"""
Unit tests for the Notification Service.
"""

import json
import os
import sys
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "services", "notification-service"))

os.environ["AWS_SAM_LOCAL"] = "true"
os.environ["STAGE"] = "test"
os.environ["LOG_LEVEL"] = "ERROR"

from tests.unit.services_test_helpers import reset_all


def setup_function():
    reset_all()


class TestTemplateEngine:
    """Tests for notification templates."""

    def test_render_processing_complete(self):
        from templates import TemplateEngine
        from shared.schemas.events import NotificationEvent, NotificationType
        engine = TemplateEngine()
        notif = NotificationEvent(
            notification_type=NotificationType.PROCESSING_COMPLETE.value,
            metadata={"record_id": "r123", "source_id": "s1", "category": "temp"},
        )
        result = engine.render(notif)
        assert "Processing Complete" in result["title"]
        assert "r123" in result["message"]

    def test_render_processing_failed(self):
        from templates import TemplateEngine
        from shared.schemas.events import NotificationEvent, NotificationType
        engine = TemplateEngine()
        notif = NotificationEvent(
            notification_type=NotificationType.PROCESSING_FAILED.value,
            source_service="processing-service",
            metadata={"error": "timeout"},
        )
        result = engine.render(notif)
        assert "Failure" in result["title"]
        assert "timeout" in result["message"]

    def test_render_unknown_type(self):
        from templates import TemplateEngine
        from shared.schemas.events import NotificationEvent
        engine = TemplateEngine()
        notif = NotificationEvent(
            notification_type="unknown_type",
            title="Custom Title",
            message="Custom message",
        )
        result = engine.render(notif)
        assert result["title"] == "Custom Title"


class TestChannels:
    """Tests for notification channels."""

    def test_log_channel(self):
        from channels import LogChannel
        from shared.schemas.events import NotificationEvent, AlertSeverity
        channel = LogChannel()
        notif = NotificationEvent(
            title="Test Alert",
            message="Test message",
            severity=AlertSeverity.WARNING.value,
        )
        result = channel.send(notif)
        assert result["status"] == "sent"
        assert result["channel"] == "log"

    def test_webhook_channel(self):
        from channels import WebhookChannel
        from shared.schemas.events import NotificationEvent
        channel = WebhookChannel()
        notif = NotificationEvent(title="Test", message="Test")
        result = channel.send(notif)
        assert result["status"] == "sent_simulated"
        assert result["channel"] == "webhook"

    def test_email_channel(self):
        from channels import EmailChannel
        from shared.schemas.events import NotificationEvent
        channel = EmailChannel()
        notif = NotificationEvent(title="Test", message="Test")
        result = channel.send(notif)
        assert result["status"] == "sent_simulated"
        assert result["channel"] == "email"

    def test_channel_manager(self):
        from channels import NotificationChannelManager
        from shared.schemas.events import NotificationEvent
        mgr = NotificationChannelManager()
        notif = NotificationEvent(title="Test", message="Test")
        results = mgr.send(notif)
        assert "log" in results
        assert "webhook" in results
        assert "email" in results


class TestNotificationHandler:
    """Tests for the notification Lambda handler."""

    def test_handle_notification(self):
        import handler
        event = {
            "httpMethod": "POST",
            "path": "/notify",
            "body": json.dumps({
                "status": "completed",
                "record_id": "r1",
                "source_service": "processing",
            }),
            "headers": {},
        }
        result = handler.handle_notification(event)
        assert result["statusCode"] == 200

    def test_handle_failure(self):
        import handler
        event = {
            "body": json.dumps({"error": "Connection timeout", "event": {}}),
            "headers": {},
        }
        result = handler.handle_failure(event)
        assert result["statusCode"] == 200

    def test_get_notifications_empty(self):
        import handler
        event = {
            "httpMethod": "GET",
            "path": "/notifications",
            "queryStringParameters": {},
            "headers": {},
        }
        result = handler.get_notifications(event)
        assert result["statusCode"] == 200
