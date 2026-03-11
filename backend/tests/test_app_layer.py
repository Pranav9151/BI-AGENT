"""
Smart BI Agent — Application Layer Tests  (Components 5–6)
Architecture v3.1

Merged from:
  test_component5.py — structured logger (redaction + injection),
                       audit hash chain, exception hierarchy & handlers
  test_component6.py — middleware (request_id, security_headers, rate_limiter),
                       app factory, dependencies
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response


# =============================================================================
# COMPONENT 5 — Structured Logger, Audit, Exceptions, Handlers
# =============================================================================

class TestRedaction:
    """T33: sensitive fields must never appear in logs."""

    def _run(self, event_dict: dict) -> dict:
        from app.logging.structured import redact_sensitive_fields
        return redact_sensitive_fields(None, "info", event_dict.copy())  # type: ignore

    def test_password_redacted(self):
        assert self._run({"password": "supersecret123"})["password"] == "[REDACTED]"

    def test_api_key_redacted(self):
        assert self._run({"api_key": "sk-abc123xyz"})["api_key"] == "[REDACTED]"

    def test_token_redacted(self):
        assert self._run({"token": "Bearer eyJhb..."})["token"] == "[REDACTED]"

    def test_secret_redacted(self):
        assert self._run({"client_secret": "very-secret"})["client_secret"] == "[REDACTED]"

    def test_partial_match_redacted(self):
        assert self._run({"hashed_password": "bcrypt..."})["hashed_password"] == "[REDACTED]"

    def test_safe_fields_preserved(self):
        result = self._run({"user_id": "abc-123", "row_count": 42, "event": "query.executed"})
        assert result["user_id"] == "abc-123" and result["row_count"] == 42

    def test_event_field_not_blanket_redacted(self):
        assert "password" in self._run({"event": "user.password_changed"})["event"]

    def test_event_field_inline_secret_redacted(self):
        result = self._run({"event": "debug token=sk-abc123"})
        assert "sk-abc123" not in result["event"] and "[REDACTED]" in result["event"]

    def test_multiple_sensitive_fields(self):
        result = self._run({"password": "pw", "api_key": "key", "user": "alice"})
        assert result["password"] == "[REDACTED]"
        assert result["api_key"] == "[REDACTED]"
        assert result["user"] == "alice"


class TestLogInjection:
    """T34: user-controlled strings must not break log structure."""

    def _run(self, event_dict: dict) -> dict:
        from app.logging.structured import prevent_log_injection
        return prevent_log_injection(None, "info", event_dict.copy())  # type: ignore

    def test_newline_escaped(self):
        result = self._run({"event": "user said\ninjected log line"})
        assert "\n" not in result["event"] and "\\n" in result["event"]

    def test_carriage_return_escaped(self):
        result = self._run({"event": "value\rwith cr"})
        assert "\r" not in result["event"] and "\\r" in result["event"]

    def test_tab_escaped(self):
        result = self._run({"question": "query\twith\ttabs"})
        assert "\t" not in result["question"] and "\\t" in result["question"]

    def test_control_chars_stripped(self):
        result = self._run({"event": "hello\x00world\x07bell"})
        assert "\x00" not in result["event"] and "\x07" not in result["event"]

    def test_json_injection_attempt(self):
        payload = 'normal\n{"level": "info", "event": "fake_admin_action"}'
        assert "\n" not in self._run({"event": payload})["event"]

    def test_safe_unicode_preserved(self):
        result = self._run({"event": "مرحبا بالعالم 你好世界"})
        assert "مرحبا" in result["event"] and "你好" in result["event"]

    def test_backslash_escaped(self):
        assert "\\\\" in self._run({"event": "path\\to\\file"})["event"]

    def test_list_values_escaped(self):
        result = self._run({"tags": ["safe", "with\nnewline"]})
        assert "\n" not in result["tags"][1] and "\\n" in result["tags"][1]


class TestAuditChain:
    """T20: hash chain must detect any modification."""

    def _make_entry(self, **kwargs):
        from app.models.audit_log import AuditLog
        entry = AuditLog(
            id=uuid.uuid4(),
            question=kwargs.get("question", "show total revenue"),
            execution_status=kwargs.get("execution_status", "success"),
            prev_hash=kwargs.get("prev_hash"),
        )
        return entry

    def test_genesis_hash_is_deterministic(self):
        from app.logging.audit import GENESIS_HASH
        assert GENESIS_HASH == hashlib.sha256(b"GENESIS_BLOCK_SMART_BI_AGENT_V3.1").hexdigest()

    def test_compute_hash_deterministic(self):
        from app.logging.audit import compute_hash
        entry = self._make_entry()
        h = compute_hash(entry)
        assert h == compute_hash(entry) and len(h) == 64

    def test_hash_changes_when_question_changes(self):
        from app.logging.audit import compute_hash
        e1 = self._make_entry(question="show revenue")
        e2 = self._make_entry(question="drop table users")
        e2.id = e1.id
        assert compute_hash(e1) != compute_hash(e2)

    def test_canonical_output_is_valid_json(self):
        from app.logging.audit import _canonical
        parsed = json.loads(_canonical(self._make_entry()).decode())
        assert "question" in parsed and "execution_status" in parsed

    def test_canonical_is_sorted_keys(self):
        from app.logging.audit import _canonical
        raw = _canonical(self._make_entry()).decode()
        keys = re.findall(r'"(\w+)":', raw)
        assert keys == sorted(keys)


class TestExceptionHierarchy:
    """All exceptions must have correct status codes and error codes."""

    def test_base_exception_defaults(self):
        from app.errors.exceptions import SmartBIException
        exc = SmartBIException()
        assert exc.status_code == 500 and exc.error_code == "INTERNAL_ERROR"

    def test_invalid_credentials_is_401(self):
        from app.errors.exceptions import InvalidCredentialsError
        exc = InvalidCredentialsError()
        assert exc.status_code == 401 and exc.error_code == "INVALID_CREDENTIALS"
        assert "not found" not in exc.message.lower()

    def test_account_locked_is_423(self):
        from app.errors.exceptions import AccountLockedError
        assert AccountLockedError().status_code == 423

    def test_rate_limit_carries_retry_after(self):
        from app.errors.exceptions import RateLimitError
        exc = RateLimitError(retry_after=60)
        assert exc.status_code == 429 and exc.retry_after == 60

    def test_resource_ownership_is_403_not_404(self):
        from app.errors.exceptions import ResourceOwnershipError
        assert ResourceOwnershipError().status_code == 403

    def test_prompt_injection_is_400(self):
        from app.errors.exceptions import PromptInjectionError
        assert PromptInjectionError().status_code == 400

    def test_llm_budget_is_429(self):
        from app.errors.exceptions import LLMBudgetExceededError
        assert LLMBudgetExceededError().status_code == 429

    def test_ssrf_error_is_400(self):
        from app.errors.exceptions import SSRFError
        assert SSRFError().status_code == 400

    def test_detail_is_not_message(self):
        from app.errors.exceptions import SmartBIException
        exc = SmartBIException(message="Safe client message", detail="Internal: stack trace")
        assert exc.message == "Safe client message" and exc.detail != exc.message

    def test_extra_context_stored(self):
        from app.errors.exceptions import LLMProviderError
        exc = LLMProviderError(extra={"provider": "openai", "attempt": 3})
        assert exc.extra["provider"] == "openai"

    def test_inheritance_chain(self):
        from app.errors.exceptions import SmartBIException, AuthenticationError, InvalidCredentialsError
        exc = InvalidCredentialsError()
        assert isinstance(exc, AuthenticationError)
        assert isinstance(exc, SmartBIException)
        assert isinstance(exc, Exception)

    def test_get_status_code_helper(self):
        from app.errors.exceptions import get_status_code, RateLimitError
        assert get_status_code(RateLimitError()) == 429
        assert get_status_code(ValueError("something")) == 500


class TestExceptionHandlers:
    """Handlers must return correct status + envelope + no internal details."""

    def _make_request(self, path: str = "/api/v1/query", request_id: str | None = None):
        request = MagicMock()
        request.url.path = path
        request.method = "POST"
        request.state.request_id = request_id or str(uuid.uuid4())
        return request

    @pytest.mark.asyncio
    async def test_smartbi_exception_returns_correct_status(self):
        from app.errors.exceptions import InvalidCredentialsError
        from app.errors.handlers import smartbi_exception_handler
        response = await smartbi_exception_handler(self._make_request(), InvalidCredentialsError())
        assert response.status_code == 401
        assert json.loads(response.body)["error"]["code"] == "INVALID_CREDENTIALS"

    @pytest.mark.asyncio
    async def test_no_internal_details_in_response(self):
        from app.errors.exceptions import SmartBIException
        from app.errors.handlers import smartbi_exception_handler
        exc = SmartBIException(message="Safe", detail="SELECT * FROM users; DROP TABLE users;")
        body_str = json.dumps(json.loads((await smartbi_exception_handler(self._make_request(), exc)).body))
        assert "DROP TABLE" not in body_str and "SELECT" not in body_str

    @pytest.mark.asyncio
    async def test_rate_limit_sets_retry_after_header(self):
        from app.errors.exceptions import RateLimitError
        from app.errors.handlers import smartbi_exception_handler
        response = await smartbi_exception_handler(self._make_request(), RateLimitError(retry_after=60))
        assert response.status_code == 429 and response.headers.get("retry-after") == "60"

    @pytest.mark.asyncio
    async def test_account_locked_sets_retry_after(self):
        from app.errors.exceptions import AccountLockedError
        from app.errors.handlers import smartbi_exception_handler
        response = await smartbi_exception_handler(self._make_request(), AccountLockedError())
        assert response.status_code == 423 and response.headers.get("retry-after") == "1800"

    @pytest.mark.asyncio
    async def test_request_id_in_response(self):
        from app.errors.exceptions import ResourceNotFoundError
        from app.errors.handlers import smartbi_exception_handler
        rid = "test-request-id-123"
        response = await smartbi_exception_handler(self._make_request(request_id=rid), ResourceNotFoundError())
        assert json.loads(response.body)["error"]["request_id"] == rid

    @pytest.mark.asyncio
    async def test_unhandled_exception_returns_500(self):
        from app.errors.handlers import unhandled_exception_handler
        response = await unhandled_exception_handler(self._make_request(), RuntimeError("Something blew up"))
        assert response.status_code == 500
        body = json.loads(response.body)
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert "blew up" not in json.dumps(body)

    @pytest.mark.asyncio
    async def test_validation_handler_sanitizes_field_values(self):
        from app.errors.handlers import validation_exception_handler
        errors = [{"loc": ("body", "email"), "msg": "not valid", "type": "value_error", "input": "user_secret_data_here"}]
        exc = MagicMock()
        exc.errors.return_value = errors
        response = await validation_exception_handler(self._make_request(), exc)
        assert response.status_code == 422
        body = json.loads(response.body)
        assert "user_secret_data_here" not in json.dumps(body)
        assert body["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_http_exception_wrapped_in_envelope(self):
        from starlette.exceptions import HTTPException as StarletteHTTPException
        from app.errors.handlers import http_exception_handler
        response = await http_exception_handler(self._make_request(), StarletteHTTPException(status_code=404))
        assert response.status_code == 404
        assert json.loads(response.body)["error"]["code"] == "NOT_FOUND"


# =============================================================================
# COMPONENT 6 — Middleware, App Factory, Dependencies
# =============================================================================

class TestRequestIDMiddleware:
    """Every request gets a unique UUID v4 request_id."""

    def _make_app(self):
        from app.middleware.request_id import RequestIDMiddleware
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_route(request: Request):
            return {"request_id": request.state.request_id}

        return app

    def test_request_id_injected_into_state(self):
        resp = TestClient(self._make_app()).get("/test")
        assert resp.status_code == 200
        uuid.UUID(resp.json()["request_id"])  # raises ValueError if not valid UUID

    def test_request_id_in_response_header(self):
        resp = TestClient(self._make_app()).get("/test")
        uuid.UUID(resp.headers["x-request-id"])

    def test_request_ids_are_unique(self):
        client = TestClient(self._make_app())
        ids = {client.get("/test").headers["x-request-id"] for _ in range(10)}
        assert len(ids) == 10

    def test_client_request_id_header_ignored(self):
        resp = TestClient(self._make_app()).get("/test", headers={"X-Request-ID": "attacker-value"})
        assert resp.headers["x-request-id"] != "attacker-value"
        uuid.UUID(resp.headers["x-request-id"])


class TestSecurityHeadersMiddleware:
    """Security headers must be present on every response."""

    def _make_app(self):
        from app.middleware.security_headers import SecurityHeadersMiddleware
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        async def test_route():
            return {"ok": True}

        return app

    def test_x_frame_options_deny(self):
        assert TestClient(self._make_app()).get("/test").headers.get("x-frame-options") == "DENY"

    def test_x_content_type_nosniff(self):
        assert TestClient(self._make_app()).get("/test").headers.get("x-content-type-options") == "nosniff"

    def test_xss_protection_disabled(self):
        assert TestClient(self._make_app()).get("/test").headers.get("x-xss-protection") == "0"

    def test_csp_header_present(self):
        csp = TestClient(self._make_app()).get("/test").headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp

    def test_referrer_policy(self):
        assert TestClient(self._make_app()).get("/test").headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy_present(self):
        assert "permissions-policy" in TestClient(self._make_app()).get("/test").headers

    def test_server_header_removed(self):
        server = TestClient(self._make_app()).get("/test").headers.get("server", "")
        assert "python" not in server.lower() and "uvicorn" not in server.lower()


class TestRateLimiterEndpointClassification:
    """Endpoint classification must map paths to correct limits."""

    def test_auth_endpoint_classified(self):
        from app.middleware.rate_limiter import _classify_endpoint
        from app.config import get_settings
        settings = get_settings()
        limit, cls = _classify_endpoint("/api/v1/auth/login", settings)
        assert cls == "auth" and limit == settings.RATE_LIMIT_AUTH_PER_MINUTE

    def test_query_endpoint_classified(self):
        from app.middleware.rate_limiter import _classify_endpoint
        from app.config import get_settings
        settings = get_settings()
        limit, cls = _classify_endpoint("/api/v1/query", settings)
        assert cls == "llm" and limit == settings.RATE_LIMIT_LLM_PER_MINUTE

    def test_export_endpoint_classified(self):
        from app.middleware.rate_limiter import _classify_endpoint
        from app.config import get_settings
        settings = get_settings()
        limit, cls = _classify_endpoint("/api/v1/export/csv", settings)
        assert cls == "export" and limit == settings.RATE_LIMIT_EXPORT_PER_MINUTE

    def test_schema_endpoint_classified(self):
        from app.middleware.rate_limiter import _classify_endpoint
        from app.config import get_settings
        settings = get_settings()
        limit, cls = _classify_endpoint("/api/v1/schema/introspect", settings)
        assert cls == "schema" and limit == settings.RATE_LIMIT_SCHEMA_PER_MINUTE

    def test_default_endpoint_classified(self):
        from app.middleware.rate_limiter import _classify_endpoint
        from app.config import get_settings
        settings = get_settings()
        limit, cls = _classify_endpoint("/api/v1/users", settings)
        assert cls == "default" and limit == settings.RATE_LIMIT_DEFAULT_PER_MINUTE

    def test_client_ip_extraction_xff(self):
        from app.middleware.rate_limiter import _get_client_ip
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4, 10.0.0.1"}
        request.client = None
        assert _get_client_ip(request) == "1.2.3.4"

    def test_client_ip_fallback(self):
        from app.middleware.rate_limiter import _get_client_ip
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "192.168.1.1"
        assert _get_client_ip(request) == "192.168.1.1"


class TestExceptionHandlerIntegration:
    """App factory wires exception handlers correctly."""

    def _make_app(self):
        app = FastAPI()
        from app.errors.handlers import register_exception_handlers
        register_exception_handlers(app)

        @app.get("/raises-smartbi")
        async def raises_smartbi():
            from app.errors.exceptions import RateLimitError
            raise RateLimitError(retry_after=60)

        @app.get("/raises-unhandled")
        async def raises_unhandled():
            raise RuntimeError("internal boom")

        return app

    def test_smartbi_exception_returns_json_envelope(self):
        client = TestClient(self._make_app(), raise_server_exceptions=False)
        resp = client.get("/raises-smartbi")
        assert resp.status_code == 429
        assert resp.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "retry-after" in resp.headers

    def test_unhandled_exception_returns_500_no_details(self):
        client = TestClient(self._make_app(), raise_server_exceptions=False)
        resp = client.get("/raises-unhandled")
        assert resp.status_code == 500
        assert resp.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "boom" not in json.dumps(resp.json())


class TestAppFactory:
    """App factory creates a valid FastAPI app."""

    def test_app_is_fastapi_instance(self):
        from app.main import app
        assert isinstance(app, FastAPI)

    def test_exception_handlers_registered(self):
        from app.main import app
        from app.errors.exceptions import SmartBIException
        assert SmartBIException in app.exception_handlers

    def test_cors_middleware_in_stack(self):
        from app.main import app
        from starlette.middleware.cors import CORSMiddleware
        assert CORSMiddleware in [m.cls for m in app.user_middleware]

    def test_request_id_middleware_in_stack(self):
        from app.main import app
        from app.middleware.request_id import RequestIDMiddleware
        assert RequestIDMiddleware in [m.cls for m in app.user_middleware]

    def test_health_endpoint_exists(self):
        from app.main import app
        resp = TestClient(app, raise_server_exceptions=False).get("/health")
        assert resp.status_code in (200, 503)
        assert "status" in resp.json()

    def test_swagger_disabled_in_test_env(self):
        from app.config import get_settings
        assert not get_settings().swagger_enabled


class TestDependencies:
    """Dependency functions handle edge cases correctly."""

    @pytest.mark.asyncio
    async def test_get_current_user_missing_header(self):
        from app.dependencies import get_current_user
        from app.errors.exceptions import AuthenticationError
        request = MagicMock()
        request.url.path = "/api/v1/query"
        request.app.state = MagicMock()
        with pytest.raises(AuthenticationError):
            await get_current_user(request=request, credentials=None)

    @pytest.mark.asyncio
    async def test_require_admin_rejects_non_admin(self):
        from app.dependencies import require_admin
        from app.errors.exceptions import AdminRequiredError
        viewer = {"user_id": str(uuid.uuid4()), "role": "viewer", "email": "v@test.com"}
        with pytest.raises(AdminRequiredError):
            await require_admin(current_user=viewer)

    @pytest.mark.asyncio
    async def test_require_admin_passes_for_admin(self):
        from app.dependencies import require_admin
        admin = {"user_id": str(uuid.uuid4()), "role": "admin", "email": "a@test.com"}
        result = await require_admin(current_user=admin)
        assert result["role"] == "admin"

    @pytest.mark.asyncio
    async def test_require_analyst_rejects_viewer(self):
        from app.dependencies import require_analyst_or_above
        from app.errors.exceptions import InsufficientPermissionsError
        viewer = {"user_id": str(uuid.uuid4()), "role": "viewer", "email": "v@test.com"}
        with pytest.raises(InsufficientPermissionsError):
            await require_analyst_or_above(current_user=viewer)

    @pytest.mark.asyncio
    async def test_require_analyst_passes_for_analyst(self):
        from app.dependencies import require_analyst_or_above
        analyst = {"user_id": str(uuid.uuid4()), "role": "analyst", "email": "a@test.com"}
        result = await require_analyst_or_above(current_user=analyst)
        assert result["role"] == "analyst"

    @pytest.mark.asyncio
    async def test_require_analyst_passes_for_admin(self):
        from app.dependencies import require_analyst_or_above
        admin = {"user_id": str(uuid.uuid4()), "role": "admin", "email": "a@test.com"}
        result = await require_analyst_or_above(current_user=admin)
        assert result["role"] == "admin"