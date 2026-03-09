"""
Smart BI Agent — Audit Log Model
Architecture v3.1 | Section 5 | Threat: T20 (tamper-evidence)
Append-only, hash-chained: each entry's prev_hash = SHA256(previous entry)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class AuditLog(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "audit_logs"

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    connection_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    llm_provider_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    notification_platform_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    question: Mapped[str] = mapped_column(Text, nullable=False)  # GDPR: redactable
    generated_sql: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    execution_status: Mapped[str] = mapped_column(String(50), nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    row_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    result_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    llm_provider_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    llm_model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    llm_tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    # T20: Hash chain — SHA256 of previous entry for tamper evidence
    prev_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_audit_user", "user_id"),
        Index("idx_audit_created", "created_at"),
        Index("idx_audit_status", "execution_status"),
        {"comment": "Append-only: NO UPDATE/DELETE privileges for app user"},
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.execution_status} user={self.user_id}>"
