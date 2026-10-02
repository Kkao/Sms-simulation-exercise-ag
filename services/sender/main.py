import argparse
import asyncio
import logging

import httpx
from pydantic import ValidationError

from services.sender.client import SenderClient
from services.sender.config import SenderConfig
from services.sender.sender import SenderServiceError, run_senders


async def run(config: SenderConfig) -> int:
    """Own the HTTP pool for the lifetime of all workers."""
    async with httpx.AsyncClient() as client:
        endpoints = SenderClient(client, config)
        return await run_senders(config, endpoints.claim, report=endpoints.report)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Simulate SMS senders")
    parser.add_argument("--sender-count", type=int, default=3)
    parser.add_argument("--mean-delay", type=float, default=0.25, help="Mean seconds")
    parser.add_argument("--failure-rate", type=float, default=0.1)
    parser.add_argument(
        "--poll-interval", type=float, default=0.1, help="Idle poll seconds"
    )
    parser.add_argument("--broker-url", default="http://127.0.0.1:8000")
    parser.add_argument("--metrics-url", default="http://127.0.0.1:8002/metrics")
    parser.add_argument(
        "--timeout", type=float, default=5.0, help="Seconds per request"
    )
    parser.add_argument("--metrics-retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=0.5)
    try:
        config = SenderConfig(**vars(parser.parse_args(argv)))
    except ValidationError as error:
        parser.error(str(error))
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run(config))
    except SenderServiceError as error:
        parser.exit(1, f"{error}\n")
    except KeyboardInterrupt:
        parser.exit(130, "Sender interrupted; claimed work may be lost; see logs\n")


if __name__ == "__main__":
    main()
