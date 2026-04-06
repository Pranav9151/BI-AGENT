"""
Smart BI Agent — Test Configuration
Sets required environment variables AND generates RSA test keys BEFORE any
test module is imported. This runs in pytest_configure — the earliest possible
hook, before fixtures, before collection, before any Settings object is built.

Windows note: /tmp does not exist on Windows. We use tempfile.gettempdir()
which returns the correct platform temp directory (e.g. C:\\Users\\...\\AppData\\Local\\Temp).
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def _generate_rsa_keys() -> tuple:
    """
    Generate an RSA-2048 key pair, write to the platform temp directory,
    and return (private_key_path, public_key_path).

    Uses tempfile.gettempdir() — works on Windows, Linux, and macOS.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    tmp = tempfile.gettempdir()  # C:\Users\...\AppData\Local\Temp on Windows
    private_path = os.path.join(tmp, "sbi_test_private.pem")
    public_path = os.path.join(tmp, "sbi_test_public.pem")

    with open(private_path, "wb") as f:
        f.write(private_pem)
    with open(public_path, "wb") as f:
        f.write(public_pem)

    return private_path, public_path


def pytest_configure(config):
    """
    Set environment variables for test Settings BEFORE any imports.

    RSA keys are generated here (not in a fixture) because pytest_configure
    runs before collection — meaning before any test module is imported and
    before any Settings object is constructed via get_settings(). This
    guarantees Settings.jwt_private_key finds a real file on disk.
    """
    # Generate RSA key pair first — paths must be set before Settings loads
    private_key_path, public_key_path = _generate_rsa_keys()

    os.environ.setdefault("APP_ENV", "testing")
    os.environ.setdefault("POSTGRES_USER", "test_user")
    os.environ.setdefault("POSTGRES_PASSWORD", "test_password_123")
    os.environ.setdefault("POSTGRES_DB", "test_db")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
    os.environ.setdefault("REDIS_PASSWORD", "test_redis_pass")
    os.environ.setdefault("ENCRYPTION_MASTER_KEY", "ab" * 32)  # 64 hex chars
    # Use freshly generated key paths (force-set, don't use setdefault)
    os.environ["JWT_PRIVATE_KEY_PATH"] = private_key_path
    os.environ["JWT_PUBLIC_KEY_PATH"] = public_key_path
    os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")
    os.environ.setdefault("CORS_ORIGINS", '["http://localhost:3000"]')
    os.environ.setdefault("REGISTRATION_OPEN", "true")  # Allow in testing
    os.environ["ALLOW_PRIVATE_DB_CONNECTIONS"] = "false"

    # Clear the lru_cache on Settings so it picks up the new env vars
    from app.config import get_settings
    get_settings.cache_clear()
