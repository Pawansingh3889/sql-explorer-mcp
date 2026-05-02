"""Multi-server configuration loader.

Reads servers.yaml from one of: $SQL_EXPLORER_CONFIG, ./servers.yaml,
~/.sql-explorer-mcp/servers.yaml. Each server entry has a name, dialect
(mssql / postgres / sqlite), and connection details.

Example servers.yaml:

    default_server: lab
    servers:
      lab:
        dialect: mssql
        host: localhost
        port: 1433
        database: BusinessLab
        auth: sql
        username: sa
        password_env: LAB_PASSWORD          # read from env, not the file
      production:
        dialect: mssql
        host: BUSINESS-SQL
        port: 1433
        database: SI
        auth: windows                       # uses Trusted_Connection
      analytics:
        dialect: postgres
        host: db.internal
        port: 5432
        database: warehouse
        username: readonly
        password_env: PG_PASSWORD
      local:
        dialect: sqlite
        path: ./mydb.sqlite
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

Dialect = Literal["mssql", "postgres", "sqlite"]


class ConfigError(RuntimeError):
    pass


@dataclass
class ServerConfig:
    name: str
    dialect: Dialect
    # mssql / postgres
    host: str | None = None
    port: int | None = None
    database: str | None = None
    auth: str = "sql"  # 'sql' or 'windows' (mssql only)
    username: str | None = None
    password_env: str | None = None
    # sqlite
    path: str | None = None
    # safety
    max_rows: int = 1000
    query_timeout_seconds: int = 30

    @property
    def password(self) -> str | None:
        if self.password_env:
            val = os.environ.get(self.password_env)
            if not val:
                raise ConfigError(
                    f"Server '{self.name}' has password_env={self.password_env!r} "
                    f"but that env var is not set"
                )
            return val
        return None


@dataclass
class Config:
    default_server: str
    servers: dict[str, ServerConfig] = field(default_factory=dict)

    def get_server(self, name: str | None) -> ServerConfig:
        key = name or self.default_server
        if key not in self.servers:
            raise ConfigError(
                f"Unknown server {key!r}. Configured servers: {sorted(self.servers)}"
            )
        return self.servers[key]


def _candidate_paths() -> list[Path]:
    paths = []
    env = os.environ.get("SQL_EXPLORER_CONFIG")
    if env:
        paths.append(Path(env))
    paths.extend([
        Path("servers.yaml"),
        Path("servers.yml"),
        Path.home() / ".sql-explorer-mcp" / "servers.yaml",
    ])
    return paths


def load_config(path: str | Path | None = None) -> Config:
    if path:
        candidates = [Path(path)]
    else:
        candidates = _candidate_paths()

    for cand in candidates:
        if cand.exists():
            return _parse(cand)

    tried = ", ".join(str(c) for c in candidates)
    raise ConfigError(
        f"No servers.yaml found. Set SQL_EXPLORER_CONFIG or place a "
        f"servers.yaml in cwd or ~/.sql-explorer-mcp/. Tried: {tried}"
    )


def _parse(path: Path) -> Config:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top-level must be a mapping")

    default_server = raw.get("default_server")
    servers_raw = raw.get("servers", {})
    if not isinstance(servers_raw, dict) or not servers_raw:
        raise ConfigError(f"{path}: missing or empty 'servers:' section")

    servers: dict[str, ServerConfig] = {}
    for name, entry in servers_raw.items():
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: server {name!r} must be a mapping")
        dialect = entry.get("dialect")
        if dialect not in ("mssql", "postgres", "sqlite"):
            raise ConfigError(
                f"{path}: server {name!r} has invalid dialect={dialect!r}; "
                f"must be mssql / postgres / sqlite"
            )
        servers[name] = ServerConfig(
            name=name,
            dialect=dialect,
            host=entry.get("host"),
            port=entry.get("port"),
            database=entry.get("database"),
            auth=entry.get("auth", "sql"),
            username=entry.get("username"),
            password_env=entry.get("password_env"),
            path=entry.get("path"),
            max_rows=int(entry.get("max_rows", 1000)),
            query_timeout_seconds=int(entry.get("query_timeout_seconds", 30)),
        )

    if not default_server:
        # Default to the first server if not specified
        default_server = next(iter(servers))

    if default_server not in servers:
        raise ConfigError(
            f"{path}: default_server={default_server!r} is not in servers list"
        )

    return Config(default_server=default_server, servers=servers)
