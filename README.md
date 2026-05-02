# sql-explorer-mcp

[![PyPI](https://img.shields.io/pypi/v/sql-explorer-mcp)](https://pypi.org/project/sql-explorer-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/sql-explorer-mcp)](https://pypi.org/project/sql-explorer-mcp/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Read-only Model Context Protocol server for SQL databases. Lets LLMs (Claude, Cursor, ChatGPT, Continue) introspect and query **SQL Server, Postgres, and SQLite** with three layers of safety:

1. **Connection-level read-only** — `pyodbc readonly=True`, Postgres `SET TRANSACTION READ ONLY`
2. **AST validation** — sqlglot parses every query and rejects anything that isn't a `SELECT` (catches DML smuggled in CTEs)
3. **Linter pass** — [sql-sop](https://pypi.org/project/sql-sop/) checks every query and rejects error-severity findings; warnings are surfaced to the LLM as advisory output

Multi-server: configure several databases in one `servers.yaml`, the LLM picks which one to target per call.

## Tools exposed to the LLM

| Tool | Purpose |
|---|---|
| `list_servers()` | Enumerate configured servers + their dialect |
| `list_databases(server?)` | List databases on a server |
| `list_tables(server?, database?, schema?)` | List tables, optionally filtered by schema |
| `describe_table(table, server?, schema?)` | Columns, types, nullability, defaults |
| `get_table_sample(table, n=10, server?, schema?)` | Quick `SELECT TOP n / LIMIT n` |
| `run_query(sql, server?)` | Execute arbitrary SELECT — three-layer safety stack |
| `explain_query(sql, server?)` | Return execution plan (engine-specific) |
| `search_objects(query, server?)` | Find tables and columns by name fragment |

All tools accept an optional `server` to target a specific entry from `servers.yaml`. Default server is used when omitted.

## Install

```bash
pip install sql-explorer-mcp
# or
pipx install sql-explorer-mcp
```

For SQL Server, install [Microsoft ODBC Driver 18](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server). Postgres and SQLite drivers ship as dependencies.

## Configure

Copy `servers.example.yaml` to `servers.yaml` and edit. Passwords are read from environment variables, never stored in the file.

```yaml
default_server: lab

servers:
  lab:
    dialect: mssql
    host: localhost
    port: 1433
    database: BusinessLab
    auth: sql
    username: sa
    password_env: SQL_EXPLORER_LAB_PASSWORD

  production:
    dialect: mssql
    host: BUSINESS-SQL
    database: SI
    auth: windows               # uses Trusted_Connection
    max_rows: 500

  warehouse:
    dialect: postgres
    host: db.internal
    database: warehouse
    username: readonly
    password_env: WAREHOUSE_PG_PASSWORD
```

The config file is searched in this order:
1. `$SQL_EXPLORER_CONFIG` if set
2. `./servers.yaml` (current directory)
3. `~/.sql-explorer-mcp/servers.yaml`

## Run

### As an MCP server for Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (Mac) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "sql-explorer": {
      "command": "sql-explorer-mcp",
      "env": {
        "SQL_EXPLORER_CONFIG": "/full/path/to/servers.yaml",
        "SQL_EXPLORER_LAB_PASSWORD": "your-lab-password"
      }
    }
  }
}
```

Restart Claude Desktop. The seven tools appear under Settings → Tools.

### As an MCP server for Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "sql-explorer": {
      "command": "sql-explorer-mcp",
      "env": { "SQL_EXPLORER_CONFIG": "/full/path/to/servers.yaml" }
    }
  }
}
```

### Standalone (debug)

```bash
sql-explorer-mcp
```

Reads stdin/stdout in MCP protocol. Use the [MCP Inspector](https://github.com/modelcontextprotocol/inspector) to test interactively:

```bash
npx @modelcontextprotocol/inspector sql-explorer-mcp
```

## Safety architecture

```
LLM submits SQL
       │
       ▼
┌──────────────────┐
│ Layer 2 (sqlglot)│  Parse, reject if not exactly one SELECT
└────────┬─────────┘  Catches: INSERT, UPDATE, DELETE, MERGE, EXEC,
         │            CREATE, DROP, ALTER, smuggled DML in CTEs,
         │            multiple statements
         ▼
┌──────────────────┐
│ Layer 3 (sql-sop)│  Lint, reject if any error-severity findings
└────────┬─────────┘  Warnings (W*) returned as advisory output,
         │            don't block execution.
         ▼
┌──────────────────┐
│ Layer 1 (driver) │  pyodbc readonly=True / Postgres SET TXN READ ONLY
└────────┬─────────┘  Final defence at the protocol layer.
         ▼
   Database
         │
         ▼
   Result rows (capped at server.max_rows)
```

Failure at any layer returns a structured result the LLM can read and react to:

```json
{
  "passed": false,
  "layer": "select-only",
  "reason": "Forbidden statement type in query: Delete"
}
```

## Why this design

- **Read-only by enforcement, not convention.** A misconfigured login isn't your only protection.
- **Multi-engine from day 1.** Same tool surface across SQL Server, Postgres, SQLite. Same `servers.yaml`.
- **Multi-server in one process.** Switch between lab and production by passing `server="production"` instead of restarting.
- **Linter-aware.** Uses [sql-sop](https://pypi.org/project/sql-sop/) to flag patterns that compile fine but signal poor query habits (SELECT *, unbounded queries, etc.).
- **Result caps.** Every tool clamps row counts (max 1000 default) so a curious LLM can't pull 100k rows into context.

## Comparison to other SQL MCP servers

| Server | Dialects | Read-only | Linter pass | Multi-server |
|---|---|---|---|---|
| sql-explorer-mcp | mssql, postgres, sqlite | ✓ (3 layers) | ✓ via sql-sop | ✓ |
| various community mssql-mcp | mssql | depends | ✗ | usually ✗ |
| various postgres-mcp | postgres | depends | ✗ | usually ✗ |

## Development

```bash
git clone https://github.com/Pawansingh3889/sql-explorer-mcp
cd sql-explorer-mcp
pip install -e ".[dev]"
pytest -v
```

## License

MIT
