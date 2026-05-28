"""
SPA Database URL Resolver — BL-008 Phase 1

Single source of truth for resolving which database backend the application
should talk to. Reads `SPA_DATABASE_URL` from the environment; falls back to a
local SQLite file at `spa_core/database/spa.db`.

Designed to be dependency-free (pure stdlib) so it can be imported from any
module without pulling in psycopg2 or sqlalchemy. The actual driver selection
lives in `spa_core.database.connection`.

URL formats supported:
    sqlite:///absolute/path/to/file.db
    sqlite:///:memory:
    postgresql://user:pass@host:port/dbname
    postgres://user:pass@host:port/dbname        (alias for postgresql://)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# Canonical on-disk SQLite location for the current SQLite-only era.
_DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent / "spa.db"

# Environment variable that drives backend selection.
ENV_VAR = "SPA_DATABASE_URL"


def get_db_url() -> str:
    """
    Return the active database URL.

    Resolution order:
      1. `SPA_DATABASE_URL` environment variable (if non-empty)
      2. SQLite fallback pointing at `spa_core/database/spa.db`

    The fallback is always an absolute path so behaviour does not depend on
    the working directory of the caller.
    """
    env_url = os.environ.get(ENV_VAR, "").strip()
    if env_url:
        return env_url
    return f"sqlite:///{_DEFAULT_SQLITE_PATH}"


def is_postgres(url: Optional[str] = None) -> bool:
    """Return True iff the URL targets a PostgreSQL instance."""
    u = url if url is not None else get_db_url()
    return u.startswith("postgresql://") or u.startswith("postgres://")


def is_sqlite(url: Optional[str] = None) -> bool:
    """Return True iff the URL targets a SQLite database."""
    u = url if url is not None else get_db_url()
    return u.startswith("sqlite:///") or u.startswith("sqlite://")


def get_sqlite_path(url: Optional[str] = None) -> Optional[Path]:
    """
    Extract the filesystem path from a `sqlite:///...` URL.

    Returns:
        Path object for the SQLite file, or None if the URL is not SQLite.
        Special-cases `:memory:` and returns it as Path(':memory:').
    """
    u = url if url is not None else get_db_url()
    if not is_sqlite(u):
        return None
    # Strip the scheme. sqlite:/// → absolute, sqlite:// → relative-ish.
    if u.startswith("sqlite:///"):
        raw = u[len("sqlite:///"):]
    elif u.startswith("sqlite://"):
        raw = u[len("sqlite://"):]
    else:
        return None
    if not raw:
        return None
    return Path(raw)


__all__ = [
    "ENV_VAR",
    "get_db_url",
    "is_postgres",
    "is_sqlite",
    "get_sqlite_path",
]
