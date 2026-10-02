from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from shared import SenderResult


class _Response(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IngestResponse(_Response):
    status: Literal["accepted", "duplicate"]
    event_id: UUID


class MetricsPage(_Response):
    items: list[SenderResult]
    total: Annotated[int, Field(ge=0)]
    limit: Annotated[int, Field(ge=1, le=1000)]
    offset: Annotated[int, Field(ge=0)]


class MetricsSummary(_Response):
    total: Annotated[int, Field(ge=0)]
    sent: Annotated[int, Field(ge=0)]
    failed: Annotated[int, Field(ge=0)]
    failure_rate: Annotated[float, Field(ge=0, le=1)]
    average_processing_duration_ms: Annotated[float, Field(ge=0)]
    p90_processing_duration_ms: Annotated[float, Field(ge=0)]
    p99_processing_duration_ms: Annotated[float, Field(ge=0)]
    total_latency_sample_count: Annotated[int, Field(ge=0)]
    average_total_latency_ms: Annotated[float, Field(ge=0)] | None
    p90_total_latency_ms: Annotated[float, Field(ge=0)] | None
    p99_total_latency_ms: Annotated[float, Field(ge=0)] | None
    sender_count: Annotated[int, Field(ge=0)]
    latest_occurred_at: datetime | None


class HealthResponse(_Response):
    status: Literal["ok"] = "ok"
    stored_events: Annotated[int, Field(ge=0)]
