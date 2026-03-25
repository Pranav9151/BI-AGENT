"""
Smart BI Agent — Rate Limiter Middleware
Architecture v3.1 | Layer 3 (API Gateway) | Threat: T12

PURPOSE:
    Sliding-window rate limiting per IP address, stored in Redis DB 1
    (security database — noeviction, fail-closed).

DIFFERENTIATED LIMITS (v3.1 Layer 3):
    /api/v1/auth/*          →  10 req/min  (brute-force protection)
    /api/v1/query           →  10 req/min  (LLM cost protection)
    /api/v1/query/stream    →  10 req/min  (WebSocket LLM cost)
    /api/v1/schema*         →  60 req/min  (read-heavy, cache-backed)
    /api/v1/export*         →   5 req/min  (CPU/memory intensive)
    everything else         → 100 req/min  (default)

FAIL-CLOSED (T12):
    If Redis DB 1 is unavailable, ALL requests are rejected with 503.
    Security cannot degrade: if we can't check the rate limit, we
    cannot allow the request. This is the same principle as the token
    blacklist — Redis DB 1 MUST be up.

ALGORITHM — Sliding Window Counter:
    For each (ip, window) pair, we store a counter in Redis with a TTL
    equal to the window size. On each request:
        1. INCR counter key
        2. If count == 1: SET TTL (first request in window)
        3. If count > limit: reject 429

    This is a "fixed window with sliding expiry" — not a true sliding window
    but accurate enough for rate limiting and O(1) per request.

    Redis key format: ratelimit:{endpoint_class}:{ip}:{window_unix_minute}
    Example: ratelimit:auth:192.168.1.1:28512450

CLIENT IDENTIFICATION:
    Uses X-Forwarded-For (first IP) when behind Nginx, falls back to
    request.client.host. We trust X-Forwarded-For because Nginx is
    the only entry point and sets this correctly.

    In production, Nginx should be configured with:
        set_real_ip_from 0.0.0.0/0;
        real_ip_header X-Forwarded-For;
"""

from __future__ import annotations

import time
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings
from app.logging.structured import get_logger

log = get_logger(__name__)

# =============================================================================
# Endpoint class → rate limit mapping
# =============================================================================

# (path_prefix, limit_per_minute, endpoint_class_name)
_ENDPOINT_RULES: list[tuple[str, int, str]] = [
    ("/api/v1/auth",    10,  "auth"),
    ("/api/v1/query",   30,  "llm"),
    ("/api/v1/export",   5,  "export"),
    ("/api/v1/schema",  60,  "schema"),
]


def _classify_endpoint(path: str, settings) -> tuple[int, str]:
    """
    Return (limit_per_minute, class_name) for a given path.
    Checks prefix matches in priority order.
    """
    for prefix, limit, name in _ENDPOINT_RULES:
        if path.startswith(prefix):
            return limit, name
    return settings.RATE_LIMIT_DEFAULT_PER_MINUTE, "default"


def _get_client_ip(request: Request) -> str:
    """
    Extract the real client IP. Trusts X-Forwarded-For when set
    (Nginx strips/rewrites this so we can trust it in our setup).
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # Take the first IP (leftmost = originating client)
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """
    Per-IP sliding-window rate limiter backed by Redis DB 1.

    Fail-closed: returns 503 if Redis is unavailable.
    Order in middleware stack: Third (after RequestID, SecurityHeaders).
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # Skip rate limiting for health endpoint — monitoring must always work
        if request.url.path in ("/health", "/health/"):
            return await call_next(request)

        settings = get_settings()
        client_ip = _get_client_ip(request)
        limit, endpoint_class = _classify_endpoint(request.url.path, settings)

        # Sliding window: bucket by minute
        window = int(time.time() // 60)
        redis_key = f"ratelimit:{endpoint_class}:{client_ip}:{window}"

        try:
            from app.db.redis_manager import get_redis_security
            redis = get_redis_security()

            # Atomic increment
            count = await redis.incr(redis_key)

            # Set TTL on first request in this window
            if count == 1:
                await redis.expire(redis_key, 90)  # 90s TTL (1.5× window) for safety

            if count > limit:
                log.warning(
                    "rate_limit.exceeded",
                    ip=client_ip,
                    path=request.url.path,
                    endpoint_class=endpoint_class,
                    count=count,
                    limit=limit,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "RATE_LIMIT_EXCEEDED",
                            "message": "Too many requests. Please slow down and try again.",
                            "request_id": getattr(request.state, "request_id", None),
                        }
                    },
                    headers={
                        "Retry-After": "60",
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str((window + 1) * 60),
                    },
                )

        except RuntimeError:
            # Redis not initialized — this shouldn't happen post-startup
            # but guard against it during tests/startup race
            log.error(
                "rate_limiter.redis_not_initialized",
                path=request.url.path,
                ip=client_ip,
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "SERVICE_UNAVAILABLE",
                        "message": "Security service not ready. Redis DB1 may still be starting. Try again in a few seconds.",
                        "request_id": getattr(request.state, "request_id", None),
                    }
                },
            )
        except Exception as exc:
            # Redis unreachable → FAIL-CLOSED (T12)
            log.error(
                "rate_limiter.redis_unavailable",
                path=request.url.path,
                ip=client_ip,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "SERVICE_UNAVAILABLE",
                        "message": f"Security service unavailable (Redis DB1). Please check Docker services: docker compose ps. Error: {type(exc).__name__}",
                        "request_id": getattr(request.state, "request_id", None),
                    }
                },
            )

        # ── Rate limit passed — forward to downstream handler ────────────
        # This is OUTSIDE the Redis try/except so downstream errors
        # (TypeError, ValidationError, etc.) propagate correctly to
        # FastAPI's error handlers instead of being masked as Redis errors.
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        response.headers["X-RateLimit-Reset"] = str((window + 1) * 60)
        return response