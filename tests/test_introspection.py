"""Tests for the dialect-specific introspection query builders."""

from __future__ import annotations

import pytest

from sql_explorer_mcp.introspection import (
    describe_table_sql,
    explain_query_sql,
    get_table_sample_sql,
    list_databases_sql,
    list_tables_sql,
    search_objects_sql,
)


class TestListDatabases:
    @pytest.mark.parametrize("dialect", ["mssql", "postgres", "sqlite"])
    def test_returns_sql_for_each_dialect(self, dialect):
        sql = list_databases_sql(dialect)
        assert sql.upper().startswith("SELECT")

    def test_unknown_dialect_raises(self):
        with pytest.raises(ValueError):
            list_databases_sql("oracle")


class TestListTables:
    @pytest.mark.parametrize("dialect", ["mssql", "postgres", "sqlite"])
    def test_no_schema_filter(self, dialect):
        sql, params = list_tables_sql(dialect, None)
        assert sql.upper().startswith("SELECT")
        assert "schema" not in params

    @pytest.mark.parametrize("dialect", ["mssql", "postgres"])
    def test_with_schema_filter(self, dialect):
        sql, params = list_tables_sql(dialect, "dbo")
        assert ":schema" in sql
        assert params["schema"] == "dbo"


class TestDescribeTable:
    @pytest.mark.parametrize("dialect", ["mssql", "postgres"])
    def test_table_name_bound_as_param(self, dialect):
        sql, params = describe_table_sql(dialect, "InventoryBatch", "dbo")
        assert ":table" in sql
        assert params["table"] == "InventoryBatch"

    def test_sqlite_validates_table_name(self):
        # SQLite uses pragma which can't bind params; we validate the input
        with pytest.raises(ValueError):
            describe_table_sql("sqlite", "users; DROP TABLE x", None)

    def test_sqlite_safe_name(self):
        sql, params = describe_table_sql("sqlite", "users", None)
        assert "pragma_table_info" in sql.lower()


class TestGetTableSample:
    def test_mssql_uses_top(self):
        sql, _ = get_table_sample_sql("mssql", "InventoryBatch", "dbo", 5)
        assert "TOP (5)" in sql

    def test_postgres_uses_limit(self):
        sql, _ = get_table_sample_sql("postgres", "users", "public", 5)
        assert "LIMIT 5" in sql

    def test_sqlite_uses_limit(self):
        sql, _ = get_table_sample_sql("sqlite", "users", None, 5)
        assert "LIMIT 5" in sql

    def test_n_clamped_to_max(self):
        sql, _ = get_table_sample_sql("mssql", "t", None, 999999)
        assert "TOP (1000)" in sql

    def test_n_clamped_to_min(self):
        sql, _ = get_table_sample_sql("mssql", "t", None, 0)
        assert "TOP (1)" in sql

    def test_sqlite_rejects_dangerous_name(self):
        with pytest.raises(ValueError):
            get_table_sample_sql("sqlite", "users; DROP TABLE x", None, 10)


class TestExplainQuery:
    def test_mssql_uses_showplan(self):
        sql = explain_query_sql("mssql", "SELECT 1")
        assert "SHOWPLAN" in sql

    def test_postgres_uses_explain_json(self):
        sql = explain_query_sql("postgres", "SELECT 1")
        assert sql.startswith("EXPLAIN")
        assert "JSON" in sql

    def test_sqlite_uses_explain_query_plan(self):
        sql = explain_query_sql("sqlite", "SELECT 1")
        assert "EXPLAIN QUERY PLAN" in sql


class TestSearchObjects:
    @pytest.mark.parametrize("dialect", ["mssql", "postgres", "sqlite"])
    def test_pattern_bound_with_wildcards(self, dialect):
        sql, params = search_objects_sql(dialect, "inventory")
        assert params["pattern"] == "%inventory%"
