"""Smart BI Agent — Settings & Dashboard Models (Phase 8)

Settings: Platform-wide key-value store (branding, etc.)
Dashboard: User-created dashboard layouts for Studio
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PlatformSetting(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Key-value settings for the platform (branding, defaults, etc.)."""
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )


class Dashboard(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """User-created dashboard layout for Studio."""
    __tablename__ = "dashboards"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    is_default: Mapped[bool] = mapped_column(default=False)

    user = relationship("User")
