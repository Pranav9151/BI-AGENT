"""
Smart BI Agent — Connection Schemas
Architecture v3.1 | Layer 4 | Threats: T1 (SSRF), T2 (credential exposure)

Request and response schemas for database connection management.

Security notes:
  - username/password in request schemas ONLY — never in response schemas
  - encrypted_credentials (raw HKDF ciphertext) NEVER appears in any response
  - host/port appear in responses (not sensitive — visible to admins who set them)
  - db_type is an enum — prevents SQL injection via type confusion
  - SSRF validation is enforced at the route layer, not the schema layer
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Enums
# =============================================================================

class DBType(str, Enum):
    """Supported database types."""
    postgresql = "postgresql"
    mysql      = "mysql"
    mssql      = "mssql"
    bigquery   = "bigquery"
    snowflake  = "snowflake"


class SSLMode(str, Enum):
    """SSL/TLS connection mode."""
    disable  = "disable"
    allow    = "allow"
    prefer   = "prefer"
    require  = "require"
    verify_ca   = "verify-ca"
    verify_full = "verify-full"


# =============================================================================
# Request Schemas
# =============================================================================

class ConnectionCreateRequest(BaseModel):
    """
    POST /api/v1/connections — body.

    username + password are accepted here and immediately encrypted with
    HKDF KeyPurpose.DB_CREDENTIALS before storage. They are never returned
    in any response schema.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255, description="Human-readable connection name")
    db_type: DBType = Field(..., description="Database engine type")
    host: str = Field(..., min_length=1, max_length=500, description="Hostname or IP of the database server")
    port: int = Field(..., ge=1, le=65535, description="TCP port of the database server")
    database_name: str = Field(..., min_length=1, max_length=255, description="Target database/schema name")
    username: str = Field(..., min_length=1, max_length=255, description="Database username")
    password: str = Field(..., min_length=0, max_length=1024, description="Database password")
    ssl_mode: SSLMode = Field(SSLMode.require, description="SSL/TLS mode")
    query_timeout: int = Field(30, ge=1, le=300, description="Query timeout in seconds")
    max_rows: int = Field(10000, ge=1, le=100000, description="Maximum rows returned per query")
    allowed_schemas: list[str] = Field(
        default=["public"],
        description="Allowlist of database schemas accessible through this connection",
    )


class ConnectionUpdateRequest(BaseModel):
    """
    PATCH /api/v1/connections/{connection_id} — body.

    All fields optional. If username/password are omitted, existing
    encrypted credentials are preserved. If either is supplied,
    both must be supplied (enforced in route logic).
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    host: Optional[str] = Field(None, min_length=1, max_length=500)
    port: Optional[int] = Field(None, ge=1, le=65535)
    database_name: Optional[str] = Field(None, min_length=1, max_length=255)
    username: Optional[str] = Field(None, min_length=1, max_length=255)
    password: Optional[str] = Field(None, min_length=0, max_length=1024)
    ssl_mode: Optional[SSLMode] = None
    query_timeout: Optional[int] = Field(None, ge=1, le=300)
    max_rows: Optional[int] = Field(None, ge=1, le=100000)
    allowed_schemas: Optional[list[str]] = None
    is_active: Optional[bool] = None


# =============================================================================
# Response Schemas
# =============================================================================

class ConnectionResponse(BaseModel):
    """
    Safe connection representation — NEVER includes credentials.

    encrypted_credentials, username, and password are intentionally absent.
    Admins see the connection metadata but cannot retrieve the stored password
    through the API.
    """
    model_config = ConfigDict(from_attributes=True)

    connection_id: str
    name: str
    db_type: str
    host: Optional[str]
    port: Optional[int]
    database_name: Optional[str]
    ssl_mode: str
    query_timeout: int
    max_rows: int
    allowed_schemas: Optional[list[str]]
    is_active: bool
    created_by: Optional[str]


class ConnectionListResponse(BaseModel):
    """Paginated list of connections."""
    connections: list[ConnectionResponse]
    total: int
    skip: int
    limit: int


class ConnectionTestResponse(BaseModel):
    """
    POST /api/v1/connections/{connection_id}/test — response.

    Reports the result of a TCP-level connectivity check to the
    SSRF-validated, DNS-pinned host:port.
    """
    success: bool
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    resolved_ip: Optional[str] = Field(
        None,
        description="The DNS-pinned IP used for the connection attempt (audit/debug)",
    )