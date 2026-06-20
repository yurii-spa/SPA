"""
spa_core/database/sqlite_manager.py

SQLite-based data layer for SPA.
Stores paper trading history, evidence records, adapter APY history,
and system events. Falls back gracefully when SQLite is unavailable.

Design:
  - Self-contained: no external dependencies (stdlib only).
  - WAL mode + foreign keys enabled on every connection.
  - Atomic commits via context manager (_conn).
  - All inserts return the new rowid.
  - Separate from the existing BL-008 connection layer (which owns
    protocols/apy_snapshots/paper_trades). This manager owns the
    evidence / paper-trading-record side of the DB.

Tables:
  paper_trading_records  — daily cycle output per strategy
  adapter_apy_history    — per-adapter APY time series
  evidence_records       — GoLive evidence scoring history
  system_events          — audit log of significant events

LLM FORBIDDEN in this module (monitoring-adjacent).
MP-1539 (v11.55)
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional


class SQLiteManager:
    """SQLite data manager for SPA local data storage.

    Args:
        db_path: Path to the SQLite file.  Default ``data/spa.db``.
                 Use ``:memory:`` for ephemeral/test databases.
    """

    SCHEMA: str = """
    CREATE TABLE IF NOT EXISTS paper_trading_records (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        date          TEXT    NOT NULL,
        cycle_number  INTEGER NOT NULL,
        strategy_id   TEXT    NOT NULL,
        portfolio_nav REAL    NOT NULL,
        daily_pnl     REAL    NOT NULL,
        daily_apy     REAL    NOT NULL,
        allocation_json TEXT,
        created_at    TEXT    DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS adapter_apy_history (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        date         TEXT    NOT NULL,
        adapter_name TEXT    NOT NULL,
        apy          REAL    NOT NULL,
        source       TEXT    DEFAULT 'defillama',
        created_at   TEXT    DEFAULT (datetime('now')),
        UNIQUE (date, adapter_name)
    );

    CREATE TABLE IF NOT EXISTS evidence_records (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        date              TEXT    NOT NULL UNIQUE,
        daily_cycle_pts   REAL    NOT NULL,
        apy_tracking_pts  REAL    NOT NULL,
        risk_policy_pts   REAL    NOT NULL,
        total_pts         REAL    NOT NULL,
        is_seed           INTEGER DEFAULT 0,
        created_at        TEXT    DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS system_events (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type     TEXT    NOT NULL,
        description    TEXT    NOT NULL,
        severity       TEXT    DEFAULT 'INFO',
        correlation_id TEXT,
        metadata_json  TEXT,
        created_at     TEXT    DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_paper_trading_date
        ON paper_trading_records(date);
    CREATE INDEX IF NOT EXISTS idx_adapter_apy_date
        ON adapter_apy_history(date, adapter_name);
    CREATE INDEX IF NOT EXISTS idx_evidence_date
        ON evidence_records(date);
    CREATE INDEX IF NOT EXISTS idx_events_type
        ON system_events(event_type, created_at);
    """

    def __init__(self, db_path: str = "data/spa.db") -> None:
        self.db_path = db_path
        # Ensure parent directory exists (skip for :memory:)
        if db_path != ":memory:":
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        # For in-memory databases, keep a single persistent connection so the
        # schema survives across method calls (each sqlite3.connect(":memory:")
        # creates an isolated, empty database).
        self._mem_conn: Optional[sqlite3.Connection] = None
        if db_path == ":memory:":
            self._mem_conn = self._make_conn()
        self._init_db()

    # ── Internal connection helper ─────────────────────────────────────────

    def _make_conn(self) -> sqlite3.Connection:
        """Create and configure a new sqlite3 connection."""
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured sqlite3 connection; commit on exit, rollback on error.

        For in-memory databases the same persistent connection is reused;
        for on-disk databases a new connection is created per call (WAL-safe).
        """
        if self._mem_conn is not None:
            # In-memory: reuse the single connection, never close it.
            try:
                yield self._mem_conn
                self._mem_conn.commit()
            except Exception:
                self._mem_conn.rollback()
                raise
        else:
            conn = self._make_conn()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_db(self) -> None:
        """Apply the schema (CREATE IF NOT EXISTS — idempotent)."""
        with self._conn() as conn:
            conn.executescript(self.SCHEMA)

    # ── paper_trading_records ──────────────────────────────────────────────

    def insert_paper_record(
        self,
        date: str,
        cycle_number: int,
        strategy_id: str,
        portfolio_nav: float,
        daily_pnl: float,
        daily_apy: float,
        allocation: Optional[Dict] = None,
    ) -> int:
        """Insert one paper-trading cycle record.

        Returns:
            rowid of the inserted row.
        """
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO paper_trading_records
                    (date, cycle_number, strategy_id, portfolio_nav,
                     daily_pnl, daily_apy, allocation_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    date,
                    cycle_number,
                    strategy_id,
                    portfolio_nav,
                    daily_pnl,
                    daily_apy,
                    json.dumps(allocation) if allocation is not None else None,
                ),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def get_paper_records(self, limit: int = 30) -> List[Dict]:
        """Return the most recent `limit` paper-trading records, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM paper_trading_records ORDER BY date DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_paper_records_by_date(self, date: str) -> List[Dict]:
        """Return all records for a specific ISO date."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM paper_trading_records WHERE date = ? ORDER BY id",
                (date,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_paper_records_by_strategy(
        self, strategy_id: str, limit: int = 30
    ) -> List[Dict]:
        """Return records for a specific strategy, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM paper_trading_records
                WHERE strategy_id = ?
                ORDER BY date DESC
                LIMIT ?
                """,
                (strategy_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def count_paper_records(self) -> int:
        """Return total count of paper trading records."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM paper_trading_records"
            ).fetchone()[0]

    # ── adapter_apy_history ────────────────────────────────────────────────

    def insert_adapter_apy(
        self,
        date: str,
        adapter_name: str,
        apy: float,
        source: str = "defillama",
    ) -> None:
        """Upsert an adapter APY snapshot (INSERT OR REPLACE by date+adapter)."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO adapter_apy_history
                    (date, adapter_name, apy, source)
                VALUES (?, ?, ?, ?)
                """,
                (date, adapter_name, apy, source),
            )

    def get_adapter_apy_history(
        self, adapter_name: str, days: int = 30
    ) -> List[Dict]:
        """Return APY history for one adapter, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM adapter_apy_history
                WHERE adapter_name = ?
                ORDER BY date DESC
                LIMIT ?
                """,
                (adapter_name, days),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_adapters_on_date(self, date: str) -> List[Dict]:
        """Return APY records for all adapters on a given date."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM adapter_apy_history WHERE date = ? ORDER BY adapter_name",
                (date,),
            ).fetchall()
            return [dict(r) for r in rows]

    def count_adapter_apy_records(self) -> int:
        """Return total count of adapter APY records."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM adapter_apy_history"
            ).fetchone()[0]

    # ── evidence_records ───────────────────────────────────────────────────

    def insert_evidence_record(
        self,
        date: str,
        daily_cycle_pts: float,
        apy_tracking_pts: float,
        risk_policy_pts: float,
        total_pts: float,
        is_seed: bool = False,
    ) -> int:
        """Insert one evidence record.

        INSERT OR REPLACE — if date already exists, it is overwritten.

        Returns:
            rowid of the inserted/replaced row.
        """
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT OR REPLACE INTO evidence_records
                    (date, daily_cycle_pts, apy_tracking_pts,
                     risk_policy_pts, total_pts, is_seed)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    date,
                    daily_cycle_pts,
                    apy_tracking_pts,
                    risk_policy_pts,
                    total_pts,
                    1 if is_seed else 0,
                ),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def get_evidence_records(self, limit: int = 30) -> List[Dict]:
        """Return the most recent `limit` evidence records, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence_records ORDER BY date DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_evidence_by_date(self, date: str) -> Optional[Dict]:
        """Return evidence record for a specific date, or None."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM evidence_records WHERE date = ?",
                (date,),
            ).fetchone()
            return dict(row) if row else None

    def count_evidence_records(self) -> int:
        """Return total count of evidence records."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM evidence_records"
            ).fetchone()[0]

    def count_evidence_non_seed(self) -> int:
        """Return count of real (non-seed) evidence records."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM evidence_records WHERE is_seed = 0"
            ).fetchone()[0]

    # ── system_events ──────────────────────────────────────────────────────

    def log_event(
        self,
        event_type: str,
        description: str,
        severity: str = "INFO",
        correlation_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> int:
        """Insert one system event into the audit log.

        Returns:
            rowid of the inserted row.
        """
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO system_events
                    (event_type, description, severity, correlation_id, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    description,
                    severity,
                    correlation_id,
                    json.dumps(metadata) if metadata is not None else None,
                ),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def get_events(
        self,
        event_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Return recent system events, optionally filtered by type."""
        with self._conn() as conn:
            if event_type:
                rows = conn.execute(
                    """
                    SELECT * FROM system_events
                    WHERE event_type = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (event_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM system_events ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def count_events(self, severity: Optional[str] = None) -> int:
        """Return event count, optionally filtered by severity."""
        with self._conn() as conn:
            if severity:
                return conn.execute(
                    "SELECT COUNT(*) FROM system_events WHERE severity = ?",
                    (severity,),
                ).fetchone()[0]
            return conn.execute(
                "SELECT COUNT(*) FROM system_events"
            ).fetchone()[0]

    # ── Introspection / health ─────────────────────────────────────────────

    def table_counts(self) -> Dict[str, int]:
        """Return row counts for all managed tables."""
        return {
            "paper_trading_records": self.count_paper_records(),
            "adapter_apy_history": self.count_adapter_apy_records(),
            "evidence_records": self.count_evidence_records(),
            "system_events": self.count_events(),
        }

    def health_check(self) -> Dict[str, object]:
        """Return a health dict suitable for monitoring / dashboards."""
        try:
            counts = self.table_counts()
            return {
                "status": "ok",
                "db_path": self.db_path,
                "table_counts": counts,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "error",
                "db_path": self.db_path,
                "error": str(exc),
            }
