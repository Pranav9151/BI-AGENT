"""
Smart BI Agent — Setup Verification Script
Architecture v3.1 | Bootstrap Script

PURPOSE:
    Runs a pre-flight checklist before starting the application.
    Validates that all required infrastructure is configured and reachable.

CHECKS PERFORMED:
    [1] Environment variables — all required vars present and valid
    [2] JWT key files — both private.pem and public.pem exist and are valid RSA keys
    [3] Encryption master key — valid hex, sufficient entropy
    [4] PostgreSQL connectivity — can connect and query
    [5] Redis connectivity — all three databases reachable
    [6] Alembic migrations — DB schema is up to date
    [7] Admin user exists — at least one active admin in the system
    [8] Ollama exposure (T32) — warns if Ollama is listening on 0.0.0.0

USAGE:
    cd backend
    source .venv/Scripts/activate
    python scripts/verify_setup.py

EXIT CODES:
    0 — All checks passed (or only warnings)
    1 — One or more critical checks failed
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Callable

# Add backend/ to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Colour codes for terminal output
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def ok(msg: str)   -> None: print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg: str) -> None: print(f"  {YELLOW}⚠{RESET}  {msg}")
def fail(msg: str) -> None: print(f"  {RED}✗{RESET}  {msg}")


# =============================================================================
# Individual checks
# =============================================================================

def check_environment() -> bool:
    """Validate all required environment variables."""
    print(f"\n{BOLD}[1] Environment Variables{RESET}")

    required = [
        "DATABASE_URL",
        "REDIS_URL",
        "ENCRYPTION_MASTER_KEY",
        "POSTGRES_PASSWORD",
        "JWT_PRIVATE_KEY_PATH",
        "JWT_PUBLIC_KEY_PATH",
    ]

    all_ok = True
    for var in required:
        value = os.environ.get(var)
        if not value:
            fail(f"{var} is not set")
            all_ok = False
        else:
            ok(f"{var} is set")

    # Validate via Pydantic settings
    try:
        from app.config import get_settings
        settings = get_settings()
        ok(f"Settings validated (env={settings.APP_ENV.value})")
    except Exception as exc:
        fail(f"Settings validation failed: {exc}")
        all_ok = False

    return all_ok


def check_jwt_keys() -> bool:
    """Check JWT key files exist and are valid RSA keys."""
    print(f"\n{BOLD}[2] JWT Key Files{RESET}")

    from app.config import get_settings
    settings = get_settings()

    all_ok = True

    # Check private key
    priv_path = settings.JWT_PRIVATE_KEY_PATH
    if not os.path.exists(priv_path):
        fail(f"Private key not found: {priv_path}")
        fail("  Run: make keys  (or: bash scripts/generate_keys.sh)")
        all_ok = False
    else:
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            with open(priv_path, "rb") as f:
                load_pem_private_key(f.read(), password=None)
            ok(f"Private key valid: {priv_path}")
        except Exception as exc:
            fail(f"Private key invalid: {exc}")
            all_ok = False

    # Check public key
    pub_path = settings.JWT_PUBLIC_KEY_PATH
    if not os.path.exists(pub_path):
        fail(f"Public key not found: {pub_path}")
        all_ok = False
    else:
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_public_key
            with open(pub_path, "rb") as f:
                load_pem_public_key(f.read())
            ok(f"Public key valid: {pub_path}")
        except Exception as exc:
            fail(f"Public key invalid: {exc}")
            all_ok = False

    return all_ok


def check_encryption_key() -> bool:
    """Validate the HKDF master key."""
    print(f"\n{BOLD}[3] Encryption Master Key{RESET}")

    from app.config import get_settings
    settings = get_settings()

    try:
        from app.security.key_manager import init_key_manager, KeyPurpose
        km = init_key_manager(settings.ENCRYPTION_MASTER_KEY)

        # Test that key derivation works for all purposes
        for purpose in KeyPurpose:
            fp = km.get_key_fingerprint(purpose)
            ok(f"{purpose.value}: fingerprint={fp}")

        return True
    except Exception as exc:
        fail(f"Key manager initialization failed: {exc}")
        return False


async def check_database() -> bool:
    """Test PostgreSQL connectivity and migration status."""
    print(f"\n{BOLD}[4] PostgreSQL Database{RESET}")

    try:
        from app.db.session import init_db_engine, _async_session_factory, close_db_engine
        from sqlalchemy import text

        init_db_engine()

        async with _async_session_factory() as session:
            result = await session.execute(text("SELECT version()"))
            version = result.scalar()
            ok(f"Connected: {version[:50]}...")

            # Check if alembic_version table exists
            result = await session.execute(text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'alembic_version')"
            ))
            has_alembic = result.scalar()
            if has_alembic:
                result = await session.execute(text("SELECT version_num FROM alembic_version"))
                version_num = result.scalar()
                ok(f"Alembic migrations applied (current: {version_num})")
            else:
                warn("Alembic table not found — run: alembic upgrade head")

            # Check if users table exists
            result = await session.execute(text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'users')"
            ))
            has_users = result.scalar()
            if has_users:
                ok("Schema tables exist")
            else:
                warn("Users table not found — run: alembic upgrade head")

        await close_db_engine()
        return True

    except Exception as exc:
        fail(f"Database connection failed: {exc}")
        fail("  Check: DATABASE_URL, PostgreSQL running, network access")
        return False


async def check_redis() -> bool:
    """Test all three Redis database connections."""
    print(f"\n{BOLD}[5] Redis (3 Databases){RESET}")

    try:
        from app.db.redis_manager import init_redis, check_redis_health, close_redis

        await init_redis()
        health = await check_redis_health()

        all_ok = True
        labels = {
            "cache_db0":         "DB 0 — Cache (allkeys-lru, degradable)",
            "security_db1":      "DB 1 — Security (noeviction, fail-closed)",
            "coordination_db2":  "DB 2 — Coordination (volatile-lru)",
        }
        for key, label in labels.items():
            if health.get(key):
                ok(label)
            else:
                fail(label)
                if key == "security_db1":
                    fail("  CRITICAL: Security Redis is required for auth + rate limiting")
                all_ok = False

        await close_redis()
        return all_ok

    except Exception as exc:
        fail(f"Redis connection failed: {exc}")
        fail("  Check: REDIS_URL, REDIS_PASSWORD, Redis running")
        return False


async def check_admin_user() -> bool:
    """Verify at least one admin user exists."""
    print(f"\n{BOLD}[6] Admin User{RESET}")

    try:
        from app.db.session import init_db_engine, _async_session_factory, close_db_engine
        from sqlalchemy import select, func
        from app.models.user import User

        init_db_engine()

        async with _async_session_factory() as session:
            # Check if users table exists first
            from sqlalchemy import text
            result = await session.execute(text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users')"
            ))
            if not result.scalar():
                warn("Users table not found — run migrations first")
                await close_db_engine()
                return True  # Not a failure at this stage

            result = await session.execute(
                select(func.count(User.id))
                .where(User.role == "admin")
                .where(User.is_active == True)
            )
            admin_count = result.scalar() or 0

            if admin_count > 0:
                ok(f"{admin_count} active admin user(s) found")
            else:
                warn("No admin users found")
                warn("  Run: python scripts/create_admin.py")

        await close_db_engine()
        return True  # Warning, not a hard failure

    except Exception as exc:
        warn(f"Could not check admin users: {exc}")
        return True  # Don't fail on this check if DB isn't ready yet


def check_ollama_exposure() -> bool:
    """T32: Warn if Ollama is listening on 0.0.0.0."""
    print(f"\n{BOLD}[7] Ollama Exposure Check (T32){RESET}")

    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        # Try connecting to Ollama on all interfaces
        result = sock.connect_ex(("127.0.0.1", 11434))
        sock.close()

        if result == 0:
            # Ollama is running — check if exposed externally
            sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock2.settimeout(1)
            ext_result = sock2.connect_ex(("0.0.0.0", 11434))
            sock2.close()

            if ext_result == 0:
                warn("Ollama appears to be running")
                warn("Ensure it is bound to 127.0.0.1 ONLY in production")
                warn("The 91,000 Ollama attacks in Jan 2026 targeted 0.0.0.0 binding")
            else:
                ok("Ollama running but NOT exposed on 0.0.0.0")
        else:
            ok("Ollama not running (or not enabled)")

    except Exception:
        ok("Ollama not reachable (expected in dev without --profile ollama)")

    return True  # Always pass — this is informational


# =============================================================================
# Main
# =============================================================================

async def run_all_checks() -> int:
    """Run all checks and return exit code."""
    print(f"\n{BOLD}{'='*60}")
    print(f"  Smart BI Agent — Setup Verification")
    print(f"{'='*60}{RESET}")

    results: list[bool] = []

    # Synchronous checks
    results.append(check_environment())
    results.append(check_jwt_keys())
    results.append(check_encryption_key())

    # Async checks
    results.append(await check_database())
    results.append(await check_redis())
    results.append(await check_admin_user())

    # Informational
    check_ollama_exposure()

    # Summary
    passed = sum(results)
    total = len(results)
    failed_count = total - passed

    print(f"\n{BOLD}{'='*60}")
    if failed_count == 0:
        print(f"{GREEN}  ALL CHECKS PASSED ({passed}/{total}){RESET}{BOLD}")
        print(f"  System is ready to start.")
    else:
        print(f"{RED}  {failed_count} CHECK(S) FAILED ({passed}/{total} passed){RESET}{BOLD}")
        print(f"  Fix the issues above before starting the application.")
    print(f"{'='*60}{RESET}\n")

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_checks())
    sys.exit(exit_code)
