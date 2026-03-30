"""Smart BI Agent — Settings & Dashboard Schemas (Phase 9.5)
Upgraded: Flexible widget config for Canvas Studio v4
"""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


# ─── Branding ────────────────────────────────────────────────────────────────

class BrandingData(BaseModel):
    company_name: str = Field(default="Smart BI Agent", max_length=100)
    logo_url: str = Field(default="", max_length=500)
    tagline: str = Field(default="AI-Powered Business Intelligence", max_length=200)


class BrandingResponse(BaseModel):
    branding: BrandingData


# ─── Dashboards ──────────────────────────────────────────────────────────────

class DashboardWidgetSchema(BaseModel):
    """Flexible widget schema — supports both legacy and Canvas Studio v4 formats."""
    id: str
    # Legacy fields (optional for backward compat)
    query_id: Optional[str] = None
    query_name: Optional[str] = None
    question: Optional[str] = None
    connection_id: Optional[str] = None
    chart_type: str = "auto"
    title: str = "Untitled"
    size: str = "md"
    # Canvas Studio v4 fields
    mode: Optional[str] = None  # "fields" | "nlq"
    x_axis: Optional[dict[str, Any]] = None
    values_fields: Optional[list[dict[str, Any]]] = None
    legend: Optional[dict[str, Any]] = None
    nl_question: Optional[str] = None
    generated_sql: Optional[str] = None

    model_config = {"extra": "allow"}  # Accept any extra fields


class DashboardConfigSchema(BaseModel):
    """Flexible config — accepts any JSON structure for maximum forward-compat."""
    title: str = Field(default="My Dashboard", max_length=255)
    description: str = Field(default="", max_length=500)
    widgets: list[DashboardWidgetSchema] = []
    columns: int = Field(default=12, ge=1, le=12)
    # Canvas Studio v4 fields
    connection_id: Optional[str] = None
    department: Optional[str] = None

    model_config = {"extra": "allow"}


class DashboardCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    config: DashboardConfigSchema
    department: Optional[str] = None


class DashboardUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    config: Optional[DashboardConfigSchema] = None
    is_default: Optional[bool] = None
    department: Optional[str] = None


class DashboardResponse(BaseModel):
    dashboard_id: str
    name: str
    description: Optional[str]
    config: DashboardConfigSchema
    is_default: bool
    created_at: str
    updated_at: str


class DashboardListResponse(BaseModel):
    dashboards: list[DashboardResponse]
    total: int
