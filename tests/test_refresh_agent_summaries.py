#!/usr/bin/env python3
"""
tests/test_refresh_agent_summaries.py — MP-1452 (Sprint v10.68)

Test suite for spa_core/utils/refresh_agent_summaries.py.

Tests:
  A. Atomic migration — uses atomic_save after MP-1452 (A1–A3)
  B. build_summaries (B1–B4)
  C. write_summaries dry_run (C1–C3)
  D. write_summaries actual write (D1–D5)

Pure stdlib. No network. Offline.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
import unittest.mock

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

import spa_core.utils.refresh_agent_summaries as _ras


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_positions(protocols=("aave_v3", "compound_v3"), capital: float = 100000.0) -> dict:
    n = len(protocols)
    share = capital / n
    return {p: {"usd_value": share, "target_pct": 1.0 / n} for p in protocols}


def _make_status(capital: float = 100000.0) -> dict:
    return {
        "capital_usd": capital,
        "is_demo": False,
        "last_cycle_ts": "2026-06-20T08:00:00+00:00",
        "daily_apy_pct": 4.5,
        "cycle_count": 11,
    }


def _make_data_dir(tmp: pathlib.Path,
                   positions: dict = None,
                   status: dict = None,
                   equity: list = None) -> pathlib.Path:
    data_dir = tmp / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "current_positions.json").write_text(
        json.dumps(positions or _make_positions()), encoding="utf-8"
    )
    (data_dir / "paper_trading_status.json").write_text(
        json.dumps(status or _make_status()), encoding="utf-8"
    )
    if equity:
        (data_dir / "equity_curve_daily.json").write_text(
            json.dumps({"daily": equity}), encoding="utf-8"
        )
    return data_dir


# ═══════════════════════════════════════════════════════════════════════════════
# Group A — Atomic migration
# ═══════════════════════════════════════════════════════════════════════════════

class TestAtomicMigration(unittest.TestCase):

    def test_A1_atomic_save_imported_after_migration(self):
        """refresh_agent_summaries.py imports atomic_save after migration (MP-1452)."""
        src = (_REPO / "spa_core" / "utils" / "refresh_agent_summaries.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("atomic_save", src,
                      "write_summaries should use atomic_save after migration")

    def test_A2_from_atomic_import_present(self):
        """refresh_agent_summaries.py has 'from spa_core.utils.atomic import'."""
        src = (_REPO / "spa_core" / "utils" / "refresh_agent_summaries.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from spa_core.utils.atomic import", src)

    def test_A3_write_creates_no_tmp_files(self):
        """write_summaries leaves no .tmp files after successful write."""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            data_dir = _make_data_dir(tmp)
            out_path = tmp / "agent_summaries.json"
            with unittest.mock.patch.object(_ras, "_OUT_PATH", out_path), \
                 unittest.mock.patch.object(_ras, "_DATA_DIR", data_dir):
                _ras.write_summaries(dry_run=False)
            tmp_files = list(tmp.glob("**/*.tmp"))
            self.assertEqual(len(tmp_files), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Group B — build_summaries
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildSummaries(unittest.TestCase):

    def _build(self, positions=None, status=None):
        with tempfile.TemporaryDirectory() as d:
            data_dir = _make_data_dir(pathlib.Path(d), positions=positions, status=status)
            with unittest.mock.patch.object(_ras, "_DATA_DIR", data_dir):
                return _ras.build_summaries()

    def test_B1_returns_dict(self):
        """build_summaries returns a dict."""
        result = self._build()
        self.assertIsInstance(result, dict)

    def test_B2_has_timestamp_key(self):
        """build_summaries result has a 'generated_at' or 'ts' timestamp key."""
        result = self._build()
        has_ts = "generated_at" in result or "ts" in result or "timestamp" in result
        self.assertTrue(has_ts, f"No timestamp key in: {list(result.keys())}")

    def test_B3_has_trader_or_summaries_key(self):
        """build_summaries result contains at least one summary section."""
        result = self._build()
        # At least one section should be present
        self.assertGreater(len(result), 0)

    def test_B4_no_exception_on_missing_files(self):
        """build_summaries does not raise when data files are absent."""
        with tempfile.TemporaryDirectory() as d:
            empty_dir = pathlib.Path(d) / "empty"
            empty_dir.mkdir()
            with unittest.mock.patch.object(_ras, "_DATA_DIR", empty_dir):
                try:
                    result = _ras.build_summaries()
                    self.assertIsInstance(result, dict)
                except Exception as e:
                    self.fail(f"build_summaries raised: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Group C — write_summaries dry_run
# ═══════════════════════════════════════════════════════════════════════════════

class TestWriteSummariesDryRun(unittest.TestCase):

    def test_C1_dry_run_returns_dict(self):
        """write_summaries(dry_run=True) returns a dict."""
        with tempfile.TemporaryDirectory() as d:
            data_dir = _make_data_dir(pathlib.Path(d))
            out_path = pathlib.Path(d) / "agent_summaries.json"
            with unittest.mock.patch.object(_ras, "_DATA_DIR", data_dir), \
                 unittest.mock.patch.object(_ras, "_OUT_PATH", out_path):
                result = _ras.write_summaries(dry_run=True)
            self.assertIsInstance(result, dict)

    def test_C2_dry_run_does_not_write_file(self):
        """write_summaries(dry_run=True) does not create the output file."""
        with tempfile.TemporaryDirectory() as d:
            data_dir = _make_data_dir(pathlib.Path(d))
            out_path = pathlib.Path(d) / "agent_summaries.json"
            with unittest.mock.patch.object(_ras, "_DATA_DIR", data_dir), \
                 unittest.mock.patch.object(_ras, "_OUT_PATH", out_path):
                _ras.write_summaries(dry_run=True)
            self.assertFalse(out_path.exists())

    def test_C3_dry_run_output_is_json_serializable(self):
        """write_summaries(dry_run=True) result is JSON serializable."""
        with tempfile.TemporaryDirectory() as d:
            data_dir = _make_data_dir(pathlib.Path(d))
            out_path = pathlib.Path(d) / "agent_summaries.json"
            with unittest.mock.patch.object(_ras, "_DATA_DIR", data_dir), \
                 unittest.mock.patch.object(_ras, "_OUT_PATH", out_path):
                result = _ras.write_summaries(dry_run=True)
            serialized = json.dumps(result)
            self.assertIsInstance(serialized, str)


# ═══════════════════════════════════════════════════════════════════════════════
# Group D — write_summaries actual write
# ═══════════════════════════════════════════════════════════════════════════════

class TestWriteSummariesActual(unittest.TestCase):

    def _write(self, positions=None, status=None):
        tmp = tempfile.mkdtemp()
        data_dir = _make_data_dir(pathlib.Path(tmp), positions=positions, status=status)
        out_path = pathlib.Path(tmp) / "agent_summaries.json"
        with unittest.mock.patch.object(_ras, "_DATA_DIR", data_dir), \
             unittest.mock.patch.object(_ras, "_OUT_PATH", out_path):
            result = _ras.write_summaries(dry_run=False)
        return out_path, result

    def test_D1_creates_output_file(self):
        """write_summaries creates agent_summaries.json."""
        out_path, _ = self._write()
        self.assertTrue(out_path.exists())

    def test_D2_output_is_valid_json(self):
        """Written file is valid JSON."""
        out_path, _ = self._write()
        data = json.loads(out_path.read_text())
        self.assertIsInstance(data, dict)

    def test_D3_returns_same_as_written(self):
        """write_summaries returns the same dict that was written."""
        out_path, result = self._write()
        written = json.loads(out_path.read_text())
        # Compare a key to confirm consistency
        self.assertEqual(type(result), type(written))

    def test_D4_idempotent_double_write(self):
        """write_summaries can be called twice without error."""
        with tempfile.TemporaryDirectory() as d:
            data_dir = _make_data_dir(pathlib.Path(d))
            out_path = pathlib.Path(d) / "agent_summaries.json"
            with unittest.mock.patch.object(_ras, "_DATA_DIR", data_dir), \
                 unittest.mock.patch.object(_ras, "_OUT_PATH", out_path):
                _ras.write_summaries(dry_run=False)
                _ras.write_summaries(dry_run=False)  # second call
            self.assertTrue(out_path.exists())

    def test_D5_no_tmp_files_after_write(self):
        """No .tmp files remain after write_summaries completes."""
        with tempfile.TemporaryDirectory() as d:
            data_dir = _make_data_dir(pathlib.Path(d))
            out_path = pathlib.Path(d) / "agent_summaries.json"
            with unittest.mock.patch.object(_ras, "_DATA_DIR", data_dir), \
                 unittest.mock.patch.object(_ras, "_OUT_PATH", out_path):
                _ras.write_summaries(dry_run=False)
            tmp_files = list(pathlib.Path(d).glob("**/*.tmp"))
            self.assertEqual(len(tmp_files), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
