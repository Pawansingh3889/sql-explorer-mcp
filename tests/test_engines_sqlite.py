"""Integration test: real engine round-trip against an in-memory SQLite DB.

Proves the engine layer works end-to-end without needing Docker / SQL
Server / Postgres. CI runs this without any external services.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sql_explorer_mcp.config import ServerConfig
from sql_explorer_mcp.engines import execute_select


@pytest.fixture
def sqlite_server(tmp_path: Path) -> ServerConfig:
    """Build a SQLite server config pointing at a temp file with a tiny schema."""
    db_path = tmp_path / "test.sqlite"
    cfg = ServerConfig(
        name="test",
        dialect="sqlite",
        path=str(db_path),
        max_rows=100,
    )
    # Seed a tiny schema using sqlite3 directly
    import sqlite3
    cn = sqlite3.connect(db_path)
    cn.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, active INTEGER);
        INSERT INTO users (name, active) VALUES
            ('alice', 1), ('bob', 1), ('carol', 0);
    """)
    cn.commit()
    cn.close()
    return cfg


class TestExecuteSelect:
    def test_simple_select(self, sqlite_server):
        rows = execute_select(sqlite_server, "SELECT id, name FROM users ORDER BY id")
        assert len(rows) == 3
        assert rows[0] == {"id": 1, "name": "alice"}
        assert rows[2] == {"id": 3, "name": "carol"}

    def test_with_params(self, sqlite_server):
        rows = execute_select(
            sqlite_server,
            "SELECT name FROM users WHERE active = :active",
            {"active": 1},
        )
        names = sorted(r["name"] for r in rows)
        assert names == ["alice", "bob"]

    def test_max_rows_caps_result(self, sqlite_server):
        sqlite_server.max_rows = 2
        rows = execute_select(sqlite_server, "SELECT * FROM users")
        assert len(rows) == 2

    def test_returns_list_of_dicts(self, sqlite_server):
        rows = execute_select(sqlite_server, "SELECT id FROM users LIMIT 1")
        assert isinstance(rows, list)
        assert isinstance(rows[0], dict)
