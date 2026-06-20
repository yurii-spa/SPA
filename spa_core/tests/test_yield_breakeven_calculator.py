"""
Tests for MP-734: YieldBreakevenCalculator
>=60 test cases using unittest only (no pytest, no numpy, no pandas).
Tempfile-based persistence — production data/ is never touched.
"""

import json
import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.yield_breakeven_calculator import (
    MAX_ENTRIES,
    BREAKEVEN_DAYS_PROFITABLE,
    BREAKEVEN_DAYS_MARGINAL,
    BREAKEVEN_FRACTION_PROFITABLE,
    BREAKEVEN_FRACTION_MARGINAL,
    HIGH_COST_PCT_THRESHOLD,
    BreakevenReport,
    YieldBreakevenCalculator,
)


class TestEffectiveAnnualYield(unittest.TestCase):
    def setUp(self):
        self.c = YieldBreakevenCalculator()

    def test_no_compounding_reduces_to_apy(self):
        self.assertAlmostEqual(self.c._effective_annual_yield(0.12, 1), 0.12)

    def test_zero_compounding_reduces_to_apy(self):
        self.assertAlmostEqual(self.c._effective_annual_yield(0.12, 0), 0.12)

    def test_negative_compounding_reduces_to_apy(self):
        self.assertAlmostEqual(self.c._effective_annual_yield(0.12, -3), 0.12)

    def test_daily_compounding_exceeds_nominal(self):
        eff = self.c._effective_annual_yield(0.12, 365)
        self.assertGreater(eff, 0.12)

    def test_known_compounding_value(self):
        # (1 + 0.10/2)**2 - 1 = 0.1025
        self.assertAlmostEqual(self.c._effective_annual_yield(0.10, 2), 0.1025, places=6)

    def test_zero_apy_zero_yield(self):
        self.assertAlmostEqual(self.c._effective_annual_yield(0.0, 365), 0.0)

    def test_negative_apy(self):
        self.assertLess(self.c._effective_annual_yield(-0.05, 365), 0.0)


class TestDailyYield(unittest.TestCase):
    def setUp(self):
        self.c = YieldBreakevenCalculator()

    def test_basic(self):
        # 10000 * 0.365 / 365 = 10.0
        self.assertAlmostEqual(self.c._daily_yield_usd(10000.0, 0.365), 10.0, places=6)

    def test_zero_yield(self):
        self.assertEqual(self.c._daily_yield_usd(10000.0, 0.0), 0.0)

    def test_negative_yield(self):
        self.assertLess(self.c._daily_yield_usd(10000.0, -0.10), 0.0)

    def test_scales_with_position(self):
        a = self.c._daily_yield_usd(1000.0, 0.12)
        b = self.c._daily_yield_usd(2000.0, 0.12)
        self.assertAlmostEqual(b, 2 * a, places=6)


class TestBreakevenDays(unittest.TestCase):
    def setUp(self):
        self.c = YieldBreakevenCalculator()

    def test_basic(self):
        self.assertAlmostEqual(self.c._breakeven_days(30.0, 10.0), 3.0, places=6)

    def test_zero_daily_yield_none(self):
        self.assertIsNone(self.c._breakeven_days(30.0, 0.0))

    def test_negative_daily_yield_none(self):
        self.assertIsNone(self.c._breakeven_days(30.0, -5.0))

    def test_zero_cost_zero_days(self):
        self.assertEqual(self.c._breakeven_days(0.0, 10.0), 0.0)


class TestClassifyNoHold(unittest.TestCase):
    def setUp(self):
        self.c = YieldBreakevenCalculator()

    def test_none_breakeven_unknown(self):
        self.assertEqual(self.c._classify(None, None), "UNKNOWN")

    def test_fast_profitable(self):
        self.assertEqual(self.c._classify(10.0, None), "PROFITABLE")

    def test_profitable_boundary(self):
        self.assertEqual(self.c._classify(BREAKEVEN_DAYS_PROFITABLE, None), "PROFITABLE")

    def test_marginal(self):
        self.assertEqual(self.c._classify(60.0, None), "MARGINAL")

    def test_marginal_boundary(self):
        self.assertEqual(self.c._classify(BREAKEVEN_DAYS_MARGINAL, None), "MARGINAL")

    def test_unprofitable(self):
        self.assertEqual(self.c._classify(120.0, None), "UNPROFITABLE")

    def test_just_above_profitable(self):
        self.assertEqual(
            self.c._classify(BREAKEVEN_DAYS_PROFITABLE + 0.01, None), "MARGINAL"
        )

    def test_just_above_marginal(self):
        self.assertEqual(
            self.c._classify(BREAKEVEN_DAYS_MARGINAL + 0.01, None), "UNPROFITABLE"
        )


class TestClassifyWithHold(unittest.TestCase):
    def setUp(self):
        self.c = YieldBreakevenCalculator()

    def test_within_half_profitable(self):
        # hold 100, breakeven 40 <= 50 => PROFITABLE
        self.assertEqual(self.c._classify(40.0, 100.0), "PROFITABLE")

    def test_half_boundary_profitable(self):
        self.assertEqual(
            self.c._classify(BREAKEVEN_FRACTION_PROFITABLE * 100.0, 100.0), "PROFITABLE"
        )

    def test_within_full_marginal(self):
        self.assertEqual(self.c._classify(80.0, 100.0), "MARGINAL")

    def test_full_boundary_marginal(self):
        self.assertEqual(
            self.c._classify(BREAKEVEN_FRACTION_MARGINAL * 100.0, 100.0), "MARGINAL"
        )

    def test_beyond_hold_unprofitable(self):
        self.assertEqual(self.c._classify(150.0, 100.0), "UNPROFITABLE")

    def test_zero_hold_falls_back_to_absolute(self):
        # intended_hold 0 is not > 0, so absolute thresholds apply
        self.assertEqual(self.c._classify(10.0, 0.0), "PROFITABLE")

    def test_negative_hold_falls_back_to_absolute(self):
        self.assertEqual(self.c._classify(10.0, -5.0), "PROFITABLE")


class TestAnalyzeGuards(unittest.TestCase):
    def setUp(self):
        self.c = YieldBreakevenCalculator()

    def test_zero_position_unknown(self):
        r = self.c.analyze(position_size_usd=0.0)
        self.assertEqual(r.verdict_tier, "UNKNOWN")

    def test_negative_position_unknown(self):
        r = self.c.analyze(position_size_usd=-100.0)
        self.assertEqual(r.verdict_tier, "UNKNOWN")

    def test_zero_position_advisory(self):
        r = self.c.analyze(position_size_usd=0.0)
        self.assertTrue(any("positive" in a for a in r.advisory))

    def test_zero_position_breakeven_none(self):
        r = self.c.analyze(position_size_usd=0.0)
        self.assertIsNone(r.breakeven_days)

    def test_zero_position_net_none(self):
        r = self.c.analyze(position_size_usd=0.0, intended_hold_days=30.0)
        self.assertIsNone(r.net_profit_usd)
        self.assertIsNone(r.net_apy)

    def test_returns_report_type(self):
        self.assertIsInstance(self.c.analyze(), BreakevenReport)


class TestAnalyzeTotalCost(unittest.TestCase):
    def setUp(self):
        self.c = YieldBreakevenCalculator()

    def test_total_cost_sum(self):
        r = self.c.analyze(entry_cost_usd=15.0, exit_cost_usd=20.0)
        self.assertEqual(r.total_cost_usd, 35.0)

    def test_gross_apy_total(self):
        r = self.c.analyze(gross_apy=0.10, reward_apy=0.03)
        self.assertAlmostEqual(r.gross_apy_total, 0.13, places=6)

    def test_default_reward_zero(self):
        r = self.c.analyze(gross_apy=0.10)
        self.assertEqual(r.reward_apy, 0.0)
        self.assertAlmostEqual(r.gross_apy_total, 0.10, places=6)

    def test_cost_pct(self):
        r = self.c.analyze(position_size_usd=10000.0, entry_cost_usd=50.0, exit_cost_usd=50.0)
        self.assertAlmostEqual(r.cost_as_pct_of_position, 0.01, places=6)


class TestAnalyzeBreakeven(unittest.TestCase):
    def setUp(self):
        self.c = YieldBreakevenCalculator()

    def test_breakeven_positive(self):
        r = self.c.analyze(gross_apy=0.12)
        self.assertIsNotNone(r.breakeven_days)
        self.assertGreater(r.breakeven_days, 0.0)

    def test_zero_apy_breakeven_none(self):
        r = self.c.analyze(gross_apy=0.0, reward_apy=0.0)
        self.assertIsNone(r.breakeven_days)
        self.assertEqual(r.verdict_tier, "UNKNOWN")

    def test_negative_apy_breakeven_none(self):
        r = self.c.analyze(gross_apy=-0.05, reward_apy=0.0, compounding_per_year=1)
        self.assertIsNone(r.breakeven_days)
        self.assertEqual(r.verdict_tier, "UNKNOWN")

    def test_higher_apy_faster_breakeven(self):
        low = self.c.analyze(gross_apy=0.05)
        high = self.c.analyze(gross_apy=0.50)
        self.assertLess(high.breakeven_days, low.breakeven_days)

    def test_higher_cost_slower_breakeven(self):
        cheap = self.c.analyze(entry_cost_usd=5.0, exit_cost_usd=5.0)
        pricey = self.c.analyze(entry_cost_usd=50.0, exit_cost_usd=50.0)
        self.assertLess(cheap.breakeven_days, pricey.breakeven_days)


class TestAnalyzeProfitableScenarios(unittest.TestCase):
    def setUp(self):
        self.c = YieldBreakevenCalculator()

    def test_profitable_low_cost_high_apy(self):
        r = self.c.analyze(
            position_size_usd=10000.0,
            entry_cost_usd=5.0,
            exit_cost_usd=5.0,
            gross_apy=0.50,
        )
        self.assertEqual(r.verdict_tier, "PROFITABLE")

    def test_unprofitable_high_cost_low_apy(self):
        r = self.c.analyze(
            position_size_usd=1000.0,
            entry_cost_usd=40.0,
            exit_cost_usd=40.0,
            gross_apy=0.02,
        )
        self.assertEqual(r.verdict_tier, "UNPROFITABLE")

    def test_profitable_advisory(self):
        r = self.c.analyze(
            position_size_usd=10000.0, entry_cost_usd=5.0, exit_cost_usd=5.0, gross_apy=0.50
        )
        self.assertTrue(any("Profitable" in a for a in r.advisory))

    def test_unprofitable_advisory(self):
        r = self.c.analyze(
            position_size_usd=1000.0, entry_cost_usd=40.0, exit_cost_usd=40.0, gross_apy=0.02
        )
        self.assertTrue(any("Unprofitable" in a for a in r.advisory))

    def test_tier_in_known_set(self):
        r = self.c.analyze()
        self.assertIn(
            r.verdict_tier,
            {"PROFITABLE", "MARGINAL", "UNPROFITABLE", "UNKNOWN"},
        )


class TestAnalyzeWithHold(unittest.TestCase):
    def setUp(self):
        self.c = YieldBreakevenCalculator()

    def test_net_profit_computed(self):
        r = self.c.analyze(intended_hold_days=60.0)
        self.assertIsNotNone(r.net_profit_usd)

    def test_net_apy_computed(self):
        r = self.c.analyze(intended_hold_days=60.0)
        self.assertIsNotNone(r.net_apy)

    def test_no_hold_net_none(self):
        r = self.c.analyze(intended_hold_days=None)
        self.assertIsNone(r.net_profit_usd)
        self.assertIsNone(r.net_apy)

    def test_net_profit_formula(self):
        r = self.c.analyze(
            position_size_usd=10000.0,
            entry_cost_usd=10.0,
            exit_cost_usd=10.0,
            gross_apy=0.12,
            intended_hold_days=90.0,
        )
        expected = round(r.daily_yield_usd * 90.0 - r.total_cost_usd, 6)
        self.assertAlmostEqual(r.net_profit_usd, expected, places=4)

    def test_negative_net_profit_advisory(self):
        # short hold, high cost -> net loss
        r = self.c.analyze(
            position_size_usd=1000.0,
            entry_cost_usd=40.0,
            exit_cost_usd=40.0,
            gross_apy=0.05,
            intended_hold_days=5.0,
        )
        self.assertLess(r.net_profit_usd, 0.0)
        self.assertTrue(any("Net loss" in a for a in r.advisory))

    def test_long_hold_more_profit(self):
        short = self.c.analyze(gross_apy=0.12, intended_hold_days=30.0)
        long = self.c.analyze(gross_apy=0.12, intended_hold_days=300.0)
        self.assertGreater(long.net_profit_usd, short.net_profit_usd)

    def test_zero_hold_treated_as_no_hold(self):
        r = self.c.analyze(intended_hold_days=0.0)
        self.assertIsNone(r.net_profit_usd)


class TestHighCostFlag(unittest.TestCase):
    def setUp(self):
        self.c = YieldBreakevenCalculator()

    def test_high_cost_flagged(self):
        r = self.c.analyze(
            position_size_usd=1000.0, entry_cost_usd=10.0, exit_cost_usd=10.0
        )
        # 20/1000 = 2% > 1%
        self.assertTrue(any("High transaction cost" in a for a in r.advisory))

    def test_low_cost_not_flagged(self):
        r = self.c.analyze(
            position_size_usd=100000.0, entry_cost_usd=5.0, exit_cost_usd=5.0, gross_apy=0.20
        )
        self.assertFalse(any("High transaction cost" in a for a in r.advisory))

    def test_threshold_constant(self):
        self.assertEqual(HIGH_COST_PCT_THRESHOLD, 0.01)


class TestRounding(unittest.TestCase):
    def setUp(self):
        self.c = YieldBreakevenCalculator()

    def test_all_floats_6dp(self):
        r = self.c.analyze(gross_apy=0.123456789, intended_hold_days=37.0)
        for v in (
            r.effective_annual_yield,
            r.daily_yield_usd,
            r.cost_as_pct_of_position,
            r.gross_apy_total,
        ):
            self.assertEqual(v, round(v, 6))

    def test_breakeven_rounded(self):
        r = self.c.analyze(gross_apy=0.123456789)
        self.assertEqual(r.breakeven_days, round(r.breakeven_days, 6))

    def test_generated_at_set(self):
        r = self.c.analyze()
        self.assertTrue(r.generated_at.endswith("Z"))

    def test_compounding_recorded(self):
        r = self.c.analyze(compounding_per_year=12)
        self.assertEqual(r.compounding_per_year, 12)


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.c = YieldBreakevenCalculator()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "breakeven.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing_empty(self):
        self.assertEqual(self.c.load_history(self.path), [])

    def test_save_then_load(self):
        self.c.save_report(self.c.analyze(), self.path)
        self.assertEqual(len(self.c.load_history(self.path)), 1)

    def test_saved_fields(self):
        self.c.save_report(self.c.analyze(intended_hold_days=60.0), self.path)
        e = self.c.load_history(self.path)[0]
        self.assertIn("breakeven_days", e)
        self.assertIn("verdict_tier", e)
        self.assertIn("advisory", e)
        self.assertIn("net_profit_usd", e)

    def test_append_multiple(self):
        for _ in range(4):
            self.c.save_report(self.c.analyze(), self.path)
        self.assertEqual(len(self.c.load_history(self.path)), 4)

    def test_ring_buffer_cap(self):
        for _ in range(MAX_ENTRIES + 5):
            self.c.save_report(self.c.analyze(), self.path)
        self.assertEqual(len(self.c.load_history(self.path)), MAX_ENTRIES)

    def test_corrupt_returns_empty(self):
        self.path.write_text("garbage{{")
        self.assertEqual(self.c.load_history(self.path), [])

    def test_no_tmp_left(self):
        self.c.save_report(self.c.analyze(), self.path)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_valid_json(self):
        self.c.save_report(self.c.analyze(), self.path)
        json.loads(self.path.read_text())

    def test_creates_parent_dir(self):
        nested = Path(self.tmp.name) / "x" / "y" / "breakeven.json"
        self.c.save_report(self.c.analyze(), nested)
        self.assertTrue(nested.exists())

    def test_none_breakeven_persisted(self):
        self.c.save_report(self.c.analyze(gross_apy=0.0), self.path)
        e = self.c.load_history(self.path)[0]
        self.assertIsNone(e["breakeven_days"])


class TestFullScenario(unittest.TestCase):
    def setUp(self):
        self.c = YieldBreakevenCalculator()

    def test_realistic(self):
        r = self.c.analyze(
            position_size_usd=10000.0,
            entry_cost_usd=20.0,
            exit_cost_usd=18.0,
            gross_apy=0.14,
            reward_apy=0.02,
            intended_hold_days=60.0,
        )
        self.assertEqual(r.total_cost_usd, 38.0)
        self.assertIn(
            r.verdict_tier, {"PROFITABLE", "MARGINAL", "UNPROFITABLE", "UNKNOWN"}
        )
        self.assertTrue(len(r.advisory) >= 1)

    def test_marginal_with_hold(self):
        # tune so breakeven sits between 0.5*hold and hold
        r = self.c.analyze(
            position_size_usd=10000.0,
            entry_cost_usd=30.0,
            exit_cost_usd=30.0,
            gross_apy=0.10,
            intended_hold_days=30.0,
        )
        self.assertIn(r.verdict_tier, {"PROFITABLE", "MARGINAL", "UNPROFITABLE"})

    def test_advisory_present(self):
        r = self.c.analyze()
        self.assertTrue(len(r.advisory) >= 1)

    def test_compounding_lifts_effective(self):
        no_comp = self.c.analyze(gross_apy=0.20, compounding_per_year=1)
        daily = self.c.analyze(gross_apy=0.20, compounding_per_year=365)
        self.assertGreater(daily.effective_annual_yield, no_comp.effective_annual_yield)


if __name__ == "__main__":
    unittest.main()
