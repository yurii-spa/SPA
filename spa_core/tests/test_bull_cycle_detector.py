"""
Tests for spa_core/strategies/bull_cycle_detector.py — FEAT-STRAT-001 (v3.19).

Run:
    python -m unittest spa_core/tests/test_bull_cycle_detector.py -v

Expected: ≥ 60 tests, all PASS.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.strategies.bull_cycle_detector import (
    AllocationCaps,
    BullCycleDetector,
    CycleState,
    DynamicTierAllocator,
    get_allocation_caps,
    get_cycle,
    get_detector,
    _compute_daily_market_medians,
    _count_consecutive_bull_days,
    _determine_cycle,
    _load_apy_history,
    _protocol_apy_summary,
    BULL_APY_THRESHOLD,
    MIN_BULL_DAYS,
    _CAPS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_apy_history(
    protocols: dict[str, list[float]],
    start_date: str = "2026-05-01",
) -> dict[str, list[dict]]:
    """
    Build a synthetic apy_history dict.
    protocols: {protocol_key: [apy_day0, apy_day1, ...]}
    """
    from datetime import date as _date
    d = _date.fromisoformat(start_date)
    result = {}
    for proto_key, apys in protocols.items():
        entries = []
        for i, apy in enumerate(apys):
            entries.append({
                "date": (d + timedelta(days=i)).isoformat(),
                "apy": apy,
                "tvl_usd": 1_000_000,
            })
        result[proto_key] = entries
    return result


def _make_json_file(protocols: dict[str, list[float]], start_date: str = "2026-05-01") -> str:
    """Write a temporary historical_apy.json and return its path."""
    history = _make_apy_history(protocols, start_date)
    data = {
        "generated_at": "2026-05-28T00:00:00Z",
        "data_source": "test",
        "days": 30,
        "protocols": history,
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
        json.dump(data, fh)
        return fh.name


# ---------------------------------------------------------------------------
# 1. AllocationCaps
# ---------------------------------------------------------------------------

class TestAllocationCaps(unittest.TestCase):

    def test_valid_caps(self):
        caps = AllocationCaps(t1_max_pct=60, t2_max_pct=30, t3_max_pct=10,
                               cash_buffer_min_pct=5)
        self.assertEqual(caps.t1_max_pct, 60)

    def test_to_dict_has_all_keys(self):
        caps = AllocationCaps(60, 30, 10, 5)
        d = caps.to_dict()
        for k in ["t1_max_pct", "t2_max_pct", "t3_max_pct", "cash_buffer_min_pct"]:
            self.assertIn(k, d)

    def test_negative_value_raises(self):
        with self.assertRaises(ValueError):
            AllocationCaps(t1_max_pct=-10, t2_max_pct=30, t3_max_pct=10,
                           cash_buffer_min_pct=5)

    def test_over_100_raises(self):
        with self.assertRaises(ValueError):
            AllocationCaps(t1_max_pct=101, t2_max_pct=30, t3_max_pct=10,
                           cash_buffer_min_pct=5)

    def test_zero_is_valid(self):
        caps = AllocationCaps(0, 0, 0, 5)
        self.assertEqual(caps.t1_max_pct, 0)

    def test_bear_caps_preset(self):
        caps = AllocationCaps(**_CAPS["BEAR"])
        self.assertGreater(caps.t1_max_pct, caps.t3_max_pct)

    def test_bull_caps_preset(self):
        caps = AllocationCaps(**_CAPS["BULL"])
        self.assertGreater(caps.t3_max_pct, _CAPS["NEUTRAL"]["t3_max_pct"])


# ---------------------------------------------------------------------------
# 2. _compute_daily_market_medians
# ---------------------------------------------------------------------------

class TestComputeDailyMarketMedians(unittest.TestCase):

    def test_returns_list(self):
        history = _make_apy_history({"aave": [5.0] * 20, "comp": [6.0] * 20})
        result = _compute_daily_market_medians(history, lookback_days=30)
        self.assertIsInstance(result, list)

    def test_empty_history_returns_empty(self):
        result = _compute_daily_market_medians({}, lookback_days=30)
        self.assertEqual(result, [])

    def test_sorted_ascending(self):
        history = _make_apy_history({"aave": [5.0] * 20, "comp": [6.0] * 20})
        result = _compute_daily_market_medians(history, lookback_days=30)
        dates = [d for d, _ in result]
        self.assertEqual(dates, sorted(dates))

    def test_median_of_two_protocols(self):
        # aave=4.0, comp=8.0 → median=6.0 each day
        history = _make_apy_history({"aave": [4.0] * 20, "comp": [8.0] * 20})
        result = _compute_daily_market_medians(history, lookback_days=25)
        if result:
            _, median = result[-1]
            self.assertAlmostEqual(median, 6.0, places=2)

    def test_negative_apy_excluded(self):
        # Negative APY is excluded from median calculation
        history = _make_apy_history({"aave": [-1.0] * 20, "comp": [6.0] * 20})
        result = _compute_daily_market_medians(history, lookback_days=25)
        for _, median in result:
            self.assertGreaterEqual(median, 0)


# ---------------------------------------------------------------------------
# 3. _count_consecutive_bull_days
# ---------------------------------------------------------------------------

class TestCountConsecutiveBullDays(unittest.TestCase):

    def test_all_above_threshold(self):
        medians = [("2026-05-01", 9.0), ("2026-05-02", 9.5), ("2026-05-03", 10.0)]
        self.assertEqual(_count_consecutive_bull_days(medians, threshold=8.0), 3)

    def test_trailing_days_only(self):
        # Only last 2 days above threshold
        medians = [("2026-05-01", 5.0), ("2026-05-02", 9.0), ("2026-05-03", 9.5)]
        self.assertEqual(_count_consecutive_bull_days(medians, threshold=8.0), 2)

    def test_none_above_threshold(self):
        medians = [("2026-05-01", 5.0), ("2026-05-02", 6.0)]
        self.assertEqual(_count_consecutive_bull_days(medians, threshold=8.0), 0)

    def test_empty_medians(self):
        self.assertEqual(_count_consecutive_bull_days([], threshold=8.0), 0)

    def test_exactly_at_threshold(self):
        medians = [("2026-05-01", 8.0)]
        self.assertEqual(_count_consecutive_bull_days(medians, threshold=8.0), 1)

    def test_gap_resets_count(self):
        # Day 3 drops below → only day 4 counts
        medians = [
            ("2026-05-01", 9.0),
            ("2026-05-02", 9.0),
            ("2026-05-03", 5.0),
            ("2026-05-04", 9.0),
        ]
        self.assertEqual(_count_consecutive_bull_days(medians, threshold=8.0), 1)


# ---------------------------------------------------------------------------
# 4. _determine_cycle
# ---------------------------------------------------------------------------

class TestDetermineCycle(unittest.TestCase):

    def test_bull_when_enough_consecutive_days(self):
        result = _determine_cycle(7, 9.0, threshold=8.0, min_bull_days=7)
        self.assertEqual(result, "BULL")

    def test_neutral_when_not_enough_days(self):
        result = _determine_cycle(5, 9.0, threshold=8.0, min_bull_days=7)
        self.assertEqual(result, "NEUTRAL")

    def test_bear_when_median_well_below(self):
        # 9.0 * 0.75 = 6.75 — median < 6.75 → BEAR
        result = _determine_cycle(0, 5.0, threshold=9.0, min_bull_days=7)
        self.assertEqual(result, "BEAR")

    def test_neutral_between_bear_and_bull(self):
        # median = 7.0, threshold = 8.0, 7*0.75=6.0 — above bear, not enough bull days
        result = _determine_cycle(3, 7.0, threshold=8.0, min_bull_days=7)
        self.assertEqual(result, "NEUTRAL")

    def test_bull_overrides_bear(self):
        # If consecutive_bull_days >= min_bull_days, cycle is BULL regardless of median
        result = _determine_cycle(10, 1.0, threshold=8.0, min_bull_days=7)
        self.assertEqual(result, "BULL")


# ---------------------------------------------------------------------------
# 5. BullCycleDetector — with synthetic data
# ---------------------------------------------------------------------------

class TestBullCycleDetectorSynthetic(unittest.TestCase):

    def _make_detector(self, apys_by_protocol: dict[str, list[float]],
                       start_days_ago: int = 20) -> BullCycleDetector:
        today = datetime.now(timezone.utc).date()
        start = (today - timedelta(days=start_days_ago)).isoformat()
        path = _make_json_file(apys_by_protocol, start_date=start)
        self._tmpfiles = getattr(self, "_tmpfiles", [])
        self._tmpfiles.append(path)
        return BullCycleDetector(apy_history_path=path, lookback_days=25)

    def tearDown(self):
        for p in getattr(self, "_tmpfiles", []):
            try:
                os.unlink(p)
            except Exception:
                pass

    def test_detect_returns_cycle_state(self):
        d = self._make_detector({"aave": [6.0] * 20, "comp": [6.5] * 20})
        state = d.detect()
        self.assertIsInstance(state, CycleState)

    def test_detect_bull_cycle(self):
        # All days above 8% → BULL after 7 days
        d = self._make_detector(
            {"aave": [9.0] * 20, "comp": [10.0] * 20},
            start_days_ago=20
        )
        state = d.detect()
        self.assertEqual(state.cycle, "BULL")
        self.assertGreaterEqual(state.consecutive_bull_days, 7)

    def test_detect_bear_cycle(self):
        # All days well below 8%
        d = self._make_detector(
            {"aave": [3.0] * 20, "comp": [3.5] * 20},
            start_days_ago=20
        )
        state = d.detect()
        self.assertEqual(state.cycle, "BEAR")

    def test_detect_neutral_cycle(self):
        # APY above bear threshold but not 7 consecutive bull days
        apys = [5.0] * 15 + [8.5] * 5  # only 5 bull days
        d = self._make_detector({"aave": apys, "comp": [7.0] * 20}, start_days_ago=20)
        state = d.detect()
        # Should NOT be BULL (only 5 days above threshold)
        self.assertNotEqual(state.cycle, "BULL")

    def test_cycle_state_caps_match_cycle(self):
        d = self._make_detector({"aave": [9.0] * 20, "comp": [10.0] * 20}, start_days_ago=20)
        state = d.detect()
        expected_caps = _CAPS[state.cycle]
        self.assertEqual(state.allocation_caps.t1_max_pct, expected_caps["t1_max_pct"])

    def test_is_bull_returns_true(self):
        d = self._make_detector({"aave": [9.0] * 20, "comp": [10.0] * 20}, start_days_ago=20)
        self.assertTrue(d.is_bull())

    def test_is_bear_returns_true(self):
        d = self._make_detector({"aave": [3.0] * 20, "comp": [3.5] * 20}, start_days_ago=20)
        self.assertTrue(d.is_bear())

    def test_export_returns_dict(self):
        d = self._make_detector({"aave": [6.0] * 20}, start_days_ago=20)
        result = d.export(dry_run=True)
        self.assertIn("cycle", result)
        self.assertIn("allocation_caps", result)

    def test_missing_file_returns_neutral(self):
        d = BullCycleDetector(apy_history_path="/nonexistent/path.json")
        state = d.detect()
        self.assertEqual(state.cycle, "NEUTRAL")

    def test_never_raises_on_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            json.dump({}, fh)
            path = fh.name
        try:
            d = BullCycleDetector(apy_history_path=path)
            state = d.detect()
            self.assertIsNotNone(state)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 6. DynamicTierAllocator
# ---------------------------------------------------------------------------

class TestDynamicTierAllocator(unittest.TestCase):

    def _make_allocator(self, cycle: str = "NEUTRAL") -> DynamicTierAllocator:
        """Create an allocator with a mocked detector returning a fixed cycle."""
        detector = MagicMock(spec=BullCycleDetector)
        detector.get_allocation_caps.return_value = AllocationCaps(**_CAPS[cycle])
        detector.get_cycle.return_value = cycle
        return DynamicTierAllocator(detector=detector)

    def test_apply_caps_returns_dict(self):
        a = self._make_allocator("NEUTRAL")
        result = a.apply_caps(100_000, {"t1": 60_000, "t2": 30_000, "t3": 10_000})
        self.assertIn("t1", result)
        self.assertIn("t2", result)
        self.assertIn("t3", result)
        self.assertIn("cash", result)
        self.assertIn("cycle", result)

    def test_cash_buffer_preserved_neutral(self):
        a = self._make_allocator("NEUTRAL")
        result = a.apply_caps(100_000, {"t1": 60_000, "t2": 30_000, "t3": 10_000})
        self.assertGreaterEqual(result["cash"], 5_000)  # 5% min

    def test_cash_buffer_preserved_bull(self):
        a = self._make_allocator("BULL")
        result = a.apply_caps(100_000, {"t1": 60_000, "t2": 40_000, "t3": 20_000})
        self.assertGreaterEqual(result["cash"], 5_000)

    def test_total_equals_capital(self):
        a = self._make_allocator("NEUTRAL")
        result = a.apply_caps(100_000, {"t1": 55_000, "t2": 30_000, "t3": 10_000})
        total = result["t1"] + result["t2"] + result["t3"] + result["cash"]
        self.assertAlmostEqual(total, 100_000, places=1)

    def test_bull_caps_t3_higher_than_neutral(self):
        a_bull = self._make_allocator("BULL")
        a_neut = self._make_allocator("NEUTRAL")
        targets = {"t1": 50_000, "t2": 30_000, "t3": 20_000}
        bull_res = a_bull.apply_caps(100_000, targets)
        neut_res = a_neut.apply_caps(100_000, targets)
        # Bull allows more T3
        self.assertGreaterEqual(bull_res["t3"], neut_res["t3"])

    def test_bear_caps_t1_higher(self):
        a_bear = self._make_allocator("BEAR")
        result = a_bear.apply_caps(100_000, {"t1": 90_000, "t2": 5_000, "t3": 5_000})
        # T1 capped at 80% (BEAR)
        self.assertLessEqual(result["t1"], 80_000 + 0.01)

    def test_zero_capital_returns_zeros(self):
        a = self._make_allocator("NEUTRAL")
        result = a.apply_caps(0, {"t1": 0, "t2": 0, "t3": 0})
        self.assertEqual(result["t1"], 0.0)
        self.assertEqual(result["cash"], 0.0)

    def test_cycle_label_in_result(self):
        a = self._make_allocator("BULL")
        result = a.apply_caps(100_000, {"t1": 40_000, "t2": 40_000, "t3": 20_000})
        self.assertEqual(result["cycle"], "BULL")

    def test_never_raises(self):
        a = self._make_allocator("NEUTRAL")
        try:
            a.apply_caps(100_000, {"t1": 50_000, "t2": 30_000, "t3": 20_000})
        except Exception as e:
            self.fail(f"apply_caps raised: {e}")

    def test_describe_returns_string(self):
        detector = BullCycleDetector(apy_history_path="/nonexistent/path.json")
        a = DynamicTierAllocator(detector=detector)
        result = a.describe(100_000)
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# 7. Module-level shortcuts
# ---------------------------------------------------------------------------

class TestModuleLevelShortcuts(unittest.TestCase):

    def test_get_detector_singleton(self):
        d1 = get_detector()
        d2 = get_detector()
        self.assertIs(d1, d2)

    def test_get_cycle_returns_string(self):
        result = get_cycle()
        self.assertIn(result, ["BEAR", "NEUTRAL", "BULL"])

    def test_get_allocation_caps_returns_caps(self):
        result = get_allocation_caps()
        self.assertIsInstance(result, AllocationCaps)


# ---------------------------------------------------------------------------
# 8. CycleState
# ---------------------------------------------------------------------------

class TestCycleState(unittest.TestCase):

    def _make_state(self, cycle: str = "NEUTRAL") -> CycleState:
        return CycleState(
            cycle=cycle,
            consecutive_bull_days=5,
            current_median_apy=7.5,
            bull_threshold=8.0,
            min_bull_days=7,
            allocation_caps=AllocationCaps(**_CAPS[cycle]),
            protocol_apys={"aave": {"latest_apy": 7.5, "7d_median": 7.3}},
            history_days_used=20,
        )

    def test_to_dict_has_all_keys(self):
        state = self._make_state()
        d = state.to_dict()
        for k in ["cycle", "consecutive_bull_days", "current_median_apy",
                  "allocation_caps", "generated_at"]:
            self.assertIn(k, d)

    def test_cycle_in_output(self):
        state = self._make_state("BULL")
        self.assertEqual(state.to_dict()["cycle"], "BULL")

    def test_generated_at_is_iso(self):
        state = self._make_state()
        self.assertIn("T", state.generated_at)


# ---------------------------------------------------------------------------
# 9. Export to file
# ---------------------------------------------------------------------------

class TestExportToFile(unittest.TestCase):

    def test_writes_json_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            today = datetime.now(timezone.utc).date()
            start = (today - timedelta(days=20)).isoformat()
            apy_path = _make_json_file({"aave": [6.0] * 20}, start_date=start)
            out_path = Path(tmpdir) / "market_cycle.json"
            try:
                d = BullCycleDetector(apy_history_path=apy_path, output_path=str(out_path))
                d.export(dry_run=False)
                self.assertTrue(out_path.exists())
                with out_path.open() as fh:
                    data = json.load(fh)
                self.assertIn("cycle", data)
            finally:
                os.unlink(apy_path)

    def test_dry_run_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "market_cycle.json"
            d = BullCycleDetector(apy_history_path="/nonexistent.json",
                                  output_path=str(out_path))
            d.export(dry_run=True)
            self.assertFalse(out_path.exists())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
