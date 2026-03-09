"""
Smart BI Agent — Database Layer Tests
Architecture v3.1 | Component 4
"""
import pytest

# Import ALL models once at module level (avoids re-registration issues)
from app.models import (
    Base, User, ApiKey, Connection, LLMProvider,
    NotificationPlatform, PlatformUserMapping,
    RolePermission, DepartmentPermission, UserPermission,
    AuditLog, SavedQuery, Conversation, ConversationMessage,
    Schedule, LLMTokenUsage, KeyRotationRegistry,
)
from app.db.redis_manager import _extract_host, _extract_port
from app.config import get_settings


class TestModelImports:
    @pytest.mark.security
    def test_all_models_import(self):
        assert Base is not None
        assert User is not None
        assert LLMProvider is not None

    @pytest.mark.security
    def test_table_names(self):
        expected = {
            User: "users", ApiKey: "api_keys", Connection: "connections",
            LLMProvider: "llm_providers", NotificationPlatform: "notification_platforms",
            PlatformUserMapping: "platform_user_mappings",
            RolePermission: "role_permissions", DepartmentPermission: "department_permissions",
            UserPermission: "user_permissions", AuditLog: "audit_logs",
            SavedQuery: "saved_queries", Conversation: "conversations",
            ConversationMessage: "conversation_messages", Schedule: "schedules",
            LLMTokenUsage: "llm_token_usage", KeyRotationRegistry: "key_rotation_registry",
        }
        for model, name in expected.items():
            assert model.__tablename__ == name, f"{model.__name__} should be '{name}'"

    @pytest.mark.security
    def test_total_table_count(self):
        tables = Base.metadata.tables
        assert len(tables) == 16, f"Expected 16 tables, got {len(tables)}: {list(tables.keys())}"


class TestUserModel:
    @pytest.mark.security
    def test_totp_fields(self):
        cols = {c.name for c in User.__table__.columns}
        assert "totp_secret_enc" in cols
        assert "totp_enabled" in cols

    @pytest.mark.security
    def test_lockout_fields(self):
        cols = {c.name for c in User.__table__.columns}
        assert "failed_login_attempts" in cols
        assert "locked_until" in cols

    @pytest.mark.security
    def test_approval_field(self):
        cols = {c.name for c in User.__table__.columns}
        assert "is_approved" in cols

    @pytest.mark.security
    def test_default_role_viewer(self):
        assert User.__table__.columns["role"].default.arg == "viewer"


class TestLLMProviderModel:
    @pytest.mark.security
    def test_fallback_priority(self):
        assert "priority" in {c.name for c in LLMProvider.__table__.columns}

    @pytest.mark.security
    def test_data_residency(self):
        assert "data_residency" in {c.name for c in LLMProvider.__table__.columns}

    @pytest.mark.security
    def test_token_budget(self):
        assert "daily_token_budget" in {c.name for c in LLMProvider.__table__.columns}


class TestAuditLogModel:
    @pytest.mark.security
    def test_prev_hash(self):
        assert "prev_hash" in {c.name for c in AuditLog.__table__.columns}

    @pytest.mark.security
    def test_token_tracking(self):
        assert "llm_tokens_used" in {c.name for c in AuditLog.__table__.columns}


class TestSavedQueryModel:
    @pytest.mark.security
    def test_sensitivity(self):
        assert "sensitivity" in {c.name for c in SavedQuery.__table__.columns}


class TestPlatformMappingModel:
    @pytest.mark.security
    def test_verification_fields(self):
        cols = {c.name for c in PlatformUserMapping.__table__.columns}
        assert "is_verified" in cols
        assert "verified_at" in cols
        assert "expires_at" in cols


class TestRedisManager:
    def test_extract_host(self):
        assert _extract_host("redis://myhost:6379") == "myhost"
        assert _extract_host("redis://localhost:6379") == "localhost"
        assert _extract_host("redis://:password@host:6379") == "host"

    def test_extract_port(self):
        assert _extract_port("redis://localhost:6379") == 6379
        assert _extract_port("redis://localhost:6380") == 6380
        assert _extract_port("redis://localhost") == 6379

    def test_three_databases(self):
        settings = get_settings()
        assert settings.REDIS_DB_CACHE == 0
        assert settings.REDIS_DB_SECURITY == 1
        assert settings.REDIS_DB_COORDINATION == 2


class TestConnectionModel:
    @pytest.mark.security
    def test_pool_config(self):
        cols = {c.name for c in Connection.__table__.columns}
        assert "pool_min_size" in cols
        assert "pool_max_size" in cols
