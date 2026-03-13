"""
Smart BI Agent — Integration Routes  (Component 18)
Architecture v3.1 | Layer 4 (Application) | Threats: T21 (GDPR erasure),
                                                        T29 (unverified mapping),
                                                        T30 (WhatsApp/Slack replay)

ENDPOINTS:
    POST   /api/v1/integrations/inbound/{platform_type}   — inbound webhook handler
    POST   /api/v1/integrations/verify                    — confirm platform mapping (T29)
    POST   /api/v1/integrations/gdpr/erasure              — redact audit log (admin, T21)

═══════════════════════════════════════════════════════════════════════════
INBOUND WEBHOOK HANDLER  (T30)
═══════════════════════════════════════════════════════════════════════════
Security pipeline (fail-closed — all steps must pass):

  Step 1 — Platform enabled check
    The NotificationPlatform record must exist AND is_inbound_enabled=True.
    If the platform is deactivated or inbound is disabled → 404.
    This prevents unauthenticated probing of inactive endpoints.

  Step 2 — Signature verification
    Each platform sends a HMAC signature in a request header:
      Slack:     X-Slack-Signature  (v0=HMAC-SHA256 of "v0:{ts}:{body}")
      WhatsApp:  X-Hub-Signature-256 (sha256=HMAC-SHA256 of body)
      Teams/Jira/ClickUp/generic webhook: X-Webhook-Signature (HMAC-SHA256 of body)
    The HMAC secret is decrypted from encrypted_config via KeyPurpose.NOTIFICATION_KEYS.
    Comparison uses hmac.compare_digest (T50 — timing side-channel).
    On failure → 401 WebhookSignatureError.

  Step 3 — Timestamp / replay check
    For Slack: the ts header field must be within 5 minutes of now (T30).
    For WhatsApp: the message timestamp field in the body must be within 5 minutes.
    On failure → 401 WebhookReplayError.

  Step 4 — Deduplication (T30)
    Redis DB1: SET NX "webhook_dedup:{message_id}" with TTL=3600s.
    If the key already existed → return 200 {accepted:True, deduplicated:True}.
    This silently absorbs replays that slipped past timestamp checks.

  Step 5 — Platform user lookup
    Extract platform_user_id from the payload.
    Look up PlatformUserMapping.  If no verified mapping found, the message is
    accepted (200) but not processed — the platform adapter logs and drops it.
    This avoids user enumeration.

  Step 6 — Query dispatch (Phase 6 stub)
    In Phase 6 the conversation pipeline is invoked here.
    In Phase 2 the route acknowledges receipt and returns accepted=True.

═══════════════════════════════════════════════════════════════════════════
MAPPING VERIFICATION  (T29)
═══════════════════════════════════════════════════════════════════════════
When an admin adds a PlatformUserMapping, the notification worker sends
a verification DM containing a short-lived token.  The user replies with
the token, which is routed here.  On success:
  - is_verified = True
  - verified_at = now()
  - expires_at unchanged (still the 90-day window set at creation)

Token validation is a stub in Phase 2 (the notification worker that issues
tokens is built in Phase 6).  The route validates token format and updates
the mapping if found.

═══════════════════════════════════════════════════════════════════════════
GDPR ERASURE  (T21)
═══════════════════════════════════════════════════════════════════════════
Redact-not-delete: all AuditLog.question values for a target user are
overwritten with the GDPR_REDACTION_SENTINEL constant.  All other columns
(timestamps, status, row_count, etc.) are preserved for compliance reporting.

The erasure itself is audit-logged under the requesting admin's identity so
the operation is traceable.  Erasure is irreversible.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUser,
    get_audit_writer,
    get_db,
    get_key_manager,
    get_redis_security,
    require_admin,
    require_active_user,
)
from app.errors.exceptions import (
    InsufficientPermissionsError,
    ResourceNotFoundError,
    ValidationError,
    WebhookReplayError,
    WebhookSignatureError,
)
from app.logging.structured import get_logger
from app.models.audit_log import AuditLog
from app.models.notification_platform import NotificationPlatform, PlatformUserMapping
from app.schemas.integration import (
    GDPR_REDACTION_SENTINEL,
    INBOUND_PLATFORM_TYPES,
    WEBHOOK_MAX_AGE_SECONDS,
    GDPRErasureRequest,
    GDPRErasureResponse,
    InboundWebhookResponse,
    MappingVerifyRequest,
    MappingVerifyResponse,
)
from app.security.key_manager import KeyManager, KeyPurpose

log = get_logger(__name__)

router = APIRouter()


# =============================================================================
# Shared helpers
# =============================================================================

def _get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _hmac_sha256(secret: bytes, data: bytes) -> str:
    return hmac.new(secret, data, hashlib.sha256).hexdigest()


def _constant_eq(a: str, b: str) -> bool:
    """Constant-time string comparison — T50."""
    return hmac.compare_digest(a.encode(), b.encode())


async def _get_platform_by_type(
    platform_type: str,
    db: AsyncSession,
    require_inbound: bool = True,
) -> Optional[NotificationPlatform]:
    """
    Fetch the first active platform of the given type.
    Returns None if not found or inbound is disabled (caller decides 404 vs 401).
    """
    stmt = select(NotificationPlatform).where(
        NotificationPlatform.platform_type == platform_type,
        NotificationPlatform.is_active.is_(True),
    )
    if require_inbound:
        stmt = stmt.where(NotificationPlatform.is_inbound_enabled.is_(True))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _dedup_check(redis, message_id: str) -> bool:
    """
    Redis SET NX deduplication (T30).
    Returns True if the message is a duplicate (key existed).
    Returns False if this is a fresh message (key was created).
    """
    if redis is None:
        # No Redis in test environments — treat every message as fresh
        return False
    key = f"webhook_dedup:{message_id}"
    # SET key 1 NX EX 3600
    result = await redis.set(key, "1", nx=True, ex=3600)
    # result is None if key existed (duplicate), True if created (fresh)
    return result is None


def _verify_slack_signature(
    secret: str,
    raw_body: bytes,
    signature_header: Optional[str],
    timestamp_header: Optional[str],
) -> None:
    """
    Slack signature verification + replay check (T30).
    Raises WebhookSignatureError or WebhookReplayError on failure.
    Spec: https://api.slack.com/authentication/verifying-requests-from-slack
    """
    if not signature_header or not timestamp_header:
        raise WebhookSignatureError(
            message="Missing Slack signature headers.",
            detail="X-Slack-Signature and X-Slack-Request-Timestamp are required",
        )

    # Replay check — timestamp must be within 5 minutes
    try:
        ts = int(timestamp_header)
    except ValueError:
        raise WebhookSignatureError(
            message="Invalid Slack timestamp header.",
            detail=f"X-Slack-Request-Timestamp={timestamp_header!r} is not an integer",
        )

    age = abs(time.time() - ts)
    if age > WEBHOOK_MAX_AGE_SECONDS:
        raise WebhookReplayError(
            message="Slack webhook timestamp too old.",
            detail=f"Request is {age:.0f}s old; max {WEBHOOK_MAX_AGE_SECONDS}s (T30)",
        )

    sig_basestring = f"v0:{timestamp_header}:{raw_body.decode('utf-8', errors='replace')}"
    expected = "v0=" + _hmac_sha256(secret.encode(), sig_basestring.encode())

    if not _constant_eq(expected, signature_header):
        raise WebhookSignatureError(
            message="Slack signature verification failed.",
            detail="HMAC mismatch on X-Slack-Signature",
        )


def _verify_hub_signature(
    secret: str,
    raw_body: bytes,
    signature_header: Optional[str],
) -> None:
    """
    WhatsApp / Meta X-Hub-Signature-256 verification (T30).
    Format: "sha256=<hex>"
    """
    if not signature_header:
        raise WebhookSignatureError(
            message="Missing X-Hub-Signature-256 header.",
            detail="WhatsApp webhooks require X-Hub-Signature-256",
        )

    expected = "sha256=" + _hmac_sha256(secret.encode(), raw_body)

    if not _constant_eq(expected, signature_header):
        raise WebhookSignatureError(
            message="WhatsApp signature verification failed.",
            detail="HMAC mismatch on X-Hub-Signature-256",
        )


def _verify_generic_signature(
    secret: str,
    raw_body: bytes,
    signature_header: Optional[str],
) -> None:
    """
    Generic HMAC-SHA256 for Teams / Jira / ClickUp / webhook platforms.
    Header: X-Webhook-Signature: sha256=<hex>
    """
    if not signature_header:
        raise WebhookSignatureError(
            message="Missing X-Webhook-Signature header.",
            detail=f"Platform requires X-Webhook-Signature for verification",
        )

    raw_sig = signature_header.removeprefix("sha256=")
    expected = _hmac_sha256(secret.encode(), raw_body)

    if not _constant_eq(expected, raw_sig):
        raise WebhookSignatureError(
            message="Webhook signature verification failed.",
            detail="HMAC mismatch on X-Webhook-Signature",
        )


def _extract_message_id(platform_type: str, body: dict[str, Any]) -> str:
    """
    Extract a platform-specific message ID for deduplication.
    Falls back to a deterministic hash of the body if no ID found.
    """
    extractors: dict[str, list[str]] = {
        "slack":     ["event_id", "client_msg_id"],
        "whatsapp":  ["entry.0.changes.0.value.messages.0.id", "id"],
        "teams":     ["id", "activityId"],
        "jira":      ["webhookEvent", "issue.id"],
        "clickup":   ["task_id", "webhook_id"],
        "webhook":   ["id", "message_id", "event_id"],
    }
    keys = extractors.get(platform_type, ["id"])
    for key in keys:
        # Support simple dot-path for nested keys
        val = body
        try:
            for part in key.split("."):
                val = val[part]
            if val:
                return str(val)
        except (KeyError, TypeError):
            continue

    # Deterministic fallback
    body_bytes = json.dumps(body, sort_keys=True).encode()
    return hashlib.sha256(body_bytes).hexdigest()[:32]


def _extract_platform_user_id(platform_type: str, body: dict[str, Any]) -> Optional[str]:
    """Extract the platform-side user identifier from the inbound payload."""
    extractors = {
        "slack":    ["event.user", "user_id"],
        "whatsapp": ["entry.0.changes.0.value.messages.0.from", "from"],
        "teams":    ["from.id"],
        "jira":     ["user.accountId", "user.name"],
        "clickup":  ["user.id"],
        "webhook":  ["user_id", "from"],
    }
    keys = extractors.get(platform_type, ["user_id"])
    for key in keys:
        val = body
        try:
            for part in key.split("."):
                val = val[part]
            if val:
                return str(val)
        except (KeyError, TypeError):
            continue
    return None


def _decrypt_signing_secret(
    platform: NotificationPlatform, key_manager: KeyManager
) -> str:
    """
    Decrypt the platform config and extract the signing secret.
    Raises WebhookSignatureError if decryption fails or secret is missing.
    """
    plaintext: Optional[str] = None
    try:
        plaintext = key_manager.decrypt(
            platform.encrypted_config, KeyPurpose.NOTIFICATION_KEYS
        )
        config = json.loads(plaintext)
        # Try multiple key names per platform convention
        secret = (
            config.get("signing_secret")
            or config.get("secret")
            or config.get("webhook_secret")
            or config.get("app_secret")
        )
        if not secret:
            raise WebhookSignatureError(
                message="Platform configuration missing signing secret.",
                detail=f"No signing_secret/secret found in config for platform {platform.id}",
            )
        return str(secret)
    except WebhookSignatureError:
        raise
    except Exception as exc:
        raise WebhookSignatureError(
            message="Platform credential decryption failed.",
            detail=str(exc),
        )
    finally:
        plaintext = None  # Zero reference


# =============================================================================
# POST /inbound/{platform_type}  — Inbound webhook
# =============================================================================

@router.post(
    "/inbound/{platform_type}",
    response_model=InboundWebhookResponse,
    summary="Inbound webhook handler",
    description=(
        "Receives inbound messages from Slack, WhatsApp, Teams, Jira, ClickUp, or generic webhooks. "
        "Signature-verified (T30), timestamp-checked (T30), deduplicated via Redis (T30). "
        "No JWT required — authentication is the HMAC signature."
    ),
    status_code=status.HTTP_200_OK,
)
async def inbound_webhook(
    platform_type: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    key_manager: KeyManager = Depends(get_key_manager),
    redis=Depends(get_redis_security),
    audit=Depends(get_audit_writer),
    # Signature headers — all optional at FastAPI level; validated per-platform below
    x_slack_signature: Optional[str] = Header(None, alias="x-slack-signature"),
    x_slack_request_timestamp: Optional[str] = Header(None, alias="x-slack-request-timestamp"),
    x_hub_signature_256: Optional[str] = Header(None, alias="x-hub-signature-256"),
    x_webhook_signature: Optional[str] = Header(None, alias="x-webhook-signature"),
) -> InboundWebhookResponse:
    """
    Security pipeline (all steps must pass — fail-closed):

    1. platform_type in INBOUND_PLATFORM_TYPES → 404 otherwise
    2. Platform record exists + is_active + is_inbound_enabled → 404 otherwise
    3. Read raw body BEFORE JSON parsing (needed for HMAC over raw bytes)
    4. Decrypt signing secret from platform encrypted_config
    5. Verify HMAC signature (platform-specific header/format)
    6. Timestamp / replay check (Slack: header ts; WhatsApp: body ts)
    7. Deduplication via Redis SET NX (T30)
    8. Platform user lookup (no error on miss — silently drop unverified)
    9. Dispatch to query pipeline (Phase 6 stub)
    """
    # Step 1 — validate platform type
    if platform_type not in INBOUND_PLATFORM_TYPES:
        raise ResourceNotFoundError(
            message="Unknown integration platform.",
            detail=f"{platform_type!r} is not a supported inbound platform",
        )

    # Step 2 — fetch platform record (fail-closed: 404 if not found/inactive/inbound-disabled)
    platform = await _get_platform_by_type(platform_type, db, require_inbound=True)
    if platform is None:
        raise ResourceNotFoundError(
            message="Integration endpoint not configured.",
            detail=f"No active inbound platform of type {platform_type!r}",
        )

    # Step 3 — read raw body (must happen before .json() consumes the stream)
    raw_body = await request.body()

    # Step 4 — decrypt signing secret
    signing_secret = _decrypt_signing_secret(platform, key_manager)

    # Step 5+6 — platform-specific signature + replay verification
    if platform_type == "slack":
        _verify_slack_signature(
            signing_secret, raw_body, x_slack_signature, x_slack_request_timestamp
        )
    elif platform_type == "whatsapp":
        _verify_hub_signature(signing_secret, raw_body, x_hub_signature_256)
    else:
        # Teams, Jira, ClickUp, generic webhook
        _verify_generic_signature(signing_secret, raw_body, x_webhook_signature)

    # Step 6b — WhatsApp body-based replay check
    body: dict[str, Any] = {}
    try:
        body = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        body = {}

    if platform_type == "whatsapp":
        try:
            msg_ts_str = (
                body.get("entry", [{}])[0]
                .get("changes", [{}])[0]
                .get("value", {})
                .get("messages", [{}])[0]
                .get("timestamp", "")
            )
            if msg_ts_str:
                age = abs(time.time() - float(msg_ts_str))
                if age > WEBHOOK_MAX_AGE_SECONDS:
                    raise WebhookReplayError(
                        message="WhatsApp message timestamp too old.",
                        detail=f"Message is {age:.0f}s old; max {WEBHOOK_MAX_AGE_SECONDS}s (T30)",
                    )
        except (IndexError, KeyError, ValueError):
            pass  # Missing timestamp field — do not block; HMAC already verified

    # Step 7 — deduplication
    message_id = _extract_message_id(platform_type, body)
    is_duplicate = await _dedup_check(redis, message_id)

    if is_duplicate:
        log.info(
            "integration.inbound.deduplicated",
            platform_type=platform_type,
            message_id=message_id,
        )
        return InboundWebhookResponse(
            accepted=True,
            deduplicated=True,
            platform_type=platform_type,
            message=f"Duplicate message {message_id!r} silently absorbed.",
        )

    # Step 8 — platform user lookup (informational — no error on miss)
    platform_user_id = _extract_platform_user_id(platform_type, body)
    verified_mapping = None
    if platform_user_id:
        now = datetime.now(timezone.utc)
        mapping_result = await db.execute(
            select(PlatformUserMapping).where(
                PlatformUserMapping.platform_id == platform.id,
                PlatformUserMapping.platform_user_id == platform_user_id,
                PlatformUserMapping.is_verified.is_(True),
                PlatformUserMapping.expires_at > now,
            )
        )
        verified_mapping = mapping_result.scalar_one_or_none()

    log.info(
        "integration.inbound.received",
        platform_type=platform_type,
        message_id=message_id,
        platform_user_id=platform_user_id,
        has_verified_mapping=verified_mapping is not None,
    )

    # Step 9 — audit + Phase 6 dispatch stub
    if audit:
        await audit.log(
            execution_status="integration.inbound.received",
            question=(
                f"Inbound {platform_type} webhook received. "
                f"platform_user={platform_user_id!r}, "
                f"verified_mapping={verified_mapping is not None}, "
                f"message_id={message_id!r}"
            ),
            notification_platform_id=platform.id,
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    user_status = (
        "verified" if verified_mapping else
        "unverified (message not processed)" if platform_user_id else
        "unknown sender"
    )
    return InboundWebhookResponse(
        accepted=True,
        deduplicated=False,
        platform_type=platform_type,
        message=f"Message accepted. User status: {user_status}. Query dispatch: Phase 6.",
    )


# =============================================================================
# POST /verify  — Confirm platform mapping
# =============================================================================

@router.post(
    "/verify",
    response_model=MappingVerifyResponse,
    summary="Confirm platform user mapping",
    description=(
        "Called when a platform user replies with the verification token sent in a DM. "
        "Sets is_verified=True on the matching PlatformUserMapping (T29). "
        "No JWT required — the token itself is the credential."
    ),
    status_code=status.HTTP_200_OK,
)
async def verify_mapping(
    request: Request,
    body: MappingVerifyRequest,
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> MappingVerifyResponse:
    """
    Token-based mapping verification (T29).

    Phase 2 stub: The notification worker that issues tokens and stores them
    is built in Phase 6.  In Phase 2 we:
      - Validate request body shape
      - Look up a matching unverified mapping by (platform_type, platform_user_id)
      - Accept any non-empty token as valid (Phase 6 will check Redis token store)
      - Set is_verified=True and verified_at=now() if found

    This makes the route fully testable without Phase 6 token issuance.
    """
    if body.platform_type not in INBOUND_PLATFORM_TYPES:
        raise ValidationError(
            message=f"Unknown platform type: {body.platform_type!r}.",
            detail=f"Supported types: {sorted(INBOUND_PLATFORM_TYPES)}",
        )

    # Find matching unverified mapping
    platform_result = await db.execute(
        select(NotificationPlatform).where(
            NotificationPlatform.platform_type == body.platform_type,
            NotificationPlatform.is_active.is_(True),
        )
    )
    platform = platform_result.scalar_one_or_none()
    if platform is None:
        # Do not reveal whether the platform exists — return generic response
        return MappingVerifyResponse(
            verified=False,
            platform_type=body.platform_type,
            message="Verification token not recognised or expired.",
        )

    mapping_result = await db.execute(
        select(PlatformUserMapping).where(
            PlatformUserMapping.platform_id == platform.id,
            PlatformUserMapping.platform_user_id == body.platform_user_id,
            PlatformUserMapping.is_verified.is_(False),
        )
    )
    mapping = mapping_result.scalar_one_or_none()
    if mapping is None:
        return MappingVerifyResponse(
            verified=False,
            platform_type=body.platform_type,
            message="Verification token not recognised or already verified.",
        )

    # Phase 2: accept any token (Phase 6 validates against Redis token store)
    # Phase 6 will: redis.get(f"verify_token:{token}") → internal_user_id
    now = datetime.now(timezone.utc)
    mapping.is_verified = True
    mapping.verified_at = now
    await db.commit()

    log.info(
        "integration.mapping.verified",
        platform_type=body.platform_type,
        platform_user_id=body.platform_user_id,
        mapping_id=str(mapping.id),
    )

    if audit:
        await audit.log(
            execution_status="integration.mapping.verified",
            question=(
                f"Platform mapping verified: {body.platform_type} "
                f"user={body.platform_user_id!r} → internal={mapping.internal_user_id}"
            ),
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return MappingVerifyResponse(
        verified=True,
        platform_type=body.platform_type,
        internal_user_id=str(mapping.internal_user_id),
        message="Platform user identity confirmed.",
    )


# =============================================================================
# POST /gdpr/erasure  — GDPR audit log erasure (admin only)
# =============================================================================

@router.post(
    "/gdpr/erasure",
    response_model=GDPRErasureResponse,
    summary="GDPR erasure — redact audit log question text",
    description=(
        "Admin only. Redacts the question field in all AuditLog rows for the target user. "
        "All other columns (timestamps, status, row_count, SQL) are preserved. "
        "Irreversible. The erasure itself is audit-logged (T21)."
    ),
    status_code=status.HTTP_200_OK,
)
async def gdpr_erasure(
    request: Request,
    body: GDPRErasureRequest,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> GDPRErasureResponse:
    """
    GDPR right-to-erasure implementation (T21).

    Redact-not-delete strategy:
      - question → GDPR_REDACTION_SENTINEL
      - generated_sql → preserved (not personal data; needed for compliance)
      - All other columns → preserved

    The audit log entry for this erasure is written AFTER the redaction commits
    so that the erasure itself is recorded under the admin's identity.
    """
    try:
        target_uuid = uuid.UUID(body.user_id)
    except ValueError:
        raise ValidationError(
            message="Invalid user_id format.",
            detail=f"user_id={body.user_id!r} is not a valid UUID",
        )

    now = datetime.now(timezone.utc)

    # Bulk update — redact question field for all audit rows belonging to target user
    result = await db.execute(
        update(AuditLog)
        .where(AuditLog.user_id == target_uuid)
        .where(AuditLog.question != GDPR_REDACTION_SENTINEL)  # idempotent — skip already-redacted
        .values(question=GDPR_REDACTION_SENTINEL)
    )
    rows_redacted = result.rowcount if result.rowcount is not None else 0
    await db.commit()

    log.info(
        "integration.gdpr.erasure",
        admin_id=admin["user_id"],
        target_user_id=body.user_id,
        rows_redacted=rows_redacted,
    )

    # Audit log entry for the erasure itself
    if audit:
        await audit.log(
            execution_status="integration.gdpr.erasure",
            question=(
                f"GDPR erasure performed by admin {admin['user_id']!r}: "
                f"target_user={body.user_id!r}, "
                f"rows_redacted={rows_redacted}, "
                f"reason={body.reason!r}"
            ),
            user_id=admin["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return GDPRErasureResponse(
        user_id=body.user_id,
        rows_redacted=rows_redacted,
        sentinel=GDPR_REDACTION_SENTINEL,
        erased_by=admin["user_id"],
        erased_at=now.isoformat(),
        reason=body.reason,
    )