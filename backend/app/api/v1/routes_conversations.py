"""
Smart BI Agent — Conversation Routes  (Component 14)
Architecture v3.1 | Layer 4 (Application) | Threats: T37 (prompt manipulation),
                                                        T52 (IDOR — ownership check)

ENDPOINTS:
    GET    /api/v1/conversations                         — list own conversations
    GET    /api/v1/conversations/{id}                    — get single conversation
    GET    /api/v1/conversations/{id}/messages           — get message history
    POST   /api/v1/conversations                         — create conversation shell
    PATCH  /api/v1/conversations/{id}                    — rename conversation
    DELETE /api/v1/conversations/{id}                    — delete conversation + messages

OWNERSHIP MODEL (T52 — IDOR prevention):
    Same pattern as C13 (SavedQuery).
    Every mutating endpoint checks: record.user_id == current_user OR admin.
    Admin can read/modify/delete any conversation.
    Regular users only see their own conversations (no shared concept for convos).

20-TURN LIMIT (T37 — gradual prompt manipulation):
    The hard enforcement happens in the query pipeline (future component) which
    refuses to add a new message when message_count >= MAX_TURNS.
    This layer surfaces turn_limit_reached in every response so the UI can
    disable the input field and show a "Start new conversation" prompt.
    Admins can delete a maxed-out conversation so users aren't permanently blocked.

MESSAGE HISTORY:
    GET /{id}/messages returns the ordered message log.
    Messages are append-only — no endpoint exists to edit or delete individual
    messages. Deleting the parent conversation cascade-deletes all messages.
    The query pipeline is the only writer to conversation_messages.

AUDIT:
    create, rename, and delete write to AuditWriter.
    Message content is not included in audit log text (can be long/sensitive).
"""
from __future__ import annotations

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
    require_active_user,
)
from app.errors.exceptions import (
    InsufficientPermissionsError,
    ResourceNotFoundError,
    ValidationError,
)
from app.logging.structured import get_logger
from app.models.conversation import Conversation, ConversationMessage
from app.schemas.conversation import (
    MAX_TURNS,
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationMessageListResponse,
    ConversationResponse,
    ConversationUpdateRequest,
    MessageResponse,
)

log = get_logger(__name__)

router = APIRouter()


# =============================================================================
# Helpers
# =============================================================================

def _conv_to_response(conv: Conversation) -> ConversationResponse:
    """Convert a Conversation ORM object to a safe API response."""
    return ConversationResponse(
        conversation_id=str(conv.id),
        user_id=str(conv.user_id),
        connection_id=str(conv.connection_id),
        title=conv.title,
        message_count=conv.message_count,
        turn_limit_reached=conv.message_count >= MAX_TURNS,
        created_at=conv.created_at.isoformat() if conv.created_at else "",
        updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
    )


def _msg_to_response(msg: ConversationMessage) -> MessageResponse:
    """Convert a ConversationMessage ORM object to a response."""
    return MessageResponse(
        message_id=str(msg.id),
        conversation_id=str(msg.conversation_id),
        role=msg.role,
        question=msg.question,
        sql_query=msg.sql_query,
        result_summary=msg.result_summary,
        row_count=msg.row_count,
        duration_ms=msg.duration_ms,
        chart_config=msg.chart_config,
        created_at=msg.created_at.isoformat() if msg.created_at else "",
    )


async def _get_conv_or_404(conv_id: uuid.UUID, db: AsyncSession) -> Conversation:
    """Fetch a Conversation by ID or raise ResourceNotFoundError (404)."""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_id)
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise ResourceNotFoundError(
            message="Conversation not found.",
            detail=f"Conversation {conv_id} does not exist",
        )
    return conv


def _assert_owner_or_admin(conv: Conversation, current_user: CurrentUser) -> None:
    """
    Ownership gate — T52 IDOR prevention.

    Unlike saved queries there is no 'shared' concept for conversations —
    conversations are always private to their owner.
    """
    if str(conv.user_id) != current_user["user_id"] and current_user["role"] != "admin":
        raise InsufficientPermissionsError(
            message="You do not have permission to access this conversation.",
            detail=(
                f"Conversation {conv.id} owned by {conv.user_id}, "
                f"requested by {current_user['user_id']} (role={current_user['role']})"
            ),
        )


def _get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# =============================================================================
# GET /  — List conversations
# =============================================================================

@router.get(
    "/",
    response_model=ConversationListResponse,
    summary="List conversations",
    description=(
        "Returns the calling user's conversations, most recent first. "
        "Admins may additionally filter by user_id to see another user's conversations."
    ),
)
async def list_conversations(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    connection_id: Optional[str] = Query(None, description="Filter by connection UUID"),
    user_id: Optional[str] = Query(
        None,
        description="Admin-only: filter by a specific user's UUID",
    ),
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationListResponse:
    """
    Admins can pass user_id to view another user's conversations.
    Non-admins are always scoped to their own user_id regardless of the param.
    """
    is_admin = current_user["role"] == "admin"

    # Determine the effective owner filter
    if user_id and is_admin:
        try:
            owner_uuid = uuid.UUID(user_id)
        except ValueError:
            raise ValidationError(
                message="Invalid user_id format.",
                detail=f"user_id={user_id!r} is not a valid UUID",
            )
    else:
        # Non-admins always see only their own; admins default to own too
        owner_uuid = uuid.UUID(current_user["user_id"])

    conditions = [Conversation.user_id == owner_uuid]

    if connection_id:
        try:
            conditions.append(Conversation.connection_id == uuid.UUID(connection_id))
        except ValueError:
            raise ValidationError(
                message="Invalid connection_id format.",
                detail=f"connection_id={connection_id!r} is not a valid UUID",
            )

    count_stmt = select(func.count()).select_from(Conversation).where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    data_stmt = (
        select(Conversation)
        .where(*conditions)
        .order_by(Conversation.updated_at.desc())
        .offset(skip)
        .limit(limit)
    )
    convs = (await db.execute(data_stmt)).scalars().all()

    log.info(
        "conversations.list",
        user_id=current_user["user_id"],
        owner_uuid=str(owner_uuid),
        total=total,
    )

    return ConversationListResponse(
        conversations=[_conv_to_response(c) for c in convs],
        total=total,
        skip=skip,
        limit=limit,
    )


# =============================================================================
# GET /{conversation_id}  — Get single conversation
# =============================================================================

@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Get conversation",
    description="Retrieve a single conversation summary. Owner or admin only.",
)
async def get_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    conv = await _get_conv_or_404(conversation_id, db)
    _assert_owner_or_admin(conv, current_user)

    log.info(
        "conversations.get",
        user_id=current_user["user_id"],
        conversation_id=str(conversation_id),
    )
    return _conv_to_response(conv)


# =============================================================================
# GET /{conversation_id}/messages  — Get message history
# =============================================================================

@router.get(
    "/{conversation_id}/messages",
    response_model=ConversationMessageListResponse,
    summary="Get conversation messages",
    description=(
        "Retrieve the ordered message history for a conversation. "
        "Owner or admin only. Messages are returned oldest-first."
    ),
)
async def get_conversation_messages(
    conversation_id: uuid.UUID,
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationMessageListResponse:
    """
    Returns messages oldest-first so clients can render the chat thread
    in chronological order without reversing.

    turn_limit_reached is included so the UI knows whether to disable
    the input field without a separate GET / call.
    """
    conv = await _get_conv_or_404(conversation_id, db)
    _assert_owner_or_admin(conv, current_user)

    count_stmt = (
        select(func.count())
        .select_from(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    msgs_stmt = (
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    msgs = (await db.execute(msgs_stmt)).scalars().all()

    log.info(
        "conversations.messages.listed",
        user_id=current_user["user_id"],
        conversation_id=str(conversation_id),
        total=total,
    )

    return ConversationMessageListResponse(
        conversation_id=str(conversation_id),
        messages=[_msg_to_response(m) for m in msgs],
        total=total,
        turn_limit_reached=conv.message_count >= MAX_TURNS,
    )


# =============================================================================
# POST /  — Create conversation shell
# =============================================================================

@router.post(
    "/",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create conversation",
    description=(
        "Pre-create a named conversation shell before the first query. "
        "The query pipeline also creates conversations automatically. "
        "The new conversation is owned by the calling user."
    ),
)
async def create_conversation(
    request: Request,
    body: ConversationCreateRequest,
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> ConversationResponse:
    """Create an empty conversation owned by the calling user."""
    try:
        conn_uuid = uuid.UUID(body.connection_id)
    except ValueError:
        raise ValidationError(
            message="Invalid connection_id format.",
            detail=f"connection_id={body.connection_id!r} is not a valid UUID",
        )

    now = datetime.now(timezone.utc)
    conv = Conversation(
        id=uuid.uuid4(),
        user_id=uuid.UUID(current_user["user_id"]),
        connection_id=conn_uuid,
        title=body.title,
        message_count=0,
    )
    conv.created_at = now
    conv.updated_at = now

    db.add(conv)
    await db.commit()

    log.info(
        "conversations.created",
        user_id=current_user["user_id"],
        conversation_id=str(conv.id),
        title=conv.title,
    )

    if audit:
        await audit.log(
            execution_status="conversation.created",
            question=f"User created conversation: {body.title or '(untitled)'!r}",
            user_id=current_user["user_id"],
            connection_id=conn_uuid,
            conversation_id=conv.id,
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _conv_to_response(conv)


# =============================================================================
# PATCH /{conversation_id}  — Rename conversation
# =============================================================================

@router.patch(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Rename conversation",
    description="Update the conversation title. Owner or admin only.",
)
async def update_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    body: ConversationUpdateRequest,
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> ConversationResponse:
    """Rename a conversation — owner or admin only (T52)."""
    conv = await _get_conv_or_404(conversation_id, db)
    _assert_owner_or_admin(conv, current_user)

    changed_fields: list[str] = []

    if body.title is not None:
        conv.title = body.title
        changed_fields.append("title")

    conv.updated_at = datetime.now(timezone.utc)
    await db.commit()

    log.info(
        "conversations.updated",
        user_id=current_user["user_id"],
        conversation_id=str(conversation_id),
        changed_fields=changed_fields,
    )

    if audit and changed_fields:
        await audit.log(
            execution_status="conversation.updated",
            question=(
                f"Conversation ({conversation_id}) renamed to "
                f"{conv.title!r}"
            ),
            user_id=current_user["user_id"],
            connection_id=conv.connection_id,
            conversation_id=conversation_id,
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return _conv_to_response(conv)


# =============================================================================
# DELETE /{conversation_id}  — Delete conversation
# =============================================================================

@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete conversation",
    description=(
        "Permanently delete a conversation and all its messages. "
        "Owner or admin only. This action is irreversible."
    ),
)
async def delete_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
    audit=Depends(get_audit_writer),
) -> Response:
    """
    Hard delete — cascade='all, delete-orphan' on the messages relationship
    means SQLAlchemy will delete all ConversationMessages automatically.
    """
    conv = await _get_conv_or_404(conversation_id, db)
    _assert_owner_or_admin(conv, current_user)

    title_snapshot = conv.title
    conn_snapshot = conv.connection_id
    count_snapshot = conv.message_count

    await db.delete(conv)
    await db.commit()

    log.info(
        "conversations.deleted",
        user_id=current_user["user_id"],
        conversation_id=str(conversation_id),
        title=title_snapshot,
        message_count=count_snapshot,
    )

    if audit:
        await audit.log(
            execution_status="conversation.deleted",
            question=(
                f"Deleted conversation {title_snapshot or '(untitled)'!r} "
                f"({conversation_id}, {count_snapshot} messages)"
            ),
            user_id=current_user["user_id"],
            connection_id=conn_snapshot,
            conversation_id=conversation_id,
            ip_address=_get_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)