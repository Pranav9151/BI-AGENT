"""
Smart BI Agent — FastAPI Dependency Injection
Architecture v3.1 | Layer 4 (Application) | Cross-cutting

PURPOSE:
    Central dependency injection layer. Every route handler pulls its
    dependencies from here via FastAPI's Depends() system.

    Centralizing DI here means:
    - Security logic lives in ONE place (not scattered across routes)
    - Every authentication check is identical (no ad-hoc JWT parsing)
    - Changing auth behaviour updates ALL routes simultaneously

DEPENDENCIES PROVIDED:

    get_db()                  → AsyncSession       (PostgreSQL session)
    get_redis_cache()         → aioredis.Redis      (DB 0 — cache)
    get_redis_security()      → aioredis.Redis      (DB 1 — security, fail-closed)
    get_redis_coordination()  → aioredis.Redis      (DB 2 — coordination)
    get_key_manager()         → KeyManager          (HKDF hierarchy singleton)
    get_audit_writer()        → AuditWriter         (async hash-chained audit)

    get_current_user()        → CurrentUser         (JWT-verified user dict)
    require_admin()           → CurrentUser         (must be role=admin)
    require_active_user()     → CurrentUser         (must be active + approved)

SECURITY FLOW (get_current_user):
    1. Extract Bearer token from Authorization header
    2. Verify RS256 signature with hardcoded algorithm whitelist (T4)
    3. Check token expiry
    4. Check token blacklist via Redis DB 1 (T11) — FAIL-CLOSED
    5. Return clean user dict (no DB call on every request — JWT is stateless)

    Redis DB 1 unavailability → 503 (fail-closed, T12).
    Any token verification failure → 401 (intentionally vague message, T10).

ADMIN SESSIONS (T15 — 15-minute idle timeout):
    Admin access tokens expire after 15 minutes regardless of JWT expiry.
    The admin session idle-timeout key in Redis DB 1 is refreshed on every
    successful admin request. If the key expires, the next request gets 401.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.errors.exceptions import (
    AdminRequiredError,
    AuthenticationError,
    InsufficientPermissionsError,
    TokenBlacklistedError,
    TokenExpiredError,
    TokenInvalidError,
)
from app.logging.structured import bind_user_context, get_logger
from app.security.auth import verify_token

log = get_logger(__name__)

# Bearer token extractor — auto_error=False so we return our own error shape
_bearer_scheme = HTTPBearer(auto_error=False)


# =============================================================================
# Type alias for the current user dict injected into every route
# =============================================================================

CurrentUser = dict[str, Any]
"""
Shape:
    {
        "user_id": str (UUID),
        "email": str,
        "role": str  ("admin" | "analyst" | "viewer"),
        "department": str,
        "jti": str,
    }
"""


# =============================================================================
# Infrastructure dependencies
# =============================================================================

async def get_db():
    """
    Yield an async PostgreSQL session.
    Re-exports from db.session for a single import point in route files.
    """
    from app.db.session import get_db as _get_db
    async for session in _get_db():
        yield session


def get_redis_cache():
    """Redis DB 0 — cache. Degradable: fall back to DB on miss."""
    from app.db.redis_manager import get_redis_cache as _get
    return _get()


def get_redis_security():
    """Redis DB 1 — security. Fail-closed: 503 if unavailable."""
    from app.db.redis_manager import get_redis_security as _get
    return _get()


def get_redis_coordination():
    """Redis DB 2 — coordination. Partially degradable."""
    from app.db.redis_manager import get_redis_coordination as _get
    return _get()


def get_key_manager():
    """HKDF key manager singleton. Initialized in lifespan startup."""
    from app.security.key_manager import get_key_manager as _get
    return _get()


def get_audit_writer(request: Request):
    """
    AuditWriter singleton stored on app.state.
    Initialized in lifespan startup, gracefully absent if startup failed.
    """
    return getattr(request.app.state, "audit", None)


# =============================================================================
# JWT Authentication
# =============================================================================

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> CurrentUser:
    """
    Verify JWT token and return the current user dict.

    Security steps:
        1. Require Authorization: Bearer <token> header
        2. Verify RS256 signature (T4 — algorithm whitelist)
        3. Check expiry, issuer, audience
        4. Check blacklist in Redis DB 1 (T11)
        5. Bind user_id to structlog context for this request

    Raises:
        AuthenticationError (401) on any failure — intentionally vague (T10)
    """
    if credentials is None:
        raise AuthenticationError(
            message="Authentication required.",
            detail="Missing Authorization: Bearer header",
        )

    token = credentials.credentials

    try:
        from app.db.redis_manager import get_redis_security
        redis_security = get_redis_security()
    except RuntimeError:
        # Redis not initialized — fail-closed (T12)
        log.error("auth.redis_unavailable", path=request.url.path)
        raise AuthenticationError(
            message="Authentication service temporarily unavailable.",
            detail="Redis DB1 not initialized during auth check",
        )
    except Exception as exc:
        log.error("auth.redis_error", error=str(exc), path=request.url.path)
        raise AuthenticationError(
            message="Authentication service temporarily unavailable.",
            detail=f"Redis error during auth: {exc}",
        )

    try:
        payload = await verify_token(
            token=token,
            expected_type="access",
            redis_security=redis_security,
        )
    except TokenExpiredError:
        raise TokenExpiredError(message="Your session has expired. Please log in again.")
    except TokenBlacklistedError:
        raise TokenBlacklistedError(message="This session has been revoked. Please log in again.")
    except Exception as exc:
        # Any other Jose/JWT error → generic 401 (T10)
        log.info(
            "auth.token_invalid",
            error=str(exc),
            path=request.url.path,
        )
        raise TokenInvalidError(message="Invalid authentication token.")

    user: CurrentUser = {
        "user_id": payload["sub"],
        "email": payload.get("email", ""),
        "role": payload.get("role", "viewer"),
        "department": payload.get("department", ""),
        "jti": payload.get("jti", ""),
    }

    # Bind user identity to structlog for this request
    bind_user_context(user_id=user["user_id"], role=user["role"])

    # Admin session idle-timeout enforcement (T15 — 15min idle)
    if user["role"] == "admin":
        await _refresh_admin_session(user["user_id"], redis_security)

    return user


async def _refresh_admin_session(user_id: str, redis_security) -> None:
    """
    Refresh the admin session idle-timeout key in Redis DB 1.

    The key expires after ADMIN_SESSION_TIMEOUT_MINUTES of inactivity.
    If it doesn't exist (first request or timed out), we create it fresh.
    On session logout, the key is deleted alongside token blacklisting.
    """
    settings = get_settings()
    session_key = f"admin_session:{user_id}"
    ttl_seconds = settings.ADMIN_SESSION_TIMEOUT_MINUTES * 60

    try:
        # GETEX: get current value and reset TTL atomically
        await redis_security.set(session_key, "1", ex=ttl_seconds, keepttl=False)
    except Exception as exc:
        # Don't crash the request — log and continue
        log.warning("auth.admin_session_refresh_failed", user_id=user_id, error=str(exc))


# =============================================================================
# Authorization dependencies (compose on top of get_current_user)
# =============================================================================

def get_pre_totp_redis():
    """
    Dedicated Redis DB1 dependency for pre-TOTP endpoints only.

    Isolated from the shared get_redis_security() so tests can override
    this specific function via app.dependency_overrides without interfering
    with other endpoints. Returns None on RuntimeError so get_pre_totp_user
    can raise a clean 401 rather than an unhandled 500.
    """
    try:
        from app.db.redis_manager import get_redis_security as _get
        return _get()
    except RuntimeError:
        return None
    except Exception:
        return None


async def get_pre_totp_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    redis_security=Depends(get_pre_totp_redis),
) -> CurrentUser:
    """
    Verify a pre_totp JWT and return the partial admin user dict.

    Used EXCLUSIVELY on:
        POST /auth/totp/verify   — complete MFA verification
        POST /auth/totp/setup    — initiate TOTP setup
        POST /auth/totp/confirm  — confirm TOTP activation

    A pre_totp token is issued by /auth/login after successful password
    verification for admin accounts. It is rejected by get_current_user()
    because expected_type="access" != "pre_totp".

    Security:
        - Same blacklist check as get_current_user() (T11)
        - Redis DB1 unavailability → 503, fail-closed (T12)
        - Role claim validated — must be "admin"

    Raises:
        AuthenticationError (401) on any failure.
    """
    if credentials is None:
        raise AuthenticationError(
            message="Authentication required.",
            detail="Missing Authorization: Bearer header on pre_totp endpoint",
        )

    token = credentials.credentials

    if redis_security is None:
        log.error("auth.pre_totp.redis_unavailable", path=request.url.path)
        raise AuthenticationError(
            message="Authentication service temporarily unavailable.",
            detail="Redis DB1 not initialized during pre_totp check",
        )

    try:
        payload = await verify_token(
            token=token,
            expected_type="pre_totp",
            redis_security=redis_security,
        )
    except TokenExpiredError:
        raise TokenExpiredError(
            message="Your MFA session has expired. Please log in again."
        )
    except TokenBlacklistedError:
        raise TokenBlacklistedError(
            message="This session has been revoked. Please log in again."
        )
    except Exception as exc:
        log.info("auth.pre_totp.token_invalid", error=str(exc), path=request.url.path)
        raise TokenInvalidError(message="Invalid authentication token.")

    # Extra guard: pre_totp tokens are only issued to admins
    if payload.get("role") != "admin":
        log.warning(
            "auth.pre_totp.non_admin_claim",
            role=payload.get("role"),
            user_id=payload.get("sub"),
        )
        raise AdminRequiredError()

    user: CurrentUser = {
        "user_id": payload["sub"],
        "email": payload.get("email", ""),
        "role": "admin",
        "department": "",
        "jti": payload.get("jti", ""),
    }

    bind_user_context(user_id=user["user_id"], role="admin")
    return user


async def require_admin(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """
    Require the current user to have the 'admin' role.

    Used on all admin-only endpoints:
        /api/v1/users, /api/v1/connections, /api/v1/llm-providers,
        /api/v1/notification-platforms, /api/v1/audit, /health/deep

    Raises:
        AdminRequiredError (403)
    """
    if current_user["role"] != "admin":
        log.info(
            "auth.admin_required.denied",
            user_id=current_user["user_id"],
            role=current_user["role"],
        )
        raise AdminRequiredError()
    return current_user


async def require_active_user(
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
) -> CurrentUser:
    """
    Require the user to be active AND approved (not just authenticated).

    Checks the DB to ensure:
    - user.is_active is True (not deactivated by admin)
    - user.is_approved is True (closed registration — admin must approve)

    This is a heavier dependency (one DB query) — use it only on sensitive
    endpoints where stale JWT data is a concern.

    Raises:
        AuthenticationError (401) if user no longer active/approved
    """
    from sqlalchemy import select
    from app.models.user import User

    result = await db.execute(
        select(User.is_active, User.is_approved)
        .where(User.id == current_user["user_id"])
    )
    row = result.first()

    if row is None:
        raise AuthenticationError(
            message="Authentication failed.",
            detail=f"User {current_user['user_id']} not found in DB during active check",
        )

    is_active, is_approved = row
    if not is_active:
        raise AuthenticationError(
            message="Your account has been deactivated.",
            detail=f"User {current_user['user_id']} is_active=False",
        )
    if not is_approved:
        raise AuthenticationError(
            message="Your account is pending administrator approval.",
            detail=f"User {current_user['user_id']} is_approved=False",
        )

    return current_user


async def require_analyst_or_above(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """
    Require role to be 'analyst' or 'admin'.
    Viewers cannot execute queries — they can only view saved results.

    Raises:
        InsufficientPermissionsError (403)
    """
    if current_user["role"] not in ("admin", "analyst"):
        raise InsufficientPermissionsError(
            message="Query execution requires analyst or admin role.",
            detail=f"User {current_user['user_id']} has role={current_user['role']}",
        )
    return current_user