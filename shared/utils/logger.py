"""
Structured JSON logging with correlation IDs and request tracing.

Provides consistent log formatting across all Lambda services with
CloudWatch-compatible structured output.
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


class StructuredFormatter(logging.Formatter):
    """Formats log records as structured JSON for CloudWatch ingestion."""

    def __init__(self, service_name: str = "unknown"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add correlation ID if present
        if hasattr(record, "correlation_id"):
            log_entry["correlation_id"] = record.correlation_id

        # Add request context if present
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id

        # Add extra fields
        if hasattr(record, "extra_fields"):
            log_entry.update(record.extra_fields)

        # Add exception info
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info),
            }

        return json.dumps(log_entry, default=str)


class StructuredLogger:
    """
    Production-grade structured logger with correlation tracking.

    Usage:
        logger = StructuredLogger("ingestion-service")
        logger.info("Processing record", record_id="abc-123", batch_size=50)
        logger.error("Validation failed", error="Missing field 'source_id'")
    """

    def __init__(self, service_name: str, level: Optional[str] = None):
        self.service_name = service_name
        self.correlation_id: Optional[str] = None
        self.request_id: Optional[str] = None
        self._start_times: dict[str, float] = {}

        log_level = level or os.environ.get("LOG_LEVEL", "INFO")
        self.logger = logging.getLogger(f"platform.{service_name}")
        self.logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

        # Avoid duplicate handlers on re-initialization
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(StructuredFormatter(service_name))
            self.logger.addHandler(handler)
            self.logger.propagate = False

    def set_correlation_id(self, correlation_id: Optional[str] = None) -> str:
        """Set or generate a correlation ID for request tracing."""
        self.correlation_id = correlation_id or str(uuid.uuid4())
        return self.correlation_id

    def set_request_id(self, request_id: str) -> None:
        """Set the AWS request ID from Lambda context."""
        self.request_id = request_id

    def _log(self, level: int, message: str, **kwargs: Any) -> None:
        """Internal log method that injects context."""
        extra = {
            "extra_fields": kwargs,
        }
        if self.correlation_id:
            extra["correlation_id"] = self.correlation_id
        if self.request_id:
            extra["request_id"] = self.request_id

        record = self.logger.makeRecord(
            name=self.logger.name,
            level=level,
            fn="",
            lno=0,
            msg=message,
            args=(),
            exc_info=None,
        )
        for key, value in extra.items():
            setattr(record, key, value)

        self.logger.handle(record)

    def info(self, message: str, **kwargs: Any) -> None:
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, message, **kwargs)

    def debug(self, message: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, message, **kwargs)

    def start_timer(self, operation: str) -> None:
        """Start timing an operation for performance tracking."""
        self._start_times[operation] = time.time()

    def end_timer(self, operation: str, **kwargs: Any) -> float:
        """End timing and log the duration in milliseconds."""
        start = self._start_times.pop(operation, None)
        if start is None:
            self.warning(f"Timer '{operation}' was never started")
            return 0.0
        duration_ms = (time.time() - start) * 1000
        self.info(
            f"Operation completed: {operation}",
            operation=operation,
            duration_ms=round(duration_ms, 2),
            **kwargs,
        )
        return duration_ms

    def log_lambda_start(self, event: dict, context: Any = None) -> str:
        """Log the start of a Lambda invocation with context."""
        correlation_id = self.set_correlation_id(
            event.get("headers", {}).get("x-correlation-id")
            if isinstance(event.get("headers"), dict)
            else None
        )
        if context:
            self.set_request_id(getattr(context, "aws_request_id", "local"))

        self.info(
            "Lambda invocation started",
            event_source=event.get("source", "api-gateway"),
            http_method=event.get("httpMethod", "N/A"),
            path=event.get("path", "N/A"),
            correlation_id=correlation_id,
        )
        self.start_timer("lambda_execution")
        return correlation_id

    def log_lambda_end(self, status_code: int = 200, **kwargs: Any) -> float:
        """Log the end of a Lambda invocation."""
        duration = self.end_timer("lambda_execution", status_code=status_code, **kwargs)
        return duration


# Module-level convenience function
_loggers: dict[str, StructuredLogger] = {}


def get_logger(service_name: str, level: Optional[str] = None) -> StructuredLogger:
    """Get or create a structured logger for the given service."""
    if service_name not in _loggers:
        _loggers[service_name] = StructuredLogger(service_name, level)
    return _loggers[service_name]
