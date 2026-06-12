#!/usr/bin/env python3
"""SQLite mirror of the paper-trading track record (MP-109, SPA-V415).

The paper-trading track — ``data/trades.json`` + ``data/equity_curve_daily.json``
— is the company's main asset, and until now lived only as JSON files on a
single machine. ``TrackStore`` mirrors both into a local SQLite database
(``data/track.db``) so the track survives a corrupted/lost JSON file and can be
backed up off-site as a single file (see ``spa_core/persistence/backup.py``).

Design rules
============
* SQLite is a **mirror, not the source of truth**. The JSON files written by
  ``cycle_runner`` remain authoritative; this module NEVER modifies them
  (strictly read-only towards ``data/*.json``).
* Idempotent: ``sync_from_json()`` may be re-run any number of times — rows are
  upserted on their natural keys (``trades.trade_id``, ``equity_curve.date``),
  so a re-sync never creates duplicates and an amended JSON record updates the
  mirrored row in place.
* Loss-less: well-known fields get typed columns (schema derived from the real
  ``trades.json`` / ``equity_curve_daily.json`` produced by ``cycle_runner``);
  the complete original record is additionally stored verbatim in a
  ``raw_json`` TEXT column, so unknown/extra fields are never dropped.
* Fail-safe: the public API never raises — any error is logged as WARNING and
  surfaced as ``{"status": "error", ...}`` so the daily cycle can not be
  crashed by persistence (see ``cycle_runner._persist_track``).
* Atomic publication: SQLite work happens on a scratch copy of the database in
  the local temp directory (a native filesystem — SQLite's POSIX locking is
  not available on some mounted/virtual filesystems and fails with
  ``disk I/O error``); the finished database is then published to ``db_path``
  via tempfile + ``os.replace``, the repo-wide atomic-write pattern. A reader
  therefore never observes a half-written ``track.db``.
* Stdlib only: ``sqlite3``, ``json``, ``os``, ``tempfile``, ``datetime``.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timezone

log = logging.getLogger("spa.track_store")

TRADES_FILENAME = "trades.json"
EQUITY_FILENAME = "equity_curve_daily.json"
DB_FILENAME = "track.db"

# Typed columns mirrored from the real cycle_runner schemas. Anything not
# listed here still survives inside raw_json.
_TRADES_DDL = """
CREATE TABLE IF NOT EXISTS trades (
    trade_id             TEXT PRIMARY KEY,
    ts                   TEXT,
    type                 TEXT,
    from_allocation      TEXT,   -- JSON object: pool -> USD
    to_allocation        TEXT,   -- JSON object: pool -> USD
    diff_usd             REAL,
    reason               TEXT,
    model_used           TEXT,
    strategy_loop_active INTEGER,
    capital              REAL,
    is_demo              INTEGER,
    raw_json             TEXT NOT NULL,
    synced_at            TEXT NOT NULL
)
"""

_EQUITY_DDL = """
CREATE TABLE IF NOT EXISTS equity_curve (
    date                  TEXT PRIMARY KEY,  -- YYYY-MM-DD (UTC day)
    open_equity           REAL,
    close_equity          REAL,
    high_equity           REAL,
    low_equity            REAL,
    snapshots             INTEGER,
    daily_return_pct      REAL,
    cumulative_return_pct REAL,
    drawdown_pct          REAL,
    equity                REAL,
    apy_today             REAL,
    daily_yield_usd       REAL,
    positions             TEXT,   -- JSON object: pool -> USD
    raw_json              TEXT NOT NULL,
    synced_at             TEXT NOT NULL
)
"""

_TRADE_UPSERT = """
INSERT INTO trades (
    trade_id, ts, type, from_allocation, to_allocation, diff_usd, reason,
    model_used, strategy_loop_active, capital, is_demo, raw_json, synced_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(trade_id) DO UPDATE SET
    ts = excluded.ts,
    type = excluded.type,
    from_allocation = excluded.from_allocation,
    to_allocation = excluded.to_allocation,
    diff_usd = excluded.diff_usd,
    reason = excluded.reason,
    model_used = excluded.model_used,
    strategy_loop_active = excluded.strategy_loop_active,
    capital = excluded.capital,
    is_demo = excluded.is_demo,
    raw_json = excluded.raw_json,
    synced_at = excluded.synced_at
"""

_EQUITY_UPSERT = """
INSERT INTO equity_curve (
    date, open_equity, close_equity, high_equity, low_equity, snapshots,
    daily_return_pct, cumulative_return_pct, drawdown_pct, equity, apy_today,
    daily_yield_usd, positions, raw_json, synced_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(date) DO UPDATE SET
    open_equity = excluded.open_equity,
    close_equity = excluded.close_equity,
    high_equity = excluded.high_equity,
    low_equity = excluded.low_equity,
    snapshots = excluded.snapshots,
    daily_return_pct = excluded.daily_return_pct,
    cumulative_return_pct = excluded.cumulative_return_pct,
    drawdown_pct = excluded.drawdown_pct,
    equity = excluded.equity,
    apy_today = excluded.apy_today,
    daily_yield_usd = excluded.daily_yield_usd,
    positions = excluded.positions,
    raw_json = excluded.raw_json,
    synced_at = excluded.synced_at
"""


def _num(value):
    """Coerce to float for a REAL column; non-numeric → None (kept in raw_json)."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _intish(value):
    """Coerce to int for an INTEGER column (bools included); else None."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return None


def _json_or_none(value):
    """Serialise dict/list sub-documents into a TEXT column; else None."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return None


class TrackStore:
    """SQLite mirror of the paper-trading track (trades + daily equity curve)."""

    def __init__(self, db_path: str | os.PathLike = os.path.join("data", DB_FILENAME)):
        self.db_path = os.fspath(db_path)

    # ── scratch copy / atomic publish ────────────────────────────────────────

    @staticmethod
    def _copy_bytes(src: str, dst: str) -> None:
        with open(src, "rb") as inp, open(dst, "wb") as out:
            while True:
                chunk = inp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())

    def _publish(self, scratch_db: str) -> None:
        """Atomically replace ``db_path`` with the finished scratch database."""
        parent = os.path.dirname(os.path.abspath(self.db_path)) or "."
        os.makedirs(parent, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=parent, prefix=f".{os.path.basename(self.db_path)}.", suffix=".tmp"
        )
        os.close(fd)
        try:
            self._copy_bytes(scratch_db, tmp_name)
            os.replace(tmp_name, self.db_path)
        except Exception:
            try:
                if os.path.exists(tmp_name):
                    os.remove(tmp_name)
            finally:
                raise

    # ── row builders ────────────────────────────────────────────────────────

    @staticmethod
    def _trade_row(rec: dict, synced_at: str) -> tuple | None:
        trade_id = rec.get("trade_id")
        if not isinstance(trade_id, str) or not trade_id:
            return None  # no natural key → cannot mirror idempotently
        return (
            trade_id,
            rec.get("ts"),
            rec.get("type"),
            _json_or_none(rec.get("from_allocation")),
            _json_or_none(rec.get("to_allocation")),
            _num(rec.get("diff_usd")),
            rec.get("reason"),
            rec.get("model_used"),
            _intish(rec.get("strategy_loop_active")),
            _num(rec.get("capital")),
            _intish(rec.get("is_demo")),
            json.dumps(rec, ensure_ascii=False, sort_keys=True),
            synced_at,
        )

    @staticmethod
    def _equity_row(bar: dict, synced_at: str) -> tuple | None:
        date = bar.get("date")
        if not isinstance(date, str) or not date:
            return None
        return (
            date,
            _num(bar.get("open_equity")),
            _num(bar.get("close_equity")),
            _num(bar.get("high_equity")),
            _num(bar.get("low_equity")),
            _intish(bar.get("snapshots")),
            _num(bar.get("daily_return_pct")),
            _num(bar.get("cumulative_return_pct")),
            _num(bar.get("drawdown_pct")),
            _num(bar.get("equity")),
            _num(bar.get("apy_today")),
            _num(bar.get("daily_yield_usd")),
            _json_or_none(bar.get("positions")),
            json.dumps(bar, ensure_ascii=False, sort_keys=True),
            synced_at,
        )

    # ── public API ──────────────────────────────────────────────────────────

    def sync_from_json(self, data_dir: str | os.PathLike) -> dict:
        """Mirror ``trades.json`` + ``equity_curve_daily.json`` into SQLite.

        Idempotent (upsert on trade_id / date — re-running creates no
        duplicates) and strictly read-only towards the JSON sources. Never
        raises: any problem is logged as WARNING and reported in the returned
        dict. ``status`` is ``"ok"`` only when BOTH sources were read cleanly;
        a missing/corrupt source yields ``status="error"`` (whatever could
        still be parsed is mirrored anyway — partial sync beats no sync).
        """
        data_dir = os.fspath(data_dir)
        synced_at = datetime.now(timezone.utc).isoformat()
        result: dict = {
            "status": "ok",
            "db_path": self.db_path,
            "trades_synced": 0,
            "equity_points_synced": 0,
            "trades_total": 0,
            "equity_points_total": 0,
            "errors": [],
            "synced_at": synced_at,
        }
        try:
            trades = self._load_trades(os.path.join(data_dir, TRADES_FILENAME), result)
            bars = self._load_equity(os.path.join(data_dir, EQUITY_FILENAME), result)

            # SQLite work runs on a scratch copy in the local temp dir (native
            # fs — POSIX locks may be unavailable at db_path's filesystem),
            # then the result is published atomically (tmp + os.replace).
            with tempfile.TemporaryDirectory(prefix="spa_track_") as scratch_dir:
                scratch_db = os.path.join(scratch_dir, DB_FILENAME)
                if os.path.exists(self.db_path):
                    self._copy_bytes(self.db_path, scratch_db)
                conn = sqlite3.connect(scratch_db)
                try:
                    conn.execute(_TRADES_DDL)
                    conn.execute(_EQUITY_DDL)
                    with conn:  # one transaction — all-or-nothing per sync
                        for rec in trades:
                            row = self._trade_row(rec, synced_at) if isinstance(rec, dict) else None
                            if row is None:
                                result["errors"].append("trades: record without trade_id skipped")
                                continue
                            conn.execute(_TRADE_UPSERT, row)
                            result["trades_synced"] += 1
                        for bar in bars:
                            row = self._equity_row(bar, synced_at) if isinstance(bar, dict) else None
                            if row is None:
                                result["errors"].append("equity: bar without date skipped")
                                continue
                            conn.execute(_EQUITY_UPSERT, row)
                            result["equity_points_synced"] += 1
                    result["trades_total"] = conn.execute(
                        "SELECT COUNT(*) FROM trades"
                    ).fetchone()[0]
                    result["equity_points_total"] = conn.execute(
                        "SELECT COUNT(*) FROM equity_curve"
                    ).fetchone()[0]
                finally:
                    conn.close()
                self._publish(scratch_db)
        except Exception as exc:  # noqa: BLE001 — persistence must never raise
            log.warning("track sync failed (%s) — JSON sources untouched", exc)
            result["status"] = "error"
            result["errors"].append(f"{type(exc).__name__}: {exc}")

        if result["errors"] and result["status"] == "ok":
            result["status"] = "error"
        if result["status"] == "error":
            log.warning("track sync finished with errors: %s", "; ".join(result["errors"]))
        return result

    # ── source readers (read-only, defensive) ───────────────────────────────

    @staticmethod
    def _load_trades(path: str, result: dict) -> list:
        if not os.path.exists(path):
            result["errors"].append(f"{TRADES_FILENAME}: missing")
            return []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except (ValueError, OSError) as exc:
            result["errors"].append(f"{TRADES_FILENAME}: unreadable ({exc})")
            return []
        if not isinstance(doc, list):
            result["errors"].append(f"{TRADES_FILENAME}: expected a list, got {type(doc).__name__}")
            return []
        return doc

    @staticmethod
    def _load_equity(path: str, result: dict) -> list:
        if not os.path.exists(path):
            result["errors"].append(f"{EQUITY_FILENAME}: missing")
            return []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except (ValueError, OSError) as exc:
            result["errors"].append(f"{EQUITY_FILENAME}: unreadable ({exc})")
            return []
        # cycle_runner writes {"summary": ..., "daily": [...]}; tolerate a bare list too.
        if isinstance(doc, dict):
            daily = doc.get("daily")
            if isinstance(daily, list):
                return daily
            result["errors"].append(f"{EQUITY_FILENAME}: no usable 'daily' list")
            return []
        if isinstance(doc, list):
            return doc
        result["errors"].append(f"{EQUITY_FILENAME}: unexpected top-level {type(doc).__name__}")
        return []
