import asyncio
import random
from datetime import UTC, datetime
from functools import partial
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from services.producer import ProducerConfig, ProductionError, generate_message, produce
from services.producer import producer as producer_module
from services.producer.client import SubmissionError
from services.producer.producer import ALPHABET
from shared import SmsMessage


@pytest.mark.parametrize(
    ("latency", "starts", "waits"),
    [(0, [0, 0.5, 1], [0.5, 0.5]), (0.2, [0, 0.5, 1], [0.3, 0.3]), (2, [0, 2, 4], [])],
)
def test_pacing_accounts_for_request_time_without_catchup(
    monkeypatch: pytest.MonkeyPatch,
    latency: float,
    starts: list[float],
    waits: list[float],
) -> None:
    clock = [0.0]
    observed_starts = []
    observed_waits = []
    messages = []
    ids = iter([UUID(int=n) for n in range(1, 4)])
    monkeypatch.setattr(producer_module, "uuid4", lambda: next(ids))
    monkeypatch.setattr(producer_module, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        producer_module,
        "generate_message",
        partial(
            producer_module.generate_message,
            utc_now=lambda: datetime(2026, 9, 28, tzinfo=UTC),
        ),
    )

    async def sleep(delay: float) -> None:
        observed_waits.append(delay)
        clock[0] += delay

    async def submit(message: SmsMessage) -> None:
        observed_starts.append(clock[0])
        messages.append(message)
        clock[0] += latency

    monkeypatch.setattr(producer_module, "sleep", sleep)
    result = asyncio.run(
        produce(
            ProducerConfig(count=3, rate=2),
            submit,
            rng=random.Random(1),
        )
    )
    assert result == 3
    assert observed_starts == pytest.approx(starts)
    assert observed_waits == pytest.approx(waits)
    assert [m.message_id for m in messages] == [UUID(int=n) for n in range(1, 4)]


def test_zero_count_does_no_work(monkeypatch: pytest.MonkeyPatch) -> None:
    submit, sleep = AsyncMock(), AsyncMock()
    monkeypatch.setattr(producer_module, "sleep", sleep)
    assert asyncio.run(produce(ProducerConfig(count=0), submit)) == 0
    submit.assert_not_awaited()
    sleep.assert_not_awaited()


def test_failure_retains_message_and_stops_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = []
    ticks = iter([0, 1, 2, 3, 4, 5])
    monkeypatch.setattr(producer_module, "monotonic", lambda: next(ticks))

    async def submit(message: SmsMessage) -> None:
        messages.append(message)
        if len(messages) == 2:
            raise SubmissionError("HTTP 409")

    with pytest.raises(ProductionError, match="HTTP 409") as caught:
        asyncio.run(
            produce(
                ProducerConfig(count=3),
                submit,
            )
        )
    assert caught.value.completed == 1
    assert caught.value.message is messages[1]
    assert len(messages) == 2


@pytest.mark.parametrize("length", [0, 1, 99, 100])
def test_generation_preserves_contract_and_injected_values(
    monkeypatch: pytest.MonkeyPatch,
    length: int,
) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    monkeypatch.setattr(producer_module, "uuid4", lambda: UUID(int=1))
    message = generate_message(
        length,
        rng=random.Random(7),
        utc_now=lambda: now,
    )
    assert message.body == "".join(random.Random(7).choices(ALPHABET, k=length))
    assert len(message.body) == length
    assert message.message_id == UUID(int=1)
    assert message.created_at == now
    assert message.schema_version == 1
    assert message.message_type == "sms_message"
    assert SmsMessage.model_validate_json(message.model_dump_json()) == message


@pytest.mark.parametrize("length", [-1, 101, True, 2.5, "5"])
def test_invalid_length(length: object) -> None:
    with pytest.raises(ValueError, match="body_length"):
        generate_message(length)


@pytest.mark.parametrize(
    "count, latency, sizes, starts, waits",
    [
        (10, 0, [5, 5], [0, 1], [1]),
        (10, 0.25, [5, 5], [0, 1], [0.75]),
        (10, 2, [5, 5], [0, 2], []),
        (11, 0, [5, 5, 1], [0, 1, 2], [1, 1]),
        (3, 0, [3], [0], []),
        (0, 0, [], [], []),
    ],
)
def test_batch_counts_and_pacing(
    monkeypatch: pytest.MonkeyPatch,
    count: int,
    latency: float,
    sizes: list[int],
    starts: list[float],
    waits: list[float],
) -> None:
    clock = [0.0]
    batches = []
    observed_starts, observed_waits = [], []
    ids = iter(UUID(int=n) for n in range(1, count + 1))
    monkeypatch.setattr(producer_module, "monotonic", lambda: clock[0])
    monkeypatch.setattr(producer_module, "uuid4", lambda: next(ids))
    single = AsyncMock()

    async def sleep(delay: float) -> None:
        observed_waits.append(delay)
        clock[0] += delay

    async def submit_batch(messages: list[SmsMessage]) -> None:
        batches.append(messages)
        observed_starts.append(clock[0])
        clock[0] += latency

    monkeypatch.setattr(producer_module, "sleep", sleep)
    assert (
        asyncio.run(
            produce(
                ProducerConfig(count=count, batch_size=5, rate=5),
                single,
                submit_batch=submit_batch,
            )
        )
        == count
    )
    assert [len(batch) for batch in batches] == sizes
    assert observed_starts == pytest.approx(starts)
    assert observed_waits == pytest.approx(waits)
    assert [m.message_id for batch in batches for m in batch] == [
        UUID(int=n) for n in range(1, count + 1)
    ]
    single.assert_not_awaited()


def test_batch_failure_retains_all_unconfirmed_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter(range(20))
    monkeypatch.setattr(producer_module, "monotonic", lambda: next(ticks))
    batch = AsyncMock(side_effect=[None, SubmissionError("full")])
    with pytest.raises(ProductionError, match="5 unconfirmed") as caught:
        asyncio.run(
            produce(
                ProducerConfig(count=15, batch_size=5, rate=5),
                AsyncMock(),
                submit_batch=batch,
            )
        )
    assert caught.value.completed == 5
    assert caught.value.messages == tuple(batch.await_args_list[1].args[0])
    assert caught.value.message is caught.value.messages[0]
    assert batch.await_count == 2


def test_batch_requires_a_submission_callback() -> None:
    with pytest.raises(ValueError, match="submit_batch"):
        asyncio.run(produce(ProducerConfig(batch_size=5), AsyncMock()))
