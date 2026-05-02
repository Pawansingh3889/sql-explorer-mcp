"""Three-layer safety stack for run_query.

Layer 1: connection-level read-only (handled in engines.py)
Layer 2: sqlglot AST validation -- reject anything that isn't a single SELECT
Layer 3: sql-sop linter -- reject queries with error-severity findings

Each call to validate_query() runs both layer 2 and layer 3 and returns a
SafetyResult with passed=True only if both pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import expressions as sg_exp


SELECT_ROOT_TYPES = (sg_exp.Select, sg_exp.Union, sg_exp.With)


@dataclass
class SafetyResult:
    passed: bool
    layer: str | None = None  # which layer failed, or None
    reason: str | None = None
    sqlsop_findings: list[dict] = field(default_factory=list)


def validate_select_only(sql: str, dialect: str = "tsql") -> SafetyResult:
    """Layer 2: parse the SQL, ensure it's exactly one statement and that
    statement is a SELECT (or UNION/CTE wrapping a SELECT). Reject everything
    else (INSERT, UPDATE, DELETE, MERGE, EXEC, DDL).

    `dialect` is the sqlglot dialect token: 'tsql', 'postgres', 'sqlite'.
    """
    sqlglot_dialect = {"mssql": "tsql", "postgres": "postgres", "sqlite": "sqlite"}.get(
        dialect, dialect
    )

    try:
        statements = sqlglot.parse(sql, dialect=sqlglot_dialect)
    except sqlglot.ParseError as e:
        return SafetyResult(passed=False, layer="parse", reason=f"SQL parse error: {e}")

    statements = [s for s in statements if s is not None]

    if len(statements) == 0:
        return SafetyResult(passed=False, layer="parse", reason="No statements found")
    if len(statements) > 1:
        return SafetyResult(
            passed=False,
            layer="select-only",
            reason=f"Multiple statements not allowed ({len(statements)} found). "
                   f"Submit one SELECT at a time.",
        )

    stmt = statements[0]

    # Allow SELECT, UNION, INTERSECT, EXCEPT, and CTEs that wrap a SELECT.
    if not isinstance(stmt, SELECT_ROOT_TYPES):
        return SafetyResult(
            passed=False,
            layer="select-only",
            reason=f"Only SELECT statements allowed. Got: {type(stmt).__name__}",
        )

    # If it's a WITH (CTE), check that the body is a SELECT
    if isinstance(stmt, sg_exp.With):
        body = stmt.expression
        if not isinstance(body, SELECT_ROOT_TYPES):
            return SafetyResult(
                passed=False,
                layer="select-only",
                reason=f"CTE body must be SELECT. Got: {type(body).__name__}",
            )

    # Walk the tree and reject if any DML/DDL nodes appear (CTE or subquery
    # smuggling INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/MERGE/EXEC).
    forbidden = (
        sg_exp.Insert,
        sg_exp.Update,
        sg_exp.Delete,
        sg_exp.Merge,
        sg_exp.Create,
        sg_exp.Drop,
        sg_exp.Alter,
        sg_exp.Command,  # generic catch-all (EXEC, GRANT, REVOKE, etc.)
    )
    for node in stmt.walk():
        actual_node = node[0] if isinstance(node, tuple) else node
        if isinstance(actual_node, forbidden):
            return SafetyResult(
                passed=False,
                layer="select-only",
                reason=f"Forbidden statement type in query: {type(actual_node).__name__}",
            )

    return SafetyResult(passed=True)


def lint_with_sql_sop(sql: str) -> SafetyResult:
    """Layer 3: run sql-sop and reject if any error-severity findings fire.

    Warnings are collected and returned in SafetyResult.sqlsop_findings but
    don't block the query -- the LLM gets to see them as advisory output.
    """
    try:
        from sql_guard.fluent import SqlGuard
    except ImportError:
        # If sql-sop isn't installed, layer 3 is a no-op.
        return SafetyResult(passed=True)

    result = SqlGuard().scan(sql)
    findings = [
        {
            "rule_id": f.rule_id,
            "severity": f.severity,
            "message": f.message,
            "line": getattr(f, "line", None),
        }
        for f in result.findings
    ]
    errors = [f for f in findings if f["severity"] == "error"]
    if errors:
        return SafetyResult(
            passed=False,
            layer="sql-sop-error",
            reason=f"sql-sop found {len(errors)} error-severity issue(s): "
                   + "; ".join(f"{e['rule_id']} {e['message']}" for e in errors[:3]),
            sqlsop_findings=findings,
        )
    return SafetyResult(passed=True, sqlsop_findings=findings)


def validate_query(sql: str, dialect: str = "mssql") -> SafetyResult:
    """Run all safety layers. First failure short-circuits."""
    layer2 = validate_select_only(sql, dialect=dialect)
    if not layer2.passed:
        return layer2
    layer3 = lint_with_sql_sop(sql)
    return layer3
