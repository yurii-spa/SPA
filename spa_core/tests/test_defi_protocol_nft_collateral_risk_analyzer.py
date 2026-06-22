"""
Tests for MP-1016: DeFiProtocolNFTCollateralRiskAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_nft_collateral_risk_analyzer
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure repo root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_nft_collateral_risk_analyzer import (
    DeFiProtocolNFTCollateralRiskAnalyzer,
    ORACLE_RISK_MAP,
)


def _pos(
    name="POS-1",
    collection="TestNFT",
    floor_price_eth=10.0,
    loan_to_value_pct=50.0,
    loan_amount_eth=5.0,
    liquidation_threshold_pct=80.0,
    collection_volume_30d_eth=20.0,
    collection_listings_count=50.0,
    days_to_maturity=30.0,
    oracle_type="twap_floor",
    floor_price_volatility_30d_pct=10.0,
    blue_chip_collection=False,
    wash_trading_score=10.0,
    royalty_enforced=True,
):
    """Helper to build a position dict with sensible defaults."""
    return {
        "name": name,
        "collection": collection,
        "floor_price_eth": floor_price_eth,
        "loan_to_value_pct": loan_to_value_pct,
        "loan_amount_eth": loan_amount_eth,
        "liquidation_threshold_pct": liquidation_threshold_pct,
        "collection_volume_30d_eth": collection_volume_30d_eth,
        "days_to_maturity": days_to_maturity,
        "oracle_type": oracle_type,
        "floor_price_volatility_30d_pct": floor_price_volatility_30d_pct,
        "blue_chip_collection": blue_chip_collection,
        "wash_trading_score": wash_trading_score,
        "royalty_enforced": royalty_enforced,
        "collection_listings_count": collection_listings_count,
    }


def _tmp_log(tmp_dir):
    return os.path.join(tmp_dir, "nft_risk_log.json")


class TestInstantiation(unittest.TestCase):
    def test_instantiation(self):
        a = DeFiProtocolNFTCollateralRiskAnalyzer()
        self.assertIsNotNone(a)

    def test_name_attribute(self):
        a = DeFiProtocolNFTCollateralRiskAnalyzer()
        self.assertEqual(a.name, "DeFiProtocolNFTCollateralRiskAnalyzer")

    def test_version_attribute(self):
        a = DeFiProtocolNFTCollateralRiskAnalyzer()
        self.assertEqual(a.version, "1.0.0")


class TestOracleRiskMap(unittest.TestCase):
    def test_floor_price_oracle_risk(self):
        self.assertEqual(ORACLE_RISK_MAP["floor_price"], 80.0)

    def test_twap_floor_oracle_risk(self):
        self.assertEqual(ORACLE_RISK_MAP["twap_floor"], 40.0)

    def test_appraisal_oracle_risk(self):
        self.assertEqual(ORACLE_RISK_MAP["appraisal"], 20.0)

    def test_chainlink_oracle_risk(self):
        self.assertEqual(ORACLE_RISK_MAP["chainlink"], 10.0)

    def test_unknown_oracle_defaults_to_floor_price(self):
        a = DeFiProtocolNFTCollateralRiskAnalyzer()
        p = _pos(oracle_type="unknown_oracle")
        with tempfile.TemporaryDirectory() as d:
            result = a.analyze([p], {"log_file": _tmp_log(d)})
        pos = result["positions"][0]
        self.assertEqual(pos["oracle_risk_score"], 80.0)


class TestEmptyInput(unittest.TestCase):
    def test_empty_list_returns_zero_count(self):
        a = DeFiProtocolNFTCollateralRiskAnalyzer()
        r = a.analyze([])
        self.assertEqual(r["position_count"], 0)

    def test_empty_list_positions_is_empty(self):
        a = DeFiProtocolNFTCollateralRiskAnalyzer()
        r = a.analyze([])
        self.assertEqual(r["positions"], [])

    def test_empty_list_aggregates_none(self):
        a = DeFiProtocolNFTCollateralRiskAnalyzer()
        r = a.analyze([])
        self.assertIsNone(r["aggregates"]["safest"])
        self.assertIsNone(r["aggregates"]["riskiest"])

    def test_empty_list_avg_composite_zero(self):
        a = DeFiProtocolNFTCollateralRiskAnalyzer()
        r = a.analyze([])
        self.assertEqual(r["aggregates"]["avg_composite_risk"], 0.0)

    def test_empty_list_counts_zero(self):
        a = DeFiProtocolNFTCollateralRiskAnalyzer()
        r = a.analyze([])
        self.assertEqual(r["aggregates"]["imminent_liquidation_count"], 0)
        self.assertEqual(r["aggregates"]["fortress_count"], 0)


class TestReturnStructure(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolNFTCollateralRiskAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_top_level_keys_present(self):
        r = self.a.analyze([_pos()], self.cfg)
        for k in ("analyzer", "version", "timestamp", "position_count", "positions", "aggregates"):
            self.assertIn(k, r)

    def test_position_count_matches(self):
        r = self.a.analyze([_pos("A"), _pos("B"), _pos("C")], self.cfg)
        self.assertEqual(r["position_count"], 3)
        self.assertEqual(len(r["positions"]), 3)

    def test_position_keys_present(self):
        r = self.a.analyze([_pos()], self.cfg)
        p = r["positions"][0]
        for k in (
            "name", "collection", "floor_price_eth", "loan_to_value_pct",
            "loan_amount_eth", "liquidation_threshold_pct", "oracle_type",
            "liquidation_buffer_pct", "floor_drop_to_liquidation_pct",
            "liquidity_risk_score", "oracle_risk_score", "composite_nft_risk_score",
            "risk_label", "flags",
        ):
            self.assertIn(k, p)

    def test_aggregate_keys_present(self):
        r = self.a.analyze([_pos()], self.cfg)
        for k in ("safest", "riskiest", "avg_composite_risk", "imminent_liquidation_count", "fortress_count"):
            self.assertIn(k, r["aggregates"])

    def test_analyzer_name_in_result(self):
        r = self.a.analyze([_pos()], self.cfg)
        self.assertEqual(r["analyzer"], "DeFiProtocolNFTCollateralRiskAnalyzer")

    def test_version_in_result(self):
        r = self.a.analyze([_pos()], self.cfg)
        self.assertEqual(r["version"], "1.0.0")

    def test_timestamp_is_string(self):
        r = self.a.analyze([_pos()], self.cfg)
        self.assertIsInstance(r["timestamp"], str)


class TestLiquidationBuffer(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolNFTCollateralRiskAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_buffer_basic(self):
        p = _pos(loan_to_value_pct=50.0, liquidation_threshold_pct=80.0)
        r = self.a.analyze([p], self.cfg)
        self.assertAlmostEqual(r["positions"][0]["liquidation_buffer_pct"], 30.0)

    def test_buffer_near_zero(self):
        p = _pos(loan_to_value_pct=79.0, liquidation_threshold_pct=80.0)
        r = self.a.analyze([p], self.cfg)
        self.assertAlmostEqual(r["positions"][0]["liquidation_buffer_pct"], 1.0)

    def test_buffer_large_gap(self):
        p = _pos(loan_to_value_pct=20.0, liquidation_threshold_pct=90.0)
        r = self.a.analyze([p], self.cfg)
        self.assertAlmostEqual(r["positions"][0]["liquidation_buffer_pct"], 70.0)

    def test_buffer_negative_when_already_liquidated(self):
        p = _pos(loan_to_value_pct=85.0, liquidation_threshold_pct=80.0)
        r = self.a.analyze([p], self.cfg)
        self.assertLess(r["positions"][0]["liquidation_buffer_pct"], 0.0)

    def test_buffer_zero_means_at_threshold(self):
        p = _pos(loan_to_value_pct=80.0, liquidation_threshold_pct=80.0)
        r = self.a.analyze([p], self.cfg)
        self.assertAlmostEqual(r["positions"][0]["liquidation_buffer_pct"], 0.0)


class TestFloorDropToLiquidation(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolNFTCollateralRiskAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_floor_drop_basic(self):
        # (80-50)/80 * 100 = 37.5%
        p = _pos(loan_to_value_pct=50.0, liquidation_threshold_pct=80.0)
        r = self.a.analyze([p], self.cfg)
        self.assertAlmostEqual(r["positions"][0]["floor_drop_to_liquidation_pct"], 37.5, places=2)

    def test_floor_drop_small_buffer(self):
        # (75-70)/75 * 100 = 6.67%
        p = _pos(loan_to_value_pct=70.0, liquidation_threshold_pct=75.0)
        r = self.a.analyze([p], self.cfg)
        self.assertAlmostEqual(r["positions"][0]["floor_drop_to_liquidation_pct"], 6.666, places=2)

    def test_floor_drop_zero_when_at_threshold(self):
        p = _pos(loan_to_value_pct=80.0, liquidation_threshold_pct=80.0)
        r = self.a.analyze([p], self.cfg)
        self.assertAlmostEqual(r["positions"][0]["floor_drop_to_liquidation_pct"], 0.0, places=3)

    def test_floor_drop_high_buffer(self):
        # (90-20)/90 * 100 ≈ 77.78%
        p = _pos(loan_to_value_pct=20.0, liquidation_threshold_pct=90.0)
        r = self.a.analyze([p], self.cfg)
        self.assertAlmostEqual(r["positions"][0]["floor_drop_to_liquidation_pct"], 77.77, places=1)

    def test_floor_drop_zero_threshold_handled(self):
        p = _pos(loan_to_value_pct=50.0, liquidation_threshold_pct=0.0)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["positions"][0]["floor_drop_to_liquidation_pct"], 0.0)


class TestLiquidityRiskScore(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolNFTCollateralRiskAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_zero_volume_raises_risk(self):
        # 0 volume → volume_risk=100, weight=40% → score=40.0 (volume component dominates)
        p = _pos(collection_volume_30d_eth=0.0, collection_listings_count=0.0, wash_trading_score=0.0)
        r = self.a.analyze([p], self.cfg)
        self.assertGreater(r["positions"][0]["liquidity_risk_score"], 30.0)

    def test_high_volume_lowers_risk(self):
        p = _pos(collection_volume_30d_eth=100.0, collection_listings_count=0.0, wash_trading_score=0.0)
        r = self.a.analyze([p], self.cfg)
        self.assertLess(r["positions"][0]["liquidity_risk_score"], 10.0)

    def test_high_listings_raises_risk(self):
        p_high = _pos(collection_volume_30d_eth=20.0, collection_listings_count=1000.0, wash_trading_score=0.0)
        p_low = _pos(collection_volume_30d_eth=20.0, collection_listings_count=0.0, wash_trading_score=0.0)
        r_high = self.a.analyze([p_high], self.cfg)
        r_low = self.a.analyze([p_low], self.cfg)
        self.assertGreater(
            r_high["positions"][0]["liquidity_risk_score"],
            r_low["positions"][0]["liquidity_risk_score"],
        )

    def test_high_wash_raises_risk(self):
        p_hw = _pos(collection_volume_30d_eth=20.0, collection_listings_count=50.0, wash_trading_score=90.0)
        p_lw = _pos(collection_volume_30d_eth=20.0, collection_listings_count=50.0, wash_trading_score=0.0)
        r_hw = self.a.analyze([p_hw], self.cfg)
        r_lw = self.a.analyze([p_lw], self.cfg)
        self.assertGreater(
            r_hw["positions"][0]["liquidity_risk_score"],
            r_lw["positions"][0]["liquidity_risk_score"],
        )

    def test_liquidity_risk_bounded_0_100(self):
        a = DeFiProtocolNFTCollateralRiskAnalyzer()
        for v in [0, 5, 20, 100]:
            for l in [0, 100, 1000, 5000]:
                for w in [0, 50, 100]:
                    score = a._calc_liquidity_risk(float(v), float(l), float(w))
                    self.assertGreaterEqual(score, 0.0)
                    self.assertLessEqual(score, 100.0)

    def test_all_worst_case_near_100(self):
        a = DeFiProtocolNFTCollateralRiskAnalyzer()
        score = a._calc_liquidity_risk(0.0, 10000.0, 100.0)
        self.assertGreater(score, 90.0)

    def test_all_best_case_near_0(self):
        a = DeFiProtocolNFTCollateralRiskAnalyzer()
        score = a._calc_liquidity_risk(100.0, 0.0, 0.0)
        self.assertAlmostEqual(score, 0.0)

    def test_volume_20_contribution_zero(self):
        # 20 ETH volume → volume_risk = max(0, 100 - 20*5) = 0
        a = DeFiProtocolNFTCollateralRiskAnalyzer()
        score = a._calc_liquidity_risk(20.0, 0.0, 0.0)
        self.assertAlmostEqual(score, 0.0)


class TestCompositeNFTRiskScore(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolNFTCollateralRiskAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_composite_bounded_0_100(self):
        # Stress test a variety of positions
        test_cases = [
            _pos(loan_to_value_pct=10.0, floor_price_volatility_30d_pct=0.0,
                 collection_volume_30d_eth=100.0, oracle_type="chainlink"),
            _pos(loan_to_value_pct=85.0, floor_price_volatility_30d_pct=50.0,
                 collection_volume_30d_eth=0.0, oracle_type="floor_price"),
        ]
        for p in test_cases:
            r = self.a.analyze([p], self.cfg)
            score = r["positions"][0]["composite_nft_risk_score"]
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_high_buffer_lowers_composite(self):
        p_safe = _pos(loan_to_value_pct=20.0, liquidation_threshold_pct=90.0,
                      floor_price_volatility_30d_pct=5.0, collection_volume_30d_eth=50.0,
                      oracle_type="chainlink")
        p_risky = _pos(loan_to_value_pct=75.0, liquidation_threshold_pct=80.0,
                       floor_price_volatility_30d_pct=5.0, collection_volume_30d_eth=50.0,
                       oracle_type="chainlink")
        r_safe = self.a.analyze([p_safe], self.cfg)
        r_risky = self.a.analyze([p_risky], self.cfg)
        self.assertLess(
            r_safe["positions"][0]["composite_nft_risk_score"],
            r_risky["positions"][0]["composite_nft_risk_score"],
        )

    def test_chainlink_oracle_lowers_composite_vs_floor(self):
        p_cl = _pos(oracle_type="chainlink", loan_to_value_pct=50.0)
        p_fp = _pos(oracle_type="floor_price", loan_to_value_pct=50.0)
        r_cl = self.a.analyze([p_cl], self.cfg)
        r_fp = self.a.analyze([p_fp], self.cfg)
        self.assertLess(
            r_cl["positions"][0]["composite_nft_risk_score"],
            r_fp["positions"][0]["composite_nft_risk_score"],
        )

    def test_composite_is_float(self):
        r = self.a.analyze([_pos()], self.cfg)
        self.assertIsInstance(r["positions"][0]["composite_nft_risk_score"], float)


class TestRiskLabels(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolNFTCollateralRiskAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_label_liquidation_imminent_buffer_below_10(self):
        p = _pos(loan_to_value_pct=78.0, liquidation_threshold_pct=80.0)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["positions"][0]["risk_label"], "LIQUIDATION_IMMINENT")

    def test_label_liquidation_imminent_exactly_9_9(self):
        p = _pos(loan_to_value_pct=70.1, liquidation_threshold_pct=80.0)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["positions"][0]["risk_label"], "LIQUIDATION_IMMINENT")

    def test_label_high_risk_ltv_above_70(self):
        p = _pos(loan_to_value_pct=75.0, liquidation_threshold_pct=85.0,
                 floor_price_volatility_30d_pct=10.0)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["positions"][0]["risk_label"], "HIGH_RISK")

    def test_label_high_risk_volatility_above_30(self):
        p = _pos(loan_to_value_pct=50.0, liquidation_threshold_pct=80.0,
                 floor_price_volatility_30d_pct=35.0)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["positions"][0]["risk_label"], "HIGH_RISK")

    def test_label_nft_fortress(self):
        p = _pos(
            loan_to_value_pct=25.0,
            liquidation_threshold_pct=80.0,
            oracle_type="twap_floor",
            blue_chip_collection=True,
            floor_price_volatility_30d_pct=5.0,
            collection_volume_30d_eth=50.0,
            wash_trading_score=5.0,
        )
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["positions"][0]["risk_label"], "NFT_FORTRESS")

    def test_label_fortress_requires_twap_floor(self):
        p = _pos(
            loan_to_value_pct=25.0,
            liquidation_threshold_pct=80.0,
            oracle_type="chainlink",  # not twap_floor
            blue_chip_collection=True,
            floor_price_volatility_30d_pct=5.0,
            collection_volume_30d_eth=50.0,
        )
        r = self.a.analyze([p], self.cfg)
        self.assertNotEqual(r["positions"][0]["risk_label"], "NFT_FORTRESS")

    def test_label_fortress_requires_blue_chip(self):
        p = _pos(
            loan_to_value_pct=25.0,
            liquidation_threshold_pct=80.0,
            oracle_type="twap_floor",
            blue_chip_collection=False,  # not blue chip
            floor_price_volatility_30d_pct=5.0,
            collection_volume_30d_eth=50.0,
        )
        r = self.a.analyze([p], self.cfg)
        self.assertNotEqual(r["positions"][0]["risk_label"], "NFT_FORTRESS")

    def test_label_low_risk(self):
        # Large buffer, low volatility, chainlink oracle, high volume → low composite
        p = _pos(
            loan_to_value_pct=10.0,
            liquidation_threshold_pct=90.0,
            oracle_type="chainlink",
            floor_price_volatility_30d_pct=2.0,
            collection_volume_30d_eth=100.0,
            wash_trading_score=0.0,
            collection_listings_count=0.0,
            blue_chip_collection=False,
        )
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["positions"][0]["risk_label"], "LOW_RISK")

    def test_label_moderate_risk(self):
        # Moderate conditions → composite 30-60 range
        p = _pos(
            loan_to_value_pct=45.0,
            liquidation_threshold_pct=80.0,
            oracle_type="twap_floor",
            floor_price_volatility_30d_pct=15.0,
            collection_volume_30d_eth=10.0,
            wash_trading_score=30.0,
            collection_listings_count=100.0,
            blue_chip_collection=False,
        )
        r = self.a.analyze([p], self.cfg)
        label = r["positions"][0]["risk_label"]
        # Should be either MODERATE_RISK or HIGH_RISK depending on composite
        self.assertIn(label, ("MODERATE_RISK", "HIGH_RISK"))

    def test_label_imminent_overrides_high_ltv(self):
        # buffer < 10 AND ltv > 70 → LIQUIDATION_IMMINENT wins
        p = _pos(loan_to_value_pct=78.0, liquidation_threshold_pct=80.0,
                 floor_price_volatility_30d_pct=5.0)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["positions"][0]["risk_label"], "LIQUIDATION_IMMINENT")


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolNFTCollateralRiskAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_flag_near_liquidation_buffer_below_15(self):
        p = _pos(loan_to_value_pct=68.0, liquidation_threshold_pct=80.0)
        r = self.a.analyze([p], self.cfg)
        self.assertIn("NEAR_LIQUIDATION", r["positions"][0]["flags"])

    def test_flag_near_liquidation_not_set_when_buffer_ok(self):
        p = _pos(loan_to_value_pct=50.0, liquidation_threshold_pct=80.0)
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn("NEAR_LIQUIDATION", r["positions"][0]["flags"])

    def test_flag_floor_price_oracle(self):
        p = _pos(oracle_type="floor_price")
        r = self.a.analyze([p], self.cfg)
        self.assertIn("FLOOR_PRICE_ORACLE", r["positions"][0]["flags"])

    def test_flag_floor_price_oracle_not_set_for_twap(self):
        p = _pos(oracle_type="twap_floor")
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn("FLOOR_PRICE_ORACLE", r["positions"][0]["flags"])

    def test_flag_high_ltv_nft_above_60(self):
        p = _pos(loan_to_value_pct=65.0, liquidation_threshold_pct=85.0)
        r = self.a.analyze([p], self.cfg)
        self.assertIn("HIGH_LTV_NFT", r["positions"][0]["flags"])

    def test_flag_high_ltv_nft_not_set_at_60(self):
        p = _pos(loan_to_value_pct=60.0, liquidation_threshold_pct=85.0)
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn("HIGH_LTV_NFT", r["positions"][0]["flags"])

    def test_flag_blue_chip_premium(self):
        p = _pos(blue_chip_collection=True)
        r = self.a.analyze([p], self.cfg)
        self.assertIn("BLUE_CHIP_PREMIUM", r["positions"][0]["flags"])

    def test_flag_blue_chip_not_set(self):
        p = _pos(blue_chip_collection=False)
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn("BLUE_CHIP_PREMIUM", r["positions"][0]["flags"])

    def test_flag_wash_trading_suspected_above_60(self):
        p = _pos(wash_trading_score=70.0)
        r = self.a.analyze([p], self.cfg)
        self.assertIn("WASH_TRADING_SUSPECTED", r["positions"][0]["flags"])

    def test_flag_wash_trading_not_set_at_60(self):
        p = _pos(wash_trading_score=60.0)
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn("WASH_TRADING_SUSPECTED", r["positions"][0]["flags"])

    def test_flag_low_liquidity_volume_below_10(self):
        p = _pos(collection_volume_30d_eth=5.0)
        r = self.a.analyze([p], self.cfg)
        self.assertIn("LOW_LIQUIDITY_COLLECTION", r["positions"][0]["flags"])

    def test_flag_low_liquidity_not_set_at_10(self):
        p = _pos(collection_volume_30d_eth=10.0)
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn("LOW_LIQUIDITY_COLLECTION", r["positions"][0]["flags"])

    def test_no_flags_for_safe_position(self):
        p = _pos(
            loan_to_value_pct=20.0,
            liquidation_threshold_pct=90.0,
            oracle_type="chainlink",
            blue_chip_collection=False,
            wash_trading_score=0.0,
            collection_volume_30d_eth=50.0,
        )
        r = self.a.analyze([p], self.cfg)
        flags = r["positions"][0]["flags"]
        self.assertNotIn("NEAR_LIQUIDATION", flags)
        self.assertNotIn("FLOOR_PRICE_ORACLE", flags)
        self.assertNotIn("HIGH_LTV_NFT", flags)
        self.assertNotIn("BLUE_CHIP_PREMIUM", flags)
        self.assertNotIn("WASH_TRADING_SUSPECTED", flags)

    def test_multiple_flags_simultaneously(self):
        p = _pos(
            loan_to_value_pct=68.0,
            liquidation_threshold_pct=80.0,
            oracle_type="floor_price",
            blue_chip_collection=True,
            wash_trading_score=80.0,
            collection_volume_30d_eth=5.0,
        )
        r = self.a.analyze([p], self.cfg)
        flags = r["positions"][0]["flags"]
        self.assertIn("NEAR_LIQUIDATION", flags)
        self.assertIn("FLOOR_PRICE_ORACLE", flags)
        self.assertIn("BLUE_CHIP_PREMIUM", flags)
        self.assertIn("WASH_TRADING_SUSPECTED", flags)
        self.assertIn("LOW_LIQUIDITY_COLLECTION", flags)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolNFTCollateralRiskAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_safest_is_min_composite(self):
        p_safe = _pos("SAFE", loan_to_value_pct=10.0, liquidation_threshold_pct=90.0,
                      oracle_type="chainlink", floor_price_volatility_30d_pct=1.0,
                      collection_volume_30d_eth=100.0, wash_trading_score=0.0)
        p_risky = _pos("RISKY", loan_to_value_pct=75.0, liquidation_threshold_pct=85.0,
                       oracle_type="floor_price", floor_price_volatility_30d_pct=40.0,
                       collection_volume_30d_eth=0.0, wash_trading_score=90.0)
        r = self.a.analyze([p_safe, p_risky], self.cfg)
        self.assertEqual(r["aggregates"]["safest"], "SAFE")

    def test_riskiest_is_max_composite(self):
        p_safe = _pos("SAFE", loan_to_value_pct=10.0, liquidation_threshold_pct=90.0,
                      oracle_type="chainlink", floor_price_volatility_30d_pct=1.0,
                      collection_volume_30d_eth=100.0, wash_trading_score=0.0)
        p_risky = _pos("RISKY", loan_to_value_pct=75.0, liquidation_threshold_pct=85.0,
                       oracle_type="floor_price", floor_price_volatility_30d_pct=40.0,
                       collection_volume_30d_eth=0.0, wash_trading_score=90.0)
        r = self.a.analyze([p_safe, p_risky], self.cfg)
        self.assertEqual(r["aggregates"]["riskiest"], "RISKY")

    def test_avg_composite_risk(self):
        p1 = _pos("A", loan_to_value_pct=10.0, liquidation_threshold_pct=90.0,
                  oracle_type="chainlink", floor_price_volatility_30d_pct=0.0,
                  collection_volume_30d_eth=100.0, wash_trading_score=0.0)
        r = self.a.analyze([p1], self.cfg)
        # avg = same as single position composite
        pos_composite = r["positions"][0]["composite_nft_risk_score"]
        self.assertAlmostEqual(r["aggregates"]["avg_composite_risk"], pos_composite)

    def test_imminent_liquidation_count(self):
        p1 = _pos("IM1", loan_to_value_pct=78.0, liquidation_threshold_pct=80.0)
        p2 = _pos("IM2", loan_to_value_pct=79.0, liquidation_threshold_pct=80.0)
        p3 = _pos("OK", loan_to_value_pct=50.0, liquidation_threshold_pct=80.0)
        r = self.a.analyze([p1, p2, p3], self.cfg)
        self.assertEqual(r["aggregates"]["imminent_liquidation_count"], 2)

    def test_fortress_count(self):
        f = _pos("FORT", loan_to_value_pct=25.0, liquidation_threshold_pct=80.0,
                 oracle_type="twap_floor", blue_chip_collection=True,
                 floor_price_volatility_30d_pct=5.0, collection_volume_30d_eth=50.0,
                 wash_trading_score=5.0)
        other = _pos("OTHER")
        r = self.a.analyze([f, other], self.cfg)
        self.assertEqual(r["aggregates"]["fortress_count"], 1)

    def test_single_position_safest_equals_riskiest(self):
        p = _pos()
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["aggregates"]["safest"], r["aggregates"]["riskiest"])

    def test_avg_composite_multiple(self):
        # Two positions: manually compute expected average
        p1 = _pos("A", loan_to_value_pct=10.0, liquidation_threshold_pct=90.0,
                  oracle_type="chainlink", floor_price_volatility_30d_pct=0.0,
                  collection_volume_30d_eth=100.0, wash_trading_score=0.0,
                  collection_listings_count=0.0)
        p2 = _pos("B", loan_to_value_pct=10.0, liquidation_threshold_pct=90.0,
                  oracle_type="chainlink", floor_price_volatility_30d_pct=0.0,
                  collection_volume_30d_eth=100.0, wash_trading_score=0.0,
                  collection_listings_count=0.0)
        r = self.a.analyze([p1, p2], self.cfg)
        expected = (r["positions"][0]["composite_nft_risk_score"] +
                    r["positions"][1]["composite_nft_risk_score"]) / 2.0
        self.assertAlmostEqual(r["aggregates"]["avg_composite_risk"], expected, places=4)


class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolNFTCollateralRiskAnalyzer()
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_log_file_created(self):
        log = _tmp_log(self.tmp)
        self.a.analyze([_pos()], {"log_file": log})
        self.assertTrue(os.path.exists(log))

    def test_log_is_list(self):
        log = _tmp_log(self.tmp)
        self.a.analyze([_pos()], {"log_file": log})
        with open(log) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_timestamp(self):
        log = _tmp_log(self.tmp)
        self.a.analyze([_pos()], {"log_file": log})
        with open(log) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_aggregates(self):
        log = _tmp_log(self.tmp)
        self.a.analyze([_pos()], {"log_file": log})
        with open(log) as f:
            data = json.load(f)
        self.assertIn("aggregates", data[0])

    def test_log_accumulates_entries(self):
        log = _tmp_log(self.tmp)
        cfg = {"log_file": log}
        self.a.analyze([_pos()], cfg)
        self.a.analyze([_pos()], cfg)
        self.a.analyze([_pos()], cfg)
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_ring_buffer_cap_respected(self):
        log = _tmp_log(self.tmp)
        cfg = {"log_file": log, "ring_buffer_cap": 5}
        for _ in range(10):
            self.a.analyze([_pos()], cfg)
        with open(log) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 5)

    def test_atomic_write_no_partial_file(self):
        log = _tmp_log(self.tmp)
        self.a.analyze([_pos()], {"log_file": log})
        # File should be valid JSON immediately after analyze
        with open(log) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


class TestSinglePosition(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolNFTCollateralRiskAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_single_position_count_one(self):
        r = self.a.analyze([_pos()], self.cfg)
        self.assertEqual(r["position_count"], 1)

    def test_single_position_name_preserved(self):
        r = self.a.analyze([_pos("MY_NFT")], self.cfg)
        self.assertEqual(r["positions"][0]["name"], "MY_NFT")

    def test_single_position_collection_preserved(self):
        r = self.a.analyze([_pos(collection="BAYC")], self.cfg)
        self.assertEqual(r["positions"][0]["collection"], "BAYC")

    def test_single_position_floor_price_preserved(self):
        r = self.a.analyze([_pos(floor_price_eth=42.5)], self.cfg)
        self.assertEqual(r["positions"][0]["floor_price_eth"], 42.5)

    def test_single_position_royalty_preserved(self):
        r = self.a.analyze([_pos(royalty_enforced=True)], self.cfg)
        self.assertTrue(r["positions"][0]["royalty_enforced"])


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolNFTCollateralRiskAnalyzer()
        self.tmp = tempfile.mkdtemp()
        self.cfg = {"log_file": _tmp_log(self.tmp)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_zero_floor_price(self):
        p = _pos(floor_price_eth=0.0)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["positions"][0]["floor_price_eth"], 0.0)

    def test_100_ltv(self):
        p = _pos(loan_to_value_pct=100.0, liquidation_threshold_pct=80.0)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["positions"][0]["risk_label"], "LIQUIDATION_IMMINENT")

    def test_zero_ltv_no_loan(self):
        p = _pos(loan_to_value_pct=0.0)
        r = self.a.analyze([p], self.cfg)
        self.assertGreater(r["positions"][0]["liquidation_buffer_pct"], 0)

    def test_very_high_volatility(self):
        p = _pos(floor_price_volatility_30d_pct=200.0)
        r = self.a.analyze([p], self.cfg)
        self.assertLessEqual(r["positions"][0]["composite_nft_risk_score"], 100.0)

    def test_wash_score_100(self):
        p = _pos(wash_trading_score=100.0)
        r = self.a.analyze([p], self.cfg)
        self.assertIn("WASH_TRADING_SUSPECTED", r["positions"][0]["flags"])

    def test_wash_score_0(self):
        p = _pos(wash_trading_score=0.0)
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn("WASH_TRADING_SUSPECTED", r["positions"][0]["flags"])

    def test_missing_optional_fields_handled(self):
        p = {"name": "MINIMAL", "loan_to_value_pct": 50.0, "liquidation_threshold_pct": 80.0}
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["position_count"], 1)
        self.assertIn("risk_label", r["positions"][0])

    def test_custom_config_thresholds(self):
        cfg = {
            "log_file": _tmp_log(self.tmp),
            "liquidation_imminent_buffer": 5.0,  # lowered threshold
        }
        p = _pos(loan_to_value_pct=77.0, liquidation_threshold_pct=80.0)  # buffer = 3
        r = self.a.analyze([p], cfg)
        self.assertEqual(r["positions"][0]["risk_label"], "LIQUIDATION_IMMINENT")

    def test_large_position_count(self):
        positions = [_pos(name=f"POS-{i}") for i in range(50)]
        r = self.a.analyze(positions, self.cfg)
        self.assertEqual(r["position_count"], 50)

    def test_flags_is_list(self):
        r = self.a.analyze([_pos()], self.cfg)
        self.assertIsInstance(r["positions"][0]["flags"], list)

    def test_no_config_uses_defaults(self):
        # Should not crash without config; log to default path not checked
        r = self.a.analyze([], None)
        self.assertEqual(r["position_count"], 0)

    def test_imminent_count_zero_when_none_imminent(self):
        p = _pos(loan_to_value_pct=30.0, liquidation_threshold_pct=80.0)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["aggregates"]["imminent_liquidation_count"], 0)

    def test_fortress_count_zero_when_none(self):
        p = _pos(blue_chip_collection=False)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["aggregates"]["fortress_count"], 0)


if __name__ == "__main__":
    unittest.main()
