"""
Smart BI Agent — Schedule Schemas
Architecture v3.1 | Layer 4 | Threats: T9 (stale permissions at run time),
                                        T47 (timezone confusion), T52 (IDOR),
                                        T8 (APScheduler duplicate job)

Request and response schemas for the Scheduled Reports system.

Design notes:
  - cron_expression is validated by regex to the classic 5-field UNIX format.
    APScheduler performs the authoritative parse at job-load time; we reject
    obvious garbage early so the error message reaches the user at save time,
    not silently at the next scheduler reload.
  - delivery_targets is a list of {platform_id, destination} dicts.  Platform
    existence is NOT validated here — the scheduler re-checks at execution time
    so stale platform deletions fail gracefully (T9).
  - saved_query_id is nullable: a schedule can be "pending" while the user
    hasn't yet linked a query.  Active schedules with null saved_query_id are
    skipped by the scheduler with a warning.
  - output_format enum covers the three export surfaces (csv / excel / pdf).
  - next_run_at and last_run_* are computed / written by the APScheduler worker,
    never by the CRUD layer.  They are read-only in all request schemas.
  - T47: timezone must be a non-empty string.  Full IANA validation happens in
    the APScheduler job at load time; we enforce non-blank here only.
  - T8: is_active=False tells the scheduler to skip the job without deleting it.
    The distributed lock (schedule_lock:{id}, DB2, TTL 300s) is managed by the
    scheduler worker, not this layer.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Simple permissive 5-field cron regex; full IANA/APScheduler validation at job load
_CRON_FIELD = r'(\*(/\d+)?|\d+(-\d+)?(/\d+)?(,(\d+(-\d+)?(/\d+)?))*)'  # noqa
_CRON_RE = re.compile(r'^' + r'\s+'.join([_CRON_FIELD] * 5) + r'$')


def _validate_cron(value: str) -> str:
    """Raise ValueError if value is not a valid 5-field cron expression."""
    stripped = value.strip()
    if not stripped:
        raise ValueError("cron_expression must not be empty.")
    parts = stripped.split()
    if len(parts) != 5:
        raise ValueError(
            f"cron_expression must have exactly 5 fields "
            f"(minute hour dom month dow), got {len(parts)}: {stripped!r}"
        )
    if not _CRON_RE.match(stripped):
        raise ValueError(
            f"cron_expression {stripped!r} does not match standard 5-field cron format."
        )
    return stripped


# =============================================================================
# Enums
# =============================================================================

class OutputFormat(str):
    """Allowed output formats for scheduled report delivery."""
    csv   = "csv"
    excel = "excel"
    pdf   = "pdf"

_VALID_OUTPUT_FORMATS = {"csv", "excel", "pdf"}


# =============================================================================
# Sub-schemas
# =============================================================================

class DeliveryTarget(BaseModel):
    """
    Single delivery target within a schedule.

    platform_id must reference a NotificationPlatform row.
    destination is platform-specific (Slack channel, email address, webhook URL, etc.).
    Existence of platform_id is validated at scheduler execution time (T9).
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    platform_id: str = Field(..., description="UUID of the NotificationPlatform")
    destination: str = Field(
        ..., min_length=1, max_length=500,
        description="Platform-specific destination (channel, address, URL, etc.)",
    )


# =============================================================================
# Request Schemas
# =============================================================================

class ScheduleCreateRequest(BaseModel):
    """
    POST /api/v1/schedules — body.

    cron_expression is validated at schema level (5-field format only).
    Full IANA timezone validation deferred to APScheduler at job-load time (T47).
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255, description="Human-readable schedule name")
    saved_query_id: Optional[str] = Field(
        None,
        description="UUID of the SavedQuery to run. Nullable — schedule can be created before linking.",
    )
    cron_expression: str = Field(
        ..., min_length=9, max_length=100,
        description="Standard 5-field UNIX cron expression e.g. '0 8 * * 1' (Mon 08:00)",
    )
    timezone: str = Field(
        "UTC", min_length=1, max_length=100,
        description="IANA timezone string e.g. 'Asia/Riyadh', 'Europe/London' (T47)",
    )
    output_format: str = Field(
        "csv",
        description="Export format for the report: csv | excel | pdf",
    )
    delivery_targets: list[DeliveryTarget] = Field(
        default=[],
        description="Ordered list of notification platform targets",
    )
    is_active: bool = Field(True, description="Whether this schedule is enabled")

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        return _validate_cron(v)

    @field_validator("output_format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        if v not in _VALID_OUTPUT_FORMATS:
            raise ValueError(
                f"output_format must be one of {sorted(_VALID_OUTPUT_FORMATS)}, got {v!r}"
            )
        return v


class ScheduleUpdateRequest(BaseModel):
    """
    PATCH /api/v1/schedules/{id} — body.

    All fields optional. saved_query_id may be set to null explicitly to
    "unlink" a query (leaving the schedule in a pending/skip state).
    cron_expression, if supplied, is re-validated.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    saved_query_id: Optional[str] = None          # null = unlink
    cron_expression: Optional[str] = Field(None, min_length=9, max_length=100)
    timezone: Optional[str] = Field(None, min_length=1, max_length=100)
    output_format: Optional[str] = None
    delivery_targets: Optional[list[DeliveryTarget]] = None
    is_active: Optional[bool] = None

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_cron(v)
        return v

    @field_validator("output_format")
    @classmethod
    def validate_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_OUTPUT_FORMATS:
            raise ValueError(
                f"output_format must be one of {sorted(_VALID_OUTPUT_FORMATS)}, got {v!r}"
            )
        return v


# =============================================================================
# Response Schemas
# =============================================================================

class ScheduleResponse(BaseModel):
    """
    Safe schedule representation.

    last_run_* and next_run_at are populated by the APScheduler worker.
    They will be None for newly created schedules.
    """
    model_config = ConfigDict(from_attributes=True)

    schedule_id: str
    user_id: str
    saved_query_id: Optional[str]
    name: str
    cron_expression: str
    timezone: str
    output_format: str
    delivery_targets: list[Any]     # [{platform_id, destination}, ...]
    is_active: bool
    last_run_at: Optional[str]       # ISO-8601 or None
    last_run_status: Optional[str]   # "success" | "failed" | "skipped" | None
    next_run_at: Optional[str]       # ISO-8601 or None
    created_at: str
    updated_at: str


class ScheduleListResponse(BaseModel):
    """Paginated list of schedules."""
    schedules: list[ScheduleResponse]
    total: int
    skip: int
    limit: int


class ScheduleToggleResponse(BaseModel):
    """PATCH /{id}/toggle — minimal response."""
    schedule_id: str
    name: str
    is_active: bool
    message: str