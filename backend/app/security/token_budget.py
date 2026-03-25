"""
Smart BI Agent — Token Budget Enforcement
Architecture v3.1 | Phase 7 Session 9 | Threat: T (denial-of-wallet)

PURPOSE:
    Enforce daily per-user LLM token budgets.
    Prevents a single user from exhausting the LLM API budget.

STORAGE:
    Redis DB 2 (coordination) — key: token_budget:{user_id}:{date}
    TTL: 25 hours (auto-cleanup after midnight rollover)

DEFAULTS:
    - Per-user daily limit: 100,000 tokens (configurable via settings)
    - Checked BEFORE LLM call, updated AFTER
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from app.logging.structured import get_logger

log = get_logger(__name__)

_DEFAULT_DAILY_LIMIT = 100_000


def _budget_key(user_id: str) -> str:
    """Redis key for today's token budget."""
    today = date.today().isoformat()
    return f"token_budget:{user_id}:{today}"


async def check_token_budget(
    user_id: str,
    redis,
    daily_limit: int = _DEFAULT_DAILY_LIMIT,
) -> tuple[bool, int, int]:
    """
    Check if user has remaining token budget for today.

    Returns:
        (allowed, tokens_used_today, daily_limit)
    """
    if redis is None:
        return True, 0, daily_limit

    key = _budget_key(user_id)
    try:
        used_raw = await redis.get(key)
        used = int(used_raw) if used_raw else 0
        allowed = used < daily_limit
        if not allowed:
            log.warning(
                "token_budget.exceeded",
                user_id=user_id,
                used=used,
                limit=daily_limit,
            )
        return allowed, used, daily_limit
    except Exception as exc:
        log.error("token_budget.check_failed", user_id=user_id, error=str(exc))
        # Fail open on budget check errors — don't block users
        return True, 0, daily_limit


async def record_token_usage(
    user_id: str,
    tokens: int,
    redis,
) -> int:
    """
    Record tokens used. Returns new total for today.
    """
    if redis is None or tokens <= 0:
        return 0

    key = _budget_key(user_id)
    try:
        new_total = await redis.incrby(key, tokens)
        # Set TTL on first use (25 hours — covers timezone differences)
        if new_total == tokens:
            await redis.expire(key, 90_000)
        return new_total
    except Exception as exc:
        log.error("token_budget.record_failed", user_id=user_id, error=str(exc))
        return 0