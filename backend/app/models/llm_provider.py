"""
Smart BI Agent — LLM Provider Model
Architecture v3.1 | Section 5 | Threats: T19(residency), T36(token budget), T45(fallback)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LLMProvider(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "llm_providers"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)  # openai, claude, gemini, groq, deepseek, ollama
    encrypted_api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # HKDF-derived, NULL for Ollama
    base_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Ollama only

    # Model configuration
    model_sql: Mapped[str] = mapped_column(String(100), nullable=False)
    model_insight: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model_suggestion: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    max_tokens_sql: Mapped[int] = mapped_column(Integer, default=2048)
    max_tokens_insight: Mapped[int] = mapped_column(Integer, default=1024)
    temperature_sql: Mapped[float] = mapped_column(Float, default=0.1)
    temperature_insight: Mapped[float] = mapped_column(Float, default=0.3)

    # T19: Data residency compliance
    data_residency: Mapped[str] = mapped_column(String(20), default="unknown")  # us, eu, cn, local, unknown

    # T45: Fallback chain priority (1=primary, 2=secondary, 3=tertiary)
    priority: Mapped[int] = mapped_column(Integer, default=99)

    # T36: Daily token budget
    daily_token_budget: Mapped[int] = mapped_column(Integer, default=1000000)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    def __repr__(self) -> str:
        return f"<LLMProvider {self.name} type={self.provider_type} priority={self.priority}>"
