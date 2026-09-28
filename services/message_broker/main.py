"""Run a fresh message broker for local API use."""

import argparse
import logging

import uvicorn

from services.message_broker.api import create_app


def main() -> None:
    """Start one broker on localhost, with interactive API docs at /docs."""
    parser = argparse.ArgumentParser(description="Run the local SMS message broker")
    parser.add_argument(
        "--port", type=int, default=8000, help="HTTP port (default: 8000)"
    )
    parser.add_argument(
        "--capacity",
        type=int,
        help="Queue capacity (defaults to BROKER_QUEUE_CAPACITY, or 1000)",
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.capacity is not None and args.capacity < 1:
        parser.error("--capacity must be a positive integer")

    logging.basicConfig(level=logging.INFO)
    app = create_app(capacity=args.capacity)
    logging.getLogger(__name__).info(
        "Interactive API docs: http://127.0.0.1:%s/docs", args.port
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1, reload=False)


if __name__ == "__main__":
    main()
