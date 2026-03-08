"""
Smart BI Agent — Account Lockout
Architecture v3.1 | Security Layer 8 | Threat: T10

Controls:
    - 10 failed login attempts → 30-minute lockout
    - Progressive delay: attempt_count × 2 seconds
    - Admin notification on lockout
    - Tracks via Redis DB 1 (fail-closed) + PostgreSQL (persistent)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import get_settings


class AccountLockedError(Exception):
    """Raised when a locked account attempts to authenticate."""

    def __init__(self, locked_until: datetime, attempts: int) -> None:
        self.locked_until = locked_until
        self.attempts = attempts
        remaining = (locked_until - datetime.now(timezone.utc)).total_seconds()
        remaining_minutes = max(0, int(remaining / 60))
        super().__init__(
            f"Account locked for {remaining_minutes} more minutes "
            f"after {attempts} failed attempts."
        )


class LockoutManager:
    """
    Manages account lockout state and progressive delays.

    State is stored in two places:
        1. Redis DB 1 (fast check, fail-closed if Redis down)
        2. PostgreSQL users table (persistent, source of truth)

    The Redis layer provides fast lockout checks without hitting the DB
    on every authentication attempt. The DB layer ensures lockout survives
    Redis restarts.
    """

    def __init__(self, redis_security=None) -> None:
        """
        Args:
            redis_security: Redis client connected to DB 1 (security).
                           Passed at init to avoid circular imports.
        """
        self._redis = redis_security
        self._settings = get_settings()

    @property
    def threshold(self) -> int:
        """Number of failed attempts before lockout."""
        return self._settings.LOCKOUT_THRESHOLD

    @property
    def duration_minutes(self) -> int:
        """How long the account stays locked (minutes)."""
        return self._settings.LOCKOUT_DURATION_MINUTES

    @property
    def delay_factor(self) -> int:
        """Progressive delay multiplier (seconds per attempt)."""
        return self._settings.PROGRESSIVE_DELAY_FACTOR

    async def check_lockout(self, email: str) -> None:
        """
        Check if an account is currently locked. Call BEFORE password verification.

        Args:
            email: The login email.

        Raises:
            AccountLockedError: If the account is locked.
        """
        # Check Redis first (fast path)
        if self._redis:
            lockout_key = f"lockout:{email}"
            lockout_data = await self._redis.get(lockout_key)
            if lockout_data:
                # Account is locked in Redis
                ttl = await self._redis.ttl(lockout_key)
                locked_until = datetime.now(timezone.utc) + timedelta(seconds=max(ttl, 0))
                raise AccountLockedError(
                    locked_until=locked_until,
                    attempts=self.threshold,
                )

    async def record_failed_attempt(self, email: str, current_attempts: int) -> int:
        """
        Record a failed login attempt. Returns updated attempt count.

        Applies progressive delay: attempt_count × delay_factor seconds.
        If threshold is reached, triggers lockout.

        Args:
            email: The login email.
            current_attempts: Current failed attempt count from DB.

        Returns:
            New failed attempt count.
        """
        new_count = current_attempts + 1

        # Progressive delay — makes brute force increasingly painful
        # Attempt 1: 2s, Attempt 2: 4s, ..., Attempt 9: 18s
        delay_seconds = new_count * self.delay_factor
        # Cap delay to avoid absurd waits
        delay_seconds = min(delay_seconds, 30)
        await asyncio.sleep(delay_seconds)

        # Check if threshold reached
        if new_count >= self.threshold:
            await self._trigger_lockout(email)

        return new_count

    async def record_successful_login(self, email: str) -> None:
        """
        Clear lockout state after successful authentication.

        Args:
            email: The login email.
        """
        if self._redis:
            lockout_key = f"lockout:{email}"
            await self._redis.delete(lockout_key)

    async def _trigger_lockout(self, email: str) -> None:
        """
        Lock the account in Redis with TTL = lockout duration.

        Args:
            email: The email to lock.
        """
        if self._redis:
            lockout_key = f"lockout:{email}"
            ttl_seconds = self.duration_minutes * 60
            await self._redis.set(lockout_key, "locked", ex=ttl_seconds)

        # TODO: Send admin notification (Phase 6 — notification hub)
        # For now, this is logged by the caller via structlog

    def compute_locked_until(self) -> datetime:
        """Compute the lockout expiry timestamp."""
        return datetime.now(timezone.utc) + timedelta(minutes=self.duration_minutes)

    @staticmethod
    def is_locked(locked_until: Optional[datetime]) -> bool:
        """
        Check if a locked_until timestamp is still in the future.

        Args:
            locked_until: The lockout expiry from the DB (can be None).

        Returns:
            True if the account is currently locked.
        """
        if locked_until is None:
            return False
        # Ensure timezone-aware comparison
        now = datetime.now(timezone.utc)
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        return locked_until > now
