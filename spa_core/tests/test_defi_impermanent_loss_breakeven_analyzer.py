"""
MP-993 Tests: DeFiImpermanentLossBreakevenAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_impermanent_loss_breakeven_analyzer -v
"""

import json
import math
import os
import tempfile
import unittest

from spa_core.analytics.defi_impermanent_loss_breakeven_analyzer import (
    DeFiImpermanentLossBreakevenAnalyzer,
)


def make_pos(**kwargs):
    defaults = {
        "name": "ETH-USDC",
        "protocol": "Uniswap",
        "pair": "ETH/USDC",
        "fee_apr_pct": 20.0,
        "reward_apr_pct": 0.0,
        "expected_price_divergence_pct": 50.0,
        "horizon_days": 365.0,
        "position_size_usd": 100_000.0,
    }
    defaults.update(kwargs)
    return defaults


class TestBasicShape(unittest.TestCase):
    def setUp(self):
        self.az = DeFiImpermanentLossBreakevenAnalyzer()

    def test_returns_expected_keys(self):
        r = self.az.analyze([make_pos()])
        self.assertEqual(r["position_count"], 1)
        p = r["positions"][0]
        for k in (
            "total_apr_pct", "expected_divergence_pct", "il_pct", "fee_income_pct",
            "net_pnl_pct", "breakeven_days", "breakeven_divergence_pct",
            "required_fee_apr_pct", "il_usd", "fee_income_usd", "net_pnl_usd",
            "lp_score", "grade", "classification", "flags",
        ):
            self.assertIn(k, p)

    def test_empty_input(self):
        r = self.az.analyze([])
        self.assertEqual(r["position_count"], 0)
        self.assertIsNone(r["aggregates"]["average_net_pnl_pct"])


class TestILMath(unittest.TestCase):
    def setUp(self):
        self.az = DeFiImpermanentLossBreakevenAnalyzer()

    def test_il_fraction_zero_at_no_divergence(self):
        self.assertAlmostEqual(self.az._il_fraction(1.0), 0.0, places=10)

    def test_il_fraction_known_value_2x(self):
        # r=2 -> 1 - 2*sqrt(2)/3 = 0.0572809...
        self.assertAlmostEqual(self.az._il_fraction(2.0), 0.05719095841794, places=8)

    def test_il_symmetric(self):
        self.assertAlmostEqual(
            self.az._il_fraction(4.0), self.az._il_fraction(0.25), places=10
        )

    def test_il_pct_for_50pct_divergence(self):
        # r=1.5 -> IL = 1 - 2*sqrt(1.5)/2.5 = 0.0203044...
        p = self.az.analyze([make_pos()])["positions"][0]
        expected = (1.0 - 2.0 * math.sqrt(1.5) / 2.5) * 100.0
        self.assertAlmostEqual(p["il_pct"], round(expected, 4), places=4)

    def test_divergence_uses_absolute_value(self):
        pos = self.az.analyze([make_pos(expected_price_divergence_pct=-50.0)])["positions"][0]
        neg = self.az.analyze([make_pos(expected_price_divergence_pct=50.0)])["positions"][0]
        self.assertAlmostEqual(pos["il_pct"], neg["il_pct"], places=8)


class TestBreakeven(unittest.TestCase):
    def setUp(self):
        self.az = DeFiImpermanentLossBreakevenAnalyzer()

    def test_net_pnl_is_fee_minus_il(self):
        p = self.az.analyze([make_pos()])["positions"][0]
        self.assertAlmostEqual(
            p["net_pnl_pct"], p["fee_income_pct"] - p["il_pct"], places=4
        )

    def test_fee_income_over_horizon(self):
        # 20% apr * 0.5 yr = 10%
        p = self.az.analyze([make_pos(horizon_days=182.5)])["positions"][0]
        self.assertAlmostEqual(p["fee_income_pct"], 10.0, places=2)

    def test_breakeven_days_roundtrip(self):
        # IL at 50% div ~2.03%, fee apr 20% -> days = 2.03/20*365 ~ 37
        p = self.az.analyze([make_pos()])["positions"][0]
        self.assertAlmostEqual(p["breakeven_days"], p["il_pct"] / 20.0 * 365.0, places=2)

    def test_breakeven_divergence_il_matches_fee_income(self):
        # at the break-even divergence, IL fraction should equal fee_income fraction
        p = self.az.analyze([make_pos(fee_apr_pct=5.0, horizon_days=365.0)])["positions"][0]
        bd = p["breakeven_divergence_pct"]
        self.assertIsNotNone(bd)
        r = 1.0 + bd / 100.0
        self.assertAlmostEqual(
            self.az._il_fraction(r) * 100.0, p["fee_income_pct"], places=2
        )

    def test_required_fee_apr(self):
        # required apr to offset IL over horizon = il_pct / horizon_years
        p = self.az.analyze([make_pos(horizon_days=365.0)])["positions"][0]
        self.assertAlmostEqual(p["required_fee_apr_pct"], p["il_pct"], places=4)

    def test_high_fees_low_divergence_profitable(self):
        p = self.az.analyze([make_pos(fee_apr_pct=30.0,
                                      expected_price_divergence_pct=10.0)])["positions"][0]
        self.assertGreater(p["net_pnl_pct"], 0.0)
        self.assertIn(p["classification"], ("PROFITABLE", "STRONGLY_PROFITABLE"))
        self.assertIn("FEES_COVER_IL", p["flags"])

    def test_low_fees_high_divergence_il_dominated(self):
        p = self.az.analyze([make_pos(fee_apr_pct=1.0, reward_apr_pct=0.0,
                                      expected_price_divergence_pct=300.0,
                                      horizon_days=30.0)])["positions"][0]
        self.assertLess(p["net_pnl_pct"], 0.0)
        self.assertIn("IL_EXCEEDS_FEES", p["flags"])
        self.assertEqual(p["classification"], "IL_DOMINATED")


class TestGuards(unittest.TestCase):
    def setUp(self):
        self.az = DeFiImpermanentLossBreakevenAnalyzer()

    def test_zero_apr_no_breakeven_days(self):
        p = self.az.analyze([make_pos(fee_apr_pct=0.0, reward_apr_pct=0.0)])["positions"][0]
        self.assertIsNone(p["breakeven_days"])

    def test_zero_horizon_no_required_apr(self):
        p = self.az.analyze([make_pos(horizon_days=0.0)])["positions"][0]
        self.assertIsNone(p["required_fee_apr_pct"])

    def test_no_divergence_breakeven_divergence_positive(self):
        p = self.az.analyze([make_pos(expected_price_divergence_pct=0.0)])["positions"][0]
        self.assertEqual(p["il_pct"], 0.0)
        self.assertIsNotNone(p["breakeven_divergence_pct"])

    def test_extreme_fees_breakeven_divergence_none(self):
        # fee income >50% can't be matched by IL within MAX_R -> None
        p = self.az.analyze([make_pos(fee_apr_pct=200.0, horizon_days=365.0)])["positions"][0]
        self.assertIsNone(p["breakeven_divergence_pct"])

    def test_empty_position_insufficient(self):
        p = self.az.analyze([make_pos(fee_apr_pct=0.0, reward_apr_pct=0.0,
                                      position_size_usd=0.0,
                                      expected_price_divergence_pct=0.0)])["positions"][0]
        self.assertIn("INSUFFICIENT_DATA", p["flags"])


class TestScoreAndFlags(unittest.TestCase):
    def setUp(self):
        self.az = DeFiImpermanentLossBreakevenAnalyzer()

    def test_score_bounds(self):
        for div in (0.0, 25.0, 100.0, 500.0):
            p = self.az.analyze([make_pos(expected_price_divergence_pct=div)])["positions"][0]
            self.assertGreaterEqual(p["lp_score"], 0.0)
            self.assertLessEqual(p["lp_score"], 100.0)

    def test_coverage_2x_scores_100(self):
        # fee income double the IL -> score 100
        p = self.az.analyze([make_pos(fee_apr_pct=50.0,
                                      expected_price_divergence_pct=50.0)])["positions"][0]
        self.assertGreaterEqual(p["fee_income_pct"], 2.0 * p["il_pct"])
        self.assertEqual(p["lp_score"], 100.0)

    def test_stable_pair_flag(self):
        p = self.az.analyze([make_pos(expected_price_divergence_pct=2.0)])["positions"][0]
        self.assertIn("STABLE_PAIR", p["flags"])

    def test_high_divergence_flag(self):
        p = self.az.analyze([make_pos(expected_price_divergence_pct=80.0)])["positions"][0]
        self.assertIn("HIGH_DIVERGENCE", p["flags"])

    def test_thin_fees_flag(self):
        p = self.az.analyze([make_pos(fee_apr_pct=1.0)])["positions"][0]
        self.assertIn("THIN_FEES", p["flags"])

    def test_long_horizon_flag(self):
        p = self.az.analyze([make_pos(horizon_days=400.0)])["positions"][0]
        self.assertIn("LONG_HORIZON", p["flags"])

    def test_reward_apr_counts_toward_income(self):
        p = self.az.analyze([make_pos(fee_apr_pct=10.0, reward_apr_pct=10.0)])["positions"][0]
        self.assertAlmostEqual(p["total_apr_pct"], 20.0, places=4)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.az = DeFiImpermanentLossBreakevenAnalyzer()

    def test_best_worst_counts(self):
        r = self.az.analyze([
            make_pos(name="good", fee_apr_pct=40.0, expected_price_divergence_pct=10.0),
            make_pos(name="bad", fee_apr_pct=1.0, expected_price_divergence_pct=300.0,
                     horizon_days=30.0),
        ])
        agg = r["aggregates"]
        self.assertEqual(agg["best_position"]["name"], "good")
        self.assertEqual(agg["worst_position"]["name"], "bad")
        self.assertGreaterEqual(agg["profitable_count"], 1)
        self.assertGreaterEqual(agg["il_dominated_count"], 1)


class TestLogging(unittest.TestCase):
    def setUp(self):
        self.az = DeFiImpermanentLossBreakevenAnalyzer()

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.az.analyze([make_pos()], config={"write_log": True, "data_dir": d})
            path = os.path.join(d, "impermanent_loss_breakeven_log.json")
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                self.assertEqual(len(json.load(f)), 1)

    def test_ring_buffer_caps_at_100(self):
        with tempfile.TemporaryDirectory() as d:
            for _ in range(103):
                self.az.analyze([make_pos()], config={"write_log": True, "data_dir": d})
            with open(os.path.join(d, "impermanent_loss_breakeven_log.json")) as f:
                self.assertEqual(len(json.load(f)), 100)

    def test_corrupt_log_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "impermanent_loss_breakeven_log.json")
            with open(path, "w") as f:
                f.write("garbage")
            self.az.analyze([make_pos()], config={"write_log": True, "data_dir": d})
            with open(path) as f:
                self.assertEqual(len(json.load(f)), 1)


if __name__ == "__main__":
    unittest.main()
