"""
Custom metrics collection and reporting.

Tracks platform metrics (records processed, latency, errors, throughput)
and can publish to CloudWatch in production or store in-memory for
local simulation and dashboard display.
"""

import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class MetricUnit(str, Enum):
    COUNT = "Count"
    MILLISECONDS = "Milliseconds"
    BYTES = "Bytes"
    PERCENT = "Percent"
    SECONDS = "Seconds"
    NONE = "None"


@dataclass
class MetricDataPoint:
    """A single metric measurement."""
    name: str
    value: float
    unit: MetricUnit
    timestamp: str
    dimensions: dict[str, str] = field(default_factory=dict)
    service: str = ""


class MetricsCollector:
    """
    Thread-safe metrics collector that stores metrics in-memory
    and optionally publishes to CloudWatch.

    Usage:
        metrics = MetricsCollector("ingestion-service")
        metrics.record("records_ingested", 1, MetricUnit.COUNT)
        metrics.record("api_latency", 45.2, MetricUnit.MILLISECONDS)
        metrics.record("batch_size", 100, MetricUnit.COUNT)

        # Get summary
        summary = metrics.get_summary()
    """

    def __init__(self, service_name: str, publish_to_cloudwatch: bool = False):
        self.service_name = service_name
        self.publish_to_cloudwatch = publish_to_cloudwatch
        self._lock = threading.Lock()
        self._data_points: list[MetricDataPoint] = []
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, list[float]] = defaultdict(list)
        self._timers: dict[str, float] = {}

    def record(
        self,
        name: str,
        value: float,
        unit: MetricUnit = MetricUnit.COUNT,
        dimensions: Optional[dict[str, str]] = None,
    ) -> None:
        """Record a metric data point."""
        dp = MetricDataPoint(
            name=name,
            value=value,
            unit=unit,
            timestamp=datetime.now(timezone.utc).isoformat(),
            dimensions=dimensions or {},
            service=self.service_name,
        )
        with self._lock:
            self._data_points.append(dp)
            self._counters[name] += value
            self._gauges[name].append(value)

    def increment(self, name: str, amount: float = 1.0) -> None:
        """Increment a counter metric."""
        self.record(name, amount, MetricUnit.COUNT)

    def record_latency(self, name: str, latency_ms: float) -> None:
        """Record a latency measurement in milliseconds."""
        self.record(name, latency_ms, MetricUnit.MILLISECONDS)

    def start_timer(self, name: str) -> None:
        """Start a named timer."""
        self._timers[name] = time.time()

    def stop_timer(self, name: str) -> float:
        """Stop a named timer and record the duration."""
        start = self._timers.pop(name, None)
        if start is None:
            return 0.0
        duration_ms = (time.time() - start) * 1000
        self.record_latency(f"{name}_duration", duration_ms)
        return duration_ms

    def get_counter(self, name: str) -> float:
        """Get the current value of a counter."""
        with self._lock:
            return self._counters.get(name, 0.0)

    def get_average(self, name: str) -> float:
        """Get the average value of a gauge metric."""
        with self._lock:
            values = self._gauges.get(name, [])
            return sum(values) / len(values) if values else 0.0

    def get_percentile(self, name: str, percentile: float) -> float:
        """Get a percentile value of a gauge metric."""
        with self._lock:
            values = sorted(self._gauges.get(name, []))
            if not values:
                return 0.0
            idx = int(len(values) * percentile / 100)
            return values[min(idx, len(values) - 1)]

    def get_summary(self) -> dict[str, Any]:
        """Get a comprehensive metrics summary."""
        with self._lock:
            summary: dict[str, Any] = {
                "service": self.service_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_data_points": len(self._data_points),
                "counters": dict(self._counters),
                "gauges": {},
            }

            for name, values in self._gauges.items():
                sorted_values = sorted(values)
                summary["gauges"][name] = {
                    "count": len(values),
                    "min": min(values) if values else 0,
                    "max": max(values) if values else 0,
                    "avg": sum(values) / len(values) if values else 0,
                    "p50": sorted_values[len(sorted_values) // 2] if sorted_values else 0,
                    "p95": sorted_values[int(len(sorted_values) * 0.95)] if sorted_values else 0,
                    "p99": sorted_values[int(len(sorted_values) * 0.99)] if sorted_values else 0,
                    "sum": sum(values),
                }

            return summary

    def get_data_points(self, name: Optional[str] = None, limit: int = 1000) -> list[dict]:
        """Get raw data points, optionally filtered by metric name."""
        with self._lock:
            points = self._data_points
            if name:
                points = [dp for dp in points if dp.name == name]
            recent = points[-limit:]
            return [
                {
                    "name": dp.name,
                    "value": dp.value,
                    "unit": dp.unit.value,
                    "timestamp": dp.timestamp,
                    "dimensions": dp.dimensions,
                    "service": dp.service,
                }
                for dp in recent
            ]

    def reset(self) -> None:
        """Reset all collected metrics."""
        with self._lock:
            self._data_points.clear()
            self._counters.clear()
            self._gauges.clear()
            self._timers.clear()

    def get_cost_estimate(self) -> dict[str, Any]:
        """
        Estimate AWS costs based on collected metrics.
        Uses AWS pricing approximations for the free tier and on-demand pricing.
        """
        with self._lock:
            lambda_invocations = self._counters.get("lambda_invocations", 0)
            lambda_duration_ms = self._counters.get("lambda_execution_duration", 0)
            dynamodb_reads = self._counters.get("dynamodb_read_operations", 0)
            dynamodb_writes = self._counters.get("dynamodb_write_operations", 0)
            api_requests = self._counters.get("api_requests", 0)

            # Lambda pricing: $0.20 per 1M requests, $0.0000166667 per GB-second (128MB)
            lambda_request_cost = (lambda_invocations / 1_000_000) * 0.20
            lambda_compute_gb_sec = (lambda_duration_ms / 1000) * (128 / 1024)
            lambda_compute_cost = lambda_compute_gb_sec * 0.0000166667

            # DynamoDB: $1.25 per million WCU, $0.25 per million RCU (on-demand)
            dynamodb_write_cost = (dynamodb_writes / 1_000_000) * 1.25
            dynamodb_read_cost = (dynamodb_reads / 1_000_000) * 0.25

            # API Gateway: $3.50 per million requests
            api_cost = (api_requests / 1_000_000) * 3.50

            total = (
                lambda_request_cost + lambda_compute_cost
                + dynamodb_write_cost + dynamodb_read_cost + api_cost
            )

            return {
                "lambda": {
                    "invocations": lambda_invocations,
                    "request_cost": round(lambda_request_cost, 6),
                    "compute_cost": round(lambda_compute_cost, 6),
                    "total": round(lambda_request_cost + lambda_compute_cost, 6),
                },
                "dynamodb": {
                    "read_operations": dynamodb_reads,
                    "write_operations": dynamodb_writes,
                    "read_cost": round(dynamodb_read_cost, 6),
                    "write_cost": round(dynamodb_write_cost, 6),
                    "total": round(dynamodb_read_cost + dynamodb_write_cost, 6),
                },
                "api_gateway": {
                    "requests": api_requests,
                    "cost": round(api_cost, 6),
                },
                "total_estimated_cost": round(total, 4),
                "currency": "USD",
                "pricing_model": "on-demand",
                "note": "Estimates exclude free tier. Actual costs may vary.",
            }


# Global metrics registry
_collectors: dict[str, MetricsCollector] = {}
_global_lock = threading.Lock()


def get_metrics(service_name: str) -> MetricsCollector:
    """Get or create a metrics collector for a service."""
    with _global_lock:
        if service_name not in _collectors:
            _collectors[service_name] = MetricsCollector(service_name)
        return _collectors[service_name]


def get_all_metrics() -> dict[str, MetricsCollector]:
    """Get all registered metrics collectors."""
    with _global_lock:
        return dict(_collectors)
