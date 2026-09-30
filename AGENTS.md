# Project guidance

## Purpose and scope

This project is a Python SMS alert simulation system. Read `README.md` and
`DESIGN.md` before changing behavior or message contracts. The repository currently
contains design documentation and package scaffolding; the application and test
infrastructure still need to be implemented. Keep each service in its own package
under `services/` and common schemas in `shared/`. Keep unit tests alongside the
code in `services/<service>/tests/` and `shared/tests/`. Keep integration tests
at the repository root under `tests/integration/`.

All application services and test code must be written in Python. The planned
components are:

- **Producer:** generates configurable SMS messages and controls production rate.
- **Message broker:** uses Python's standard-library `collections.deque` in a single
  broker process to queue messages and assign work when senders poll its API.
  Route validated messages into queues keyed by message type; claims select the
  requested type's queue. Preserve FIFO within each queue and enforce one capacity
  limit across all pending messages.
  Access broker state only from one event-loop thread. All `async def` API
  handlers must call synchronous broker methods directly, without yielding during
  state updates or offloading broker access to a thread pool. Enforce queue capacity
  explicitly; do not use `deque(maxlen=...)`, which silently discards older work.
- **Senders:** simulate configurable processing delays and failure rates.
- **Metrics aggregator:** exposes a FastAPI API and persists metrics in SQLite.

Keep SMS delivery simulated. Do not introduce a real SMS provider unless requested.
Keep local setup limited to Python and Python packages; do not require a separate
messaging server or container runtime. The broker queue is in memory and loses
queued work on restart. Persistence, acknowledgments, retries, and recovery of
interrupted attempts require explicit application logic if implemented.

## Protected files

- Treat DESIGN.md as read-only. Do not edit, reformat, rename, or delete it.
- Requests to implement features or update documentation do not authorize
  changes to DESIGN.md.
- Only modify DESIGN.md when the user explicitly requests changes to that file.
- Put implementation details in README.md and decisions in TRADEOFFS.md.
- This restriction takes precedence over general documentation-update guidance.
- Before completing work, verify you introduced no changes to DESIGN.md.
  Preserve any pre-existing user changes.

## Python development

- Install Python packages only into the project's `.venv` virtual environment.
  Reuse it if present; otherwise create it with `python -m venv .venv` before
  installing packages. Use its interpreter explicitly:
  `.\.venv\Scripts\python.exe -m pip install ...` on Windows or
  `./.venv/bin/python -m pip install ...` on macOS/Linux. Do not install project
  dependencies globally or with `--user`, and do not rely on a bare `pip` command
  selecting the correct environment. Use the same virtual environment to run
  services and tests.
- Declare runtime and development dependencies in `pyproject.toml`. Document the
  supported Python version and installation commands in `README.md`.
- Keep service responsibilities separate. Share message schemas and validation
  rather than duplicating them across services.
- Use type hints for public functions and data models, clear names, and small,
  focused functions. Prefer straightforward implementations over speculative abstractions.
- Keep source and test files small and focused on one responsibility. When a file
  becomes difficult to navigate or mixes concerns, split it into cohesive modules
  before adding more code. Separate API handling, business logic, and persistence
  as they grow. Use readability and cohesion to guide file size rather than a rigid
  line limit.
- Keep code maintainable with clear interfaces, minimal nesting, and explicit
  dependencies. Remove duplication when a shared abstraction has a clear purpose,
  and avoid unnecessary layers or overly fragmented modules. Update relevant tests
  when refactoring.
- Validate configuration at startup, including message counts, body lengths,
  production rates, sender counts, delay settings, and failure probabilities.
- Make randomness, clocks, delays, and external clients injectable so behavior can
  be tested deterministically. Use UTC for event timestamps and a monotonic clock
  for elapsed durations.
- Preserve the documented schema versions and identifiers. Retries must preserve
  message IDs and message types while creating new attempt metadata. Deduplicate
  repeated metric submissions using their event IDs.
- Handle failures explicitly, use bounded timeouts, and close connections and
  database resources during shutdown. Do not silently discard failed work.
- Keep credentials out of source control. Document environment variables and
  provide safe example configuration as needed.

## Required tests

Use `pytest` for both unit and integration tests. Keep unit tests in each service's
`tests/` folder and in `shared/tests/`, and integration tests in
`tests/integration/` so the suites can run independently. Add relevant tests with
new behavior and regression tests with bug fixes. When configuring pytest, use
`--import-mode=importlib` to avoid collisions between test modules with the same
filename in different service folders.

### Unit tests

- Test individual functions and components without running service processes,
  external network access, or persistent shared state.
- Replace external boundaries with fakes or mocks. Control random values, clocks,
  and waiting; avoid real sleeps and assertions that depend on chance.
- Cover message generation and length limits, schema validation, configuration
  boundaries, rate and delay calculations, success and failure outcomes, attempt
  metadata, and metrics calculations as those features are implemented.
- Include invalid inputs and boundary cases, including failure probabilities of
  zero and one. Assert observable behavior rather than private implementation details.

### Integration tests

- Exercise component interactions with real implementations: broker enqueueing
  and sender polling, API request/response boundaries, and SQLite persistence
  and queries. Use temporary databases and a fresh in-memory queue for each test.
- Include a small end-to-end simulation from producer through broker and sender to
  stored, queryable metrics. Verify message types, message IDs, and outcome totals.
- Test duplicate metric events and, when implemented, application-managed retries
  and recovery of interrupted attempts without double-counting completed attempts.
- Provision test dependencies explicitly and clean up resources even after failures.
  Never connect tests to production infrastructure.
- Use readiness checks and bounded polling for asynchronous results instead of
  arbitrary sleeps. Keep workloads small and deterministic.
- Fail with a clear diagnostic when required integration infrastructure is missing;
  do not silently skip the required suite in CI.

## Tracking trade-offs

Record design and implementation trade-offs in [TRADEOFFS.md](TRADEOFFS.md).
Read existing entries before changing a related decision, and update the file as
part of any change that introduces or revises a trade-off.

For each entry, describe the decision, the alternatives considered, why the chosen
approach fits this project, and the limitations or costs accepted. Note the
conditions that would justify revisiting the decision. Keep entries concise and
grouped by component. When a decision changes, mark the earlier choice as
superseded and explain its replacement so the reasoning remains traceable.

## Validation and completion

Once the test infrastructure exists, support these commands from the repository root:

```sh
python -m pytest --import-mode=importlib services shared
python -m pytest --import-mode=importlib tests/integration
python -m pytest --import-mode=importlib
```

Document Python dependency installation, service startup, test configuration, and cleanup
in `README.md`. Configure CI to run both suites with the required services. Run
checks relevant to each change, including both suites for changes spanning services.
Report which checks passed and any checks that could not run, with the reason.

Keep changes focused and preserve unrelated work. Update documentation when setup,
configuration, public APIs, or message contracts change. Do not claim tests passed
unless they were actually executed successfully.
