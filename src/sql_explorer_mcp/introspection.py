"""Dialect-specific introspection queries.

Each function returns the SQL string for one dialect. Tools call these
to render list_databases / list_tables / describe_table / etc.

The queries are short, parameterised where appropriate, and read-only.
"""

from __future__ import annotations


def list_databases_sql(dialect: str) -> str:
    if dialect == "mssql":
        return "SELECT name FROM sys.databases WHERE state = 0 ORDER BY name"
    if dialect == "postgres":
        return ("SELECT datname AS name FROM pg_database "
                "WHERE datistemplate = false ORDER BY datname")
    if dialect == "sqlite":
        return "SELECT name FROM pragma_database_list()"
    raise ValueError(f"Unknown dialect: {dialect}")


def list_tables_sql(dialect: str, schema: str | None) -> tuple[str, dict]:
    if dialect == "mssql":
        sql = (
            "SELECT TABLE_SCHEMA AS schema_name, TABLE_NAME AS table_name, "
            "TABLE_TYPE AS table_type "
            "FROM INFORMATION_SCHEMA.TABLES "
        )
        params = {}
        if schema:
            sql += "WHERE TABLE_SCHEMA = :schema "
            params["schema"] = schema
        sql += "ORDER BY TABLE_SCHEMA, TABLE_NAME"
        return sql, params
    if dialect == "postgres":
        sql = (
            "SELECT schemaname AS schema_name, tablename AS table_name, "
            "'BASE TABLE' AS table_type "
            "FROM pg_tables "
            "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') "
        )
        params = {}
        if schema:
            sql += "AND schemaname = :schema "
            params["schema"] = schema
        sql += "ORDER BY schemaname, tablename"
        return sql, params
    if dialect == "sqlite":
        sql = (
            "SELECT 'main' AS schema_name, name AS table_name, "
            "type AS table_type "
            "FROM sqlite_master WHERE type IN ('table','view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return sql, {}
    raise ValueError(f"Unknown dialect: {dialect}")


def describe_table_sql(dialect: str, table: str, schema: str | None) -> tuple[str, dict]:
    if dialect == "mssql":
        sql = (
            "SELECT c.COLUMN_NAME AS column_name, c.DATA_TYPE AS data_type, "
            "c.CHARACTER_MAXIMUM_LENGTH AS max_length, "
            "c.NUMERIC_PRECISION AS [precision], c.NUMERIC_SCALE AS scale, "
            "c.IS_NULLABLE AS is_nullable, c.COLUMN_DEFAULT AS [default] "
            "FROM INFORMATION_SCHEMA.COLUMNS c "
            "WHERE c.TABLE_NAME = :table "
        )
        params = {"table": table}
        if schema:
            sql += "AND c.TABLE_SCHEMA = :schema "
            params["schema"] = schema
        sql += "ORDER BY c.ORDINAL_POSITION"
        return sql, params
    if dialect == "postgres":
        sql = (
            "SELECT column_name, data_type, "
            "character_maximum_length AS max_length, "
            "numeric_precision AS precision, numeric_scale AS scale, "
            "is_nullable, column_default AS default "
            "FROM information_schema.columns "
            "WHERE table_name = :table "
        )
        params = {"table": table}
        if schema:
            sql += "AND table_schema = :schema "
            params["schema"] = schema
        sql += "ORDER BY ordinal_position"
        return sql, params
    if dialect == "sqlite":
        # SQLite uses pragma; quote table name safely
        # NOTE: pragma doesn't accept bound params, so we have to inject -
        # but we validate the table name first to prevent injection
        if not table.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"Invalid table name: {table!r}")
        sql = f"SELECT name AS column_name, type AS data_type, NULL AS max_length, NULL AS precision, NULL AS scale, CASE WHEN \"notnull\" = 0 THEN 'YES' ELSE 'NO' END AS is_nullable, dflt_value AS default FROM pragma_table_info('{table}')"
        return sql, {}
    raise ValueError(f"Unknown dialect: {dialect}")


def get_table_sample_sql(dialect: str, table: str, schema: str | None, n: int) -> tuple[str, dict]:
    n = max(1, min(n, 1000))  # clamp 1-1000
    fq_table = f"{schema}.{table}" if schema else table
    # Quote each part to prevent injection -- bracket for mssql, double-quote elsewhere
    if dialect == "mssql":
        parts = fq_table.split(".")
        fq_quoted = ".".join(f"[{p}]" for p in parts)
        return f"SELECT TOP ({n}) * FROM {fq_quoted}", {}
    if dialect == "postgres":
        parts = fq_table.split(".")
        fq_quoted = ".".join(f'"{p}"' for p in parts)
        return f'SELECT * FROM {fq_quoted} LIMIT {n}', {}
    if dialect == "sqlite":
        # SQLite has no schemas in the same sense
        if not table.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"Invalid table name: {table!r}")
        return f'SELECT * FROM "{table}" LIMIT {n}', {}
    raise ValueError(f"Unknown dialect: {dialect}")


def explain_query_sql(dialect: str, sql: str) -> str:
    """Wrap a query so the engine returns its execution plan as text/JSON."""
    if dialect == "mssql":
        # SET SHOWPLAN_TEXT requires its own batch; the simpler 'SHOWPLAN_ALL'
        # would also do it. For richer JSON output we'd use SET STATISTICS XML
        # but XML in JSON is awkward. Use estimated text plan for v0.1.
        return f"SET SHOWPLAN_TEXT ON;\n{sql}"
    if dialect == "postgres":
        return f"EXPLAIN (FORMAT JSON) {sql}"
    if dialect == "sqlite":
        return f"EXPLAIN QUERY PLAN {sql}"
    raise ValueError(f"Unknown dialect: {dialect}")


def search_objects_sql(dialect: str, query: str) -> tuple[str, dict]:
    pattern = f"%{query}%"
    if dialect == "mssql":
        sql = (
            "SELECT 'TABLE' AS object_type, TABLE_SCHEMA AS schema_name, "
            "TABLE_NAME AS object_name, NULL AS column_name "
            "FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME LIKE :pattern "
            "UNION ALL "
            "SELECT 'COLUMN' AS object_type, TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME "
            "FROM INFORMATION_SCHEMA.COLUMNS WHERE COLUMN_NAME LIKE :pattern "
            "ORDER BY object_type, schema_name, object_name"
        )
        return sql, {"pattern": pattern}
    if dialect == "postgres":
        sql = (
            "SELECT 'TABLE' AS object_type, schemaname AS schema_name, "
            "tablename AS object_name, NULL AS column_name "
            "FROM pg_tables WHERE tablename ILIKE :pattern "
            "UNION ALL "
            "SELECT 'COLUMN', table_schema, table_name, column_name "
            "FROM information_schema.columns WHERE column_name ILIKE :pattern "
            "ORDER BY object_type, schema_name, object_name"
        )
        return sql, {"pattern": pattern}
    if dialect == "sqlite":
        sql = (
            "SELECT 'TABLE' AS object_type, 'main' AS schema_name, "
            "name AS object_name, NULL AS column_name "
            "FROM sqlite_master WHERE type='table' AND name LIKE :pattern "
            "ORDER BY object_name"
        )
        return sql, {"pattern": pattern}
    raise ValueError(f"Unknown dialect: {dialect}")
