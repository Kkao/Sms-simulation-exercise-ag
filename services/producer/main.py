import argparse
import asyncio

import httpx
from pydantic import ValidationError

from services.producer.client import BrokerClient
from services.producer.config import ProducerConfig
from services.producer.producer import ProductionError, produce


async def run(config: ProducerConfig) -> int:
    """Own and close the HTTP connection pool on success, error, or cancellation."""
    async with httpx.AsyncClient() as client:
        broker = BrokerClient(client, config)
        return await produce(config, broker.submit, submit_batch=broker.submit_batch)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate simulated SMS messages")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Messages per request (1-1000); values above 1 use /messages/batch",
    )
    parser.add_argument("--body-length", type=int, default=100)
    parser.add_argument("--rate", type=float, default=10.0, help="Messages per second")
    parser.add_argument("--broker-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--timeout", type=float, default=5.0, help="Seconds per request"
    )
    parser.add_argument("--max-retries", type=int, default=3, help="Queue-full retries")
    try:
        config = ProducerConfig(**vars(parser.parse_args(argv)))
    except ValidationError as error:
        parser.error(str(error))
    try:
        completed = asyncio.run(run(config))
    except ProductionError as error:
        parser.exit(1, f"{error}\n")
    except KeyboardInterrupt:
        parser.exit(130, "Producer interrupted; pending admission may be unknown\n")
    print(f"Confirmed {completed} messages with the broker")


if __name__ == "__main__":
    main()
