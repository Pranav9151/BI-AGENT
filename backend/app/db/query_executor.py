"""
Smart BI Agent — Query Executor (PostgreSQL)
Architecture v3.1 | Layer 6 (Query Processing) | Layer 7 (Data Layer)

PURPOSE:
    Execute validated SQL against user-configured PostgreSQL databases.
    Returns results as a list of dicts (column_name → value).

    Built with a clean interface so MySQL/BigQuery adapters can
    plug in later — only PostgreSQL is implemented now.

SECURITY:
    - Uses asyncpg with statement_timeout enforced per-query
    - Read-only connections enforced at DB level (recommended)
    - Credentials are decrypted in-memory only for connection duration
    - Connection is closed immediately after query execution
    - Row limit and byte limit enforced at the application level
"""

from __future__ import annotations

import json
import time
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

import asyncpg

from app.errors.exceptions import (
    DatabaseConnectionError,
    QueryExecutionError,
    QueryResultTooLargeError,
)
from app.logging.structured import get_logger

log = get_logger(__name__)


@dataclass
class QueryResult:
    """Standardized query result."""
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    duration_ms: int
    truncated: bool = False       # True if rows were capped at max_rows
    error: Optional[str] = None


async def execute_query_postgres(
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
    Execute a validated SQL query against a PostgreSQL database.

    Args:
        host: Database host (already SSRF-validated).
        port: Database port.
        database: Database name.
        username: Decrypted username.
        password: Decrypted password.
        sql: Validated SQL (already passed the validator pipeline).
        max_rows: Maximum rows to return.
        query_timeout: Query timeout in seconds.
        ssl_mode: SSL mode for connection.

    Returns:
        QueryResult with columns and rows.

    Raises:
        DatabaseConnectionError: Cannot connect to the database.
        QueryExecutionError: SQL execution failed.
        QueryResultTooLargeError: Result exceeds size limits.
    """
    conn: Optional[asyncpg.Connection] = None
    start = time.monotonic()

    # Build SSL context
    ssl_ctx: Any = None
    if ssl_mode in ("require", "verify-ca", "verify-full"):
        ssl_ctx = "require"  # asyncpg accepts string shorthand
    elif ssl_mode == "disable":
        ssl_ctx = False

    try:
        conn = await asyncpg.connect(
            host=host,
            port=port,
            database=database,
            user=username,
            password=password,
            ssl=ssl_ctx,
            timeout=10,  # Connection timeout
            command_timeout=query_timeout,
        )

        # Set statement_timeout as a safety net
        await conn.execute(f"SET statement_timeout = '{query_timeout * 1000}'")

        # Execute the query
        records = await conn.fetch(sql)

        duration_ms = int((time.monotonic() - start) * 1000)

        if not records:
            return QueryResult(
                columns=[],
                rows=[],
                row_count=0,
                duration_ms=duration_ms,
            )

        # Extract column names from the first record
        columns = list(records[0].keys())

        # Convert to list of dicts, respecting max_rows
        truncated = len(records) > max_rows
        rows: list[dict[str, Any]] = []
        for i, record in enumerate(records):
            if i >= max_rows:
                break
            row = {}
            for col in columns:
                val = record[col]
                # Convert non-JSON-serializable types
                if val is None:
                    row[col] = None
                elif isinstance(val, (bytes, bytearray, memoryview)):
                    row[col] = "<binary>"
                elif hasattr(val, "isoformat"):  # datetime, date, time
                    row[col] = val.isoformat()
                elif isinstance(val, (int, float, bool, str)):
                    row[col] = val
                elif isinstance(val, (list, dict)):
                    row[col] = val
                else:
                    # Decimal, UUID, and any other types → convert to float or string
                    try:
                        row[col] = float(val)
                    except (ValueError, TypeError):
                        row[col] = str(val)
            rows.append(row)

        # Check result byte size (rough estimate)
        result_size = sys.getsizeof(str(rows))
        if result_size > 50_000_000:  # 50MB
            raise QueryResultTooLargeError(
                message="The query result is too large. Add filters or a LIMIT.",
                detail=f"Result size: {result_size} bytes",
            )

        log.info(
            "query_executor.success",
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

    except asyncpg.InvalidCatalogNameError as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        log.error("query_executor.invalid_database", error=str(exc))
        raise DatabaseConnectionError(
            message="The database name is invalid or does not exist.",
            detail=f"asyncpg InvalidCatalogNameError: {exc}",
        ) from exc

    except asyncpg.InvalidPasswordError as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        log.error("query_executor.auth_failed", error=str(exc))
        raise DatabaseConnectionError(
            message="Database authentication failed. Check credentials.",
            detail=f"asyncpg auth error: {exc}",
        ) from exc

    except asyncpg.PostgresError as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        # Extract just the message, not the full traceback
        pg_msg = str(exc).split("\n")[0] if str(exc) else "Unknown PostgreSQL error"
        log.error("query_executor.postgres_error", error=pg_msg, duration_ms=duration_ms)
        raise QueryExecutionError(
            message="The query could not be executed against the database.",
            detail=f"PostgreSQL error: {pg_msg}",
        ) from exc

    except (OSError, ConnectionRefusedError, TimeoutError) as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        log.error("query_executor.connection_failed", error=str(exc))
        raise DatabaseConnectionError(
            message="Could not connect to the database. Check host and port.",
            detail=f"Connection error: {type(exc).__name__}: {exc}",
        ) from exc

    except (QueryResultTooLargeError, DatabaseConnectionError, QueryExecutionError):
        raise  # Re-raise our own exceptions

    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        log.error("query_executor.unexpected", error=str(exc), type=type(exc).__name__)
        raise QueryExecutionError(
            message="An unexpected error occurred while executing the query.",
            detail=f"Unexpected: {type(exc).__name__}: {exc}",
        ) from exc

    finally:
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass