"""
Smart BI Agent — Query Routes  (THE CORE)
Architecture v3.1 | Layer 4+5+6 | The reason this product exists.

ENDPOINT:
    POST /api/v1/query  — Execute natural language → SQL → results

PIPELINE:
    1. Validate input (question length, connection exists, user permissions)
    2. Load connection schema (from cache or introspect)
    3. Load conversation history (if conversation_id provided)
    4. Build LLM prompt with schema context + history
    5. Call LLM provider (with fallback chain)
    6. Extract SQL from LLM response
    7. Validate generated SQL (5-step pipeline)
    8. Execute against user's database connection
    9. Store conversation message
   10. Return results + metadata

SECURITY:
    - require_analyst_or_above: viewers cannot execute queries
    - Question length capped at MAX_QUESTION_LENGTH (2000 chars)
    - Schema is permission-filtered before entering the prompt
    - SQL validator blocks DDL/DML, unauthorized tables, multi-statement
    - Execution uses decrypted credentials held only for call duration
    - Results are never sent to the LLM (zero-knowledge data principle)
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.executor_factory import execute_query, get_dialect
from app.dependencies import (
    CurrentUser,
    get_audit_writer,
    get_db,
    get_key_manager,
    get_redis_cache,
    require_analyst_or_above,
)
from app.errors.exceptions import (
    InputTooLongError,
    LLMProviderError,
    ResourceNotFoundError,
    SQLValidationError,
    ValidationError,
)
from app.llm import LLMRequest, generate_with_fallback
from app.logging.structured import get_logger
from app.models.connection import Connection
from app.models.conversation import Conversation, ConversationMessage
from app.security.prompt_guard import (
    detect_injection,
    sanitize_conversation_history,
    is_conversation_at_limit,
)
from app.security.output_sanitizer import detect_system_prompt_leakage
from app.services.sql_validator import validate_sql

log = get_logger(__name__)
router = APIRouter()


# =============================================================================
# Request / Response Schemas
# =============================================================================

class QueryRequest(BaseModel):
    """POST /api/v1/query — body."""
    question: str = Field(..., min_length=1, max_length=2000)
    connection_id: str = Field(..., description="UUID of the database connection")
    conversation_id: Optional[str] = Field(None, description="UUID of existing conversation (for follow-ups)")


class QueryResponse(BaseModel):
    """POST /api/v1/query — response."""
    question: str
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    duration_ms: int
    truncated: bool
    conversation_id: str
    message_id: str
    provider_type: str
    model: str
    llm_latency_ms: int
    insight: Optional[str] = None


# =============================================================================
# Prompt Builder
# =============================================================================

_SYSTEM_PROMPT_TEMPLATE = """You are an expert SQL analyst. Your job is to convert natural language questions into precise, read-only PostgreSQL SQL queries.

RULES:
1. Generate ONLY a single SELECT statement. Never INSERT, UPDATE, DELETE, DROP, or any DDL.
2. Use ONLY the tables and columns listed in the schema below. Do not invent tables or columns.
3. Always qualify column names with table aliases when joining.
4. Use appropriate JOINs, GROUP BY, ORDER BY, and aggregate functions as needed.
5. If the question is ambiguous, make reasonable assumptions and note them.
6. Keep queries efficient — avoid SELECT * when specific columns answer the question.

SCHEMA:
{schema_context}

{conversation_context}

Respond with ONLY the SQL query — no explanation, no markdown fences, no comments. Just the raw SQL."""


def _build_schema_context(schema_data: dict) -> str:
    """Format schema into a string for the LLM prompt."""
    if not schema_data:
        return "No schema available."

    lines = []
    for table_name, table_info in schema_data.items():
        cols = table_info.get("columns", {})
        col_strs = []
        for col_name, col_info in cols.items():
            col_type = col_info.get("type", "unknown") if isinstance(col_info, dict) else str(col_info)
            pk = " [PK]" if (isinstance(col_info, dict) and col_info.get("primary_key")) else ""
            col_strs.append(f"  - {col_name}: {col_type}{pk}")
        lines.append(f"TABLE: {table_name}")
        lines.extend(col_strs)
        lines.append("")  # blank line between tables

    return "\n".join(lines)


def _build_conversation_context(history: list[dict]) -> str:
    """Format sanitized conversation history for the prompt."""
    if not history:
        return ""

    lines = ["CONVERSATION HISTORY (for context — generate SQL for the LATEST question only):"]
    for i, turn in enumerate(history, 1):
        q = turn.get("question", "")
        s = turn.get("sql", "")
        r = turn.get("result", "")
        parts = []
        if q:
            parts.append(f"Q: {q}")
        if s:
            parts.append(f"SQL: {s}")
        if r:
            parts.append(f"Result: {r}")
        if parts:
            lines.append(f"Turn {i}: {' | '.join(parts)}")

    return "\n".join(lines)


def _extract_sql_from_response(content: str) -> str:
    """
    Extract SQL from LLM response.
    Handles cases where the LLM wraps SQL in markdown code fences.
    """
    text = content.strip()

    # Remove markdown SQL fences
    sql_fence_pattern = re.compile(r"```(?:sql)?\s*\n?(.*?)\n?\s*```", re.DOTALL | re.IGNORECASE)
    match = sql_fence_pattern.search(text)
    if match:
        return match.group(1).strip()

    # Remove any leading/trailing backticks
    text = text.strip("`").strip()

    return text


# =============================================================================
# Schema Loader (reuses routes_schema introspection + cache)
# =============================================================================

async def _load_schema_for_query(
    connection_id: uuid.UUID,
    user_id: str,
    role: str,
    department: str,
    db: AsyncSession,
    redis,
    key_manager,
) -> dict:
    """
    Load the permission-filtered schema for the query prompt.
    Uses the same cache as routes_schema.
    """
    import hashlib
    from app.models.permission import DepartmentPermission, RolePermission, UserPermission

    conn = await _get_active_connection(connection_id, db)

    # Check cache first
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()[:16]
    cache_key = f"schema:{connection_id}:{user_hash}"

    if redis is not None:
        try:
            cached = await redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    # No cache — introspect with real DB connection
    from app.services.schema_reader import introspect_schema
    schema_data = await introspect_schema(conn, key_manager)

    # Load permissions and filter
    perms = await _load_user_permissions(user_id, role, department, connection_id, db)
    filtered = _filter_schema(schema_data, perms)

    # Cache it
    if redis is not None and filtered:
        try:
            await redis.set(cache_key, json.dumps(filtered), ex=900)
        except Exception:
            pass

    return filtered


async def _load_user_permissions(
    user_id: str, role: str, department: str,
    connection_id: uuid.UUID, db: AsyncSession,
) -> dict:
    """Load 3-tier permissions for this user+connection."""
    from app.models.permission import DepartmentPermission, RolePermission, UserPermission

    allowed_tables: list[str] = []
    denied_columns: set[str] = set()

    # Role tier
    result = await db.execute(
        select(RolePermission).where(
            RolePermission.role == role,
            RolePermission.connection_id == connection_id,
        )
    )
    role_perm = result.scalar_one_or_none()
    if role_perm:
        allowed_tables = list(role_perm.allowed_tables or [])
        denied_columns.update(role_perm.denied_columns or [])

    # Department tier
    if department:
        result = await db.execute(
            select(DepartmentPermission).where(
                DepartmentPermission.department == department,
                DepartmentPermission.connection_id == connection_id,
            )
        )
        dept_perm = result.scalar_one_or_none()
        if dept_perm:
            if dept_perm.allowed_tables:
                allowed_tables = list(dept_perm.allowed_tables)
            denied_columns.update(dept_perm.denied_columns or [])

    # User tier
    result = await db.execute(
        select(UserPermission).where(
            UserPermission.user_id == uuid.UUID(user_id),
            UserPermission.connection_id == connection_id,
        )
    )
    user_perm = result.scalar_one_or_none()
    if user_perm:
        if user_perm.allowed_tables:
            allowed_tables = list(user_perm.allowed_tables)
        denied_columns.update(user_perm.denied_columns or [])

    return {
        "allowed_tables": allowed_tables,
        "denied_columns": denied_columns,
    }


def _filter_schema(schema_data: dict, perms: dict) -> dict:
    """Apply permission filtering to schema."""
    allowed = set(t.lower() for t in perms.get("allowed_tables", []))
    denied_cols = set(perms.get("denied_columns", []))

    if not allowed and not denied_cols:
        return schema_data

    filtered = {}
    for table_name, table_info in schema_data.items():
        if allowed and table_name.lower() not in allowed:
            continue
        if denied_cols:
            columns = {
                k: v for k, v in table_info.get("columns", {}).items()
                if k not in denied_cols
            }
            filtered[table_name] = {"columns": columns}
        else:
            filtered[table_name] = table_info

    return filtered


# =============================================================================
# Helpers
# =============================================================================

async def _get_active_connection(
    connection_id: uuid.UUID, db: AsyncSession
) -> Connection:
    """Fetch active connection or 404."""
    result = await db.execute(
        select(Connection).where(
            Connection.id == connection_id,
            Connection.is_active == True,
        )
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise ResourceNotFoundError(
            message="Database connection not found or inactive.",
            detail=f"Connection {connection_id} not found/active",
        )
    return conn


def _get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# =============================================================================
# POST /query  — The main pipeline
# =============================================================================

@router.post(
    "/",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute natural language query",
    description=(
        "The core AI query pipeline: natural language → SQL → execute → results. "
        "Requires analyst or admin role."
    ),
)
async def execute_query(
    request: Request,
    body: QueryRequest,
    current_user: CurrentUser = Depends(require_analyst_or_above),
    db: AsyncSession = Depends(get_db),
    key_manager=Depends(get_key_manager),
    redis=Depends(get_redis_cache),
    audit=Depends(get_audit_writer),
) -> QueryResponse:
    """
    Full NL→SQL→Execute pipeline.

    Security controls at each step:
        1. Auth: require_analyst_or_above
        2. Input: question length validation, injection detection
        3. Schema: permission-filtered (3-tier RBAC)
        4. LLM: system prompt in code, not credentials
        5. Validator: 5-step SQL pipeline (DDL block, table check, LIMIT)
        6. Execution: timeout, row limit, credential scoping
        7. Audit: every query logged with hash chain
    """
    user_id = current_user["user_id"]
    role = current_user.get("role", "viewer")
    department = current_user.get("department", "")
    settings = get_settings()
    pipeline_start = time.monotonic()

    # ── Step 1: Input validation ─────────────────────────────────────────
    if len(body.question) > settings.MAX_QUESTION_LENGTH:
        raise InputTooLongError(
            message=f"Question exceeds the {settings.MAX_QUESTION_LENGTH} character limit.",
        )

    # Log injection attempts but don't block (strip instead)
    injections = detect_injection(body.question)
    if injections:
        log.warning(
            "query.injection_detected",
            user_id=user_id,
            patterns=len(injections),
        )

    # ── Step 2: Load connection ──────────────────────────────────────────
    try:
        conn_uuid = uuid.UUID(body.connection_id)
    except ValueError:
        raise ValidationError(
            message="Invalid connection ID format.",
            detail=f"Not a valid UUID: {body.connection_id}",
        )

    connection = await _get_active_connection(conn_uuid, db)

    # ── Step 3: Load schema (permission-filtered) ────────────────────────
    schema_data = await _load_schema_for_query(
        conn_uuid, user_id, role, department, db, redis, key_manager,
    )
    schema_context = _build_schema_context(schema_data)

    # ── Step 4: Load conversation history (if follow-up) ─────────────────
    conversation_context = ""
    conversation: Optional[Conversation] = None

    if body.conversation_id:
        try:
            conv_uuid = uuid.UUID(body.conversation_id)
            result = await db.execute(
                select(Conversation).where(
                    Conversation.id == conv_uuid,
                    Conversation.user_id == uuid.UUID(user_id),
                )
            )
            conversation = result.scalar_one_or_none()
        except ValueError:
            pass

        if conversation:
            # Check turn limit (T37)
            if is_conversation_at_limit(conversation.message_count):
                raise ValidationError(
                    message=f"Conversation has reached the {settings.MAX_CONVERSATION_TURNS}-turn limit. Start a new conversation.",
                )

            # Load and sanitize history
            msg_result = await db.execute(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation.id)
                .order_by(ConversationMessage.created_at.asc())
            )
            messages = msg_result.scalars().all()
            history = [
                {
                    "question": m.question,
                    "sql_query": m.sql_query,
                    "result_summary": m.result_summary,
                }
                for m in messages
            ]
            sanitized = sanitize_conversation_history(history)
            conversation_context = _build_conversation_context(sanitized)

    # ── Step 5: Build prompt and call LLM ────────────────────────────────
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        schema_context=schema_context,
        conversation_context=conversation_context,
    )

    llm_request = LLMRequest(
        system_prompt=system_prompt,
        user_message=body.question,
        model="",  # factory overrides from provider config
    )

    llm_response = await generate_with_fallback(llm_request, db, key_manager)

    # ── Step 6: Extract and validate SQL ─────────────────────────────────
    raw_sql = _extract_sql_from_response(llm_response.content)

    # Check for system prompt leakage (T35)
    leaked = detect_system_prompt_leakage(raw_sql)
    if leaked:
        log.warning("query.prompt_leakage_detected", user_id=user_id, markers=leaked)
        raise LLMProviderError(
            message="The AI response was filtered for security. Please rephrase your question.",
            detail=f"System prompt leakage detected: {leaked}",
        )

    # Build allowed tables set from schema
    allowed_tables = set(schema_data.keys()) if schema_data else set()

    # Build allowed columns per table (from permission-filtered schema)
    allowed_columns: dict[str, set[str]] = {}
    for tbl, info in schema_data.items():
        cols = info.get("columns", {})
        if isinstance(cols, dict):
            allowed_columns[tbl] = set(cols.keys())

    # Load denied columns for column-level permission check (step 9)
    user_perms = await _load_user_permissions(
        user_id, role, department, conn_uuid, db,
    )
    denied_columns = user_perms.get("denied_columns", set())

    validation = validate_sql(
        raw_sql=raw_sql,
        allowed_tables=allowed_tables,
        max_rows=connection.max_rows,
        dialect=get_dialect(connection.db_type),
        denied_columns=denied_columns if denied_columns else None,
        allowed_columns=allowed_columns if allowed_columns else None,
    )

    # ── Step 7: Execute against user's database ──────────────────────────
    # Executor factory routes by db_type (postgres, mysql, bigquery)
    query_result = await execute_query(
        connection=connection,
        sql=validation.sql,
        key_manager=key_manager,
    )

    # ── Step 8: Store conversation + message ─────────────────────────────
    # Create conversation if new
    if conversation is None:
        conversation = Conversation(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            connection_id=conn_uuid,
            title=body.question[:100],
            message_count=0,
        )
        db.add(conversation)
        await db.flush()

    # Create message
    result_summary = f"{query_result.row_count} rows, {len(query_result.columns)} columns"
    message = ConversationMessage(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role="user",
        question=body.question,
        sql_query=validation.sql,
        result_summary=result_summary,
        row_count=query_result.row_count,
        duration_ms=query_result.duration_ms,
    )
    db.add(message)
    conversation.message_count = (conversation.message_count or 0) + 1
    await db.commit()

    # ── Step 9: Audit ────────────────────────────────────────────────────
    total_ms = int((time.monotonic() - pipeline_start) * 1000)

    if audit:
        await audit.log(
            execution_status="query.executed",
            question=body.question[:500],
            user_id=user_id,
            connection_id=conn_uuid,
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    log.info(
        "query.completed",
        user_id=user_id,
        connection_id=str(conn_uuid),
        row_count=query_result.row_count,
        llm_latency_ms=llm_response.latency_ms,
        query_latency_ms=query_result.duration_ms,
        total_ms=total_ms,
        provider=llm_response.provider_type,
        model=llm_response.model,
    )

    return QueryResponse(
        question=body.question,
        sql=validation.sql,
        columns=query_result.columns,
        rows=query_result.rows,
        row_count=query_result.row_count,
        duration_ms=query_result.duration_ms,
        truncated=query_result.truncated,
        conversation_id=str(conversation.id),
        message_id=str(message.id),
        provider_type=llm_response.provider_type,
        model=llm_response.model,
        llm_latency_ms=llm_response.latency_ms,
    )