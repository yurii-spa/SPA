"""
Tests for MP-1259:
DeFiProtocolVaultPerformanceFeeGrossOfImpermanentLossPremiumAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_performance_fee_gross_of_impermanent_loss_premium_analyzer -v
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

from spa_core.analytics.gross_of.defi_protocol_vault_performance_fee_gross_of_impermanent_loss_premium_analyzer import (  # noqa: E501
    GrossOfImpermanentLossPremiumAnalyzer,
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
    HIGH_IL_PREMIUM_PCT,
    EPS,
    LOG_PATH,
    LOG_CAP,
)


# -- fixtures ----------------------------------------------------------------

def make_pos(
    vault="ETH-Vault",
    gross_yield_pct=None,
    net_of_il_yield_pct=None,
    performance_fee_pct=None,
    impermanent_loss_premium_rate_pct=None,
    impermanent_loss_premium_gap_pct=None,
    fee_charged_pct=None,
):
    pos = {"vault": vault}
    if gross_yield_pct is not None:
        pos["gross_yield_pct"] = gross_yield_pct
    if net_of_il_yield_pct is not None:
        pos["net_of_il_yield_pct"] = net_of_il_yield_pct
    if performance_fee_pct is not None:
        pos["performance_fee_pct"] = performance_fee_pct
    if impermanent_loss_premium_rate_pct is not None:
        pos["impermanent_loss_premium_rate_pct"] = impermanent_loss_premium_rate_pct
    if impermanent_loss_premium_gap_pct is not None:
        pos["impermanent_loss_premium_gap_pct"] = impermanent_loss_premium_gap_pct
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


# -- TestHelpers (12 tests) --------------------------------------------------

class TestHelpers(unittest.TestCase):
    # 1
    def test_f_default(self):
        self.assertEqual(_f(None), 0.0)
        self.assertEqual(_f(None, 3.0), 3.0)
        self.assertEqual(_f("x", 1.0), 1.0)
        self.assertEqual(_f("2.5"), 2.5)
        self.assertEqual(_f(4), 4.0)

    # 2
    def test_clamp(self):
        self.assertEqual(_clamp(5, 0, 1), 1)
        self.assertEqual(_clamp(-5, 0, 1), 0)
        self.assertEqual(_clamp(0.5, 0, 1), 0.5)

    # 3
    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    # 4
    def test_mean_values(self):
        self.assertEqual(_mean([2, 4]), 3.0)
        self.assertAlmostEqual(_mean([1.0, 2.0, 3.0]), 2.0, places=6)

    # 5
    def test_safe_div_positive(self):
        self.assertEqual(_safe_div(10, 2, None), 5.0)

    # 6
    def test_safe_div_zero_den(self):
        self.assertIsNone(_safe_div(10, 0, None))

    # 7
    def test_safe_div_negative_den(self):
        self.assertIsNone(_safe_div(10, -1, None))

    # 8
    def test_coerce_num_basic(self):
        self.assertAlmostEqual(_coerce_num(3.14), 3.14)
        self.assertAlmostEqual(_coerce_num("2.5"), 2.5)
        self.assertAlmostEqual(_coerce_num(5), 5.0)

    # 9
    def test_coerce_num_rejects_bool(self):
        self.assertIsNone(_coerce_num(True))
        self.assertIsNone(_coerce_num(False))

    # 10
    def test_coerce_num_rejects_nan_inf(self):
        self.assertIsNone(_coerce_num(float("nan")))
        self.assertIsNone(_coerce_num(float("inf")))
        self.assertIsNone(_coerce_num(float("-inf")))

    # 11
    def test_coerce_signed_accepts_negative(self):
        self.assertAlmostEqual(_coerce_signed(-3.5), -3.5)

    # 12
    def test_coerce_count_basic(self):
        self.assertEqual(_coerce_count(5), 5)
        self.assertEqual(_coerce_count(0), 0)
        self.assertIsNone(_coerce_count(-1))


# -- TestGradeFromScore (1 test) ---------------------------------------------

class TestGradeFromScore(unittest.TestCase):
    # 13
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


# -- TestMainPathClassification (10 tests) -----------------------------------

class TestMainPathClassification(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfImpermanentLossPremiumAnalyzer()

    # 14
    def test_clean_equal_net_gross(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_il_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"],
                         "CLEAN_NET_OF_IL_BASE")
        self.assertIn("CLEAN_NET_BASE", r["flags"])

    # 15
    def test_clean_tiny_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=9.95,
            performance_fee_pct=10.0))
        self.assertEqual(r["classification"],
                         "CLEAN_NET_OF_IL_BASE")
        self.assertLessEqual(
            r["fee_on_il_fraction"], CLEAN_FRACTION)

    # 16
    def test_mild_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=9.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"],
                         "MILD_FEE_ON_IL_GAP")
        self.assertGreater(
            r["fee_on_il_fraction"], CLEAN_FRACTION)
        self.assertLessEqual(
            r["fee_on_il_fraction"], MILD_FRACTION)

    # 17
    def test_moderate_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=5.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"],
                         "MODERATE_FEE_ON_IL_GAP")
        self.assertAlmostEqual(
            r["fee_on_il_fraction"], 0.5, places=4)

    # 18
    def test_severe_gap_high_fraction(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=1.0,
            performance_fee_pct=20.0))
        self.assertGreater(
            r["fee_on_il_fraction"], MODERATE_FRACTION)
        self.assertEqual(r["classification"],
                         "SEVERE_FEE_ON_IL_GAP")

    # 19
    def test_severe_net_negative(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=-2.0,
            performance_fee_pct=50.0))
        self.assertEqual(r["classification"],
                         "SEVERE_FEE_ON_IL_GAP")
        self.assertTrue(r["net_is_negative"])

    # 20
    def test_zero_net_yield(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=0.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(
            r["fee_on_il_fraction"], 1.0, places=4)

    # 21
    def test_full_fee_on_il_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=0.0,
            performance_fee_pct=20.0))
        self.assertIn("FULL_FEE_ON_IL", r["flags"])

    # 22
    def test_high_il_rate_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_il_yield_pct=14.5,
            performance_fee_pct=20.0,
            impermanent_loss_premium_rate_pct=0.30))
        self.assertIn("HIGH_IL_PREMIUM", r["flags"])

    # 23
    def test_low_il_rate_no_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_il_yield_pct=14.5,
            performance_fee_pct=20.0,
            impermanent_loss_premium_rate_pct=0.10))
        self.assertNotIn("HIGH_IL_PREMIUM", r["flags"])


# -- TestOverridePath (8 tests) ----------------------------------------------

class TestOverridePath(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfImpermanentLossPremiumAnalyzer()

    # 24
    def test_override_basic(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            impermanent_loss_premium_gap_pct=4.8,
            fee_charged_pct=12.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_main"])
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])
        self.assertAlmostEqual(
            r["fee_on_il_fraction"], 0.4, places=4)

    # 25
    def test_override_gap_clamped_to_fee(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            impermanent_loss_premium_gap_pct=15.0,
            fee_charged_pct=10.0))
        self.assertEqual(r["impermanent_loss_premium_gap_pct"], 10.0)
        self.assertEqual(r["fee_on_il_fraction"], 1.0)
        self.assertEqual(r["fair_fee_pct"], 0.0)

    # 26
    def test_override_negative_gap_abs(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            impermanent_loss_premium_gap_pct=-3.0,
            fee_charged_pct=10.0))
        self.assertAlmostEqual(
            r["impermanent_loss_premium_gap_pct"], 3.0, places=4)

    # 27
    def test_override_zero_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            impermanent_loss_premium_gap_pct=0.0,
            fee_charged_pct=10.0))
        self.assertEqual(r["classification"],
                         "CLEAN_NET_OF_IL_BASE")

    # 28
    def test_override_with_rate(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            impermanent_loss_premium_gap_pct=2.0,
            fee_charged_pct=10.0,
            impermanent_loss_premium_rate_pct=0.30))
        self.assertIn("HIGH_IL_PREMIUM", r["flags"])

    # 29
    def test_override_used_flag_true(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            impermanent_loss_premium_gap_pct=4.8,
            fee_charged_pct=12.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_main"])

    # 30
    def test_override_gap_from_override_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            impermanent_loss_premium_gap_pct=4.8,
            fee_charged_pct=12.0))
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])

    # 31
    def test_override_score_range(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            impermanent_loss_premium_gap_pct=4.8,
            fee_charged_pct=12.0))
        self.assertGreaterEqual(r["score"], 0.0)
        self.assertLessEqual(r["score"], 100.0)


# -- TestInsufficientData (8 tests) ------------------------------------------

class TestInsufficientData(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfImpermanentLossPremiumAnalyzer()

    # 32
    def test_no_gross_yield(self):
        r = self.an.analyze(make_pos(
            performance_fee_pct=20.0,
            net_of_il_yield_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    # 33
    def test_zero_gross_yield(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=0.0, performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    # 34
    def test_negative_gross_yield(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=-5.0, performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    # 35
    def test_no_fee_no_override(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=8.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    # 36
    def test_nan_gross(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=float("nan"), performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    # 37
    def test_inf_gross(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=float("inf"), performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    # 38
    def test_none_fee_pct(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    # 39
    def test_insufficient_score_zero(self):
        r = self.an.analyze(make_pos(performance_fee_pct=20.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")


# -- TestScoring (10 tests) --------------------------------------------------

class TestScoring(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfImpermanentLossPremiumAnalyzer()

    # 40
    def test_perfect_score_clean(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_il_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["score"], 100.0, places=2)

    # 41
    def test_zero_score_full_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=0.0,
            performance_fee_pct=20.0))
        self.assertLessEqual(r["score"], 35.0)

    # 42
    def test_score_moderate(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_il_yield_pct=10.0,
            performance_fee_pct=20.0))
        self.assertGreaterEqual(r["score"], 45.0)
        self.assertLessEqual(r["score"], 75.0)

    # 43
    def test_score_severe_negative(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=-3.0,
            performance_fee_pct=50.0))
        self.assertLess(r["score"], 40.0)

    # 44
    def test_score_always_0_100(self):
        for gross in (1.0, 5.0, 20.0, 100.0):
            for net in (-5.0, 0.0, gross * 0.5, gross):
                for fee in (0.0, 10.0, 50.0, 100.0):
                    r = self.an.analyze(make_pos(
                        gross_yield_pct=gross,
                        net_of_il_yield_pct=net,
                        performance_fee_pct=fee))
                    self.assertGreaterEqual(r["score"], 0.0)
                    self.assertLessEqual(r["score"], 100.0)

    # 45
    def test_score_monotone_with_gap(self):
        prev_score = 200.0
        for net in (20.0, 16.0, 12.0, 8.0, 4.0, 0.0):
            r = self.an.analyze(make_pos(
                gross_yield_pct=20.0,
                net_of_il_yield_pct=net,
                performance_fee_pct=20.0))
            self.assertLessEqual(r["score"], prev_score)
            prev_score = r["score"]

    # 46
    def test_score_formula_components(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0,
            net_of_il_yield_pct=8.0,
            performance_fee_pct=20.0))
        rr = r["realization_ratio"]
        frac = r["fee_on_il_fraction"]
        expected = 70.0 * rr + 30.0 * (1.0 - frac)
        self.assertAlmostEqual(r["score"], round(expected, 2), places=2)

    # 47
    def test_grade_A_threshold(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_il_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertGreaterEqual(r["score"], 85.0)
        self.assertEqual(r["grade"], "A")

    # 48
    def test_grade_B_threshold(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_il_yield_pct=17.0,
            performance_fee_pct=20.0))
        if 70.0 <= r["score"] < 85.0:
            self.assertEqual(r["grade"], "B")

    # 49
    def test_grade_F_threshold(self):
        r = self.an.analyze(make_pos(performance_fee_pct=20.0))
        self.assertLess(r["score"], 40.0)
        self.assertEqual(r["grade"], "F")


# -- TestRecommendation (5 tests) --------------------------------------------

class TestRecommendation(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfImpermanentLossPremiumAnalyzer()

    # 50
    def test_recommend_trust(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_il_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"], "TRUST_FEE_STRUCTURE")

    # 51
    def test_recommend_minor(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=9.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"],
                         "MINOR_FEE_ON_IL")

    # 52
    def test_recommend_demand(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=5.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"],
                         "DEMAND_NET_OF_IL_BASE")

    # 53
    def test_recommend_avoid(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=1.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"],
                         "AVOID_FEE_ON_IL")

    # 54
    def test_recommend_insufficient(self):
        r = self.an.analyze(make_pos(performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"],
                         "AVOID_FEE_ON_IL")


# -- TestFlags (8 tests) -----------------------------------------------------

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfImpermanentLossPremiumAnalyzer()

    # 55
    def test_classification_in_flags(self):
        for net in (15.0, 12.0, 8.0, 4.0):
            r = self.an.analyze(make_pos(
                gross_yield_pct=15.0,
                net_of_il_yield_pct=net,
                performance_fee_pct=20.0))
            self.assertIn(r["classification"], r["flags"])

    # 56
    def test_clean_net_base_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_il_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertIn("CLEAN_NET_BASE", r["flags"])

    # 57
    def test_net_negative_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=-2.0,
            performance_fee_pct=50.0))
        self.assertIn("NET_NEGATIVE_AFTER_FEE", r["flags"])

    # 58
    def test_high_rate_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_il_yield_pct=13.0,
            performance_fee_pct=20.0,
            impermanent_loss_premium_rate_pct=HIGH_IL_PREMIUM_PCT))
        self.assertIn("HIGH_IL_PREMIUM", r["flags"])

    # 59
    def test_fee_on_il_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            net_of_il_yield_pct=14.0,
            performance_fee_pct=20.0))
        self.assertIn("FEE_ON_IL", r["flags"])

    # 60
    def test_full_fee_on_il_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=0.0,
            performance_fee_pct=20.0))
        self.assertIn("FULL_FEE_ON_IL", r["flags"])

    # 61
    def test_override_gap_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0,
            impermanent_loss_premium_gap_pct=4.8,
            fee_charged_pct=12.0))
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])

    # 62
    def test_no_duplicate_flags(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_il_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertEqual(len(r["flags"]), len(set(r["flags"])))


# -- TestPortfolio (8 tests) -------------------------------------------------

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfImpermanentLossPremiumAnalyzer()

    # 63
    def test_portfolio_empty(self):
        out = self.an.analyze_portfolio([])
        agg = out["aggregate"]
        self.assertEqual(agg["position_count"], 0)
        self.assertIsNone(agg["cleanest_vault"])

    # 64
    def test_portfolio_single(self):
        positions = [make_pos(vault="Solo", gross_yield_pct=15.0,
                              net_of_il_yield_pct=15.0,
                              performance_fee_pct=20.0)]
        out = self.an.analyze_portfolio(positions)
        self.assertEqual(len(out["positions"]), 1)
        agg = out["aggregate"]
        self.assertEqual(agg["position_count"], 1)
        self.assertEqual(agg["cleanest_vault"], "Solo")

    # 65
    def test_portfolio_multiple(self):
        positions = [
            make_pos(vault="A", gross_yield_pct=15.0,
                     net_of_il_yield_pct=15.0,
                     performance_fee_pct=20.0),
            make_pos(vault="B", gross_yield_pct=20.0,
                     net_of_il_yield_pct=10.0,
                     performance_fee_pct=20.0),
            make_pos(vault="C", gross_yield_pct=10.0,
                     net_of_il_yield_pct=-2.0,
                     performance_fee_pct=50.0),
        ]
        out = self.an.analyze_portfolio(positions)
        self.assertEqual(len(out["positions"]), 3)
        agg = out["aggregate"]
        self.assertEqual(agg["position_count"], 3)
        self.assertIsNotNone(agg["avg_score"])

    # 66
    def test_portfolio_cleanest_worst(self):
        positions = [
            make_pos(vault="Clean", gross_yield_pct=15.0,
                     net_of_il_yield_pct=15.0,
                     performance_fee_pct=20.0),
            make_pos(vault="Bad", gross_yield_pct=10.0,
                     net_of_il_yield_pct=-2.0,
                     performance_fee_pct=50.0),
        ]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["cleanest_vault"], "Clean")
        self.assertEqual(
            agg["worst_il_gap_vault"], "Bad")

    # 67
    def test_portfolio_net_negative_count(self):
        positions = [
            make_pos(vault="A", gross_yield_pct=15.0,
                     net_of_il_yield_pct=15.0,
                     performance_fee_pct=20.0),
            make_pos(vault="B", gross_yield_pct=10.0,
                     net_of_il_yield_pct=-2.0,
                     performance_fee_pct=50.0),
        ]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["net_negative_count"], 1)

    # 68
    def test_portfolio_all_insufficient(self):
        positions = [make_pos(vault="X"), make_pos(vault="Y")]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertIsNone(agg["cleanest_vault"])
        self.assertIsNone(
            agg["worst_il_gap_vault"])
        self.assertEqual(agg["avg_score"], 0.0)

    # 69
    def test_portfolio_mixed(self):
        positions = [
            make_pos(vault="Clean", gross_yield_pct=15.0,
                     net_of_il_yield_pct=15.0,
                     performance_fee_pct=20.0),
            make_pos(vault="NoData"),
        ]
        out = self.an.analyze_portfolio(positions)
        agg = out["aggregate"]
        self.assertEqual(agg["position_count"], 2)
        self.assertEqual(agg["cleanest_vault"], "Clean")

    # 70
    def test_portfolio_position_count(self):
        positions = [
            make_pos(vault="A", gross_yield_pct=15.0,
                     net_of_il_yield_pct=15.0,
                     performance_fee_pct=20.0),
            make_pos(vault="B", gross_yield_pct=15.0,
                     net_of_il_yield_pct=15.0,
                     performance_fee_pct=20.0),
        ]
        out = self.an.analyze_portfolio(positions)
        self.assertEqual(len(out["positions"]),
                         out["aggregate"]["position_count"])


# -- TestAnalyzeSingle (5 tests) ---------------------------------------------

class TestAnalyzeSingle(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfImpermanentLossPremiumAnalyzer()

    # 71
    def test_analyze_returns_dict(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_il_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertIsInstance(r, dict)

    # 72
    def test_analyze_write_log_false(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 100}
            self.an.analyze(make_pos(
                gross_yield_pct=15.0,
                net_of_il_yield_pct=15.0,
                performance_fee_pct=20.0),
                cfg=cfg, write_log=False)
            self.assertFalse(os.path.exists(log_path))

    # 73
    def test_analyze_keys_present(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_il_yield_pct=15.0,
            performance_fee_pct=20.0))
        for key in ("token", "classification", "score", "grade",
                    "recommendation", "flags", "used_main", "used_override",
                    "fee_on_il_fraction",
                    "realization_ratio"):
            self.assertIn(key, r)

    # 74
    def test_analyze_token_from_vault(self):
        r = self.an.analyze(make_pos(
            vault="MY-VAULT",
            gross_yield_pct=15.0,
            net_of_il_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["token"], "MY-VAULT")

    # 75
    def test_analyze_token_fallback(self):
        r = self.an.analyze({"token": "TKN", "gross_yield_pct": 15.0,
                             "net_of_il_yield_pct": 15.0,
                             "performance_fee_pct": 20.0})
        self.assertEqual(r["token"], "TKN")


# -- TestWriteLog (7 tests) --------------------------------------------------

class TestWriteLog(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfImpermanentLossPremiumAnalyzer()

    # 76
    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "sub", "log.json")
            cfg = {"log_path": log_path, "log_cap": 100}
            self.an.analyze_portfolio(_demo_positions(), cfg=cfg,
                                      write_log=True)
            self.assertTrue(os.path.exists(log_path))

    # 77
    def test_write_log_json_valid(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 100}
            self.an.analyze_portfolio(_demo_positions(), cfg=cfg,
                                      write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    # 78
    def test_write_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            for _ in range(5):
                self.an.analyze_portfolio(
                    [make_pos(gross_yield_pct=16.0,
                              net_of_il_yield_pct=10.0,
                              performance_fee_pct=20.0)],
                    cfg=cfg, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    # 79
    def test_write_log_appends(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 100}
            self.an.analyze_portfolio(
                [make_pos(gross_yield_pct=16.0,
                          net_of_il_yield_pct=10.0,
                          performance_fee_pct=20.0)],
                cfg=cfg, write_log=True)
            self.an.analyze_portfolio(
                [make_pos(gross_yield_pct=16.0,
                          net_of_il_yield_pct=10.0,
                          performance_fee_pct=20.0)],
                cfg=cfg, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 2)

    # 80
    def test_write_log_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 10}
            self.an.analyze_portfolio(_demo_positions(), cfg=cfg,
                                      write_log=True)
            self.assertFalse(os.path.exists(log_path + ".tmp"))
            self.assertTrue(os.path.exists(log_path))

    # 81
    def test_write_log_custom_path(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "custom", "deep", "log.json")
            cfg = {"log_path": log_path, "log_cap": 100}
            self.an.analyze_portfolio(_demo_positions(), cfg=cfg,
                                      write_log=True)
            self.assertTrue(os.path.exists(log_path))

    # 82
    def test_write_log_entry_structure(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 100}
            self.an.analyze_portfolio(_demo_positions(), cfg=cfg,
                                      write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            entry = data[0]
            self.assertIn("ts", entry)
            self.assertIn("aggregate", entry)
            self.assertIn("snapshots", entry)
            self.assertIn("position_count", entry["aggregate"])


# -- TestEdgeCases (10 tests) ------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfImpermanentLossPremiumAnalyzer()

    # 83
    def test_string_gross_yield(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct="15.0",
            net_of_il_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"],
                         "CLEAN_NET_OF_IL_BASE")

    # 84
    def test_string_fee_pct(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0,
            net_of_il_yield_pct=8.0,
            performance_fee_pct="20"))
        self.assertEqual(r["classification"],
                         "MODERATE_FEE_ON_IL_GAP")

    # 85
    def test_very_large_yield(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=999.0,
            net_of_il_yield_pct=998.0,
            performance_fee_pct=20.0))
        self.assertTrue(_all_floats_finite(r))
        self.assertGreaterEqual(r["score"], 0.0)
        self.assertLessEqual(r["score"], 100.0)

    # 86
    def test_very_small_yield(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=0.001,
            net_of_il_yield_pct=0.001,
            performance_fee_pct=20.0))
        self.assertTrue(_all_floats_finite(r))

    # 87
    def test_fee_pct_100(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=8.0,
            performance_fee_pct=100.0))
        self.assertAlmostEqual(r["performance_fee_pct"], 100.0, places=2)

    # 88
    def test_fee_pct_0(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0,
            net_of_il_yield_pct=8.0,
            performance_fee_pct=0.0))
        self.assertAlmostEqual(r["fee_charged_pct"], 0.0, places=4)
        self.assertAlmostEqual(
            r["impermanent_loss_premium_gap_pct"], 0.0, places=4)

    # 89
    def test_extra_keys_ignored(self):
        pos = make_pos(
            gross_yield_pct=15.0,
            net_of_il_yield_pct=15.0,
            performance_fee_pct=20.0)
        pos["extra_key"] = "should_be_ignored"
        pos["another_extra"] = 42
        r = self.an.analyze(pos)
        self.assertEqual(r["classification"],
                         "CLEAN_NET_OF_IL_BASE")

    # 90
    def test_missing_vault_key(self):
        r = self.an.analyze({"gross_yield_pct": 15.0,
                             "net_of_il_yield_pct": 15.0,
                             "performance_fee_pct": 20.0})
        self.assertEqual(r["token"], "UNKNOWN")

    # 91
    def test_all_floats_finite(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertTrue(_all_floats_finite(out))

    # 92
    def test_boolean_fields_correct(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0,
            net_of_il_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertIsInstance(r["used_override"], bool)
        self.assertIsInstance(r["used_main"], bool)
        self.assertIsInstance(r["net_is_negative"], bool)


# -- TestBuildDefaultCfg (2 tests) -------------------------------------------

class TestBuildDefaultCfg(unittest.TestCase):
    # 93
    def test_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    # 94
    def test_override_cfg(self):
        cfg = _build_default_cfg({"log_cap": 5, "log_path": "/tmp/custom.json"})
        self.assertEqual(cfg["log_cap"], 5)
        self.assertEqual(cfg["log_path"], "/tmp/custom.json")


# -- TestConstants (2 tests) -------------------------------------------------

class TestConstants(unittest.TestCase):
    # 95
    def test_constants_values(self):
        self.assertAlmostEqual(CLEAN_FRACTION, 0.05, places=6)
        self.assertAlmostEqual(MILD_FRACTION, 0.20, places=6)
        self.assertAlmostEqual(MODERATE_FRACTION, 0.50, places=6)
        self.assertAlmostEqual(EPS, 1e-12, places=18)

    # 96
    def test_log_cap(self):
        self.assertEqual(LOG_CAP, 100)


# -- TestDemoPositions (1 test) ----------------------------------------------

class TestDemoPositions(unittest.TestCase):
    # 97
    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 5)


# -- TestCLIEntryPoint (1 test) ----------------------------------------------

class TestCLIEntryPoint(unittest.TestCase):
    # 98
    def test_cli_exit_zero(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m",
             "spa_core.analytics.gross_of."
             "defi_protocol_vault_performance_fee_gross_of_"
             "impermanent_loss_premium_analyzer",
             "--check"],
            capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
