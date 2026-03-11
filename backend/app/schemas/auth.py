"""
Smart BI Agent — Auth Schemas
Architecture v3.1 | Layer 4 | Threats: T4, T8, T9, T10

All request schemas apply strict validation:
    - EmailStr normalises email addresses
    - Password length capped to prevent DoS (bcrypt is slow by design)
    - TOTP codes validated for digit-only format

Response schemas follow T10 (info leakage prevention):
    - No internal user IDs in error responses
    - Login response flags (totp_required) avoid leaking flow details beyond
      what the client strictly needs to render the next UI step
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# =============================================================================
# Login
# =============================================================================

class LoginRequest(BaseModel):
    """
    POST /api/v1/auth/login

    Password is capped at 128 chars on the wire (bcrypt pre-hash handles the
    actual 72-byte limit — see security/password.py). The 128 cap prevents
    clients from sending megabytes of data to abuse our intentionally slow hash.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="User password",
    )

    @field_validator("email", mode="before")
    @classmethod
    def lowercase_email(cls, v: object) -> object:
        """
        Normalise email to fully lowercase BEFORE EmailStr validation.
        EmailStr only lowercases the domain (RFC-compliant), but we always
        store/compare fully lowercased emails. Running mode="before" ensures
        the local part is lowercased before email-validator normalises it.
        """
        if isinstance(v, str):
            return v.strip().lower()
        return v


class LoginResponse(BaseModel):
    """
    POST /api/v1/auth/login — success response.

    Three possible client states after a 200 response:

    1. Full access (non-admin or admin with TOTP already confirmed):
         totp_required=False, totp_setup_required=False
         → access_token is a full-scope JWT (15 min)
         → refresh cookie is set

    2. Admin TOTP verification required (secret exists, not yet verified):
         totp_required=True, totp_setup_required=False
         → access_token is a pre_totp JWT (5 min)
         → client redirects to /auth/totp/verify

    3. Admin TOTP setup required (no secret stored yet):
         totp_required=True, totp_setup_required=True
         → access_token is a pre_totp JWT (5 min)
         → client redirects to /auth/totp/setup then /auth/totp/confirm
    """
    access_token: str
    token_type: str = "bearer"
    totp_required: bool = False
    totp_setup_required: bool = False


# =============================================================================
# TOTP Verify (complete admin login)
# =============================================================================

class TOTPVerifyRequest(BaseModel):
    """POST /api/v1/auth/totp/verify — body."""
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(
        ...,
        min_length=6,
        max_length=8,  # "123 456" (7 chars with space) is cleaned in the route
        description="6-digit TOTP code from authenticator app",
    )


class TOTPVerifyResponse(BaseModel):
    """Returned after successful TOTP verification — full access granted."""
    access_token: str
    token_type: str = "bearer"


# =============================================================================
# Token Refresh
# =============================================================================

class RefreshResponse(BaseModel):
    """POST /api/v1/auth/refresh — new access token issued."""
    access_token: str
    token_type: str = "bearer"


# =============================================================================
# Current User
# =============================================================================

class MeResponse(BaseModel):
    """GET /api/v1/auth/me — current user info from DB (fresh, not from JWT)."""
    user_id: str
    email: str
    name: str
    role: str
    department: Optional[str]
    totp_enabled: bool
    is_active: bool
    is_approved: bool
    last_login_at: Optional[datetime]


# =============================================================================
# TOTP Setup (admin only — via pre_totp token)
# =============================================================================

class TOTPSetupResponse(BaseModel):
    """
    POST /api/v1/auth/totp/setup

    The QR code and secret are generated fresh each time and NEVER stored.
    The secret is also returned for manual entry (some authenticators don't
    support QR scanning).

    This data is transmitted ONCE and should not be logged or persisted
    beyond the HTTP response.
    """
    qr_code: str = Field(
        ...,
        description='Base64-encoded PNG as data URI: "data:image/png;base64,..."',
    )
    secret: str = Field(
        ...,
        description="Base32 TOTP secret for manual entry in authenticator app",
    )
    uri: str = Field(
        ...,
        description="otpauth:// URI for QR code scanning",
    )


# =============================================================================
# TOTP Confirm (activate TOTP after setup)
# =============================================================================

class TOTPConfirmRequest(BaseModel):
    """POST /api/v1/auth/totp/confirm — body."""
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(
        ...,
        min_length=6,
        max_length=8,
        description="6-digit TOTP code to verify setup succeeded",
    )


class TOTPConfirmResponse(BaseModel):
    """Returned after TOTP successfully activated on the account."""
    message: str = (
        "TOTP successfully enabled. "
        "Your next login will require your authenticator code."
    )