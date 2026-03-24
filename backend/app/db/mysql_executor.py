"""
Smart BI Agent — Query Executor (MySQL)
Architecture v3.1 | Layer 6 (Query Processing) | Phase 5 Session 3

PURPOSE:
    Execute validated SQL against user-configured MySQL databases.
    Mirrors execute_query_postgres interface for drop-in use via executor factory.

SECURITY:
    - Read-only connections recommended at DB level (GRANT SELECT only)
    - Credentials decrypted in-memory only for connection duration
    - Connection closed immediately after query execution
    - Row limit and byte limit enforced at application level
"""

from __future__ import annotations

import sys
import time
from typing import Any, Optional

from app.db.query_executor import QueryResult
from app.errors.exceptions import (
    DatabaseConnectionError,
    QueryExecutionError,
    QueryResultTooLargeError,
)
from app.logging.structured import get_logger

log = get_logger(__name__)


async def execute_query_mysql(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    sql: str,
    max_rows: int = 10_000,
    query_timeout: int = 30,
    ssl_mode: str = "require",
) -> QueryResult:
    """
    Execute a validated SQL query against a MySQL database.

    Args:
        host: Database host (already SSRF-validated).
        port: Database port (default 3306).
        database: Database name.
        username: Decrypted username.
        password: Decrypted password.
        sql: Validated SQL (already passed the validator pipeline).
        max_rows: Maximum rows to return.
        query_timeout: Query timeout in seconds.
        ssl_mode: SSL mode for connection.

    Returns:
        QueryResult with columns and rows.
    """
    try:
        import aiomysql
    except ImportError:
        raise QueryExecutionError(
            message="MySQL support requires aiomysql. Please install it.",
            detail="aiomysql package not installed",
        )

    conn: Optional[Any] = None
    start = time.monotonic()

    # Build SSL context
    ssl_ctx: Any = None
    if ssl_mode not in ("disable", "allow"):
        try:
            import ssl as _ssl
            ssl_ctx = _ssl.create_default_context()
            if ssl_mode == "require":
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = _ssl.CERT_NONE
        except Exception:
            ssl_ctx = None

    try:
        conn = await aiomysql.connect(
            host=host,
            port=port,
            db=database,
            user=username,
            password=password,
            ssl=ssl_ctx,
            connect_timeout=10,
            read_timeout=query_timeout,
            write_timeout=query_timeout,
            charset="utf8mb4",
            autocommit=True,
        )

        async with conn.cursor(aiomysql.DictCursor) as cursor:
            # Set session timeout
            await cursor.execute(
                f"SET SESSION MAX_EXECUTION_TIME = {query_timeout * 1000}"
            )

            await cursor.execute(sql)
            records = await cursor.fetchmany(max_rows + 1)

        duration_ms = int((time.monotonic() - start) * 1000)

        if not records:
            return QueryResult(
                columns=[],
                rows=[],
                row_count=0,
                duration_ms=duration_ms,
            )

        columns = list(records[0].keys())
        truncated = len(records) > max_rows
        rows_to_process = records[:max_rows]

        rows: list[dict[str, Any]] = []
        for record in rows_to_process:
            row: dict[str, Any] = {}
            for col in columns:
                val = record[col]
                if val is None:
                    row[col] = None
                elif isinstance(val, (bytes, bytearray)):
                    row[col] = "<binary>"
                elif hasattr(val, "isoformat"):
                    row[col] = val.isoformat()
                elif isinstance(val, (int, float, bool, str)):
                    row[col] = val
                else:
                    try:
                        row[col] = float(val)
                    except (ValueError, TypeError):
                        row[col] = str(val)
            rows.append(row)

        # Check result byte size
        result_size = sys.getsizeof(str(rows))
        if result_size > 50_000_000:
            raise QueryResultTooLargeError(
                message="The query result is too large. Add filters or a LIMIT.",
                detail=f"Result size: {result_size} bytes",
            )

        log.info(
            "mysql_executor.success",
            row_count=len(rows),
            column_count=len(columns),
            duration_ms=duration_ms,
            truncated=truncated,
        )

        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            duration_ms=duration_ms,
            truncated=truncated,
        )

    except (QueryResultTooLargeError, DatabaseConnectionError, QueryExecutionError):
        raise

    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        exc_name = type(exc).__name__
        exc_msg = str(exc).split("\n")[0] if str(exc) else "Unknown error"

        if "Access denied" in str(exc) or "authentication" in str(exc).lower():
            log.error("mysql_executor.auth_failed", error=exc_msg)
            raise DatabaseConnectionError(
                message="MySQL authentication failed. Check credentials.",
                detail=f"MySQL auth error: {exc_msg}",
            ) from exc

        if any(kw in exc_name for kw in ("Operational", "Connect", "Timeout", "OS")):
            log.error("mysql_executor.connection_failed", error=exc_msg)
            raise DatabaseConnectionError(
                message="Could not connect to MySQL. Check host and port.",
                detail=f"Connection error: {exc_name}: {exc_msg}",
            ) from exc

        log.error("mysql_executor.failed", error=exc_msg, type=exc_name)
        raise QueryExecutionError(
            message="The query could not be executed against MySQL.",
            detail=f"MySQL error: {exc_name}: {exc_msg}",
        ) from exc

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass