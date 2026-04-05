"""
Smart BI Agent — Structured Query Routes (Phase 12)
Architecture v3.1 | Layer 4+6

PURPOSE:
    Accepts structured field-based queries (dimensions, measures, filters)
    and generates correct SQL with proper JOINs — replacing the frontend
    buildSql() function that caused cross-join cartesian products.

ENDPOINT:
    POST /api/v1/query/structured — Execute a structured field-based query

WHY THIS EXISTS:
    The frontend StudioPage lets users drag columns from multiple tables
    into field wells. Previously, the frontend naively generated
    "SELECT ... FROM table1, table2" (implicit cross join), producing
    wildly incorrect numbers. This endpoint:
      1. Detects foreign key relationships between referenced tables
      2. Generates proper JOIN clauses
      3. Falls back to error if no relationship path exists
      4. Applies the same SQL validation + execution pipeline as /query/

SECURITY:
    Same as routes_query: analyst_or_above, SQL validation, column permissions.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.executor_factory import execute_query as run_query, get_dialect
from app.dependencies import (
    CurrentUser,
    get_audit_writer,
    get_db,
    get_key_manager,
    get_redis_cache,
    get_redis_coordination,
    require_analyst_or_above,
)
from app.errors.exceptions import (
    ResourceNotFoundError,
    SQLValidationError,
    ValidationError,
)
from app.logging.structured import get_logger
from app.models.connection import Connection
from app.services.sql_validator import validate_sql

log = get_logger(__name__)
router = APIRouter()


# =============================================================================
# Request / Response Schemas
# =============================================================================

class FieldSpec(BaseModel):
    """A single field (column) specification."""
    table: str = Field(..., description="Table name")
    column: str = Field(..., description="Column name")
    type: str = Field("text", description="Column type: numeric, text, date")
    agg: str = Field("NONE", description="Aggregation: SUM, COUNT, AVG, MIN, MAX, NONE")


class FilterSpec(BaseModel):
    """A single filter condition."""
    table: str
    column: str
    operator: str = Field("=", description="Operator: =, !=, >, <, >=, <=, LIKE, IN, NOT IN, IS NULL, IS NOT NULL")
    value: Optional[Any] = None
    values: Optional[list[Any]] = None  # For IN / NOT IN


class StructuredQueryRequest(BaseModel):
    """POST /api/v1/query/structured — body."""
    connection_id: str = Field(..., description="UUID of the database connection")
    dimensions: list[FieldSpec] = Field(default_factory=list, description="Group-by / X-axis fields")
    measures: list[FieldSpec] = Field(default_factory=list, description="Aggregated value fields")
    filters: list[FilterSpec] = Field(default_factory=list, description="WHERE conditions")
    order_by: Optional[str] = Field(None, description="Column name to order by")
    order_dir: str = Field("ASC", description="ASC or DESC")
    limit: int = Field(500, ge=1, le=10000, description="Max rows to return")


class StructuredQueryResponse(BaseModel):
    """POST /api/v1/query/structured — response."""
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    duration_ms: int
    truncated: bool
    tables_used: list[str]
    joins_generated: list[str]


# =============================================================================
# Relationship Detection (FK-based)
# =============================================================================

async def _detect_relationships(
    connection: Connection,
    key_manager: Any,
    tables: set[str],
) -> list[dict[str, str]]:
    """
    Detect foreign key relationships between the specified tables.
    
    Returns a list of relationship dicts:
    [{"from_table": "orders", "from_col": "customer_id",
      "to_table": "customers", "to_col": "id"}]
    """
    db_type = (connection.db_type or "").lower()
    
    if db_type in ("postgresql", "postgres"):
        return await _detect_relationships_postgres(connection, key_manager, tables)
    
    # For other DB types, return empty (no auto-join)
    return []


async def _detect_relationships_postgres(
    connection: Connection,
    key_manager: Any,
    tables: set[str],
) -> list[dict[str, str]]:
    """PostgreSQL FK relationship detection via information_schema."""
    import asyncpg
    from app.security.key_manager import KeyPurpose
    
    try:
        creds = json.loads(
            key_manager.decrypt(connection.encrypted_credentials, KeyPurpose.DB_CREDENTIALS)
        )
    except Exception:
        return []
    
    ssl_ctx: Any = False
    if connection.ssl_mode in ("require", "verify-ca", "verify-full"):
        ssl_ctx = "require"
    
    db_conn = None
    try:
        db_conn = await asyncpg.connect(
            host=connection.host,
            port=connection.port,
            database=connection.database_name,
            user=creds["username"],
            password=creds["password"],
            ssl=ssl_ctx,
            timeout=10,
        )
        
        schemas = connection.allowed_schemas or ["public"]
        placeholders = ", ".join(f"${i+1}" for i in range(len(schemas)))
        
        fk_sql = f"""
            SELECT
                tc.table_name AS from_table,
                kcu.column_name AS from_column,
                ccu.table_name AS to_table,
                ccu.column_name AS to_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
                AND tc.table_schema = ccu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema IN ({placeholders})
        """
        rows = await db_conn.fetch(fk_sql, *schemas)
        
        # Filter to only relationships between our tables
        relationships = []
        for row in rows:
            from_tbl = row["from_table"]
            to_tbl = row["to_table"]
            if from_tbl in tables and to_tbl in tables:
                relationships.append({
                    "from_table": from_tbl,
                    "from_col": row["from_column"],
                    "to_table": to_tbl,
                    "to_col": row["to_column"],
                })
        
        return relationships
    
    except Exception as exc:
        log.warning("structured_query.fk_detection_failed", error=str(exc))
        return []
    
    finally:
        if db_conn:
            try:
                await db_conn.close()
            except Exception:
                pass


# =============================================================================
# SQL Generation
# =============================================================================

VALID_AGGS = {"SUM", "COUNT", "AVG", "MIN", "MAX", "NONE"}
VALID_OPS = {"=", "!=", ">", "<", ">=", "<=", "LIKE", "IN", "NOT IN", "IS NULL", "IS NOT NULL"}


def _quote(identifier: str) -> str:
    """Quote a SQL identifier to prevent injection."""
    # Strip any existing quotes and re-quote
    clean = identifier.replace('"', '').replace("'", "").replace(";", "")
    return f'"{clean}"'


def _build_structured_sql(
    req: StructuredQueryRequest,
    relationships: list[dict[str, str]],
) -> tuple[str, list[str], list[str]]:
    """
    Build SQL from structured field specs.
    
    Returns:
        (sql_string, tables_used, joins_generated)
    
    Raises:
        ValidationError if tables can't be joined.
    """
    # Collect all referenced tables
    all_fields = req.dimensions + req.measures
    table_set: set[str] = set()
    for f in all_fields:
        table_set.add(f.table)
    for f in req.filters:
        table_set.add(f.table)
    
    tables = sorted(table_set)
    
    if not tables:
        raise ValidationError(
            message="No fields specified.",
            detail="At least one dimension or measure is required.",
        )
    
    # Build SELECT clause
    select_parts: list[str] = []
    group_by_parts: list[str] = []
    
    for d in req.dimensions:
        ref = f'{_quote(d.table)}.{_quote(d.column)}'
        select_parts.append(f'{ref} AS {_quote(d.column)}')
        group_by_parts.append(ref)
    
    for m in req.measures:
        ref = f'{_quote(m.table)}.{_quote(m.column)}'
        agg = m.agg.upper() if m.agg.upper() in VALID_AGGS else "NONE"
        if agg == "NONE":
            select_parts.append(f'{ref} AS {_quote(m.column)}')
        else:
            select_parts.append(f'{agg}({ref}) AS {_quote(m.column)}')
    
    if not select_parts:
        raise ValidationError(
            message="No columns to select.",
            detail="Add at least one dimension or measure.",
        )
    
    # Build FROM + JOIN clauses
    joins_generated: list[str] = []
    
    if len(tables) == 1:
        from_clause = _quote(tables[0])
    else:
        # Multi-table: need JOIN paths
        if not relationships:
            raise ValidationError(
                message=f"Cannot join tables: {', '.join(tables)}. No foreign key relationships found between these tables.",
                detail="Define table relationships or select fields from a single table.",
            )
        
        # Build join chain using detected relationships
        from_clause, join_clauses = _build_join_chain(tables, relationships)
        joins_generated = join_clauses
    
    # Build WHERE clause
    where_parts: list[str] = []
    for f in req.filters:
        op = f.operator.upper()
        if op not in VALID_OPS:
            continue
        ref = f'{_quote(f.table)}.{_quote(f.column)}'
        
        if op in ("IS NULL", "IS NOT NULL"):
            where_parts.append(f'{ref} {op}')
        elif op in ("IN", "NOT IN") and f.values:
            vals = ", ".join(f"'{str(v)}'" for v in f.values)
            where_parts.append(f'{ref} {op} ({vals})')
        elif f.value is not None:
            val = str(f.value).replace("'", "''")  # Escape single quotes
            where_parts.append(f"{ref} {op} '{val}'")
    
    # Assemble
    sql = f"SELECT {', '.join(select_parts)} FROM {from_clause}"
    
    for jc in joins_generated:
        sql += f" {jc}"
    
    if where_parts:
        sql += f" WHERE {' AND '.join(where_parts)}"
    
    if group_by_parts:
        sql += f" GROUP BY {', '.join(group_by_parts)}"
    
    # ORDER BY
    if req.order_by:
        direction = "DESC" if req.order_dir.upper() == "DESC" else "ASC"
        sql += f" ORDER BY {_quote(req.order_by)} {direction}"
    elif req.dimensions:
        sql += f" ORDER BY {_quote(req.dimensions[0].column)}"
    
    sql += f" LIMIT {req.limit}"
    
    return sql, tables, [str(j) for j in joins_generated]


def _build_join_chain(
    tables: list[str],
    relationships: list[dict[str, str]],
) -> tuple[str, list[str]]:
    """
    Build a JOIN chain connecting all tables using FK relationships.
    
    Uses a simple BFS approach: start with the first table, greedily
    join tables that have a direct FK relationship.
    
    Returns:
        (base_table_quoted, list_of_join_clauses)
    """
    joined = {tables[0]}
    remaining = set(tables[1:])
    join_clauses: list[str] = []
    
    # Build adjacency from relationships
    adj: dict[str, list[dict]] = {}
    for r in relationships:
        adj.setdefault(r["from_table"], []).append(r)
        # Also add reverse direction
        adj.setdefault(r["to_table"], []).append({
            "from_table": r["to_table"],
            "from_col": r["to_col"],
            "to_table": r["from_table"],
            "to_col": r["from_col"],
        })
    
    max_iterations = len(tables) * 2
    iteration = 0
    
    while remaining and iteration < max_iterations:
        iteration += 1
        found = False
        
        for tbl in list(remaining):
            # Check if any joined table has a relationship to this table
            for joined_tbl in joined:
                for rel in adj.get(joined_tbl, []):
                    if rel["to_table"] == tbl:
                        join_clauses.append(
                            f'JOIN {_quote(tbl)} ON {_quote(joined_tbl)}.{_quote(rel["from_col"])} = {_quote(tbl)}.{_quote(rel["to_col"])}'
                        )
                        joined.add(tbl)
                        remaining.discard(tbl)
                        found = True
                        break
                if found:
                    break
            if found:
                break
        
        if not found:
            # No more joinable tables
            break
    
    if remaining:
        raise ValidationError(
            message=f"Cannot find join path for tables: {', '.join(remaining)}. No foreign key relationship connects them to the other tables.",
            detail="Use AI Query mode or select fields from related tables only.",
        )
    
    return _quote(tables[0]), join_clauses


# =============================================================================
# Route
# =============================================================================

@router.post(
    "/structured",
    response_model=StructuredQueryResponse,
    summary="Execute a structured field-based query with auto-JOINs",
)
async def structured_query(
    body: StructuredQueryRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_analyst_or_above),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis_cache),
    key_manager=Depends(get_key_manager),
    audit=Depends(get_audit_writer),
) -> StructuredQueryResponse:
    """
    Execute a structured query built from field specifications.
    
    Unlike the NL query endpoint, this accepts explicit field definitions
    (dimensions, measures, filters) and generates SQL with proper JOINs
    based on detected foreign key relationships.
    
    This is used by the Studio dashboard builder when users drag fields
    from schema into field wells.
    """
    pipeline_start = time.monotonic()
    user_id = current_user["user_id"]
    
    # Validate connection
    try:
        conn_uuid = uuid.UUID(body.connection_id)
    except ValueError:
        raise ValidationError(
            message="Invalid connection ID.",
            detail=f"'{body.connection_id}' is not a valid UUID.",
        )
    
    result = await db.execute(
        select(Connection).where(Connection.id == conn_uuid, Connection.is_active == True)
    )
    connection = result.scalar_one_or_none()
    if connection is None:
        raise ResourceNotFoundError(
            message="Connection not found.",
            detail=f"Connection {conn_uuid} does not exist or is inactive.",
        )
    
    # Collect referenced tables
    all_fields = body.dimensions + body.measures
    table_set = {f.table for f in all_fields}
    for f in body.filters:
        table_set.add(f.table)
    
    # Detect FK relationships (only if multi-table)
    relationships: list[dict[str, str]] = []
    if len(table_set) > 1:
        relationships = await _detect_relationships(connection, key_manager, table_set)
    
    # Build SQL
    sql, tables_used, joins_generated = _build_structured_sql(body, relationships)
    
    log.info(
        "structured_query.sql_generated",
        user_id=user_id,
        tables=tables_used,
        joins=len(joins_generated),
        sql_length=len(sql),
    )
    
    # Validate SQL (same pipeline as NL queries)
    # Load allowed tables from schema
    from app.api.v1.routes_query import _load_schema_for_query
    role = current_user.get("role", "viewer")
    department = current_user.get("department", "")
    schema_data = await _load_schema_for_query(
        conn_uuid, user_id, role, department, db, redis, key_manager,
    )
    allowed_tables = set(schema_data.keys()) if schema_data else set()
    
    validation = validate_sql(
        raw_sql=sql,
        allowed_tables=allowed_tables,
        max_rows=connection.max_rows,
        dialect=get_dialect(connection.db_type),
    )
    
    # Execute
    query_result = await run_query(
        connection=connection,
        sql=validation.sql,
        key_manager=key_manager,
    )
    
    total_ms = int((time.monotonic() - pipeline_start) * 1000)
    
    # Audit
    if audit:
        await audit.log(
            execution_status="structured_query.executed",
            question=f"Structured: {len(body.dimensions)} dims, {len(body.measures)} measures, {len(body.filters)} filters",
            user_id=user_id,
            connection_id=conn_uuid,
            ip_address=request.client.host if request.client else "unknown",
            request_id=getattr(request.state, "request_id", None),
        )
    
    log.info(
        "structured_query.completed",
        user_id=user_id,
        row_count=query_result.row_count,
        total_ms=total_ms,
    )
    
    return StructuredQueryResponse(
        sql=validation.sql,
        columns=query_result.columns,
        rows=query_result.rows,
        row_count=query_result.row_count,
        duration_ms=query_result.duration_ms,
        truncated=query_result.truncated,
        tables_used=tables_used,
        joins_generated=joins_generated,
    )
