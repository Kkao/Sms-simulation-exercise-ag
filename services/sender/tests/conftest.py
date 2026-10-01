from datetime import UTC, datetime
from uuid import UUID

import pytest

from shared import BrokerAttempt, SenderResult, SmsMessage


@pytest.fixture
def attempt() -> BrokerAttempt:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    return BrokerAttempt(
        schema_version=1,
        message_type="sms_message",
        attempt_id=UUID(int=2),
        attempt_number=2,
        enqueued_at=now,
        dispatched_at=now,
        message=SmsMessage(
            schema_version=1,
            message_type="sms_message",
            message_id=UUID(int=1),
            created_at=now,
            body="Simulated SMS",
        ),
    )


@pytest.fixture
def result(attempt: BrokerAttempt) -> SenderResult:
    return SenderResult(
        schema_version=1,
        message_type="sms_message",
        event_id=UUID(int=3),
        event_type="sms.attempt_completed",
        message_id=attempt.message.message_id,
        attempt_id=attempt.attempt_id,
        sender_id="sender-1",
        occurred_at=attempt.dispatched_at,
        status="sent",
        processing_duration_ms=250,
        error_code=None,
    )
