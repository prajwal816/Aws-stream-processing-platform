"""
Event bus for async Lambda chaining with local simulation.

In production, wraps AWS SNS/SQS for event routing.
Locally, uses an in-memory queue system with retry support.
"""

import json
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from shared.utils.logger import get_logger
from shared.utils.metrics import get_metrics

logger = get_logger("event-bus")
metrics = get_metrics("event-bus")


class EventBus:
    """
    In-memory event bus that simulates SNS/SQS async event routing.

    Supports:
    - Topic-based publish/subscribe
    - Retry logic with configurable attempts
    - Dead-letter queue for failed events
    - Event history for auditing
    """

    def __init__(self, max_retries: int = 3, retry_delay_ms: int = 100):
        self.max_retries = max_retries
        self.retry_delay_ms = retry_delay_ms
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._event_history: list[dict[str, Any]] = []
        self._dead_letter_queue: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._processing = False

    def subscribe(self, topic: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        """Subscribe a handler to a topic."""
        with self._lock:
            self._subscribers[topic].append(handler)
        logger.info(f"Handler subscribed to topic: {topic}")

    def unsubscribe(self, topic: str, handler: Callable) -> None:
        """Unsubscribe a handler from a topic."""
        with self._lock:
            if topic in self._subscribers:
                self._subscribers[topic] = [
                    h for h in self._subscribers[topic] if h != handler
                ]

    def publish(
        self,
        topic: str,
        message: dict[str, Any],
        correlation_id: Optional[str] = None,
        source: str = "unknown",
    ) -> str:
        """
        Publish an event to a topic. Returns the event ID.

        In local mode, synchronously invokes all subscribers.
        """
        event_id = str(uuid.uuid4())
        event = {
            "event_id": event_id,
            "topic": topic,
            "message": message,
            "correlation_id": correlation_id or str(uuid.uuid4()),
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "retry_count": 0,
            "status": "published",
        }

        with self._lock:
            self._event_history.append(event.copy())

        metrics.increment("events_published")
        logger.info(
            f"Event published to {topic}",
            event_id=event_id,
            topic=topic,
            source=source,
        )

        # Process synchronously in local mode
        self._process_event(event)
        return event_id

    def _process_event(self, event: dict[str, Any]) -> None:
        """Process an event by invoking all subscribers with retry logic."""
        topic = event["topic"]

        with self._lock:
            handlers = list(self._subscribers.get(topic, []))

        if not handlers:
            logger.warning(f"No subscribers for topic: {topic}")
            return

        for handler in handlers:
            success = False
            last_error = None

            for attempt in range(self.max_retries + 1):
                try:
                    handler(event["message"])
                    success = True
                    metrics.increment("events_processed")
                    break
                except Exception as e:
                    last_error = str(e)
                    event["retry_count"] = attempt + 1
                    logger.warning(
                        f"Event processing failed (attempt {attempt + 1}/{self.max_retries + 1})",
                        event_id=event["event_id"],
                        topic=topic,
                        error=last_error,
                    )
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay_ms / 1000)

            if not success:
                event["status"] = "failed"
                event["error"] = last_error
                with self._lock:
                    self._dead_letter_queue.append(event.copy())
                metrics.increment("events_failed")
                logger.error(
                    f"Event moved to DLQ after {self.max_retries + 1} attempts",
                    event_id=event["event_id"],
                    topic=topic,
                    error=last_error,
                )
            else:
                event["status"] = "processed"

    def get_event_history(self, topic: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        """Get event history, optionally filtered by topic."""
        with self._lock:
            events = self._event_history
            if topic:
                events = [e for e in events if e["topic"] == topic]
            return events[-limit:]

    def get_dead_letter_queue(self) -> list[dict[str, Any]]:
        """Get all events in the dead-letter queue."""
        with self._lock:
            return list(self._dead_letter_queue)

    def get_stats(self) -> dict[str, Any]:
        """Get event bus statistics."""
        with self._lock:
            topic_counts = defaultdict(int)
            for event in self._event_history:
                topic_counts[event["topic"]] += 1

            return {
                "total_events": len(self._event_history),
                "dlq_size": len(self._dead_letter_queue),
                "topics": dict(topic_counts),
                "subscriber_counts": {
                    topic: len(handlers)
                    for topic, handlers in self._subscribers.items()
                },
            }

    def clear(self) -> None:
        """Clear all event history and DLQ."""
        with self._lock:
            self._event_history.clear()
            self._dead_letter_queue.clear()


# Topic constants
class Topics:
    """Standard event topics for the platform."""
    RECORD_INGESTED = "record.ingested"
    RECORD_VALIDATED = "record.validated"
    BATCH_INGESTED = "batch.ingested"
    PROCESSING_STARTED = "processing.started"
    PROCESSING_COMPLETED = "processing.completed"
    PROCESSING_FAILED = "processing.failed"
    ANALYTICS_UPDATED = "analytics.updated"
    ALERT_TRIGGERED = "alert.triggered"
    HEALTH_CHECK = "health.check"
    THRESHOLD_EXCEEDED = "threshold.exceeded"


# Singleton event bus
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def reset_event_bus() -> None:
    """Reset the global event bus (useful for testing)."""
    global _event_bus
    _event_bus = None
