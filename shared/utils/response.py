"""
Standardized API response builder.

Provides consistent response formatting with proper status codes,
CORS headers, and error handling for all API Gateway responses.
"""

import json
from typing import Any, Optional


# Default CORS headers for API Gateway
CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Correlation-Id, X-Api-Key",
    "X-Platform-Version": "1.0.0",
}


def api_response(
    status_code: int = 200,
    body: Optional[Any] = None,
    message: Optional[str] = None,
    headers: Optional[dict[str, str]] = None,
    correlation_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Build a standardized API Gateway response.

    Args:
        status_code: HTTP status code
        body: Response body (will be JSON serialized)
        message: Optional status message
        headers: Additional response headers
        correlation_id: Request correlation ID for tracing

    Returns:
        API Gateway-compatible response dict
    """
    response_body: dict[str, Any] = {
        "status": "success" if status_code < 400 else "error",
        "statusCode": status_code,
    }

    if message:
        response_body["message"] = message

    if body is not None:
        response_body["data"] = body

    if correlation_id:
        response_body["correlationId"] = correlation_id

    response_headers = dict(CORS_HEADERS)
    if correlation_id:
        response_headers["X-Correlation-Id"] = correlation_id
    if headers:
        response_headers.update(headers)

    return {
        "statusCode": status_code,
        "headers": response_headers,
        "body": json.dumps(response_body, default=str),
    }


def error_response(
    status_code: int = 500,
    message: str = "Internal server error",
    error_code: Optional[str] = None,
    details: Optional[Any] = None,
    correlation_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Build a standardized error response.

    Args:
        status_code: HTTP error status code
        message: Error message
        error_code: Machine-readable error code
        details: Additional error details
        correlation_id: Request correlation ID

    Returns:
        API Gateway-compatible error response dict
    """
    error_body: dict[str, Any] = {
        "status": "error",
        "statusCode": status_code,
        "error": {
            "message": message,
        },
    }

    if error_code:
        error_body["error"]["code"] = error_code

    if details:
        error_body["error"]["details"] = details

    if correlation_id:
        error_body["correlationId"] = correlation_id

    response_headers = dict(CORS_HEADERS)
    if correlation_id:
        response_headers["X-Correlation-Id"] = correlation_id

    return {
        "statusCode": status_code,
        "headers": response_headers,
        "body": json.dumps(error_body, default=str),
    }


def options_response() -> dict[str, Any]:
    """Build a CORS preflight response."""
    return {
        "statusCode": 200,
        "headers": CORS_HEADERS,
        "body": "",
    }


# Common HTTP error helpers
def bad_request(message: str = "Bad request", **kwargs) -> dict[str, Any]:
    return error_response(400, message, error_code="BAD_REQUEST", **kwargs)


def not_found(message: str = "Resource not found", **kwargs) -> dict[str, Any]:
    return error_response(404, message, error_code="NOT_FOUND", **kwargs)


def conflict(message: str = "Resource conflict", **kwargs) -> dict[str, Any]:
    return error_response(409, message, error_code="CONFLICT", **kwargs)


def too_many_requests(message: str = "Rate limit exceeded", **kwargs) -> dict[str, Any]:
    return error_response(429, message, error_code="RATE_LIMIT_EXCEEDED", **kwargs)


def internal_error(message: str = "Internal server error", **kwargs) -> dict[str, Any]:
    return error_response(500, message, error_code="INTERNAL_ERROR", **kwargs)
