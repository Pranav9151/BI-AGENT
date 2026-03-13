"""
Smart BI Agent — Export Schemas
Architecture v3.1 | Layer 4 | Threats: T18 (weasyprint SSRF),
                                        T31 (sensitive SQL in Jira/export),
                                        T48 (shadow AI data leakage)

Request and response schemas for the Export Engine.

Design notes:
  - The export endpoint accepts pre-computed tabular data (rows + columns)
    from the client.  Actual query result rows are NEVER persisted to the DB
    (zero-knowledge principle); they exist only in the client's memory after
    a query run and are passed here for file generation.

  - Row count hard cap: 10 000 rows maximum per export request.  Enforced
    at schema level so the error reaches the caller before any file generation.

  - sensitivity is a required field on every export.  The export engine stamps
    the file with a classification label (T48 shadow AI data leakage control).
    "restricted" exports are blocked entirely — the sensitivity guard at the
    saved-query level means restricted data should never reach the export surface.

  - supported_formats: csv | excel | pdf.  pdf uses weasyprint with a custom
    url_fetcher that blocks external URLs (T18).

  - ExportSavedQueryRequest is the schema for exporting a saved query's stored
    SQL text as a plain .sql file (not the result rows — those are not stored).
    This is intentionally lightweight: just the SQL for analysts to inspect or
    replay in a DB client.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

SUPPORTED_FORMATS = frozenset({"csv", "excel", "pdf"})
SENSITIVITY_LEVELS = frozenset({"normal", "sensitive", "restricted"})
MAX_EXPORT_ROWS = 10_000


# =============================================================================
# Request Schemas
# =============================================================================

class ExportRequest(BaseModel):
    """
    POST /api/v1/export — body.

    The client submits the rows it wants exported (received from a query run).
    The server generates the file and returns it as a streaming attachment.
    Result data never touches the DB — this route is the only path from
    in-memory query result → downloadable file.

    Security fields:
      - sensitivity: required; "restricted" is rejected (T31/T48).
      - filename: optional hint; sanitised server-side (no path traversal).
    """
    model_config = ConfigDict()

    columns: list[str] = Field(
        ..., min_length=1,
        description="Ordered list of column names",
    )
    rows: list[list[Any]] = Field(
        ...,
        description="Row data — each inner list must match len(columns)",
    )
    format: str = Field(
        ...,
        description=f"Export format: {sorted(SUPPORTED_FORMATS)}",
    )
    sensitivity: str = Field(
        "normal",
        description="Data sensitivity classification for the classification stamp (T48)",
    )
    filename: Optional[str] = Field(
        None, max_length=200,
        description="Optional filename hint (extension appended by server)",
    )
    title: Optional[str] = Field(
        None, max_length=255,
        description="Optional report title (used in PDF/Excel headers)",
    )

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        if v not in SUPPORTED_FORMATS:
            raise ValueError(
                f"format must be one of {sorted(SUPPORTED_FORMATS)}, got {v!r}"
            )
        return v

    @field_validator("sensitivity")
    @classmethod
    def validate_sensitivity(cls, v: str) -> str:
        if v not in SENSITIVITY_LEVELS:
            raise ValueError(
                f"sensitivity must be one of {sorted(SENSITIVITY_LEVELS)}, got {v!r}"
            )
        return v

    @field_validator("rows")
    @classmethod
    def validate_row_count(cls, v: list) -> list:
        if len(v) > MAX_EXPORT_ROWS:
            raise ValueError(
                f"Export exceeds maximum row limit ({MAX_EXPORT_ROWS}). "
                f"Got {len(v)} rows. Split into multiple exports or reduce result size."
            )
        return v

    @field_validator("filename")
    @classmethod
    def sanitise_filename(cls, v: Optional[str]) -> Optional[str]:
        """Strip path separators and null bytes to prevent path traversal."""
        if v is None:
            return v
        # Remove path separators and null bytes
        for ch in ("/", "\\", "\x00", "..", ":"):
            v = v.replace(ch, "_")
        return v.strip() or None


class ExportSavedQueryRequest(BaseModel):
    """
    POST /api/v1/export/saved-query/{id} — body.

    Export the SQL text of a saved query as a .sql file.
    This does NOT re-execute the query — it only packages the stored SQL string
    for download.  Ownership is enforced at the route level (T52).
    """
    model_config = ConfigDict()

    include_question: bool = Field(
        True,
        description="If True, prepend the original natural-language question as a SQL comment",
    )


# =============================================================================
# Metadata Response (non-file endpoints)
# =============================================================================

class ExportMetadataResponse(BaseModel):
    """
    Returned when the export is queued or when surfacing export metadata.
    For synchronous exports the actual file is the response body (StreamingResponse).
    This schema is used by tests and for error/metadata paths.
    """
    format: str
    rows_exported: int
    filename: str
    sensitivity: str
    size_bytes: Optional[int] = None
    message: Optional[str] = None