"""
Smart BI Agent — Query Executor (BigQuery)
Architecture v3.1 | Layer 6 (Query Processing) | Phase 5 Session 3

PURPOSE:
    Execute validated SQL against Google BigQuery datasets.
    Uses service account credentials stored in encrypted_credentials.

CREDENTIAL FORMAT (stored in encrypted_credentials as JSON):
    {
        "project_id": "my-gcp-project",
        "service_account_json": { ... full SA key JSON ... }
    }

    Alternatively for Workload Identity (future):
    {
        "project_id": "my-gcp-project",
        "use_default_credentials": true
    }

SECURITY:
    - Service account should have BigQuery Data Viewer role only
    - Credentials decrypted in-memory only for client creation
    - Query timeout enforced via BigQuery job configuration
    - Row limit enforced at application level
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


async def execute_query_bigquery(
    project_id: str,
    dataset: str,
    service_account_json: Optional[dict],
    sql: str,
    max_rows: int = 10_000,
    query_timeout: int = 30,
) -> QueryResult:
    """
    Execute a validated SQL query against Google BigQuery.

    Args:
        project_id: GCP project ID.
        dataset: Default dataset (used if tables lack dataset prefix).
        service_account_json: SA key dict, or None for default credentials.
        sql: Validated SQL (already passed the validator pipeline).
        max_rows: Maximum rows to return.
        query_timeout: Query timeout in seconds.

    Returns:
        QueryResult with columns and rows.
    """
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account as sa_mod
    except ImportError:
        raise QueryExecutionError(
            message="BigQuery support requires google-cloud-bigquery. Please install it.",
            detail="google-cloud-bigquery package not installed",
        )

    start = time.monotonic()

    try:
        # Build credentials
        credentials = None
        if service_account_json:
            credentials = sa_mod.Credentials.from_service_account_info(
                service_account_json,
                scopes=["https://www.googleapis.com/auth/bigquery.readonly"],
            )

        client = bigquery.Client(
            project=project_id,
            credentials=credentials,
        )

        # Configure query job
        job_config = bigquery.QueryJobConfig(
            default_dataset=f"{project_id}.{dataset}" if dataset else None,
            use_legacy_sql=False,
            maximum_bytes_billed=10 * 1024 * 1024 * 1024,  # 10GB safety cap
        )

        # Run query (synchronous — BigQuery client handles async internally)
        import asyncio
        loop = asyncio.get_event_loop()
        query_job = await loop.run_in_executor(
            None,
            lambda: client.query(sql, job_config=job_config, timeout=query_timeout),
        )

        # Wait for results
        result_iter = await loop.run_in_executor(
            None,
            lambda: query_job.result(timeout=query_timeout),
        )

        duration_ms = int((time.monotonic() - start) * 1000)

        # Extract schema (column names + types)
        schema = query_job.schema or []
        columns = [field.name for field in schema]

        if not columns:
            return QueryResult(
                columns=[],
                rows=[],
                row_count=0,
                duration_ms=duration_ms,
            )

        # Process rows
        rows: list[dict[str, Any]] = []
        truncated = False
        row_count = 0

        for bq_row in result_iter:
            if row_count >= max_rows:
                truncated = True
                break
            row: dict[str, Any] = {}
            for col in columns:
                val = bq_row[col]
                if val is None:
                    row[col] = None
                elif isinstance(val, (bytes, bytearray)):
                    row[col] = "<binary>"
                elif hasattr(val, "isoformat"):
                    row[col] = val.isoformat()
                elif isinstance(val, (int, float, bool, str)):
                    row[col] = val
                elif isinstance(val, (list, dict)):
                    row[col] = val
                else:
                    try:
                        row[col] = float(val)
                    except (ValueError, TypeError):
                        row[col] = str(val)
            rows.append(row)
            row_count += 1

        # Check result size
        result_size = sys.getsizeof(str(rows))
        if result_size > 50_000_000:
            raise QueryResultTooLargeError(
                message="The query result is too large. Add filters or a LIMIT.",
                detail=f"Result size: {result_size} bytes",
            )

        log.info(
            "bigquery_executor.success",
            row_count=len(rows),
            column_count=len(columns),
            duration_ms=duration_ms,
            truncated=truncated,
            bytes_billed=query_job.total_bytes_billed,
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

        if "credentials" in str(exc).lower() or "permission" in str(exc).lower():
            log.error("bigquery_executor.auth_failed", error=exc_msg)
            raise DatabaseConnectionError(
                message="BigQuery authentication failed. Check service account credentials.",
                detail=f"BigQuery auth error: {exc_msg}",
            ) from exc

        if "not found" in str(exc).lower():
            log.error("bigquery_executor.not_found", error=exc_msg)
            raise DatabaseConnectionError(
                message="BigQuery project or dataset not found.",
                detail=f"BigQuery error: {exc_msg}",
            ) from exc

        log.error("bigquery_executor.failed", error=exc_msg, type=exc_name)
        raise QueryExecutionError(
            message="The query could not be executed against BigQuery.",
            detail=f"BigQuery error: {exc_name}: {exc_msg}",
        ) from exc