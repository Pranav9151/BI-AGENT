"""Smart BI Agent — Notification Platform Models (v3.1)"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

class NotificationPlatform(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notification_platforms"
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    platform_type: Mapped[str] = mapped_column(String(50), nullable=False)
    encrypted_config: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_inbound_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_outbound_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"), nullable=True)
    user_mappings = relationship("PlatformUserMapping", back_populates="platform", cascade="all, delete-orphan")

class PlatformUserMapping(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "platform_user_mappings"
    platform_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("notification_platforms.id", ondelete="CASCADE"), nullable=False)
    platform_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    internal_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("platform_id", "platform_user_id", name="uq_platform_user"),)
    platform = relationship("NotificationPlatform", back_populates="user_mappings")
