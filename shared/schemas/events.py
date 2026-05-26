"""
Data schemas and models for the platform.

Defines the core data structures used across all services
with serialization/deserialization support.
"""

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class EventType(str, Enum):
    """Types of events flowing through the platform."""
    SENSOR_READING = "sensor_reading"
    API_EVENT = "api_event"
    TRANSACTION = "transaction"
    SYSTEM_EVENT = "system_event"
    ALERT = "alert"


class ProcessingStatus(str, Enum):
    """Processing pipeline statuses."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NotificationType(str, Enum):
    """Types of notifications."""
    PROCESSING_COMPLETE = "processing_complete"
    PROCESSING_FAILED = "processing_failed"
    THRESHOLD_EXCEEDED = "threshold_exceeded"
    SYSTEM_ALERT = "system_alert"
    DAILY_SUMMARY = "daily_summary"


@dataclass
class RawEvent:
    """
    Represents a raw incoming event before processing.
    Stored in the RawEvents DynamoDB table.
    """
    source_id: str
    timestamp: str
    event_type: str = EventType.SENSOR_READING.value
    record_type: str = "sensor_reading"
    value: float = 0.0
    unit: str = "count"
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ingested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ttl_expiry: int = 0  # Epoch seconds for DynamoDB TTL
    metadata: dict = field(default_factory=dict)
    tags: list = field(default_factory=list)
    quality_score: float = 1.0
    location: str = ""
    payload: dict = field(default_factory=dict)
    priority: str = "medium"
    amount: float = 0.0
    currency: str = ""
    category: str = ""
    description: str = ""

    def __post_init__(self):
        if self.ttl_expiry == 0:
            # Default TTL: 30 days from ingestion
            from datetime import timedelta
            expiry = datetime.now(timezone.utc) + timedelta(days=30)
            self.ttl_expiry = int(expiry.timestamp())

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v or v == 0}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RawEvent":
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class ProcessedRecord:
    """
    Represents a processed and transformed record.
    Stored in the ProcessedData DynamoDB table.
    """
    record_id: str
    processed_at: str
    source_event_id: str
    source_id: str
    event_type: str
    category: str = "general"
    status: str = ProcessingStatus.COMPLETED.value
    original_value: float = 0.0
    normalized_value: float = 0.0
    unit: str = "count"
    aggregation_key: str = ""
    quality_score: float = 1.0
    processing_duration_ms: float = 0.0
    transformations_applied: list = field(default_factory=list)
    enrichment_data: dict = field(default_factory=dict)
    tags: list = field(default_factory=list)
    ttl_expiry: int = 0
    correlation_id: str = ""

    def __post_init__(self):
        if self.ttl_expiry == 0:
            from datetime import timedelta
            expiry = datetime.now(timezone.utc) + timedelta(days=90)
            self.ttl_expiry = int(expiry.timestamp())
        if not self.aggregation_key:
            self.aggregation_key = f"{self.source_id}#{self.category}"

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v or v == 0}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProcessedRecord":
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class AnalyticsSummary:
    """
    Represents an aggregated analytics summary.
    Stored in the AnalyticsSummaries DynamoDB table.
    """
    metric_name: str
    period: str  # "hourly#2024-01-01T00:00:00Z", "daily#2024-01-01", etc.
    count: int = 0
    sum_value: float = 0.0
    avg_value: float = 0.0
    min_value: float = float("inf")
    max_value: float = float("-inf")
    p50_value: float = 0.0
    p95_value: float = 0.0
    p99_value: float = 0.0
    category: str = "general"
    source_ids: list = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Handle infinity values for JSON serialization
        if d["min_value"] == float("inf"):
            d["min_value"] = 0
        if d["max_value"] == float("-inf"):
            d["max_value"] = 0
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalyticsSummary":
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def update_with_value(self, value: float) -> None:
        """Update running statistics with a new value."""
        self.count += 1
        self.sum_value += value
        self.avg_value = self.sum_value / self.count
        self.min_value = min(self.min_value, value)
        self.max_value = max(self.max_value, value)
        self.last_updated = datetime.now(timezone.utc).isoformat()


@dataclass
class NotificationEvent:
    """
    Represents a notification to be sent.
    """
    notification_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    notification_type: str = NotificationType.SYSTEM_ALERT.value
    severity: str = AlertSeverity.INFO.value
    title: str = ""
    message: str = ""
    source_service: str = ""
    correlation_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    recipients: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    acknowledged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NotificationEvent":
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class PipelineEvent:
    """
    Internal event used for inter-service communication via the event bus.
    """
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    source_service: str = ""
    target_service: str = ""
    payload: dict = field(default_factory=dict)
    correlation_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    retry_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineEvent":
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)
