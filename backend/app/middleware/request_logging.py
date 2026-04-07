"""
Smart BI Agent — Request Logging Middleware
Architecture v3.1 | Layer 3 (Observability)

PURPOSE:
    Logs every HTTP request with method, path, status, and duration.
    Essential for production debugging, latency tracking, and SLA monitoring.

LOG FORMAT:
    Each request emits a single structured log line:
        http.request method=GET path=/api/v1/schema/... status=200 duration_ms=42 ip=...

    Sensitive paths (/auth/login, /auth/register) do NOT log request bodies.
    Health check endpoints are logged at DEBUG level to reduce noise.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.logging.structured import get_logger

log = get_logger(__name__)

# Paths logged at DEBUG (high-frequency, low-value)
_QUIET_PATHS = frozenset({"/health", "/health/deep"})


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log method, path, status code, and duration for every request."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        start = time.monotonic()
        path = request.url.path
        method = request.method

        # Extract client IP (trust X-Forwarded-For from Nginx)
        xff = request.headers.get("x-forwarded-for")
        client_ip = xff.split(",")[0].strip() if xff else (
            request.client.host if request.client else "unknown"
        )

        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            status = response.status_code if response else 500
            request_id = getattr(request.state, "request_id", None)

            log_kwargs = {
                "method": method,
                "path": path,
                "status": status,
                "duration_ms": duration_ms,
                "ip": client_ip,
            }
            if request_id:
                log_kwargs["request_id"] = request_id

            if path in _QUIET_PATHS:
                log.debug("http.request", **log_kwargs)
            elif status >= 500:
                log.error("http.request", **log_kwargs)
            elif status >= 400:
                log.warning("http.request", **log_kwargs)
            else:
                log.info("http.request", **log_kwargs)
