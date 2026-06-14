"""
Tests for MP-710: YieldMomentumTracker
≥65 unittest cases covering all helpers, signals, edge cases, persistence.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.yield_momentum_tracker import (
    MomentumSnapshot,
    MomentumReport,
    simple_ma,
    rate_of_change,
    linear_slope,
    apy_percentile,
    analyze,
    compare_momentum,
    save_results,
    load_history,
    MAX_ENTRIES,
    _crossover_signal,
    _trend_direction,
    _momentum_signal,
    _build_warnings,
)


def make_snapshots(apys):
    """Helper: create MomentumSnapshot list from APY list."""
    return [
        MomentumSnapshot(timestamp_iso=f"2026-05-{i+1:02d}T00:00:00Z", apy=a)
        for i, a in enumerate(apys)
    ]


# ---------------------------------------------------------------------------
# simple_ma
# ---------------------------------------------------------------------------

class TestSimpleMa(unittest.TestCase):

    def test_exactly_period_items(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        self.assertAlmostEqual(simple_ma(vals, 7), 4.0)

    def test_more_than_period_uses_last(self):
        vals = [100.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        # last 7: [1,2,3,4,5,6,7] avg=4
        self.assertAlmostEqual(simple_ma(vals, 7), 4.0)

    def test_fewer_than_period_uses_all(self):
        vals = [4.0, 6.0]
        # fewer than 7 → average of all
        self.assertAlmostEqual(simple_ma(vals, 7), 5.0)

    def test_single_value(self):
        self.assertAlmostEqual(simple_ma([9.0], 7), 9.0)

    def test_empty_returns_zero(self):
        self.assertAlmostEqual(simple_ma([], 7), 0.0)

    def test_period_1(self):
        vals = [1.0, 2.0, 3.0]
        self.assertAlmostEqual(simple_ma(vals, 1), 3.0)

    def test_ma14_uses_last_14(self):
        vals = list(range(1, 21))  # 1..20
        expected = sum(range(7, 21)) / 14  # last 14: 7..20
        self.assertAlmostEqual(simple_ma(vals, 14), expected)

    def test_uniform_values(self):
        vals = [5.0] * 10
        self.assertAlmostEqual(simple_ma(vals, 7), 5.0)


# ---------------------------------------------------------------------------
# rate_of_change
# ---------------------------------------------------------------------------

class TestRateOfChange(unittest.TestCase):

    def test_basic(self):
        # values[-8]=10, values[-1]=15 → (15-10)/10*100=50
        vals = [10.0, 11.0, 12.0, 11.0, 13.0, 12.0, 14.0, 15.0]
        self.assertAlmostEqual(rate_of_change(vals, 7), 50.0)

    def test_not_enough_data_returns_zero(self):
        # need period+1=8 values, only 7
        vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        self.assertAlmostEqual(rate_of_change(vals, 7), 0.0)

    def test_exactly_enough(self):
        vals = [10.0, 15.0]  # period=1: (15-10)/10*100=50
        self.assertAlmostEqual(rate_of_change(vals, 1), 50.0)

    def test_zero_base_returns_zero(self):
        vals = [0.0, 5.0, 3.0, 7.0, 2.0, 9.0, 4.0, 8.0]
        self.assertAlmostEqual(rate_of_change(vals, 7), 0.0)

    def test_negative_change(self):
        vals = [20.0, 15.0, 12.0, 10.0, 8.0, 7.0, 6.0, 5.0]
        # vals[-8]=20, vals[-1]=5 → (5-20)/20*100 = -75
        self.assertAlmostEqual(rate_of_change(vals, 7), -75.0)

    def test_no_change(self):
        vals = [10.0] * 8
        self.assertAlmostEqual(rate_of_change(vals, 7), 0.0)

    def test_roc_30_insufficient(self):
        vals = list(range(20))
        self.assertAlmostEqual(rate_of_change(vals, 30), 0.0)

    def test_single_value_returns_zero(self):
        self.assertAlmostEqual(rate_of_change([5.0], 7), 0.0)


# ---------------------------------------------------------------------------
# linear_slope
# ---------------------------------------------------------------------------

class TestLinearSlope(unittest.TestCase):

    def test_upward_series(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertGreater(linear_slope(vals), 0)

    def test_downward_series(self):
        vals = [5.0, 4.0, 3.0, 2.0, 1.0]
        self.assertLess(linear_slope(vals), 0)

    def test_flat_series_returns_zero(self):
        vals = [7.0] * 10
        self.assertAlmostEqual(linear_slope(vals), 0.0)

    def test_single_value_returns_zero(self):
        self.assertAlmostEqual(linear_slope([5.0]), 0.0)

    def test_empty_returns_zero(self):
        self.assertAlmostEqual(linear_slope([]), 0.0)

    def test_uses_last_14(self):
        # First 10 values are irrelevant noise; last 14 are 1..14
        noise = [1000.0] * 10
        signal = list(range(1, 15))   # slope ~1
        vals = noise + signal
        slope = linear_slope(vals)
        self.assertGreater(slope, 0.8)
        self.assertLess(slope, 1.2)

    def test_two_values_ascending(self):
        slope = linear_slope([1.0, 3.0])
        self.assertAlmostEqual(slope, 2.0, places=5)

    def test_exact_slope_1(self):
        vals = [float(i) for i in range(5)]  # 0,1,2,3,4
        self.assertAlmostEqual(linear_slope(vals), 1.0, places=5)


# ---------------------------------------------------------------------------
# apy_percentile
# ---------------------------------------------------------------------------

class TestApyPercentile(unittest.TestCase):

    def test_current_is_max(self):
        apys = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertAlmostEqual(apy_percentile(5.0, apys), 100.0)

    def test_current_is_min(self):
        apys = [1.0, 2.0, 3.0, 4.0, 5.0]
        # 1 value ≤ 1.0 out of 5 → 20%
        self.assertAlmostEqual(apy_percentile(1.0, apys), 20.0)

    def test_current_is_median(self):
        apys = [1.0, 2.0, 3.0, 4.0, 5.0]
        # 3 values ≤ 3.0 → 60%
        self.assertAlmostEqual(apy_percentile(3.0, apys), 60.0)

    def test_empty_history_returns_zero(self):
        self.assertAlmostEqual(apy_percentile(5.0, []), 0.0)

    def test_current_below_all(self):
        apys = [2.0, 3.0, 4.0]
        # 0 values ≤ 0.5 → 0%
        self.assertAlmostEqual(apy_percentile(0.5, apys), 0.0)

    def test_all_same_values(self):
        apys = [5.0, 5.0, 5.0, 5.0]
        self.assertAlmostEqual(apy_percentile(5.0, apys), 100.0)

    def test_current_above_all(self):
        apys = [1.0, 2.0, 3.0]
        self.assertAlmostEqual(apy_percentile(10.0, apys), 100.0)


# ---------------------------------------------------------------------------
# _crossover_signal
# ---------------------------------------------------------------------------

class TestCrossoverSignal(unittest.TestCase):

    def test_golden_cross(self):
        self.assertEqual(_crossover_signal(10.0, 8.0, 6.0), "GOLDEN_CROSS")

    def test_death_cross(self):
        self.assertEqual(_crossover_signal(4.0, 6.0, 8.0), "DEATH_CROSS")

    def test_mixed_ma7_gt_ma14_not_gt_ma30(self):
        self.assertEqual(_crossover_signal(9.0, 8.0, 10.0), "MIXED")

    def test_mixed_all_equal(self):
        self.assertEqual(_crossover_signal(5.0, 5.0, 5.0), "MIXED")

    def test_mixed_partial(self):
        # ma7 > ma14 but ma14 < ma30
        self.assertEqual(_crossover_signal(7.0, 5.0, 8.0), "MIXED")


# ---------------------------------------------------------------------------
# _trend_direction
# ---------------------------------------------------------------------------

class TestTrendDirection(unittest.TestCase):

    def test_uptrend(self):
        self.assertEqual(_trend_direction(0.5), "UPTREND")

    def test_downtrend(self):
        self.assertEqual(_trend_direction(-0.5), "DOWNTREND")

    def test_sideways_positive(self):
        self.assertEqual(_trend_direction(0.05), "SIDEWAYS")

    def test_sideways_negative(self):
        self.assertEqual(_trend_direction(-0.05), "SIDEWAYS")

    def test_sideways_zero(self):
        self.assertEqual(_trend_direction(0.0), "SIDEWAYS")

    def test_boundary_above(self):
        self.assertEqual(_trend_direction(0.11), "UPTREND")

    def test_boundary_below(self):
        self.assertEqual(_trend_direction(-0.11), "DOWNTREND")

    def test_exact_boundary(self):
        # slope == 0.1 is not > 0.1, not < -0.1 → SIDEWAYS
        self.assertEqual(_trend_direction(0.1), "SIDEWAYS")


# ---------------------------------------------------------------------------
# _momentum_signal
# ---------------------------------------------------------------------------

class TestMomentumSignal(unittest.TestCase):

    def test_strong_buy(self):
        sig = _momentum_signal(15.0, "GOLDEN_CROSS", "UPTREND")
        self.assertEqual(sig, "STRONG_BUY")

    def test_buy_roc_positive(self):
        sig = _momentum_signal(5.0, "MIXED", "SIDEWAYS")
        self.assertEqual(sig, "BUY")

    def test_buy_golden_cross_uptrend(self):
        # roc_7=1 (not >3) but GOLDEN_CROSS + UPTREND → BUY
        sig = _momentum_signal(1.0, "GOLDEN_CROSS", "UPTREND")
        self.assertEqual(sig, "BUY")

    def test_strong_sell(self):
        sig = _momentum_signal(-15.0, "DEATH_CROSS", "DOWNTREND")
        self.assertEqual(sig, "STRONG_SELL")

    def test_sell_roc_negative(self):
        sig = _momentum_signal(-5.0, "MIXED", "SIDEWAYS")
        self.assertEqual(sig, "SELL")

    def test_sell_death_cross_downtrend(self):
        # roc_7=-1 (not < -3) but DEATH_CROSS + DOWNTREND → SELL
        sig = _momentum_signal(-1.0, "DEATH_CROSS", "DOWNTREND")
        self.assertEqual(sig, "SELL")

    def test_neutral(self):
        sig = _momentum_signal(0.0, "MIXED", "SIDEWAYS")
        self.assertEqual(sig, "NEUTRAL")

    def test_neutral_roc_within_band(self):
        # roc between -3 and 3, not golden/death
        sig = _momentum_signal(2.0, "MIXED", "SIDEWAYS")
        self.assertEqual(sig, "NEUTRAL")

    def test_strong_buy_requires_golden_cross(self):
        # roc_7 > 10 but NOT golden cross → should be BUY (roc > 3)
        sig = _momentum_signal(15.0, "DEATH_CROSS", "SIDEWAYS")
        # roc > 3 → BUY
        self.assertEqual(sig, "BUY")

    def test_strong_sell_requires_death_cross(self):
        # roc_7 < -10 but NOT death cross → SELL (roc < -3)
        sig = _momentum_signal(-15.0, "GOLDEN_CROSS", "SIDEWAYS")
        self.assertEqual(sig, "SELL")


# ---------------------------------------------------------------------------
# _build_warnings
# ---------------------------------------------------------------------------

class TestBuildWarnings(unittest.TestCase):

    def test_apy_near_historical_low(self):
        warns = _build_warnings(0.0, 10.0)
        self.assertIn("APY near historical low", warns)

    def test_apy_near_historical_high(self):
        warns = _build_warnings(0.0, 85.0)
        self.assertIn("APY near historical high (may revert)", warns)

    def test_extreme_positive_momentum(self):
        warns = _build_warnings(35.0, 50.0)
        self.assertIn("extreme positive momentum (unsustainable?)", warns)

    def test_sharp_decline(self):
        warns = _build_warnings(-35.0, 50.0)
        self.assertIn("sharp decline", warns)

    def test_no_warnings(self):
        warns = _build_warnings(0.0, 50.0)
        self.assertEqual(warns, [])

    def test_multiple_warnings(self):
        warns = _build_warnings(-35.0, 10.0)
        self.assertIn("APY near historical low", warns)
        self.assertIn("sharp decline", warns)

    def test_high_apy_and_extreme_positive(self):
        warns = _build_warnings(35.0, 90.0)
        self.assertIn("APY near historical high (may revert)", warns)
        self.assertIn("extreme positive momentum (unsustainable?)", warns)


# ---------------------------------------------------------------------------
# analyze()
# ---------------------------------------------------------------------------

class TestAnalyze(unittest.TestCase):

    def setUp(self):
        self.proto = "Aave V3"
        self.pool = "USDC"
        self.snapshots_30 = make_snapshots([5.0 + i * 0.1 for i in range(30)])
        # 35 snapshots, strongly rising — ensures ma7 > ma14 > ma30
        self.snapshots_rising = make_snapshots(
            [1.0 + i * 0.3 for i in range(35)]
        )

    def test_returns_momentum_report(self):
        snap = make_snapshots([5.0, 6.0])
        report = analyze(self.proto, self.pool, snap)
        self.assertIsInstance(report, MomentumReport)

    def test_current_apy_is_last(self):
        snap = make_snapshots([1.0, 2.0, 8.0])
        report = analyze(self.proto, self.pool, snap)
        self.assertAlmostEqual(report.current_apy, 8.0)

    def test_ma7_computed(self):
        apys = [10.0] * 10
        snap = make_snapshots(apys)
        report = analyze(self.proto, self.pool, snap)
        self.assertAlmostEqual(report.ma7, 10.0)

    def test_ma14_fewer_values(self):
        apys = [5.0] * 5
        snap = make_snapshots(apys)
        report = analyze(self.proto, self.pool, snap)
        self.assertAlmostEqual(report.ma14, 5.0)

    def test_crossover_golden_on_rising(self):
        report = analyze(self.proto, self.pool, self.snapshots_rising)
        self.assertEqual(report.crossover_signal, "GOLDEN_CROSS")

    def test_trend_uptrend_on_rising(self):
        report = analyze(self.proto, self.pool, self.snapshots_rising)
        self.assertEqual(report.trend_direction, "UPTREND")

    def test_roc_zero_on_flat(self):
        snap = make_snapshots([5.0] * 10)
        report = analyze(self.proto, self.pool, snap)
        self.assertAlmostEqual(report.roc_7, 0.0)

    def test_warnings_list_exists(self):
        snap = make_snapshots([5.0, 6.0])
        report = analyze(self.proto, self.pool, snap)
        self.assertIsInstance(report.warnings, list)

    def test_saved_to_field_set(self):
        snap = make_snapshots([5.0, 6.0])
        report = analyze(self.proto, self.pool, snap)
        self.assertIn("yield_momentum_log.json", report.saved_to)

    def test_single_snapshot_no_crash(self):
        snap = make_snapshots([7.0])
        report = analyze(self.proto, self.pool, snap)
        self.assertAlmostEqual(report.current_apy, 7.0)
        self.assertAlmostEqual(report.roc_7, 0.0)
        self.assertAlmostEqual(report.trend_slope, 0.0)

    def test_all_same_apy_slope_zero(self):
        snap = make_snapshots([5.0] * 20)
        report = analyze(self.proto, self.pool, snap)
        self.assertAlmostEqual(report.trend_slope, 0.0)
        self.assertAlmostEqual(report.roc_7, 0.0)

    def test_percentile_max_when_current_highest(self):
        apys = [1.0, 2.0, 3.0, 4.0, 5.0]
        snap = make_snapshots(apys)
        report = analyze(self.proto, self.pool, snap)
        self.assertAlmostEqual(report.apy_percentile, 100.0)


# ---------------------------------------------------------------------------
# compare_momentum
# ---------------------------------------------------------------------------

class TestCompareMomentum(unittest.TestCase):

    def _make_report(self, roc):
        snap = make_snapshots([5.0, 5.0 * (1 + roc / 100)])
        r = analyze("Proto", "Pool", snap)
        # Force roc_7 for comparison testing
        r.roc_7 = roc
        return r

    def test_sorted_descending(self):
        r1 = self._make_report(10.0)
        r2 = self._make_report(2.0)
        r3 = self._make_report(-5.0)
        result = compare_momentum([r3, r1, r2])
        self.assertEqual(result[0].roc_7, 10.0)
        self.assertEqual(result[1].roc_7, 2.0)
        self.assertEqual(result[2].roc_7, -5.0)

    def test_empty_list(self):
        self.assertEqual(compare_momentum([]), [])

    def test_single_element(self):
        r = self._make_report(3.0)
        self.assertEqual(compare_momentum([r]), [r])


# ---------------------------------------------------------------------------
# save/load round-trip and ring-buffer
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "test_momentum.json"

    def tearDown(self):
        if self.data_file.exists():
            os.unlink(self.data_file)
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_save_and_load_round_trip(self):
        snap = make_snapshots([4.0, 5.0, 6.0])
        report = analyze("Morpho", "USDC", snap, data_file=self.data_file)
        save_results(report, data_file=self.data_file)
        history = load_history(data_file=self.data_file)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["protocol"], "Morpho")
        self.assertEqual(history[0]["pool"], "USDC")

    def test_multiple_saves(self):
        for i in range(5):
            snap = make_snapshots([float(i), float(i + 1)])
            report = analyze("Proto", "Pool", snap, data_file=self.data_file)
            save_results(report, data_file=self.data_file)
        history = load_history(data_file=self.data_file)
        self.assertEqual(len(history), 5)

    def test_ring_buffer_cap_at_100(self):
        for i in range(110):
            snap = make_snapshots([float(i), float(i + 1)])
            report = analyze("Proto", "Pool", snap, data_file=self.data_file)
            save_results(report, data_file=self.data_file)
        history = load_history(data_file=self.data_file)
        self.assertEqual(len(history), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            snap = make_snapshots([float(i), float(i + 1)])
            report = analyze("Proto", "Pool", snap, data_file=self.data_file)
            report.current_apy = float(i + 1)
            save_results(report, data_file=self.data_file)
        history = load_history(data_file=self.data_file)
        # The last entry should have current_apy = 105
        self.assertAlmostEqual(history[-1]["current_apy"], 105.0)

    def test_load_nonexistent_returns_empty(self):
        missing = Path(self.tmp_dir) / "nonexistent.json"
        result = load_history(data_file=missing)
        self.assertEqual(result, [])

    def test_load_corrupted_json_returns_empty(self):
        with open(self.data_file, "w") as f:
            f.write("{{not valid json")
        result = load_history(data_file=self.data_file)
        self.assertEqual(result, [])

    def test_atomic_write_no_partial_file(self):
        snap = make_snapshots([3.0, 4.0])
        report = analyze("X", "Y", snap, data_file=self.data_file)
        save_results(report, data_file=self.data_file)
        # The .tmp file should NOT remain after save
        tmp_file = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp_file.exists())

    def test_saved_to_field_in_json(self):
        snap = make_snapshots([3.0, 4.0])
        report = analyze("X", "Y", snap, data_file=self.data_file)
        save_results(report, data_file=self.data_file)
        history = load_history(data_file=self.data_file)
        self.assertIn("saved_to", history[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
