"""
Smart BI Agent — Application Configuration
Architecture v3.1 | All environment variables typed and validated.

RULE: .env contains ONLY infrastructure credentials.
      All other secrets (LLM keys, DB creds, notif tokens) are encrypted
      in the app database using HKDF-derived keys (see security/key_manager.py).
"""

from __future__ import annotations

import json
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(str, Enum):
    """Application environment modes."""
    PRODUCTION = "production"
    DEVELOPMENT = "development"
    TESTING = "testing"


class Settings(BaseSettings):
    """
    Central configuration — loads from .env file and environment variables.
    Every field is typed, validated, and has security-appropriate defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================================================================
    # Application
    # =========================================================================
    APP_ENV: AppEnvironment = AppEnvironment.PRODUCTION
    APP_NAME: str = "Smart BI Agent"
    APP_VERSION: str = "3.1.0"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_WORKERS: int = 4
    LOG_LEVEL: str = "info"

    # CORS — NEVER ["*"] (v3.1 Layer 3)
    FRONTEND_URL: str = "https://localhost"
    CORS_ORIGINS: list[str] = Field(default=["https://localhost"])

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors_no_wildcard(cls, v: list[str]) -> list[str]:
        if "*" in v:
            raise ValueError("CORS_ORIGINS must never contain '*' — security violation")
        return v

    # =========================================================================
    # PostgreSQL — App Database
    # =========================================================================
    POSTGRES_USER: str = "sbi_admin"
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str = "smart_bi_agent"
    DATABASE_URL: str

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
        return v

    # =========================================================================
    # Redis (Segmented — 3 Databases per v3.1 Section 6)
    # =========================================================================
    REDIS_URL: str = "redis://redis:6379"
    REDIS_PASSWORD: str = ""

    # Redis database numbers (hardcoded per architecture)
    REDIS_DB_CACHE: int = 0          # DB 0: Cache (allkeys-lru, degradable)
    REDIS_DB_SECURITY: int = 1       # DB 1: Security (noeviction, FAIL-CLOSED)
    REDIS_DB_COORDINATION: int = 2   # DB 2: Coordination (volatile-lru)

    # =========================================================================
    # Encryption — HKDF Master Key (T1, T2)
    # =========================================================================
    ENCRYPTION_MASTER_KEY: str

    @field_validator("ENCRYPTION_MASTER_KEY")
    @classmethod
    def validate_master_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError(
                "ENCRYPTION_MASTER_KEY must be at least 32 characters (64 hex chars recommended)"
            )
        return v

    # =========================================================================
    # JWT — RS256 (T4: Algorithm hardcoded, never HS256, never "none")
    # =========================================================================
    JWT_PRIVATE_KEY_PATH: str = "/app/keys/private.pem"
    JWT_PUBLIC_KEY_PATH: str = "/app/keys/public.pem"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_ISSUER: str = "smart-bi-agent"
    JWT_AUDIENCE: str = "smart-bi-agent"
    # HARDCODED — never configurable (T4 mitigation)
    JWT_ALGORITHM: str = "RS256"

    @field_validator("JWT_ALGORITHM")
    @classmethod
    def enforce_rs256(cls, v: str) -> str:
        if v != "RS256":
            raise ValueError("JWT_ALGORITHM must be RS256 — algorithm confusion attack prevention (T4)")
        return v

    @property
    def jwt_private_key(self) -> str:
        """Load private key from file at runtime."""
        path = Path(self.JWT_PRIVATE_KEY_PATH)
        if not path.exists():
            raise FileNotFoundError(
                f"JWT private key not found at {path}. Run: make keys"
            )
        return path.read_text().strip()

    @property
    def jwt_public_key(self) -> str:
        """Load public key from file at runtime."""
        path = Path(self.JWT_PUBLIC_KEY_PATH)
        if not path.exists():
            raise FileNotFoundError(
                f"JWT public key not found at {path}. Run: make keys"
            )
        return path.read_text().strip()

    # =========================================================================
    # Security Settings
    # =========================================================================
    # Account lockout (T10)
    LOCKOUT_THRESHOLD: int = 10
    LOCKOUT_DURATION_MINUTES: int = 30
    PROGRESSIVE_DELAY_FACTOR: int = 2

    # Registration (T53)
    REGISTRATION_OPEN: bool = False  # Closed by default

    # WebSocket (T26, T39, T55)
    WS_MAX_CONNECTIONS_PER_USER: int = 3
    WS_AUTH_TIMEOUT_SECONDS: int = 30
    WS_MAX_MESSAGE_SIZE_BYTES: int = 65536  # 64KB
    WS_PING_INTERVAL_SECONDS: int = 15

    # Rate Limits — differentiated per v3.1 Layer 3
    RATE_LIMIT_LLM_PER_MINUTE: int = 10
    RATE_LIMIT_SCHEMA_PER_MINUTE: int = 60
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10
    RATE_LIMIT_EXPORT_PER_MINUTE: int = 5
    RATE_LIMIT_DEFAULT_PER_MINUTE: int = 100

    # Session
    ADMIN_SESSION_TIMEOUT_MINUTES: int = 15

    # Query limits (T6)
    MAX_QUESTION_LENGTH: int = 2000
    MAX_ROWS: int = 10000
    MAX_RESULT_BYTES: int = 52_428_800  # 50MB
    QUERY_TIMEOUT_SECONDS: int = 30

    # Conversation limits (T37)
    MAX_CONVERSATION_TURNS: int = 20
    MAX_CONVERSATION_TURN_CHARS: int = 500

    # Token budget (T36)
    DEFAULT_DAILY_TOKEN_BUDGET_USER: int = 500_000
    DEFAULT_DAILY_TOKEN_BUDGET_TENANT: int = 1_000_000
    TOKEN_BUDGET_ALERT_THRESHOLD: float = 0.8

    # Data residency (T19)
    ALLOWED_DATA_RESIDENCIES: list[str] = Field(default=["us", "eu", "local"])

    @field_validator("ALLOWED_DATA_RESIDENCIES", mode="before")
    @classmethod
    def parse_residencies(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                return [s.strip() for s in v.split(",") if s.strip()]
        return v

    # =========================================================================
    # Nginx
    # =========================================================================
    NGINX_HTTP_PORT: int = 80
    NGINX_HTTPS_PORT: int = 443

    # =========================================================================
    # Ollama (T32, T33, T34)
    # =========================================================================
    OLLAMA_BASE_URL: str = "http://ollama:11434"  # Docker internal ONLY
    OLLAMA_ENABLED: bool = False
    ALLOW_PRIVATE_DB_CONNECTIONS: bool = False

    # =========================================================================
    # Email / SMTP
    # =========================================================================
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_TLS: bool = True

    # =========================================================================
    # Initial Admin
    # =========================================================================
    ADMIN_EMAIL: str = ""
    ADMIN_NAME: str = "System Admin"
    ADMIN_PASSWORD: str = ""

    # =========================================================================
    # Computed Properties
    # =========================================================================

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == AppEnvironment.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == AppEnvironment.DEVELOPMENT

    @property
    def is_testing(self) -> bool:
        return self.APP_ENV == AppEnvironment.TESTING

    @property
    def swagger_enabled(self) -> bool:
        """Swagger/OpenAPI enabled in development only (T54)."""
        return self.is_development

    @property
    def redis_cache_url(self) -> str:
        """Redis DB 0 — Cache (degradable)."""
        base = self.REDIS_URL.rstrip("/")
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        # Replace redis:// with auth version
        if auth and "://" in base:
            scheme, rest = base.split("://", 1)
            return f"{scheme}://{auth}{rest}/{self.REDIS_DB_CACHE}"
        return f"{base}/{self.REDIS_DB_CACHE}"

    @property
    def redis_security_url(self) -> str:
        """Redis DB 1 — Security (fail-closed, noeviction)."""
        base = self.REDIS_URL.rstrip("/")
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        if auth and "://" in base:
            scheme, rest = base.split("://", 1)
            return f"{scheme}://{auth}{rest}/{self.REDIS_DB_SECURITY}"
        return f"{base}/{self.REDIS_DB_SECURITY}"

    @property
    def redis_coordination_url(self) -> str:
        """Redis DB 2 — Coordination."""
        base = self.REDIS_URL.rstrip("/")
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        if auth and "://" in base:
            scheme, rest = base.split("://", 1)
            return f"{scheme}://{auth}{rest}/{self.REDIS_DB_COORDINATION}"
        return f"{base}/{self.REDIS_DB_COORDINATION}"

    # =========================================================================
    # Validation
    # =========================================================================

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        """Enforce strict settings in production."""
        if self.is_production:
            if self.REGISTRATION_OPEN:
                raise ValueError(
                    "REGISTRATION_OPEN must be false in production (T53)"
                )
            if self.LOG_LEVEL == "debug":
                raise ValueError(
                    "LOG_LEVEL=debug not allowed in production (verbose logs may leak data)"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """
    Cached singleton — call this everywhere.
    Uses lru_cache so .env is read once.
    """
    return Settings()
