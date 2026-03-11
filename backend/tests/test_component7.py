"""
Smart BI Agent — Component 7 Tests
Auth routes: /login, /totp/verify, /refresh, /logout, /me, /totp/setup, /totp/confirm

Tests use:
  - FastAPI TestClient (sync) with dependency overrides — no real DB or Redis
  - patch() for bcrypt (avoid 250ms cost per test) and asyncio.sleep
  - Mock User objects matching the SQLAlchemy model shape
  - Mock JWT keys generated once per session for real token round-trips

Test coverage:
  - Login: success (all 3 paths), wrong password, user not found, locked (Redis),
           locked (DB), inactive, unapproved, missing fields
  - TOTP verify: success, wrong code, wrong token type, missing token, no secret
  - Refresh: success, no cookie, invalid token, deactivated user
  - Logout: success (clears cookie), no auth, admin session cleared
  - Me: success, user not found
  - TOTP setup: success, non-admin rejected
  - TOTP confirm: success, wrong code, no secret stored
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors.handlers import register_exception_handlers


# =============================================================================
# Test Fixtures & Helpers
# (RSA key generation is handled in conftest.py pytest_configure — runs before
#  any import, cross-platform via tempfile.gettempdir())
# =============================================================================

_TEST_USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_TEST_ADMIN_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _make_user(**kwargs) -> MagicMock:
    """Build a mock User with sensible defaults (non-admin, active, approved)."""
    user = MagicMock()
    user.id = uuid.UUID(_TEST_USER_ID)
    user.email = "user@example.com"
    user.name = "Test User"
    user.role = "viewer"
    user.department = "Engineering"
    user.is_active = True
    user.is_approved = True
    user.totp_enabled = False
    user.totp_secret_enc = None
    user.hashed_password = "hashed_pw_placeholder"
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = None
    for key, value in kwargs.items():
        setattr(user, key, value)
    return user


def _make_admin(**kwargs) -> MagicMock:
    """Build a mock admin User."""
    defaults = dict(
        id=uuid.UUID(_TEST_ADMIN_ID),
        email="admin@example.com",
        name="Admin User",
        role="admin",
        totp_enabled=True,
        totp_secret_enc="v1:encrypted_secret",
    )
    defaults.update(kwargs)
    return _make_user(**defaults)


def _make_db_session(user: Optional[MagicMock] = None) -> AsyncMock:
    """Mock AsyncSession that returns `user` from execute()."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


def _make_redis() -> AsyncMock:
    """Mock Redis client (DB1 — security)."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)   # not locked by default
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.ttl = AsyncMock(return_value=-1)
    return redis


def _build_test_app() -> FastAPI:
    """Create a minimal FastAPI app with the auth router and exception handlers."""
    from app.api.v1.routes_auth import router as auth_router

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
    register_exception_handlers(app)
    return app


# =============================================================================
# JWT helpers for tests that need real tokens
# =============================================================================

def _issue_real_tokens(user: MagicMock) -> dict[str, str]:
    """
    Issue real JWTs (RS256) using the configured test keys.
    Used for tests that verify token content or blacklisting logic.
    """
    from app.security.auth import (
        create_access_token,
        create_pre_totp_token,
        create_refresh_token,
    )

    access = create_access_token(
        user_id=str(user.id),
        email=user.email,
        role=user.role,
        department=str(user.department) if user.department else None,
    )
    refresh = create_refresh_token(user_id=str(user.id))
    pre_totp = create_pre_totp_token(user_id=str(user.id), email=user.email)
    return {"access": access, "refresh": refresh, "pre_totp": pre_totp}


# =============================================================================
# Login Endpoint Tests
# =============================================================================

class TestLoginEndpoint:
    """POST /api/v1/auth/login"""

    def _make_client(self, user: Optional[MagicMock] = None, redis=None) -> TestClient:
        app = _build_test_app()
        db_session = _make_db_session(user)
        mock_redis = redis or _make_redis()
        mock_audit = AsyncMock()
        mock_audit.log = AsyncMock()

        async def override_db():
            yield db_session

        app.dependency_overrides.update({
            __import__("app.dependencies", fromlist=["get_db"]).get_db: override_db,
            __import__("app.dependencies", fromlist=["get_redis_security"]).get_redis_security: lambda: mock_redis,
            __import__("app.dependencies", fromlist=["get_audit_writer"]).get_audit_writer: lambda: mock_audit,
        })
        return TestClient(app, raise_server_exceptions=False)

    # ------------------------------------------------------------------
    # Happy path: non-admin full access
    # ------------------------------------------------------------------

    @patch("app.security.lockout.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.api.v1.routes_auth.verify_password", return_value=True)
    def test_login_non_admin_success(self, mock_verify, mock_sleep):
        """Non-admin login returns access token + sets refresh cookie."""
        user = _make_user(role="analyst")
        client = self._make_client(user=user)

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "correctpassword"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["totp_required"] is False
        assert body["totp_setup_required"] is False
        assert "refresh_token" in resp.cookies

    @patch("app.security.lockout.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.api.v1.routes_auth.verify_password", return_value=True)
    def test_login_admin_totp_enabled_returns_pre_totp(self, mock_verify, mock_sleep):
        """Admin with TOTP enabled gets pre_totp token and totp_required=True."""
        admin = _make_admin(totp_enabled=True, totp_secret_enc="v1:encrypted")
        client = self._make_client(user=admin)

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "adminpassword"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["totp_required"] is True
        assert body["totp_setup_required"] is False
        # No refresh cookie — admin must complete TOTP first
        assert "refresh_token" not in resp.cookies

    @patch("app.security.lockout.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.api.v1.routes_auth.verify_password", return_value=True)
    def test_login_admin_no_totp_secret_requires_setup(self, mock_verify, mock_sleep):
        """Admin with no TOTP secret gets pre_totp token and totp_setup_required=True."""
        admin = _make_admin(totp_enabled=False, totp_secret_enc=None)
        client = self._make_client(user=admin)

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "adminpassword"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["totp_required"] is True
        assert body["totp_setup_required"] is True
        assert "access_token" in body
        assert "refresh_token" not in resp.cookies

    @patch("app.security.lockout.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.api.v1.routes_auth.verify_password", return_value=True)
    def test_login_admin_totp_secret_but_not_enabled_requires_verify(self, mock_verify, mock_sleep):
        """Admin with secret stored but totp_enabled=False → verify path (not setup)."""
        admin = _make_admin(totp_enabled=False, totp_secret_enc="v1:someencrypted")
        client = self._make_client(user=admin)

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "adminpassword"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["totp_required"] is True
        assert body["totp_setup_required"] is False  # Has secret → verify, not setup

    # ------------------------------------------------------------------
    # Failure paths — all return 401 with identical vague message (T10)
    # ------------------------------------------------------------------

    @patch("app.security.lockout.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.api.v1.routes_auth.verify_password", return_value=False)
    def test_login_wrong_password_returns_401(self, mock_verify, mock_sleep):
        """Wrong password → 401 with vague 'Invalid credentials.' message (T10)."""
        user = _make_user()
        client = self._make_client(user=user)

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "wrongpassword"},
        )

        assert resp.status_code == 401
        body = resp.json()
        assert body["error"]["code"] == "INVALID_CREDENTIALS"
        assert "password" not in body["error"]["message"].lower()
        assert "email" not in body["error"]["message"].lower()

    @patch("app.security.lockout.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.api.v1.routes_auth.verify_password", return_value=False)
    def test_login_user_not_found_same_message_as_wrong_password(self, mock_verify, mock_sleep):
        """
        Non-existent email → same 401 message as wrong password (T10 — no enumeration).
        bcrypt still runs (verified by checking verify_password was called).
        """
        client = self._make_client(user=None)  # No user in DB

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@example.com", "password": "anything"},
        )

        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"
        # bcrypt must always run — even for non-existent users
        mock_verify.assert_called_once()

    @patch("app.security.lockout.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.api.v1.routes_auth.verify_password", return_value=True)
    def test_login_inactive_user_returns_401_not_403(self, mock_verify, mock_sleep):
        """Deactivated account → 401 (same vague message, T10 — no info leakage)."""
        user = _make_user(is_active=False)
        client = self._make_client(user=user)

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "correctpassword"},
        )

        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"

    @patch("app.security.lockout.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.api.v1.routes_auth.verify_password", return_value=True)
    def test_login_unapproved_user_returns_401(self, mock_verify, mock_sleep):
        """Not-yet-approved account → 401 (vague message, T10)."""
        user = _make_user(is_approved=False)
        client = self._make_client(user=user)

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "correctpassword"},
        )

        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"

    def test_login_redis_locked_account_returns_423(self):
        """Redis lockout key present → 423 Account Locked before bcrypt runs."""
        redis = _make_redis()
        redis.get = AsyncMock(return_value=b"locked")  # Account is locked in Redis
        redis.ttl = AsyncMock(return_value=1200)

        client = self._make_client(redis=redis)

        with patch("app.api.v1.routes_auth.verify_password") as mock_verify:
            resp = client.post(
                "/api/v1/auth/login",
                json={"email": "user@example.com", "password": "anypassword"},
            )
            # bcrypt must NOT run — lockout check is before password verification
            mock_verify.assert_not_called()

        assert resp.status_code == 423
        assert resp.json()["error"]["code"] == "ACCOUNT_LOCKED"

    @patch("app.security.lockout.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.api.v1.routes_auth.verify_password", return_value=False)
    def test_login_db_locked_account_returns_423(self, mock_verify, mock_sleep):
        """DB locked_until in future → 423 even if Redis has expired (restart recovery)."""
        locked_until = datetime.now(timezone.utc) + timedelta(minutes=20)
        user = _make_user(locked_until=locked_until)
        client = self._make_client(user=user)

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "anypassword"},
        )

        assert resp.status_code == 423
        assert resp.json()["error"]["code"] == "ACCOUNT_LOCKED"

    def test_login_missing_email_returns_422(self):
        """Missing required field → 422 Unprocessable Entity."""
        client = self._make_client()
        resp = client.post("/api/v1/auth/login", json={"password": "somepassword"})
        assert resp.status_code == 422

    def test_login_missing_password_returns_422(self):
        client = self._make_client()
        resp = client.post("/api/v1/auth/login", json={"email": "user@example.com"})
        assert resp.status_code == 422

    def test_login_invalid_email_format_returns_422(self):
        """Malformed email → 422 from Pydantic EmailStr validation."""
        client = self._make_client()
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "not-an-email", "password": "somepassword"},
        )
        assert resp.status_code == 422

    def test_login_password_too_long_returns_422(self):
        """Password > 128 chars → 422 (DoS prevention)."""
        client = self._make_client()
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "x" * 129},
        )
        assert resp.status_code == 422

    @patch("app.security.lockout.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.api.v1.routes_auth.verify_password", return_value=False)
    def test_login_failed_increments_db_counter(self, mock_verify, mock_sleep):
        """Failed login increments failed_login_attempts on the DB user record."""
        user = _make_user(failed_login_attempts=2)
        client = self._make_client(user=user)

        client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "wrong"},
        )

        # DB commit was called (to persist the updated attempt count)
        # Find the db session and assert commit was called
        # The user.failed_login_attempts should have been incremented
        assert user.failed_login_attempts == 3

    @patch("app.security.lockout.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.api.v1.routes_auth.verify_password", return_value=True)
    def test_login_success_clears_failed_attempts(self, mock_verify, mock_sleep):
        """Successful login resets failed_login_attempts to 0."""
        user = _make_user(role="viewer", failed_login_attempts=3)
        client = self._make_client(user=user)

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "correct"},
        )

        assert resp.status_code == 200
        assert user.failed_login_attempts == 0
        assert user.locked_until is None

    @patch("app.security.lockout.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.api.v1.routes_auth.verify_password", return_value=True)
    def test_login_success_sets_last_login_at(self, mock_verify, mock_sleep):
        """Successful login sets last_login_at timestamp."""
        user = _make_user(role="viewer")
        client = self._make_client(user=user)

        client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "correct"},
        )

        assert user.last_login_at is not None
        assert isinstance(user.last_login_at, datetime)


# =============================================================================
# TOTP Verify Endpoint Tests
# =============================================================================

class TestTOTPVerifyEndpoint:
    """POST /api/v1/auth/totp/verify"""

    def _make_client(self, user: Optional[MagicMock] = None, redis=None) -> tuple[TestClient, FastAPI]:
        app = _build_test_app()
        db_session = _make_db_session(user)
        mock_audit = AsyncMock()
        mock_audit.log = AsyncMock()
        mock_km = MagicMock()
        mock_redis = redis or _make_redis()

        async def override_db():
            yield db_session

        from app.dependencies import get_db, get_key_manager, get_audit_writer, get_pre_totp_redis

        app.dependency_overrides.update({
            get_db: override_db,
            get_key_manager: lambda: mock_km,
            get_audit_writer: lambda: mock_audit,
            get_pre_totp_redis: lambda: mock_redis,
        })
        return TestClient(app, raise_server_exceptions=False), app

    def test_totp_verify_success(self):
        """Valid pre_totp token + correct TOTP code → full access token + refresh cookie."""
        admin = _make_admin(totp_enabled=True, totp_secret_enc="v1:encrypted")
        client, app = self._make_client(user=admin)
        tokens = _issue_real_tokens(admin)

        with (
            patch("app.api.v1.routes_auth.decrypt_totp_secret", return_value="JBSWY3DPEHPK3PXP"),
            patch("app.api.v1.routes_auth.verify_totp_code", return_value=True),
        ):
            resp = client.post(
                "/api/v1/auth/totp/verify",
                json={"code": "123456"},
                headers={"Authorization": f"Bearer {tokens['pre_totp']}"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert "refresh_token" in resp.cookies

    def test_totp_verify_wrong_code_returns_401(self):
        """Wrong TOTP code → 401 MFA_INVALID."""
        admin = _make_admin(totp_enabled=True, totp_secret_enc="v1:encrypted")
        client, app = self._make_client(user=admin)
        tokens = _issue_real_tokens(admin)

        with (
            patch("app.api.v1.routes_auth.decrypt_totp_secret", return_value="JBSWY3DPEHPK3PXP"),
            patch("app.api.v1.routes_auth.verify_totp_code", return_value=False),
        ):
            resp = client.post(
                "/api/v1/auth/totp/verify",
                json={"code": "000000"},
                headers={"Authorization": f"Bearer {tokens['pre_totp']}"},
            )

        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "MFA_INVALID"

    def test_totp_verify_rejects_full_access_token(self):
        """
        Full access token (type=access) rejected on this endpoint.
        get_pre_totp_user() expects type=pre_totp.
        """
        admin = _make_admin()
        client, _ = self._make_client(user=admin)
        tokens = _issue_real_tokens(admin)

        resp = client.post(
                "/api/v1/auth/totp/verify",
                json={"code": "123456"},
                headers={"Authorization": f"Bearer {tokens['access']}"},
            )

        assert resp.status_code == 401

    def test_totp_verify_missing_token_returns_401(self):
        """No Authorization header → 401."""
        client, _ = self._make_client()
        resp = client.post("/api/v1/auth/totp/verify", json={"code": "123456"})
        assert resp.status_code == 401

    def test_totp_verify_no_secret_returns_401(self):
        """Admin with no TOTP secret stored → 401 (can't verify)."""
        admin = _make_admin(totp_secret_enc=None)
        client, _ = self._make_client(user=admin)
        tokens = _issue_real_tokens(admin)

        resp = client.post(
                "/api/v1/auth/totp/verify",
                json={"code": "123456"},
                headers={"Authorization": f"Bearer {tokens['pre_totp']}"},
            )

        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "MFA_INVALID"

    def test_totp_verify_activates_totp_if_not_yet_enabled(self):
        """If admin has secret but totp_enabled=False, verify sets it to True."""
        admin = _make_admin(totp_enabled=False, totp_secret_enc="v1:encrypted")
        client, _ = self._make_client(user=admin)
        tokens = _issue_real_tokens(admin)

        with (
            patch("app.api.v1.routes_auth.decrypt_totp_secret", return_value="BASE32SECRET"),
            patch("app.api.v1.routes_auth.verify_totp_code", return_value=True),
        ):
            resp = client.post(
                "/api/v1/auth/totp/verify",
                json={"code": "123456"},
                headers={"Authorization": f"Bearer {tokens['pre_totp']}"},
            )

        assert resp.status_code == 200
        # totp_enabled should now be True
        assert admin.totp_enabled is True


# =============================================================================
# Refresh Endpoint Tests
# =============================================================================

class TestRefreshEndpoint:
    """POST /api/v1/auth/refresh"""

    def _make_client(self, user: Optional[MagicMock] = None) -> TestClient:
        app = _build_test_app()
        db_session = _make_db_session(user)
        mock_redis = _make_redis()

        async def override_db():
            yield db_session

        from app.dependencies import get_db, get_redis_security

        app.dependency_overrides.update({
            get_db: override_db,
            get_redis_security: lambda: mock_redis,
        })
        return TestClient(app, raise_server_exceptions=False)

    def test_refresh_success_rotates_token(self):
        """Valid refresh cookie → new access token + new refresh cookie."""
        user = _make_user(role="analyst")
        client = self._make_client(user=user)
        tokens = _issue_real_tokens(user)

        resp = client.post(
            "/api/v1/auth/refresh",
            cookies={"refresh_token": tokens["refresh"]},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        # New refresh cookie must be set
        assert "refresh_token" in resp.cookies
        # New refresh token must differ from old one
        assert resp.cookies["refresh_token"] != tokens["refresh"]

    def test_refresh_no_cookie_returns_401(self):
        """Missing refresh_token cookie → 401."""
        client = self._make_client()
        resp = client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401

    def test_refresh_invalid_token_returns_401(self):
        """Malformed refresh token → 401."""
        user = _make_user()
        client = self._make_client(user=user)
        resp = client.post(
            "/api/v1/auth/refresh",
            cookies={"refresh_token": "not.a.valid.jwt"},
        )
        assert resp.status_code == 401

    def test_refresh_wrong_token_type_returns_401(self):
        """Access token in cookie slot (wrong type) → 401."""
        user = _make_user()
        client = self._make_client(user=user)
        tokens = _issue_real_tokens(user)
        # Pass access token where refresh is expected
        resp = client.post(
            "/api/v1/auth/refresh",
            cookies={"refresh_token": tokens["access"]},
        )
        assert resp.status_code == 401

    def test_refresh_deactivated_user_returns_401(self):
        """User deactivated since token was issued → 401."""
        user = _make_user(is_active=False)
        client = self._make_client(user=user)
        tokens = _issue_real_tokens(user)
        resp = client.post(
            "/api/v1/auth/refresh",
            cookies={"refresh_token": tokens["refresh"]},
        )
        assert resp.status_code == 401

    def test_refresh_unapproved_user_returns_401(self):
        """User pending approval → 401."""
        user = _make_user(is_approved=False)
        client = self._make_client(user=user)
        tokens = _issue_real_tokens(user)
        resp = client.post(
            "/api/v1/auth/refresh",
            cookies={"refresh_token": tokens["refresh"]},
        )
        assert resp.status_code == 401


# =============================================================================
# Logout Endpoint Tests
# =============================================================================

class TestLogoutEndpoint:
    """POST /api/v1/auth/logout"""

    def _make_client(
        self,
        current_user_override: Optional[dict] = None,
    ) -> tuple[TestClient, AsyncMock]:
        app = _build_test_app()
        mock_redis = _make_redis()

        default_user: dict[str, Any] = {
            "user_id": _TEST_USER_ID,
            "email": "user@example.com",
            "role": "viewer",
            "department": "",
            "jti": "test-jti-abc",
        }
        user_dict = current_user_override or default_user

        from app.dependencies import get_current_user, get_redis_security

        app.dependency_overrides.update({
            get_current_user: lambda: user_dict,
            get_redis_security: lambda: mock_redis,
        })
        return TestClient(app, raise_server_exceptions=False), mock_redis

    def test_logout_returns_204(self):
        """Successful logout → 204 No Content."""
        client, _ = self._make_client()
        resp = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": "Bearer sometoken"},
        )
        assert resp.status_code == 204

    def test_logout_deletes_refresh_cookie(self):
        """Logout response deletes the refresh_token cookie."""
        client, _ = self._make_client()
        # Set a cookie first (simulating it was set at login)
        resp = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": "Bearer sometoken"},
            cookies={"refresh_token": "somerefreshtoken"},
        )
        assert resp.status_code == 204
        # The cookie should be cleared (max-age=0 or Set-Cookie with empty value)
        set_cookie = resp.headers.get("set-cookie", "")
        assert "refresh_token" in set_cookie

    def test_logout_clears_admin_session_key(self):
        """Admin logout deletes admin_session:{user_id} from Redis DB1 (T15)."""
        admin_user = {
            "user_id": _TEST_ADMIN_ID,
            "email": "admin@example.com",
            "role": "admin",
            "department": "",
            "jti": "admin-jti",
        }
        client, mock_redis = self._make_client(current_user_override=admin_user)

        resp = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": "Bearer sometoken"},
        )

        assert resp.status_code == 204
        # Redis delete must have been called for the admin session key
        mock_redis.delete.assert_called()
        call_args = [str(c) for c in mock_redis.delete.call_args_list]
        assert any(f"admin_session:{_TEST_ADMIN_ID}" in arg for arg in call_args)

    def test_logout_no_auth_returns_401(self):
        """No Authorization header → 401 from get_current_user dependency."""
        app = _build_test_app()
        register_exception_handlers(app)
        mock_redis = _make_redis()

        from app.dependencies import get_redis_security
        app.dependency_overrides[get_redis_security] = lambda: mock_redis

        client = TestClient(app, raise_server_exceptions=False)
        with patch("app.dependencies.get_redis_security", return_value=mock_redis):
            resp = client.post("/api/v1/auth/logout")

        assert resp.status_code == 401


# =============================================================================
# Me Endpoint Tests
# =============================================================================

class TestMeEndpoint:
    """GET /api/v1/auth/me"""

    def _make_client(self, user: Optional[MagicMock] = None) -> TestClient:
        app = _build_test_app()
        db_session = _make_db_session(user)

        current_user_dict = {
            "user_id": _TEST_USER_ID,
            "email": "user@example.com",
            "role": "viewer",
            "department": "Engineering",
            "jti": "jti-123",
        }

        async def override_db():
            yield db_session

        from app.dependencies import get_db, get_current_user

        app.dependency_overrides.update({
            get_db: override_db,
            get_current_user: lambda: current_user_dict,
        })
        return TestClient(app, raise_server_exceptions=False)

    def test_me_returns_current_user_info(self):
        """GET /me returns fresh user data from DB."""
        user = _make_user(
            role="analyst",
            department="Data Science",
            totp_enabled=False,
        )
        client = self._make_client(user=user)

        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer faketoken"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == str(user.id)
        assert body["email"] == user.email
        assert body["name"] == user.name
        assert body["role"] == user.role
        assert body["department"] == user.department
        assert body["totp_enabled"] is False
        assert body["is_active"] is True
        assert body["is_approved"] is True

    def test_me_user_not_in_db_returns_404(self):
        """JWT valid but user deleted from DB → 404."""
        client = self._make_client(user=None)

        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer faketoken"},
        )

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_me_no_auth_returns_401(self):
        """No Authorization header → 401 (get_current_user dependency fails)."""
        app = _build_test_app()
        from app.dependencies import get_redis_security
        app.dependency_overrides[get_redis_security] = lambda: _make_redis()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401


# =============================================================================
# TOTP Setup Endpoint Tests
# =============================================================================

class TestTOTPSetupEndpoint:
    """POST /api/v1/auth/totp/setup"""

    def _make_client(self, user: Optional[MagicMock] = None, redis=None) -> TestClient:
        app = _build_test_app()
        db_session = _make_db_session(user)
        mock_km = MagicMock()
        mock_km.encrypt = MagicMock(return_value="v1:newencryptedsecret")
        mock_redis = redis or _make_redis()

        async def override_db():
            yield db_session

        from app.dependencies import get_db, get_key_manager, get_pre_totp_redis

        app.dependency_overrides.update({
            get_db: override_db,
            get_key_manager: lambda: mock_km,
            get_pre_totp_redis: lambda: mock_redis,
        })
        return TestClient(app, raise_server_exceptions=False)

    def test_totp_setup_success(self):
        """
        Valid pre_totp token → TOTP secret generated, encrypted, stored;
        QR code + secret + URI returned.
        """
        admin = _make_admin(totp_secret_enc=None)
        client = self._make_client(user=admin)
        tokens = _issue_real_tokens(admin)

        resp = client.post(
                "/api/v1/auth/totp/setup",
                headers={"Authorization": f"Bearer {tokens['pre_totp']}"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "qr_code" in body
        assert "secret" in body
        assert "uri" in body
        assert "otpauth://" in body["uri"]

    def test_totp_setup_full_token_rejected(self):
        """Full access token (type=access) rejected — must use pre_totp token."""
        user = _make_user()
        client = self._make_client(user=user)
        tokens = _issue_real_tokens(user)

        resp = client.post(
                "/api/v1/auth/totp/setup",
                headers={"Authorization": f"Bearer {tokens['access']}"},
            )

        assert resp.status_code == 401

    def test_totp_setup_stores_encrypted_secret_in_db(self):
        """Setup call writes encrypted secret to user.totp_secret_enc."""
        admin = _make_admin(totp_secret_enc=None)
        client = self._make_client(user=admin)
        tokens = _issue_real_tokens(admin)

        client.post(
                "/api/v1/auth/totp/setup",
                headers={"Authorization": f"Bearer {tokens['pre_totp']}"},
            )

        # Secret must have been written to the user record
        assert admin.totp_secret_enc is not None
        # TOTP must NOT be enabled yet — must be confirmed first
        assert admin.totp_enabled is False

    def test_totp_setup_no_token_returns_401(self):
        """Missing Authorization header → 401."""
        client = self._make_client()
        resp = client.post("/api/v1/auth/totp/setup")
        assert resp.status_code == 401


# =============================================================================
# TOTP Confirm Endpoint Tests
# =============================================================================

class TestTOTPConfirmEndpoint:
    """POST /api/v1/auth/totp/confirm"""

    def _make_client(self, user: Optional[MagicMock] = None, redis=None) -> TestClient:
        app = _build_test_app()
        db_session = _make_db_session(user)
        mock_km = MagicMock()
        mock_audit = AsyncMock()
        mock_audit.log = AsyncMock()
        mock_redis = redis or _make_redis()

        async def override_db():
            yield db_session

        from app.dependencies import get_db, get_key_manager, get_audit_writer, get_pre_totp_redis

        app.dependency_overrides.update({
            get_db: override_db,
            get_key_manager: lambda: mock_km,
            get_audit_writer: lambda: mock_audit,
            get_pre_totp_redis: lambda: mock_redis,
        })
        return TestClient(app, raise_server_exceptions=False)

    def test_totp_confirm_success_enables_totp(self):
        """Valid code → totp_enabled=True, 200 with success message."""
        admin = _make_admin(totp_enabled=False, totp_secret_enc="v1:encrypted")
        client = self._make_client(user=admin)
        tokens = _issue_real_tokens(admin)

        with (
            patch("app.api.v1.routes_auth.decrypt_totp_secret", return_value="BASE32SECRET"),
            patch("app.api.v1.routes_auth.verify_totp_code", return_value=True),
        ):
            resp = client.post(
                "/api/v1/auth/totp/confirm",
                json={"code": "123456"},
                headers={"Authorization": f"Bearer {tokens['pre_totp']}"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "message" in body
        assert "enabled" in body["message"].lower()
        # TOTP must now be activated on the model
        assert admin.totp_enabled is True

    def test_totp_confirm_wrong_code_returns_401(self):
        """Wrong TOTP code → 401 MFA_INVALID."""
        admin = _make_admin(totp_secret_enc="v1:encrypted")
        client = self._make_client(user=admin)
        tokens = _issue_real_tokens(admin)

        with (
            patch("app.api.v1.routes_auth.decrypt_totp_secret", return_value="BASE32SECRET"),
            patch("app.api.v1.routes_auth.verify_totp_code", return_value=False),
        ):
            resp = client.post(
                "/api/v1/auth/totp/confirm",
                json={"code": "999999"},
                headers={"Authorization": f"Bearer {tokens['pre_totp']}"},
            )

        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "MFA_INVALID"

    def test_totp_confirm_no_secret_stored_returns_401(self):
        """No secret stored (setup not called first) → 401."""
        admin = _make_admin(totp_secret_enc=None)
        client = self._make_client(user=admin)
        tokens = _issue_real_tokens(admin)

        resp = client.post(
                "/api/v1/auth/totp/confirm",
                json={"code": "123456"},
                headers={"Authorization": f"Bearer {tokens['pre_totp']}"},
            )

        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "MFA_INVALID"

    def test_totp_confirm_full_token_rejected(self):
        """Full access token rejected on this endpoint (needs pre_totp)."""
        user = _make_user()
        client = self._make_client(user=user)
        tokens = _issue_real_tokens(user)

        resp = client.post(
                "/api/v1/auth/totp/confirm",
                json={"code": "123456"},
                headers={"Authorization": f"Bearer {tokens['access']}"},
            )

        assert resp.status_code == 401

    def test_totp_confirm_missing_code_returns_422(self):
        """Missing body field → 422."""
        admin = _make_admin()
        client = self._make_client(user=admin)
        tokens = _issue_real_tokens(admin)

        resp = client.post(
                "/api/v1/auth/totp/confirm",
                json={},
                headers={"Authorization": f"Bearer {tokens['pre_totp']}"},
            )

        assert resp.status_code == 422


# =============================================================================
# Schema Validation Tests
# =============================================================================

class TestAuthSchemas:
    """Pydantic v2 schema validation — no HTTP call needed."""

    def test_login_request_normalises_email(self):
        from app.schemas.auth import LoginRequest
        req = LoginRequest(email="User@Example.COM", password="pw")
        assert req.email == "user@example.com"

    def test_login_request_strips_whitespace(self):
        from app.schemas.auth import LoginRequest
        req = LoginRequest(email="  user@example.com  ", password="  mypassword  ")
        assert req.email == "user@example.com"
        assert req.password == "mypassword"

    def test_login_request_rejects_empty_password(self):
        from app.schemas.auth import LoginRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            LoginRequest(email="user@example.com", password="")

    def test_login_request_rejects_password_over_128_chars(self):
        from app.schemas.auth import LoginRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            LoginRequest(email="user@example.com", password="a" * 129)

    def test_totp_verify_request_min_length(self):
        from app.schemas.auth import TOTPVerifyRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TOTPVerifyRequest(code="12345")  # 5 chars — too short

    def test_totp_confirm_request_min_length(self):
        from app.schemas.auth import TOTPConfirmRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TOTPConfirmRequest(code="1")

    def test_login_response_defaults(self):
        from app.schemas.auth import LoginResponse
        resp = LoginResponse(access_token="tok")
        assert resp.token_type == "bearer"
        assert resp.totp_required is False
        assert resp.totp_setup_required is False

    def test_me_response_allows_none_fields(self):
        from app.schemas.auth import MeResponse
        resp = MeResponse(
            user_id="abc",
            email="a@b.com",
            name="A",
            role="viewer",
            department=None,
            totp_enabled=False,
            is_active=True,
            is_approved=True,
            last_login_at=None,
        )
        assert resp.department is None
        assert resp.last_login_at is None


# =============================================================================
# create_pre_totp_token Tests
# =============================================================================

class TestPreTOTPToken:
    """Token construction and verification contracts."""

    def test_pre_totp_token_has_correct_type(self):
        """Token payload type must be 'pre_totp' (not 'access')."""
        from app.security.auth import create_pre_totp_token
        from jose import jwt
        from app.config import get_settings

        settings = get_settings()
        token = create_pre_totp_token(user_id=_TEST_ADMIN_ID, email="admin@example.com")
        payload = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=["RS256"],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
        )
        assert payload["type"] == "pre_totp"
        assert payload["role"] == "admin"
        assert payload["sub"] == _TEST_ADMIN_ID

    def test_pre_totp_token_rejected_by_get_current_user(self):
        """
        pre_totp token must not work on endpoints protected by get_current_user().
        Endpoint /me uses get_current_user (expected_type=access).
        """
        app = _build_test_app()
        db_session = _make_db_session(_make_user())

        async def override_db():
            yield db_session

        from app.dependencies import get_db

        app.dependency_overrides[get_db] = override_db

        admin = _make_admin()
        tokens = _issue_real_tokens(admin)

        from app.dependencies import get_redis_security
        app.dependency_overrides[get_redis_security] = lambda: _make_redis()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tokens['pre_totp']}"},
        )

        # Must be rejected — pre_totp ≠ access
        assert resp.status_code == 401

    def test_pre_totp_token_5_minute_expiry(self):
        """Pre-TOTP token TTL is 5 minutes (not 15)."""
        from app.security.auth import create_pre_totp_token
        from jose import jwt
        from app.config import get_settings

        settings = get_settings()
        token = create_pre_totp_token(user_id=_TEST_ADMIN_ID, email="admin@example.com")
        payload = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=["RS256"],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
        )

        iat = payload["iat"]
        exp = payload["exp"]
        ttl_minutes = (exp - iat) / 60
        assert 4 <= ttl_minutes <= 6  # 5 minutes ± tolerance