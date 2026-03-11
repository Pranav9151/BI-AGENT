"""
Smart BI Agent — Schema Schemas
Architecture v3.1 | Layer 4 | Component 11
"""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict


class ColumnInfo(BaseModel):
    type: str
    nullable: Optional[bool] = None
    primary_key: Optional[bool] = None


class TableInfo(BaseModel):
    columns: dict[str, ColumnInfo]
    row_count_estimate: Optional[int] = None


class SchemaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    connection_id: str
    schema_data: dict[str, TableInfo]   # table_name → TableInfo
    cached: bool = False
    cache_age_seconds: Optional[int] = None


class SchemaRefreshResponse(BaseModel):
    connection_id: str
    message: str = "Schema cache invalidated. Next fetch will re-introspect."
    keys_deleted: int = 0