"""
Processing Service — Lambda Handler

Transforms raw events into processed records, performs aggregation
and filtering, and updates analytics summaries.

Triggered by:
    - Event bus: RECORD_INGESTED, BATCH_INGESTED
    - API: POST /process (manual trigger)
"""

import json
import time
import uuid
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

_service_dir = os.path.dirname(os.path.abspath(__file__))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from shared.utils.logger import get_logger
from shared.utils.metrics import get_metrics, MetricUnit
from shared.utils.response import api_response, error_response, internal_error
from shared.utils.dynamodb import get_dynamodb_client
from shared.utils.event_bus import get_event_bus, Topics
from shared.schemas.events import RawEvent, ProcessedRecord, AnalyticsSummary, ProcessingStatus
from shared.configs.settings import get_settings
from transformer import DataTransformer
from aggregator import DataAggregator
from filters import DataFilter

logger = get_logger("processing-service")
metrics = get_metrics("processing-service")
settings = get_settings()
db = get_dynamodb_client()
event_bus = get_event_bus()

# Initialize processing components
transformer = DataTransformer()
aggregator = DataAggregator()
data_filter = DataFilter()

# Register DynamoDB tables
db.register_table(
    table_name=settings.processed_data_table,
    partition_key="record_id",
    sort_key="processed_at",
    gsi_definitions=[
        {"index_name": "category-index", "partition_key": "category", "sort_key": "processed_at"},
        {"index_name": "status-index", "partition_key": "status", "sort_key": "processed_at"},
    ],
)

db.register_table(
    table_name=settings.analytics_table,
    partition_key="metric_name",
    sort_key="period",
    gsi_definitions=[
        {"index_name": "dashboard-index", "partition_key": "category", "sort_key": "last_updated"},
    ],
)


def process_event(event, context=None):
    """
    Process a single raw event from the event bus.

    This is the primary processing pipeline:
    1. Retrieve raw event data
    2. Apply filters (quality, dedup, threshold)
    3. Transform the data
    4. Update aggregations
    5. Store processed record
    6. Publish completion event
    """
    correlation_id = logger.log_lambda_start(event, context)
    metrics.increment("lambda_invocations")

    try:
        # Extract event data - handle both direct invocation and event bus format
        if isinstance(event, dict) and "body" in event:
            body = event.get("body", "{}")
            if isinstance(body, str):
                body = json.loads(body)
            raw_data = body.get("data", body)
        elif isinstance(event, dict) and "data" in event:
            raw_data = event["data"]
        else:
            raw_data = event

        source_id = raw_data.get("source_id", "unknown")
        event_id = raw_data.get("event_id", str(uuid.uuid4()))
        record_type = raw_data.get("record_type", "sensor_reading")

        logger.info(
            "Processing event",
            event_id=event_id,
            source_id=source_id,
            record_type=record_type,
        )

        # Step 1: Apply filters
        metrics.start_timer("filtering")
        filter_result = data_filter.apply_filters(raw_data)
        metrics.stop_timer("filtering")

        if not filter_result["passed"]:
            logger.info(
                "Record filtered out",
                event_id=event_id,
                reason=filter_result["reason"],
            )
            metrics.increment("records_filtered")

            processed = ProcessedRecord(
                record_id=str(uuid.uuid4()),
                processed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                source_event_id=event_id,
                source_id=source_id,
                event_type=record_type,
                status=ProcessingStatus.SKIPPED.value,
                category=raw_data.get("category", "filtered"),
                correlation_id=correlation_id,
            )
            db.put_item(settings.processed_data_table, processed.to_dict())
            return _build_response(processed, correlation_id, "skipped")

        # Step 2: Transform data
        metrics.start_timer("transformation")
        transformed = transformer.transform(raw_data)
        metrics.stop_timer("transformation")

        # Step 3: Create processed record
        processed = ProcessedRecord(
            record_id=str(uuid.uuid4()),
            processed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            source_event_id=event_id,
            source_id=source_id,
            event_type=record_type,
            category=transformed.get("category", "general"),
            status=ProcessingStatus.COMPLETED.value,
            original_value=float(raw_data.get("value", 0)),
            normalized_value=float(transformed.get("normalized_value", 0)),
            unit=transformed.get("normalized_unit", raw_data.get("unit", "count")),
            quality_score=float(transformed.get("quality_score", 1.0)),
            transformations_applied=transformed.get("transformations", []),
            enrichment_data=transformed.get("enrichment", {}),
            tags=raw_data.get("tags", []),
            correlation_id=correlation_id,
        )

        # Step 4: Store processed record
        metrics.start_timer("dynamodb_write")
        db.put_item(settings.processed_data_table, processed.to_dict())
        metrics.stop_timer("dynamodb_write")

        # Step 5: Update aggregations
        metrics.start_timer("aggregation")
        aggregator.update(processed)
        metrics.stop_timer("aggregation")

        # Step 6: Publish completion event
        event_bus.publish(
            Topics.PROCESSING_COMPLETED,
            {
                "record_id": processed.record_id,
                "source_event_id": event_id,
                "source_id": source_id,
                "category": processed.category,
                "normalized_value": processed.normalized_value,
                "status": "completed",
            },
            correlation_id=correlation_id,
            source="processing-service",
        )

        metrics.increment("records_processed")
        duration = logger.log_lambda_end(status_code=200, records_processed=1)
        metrics.record("lambda_execution_duration", duration, MetricUnit.MILLISECONDS)
        metrics.record("processing_latency", duration, MetricUnit.MILLISECONDS)

        return _build_response(processed, correlation_id, "processed")

    except Exception as e:
        logger.error(f"Processing failed: {str(e)}", error=str(e))
        metrics.increment("processing_errors")

        # Publish failure event
        event_bus.publish(
            Topics.PROCESSING_FAILED,
            {
                "error": str(e),
                "event": event if isinstance(event, dict) else {},
                "correlation_id": correlation_id,
            },
            correlation_id=correlation_id,
            source="processing-service",
        )

        logger.log_lambda_end(status_code=500)
        return internal_error(
            f"Processing failed: {str(e)}",
            correlation_id=correlation_id,
        )


def batch_process(event, context=None):
    """
    Process a batch of events. Triggered by BATCH_INGESTED events.
    """
    correlation_id = logger.log_lambda_start(event, context)
    metrics.increment("lambda_invocations")

    try:
        if isinstance(event, dict) and "body" in event:
            body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]
            event_ids = body.get("event_ids", [])
        else:
            event_ids = event.get("event_ids", [])

        results = {"processed": 0, "failed": 0, "skipped": 0}

        # Retrieve raw events from DynamoDB and process each
        raw_table = settings.raw_events_table
        all_items = db.scan(raw_table, limit=len(event_ids) if event_ids else 100)

        for item in all_items:
            try:
                result = process_event({"data": item}, context)
                result_body = json.loads(result.get("body", "{}"))
                status = result_body.get("data", {}).get("status", "unknown")
                if status == "processed":
                    results["processed"] += 1
                elif status == "skipped":
                    results["skipped"] += 1
                else:
                    results["failed"] += 1
            except Exception as e:
                results["failed"] += 1
                logger.error(f"Batch item processing failed: {str(e)}")

        metrics.increment("batch_operations")
        duration = logger.log_lambda_end(status_code=200, **results)
        metrics.record("lambda_execution_duration", duration, MetricUnit.MILLISECONDS)

        return api_response(
            200,
            results,
            message=f"Batch processed: {results['processed']} completed, {results['skipped']} skipped, {results['failed']} failed",
            correlation_id=correlation_id,
        )

    except Exception as e:
        logger.error(f"Batch processing failed: {str(e)}")
        logger.log_lambda_end(status_code=500)
        return internal_error(str(e), correlation_id=correlation_id)


def _build_response(record: ProcessedRecord, correlation_id: str, status: str) -> dict:
    """Build a standardized processing response."""
    return api_response(
        200,
        {
            "record_id": record.record_id,
            "source_event_id": record.source_event_id,
            "status": status,
            "category": record.category,
            "normalized_value": record.normalized_value,
            "quality_score": record.quality_score,
            "transformations": record.transformations_applied,
        },
        message=f"Record {status}",
        correlation_id=correlation_id,
    )


def lambda_handler(event, context=None):
    """Main Lambda entry point."""
    http_method = event.get("httpMethod", "")
    path = event.get("path", "")

    if http_method == "OPTIONS":
        from shared.utils.response import options_response
        return options_response()

    if path in ("/process", "/v1/process") and http_method == "POST":
        return process_event(event, context)
    elif path in ("/process/batch", "/v1/process/batch") and http_method == "POST":
        return batch_process(event, context)
    else:
        # Assume event bus invocation
        return process_event(event, context)
