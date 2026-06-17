"""Optional audit trail for run_query, backed by agent-blackbox.

Off by default. Set ``SQL_EXPLORER_AUDIT_DB`` to a file path and every run_query
call is recorded to a tamper-evident agent-blackbox ledger: the SQL, which
server, the outcome (ok / blocked / error), row count and timing. Set
``SQL_EXPLORER_AUDIT_HASH=1`` to store a SHA-256 of the SQL instead of the clear
text, for sensitive workloads.

The record is written by the server, not the model, so a clever prompt can't
talk the log out of existence. If agent-blackbox isn't installed, or the env var
isn't set, every call here is a no-op — auditing must never break a query.

Install the optional dependency with: pip install "sql-explorer-mcp[audit]"
"""
from __future__ import annotations

import os
from typing import Optional

_ledger = None
_resolved = False


def _get_ledger():
    """Return a cached Ledger, or None if auditing is off / unavailable."""
    global _ledger, _resolved
    if _resolved:
        return _ledger
    _resolved = True
    path = os.environ.get("SQL_EXPLORER_AUDIT_DB")
    if not path:
        return None
    try:
        from agent_blackbox import Ledger
    except ImportError:
        return None
    hash_payload = os.environ.get("SQL_EXPLORER_AUDIT_HASH") == "1"
    if hash_payload:
        try:
            _ledger = Ledger(path, hash_payload=True)
        except TypeError:
            # Installed agent-blackbox predates hash_payload; store clear text.
            _ledger = Ledger(path)
    else:
        _ledger = Ledger(path)
    return _ledger


def record_query(sql: str, server: str, outcome: str, meta: Optional[dict] = None) -> None:
    """Record one run_query call, if auditing is enabled. Never raises."""
    led = _get_ledger()
    if led is None:
        return
    try:
        led.record(
            "sql-explorer-mcp",
            "run_query",
            target=server,
            payload=sql,
            outcome=outcome,
            meta=meta or {},
        )
    except Exception:
        # An audit failure must not take down the query path.
        pass
