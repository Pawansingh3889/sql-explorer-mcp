"""Tests for the multi-server config loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from sql_explorer_mcp.config import ConfigError, load_config


def write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


class TestLoadConfig:
    def test_loads_minimal_config(self, tmp_path: Path):
        p = write(
            tmp_path,
            "servers.yaml",
            """
default_server: lab
servers:
  lab:
    dialect: sqlite
    path: ./test.sqlite
""",
        )
        cfg = load_config(p)
        assert cfg.default_server == "lab"
        assert "lab" in cfg.servers
        assert cfg.servers["lab"].dialect == "sqlite"

    def test_default_server_optional_picks_first(self, tmp_path: Path):
        p = write(
            tmp_path,
            "servers.yaml",
            """
servers:
  alpha:
    dialect: sqlite
    path: ./a.sqlite
  beta:
    dialect: sqlite
    path: ./b.sqlite
""",
        )
        cfg = load_config(p)
        assert cfg.default_server == "alpha"

    def test_unknown_dialect_raises(self, tmp_path: Path):
        p = write(
            tmp_path,
            "servers.yaml",
            """
servers:
  bad:
    dialect: oracle
""",
        )
        with pytest.raises(ConfigError):
            load_config(p)

    def test_missing_servers_section_raises(self, tmp_path: Path):
        p = write(tmp_path, "servers.yaml", "default_server: nope\n")
        with pytest.raises(ConfigError):
            load_config(p)

    def test_default_server_must_exist_in_servers(self, tmp_path: Path):
        p = write(
            tmp_path,
            "servers.yaml",
            """
default_server: ghost
servers:
  real:
    dialect: sqlite
    path: ./r.sqlite
""",
        )
        with pytest.raises(ConfigError):
            load_config(p)


class TestGetServer:
    def test_returns_default_when_name_omitted(self, tmp_path: Path):
        p = write(
            tmp_path,
            "servers.yaml",
            """
default_server: lab
servers:
  lab:
    dialect: sqlite
    path: ./test.sqlite
""",
        )
        cfg = load_config(p)
        assert cfg.get_server(None).name == "lab"

    def test_returns_named_server(self, tmp_path: Path):
        p = write(
            tmp_path,
            "servers.yaml",
            """
default_server: lab
servers:
  lab:
    dialect: sqlite
    path: ./l.sqlite
  prod:
    dialect: sqlite
    path: ./p.sqlite
""",
        )
        cfg = load_config(p)
        assert cfg.get_server("prod").name == "prod"

    def test_unknown_server_raises(self, tmp_path: Path):
        p = write(
            tmp_path,
            "servers.yaml",
            """
servers:
  lab:
    dialect: sqlite
    path: ./l.sqlite
""",
        )
        cfg = load_config(p)
        with pytest.raises(ConfigError):
            cfg.get_server("nope")


class TestPasswordEnv:
    def test_password_read_from_env(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("MY_TEST_PWD", "supersecret")
        p = write(
            tmp_path,
            "servers.yaml",
            """
servers:
  s:
    dialect: postgres
    host: x
    username: u
    password_env: MY_TEST_PWD
""",
        )
        cfg = load_config(p)
        assert cfg.servers["s"].password == "supersecret"

    def test_missing_env_raises_on_access(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("MISSING_PWD", raising=False)
        p = write(
            tmp_path,
            "servers.yaml",
            """
servers:
  s:
    dialect: postgres
    host: x
    username: u
    password_env: MISSING_PWD
""",
        )
        cfg = load_config(p)
        with pytest.raises(ConfigError):
            _ = cfg.servers["s"].password
