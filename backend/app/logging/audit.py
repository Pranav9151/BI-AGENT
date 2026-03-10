"""
Smart BI Agent — Audit Logger
Architecture v3.1 | Layer 8 (Security) + Layer 9 (Observability) | Threat: T20

PURPOSE:
    Tamper-evident, append-only audit trail for all query executions and
    security events.

T20 — TAMPER EVIDENCE (Hash Chain):
    Every audit log entry stores the SHA-256 hash of the PREVIOUS entry's
    canonical representation. This creates a chain:

        Entry N: prev_hash = SHA256(canonical(Entry N-1))
        Entry N+1: prev_hash = SHA256(canonical(Entry N))

    If any entry is deleted or modified, all subsequent hashes become invalid.
    A monthly integrity verification job (scheduled separately) walks the chain
    and alerts on any break.

    The GENESIS entry (first entry ever, or first after a verified reset) has
    prev_hash = SHA256("GENESIS_BLOCK_SMART_BI_AGENT_V3.1") — a known constant.

T20 — APPEND-ONLY ENFORCEMENT:
    The PostgreSQL role used by the application has INSERT privilege ONLY on
    audit_logs. No UPDATE, no DELETE. Even if an attacker achieves RCE as the
    app user, they cannot modify existing audit entries.

DESIGN:
    - Async writer: does NOT block the request path
    - asyncio.Queue with a background task drains entries — no DB latency
      added to the user-facing response
    - Queue is bounded (MAX_QUEUE_SIZE) — if the DB is down, entries are
      dropped with a CRITICAL log rather than crashing the queue producer.
      This is the correct trade-off: availability over audit completeness
      during a DB outage (the structured log will still capture the event).
    - SIEM shipping: structlog emits a secondary JSON log for every audit
      entry — syslog/Loki/Splunk can pick this up from stdout.

GDPR:
    The `question` field is the only PII-bearing field. The GDPR erasure
    endpoint sets question = "[GDPR_ERASED]" for a specific user's entries.
    All other fields are operational metadata with no direct PII.

USAGE:
    from app.logging.audit import AuditWriter

    # In lifespan startup:
    audit = AuditWriter(db_session_factory)
    await audit.start()
    app.state.audit = audit

    # In query handler:
    await request.app.state.audit.log(
        user_id=current_user.id,
        question="Show me total revenue by region",
        generated_sql="SELECT region, SUM(revenue) FROM sales GROUP BY region",
        execution_status="success",
        row_count=12,
        duration_ms=87,
        ip_address=request.client.host,
        request_id=request.state.request_id,
        llm_provider_type="openai",
        llm_model_used="gpt-4o",
        llm_tokens_used=342,
    )

    # In lifespan shutdown:
    await audit.stop()
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.logging.structured import get_logger
from app.models.audit_log import AuditLog

log = get_logger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Known genesis hash — the chain anchor for the very first entry.
# Do NOT change this after deployment. It is the trust root.
GENESIS_HASH: str = hashlib.sha256(
    b"GENESIS_BLOCK_SMART_BI_AGENT_V3.1"
).hexdigest()

# Maximum entries buffered in memory before dropping (DB outage resilience)
MAX_QUEUE_SIZE: int = 10_000

# Seconds to wait for the drain task to finish on shutdown
SHUTDOWN_DRAIN_TIMEOUT: float = 10.0


# =============================================================================
# Canonical Representation for Hashing
# =============================================================================

def _canonical(entry: AuditLog) -> bytes:
    """
    Produce a stable, canonical byte representation of an audit entry for
    hash-chain computation. Uses only immutable fields that define the entry's
    identity. Field order is FIXED — never change this after deployment.
    """
    payload = {
        "id": str(entry.id),
        "user_id": str(entry.user_id) if entry.user_id else None,
        "connection_id": str(entry.connection_id) if entry.connection_id else None,
        "conversation_id": str(entry.conversation_id) if entry.conversation_id else None,
        "request_id": entry.request_id,
        "question": entry.question,
        "generated_sql": entry.generated_sql,
        "execution_status": entry.execution_status,
        "error_message": entry.error_message,
        "row_count": entry.row_count,
        "result_bytes": entry.result_bytes,
        "duration_ms": entry.duration_ms,
        "llm_provider_type": entry.llm_provider_type,
        "llm_model_used": entry.llm_model_used,
        "llm_tokens_used": entry.llm_tokens_used,
        "ip_address": entry.ip_address,
        # created_at excluded — server-generated, could differ by microseconds
    }
    # separators=(',', ':') produces compact JSON — no whitespace variation
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def compute_hash(entry: AuditLog) -> str:
    """Return the SHA-256 hex digest of the canonical entry representation."""
    return hashlib.sha256(_canonical(entry)).hexdigest()


# =============================================================================
# Audit Entry (in-memory before DB write)
# =============================================================================

class _AuditEntry:
    """
    Lightweight in-memory struct passed through the asyncio queue.
    Using a plain class (not dataclass) to keep import overhead minimal.
    """
    __slots__ = (
        "user_id", "connection_id", "llm_provider_id",
        "notification_platform_id", "conversation_id", "request_id",
        "question", "generated_sql", "execution_status",
        "error_message", "row_count", "result_bytes", "duration_ms",
        "llm_provider_type", "llm_model_used", "llm_tokens_used",
        "ip_address",
    )

    def __init__(self, **kwargs: Any) -> None:
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))


# =============================================================================
# AuditWriter — the public interface
# =============================================================================

class AuditWriter:
    """
    Async, non-blocking audit log writer with hash-chain tamper evidence.

    Lifecycle:
        await writer.start()   # call from app lifespan startup
        await writer.log(...)  # call from route handlers
        await writer.stop()    # call from app lifespan shutdown
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._queue: asyncio.Queue[_AuditEntry | None] = asyncio.Queue(
            maxsize=MAX_QUEUE_SIZE
        )
        self._task: asyncio.Task | None = None
        self._last_hash: str = GENESIS_HASH
        self._running: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Start the background drain task and restore last_hash from DB.
        Call once from application lifespan startup.
        """
        if self._running:
            return

        # Restore hash chain tip from DB so we don't restart from GENESIS
        # on every app restart.
        await self._restore_chain_tip()

        self._running = True
        self._task = asyncio.create_task(
            self._drain_loop(), name="audit-drain"
        )
        log.info("audit.writer.started", last_hash=self._last_hash[:16] + "...")

    async def stop(self) -> None:
        """
        Gracefully drain the queue and stop the background task.
        Call from application lifespan shutdown.
        """
        if not self._running:
            return

        self._running = False
        # Sentinel None tells the drain loop to exit after flushing
        await self._queue.put(None)

        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=SHUTDOWN_DRAIN_TIMEOUT)
            except asyncio.TimeoutError:
                log.error(
                    "audit.writer.shutdown_timeout",
                    pending=self._queue.qsize(),
                )
                self._task.cancel()

        log.info("audit.writer.stopped")

    # ------------------------------------------------------------------
    # Public log method
    # ------------------------------------------------------------------

    async def log(
        self,
        *,
        execution_status: str,
        question: str,
        user_id: uuid.UUID | str | None = None,
        connection_id: uuid.UUID | str | None = None,
        llm_provider_id: uuid.UUID | str | None = None,
        notification_platform_id: uuid.UUID | str | None = None,
        conversation_id: uuid.UUID | str | None = None,
        request_id: str | None = None,
        generated_sql: str | None = None,
        error_message: str | None = None,
        row_count: int | None = None,
        result_bytes: int | None = None,
        duration_ms: int | None = None,
        llm_provider_type: str | None = None,
        llm_model_used: str | None = None,
        llm_tokens_used: int | None = None,
        ip_address: str | None = None,
    ) -> None:
        """
        Enqueue an audit entry for async DB write. Non-blocking.

        If the queue is full (DB outage lasting long enough to exhaust
        MAX_QUEUE_SIZE), the entry is DROPPED and logged as CRITICAL to
        structured log (which goes to stdout → SIEM).
        """
        entry = _AuditEntry(
            user_id=user_id,
            connection_id=connection_id,
            llm_provider_id=llm_provider_id,
            notification_platform_id=notification_platform_id,
            conversation_id=conversation_id,
            request_id=request_id,
            question=question,
            generated_sql=generated_sql,
            execution_status=execution_status,
            error_message=error_message,
            row_count=row_count,
            result_bytes=result_bytes,
            duration_ms=duration_ms,
            llm_provider_type=llm_provider_type,
            llm_model_used=llm_model_used,
            llm_tokens_used=llm_tokens_used,
            ip_address=ip_address,
        )

        try:
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            log.critical(
                "audit.queue.full_dropped",
                execution_status=execution_status,
                user_id=str(user_id) if user_id else None,
                request_id=request_id,
            )

    # ------------------------------------------------------------------
    # Background drain loop
    # ------------------------------------------------------------------

    async def _drain_loop(self) -> None:
        """
        Background coroutine: drain queue entries one by one, writing each
        to PostgreSQL with hash-chain linking.
        """
        log.debug("audit.drain_loop.running")

        while True:
            try:
                item = await self._queue.get()
            except Exception as exc:  # pragma: no cover
                log.error("audit.queue.get_error", error=str(exc))
                continue

            # None sentinel → shutdown
            if item is None:
                # Drain any remaining items before exit
                while not self._queue.empty():
                    remaining = self._queue.get_nowait()
                    if remaining is not None:
                        await self._write_entry(remaining)
                break

            await self._write_entry(item)

        log.debug("audit.drain_loop.exited")

    async def _write_entry(self, item: _AuditEntry) -> None:
        """
        Write a single audit entry to PostgreSQL.
        Computes hash chain inline — prev_hash = self._last_hash.
        """
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    audit_entry = AuditLog(
                        user_id=item.user_id,
                        connection_id=item.connection_id,
                        llm_provider_id=item.llm_provider_id,
                        notification_platform_id=item.notification_platform_id,
                        conversation_id=item.conversation_id,
                        request_id=item.request_id,
                        question=item.question,
                        generated_sql=item.generated_sql,
                        execution_status=item.execution_status,
                        error_message=item.error_message,
                        row_count=item.row_count,
                        result_bytes=item.result_bytes,
                        duration_ms=item.duration_ms,
                        llm_provider_type=item.llm_provider_type,
                        llm_model_used=item.llm_model_used,
                        llm_tokens_used=item.llm_tokens_used,
                        ip_address=item.ip_address,
                        prev_hash=self._last_hash,
                    )
                    session.add(audit_entry)
                    await session.flush()  # get generated id + created_at

                    # Compute this entry's own hash AFTER flush (id is now set)
                    entry_hash = compute_hash(audit_entry)
                    self._last_hash = entry_hash

            # Secondary SIEM log — emitted to stdout as structured JSON
            log.info(
                "audit.entry.written",
                audit_id=str(audit_entry.id),
                user_id=str(item.user_id) if item.user_id else None,
                execution_status=item.execution_status,
                duration_ms=item.duration_ms,
                row_count=item.row_count,
                llm_provider_type=item.llm_provider_type,
                entry_hash=entry_hash[:16] + "...",
            )

        except Exception as exc:
            # Never crash the drain loop — log and continue
            log.error(
                "audit.write.failed",
                error=str(exc),
                execution_status=item.execution_status,
                user_id=str(item.user_id) if item.user_id else None,
            )

    # ------------------------------------------------------------------
    # Hash chain integrity helpers
    # ------------------------------------------------------------------

    async def _restore_chain_tip(self) -> None:
        """
        On startup, query the last audit entry to restore the hash chain tip.
        If the table is empty, use GENESIS_HASH.
        """
        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(AuditLog)
                    .order_by(AuditLog.created_at.desc())
                    .limit(1)
                )
                last_entry = result.scalar_one_or_none()

                if last_entry is None:
                    self._last_hash = GENESIS_HASH
                    log.info("audit.chain.genesis", hash=GENESIS_HASH[:16] + "...")
                else:
                    self._last_hash = compute_hash(last_entry)
                    log.info(
                        "audit.chain.restored",
                        last_audit_id=str(last_entry.id),
                        tip_hash=self._last_hash[:16] + "...",
                    )
        except Exception as exc:
            # If DB is unavailable at startup, start with GENESIS to avoid
            # blocking startup. The chain will have a break at this restart
            # point — integrity job will flag it.
            log.error(
                "audit.chain.restore_failed",
                error=str(exc),
                fallback="GENESIS_HASH",
            )
            self._last_hash = GENESIS_HASH

    async def verify_chain_integrity(
        self,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """
        Walk the audit chain and verify hash continuity.

        Called by the monthly integrity cron job and the /health/deep endpoint
        (admin auth required). Returns a summary dict with any broken links.

        Args:
            limit: Max entries to scan (scan in reverse-chronological batches
                   for the monthly job; pass None for full scan — can be slow).
        """
        broken_links: list[dict] = []
        entries_checked: int = 0
        prev_entry: AuditLog | None = None

        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(AuditLog)
                    .order_by(AuditLog.created_at.asc())
                    .limit(limit)
                )
                entries = result.scalars().all()

                for entry in entries:
                    entries_checked += 1
                    expected_prev_hash = (
                        GENESIS_HASH if prev_entry is None
                        else compute_hash(prev_entry)
                    )
                    if entry.prev_hash != expected_prev_hash:
                        broken_links.append({
                            "audit_id": str(entry.id),
                            "expected_prev_hash": expected_prev_hash[:16] + "...",
                            "actual_prev_hash": (entry.prev_hash or "")[:16] + "...",
                            "created_at": entry.created_at.isoformat(),
                        })
                    prev_entry = entry

        except Exception as exc:
            log.error("audit.integrity.check_failed", error=str(exc))
            return {"status": "error", "error": str(exc)}

        status = "ok" if not broken_links else "TAMPERED"
        if broken_links:
            log.critical(
                "audit.integrity.BREACH_DETECTED",
                broken_count=len(broken_links),
                first_break=broken_links[0],
            )
        else:
            log.info(
                "audit.integrity.ok",
                entries_checked=entries_checked,
            )

        return {
            "status": status,
            "entries_checked": entries_checked,
            "broken_links": broken_links,
        }
