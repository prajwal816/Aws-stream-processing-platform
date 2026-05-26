"""
Notification channels — routes notifications to appropriate outputs.

Supports: Log-based alerts, webhook simulation, email simulation (SES).
"""

import json
from datetime import datetime, timezone
from typing import Any

from shared.utils.logger import get_logger
from shared.schemas.events import NotificationEvent, AlertSeverity

logger = get_logger("notification-channels")

# In-memory log of all channel outputs (for dashboard display)
_channel_logs: list[dict[str, Any]] = []


class LogChannel:
    """Outputs notifications as structured log entries."""

    def send(self, notification: NotificationEvent) -> dict[str, Any]:
        severity_map = {
            AlertSeverity.INFO.value: logger.info,
            AlertSeverity.WARNING.value: logger.warning,
            AlertSeverity.ERROR.value: logger.error,
            AlertSeverity.CRITICAL.value: logger.critical,
        }
        log_fn = severity_map.get(notification.severity, logger.info)
        log_fn(
            f"[ALERT] {notification.title}: {notification.message}",
            notification_id=notification.notification_id,
            severity=notification.severity,
            notification_type=notification.notification_type,
        )
        return {"status": "sent", "channel": "log", "timestamp": datetime.now(timezone.utc).isoformat()}


class WebhookChannel:
    """Simulates sending notifications via webhook."""

    def __init__(self, webhook_url: str = "https://hooks.example.com/alerts"):
        self.webhook_url = webhook_url

    def send(self, notification: NotificationEvent) -> dict[str, Any]:
        payload = {
            "id": notification.notification_id,
            "type": notification.notification_type,
            "severity": notification.severity,
            "title": notification.title,
            "message": notification.message,
            "timestamp": notification.timestamp,
            "source": notification.source_service,
        }
        # In local mode, simulate the webhook call
        logger.info(
            f"Webhook notification sent (simulated)",
            url=self.webhook_url,
            payload_size=len(json.dumps(payload)),
        )
        return {
            "status": "sent_simulated",
            "channel": "webhook",
            "url": self.webhook_url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class EmailChannel:
    """Simulates sending notifications via email (SES)."""

    def __init__(self, recipient: str = "alerts@platform.example.com"):
        self.recipient = recipient

    def send(self, notification: NotificationEvent) -> dict[str, Any]:
        logger.info(
            f"Email notification sent (simulated)",
            to=self.recipient,
            subject=notification.title,
        )
        return {
            "status": "sent_simulated",
            "channel": "email",
            "recipient": self.recipient,
            "subject": notification.title,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class NotificationChannelManager:
    """
    Manages notification channels and routes notifications to all active channels.
    """

    def __init__(self):
        self.channels = {
            "log": LogChannel(),
            "webhook": WebhookChannel(),
            "email": EmailChannel(),
        }

    def send(self, notification: NotificationEvent) -> dict[str, Any]:
        """Send a notification through all active channels."""
        results = {}
        for name, channel in self.channels.items():
            try:
                result = channel.send(notification)
                results[name] = result
            except Exception as e:
                results[name] = {
                    "status": "failed",
                    "error": str(e),
                    "channel": name,
                }
                logger.error(f"Channel {name} failed: {str(e)}")

        # Store in channel logs
        log_entry = {
            "notification_id": notification.notification_id,
            "type": notification.notification_type,
            "severity": notification.severity,
            "title": notification.title,
            "channels": results,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        _channel_logs.append(log_entry)
        if len(_channel_logs) > 500:
            _channel_logs.pop(0)

        return results

    def get_channel_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent channel log entries."""
        return _channel_logs[-limit:]
