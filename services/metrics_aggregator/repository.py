import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from math import ceil
from pathlib import Path
from typing import Literal
from uuid import UUID

from services.metrics_aggregator.models import MetricsSummary
from shared import SenderResult

MetricStatus = Literal["sent", "failed"]


class MetricsRepository:
    """Use one configured SQLite connection and transaction per operation."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        if self.database_path == ":memory:":
            raise ValueError(
                "database_path must be file-backed when using per-operation connections"
            )
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        # SQLite disables foreign-key enforcement separately on every connection.
        connection.execute("PRAGMA foreign_keys = ON")
        # Wait up to five seconds for another connection to release a database lock.
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize_database(self) -> None:
        connection = self._connect()
        try:
            # Persist write-ahead logging so readers can continue during a write.
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS metric_events (
                    event_id TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL,
                    message_type TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('sent', 'failed')),
                    processing_duration_ms REAL NOT NULL CHECK (
                        processing_duration_ms >= 0
                    ),
                    error_code TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS metric_events_occurred_at_idx
                ON metric_events (occurred_at DESC, event_id DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS metric_events_status_idx
                ON metric_events (status)
                """
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection, None, None]:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def add(self, event: SenderResult) -> bool:
        event = SenderResult.model_validate(event)
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO metric_events (
                    event_id, schema_version, message_type, event_type,
                    message_id, attempt_id, sender_id, occurred_at, status,
                    processing_duration_ms, error_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(event.event_id),
                    event.schema_version,
                    event.message_type,
                    event.event_type,
                    str(event.message_id),
                    str(event.attempt_id),
                    event.sender_id,
                    event.occurred_at.isoformat(),
                    event.status,
                    event.processing_duration_ms,
                    event.error_code,
                ),
            )
            return cursor.rowcount == 1

    def list(
        self,
        *,
        status: MetricStatus | None = None,
        sender_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[SenderResult], int]:
        conditions: list[str] = []
        parameters: list[object] = []
        if status is not None:
            conditions.append("status = ?")
            parameters.append(status)
        if sender_id is not None:
            conditions.append("sender_id = ?")
            parameters.append(sender_id)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self._transaction() as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM metric_events" + where, parameters
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM metric_events"
                + where
                + " ORDER BY occurred_at DESC, event_id DESC LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
        return [self._to_event(row) for row in rows], total

    def summary(self) -> MetricsSummary:
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(status = 'sent'), 0) AS sent,
                    COALESCE(SUM(status = 'failed'), 0) AS failed,
                    COALESCE(AVG(processing_duration_ms), 0) AS average_duration,
                    COUNT(DISTINCT sender_id) AS sender_count,
                    MAX(occurred_at) AS latest_occurred_at
                FROM metric_events
                """
            ).fetchone()
            total = int(row["total"])
            p90_duration = 0.0
            p99_duration = 0.0
            if total:
                p90_rank = ceil(0.90 * total)
                p99_rank = ceil(0.99 * total)
                p90_duration = self._duration_at_rank(connection, p90_rank)
                p99_duration = self._duration_at_rank(connection, p99_rank)
        failed = int(row["failed"])
        return MetricsSummary(
            total=total,
            sent=int(row["sent"]),
            failed=failed,
            failure_rate=failed / total if total else 0,
            average_processing_duration_ms=float(row["average_duration"]),
            p90_processing_duration_ms=p90_duration,
            p99_processing_duration_ms=p99_duration,
            sender_count=int(row["sender_count"]),
            latest_occurred_at=row["latest_occurred_at"],
        )

    def count(self) -> int:
        with self._transaction() as connection:
            return int(
                connection.execute("SELECT COUNT(*) FROM metric_events").fetchone()[0]
            )

    @staticmethod
    def _duration_at_rank(connection: sqlite3.Connection, rank: int) -> float:
        """Find the processing time at the requested place in the sorted results."""
        row = connection.execute(
            """
            SELECT processing_duration_ms
            FROM metric_events
            ORDER BY processing_duration_ms ASC
            LIMIT 1 OFFSET ?
            """,
            (rank - 1,),
        ).fetchone()
        return float(row[0])

    @staticmethod
    def _to_event(row: sqlite3.Row) -> SenderResult:
        """Turn one database row into a sender result the application can use."""
        return SenderResult(
            schema_version=row["schema_version"],
            message_type=row["message_type"],
            event_id=UUID(row["event_id"]),
            event_type=row["event_type"],
            message_id=UUID(row["message_id"]),
            attempt_id=UUID(row["attempt_id"]),
            sender_id=row["sender_id"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            status=row["status"],
            processing_duration_ms=row["processing_duration_ms"],
            error_code=row["error_code"],
        )
