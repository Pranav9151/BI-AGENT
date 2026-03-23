"""
Smart BI Agent — Auth Routes
Architecture v3.1 | Layer 4 (Application) | Threats: T4, T8, T9, T10, T11, T12, T15

ENDPOINTS:
    POST /login            — password verify → lockout check → TOTP gate → tokens
    POST /totp/verify      — complete admin login with TOTP code
    POST /refresh          — rotate access token via HttpOnly refresh cookie
    POST /logout           — blacklist both tokens, clear cookie + admin session
    GET  /me               — current user from DB (always fresh)
    POST /totp/setup       — generate TOTP secret + QR code (pre_totp token)
    POST /totp/confirm     — activate TOTP after setup verification (pre_totp token)

LOGIN FLOW (T10 — timing-safe, enumeration-resistant):
    1. Lookup user by email (always run bcrypt, even if not found)
    2. Check Redis DB1 lockout → 423 if locked
    3. If user found but DB-locked (Redis miss after restart) → 423
    4. Verify bcrypt password
    5. Failure → increment DB counter + progressive sleep + Redis lockout at threshold
    6. Success → clear counters, update last_login_at
    7. Admin + no TOTP secret → issue pre_totp + totp_setup_required=True
    8. Admin + TOTP secret present → issue pre_totp + totp_required=True
    9. Non-admin → issue full access + refresh cookie

TOKEN TYPES:
    "access"    — 15min, full scope, accepted by get_current_user()
    "pre_totp"  — 5min, admin only, accepted ONLY by get_pre_totp_user()
    "refresh"   — 7 days, HttpOnly cookie, rotated on each use
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUser,
    get_audit_writer,
    get_current_user,
    get_db,
    get_key_manager,
    get_pre_totp_user,
    get_redis_security,
)
from app.errors.exceptions import (
    AccountLockedError,
    AdminRequiredError,
    AuthenticationError,
    InvalidCredentialsError,
    MFAInvalidError,
    MFARequiredError,
    ResourceNotFoundError,
)
from app.logging.structured import get_logger
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    RefreshResponse,
    TOTPConfirmRequest,
    TOTPConfirmResponse,
    TOTPSetupResponse,
    TOTPVerifyRequest,
    TOTPVerifyResponse,
)
from app.security.auth import (
    blacklist_token,
    create_access_token,
    create_pre_totp_token,
    create_refresh_token,
    get_refresh_cookie_settings,
    verify_token,
)
from app.security.lockout import AccountLockedError as LockoutAccountLockedError
from app.security.lockout import LockoutManager
from app.security.password import verify_password
from app.security.totp import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    setup_totp,
    verify_totp_code,
)

log = get_logger(__name__)

router = APIRouter()

# =============================================================================
# Constants
# =============================================================================

# Pre-computed bcrypt cost-12 hash of a sentinel value.
# Ensures bcrypt ALWAYS runs on login — even when the email is not found —
# making login timing indistinguishable between "wrong password" and
# "user not found" (T10 — user enumeration prevention).
# This hash was generated offline and never matches any real password.
_DUMMY_HASH: str = (
    "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMqJqhNA9nFkC8UjxNGCpIQ8Hy"
)


# =============================================================================
# Private helpers
# =============================================================================

async def _get_user_by_email(email: str, db: AsyncSession) -> Optional[User]:
    """Look up a user by email. Returns None if not found."""
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def _get_user_by_id(user_id: str, db: AsyncSession) -> Optional[User]:
    """Look up a user by UUID. Returns None if not found."""
    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    return result.scalar_one_or_none()


def _client_ip(request: Request) -> str:
    """Extract client IP, preferring X-Forwarded-For (set by Nginx)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# =============================================================================
# POST /login
# =============================================================================

@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis_security=Depends(get_redis_security),
    audit=Depends(get_audit_writer),
) -> LoginResponse:
    """
    Authenticate a user with email + password.

    Security properties:
        - bcrypt always runs (T10 — timing-safe, no user enumeration)
        - Lockout checked before password (T8)
        - Progressive delay on failure (T8 — makes brute force costly)
        - Vague error message: "Invalid credentials." for ALL failures (T10)
        - Admin gate: password-only login issues pre_totp token, never full access
        - Audit log written for both success and failure
    """
    email = str(body.email).lower().strip()
    ip = _client_ip(request)
    request_id = getattr(request.state, "request_id", None)

    # ------------------------------------------------------------------
    # Step 1: Instantiate lockout manager
    # ------------------------------------------------------------------
    lockout = LockoutManager(redis_security=redis_security)

    # ------------------------------------------------------------------
    # Step 2: Redis lockout check (fast path — before any DB or bcrypt)
    # ------------------------------------------------------------------
    try:
        await lockout.check_lockout(email)
    except LockoutAccountLockedError:
        log.warning("auth.login.locked_redis", email=email, ip=ip)
        if audit:
            await audit.log(
                execution_status="login_locked",
                question=f"login:{email}",
                ip_address=ip,
                request_id=request_id,
            )
        raise AccountLockedError()

    # ------------------------------------------------------------------
    # Step 3: Look up user (result hidden from attacker by always running bcrypt)
    # ------------------------------------------------------------------
    user = await _get_user_by_email(email, db)

    # ------------------------------------------------------------------
    # Step 4: DB lockout check (catches Redis miss after restart)
    # ------------------------------------------------------------------
    if user and LockoutManager.is_locked(user.locked_until):
        log.warning("auth.login.locked_db", user_id=str(user.id), ip=ip)
        # Re-sync Redis with DB lock so fast path works next time
        remaining = (
            user.locked_until - datetime.now(timezone.utc)
        ).total_seconds()
        if remaining > 0:
            try:
                await redis_security.set(
                    f"lockout:{email}", "locked", ex=int(remaining)
                )
            except Exception:
                pass  # Best-effort resync; DB check already caught it
        if audit:
            await audit.log(
                execution_status="login_locked",
                question=f"login:{email}",
                user_id=user.id,
                ip_address=ip,
                request_id=request_id,
            )
        raise AccountLockedError()

    # ------------------------------------------------------------------
    # Step 5: bcrypt verification (ALWAYS runs — T10 timing safety)
    # ------------------------------------------------------------------
    hash_to_check = user.hashed_password if user else _DUMMY_HASH
    password_valid = verify_password(body.password, hash_to_check)

    # ------------------------------------------------------------------
    # Step 6: Handle authentication failure
    # ------------------------------------------------------------------
    if not password_valid:
        log.info("auth.login.failed", email=email, ip=ip, user_found=(user is not None))

        if user:
            # Increment DB counter and apply progressive delay via LockoutManager
            new_count = await lockout.record_failed_attempt(
                email=email,
                current_attempts=user.failed_login_attempts,
            )
            # Persist new attempt count and potential lockout timestamp
            user.failed_login_attempts = new_count
            if new_count >= lockout.threshold:
                user.locked_until = lockout.compute_locked_until()
                log.warning(
                    "auth.login.account_locked",
                    user_id=str(user.id),
                    attempts=new_count,
                    ip=ip,
                )
            await db.commit()
        else:
            # No user in DB — still apply a base progressive delay
            # so timing is similar to the user-found failure path.
            # Use attempt count 0 → 2s delay (factor × 1).
            await lockout.record_failed_attempt(email=email, current_attempts=0)

        if audit:
            await audit.log(
                execution_status="login_failed",
                question=f"login:{email}",
                user_id=user.id if user else None,
                ip_address=ip,
                request_id=request_id,
                error_message="invalid_credentials",
            )

        # T10: identical vague message regardless of failure reason
        raise InvalidCredentialsError()

    # ------------------------------------------------------------------
    # Step 7: Successful authentication — clear lockout state
    # ------------------------------------------------------------------
    log.info("auth.login.success", user_id=str(user.id), role=user.role, ip=ip)

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await lockout.record_successful_login(email)

    # ------------------------------------------------------------------
    # Step 8: Check user is active and approved
    # ------------------------------------------------------------------
    if not user.is_active:
        # Intentionally same message as invalid credentials (T10)
        if audit:
            await audit.log(
                execution_status="login_failed",
                question=f"login:{email}",
                user_id=user.id,
                ip_address=ip,
                request_id=request_id,
                error_message="account_inactive",
            )
        raise InvalidCredentialsError()

    if not user.is_approved:
        if audit:
            await audit.log(
                execution_status="login_failed",
                question=f"login:{email}",
                user_id=user.id,
                ip_address=ip,
                request_id=request_id,
                error_message="account_not_approved",
            )
        raise InvalidCredentialsError()

    # ------------------------------------------------------------------
    # Step 9: Admin TOTP gate
    # ------------------------------------------------------------------
    if user.role == "admin":
        pre_totp_token = create_pre_totp_token(
            user_id=str(user.id),
            email=user.email,
        )

        # No TOTP secret stored yet → must complete setup first
        if not user.totp_secret_enc:
            log.info("auth.login.totp_setup_required", user_id=str(user.id))
            if audit:
                await audit.log(
                    execution_status="login_totp_setup_required",
                    question=f"login:{email}",
                    user_id=user.id,
                    ip_address=ip,
                    request_id=request_id,
                )
            return LoginResponse(
                access_token=pre_totp_token,
                totp_required=True,
                totp_setup_required=True,
            )

        # TOTP secret exists → must verify code
        log.info("auth.login.totp_required", user_id=str(user.id))
        if audit:
            await audit.log(
                execution_status="login_totp_pending",
                question=f"login:{email}",
                user_id=user.id,
                ip_address=ip,
                request_id=request_id,
            )
        return LoginResponse(
            access_token=pre_totp_token,
            totp_required=True,
            totp_setup_required=False,
        )

    # ------------------------------------------------------------------
    # Step 10: Non-admin — issue full access + refresh tokens
    # ------------------------------------------------------------------
    access_token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        role=user.role,
        department=user.department,
    )
    refresh_token = create_refresh_token(user_id=str(user.id))

    if audit:
        await audit.log(
            execution_status="login_success",
            question=f"login:{email}",
            user_id=user.id,
            ip_address=ip,
            request_id=request_id,
        )

    # Set HttpOnly refresh cookie (T9)
    cookie_settings = get_refresh_cookie_settings()
    response.set_cookie(value=refresh_token, **cookie_settings)

    return LoginResponse(access_token=access_token)


# =============================================================================
# POST /totp/verify
# =============================================================================

@router.post("/totp/verify", response_model=TOTPVerifyResponse)
async def totp_verify(
    request: Request,
    body: TOTPVerifyRequest,
    response: Response,
    pre_totp_user: CurrentUser = Depends(get_pre_totp_user),
    db: AsyncSession = Depends(get_db),
    key_manager=Depends(get_key_manager),
    audit=Depends(get_audit_writer),
) -> TOTPVerifyResponse:
    """
    Complete admin login by verifying a TOTP code.

    Requires a pre_totp JWT (issued by /login after password verification).
    On success: blacklists the pre_totp token (one-time use), issues full
    access token + refresh cookie.

    Raises:
        MFAInvalidError (401) if code is wrong or TOTP not configured.
    """
    ip = _client_ip(request)
    request_id = getattr(request.state, "request_id", None)
    user_id = pre_totp_user["user_id"]

    user = await _get_user_by_id(user_id, db)
    if not user:
        log.error("auth.totp_verify.user_not_found", user_id=user_id)
        raise AuthenticationError(message="Authentication failed.")

    if not user.totp_secret_enc:
        log.warning("auth.totp_verify.no_secret", user_id=user_id)
        raise MFAInvalidError()

    # Decrypt stored secret and verify code
    try:
        secret = decrypt_totp_secret(user.totp_secret_enc, key_manager)
    except Exception as exc:
        log.error("auth.totp_verify.decrypt_failed", user_id=user_id, error=str(exc))
        raise AuthenticationError(message="Authentication failed.")

    if not verify_totp_code(secret, body.code):
        log.info("auth.totp_verify.invalid_code", user_id=user_id, ip=ip)
        if audit:
            await audit.log(
                execution_status="totp_verify_failed",
                question=f"totp_verify:{user.email}",
                user_id=user.id,
                ip_address=ip,
                request_id=request_id,
                error_message="invalid_totp_code",
            )
        raise MFAInvalidError()

    # Ensure totp_enabled is True in DB (idempotent)
    if not user.totp_enabled:
        user.totp_enabled = True
        await db.commit()

    # Issue full access token
    access_token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        role=user.role,
        department=user.department,
    )
    refresh_token = create_refresh_token(user_id=str(user.id))

    log.info("auth.totp_verify.success", user_id=user_id, ip=ip)
    if audit:
        await audit.log(
            execution_status="login_success_totp",
            question=f"totp_verify:{user.email}",
            user_id=user.id,
            ip_address=ip,
            request_id=request_id,
        )

    cookie_settings = get_refresh_cookie_settings()
    response.set_cookie(value=refresh_token, **cookie_settings)

    return TOTPVerifyResponse(access_token=access_token)


# =============================================================================
# POST /refresh
# =============================================================================

@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis_security=Depends(get_redis_security),
) -> RefreshResponse:
    """
    Rotate the access token using the HttpOnly refresh cookie.

    Security:
        - Refresh token verified (RS256 + blacklist check)
        - OLD refresh token is immediately blacklisted (T11 — one-time use)
        - DB check: user still active + approved (catches 7-day-old stale JWTs)
        - New refresh token issued and set in cookie

    Raises:
        AuthenticationError (401) if no cookie, invalid token, or user deactivated.
    """
    ip = _client_ip(request)

    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise AuthenticationError(
            message="Authentication required.",
            detail="Missing refresh_token cookie",
        )

    # Verify the refresh token
    try:
        payload = await verify_token(
            token=refresh_token,
            expected_type="refresh",
            redis_security=redis_security,
        )
    except Exception as exc:
        log.info("auth.refresh.invalid_token", error=str(exc), ip=ip)
        raise AuthenticationError(
            message="Your session has expired. Please log in again.",
            detail=f"Refresh token verify failed: {exc}",
        )

    user_id = payload["sub"]

    # DB check: user still active and approved (7-day window for stale tokens)
    user = await _get_user_by_id(user_id, db)
    if not user:
        log.warning("auth.refresh.user_not_found", user_id=user_id)
        raise AuthenticationError(message="Authentication failed.")
    if not user.is_active:
        log.info("auth.refresh.inactive_user", user_id=user_id)
        raise AuthenticationError(message="Your account has been deactivated.")
    if not user.is_approved:
        log.info("auth.refresh.unapproved_user", user_id=user_id)
        raise AuthenticationError(
            message="Your account is pending administrator approval."
        )

    # Blacklist the OLD refresh token immediately (one-time use, T11)
    await blacklist_token(refresh_token, redis_security)

    # Issue fresh tokens
    new_access_token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        role=user.role,
        department=user.department,
    )
    new_refresh_token = create_refresh_token(user_id=str(user.id))

    log.info("auth.refresh.success", user_id=user_id, ip=ip)

    cookie_settings = get_refresh_cookie_settings()
    response.set_cookie(value=new_refresh_token, **cookie_settings)

    return RefreshResponse(access_token=new_access_token)


# =============================================================================
# POST /logout
# =============================================================================

@router.post("/logout", status_code=200)
async def logout(
    request: Request,
    response: Response,
    current_user: CurrentUser = Depends(get_current_user),
    redis_security=Depends(get_redis_security),
) -> None:
    """
    Revoke both tokens and clear the session.

    Actions:
        1. Blacklist the access token JTI in Redis DB1
        2. Blacklist the refresh token (if cookie present)
        3. Delete the refresh cookie
        4. Clear admin session idle-timeout key (T15)

    Returns 204 No Content. Errors are swallowed — logout always succeeds
    from the client's perspective (cookie is deleted regardless).
    """
    ip = _client_ip(request)
    user_id = current_user["user_id"]

    # Blacklist the access token (extract raw token from Authorization header)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        access_token = auth_header[len("Bearer "):].strip()
        try:
            await blacklist_token(access_token, redis_security)
        except Exception as exc:
            log.warning("auth.logout.access_blacklist_failed", user_id=user_id, error=str(exc))

    # Blacklist the refresh token if present in cookie
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        try:
            await blacklist_token(refresh_token, redis_security)
        except Exception as exc:
            log.warning("auth.logout.refresh_blacklist_failed", user_id=user_id, error=str(exc))

    # Clear admin session idle-timeout key (T15)
    if current_user["role"] == "admin":
        try:
            await redis_security.delete(f"admin_session:{user_id}")
        except Exception as exc:
            log.warning("auth.logout.admin_session_clear_failed", user_id=user_id, error=str(exc))

    # Delete the refresh cookie (path must match set path for browser to honour it)
    cookie_settings = get_refresh_cookie_settings()
    response.delete_cookie(
        key=cookie_settings["key"],
        path=cookie_settings["path"],
        httponly=cookie_settings["httponly"],
        secure=cookie_settings["secure"],
        samesite=cookie_settings["samesite"],
    )

    log.info("auth.logout.success", user_id=user_id, ip=ip)


# =============================================================================
# GET /me
# =============================================================================

@router.get("/me", response_model=MeResponse)
async def me(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """
    Return the current authenticated user's profile.

    Always queries the DB (not just JWT) so callers see up-to-date fields
    (totp_enabled, is_active, department changes, etc.).
    """
    user = await _get_user_by_id(current_user["user_id"], db)
    if not user:
        log.error("auth.me.user_not_found", user_id=current_user["user_id"])
        raise ResourceNotFoundError(
            message="User not found.",
            detail=f"User {current_user['user_id']} in JWT but not in DB",
        )

    return MeResponse(
        user_id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role,
        department=user.department,
        totp_enabled=user.totp_enabled,
        is_active=user.is_active,
        is_approved=user.is_approved,
        last_login_at=user.last_login_at,
    )


# =============================================================================
# POST /totp/setup
# =============================================================================

@router.post("/totp/setup", response_model=TOTPSetupResponse)
async def totp_setup(
    request: Request,
    pre_totp_user: CurrentUser = Depends(get_pre_totp_user),
    db: AsyncSession = Depends(get_db),
    key_manager=Depends(get_key_manager),
) -> TOTPSetupResponse:
    """
    Generate a new TOTP secret and QR code for an admin account.

    Requires a pre_totp JWT (issued at login when admin has no TOTP secret).
    The secret is immediately encrypted and stored in DB, but totp_enabled
    remains False until /totp/confirm is called with a valid code.

    The QR code and secret are returned ONCE and never stored server-side.
    If called again (e.g., lost phone), a new secret is generated and
    overwrites the unconfirmed one.
    """
    user_id = pre_totp_user["user_id"]
    user = await _get_user_by_id(user_id, db)
    if not user:
        log.error("auth.totp_setup.user_not_found", user_id=user_id)
        raise AuthenticationError(message="Authentication failed.")

    # Generate fresh secret + QR code
    setup_result = setup_totp(email=user.email)

    # Encrypt and store secret (not yet active — totp_enabled stays False)
    encrypted_secret = encrypt_totp_secret(setup_result.secret, key_manager)
    user.totp_secret_enc = encrypted_secret
    user.totp_enabled = False  # Must be confirmed via /totp/confirm
    await db.commit()

    log.info("auth.totp_setup.secret_stored", user_id=user_id)

    qr_code_data_uri = (
        setup_result.qr_code_base64
        if setup_result.qr_code_base64.startswith("data:")
        else f"data:image/png;base64,{setup_result.qr_code_base64}"
    )

    return TOTPSetupResponse(
        qr_code=qr_code_data_uri,
        secret=setup_result.secret,
        uri=setup_result.uri,
    )


# =============================================================================
# POST /totp/confirm
# =============================================================================

@router.post("/totp/confirm", response_model=TOTPConfirmResponse)
async def totp_confirm(
    request: Request,
    body: TOTPConfirmRequest,
    pre_totp_user: CurrentUser = Depends(get_pre_totp_user),
    db: AsyncSession = Depends(get_db),
    key_manager=Depends(get_key_manager),
    audit=Depends(get_audit_writer),
) -> TOTPConfirmResponse:
    """
    Verify a TOTP code to confirm setup and activate TOTP on the account.

    Requires a pre_totp JWT (issued at login after password verification).
    A valid code proves the admin has successfully scanned the QR code and
    their authenticator app is synchronized.

    After this call, totp_enabled=True. Every future login will require
    a TOTP code.

    Raises:
        MFAInvalidError (401) if the code is wrong or no secret is stored.
    """
    ip = _client_ip(request)
    request_id = getattr(request.state, "request_id", None)
    user_id = pre_totp_user["user_id"]

    user = await _get_user_by_id(user_id, db)
    if not user:
        log.error("auth.totp_confirm.user_not_found", user_id=user_id)
        raise AuthenticationError(message="Authentication failed.")

    if not user.totp_secret_enc:
        log.warning("auth.totp_confirm.no_secret", user_id=user_id)
        raise MFAInvalidError(
            detail=f"User {user_id} has no TOTP secret; call /totp/setup first"
        )

    # Decrypt and verify
    try:
        secret = decrypt_totp_secret(user.totp_secret_enc, key_manager)
    except Exception as exc:
        log.error("auth.totp_confirm.decrypt_failed", user_id=user_id, error=str(exc))
        raise AuthenticationError(message="Authentication failed.")

    if not verify_totp_code(secret, body.code):
        log.info("auth.totp_confirm.invalid_code", user_id=user_id, ip=ip)
        if audit:
            await audit.log(
                execution_status="totp_confirm_failed",
                question=f"totp_confirm:{user.email}",
                user_id=user.id,
                ip_address=ip,
                request_id=request_id,
                error_message="invalid_totp_code",
            )
        raise MFAInvalidError()

    # Activate TOTP on the account
    user.totp_enabled = True
    await db.commit()

    log.info("auth.totp_confirm.activated", user_id=user_id)
    if audit:
        await audit.log(
            execution_status="totp_activated",
            question=f"totp_confirm:{user.email}",
            user_id=user.id,
            ip_address=ip,
            request_id=request_id,
        )

    return TOTPConfirmResponse()