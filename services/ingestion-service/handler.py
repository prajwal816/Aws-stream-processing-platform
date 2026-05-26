"""
Ingestion Service — Lambda Handler

Validates incoming records, enriches them with metadata,
stores them in the RawEvents DynamoDB table, and publishes
events to the processing pipeline.

Endpoints:
    POST /ingest          — Ingest a single record
    POST /ingest/batch    — Ingest a batch of records (up to 500)
    GET  /health          — Service health check
"""

import json
import time
import uuid
from datetime import datetime, timezone

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from shared.utils.logger import get_logger
from shared.utils.metrics import get_metrics, MetricUnit
from shared.utils.response import api_response, error_response, bad_request, internal_error
from shared.utils.validators import validate_record, validate_batch, ValidationError
from shared.utils.dynamodb import get_dynamodb_client
from shared.utils.event_bus import get_event_bus, Topics
from shared.schemas.events import RawEvent
from shared.configs.settings import get_settings
from services.ingestion_service_local.validator import (
    validate_ingestion_record,
    enrich_record,
)

logger = get_logger("ingestion-service")
metrics = get_metrics("ingestion-service")
settings = get_settings()
db = get_dynamodb_client()
event_bus = get_event_bus()

# Register DynamoDB table for local simulation
db.register_table(
    table_name=settings.raw_events_table,
    partition_key="source_id",
    sort_key="timestamp",
    gsi_definitions=[
        {"index_name": "event_type-index", "partition_key": "event_type", "sort_key": "timestamp"},
    ],
)


def ingest_record(event, context=None):
    """
    Lambda handler: Ingest a single record.

    API Gateway event format:
        POST /ingest
        Body: { "source_id": "...", "value": 42.0, "unit": "celsius", ... }
    """
    correlation_id = logger.log_lambda_start(event, context)
    metrics.increment("lambda_invocations")
    metrics.increment("api_requests")

    try:
        # Parse request body
        body = event.get("body", "{}")
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError:
                return bad_request("Invalid JSON in request body", correlation_id=correlation_id)

        if not body:
            return bad_request("Request body is required", correlation_id=correlation_id)

        # Validate the record
        record_type = body.get("record_type", "sensor_reading")
        try:
            validated = validate_record(body, record_type)
        except ValidationError as e:
            metrics.increment("validation_errors")
            return error_response(
                422, e.message,
                error_code="VALIDATION_ERROR",
                details=e.errors,
                correlation_id=correlation_id,
            )

        # Additional ingestion-specific validation
        try:
            validated = validate_ingestion_record(validated)
        except ValidationError as e:
            metrics.increment("validation_errors")
            return error_response(
                422, e.message,
                error_code="VALIDATION_ERROR",
                details=e.errors,
                correlation_id=correlation_id,
            )

        # Enrich the record
        enriched = enrich_record(validated, correlation_id)

        # Create RawEvent
        raw_event = RawEvent(
            source_id=enriched["source_id"],
            timestamp=enriched["timestamp"],
            event_type=enriched.get("event_type", record_type),
            record_type=record_type,
            value=float(enriched.get("value", 0)),
            unit=enriched.get("unit", "count"),
            correlation_id=correlation_id,
            metadata=enriched.get("metadata", {}),
            tags=enriched.get("tags", []),
            quality_score=float(enriched.get("quality_score", 1.0)),
            location=enriched.get("location", ""),
            payload=enriched.get("payload", {}),
            priority=enriched.get("priority", "medium"),
            amount=float(enriched.get("amount", 0)),
            currency=enriched.get("currency", ""),
            category=enriched.get("category", ""),
            description=enriched.get("description", ""),
        )

        # Store in DynamoDB
        metrics.start_timer("dynamodb_write")
        db.put_item(settings.raw_events_table, raw_event.to_dict())
        metrics.stop_timer("dynamodb_write")

        # Publish event for processing
        event_bus.publish(
            Topics.RECORD_INGESTED,
            {
                "event_id": raw_event.event_id,
                "source_id": raw_event.source_id,
                "record_type": record_type,
                "timestamp": raw_event.timestamp,
                "data": raw_event.to_dict(),
            },
            correlation_id=correlation_id,
            source="ingestion-service",
        )

        metrics.increment("records_ingested")
        duration = logger.log_lambda_end(status_code=201, records_ingested=1)
        metrics.record("lambda_execution_duration", duration, MetricUnit.MILLISECONDS)

        return api_response(
            201,
            {
                "event_id": raw_event.event_id,
                "source_id": raw_event.source_id,
                "timestamp": raw_event.timestamp,
                "status": "ingested",
            },
            message="Record ingested successfully",
            correlation_id=correlation_id,
        )

    except Exception as e:
        logger.error(f"Ingestion failed: {str(e)}", error=str(e))
        metrics.increment("ingestion_errors")
        logger.log_lambda_end(status_code=500)
        return internal_error(
            f"Ingestion failed: {str(e)}",
            correlation_id=correlation_id,
        )


def batch_ingest(event, context=None):
    """
    Lambda handler: Ingest a batch of records.

    API Gateway event format:
        POST /ingest/batch
        Body: { "records": [...] }
    """
    correlation_id = logger.log_lambda_start(event, context)
    metrics.increment("lambda_invocations")
    metrics.increment("api_requests")

    try:
        body = event.get("body", "{}")
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError:
                return bad_request("Invalid JSON in request body", correlation_id=correlation_id)

        records = body.get("records", [])
        if not records:
            return bad_request("'records' array is required", correlation_id=correlation_id)

        # Validate batch
        try:
            batch_result = validate_batch(records)
        except ValidationError as e:
            return error_response(
                422, e.message,
                error_code="VALIDATION_ERROR",
                details=e.errors,
                correlation_id=correlation_id,
            )

        # Process valid records
        ingested_events = []
        for record in batch_result["valid"]:
            try:
                enriched = enrich_record(record, correlation_id)
                raw_event = RawEvent(
                    source_id=enriched["source_id"],
                    timestamp=enriched["timestamp"],
                    event_type=enriched.get("event_type", enriched.get("record_type", "sensor_reading")),
                    record_type=enriched.get("record_type", "sensor_reading"),
                    value=float(enriched.get("value", 0)),
                    unit=enriched.get("unit", "count"),
                    correlation_id=correlation_id,
                    metadata=enriched.get("metadata", {}),
                    tags=enriched.get("tags", []),
                    quality_score=float(enriched.get("quality_score", 1.0)),
                    location=enriched.get("location", ""),
                    payload=enriched.get("payload", {}),
                    priority=enriched.get("priority", "medium"),
                    amount=float(enriched.get("amount", 0)),
                    currency=enriched.get("currency", ""),
                    category=enriched.get("category", ""),
                    description=enriched.get("description", ""),
                )
                ingested_events.append(raw_event.to_dict())
            except Exception as e:
                batch_result["invalid"].append({
                    "record": record,
                    "error": {"message": str(e)},
                })
                batch_result["invalid_count"] += 1
                batch_result["valid_count"] -= 1

        # Batch write to DynamoDB
        if ingested_events:
            metrics.start_timer("dynamodb_batch_write")
            db.batch_write(settings.raw_events_table, ingested_events)
            metrics.stop_timer("dynamodb_batch_write")

            # Publish batch event
            event_bus.publish(
                Topics.BATCH_INGESTED,
                {
                    "batch_size": len(ingested_events),
                    "event_ids": [e["event_id"] for e in ingested_events],
                    "correlation_id": correlation_id,
                },
                correlation_id=correlation_id,
                source="ingestion-service",
            )

        metrics.increment("records_ingested", len(ingested_events))
        metrics.increment("batch_operations")
        duration = logger.log_lambda_end(
            status_code=200,
            records_ingested=len(ingested_events),
            records_failed=batch_result["invalid_count"],
        )
        metrics.record("lambda_execution_duration", duration, MetricUnit.MILLISECONDS)

        return api_response(
            200,
            {
                "ingested": len(ingested_events),
                "failed": batch_result["invalid_count"],
                "total": batch_result["total"],
                "errors": batch_result["invalid"][:10],  # Return first 10 errors
            },
            message=f"Batch processed: {len(ingested_events)} ingested, {batch_result['invalid_count']} failed",
            correlation_id=correlation_id,
        )

    except Exception as e:
        logger.error(f"Batch ingestion failed: {str(e)}", error=str(e))
        metrics.increment("ingestion_errors")
        logger.log_lambda_end(status_code=500)
        return internal_error(
            f"Batch ingestion failed: {str(e)}",
            correlation_id=correlation_id,
        )


def health_check(event, context=None):
    """
    Lambda handler: Service health check.

    GET /health
    """
    correlation_id = logger.log_lambda_start(event, context)

    try:
        # Check DynamoDB connectivity
        table_stats = db.get_table_stats()
        raw_count = db.item_count(settings.raw_events_table)

        health = {
            "service": "ingestion-service",
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "1.0.0",
            "checks": {
                "dynamodb": {
                    "status": "connected",
                    "tables": table_stats,
                    "raw_events_count": raw_count,
                },
                "event_bus": {
                    "status": "connected",
                    "stats": event_bus.get_stats(),
                },
            },
            "metrics_summary": metrics.get_summary(),
        }

        logger.log_lambda_end(status_code=200)
        return api_response(200, health, message="Service is healthy", correlation_id=correlation_id)

    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return error_response(
            503, "Service unhealthy",
            details=str(e),
            correlation_id=correlation_id,
        )


def lambda_handler(event, context=None):
    """
    Main Lambda entry point — routes requests based on HTTP method and path.
    """
    http_method = event.get("httpMethod", "GET")
    path = event.get("path", "/health")

    if http_method == "OPTIONS":
        from shared.utils.response import options_response
        return options_response()

    if path == "/health" or path == "/v1/health":
        return health_check(event, context)
    elif path in ("/ingest", "/v1/ingest") and http_method == "POST":
        return ingest_record(event, context)
    elif path in ("/ingest/batch", "/v1/ingest/batch") and http_method == "POST":
        return batch_ingest(event, context)
    else:
        return error_response(404, f"Route not found: {http_method} {path}")
