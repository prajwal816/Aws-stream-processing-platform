"""
Unit tests for shared utilities.
"""

import json
import os
import sys
import pytest
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

os.environ["AWS_SAM_LOCAL"] = "true"
os.environ["STAGE"] = "test"
os.environ["LOG_LEVEL"] = "ERROR"


class TestStructuredLogger:
    """Tests for the structured logger."""

    def test_create_logger(self):
        from shared.utils.logger import StructuredLogger
        logger = StructuredLogger("test-service")
        assert logger.service_name == "test-service"

    def test_set_correlation_id(self):
        from shared.utils.logger import StructuredLogger
        logger = StructuredLogger("test-service")
        cid = logger.set_correlation_id()
        assert cid is not None
        assert len(cid) == 36  # UUID format

    def test_set_custom_correlation_id(self):
        from shared.utils.logger import StructuredLogger
        logger = StructuredLogger("test-service")
        cid = logger.set_correlation_id("my-custom-id")
        assert cid == "my-custom-id"

    def test_timer(self):
        from shared.utils.logger import StructuredLogger
        logger = StructuredLogger("test-service")
        logger.start_timer("test_op")
        time.sleep(0.01)
        duration = logger.end_timer("test_op")
        assert duration >= 10  # At least 10ms

    def test_get_logger_singleton(self):
        from shared.utils.logger import get_logger
        l1 = get_logger("singleton-test")
        l2 = get_logger("singleton-test")
        assert l1 is l2


class TestMetricsCollector:
    """Tests for the metrics collector."""

    def test_record_metric(self):
        from shared.utils.metrics import MetricsCollector, MetricUnit
        m = MetricsCollector("test")
        m.record("test_metric", 42, MetricUnit.COUNT)
        assert m.get_counter("test_metric") == 42

    def test_increment(self):
        from shared.utils.metrics import MetricsCollector
        m = MetricsCollector("test")
        m.increment("counter")
        m.increment("counter")
        m.increment("counter", 3)
        assert m.get_counter("counter") == 5

    def test_average(self):
        from shared.utils.metrics import MetricsCollector
        m = MetricsCollector("test")
        for v in [10, 20, 30]:
            m.record("avg_test", v)
        assert m.get_average("avg_test") == 20.0

    def test_percentile(self):
        from shared.utils.metrics import MetricsCollector
        m = MetricsCollector("test")
        for v in range(1, 101):
            m.record("pct_test", v)
        p50 = m.get_percentile("pct_test", 50)
        assert 49 <= p50 <= 51

    def test_summary(self):
        from shared.utils.metrics import MetricsCollector
        m = MetricsCollector("test")
        m.increment("requests", 100)
        summary = m.get_summary()
        assert summary["service"] == "test"
        assert summary["counters"]["requests"] == 100

    def test_cost_estimate(self):
        from shared.utils.metrics import MetricsCollector
        m = MetricsCollector("test")
        m.increment("lambda_invocations", 1000)
        m.increment("dynamodb_read_operations", 500)
        m.increment("dynamodb_write_operations", 200)
        m.increment("api_requests", 1000)
        cost = m.get_cost_estimate()
        assert cost["currency"] == "USD"
        assert cost["total_estimated_cost"] >= 0

    def test_reset(self):
        from shared.utils.metrics import MetricsCollector
        m = MetricsCollector("test")
        m.increment("x", 100)
        m.reset()
        assert m.get_counter("x") == 0


class TestDynamoDBClient:
    """Tests for the local DynamoDB client."""

    def test_put_and_get(self):
        from shared.utils.dynamodb import DynamoDBClient
        client = DynamoDBClient()
        client.register_table("test_table", "id", "ts")
        client.put_item("test_table", {"id": "pk1", "ts": "2024", "data": "hello"})
        item = client.get_item("test_table", {"id": "pk1", "ts": "2024"})
        assert item is not None
        assert item["data"] == "hello"

    def test_delete(self):
        from shared.utils.dynamodb import DynamoDBClient
        client = DynamoDBClient()
        client.register_table("test_del", "id")
        client.put_item("test_del", {"id": "d1", "val": 1})
        assert client.delete_item("test_del", {"id": "d1"})
        assert client.get_item("test_del", {"id": "d1"}) is None

    def test_query(self):
        from shared.utils.dynamodb import DynamoDBClient
        client = DynamoDBClient()
        client.register_table("test_q", "pk", "sk")
        for i in range(5):
            client.put_item("test_q", {"pk": "group1", "sk": f"item-{i}", "val": i})
        results = client.query("test_q", partition_value="group1")
        assert len(results) == 5

    def test_batch_write(self):
        from shared.utils.dynamodb import DynamoDBClient
        client = DynamoDBClient()
        client.register_table("test_batch", "id")
        items = [{"id": f"b{i}", "val": i} for i in range(10)]
        count = client.batch_write("test_batch", items)
        assert count == 10
        assert client.item_count("test_batch") == 10

    def test_scan(self):
        from shared.utils.dynamodb import DynamoDBClient
        client = DynamoDBClient()
        client.register_table("test_scan", "id")
        for i in range(3):
            client.put_item("test_scan", {"id": f"s{i}"})
        results = client.scan("test_scan")
        assert len(results) == 3


class TestEventBus:
    """Tests for the event bus."""

    def test_publish_subscribe(self):
        from shared.utils.event_bus import EventBus
        bus = EventBus()
        received = []
        bus.subscribe("test.topic", lambda msg: received.append(msg))
        bus.publish("test.topic", {"key": "value"})
        assert len(received) == 1
        assert received[0]["key"] == "value"

    def test_multiple_subscribers(self):
        from shared.utils.event_bus import EventBus
        bus = EventBus()
        results = []
        bus.subscribe("multi", lambda msg: results.append("a"))
        bus.subscribe("multi", lambda msg: results.append("b"))
        bus.publish("multi", {})
        assert len(results) == 2

    def test_retry_on_failure(self):
        from shared.utils.event_bus import EventBus
        bus = EventBus(max_retries=2, retry_delay_ms=1)
        call_count = [0]

        def failing_handler(msg):
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("fail")

        bus.subscribe("retry", failing_handler)
        bus.publish("retry", {})
        assert call_count[0] == 3  # 1 initial + 2 retries

    def test_dead_letter_queue(self):
        from shared.utils.event_bus import EventBus
        bus = EventBus(max_retries=1, retry_delay_ms=1)
        bus.subscribe("dlq_test", lambda msg: (_ for _ in ()).throw(Exception("always fail")))
        bus.publish("dlq_test", {"data": 1})
        dlq = bus.get_dead_letter_queue()
        assert len(dlq) == 1

    def test_event_history(self):
        from shared.utils.event_bus import EventBus
        bus = EventBus()
        bus.subscribe("history", lambda msg: None)
        bus.publish("history", {"a": 1})
        bus.publish("history", {"a": 2})
        history = bus.get_event_history("history")
        assert len(history) == 2

    def test_stats(self):
        from shared.utils.event_bus import EventBus
        bus = EventBus()
        bus.subscribe("stats_topic", lambda msg: None)
        bus.publish("stats_topic", {})
        stats = bus.get_stats()
        assert stats["total_events"] == 1


class TestValidators:
    """Tests for input validators."""

    def test_validate_sensor_reading(self):
        from shared.utils.validators import validate_record
        result = validate_record({
            "source_id": "sensor-1",
            "value": 22.5,
            "unit": "celsius",
        }, "sensor_reading")
        assert result["record_type"] == "sensor_reading"
        assert "timestamp" in result

    def test_validate_missing_required(self):
        from shared.utils.validators import validate_record, ValidationError
        with pytest.raises(ValidationError):
            validate_record({"value": 22}, "sensor_reading")

    def test_validate_empty_record(self):
        from shared.utils.validators import validate_record, ValidationError
        with pytest.raises(ValidationError):
            validate_record({})

    def test_validate_batch(self):
        from shared.utils.validators import validate_batch
        records = [
            {"source_id": "s1", "value": 22, "unit": "celsius"},
            {"value": 22},  # invalid
            {"source_id": "s3", "value": 25, "unit": "celsius"},
        ]
        result = validate_batch(records, "sensor_reading")
        assert result["valid_count"] == 2
        assert result["invalid_count"] == 1

    def test_validate_unknown_type(self):
        from shared.utils.validators import validate_record, ValidationError
        with pytest.raises(ValidationError):
            validate_record({"source_id": "s1"}, "unknown_type")


class TestResponseBuilder:
    """Tests for API response builder."""

    def test_success_response(self):
        from shared.utils.response import api_response
        result = api_response(200, {"key": "value"}, message="OK")
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["status"] == "success"
        assert body["data"]["key"] == "value"

    def test_error_response(self):
        from shared.utils.response import error_response
        result = error_response(500, "Something broke")
        assert result["statusCode"] == 500
        body = json.loads(result["body"])
        assert body["status"] == "error"

    def test_bad_request(self):
        from shared.utils.response import bad_request
        result = bad_request("Missing field")
        assert result["statusCode"] == 400

    def test_not_found(self):
        from shared.utils.response import not_found
        result = not_found()
        assert result["statusCode"] == 404

    def test_cors_headers(self):
        from shared.utils.response import api_response
        result = api_response(200)
        assert result["headers"]["Access-Control-Allow-Origin"] == "*"


class TestSettings:
    """Tests for configuration settings."""

    def test_default_settings(self):
        from shared.configs.settings import Settings
        s = Settings()
        assert s.stage in ["dev", "test"]
        assert s.is_local is True

    def test_table_name_prefix(self):
        from shared.configs.settings import Settings
        s = Settings()
        assert "test" in s.raw_events_table or "dev" in s.raw_events_table

    def test_to_dict(self):
        from shared.configs.settings import Settings
        s = Settings()
        d = s.to_dict()
        assert "STAGE" in d
        assert "RAW_EVENTS_TABLE" in d


class TestEventSchemas:
    """Tests for event data schemas."""

    def test_raw_event_creation(self):
        from shared.schemas.events import RawEvent
        evt = RawEvent(source_id="s1", timestamp="2024-01-01")
        assert evt.source_id == "s1"
        assert evt.event_id is not None
        assert evt.ttl_expiry > 0

    def test_raw_event_to_dict(self):
        from shared.schemas.events import RawEvent
        evt = RawEvent(source_id="s1", timestamp="2024-01-01", value=42)
        d = evt.to_dict()
        assert d["source_id"] == "s1"
        assert d["value"] == 42

    def test_processed_record(self):
        from shared.schemas.events import ProcessedRecord
        rec = ProcessedRecord(
            record_id="r1", processed_at="2024-01-01",
            source_event_id="e1", source_id="s1", event_type="sensor",
        )
        assert rec.aggregation_key == "s1#general"

    def test_analytics_summary_update(self):
        from shared.schemas.events import AnalyticsSummary
        summary = AnalyticsSummary(metric_name="test", period="daily#2024-01-01")
        summary.update_with_value(10)
        summary.update_with_value(20)
        assert summary.count == 2
        assert summary.avg_value == 15.0
        assert summary.min_value == 10
        assert summary.max_value == 20
