from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4

from shared import BrokerAttempt, MessageType, SmsMessage
from shared.validation import validate_utc_timestamp

MAX_BATCH_SIZE = 1000


class EnqueueStatus(str, Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"


class BrokerQueueFull(RuntimeError):
    """The message was not accepted; the producer may retry later."""


class DuplicateMessageError(ValueError):
    """An accepted message's identifiers were reused with different content."""


@dataclass(frozen=True)
class _QueuedAttempt:
    message: SmsMessage
    attempt_id: UUID
    enqueued_at: datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MessageBroker:
    def __init__(
        self,
        capacity: int = 1000,
        *,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        if type(capacity) is not int or capacity < 1:
            raise ValueError("capacity must be a positive integer")
        self._capacity = capacity
        self._queues: dict[MessageType, deque[_QueuedAttempt]] = {}
        self._accepted: dict[UUID, SmsMessage] = {}
        self._clock = clock
        self._id_factory = id_factory

    @property
    def pending_count(self) -> int:
        return sum(len(queue) for queue in self._queues.values())

    def enqueue(self, message: SmsMessage) -> EnqueueStatus:
        """
        Accept a validated message once, or report an identical resubmission.

        Raises DuplicateMessageError for conflicting content and BrokerQueueFull
        when capacity is exhausted.
        """
        return self.enqueue_many([message])[0]

    def enqueue_many(self, messages: list[SmsMessage]) -> list[EnqueueStatus]:
        """Admit a batch of messages, returning one status per input in order."""
        if not 1 <= len(messages) <= MAX_BATCH_SIZE:
            raise ValueError(f"batch must contain 1 to {MAX_BATCH_SIZE} messages")
        validated = [SmsMessage.model_validate(message) for message in messages]
        new_messages: dict[UUID, SmsMessage] = {}
        statuses: list[EnqueueStatus] = []
        for message in validated:
            key = message.message_id
            previous = self._accepted.get(key) or new_messages.get(key)
            if previous is not None:
                if previous != message:
                    raise DuplicateMessageError(
                        f"message_id {key} already accepted or repeated with different content"
                    )
                statuses.append(EnqueueStatus.DUPLICATE)
            else:
                new_messages[key] = message
                statuses.append(EnqueueStatus.ACCEPTED)

        if self.pending_count + len(new_messages) > self._capacity:
            raise BrokerQueueFull("broker queue is full")

        entries = [self._prepare_attempt(message) for message in new_messages.values()]
        for entry in entries:
            queue = self._queues.setdefault(entry.message.message_type, deque())
            queue.append(entry)
            self._accepted[entry.message.message_id] = entry.message
        return statuses

    def _prepare_attempt(self, message: SmsMessage) -> _QueuedAttempt:
        attempt_id = self._id_factory()
        if not isinstance(attempt_id, UUID):
            raise ValueError("id_factory must return a UUID")
        return _QueuedAttempt(
            message=message,
            attempt_id=attempt_id,
            enqueued_at=validate_utc_timestamp(self._clock()),
        )

    def claim(self, message_type: MessageType) -> BrokerAttempt | None:
        """
        Claim the oldest attempt from the requested message type's queue.
        """
        queue = self._queues.get(message_type)
        if not queue:
            return None

        entry = queue[0]
        attempt = BrokerAttempt(
            schema_version=1,
            message_type=message_type,
            attempt_id=entry.attempt_id,
            attempt_number=1,
            enqueued_at=entry.enqueued_at,
            dispatched_at=validate_utc_timestamp(self._clock()),
            message=entry.message,
        )
        queue.popleft()
        return attempt
