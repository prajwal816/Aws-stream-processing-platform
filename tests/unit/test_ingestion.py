"""
Unit tests for the Ingestion Service.
"""

import json
import os
import sys
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "services", "ingestion-service"))

os.environ["AWS_SAM_LOCAL"] = "true"
os.environ["STAGE"] = "test"
os.environ["LOG_LEVEL"] = "ERROR"

from tests.unit.services_test_helpers import reset_all
import handler


def setup_function():
    """Reset state before each test."""
    reset_all()


class TestIngestRecord:
    """Tests for single record ingestion."""

    def test_ingest_valid_sensor_reading(self):
        event = {
            "httpMethod": "POST",
            "path": "/ingest",
            "body": json.dumps({
                "source_id": "sensor-temp-001",
                "value": 22.5,
                "unit": "celsius",
                "record_type": "sensor_reading",
            }),
            "headers": {},
        }
        result = handler.ingest_record(event)
        assert result["statusCode"] == 201
        body = json.loads(result["body"])
        assert body["status"] == "success"
        assert body["data"]["status"] == "ingested"
        assert "event_id" in body["data"]

    def test_ingest_valid_transaction(self):
        event = {
            "httpMethod": "POST",
            "path": "/ingest",
            "body": json.dumps({
                "source_id": "payment-gateway",
                "amount": 99.99,
                "currency": "USD",
                "category": "electronics",
                "record_type": "transaction",
            }),
            "headers": {},
        }
        result = handler.ingest_record(event)
        assert result["statusCode"] == 201

    def test_ingest_valid_api_event(self):
        event = {
            "httpMethod": "POST",
            "path": "/ingest",
            "body": json.dumps({
                "source_id": "web-app",
                "event_type": "page_view",
                "payload": {"page": "/home"},
                "record_type": "api_event",
            }),
            "headers": {},
        }
        result = handler.ingest_record(event)
        assert result["statusCode"] == 201

    def test_ingest_missing_body(self):
        event = {
            "httpMethod": "POST",
            "path": "/ingest",
            "body": "{}",
            "headers": {},
        }
        result = handler.ingest_record(event)
        assert result["statusCode"] == 400

    def test_ingest_invalid_json(self):
        event = {
            "httpMethod": "POST",
            "path": "/ingest",
            "body": "not-json",
            "headers": {},
        }
        result = handler.ingest_record(event)
        assert result["statusCode"] == 400

    def test_ingest_missing_required_field(self):
        event = {
            "httpMethod": "POST",
            "path": "/ingest",
            "body": json.dumps({
                "value": 22.5,
                "unit": "celsius",
            }),
            "headers": {},
        }
        result = handler.ingest_record(event)
        assert result["statusCode"] == 422

    def test_ingest_invalid_unit(self):
        event = {
            "httpMethod": "POST",
            "path": "/ingest",
            "body": json.dumps({
                "source_id": "sensor-001",
                "value": 22.5,
                "unit": "invalid_unit",
            }),
            "headers": {},
        }
        result = handler.ingest_record(event)
        assert result["statusCode"] == 422

    def test_cors_headers_present(self):
        event = {
            "httpMethod": "POST",
            "path": "/ingest",
            "body": json.dumps({
                "source_id": "sensor-001",
                "value": 22.5,
                "unit": "celsius",
            }),
            "headers": {},
        }
        result = handler.ingest_record(event)
        assert "Access-Control-Allow-Origin" in result["headers"]


class TestBatchIngest:
    """Tests for batch ingestion."""

    def test_batch_ingest_valid(self):
        records = [
            {"source_id": f"sensor-{i}", "value": 20 + i, "unit": "celsius"}
            for i in range(10)
        ]
        event = {
            "httpMethod": "POST",
            "path": "/ingest/batch",
            "body": json.dumps({"records": records}),
            "headers": {},
        }
        result = handler.batch_ingest(event)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["data"]["ingested"] == 10
        assert body["data"]["failed"] == 0

    def test_batch_ingest_mixed_validity(self):
        records = [
            {"source_id": "valid-1", "value": 22, "unit": "celsius"},
            {"value": 22, "unit": "celsius"},  # missing source_id
            {"source_id": "valid-2", "value": 25, "unit": "celsius"},
        ]
        event = {
            "httpMethod": "POST",
            "path": "/ingest/batch",
            "body": json.dumps({"records": records}),
            "headers": {},
        }
        result = handler.batch_ingest(event)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["data"]["ingested"] == 2
        assert body["data"]["failed"] == 1

    def test_batch_ingest_empty(self):
        event = {
            "httpMethod": "POST",
            "path": "/ingest/batch",
            "body": json.dumps({"records": []}),
            "headers": {},
        }
        result = handler.batch_ingest(event)
        assert result["statusCode"] == 422


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_check(self):
        event = {"httpMethod": "GET", "path": "/health", "headers": {}}
        result = handler.health_check(event)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["data"]["status"] == "healthy"
        assert "checks" in body["data"]


class TestLambdaHandler:
    """Tests for the main Lambda router."""

    def test_route_health(self):
        event = {"httpMethod": "GET", "path": "/health", "headers": {}}
        result = handler.lambda_handler(event)
        assert result["statusCode"] == 200

    def test_route_ingest(self):
        event = {
            "httpMethod": "POST",
            "path": "/ingest",
            "body": json.dumps({"source_id": "s1", "value": 1, "unit": "celsius"}),
            "headers": {},
        }
        result = handler.lambda_handler(event)
        assert result["statusCode"] == 201

    def test_route_not_found(self):
        event = {"httpMethod": "GET", "path": "/unknown", "headers": {}}
        result = handler.lambda_handler(event)
        assert result["statusCode"] == 404
