"""FastMCP server entry. Registers seven tools.

Tools:
  list_servers              -- enumerate configured servers
  list_databases            -- list databases on a server
  list_tables               -- list tables in a database
  describe_table            -- columns/types/nullability for a table
  get_table_sample          -- SELECT TOP n / LIMIT n
  run_query                 -- arbitrary SELECT, three-layer safety
  explain_query             -- execution plan for a query
  search_objects            -- find tables/columns by name fragment

All tools accept an optional `server` parameter to target a specific
server from servers.yaml; default_server is used when omitted.
"""

from __future__ import annotations

import time

from dotenv import load_dotenv
from fastmcp import FastMCP
from pydantic import Field

from sql_explorer_mcp import __version__
from sql_explorer_mcp.config import load_config
from sql_explorer_mcp.engines import execute_select
from sql_explorer_mcp.introspection import (
    describe_table_sql,
    explain_query_sql,
    get_table_sample_sql,
    list_databases_sql,
    list_tables_sql,
    search_objects_sql,
)
from sql_explorer_mcp.safety import validate_query
from sql_explorer_mcp.audit import record_query

load_dotenv()

mcp = FastMCP("sql-explorer-mcp")
_config = None


def _get_config():
    global _config
    if _config is None:
        _config = load_config()
    return _config


@mcp.tool()
def list_servers() -> dict:
    """List all configured database servers from servers.yaml.

    Returns a dict with the configured server names, their dialect
    (mssql / postgres / sqlite), and which one is the default.
    """
    cfg = _get_config()
    return {
        "default_server": cfg.default_server,
        "servers": [
            {
                "name": s.name,
                "dialect": s.dialect,
                "host": s.host,
                "database": s.database,
            }
            for s in cfg.servers.values()
        ],
        "version": __version__,
    }


@mcp.tool()
def list_databases(server: str | None = Field(default=None, description="Server name from servers.yaml; omit for default")) -> list[dict]:
    """List databases visible on a given server (mssql/postgres only -- sqlite returns the single attached file)."""
    cfg = _get_config()
    s = cfg.get_server(server)
    sql = list_databases_sql(s.dialect)
    return execute_select(s, sql)


@mcp.tool()
def list_tables(
    server: str | None = Field(default=None),
    database: str | None = Field(default=None, description="(mssql/postgres) override the database in the connection"),
    schema: str | None = Field(default=None, description="Filter by schema (e.g. 'dbo' for mssql, 'public' for postgres)"),
) -> list[dict]:
    """List tables on a server, optionally filtered by schema."""
    cfg = _get_config()
    s = cfg.get_server(server)
    # If a database is given and differs from server.database, swap it in
    if database and database != s.database:
        from dataclasses import replace
        s = replace(s, database=database)
    sql, params = list_tables_sql(s.dialect, schema)
    return execute_select(s, sql, params)


@mcp.tool()
def describe_table(
    table: str,
    server: str | None = Field(default=None),
    schema: str | None = Field(default=None),
) -> list[dict]:
    """Return column metadata for a table: name, type, nullability, default."""
    cfg = _get_config()
    s = cfg.get_server(server)
    sql, params = describe_table_sql(s.dialect, table, schema)
    return execute_select(s, sql, params)


@mcp.tool()
def get_table_sample(
    table: str,
    n: int = Field(default=10, ge=1, le=1000),
    server: str | None = Field(default=None),
    schema: str | None = Field(default=None),
) -> list[dict]:
    """Return the first n rows of a table. n is clamped to 1-1000."""
    cfg = _get_config()
    s = cfg.get_server(server)
    sql, params = get_table_sample_sql(s.dialect, table, schema, n)
    return execute_select(s, sql, params)


@mcp.tool()
def run_query(
    sql: str,
    server: str | None = Field(default=None),
) -> dict:
    """Execute an arbitrary SELECT against a server.

    Three-layer safety stack:
      1. Connection is read-only (driver-enforced)
      2. sqlglot parses the SQL and rejects anything that isn't a SELECT
      3. sql-sop linter rejects queries with error-severity findings;
         warnings are returned alongside results as advisory output

    Result rows are capped at the server's max_rows (default 1000).

    Returns: {passed: bool, rows: [...], rowcount: int, warnings: [...]}
    Failure: {passed: false, layer: 'select-only'|'sql-sop-error'|'parse', reason: str}
    """
    cfg = _get_config()
    s = cfg.get_server(server)
    safety = validate_query(sql, dialect=s.dialect)
    if not safety.passed:
        record_query(sql, s.name, outcome="blocked", meta={"layer": safety.layer, "reason": safety.reason})
        return {
            "passed": False,
            "layer": safety.layer,
            "reason": safety.reason,
            "warnings": safety.sqlsop_findings,
        }
    start = time.perf_counter()
    try:
        rows = execute_select(s, sql)
    except Exception as exc:
        record_query(sql, s.name, outcome="error", meta={"error": str(exc)[:200], "ms": round((time.perf_counter() - start) * 1000)})
        raise
    record_query(sql, s.name, outcome="ok", meta={"rows": len(rows), "ms": round((time.perf_counter() - start) * 1000)})
    return {
        "passed": True,
        "rows": rows,
        "rowcount": len(rows),
        "warnings": safety.sqlsop_findings,
    }


@mcp.tool()
def explain_query(
    sql: str,
    server: str | None = Field(default=None),
) -> list[dict]:
    """Return the execution plan for a query (without running it for results).

    Engine-specific:
      mssql:    SET SHOWPLAN_TEXT ON + the query (text plan)
      postgres: EXPLAIN (FORMAT JSON) + the query (JSON plan)
      sqlite:   EXPLAIN QUERY PLAN + the query
    """
    cfg = _get_config()
    s = cfg.get_server(server)
    # Validate the underlying query first -- only explain SELECTs
    safety = validate_query(sql, dialect=s.dialect)
    if not safety.passed:
        return [{"error": safety.reason, "layer": safety.layer}]
    plan_sql = explain_query_sql(s.dialect, sql)
    try:
        return execute_select(s, plan_sql)
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
def search_objects(
    query: str,
    server: str | None = Field(default=None),
) -> list[dict]:
    """Search for tables and columns whose names match a fragment.

    Returns rows like {object_type: 'TABLE'|'COLUMN', schema_name, object_name, column_name}.
    """
    cfg = _get_config()
    s = cfg.get_server(server)
    sql, params = search_objects_sql(s.dialect, query)
    return execute_select(s, sql, params)


def main():
    """Entry point for the sql-explorer-mcp script."""
    mcp.run()


if __name__ == "__main__":
    main()
