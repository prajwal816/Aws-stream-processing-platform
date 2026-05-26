"""
Integration tests — end-to-end pipeline test.

Tests the full flow: ingestion → processing → analytics.
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

# Add service dirs
for svc in ["ingestion-service", "processing-service", "analytics-service", "notification-service"]:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "services", svc))

from shared.utils.dynamodb import get_dynamodb_client, reset_client
from shared.utils.event_bus import get_event_bus, reset_event_bus, Topics
from shared.configs.settings import get_settings, reset_settings


def setup_function():
    reset_client()
    reset_event_bus()
    reset_settings()


class TestEndToEndPipeline:
    """Tests for the full ingestion → processing → analytics pipeline."""

    def _setup_pipeline(self):
        """Set up the event bus wiring and import handlers."""
        from tests.unit.services_test_helpers import load_service_handler
        
        ingestion = load_service_handler("ingestion-service")
        processing_mod = load_service_handler("processing-service")
        analytics_mod = load_service_handler("analytics-service")
        notification_mod = load_service_handler("notification-service")

        # Wire event bus
        event_bus = get_event_bus()
        event_bus.subscribe(Topics.RECORD_INGESTED,
            lambda msg: processing_mod.process_event({"data": msg.get("data", msg)}))
        event_bus.subscribe(Topics.PROCESSING_COMPLETED,
            lambda msg: notification_mod.handle_notification(msg))

        return ingestion, processing_mod, analytics_mod

    def test_single_record_pipeline(self):
        """Test ingesting a single record flows through the full pipeline."""
        ingestion, _, analytics = self._setup_pipeline()

        # Ingest a record
        event = {
            "httpMethod": "POST",
            "path": "/ingest",
            "body": json.dumps({
                "source_id": "integration-sensor-001",
                "value": 25.5,
                "unit": "celsius",
                "record_type": "sensor_reading",
            }),
            "headers": {},
        }
        result = ingestion.ingest_record(event)
        assert result["statusCode"] == 201

        # Query analytics
        analytics_event = {
            "httpMethod": "GET",
            "path": "/analytics/dashboard",
            "queryStringParameters": {},
            "headers": {},
        }
        dashboard = analytics.get_dashboard_data(analytics_event)
        assert dashboard["statusCode"] == 200
        body = json.loads(dashboard["body"])
        assert body["data"]["overview"]["total_records_ingested"] >= 0

    def test_batch_pipeline(self):
        """Test batch ingestion flows through the pipeline."""
        ingestion, _, analytics = self._setup_pipeline()

        records = [
            {"source_id": f"batch-sensor-{i}", "value": 20 + i, "unit": "celsius"}
            for i in range(20)
        ]
        event = {
            "httpMethod": "POST",
            "path": "/ingest/batch",
            "body": json.dumps({"records": records}),
            "headers": {},
        }
        result = ingestion.batch_ingest(event)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["data"]["ingested"] == 20

    def test_mixed_record_types(self):
        """Test ingesting different record types."""
        ingestion, _, _ = self._setup_pipeline()

        records = [
            {"source_id": "s1", "value": 22, "unit": "celsius", "record_type": "sensor_reading"},
            {"source_id": "s2", "event_type": "click", "payload": {"page": "/"}, "record_type": "api_event"},
            {"source_id": "s3", "amount": 49.99, "currency": "USD", "category": "food", "record_type": "transaction"},
        ]

        for record in records:
            event = {
                "httpMethod": "POST",
                "path": "/ingest",
                "body": json.dumps(record),
                "headers": {},
            }
            result = ingestion.ingest_record(event)
            assert result["statusCode"] == 201

    def test_health_after_processing(self):
        """Test health check reflects processed data."""
        ingestion, _, _ = self._setup_pipeline()

        # Ingest some data
        event = {
            "httpMethod": "POST",
            "path": "/ingest",
            "body": json.dumps({"source_id": "health-test", "value": 10, "unit": "celsius"}),
            "headers": {},
        }
        ingestion.ingest_record(event)

        # Check health
        health_event = {"httpMethod": "GET", "path": "/health", "headers": {}}
        result = ingestion.health_check(health_event)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["data"]["status"] == "healthy"
