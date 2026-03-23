"""Smart BI Agent — Permission Models (3-tier RBAC) (v3.1)"""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, UUIDPrimaryKeyMixin

class RolePermission(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "role_permissions"
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connections.id", ondelete="CASCADE"), nullable=False)
    allowed_tables: Mapped[list] = mapped_column(ARRAY(Text), default=[])
    denied_columns: Mapped[list] = mapped_column(ARRAY(Text), default=[])
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class DepartmentPermission(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "department_permissions"
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connections.id", ondelete="CASCADE"), nullable=False)
    allowed_tables: Mapped[list] = mapped_column(ARRAY(Text), default=[])
    denied_columns: Mapped[list] = mapped_column(ARRAY(Text), default=[])
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class UserPermission(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "user_permissions"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connections.id", ondelete="CASCADE"), nullable=False)
    allowed_tables: Mapped[list] = mapped_column(ARRAY(Text), default=[])
    denied_tables: Mapped[list] = mapped_column(ARRAY(Text), default=[])
    denied_columns: Mapped[list] = mapped_column(ARRAY(Text), default=[])
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
