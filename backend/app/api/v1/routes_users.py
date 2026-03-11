"""
Smart BI Agent — User Management Routes
Architecture v3.1 | Layer 4 (Application) | Threats: T10, T20, T53

ENDPOINTS:
    GET    /api/v1/users                    — paginated user list (admin only)
    GET    /api/v1/users/{user_id}          — single user (admin or own profile)
    POST   /api/v1/users                    — create user (admin only)
    PATCH  /api/v1/users/{user_id}          — update user (admin or limited self-service)
    DELETE /api/v1/users/{user_id}          — soft-deactivate user (admin only)
    POST   /api/v1/users/{user_id}/gdpr-erase — GDPR erasure (admin only)

ACCESS CONTROL:
    - All endpoints require authentication (JWT Bearer)
    - Most endpoints require admin role via require_admin()
    - GET /{user_id} and PATCH /{user_id}: admin OR owner
    - Self-service PATCH: name and department only (role/is_active/is_approved require admin)
    - DELETE and GDPR erase: admin cannot target their own account (prevents lockout)

SOFT DELETE POLICY:
    Users are NEVER hard-deleted (audit trail integrity, T20).
    DELETE sets is_active=False. GDPR erase anonymises PII but leaves the row.

GDPR ERASURE:
    Replaces all user PII with sentinel values:
      - name → "[GDPR_ERASED]"
      - email → "gdpr_erased_{id}@deleted.invalid"  (unique, DB-safe)
      - department → None
      - totp_secret_enc → None, totp_enabled → False
      - is_active → False
    Also updates audit_logs.question = "[GDPR_ERASED]" for all entries
    belonging to this user. This requires the DB role to have UPDATE
    privilege on audit_logs.question in production.

AUDIT TRAIL:
    Every state-changing action writes to AuditWriter (T20).
    question field summarises the admin action for audit correlation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUser,
    get_audit_writer,
    get_current_user,
    get_db,
    require_admin,
)
from app.errors.exceptions import (
    DuplicateResourceError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
    ResourceOwnershipError,
)
from app.logging.structured import get_logger
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.user import (
    GDPREraseResponse,
    UserCreateRequest,
    UserListResponse,
    UserListMeta,
    UserResponse,
    UserUpdateRequest,
)
from app.security.password import hash_password

log = get_logger(__name__)

router = APIRouter()


# =============================================================================
# Helpers
# =============================================================================

def _user_to_response(user: User) -> UserResponse:
    """Convert a User ORM object to a safe UserResponse schema."""
    return UserResponse(
        user_id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role,
        department=user.department,
        is_active=user.is_active,
        is_approved=user.is_approved,
        totp_enabled=user.totp_enabled,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


async def _get_user_or_404(user_id: uuid.UUID, db: AsyncSession) -> User:
    """
    Fetch a User by ID or raise ResourceNotFoundError.
    Centralised to ensure consistent 404 shape across all endpoints.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ResourceNotFoundError(
            message="User not found.",
            detail=f"User {user_id} does not exist",
        )
    return user


def _get_client_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For or direct connection."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# =============================================================================
# GET /  — List users
# =============================================================================

@router.get(
    "/",
    response_model=UserListResponse,
    summary="List users",
    description="Returns a paginated list of all users. Admin only.",
)
async def list_users(
    request: Request,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=200, description="Maximum records to return"),
    role: Optional[str] = Query(None, description="Filter by role (viewer/analyst/admin)"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, max_length=100, description="Search email or name"),
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserListResponse:
    """
    Return paginated user list with optional filters.

    Filters are combined with AND logic.
    search performs case-insensitive partial match on email and name.
    """
    # Build base filter conditions
    conditions = []
    if role is not None:
        conditions.append(User.role == role)
    if is_active is not None:
        conditions.append(User.is_active == is_active)
    if search:
        pattern = f"%{search}%"
        conditions.append(
            or_(
                User.email.ilike(pattern),
                User.name.ilike(pattern),
            )
        )

    # Count total matching records
    count_stmt = select(func.count()).select_from(User)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    # Fetch paginated data
    data_stmt = select(User).order_by(User.created_at.asc()).offset(skip).limit(limit)
    if conditions:
        data_stmt = data_stmt.where(*conditions)
    data_result = await db.execute(data_stmt)
    users = data_result.scalars().all()

    log.info(
        "users.list",
        admin_id=admin["user_id"],
        total=total,
        skip=skip,
        limit=limit,
        filters={"role": role, "is_active": is_active, "search": bool(search)},
    )

    return UserListResponse(
        users=[_user_to_response(u) for u in users],
        meta=UserListMeta(
            total=total,
            skip=skip,
            limit=limit,
            has_more=(skip + len(users)) < total,
        ),
    )


# =============================================================================
# GET /{user_id}  — Get single user
# =============================================================================

@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get user",
    description="Retrieve a user by ID. Admin can get any user; non-admin can only get themselves.",
)
async def get_user(
    user_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Fetch a single user.

    Access control:
      - Admin: any user
      - Non-admin: own profile only (ResourceOwnershipError → 403 on others,
        NOT 404, to avoid leaking user existence — IDOR prevention)
    """
    is_admin = current_user["role"] == "admin"
    is_self = str(user_id) == current_user["user_id"]

    # Non-admin requesting someone else's profile — 403 (not 404, IDOR prevention)
    if not is_admin and not is_self:
        raise ResourceOwnershipError(
            detail=f"User {current_user['user_id']} attempted to access profile of {user_id}",
        )

    user = await _get_user_or_404(user_id, db)

    log.info(
        "users.get",
        requester_id=current_user["user_id"],
        target_user_id=str(user_id),
        is_self=is_self,
    )
    return _user_to_response(user)


# =============================================================================
# POST /  — Create user
# =============================================================================

@router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create user",
    description="Create a new user account. Admin only.",
)
async def create_user(
    request: Request,
    body: UserCreateRequest,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> UserResponse:
    """
    Create a new user account.

    - Email is stored fully lowercased (already normalised by schema validator)
    - Password is immediately hashed with bcrypt cost-12 — plaintext is never stored
    - New accounts are created with is_approved=False by default (T53)
    - Admin can set role, department at creation time
    """
    # Check for duplicate email — case-insensitive (emails are stored lowercased)
    dup_result = await db.execute(
        select(User).where(User.email == body.email.lower())
    )
    if dup_result.scalar_one_or_none() is not None:
        raise DuplicateResourceError(
            message="A user with this email address already exists.",
            detail=f"Duplicate email: {body.email}",
        )

    # Create new user with explicit UUID so response is correct without DB flush
    now = datetime.now(timezone.utc)
    new_user = User(
        id=uuid.uuid4(),
        email=body.email.lower(),
        name=body.name,
        hashed_password=hash_password(body.password),
        role=body.role.value,
        department=body.department,
        is_active=True,
        is_approved=False,   # Requires admin approval after creation (T53)
        totp_enabled=False,
    )
    # Set timestamps explicitly for test compatibility
    # (server_default fires on DB INSERT, not Python constructor)
    new_user.created_at = now
    new_user.updated_at = now

    db.add(new_user)
    await db.commit()

    log.info(
        "users.created",
        admin_id=admin["user_id"],
        new_user_id=str(new_user.id),
        email=new_user.email,
        role=new_user.role,
    )

    if audit:
        await audit.log(
            execution_status="user.created",
            question=f"Admin created user: {new_user.email} (role={new_user.role})",
            user_id=admin["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _user_to_response(new_user)


# =============================================================================
# PATCH /{user_id}  — Update user
# =============================================================================

@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update user",
    description=(
        "Update user fields. Admin can update all fields. "
        "Non-admin can only update their own name and department."
    ),
)
async def update_user(
    user_id: uuid.UUID,
    request: Request,
    body: UserUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> UserResponse:
    """
    Partial update a user record.

    Field-level access control:
      - name, department: admin OR self
      - role, is_active, is_approved: admin ONLY

    A non-admin attempting to update admin-only fields has those fields
    silently ignored (the update proceeds for allowed fields). If they
    attempt to update ANOTHER user, ResourceOwnershipError (403) is raised.
    """
    is_admin = current_user["role"] == "admin"
    is_self = str(user_id) == current_user["user_id"]

    # Non-admin updating someone else: 403 (IDOR prevention, same as GET)
    if not is_admin and not is_self:
        raise ResourceOwnershipError(
            detail=f"User {current_user['user_id']} attempted to update profile of {user_id}",
        )

    user = await _get_user_or_404(user_id, db)

    # Apply fields — admin-only fields rejected silently for self-service
    changed_fields: list[str] = []

    if body.name is not None:
        user.name = body.name
        changed_fields.append("name")

    if body.department is not None:
        user.department = body.department
        changed_fields.append("department")

    # Admin-only fields — silently ignore if non-admin (T10: no info leak)
    if is_admin:
        if body.role is not None:
            user.role = body.role.value
            changed_fields.append("role")
        if body.is_active is not None:
            user.is_active = body.is_active
            changed_fields.append("is_active")
        if body.is_approved is not None:
            user.is_approved = body.is_approved
            changed_fields.append("is_approved")
    else:
        # Non-admin supplied admin-only fields → 403
        if body.role is not None or body.is_active is not None or body.is_approved is not None:
            raise InsufficientPermissionsError(
                message="You do not have permission to modify role or account status.",
                detail="Non-admin attempted to set role/is_active/is_approved",
            )

    await db.commit()

    log.info(
        "users.updated",
        updater_id=current_user["user_id"],
        target_user_id=str(user_id),
        changed_fields=changed_fields,
    )

    if audit and changed_fields:
        await audit.log(
            execution_status="user.updated",
            question=f"User {user_id} updated fields: {', '.join(changed_fields)}",
            user_id=current_user["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _user_to_response(user)


# =============================================================================
# DELETE /{user_id}  — Soft-deactivate user
# =============================================================================

@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate user",
    description="Soft-deactivate a user account. Admin only. Cannot deactivate own account.",
)
async def deactivate_user(
    user_id: uuid.UUID,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> Response:
    """
    Soft-deactivate a user by setting is_active=False.

    Hard deletion is never performed — audit trail integrity (T20) requires
    that user records persist. The user will be unable to log in but their
    audit history remains intact.

    An admin cannot deactivate their own account to prevent accidental lockout.
    """
    if str(user_id) == admin["user_id"]:
        raise InsufficientPermissionsError(
            message="You cannot deactivate your own account.",
            detail="Admin attempted self-deactivation",
        )

    user = await _get_user_or_404(user_id, db)

    user.is_active = False
    await db.commit()

    log.warning(
        "users.deactivated",
        admin_id=admin["user_id"],
        deactivated_user_id=str(user_id),
        email=user.email,
    )

    if audit:
        await audit.log(
            execution_status="user.deactivated",
            question=f"Admin deactivated user: {user.email} ({user_id})",
            user_id=admin["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# POST /{user_id}/gdpr-erase  — GDPR erasure
# =============================================================================

@router.post(
    "/{user_id}/gdpr-erase",
    response_model=GDPREraseResponse,
    summary="GDPR erase user",
    description=(
        "Permanently anonymise all PII for a user. "
        "Irreversible. Admin only. Cannot erase own account."
    ),
)
async def gdpr_erase_user(
    user_id: uuid.UUID,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> GDPREraseResponse:
    """
    GDPR right-to-erasure implementation.

    Anonymises all personally-identifiable fields on the User record:
      - name       → "[GDPR_ERASED]"
      - email      → "gdpr_erased_{id}@deleted.invalid" (unique, DB constraint safe)
      - department → None
      - TOTP secret erased, TOTP disabled
      - Account deactivated

    Also updates audit_logs.question = "[GDPR_ERASED]" for all entries
    belonging to this user — the only PII-bearing audit field (T20, GDPR).

    NOTE: This requires the DB application role to have UPDATE privilege
    on audit_logs.question. In production, a dedicated migration grants
    this to the gdpr_eraser role. The append-only constraint on INSERT
    remains; only the question column is updatable.

    An admin cannot erase their own account.
    """
    if str(user_id) == admin["user_id"]:
        raise InsufficientPermissionsError(
            message="You cannot erase your own account.",
            detail="Admin attempted self-erasure",
        )

    user = await _get_user_or_404(user_id, db)

    erased_email = f"gdpr_erased_{user_id}@deleted.invalid"
    user.name = "[GDPR_ERASED]"
    user.email = erased_email
    user.department = None
    user.totp_secret_enc = None
    user.totp_enabled = False
    user.is_active = False

    # Anonymise the question field in all audit entries for this user.
    # This is the only PII-bearing field in audit_logs per architecture.
    await db.execute(
        update(AuditLog)
        .where(AuditLog.user_id == user_id)
        .values(question="[GDPR_ERASED]")
    )

    await db.commit()

    log.warning(
        "users.gdpr_erased",
        admin_id=admin["user_id"],
        erased_user_id=str(user_id),
    )

    if audit:
        await audit.log(
            execution_status="user.gdpr_erased",
            question=f"GDPR erasure performed for user {user_id}",
            user_id=admin["user_id"],
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return GDPREraseResponse(
        message="User data has been permanently erased in compliance with GDPR.",
        erased_user_id=str(user_id),
    )