"""
MP-1004 Tests: DeFiRewardTokenSellPressureAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_reward_token_sell_pressure_analyzer -v
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_reward_token_sell_pressure_analyzer import (
    DeFiRewardTokenSellPressureAnalyzer,
)


def make_pos(**kwargs):
    defaults = {
        "name": "FARM-A",
        "protocol": "YieldDex",
        "reward_token": "FARM",
        "daily_emissions_usd": 100_000.0,
        "organic_daily_buy_volume_usd": 500_000.0,
        "pool_liquidity_usd": 50_000_000.0,
        "advertised_apy_pct": 40.0,
        "sell_propensity_pct": 70.0,
    }
    defaults.update(kwargs)
    return defaults


class TestBasicShape(unittest.TestCase):
    def setUp(self):
        self.az = DeFiRewardTokenSellPressureAnalyzer()

    def test_returns_expected_keys(self):
        r = self.az.analyze([make_pos()])
        self.assertEqual(r["position_count"], 1)
        p = r["positions"][0]
        for k in (
            "name", "protocol", "reward_token", "daily_sell_usd",
            "sell_propensity_pct", "sell_pressure_ratio", "liquidity_turnover_pct",
            "estimated_daily_price_drag_pct", "annualized_price_drag_pct",
            "advertised_apy_pct", "realized_apy_pct", "sell_pressure_score",
            "grade", "classification", "flags",
        ):
            self.assertIn(k, p)

    def test_aggregate_keys(self):
        r = self.az.analyze([make_pos()])
        agg = r["aggregates"]
        for k in (
            "best_position", "worst_position", "average_sell_pressure_score",
            "high_pressure_count", "net_negative_apy_count",
        ):
            self.assertIn(k, agg)

    def test_timestamp_present(self):
        r = self.az.analyze([make_pos()])
        self.assertIn("timestamp", r)
        self.assertIsInstance(r["timestamp"], str)

    def test_empty_input(self):
        r = self.az.analyze([])
        self.assertEqual(r["position_count"], 0)
        self.assertIsNone(r["aggregates"]["average_sell_pressure_score"])
        self.assertIsNone(r["aggregates"]["best_position"])

    def test_position_count_multi(self):
        r = self.az.analyze([make_pos(), make_pos(name="B"), make_pos(name="C")])
        self.assertEqual(r["position_count"], 3)


class TestCoreMath(unittest.TestCase):
    def setUp(self):
        self.az = DeFiRewardTokenSellPressureAnalyzer()

    def test_daily_sell_usd(self):
        # 100k emissions * 70% propensity = 70k
        p = self.az.analyze([make_pos()])["positions"][0]
        self.assertAlmostEqual(p["daily_sell_usd"], 70_000.0, places=2)

    def test_sell_pressure_ratio(self):
        # 70k sells / 500k organic = 0.14
        p = self.az.analyze([make_pos()])["positions"][0]
        self.assertAlmostEqual(p["sell_pressure_ratio"], 0.14, places=4)

    def test_liquidity_turnover_pct(self):
        # 70k / 50,000,000 * 100 = 0.14
        p = self.az.analyze([make_pos()])["positions"][0]
        self.assertAlmostEqual(p["liquidity_turnover_pct"], 0.14, places=4)

    def test_daily_drag_known_value(self):
        # turnover 0.14 -> drag = 5.0 * 0.14/(0.14+10) = 5.0*0.0138067... = 0.069033...
        p = self.az.analyze([make_pos()])["positions"][0]
        expected = 5.0 * (0.14 / (0.14 + 10.0))
        self.assertAlmostEqual(p["estimated_daily_price_drag_pct"], round(expected, 4),
                               places=4)

    def test_annualized_drag_is_daily_times_365(self):
        p = self.az.analyze([make_pos()])["positions"][0]
        # annualized is the (unrounded) daily drag * 365
        daily = self.az._daily_price_drag_pct(p["liquidity_turnover_pct"])
        self.assertAlmostEqual(p["annualized_price_drag_pct"],
                               round(daily * 365.0, 4), places=2)

    def test_realized_apy_is_advertised_minus_drag(self):
        p = self.az.analyze([make_pos()])["positions"][0]
        self.assertAlmostEqual(
            p["realized_apy_pct"],
            p["advertised_apy_pct"] - p["annualized_price_drag_pct"], places=4
        )

    def test_drag_helper_monotonic_and_capped(self):
        d_low = self.az._daily_price_drag_pct(1.0)
        d_high = self.az._daily_price_drag_pct(100.0)
        self.assertLess(d_low, d_high)
        self.assertLessEqual(d_high, self.az.DRAG_CAP_PCT)

    def test_drag_half_at_half_turnover(self):
        # at turnover == DRAG_HALF_TURNOVER, drag == cap/2
        d = self.az._daily_price_drag_pct(self.az.DRAG_HALF_TURNOVER)
        self.assertAlmostEqual(d, self.az.DRAG_CAP_PCT / 2.0, places=8)

    def test_zero_turnover_zero_drag(self):
        self.assertAlmostEqual(self.az._daily_price_drag_pct(0.0), 0.0, places=10)


class TestGuards(unittest.TestCase):
    def setUp(self):
        self.az = DeFiRewardTokenSellPressureAnalyzer()

    def test_zero_organic_buy_guarded(self):
        # no organic buys -> huge ratio, no crash
        p = self.az.analyze([make_pos(organic_daily_buy_volume_usd=0.0)])["positions"][0]
        self.assertGreater(p["sell_pressure_ratio"], 1000.0)

    def test_zero_liquidity_guarded(self):
        p = self.az.analyze([make_pos(pool_liquidity_usd=0.0)])["positions"][0]
        self.assertGreater(p["liquidity_turnover_pct"], 0.0)

    def test_sell_propensity_clamped_high(self):
        p = self.az.analyze([make_pos(sell_propensity_pct=150.0)])["positions"][0]
        self.assertEqual(p["sell_propensity_pct"], 100.0)

    def test_sell_propensity_clamped_low(self):
        p = self.az.analyze([make_pos(sell_propensity_pct=-10.0)])["positions"][0]
        self.assertEqual(p["sell_propensity_pct"], 0.0)

    def test_sell_propensity_default(self):
        pos = make_pos()
        del pos["sell_propensity_pct"]
        p = self.az.analyze([pos])["positions"][0]
        self.assertAlmostEqual(p["sell_propensity_pct"], 70.0, places=4)

    def test_no_emissions_zero_sell(self):
        p = self.az.analyze([make_pos(daily_emissions_usd=0.0)])["positions"][0]
        self.assertEqual(p["daily_sell_usd"], 0.0)


class TestClassification(unittest.TestCase):
    def setUp(self):
        self.az = DeFiRewardTokenSellPressureAnalyzer()

    def test_minimal_pressure(self):
        # tiny emissions vs huge organic + deep liquidity
        p = self.az.analyze([make_pos(
            daily_emissions_usd=10_000.0,
            organic_daily_buy_volume_usd=5_000_000.0,
            pool_liquidity_usd=500_000_000.0,
        )])["positions"][0]
        self.assertEqual(p["classification"], "MINIMAL_PRESSURE")

    def test_absorbable(self):
        # ratio ~0.5-1, low turnover
        p = self.az.analyze([make_pos(
            daily_emissions_usd=100_000.0,
            organic_daily_buy_volume_usd=100_000.0,
            pool_liquidity_usd=500_000_000.0,
        )])["positions"][0]
        self.assertEqual(p["classification"], "ABSORBABLE")

    def test_elevated(self):
        # ratio >= 1, turnover moderate
        # sells 210k vs organic 180k -> ratio ~1.17, turnover ~1% -> ELEVATED
        p = self.az.analyze([make_pos(
            daily_emissions_usd=300_000.0,
            organic_daily_buy_volume_usd=180_000.0,
            pool_liquidity_usd=20_000_000.0,
        )])["positions"][0]
        self.assertEqual(p["classification"], "ELEVATED")

    def test_high_pressure(self):
        p = self.az.analyze([make_pos(
            daily_emissions_usd=1_000_000.0,
            organic_daily_buy_volume_usd=200_000.0,
            pool_liquidity_usd=10_000_000.0,
        )])["positions"][0]
        self.assertEqual(p["classification"], "HIGH_PRESSURE")

    def test_reflexive_death_spiral(self):
        # sells crush demand, thin liquidity churned hard, realized apy negative
        p = self.az.analyze([make_pos(
            daily_emissions_usd=2_000_000.0,
            organic_daily_buy_volume_usd=100_000.0,
            pool_liquidity_usd=2_000_000.0,
            advertised_apy_pct=50.0,
        )])["positions"][0]
        self.assertEqual(p["classification"], "REFLEXIVE_DEATH_SPIRAL")

    def test_insufficient_data(self):
        p = self.az.analyze([make_pos(
            daily_emissions_usd=0.0, pool_liquidity_usd=0.0,
        )])["positions"][0]
        self.assertEqual(p["classification"], "INSUFFICIENT_DATA")


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.az = DeFiRewardTokenSellPressureAnalyzer()

    def test_insufficient_data_flag(self):
        p = self.az.analyze([make_pos(
            daily_emissions_usd=0.0, pool_liquidity_usd=0.0,
        )])["positions"][0]
        self.assertIn("INSUFFICIENT_DATA", p["flags"])

    def test_sell_exceeds_organic_flag(self):
        p = self.az.analyze([make_pos(
            daily_emissions_usd=1_000_000.0,
            organic_daily_buy_volume_usd=100_000.0,
        )])["positions"][0]
        self.assertIn("SELL_EXCEEDS_ORGANIC", p["flags"])

    def test_thin_liquidity_flag(self):
        p = self.az.analyze([make_pos(
            daily_emissions_usd=2_000_000.0,
            pool_liquidity_usd=2_000_000.0,
        )])["positions"][0]
        self.assertIn("THIN_LIQUIDITY", p["flags"])

    def test_high_liquidity_turnover_flag(self):
        p = self.az.analyze([make_pos(
            daily_emissions_usd=2_000_000.0,
            pool_liquidity_usd=10_000_000.0,
        )])["positions"][0]
        self.assertIn("HIGH_LIQUIDITY_TURNOVER", p["flags"])

    def test_apy_net_negative_flag(self):
        p = self.az.analyze([make_pos(
            daily_emissions_usd=2_000_000.0,
            pool_liquidity_usd=5_000_000.0,
            advertised_apy_pct=10.0,
        )])["positions"][0]
        self.assertIn("APY_NET_NEGATIVE", p["flags"])

    def test_emissions_self_defeating_flag(self):
        p = self.az.analyze([make_pos(
            daily_emissions_usd=500_000.0,
            pool_liquidity_usd=20_000_000.0,
            advertised_apy_pct=100.0,
        )])["positions"][0]
        self.assertIn("EMISSIONS_SELF_DEFEATING", p["flags"])

    def test_organic_demand_strong_flag(self):
        p = self.az.analyze([make_pos(
            daily_emissions_usd=100_000.0,
            organic_daily_buy_volume_usd=5_000_000.0,
        )])["positions"][0]
        self.assertIn("ORGANIC_DEMAND_STRONG", p["flags"])

    def test_no_self_defeating_when_clean(self):
        p = self.az.analyze([make_pos(
            daily_emissions_usd=10_000.0,
            organic_daily_buy_volume_usd=5_000_000.0,
            pool_liquidity_usd=500_000_000.0,
        )])["positions"][0]
        self.assertNotIn("APY_NET_NEGATIVE", p["flags"])


class TestScoreAndGrade(unittest.TestCase):
    def setUp(self):
        self.az = DeFiRewardTokenSellPressureAnalyzer()

    def test_score_bounds(self):
        for em, org, liq in (
            (10_000.0, 5_000_000.0, 500_000_000.0),
            (1_000_000.0, 100_000.0, 5_000_000.0),
            (2_000_000.0, 50_000.0, 1_000_000.0),
        ):
            p = self.az.analyze([make_pos(
                daily_emissions_usd=em, organic_daily_buy_volume_usd=org,
                pool_liquidity_usd=liq,
            )])["positions"][0]
            self.assertGreaterEqual(p["sell_pressure_score"], 0.0)
            self.assertLessEqual(p["sell_pressure_score"], 100.0)

    def test_no_sells_perfect_score(self):
        p = self.az.analyze([make_pos(daily_emissions_usd=0.0)])["positions"][0]
        self.assertEqual(p["sell_pressure_score"], 100.0)
        self.assertEqual(p["grade"], "A")

    def test_low_pressure_scores_higher_than_high(self):
        low = self.az.analyze([make_pos(
            daily_emissions_usd=10_000.0,
            organic_daily_buy_volume_usd=5_000_000.0,
            pool_liquidity_usd=500_000_000.0,
        )])["positions"][0]
        high = self.az.analyze([make_pos(
            daily_emissions_usd=2_000_000.0,
            organic_daily_buy_volume_usd=100_000.0,
            pool_liquidity_usd=2_000_000.0,
        )])["positions"][0]
        self.assertGreater(low["sell_pressure_score"], high["sell_pressure_score"])

    def test_grade_thresholds(self):
        self.assertEqual(self.az._grade(95.0), "A")
        self.assertEqual(self.az._grade(90.0), "A")
        self.assertEqual(self.az._grade(80.0), "B")
        self.assertEqual(self.az._grade(75.0), "B")
        self.assertEqual(self.az._grade(65.0), "C")
        self.assertEqual(self.az._grade(60.0), "C")
        self.assertEqual(self.az._grade(50.0), "D")
        self.assertEqual(self.az._grade(45.0), "D")
        self.assertEqual(self.az._grade(10.0), "F")


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.az = DeFiRewardTokenSellPressureAnalyzer()

    def test_best_worst_counts(self):
        r = self.az.analyze([
            make_pos(name="clean",
                     daily_emissions_usd=10_000.0,
                     organic_daily_buy_volume_usd=5_000_000.0,
                     pool_liquidity_usd=500_000_000.0),
            make_pos(name="spiral",
                     daily_emissions_usd=2_000_000.0,
                     organic_daily_buy_volume_usd=100_000.0,
                     pool_liquidity_usd=2_000_000.0,
                     advertised_apy_pct=20.0),
        ])
        agg = r["aggregates"]
        self.assertEqual(agg["best_position"]["name"], "clean")
        self.assertEqual(agg["worst_position"]["name"], "spiral")
        self.assertGreaterEqual(agg["high_pressure_count"], 1)
        self.assertGreaterEqual(agg["net_negative_apy_count"], 1)

    def test_average_score(self):
        r = self.az.analyze([make_pos(), make_pos(name="B")])
        scores = [p["sell_pressure_score"] for p in r["positions"]]
        self.assertAlmostEqual(
            r["aggregates"]["average_sell_pressure_score"],
            round(sum(scores) / len(scores), 4), places=4
        )


class TestLogging(unittest.TestCase):
    def setUp(self):
        self.az = DeFiRewardTokenSellPressureAnalyzer()

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.az.analyze([make_pos()], config={"write_log": True, "data_dir": d})
            path = os.path.join(d, "reward_token_sell_pressure_log.json")
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                self.assertEqual(len(json.load(f)), 1)

    def test_no_log_without_flag(self):
        with tempfile.TemporaryDirectory() as d:
            self.az.analyze([make_pos()], config={"data_dir": d})
            path = os.path.join(d, "reward_token_sell_pressure_log.json")
            self.assertFalse(os.path.exists(path))

    def test_ring_buffer_caps_at_100(self):
        with tempfile.TemporaryDirectory() as d:
            for _ in range(103):
                self.az.analyze([make_pos()], config={"write_log": True, "data_dir": d})
            with open(os.path.join(d, "reward_token_sell_pressure_log.json")) as f:
                self.assertEqual(len(json.load(f)), 100)

    def test_corrupt_log_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "reward_token_sell_pressure_log.json")
            with open(path, "w") as f:
                f.write("garbage")
            self.az.analyze([make_pos()], config={"write_log": True, "data_dir": d})
            with open(path) as f:
                self.assertEqual(len(json.load(f)), 1)


if __name__ == "__main__":
    unittest.main()
