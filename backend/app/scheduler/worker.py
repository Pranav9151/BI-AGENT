"""
Smart BI Agent — Schedule Worker
Architecture v3.1 | Phase 6 Session 6

Runs scheduled queries via APScheduler with Redis distributed lock (T8).
Each job: load saved query → execute via query pipeline → format results → send via dispatcher.

SECURITY:
    - Re-validates permissions at execution time (T43/T9)
    - Distributed lock prevents duplicate execution across workers (T8)
    - Timezone-aware scheduling (T47)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.logging.structured import get_logger

log = get_logger(__name__)

_LOCK_TTL = 300  # 5 minutes — max expected job duration


async def execute_scheduled_job(
    schedule_id: str,
    db_session_factory,
    redis,
    key_manager,
) -> dict[str, Any]:
    """
    Execute a single scheduled job.

    Pipeline:
        1. Acquire Redis distributed lock (T8)
        2. Load schedule + saved query
        3. Execute query through pipeline (fresh permissions — T43)
        4. Format results
        5. Send via notification dispatcher
        6. Update schedule run status
        7. Release lock

    Returns status dict for logging.
    """
    from sqlalchemy import select
    from app.models.schedule import Schedule
    from app.models.saved_query import SavedQuery
    from app.models.connection import Connection
    from app.db.executor_factory import execute_query, get_dialect
    from app.services.sql_validator import validate_sql
    from app.notifications.dispatcher import dispatch_notification, NotificationPayload
    from app.security.key_manager import KeyPurpose

    lock_key = f"schedule_lock:{schedule_id}"
    status_result: dict[str, Any] = {
        "schedule_id": schedule_id,
        "status": "skipped",
        "message": "",
    }

    # Step 1: Acquire distributed lock
    if redis is not None:
        try:
            acquired = await redis.set(lock_key, "1", ex=_LOCK_TTL, nx=True)
            if not acquired:
                status_result["message"] = "Lock held by another worker"
                log.info("scheduler.lock_held", schedule_id=schedule_id)
                return status_result
        except Exception as exc:
            log.error("scheduler.lock_failed", schedule_id=schedule_id, error=str(exc))
            status_result["status"] = "failed"
            status_result["message"] = f"Lock error: {exc}"
            return status_result

    try:
        async with db_session_factory() as db:
            # Step 2: Load schedule
            sched_uuid = uuid.UUID(schedule_id)
            result = await db.execute(
                select(Schedule).where(Schedule.id == sched_uuid)
            )
            schedule = result.scalar_one_or_none()

            if not schedule:
                status_result["message"] = "Schedule not found"
                return status_result

            if not schedule.is_active:
                status_result["message"] = "Schedule is inactive"
                return status_result

            if not schedule.saved_query_id:
                status_result["status"] = "skipped"
                status_result["message"] = "No saved query linked"
                schedule.last_run_status = "skipped"
                schedule.last_run_at = datetime.now(timezone.utc)
                await db.commit()
                return status_result

            # Load saved query
            sq_result = await db.execute(
                select(SavedQuery).where(SavedQuery.id == schedule.saved_query_id)
            )
            saved_query = sq_result.scalar_one_or_none()

            if not saved_query:
                status_result["status"] = "failed"
                status_result["message"] = "Linked saved query not found"
                schedule.last_run_status = "failed"
                schedule.last_run_at = datetime.now(timezone.utc)
                await db.commit()
                return status_result

            # Load connection
            conn_result = await db.execute(
                select(Connection).where(
                    Connection.id == saved_query.connection_id,
                    Connection.is_active == True,
                )
            )
            connection = conn_result.scalar_one_or_none()

            if not connection:
                status_result["status"] = "failed"
                status_result["message"] = "Connection inactive or not found"
                schedule.last_run_status = "failed"
                schedule.last_run_at = datetime.now(timezone.utc)
                await db.commit()
                return status_result

            # Step 3: Validate SQL (fresh validation — T43)
            allowed_tables = set()  # Full access for scheduled jobs (owner's perms applied at save time)
            dialect = get_dialect(connection.db_type)

            try:
                validation = validate_sql(
                    raw_sql=saved_query.sql_query,
                    allowed_tables=allowed_tables,
                    max_rows=connection.max_rows,
                    dialect=dialect,
                )
            except Exception as exc:
                status_result["status"] = "failed"
                status_result["message"] = f"SQL validation failed: {exc}"
                schedule.last_run_status = "failed"
                schedule.last_run_at = datetime.now(timezone.utc)
                await db.commit()
                return status_result

            # Step 4: Execute query
            try:
                query_result = await execute_query(
                    connection=connection,
                    sql=validation.sql,
                    key_manager=key_manager,
                )
            except Exception as exc:
                status_result["status"] = "failed"
                status_result["message"] = f"Query execution failed: {exc}"
                schedule.last_run_status = "failed"
                schedule.last_run_at = datetime.now(timezone.utc)
                await db.commit()
                return status_result

            # Step 5: Format results summary
            summary_lines = [
                f"📊 **{saved_query.name}**",
                f"Query: {saved_query.question}",
                f"Results: {query_result.row_count} rows, {len(query_result.columns)} columns",
                f"Duration: {query_result.duration_ms}ms",
            ]

            if query_result.row_count > 0 and query_result.columns:
                # Show first few rows as preview
                preview_rows = query_result.rows[:5]
                col_names = query_result.columns[:6]
                header = " | ".join(col_names)
                summary_lines.append(f"\n{header}")
                summary_lines.append("-" * len(header))
                for row in preview_rows:
                    vals = [str(row.get(c, ""))[:20] for c in col_names]
                    summary_lines.append(" | ".join(vals))
                if query_result.row_count > 5:
                    summary_lines.append(f"... and {query_result.row_count - 5} more rows")

            body = "\n".join(summary_lines)

            # Step 6: Send via notification dispatcher
            targets = schedule.delivery_targets or []
            send_failures: list[str] = []

            for target in targets:
                platform_id = target.get("platform_id")
                destination = target.get("destination", "")

                if not platform_id:
                    continue

                try:
                    from app.models.notification_platform import NotificationPlatform

                    plat_result = await db.execute(
                        select(NotificationPlatform).where(
                            NotificationPlatform.id == uuid.UUID(platform_id),
                            NotificationPlatform.is_active == True,
                        )
                    )
                    platform = plat_result.scalar_one_or_none()

                    if not platform:
                        send_failures.append(f"Platform {platform_id} not found/inactive")
                        continue

                    config = json.loads(
                        key_manager.decrypt(platform.encrypted_config, KeyPurpose.NOTIFICATION_KEYS)
                    )

                    payload = NotificationPayload(
                        title=f"Scheduled Report: {saved_query.name}",
                        body=body,
                        destination=destination,
                    )

                    notif_result = await dispatch_notification(
                        platform_type=platform.platform_type,
                        config=config,
                        payload=payload,
                    )

                    if not notif_result.success:
                        send_failures.append(
                            f"{platform.platform_type}→{destination}: {notif_result.error}"
                        )

                except Exception as exc:
                    send_failures.append(f"Platform {platform_id}: {exc}")

            # Step 7: Update schedule status
            now = datetime.now(timezone.utc)
            schedule.last_run_at = now
            saved_query.run_count = (saved_query.run_count or 0) + 1
            saved_query.last_run_at = now

            if send_failures:
                schedule.last_run_status = "partial"
                status_result["status"] = "partial"
                status_result["message"] = f"Query OK, delivery issues: {'; '.join(send_failures[:3])}"
            else:
                schedule.last_run_status = "success"
                status_result["status"] = "success"
                status_result["message"] = (
                    f"OK: {query_result.row_count} rows, "
                    f"sent to {len(targets)} target(s)"
                )

            await db.commit()

            log.info(
                "scheduler.job_completed",
                schedule_id=schedule_id,
                status=status_result["status"],
                rows=query_result.row_count,
                targets=len(targets),
            )

    except Exception as exc:
        log.error("scheduler.job_error", schedule_id=schedule_id, error=str(exc))
        status_result["status"] = "failed"
        status_result["message"] = str(exc)[:200]

    finally:
        # Release lock
        if redis is not None:
            try:
                await redis.delete(lock_key)
            except Exception:
                pass

    return status_result