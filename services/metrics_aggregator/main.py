"""Run the SQLite-backed metrics API and live dashboard."""

import argparse
from pathlib import Path

import uvicorn

from services.metrics_aggregator.api import create_app
from shared.logging import suppress_routine_request_logs


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the SMS metrics aggregator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument(
        "--database",
        type=Path,
        help="SQLite path (defaults to METRICS_DB_PATH or metrics.sqlite3)",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    suppress_routine_request_logs()
    app = create_app(database_path=args.database)
    uvicorn.run(app, host=args.host, port=args.port, workers=1, reload=False)


if __name__ == "__main__":
    main()
