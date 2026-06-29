"""Optional role-based access layer, backed by query-warden.

Off by default. Set ``SQL_EXPLORER_POLICY`` to a query-warden policy YAML file
(and optionally ``SQL_EXPLORER_ROLE`` to the role to enforce) and every query is
checked against that role before it runs: tables and columns outside the role's
allow-list are blocked. If query-warden isn't installed or no policy is set,
this is a no-op that allows everything, so it never breaks an unconfigured server.

Install with: pip install "sql-explorer-mcp[rbac]"
"""

from __future__ import annotations

import os

_warden = None
_resolved = False


def _get_warden():
    """Return a cached query-warden Warden, or None if off / unavailable."""
    global _warden, _resolved
    if _resolved:
        return _warden
    _resolved = True
    path = os.environ.get("SQL_EXPLORER_POLICY")
    if not path:
        return None
    try:
        from query_warden import Warden
    except ImportError:
        return None
    try:
        _warden = Warden.from_yaml(path)
    except Exception:
        _warden = None
    return _warden


def _warden_dialect(dialect: str | None) -> str | None:
    # query-warden parses with sqlglot; map our engine names to sqlglot tokens.
    return {"mssql": "tsql", "postgres": "postgres", "sqlite": "sqlite"}.get(dialect, dialect)


def check_role(sql: str, dialect: str | None = None):
    """Return (allowed, reason). Allows everything when no policy is configured."""
    warden = _get_warden()
    if warden is None:
        return True, None
    role = os.environ.get("SQL_EXPLORER_ROLE")
    decision = warden.check(sql, role=role, dialect=_warden_dialect(dialect))
    return decision.allowed, decision.reason
