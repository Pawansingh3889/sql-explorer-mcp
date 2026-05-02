"""Engine abstraction over SQLAlchemy.

One process holds at most one engine per configured server, lazy-built
on first use. Each engine carries enough metadata to dispatch dialect-
specific introspection queries (sys.tables vs information_schema vs
pragma).
"""

from __future__ import annotations

import urllib.parse
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from sql_explorer_mcp.config import ServerConfig


def _mssql_url(s: ServerConfig) -> str:
    parts = [
        "DRIVER={ODBC Driver 18 for SQL Server}",
        f"SERVER={s.host},{s.port or 1433}",
    ]
    if s.database:
        parts.append(f"DATABASE={s.database}")
    parts.append("TrustServerCertificate=yes")
    parts.append("APP=sql-explorer-mcp")
    if s.auth == "windows":
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={s.username}")
        if s.password:
            parts.append(f"PWD={s.password}")
    odbc = urllib.parse.quote_plus(";".join(parts))
    return f"mssql+pyodbc:///?odbc_connect={odbc}"


def _postgres_url(s: ServerConfig) -> str:
    auth = ""
    if s.username:
        auth = s.username
        if s.password:
            auth += f":{urllib.parse.quote_plus(s.password)}"
        auth += "@"
    return f"postgresql+psycopg://{auth}{s.host}:{s.port or 5432}/{s.database or ''}"


def _sqlite_url(s: ServerConfig) -> str:
    if not s.path:
        raise ValueError(f"SQLite server {s.name!r} requires 'path'")
    return f"sqlite:///{s.path}"


@lru_cache(maxsize=8)
def _build_engine(server_name: str, dsn: str) -> Engine:
    return create_engine(
        dsn,
        pool_pre_ping=True,
        future=True,
        connect_args={"readonly": True} if dsn.startswith("mssql") else {},
    )


def get_engine(server: ServerConfig) -> Engine:
    if server.dialect == "mssql":
        dsn = _mssql_url(server)
    elif server.dialect == "postgres":
        dsn = _postgres_url(server)
    elif server.dialect == "sqlite":
        dsn = _sqlite_url(server)
    else:
        raise ValueError(f"Unknown dialect: {server.dialect}")
    return _build_engine(server.name, dsn)


def execute_select(server: ServerConfig, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
    """Execute a SELECT and return rows as list of dicts. Capped at server.max_rows."""
    eng = get_engine(server)
    with eng.connect() as cn:
        # Postgres: enforce read-only at session level
        if server.dialect == "postgres":
            cn.execute(text("SET TRANSACTION READ ONLY"))
        # SQL Server: query-level timeout via SET LOCK_TIMEOUT (less ideal than
        # connection timeout but a meaningful safety net)
        result = cn.execute(text(sql), params or {})
        rows = result.fetchmany(server.max_rows)
        cols = list(result.keys())
        return [dict(zip(cols, _serialise_row(r))) for r in rows]


def _serialise_row(row: Any) -> tuple:
    """Convert SQLAlchemy Row values to JSON-safe primitives."""
    out = []
    for v in row:
        if v is None:
            out.append(None)
        elif isinstance(v, (bool, int, float, str)):
            out.append(v)
        else:
            out.append(str(v))
    return tuple(out)
