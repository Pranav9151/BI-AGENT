"""
Smart BI Agent — Executor Factory
Architecture v3.1 | Layer 6 (Query Processing) | Phase 5 Session 3

PURPOSE:
    Routes query execution to the correct database-specific executor
    based on connection.db_type.

SUPPORTED:
    - postgresql (asyncpg)    — Phase 4
    - mysql      (aiomysql)   — Phase 5 Session 3
    - bigquery   (google-cloud-bigquery) — Phase 5 Session 3

FUTURE:
    - mssql     (aioodbc)     — Phase 5+
    - snowflake (snowflake-connector) — Phase 5+
"""

from __future__ import annotations

import json
from typing import Any

from app.db.query_executor import QueryResult, execute_query_postgres
from app.errors.exceptions import ValidationError
from app.logging.structured import get_logger
from app.models.connection import Connection
from app.security.key_manager import KeyPurpose

log = get_logger(__name__)

# Map db_type to sqlglot dialect
DIALECT_MAP: dict[str, str] = {
    "postgresql": "postgres",
    "postgres":   "postgres",
    "mysql":      "mysql",
    "bigquery":   "bigquery",
    "mssql":      "tsql",
    "snowflake":  "snowflake",
}


def get_dialect(db_type: str) -> str:
    """Return the sqlglot dialect string for a given db_type."""
    return DIALECT_MAP.get(db_type.lower(), "postgres")


async def execute_query(
    connection: Connection,
    sql: str,
    key_manager: Any,
) -> QueryResult:
    """
    Execute a validated SQL query against the correct database backend.

    Args:
        connection: Connection ORM object with db_type, credentials, etc.
        sql: Validated SQL (already passed the validator pipeline).
        key_manager: KeyManager for decrypting credentials.

    Returns:
        QueryResult with columns and rows.

    Raises:
        ValidationError: Unsupported db_type.
        DatabaseConnectionError / QueryExecutionError: From executors.
    """
    db_type = (connection.db_type or "").lower()

    # Decrypt credentials
    creds = json.loads(
        key_manager.decrypt(connection.encrypted_credentials, KeyPurpose.DB_CREDENTIALS)
    )

    if db_type in ("postgresql", "postgres"):
        return await execute_query_postgres(
            host=connection.host,
            port=connection.port,
            database=connection.database_name,
            username=creds["username"],
            password=creds["password"],
            sql=sql,
            max_rows=connection.max_rows,
            query_timeout=connection.query_timeout,
            ssl_mode=connection.ssl_mode,
        )

    if db_type == "mysql":
        from app.db.mysql_executor import execute_query_mysql

        return await execute_query_mysql(
            host=connection.host,
            port=connection.port or 3306,
            database=connection.database_name,
            username=creds["username"],
            password=creds["password"],
            sql=sql,
            max_rows=connection.max_rows,
            query_timeout=connection.query_timeout,
            ssl_mode=connection.ssl_mode,
        )

    if db_type == "bigquery":
        from app.db.bigquery_executor import execute_query_bigquery

        return await execute_query_bigquery(
            project_id=creds.get("project_id", connection.database_name or ""),
            dataset=creds.get("dataset", ""),
            service_account_json=creds.get("service_account_json"),
            sql=sql,
            max_rows=connection.max_rows,
            query_timeout=connection.query_timeout,
        )

    log.warning("executor_factory.unsupported_db_type", db_type=db_type)
    raise ValidationError(
        message=f"Database type '{db_type}' is not yet supported.",
        detail=f"Supported types: postgresql, mysql, bigquery",
    )