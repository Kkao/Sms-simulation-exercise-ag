import asyncio
import random
from datetime import UTC
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

from services.sender import (
    SenderConfig,
    SenderError,
    SenderServiceError,
    process_attempt,
    run_sender,
    run_senders,
)
from services.sender import sender as sender_module
from shared import BrokerAttempt, SenderResult


@pytest.mark.parametrize(
    "rate,draw,status",
    [
        (0, 0, "sent"),
        (1, 0.999999, "failed"),
        (0.5, 0.49, "failed"),
        (0.5, 0.5, "sent"),
    ],
)
def test_processing_preserves_metadata_and_measures_elapsed_time(
    attempt: BrokerAttempt,
    rate: float,
    draw: float,
    status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rng = Mock()
    rng.uniform.return_value = 0.2
    rng.random.return_value = draw
    sleep = AsyncMock()
    datetime = Mock()
    datetime.now.return_value = attempt.dispatched_at
    monkeypatch.setattr(sender_module, "sleep", sleep)
    monkeypatch.setattr(sender_module, "monotonic", Mock(side_effect=[10, 10.25]))
    monkeypatch.setattr(sender_module, "datetime", datetime)
    monkeypatch.setattr(sender_module, "uuid4", lambda: UUID(int=9))
    result = asyncio.run(
        process_attempt(
            attempt,
            "sender-test",
            SenderConfig(mean_delay=0.3, failure_rate=rate),
            rng=rng,
        )
    )
    rng.uniform.assert_called_once_with(0, 0.6)
    sleep.assert_awaited_once_with(0.2)
    datetime.now.assert_called_once_with(UTC)
    assert result.status == status
    assert result.error_code == (
        "SIMULATED_SEND_FAILURE" if status == "failed" else None
    )
    assert result.processing_duration_ms == 250
    assert result.message_id == attempt.message.message_id
    assert result.attempt_id == attempt.attempt_id
    assert result.message_type == attempt.message_type
    assert result.event_id == UUID(int=9)
    assert result.sender_id == "sender-test"
    assert result.occurred_at == attempt.dispatched_at
    assert attempt.attempt_number == 2


def test_processing_error_retains_attempt_without_claiming_again(
    attempt: BrokerAttempt,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = AsyncMock(return_value=attempt)
    monkeypatch.setattr(
        sender_module,
        "process_attempt",
        AsyncMock(side_effect=RuntimeError("processing failed")),
    )
    with pytest.raises(SenderError, match="processing failed") as caught:
        asyncio.run(
            run_sender(
                "s",
                SenderConfig(),
                claim,
                stop=asyncio.Event(),
            )
        )
    assert caught.value.attempt == attempt
    claim.assert_awaited_once_with("s")


def test_completed_attempt_is_reported_before_counting(
    attempt: BrokerAttempt,
    result: SenderResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        stop = asyncio.Event()
        claim = AsyncMock(return_value=attempt)
        report = AsyncMock(side_effect=lambda event: stop.set())
        monkeypatch.setattr(
            sender_module, "process_attempt", AsyncMock(return_value=result)
        )
        assert (
            await run_sender("s", SenderConfig(), claim, report=report, stop=stop) == 1
        )
        report.assert_awaited_once_with(result)

    asyncio.run(scenario())


def test_concurrent_workers_have_distinct_ids_and_finish_inflight_on_error(
    attempt: BrokerAttempt,
    result: SenderResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        ready = asyncio.Event()
        failing = asyncio.Event()
        claimed = []
        completed = []

        async def claim(sender_id: str) -> BrokerAttempt:
            claimed.append(sender_id)
            if len(claimed) == 3:
                ready.set()
            await ready.wait()
            return attempt

        async def process(
            work: BrokerAttempt,
            sender_id: str,
            config: SenderConfig,
            *,
            rng: random.Random,
        ) -> SenderResult:
            if sender_id == "sms-sender-1":
                failing.set()
                raise RuntimeError("processing error")
            await failing.wait()
            completed.append(sender_id)
            return result.model_copy(update={"sender_id": sender_id})

        monkeypatch.setattr(sender_module, "process_attempt", process)
        with pytest.raises(SenderServiceError) as caught:
            async with asyncio.timeout(2):
                await run_senders(
                    SenderConfig(sender_count=3),
                    claim,
                )
        assert sorted(claimed) == ["sms-sender-1", "sms-sender-2", "sms-sender-3"]
        assert sorted(completed) == ["sms-sender-2", "sms-sender-3"]
        assert len(caught.value.errors) == 1
        assert caught.value.errors[0].attempt == attempt

    asyncio.run(scenario())


def test_already_stopped_service_does_not_claim() -> None:
    async def scenario() -> None:
        stop = asyncio.Event()
        stop.set()
        claim = AsyncMock()
        assert await run_senders(SenderConfig(), claim, stop=stop) == 0
        claim.assert_not_called()

    asyncio.run(scenario())


def test_cancellation_logs_interrupted_attempt_and_cleans_up_workers(
    attempt: BrokerAttempt,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        processing = asyncio.Event()
        cleaned = asyncio.Event()

        async def process(
            work: BrokerAttempt,
            sender_id: str,
            config: SenderConfig,
            *,
            rng: random.Random,
        ) -> SenderResult:
            processing.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        monkeypatch.setattr(sender_module, "process_attempt", process)
        task = asyncio.create_task(
            run_senders(
                SenderConfig(sender_count=1),
                AsyncMock(return_value=attempt),
            )
        )
        async with asyncio.timeout(2):
            await processing.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert cleaned.is_set()
        assert str(attempt.attempt_id) in caplog.text

    asyncio.run(scenario())
