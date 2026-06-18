"""
Tests for MP-1208: DeFiProtocolVaultPerformanceFeeUnrealizedGainClawbackGapAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_performance_fee_unrealized_gain_clawback_gap_analyzer -v
"""

import json
import math
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.defi_protocol_vault_performance_fee_unrealized_gain_clawback_gap_analyzer import (  # noqa: E501
    DeFiProtocolVaultPerformanceFeeUnrealizedGainClawbackGapAnalyzer,
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
    EPS,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    peak_unrealized_gain_pct=None,
    realized_gain_pct=None,
    performance_fee_pct=None,
    crystallizations=None,
    clawback_gap_pct=None,
    fee_paid_on_peak_pct=None,
):
    pos = {"vault": vault}
    if peak_unrealized_gain_pct is not None:
        pos["peak_unrealized_gain_pct"] = peak_unrealized_gain_pct
    if realized_gain_pct is not None:
        pos["realized_gain_pct"] = realized_gain_pct
    if performance_fee_pct is not None:
        pos["performance_fee_pct"] = performance_fee_pct
    if crystallizations is not None:
        pos["crystallizations"] = crystallizations
    if clawback_gap_pct is not None:
        pos["clawback_gap_pct"] = clawback_gap_pct
    if fee_paid_on_peak_pct is not None:
        pos["fee_paid_on_peak_pct"] = fee_paid_on_peak_pct
    return pos


def A():
    return DeFiProtocolVaultPerformanceFeeUnrealizedGainClawbackGapAnalyzer()


def finite_check(testcase, result):
    for v in result.values():
        if isinstance(v, float):
            testcase.assertTrue(math.isfinite(v), f"non-finite: {v}")


# ── helper-function tests ─────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    def test_f_valid_str(self):
        self.assertEqual(_f("3.5"), 3.5)

    def test_f_none_default(self):
        self.assertEqual(_f(None), 0.0)

    def test_f_none_custom_default(self):
        self.assertEqual(_f(None, 9.0), 9.0)

    def test_f_bad_str(self):
        self.assertEqual(_f("abc"), 0.0)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1.0, 0.0, 1.0), 0.0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(2.0, 0.0, 1.0), 1.0)

    def test_clamp_mid(self):
        self.assertEqual(_clamp(0.5, 0.0, 1.0), 0.5)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertAlmostEqual(_mean([1.0, 2.0, 3.0]), 2.0)

    def test_safe_div_ok(self):
        self.assertAlmostEqual(_safe_div(6.0, 3.0, None), 2.0)

    def test_safe_div_zero_den(self):
        self.assertIsNone(_safe_div(6.0, 0.0, None))

    def test_coerce_num_bool(self):
        self.assertIsNone(_coerce_num(True))

    def test_coerce_num_none(self):
        self.assertIsNone(_coerce_num(None))

    def test_coerce_num_nan(self):
        self.assertIsNone(_coerce_num(float("nan")))

    def test_coerce_num_inf(self):
        self.assertIsNone(_coerce_num(float("inf")))

    def test_coerce_num_str(self):
        self.assertEqual(_coerce_num("2.5"), 2.5)

    def test_coerce_num_neg_str(self):
        self.assertEqual(_coerce_num("-2.5"), -2.5)

    def test_coerce_num_empty_str(self):
        self.assertIsNone(_coerce_num("   "))

    def test_coerce_num_int(self):
        self.assertEqual(_coerce_num(4), 4.0)

    def test_coerce_signed_positive(self):
        self.assertEqual(_coerce_signed(1.5), 1.5)

    def test_coerce_signed_negative(self):
        self.assertEqual(_coerce_signed(-1.5), -1.5)

    def test_coerce_signed_none(self):
        self.assertIsNone(_coerce_signed(None))

    def test_coerce_signed_nan(self):
        self.assertIsNone(_coerce_signed(float("nan")))

    def test_coerce_signed_bool(self):
        self.assertIsNone(_coerce_signed(True))

    def test_coerce_signed_str(self):
        self.assertEqual(_coerce_signed("-3.0"), -3.0)

    def test_coerce_count_int(self):
        self.assertEqual(_coerce_count(3), 3)

    def test_coerce_count_float(self):
        self.assertEqual(_coerce_count(2.0), 2)

    def test_coerce_count_str(self):
        self.assertEqual(_coerce_count("4"), 4)

    def test_coerce_count_none(self):
        self.assertIsNone(_coerce_count(None))

    def test_coerce_count_negative(self):
        self.assertIsNone(_coerce_count(-1))

    def test_coerce_count_nan(self):
        self.assertIsNone(_coerce_count(float("nan")))

    def test_coerce_count_bool(self):
        self.assertIsNone(_coerce_count(True))

    def test_coerce_count_zero(self):
        self.assertEqual(_coerce_count(0), 0)

    def test_grade_a(self):
        self.assertEqual(_grade_from_score(90), "A")

    def test_grade_b(self):
        self.assertEqual(_grade_from_score(75), "B")

    def test_grade_c(self):
        self.assertEqual(_grade_from_score(60), "C")

    def test_grade_d(self):
        self.assertEqual(_grade_from_score(45), "D")

    def test_grade_f(self):
        self.assertEqual(_grade_from_score(10), "F")

    def test_grade_boundary_85(self):
        self.assertEqual(_grade_from_score(85), "A")

    def test_grade_boundary_70(self):
        self.assertEqual(_grade_from_score(70), "B")

    def test_grade_just_below_85(self):
        self.assertEqual(_grade_from_score(84.99), "B")

    def test_build_default_cfg_defaults(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg["log_cap"], 5)

    def test_build_default_cfg_none(self):
        cfg = _build_default_cfg(None)
        self.assertEqual(cfg["log_cap"], LOG_CAP)


# ── main-path math correctness ───────────────────────────────────────────────

class TestMainMath(unittest.TestCase):
    def test_fee_paid_on_peak_formula(self):
        # fee 20%, peak 20 → 0.2*20=4.0
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=20.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["fee_paid_on_peak_pct"], 4.0, places=4)

    def test_fair_fee_formula(self):
        # fee 20%, realized 8 → 0.2*8=1.6
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=16.0, realized_gain_pct=8.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["fair_fee_pct"], 1.6, places=4)

    def test_clawback_gap_formula(self):
        # fee paid 3.2, fair 1.6 → gap 1.6
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=16.0, realized_gain_pct=8.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["clawback_gap_pct"], 1.6, places=4)

    def test_gap_equals_feefrac_times_reverted(self):
        # realized >= 0: gap = fee_frac*(peak - realized)
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=12.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(
            r["clawback_gap_pct"], 0.2 * (20.0 - 12.0), places=4)

    def test_reverted_gain_formula(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=12.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["reverted_gain_pct"], 8.0, places=4)

    def test_reverted_gain_zero_when_realized_above_peak(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=10.0, realized_gain_pct=12.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["reverted_gain_pct"], 0.0, places=6)

    def test_gap_zero_when_realized_equals_peak(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=20.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["clawback_gap_pct"], 0.0, places=6)

    def test_gap_zero_when_realized_above_peak(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=25.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["clawback_gap_pct"], 0.0, places=6)

    def test_net_realized_formula(self):
        # realized 8, fee paid 3.2 → net 4.8
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=16.0, realized_gain_pct=8.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["net_realized_pct"], 4.8, places=4)

    def test_net_realized_fair_formula(self):
        # realized 8, fair 1.6 → 6.4
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=16.0, realized_gain_pct=8.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["net_realized_fair_pct"], 6.4, places=4)

    def test_net_negative_when_fee_exceeds_realized(self):
        # big fee on peak, thin realized → net negative
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=12.0, realized_gain_pct=1.0,
            performance_fee_pct=50.0))
        self.assertTrue(r["net_is_negative"])
        self.assertLess(r["net_realized_pct"], 0.0)

    def test_overstatement_equals_gap(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=16.0, realized_gain_pct=8.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(
            r["overstatement_pct"], r["clawback_gap_pct"], places=6)

    def test_fee_on_reverted_fraction_value(self):
        # fee paid 3.2, gap 1.6 → fraction 0.5
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=16.0, realized_gain_pct=8.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["fee_on_reverted_fraction"], 0.5, places=4)

    def test_realization_ratio_value(self):
        # net 4.8, net_fair 6.4 → 0.75
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=16.0, realized_gain_pct=8.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["realization_ratio"], 0.75, places=4)

    def test_fee_frac_clamped_above_100(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=10.0,
            performance_fee_pct=150.0))
        self.assertAlmostEqual(r["performance_fee_pct"], 100.0, places=4)

    def test_fee_frac_clamped_negative(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=10.0,
            performance_fee_pct=-30.0))
        self.assertAlmostEqual(r["performance_fee_pct"], 0.0, places=4)
        self.assertAlmostEqual(r["fee_paid_on_peak_pct"], 0.0, places=6)

    def test_realized_defaults_zero_when_missing(self):
        # no realized → 0.0 = full reversal
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, performance_fee_pct=20.0))
        self.assertAlmostEqual(r["realized_gain_pct"], 0.0, places=6)

    def test_realized_negative_allowed(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=-5.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["realized_gain_pct"], -5.0, places=4)

    def test_fair_fee_zero_when_realized_negative(self):
        # realized < 0 → fair fee = fee_frac*max(0, realized) = 0
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=-5.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["fair_fee_pct"], 0.0, places=6)

    def test_no_fee_fully_realized_ratio_one(self):
        # zero fee → ratio 1.0, fraction 0
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=10.0,
            performance_fee_pct=0.0))
        self.assertAlmostEqual(r["realization_ratio"], 1.0, places=4)
        self.assertAlmostEqual(r["fee_on_reverted_fraction"], 0.0, places=4)

    def test_crystallizations_passthrough(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=20.0,
            performance_fee_pct=20.0, crystallizations=3))
        self.assertEqual(r["crystallizations"], 3)


# ── classification thresholds ───────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_clean_zero_gap(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=20.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "CLEAN_PERSISTENT_GAIN")

    def test_clean_realized_above_peak(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=25.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "CLEAN_PERSISTENT_GAIN")

    def test_clean_boundary_exact(self):
        # fee_on_reverted exactly 0.05: gap/fee_paid = 0.05.
        # fee_paid=0.2*20=4.0; gap=0.2 → reverted=1.0 → realized=19.0
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=19.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["fee_on_reverted_fraction"], 0.05, places=4)
        self.assertEqual(r["classification"], "CLEAN_PERSISTENT_GAIN")

    def test_just_above_clean_is_mild(self):
        # realized 18.8 → reverted 1.2 → fraction 0.06
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=18.8,
            performance_fee_pct=20.0))
        self.assertGreater(r["fee_on_reverted_fraction"], CLEAN_FRACTION)
        self.assertEqual(r["classification"], "MILD_CLAWBACK_GAP")

    def test_mild_clawback_gap(self):
        # realized 17 → reverted 3 → fraction 0.15
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=17.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "MILD_CLAWBACK_GAP")

    def test_mild_boundary_exact(self):
        # fraction 0.20: reverted 4, realized 16, peak 20
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=16.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["fee_on_reverted_fraction"], 0.20, places=4)
        self.assertEqual(r["classification"], "MILD_CLAWBACK_GAP")

    def test_just_above_mild_is_moderate(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=15.0,
            performance_fee_pct=20.0))
        self.assertGreater(r["fee_on_reverted_fraction"], MILD_FRACTION)
        self.assertEqual(r["classification"], "MODERATE_CLAWBACK_GAP")

    def test_moderate_clawback_gap(self):
        # peak 16, realized 8, fraction 0.5
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=16.0, realized_gain_pct=8.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "MODERATE_CLAWBACK_GAP")

    def test_moderate_boundary_exact(self):
        # fraction 0.50: realized 10, peak 20
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=10.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["fee_on_reverted_fraction"], 0.50, places=4)
        self.assertEqual(r["classification"], "MODERATE_CLAWBACK_GAP")

    def test_just_above_moderate_is_severe(self):
        # realized 9, peak 20, fee 20% → reverted 11, fraction 0.55,
        # net = 9 - 4 = 5 > 0 (not net-negative)
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=9.0,
            performance_fee_pct=20.0))
        self.assertGreater(r["fee_on_reverted_fraction"], MODERATE_FRACTION)
        self.assertEqual(r["classification"], "SEVERE_CLAWBACK_GAP")
        self.assertFalse(r["net_is_negative"])

    def test_severe_via_net_negative(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=12.0, realized_gain_pct=1.0,
            performance_fee_pct=50.0))
        self.assertEqual(r["classification"], "SEVERE_CLAWBACK_GAP")
        self.assertTrue(r["net_is_negative"])

    def test_net_negative_overrides_low_fraction(self):
        # net negative forces SEVERE even if fraction is small-ish
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=10.0, realized_gain_pct=2.0,
            performance_fee_pct=100.0))
        # fee_paid=10, net=2-10=-8 → negative → SEVERE
        self.assertTrue(r["net_is_negative"])
        self.assertEqual(r["classification"], "SEVERE_CLAWBACK_GAP")

    def test_full_reversal_severe(self):
        # realized 0 → full reversal, fraction 1.0
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=0.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["fee_on_reverted_fraction"], 1.0, places=4)
        self.assertEqual(r["classification"], "SEVERE_CLAWBACK_GAP")

    def test_classification_monotone_with_reversal(self):
        fractions = []
        for realized in (19.0, 16.0, 10.0, 2.0):
            r = A()._analyze_one(make_pos(
                peak_unrealized_gain_pct=20.0, realized_gain_pct=realized,
                performance_fee_pct=20.0))
            fractions.append(r["fee_on_reverted_fraction"])
        for i in range(len(fractions) - 1):
            self.assertLessEqual(fractions[i], fractions[i + 1])


# ── _classify direct ─────────────────────────────────────────────────────────────

class TestClassifyDirect(unittest.TestCase):
    def test_classify_net_negative(self):
        self.assertEqual(A()._classify(0.01, True), "SEVERE_CLAWBACK_GAP")

    def test_classify_clean(self):
        self.assertEqual(A()._classify(0.05, False), "CLEAN_PERSISTENT_GAIN")

    def test_classify_clean_below(self):
        self.assertEqual(A()._classify(0.0, False), "CLEAN_PERSISTENT_GAIN")

    def test_classify_mild(self):
        self.assertEqual(A()._classify(0.20, False), "MILD_CLAWBACK_GAP")

    def test_classify_mild_mid(self):
        self.assertEqual(A()._classify(0.10, False), "MILD_CLAWBACK_GAP")

    def test_classify_moderate(self):
        self.assertEqual(A()._classify(0.50, False), "MODERATE_CLAWBACK_GAP")

    def test_classify_moderate_mid(self):
        self.assertEqual(A()._classify(0.35, False), "MODERATE_CLAWBACK_GAP")

    def test_classify_severe(self):
        self.assertEqual(A()._classify(0.51, False), "SEVERE_CLAWBACK_GAP")

    def test_classify_severe_high(self):
        self.assertEqual(A()._classify(1.0, False), "SEVERE_CLAWBACK_GAP")


# ── ratios bounds ────────────────────────────────────────────────────────────────

class TestRatios(unittest.TestCase):
    def test_realization_bounds(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            if r["realization_ratio"] is not None:
                self.assertGreaterEqual(r["realization_ratio"], 0.0)
                self.assertLessEqual(r["realization_ratio"], 1.0)

    def test_fee_on_reverted_bounds(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            if r["fee_on_reverted_fraction"] is not None:
                self.assertGreaterEqual(r["fee_on_reverted_fraction"], 0.0)
                self.assertLessEqual(r["fee_on_reverted_fraction"], 1.0)

    def test_fee_on_reverted_capped_at_one(self):
        # full reversal → fraction capped at 1.0
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=-50.0,
            performance_fee_pct=20.0))
        self.assertLessEqual(r["fee_on_reverted_fraction"], 1.0)

    def test_realization_zero_when_net_negative(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=12.0, realized_gain_pct=1.0,
            performance_fee_pct=50.0))
        self.assertAlmostEqual(r["realization_ratio"], 0.0, places=6)

    def test_realization_ratio_clean_one(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=20.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["realization_ratio"], 1.0, places=4)


# ── override path ────────────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def test_override_used(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=5.0,
            fee_paid_on_peak_pct=12.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_main"])
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])
        finite_check(self, r)

    def test_override_gap_verbatim(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=5.0,
            fee_paid_on_peak_pct=12.0))
        self.assertAlmostEqual(r["clawback_gap_pct"], 5.0, places=4)

    def test_override_fee_on_reverted(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=5.0,
            fee_paid_on_peak_pct=12.0))
        self.assertAlmostEqual(
            r["fee_on_reverted_fraction"], 5.0 / 12.0, places=4)

    def test_override_geometry_none(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=5.0,
            fee_paid_on_peak_pct=12.0))
        self.assertIsNone(r["realized_gain_pct"])
        self.assertIsNone(r["reverted_gain_pct"])
        self.assertIsNone(r["net_realized_pct"])
        self.assertIsNone(r["net_realized_fair_pct"])
        self.assertIsNone(r["performance_fee_pct"])

    def test_override_realization_anchor(self):
        # ratio = 1 - fraction = 1 - 5/12
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=5.0,
            fee_paid_on_peak_pct=12.0))
        self.assertAlmostEqual(
            r["realization_ratio"], 1.0 - 5.0 / 12.0, places=4)

    def test_override_negative_gap_to_magnitude(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=-5.0,
            fee_paid_on_peak_pct=12.0))
        self.assertTrue(r["used_override"])
        self.assertAlmostEqual(r["clawback_gap_pct"], 5.0, places=4)

    def test_override_gap_capped_at_fee_paid(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=20.0,
            fee_paid_on_peak_pct=12.0))
        self.assertAlmostEqual(r["clawback_gap_pct"], 12.0, places=4)
        self.assertAlmostEqual(r["fee_on_reverted_fraction"], 1.0, places=4)

    def test_override_suppresses_geometry_flags(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=5.0,
            fee_paid_on_peak_pct=12.0))
        self.assertNotIn("FEE_ON_VANISHED_GAINS", r["flags"])
        self.assertNotIn("FULL_REVERSAL", r["flags"])
        self.assertNotIn("NET_NEGATIVE_AFTER_FEE", r["flags"])

    def test_override_clean_when_zero_gap(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=0.0,
            fee_paid_on_peak_pct=12.0))
        self.assertEqual(r["classification"], "CLEAN_PERSISTENT_GAIN")
        self.assertIn("CLEAN_NO_REVERSAL", r["flags"])

    def test_override_moderate_classification(self):
        # 5/12 ≈ 0.4167 → MODERATE
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=5.0,
            fee_paid_on_peak_pct=12.0))
        self.assertEqual(r["classification"], "MODERATE_CLAWBACK_GAP")

    def test_override_str_inputs(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct="24.0", clawback_gap_pct="5.0",
            fee_paid_on_peak_pct="12.0"))
        self.assertTrue(r["used_override"])
        self.assertAlmostEqual(
            r["fee_on_reverted_fraction"], 5.0 / 12.0, places=4)

    def test_override_with_crystallizations(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=5.0,
            fee_paid_on_peak_pct=12.0, crystallizations=2))
        self.assertEqual(r["crystallizations"], 2)
        self.assertIn("MULTIPLE_CRYSTALLIZATIONS", r["flags"])

    def test_override_requires_positive_fee_paid(self):
        # fee_paid 0 → not override path; falls back to main (needs fee_pct)
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=5.0,
            fee_paid_on_peak_pct=0.0, performance_fee_pct=20.0,
            realized_gain_pct=10.0))
        self.assertFalse(r["used_override"])
        self.assertTrue(r["used_main"])

    def test_override_nan_gap_falls_to_main(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, clawback_gap_pct=float("nan"),
            fee_paid_on_peak_pct=12.0, performance_fee_pct=20.0,
            realized_gain_pct=10.0))
        self.assertFalse(r["used_override"])
        self.assertTrue(r["used_main"])

    def test_override_missing_fee_paid_falls_to_main(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, clawback_gap_pct=3.0,
            performance_fee_pct=20.0, realized_gain_pct=10.0))
        self.assertFalse(r["used_override"])
        self.assertTrue(r["used_main"])

    def test_override_requires_positive_peak(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=0.0, clawback_gap_pct=5.0,
            fee_paid_on_peak_pct=12.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_net_is_negative_false(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=5.0,
            fee_paid_on_peak_pct=12.0))
        self.assertFalse(r["net_is_negative"])

    def test_override_full_gap_severe(self):
        # gap == fee_paid → fraction 1.0 → SEVERE
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=12.0,
            fee_paid_on_peak_pct=12.0))
        self.assertEqual(r["classification"], "SEVERE_CLAWBACK_GAP")


# ── insufficient data ────────────────────────────────────────────────────────────

class TestInsufficient(unittest.TestCase):
    def test_no_peak(self):
        r = A()._analyze_one(make_pos(
            performance_fee_pct=20.0, realized_gain_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_peak(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=0.0, performance_fee_pct=20.0,
            realized_gain_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_peak(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=-3.0, performance_fee_pct=20.0,
            realized_gain_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_peak(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=float("nan"), performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_peak(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=float("inf"), performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_bad_str_peak(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct="abc", performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_bool_peak(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=True, performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_fee_pct(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=10.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_fee_pct(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, performance_fee_pct=float("nan"),
            realized_gain_pct=10.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_fee_pct(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, performance_fee_pct=float("inf"),
            realized_gain_pct=10.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_data_at_all(self):
        r = A()._analyze_one({"vault": "x"})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_shape(self):
        r = A()._analyze_one(make_pos(performance_fee_pct=20.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertIsNone(r["realization_ratio"])
        self.assertIsNone(r["fee_on_reverted_fraction"])
        self.assertIsNone(r["peak_unrealized_gain_pct"])
        self.assertIsNone(r["fee_paid_on_peak_pct"])

    def test_insufficient_recommendation(self):
        r = A()._analyze_one(make_pos(performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"], "AVOID_NO_CLAWBACK")

    def test_insufficient_net_negative_false(self):
        r = A()._analyze_one(make_pos(performance_fee_pct=20.0))
        self.assertFalse(r["net_is_negative"])

    def test_insufficient_used_flags_false(self):
        r = A()._analyze_one(make_pos(performance_fee_pct=20.0))
        self.assertFalse(r["used_override"])
        self.assertFalse(r["used_main"])

    def test_insufficient_crystallizations_none(self):
        r = A()._analyze_one(make_pos(performance_fee_pct=20.0))
        self.assertIsNone(r["crystallizations"])


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_classification_in_flags_first(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=16.0, realized_gain_pct=8.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["flags"][0], r["classification"])

    def test_clean_no_reversal_flag(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=20.0,
            performance_fee_pct=20.0))
        self.assertIn("CLEAN_NO_REVERSAL", r["flags"])

    def test_no_clean_flag_when_gap(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=16.0, realized_gain_pct=8.0,
            performance_fee_pct=20.0))
        self.assertNotIn("CLEAN_NO_REVERSAL", r["flags"])

    def test_net_negative_flag(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=12.0, realized_gain_pct=1.0,
            performance_fee_pct=50.0))
        self.assertIn("NET_NEGATIVE_AFTER_FEE", r["flags"])

    def test_no_net_negative_flag_clean(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=20.0,
            performance_fee_pct=20.0))
        self.assertNotIn("NET_NEGATIVE_AFTER_FEE", r["flags"])

    def test_fee_on_vanished_gains_flag(self):
        # reverted > 0 → FEE_ON_VANISHED_GAINS
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=12.0,
            performance_fee_pct=20.0))
        self.assertIn("FEE_ON_VANISHED_GAINS", r["flags"])

    def test_no_fee_on_vanished_when_no_reversal(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=20.0,
            performance_fee_pct=20.0))
        self.assertNotIn("FEE_ON_VANISHED_GAINS", r["flags"])

    def test_full_reversal_flag(self):
        # realized 0, peak > 0 → FULL_REVERSAL
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=0.0,
            performance_fee_pct=20.0))
        self.assertIn("FULL_REVERSAL", r["flags"])

    def test_full_reversal_flag_negative_realized(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=-3.0,
            performance_fee_pct=20.0))
        self.assertIn("FULL_REVERSAL", r["flags"])

    def test_no_full_reversal_when_realized_positive(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=12.0,
            performance_fee_pct=20.0))
        self.assertNotIn("FULL_REVERSAL", r["flags"])

    def test_multiple_crystallizations_flag(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=10.0,
            performance_fee_pct=20.0, crystallizations=2))
        self.assertIn("MULTIPLE_CRYSTALLIZATIONS", r["flags"])

    def test_no_multiple_crystallizations_when_one(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=10.0,
            performance_fee_pct=20.0, crystallizations=1))
        self.assertNotIn("MULTIPLE_CRYSTALLIZATIONS", r["flags"])

    def test_no_multiple_crystallizations_when_absent(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=10.0,
            performance_fee_pct=20.0))
        self.assertNotIn("MULTIPLE_CRYSTALLIZATIONS", r["flags"])

    def test_gap_from_override_flag(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=5.0,
            fee_paid_on_peak_pct=12.0))
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])

    def test_main_path_no_override_flag(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=20.0,
            performance_fee_pct=20.0))
        self.assertNotIn("GAP_FROM_OVERRIDE", r["flags"])

    def test_severe_multiple_flags_together(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=12.0, realized_gain_pct=0.0,
            performance_fee_pct=50.0, crystallizations=3))
        self.assertIn("SEVERE_CLAWBACK_GAP", r["flags"])
        self.assertIn("NET_NEGATIVE_AFTER_FEE", r["flags"])
        self.assertIn("FEE_ON_VANISHED_GAINS", r["flags"])
        self.assertIn("FULL_REVERSAL", r["flags"])
        self.assertIn("MULTIPLE_CRYSTALLIZATIONS", r["flags"])


# ── scoring ─────────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_clean_high_score(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=20.0,
            performance_fee_pct=20.0))
        self.assertGreaterEqual(r["score"], 80)

    def test_clean_score_full_when_no_fee(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=10.0,
            performance_fee_pct=0.0))
        self.assertAlmostEqual(r["score"], 100.0, places=2)

    def test_severe_low_score(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=12.0, realized_gain_pct=1.0,
            performance_fee_pct=50.0))
        self.assertLess(r["score"], 40)

    def test_score_in_range_all_demo(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_score_monotonic_in_reversal(self):
        # more reversal → lower score
        low = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=18.0,
            performance_fee_pct=20.0))
        high = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=10.0,
            performance_fee_pct=20.0))
        self.assertGreater(low["score"], high["score"])

    def test_score_monotonic_override(self):
        a = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=2.0,
            fee_paid_on_peak_pct=12.0))
        b = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=10.0,
            fee_paid_on_peak_pct=12.0))
        self.assertGreater(a["score"], b["score"])

    def test_score_formula(self):
        # peak 16, realized 8, fee 20%:
        # fee_paid 3.2, gap 1.6, net 4.8, net_fair 6.4 → ratio 0.75, frac 0.5
        # score = 70*0.75 + 30*0.5 = 52.5 + 15 = 67.5
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=16.0, realized_gain_pct=8.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["score"], 67.5, places=2)

    def test_insufficient_score_zero(self):
        r = A()._analyze_one(make_pos(performance_fee_pct=20.0))
        self.assertEqual(r["score"], 0.0)

    def test_score_grade_consistency(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── recommendation mapping ───────────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_clean_trust(self):
        self.assertEqual(
            A()._recommend("CLEAN_PERSISTENT_GAIN"), "TRUST_FEE_STRUCTURE")

    def test_mild_minor(self):
        self.assertEqual(
            A()._recommend("MILD_CLAWBACK_GAP"), "MINOR_CLAWBACK_GAP")

    def test_moderate_demand(self):
        self.assertEqual(
            A()._recommend("MODERATE_CLAWBACK_GAP"),
            "DEMAND_CLAWBACK_PROVISION")

    def test_severe_avoid(self):
        self.assertEqual(
            A()._recommend("SEVERE_CLAWBACK_GAP"), "AVOID_NO_CLAWBACK")

    def test_insufficient_avoid(self):
        self.assertEqual(
            A()._recommend("INSUFFICIENT_DATA"), "AVOID_NO_CLAWBACK")

    def test_recommendation_via_result_clean(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=20.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"], "TRUST_FEE_STRUCTURE")

    def test_recommendation_via_result_severe(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=12.0, realized_gain_pct=1.0,
            performance_fee_pct=50.0))
        self.assertEqual(r["recommendation"], "AVOID_NO_CLAWBACK")


# ── portfolio / aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def test_portfolio_shape(self):
        out = A().analyze_portfolio(_demo_positions())
        self.assertIn("positions", out)
        self.assertIn("aggregate", out)
        self.assertEqual(len(out["positions"]), len(_demo_positions()))

    def test_aggregate_fields(self):
        agg = A().analyze_portfolio(_demo_positions())["aggregate"]
        for key in (
            "cleanest_vault", "worst_clawback_vault", "avg_score",
            "net_negative_count", "position_count",
        ):
            self.assertIn(key, agg)

    def test_aggregate_all_insufficient(self):
        out = A().analyze_portfolio([{"vault": "x"}, {"vault": "y"}])
        agg = out["aggregate"]
        self.assertIsNone(agg["cleanest_vault"])
        self.assertIsNone(agg["worst_clawback_vault"])
        self.assertEqual(agg["avg_score"], 0.0)
        self.assertEqual(agg["net_negative_count"], 0)
        self.assertEqual(agg["position_count"], 2)

    def test_aggregate_empty(self):
        out = A().analyze_portfolio([])
        agg = out["aggregate"]
        self.assertIsNone(agg["cleanest_vault"])
        self.assertEqual(agg["position_count"], 0)

    def test_cleanest_has_highest_score(self):
        out = A().analyze_portfolio(_demo_positions())
        scored = [
            r for r in out["positions"]
            if r["classification"] != "INSUFFICIENT_DATA"]
        best = max(scored, key=lambda r: r["score"])
        self.assertEqual(out["aggregate"]["cleanest_vault"], best["token"])

    def test_worst_has_lowest_score(self):
        out = A().analyze_portfolio(_demo_positions())
        scored = [
            r for r in out["positions"]
            if r["classification"] != "INSUFFICIENT_DATA"]
        worst = min(scored, key=lambda r: r["score"])
        self.assertEqual(
            out["aggregate"]["worst_clawback_vault"], worst["token"])

    def test_net_negative_count(self):
        positions = [
            make_pos(vault="neg", peak_unrealized_gain_pct=12.0,
                     realized_gain_pct=1.0, performance_fee_pct=50.0),
            make_pos(vault="ok", peak_unrealized_gain_pct=20.0,
                     realized_gain_pct=20.0, performance_fee_pct=20.0),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["net_negative_count"], 1)

    def test_net_negative_count_zero(self):
        positions = [
            make_pos(vault="a", peak_unrealized_gain_pct=20.0,
                     realized_gain_pct=20.0, performance_fee_pct=20.0),
            make_pos(vault="b", peak_unrealized_gain_pct=20.0,
                     realized_gain_pct=18.0, performance_fee_pct=10.0),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["net_negative_count"], 0)

    def test_position_count(self):
        agg = A().analyze_portfolio(_demo_positions())["aggregate"]
        self.assertEqual(agg["position_count"], len(_demo_positions()))

    def test_avg_score_excludes_insufficient(self):
        positions = [
            make_pos(vault="a", peak_unrealized_gain_pct=20.0,
                     realized_gain_pct=10.0, performance_fee_pct=0.0),
            make_pos(vault="bad", performance_fee_pct=20.0),  # insufficient
        ]
        out = A().analyze_portfolio(positions)
        agg = out["aggregate"]
        self.assertAlmostEqual(agg["avg_score"], 100.0, places=2)
        self.assertEqual(agg["position_count"], 2)


# ── finite / robustness ─────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_all_demo_finite(self):
        for p in _demo_positions():
            finite_check(self, A()._analyze_one(p))

    def test_no_infinity_nan_in_json(self):
        out = A().analyze_portfolio(_demo_positions())
        text = json.dumps(out)
        self.assertNotIn("Infinity", text)
        self.assertNotIn("NaN", text)

    def test_every_float_finite_or_none(self):
        positions = _demo_positions() + [
            make_pos(peak_unrealized_gain_pct=20.0, realized_gain_pct=-50.0,
                     performance_fee_pct=20.0),
            make_pos(peak_unrealized_gain_pct=24.0, clawback_gap_pct=20.0,
                     fee_paid_on_peak_pct=12.0),
        ]
        for p in positions:
            r = A()._analyze_one(p)
            for k, v in r.items():
                if isinstance(v, float):
                    self.assertTrue(math.isfinite(v), f"{k}={v}")
                elif v is None or isinstance(v, (int, str, bool, list)):
                    pass

    def test_token_field_alias(self):
        r = A()._analyze_one({
            "token": "T1", "peak_unrealized_gain_pct": 20.0,
            "realized_gain_pct": 10.0, "performance_fee_pct": 20.0})
        self.assertEqual(r["token"], "T1")

    def test_unknown_token(self):
        r = A()._analyze_one({
            "peak_unrealized_gain_pct": 20.0, "performance_fee_pct": 20.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_vault_preferred_over_token(self):
        r = A()._analyze_one({
            "vault": "V", "token": "T", "peak_unrealized_gain_pct": 20.0,
            "performance_fee_pct": 20.0})
        self.assertEqual(r["token"], "V")

    def test_huge_peak_no_overflow(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=1e6, realized_gain_pct=10.0,
            performance_fee_pct=20.0))
        finite_check(self, r)

    def test_huge_negative_realized_no_overflow(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=-1e6,
            performance_fee_pct=20.0))
        finite_check(self, r)

    def test_string_realized(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct="10",
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["realized_gain_pct"], 10.0, places=4)

    def test_nan_realized_defaults_zero(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=float("nan"),
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["realized_gain_pct"], 0.0, places=6)

    def test_garbage_realized_defaults_zero(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct="garbage",
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["realized_gain_pct"], 0.0, places=6)


# ── rounding ─────────────────────────────────────────────────────────────────────

class TestRounding(unittest.TestCase):
    def test_score_rounded_2dp(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=16.0, realized_gain_pct=8.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["score"], round(r["score"], 2))

    def test_ratio_rounded_4dp(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=16.0, realized_gain_pct=8.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["realization_ratio"],
                         round(r["realization_ratio"], 4))

    def test_fee_on_reverted_rounded_4dp(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=5.0,
            fee_paid_on_peak_pct=12.0))
        self.assertEqual(r["fee_on_reverted_fraction"],
                         round(r["fee_on_reverted_fraction"], 4))


# ── result keys / shape ──────────────────────────────────────────────────────────

class TestResultShape(unittest.TestCase):
    def test_main_result_keys(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=20.0,
            performance_fee_pct=20.0))
        expected = set(A()._insufficient("x").keys())
        self.assertEqual(set(r.keys()), expected)

    def test_override_result_keys(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=24.0, clawback_gap_pct=5.0,
            fee_paid_on_peak_pct=12.0))
        expected = set(A()._insufficient("x").keys())
        self.assertEqual(set(r.keys()), expected)

    def test_insufficient_result_keys(self):
        r = A()._analyze_one(make_pos(performance_fee_pct=20.0))
        expected = set(A()._insufficient("x").keys())
        self.assertEqual(set(r.keys()), expected)

    def test_all_demo_same_keys(self):
        expected = set(A()._insufficient("x").keys())
        for p in _demo_positions():
            r = A()._analyze_one(p)
            self.assertEqual(set(r.keys()), expected)

    def test_sample_count_zero(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=20.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["sample_count"], 0)

    def test_used_main_true_on_main(self):
        r = A()._analyze_one(make_pos(
            peak_unrealized_gain_pct=20.0, realized_gain_pct=20.0,
            performance_fee_pct=20.0))
        self.assertTrue(r["used_main"])
        self.assertFalse(r["used_override"])


# ── logging ─────────────────────────────────────────────────────────────────────

class TestLogging(unittest.TestCase):
    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "log.json")
            A().analyze_portfolio(
                _demo_positions(), cfg={"log_path": path}, write_log=True)
            self.assertTrue(os.path.exists(path))
            with open(path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_log_ring_buffer_cap_small(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for _ in range(5):
                A().analyze_portfolio(
                    _demo_positions(),
                    cfg={"log_path": path, "log_cap": 3}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_log_ring_buffer_cap_100(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for _ in range(105):
                A().analyze(
                    make_pos(peak_unrealized_gain_pct=20.0,
                             realized_gain_pct=20.0, performance_fee_pct=20.0),
                    cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), LOG_CAP)

    def test_log_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio(
                _demo_positions(), cfg={"log_path": path}, write_log=True)
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_log_corrupt_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as fh:
                fh.write("{ not json")
            A().analyze_portfolio(
                _demo_positions(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_log_non_list_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as fh:
                json.dump({"not": "a list"}, fh)
            A().analyze_portfolio(
                _demo_positions(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_analyze_single_write_log(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(
                _demo_positions()[0], cfg={"log_path": path}, write_log=True)
            self.assertTrue(os.path.exists(path))

    def test_log_entry_shape(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio(
                _demo_positions(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            entry = data[0]
            for key in ("ts", "position_count", "aggregate", "snapshots"):
                self.assertIn(key, entry)

    def test_log_snapshot_shape(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio(
                _demo_positions(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            snap = data[0]["snapshots"][0]
            for key in (
                "token", "classification", "score", "recommendation", "flags",
            ):
                self.assertIn(key, snap)

    def test_log_deterministic_snapshot_tokens(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio(
                _demo_positions(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            tokens = [s["token"] for s in data[0]["snapshots"]]
            expected = [p["vault"] for p in _demo_positions()]
            self.assertEqual(tokens, expected)

    def test_no_write_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio(_demo_positions(), cfg={"log_path": path})
            self.assertFalse(os.path.exists(path))

    def test_log_does_not_pollute_real_data(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio(
                _demo_positions(), cfg={"log_path": path}, write_log=True)
            self.assertTrue(os.path.exists(path))
            self.assertNotEqual(path, LOG_PATH)


# ── CLI / demo validity ─────────────────────────────────────────────────────────

class TestDemo(unittest.TestCase):
    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 5)

    def test_demo_has_each_class(self):
        results = [A()._analyze_one(p) for p in _demo_positions()]
        classes = {r["classification"] for r in results}
        self.assertIn("CLEAN_PERSISTENT_GAIN", classes)
        self.assertIn("MODERATE_CLAWBACK_GAP", classes)
        self.assertIn("SEVERE_CLAWBACK_GAP", classes)
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_override_present(self):
        results = [A()._analyze_one(p) for p in _demo_positions()]
        self.assertTrue(any(r["used_override"] for r in results))

    def test_demo_main_present(self):
        results = [A()._analyze_one(p) for p in _demo_positions()]
        self.assertTrue(any(r["used_main"] for r in results))

    def test_demo_net_negative_present(self):
        results = [A()._analyze_one(p) for p in _demo_positions()]
        self.assertTrue(any(r["net_is_negative"] for r in results))

    def test_demo_determinism(self):
        first = A().analyze_portfolio(_demo_positions())["positions"]
        second = A().analyze_portfolio(_demo_positions())["positions"]
        self.assertEqual(
            [r["score"] for r in first], [r["score"] for r in second])

    def test_demo_json_serializable(self):
        out = A().analyze_portfolio(_demo_positions())
        json.dumps(out)

    def test_demo_portfolio_classifications(self):
        out = A().analyze_portfolio(_demo_positions())
        classes = [r["classification"] for r in out["positions"]]
        self.assertEqual(classes, [
            "CLEAN_PERSISTENT_GAIN",
            "MODERATE_CLAWBACK_GAP",
            "SEVERE_CLAWBACK_GAP",
            "MODERATE_CLAWBACK_GAP",
            "INSUFFICIENT_DATA",
        ])


# ── registry integration ────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    def test_registered(self):
        from spa_core.analytics import _module_registry as reg
        names = [m["module"] for m in reg.ALL_MODULES]
        self.assertIn(
            "defi_protocol_vault_performance_fee_unrealized_gain_clawback_gap_analyzer",  # noqa: E501
            names)

    def test_registry_entry_fields(self):
        from spa_core.analytics import _module_registry as reg
        entry = next(
            m for m in reg.ALL_MODULES
            if m["module"]
            == "defi_protocol_vault_performance_fee_unrealized_gain_clawback_gap_analyzer")  # noqa: E501
        self.assertEqual(entry["tier"], "B")
        self.assertEqual(entry["category"], "yield_quality")
        self.assertEqual(entry["weight"], 0.5)
        self.assertEqual(
            entry["class"],
            "DeFiProtocolVaultPerformanceFeeUnrealizedGainClawbackGapAnalyzer")

    def test_registry_get_module_info(self):
        from spa_core.analytics import _module_registry as reg
        info = reg.get_module_info(
            "defi_protocol_vault_performance_fee_unrealized_gain_clawback_gap_analyzer")  # noqa: E501
        self.assertIsNotNone(info)
        self.assertEqual(info["tier"], "B")


# ── constants sanity ─────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_thresholds_ordered(self):
        self.assertLess(CLEAN_FRACTION, MILD_FRACTION)
        self.assertLess(MILD_FRACTION, MODERATE_FRACTION)

    def test_clean_fraction(self):
        self.assertEqual(CLEAN_FRACTION, 0.05)

    def test_mild_fraction(self):
        self.assertEqual(MILD_FRACTION, 0.20)

    def test_moderate_fraction(self):
        self.assertEqual(MODERATE_FRACTION, 0.50)

    def test_log_cap(self):
        self.assertEqual(LOG_CAP, 100)

    def test_eps_tiny(self):
        self.assertLess(EPS, 1e-6)

    def test_clean_fraction_positive(self):
        self.assertGreater(CLEAN_FRACTION, 0.0)

    def test_moderate_fraction_below_one(self):
        self.assertLess(MODERATE_FRACTION, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
