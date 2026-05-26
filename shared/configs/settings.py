"""
Environment-based configuration management.

Provides centralized configuration for all services with
environment isolation (dev/staging/prod).
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Settings:
    """
    Platform configuration with environment-based overrides.

    Configuration hierarchy:
    1. Environment variables (highest priority)
    2. Stage-specific defaults
    3. Global defaults (lowest priority)
    """

    # Environment
    stage: str = "dev"
    region: str = "us-east-1"
    account_id: str = "123456789012"

    # DynamoDB tables
    raw_events_table: str = "serverless-platform-raw-events"
    processed_data_table: str = "serverless-platform-processed-data"
    analytics_table: str = "serverless-platform-analytics"

    # S3
    archive_bucket: str = "serverless-platform-archive"
    data_bucket: str = "serverless-platform-data"

    # API Configuration
    api_stage: str = "v1"
    api_throttle_rate: int = 1000
    api_throttle_burst: int = 500

    # Lambda Configuration
    lambda_timeout: int = 30
    lambda_memory: int = 256
    lambda_max_retries: int = 3

    # DynamoDB Configuration
    dynamodb_read_capacity: int = 25
    dynamodb_write_capacity: int = 25
    dynamodb_ttl_days_raw: int = 30
    dynamodb_ttl_days_processed: int = 90

    # Logging
    log_level: str = "INFO"
    enable_request_tracing: bool = True

    # Feature Flags
    enable_notifications: bool = True
    enable_cost_tracking: bool = True
    enable_batch_processing: bool = True

    # Processing Configuration
    batch_size: int = 25
    processing_concurrency: int = 5
    quality_threshold: float = 0.5

    # Notification Configuration
    alert_email: str = "alerts@platform.example.com"
    notification_channels: list = field(default_factory=lambda: ["log", "webhook"])

    # S3 Lifecycle
    s3_transition_ia_days: int = 30
    s3_transition_glacier_days: int = 90
    s3_expiration_days: int = 365

    # Multi-region (simulated)
    primary_region: str = "us-east-1"
    secondary_region: str = "us-west-2"
    enable_multi_region: bool = False

    # Local simulation
    is_local: bool = True
    local_server_port: int = 5000

    def __post_init__(self):
        """Override with environment variables."""
        self.stage = os.environ.get("STAGE", self.stage)
        self.region = os.environ.get("AWS_REGION", self.region)
        self.log_level = os.environ.get("LOG_LEVEL", self.log_level)
        self.is_local = os.environ.get("AWS_SAM_LOCAL", "true").lower() == "true"

        # Stage-specific table names
        prefix = f"serverless-platform-{self.stage}"
        self.raw_events_table = os.environ.get("RAW_EVENTS_TABLE", f"{prefix}-raw-events")
        self.processed_data_table = os.environ.get("PROCESSED_DATA_TABLE", f"{prefix}-processed-data")
        self.analytics_table = os.environ.get("ANALYTICS_TABLE", f"{prefix}-analytics")
        self.archive_bucket = os.environ.get("ARCHIVE_BUCKET", f"{prefix}-archive")
        self.data_bucket = os.environ.get("DATA_BUCKET", f"{prefix}-data")

        # Lambda settings
        self.lambda_timeout = int(os.environ.get("LAMBDA_TIMEOUT", self.lambda_timeout))
        self.lambda_memory = int(os.environ.get("LAMBDA_MEMORY", self.lambda_memory))

        # Processing settings
        self.batch_size = int(os.environ.get("BATCH_SIZE", self.batch_size))
        self.quality_threshold = float(os.environ.get("QUALITY_THRESHOLD", self.quality_threshold))

        # Port
        self.local_server_port = int(os.environ.get("PORT", self.local_server_port))

    def get_table_name(self, base_name: str) -> str:
        """Get the full table name with stage prefix."""
        return f"serverless-platform-{self.stage}-{base_name}"

    def to_dict(self) -> dict:
        """Export settings as dictionary (for Lambda environment variables)."""
        return {
            "STAGE": self.stage,
            "AWS_REGION": self.region,
            "RAW_EVENTS_TABLE": self.raw_events_table,
            "PROCESSED_DATA_TABLE": self.processed_data_table,
            "ANALYTICS_TABLE": self.analytics_table,
            "ARCHIVE_BUCKET": self.archive_bucket,
            "LOG_LEVEL": self.log_level,
            "BATCH_SIZE": str(self.batch_size),
            "QUALITY_THRESHOLD": str(self.quality_threshold),
            "ENABLE_NOTIFICATIONS": str(self.enable_notifications).lower(),
            "ENABLE_COST_TRACKING": str(self.enable_cost_tracking).lower(),
        }

    def to_cloudformation_params(self) -> dict:
        """Export as CloudFormation parameter overrides."""
        return {
            "Stage": self.stage,
            "Region": self.region,
            "LambdaTimeout": str(self.lambda_timeout),
            "LambdaMemory": str(self.lambda_memory),
            "DynamoDBReadCapacity": str(self.dynamodb_read_capacity),
            "DynamoDBWriteCapacity": str(self.dynamodb_write_capacity),
        }


# Singleton settings
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset settings (useful for testing with different environments)."""
    global _settings
    _settings = None
