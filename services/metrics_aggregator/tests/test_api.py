import asyncio
from pathlib import Path

import httpx

from services.metrics_aggregator import MetricsRepository, create_app
from shared import SenderResult


def test_ingestion_queries_health_and_dashboard(
    tmp_path: Path, event: SenderResult
) -> None:
    async def scenario() -> None:
        repository = MetricsRepository(tmp_path / "api.sqlite3")
        app = create_app(repository=repository)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://metrics"
        ) as client:
            response = await client.post("/metrics", json=event.model_dump(mode="json"))
            assert response.status_code == 202
            assert response.json() == {
                "status": "accepted",
                "event_id": str(event.event_id),
            }
            duplicate = await client.post(
                "/metrics", json=event.model_dump(mode="json")
            )
            assert duplicate.status_code == 200
            assert duplicate.json()["status"] == "duplicate"

            page = (await client.get("/metrics?status=sent&limit=1")).json()
            assert page["total"] == 1
            assert page["items"][0]["message_id"] == str(event.message_id)
            summary = (await client.get("/metrics/summary")).json()
            assert summary["sent"] == 1
            assert summary["p90_processing_duration_ms"] == 125
            assert summary["p99_processing_duration_ms"] == 125
            assert summary["total_latency_sample_count"] == 1
            assert summary["average_total_latency_ms"] == 625
            assert summary["p90_total_latency_ms"] == 625
            assert summary["p99_total_latency_ms"] == 625
            assert (await client.get("/health")).json() == {
                "status": "ok",
                "stored_events": 1,
            }
            dashboard = await client.get("/")
            assert dashboard.status_code == 200
            assert "SMS delivery metrics" in dashboard.text
            assert "Overall delivery" in dashboard.text
            assert "Sender service" in dashboard.text
            assert "Average total latency" in dashboard.text
            assert "Average sender processing duration" in dashboard.text
            assert "setInterval(refresh, 1000)" in dashboard.text

    asyncio.run(scenario())


def test_rejects_invalid_events_and_query_bounds(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository = MetricsRepository(tmp_path / "invalid.sqlite3")
        app = create_app(repository=repository)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://metrics"
        ) as client:
            assert (await client.post("/metrics", json={})).status_code == 422
            assert (await client.get("/metrics?limit=0")).status_code == 422
            assert (await client.get("/metrics?status=unknown")).status_code == 422

    asyncio.run(scenario())
