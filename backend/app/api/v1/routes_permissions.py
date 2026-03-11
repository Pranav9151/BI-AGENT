"""
Smart BI Agent — Permission Management Routes
Architecture v3.1 | Layer 4 (Application) | Threats: T20 (audit), T56 (race conditions)

3-TIER RBAC (role → department → user override):
    Tier 1: RolePermission      — baseline per role  (viewer/analyst/admin)
    Tier 2: DepartmentPermission — refinement per department
    Tier 3: UserPermission      — explicit per-user override (highest precedence)

    Each tier is scoped to a connection_id. Access to connection A is fully
    independent from access to connection B.

ENDPOINTS:
    Role permissions:
        GET    /api/v1/permissions/roles               — list
        GET    /api/v1/permissions/roles/{id}          — get one
        POST   /api/v1/permissions/roles               — create
        PATCH  /api/v1/permissions/roles/{id}          — update
        DELETE /api/v1/permissions/roles/{id}          — delete

    Department permissions:
        GET    /api/v1/permissions/departments          — list (filter by dept)
        GET    /api/v1/permissions/departments/{id}     — get one
        POST   /api/v1/permissions/departments          — create
        PATCH  /api/v1/permissions/departments/{id}     — update
        DELETE /api/v1/permissions/departments/{id}     — delete

    User permissions:
        GET    /api/v1/permissions/users                — list (filter by user_id)
        GET    /api/v1/permissions/users/{id}           — get one
        POST   /api/v1/permissions/users                — create
        PATCH  /api/v1/permissions/users/{id}           — update
        DELETE /api/v1/permissions/users/{id}           — delete

ACCESS CONTROL:
    All endpoints are admin-only — permission management is the highest-privilege
    administrative action (misconfiguration directly controls data exposure).

IDENTIFIER SANITIZATION:
    All table and column names in allowed_tables / denied_tables / denied_columns
    are sanitized with sanitize_schema_identifier() before storage. This prevents
    prompt-injection attacks via maliciously named identifiers flowing into LLM
    prompts during schema introspection (Component 11).

AUDIT:
    Every mutating action (create, update, delete) writes to AuditWriter.
    The question field summarises the permission change for compliance review.

T56 — RACE CONDITIONS:
    Permissions are loaded per-request (not cached per-session) by the query
    pipeline. The DB is the source of truth. No in-memory permission state
    accumulates across requests. Atomic DB reads prevent TOCTOU.
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
    require_admin,
)
from app.errors.exceptions import ResourceNotFoundError
from app.logging.structured import get_logger
from app.models.permission import (
    DepartmentPermission,
    RolePermission,
    UserPermission,
)
from app.schemas.permission import (
    DepartmentPermissionCreateRequest,
    DepartmentPermissionListResponse,
    DepartmentPermissionResponse,
    DepartmentPermissionUpdateRequest,
    RolePermissionCreateRequest,
    RolePermissionListResponse,
    RolePermissionResponse,
    RolePermissionUpdateRequest,
    UserPermissionCreateRequest,
    UserPermissionListResponse,
    UserPermissionResponse,
    UserPermissionUpdateRequest,
)
from app.security.sanitizer import sanitize_schema_identifier

log = get_logger(__name__)

router = APIRouter()


# =============================================================================
# Helpers
# =============================================================================

def _sanitize_identifiers(names: list[str]) -> list[str]:
    """
    Sanitize a list of table or column identifiers.

    Strips characters that could enable prompt injection when these names
    are embedded into LLM prompts during schema introspection.
    Empty strings produced by sanitization are filtered out.
    """
    return [s for s in (sanitize_schema_identifier(n) for n in names) if s]


def _get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _audit(audit, *, status: str, question: str, admin_id: str, request: Request) -> None:
    if audit:
        await audit.log(
            execution_status=status,
            question=question,
            user_id=admin_id,
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )


# =============================================================================
# ROLE PERMISSIONS
# =============================================================================

def _role_perm_to_response(p: RolePermission) -> RolePermissionResponse:
    return RolePermissionResponse(
        permission_id=str(p.id),
        role=p.role,
        connection_id=str(p.connection_id),
        allowed_tables=p.allowed_tables or [],
        denied_columns=p.denied_columns or [],
        created_at=p.created_at if not isinstance(p.created_at, str) else None,
    )


async def _get_role_perm_or_404(perm_id: uuid.UUID, db: AsyncSession) -> RolePermission:
    result = await db.execute(select(RolePermission).where(RolePermission.id == perm_id))
    perm = result.scalar_one_or_none()
    if perm is None:
        raise ResourceNotFoundError(
            message="Role permission not found.",
            detail=f"RolePermission {perm_id} does not exist",
        )
    return perm


@router.get(
    "/roles",
    response_model=RolePermissionListResponse,
    summary="List role permissions",
)
async def list_role_permissions(
    request: Request,
    role: Optional[str] = Query(None, description="Filter by role name"),
    connection_id: Optional[str] = Query(None, description="Filter by connection UUID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RolePermissionListResponse:
    """List role permissions with optional role/connection filters."""
    conditions = []
    if role:
        conditions.append(RolePermission.role == role)
    if connection_id:
        try:
            conditions.append(RolePermission.connection_id == uuid.UUID(connection_id))
        except ValueError:
            return RolePermissionListResponse(permissions=[], total=0)

    count_stmt = select(func.count()).select_from(RolePermission)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    data_stmt = select(RolePermission).order_by(RolePermission.created_at.asc()).offset(skip).limit(limit)
    if conditions:
        data_stmt = data_stmt.where(*conditions)
    perms = (await db.execute(data_stmt)).scalars().all()

    return RolePermissionListResponse(
        permissions=[_role_perm_to_response(p) for p in perms],
        total=total,
    )


@router.get(
    "/roles/{permission_id}",
    response_model=RolePermissionResponse,
    summary="Get role permission",
)
async def get_role_permission(
    permission_id: uuid.UUID,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RolePermissionResponse:
    perm = await _get_role_perm_or_404(permission_id, db)
    return _role_perm_to_response(perm)


@router.post(
    "/roles",
    response_model=RolePermissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create role permission",
)
async def create_role_permission(
    request: Request,
    body: RolePermissionCreateRequest,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> RolePermissionResponse:
    """
    Set baseline table/column permissions for a role on a connection.
    Table and column names are sanitized before storage.
    """
    now = datetime.now(timezone.utc)
    perm = RolePermission(
        id=uuid.uuid4(),
        role=body.role,
        connection_id=uuid.UUID(body.connection_id),
        allowed_tables=_sanitize_identifiers(body.allowed_tables),
        denied_columns=_sanitize_identifiers(body.denied_columns),
    )
    perm.created_at = now

    db.add(perm)
    await db.commit()

    log.info("permissions.role.created", admin_id=admin["user_id"], role=body.role, connection_id=body.connection_id)
    await _audit(
        audit,
        status="permission.role.created",
        question=f"Role permission created: role={body.role} connection={body.connection_id} "
                 f"allowed_tables={body.allowed_tables}",
        admin_id=admin["user_id"],
        request=request,
    )
    return _role_perm_to_response(perm)


@router.patch(
    "/roles/{permission_id}",
    response_model=RolePermissionResponse,
    summary="Update role permission",
)
async def update_role_permission(
    permission_id: uuid.UUID,
    request: Request,
    body: RolePermissionUpdateRequest,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> RolePermissionResponse:
    perm = await _get_role_perm_or_404(permission_id, db)
    changed: list[str] = []

    if body.allowed_tables is not None:
        perm.allowed_tables = _sanitize_identifiers(body.allowed_tables)
        changed.append("allowed_tables")
    if body.denied_columns is not None:
        perm.denied_columns = _sanitize_identifiers(body.denied_columns)
        changed.append("denied_columns")

    await db.commit()

    log.info("permissions.role.updated", admin_id=admin["user_id"], permission_id=str(permission_id), changed=changed)
    if changed:
        await _audit(
            audit,
            status="permission.role.updated",
            question=f"Role permission {permission_id} updated: {', '.join(changed)}",
            admin_id=admin["user_id"],
            request=request,
        )
    return _role_perm_to_response(perm)


@router.delete(
    "/roles/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete role permission",
)
async def delete_role_permission(
    permission_id: uuid.UUID,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> Response:
    perm = await _get_role_perm_or_404(permission_id, db)
    await db.delete(perm)
    await db.commit()

    log.info("permissions.role.deleted", admin_id=admin["user_id"], permission_id=str(permission_id))
    await _audit(
        audit,
        status="permission.role.deleted",
        question=f"Role permission {permission_id} deleted (role={perm.role})",
        admin_id=admin["user_id"],
        request=request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# DEPARTMENT PERMISSIONS
# =============================================================================

def _dept_perm_to_response(p: DepartmentPermission) -> DepartmentPermissionResponse:
    return DepartmentPermissionResponse(
        permission_id=str(p.id),
        department=p.department,
        connection_id=str(p.connection_id),
        allowed_tables=p.allowed_tables or [],
        denied_columns=p.denied_columns or [],
        created_at=p.created_at if not isinstance(p.created_at, str) else None,
    )


async def _get_dept_perm_or_404(perm_id: uuid.UUID, db: AsyncSession) -> DepartmentPermission:
    result = await db.execute(select(DepartmentPermission).where(DepartmentPermission.id == perm_id))
    perm = result.scalar_one_or_none()
    if perm is None:
        raise ResourceNotFoundError(
            message="Department permission not found.",
            detail=f"DepartmentPermission {perm_id} does not exist",
        )
    return perm


@router.get(
    "/departments",
    response_model=DepartmentPermissionListResponse,
    summary="List department permissions",
)
async def list_department_permissions(
    request: Request,
    department: Optional[str] = Query(None, description="Filter by department name"),
    connection_id: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DepartmentPermissionListResponse:
    conditions = []
    if department:
        conditions.append(DepartmentPermission.department == department)
    if connection_id:
        try:
            conditions.append(DepartmentPermission.connection_id == uuid.UUID(connection_id))
        except ValueError:
            return DepartmentPermissionListResponse(permissions=[], total=0)

    count_stmt = select(func.count()).select_from(DepartmentPermission)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    data_stmt = select(DepartmentPermission).order_by(DepartmentPermission.created_at.asc()).offset(skip).limit(limit)
    if conditions:
        data_stmt = data_stmt.where(*conditions)
    perms = (await db.execute(data_stmt)).scalars().all()

    return DepartmentPermissionListResponse(
        permissions=[_dept_perm_to_response(p) for p in perms],
        total=total,
    )


@router.get(
    "/departments/{permission_id}",
    response_model=DepartmentPermissionResponse,
    summary="Get department permission",
)
async def get_department_permission(
    permission_id: uuid.UUID,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DepartmentPermissionResponse:
    perm = await _get_dept_perm_or_404(permission_id, db)
    return _dept_perm_to_response(perm)


@router.post(
    "/departments",
    response_model=DepartmentPermissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create department permission",
)
async def create_department_permission(
    request: Request,
    body: DepartmentPermissionCreateRequest,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> DepartmentPermissionResponse:
    now = datetime.now(timezone.utc)
    perm = DepartmentPermission(
        id=uuid.uuid4(),
        department=body.department,
        connection_id=uuid.UUID(body.connection_id),
        allowed_tables=_sanitize_identifiers(body.allowed_tables),
        denied_columns=_sanitize_identifiers(body.denied_columns),
    )
    perm.created_at = now

    db.add(perm)
    await db.commit()

    log.info("permissions.dept.created", admin_id=admin["user_id"], department=body.department)
    await _audit(
        audit,
        status="permission.dept.created",
        question=f"Dept permission created: dept={body.department} connection={body.connection_id} "
                 f"allowed_tables={body.allowed_tables}",
        admin_id=admin["user_id"],
        request=request,
    )
    return _dept_perm_to_response(perm)


@router.patch(
    "/departments/{permission_id}",
    response_model=DepartmentPermissionResponse,
    summary="Update department permission",
)
async def update_department_permission(
    permission_id: uuid.UUID,
    request: Request,
    body: DepartmentPermissionUpdateRequest,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> DepartmentPermissionResponse:
    perm = await _get_dept_perm_or_404(permission_id, db)
    changed: list[str] = []

    if body.allowed_tables is not None:
        perm.allowed_tables = _sanitize_identifiers(body.allowed_tables)
        changed.append("allowed_tables")
    if body.denied_columns is not None:
        perm.denied_columns = _sanitize_identifiers(body.denied_columns)
        changed.append("denied_columns")

    await db.commit()

    log.info("permissions.dept.updated", admin_id=admin["user_id"], permission_id=str(permission_id))
    if changed:
        await _audit(
            audit,
            status="permission.dept.updated",
            question=f"Dept permission {permission_id} updated: {', '.join(changed)}",
            admin_id=admin["user_id"],
            request=request,
        )
    return _dept_perm_to_response(perm)


@router.delete(
    "/departments/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete department permission",
)
async def delete_department_permission(
    permission_id: uuid.UUID,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> Response:
    perm = await _get_dept_perm_or_404(permission_id, db)
    await db.delete(perm)
    await db.commit()

    log.info("permissions.dept.deleted", admin_id=admin["user_id"], permission_id=str(permission_id))
    await _audit(
        audit,
        status="permission.dept.deleted",
        question=f"Dept permission {permission_id} deleted (dept={perm.department})",
        admin_id=admin["user_id"],
        request=request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# USER PERMISSIONS
# =============================================================================

def _user_perm_to_response(p: UserPermission) -> UserPermissionResponse:
    return UserPermissionResponse(
        permission_id=str(p.id),
        user_id=str(p.user_id),
        connection_id=str(p.connection_id),
        allowed_tables=p.allowed_tables or [],
        denied_tables=p.denied_tables or [],
        denied_columns=p.denied_columns or [],
        created_at=p.created_at if not isinstance(p.created_at, str) else None,
    )


async def _get_user_perm_or_404(perm_id: uuid.UUID, db: AsyncSession) -> UserPermission:
    result = await db.execute(select(UserPermission).where(UserPermission.id == perm_id))
    perm = result.scalar_one_or_none()
    if perm is None:
        raise ResourceNotFoundError(
            message="User permission not found.",
            detail=f"UserPermission {perm_id} does not exist",
        )
    return perm


@router.get(
    "/users",
    response_model=UserPermissionListResponse,
    summary="List user permissions",
)
async def list_user_permissions(
    request: Request,
    user_id: Optional[str] = Query(None, description="Filter by user UUID"),
    connection_id: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserPermissionListResponse:
    conditions = []
    if user_id:
        try:
            conditions.append(UserPermission.user_id == uuid.UUID(user_id))
        except ValueError:
            return UserPermissionListResponse(permissions=[], total=0)
    if connection_id:
        try:
            conditions.append(UserPermission.connection_id == uuid.UUID(connection_id))
        except ValueError:
            return UserPermissionListResponse(permissions=[], total=0)

    count_stmt = select(func.count()).select_from(UserPermission)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    data_stmt = select(UserPermission).order_by(UserPermission.created_at.asc()).offset(skip).limit(limit)
    if conditions:
        data_stmt = data_stmt.where(*conditions)
    perms = (await db.execute(data_stmt)).scalars().all()

    return UserPermissionListResponse(
        permissions=[_user_perm_to_response(p) for p in perms],
        total=total,
    )


@router.get(
    "/users/{permission_id}",
    response_model=UserPermissionResponse,
    summary="Get user permission",
)
async def get_user_permission(
    permission_id: uuid.UUID,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserPermissionResponse:
    perm = await _get_user_perm_or_404(permission_id, db)
    return _user_perm_to_response(perm)


@router.post(
    "/users",
    response_model=UserPermissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create user permission",
)
async def create_user_permission(
    request: Request,
    body: UserPermissionCreateRequest,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> UserPermissionResponse:
    """
    Set the highest-precedence permission override for a specific user
    on a specific connection.

    denied_tables overrides any role/department allowance for this user.
    """
    now = datetime.now(timezone.utc)
    perm = UserPermission(
        id=uuid.uuid4(),
        user_id=uuid.UUID(body.user_id),
        connection_id=uuid.UUID(body.connection_id),
        allowed_tables=_sanitize_identifiers(body.allowed_tables),
        denied_tables=_sanitize_identifiers(body.denied_tables),
        denied_columns=_sanitize_identifiers(body.denied_columns),
    )
    perm.created_at = now

    db.add(perm)
    await db.commit()

    log.info("permissions.user.created", admin_id=admin["user_id"], target_user_id=body.user_id)
    await _audit(
        audit,
        status="permission.user.created",
        question=f"User permission created: user={body.user_id} connection={body.connection_id} "
                 f"allowed={body.allowed_tables} denied={body.denied_tables}",
        admin_id=admin["user_id"],
        request=request,
    )
    return _user_perm_to_response(perm)


@router.patch(
    "/users/{permission_id}",
    response_model=UserPermissionResponse,
    summary="Update user permission",
)
async def update_user_permission(
    permission_id: uuid.UUID,
    request: Request,
    body: UserPermissionUpdateRequest,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> UserPermissionResponse:
    perm = await _get_user_perm_or_404(permission_id, db)
    changed: list[str] = []

    if body.allowed_tables is not None:
        perm.allowed_tables = _sanitize_identifiers(body.allowed_tables)
        changed.append("allowed_tables")
    if body.denied_tables is not None:
        perm.denied_tables = _sanitize_identifiers(body.denied_tables)
        changed.append("denied_tables")
    if body.denied_columns is not None:
        perm.denied_columns = _sanitize_identifiers(body.denied_columns)
        changed.append("denied_columns")

    await db.commit()

    log.info("permissions.user.updated", admin_id=admin["user_id"], permission_id=str(permission_id))
    if changed:
        await _audit(
            audit,
            status="permission.user.updated",
            question=f"User permission {permission_id} updated: {', '.join(changed)}",
            admin_id=admin["user_id"],
            request=request,
        )
    return _user_perm_to_response(perm)


@router.delete(
    "/users/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete user permission",
)
async def delete_user_permission(
    permission_id: uuid.UUID,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> Response:
    perm = await _get_user_perm_or_404(permission_id, db)
    await db.delete(perm)
    await db.commit()

    log.info("permissions.user.deleted", admin_id=admin["user_id"], permission_id=str(permission_id))
    await _audit(
        audit,
        status="permission.user.deleted",
        question=f"User permission {permission_id} deleted (user={perm.user_id})",
        admin_id=admin["user_id"],
        request=request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)