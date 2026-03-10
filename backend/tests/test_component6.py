"""
Smart BI Agent — Component 6 Tests
Tests: middleware (request_id, security_headers, rate_limiter), dependencies, main app factory.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response
from starlette.testclient import TestClient as StarletteClient


# =============================================================================
# Request ID Middleware
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
        client = TestClient(self._make_app())
        resp = client.get("/test")
        assert resp.status_code == 200
        rid = resp.json()["request_id"]
        # Should be a valid UUID
        uuid.UUID(rid)  # raises ValueError if not valid UUID

    def test_request_id_in_response_header(self):
        client = TestClient(self._make_app())
        resp = client.get("/test")
        assert "x-request-id" in resp.headers
        uuid.UUID(resp.headers["x-request-id"])

    def test_request_ids_are_unique(self):
        client = TestClient(self._make_app())
        ids = {client.get("/test").headers["x-request-id"] for _ in range(10)}
        assert len(ids) == 10  # All unique

    def test_client_request_id_header_ignored(self):
        """Client-supplied X-Request-ID must be ignored — T34 log injection."""
        client = TestClient(self._make_app())
        resp = client.get("/test", headers={"X-Request-ID": "attacker-controlled-value"})
        # Response header must NOT be the attacker's value
        assert resp.headers["x-request-id"] != "attacker-controlled-value"
        # Must be a valid UUID (our generated one)
        uuid.UUID(resp.headers["x-request-id"])


# =============================================================================
# Security Headers Middleware
# =============================================================================

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
        client = TestClient(self._make_app())
        resp = client.get("/test")
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_x_content_type_nosniff(self):
        client = TestClient(self._make_app())
        resp = client.get("/test")
        assert resp.headers.get("x-content-type-options") == "nosniff"

    def test_xss_protection_disabled(self):
        """Modern: disable broken XSS filter, rely on CSP."""
        client = TestClient(self._make_app())
        resp = client.get("/test")
        assert resp.headers.get("x-xss-protection") == "0"

    def test_csp_header_present(self):
        client = TestClient(self._make_app())
        resp = client.get("/test")
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "object-src 'none'" in csp

    def test_referrer_policy(self):
        client = TestClient(self._make_app())
        resp = client.get("/test")
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy_present(self):
        client = TestClient(self._make_app())
        resp = client.get("/test")
        assert "permissions-policy" in resp.headers

    def test_server_header_removed(self):
        """Don't leak server/stack info."""
        client = TestClient(self._make_app())
        resp = client.get("/test")
        # Server header should not be present or should not reveal stack
        server = resp.headers.get("server", "")
        assert "python" not in server.lower()
        assert "uvicorn" not in server.lower()


# =============================================================================
# Rate Limiter Middleware
# =============================================================================

class TestRateLimiterEndpointClassification:
    """Endpoint classification must map paths to correct limits."""

    def test_auth_endpoint_classified(self):
        from app.middleware.rate_limiter import _classify_endpoint
        from app.config import get_settings
        settings = get_settings()
        limit, cls = _classify_endpoint("/api/v1/auth/login", settings)
        assert cls == "auth"
        assert limit == settings.RATE_LIMIT_AUTH_PER_MINUTE

    def test_query_endpoint_classified(self):
        from app.middleware.rate_limiter import _classify_endpoint
        from app.config import get_settings
        settings = get_settings()
        limit, cls = _classify_endpoint("/api/v1/query", settings)
        assert cls == "llm"
        assert limit == settings.RATE_LIMIT_LLM_PER_MINUTE

    def test_export_endpoint_classified(self):
        from app.middleware.rate_limiter import _classify_endpoint
        from app.config import get_settings
        settings = get_settings()
        limit, cls = _classify_endpoint("/api/v1/export/csv", settings)
        assert cls == "export"
        assert limit == settings.RATE_LIMIT_EXPORT_PER_MINUTE

    def test_schema_endpoint_classified(self):
        from app.middleware.rate_limiter import _classify_endpoint
        from app.config import get_settings
        settings = get_settings()
        limit, cls = _classify_endpoint("/api/v1/schema/introspect", settings)
        assert cls == "schema"
        assert limit == settings.RATE_LIMIT_SCHEMA_PER_MINUTE

    def test_default_endpoint_classified(self):
        from app.middleware.rate_limiter import _classify_endpoint
        from app.config import get_settings
        settings = get_settings()
        limit, cls = _classify_endpoint("/api/v1/users", settings)
        assert cls == "default"
        assert limit == settings.RATE_LIMIT_DEFAULT_PER_MINUTE

    def test_client_ip_extraction_xff(self):
        """XFF header → use first IP."""
        from app.middleware.rate_limiter import _get_client_ip
        request = MagicMock()
        request.headers = {"x-forwarded-for": "1.2.3.4, 10.0.0.1"}
        request.client = None
        ip = _get_client_ip(request)
        assert ip == "1.2.3.4"

    def test_client_ip_fallback(self):
        """No XFF → use request.client.host."""
        from app.middleware.rate_limiter import _get_client_ip
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "192.168.1.1"
        ip = _get_client_ip(request)
        assert ip == "192.168.1.1"


# =============================================================================
# Exception Hierarchy integration with handlers
# =============================================================================

class TestExceptionHandlerIntegration:
    """App factory wires exception handlers correctly."""

    def _make_app(self):
        """Minimal app with handlers registered."""
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
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "retry-after" in resp.headers

    def test_unhandled_exception_returns_500_no_details(self):
        client = TestClient(self._make_app(), raise_server_exceptions=False)
        resp = client.get("/raises-unhandled")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        # Internal error message must NOT appear
        assert "boom" not in json.dumps(body)


# =============================================================================
# App factory — smoke tests
# =============================================================================

class TestAppFactory:
    """App factory creates a valid FastAPI app."""

    def test_app_is_fastapi_instance(self):
        from app.main import app
        assert isinstance(app, FastAPI)

    def test_exception_handlers_registered(self):
        from app.main import app
        from app.errors.exceptions import SmartBIException
        # FastAPI stores exception handlers in exception_handlers dict
        assert SmartBIException in app.exception_handlers

    def test_cors_middleware_in_stack(self):
        from app.main import app
        from starlette.middleware.cors import CORSMiddleware
        middleware_types = [m.cls for m in app.user_middleware]
        assert CORSMiddleware in middleware_types

    def test_request_id_middleware_in_stack(self):
        from app.main import app
        from app.middleware.request_id import RequestIDMiddleware
        middleware_types = [m.cls for m in app.user_middleware]
        assert RequestIDMiddleware in middleware_types

    def test_health_endpoint_exists(self):
        """Health endpoint must exist without auth."""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        # Will fail with 503 (no Redis in test) but endpoint exists
        resp = client.get("/health")
        assert resp.status_code in (200, 503)
        body = resp.json()
        assert "status" in body

    def test_swagger_disabled_in_test_env(self):
        """Docs should be disabled in testing env (treated as non-dev)."""
        # In testing env, APP_ENV=testing → not development → docs disabled
        from app.config import get_settings
        settings = get_settings()
        # testing env is not development, so swagger_enabled = False
        assert not settings.swagger_enabled


# =============================================================================
# Dependencies — unit tests (no live Redis/DB)
# =============================================================================

class TestDependencies:
    """Dependency functions handle edge cases correctly."""

    @pytest.mark.asyncio
    async def test_get_current_user_missing_header(self):
        """Missing Authorization header → AuthenticationError."""
        from app.dependencies import get_current_user
        from app.errors.exceptions import AuthenticationError

        request = MagicMock()
        request.url.path = "/api/v1/query"
        request.app.state = MagicMock()

        with pytest.raises(AuthenticationError):
            await get_current_user(request=request, credentials=None)

    @pytest.mark.asyncio
    async def test_require_admin_rejects_non_admin(self):
        """Non-admin user → AdminRequiredError."""
        from app.dependencies import require_admin
        from app.errors.exceptions import AdminRequiredError

        viewer = {"user_id": str(uuid.uuid4()), "role": "viewer", "email": "v@test.com"}
        with pytest.raises(AdminRequiredError):
            await require_admin(current_user=viewer)

    @pytest.mark.asyncio
    async def test_require_admin_passes_for_admin(self):
        """Admin user passes through."""
        from app.dependencies import require_admin

        admin = {"user_id": str(uuid.uuid4()), "role": "admin", "email": "a@test.com"}
        result = await require_admin(current_user=admin)
        assert result["role"] == "admin"

    @pytest.mark.asyncio
    async def test_require_analyst_rejects_viewer(self):
        """Viewer cannot execute queries."""
        from app.dependencies import require_analyst_or_above
        from app.errors.exceptions import InsufficientPermissionsError

        viewer = {"user_id": str(uuid.uuid4()), "role": "viewer", "email": "v@test.com"}
        with pytest.raises(InsufficientPermissionsError):
            await require_analyst_or_above(current_user=viewer)

    @pytest.mark.asyncio
    async def test_require_analyst_passes_for_analyst(self):
        """Analyst can execute queries."""
        from app.dependencies import require_analyst_or_above

        analyst = {"user_id": str(uuid.uuid4()), "role": "analyst", "email": "a@test.com"}
        result = await require_analyst_or_above(current_user=analyst)
        assert result["role"] == "analyst"

    @pytest.mark.asyncio
    async def test_require_analyst_passes_for_admin(self):
        """Admin also passes analyst check."""
        from app.dependencies import require_analyst_or_above

        admin = {"user_id": str(uuid.uuid4()), "role": "admin", "email": "a@test.com"}
        result = await require_analyst_or_above(current_user=admin)
        assert result["role"] == "admin"
