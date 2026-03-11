"""
Smart BI Agent — User Schemas
Architecture v3.1 | Layer 4 | Threats: T4, T8, T10, T53

Request and response schemas for user management endpoints.

Security notes:
  - Password handled with min_length 8, max_length 128 (bcrypt limit protection)
  - Email always lowercased before processing (T10 — enumeration prevention)
  - hashed_password, totp_secret_enc never appear in any response schema
  - role changes are restricted to admin only (enforced in routes, schema is passive)
  - GDPR erasure replaces all PII with [GDPR_ERASED] sentinel
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# =============================================================================
# Enums
# =============================================================================

class UserRole(str, Enum):
    """Valid user roles — ordered from least to most privileged."""
    viewer = "viewer"
    analyst = "analyst"
    admin = "admin"


# =============================================================================
# Request Schemas
# =============================================================================

class UserCreateRequest(BaseModel):
    """
    POST /api/v1/users — body.

    Admin-only. Password is hashed at the route layer with bcrypt cost-12.
    Email is normalised to fully lowercase before storage (T10).
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr = Field(..., description="User email address")
    name: str = Field(..., min_length=1, max_length=255, description="Display name")
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Initial password (min 8 chars, max 128 to protect bcrypt)",
    )
    role: UserRole = Field(
        UserRole.viewer,
        description="User role — defaults to viewer (least privilege)",
    )
    department: Optional[str] = Field(
        None,
        max_length=100,
        description="Optional department name",
    )

    @field_validator("email", mode="before")
    @classmethod
    def lowercase_email(cls, v: object) -> object:
        """
        Fully lowercase the email BEFORE EmailStr validation.
        EmailStr normalises only the domain part (RFC-compliant), but we
        store and compare fully lowercased emails for consistency.
        """
        if isinstance(v, str):
            return v.strip().lower()
        return v


class UserUpdateRequest(BaseModel):
    """
    PATCH /api/v1/users/{user_id} — body.

    All fields are optional — only supplied fields are applied.

    Field access control (enforced in route, not schema):
      - Admin can update: name, department, role, is_active, is_approved
      - Self (non-admin) can update: name, department ONLY
      - role, is_active, is_approved require admin

    Password changes are handled by a separate endpoint (future component).
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    department: Optional[str] = Field(None, max_length=100)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    is_approved: Optional[bool] = None


# =============================================================================
# Response Schemas
# =============================================================================

class UserResponse(BaseModel):
    """
    Single user representation — safe for external consumption.

    Intentionally excludes:
      - hashed_password    (never returned — T10)
      - totp_secret_enc    (HKDF-encrypted secret — never returned)
      - failed_login_attempts / locked_until  (internal security state)
    """
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    email: str
    name: str
    role: str
    department: Optional[str]
    is_active: bool
    is_approved: bool
    totp_enabled: bool
    last_login_at: Optional[datetime]
    created_at: Optional[datetime] = None


class UserListMeta(BaseModel):
    """Pagination metadata for list responses."""
    total: int = Field(..., description="Total number of matching users")
    skip: int = Field(..., description="Number of records skipped")
    limit: int = Field(..., description="Maximum records returned per page")
    has_more: bool = Field(..., description="True if more records exist beyond this page")


class UserListResponse(BaseModel):
    """Paginated list of users with metadata."""
    users: list[UserResponse]
    meta: UserListMeta


class GDPREraseResponse(BaseModel):
    """
    POST /api/v1/users/{user_id}/gdpr-erase — response.

    Returned after successful GDPR erasure. The erased_user_id is included
    so the caller can correlate with their own records.
    """
    message: str = "User data has been permanently erased in compliance with GDPR."
    erased_user_id: str