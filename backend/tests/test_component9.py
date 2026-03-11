"""
Smart BI Agent — Component 9 Tests
Connection management routes: /connections CRUD + /test endpoint

Test strategy:
  - FastAPI TestClient (sync) with dependency_overrides
  - require_admin always overridden (all endpoints are admin-only)
  - KeyManager mocked — encrypt returns "v1:ENCRYPTED", decrypt returns JSON
  - validate_connection_host patched at import path in routes module
  - _tcp_probe patched to control success/failure/latency
  - DB session mock handles list (count+data) and single-row patterns

Coverage:
  - List: pagination, active filter, field safety (no credentials)
  - Get: success, 404
  - Create: success, SSRF blocked (400), duplicate name (409), validations (422)
  - Create: credentials encrypted (verify encrypt called, plaintext not stored)
  - Update: metadata fields, credential re-encryption, SSRF re-validation on host change
  - Deactivate: success (204), 404, soft-delete (is_active=False)
  - Test: TCP success with latency, TCP failure, SSRF block, missing host/port
  - Schemas: enum validation, field ranges, ssl_mode, credential exclusion
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors.handlers import register_exception_handlers
from app.errors.exceptions import AdminRequiredError


# =============================================================================
# Constants
# =============================================================================

_CONN_ID   = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_ADMIN_ID  = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_FIXED_NOW = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

_ADMIN_DICT: dict[str, Any] = {
    "user_id": _ADMIN_ID,
    "email": "admin@example.com",
    "role": "admin",
    "department": "",
    "jti": "test-admin-jti",
}

_ENCRYPTED_CREDS = "v1:ENCRYPTED_CREDS_PLACEHOLDER"
_DECRYPTED_CREDS = json.dumps({"username": "dbuser", "password": "dbpass"})


# =============================================================================
# Mock builders
# =============================================================================

def _make_connection(**kwargs) -> MagicMock:
    conn = MagicMock()
    conn.id = uuid.UUID(_CONN_ID)
    conn.name = "My DB"
    conn.db_type = "postgresql"
    conn.host = "db.example.com"
    conn.port = 5432
    conn.database_name = "prod_db"
    conn.encrypted_credentials = _ENCRYPTED_CREDS
    conn.ssl_mode = "require"
    conn.query_timeout = 30
    conn.max_rows = 10000
    conn.max_result_bytes = 52428800
    conn.allowed_schemas = ["public"]
    conn.pool_min_size = 1
    conn.pool_max_size = 5
    conn.is_active = True
    conn.created_by = uuid.UUID(_ADMIN_ID)
    conn.created_at = _FIXED_NOW
    conn.updated_at = _FIXED_NOW
    for k, v in kwargs.items():
        setattr(conn, k, v)
    return conn


def _make_db_session(
    conn: Optional[MagicMock] = None,
    conns: Optional[list] = None,
    count: Optional[int] = None,
) -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    if conns is not None:
        total = count if count is not None else len(conns)
        count_result = MagicMock()
        count_result.scalar.return_value = total
        list_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = conns
        list_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(side_effect=[count_result, list_result])
    else:
        single_result = MagicMock()
        single_result.scalar_one_or_none.return_value = conn
        session.execute = AsyncMock(return_value=single_result)

    return session


def _make_key_manager(
    encrypt_return: str = _ENCRYPTED_CREDS,
    decrypt_return: str = _DECRYPTED_CREDS,
) -> MagicMock:
    km = MagicMock()
    km.encrypt.return_value = encrypt_return
    km.decrypt.return_value = decrypt_return
    return km


def _make_audit() -> AsyncMock:
    audit = AsyncMock()
    audit.log = AsyncMock()
    return audit


def _make_pinned_host(host="db.example.com", ip="203.0.113.10", port=5432):
    """PinnedHost-like mock."""
    ph = MagicMock()
    ph.original_host = host
    ph.resolved_ip = ip
    ph.port = port
    return ph


# =============================================================================
# App builder
# =============================================================================

def _build_test_app() -> FastAPI:
    from app.api.v1.routes_connections import router as conn_router
    app = FastAPI()
    app.include_router(conn_router, prefix="/api/v1/connections", tags=["connections"])
    register_exception_handlers(app)
    return app


def _make_admin_client(db=None, km=None, audit=None) -> TestClient:
    app = _build_test_app()
    mock_db = db or _make_db_session()
    mock_km = km or _make_key_manager()
    mock_audit = audit or _make_audit()

    async def override_db():
        yield mock_db

    from app.dependencies import require_admin, get_db, get_audit_writer, get_key_manager
    app.dependency_overrides.update({
        require_admin: lambda: _ADMIN_DICT,
        get_db: override_db,
        get_key_manager: lambda: mock_km,
        get_audit_writer: lambda: mock_audit,
    })
    return TestClient(app, raise_server_exceptions=False)


def _make_non_admin_client() -> TestClient:
    app = _build_test_app()

    async def override_db():
        yield _make_db_session()

    def _reject():
        raise AdminRequiredError()

    from app.dependencies import require_admin, get_db, get_audit_writer, get_key_manager
    app.dependency_overrides.update({
        require_admin: _reject,
        get_db: override_db,
        get_key_manager: lambda: _make_key_manager(),
        get_audit_writer: lambda: _make_audit(),
    })
    return TestClient(app, raise_server_exceptions=False)


# =============================================================================
# LIST ENDPOINT TESTS
# =============================================================================

class TestConnectionListEndpoint:
    """GET /api/v1/connections/"""

    def test_admin_gets_connection_list(self):
        conns = [_make_connection(), _make_connection(id=uuid.uuid4(), name="Other DB")]
        client = _make_admin_client(db=_make_db_session(conns=conns))
        resp = client.get("/api/v1/connections/")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["connections"]) == 2
        assert "total" in body

    def test_list_returns_pagination_fields(self):
        conns = [_make_connection()]
        client = _make_admin_client(db=_make_db_session(conns=conns, count=5))
        resp = client.get("/api/v1/connections/?skip=0&limit=1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert body["skip"] == 0
        assert body["limit"] == 1

    def test_list_never_returns_credentials(self):
        conns = [_make_connection()]
        client = _make_admin_client(db=_make_db_session(conns=conns))
        resp = client.get("/api/v1/connections/")
        assert resp.status_code == 200
        conn_body = resp.json()["connections"][0]
        assert "encrypted_credentials" not in conn_body
        assert "password" not in conn_body
        assert "username" not in conn_body

    def test_list_non_admin_returns_403(self):
        client = _make_non_admin_client()
        resp = client.get("/api/v1/connections/")
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "ADMIN_REQUIRED"

    def test_list_limit_too_large_returns_422(self):
        client = _make_admin_client()
        resp = client.get("/api/v1/connections/?limit=999")
        assert resp.status_code == 422


# =============================================================================
# GET SINGLE CONNECTION ENDPOINT TESTS
# =============================================================================

class TestConnectionGetEndpoint:
    """GET /api/v1/connections/{connection_id}"""

    def test_get_existing_connection(self):
        conn = _make_connection()
        client = _make_admin_client(db=_make_db_session(conn=conn))
        resp = client.get(f"/api/v1/connections/{_CONN_ID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["connection_id"] == _CONN_ID
        assert body["name"] == "My DB"
        assert body["db_type"] == "postgresql"
        assert body["host"] == "db.example.com"
        assert body["port"] == 5432

    def test_get_nonexistent_returns_404(self):
        client = _make_admin_client(db=_make_db_session(conn=None))
        missing = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        resp = client.get(f"/api/v1/connections/{missing}")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    def test_get_no_credentials_in_response(self):
        conn = _make_connection()
        client = _make_admin_client(db=_make_db_session(conn=conn))
        resp = client.get(f"/api/v1/connections/{_CONN_ID}")
        assert resp.status_code == 200
        assert "encrypted_credentials" not in resp.json()
        assert "password" not in resp.json()

    def test_get_invalid_uuid_returns_422(self):
        client = _make_admin_client()
        resp = client.get("/api/v1/connections/not-a-uuid")
        assert resp.status_code == 422

    def test_get_non_admin_returns_403(self):
        client = _make_non_admin_client()
        resp = client.get(f"/api/v1/connections/{_CONN_ID}")
        assert resp.status_code == 403


# =============================================================================
# CREATE CONNECTION ENDPOINT TESTS
# =============================================================================

class TestConnectionCreateEndpoint:
    """POST /api/v1/connections/"""

    _VALID_BODY = {
        "name": "Prod DB",
        "db_type": "postgresql",
        "host": "db.example.com",
        "port": 5432,
        "database_name": "prod",
        "username": "sbi_user",
        "password": "s3cr3t!",
        "ssl_mode": "require",
    }

    def _make_ssrf_ok_client(self, db=None, km=None, audit=None):
        """Client with SSRF guard patched to succeed."""
        pinned = _make_pinned_host()
        with patch(
            "app.api.v1.routes_connections.validate_connection_host",
            return_value=pinned,
        ):
            client = _make_admin_client(db=db or _make_db_session(conn=None), km=km, audit=audit)
            return client, pinned

    def test_create_connection_success(self):
        pinned = _make_pinned_host()
        with patch("app.api.v1.routes_connections.validate_connection_host", return_value=pinned):
            client = _make_admin_client(db=_make_db_session(conn=None))
            resp = client.post("/api/v1/connections/", json=self._VALID_BODY)
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Prod DB"
        assert body["db_type"] == "postgresql"
        assert body["host"] == "db.example.com"
        assert body["is_active"] is True

    def test_create_returns_no_credentials(self):
        pinned = _make_pinned_host()
        with patch("app.api.v1.routes_connections.validate_connection_host", return_value=pinned):
            client = _make_admin_client(db=_make_db_session(conn=None))
            resp = client.post("/api/v1/connections/", json=self._VALID_BODY)
        assert resp.status_code == 201
        assert "encrypted_credentials" not in resp.json()
        assert "password" not in resp.json()
        assert "username" not in resp.json()

    def test_create_encrypts_credentials(self):
        """Credentials are encrypted via key_manager.encrypt — plaintext never stored."""
        pinned = _make_pinned_host()
        mock_km = _make_key_manager()
        captured = {}

        original_add = MagicMock()
        db = _make_db_session(conn=None)

        def capture_add(obj):
            captured["conn"] = obj
            return original_add(obj)

        db.add = capture_add

        with patch("app.api.v1.routes_connections.validate_connection_host", return_value=pinned):
            client = _make_admin_client(db=db, km=mock_km)
            resp = client.post("/api/v1/connections/", json=self._VALID_BODY)

        assert resp.status_code == 201
        # encrypt() was called
        mock_km.encrypt.assert_called_once()
        call_args = mock_km.encrypt.call_args
        plaintext_arg = call_args[0][0]
        # Plaintext contains the password
        assert "s3cr3t!" in plaintext_arg
        # Stored value is the encrypted version, not plaintext
        if captured.get("conn"):
            assert captured["conn"].encrypted_credentials != "s3cr3t!"
            assert captured["conn"].encrypted_credentials == _ENCRYPTED_CREDS

    def test_create_ssrf_blocked_returns_400(self):
        """SSRF-blocked host → 400."""
        from app.errors.exceptions import SSRFError as AppSSRFError
        from app.security.ssrf_guard import SSRFError as GuardSSRFError

        with patch(
            "app.api.v1.routes_connections.validate_connection_host",
            side_effect=GuardSSRFError("Host resolves to private IP: 192.168.1.1"),
        ):
            client = _make_admin_client(db=_make_db_session(conn=None))
            resp = client.post("/api/v1/connections/", json=self._VALID_BODY)

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "CONNECTION_BLOCKED"

    def test_create_duplicate_name_returns_409(self):
        """Duplicate connection name → 409."""
        existing = _make_connection(name="Prod DB")
        pinned = _make_pinned_host()
        with patch("app.api.v1.routes_connections.validate_connection_host", return_value=pinned):
            client = _make_admin_client(db=_make_db_session(conn=existing))
            resp = client.post("/api/v1/connections/", json=self._VALID_BODY)
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "DUPLICATE_RESOURCE"

    def test_create_missing_host_returns_422(self):
        client = _make_admin_client()
        body = {**self._VALID_BODY}
        del body["host"]
        resp = client.post("/api/v1/connections/", json=body)
        assert resp.status_code == 422

    def test_create_invalid_port_too_high_returns_422(self):
        client = _make_admin_client()
        resp = client.post("/api/v1/connections/", json={**self._VALID_BODY, "port": 99999})
        assert resp.status_code == 422

    def test_create_invalid_port_zero_returns_422(self):
        client = _make_admin_client()
        resp = client.post("/api/v1/connections/", json={**self._VALID_BODY, "port": 0})
        assert resp.status_code == 422

    def test_create_invalid_db_type_returns_422(self):
        client = _make_admin_client()
        resp = client.post("/api/v1/connections/", json={**self._VALID_BODY, "db_type": "oracle"})
        assert resp.status_code == 422

    def test_create_non_admin_returns_403(self):
        client = _make_non_admin_client()
        resp = client.post("/api/v1/connections/", json=self._VALID_BODY)
        assert resp.status_code == 403

    def test_create_writes_audit_log(self):
        pinned = _make_pinned_host()
        mock_audit = _make_audit()
        with patch("app.api.v1.routes_connections.validate_connection_host", return_value=pinned):
            client = _make_admin_client(db=_make_db_session(conn=None), audit=mock_audit)
            resp = client.post("/api/v1/connections/", json=self._VALID_BODY)
        assert resp.status_code == 201
        mock_audit.log.assert_called_once()
        assert mock_audit.log.call_args.kwargs["execution_status"] == "connection.created"

    def test_create_query_timeout_default(self):
        """Default query_timeout=30 when not supplied."""
        pinned = _make_pinned_host()
        captured = {}
        db = _make_db_session(conn=None)
        original_add = db.add

        def capture(obj):
            captured["conn"] = obj
            original_add(obj)

        db.add = capture
        with patch("app.api.v1.routes_connections.validate_connection_host", return_value=pinned):
            body = {k: v for k, v in self._VALID_BODY.items()}  # no query_timeout
            client = _make_admin_client(db=db)
            resp = client.post("/api/v1/connections/", json=body)
        assert resp.status_code == 201
        assert resp.json()["query_timeout"] == 30


# =============================================================================
# UPDATE CONNECTION ENDPOINT TESTS
# =============================================================================

class TestConnectionUpdateEndpoint:
    """PATCH /api/v1/connections/{connection_id}"""

    def test_update_name(self):
        conn = _make_connection(name="Old Name")
        client = _make_admin_client(db=_make_db_session(conn=conn))
        resp = client.patch(f"/api/v1/connections/{_CONN_ID}", json={"name": "New Name"})
        assert resp.status_code == 200
        assert conn.name == "New Name"

    def test_update_ssl_mode(self):
        conn = _make_connection(ssl_mode="require")
        client = _make_admin_client(db=_make_db_session(conn=conn))
        resp = client.patch(f"/api/v1/connections/{_CONN_ID}", json={"ssl_mode": "verify-full"})
        assert resp.status_code == 200
        assert conn.ssl_mode == "verify-full"

    def test_update_host_reruns_ssrf_guard(self):
        """Changing host re-validates SSRF."""
        conn = _make_connection()
        pinned = _make_pinned_host(host="newdb.example.com", ip="203.0.113.20")
        with patch(
            "app.api.v1.routes_connections.validate_connection_host",
            return_value=pinned,
        ) as mock_validate:
            client = _make_admin_client(db=_make_db_session(conn=conn))
            resp = client.patch(
                f"/api/v1/connections/{_CONN_ID}",
                json={"host": "newdb.example.com"},
            )
        assert resp.status_code == 200
        mock_validate.assert_called_once_with("newdb.example.com", conn.port)

    def test_update_host_ssrf_blocked_returns_400(self):
        """Changing host to a blocked one → 400."""
        from app.security.ssrf_guard import SSRFError as GuardSSRFError
        conn = _make_connection()
        with patch(
            "app.api.v1.routes_connections.validate_connection_host",
            side_effect=GuardSSRFError("Blocked: 10.0.0.1"),
        ):
            client = _make_admin_client(db=_make_db_session(conn=conn))
            resp = client.patch(
                f"/api/v1/connections/{_CONN_ID}",
                json={"host": "internal.host"},
            )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "CONNECTION_BLOCKED"

    def test_update_credentials_re_encrypted(self):
        """Supplying new username/password re-encrypts credentials."""
        conn = _make_connection()
        mock_km = _make_key_manager()
        client = _make_admin_client(db=_make_db_session(conn=conn), km=mock_km)
        resp = client.patch(
            f"/api/v1/connections/{_CONN_ID}",
            json={"username": "newuser", "password": "newpass"},
        )
        assert resp.status_code == 200
        mock_km.encrypt.assert_called_once()
        # Encrypted value applied to model
        assert conn.encrypted_credentials == _ENCRYPTED_CREDS

    def test_update_password_only_preserves_username(self):
        """Supplying only password re-encrypts with existing username."""
        conn = _make_connection()
        mock_km = _make_key_manager(decrypt_return=json.dumps({"username": "existinguser", "password": "oldpass"}))
        client = _make_admin_client(db=_make_db_session(conn=conn), km=mock_km)
        resp = client.patch(
            f"/api/v1/connections/{_CONN_ID}",
            json={"password": "newpass123"},
        )
        assert resp.status_code == 200
        mock_km.decrypt.assert_called_once()
        call_args = mock_km.encrypt.call_args[0][0]
        data = json.loads(call_args)
        assert data["username"] == "existinguser"
        assert data["password"] == "newpass123"

    def test_update_nonexistent_returns_404(self):
        client = _make_admin_client(db=_make_db_session(conn=None))
        missing = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        resp = client.patch(f"/api/v1/connections/{missing}", json={"name": "X"})
        assert resp.status_code == 404

    def test_update_non_admin_returns_403(self):
        client = _make_non_admin_client()
        resp = client.patch(f"/api/v1/connections/{_CONN_ID}", json={"name": "X"})
        assert resp.status_code == 403

    def test_update_writes_audit_log(self):
        conn = _make_connection()
        mock_audit = _make_audit()
        client = _make_admin_client(db=_make_db_session(conn=conn), audit=mock_audit)
        resp = client.patch(f"/api/v1/connections/{_CONN_ID}", json={"name": "Updated"})
        assert resp.status_code == 200
        mock_audit.log.assert_called_once()
        assert mock_audit.log.call_args.kwargs["execution_status"] == "connection.updated"


# =============================================================================
# DEACTIVATE CONNECTION ENDPOINT TESTS
# =============================================================================

class TestConnectionDeactivateEndpoint:
    """DELETE /api/v1/connections/{connection_id}"""

    def test_deactivate_returns_204(self):
        conn = _make_connection(is_active=True)
        client = _make_admin_client(db=_make_db_session(conn=conn))
        resp = client.delete(f"/api/v1/connections/{_CONN_ID}")
        assert resp.status_code == 204
        assert resp.content == b""

    def test_deactivate_sets_is_active_false(self):
        conn = _make_connection(is_active=True)
        client = _make_admin_client(db=_make_db_session(conn=conn))
        client.delete(f"/api/v1/connections/{_CONN_ID}")
        assert conn.is_active is False

    def test_deactivate_nonexistent_returns_404(self):
        client = _make_admin_client(db=_make_db_session(conn=None))
        missing = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        resp = client.delete(f"/api/v1/connections/{missing}")
        assert resp.status_code == 404

    def test_deactivate_non_admin_returns_403(self):
        client = _make_non_admin_client()
        resp = client.delete(f"/api/v1/connections/{_CONN_ID}")
        assert resp.status_code == 403

    def test_deactivate_writes_audit_log(self):
        conn = _make_connection()
        mock_audit = _make_audit()
        client = _make_admin_client(db=_make_db_session(conn=conn), audit=mock_audit)
        client.delete(f"/api/v1/connections/{_CONN_ID}")
        mock_audit.log.assert_called_once()
        assert mock_audit.log.call_args.kwargs["execution_status"] == "connection.deactivated"


# =============================================================================
# TEST CONNECTION ENDPOINT TESTS
# =============================================================================

class TestConnectionTestEndpoint:
    """POST /api/v1/connections/{connection_id}/test"""

    def test_tcp_success_returns_success_and_latency(self):
        conn = _make_connection(host="db.example.com", port=5432)
        pinned = _make_pinned_host(ip="203.0.113.10")
        with patch("app.api.v1.routes_connections.validate_connection_host", return_value=pinned), \
             patch("app.api.v1.routes_connections._tcp_probe", return_value=(True, 42, None)) as mock_probe:
            client = _make_admin_client(db=_make_db_session(conn=conn))
            resp = client.post(f"/api/v1/connections/{_CONN_ID}/test")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["latency_ms"] == 42
        assert body["error"] is None
        assert body["resolved_ip"] == "203.0.113.10"
        mock_probe.assert_called_once_with(ip="203.0.113.10", port=5432)

    def test_tcp_failure_returns_error(self):
        conn = _make_connection()
        pinned = _make_pinned_host()
        with patch("app.api.v1.routes_connections.validate_connection_host", return_value=pinned), \
             patch("app.api.v1.routes_connections._tcp_probe", return_value=(False, None, "Connection refused")):
            client = _make_admin_client(db=_make_db_session(conn=conn))
            resp = client.post(f"/api/v1/connections/{_CONN_ID}/test")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["error"] == "Connection refused"
        assert body["latency_ms"] is None

    def test_ssrf_block_on_test_returns_success_false(self):
        """SSRF block during test → success=False (not 400) — graceful degradation."""
        from app.security.ssrf_guard import SSRFError as GuardSSRFError
        conn = _make_connection()
        with patch(
            "app.api.v1.routes_connections.validate_connection_host",
            side_effect=GuardSSRFError("Blocked IP"),
        ):
            client = _make_admin_client(db=_make_db_session(conn=conn))
            resp = client.post(f"/api/v1/connections/{_CONN_ID}/test")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "SSRF" in body["error"]

    def test_connection_missing_host_returns_failure(self):
        """Connection with no host returns success=False without calling probe."""
        conn = _make_connection(host=None, port=None)
        client = _make_admin_client(db=_make_db_session(conn=conn))
        resp = client.post(f"/api/v1/connections/{_CONN_ID}/test")
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "host or port" in resp.json()["error"]

    def test_test_nonexistent_connection_returns_404(self):
        client = _make_admin_client(db=_make_db_session(conn=None))
        missing = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        resp = client.post(f"/api/v1/connections/{missing}/test")
        assert resp.status_code == 404

    def test_test_non_admin_returns_403(self):
        client = _make_non_admin_client()
        resp = client.post(f"/api/v1/connections/{_CONN_ID}/test")
        assert resp.status_code == 403

    def test_tcp_probe_uses_pinned_ip_not_hostname(self):
        """TCP probe is called with resolved_ip, not original hostname (T51)."""
        conn = _make_connection(host="db.example.com", port=5432)
        pinned = _make_pinned_host(host="db.example.com", ip="198.51.100.42", port=5432)
        with patch("app.api.v1.routes_connections.validate_connection_host", return_value=pinned), \
             patch("app.api.v1.routes_connections._tcp_probe", return_value=(True, 10, None)) as mock_probe:
            client = _make_admin_client(db=_make_db_session(conn=conn))
            client.post(f"/api/v1/connections/{_CONN_ID}/test")

        # Must use resolved IP, not "db.example.com"
        call_kwargs = mock_probe.call_args.kwargs
        assert call_kwargs["ip"] == "198.51.100.42"
        assert call_kwargs["ip"] != "db.example.com"


# =============================================================================
# SCHEMA TESTS
# =============================================================================

class TestConnectionSchemas:
    """Pydantic v2 schema validation."""

    def test_db_type_enum_values(self):
        from app.schemas.connection import DBType
        types = {t.value for t in DBType}
        assert "postgresql" in types
        assert "mysql" in types
        assert "mssql" in types

    def test_ssl_mode_enum_values(self):
        from app.schemas.connection import SSLMode
        modes = {m.value for m in SSLMode}
        assert "require" in modes
        assert "disable" in modes
        assert "verify-full" in modes

    def test_create_request_port_out_of_range(self):
        from app.schemas.connection import ConnectionCreateRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ConnectionCreateRequest(
                name="X", db_type="postgresql", host="h", port=0,
                database_name="d", username="u", password="p",
            )

    def test_create_request_defaults(self):
        from app.schemas.connection import ConnectionCreateRequest, SSLMode
        req = ConnectionCreateRequest(
            name="X", db_type="postgresql", host="h", port=5432,
            database_name="d", username="u", password="p",
        )
        assert req.ssl_mode == SSLMode.require
        assert req.query_timeout == 30
        assert req.max_rows == 10000
        assert req.allowed_schemas == ["public"]

    def test_update_request_all_optional(self):
        from app.schemas.connection import ConnectionUpdateRequest
        req = ConnectionUpdateRequest()
        assert req.name is None
        assert req.host is None
        assert req.port is None
        assert req.username is None
        assert req.password is None

    def test_connection_response_no_credentials_field(self):
        from app.schemas.connection import ConnectionResponse
        fields = ConnectionResponse.model_fields
        assert "encrypted_credentials" not in fields
        assert "password" not in fields
        assert "username" not in fields

    def test_connection_test_response_structure(self):
        from app.schemas.connection import ConnectionTestResponse
        resp = ConnectionTestResponse(success=True, latency_ms=25, resolved_ip="1.2.3.4")
        assert resp.success is True
        assert resp.latency_ms == 25
        assert resp.error is None

    def test_query_timeout_max_enforced(self):
        from app.schemas.connection import ConnectionCreateRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ConnectionCreateRequest(
                name="X", db_type="postgresql", host="h", port=5432,
                database_name="d", username="u", password="p",
                query_timeout=999,
            )
            