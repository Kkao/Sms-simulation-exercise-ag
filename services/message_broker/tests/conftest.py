from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID

import pytest

from services.message_broker import MessageBroker
from shared import SmsMessage


@pytest.fixture
def message() -> SmsMessage:
    return SmsMessage(
        schema_version=1,
        message_type="sms_message",
        message_id=UUID(int=1),
        created_at=datetime(2026, 9, 26, 14, 30, tzinfo=UTC),
        body="Simulated SMS",
    )


@pytest.fixture
def clock() -> Mock:
    return Mock(return_value=datetime(2026, 9, 26, 14, 31, tzinfo=UTC))


@pytest.fixture
def id_factory() -> Mock:
    return Mock(side_effect=[UUID(int=value) for value in range(101, 111)])


@pytest.fixture
def broker(clock: Mock, id_factory: Mock) -> MessageBroker:
    return MessageBroker(capacity=2, clock=clock, id_factory=id_factory)
