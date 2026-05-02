"""sql-explorer-mcp: Read-only MCP server for SQL databases.

Three engines (SQL Server, Postgres, SQLite), three safety layers
(read-only connection, sqlglot SELECT-only validation, sql-sop linter).
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sql-explorer-mcp")
except PackageNotFoundError:
    __version__ = "0.1.0"
