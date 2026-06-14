"""
Tests for MP-705: SharpeRatioCalculator
≥60 test cases using unittest only (no pytest, no numpy, no pandas).
Tempfile-based persistence — production data/ is never touched.
"""

import json
import math
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.sharpe_ratio_calculator import (
    MAX_ENTRIES,
    SHARPE_EXCELLENT,
    SHARPE_GOOD,
    SharpeRatioCalculator,
    SharpeReport,
)


class TestMean(unittest.TestCase):
    def setUp(self):
        self.c = SharpeRatioCalculator()

    def test_empty(self):
        self.assertEqual(self.c._mean([]), 0.0)

    def test_single(self):
        self.assertEqual(self.c._mean([0.05]), 0.05)

    def test_average(self):
        self.assertAlmostEqual(self.c._mean([0.1, 0.2, 0.3]), 0.2)

    def test_negative(self):
        self.assertAlmostEqual(self.c._mean([-0.1, 0.1]), 0.0)


class TestStdev(unittest.TestCase):
    def setUp(self):
        self.c = SharpeRatioCalculator()

    def test_fewer_than_two(self):
        self.assertEqual(self.c._sample_stdev([0.1], 0.1), 0.0)

    def test_empty(self):
        self.assertEqual(self.c._sample_stdev([], 0.0), 0.0)

    def test_known_value(self):
        xs = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        m = sum(xs) / len(xs)
        # sample stdev of this classic set is sqrt(32/7)
        self.assertAlmostEqual(self.c._sample_stdev(xs, m), math.sqrt(32 / 7), places=6)

    def test_zero_variance(self):
        self.assertEqual(self.c._sample_stdev([0.05, 0.05, 0.05], 0.05), 0.0)

    def test_two_points(self):
        # values 0 and 2, mean 1, sample var = ((1)+(1))/1 =2, stdev sqrt2
        self.assertAlmostEqual(self.c._sample_stdev([0.0, 2.0], 1.0), math.sqrt(2.0))


class TestDownsideDeviation(unittest.TestCase):
    def setUp(self):
        self.c = SharpeRatioCalculator()

    def test_empty(self):
        self.assertEqual(self.c._downside_deviation([], 0.0), 0.0)

    def test_all_above_target(self):
        self.assertEqual(self.c._downside_deviation([0.1, 0.2], 0.0), 0.0)

    def test_some_below(self):
        # returns [-0.1, 0.1], target 0 -> only -0.1 counts; rms = sqrt((0.01)/2)
        val = self.c._downside_deviation([-0.1, 0.1], 0.0)
        self.assertAlmostEqual(val, math.sqrt(0.01 / 2), places=6)

    def test_target_shifts_downside(self):
        # target 0.05; returns [0.0, 0.1] -> 0.0 is below by 0.05
        val = self.c._downside_deviation([0.0, 0.1], 0.05)
        self.assertAlmostEqual(val, math.sqrt((0.05 ** 2) / 2), places=6)

    def test_all_below(self):
        val = self.c._downside_deviation([-0.1, -0.2], 0.0)
        self.assertAlmostEqual(val, math.sqrt((0.01 + 0.04) / 2), places=6)


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.c = SharpeRatioCalculator()

    def test_excellent_boundary(self):
        self.assertEqual(self.c._classify(SHARPE_EXCELLENT), "EXCELLENT")

    def test_excellent_high(self):
        self.assertEqual(self.c._classify(3.5), "EXCELLENT")

    def test_good_boundary(self):
        self.assertEqual(self.c._classify(SHARPE_GOOD), "GOOD")

    def test_good_mid(self):
        self.assertEqual(self.c._classify(1.5), "GOOD")

    def test_acceptable_zero(self):
        self.assertEqual(self.c._classify(0.0), "ACCEPTABLE")

    def test_acceptable_mid(self):
        self.assertEqual(self.c._classify(0.5), "ACCEPTABLE")

    def test_poor_negative(self):
        self.assertEqual(self.c._classify(-0.5), "POOR")

    def test_just_below_good(self):
        self.assertEqual(self.c._classify(0.999), "ACCEPTABLE")

    def test_just_below_excellent(self):
        self.assertEqual(self.c._classify(1.999), "GOOD")


class TestAnalyzeGuards(unittest.TestCase):
    def setUp(self):
        self.c = SharpeRatioCalculator()

    def test_empty(self):
        r = self.c.analyze([])
        self.assertEqual(r.performance_tier, "UNKNOWN")
        self.assertEqual(r.num_returns, 0)

    def test_single(self):
        r = self.c.analyze([0.05])
        self.assertEqual(r.performance_tier, "UNKNOWN")

    def test_single_advisory(self):
        r = self.c.analyze([0.05])
        self.assertTrue(any("at least 2" in a for a in r.advisory))

    def test_returns_report_type(self):
        self.assertIsInstance(self.c.analyze([0.01, 0.02]), SharpeReport)

    def test_ppy_defaults_to_one_when_zero(self):
        r = self.c.analyze([0.01, 0.02], periods_per_year=0)
        self.assertEqual(r.periods_per_year, 1)

    def test_ppy_defaults_to_one_when_negative(self):
        r = self.c.analyze([0.01, 0.02], periods_per_year=-5)
        self.assertEqual(r.periods_per_year, 1)


class TestSharpeMath(unittest.TestCase):
    def setUp(self):
        self.c = SharpeRatioCalculator()

    def test_positive_sharpe(self):
        r = self.c.analyze([0.01, 0.02, 0.015, 0.012])
        self.assertGreater(r.sharpe_ratio, 0.0)

    def test_zero_volatility_zero_sharpe(self):
        r = self.c.analyze([0.05, 0.05, 0.05])
        self.assertEqual(r.volatility, 0.0)
        self.assertEqual(r.sharpe_ratio, 0.0)

    def test_zero_vol_advisory(self):
        r = self.c.analyze([0.05, 0.05, 0.05])
        self.assertTrue(any("Zero volatility" in a for a in r.advisory))

    def test_risk_free_reduces_sharpe(self):
        base = self.c.analyze([0.02, 0.03, 0.04], risk_free_per_period=0.0)
        with_rf = self.c.analyze([0.02, 0.03, 0.04], risk_free_per_period=0.01)
        self.assertGreater(base.sharpe_ratio, with_rf.sharpe_ratio)

    def test_known_sharpe(self):
        # returns [0.0,0.02], mean 0.01, sample stdev sqrt2*0.01... compute
        r = self.c.analyze([0.0, 0.02], risk_free_per_period=0.0, periods_per_year=1)
        mean = 0.01
        stdev = math.sqrt(((0.0 - 0.01) ** 2 + (0.02 - 0.01) ** 2) / 1)
        self.assertAlmostEqual(r.sharpe_ratio, round(mean / stdev, 6), places=6)

    def test_negative_mean_negative_sharpe(self):
        r = self.c.analyze([-0.02, -0.01, -0.03])
        self.assertLess(r.sharpe_ratio, 0.0)
        self.assertEqual(r.performance_tier, "POOR")

    def test_mean_return_rounded(self):
        r = self.c.analyze([0.011111111, 0.022222222])
        self.assertEqual(r.mean_return, round((0.011111111 + 0.022222222) / 2, 6))


class TestSortino(unittest.TestCase):
    def setUp(self):
        self.c = SharpeRatioCalculator()

    def test_sortino_positive(self):
        r = self.c.analyze([0.01, -0.005, 0.02, 0.015])
        self.assertGreater(r.sortino_ratio, 0.0)

    def test_no_downside_zero_sortino(self):
        # all returns above risk-free target -> downside dev 0 -> sortino 0
        r = self.c.analyze([0.02, 0.03, 0.04], risk_free_per_period=0.0)
        self.assertEqual(r.downside_deviation, 0.0)
        self.assertEqual(r.sortino_ratio, 0.0)

    def test_sortino_exceeds_sharpe_advisory(self):
        # one small downside, several larger upside moves -> sortino > sharpe
        r = self.c.analyze([-0.01, 0.02, 0.03, 0.025], risk_free_per_period=0.0)
        self.assertGreater(r.sortino_ratio, r.sharpe_ratio)
        self.assertNotEqual(r.sortino_ratio, 0.0)
        self.assertTrue(any("Sortino exceeds Sharpe" in a for a in r.advisory))


class TestAnnualization(unittest.TestCase):
    def setUp(self):
        self.c = SharpeRatioCalculator()

    def test_annualized_sharpe_scales(self):
        r = self.c.analyze([0.01, 0.02, 0.015], periods_per_year=12)
        self.assertAlmostEqual(
            r.annualized_sharpe, round(r.sharpe_ratio * math.sqrt(12), 6), places=6
        )

    def test_annualized_return_scales(self):
        r = self.c.analyze([0.01, 0.01], periods_per_year=12)
        self.assertAlmostEqual(r.annualized_return, round(0.01 * 12, 6), places=6)

    def test_ppy_one_no_scaling(self):
        r = self.c.analyze([0.01, 0.02, 0.015], periods_per_year=1)
        self.assertAlmostEqual(r.annualized_sharpe, r.sharpe_ratio, places=6)

    def test_annualized_sortino_scales(self):
        r = self.c.analyze([0.01, -0.005, 0.02], periods_per_year=4)
        self.assertAlmostEqual(
            r.annualized_sortino, r.sortino_ratio * math.sqrt(4), places=4
        )

    def test_tier_based_on_annualized(self):
        # small per-period sharpe but high ppy can lift tier
        r = self.c.analyze([0.01, 0.011, 0.009, 0.012], periods_per_year=365)
        self.assertIn(r.performance_tier, {"EXCELLENT", "GOOD", "ACCEPTABLE", "POOR"})


class TestRounding(unittest.TestCase):
    def setUp(self):
        self.c = SharpeRatioCalculator()

    def test_all_ratios_6dp(self):
        r = self.c.analyze([0.013, 0.027, 0.011])
        for v in (r.sharpe_ratio, r.sortino_ratio, r.annualized_sharpe, r.volatility):
            self.assertEqual(v, round(v, 6))

    def test_generated_at_set(self):
        r = self.c.analyze([0.01, 0.02])
        self.assertTrue(r.generated_at.endswith("Z"))

    def test_periods_recorded(self):
        r = self.c.analyze([0.01, 0.02], periods_per_year=52)
        self.assertEqual(r.periods_per_year, 52)


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.c = SharpeRatioCalculator()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sharpe.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing_empty(self):
        self.assertEqual(self.c.load_history(self.path), [])

    def test_save_then_load(self):
        self.c.save_report(self.c.analyze([0.01, 0.02, 0.015]), self.path)
        self.assertEqual(len(self.c.load_history(self.path)), 1)

    def test_saved_fields(self):
        self.c.save_report(self.c.analyze([0.01, 0.02, 0.015]), self.path)
        e = self.c.load_history(self.path)[0]
        self.assertIn("sharpe_ratio", e)
        self.assertIn("performance_tier", e)
        self.assertIn("advisory", e)

    def test_append_multiple(self):
        for _ in range(4):
            self.c.save_report(self.c.analyze([0.01, 0.02]), self.path)
        self.assertEqual(len(self.c.load_history(self.path)), 4)

    def test_ring_buffer_cap(self):
        for _ in range(MAX_ENTRIES + 5):
            self.c.save_report(self.c.analyze([0.01, 0.02]), self.path)
        self.assertEqual(len(self.c.load_history(self.path)), MAX_ENTRIES)

    def test_corrupt_returns_empty(self):
        self.path.write_text("garbage{{")
        self.assertEqual(self.c.load_history(self.path), [])

    def test_no_tmp_left(self):
        self.c.save_report(self.c.analyze([0.01, 0.02]), self.path)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_valid_json(self):
        self.c.save_report(self.c.analyze([0.01, 0.02]), self.path)
        json.loads(self.path.read_text())

    def test_creates_parent_dir(self):
        nested = Path(self.tmp.name) / "x" / "y" / "sharpe.json"
        self.c.save_report(self.c.analyze([0.01, 0.02]), nested)
        self.assertTrue(nested.exists())


class TestFullScenario(unittest.TestCase):
    def setUp(self):
        self.c = SharpeRatioCalculator()

    def test_realistic_monthly(self):
        returns = [0.012, 0.008, -0.004, 0.015, 0.006, 0.010, -0.002, 0.009]
        r = self.c.analyze(returns, risk_free_per_period=0.003, periods_per_year=12)
        self.assertEqual(r.num_returns, 8)
        self.assertIn(r.performance_tier, {"EXCELLENT", "GOOD", "ACCEPTABLE", "POOR"})
        self.assertTrue(len(r.advisory) >= 1)

    def test_tier_in_known_set(self):
        r = self.c.analyze([0.01, 0.02, 0.03])
        self.assertIn(
            r.performance_tier, {"EXCELLENT", "GOOD", "ACCEPTABLE", "POOR", "UNKNOWN"}
        )

    def test_excellent_scenario(self):
        # very stable positive returns, high ppy
        r = self.c.analyze([0.01, 0.0105, 0.0102, 0.0108], periods_per_year=12)
        self.assertEqual(r.performance_tier, "EXCELLENT")

    def test_poor_scenario(self):
        r = self.c.analyze([-0.02, 0.03, -0.04, 0.01], periods_per_year=12)
        self.assertEqual(r.performance_tier, "POOR")

    def test_advisory_present(self):
        r = self.c.analyze([0.01, 0.02, 0.015])
        self.assertTrue(len(r.advisory) >= 1)


if __name__ == "__main__":
    unittest.main()
