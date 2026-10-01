import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from services.sender import SenderConfig
from services.sender.client import ClaimError, SenderClient
from shared import BrokerAttempt


def test_claim_payload_and_envelope(attempt: BrokerAttempt) -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url == "http://broker/messages/claim"
            assert json.loads(request.content) == {
                "sender_id": "s",
                "message_type": "sms_message",
            }
            assert request.extensions["timeout"]["read"] == 2
            return httpx.Response(200, json=attempt.model_dump(mode="json"))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = SenderClient(
                http, SenderConfig(broker_url="http://broker", timeout=2)
            )
            assert await client.claim("s") == attempt

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status,body",
    [
        (204, ""),
        (200, "not json"),
        (200, '{"message_type":"unsupported"}'),
        (503, ""),
        (302, ""),
    ],
)
def test_claim_empty_or_invalid(status: int, body: str) -> None:
    async def scenario() -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(status, text=body)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = SenderClient(http, SenderConfig())
            if status == 204:
                assert await client.claim("s") is None
            else:
                with pytest.raises(ClaimError):
                    await client.claim("s")
            assert len(calls) == 1

    asyncio.run(scenario())


def test_claim_network_error_is_not_retried() -> None:
    async def scenario() -> None:
        handler = AsyncMock(side_effect=httpx.ReadTimeout("lost claim response"))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(ClaimError, match="unknown"):
                await SenderClient(http, SenderConfig()).claim("s")
        assert handler.await_count == 1

    asyncio.run(scenario())
