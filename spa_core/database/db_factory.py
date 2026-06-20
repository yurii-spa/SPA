"""
spa_core/database/db_factory.py

Database factory — returns SQLite or PostgreSQL manager based on config.
Allows seamless backend switching when deploying to production.

Resolution order:
  1. DATABASE_URL environment variable
     • sqlite:///<path>   → SQLiteManager at that path
     • :memory:           → SQLiteManager (in-memory, for tests)
     • postgresql://...   → NotImplementedError (see ADR-031)
     • postgres://...     → NotImplementedError (see ADR-031)
  2. SQLITE_PATH environment variable   → SQLiteManager at that path
  3. Default                            → SQLiteManager at <base_dir>/data/spa.db

Design notes:
  - Callers use get_db_manager() and stay backend-agnostic.
  - get_db_url() masks the password in logs.
  - No external dependencies (stdlib only).
  - PostgreSQL path raises NotImplementedError with an ADR reference until
    psycopg2 / async driver is approved in ADR-031.

LLM FORBIDDEN in this module.
MP-1541 (v11.57)
"""

from __future__ import annotations

import os
import re
from typing import Optional

from spa_core.database.sqlite_manager import SQLiteManager


# ─── Public API ───────────────────────────────────────────────────────────────


def get_db_manager(base_dir: str = ".") -> SQLiteManager:
    """Return a SQLiteManager configured from environment variables.

    Resolution order:
      1. DATABASE_URL env var:
         - "sqlite:///<path>" → SQLiteManager(db_path=<path>)
         - ":memory:"         → SQLiteManager(db_path=":memory:")
         - "postgresql://..."  → NotImplementedError
         - "postgres://..."    → NotImplementedError
      2. SQLITE_PATH env var  → SQLiteManager(db_path=<SQLITE_PATH>)
      3. default              → SQLiteManager(db_path=<base_dir>/data/spa.db)

    Args:
        base_dir: Root directory used for the default SQLite path.  Does not
                  affect anything when DATABASE_URL or SQLITE_PATH is set.

    Returns:
        A configured SQLiteManager instance.

    Raises:
        NotImplementedError: When DATABASE_URL targets a PostgreSQL instance.
            See docs/adr/ADR-031-baseanalytics-migration.md for the plan.
        ValueError: When DATABASE_URL has an unrecognised scheme.
    """
    db_url = os.environ.get("DATABASE_URL", "").strip()

    if db_url:
        return _manager_from_url(db_url)

    # SQLITE_PATH override
    sqlite_path = os.environ.get("SQLITE_PATH", "").strip()
    if sqlite_path:
        return SQLiteManager(db_path=sqlite_path)

    # Default: <base_dir>/data/spa.db
    default_path = os.path.join(base_dir, "data", "spa.db")
    return SQLiteManager(db_path=default_path)


def get_db_url() -> str:
    """Return the current database URL with the password masked.

    Safe to include in log messages and dashboards.

    Returns:
        E.g. "sqlite:///data/spa.db" or "postgresql://user:***@host:5432/spa".
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        sqlite_path = os.environ.get("SQLITE_PATH", "data/spa.db").strip()
        return f"sqlite:///{sqlite_path}"
    return _mask_password(url)


def is_postgres_configured() -> bool:
    """Return True iff DATABASE_URL targets a PostgreSQL instance."""
    url = os.environ.get("DATABASE_URL", "").strip()
    return url.startswith("postgresql://") or url.startswith("postgres://")


def is_sqlite_configured() -> bool:
    """Return True iff no DATABASE_URL is set or it targets SQLite."""
    return not is_postgres_configured()


# ─── Internal helpers ────────────────────────────────────────────────────────


def _manager_from_url(url: str) -> SQLiteManager:
    """Parse DATABASE_URL and return the appropriate manager."""
    if url == ":memory:":
        return SQLiteManager(db_path=":memory:")

    if url.startswith("sqlite:///"):
        path = url[len("sqlite:///"):]
        if not path:
            raise ValueError(
                f"DATABASE_URL sqlite:/// path is empty: {url!r}"
            )
        return SQLiteManager(db_path=path)

    if url.startswith("sqlite://"):
        # sqlite:// (two slashes) — treat remainder as relative path
        path = url[len("sqlite://"):]
        if not path:
            raise ValueError(
                f"DATABASE_URL sqlite:// path is empty: {url!r}"
            )
        return SQLiteManager(db_path=path)

    if url.startswith("postgresql://") or url.startswith("postgres://"):
        raise NotImplementedError(
            "PostgreSQL manager is not yet implemented. "
            "See docs/adr/ADR-031-baseanalytics-migration.md for the roadmap. "
            f"Configured URL: {_mask_password(url)}"
        )

    raise ValueError(
        f"DATABASE_URL has an unrecognised scheme: {url!r}. "
        "Supported: sqlite:///<path>, postgresql://..., postgres://..."
    )


def _mask_password(url: str) -> str:
    """Replace the password in a DB URL with '***'."""
    return re.sub(r"(://[^:@]+):[^@]+@", r"\1:***@", url)
