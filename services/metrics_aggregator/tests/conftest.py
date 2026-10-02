from datetime import UTC, datetime
from uuid import UUID

import pytest

from shared import SenderResult


@pytest.fixture
def event() -> SenderResult:
    return SenderResult(
        schema_version=1,
        message_type="sms_message",
        event_id=UUID(int=1),
        event_type="sms.attempt_completed",
        message_id=UUID(int=2),
        attempt_id=UUID(int=3),
        sender_id="sms-sender-1",
        occurred_at=datetime(2026, 10, 1, 12, tzinfo=UTC),
        status="sent",
        processing_duration_ms=125,
        total_latency_ms=625,
        error_code=None,
    )
