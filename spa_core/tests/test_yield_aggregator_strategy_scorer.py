"""
Tests for MP-897 YieldAggregatorStrategyScorer.
Run: python3 -m unittest spa_core.tests.test_yield_aggregator_strategy_scorer -v
"""

import json
import os
import time
import unittest

from spa_core.analytics.yield_aggregator_strategy_scorer import (
    analyze,
    _strategy_maturity,
    _harvest_health,
    _aggregator_grade,
    _build_recommendation,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_strategy(**overrides):
    base = {
        "name": "Test Vault",
        "aggregator": "YEARN",
        "underlying_apy_pct": 5.0,
        "aggregated_apy_pct": 8.0,
        "management_fee_pct": 0.5,
        "performance_fee_pct": 10.0,
        "auto_compound_frequency": "DAILY",
        "strategy_age_days": 400,
        "tvl_usd": 5_000_000.0,
        "strategy_count": 3,
        "last_harvest_days_ago": 1,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestStrategyMaturity(unittest.TestCase):
    def test_new_exactly_90(self):
        self.assertEqual(_strategy_maturity(90), "NEW")

    def test_new_zero(self):
        self.assertEqual(_strategy_maturity(0), "NEW")

    def test_new_89(self):
        self.assertEqual(_strategy_maturity(89), "NEW")

    def test_growing_91(self):
        self.assertEqual(_strategy_maturity(91), "GROWING")

    def test_growing_180(self):
        self.assertEqual(_strategy_maturity(180), "GROWING")

    def test_mature_181(self):
        self.assertEqual(_strategy_maturity(181), "MATURE")

    def test_mature_365(self):
        self.assertEqual(_strategy_maturity(365), "MATURE")

    def test_established_366(self):
        self.assertEqual(_strategy_maturity(366), "ESTABLISHED")

    def test_established_1000(self):
        self.assertEqual(_strategy_maturity(1000), "ESTABLISHED")


class TestHarvestHealth(unittest.TestCase):
    def test_fresh_zero(self):
        self.assertEqual(_harvest_health(0), "FRESH")

    def test_fresh_one(self):
        self.assertEqual(_harvest_health(1), "FRESH")

    def test_healthy_2(self):
        self.assertEqual(_harvest_health(2), "HEALTHY")

    def test_healthy_7(self):
        self.assertEqual(_harvest_health(7), "HEALTHY")

    def test_stale_8(self):
        self.assertEqual(_harvest_health(8), "STALE")

    def test_stale_30(self):
        self.assertEqual(_harvest_health(30), "STALE")

    def test_abandoned_31(self):
        self.assertEqual(_harvest_health(31), "ABANDONED")

    def test_abandoned_100(self):
        self.assertEqual(_harvest_health(100), "ABANDONED")


class TestAggregatorGrade(unittest.TestCase):
    def test_grade_s(self):
        self.assertEqual(_aggregator_grade(90), "S")

    def test_grade_s_100(self):
        self.assertEqual(_aggregator_grade(100), "S")

    def test_grade_a_80(self):
        self.assertEqual(_aggregator_grade(80), "A")

    def test_grade_a_89(self):
        self.assertEqual(_aggregator_grade(89), "A")

    def test_grade_b_70(self):
        self.assertEqual(_aggregator_grade(70), "B")

    def test_grade_b_79(self):
        self.assertEqual(_aggregator_grade(79), "B")

    def test_grade_c_60(self):
        self.assertEqual(_aggregator_grade(60), "C")

    def test_grade_c_69(self):
        self.assertEqual(_aggregator_grade(69), "C")

    def test_grade_d_50(self):
        self.assertEqual(_aggregator_grade(50), "D")

    def test_grade_d_59(self):
        self.assertEqual(_aggregator_grade(59), "D")

    def test_grade_f_49(self):
        self.assertEqual(_aggregator_grade(49), "F")

    def test_grade_f_0(self):
        self.assertEqual(_aggregator_grade(0), "F")


class TestBuildRecommendation(unittest.TestCase):
    def test_grade_s(self):
        rec = _build_recommendation("S", 7.5, 1.5, 0.5, [])
        self.assertIn("Top-tier", rec)
        self.assertIn("7.5%", rec)
        self.assertIn("1.50x", rec)

    def test_grade_a(self):
        rec = _build_recommendation("A", 6.0, 1.2, 0.8, [])
        self.assertIn("Top-tier", rec)

    def test_grade_b(self):
        rec = _build_recommendation("B", 5.0, 1.1, 1.0, ["LOW_TVL"])
        self.assertIn("Solid", rec)
        self.assertIn("1 minor", rec)

    def test_grade_b_two_flags(self):
        rec = _build_recommendation("B", 4.0, 1.05, 1.2, ["LOW_TVL", "SINGLE_STRATEGY"])
        self.assertIn("2 minor", rec)

    def test_grade_c(self):
        rec = _build_recommendation("C", 3.0, 0.8, 4.0, [])
        self.assertIn("Mediocre", rec)
        self.assertIn("4.0%", rec)

    def test_grade_d(self):
        rec = _build_recommendation("D", 1.0, 0.5, 5.0, ["HIGH_FEES", "STALE_HARVEST"])
        self.assertIn("Avoid", rec)

    def test_grade_f(self):
        rec = _build_recommendation("F", -1.0, 0.2, 6.0, [])
        self.assertIn("poor metrics", rec)

    def test_grade_f_with_flags(self):
        rec = _build_recommendation("F", -1.0, 0.2, 6.0, ["HIGH_FEES", "LOW_TVL", "STALE_HARVEST"])
        self.assertIn("HIGH_FEES", rec)


# ---------------------------------------------------------------------------
# analyze() — empty input
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):
    def test_empty_strategies(self):
        result = analyze([])
        self.assertEqual(result["strategies"], [])
        self.assertIsNone(result["best_strategy"])
        self.assertIsNone(result["most_efficient"])
        self.assertEqual(result["average_net_apy_pct"], 0.0)
        self.assertIn("timestamp", result)

    def test_empty_has_timestamp(self):
        before = time.time()
        result = analyze([])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)


# ---------------------------------------------------------------------------
# analyze() — basic single strategy
# ---------------------------------------------------------------------------

class TestAnalyzeSingle(unittest.TestCase):
    def setUp(self):
        self.s = _make_strategy()
        self.result = analyze([self.s])
        self.strat = self.result["strategies"][0]

    def test_returns_one_strategy(self):
        self.assertEqual(len(self.result["strategies"]), 1)

    def test_name_preserved(self):
        self.assertEqual(self.strat["name"], "Test Vault")

    def test_aggregator_preserved(self):
        self.assertEqual(self.strat["aggregator"], "YEARN")

    def test_apy_boost(self):
        # aggregated 8 - underlying 5 = 3
        self.assertAlmostEqual(self.strat["apy_boost_pct"], 3.0, places=4)

    def test_fee_drag(self):
        # mgmt 0.5 + perf 10 * 8/100 = 0.5 + 0.8 = 1.3
        self.assertAlmostEqual(self.strat["fee_drag_pct"], 1.3, places=4)

    def test_net_apy(self):
        # 8 - 1.3 = 6.7
        self.assertAlmostEqual(self.strat["net_apy_pct"], 6.7, places=4)

    def test_efficiency_ratio(self):
        # 6.7 / 5.0 = 1.34
        self.assertAlmostEqual(self.strat["efficiency_ratio"], 1.34, places=4)

    def test_compound_frequency_score(self):
        self.assertEqual(self.strat["compound_frequency_score"], 80)  # DAILY

    def test_strategy_maturity_established(self):
        self.assertEqual(self.strat["strategy_maturity"], "ESTABLISHED")

    def test_harvest_health_fresh(self):
        self.assertEqual(self.strat["harvest_health"], "FRESH")

    def test_quality_score_range(self):
        self.assertGreaterEqual(self.strat["quality_score"], 0)
        self.assertLessEqual(self.strat["quality_score"], 100)

    def test_grade_is_string(self):
        self.assertIn(self.strat["aggregator_grade"], ["S", "A", "B", "C", "D", "F"])

    def test_flags_is_list(self):
        self.assertIsInstance(self.strat["flags"], list)

    def test_recommendation_is_string(self):
        self.assertIsInstance(self.strat["recommendation"], str)

    def test_best_strategy(self):
        self.assertEqual(self.result["best_strategy"], "Test Vault")

    def test_most_efficient(self):
        self.assertEqual(self.result["most_efficient"], "Test Vault")

    def test_average_net_apy(self):
        self.assertAlmostEqual(self.result["average_net_apy_pct"], 6.7, places=4)


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):
    def test_insufficient_boost(self):
        s = _make_strategy(underlying_apy_pct=6.0, aggregated_apy_pct=7.0)  # boost=1 < 2
        result = analyze([s])
        self.assertIn("INSUFFICIENT_BOOST", result["strategies"][0]["flags"])

    def test_no_insufficient_boost_when_enough(self):
        s = _make_strategy(underlying_apy_pct=5.0, aggregated_apy_pct=8.0)  # boost=3 >= 2
        result = analyze([s])
        self.assertNotIn("INSUFFICIENT_BOOST", result["strategies"][0]["flags"])

    def test_high_fees(self):
        # management=2.0, performance=20 * 10/100=2.0 → drag=4.0 > 3.0
        s = _make_strategy(management_fee_pct=2.0, performance_fee_pct=20.0, aggregated_apy_pct=10.0)
        result = analyze([s])
        self.assertIn("HIGH_FEES", result["strategies"][0]["flags"])

    def test_no_high_fees(self):
        s = _make_strategy(management_fee_pct=0.2, performance_fee_pct=5.0, aggregated_apy_pct=8.0)
        result = analyze([s])
        # drag = 0.2 + 0.4 = 0.6
        self.assertNotIn("HIGH_FEES", result["strategies"][0]["flags"])

    def test_stale_harvest_stale(self):
        s = _make_strategy(last_harvest_days_ago=15)
        result = analyze([s])
        self.assertIn("STALE_HARVEST", result["strategies"][0]["flags"])

    def test_stale_harvest_abandoned(self):
        s = _make_strategy(last_harvest_days_ago=60)
        result = analyze([s])
        self.assertIn("STALE_HARVEST", result["strategies"][0]["flags"])

    def test_no_stale_harvest_fresh(self):
        s = _make_strategy(last_harvest_days_ago=0)
        result = analyze([s])
        self.assertNotIn("STALE_HARVEST", result["strategies"][0]["flags"])

    def test_no_stale_harvest_healthy(self):
        s = _make_strategy(last_harvest_days_ago=5)
        result = analyze([s])
        self.assertNotIn("STALE_HARVEST", result["strategies"][0]["flags"])

    def test_low_tvl(self):
        s = _make_strategy(tvl_usd=500_000)
        result = analyze([s])
        self.assertIn("LOW_TVL", result["strategies"][0]["flags"])

    def test_no_low_tvl(self):
        s = _make_strategy(tvl_usd=2_000_000)
        result = analyze([s])
        self.assertNotIn("LOW_TVL", result["strategies"][0]["flags"])

    def test_single_strategy(self):
        s = _make_strategy(strategy_count=1)
        result = analyze([s])
        self.assertIn("SINGLE_STRATEGY", result["strategies"][0]["flags"])

    def test_no_single_strategy(self):
        s = _make_strategy(strategy_count=2)
        result = analyze([s])
        self.assertNotIn("SINGLE_STRATEGY", result["strategies"][0]["flags"])

    def test_custom_min_boost(self):
        s = _make_strategy(underlying_apy_pct=5.0, aggregated_apy_pct=6.0)  # boost=1
        result = analyze([s], config={"min_apy_improvement_pct": 0.5})
        self.assertNotIn("INSUFFICIENT_BOOST", result["strategies"][0]["flags"])

    def test_no_flags_clean_strategy(self):
        s = _make_strategy(
            underlying_apy_pct=5.0,
            aggregated_apy_pct=10.0,
            management_fee_pct=0.2,
            performance_fee_pct=5.0,
            tvl_usd=5_000_000,
            strategy_count=5,
            last_harvest_days_ago=0,
        )
        result = analyze([s])
        self.assertEqual(result["strategies"][0]["flags"], [])


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_underlying_zero_efficiency_is_one(self):
        s = _make_strategy(underlying_apy_pct=0.0, aggregated_apy_pct=5.0)
        result = analyze([s])
        self.assertAlmostEqual(result["strategies"][0]["efficiency_ratio"], 1.0, places=4)

    def test_quality_score_clamped_0_100(self):
        # Pathological: all zeros
        s = _make_strategy(
            underlying_apy_pct=0.0,
            aggregated_apy_pct=0.0,
            management_fee_pct=99.0,
            performance_fee_pct=99.0,
            auto_compound_frequency="MANUAL",
            strategy_age_days=0,
            tvl_usd=0.0,
            strategy_count=0,
            last_harvest_days_ago=999,
        )
        result = analyze([s])
        qs = result["strategies"][0]["quality_score"]
        self.assertGreaterEqual(qs, 0)
        self.assertLessEqual(qs, 100)

    def test_hourly_compound_score(self):
        s = _make_strategy(auto_compound_frequency="HOURLY")
        result = analyze([s])
        self.assertEqual(result["strategies"][0]["compound_frequency_score"], 100)

    def test_weekly_compound_score(self):
        s = _make_strategy(auto_compound_frequency="WEEKLY")
        result = analyze([s])
        self.assertEqual(result["strategies"][0]["compound_frequency_score"], 50)

    def test_unknown_compound_freq_defaults_10(self):
        s = _make_strategy(auto_compound_frequency="BIWEEKLY")
        result = analyze([s])
        self.assertEqual(result["strategies"][0]["compound_frequency_score"], 10)

    def test_strategy_diversity_score_capped_100(self):
        # strategy_count=10 → 10*20=200 → capped at 100
        s = _make_strategy(strategy_count=10)
        result = analyze([s])
        # Just ensure quality_score is valid (diversity capped)
        self.assertLessEqual(result["strategies"][0]["quality_score"], 100)

    def test_negative_net_apy(self):
        # Very high fees → negative net
        s = _make_strategy(management_fee_pct=10.0, aggregated_apy_pct=5.0)
        result = analyze([s])
        self.assertLess(result["strategies"][0]["net_apy_pct"], 0)

    def test_high_efficiency_ratio(self):
        s = _make_strategy(underlying_apy_pct=1.0, aggregated_apy_pct=20.0,
                           management_fee_pct=0.0, performance_fee_pct=0.0)
        result = analyze([s])
        self.assertGreater(result["strategies"][0]["efficiency_ratio"], 1.0)


# ---------------------------------------------------------------------------
# Multi-strategy selection
# ---------------------------------------------------------------------------

class TestMultiStrategy(unittest.TestCase):
    def setUp(self):
        self.s_low = _make_strategy(
            name="Low",
            underlying_apy_pct=3.0,
            aggregated_apy_pct=5.0,
            management_fee_pct=0.5,
            performance_fee_pct=10.0,
        )
        self.s_high = _make_strategy(
            name="High",
            underlying_apy_pct=5.0,
            aggregated_apy_pct=15.0,
            management_fee_pct=0.5,
            performance_fee_pct=10.0,
        )
        self.s_mid = _make_strategy(
            name="Mid",
            underlying_apy_pct=4.0,
            aggregated_apy_pct=10.0,
            management_fee_pct=0.5,
            performance_fee_pct=10.0,
        )
        self.result = analyze([self.s_low, self.s_high, self.s_mid])

    def test_best_strategy_highest_net_apy(self):
        # High: net_apy = 15 - (0.5 + 10*15/100) = 15 - 2.0 = 13.0
        self.assertEqual(self.result["best_strategy"], "High")

    def test_most_efficient_highest_ratio(self):
        # High: efficiency = 13.0 / 5.0 = 2.6
        # Mid: net=10-(0.5+1.0)=8.5 eff=8.5/4=2.125
        # Low: net=5-(0.5+0.5)=4.0 eff=4/3=1.333
        self.assertEqual(self.result["most_efficient"], "High")

    def test_average_net_apy(self):
        # Low net=4.0, High net=13.0, Mid net=8.5 → avg = 25.5/3 = 8.5
        self.assertAlmostEqual(self.result["average_net_apy_pct"], 8.5, places=3)

    def test_all_strategies_returned(self):
        self.assertEqual(len(self.result["strategies"]), 3)

    def test_strategy_names_preserved(self):
        names = [s["name"] for s in self.result["strategies"]]
        self.assertIn("Low", names)
        self.assertIn("High", names)
        self.assertIn("Mid", names)


# ---------------------------------------------------------------------------
# Aggregator types
# ---------------------------------------------------------------------------

class TestAggregatorTypes(unittest.TestCase):
    def test_convex(self):
        s = _make_strategy(aggregator="CONVEX")
        result = analyze([s])
        self.assertEqual(result["strategies"][0]["aggregator"], "CONVEX")

    def test_beefy(self):
        s = _make_strategy(aggregator="BEEFY")
        result = analyze([s])
        self.assertEqual(result["strategies"][0]["aggregator"], "BEEFY")

    def test_harvest(self):
        s = _make_strategy(aggregator="HARVEST")
        result = analyze([s])
        self.assertEqual(result["strategies"][0]["aggregator"], "HARVEST")

    def test_other(self):
        s = _make_strategy(aggregator="OTHER")
        result = analyze([s])
        self.assertEqual(result["strategies"][0]["aggregator"], "OTHER")


# ---------------------------------------------------------------------------
# Maturity boundary
# ---------------------------------------------------------------------------

class TestMaturityBoundary(unittest.TestCase):
    def test_exactly_91_days(self):
        s = _make_strategy(strategy_age_days=91)
        r = analyze([s])
        self.assertEqual(r["strategies"][0]["strategy_maturity"], "GROWING")

    def test_exactly_181_days(self):
        s = _make_strategy(strategy_age_days=181)
        r = analyze([s])
        self.assertEqual(r["strategies"][0]["strategy_maturity"], "MATURE")

    def test_exactly_366_days(self):
        s = _make_strategy(strategy_age_days=366)
        r = analyze([s])
        self.assertEqual(r["strategies"][0]["strategy_maturity"], "ESTABLISHED")


# ---------------------------------------------------------------------------
# Harvest boundary
# ---------------------------------------------------------------------------

class TestHarvestBoundary(unittest.TestCase):
    def test_exactly_7_days(self):
        s = _make_strategy(last_harvest_days_ago=7)
        r = analyze([s])
        self.assertEqual(r["strategies"][0]["harvest_health"], "HEALTHY")

    def test_exactly_8_days(self):
        s = _make_strategy(last_harvest_days_ago=8)
        r = analyze([s])
        self.assertEqual(r["strategies"][0]["harvest_health"], "STALE")

    def test_exactly_30_days(self):
        s = _make_strategy(last_harvest_days_ago=30)
        r = analyze([s])
        self.assertEqual(r["strategies"][0]["harvest_health"], "STALE")

    def test_exactly_31_days(self):
        s = _make_strategy(last_harvest_days_ago=31)
        r = analyze([s])
        self.assertEqual(r["strategies"][0]["harvest_health"], "ABANDONED")


# ---------------------------------------------------------------------------
# Quality score formula spot-checks
# ---------------------------------------------------------------------------

class TestQualityScoreFormula(unittest.TestCase):
    def test_perfect_strategy(self):
        # HOURLY(100), ESTABLISHED(100), FRESH(100), 5 strategies(100), efficiency huge→capped 100
        s = _make_strategy(
            underlying_apy_pct=5.0,
            aggregated_apy_pct=50.0,
            management_fee_pct=0.0,
            performance_fee_pct=0.0,
            auto_compound_frequency="HOURLY",
            strategy_age_days=400,
            strategy_count=5,
            last_harvest_days_ago=0,
        )
        r = analyze([s])
        qs = r["strategies"][0]["quality_score"]
        # = int(100*0.20 + 100*0.30 + 100*0.20 + 100*0.10 + 100*0.20)
        # = int(20 + 30 + 20 + 10 + 20) = 100
        self.assertEqual(qs, 100)

    def test_manual_new_abandoned_single(self):
        # MANUAL(10), NEW(10), ABANDONED(0), diversity=20(1 strategy)
        # efficiency: underlying=5, net_apy=3-drag; let's do underlying=5, aggregated=5 exact fee=0
        # net=5, eff=1.0, eff_capped=20
        # = int(20*0.20 + 10*0.30 + 20*0.20 + 10*0.10 + 0*0.20)
        # = int(4 + 3 + 4 + 1 + 0) = 12
        s = _make_strategy(
            underlying_apy_pct=5.0,
            aggregated_apy_pct=5.0,
            management_fee_pct=0.0,
            performance_fee_pct=0.0,
            auto_compound_frequency="MANUAL",
            strategy_age_days=30,
            strategy_count=1,
            last_harvest_days_ago=60,
            tvl_usd=500_000,
        )
        r = analyze([s])
        qs = r["strategies"][0]["quality_score"]
        self.assertEqual(qs, 12)


# ---------------------------------------------------------------------------
# Logging (non-crashing)
# ---------------------------------------------------------------------------

class TestLogging(unittest.TestCase):
    def test_logging_does_not_raise(self):
        # Should complete without exception
        s = _make_strategy()
        result = analyze([s])
        self.assertIn("timestamp", result)

    def test_multiple_calls_do_not_raise(self):
        for _ in range(3):
            analyze([_make_strategy()])


if __name__ == "__main__":
    unittest.main()
