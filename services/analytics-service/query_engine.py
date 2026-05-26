"""
DynamoDB query engine for the analytics service.

Provides optimized query patterns for retrieving analytics summaries,
processed records, and pipeline statistics.
"""

from typing import Any, Optional

from shared.utils.dynamodb import get_dynamodb_client
from shared.utils.metrics import get_metrics
from shared.configs.settings import get_settings

db = get_dynamodb_client()
metrics = get_metrics("analytics-service")
settings = get_settings()


class QueryEngine:
    """
    Query engine for analytics data with DynamoDB-optimized access patterns.
    """

    def get_analytics_summaries(
        self,
        period_type: str = "daily",
        category: Optional[str] = None,
        metric_name: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Query analytics summaries by period type.

        Scans the analytics table and filters by period prefix.
        In production, this would use a GSI for efficient queries.
        """
        metrics.increment("dynamodb_read_operations")

        all_items = db.scan(settings.analytics_table, limit=500)

        # Filter by period type
        results = []
        for item in all_items:
            period = item.get("period", "")
            if not period.startswith(f"{period_type}#"):
                continue

            if category and item.get("category") != category:
                continue

            if metric_name and item.get("metric_name") != metric_name:
                continue

            results.append(item)

        # Sort by period descending (most recent first)
        results.sort(key=lambda x: x.get("period", ""), reverse=True)
        return results[:limit]

    def get_category_breakdown(self) -> dict[str, Any]:
        """
        Get record counts and statistics grouped by category.
        """
        metrics.increment("dynamodb_read_operations")
        all_items = db.scan(settings.analytics_table, limit=500)

        categories: dict[str, dict[str, Any]] = {}
        for item in all_items:
            cat = item.get("category", "unknown")
            metric = item.get("metric_name", "")

            if not metric.startswith("category_"):
                continue

            period = item.get("period", "")
            if not period.startswith("daily#"):
                continue

            if cat not in categories:
                categories[cat] = {
                    "total_count": 0,
                    "total_sum": 0,
                    "avg_value": 0,
                    "min_value": float("inf"),
                    "max_value": float("-inf"),
                    "periods": 0,
                }

            categories[cat]["total_count"] += item.get("count", 0)
            categories[cat]["total_sum"] += item.get("sum_value", 0)
            categories[cat]["periods"] += 1
            categories[cat]["min_value"] = min(
                categories[cat]["min_value"],
                item.get("min_value", float("inf")),
            )
            categories[cat]["max_value"] = max(
                categories[cat]["max_value"],
                item.get("max_value", float("-inf")),
            )

        # Calculate averages and fix infinity
        for cat, data in categories.items():
            if data["total_count"] > 0:
                data["avg_value"] = round(data["total_sum"] / data["total_count"], 4)
            if data["min_value"] == float("inf"):
                data["min_value"] = 0
            if data["max_value"] == float("-inf"):
                data["max_value"] = 0
            data["total_sum"] = round(data["total_sum"], 4)

        return categories

    def get_pipeline_stats(self) -> dict[str, Any]:
        """
        Get processing pipeline statistics.
        """
        processed_count = db.item_count(settings.processed_data_table)

        # Get status breakdown
        all_processed = db.scan(settings.processed_data_table, limit=1000)
        status_counts: dict[str, int] = {}
        for item in all_processed:
            status = item.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "total_processed": processed_count,
            "status_breakdown": status_counts,
            "processing_rate": processed_count,  # Simplified
        }

    def get_recent_records(self, limit: int = 20) -> list[dict[str, Any]]:
        """
        Get most recently processed records.
        """
        metrics.increment("dynamodb_read_operations")
        all_records = db.scan(settings.processed_data_table, limit=500)

        # Sort by processed_at descending
        all_records.sort(key=lambda x: x.get("processed_at", ""), reverse=True)

        # Return simplified records
        return [
            {
                "record_id": r.get("record_id", ""),
                "source_id": r.get("source_id", ""),
                "category": r.get("category", ""),
                "status": r.get("status", ""),
                "normalized_value": r.get("normalized_value", 0),
                "quality_score": r.get("quality_score", 0),
                "processed_at": r.get("processed_at", ""),
                "event_type": r.get("event_type", ""),
            }
            for r in all_records[:limit]
        ]

    def query_records(
        self,
        category: Optional[str] = None,
        status: Optional[str] = None,
        source_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Query processed records with optional filters.
        """
        metrics.increment("dynamodb_read_operations")

        if category:
            results = db.query(
                settings.processed_data_table,
                partition_value=category,
                index_name="category-index",
                limit=limit,
            )
        elif status:
            results = db.query(
                settings.processed_data_table,
                partition_value=status,
                index_name="status-index",
                limit=limit,
            )
        else:
            results = db.scan(settings.processed_data_table, limit=limit)

        # Apply additional filters
        if source_id:
            results = [r for r in results if r.get("source_id") == source_id]

        return results[:limit]
