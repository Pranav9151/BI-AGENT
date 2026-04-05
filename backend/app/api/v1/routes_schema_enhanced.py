"""
Smart BI Agent — Enhanced Schema Routes (Phase 12)
Architecture v3.1 | Layer 4

PURPOSE:
    Extends the base schema browser with:
      1. Foreign key relationship detection → ERD visualization
      2. Data profiling (sample values, null %, distinct count)
      3. Table row count estimates

ENDPOINTS:
    GET  /api/v1/schema/{connection_id}/relationships  — FK relationships
    GET  /api/v1/schema/{connection_id}/profile/{table} — Column profiling
    GET  /api/v1/schema/{connection_id}/stats           — Table-level stats

SECURITY:
    All endpoints require analyst_or_above.
    Profiling queries use LIMIT and are read-only.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUser,
    get_db,
    get_key_manager,
    get_redis_cache,
    require_analyst_or_above,
)
from app.errors.exceptions import ResourceNotFoundError, ValidationError
from app.logging.structured import get_logger
from app.models.connection import Connection
from app.security.key_manager import KeyPurpose

log = get_logger(__name__)
router = APIRouter()


# =============================================================================
# Response Schemas
# =============================================================================

class Relationship(BaseModel):
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    constraint_name: str = ""


class RelationshipsResponse(BaseModel):
    connection_id: str
    relationships: list[Relationship]
    table_count: int


class ColumnProfile(BaseModel):
    column_name: str
    data_type: str
    null_count: int = 0
    null_pct: float = 0.0
    distinct_count: int = 0
    sample_values: list[str] = []
    min_value: Optional[str] = None
    max_value: Optional[str] = None


class TableProfile(BaseModel):
    table_name: str
    row_count: int
    columns: list[ColumnProfile]


class TableStat(BaseModel):
    table_name: str
    row_count_estimate: int
    column_count: int
    has_primary_key: bool
    primary_key_columns: list[str] = []
    index_count: int = 0


class StatsResponse(BaseModel):
    connection_id: str
    tables: list[TableStat]
    total_tables: int
    total_columns: int


# =============================================================================
# Helpers
# =============================================================================

async def _get_connection(connection_id: uuid.UUID, db: AsyncSession) -> Connection:
    result = await db.execute(
        select(Connection).where(Connection.id == connection_id, Connection.is_active == True)
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise ResourceNotFoundError(
            message="Connection not found.",
            detail=f"Connection {connection_id} does not exist or is inactive",
        )
    return conn


async def _get_postgres_conn(connection: Connection, key_manager: Any):
    """Create an asyncpg connection to the user's database."""
    import asyncpg

    creds = json.loads(
        key_manager.decrypt(connection.encrypted_credentials, KeyPurpose.DB_CREDENTIALS)
    )

    ssl_ctx: Any = False
    if connection.ssl_mode in ("require", "verify-ca", "verify-full"):
        ssl_ctx = "require"

    return await asyncpg.connect(
        host=connection.host,
        port=connection.port,
        database=connection.database_name,
        user=creds["username"],
        password=creds["password"],
        ssl=ssl_ctx,
        timeout=10,
    )


# =============================================================================
# GET /schema/{connection_id}/relationships
# =============================================================================

@router.get(
    "/{connection_id}/relationships",
    response_model=RelationshipsResponse,
    summary="Detect foreign key relationships between tables",
)
async def get_relationships(
    connection_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_analyst_or_above),
    db: AsyncSession = Depends(get_db),
    key_manager=Depends(get_key_manager),
    redis=Depends(get_redis_cache),
) -> RelationshipsResponse:
    """
    Returns all foreign key relationships in the connection's allowed schemas.
    Used by the Schema Browser ERD visualization.
    """
    conn = await _get_connection(connection_id, db)
    db_type = (conn.db_type or "").lower()

    # Cache check
    cache_key = f"schema_rels:{connection_id}"
    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                data = json.loads(cached)
                return RelationshipsResponse(**data)
        except Exception:
            pass

    relationships: list[Relationship] = []
    table_count = 0

    if db_type in ("postgresql", "postgres"):
        pg = None
        try:
            pg = await _get_postgres_conn(conn, key_manager)
            schemas = conn.allowed_schemas or ["public"]
            ph = ", ".join(f"${i+1}" for i in range(len(schemas)))

            # Count tables
            count_result = await pg.fetchval(
                f"SELECT COUNT(*) FROM information_schema.tables "
                f"WHERE table_schema IN ({ph}) AND table_type = 'BASE TABLE'",
                *schemas
            )
            table_count = count_result or 0

            # Foreign keys
            fk_sql = f"""
                SELECT
                    tc.constraint_name,
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
                    AND tc.table_schema IN ({ph})
                ORDER BY tc.table_name
            """
            rows = await pg.fetch(fk_sql, *schemas)

            for row in rows:
                relationships.append(Relationship(
                    from_table=row["from_table"],
                    from_column=row["from_column"],
                    to_table=row["to_table"],
                    to_column=row["to_column"],
                    constraint_name=row["constraint_name"],
                ))

        except Exception as exc:
            log.warning("schema_enhanced.relationships_failed", error=str(exc))
        finally:
            if pg:
                await pg.close()

    result = RelationshipsResponse(
        connection_id=str(connection_id),
        relationships=relationships,
        table_count=table_count,
    )

    # Cache for 15 minutes
    if redis:
        try:
            await redis.set(cache_key, result.model_dump_json(), ex=900)
        except Exception:
            pass

    return result


# =============================================================================
# GET /schema/{connection_id}/profile/{table_name}
# =============================================================================

@router.get(
    "/{connection_id}/profile/{table_name}",
    response_model=TableProfile,
    summary="Profile a table's columns (null %, distinct count, samples)",
)
async def profile_table(
    connection_id: uuid.UUID,
    table_name: str,
    request: Request,
    current_user: CurrentUser = Depends(require_analyst_or_above),
    db: AsyncSession = Depends(get_db),
    key_manager=Depends(get_key_manager),
) -> TableProfile:
    """
    Returns data profiling information for a specific table.
    Analyzes null rates, distinct counts, min/max, and sample values.
    Uses LIMIT to keep profiling queries fast.
    """
    conn = await _get_connection(connection_id, db)
    db_type = (conn.db_type or "").lower()

    # Sanitize table name
    clean_table = table_name.replace('"', '').replace("'", '').replace(";", '')
    if not clean_table:
        raise ValidationError(message="Invalid table name.", detail="Table name is empty.")

    if db_type in ("postgresql", "postgres"):
        return await _profile_postgres(conn, key_manager, clean_table)

    raise ValidationError(
        message=f"Profiling not yet supported for {db_type}.",
        detail="Currently only PostgreSQL is supported for data profiling.",
    )


async def _profile_postgres(conn: Connection, key_manager: Any, table_name: str) -> TableProfile:
    """Profile a PostgreSQL table."""
    import asyncpg

    pg = None
    try:
        pg = await _get_postgres_conn(conn, key_manager)

        # Row count
        row_count = await pg.fetchval(f'SELECT COUNT(*) FROM "{table_name}"')

        # Get columns
        col_rows = await pg.fetch(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = $1 ORDER BY ordinal_position",
            table_name,
        )

        profiles: list[ColumnProfile] = []

        for col_row in col_rows:
            col_name = col_row["column_name"]
            data_type = col_row["data_type"]

            # Profile each column
            try:
                profile_sql = f"""
                    SELECT
                        COUNT(*) FILTER (WHERE "{col_name}" IS NULL) AS null_count,
                        COUNT(DISTINCT "{col_name}") AS distinct_count,
                        MIN("{col_name}"::text) AS min_val,
                        MAX("{col_name}"::text) AS max_val
                    FROM "{table_name}"
                """
                stats = await pg.fetchrow(profile_sql)

                # Sample values (up to 5 distinct)
                sample_sql = f"""
                    SELECT DISTINCT "{col_name}"::text AS val
                    FROM "{table_name}"
                    WHERE "{col_name}" IS NOT NULL
                    LIMIT 5
                """
                samples = await pg.fetch(sample_sql)

                null_count = stats["null_count"] or 0
                null_pct = (null_count / row_count * 100) if row_count > 0 else 0

                profiles.append(ColumnProfile(
                    column_name=col_name,
                    data_type=data_type,
                    null_count=null_count,
                    null_pct=round(null_pct, 1),
                    distinct_count=stats["distinct_count"] or 0,
                    sample_values=[r["val"] for r in samples if r["val"]],
                    min_value=stats["min_val"],
                    max_value=stats["max_val"],
                ))
            except Exception as exc:
                # Some columns may fail (e.g., bytea can't cast to text)
                profiles.append(ColumnProfile(
                    column_name=col_name,
                    data_type=data_type,
                ))

        return TableProfile(
            table_name=table_name,
            row_count=row_count or 0,
            columns=profiles,
        )

    except Exception as exc:
        log.error("schema_enhanced.profile_failed", table=table_name, error=str(exc))
        raise ValidationError(
            message=f"Failed to profile table '{table_name}'.",
            detail=str(exc),
        )

    finally:
        if pg:
            await pg.close()


# =============================================================================
# GET /schema/{connection_id}/stats
# =============================================================================

@router.get(
    "/{connection_id}/stats",
    response_model=StatsResponse,
    summary="Get table-level statistics (row counts, PKs, indexes)",
)
async def get_stats(
    connection_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_analyst_or_above),
    db: AsyncSession = Depends(get_db),
    key_manager=Depends(get_key_manager),
    redis=Depends(get_redis_cache),
) -> StatsResponse:
    """
    Returns table-level statistics: estimated row counts, primary keys,
    column counts, and index counts. Uses pg_stat and information_schema
    for fast estimates without full table scans.
    """
    conn = await _get_connection(connection_id, db)
    db_type = (conn.db_type or "").lower()

    if db_type not in ("postgresql", "postgres"):
        return StatsResponse(
            connection_id=str(connection_id),
            tables=[], total_tables=0, total_columns=0,
        )

    pg = None
    try:
        pg = await _get_postgres_conn(conn, key_manager)
        schemas = conn.allowed_schemas or ["public"]
        ph = ", ".join(f"${i+1}" for i in range(len(schemas)))

        # Table stats with row estimates from pg_stat
        stats_sql = f"""
            SELECT
                t.table_name,
                (SELECT reltuples::bigint FROM pg_class
                 WHERE oid = (t.table_schema || '.' || t.table_name)::regclass) AS row_estimate,
                COUNT(c.column_name) AS col_count
            FROM information_schema.tables t
            LEFT JOIN information_schema.columns c
                ON c.table_schema = t.table_schema AND c.table_name = t.table_name
            WHERE t.table_schema IN ({ph})
                AND t.table_type = 'BASE TABLE'
            GROUP BY t.table_schema, t.table_name
            ORDER BY t.table_name
        """
        rows = await pg.fetch(stats_sql, *schemas)

        # PK info
        pk_sql = f"""
            SELECT tc.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema IN ({ph})
        """
        pk_rows = await pg.fetch(pk_sql, *schemas)

        # Build PK map
        pk_map: dict[str, list[str]] = {}
        for pk in pk_rows:
            pk_map.setdefault(pk["table_name"], []).append(pk["column_name"])

        # Index count
        idx_sql = f"""
            SELECT tablename AS table_name, COUNT(*) AS idx_count
            FROM pg_indexes
            WHERE schemaname IN ({ph})
            GROUP BY tablename
        """
        idx_rows = await pg.fetch(idx_sql, *schemas)
        idx_map = {r["table_name"]: r["idx_count"] for r in idx_rows}

        tables: list[TableStat] = []
        total_columns = 0

        for row in rows:
            tname = row["table_name"]
            col_count = row["col_count"] or 0
            total_columns += col_count
            pks = pk_map.get(tname, [])

            tables.append(TableStat(
                table_name=tname,
                row_count_estimate=max(0, row["row_estimate"] or 0),
                column_count=col_count,
                has_primary_key=len(pks) > 0,
                primary_key_columns=pks,
                index_count=idx_map.get(tname, 0),
            ))

        return StatsResponse(
            connection_id=str(connection_id),
            tables=tables,
            total_tables=len(tables),
            total_columns=total_columns,
        )

    except Exception as exc:
        log.error("schema_enhanced.stats_failed", error=str(exc))
        return StatsResponse(
            connection_id=str(connection_id),
            tables=[], total_tables=0, total_columns=0,
        )

    finally:
        if pg:
            await pg.close()
