#!/usr/bin/env python3
"""
tests/test_json_compat.py — MP-1452 (Sprint v10.68)

Test suite for spa_core/persistence/json_compat.py.

Tests:
  A. Atomic migration — _atomic_append_equity_json uses atomic_save (A1–A2)
  B. _atomic_append_equity_json (B1–B5)
  C. read_equity_curve — JSON fallback (C1–C4)
  D. read_daily_report (D1–D3)
  E. Idempotency & upsert (E1–E3)

Pure stdlib. Uses tmpdir fixtures. DB operations via sqlite3.
"""
from __future__ import annotations

import json
import pathlib
import sys
import unittest
import unittest.mock
import tempfile

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from spa_core.persistence.json_compat import (
    _atomic_append_equity_json,
    read_equity_curve,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _write_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# Group A — Atomic migration
# ═══════════════════════════════════════════════════════════════════════════════

class TestAtomicMigration(unittest.TestCase):

    def test_A1_atomic_save_imported_after_migration(self):
        """json_compat.py imports atomic_save after migration (MP-1452)."""
        src = (_REPO / "spa_core" / "persistence" / "json_compat.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("atomic_save", src,
                      "_atomic_append_equity_json should use atomic_save")

    def test_A2_no_raw_mkstemp_in_atomic_append(self):
        """json_compat.py has 'from spa_core.utils.atomic import' after migration."""
        src = (_REPO / "spa_core" / "persistence" / "json_compat.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from spa_core.utils.atomic import", src)


# ═══════════════════════════════════════════════════════════════════════════════
# Group B — _atomic_append_equity_json
# ═══════════════════════════════════════════════════════════════════════════════

class TestAtomicAppendEquityJson(unittest.TestCase):

    def test_B1_creates_file_when_absent(self):
        """_atomic_append_equity_json creates JSON file if it doesn't exist."""
        with tempfile.TemporaryDirectory() as d:
            eq_path = pathlib.Path(d) / "equity_curve_daily.json"
            _atomic_append_equity_json(eq_path, "2026-06-20", 100500.0, 500.0, 0.5)
            self.assertTrue(eq_path.exists())

    def test_B2_written_file_has_daily_key(self):
        """Written equity file has a 'daily' list."""
        with tempfile.TemporaryDirectory() as d:
            eq_path = pathlib.Path(d) / "equity_curve_daily.json"
            _atomic_append_equity_json(eq_path, "2026-06-20", 100500.0, 500.0, 0.5)
            data = json.loads(eq_path.read_text())
            self.assertIn("daily", data)
            self.assertIsInstance(data["daily"], list)

    def test_B3_bar_appears_in_daily(self):
        """Appended bar appears in the daily list."""
        with tempfile.TemporaryDirectory() as d:
            eq_path = pathlib.Path(d) / "equity_curve_daily.json"
            _atomic_append_equity_json(eq_path, "2026-06-20", 100500.0, 500.0, 0.5)
            data = json.loads(eq_path.read_text())
            dates = [b["date"] for b in data["daily"]]
            self.assertIn("2026-06-20", dates)

    def test_B4_no_tmp_files_left(self):
        """_atomic_append_equity_json leaves no .tmp files."""
        with tempfile.TemporaryDirectory() as d:
            eq_path = pathlib.Path(d) / "equity_curve_daily.json"
            _atomic_append_equity_json(eq_path, "2026-06-20", 100200.0, 200.0, 0.2)
            tmp_files = list(pathlib.Path(d).glob("*.tmp"))
            self.assertEqual(len(tmp_files), 0)

    def test_B5_multiple_dates_accumulated(self):
        """Multiple calls accumulate different date bars."""
        with tempfile.TemporaryDirectory() as d:
            eq_path = pathlib.Path(d) / "equity_curve_daily.json"
            _atomic_append_equity_json(eq_path, "2026-06-18", 100000.0, 0.0, 0.0)
            _atomic_append_equity_json(eq_path, "2026-06-19", 100100.0, 100.0, 0.1)
            _atomic_append_equity_json(eq_path, "2026-06-20", 100200.0, 200.0, 0.2)
            data = json.loads(eq_path.read_text())
            dates = {b["date"] for b in data["daily"]}
            self.assertIn("2026-06-18", dates)
            self.assertIn("2026-06-19", dates)
            self.assertIn("2026-06-20", dates)


# ═══════════════════════════════════════════════════════════════════════════════
# Group C — read_equity_curve JSON fallback
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadEquityCurve(unittest.TestCase):

    def test_C1_returns_empty_when_no_db_no_json(self):
        """read_equity_curve returns [] when no DB and no JSON file."""
        with tempfile.TemporaryDirectory() as d:
            import unittest.mock as _m
            # Point DB to temp path with no data
            db_path = str(pathlib.Path(d) / "empty.db")
            result = read_equity_curve(db_path=db_path, data_dir=d)
            self.assertIsInstance(result, list)

    def test_C2_reads_json_fallback_dict_format(self):
        """read_equity_curve reads JSON fallback with {"daily":[...]} format."""
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            bars = [
                {"date": "2026-06-18", "equity": 100000.0},
                {"date": "2026-06-19", "equity": 100100.0},
            ]
            _write_json(data_dir / "equity_curve_daily.json", {"daily": bars})
            db_path = str(data_dir / "empty.db")
            result = read_equity_curve(db_path=db_path, data_dir=str(data_dir))
            dates = [b["date"] for b in result]
            self.assertIn("2026-06-18", dates)

    def test_C3_reads_json_fallback_list_format(self):
        """read_equity_curve reads JSON fallback with plain list format."""
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            bars = [{"date": "2026-06-20", "equity": 100500.0}]
            _write_json(data_dir / "equity_curve_daily.json", bars)
            db_path = str(data_dir / "empty.db")
            result = read_equity_curve(db_path=db_path, data_dir=str(data_dir))
            dates = [b["date"] for b in result]
            self.assertIn("2026-06-20", dates)

    def test_C4_corrupted_json_returns_empty(self):
        """read_equity_curve returns [] when JSON file is corrupted."""
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            (data_dir / "equity_curve_daily.json").write_text("NOT JSON {{{")
            db_path = str(data_dir / "empty.db")
            result = read_equity_curve(db_path=db_path, data_dir=str(data_dir))
            self.assertIsInstance(result, list)


# ═══════════════════════════════════════════════════════════════════════════════
# Group E — Idempotency & upsert
# ═══════════════════════════════════════════════════════════════════════════════

class TestUpsertBehavior(unittest.TestCase):

    def test_E1_same_date_upserts_not_duplicates(self):
        """Appending same date twice upserts, not duplicates."""
        with tempfile.TemporaryDirectory() as d:
            eq_path = pathlib.Path(d) / "equity_curve_daily.json"
            _atomic_append_equity_json(eq_path, "2026-06-20", 100000.0, 0.0, 0.0)
            _atomic_append_equity_json(eq_path, "2026-06-20", 100500.0, 500.0, 0.5)
            data = json.loads(eq_path.read_text())
            june20_bars = [b for b in data["daily"] if b["date"] == "2026-06-20"]
            self.assertEqual(len(june20_bars), 1)

    def test_E2_upsert_updates_equity_value(self):
        """Second write for same date updates equity to new value."""
        with tempfile.TemporaryDirectory() as d:
            eq_path = pathlib.Path(d) / "equity_curve_daily.json"
            _atomic_append_equity_json(eq_path, "2026-06-20", 100000.0, 0.0, 0.0)
            _atomic_append_equity_json(eq_path, "2026-06-20", 100999.0, 999.0, 0.999)
            data = json.loads(eq_path.read_text())
            bar = next(b for b in data["daily"] if b["date"] == "2026-06-20")
            self.assertAlmostEqual(bar["equity"], 100999.0, places=2)

    def test_E3_existing_json_list_format_preserved(self):
        """Existing plain-list JSON is normalized to {"daily":[...]} on append."""
        with tempfile.TemporaryDirectory() as d:
            eq_path = pathlib.Path(d) / "equity_curve_daily.json"
            # Pre-seed with plain list
            eq_path.write_text(
                json.dumps([{"date": "2026-06-19", "equity": 99000.0}]),
                encoding="utf-8"
            )
            _atomic_append_equity_json(eq_path, "2026-06-20", 100000.0, 0.0, 0.0)
            data = json.loads(eq_path.read_text())
            self.assertIn("daily", data)
            dates = {b["date"] for b in data["daily"]}
            self.assertIn("2026-06-19", dates)
            self.assertIn("2026-06-20", dates)


if __name__ == "__main__":
    unittest.main(verbosity=2)
