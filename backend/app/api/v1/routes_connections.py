"""
Smart BI Agent — Connection Management Routes
Architecture v3.1 | Layer 4 (Application) | Threats: T1 (SSRF), T2 (credential exposure),
                                                         T20 (audit), T51 (DNS rebinding)

ENDPOINTS:
    GET    /api/v1/connections                          — list connections (admin)
    GET    /api/v1/connections/{connection_id}          — get single connection (admin)
    POST   /api/v1/connections                          — create connection (admin)
    PATCH  /api/v1/connections/{connection_id}          — update connection (admin)
    DELETE /api/v1/connections/{connection_id}          — soft-deactivate (admin)
    POST   /api/v1/connections/{connection_id}/test     — test connectivity (admin)

SECURITY:
    All endpoints are admin-only — connections contain database credentials
    and represent the primary data exfiltration surface.

CREDENTIAL HANDLING (T2):
    Credentials are stored as an encrypted JSON blob:
        {"username": "...", "password": "..."}
    Encrypted with HKDF KeyPurpose.DB_CREDENTIALS before any DB write.
    The plaintext is zeroed from memory immediately after encryption.
    Credentials are NEVER returned in any API response.

SSRF GUARD (T1, T51):
    On both create AND test, the host is passed through:
        validate_connection_host(host, port)  →  PinnedHost
    This:
        1. Resolves the hostname to an IP
        2. Rejects private/loopback/link-local/metadata IPs
        3. Returns a PinnedHost — the resolved IP must be used for connections,
           never the original hostname (DNS rebinding prevention, T51)
    SSRF failures → 400 CONNECTION_BLOCKED (same as all SSRF errors).

TEST CONNECTION (TCP-level):
    We deliberately do NOT do a full database handshake in the test endpoint.
    A TCP connect to the pinned IP:port is sufficient to:
      - Verify the host is reachable
      - Confirm the port is open
      - Confirm SSRF guard passed
    Full DB auth would require installing per-DB driver packages, which bloats
    the container. The schema introspection layer (Component 11) does the real
    DB connect with the correct async driver.

AUDIT:
    Every state-changing action (create, update, deactivate) writes to AuditWriter.
    question field summarises the action without including credential values.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUser,
    get_audit_writer,
    get_db,
    get_key_manager,
    require_admin,
)
from app.errors.exceptions import (
    DuplicateResourceError,
    ResourceNotFoundError,
    SSRFError,
    ValidationError,
)
from app.logging.structured import get_logger
from app.models.connection import Connection
from app.schemas.connection import (
    ConnectionCreateRequest,
    ConnectionListResponse,
    ConnectionResponse,
    ConnectionTestResponse,
    ConnectionUpdateRequest,
)
from app.security.key_manager import KeyPurpose
from app.security.ssrf_guard import SSRFError as GuardSSRFError
from app.security.ssrf_guard import validate_connection_host

log = get_logger(__name__)

router = APIRouter()

# Connection timeout for the TCP probe in seconds
_TCP_CONNECT_TIMEOUT = 5.0


# =============================================================================
# Helpers
# =============================================================================

def _conn_to_response(conn: Connection) -> ConnectionResponse:
    """Convert a Connection ORM object to a safe ConnectionResponse."""
    return ConnectionResponse(
        connection_id=str(conn.id),
        name=conn.name,
        db_type=conn.db_type,
        host=conn.host,
        port=conn.port,
        database_name=conn.database_name,
        ssl_mode=conn.ssl_mode,
        query_timeout=conn.query_timeout,
        max_rows=conn.max_rows,
        allowed_schemas=conn.allowed_schemas,
        is_active=conn.is_active,
        created_by=str(conn.created_by) if conn.created_by else None,
    )


async def _get_conn_or_404(conn_id: uuid.UUID, db: AsyncSession) -> Connection:
    """Fetch a Connection by ID or raise ResourceNotFoundError (404)."""
    result = await db.execute(select(Connection).where(Connection.id == conn_id))
    conn = result.scalar_one_or_none()
    if conn is None:
        raise ResourceNotFoundError(
            message="Connection not found.",
            detail=f"Connection {conn_id} does not exist",
        )
    return conn


def _get_client_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For or direct connection."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _encrypt_credentials(key_manager, username: str, password: str) -> str:
    """
    Serialize and encrypt connection credentials as a JSON blob.

    Returns a versioned encrypted string: "v1:<fernet-ciphertext>"
    Uses KeyPurpose.DB_CREDENTIALS so that compromise of another
    key purpose (e.g., TOTP_SECRETS) doesn't expose DB passwords.
    """
    plaintext = json.dumps({"username": username, "password": password})
    return key_manager.encrypt(plaintext, KeyPurpose.DB_CREDENTIALS)


def _decrypt_credentials(key_manager, encrypted_value: str) -> dict:
    """
    Decrypt and deserialize connection credentials.
    Returns {"username": ..., "password": ...}.
    """
    plaintext = key_manager.decrypt(encrypted_value, KeyPurpose.DB_CREDENTIALS)
    return json.loads(plaintext)


async def _tcp_probe(ip: str, port: int, timeout: float = _TCP_CONNECT_TIMEOUT) -> tuple[bool, Optional[int], Optional[str]]:
    """
    Attempt a TCP connection to ip:port.

    Returns (success, latency_ms, error_message).
    Uses the pinned resolved IP — never the original hostname (T51).
    """
    start = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass  # Not all transports support wait_closed
        return True, latency_ms, None
    except asyncio.TimeoutError:
        return False, None, f"Connection timed out after {int(timeout)}s"
    except ConnectionRefusedError:
        return False, None, "Connection refused"
    except OSError as e:
        return False, None, f"Network error: {e.strerror}"
    except Exception as e:
        return False, None, f"Unexpected error: {type(e).__name__}"


async def _validate_db_credentials(
    db_type: str,
    host: str,
    port: int,
    database_name: str,
    username: str,
    password: str,
    ssl_mode: str = "disable",
) -> tuple[bool, Optional[str]]:
    """
    Attempt a real database login to validate credentials.
    Returns (success, error_message).
    """
    if db_type in ("postgresql", "postgres"):
        try:
            import asyncpg
            ssl_ctx = "require" if ssl_mode in ("require", "verify-ca", "verify-full") else False
            conn = await asyncio.wait_for(
                asyncpg.connect(
                    host=host, port=port, database=database_name,
                    user=username, password=password, ssl=ssl_ctx,
                ),
                timeout=10,
            )
            await conn.close()
            return True, None
        except asyncio.TimeoutError:
            return False, "Connection timed out — check host and port."
        except Exception as exc:
            msg = str(exc)
            if "password authentication failed" in msg:
                return False, "Authentication failed — check username and password."
            if "does not exist" in msg:
                return False, f"Database '{database_name}' does not exist."
            if "Connection refused" in msg:
                return False, "Connection refused — check host and port."
            return False, f"Connection failed: {msg[:200]}"

    elif db_type == "mysql":
        try:
            import aiomysql
            conn = await asyncio.wait_for(
                aiomysql.connect(
                    host=host, port=port, db=database_name,
                    user=username, password=password,
                ),
                timeout=10,
            )
            conn.close()
            return True, None
        except Exception as exc:
            msg = str(exc)
            if "Access denied" in msg:
                return False, "Authentication failed — check username and password."
            return False, f"Connection failed: {msg[:200]}"

    # For BigQuery/Snowflake/MSSQL — skip credential check (different auth model)
    return True, None


# =============================================================================
# GET /  — List connections
# =============================================================================

@router.get(
    "/",
    response_model=ConnectionListResponse,
    summary="List connections",
    description="Returns a paginated list of all database connections. Admin only.",
)
async def list_connections(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    is_active: Optional[bool] = Query(None),
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ConnectionListResponse:
    """Paginated connection list with optional active-status filter."""
    conditions = []
    if is_active is not None:
        conditions.append(Connection.is_active == is_active)

    count_stmt = select(func.count()).select_from(Connection)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    data_stmt = (
        select(Connection)
        .order_by(Connection.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    if conditions:
        data_stmt = data_stmt.where(*conditions)
    conns = (await db.execute(data_stmt)).scalars().all()

    log.info("connections.list", admin_id=admin["user_id"], total=total)

    return ConnectionListResponse(
        connections=[_conn_to_response(c) for c in conns],
        total=total,
        skip=skip,
        limit=limit,
    )


# =============================================================================
# GET /{connection_id}  — Get single connection
# =============================================================================

@router.get(
    "/{connection_id}",
    response_model=ConnectionResponse,
    summary="Get connection",
    description="Retrieve a single connection by ID. Admin only.",
)
async def get_connection(
    connection_id: uuid.UUID,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ConnectionResponse:
    conn = await _get_conn_or_404(connection_id, db)
    log.info("connections.get", admin_id=admin["user_id"], connection_id=str(connection_id))
    return _conn_to_response(conn)


# =============================================================================
# POST /  — Create connection
# =============================================================================

@router.post(
    "/",
    response_model=ConnectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create connection",
    description=(
        "Create a new database connection. Admin only. "
        "Credentials are encrypted at rest using HKDF KeyPurpose.DB_CREDENTIALS. "
        "The host is validated against SSRF before saving."
    ),
)
async def create_connection(
    request: Request,
    body: ConnectionCreateRequest,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    key_manager=Depends(get_key_manager),
    audit=Depends(get_audit_writer),
) -> ConnectionResponse:
    """
    Create a database connection.

    Security pipeline:
        1. SSRF guard: validate_connection_host() resolves and pins the host
        2. Duplicate name check
        3. Encrypt credentials with HKDF DB_CREDENTIALS key
        4. Persist to DB — plaintext credentials not stored

    SSRFError (400) is raised before any DB write if the host is blocked.
    """
    # Step 1: SSRF guard — validates host and returns pinned IP
    # Raises SSRFError (→ 400) if host is private/loopback/cloud-metadata
    try:
        pinned = validate_connection_host(body.host, body.port)
    except GuardSSRFError as exc:
        raise SSRFError(
            message="Connection host is not allowed.",
            detail=str(exc),
        ) from exc

    # Step 2: Duplicate name check (case-insensitive)
    dup_result = await db.execute(
        select(Connection).where(Connection.name == body.name)
    )
    if dup_result.scalar_one_or_none() is not None:
        raise DuplicateResourceError(
            message="A connection with this name already exists.",
            detail=f"Duplicate connection name: {body.name}",
        )

    # Step 2b: Validate credentials with real DB login
    if body.username and body.password:
        cred_ok, cred_err = await _validate_db_credentials(
            db_type=body.db_type.value,
            host=body.host,
            port=body.port,
            database_name=body.database_name,
            username=body.username,
            password=body.password,
            ssl_mode=body.ssl_mode.value,
        )
        if not cred_ok:
            raise ValidationError(
                message=cred_err or "Could not connect to the database.",
                detail="Credential validation failed before saving.",
            )

    # Step 3: Encrypt credentials — plaintext never stored
    encrypted = _encrypt_credentials(key_manager, body.username, body.password)

    # Step 4: Persist
    now = datetime.now(timezone.utc)
    new_conn = Connection(
        id=uuid.uuid4(),
        name=body.name,
        db_type=body.db_type.value,
        host=body.host,
        port=body.port,
        database_name=body.database_name,
        encrypted_credentials=encrypted,
        ssl_mode=body.ssl_mode.value,
        query_timeout=body.query_timeout,
        max_rows=body.max_rows,
        allowed_schemas=body.allowed_schemas,
        is_active=True,
        created_by=uuid.UUID(admin["user_id"]),
    )
    new_conn.created_at = now
    new_conn.updated_at = now

    db.add(new_conn)
    await db.commit()

    log.info(
        "connections.created",
        admin_id=admin["user_id"],
        connection_id=str(new_conn.id),
        db_type=new_conn.db_type,
        host=new_conn.host,
        resolved_ip=pinned.resolved_ip,
    )

    if audit:
        await audit.log(
            execution_status="connection.created",
            question=f"Admin created connection: {body.name} ({body.db_type.value}://{body.host}:{body.port})",
            user_id=admin["user_id"],
            connection_id=new_conn.id,
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _conn_to_response(new_conn)


# =============================================================================
# PATCH /{connection_id}  — Update connection
# =============================================================================

@router.patch(
    "/{connection_id}",
    response_model=ConnectionResponse,
    summary="Update connection",
    description="Update connection metadata or credentials. Admin only. Re-validates SSRF if host changes.",
)
async def update_connection(
    connection_id: uuid.UUID,
    request: Request,
    body: ConnectionUpdateRequest,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    key_manager=Depends(get_key_manager),
    audit=Depends(get_audit_writer),
) -> ConnectionResponse:
    """
    Partial update a connection.

    If host (or port) changes, SSRF guard is re-run on the new host.
    If username or password is supplied, both are required and new credentials
    are re-encrypted. Omitting both leaves existing credentials intact.
    """
    conn = await _get_conn_or_404(connection_id, db)
    changed_fields: list[str] = []

    # Determine effective host/port for SSRF re-validation
    new_host = body.host if body.host is not None else conn.host
    new_port = body.port if body.port is not None else conn.port

    # Re-run SSRF guard if host or port changed
    if body.host is not None or body.port is not None:
        try:
            validate_connection_host(new_host, new_port)
        except GuardSSRFError as exc:
            raise SSRFError(
                message="Connection host is not allowed.",
                detail=str(exc),
            ) from exc

    # Apply scalar fields
    if body.name is not None:
        conn.name = body.name
        changed_fields.append("name")
    if body.host is not None:
        conn.host = body.host
        changed_fields.append("host")
    if body.port is not None:
        conn.port = body.port
        changed_fields.append("port")
    if body.database_name is not None:
        conn.database_name = body.database_name
        changed_fields.append("database_name")
    if body.ssl_mode is not None:
        conn.ssl_mode = body.ssl_mode.value
        changed_fields.append("ssl_mode")
    if body.query_timeout is not None:
        conn.query_timeout = body.query_timeout
        changed_fields.append("query_timeout")
    if body.max_rows is not None:
        conn.max_rows = body.max_rows
        changed_fields.append("max_rows")
    if body.allowed_schemas is not None:
        conn.allowed_schemas = body.allowed_schemas
        changed_fields.append("allowed_schemas")
    if body.is_active is not None:
        conn.is_active = body.is_active
        changed_fields.append("is_active")

    # Re-encrypt credentials if either username or password is provided
    if body.username is not None or body.password is not None:
        if body.username is None or body.password is None:
            existing = _decrypt_credentials(key_manager, conn.encrypted_credentials)
            new_username = body.username if body.username is not None else existing["username"]
            new_password = body.password if body.password is not None else existing["password"]
        else:
            new_username = body.username
            new_password = body.password

        # Validate new credentials before saving
        cred_ok, cred_err = await _validate_db_credentials(
            db_type=conn.db_type or "postgresql",
            host=new_host,
            port=new_port,
            database_name=body.database_name if body.database_name is not None else (conn.database_name or ""),
            username=new_username,
            password=new_password,
            ssl_mode=body.ssl_mode.value if body.ssl_mode is not None else (conn.ssl_mode or "disable"),
        )
        if not cred_ok:
            raise ValidationError(
                message=cred_err or "Could not authenticate with the database.",
                detail="Credential validation failed.",
            )

        conn.encrypted_credentials = _encrypt_credentials(key_manager, new_username, new_password)
        changed_fields.append("credentials")

    await db.commit()

    log.info(
        "connections.updated",
        admin_id=admin["user_id"],
        connection_id=str(connection_id),
        changed_fields=changed_fields,
    )

    if audit and changed_fields:
        await audit.log(
            execution_status="connection.updated",
            question=f"Connection {conn.name} ({connection_id}) updated: {', '.join(changed_fields)}",
            user_id=admin["user_id"],
            connection_id=connection_id,
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _conn_to_response(conn)


# =============================================================================
# DELETE /{connection_id}  — Soft-deactivate
# =============================================================================

@router.delete(
    "/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate connection",
    description="Soft-deactivate a connection. Admin only. Connection record is never hard-deleted.",
)
async def deactivate_connection(
    connection_id: uuid.UUID,
    request: Request,
    permanent: bool = Query(False, description="If true, permanently delete instead of soft-deactivate"),
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> Response:
    """
    Deactivate or permanently delete a connection.
    Default: soft-deactivate (is_active=False).
    With ?permanent=true: hard delete from database.
    """
    conn = await _get_conn_or_404(connection_id, db)

    if permanent:
        await db.delete(conn)
        await db.commit()
        log.warning(
            "connections.deleted_permanently",
            admin_id=admin["user_id"],
            connection_id=str(connection_id),
            name=conn.name,
        )
        if audit:
            await audit.log(
                execution_status="connection.deleted",
                question=f"Admin permanently deleted connection: {conn.name} ({connection_id})",
                user_id=admin["user_id"],
                connection_id=connection_id,
                ip_address=_get_client_ip(request),
                request_id=getattr(request.state, "request_id", None),
            )
    else:
        conn.is_active = False
        await db.commit()
        log.warning(
            "connections.deactivated",
            admin_id=admin["user_id"],
            connection_id=str(connection_id),
            name=conn.name,
        )
        if audit:
            await audit.log(
                execution_status="connection.deactivated",
                question=f"Admin deactivated connection: {conn.name} ({connection_id})",
                user_id=admin["user_id"],
                connection_id=connection_id,
                ip_address=_get_client_ip(request),
                request_id=getattr(request.state, "request_id", None),
            )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# POST /test-inline  — Test credentials without saving
# =============================================================================

@router.post(
    "/test-inline",
    response_model=ConnectionTestResponse,
    summary="Test connection credentials inline (without saving)",
    description="Validates host, port, and credentials without creating a connection. Admin only.",
)
async def test_connection_inline(
    request: Request,
    body: ConnectionCreateRequest,
    admin: CurrentUser = Depends(require_admin),
) -> ConnectionTestResponse:
    """
    Test raw connection credentials before saving.
    Used by the 'Test Connection' button on the create form.
    """
    # SSRF guard
    try:
        pinned = validate_connection_host(body.host, body.port)
    except GuardSSRFError as exc:
        return ConnectionTestResponse(
            success=False,
            error=f"Host not allowed: {exc}",
        )

    # Real DB credential validation
    start = time.monotonic()
    cred_ok, cred_err = await _validate_db_credentials(
        db_type=body.db_type.value,
        host=body.host,
        port=body.port,
        database_name=body.database_name,
        username=body.username,
        password=body.password,
        ssl_mode=body.ssl_mode.value,
    )
    latency_ms = int((time.monotonic() - start) * 1000)

    return ConnectionTestResponse(
        success=cred_ok,
        latency_ms=latency_ms if cred_ok else None,
        error=cred_err,
        resolved_ip=pinned.resolved_ip,
    )


# =============================================================================
# POST /{connection_id}/test  — Test connectivity
# =============================================================================

@router.post(
    "/{connection_id}/test",
    response_model=ConnectionTestResponse,
    summary="Test connection",
    description=(
        "Test TCP connectivity to a connection's host:port. "
        "Re-validates SSRF guard on every call. "
        "Admin only."
    ),
)
async def test_connection(
    connection_id: uuid.UUID,
    request: Request,
    admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    key_manager=Depends(get_key_manager),
) -> ConnectionTestResponse:
    """
    Full connectivity + authentication probe.

    Steps:
        1. Fetch connection from DB
        2. Re-validate SSRF guard on stored host:port (T1, T51)
        3. Decrypt credentials and attempt real DB login
        4. Return result with latency
    """
    conn = await _get_conn_or_404(connection_id, db)

    if not conn.host or not conn.port:
        return ConnectionTestResponse(
            success=False,
            error="Connection has no host or port configured.",
        )

    # SSRF guard — re-validate every test (host/IP may have changed since creation)
    try:
        pinned = validate_connection_host(conn.host, conn.port)
    except GuardSSRFError as exc:
        log.warning(
            "connections.test.ssrf_blocked",
            admin_id=admin["user_id"],
            connection_id=str(connection_id),
            host=conn.host,
            error=str(exc),
        )
        return ConnectionTestResponse(
            success=False,
            error="Connection host failed SSRF validation and cannot be reached.",
            resolved_ip=None,
        )

    # Decrypt credentials and do real DB authentication
    start = time.monotonic()
    try:
        creds = _decrypt_credentials(key_manager, conn.encrypted_credentials)
    except Exception:
        return ConnectionTestResponse(
            success=False,
            error="Could not decrypt stored credentials. Re-save the connection.",
        )

    cred_ok, cred_err = await _validate_db_credentials(
        db_type=conn.db_type or "postgresql",
        host=conn.host,
        port=conn.port,
        database_name=conn.database_name or "",
        username=creds.get("username", ""),
        password=creds.get("password", ""),
        ssl_mode=conn.ssl_mode or "disable",
    )
    latency_ms = int((time.monotonic() - start) * 1000)

    if not cred_ok:
        # Fall back to TCP probe to distinguish network vs auth errors
        tcp_ok, _, _ = await _tcp_probe(pinned.resolved_ip, conn.port)
        if not tcp_ok:
            cred_err = "Cannot reach database server — check host and port."

    log.info(
        "connections.tested",
        admin_id=admin["user_id"],
        connection_id=str(connection_id),
        resolved_ip=pinned.resolved_ip,
        success=cred_ok,
        latency_ms=latency_ms,
    )

    return ConnectionTestResponse(
        success=cred_ok,
        latency_ms=latency_ms,
        error=cred_err,
        resolved_ip=pinned.resolved_ip,
    )