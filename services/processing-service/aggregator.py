"""
Data aggregation logic for the processing pipeline.

Maintains running aggregates (totals, averages, counts) across
multiple dimensions (category, time window, source) and persists
summaries to the AnalyticsSummaries DynamoDB table.
"""

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from shared.utils.logger import get_logger
from shared.utils.dynamodb import get_dynamodb_client
from shared.utils.metrics import get_metrics
from shared.schemas.events import ProcessedRecord, AnalyticsSummary
from shared.configs.settings import get_settings

logger = get_logger("aggregator")
metrics = get_metrics("processing-service")
db = get_dynamodb_client()
settings = get_settings()


class DataAggregator:
    """
    Maintains running aggregations and persists analytics summaries.

    Aggregation dimensions:
    - By category (hourly and daily)
    - By source (hourly)
    - Global totals (hourly and daily)
    - By event type (daily)
    """

    def __init__(self):
        # In-memory running aggregates for fast updates
        self._aggregates: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "count": 0,
                "sum": 0.0,
                "min": float("inf"),
                "max": float("-inf"),
                "values": [],
            }
        )

    def update(self, record: ProcessedRecord) -> None:
        """
        Update all relevant aggregations with a new processed record.
        """
        now = datetime.now(timezone.utc)
        hourly_key = now.strftime("hourly#%Y-%m-%dT%H:00:00Z")
        daily_key = now.strftime("daily#%Y-%m-%d")
        value = record.normalized_value

        # Update by category (hourly)
        self._update_aggregate(
            metric_name=f"category_{record.category}",
            period=hourly_key,
            value=value,
            category=record.category,
            source_id=record.source_id,
        )

        # Update by category (daily)
        self._update_aggregate(
            metric_name=f"category_{record.category}",
            period=daily_key,
            value=value,
            category=record.category,
            source_id=record.source_id,
        )

        # Update global totals (hourly)
        self._update_aggregate(
            metric_name="global_totals",
            period=hourly_key,
            value=value,
            category="global",
            source_id=record.source_id,
        )

        # Update global totals (daily)
        self._update_aggregate(
            metric_name="global_totals",
            period=daily_key,
            value=value,
            category="global",
            source_id=record.source_id,
        )

        # Update by event type (daily)
        self._update_aggregate(
            metric_name=f"event_type_{record.event_type}",
            period=daily_key,
            value=value,
            category=record.event_type,
            source_id=record.source_id,
        )

        # Update by source (hourly)
        self._update_aggregate(
            metric_name=f"source_{record.source_id}",
            period=hourly_key,
            value=value,
            category=record.category,
            source_id=record.source_id,
        )

        # Update records processed counter
        self._update_aggregate(
            metric_name="records_processed",
            period=daily_key,
            value=1,
            category="counter",
            source_id=record.source_id,
        )

        # Update throughput metric
        self._update_aggregate(
            metric_name="throughput",
            period=hourly_key,
            value=1,
            category="throughput",
            source_id=record.source_id,
        )

        metrics.increment("aggregations_updated")

    def _update_aggregate(
        self,
        metric_name: str,
        period: str,
        value: float,
        category: str = "general",
        source_id: str = "",
    ) -> None:
        """Update a single aggregation and persist to DynamoDB."""
        key = f"{metric_name}#{period}"

        agg = self._aggregates[key]
        agg["count"] += 1
        agg["sum"] += value
        agg["min"] = min(agg["min"], value)
        agg["max"] = max(agg["max"], value)
        agg["values"].append(value)

        # Keep only last 1000 values for percentile calculation
        if len(agg["values"]) > 1000:
            agg["values"] = agg["values"][-1000:]

        # Calculate percentiles
        sorted_values = sorted(agg["values"])
        count = len(sorted_values)
        p50 = sorted_values[count // 2] if count > 0 else 0
        p95 = sorted_values[int(count * 0.95)] if count > 0 else 0
        p99 = sorted_values[int(count * 0.99)] if count > 0 else 0

        # Create summary
        summary = AnalyticsSummary(
            metric_name=metric_name,
            period=period,
            count=agg["count"],
            sum_value=round(agg["sum"], 4),
            avg_value=round(agg["sum"] / agg["count"], 4) if agg["count"] > 0 else 0,
            min_value=round(agg["min"], 4) if agg["min"] != float("inf") else 0,
            max_value=round(agg["max"], 4) if agg["max"] != float("-inf") else 0,
            p50_value=round(p50, 4),
            p95_value=round(p95, 4),
            p99_value=round(p99, 4),
            category=category,
            source_ids=list(set([source_id])) if source_id else [],
        )

        # Persist to DynamoDB
        db.put_item(settings.analytics_table, summary.to_dict())

    def get_aggregate(self, metric_name: str, period: str) -> Optional[dict[str, Any]]:
        """Get a specific aggregation."""
        key = f"{metric_name}#{period}"
        if key in self._aggregates:
            agg = self._aggregates[key]
            return {
                "metric_name": metric_name,
                "period": period,
                "count": agg["count"],
                "sum": agg["sum"],
                "avg": agg["sum"] / agg["count"] if agg["count"] > 0 else 0,
                "min": agg["min"] if agg["min"] != float("inf") else 0,
                "max": agg["max"] if agg["max"] != float("-inf") else 0,
            }
        return None

    def get_all_aggregates(self) -> dict[str, Any]:
        """Get all current aggregations."""
        result = {}
        for key, agg in self._aggregates.items():
            result[key] = {
                "count": agg["count"],
                "sum": round(agg["sum"], 4),
                "avg": round(agg["sum"] / agg["count"], 4) if agg["count"] > 0 else 0,
                "min": round(agg["min"], 4) if agg["min"] != float("inf") else 0,
                "max": round(agg["max"], 4) if agg["max"] != float("-inf") else 0,
            }
        return result

    def reset(self) -> None:
        """Reset all aggregations."""
        self._aggregates.clear()
