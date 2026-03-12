"""
Smart BI Agent — Saved Query Schemas
Architecture v3.1 | Layer 4 | Threats: T43 (stale permissions), T52 (IDOR)

Request and response schemas for the Saved Query / Query Library system.

Security notes:
  - sql_query is stored verbatim — it is never re-executed without a fresh
    permission check (T43). Re-run logic lives in the query pipeline, not here.
  - sensitivity enum limits classification to three known values; prevents
    free-text injection into the sensitivity field.
  - is_shared=True makes the query readable by ALL authenticated users.
    Admins can set is_shared on any query; owners can share their own.
  - Ownership (IDOR, T52) is enforced at the route layer — these schemas
    carry no ownership logic.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Enums
# =============================================================================

class SensitivityLevel(str, Enum):
    """Data sensitivity classification for saved queries."""
    normal     = "normal"
    sensitive  = "sensitive"
    restricted = "restricted"


# =============================================================================
# Request Schemas
# =============================================================================

class SavedQueryCreateRequest(BaseModel):
    """
    POST /api/v1/saved-queries — body.

    Callers supply the natural-language question alongside the generated SQL.
    The SQL is stored for direct re-run; re-runs must re-validate permissions (T43).
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    connection_id: str = Field(..., description="UUID of the target database connection")
    name: str = Field(..., min_length=1, max_length=255, description="Human-readable query name")
    description: Optional[str] = Field(None, max_length=2000, description="Optional longer description")
    question: str = Field(
        ..., min_length=1, max_length=2000,
        description="Original natural-language question that produced this SQL",
    )
    sql_query: str = Field(
        ..., min_length=1, max_length=65535,
        description="Generated SQL to store. Re-run requires fresh permission check (T43).",
    )
    tags: list[str] = Field(default=[], description="Free-form tags for search/filtering")
    sensitivity: SensitivityLevel = Field(
        SensitivityLevel.normal,
        description="Data sensitivity classification (normal | sensitive | restricted)",
    )
    is_shared: bool = Field(False, description="If True, all authenticated users can view this query")
    is_pinned: bool = Field(False, description="Pin to dashboard for quick access")


class SavedQueryUpdateRequest(BaseModel):
    """
    PATCH /api/v1/saved-queries/{id} — body.

    All fields optional. sql_query and question may be updated together
    when the user refines a query. connection_id is immutable after creation
    (changing the target DB would silently invalidate the stored SQL).
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    question: Optional[str] = Field(None, min_length=1, max_length=2000)
    sql_query: Optional[str] = Field(None, min_length=1, max_length=65535)
    tags: Optional[list[str]] = None
    sensitivity: Optional[SensitivityLevel] = None
    is_shared: Optional[bool] = None
    is_pinned: Optional[bool] = None


# =============================================================================
# Response Schemas
# =============================================================================

class SavedQueryResponse(BaseModel):
    """
    Safe saved query representation.

    sql_query IS returned — owners need it to inspect and re-use.
    run_count / last_run_at are read-only stats, updated by the query pipeline.
    """
    model_config = ConfigDict(from_attributes=True)

    query_id: str
    user_id: str
    connection_id: str
    name: str
    description: Optional[str]
    question: str
    sql_query: str
    tags: list[str]
    sensitivity: str
    is_shared: bool
    is_pinned: bool
    run_count: int
    last_run_at: Optional[str]  # ISO-8601 string; None if never run


class SavedQueryListResponse(BaseModel):
    """Paginated list of saved queries."""
    queries: list[SavedQueryResponse]
    total: int
    skip: int
    limit: int


class SavedQueryDuplicateResponse(BaseModel):
    """POST /api/v1/saved-queries/{id}/duplicate — response."""
    query_id: str
    name: str
    message: str