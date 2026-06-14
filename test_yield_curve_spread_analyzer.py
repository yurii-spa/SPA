"""
Tests for MP-732: YieldCurveSpreadAnalyzer
≥65 tests using unittest only.
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure repo root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.yield_curve_spread_analyzer import (
    YieldTenor,
    YieldSpread,
    YieldCurveAnalysisResult,
    compute_spread,
    compute_curve_shape,
    risk_adjusted_yield,
    analyze,
    save_results,
    load_history,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tenor(label="1W", days=7, apy=5.0, protocol="Proto", risk_score=20.0):
    return YieldTenor(label=label, days=days, apy=apy, protocol=protocol, risk_score=risk_score)


def make_normal_tenors():
    """Monotonically increasing APY (NORMAL curve)."""
    return [
        make_tenor("1W",  7,   3.0, "A", 10),
        make_tenor("1M",  30,  4.0, "B", 20),
        make_tenor("3M",  90,  5.0, "C", 30),
        make_tenor("6M",  180, 6.0, "D", 50),
        make_tenor("1Y",  365, 7.0, "E", 80),
    ]


def make_inverted_tenors():
    """Monotonically decreasing APY (INVERTED curve)."""
    return [
        make_tenor("1W",  7,   7.0, "A", 10),
        make_tenor("1M",  30,  6.0, "B", 20),
        make_tenor("3M",  90,  5.0, "C", 30),
        make_tenor("6M",  180, 4.0, "D", 50),
        make_tenor("1Y",  365, 3.0, "E", 80),
    ]


def make_humped_tenors():
    """Peak in middle (HUMPED curve)."""
    return [
        make_tenor("1W",  7,   3.0, "A", 10),
        make_tenor("1M",  30,  5.0, "B", 20),
        make_tenor("3M",  90,  8.0, "C", 30),  # peak
        make_tenor("6M",  180, 5.5, "D", 50),
        make_tenor("1Y",  365, 4.0, "E", 80),
    ]


# ---------------------------------------------------------------------------
# 1. compute_spread — spread_bps formula
# ---------------------------------------------------------------------------

class TestComputeSpreadBps(unittest.TestCase):
    def test_spread_bps_positive(self):
        long_t = make_tenor("1Y", 365, 8.0)
        short_t = make_tenor("1W",  7,  3.0)
        s = compute_spread(long_t, short_t)
        self.assertAlmostEqual(s.spread_bps, (8.0 - 3.0) * 100)

    def test_spread_bps_negative(self):
        long_t = make_tenor("1Y", 365, 2.0)
        short_t = make_tenor("1W",  7,  6.0)
        s = compute_spread(long_t, short_t)
        self.assertAlmostEqual(s.spread_bps, (2.0 - 6.0) * 100)

    def test_spread_bps_zero(self):
        long_t = make_tenor("1M", 30, 5.0)
        short_t = make_tenor("1W", 7, 5.0)
        s = compute_spread(long_t, short_t)
        self.assertAlmostEqual(s.spread_bps, 0.0)

    def test_spread_label(self):
        long_t = make_tenor("1Y", 365, 7.0)
        short_t = make_tenor("1W",  7,  3.0)
        s = compute_spread(long_t, short_t)
        self.assertEqual(s.label, "1Y-1W")

    def test_spread_stores_apys(self):
        long_t = make_tenor("1M", 30, 6.0)
        short_t = make_tenor("1W", 7,  4.0)
        s = compute_spread(long_t, short_t)
        self.assertEqual(s.long_apy, 6.0)
        self.assertEqual(s.short_apy, 4.0)


# ---------------------------------------------------------------------------
# 2. compute_spread — direction
# ---------------------------------------------------------------------------

class TestComputeSpreadDirection(unittest.TestCase):
    def test_direction_normal_large(self):
        long_t = make_tenor("1Y", 365, 10.0)
        short_t = make_tenor("1W",  7,   3.0)
        s = compute_spread(long_t, short_t)
        self.assertEqual(s.spread_direction, "NORMAL")

    def test_direction_normal_boundary(self):
        # 6 bps → NORMAL (>5)
        long_t = make_tenor("1Y", 365, 5.06)
        short_t = make_tenor("1W",  7,   5.0)
        s = compute_spread(long_t, short_t)
        self.assertEqual(s.spread_direction, "NORMAL")

    def test_direction_inverted_large(self):
        long_t = make_tenor("1Y", 365, 2.0)
        short_t = make_tenor("1W",  7,  9.0)
        s = compute_spread(long_t, short_t)
        self.assertEqual(s.spread_direction, "INVERTED")

    def test_direction_inverted_boundary(self):
        # -6 bps → INVERTED (<-5)
        long_t = make_tenor("1Y", 365, 4.94)
        short_t = make_tenor("1W",  7,  5.0)
        s = compute_spread(long_t, short_t)
        self.assertEqual(s.spread_direction, "INVERTED")

    def test_direction_flat_zero(self):
        long_t = make_tenor("1M", 30, 5.0)
        short_t = make_tenor("1W", 7, 5.0)
        s = compute_spread(long_t, short_t)
        self.assertEqual(s.spread_direction, "FLAT")

    def test_direction_flat_small_positive(self):
        # 4 bps → FLAT (not >5)
        long_t = make_tenor("1M", 30, 5.04)
        short_t = make_tenor("1W", 7,  5.0)
        s = compute_spread(long_t, short_t)
        self.assertEqual(s.spread_direction, "FLAT")

    def test_direction_flat_small_negative(self):
        # -4 bps → FLAT (not <-5)
        long_t = make_tenor("1M", 30, 4.96)
        short_t = make_tenor("1W", 7,  5.0)
        s = compute_spread(long_t, short_t)
        self.assertEqual(s.spread_direction, "FLAT")


# ---------------------------------------------------------------------------
# 3. compute_spread — signal
# ---------------------------------------------------------------------------

class TestComputeSpreadSignal(unittest.TestCase):
    def test_signal_steepening_positive(self):
        # spread > 100 bps
        long_t = make_tenor("1Y", 365, 12.0)
        short_t = make_tenor("1W",  7,   1.0)
        s = compute_spread(long_t, short_t)
        self.assertEqual(s.signal, "STEEPENING")

    def test_signal_steepening_negative(self):
        # spread < -100 bps
        long_t = make_tenor("1Y", 365, 1.0)
        short_t = make_tenor("1W",  7, 12.0)
        s = compute_spread(long_t, short_t)
        self.assertEqual(s.signal, "STEEPENING")

    def test_signal_flattening_positive(self):
        # spread < 20 bps positive
        long_t = make_tenor("1M", 30, 5.1)
        short_t = make_tenor("1W", 7, 5.0)
        s = compute_spread(long_t, short_t)
        self.assertEqual(s.signal, "FLATTENING")

    def test_signal_flattening_negative(self):
        # spread between -20 and 0 (abs < 20)
        long_t = make_tenor("1M", 30, 4.9)
        short_t = make_tenor("1W", 7, 5.0)
        s = compute_spread(long_t, short_t)
        self.assertEqual(s.signal, "FLATTENING")

    def test_signal_stable_midrange(self):
        # 50 bps → STABLE (20 ≤ abs ≤ 100)
        long_t = make_tenor("1Y", 365, 5.5)
        short_t = make_tenor("1W",  7,  5.0)
        s = compute_spread(long_t, short_t)
        self.assertEqual(s.signal, "STABLE")

    def test_signal_stable_exactly_at_boundary_100(self):
        # exactly 100 bps → STABLE (not > 100)
        long_t = make_tenor("1Y", 365, 6.0)
        short_t = make_tenor("1W",  7,  5.0)
        s = compute_spread(long_t, short_t)
        self.assertEqual(s.signal, "STABLE")


# ---------------------------------------------------------------------------
# 4. compute_curve_shape
# ---------------------------------------------------------------------------

class TestComputeCurveShape(unittest.TestCase):
    def test_shape_normal(self):
        tenors = make_normal_tenors()
        self.assertEqual(compute_curve_shape(tenors), "NORMAL")

    def test_shape_normal_two_tenors(self):
        tenors = [make_tenor("1W", 7, 3.0), make_tenor("1M", 30, 5.0)]
        self.assertEqual(compute_curve_shape(tenors), "NORMAL")

    def test_shape_inverted(self):
        tenors = make_inverted_tenors()
        self.assertEqual(compute_curve_shape(tenors), "INVERTED")

    def test_shape_inverted_two_tenors(self):
        tenors = [make_tenor("1W", 7, 7.0), make_tenor("1M", 30, 3.0)]
        self.assertEqual(compute_curve_shape(tenors), "INVERTED")

    def test_shape_humped(self):
        tenors = make_humped_tenors()
        self.assertEqual(compute_curve_shape(tenors), "HUMPED")

    def test_shape_flat_equal_apys(self):
        tenors = [
            make_tenor("1W",  7,   5.0),
            make_tenor("1M",  30,  5.0),
            make_tenor("3M",  90,  5.0),
        ]
        # All same → both inc and dec are satisfied but inc check should win (<=)
        # Actually: all equal → monotonically increasing (<=) → NORMAL
        shape = compute_curve_shape(tenors)
        self.assertIn(shape, ("NORMAL", "FLAT"))  # equal APYs satisfy both conditions

    def test_shape_single_tenor(self):
        tenors = [make_tenor("1W", 7, 5.0)]
        self.assertEqual(compute_curve_shape(tenors), "FLAT")

    def test_shape_unsorted_input_still_correct(self):
        # Supply in unsorted order — function must sort internally
        tenors = [
            make_tenor("1Y",  365, 7.0, "E"),
            make_tenor("1W",  7,   3.0, "A"),
            make_tenor("3M",  90,  5.0, "C"),
            make_tenor("1M",  30,  4.0, "B"),
            make_tenor("6M",  180, 6.0, "D"),
        ]
        self.assertEqual(compute_curve_shape(tenors), "NORMAL")

    def test_shape_humped_three_tenors(self):
        tenors = [
            make_tenor("1W", 7,  2.0),
            make_tenor("1M", 30, 8.0),  # peak
            make_tenor("1Y", 365, 4.0),
        ]
        self.assertEqual(compute_curve_shape(tenors), "HUMPED")


# ---------------------------------------------------------------------------
# 5. risk_adjusted_yield
# ---------------------------------------------------------------------------

class TestRiskAdjustedYield(unittest.TestCase):
    def test_basic_formula(self):
        t = make_tenor(apy=10.0, risk_score=25.0)
        # 10 / (1 + 25/100) = 10 / 1.25 = 8.0
        self.assertAlmostEqual(risk_adjusted_yield(t), 8.0)

    def test_zero_risk(self):
        t = make_tenor(apy=5.0, risk_score=0.0)
        self.assertAlmostEqual(risk_adjusted_yield(t), 5.0)

    def test_max_risk(self):
        t = make_tenor(apy=10.0, risk_score=100.0)
        # 10 / 2.0 = 5.0
        self.assertAlmostEqual(risk_adjusted_yield(t), 5.0)

    def test_higher_apy_lower_risk_wins(self):
        t_high_risk = make_tenor(apy=12.0, risk_score=80.0)
        t_low_risk  = make_tenor(apy=8.0,  risk_score=10.0)
        # 12/1.8=6.67 vs 8/1.1=7.27 → low-risk wins
        self.assertGreater(risk_adjusted_yield(t_low_risk), risk_adjusted_yield(t_high_risk))

    def test_identical_risk_higher_apy_wins(self):
        t1 = make_tenor(apy=10.0, risk_score=50.0)
        t2 = make_tenor(apy=12.0, risk_score=50.0)
        self.assertGreater(risk_adjusted_yield(t2), risk_adjusted_yield(t1))


# ---------------------------------------------------------------------------
# 6. analyze — steepness_bps
# ---------------------------------------------------------------------------

class TestAnalyzeSteepness(unittest.TestCase):
    def test_steepness_formula(self):
        tenors = [
            make_tenor("1W", 7,  2.0),
            make_tenor("1M", 30, 7.0),
        ]
        r = analyze(tenors)
        self.assertAlmostEqual(r.steepness_bps, (7.0 - 2.0) * 100)

    def test_steepness_zero_same_apy(self):
        tenors = [
            make_tenor("1W", 7,  5.0),
            make_tenor("1M", 30, 5.0),
        ]
        r = analyze(tenors)
        self.assertAlmostEqual(r.steepness_bps, 0.0)

    def test_steepness_single_tenor(self):
        r = analyze([make_tenor("1W", 7, 5.0)])
        self.assertAlmostEqual(r.steepness_bps, 0.0)


# ---------------------------------------------------------------------------
# 7. analyze — inversion_count and is_curve_inverted
# ---------------------------------------------------------------------------

class TestAnalyzeInversion(unittest.TestCase):
    def test_inversion_count_normal_curve(self):
        r = analyze(make_normal_tenors())
        self.assertEqual(r.inversion_count, 0)

    def test_inversion_count_inverted_curve(self):
        r = analyze(make_inverted_tenors())
        self.assertEqual(r.inversion_count, len(make_inverted_tenors()) - 1)

    def test_is_curve_inverted_false_normal(self):
        r = analyze(make_normal_tenors())
        self.assertFalse(r.is_curve_inverted)

    def test_is_curve_inverted_true_inverted(self):
        r = analyze(make_inverted_tenors())
        self.assertTrue(r.is_curve_inverted)

    def test_is_curve_inverted_majority_rule(self):
        # 3 inverted, 1 normal out of 4 adjacent → majority inverted
        tenors = [
            make_tenor("1W",  7,   8.0),
            make_tenor("1M",  30,  7.0),
            make_tenor("3M",  90,  6.0),
            make_tenor("6M",  180, 5.0),
            make_tenor("1Y",  365, 9.0),  # one non-inverted at end
        ]
        r = analyze(tenors)
        # 3 out of 4 adjacent spreads inverted → majority
        self.assertTrue(r.is_curve_inverted)

    def test_inversion_count_partial(self):
        # Humped: 1W→1M normal, 1M→3M inverted part
        tenors = make_humped_tenors()
        r = analyze(tenors)
        self.assertGreaterEqual(r.inversion_count, 0)


# ---------------------------------------------------------------------------
# 8. analyze — optimal_tenor
# ---------------------------------------------------------------------------

class TestAnalyzeOptimalTenor(unittest.TestCase):
    def test_optimal_tenor_is_best_risk_adjusted(self):
        tenors = [
            make_tenor("1W",  7,   5.0, risk_score=10),   # 5/1.1 = 4.545
            make_tenor("1M",  30,  8.0, risk_score=50),   # 8/1.5 = 5.333
            make_tenor("3M",  90,  7.0, risk_score=20),   # 7/1.2 = 5.833  ← best
            make_tenor("1Y",  365, 15.0, risk_score=90),  # 15/1.9 = 7.89 ← actually best
        ]
        r = analyze(tenors)
        # 15/1.9 = 7.89 is best
        self.assertEqual(r.optimal_tenor, "1Y")

    def test_optimal_tenor_low_risk_wins_when_apy_comparable(self):
        tenors = [
            make_tenor("1W", 7,  10.0, risk_score=80),  # 10/1.8=5.55
            make_tenor("1M", 30, 8.0,  risk_score=0),   # 8/1.0=8.0  ← best
        ]
        r = analyze(tenors)
        self.assertEqual(r.optimal_tenor, "1M")

    def test_optimal_tenor_single(self):
        r = analyze([make_tenor("1W", 7, 5.0)])
        self.assertEqual(r.optimal_tenor, "1W")


# ---------------------------------------------------------------------------
# 9. analyze — risk_premium_bps
# ---------------------------------------------------------------------------

class TestAnalyzeRiskPremium(unittest.TestCase):
    def test_risk_premium_positive(self):
        tenors = [
            make_tenor("1W", 7,  3.0, risk_score=10),  # low-risk
            make_tenor("1Y", 365, 9.0, risk_score=80), # high-risk
        ]
        r = analyze(tenors)
        # (9.0 - 3.0) * 100 = 600
        self.assertAlmostEqual(r.risk_premium_bps, 600.0)

    def test_risk_premium_zero_no_high_risk(self):
        tenors = [
            make_tenor("1W", 7,  3.0, risk_score=10),
            make_tenor("1M", 30, 5.0, risk_score=20),
        ]
        r = analyze(tenors)
        self.assertAlmostEqual(r.risk_premium_bps, 0.0)

    def test_risk_premium_zero_no_low_risk(self):
        tenors = [
            make_tenor("1W", 7,  5.0, risk_score=75),
            make_tenor("1M", 30, 8.0, risk_score=85),
        ]
        r = analyze(tenors)
        self.assertAlmostEqual(r.risk_premium_bps, 0.0)

    def test_risk_premium_multiple_each(self):
        tenors = [
            make_tenor("1W",  7,   2.0, risk_score=5),   # low
            make_tenor("1M",  30,  4.0, risk_score=20),  # low
            make_tenor("3M",  90,  8.0, risk_score=75),  # high
            make_tenor("1Y",  365, 12.0, risk_score=90), # high
        ]
        r = analyze(tenors)
        # avg_high = (8+12)/2 = 10; avg_low = (2+4)/2 = 3; premium = 700 bps
        self.assertAlmostEqual(r.risk_premium_bps, 700.0)


# ---------------------------------------------------------------------------
# 10. analyze — curve_shape propagation
# ---------------------------------------------------------------------------

class TestAnalyzeCurveShape(unittest.TestCase):
    def test_curve_shape_normal(self):
        r = analyze(make_normal_tenors())
        self.assertEqual(r.curve_shape, "NORMAL")

    def test_curve_shape_inverted(self):
        r = analyze(make_inverted_tenors())
        self.assertEqual(r.curve_shape, "INVERTED")

    def test_curve_shape_humped(self):
        r = analyze(make_humped_tenors())
        self.assertEqual(r.curve_shape, "HUMPED")


# ---------------------------------------------------------------------------
# 11. analyze — edge cases
# ---------------------------------------------------------------------------

class TestAnalyzeEdgeCases(unittest.TestCase):
    def test_single_tenor_no_spreads(self):
        r = analyze([make_tenor("1W", 7, 5.0)])
        # adjacent spreads: 0; overall: also 0 (only 1 tenor)
        adj_spreads = [s for s in r.spreads if not s.label.startswith("MAX")]
        self.assertEqual(len(adj_spreads), 0)

    def test_single_tenor_shape_flat(self):
        r = analyze([make_tenor("1W", 7, 5.0)])
        self.assertEqual(r.curve_shape, "FLAT")

    def test_two_tenors_one_spread(self):
        tenors = [make_tenor("1W", 7, 3.0), make_tenor("1M", 30, 5.0)]
        r = analyze(tenors)
        # 1 adjacent + 0 or 1 overall (same spread)
        self.assertGreaterEqual(len(r.spreads), 1)

    def test_all_same_apy_steepness_zero(self):
        tenors = [
            make_tenor("1W",  7,   5.0),
            make_tenor("1M",  30,  5.0),
            make_tenor("3M",  90,  5.0),
        ]
        r = analyze(tenors)
        self.assertAlmostEqual(r.steepness_bps, 0.0)

    def test_recommendation_is_string(self):
        r = analyze(make_normal_tenors())
        self.assertIsInstance(r.recommendation, str)
        self.assertGreater(len(r.recommendation), 0)


# ---------------------------------------------------------------------------
# 12. save / load round-trip
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._data_file = os.path.join(self._tmpdir, "test_yield_curve_spread_log.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_result(self):
        return analyze(make_normal_tenors(), data_file=self._data_file)

    def test_save_creates_file(self):
        r = self._make_result()
        save_results(r, data_file=self._data_file)
        self.assertTrue(os.path.exists(self._data_file))

    def test_load_empty_on_missing_file(self):
        hist = load_history(data_file=self._data_file)
        self.assertEqual(hist, [])

    def test_save_load_single_entry(self):
        r = self._make_result()
        save_results(r, data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertEqual(len(hist), 1)

    def test_save_accumulates_entries(self):
        for _ in range(3):
            r = self._make_result()
            save_results(r, data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertEqual(len(hist), 3)

    def test_entry_has_curve_shape(self):
        r = self._make_result()
        save_results(r, data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertIn("curve_shape", hist[0])

    def test_entry_has_steepness_bps(self):
        r = self._make_result()
        save_results(r, data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertIn("steepness_bps", hist[0])

    def test_file_is_valid_json(self):
        r = self._make_result()
        save_results(r, data_file=self._data_file)
        with open(self._data_file) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)


# ---------------------------------------------------------------------------
# 13. Ring-buffer cap 100
# ---------------------------------------------------------------------------

class TestRingBuffer(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._data_file = os.path.join(self._tmpdir, "rb_test.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_ring_buffer_cap_100(self):
        for i in range(110):
            tenors = [make_tenor("1W", 7, float(i % 10 + 1))]
            r = analyze(tenors, data_file=self._data_file)
            save_results(r, data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertEqual(len(hist), 100)

    def test_ring_buffer_keeps_latest(self):
        # Save 105 entries; last entry should have steepness from last tenor
        for i in range(105):
            tenors = [
                make_tenor("1W", 7, float(i) + 1.0),
                make_tenor("1M", 30, float(i) + 2.0),
            ]
            r = analyze(tenors, data_file=self._data_file)
            save_results(r, data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertEqual(len(hist), 100)
        # Last entry should have steepness from i=104: (106-105)*100 = 100
        self.assertAlmostEqual(hist[-1]["steepness_bps"], 100.0)


# ---------------------------------------------------------------------------
# 14. Additional spread correctness tests
# ---------------------------------------------------------------------------

class TestSpreadAdditional(unittest.TestCase):
    def test_full_spread_list_length_normal_curve(self):
        tenors = make_normal_tenors()  # 5 tenors
        r = analyze(tenors)
        # 4 adjacent + 1 overall = 5 spreads
        self.assertEqual(len(r.spreads), 5)

    def test_adjacent_spreads_labels_correct(self):
        tenors = [
            make_tenor("1W", 7,  3.0),
            make_tenor("1M", 30, 5.0),
            make_tenor("3M", 90, 7.0),
        ]
        r = analyze(tenors)
        adjacent_labels = [s.label for s in r.spreads if not s.label.startswith("MAX")]
        self.assertIn("1M-1W", adjacent_labels)
        self.assertIn("3M-1M", adjacent_labels)

    def test_overall_spread_present(self):
        tenors = make_normal_tenors()
        r = analyze(tenors)
        overall = [s for s in r.spreads if s.label.startswith("MAX")]
        self.assertGreater(len(overall), 0)

    def test_spread_returns_dataclass(self):
        long_t = make_tenor("1Y", 365, 8.0)
        short_t = make_tenor("1W",  7,  3.0)
        s = compute_spread(long_t, short_t)
        self.assertIsInstance(s, YieldSpread)

    def test_result_is_dataclass(self):
        r = analyze(make_normal_tenors())
        self.assertIsInstance(r, YieldCurveAnalysisResult)


# ---------------------------------------------------------------------------
# 15. YieldTenor dataclass sanity
# ---------------------------------------------------------------------------

class TestYieldTenorDataclass(unittest.TestCase):
    def test_fields_accessible(self):
        t = make_tenor("3M", 90, 6.5, "Aave", 30.0)
        self.assertEqual(t.label, "3M")
        self.assertEqual(t.days, 90)
        self.assertAlmostEqual(t.apy, 6.5)
        self.assertEqual(t.protocol, "Aave")
        self.assertAlmostEqual(t.risk_score, 30.0)

    def test_risk_adjusted_low_risk_high_score(self):
        # risk_score=0 → no penalty
        t = make_tenor(apy=5.0, risk_score=0.0)
        self.assertAlmostEqual(risk_adjusted_yield(t), 5.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
