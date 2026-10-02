import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from services.sender import SenderConfig
from services.sender.client import ClaimError, MetricsReportError, SenderClient
from shared import BrokerAttempt, SenderResult


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


@pytest.mark.parametrize("response_status", [200, 202])
def test_report_accepts_new_and_duplicate_responses(
    response_status: int, result: SenderResult
) -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url == "http://metrics/metrics"
            assert json.loads(request.content)["event_id"] == str(result.event_id)
            return httpx.Response(response_status)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = SenderClient(
                http, SenderConfig(metrics_url="http://metrics/metrics")
            )
            await client.report(result)

    asyncio.run(scenario())


def test_report_retries_same_event_on_transient_failure(
    result: SenderResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        requests: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content))
            return httpx.Response(503)

        wait = AsyncMock()
        monkeypatch.setattr(asyncio, "sleep", wait)
        config = SenderConfig(metrics_retries=2, retry_delay=0.25)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(MetricsReportError, match="503"):
                await SenderClient(http, config).report(result)
        assert len(requests) == 3
        assert requests[0] == requests[1] == requests[2]
        assert wait.await_count == 2

    asyncio.run(scenario())


def test_report_does_not_retry_permanent_failure(result: SenderResult) -> None:
    async def scenario() -> None:
        handler = AsyncMock(return_value=httpx.Response(422))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(MetricsReportError, match="422"):
                await SenderClient(http, SenderConfig()).report(result)
        assert handler.await_count == 1

    asyncio.run(scenario())
