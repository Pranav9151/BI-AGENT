"""
Smart BI Agent — Saved Query Routes  (Component 13)
Architecture v3.1 | Layer 4 (Application) | Threats: T43 (stale permissions),
                                                        T52 (IDOR — ownership check)

ENDPOINTS:
    GET    /api/v1/saved-queries                       — list (own + shared)
    GET    /api/v1/saved-queries/{id}                  — get single query
    POST   /api/v1/saved-queries                       — create
    PATCH  /api/v1/saved-queries/{id}                  — update (owner or admin)
    DELETE /api/v1/saved-queries/{id}                  — delete (owner or admin)
    POST   /api/v1/saved-queries/{id}/duplicate        — copy with new name
    PATCH  /api/v1/saved-queries/{id}/pin              — toggle pin flag
    PATCH  /api/v1/saved-queries/{id}/share            — toggle shared flag

OWNERSHIP MODEL (T52 — IDOR prevention):
    Every resource access gate is:
        1. Fetch record from DB
        2. If record.user_id != current_user.user_id AND role != "admin" → 403

    Only admins can access other users' private queries.
    Shared queries (is_shared=True) are readable (GET only) by all active users.

SENSITIVITY (new in v3.1):
    "restricted" queries are only readable/runnable by the owning user and admins.
    "sensitive" queries are readable by owner, admin, and users with analyst role.
    "normal" queries follow standard shared/private logic.

STALE PERMISSION NOTE (T43):
    This component stores and retrieves saved queries. It does NOT re-execute SQL.
    Re-running a saved query goes through the full query pipeline (C-future),
    which re-validates permissions against current DB state before execution.
    The run_count and last_run_at fields are updated by that pipeline, not here.

AUDIT:
    State-changing actions (create, update, delete, duplicate) write to AuditWriter.
    The sql_query text is intentionally excluded from audit log messages
    (could be long; the query_id is sufficient for reconstruction).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUser,
    get_audit_writer,
    get_db,
    get_current_user,
    require_admin,
    require_active_user,
)
from app.errors.exceptions import (
    InsufficientPermissionsError,
    ResourceNotFoundError,
    ValidationError,
)
from app.logging.structured import get_logger
from app.models.saved_query import SavedQuery
from app.schemas.saved_query import (
    SavedQueryCreateRequest,
    SavedQueryDuplicateResponse,
    SavedQueryListResponse,
    SavedQueryResponse,
    SavedQueryUpdateRequest,
    SensitivityLevel,
)

log = get_logger(__name__)

router = APIRouter()


# =============================================================================
# Helpers
# =============================================================================

def _sq_to_response(sq: SavedQuery) -> SavedQueryResponse:
    """Convert a SavedQuery ORM object to a safe API response."""
    last_run = (
        sq.last_run_at.isoformat()
        if sq.last_run_at is not None
        else None
    )
    return SavedQueryResponse(
        query_id=str(sq.id),
        user_id=str(sq.user_id),
        connection_id=str(sq.connection_id),
        name=sq.name,
        description=sq.description,
        question=sq.question,
        sql_query=sq.sql_query,
        tags=sq.tags or [],
        sensitivity=sq.sensitivity,
        is_shared=sq.is_shared,
        is_pinned=sq.is_pinned,
        run_count=sq.run_count,
        last_run_at=last_run,
    )


async def _get_sq_or_404(sq_id: uuid.UUID, db: AsyncSession) -> SavedQuery:
    """Fetch a SavedQuery by ID or raise ResourceNotFoundError (404)."""
    result = await db.execute(
        select(SavedQuery).where(SavedQuery.id == sq_id)
    )
    sq = result.scalar_one_or_none()
    if sq is None:
        raise ResourceNotFoundError(
            message="Saved query not found.",
            detail=f"SavedQuery {sq_id} does not exist",
        )
    return sq


def _assert_owner_or_admin(sq: SavedQuery, current_user: CurrentUser) -> None:
    """
    Ownership gate — T52 IDOR prevention.

    Raises InsufficientPermissionsError (403) if the current user is neither
    the owner nor an admin.
    """
    if str(sq.user_id) != current_user["user_id"] and current_user["role"] != "admin":
        raise InsufficientPermissionsError(
            message="You do not have permission to access this saved query.",
            detail=(
                f"SavedQuery {sq.id} owned by {sq.user_id}, "
                f"requested by {current_user['user_id']} (role={current_user['role']})"
            ),
        )


def _assert_readable(sq: SavedQuery, current_user: CurrentUser) -> None:
    """
    Read-access gate incorporating sensitivity rules.

    Rules (in priority order):
      1. Owner always has access.
      2. Admin always has access.
      3. is_shared=False and not owner/admin → 403 (private).
      4. sensitivity="restricted" → only owner + admin (is_shared irrelevant).
      5. sensitivity="sensitive" → owner + admin + analysts.
      6. sensitivity="normal" + is_shared=True → all authenticated users.
    """
    is_owner = str(sq.user_id) == current_user["user_id"]
    is_admin = current_user["role"] == "admin"

    if is_owner or is_admin:
        return

    # Restricted sensitivity — owner/admin only, regardless of is_shared
    if sq.sensitivity == SensitivityLevel.restricted:
        raise InsufficientPermissionsError(
            message="You do not have permission to access this saved query.",
            detail=f"SavedQuery {sq.id} has sensitivity=restricted; owner/admin only",
        )

    # Private (not shared) and not owner/admin → deny
    if not sq.is_shared:
        raise InsufficientPermissionsError(
            message="You do not have permission to access this saved query.",
            detail=f"SavedQuery {sq.id} is private (is_shared=False)",
        )

    # Shared but sensitive — require analyst or admin
    if sq.sensitivity == SensitivityLevel.sensitive:
        if current_user["role"] not in ("admin", "analyst"):
            raise InsufficientPermissionsError(
                message="You do not have permission to access this saved query.",
                detail=(
                    f"SavedQuery {sq.id} sensitivity=sensitive requires analyst+ role; "
                    f"user role={current_user['role']}"
                ),
            )


def _get_client_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For or direct connection."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# =============================================================================
# GET /  — List saved queries
# =============================================================================

@router.get(
    "/",
    response_model=SavedQueryListResponse,
    summary="List saved queries",
    description=(
        "Returns saved queries visible to the current user: "
        "their own queries plus all shared queries. "
        "Admins see all queries. "
        "Paginated with optional tag/name filter."
    ),
)
async def list_saved_queries(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    name: Optional[str] = Query(None, description="Filter by name substring (case-insensitive)"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    connection_id: Optional[str] = Query(None, description="Filter by connection UUID"),
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> SavedQueryListResponse:
    """
    Visibility rules:
      - Admin → sees everything
      - Regular user → sees own queries + is_shared=True queries
      - Restricted sensitivity queries are hidden from non-owners in shared lists
    """
    user_id = current_user["user_id"]
    is_admin = current_user["role"] == "admin"

    # Base visibility filter
    if is_admin:
        visibility_clause = []  # No restriction for admins
    else:
        visibility_clause = [
            or_(
                SavedQuery.user_id == uuid.UUID(user_id),
                # Shared but not restricted
                (SavedQuery.is_shared == True) &  # noqa: E712
                (SavedQuery.sensitivity != SensitivityLevel.restricted.value),
            )
        ]

    conditions = list(visibility_clause)

    # Optional filters
    if name:
        conditions.append(SavedQuery.name.ilike(f"%{name}%"))
    if tag:
        conditions.append(SavedQuery.tags.any(tag))
    if connection_id:
        try:
            cid = uuid.UUID(connection_id)
            conditions.append(SavedQuery.connection_id == cid)
        except ValueError:
            raise ValidationError(
                message="Invalid connection_id format.",
                detail=f"connection_id={connection_id!r} is not a valid UUID",
            )

    count_stmt = select(func.count()).select_from(SavedQuery)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    data_stmt = (
        select(SavedQuery)
        .order_by(SavedQuery.is_pinned.desc(), SavedQuery.updated_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if conditions:
        data_stmt = data_stmt.where(*conditions)
    queries = (await db.execute(data_stmt)).scalars().all()

    log.info(
        "saved_queries.list",
        user_id=user_id,
        total=total,
        is_admin=is_admin,
    )

    return SavedQueryListResponse(
        queries=[_sq_to_response(q) for q in queries],
        total=total,
        skip=skip,
        limit=limit,
    )


# =============================================================================
# GET /{query_id}  — Get single saved query
# =============================================================================

@router.get(
    "/{query_id}",
    response_model=SavedQueryResponse,
    summary="Get saved query",
    description="Retrieve a single saved query. Ownership and sensitivity rules apply.",
)
async def get_saved_query(
    query_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> SavedQueryResponse:
    sq = await _get_sq_or_404(query_id, db)
    _assert_readable(sq, current_user)

    log.info(
        "saved_queries.get",
        user_id=current_user["user_id"],
        query_id=str(query_id),
    )
    return _sq_to_response(sq)


# =============================================================================
# POST /  — Create saved query
# =============================================================================

@router.post(
    "/",
    response_model=SavedQueryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create saved query",
    description=(
        "Save a query to the library. Any active user may create saved queries. "
        "The new query is owned by the calling user."
    ),
)
async def create_saved_query(
    request: Request,
    body: SavedQueryCreateRequest,
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> SavedQueryResponse:
    """
    Create a saved query owned by the calling user.

    connection_id is validated as a UUID but NOT checked for existence here —
    the query pipeline validates connection access before executing SQL (T43).
    """
    try:
        conn_uuid = uuid.UUID(body.connection_id)
    except ValueError:
        raise ValidationError(
            message="Invalid connection_id format.",
            detail=f"connection_id={body.connection_id!r} is not a valid UUID",
        )

    now = datetime.now(timezone.utc)
    sq = SavedQuery(
        id=uuid.uuid4(),
        user_id=uuid.UUID(current_user["user_id"]),
        connection_id=conn_uuid,
        name=body.name,
        description=body.description,
        question=body.question,
        sql_query=body.sql_query,
        tags=body.tags,
        sensitivity=body.sensitivity.value,
        is_shared=body.is_shared,
        is_pinned=body.is_pinned,
        run_count=0,
        last_run_at=None,
    )
    sq.created_at = now
    sq.updated_at = now

    db.add(sq)
    await db.commit()

    log.info(
        "saved_queries.created",
        user_id=current_user["user_id"],
        query_id=str(sq.id),
        name=sq.name,
        sensitivity=sq.sensitivity,
        is_shared=sq.is_shared,
    )

    if audit:
        await audit.log(
            execution_status="saved_query.created",
            question=f"User saved query: {body.name!r} (connection={body.connection_id})",
            user_id=current_user["user_id"],
            connection_id=conn_uuid,
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _sq_to_response(sq)


# =============================================================================
# PATCH /{query_id}  — Update saved query
# =============================================================================

@router.patch(
    "/{query_id}",
    response_model=SavedQueryResponse,
    summary="Update saved query",
    description=(
        "Partial-update a saved query. Only the owner or an admin may update. "
        "connection_id is immutable after creation."
    ),
)
async def update_saved_query(
    query_id: uuid.UUID,
    request: Request,
    body: SavedQueryUpdateRequest,
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> SavedQueryResponse:
    """Partial update — owner or admin only (T52)."""
    sq = await _get_sq_or_404(query_id, db)
    _assert_owner_or_admin(sq, current_user)

    changed_fields: list[str] = []

    if body.name is not None:
        sq.name = body.name
        changed_fields.append("name")
    if body.description is not None:
        sq.description = body.description
        changed_fields.append("description")
    if body.question is not None:
        sq.question = body.question
        changed_fields.append("question")
    if body.sql_query is not None:
        sq.sql_query = body.sql_query
        changed_fields.append("sql_query")
    if body.tags is not None:
        sq.tags = body.tags
        changed_fields.append("tags")
    if body.sensitivity is not None:
        sq.sensitivity = body.sensitivity.value
        changed_fields.append("sensitivity")
    if body.is_shared is not None:
        sq.is_shared = body.is_shared
        changed_fields.append("is_shared")
    if body.is_pinned is not None:
        sq.is_pinned = body.is_pinned
        changed_fields.append("is_pinned")

    sq.updated_at = datetime.now(timezone.utc)
    await db.commit()

    log.info(
        "saved_queries.updated",
        user_id=current_user["user_id"],
        query_id=str(query_id),
        changed_fields=changed_fields,
    )

    if audit and changed_fields:
        await audit.log(
            execution_status="saved_query.updated",
            question=(
                f"Saved query {sq.name!r} ({query_id}) "
                f"updated: {', '.join(changed_fields)}"
            ),
            user_id=current_user["user_id"],
            connection_id=sq.connection_id,
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _sq_to_response(sq)


# =============================================================================
# DELETE /{query_id}  — Delete saved query
# =============================================================================

@router.delete(
    "/{query_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete saved query",
    description="Permanently delete a saved query. Owner or admin only.",
)
async def delete_saved_query(
    query_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> Response:
    """Hard delete — saved queries have no downstream FK dependents."""
    sq = await _get_sq_or_404(query_id, db)
    _assert_owner_or_admin(sq, current_user)

    name_snapshot = sq.name
    conn_snapshot = sq.connection_id
    await db.delete(sq)
    await db.commit()

    log.info(
        "saved_queries.deleted",
        user_id=current_user["user_id"],
        query_id=str(query_id),
        name=name_snapshot,
    )

    if audit:
        await audit.log(
            execution_status="saved_query.deleted",
            question=f"Deleted saved query: {name_snapshot!r} ({query_id})",
            user_id=current_user["user_id"],
            connection_id=conn_snapshot,
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# POST /{query_id}/duplicate  — Duplicate a saved query
# =============================================================================

@router.post(
    "/{query_id}/duplicate",
    response_model=SavedQueryDuplicateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Duplicate saved query",
    description=(
        "Create a personal copy of an accessible saved query. "
        "The duplicate is always owned by the calling user, "
        "starts unshared and unpinned, with run_count reset to 0."
    ),
)
async def duplicate_saved_query(
    query_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> SavedQueryDuplicateResponse:
    """
    Copy a readable query into the current user's library.

    Access gate: _assert_readable (not _assert_owner_or_admin) —
    users may duplicate any query they can see (shared or own).
    The copy is always private (is_shared=False) and belongs to the caller.
    """
    sq = await _get_sq_or_404(query_id, db)
    _assert_readable(sq, current_user)

    now = datetime.now(timezone.utc)
    copy_name = f"Copy of {sq.name}"

    new_sq = SavedQuery(
        id=uuid.uuid4(),
        user_id=uuid.UUID(current_user["user_id"]),
        connection_id=sq.connection_id,
        name=copy_name,
        description=sq.description,
        question=sq.question,
        sql_query=sq.sql_query,
        tags=list(sq.tags or []),
        sensitivity=sq.sensitivity,
        is_shared=False,   # Always start private
        is_pinned=False,   # Always start unpinned
        run_count=0,
        last_run_at=None,
    )
    new_sq.created_at = now
    new_sq.updated_at = now

    db.add(new_sq)
    await db.commit()

    log.info(
        "saved_queries.duplicated",
        user_id=current_user["user_id"],
        source_id=str(query_id),
        new_id=str(new_sq.id),
    )

    if audit:
        await audit.log(
            execution_status="saved_query.duplicated",
            question=f"Duplicated saved query {sq.name!r} ({query_id}) → {copy_name!r}",
            user_id=current_user["user_id"],
            connection_id=new_sq.connection_id,
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return SavedQueryDuplicateResponse(
        query_id=str(new_sq.id),
        name=copy_name,
        message=f"Query duplicated as '{copy_name}'.",
    )


# =============================================================================
# PATCH /{query_id}/pin  — Toggle pin flag
# =============================================================================

@router.patch(
    "/{query_id}/pin",
    response_model=SavedQueryResponse,
    summary="Toggle pin",
    description="Toggle the is_pinned flag. Owner or admin only.",
)
async def toggle_pin(
    query_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> SavedQueryResponse:
    """Toggle is_pinned — owner or admin only (T52)."""
    sq = await _get_sq_or_404(query_id, db)
    _assert_owner_or_admin(sq, current_user)

    sq.is_pinned = not sq.is_pinned
    sq.updated_at = datetime.now(timezone.utc)
    await db.commit()

    log.info(
        "saved_queries.pin_toggled",
        user_id=current_user["user_id"],
        query_id=str(query_id),
        is_pinned=sq.is_pinned,
    )

    if audit:
        action = "pinned" if sq.is_pinned else "unpinned"
        await audit.log(
            execution_status=f"saved_query.{action}",
            question=f"Saved query {sq.name!r} ({query_id}) {action}",
            user_id=current_user["user_id"],
            connection_id=sq.connection_id,
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _sq_to_response(sq)


# =============================================================================
# PATCH /{query_id}/share  — Toggle shared flag
# =============================================================================

@router.patch(
    "/{query_id}/share",
    response_model=SavedQueryResponse,
    summary="Toggle share",
    description=(
        "Toggle the is_shared flag. Owner or admin only. "
        "Note: 'restricted' sensitivity queries cannot be shared — "
        "attempting to share one returns 422."
    ),
)
async def toggle_share(
    query_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> SavedQueryResponse:
    """
    Toggle is_shared — owner or admin only (T52).

    Restricted-sensitivity queries cannot be shared:
    sharing would expose them to non-owners, contradicting the restriction.
    """
    sq = await _get_sq_or_404(query_id, db)
    _assert_owner_or_admin(sq, current_user)

    # Cannot share a restricted query
    if not sq.is_shared and sq.sensitivity == SensitivityLevel.restricted:
        raise ValidationError(
            message="Restricted queries cannot be shared.",
            detail=(
                f"SavedQuery {sq.id} has sensitivity=restricted; "
                "set sensitivity to 'normal' or 'sensitive' before sharing"
            ),
        )

    sq.is_shared = not sq.is_shared
    sq.updated_at = datetime.now(timezone.utc)
    await db.commit()

    log.info(
        "saved_queries.share_toggled",
        user_id=current_user["user_id"],
        query_id=str(query_id),
        is_shared=sq.is_shared,
    )

    if audit:
        action = "shared" if sq.is_shared else "unshared"
        await audit.log(
            execution_status=f"saved_query.{action}",
            question=f"Saved query {sq.name!r} ({query_id}) {action}",
            user_id=current_user["user_id"],
            connection_id=sq.connection_id,
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _sq_to_response(sq)