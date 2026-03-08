"""
Smart BI Agent — Test Configuration
Sets required environment variables before any test imports Settings.
"""

import os

import pytest


def pytest_configure(config):
    """Set environment variables for test Settings BEFORE any imports."""
    os.environ.setdefault("APP_ENV", "testing")
    os.environ.setdefault("POSTGRES_USER", "test_user")
    os.environ.setdefault("POSTGRES_PASSWORD", "test_password_123")
    os.environ.setdefault("POSTGRES_DB", "test_db")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
    os.environ.setdefault("REDIS_PASSWORD", "test_redis_pass")
    os.environ.setdefault("ENCRYPTION_MASTER_KEY", "ab" * 32)  # 64 hex chars
    os.environ.setdefault("JWT_PRIVATE_KEY_PATH", "/tmp/test_private.pem")
    os.environ.setdefault("JWT_PUBLIC_KEY_PATH", "/tmp/test_public.pem")
    os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")
    os.environ.setdefault("CORS_ORIGINS", '["http://localhost:3000"]')
    os.environ.setdefault("REGISTRATION_OPEN", "true")  # Allow in testing

    # Clear the lru_cache on Settings so it picks up test env vars
    from app.config import get_settings
    get_settings.cache_clear()