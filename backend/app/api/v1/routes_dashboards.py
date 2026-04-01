"""
Smart BI Agent — Dashboard Routes (Phase 8)
Architecture v3.1 | Layer 4

Endpoints:
    GET    /api/v1/dashboards/         — List user's dashboards
    POST   /api/v1/dashboards/         — Create a dashboard
    GET    /api/v1/dashboards/{id}     — Get single dashboard
    PUT    /api/v1/dashboards/{id}     — Update a dashboard
    DELETE /api/v1/dashboards/{id}     — Delete a dashboard
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUser, get_current_user, get_db
from app.errors.exceptions import ResourceNotFoundError, ValidationError
from app.logging.structured import get_logger
from app.models.settings import Dashboard
from app.schemas.settings import (
    DashboardConfigSchema,
    DashboardCreateRequest,
    DashboardListResponse,
    DashboardResponse,
    DashboardUpdateRequest,
)

log = get_logger(__name__)
router = APIRouter()


def _to_response(d: Dashboard) -> DashboardResponse:
    try:
        config = DashboardConfigSchema(**json.loads(d.config_json))
    except Exception:
        config = DashboardConfigSchema()
    return DashboardResponse(
        dashboard_id=str(d.id),
        name=d.name,
        description=d.description,
        config=config,
        is_default=d.is_default,
        created_at=d.created_at.isoformat(),
        updated_at=d.updated_at.isoformat(),
    )


@router.get(
    "/",
    response_model=DashboardListResponse,
    summary="List user's dashboards",
)
async def list_dashboards(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardListResponse:
    user_id = uuid.UUID(current_user["user_id"])
    result = await db.execute(
        select(Dashboard)
        .where(Dashboard.user_id == user_id)
        .order_by(Dashboard.updated_at.desc())
    )
    dashboards = result.scalars().all()
    return DashboardListResponse(
        dashboards=[_to_response(d) for d in dashboards],
        total=len(dashboards),
    )


@router.post(
    "/",
    response_model=DashboardResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a dashboard",
)
async def create_dashboard(
    body: DashboardCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    user_id = uuid.UUID(current_user["user_id"])

    dashboard = Dashboard(
        id=uuid.uuid4(),
        user_id=user_id,
        name=body.name,
        description=body.description,
        config_json=body.config.model_dump_json(),
        is_default=False,
    )
    db.add(dashboard)
    await db.commit()
    await db.refresh(dashboard)

    log.info("dashboard.created", dashboard_id=str(dashboard.id), user_id=current_user["user_id"])
    return _to_response(dashboard)


@router.get(
    "/{dashboard_id}",
    response_model=DashboardResponse,
    summary="Get a single dashboard",
)
async def get_dashboard(
    dashboard_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    try:
        did = uuid.UUID(dashboard_id)
    except ValueError:
        raise ValidationError(message="Invalid dashboard ID format.")

    result = await db.execute(
        select(Dashboard).where(
            Dashboard.id == did,
            Dashboard.user_id == uuid.UUID(current_user["user_id"]),
        )
    )
    dashboard = result.scalar_one_or_none()
    if not dashboard:
        raise ResourceNotFoundError(message="Dashboard not found.")
    return _to_response(dashboard)


@router.put(
    "/{dashboard_id}",
    response_model=DashboardResponse,
    summary="Update a dashboard",
)
async def update_dashboard(
    dashboard_id: str,
    body: DashboardUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    try:
        did = uuid.UUID(dashboard_id)
    except ValueError:
        raise ValidationError(message="Invalid dashboard ID format.")

    result = await db.execute(
        select(Dashboard).where(
            Dashboard.id == did,
            Dashboard.user_id == uuid.UUID(current_user["user_id"]),
        )
    )
    dashboard = result.scalar_one_or_none()
    if not dashboard:
        raise ResourceNotFoundError(message="Dashboard not found.")

    if body.name is not None:
        dashboard.name = body.name
    if body.description is not None:
        dashboard.description = body.description
    if body.config is not None:
        dashboard.config_json = body.config.model_dump_json()
    if body.is_default is not None:
        # If setting as default, unset others
        if body.is_default:
            others = await db.execute(
                select(Dashboard).where(
                    Dashboard.user_id == uuid.UUID(current_user["user_id"]),
                    Dashboard.is_default == True,
                    Dashboard.id != did,
                )
            )
            for other in others.scalars().all():
                other.is_default = False
        dashboard.is_default = body.is_default

    await db.commit()
    await db.refresh(dashboard)
    log.info("dashboard.updated", dashboard_id=dashboard_id, user_id=current_user["user_id"])
    return _to_response(dashboard)


@router.delete(
    "/{dashboard_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a dashboard",
)
async def delete_dashboard(
    dashboard_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        did = uuid.UUID(dashboard_id)
    except ValueError:
        raise ValidationError(message="Invalid dashboard ID format.")

    result = await db.execute(
        select(Dashboard).where(
            Dashboard.id == did,
            Dashboard.user_id == uuid.UUID(current_user["user_id"]),
        )
    )
    dashboard = result.scalar_one_or_none()
    if not dashboard:
        raise ResourceNotFoundError(message="Dashboard not found.")

    await db.delete(dashboard)
    await db.commit()
    log.info("dashboard.deleted", dashboard_id=dashboard_id, user_id=current_user["user_id"])
