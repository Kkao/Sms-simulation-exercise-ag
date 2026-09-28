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
