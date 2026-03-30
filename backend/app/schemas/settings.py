"""Smart BI Agent — Settings & Dashboard Schemas (Phase 8)"""
from __future__ import annotations

from typing import Optional
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
    id: str
    query_id: str
    query_name: str
    question: str
    connection_id: str
    chart_type: str = "auto"
    title: str
    size: str = "md"


class DashboardConfigSchema(BaseModel):
    title: str = Field(default="My Dashboard", max_length=255)
    description: str = Field(default="", max_length=500)
    widgets: list[DashboardWidgetSchema] = []
    columns: int = Field(default=2, ge=1, le=4)


class DashboardCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    config: DashboardConfigSchema


class DashboardUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    config: Optional[DashboardConfigSchema] = None
    is_default: Optional[bool] = None


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
