"""
Smart BI Agent — Request ID Middleware
Architecture v3.1 | Layer 3 (API Gateway) | Cross-cutting

PURPOSE:
    Injects a UUID v4 request_id into every request BEFORE any handler runs.

    Two uses:
    1. Correlation: every log call in a request includes request_id automatically
       (via structlog contextvars — bound here, cleared in finally block).
    2. Client error correlation: request_id is returned in all error responses
       so users can quote it when reporting issues to support (T10 safe — no
       internal details, just an opaque ID).

    The request_id is:
        - Generated fresh for every request (never reused)
        - Stored in request.state.request_id for handlers and dependencies
        - Injected into the X-Request-ID response header
        - Bound to structlog contextvars for the duration of the request

DESIGN:
    Uses Starlette's BaseHTTPMiddleware. The overhead is one uuid4() call
    (~1µs) and two contextvars operations per request — negligible.

    If the client sends an X-Request-ID header, we IGNORE it and generate
    our own. Trusting client-supplied IDs would allow log injection / correlation
    spoofing.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.logging.structured import bind_request_context, clear_request_context

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Generates a unique request ID for every incoming request.

    Order in middleware stack: FIRST — must run before all other middleware
    so that all subsequent log calls have the request_id bound.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # Generate a new UUID — never trust X-Request-ID from client
        request_id = str(uuid.uuid4())

        # Attach to request state so handlers/dependencies can read it
        request.state.request_id = request_id

        # Bind to structlog contextvars — all log calls within this request
        # will include request_id, method, and path automatically
        bind_request_context(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            # user_id is bound later by the JWT dependency once token is verified
        )

        try:
            response = await call_next(request)
        finally:
            # Always clear contextvars — prevents leakage to the next request
            # on the same asyncio Task (connection pool reuse)
            clear_request_context()

        # Inject into response header for client-side correlation
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
