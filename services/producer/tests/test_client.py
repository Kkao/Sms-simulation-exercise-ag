import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from services.producer import ProducerConfig
from services.producer.client import BrokerClient, SubmissionError
from shared import SmsMessage


def message(number: int = 1, body: str = "") -> SmsMessage:
    return SmsMessage(
        schema_version=1,
        message_type="sms_message",
        message_id=UUID(int=number),
        created_at=datetime(2026, 9, 28, tzinfo=UTC),
        body=body,
    )


@pytest.mark.parametrize("status", ["accepted", "duplicate"])
def test_full_queue_retries_identical_payload_until_confirmed(status: str) -> None:
    sms = message()
    requests = []
    sleep = AsyncMock()

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) < 3:
            return httpx.Response(503, headers={"Retry-After": "2"})
        return httpx.Response(
            202,
            json={
                "status": status,
                "message_id": str(sms.message_id),
                "message_type": sms.message_type,
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            await BrokerClient(
                client, ProducerConfig(max_retries=2), sleep=sleep
            ).submit(sms)

    asyncio.run(scenario())
    assert len(requests) == 3
    assert all(json.loads(r.content) == sms.model_dump(mode="json") for r in requests)
    assert all(str(r.url) == "http://127.0.0.1:8000/messages" for r in requests)
    assert [call.args for call in sleep.await_args_list] == [(2,), (2,)]


@pytest.mark.parametrize(
    "status, retries, calls",
    [(409, 3, 1), (422, 3, 1), (500, 3, 1), (503, 0, 1), (503, 2, 3), (200, 3, 1)],
)
def test_failures_are_explicit_and_retries_bounded(status, retries, calls) -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with pytest.raises(SubmissionError):
                await BrokerClient(
                    client, ProducerConfig(max_retries=retries), sleep=AsyncMock()
                ).submit(message())

    asyncio.run(scenario())
    assert len(requests) == calls


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"status": "accepted"},
        {
            "status": "accepted",
            "message_id": str(UUID(int=2)),
            "message_type": "sms_message",
        },
        {"status": "accepted", "message_id": str(UUID(int=1)), "message_type": "other"},
        {
            "status": "unknown",
            "message_id": str(UUID(int=1)),
            "message_type": "sms_message",
        },
    ],
)
def test_malformed_receipt_is_not_counted_as_success(payload) -> None:
    async def scenario() -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(202, json=payload))
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(SubmissionError, match="receipt"):
                await BrokerClient(client, ProducerConfig()).submit(message())

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError("offline"), httpx.ReadTimeout("timeout"), TimeoutError()],
)
def test_transport_failures_are_not_retried(error: Exception) -> None:
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post.side_effect = error
    with pytest.raises(SubmissionError, match="admission may be unknown"):
        asyncio.run(BrokerClient(client, ProducerConfig()).submit(message()))
    assert client.post.await_count == 1


@pytest.mark.parametrize("header", ["bad", "-1", "61"])
def test_unsupported_retry_after_fails_without_sleeping(header: str) -> None:
    sleep = AsyncMock()

    async def scenario() -> None:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(503, headers={"Retry-After": header})
        )
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(SubmissionError, match="Retry-After"):
                await BrokerClient(client, ProducerConfig(), sleep=sleep).submit(
                    message()
                )

    asyncio.run(scenario())
    sleep.assert_not_awaited()


@pytest.fixture
def messages() -> list[SmsMessage]:
    return [message(n, "hello") for n in (1, 2)]


def receipts(messages: list[SmsMessage]) -> list[dict]:
    return [
        {
            "status": "accepted",
            "message_id": str(m.message_id),
            "message_type": m.message_type,
        }
        for m in messages
    ]


def test_retry_preserves_complete_batch_and_accepts_duplicate_receipts(
    messages: list[SmsMessage],
) -> None:
    requests = []
    sleep = AsyncMock()
    response_body = receipts(messages)
    response_body[1]["status"] = "duplicate"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, headers={"Retry-After": "1"})
        return httpx.Response(202, json=response_body)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await BrokerClient(http, ProducerConfig(), sleep=sleep).submit_batch(
                messages
            )

    asyncio.run(scenario())
    assert len(requests) == 2
    assert all(r.url.path == "/messages/batch" for r in requests)
    assert all(
        json.loads(r.content) == [m.model_dump(mode="json") for m in messages]
        for r in requests
    )
    sleep.assert_awaited_once_with(1)


@pytest.mark.parametrize(
    "kind", ["object", "short", "long", "reversed", "type", "status", "invalid_json"]
)
def test_invalid_batch_receipts_fail(messages: list[SmsMessage], kind: str) -> None:
    body = receipts(messages)
    if kind == "object":
        body = body[0]
    elif kind == "short":
        body.pop()
    elif kind == "long":
        body.append(body[0])
    elif kind == "reversed":
        body.reverse()
    elif kind == "type":
        body[1]["message_type"] = "other"
    elif kind == "status":
        body[1]["status"] = "failed"

    async def scenario() -> None:
        response = (
            httpx.Response(202, content="not json")
            if kind == "invalid_json"
            else httpx.Response(202, json=body)
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: response)
        ) as http:
            with pytest.raises(SubmissionError, match="receipt"):
                await BrokerClient(http, ProducerConfig()).submit_batch(messages)

    asyncio.run(scenario())
