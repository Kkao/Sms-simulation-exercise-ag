# Design trade-offs

This document summarizes the current architectural trade-offs for the SMS alert
simulation. It focuses on system and service design. 

## Overall system

### Separate service processes and HTTP boundaries

- **Decision:** Run the producer, broker, sender, and metrics aggregator as
  separate local processes that communicate through HTTP APIs. Real service boundaries exercise serialization, API contracts, startup ordering, and component failure behavior while remaining runnable with
  one Python installation.

- **Accepted costs:** The system needs free ports, readiness checks, coordinated
  shutdown, HTTP clients, and more operational setup than an in-process model.

- **Alternatives:** Run the complete simulation in one Python process or use a
  production process manager or container platform.


### Simple delivery rather than guaranteed delivery

- **Decision:** Treat a successful broker claim as a destructive removal from the
  queue. Do not implement acknowledgments, leases, visibility timeouts, or broker
  recovery. 

- **Accepted costs:** A lost claim response, sender crash, or interrupted attempt
  can lose work. Delivery after a claim is effectively at-most-once; the system
  does not provide exactly-once or end-to-end at-least-once delivery.

- **Alternatives:** Acknowledged delivery with requeueing, persistent queues, or a
  managed message broker. However, this adds additional latency.
   This is something that can be added in the future to have
  more durable queues. 


## Message broker service

### Per-type `deque` queues

- **Decision:** Store pending work in a dictionary of `deque` instances keyed by
  validated message type, creating a queue on first use. However, the benefit of keying
  the queue is that the message broker can easily support other types of producer
  events in the future. 

- **Accepted costs:** One more layer of abstraction to track and manage.

- **Alternatives:** One mixed queue, scanning for compatible messages, or a
  thread-safe `queue.Queue` per type.



### Short polling

- **Decision:** Respond immediately to an empty claim and let each sender wait for
  its configured poll interval before trying again. 

- **Accepted costs:** Senders will continuously ping the message broker service for
any messages. Idle request volume is approximately sender count divided by
  poll interval. However, these are all simple requests that are very quick for the 
  message broker to respond.

- **Alternatives:** Long polling, streaming assignment, or push delivery. All of the alternatives
reduce the amount of API calls the sender service has to make to the message broker.


## Sender service

### Async workers with one attempt each

- **Decision:** Run a configurable number of asyncio workers. Each worker claims
  and completes one attempt before claiming another. The simulated waits are I/O-like, and the worker count directly
  represents the maximum processing concurrency.However, if each sender has a 
  lot of CPU-bound work, then this async process will need to be updated

- **Accepted costs:** Per-worker throughput is sequential, and all workers in a CLI
  process share the same simulation settings.

- **Alternatives:** Threads, processes, multiple in-flight attempts per worker, or
  a shared central dispatcher.

### Independent worker claims

- **Decision:** Let each idle worker claim directly through a shared HTTP client
  pool rather than using a central dispatcher. The logic is simpler and less coordination
  is required for the main sender service.

- **Accepted costs:** Idle workers poll independently. A dispatcher could reduce polling but
  local prefetching would increase work lost on a sender-process crash.

- **Alternatives:** A dispatcher that reserves workers, claims centrally, and
  assigns attempts from a local buffer.


### Sender-calculated end-to-end latency

- **Decision:** Calculate `total_latency_ms` at completion from the message's UTC
  `created_at` and the sender's UTC completion time. Keep the field optional for
  compatibility with older clients and stored rows.

- **Accepted costs:** Unlike processing duration, total latency uses wall clocks
  across components and therefore depends on clock synchronization. Older events
  do not contribute latency samples.

- **Alternatives:** Persist source timestamps and calculate latency in queries,
  calculate it in the broker, or require the field in a new schema version.

## Metrics aggregator service

### Per-operation connections and transactions

- **Decision:** Open, configure, transact with, and close a SQLite connection for
  each repository operation. Enable WAL and a bounded busy timeout.
  One request cannot accidentally commit or roll back another
  request's work, while WAL lets dashboard reads overlap ingestion. For this simulation, 
  the metrics are only appended and we never need to update preexisting logs. 

- **Accepted costs:** Connection setup adds overhead, writers can still wait, and
  private `:memory:` databases are incompatible because connections would not
  share their data.

- **Alternatives:** One cross-thread connection behind a lock, connection pooling,
  or an asynchronous database library.


