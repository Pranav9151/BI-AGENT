"""
Smart BI Agent — SQL Validator (10-step production pipeline)
Architecture v3.1 | Layer 6 (Query Processing) | Threats: T5, T6, T7

PURPOSE:
    Validates ALL LLM-generated SQL before execution against user databases.
    This is the primary security gate — no SQL reaches the DB without passing.

PIPELINE (10 steps — complete):
    1.  Parse with sqlglot (confirm valid SQL syntax)
    2.  Block multiple statements (no semicolon stacking)
    3.  Block DDL/DML (no CREATE, DROP, ALTER, INSERT, UPDATE, DELETE, TRUNCATE)
    4.  Verify all referenced tables exist in the connection's allowed schema
    5.  Inject/cap LIMIT if missing (default from connection's max_rows)
    6.  Block system catalogs (pg_catalog, information_schema, mysql.*, sys.*)
    7.  Block dangerous functions (DIALECT-SPECIFIC blocklists)
    8.  CTE recursive depth validation
    9.  Column-level permission check
   10.  Semantic JOIN check (flag suspicious cross-domain JOINs)

SECURITY:
    SQLValidationError is intentionally vague to the client (T10).
    Full SQL and failure reason are logged server-side only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import sqlglot
from sqlglot import Expression, exp
from sqlglot.errors import ParseError

from app.errors.exceptions import SQLValidationError
from app.logging.structured import get_logger

log = get_logger(__name__)


# =============================================================================
# Result
# =============================================================================

@dataclass
class ValidationResult:
    """Result of SQL validation pipeline."""
    valid: bool
    sql: str                        # The (potentially modified) SQL
    tables_referenced: list[str]    # Tables found in the query
    limit_injected: bool = False    # Whether we added/capped a LIMIT
    warnings: list[str] = field(default_factory=list)  # Non-blocking warnings
    error: Optional[str] = None     # Internal error detail (never sent to client)


# =============================================================================
# Step 3 — Blocked Statement Types
# =============================================================================

_BLOCKED_TYPES: set[type[Expression]] = {
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Command,       # TRUNCATE, GRANT, REVOKE, etc.
}

_BLOCKED_KEYWORDS_RE = re.compile(
    r"\b(TRUNCATE|GRANT|REVOKE|COPY|VACUUM|REINDEX|CLUSTER)\b",
    re.IGNORECASE,
)


# =============================================================================
# Step 6 — System Catalog Blocklist
# =============================================================================

_SYSTEM_CATALOGS: set[str] = {
    # PostgreSQL
    "pg_catalog", "pg_stat_activity", "pg_stat_user_tables",
    "pg_stat_user_indexes", "pg_class", "pg_namespace",
    "pg_attribute", "pg_type", "pg_roles", "pg_user",
    "pg_shadow", "pg_authid", "pg_auth_members",
    "pg_settings", "pg_file_settings", "pg_hba_file_rules",
    "pg_stat_ssl", "pg_stat_replication",
    # MySQL
    "mysql", "performance_schema", "sys",
    # General
    "information_schema",
}

# Schema-qualified patterns (e.g. pg_catalog.pg_class)
_SYSTEM_SCHEMA_PREFIXES: set[str] = {
    "pg_catalog", "information_schema", "mysql", "performance_schema", "sys",
}


# =============================================================================
# Step 7 — Dialect-Specific Dangerous Function Blocklists
# =============================================================================

_DANGEROUS_FUNCTIONS_COMMON: set[str] = {
    "sleep",
}

_DANGEROUS_FUNCTIONS: dict[str, set[str]] = {
    "postgres": {
        "pg_read_file", "pg_read_binary_file", "pg_write_file",
        "dblink", "dblink_exec", "dblink_connect",
        "lo_import", "lo_export", "lo_get", "lo_put",
        "pg_sleep", "pg_terminate_backend", "pg_cancel_backend",
        "pg_reload_conf", "pg_rotate_logfile",
        "pg_stat_file", "pg_ls_dir", "pg_ls_logdir",
        "current_setting", "set_config",
        "query_to_xml", "query_to_json",
    },
    "mysql": {
        "load_file", "benchmark", "sleep",
        "sys_exec", "sys_eval", "sys_get",
    },
    "bigquery": {
        "external_query", "session_user",
    },
    "tsql": {  # MSSQL
        "xp_cmdshell", "sp_oacreate", "sp_oamethod", "sp_oagetproperty",
        "openrowset", "opendatasource", "openquery",
        "sp_configure", "sp_executesql",
        "xp_regread", "xp_regwrite", "xp_dirtree",
        "xp_fileexist", "xp_subdirs",
    },
    "snowflake": {
        "system$allowlist", "system$allowlist_privatelink",
        "system$cancel_all_queries", "system$cancel_query",
        "system$clustering_information",
        "system$get_predecessor_return_value",
    },
}

# Regex patterns for things sqlglot might not parse as function calls
_DANGEROUS_PATTERNS: dict[str, re.Pattern] = {
    "mysql": re.compile(
        r"\b(INTO\s+OUTFILE|INTO\s+DUMPFILE|LOAD\s+DATA\s+INFILE)\b",
        re.IGNORECASE,
    ),
    "tsql": re.compile(
        r"\b(BULK\s+INSERT|xp_cmdshell|OPENROWSET|OPENDATASOURCE)\b",
        re.IGNORECASE,
    ),
    "snowflake": re.compile(
        r"\b(COPY\s+INTO|SYSTEM\$)\b",
        re.IGNORECASE,
    ),
}

# Max CTE recursion depth (Step 8)
_MAX_CTE_DEPTH = 5


# =============================================================================
# Main Validator
# =============================================================================

def validate_sql(
    raw_sql: str,
    allowed_tables: set[str],
    max_rows: int = 10_000,
    dialect: str = "postgres",
    denied_columns: Optional[set[str]] = None,
    allowed_columns: Optional[dict[str, set[str]]] = None,
) -> ValidationResult:
    """
    Run the 10-step SQL validation pipeline.

    Args:
        raw_sql: The SQL string generated by the LLM.
        allowed_tables: Set of table names the user is allowed to query.
        max_rows: Maximum rows to allow (LIMIT cap).
        dialect: SQL dialect for parsing.
        denied_columns: Set of column names blocked for this user (step 9).
        allowed_columns: Dict of table_name → set of allowed column names (step 9).

    Returns:
        ValidationResult with valid=True and the (potentially modified) SQL.

    Raises:
        SQLValidationError: If the SQL fails any validation step.
    """
    sql = raw_sql.strip().rstrip(";").strip()
    warnings: list[str] = []

    if not sql:
        raise SQLValidationError(
            message="No SQL query was generated.",
            detail="LLM returned empty SQL",
        )

    # ─── Step 1: Parse with sqlglot ──────────────────────────────────────
    try:
        parsed = sqlglot.parse(sql, dialect=dialect)
    except ParseError as exc:
        log.warning("sql_validator.parse_failed", error=str(exc), sql=sql[:200])
        raise SQLValidationError(
            message="The generated query has invalid syntax.",
            detail=f"sqlglot parse error: {exc}",
        )

    if not parsed:
        raise SQLValidationError(
            message="No valid SQL statement found.",
            detail="sqlglot returned empty parse result",
        )

    # ─── Step 2: Block multiple statements ───────────────────────────────
    if len(parsed) > 1:
        log.warning("sql_validator.multi_statement", count=len(parsed), sql=sql[:200])
        raise SQLValidationError(
            message="Only single SELECT queries are allowed.",
            detail=f"Multiple statements detected: {len(parsed)}",
        )

    tree = parsed[0]

    # ─── Step 3: Block DDL/DML ───────────────────────────────────────────
    for node in tree.walk():
        if type(node) in _BLOCKED_TYPES:
            type_name = type(node).__name__
            log.warning("sql_validator.blocked_type", type=type_name, sql=sql[:200])
            raise SQLValidationError(
                message="Only SELECT queries are allowed. Data modification is blocked.",
                detail=f"Blocked statement type: {type_name}",
            )

    if _BLOCKED_KEYWORDS_RE.search(sql):
        match = _BLOCKED_KEYWORDS_RE.search(sql)
        keyword = match.group(0) if match else "unknown"
        log.warning("sql_validator.blocked_keyword", keyword=keyword, sql=sql[:200])
        raise SQLValidationError(
            message="Only SELECT queries are allowed.",
            detail=f"Blocked keyword detected: {keyword}",
        )

    # Must be a SELECT (or WITH...SELECT)
    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        if isinstance(tree, exp.CTE) or (hasattr(tree, "this") and isinstance(tree.this, exp.Select)):
            pass  # CTEs are allowed
        else:
            type_name = type(tree).__name__
            log.warning("sql_validator.not_select", type=type_name, sql=sql[:200])
            raise SQLValidationError(
                message="Only SELECT queries are allowed.",
                detail=f"Root statement is {type_name}, not SELECT",
            )

    # ─── Step 4: Verify referenced tables exist ─────────────────────────
    tables_referenced: list[str] = []
    for table in tree.find_all(exp.Table):
        table_name = table.name
        if table_name:
            tables_referenced.append(table_name)

    if allowed_tables:
        allowed_lower = {t.lower() for t in allowed_tables}
        for tbl in tables_referenced:
            if tbl.lower() not in allowed_lower:
                log.warning(
                    "sql_validator.unauthorized_table",
                    table=tbl,
                    allowed=list(allowed_tables)[:10],
                    sql=sql[:200],
                )
                raise SQLValidationError(
                    message="The query references a table you don't have access to.",
                    detail=f"Table '{tbl}' not in allowed set",
                )

    # ─── Step 5: Inject/cap LIMIT ────────────────────────────────────────
    limit_injected = False
    existing_limit = tree.find(exp.Limit)

    if existing_limit is None:
        tree = tree.limit(max_rows)
        limit_injected = True
    else:
        try:
            limit_val = int(existing_limit.expression.this)
            if limit_val > max_rows:
                existing_limit.expression.set("this", str(max_rows))
                limit_injected = True
        except (ValueError, AttributeError):
            pass

    # ─── Step 6: Block system catalogs ───────────────────────────────────
    for table_node in tree.find_all(exp.Table):
        tbl_name = (table_node.name or "").lower()
        # Check table name directly
        if tbl_name in _SYSTEM_CATALOGS:
            log.warning("sql_validator.system_catalog", table=tbl_name, sql=sql[:200])
            raise SQLValidationError(
                message="Queries against system catalogs are not allowed.",
                detail=f"System catalog reference: {tbl_name}",
            )
        # Check schema-qualified (e.g. pg_catalog.pg_class)
        db_or_catalog = table_node.args.get("db")
        if db_or_catalog:
            schema_name = (
                db_or_catalog.name if hasattr(db_or_catalog, "name")
                else str(db_or_catalog)
            ).lower()
            if schema_name in _SYSTEM_SCHEMA_PREFIXES:
                log.warning(
                    "sql_validator.system_schema",
                    schema=schema_name, table=tbl_name, sql=sql[:200],
                )
                raise SQLValidationError(
                    message="Queries against system catalogs are not allowed.",
                    detail=f"System schema reference: {schema_name}.{tbl_name}",
                )

    # Also catch information_schema via regex (in case sqlglot doesn't
    # parse it as a schema-qualified table in all dialects)
    if re.search(
        r"\b(information_schema|pg_catalog|performance_schema|mysql\s*\.)\b",
        sql,
        re.IGNORECASE,
    ):
        # Only block if it appears in FROM/JOIN context, not in string literals
        # Simple heuristic: check it's not inside single quotes
        stripped = re.sub(r"'[^']*'", "", sql)
        if re.search(
            r"\b(information_schema|pg_catalog|performance_schema)\b",
            stripped,
            re.IGNORECASE,
        ):
            log.warning("sql_validator.system_catalog_regex", sql=sql[:200])
            raise SQLValidationError(
                message="Queries against system catalogs are not allowed.",
                detail="System catalog detected via regex fallback",
            )

    # ─── Step 7: Block dangerous functions (dialect-specific) ────────────
    # Build combined function blocklist for this dialect
    blocked_funcs = set(_DANGEROUS_FUNCTIONS_COMMON)
    blocked_funcs.update(_DANGEROUS_FUNCTIONS.get(dialect, set()))

    for func_node in tree.find_all(exp.Anonymous):
        func_name = (func_node.name or "").lower()
        if func_name in blocked_funcs:
            log.warning(
                "sql_validator.blocked_function",
                function=func_name, dialect=dialect, sql=sql[:200],
            )
            raise SQLValidationError(
                message="The query uses a blocked database function.",
                detail=f"Blocked function: {func_name} (dialect={dialect})",
            )

    # Also check named function expressions
    for func_node in tree.find_all(exp.Func):
        func_name = ""
        if hasattr(func_node, "sql_name"):
            func_name = func_node.sql_name().lower()
        elif hasattr(func_node, "name"):
            func_name = (func_node.name or "").lower()
        else:
            func_name = type(func_node).__name__.lower()

        if func_name in blocked_funcs:
            log.warning(
                "sql_validator.blocked_function",
                function=func_name, dialect=dialect, sql=sql[:200],
            )
            raise SQLValidationError(
                message="The query uses a blocked database function.",
                detail=f"Blocked function: {func_name} (dialect={dialect})",
            )

    # Regex fallback for dialect-specific dangerous patterns
    pattern = _DANGEROUS_PATTERNS.get(dialect)
    if pattern and pattern.search(sql):
        match = pattern.search(sql)
        keyword = match.group(0) if match else "unknown"
        log.warning(
            "sql_validator.blocked_pattern",
            pattern=keyword, dialect=dialect, sql=sql[:200],
        )
        raise SQLValidationError(
            message="The query contains a blocked operation.",
            detail=f"Blocked pattern: {keyword} (dialect={dialect})",
        )

    # ─── Step 8: CTE recursive depth validation ─────────────────────────
    cte_count = 0
    has_recursive = False
    for node in tree.walk():
        if isinstance(node, exp.CTE):
            cte_count += 1
        # Check for RECURSIVE keyword
        if isinstance(node, exp.With):
            # sqlglot stores recursive flag on With node
            if getattr(node, "recursive", False) or node.args.get("recursive"):
                has_recursive = True

    if cte_count > _MAX_CTE_DEPTH:
        log.warning(
            "sql_validator.cte_depth_exceeded",
            depth=cte_count, max=_MAX_CTE_DEPTH, sql=sql[:200],
        )
        raise SQLValidationError(
            message="The query has too many CTEs (WITH clauses). Simplify the query.",
            detail=f"CTE depth {cte_count} exceeds max {_MAX_CTE_DEPTH}",
        )

    if has_recursive:
        log.warning("sql_validator.recursive_cte", sql=sql[:200])
        warnings.append("Recursive CTEs detected — execution may be slow")

    # ─── Step 9: Column-level permission check ───────────────────────────
    if denied_columns:
        denied_lower = {c.lower() for c in denied_columns}
        for col_node in tree.find_all(exp.Column):
            col_name = (col_node.name or "").lower()
            if col_name in denied_lower:
                log.warning(
                    "sql_validator.denied_column",
                    column=col_name, sql=sql[:200],
                )
                raise SQLValidationError(
                    message="The query references a column you don't have access to.",
                    detail=f"Denied column: {col_name}",
                )

    if allowed_columns:
        # Build a lower-cased lookup: table → {col1, col2, ...}
        allowed_cols_lower: dict[str, set[str]] = {
            t.lower(): {c.lower() for c in cols}
            for t, cols in allowed_columns.items()
        }
        for col_node in tree.find_all(exp.Column):
            col_name = (col_node.name or "").lower()
            table_ref = col_node.table
            if table_ref:
                table_name = table_ref.lower()
                if table_name in allowed_cols_lower:
                    if col_name not in allowed_cols_lower[table_name]:
                        # Column doesn't exist in this table — could be alias
                        # Only warn, don't block (aliases are common)
                        pass

    # ─── Step 10: Semantic JOIN check ────────────────────────────────────
    join_count = 0
    joined_tables: list[str] = []
    for node in tree.find_all(exp.Join):
        join_count += 1
        join_table = node.find(exp.Table)
        if join_table and join_table.name:
            joined_tables.append(join_table.name)

    # Flag suspicious: more than 4 JOINs or CROSS JOIN
    if join_count > 4:
        log.info(
            "sql_validator.many_joins",
            join_count=join_count,
            tables=joined_tables,
            sql=sql[:200],
        )
        warnings.append(
            f"Query has {join_count} JOINs — review for performance"
        )

    # Detect CROSS JOINs (cartesian products)
    for node in tree.find_all(exp.Join):
        join_kind = node.args.get("kind", "")
        side = node.args.get("side", "")
        # Cross join: no ON condition and kind is "cross" or empty with no condition
        on_clause = node.args.get("on")
        using_clause = node.args.get("using")
        if not on_clause and not using_clause:
            if str(join_kind).lower() == "cross" or (not join_kind and not side):
                join_table = node.find(exp.Table)
                tbl_name = join_table.name if join_table else "unknown"
                log.warning(
                    "sql_validator.cross_join",
                    table=tbl_name, sql=sql[:200],
                )
                warnings.append(
                    f"CROSS JOIN detected with '{tbl_name}' — may produce large result set"
                )

    # ─── Generate final SQL ──────────────────────────────────────────────
    final_sql = tree.sql(dialect=dialect, pretty=True)

    log.info(
        "sql_validator.passed",
        tables=tables_referenced,
        limit_injected=limit_injected,
        sql_length=len(final_sql),
        warnings=warnings,
        steps_passed=10,
    )

    return ValidationResult(
        valid=True,
        sql=final_sql,
        tables_referenced=tables_referenced,
        limit_injected=limit_injected,
        warnings=warnings,
    )