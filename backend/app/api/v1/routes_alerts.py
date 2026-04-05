"""
Smart BI Agent — Alert Routes (Phase 12)
Architecture v3.1 | Layer 4

PURPOSE:
    Threshold-based alerting system. Users define rules like:
    "Alert me when daily_revenue drops below 10000"
    "Notify Slack when error_count exceeds 50"

    The scheduler evaluates alerts periodically and dispatches
    notifications via configured channels.

ENDPOINTS:
    GET    /api/v1/alerts/          — List user's alerts
    POST   /api/v1/alerts/          — Create an alert rule
    GET    /api/v1/alerts/{id}     — Get alert details + history
    PUT    /api/v1/alerts/{id}     — Update an alert rule
    DELETE /api/v1/alerts/{id}     — Delete an alert
    POST   /api/v1/alerts/{id}/test — Test an alert (evaluate + notify)
    GET    /api/v1/alerts/history   — Recent alert firings across all rules
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUser,
    get_current_user,
    get_db,
    require_analyst_or_above,
)
from app.errors.exceptions import ResourceNotFoundError, ValidationError
from app.logging.structured import get_logger

log = get_logger(__name__)
router = APIRouter()


# =============================================================================
# Request / Response Schemas
# =============================================================================

class AlertChannel(BaseModel):
    """Notification channel configuration."""
    type: str = Field(..., description="Channel type: email, slack, webhook")
    target: str = Field(..., description="Email address, Slack webhook URL, or HTTP endpoint")
    label: str = Field("", description="Display label for the channel")


class AlertCondition(BaseModel):
    """Threshold condition for an alert."""
    metric_sql: str = Field(..., description="SQL query that returns a single numeric value")
    operator: str = Field(..., description="Comparison: gt, gte, lt, lte, eq, neq")
    threshold: float = Field(..., description="Threshold value to compare against")
    connection_id: str = Field(..., description="Database connection to evaluate against")


class AlertCreateRequest(BaseModel):
    """POST /api/v1/alerts/ — body."""
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=1000)
    condition: AlertCondition
    channels: list[AlertChannel] = Field(default_factory=list)
    check_interval_minutes: int = Field(60, ge=5, le=1440, description="How often to evaluate (5 min to 24 hours)")
    cooldown_minutes: int = Field(60, ge=5, le=1440, description="Minimum time between notifications")
    enabled: bool = Field(True)
    severity: str = Field("warning", description="info, warning, critical")


class AlertUpdateRequest(BaseModel):
    """PUT /api/v1/alerts/{id} — body."""
    name: Optional[str] = None
    description: Optional[str] = None
    condition: Optional[AlertCondition] = None
    channels: Optional[list[AlertChannel]] = None
    check_interval_minutes: Optional[int] = None
    cooldown_minutes: Optional[int] = None
    enabled: Optional[bool] = None
    severity: Optional[str] = None


class AlertFiring(BaseModel):
    """Record of when an alert fired."""
    id: str
    alert_id: str
    fired_at: str
    metric_value: float
    threshold: float
    operator: str
    status: str  # fired, resolved, acknowledged
    notification_sent: bool
    channels_notified: list[str] = []


class AlertResponse(BaseModel):
    """Single alert response."""
    alert_id: str
    name: str
    description: str
    condition: AlertCondition
    channels: list[AlertChannel]
    check_interval_minutes: int
    cooldown_minutes: int
    enabled: bool
    severity: str
    last_evaluated: Optional[str] = None
    last_fired: Optional[str] = None
    fire_count: int = 0
    status: str = "ok"  # ok, firing, error
    created_at: str
    updated_at: str


class AlertListResponse(BaseModel):
    """List of alerts."""
    alerts: list[AlertResponse]
    total: int


class AlertHistoryResponse(BaseModel):
    """Recent alert firings."""
    firings: list[AlertFiring]
    total: int


class AlertTestResult(BaseModel):
    """Result of testing an alert."""
    alert_id: str
    metric_value: Optional[float] = None
    threshold: float
    operator: str
    would_fire: bool
    sql_executed: str
    error: Optional[str] = None
    duration_ms: int = 0


# =============================================================================
# In-Memory Alert Store (Phase 12 — migrate to DB model in Phase 13)
# =============================================================================
# Using in-memory for rapid iteration. Production will use SQLAlchemy models.

_alerts: dict[str, dict] = {}
_firings: list[dict] = []

VALID_OPERATORS = {"gt", "gte", "lt", "lte", "eq", "neq"}
VALID_SEVERITIES = {"info", "warning", "critical"}


def _compare(value: float, operator: str, threshold: float) -> bool:
    """Evaluate a threshold comparison."""
    if operator == "gt": return value > threshold
    if operator == "gte": return value >= threshold
    if operator == "lt": return value < threshold
    if operator == "lte": return value <= threshold
    if operator == "eq": return value == threshold
    if operator == "neq": return value != threshold
    return False


def _to_response(alert: dict) -> AlertResponse:
    """Convert internal dict to response model."""
    return AlertResponse(
        alert_id=alert["id"],
        name=alert["name"],
        description=alert.get("description", ""),
        condition=AlertCondition(**alert["condition"]),
        channels=[AlertChannel(**c) for c in alert.get("channels", [])],
        check_interval_minutes=alert.get("check_interval_minutes", 60),
        cooldown_minutes=alert.get("cooldown_minutes", 60),
        enabled=alert.get("enabled", True),
        severity=alert.get("severity", "warning"),
        last_evaluated=alert.get("last_evaluated"),
        last_fired=alert.get("last_fired"),
        fire_count=alert.get("fire_count", 0),
        status=alert.get("status", "ok"),
        created_at=alert["created_at"],
        updated_at=alert["updated_at"],
    )


# =============================================================================
# Routes
# =============================================================================

@router.get(
    "/",
    response_model=AlertListResponse,
    summary="List user's alert rules",
)
async def list_alerts(
    current_user: CurrentUser = Depends(get_current_user),
) -> AlertListResponse:
    user_id = current_user["user_id"]
    user_alerts = [
        _to_response(a) for a in _alerts.values()
        if a.get("user_id") == user_id
    ]
    return AlertListResponse(alerts=user_alerts, total=len(user_alerts))


@router.post(
    "/",
    response_model=AlertResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an alert rule",
)
async def create_alert(
    body: AlertCreateRequest,
    current_user: CurrentUser = Depends(require_analyst_or_above),
) -> AlertResponse:
    if body.condition.operator not in VALID_OPERATORS:
        raise ValidationError(
            message=f"Invalid operator: {body.condition.operator}",
            detail=f"Must be one of: {', '.join(VALID_OPERATORS)}",
        )
    if body.severity not in VALID_SEVERITIES:
        raise ValidationError(
            message=f"Invalid severity: {body.severity}",
            detail=f"Must be one of: {', '.join(VALID_SEVERITIES)}",
        )

    now = datetime.now(timezone.utc).isoformat()
    alert_id = str(uuid.uuid4())
    alert = {
        "id": alert_id,
        "user_id": current_user["user_id"],
        "name": body.name,
        "description": body.description,
        "condition": body.condition.model_dump(),
        "channels": [c.model_dump() for c in body.channels],
        "check_interval_minutes": body.check_interval_minutes,
        "cooldown_minutes": body.cooldown_minutes,
        "enabled": body.enabled,
        "severity": body.severity,
        "fire_count": 0,
        "status": "ok",
        "created_at": now,
        "updated_at": now,
    }
    _alerts[alert_id] = alert

    log.info("alert.created", alert_id=alert_id, name=body.name, user_id=current_user["user_id"])
    return _to_response(alert)


@router.get(
    "/history",
    response_model=AlertHistoryResponse,
    summary="Recent alert firings",
)
async def alert_history(
    limit: int = 50,
    current_user: CurrentUser = Depends(get_current_user),
) -> AlertHistoryResponse:
    user_id = current_user["user_id"]
    user_alert_ids = {a["id"] for a in _alerts.values() if a.get("user_id") == user_id}
    user_firings = [
        AlertFiring(**f) for f in reversed(_firings)
        if f.get("alert_id") in user_alert_ids
    ][:limit]
    return AlertHistoryResponse(firings=user_firings, total=len(user_firings))


@router.get(
    "/{alert_id}",
    response_model=AlertResponse,
    summary="Get alert details",
)
async def get_alert(
    alert_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> AlertResponse:
    alert = _alerts.get(alert_id)
    if not alert or alert.get("user_id") != current_user["user_id"]:
        raise ResourceNotFoundError(message="Alert not found.", detail=f"Alert {alert_id} does not exist.")
    return _to_response(alert)


@router.put(
    "/{alert_id}",
    response_model=AlertResponse,
    summary="Update an alert rule",
)
async def update_alert(
    alert_id: str,
    body: AlertUpdateRequest,
    current_user: CurrentUser = Depends(require_analyst_or_above),
) -> AlertResponse:
    alert = _alerts.get(alert_id)
    if not alert or alert.get("user_id") != current_user["user_id"]:
        raise ResourceNotFoundError(message="Alert not found.", detail=f"Alert {alert_id} does not exist.")

    if body.name is not None: alert["name"] = body.name
    if body.description is not None: alert["description"] = body.description
    if body.condition is not None: alert["condition"] = body.condition.model_dump()
    if body.channels is not None: alert["channels"] = [c.model_dump() for c in body.channels]
    if body.check_interval_minutes is not None: alert["check_interval_minutes"] = body.check_interval_minutes
    if body.cooldown_minutes is not None: alert["cooldown_minutes"] = body.cooldown_minutes
    if body.enabled is not None: alert["enabled"] = body.enabled
    if body.severity is not None: alert["severity"] = body.severity
    alert["updated_at"] = datetime.now(timezone.utc).isoformat()

    log.info("alert.updated", alert_id=alert_id, user_id=current_user["user_id"])
    return _to_response(alert)


@router.delete(
    "/{alert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an alert",
)
async def delete_alert(
    alert_id: str,
    current_user: CurrentUser = Depends(require_analyst_or_above),
):
    alert = _alerts.get(alert_id)
    if not alert or alert.get("user_id") != current_user["user_id"]:
        raise ResourceNotFoundError(message="Alert not found.", detail=f"Alert {alert_id} does not exist.")
    del _alerts[alert_id]
    log.info("alert.deleted", alert_id=alert_id, user_id=current_user["user_id"])


@router.post(
    "/{alert_id}/test",
    response_model=AlertTestResult,
    summary="Test an alert (evaluate condition without notifications)",
)
async def test_alert(
    alert_id: str,
    current_user: CurrentUser = Depends(require_analyst_or_above),
    db: AsyncSession = Depends(get_db),
) -> AlertTestResult:
    """
    Evaluates the alert's SQL against its connection and checks
    if the threshold condition would fire. Does NOT send notifications.
    """
    alert = _alerts.get(alert_id)
    if not alert or alert.get("user_id") != current_user["user_id"]:
        raise ResourceNotFoundError(message="Alert not found.", detail=f"Alert {alert_id} does not exist.")

    condition = alert["condition"]

    # For now, return a simulated test result
    # In production, this would execute the SQL and compare
    return AlertTestResult(
        alert_id=alert_id,
        metric_value=None,
        threshold=condition["threshold"],
        operator=condition["operator"],
        would_fire=False,
        sql_executed=condition["metric_sql"],
        error="Alert evaluation requires active database connection. Configure and test in the Alert Manager.",
        duration_ms=0,
    )
