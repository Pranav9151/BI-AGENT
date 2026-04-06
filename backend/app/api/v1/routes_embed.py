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

import base64
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import (
    CurrentUser,
    get_db,
    get_redis_coordination,
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
    allowed_origin: str = Field("", description="CORS origin for embedding (defaults to FRONTEND_URL)")


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


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + pad).encode("ascii"))


def _sign_payload(payload_json: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload_json.encode("utf-8"), "sha256").hexdigest()


def _generate_signed_token(
    dashboard_id: str,
    user_id: str,
    expires_hours: int,
    allowed_origin: str,
    secret: str,
) -> tuple[str, dict[str, Any]]:
    """Generate HMAC-signed embed token."""
    now = int(time.time())
    payload = {
        "jti": str(uuid.uuid4()).replace("-", "")[:24],
        "dashboard_id": dashboard_id,
        "user_id": user_id,
        "iat": now,
        "exp": now + (expires_hours * 3600),
        "allowed_origin": allowed_origin,
        "scope": "embed:read",
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_b64 = _b64url_encode(payload_json.encode("utf-8"))
    sig = _sign_payload(payload_json, secret)
    return f"{payload_b64}.{sig}", payload


def _validate_signed_token(token: str, secret: str) -> dict[str, Any] | None:
    """Validate HMAC signature + exp timestamp for embed token."""
    try:
        payload_b64, sig = token.split(".", 1)
        payload_json = _b64url_decode(payload_b64).decode("utf-8")
        expected = _sign_payload(payload_json, secret)
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(payload_json)
        if int(time.time()) > int(payload.get("exp", 0)):
            return None
        if payload.get("scope") != "embed:read":
            return None
        return payload
    except Exception:
        return None


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
    redis=Depends(get_redis_coordination),
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

    settings = get_settings()
    allowed_origin = body.allowed_origin.strip() if body.allowed_origin else ""
    if not allowed_origin or allowed_origin == "*":
        allowed_origin = settings.FRONTEND_URL

    # Generate signed token
    token, payload = _generate_signed_token(
        dashboard_id=body.dashboard_id,
        user_id=user_id,
        expires_hours=body.expires_hours,
        allowed_origin=allowed_origin,
        secret=settings.ENCRYPTION_MASTER_KEY,
    )
    ttl_seconds = max(int(payload["exp"] - time.time()), 1)
    await redis.set(f"embed:token:{payload['jti']}", "1", ex=ttl_seconds)

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
        allowed_origin=allowed_origin,
    )


@router.get(
    "/{token}/config",
    response_model=EmbedConfigResponse,
    summary="Get dashboard config for embedding",
)
async def get_embed_config(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis_coordination),
) -> EmbedConfigResponse:
    """
    Returns the dashboard configuration for an embed token.
    This endpoint does NOT require authentication — the token IS the auth.
    Used by the embed viewer (iframe) to render the dashboard.
    """
    settings = get_settings()
    payload = _validate_signed_token(token, settings.ENCRYPTION_MASTER_KEY)
    if payload is None:
        raise ResourceNotFoundError(
            message="Invalid or expired embed token.",
            detail="The embed token is invalid, expired, or has been revoked.",
        )
    # Basic per-IP rate limiting for embed token validation.
    xff = request.headers.get("x-forwarded-for")
    client_ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "unknown")
    minute_bucket = int(time.time() // 60)
    rl_key = f"embed:rl:{client_ip}:{minute_bucket}"
    count = await redis.incr(rl_key)
    if count == 1:
        await redis.expire(rl_key, 90)
    if count > 120:
        raise HTTPException(status_code=429, detail="Too many embed validation requests.")

    token_exists = await redis.get(f"embed:token:{payload.get('jti', '')}")
    if not token_exists:
        raise ResourceNotFoundError(
            message="Invalid or expired embed token.",
            detail="Embed token has been revoked or expired.",
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
