import sqlite3
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
    assert summary.total_latency_sample_count == 2
    assert summary.average_total_latency_ms == 625
    assert summary.p90_total_latency_ms == 625
    assert summary.p99_total_latency_ms == 625
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
    assert summary.total_latency_sample_count == 0
    assert summary.average_total_latency_ms is None
    assert summary.p90_total_latency_ms is None
    assert summary.p99_total_latency_ms is None
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


def test_events_without_latency_remain_queryable(
    tmp_path: Path, event: SenderResult
) -> None:
    repository = MetricsRepository(tmp_path / "legacy-event.sqlite3")
    legacy_event = event.model_copy(update={"total_latency_ms": None})
    assert repository.add(legacy_event) is True

    items, total = repository.list()
    assert total == 1
    assert items == [legacy_event]
    assert repository.summary().total_latency_sample_count == 0


def test_existing_database_schema_is_migrated(
    tmp_path: Path, event: SenderResult
) -> None:
    path = tmp_path / "pre-latency.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE metric_events (
            event_id TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            message_type TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            status TEXT NOT NULL,
            processing_duration_ms REAL NOT NULL,
            error_code TEXT
        )
        """
    )
    connection.commit()
    connection.close()

    repository = MetricsRepository(path)
    assert repository.add(event) is True
    items, total = repository.list()
    assert total == 1
    assert items == [event]
