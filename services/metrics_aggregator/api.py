import os
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Query, Response, status
from fastapi.responses import HTMLResponse

from services.metrics_aggregator.dashboard import DASHBOARD_HTML
from services.metrics_aggregator.models import (
    HealthResponse,
    IngestResponse,
    MetricsPage,
    MetricsSummary,
)
from services.metrics_aggregator.repository import MetricsRepository
from shared import SenderResult


def create_app(
    *,
    database_path: str | Path | None = None,
    repository: MetricsRepository | None = None,
) -> FastAPI:
    if database_path is not None and repository is not None:
        raise ValueError("provide database_path or repository, not both")
    if repository is None:
        configured_path = database_path or os.environ.get(
            "METRICS_DB_PATH", "metrics.sqlite3"
        )
        repository = MetricsRepository(configured_path)

    app = FastAPI(title="SMS Metrics Aggregator", version="0.1.0")
    app.state.metrics_repository = repository

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard() -> str:
        return DASHBOARD_HTML

    @app.post(
        "/metrics",
        response_model=IngestResponse,
        status_code=status.HTTP_202_ACCEPTED,
        responses={200: {"model": IngestResponse, "description": "Duplicate event"}},
    )
    def ingest(event: SenderResult, response: Response) -> IngestResponse:
        accepted = repository.add(event)
        if not accepted:
            response.status_code = status.HTTP_200_OK
        return IngestResponse(
            status="accepted" if accepted else "duplicate", event_id=event.event_id
        )

    @app.get("/metrics", response_model=MetricsPage)
    def list_metrics(
        metric_status: Annotated[
            Literal["sent", "failed"] | None, Query(alias="status")
        ] = None,
        sender_id: Annotated[str | None, Query(min_length=1)] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> MetricsPage:
        items, total = repository.list(
            status=metric_status,
            sender_id=sender_id,
            limit=limit,
            offset=offset,
        )
        return MetricsPage(items=items, total=total, limit=limit, offset=offset)

    @app.get("/metrics/summary", response_model=MetricsSummary)
    def summary() -> MetricsSummary:
        return repository.summary()

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(stored_events=repository.count())

    return app
