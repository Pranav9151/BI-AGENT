"""
Smart BI Agent — Component 5 Tests
Tests: structured logger (redaction + injection), audit chain, exception hierarchy, handlers.
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


# =============================================================================
# structured.py — Redaction
# =============================================================================

class TestRedaction:
    """T33: sensitive fields must never appear in logs."""

    def _run_processor(self, event_dict: dict) -> dict:
        from app.logging.structured import redact_sensitive_fields
        return redact_sensitive_fields(None, "info", event_dict.copy())  # type: ignore

    def test_password_redacted(self):
        result = self._run_processor({"password": "supersecret123", "event": "login"})
        assert result["password"] == "[REDACTED]"

    def test_api_key_redacted(self):
        result = self._run_processor({"api_key": "sk-abc123xyz"})
        assert result["api_key"] == "[REDACTED]"

    def test_token_redacted(self):
        result = self._run_processor({"token": "Bearer eyJhb..."})
        assert result["token"] == "[REDACTED]"

    def test_secret_redacted(self):
        result = self._run_processor({"client_secret": "very-secret"})
        assert result["client_secret"] == "[REDACTED]"

    def test_partial_match_redacted(self):
        # Field name containing "password" substring
        result = self._run_processor({"hashed_password": "bcrypt..."})
        assert result["hashed_password"] == "[REDACTED]"

    def test_safe_fields_preserved(self):
        result = self._run_processor({
            "user_id": "abc-123",
            "row_count": 42,
            "event": "query.executed",
        })
        assert result["user_id"] == "abc-123"
        assert result["row_count"] == 42

    def test_event_field_not_blanket_redacted(self):
        # Event name itself shouldn't be redacted unless it contains a secret value
        result = self._run_processor({"event": "user.password_changed"})
        assert "password" in result["event"]  # event name preserved

    def test_event_field_inline_secret_redacted(self):
        # e.g. accidental: log.info(f"token={token}")
        result = self._run_processor({"event": "debug token=sk-abc123"})
        assert "sk-abc123" not in result["event"]
        assert "[REDACTED]" in result["event"]

    def test_multiple_sensitive_fields(self):
        result = self._run_processor({
            "password": "pw",
            "api_key": "key",
            "user": "alice",
        })
        assert result["password"] == "[REDACTED]"
        assert result["api_key"] == "[REDACTED]"
        assert result["user"] == "alice"


# =============================================================================
# structured.py — Log Injection Prevention
# =============================================================================

class TestLogInjection:
    """T34: user-controlled strings must not break log structure."""

    def _run_processor(self, event_dict: dict) -> dict:
        from app.logging.structured import prevent_log_injection
        return prevent_log_injection(None, "info", event_dict.copy())  # type: ignore

    def test_newline_escaped(self):
        result = self._run_processor({"event": "user said\ninjected log line"})
        assert "\n" not in result["event"]
        assert "\\n" in result["event"]

    def test_carriage_return_escaped(self):
        result = self._run_processor({"event": "value\rwith cr"})
        assert "\r" not in result["event"]
        assert "\\r" in result["event"]

    def test_tab_escaped(self):
        result = self._run_processor({"question": "query\twith\ttabs"})
        assert "\t" not in result["question"]
        assert "\\t" in result["question"]

    def test_control_chars_stripped(self):
        # NULL byte and other control chars
        result = self._run_processor({"event": "hello\x00world\x07bell"})
        assert "\x00" not in result["event"]
        assert "\x07" not in result["event"]
        assert "helloworld" in result["event"].replace("bell", "")

    def test_json_injection_attempt(self):
        # Attacker tries to inject a fake JSON log line
        payload = 'normal message\n{"level": "info", "event": "fake_admin_action"}'
        result = self._run_processor({"event": payload})
        assert "\n" not in result["event"]

    def test_safe_unicode_preserved(self):
        result = self._run_processor({"event": "مرحبا بالعالم 你好世界"})
        assert "مرحبا" in result["event"]
        assert "你好" in result["event"]

    def test_backslash_escaped(self):
        result = self._run_processor({"event": "path\\to\\file"})
        # Backslashes should be escaped to double-backslash
        assert "\\\\" in result["event"]

    def test_list_values_escaped(self):
        result = self._run_processor({"tags": ["safe", "with\nnewline"]})
        assert "\n" not in result["tags"][1]
        assert "\\n" in result["tags"][1]


# =============================================================================
# audit.py — Hash Chain
# =============================================================================

class TestAuditChain:
    """T20: hash chain must detect any modification."""

    def _make_entry(self, **kwargs) -> "AuditLog":
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
        expected = hashlib.sha256(b"GENESIS_BLOCK_SMART_BI_AGENT_V3.1").hexdigest()
        assert GENESIS_HASH == expected

    def test_compute_hash_deterministic(self):
        from app.logging.audit import compute_hash
        entry = self._make_entry()
        h1 = compute_hash(entry)
        h2 = compute_hash(entry)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex = 64 chars

    def test_hash_changes_when_question_changes(self):
        from app.logging.audit import compute_hash
        e1 = self._make_entry(question="show revenue")
        e2 = self._make_entry(question="drop table users")
        e2.id = e1.id  # same id, different question
        assert compute_hash(e1) != compute_hash(e2)

    def test_canonical_output_is_valid_json(self):
        from app.logging.audit import _canonical
        entry = self._make_entry()
        canonical_bytes = _canonical(entry)
        parsed = json.loads(canonical_bytes.decode())
        assert "question" in parsed
        assert "execution_status" in parsed

    def test_canonical_is_sorted_keys(self):
        from app.logging.audit import _canonical
        entry = self._make_entry()
        raw = _canonical(entry).decode()
        # Keys must be in alphabetical order (sort_keys=True)
        keys = re.findall(r'"(\w+)":', raw)
        assert keys == sorted(keys)


# =============================================================================
# exceptions.py — Exception Hierarchy
# =============================================================================

class TestExceptionHierarchy:
    """All exceptions must have correct status codes and error codes."""

    def test_base_exception_defaults(self):
        from app.errors.exceptions import SmartBIException
        exc = SmartBIException()
        assert exc.status_code == 500
        assert exc.error_code == "INTERNAL_ERROR"
        assert exc.message == "An unexpected error occurred."

    def test_invalid_credentials_is_401(self):
        from app.errors.exceptions import InvalidCredentialsError
        exc = InvalidCredentialsError()
        assert exc.status_code == 401
        assert exc.error_code == "INVALID_CREDENTIALS"
        # Must NOT say "user not found" — T10 enumeration prevention
        assert "not found" not in exc.message.lower()

    def test_account_locked_is_423(self):
        from app.errors.exceptions import AccountLockedError
        exc = AccountLockedError()
        assert exc.status_code == 423

    def test_rate_limit_carries_retry_after(self):
        from app.errors.exceptions import RateLimitError
        exc = RateLimitError(retry_after=60)
        assert exc.status_code == 429
        assert exc.retry_after == 60

    def test_resource_ownership_is_403_not_404(self):
        # Must be 403, not 404 — don't reveal whether resource exists
        from app.errors.exceptions import ResourceOwnershipError
        exc = ResourceOwnershipError()
        assert exc.status_code == 403

    def test_prompt_injection_is_400(self):
        from app.errors.exceptions import PromptInjectionError
        exc = PromptInjectionError()
        assert exc.status_code == 400

    def test_llm_budget_is_429(self):
        from app.errors.exceptions import LLMBudgetExceededError
        exc = LLMBudgetExceededError()
        assert exc.status_code == 429

    def test_ssrf_error_is_400(self):
        from app.errors.exceptions import SSRFError
        exc = SSRFError()
        assert exc.status_code == 400

    def test_detail_is_not_message(self):
        from app.errors.exceptions import SmartBIException
        exc = SmartBIException(
            message="Safe client message",
            detail="Internal: stack trace here, SELECT * FROM secret_table",
        )
        assert exc.message == "Safe client message"
        assert exc.detail != exc.message

    def test_extra_context_stored(self):
        from app.errors.exceptions import LLMProviderError
        exc = LLMProviderError(extra={"provider": "openai", "attempt": 3})
        assert exc.extra["provider"] == "openai"

    def test_inheritance_chain(self):
        from app.errors.exceptions import (
            SmartBIException,
            AuthenticationError,
            InvalidCredentialsError,
        )
        exc = InvalidCredentialsError()
        assert isinstance(exc, AuthenticationError)
        assert isinstance(exc, SmartBIException)
        assert isinstance(exc, Exception)

    def test_get_status_code_helper(self):
        from app.errors.exceptions import get_status_code, RateLimitError
        exc = RateLimitError()
        assert get_status_code(exc) == 429
        assert get_status_code(ValueError("something")) == 500


# =============================================================================
# handlers.py — Response envelope
# =============================================================================

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

        exc = InvalidCredentialsError()
        request = self._make_request()
        response = await smartbi_exception_handler(request, exc)

        assert response.status_code == 401
        body = json.loads(response.body)
        assert body["error"]["code"] == "INVALID_CREDENTIALS"
        assert "message" in body["error"]

    @pytest.mark.asyncio
    async def test_no_internal_details_in_response(self):
        from app.errors.exceptions import SmartBIException
        from app.errors.handlers import smartbi_exception_handler

        exc = SmartBIException(
            message="Safe message",
            detail="SELECT * FROM users WHERE id=1; DROP TABLE users;",
        )
        request = self._make_request()
        response = await smartbi_exception_handler(request, exc)

        body = json.loads(response.body)
        response_str = json.dumps(body)
        # SQL must NOT appear in response
        assert "DROP TABLE" not in response_str
        assert "SELECT" not in response_str

    @pytest.mark.asyncio
    async def test_rate_limit_sets_retry_after_header(self):
        from app.errors.exceptions import RateLimitError
        from app.errors.handlers import smartbi_exception_handler

        exc = RateLimitError(retry_after=60)
        request = self._make_request()
        response = await smartbi_exception_handler(request, exc)

        assert response.status_code == 429
        assert response.headers.get("retry-after") == "60"

    @pytest.mark.asyncio
    async def test_account_locked_sets_retry_after(self):
        from app.errors.exceptions import AccountLockedError
        from app.errors.handlers import smartbi_exception_handler

        exc = AccountLockedError()
        request = self._make_request()
        response = await smartbi_exception_handler(request, exc)

        assert response.status_code == 423
        assert response.headers.get("retry-after") == "1800"

    @pytest.mark.asyncio
    async def test_request_id_in_response(self):
        from app.errors.exceptions import ResourceNotFoundError
        from app.errors.handlers import smartbi_exception_handler

        rid = "test-request-id-123"
        exc = ResourceNotFoundError()
        request = self._make_request(request_id=rid)
        response = await smartbi_exception_handler(request, exc)

        body = json.loads(response.body)
        assert body["error"]["request_id"] == rid

    @pytest.mark.asyncio
    async def test_unhandled_exception_returns_500(self):
        from app.errors.handlers import unhandled_exception_handler

        exc = RuntimeError("Something blew up internally")
        request = self._make_request()
        response = await unhandled_exception_handler(request, exc)

        assert response.status_code == 500
        body = json.loads(response.body)
        assert body["error"]["code"] == "INTERNAL_ERROR"
        # Must NOT echo the internal error message
        assert "blew up" not in json.dumps(body)

    @pytest.mark.asyncio
    async def test_validation_handler_sanitizes_field_values(self):
        from fastapi.exceptions import RequestValidationError
        from pydantic import ValidationError as PydanticValidationError
        from app.errors.handlers import validation_exception_handler

        # Build a minimal RequestValidationError
        errors = [
            {
                "loc": ("body", "email"),
                "msg": "value is not a valid email address",
                "type": "value_error.email",
                "input": "user_secret_data_here",  # this must NOT appear in response
            }
        ]

        class _FakeBody:
            errors_list = errors

        exc = MagicMock(spec=RequestValidationError)
        exc.errors.return_value = errors
        request = self._make_request()
        response = await validation_exception_handler(request, exc)

        assert response.status_code == 422
        body = json.loads(response.body)
        response_str = json.dumps(body)
        assert "user_secret_data_here" not in response_str
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert "fields" in body["error"]

    @pytest.mark.asyncio
    async def test_http_exception_wrapped_in_envelope(self):
        from starlette.exceptions import HTTPException as StarletteHTTPException
        from app.errors.handlers import http_exception_handler

        exc = StarletteHTTPException(status_code=404, detail="Not Found")
        request = self._make_request()
        response = await http_exception_handler(request, exc)

        assert response.status_code == 404
        body = json.loads(response.body)
        assert body["error"]["code"] == "NOT_FOUND"
