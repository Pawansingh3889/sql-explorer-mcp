"""Tests for the three-layer safety stack.

Layer 1 (read-only connection) is tested elsewhere via engine integration.
This file covers layers 2 (sqlglot SELECT-only) and 3 (sql-sop linter).
"""

from __future__ import annotations

import pytest

from sql_explorer_mcp.safety import (
    SafetyResult,
    lint_with_sql_sop,
    validate_query,
    validate_select_only,
)


# ---------------------------------------------------------------------------
# Layer 2: SELECT-only validation
# ---------------------------------------------------------------------------


class TestSelectOnly:
    def test_plain_select_passes(self):
        r = validate_select_only("SELECT * FROM users WHERE id = 1")
        assert r.passed

    def test_cte_with_select_passes(self):
        r = validate_select_only(
            "WITH active AS (SELECT id FROM users WHERE active = 1) "
            "SELECT * FROM active"
        )
        assert r.passed

    def test_union_passes(self):
        r = validate_select_only(
            "SELECT id FROM users UNION ALL SELECT id FROM customers"
        )
        assert r.passed

    def test_insert_rejected(self):
        r = validate_select_only("INSERT INTO users (id) VALUES (1)")
        assert not r.passed
        assert r.layer == "select-only"

    def test_update_rejected(self):
        r = validate_select_only("UPDATE users SET active = 0 WHERE id = 1")
        assert not r.passed
        assert r.layer == "select-only"

    def test_delete_rejected(self):
        r = validate_select_only("DELETE FROM users WHERE id = 1")
        assert not r.passed
        assert r.layer == "select-only"

    def test_drop_rejected(self):
        r = validate_select_only("DROP TABLE users")
        assert not r.passed
        assert r.layer == "select-only"

    def test_create_rejected(self):
        r = validate_select_only("CREATE TABLE t (id INT)")
        assert not r.passed
        assert r.layer == "select-only"

    def test_alter_rejected(self):
        r = validate_select_only("ALTER TABLE users ADD COLUMN email TEXT")
        assert not r.passed
        assert r.layer == "select-only"

    def test_multiple_statements_rejected(self):
        r = validate_select_only("SELECT 1; SELECT 2;")
        assert not r.passed
        assert r.layer == "select-only"

    def test_smuggled_delete_in_cte_rejected(self):
        # The classic attack: hide a DELETE inside a CTE
        r = validate_select_only(
            "WITH evil AS (DELETE FROM users RETURNING id) SELECT * FROM evil",
            dialect="postgres",
        )
        assert not r.passed

    def test_unparseable_sql_fails(self):
        r = validate_select_only("SELEC * FROM where junk")
        assert not r.passed
        assert r.layer == "parse"


# ---------------------------------------------------------------------------
# Layer 3: sql-sop linter integration
# ---------------------------------------------------------------------------


class TestSqlSopIntegration:
    def test_clean_select_returns_empty_warnings(self):
        r = lint_with_sql_sop("SELECT id, name FROM users WHERE active = 1 LIMIT 10")
        assert r.passed
        # Some W-level findings may fire; they're warnings, not errors
        assert all(f["severity"] != "error" for f in r.sqlsop_findings)

    def test_warnings_pass_but_are_returned(self):
        # SELECT * triggers W001
        r = lint_with_sql_sop("SELECT * FROM users")
        assert r.passed  # warnings don't block
        assert any(f["rule_id"] == "W001" for f in r.sqlsop_findings)


# ---------------------------------------------------------------------------
# Combined validate_query
# ---------------------------------------------------------------------------


class TestValidateQuery:
    def test_clean_select_passes(self):
        r = validate_query("SELECT id FROM users WHERE active = 1 LIMIT 10")
        assert r.passed

    def test_dml_blocked_at_layer_2(self):
        r = validate_query("DELETE FROM users")
        assert not r.passed
        assert r.layer == "select-only"

    def test_select_with_only_warnings_passes(self):
        r = validate_query("SELECT * FROM users")
        assert r.passed
        assert len(r.sqlsop_findings) > 0  # warnings present
