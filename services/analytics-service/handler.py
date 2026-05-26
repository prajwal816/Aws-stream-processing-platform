"""
Analytics Service — Lambda Handler

Queries processed data and analytics summaries to provide
insights, statistics, and dashboard data.

Endpoints:
    GET /analytics              — Get analytics summary
    GET /analytics/dashboard    — Get full dashboard payload
    GET /analytics/records      — Query processed records
    GET /analytics/metrics      — Get platform metrics
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

_service_dir = os.path.dirname(os.path.abspath(__file__))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from shared.utils.logger import get_logger
from shared.utils.metrics import get_metrics, get_all_metrics, MetricUnit
from shared.utils.response import api_response, error_response, bad_request, not_found, internal_error
from shared.utils.dynamodb import get_dynamodb_client
from shared.utils.event_bus import get_event_bus
from shared.configs.settings import get_settings
from query_engine import QueryEngine
from statistics_engine import StatisticsEngine

logger = get_logger("analytics-service")
metrics = get_metrics("analytics-service")
settings = get_settings()
db = get_dynamodb_client()

query_engine = QueryEngine()
stats_engine = StatisticsEngine()


def get_analytics(event, context=None):
    """
    Get analytics summary with key metrics and trends.

    Query params:
        period: hourly|daily (default: daily)
        category: filter by category
        limit: max results (default: 50)
    """
    correlation_id = logger.log_lambda_start(event, context)
    metrics.increment("lambda_invocations")
    metrics.increment("api_requests")

    try:
        params = event.get("queryStringParameters") or {}
        period_type = params.get("period", "daily")
        category = params.get("category")
        limit = int(params.get("limit", "50"))

        # Query analytics summaries
        summaries = query_engine.get_analytics_summaries(
            period_type=period_type,
            category=category,
            limit=limit,
        )

        # Calculate statistics
        stats = stats_engine.compute_summary_stats(summaries)

        duration = logger.log_lambda_end(status_code=200)
        metrics.record("lambda_execution_duration", duration, MetricUnit.MILLISECONDS)

        return api_response(
            200,
            {
                "summaries": summaries,
                "statistics": stats,
                "query": {
                    "period": period_type,
                    "category": category,
                    "limit": limit,
                    "result_count": len(summaries),
                },
            },
            message="Analytics retrieved successfully",
            correlation_id=correlation_id,
        )

    except Exception as e:
        logger.error(f"Analytics query failed: {str(e)}")
        logger.log_lambda_end(status_code=500)
        return internal_error(str(e), correlation_id=correlation_id)


def get_dashboard_data(event, context=None):
    """
    Get comprehensive dashboard payload with all widgets data.
    """
    correlation_id = logger.log_lambda_start(event, context)
    metrics.increment("lambda_invocations")
    metrics.increment("api_requests")

    try:
        # Get all metrics from all services
        all_metrics = get_all_metrics()
        service_metrics = {}
        for service_name, collector in all_metrics.items():
            service_metrics[service_name] = collector.get_summary()

        # Get cost estimates
        cost_data = {}
        for service_name, collector in all_metrics.items():
            cost_data[service_name] = collector.get_cost_estimate()

        # Get analytics summaries
        hourly_summaries = query_engine.get_analytics_summaries(period_type="hourly", limit=24)
        daily_summaries = query_engine.get_analytics_summaries(period_type="daily", limit=30)

        # Get category breakdown
        categories = query_engine.get_category_breakdown()

        # Get processing pipeline stats
        pipeline_stats = query_engine.get_pipeline_stats()

        # Get recent records
        recent_records = query_engine.get_recent_records(limit=20)

        # Get event bus stats
        event_bus = get_event_bus()
        event_stats = event_bus.get_stats()

        # Get table stats
        table_stats = db.get_table_stats()

        # Compute overall stats
        overall_stats = stats_engine.compute_overall_stats(all_metrics)

        dashboard = {
            "overview": {
                "total_records_ingested": overall_stats.get("total_ingested", 0),
                "total_records_processed": overall_stats.get("total_processed", 0),
                "total_errors": overall_stats.get("total_errors", 0),
                "avg_processing_latency_ms": overall_stats.get("avg_latency", 0),
                "p95_processing_latency_ms": overall_stats.get("p95_latency", 0),
                "uptime_percentage": 99.97,
                "active_sources": overall_stats.get("active_sources", 0),
            },
            "service_metrics": service_metrics,
            "cost_analysis": cost_data,
            "hourly_trends": hourly_summaries,
            "daily_trends": daily_summaries,
            "category_breakdown": categories,
            "pipeline_stats": pipeline_stats,
            "recent_records": recent_records,
            "event_bus": event_stats,
            "infrastructure": {
                "dynamodb_tables": table_stats,
                "lambda_functions": {
                    "ingestion-service": {"status": "active", "memory_mb": 256},
                    "processing-service": {"status": "active", "memory_mb": 256},
                    "analytics-service": {"status": "active", "memory_mb": 256},
                    "notification-service": {"status": "active", "memory_mb": 128},
                },
            },
        }

        duration = logger.log_lambda_end(status_code=200)
        metrics.record("lambda_execution_duration", duration, MetricUnit.MILLISECONDS)

        return api_response(
            200,
            dashboard,
            message="Dashboard data retrieved",
            correlation_id=correlation_id,
        )

    except Exception as e:
        logger.error(f"Dashboard query failed: {str(e)}")
        logger.log_lambda_end(status_code=500)
        return internal_error(str(e), correlation_id=correlation_id)


def get_records(event, context=None):
    """
    Query processed records with filtering.

    Query params:
        category, status, source_id, limit
    """
    correlation_id = logger.log_lambda_start(event, context)
    metrics.increment("lambda_invocations")
    metrics.increment("api_requests")

    try:
        params = event.get("queryStringParameters") or {}
        category = params.get("category")
        status = params.get("status")
        source_id = params.get("source_id")
        limit = int(params.get("limit", "50"))

        records = query_engine.query_records(
            category=category,
            status=status,
            source_id=source_id,
            limit=limit,
        )

        duration = logger.log_lambda_end(status_code=200)
        metrics.record("lambda_execution_duration", duration, MetricUnit.MILLISECONDS)

        return api_response(
            200,
            {
                "records": records,
                "count": len(records),
                "query": params,
            },
            message="Records retrieved",
            correlation_id=correlation_id,
        )

    except Exception as e:
        logger.error(f"Records query failed: {str(e)}")
        logger.log_lambda_end(status_code=500)
        return internal_error(str(e), correlation_id=correlation_id)


def get_platform_metrics(event, context=None):
    """
    Get raw platform metrics from all services.
    """
    correlation_id = logger.log_lambda_start(event, context)
    metrics.increment("lambda_invocations")

    try:
        all_metrics = get_all_metrics()
        params = event.get("queryStringParameters") or {}
        metric_name = params.get("metric")
        service = params.get("service")

        result = {}
        for svc_name, collector in all_metrics.items():
            if service and svc_name != service:
                continue
            if metric_name:
                result[svc_name] = {
                    "data_points": collector.get_data_points(metric_name, limit=100),
                    "counter": collector.get_counter(metric_name),
                    "average": collector.get_average(metric_name),
                }
            else:
                result[svc_name] = collector.get_summary()

        duration = logger.log_lambda_end(status_code=200)
        return api_response(200, result, message="Metrics retrieved", correlation_id=correlation_id)

    except Exception as e:
        logger.error(f"Metrics query failed: {str(e)}")
        return internal_error(str(e), correlation_id=correlation_id)


def lambda_handler(event, context=None):
    """Main Lambda entry point."""
    http_method = event.get("httpMethod", "GET")
    path = event.get("path", "/analytics")

    if http_method == "OPTIONS":
        from shared.utils.response import options_response
        return options_response()

    if path in ("/analytics", "/v1/analytics"):
        return get_analytics(event, context)
    elif path in ("/analytics/dashboard", "/v1/analytics/dashboard"):
        return get_dashboard_data(event, context)
    elif path in ("/analytics/records", "/v1/analytics/records"):
        return get_records(event, context)
    elif path in ("/analytics/metrics", "/v1/analytics/metrics"):
        return get_platform_metrics(event, context)
    else:
        return error_response(404, f"Route not found: {http_method} {path}")
