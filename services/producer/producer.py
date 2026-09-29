import random
import string
from asyncio import sleep
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from services.producer.client import SubmissionError
from services.producer.config import ProducerConfig
from shared import SmsMessage

ALPHABET = string.ascii_letters + string.digits + string.punctuation + " "


def generate_message(
    body_length: int = 100,
    *,
    # Selects random body characters; a seeded generator makes text repeatable in tests.
    rng: random.Random | None = None,
    utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> SmsMessage:
    """Create a message with exactly body_length random printable characters."""
    if type(body_length) is not int or not 0 <= body_length <= 100:
        raise ValueError("body_length must be an integer between 0 and 100")
    if rng is None:
        rng = random.Random()
    return SmsMessage(
        schema_version=1,
        message_type="sms_message",
        message_id=uuid4(),
        created_at=utc_now(),
        body="".join(rng.choices(ALPHABET, k=body_length)),
    )


class ProductionError(RuntimeError):
    """Retain the unconfirmed payload and progress so callers can handle failure."""

    def __init__(
        self, message: SmsMessage | list[SmsMessage], completed: int, reason: str
    ) -> None:
        self.messages = (
            (message,) if isinstance(message, SmsMessage) else tuple(message)
        )
        self.message = self.messages[0]
        self.completed = completed
        super().__init__(
            f"Stopped after {completed} confirmed messages; "
            f"message_id={self.message.message_id} "
            f"({len(self.messages)} unconfirmed): {reason}"
        )


async def produce(
    config: ProducerConfig,
    submit: Callable[[SmsMessage], Awaitable[None]],
    *,
    submit_batch: Callable[[list[SmsMessage]], Awaitable[None]] | None = None,
    # Shared across messages; a fixed seed reproduces the sequence of SMS bodies.
    # None creates a new generator. IDs and timestamps are unaffected.
    rng: random.Random | None = None,
) -> int:
    """
    Return confirmed submissions; stop at the first unconfirmed message.
    """
    if config.batch_size > 1 and submit_batch is None:
        raise ValueError("submit_batch is required when batch_size exceeds 1")
    if rng is None:
        rng = random.Random()
    next_start = monotonic()
    for completed in range(0, config.count, config.batch_size):
        remaining = next_start - monotonic()
        while remaining > 0:
            await sleep(remaining)
            remaining = next_start - monotonic()
        next_start = monotonic() + config.batch_size / config.rate
        messages = [
            generate_message(config.body_length, rng=rng)
            for _ in range(min(config.batch_size, config.count - completed))
        ]
        try:
            if config.batch_size == 1:
                await submit(messages[0])
            else:
                await submit_batch(messages)
        except SubmissionError as error:
            raise ProductionError(messages, completed, str(error)) from error
    return config.count
