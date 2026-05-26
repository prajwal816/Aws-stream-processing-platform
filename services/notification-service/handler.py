"""
Notification Service — Lambda Handler

Handles event-based alerts and failure notifications.
Triggered by processing completion/failure events.

Endpoints:
    POST /notify         — Send a notification
    GET  /notifications  — List recent notifications
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

_service_dir = os.path.dirname(os.path.abspath(__file__))
if _service_dir not in sys.path:
    sys.path.insert(0, _service_dir)

from shared.utils.logger import get_logger
from shared.utils.metrics import get_metrics, MetricUnit
from shared.utils.response import api_response, error_response, internal_error
from shared.utils.event_bus import get_event_bus, Topics
from shared.schemas.events import NotificationEvent, NotificationType, AlertSeverity
from shared.configs.settings import get_settings
from channels import NotificationChannelManager
from templates import TemplateEngine

logger = get_logger("notification-service")
metrics = get_metrics("notification-service")
settings = get_settings()
event_bus = get_event_bus()

channel_manager = NotificationChannelManager()
template_engine = TemplateEngine()

# Store notifications in-memory for the local simulation
_notification_store: list[dict] = []


def handle_notification(event, context=None):
    """
    Handle an incoming notification event.

    Can be triggered by:
    - Event bus (processing.completed, processing.failed, etc.)
    - Direct API call (POST /notify)
    """
    correlation_id = logger.log_lambda_start(event, context)
    metrics.increment("lambda_invocations")

    try:
        # Parse event data
        if isinstance(event, dict) and "body" in event:
            body = event.get("body", "{}")
            if isinstance(body, str):
                body = json.loads(body)
        else:
            body = event

        # Determine notification type and build notification
        notification = _build_notification(body, correlation_id)

        # Render notification content from template
        rendered = template_engine.render(notification)
        notification.title = rendered["title"]
        notification.message = rendered["message"]

        # Send through notification channels
        send_results = channel_manager.send(notification)

        # Store notification
        notification_dict = notification.to_dict()
        notification_dict["send_results"] = send_results
        _notification_store.append(notification_dict)

        # Keep store bounded
        if len(_notification_store) > 1000:
            _notification_store.pop(0)

        metrics.increment("notifications_sent")
        duration = logger.log_lambda_end(status_code=200)
        metrics.record("lambda_execution_duration", duration, MetricUnit.MILLISECONDS)

        logger.info(
            "Notification sent",
            notification_id=notification.notification_id,
            type=notification.notification_type,
            severity=notification.severity,
            channels=list(send_results.keys()),
        )

        return api_response(
            200,
            {
                "notification_id": notification.notification_id,
                "type": notification.notification_type,
                "severity": notification.severity,
                "channels": send_results,
                "title": notification.title,
            },
            message="Notification sent",
            correlation_id=correlation_id,
        )

    except Exception as e:
        logger.error(f"Notification failed: {str(e)}")
        metrics.increment("notification_errors")
        logger.log_lambda_end(status_code=500)
        return internal_error(str(e), correlation_id=correlation_id)


def handle_failure(event, context=None):
    """
    Handle a processing failure — dead-letter queue handler.
    """
    correlation_id = logger.log_lambda_start(event, context)
    metrics.increment("lambda_invocations")
    metrics.increment("failure_notifications")

    try:
        if isinstance(event, dict) and "body" in event:
            body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]
        else:
            body = event

        error_msg = body.get("error", "Unknown error")
        source_event = body.get("event", {})

        notification = NotificationEvent(
            notification_type=NotificationType.PROCESSING_FAILED.value,
            severity=AlertSeverity.ERROR.value,
            title="Processing Failure Alert",
            message=f"Processing failed: {error_msg}",
            source_service="processing-service",
            correlation_id=correlation_id,
            metadata={
                "error": error_msg,
                "source_event": source_event,
            },
        )

        rendered = template_engine.render(notification)
        notification.title = rendered["title"]
        notification.message = rendered["message"]

        send_results = channel_manager.send(notification)

        notification_dict = notification.to_dict()
        notification_dict["send_results"] = send_results
        _notification_store.append(notification_dict)

        duration = logger.log_lambda_end(status_code=200)
        metrics.record("lambda_execution_duration", duration, MetricUnit.MILLISECONDS)

        return api_response(
            200,
            {
                "notification_id": notification.notification_id,
                "type": "failure_alert",
                "error": error_msg,
            },
            message="Failure notification sent",
            correlation_id=correlation_id,
        )

    except Exception as e:
        logger.error(f"Failure notification failed: {str(e)}")
        return internal_error(str(e), correlation_id=correlation_id)


def get_notifications(event, context=None):
    """
    Get recent notifications.
    GET /notifications?limit=50&severity=error
    """
    correlation_id = logger.log_lambda_start(event, context)
    metrics.increment("lambda_invocations")
    metrics.increment("api_requests")

    try:
        params = event.get("queryStringParameters") or {}
        limit = int(params.get("limit", "50"))
        severity = params.get("severity")
        notif_type = params.get("type")

        results = list(_notification_store)

        if severity:
            results = [n for n in results if n.get("severity") == severity]
        if notif_type:
            results = [n for n in results if n.get("notification_type") == notif_type]

        results = results[-limit:]
        results.reverse()  # Most recent first

        duration = logger.log_lambda_end(status_code=200)

        return api_response(
            200,
            {
                "notifications": results,
                "count": len(results),
                "total": len(_notification_store),
            },
            message="Notifications retrieved",
            correlation_id=correlation_id,
        )

    except Exception as e:
        logger.error(f"Get notifications failed: {str(e)}")
        return internal_error(str(e), correlation_id=correlation_id)


def _build_notification(data: dict, correlation_id: str) -> NotificationEvent:
    """Build a NotificationEvent from event data."""
    # Determine notification type based on event content
    if data.get("status") == "completed":
        notif_type = NotificationType.PROCESSING_COMPLETE.value
        severity = AlertSeverity.INFO.value
    elif data.get("error") or data.get("status") == "failed":
        notif_type = NotificationType.PROCESSING_FAILED.value
        severity = AlertSeverity.ERROR.value
    elif data.get("threshold_exceeded"):
        notif_type = NotificationType.THRESHOLD_EXCEEDED.value
        severity = AlertSeverity.WARNING.value
    else:
        notif_type = data.get("notification_type", NotificationType.SYSTEM_ALERT.value)
        severity = data.get("severity", AlertSeverity.INFO.value)

    return NotificationEvent(
        notification_type=notif_type,
        severity=severity,
        title=data.get("title", ""),
        message=data.get("message", ""),
        source_service=data.get("source_service", "unknown"),
        correlation_id=correlation_id,
        metadata=data,
    )


def lambda_handler(event, context=None):
    """Main Lambda entry point."""
    http_method = event.get("httpMethod", "")
    path = event.get("path", "")

    if http_method == "OPTIONS":
        from shared.utils.response import options_response
        return options_response()

    if path in ("/notify", "/v1/notify") and http_method == "POST":
        return handle_notification(event, context)
    elif path in ("/notifications", "/v1/notifications") and http_method == "GET":
        return get_notifications(event, context)
    else:
        # Assume event bus invocation
        return handle_notification(event, context)
