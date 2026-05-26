"""
API integration tests — tests the local server endpoints.
Run with: pytest tests/integration/test_api.py -v
Requires the local server to NOT be running (tests start their own).
"""

import json
import os
import sys
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

os.environ["AWS_SAM_LOCAL"] = "true"
os.environ["STAGE"] = "test"
os.environ["LOG_LEVEL"] = "ERROR"


@pytest.fixture
def client():
    """Create a Flask test client."""
    from scripts.local_server import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["status"] == "healthy"


class TestIngestionEndpoints:
    def test_ingest_single_record(self, client):
        resp = client.post("/ingest", json={
            "source_id": "api-test-sensor",
            "value": 23.5,
            "unit": "celsius",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["data"]["status"] == "ingested"

    def test_ingest_batch(self, client):
        records = [
            {"source_id": f"api-batch-{i}", "value": 20 + i, "unit": "celsius"}
            for i in range(5)
        ]
        resp = client.post("/ingest/batch", json={"records": records})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["ingested"] == 5

    def test_ingest_invalid_returns_error(self, client):
        resp = client.post("/ingest", json={})
        assert resp.status_code == 400


class TestAnalyticsEndpoints:
    def test_analytics_returns_200(self, client):
        resp = client.get("/analytics")
        assert resp.status_code == 200

    def test_dashboard_returns_200(self, client):
        resp = client.get("/analytics/dashboard")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "overview" in data["data"]

    def test_records_returns_200(self, client):
        resp = client.get("/analytics/records")
        assert resp.status_code == 200

    def test_metrics_returns_200(self, client):
        resp = client.get("/analytics/metrics")
        assert resp.status_code == 200


class TestNotificationEndpoints:
    def test_send_notification(self, client):
        resp = client.post("/notify", json={
            "status": "completed",
            "record_id": "test-r1",
            "source_service": "test",
        })
        assert resp.status_code == 200

    def test_list_notifications(self, client):
        resp = client.get("/notifications")
        assert resp.status_code == 200


class TestSimulationEndpoint:
    def test_simulate(self, client):
        resp = client.post("/api/simulate", json={"count": 10})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["ingested"] > 0


class TestCORS:
    def test_cors_headers(self, client):
        resp = client.post("/ingest", json={
            "source_id": "cors-test",
            "value": 1,
            "unit": "celsius",
        })
        assert "Access-Control-Allow-Origin" in resp.headers
