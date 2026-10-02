from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

from services.metrics_aggregator import MetricsRepository
from shared import SenderResult


def test_persists_deduplicates_queries_and_reopens(
    tmp_path: Path, event: SenderResult
) -> None:
    path = tmp_path / "metrics.sqlite3"
    repository = MetricsRepository(path)
    assert repository.add(event) is True
    assert repository.add(event.model_copy(update={"sender_id": "changed"})) is False
    failed = event.model_copy(
        update={
            "event_id": UUID(int=4),
            "attempt_id": UUID(int=5),
            "sender_id": "sms-sender-2",
            "status": "failed",
            "processing_duration_ms": 375,
            "error_code": "SIMULATED_SEND_FAILURE",
        }
    )
    assert repository.add(failed) is True

    items, total = repository.list(status="failed", limit=10)
    assert total == 1
    assert items == [failed]
    summary = repository.summary()
    assert summary.total == 2
    assert summary.sent == summary.failed == 1
    assert summary.failure_rate == 0.5
    assert summary.average_processing_duration_ms == 250
    assert summary.p90_processing_duration_ms == 375
    assert summary.p99_processing_duration_ms == 375
    assert summary.sender_count == 2
    reopened = MetricsRepository(path)
    assert reopened.count() == 2


def test_empty_summary(tmp_path: Path) -> None:
    repository = MetricsRepository(tmp_path / "empty.sqlite3")
    summary = repository.summary()
    assert summary.total == 0
    assert summary.failure_rate == 0
    assert summary.p90_processing_duration_ms == 0
    assert summary.p99_processing_duration_ms == 0
    assert summary.latest_occurred_at is None


def test_percentiles_use_nearest_rank(tmp_path: Path, event: SenderResult) -> None:
    repository = MetricsRepository(tmp_path / "percentiles.sqlite3")
    for value in range(1, 101):
        repository.add(
            event.model_copy(
                update={
                    "event_id": UUID(int=1000 + value),
                    "attempt_id": UUID(int=2000 + value),
                    "processing_duration_ms": float(value),
                }
            )
        )
    summary = repository.summary()
    assert summary.p90_processing_duration_ms == 90
    assert summary.p99_processing_duration_ms == 99


def test_concurrent_appends_use_independent_connections(
    tmp_path: Path, event: SenderResult
) -> None:
    repository = MetricsRepository(tmp_path / "concurrent.sqlite3")

    def add(value: int) -> bool:
        return repository.add(
            event.model_copy(
                update={
                    "event_id": UUID(int=3000 + value),
                    "attempt_id": UUID(int=4000 + value),
                }
            )
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert all(executor.map(add, range(50)))
    assert repository.count() == 50


def test_rejects_private_in_memory_database() -> None:
    try:
        MetricsRepository(":memory:")
    except ValueError as error:
        assert "file-backed" in str(error)
    else:
        raise AssertionError("expected an explicit error for :memory:")
