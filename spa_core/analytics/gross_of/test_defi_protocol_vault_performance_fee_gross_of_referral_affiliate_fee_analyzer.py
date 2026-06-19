"""
Tests for MP-1251:
GrossOfReferralAffiliateFeeAnalyzer
Run: python3 -m unittest spa_core.analytics.gross_of.test_defi_protocol_vault_performance_fee_gross_of_referral_affiliate_fee_analyzer -v
"""

import json
import math
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.gross_of.defi_protocol_vault_performance_fee_gross_of_referral_affiliate_fee_analyzer import (  # noqa: E501
    GrossOfReferralAffiliateFeeAnalyzer,
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
    HIGH_REF_AFF_FEE_PCT,
    EPS,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    gross_yield_pct=None,
    net_of_ref_aff_fee_yield_pct=None,
    performance_fee_pct=None,
    ref_aff_fee_rate_pct=None,
    ref_aff_gap_pct=None,
    fee_charged_pct=None,
):
    pos = {"vault": vault}
    if gross_yield_pct is not None:
        pos["gross_yield_pct"] = gross_yield_pct
    if net_of_ref_aff_fee_yield_pct is not None:
        pos["net_of_ref_aff_fee_yield_pct"] = net_of_ref_aff_fee_yield_pct
    if performance_fee_pct is not None:
        pos["performance_fee_pct"] = performance_fee_pct
    if ref_aff_fee_rate_pct is not None:
        pos["ref_aff_fee_rate_pct"] = ref_aff_fee_rate_pct
    if ref_aff_gap_pct is not None:
        pos["ref_aff_gap_pct"] = ref_aff_gap_pct
    if fee_charged_pct is not None:
        pos["fee_charged_pct"] = fee_charged_pct
    return pos


def _all_floats_finite(obj):
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
        self.an = GrossOfReferralAffiliateFeeAnalyzer()

    def test_clean_equal_net_gross(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=12.0, net_of_ref_aff_fee_yield_pct=12.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "CLEAN_NET_OF_REF_AFF_BASE")
        self.assertGreaterEqual(r["score"], 85)

    def test_clean_tiny_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=9.8,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "CLEAN_NET_OF_REF_AFF_BASE")

    def test_mild_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=8.5,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "MILD_FEE_ON_REF_AFF_GAP")

    def test_moderate_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=5.5,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "MODERATE_FEE_ON_REF_AFF_GAP")

    def test_severe_gap_high_fraction(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=2.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "SEVERE_FEE_ON_REF_AFF_GAP")

    def test_severe_net_negative(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=-2.0,
            performance_fee_pct=50.0))
        self.assertEqual(r["classification"], "SEVERE_FEE_ON_REF_AFF_GAP")
        self.assertTrue(r["net_is_negative"])

    def test_score_monotonic_with_net(self):
        scores = []
        for net in [12.0, 10.0, 6.0, 2.0, 0.0]:
            r = self.an.analyze(make_pos(
                gross_yield_pct=12.0, net_of_ref_aff_fee_yield_pct=net,
                performance_fee_pct=20.0))
            scores.append(r["score"])
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1])

    def test_grade_a(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=10.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["grade"], "A")

    def test_grade_f_severe(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=-5.0,
            performance_fee_pct=50.0))
        self.assertEqual(r["grade"], "F")


# ── recommendations ─────────────────────────────────────────────────────────

class TestRecommendations(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfReferralAffiliateFeeAnalyzer()

    def test_trust_clean(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=10.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"], "TRUST_FEE_STRUCTURE")

    def test_minor_mild(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=8.5,
            performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"], "MINOR_FEE_ON_REF_AFF")

    def test_demand_moderate(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=5.5,
            performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"], "DEMAND_NET_OF_REF_AFF_BASE")

    def test_avoid_severe(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=-2.0,
            performance_fee_pct=50.0))
        self.assertEqual(r["recommendation"], "AVOID_FEE_ON_REF_AFF")


# ── flags ──────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfReferralAffiliateFeeAnalyzer()

    def test_clean_net_base_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=10.0,
            performance_fee_pct=20.0))
        self.assertIn("CLEAN_NET_BASE", r["flags"])

    def test_net_negative_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=-3.0,
            performance_fee_pct=50.0))
        self.assertIn("NET_NEGATIVE_AFTER_FEE", r["flags"])

    def test_fee_on_ref_aff_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=7.0,
            performance_fee_pct=20.0))
        self.assertIn("FEE_ON_REF_AFF", r["flags"])

    def test_full_fee_on_ref_aff_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=0.0,
            performance_fee_pct=20.0))
        self.assertIn("FULL_FEE_ON_REF_AFF", r["flags"])

    def test_high_ref_aff_fee_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=9.0,
            performance_fee_pct=20.0, ref_aff_fee_rate_pct=0.60))
        self.assertIn("HIGH_REF_AFF_FEE", r["flags"])

    def test_no_high_ref_aff_fee_below_threshold(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=9.0,
            performance_fee_pct=20.0, ref_aff_fee_rate_pct=0.10))
        self.assertNotIn("HIGH_REF_AFF_FEE", r["flags"])

    def test_override_flag_present(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, ref_aff_gap_pct=3.0,
            fee_charged_pct=10.0))
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])

    def test_no_fee_on_ref_aff_in_override(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, ref_aff_gap_pct=3.0,
            fee_charged_pct=10.0))
        self.assertNotIn("FEE_ON_REF_AFF", r["flags"])
        self.assertNotIn("FULL_FEE_ON_REF_AFF", r["flags"])


# ── insufficient data ──────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfReferralAffiliateFeeAnalyzer()

    def test_no_gross(self):
        r = self.an.analyze(make_pos(performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_gross_zero(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=0.0, performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_gross_negative(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=-5.0, performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_gross_nan(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=float("nan"), performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_gross_inf(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=float("inf"), performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_fee_pct(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=8.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_fee_pct_nan(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, performance_fee_pct=float("nan")))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_fields_are_none(self):
        r = self.an.analyze(make_pos())
        for k in ["gross_yield_pct", "performance_fee_pct", "fee_charged_pct",
                   "fair_fee_pct", "ref_aff_gap_pct", "net_return_after_fee_pct",
                   "net_return_fair_pct", "overstatement_pct",
                   "realization_ratio", "fee_on_ref_aff_fraction"]:
            self.assertIsNone(r[k])

    def test_insufficient_recommendation(self):
        r = self.an.analyze(make_pos())
        self.assertEqual(r["recommendation"], "AVOID_FEE_ON_REF_AFF")


# ── override path ──────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfReferralAffiliateFeeAnalyzer()

    def test_override_basic(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, ref_aff_gap_pct=2.0,
            fee_charged_pct=10.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_main"])
        self.assertAlmostEqual(r["ref_aff_gap_pct"], 2.0, places=2)

    def test_override_negative_gap_takes_magnitude(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, ref_aff_gap_pct=-3.0,
            fee_charged_pct=10.0))
        self.assertAlmostEqual(r["ref_aff_gap_pct"], 3.0, places=2)

    def test_override_gap_capped_at_fee_charged(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, ref_aff_gap_pct=15.0,
            fee_charged_pct=10.0))
        self.assertAlmostEqual(r["ref_aff_gap_pct"], 10.0, places=2)

    def test_override_net_fields_none(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, ref_aff_gap_pct=2.0,
            fee_charged_pct=10.0))
        self.assertIsNone(r["net_of_ref_aff_fee_yield_pct"])
        self.assertIsNone(r["ref_aff_consumed_yield_pct"])

    def test_override_realization_ratio(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, ref_aff_gap_pct=5.0,
            fee_charged_pct=10.0))
        self.assertAlmostEqual(r["fee_on_ref_aff_fraction"], 0.5, places=2)
        self.assertAlmostEqual(r["realization_ratio"], 0.5, places=2)

    def test_override_zero_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, ref_aff_gap_pct=0.0,
            fee_charged_pct=10.0))
        self.assertAlmostEqual(r["ref_aff_gap_pct"], 0.0, places=4)
        self.assertEqual(r["classification"], "CLEAN_NET_OF_REF_AFF_BASE")

    def test_override_falls_to_main_if_fee_charged_zero(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, ref_aff_gap_pct=2.0,
            fee_charged_pct=0.0, performance_fee_pct=20.0,
            net_of_ref_aff_fee_yield_pct=8.0))
        self.assertTrue(r["used_main"])
        self.assertFalse(r["used_override"])

    def test_override_falls_to_main_if_fee_charged_negative(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, ref_aff_gap_pct=2.0,
            fee_charged_pct=-1.0, performance_fee_pct=20.0,
            net_of_ref_aff_fee_yield_pct=8.0))
        self.assertTrue(r["used_main"])


# ── numeric precision ──────────────────────────────────────────────────────

class TestNumericPrecision(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfReferralAffiliateFeeAnalyzer()

    def test_all_outputs_finite(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=5.0,
            performance_fee_pct=20.0))
        self.assertTrue(_all_floats_finite(r))

    def test_all_outputs_finite_override(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, ref_aff_gap_pct=3.0,
            fee_charged_pct=10.0))
        self.assertTrue(_all_floats_finite(r))

    def test_score_range(self):
        for net in [15.0, 10.0, 5.0, 0.0, -3.0]:
            r = self.an.analyze(make_pos(
                gross_yield_pct=15.0, net_of_ref_aff_fee_yield_pct=net,
                performance_fee_pct=20.0))
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_realization_ratio_range(self):
        for net in [12.0, 6.0, 0.0, -2.0]:
            r = self.an.analyze(make_pos(
                gross_yield_pct=12.0, net_of_ref_aff_fee_yield_pct=net,
                performance_fee_pct=20.0))
            self.assertGreaterEqual(r["realization_ratio"], 0.0)
            self.assertLessEqual(r["realization_ratio"], 1.0)

    def test_fee_on_ref_aff_fraction_range(self):
        for net in [10.0, 5.0, 0.0]:
            r = self.an.analyze(make_pos(
                gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=net,
                performance_fee_pct=20.0))
            self.assertGreaterEqual(r["fee_on_ref_aff_fraction"], 0.0)
            self.assertLessEqual(r["fee_on_ref_aff_fraction"], 1.0)

    def test_gap_never_negative(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertGreaterEqual(r["ref_aff_gap_pct"], 0.0)


# ── math verification ──────────────────────────────────────────────────────

class TestMathVerification(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfReferralAffiliateFeeAnalyzer()

    def test_fee_charged_equals_frac_times_gross(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=12.0, net_of_ref_aff_fee_yield_pct=8.0,
            performance_fee_pct=20.0))
        expected_fee = 0.20 * 12.0
        self.assertAlmostEqual(r["fee_charged_pct"], expected_fee, places=4)

    def test_fair_fee_equals_frac_times_net(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=12.0, net_of_ref_aff_fee_yield_pct=8.0,
            performance_fee_pct=20.0))
        expected_fair = 0.20 * 8.0
        self.assertAlmostEqual(r["fair_fee_pct"], expected_fair, places=4)

    def test_gap_equals_fee_charged_minus_fair(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=12.0, net_of_ref_aff_fee_yield_pct=8.0,
            performance_fee_pct=20.0))
        expected_gap = 0.20 * 12.0 - 0.20 * 8.0
        self.assertAlmostEqual(r["ref_aff_gap_pct"], expected_gap, places=4)

    def test_overstatement_equals_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=12.0, net_of_ref_aff_fee_yield_pct=8.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(
            r["overstatement_pct"], r["ref_aff_gap_pct"], places=4)

    def test_net_return_after_fee(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=7.0,
            performance_fee_pct=20.0))
        expected = 7.0 - 0.20 * 10.0
        self.assertAlmostEqual(
            r["net_return_after_fee_pct"], expected, places=4)

    def test_net_return_fair(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=7.0,
            performance_fee_pct=20.0))
        expected = 7.0 - 0.20 * 7.0
        self.assertAlmostEqual(
            r["net_return_fair_pct"], expected, places=4)

    def test_consumed_yield(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=7.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["ref_aff_consumed_yield_pct"], 3.0, places=4)


# ── edge cases ─────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfReferralAffiliateFeeAnalyzer()

    def test_zero_performance_fee(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=8.0,
            performance_fee_pct=0.0))
        self.assertAlmostEqual(r["fee_charged_pct"], 0.0, places=4)
        self.assertAlmostEqual(r["ref_aff_gap_pct"], 0.0, places=4)

    def test_100_pct_performance_fee(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=8.0,
            performance_fee_pct=100.0))
        self.assertAlmostEqual(r["fee_charged_pct"], 10.0, places=4)
        self.assertAlmostEqual(r["fair_fee_pct"], 8.0, places=4)

    def test_net_equals_zero(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=0.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["fair_fee_pct"], 0.0, places=4)
        self.assertIn("FULL_FEE_ON_REF_AFF", r["flags"])

    def test_net_exceeds_gross(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_ref_aff_fee_yield_pct=15.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["ref_aff_gap_pct"], 0.0, places=4)
        self.assertEqual(r["classification"], "CLEAN_NET_OF_REF_AFF_BASE")

    def test_tiny_gross(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=0.001, net_of_ref_aff_fee_yield_pct=0.0005,
            performance_fee_pct=20.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertTrue(_all_floats_finite(r))

    def test_token_fallback(self):
        r = self.an.analyze({
            "token": "MY-TOKEN",
            "gross_yield_pct": 10.0,
            "net_of_ref_aff_fee_yield_pct": 9.0,
            "performance_fee_pct": 20.0,
        })
        self.assertEqual(r["token"], "MY-TOKEN")

    def test_token_unknown_fallback(self):
        r = self.an.analyze({"gross_yield_pct": 10.0, "performance_fee_pct": 20.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_default_net_when_missing(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, performance_fee_pct=20.0))
        self.assertAlmostEqual(r["net_of_ref_aff_fee_yield_pct"], 0.0, places=4)

    def test_string_gross_yield(self):
        r = self.an.analyze({
            "vault": "V", "gross_yield_pct": "10.0",
            "net_of_ref_aff_fee_yield_pct": "8.0",
            "performance_fee_pct": "20.0"})
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_bool_gross_yield_rejected(self):
        r = self.an.analyze({
            "vault": "V", "gross_yield_pct": True,
            "performance_fee_pct": 20.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")


# ── portfolio ──────────────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfReferralAffiliateFeeAnalyzer()

    def test_portfolio_basic(self):
        positions = [
            make_pos(vault="A", gross_yield_pct=10.0,
                     net_of_ref_aff_fee_yield_pct=10.0,
                     performance_fee_pct=20.0),
            make_pos(vault="B", gross_yield_pct=10.0,
                     net_of_ref_aff_fee_yield_pct=5.0,
                     performance_fee_pct=20.0),
        ]
        result = self.an.analyze_portfolio(positions)
        self.assertEqual(len(result["positions"]), 2)
        self.assertIn("aggregate", result)

    def test_portfolio_cleanest_worst(self):
        positions = [
            make_pos(vault="Clean", gross_yield_pct=10.0,
                     net_of_ref_aff_fee_yield_pct=10.0,
                     performance_fee_pct=20.0),
            make_pos(vault="Worst", gross_yield_pct=10.0,
                     net_of_ref_aff_fee_yield_pct=2.0,
                     performance_fee_pct=20.0),
        ]
        result = self.an.analyze_portfolio(positions)
        agg = result["aggregate"]
        self.assertEqual(agg["cleanest_vault"], "Clean")
        self.assertEqual(agg["worst_ref_aff_gap_vault"], "Worst")

    def test_portfolio_avg_score(self):
        positions = [
            make_pos(vault="A", gross_yield_pct=10.0,
                     net_of_ref_aff_fee_yield_pct=10.0,
                     performance_fee_pct=20.0),
            make_pos(vault="B", gross_yield_pct=10.0,
                     net_of_ref_aff_fee_yield_pct=10.0,
                     performance_fee_pct=20.0),
        ]
        result = self.an.analyze_portfolio(positions)
        self.assertGreater(result["aggregate"]["avg_score"], 0.0)

    def test_portfolio_all_insufficient(self):
        positions = [make_pos(vault="X"), make_pos(vault="Y")]
        result = self.an.analyze_portfolio(positions)
        agg = result["aggregate"]
        self.assertIsNone(agg["cleanest_vault"])
        self.assertEqual(agg["avg_score"], 0.0)

    def test_portfolio_net_negative_count(self):
        positions = [
            make_pos(vault="A", gross_yield_pct=10.0,
                     net_of_ref_aff_fee_yield_pct=-2.0,
                     performance_fee_pct=50.0),
            make_pos(vault="B", gross_yield_pct=10.0,
                     net_of_ref_aff_fee_yield_pct=8.0,
                     performance_fee_pct=20.0),
        ]
        result = self.an.analyze_portfolio(positions)
        self.assertEqual(result["aggregate"]["net_negative_count"], 1)

    def test_portfolio_position_count(self):
        positions = [make_pos(vault=f"V{i}", gross_yield_pct=10.0,
                              net_of_ref_aff_fee_yield_pct=8.0,
                              performance_fee_pct=20.0) for i in range(5)]
        result = self.an.analyze_portfolio(positions)
        self.assertEqual(result["aggregate"]["position_count"], 5)

    def test_empty_portfolio(self):
        result = self.an.analyze_portfolio([])
        self.assertEqual(result["aggregate"]["position_count"], 0)


# ── logging ──────────────────────────────────────────────────────────────────

class TestLogging(unittest.TestCase):
    def setUp(self):
        self.an = GrossOfReferralAffiliateFeeAnalyzer()

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "test_log.json")
            cfg = {"log_path": log_path, "log_cap": 10}
            self.an.analyze(
                make_pos(gross_yield_pct=10.0,
                         net_of_ref_aff_fee_yield_pct=8.0,
                         performance_fee_pct=20.0),
                cfg=cfg, write_log=True)
            self.assertTrue(os.path.exists(log_path))
            with open(log_path) as f:
                log = json.load(f)
            self.assertEqual(len(log), 1)
            self.assertIn("ts", log[0])

    def test_write_log_ring_buffer(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "test_log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            for _ in range(5):
                self.an.analyze(
                    make_pos(gross_yield_pct=10.0,
                             net_of_ref_aff_fee_yield_pct=8.0,
                             performance_fee_pct=20.0),
                    cfg=cfg, write_log=True)
            with open(log_path) as f:
                log = json.load(f)
            self.assertLessEqual(len(log), 3)

    def test_no_write_without_flag(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "test_log.json")
            cfg = {"log_path": log_path, "log_cap": 10}
            self.an.analyze(
                make_pos(gross_yield_pct=10.0,
                         net_of_ref_aff_fee_yield_pct=8.0,
                         performance_fee_pct=20.0),
                cfg=cfg, write_log=False)
            self.assertFalse(os.path.exists(log_path))

    def test_portfolio_write_log(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "test_log.json")
            cfg = {"log_path": log_path, "log_cap": 10}
            self.an.analyze_portfolio(
                [make_pos(vault="A", gross_yield_pct=10.0,
                          net_of_ref_aff_fee_yield_pct=8.0,
                          performance_fee_pct=20.0)],
                cfg=cfg, write_log=True)
            with open(log_path) as f:
                log = json.load(f)
            self.assertEqual(len(log), 1)
            self.assertEqual(log[0]["position_count"], 1)

    def test_corrupted_log_file_handled(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = os.path.join(td, "test_log.json")
            with open(log_path, "w") as f:
                f.write("NOT JSON")
            cfg = {"log_path": log_path, "log_cap": 10}
            self.an.analyze(
                make_pos(gross_yield_pct=10.0,
                         net_of_ref_aff_fee_yield_pct=8.0,
                         performance_fee_pct=20.0),
                cfg=cfg, write_log=True)
            with open(log_path) as f:
                log = json.load(f)
            self.assertEqual(len(log), 1)


# ── constants ──────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_clean_fraction(self):
        self.assertAlmostEqual(CLEAN_FRACTION, 0.05)

    def test_mild_fraction(self):
        self.assertAlmostEqual(MILD_FRACTION, 0.20)

    def test_moderate_fraction(self):
        self.assertAlmostEqual(MODERATE_FRACTION, 0.50)

    def test_high_ref_aff_fee_pct(self):
        self.assertAlmostEqual(HIGH_REF_AFF_FEE_PCT, 0.50)

    def test_eps_positive(self):
        self.assertGreater(EPS, 0.0)

    def test_log_cap(self):
        self.assertEqual(LOG_CAP, 100)

    def test_log_path_ends_correctly(self):
        self.assertTrue(LOG_PATH.endswith(
            "vault_performance_fee_gross_of_referral_affiliate_fee_log.json"))


# ── CLI / demo positions ──────────────────────────────────────────────────

class TestDemo(unittest.TestCase):
    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 5)

    def test_demo_all_have_vault(self):
        for p in _demo_positions():
            self.assertIn("vault", p)

    def test_demo_portfolio_runs(self):
        an = GrossOfReferralAffiliateFeeAnalyzer()
        result = an.analyze_portfolio(_demo_positions())
        self.assertEqual(len(result["positions"]), 5)
        self.assertIn("aggregate", result)

    def test_demo_no_crash(self):
        an = GrossOfReferralAffiliateFeeAnalyzer()
        for p in _demo_positions():
            r = an.analyze(p)
            self.assertIn("classification", r)

    def test_build_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertIn("log_path", cfg)
        self.assertIn("log_cap", cfg)

    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 50})
        self.assertEqual(cfg["log_cap"], 50)


if __name__ == "__main__":
    unittest.main()
