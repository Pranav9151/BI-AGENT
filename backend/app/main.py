"""
Smart BI Agent — Application Factory
Architecture v3.1 | Layer 4 (Application) | All layers wired here

PURPOSE:
    Single entry point for the FastAPI application.
    Wires all infrastructure components in the correct startup order
    and tears them down in reverse on shutdown.

STARTUP ORDER (critical — do not reorder):
    1. configure_logging()     — must be first; all subsequent code logs
    2. init_key_manager()      — HKDF hierarchy; needed before any crypto
    3. init_db_engine()        — PostgreSQL pool; needed by AuditWriter
    4. init_redis()            — Redis pool; needed by rate limiter + auth
    5. AuditWriter.start()     — starts drain task; needs DB + Redis
    6. Middleware stack         — applied to all requests
    7. Exception handlers       — registered before routers
    8. Routers                  — mounted last

SHUTDOWN ORDER (reverse of startup):
    1. AuditWriter.stop()      — drain queue before closing DB
    2. close_redis()
    3. close_db_engine()

MIDDLEWARE STACK ORDER (outermost → innermost):
    1. CORSMiddleware           — must be outermost (Starlette requirement)
    2. RequestIDMiddleware      — generates request_id, binds structlog ctx
    3. SecurityHeadersMiddleware — injects HSTS, CSP, X-Frame-Options etc.
    4. RateLimiterMiddleware    — Redis DB1 sliding window (fail-closed)
    (JWT auth is a FastAPI dependency, not middleware — runs per-route)

SECURITY (T54):
    Swagger UI and ReDoc are disabled in production.
    The OpenAPI schema endpoint (/openapi.json) is also disabled.
    This prevents API enumeration attacks.

HEALTH ENDPOINTS:
    GET /health        — public, lightweight: {"status": "ok"} or "degraded"
    GET /health/deep   — admin-auth required, full component status
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import AppEnvironment, get_settings
from app.logging.structured import configure_logging, get_logger

# Logger for this module — configured before use in lifespan
log = get_logger(__name__)


# =============================================================================
# Lifespan — startup and shutdown
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Runs startup code before yield, shutdown code after yield.
    FastAPI's recommended pattern (replaces @app.on_event).
    """
    settings = get_settings()

    # ------------------------------------------------------------------
    # STARTUP
    # ------------------------------------------------------------------

    # 1. Logging — must be first
    configure_logging()
    log.info(
        "startup.begin",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        env=settings.APP_ENV.value,
    )

    # 2. Key Manager — HKDF hierarchy
    from app.security.key_manager import init_key_manager
    init_key_manager(settings.ENCRYPTION_MASTER_KEY)
    log.info("startup.key_manager.ready")

    # 3. Database engine
    from app.db.session import init_db_engine
    init_db_engine()
    log.info("startup.database.pool_ready")

    # 4. Redis (all three databases)
    from app.db.redis_manager import init_redis
    await init_redis()
    log.info("startup.redis.ready")

    # 5. Audit writer — async hash-chained drain task
    from app.db.session import _async_session_factory
    from app.logging.audit import AuditWriter
    audit = AuditWriter(_async_session_factory)
    await audit.start()
    app.state.audit = audit
    log.info("startup.audit_writer.ready")

    log.info("startup.complete", host=settings.APP_HOST, port=settings.APP_PORT)

    # ------------------------------------------------------------------
    # RUNNING — yield control to FastAPI
    # ------------------------------------------------------------------
    yield

    # ------------------------------------------------------------------
    # SHUTDOWN
    # ------------------------------------------------------------------
    log.info("shutdown.begin")

    # 1. Drain audit queue before closing DB
    try:
        await audit.stop()
        log.info("shutdown.audit_writer.stopped")
    except Exception as exc:
        log.error("shutdown.audit_writer.error", error=str(exc))

    # 2. Close Redis
    from app.db.redis_manager import close_redis
    try:
        await close_redis()
        log.info("shutdown.redis.closed")
    except Exception as exc:
        log.error("shutdown.redis.error", error=str(exc))

    # 3. Close DB pool
    from app.db.session import close_db_engine
    try:
        await close_db_engine()
        log.info("shutdown.database.closed")
    except Exception as exc:
        log.error("shutdown.database.error", error=str(exc))

    log.info("shutdown.complete")


# =============================================================================
# App factory
# =============================================================================

def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Called by uvicorn: uvicorn app.main:app
    """
    settings = get_settings()

    # T54: Disable Swagger/ReDoc/OpenAPI in production
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # Middleware stack — ORDER MATTERS
    # Starlette applies middleware from LAST added to FIRST added (LIFO).
    # So add in REVERSE order of execution.
    # Execution order: CORS → RequestID → SecurityHeaders → RateLimiter
    # Add order:       RateLimiter → SecurityHeaders → RequestID → CORS
    # ------------------------------------------------------------------

    # 5. Content-Type validation (innermost — closest to handlers)
    from app.middleware.content_type import ContentTypeValidationMiddleware
    app.add_middleware(ContentTypeValidationMiddleware)

    # 4b. Request logging (method, path, status, duration)
    from app.middleware.request_logging import RequestLoggingMiddleware
    app.add_middleware(RequestLoggingMiddleware)

    # 4a. Prometheus metrics collection
    from app.middleware.metrics import MetricsMiddleware
    app.add_middleware(MetricsMiddleware)

    # 4. Rate limiter
    from app.middleware.rate_limiter import RateLimiterMiddleware
    app.add_middleware(RateLimiterMiddleware)

    # 3. Security headers
    from app.middleware.security_headers import SecurityHeadersMiddleware
    app.add_middleware(SecurityHeadersMiddleware)

    # 2. Request ID (binds structlog context)
    from app.middleware.request_id import RequestIDMiddleware
    app.add_middleware(RequestIDMiddleware)

    # 1. CORS — outermost (handles preflight OPTIONS before anything else)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,   # Never ["*"] — validated in config
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
        max_age=600,
    )

    # ------------------------------------------------------------------
    # Exception handlers — registered before routers
    # ------------------------------------------------------------------
    from app.errors.handlers import register_exception_handlers
    register_exception_handlers(app)

    # ------------------------------------------------------------------
    # Routers — Phase 2 routes mounted here as they're built
    # ------------------------------------------------------------------
    _mount_routers(app)

    return app


def _mount_routers(app: FastAPI) -> None:
    """
    Mount API routers. Called by create_app().
    Routes are added here as each Phase 2 component is built.
    Currently only health endpoints are live.
    """
    from app.api.v1 import router as api_v1_router
    app.include_router(api_v1_router)


# =============================================================================
# Health endpoints — defined here directly (not in a router file yet)
# Phase 2 will move these to routes_health.py
# =============================================================================

# Forward reference: the app instance is created below
# Health routes are added after app creation using a simple include

def _register_health_routes(app: FastAPI) -> None:
    """Register health check endpoints directly on the app."""

    @app.get("/health", tags=["health"], include_in_schema=False)
    async def health_check():
        """
        Public health check — minimal response only.
        Returns "ok" or "degraded". Never exposes component details (T10).
        Called by Docker healthcheck and load balancers.
        """
        # Quick Redis ping to determine degraded state
        try:
            from app.db.redis_manager import get_redis_security
            await get_redis_security().ping()
            return {"status": "ok"}
        except Exception:
            # Security Redis down → degraded (fail-closed still active)
            return JSONResponse(
                status_code=503,
                content={"status": "degraded"},
            )

    @app.get("/health/deep", tags=["health"], include_in_schema=False)
    async def health_deep(request: Request):
        """
        Admin-only deep health check. Returns full component status.
        Requires valid admin JWT (enforced below via dependency check).
        """
        from app.dependencies import get_current_user, require_admin
        from app.db.redis_manager import check_redis_health

        # Manual auth check (can't use Depends here directly in this pattern)
        # Phase 2 routes_health.py will use proper Depends(require_admin)
        from fastapi.security import HTTPBearer
        from app.security.auth import verify_token

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"error": {"code": "UNAUTHORIZED"}})

        token = auth_header.split(" ", 1)[1]
        try:
            from app.db.redis_manager import get_redis_security
            payload = await verify_token(token, "access", get_redis_security())
            if payload.get("role") != "admin":
                return JSONResponse(status_code=403, content={"error": {"code": "ADMIN_REQUIRED"}})
        except Exception:
            return JSONResponse(status_code=401, content={"error": {"code": "UNAUTHORIZED"}})

        # Gather component health
        redis_status = await check_redis_health()

        db_ok = False
        try:
            from app.db.session import get_engine
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import AsyncSession
            from app.db.session import _async_session_factory
            async with _async_session_factory() as session:
                await session.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False

        # Ollama exposure check (T32) — warn if listening on 0.0.0.0
        ollama_exposed = False
        settings = get_settings()
        if settings.OLLAMA_ENABLED:
            try:
                import socket
                # Check if Ollama is listening externally
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(("0.0.0.0", 11434))
                sock.close()
                ollama_exposed = result == 0
            except Exception:
                pass

        all_ok = (
            redis_status.get("security_db1", False)
            and db_ok
            and not ollama_exposed
        )

        return {
            "status": "ok" if all_ok else "degraded",
            "components": {
                "database": "ok" if db_ok else "error",
                "redis_cache": "ok" if redis_status.get("cache_db0") else "error",
                "redis_security": "ok" if redis_status.get("security_db1") else "error",
                "redis_coordination": "ok" if redis_status.get("coordination_db2") else "error",
            },
            "warnings": {
                "ollama_exposed": ollama_exposed,
            },
        }

    @app.get("/metrics", tags=["observability"], include_in_schema=False)
    async def prometheus_metrics():
        """Prometheus metrics endpoint. No auth required (bind to internal network)."""
        from app.middleware.metrics import metrics_response
        return metrics_response()


# =============================================================================
# Application instance — imported by uvicorn
# =============================================================================

import os as _os

def _get_app() -> FastAPI:
    """
    Lazy app factory — only calls create_app() when env vars are present.
    Prevents import-time failures when running tools like mypy or alembic
    that import the module without a full environment loaded.
    """
    if not _os.environ.get("ENCRYPTION_MASTER_KEY"):
        # Return a minimal placeholder app for import-time tooling
        _placeholder = FastAPI(title="Smart BI Agent (not configured)")
        return _placeholder
    app = create_app()
    _register_health_routes(app)
    return app


app = _get_app()