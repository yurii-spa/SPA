"""
spa_core/academy/db.py

SQLite data layer for the Academy: Real-Money Onboarding contour.

Design (adapted from spa_core/database/sqlite_manager.py):
  - Self-contained: stdlib sqlite3 only (NO sqlalchemy, NO alembic).
  - WAL mode + foreign keys enabled on every connection.
  - row_factory = sqlite3.Row on every connection.
  - Atomic commits via the connect() context manager.
  - File-based numbered SQL migrations tracked in schema_migrations.

The database path is taken from the SPA_ACADEMY_DB environment variable.
There is NO implicit default path — an unset variable raises ValueError so a
stray dev process can never silently create/write a database in the wrong
place (or clobber a prod file).

LLM FORBIDDEN in this module (monitoring/data-adjacent).
Academy stage 1.
"""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional


# Numbered migration filenames: NNNN_description.sql
_MIGRATION_RE = re.compile(r"^(\d+)_.*\.sql$")

# Default migrations directory shipped alongside this module.
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class AcademyDB:
    """SQLite data manager for the Academy DB.

    Args:
        db_path: Path to the SQLite file.  When omitted, the value of the
                 ``SPA_ACADEMY_DB`` environment variable is used.  If neither
                 is provided, a :class:`ValueError` is raised — there is no
                 implicit default path.

    Raises:
        ValueError: If no path is given and ``SPA_ACADEMY_DB`` is unset/empty.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        resolved = db_path if db_path is not None else os.environ.get("SPA_ACADEMY_DB")
        if not resolved:
            raise ValueError(
                "SPA_ACADEMY_DB is not set. Refusing to guess a database path; "
                "set the SPA_ACADEMY_DB environment variable (or pass db_path=) "
                "to point at the academy sqlite file."
            )
        self.db_path = resolved

    # ── Internal connection helper ─────────────────────────────────────────

    def _make_conn(self) -> sqlite3.Connection:
        """Create and configure a new sqlite3 connection."""
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured connection; commit on exit, rollback on error."""
        conn = self._make_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Migrations ─────────────────────────────────────────────────────────

    @staticmethod
    def _discover_migrations(migrations_dir: Path) -> List[tuple]:
        """Return sorted [(version:int, path:Path), ...] for *.sql migrations."""
        found: List[tuple] = []
        for entry in sorted(os.listdir(migrations_dir)):
            match = _MIGRATION_RE.match(entry)
            if not match:
                continue
            found.append((int(match.group(1)), migrations_dir / entry))
        found.sort(key=lambda item: item[0])
        return found

    def run_migrations(self, migrations_dir=None) -> List[int]:
        """Apply any un-applied numbered SQL migrations, in order.

        Reads ``.sql`` files named ``NNNN_description.sql`` from
        ``migrations_dir`` (defaults to the bundled ``migrations/``), and
        applies only those whose version is not already recorded in the
        ``schema_migrations`` table. Idempotent: a second call is a no-op.

        Returns:
            List of versions applied by this call (empty if already current).
        """
        base = Path(migrations_dir) if migrations_dir is not None else MIGRATIONS_DIR
        migrations = self._discover_migrations(base)

        applied: List[int] = []
        with self.connect() as conn:
            # Ensure the ledger table exists before we probe it.  The very
            # first migration also declares it (IF NOT EXISTS), so this is safe.
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "  version INTEGER PRIMARY KEY,"
                "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
                ")"
            )
            existing = {
                row["version"]
                for row in conn.execute("SELECT version FROM schema_migrations")
            }
            for version, path in migrations:
                if version in existing:
                    continue
                sql = Path(path).read_text(encoding="utf-8")
                conn.executescript(sql)
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
                    (version,),
                )
                applied.append(version)
        return applied

    def schema_version(self) -> int:
        """Return the highest applied migration version (0 if none)."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT MAX(version) AS v FROM schema_migrations"
            ).fetchone()
        return int(row["v"]) if row and row["v"] is not None else 0
