"""
Smart BI Agent — Schedule Routes  (Component 15)
Architecture v3.1 | Layer 4 (Application) | Threats: T8  (APScheduler duplicate job),
                                                        T9  (stale permissions at run time),
                                                        T47 (timezone confusion),
                                                        T52 (IDOR — ownership check)

ENDPOINTS:
    GET    /api/v1/schedules                     — list schedules (own; admin sees all)
    GET    /api/v1/schedules/{id}                — get single schedule
    POST   /api/v1/schedules                     — create schedule
    PATCH  /api/v1/schedules/{id}                — update schedule
    DELETE /api/v1/schedules/{id}                — delete schedule
    PATCH  /api/v1/schedules/{id}/toggle         — enable / disable without deleting

OWNERSHIP MODEL (T52):
    Owner or admin for all mutating operations.
    Non-admin list is scoped to own schedules only (no sharing concept).
    Admins may pass ?user_id= to view another user's schedules.

STALE PERMISSIONS (T9):
    This layer stores the schedule record only.  At execution time the APScheduler
    worker always:
      1. Reloads the schedule from PostgreSQL (detects deactivation).
      2. Fetches fresh user + permissions from DB (detects role/perm changes).
      3. Verifies user.is_active before executing the query.
    If any of these checks fail, the job is skipped and the admin is notified.
    This layer does NOT perform permission re-validation — that is the worker's job.

DISTRIBUTED LOCK (T8):
    The APScheduler worker acquires `schedule_lock:{id}` in Redis DB2 (TTL 300s)
    before running a job.  If the lock is already held (another instance fired the
    same job), the second instance skips silently.  This layer has no lock logic —
    it surfaces is_active so operators can disable a runaway schedule quickly.

TIMEZONE (T47):
    cron_expression is validated to 5-field UNIX format in the schema layer.
    Timezone string is stored verbatim; APScheduler performs full IANA validation
    when loading jobs on startup.  An invalid timezone causes the job to be
    skipped at load time with a structured log warning.

AUDIT:
    create, update, delete, and toggle all write to AuditWriter.
"""
from __future__ import annotations

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
    require_active_user,
)
from app.errors.exceptions import (
    InsufficientPermissionsError,
    ResourceNotFoundError,
    ValidationError,
)
from app.logging.structured import get_logger
from app.models.schedule import Schedule
from app.schemas.schedule import (
    ScheduleCreateRequest,
    ScheduleListResponse,
    ScheduleResponse,
    ScheduleToggleResponse,
    ScheduleUpdateRequest,
)

log = get_logger(__name__)

router = APIRouter()


# =============================================================================
# Helpers
# =============================================================================

def _sched_to_response(s: Schedule) -> ScheduleResponse:
    """Convert a Schedule ORM object to a safe API response."""
    def _iso(dt: Optional[datetime]) -> Optional[str]:
        return dt.isoformat() if dt is not None else None

    return ScheduleResponse(
        schedule_id=str(s.id),
        user_id=str(s.user_id),
        saved_query_id=str(s.saved_query_id) if s.saved_query_id else None,
        name=s.name,
        cron_expression=s.cron_expression,
        timezone=s.timezone,
        output_format=s.output_format,
        delivery_targets=s.delivery_targets or [],
        is_active=s.is_active,
        last_run_at=_iso(s.last_run_at),
        last_run_status=s.last_run_status,
        next_run_at=_iso(s.next_run_at),
        created_at=_iso(s.created_at) or "",
        updated_at=_iso(s.updated_at) or "",
    )


async def _get_sched_or_404(sched_id: uuid.UUID, db: AsyncSession) -> Schedule:
    result = await db.execute(
        select(Schedule).where(Schedule.id == sched_id)
    )
    s = result.scalar_one_or_none()
    if s is None:
        raise ResourceNotFoundError(
            message="Schedule not found.",
            detail=f"Schedule {sched_id} does not exist",
        )
    return s


def _assert_owner_or_admin(s: Schedule, current_user: CurrentUser) -> None:
    """Ownership gate — T52 IDOR prevention."""
    if str(s.user_id) != current_user["user_id"] and current_user["role"] != "admin":
        raise InsufficientPermissionsError(
            message="You do not have permission to access this schedule.",
            detail=(
                f"Schedule {s.id} owned by {s.user_id}, "
                f"requested by {current_user['user_id']} (role={current_user['role']})"
            ),
        )


def _parse_optional_uuid(value: Optional[str], field: str) -> Optional[uuid.UUID]:
    """Parse a UUID string or return None, raising ValidationError on bad format."""
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ValidationError(
            message=f"Invalid {field} format.",
            detail=f"{field}={value!r} is not a valid UUID",
        )


def _get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _targets_to_json(targets) -> list:
    """Convert DeliveryTarget pydantic objects → plain dicts for JSONB storage."""
    return [t.model_dump() for t in targets]


# =============================================================================
# GET /  — List schedules
# =============================================================================

@router.get(
    "/",
    response_model=ScheduleListResponse,
    summary="List schedules",
    description=(
        "Returns schedules visible to the current user. "
        "Non-admins see only their own. "
        "Admins may pass ?user_id= to scope to a specific user, or omit it to see all."
    ),
)
async def list_schedules(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user_id: Optional[str] = Query(None, description="Admin-only: filter by user UUID"),
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> ScheduleListResponse:
    is_admin = current_user["role"] == "admin"
    conditions = []

    if is_admin and user_id:
        owner_uuid = _parse_optional_uuid(user_id, "user_id")
        conditions.append(Schedule.user_id == owner_uuid)
    elif not is_admin:
        # Non-admins always scoped to own schedules
        conditions.append(Schedule.user_id == uuid.UUID(current_user["user_id"]))
    # Admin with no user_id filter → no ownership condition (sees all)

    if is_active is not None:
        conditions.append(Schedule.is_active == is_active)

    count_stmt = select(func.count()).select_from(Schedule)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    data_stmt = (
        select(Schedule)
        .order_by(Schedule.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if conditions:
        data_stmt = data_stmt.where(*conditions)
    schedules = (await db.execute(data_stmt)).scalars().all()

    log.info(
        "schedules.list",
        user_id=current_user["user_id"],
        is_admin=is_admin,
        total=total,
    )

    return ScheduleListResponse(
        schedules=[_sched_to_response(s) for s in schedules],
        total=total,
        skip=skip,
        limit=limit,
    )


# =============================================================================
# GET /{schedule_id}  — Get single schedule
# =============================================================================

@router.get(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Get schedule",
    description="Retrieve a single schedule by ID. Owner or admin only.",
)
async def get_schedule(
    schedule_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    s = await _get_sched_or_404(schedule_id, db)
    _assert_owner_or_admin(s, current_user)

    log.info(
        "schedules.get",
        user_id=current_user["user_id"],
        schedule_id=str(schedule_id),
    )
    return _sched_to_response(s)


# =============================================================================
# POST /  — Create schedule
# =============================================================================

@router.post(
    "/",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create schedule",
    description=(
        "Create a new scheduled report. Any active user may create schedules. "
        "The schedule is owned by the calling user. "
        "cron_expression must be a valid 5-field UNIX cron string."
    ),
)
async def create_schedule(
    request: Request,
    body: ScheduleCreateRequest,
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> ScheduleResponse:
    """
    Create a schedule record.

    saved_query_id existence is NOT validated here (T9) — the APScheduler worker
    re-checks at execution time and skips gracefully if the query was deleted.
    """
    saved_query_uuid = _parse_optional_uuid(body.saved_query_id, "saved_query_id")

    now = datetime.now(timezone.utc)
    s = Schedule(
        id=uuid.uuid4(),
        user_id=uuid.UUID(current_user["user_id"]),
        saved_query_id=saved_query_uuid,
        name=body.name,
        cron_expression=body.cron_expression,
        timezone=body.timezone,
        output_format=body.output_format,
        delivery_targets=_targets_to_json(body.delivery_targets),
        is_active=body.is_active,
        last_run_at=None,
        last_run_status=None,
        next_run_at=None,
    )
    s.created_at = now
    s.updated_at = now

    db.add(s)
    await db.commit()

    log.info(
        "schedules.created",
        user_id=current_user["user_id"],
        schedule_id=str(s.id),
        name=s.name,
        cron=s.cron_expression,
        timezone=s.timezone,
        is_active=s.is_active,
    )

    if audit:
        await audit.log(
            execution_status="schedule.created",
            question=(
                f"User created schedule: {body.name!r} "
                f"(cron={body.cron_expression!r}, tz={body.timezone!r})"
            ),
            user_id=current_user["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _sched_to_response(s)


# =============================================================================
# PATCH /{schedule_id}  — Update schedule
# =============================================================================

@router.patch(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Update schedule",
    description=(
        "Partial-update a schedule. Owner or admin only. "
        "If cron_expression is supplied it is re-validated. "
        "Changes take effect on the next APScheduler reload cycle."
    ),
)
async def update_schedule(
    schedule_id: uuid.UUID,
    request: Request,
    body: ScheduleUpdateRequest,
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> ScheduleResponse:
    """Partial update — owner or admin only (T52)."""
    s = await _get_sched_or_404(schedule_id, db)
    _assert_owner_or_admin(s, current_user)

    changed_fields: list[str] = []

    if body.name is not None:
        s.name = body.name
        changed_fields.append("name")
    if body.saved_query_id is not None:
        s.saved_query_id = _parse_optional_uuid(body.saved_query_id, "saved_query_id")
        changed_fields.append("saved_query_id")
    if body.cron_expression is not None:
        s.cron_expression = body.cron_expression
        changed_fields.append("cron_expression")
    if body.timezone is not None:
        s.timezone = body.timezone
        changed_fields.append("timezone")
    if body.output_format is not None:
        s.output_format = body.output_format
        changed_fields.append("output_format")
    if body.delivery_targets is not None:
        s.delivery_targets = _targets_to_json(body.delivery_targets)
        changed_fields.append("delivery_targets")
    if body.is_active is not None:
        s.is_active = body.is_active
        changed_fields.append("is_active")

    s.updated_at = datetime.now(timezone.utc)
    await db.commit()

    log.info(
        "schedules.updated",
        user_id=current_user["user_id"],
        schedule_id=str(schedule_id),
        changed_fields=changed_fields,
    )

    if audit and changed_fields:
        await audit.log(
            execution_status="schedule.updated",
            question=(
                f"Schedule {s.name!r} ({schedule_id}) "
                f"updated: {', '.join(changed_fields)}"
            ),
            user_id=current_user["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _sched_to_response(s)


# =============================================================================
# DELETE /{schedule_id}  — Delete schedule
# =============================================================================

@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete schedule",
    description="Permanently delete a schedule. Owner or admin only.",
)
async def delete_schedule(
    schedule_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> Response:
    """Hard delete — the APScheduler worker will drop the job on next reload."""
    s = await _get_sched_or_404(schedule_id, db)
    _assert_owner_or_admin(s, current_user)

    name_snapshot = s.name
    await db.delete(s)
    await db.commit()

    log.info(
        "schedules.deleted",
        user_id=current_user["user_id"],
        schedule_id=str(schedule_id),
        name=name_snapshot,
    )

    if audit:
        await audit.log(
            execution_status="schedule.deleted",
            question=f"Deleted schedule: {name_snapshot!r} ({schedule_id})",
            user_id=current_user["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# PATCH /{schedule_id}/toggle  — Enable / disable
# =============================================================================

@router.patch(
    "/{schedule_id}/toggle",
    response_model=ScheduleToggleResponse,
    summary="Toggle schedule",
    description=(
        "Enable or disable a schedule without deleting it. "
        "Owner or admin only. "
        "Disabling sets is_active=False; the APScheduler worker will skip the job "
        "on the next scheduled tick — the distributed lock (T8) is not involved. "
        "Re-enabling sets is_active=True; the worker picks it up on next reload."
    ),
)
async def toggle_schedule(
    schedule_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> ScheduleToggleResponse:
    """Toggle is_active — owner or admin only (T52)."""
    s = await _get_sched_or_404(schedule_id, db)
    _assert_owner_or_admin(s, current_user)

    s.is_active = not s.is_active
    s.updated_at = datetime.now(timezone.utc)
    await db.commit()

    action = "enabled" if s.is_active else "disabled"

    log.info(
        "schedules.toggled",
        user_id=current_user["user_id"],
        schedule_id=str(schedule_id),
        is_active=s.is_active,
    )

    if audit:
        await audit.log(
            execution_status=f"schedule.{action}",
            question=f"Schedule {s.name!r} ({schedule_id}) {action}",
            user_id=current_user["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return ScheduleToggleResponse(
        schedule_id=str(s.id),
        name=s.name,
        is_active=s.is_active,
        message=f"Schedule '{s.name}' has been {action}.",
    )