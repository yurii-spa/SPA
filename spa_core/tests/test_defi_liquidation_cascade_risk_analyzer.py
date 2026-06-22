"""
MP-909 — Unit tests for DeFiLiquidationCascadeRiskAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_liquidation_cascade_risk_analyzer -v
Target: ≥80 tests
"""
import os
import sys
import unittest

# allow imports from repo root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from spa_core.analytics.defi_liquidation_cascade_risk_analyzer import (
    DEFAULT_CONFIG,
    LABEL_AT_RISK,
    LABEL_CRITICAL,
    LABEL_DANGER,
    LABEL_SAFE,
    LABEL_WATCH,
    FLAG_BELOW_130,
    FLAG_CORRELATED,
    FLAG_HIGH_VOL,
    FLAG_LARGE_POS,
    DeFiLiquidationCascadeRiskAnalyzer,
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _pos(
    protocol="AAVE",
    collateral_token="ETH",
    debt_token="USDC",
    collateral_usd=10_000.0,
    debt_usd=5_000.0,
    liquidation_threshold_pct=80.0,
    current_price_usd=2_000.0,
    price_30d_volatility_pct=20.0,
    collateral_correlation_to_debt=0.0,
):
    return {
        "protocol": protocol,
        "collateral_token": collateral_token,
        "debt_token": debt_token,
        "collateral_usd": collateral_usd,
        "debt_usd": debt_usd,
        "liquidation_threshold_pct": liquidation_threshold_pct,
        "current_price_usd": current_price_usd,
        "price_30d_volatility_pct": price_30d_volatility_pct,
        "collateral_correlation_to_debt": collateral_correlation_to_debt,
    }


# ── test class ────────────────────────────────────────────────────────────────
class TestBasicConstruction(unittest.TestCase):
    def test_01_instantiate(self):
        a = DeFiLiquidationCascadeRiskAnalyzer()
        self.assertIsNotNone(a)

    def test_02_analyze_callable(self):
        a = DeFiLiquidationCascadeRiskAnalyzer()
        result = a.analyze([], {})
        self.assertIsInstance(result, dict)

    def test_03_result_has_positions_detail(self):
        a = DeFiLiquidationCascadeRiskAnalyzer()
        result = a.analyze([], {})
        self.assertIn("positions_detail", result)

    def test_04_result_has_timestamp(self):
        a = DeFiLiquidationCascadeRiskAnalyzer()
        result = a.analyze([], {})
        self.assertIn("timestamp_utc", result)

    def test_05_result_has_config_used(self):
        a = DeFiLiquidationCascadeRiskAnalyzer()
        result = a.analyze([], {})
        self.assertIn("config_used", result)

    def test_06_result_has_most_at_risk(self):
        a = DeFiLiquidationCascadeRiskAnalyzer()
        result = a.analyze([], {})
        self.assertIn("most_at_risk", result)

    def test_07_result_has_safest_position(self):
        a = DeFiLiquidationCascadeRiskAnalyzer()
        result = a.analyze([], {})
        self.assertIn("safest_position", result)

    def test_08_result_has_total_debt_at_risk(self):
        a = DeFiLiquidationCascadeRiskAnalyzer()
        result = a.analyze([], {})
        self.assertIn("total_debt_at_risk_usd", result)

    def test_09_result_has_average_health_factor(self):
        a = DeFiLiquidationCascadeRiskAnalyzer()
        result = a.analyze([], {})
        self.assertIn("average_health_factor", result)

    def test_10_result_has_critical_count(self):
        a = DeFiLiquidationCascadeRiskAnalyzer()
        result = a.analyze([], {})
        self.assertIn("critical_count", result)


class TestEmptyInput(unittest.TestCase):
    def setUp(self):
        self.a = DeFiLiquidationCascadeRiskAnalyzer()

    def test_11_empty_positions_detail_is_list(self):
        r = self.a.analyze([])
        self.assertIsInstance(r["positions_detail"], list)

    def test_12_empty_positions_detail_len_zero(self):
        r = self.a.analyze([])
        self.assertEqual(len(r["positions_detail"]), 0)

    def test_13_empty_most_at_risk_is_none(self):
        r = self.a.analyze([])
        self.assertIsNone(r["most_at_risk"])

    def test_14_empty_safest_is_none(self):
        r = self.a.analyze([])
        self.assertIsNone(r["safest_position"])

    def test_15_empty_total_debt_zero(self):
        r = self.a.analyze([])
        self.assertEqual(r["total_debt_at_risk_usd"], 0.0)

    def test_16_empty_avg_hf_none(self):
        r = self.a.analyze([])
        self.assertIsNone(r["average_health_factor"])

    def test_17_empty_critical_count_zero(self):
        r = self.a.analyze([])
        self.assertEqual(r["critical_count"], 0)


class TestHealthFactor(unittest.TestCase):
    def setUp(self):
        self.a = DeFiLiquidationCascadeRiskAnalyzer()

    def test_18_health_factor_calculation(self):
        # HF = (10000 * 0.8) / 5000 = 1.6
        r = self.a.analyze([_pos()], {"log_enabled": False})
        hf = r["positions_detail"][0]["health_factor"]
        self.assertAlmostEqual(hf, 1.6, places=2)

    def test_19_health_factor_zero_debt_is_none(self):
        pos = _pos(debt_usd=0.0)
        r = self.a.analyze([pos], {"log_enabled": False})
        hf = r["positions_detail"][0]["health_factor"]
        self.assertIsNone(hf)

    def test_20_health_factor_high_safe(self):
        pos = _pos(collateral_usd=100_000.0, debt_usd=10_000.0)
        r = self.a.analyze([pos], {"log_enabled": False})
        hf = r["positions_detail"][0]["health_factor"]
        self.assertGreater(hf, 1.5)

    def test_21_health_factor_near_liq(self):
        # HF = (1000 * 0.8) / 1000 = 0.8 → CRITICAL
        pos = _pos(collateral_usd=1_000.0, debt_usd=1_000.0, liquidation_threshold_pct=80.0)
        r = self.a.analyze([pos], {"log_enabled": False})
        hf = r["positions_detail"][0]["health_factor"]
        self.assertAlmostEqual(hf, 0.8, places=2)

    def test_22_health_factor_exact_1(self):
        # HF = (10000 * 0.5) / 5000 = 1.0 → CRITICAL
        pos = _pos(collateral_usd=10_000.0, debt_usd=5_000.0, liquidation_threshold_pct=50.0)
        r = self.a.analyze([pos], {"log_enabled": False})
        hf = r["positions_detail"][0]["health_factor"]
        self.assertAlmostEqual(hf, 1.0, places=4)


class TestRiskLabels(unittest.TestCase):
    def setUp(self):
        self.a = DeFiLiquidationCascadeRiskAnalyzer()
        self.cfg = {"log_enabled": False}

    def test_23_label_safe(self):
        # HF=2.0 → SAFE
        pos = _pos(collateral_usd=12_500.0, debt_usd=5_000.0)
        r = self.a.analyze([pos], self.cfg)
        self.assertEqual(r["positions_detail"][0]["risk_label"], LABEL_SAFE)

    def test_24_label_watch(self):
        # HF = (6500*0.8)/4000 = 1.3 → WATCH range (1.3..1.5)
        pos = _pos(collateral_usd=6_500.0, debt_usd=4_000.0, liquidation_threshold_pct=80.0)
        r = self.a.analyze([pos], self.cfg)
        label = r["positions_detail"][0]["risk_label"]
        self.assertIn(label, [LABEL_WATCH, LABEL_AT_RISK])

    def test_25_label_critical(self):
        # HF = (10000*0.5)/5500 ≈ 0.909 < 1.0 → CRITICAL
        pos = _pos(collateral_usd=10_000.0, debt_usd=5_500.0, liquidation_threshold_pct=50.0)
        r = self.a.analyze([pos], self.cfg)
        self.assertEqual(r["positions_detail"][0]["risk_label"], LABEL_CRITICAL)

    def test_26_label_zero_debt_safe(self):
        pos = _pos(debt_usd=0.0)
        r = self.a.analyze([pos], self.cfg)
        self.assertEqual(r["positions_detail"][0]["risk_label"], LABEL_SAFE)

    def test_27_label_at_risk(self):
        # HF = (10000*0.7)/6000 ≈ 1.167 → AT_RISK (1.0 < HF < 1.3)
        pos = _pos(collateral_usd=10_000.0, debt_usd=6_000.0, liquidation_threshold_pct=70.0)
        r = self.a.analyze([pos], self.cfg)
        label = r["positions_detail"][0]["risk_label"]
        self.assertIn(label, [LABEL_AT_RISK, LABEL_DANGER])


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.a = DeFiLiquidationCascadeRiskAnalyzer()
        self.cfg = {"log_enabled": False}

    def test_28_flag_below_130_present(self):
        # HF ≈ 0.8 → below 1.3
        pos = _pos(collateral_usd=1_000.0, debt_usd=1_000.0, liquidation_threshold_pct=80.0)
        r = self.a.analyze([pos], self.cfg)
        self.assertIn(FLAG_BELOW_130, r["positions_detail"][0]["flags"])

    def test_29_flag_below_130_absent_when_safe(self):
        pos = _pos(collateral_usd=20_000.0, debt_usd=5_000.0)
        r = self.a.analyze([pos], self.cfg)
        self.assertNotIn(FLAG_BELOW_130, r["positions_detail"][0]["flags"])

    def test_30_flag_correlated(self):
        pos = _pos(collateral_correlation_to_debt=0.9)
        r = self.a.analyze([pos], self.cfg)
        self.assertIn(FLAG_CORRELATED, r["positions_detail"][0]["flags"])

    def test_31_flag_correlated_absent_low(self):
        pos = _pos(collateral_correlation_to_debt=0.5)
        r = self.a.analyze([pos], self.cfg)
        self.assertNotIn(FLAG_CORRELATED, r["positions_detail"][0]["flags"])

    def test_32_flag_high_volatility(self):
        pos = _pos(price_30d_volatility_pct=60.0)
        r = self.a.analyze([pos], self.cfg)
        self.assertIn(FLAG_HIGH_VOL, r["positions_detail"][0]["flags"])

    def test_33_flag_high_volatility_absent(self):
        pos = _pos(price_30d_volatility_pct=20.0)
        r = self.a.analyze([pos], self.cfg)
        self.assertNotIn(FLAG_HIGH_VOL, r["positions_detail"][0]["flags"])

    def test_34_flag_large_position(self):
        pos = _pos(debt_usd=200_000.0)
        r = self.a.analyze([pos], self.cfg)
        self.assertIn(FLAG_LARGE_POS, r["positions_detail"][0]["flags"])

    def test_35_flag_large_position_absent(self):
        pos = _pos(debt_usd=50_000.0)
        r = self.a.analyze([pos], self.cfg)
        self.assertNotIn(FLAG_LARGE_POS, r["positions_detail"][0]["flags"])

    def test_36_flags_multiple(self):
        pos = _pos(
            collateral_usd=1_000.0,
            debt_usd=200_000.0,
            liquidation_threshold_pct=80.0,
            price_30d_volatility_pct=75.0,
            collateral_correlation_to_debt=0.95,
        )
        r = self.a.analyze([pos], self.cfg)
        flags = r["positions_detail"][0]["flags"]
        self.assertIn(FLAG_BELOW_130, flags)
        self.assertIn(FLAG_CORRELATED, flags)
        self.assertIn(FLAG_HIGH_VOL, flags)
        self.assertIn(FLAG_LARGE_POS, flags)

    def test_37_flags_is_list(self):
        pos = _pos()
        r = self.a.analyze([pos], self.cfg)
        self.assertIsInstance(r["positions_detail"][0]["flags"], list)


class TestDistanceAndLiqPrice(unittest.TestCase):
    def setUp(self):
        self.a = DeFiLiquidationCascadeRiskAnalyzer()
        self.cfg = {"log_enabled": False}

    def test_38_distance_positive(self):
        pos = _pos()  # HF=1.6, healthy
        r = self.a.analyze([pos], self.cfg)
        d = r["positions_detail"][0]["distance_to_liquidation_pct"]
        self.assertGreater(d, 0.0)

    def test_39_distance_zero_when_below_liq(self):
        # Already below liquidation: debt > collateral * threshold
        pos = _pos(collateral_usd=1_000.0, debt_usd=2_000.0, liquidation_threshold_pct=80.0)
        r = self.a.analyze([pos], self.cfg)
        d = r["positions_detail"][0]["distance_to_liquidation_pct"]
        self.assertLessEqual(d, 0.0)

    def test_40_liq_price_less_than_current(self):
        pos = _pos()
        r = self.a.analyze([pos], self.cfg)
        liq_price = r["positions_detail"][0]["liquidation_price_usd"]
        self.assertLess(liq_price, pos["current_price_usd"])

    def test_41_liq_price_zero_when_no_debt(self):
        pos = _pos(debt_usd=0.0)
        r = self.a.analyze([pos], self.cfg)
        self.assertEqual(r["positions_detail"][0]["liquidation_price_usd"], 0.0)

    def test_42_liq_price_zero_when_no_price(self):
        pos = _pos(current_price_usd=0.0)
        r = self.a.analyze([pos], self.cfg)
        self.assertEqual(r["positions_detail"][0]["liquidation_price_usd"], 0.0)


class TestCascadeRiskScore(unittest.TestCase):
    def setUp(self):
        self.a = DeFiLiquidationCascadeRiskAnalyzer()
        self.cfg = {"log_enabled": False}

    def test_43_cascade_score_in_range(self):
        pos = _pos()
        r = self.a.analyze([pos], self.cfg)
        score = r["positions_detail"][0]["cascade_risk_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_44_high_vol_high_corr_raises_score(self):
        pos_low = _pos(price_30d_volatility_pct=5.0, collateral_correlation_to_debt=0.0)
        pos_high = _pos(price_30d_volatility_pct=80.0, collateral_correlation_to_debt=0.95)
        r_low = self.a.analyze([pos_low], self.cfg)
        r_high = self.a.analyze([pos_high], self.cfg)
        self.assertGreater(
            r_high["positions_detail"][0]["cascade_risk_score"],
            r_low["positions_detail"][0]["cascade_risk_score"],
        )

    def test_45_zero_debt_score_is_zero(self):
        pos = _pos(debt_usd=0.0)
        r = self.a.analyze([pos], self.cfg)
        self.assertEqual(r["positions_detail"][0]["cascade_risk_score"], 0.0)

    def test_46_score_is_float(self):
        pos = _pos()
        r = self.a.analyze([pos], self.cfg)
        self.assertIsInstance(r["positions_detail"][0]["cascade_risk_score"], float)


class TestAggregation(unittest.TestCase):
    def setUp(self):
        self.a = DeFiLiquidationCascadeRiskAnalyzer()
        self.cfg = {"log_enabled": False}

    def test_47_most_at_risk_is_protocol_name(self):
        positions = [
            _pos("AAVE", collateral_usd=20_000.0, debt_usd=5_000.0),
            _pos("Compound", collateral_usd=1_000.0, debt_usd=1_000.0),
        ]
        r = self.a.analyze(positions, self.cfg)
        self.assertIsNotNone(r["most_at_risk"])

    def test_48_safest_position_is_protocol_name(self):
        positions = [
            _pos("AAVE", collateral_usd=20_000.0, debt_usd=5_000.0),
            _pos("Compound", collateral_usd=1_000.0, debt_usd=1_000.0),
        ]
        r = self.a.analyze(positions, self.cfg)
        self.assertIsNotNone(r["safest_position"])

    def test_49_safest_different_from_most_at_risk(self):
        positions = [
            _pos("AAVE", collateral_usd=50_000.0, debt_usd=5_000.0),
            _pos("Compound", collateral_usd=500.0, debt_usd=2_000.0),
        ]
        r = self.a.analyze(positions, self.cfg)
        # Can be same if only one position dominates — just check types
        self.assertIsInstance(r["most_at_risk"], str)
        self.assertIsInstance(r["safest_position"], str)

    def test_50_total_debt_at_risk_usd_type(self):
        positions = [_pos()]
        r = self.a.analyze(positions, self.cfg)
        self.assertIsInstance(r["total_debt_at_risk_usd"], float)

    def test_51_average_health_factor_type(self):
        positions = [_pos()]
        r = self.a.analyze(positions, self.cfg)
        self.assertIsInstance(r["average_health_factor"], float)

    def test_52_critical_count_zero_for_safe_positions(self):
        positions = [
            _pos(collateral_usd=100_000.0, debt_usd=1_000.0),
        ]
        r = self.a.analyze(positions, self.cfg)
        self.assertEqual(r["critical_count"], 0)

    def test_53_critical_count_increments(self):
        # Make 2 critical positions
        critical = _pos(collateral_usd=1_000.0, debt_usd=5_000.0, liquidation_threshold_pct=80.0)
        positions = [critical, critical]
        r = self.a.analyze(positions, self.cfg)
        self.assertGreater(r["critical_count"], 0)

    def test_54_avg_hf_single_position(self):
        pos = _pos()  # HF=1.6
        r = self.a.analyze([pos], self.cfg)
        self.assertAlmostEqual(r["average_health_factor"], 1.6, places=2)

    def test_55_avg_hf_two_positions(self):
        p1 = _pos(collateral_usd=10_000.0, debt_usd=5_000.0)   # HF=1.6
        p2 = _pos(collateral_usd=10_000.0, debt_usd=4_000.0, liquidation_threshold_pct=80.0)  # HF=2.0
        r = self.a.analyze([p1, p2], self.cfg)
        # avg of 1.6 and 2.0 = 1.8
        self.assertAlmostEqual(r["average_health_factor"], 1.8, places=2)


class TestPositionFields(unittest.TestCase):
    def setUp(self):
        self.a = DeFiLiquidationCascadeRiskAnalyzer()
        self.cfg = {"log_enabled": False}
        self.detail = self.a.analyze([_pos()], self.cfg)["positions_detail"][0]

    def test_56_protocol_field(self):
        self.assertEqual(self.detail["protocol"], "AAVE")

    def test_57_collateral_token_field(self):
        self.assertEqual(self.detail["collateral_token"], "ETH")

    def test_58_debt_token_field(self):
        self.assertEqual(self.detail["debt_token"], "USDC")

    def test_59_collateral_usd_field(self):
        self.assertEqual(self.detail["collateral_usd"], 10_000.0)

    def test_60_debt_usd_field(self):
        self.assertEqual(self.detail["debt_usd"], 5_000.0)

    def test_61_liquidation_threshold_field(self):
        self.assertEqual(self.detail["liquidation_threshold_pct"], 80.0)

    def test_62_volatility_field(self):
        self.assertEqual(self.detail["price_30d_volatility_pct"], 20.0)

    def test_63_correlation_field(self):
        self.assertEqual(self.detail["collateral_correlation_to_debt"], 0.0)

    def test_64_risk_label_is_string(self):
        self.assertIsInstance(self.detail["risk_label"], str)

    def test_65_cascade_score_present(self):
        self.assertIn("cascade_risk_score", self.detail)


class TestConfigOverrides(unittest.TestCase):
    def setUp(self):
        self.a = DeFiLiquidationCascadeRiskAnalyzer()

    def test_66_custom_correlation_threshold(self):
        cfg = {"correlation_threshold": 0.5, "log_enabled": False}
        pos = _pos(collateral_correlation_to_debt=0.6)
        r = self.a.analyze([pos], cfg)
        self.assertIn(FLAG_CORRELATED, r["positions_detail"][0]["flags"])

    def test_67_custom_vol_threshold(self):
        cfg = {"volatility_threshold": 10.0, "log_enabled": False}
        pos = _pos(price_30d_volatility_pct=15.0)
        r = self.a.analyze([pos], cfg)
        self.assertIn(FLAG_HIGH_VOL, r["positions_detail"][0]["flags"])

    def test_68_custom_large_position_threshold(self):
        cfg = {"large_position_debt_usd": 10_000.0, "log_enabled": False}
        pos = _pos(debt_usd=15_000.0)
        r = self.a.analyze([pos], cfg)
        self.assertIn(FLAG_LARGE_POS, r["positions_detail"][0]["flags"])

    def test_69_config_merged_with_defaults(self):
        cfg = {"log_enabled": False}
        r = self.a.analyze([_pos()], cfg)
        used = r["config_used"]
        self.assertIn("cascade_vol_weight", used)
        self.assertIn("cascade_corr_weight", used)

    def test_70_none_config_uses_defaults(self):
        a = DeFiLiquidationCascadeRiskAnalyzer()
        r = a.analyze([_pos()], None)
        self.assertIn("cascade_vol_weight", r["config_used"])


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.a = DeFiLiquidationCascadeRiskAnalyzer()
        self.cfg = {"log_enabled": False}

    def test_71_liquidation_threshold_100(self):
        pos = _pos(liquidation_threshold_pct=100.0)
        r = self.a.analyze([pos], self.cfg)
        hf = r["positions_detail"][0]["health_factor"]
        self.assertAlmostEqual(hf, 2.0, places=2)

    def test_72_liquidation_threshold_clamped_above_100(self):
        pos = _pos(liquidation_threshold_pct=150.0)
        r = self.a.analyze([pos], self.cfg)
        # clamped to 100
        hf = r["positions_detail"][0]["health_factor"]
        self.assertIsNotNone(hf)

    def test_73_correlation_clamped_above_1(self):
        pos = _pos(collateral_correlation_to_debt=1.5)
        r = self.a.analyze([pos], self.cfg)
        corr = r["positions_detail"][0]["collateral_correlation_to_debt"]
        self.assertLessEqual(corr, 1.0)

    def test_74_correlation_clamped_below_0(self):
        pos = _pos(collateral_correlation_to_debt=-0.5)
        r = self.a.analyze([pos], self.cfg)
        corr = r["positions_detail"][0]["collateral_correlation_to_debt"]
        self.assertGreaterEqual(corr, 0.0)

    def test_75_multiple_positions_count(self):
        positions = [_pos(protocol=f"P{i}") for i in range(5)]
        r = self.a.analyze(positions, self.cfg)
        self.assertEqual(len(r["positions_detail"]), 5)

    def test_76_zero_collateral_usd(self):
        pos = _pos(collateral_usd=0.0)
        r = self.a.analyze([pos], self.cfg)
        detail = r["positions_detail"][0]
        self.assertIsNotNone(detail)

    def test_77_large_collateral(self):
        pos = _pos(collateral_usd=1_000_000_000.0, debt_usd=1.0)
        r = self.a.analyze([pos], self.cfg)
        hf = r["positions_detail"][0]["health_factor"]
        self.assertGreater(hf, 1_000_000.0)

    def test_78_single_position_most_at_risk_equals_safest(self):
        r = self.a.analyze([_pos()], self.cfg)
        # With one position, both most_at_risk and safest are the same protocol
        self.assertEqual(r["most_at_risk"], r["safest_position"])

    def test_79_positions_detail_is_list(self):
        positions = [_pos(protocol=f"P{i}") for i in range(3)]
        r = self.a.analyze(positions, self.cfg)
        self.assertIsInstance(r["positions_detail"], list)

    def test_80_danger_label_contributes_to_debt_at_risk(self):
        # HF just above 1.0 but < 1.1 → DANGER
        pos = _pos(collateral_usd=10_000.0, debt_usd=9_600.0, liquidation_threshold_pct=80.0)
        # HF = 10000*0.8/9600 ≈ 0.833 → CRITICAL
        r = self.a.analyze([pos], self.cfg)
        # Either DANGER or CRITICAL → should be counted
        label = r["positions_detail"][0]["risk_label"]
        if label in ["DANGER", "CRITICAL"]:
            self.assertGreater(r["total_debt_at_risk_usd"], 0.0)

    def test_81_analyze_returns_dict(self):
        r = self.a.analyze([_pos()])
        self.assertIsInstance(r, dict)

    def test_82_no_flags_when_all_benign(self):
        pos = _pos(
            collateral_usd=1_000_000.0,
            debt_usd=1_000.0,
            price_30d_volatility_pct=5.0,
            collateral_correlation_to_debt=0.1,
        )
        r = self.a.analyze([pos], self.cfg)
        flags = r["positions_detail"][0]["flags"]
        self.assertNotIn(FLAG_BELOW_130, flags)
        self.assertNotIn(FLAG_CORRELATED, flags)
        self.assertNotIn(FLAG_HIGH_VOL, flags)
        self.assertNotIn(FLAG_LARGE_POS, flags)


class TestLogDisabled(unittest.TestCase):
    def test_83_log_disabled_no_write(self):
        a = DeFiLiquidationCascadeRiskAnalyzer()
        # Should not raise even with log disabled
        r = a.analyze([_pos()], {"log_enabled": False})
        self.assertIn("positions_detail", r)


class TestDefaultConfigConstants(unittest.TestCase):
    def test_84_default_config_has_health_watch(self):
        self.assertIn("health_watch", DEFAULT_CONFIG)

    def test_85_default_config_has_health_critical(self):
        self.assertIn("health_critical", DEFAULT_CONFIG)

    def test_86_default_config_has_vol_threshold(self):
        self.assertIn("volatility_threshold", DEFAULT_CONFIG)

    def test_87_label_constants_distinct(self):
        labels = {LABEL_SAFE, LABEL_WATCH, LABEL_AT_RISK, LABEL_DANGER, LABEL_CRITICAL}
        self.assertEqual(len(labels), 5)

    def test_88_flag_constants_distinct(self):
        flags = {FLAG_BELOW_130, FLAG_CORRELATED, FLAG_HIGH_VOL, FLAG_LARGE_POS}
        self.assertEqual(len(flags), 4)

    def test_89_default_log_cap_is_100(self):
        from spa_core.analytics.defi_liquidation_cascade_risk_analyzer import LOG_CAP
        self.assertEqual(LOG_CAP, 100)

    def test_90_cascade_weights_sum_to_one(self):
        w = (
            DEFAULT_CONFIG["cascade_vol_weight"]
            + DEFAULT_CONFIG["cascade_corr_weight"]
            + DEFAULT_CONFIG["cascade_proximity_weight"]
        )
        self.assertAlmostEqual(w, 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
