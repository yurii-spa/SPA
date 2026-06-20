"""
tests/test_db_factory.py

20 unit tests for spa_core.database.db_factory.

Tests use monkeypatch to control environment variables so they do not
require a real PostgreSQL instance and do not touch the filesystem.

MP-1541 (v11.57)
"""

from __future__ import annotations

import os
import pytest

from spa_core.database.db_factory import (
    _mask_password,
    get_db_manager,
    get_db_url,
    is_postgres_configured,
    is_sqlite_configured,
)
from spa_core.database.sqlite_manager import SQLiteManager


# ─── Helpers ────────────────────────────────────────────────────────────────

def clear_db_env(monkeypatch):
    """Remove all DB-related env vars."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SQLITE_PATH", raising=False)


# ─── 1. get_db_manager — default path ────────────────────────────────────────

def test_default_returns_sqlite_manager(monkeypatch, tmp_path):
    clear_db_env(monkeypatch)
    mgr = get_db_manager(base_dir=str(tmp_path))
    assert isinstance(mgr, SQLiteManager)


def test_default_db_path_under_base_dir(monkeypatch, tmp_path):
    clear_db_env(monkeypatch)
    mgr = get_db_manager(base_dir=str(tmp_path))
    expected = os.path.join(str(tmp_path), "data", "spa.db")
    assert mgr.db_path == expected


def test_sqlite_path_env_var(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SQLITE_PATH", ":memory:")
    mgr = get_db_manager()
    assert mgr.db_path == ":memory:"


# ─── 2. get_db_manager — DATABASE_URL: sqlite ─────────────────────────────────

def test_database_url_sqlite_three_slashes(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    mgr = get_db_manager()
    assert isinstance(mgr, SQLiteManager)
    assert mgr.db_path == ":memory:"


def test_database_url_memory_shorthand(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", ":memory:")
    mgr = get_db_manager()
    assert mgr.db_path == ":memory:"


def test_database_url_sqlite_custom_path(monkeypatch, tmp_path):
    db_file = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    mgr = get_db_manager()
    assert mgr.db_path == db_file


def test_database_url_sqlite_two_slashes(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://:memory:")
    mgr = get_db_manager()
    assert mgr.db_path == ":memory:"


# ─── 3. get_db_manager — DATABASE_URL: postgresql ─────────────────────────────

def test_database_url_postgresql_raises(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/spa")
    with pytest.raises(NotImplementedError) as exc_info:
        get_db_manager()
    assert "ADR-031" in str(exc_info.value)


def test_database_url_postgres_alias_raises(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@localhost/spa")
    with pytest.raises(NotImplementedError):
        get_db_manager()


def test_database_url_unknown_scheme_raises(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mysql://user:pass@localhost/spa")
    with pytest.raises(ValueError) as exc_info:
        get_db_manager()
    assert "unrecognised scheme" in str(exc_info.value)


def test_database_url_empty_sqlite_path_raises(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///")
    with pytest.raises(ValueError) as exc_info:
        get_db_manager()
    assert "empty" in str(exc_info.value)


# ─── 4. get_db_url ────────────────────────────────────────────────────────────

def test_get_db_url_default(monkeypatch):
    clear_db_env(monkeypatch)
    url = get_db_url()
    assert url.startswith("sqlite:///")


def test_get_db_url_sqlite_path_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SQLITE_PATH", "/tmp/custom.db")
    url = get_db_url()
    assert url == "sqlite:////tmp/custom.db"


def test_get_db_url_masks_password(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:s3cr3t@localhost/spa")
    url = get_db_url()
    assert "s3cr3t" not in url
    assert "***" in url


def test_get_db_url_sqlite_no_mask(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///data/spa.db")
    url = get_db_url()
    assert url == "sqlite:///data/spa.db"


# ─── 5. is_postgres_configured / is_sqlite_configured ────────────────────────

def test_is_postgres_false_by_default(monkeypatch):
    clear_db_env(monkeypatch)
    assert is_postgres_configured() is False


def test_is_postgres_true_postgresql(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/spa")
    assert is_postgres_configured() is True


def test_is_postgres_true_postgres_alias(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@localhost/spa")
    assert is_postgres_configured() is True


def test_is_sqlite_true_by_default(monkeypatch):
    clear_db_env(monkeypatch)
    assert is_sqlite_configured() is True


def test_is_sqlite_false_when_postgres(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/spa")
    assert is_sqlite_configured() is False


# ─── 6. _mask_password helper ─────────────────────────────────────────────────

def test_mask_password_replaces_secret():
    url = "postgresql://admin:supersecret@db.example.com:5432/mydb"
    masked = _mask_password(url)
    assert "supersecret" not in masked
    assert "***" in masked
    assert "admin" in masked
