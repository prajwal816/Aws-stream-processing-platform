"""
Statistical computation engine for the analytics service.

Provides summary statistics, trend analysis, and aggregation
computations over analytics data.
"""

import math
from typing import Any, Optional


class StatisticsEngine:
    """
    Computes statistical summaries and trends from analytics data.
    """

    def compute_summary_stats(self, summaries: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Compute high-level statistics from a list of analytics summaries.
        """
        if not summaries:
            return {
                "total_records": 0,
                "total_data_points": 0,
                "unique_metrics": 0,
                "avg_value": 0,
                "overall_min": 0,
                "overall_max": 0,
            }

        total_count = sum(s.get("count", 0) for s in summaries)
        total_sum = sum(s.get("sum_value", 0) for s in summaries)
        all_mins = [s.get("min_value", 0) for s in summaries if s.get("min_value", 0) != 0]
        all_maxs = [s.get("max_value", 0) for s in summaries if s.get("max_value", 0) != 0]
        unique_metrics = len(set(s.get("metric_name", "") for s in summaries))

        return {
            "total_records": total_count,
            "total_data_points": len(summaries),
            "unique_metrics": unique_metrics,
            "avg_value": round(total_sum / total_count, 4) if total_count > 0 else 0,
            "overall_min": round(min(all_mins), 4) if all_mins else 0,
            "overall_max": round(max(all_maxs), 4) if all_maxs else 0,
            "total_sum": round(total_sum, 4),
        }

    def compute_overall_stats(self, all_metrics: dict) -> dict[str, Any]:
        """
        Compute platform-wide statistics from all service metrics collectors.
        """
        total_ingested = 0
        total_processed = 0
        total_errors = 0
        latency_values = []
        active_sources = set()

        for service_name, collector in all_metrics.items():
            summary = collector.get_summary()
            counters = summary.get("counters", {})

            total_ingested += counters.get("records_ingested", 0)
            total_processed += counters.get("records_processed", 0)
            total_errors += (
                counters.get("ingestion_errors", 0)
                + counters.get("processing_errors", 0)
                + counters.get("validation_errors", 0)
            )

            # Get latency data
            gauges = summary.get("gauges", {})
            for gauge_name in ["processing_latency", "lambda_execution_duration"]:
                if gauge_name in gauges:
                    gauge = gauges[gauge_name]
                    if gauge.get("avg", 0) > 0:
                        latency_values.append(gauge["avg"])

        avg_latency = round(sum(latency_values) / len(latency_values), 2) if latency_values else 0

        # Estimate p95 latency (simplified)
        p95_latency = round(avg_latency * 1.8, 2) if avg_latency > 0 else 0

        return {
            "total_ingested": int(total_ingested),
            "total_processed": int(total_processed),
            "total_errors": int(total_errors),
            "avg_latency": avg_latency,
            "p95_latency": p95_latency,
            "error_rate": round(total_errors / max(total_ingested, 1) * 100, 2),
            "processing_rate": round(total_processed / max(total_ingested, 1) * 100, 2),
            "active_sources": len(active_sources),
        }

    def compute_trend(self, data_points: list[dict[str, Any]], field: str = "count") -> dict[str, Any]:
        """
        Compute trend direction and magnitude from time-series data.
        """
        if len(data_points) < 2:
            return {"direction": "stable", "magnitude": 0, "change_percent": 0}

        values = [dp.get(field, 0) for dp in data_points]

        # Simple linear regression
        n = len(values)
        x_sum = sum(range(n))
        y_sum = sum(values)
        xy_sum = sum(i * v for i, v in enumerate(values))
        x2_sum = sum(i * i for i in range(n))

        denominator = n * x2_sum - x_sum * x_sum
        if denominator == 0:
            return {"direction": "stable", "magnitude": 0, "change_percent": 0}

        slope = (n * xy_sum - x_sum * y_sum) / denominator

        # Determine direction
        if abs(slope) < 0.01:
            direction = "stable"
        elif slope > 0:
            direction = "increasing"
        else:
            direction = "decreasing"

        # Calculate percentage change
        first_val = values[0] if values[0] != 0 else 1
        change_pct = round(((values[-1] - values[0]) / abs(first_val)) * 100, 2)

        return {
            "direction": direction,
            "magnitude": round(abs(slope), 4),
            "change_percent": change_pct,
            "first_value": values[0],
            "last_value": values[-1],
            "slope": round(slope, 4),
        }

    def compute_percentiles(self, values: list[float]) -> dict[str, float]:
        """Compute standard percentiles from a list of values."""
        if not values:
            return {"p50": 0, "p75": 0, "p90": 0, "p95": 0, "p99": 0}

        sorted_vals = sorted(values)
        n = len(sorted_vals)

        return {
            "p50": sorted_vals[n // 2],
            "p75": sorted_vals[int(n * 0.75)],
            "p90": sorted_vals[int(n * 0.90)],
            "p95": sorted_vals[int(n * 0.95)],
            "p99": sorted_vals[int(n * 0.99)],
        }
