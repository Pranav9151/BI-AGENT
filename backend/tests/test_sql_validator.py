"""
Smart BI Agent — SQL Validator Unit Tests
Covers all 10 validation steps.
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.sql_validator import validate_sql, ValidationResult
from app.errors.exceptions import SQLValidationError


ALLOWED = {"orders", "customers", "products", "employees", "departments"}


class TestStep1Parse:
    def test_valid_select(self):
        r = validate_sql("SELECT * FROM orders", ALLOWED)
        assert r.valid
        assert "orders" in r.sql.lower()

    def test_empty_sql(self):
        with pytest.raises(SQLValidationError):
            validate_sql("", ALLOWED)

    def test_invalid_syntax(self):
        with pytest.raises(SQLValidationError):
            validate_sql("SELCT * FORM orders", ALLOWED)


class TestStep2MultiStatement:
    def test_single_statement(self):
        r = validate_sql("SELECT 1", set())
        assert r.valid

    def test_multi_statement_blocked(self):
        with pytest.raises(SQLValidationError, match="single SELECT"):
            validate_sql("SELECT 1; SELECT 2", set())


class TestStep3BlockDDL:
    @pytest.mark.parametrize("sql", [
        "DROP TABLE orders",
        "CREATE TABLE hack (id int)",
        "ALTER TABLE orders ADD COLUMN x int",
        "INSERT INTO orders VALUES (1)",
        "UPDATE orders SET status = 'x'",
        "DELETE FROM orders",
        "TRUNCATE orders",
    ])
    def test_ddl_dml_blocked(self, sql):
        with pytest.raises(SQLValidationError):
            validate_sql(sql, ALLOWED)

    def test_select_allowed(self):
        r = validate_sql("SELECT id FROM orders", ALLOWED)
        assert r.valid


class TestStep4TableVerification:
    def test_allowed_table(self):
        r = validate_sql("SELECT * FROM orders", ALLOWED)
        assert r.valid
        assert "orders" in r.tables_referenced

    def test_unauthorized_table(self):
        with pytest.raises(SQLValidationError, match="don't have access"):
            validate_sql("SELECT * FROM secret_data", ALLOWED)

    def test_case_insensitive(self):
        r = validate_sql("SELECT * FROM Orders", ALLOWED)
        assert r.valid

    def test_empty_allowed_skips_check(self):
        r = validate_sql("SELECT * FROM anything", set())
        assert r.valid


class TestStep5LimitInjection:
    def test_limit_injected(self):
        r = validate_sql("SELECT * FROM orders", ALLOWED)
        assert r.limit_injected
        assert "LIMIT" in r.sql.upper()

    def test_existing_limit_preserved(self):
        r = validate_sql("SELECT * FROM orders LIMIT 5", ALLOWED)
        assert "5" in r.sql

    def test_excessive_limit_capped(self):
        r = validate_sql("SELECT * FROM orders LIMIT 999999", ALLOWED, max_rows=100)
        assert r.limit_injected
        assert "100" in r.sql


class TestStep6SystemCatalogs:
    @pytest.mark.parametrize("sql", [
        "SELECT * FROM pg_catalog.pg_class",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM pg_shadow",
        "SELECT * FROM pg_roles",
        "SELECT * FROM pg_settings",
    ])
    def test_system_catalogs_blocked(self, sql):
        with pytest.raises(SQLValidationError, match="system catalog"):
            validate_sql(sql, set())


class TestStep7DangerousFunctions:
    @pytest.mark.parametrize("sql,dialect", [
        ("SELECT pg_read_file('/etc/passwd')", "postgres"),
        ("SELECT pg_sleep(10)", "postgres"),
        ("SELECT dblink('host=evil')", "postgres"),
        ("SELECT lo_import('/etc/passwd')", "postgres"),
    ])
    def test_postgres_functions_blocked(self, sql, dialect):
        with pytest.raises(SQLValidationError, match="blocked"):
            validate_sql(sql, set(), dialect=dialect)

    @pytest.mark.parametrize("sql", [
        "SELECT LOAD_FILE('/etc/passwd')",
        "SELECT * FROM t INTO OUTFILE '/tmp/x'",
    ])
    def test_mysql_patterns_blocked(self, sql):
        with pytest.raises(SQLValidationError, match="blocked"):
            validate_sql(sql, set(), dialect="mysql")

    def test_safe_functions_allowed(self):
        r = validate_sql("SELECT COUNT(*), SUM(amount) FROM orders", ALLOWED)
        assert r.valid


class TestStep8CTEValidation:
    def test_simple_cte(self):
        sql = "WITH t AS (SELECT * FROM orders) SELECT * FROM t"
        r = validate_sql(sql, ALLOWED)
        assert r.valid

    def test_excessive_ctes(self):
        ctes = ", ".join(f"t{i} AS (SELECT {i})" for i in range(6))
        sql = f"WITH {ctes} SELECT * FROM t0"
        with pytest.raises(SQLValidationError, match="too many CTEs"):
            validate_sql(sql, set())


class TestStep9ColumnPermissions:
    def test_denied_column_blocked(self):
        with pytest.raises(SQLValidationError, match="column"):
            validate_sql(
                "SELECT salary FROM employees",
                ALLOWED,
                denied_columns={"salary"},
            )

    def test_allowed_column_passes(self):
        r = validate_sql(
            "SELECT name FROM employees",
            ALLOWED,
            denied_columns={"salary"},
        )
        assert r.valid


class TestStep10JoinCheck:
    def test_simple_join_ok(self):
        r = validate_sql(
            "SELECT o.id FROM orders o JOIN customers c ON o.customer_id = c.id",
            ALLOWED,
        )
        assert r.valid

    def test_many_joins_warning(self):
        sql = (
            "SELECT * FROM orders o "
            "JOIN customers c ON o.cid = c.id "
            "JOIN products p ON o.pid = p.id "
            "JOIN employees e ON o.eid = e.id "
            "JOIN departments d ON e.did = d.id "
            "JOIN orders o2 ON o.id = o2.id"
        )
        r = validate_sql(sql, ALLOWED)
        assert r.valid
        assert any("JOIN" in w for w in r.warnings)


class TestDialects:
    def test_postgres_dialect(self):
        r = validate_sql("SELECT * FROM orders", ALLOWED, dialect="postgres")
        assert r.valid

    def test_mysql_dialect(self):
        r = validate_sql("SELECT * FROM orders", ALLOWED, dialect="mysql")
        assert r.valid

    def test_bigquery_dialect(self):
        r = validate_sql("SELECT * FROM orders", ALLOWED, dialect="bigquery")
        assert r.valid