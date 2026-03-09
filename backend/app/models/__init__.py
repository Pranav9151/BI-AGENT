"""
Smart BI Agent — Model Registry
All models imported here so Alembic autogenerate discovers them.
"""

from app.models.base import Base
from app.models.user import User, ApiKey
from app.models.connection import Connection
from app.models.llm_provider import LLMProvider
from app.models.notification_platform import NotificationPlatform, PlatformUserMapping
from app.models.permission import RolePermission, DepartmentPermission, UserPermission
from app.models.audit_log import AuditLog
from app.models.saved_query import SavedQuery
from app.models.conversation import Conversation, ConversationMessage
from app.models.schedule import Schedule
from app.models.token_usage import LLMTokenUsage, KeyRotationRegistry

__all__ = [
    "Base",
    "User", "ApiKey",
    "Connection",
    "LLMProvider",
    "NotificationPlatform", "PlatformUserMapping",
    "RolePermission", "DepartmentPermission", "UserPermission",
    "AuditLog",
    "SavedQuery",
    "Conversation", "ConversationMessage",
    "Schedule",
    "LLMTokenUsage", "KeyRotationRegistry",
]
