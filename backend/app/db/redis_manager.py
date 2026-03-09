"""
Smart BI Agent — Segmented Redis Manager
Architecture v3.1 | Layer 7 | Section 6 | Threat: T12

Three Redis databases with different failure modes:

    DB 0 — CACHE (allkeys-lru, DEGRADABLE)
        Schema cache, query result cache, conversation context, suggestions.
        If Redis fails: app works slower (cache miss → DB introspection).

    DB 1 — SECURITY (noeviction, FAIL-CLOSED)
        Token blacklist, rate limits, sessions, lockouts, WS counts, webhook dedup.
        If Redis fails: ALL REQUESTS REJECTED. Security cannot degrade.

    DB 2 — COORDINATION (volatile-lru)
        Schedule locks, LLM token budgets, failover cooldowns.
        If Redis fails: schedules may double-fire, budgets unchecked.
"""

from __future__ import annotations

import logging
from typing import Optional

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)

# Module-level instances
_cache_pool: Optional[aioredis.Redis] = None       # DB 0
_security_pool: Optional[aioredis.Redis] = None     # DB 1
_coordination_pool: Optional[aioredis.Redis] = None  # DB 2


async def init_redis() -> None:
    """Initialize all three Redis connections. Called during app lifespan."""
    global _cache_pool, _security_pool, _coordination_pool

    settings = get_settings()
    base_url = settings.REDIS_URL.rstrip("/")
    password = settings.REDIS_PASSWORD or None

    common_kwargs = {
        "decode_responses": True,
        "password": password,
        "socket_timeout": 5.0,
        "socket_connect_timeout": 5.0,
        "retry_on_timeout": True,
        "health_check_interval": 30,
    }

    # DB 0 — Cache (degradable)
    _cache_pool = aioredis.Redis(
        host=_extract_host(base_url),
        port=_extract_port(base_url),
        db=settings.REDIS_DB_CACHE,
        **common_kwargs,
    )

    # DB 1 — Security (fail-closed)
    _security_pool = aioredis.Redis(
        host=_extract_host(base_url),
        port=_extract_port(base_url),
        db=settings.REDIS_DB_SECURITY,
        **common_kwargs,
    )

    # DB 2 — Coordination
    _coordination_pool = aioredis.Redis(
        host=_extract_host(base_url),
        port=_extract_port(base_url),
        db=settings.REDIS_DB_COORDINATION,
        **common_kwargs,
    )

    # Verify connectivity
    try:
        await _cache_pool.ping()
        await _security_pool.ping()
        await _coordination_pool.ping()
        logger.info("Redis connected: DB0(cache), DB1(security), DB2(coordination)")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        raise


async def close_redis() -> None:
    """Close all Redis connections. Called during app shutdown."""
    global _cache_pool, _security_pool, _coordination_pool

    for pool, name in [
        (_cache_pool, "cache"),
        (_security_pool, "security"),
        (_coordination_pool, "coordination"),
    ]:
        if pool:
            try:
                await pool.aclose()
            except Exception as e:
                logger.warning(f"Error closing Redis {name}: {e}")

    _cache_pool = None
    _security_pool = None
    _coordination_pool = None


def get_redis_cache() -> aioredis.Redis:
    """
    Get Redis DB 0 — Cache.

    DEGRADABLE: If unavailable, callers should fall back to DB queries.
    Never fail-closed on cache misses.
    """
    if _cache_pool is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _cache_pool


def get_redis_security() -> aioredis.Redis:
    """
    Get Redis DB 1 — Security.

    FAIL-CLOSED: If unavailable, ALL requests must be rejected.
    Token blacklist, rate limits, and lockouts live here.
    """
    if _security_pool is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _security_pool


def get_redis_coordination() -> aioredis.Redis:
    """
    Get Redis DB 2 — Coordination.

    Partially degradable: schedule locks and token budgets.
    """
    if _coordination_pool is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _coordination_pool


async def check_redis_health() -> dict[str, bool]:
    """
    Health check for all three Redis databases.
    Returns status of each for /health/deep endpoint.
    """
    results = {}
    for pool, name in [
        (_cache_pool, "cache_db0"),
        (_security_pool, "security_db1"),
        (_coordination_pool, "coordination_db2"),
    ]:
        try:
            if pool:
                await pool.ping()
                results[name] = True
            else:
                results[name] = False
        except Exception:
            results[name] = False
    return results


def _extract_host(url: str) -> str:
    """Extract host from redis://host:port URL."""
    url = url.replace("redis://", "").replace("rediss://", "")
    url = url.split("@")[-1]  # Remove auth if present
    return url.split(":")[0] or "localhost"


def _extract_port(url: str) -> int:
    """Extract port from redis://host:port URL."""
    url = url.replace("redis://", "").replace("rediss://", "")
    url = url.split("@")[-1]
    parts = url.split(":")
    if len(parts) > 1:
        port_str = parts[1].split("/")[0]
        try:
            return int(port_str)
        except ValueError:
            pass
    return 6379
