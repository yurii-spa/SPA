"""
Tests for MP-718: TimeWeightedReturnCalculator
≥50 test cases using unittest only (no pytest, no numpy, no pandas).
Tempfile-based persistence — production data/ is never touched.
"""

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.time_weighted_return_calculator import (
    MAX_ENTRIES,
    TWR_MODERATE,
    TWR_STRONG,
    TimeWeightedReturnCalculator,
    TWRReport,
)


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.c = TimeWeightedReturnCalculator()

    def test_strong_boundary(self):
        self.assertEqual(self.c._classify(TWR_STRONG), "STRONG")

    def test_strong_high(self):
        self.assertEqual(self.c._classify(0.5), "STRONG")

    def test_moderate_boundary(self):
        self.assertEqual(self.c._classify(TWR_MODERATE), "MODERATE")

    def test_moderate_mid(self):
        self.assertEqual(self.c._classify(0.05), "MODERATE")

    def test_flat_zero(self):
        self.assertEqual(self.c._classify(0.0), "FLAT")

    def test_flat_small(self):
        self.assertEqual(self.c._classify(0.01), "FLAT")

    def test_negative(self):
        self.assertEqual(self.c._classify(-0.05), "NEGATIVE")

    def test_just_below_strong(self):
        self.assertEqual(self.c._classify(0.0999), "MODERATE")

    def test_just_below_moderate(self):
        self.assertEqual(self.c._classify(0.0299), "FLAT")

    def test_just_below_flat(self):
        self.assertEqual(self.c._classify(-0.0001), "NEGATIVE")


class TestAnalyzeGuards(unittest.TestCase):
    def setUp(self):
        self.c = TimeWeightedReturnCalculator()

    def test_empty(self):
        r = self.c.analyze([])
        self.assertEqual(r.performance_tier, "UNKNOWN")
        self.assertEqual(r.num_periods, 0)

    def test_empty_advisory(self):
        r = self.c.analyze([])
        self.assertTrue(any("at least 1" in a for a in r.advisory))

    def test_returns_report_type(self):
        self.assertIsInstance(self.c.analyze([0.01]), TWRReport)

    def test_single_element_ok(self):
        r = self.c.analyze([0.05])
        self.assertEqual(r.num_periods, 1)
        self.assertNotEqual(r.performance_tier, "UNKNOWN")

    def test_ppy_defaults_to_one_when_zero(self):
        r = self.c.analyze([0.01, 0.02], periods_per_year=0)
        self.assertEqual(r.periods_per_year, 1)

    def test_ppy_defaults_to_one_when_negative(self):
        r = self.c.analyze([0.01, 0.02], periods_per_year=-5)
        self.assertEqual(r.periods_per_year, 1)

    def test_empty_zero_fields(self):
        r = self.c.analyze([])
        self.assertEqual(r.cumulative_twr, 0.0)
        self.assertEqual(r.annualized_twr, 0.0)
        self.assertEqual(r.geometric_mean_return, 0.0)


class TestTWRMath(unittest.TestCase):
    def setUp(self):
        self.c = TimeWeightedReturnCalculator()

    def test_cumulative_simple(self):
        # (1.1)*(1.1) - 1 = 0.21
        r = self.c.analyze([0.1, 0.1])
        self.assertAlmostEqual(r.cumulative_twr, 0.21, places=6)

    def test_cumulative_single(self):
        r = self.c.analyze([0.05])
        self.assertAlmostEqual(r.cumulative_twr, 0.05, places=6)

    def test_cumulative_mixed(self):
        # (1.02)*(0.99) - 1
        r = self.c.analyze([0.02, -0.01])
        expected = 1.02 * 0.99 - 1.0
        self.assertAlmostEqual(r.cumulative_twr, round(expected, 6), places=6)

    def test_geometric_mean(self):
        # factor = 1.1*1.1 = 1.21 ; gm = 1.21**0.5 - 1 = 0.1
        r = self.c.analyze([0.1, 0.1])
        self.assertAlmostEqual(r.geometric_mean_return, 0.1, places=6)

    def test_geometric_mean_single(self):
        r = self.c.analyze([0.07])
        self.assertAlmostEqual(r.geometric_mean_return, 0.07, places=6)

    def test_geometric_mean_three(self):
        # factor = 1.2*1.0*0.8 = 0.96 ; gm = 0.96**(1/3) - 1
        r = self.c.analyze([0.2, 0.0, -0.2])
        expected = (1.2 * 1.0 * 0.8) ** (1.0 / 3.0) - 1.0
        self.assertAlmostEqual(r.geometric_mean_return, round(expected, 6), places=6)

    def test_best_period(self):
        r = self.c.analyze([0.02, 0.05, -0.01])
        self.assertEqual(r.best_period_return, 0.05)

    def test_worst_period(self):
        r = self.c.analyze([0.02, 0.05, -0.01])
        self.assertEqual(r.worst_period_return, -0.01)

    def test_best_equals_worst_single(self):
        r = self.c.analyze([0.03])
        self.assertEqual(r.best_period_return, 0.03)
        self.assertEqual(r.worst_period_return, 0.03)

    def test_positive_ratio_all(self):
        r = self.c.analyze([0.01, 0.02, 0.03])
        self.assertEqual(r.positive_period_ratio, 1.0)

    def test_positive_ratio_none(self):
        r = self.c.analyze([-0.01, -0.02])
        self.assertEqual(r.positive_period_ratio, 0.0)

    def test_positive_ratio_half(self):
        r = self.c.analyze([0.01, -0.01, 0.02, -0.02])
        self.assertEqual(r.positive_period_ratio, 0.5)

    def test_zero_return_not_positive(self):
        r = self.c.analyze([0.0, 0.0])
        self.assertEqual(r.positive_period_ratio, 0.0)

    def test_num_periods(self):
        r = self.c.analyze([0.01, 0.02, 0.03, 0.04])
        self.assertEqual(r.num_periods, 4)

    def test_all_flat_zero_cumulative(self):
        r = self.c.analyze([0.0, 0.0, 0.0])
        self.assertEqual(r.cumulative_twr, 0.0)
        self.assertEqual(r.geometric_mean_return, 0.0)


class TestTotalLoss(unittest.TestCase):
    def setUp(self):
        self.c = TimeWeightedReturnCalculator()

    def test_total_loss_minus_one_return(self):
        r = self.c.analyze([0.1, -1.0, 0.2])
        self.assertEqual(r.cumulative_twr, -1.0)

    def test_total_loss_geometric(self):
        r = self.c.analyze([0.1, -1.0])
        self.assertEqual(r.geometric_mean_return, -1.0)

    def test_total_loss_annualized(self):
        r = self.c.analyze([0.1, -1.0], periods_per_year=12)
        self.assertEqual(r.annualized_twr, -1.0)

    def test_total_loss_advisory(self):
        r = self.c.analyze([-1.0])
        self.assertTrue(any("Total loss" in a for a in r.advisory))

    def test_total_loss_below_minus_one(self):
        # growth = 1 + (-1.5) = -0.5 <= 0 triggers total loss
        r = self.c.analyze([-1.5])
        self.assertEqual(r.cumulative_twr, -1.0)

    def test_total_loss_tier_negative(self):
        r = self.c.analyze([0.1, -1.0])
        self.assertEqual(r.performance_tier, "NEGATIVE")

    def test_exact_minus_one_is_total_loss(self):
        # 1 + (-1.0) = 0.0 which is <= 0 => total loss
        r = self.c.analyze([-1.0, 0.5])
        self.assertEqual(r.cumulative_twr, -1.0)

    def test_no_total_loss_normal(self):
        r = self.c.analyze([0.1, -0.5])
        self.assertNotEqual(r.cumulative_twr, -1.0)
        self.assertFalse(any("Total loss" in a for a in r.advisory))


class TestAnnualization(unittest.TestCase):
    def setUp(self):
        self.c = TimeWeightedReturnCalculator()

    def test_annualized_ppy_one_equals_cumulative(self):
        # ppy=1, n=1 => annualized = factor**(1/1)-1 = cumulative
        r = self.c.analyze([0.05], periods_per_year=1)
        self.assertAlmostEqual(r.annualized_twr, r.cumulative_twr, places=6)

    def test_annualized_full_year(self):
        # 12 monthly periods, ppy=12, n=12 => annualized = factor - 1 = cumulative
        rets = [0.01] * 12
        r = self.c.analyze(rets, periods_per_year=12)
        self.assertAlmostEqual(r.annualized_twr, r.cumulative_twr, places=6)

    def test_annualized_extrapolates(self):
        # 6 monthly periods, ppy=12 => annualized > cumulative for positive returns
        rets = [0.01] * 6
        r = self.c.analyze(rets, periods_per_year=12)
        self.assertGreater(r.annualized_twr, r.cumulative_twr)

    def test_annualized_known(self):
        # factor = 1.1, n=1, ppy=12 => 1.1**12 - 1
        r = self.c.analyze([0.1], periods_per_year=12)
        expected = (1.1 ** 12) - 1.0
        self.assertAlmostEqual(r.annualized_twr, round(expected, 6), places=6)

    def test_tier_uses_annualized(self):
        # small per-period return but high ppy lifts annualized into STRONG
        r = self.c.analyze([0.01, 0.011, 0.009], periods_per_year=365)
        self.assertEqual(r.performance_tier, "STRONG")

    def test_ppy_recorded(self):
        r = self.c.analyze([0.01, 0.02], periods_per_year=52)
        self.assertEqual(r.periods_per_year, 52)


class TestTiers(unittest.TestCase):
    def setUp(self):
        self.c = TimeWeightedReturnCalculator()

    def test_strong_scenario(self):
        # annualized = geometric mean per period (ppy==n==3) ~ 0.15 >= 0.10
        r = self.c.analyze([0.15, 0.16, 0.14], periods_per_year=3)
        self.assertEqual(r.performance_tier, "STRONG")

    def test_negative_scenario(self):
        r = self.c.analyze([-0.05, -0.03], periods_per_year=1)
        self.assertEqual(r.performance_tier, "NEGATIVE")

    def test_flat_scenario(self):
        r = self.c.analyze([0.005, -0.004], periods_per_year=1)
        self.assertEqual(r.performance_tier, "FLAT")

    def test_tier_in_known_set(self):
        r = self.c.analyze([0.01, 0.02, 0.03])
        self.assertIn(
            r.performance_tier,
            {"STRONG", "MODERATE", "FLAT", "NEGATIVE", "UNKNOWN"},
        )

    def test_advisory_present(self):
        r = self.c.analyze([0.01, 0.02])
        self.assertGreaterEqual(len(r.advisory), 1)

    def test_weak_consistency_advisory(self):
        # mostly negative periods but no total loss
        r = self.c.analyze([0.2, -0.01, -0.02, -0.03])
        self.assertTrue(any("consistency is weak" in a for a in r.advisory))


class TestSubreturnsFromNavs(unittest.TestCase):
    def setUp(self):
        self.c = TimeWeightedReturnCalculator()

    def test_empty(self):
        self.assertEqual(self.c.subreturns_from_navs([]), [])

    def test_single_point(self):
        self.assertEqual(self.c.subreturns_from_navs([100.0]), [])

    def test_two_points_no_flow(self):
        # (110 - 0)/100 - 1 = 0.1
        out = self.c.subreturns_from_navs([100.0, 110.0])
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0], 0.1, places=9)

    def test_three_points_no_flow(self):
        out = self.c.subreturns_from_navs([100.0, 110.0, 121.0])
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(out[0], 0.1, places=9)
        self.assertAlmostEqual(out[1], 0.1, places=9)

    def test_with_flow_strips_deposit(self):
        # end-of-period deposit of 10: (110 - 10)/100 - 1 = 0.0
        out = self.c.subreturns_from_navs([100.0, 110.0], flows=[10.0])
        self.assertAlmostEqual(out[0], 0.0, places=9)

    def test_with_flow_withdrawal(self):
        # withdrawal of 10 (negative flow): (90 - (-10))/100 - 1 = 0.0
        out = self.c.subreturns_from_navs([100.0, 90.0], flows=[-10.0])
        self.assertAlmostEqual(out[0], 0.0, places=9)

    def test_flows_default_zero(self):
        out_a = self.c.subreturns_from_navs([100.0, 105.0, 102.0])
        out_b = self.c.subreturns_from_navs([100.0, 105.0, 102.0], flows=[0.0, 0.0])
        self.assertEqual(out_a, out_b)

    def test_non_positive_opening_returns_zero(self):
        # opening NAV 0 => that period returns 0.0
        out = self.c.subreturns_from_navs([0.0, 50.0])
        self.assertEqual(out[0], 0.0)

    def test_negative_opening_returns_zero(self):
        out = self.c.subreturns_from_navs([-10.0, 50.0])
        self.assertEqual(out[0], 0.0)

    def test_chains_into_analyze(self):
        navs = [100.0, 102.0, 101.0, 104.0]
        subs = self.c.subreturns_from_navs(navs)
        r = self.c.analyze(subs)
        self.assertEqual(r.num_periods, 3)

    def test_short_flows_list_pads_zero(self):
        # flows shorter than n_periods: missing flows treated as 0.0
        out = self.c.subreturns_from_navs([100.0, 110.0, 121.0], flows=[0.0])
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(out[1], 0.1, places=9)


class TestRounding(unittest.TestCase):
    def setUp(self):
        self.c = TimeWeightedReturnCalculator()

    def test_all_fields_6dp(self):
        r = self.c.analyze([0.013, 0.027, 0.011])
        for v in (
            r.cumulative_twr,
            r.annualized_twr,
            r.geometric_mean_return,
            r.best_period_return,
            r.worst_period_return,
            r.positive_period_ratio,
        ):
            self.assertEqual(v, round(v, 6))

    def test_generated_at_set(self):
        r = self.c.analyze([0.01, 0.02])
        self.assertTrue(r.generated_at.endswith("Z"))


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.c = TimeWeightedReturnCalculator()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "twr.json"

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
        self.assertIn("cumulative_twr", e)
        self.assertIn("annualized_twr", e)
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
        nested = Path(self.tmp.name) / "x" / "y" / "twr.json"
        self.c.save_report(self.c.analyze([0.01, 0.02]), nested)
        self.assertTrue(nested.exists())

    def test_ring_buffer_keeps_latest(self):
        for i in range(MAX_ENTRIES + 3):
            r = self.c.analyze([0.01 * (i + 1), 0.02])
            self.c.save_report(r, self.path)
        hist = self.c.load_history(self.path)
        self.assertEqual(len(hist), MAX_ENTRIES)
        # last entry should reflect the most recent save
        self.assertEqual(hist[-1]["num_periods"], 2)


class TestFullScenario(unittest.TestCase):
    def setUp(self):
        self.c = TimeWeightedReturnCalculator()

    def test_realistic_monthly(self):
        rets = [0.02, -0.01, 0.015, 0.008, -0.005, 0.012]
        r = self.c.analyze(rets, periods_per_year=12)
        self.assertEqual(r.num_periods, 6)
        self.assertIn(
            r.performance_tier, {"STRONG", "MODERATE", "FLAT", "NEGATIVE"}
        )
        self.assertGreaterEqual(len(r.advisory), 1)

    def test_navs_pipeline_full(self):
        navs = [100.0, 102.0, 100.98, 102.5, 101.99, 103.21]
        subs = self.c.subreturns_from_navs(navs)
        r = self.c.analyze(subs, periods_per_year=12)
        self.assertEqual(r.num_periods, 5)


if __name__ == "__main__":
    unittest.main()
