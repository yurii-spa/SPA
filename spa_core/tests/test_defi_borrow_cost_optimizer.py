"""
Tests for MP-863 DeFiBorrowCostOptimizer.
Run: python3 -m unittest spa_core.tests.test_defi_borrow_cost_optimizer -v
"""

import os
import sys
import json
import time
import unittest

# Ensure repo root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_borrow_cost_optimizer import (
    analyze,
    _effective_cost_score,
    _rate_stability_score,
    _liquidity_score,
    _utilization_risk_score,
    _composite_score,
    _borrow_label,
    _is_near_kink,
    _rate_trend,
    _recommendation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _market(**kwargs):
    """Build a minimal valid borrow market dict."""
    defaults = {
        "protocol": "Aave",
        "borrow_asset": "USDC",
        "borrow_apy_pct": 3.0,
        "utilization_pct": 60.0,
        "rate_model": "VARIABLE",
        "kink_utilization_pct": 0.0,
        "rate_30d_avg_pct": 3.0,
        "rate_30d_std_pct": 0.3,
        "available_liquidity_usd": 5_000_000.0,
    }
    defaults.update(kwargs)
    return defaults


# ===========================================================================
# 1. effective_cost_score
# ===========================================================================

class TestEffectiveCostScore(unittest.TestCase):

    def test_at_or_below_1(self):
        self.assertEqual(_effective_cost_score(0.5), 100)

    def test_exactly_1(self):
        self.assertEqual(_effective_cost_score(1.0), 100)

    def test_between_1_and_3(self):
        self.assertEqual(_effective_cost_score(2.0), 85)

    def test_exactly_3(self):
        self.assertEqual(_effective_cost_score(3.0), 85)

    def test_between_3_and_5(self):
        self.assertEqual(_effective_cost_score(4.5), 70)

    def test_exactly_5(self):
        self.assertEqual(_effective_cost_score(5.0), 70)

    def test_between_5_and_8(self):
        self.assertEqual(_effective_cost_score(7.0), 55)

    def test_exactly_8(self):
        self.assertEqual(_effective_cost_score(8.0), 55)

    def test_between_8_and_12(self):
        self.assertEqual(_effective_cost_score(10.0), 35)

    def test_exactly_12(self):
        self.assertEqual(_effective_cost_score(12.0), 35)

    def test_between_12_and_20(self):
        self.assertEqual(_effective_cost_score(15.0), 20)

    def test_exactly_20(self):
        self.assertEqual(_effective_cost_score(20.0), 20)

    def test_above_20(self):
        self.assertEqual(_effective_cost_score(25.0), 5)

    def test_zero_apy(self):
        self.assertEqual(_effective_cost_score(0.0), 100)

    def test_very_high_apy(self):
        self.assertEqual(_effective_cost_score(100.0), 5)


# ===========================================================================
# 2. rate_stability_score
# ===========================================================================

class TestRateStabilityScore(unittest.TestCase):

    def test_at_or_below_01(self):
        self.assertEqual(_rate_stability_score(0.05), 100)

    def test_exactly_01(self):
        self.assertEqual(_rate_stability_score(0.1), 100)

    def test_between_01_and_05(self):
        self.assertEqual(_rate_stability_score(0.3), 80)

    def test_exactly_05(self):
        self.assertEqual(_rate_stability_score(0.5), 80)

    def test_between_05_and_10(self):
        self.assertEqual(_rate_stability_score(0.8), 60)

    def test_exactly_10(self):
        self.assertEqual(_rate_stability_score(1.0), 60)

    def test_between_10_and_20(self):
        self.assertEqual(_rate_stability_score(1.5), 40)

    def test_exactly_20(self):
        self.assertEqual(_rate_stability_score(2.0), 40)

    def test_between_20_and_50(self):
        self.assertEqual(_rate_stability_score(3.0), 20)

    def test_exactly_50(self):
        self.assertEqual(_rate_stability_score(5.0), 20)

    def test_above_50(self):
        self.assertEqual(_rate_stability_score(6.0), 5)

    def test_zero_std(self):
        self.assertEqual(_rate_stability_score(0.0), 100)


# ===========================================================================
# 3. liquidity_score
# ===========================================================================

class TestLiquidityScore(unittest.TestCase):

    def test_above_100m(self):
        self.assertEqual(_liquidity_score(200_000_000), 100)

    def test_exactly_100m(self):
        self.assertEqual(_liquidity_score(100_000_000), 100)

    def test_between_10m_and_100m(self):
        self.assertEqual(_liquidity_score(50_000_000), 80)

    def test_exactly_10m(self):
        self.assertEqual(_liquidity_score(10_000_000), 80)

    def test_between_1m_and_10m(self):
        self.assertEqual(_liquidity_score(5_000_000), 60)

    def test_exactly_1m(self):
        self.assertEqual(_liquidity_score(1_000_000), 60)

    def test_between_500k_and_1m(self):
        self.assertEqual(_liquidity_score(750_000), 40)

    def test_exactly_500k(self):
        self.assertEqual(_liquidity_score(500_000), 40)

    def test_between_100k_and_500k(self):
        self.assertEqual(_liquidity_score(200_000), 20)

    def test_exactly_100k(self):
        self.assertEqual(_liquidity_score(100_000), 20)

    def test_below_100k(self):
        self.assertEqual(_liquidity_score(50_000), 5)

    def test_zero(self):
        self.assertEqual(_liquidity_score(0), 5)


# ===========================================================================
# 4. utilization_risk_score
# ===========================================================================

class TestUtilizationRiskScore(unittest.TestCase):

    def test_at_or_below_50(self):
        self.assertEqual(_utilization_risk_score(30.0), 100)

    def test_exactly_50(self):
        self.assertEqual(_utilization_risk_score(50.0), 100)

    def test_between_50_and_70(self):
        self.assertEqual(_utilization_risk_score(65.0), 80)

    def test_exactly_70(self):
        self.assertEqual(_utilization_risk_score(70.0), 80)

    def test_between_70_and_80(self):
        self.assertEqual(_utilization_risk_score(75.0), 60)

    def test_exactly_80(self):
        self.assertEqual(_utilization_risk_score(80.0), 60)

    def test_between_80_and_90(self):
        self.assertEqual(_utilization_risk_score(85.0), 30)

    def test_exactly_90(self):
        self.assertEqual(_utilization_risk_score(90.0), 30)

    def test_between_90_and_95(self):
        self.assertEqual(_utilization_risk_score(93.0), 10)

    def test_exactly_95(self):
        self.assertEqual(_utilization_risk_score(95.0), 10)

    def test_above_95(self):
        self.assertEqual(_utilization_risk_score(98.0), 5)

    def test_full_util(self):
        self.assertEqual(_utilization_risk_score(100.0), 5)


# ===========================================================================
# 5. composite_score
# ===========================================================================

class TestCompositeScore(unittest.TestCase):

    def test_all_100(self):
        self.assertEqual(_composite_score(100, 100, 100, 100), 100)

    def test_all_zero(self):
        self.assertEqual(_composite_score(0, 0, 0, 0), 0)

    def test_weights_sum(self):
        # 80*0.4 + 60*0.3 + 40*0.2 + 20*0.1 = 32+18+8+2 = 60
        self.assertEqual(_composite_score(80, 60, 40, 20), 60)

    def test_caps_at_100(self):
        self.assertEqual(_composite_score(200, 200, 200, 200), 100)

    def test_truncates_not_rounds(self):
        # 85*0.4 + 80*0.3 + 80*0.2 + 80*0.1 = 34+24+16+8 = 82.0
        self.assertEqual(_composite_score(85, 80, 80, 80), 82)

    def test_int_return_type(self):
        result = _composite_score(70, 70, 70, 70)
        self.assertIsInstance(result, int)


# ===========================================================================
# 6. borrow_label
# ===========================================================================

class TestBorrowLabel(unittest.TestCase):

    def test_optimal(self):
        self.assertEqual(_borrow_label(80), "OPTIMAL")

    def test_optimal_100(self):
        self.assertEqual(_borrow_label(100), "OPTIMAL")

    def test_good(self):
        self.assertEqual(_borrow_label(60), "GOOD")

    def test_good_79(self):
        self.assertEqual(_borrow_label(79), "GOOD")

    def test_acceptable(self):
        self.assertEqual(_borrow_label(40), "ACCEPTABLE")

    def test_acceptable_59(self):
        self.assertEqual(_borrow_label(59), "ACCEPTABLE")

    def test_risky(self):
        self.assertEqual(_borrow_label(20), "RISKY")

    def test_risky_39(self):
        self.assertEqual(_borrow_label(39), "RISKY")

    def test_avoid(self):
        self.assertEqual(_borrow_label(19), "AVOID")

    def test_avoid_0(self):
        self.assertEqual(_borrow_label(0), "AVOID")


# ===========================================================================
# 7. is_near_kink
# ===========================================================================

class TestIsNearKink(unittest.TestCase):

    def test_kinked_exactly_at_kink(self):
        self.assertTrue(_is_near_kink("KINKED", 80.0, 80.0))

    def test_kinked_within_5(self):
        self.assertTrue(_is_near_kink("KINKED", 76.0, 80.0))

    def test_kinked_exactly_5_below(self):
        self.assertTrue(_is_near_kink("KINKED", 75.0, 80.0))

    def test_kinked_exactly_5_above(self):
        self.assertTrue(_is_near_kink("KINKED", 85.0, 80.0))

    def test_kinked_just_outside(self):
        self.assertFalse(_is_near_kink("KINKED", 74.9, 80.0))

    def test_kinked_zero_kink(self):
        self.assertFalse(_is_near_kink("KINKED", 0.0, 0.0))

    def test_variable_model(self):
        self.assertFalse(_is_near_kink("VARIABLE", 80.0, 80.0))

    def test_stable_model(self):
        self.assertFalse(_is_near_kink("STABLE", 80.0, 80.0))

    def test_kinked_far_away(self):
        self.assertFalse(_is_near_kink("KINKED", 50.0, 80.0))


# ===========================================================================
# 8. rate_trend
# ===========================================================================

class TestRateTrend(unittest.TestCase):

    def test_falling(self):
        # current = 2.8 < 3.0 * 0.95 = 2.85
        self.assertEqual(_rate_trend(2.8, 3.0), "FALLING")

    def test_rising(self):
        # current = 3.2 > 3.0 * 1.05 = 3.15
        self.assertEqual(_rate_trend(3.2, 3.0), "RISING")

    def test_stable_same(self):
        self.assertEqual(_rate_trend(3.0, 3.0), "STABLE")

    def test_stable_within_band(self):
        # 3.0 * 0.95 = 2.85, 3.0 * 1.05 = 3.15
        self.assertEqual(_rate_trend(3.0, 3.0), "STABLE")

    def test_zero_avg_stable(self):
        self.assertEqual(_rate_trend(5.0, 0.0), "STABLE")

    def test_exactly_at_lower_boundary(self):
        # current = avg * 0.95 exactly → NOT falling (< not <=)
        self.assertEqual(_rate_trend(2.85, 3.0), "STABLE")

    def test_exactly_at_upper_boundary(self):
        self.assertEqual(_rate_trend(3.15, 3.0), "STABLE")


# ===========================================================================
# 9. recommendation strings
# ===========================================================================

class TestRecommendation(unittest.TestCase):

    def test_optimal_contains_best_available(self):
        rec = _recommendation("OPTIMAL", "Aave", "USDC", 2.5, 0.2, 60)
        self.assertIn("Best available rate", rec)
        self.assertIn("USDC", rec)
        self.assertIn("Aave", rec)

    def test_good_contains_std(self):
        rec = _recommendation("GOOD", "Compound", "DAI", 4.0, 0.5, 65)
        self.assertIn("stable", rec)
        self.assertIn("0.50% std", rec)

    def test_acceptable_contains_volatility(self):
        rec = _recommendation("ACCEPTABLE", "Euler", "ETH", 8.0, 1.5, 78)
        self.assertIn("volatility", rec)

    def test_risky_contains_utilization(self):
        rec = _recommendation("RISKY", "Morpho", "USDC", 12.0, 2.0, 92)
        self.assertIn("92%", rec)
        self.assertIn("may spike", rec)

    def test_avoid_contains_avoid(self):
        rec = _recommendation("AVOID", "Unknown", "TOKEN", 25.0, 6.0, 99)
        self.assertIn("Avoid", rec)
        self.assertIn("Poor composite", rec)


# ===========================================================================
# 10. analyze() — integration tests
# ===========================================================================

class TestAnalyzeBasic(unittest.TestCase):

    def setUp(self):
        self.market = _market(
            protocol="Aave",
            borrow_asset="USDC",
            borrow_apy_pct=2.0,
            utilization_pct=50.0,
            rate_model="VARIABLE",
            kink_utilization_pct=0.0,
            rate_30d_avg_pct=2.0,
            rate_30d_std_pct=0.05,
            available_liquidity_usd=50_000_000,
        )

    def test_returns_dict(self):
        result = analyze([self.market])
        self.assertIsInstance(result, dict)

    def test_required_keys(self):
        result = analyze([self.market])
        for key in ("borrow_markets", "best_borrow_market", "asset_summary",
                    "filtered_out_count", "average_composite_score", "timestamp"):
            self.assertIn(key, result)

    def test_market_keys(self):
        result = analyze([self.market])
        m = result["borrow_markets"][0]
        for key in ("protocol", "borrow_asset", "borrow_apy_pct",
                    "effective_cost_score", "rate_stability_score",
                    "liquidity_score", "utilization_risk_score",
                    "composite_score", "borrow_label", "is_near_kink",
                    "rate_trend", "recommendation"):
            self.assertIn(key, m)

    def test_composite_is_int(self):
        result = analyze([self.market])
        self.assertIsInstance(result["borrow_markets"][0]["composite_score"], int)

    def test_best_market_format(self):
        result = analyze([self.market])
        self.assertEqual(result["best_borrow_market"], "Aave (USDC)")

    def test_timestamp_is_float(self):
        result = analyze([self.market])
        self.assertIsInstance(result["timestamp"], float)

    def test_filtered_count_zero(self):
        result = analyze([self.market])
        self.assertEqual(result["filtered_out_count"], 0)

    def test_apy_passthrough(self):
        result = analyze([self.market])
        self.assertAlmostEqual(result["borrow_markets"][0]["borrow_apy_pct"], 2.0)


class TestAnalyzeFiltering(unittest.TestCase):

    def test_market_below_min_liquidity_excluded(self):
        m = _market(available_liquidity_usd=50_000)
        result = analyze([m])
        self.assertEqual(len(result["borrow_markets"]), 0)
        self.assertEqual(result["filtered_out_count"], 1)
        self.assertIsNone(result["best_borrow_market"])

    def test_custom_min_liquidity(self):
        m = _market(available_liquidity_usd=500_000)
        result = analyze([m], config={"min_liquidity_usd": 1_000_000})
        self.assertEqual(result["filtered_out_count"], 1)
        self.assertEqual(len(result["borrow_markets"]), 0)

    def test_custom_min_liquidity_passes(self):
        m = _market(available_liquidity_usd=500_000)
        result = analyze([m], config={"min_liquidity_usd": 400_000})
        self.assertEqual(result["filtered_out_count"], 0)
        self.assertEqual(len(result["borrow_markets"]), 1)

    def test_mixed_pass_and_filter(self):
        markets = [
            _market(protocol="Good", available_liquidity_usd=5_000_000),
            _market(protocol="Bad", available_liquidity_usd=10_000),
        ]
        result = analyze(markets)
        self.assertEqual(result["filtered_out_count"], 1)
        self.assertEqual(len(result["borrow_markets"]), 1)
        self.assertEqual(result["borrow_markets"][0]["protocol"], "Good")

    def test_all_filtered_empty_summary(self):
        m = _market(available_liquidity_usd=1_000)
        result = analyze([m])
        self.assertEqual(result["asset_summary"], {})
        self.assertEqual(result["average_composite_score"], 0.0)


class TestAnalyzeMultipleMarkets(unittest.TestCase):

    def test_best_market_is_highest_composite(self):
        markets = [
            _market(protocol="A", borrow_apy_pct=1.0, rate_30d_std_pct=0.05,
                    available_liquidity_usd=100_000_000, utilization_pct=30),
            _market(protocol="B", borrow_apy_pct=15.0, rate_30d_std_pct=4.0,
                    available_liquidity_usd=100_000, utilization_pct=95),
        ]
        result = analyze(markets)
        self.assertIn("A", result["best_borrow_market"])

    def test_average_composite_calculated(self):
        markets = [
            _market(protocol="A", borrow_apy_pct=1.0, rate_30d_std_pct=0.05,
                    available_liquidity_usd=100_000_000, utilization_pct=30),
            _market(protocol="B", borrow_apy_pct=5.0, rate_30d_std_pct=0.5,
                    available_liquidity_usd=1_000_000, utilization_pct=70),
        ]
        result = analyze(markets)
        self.assertGreater(result["average_composite_score"], 0)
        # avg should be between 0 and 100
        self.assertLessEqual(result["average_composite_score"], 100)

    def test_two_markets_same_asset(self):
        markets = [
            _market(protocol="A", borrow_asset="USDC", available_liquidity_usd=5_000_000),
            _market(protocol="B", borrow_asset="USDC", available_liquidity_usd=2_000_000),
        ]
        result = analyze(markets)
        self.assertEqual(result["asset_summary"]["USDC"]["count"], 2)

    def test_two_different_assets(self):
        markets = [
            _market(protocol="A", borrow_asset="USDC", available_liquidity_usd=5_000_000),
            _market(protocol="B", borrow_asset="DAI", available_liquidity_usd=2_000_000),
        ]
        result = analyze(markets)
        self.assertIn("USDC", result["asset_summary"])
        self.assertIn("DAI", result["asset_summary"])


class TestAnalyzeAssetSummary(unittest.TestCase):

    def test_asset_summary_has_count(self):
        result = analyze([_market()])
        asset = result["asset_summary"]["USDC"]
        self.assertEqual(asset["count"], 1)

    def test_asset_summary_best_protocol(self):
        markets = [
            _market(protocol="Better", borrow_apy_pct=1.0, rate_30d_std_pct=0.05,
                    available_liquidity_usd=100_000_000, utilization_pct=20, borrow_asset="USDC"),
            _market(protocol="Worse", borrow_apy_pct=20.0, rate_30d_std_pct=5.0,
                    available_liquidity_usd=100_000, utilization_pct=99, borrow_asset="USDC"),
        ]
        result = analyze(markets, config={"min_liquidity_usd": 50_000})
        self.assertEqual(result["asset_summary"]["USDC"]["best_protocol"], "Better")

    def test_asset_summary_min_apy(self):
        markets = [
            _market(protocol="A", borrow_apy_pct=3.0, available_liquidity_usd=5_000_000),
            _market(protocol="B", borrow_apy_pct=7.0, available_liquidity_usd=5_000_000),
        ]
        result = analyze(markets)
        self.assertAlmostEqual(result["asset_summary"]["USDC"]["min_apy"], 3.0)


class TestAnalyzeLabels(unittest.TestCase):

    def test_optimal_label_assigned(self):
        m = _market(borrow_apy_pct=1.0, rate_30d_std_pct=0.05,
                    available_liquidity_usd=100_000_000, utilization_pct=20)
        result = analyze([m])
        self.assertEqual(result["borrow_markets"][0]["borrow_label"], "OPTIMAL")

    def test_avoid_label_assigned(self):
        m = _market(borrow_apy_pct=25.0, rate_30d_std_pct=10.0,
                    available_liquidity_usd=110_000, utilization_pct=99)
        result = analyze([m])
        self.assertEqual(result["borrow_markets"][0]["borrow_label"], "AVOID")

    def test_good_label(self):
        m = _market(borrow_apy_pct=3.0, rate_30d_std_pct=0.3,
                    available_liquidity_usd=5_000_000, utilization_pct=60)
        result = analyze([m])
        label = result["borrow_markets"][0]["borrow_label"]
        self.assertIn(label, ("OPTIMAL", "GOOD"))


class TestAnalyzeKinkAndTrend(unittest.TestCase):

    def test_kinked_near_kink_true(self):
        m = _market(rate_model="KINKED", utilization_pct=78.0, kink_utilization_pct=80.0,
                    available_liquidity_usd=5_000_000)
        result = analyze([m])
        self.assertTrue(result["borrow_markets"][0]["is_near_kink"])

    def test_kinked_far_from_kink(self):
        m = _market(rate_model="KINKED", utilization_pct=50.0, kink_utilization_pct=80.0,
                    available_liquidity_usd=5_000_000)
        result = analyze([m])
        self.assertFalse(result["borrow_markets"][0]["is_near_kink"])

    def test_variable_not_near_kink(self):
        m = _market(rate_model="VARIABLE", utilization_pct=80.0, kink_utilization_pct=80.0,
                    available_liquidity_usd=5_000_000)
        result = analyze([m])
        self.assertFalse(result["borrow_markets"][0]["is_near_kink"])

    def test_rate_trend_falling(self):
        m = _market(borrow_apy_pct=2.5, rate_30d_avg_pct=3.0,
                    available_liquidity_usd=5_000_000)
        result = analyze([m])
        self.assertEqual(result["borrow_markets"][0]["rate_trend"], "FALLING")

    def test_rate_trend_rising(self):
        m = _market(borrow_apy_pct=3.5, rate_30d_avg_pct=3.0,
                    available_liquidity_usd=5_000_000)
        result = analyze([m])
        self.assertEqual(result["borrow_markets"][0]["rate_trend"], "RISING")

    def test_rate_trend_stable(self):
        m = _market(borrow_apy_pct=3.0, rate_30d_avg_pct=3.0,
                    available_liquidity_usd=5_000_000)
        result = analyze([m])
        self.assertEqual(result["borrow_markets"][0]["rate_trend"], "STABLE")


class TestAnalyzeEdgeCases(unittest.TestCase):

    def test_empty_list(self):
        result = analyze([])
        self.assertEqual(result["borrow_markets"], [])
        self.assertIsNone(result["best_borrow_market"])
        self.assertEqual(result["asset_summary"], {})
        self.assertEqual(result["filtered_out_count"], 0)
        self.assertEqual(result["average_composite_score"], 0.0)

    def test_none_config(self):
        result = analyze([_market()], config=None)
        self.assertIsInstance(result, dict)

    def test_empty_config(self):
        result = analyze([_market()], config={})
        self.assertIsInstance(result, dict)

    def test_composite_never_exceeds_100(self):
        # Artificially perfect market
        m = _market(borrow_apy_pct=0.5, rate_30d_std_pct=0.0,
                    available_liquidity_usd=500_000_000, utilization_pct=10)
        result = analyze([m])
        self.assertLessEqual(result["borrow_markets"][0]["composite_score"], 100)

    def test_composite_is_always_non_negative(self):
        m = _market(borrow_apy_pct=100.0, rate_30d_std_pct=50.0,
                    available_liquidity_usd=110_000, utilization_pct=100)
        result = analyze([m])
        self.assertGreaterEqual(result["borrow_markets"][0]["composite_score"], 0)

    def test_single_market_is_best(self):
        m = _market(protocol="OnlyOne", borrow_asset="ETH")
        result = analyze([m])
        self.assertEqual(result["best_borrow_market"], "OnlyOne (ETH)")

    def test_three_markets_best_selected(self):
        markets = [
            _market(protocol="A", borrow_apy_pct=25.0, rate_30d_std_pct=8.0,
                    available_liquidity_usd=110_000, utilization_pct=99),
            _market(protocol="B", borrow_apy_pct=1.0, rate_30d_std_pct=0.05,
                    available_liquidity_usd=200_000_000, utilization_pct=10),
            _market(protocol="C", borrow_apy_pct=5.0, rate_30d_std_pct=0.5,
                    available_liquidity_usd=5_000_000, utilization_pct=60),
        ]
        result = analyze(markets)
        self.assertIn("B", result["best_borrow_market"])

    def test_scores_are_int(self):
        result = analyze([_market()])
        m = result["borrow_markets"][0]
        for key in ("effective_cost_score", "rate_stability_score",
                    "liquidity_score", "utilization_risk_score", "composite_score"):
            self.assertIsInstance(m[key], int, f"{key} should be int")

    def test_recommendation_non_empty(self):
        result = analyze([_market()])
        self.assertGreater(len(result["borrow_markets"][0]["recommendation"]), 0)

    def test_is_near_kink_bool(self):
        result = analyze([_market()])
        self.assertIsInstance(result["borrow_markets"][0]["is_near_kink"], bool)

    def test_multiple_filter_and_keep(self):
        markets = [
            _market(protocol=f"P{i}", available_liquidity_usd=200_000 if i < 3 else 50_000)
            for i in range(6)
        ]
        result = analyze(markets)
        self.assertEqual(result["filtered_out_count"], 3)
        self.assertEqual(len(result["borrow_markets"]), 3)


if __name__ == "__main__":
    unittest.main()
