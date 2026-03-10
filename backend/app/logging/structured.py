"""
Smart BI Agent — Structured Logger
Architecture v3.1 | Layer 9 (Observability) | Threats: T20, T33, T34

PURPOSE:
    Centralized structlog configuration with two security controls:

    1. REDACTION (T33 — Credential Leak in Logs):
       Fields named password, api_key, token, secret, credential, authorization,
       cookie, private_key are replaced with "[REDACTED]" at the processor level.
       This runs on EVERY log call — there is no way to accidentally bypass it.

    2. LOG INJECTION PREVENTION (T34 — Log Forging):
       User-controlled strings (questions, usernames, error messages) can contain
       newlines and ANSI/control characters that fragment log lines or poison
       aggregators (e.g., inject fake log entries by embedding \\n{...json...}).
       All string values are escaped: \\n → \\\\n, \\r → \\\\r, \\t → \\\\t,
       and control chars 0x00-0x1F/0x7F stripped.

DESIGN:
    - JSON renderer in production (machine-readable for SIEM shipping)
    - Console renderer in development (human-readable)
    - Request-scoped context bound via structlog.contextvars (async-safe)
    - request_id, user_id, trace_id automatically included in every log call
      within a request without passing them explicitly

USAGE:
    from app.logging.structured import get_logger, bind_request_context, clear_request_context

    # In middleware — bind once per request:
    bind_request_context(request_id="uuid", user_id="uuid", ip="1.2.3.4")

    # In any module:
    log = get_logger(__name__)
    log.info("query.executed", duration_ms=42, row_count=100)
    log.warning("rate_limit.exceeded", endpoint="/api/v1/query")
    log.error("llm.provider_failed", provider="openai", error=str(e))
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog
from structlog.contextvars import (
    bind_contextvars,
    clear_contextvars,
    merge_contextvars,
)
from structlog.types import EventDict, WrappedLogger

from app.config import get_settings

# =============================================================================
# Redaction — T33: Credential Leak Prevention
# =============================================================================

# These field names (case-insensitive, partial match) are always redacted.
# Add to this list; never remove from it.
_REDACTED_FIELDS: frozenset[str] = frozenset({
    "password",
    "passwd",
    "api_key",
    "apikey",
    "token",
    "secret",
    "credential",
    "authorization",
    "cookie",
    "private_key",
    "privatekey",
    "access_key",
    "accesskey",
    "client_secret",
    "refresh_token",
    "totp_secret",
    "encryption_key",
    "master_key",
    "hkdf",
    "fernet",
})

_REDACT_PATTERN: re.Pattern = re.compile(
    r"(" + "|".join(re.escape(f) for f in _REDACTED_FIELDS) + r")",
    re.IGNORECASE,
)


def _should_redact(key: str) -> bool:
    """Return True if the key name suggests it holds a sensitive value."""
    key_lower = key.lower()
    return any(f in key_lower for f in _REDACTED_FIELDS)


def redact_sensitive_fields(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """
    Structlog processor: replace sensitive field values with '[REDACTED]'.

    Walks the top-level event dict only (not nested dicts, by design — nested
    structures that reach logs should be flattened at the call site so this
    processor can protect them).
    """
    for key in list(event_dict.keys()):
        if key == "event":
            # Don't redact the event name itself, but scan it for leaked creds
            if isinstance(event_dict[key], str) and _REDACT_PATTERN.search(event_dict[key]):
                # Only redact if the event string itself looks like a secret dump
                # e.g. "password=abc123" in event string
                event_dict[key] = re.sub(
                    r'(' + '|'.join(re.escape(f) for f in _REDACTED_FIELDS) + r')(=|:)\S+',
                    r'\1\2[REDACTED]',
                    event_dict[key],
                    flags=re.IGNORECASE,
                )
        elif _should_redact(key):
            event_dict[key] = "[REDACTED]"
    return event_dict


# =============================================================================
# Log Injection Prevention — T34: Log Forging
# =============================================================================

# Control characters 0x00–0x1F except tab (0x09), LF (0x0A), CR (0x0D)
# which we handle explicitly. Also strip DEL (0x7F).
_CTRL_CHARS: re.Pattern = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _escape_string(value: str) -> str:
    """
    Escape a string value to prevent log injection.

    Newlines/tabs → escaped literals so a single log entry stays on one line
    and cannot forge additional JSON log entries.
    Control chars → stripped entirely.
    """
    value = value.replace("\\", "\\\\")  # escape backslashes first
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "\\r")
    value = value.replace("\t", "\\t")
    value = _CTRL_CHARS.sub("", value)   # strip remaining control chars
    return value


def prevent_log_injection(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """
    Structlog processor: escape newlines and control characters in all string
    values. Prevents multi-line log injection and ANSI escape code injection.

    Applied to ALL string values in the event dict, including the event name.
    """
    for key, value in event_dict.items():
        if isinstance(value, str):
            event_dict[key] = _escape_string(value)
        elif isinstance(value, (list, tuple)):
            event_dict[key] = [
                _escape_string(v) if isinstance(v, str) else v for v in value
            ]
    return event_dict


# =============================================================================
# Processor Chain
# =============================================================================

def _build_processors(json_output: bool) -> list:
    """Build the structlog processor chain for the given output mode."""
    shared: list = [
        merge_contextvars,                        # inject request_id, user_id etc.
        structlog.stdlib.add_log_level,           # add "level" key
        structlog.stdlib.add_logger_name,         # add "logger" key
        structlog.processors.TimeStamper(fmt="iso", utc=True),  # UTC ISO timestamp
        redact_sensitive_fields,                  # T33 — must run BEFORE injection check
        prevent_log_injection,                    # T34 — must run AFTER redaction
        structlog.processors.StackInfoRenderer(), # stack_info if requested
        structlog.processors.format_exc_info,     # exc_info → traceback string
    ]

    if json_output:
        shared.append(structlog.processors.JSONRenderer())
    else:
        shared.append(
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            )
        )

    return shared


# =============================================================================
# Initialisation — called once from app factory (main.py lifespan)
# =============================================================================

def configure_logging() -> None:
    """
    Configure structlog and stdlib logging.

    Must be called ONCE at application startup before any loggers are used.
    Idempotent — safe to call multiple times (e.g., in tests).
    """
    settings = get_settings()

    json_output = settings.APP_ENV.value != "development"

    # ------------------------------------------------------------------
    # stdlib root logger — captures logs from third-party libraries
    # ------------------------------------------------------------------
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    # Avoid duplicate handlers on re-configuration (e.g., test teardown)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Suppress noisy libraries in production
    if json_output:
        for noisy in ("uvicorn.access", "httpx", "httpcore"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    # ------------------------------------------------------------------
    # structlog global configuration
    # ------------------------------------------------------------------
    structlog.configure(
        processors=_build_processors(json_output=json_output),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


# =============================================================================
# Public API
# =============================================================================

def get_logger(name: str) -> structlog.BoundLogger:
    """
    Return a structlog BoundLogger for the given module name.

    Usage:
        log = get_logger(__name__)
        log.info("event.name", key="value")
    """
    return structlog.get_logger(name)


def bind_request_context(
    request_id: str,
    user_id: str | None = None,
    ip_address: str | None = None,
    method: str | None = None,
    path: str | None = None,
) -> None:
    """
    Bind request-scoped fields to the structlog context vars.

    Call this in the Request ID middleware at the START of each request.
    All subsequent log calls in the same async task will include these fields
    automatically without any explicit passing.

    Fields are stored in contextvars — async-safe, task-local.
    """
    ctx: dict[str, Any] = {"request_id": request_id}
    if user_id:
        ctx["user_id"] = user_id
    if ip_address:
        ctx["ip"] = ip_address
    if method:
        ctx["http_method"] = method
    if path:
        ctx["path"] = path
    bind_contextvars(**ctx)


def bind_user_context(user_id: str, role: str | None = None) -> None:
    """
    Bind user identity after JWT verification.
    Call this from the JWT auth dependency once the user is known.
    """
    ctx: dict[str, Any] = {"user_id": user_id}
    if role:
        ctx["user_role"] = role
    bind_contextvars(**ctx)


def clear_request_context() -> None:
    """
    Clear all request-scoped context vars.
    Call this in middleware AFTER the response is sent (finally block).
    """
    clear_contextvars()
