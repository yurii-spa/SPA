"""
Tests for MP-933 DeFiLiquidStakingPremiumAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_liquid_staking_premium_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure the repo root is on the path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_liquid_staking_premium_analyzer import (
    DeFiLiquidStakingPremiumAnalyzer,
    _clamp,
    _grade_from_score,
    _classify,
    _atomic_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _token(
    name="stETH",
    market_price_usd=1.00,
    nav_usd=1.00,
    base_staking_apy_pct=4.0,
    redemption_days=7.0,
    can_redeem=True,
    tvl_usd=1_000_000.0,
):
    return {
        "name": name,
        "market_price_usd": market_price_usd,
        "nav_usd": nav_usd,
        "base_staking_apy_pct": base_staking_apy_pct,
        "redemption_days": redemption_days,
        "can_redeem": can_redeem,
        "tvl_usd": tvl_usd,
    }


NO_LOG = {"write_log": False}


# ===========================================================================
# 1. Instantiation and structure
# ===========================================================================

class TestInstantiation(unittest.TestCase):
    def test_instantiation(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        self.assertIsNotNone(a)

    def test_analyze_returns_dict(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        self.assertIsInstance(a.analyze([_token()], NO_LOG), dict)

    def test_top_level_keys(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        out = a.analyze([_token()], NO_LOG)
        for key in ("results", "aggregates", "timestamp"):
            self.assertIn(key, out)

    def test_results_length(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        out = a.analyze([_token(), _token(name="rETH")], NO_LOG)
        self.assertEqual(len(out["results"]), 2)

    def test_per_token_keys(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token()], NO_LOG)["results"][0]
        for key in (
            "name", "market_price_usd", "nav_usd", "premium_discount_pct",
            "base_staking_apy_pct", "discount_capture_apy_pct",
            "effective_buy_apy_pct", "redemption_days", "can_redeem",
            "buy_score", "classification", "grade", "flags",
        ):
            self.assertIn(key, r)

    def test_symbol_fallback_for_name(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([{"symbol": "weETH", "market_price_usd": 1.0, "nav_usd": 1.0}], NO_LOG)
        self.assertEqual(r["results"][0]["name"], "weETH")

    def test_unknown_name(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([{"market_price_usd": 1.0, "nav_usd": 1.0}], NO_LOG)
        self.assertEqual(r["results"][0]["name"], "unknown")

    def test_timestamp_float(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        self.assertIsInstance(a.analyze([_token()], NO_LOG)["timestamp"], float)


# ===========================================================================
# 2. _clamp helper
# ===========================================================================

class TestClamp(unittest.TestCase):
    def test_within(self):
        self.assertEqual(_clamp(50.0, 0.0, 100.0), 50.0)

    def test_below(self):
        self.assertEqual(_clamp(-10.0, 0.0, 100.0), 0.0)

    def test_above(self):
        self.assertEqual(_clamp(150.0, 0.0, 100.0), 100.0)

    def test_low_boundary(self):
        self.assertEqual(_clamp(0.0, 0.0, 100.0), 0.0)

    def test_high_boundary(self):
        self.assertEqual(_clamp(100.0, 0.0, 100.0), 100.0)


# ===========================================================================
# 3. Grade & classification
# ===========================================================================

class TestGrade(unittest.TestCase):
    def test_a(self):
        self.assertEqual(_grade_from_score(90.0), "A")

    def test_a_boundary(self):
        self.assertEqual(_grade_from_score(85.0), "A")

    def test_b(self):
        self.assertEqual(_grade_from_score(75.0), "B")

    def test_b_boundary(self):
        self.assertEqual(_grade_from_score(70.0), "B")

    def test_c(self):
        self.assertEqual(_grade_from_score(60.0), "C")

    def test_c_boundary(self):
        self.assertEqual(_grade_from_score(55.0), "C")

    def test_d(self):
        self.assertEqual(_grade_from_score(45.0), "D")

    def test_d_boundary(self):
        self.assertEqual(_grade_from_score(40.0), "D")

    def test_f(self):
        self.assertEqual(_grade_from_score(30.0), "F")


class TestClassify(unittest.TestCase):
    def test_deep_discount(self):
        self.assertEqual(_classify(-4.0), "DEEP_DISCOUNT")

    def test_deep_discount_boundary(self):
        self.assertEqual(_classify(-3.0), "DEEP_DISCOUNT")

    def test_discount(self):
        self.assertEqual(_classify(-1.0), "DISCOUNT")

    def test_discount_boundary(self):
        self.assertEqual(_classify(-0.5), "DISCOUNT")

    def test_fair(self):
        self.assertEqual(_classify(0.0), "FAIR")

    def test_fair_upper(self):
        self.assertEqual(_classify(0.4), "FAIR")

    def test_premium(self):
        self.assertEqual(_classify(1.0), "PREMIUM")

    def test_premium_upper(self):
        self.assertEqual(_classify(1.9), "PREMIUM")

    def test_overpriced(self):
        self.assertEqual(_classify(3.0), "OVERPRICED")

    def test_overpriced_boundary(self):
        self.assertEqual(_classify(2.0), "OVERPRICED")


# ===========================================================================
# 4. Premium / discount calculation
# ===========================================================================

class TestPremiumDiscount(unittest.TestCase):
    def test_at_par(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=1.0, nav_usd=1.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["premium_discount_pct"], 0.0)

    def test_discount(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=0.95, nav_usd=1.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["premium_discount_pct"], -5.0)

    def test_premium(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=1.03, nav_usd=1.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["premium_discount_pct"], 3.0)

    def test_classification_discount(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=0.96, nav_usd=1.0)], NO_LOG)["results"][0]
        self.assertEqual(r["classification"], "DEEP_DISCOUNT")

    def test_classification_fair(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=1.001, nav_usd=1.0)], NO_LOG)["results"][0]
        self.assertEqual(r["classification"], "FAIR")

    def test_classification_premium(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=1.015, nav_usd=1.0)], NO_LOG)["results"][0]
        self.assertEqual(r["classification"], "PREMIUM")


# ===========================================================================
# 5. Discount-capture APY & effective buy APY
# ===========================================================================

class TestCaptureAPY(unittest.TestCase):
    def test_discount_capture_positive(self):
        # buy 0.90, nav 1.0, 365 day redemption -> gain (1/0.9-1)=0.1111 annualized x1
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=0.90, nav_usd=1.0,
                              redemption_days=365.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["discount_capture_apy_pct"], (1.0 / 0.9 - 1.0) * 100.0, places=4)

    def test_fast_redemption_amplifies_capture(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=0.99, nav_usd=1.0,
                              redemption_days=7.0)], NO_LOG)["results"][0]
        gain = (1.0 / 0.99 - 1.0)
        expected = gain * (365.0 / 7.0) * 100.0
        self.assertAlmostEqual(r["discount_capture_apy_pct"], round(expected, 6), places=3)

    def test_no_redeem_zero_capture(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=0.90, nav_usd=1.0,
                              can_redeem=False)], NO_LOG)["results"][0]
        self.assertEqual(r["discount_capture_apy_pct"], 0.0)

    def test_premium_negative_capture(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=1.05, nav_usd=1.0,
                              redemption_days=365.0)], NO_LOG)["results"][0]
        self.assertLess(r["discount_capture_apy_pct"], 0.0)

    def test_effective_buy_apy_sum(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=0.90, nav_usd=1.0,
                              base_staking_apy_pct=4.0, redemption_days=365.0)], NO_LOG)["results"][0]
        expected = round(4.0 + r["discount_capture_apy_pct"], 6)
        self.assertAlmostEqual(r["effective_buy_apy_pct"], expected)

    def test_effective_apy_at_par_equals_base(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=1.0, nav_usd=1.0,
                              base_staking_apy_pct=5.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["effective_buy_apy_pct"], 5.0)


# ===========================================================================
# 6. Buy score
# ===========================================================================

class TestBuyScore(unittest.TestCase):
    def test_par_score_baseline(self):
        # premium 0, redemption 7 (not <=3) -> score 50
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=1.0, nav_usd=1.0,
                              redemption_days=7.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["buy_score"], 50.0)

    def test_discount_raises_score(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=0.97, nav_usd=1.0,
                              redemption_days=7.0)], NO_LOG)["results"][0]
        # disc -3 -> 50 - (-3)*10 = 80
        self.assertAlmostEqual(r["buy_score"], 80.0)

    def test_premium_lowers_score(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=1.03, nav_usd=1.0,
                              redemption_days=7.0)], NO_LOG)["results"][0]
        # premium 3 -> 50 - 30 = 20
        self.assertAlmostEqual(r["buy_score"], 20.0)

    def test_fast_redemption_bonus(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=1.0, nav_usd=1.0,
                              redemption_days=2.0)], NO_LOG)["results"][0]
        # 50 + 5 bonus
        self.assertAlmostEqual(r["buy_score"], 55.0)

    def test_no_redeem_penalty(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=1.0, nav_usd=1.0,
                              redemption_days=7.0, can_redeem=False)], NO_LOG)["results"][0]
        # 50 - 15
        self.assertAlmostEqual(r["buy_score"], 35.0)

    def test_slow_redemption_penalty(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=1.0, nav_usd=1.0,
                              redemption_days=30.0)], NO_LOG)["results"][0]
        # 50 - 10
        self.assertAlmostEqual(r["buy_score"], 40.0)

    def test_score_clamped_0_100(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=0.50, nav_usd=1.0,
                              redemption_days=2.0)], NO_LOG)["results"][0]
        self.assertLessEqual(r["buy_score"], 100.0)
        self.assertGreaterEqual(r["buy_score"], 0.0)

    def test_high_score_grades_a(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=0.96, nav_usd=1.0,
                              redemption_days=2.0)], NO_LOG)["results"][0]
        self.assertEqual(r["grade"], "A")


# ===========================================================================
# 7. Flags
# ===========================================================================

class TestFlags(unittest.TestCase):
    def test_insufficient_data_zero_price(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=0.0, nav_usd=1.0)], NO_LOG)["results"][0]
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_data_zero_nav(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=1.0, nav_usd=0.0)], NO_LOG)["results"][0]
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_data_only_flag(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=0.0, nav_usd=0.0)], NO_LOG)["results"][0]
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_depeg_risk_flag(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=0.95, nav_usd=1.0)], NO_LOG)["results"][0]
        self.assertIn("DEPEG_RISK", r["flags"])

    def test_deep_discount_flag(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=0.975, nav_usd=1.0)], NO_LOG)["results"][0]
        self.assertIn("DEEP_DISCOUNT", r["flags"])

    def test_trading_premium_flag(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=1.02, nav_usd=1.0)], NO_LOG)["results"][0]
        self.assertIn("TRADING_PREMIUM", r["flags"])

    def test_slow_redemption_flag(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(redemption_days=30.0)], NO_LOG)["results"][0]
        self.assertIn("SLOW_REDEMPTION", r["flags"])

    def test_no_redemption_flag(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(can_redeem=False)], NO_LOG)["results"][0]
        self.assertIn("NO_REDEMPTION", r["flags"])

    def test_arbitrage_opportunity_flag(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=0.98, nav_usd=1.0,
                              can_redeem=True, redemption_days=5.0)], NO_LOG)["results"][0]
        self.assertIn("ARBITRAGE_OPPORTUNITY", r["flags"])

    def test_no_arbitrage_when_slow(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=0.98, nav_usd=1.0,
                              can_redeem=True, redemption_days=20.0)], NO_LOG)["results"][0]
        self.assertNotIn("ARBITRAGE_OPPORTUNITY", r["flags"])

    def test_no_arbitrage_when_cant_redeem(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=0.98, nav_usd=1.0,
                              can_redeem=False, redemption_days=5.0)], NO_LOG)["results"][0]
        self.assertNotIn("ARBITRAGE_OPPORTUNITY", r["flags"])

    def test_clean_token_minimal_flags(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=1.0, nav_usd=1.0,
                              redemption_days=7.0, can_redeem=True)], NO_LOG)["results"][0]
        self.assertEqual(r["flags"], [])

    def test_flags_is_list(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token()], NO_LOG)["results"][0]
        self.assertIsInstance(r["flags"], list)


# ===========================================================================
# 8. Aggregates
# ===========================================================================

class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.a = DeFiLiquidStakingPremiumAnalyzer()
        self.tokens = [
            _token(name="Cheap", market_price_usd=0.95, nav_usd=1.0, redemption_days=5.0),
            _token(name="Par", market_price_usd=1.0, nav_usd=1.0),
            _token(name="Expensive", market_price_usd=1.05, nav_usd=1.0),
        ]
        self.out = self.a.analyze(self.tokens, NO_LOG)
        self.agg = self.out["aggregates"]

    def test_aggregate_keys(self):
        for key in (
            "best_buy_opportunity", "most_overpriced",
            "average_premium_discount_pct", "average_effective_buy_apy_pct",
            "deep_discount_count", "arbitrage_opportunity_count",
        ):
            self.assertIn(key, self.agg)

    def test_best_buy_opportunity(self):
        self.assertEqual(self.agg["best_buy_opportunity"], "Cheap")

    def test_most_overpriced(self):
        self.assertEqual(self.agg["most_overpriced"], "Expensive")

    def test_deep_discount_count(self):
        self.assertEqual(self.agg["deep_discount_count"], 1)

    def test_arbitrage_count(self):
        self.assertEqual(self.agg["arbitrage_opportunity_count"], 1)

    def test_average_premium(self):
        expected = (-5.0 + 0.0 + 5.0) / 3
        self.assertAlmostEqual(self.agg["average_premium_discount_pct"], round(expected, 6))


# ===========================================================================
# 9. Empty input
# ===========================================================================

class TestEmptyInput(unittest.TestCase):
    def test_empty_results(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        self.assertEqual(a.analyze([], NO_LOG)["results"], [])

    def test_empty_aggregates(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        agg = a.analyze([], NO_LOG)["aggregates"]
        self.assertIsNone(agg["best_buy_opportunity"])
        self.assertIsNone(agg["most_overpriced"])
        self.assertEqual(agg["deep_discount_count"], 0)
        self.assertEqual(agg["arbitrage_opportunity_count"], 0)
        self.assertEqual(agg["average_premium_discount_pct"], 0.0)


# ===========================================================================
# 10. Input validation & defaults
# ===========================================================================

class TestInputValidation(unittest.TestCase):
    def test_non_list_raises(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        with self.assertRaises(TypeError):
            a.analyze("nope", NO_LOG)

    def test_dict_raises(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        with self.assertRaises(TypeError):
            a.analyze({"name": "x"}, NO_LOG)

    def test_default_redemption_days(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([{"name": "x", "market_price_usd": 1.0, "nav_usd": 1.0}], NO_LOG)["results"][0]
        self.assertEqual(r["redemption_days"], 7.0)

    def test_default_can_redeem_true(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([{"name": "x", "market_price_usd": 1.0, "nav_usd": 1.0}], NO_LOG)["results"][0]
        self.assertTrue(r["can_redeem"])

    def test_default_base_apy_zero(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([{"name": "x", "market_price_usd": 1.0, "nav_usd": 1.0}], NO_LOG)["results"][0]
        self.assertEqual(r["base_staking_apy_pct"], 0.0)


# ===========================================================================
# 11. Logging / persistence
# ===========================================================================

class TestLogging(unittest.TestCase):
    def test_no_log_disabled(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            a.analyze([_token()], {"write_log": False, "log_path": path})
            self.assertFalse(os.path.exists(path))

    def test_log_written(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            a.analyze([_token()], {"write_log": True, "log_path": path})
            self.assertTrue(os.path.exists(path))

    def test_log_entry_fields(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            a.analyze([_token()], {"write_log": True, "log_path": path})
            with open(path) as fh:
                entry = json.load(fh)[0]
            self.assertIn("timestamp", entry)
            self.assertIn("token_count", entry)
            self.assertIn("aggregates", entry)

    def test_ring_buffer_cap(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for _ in range(103):
                a.analyze([_token()], {"write_log": True, "log_path": path})
            with open(path) as fh:
                self.assertEqual(len(json.load(fh)), 100)

    def test_atomic_log_direct(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _atomic_log(path, {"x": 1})
            _atomic_log(path, {"x": 2})
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 2)

    def test_atomic_log_corrupt_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as fh:
                fh.write("{garbage")
            _atomic_log(path, {"x": 1})
            with open(path) as fh:
                self.assertEqual(json.load(fh), [{"x": 1}])


# ===========================================================================
# 12. Determinism
# ===========================================================================

class TestDeterminism(unittest.TestCase):
    def test_repeatable(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r1 = a.analyze([_token()], NO_LOG)["results"]
        r2 = a.analyze([_token()], NO_LOG)["results"]
        self.assertEqual(r1, r2)

    def test_premium_rounded(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        r = a.analyze([_token(market_price_usd=1.0, nav_usd=3.0)], NO_LOG)["results"][0]
        expected = round((1.0 - 3.0) / 3.0 * 100.0, 6)
        self.assertEqual(r["premium_discount_pct"], expected)

    def test_independent_tokens(self):
        a = DeFiLiquidStakingPremiumAnalyzer()
        out = a.analyze([
            _token(name="A", market_price_usd=0.95, nav_usd=1.0, redemption_days=2.0),
            _token(name="B", market_price_usd=1.05, nav_usd=1.0),
        ], NO_LOG)
        self.assertGreater(out["results"][0]["buy_score"], out["results"][1]["buy_score"])


if __name__ == "__main__":
    unittest.main()
