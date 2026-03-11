"""
Smart BI Agent — Permission Schemas
Architecture v3.1 | Layer 4 | 3-tier RBAC: role → department → user override

Resolution order (lowest → highest precedence):
    Tier 1 — RolePermission:        baseline per role (viewer/analyst/admin)
    Tier 2 — DepartmentPermission:  refinement per department
    Tier 3 — UserPermission:        explicit per-user override (highest precedence)

Each tier is scoped to a specific connection_id so permissions are always
per-connection — a user's access to connection A is completely independent
of their access to connection B.

Security note:
    Table and column names in allowed_tables / denied_columns / denied_tables
    are sanitized with sanitize_schema_identifier() at the route layer before
    storage. This prevents prompt-injection via malicious identifier names.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Role Permission Schemas
# =============================================================================

class RolePermissionCreateRequest(BaseModel):
    """
    POST /api/v1/permissions/roles

    Sets the baseline table/column permissions for a role on a connection.
    allowed_tables:  only these tables may be queried (empty = all allowed)
    denied_columns:  these columns are always masked regardless of role
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    role: str = Field(..., description="Role name: viewer | analyst | admin")
    connection_id: str = Field(..., description="UUID of the target connection")
    allowed_tables: list[str] = Field(
        default=[],
        description="Allowlist of table names. Empty list = all tables permitted.",
    )
    denied_columns: list[str] = Field(
        default=[],
        description="Columns always denied regardless of allowed_tables.",
    )


class RolePermissionUpdateRequest(BaseModel):
    """PATCH /api/v1/permissions/roles/{id} — partial update."""
    model_config = ConfigDict(str_strip_whitespace=True)

    allowed_tables: Optional[list[str]] = None
    denied_columns: Optional[list[str]] = None


class RolePermissionResponse(BaseModel):
    """Single role permission record."""
    model_config = ConfigDict(from_attributes=True)

    permission_id: str
    role: str
    connection_id: str
    allowed_tables: list[str]
    denied_columns: list[str]
    created_at: Optional[datetime] = None


# =============================================================================
# Department Permission Schemas
# =============================================================================

class DepartmentPermissionCreateRequest(BaseModel):
    """
    POST /api/v1/permissions/departments

    Refines access for a department within a connection.
    Takes precedence over role permissions for members of this department.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    department: str = Field(..., min_length=1, max_length=100)
    connection_id: str = Field(..., description="UUID of the target connection")
    allowed_tables: list[str] = Field(default=[])
    denied_columns: list[str] = Field(default=[])


class DepartmentPermissionUpdateRequest(BaseModel):
    """PATCH /api/v1/permissions/departments/{id} — partial update."""
    model_config = ConfigDict(str_strip_whitespace=True)

    allowed_tables: Optional[list[str]] = None
    denied_columns: Optional[list[str]] = None


class DepartmentPermissionResponse(BaseModel):
    """Single department permission record."""
    model_config = ConfigDict(from_attributes=True)

    permission_id: str
    department: str
    connection_id: str
    allowed_tables: list[str]
    denied_columns: list[str]
    created_at: Optional[datetime] = None


# =============================================================================
# User Permission Schemas
# =============================================================================

class UserPermissionCreateRequest(BaseModel):
    """
    POST /api/v1/permissions/users

    Highest-precedence override for a specific user on a connection.
    allowed_tables: explicit allowlist for this user
    denied_tables:  explicit denylist (blocks even if role/dept allow it)
    denied_columns: column-level masking for this user
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    user_id: str = Field(..., description="UUID of the target user")
    connection_id: str = Field(..., description="UUID of the target connection")
    allowed_tables: list[str] = Field(default=[])
    denied_tables: list[str] = Field(
        default=[],
        description="Explicitly blocked tables — override any role/dept allowance.",
    )
    denied_columns: list[str] = Field(default=[])


class UserPermissionUpdateRequest(BaseModel):
    """PATCH /api/v1/permissions/users/{id} — partial update."""
    model_config = ConfigDict(str_strip_whitespace=True)

    allowed_tables: Optional[list[str]] = None
    denied_tables: Optional[list[str]] = None
    denied_columns: Optional[list[str]] = None


class UserPermissionResponse(BaseModel):
    """Single user permission record."""
    model_config = ConfigDict(from_attributes=True)

    permission_id: str
    user_id: str
    connection_id: str
    allowed_tables: list[str]
    denied_tables: list[str]
    denied_columns: list[str]
    created_at: Optional[datetime] = None


# =============================================================================
# List Response Schemas
# =============================================================================

class RolePermissionListResponse(BaseModel):
    permissions: list[RolePermissionResponse]
    total: int


class DepartmentPermissionListResponse(BaseModel):
    permissions: list[DepartmentPermissionResponse]
    total: int


class UserPermissionListResponse(BaseModel):
    permissions: list[UserPermissionResponse]
    total: int