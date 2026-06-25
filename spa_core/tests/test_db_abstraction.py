"""
Tests for the database abstraction scaffold introduced in BL-008 Phase 1.

Covers:
    * db_url.get_db_url / is_postgres / is_sqlite / get_sqlite_path
    * connection.get_connection (sqlite branch, postgres-without-driver branch)

All tests are deterministic: no network, no real filesystem writes beyond
pytest's tmp_path, and the postgres branch is exercised only when psycopg2
is NOT installed (otherwise that test is skipped, since we don't spin up a
real database in this scaffold phase).
"""
from __future__ import annotations

import importlib.util
import sqlite3

import pytest

from spa_core.database import db_url as db_url_mod
from spa_core.database.connection import DriverNotInstalled, get_connection


# ─── db_url.get_db_url ────────────────────────────────────────────────────────

def test_default_url_is_sqlite(monkeypatch):
    """With no env override, URL must point at the on-disk SQLite file."""
    monkeypatch.delenv(db_url_mod.ENV_VAR, raising=False)
    url = db_url_mod.get_db_url()
    assert url.startswith("sqlite:///"), url
    assert url.endswith("spa.db"), url


def test_env_var_override(monkeypatch):
    """Setting SPA_DATABASE_URL must override the SQLite fallback."""
    monkeypatch.setenv(db_url_mod.ENV_VAR, "postgresql://u@h/db")
    assert db_url_mod.get_db_url() == "postgresql://u@h/db"


def test_env_var_empty_string_falls_back(monkeypatch):
    """Empty/whitespace env var must be treated as unset."""
    monkeypatch.setenv(db_url_mod.ENV_VAR, "   ")
    assert db_url_mod.get_db_url().startswith("sqlite:///")


# ─── db_url.is_postgres ───────────────────────────────────────────────────────

def test_is_postgres_for_postgresql_url():
    assert db_url_mod.is_postgres("postgresql://u@h/db") is True


def test_is_postgres_for_postgres_url():
    assert db_url_mod.is_postgres("postgres://u@h/db") is True


def test_is_postgres_false_for_sqlite():
    assert db_url_mod.is_postgres("sqlite:///tmp/x.db") is False


# ─── db_url.get_sqlite_path ───────────────────────────────────────────────────

def test_get_sqlite_path_extracts_path():
    # `sqlite:///` is the SQLAlchemy-style prefix and what get_db_url() emits.
    # The portion after that prefix is the path verbatim — here a relative one.
    p = db_url_mod.get_sqlite_path("sqlite:///var/data/spa.db")
    assert p is not None
    assert str(p) == "var/data/spa.db"


def test_get_sqlite_path_extracts_absolute_path():
    # Absolute paths require the 4-slash form (`sqlite:////abs/path`) which is
    # also what get_db_url() produces for the on-disk fallback.
    p = db_url_mod.get_sqlite_path("sqlite:////var/data/spa.db")
    assert p is not None
    assert str(p) == "/var/data/spa.db"


def test_get_sqlite_path_returns_none_for_postgres():
    assert db_url_mod.get_sqlite_path("postgresql://u@h/db") is None


def test_get_sqlite_path_handles_memory():
    p = db_url_mod.get_sqlite_path("sqlite:///:memory:")
    assert p is not None
    assert str(p) == ":memory:"


# ─── connection.get_connection ────────────────────────────────────────────────

def test_connection_sqlite_returns_row_factory(monkeypatch):
    """SQLite branch must yield a sqlite3.Connection with sqlite3.Row factory."""
    monkeypatch.setenv(db_url_mod.ENV_VAR, "sqlite:///:memory:")
    with get_connection() as conn:
        assert isinstance(conn, sqlite3.Connection)
        assert conn.row_factory is sqlite3.Row
        # Smoke-test that it actually works.
        cur = conn.execute("SELECT 1 AS one")
        row = cur.fetchone()
        assert row["one"] == 1


def test_connection_sqlite_explicit_url_argument(tmp_path):
    """Passing an explicit URL must bypass env resolution."""
    db_file = tmp_path / "explicit.db"
    with get_connection(f"sqlite:///{db_file}") as conn:
        assert isinstance(conn, sqlite3.Connection)
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (42)")
        conn.commit()
    # File should have been created on disk.
    assert db_file.exists()


def test_connection_postgres_raises_without_driver(monkeypatch):
    """
    If psycopg2 is not installed, requesting a Postgres URL must raise
    DriverNotInstalled (a RuntimeError subclass). When psycopg2 IS available
    we skip — Phase 1 does not run a real Postgres.
    """
    if importlib.util.find_spec("psycopg2") is not None:
        pytest.skip("psycopg2 installed; cannot exercise missing-driver path")
    monkeypatch.setenv(db_url_mod.ENV_VAR, "postgresql://u:p@localhost/nope")
    with pytest.raises(RuntimeError) as exc_info:
        with get_connection() as _conn:
            pass
    assert isinstance(exc_info.value, DriverNotInstalled)
    assert "psycopg2-binary" in str(exc_info.value)


def test_connection_unknown_scheme_raises(monkeypatch):
    """Anything that's not sqlite:// or postgres:// must raise ValueError or ConfigError."""
    from spa_core.utils.errors import ConfigError
    monkeypatch.setenv(db_url_mod.ENV_VAR, "mysql://u@h/db")
    with pytest.raises((ValueError, ConfigError)):
        with get_connection() as _conn:
            pass
