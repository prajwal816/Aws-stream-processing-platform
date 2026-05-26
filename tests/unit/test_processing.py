"""
Unit tests for the Processing Service.
"""

import json
import os
import sys
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "services", "processing-service"))

os.environ["AWS_SAM_LOCAL"] = "true"
os.environ["STAGE"] = "test"
os.environ["LOG_LEVEL"] = "ERROR"

from tests.unit.services_test_helpers import reset_all


def setup_function():
    reset_all()


class TestTransformer:
    """Tests for the data transformer."""

    def test_temperature_normalization_fahrenheit(self):
        from transformer import DataTransformer
        t = DataTransformer()
        result = t.transform({
            "source_id": "sensor-1",
            "value": 212,
            "unit": "fahrenheit",
            "timestamp": "2024-01-01T12:00:00Z",
        })
        assert abs(result["normalized_value"] - 100.0) < 0.01
        assert result["normalized_unit"] == "celsius"
        assert "unit_conversion:fahrenheit->celsius" in result["transformations"]

    def test_temperature_normalization_kelvin(self):
        from transformer import DataTransformer
        t = DataTransformer()
        result = t.transform({
            "source_id": "sensor-1",
            "value": 373.15,
            "unit": "kelvin",
            "timestamp": "2024-01-01T12:00:00Z",
        })
        assert abs(result["normalized_value"] - 100.0) < 0.01

    def test_celsius_passthrough(self):
        from transformer import DataTransformer
        t = DataTransformer()
        result = t.transform({
            "source_id": "sensor-1",
            "value": 25.0,
            "unit": "celsius",
            "timestamp": "2024-01-01T12:00:00Z",
        })
        assert result["normalized_value"] == 25.0

    def test_category_classification_temperature(self):
        from transformer import DataTransformer
        t = DataTransformer()
        result = t.transform({
            "source_id": "sensor-temp-001",
            "value": 22,
            "unit": "celsius",
        })
        assert result["category"] == "temperature"

    def test_category_classification_humidity(self):
        from transformer import DataTransformer
        t = DataTransformer()
        result = t.transform({
            "source_id": "sensor-humidity-001",
            "value": 60,
            "unit": "percent",
        })
        assert result["category"] == "humidity"

    def test_category_classification_transaction(self):
        from transformer import DataTransformer
        t = DataTransformer()
        result = t.transform({
            "source_id": "payment-gw",
            "value": 99.99,
            "unit": "count",
            "record_type": "transaction",
        })
        assert result["category"] == "financial"

    def test_derived_metrics_added(self):
        from transformer import DataTransformer
        t = DataTransformer()
        result = t.transform({
            "source_id": "sensor-1",
            "value": 50,
            "unit": "celsius",
            "timestamp": "2024-01-01T14:00:00Z",
        })
        enrichment = result.get("enrichment", {})
        assert "magnitude" in enrichment
        assert "log_value" in enrichment
        assert enrichment.get("is_business_hours") is True

    def test_quality_adjustment(self):
        from transformer import DataTransformer
        t = DataTransformer()
        result = t.transform({
            "source_id": "sensor-1",
            "value": 25,
            "unit": "celsius",
            "quality_score": 0.95,
            "tags": ["production"],
            "metadata": {"a": 1, "b": 2, "c": 3},
        })
        # Quality should be boosted slightly for tags + metadata
        assert result["quality_score"] >= 0.95


class TestFilters:
    """Tests for the data filter."""

    def test_pass_valid_record(self):
        from filters import DataFilter
        f = DataFilter(quality_threshold=0.5)
        result = f.apply_filters({
            "source_id": "s1",
            "value": 22,
            "unit": "celsius",
            "quality_score": 0.9,
            "timestamp": "2024-01-01T00:00:00Z",
        })
        assert result["passed"] is True

    def test_filter_low_quality(self):
        from filters import DataFilter
        f = DataFilter(quality_threshold=0.5)
        result = f.apply_filters({
            "source_id": "s1",
            "value": 22,
            "quality_score": 0.1,
        })
        assert result["passed"] is False
        assert result["filter"] == "quality_threshold"

    def test_filter_duplicate(self):
        from filters import DataFilter
        f = DataFilter(enable_dedup=True)
        record = {"source_id": "s1", "value": 22, "timestamp": "2024-01-01", "unit": "c"}
        r1 = f.apply_filters(record)
        r2 = f.apply_filters(record)
        assert r1["passed"] is True
        assert r2["passed"] is False
        assert r2["filter"] == "deduplication"

    def test_filter_extreme_value(self):
        from filters import DataFilter
        f = DataFilter()
        result = f.apply_filters({
            "source_id": "s1",
            "value": 99999999,
            "record_type": "sensor_reading",
            "timestamp": "t1",
            "unit": "c",
        })
        assert result["passed"] is False
        assert result["filter"] == "value_range"


class TestAggregator:
    """Tests for the data aggregator."""

    def test_update_creates_summary(self):
        from aggregator import DataAggregator
        from shared.schemas.events import ProcessedRecord
        agg = DataAggregator()
        record = ProcessedRecord(
            record_id="r1", processed_at="2024-01-01T00:00:00Z",
            source_event_id="e1", source_id="s1", event_type="sensor_reading",
            category="temperature", normalized_value=25.0,
        )
        agg.update(record)
        aggregates = agg.get_all_aggregates()
        assert len(aggregates) > 0

    def test_multiple_updates_accumulate(self):
        from aggregator import DataAggregator
        from shared.schemas.events import ProcessedRecord
        agg = DataAggregator()
        for i in range(5):
            record = ProcessedRecord(
                record_id=f"r{i}", processed_at="2024-01-01T00:00:00Z",
                source_event_id=f"e{i}", source_id="s1", event_type="sensor_reading",
                category="temperature", normalized_value=20.0 + i,
            )
            agg.update(record)
        aggregates = agg.get_all_aggregates()
        # Should have global and category aggregates
        assert any("global" in k for k in aggregates)
