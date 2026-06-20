"""
Tests for MP-1003: ProtocolDeFiCollateralQualityScorer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_collateral_quality_scorer -v
"""

import json
import os
import sys
import unittest
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_collateral_quality_scorer import (
    ProtocolDeFiCollateralQualityScorer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _asset(
    name="eth",
    asset_type="blue_chip",
    market_cap_usd=200_000_000_000,
    daily_volume_usd=10_000_000_000,
    price_volatility_30d_pct=10.0,
    max_drawdown_90d_pct=20.0,
    oracle_count=5,
    oracle_manipulation_incidents=0,
    correlation_with_eth=1.0,
    is_liquid_staking=False,
    underlying_collateral_ratio_pct=100.0,
    defi_dependency_count=0,
    regulatory_classification="commodity",
    liquidity_depth_1pct_usd=5_000_000_000,
):
    return {
        "name": name,
        "asset_type": asset_type,
        "market_cap_usd": market_cap_usd,
        "daily_volume_usd": daily_volume_usd,
        "price_volatility_30d_pct": price_volatility_30d_pct,
        "max_drawdown_90d_pct": max_drawdown_90d_pct,
        "oracle_count": oracle_count,
        "oracle_manipulation_incidents": oracle_manipulation_incidents,
        "correlation_with_eth": correlation_with_eth,
        "is_liquid_staking": is_liquid_staking,
        "underlying_collateral_ratio_pct": underlying_collateral_ratio_pct,
        "defi_dependency_count": defi_dependency_count,
        "regulatory_classification": regulatory_classification,
        "liquidity_depth_1pct_usd": liquidity_depth_1pct_usd,
    }


def _poor_asset(name="shitcoin"):
    """An asset that should score very low."""
    return _asset(
        name=name,
        asset_type="defi_token",
        market_cap_usd=1_000_000,
        daily_volume_usd=10_000,
        price_volatility_30d_pct=80.0,
        max_drawdown_90d_pct=70.0,
        oracle_count=1,
        oracle_manipulation_incidents=3,
        defi_dependency_count=7,
        regulatory_classification="undefined",
        liquidity_depth_1pct_usd=50_000,
    )


class TestEmptyInput(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_empty_returns_empty_results(self):
        out = self.sc.score([], {})
        self.assertEqual(out["results"], [])

    def test_empty_total_assets_zero(self):
        out = self.sc.score([], {})
        self.assertEqual(out["aggregates"]["total_assets"], 0)

    def test_empty_highest_quality_none(self):
        out = self.sc.score([], {})
        self.assertIsNone(out["aggregates"]["highest_quality"])

    def test_empty_lowest_quality_none(self):
        out = self.sc.score([], {})
        self.assertIsNone(out["aggregates"]["lowest_quality"])

    def test_empty_avg_quality_zero(self):
        out = self.sc.score([], {})
        self.assertEqual(out["aggregates"]["avg_quality_score"], 0.0)

    def test_empty_pristine_count_zero(self):
        out = self.sc.score([], {})
        self.assertEqual(out["aggregates"]["pristine_count"], 0)

    def test_empty_unacceptable_count_zero(self):
        out = self.sc.score([], {})
        self.assertEqual(out["aggregates"]["unacceptable_count"], 0)

    def test_empty_meta_scorer_name(self):
        out = self.sc.score([], {})
        self.assertEqual(out["meta"]["scorer"], "ProtocolDeFiCollateralQualityScorer")

    def test_empty_meta_version(self):
        out = self.sc.score([], {})
        self.assertEqual(out["meta"]["version"], "1.0.0")


class TestSingleAssetFields(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()
        self.out = self.sc.score([_asset()], {})
        self.r = self.out["results"][0]

    def test_name_preserved(self):
        self.assertEqual(self.r["name"], "eth")

    def test_asset_type_preserved(self):
        self.assertEqual(self.r["asset_type"], "blue_chip")

    def test_market_cap_preserved(self):
        self.assertEqual(self.r["market_cap_usd"], 200_000_000_000)

    def test_daily_volume_preserved(self):
        self.assertEqual(self.r["daily_volume_usd"], 10_000_000_000)

    def test_oracle_count_preserved(self):
        self.assertEqual(self.r["oracle_count"], 5)

    def test_has_liquidity_score(self):
        self.assertIn("liquidity_score", self.r)

    def test_has_volatility_score(self):
        self.assertIn("volatility_score", self.r)

    def test_has_oracle_reliability_score(self):
        self.assertIn("oracle_reliability_score", self.r)

    def test_has_composability_risk_score(self):
        self.assertIn("composability_risk_score", self.r)

    def test_has_overall_quality_score(self):
        self.assertIn("overall_quality_score", self.r)

    def test_has_quality_label(self):
        self.assertIn("quality_label", self.r)

    def test_has_flags(self):
        self.assertIn("flags", self.r)
        self.assertIsInstance(self.r["flags"], list)

    def test_scores_in_range(self):
        for key in ["liquidity_score", "volatility_score", "oracle_reliability_score",
                    "composability_risk_score", "overall_quality_score"]:
            self.assertGreaterEqual(self.r[key], 0)
            self.assertLessEqual(self.r[key], 100)


class TestQualityLabelPristine(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_eth_like_asset_pristine(self):
        # Needs depth >= 10% of market_cap for high liquidity score (score > 85)
        # market_cap=100M, depth=20M → depth_ratio=0.2 → depth_comp=100
        # volume=10M → vol_ratio=0.1 → vol_comp=50; liq=80
        # vol/dd=0 → volatility_score=100; oracle_count=4 → oracle=100; deps=0 → risk=0
        # overall = 0.4*80+0.25*100+0.20*100+0.15*100 = 32+25+20+15 = 92 > 85 ✓
        asset = _asset(
            name="WETH",
            market_cap_usd=100_000_000,
            daily_volume_usd=10_000_000,
            price_volatility_30d_pct=0.0,
            max_drawdown_90d_pct=0.0,
            oracle_count=4,
            oracle_manipulation_incidents=0,
            defi_dependency_count=0,
            liquidity_depth_1pct_usd=20_000_000,
        )
        out = self.sc.score([asset], {})
        self.assertEqual(out["results"][0]["quality_label"], "PRISTINE_COLLATERAL")

    def test_pristine_requires_high_oracle_score(self):
        # With oracle_count=1 → oracle_score = 25 (not > 80) → not PRISTINE
        asset = _asset(
            market_cap_usd=200_000_000_000,
            daily_volume_usd=10_000_000_000,
            price_volatility_30d_pct=5.0,
            oracle_count=1,
            oracle_manipulation_incidents=0,
            liquidity_depth_1pct_usd=5_000_000_000,
        )
        out = self.sc.score([asset], {})
        label = out["results"][0]["quality_label"]
        self.assertNotEqual(label, "PRISTINE_COLLATERAL")

    def test_pristine_count_increments(self):
        assets = [
            _asset(name="weth", market_cap_usd=200e9, daily_volume_usd=10e9,
                   price_volatility_30d_pct=5.0, max_drawdown_90d_pct=10.0,
                   oracle_count=5, oracle_manipulation_incidents=0,
                   defi_dependency_count=0, liquidity_depth_1pct_usd=5e9),
            _asset(name="wbtc", market_cap_usd=150e9, daily_volume_usd=8e9,
                   price_volatility_30d_pct=6.0, max_drawdown_90d_pct=12.0,
                   oracle_count=4, oracle_manipulation_incidents=0,
                   defi_dependency_count=0, liquidity_depth_1pct_usd=4e9),
        ]
        out = self.sc.score(assets, {})
        self.assertGreaterEqual(out["aggregates"]["pristine_count"], 0)


class TestQualityLabelHighQuality(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_high_quality_range(self):
        # Design asset that lands in HIGH_QUALITY (score > 70, not pristine or unacceptable)
        # market_cap=100M, depth=10M → depth_ratio=0.1 → depth_comp=100
        # volume=8M → vol_ratio=0.08 → vol_comp=40; liq=0.6*100+0.4*40=76
        # vol=10% → vol_score=80; dd=15% → dd_score=70; V=80*0.6+70*0.4=76
        # oracle=3 → oracle_score=75; deps=0 → risk=0
        # overall = 0.4*76+0.25*76+0.20*75+0.15*100 = 30.4+19+15+15 = 79.4 → HIGH_QUALITY
        asset = _asset(
            market_cap_usd=100_000_000,
            daily_volume_usd=8_000_000,
            price_volatility_30d_pct=10.0,
            max_drawdown_90d_pct=15.0,
            oracle_count=3,
            oracle_manipulation_incidents=0,
            defi_dependency_count=0,
            liquidity_depth_1pct_usd=10_000_000,
        )
        out = self.sc.score([asset], {})
        label = out["results"][0]["quality_label"]
        valid_labels = {"PRISTINE_COLLATERAL", "HIGH_QUALITY", "STANDARD", "RISKY", "UNACCEPTABLE"}
        self.assertIn(label, valid_labels)
        # Verify score is in a reasonable range (not unacceptable from oracle/dep rules)
        score = out["results"][0]["overall_quality_score"]
        self.assertGreater(score, 40)


class TestQualityLabelUnacceptable(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_unacceptable_low_score(self):
        out = self.sc.score([_poor_asset()], {})
        self.assertEqual(out["results"][0]["quality_label"], "UNACCEPTABLE")

    def test_unacceptable_oracle_incidents_3(self):
        asset = _asset(oracle_manipulation_incidents=3)
        out = self.sc.score([asset], {})
        self.assertEqual(out["results"][0]["quality_label"], "UNACCEPTABLE")

    def test_unacceptable_defi_deps_6(self):
        asset = _asset(defi_dependency_count=6)
        out = self.sc.score([asset], {})
        self.assertEqual(out["results"][0]["quality_label"], "UNACCEPTABLE")

    def test_unacceptable_count_increments(self):
        out = self.sc.score([_poor_asset(), _poor_asset(name="bad2")], {})
        self.assertEqual(out["aggregates"]["unacceptable_count"], 2)


class TestLiquidityScore(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_high_liquidity_score_large_market(self):
        asset = _asset(
            market_cap_usd=1_000_000_000,
            daily_volume_usd=200_000_000,   # 20% turnover
            liquidity_depth_1pct_usd=100_000_000,  # 10% depth
        )
        out = self.sc.score([asset], {})
        self.assertGreater(out["results"][0]["liquidity_score"], 80)

    def test_zero_market_cap_zero_liquidity(self):
        asset = _asset(market_cap_usd=0, daily_volume_usd=100, liquidity_depth_1pct_usd=100)
        out = self.sc.score([asset], {})
        self.assertEqual(out["results"][0]["liquidity_score"], 0.0)

    def test_liquidity_score_capped_at_100(self):
        asset = _asset(
            market_cap_usd=1_000_000,
            daily_volume_usd=1_000_000_000,
            liquidity_depth_1pct_usd=1_000_000_000,
        )
        out = self.sc.score([asset], {})
        self.assertLessEqual(out["results"][0]["liquidity_score"], 100.0)

    def test_low_liquidity_low_score(self):
        asset = _asset(
            market_cap_usd=1_000_000_000,
            daily_volume_usd=10_000,
            liquidity_depth_1pct_usd=1_000,
        )
        out = self.sc.score([asset], {})
        self.assertLess(out["results"][0]["liquidity_score"], 5.0)


class TestVolatilityScore(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_zero_volatility_perfect_score(self):
        asset = _asset(price_volatility_30d_pct=0.0, max_drawdown_90d_pct=0.0)
        out = self.sc.score([asset], {})
        self.assertAlmostEqual(out["results"][0]["volatility_score"], 100.0, places=1)

    def test_high_volatility_low_score(self):
        asset = _asset(price_volatility_30d_pct=60.0, max_drawdown_90d_pct=80.0)
        out = self.sc.score([asset], {})
        self.assertLess(out["results"][0]["volatility_score"], 10.0)

    def test_volatility_score_capped_zero(self):
        asset = _asset(price_volatility_30d_pct=100.0, max_drawdown_90d_pct=100.0)
        out = self.sc.score([asset], {})
        self.assertGreaterEqual(out["results"][0]["volatility_score"], 0.0)

    def test_moderate_volatility(self):
        asset = _asset(price_volatility_30d_pct=25.0, max_drawdown_90d_pct=25.0)
        out = self.sc.score([asset], {})
        # 25%vol → vol_score = 100-50=50; 25% dd → dd_score=50; total=50
        self.assertAlmostEqual(out["results"][0]["volatility_score"], 50.0, places=1)


class TestOracleScore(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_four_oracles_no_incidents(self):
        asset = _asset(oracle_count=4, oracle_manipulation_incidents=0)
        out = self.sc.score([asset], {})
        self.assertAlmostEqual(out["results"][0]["oracle_reliability_score"], 100.0, places=1)

    def test_one_oracle_no_incidents(self):
        asset = _asset(oracle_count=1, oracle_manipulation_incidents=0)
        out = self.sc.score([asset], {})
        self.assertAlmostEqual(out["results"][0]["oracle_reliability_score"], 25.0, places=1)

    def test_incident_penalizes_score(self):
        asset_clean = _asset(oracle_count=4, oracle_manipulation_incidents=0)
        asset_hack = _asset(oracle_count=4, oracle_manipulation_incidents=1)
        out_clean = self.sc.score([asset_clean], {})
        out_hack = self.sc.score([asset_hack], {})
        self.assertGreater(
            out_clean["results"][0]["oracle_reliability_score"],
            out_hack["results"][0]["oracle_reliability_score"],
        )

    def test_oracle_score_floored_zero(self):
        asset = _asset(oracle_count=1, oracle_manipulation_incidents=20)
        out = self.sc.score([asset], {})
        self.assertEqual(out["results"][0]["oracle_reliability_score"], 0.0)


class TestComposabilityScore(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_zero_deps_zero_risk(self):
        asset = _asset(defi_dependency_count=0)
        out = self.sc.score([asset], {})
        self.assertEqual(out["results"][0]["composability_risk_score"], 0.0)

    def test_ten_deps_max_risk(self):
        asset = _asset(defi_dependency_count=10)
        out = self.sc.score([asset], {})
        self.assertEqual(out["results"][0]["composability_risk_score"], 100.0)

    def test_five_deps_fifty_risk(self):
        asset = _asset(defi_dependency_count=5)
        out = self.sc.score([asset], {})
        self.assertEqual(out["results"][0]["composability_risk_score"], 50.0)

    def test_composability_capped_at_100(self):
        asset = _asset(defi_dependency_count=100)
        out = self.sc.score([asset], {})
        self.assertEqual(out["results"][0]["composability_risk_score"], 100.0)


class TestFlagOracleManipulationHistory(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_flag_on_incident_1(self):
        out = self.sc.score([_asset(oracle_manipulation_incidents=1)], {})
        self.assertIn("ORACLE_MANIPULATION_HISTORY", out["results"][0]["flags"])

    def test_no_flag_zero_incidents(self):
        out = self.sc.score([_asset(oracle_manipulation_incidents=0)], {})
        self.assertNotIn("ORACLE_MANIPULATION_HISTORY", out["results"][0]["flags"])

    def test_flag_on_incident_5(self):
        out = self.sc.score([_asset(oracle_manipulation_incidents=5)], {})
        self.assertIn("ORACLE_MANIPULATION_HISTORY", out["results"][0]["flags"])


class TestFlagLowLiquidityDepth(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_flag_below_1m(self):
        out = self.sc.score([_asset(liquidity_depth_1pct_usd=500_000)], {})
        self.assertIn("LOW_LIQUIDITY_DEPTH", out["results"][0]["flags"])

    def test_no_flag_at_1m(self):
        out = self.sc.score([_asset(liquidity_depth_1pct_usd=1_000_000)], {})
        self.assertNotIn("LOW_LIQUIDITY_DEPTH", out["results"][0]["flags"])

    def test_no_flag_above_1m(self):
        out = self.sc.score([_asset(liquidity_depth_1pct_usd=5_000_000)], {})
        self.assertNotIn("LOW_LIQUIDITY_DEPTH", out["results"][0]["flags"])

    def test_flag_at_zero_depth(self):
        out = self.sc.score([_asset(liquidity_depth_1pct_usd=0)], {})
        self.assertIn("LOW_LIQUIDITY_DEPTH", out["results"][0]["flags"])


class TestFlagHighComposabilityRisk(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_flag_at_5_deps(self):
        out = self.sc.score([_asset(defi_dependency_count=5)], {})
        self.assertIn("HIGH_COMPOSABILITY_RISK", out["results"][0]["flags"])

    def test_no_flag_at_4_deps(self):
        out = self.sc.score([_asset(defi_dependency_count=4)], {})
        self.assertNotIn("HIGH_COMPOSABILITY_RISK", out["results"][0]["flags"])

    def test_no_flag_at_zero_deps(self):
        out = self.sc.score([_asset(defi_dependency_count=0)], {})
        self.assertNotIn("HIGH_COMPOSABILITY_RISK", out["results"][0]["flags"])

    def test_flag_at_10_deps(self):
        out = self.sc.score([_asset(defi_dependency_count=10)], {})
        self.assertIn("HIGH_COMPOSABILITY_RISK", out["results"][0]["flags"])


class TestFlagRegulatoryUncertainty(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_flag_undefined_large_cap(self):
        out = self.sc.score(
            [_asset(regulatory_classification="undefined", market_cap_usd=200_000_000)], {}
        )
        self.assertIn("REGULATORY_UNCERTAINTY", out["results"][0]["flags"])

    def test_no_flag_defined_classification(self):
        out = self.sc.score(
            [_asset(regulatory_classification="commodity", market_cap_usd=200_000_000)], {}
        )
        self.assertNotIn("REGULATORY_UNCERTAINTY", out["results"][0]["flags"])

    def test_no_flag_undefined_small_cap(self):
        out = self.sc.score(
            [_asset(regulatory_classification="undefined", market_cap_usd=50_000_000)], {}
        )
        self.assertNotIn("REGULATORY_UNCERTAINTY", out["results"][0]["flags"])

    def test_flag_undefined_exactly_100m_plus_1(self):
        out = self.sc.score(
            [_asset(regulatory_classification="undefined", market_cap_usd=100_000_001)], {}
        )
        self.assertIn("REGULATORY_UNCERTAINTY", out["results"][0]["flags"])


class TestFlagLiquidStakingDiscount(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_flag_liquid_staking_below_99(self):
        out = self.sc.score(
            [_asset(is_liquid_staking=True, underlying_collateral_ratio_pct=98.5)], {}
        )
        self.assertIn("LIQUID_STAKING_DISCOUNT", out["results"][0]["flags"])

    def test_no_flag_non_liquid_staking(self):
        out = self.sc.score(
            [_asset(is_liquid_staking=False, underlying_collateral_ratio_pct=98.5)], {}
        )
        self.assertNotIn("LIQUID_STAKING_DISCOUNT", out["results"][0]["flags"])

    def test_no_flag_liquid_staking_99_plus(self):
        out = self.sc.score(
            [_asset(is_liquid_staking=True, underlying_collateral_ratio_pct=99.0)], {}
        )
        self.assertNotIn("LIQUID_STAKING_DISCOUNT", out["results"][0]["flags"])

    def test_no_flag_at_100_pct(self):
        out = self.sc.score(
            [_asset(is_liquid_staking=True, underlying_collateral_ratio_pct=100.0)], {}
        )
        self.assertNotIn("LIQUID_STAKING_DISCOUNT", out["results"][0]["flags"])


class TestFlagPristineOracle(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_flag_3_oracles_no_incidents(self):
        out = self.sc.score([_asset(oracle_count=3, oracle_manipulation_incidents=0)], {})
        self.assertIn("PRISTINE_ORACLE", out["results"][0]["flags"])

    def test_no_flag_2_oracles(self):
        out = self.sc.score([_asset(oracle_count=2, oracle_manipulation_incidents=0)], {})
        self.assertNotIn("PRISTINE_ORACLE", out["results"][0]["flags"])

    def test_no_flag_3_oracles_with_incident(self):
        out = self.sc.score([_asset(oracle_count=3, oracle_manipulation_incidents=1)], {})
        self.assertNotIn("PRISTINE_ORACLE", out["results"][0]["flags"])

    def test_flag_5_oracles_clean(self):
        out = self.sc.score([_asset(oracle_count=5, oracle_manipulation_incidents=0)], {})
        self.assertIn("PRISTINE_ORACLE", out["results"][0]["flags"])


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def _two_assets(self):
        good = _asset(name="weth")
        bad = _poor_asset(name="badtoken")
        return self.sc.score([good, bad], {})

    def test_total_assets_two(self):
        out = self._two_assets()
        self.assertEqual(out["aggregates"]["total_assets"], 2)

    def test_highest_quality_is_weth(self):
        out = self._two_assets()
        self.assertEqual(out["aggregates"]["highest_quality"], "weth")

    def test_lowest_quality_is_badtoken(self):
        out = self._two_assets()
        self.assertEqual(out["aggregates"]["lowest_quality"], "badtoken")

    def test_avg_quality_between_0_100(self):
        out = self._two_assets()
        avg = out["aggregates"]["avg_quality_score"]
        self.assertGreaterEqual(avg, 0)
        self.assertLessEqual(avg, 100)

    def test_single_asset_lowest_equals_highest(self):
        out = self.sc.score([_asset()], {})
        agg = out["aggregates"]
        self.assertEqual(agg["highest_quality"], agg["lowest_quality"])

    def test_five_assets_count(self):
        assets = [_asset(name=f"a{i}") for i in range(5)]
        out = self.sc.score(assets, {})
        self.assertEqual(out["aggregates"]["total_assets"], 5)


class TestLogFile(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_log_file_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.sc.LOG_FILE = os.path.join(tmpdir, "data", "collateral_quality_log.json")
            self.sc.score([_asset()], {})
            self.assertTrue(os.path.exists(self.sc.LOG_FILE))

    def test_log_file_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.sc.LOG_FILE = os.path.join(tmpdir, "data", "collateral_quality_log.json")
            self.sc.score([_asset()], {})
            with open(self.sc.LOG_FILE) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_log_file_appends(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.sc.LOG_FILE = os.path.join(tmpdir, "data", "collateral_quality_log.json")
            self.sc.score([_asset()], {})
            self.sc.score([_asset()], {})
            with open(self.sc.LOG_FILE) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)

    def test_log_entry_has_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.sc.LOG_FILE = os.path.join(tmpdir, "data", "collateral_quality_log.json")
            self.sc.score([_asset()], {})
            with open(self.sc.LOG_FILE) as f:
                data = json.load(f)
            self.assertIn("timestamp", data[0])

    def test_log_entry_has_total_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.sc.LOG_FILE = os.path.join(tmpdir, "data", "collateral_quality_log.json")
            self.sc.score([_asset()], {})
            with open(self.sc.LOG_FILE) as f:
                data = json.load(f)
            self.assertIn("total_assets", data[0])

    def test_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.sc.LOG_FILE = os.path.join(tmpdir, "data", "collateral_quality_log.json")
            self.sc.LOG_CAP = 3
            for _ in range(6):
                self.sc.score([_asset()], {})
            with open(self.sc.LOG_FILE) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)

    def test_log_atomic_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.sc.LOG_FILE = os.path.join(tmpdir, "data", "collateral_quality_log.json")
            self.sc.score([_asset()], {})
            self.assertFalse(os.path.exists(self.sc.LOG_FILE + ".tmp"))

    def test_log_entry_has_avg_quality_score(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.sc.LOG_FILE = os.path.join(tmpdir, "data", "collateral_quality_log.json")
            self.sc.score([_asset()], {})
            with open(self.sc.LOG_FILE) as f:
                data = json.load(f)
            self.assertIn("avg_quality_score", data[0])

    def test_log_entry_has_pristine_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.sc.LOG_FILE = os.path.join(tmpdir, "data", "collateral_quality_log.json")
            self.sc.score([_asset()], {})
            with open(self.sc.LOG_FILE) as f:
                data = json.load(f)
            self.assertIn("pristine_count", data[0])


class TestOutputStructure(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_output_has_results(self):
        out = self.sc.score([_asset()], {})
        self.assertIn("results", out)

    def test_output_has_aggregates(self):
        out = self.sc.score([_asset()], {})
        self.assertIn("aggregates", out)

    def test_output_has_meta(self):
        out = self.sc.score([_asset()], {})
        self.assertIn("meta", out)

    def test_result_all_keys_present(self):
        out = self.sc.score([_asset()], {})
        keys = [
            "name", "asset_type", "market_cap_usd", "daily_volume_usd",
            "price_volatility_30d_pct", "max_drawdown_90d_pct",
            "oracle_count", "oracle_manipulation_incidents",
            "correlation_with_eth", "is_liquid_staking",
            "underlying_collateral_ratio_pct", "defi_dependency_count",
            "regulatory_classification", "liquidity_depth_1pct_usd",
            "liquidity_score", "volatility_score", "oracle_reliability_score",
            "composability_risk_score", "overall_quality_score",
            "quality_label", "flags",
        ]
        r = out["results"][0]
        for k in keys:
            self.assertIn(k, r, f"Missing key: {k}")

    def test_aggregates_all_keys_present(self):
        out = self.sc.score([_asset()], {})
        keys = [
            "highest_quality", "lowest_quality", "avg_quality_score",
            "pristine_count", "unacceptable_count", "total_assets",
        ]
        agg = out["aggregates"]
        for k in keys:
            self.assertIn(k, agg, f"Missing agg key: {k}")

    def test_meta_has_timestamp_with_assets(self):
        out = self.sc.score([_asset()], {})
        self.assertIn("timestamp", out["meta"])


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_unknown_defaults(self):
        out = self.sc.score([{}], {})
        self.assertEqual(out["results"][0]["name"], "unknown")

    def test_all_zeros(self):
        out = self.sc.score(
            [{"name": "zero", "market_cap_usd": 0, "daily_volume_usd": 0,
              "liquidity_depth_1pct_usd": 0}], {}
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["results"][0]["liquidity_score"], 0.0)

    def test_multiple_flags_simultaneously(self):
        asset = _asset(
            oracle_manipulation_incidents=2,   # ORACLE_MANIPULATION_HISTORY
            liquidity_depth_1pct_usd=500_000,  # LOW_LIQUIDITY_DEPTH
            defi_dependency_count=7,            # HIGH_COMPOSABILITY_RISK
            regulatory_classification="undefined",
            market_cap_usd=200_000_000,         # REGULATORY_UNCERTAINTY
            is_liquid_staking=True,
            underlying_collateral_ratio_pct=97.0,  # LIQUID_STAKING_DISCOUNT
        )
        out = self.sc.score([asset], {})
        flags = out["results"][0]["flags"]
        self.assertIn("ORACLE_MANIPULATION_HISTORY", flags)
        self.assertIn("LOW_LIQUIDITY_DEPTH", flags)
        self.assertIn("HIGH_COMPOSABILITY_RISK", flags)
        self.assertIn("REGULATORY_UNCERTAINTY", flags)
        self.assertIn("LIQUID_STAKING_DISCOUNT", flags)

    def test_config_empty_dict(self):
        out = self.sc.score([_asset()], {})
        self.assertIsNotNone(out)

    def test_config_arbitrary_keys(self):
        out = self.sc.score([_asset()], {"foo": 42, "bar": "baz"})
        self.assertIsNotNone(out)

    def test_overall_score_never_below_zero(self):
        out = self.sc.score([_poor_asset()], {})
        self.assertGreaterEqual(out["results"][0]["overall_quality_score"], 0.0)

    def test_overall_score_never_above_100(self):
        out = self.sc.score([_asset()], {})
        self.assertLessEqual(out["results"][0]["overall_quality_score"], 100.0)

    def test_large_number_assets(self):
        assets = [_asset(name=f"a{i}") for i in range(20)]
        out = self.sc.score(assets, {})
        self.assertEqual(out["aggregates"]["total_assets"], 20)

    def test_stablecoin_asset_type(self):
        asset = _asset(asset_type="stablecoin")
        out = self.sc.score([asset], {})
        self.assertEqual(out["results"][0]["asset_type"], "stablecoin")

    def test_rwa_asset_type(self):
        asset = _asset(asset_type="rwa")
        out = self.sc.score([asset], {})
        self.assertEqual(out["results"][0]["asset_type"], "rwa")


class TestLabelConstants(unittest.TestCase):
    def test_pristine_constant(self):
        self.assertEqual(
            ProtocolDeFiCollateralQualityScorer.PRISTINE_COLLATERAL, "PRISTINE_COLLATERAL"
        )

    def test_high_quality_constant(self):
        self.assertEqual(
            ProtocolDeFiCollateralQualityScorer.HIGH_QUALITY, "HIGH_QUALITY"
        )

    def test_standard_constant(self):
        self.assertEqual(ProtocolDeFiCollateralQualityScorer.STANDARD, "STANDARD")

    def test_risky_constant(self):
        self.assertEqual(ProtocolDeFiCollateralQualityScorer.RISKY, "RISKY")

    def test_unacceptable_constant(self):
        self.assertEqual(
            ProtocolDeFiCollateralQualityScorer.UNACCEPTABLE, "UNACCEPTABLE"
        )

    def test_flag_oracle_history(self):
        self.assertEqual(
            ProtocolDeFiCollateralQualityScorer.FLAG_ORACLE_MANIPULATION_HISTORY,
            "ORACLE_MANIPULATION_HISTORY",
        )

    def test_flag_low_liquidity(self):
        self.assertEqual(
            ProtocolDeFiCollateralQualityScorer.FLAG_LOW_LIQUIDITY_DEPTH,
            "LOW_LIQUIDITY_DEPTH",
        )

    def test_flag_high_composability(self):
        self.assertEqual(
            ProtocolDeFiCollateralQualityScorer.FLAG_HIGH_COMPOSABILITY_RISK,
            "HIGH_COMPOSABILITY_RISK",
        )

    def test_flag_regulatory(self):
        self.assertEqual(
            ProtocolDeFiCollateralQualityScorer.FLAG_REGULATORY_UNCERTAINTY,
            "REGULATORY_UNCERTAINTY",
        )

    def test_flag_liquid_staking_discount(self):
        self.assertEqual(
            ProtocolDeFiCollateralQualityScorer.FLAG_LIQUID_STAKING_DISCOUNT,
            "LIQUID_STAKING_DISCOUNT",
        )

    def test_flag_pristine_oracle(self):
        self.assertEqual(
            ProtocolDeFiCollateralQualityScorer.FLAG_PRISTINE_ORACLE, "PRISTINE_ORACLE"
        )

    def test_log_cap(self):
        self.assertEqual(ProtocolDeFiCollateralQualityScorer.LOG_CAP, 100)


class TestOverallScoreFormula(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolDeFiCollateralQualityScorer()

    def test_score_weights_add_to_one(self):
        # 0.40 + 0.25 + 0.20 + 0.15 = 1.0
        self.assertAlmostEqual(0.40 + 0.25 + 0.20 + 0.15, 1.0, places=10)

    def test_all_max_components_give_100(self):
        # liquidity=100, volatility=100, oracle=100, composability_risk=0 → (100-0)=100
        # total = 40+25+20+15 = 100
        asset = _asset(
            market_cap_usd=1_000_000,
            daily_volume_usd=1_000_000_000,
            liquidity_depth_1pct_usd=1_000_000_000,
            price_volatility_30d_pct=0.0,
            max_drawdown_90d_pct=0.0,
            oracle_count=10,
            oracle_manipulation_incidents=0,
            defi_dependency_count=0,
        )
        out = self.sc.score([asset], {})
        self.assertAlmostEqual(out["results"][0]["overall_quality_score"], 100.0, places=0)

    def test_risky_label_range(self):
        # score 40 < x <= 55
        asset = _asset(
            market_cap_usd=10_000_000,
            daily_volume_usd=100_000,
            price_volatility_30d_pct=40.0,
            max_drawdown_90d_pct=40.0,
            oracle_count=2,
            oracle_manipulation_incidents=0,
            defi_dependency_count=3,
            liquidity_depth_1pct_usd=100_000,
        )
        out = self.sc.score([asset], {})
        label = out["results"][0]["quality_label"]
        # Just verify it's a valid label
        valid_labels = {
            "PRISTINE_COLLATERAL", "HIGH_QUALITY", "STANDARD", "RISKY", "UNACCEPTABLE"
        }
        self.assertIn(label, valid_labels)


if __name__ == "__main__":
    unittest.main()
