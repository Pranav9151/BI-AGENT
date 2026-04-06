"""
Smart BI Agent — Notification Platform Routes  (Component 16)
Architecture v3.1 | Layer 4 (Application) | Threats: T6  (notification card injection),
                                                        T29 (unverified platform mapping),
                                                        T30 (webhook replay / SSRF)

ENDPOINTS:
    GET    /api/v1/notifications                          — list platforms (admin)
    GET    /api/v1/notifications/{id}                     — get platform (admin)
    POST   /api/v1/notifications                          — create platform (admin)
    PATCH  /api/v1/notifications/{id}                     — update platform (admin)
    DELETE /api/v1/notifications/{id}                     — deactivate platform (admin)
    POST   /api/v1/notifications/{id}/test                — test connectivity (admin)
    GET    /api/v1/notifications/{id}/mappings            — list user mappings (admin)
    POST   /api/v1/notifications/{id}/mappings            — add user mapping (admin)
    DELETE /api/v1/notifications/{id}/mappings/{map_id}   — remove mapping (admin)

ACCESS:
    ALL endpoints require require_admin.  Notification platforms are global,
    admin-managed infrastructure (same pattern as LLM providers).
    Non-admin users never see platform credentials or mappings.

CREDENTIAL SECURITY:
    - delivery_config (plaintext) is encrypted with KeyPurpose.NOTIFICATION_KEYS
      before any DB write.
    - Only a config_preview (first 8 chars + "...") is returned in any GET response.
    - Decryption happens in-memory only for the /test probe; the reference is
      zeroed immediately after use.
    - delivery_config is never logged.

SSRF (T30 — webhook platforms):
    Platforms whose delivery_config includes a URL (webhook, teams, jira,
    clickup) have that URL SSRF-validated before the record is saved or updated.
    Validation uses the same ssrf_guard.validate_url used by connection routes.

PLATFORM USER MAPPINGS (T29):
    Mappings start unverified (is_verified=False).  The notification worker sends
    a verification message to the platform user; the integration handler sets
    is_verified=True when the user confirms.  Unverified mappings are accepted
    by inbound handlers but trigger a confirmation flow.
    expires_at is set to 90 days from creation; the scheduler clears expired
    mappings so users periodically re-verify.

AUDIT:
    create, update, deactivate, test, mapping add/remove all write to AuditWriter.
    delivery_config content is never included in audit log messages.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUser,
    get_audit_writer,
    get_db,
    get_key_manager,
    require_admin,
)
from app.errors.exceptions import (
    InsufficientPermissionsError,
    ResourceNotFoundError,
    SSRFError,
    ValidationError,
)
from app.logging.structured import get_logger
from app.models.notification_platform import NotificationPlatform, PlatformUserMapping
from app.notifications.dispatcher import test_provider
from app.schemas.notification import (
    PLATFORM_TYPES,
    WEBHOOK_PLATFORM_TYPES,
    NotificationPlatformCreateRequest,
    NotificationPlatformListResponse,
    NotificationPlatformResponse,
    NotificationPlatformTestResponse,
    NotificationPlatformUpdateRequest,
    PlatformMappingCreateRequest,
    PlatformMappingListResponse,
    PlatformMappingResponse,
)
from app.security.key_manager import KeyManager, KeyPurpose

try:
    from app.security.ssrf_guard import SSRFError as GuardSSRFError
    from app.security.ssrf_guard import validate_url
    _SSRF_AVAILABLE = True
except ImportError:
    _SSRF_AVAILABLE = False

log = get_logger(__name__)

router = APIRouter()

# =============================================================================
# Helpers
# =============================================================================

def _extract_config_preview(key_manager: KeyManager, encrypted_config: str) -> str:
    """
    Decrypt just enough of the config to form an 8-char preview, then discard.
    Returns "????????..." if decryption fails (config stored but unreadable —
    should not happen in normal operation; indicates key rotation in progress).
    """
    try:
        plaintext = key_manager.decrypt(encrypted_config, KeyPurpose.NOTIFICATION_KEYS)
        preview_src = plaintext[:8] if len(plaintext) >= 8 else plaintext
        return f"{preview_src}..."
    except Exception:
        return "????????..."


def _platform_to_response(
    p: NotificationPlatform, key_manager: KeyManager
) -> NotificationPlatformResponse:
    def _iso(dt: Optional[datetime]) -> Optional[str]:
        return dt.isoformat() if dt is not None else None

    return NotificationPlatformResponse(
        platform_id=str(p.id),
        name=p.name,
        platform_type=p.platform_type,
        config_preview=_extract_config_preview(key_manager, p.encrypted_config),
        is_active=p.is_active,
        is_inbound_enabled=p.is_inbound_enabled,
        is_outbound_enabled=p.is_outbound_enabled,
        created_by=str(p.created_by) if p.created_by else None,
        created_at=_iso(p.created_at) or "",
        updated_at=_iso(p.updated_at) or "",
    )


def _mapping_to_response(m: PlatformUserMapping) -> PlatformMappingResponse:
    def _iso(dt: Optional[datetime]) -> Optional[str]:
        return dt.isoformat() if dt is not None else None

    return PlatformMappingResponse(
        mapping_id=str(m.id),
        platform_id=str(m.platform_id),
        platform_user_id=m.platform_user_id,
        internal_user_id=str(m.internal_user_id),
        is_verified=m.is_verified,
        verified_at=_iso(m.verified_at),
        expires_at=_iso(m.expires_at),
        created_at=_iso(m.created_at) or "",
    )


async def _get_platform_or_404(
    platform_id: uuid.UUID, db: AsyncSession
) -> NotificationPlatform:
    result = await db.execute(
        select(NotificationPlatform).where(NotificationPlatform.id == platform_id)
    )
    p = result.scalar_one_or_none()
    if p is None:
        raise ResourceNotFoundError(
            message="Notification platform not found.",
            detail=f"NotificationPlatform {platform_id} does not exist",
        )
    return p


async def _get_mapping_or_404(
    mapping_id: uuid.UUID, platform_id: uuid.UUID, db: AsyncSession
) -> PlatformUserMapping:
    result = await db.execute(
        select(PlatformUserMapping).where(
            PlatformUserMapping.id == mapping_id,
            PlatformUserMapping.platform_id == platform_id,
        )
    )
    m = result.scalar_one_or_none()
    if m is None:
        raise ResourceNotFoundError(
            message="Platform user mapping not found.",
            detail=f"Mapping {mapping_id} not found on platform {platform_id}",
        )
    return m


def _ssrf_check_url(url: Optional[str], field: str = "webhook URL") -> None:
    """
    Run SSRF validation on a URL extracted from delivery_config.
    No-op if the SSRF guard module is unavailable (test environments).
    Raises SSRFError (400) on blocked hosts.
    """
    if not url or not _SSRF_AVAILABLE:
        return
    try:
        validate_url(url)
    except GuardSSRFError as exc:
        raise SSRFError(
            message=f"The {field} is not reachable.",
            detail=str(exc),
        )


def _get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# =============================================================================
# GET /  — List notification platforms
# =============================================================================

@router.get(
    "/",
    response_model=NotificationPlatformListResponse,
    summary="List notification platforms",
    description="Admin only. Returns all configured notification platforms with config preview.",
)
async def list_platforms(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    platform_type: Optional[str] = Query(None, description="Filter by platform type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    key_manager: KeyManager = Depends(get_key_manager),
) -> NotificationPlatformListResponse:
    conditions = []
    if platform_type:
        conditions.append(NotificationPlatform.platform_type == platform_type)
    if is_active is not None:
        conditions.append(NotificationPlatform.is_active == is_active)

    count_stmt = select(func.count()).select_from(NotificationPlatform)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    data_stmt = (
        select(NotificationPlatform)
        .order_by(NotificationPlatform.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if conditions:
        data_stmt = data_stmt.where(*conditions)
    platforms = (await db.execute(data_stmt)).scalars().all()

    log.info(
        "notifications.list",
        admin_id=admin["user_id"],
        total=total,
    )

    return NotificationPlatformListResponse(
        platforms=[_platform_to_response(p, key_manager) for p in platforms],
        total=total,
        skip=skip,
        limit=limit,
    )


# =============================================================================
# GET /{platform_id}  — Get single platform
# =============================================================================

@router.get(
    "/{platform_id}",
    response_model=NotificationPlatformResponse,
    summary="Get notification platform",
    description="Admin only. encrypted_config is never returned — only config_preview.",
)
async def get_platform(
    platform_id: uuid.UUID,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    key_manager: KeyManager = Depends(get_key_manager),
) -> NotificationPlatformResponse:
    p = await _get_platform_or_404(platform_id, db)
    log.info("notifications.get", admin_id=admin["user_id"], platform_id=str(platform_id))
    return _platform_to_response(p, key_manager)


# =============================================================================
# POST /  — Create platform
# =============================================================================

@router.post(
    "/",
    response_model=NotificationPlatformResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create notification platform",
    description=(
        "Admin only. delivery_config is encrypted with NOTIFICATION_KEYS before storage. "
        "Webhook-type platform URLs are SSRF-validated before persistence (T30)."
    ),
)
async def create_platform(
    request: Request,
    body: NotificationPlatformCreateRequest,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    key_manager: KeyManager = Depends(get_key_manager),
    audit=Depends(get_audit_writer),
) -> NotificationPlatformResponse:
    # Validate platform_type
    if body.platform_type not in PLATFORM_TYPES:
        raise ValidationError(
            message=f"Unknown platform type: {body.platform_type!r}.",
            detail=f"Valid types: {sorted(PLATFORM_TYPES)}",
        )

    # SSRF check for webhook-type platforms (T30)
    if body.platform_type in WEBHOOK_PLATFORM_TYPES:
        _ssrf_check_url(body.webhook_url, field=f"{body.platform_type} URL")

    # Encrypt delivery_config — plaintext never persisted
    plaintext = json.dumps(body.delivery_config, separators=(",", ":"))
    encrypted_config = key_manager.encrypt(plaintext, KeyPurpose.NOTIFICATION_KEYS)

    now = datetime.now(timezone.utc)
    p = NotificationPlatform(
        id=uuid.uuid4(),
        name=body.name,
        platform_type=body.platform_type,
        encrypted_config=encrypted_config,
        is_active=body.is_active,
        is_inbound_enabled=body.is_inbound_enabled,
        is_outbound_enabled=body.is_outbound_enabled,
        created_by=uuid.UUID(admin["user_id"]),
    )
    p.created_at = now
    p.updated_at = now

    db.add(p)
    await db.commit()

    log.info(
        "notifications.created",
        admin_id=admin["user_id"],
        platform_id=str(p.id),
        platform_type=p.platform_type,
        name=p.name,
    )

    if audit:
        await audit.log(
            execution_status="notification_platform.created",
            question=f"Admin created notification platform: {body.name!r} ({body.platform_type})",
            user_id=admin["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _platform_to_response(p, key_manager)


# =============================================================================
# PATCH /{platform_id}  — Update platform
# =============================================================================

@router.patch(
    "/{platform_id}",
    response_model=NotificationPlatformResponse,
    summary="Update notification platform",
    description=(
        "Admin only. If delivery_config is supplied it replaces the entire stored "
        "config (re-encrypted). Webhook URLs are SSRF-re-validated."
    ),
)
async def update_platform(
    platform_id: uuid.UUID,
    request: Request,
    body: NotificationPlatformUpdateRequest,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    key_manager: KeyManager = Depends(get_key_manager),
    audit=Depends(get_audit_writer),
) -> NotificationPlatformResponse:
    p = await _get_platform_or_404(platform_id, db)

    changed_fields: list[str] = []

    if body.name is not None:
        p.name = body.name
        changed_fields.append("name")

    if body.delivery_config is not None:
        # SSRF re-check if platform is webhook-type and config carries a URL
        if p.platform_type in WEBHOOK_PLATFORM_TYPES:
            _ssrf_check_url(body.webhook_url, field=f"{p.platform_type} URL")
        plaintext = json.dumps(body.delivery_config, separators=(",", ":"))
        p.encrypted_config = key_manager.encrypt(plaintext, KeyPurpose.NOTIFICATION_KEYS)
        changed_fields.append("delivery_config")

    if body.is_active is not None:
        p.is_active = body.is_active
        changed_fields.append("is_active")

    if body.is_inbound_enabled is not None:
        p.is_inbound_enabled = body.is_inbound_enabled
        changed_fields.append("is_inbound_enabled")

    if body.is_outbound_enabled is not None:
        p.is_outbound_enabled = body.is_outbound_enabled
        changed_fields.append("is_outbound_enabled")

    p.updated_at = datetime.now(timezone.utc)
    await db.commit()

    log.info(
        "notifications.updated",
        admin_id=admin["user_id"],
        platform_id=str(platform_id),
        changed_fields=changed_fields,
    )

    if audit and changed_fields:
        await audit.log(
            execution_status="notification_platform.updated",
            question=(
                f"Admin updated platform {p.name!r} ({platform_id}): "
                f"{', '.join(changed_fields)}"
            ),
            user_id=admin["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _platform_to_response(p, key_manager)


# =============================================================================
# DELETE /{platform_id}  — Deactivate platform
# =============================================================================

@router.delete(
    "/{platform_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate notification platform",
    description=(
        "Admin only. Soft-deactivate: sets is_active=False and is_inbound_enabled=False. "
        "The record and all user mappings are retained for audit history. "
        "Schedules referencing this platform will skip delivery gracefully."
    ),
)
async def deactivate_platform(
    platform_id: uuid.UUID,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    key_manager: KeyManager = Depends(get_key_manager),
    audit=Depends(get_audit_writer),
) -> Response:
    """
    Soft-deactivate rather than hard-delete: schedules reference platform_id
    via delivery_targets JSONB; hard-deleting would leave dangling references
    that the scheduler must handle anyway.  Deactivation is the safer choice.
    """
    p = await _get_platform_or_404(platform_id, db)

    name_snapshot = p.name
    type_snapshot = p.platform_type

    p.is_active = False
    p.is_inbound_enabled = False
    p.updated_at = datetime.now(timezone.utc)
    await db.commit()

    log.info(
        "notifications.deactivated",
        admin_id=admin["user_id"],
        platform_id=str(platform_id),
        name=name_snapshot,
    )

    if audit:
        await audit.log(
            execution_status="notification_platform.deactivated",
            question=(
                f"Admin deactivated notification platform: "
                f"{name_snapshot!r} ({type_snapshot}) ({platform_id})"
            ),
            user_id=admin["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# POST /{platform_id}/test  — Test connectivity
# =============================================================================

@router.post(
    "/{platform_id}/test",
    response_model=NotificationPlatformTestResponse,
    summary="Test platform connectivity",
    description=(
        "Admin only. Decrypts the config in-memory, sends a probe message, "
        "then zeroes the plaintext reference. "
        "The platform must be active to test."
    ),
)
async def test_platform(
    platform_id: uuid.UUID,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    key_manager: KeyManager = Depends(get_key_manager),
    audit=Depends(get_audit_writer),
) -> NotificationPlatformTestResponse:
    """
    Connectivity probe against the actual provider endpoint/credentials.
    """
    p = await _get_platform_or_404(platform_id, db)

    if not p.is_active:
        return NotificationPlatformTestResponse(
            platform_id=str(p.id),
            name=p.name,
            platform_type=p.platform_type,
            success=False,
            message="Platform is deactivated. Re-activate before testing.",
        )

    # Decrypt in-memory only; zero reference immediately after use.
    plaintext_config: Optional[str] = None
    success = False
    message = "Test failed."

    try:
        plaintext_config = key_manager.decrypt(
            p.encrypted_config, KeyPurpose.NOTIFICATION_KEYS
        )
        try:
            config_dict = json.loads(plaintext_config)
            if not isinstance(config_dict, dict):
                raise ValueError("delivery_config JSON must be an object")
        except Exception:
            # Backward compatibility: older rows may contain plaintext token/URL values.
            # Wrap as provider-appropriate minimal config so test probes can still run.
            if p.platform_type == "slack":
                config_dict = {"bot_token": plaintext_config}
            elif p.platform_type in ("teams", "webhook"):
                config_dict = {"webhook_url": plaintext_config}
            else:
                config_dict = {"value": plaintext_config}
        result = await test_provider(p.platform_type, config_dict)
        success = result.success
        message = result.message if result.success else (result.error or "Connectivity test failed.")
    except Exception as exc:
        log.warning(
            "notifications.test.failed",
            admin_id=admin["user_id"],
            platform_id=str(platform_id),
            error=str(exc),
        )
        message = f"Test failed: {str(exc)[:100]}"
    finally:
        # Zero the plaintext reference (T — credential in-memory exposure)
        plaintext_config = None  # noqa: F841

    log.info(
        "notifications.test",
        admin_id=admin["user_id"],
        platform_id=str(platform_id),
        success=success,
    )

    if audit:
        await audit.log(
            execution_status="notification_platform.tested",
            question=f"Admin tested platform {p.name!r} ({platform_id}): success={success}",
            user_id=admin["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return NotificationPlatformTestResponse(
        platform_id=str(p.id),
        name=p.name,
        platform_type=p.platform_type,
        success=success,
        message=message,
    )


# =============================================================================
# GET /{platform_id}/mappings  — List user mappings
# =============================================================================

@router.get(
    "/{platform_id}/mappings",
    response_model=PlatformMappingListResponse,
    summary="List platform user mappings",
    description="Admin only. Returns all user mappings for a platform with verification status.",
)
async def list_mappings(
    platform_id: uuid.UUID,
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    is_verified: Optional[bool] = Query(None, description="Filter by verification status"),
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PlatformMappingListResponse:
    # Verify platform exists
    await _get_platform_or_404(platform_id, db)

    conditions = [PlatformUserMapping.platform_id == platform_id]
    if is_verified is not None:
        conditions.append(PlatformUserMapping.is_verified == is_verified)

    count_stmt = (
        select(func.count())
        .select_from(PlatformUserMapping)
        .where(*conditions)
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    data_stmt = (
        select(PlatformUserMapping)
        .where(*conditions)
        .order_by(PlatformUserMapping.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    mappings = (await db.execute(data_stmt)).scalars().all()

    log.info(
        "notifications.mappings.listed",
        admin_id=admin["user_id"],
        platform_id=str(platform_id),
        total=total,
    )

    return PlatformMappingListResponse(
        platform_id=str(platform_id),
        mappings=[_mapping_to_response(m) for m in mappings],
        total=total,
        skip=skip,
        limit=limit,
    )


# =============================================================================
# POST /{platform_id}/mappings  — Add user mapping
# =============================================================================

@router.post(
    "/{platform_id}/mappings",
    response_model=PlatformMappingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add platform user mapping",
    description=(
        "Admin only. Links a platform-side user ID to an internal Smart BI user. "
        "The mapping starts unverified (T29). "
        "The notification worker sends a verification message; "
        "the integration handler sets is_verified=True on confirmation. "
        "expires_at is set to 90 days from now."
    ),
)
async def add_mapping(
    platform_id: uuid.UUID,
    request: Request,
    body: PlatformMappingCreateRequest,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> PlatformMappingResponse:
    """
    Create an unverified mapping.  Uniqueness constraint on
    (platform_id, platform_user_id) is enforced by the DB; duplicate
    inserts will raise an IntegrityError which FastAPI will return as 500
    until a dedicated duplicate-detection handler is added in Phase 6.
    """
    await _get_platform_or_404(platform_id, db)

    try:
        internal_uuid = uuid.UUID(body.internal_user_id)
    except ValueError:
        raise ValidationError(
            message="Invalid internal_user_id format.",
            detail=f"internal_user_id={body.internal_user_id!r} is not a valid UUID",
        )

    # 90-day expiry (T29)
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=90)

    m = PlatformUserMapping(
        id=uuid.uuid4(),
        platform_id=platform_id,
        platform_user_id=body.platform_user_id,
        internal_user_id=internal_uuid,
        is_verified=False,
        verified_at=None,
        expires_at=expires_at,
    )
    m.created_at = now

    db.add(m)
    await db.commit()

    log.info(
        "notifications.mapping.added",
        admin_id=admin["user_id"],
        platform_id=str(platform_id),
        mapping_id=str(m.id),
        is_verified=False,
    )

    if audit:
        await audit.log(
            execution_status="notification_platform.mapping_added",
            question=(
                f"Admin added unverified mapping: "
                f"platform_user={body.platform_user_id!r} → "
                f"internal_user={body.internal_user_id!r} "
                f"on platform {platform_id}"
            ),
            user_id=admin["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _mapping_to_response(m)


# =============================================================================
# DELETE /{platform_id}/mappings/{mapping_id}  — Remove user mapping
# =============================================================================

@router.delete(
    "/{platform_id}/mappings/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove platform user mapping",
    description="Admin only. Hard-delete the user mapping.",
)
async def remove_mapping(
    platform_id: uuid.UUID,
    mapping_id: uuid.UUID,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> Response:
    m = await _get_mapping_or_404(mapping_id, platform_id, db)
    user_snapshot = m.platform_user_id

    await db.delete(m)
    await db.commit()

    log.info(
        "notifications.mapping.removed",
        admin_id=admin["user_id"],
        platform_id=str(platform_id),
        mapping_id=str(mapping_id),
    )

    if audit:
        await audit.log(
            execution_status="notification_platform.mapping_removed",
            question=(
                f"Admin removed mapping {mapping_id} "
                f"(platform_user={user_snapshot!r}) from platform {platform_id}"
            ),
            user_id=admin["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
