"""
Smart BI Agent — Settings Routes (Phase 8)
Architecture v3.1 | Layer 4

Endpoints:
    GET  /api/v1/settings/branding — Get platform branding (public to authenticated users)
    PUT  /api/v1/settings/branding — Update branding (admin only)
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUser, get_current_user, get_db, require_admin
from app.logging.structured import get_logger
from app.models.settings import PlatformSetting
from app.schemas.settings import BrandingData, BrandingResponse

log = get_logger(__name__)
router = APIRouter()

_BRANDING_KEY = "branding"
_DEFAULT_BRANDING = BrandingData()


@router.get(
    "/branding",
    response_model=BrandingResponse,
    summary="Get platform branding",
)
async def get_branding(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrandingResponse:
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == _BRANDING_KEY)
    )
    setting = result.scalar_one_or_none()

    if setting:
        try:
            data = BrandingData(**json.loads(setting.value))
            return BrandingResponse(branding=data)
        except Exception:
            pass

    return BrandingResponse(branding=_DEFAULT_BRANDING)


@router.put(
    "/branding",
    response_model=BrandingResponse,
    summary="Update platform branding (admin)",
)
async def update_branding(
    body: BrandingData,
    current_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BrandingResponse:
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == _BRANDING_KEY)
    )
    setting = result.scalar_one_or_none()

    value_json = body.model_dump_json()

    if setting:
        setting.value = value_json
        setting.updated_by = current_user["user_id"]
    else:
        import uuid
        setting = PlatformSetting(
            id=uuid.uuid4(),
            key=_BRANDING_KEY,
            value=value_json,
            updated_by=current_user["user_id"],
        )
        db.add(setting)

    await db.commit()
    log.info("settings.branding.updated", user_id=current_user["user_id"])
    return BrandingResponse(branding=body)
