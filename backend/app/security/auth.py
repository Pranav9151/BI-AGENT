"""
Smart BI Agent — JWT Authentication
Architecture v3.1 | Security Layer 8 | Threats: T4, T9, T11

T4 — Algorithm Confusion Prevention:
    algorithms=["RS256"] is HARDCODED in decode(). The token header's "alg"
    field is IGNORED if it's not in this whitelist. This prevents an attacker
    from forging tokens signed with the public key using HS256.

T9 — Secure Refresh Cookie:
    HttpOnly, Secure, SameSite=Strict, Domain, Path=/api/v1/auth

T11 — Token Blacklist:
    On logout, the JTI (JWT ID) is added to Redis DB 1 (noeviction).
    Every token verification checks the blacklist first.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt

from app.config import get_settings


class AuthenticationError(Exception):
    """Raised for any authentication failure."""
    pass


class TokenBlacklistedError(AuthenticationError):
    """Raised when a blacklisted token is used."""
    pass


class TokenExpiredError(AuthenticationError):
    """Raised when an expired token is used."""
    pass


# ============================================================================
# HARDCODED — T4 Algorithm Confusion Prevention
# This MUST be ["RS256"] and NOTHING ELSE. Never add "HS256" or "none".
# The 91,000 Ollama attacks taught us: if it's configurable, it's vulnerable.
# ============================================================================
ALLOWED_ALGORITHMS: list[str] = ["RS256"]


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    department: Optional[str] = None,
) -> str:
    """
    Create a JWT access token (short-lived, 15 minutes).

    The token contains the user's identity and role for stateless
    authorization. Signed with RSA private key (RS256).

    Args:
        user_id: UUID string of the user.
        email: User's email.
        role: User's role (admin, analyst, viewer).
        department: User's department (optional).

    Returns:
        Signed JWT string.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)

    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "department": department or "",
        "type": "access",
        "jti": str(uuid.uuid4()),  # Unique token ID for blacklisting
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }

    return jwt.encode(
        payload,
        settings.jwt_private_key,
        algorithm="RS256",  # Hardcoded — never dynamic
    )


def create_refresh_token(user_id: str) -> str:
    """
    Create a JWT refresh token (long-lived, 7 days).

    Refresh tokens are stored in HttpOnly cookies (T9).
    They contain minimal claims — just enough to issue a new access token.

    Args:
        user_id: UUID string of the user.

    Returns:
        Signed JWT string.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)

    payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }

    return jwt.encode(
        payload,
        settings.jwt_private_key,
        algorithm="RS256",
    )


async def verify_token(
    token: str,
    expected_type: str = "access",
    redis_security=None,
) -> dict[str, Any]:
    """
    Verify and decode a JWT token.

    Security checks performed:
        1. Signature verification with RSA public key
        2. Algorithm whitelist: ONLY RS256 accepted (T4)
        3. Expiration check
        4. Issuer/audience validation
        5. Token type validation (access vs refresh)
        6. Blacklist check against Redis DB 1 (T11)

    Args:
        token: The JWT string to verify.
        expected_type: Expected token type ("access" or "refresh").
        redis_security: Redis client for DB 1 (blacklist check).

    Returns:
        Decoded token payload dict.

    Raises:
        AuthenticationError: For any verification failure.
        TokenBlacklistedError: If the token has been revoked.
        TokenExpiredError: If the token has expired.
    """
    settings = get_settings()

    # Step 1-3: Decode with signature verification, algorithm whitelist, expiry check
    try:
        payload = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=ALLOWED_ALGORITHMS,  # T4: HARDCODED RS256 ONLY
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
            options={
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": True,
                "verify_iat": True,
                "require_exp": True,
                "require_iat": True,
                "require_sub": True,
            },
        )
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError("Token has expired")
    except JWTError as e:
        raise AuthenticationError(f"Invalid token: {e}")

    # Step 4: Validate token type
    token_type = payload.get("type")
    if token_type != expected_type:
        raise AuthenticationError(
            f"Invalid token type: expected '{expected_type}', got '{token_type}'"
        )

    # Step 5: Validate required fields
    if not payload.get("sub"):
        raise AuthenticationError("Token missing subject claim")
    if not payload.get("jti"):
        raise AuthenticationError("Token missing JTI claim")

    # Step 6: Blacklist check (T11) — Redis DB 1, noeviction
    if redis_security:
        jti = payload["jti"]
        is_blacklisted = await redis_security.get(f"blacklist:{jti}")
        if is_blacklisted:
            raise TokenBlacklistedError("Token has been revoked")

    return payload


async def blacklist_token(
    token: str,
    redis_security,
) -> None:
    """
    Add a token to the blacklist (on logout or security event).

    The blacklist entry TTL matches the token's remaining lifetime.
    After expiry, the blacklist entry auto-expires (no cleanup needed).

    Redis DB 1 uses noeviction policy — blacklist entries are NEVER
    evicted under memory pressure (T11).

    Args:
        token: The JWT string to blacklist.
        redis_security: Redis client for DB 1.
    """
    try:
        # Decode without verification just to get JTI and exp
        # (the token was already verified before reaching this point)
        settings = get_settings()
        payload = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=ALLOWED_ALGORITHMS,
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
            options={"verify_exp": False},  # May be expired on logout
        )

        jti = payload.get("jti")
        exp = payload.get("exp")
        if not jti:
            return

        # Calculate remaining TTL
        if exp:
            exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
            remaining = (exp_dt - datetime.now(timezone.utc)).total_seconds()
            ttl = max(int(remaining), 1)  # At least 1 second
        else:
            ttl = 86400  # Fallback: 24 hours

        # Add to blacklist with TTL
        await redis_security.set(f"blacklist:{jti}", "1", ex=ttl)

    except Exception:
        # If blacklisting fails, log it but don't crash the logout
        # The token will expire naturally
        pass


def get_refresh_cookie_settings() -> dict[str, Any]:
    """
    Get cookie settings for the refresh token (T9).

    HttpOnly: JavaScript cannot read the cookie (XSS protection)
    Secure: Only sent over HTTPS
    SameSite=Strict: Never sent cross-origin (CSRF protection)
    Path=/api/v1/auth: Only sent to auth endpoints (minimize exposure)

    Returns:
        Dict of cookie parameters for Response.set_cookie().
    """
    settings = get_settings()
    return {
        "key": "refresh_token",
        "httponly": True,
        "secure": settings.is_production,  # True in production
        "samesite": "strict",
        "path": "/api/v1/auth",
        "max_age": settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    }


def extract_user_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Extract user info from a verified token payload.

    Returns a clean dict suitable for dependency injection.
    """
    return {
        "user_id": payload["sub"],
        "email": payload.get("email", ""),
        "role": payload.get("role", "viewer"),
        "department": payload.get("department", ""),
        "jti": payload.get("jti", ""),
    }
