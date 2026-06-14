"""
Tests for spa_core/analytics/daily_pnl_reconciler.py  (MP-641)
≥60 tests — stdlib unittest only (no external dependencies).
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
import unittest

# Make spa_core importable when run from project root or directly
_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.analytics.daily_pnl_reconciler import (
    DailyPnLReconciler,
    ReconciliationReport,
    StrategyPnL,
    MAX_ENTRIES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_strategy(sid, capital=10_000.0, exp_apy=0.05, act_apy=0.05):
    return {"strategy_id": sid, "capital_usd": capital,
            "expected_apy": exp_apy, "actual_apy": act_apy}


def _make_spnl(status):
    return StrategyPnL(
        strategy_id="S", date_str="2026-01-01", capital_usd=1000.0,
        expected_apy=0.05, actual_apy=0.05,
        expected_daily_pnl=0.14, actual_daily_pnl=0.14,
        variance_usd=0.0, variance_pct=0.0, status=status,
    )


class BaseReconcilerTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "daily_pnl_reconciliation.json"
        self.r = DailyPnLReconciler(data_file=self.data_file)


# ---------------------------------------------------------------------------
# _compute_daily_pnl
# ---------------------------------------------------------------------------

class TestComputeDailyPnl(BaseReconcilerTest):

    def test_known_value(self):
        result = self.r._compute_daily_pnl(36500, 0.10)
        self.assertAlmostEqual(result, 10.0, places=9)

    def test_zero_capital(self):
        self.assertEqual(self.r._compute_daily_pnl(0, 0.10), 0.0)

    def test_zero_apy(self):
        self.assertEqual(self.r._compute_daily_pnl(10_000, 0.0), 0.0)

    def test_both_zero(self):
        self.assertEqual(self.r._compute_daily_pnl(0, 0.0), 0.0)

    def test_large_capital(self):
        result = self.r._compute_daily_pnl(100_000, 0.0365)
        self.assertAlmostEqual(result, 10.0, places=9)

    def test_proportional_to_capital(self):
        r1 = self.r._compute_daily_pnl(10_000, 0.05)
        r2 = self.r._compute_daily_pnl(20_000, 0.05)
        self.assertAlmostEqual(r2, 2 * r1, places=9)

    def test_proportional_to_apy(self):
        r1 = self.r._compute_daily_pnl(10_000, 0.05)
        r2 = self.r._compute_daily_pnl(10_000, 0.10)
        self.assertAlmostEqual(r2, 2 * r1, places=9)


# ---------------------------------------------------------------------------
# _compute_variance_pct
# ---------------------------------------------------------------------------

class TestComputeVariancePct(BaseReconcilerTest):

    def test_zero_expected_returns_zero(self):
        self.assertEqual(self.r._compute_variance_pct(100.0, 0.0), 0.0)

    def test_near_zero_expected_returns_zero(self):
        self.assertEqual(self.r._compute_variance_pct(1.0, 1e-7), 0.0)

    def test_positive_variance(self):
        result = self.r._compute_variance_pct(1.0, 10.0)
        self.assertAlmostEqual(result, 0.1, places=9)

    def test_negative_variance(self):
        result = self.r._compute_variance_pct(-2.0, 10.0)
        self.assertAlmostEqual(result, -0.2, places=9)

    def test_exact_match(self):
        self.assertEqual(self.r._compute_variance_pct(0.0, 10.0), 0.0)

    def test_fifty_percent_over(self):
        result = self.r._compute_variance_pct(5.0, 10.0)
        self.assertAlmostEqual(result, 0.5, places=9)


# ---------------------------------------------------------------------------
# _classify_strategy
# ---------------------------------------------------------------------------

class TestClassifyStrategy(BaseReconcilerTest):

    def test_on_track_zero_variance(self):
        self.assertEqual(self.r._classify_strategy(0.0, 0.05), "ON_TRACK")

    def test_on_track_within_9pct(self):
        self.assertEqual(self.r._classify_strategy(0.09, 0.05), "ON_TRACK")

    def test_on_track_minus_9pct(self):
        self.assertEqual(self.r._classify_strategy(-0.09, 0.05), "ON_TRACK")

    def test_boundary_exactly_minus_10pct_is_on_track(self):
        # abs(-0.10) <= 0.10 → ON_TRACK (inclusive boundary)
        self.assertEqual(self.r._classify_strategy(-0.10, 0.05), "ON_TRACK")

    def test_underperform_just_past_boundary(self):
        self.assertEqual(self.r._classify_strategy(-0.1001, 0.05), "UNDERPERFORM")

    def test_overperform_just_past_boundary(self):
        self.assertEqual(self.r._classify_strategy(0.1001, 0.05), "OVERPERFORM")

    def test_data_missing_both_zero(self):
        self.assertEqual(self.r._classify_strategy(0.0, 0.0), "DATA_MISSING")

    def test_overperform_large(self):
        self.assertEqual(self.r._classify_strategy(0.5, 0.10), "OVERPERFORM")

    def test_underperform_large_negative(self):
        self.assertEqual(self.r._classify_strategy(-0.5, 0.10), "UNDERPERFORM")

    def test_non_zero_actual_on_track(self):
        # variance_pct=0 and actual_apy != 0 → ON_TRACK
        self.assertEqual(self.r._classify_strategy(0.0, 0.05), "ON_TRACK")

    def test_exactly_plus_10pct_is_on_track(self):
        # abs(0.10) <= 0.10 → ON_TRACK (inclusive boundary)
        self.assertEqual(self.r._classify_strategy(0.10, 0.05), "ON_TRACK")


# ---------------------------------------------------------------------------
# _overall_status
# ---------------------------------------------------------------------------

class TestOverallStatus(BaseReconcilerTest):

    def test_all_on_track_green(self):
        strats = [_make_spnl("ON_TRACK")] * 5
        self.assertEqual(self.r._overall_status(strats), "GREEN")

    def test_zero_underperformers_green(self):
        strats = [_make_spnl("OVERPERFORM"), _make_spnl("ON_TRACK")]
        self.assertEqual(self.r._overall_status(strats), "GREEN")

    def test_one_of_four_underperform_yellow(self):
        # floor(4/3) = 1 → 1 underperformer ≤ 1 → YELLOW
        strats = [_make_spnl("UNDERPERFORM")] + [_make_spnl("ON_TRACK")] * 3
        self.assertEqual(self.r._overall_status(strats), "YELLOW")

    def test_two_of_five_underperform_red(self):
        # floor(5/3) = 1 → 2 > 1 → RED
        strats = [_make_spnl("UNDERPERFORM")] * 2 + [_make_spnl("ON_TRACK")] * 3
        self.assertEqual(self.r._overall_status(strats), "RED")

    def test_majority_underperform_red(self):
        strats = [_make_spnl("UNDERPERFORM")] * 4 + [_make_spnl("ON_TRACK")] * 1
        self.assertEqual(self.r._overall_status(strats), "RED")

    def test_empty_list_green(self):
        self.assertEqual(self.r._overall_status([]), "GREEN")

    def test_single_underperform_red(self):
        # 1 total, floor(1/3)=0 → 1 > 0 → RED
        strats = [_make_spnl("UNDERPERFORM")]
        self.assertEqual(self.r._overall_status(strats), "RED")

    def test_all_data_missing_green(self):
        strats = [_make_spnl("DATA_MISSING")] * 3
        self.assertEqual(self.r._overall_status(strats), "GREEN")


# ---------------------------------------------------------------------------
# reconcile
# ---------------------------------------------------------------------------

class TestReconcile(BaseReconcilerTest):

    def test_single_on_track(self):
        data = [_make_strategy("S0", capital=36500, exp_apy=0.10, act_apy=0.10)]
        report = self.r.reconcile("2026-01-01", data)
        self.assertEqual(len(report.strategies), 1)
        s = report.strategies[0]
        self.assertEqual(s.status, "ON_TRACK")
        self.assertEqual(s.variance_usd, 0.0)

    def test_single_underperform(self):
        data = [_make_strategy("S1", capital=10_000, exp_apy=0.10, act_apy=0.05)]
        report = self.r.reconcile("2026-01-01", data)
        s = report.strategies[0]
        self.assertEqual(s.status, "UNDERPERFORM")
        self.assertLess(s.variance_usd, 0)

    def test_single_overperform(self):
        data = [_make_strategy("S2", capital=10_000, exp_apy=0.05, act_apy=0.10)]
        report = self.r.reconcile("2026-01-01", data)
        s = report.strategies[0]
        self.assertEqual(s.status, "OVERPERFORM")
        self.assertGreater(s.variance_usd, 0)

    def test_data_missing_zero_actual(self):
        data = [_make_strategy("S3", capital=10_000, exp_apy=0.0, act_apy=0.0)]
        report = self.r.reconcile("2026-01-01", data)
        self.assertEqual(report.strategies[0].status, "DATA_MISSING")

    def test_empty_strategy_list(self):
        report = self.r.reconcile("2026-01-01", [])
        self.assertEqual(report.strategies, [])
        self.assertEqual(report.total_capital_usd, 0.0)
        self.assertEqual(report.overall_status, "GREEN")

    def test_total_capital_sum(self):
        data = [_make_strategy("S0", capital=10_000), _make_strategy("S1", capital=20_000)]
        report = self.r.reconcile("2026-01-01", data)
        self.assertAlmostEqual(report.total_capital_usd, 30_000, delta=0.01)

    def test_total_expected_pnl_sum(self):
        data = [_make_strategy("SA", capital=36500, exp_apy=0.10)]
        report = self.r.reconcile("2026-01-01", data)
        self.assertAlmostEqual(report.total_expected_pnl, 10.0, delta=0.001)

    def test_total_actual_pnl_sum(self):
        data = [_make_strategy("SB", capital=36500, act_apy=0.10, exp_apy=0.10)]
        report = self.r.reconcile("2026-01-01", data)
        self.assertAlmostEqual(report.total_actual_pnl, 10.0, delta=0.001)

    def test_total_variance_usd(self):
        data = [
            _make_strategy("S0", capital=36500, exp_apy=0.10, act_apy=0.10),
            _make_strategy("S1", capital=36500, exp_apy=0.10, act_apy=0.05),
        ]
        report = self.r.reconcile("2026-01-01", data)
        # S0: var=0, S1: var = -5.0
        self.assertAlmostEqual(report.total_variance_usd, -5.0, delta=0.01)

    def test_underperformers_list(self):
        data = [
            _make_strategy("S0", exp_apy=0.10, act_apy=0.02),
            _make_strategy("S1", exp_apy=0.05, act_apy=0.05),
        ]
        report = self.r.reconcile("2026-01-01", data)
        self.assertIn("S0", report.underperformers)
        self.assertNotIn("S1", report.underperformers)

    def test_overperformers_list(self):
        data = [
            _make_strategy("S0", exp_apy=0.05, act_apy=0.12),
            _make_strategy("S1", exp_apy=0.05, act_apy=0.05),
        ]
        report = self.r.reconcile("2026-01-01", data)
        self.assertIn("S0", report.overperformers)
        self.assertNotIn("S1", report.overperformers)

    def test_overall_status_green_all_on_track(self):
        data = [_make_strategy(f"S{i}") for i in range(5)]
        report = self.r.reconcile("2026-01-01", data)
        self.assertEqual(report.overall_status, "GREEN")

    def test_overall_status_red_majority_under(self):
        data = [
            _make_strategy("S0", exp_apy=0.10, act_apy=0.01),
            _make_strategy("S1", exp_apy=0.10, act_apy=0.01),
            _make_strategy("S2", exp_apy=0.05, act_apy=0.05),
        ]
        report = self.r.reconcile("2026-01-01", data)
        self.assertEqual(report.overall_status, "RED")

    def test_date_str_propagated(self):
        data = [_make_strategy("S0")]
        report = self.r.reconcile("2026-06-15", data)
        self.assertEqual(report.date_str, "2026-06-15")
        self.assertEqual(report.strategies[0].date_str, "2026-06-15")

    def test_timestamp_recent(self):
        data = [_make_strategy("S0")]
        before = time.time()
        report = self.r.reconcile("2026-01-01", data)
        after = time.time()
        self.assertGreaterEqual(report.timestamp, before)
        self.assertLessEqual(report.timestamp, after)


# ---------------------------------------------------------------------------
# Full scenario: 5 strategies mixed
# ---------------------------------------------------------------------------

class TestFullScenario(BaseReconcilerTest):

    def test_five_strategy_scenario(self):
        data = [
            _make_strategy("S0", capital=30_000, exp_apy=0.06, act_apy=0.06),
            _make_strategy("S1", capital=25_000, exp_apy=0.07, act_apy=0.07),
            _make_strategy("S2", capital=20_000, exp_apy=0.08, act_apy=0.04),
            _make_strategy("S3", capital=15_000, exp_apy=0.05, act_apy=0.09),
            _make_strategy("S4", capital=10_000, exp_apy=0.00, act_apy=0.00),
        ]
        report = self.r.reconcile("2026-06-13", data)
        self.assertEqual(len(report.strategies), 5)
        self.assertEqual(report.strategies[0].status, "ON_TRACK")
        self.assertEqual(report.strategies[1].status, "ON_TRACK")
        self.assertEqual(report.strategies[2].status, "UNDERPERFORM")
        self.assertEqual(report.strategies[3].status, "OVERPERFORM")
        self.assertEqual(report.strategies[4].status, "DATA_MISSING")
        self.assertIn("S2", report.underperformers)
        self.assertIn("S3", report.overperformers)
        self.assertAlmostEqual(report.total_capital_usd, 100_000, delta=0.01)

    def test_five_strategy_totals(self):
        data = [
            _make_strategy("S0", capital=36500, exp_apy=0.10, act_apy=0.10),
            _make_strategy("S1", capital=36500, exp_apy=0.10, act_apy=0.10),
        ]
        report = self.r.reconcile("2026-01-01", data)
        self.assertAlmostEqual(report.total_expected_pnl, 20.0, delta=0.01)
        self.assertAlmostEqual(report.total_actual_pnl, 20.0, delta=0.01)
        self.assertAlmostEqual(report.total_variance_usd, 0.0, delta=0.001)

    def test_strategy_count_in_report(self):
        data = [_make_strategy(f"S{i}") for i in range(7)]
        report = self.r.reconcile("2026-01-01", data)
        self.assertEqual(len(report.strategies), 7)


# ---------------------------------------------------------------------------
# save_report / load_history / ring-buffer
# ---------------------------------------------------------------------------

class TestSaveAndLoad(BaseReconcilerTest):

    def _make_report(self, date="2026-01-01"):
        data = [_make_strategy("S0")]
        return self.r.reconcile(date, data)

    def test_save_creates_file(self):
        self.r.save_report(self._make_report())
        self.assertTrue(self.data_file.exists())

    def test_save_valid_json(self):
        self.r.save_report(self._make_report())
        content = json.loads(self.data_file.read_text())
        self.assertIsInstance(content, list)
        self.assertEqual(len(content), 1)

    def test_save_entry_fields(self):
        self.r.save_report(self._make_report())
        entry = json.loads(self.data_file.read_text())[0]
        for key in ("date_str", "overall_status", "strategy_count", "timestamp"):
            self.assertIn(key, entry)

    def test_ring_buffer_max_entries(self):
        for i in range(MAX_ENTRIES + 10):
            self.r.save_report(self._make_report())
        history = json.loads(self.data_file.read_text())
        self.assertEqual(len(history), MAX_ENTRIES)

    def test_atomic_write_no_tmp_left(self):
        self.r.save_report(self._make_report())
        self.assertFalse(self.data_file.with_suffix(".tmp").exists())

    def test_load_history_missing_file(self):
        self.assertEqual(self.r.load_history(), [])

    def test_load_history_returns_list(self):
        self.r.save_report(self._make_report())
        history = self.r.load_history()
        self.assertIsInstance(history, list)
        self.assertEqual(len(history), 1)

    def test_load_history_corrupt_file(self):
        self.data_file.write_text("not json!!!")
        self.assertEqual(self.r.load_history(), [])

    def test_multiple_saves_accumulate(self):
        for i in range(5):
            self.r.save_report(self._make_report())
        self.assertEqual(len(self.r.load_history()), 5)


# ---------------------------------------------------------------------------
# get_streak
# ---------------------------------------------------------------------------

class TestGetStreak(BaseReconcilerTest):

    def _push_status(self, status):
        existing = self.r.load_history()
        existing.append({
            "date_str": "2026-01-01",
            "timestamp": time.time(),
            "overall_status": status,
            "strategy_count": 1,
            "total_capital_usd": 10000.0,
            "total_expected_pnl": 1.0,
            "total_actual_pnl": 1.0,
            "total_variance_usd": 0.0,
            "underperformers": [],
            "overperformers": [],
        })
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def test_empty_history_zero(self):
        self.assertEqual(self.r.get_streak("GREEN"), 0)

    def test_single_green(self):
        self._push_status("GREEN")
        self.assertEqual(self.r.get_streak("GREEN"), 1)

    def test_streak_three_green(self):
        for _ in range(3):
            self._push_status("GREEN")
        self.assertEqual(self.r.get_streak("GREEN"), 3)

    def test_streak_broken_by_red(self):
        self._push_status("GREEN")
        self._push_status("RED")
        self._push_status("GREEN")
        self._push_status("GREEN")
        self.assertEqual(self.r.get_streak("GREEN"), 2)

    def test_streak_broken_by_yellow(self):
        self._push_status("GREEN")
        self._push_status("GREEN")
        self._push_status("YELLOW")
        self._push_status("GREEN")
        self.assertEqual(self.r.get_streak("GREEN"), 1)

    def test_streak_zero_when_last_is_red(self):
        self._push_status("GREEN")
        self._push_status("GREEN")
        self._push_status("RED")
        self.assertEqual(self.r.get_streak("GREEN"), 0)

    def test_streak_yellow_status(self):
        self._push_status("YELLOW")
        self._push_status("YELLOW")
        self.assertEqual(self.r.get_streak("YELLOW"), 2)

    def test_streak_default_is_green(self):
        self._push_status("GREEN")
        self.assertEqual(self.r.get_streak(), 1)


if __name__ == "__main__":
    unittest.main()
