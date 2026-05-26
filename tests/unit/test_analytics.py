"""
Unit tests for the Analytics Service.
"""

import json
import os
import sys
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "services", "analytics-service"))

os.environ["AWS_SAM_LOCAL"] = "true"
os.environ["STAGE"] = "test"
os.environ["LOG_LEVEL"] = "ERROR"

from tests.unit.services_test_helpers import reset_all, load_service_handler


def setup_function():
    reset_all()


class TestStatisticsEngine:
    """Tests for the statistics computation engine."""

    def test_compute_summary_empty(self):
        from statistics_engine import StatisticsEngine
        engine = StatisticsEngine()
        result = engine.compute_summary_stats([])
        assert result["total_records"] == 0

    def test_compute_summary_with_data(self):
        from statistics_engine import StatisticsEngine
        engine = StatisticsEngine()
        summaries = [
            {"count": 100, "sum_value": 2500, "min_value": 10, "max_value": 50, "metric_name": "temp"},
            {"count": 50, "sum_value": 1000, "min_value": 5, "max_value": 40, "metric_name": "temp"},
        ]
        result = engine.compute_summary_stats(summaries)
        assert result["total_records"] == 150
        assert result["total_data_points"] == 2
        assert result["overall_min"] == 5
        assert result["overall_max"] == 50

    def test_compute_trend_increasing(self):
        from statistics_engine import StatisticsEngine
        engine = StatisticsEngine()
        data = [{"count": i * 10} for i in range(1, 11)]
        result = engine.compute_trend(data, field="count")
        assert result["direction"] == "increasing"
        assert result["change_percent"] > 0

    def test_compute_trend_decreasing(self):
        from statistics_engine import StatisticsEngine
        engine = StatisticsEngine()
        data = [{"count": (10 - i) * 10} for i in range(10)]
        result = engine.compute_trend(data, field="count")
        assert result["direction"] == "decreasing"

    def test_compute_percentiles(self):
        from statistics_engine import StatisticsEngine
        engine = StatisticsEngine()
        values = list(range(1, 101))
        result = engine.compute_percentiles(values)
        assert result["p50"] == 50 or result["p50"] == 51
        assert result["p95"] >= 95
        assert result["p99"] >= 99

    def test_compute_percentiles_empty(self):
        from statistics_engine import StatisticsEngine
        engine = StatisticsEngine()
        result = engine.compute_percentiles([])
        assert result["p50"] == 0


class TestQueryEngine:
    """Tests for the DynamoDB query engine."""

    def test_get_analytics_summaries_empty(self):
        from query_engine import QueryEngine
        engine = QueryEngine()
        result = engine.get_analytics_summaries()
        assert isinstance(result, list)

    def test_get_pipeline_stats(self):
        from query_engine import QueryEngine
        engine = QueryEngine()
        result = engine.get_pipeline_stats()
        assert "total_processed" in result
        assert "status_breakdown" in result

    def test_get_recent_records_empty(self):
        from query_engine import QueryEngine
        engine = QueryEngine()
        result = engine.get_recent_records()
        assert isinstance(result, list)


class TestAnalyticsHandler:
    """Tests for the analytics Lambda handler."""

    def test_get_analytics(self):
        handler = load_service_handler("analytics-service")
        event = {
            "httpMethod": "GET",
            "path": "/analytics",
            "queryStringParameters": {},
            "headers": {},
        }
        result = handler.get_analytics(event)
        assert result["statusCode"] == 200

    def test_get_dashboard_data(self):
        handler = load_service_handler("analytics-service")
        event = {
            "httpMethod": "GET",
            "path": "/analytics/dashboard",
            "queryStringParameters": {},
            "headers": {},
        }
        result = handler.get_dashboard_data(event)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "overview" in body["data"]
        assert "service_metrics" in body["data"]

    def test_route_not_found(self):
        handler = load_service_handler("analytics-service")
        event = {"httpMethod": "GET", "path": "/unknown", "headers": {}}
        result = handler.lambda_handler(event)
        assert result["statusCode"] == 404
