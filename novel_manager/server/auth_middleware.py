from __future__ import annotations

from typing import Any, Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .services.pairing_service import is_localhost_request, verify_device_token


# APIs that require authorization for non-localhost requests
PROTECTED_APIS = [
    "/api/sync/",
    "/api/books/",
    "/api/tasks/",
    "/api/incoming/",
    "/api/operations/",
    "/api/health/",
    "/api/pairing/devices",
]

# APIs that are always public (no authorization needed)
PUBLIC_APIS = [
    "/api/health",  # Basic health check
    "/api/pairing/create",
    "/api/pairing/confirm",
    "/api/repo/status",
]


def is_protected_api(path: str) -> bool:
    """Check if an API path requires authorization."""
    # Check if it's a public API
    for public in PUBLIC_APIS:
        if path == public or path.startswith(public + "/"):
            return False

    # Check if it's a protected API
    for protected in PROTECTED_APIS:
        if path.startswith(protected):
            return True

    return False


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware to authorize device access for non-localhost requests."""

    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        path = request.url.path

        # Skip auth for non-API requests (static files, etc.)
        if not path.startswith("/api/"):
            return await call_next(request)

        # Skip auth for public APIs
        if not is_protected_api(path):
            return await call_next(request)

        # Get client host
        client_host = request.client.host if request.client else None

        # Allow localhost requests without authorization
        if is_localhost_request(client_host):
            return await call_next(request)

        # For non-localhost, require authorization
        device_id = request.headers.get("X-Device-ID", "")
        device_token = request.headers.get("X-Device-Token", "")

        # Also support Authorization header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            device_token = auth_header[7:]

        if not device_id or not device_token:
            return JSONResponse(
                status_code=401,
                content={
                    "ok": False,
                    "error_code": "unauthorized_device",
                    "error": "该设备尚未配对，请先在电脑端完成配对。",
                },
            )

        # Verify token
        repo_path = request.app.state.repo_path
        result = verify_device_token(repo_path, device_id, device_token)

        if not result.get("ok"):
            error_code = result.get("error_code", "unauthorized_device")
            error_msg = result.get("error", "该设备尚未配对，请先在电脑端完成配对。")
            return JSONResponse(
                status_code=401,
                content={
                    "ok": False,
                    "error_code": error_code,
                    "error": error_msg,
                },
            )

        return await call_next(request)
