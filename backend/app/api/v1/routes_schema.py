"""
Smart BI Agent — Schema Routes
Architecture v3.1 | Layer 4 | Component 11

ENDPOINTS:
    GET  /api/v1/schema/{connection_id}         — Fetch schema (cached, permission-filtered)
    POST /api/v1/schema/{connection_id}/refresh — Admin: invalidate cache + force re-fetch

CACHE (Redis DB 0):
    Key:  schema:{connection_id}:{sha256(user_id)}   TTL: 900s
    Lock: schema_lock:{connection_id}                TTL: 30s  (stampede prevention)

PIPELINE on cache miss:
    1. Fetch connection from DB (verify active)
    2. Acquire stampede lock
    3. _introspect_schema(conn) — stub, wired to real reader in Phase 3
    4. Load user permissions (role → dept → user override)
    5. Filter tables by permissions
    6. Sanitize all identifiers
    7. Store in cache (TTL 900s)
    8. Return schema

ACCESS:
    GET    — require_analyst_or_above  (analysts need schema to build queries)
    POST   — require_admin             (cache invalidation is admin-only)

SECURITY:
    - Identifiers sanitized with sanitize_schema_identifier() before storage + return
    - Permission filtering: denied_tables removed, denied_columns stripped from columns
    - Cache key includes user_id hash — different users get different cached views
    - Stampede lock prevents N simultaneous DB introspections on cold cache
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUser,
    get_audit_writer,
    get_db,
    get_key_manager,
    get_redis_cache,
    require_admin,
    require_analyst_or_above,
)
from app.errors.exceptions import ResourceNotFoundError
from app.logging.structured import get_logger
from app.models.connection import Connection
from app.models.permission import (
    DepartmentPermission,
    RolePermission,
    UserPermission,
)
from app.schemas.schema import SchemaRefreshResponse, SchemaResponse, TableInfo, ColumnInfo
from app.security.sanitizer import sanitize_schema_identifier

log = get_logger(__name__)
router = APIRouter()

_SCHEMA_TTL = 900       # 15 minutes
_LOCK_TTL   = 30        # stampede lock


# =============================================================================
# Helpers
# =============================================================================

def _user_hash(user_id: str) -> str:
    """Stable 16-char hex hash of user_id for cache key."""
    return hashlib.sha256(user_id.encode()).hexdigest()[:16]


def _cache_key(connection_id: str, user_id: str) -> str:
    return f"schema:{connection_id}:{_user_hash(user_id)}"


def _lock_key(connection_id: str) -> str:
    return f"schema_lock:{connection_id}"


async def _get_connection_or_404(connection_id: uuid.UUID, db: AsyncSession) -> Connection:
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


async def _load_permissions(
    user_id: str,
    role: str,
    department: str,
    connection_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """
    Load all three permission tiers for this user + connection.
    Returns a merged dict with allowed_tables and denied_columns sets.
    """
    # Tier 1 — Role
    role_result = await db.execute(
        select(RolePermission).where(
            RolePermission.role == role,
            RolePermission.connection_id == connection_id,
        )
    )
    role_perm = role_result.scalar_one_or_none()

    # Tier 2 — Department
    dept_perm = None
    if department:
        dept_result = await db.execute(
            select(DepartmentPermission).where(
                DepartmentPermission.department == department,
                DepartmentPermission.connection_id == connection_id,
            )
        )
        dept_perm = dept_result.scalar_one_or_none()

    # Tier 3 — User override
    user_result = await db.execute(
        select(UserPermission).where(
            UserPermission.user_id == uuid.UUID(user_id),
            UserPermission.connection_id == connection_id,
        )
    )
    user_perm = user_result.scalar_one_or_none()

    # Merge: highest tier wins
    allowed_tables: list[str] = []
    denied_tables:  set[str]  = set()
    denied_columns: set[str]  = set()

    if role_perm:
        allowed_tables = list(role_perm.allowed_tables or [])
        denied_columns.update(role_perm.denied_columns or [])

    if dept_perm:
        if dept_perm.allowed_tables:
            allowed_tables = list(dept_perm.allowed_tables)
        denied_columns.update(dept_perm.denied_columns or [])

    if user_perm:
        if user_perm.allowed_tables:
            allowed_tables = list(user_perm.allowed_tables)
        denied_tables.update(user_perm.denied_tables or [])
        denied_columns.update(user_perm.denied_columns or [])

    return {
        "allowed_tables": allowed_tables,
        "denied_tables":  denied_tables,
        "denied_columns": denied_columns,
    }


def _filter_schema(
    raw_schema: dict[str, Any],
    allowed_tables: list[str],
    denied_tables: set[str],
    denied_columns: set[str],
) -> dict[str, Any]:
    """
    Apply permission filtering and identifier sanitization.

    Rules (3-tier, highest wins):
      - allowed_tables: if non-empty, only these tables are shown
      - denied_tables:  these tables are always removed (user-tier override)
      - denied_columns: these columns are stripped from ALL tables
    """
    filtered: dict[str, Any] = {}

    for raw_table, table_data in raw_schema.items():
        table_name = sanitize_schema_identifier(raw_table)
        if not table_name:
            continue

        # Apply table-level filters
        if denied_tables and table_name in denied_tables:
            continue
        if allowed_tables and table_name not in allowed_tables:
            continue

        # Filter + sanitize columns
        raw_columns = table_data.get("columns", {})
        filtered_columns: dict[str, Any] = {}
        for raw_col, col_info in raw_columns.items():
            col_name = sanitize_schema_identifier(raw_col)
            if not col_name:
                continue
            if col_name in denied_columns:
                continue
            filtered_columns[col_name] = col_info

        filtered[table_name] = {"columns": filtered_columns}

    return filtered


async def _introspect_schema(conn: Connection, key_manager) -> dict[str, Any]:
    """
    DB schema introspection via shared service.
    Routes to the correct adapter by db_type.
    """
    from app.services.schema_reader import introspect_schema
    return await introspect_schema(conn, key_manager)


# =============================================================================
# Routes
# =============================================================================

@router.get(
    "/{connection_id}",
    response_model=SchemaResponse,
    summary="Get schema for a connection (cached, permission-filtered)",
)
async def get_schema(
    connection_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_analyst_or_above),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis_cache),
    key_manager=Depends(get_key_manager),
) -> SchemaResponse:
    """
    Returns the sanitized, permission-filtered schema for a connection.

    Cache hit  → returns immediately (TTL 900s, key includes user_id hash).
    Cache miss → introspects DB, filters by permissions, sanitizes, caches.

    Stampede lock (schema_lock:{conn_id}, TTL 30s) prevents N simultaneous
    introspections when cache is cold.
    """
    user_id     = current_user["user_id"]
    role        = current_user.get("role", "viewer")
    department  = current_user.get("department", "")

    # 1. Verify connection exists
    conn = await _get_connection_or_404(connection_id, db)

    # 2. Check cache
    key    = _cache_key(str(connection_id), user_id)
    cached = None
    cache_age: Optional[int] = None

    if redis is not None:
        try:
            cached_bytes = await redis.get(key)
            if cached_bytes:
                ttl = await redis.ttl(key)
                cache_age = _SCHEMA_TTL - ttl if ttl >= 0 else None
                schema_data = json.loads(cached_bytes)
                return SchemaResponse(
                    connection_id=str(connection_id),
                    schema_data=schema_data,
                    cached=True,
                    cache_age_seconds=cache_age,
                )
        except Exception:
            log.warning("schema.cache_read_failed", connection_id=str(connection_id))

    # 3. Load permissions (3 tiers)
    perms = await _load_permissions(user_id, role, department, connection_id, db)

    # 4. Introspect (with stampede lock)
    lock_key = _lock_key(str(connection_id))
    if redis is not None:
        try:
            await redis.set(lock_key, "1", ex=_LOCK_TTL, nx=True)
        except Exception:
            pass

    raw_schema = await _introspect_schema(conn, key_manager)

    # 5. Filter + sanitize
    schema_data = _filter_schema(
        raw_schema,
        allowed_tables=perms["allowed_tables"],
        denied_tables=perms["denied_tables"],
        denied_columns=perms["denied_columns"],
    )

    # 6. Cache result
    if redis is not None:
        try:
            await redis.set(key, json.dumps(schema_data), ex=_SCHEMA_TTL)
            if redis is not None:
                await redis.delete(lock_key)
        except Exception:
            log.warning("schema.cache_write_failed", connection_id=str(connection_id))

    log.info("schema.fetched", connection_id=str(connection_id), user_id=user_id, cached=False)

    return SchemaResponse(
        connection_id=str(connection_id),
        schema_data=schema_data,
        cached=False,
        cache_age_seconds=None,
    )


@router.post(
    "/{connection_id}/refresh",
    response_model=SchemaRefreshResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin: invalidate schema cache for a connection",
)
async def refresh_schema(
    connection_id: uuid.UUID,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis_cache),
    audit=Depends(get_audit_writer),
) -> SchemaRefreshResponse:
    """
    Invalidates all schema cache entries for the given connection.

    All per-user cached views (schema:{connection_id}:*) are deleted.
    Next fetch for any user will re-introspect the live DB.

    Admin-only — deliberate action with audit trail.
    """
    # Verify connection exists
    await _get_connection_or_404(connection_id, db)

    keys_deleted = 0
    pattern = f"schema:{connection_id}:*"

    if redis is not None:
        try:
            keys = await redis.keys(pattern)
            if keys:
                keys_deleted = await redis.delete(*keys)
        except Exception:
            log.warning("schema.cache_invalidation_failed", connection_id=str(connection_id))

    log.info(
        "schema.cache_refreshed",
        admin_id=admin["user_id"],
        connection_id=str(connection_id),
        keys_deleted=keys_deleted,
    )

    if audit:
        await audit.log(
            execution_status="schema.cache_refreshed",
            question=f"Schema cache invalidated for connection {connection_id} ({keys_deleted} keys deleted)",
            user_id=admin["user_id"],
            ip_address=request.client.host if request.client else "unknown",
            request_id=getattr(request.state, "request_id", None),
        )

    return SchemaRefreshResponse(
        connection_id=str(connection_id),
        keys_deleted=keys_deleted,
    )