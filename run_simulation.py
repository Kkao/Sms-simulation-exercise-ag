r"""Launch the complete local SMS simulation from one Python script.

The launcher performs these steps:

1. Validate the settings and confirm that the selected ports are available.
2. Start the message broker and wait until its health check succeeds.
3. Start the metrics service and record how many results already exist.
4. Start the senders, followed by the producer that creates the SMS messages.
5. Wait for the producer to finish and for every new message to have a result.
6. Print the metrics summary and stop all services, unless ``--keep-running``
   was requested.

If any step fails or the user presses Ctrl+C, all processes started by this
launcher are stopped before it exits.

Run this file from the project root with the project's virtual environment:

    .\.venv\Scripts\python.exe run_simulation.py

Use ``--help`` to see every setting. Add ``--keep-running`` to leave the services
and metrics dashboard running until Ctrl+C is pressed. For example:

    .\.venv\Scripts\python.exe run_simulation.py --count 100 --keep-running

With ``--keep-running`` active, you can open the dashboard in the browser as well
The default url for the dashboard is http://127.0.0.1:8002/
"""

from __future__ import annotations

import argparse
import json
import math
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

POLL_INTERVAL_SECONDS = 0.1
SHUTDOWN_TIMEOUT_SECONDS = 5.0


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return parsed


def _port(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the broker, metrics API, senders, and producer end to end"
    )
    parser.add_argument("--count", type=_nonnegative_int, default=1000)
    parser.add_argument("--batch-size", type=_positive_int, default=1)
    parser.add_argument("--body-length", type=_nonnegative_int, default=100)
    parser.add_argument("--rate", type=float, default=10.0)
    parser.add_argument("--sender-count", type=_positive_int, default=3)
    parser.add_argument("--mean-delay", type=float, default=0.25)
    parser.add_argument("--failure-rate", type=float, default=0.1)
    parser.add_argument("--poll-interval", type=float, default=0.1)
    parser.add_argument("--request-timeout", type=float, default=5.0)
    parser.add_argument("--max-retries", type=_nonnegative_int, default=3)
    parser.add_argument("--metrics-retries", type=_nonnegative_int, default=3)
    parser.add_argument("--retry-delay", type=float, default=0.5)
    parser.add_argument("--capacity", type=_positive_int, default=1000)
    parser.add_argument("--broker-port", type=_port, default=8000)
    parser.add_argument("--metrics-port", type=_port, default=8002)
    parser.add_argument("--database", type=Path, default=Path("metrics.sqlite3"))
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=15.0,
        help="Seconds allowed for each API to become healthy (default: 15)",
    )
    parser.add_argument(
        "--completion-timeout",
        type=float,
        default=300.0,
        help="Seconds allowed for production and delivery (default: 300)",
    )
    parser.add_argument(
        "--keep-running",
        action="store_true",
        help="Keep APIs and senders running after completion until Ctrl+C",
    )
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.batch_size > 1000:
        parser.error("--batch-size must be at most 1000")
    if args.body_length > 100:
        parser.error("--body-length must be at most 100")
    if not math.isfinite(args.rate) or args.rate <= 0:
        parser.error("--rate must be positive")
    if not math.isfinite(args.mean_delay) or args.mean_delay < 0:
        parser.error("--mean-delay must be nonnegative")
    if not math.isfinite(args.failure_rate) or not 0 <= args.failure_rate <= 1:
        parser.error("--failure-rate must be between 0 and 1")
    if not math.isfinite(args.poll_interval) or args.poll_interval <= 0:
        parser.error("--poll-interval must be positive")
    if not math.isfinite(args.request_timeout) or args.request_timeout <= 0:
        parser.error("--request-timeout must be positive")
    if not math.isfinite(args.retry_delay) or args.retry_delay <= 0:
        parser.error("--retry-delay must be positive")
    if not math.isfinite(args.startup_timeout) or args.startup_timeout <= 0:
        parser.error("--startup-timeout must be positive")
    if not math.isfinite(args.completion_timeout) or args.completion_timeout <= 0:
        parser.error("--completion-timeout must be positive")
    if args.broker_port == args.metrics_port:
        parser.error("--broker-port and --metrics-port must differ")
    if args.count and min(args.count, args.batch_size) > args.capacity:
        parser.error("the broker capacity must fit the first producer batch")


def _ensure_port_available(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as error:
            raise RuntimeError(f"port {port} is already in use") from error


def _start(name: str, arguments: list[str]) -> subprocess.Popen[Any]:
    command = [sys.executable, "-m", *arguments]
    options: dict[str, Any] = {}
    if os.name == "nt":
        # If OS is windows
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        # Linux or MacOS
        options["start_new_session"] = True
    print(f"Starting {name}: {' '.join(command)}", flush=True)
    return subprocess.Popen(command, **options)


def _read_json(url: str, timeout: float = 1.0) -> dict[str, Any]:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - localhost only
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object from {url}")
    return payload


def _wait_for_health(
    name: str,
    process: subprocess.Popen[Any],
    url: str,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(f"{name} exited during startup with code {exit_code}")
        try:
            payload = _read_json(url)
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            last_error = error
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        if process.poll() is None:
            print(f"{name.capitalize()} is ready", flush=True)
            return payload
    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(f"timed out waiting for {name} at {url}{detail}")


def _wait_for_process(
    name: str, process: subprocess.Popen[Any], deadline: float
) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError(f"timed out waiting for {name}")
    try:
        exit_code = process.wait(timeout=remaining)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"timed out waiting for {name}") from error
    if exit_code != 0:
        raise RuntimeError(f"{name} exited with code {exit_code}")


def _wait_for_completion(
    *,
    processes: dict[str, subprocess.Popen[Any]],
    broker_health_url: str,
    metrics_health_url: str,
    initial_event_count: int,
    message_count: int,
    deadline: float,
) -> None:
    expected_event_count = initial_event_count + message_count
    last_state = "no health response"
    while time.monotonic() < deadline:
        for name in ("broker", "metrics", "sender"):
            exit_code = processes[name].poll()
            if exit_code is not None:
                raise RuntimeError(f"{name} exited unexpectedly with code {exit_code}")
        try:
            broker = _read_json(broker_health_url)
            metrics = _read_json(metrics_health_url)
            pending = int(broker["pending_messages"])
            stored = int(metrics["stored_events"])
            last_state = f"pending messages={pending}, stored events={stored}"
            if pending == 0 and stored >= expected_event_count:
                return
        except (HTTPError, URLError, TimeoutError, KeyError, TypeError, ValueError):
            pass
        time.sleep(POLL_INTERVAL_SECONDS)
    raise RuntimeError(f"timed out waiting for delivery ({last_state})")


def _stop_processes(processes: list[tuple[str, subprocess.Popen[Any]]]) -> None:
    for name, process in reversed(processes):
        if process.poll() is None:
            print(f"Stopping {name}", flush=True)
            process.terminate()
    for name, process in reversed(processes):
        if process.poll() is not None:
            continue
        try:
            process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            print(f"Killing unresponsive {name}", file=sys.stderr, flush=True)
            process.kill()
            process.wait()


def run(args: argparse.Namespace) -> int:
    _ensure_port_available(args.broker_port)
    _ensure_port_available(args.metrics_port)

    broker_url = f"http://127.0.0.1:{args.broker_port}"
    metrics_url = f"http://127.0.0.1:{args.metrics_port}"
    database = args.database.resolve()
    started: list[tuple[str, subprocess.Popen[Any]]] = []
    by_name: dict[str, subprocess.Popen[Any]] = {}

    try:
        broker = _start(
            "broker",
            [
                "services.message_broker.main",
                "--port",
                str(args.broker_port),
                "--capacity",
                str(args.capacity),
            ],
        )
        started.append(("broker", broker))
        by_name["broker"] = broker
        _wait_for_health("broker", broker, f"{broker_url}/health", args.startup_timeout)

        metrics = _start(
            "metrics",
            [
                "services.metrics_aggregator.main",
                "--port",
                str(args.metrics_port),
                "--database",
                str(database),
            ],
        )
        started.append(("metrics", metrics))
        by_name["metrics"] = metrics
        metrics_health = _wait_for_health(
            "metrics", metrics, f"{metrics_url}/health", args.startup_timeout
        )
        initial_event_count = int(metrics_health["stored_events"])

        sender = _start(
            "sender",
            [
                "services.sender.main",
                "--sender-count",
                str(args.sender_count),
                "--mean-delay",
                str(args.mean_delay),
                "--failure-rate",
                str(args.failure_rate),
                "--poll-interval",
                str(args.poll_interval),
                "--broker-url",
                broker_url,
                "--metrics-url",
                f"{metrics_url}/metrics",
                "--timeout",
                str(args.request_timeout),
                "--metrics-retries",
                str(args.metrics_retries),
                "--retry-delay",
                str(args.retry_delay),
            ],
        )
        started.append(("sender", sender))
        by_name["sender"] = sender

        producer = _start(
            "producer",
            [
                "services.producer.main",
                "--count",
                str(args.count),
                "--batch-size",
                str(args.batch_size),
                "--body-length",
                str(args.body_length),
                "--rate",
                str(args.rate),
                "--broker-url",
                broker_url,
                "--timeout",
                str(args.request_timeout),
                "--max-retries",
                str(args.max_retries),
            ],
        )
        started.append(("producer", producer))
        by_name["producer"] = producer

        deadline = time.monotonic() + args.completion_timeout
        _wait_for_process("producer", producer, deadline)
        _wait_for_completion(
            processes=by_name,
            broker_health_url=f"{broker_url}/health",
            metrics_health_url=f"{metrics_url}/health",
            initial_event_count=initial_event_count,
            message_count=args.count,
            deadline=deadline,
        )
        summary = _read_json(f"{metrics_url}/metrics/summary")
        print("Simulation complete", flush=True)
        print(json.dumps(summary, indent=2), flush=True)
        if args.keep_running:
            print(f"Dashboard: {metrics_url}/ (press Ctrl+C to stop)", flush=True)
            while True:
                for name in ("broker", "metrics", "sender"):
                    exit_code = by_name[name].poll()
                    if exit_code is not None:
                        raise RuntimeError(
                            f"{name} exited unexpectedly with code {exit_code}"
                        )
                time.sleep(1)
        return 0
    finally:
        _stop_processes(started)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("Simulation interrupted", file=sys.stderr)
        return 130
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as error:
        print(f"Simulation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
