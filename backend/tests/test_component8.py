"""
Smart BI Agent — Component 8 Tests
User management routes: /users, /users/{id}, create, update, deactivate, gdpr-erase

Test strategy:
  - FastAPI TestClient (sync) with dependency_overrides — no real DB or Redis
  - require_admin overridden directly for admin-only endpoints
  - get_current_user overridden for mixed (admin-or-self) endpoints
  - MagicMock User objects match the SQLAlchemy model shape
  - DB session mock handles both single-user and list/count query patterns

Coverage:
  - List: pagination, filters, non-admin 403
  - Get: admin any user, self-service, IDOR protection (403 not 404)
  - Create: success, duplicate email (409), validation failures (422), non-admin (403)
  - Update: admin all fields, self-service (name/department only), non-admin blocked (403)
  - Deactivate: success, self-deactivation blocked, non-admin 403, missing 404
  - GDPR erase: anonymises all PII, self-erase blocked, non-admin 403
  - Schemas: validation rules, email normalisation, field exclusions
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors.handlers import register_exception_handlers
from app.errors.exceptions import AdminRequiredError


# =============================================================================
# Constants
# =============================================================================

_TEST_USER_ID  = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_TEST_ADMIN_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_TEST_OTHER_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"

_FIXED_NOW = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


# =============================================================================
# Mock builders
# =============================================================================

def _make_user(**kwargs) -> MagicMock:
    """Build a mock User with viewer defaults — matches SQLAlchemy model shape."""
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
    user.created_at = _FIXED_NOW
    user.updated_at = _FIXED_NOW
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
        is_approved=True,
        totp_enabled=True,
        totp_secret_enc="v1:encrypted",
    )
    defaults.update(kwargs)
    return _make_user(**defaults)


def _make_db_session(
    user: Optional[MagicMock] = None,
    users: Optional[list] = None,
    count: Optional[int] = None,
) -> AsyncMock:
    """
    Flexible DB session mock.

    - user=X         → single-query path: execute() returns result with scalar_one_or_none()=X
    - users=[...]    → two-query path: first execute() returns count, second returns list
    - count=N        → override total count for list path (defaults to len(users))
    """
    session = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    if users is not None:
        total = count if count is not None else len(users)

        count_result = MagicMock()
        count_result.scalar.return_value = total

        list_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = users
        list_result.scalars.return_value = scalars_mock

        session.execute = AsyncMock(side_effect=[count_result, list_result])
    else:
        single_result = MagicMock()
        single_result.scalar_one_or_none.return_value = user
        session.execute = AsyncMock(return_value=single_result)

    return session


def _make_audit() -> AsyncMock:
    audit = AsyncMock()
    audit.log = AsyncMock()
    return audit


# Admin user dict as returned by require_admin / get_current_user
_ADMIN_DICT: dict[str, Any] = {
    "user_id": _TEST_ADMIN_ID,
    "email": "admin@example.com",
    "role": "admin",
    "department": "",
    "jti": "test-admin-jti",
}

_USER_DICT: dict[str, Any] = {
    "user_id": _TEST_USER_ID,
    "email": "user@example.com",
    "role": "viewer",
    "department": "Engineering",
    "jti": "test-user-jti",
}


# =============================================================================
# App builder
# =============================================================================

def _build_test_app() -> FastAPI:
    """Build a minimal FastAPI app with only the users router."""
    from app.api.v1.routes_users import router as users_router
    app = FastAPI()
    app.include_router(users_router, prefix="/api/v1/users", tags=["users"])
    register_exception_handlers(app)
    return app


def _make_admin_client(db=None, audit=None) -> TestClient:
    """Client with require_admin overridden to return the admin dict."""
    app = _build_test_app()
    mock_db = db or _make_db_session()
    mock_audit = audit or _make_audit()

    async def override_db():
        yield mock_db

    from app.dependencies import require_admin, get_db, get_audit_writer
    app.dependency_overrides.update({
        require_admin: lambda: _ADMIN_DICT,
        get_db: override_db,
        get_audit_writer: lambda: mock_audit,
    })
    return TestClient(app, raise_server_exceptions=False)


def _make_user_client(current_user: dict, db=None, audit=None) -> TestClient:
    """Client with get_current_user overridden to the given dict."""
    app = _build_test_app()
    mock_db = db or _make_db_session()
    mock_audit = audit or _make_audit()

    async def override_db():
        yield mock_db

    from app.dependencies import get_current_user, get_db, get_audit_writer
    app.dependency_overrides.update({
        get_current_user: lambda: current_user,
        get_db: override_db,
        get_audit_writer: lambda: mock_audit,
    })
    return TestClient(app, raise_server_exceptions=False)


def _make_non_admin_client(db=None) -> TestClient:
    """Client with require_admin overriding to raise AdminRequiredError (→ 403)."""
    app = _build_test_app()
    mock_db = db or _make_db_session()

    async def override_db():
        yield mock_db

    def _reject():
        raise AdminRequiredError()

    from app.dependencies import require_admin, get_db, get_audit_writer
    app.dependency_overrides.update({
        require_admin: _reject,
        get_db: override_db,
        get_audit_writer: lambda: _make_audit(),
    })
    return TestClient(app, raise_server_exceptions=False)


# =============================================================================
# LIST ENDPOINT TESTS
# =============================================================================

class TestUserListEndpoint:
    """GET /api/v1/users"""

    def test_admin_gets_user_list(self):
        """Admin receives a list of users."""
        users = [_make_user(), _make_user(id=uuid.UUID(_TEST_OTHER_ID), email="other@example.com")]
        client = _make_admin_client(db=_make_db_session(users=users))

        resp = client.get("/api/v1/users/")

        assert resp.status_code == 200
        body = resp.json()
        assert "users" in body
        assert "meta" in body
        assert len(body["users"]) == 2

    def test_list_returns_pagination_metadata(self):
        """Meta contains total, skip, limit, has_more."""
        users = [_make_user()]
        client = _make_admin_client(db=_make_db_session(users=users, count=5))

        resp = client.get("/api/v1/users/?skip=0&limit=1")

        assert resp.status_code == 200
        meta = resp.json()["meta"]
        assert meta["total"] == 5
        assert meta["skip"] == 0
        assert meta["limit"] == 1
        assert meta["has_more"] is True

    def test_list_has_more_false_at_end(self):
        """has_more is False when all results fit in one page."""
        users = [_make_user()]
        client = _make_admin_client(db=_make_db_session(users=users, count=1))

        resp = client.get("/api/v1/users/?skip=0&limit=50")

        assert resp.json()["meta"]["has_more"] is False

    def test_list_non_admin_returns_403(self):
        """Non-admin cannot access the user list."""
        client = _make_non_admin_client()
        resp = client.get("/api/v1/users/")
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "ADMIN_REQUIRED"

    def test_list_pagination_skip_param(self):
        """skip param is echoed back in meta."""
        client = _make_admin_client(db=_make_db_session(users=[], count=0))
        resp = client.get("/api/v1/users/?skip=10&limit=5")
        assert resp.status_code == 200
        assert resp.json()["meta"]["skip"] == 10
        assert resp.json()["meta"]["limit"] == 5

    def test_list_limit_too_large_returns_422(self):
        """limit > 200 is rejected by FastAPI query validation."""
        client = _make_admin_client()
        resp = client.get("/api/v1/users/?limit=999")
        assert resp.status_code == 422

    def test_list_user_fields_no_sensitive_data(self):
        """Response users never include hashed_password or totp_secret_enc."""
        users = [_make_user()]
        client = _make_admin_client(db=_make_db_session(users=users))
        resp = client.get("/api/v1/users/")
        assert resp.status_code == 200
        user_body = resp.json()["users"][0]
        assert "hashed_password" not in user_body
        assert "totp_secret_enc" not in user_body
        assert "failed_login_attempts" not in user_body
        assert "locked_until" not in user_body


# =============================================================================
# GET SINGLE USER ENDPOINT TESTS
# =============================================================================

class TestUserGetEndpoint:
    """GET /api/v1/users/{user_id}"""

    def test_admin_gets_any_user(self):
        """Admin can retrieve any user's profile."""
        user = _make_user()
        db = _make_db_session(user=user)
        client = _make_user_client(_ADMIN_DICT, db=db)

        resp = client.get(f"/api/v1/users/{_TEST_USER_ID}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == _TEST_USER_ID
        assert body["email"] == "user@example.com"
        assert body["name"] == "Test User"

    def test_user_gets_own_profile(self):
        """Non-admin user can retrieve their own profile."""
        user = _make_user()
        db = _make_db_session(user=user)
        client = _make_user_client(_USER_DICT, db=db)

        resp = client.get(f"/api/v1/users/{_TEST_USER_ID}")

        assert resp.status_code == 200
        assert resp.json()["user_id"] == _TEST_USER_ID

    def test_user_cannot_get_other_user_returns_403(self):
        """Non-admin requesting another user's profile → 403 (IDOR prevention)."""
        client = _make_user_client(_USER_DICT)  # viewer trying to get admin's profile

        resp = client.get(f"/api/v1/users/{_TEST_ADMIN_ID}")

        assert resp.status_code == 403
        # Must be 403, not 404 — to avoid leaking that the user exists
        assert resp.json()["error"]["code"] == "RESOURCE_OWNERSHIP"

    def test_admin_get_nonexistent_user_returns_404(self):
        """Admin requesting a user that doesn't exist → 404."""
        db = _make_db_session(user=None)
        client = _make_user_client(_ADMIN_DICT, db=db)

        missing_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        resp = client.get(f"/api/v1/users/{missing_id}")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_get_returns_no_sensitive_fields(self):
        """UserResponse never exposes internal security fields."""
        user = _make_user()
        db = _make_db_session(user=user)
        client = _make_user_client(_ADMIN_DICT, db=db)

        resp = client.get(f"/api/v1/users/{_TEST_USER_ID}")
        body = resp.json()

        assert "hashed_password" not in body
        assert "totp_secret_enc" not in body
        assert "failed_login_attempts" not in body
        assert "locked_until" not in body

    def test_get_invalid_uuid_returns_422(self):
        """Malformed UUID in path → 422 validation error."""
        client = _make_user_client(_ADMIN_DICT)
        resp = client.get("/api/v1/users/not-a-uuid")
        assert resp.status_code == 422


# =============================================================================
# CREATE USER ENDPOINT TESTS
# =============================================================================

class TestUserCreateEndpoint:
    """POST /api/v1/users"""

    _VALID_BODY = {
        "email": "newuser@example.com",
        "name": "New User",
        "password": "SecurePass123",
        "role": "viewer",
        "department": "Engineering",
    }

    def test_admin_creates_user_success(self):
        """Admin can create a new user — returns 201 with user data."""
        db = _make_db_session(user=None)  # No duplicate found
        client = _make_admin_client(db=db)

        resp = client.post("/api/v1/users/", json=self._VALID_BODY)

        assert resp.status_code == 201
        body = resp.json()
        assert body["email"] == "newuser@example.com"
        assert body["name"] == "New User"
        assert body["role"] == "viewer"
        assert body["department"] == "Engineering"
        assert body["is_active"] is True
        assert body["is_approved"] is False  # New accounts need approval (T53)
        assert body["totp_enabled"] is False
        assert "user_id" in body

    def test_create_user_email_lowercased_in_response(self):
        """Email is normalised to lowercase in the response."""
        db = _make_db_session(user=None)
        client = _make_admin_client(db=db)

        resp = client.post("/api/v1/users/", json={**self._VALID_BODY, "email": "NewUser@EXAMPLE.COM"})

        assert resp.status_code == 201
        assert resp.json()["email"] == "newuser@example.com"

    def test_create_duplicate_email_returns_409(self):
        """Duplicate email → 409 Conflict."""
        existing_user = _make_user()
        db = _make_db_session(user=existing_user)  # Duplicate found
        client = _make_admin_client(db=db)

        resp = client.post("/api/v1/users/", json=self._VALID_BODY)

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "DUPLICATE_RESOURCE"

    def test_create_user_password_not_in_response(self):
        """hashed_password is never returned in the response."""
        db = _make_db_session(user=None)
        client = _make_admin_client(db=db)

        resp = client.post("/api/v1/users/", json=self._VALID_BODY)

        assert resp.status_code == 201
        assert "password" not in resp.json()
        assert "hashed_password" not in resp.json()

    def test_create_user_hashes_password(self):
        """The password is hashed before storage (bcrypt detected by prefix)."""
        captured_user = None

        async def override_db_capture():
            session = _make_db_session(user=None)
            original_add = session.add

            def capture_add(u):
                nonlocal captured_user
                captured_user = u
                return original_add(u)

            session.add = capture_add
            yield session

        app = _build_test_app()
        from app.dependencies import require_admin, get_db, get_audit_writer
        app.dependency_overrides.update({
            require_admin: lambda: _ADMIN_DICT,
            get_db: override_db_capture,
            get_audit_writer: lambda: _make_audit(),
        })
        client = TestClient(app, raise_server_exceptions=False)

        client.post("/api/v1/users/", json=self._VALID_BODY)

        assert captured_user is not None
        assert captured_user.hashed_password != "SecurePass123"
        assert captured_user.hashed_password.startswith("$2b$")

    def test_create_non_admin_returns_403(self):
        """Non-admin cannot create users."""
        client = _make_non_admin_client()
        resp = client.post("/api/v1/users/", json=self._VALID_BODY)
        assert resp.status_code == 403

    def test_create_missing_email_returns_422(self):
        """Missing required email field → 422."""
        client = _make_admin_client()
        resp = client.post("/api/v1/users/", json={"name": "X", "password": "pass1234"})
        assert resp.status_code == 422

    def test_create_password_too_short_returns_422(self):
        """Password shorter than 8 chars → 422."""
        client = _make_admin_client()
        resp = client.post("/api/v1/users/", json={**self._VALID_BODY, "password": "short"})
        assert resp.status_code == 422

    def test_create_password_too_long_returns_422(self):
        """Password longer than 128 chars → 422 (bcrypt protection)."""
        client = _make_admin_client()
        resp = client.post("/api/v1/users/", json={**self._VALID_BODY, "password": "x" * 129})
        assert resp.status_code == 422

    def test_create_invalid_role_returns_422(self):
        """Invalid role value → 422."""
        client = _make_admin_client()
        resp = client.post("/api/v1/users/", json={**self._VALID_BODY, "role": "superuser"})
        assert resp.status_code == 422

    def test_create_writes_audit_log(self):
        """Successful user creation writes an audit log entry."""
        db = _make_db_session(user=None)
        mock_audit = _make_audit()
        client = _make_admin_client(db=db, audit=mock_audit)

        resp = client.post("/api/v1/users/", json=self._VALID_BODY)

        assert resp.status_code == 201
        mock_audit.log.assert_called_once()
        call_kwargs = mock_audit.log.call_args.kwargs
        assert call_kwargs["execution_status"] == "user.created"
        assert "newuser@example.com" in call_kwargs["question"]


# =============================================================================
# UPDATE USER ENDPOINT TESTS
# =============================================================================

class TestUserUpdateEndpoint:
    """PATCH /api/v1/users/{user_id}"""

    def test_admin_updates_user_role(self):
        """Admin can change a user's role."""
        user = _make_user(role="viewer")
        db = _make_db_session(user=user)
        client = _make_user_client(_ADMIN_DICT, db=db)

        resp = client.patch(
            f"/api/v1/users/{_TEST_USER_ID}",
            json={"role": "analyst"},
        )

        assert resp.status_code == 200
        assert user.role == "analyst"

    def test_admin_approves_user(self):
        """Admin can approve a pending user."""
        user = _make_user(is_approved=False)
        db = _make_db_session(user=user)
        client = _make_user_client(_ADMIN_DICT, db=db)

        resp = client.patch(
            f"/api/v1/users/{_TEST_USER_ID}",
            json={"is_approved": True},
        )

        assert resp.status_code == 200
        assert user.is_approved is True

    def test_admin_deactivates_via_patch(self):
        """Admin can set is_active=False via PATCH."""
        user = _make_user(is_active=True)
        db = _make_db_session(user=user)
        client = _make_user_client(_ADMIN_DICT, db=db)

        resp = client.patch(
            f"/api/v1/users/{_TEST_USER_ID}",
            json={"is_active": False},
        )

        assert resp.status_code == 200
        assert user.is_active is False

    def test_user_updates_own_name_and_department(self):
        """Non-admin can update their own name and department."""
        user = _make_user(name="Old Name", department="Old Dept")
        db = _make_db_session(user=user)
        client = _make_user_client(_USER_DICT, db=db)

        resp = client.patch(
            f"/api/v1/users/{_TEST_USER_ID}",
            json={"name": "New Name", "department": "New Dept"},
        )

        assert resp.status_code == 200
        assert user.name == "New Name"
        assert user.department == "New Dept"

    def test_non_admin_cannot_change_own_role(self):
        """Non-admin attempting to change their own role → 403."""
        user = _make_user()
        db = _make_db_session(user=user)
        client = _make_user_client(_USER_DICT, db=db)

        resp = client.patch(
            f"/api/v1/users/{_TEST_USER_ID}",
            json={"role": "admin"},
        )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    def test_non_admin_cannot_change_is_approved(self):
        """Non-admin attempting to change is_approved → 403."""
        user = _make_user(is_approved=False)
        db = _make_db_session(user=user)
        client = _make_user_client(_USER_DICT, db=db)

        resp = client.patch(
            f"/api/v1/users/{_TEST_USER_ID}",
            json={"is_approved": True},
        )

        assert resp.status_code == 403

    def test_user_cannot_update_other_user_returns_403(self):
        """Non-admin trying to update another user's profile → 403."""
        client = _make_user_client(_USER_DICT)

        resp = client.patch(
            f"/api/v1/users/{_TEST_ADMIN_ID}",  # Other user
            json={"name": "Hacked"},
        )

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "RESOURCE_OWNERSHIP"

    def test_update_nonexistent_user_returns_404(self):
        """Updating a user that doesn't exist → 404."""
        db = _make_db_session(user=None)
        client = _make_user_client(_ADMIN_DICT, db=db)

        missing_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        resp = client.patch(f"/api/v1/users/{missing_id}", json={"name": "X"})

        assert resp.status_code == 404

    def test_update_writes_audit_log(self):
        """Successful update writes an audit log entry."""
        user = _make_user()
        db = _make_db_session(user=user)
        mock_audit = _make_audit()
        client = _make_user_client(_ADMIN_DICT, db=db, audit=mock_audit)

        client.patch(f"/api/v1/users/{_TEST_USER_ID}", json={"name": "Updated"})

        mock_audit.log.assert_called_once()
        call_kwargs = mock_audit.log.call_args.kwargs
        assert call_kwargs["execution_status"] == "user.updated"


# =============================================================================
# DEACTIVATE USER ENDPOINT TESTS
# =============================================================================

class TestUserDeactivateEndpoint:
    """DELETE /api/v1/users/{user_id}"""

    def test_admin_deactivates_user(self):
        """Admin can deactivate another user — returns 204."""
        user = _make_user(is_active=True)
        db = _make_db_session(user=user)
        client = _make_admin_client(db=db)

        resp = client.delete(f"/api/v1/users/{_TEST_USER_ID}")

        assert resp.status_code == 204
        assert resp.content == b""

    def test_deactivated_user_is_active_false(self):
        """Deactivation sets is_active=False on the model."""
        user = _make_user(is_active=True)
        db = _make_db_session(user=user)
        client = _make_admin_client(db=db)

        client.delete(f"/api/v1/users/{_TEST_USER_ID}")

        assert user.is_active is False

    def test_admin_cannot_deactivate_self(self):
        """Admin cannot deactivate their own account — 403."""
        client = _make_admin_client()

        resp = client.delete(f"/api/v1/users/{_TEST_ADMIN_ID}")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    def test_non_admin_cannot_deactivate_returns_403(self):
        """Non-admin attempting to deactivate a user → 403."""
        client = _make_non_admin_client()

        resp = client.delete(f"/api/v1/users/{_TEST_USER_ID}")

        assert resp.status_code == 403

    def test_deactivate_nonexistent_user_returns_404(self):
        """Deactivating a user that doesn't exist → 404."""
        db = _make_db_session(user=None)
        client = _make_admin_client(db=db)

        missing_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        resp = client.delete(f"/api/v1/users/{missing_id}")

        assert resp.status_code == 404

    def test_deactivate_writes_audit_log(self):
        """Successful deactivation writes an audit log entry."""
        user = _make_user()
        db = _make_db_session(user=user)
        mock_audit = _make_audit()
        client = _make_admin_client(db=db, audit=mock_audit)

        client.delete(f"/api/v1/users/{_TEST_USER_ID}")

        mock_audit.log.assert_called_once()
        call_kwargs = mock_audit.log.call_args.kwargs
        assert call_kwargs["execution_status"] == "user.deactivated"


# =============================================================================
# GDPR ERASE ENDPOINT TESTS
# =============================================================================

class TestUserGDPREraseEndpoint:
    """POST /api/v1/users/{user_id}/gdpr-erase"""

    def test_gdpr_erase_anonymises_name(self):
        """GDPR erase sets user.name to '[GDPR_ERASED]'."""
        user = _make_user(name="John Smith")
        db = _make_db_session(user=user)
        client = _make_admin_client(db=db)

        resp = client.post(f"/api/v1/users/{_TEST_USER_ID}/gdpr-erase")

        assert resp.status_code == 200
        assert user.name == "[GDPR_ERASED]"

    def test_gdpr_erase_anonymises_email(self):
        """GDPR erase replaces email with a unique non-PII sentinel."""
        user = _make_user(email="john.smith@company.com")
        db = _make_db_session(user=user)
        client = _make_admin_client(db=db)

        client.post(f"/api/v1/users/{_TEST_USER_ID}/gdpr-erase")

        # Email must not contain original PII
        assert "john.smith" not in user.email
        assert "company.com" not in user.email
        # Must be unique (contains user ID) for DB constraint safety
        assert _TEST_USER_ID in user.email

    def test_gdpr_erase_nullifies_totp(self):
        """GDPR erase clears TOTP secret and disables TOTP."""
        user = _make_user(totp_secret_enc="v1:encrypted_secret", totp_enabled=True)
        db = _make_db_session(user=user)
        client = _make_admin_client(db=db)

        client.post(f"/api/v1/users/{_TEST_USER_ID}/gdpr-erase")

        assert user.totp_secret_enc is None
        assert user.totp_enabled is False

    def test_gdpr_erase_deactivates_user(self):
        """GDPR erase sets is_active=False."""
        user = _make_user(is_active=True)
        db = _make_db_session(user=user)
        client = _make_admin_client(db=db)

        client.post(f"/api/v1/users/{_TEST_USER_ID}/gdpr-erase")

        assert user.is_active is False

    def test_gdpr_erase_updates_audit_logs(self):
        """GDPR erase issues an UPDATE on audit_logs.question."""
        user = _make_user()
        db = _make_db_session(user=user)
        client = _make_admin_client(db=db)

        client.post(f"/api/v1/users/{_TEST_USER_ID}/gdpr-erase")

        # The db.execute should have been called twice:
        # 1. SELECT to fetch the user
        # 2. UPDATE on audit_logs
        assert db.execute.call_count == 2

    def test_gdpr_erase_response_body(self):
        """Response contains confirmation message and erased_user_id."""
        user = _make_user()
        db = _make_db_session(user=user)
        client = _make_admin_client(db=db)

        resp = client.post(f"/api/v1/users/{_TEST_USER_ID}/gdpr-erase")

        assert resp.status_code == 200
        body = resp.json()
        assert "message" in body
        assert "erased_user_id" in body
        assert body["erased_user_id"] == _TEST_USER_ID
        assert "GDPR" in body["message"]

    def test_admin_cannot_erase_self_returns_403(self):
        """Admin cannot erase their own account — 403."""
        client = _make_admin_client()

        resp = client.post(f"/api/v1/users/{_TEST_ADMIN_ID}/gdpr-erase")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    def test_non_admin_cannot_erase_returns_403(self):
        """Non-admin cannot invoke GDPR erase — 403."""
        client = _make_non_admin_client()

        resp = client.post(f"/api/v1/users/{_TEST_USER_ID}/gdpr-erase")

        assert resp.status_code == 403

    def test_gdpr_erase_nonexistent_user_returns_404(self):
        """GDPR erase on a missing user → 404."""
        db = _make_db_session(user=None)
        client = _make_admin_client(db=db)

        missing_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        resp = client.post(f"/api/v1/users/{missing_id}/gdpr-erase")

        assert resp.status_code == 404

    def test_gdpr_erase_writes_audit_log(self):
        """GDPR erase writes an audit log entry."""
        user = _make_user()
        db = _make_db_session(user=user)
        mock_audit = _make_audit()
        client = _make_admin_client(db=db, audit=mock_audit)

        client.post(f"/api/v1/users/{_TEST_USER_ID}/gdpr-erase")

        mock_audit.log.assert_called_once()
        call_kwargs = mock_audit.log.call_args.kwargs
        assert call_kwargs["execution_status"] == "user.gdpr_erased"


# =============================================================================
# SCHEMA TESTS
# =============================================================================

class TestUserSchemas:
    """Pydantic v2 schema validation — no HTTP call needed."""

    def test_create_request_normalises_email(self):
        """Email is fully lowercased including local part."""
        from app.schemas.user import UserCreateRequest
        req = UserCreateRequest(email="John.Doe@EXAMPLE.COM", name="John", password="password123")
        assert req.email == "john.doe@example.com"

    def test_create_request_strips_whitespace(self):
        """Leading/trailing whitespace is stripped from all fields."""
        from app.schemas.user import UserCreateRequest
        req = UserCreateRequest(
            email="  user@example.com  ",
            name="  Test User  ",
            password="  password123  ",
        )
        assert req.email == "user@example.com"
        assert req.name == "Test User"
        assert req.password == "password123"

    def test_create_password_min_length_enforced(self):
        """Password shorter than 8 chars raises ValidationError."""
        from app.schemas.user import UserCreateRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UserCreateRequest(email="x@x.com", name="X", password="short")

    def test_create_password_max_length_enforced(self):
        """Password longer than 128 chars raises ValidationError."""
        from app.schemas.user import UserCreateRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UserCreateRequest(email="x@x.com", name="X", password="x" * 129)

    def test_create_invalid_role_raises(self):
        """Invalid role value raises ValidationError."""
        from app.schemas.user import UserCreateRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UserCreateRequest(email="x@x.com", name="X", password="password123", role="root")

    def test_create_default_role_is_viewer(self):
        """Default role is viewer (least privilege)."""
        from app.schemas.user import UserCreateRequest
        from app.schemas.user import UserRole
        req = UserCreateRequest(email="x@x.com", name="X", password="password123")
        assert req.role == UserRole.viewer

    def test_update_request_all_fields_optional(self):
        """UserUpdateRequest can be instantiated with no fields (partial update)."""
        from app.schemas.user import UserUpdateRequest
        req = UserUpdateRequest()
        assert req.name is None
        assert req.department is None
        assert req.role is None
        assert req.is_active is None
        assert req.is_approved is None

    def test_user_role_enum_has_three_values(self):
        """UserRole enum has exactly viewer, analyst, admin."""
        from app.schemas.user import UserRole
        roles = {r.value for r in UserRole}
        assert roles == {"viewer", "analyst", "admin"}

    def test_gdpr_erase_response_default_message(self):
        """GDPREraseResponse has a meaningful default message."""
        from app.schemas.user import GDPREraseResponse
        resp = GDPREraseResponse(erased_user_id=_TEST_USER_ID)
        assert "GDPR" in resp.message
        assert resp.erased_user_id == _TEST_USER_ID

    def test_user_list_response_structure(self):
        """UserListResponse has users list and meta object."""
        from app.schemas.user import UserListResponse, UserListMeta, UserResponse
        resp = UserListResponse(
            users=[],
            meta=UserListMeta(total=0, skip=0, limit=50, has_more=False),
        )
        assert resp.users == []
        assert resp.meta.total == 0
        assert resp.meta.has_more is False