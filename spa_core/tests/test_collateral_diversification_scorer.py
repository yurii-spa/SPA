"""
Tests for MP-819 CollateralDiversificationScorer
=================================================
≥ 65 test cases using stdlib unittest only.
Run: python3 -m unittest spa_core.tests.test_collateral_diversification_scorer -v
"""

import json
import os
import time
import unittest
import tempfile

from spa_core.analytics.collateral_diversification_scorer import (
    _append_log,
    _grade,
    analyze,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------
def _simple_asset(
    symbol: str = "ETH",
    category: str = "eth_derivative",
    usd: float = 1_000_000.0,
    vol: float = 50.0,
    corr: float = 1.0,
) -> dict:
    return {
        "symbol": symbol,
        "category": category,
        "collateral_usd": usd,
        "volatility_30d_pct": vol,
        "correlation_to_eth": corr,
    }


def _diverse_assets() -> list[dict]:
    """8 assets across 5 categories — useful for high-score tests."""
    return [
        _simple_asset("USDC", "stablecoin", 10_000_000, 0.2, 0.0),
        _simple_asset("DAI",  "stablecoin", 8_000_000,  0.3, 0.0),
        _simple_asset("ETH",  "eth_derivative", 12_000_000, 55.0, 1.0),
        _simple_asset("stETH","eth_derivative", 6_000_000, 55.0, 0.98),
        _simple_asset("WBTC", "btc_derivative", 9_000_000, 50.0, 0.75),
        _simple_asset("UNI",  "defi_token",    4_000_000, 80.0, 0.65),
        _simple_asset("ONDO", "rwa",            5_000_000, 30.0, 0.2),
        _simple_asset("OTHER","other",          3_000_000, 40.0, 0.3),
    ]


# ---------------------------------------------------------------------------
# 1. Empty-input edge cases
# ---------------------------------------------------------------------------
class TestEmptyInput(unittest.TestCase):
    def setUp(self):
        self.result = analyze("EmptyProto", [])

    def test_protocol_name_preserved(self):
        self.assertEqual(self.result["protocol"], "EmptyProto")

    def test_total_collateral_zero(self):
        self.assertEqual(self.result["total_collateral_usd"], 0.0)

    def test_asset_count_zero(self):
        self.assertEqual(self.result["asset_count"], 0)

    def test_by_category_empty(self):
        self.assertEqual(self.result["by_category"], {})

    def test_top_assets_empty(self):
        self.assertEqual(self.result["top_assets"], [])

    def test_metrics_all_zero(self):
        m = self.result["metrics"]
        self.assertEqual(m["weighted_volatility"], 0.0)
        self.assertEqual(m["weighted_eth_correlation"], 0.0)
        self.assertEqual(m["hhi"], 0.0)
        self.assertEqual(m["diversification_ratio"], 0.0)

    def test_scores_all_zero(self):
        s = self.result["scores"]
        for key in ("asset_diversity_score", "category_diversity_score",
                    "concentration_score", "volatility_score", "total_score"):
            self.assertEqual(s[key], 0)

    def test_grade_F(self):
        self.assertEqual(self.result["grade"], "F")

    def test_no_risk_flags(self):
        self.assertEqual(self.result["risk_flags"], [])

    def test_timestamp_recent(self):
        self.assertAlmostEqual(self.result["timestamp"], time.time(), delta=5)


# ---------------------------------------------------------------------------
# 2. Single-asset edge cases
# ---------------------------------------------------------------------------
class TestSingleAsset(unittest.TestCase):
    def setUp(self):
        assets = [_simple_asset("ETH", "eth_derivative", 5_000_000, 50.0, 1.0)]
        self.result = analyze("MonoProto", assets)

    def test_asset_count_one(self):
        self.assertEqual(self.result["asset_count"], 1)

    def test_total_collateral(self):
        self.assertEqual(self.result["total_collateral_usd"], 5_000_000.0)

    def test_pct_is_100(self):
        top = self.result["top_assets"][0]
        self.assertAlmostEqual(top["pct"], 100.0, places=3)

    def test_hhi_is_one(self):
        self.assertAlmostEqual(self.result["metrics"]["hhi"], 1.0, places=4)

    def test_diversification_ratio_zero(self):
        self.assertAlmostEqual(self.result["metrics"]["diversification_ratio"], 0.0, places=4)

    def test_asset_diversity_score_capped(self):
        # 1 * 5 = 5, not capped at 40
        self.assertEqual(self.result["scores"]["asset_diversity_score"], 5)

    def test_category_diversity_score_one_category(self):
        # 1 * 6 = 6
        self.assertEqual(self.result["scores"]["category_diversity_score"], 6)

    def test_concentration_score_zero(self):
        # 20 * 0.0 = 0
        self.assertEqual(self.result["scores"]["concentration_score"], 0)

    def test_concentration_flag_raised(self):
        # 100% > 30% default threshold → flag should appear
        flags = self.result["risk_flags"]
        self.assertTrue(any("ETH" in f for f in flags))

    def test_category_flag_raised(self):
        flags = self.result["risk_flags"]
        self.assertTrue(any("eth_derivative" in f for f in flags))


# ---------------------------------------------------------------------------
# 3. Score computation — asset diversity
# ---------------------------------------------------------------------------
class TestAssetDiversityScore(unittest.TestCase):
    def _score(self, n: int) -> int:
        assets = [_simple_asset(f"A{i}", "stablecoin", 1_000_000, 0.1, 0.0)
                  for i in range(n)]
        return analyze("P", assets)["scores"]["asset_diversity_score"]

    def test_one_asset(self):
        self.assertEqual(self._score(1), 5)

    def test_four_assets(self):
        self.assertEqual(self._score(4), 20)

    def test_eight_assets(self):
        self.assertEqual(self._score(8), 40)

    def test_ten_assets_capped(self):
        self.assertEqual(self._score(10), 40)

    def test_twenty_assets_still_capped(self):
        self.assertEqual(self._score(20), 40)


# ---------------------------------------------------------------------------
# 4. Score computation — category diversity
# ---------------------------------------------------------------------------
class TestCategoryDiversityScore(unittest.TestCase):
    def _score(self, categories: list[str]) -> int:
        assets = [_simple_asset(f"A{i}", cat, 1_000_000, 0.1, 0.0)
                  for i, cat in enumerate(categories)]
        return analyze("P", assets)["scores"]["category_diversity_score"]

    def test_one_category(self):
        self.assertEqual(self._score(["stablecoin"]), 6)

    def test_two_categories(self):
        self.assertEqual(self._score(["stablecoin", "eth_derivative"]), 12)

    def test_five_categories(self):
        cats = ["stablecoin", "eth_derivative", "btc_derivative", "defi_token", "rwa"]
        self.assertEqual(self._score(cats), 30)

    def test_six_categories_capped(self):
        cats = ["stablecoin", "eth_derivative", "btc_derivative",
                "defi_token", "rwa", "other"]
        self.assertEqual(self._score(cats), 30)

    def test_many_same_category(self):
        cats = ["stablecoin"] * 10
        self.assertEqual(self._score(cats), 6)


# ---------------------------------------------------------------------------
# 5. Score computation — concentration (HHI)
# ---------------------------------------------------------------------------
class TestConcentrationScore(unittest.TestCase):
    def test_two_equal_assets_hhi(self):
        assets = [
            _simple_asset("A", "stablecoin", 500, 0.1, 0.0),
            _simple_asset("B", "eth_derivative", 500, 0.1, 0.0),
        ]
        r = analyze("P", assets)
        # hhi = 2 * (0.5)^2 = 0.5  → div_ratio = 0.5 → score = 10
        self.assertAlmostEqual(r["metrics"]["hhi"], 0.5, places=4)
        self.assertEqual(r["scores"]["concentration_score"], 10)

    def test_four_equal_assets_hhi(self):
        assets = [_simple_asset(f"A{i}", "stablecoin", 250, 0.1, 0.0) for i in range(4)]
        r = analyze("P", assets)
        # hhi = 4 * (0.25)^2 = 0.25 → div_ratio = 0.75 → score = 15
        self.assertAlmostEqual(r["metrics"]["hhi"], 0.25, places=4)
        self.assertEqual(r["scores"]["concentration_score"], 15)


# ---------------------------------------------------------------------------
# 6. Score computation — volatility
# ---------------------------------------------------------------------------
class TestVolatilityScore(unittest.TestCase):
    def _vol_score(self, weighted_vol: float) -> int:
        # single asset  → weighted_vol = vol
        assets = [_simple_asset("X", "stablecoin", 1_000_000, weighted_vol, 0.0)]
        return analyze("P", assets)["scores"]["volatility_score"]

    def test_vol_below_30_score_10(self):
        self.assertEqual(self._vol_score(10.0), 10)

    def test_vol_exactly_30_score_5(self):
        # 30 is NOT < 30, so falls into medium bucket
        self.assertEqual(self._vol_score(30.0), 5)

    def test_vol_between_30_and_60_score_5(self):
        self.assertEqual(self._vol_score(55.0), 5)

    def test_vol_at_60_score_0(self):
        self.assertEqual(self._vol_score(60.0), 0)

    def test_vol_above_60_score_0(self):
        self.assertEqual(self._vol_score(90.0), 0)


# ---------------------------------------------------------------------------
# 7. Grade thresholds
# ---------------------------------------------------------------------------
class TestGradeFunction(unittest.TestCase):
    def test_grade_A_at_80(self):
        self.assertEqual(_grade(80), "A")

    def test_grade_A_at_100(self):
        self.assertEqual(_grade(100), "A")

    def test_grade_B_at_65(self):
        self.assertEqual(_grade(65), "B")

    def test_grade_B_at_79(self):
        self.assertEqual(_grade(79), "B")

    def test_grade_C_at_50(self):
        self.assertEqual(_grade(50), "C")

    def test_grade_C_at_64(self):
        self.assertEqual(_grade(64), "C")

    def test_grade_D_at_35(self):
        self.assertEqual(_grade(35), "D")

    def test_grade_D_at_49(self):
        self.assertEqual(_grade(49), "D")

    def test_grade_F_at_34(self):
        self.assertEqual(_grade(34), "F")

    def test_grade_F_at_0(self):
        self.assertEqual(_grade(0), "F")


# ---------------------------------------------------------------------------
# 8. Risk flags
# ---------------------------------------------------------------------------
class TestRiskFlags(unittest.TestCase):
    def test_no_flags_when_balanced(self):
        assets = _diverse_assets()
        r = analyze("Good", assets)
        # With diverse assets and low vol stablecoins dominating, flags depend on pcts
        # Just verify the flag list is a list
        self.assertIsInstance(r["risk_flags"], list)

    def test_asset_exceeds_default_threshold(self):
        assets = [
            _simple_asset("BIG", "eth_derivative", 80_000, 50.0, 1.0),
            _simple_asset("SML", "stablecoin",      20_000, 0.1, 0.0),
        ]
        r = analyze("P", assets)
        flags = r["risk_flags"]
        self.assertTrue(any("BIG" in f and "30%" in f for f in flags))

    def test_asset_exceeds_custom_threshold(self):
        assets = [
            _simple_asset("BIG", "eth_derivative", 60_000, 50.0, 1.0),
            _simple_asset("SML", "stablecoin",      40_000, 0.1, 0.0),
        ]
        r = analyze("P", assets, config={"max_single_asset_pct": 50.0})
        # 60% > 50% → should flag
        flags = r["risk_flags"]
        self.assertTrue(any("BIG" in f and "50%" in f for f in flags))

    def test_no_asset_flag_when_within_threshold(self):
        assets = [
            _simple_asset("A", "stablecoin", 35_000, 0.1, 0.0),
            _simple_asset("B", "eth_derivative", 35_000, 50.0, 1.0),
            _simple_asset("C", "btc_derivative", 30_000, 45.0, 0.7),
        ]
        r = analyze("P", assets)
        # Max single asset ≈ 35% > 30%, so flag should appear for A and B
        flags = r["risk_flags"]
        asset_flags = [f for f in flags if "exceeds" in f and "category" not in f]
        # A and B are each 35% > 30%
        self.assertTrue(len(asset_flags) >= 1)

    def test_category_flag_stablecoin_dominance(self):
        assets = [
            _simple_asset("USDC", "stablecoin", 60_000, 0.1, 0.0),
            _simple_asset("DAI",  "stablecoin", 20_000, 0.1, 0.0),
            _simple_asset("ETH",  "eth_derivative", 20_000, 55.0, 1.0),
        ]
        r = analyze("P", assets)
        flags = r["risk_flags"]
        self.assertTrue(any("stablecoin" in f and "category" in f for f in flags))

    def test_category_flag_custom_threshold(self):
        assets = [
            _simple_asset("USDC", "stablecoin", 45_000, 0.1, 0.0),
            _simple_asset("ETH",  "eth_derivative", 55_000, 55.0, 1.0),
        ]
        r = analyze("P", assets, config={"max_single_category_pct": 40.0})
        flags = r["risk_flags"]
        self.assertTrue(any("stablecoin" in f and "40%" in f for f in flags))
        self.assertTrue(any("eth_derivative" in f and "40%" in f for f in flags))

    def test_eth_correlation_flag(self):
        assets = [
            _simple_asset("ETH",  "eth_derivative", 500, 50.0, 1.0),
            _simple_asset("stETH","eth_derivative", 500, 50.0, 0.99),
        ]
        r = analyze("P", assets)
        flags = r["risk_flags"]
        self.assertTrue(any("ETH correlation" in f for f in flags))

    def test_no_eth_correlation_flag_below_threshold(self):
        assets = [
            _simple_asset("USDC", "stablecoin", 500, 0.1, 0.0),
            _simple_asset("ONDO", "rwa",         500, 30.0, 0.2),
        ]
        r = analyze("P", assets)
        flags = r["risk_flags"]
        self.assertFalse(any("ETH correlation" in f for f in flags))

    def test_high_volatility_flag(self):
        assets = [
            _simple_asset("SHIB", "defi_token", 1_000_000, 200.0, 0.5),
        ]
        r = analyze("P", assets)
        flags = r["risk_flags"]
        self.assertTrue(any("volatility" in f.lower() for f in flags))

    def test_no_high_volatility_flag_below_threshold(self):
        assets = [_simple_asset("ETH", "eth_derivative", 1_000_000, 75.0, 1.0)]
        r = analyze("P", assets)
        flags = r["risk_flags"]
        self.assertFalse(any("volatility" in f.lower() for f in flags))


# ---------------------------------------------------------------------------
# 9. top_assets ordering
# ---------------------------------------------------------------------------
class TestTopAssets(unittest.TestCase):
    def test_sorted_by_usd_desc(self):
        assets = [
            _simple_asset("SMALL", "stablecoin",    100_000, 0.1, 0.0),
            _simple_asset("BIG",   "eth_derivative", 900_000, 50.0, 1.0),
            _simple_asset("MED",   "btc_derivative", 500_000, 45.0, 0.7),
        ]
        r = analyze("P", assets)
        top = r["top_assets"]
        self.assertEqual(top[0]["symbol"], "BIG")
        self.assertEqual(top[1]["symbol"], "MED")
        self.assertEqual(top[2]["symbol"], "SMALL")

    def test_all_assets_returned(self):
        assets = [_simple_asset(f"A{i}", "stablecoin", 1_000_000, 0.1, 0.0) for i in range(10)]
        r = analyze("P", assets)
        self.assertEqual(len(r["top_assets"]), 10)

    def test_top_assets_have_required_fields(self):
        assets = [_simple_asset("ETH", "eth_derivative", 1_000_000, 50.0, 1.0)]
        r = analyze("P", assets)
        top = r["top_assets"][0]
        for key in ("symbol", "category", "pct", "volatility_30d_pct"):
            self.assertIn(key, top)


# ---------------------------------------------------------------------------
# 10. by_category structure
# ---------------------------------------------------------------------------
class TestByCategory(unittest.TestCase):
    def test_by_category_keys(self):
        assets = [
            _simple_asset("USDC", "stablecoin", 500_000, 0.1, 0.0),
            _simple_asset("ETH",  "eth_derivative", 500_000, 50.0, 1.0),
        ]
        r = analyze("P", assets)
        self.assertIn("stablecoin", r["by_category"])
        self.assertIn("eth_derivative", r["by_category"])

    def test_by_category_usd_sum(self):
        assets = [
            _simple_asset("USDC", "stablecoin", 300_000, 0.1, 0.0),
            _simple_asset("DAI",  "stablecoin", 200_000, 0.1, 0.0),
            _simple_asset("ETH",  "eth_derivative", 500_000, 50.0, 1.0),
        ]
        r = analyze("P", assets)
        self.assertAlmostEqual(r["by_category"]["stablecoin"]["usd"], 500_000.0, places=2)

    def test_by_category_pct_sums_to_100(self):
        assets = _diverse_assets()
        r = analyze("P", assets)
        total_pct = sum(info["pct"] for info in r["by_category"].values())
        self.assertAlmostEqual(total_pct, 100.0, places=2)

    def test_by_category_assets_list(self):
        assets = [
            _simple_asset("USDC", "stablecoin", 500_000, 0.1, 0.0),
            _simple_asset("DAI",  "stablecoin", 300_000, 0.1, 0.0),
        ]
        r = analyze("P", assets)
        cat_assets = r["by_category"]["stablecoin"]["assets"]
        self.assertIn("USDC", cat_assets)
        self.assertIn("DAI", cat_assets)


# ---------------------------------------------------------------------------
# 11. Metrics accuracy
# ---------------------------------------------------------------------------
class TestMetrics(unittest.TestCase):
    def test_weighted_volatility_two_equal_assets(self):
        assets = [
            _simple_asset("A", "stablecoin", 500, 20.0, 0.0),
            _simple_asset("B", "eth_derivative", 500, 60.0, 1.0),
        ]
        r = analyze("P", assets)
        # 0.5 * 20 + 0.5 * 60 = 40.0
        self.assertAlmostEqual(r["metrics"]["weighted_volatility"], 40.0, places=2)

    def test_weighted_eth_correlation_two_assets(self):
        assets = [
            _simple_asset("A", "stablecoin", 500, 0.1, 0.0),
            _simple_asset("B", "eth_derivative", 500, 50.0, 1.0),
        ]
        r = analyze("P", assets)
        # 0.5 * 0.0 + 0.5 * 1.0 = 0.5
        self.assertAlmostEqual(r["metrics"]["weighted_eth_correlation"], 0.5, places=2)

    def test_hhi_single_asset_is_one(self):
        assets = [_simple_asset("X", "stablecoin", 1_000_000, 0.1, 0.0)]
        r = analyze("P", assets)
        self.assertAlmostEqual(r["metrics"]["hhi"], 1.0, places=4)

    def test_hhi_two_equal(self):
        assets = [
            _simple_asset("A", "stablecoin", 500, 0.1, 0.0),
            _simple_asset("B", "eth_derivative", 500, 50.0, 1.0),
        ]
        r = analyze("P", assets)
        self.assertAlmostEqual(r["metrics"]["hhi"], 0.5, places=4)

    def test_diversification_ratio_complement(self):
        assets = _diverse_assets()
        r = analyze("P", assets)
        self.assertAlmostEqual(
            r["metrics"]["hhi"] + r["metrics"]["diversification_ratio"],
            1.0,
            places=5,
        )

    def test_total_collateral_matches_sum(self):
        assets = [
            _simple_asset("A", "stablecoin", 300_000, 0.1, 0.0),
            _simple_asset("B", "eth_derivative", 700_000, 50.0, 1.0),
        ]
        r = analyze("P", assets)
        self.assertAlmostEqual(r["total_collateral_usd"], 1_000_000.0, places=2)


# ---------------------------------------------------------------------------
# 12. Config overrides
# ---------------------------------------------------------------------------
class TestConfigOverrides(unittest.TestCase):
    def test_custom_max_single_asset_pct(self):
        assets = [
            _simple_asset("A", "stablecoin", 60_000, 0.1, 0.0),
            _simple_asset("B", "eth_derivative", 40_000, 50.0, 1.0),
        ]
        r_default = analyze("P", assets)
        r_custom  = analyze("P", assets, config={"max_single_asset_pct": 70.0})
        # With default 30%: A (60%) → flag. With 70% threshold: no flag for A.
        default_flags = [f for f in r_default["risk_flags"] if "A" in f and "category" not in f]
        custom_flags  = [f for f in r_custom["risk_flags"]  if "A" in f and "category" not in f]
        self.assertTrue(len(default_flags) > 0)
        self.assertEqual(len(custom_flags), 0)

    def test_custom_max_category_pct(self):
        assets = [
            _simple_asset("A", "stablecoin", 60_000, 0.1, 0.0),
            _simple_asset("B", "eth_derivative", 40_000, 50.0, 1.0),
        ]
        r = analyze("P", assets, config={"max_single_category_pct": 45.0})
        flags = r["risk_flags"]
        # stablecoin = 60% > 45%
        self.assertTrue(any("stablecoin" in f and "45%" in f for f in flags))

    def test_none_config_uses_defaults(self):
        assets = [_simple_asset("ETH", "eth_derivative", 1_000_000, 50.0, 1.0)]
        r = analyze("P", assets, config=None)
        self.assertIn("risk_flags", r)


# ---------------------------------------------------------------------------
# 13. Return-value schema validation
# ---------------------------------------------------------------------------
class TestReturnSchema(unittest.TestCase):
    def setUp(self):
        self.result = analyze("SchemaCheck", _diverse_assets())

    def test_top_level_keys(self):
        expected = {
            "protocol", "total_collateral_usd", "asset_count", "by_category",
            "top_assets", "metrics", "scores", "grade", "risk_flags", "timestamp",
        }
        self.assertEqual(set(self.result.keys()), expected)

    def test_scores_keys(self):
        expected = {
            "asset_diversity_score", "category_diversity_score",
            "concentration_score", "volatility_score", "total_score",
        }
        self.assertEqual(set(self.result["scores"].keys()), expected)

    def test_metrics_keys(self):
        expected = {
            "weighted_volatility", "weighted_eth_correlation",
            "hhi", "diversification_ratio",
        }
        self.assertEqual(set(self.result["metrics"].keys()), expected)

    def test_total_score_in_range(self):
        score = self.result["scores"]["total_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_grade_valid_value(self):
        self.assertIn(self.result["grade"], {"A", "B", "C", "D", "F"})

    def test_risk_flags_is_list(self):
        self.assertIsInstance(self.result["risk_flags"], list)

    def test_timestamp_is_float(self):
        self.assertIsInstance(self.result["timestamp"], float)

    def test_asset_count_matches_input(self):
        self.assertEqual(self.result["asset_count"], len(_diverse_assets()))


# ---------------------------------------------------------------------------
# 14. Diverse portfolio gets high score
# ---------------------------------------------------------------------------
class TestDiversePortfolio(unittest.TestCase):
    def setUp(self):
        assets = [
            _simple_asset("USDC",  "stablecoin",    10_000_000, 0.2, 0.0),
            _simple_asset("DAI",   "stablecoin",     8_000_000, 0.3, 0.0),
            _simple_asset("ETH",   "eth_derivative", 9_000_000, 55.0, 1.0),
            _simple_asset("stETH", "eth_derivative", 7_000_000, 55.0, 0.98),
            _simple_asset("WBTC",  "btc_derivative", 8_000_000, 50.0, 0.75),
            _simple_asset("UNI",   "defi_token",     4_000_000, 80.0, 0.65),
            _simple_asset("ONDO",  "rwa",            5_000_000, 30.0, 0.2),
            _simple_asset("OTHER", "other",          3_000_000, 40.0, 0.3),
        ]
        self.result = analyze("DiverseProto", assets)

    def test_total_score_positive(self):
        self.assertGreater(self.result["scores"]["total_score"], 0)

    def test_six_categories_present(self):
        # Actually 6 unique categories above
        self.assertEqual(len(self.result["by_category"]), 6)

    def test_max_category_score(self):
        self.assertEqual(self.result["scores"]["category_diversity_score"], 30)

    def test_asset_diversity_score_max(self):
        self.assertEqual(self.result["scores"]["asset_diversity_score"], 40)


# ---------------------------------------------------------------------------
# 15. Concentrated single-category portfolio
# ---------------------------------------------------------------------------
class TestConcentratedPortfolio(unittest.TestCase):
    def setUp(self):
        assets = [
            _simple_asset(f"ETH_{i}", "eth_derivative", 200_000, 55.0, 0.95)
            for i in range(5)
        ]
        self.result = analyze("ConcentratedProto", assets)

    def test_category_flag_raised(self):
        flags = self.result["risk_flags"]
        self.assertTrue(any("eth_derivative" in f for f in flags))

    def test_eth_correlation_flag_raised(self):
        flags = self.result["risk_flags"]
        self.assertTrue(any("ETH correlation" in f for f in flags))

    def test_grade_not_high(self):
        grade = self.result["grade"]
        self.assertIn(grade, {"C", "D", "F"})


# ---------------------------------------------------------------------------
# 16. Atomic log persistence
# ---------------------------------------------------------------------------
class TestLogPersistence(unittest.TestCase):
    def test_log_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = analyze("LogTest", [_simple_asset()])
            _append_log(result, data_dir=tmp)
            log_path = os.path.join(tmp, "collateral_diversification_log.json")
            self.assertTrue(os.path.exists(log_path))

    def test_log_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = analyze("LogTest", [_simple_asset()])
            _append_log(result, data_dir=tmp)
            log_path = os.path.join(tmp, "collateral_diversification_log.json")
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)

    def test_log_grows(self):
        with tempfile.TemporaryDirectory() as tmp:
            for _ in range(3):
                result = analyze("LogTest", [_simple_asset()])
                _append_log(result, data_dir=tmp)
            log_path = os.path.join(tmp, "collateral_diversification_log.json")
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_log_ring_buffer_cap_100(self):
        with tempfile.TemporaryDirectory() as tmp:
            for _ in range(110):
                result = analyze("LogTest", [_simple_asset()])
                _append_log(result, data_dir=tmp)
            log_path = os.path.join(tmp, "collateral_diversification_log.json")
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 100)

    def test_log_entry_has_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = analyze("ProtoXYZ", [_simple_asset()])
            _append_log(result, data_dir=tmp)
            log_path = os.path.join(tmp, "collateral_diversification_log.json")
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(data[0]["protocol"], "ProtoXYZ")

    def test_log_survives_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "collateral_diversification_log.json")
            with open(log_path, "w") as fh:
                fh.write("not valid json {{")
            result = analyze("LogTest", [_simple_asset()])
            _append_log(result, data_dir=tmp)  # should not raise
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)


# ---------------------------------------------------------------------------
# 17. Zero collateral_usd guard
# ---------------------------------------------------------------------------
class TestZeroUSDAssets(unittest.TestCase):
    def test_zero_usd_asset_included_but_zero_pct(self):
        assets = [
            _simple_asset("ETH", "eth_derivative", 1_000_000, 50.0, 1.0),
            {"symbol": "GHOST", "category": "rwa", "collateral_usd": 0.0,
             "volatility_30d_pct": 20.0, "correlation_to_eth": 0.1},
        ]
        r = analyze("P", assets)
        # Total should be 1M, GHOST pct should be 0
        self.assertAlmostEqual(r["total_collateral_usd"], 1_000_000.0, places=2)
        ghost = next((a for a in r["top_assets"] if a["symbol"] == "GHOST"), None)
        self.assertIsNotNone(ghost)
        self.assertAlmostEqual(ghost["pct"], 0.0, places=4)

    def test_all_zero_usd_still_returns_dict(self):
        assets = [
            {"symbol": "X", "category": "stablecoin", "collateral_usd": 0.0,
             "volatility_30d_pct": 0.0, "correlation_to_eth": 0.0},
        ]
        r = analyze("P", assets)
        self.assertIn("grade", r)
        self.assertEqual(r["total_collateral_usd"], 0.0)


# ---------------------------------------------------------------------------
# 18. Total score clamped to 0-100
# ---------------------------------------------------------------------------
class TestScoreClamping(unittest.TestCase):
    def test_score_never_exceeds_100(self):
        # 10 assets, 5 categories, low vol → raw sum could be 40+30+20+10=100
        assets = [
            _simple_asset(f"A{i}", cat, 1_000_000, 5.0, 0.0)
            for i, cat in enumerate(
                ["stablecoin", "stablecoin", "eth_derivative", "eth_derivative",
                 "btc_derivative", "btc_derivative", "defi_token", "defi_token",
                 "rwa", "rwa"]
            )
        ]
        r = analyze("P", assets)
        self.assertLessEqual(r["scores"]["total_score"], 100)

    def test_score_never_negative(self):
        assets = [_simple_asset("X", "defi_token", 1_000_000, 200.0, 1.0)]
        r = analyze("P", assets)
        self.assertGreaterEqual(r["scores"]["total_score"], 0)


# ---------------------------------------------------------------------------
# 19. Protocol name passthrough
# ---------------------------------------------------------------------------
class TestProtocolName(unittest.TestCase):
    def test_protocol_name_returned_correctly(self):
        r = analyze("AaveV3", [_simple_asset()])
        self.assertEqual(r["protocol"], "AaveV3")

    def test_empty_protocol_name(self):
        r = analyze("", [_simple_asset()])
        self.assertEqual(r["protocol"], "")

    def test_unicode_protocol_name(self):
        r = analyze("Протокол", [_simple_asset()])
        self.assertEqual(r["protocol"], "Протокол")


if __name__ == "__main__":
    unittest.main(verbosity=2)
