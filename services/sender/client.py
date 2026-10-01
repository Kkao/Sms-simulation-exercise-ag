import asyncio

import httpx

from services.sender.config import SenderConfig
from shared import BrokerAttempt


class ClaimError(RuntimeError):
    """Claim failed; the broker may already have removed an attempt."""


class SenderClient:
    """Broker claims using a caller-owned HTTP connection pool."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: SenderConfig,
    ) -> None:
        self.client = client
        self.config = config

    async def claim(self, sender_id: str) -> BrokerAttempt | None:
        url = str(self.config.broker_url).rstrip("/") + "/messages/claim"
        try:
            async with asyncio.timeout(self.config.timeout):
                response = await self.client.post(
                    url,
                    json={"sender_id": sender_id, "message_type": "sms_message"},
                    timeout=self.config.timeout,
                )
        except (httpx.RequestError, TimeoutError) as error:
            raise ClaimError("Claim failed; assignment may be unknown") from error
        if response.status_code == 204:
            return None
        if response.status_code != 200:
            raise ClaimError(f"Broker returned HTTP {response.status_code}")
        try:
            return BrokerAttempt.model_validate_json(response.content)
        except ValueError as error:
            raise ClaimError(
                "Invalid broker attempt; assignment may be lost"
            ) from error
