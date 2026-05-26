"""
Flask-based local API server mimicking API Gateway.

Serves REST endpoints that invoke Lambda handlers directly,
and serves the web dashboard for visualizing platform metrics.
"""

import json
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

os.environ["AWS_SAM_LOCAL"] = "true"
os.environ["STAGE"] = "dev"
os.environ["LOG_LEVEL"] = "INFO"

from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS

# Import shared modules
from shared.utils.logger import get_logger
from shared.utils.metrics import get_metrics, get_all_metrics
from shared.utils.event_bus import get_event_bus, Topics
from shared.configs.settings import get_settings

logger = get_logger("local-server")
settings = get_settings()

# Import service handlers
def load_handlers():
    """Load all Lambda handlers."""
    services = {
        "ingestion": os.path.join(PROJECT_ROOT, "services", "ingestion-service"),
        "processing": os.path.join(PROJECT_ROOT, "services", "processing-service"),
        "analytics": os.path.join(PROJECT_ROOT, "services", "analytics-service"),
        "notification": os.path.join(PROJECT_ROOT, "services", "notification-service"),
    }

    handlers = {}
    for name, path in services.items():
        if path not in sys.path:
            sys.path.insert(0, path)

    import importlib

    # Must import in correct order to avoid conflicts
    for name, path in services.items():
        sys.path.insert(0, path)

    # Now import each handler
    ingestion_spec = importlib.util.spec_from_file_location(
        "ingestion_handler",
        os.path.join(services["ingestion"], "handler.py")
    )
    ingestion_mod = importlib.util.module_from_spec(ingestion_spec)
    ingestion_spec.loader.exec_module(ingestion_mod)
    handlers["ingestion"] = ingestion_mod

    processing_spec = importlib.util.spec_from_file_location(
        "processing_handler",
        os.path.join(services["processing"], "handler.py")
    )
    processing_mod = importlib.util.module_from_spec(processing_spec)
    processing_spec.loader.exec_module(processing_mod)
    handlers["processing"] = processing_mod

    analytics_spec = importlib.util.spec_from_file_location(
        "analytics_handler",
        os.path.join(services["analytics"], "handler.py")
    )
    analytics_mod = importlib.util.module_from_spec(analytics_spec)
    analytics_spec.loader.exec_module(analytics_mod)
    handlers["analytics"] = analytics_mod

    notification_spec = importlib.util.spec_from_file_location(
        "notification_handler",
        os.path.join(services["notification"], "handler.py")
    )
    notification_mod = importlib.util.module_from_spec(notification_spec)
    notification_spec.loader.exec_module(notification_mod)
    handlers["notification"] = notification_mod

    return handlers


# Wire up event bus
def setup_event_bus(handlers):
    """Wire event bus subscribers for the processing pipeline."""
    event_bus = get_event_bus()

    def process_ingested(message):
        event = {"data": message.get("data", message)}
        handlers["processing"].process_event(event)

    def handle_complete(message):
        handlers["notification"].handle_notification(message)

    def handle_failure(message):
        handlers["notification"].handle_failure(message)

    event_bus.subscribe(Topics.RECORD_INGESTED, process_ingested)
    event_bus.subscribe(Topics.PROCESSING_COMPLETED, handle_complete)
    event_bus.subscribe(Topics.PROCESSING_FAILED, handle_failure)


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__, static_folder=None)
    CORS(app)

    print("⏳ Loading service handlers...")
    handlers = load_handlers()
    print("  ✓ All handlers loaded")

    print("⏳ Setting up event bus...")
    setup_event_bus(handlers)
    print("  ✓ Event bus configured")

    def build_api_event(method="GET", path="/", body=None, params=None):
        """Build an API Gateway-compatible event from Flask request."""
        return {
            "httpMethod": method,
            "path": path,
            "body": json.dumps(body) if body else "{}",
            "queryStringParameters": params or {},
            "headers": dict(request.headers),
            "requestContext": {
                "requestId": "local-" + str(int(time.time() * 1000)),
            },
        }

    def lambda_response_to_flask(result):
        """Convert Lambda response to Flask response."""
        status = result.get("statusCode", 200)
        headers = result.get("headers", {})
        body = result.get("body", "{}")
        resp = Response(body, status=status, content_type="application/json")
        for k, v in headers.items():
            if k.lower() != "content-type":
                resp.headers[k] = v
        return resp

    # ================================
    # Dashboard (static files)
    # ================================
    dashboard_dir = os.path.join(os.path.dirname(__file__), "dashboard")

    @app.route("/")
    def serve_dashboard():
        return send_from_directory(dashboard_dir, "index.html")

    @app.route("/styles.css")
    def serve_css():
        return send_from_directory(dashboard_dir, "styles.css")

    @app.route("/app.js")
    def serve_js():
        return send_from_directory(dashboard_dir, "app.js")

    # ================================
    # Health
    # ================================
    @app.route("/health", methods=["GET"])
    @app.route("/v1/health", methods=["GET"])
    def health():
        event = build_api_event("GET", "/health")
        result = handlers["ingestion"].health_check(event)
        return lambda_response_to_flask(result)

    # ================================
    # Ingestion endpoints
    # ================================
    @app.route("/ingest", methods=["POST"])
    @app.route("/v1/ingest", methods=["POST"])
    def ingest():
        body = request.get_json(force=True, silent=True) or {}
        event = build_api_event("POST", "/ingest", body)
        result = handlers["ingestion"].ingest_record(event)
        return lambda_response_to_flask(result)

    @app.route("/ingest/batch", methods=["POST"])
    @app.route("/v1/ingest/batch", methods=["POST"])
    def ingest_batch():
        body = request.get_json(force=True, silent=True) or {}
        event = build_api_event("POST", "/ingest/batch", body)
        result = handlers["ingestion"].batch_ingest(event)
        return lambda_response_to_flask(result)

    # ================================
    # Analytics endpoints
    # ================================
    @app.route("/analytics", methods=["GET"])
    @app.route("/v1/analytics", methods=["GET"])
    def analytics():
        event = build_api_event("GET", "/analytics", params=dict(request.args))
        result = handlers["analytics"].get_analytics(event)
        return lambda_response_to_flask(result)

    @app.route("/analytics/dashboard", methods=["GET"])
    @app.route("/v1/analytics/dashboard", methods=["GET"])
    def analytics_dashboard():
        event = build_api_event("GET", "/analytics/dashboard", params=dict(request.args))
        result = handlers["analytics"].get_dashboard_data(event)
        return lambda_response_to_flask(result)

    @app.route("/analytics/records", methods=["GET"])
    @app.route("/v1/analytics/records", methods=["GET"])
    def analytics_records():
        event = build_api_event("GET", "/analytics/records", params=dict(request.args))
        result = handlers["analytics"].get_records(event)
        return lambda_response_to_flask(result)

    @app.route("/analytics/metrics", methods=["GET"])
    @app.route("/v1/analytics/metrics", methods=["GET"])
    def analytics_metrics():
        event = build_api_event("GET", "/analytics/metrics", params=dict(request.args))
        result = handlers["analytics"].get_platform_metrics(event)
        return lambda_response_to_flask(result)

    # ================================
    # Notification endpoints
    # ================================
    @app.route("/notify", methods=["POST"])
    @app.route("/v1/notify", methods=["POST"])
    def notify():
        body = request.get_json(force=True, silent=True) or {}
        event = build_api_event("POST", "/notify", body)
        result = handlers["notification"].handle_notification(event)
        return lambda_response_to_flask(result)

    @app.route("/notifications", methods=["GET"])
    @app.route("/v1/notifications", methods=["GET"])
    def notifications():
        event = build_api_event("GET", "/notifications", params=dict(request.args))
        result = handlers["notification"].get_notifications(event)
        return lambda_response_to_flask(result)

    # ================================
    # Processing endpoints
    # ================================
    @app.route("/process", methods=["POST"])
    @app.route("/v1/process", methods=["POST"])
    def process():
        body = request.get_json(force=True, silent=True) or {}
        event = build_api_event("POST", "/process", body)
        result = handlers["processing"].process_event(event)
        return lambda_response_to_flask(result)

    # ================================
    # Simulation endpoint (for dashboard)
    # ================================
    @app.route("/api/simulate", methods=["POST"])
    def run_sim():
        """Run a mini simulation from the dashboard."""
        body = request.get_json(force=True, silent=True) or {}
        count = body.get("count", 500)

        from scripts.generate_data import generate_batch
        records = generate_batch(count=count)

        event = build_api_event("POST", "/ingest/batch", {"records": records})
        result = handlers["ingestion"].batch_ingest(event)
        return lambda_response_to_flask(result)

    return app


def main():
    port = int(os.environ.get("PORT", 5000))
    app = create_app()

    print("\n" + "=" * 60)
    print("  SERVERLESS DATA PLATFORM — LOCAL SERVER")
    print("=" * 60)
    print(f"\n  🌐 Dashboard:  http://localhost:{port}")
    print(f"  📡 API Base:   http://localhost:{port}/v1")
    print(f"  🏥 Health:     http://localhost:{port}/health")
    print(f"\n  API Endpoints:")
    print(f"    POST /ingest          — Ingest single record")
    print(f"    POST /ingest/batch    — Batch ingest records")
    print(f"    GET  /analytics       — Get analytics")
    print(f"    GET  /analytics/dashboard — Dashboard data")
    print(f"    GET  /analytics/records   — Query records")
    print(f"    GET  /notifications   — List notifications")
    print(f"    POST /api/simulate    — Run mini simulation")
    print("=" * 60 + "\n")

    # Open browser after a short delay
    def open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=open_browser, daemon=True).start()

    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
