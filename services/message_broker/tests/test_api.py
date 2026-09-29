import asyncio
import logging
from collections.abc import Callable
from unittest.mock import Mock, create_autospec
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute

from services.message_broker import (
    BrokerQueueFull,
    DuplicateMessageError,
    EnqueueStatus,
    MessageBroker,
    api,
)
from services.message_broker.api_models import ClaimRequest
from shared import BrokerAttempt, SmsMessage


def endpoint(app: FastAPI, path: str) -> Callable:
    return next(
        route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == path
    )


@pytest.fixture
def fake_broker() -> Mock:
    return create_autospec(MessageBroker, instance=True)


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, fake_broker: Mock) -> FastAPI:
    monkeypatch.setattr(api, "MessageBroker", Mock(return_value=fake_broker))
    return api.create_app(capacity=2)


@pytest.mark.parametrize("status", [EnqueueStatus.ACCEPTED, EnqueueStatus.DUPLICATE])
def test_enqueue_handler_returns_broker_status(
    app: FastAPI, fake_broker: Mock, message: SmsMessage, status: EnqueueStatus
) -> None:
    fake_broker.enqueue.return_value = status
    response = asyncio.run(endpoint(app, "/messages")(message))
    assert response.model_dump() == {
        "status": status,
        "message_id": message.message_id,
        "message_type": message.message_type,
    }
    fake_broker.enqueue.assert_called_once_with(message)


@pytest.mark.parametrize(
    ("error", "status_code", "headers"),
    [
        (DuplicateMessageError("conflict"), 409, None),
        (BrokerQueueFull("full"), 503, {"Retry-After": "1"}),
    ],
)
def test_enqueue_handler_maps_expected_errors(
    app: FastAPI,
    fake_broker: Mock,
    message: SmsMessage,
    error: Exception,
    status_code: int,
    headers: dict[str, str] | None,
) -> None:
    fake_broker.enqueue.side_effect = error
    with pytest.raises(HTTPException) as caught:
        asyncio.run(endpoint(app, "/messages")(message))
    assert caught.value.status_code == status_code
    assert caught.value.detail == str(error)
    assert caught.value.headers == headers


def test_enqueue_handler_propagates_unexpected_failures(
    app: FastAPI, fake_broker: Mock, message: SmsMessage
) -> None:
    fake_broker.enqueue.side_effect = RuntimeError("unexpected failure")
    with pytest.raises(RuntimeError, match="unexpected failure"):
        asyncio.run(endpoint(app, "/messages")(message))


def test_batch_handler_returns_ordered_receipts(
    app: FastAPI,
    fake_broker: Mock,
    message: SmsMessage,
) -> None:
    fake_broker.enqueue_many.return_value = [
        EnqueueStatus.ACCEPTED,
        EnqueueStatus.DUPLICATE,
    ]
    response = asyncio.run(endpoint(app, "/messages/batch")([message, message]))
    assert [item.status for item in response] == [
        EnqueueStatus.ACCEPTED,
        EnqueueStatus.DUPLICATE,
    ]
    assert all(item.message_id == message.message_id for item in response)
    fake_broker.enqueue_many.assert_called_once_with([message, message])
    fake_broker.enqueue.assert_not_called()


@pytest.mark.parametrize(
    "error, code, headers",
    [
        (DuplicateMessageError("conflict"), 409, None),
        (BrokerQueueFull("full"), 503, {"Retry-After": "1"}),
    ],
)
def test_batch_handler_maps_rejections(
    app: FastAPI,
    fake_broker: Mock,
    message: SmsMessage,
    error: Exception,
    code: int,
    headers: dict[str, str] | None,
) -> None:
    fake_broker.enqueue_many.side_effect = error
    with pytest.raises(HTTPException) as caught:
        asyncio.run(endpoint(app, "/messages/batch")([message]))
    assert caught.value.status_code == code
    assert caught.value.headers == headers


def test_empty_claim_handler_returns_bodyless_response(
    app: FastAPI, fake_broker: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    fake_broker.claim.return_value = None
    with caplog.at_level(logging.INFO, logger=api.__name__):
        response = asyncio.run(
            endpoint(app, "/messages/claim")(
                ClaimRequest(sender_id="sender-1", message_type="sms_message")
            )
        )
    assert response.status_code == 204
    assert response.body == b""
    fake_broker.claim.assert_called_once_with("sms_message")
    assert not caplog.records


def test_claim_handler_returns_attempt_and_logs_correlation_ids(
    app: FastAPI,
    fake_broker: Mock,
    message: SmsMessage,
    caplog: pytest.LogCaptureFixture,
) -> None:
    attempt = BrokerAttempt(
        schema_version=1,
        message_type="sms_message",
        attempt_id=UUID(int=101),
        attempt_number=1,
        enqueued_at=message.created_at,
        dispatched_at=message.created_at,
        message=message,
    )
    fake_broker.claim.return_value = attempt
    with caplog.at_level(logging.INFO, logger=api.__name__):
        response = asyncio.run(
            endpoint(app, "/messages/claim")(
                ClaimRequest(sender_id="sender-1", message_type="sms_message")
            )
        )
    assert response == attempt
    fake_broker.claim.assert_called_once_with("sms_message")
    assert len(caplog.records) == 1
    for value in [
        str(attempt.attempt_id),
        str(message.message_id),
        "sms_message",
        "sender-1",
    ]:
        assert value in caplog.records[0].getMessage()


@pytest.mark.parametrize("pending", [0, 2])
def test_health_handler_reports_current_pending_count(
    app: FastAPI, fake_broker: Mock, pending: int
) -> None:
    fake_broker.pending_count = pending
    response = asyncio.run(endpoint(app, "/health")())
    assert response.model_dump() == {"status": "ok", "pending_messages": pending}
    fake_broker.enqueue.assert_not_called()
    fake_broker.claim.assert_not_called()


def test_batch_preserves_fifo_and_prepares_one_attempt_per_new_message(
    broker: MessageBroker,
    message: SmsMessage,
    id_factory: Mock,
) -> None:
    second = message.model_copy(update={"message_id": UUID(int=2)})
    assert broker.enqueue_many([message, second, message]) == [
        EnqueueStatus.ACCEPTED,
        EnqueueStatus.ACCEPTED,
        EnqueueStatus.DUPLICATE,
    ]
    assert broker.pending_count == 2
    assert id_factory.call_count == 2
    attempts = [broker.claim("sms_message"), broker.claim("sms_message")]
    assert [attempt.message for attempt in attempts] == [message, second]
    assert [attempt.attempt_id for attempt in attempts] == [
        UUID(int=101),
        UUID(int=102),
    ]
    assert all(attempt.attempt_number == 1 for attempt in attempts)
    assert broker.enqueue_many([message, second]) == [EnqueueStatus.DUPLICATE] * 2
    assert broker.pending_count == 0


def test_batch_capacity_rejection_is_atomic_and_retryable(
    broker: MessageBroker,
    message: SmsMessage,
    clock: Mock,
    id_factory: Mock,
) -> None:
    broker.enqueue(message)
    new = [message.model_copy(update={"message_id": UUID(int=i)}) for i in (2, 3)]
    clock.reset_mock()
    id_factory.reset_mock()
    with pytest.raises(BrokerQueueFull):
        broker.enqueue_many(new)
    assert broker.pending_count == 1
    clock.assert_not_called()
    id_factory.assert_not_called()
    assert broker.claim("sms_message").message == message
    assert broker.enqueue_many(new) == [EnqueueStatus.ACCEPTED] * 2
    assert [broker.claim("sms_message").message for _ in new] == new


@pytest.mark.parametrize("already_accepted", [False, True])
def test_conflict_rejects_entire_batch(
    broker: MessageBroker,
    message: SmsMessage,
    already_accepted: bool,
) -> None:
    if already_accepted:
        broker.enqueue(message)
    new = message.model_copy(update={"message_id": UUID(int=2)})
    conflict = message.model_copy(update={"body": "Different"})
    with pytest.raises(DuplicateMessageError):
        broker.enqueue_many([new, message, conflict])
    assert broker.pending_count == int(already_accepted)
    assert broker.enqueue(new) is EnqueueStatus.ACCEPTED


def test_invalid_later_message_does_not_admit_valid_prefix(
    broker: MessageBroker,
    message: SmsMessage,
) -> None:
    invalid = message.model_copy(update={"message_id": UUID(int=2), "body": "x" * 101})
    with pytest.raises(ValueError):
        broker.enqueue_many([message, invalid])
    assert broker.pending_count == 0
    assert broker.enqueue(message) is EnqueueStatus.ACCEPTED


@pytest.mark.parametrize("size", [0, 1001])
def test_invalid_batch_sizes(
    broker: MessageBroker, message: SmsMessage, size: int
) -> None:
    with pytest.raises(ValueError, match="1 to 1000"):
        broker.enqueue_many([message] * size)
    assert broker.pending_count == 0
