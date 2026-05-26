"""
Test helpers — resets global singletons between tests.
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

os.environ["AWS_SAM_LOCAL"] = "true"
os.environ["STAGE"] = "test"
os.environ["LOG_LEVEL"] = "ERROR"


def reset_all():
    """Reset all global singletons for clean test state."""
    from shared.utils.dynamodb import reset_client
    from shared.utils.event_bus import reset_event_bus
    from shared.configs.settings import reset_settings

    reset_client()
    reset_event_bus()
    reset_settings()


def load_service_handler(service_name: str):
    """Load a service handler bypassing sys.modules caching."""
    import importlib.util
    handler_path = os.path.join(PROJECT_ROOT, "services", service_name, "handler.py")
    module_name = f"{service_name.replace('-', '_')}_handler"
    spec = importlib.util.spec_from_file_location(module_name, handler_path)
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    return handler
