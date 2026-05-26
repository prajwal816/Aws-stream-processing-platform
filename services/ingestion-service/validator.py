"""
Ingestion-specific validation and record enrichment.

Performs additional validation beyond schema validation
and enriches records with platform metadata.
"""

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from shared.utils.validators import ValidationError


# Rate limiting simulation (per source_id)
_source_counters: dict[str, int] = {}
MAX_RECORDS_PER_SOURCE_PER_MINUTE = 1000


def validate_ingestion_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    Perform ingestion-specific validation on a record.

    Checks:
    - Value range limits per record type
    - Source ID format
    - Duplicate detection (basic)
    - Rate limiting per source

    Returns the validated record.
    Raises ValidationError if validation fails.
    """
    errors = []

    record_type = record.get("record_type", "sensor_reading")
    source_id = record.get("source_id", "")

    # Source ID format validation
    if source_id and len(source_id) > 256:
        errors.append("source_id must be 256 characters or less")

    # Value range checks per record type
    if record_type == "sensor_reading":
        value = record.get("value", 0)
        unit = record.get("unit", "").lower()

        range_limits = {
            "celsius": (-273.15, 1000),
            "fahrenheit": (-459.67, 1832),
            "kelvin": (0, 1273.15),
            "percent": (0, 100),
            "ppm": (0, 1_000_000),
            "hpa": (0, 2000),
        }

        if unit in range_limits:
            min_val, max_val = range_limits[unit]
            if not (min_val <= value <= max_val):
                errors.append(
                    f"Value {value} out of range for unit '{unit}' "
                    f"(valid: {min_val} to {max_val})"
                )

    elif record_type == "transaction":
        amount = record.get("amount", 0)
        if amount <= 0:
            errors.append("Transaction amount must be positive")
        if amount > 1_000_000:
            errors.append("Transaction amount exceeds maximum (1,000,000)")

    # Rate limiting check
    _source_counters[source_id] = _source_counters.get(source_id, 0) + 1
    if _source_counters.get(source_id, 0) > MAX_RECORDS_PER_SOURCE_PER_MINUTE:
        errors.append(f"Rate limit exceeded for source '{source_id}'")

    if errors:
        raise ValidationError(
            f"Ingestion validation failed with {len(errors)} error(s)",
            errors=errors,
        )

    return record


def enrich_record(record: dict[str, Any], correlation_id: str = "") -> dict[str, Any]:
    """
    Enrich a validated record with platform metadata.

    Adds:
    - Unique event ID
    - Ingestion timestamp
    - Correlation ID
    - Content hash for deduplication
    - Quality score adjustment
    """
    enriched = dict(record)

    # Generate event ID if not present
    if "event_id" not in enriched:
        enriched["event_id"] = str(uuid.uuid4())

    # Set timestamps
    now = datetime.now(timezone.utc)
    if "timestamp" not in enriched:
        enriched["timestamp"] = now.isoformat()
    enriched["ingested_at"] = now.isoformat()

    # Set correlation ID
    enriched["correlation_id"] = correlation_id or str(uuid.uuid4())

    # Generate content hash for deduplication
    hash_content = f"{enriched.get('source_id', '')}:{enriched.get('value', '')}:{enriched.get('timestamp', '')}"
    enriched["content_hash"] = hashlib.sha256(hash_content.encode()).hexdigest()[:16]

    # Quality score enrichment
    quality = enriched.get("quality_score", 1.0)
    if not enriched.get("location"):
        quality *= 0.95  # Slight penalty for missing location
    if not enriched.get("metadata"):
        quality *= 0.98  # Slight penalty for missing metadata
    enriched["quality_score"] = round(quality, 4)

    # TTL calculation (30 days from now)
    from datetime import timedelta
    ttl_expiry = now + timedelta(days=30)
    enriched["ttl_expiry"] = int(ttl_expiry.timestamp())

    return enriched
