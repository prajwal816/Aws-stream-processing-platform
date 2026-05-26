"""
Alert message templates for different notification event types.

Provides formatted notification content based on event type and severity.
"""

from datetime import datetime, timezone
from typing import Any

from shared.schemas.events import NotificationEvent, NotificationType, AlertSeverity


class TemplateEngine:
    """
    Renders notification templates based on event type.
    """

    TEMPLATES = {
        NotificationType.PROCESSING_COMPLETE.value: {
            "title": "✅ Processing Complete",
            "body": (
                "Record processing completed successfully.\n"
                "- Record ID: {record_id}\n"
                "- Source: {source_id}\n"
                "- Category: {category}\n"
                "- Processing Time: {processing_time}"
            ),
        },
        NotificationType.PROCESSING_FAILED.value: {
            "title": "❌ Processing Failure",
            "body": (
                "A record failed to process.\n"
                "- Error: {error}\n"
                "- Source Service: {source_service}\n"
                "- Correlation ID: {correlation_id}\n"
                "- Action Required: Review logs and retry."
            ),
        },
        NotificationType.THRESHOLD_EXCEEDED.value: {
            "title": "⚠️ Threshold Exceeded",
            "body": (
                "A monitored metric has exceeded its threshold.\n"
                "- Metric: {metric_name}\n"
                "- Current Value: {current_value}\n"
                "- Threshold: {threshold}\n"
                "- Severity: {severity}"
            ),
        },
        NotificationType.SYSTEM_ALERT.value: {
            "title": "🔔 System Alert",
            "body": (
                "System alert from {source_service}.\n"
                "- Message: {message}\n"
                "- Severity: {severity}\n"
                "- Timestamp: {timestamp}"
            ),
        },
        NotificationType.DAILY_SUMMARY.value: {
            "title": "📊 Daily Summary Report",
            "body": (
                "Daily Platform Summary\n"
                "═══════════════════════\n"
                "- Records Processed: {total_processed}\n"
                "- Success Rate: {success_rate}%\n"
                "- Avg Latency: {avg_latency}ms\n"
                "- Errors: {total_errors}\n"
                "- Estimated Cost: ${estimated_cost}"
            ),
        },
    }

    def render(self, notification: NotificationEvent) -> dict[str, str]:
        """
        Render a notification using the appropriate template.

        Returns dict with 'title' and 'message' keys.
        """
        template = self.TEMPLATES.get(notification.notification_type)

        if not template:
            return {
                "title": notification.title or "Platform Notification",
                "message": notification.message or "No message provided.",
            }

        # Build context from notification metadata
        context = {
            "severity": notification.severity,
            "source_service": notification.source_service,
            "correlation_id": notification.correlation_id,
            "timestamp": notification.timestamp,
            "message": notification.message,
        }

        # Merge metadata into context
        if notification.metadata:
            context.update({
                k: v for k, v in notification.metadata.items()
                if isinstance(v, (str, int, float, bool))
            })

        # Set defaults for missing template variables
        defaults = {
            "record_id": "N/A",
            "source_id": "N/A",
            "category": "N/A",
            "processing_time": "N/A",
            "error": "Unknown error",
            "metric_name": "N/A",
            "current_value": "N/A",
            "threshold": "N/A",
            "total_processed": "0",
            "success_rate": "0",
            "avg_latency": "0",
            "total_errors": "0",
            "estimated_cost": "0.00",
        }

        for key, default_val in defaults.items():
            context.setdefault(key, default_val)

        # Render template
        try:
            title = template["title"]
            message = template["body"].format(**context)
        except (KeyError, IndexError) as e:
            title = notification.title or template.get("title", "Notification")
            message = notification.message or f"Template rendering error: {str(e)}"

        return {"title": title, "message": message}

    def render_summary(self, stats: dict[str, Any]) -> dict[str, str]:
        """Render a daily summary notification."""
        notification = NotificationEvent(
            notification_type=NotificationType.DAILY_SUMMARY.value,
            severity=AlertSeverity.INFO.value,
            metadata=stats,
        )
        return self.render(notification)
