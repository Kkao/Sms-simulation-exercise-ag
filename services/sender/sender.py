import asyncio
import logging
import random
from asyncio import sleep
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from services.sender.config import SenderConfig
from shared import BrokerAttempt, SenderResult

logger = logging.getLogger(__name__)
SENDER_PREFIX = "sms-sender"
Claim = Callable[[str], Awaitable[BrokerAttempt | None]]
Report = Callable[[SenderResult], Awaitable[None]]


async def process_attempt(
    attempt: BrokerAttempt,
    sender_id: str,
    config: SenderConfig,
    *,
    rng: random.Random | None = None,
) -> SenderResult:
    """Simulate one attempt and return its outcome, including elapsed wait time."""
    attempt = BrokerAttempt.model_validate(attempt)
    rng = rng if rng is not None else random.Random()
    started = monotonic()
    # Uniform [0, 2 * mean] has the configured mean and a bounded upper limit.
    await sleep(rng.uniform(0, 2 * config.mean_delay))
    failed = rng.random() < config.failure_rate
    duration = (monotonic() - started) * 1000
    return SenderResult(
        schema_version=1,
        message_type=attempt.message_type,
        event_id=uuid4(),
        event_type="sms.attempt_completed",
        message_id=attempt.message.message_id,
        attempt_id=attempt.attempt_id,
        sender_id=sender_id,
        occurred_at=datetime.now(UTC),
        status="failed" if failed else "sent",
        processing_duration_ms=duration,
        error_code="SIMULATED_SEND_FAILURE" if failed else None,
    )


class SenderError(RuntimeError):
    """Retain the affected attempt so callers can inspect failed work."""

    def __init__(
        self,
        sender_id: str,
        attempt: BrokerAttempt | None,
        reason: str,
    ) -> None:
        self.sender_id = sender_id
        self.attempt = attempt
        super().__init__(
            f"{sender_id}: {reason}; "
            f"attempt_id={attempt.attempt_id if attempt else 'unknown'}"
        )


class SenderServiceError(RuntimeError):
    def __init__(self, errors: list[SenderError]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(str(error) for error in errors))


async def run_sender(
    sender_id: str,
    config: SenderConfig,
    claim: Claim,
    *,
    report: Report | None = None,
    stop: asyncio.Event,
) -> int:
    """Keep at most one attempt in flight; stop finishes any assigned attempt."""
    rng = random.Random()
    completed = 0
    attempt = None
    try:
        while not stop.is_set():
            attempt = None
            attempt = await claim(sender_id)
            if attempt is None:
                await sleep(config.poll_interval)
                continue
            result = await process_attempt(attempt, sender_id, config, rng=rng)
            if report is not None:
                await report(result)
            logger.info("Completed attempt: %s", result.model_dump_json())
            completed += 1
            attempt = None
    except asyncio.CancelledError:
        logger.warning(
            "%s cancelled; assignment may be unknown or interrupted; attempt_id=%s",
            sender_id,
            attempt.attempt_id if attempt else "unknown",
        )
        raise
    except Exception as error:
        raise SenderError(sender_id, attempt, str(error)) from error
    return completed


async def run_senders(
    config: SenderConfig,
    claim: Claim,
    *,
    report: Report | None = None,
    stop: asyncio.Event | None = None,
) -> int:
    """Run independent workers; on error stop claiming and drain other workers."""
    stop = stop if stop is not None else asyncio.Event()
    errors: list[SenderError] = []

    async def worker(index: int) -> int:
        try:
            return await run_sender(
                f"{SENDER_PREFIX}-{index}",
                config,
                claim,
                report=report,
                stop=stop,
            )
        except SenderError as error:
            errors.append(error)
            stop.set()
            logger.error("%s", error)
            return 0

    # TaskGroup also ensures cancellation waits for all worker cleanup.
    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(worker(i + 1)) for i in range(config.sender_count)]
    if errors:
        raise SenderServiceError(errors)
    return sum(task.result() for task in tasks)
