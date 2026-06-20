#!/usr/bin/env python3
"""
tests/test_track_store.py — MP-1451 (Sprint v10.67)

Test suite for spa_core/persistence/track_store.py (TrackStore SQLite mirror).

Tests:
  A. Instantiation & schema (A1–A4)
  B. sync_from_json — trades (B1–B5)
  C. sync_from_json — equity curve (C1–C4)
  D. Idempotency & upsert (D1–D3)
  E. Fail-safe & atomic publish (E1–E4)

Pure stdlib. No network. Offline. Uses tmpdir fixtures.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from spa_core.persistence.track_store import TrackStore, DB_FILENAME


def _make_trades(n: int = 3) -> list:
    """Return a plain list of trade dicts (track_store expects bare list)."""
    trades = []
    for i in range(n):
        trades.append({
            "trade_id": f"trade_{i:04d}",
            "ts": f"2026-06-{10 + i:02d}T08:00:00+00:00",
            "type": "rebalance",
            "from_allocation": {"aave_v3": 50000.0},
            "to_allocation": {"compound_v3": 50000.0},
            "diff_usd": float(100 * i),
            "reason": f"test trade {i}",
            "model_used": "S0",
            "strategy_loop_active": True,
            "capital": 100000.0,
            "is_demo": False,
        })
    return trades


def _make_equity(n: int = 3) -> list:
    """Return a plain list of equity bars (track_store expects bare list or {"daily":[...]})."""
    rows = []
    for i in range(n):
        rows.append({
            "date": f"2026-06-{10 + i:02d}",
            "open_equity": 100000.0 + i * 10,
            "close_equity": 100000.0 + i * 12,
            "high_equity": 100000.0 + i * 15,
            "low_equity": 100000.0 + i * 8,
            "daily_return_pct": 0.01 * i,
            "cumulative_return_pct": 0.01 * i,
            "drawdown_pct": 0.0,
            "equity": 100000.0 + i * 12,
            "snapshots": 1,
        })
    return rows


def _write_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_trades(data_dir: pathlib.Path, trades: list) -> None:
    """Write trades.json as a plain list (required by track_store)."""
    _write_json(data_dir / "trades.json", trades)


def _write_equity(data_dir: pathlib.Path, equity: list) -> None:
    """Write equity_curve_daily.json in {"daily":[...]} envelope."""
    _write_json(data_dir / "equity_curve_daily.json", {"daily": equity})


# ═══════════════════════════════════════════════════════════════════════════════
# Group A — Instantiation & schema
# ═══════════════════════════════════════════════════════════════════════════════

class TestInstantiation(unittest.TestCase):

    def test_A1_track_store_instantiable(self):
        """TrackStore can be created with a temp db_path."""
        with tempfile.TemporaryDirectory() as d:
            ts = TrackStore(db_path=os.path.join(d, "track.db"))
            self.assertIsNotNone(ts)

    def test_A2_db_path_attribute_set(self):
        """TrackStore.db_path is correctly set."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "track.db")
            ts = TrackStore(db_path=p)
            self.assertEqual(str(ts.db_path), p)

    def test_A3_sync_creates_db_file(self):
        """sync_from_json creates the .db file on disk."""
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d) / "data"
            data_dir.mkdir()
            _write_trades(data_dir, _make_trades(2))
            _write_equity(data_dir, _make_equity(2))
            db_path = pathlib.Path(d) / "track.db"
            ts = TrackStore(db_path=str(db_path))
            ts.sync_from_json(data_dir)
            self.assertTrue(db_path.exists(), "track.db should exist after sync")

    def test_A4_sync_returns_dict_with_status(self):
        """sync_from_json returns a dict with a 'status' key."""
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d) / "data"
            data_dir.mkdir()
            _write_trades(data_dir, _make_trades(1))
            _write_equity(data_dir, [])
            ts = TrackStore(db_path=os.path.join(d, "track.db"))
            result = ts.sync_from_json(data_dir)
            self.assertIn("status", result)


# ═══════════════════════════════════════════════════════════════════════════════
# Group B — sync_from_json: trades
# ═══════════════════════════════════════════════════════════════════════════════

class TestSyncTrades(unittest.TestCase):

    def _sync(self, trades, equity=None):
        tmp = tempfile.mkdtemp()
        data_dir = pathlib.Path(tmp) / "data"
        data_dir.mkdir()
        _write_trades(data_dir, trades)
        _write_equity(data_dir, equity or [])
        db_path = pathlib.Path(tmp) / "track.db"
        ts = TrackStore(db_path=str(db_path))
        result = ts.sync_from_json(data_dir)
        return db_path, result

    def test_B1_trades_synced_count(self):
        """Correct number of trades are inserted."""
        trades = _make_trades(3)
        db_path, result = self._sync(trades)
        self.assertIn("trades_synced", result)
        self.assertEqual(result["trades_synced"], 3)

    def test_B2_trade_row_queryable(self):
        """Synced trades can be queried from SQLite."""
        trades = _make_trades(2)
        db_path, _ = self._sync(trades)
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT trade_id FROM trades ORDER BY trade_id").fetchall()
        conn.close()
        ids = [r[0] for r in rows]
        self.assertIn("trade_0000", ids)
        self.assertIn("trade_0001", ids)

    def test_B3_trade_raw_json_stored(self):
        """raw_json column is non-empty for each trade."""
        trades = _make_trades(1)
        db_path, _ = self._sync(trades)
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT raw_json FROM trades LIMIT 1").fetchone()
        conn.close()
        self.assertIsNotNone(row)
        parsed = json.loads(row[0])
        self.assertEqual(parsed["trade_id"], "trade_0000")

    def test_B4_trades_plain_list_accepted(self):
        """trades.json as plain list (bare list) is the correct format."""
        trades = _make_trades(2)
        tmp = tempfile.mkdtemp()
        data_dir = pathlib.Path(tmp) / "data"
        data_dir.mkdir()
        _write_trades(data_dir, trades)  # writes plain list
        _write_equity(data_dir, [])
        db_path = pathlib.Path(tmp) / "track.db"
        ts = TrackStore(db_path=str(db_path))
        result = ts.sync_from_json(data_dir)
        self.assertEqual(result.get("status"), "ok")

    def test_B5_missing_trades_file_is_safe(self):
        """Missing trades.json does not crash sync (returns ok or error, not exception)."""
        tmp = tempfile.mkdtemp()
        data_dir = pathlib.Path(tmp) / "data"
        data_dir.mkdir()
        _write_equity(data_dir, [])
        # No trades.json
        db_path = pathlib.Path(tmp) / "track.db"
        ts = TrackStore(db_path=str(db_path))
        result = ts.sync_from_json(data_dir)
        self.assertIn("status", result)  # Does not raise


# ═══════════════════════════════════════════════════════════════════════════════
# Group C — sync_from_json: equity curve
# ═══════════════════════════════════════════════════════════════════════════════

class TestSyncEquity(unittest.TestCase):

    def _sync(self, equity, trades=None):
        tmp = tempfile.mkdtemp()
        data_dir = pathlib.Path(tmp) / "data"
        data_dir.mkdir()
        _write_trades(data_dir, trades or [])
        _write_equity(data_dir, equity)
        db_path = pathlib.Path(tmp) / "track.db"
        ts = TrackStore(db_path=str(db_path))
        result = ts.sync_from_json(data_dir)
        return db_path, result

    def test_C1_equity_rows_inserted(self):
        """equity_curve rows are inserted with correct count."""
        equity = _make_equity(4)
        db_path, result = self._sync(equity)
        self.assertIn("equity_points_synced", result)
        self.assertEqual(result["equity_points_synced"], 4)

    def test_C2_equity_queryable_by_date(self):
        """Equity rows can be queried by date."""
        equity = _make_equity(2)
        db_path, _ = self._sync(equity)
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT date, close_equity FROM equity_curve WHERE date=?",
            ("2026-06-10",)
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "2026-06-10")

    def test_C3_equity_plain_list_accepted(self):
        """equity_curve_daily.json as plain list is accepted by track_store."""
        equity = _make_equity(3)
        tmp = tempfile.mkdtemp()
        data_dir = pathlib.Path(tmp) / "data"
        data_dir.mkdir()
        _write_trades(data_dir, [])
        # Plain list format (also supported)
        _write_json(data_dir / "equity_curve_daily.json", equity)
        db_path = pathlib.Path(tmp) / "track.db"
        ts = TrackStore(db_path=str(db_path))
        result = ts.sync_from_json(data_dir)
        self.assertEqual(result.get("status"), "ok")
        self.assertEqual(result.get("equity_points_synced"), 3)

    def test_C4_missing_equity_file_is_safe(self):
        """Missing equity_curve_daily.json does not crash sync."""
        tmp = tempfile.mkdtemp()
        data_dir = pathlib.Path(tmp) / "data"
        data_dir.mkdir()
        _write_trades(data_dir, _make_trades(1))
        # No equity file
        db_path = pathlib.Path(tmp) / "track.db"
        ts = TrackStore(db_path=str(db_path))
        result = ts.sync_from_json(data_dir)
        self.assertIn("status", result)  # Does not raise


# ═══════════════════════════════════════════════════════════════════════════════
# Group D — Idempotency & upsert
# ═══════════════════════════════════════════════════════════════════════════════

class TestIdempotency(unittest.TestCase):

    def test_D1_double_sync_no_duplicates(self):
        """Running sync_from_json twice does not create duplicate rows."""
        tmp = tempfile.mkdtemp()
        data_dir = pathlib.Path(tmp) / "data"
        data_dir.mkdir()
        trades = _make_trades(3)
        equity = _make_equity(3)
        _write_trades(data_dir, trades)
        _write_equity(data_dir, equity)
        db_path = pathlib.Path(tmp) / "track.db"
        ts = TrackStore(db_path=str(db_path))
        ts.sync_from_json(data_dir)
        ts.sync_from_json(data_dir)  # second sync
        conn = sqlite3.connect(str(db_path))
        n_trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        n_equity = conn.execute("SELECT COUNT(*) FROM equity_curve").fetchone()[0]
        conn.close()
        self.assertEqual(n_trades, 3)
        self.assertEqual(n_equity, 3)

    def test_D2_updated_trade_row_is_refreshed(self):
        """An amended trade record is updated in-place on re-sync (upsert)."""
        tmp = tempfile.mkdtemp()
        data_dir = pathlib.Path(tmp) / "data"
        data_dir.mkdir()
        trades = _make_trades(1)
        _write_trades(data_dir, trades)
        _write_equity(data_dir, [])
        db_path = pathlib.Path(tmp) / "track.db"
        ts = TrackStore(db_path=str(db_path))
        ts.sync_from_json(data_dir)

        # Amend trade
        trades[0]["reason"] = "AMENDED"
        _write_trades(data_dir, trades)
        ts.sync_from_json(data_dir)

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT reason FROM trades WHERE trade_id='trade_0000'").fetchone()
        conn.close()
        self.assertEqual(row[0], "AMENDED")

    def test_D3_sync_result_ok_on_empty_data(self):
        """sync_from_json with empty lists returns status ok."""
        tmp = tempfile.mkdtemp()
        data_dir = pathlib.Path(tmp) / "data"
        data_dir.mkdir()
        _write_trades(data_dir, [])
        _write_equity(data_dir, [])
        db_path = pathlib.Path(tmp) / "track.db"
        ts = TrackStore(db_path=str(db_path))
        result = ts.sync_from_json(data_dir)
        self.assertEqual(result.get("status"), "ok")


# ═══════════════════════════════════════════════════════════════════════════════
# Group E — Fail-safe & atomic publish
# ═══════════════════════════════════════════════════════════════════════════════

class TestFailSafe(unittest.TestCase):

    def test_E1_nonexistent_data_dir_is_safe(self):
        """Passing a non-existent data_dir doesn't raise — returns error or ok."""
        with tempfile.TemporaryDirectory() as d:
            ts = TrackStore(db_path=os.path.join(d, "track.db"))
            result = ts.sync_from_json(pathlib.Path(d) / "no_such_dir")
            self.assertIn("status", result)

    def test_E2_db_is_valid_sqlite_after_sync(self):
        """The published db file is a valid SQLite3 database."""
        tmp = tempfile.mkdtemp()
        data_dir = pathlib.Path(tmp) / "data"
        data_dir.mkdir()
        _write_trades(data_dir, _make_trades(2))
        _write_equity(data_dir, _make_equity(2))
        db_path = pathlib.Path(tmp) / "track.db"
        ts = TrackStore(db_path=str(db_path))
        ts.sync_from_json(data_dir)
        # Should open as valid SQLite
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        table_names = [t[0] for t in tables]
        self.assertIn("trades", table_names)
        self.assertIn("equity_curve", table_names)

    def test_E3_no_tmp_files_left_after_sync(self):
        """No .tmp files linger in data/ after sync."""
        tmp = tempfile.mkdtemp()
        data_dir = pathlib.Path(tmp) / "data"
        data_dir.mkdir()
        _write_trades(data_dir, _make_trades(2))
        _write_equity(data_dir, [])
        db_path = pathlib.Path(tmp) / "track.db"
        ts = TrackStore(db_path=str(db_path))
        ts.sync_from_json(data_dir)
        tmp_files = list(pathlib.Path(tmp).glob("**/*.tmp"))
        self.assertEqual(len(tmp_files), 0, f"Leftover tmp files: {tmp_files}")

    def test_E4_db_filename_constant_correct(self):
        """DB_FILENAME constant matches expected value."""
        self.assertEqual(DB_FILENAME, "track.db")


if __name__ == "__main__":
    unittest.main(verbosity=2)
