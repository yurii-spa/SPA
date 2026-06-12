#!/usr/bin/env python3
"""SQLite persistence layer for SPA paper trading data (MP-109).

Stores equity_curve, daily_reports, analytics and allocation_history in a
local SQLite database (``data/spa.db``).  This layer complements
``track_store.py`` (which mirrors trades + equity as a read-only mirror) by
also persisting derived artefacts — daily reports, analytics snapshots and
allocation history — that live only as JSON files today.

Design rules
============
* Atomic writes everywhere (tmp + os.replace at the call-site; WAL journal
  mode is used for concurrent read safety on file-backed databases).
* Fail-safe: callers should wrap top-level public functions in try/except so
  that a persistence failure never crashes the daily cycle.
* Idempotent: upsert on (date) primary keys — safe to run multiple times.
* Lazy schema init: every public function calls ``init_db(db_path)`` first so
  the caller never has to worry about initialisation order.
* Stdlib only (runtime): ``json``, ``os``, ``shutil``, ``tempfile``, ``datetime``.
  ``spa_core.database.connection`` is also stdlib-only for the SQLite path.
* Testing: all public functions accept an optional ``db_path`` kwarg so that
  tests can pass ``":memory:"`` or a ``tmp_path`` without touching the real DB.

BL-008 Phase 2
==============
``get_connection()`` now delegates to ``spa_core.database.connection.get_connection``
(the dual-driver abstraction) via a context-manager wrapper.  All call-sites
inside this module have been migrated from the old
``conn = get_connection(path); try: ...; finally: conn.close()`` pattern to
``with get_connection(path) as conn: ...``.  External consumers that imported
only the public helper functions (``init_db``, ``upsert_*``, ``get_*``) are
unaffected.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from spa_core.database.connection import get_connection as _abstract_get_conn

log = logging.getLogger("spa.db")

# ─── Paths ───────────────────────────────────────────────────────────────────
# spa_core/persistence/db.py → parents[0]=persistence, [1]=spa_core, [2]=repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = str(_REPO_ROOT / "data" / "spa.db")
BACKUP_DIR = str(_REPO_ROOT / "data" / "backups")

# ─── DDL ─────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS equity_curve (
    date        TEXT PRIMARY KEY,
    equity      REAL NOT NULL,
    pnl_usd     REAL NOT NULL DEFAULT 0.0,
    pnl_pct     REAL NOT NULL DEFAULT 0.0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_reports (
    date        TEXT PRIMARY KEY,
    report_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics (
    date            TEXT PRIMARY KEY,
    analytics_json  TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS allocation_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,
    allocation_json TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
"""

# ─── Internal helpers ────────────────────────────────────────────────────────


def _db_url(path: str | None) -> str:
    """Convert a db_path string (or None) to a ``sqlite://`` URL.

    Handles the ``:memory:`` special case and ensures absolute paths for
    file-backed databases so the URL is unambiguous.
    """
    p = path if path is not None else DB_PATH
    if p == ":memory:":
        return "sqlite:///:memory:"
    return f"sqlite:///{os.path.abspath(p)}"


# ─── Connection ──────────────────────────────────────────────────────────────


@contextmanager
def get_connection(db_path: str | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager yielding a SQLite connection with WAL mode enabled.

    Parameters
    ----------
    db_path:
        Path to the database file.  Pass ``":memory:"`` for an in-memory
        database (useful in tests).  Defaults to the module-level
        :data:`DB_PATH`.

    BL-008 Phase 2 — delegates to ``spa_core.database.connection.get_connection``
    so the backend is env-driven (SQLite default, Postgres when
    ``SPA_DATABASE_URL`` is set).  WAL journal mode is applied after the
    connection is established for file-backed databases.
    """
    with _abstract_get_conn(_db_url(db_path)) as conn:
        # Enable WAL mode for concurrent read safety on file-backed databases.
        # This is a no-op (silently ignored) for :memory: connections.
        effective = db_path if db_path is not None else DB_PATH
        if effective != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
        yield conn


# ─── Schema initialisation ───────────────────────────────────────────────────


def init_db(db_path: str | None = None) -> None:
    """Create all tables if they do not exist yet (idempotent)."""
    with get_connection(db_path) as conn:
        conn.executescript(_DDL)
        conn.commit()


# ─── Equity curve ────────────────────────────────────────────────────────────


def upsert_equity_point(
    date_str: str,
    equity: float,
    pnl_usd: float = 0.0,
    pnl_pct: float = 0.0,
    db_path: str | None = None,
) -> None:
    """Insert or update a single equity data point."""
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO equity_curve (date, equity, pnl_usd, pnl_pct, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                equity     = excluded.equity,
                pnl_usd    = excluded.pnl_usd,
                pnl_pct    = excluded.pnl_pct,
                created_at = excluded.created_at
            """,
            (date_str, float(equity), float(pnl_usd), float(pnl_pct), now),
        )
        conn.commit()


def get_equity_curve(days: int | None = None, db_path: str | None = None) -> list[dict]:
    """Return the equity curve as a list of dicts, ordered by date ascending.

    Parameters
    ----------
    days:
        Number of most-recent days to return.  ``None`` returns all rows.
    """
    init_db(db_path)
    with get_connection(db_path) as conn:
        if days is None:
            rows = conn.execute(
                "SELECT date, equity, pnl_usd, pnl_pct, created_at "
                "FROM equity_curve ORDER BY date ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT date, equity, pnl_usd, pnl_pct, created_at "
                "FROM equity_curve ORDER BY date DESC LIMIT ?",
                (days,),
            ).fetchall()
            rows = list(reversed(rows))
        return [dict(r) for r in rows]


# ─── Daily reports ───────────────────────────────────────────────────────────


def upsert_daily_report(
    date_str: str,
    report: dict,
    db_path: str | None = None,
) -> None:
    """Store (or replace) a daily report for ``date_str``."""
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO daily_reports (date, report_json, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                report_json = excluded.report_json,
                created_at  = excluded.created_at
            """,
            (date_str, json.dumps(report, ensure_ascii=False), now),
        )
        conn.commit()


def get_daily_report(
    date_str: str,
    db_path: str | None = None,
) -> dict | None:
    """Return the daily report for ``date_str``, or ``None`` if absent."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT report_json FROM daily_reports WHERE date = ?", (date_str,)
        ).fetchone()
        return json.loads(row["report_json"]) if row else None


# ─── Analytics ───────────────────────────────────────────────────────────────


def upsert_analytics(
    date_str: str,
    analytics: dict,
    db_path: str | None = None,
) -> None:
    """Store (or replace) an analytics snapshot for ``date_str``."""
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO analytics (date, analytics_json, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                analytics_json = excluded.analytics_json,
                created_at     = excluded.created_at
            """,
            (date_str, json.dumps(analytics, ensure_ascii=False), now),
        )
        conn.commit()


def get_analytics(date_str: str, db_path: str | None = None) -> dict | None:
    """Return the analytics snapshot for ``date_str``, or ``None``."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT analytics_json FROM analytics WHERE date = ?", (date_str,)
        ).fetchone()
        return json.loads(row["analytics_json"]) if row else None


# ─── Allocation history ──────────────────────────────────────────────────────


def upsert_allocation(
    date_str: str,
    allocation: dict,
    db_path: str | None = None,
) -> None:
    """Append an allocation snapshot to the history table (append-only)."""
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO allocation_history (date, allocation_json, created_at)
            VALUES (?, ?, ?)
            """,
            (date_str, json.dumps(allocation, ensure_ascii=False), now),
        )
        conn.commit()


def get_allocation_history(
    days: int = 30,
    db_path: str | None = None,
) -> list[dict]:
    """Return the most recent ``days`` allocation snapshots, oldest first."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, date, allocation_json, created_at
            FROM allocation_history
            ORDER BY id DESC
            LIMIT ?
            """,
            (days,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "date": r["date"],
                "allocation": json.loads(r["allocation_json"]),
                "created_at": r["created_at"],
            }
            for r in reversed(rows)
        ]


# ─── Backup ──────────────────────────────────────────────────────────────────


def create_daily_backup(
    db_path: str | None = None,
    backup_dir: str | None = None,
) -> str:
    """Copy ``spa.db`` to ``<backup_dir>/spa_YYYY-MM-DD.db``.

    Returns the absolute path of the newly created backup file.
    The backup directory is created if it does not exist.
    """
    src = db_path if db_path is not None else DB_PATH
    dst_dir = backup_dir if backup_dir is not None else BACKUP_DIR
    today = date.today().isoformat()
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, f"spa_{today}.db")
    # Atomic copy: write to a tmp file in the same directory, then rename.
    fd, tmp_name = tempfile.mkstemp(dir=dst_dir, prefix=".spa_backup_", suffix=".tmp")
    os.close(fd)
    try:
        shutil.copy2(src, tmp_name)
        os.replace(tmp_name, dst)
    except Exception:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise
    log.info("DB backup created: %s", dst)
    return os.path.abspath(dst)


def cleanup_old_backups(
    keep_days: int = 30,
    backup_dir: str | None = None,
) -> int:
    """Remove backup files older than ``keep_days`` days.

    Only files matching ``spa_YYYY-MM-DD.db`` inside ``backup_dir`` are
    removed — nothing outside that directory is ever touched.

    Returns the number of files deleted.
    """
    dst_dir = backup_dir if backup_dir is not None else BACKUP_DIR
    if not os.path.isdir(dst_dir):
        return 0

    pattern = re.compile(r"^spa_(\d{4}-\d{2}-\d{2})\.db$")
    today = date.today()
    deleted = 0

    for fname in os.listdir(dst_dir):
        m = pattern.match(fname)
        if not m:
            continue
        try:
            file_date = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        age_days = (today - file_date).days
        if age_days > keep_days:
            fpath = os.path.join(dst_dir, fname)
            # Safety: resolved path must be inside backup_dir.
            if not os.path.abspath(fpath).startswith(os.path.abspath(dst_dir)):
                continue
            try:
                os.remove(fpath)
                deleted += 1
                log.info("Removed old backup: %s", fname)
            except OSError as exc:
                log.warning("Could not remove old backup %s: %s", fname, exc)

    return deleted


# ─── JSON migration ──────────────────────────────────────────────────────────


def migrate_json_to_db(
    data_dir: str | None = None,
    db_path: str | None = None,
) -> dict:
    """One-time (idempotent) import of existing JSON data into SQLite.

    Reads:
    * ``data/equity_curve_daily.json`` → ``equity_curve`` table
    * ``data/daily_report_YYYY-MM-DD.json`` → ``daily_reports`` table
    * ``data/analytics_summary.json`` → ``analytics`` table

    Returns ``{"equity_points": N, "reports": N, "analytics": N}``.
    Safe to run multiple times (upsert semantics, no duplicates).
    """
    repo_data = Path(data_dir) if data_dir else (_REPO_ROOT / "data")
    counts: dict[str, int] = {"equity_points": 0, "reports": 0, "analytics": 0}

    init_db(db_path)

    # ── equity_curve_daily.json ──────────────────────────────────────────────
    eq_path = repo_data / "equity_curve_daily.json"
    if eq_path.exists():
        try:
            doc = json.loads(eq_path.read_text(encoding="utf-8"))
            bars: list = []
            if isinstance(doc, dict):
                bars = doc.get("daily", [])
            elif isinstance(doc, list):
                bars = doc
            for bar in bars:
                if not isinstance(bar, dict):
                    continue
                d = bar.get("date")
                eq = bar.get("close_equity") or bar.get("equity")
                if not d or eq is None:
                    continue
                pnl_usd = bar.get("daily_yield_usd", 0.0) or 0.0
                pnl_pct = bar.get("daily_return_pct", 0.0) or 0.0
                upsert_equity_point(d, float(eq), float(pnl_usd), float(pnl_pct), db_path)
                counts["equity_points"] += 1
        except Exception as exc:
            log.warning("migrate equity_curve failed: %s", exc)

    # ── daily_report_*.json ─────────────────────────────────────────────────
    try:
        for p in sorted(repo_data.glob("daily_report_*.json")):
            stem = p.stem  # daily_report_2026-06-10
            date_part = stem[len("daily_report_"):]
            try:
                date.fromisoformat(date_part)  # validate format
            except ValueError:
                continue
            try:
                report = json.loads(p.read_text(encoding="utf-8"))
                upsert_daily_report(date_part, report, db_path)
                counts["reports"] += 1
            except Exception as exc:
                log.warning("migrate report %s failed: %s", p.name, exc)
    except Exception as exc:
        log.warning("migrate daily_reports glob failed: %s", exc)

    # ── analytics_summary.json ──────────────────────────────────────────────
    an_path = repo_data / "analytics_summary.json"
    if an_path.exists():
        try:
            analytics = json.loads(an_path.read_text(encoding="utf-8"))
            if isinstance(analytics, dict):
                d = (
                    analytics.get("last_date")
                    or analytics.get("date")
                    or date.today().isoformat()
                )
                upsert_analytics(d, analytics, db_path)
                counts["analytics"] += 1
        except Exception as exc:
            log.warning("migrate analytics failed: %s", exc)

    log.info("Migration complete: %s", counts)
    return counts
