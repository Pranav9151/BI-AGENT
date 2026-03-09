"""Smart BI Agent — Token Usage & Key Rotation Models (v3.1)"""
from __future__ import annotations
import uuid
from datetime import date, datetime
from typing import Optional
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, UUIDPrimaryKeyMixin

class LLMTokenUsage(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "llm_token_usage"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    llm_provider_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("llm_providers.id"), nullable=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    query_count: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("user_id", "llm_provider_id", "date", name="uq_token_usage_daily"),)

class KeyRotationRegistry(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "key_rotation_registry"
    key_purpose: Mapped[str] = mapped_column(String(50), nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
