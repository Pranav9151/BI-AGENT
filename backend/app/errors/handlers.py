"""
Smart BI Agent — FastAPI Exception Handlers
Architecture v3.1 | Cross-cutting | Threats: T10, T34

PURPOSE:
    Register exception handlers on the FastAPI app so that every error —
    whether raised intentionally (SmartBIException) or unexpectedly (500) —
    returns a consistent, structured JSON response that NEVER leaks internal
    details to the client.

T10 — INFORMATION DISCLOSURE PREVENTION:
    Client response contains ONLY:
        {
            "error": {
                "code": "INVALID_CREDENTIALS",   ← machine-readable
                "message": "Invalid credentials." ← client-safe human text
                "request_id": "uuid"              ← for user to quote in support
            }
        }

    Internal details (stack trace, SQL, model names, env values, file paths)
    are written to structured log with the same request_id, correlated server-side.

T34 — LOG INJECTION:
    exc.detail and str(exc) pass through the structured logger which applies
    the prevent_log_injection processor. No raw user input is interpolated
    into log messages directly.

HANDLERS REGISTERED:
    1. SmartBIException → exc.status_code + exc.error_code + exc.message
    2. RequestValidationError (Pydantic v2) → 422 with sanitized field errors
    3. HTTPException → passthrough with consistent envelope
    4. Exception (catch-all) → 500, logs with exc_info=True

USAGE (in main.py):
    from app.errors.handlers import register_exception_handlers
    register_exception_handlers(app)
"""

from __future__ import annotations

import traceback
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.errors.exceptions import (
    AccountLockedError,
    RateLimitError,
    SmartBIException,
)
from app.logging.structured import get_logger

log = get_logger(__name__)


# =============================================================================
# Response builder
# =============================================================================

def _error_response(
    status_code: int,
    error_code: str,
    message: str,
    request_id: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> JSONResponse:
    """
    Build the standard error JSON envelope.

    The envelope is intentionally minimal:
        {
          "error": {
            "code": "...",
            "message": "...",
            "request_id": "..."   (only if available)
          }
        }

    No stack traces, no SQL, no internal field names — T10.
    """
    body: dict[str, Any] = {
        "error": {
            "code": error_code,
            "message": message,
        }
    }
    if request_id:
        body["error"]["request_id"] = request_id

    return JSONResponse(
        status_code=status_code,
        content=body,
        headers=extra_headers,
    )


def _get_request_id(request: Request) -> str | None:
    """Extract the request_id injected by the Request ID middleware."""
    return getattr(request.state, "request_id", None)


# =============================================================================
# Handler: SmartBIException (all our typed exceptions)
# =============================================================================

async def smartbi_exception_handler(
    request: Request,
    exc: SmartBIException,
) -> JSONResponse:
    """
    Handle any intentional application exception.

    Logs at appropriate level:
    - 5xx → error (with detail for investigation)
    - 429/423 → warning (expected flow)
    - 4xx → info (expected client errors)
    """
    request_id = _get_request_id(request)

    log_ctx: dict[str, Any] = {
        "error_code": exc.error_code,
        "status_code": exc.status_code,
        "request_id": request_id,
        "path": str(request.url.path),
        **exc.extra,
    }
    if exc.detail:
        log_ctx["detail"] = exc.detail

    if exc.status_code >= 500:
        log.error("exception.smartbi.5xx", exc_info=exc, **log_ctx)
    elif exc.status_code == 429 or exc.status_code == 423:
        log.warning("exception.smartbi.rate_or_lock", **log_ctx)
    else:
        log.info("exception.smartbi.4xx", **log_ctx)

    # Build headers for specific exception types
    extra_headers: dict[str, str] = {}

    if isinstance(exc, RateLimitError) and exc.retry_after is not None:
        extra_headers["Retry-After"] = str(exc.retry_after)

    if isinstance(exc, AccountLockedError):
        # 423 with Retry-After 30 minutes — informs legitimate clients
        extra_headers["Retry-After"] = "1800"

    return _error_response(
        status_code=exc.status_code,
        error_code=exc.error_code,
        message=exc.message,
        request_id=request_id,
        extra_headers=extra_headers or None,
    )


# =============================================================================
# Handler: Pydantic RequestValidationError (422)
# =============================================================================

async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """
    Handle Pydantic v2 validation errors from request body/query/path params.

    We SANITIZE the error details:
    - Field names and types: safe to return (help client fix the request)
    - Field VALUES: never returned — could contain PII or injection strings (T10)

    Output format:
        {
          "error": {
            "code": "VALIDATION_ERROR",
            "message": "Invalid request data.",
            "request_id": "...",
            "fields": [
              {"field": "email", "issue": "value is not a valid email address"}
            ]
          }
        }
    """
    request_id = _get_request_id(request)

    # Sanitize: keep field location + type message, drop the actual value
    sanitized_errors: list[dict[str, str]] = []
    for error in exc.errors():
        loc = " → ".join(str(part) for part in error.get("loc", []))
        msg = error.get("msg", "invalid value")
        # Strip any value echoing from Pydantic's message
        # e.g. "value is not a valid integer" is fine
        # "Input should be 'foo'" might echo user input — truncate to 100 chars
        msg_safe = msg[:100] if msg else "invalid value"
        sanitized_errors.append({"field": loc, "issue": msg_safe})

    log.info(
        "exception.validation",
        request_id=request_id,
        path=str(request.url.path),
        error_count=len(sanitized_errors),
        fields=[e["field"] for e in sanitized_errors],
    )

    body: dict[str, Any] = {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Invalid request data.",
            "fields": sanitized_errors,
        }
    }
    if request_id:
        body["error"]["request_id"] = request_id

    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=body)


# =============================================================================
# Handler: HTTPException (Starlette / FastAPI built-in)
# =============================================================================

async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """
    Wrap Starlette's HTTPException in our standard envelope.

    These are raised by FastAPI internals (e.g., 405 Method Not Allowed,
    405 from router, 404 from path mismatch). We wrap them for consistent
    client response format.

    The detail field from HTTPException is generally framework-generated
    (safe strings like "Not Found") — we include it as the message.
    """
    request_id = _get_request_id(request)

    # Map status codes to machine-readable codes
    _code_map: dict[int, str] = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        408: "REQUEST_TIMEOUT",
        409: "CONFLICT",
        413: "PAYLOAD_TOO_LARGE",
        415: "UNSUPPORTED_MEDIA_TYPE",
        422: "UNPROCESSABLE_ENTITY",
        429: "RATE_LIMIT_EXCEEDED",
        500: "INTERNAL_ERROR",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
    }
    error_code = _code_map.get(exc.status_code, "HTTP_ERROR")

    # Detail can be a string or dict — normalize to string, truncate
    detail_str = str(exc.detail) if exc.detail else "An error occurred."
    message = detail_str[:200]  # Truncate just in case

    log.info(
        "exception.http",
        request_id=request_id,
        status_code=exc.status_code,
        error_code=error_code,
        path=str(request.url.path),
    )

    return _error_response(
        status_code=exc.status_code,
        error_code=error_code,
        message=message,
        request_id=request_id,
    )


# =============================================================================
# Handler: Catch-all (unexpected 500s)
# =============================================================================

async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """
    Catch-all for any unhandled exception — returns 500 with NO internal details.

    T10: The client receives only a generic message and request_id.
         The full traceback is in the structured log, keyed by request_id.

    We log at CRITICAL because any unhandled exception is a code defect
    that should be investigated immediately.
    """
    request_id = _get_request_id(request)

    # Capture the full traceback for internal logging
    tb = traceback.format_exc()

    log.critical(
        "exception.unhandled",
        request_id=request_id,
        path=str(request.url.path),
        method=request.method,
        exc_type=type(exc).__name__,
        traceback=tb,
    )

    return _error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code="INTERNAL_ERROR",
        message="An unexpected error occurred. Please contact your administrator.",
        request_id=request_id,
    )


# =============================================================================
# Registration
# =============================================================================

def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all exception handlers on the FastAPI application.

    Call this in main.py AFTER creating the FastAPI instance but BEFORE
    including routers, so handlers are in place before any routes execute.

    Handler resolution order (FastAPI uses most-specific first):
    1. SmartBIException → our typed hierarchy
    2. RequestValidationError → Pydantic validation errors
    3. StarletteHTTPException → built-in HTTP errors
    4. Exception → catch-all for unexpected errors
    """
    app.add_exception_handler(SmartBIException, smartbi_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]
