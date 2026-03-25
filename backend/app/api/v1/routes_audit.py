"""
Smart BI Agent — Audit Log Routes
Phase 6 | Session 8 | Admin only

ENDPOINTS:
    GET /api/v1/audit/   — List audit logs with search/filter/pagination
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUser, get_db, require_admin
from app.logging.structured import get_logger
from app.models.audit_log import AuditLog

from pydantic import BaseModel

log = get_logger(__name__)

router = APIRouter()


class AuditEntryResponse(BaseModel):
    id: str
    user_id: Optional[str]
    execution_status: str
    question: str
    row_count: Optional[int]
    duration_ms: Optional[int]
    ip_address: Optional[str]
    created_at: str


class AuditLogListResponse(BaseModel):
    logs: list[AuditEntryResponse]
    total: int
    skip: int
    limit: int


@router.get(
    "/",
    response_model=AuditLogListResponse,
    summary="List audit logs (admin only)",
)
async def list_audit_logs(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None, alias="status"),
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AuditLogListResponse:
    """List audit logs with optional search and status filter."""

    conditions = []
    if status:
        conditions.append(AuditLog.execution_status == status)
    if search:
        conditions.append(
            or_(
                AuditLog.question.ilike(f"%{search}%"),
                AuditLog.execution_status.ilike(f"%{search}%"),
            )
        )

    count_stmt = select(func.count()).select_from(AuditLog)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    data_stmt = (
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if conditions:
        data_stmt = data_stmt.where(*conditions)

    results = (await db.execute(data_stmt)).scalars().all()

    logs = [
        AuditEntryResponse(
            id=str(entry.id),
            user_id=str(entry.user_id) if entry.user_id else None,
            execution_status=entry.execution_status,
            question=entry.question[:500],
            row_count=entry.row_count,
            duration_ms=entry.duration_ms,
            ip_address=entry.ip_address,
            created_at=entry.created_at.isoformat() if entry.created_at else "",
        )
        for entry in results
    ]

    return AuditLogListResponse(
        logs=logs,
        total=total,
        skip=skip,
        limit=limit,
    )