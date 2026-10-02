import asyncio

import httpx

from services.sender.config import SenderConfig
from shared import BrokerAttempt, SenderResult


class ClaimError(RuntimeError):
    """Claim failed; the broker may already have removed an attempt."""


class MetricsReportError(RuntimeError):
    """A completed attempt could not be confirmed by the metrics service."""


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

    async def report(self, event: SenderResult) -> None:
        """Submit one unchanged event, retrying only transient failures."""
        payload = event.model_dump(mode="json")
        for attempt_number in range(self.config.metrics_retries + 1):
            try:
                async with asyncio.timeout(self.config.timeout):
                    response = await self.client.post(
                        str(self.config.metrics_url),
                        json=payload,
                        timeout=self.config.timeout,
                    )
            except (httpx.RequestError, TimeoutError) as error:
                if attempt_number == self.config.metrics_retries:
                    raise MetricsReportError(
                        "Metrics submission could not be confirmed"
                    ) from error
            else:
                if response.status_code in {200, 202}:
                    return
                if response.status_code not in {429, 500, 502, 503, 504}:
                    raise MetricsReportError(
                        f"Metrics service returned HTTP {response.status_code}"
                    )
                if attempt_number == self.config.metrics_retries:
                    raise MetricsReportError(
                        f"Metrics service returned HTTP {response.status_code}"
                    )
            await asyncio.sleep(self.config.retry_delay)
