"""
Smart BI Agent — Integration Schemas
Architecture v3.1 | Layer 4 | Threats: T29 (unverified platform mapping),
                                        T30 (WhatsApp/Slack replay attack),
                                        T21 (GDPR erasure)

Schemas for three integration sub-systems:
  1. Inbound webhooks  — POST /integrations/inbound/{platform_type}
  2. Mapping verification — POST /integrations/verify
  3. GDPR erasure      — POST /integrations/gdpr/erasure  (admin only)

Design notes:
  - Inbound webhook bodies are intentionally loose (dict[str, Any]) because
    each platform uses a different payload shape.  Platform-specific parsing
    is done in the route layer.  The only universal required field is a
    message_id for deduplication.
  - Signature bytes are passed via HTTP headers (X-Slack-Signature,
    X-Hub-Signature-256, etc.) and are validated at the route layer before
    any body parsing occurs (T30).
  - GDPRErasureRequest targets a user_id.  All audit log rows for that user
    have their `question` field replaced with the redaction sentinel.
    The metadata (timestamp, status, row_count) is preserved for compliance.
  - GDPR erasure is irreversible and requires admin role.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

# Platforms that support inbound webhooks in Phase 2 route scaffolding.
# Phase 6 adds full per-platform parsers; the route layer dispatches on this set.
INBOUND_PLATFORM_TYPES = frozenset(
    {"slack", "whatsapp", "teams", "jira", "clickup", "webhook"}
)

# Sentinel written into redacted audit log rows (T21)
GDPR_REDACTION_SENTINEL = "[REDACTED — GDPR erasure]"

# Maximum replay age in seconds (T30)
WEBHOOK_MAX_AGE_SECONDS = 300  # 5 minutes


# =============================================================================
# Inbound webhook schemas
# =============================================================================

class InboundWebhookResponse(BaseModel):
    """Unified acknowledgement returned to all inbound platforms."""
    accepted: bool
    message: str
    platform_type: str
    deduplicated: bool = False  # True if message was a duplicate (already processed)


# =============================================================================
# Mapping verification schemas
# =============================================================================

class MappingVerifyRequest(BaseModel):
    """
    POST /integrations/verify — body.

    The platform user sends a verification token (received in a DM) back to
    the integration handler to confirm ownership.  On success the mapping's
    is_verified field is set to True and verified_at is stamped (T29).
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    token: str = Field(..., min_length=6, max_length=128, description="Verification token from DM")
    platform_type: str = Field(..., description="Platform that issued the token")
    platform_user_id: str = Field(
        ..., min_length=1, max_length=255,
        description="Platform-native user ID of the sender",
    )


class MappingVerifyResponse(BaseModel):
    """Result of a verification attempt."""
    verified: bool
    message: str
    platform_type: str
    internal_user_id: Optional[str] = None


# =============================================================================
# GDPR erasure schemas
# =============================================================================

class GDPRErasureRequest(BaseModel):
    """
    POST /integrations/gdpr/erasure — body.  Admin only.

    Redacts question text from all audit log rows belonging to the target user.
    Preserves all metadata columns for compliance reporting.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    user_id: str = Field(..., description="UUID of the user whose question text should be redacted")
    reason: str = Field(
        ..., min_length=5, max_length=500,
        description="Reason for erasure (retained in admin audit log)",
    )


class GDPRErasureResponse(BaseModel):
    """Confirmation of GDPR erasure."""
    user_id: str
    rows_redacted: int
    sentinel: str
    erased_by: str
    erased_at: str
    reason: str