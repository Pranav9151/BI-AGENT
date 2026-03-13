"""
Alembic Environment Configuration
Async migration support with SQLAlchemy model autodiscovery.
"""

import asyncio
import os
import sys
import urllib.parse
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection, URL
from sqlalchemy.ext.asyncio import create_async_engine

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import ALL models so autogenerate can detect them
from app.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _build_engine_url() -> URL:
    """
    Build a SQLAlchemy URL object with the password decoded from raw env/ini.

    We parse the URL string manually with urllib.parse and use URL.create()
    so the password is NEVER percent-encoded when passed to asyncpg.
    This avoids two separate failure modes:
      1. configparser treating '%' as an interpolation character.
      2. asyncpg receiving 'Pass%40123' instead of 'Pass@123'.
    """
    raw = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url", "")
    parsed = urllib.parse.urlparse(raw)

    return URL.create(
        drivername=parsed.scheme,                         # postgresql+asyncpg
        username=urllib.parse.unquote(parsed.username or ""),
        password=urllib.parse.unquote(parsed.password or ""),  # Pass@123 decoded
        host=parsed.hostname or "localhost",
        port=parsed.port or 5432,
        database=(parsed.path or "").lstrip("/"),
    )


_ENGINE_URL = _build_engine_url()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode - generates SQL without a live connection."""
    context.configure(
        url=_ENGINE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = create_async_engine(_ENGINE_URL, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()