# Sms-simulation-exercise-ag

**This repository and code was written with the help of Codex GPT AI.**

## Project structure

```text
services/
    producer/             # Message generation and production rate control
        tests/            # Producer unit tests
    message_broker/       # Queuing and attempt coordination
        tests/            # Message broker unit tests
    sender/               # Simulated delivery, delays, and failures
        tests/            # Sender unit tests
    metrics_aggregator/   # FastAPI metrics API and SQLite persistence
        tests/            # Metrics aggregator unit tests
shared/                   # Common message schemas and validation
    tests/                # Shared schema and validation unit tests
```

Each service has its own Python package under `services/`. Keep service-specific
logic in that package and common message contracts in `shared/`. Services should
communicate through their documented interfaces instead of importing another
service's internal implementation.

Unit tests live alongside the package they exercise. 

Shared message contracts and all four application services are implemented. The
metrics aggregator persists sender results in SQLite, exposes query APIs, and serves
a live browser dashboard. Graceful broker lifecycle handling is still pending. See
[DESIGN.md](DESIGN.md) for system requirements and message contracts, and
[AGENTS.md](AGENTS.md) for development and testing guidance.

## Local setup

Use Python 3.12 or newer. From the repository root on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe
```

The final command opens a Python prompt for the example below.

## Development checks

Install the development dependencies from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Format all Python code with Ruff, or check formatting without changing files:

```powershell
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Run Ruff's lint checks separately:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
```

On macOS/Linux, create the environment with `python3 -m venv .venv`, then use
`./.venv/bin/python` in place of `.\.venv\Scripts\python.exe` in the commands
above and below.

After installing development dependencies, run tests from the repository root:

```powershell
# Unit tests
.\.venv\Scripts\python.exe -m pytest services shared

# All tests
.\.venv\Scripts\python.exe -m pytest
```

Pytest creates temporary test databases in a unique, ignored `.pytest-tmp-*/`
directory at the repository root and removes that directory after the run. Unique
directories prevent permission collisions when tests run under different Windows
security contexts. An explicit `--basetemp` option overrides this behavior.

## Run the complete simulation

Start the broker, metrics API, senders, and producer together from the repository
root with one command:

```powershell
.\.venv\Scripts\python.exe run_simulation.py
```

The launcher waits for both APIs to become healthy, records the metrics database's
initial event count, starts senders, and then runs the producer. After every newly
produced message has a stored sender result, it prints the metrics summary and stops
all child processes. Existing events in `metrics.sqlite3` are preserved and do not
count toward the current run's completion.

For a quick deterministic smoke run with a separate database:

```powershell
.\.venv\Scripts\python.exe run_simulation.py --count 20 --rate 100 --mean-delay 0 --failure-rate 0 --database smoke-metrics.sqlite3
```

Use `--keep-running` to leave the broker, sender, metrics API, and dashboard running
after the finite producer completes. The dashboard is then available at
[http://127.0.0.1:8002/](http://127.0.0.1:8002/); press Ctrl+C in the launcher to
stop every child process. `--broker-port` and `--metrics-port` change the local
ports, and `--capacity` changes the broker's shared queue capacity. The launcher
rejects occupied or duplicate ports and requires the first atomic producer batch
to fit within the broker capacity. Run `python run_simulation.py --help` for all
producer, sender, lifecycle, database, and timeout options.

The default 300-second completion timeout covers production and delivery together.
If startup, production, or delivery fails, the launcher reports the failing phase,
stops every process it started, and exits nonzero. The SQLite database remains on
disk; delete it while the services are stopped when a fresh metrics history is
preferred.

## Run the metrics aggregator and dashboard

Start the aggregator before the sender. From the repository root:

```powershell
.\.venv\Scripts\python.exe -m services.metrics_aggregator.main
```

Open the [live metrics dashboard](http://127.0.0.1:8002/). It refreshes summary
totals and the 25 newest attempts once per second without reloading the page.
Interactive API documentation is available at
[http://127.0.0.1:8002/docs](http://127.0.0.1:8002/docs).

By default, events persist in `metrics.sqlite3` in the current directory. Choose a
different database with `--database C:\path\to\metrics.sqlite3` or the
`METRICS_DB_PATH` environment variable; the CLI option takes precedence. `--host`
defaults to `127.0.0.1`, and `--port` defaults to `8002`. Stop the service with
Ctrl+C. Each API operation opens a configured SQLite connection and closes it after
committing or rolling back its transaction. Delete the selected database file while
the service is stopped to reset all metrics.

| Endpoint | Purpose |
| --- | --- |
| `POST /metrics` | Validate and store a `SenderResult`; returns `202 accepted` or `200 duplicate` for an existing `event_id` |
| `GET /metrics` | List newest events with `status`, `sender_id`, `limit` (1–1000), and `offset` filters |
| `GET /metrics/summary` | Return sent, failed, failure rate, average, P90, and P99 processing time, sender count, and latest event time |
| `GET /health` | Check API/database access and return the stored event count |
| `GET /` | Display the live dashboard |

An `event_id` is stored once. Repeating that ID is acknowledged as a duplicate and
does not change totals, even if the later payload differs. Events are ordered by
their UTC `occurred_at` timestamp and then event ID. The dashboard uses short
polling, so live updates normally appear within one second.

P90 and P99 use the nearest-rank definition: durations are sorted ascending and
ranks `ceil(0.90 × event count)` and `ceil(0.99 × event count)` are selected. An
empty data set reports zero milliseconds for both.

## Run the sender

Start the broker and metrics aggregator first, then run the sender in another
terminal. Each completed `SenderResult` is persisted by the aggregator and also
logged as JSON at INFO level.

```powershell
.\.venv\Scripts\python.exe -m services.sender.main --sender-count 3 --mean-delay 0.25 --failure-rate 0.1
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--sender-count` | `3` | Positive number of concurrent individual senders |
| `--mean-delay` | `0.25` | Finite nonnegative mean delay in seconds; waits are uniform from zero to twice this value |
| `--failure-rate` | `0.1` | Probability per attempt, from zero (always sent) to one (always failed) |
| `--poll-interval` | `0.1` | Positive finite seconds between empty claims |
| `--broker-url` | `http://127.0.0.1:8000` | Broker base URL |
| `--metrics-url` | `http://127.0.0.1:8002/metrics` | Full metrics ingestion URL |
| `--timeout` | `5` | Positive finite total timeout per HTTP request |
| `--metrics-retries` | `3` | Nonnegative number of retries after a transient metrics failure |
| `--retry-delay` | `0.5` | Positive finite seconds between metrics retries |

Worker IDs use the fixed prefix `sms-sender`: `sms-sender-1`, `sms-sender-2`, etc.
IDs restart from one in each process, so they do not distinguish separate processes.
All senders in a CLI process use the configured delay and failure rate. Each has
one attempt in flight and its own random generator. Delivery is simulated only.
Durations use a monotonic clock and include the actual wait; completion timestamps
use UTC. Failed simulated sends emit
`SIMULATED_SEND_FAILURE` and are not retried as new delivery attempts.

Ctrl+C cancels workers, closes the HTTP pool, and exits with code 130. Logs identify
known interrupted attempts. Claimed work may be lost,
including a claim whose response never arrived. The sender creates no files and
requires no environment variables. No sender-specific cleanup is needed.

## Run the producer

The Python API is `produce(config, submit, *, submit_batch=None, rng=None)`.
It uses `asyncio.sleep` and the monotonic clock internally, along with
`generate_message()`'s UUID and UTC timestamp defaults; `produce()` no longer
accepts `sleep`, `monotonic`, `id_factory`, or `utc_now` arguments.

`services.producer.client.BrokerClient(client, config)` uses `asyncio.sleep`
internally for queue-full retry delays. It no longer accepts a sleep callback;
tests patch the client module's sleep import to keep retry checks deterministic.

Start the broker as described below, then use a second terminal:

```powershell
.\.venv\Scripts\python.exe -m services.producer.main --count 100 --rate 20 --body-length 80
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--count` | `1000` | Nonnegative number of messages; zero is a no-op |
| `--batch-size` | `1` | Messages per request, from 1 to 1000; values above 1 use `/messages/batch` |
| `--body-length` | `100` | Exact length of each random body, from 0 to 100 characters |
| `--rate` | `10` | Positive, finite target messages per second |
| `--broker-url` | `http://127.0.0.1:8000` | HTTP(S) broker base URL |
| `--timeout` | `5` | Positive, finite timeout in seconds for each HTTP request |
| `--max-retries` | `3` | Nonnegative number of additional queue-full submission attempts |

The first submission starts immediately. Later starts are spaced by
at least `batch_size/rate` seconds using a monotonic clock, accounting for request time.
Slow requests and backpressure reduce throughput; there are no catch-up bursts
or waits after the final confirmed submission.

`--count` always counts SMS messages and `--rate` always means messages per
second. Batches arrive as bursts. A final batch may contain fewer messages to
reach the exact count; it still uses `/messages/batch`, even if it contains one
message. The default batch size of 1 keeps single-message requests to `/messages`.

To send **two requests of five messages, one second apart**, start a fresh broker
in one terminal:

```powershell
.\.venv\Scripts\python.exe -m services.message_broker.main --port 8001 --capacity 10
```

In another terminal, run the producer and check the queue:

```powershell
.\.venv\Scripts\python.exe -m services.producer.main --broker-url http://127.0.0.1:8001 --count 10 --batch-size 5 --rate 5
Invoke-RestMethod http://127.0.0.1:8001/health
```

Expect `Confirmed 10 messages with the broker` and `pending_messages: 10` when
the broker starts empty and no senders claim messages. Request starts target
one-second spacing; slow requests and queue-full retries can increase it.

Ctrl+C closes the HTTP client and exits with code 130. No producer files or durable
checkpoints are written. The Python API exposes the failed payload as
`ProductionError.messages` (a tuple of all unconfirmed messages), the first
unconfirmed message as `ProductionError.message`, and confirmed message count as
`ProductionError.completed`;
rerunning the CLI creates new IDs and does not resume failed work. The producer
uses CLI settings, with no required environment variables. Without senders draining
the queue, runs beyond remaining broker capacity will exhaust retries. Broker
admission does not mean delivery has completed.

## Run the broker API

Install the updated dependencies, then start the broker from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m services.message_broker.main
```

The `services/message_broker/main.py` entry point creates a fresh, empty broker
and serves it on `127.0.0.1:8000`. It uses one worker and disables automatic reload
so all requests share the same broker queues. It also enables INFO-level dispatch logs.
Importing the module does not start a server.

To choose another port or queue capacity:

```powershell
.\.venv\Scripts\python.exe -m services.message_broker.main --port 8001 --capacity 50
```

The port must be between 1 and 65535. `--capacity` must be a positive integer and
overrides the optional `BROKER_QUEUE_CAPACITY` environment variable; otherwise
capacity defaults to 1000 and limits the total pending messages across all type
queues. Stop the server with Ctrl+C; queued messages and
duplicate records will be lost. Graceful draining and recovery are not implemented.

Open [interactive API docs](http://127.0.0.1:8000/docs) to submit example payloads
and inspect responses. The OpenAPI schema is at `/openapi.json`.

| Endpoint | Request | Responses |
| --- | --- | --- |
| `POST /messages` | SMS JSON from `DESIGN.md`, including `"message_type": "sms_message"` | `202` with `status` (`accepted` or `duplicate`), `message_id`, and `message_type`; `409` for conflicting content; `503` when full |
| `POST /messages/batch` | JSON array of 1–1000 SMS messages | `202` with an array of receipts in input order; `409` for conflicting content; `503` if all new messages cannot fit; `422` for invalid payloads |
| `POST /messages/claim` | `{"sender_id": "sender-1", "message_type": "sms_message"}` | `200` with the documented attempt envelope; `204` with no body when no matching message is available |
| `GET /health` | None | `200` with `{"status": "ok", "pending_messages": 0}` |

Routine `204 No Content` responses from empty claims are omitted from both the
broker access log and the sender HTTP client log. Other HTTP responses remain logged.
The metrics service also omits the dashboard's routine `GET /metrics/summary` and
`GET /metrics?limit=25` polling requests from its access log.

Batch admission is all-or-nothing. Invalid messages, conflicting reuse of an ID
(including within the batch), or insufficient capacity leave the queue and
duplicate records unchanged. Only distinct new messages consume capacity. Repeated
identical items receive `duplicate` receipts; the first new occurrence receives
`accepted`. New messages retain array order within their type's FIFO queue, after
previously queued work. Retrying the unchanged array will not enqueue duplicates
while the broker retains its in-memory records. If a batch exceeds the broker's
total capacity, split it into smaller batches; waiting alone cannot make it fit.

For example, with the broker running, submit an array from Python:

```python
import asyncio

import httpx

from services.producer import generate_message


async def submit_batch():
    messages = [generate_message().model_dump(mode="json") for _ in range(50)]
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            "http://127.0.0.1:8000/messages/batch", json=messages
        )
        response.raise_for_status()
        print(response.json())


asyncio.run(submit_batch())
```
