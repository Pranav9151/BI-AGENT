"""Smart BI Agent — Connection Model (v3.1)"""
from __future__ import annotations
import uuid
from typing import Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

class Connection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "connections"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    db_type: Mapped[str] = mapped_column(String(50), nullable=False)
    host: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    database_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    encrypted_credentials: Mapped[str] = mapped_column(Text, nullable=False)
    ssl_mode: Mapped[str] = mapped_column(String(50), default="require")
    query_timeout: Mapped[int] = mapped_column(Integer, default=30)
    max_rows: Mapped[int] = mapped_column(Integer, default=10000)
    max_result_bytes: Mapped[int] = mapped_column(Integer, default=52428800)
    allowed_schemas: Mapped[Optional[list]] = mapped_column(ARRAY(Text), default=["public"])
    pool_min_size: Mapped[int] = mapped_column(Integer, default=1)
    pool_max_size: Mapped[int] = mapped_column(Integer, default=5)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"), nullable=True)
