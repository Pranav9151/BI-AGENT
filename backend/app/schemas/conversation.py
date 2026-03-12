"""
Smart BI Agent — Conversation Schemas
Architecture v3.1 | Layer 4 | Threats: T37 (prompt manipulation), T52 (IDOR)

Request and response schemas for Conversation management.

Design notes:
  - Conversations are the persistent record of a query session.
    Each conversation holds multiple turns (ConversationMessages).
  - The CRUD layer here manages the conversation shell + metadata.
    Actual message insertion is done by the query pipeline (future C-query).
  - message_count and turn_limit_reached are read-only stats derived from DB.
  - chart_config in MessageResponse is a free-form JSONB blob rendered by
    the frontend chart engine; we pass it through as-is.
  - T37: The 20-turn hard limit is enforced by the query pipeline at execution
    time. These schemas surface the count so the UI can warn the user.
  - T52 (IDOR): Ownership enforcement lives in the route layer, not here.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

# Maximum turns before the query pipeline refuses new messages (T37)
MAX_TURNS = 20


# =============================================================================
# Request Schemas
# =============================================================================

class ConversationCreateRequest(BaseModel):
    """
    POST /api/v1/conversations — body.

    Creates a conversation shell. The query pipeline creates conversations
    automatically when a new question is submitted without a conversation_id,
    so this endpoint is primarily used by clients that want to pre-create
    a named session before the first query.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    connection_id: str = Field(..., description="UUID of the target database connection")
    title: Optional[str] = Field(
        None, min_length=1, max_length=255,
        description="Human-readable conversation title (auto-generated if omitted)",
    )


class ConversationUpdateRequest(BaseModel):
    """
    PATCH /api/v1/conversations/{id} — body.

    Only the title can be changed after creation.
    connection_id is immutable — changing the target DB mid-conversation
    would silently invalidate the stored message history.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    title: Optional[str] = Field(None, min_length=1, max_length=255)


# =============================================================================
# Response Schemas
# =============================================================================

class MessageResponse(BaseModel):
    """Single conversation turn (user question or assistant answer)."""
    model_config = ConfigDict(from_attributes=True)

    message_id: str
    conversation_id: str
    role: str                           # "user" | "assistant"
    question: Optional[str]
    sql_query: Optional[str]
    result_summary: Optional[str]
    row_count: Optional[int]
    duration_ms: Optional[int]
    chart_config: Optional[Any]         # Free-form JSONB; rendered by frontend
    created_at: str                     # ISO-8601


class ConversationResponse(BaseModel):
    """
    Conversation summary — metadata only, no embedded messages.

    Use GET /{id}/messages for the full message list.
    turn_limit_reached indicates the conversation has hit the 20-turn cap (T37).
    """
    model_config = ConfigDict(from_attributes=True)

    conversation_id: str
    user_id: str
    connection_id: str
    title: Optional[str]
    message_count: int
    turn_limit_reached: bool            # True when message_count >= MAX_TURNS
    created_at: str
    updated_at: str


class ConversationListResponse(BaseModel):
    """Paginated list of conversations."""
    conversations: list[ConversationResponse]
    total: int
    skip: int
    limit: int


class ConversationMessageListResponse(BaseModel):
    """Ordered message history for a single conversation."""
    conversation_id: str
    messages: list[MessageResponse]
    total: int
    turn_limit_reached: bool