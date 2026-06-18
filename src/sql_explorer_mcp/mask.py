"""Optional PII masking of run_query results, backed by pii-veil.

Off by default. Set ``SQL_EXPLORER_MASK=1`` to mask PII in result rows before
they go back to the model, and optionally ``SQL_EXPLORER_MASK_COLUMNS`` to a
comma-separated list of columns to restrict masking to. If pii-veil isn't
installed or masking isn't enabled, this is a no-op that returns rows unchanged.

Install with: pip install "sql-explorer-mcp[mask]"
"""
from __future__ import annotations

import os

_veil = None
_resolved = False
_ON = {"1", "true", "yes", "on"}


def _get_veil():
    global _veil, _resolved
    if _resolved:
        return _veil
    _resolved = True
    if (os.environ.get("SQL_EXPLORER_MASK") or "").strip().lower() not in _ON:
        return None
    try:
        from pii_veil import Veil
    except ImportError:
        return None
    try:
        _veil = Veil()
    except Exception:
        _veil = None
    return _veil


def mask_rows(rows):
    """Mask PII in result rows when masking is enabled; otherwise return as-is."""
    veil = _get_veil()
    if veil is None or not rows:
        return rows
    cols = os.environ.get("SQL_EXPLORER_MASK_COLUMNS")
    columns = [c.strip() for c in cols.split(",") if c.strip()] if cols else None
    try:
        return veil.scrub_rows(rows, columns=columns)
    except Exception:
        return rows
