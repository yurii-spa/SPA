"""
tests/test_data_freshness_monitor.py

Sprint v11.21 — MP-1505: Data freshness monitor — 20 tests covering:
  - FRESH / STALE / MISSING detection
  - check_all() result schema
  - Threshold customisation
  - is_fresh() / stale_count() / missing_count()
  - Deterministic clock injection
  - Summary counts
  - File-map override (test isolation)
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.monitor.data_freshness_monitor import (
    DataFreshnessMonitor,
    FRESHNESS_THRESHOLDS,
    STATUS_FRESH,
    STATUS_STALE,
    STATUS_MISSING,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fixed_clock(ts: float):
    """Return a zero-arg callable that always returns *ts*."""
    return lambda: ts


def _monitor_with_files(tmp_path: str, file_ages: dict[str, float]) -> DataFreshnessMonitor:
    """
    Build a monitor with custom file_map pointing to temp files.
    *file_ages* maps data_type → age_in_seconds (how old the file should be).
    A negative age means the file should not exist.
    """
    now = 1_000_000.0  # fixed reference timestamp
    file_map: dict[str, str] = {}

    for dtype, age in file_ages.items():
        if age < 0:
            # File does not exist
            file_map[dtype] = os.path.join(tmp_path, f"missing_{dtype}.json")
        else:
            fpath = os.path.join(tmp_path, f"{dtype}.json")
            with open(fpath, "w") as f:
                f.write("{}")
            # Backdate mtime
            mtime = now - age
            os.utime(fpath, (mtime, mtime))
            file_map[dtype] = fpath

    thresholds = {k: 3_600 for k in file_ages}  # 1 h threshold for all
    return DataFreshnessMonitor(
        base_dir=tmp_path,
        thresholds=thresholds,
        file_map=file_map,
        clock=_fixed_clock(now),
    )


# ---------------------------------------------------------------------------
# 1. Basic status detection
# ---------------------------------------------------------------------------

class TestStatusDetection(unittest.TestCase):

    def test_fresh_file_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = _monitor_with_files(tmp, {"apy_data": 100})  # 100s old < 1h
            result = mon.check_all()
            assert result["checks"]["apy_data"]["status"] == STATUS_FRESH

    def test_stale_file_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = _monitor_with_files(tmp, {"apy_data": 7_200})  # 2h old > 1h
            result = mon.check_all()
            assert result["checks"]["apy_data"]["status"] == STATUS_STALE

    def test_missing_file_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = _monitor_with_files(tmp, {"apy_data": -1})  # does not exist
            result = mon.check_all()
            assert result["checks"]["apy_data"]["status"] == STATUS_MISSING

    def test_age_sec_populated_for_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = _monitor_with_files(tmp, {"apy_data": 500})
            result = mon.check_all()
            age = result["checks"]["apy_data"]["age_sec"]
            assert age is not None
            assert abs(age - 500) < 5  # within 5s tolerance

    def test_age_sec_is_none_for_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = _monitor_with_files(tmp, {"apy_data": -1})
            result = mon.check_all()
            assert result["checks"]["apy_data"]["age_sec"] is None


# ---------------------------------------------------------------------------
# 2. check_all() schema
# ---------------------------------------------------------------------------

class TestCheckAllSchema(unittest.TestCase):

    def test_result_has_required_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = _monitor_with_files(tmp, {"apy_data": 100})
            result = mon.check_all()
        for key in ("checks", "stale_files", "missing_files", "fresh_files", "last_run", "summary"):
            assert key in result, f"Missing key: {key}"

    def test_last_run_is_iso_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = _monitor_with_files(tmp, {"apy_data": 100})
            result = mon.check_all()
        assert isinstance(result["last_run"], str)
        assert "T" in result["last_run"]  # ISO format contains T separator

    def test_summary_totals_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = _monitor_with_files(tmp, {
                "apy_data": 100,       # FRESH
                "portfolio_nav": 7_200, # STALE
                "gate_status": -1,     # MISSING
            })
            result = mon.check_all()
        s = result["summary"]
        assert s["total"] == 3
        assert s["fresh"] == 1
        assert s["stale"] == 1
        assert s["missing"] == 1

    def test_check_entry_has_threshold_sec(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = _monitor_with_files(tmp, {"apy_data": 100})
            result = mon.check_all()
        assert "threshold_sec" in result["checks"]["apy_data"]


# ---------------------------------------------------------------------------
# 3. Stale / missing lists
# ---------------------------------------------------------------------------

class TestStaleMissingLists(unittest.TestCase):

    def test_stale_files_list_populated(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = _monitor_with_files(tmp, {"apy_data": 7_200, "portfolio_nav": 100})
            result = mon.check_all()
        assert "apy_data" in result["stale_files"]
        assert "portfolio_nav" not in result["stale_files"]

    def test_missing_files_list_populated(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = _monitor_with_files(tmp, {"gate_status": -1, "apy_data": 100})
            result = mon.check_all()
        assert "gate_status" in result["missing_files"]
        assert "apy_data" not in result["missing_files"]

    def test_stale_count_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = _monitor_with_files(tmp, {
                "apy_data": 7_200,
                "portfolio_nav": 7_200,
                "gate_status": 100,
            })
            mon.check_all()
        assert mon.stale_count() == 2

    def test_missing_count_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = _monitor_with_files(tmp, {"apy_data": -1, "portfolio_nav": -1})
            mon.check_all()
        assert mon.missing_count() == 2


# ---------------------------------------------------------------------------
# 4. is_fresh() helper
# ---------------------------------------------------------------------------

class TestIsFresh(unittest.TestCase):

    def test_is_fresh_true_for_fresh_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = _monitor_with_files(tmp, {"apy_data": 100})
            mon.check_all()
        assert mon.is_fresh("apy_data") is True

    def test_is_fresh_false_for_stale_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = _monitor_with_files(tmp, {"apy_data": 7_200})
            mon.check_all()
        assert mon.is_fresh("apy_data") is False

    def test_is_fresh_false_for_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mon = _monitor_with_files(tmp, {"apy_data": -1})
            mon.check_all()
        assert mon.is_fresh("apy_data") is False

    def test_is_fresh_none_before_check_all(self):
        mon = DataFreshnessMonitor()
        assert mon.is_fresh("apy_data") is None


# ---------------------------------------------------------------------------
# 5. Default thresholds
# ---------------------------------------------------------------------------

class TestDefaultThresholds(unittest.TestCase):

    def test_apy_data_threshold_is_1h(self):
        assert FRESHNESS_THRESHOLDS["apy_data"] == 3_600

    def test_portfolio_nav_threshold_is_1day(self):
        assert FRESHNESS_THRESHOLDS["portfolio_nav"] == 86_400

    def test_gate_status_threshold_is_7days(self):
        assert FRESHNESS_THRESHOLDS["gate_status"] == 86_400 * 7

    def test_backtest_results_threshold_is_30days(self):
        assert FRESHNESS_THRESHOLDS["backtest_results"] == 86_400 * 30

    def test_to_dict_returns_dict(self):
        mon = DataFreshnessMonitor()
        assert isinstance(mon.to_dict(), dict)


if __name__ == "__main__":
    unittest.main()
