"""
Smart BI Agent — Exception Hierarchy
Architecture v3.1 | Cross-cutting | Threats: T10 (info leakage), T34

PURPOSE:
    A typed exception hierarchy that lets FastAPI exception handlers return
    precise HTTP responses without leaking internal details to clients.

DESIGN PRINCIPLES:

    1. Every exception carries an `error_code` (machine-readable string).
       Frontend uses error_code to display the right localized message.
       The `detail` field is for logging ONLY — never returned to client.

    2. HTTP status codes are set on the exception class, not in route handlers.
       This prevents inconsistency (e.g., auth errors always return 401, not
       500 when a dev forgets).

    3. T10 — Information Disclosure:
       The handlers in errors/handlers.py return ONLY: error_code, message.
       Internal details (stack trace, SQL, model names) NEVER reach the client.
       They are captured in structured logs with the request_id for correlation.

    4. Security exceptions (auth, rate limit, validation) are intentionally
       vague in their client-facing messages to prevent enumeration attacks.
       E.g., "Invalid credentials" — not "User not found" vs "Wrong password".

HIERARCHY:
    SmartBIException (base)
    ├── AuthenticationError (401)
    │   ├── InvalidCredentialsError
    │   ├── TokenExpiredError
    │   ├── TokenInvalidError
    │   ├── TokenBlacklistedError
    │   └── MFARequiredError
    ├── AuthorizationError (403)
    │   ├── InsufficientPermissionsError
    │   ├── ResourceOwnershipError
    │   └── AdminRequiredError
    ├── ValidationError (422)
    │   ├── InputTooLongError
    │   ├── PromptInjectionError
    │   └── SQLValidationError
    ├── RateLimitError (429)
    ├── AccountLockedError (423)
    ├── ResourceNotFoundError (404)
    ├── ConflictError (409)
    ├── ProviderError (502)
    │   ├── LLMProviderError
    │   └── DatabaseConnectionError
    ├── SSRFError (400)
    ├── EncryptionError (500)
    └── AuditError (500)
"""

from __future__ import annotations

from typing import Any


# =============================================================================
# Base Exception
# =============================================================================

class SmartBIException(Exception):
    """
    Base exception for all Smart BI Agent application errors.

    Attributes:
        error_code: Machine-readable code for frontend localisation.
                    Format: SCREAMING_SNAKE_CASE, e.g. "INVALID_CREDENTIALS"
        message:    Client-safe human-readable message (no internal details).
        detail:     Internal detail for structured logging ONLY.
                    NEVER returned to client.
        status_code: HTTP status code for the response.
        extra:      Arbitrary additional data for logging context.
    """

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"
    default_message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        detail: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.detail = detail  # internal only — goes to structured log
        self.extra = extra or {}
        super().__init__(self.message)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"error_code={self.error_code!r}, "
            f"message={self.message!r}"
            f")"
        )


# =============================================================================
# 401 — Authentication Errors
# Intentionally vague client messages to prevent user enumeration (T10).
# =============================================================================

class AuthenticationError(SmartBIException):
    """Base for all authentication failures."""
    status_code = 401
    error_code = "AUTHENTICATION_ERROR"
    default_message = "Authentication failed."


class InvalidCredentialsError(AuthenticationError):
    """
    Wrong username/password combination.
    Message is intentionally identical to UserNotFoundError — T10.
    """
    error_code = "INVALID_CREDENTIALS"
    default_message = "Invalid credentials."


class TokenExpiredError(AuthenticationError):
    """JWT access token has passed its exp claim."""
    error_code = "TOKEN_EXPIRED"
    default_message = "Your session has expired. Please log in again."


class TokenInvalidError(AuthenticationError):
    """JWT signature invalid, malformed, or algorithm mismatch (T4)."""
    error_code = "TOKEN_INVALID"
    default_message = "Invalid authentication token."


class TokenBlacklistedError(AuthenticationError):
    """JWT JTI is on the logout blacklist (Redis DB 1)."""
    error_code = "TOKEN_REVOKED"
    default_message = "This session has been revoked. Please log in again."


class MFARequiredError(AuthenticationError):
    """
    Admin account requires TOTP verification.
    Returns 401 (not 403) because the user is not yet fully authenticated.
    """
    error_code = "MFA_REQUIRED"
    default_message = "Multi-factor authentication is required."


class MFAInvalidError(AuthenticationError):
    """Provided TOTP code is incorrect or expired."""
    error_code = "MFA_INVALID"
    default_message = "Invalid or expired MFA code."


# =============================================================================
# 423 — Account Locked
# Separate from 401 so clients can show a different UI (support contact).
# =============================================================================

class AccountLockedError(SmartBIException):
    """
    Account locked after exceeding failed login attempts (T8).
    10 failures → 30-minute lockout + admin notification.
    """
    status_code = 423  # HTTP 423 Locked (WebDAV, but semantically correct)
    error_code = "ACCOUNT_LOCKED"
    default_message = (
        "This account has been temporarily locked due to repeated failed login "
        "attempts. Please try again later or contact your administrator."
    )


# =============================================================================
# 403 — Authorization Errors
# =============================================================================

class AuthorizationError(SmartBIException):
    """Base for all authorization failures."""
    status_code = 403
    error_code = "AUTHORIZATION_ERROR"
    default_message = "You do not have permission to perform this action."


class InsufficientPermissionsError(AuthorizationError):
    """User lacks the required role/department permission for this resource."""
    error_code = "INSUFFICIENT_PERMISSIONS"
    default_message = "You do not have permission to access this resource."


class ResourceOwnershipError(AuthorizationError):
    """
    User is trying to access a resource they don't own (IDOR prevention).
    Returns 403, not 404, to avoid leaking resource existence.
    """
    error_code = "RESOURCE_OWNERSHIP"
    default_message = "You do not have permission to access this resource."


class AdminRequiredError(AuthorizationError):
    """Endpoint requires admin role."""
    error_code = "ADMIN_REQUIRED"
    default_message = "Administrator access required."


class RegistrationClosedError(AuthorizationError):
    """
    New user registration is disabled (closed by default per v3.1).
    Contact admin for an invite.
    """
    error_code = "REGISTRATION_CLOSED"
    default_message = "Account registration requires administrator approval."


# =============================================================================
# 400/422 — Input Validation Errors
# =============================================================================

class ValidationError(SmartBIException):
    """Base for input validation failures."""
    status_code = 422
    error_code = "VALIDATION_ERROR"
    default_message = "Invalid input."


class InputTooLongError(ValidationError):
    """Question text exceeds 2000 character limit."""
    error_code = "INPUT_TOO_LONG"
    default_message = "Input exceeds the maximum allowed length."


class PromptInjectionError(ValidationError):
    """
    Input matched a prompt injection pattern (T4).
    Status 400, not 422 — the structure is valid but the intent is malicious.
    """
    status_code = 400
    error_code = "PROMPT_INJECTION_DETECTED"
    default_message = "Your request contains patterns that are not allowed."


class SQLValidationError(ValidationError):
    """
    Generated SQL failed the 10-step validation pipeline (T5–T7).
    Message is sanitized — never include the raw SQL in the response.
    """
    status_code = 400
    error_code = "SQL_VALIDATION_FAILED"
    default_message = "The generated query could not be validated."


class ContentTypeError(ValidationError):
    """POST request missing or incorrect Content-Type header."""
    status_code = 415
    error_code = "UNSUPPORTED_MEDIA_TYPE"
    default_message = "Unsupported media type."


class WebSocketMessageTooLargeError(ValidationError):
    """WebSocket message exceeds 64KB limit."""
    status_code = 400
    error_code = "WS_MESSAGE_TOO_LARGE"
    default_message = "WebSocket message exceeds the maximum allowed size."


# =============================================================================
# 429 — Rate Limiting
# =============================================================================

class RateLimitError(SmartBIException):
    """
    Request rate limit exceeded (Redis DB 1).
    Differentiated limits: LLM=10/min, schema=60/min, auth=10/min, export=5/min.
    """
    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"
    default_message = "Too many requests. Please slow down and try again."

    def __init__(
        self,
        retry_after: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.retry_after = retry_after  # seconds until reset — used in Retry-After header


# =============================================================================
# 404 — Not Found
# =============================================================================

class ResourceNotFoundError(SmartBIException):
    """
    Requested resource does not exist.
    NOTE: Never use this for ownership failures — use ResourceOwnershipError (403)
    to avoid leaking existence of private resources.
    """
    status_code = 404
    error_code = "NOT_FOUND"
    default_message = "The requested resource was not found."


# =============================================================================
# 409 — Conflict
# =============================================================================

class ConflictError(SmartBIException):
    """Resource already exists or state conflict."""
    status_code = 409
    error_code = "CONFLICT"
    default_message = "A conflict occurred with the current state of the resource."


class DuplicateResourceError(ConflictError):
    """Attempt to create a resource that already exists (e.g., duplicate username)."""
    error_code = "DUPLICATE_RESOURCE"
    default_message = "A resource with this identifier already exists."


# =============================================================================
# 400 — Network / SSRF Security
# =============================================================================

class SSRFError(SmartBIException):
    """
    Request blocked by SSRF guard (T3) or DNS pinner.
    The target host resolved to a private/loopback/reserved IP or
    failed DNS pinning consistency check.
    """
    status_code = 400
    error_code = "CONNECTION_BLOCKED"
    default_message = "The target host is not allowed."


class DNSPinningError(SSRFError):
    """DNS resolution returned a different IP than the pinned value (rebinding attempt)."""
    error_code = "DNS_REBINDING_DETECTED"
    default_message = "The target host failed DNS validation."


# =============================================================================
# 502/503 — Upstream Provider Errors
# =============================================================================

class ProviderError(SmartBIException):
    """Base for failures in external providers (LLM, database connections)."""
    status_code = 502
    error_code = "PROVIDER_ERROR"
    default_message = "An upstream service is temporarily unavailable."


class LLMProviderError(ProviderError):
    """
    LLM provider API call failed or all providers in the fallback chain failed.
    Details (model name, response body) go to structured log ONLY — T10.
    """
    error_code = "LLM_PROVIDER_ERROR"
    default_message = "The AI service is temporarily unavailable. Please try again."


class LLMBudgetExceededError(ProviderError):
    """User or tenant daily token budget exhausted."""
    status_code = 429
    error_code = "LLM_BUDGET_EXCEEDED"
    default_message = "Your AI usage quota for today has been reached."


class DatabaseConnectionError(ProviderError):
    """Could not connect to a user-configured data source."""
    error_code = "DATABASE_CONNECTION_ERROR"
    default_message = "Could not connect to the data source."


class QueryExecutionError(ProviderError):
    """SQL executed but failed at the data source level."""
    error_code = "QUERY_EXECUTION_ERROR"
    default_message = "The query could not be executed."


class QueryResultTooLargeError(SmartBIException):
    """Result exceeds row (10K) or byte (50MB) limit."""
    status_code = 400
    error_code = "RESULT_TOO_LARGE"
    default_message = "The query result exceeds the allowed size limit."


# =============================================================================
# 500 — Internal / Security Infrastructure Errors
# =============================================================================

class EncryptionError(SmartBIException):
    """
    Key derivation, encryption, or decryption failure.
    The specific cause is logged internally — T10 ensures it never reaches client.
    """
    status_code = 500
    error_code = "ENCRYPTION_ERROR"
    default_message = "A security operation failed. Please contact your administrator."


class AuditError(SmartBIException):
    """Audit log write or integrity check failure."""
    status_code = 500
    error_code = "AUDIT_ERROR"
    default_message = "An internal logging error occurred."


class ConfigurationError(SmartBIException):
    """
    Application misconfiguration detected at runtime.
    E.g., missing required env var, invalid CORS setting.
    """
    status_code = 500
    error_code = "CONFIGURATION_ERROR"
    default_message = "The application is misconfigured. Please contact your administrator."


class SchedulerError(SmartBIException):
    """Scheduled query job failed to execute or reload."""
    status_code = 500
    error_code = "SCHEDULER_ERROR"
    default_message = "A scheduled task encountered an error."


class NotificationError(SmartBIException):
    """Notification delivery to Teams/Slack/WhatsApp/etc. failed."""
    status_code = 502
    error_code = "NOTIFICATION_ERROR"
    default_message = "The notification could not be delivered."


class WebhookSignatureError(SmartBIException):
    """
    Inbound webhook signature verification failed (T27).
    Returns 401 to signal rejection to the sender.
    """
    status_code = 401
    error_code = "WEBHOOK_SIGNATURE_INVALID"
    default_message = "Webhook signature verification failed."


class WebhookReplayError(SmartBIException):
    """Inbound webhook timestamp > 5 minutes old (replay attack — T28)."""
    status_code = 401
    error_code = "WEBHOOK_REPLAY_DETECTED"
    default_message = "Webhook timestamp is too old."


# =============================================================================
# Convenience: map exception class → HTTP status for quick lookup
# =============================================================================

def get_status_code(exc: Exception) -> int:
    """Return the HTTP status code for any exception type."""
    if isinstance(exc, SmartBIException):
        return exc.status_code
    return 500
