"""
Smart BI Agent — Notification Platform Schemas
Architecture v3.1 | Layer 4 | Threats: T6  (notification card injection),
                                        T29 (unverified platform mapping),
                                        T30 (webhook replay attack)

Request and response schemas for the Notification Platform system.

Design notes:
  - encrypted_config is NEVER returned in any response.  Only config_preview
    (first 8 chars + "...") is returned, exactly mirroring the LLM provider
    key_prefix pattern.  This prevents credential leakage from GET responses.
  - platform_type is an enum so the router can branch on it for SSRF validation
    (webhook-type platforms have a URL we must SSRF-check).
  - delivery_config inside the create/update request is the plaintext dict that
    will be JSON-encoded and encrypted with KeyPurpose.NOTIFICATION_KEYS before
    persistence.  It is never stored or logged in plaintext.
  - PlatformUserMapping schemas carry verification state (T29).  A mapping is
    considered trusted only when is_verified=True AND expires_at > now().
    The 90-day re-verification requirement is enforced by the scheduler, not here.
  - T6: format-specific escaping of notification content is done by the
    notification provider adapters (future component), not by these schemas.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Enums / constants
# =============================================================================

PLATFORM_TYPES = frozenset({
    "slack", "teams", "whatsapp", "jira", "clickup", "webhook", "email"
})

# Platform types that carry a webhook URL requiring SSRF validation
WEBHOOK_PLATFORM_TYPES = frozenset({"webhook", "teams", "jira", "clickup"})


# =============================================================================
# Request Schemas
# =============================================================================

class NotificationPlatformCreateRequest(BaseModel):
    """
    POST /api/v1/notifications — body.

    delivery_config is the plaintext credential dict.  It will be encrypted
    with KeyPurpose.NOTIFICATION_KEYS before writing to the DB.
    The shape of delivery_config is platform-specific:

      slack:   { "bot_token": "xoxb-...", "signing_secret": "..." }
      teams:   { "webhook_url": "https://...", "tenant_id": "..." }
      webhook: { "url": "https://...", "secret": "...", "headers": {} }
      email:   { "smtp_host": "...", "smtp_port": 587, "username": "...", "password": "..." }
      jira:    { "url": "https://...", "api_token": "...", "project_key": "ABC" }
      ...

    webhook_url (if applicable) is extracted from delivery_config for SSRF
    validation at the route level before encryption.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=100, description="Human-readable platform name")
    platform_type: str = Field(
        ..., description=f"Platform type — one of: {sorted(PLATFORM_TYPES)}"
    )
    delivery_config: dict[str, Any] = Field(
        ..., description="Plaintext credential dict (encrypted before storage)"
    )
    is_active: bool = Field(True)
    is_inbound_enabled: bool = Field(False, description="Accept inbound queries from this platform")
    is_outbound_enabled: bool = Field(True, description="Send reports/notifications via this platform")

    @property
    def webhook_url(self) -> Optional[str]:
        """Extract webhook URL from delivery_config for SSRF check, or None."""
        return self.delivery_config.get("url") or self.delivery_config.get("webhook_url")


class NotificationPlatformUpdateRequest(BaseModel):
    """
    PATCH /api/v1/notifications/{id} — body.  All fields optional.
    delivery_config, if supplied, replaces the entire stored config (re-encrypted).
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    delivery_config: Optional[dict[str, Any]] = None   # Re-encrypted if supplied
    is_active: Optional[bool] = None
    is_inbound_enabled: Optional[bool] = None
    is_outbound_enabled: Optional[bool] = None

    @property
    def webhook_url(self) -> Optional[str]:
        if self.delivery_config is None:
            return None
        return self.delivery_config.get("url") or self.delivery_config.get("webhook_url")


class PlatformMappingCreateRequest(BaseModel):
    """
    POST /api/v1/notifications/{id}/mappings — body.

    Links a platform-side user identifier (e.g. Slack user ID "U0123456") to
    an internal Smart BI user.  Starts unverified (T29).
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    platform_user_id: str = Field(
        ..., min_length=1, max_length=255,
        description="Platform-native user identifier (Slack user ID, Teams UPN, email, etc.)",
    )
    internal_user_id: str = Field(..., description="UUID of the Smart BI internal user")


# =============================================================================
# Response Schemas
# =============================================================================

class NotificationPlatformResponse(BaseModel):
    """
    Safe platform representation.

    encrypted_config is NEVER included.
    config_preview exposes only the first 8 characters for confirmation purposes.
    """
    model_config = ConfigDict(from_attributes=True)

    platform_id: str
    name: str
    platform_type: str
    config_preview: str                  # e.g. "xoxb-123..." — 8 chars + "..."
    is_active: bool
    is_inbound_enabled: bool
    is_outbound_enabled: bool
    created_by: Optional[str]
    created_at: str
    updated_at: str


class NotificationPlatformListResponse(BaseModel):
    """Paginated list of notification platforms."""
    platforms: list[NotificationPlatformResponse]
    total: int
    skip: int
    limit: int


class NotificationPlatformTestResponse(BaseModel):
    """POST /{id}/test — result of a connectivity probe."""
    platform_id: str
    name: str
    platform_type: str
    success: bool
    message: str


class PlatformMappingResponse(BaseModel):
    """Single platform user mapping."""
    model_config = ConfigDict(from_attributes=True)

    mapping_id: str
    platform_id: str
    platform_user_id: str
    internal_user_id: str
    is_verified: bool
    verified_at: Optional[str]
    expires_at: Optional[str]
    created_at: str


class PlatformMappingListResponse(BaseModel):
    """Paginated list of user mappings for a platform."""
    platform_id: str
    mappings: list[PlatformMappingResponse]
    total: int
    skip: int
    limit: int