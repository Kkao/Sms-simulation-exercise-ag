import asyncio
from collections.abc import Awaitable, Callable

import httpx

from services.producer.config import ProducerConfig
from shared import SmsMessage


class SubmissionError(RuntimeError):
    """The broker did not confirm admission of a message."""


class BrokerClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        config: ProducerConfig,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.client = client
        self.config = config
        self.sleep = sleep

    async def submit(self, message: SmsMessage) -> None:
        """Confirm admission, retrying only explicit queue-full responses."""
        receipt = await self._post("/messages", message.model_dump(mode="json"))
        self._validate_receipt(receipt, message)

    async def submit_batch(self, messages: list[SmsMessage]) -> None:
        """Confirm every ordered receipt; retry queue-full with the same payload."""
        if not 1 <= len(messages) <= 1000:
            raise ValueError("batch must contain 1 to 1000 messages")
        receipts = await self._post(
            "/messages/batch", [message.model_dump(mode="json") for message in messages]
        )
        if not isinstance(receipts, list) or len(receipts) != len(messages):
            raise SubmissionError("Invalid broker batch admission receipt")
        for receipt, message in zip(receipts, messages, strict=True):
            self._validate_receipt(receipt, message)

    async def _post(self, path: str, payload: dict | list[dict]) -> object:
        url = str(self.config.broker_url).rstrip("/") + path
        for retry in range(self.config.max_retries + 1):
            try:
                async with asyncio.timeout(self.config.timeout):
                    response = await self.client.post(
                        url,
                        json=payload,
                        timeout=self.config.timeout,
                    )
            except (httpx.RequestError, TimeoutError) as error:
                raise SubmissionError(
                    "Broker request failed; admission may be unknown"
                ) from error

            if response.status_code == 202:
                try:
                    return response.json()
                except ValueError as error:
                    raise SubmissionError("Invalid broker admission receipt") from error
            if response.status_code != 503:
                raise SubmissionError(f"Broker returned HTTP {response.status_code}")
            if retry == self.config.max_retries:
                raise SubmissionError("Broker queue remained full; retries exhausted")
            # The broker contract specifies Retry-After: 1. Accept bounded integer
            # overrides, but fail explicitly rather than retrying too early.
            try:
                delay = int(response.headers.get("Retry-After", "1"))
                if not 0 <= delay <= 60:
                    raise ValueError
            except ValueError as error:
                raise SubmissionError("Unsupported broker Retry-After value") from error
            await self.sleep(max(1, delay))

    @staticmethod
    def _validate_receipt(receipt: object, message: SmsMessage) -> None:
        if (
            not isinstance(receipt, dict)
            or receipt.get("status") not in ("accepted", "duplicate")
            or receipt.get("message_id") != str(message.message_id)
            or receipt.get("message_type") != message.message_type
        ):
            raise SubmissionError("Invalid broker admission receipt")
