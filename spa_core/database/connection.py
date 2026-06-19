"""
SPA Database Connection Adapter — BL-008 Phase 1

A thin abstraction over the two supported backends (SQLite and PostgreSQL).
Call-sites stay agnostic: they ask `get_connection()` for a context manager
and receive a driver-native connection object configured with a sensible
row-factory.

Notes
-----
* psycopg2 is imported lazily inside the function so the SQLite-only path
  has zero hard dependency on it.
* The SQLite branch keeps the existing semantics (`sqlite3.Row` row factory)
  so existing call-sites can be migrated incrementally in Phase 2.
* For PostgreSQL we attach `psycopg2.extras.RealDictCursor` as the default
  cursor factory; callers using `conn.cursor()` will get dict-like rows that
  are reasonably close to `sqlite3.Row` in ergonomics.

Phase 1 scope
-------------
Existing modules continue to call `sqlite3.connect(...)` directly. This file
exists so new code (and Phase 2 migrations) have a single seam.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

from .db_url import get_db_url, get_sqlite_path, is_postgres, is_sqlite
from spa_core.utils.errors import ConfigError


class DriverNotInstalled(RuntimeError):
    """Raised when the URL requests Postgres but psycopg2 is not importable."""


@contextmanager
def get_connection(url: Optional[str] = None) -> Iterator[object]:
    """
    Yield a live DB connection chosen by `url` (or env-resolved URL).

    Returns:
        * `sqlite3.Connection` with `row_factory = sqlite3.Row`, OR
        * `psycopg2.extensions.connection` with `cursor_factory = RealDictCursor`.

    Raises:
        DriverNotInstalled — if URL targets Postgres but psycopg2 is missing.
        ValueError — if URL scheme is not recognised.

    The connection is closed unconditionally on exit. No autocommit fiddling
    happens here; callers manage transactions explicitly.
    """
    resolved = url if url is not None else get_db_url()

    if is_sqlite(resolved):
        path = get_sqlite_path(resolved)
        if path is None:
            raise ConfigError("DATABASE_URL", f"Could not extract sqlite path from URL: {resolved!r}")
        # Ensure parent dir exists for on-disk DBs; skip for :memory:.
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
            conn_target = str(path)
        else:
            conn_target = ":memory:"
        conn = sqlite3.connect(conn_target)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
        return

    if is_postgres(resolved):
        try:
            import psycopg2  # type: ignore
            import psycopg2.extras  # type: ignore
        except ImportError as e:
            raise DriverNotInstalled(
                "psycopg2-binary not installed; pip install -r requirements.txt"
            ) from e

        conn = psycopg2.connect(resolved)
        # Attach a default cursor factory so `conn.cursor()` yields dict rows.
        # psycopg2 connections expose `cursor_factory` as a writable attribute.
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        try:
            yield conn
        finally:
            conn.close()
        return

    raise ConfigError(
        "DATABASE_URL",
        f"Unrecognised database URL scheme: {resolved!r}. "
        "Expected sqlite:/// or postgresql:// (or postgres://).",
    )


__all__ = ["get_connection", "DriverNotInstalled"]
