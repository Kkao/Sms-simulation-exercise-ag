from datetime import timedelta
from unittest.mock import Mock
from uuid import UUID

import pytest

from services.message_broker import (
    BrokerQueueFull,
    DuplicateMessageError,
    EnqueueStatus,
    MessageBroker,
)
from shared import SmsMessage


def test_empty_claim_does_not_generate_metadata(
    broker: MessageBroker, clock: Mock, id_factory: Mock
) -> None:
    assert broker.claim("sms_message") is None
    assert broker.pending_count == 0
    clock.assert_not_called()
    id_factory.assert_not_called()


def test_claim_preserves_message_and_assigns_attempt_metadata(
    broker: MessageBroker, message: SmsMessage, clock: Mock, id_factory: Mock
) -> None:
    enqueued_at = clock.return_value
    assert broker.enqueue(message) is EnqueueStatus.ACCEPTED
    assert broker.pending_count == 1
    id_factory.assert_called_once_with()
    clock.assert_called_once_with()

    dispatched_at = enqueued_at + timedelta(seconds=5)
    clock.return_value = dispatched_at
    attempt = broker.claim("sms_message")

    assert attempt is not None
    assert attempt.model_dump() == {
        "schema_version": 1,
        "message_type": "sms_message",
        "attempt_id": UUID(int=101),
        "attempt_number": 1,
        "enqueued_at": enqueued_at,
        "dispatched_at": dispatched_at,
        "message": message.model_dump(),
    }
    assert broker.pending_count == 0
    assert broker.claim("sms_message") is None
    assert clock.call_count == 2
    id_factory.assert_called_once_with()


def test_full_queue_preserves_fifo_and_rejected_message_can_be_retried(
    broker: MessageBroker, message: SmsMessage, clock: Mock, id_factory: Mock
) -> None:
    messages = [
        message.model_copy(update={"message_id": UUID(int=i)}) for i in range(1, 4)
    ]
    for item in messages[:2]:
        assert broker.enqueue(item) is EnqueueStatus.ACCEPTED

    with pytest.raises(BrokerQueueFull, match="broker queue is full"):
        broker.enqueue(messages[2])
    assert broker.pending_count == 2
    assert clock.call_count == id_factory.call_count == 2

    first = broker.claim("sms_message")
    assert first is not None
    assert first.message == messages[0]
    assert broker.pending_count == 1
    assert broker.enqueue(messages[2]) is EnqueueStatus.ACCEPTED
    assert broker.pending_count == 2

    remaining = [broker.claim("sms_message"), broker.claim("sms_message")]
    assert all(attempt is not None for attempt in remaining)
    assert [attempt.message for attempt in remaining] == messages[1:]
    assert [first.attempt_id, *(attempt.attempt_id for attempt in remaining)] == [
        UUID(int=101),
        UUID(int=102),
        UUID(int=103),
    ]
    assert broker.pending_count == 0
    assert broker.claim("sms_message") is None


@pytest.mark.parametrize("dispatched", [False, True])
def test_identical_resubmission_is_duplicate_even_when_full_or_dispatched(
    message: SmsMessage, clock: Mock, id_factory: Mock, dispatched: bool
) -> None:
    broker = MessageBroker(capacity=1, clock=clock, id_factory=id_factory)
    broker.enqueue(message)
    if dispatched:
        broker.claim("sms_message")
    clock.reset_mock()
    id_factory.reset_mock()

    assert broker.enqueue(message.model_copy()) is EnqueueStatus.DUPLICATE
    assert broker.pending_count == (0 if dispatched else 1)
    clock.assert_not_called()
    id_factory.assert_not_called()
    if not dispatched:
        assert broker.claim("sms_message").message == message
    assert broker.claim("sms_message") is None


@pytest.mark.parametrize("dispatched", [False, True])
@pytest.mark.parametrize("field", ["body", "created_at"])
def test_conflicting_duplicate_does_not_replace_original(
    message: SmsMessage, clock: Mock, id_factory: Mock, dispatched: bool, field: str
) -> None:
    broker = MessageBroker(capacity=1, clock=clock, id_factory=id_factory)
    broker.enqueue(message)
    if dispatched:
        broker.claim("sms_message")
    value = (
        "Changed body" if field == "body" else message.created_at + timedelta(seconds=1)
    )
    conflict = message.model_copy(update={field: value})
    clock.reset_mock()
    id_factory.reset_mock()

    with pytest.raises(DuplicateMessageError, match="different content"):
        broker.enqueue(conflict)
    assert broker.pending_count == (0 if dispatched else 1)
    clock.assert_not_called()
    id_factory.assert_not_called()
    assert broker.enqueue(message) is EnqueueStatus.DUPLICATE
    if not dispatched:
        assert broker.claim("sms_message").message == message
    assert broker.claim("sms_message") is None


def test_claim_for_absent_type_leaves_pending_sms_untouched(
    broker: MessageBroker, message: SmsMessage, clock: Mock
) -> None:
    broker.enqueue(message)
    clock.reset_mock()

    assert broker.claim("unsupported_type") is None
    assert broker.pending_count == 1
    clock.assert_not_called()
    assert broker.claim("sms_message").message == message


@pytest.mark.parametrize("boundary", ["clock", "id_factory"])
def test_enqueue_dependency_failure_leaves_message_retryable(
    broker: MessageBroker,
    message: SmsMessage,
    clock: Mock,
    id_factory: Mock,
    boundary: str,
) -> None:
    dependency = clock if boundary == "clock" else id_factory
    good_value = clock.return_value if boundary == "clock" else UUID(int=105)
    dependency.side_effect = [RuntimeError("dependency unavailable"), good_value]

    with pytest.raises(RuntimeError, match="dependency unavailable"):
        broker.enqueue(message)
    assert broker.pending_count == 0
    assert broker.enqueue(message) is EnqueueStatus.ACCEPTED
    clock.side_effect = None
    assert broker.claim("sms_message").message == message


@pytest.mark.parametrize("invalid_id", [None, "not-a-uuid", str(UUID(int=101)), 101])
def test_invalid_attempt_id_does_not_accept_message(
    broker: MessageBroker,
    message: SmsMessage,
    clock: Mock,
    id_factory: Mock,
    invalid_id: object,
) -> None:
    id_factory.side_effect = [invalid_id, UUID(int=102)]
    with pytest.raises(ValueError, match="id_factory must return a UUID"):
        broker.enqueue(message)
    assert broker.pending_count == 0
    clock.assert_not_called()
    assert broker.enqueue(message) is EnqueueStatus.ACCEPTED
    assert broker.claim("sms_message").attempt_id == UUID(int=102)
