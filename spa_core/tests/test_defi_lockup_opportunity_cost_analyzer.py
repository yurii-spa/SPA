"""
MP-967 Tests: DeFiLockupOpportunityCostAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_lockup_opportunity_cost_analyzer -v
"""

import json
import os
import unittest
import tempfile

from spa_core.analytics.defi_lockup_opportunity_cost_analyzer import (
    DeFiLockupOpportunityCostAnalyzer,
)


def make_pos(**kwargs):
    defaults = {
        "name": "PendlePT-USDC",
        "protocol": "Pendle",
        "locked_apy_pct": 9.0,
        "liquid_alternative_apy_pct": 4.0,
        "lock_days": 180.0,
        "early_exit_available": True,
        "early_exit_penalty_pct": 2.0,
        "expected_rate_volatility_pct": 2.0,
        "capital_usd": 100_000.0,
    }
    defaults.update(kwargs)
    return defaults


class TestBasicShape(unittest.TestCase):
    def setUp(self):
        self.az = DeFiLockupOpportunityCostAnalyzer()

    def test_returns_expected_keys(self):
        r = self.az.analyze([make_pos()])
        self.assertEqual(r["position_count"], 1)
        p = r["positions"][0]
        for k in (
            "nominal_spread_pct", "required_term_premium_pct", "excess_premium_pct",
            "breakeven_liquid_apy_pct", "opportunity_cost_usd", "lock_score",
            "grade", "classification", "flags", "illiquidity_charge_pct",
            "option_value_pct", "penalty_charge_pct", "early_exit_breakeven_days",
        ):
            self.assertIn(k, p)

    def test_empty_input(self):
        r = self.az.analyze([])
        self.assertEqual(r["position_count"], 0)
        self.assertIsNone(r["aggregates"]["best_opportunity"])

    def test_timestamp_present(self):
        self.assertIn("timestamp", self.az.analyze([make_pos()]))


class TestSpreadAndPremium(unittest.TestCase):
    def setUp(self):
        self.az = DeFiLockupOpportunityCostAnalyzer()

    def test_nominal_spread(self):
        r = self.az.analyze([make_pos(locked_apy_pct=9, liquid_alternative_apy_pct=4)])
        self.assertAlmostEqual(r["positions"][0]["nominal_spread_pct"], 5.0, places=3)

    def test_negative_spread_flag_and_class(self):
        r = self.az.analyze([make_pos(locked_apy_pct=3, liquid_alternative_apy_pct=5)])
        p = r["positions"][0]
        self.assertIn("NEGATIVE_SPREAD", p["flags"])
        self.assertEqual(p["classification"], "AVOID")

    def test_required_premium_rises_with_lock_days(self):
        short = self.az.analyze([make_pos(lock_days=30)])
        long = self.az.analyze([make_pos(lock_days=365)])
        self.assertGreater(
            long["positions"][0]["required_term_premium_pct"],
            short["positions"][0]["required_term_premium_pct"],
        )

    def test_required_premium_rises_with_volatility(self):
        lowv = self.az.analyze([make_pos(expected_rate_volatility_pct=1)])
        highv = self.az.analyze([make_pos(expected_rate_volatility_pct=10)])
        self.assertGreater(
            highv["positions"][0]["option_value_pct"],
            lowv["positions"][0]["option_value_pct"],
        )

    def test_excess_premium_is_spread_minus_hurdle(self):
        p = self.az.analyze([make_pos()])["positions"][0]
        self.assertAlmostEqual(
            p["excess_premium_pct"],
            p["nominal_spread_pct"] - p["required_term_premium_pct"],
            places=3,
        )

    def test_breakeven_liquid_apy(self):
        p = self.az.analyze([make_pos()])["positions"][0]
        self.assertAlmostEqual(
            p["breakeven_liquid_apy_pct"],
            p["locked_apy_pct"] - p["required_term_premium_pct"],
            places=3,
        )


class TestZeroAndGuards(unittest.TestCase):
    def setUp(self):
        self.az = DeFiLockupOpportunityCostAnalyzer()

    def test_zero_lock_days_no_charges(self):
        p = self.az.analyze([make_pos(lock_days=0)])["positions"][0]
        self.assertEqual(p["illiquidity_charge_pct"], 0.0)
        self.assertEqual(p["option_value_pct"], 0.0)
        self.assertEqual(p["opportunity_cost_usd"], 0.0)

    def test_insufficient_data_flag(self):
        p = self.az.analyze([make_pos(locked_apy_pct=0, liquid_alternative_apy_pct=0)])["positions"][0]
        self.assertIn("INSUFFICIENT_DATA", p["flags"])

    def test_negative_spread_no_breakeven_days(self):
        p = self.az.analyze([make_pos(locked_apy_pct=3, liquid_alternative_apy_pct=5)])["positions"][0]
        self.assertIsNone(p["early_exit_breakeven_days"])

    def test_breakeven_days_positive_when_advantage(self):
        p = self.az.analyze([make_pos(locked_apy_pct=10, liquid_alternative_apy_pct=4,
                                      early_exit_penalty_pct=2)])["positions"][0]
        self.assertIsNotNone(p["early_exit_breakeven_days"])
        self.assertGreater(p["early_exit_breakeven_days"], 0)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.az = DeFiLockupOpportunityCostAnalyzer()

    def test_long_lockup_flag(self):
        self.assertIn("LONG_LOCKUP", self.az.analyze([make_pos(lock_days=400)])["positions"][0]["flags"])

    def test_no_early_exit_flag(self):
        self.assertIn("NO_EARLY_EXIT", self.az.analyze([make_pos(early_exit_available=False)])["positions"][0]["flags"])

    def test_high_exit_penalty_flag(self):
        self.assertIn("HIGH_EXIT_PENALTY", self.az.analyze([make_pos(early_exit_penalty_pct=8)])["positions"][0]["flags"])

    def test_high_rate_volatility_flag(self):
        self.assertIn("HIGH_RATE_VOLATILITY", self.az.analyze([make_pos(expected_rate_volatility_pct=6)])["positions"][0]["flags"])

    def test_attractive_premium_flag(self):
        # Big spread, short lock, low vol → large excess premium
        p = self.az.analyze([make_pos(locked_apy_pct=15, liquid_alternative_apy_pct=4,
                                      lock_days=30, expected_rate_volatility_pct=1,
                                      early_exit_penalty_pct=0)])["positions"][0]
        self.assertIn("ATTRACTIVE_PREMIUM", p["flags"])


class TestClassificationAndScore(unittest.TestCase):
    def setUp(self):
        self.az = DeFiLockupOpportunityCostAnalyzer()

    def test_strongly_worth_locking(self):
        p = self.az.analyze([make_pos(locked_apy_pct=15, liquid_alternative_apy_pct=4,
                                      lock_days=30, expected_rate_volatility_pct=1,
                                      early_exit_penalty_pct=0)])["positions"][0]
        self.assertEqual(p["classification"], "STRONGLY_WORTH_LOCKING")
        self.assertGreaterEqual(p["lock_score"], 75.0)

    def test_not_worth_locking(self):
        p = self.az.analyze([make_pos(locked_apy_pct=4.2, liquid_alternative_apy_pct=4.0,
                                      lock_days=365, expected_rate_volatility_pct=8,
                                      early_exit_penalty_pct=10, early_exit_available=False)])["positions"][0]
        self.assertIn(p["classification"], ("NOT_WORTH_LOCKING", "MARGINAL"))

    def test_avoid_when_negative_spread(self):
        p = self.az.analyze([make_pos(locked_apy_pct=3, liquid_alternative_apy_pct=6)])["positions"][0]
        self.assertEqual(p["classification"], "AVOID")
        self.assertLessEqual(p["lock_score"], 25.0)

    def test_grade_monotonic(self):
        grades = [self.az._grade(s) for s in (95, 80, 65, 50, 10)]
        self.assertEqual(grades, ["A", "B", "C", "D", "F"])

    def test_score_in_range(self):
        p = self.az.analyze([make_pos()])["positions"][0]
        self.assertGreaterEqual(p["lock_score"], 0.0)
        self.assertLessEqual(p["lock_score"], 100.0)


class TestOpportunityCost(unittest.TestCase):
    def setUp(self):
        self.az = DeFiLockupOpportunityCostAnalyzer()

    def test_opportunity_cost_scales_with_capital(self):
        small = self.az.analyze([make_pos(capital_usd=10_000)])["positions"][0]
        big = self.az.analyze([make_pos(capital_usd=1_000_000)])["positions"][0]
        self.assertGreater(big["opportunity_cost_usd"], small["opportunity_cost_usd"])

    def test_opportunity_cost_non_negative(self):
        p = self.az.analyze([make_pos()])["positions"][0]
        self.assertGreaterEqual(p["opportunity_cost_usd"], 0.0)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.az = DeFiLockupOpportunityCostAnalyzer()

    def test_best_worst_identified(self):
        best = make_pos(name="BEST", locked_apy_pct=18, liquid_alternative_apy_pct=4,
                        lock_days=30, expected_rate_volatility_pct=1, early_exit_penalty_pct=0)
        worst = make_pos(name="WORST", locked_apy_pct=3, liquid_alternative_apy_pct=6)
        r = self.az.analyze([best, worst])
        self.assertEqual(r["aggregates"]["best_opportunity"]["name"], "BEST")
        self.assertEqual(r["aggregates"]["worst_opportunity"]["name"], "WORST")

    def test_worth_locking_count(self):
        good = make_pos(name="G", locked_apy_pct=15, liquid_alternative_apy_pct=4,
                        lock_days=30, expected_rate_volatility_pct=1, early_exit_penalty_pct=0)
        bad = make_pos(name="B", locked_apy_pct=3, liquid_alternative_apy_pct=6)
        r = self.az.analyze([good, bad])
        self.assertEqual(r["aggregates"]["worth_locking_count"], 1)
        self.assertEqual(r["aggregates"]["avoid_count"], 1)

    def test_average_excess_premium(self):
        r = self.az.analyze([make_pos(), make_pos(name="X", locked_apy_pct=12)])
        self.assertIsInstance(r["aggregates"]["average_excess_premium_pct"], float)


class TestLogging(unittest.TestCase):
    def setUp(self):
        self.az = DeFiLockupOpportunityCostAnalyzer()

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.az.analyze([make_pos()], {"write_log": True, "data_dir": d})
            path = os.path.join(d, "lockup_opportunity_cost_log.json")
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                self.assertEqual(len(json.load(f)), 1)

    def test_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            for _ in range(self.az.LOG_CAP + 5):
                self.az.analyze([make_pos()], {"write_log": True, "data_dir": d})
            with open(os.path.join(d, "lockup_opportunity_cost_log.json")) as f:
                self.assertEqual(len(json.load(f)), self.az.LOG_CAP)

    def test_no_log_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            self.az.analyze([make_pos()], {"data_dir": d})
            self.assertFalse(os.path.exists(os.path.join(d, "lockup_opportunity_cost_log.json")))


if __name__ == "__main__":
    unittest.main()
