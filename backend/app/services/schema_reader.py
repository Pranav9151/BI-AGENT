"""
Smart BI Agent — Schema Reader Service
Architecture v3.1 | Layer 6 (Query Processing)

Shared service for database schema introspection. Used by:
  - routes_schema.py (Schema Browser endpoint)
  - routes_query.py  (LLM prompt schema context)

Currently supports PostgreSQL. Phase 5/Session 3 adds MySQL + BigQuery adapters.

SECURITY:
  - Credentials decrypted in-memory only, never logged
  - Connection timeout 10s (prevents hanging on unreachable hosts)
  - Graceful fallback: returns empty schema on error (never crashes caller)
"""
from __future__ import annotations

import json
from typing import Any

from app.logging.structured import get_logger
from app.models.connection import Connection
from app.security.key_manager import KeyPurpose

log = get_logger(__name__)


async def introspect_schema(conn: Connection, key_manager: Any) -> dict[str, Any]:
    """
    Factory: route introspection to the correct adapter by db_type.
    """
    db_type = (conn.db_type or "").lower()

    if db_type in ("postgresql", "postgres"):
        return await introspect_postgres(conn, key_manager)
    if db_type == "mysql":
        return await introspect_mysql(conn, key_manager)
    if db_type == "bigquery":
        return await introspect_bigquery(conn, key_manager)

    log.warning("schema_reader.unsupported_db_type", db_type=db_type, connection_id=str(conn.id))
    return {}


async def introspect_postgres(conn: Connection, key_manager: Any) -> dict[str, Any]:
    """
    Introspect PostgreSQL schema via information_schema using asyncpg.

    Connects to the user's target database with their decrypted credentials,
    reads all tables and columns from allowed schemas, and returns a
    structured schema dict.

    Returns:
        {table_name: {columns: {col_name: {type, nullable, primary_key}}}}
    """
    import asyncpg as apg

    # Decrypt connection credentials
    try:
        creds = json.loads(
            key_manager.decrypt(conn.encrypted_credentials, KeyPurpose.DB_CREDENTIALS)
        )
    except Exception as exc:
        log.error("schema_reader.decrypt_failed", connection_id=str(conn.id), error=str(exc))
        return {}

    # Build SSL context
    ssl_ctx: Any = False
    if conn.ssl_mode == "disable":
        ssl_ctx = False
    elif conn.ssl_mode in ("require", "verify-ca", "verify-full"):
        ssl_ctx = "require"

    db_conn = None
    try:
        db_conn = await apg.connect(
            host=conn.host,
            port=conn.port,
            database=conn.database_name,
            user=creds["username"],
            password=creds["password"],
            ssl=ssl_ctx,
            timeout=10,
        )

        # Get allowed schemas (default to public)
        schemas = conn.allowed_schemas or ["public"]
        schema_placeholders = ", ".join(f"${i+1}" for i in range(len(schemas)))

        # Query all tables
        tables_sql = f"""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema IN ({schema_placeholders})
              AND table_type = 'BASE TABLE'
            ORDER BY table_schema, table_name
        """
        tables = await db_conn.fetch(tables_sql, *schemas)

        if not tables:
            log.info("schema_reader.no_tables", connection_id=str(conn.id), schemas=schemas)
            return {}

        # Query all columns with PK detection
        columns_sql = f"""
            SELECT
                c.table_name,
                c.column_name,
                c.data_type,
                c.is_nullable,
                CASE WHEN kcu.column_name IS NOT NULL THEN true ELSE false END AS is_primary_key
            FROM information_schema.columns c
            LEFT JOIN information_schema.table_constraints tc
                ON tc.table_schema = c.table_schema
                AND tc.table_name = c.table_name
                AND tc.constraint_type = 'PRIMARY KEY'
            LEFT JOIN information_schema.key_column_usage kcu
                ON kcu.constraint_name = tc.constraint_name
                AND kcu.table_schema = tc.table_schema
                AND kcu.column_name = c.column_name
            WHERE c.table_schema IN ({schema_placeholders})
            ORDER BY c.table_name, c.ordinal_position
        """
        columns = await db_conn.fetch(columns_sql, *schemas)

        # Build schema dict
        schema_data: dict[str, Any] = {}
        for table in tables:
            table_name = table["table_name"]
            schema_data[table_name] = {"columns": {}}

        for col in columns:
            table_name = col["table_name"]
            if table_name in schema_data:
                schema_data[table_name]["columns"][col["column_name"]] = {
                    "type": col["data_type"],
                    "nullable": col["is_nullable"] == "YES",
                    "primary_key": col["is_primary_key"],
                }

        log.info(
            "schema_reader.success",
            connection_id=str(conn.id),
            table_count=len(schema_data),
            column_count=sum(len(t["columns"]) for t in schema_data.values()),
        )

        return schema_data

    except Exception as exc:
        log.error("schema_reader.failed", connection_id=str(conn.id), error=str(exc))
        return {}

    finally:
        if db_conn is not None:
            try:
                await db_conn.close()
            except Exception:
                pass


async def introspect_mysql(conn: Connection, key_manager: Any) -> dict[str, Any]:
    """
    Introspect MySQL schema via information_schema using aiomysql.

    Returns:
        {table_name: {columns: {col_name: {type, nullable, primary_key}}}}
    """
    try:
        import aiomysql
    except ImportError:
        log.error("schema_reader.mysql_import_failed", connection_id=str(conn.id))
        return {}

    import json as _json

    try:
        creds = _json.loads(
            key_manager.decrypt(conn.encrypted_credentials, KeyPurpose.DB_CREDENTIALS)
        )
    except Exception as exc:
        log.error("schema_reader.decrypt_failed", connection_id=str(conn.id), error=str(exc))
        return {}

    db_conn = None
    try:
        db_conn = await aiomysql.connect(
            host=conn.host,
            port=conn.port or 3306,
            db=conn.database_name,
            user=creds["username"],
            password=creds["password"],
            connect_timeout=10,
            charset="utf8mb4",
        )

        async with db_conn.cursor(aiomysql.DictCursor) as cursor:
            # Get tables
            await cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s AND table_type = 'BASE TABLE' "
                "ORDER BY table_name",
                (conn.database_name,),
            )
            tables = await cursor.fetchall()

            if not tables:
                return {}

            # Get columns with PK info
            await cursor.execute(
                "SELECT c.table_name, c.column_name, c.data_type, c.is_nullable, "
                "c.column_key "
                "FROM information_schema.columns c "
                "WHERE c.table_schema = %s "
                "ORDER BY c.table_name, c.ordinal_position",
                (conn.database_name,),
            )
            columns = await cursor.fetchall()

        schema_data: dict[str, Any] = {}
        for t in tables:
            schema_data[t["table_name"]] = {"columns": {}}

        for col in columns:
            tbl = col["table_name"]
            if tbl in schema_data:
                schema_data[tbl]["columns"][col["column_name"]] = {
                    "type": col["data_type"],
                    "nullable": col["is_nullable"] == "YES",
                    "primary_key": col["column_key"] == "PRI",
                }

        log.info(
            "schema_reader.mysql_success",
            connection_id=str(conn.id),
            table_count=len(schema_data),
            column_count=sum(len(t["columns"]) for t in schema_data.values()),
        )
        return schema_data

    except Exception as exc:
        log.error("schema_reader.mysql_failed", connection_id=str(conn.id), error=str(exc))
        return {}

    finally:
        if db_conn is not None:
            try:
                db_conn.close()
            except Exception:
                pass


async def introspect_bigquery(conn: Connection, key_manager: Any) -> dict[str, Any]:
    """
    Introspect BigQuery dataset schema.

    Credential format in encrypted_credentials:
        {"project_id": "...", "dataset": "...", "service_account_json": {...}}

    Returns:
        {table_name: {columns: {col_name: {type, nullable, primary_key}}}}
    """
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account as sa_mod
    except ImportError:
        log.error("schema_reader.bigquery_import_failed", connection_id=str(conn.id))
        return {}

    import json as _json

    try:
        creds = _json.loads(
            key_manager.decrypt(conn.encrypted_credentials, KeyPurpose.DB_CREDENTIALS)
        )
    except Exception as exc:
        log.error("schema_reader.decrypt_failed", connection_id=str(conn.id), error=str(exc))
        return {}

    try:
        import asyncio

        project_id = creds.get("project_id", conn.database_name or "")
        dataset_id = creds.get("dataset", "")
        sa_json = creds.get("service_account_json")

        credentials = None
        if sa_json:
            credentials = sa_mod.Credentials.from_service_account_info(
                sa_json,
                scopes=["https://www.googleapis.com/auth/bigquery.readonly"],
            )

        client = bigquery.Client(project=project_id, credentials=credentials)
        loop = asyncio.get_event_loop()

        dataset_ref = f"{project_id}.{dataset_id}"
        bq_tables = await loop.run_in_executor(
            None, lambda: list(client.list_tables(dataset_ref))
        )

        if not bq_tables:
            return {}

        schema_data: dict[str, Any] = {}

        for bq_table in bq_tables:
            full_table = await loop.run_in_executor(
                None, lambda t=bq_table: client.get_table(t.reference)
            )
            cols: dict[str, Any] = {}
            for field in full_table.schema:
                cols[field.name] = {
                    "type": field.field_type.lower(),
                    "nullable": field.mode != "REQUIRED",
                    "primary_key": False,  # BigQuery has no PK concept
                }
            schema_data[bq_table.table_id] = {"columns": cols}

        log.info(
            "schema_reader.bigquery_success",
            connection_id=str(conn.id),
            table_count=len(schema_data),
            column_count=sum(len(t["columns"]) for t in schema_data.values()),
        )
        return schema_data

    except Exception as exc:
        log.error("schema_reader.bigquery_failed", connection_id=str(conn.id), error=str(exc))
        return {}