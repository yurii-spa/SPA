"""
spa_core.database.side_store — the door for SELF-CONTAINED sqlite stores (BL-008 Phase 2).

ADR-005 Phase 2 moves call-sites of the MAIN database (``SPA_DATABASE_URL`` /
``spa_core/database/spa.db``) behind ``connection.get_connection()`` so that the
backend can later flip to Postgres. Some modules own a SEPARATE sqlite file that is
not, and will never be, part of that database: a market-data cache with immutable
candles, an append-only evidence journal, a disposable memory index built in a tmp
file and ``os.replace``-d into place, a throw-away COPY of the portfolio DB checked
with the sqlite-native ``PRAGMA quick_check``. Routing those through
``get_connection()`` would be wrong twice over: under a Postgres URL it would point
them at the main DB, and it silently re-wraps the connection (``row_factory``,
``mkdir``) that their callers rely on.

This module is the one sanctioned door for such stores. It is deliberately THIN —
it returns exactly what ``sqlite3.connect(path, timeout=...)`` returns:

* ``isolation_level`` is the stdlib default (deferred transactions, explicit
  ``commit()``) unless the caller passes one;
* ``timeout`` is passed through explicitly (stdlib default 5.0 s);
* no ``row_factory``, no ``PRAGMA``, no ``journal_mode`` change, no ``mkdir`` —
  schema, triggers and directory creation stay with the store's owner;
* ``readonly=True`` opens ``file:<path>?mode=ro`` with ``uri=True`` (a missing file
  is then an error, never a silently created empty store).

The one thing it adds is a REFUSAL: it will not open the main database. That is
what keeps this door from becoming a way around Phase 2 — the main DB goes only
through ``get_connection()``, a side store only through here, and raw
``sqlite3.connect`` outside both stays at zero (``migrate_callsites``).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional, Union

from .db_url import _DEFAULT_SQLITE_PATH, get_db_url, get_sqlite_path

PathLike = Union[str, "os.PathLike[str]"]

#: Same as ``sqlite3.connect``'s own default, named so the pass-through is visible.
DEFAULT_TIMEOUT_S = 5.0

_UNSET = object()


class MainDatabaseRefused(ValueError):
    """Raised when a side-store open targets the MAIN database (use get_connection())."""


def _main_db_paths() -> list[Path]:
    out = [_DEFAULT_SQLITE_PATH]
    env_path = get_sqlite_path(get_db_url())
    if env_path is not None and str(env_path) != ":memory:":
        out.append(env_path)
    return out


def _is_main_db(path: Path) -> bool:
    if str(path) == ":memory:":
        return False
    target = os.path.realpath(path)
    for main in _main_db_paths():
        if os.path.realpath(main) == target:
            return True
        try:
            if path.exists() and main.exists() and os.path.samefile(path, main):
                return True
        except OSError:
            continue
    return False


def open_side_store(
    path: PathLike,
    *,
    readonly: bool = False,
    timeout: float = DEFAULT_TIMEOUT_S,
    isolation_level: Optional[str] = _UNSET,  # type: ignore[assignment]
) -> sqlite3.Connection:
    """Open a self-contained sqlite store at *path* — never the main database.

    Returns the plain ``sqlite3.Connection`` (caller closes / commits it, as before).
    Raises :class:`MainDatabaseRefused` if *path* resolves to the main DB.
    """
    p = Path(os.fspath(path))
    if _is_main_db(p):
        raise MainDatabaseRefused(
            f"{p} is the main database — open it through "
            "spa_core.database.connection.get_connection(), not the side-store door")
    kwargs: dict = {"timeout": timeout}
    if isolation_level is not _UNSET:
        kwargs["isolation_level"] = isolation_level
    if readonly:
        return sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, **kwargs)
    return sqlite3.connect(str(p), **kwargs)


__all__ = ["open_side_store", "MainDatabaseRefused", "DEFAULT_TIMEOUT_S"]
