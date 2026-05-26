"""
Input validation utilities for incoming records.

Provides schema-based validation with detailed error reporting.
"""

import re
import uuid
from datetime import datetime
from typing import Any, Optional


class ValidationError(Exception):
    """Raised when record validation fails."""

    def __init__(self, message: str, field: Optional[str] = None, errors: Optional[list] = None):
        self.message = message
        self.field = field
        self.errors = errors or []
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "ValidationError",
            "message": self.message,
            "field": self.field,
            "details": self.errors,
        }


# Field type validators
def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and len(value.strip()) > 0


def _is_positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and value > 0


def _is_valid_timestamp(value: Any) -> bool:
    if isinstance(value, str):
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return True
        except (ValueError, AttributeError):
            return False
    return isinstance(value, (int, float)) and value > 0


def _is_valid_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def _is_valid_email(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, value))


# Schema definitions for different record types
RECORD_SCHEMAS: dict[str, dict[str, Any]] = {
    "sensor_reading": {
        "required_fields": {
            "source_id": {"validator": _is_non_empty_string, "message": "source_id must be a non-empty string"},
            "value": {"validator": lambda v: isinstance(v, (int, float)), "message": "value must be a number"},
            "unit": {"validator": _is_non_empty_string, "message": "unit must be a non-empty string"},
        },
        "optional_fields": {
            "timestamp": {"validator": _is_valid_timestamp, "message": "timestamp must be valid ISO format"},
            "location": {"validator": _is_non_empty_string, "message": "location must be a non-empty string"},
            "quality_score": {"validator": lambda v: isinstance(v, (int, float)) and 0 <= v <= 1, "message": "quality_score must be between 0 and 1"},
            "metadata": {"validator": lambda v: isinstance(v, dict), "message": "metadata must be a dictionary"},
            "tags": {"validator": lambda v: isinstance(v, list), "message": "tags must be a list"},
        },
        "valid_units": ["celsius", "fahrenheit", "kelvin", "percent", "ppm", "hpa", "ms", "count", "bytes", "mbps"],
    },
    "api_event": {
        "required_fields": {
            "source_id": {"validator": _is_non_empty_string, "message": "source_id must be a non-empty string"},
            "event_type": {"validator": _is_non_empty_string, "message": "event_type must be a non-empty string"},
            "payload": {"validator": lambda v: isinstance(v, dict), "message": "payload must be a dictionary"},
        },
        "optional_fields": {
            "timestamp": {"validator": _is_valid_timestamp, "message": "timestamp must be valid ISO format"},
            "priority": {"validator": lambda v: isinstance(v, str) and v in ("low", "medium", "high", "critical"), "message": "priority must be low/medium/high/critical"},
            "metadata": {"validator": lambda v: isinstance(v, dict), "message": "metadata must be a dictionary"},
        },
    },
    "transaction": {
        "required_fields": {
            "source_id": {"validator": _is_non_empty_string, "message": "source_id must be a non-empty string"},
            "amount": {"validator": _is_positive_number, "message": "amount must be a positive number"},
            "currency": {"validator": _is_non_empty_string, "message": "currency must be a non-empty string"},
            "category": {"validator": _is_non_empty_string, "message": "category must be a non-empty string"},
        },
        "optional_fields": {
            "timestamp": {"validator": _is_valid_timestamp, "message": "timestamp must be valid ISO format"},
            "description": {"validator": _is_non_empty_string, "message": "description must be a non-empty string"},
            "metadata": {"validator": lambda v: isinstance(v, dict), "message": "metadata must be a dictionary"},
        },
    },
}


def validate_record(record: dict[str, Any], record_type: Optional[str] = None) -> dict[str, Any]:
    """
    Validate an incoming record against its schema.

    Args:
        record: The record to validate
        record_type: The type of record (auto-detected if not provided)

    Returns:
        The validated record with normalized fields

    Raises:
        ValidationError: If the record fails validation
    """
    if not isinstance(record, dict):
        raise ValidationError("Record must be a dictionary")

    if not record:
        raise ValidationError("Record cannot be empty")

    # Auto-detect record type
    if record_type is None:
        record_type = record.get("record_type", "sensor_reading")

    schema = RECORD_SCHEMAS.get(record_type)
    if schema is None:
        raise ValidationError(
            f"Unknown record type: {record_type}",
            field="record_type",
            errors=[f"Valid types: {', '.join(RECORD_SCHEMAS.keys())}"],
        )

    errors = []

    # Validate required fields
    for field_name, rules in schema.get("required_fields", {}).items():
        if field_name not in record:
            errors.append(f"Missing required field: {field_name}")
        elif not rules["validator"](record[field_name]):
            errors.append(rules["message"])

    # Validate optional fields (only if present)
    for field_name, rules in schema.get("optional_fields", {}).items():
        if field_name in record and record[field_name] is not None:
            if not rules["validator"](record[field_name]):
                errors.append(rules["message"])

    # Validate units if applicable
    if "valid_units" in schema and "unit" in record:
        if record["unit"].lower() not in schema["valid_units"]:
            errors.append(
                f"Invalid unit '{record['unit']}'. Valid units: {', '.join(schema['valid_units'])}"
            )

    if errors:
        raise ValidationError(
            f"Validation failed with {len(errors)} error(s)",
            errors=errors,
        )

    # Normalize the record
    validated = dict(record)
    validated["record_type"] = record_type
    if "timestamp" not in validated:
        validated["timestamp"] = datetime.utcnow().isoformat() + "Z"

    return validated


def validate_batch(records: list[dict[str, Any]], record_type: Optional[str] = None) -> dict[str, Any]:
    """
    Validate a batch of records. Returns valid and invalid records separately.
    """
    if not isinstance(records, list):
        raise ValidationError("Batch must be a list of records")

    if len(records) == 0:
        raise ValidationError("Batch cannot be empty")

    if len(records) > 500:
        raise ValidationError(f"Batch too large: {len(records)} records (max 500)")

    valid_records = []
    invalid_records = []

    for i, record in enumerate(records):
        try:
            validated = validate_record(record, record_type)
            valid_records.append(validated)
        except ValidationError as e:
            invalid_records.append({
                "index": i,
                "record": record,
                "error": e.to_dict(),
            })

    return {
        "valid": valid_records,
        "invalid": invalid_records,
        "total": len(records),
        "valid_count": len(valid_records),
        "invalid_count": len(invalid_records),
    }
