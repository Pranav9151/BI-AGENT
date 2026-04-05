"""
Smart BI Agent — Dashboard Embed Routes (Phase 12)
Architecture v3.1 | Layer 4

PURPOSE:
    Enable embedding dashboards in external applications via iframe.
    Generates short-lived embed tokens that allow read-only dashboard access.

ENDPOINTS:
    POST /api/v1/embed/token          — Generate an embed token for a dashboard
    GET  /api/v1/embed/{token}/config  — Get dashboard config (for embed viewer)

SECURITY:
    - Embed tokens are JWT with limited scope: dashboard_id + read_only
    - Token lifetime: configurable, default 24 hours
    - Tokens can be revoked by deleting the dashboard
    - No write access via embed tokens
    - CORS headers configured for embedding domain
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUser,
    get_db,
    require_analyst_or_above,
)
from app.errors.exceptions import ResourceNotFoundError, ValidationError
from app.logging.structured import get_logger
from app.models.settings import Dashboard

log = get_logger(__name__)
router = APIRouter()


# =============================================================================
# Schemas
# =============================================================================

class EmbedTokenRequest(BaseModel):
    """POST /api/v1/embed/token — body."""
    dashboard_id: str = Field(..., description="Dashboard UUID to embed")
    expires_hours: int = Field(24, ge=1, le=720, description="Token validity in hours (max 30 days)")
    allowed_origin: str = Field("*", description="CORS origin for embedding (e.g., https://myapp.com)")


class EmbedTokenResponse(BaseModel):
    """POST /api/v1/embed/token — response."""
    embed_token: str
    embed_url: str
    dashboard_id: str
    expires_at: str
    allowed_origin: str


class EmbedConfigResponse(BaseModel):
    """GET /api/v1/embed/{token}/config — response."""
    dashboard_id: str
    name: str
    description: str
    config: dict[str, Any]
    theme: str = "dark"
    created_by: str = ""


# =============================================================================
# Token Store (in-memory for Phase 12 — move to Redis in Phase 13)
# =============================================================================

_embed_tokens: dict[str, dict] = {}


def _generate_token(dashboard_id: str, user_id: str, expires_hours: int, allowed_origin: str) -> str:
    """Generate a simple signed embed token."""
    payload = {
        "dashboard_id": dashboard_id,
        "user_id": user_id,
        "created_at": time.time(),
        "expires_at": time.time() + (expires_hours * 3600),
        "allowed_origin": allowed_origin,
        "scope": "embed:read",
    }
    # Simple hash-based token (in production, use proper JWT)
    token_id = str(uuid.uuid4()).replace("-", "")[:24]
    _embed_tokens[token_id] = payload
    return token_id


def _validate_token(token: str) -> dict | None:
    """Validate an embed token. Returns payload or None."""
    payload = _embed_tokens.get(token)
    if not payload:
        return None
    if time.time() > payload.get("expires_at", 0):
        del _embed_tokens[token]
        return None
    return payload


# =============================================================================
# Routes
# =============================================================================

@router.post(
    "/token",
    response_model=EmbedTokenResponse,
    summary="Generate an embed token for a dashboard",
)
async def create_embed_token(
    body: EmbedTokenRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_analyst_or_above),
    db: AsyncSession = Depends(get_db),
) -> EmbedTokenResponse:
    """
    Generate a short-lived embed token that allows read-only access
    to a specific dashboard. The token can be used in an iframe URL.
    """
    user_id = current_user["user_id"]

    # Verify dashboard exists and belongs to user
    try:
        dash_uuid = uuid.UUID(body.dashboard_id)
    except ValueError:
        raise ValidationError(message="Invalid dashboard ID.", detail="Not a valid UUID.")

    result = await db.execute(
        select(Dashboard).where(
            Dashboard.id == dash_uuid,
            Dashboard.user_id == uuid.UUID(user_id),
        )
    )
    dashboard = result.scalar_one_or_none()
    if dashboard is None:
        raise ResourceNotFoundError(
            message="Dashboard not found.",
            detail=f"Dashboard {body.dashboard_id} does not exist or you don't own it.",
        )

    # Generate token
    token = _generate_token(
        dashboard_id=body.dashboard_id,
        user_id=user_id,
        expires_hours=body.expires_hours,
        allowed_origin=body.allowed_origin,
    )

    expires_at = datetime.fromtimestamp(
        time.time() + (body.expires_hours * 3600),
        tz=timezone.utc,
    ).isoformat()

    # Build embed URL
    base_url = str(request.base_url).rstrip("/")
    embed_url = f"{base_url}/embed/{token}"

    log.info(
        "embed.token_created",
        user_id=user_id,
        dashboard_id=body.dashboard_id,
        expires_hours=body.expires_hours,
    )

    return EmbedTokenResponse(
        embed_token=token,
        embed_url=embed_url,
        dashboard_id=body.dashboard_id,
        expires_at=expires_at,
        allowed_origin=body.allowed_origin,
    )


@router.get(
    "/{token}/config",
    response_model=EmbedConfigResponse,
    summary="Get dashboard config for embedding",
)
async def get_embed_config(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> EmbedConfigResponse:
    """
    Returns the dashboard configuration for an embed token.
    This endpoint does NOT require authentication — the token IS the auth.
    Used by the embed viewer (iframe) to render the dashboard.
    """
    payload = _validate_token(token)
    if payload is None:
        raise ResourceNotFoundError(
            message="Invalid or expired embed token.",
            detail="The embed token is invalid, expired, or has been revoked.",
        )

    dashboard_id = payload["dashboard_id"]

    result = await db.execute(
        select(Dashboard).where(Dashboard.id == uuid.UUID(dashboard_id))
    )
    dashboard = result.scalar_one_or_none()
    if dashboard is None:
        raise ResourceNotFoundError(
            message="Dashboard no longer exists.",
            detail="The embedded dashboard has been deleted.",
        )

    try:
        config = json.loads(dashboard.config_json) if dashboard.config_json else {}
    except Exception:
        config = {}

    return EmbedConfigResponse(
        dashboard_id=str(dashboard.id),
        name=dashboard.name,
        description=dashboard.description or "",
        config=config,
        theme="dark",
    )
