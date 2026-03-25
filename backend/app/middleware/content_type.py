"""
Smart BI Agent — Content-Type Validation Middleware
Architecture v3.1 | Phase 7 Session 9

PURPOSE:
    Enforce Content-Type: application/json on all POST/PATCH/PUT requests.
    Prevents content-type confusion attacks where an attacker sends
    form-encoded or multipart data that gets parsed differently.

SKIP:
    - GET, DELETE, OPTIONS, HEAD (no body)
    - /health endpoint (monitoring)
    - Requests with no body (Content-Length: 0)
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.logging.structured import get_logger

log = get_logger(__name__)

_METHODS_WITH_BODY = {"POST", "PUT", "PATCH"}
_SKIP_PATHS = {"/health", "/health/"}


class ContentTypeValidationMiddleware(BaseHTTPMiddleware):
    """
    Reject POST/PATCH/PUT requests without Content-Type: application/json.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.method not in _METHODS_WITH_BODY:
            return await call_next(request)

        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        # Allow requests with no body
        content_length = request.headers.get("content-length", "0")
        if content_length == "0":
            return await call_next(request)

        content_type = request.headers.get("content-type", "")

        if not content_type.startswith("application/json"):
            log.warning(
                "content_type.rejected",
                method=request.method,
                path=request.url.path,
                content_type=content_type,
            )
            return JSONResponse(
                status_code=415,
                content={
                    "error": {
                        "code": "UNSUPPORTED_MEDIA_TYPE",
                        "message": "Content-Type must be application/json.",
                        "request_id": getattr(request.state, "request_id", None),
                    }
                },
            )

        return await call_next(request)