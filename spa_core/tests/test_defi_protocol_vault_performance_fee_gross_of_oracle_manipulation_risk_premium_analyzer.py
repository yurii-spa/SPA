"""
Tests for MP-1252:
DeFiProtocolVaultPerformanceFeeGrossOfOracleManipulationRiskPremiumAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_performance_fee_gross_of_oracle_manipulation_risk_premium_analyzer -v
"""

import json
import math
import os
import sys
import unittest
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.gross_of.defi_protocol_vault_performance_fee_gross_of_oracle_manipulation_risk_premium_analyzer import (  # noqa: E501
    GrossOfOracleManipulationRiskPremiumAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _coerce_num,
    _coerce_signed,
    _coerce_count,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    CLEAN_FRACTION,
    MILD_FRACTION,
    MODERATE_FRACTION,
    HIGH_ORACLE_MANIPULATION_RISK_PREMIUM_PCT,
    EPS,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    gross_yield_pct=None,
    net_of_oracle_manipulation_risk_premium_yield_pct=None,
    performance_fee_pct=None,
    oracle_manipulation_risk_premium_rate_pct=None,
    oracle_manipulation_risk_premium_gap_pct=None,
    fee_charged_pct=None,
):
    pos = {"vault": vault}
    if gross_yield_pct is not None:
        pos["gross_yield_pct"] = gross_yield_pct
    if net_of_oracle_manipulation_risk_premium_yield_pct is not None:
        pos["net_of_oracle_manipulation_risk_premium_yield_pct"] = net_of_oracle_manipulation_risk_premium_yield_pct
    if performance_fee_pct is not None:
        pos["performance_fee_pct"] = performance_fee_pct
    if oracle_manipulation_risk_premium_rate_pct is not None:
        pos["oracle_manipulation_risk_premium_rate_pct"] = oracle_manipulation_risk_premium_rate_pct
    if oracle_manipulation_risk_premium_gap_pct is not None:
        pos["oracle_manipulation_risk_premium_gap_pct"] = oracle_manipulation_risk_premium_gap_pct
    if fee_charged_pct is not None:
        pos["fee_charged_pct"] = fee_charged_pct
    return pos


def _all_floats_finite(obj):
    """Recursively assert every float in a result structure is finite."""
    if isinstance(obj, float):
        return math.isfinite(obj)
    if isinstance(obj, dict):
        return all(_all_floats_finite(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_all_floats_finite(v) for v in obj)
    return True


# ── helper tests ────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    def test_f_default(self):
        self.assertEqual(_f(None), 0.0)
        self.assertEqual(_f(None, 3.0), 3.0)
        self.assertEqual(_f("x", 1.0), 1.0)
        self.assertEqual(_f("2.5"), 2.5)
        self.assertEqual(_f(4), 4.0)

    def test_clamp(self):
        self.assertEqual(_clamp(5, 0, 1), 1)
        self.assertEqual(_clamp(-5, 0, 1), 0)
        self.assertEqual(_clamp(0.5, 0, 1), 0.5)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertEqual(_mean([2, 4]), 3.0)
        self.assertAlmostEqual(_mean([1.0, 2.0, 3.0]), 2.0, places=6)

    def test_safe_div_positive(self):
        self.assertEqual(_safe_div(10, 2, None), 5.0)

    def test_safe_div_zero_den(self):
        self.assertIsNone(_safe_div(10, 0, None))

    def test_safe_div_negative_den(self):
        self.assertIsNone(_safe_div(10, -1, None))

    def test_coerce_num_basic(self):
        self.assertAlmostEqual(_coerce_num(3.14), 3.14)
        self.assertAlmostEqual(_coerce_num("2.5"), 2.5)
        self.assertAlmostEqual(_coerce_num(5), 5.0)

    def test_coerce_num_rejects_bool(self):
        self.assertIsNone(_coerce_num(True))
        self.assertIsNone(_coerce_num(False))

    def test_coerce_num_rejects_nan_inf(self):
        self.assertIsNone(_coerce_num(float("nan")))
        self.assertIsNone(_coerce_num(float("inf")))
        self.assertIsNone(_coerce_num(float("-inf")))

    def test_coerce_signed_accepts_negative(self):
        self.assertAlmostEqual(_coerce_signed(-3.5), -3.5)

    def test_coerce_count_basic(self):
        self.assertEqual(_coerce_count(5), 5)
        self.assertEqual(_coerce_count(0), 0)
        self.assertIsNone(_coerce_count(-1))

    def test_grade_from_score_boundaries(self):
        self.assertEqual(_grade_from_score(100.0), "A")
        self.assertEqual(_grade_from_score(85.0), "A")
        self.assertEqual(_grade_from_score(84.9), "B")
        self.assertEqual(_grade_from_score(70.0), "B")
        self.assertEqual(_grade_from_score(69.9), "C")
        self.assertEqual(_grade_from_score(55.0), "C")
        self.assertEqual(_grade_from_score(54.9), "D")
        self.assertEqual(_grade_from_score(40.0), "D")
        self.assertEqual(_grade_from_score(39.9), "F")
        self.assertEqual(_grade_from_score(0.0), "F")


# ── main-path classification ───────────────────────────────────────────────

class TestMainPathClassification(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfOracleManipulationRiskPremiumAnalyzer()

    def test_clean_equal_net_gross(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"],
                         "CLEAN_NET_OF_ORACLE_MANIPULATION_RISK_PREMIUM_BASE")
        self.assertIn("CLEAN_NET_BASE", r["flags"])

    def test_clean_net_slightly_below_gross(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=14.8,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"],
                         "CLEAN_NET_OF_ORACLE_MANIPULATION_RISK_PREMIUM_BASE")

    def test_mild_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=16.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(
            r["fee_on_oracle_manipulation_risk_premium_fraction"], 0.2, places=4)
        self.assertEqual(r["classification"],
                         "MILD_FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM_GAP")

    def test_moderate_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=10.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(
            r["fee_on_oracle_manipulation_risk_premium_fraction"], 0.5, places=4)
        self.assertEqual(r["classification"],
                         "MODERATE_FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM_GAP")

    def test_severe_gap_high_fraction(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=4.0,
            performance_fee_pct=20.0))
        self.assertGreater(r["fee_on_oracle_manipulation_risk_premium_fraction"], 0.50)
        self.assertEqual(r["classification"],
                         "SEVERE_FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM_GAP")

    def test_severe_gap_net_negative(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=-2.0,
            performance_fee_pct=50.0))
        self.assertEqual(r["classification"],
                         "SEVERE_FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM_GAP")
        self.assertTrue(r["net_is_negative"])

    def test_net_zero_yields_full_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=0.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(
            r["fee_on_oracle_manipulation_risk_premium_fraction"], 1.0, places=4)
        self.assertEqual(r["classification"],
                         "SEVERE_FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM_GAP")

    def test_recommendation_clean(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"], "TRUST_FEE_STRUCTURE")

    def test_recommendation_mild(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=16.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"], "MINOR_FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM")

    def test_recommendation_moderate(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=10.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"],
                         "DEMAND_NET_OF_ORACLE_MANIPULATION_RISK_PREMIUM_BASE")

    def test_recommendation_severe(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=-2.0,
            performance_fee_pct=50.0))
        self.assertEqual(r["recommendation"], "AVOID_FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM")

    def test_used_main_true(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertTrue(r["used_main"])
        self.assertFalse(r["used_override"])


# ── math precision tests ───────────────────────────────────────────────────

class TestMath(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfOracleManipulationRiskPremiumAnalyzer()

    def test_fee_charged_formula(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=14.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["fee_charged_pct"], 20.0 * 0.2, places=4)

    def test_fair_fee_formula(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=14.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["fair_fee_pct"], 14.0 * 0.2, places=4)

    def test_gap_formula(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=14.0,
            performance_fee_pct=20.0))
        expected_gap = 20.0 * 0.2 - 14.0 * 0.2
        self.assertAlmostEqual(
            r["oracle_manipulation_risk_premium_gap_pct"], expected_gap, places=4)

    def test_fraction_formula(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=14.0,
            performance_fee_pct=20.0))
        charged = 20.0 * 0.2
        gap = (20.0 - 14.0) * 0.2
        self.assertAlmostEqual(
            r["fee_on_oracle_manipulation_risk_premium_fraction"], gap / charged, places=4)

    def test_oracle_manip_consumed_formula(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=14.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(
            r["oracle_manipulation_risk_premium_consumed_yield_pct"], 6.0, places=4)

    def test_net_return_after_fee(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=14.0,
            performance_fee_pct=20.0))
        expected = 14.0 - 20.0 * 0.2
        self.assertAlmostEqual(r["net_return_after_fee_pct"], expected, places=4)

    def test_net_return_fair(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=14.0,
            performance_fee_pct=20.0))
        expected = 14.0 - 14.0 * 0.2
        self.assertAlmostEqual(r["net_return_fair_pct"], expected, places=4)

    def test_overstatement_equals_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=12.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["overstatement_pct"],
                               r["oracle_manipulation_risk_premium_gap_pct"], places=4)

    def test_realization_ratio_clean(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["realization_ratio"], 1.0, places=4)

    def test_realization_ratio_bounds(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=-3.0,
            performance_fee_pct=50.0))
        self.assertGreaterEqual(r["realization_ratio"], 0.0)
        self.assertLessEqual(r["realization_ratio"], 1.0)

    def test_performance_fee_pct_clamped_high(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=8.0,
            performance_fee_pct=200.0))
        self.assertAlmostEqual(r["performance_fee_pct"], 100.0, places=2)
        self.assertAlmostEqual(r["fee_charged_pct"], 10.0, places=4)

    def test_performance_fee_pct_clamped_low(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=8.0,
            performance_fee_pct=-50.0))
        self.assertAlmostEqual(r["performance_fee_pct"], 0.0, places=2)
        self.assertAlmostEqual(r["fee_charged_pct"], 0.0, places=4)
        self.assertAlmostEqual(
            r["oracle_manipulation_risk_premium_gap_pct"], 0.0, places=4)
        self.assertEqual(r["classification"],
                         "CLEAN_NET_OF_ORACLE_MANIPULATION_RISK_PREMIUM_BASE")

    def test_net_above_gross_clamps_consumed_zero(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=12.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(
            r["oracle_manipulation_risk_premium_consumed_yield_pct"], 0.0, places=4)
        self.assertAlmostEqual(
            r["oracle_manipulation_risk_premium_gap_pct"], 0.0, places=4)
        self.assertEqual(r["classification"],
                         "CLEAN_NET_OF_ORACLE_MANIPULATION_RISK_PREMIUM_BASE")

    def test_zero_fee_rate_always_clean(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=10.0,
            performance_fee_pct=0.0))
        self.assertAlmostEqual(
            r["oracle_manipulation_risk_premium_gap_pct"], 0.0, places=4)
        self.assertAlmostEqual(
            r["fee_on_oracle_manipulation_risk_premium_fraction"], 0.0, places=4)
        self.assertEqual(r["classification"],
                         "CLEAN_NET_OF_ORACLE_MANIPULATION_RISK_PREMIUM_BASE")


# ── override path ─────────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfOracleManipulationRiskPremiumAnalyzer()

    def test_override_basic(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            oracle_manipulation_risk_premium_gap_pct=4.8,
            fee_charged_pct=12.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_main"])
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])
        self.assertAlmostEqual(
            r["fee_on_oracle_manipulation_risk_premium_fraction"], 0.4, places=4)
        self.assertEqual(r["classification"],
                         "MODERATE_FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM_GAP")

    def test_override_geometry_none(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            oracle_manipulation_risk_premium_gap_pct=4.8,
            fee_charged_pct=12.0))
        self.assertIsNone(r["net_of_oracle_manipulation_risk_premium_yield_pct"])
        self.assertIsNone(r["oracle_manipulation_risk_premium_consumed_yield_pct"])
        self.assertIsNone(r["net_return_after_fee_pct"])
        self.assertIsNone(r["net_return_fair_pct"])
        self.assertIsNone(r["performance_fee_pct"])

    def test_override_geometry_flags_suppressed(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            oracle_manipulation_risk_premium_gap_pct=4.8,
            fee_charged_pct=12.0))
        self.assertNotIn("FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM", r["flags"])
        self.assertNotIn("FULL_FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM", r["flags"])
        self.assertNotIn("NET_NEGATIVE_AFTER_FEE", r["flags"])

    def test_override_negative_gap_magnitude(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            oracle_manipulation_risk_premium_gap_pct=-4.8,
            fee_charged_pct=12.0))
        self.assertAlmostEqual(
            r["oracle_manipulation_risk_premium_gap_pct"], 4.8, places=4)

    def test_override_gap_capped_at_fee_charged(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            oracle_manipulation_risk_premium_gap_pct=99.0,
            fee_charged_pct=12.0))
        self.assertEqual(r["oracle_manipulation_risk_premium_gap_pct"], 12.0)
        self.assertEqual(r["fee_on_oracle_manipulation_risk_premium_fraction"], 1.0)
        self.assertEqual(r["fair_fee_pct"], 0.0)

    def test_override_realization_anchor(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            oracle_manipulation_risk_premium_gap_pct=3.0,
            fee_charged_pct=12.0))
        frac = r["fee_on_oracle_manipulation_risk_premium_fraction"]
        self.assertAlmostEqual(r["realization_ratio"], 1.0 - frac, places=4)

    def test_override_denominator_is_fee_charged(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            oracle_manipulation_risk_premium_gap_pct=3.0,
            fee_charged_pct=12.0))
        self.assertAlmostEqual(
            r["fee_on_oracle_manipulation_risk_premium_fraction"], 3.0 / 12.0, places=4)

    def test_override_high_oracle_manip_still_flagged(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            oracle_manipulation_risk_premium_gap_pct=3.0,
            fee_charged_pct=12.0,
            oracle_manipulation_risk_premium_rate_pct=0.6))
        self.assertIn("HIGH_ORACLE_MANIPULATION_RISK_PREMIUM", r["flags"])
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])

    def test_override_requires_positive_fee_charged(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            oracle_manipulation_risk_premium_gap_pct=3.0,
            fee_charged_pct=0.0,
            performance_fee_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=20.0))
        self.assertFalse(r["used_override"])
        self.assertTrue(r["used_main"])

    def test_override_clean_when_small_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            oracle_manipulation_risk_premium_gap_pct=0.3,
            fee_charged_pct=12.0))
        self.assertEqual(r["classification"],
                         "CLEAN_NET_OF_ORACLE_MANIPULATION_RISK_PREMIUM_BASE")
        self.assertIn("CLEAN_NET_BASE", r["flags"])

    def test_override_severe_when_large_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            oracle_manipulation_risk_premium_gap_pct=10.0,
            fee_charged_pct=12.0))
        self.assertEqual(r["classification"],
                         "SEVERE_FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM_GAP")


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfOracleManipulationRiskPremiumAnalyzer()

    def test_missing_gross(self):
        r = self.an.analyze(make_pos(
            performance_fee_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_zero_gross(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=0.0, performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_gross(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=-5.0, performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_gross(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=float("nan"), performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_gross(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=float("inf"), performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_fee_main_path(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_fee_main_path(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=5.0,
            performance_fee_pct=float("nan")))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_fee_main_path(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            performance_fee_pct=float("inf")))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_all_none(self):
        r = self.an.analyze(make_pos(gross_yield_pct=10.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        for k in ("net_return_after_fee_pct", "fee_charged_pct",
                  "oracle_manipulation_risk_premium_gap_pct", "realization_ratio",
                  "fee_on_oracle_manipulation_risk_premium_fraction",
                  "oracle_manipulation_risk_premium_consumed_yield_pct"):
            self.assertIsNone(r[k])

    def test_insufficient_recommendation(self):
        r = self.an.analyze(make_pos(performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"], "AVOID_FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfOracleManipulationRiskPremiumAnalyzer()

    def test_clean_net_base_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertIn("CLEAN_NET_BASE", r["flags"])

    def test_classification_always_in_flags(self):
        for net in (15.0, 12.0, 8.0, 4.0):
            r = self.an.analyze(make_pos(
                gross_yield_pct=15.0,
                net_of_oracle_manipulation_risk_premium_yield_pct=net,
                performance_fee_pct=20.0))
            self.assertIn(r["classification"], r["flags"])

    def test_high_oracle_manip_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=13.0,
            performance_fee_pct=20.0,
            oracle_manipulation_risk_premium_rate_pct=HIGH_ORACLE_MANIPULATION_RISK_PREMIUM_PCT))
        self.assertIn("HIGH_ORACLE_MANIPULATION_RISK_PREMIUM", r["flags"])

    def test_no_high_oracle_manip_flag_below_threshold(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=13.0,
            performance_fee_pct=20.0,
            oracle_manipulation_risk_premium_rate_pct=0.2))
        self.assertNotIn("HIGH_ORACLE_MANIPULATION_RISK_PREMIUM", r["flags"])

    def test_full_fee_on_oracle_manip_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=0.0,
            performance_fee_pct=20.0))
        self.assertIn("FULL_FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM", r["flags"])

    def test_fee_on_oracle_manip_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=14.0,
            performance_fee_pct=20.0))
        self.assertIn("FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM", r["flags"])


# ── aggregate ─────────────────────────────────────────────────────────────────

class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfOracleManipulationRiskPremiumAnalyzer()

    def test_portfolio_structure(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertIn("positions", out)
        self.assertIn("aggregate", out)
        self.assertEqual(len(out["positions"]), 5)
        agg = out["aggregate"]
        self.assertEqual(agg["position_count"], 5)
        self.assertIn("cleanest_vault", agg)
        self.assertIn("worst_oracle_manipulation_risk_premium_gap_vault", agg)

    def test_aggregate_cleanest_and_worst(self):
        positions = [
            make_pos(vault="Clean", gross_yield_pct=15.0,
                     net_of_oracle_manipulation_risk_premium_yield_pct=15.0,
                     performance_fee_pct=20.0),
            make_pos(vault="Bad", gross_yield_pct=10.0,
                     net_of_oracle_manipulation_risk_premium_yield_pct=-2.0,
                     performance_fee_pct=50.0),
        ]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["cleanest_vault"], "Clean")
        self.assertEqual(agg["worst_oracle_manipulation_risk_premium_gap_vault"], "Bad")

    def test_aggregate_all_insufficient(self):
        positions = [make_pos(vault="X"), make_pos(vault="Y")]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertIsNone(agg["cleanest_vault"])
        self.assertIsNone(agg["worst_oracle_manipulation_risk_premium_gap_vault"])
        self.assertEqual(agg["avg_score"], 0.0)
        self.assertEqual(agg["position_count"], 2)

    def test_aggregate_net_negative_count(self):
        positions = [
            make_pos(vault="A", gross_yield_pct=15.0,
                     net_of_oracle_manipulation_risk_premium_yield_pct=15.0,
                     performance_fee_pct=20.0),
            make_pos(vault="B", gross_yield_pct=10.0,
                     net_of_oracle_manipulation_risk_premium_yield_pct=-2.0,
                     performance_fee_pct=50.0),
        ]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["net_negative_count"], 1)

    def test_aggregate_avg_score_perfect(self):
        positions = [
            make_pos(vault="A", gross_yield_pct=15.0,
                     net_of_oracle_manipulation_risk_premium_yield_pct=15.0,
                     performance_fee_pct=20.0),
            make_pos(vault="B", gross_yield_pct=15.0,
                     net_of_oracle_manipulation_risk_premium_yield_pct=15.0,
                     performance_fee_pct=20.0),
        ]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertAlmostEqual(agg["avg_score"], 100.0, places=2)

    def test_aggregate_single_position(self):
        positions = [make_pos(vault="Solo", gross_yield_pct=15.0,
                              net_of_oracle_manipulation_risk_premium_yield_pct=15.0,
                              performance_fee_pct=20.0)]
        out = self.an.analyze_portfolio(positions)
        agg = out["aggregate"]
        self.assertEqual(agg["cleanest_vault"], "Solo")
        self.assertEqual(agg["worst_oracle_manipulation_risk_premium_gap_vault"], "Solo")
        self.assertEqual(agg["position_count"], 1)


# ── ring-buffer log ───────────────────────────────────────────────────────────

class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfOracleManipulationRiskPremiumAnalyzer()

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "sub", "log.json")
            cfg = {"log_path": log_path, "log_cap": 100}
            self.an.analyze_portfolio(_demo_positions(), cfg=cfg,
                                      write_log=True)
            self.assertTrue(os.path.exists(log_path))
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)
            self.assertIn("aggregate", data[0])
            self.assertIn("snapshots", data[0])

    def test_log_ring_cap(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            for _ in range(5):
                self.an.analyze_portfolio(
                    [make_pos(gross_yield_pct=16.0,
                              net_of_oracle_manipulation_risk_premium_yield_pct=10.0,
                              performance_fee_pct=20.0)],
                    cfg=cfg, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_log_corrupt_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            with open(log_path, "w") as fh:
                fh.write("not json{{{")
            cfg = {"log_path": log_path, "log_cap": 3}
            self.an.analyze_portfolio(
                [make_pos(gross_yield_pct=16.0,
                          net_of_oracle_manipulation_risk_premium_yield_pct=10.0,
                          performance_fee_pct=20.0)],
                cfg=cfg, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            self.an.analyze(make_pos(gross_yield_pct=16.0,
                                     net_of_oracle_manipulation_risk_premium_yield_pct=10.0,
                                     performance_fee_pct=20.0),
                            cfg=cfg, write_log=True)
            self.assertFalse(os.path.exists(log_path + ".tmp"))

    def test_no_write_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            self.an.analyze(make_pos(gross_yield_pct=16.0,
                                     net_of_oracle_manipulation_risk_premium_yield_pct=10.0,
                                     performance_fee_pct=20.0),
                            cfg=cfg, write_log=False)
            self.assertFalse(os.path.exists(log_path))

    def test_log_atomic_via_replace(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 10}
            self.an.analyze_portfolio(_demo_positions(), cfg=cfg,
                                      write_log=True)
            self.assertFalse(os.path.exists(log_path + ".tmp"))
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)


# ── invariants / finiteness ───────────────────────────────────────────────────

class TestInvariants(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfOracleManipulationRiskPremiumAnalyzer()

    def test_all_floats_finite(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertTrue(_all_floats_finite(out))

    def test_no_infinity_or_nan_in_demo(self):
        out = self.an.analyze_portfolio(_demo_positions())
        s = json.dumps(out)
        self.assertNotIn("Infinity", s)
        self.assertNotIn("NaN", s)

    def test_score_bounds_random_grid(self):
        for gross in (1.0, 5.0, 12.0, 30.0, 100.0):
            for net in (-5.0, 0.0, gross * 0.5, gross, gross + 5.0):
                for fee in (0.0, 10.0, 20.0, 50.0, 100.0):
                    r = self.an.analyze(make_pos(
                        gross_yield_pct=gross,
                        net_of_oracle_manipulation_risk_premium_yield_pct=net,
                        performance_fee_pct=fee))
                    self.assertGreaterEqual(r["score"], 0.0)
                    self.assertLessEqual(r["score"], 100.0)
                    self.assertGreaterEqual(
                        r["fee_on_oracle_manipulation_risk_premium_fraction"], 0.0)
                    self.assertLessEqual(
                        r["fee_on_oracle_manipulation_risk_premium_fraction"], 1.0)
                    self.assertGreaterEqual(r["realization_ratio"], 0.0)
                    self.assertLessEqual(r["realization_ratio"], 1.0)
                    self.assertTrue(_all_floats_finite(r))

    def test_fraction_monotone_with_oracle_manip(self):
        prev = -1.0
        for net in (20.0, 16.0, 12.0, 8.0, 4.0, 0.0):
            r = self.an.analyze(make_pos(
                gross_yield_pct=20.0,
                net_of_oracle_manipulation_risk_premium_yield_pct=net,
                performance_fee_pct=20.0))
            self.assertGreaterEqual(
                r["fee_on_oracle_manipulation_risk_premium_fraction"], prev)
            prev = r["fee_on_oracle_manipulation_risk_premium_fraction"]

    def test_token_fallback(self):
        r = self.an.analyze({"token": "TKN", "gross_yield_pct": 15.0,
                             "net_of_oracle_manipulation_risk_premium_yield_pct": 15.0,
                             "performance_fee_pct": 20.0})
        self.assertEqual(r["token"], "TKN")

    def test_unknown_token(self):
        r = self.an.analyze({"gross_yield_pct": 15.0,
                             "net_of_oracle_manipulation_risk_premium_yield_pct": 15.0,
                             "performance_fee_pct": 20.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_result_keys_stable(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=10.0,
            performance_fee_pct=20.0))
        ins = self.an._insufficient("X")
        self.assertEqual(set(r.keys()), set(ins.keys()))

    def test_override_keys_stable(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            oracle_manipulation_risk_premium_gap_pct=4.8,
            fee_charged_pct=12.0))
        ins = self.an._insufficient("X")
        self.assertEqual(set(r.keys()), set(ins.keys()))

    def test_sample_count_zero(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=10.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["sample_count"], 0)

    def test_used_main_true_on_main_path(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertTrue(r["used_main"])
        self.assertFalse(r["used_override"])


# ── grades / score boundaries ─────────────────────────────────────────────────

class TestGradesAndScore(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfOracleManipulationRiskPremiumAnalyzer()

    def test_clean_grade_a(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["grade"], "A")

    def test_severe_lower_grade(self):
        clean = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=15.0,
            performance_fee_pct=20.0))
        severe = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=-2.0,
            performance_fee_pct=50.0))
        self.assertLess(severe["score"], clean["score"])

    def test_score_zero_insufficient(self):
        r = self.an.analyze(make_pos(performance_fee_pct=20.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_grade_matches_score(self):
        for gross, net, fee in (
            (15.0, 15.0, 20.0),
            (16.0, 10.0, 20.0),
            (10.0, -2.0, 50.0),
            (20.0, 18.0, 20.0),
        ):
            r = self.an.analyze(make_pos(
                gross_yield_pct=gross,
                net_of_oracle_manipulation_risk_premium_yield_pct=net,
                performance_fee_pct=fee))
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_grade_boundary_b_c(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_oracle_manipulation_risk_premium_yield_pct=12.0,
            performance_fee_pct=20.0))
        self.assertIn(r["grade"], ("B", "C", "D"))
        self.assertLess(r["score"], 85.0)


# ── CLI / demo ────────────────────────────────────────────────────────────────

class TestDemo(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfOracleManipulationRiskPremiumAnalyzer()

    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 5)

    def test_demo_classifications(self):
        out = self.an.analyze_portfolio(_demo_positions())
        classes = {p["token"]: p["classification"] for p in out["positions"]}
        self.assertEqual(
            classes["USDC-Oracle-Vault-CleanManipRisk"],
            "CLEAN_NET_OF_ORACLE_MANIPULATION_RISK_PREMIUM_BASE")
        self.assertEqual(
            classes["ETH-Oracle-Vault-ModerateManipRisk"],
            "MODERATE_FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM_GAP")
        self.assertEqual(
            classes["TWAP-Oracle-Vault-SevereManipRisk"],
            "SEVERE_FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM_GAP")
        self.assertEqual(
            classes["Pyth-Oracle-Vault-OverrideManipGap"],
            "MODERATE_FEE_ON_ORACLE_MANIPULATION_RISK_PREMIUM_GAP")
        self.assertEqual(
            classes["MYSTERY-Vault-NoData"], "INSUFFICIENT_DATA")

    def test_demo_json_serialisable(self):
        out = self.an.analyze_portfolio(_demo_positions())
        s = json.dumps(out)
        self.assertIsInstance(s, str)

    def test_demo_runs_all_paths(self):
        out = self.an.analyze_portfolio(_demo_positions())
        used_override = any(p["used_override"] for p in out["positions"])
        used_main = any(p["used_main"] for p in out["positions"])
        self.assertTrue(used_override)
        self.assertTrue(used_main)

    def test_demo_no_nan_inf(self):
        out = self.an.analyze_portfolio(_demo_positions())
        s = json.dumps(out)
        self.assertNotIn("NaN", s)
        self.assertNotIn("Infinity", s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
