import sqlite3

import pytest

from sql_explorer_mcp import audit


def _reset():
    if audit._ledger is not None:
        try:
            audit._ledger.close()
        except Exception:
            pass
    audit._ledger = None
    audit._resolved = False


def test_noop_when_disabled(monkeypatch):
    _reset()
    monkeypatch.delenv("SQL_EXPLORER_AUDIT_DB", raising=False)
    # Must not raise and must not create a ledger.
    audit.record_query("SELECT 1", "lab", outcome="ok", meta={"rows": 1})
    assert audit._get_ledger() is None
    _reset()


def test_records_when_enabled(tmp_path, monkeypatch):
    pytest.importorskip("agent_blackbox")
    _reset()
    db = tmp_path / "audit.db"
    monkeypatch.setenv("SQL_EXPLORER_AUDIT_DB", str(db))
    monkeypatch.delenv("SQL_EXPLORER_AUDIT_HASH", raising=False)

    audit.record_query("SELECT * FROM orders", "lab", outcome="ok", meta={"rows": 5})
    audit.record_query("DROP TABLE orders", "lab", outcome="blocked", meta={"layer": "select-only"})
    _reset()  # close the writer's connection

    from agent_blackbox import Ledger

    led = Ledger(str(db))
    entries = list(led.entries())
    assert len(entries) == 2
    assert entries[0].action == "run_query"
    assert entries[0].target == "lab"
    assert entries[0].outcome == "ok"
    assert entries[1].outcome == "blocked"
    assert led.verify().ok
    led.close()


def test_hash_mode_keeps_sql_off_disk(tmp_path, monkeypatch):
    import inspect

    agent_blackbox = pytest.importorskip("agent_blackbox")
    if "hash_payload" not in inspect.signature(agent_blackbox.Ledger.__init__).parameters:
        pytest.skip("installed agent-blackbox predates hash_payload")
    _reset()
    db = tmp_path / "audit.db"
    monkeypatch.setenv("SQL_EXPLORER_AUDIT_DB", str(db))
    monkeypatch.setenv("SQL_EXPLORER_AUDIT_HASH", "1")

    secret = "SELECT ssn FROM people WHERE id = 7"
    audit.record_query(secret, "prod", outcome="ok", meta={"rows": 1})
    _reset()

    stored = sqlite3.connect(str(db)).execute("SELECT payload FROM entries").fetchone()[0]
    assert secret not in str(stored)  # stored as a hash, not clear text
