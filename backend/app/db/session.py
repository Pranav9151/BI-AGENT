"""
Smart BI Agent — Database Session Factory
Architecture v3.1 | Layer 7: Data Layer
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

# Engine and session factory — initialized at startup
_engine = None
_async_session_factory = None


def init_db_engine() -> None:
    """Initialize the async database engine. Called once during app lifespan."""
    global _engine, _async_session_factory

    settings = get_settings()

    _engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.is_development,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
        pool_pre_ping=True,
    )

    _async_session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def close_db_engine() -> None:
    """Close the database engine. Called during app shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency — yields an async database session.

    Usage:
        @router.get("/users")
        async def list_users(db: AsyncSession = Depends(get_db)):
            ...
    """
    if _async_session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db_engine() first.")

    async with _async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_engine():
    """Get the raw engine (for Alembic migrations)."""
    if _engine is None:
        raise RuntimeError("Database not initialized.")
    return _engine
