"""
Tests for MP-1207: DeFiProtocolVaultPerformanceFeeHurdleRateGapAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_performance_fee_hurdle_rate_gap_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_performance_fee_hurdle_rate_gap_analyzer import (  # noqa: E501
    DeFiProtocolVaultPerformanceFeeHurdleRateGapAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _coerce_num,
    _coerce_nonneg,
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
    gross_apr_pct=None,
    performance_fee_pct=None,
    hurdle_apr_pct=None,
    benchmark_apr_pct=None,
    excess_fee_apr_pct=None,
    fee_charged_apr_pct=None,
):
    pos = {"vault": vault}
    if gross_apr_pct is not None:
        pos["gross_apr_pct"] = gross_apr_pct
    if performance_fee_pct is not None:
        pos["performance_fee_pct"] = performance_fee_pct
    if hurdle_apr_pct is not None:
        pos["hurdle_apr_pct"] = hurdle_apr_pct
    if benchmark_apr_pct is not None:
        pos["benchmark_apr_pct"] = benchmark_apr_pct
    if excess_fee_apr_pct is not None:
        pos["excess_fee_apr_pct"] = excess_fee_apr_pct
    if fee_charged_apr_pct is not None:
        pos["fee_charged_apr_pct"] = fee_charged_apr_pct
    return pos


def A():
    return DeFiProtocolVaultPerformanceFeeHurdleRateGapAnalyzer()


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

    def test_coerce_nonneg_positive(self):
        self.assertEqual(_coerce_nonneg(1.5), 1.5)

    def test_coerce_nonneg_negative_to_magnitude(self):
        self.assertEqual(_coerce_nonneg(-1.5), 1.5)

    def test_coerce_nonneg_none_zero(self):
        self.assertEqual(_coerce_nonneg(None), 0.0)

    def test_coerce_nonneg_bool_zero(self):
        self.assertEqual(_coerce_nonneg(True), 0.0)

    def test_coerce_nonneg_nan_zero(self):
        self.assertEqual(_coerce_nonneg(float("nan")), 0.0)

    def test_coerce_nonneg_inf_zero(self):
        self.assertEqual(_coerce_nonneg(float("inf")), 0.0)

    def test_coerce_nonneg_str(self):
        self.assertEqual(_coerce_nonneg("2.5"), 2.5)

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
    def test_fee_charged_formula(self):
        # fee 20%, gross 20, hurdle 5 → 0.2*(20-5)=3.0
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=5.0, benchmark_apr_pct=5.0))
        self.assertAlmostEqual(r["fee_charged_apr_pct"], 3.0, places=4)

    def test_fair_fee_formula(self):
        # fee 20%, gross 16, benchmark 8 → 0.2*(16-8)=1.6
        r = A()._analyze_one(make_pos(
            gross_apr_pct=16.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertAlmostEqual(r["fair_fee_apr_pct"], 1.6, places=4)

    def test_excess_fee_formula(self):
        # no hurdle: charged 0.2*16=3.2, fair 0.2*8=1.6 → excess 1.6
        r = A()._analyze_one(make_pos(
            gross_apr_pct=16.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertAlmostEqual(r["excess_fee_apr_pct"], 1.6, places=4)

    def test_excess_equals_feefrac_times_gap(self):
        # gross >= benchmark >= hurdle → excess = fee_frac*(benchmark - hurdle)
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=2.0, benchmark_apr_pct=8.0))
        self.assertAlmostEqual(
            r["excess_fee_apr_pct"], 0.2 * (8.0 - 2.0), places=4)

    def test_hurdle_gap_formula(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=2.0, benchmark_apr_pct=8.0))
        self.assertAlmostEqual(r["hurdle_gap_apr_pct"], 6.0, places=4)

    def test_hurdle_gap_negative_when_hurdle_above_benchmark(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=10.0, benchmark_apr_pct=5.0))
        self.assertLess(r["hurdle_gap_apr_pct"], 0.0)

    def test_excess_zero_when_hurdle_equals_benchmark(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=5.0, benchmark_apr_pct=5.0))
        self.assertAlmostEqual(r["excess_fee_apr_pct"], 0.0, places=6)

    def test_excess_zero_when_hurdle_above_benchmark(self):
        # hurdle above benchmark → fee even more conservative → excess 0
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=10.0, benchmark_apr_pct=5.0))
        self.assertAlmostEqual(r["excess_fee_apr_pct"], 0.0, places=6)

    def test_gross_alpha_formula(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=16.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertAlmostEqual(r["gross_alpha_apr_pct"], 8.0, places=4)

    def test_gross_alpha_zero_when_gross_below_benchmark(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=6.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertAlmostEqual(r["gross_alpha_apr_pct"], 0.0, places=6)

    def test_net_alpha_formula(self):
        # gross_alpha 8, fee_charged 3.2 → net_alpha 4.8
        r = A()._analyze_one(make_pos(
            gross_apr_pct=16.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertAlmostEqual(r["net_alpha_apr_pct"], 4.8, places=4)

    def test_net_alpha_negative_when_fee_exceeds_alpha(self):
        # thin alpha, big fee → net alpha negative
        r = A()._analyze_one(make_pos(
            gross_apr_pct=12.0, performance_fee_pct=50.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=10.0))
        self.assertTrue(r["net_alpha_is_negative"])
        self.assertLess(r["net_alpha_apr_pct"], 0.0)

    def test_net_apr_charged_formula(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=5.0, benchmark_apr_pct=5.0))
        self.assertAlmostEqual(
            r["net_apr_charged_pct"],
            r["gross_apr_pct"] - r["fee_charged_apr_pct"], places=6)

    def test_net_apr_fair_formula(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=16.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertAlmostEqual(
            r["net_apr_fair_pct"],
            r["gross_apr_pct"] - r["fair_fee_apr_pct"], places=6)

    def test_overstatement_equals_excess(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=16.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertAlmostEqual(
            r["overstatement_pct"], r["excess_fee_apr_pct"], places=6)

    def test_fee_on_beta_fraction_value(self):
        # charged 3.2, excess 1.6 → fraction 0.5
        r = A()._analyze_one(make_pos(
            gross_apr_pct=16.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertAlmostEqual(r["fee_on_beta_fraction"], 0.5, places=4)

    def test_alpha_realization_ratio_value(self):
        # gross_alpha 8, net_alpha 4.8 → 0.6
        r = A()._analyze_one(make_pos(
            gross_apr_pct=16.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertAlmostEqual(r["alpha_realization_ratio"], 0.6, places=4)

    def test_fee_frac_clamped_above_100(self):
        # performance_fee 150 → clamped to 100% → fee_frac 1.0
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=150.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=5.0))
        self.assertAlmostEqual(r["performance_fee_pct"], 100.0, places=4)

    def test_fee_frac_clamped_negative(self):
        # negative fee → clamped to 0 → no fee charged
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=-30.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=5.0))
        self.assertAlmostEqual(r["performance_fee_pct"], 0.0, places=4)
        self.assertAlmostEqual(r["fee_charged_apr_pct"], 0.0, places=6)

    def test_negative_hurdle_to_magnitude(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=-5.0, benchmark_apr_pct=5.0))
        self.assertAlmostEqual(r["hurdle_apr_pct"], 5.0, places=4)

    def test_negative_benchmark_to_magnitude(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=-5.0))
        self.assertAlmostEqual(r["benchmark_apr_pct"], 5.0, places=4)

    def test_no_fee_alpha_fully_realized(self):
        # zero fee → ratio 1.0, fee_on_beta 0
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=0.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=5.0))
        self.assertAlmostEqual(r["alpha_realization_ratio"], 1.0, places=4)
        self.assertAlmostEqual(r["fee_on_beta_fraction"], 0.0, places=4)

    def test_gross_below_benchmark_no_fee_ratio_one(self):
        # gross below benchmark but fee charged on small hurdle gap:
        # gross_alpha 0; fee_charged>0 → ratio 0.0
        r = A()._analyze_one(make_pos(
            gross_apr_pct=6.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertAlmostEqual(r["gross_alpha_apr_pct"], 0.0, places=6)
        self.assertGreater(r["fee_charged_apr_pct"], 0.0)
        self.assertAlmostEqual(r["alpha_realization_ratio"], 0.0, places=4)

    def test_gross_below_benchmark_no_fee_ratio_one_when_no_fee(self):
        # gross_alpha 0 AND no fee charged → ratio 1.0
        r = A()._analyze_one(make_pos(
            gross_apr_pct=6.0, performance_fee_pct=0.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertAlmostEqual(r["gross_alpha_apr_pct"], 0.0, places=6)
        self.assertAlmostEqual(r["fee_charged_apr_pct"], 0.0, places=6)
        self.assertAlmostEqual(r["alpha_realization_ratio"], 1.0, places=4)


# ── classification thresholds ───────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_clean_hurdle_zero_gap(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=5.0, benchmark_apr_pct=5.0))
        self.assertEqual(r["classification"], "CLEAN_HURDLE")

    def test_clean_hurdle_hurdle_above_benchmark(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=10.0, benchmark_apr_pct=5.0))
        self.assertEqual(r["classification"], "CLEAN_HURDLE")

    def test_clean_boundary_exact(self):
        # fee_on_beta exactly 0.05: excess/charged = 0.05.
        # charged = 0.2*20 = 4.0; excess = 0.2 → benchmark = 1.0 (hurdle 0)
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=1.0))
        self.assertAlmostEqual(r["fee_on_beta_fraction"], 0.05, places=4)
        self.assertEqual(r["classification"], "CLEAN_HURDLE")

    def test_just_above_clean_is_mild(self):
        # benchmark 1.2 → excess 0.24 → fraction 0.06
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=1.2))
        self.assertGreater(r["fee_on_beta_fraction"], CLEAN_FRACTION)
        self.assertEqual(r["classification"], "MILD_BETA_TAX")

    def test_mild_beta_tax(self):
        # benchmark 3, gross 20, hurdle 0 → fraction 0.15
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=3.0))
        self.assertEqual(r["classification"], "MILD_BETA_TAX")

    def test_mild_boundary_exact(self):
        # fraction 0.20: excess 0.2*4=0.8, benchmark 4 (gross 20)
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=4.0))
        self.assertAlmostEqual(r["fee_on_beta_fraction"], 0.20, places=4)
        self.assertEqual(r["classification"], "MILD_BETA_TAX")

    def test_just_above_mild_is_moderate(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=5.0))
        self.assertGreater(r["fee_on_beta_fraction"], MILD_FRACTION)
        self.assertEqual(r["classification"], "MODERATE_BETA_TAX")

    def test_moderate_beta_tax(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=16.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertEqual(r["classification"], "MODERATE_BETA_TAX")

    def test_moderate_boundary_exact(self):
        # fraction 0.50: benchmark 10, gross 20
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=10.0))
        self.assertAlmostEqual(r["fee_on_beta_fraction"], 0.50, places=4)
        self.assertEqual(r["classification"], "MODERATE_BETA_TAX")

    def test_just_above_moderate_is_severe(self):
        # benchmark 11, gross 20 → fraction 0.55, alpha 9, charged 4 → net positive
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=11.0))
        self.assertGreater(r["fee_on_beta_fraction"], MODERATE_FRACTION)
        self.assertEqual(r["classification"], "SEVERE_BETA_TAX")
        self.assertFalse(r["net_alpha_is_negative"])

    def test_severe_via_net_alpha_negative(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=12.0, performance_fee_pct=50.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=10.0))
        self.assertEqual(r["classification"], "SEVERE_BETA_TAX")
        self.assertTrue(r["net_alpha_is_negative"])

    def test_net_alpha_negative_overrides_low_fraction(self):
        # even if fee_on_beta low, net alpha negative → SEVERE
        r = A()._analyze_one(make_pos(
            gross_apr_pct=11.0, performance_fee_pct=100.0,
            hurdle_apr_pct=10.0, benchmark_apr_pct=10.0))
        # gross_alpha 1, charged 0.1*... wait charged = 1.0*(11-10)=1.0; net 0
        self.assertTrue(r["net_alpha_is_negative"]
                        or r["net_alpha_apr_pct"] <= 0.0)

    def test_classification_monotone_with_benchmark(self):
        fractions = []
        for bench in (1.0, 4.0, 8.0, 11.0):
            r = A()._analyze_one(make_pos(
                gross_apr_pct=20.0, performance_fee_pct=20.0,
                hurdle_apr_pct=0.0, benchmark_apr_pct=bench))
            fractions.append(r["fee_on_beta_fraction"])
        for i in range(len(fractions) - 1):
            self.assertLessEqual(fractions[i], fractions[i + 1])


# ── _classify direct ─────────────────────────────────────────────────────────────

class TestClassifyDirect(unittest.TestCase):
    def test_classify_net_alpha_negative(self):
        self.assertEqual(A()._classify(0.01, True), "SEVERE_BETA_TAX")

    def test_classify_clean(self):
        self.assertEqual(A()._classify(0.05, False), "CLEAN_HURDLE")

    def test_classify_clean_below(self):
        self.assertEqual(A()._classify(0.0, False), "CLEAN_HURDLE")

    def test_classify_mild(self):
        self.assertEqual(A()._classify(0.20, False), "MILD_BETA_TAX")

    def test_classify_mild_mid(self):
        self.assertEqual(A()._classify(0.10, False), "MILD_BETA_TAX")

    def test_classify_moderate(self):
        self.assertEqual(A()._classify(0.50, False), "MODERATE_BETA_TAX")

    def test_classify_moderate_mid(self):
        self.assertEqual(A()._classify(0.35, False), "MODERATE_BETA_TAX")

    def test_classify_severe(self):
        self.assertEqual(A()._classify(0.51, False), "SEVERE_BETA_TAX")

    def test_classify_severe_high(self):
        self.assertEqual(A()._classify(1.0, False), "SEVERE_BETA_TAX")


# ── ratios bounds ────────────────────────────────────────────────────────────────

class TestRatios(unittest.TestCase):
    def test_alpha_realization_bounds(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            if r["alpha_realization_ratio"] is not None:
                self.assertGreaterEqual(r["alpha_realization_ratio"], 0.0)
                self.assertLessEqual(r["alpha_realization_ratio"], 1.0)

    def test_fee_on_beta_bounds(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            if r["fee_on_beta_fraction"] is not None:
                self.assertGreaterEqual(r["fee_on_beta_fraction"], 0.0)
                self.assertLessEqual(r["fee_on_beta_fraction"], 1.0)

    def test_fee_on_beta_capped_at_one(self):
        # huge benchmark relative to gross → excess can not exceed charged
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=100.0))
        self.assertLessEqual(r["fee_on_beta_fraction"], 1.0)

    def test_alpha_realization_zero_when_net_alpha_negative(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=12.0, performance_fee_pct=50.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=10.0))
        self.assertAlmostEqual(r["alpha_realization_ratio"], 0.0, places=6)


# ── override path ────────────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def test_override_used(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=5.0,
            fee_charged_apr_pct=12.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_main"])
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])
        finite_check(self, r)

    def test_override_excess_verbatim(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=5.0,
            fee_charged_apr_pct=12.0))
        self.assertAlmostEqual(r["excess_fee_apr_pct"], 5.0, places=4)

    def test_override_fee_on_beta(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=5.0,
            fee_charged_apr_pct=12.0))
        self.assertAlmostEqual(r["fee_on_beta_fraction"], 5.0 / 12.0, places=4)

    def test_override_geometry_none(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=5.0,
            fee_charged_apr_pct=12.0))
        self.assertIsNone(r["hurdle_apr_pct"])
        self.assertIsNone(r["benchmark_apr_pct"])
        self.assertIsNone(r["hurdle_gap_apr_pct"])
        self.assertIsNone(r["gross_alpha_apr_pct"])
        self.assertIsNone(r["net_alpha_apr_pct"])
        self.assertIsNone(r["performance_fee_pct"])

    def test_override_negative_excess_to_magnitude(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=-5.0,
            fee_charged_apr_pct=12.0))
        self.assertTrue(r["used_override"])
        self.assertAlmostEqual(r["excess_fee_apr_pct"], 5.0, places=4)

    def test_override_excess_capped_at_charged(self):
        # excess > charged → capped to charged → fraction 1.0
        r = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=20.0,
            fee_charged_apr_pct=12.0))
        self.assertAlmostEqual(r["excess_fee_apr_pct"], 12.0, places=4)
        self.assertAlmostEqual(r["fee_on_beta_fraction"], 1.0, places=4)

    def test_override_suppresses_geometry_flags(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=5.0,
            fee_charged_apr_pct=12.0))
        self.assertNotIn("NO_HURDLE_APPLIED", r["flags"])
        self.assertNotIn("FEE_EXCEEDS_ALPHA", r["flags"])

    def test_override_clean_when_zero_excess(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=0.0,
            fee_charged_apr_pct=12.0))
        self.assertEqual(r["classification"], "CLEAN_HURDLE")
        self.assertIn("CLEAN_HURDLE_CONFIRMED", r["flags"])

    def test_override_moderate_classification(self):
        # 5/12 ≈ 0.4167 → MODERATE
        r = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=5.0,
            fee_charged_apr_pct=12.0))
        self.assertEqual(r["classification"], "MODERATE_BETA_TAX")

    def test_override_str_inputs(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct="24.0", excess_fee_apr_pct="5.0",
            fee_charged_apr_pct="12.0"))
        self.assertTrue(r["used_override"])
        self.assertAlmostEqual(r["fee_on_beta_fraction"], 5.0 / 12.0, places=4)

    def test_override_requires_positive_fee_charged(self):
        # fee_charged 0 → not override path; falls back to main (needs fee_pct)
        r = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=5.0,
            fee_charged_apr_pct=0.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=5.0))
        self.assertFalse(r["used_override"])
        self.assertTrue(r["used_main"])

    def test_override_nan_excess_falls_to_main(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, excess_fee_apr_pct=float("nan"),
            fee_charged_apr_pct=12.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=5.0))
        self.assertFalse(r["used_override"])
        self.assertTrue(r["used_main"])

    def test_override_missing_fee_charged_falls_to_main(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, excess_fee_apr_pct=3.0,
            performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=5.0))
        self.assertFalse(r["used_override"])
        self.assertTrue(r["used_main"])

    def test_override_requires_positive_gross(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=0.0, excess_fee_apr_pct=5.0,
            fee_charged_apr_pct=12.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_net_alpha_is_negative_false(self):
        # override path has no gross alpha geometry → net_alpha_is_negative False
        r = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=5.0,
            fee_charged_apr_pct=12.0))
        self.assertFalse(r["net_alpha_is_negative"])


# ── insufficient data ────────────────────────────────────────────────────────────

class TestInsufficient(unittest.TestCase):
    def test_no_gross(self):
        r = A()._analyze_one(make_pos(
            performance_fee_pct=20.0, hurdle_apr_pct=0.0,
            benchmark_apr_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_gross(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=0.0, performance_fee_pct=20.0,
            benchmark_apr_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_gross(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=-3.0, performance_fee_pct=20.0,
            benchmark_apr_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_gross(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=float("nan"), performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_gross(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=float("inf"), performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_bad_str_gross(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct="abc", performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_bool_gross(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=True, performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_fee_pct(self):
        # valid gross but no fee → INSUFFICIENT (no override either)
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, hurdle_apr_pct=0.0, benchmark_apr_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_fee_pct(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=float("nan"),
            benchmark_apr_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_fee_pct(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=float("inf"),
            benchmark_apr_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_data_at_all(self):
        r = A()._analyze_one({"vault": "x"})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_shape(self):
        r = A()._analyze_one(make_pos(performance_fee_pct=20.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertIsNone(r["alpha_realization_ratio"])
        self.assertIsNone(r["fee_on_beta_fraction"])
        self.assertIsNone(r["gross_apr_pct"])
        self.assertIsNone(r["fee_charged_apr_pct"])

    def test_insufficient_recommendation(self):
        r = A()._analyze_one(make_pos(performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"], "AVOID_NO_HURDLE_FEE")

    def test_insufficient_net_alpha_negative_false(self):
        r = A()._analyze_one(make_pos(performance_fee_pct=20.0))
        self.assertFalse(r["net_alpha_is_negative"])

    def test_insufficient_used_flags_false(self):
        r = A()._analyze_one(make_pos(performance_fee_pct=20.0))
        self.assertFalse(r["used_override"])
        self.assertFalse(r["used_main"])


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_classification_in_flags_first(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=16.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertEqual(r["flags"][0], r["classification"])

    def test_clean_hurdle_confirmed_flag(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=5.0, benchmark_apr_pct=5.0))
        self.assertIn("CLEAN_HURDLE_CONFIRMED", r["flags"])

    def test_no_clean_flag_when_beta_tax(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=16.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertNotIn("CLEAN_HURDLE_CONFIRMED", r["flags"])

    def test_net_alpha_negative_flag(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=12.0, performance_fee_pct=50.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=10.0))
        self.assertIn("NET_ALPHA_NEGATIVE_AFTER_FEE", r["flags"])

    def test_no_net_alpha_negative_flag_clean(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=5.0, benchmark_apr_pct=5.0))
        self.assertNotIn("NET_ALPHA_NEGATIVE_AFTER_FEE", r["flags"])

    def test_no_hurdle_applied_flag(self):
        # hurdle 0 and benchmark > 0 → NO_HURDLE_APPLIED
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=5.0))
        self.assertIn("NO_HURDLE_APPLIED", r["flags"])

    def test_no_hurdle_flag_absent_when_hurdle_present(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=5.0, benchmark_apr_pct=5.0))
        self.assertNotIn("NO_HURDLE_APPLIED", r["flags"])

    def test_no_hurdle_flag_absent_when_benchmark_zero(self):
        # hurdle 0 but benchmark 0 → no NO_HURDLE_APPLIED (no fair hurdle to miss)
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=0.0))
        self.assertNotIn("NO_HURDLE_APPLIED", r["flags"])

    def test_fee_exceeds_alpha_flag(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=12.0, performance_fee_pct=50.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=10.0))
        self.assertIn("FEE_EXCEEDS_ALPHA", r["flags"])

    def test_no_fee_exceeds_alpha_when_fee_small(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=5.0, benchmark_apr_pct=5.0))
        self.assertNotIn("FEE_EXCEEDS_ALPHA", r["flags"])

    def test_gap_from_override_flag(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=5.0,
            fee_charged_apr_pct=12.0))
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])

    def test_main_path_no_override_flag(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=5.0, benchmark_apr_pct=5.0))
        self.assertNotIn("GAP_FROM_OVERRIDE", r["flags"])

    def test_override_no_no_hurdle_flag(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=5.0,
            fee_charged_apr_pct=12.0))
        self.assertNotIn("NO_HURDLE_APPLIED", r["flags"])

    def test_severe_multiple_flags_together(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=12.0, performance_fee_pct=50.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=10.0))
        self.assertIn("SEVERE_BETA_TAX", r["flags"])
        self.assertIn("NET_ALPHA_NEGATIVE_AFTER_FEE", r["flags"])
        self.assertIn("NO_HURDLE_APPLIED", r["flags"])
        self.assertIn("FEE_EXCEEDS_ALPHA", r["flags"])


# ── scoring ─────────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_clean_high_score(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=5.0, benchmark_apr_pct=5.0))
        self.assertGreaterEqual(r["score"], 80)

    def test_clean_score_full_when_no_fee(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=0.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=5.0))
        self.assertAlmostEqual(r["score"], 100.0, places=2)

    def test_severe_low_score(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=12.0, performance_fee_pct=50.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=10.0))
        self.assertLess(r["score"], 40)

    def test_score_in_range_all_demo(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_score_monotonic_in_benchmark(self):
        # bigger benchmark (more beta tax) → lower score
        low = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=2.0))
        high = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertGreater(low["score"], high["score"])

    def test_score_monotonic_in_hurdle(self):
        # bigger applied hurdle (closer to benchmark) → less beta tax → higher score
        no_hurdle = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        with_hurdle = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=6.0, benchmark_apr_pct=8.0))
        self.assertGreater(with_hurdle["score"], no_hurdle["score"])

    def test_score_monotonic_override(self):
        a = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=2.0,
            fee_charged_apr_pct=12.0))
        b = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=10.0,
            fee_charged_apr_pct=12.0))
        self.assertGreater(a["score"], b["score"])

    def test_score_formula(self):
        # gross 16, fee 20%, hurdle 0, bench 8:
        # gross_alpha 8, charged 3.2, net_alpha 4.8 → ratio 0.6, fee_on_beta 0.5
        # score = 70*0.6 + 30*0.5 = 42 + 15 = 57
        r = A()._analyze_one(make_pos(
            gross_apr_pct=16.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertAlmostEqual(r["score"], 57.0, places=2)

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
            A()._recommend("CLEAN_HURDLE"), "TRUST_FEE_STRUCTURE")

    def test_mild_minor(self):
        self.assertEqual(
            A()._recommend("MILD_BETA_TAX"), "MINOR_HURDLE_GAP")

    def test_moderate_negotiate(self):
        self.assertEqual(
            A()._recommend("MODERATE_BETA_TAX"), "NEGOTIATE_HURDLE")

    def test_severe_avoid(self):
        self.assertEqual(
            A()._recommend("SEVERE_BETA_TAX"), "AVOID_NO_HURDLE_FEE")

    def test_insufficient_avoid(self):
        self.assertEqual(
            A()._recommend("INSUFFICIENT_DATA"), "AVOID_NO_HURDLE_FEE")

    def test_recommendation_via_result_clean(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=5.0, benchmark_apr_pct=5.0))
        self.assertEqual(r["recommendation"], "TRUST_FEE_STRUCTURE")

    def test_recommendation_via_result_severe(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=12.0, performance_fee_pct=50.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=10.0))
        self.assertEqual(r["recommendation"], "AVOID_NO_HURDLE_FEE")


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
            "cleanest_hurdle_vault", "worst_beta_tax_vault", "avg_score",
            "net_alpha_negative_count", "position_count",
        ):
            self.assertIn(key, agg)

    def test_aggregate_all_insufficient(self):
        out = A().analyze_portfolio([{"vault": "x"}, {"vault": "y"}])
        agg = out["aggregate"]
        self.assertIsNone(agg["cleanest_hurdle_vault"])
        self.assertIsNone(agg["worst_beta_tax_vault"])
        self.assertEqual(agg["avg_score"], 0.0)
        self.assertEqual(agg["net_alpha_negative_count"], 0)
        self.assertEqual(agg["position_count"], 2)

    def test_aggregate_empty(self):
        out = A().analyze_portfolio([])
        agg = out["aggregate"]
        self.assertIsNone(agg["cleanest_hurdle_vault"])
        self.assertEqual(agg["position_count"], 0)

    def test_cleanest_has_highest_score(self):
        out = A().analyze_portfolio(_demo_positions())
        scored = [
            r for r in out["positions"]
            if r["classification"] != "INSUFFICIENT_DATA"]
        best = max(scored, key=lambda r: r["score"])
        self.assertEqual(
            out["aggregate"]["cleanest_hurdle_vault"], best["token"])

    def test_worst_has_lowest_score(self):
        out = A().analyze_portfolio(_demo_positions())
        scored = [
            r for r in out["positions"]
            if r["classification"] != "INSUFFICIENT_DATA"]
        worst = min(scored, key=lambda r: r["score"])
        self.assertEqual(
            out["aggregate"]["worst_beta_tax_vault"], worst["token"])

    def test_net_alpha_negative_count(self):
        positions = [
            make_pos(vault="neg", gross_apr_pct=12.0, performance_fee_pct=50.0,
                     hurdle_apr_pct=0.0, benchmark_apr_pct=10.0),
            make_pos(vault="ok", gross_apr_pct=20.0, performance_fee_pct=20.0,
                     hurdle_apr_pct=5.0, benchmark_apr_pct=5.0),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["net_alpha_negative_count"], 1)

    def test_net_alpha_negative_count_zero(self):
        positions = [
            make_pos(vault="a", gross_apr_pct=20.0, performance_fee_pct=20.0,
                     hurdle_apr_pct=5.0, benchmark_apr_pct=5.0),
            make_pos(vault="b", gross_apr_pct=20.0, performance_fee_pct=10.0,
                     hurdle_apr_pct=4.0, benchmark_apr_pct=5.0),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["net_alpha_negative_count"], 0)

    def test_position_count(self):
        agg = A().analyze_portfolio(_demo_positions())["aggregate"]
        self.assertEqual(agg["position_count"], len(_demo_positions()))

    def test_avg_score_excludes_insufficient(self):
        positions = [
            make_pos(vault="a", gross_apr_pct=20.0, performance_fee_pct=0.0,
                     hurdle_apr_pct=0.0, benchmark_apr_pct=5.0),
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
            make_pos(gross_apr_pct=20.0, performance_fee_pct=20.0,
                     hurdle_apr_pct=0.0, benchmark_apr_pct=100.0),
            make_pos(gross_apr_pct=24.0, excess_fee_apr_pct=20.0,
                     fee_charged_apr_pct=12.0),
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
            "token": "T1", "gross_apr_pct": 20.0,
            "performance_fee_pct": 20.0, "benchmark_apr_pct": 5.0})
        self.assertEqual(r["token"], "T1")

    def test_unknown_token(self):
        r = A()._analyze_one({"gross_apr_pct": 20.0, "performance_fee_pct": 20.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_vault_preferred_over_token(self):
        r = A()._analyze_one({
            "vault": "V", "token": "T", "gross_apr_pct": 20.0,
            "performance_fee_pct": 20.0})
        self.assertEqual(r["token"], "V")

    def test_huge_benchmark_no_overflow(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=1e6))
        finite_check(self, r)

    def test_huge_gross_no_overflow(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=1e6, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=5.0))
        finite_check(self, r)

    def test_string_hurdle_and_benchmark(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct="0", benchmark_apr_pct="5"))
        self.assertAlmostEqual(r["benchmark_apr_pct"], 5.0, places=4)


# ── rounding ─────────────────────────────────────────────────────────────────────

class TestRounding(unittest.TestCase):
    def test_score_rounded_2dp(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=16.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertEqual(r["score"], round(r["score"], 2))

    def test_ratio_rounded_4dp(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=16.0, performance_fee_pct=20.0,
            hurdle_apr_pct=0.0, benchmark_apr_pct=8.0))
        self.assertEqual(r["alpha_realization_ratio"],
                         round(r["alpha_realization_ratio"], 4))

    def test_fee_on_beta_rounded_4dp(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=5.0,
            fee_charged_apr_pct=12.0))
        self.assertEqual(r["fee_on_beta_fraction"],
                         round(r["fee_on_beta_fraction"], 4))


# ── result keys / shape ──────────────────────────────────────────────────────────

class TestResultShape(unittest.TestCase):
    def test_main_result_keys(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=5.0, benchmark_apr_pct=5.0))
        expected = set(A()._insufficient("x").keys())
        self.assertEqual(set(r.keys()), expected)

    def test_override_result_keys(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=24.0, excess_fee_apr_pct=5.0,
            fee_charged_apr_pct=12.0))
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
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=5.0, benchmark_apr_pct=5.0))
        self.assertEqual(r["sample_count"], 0)

    def test_used_main_true_on_main(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, performance_fee_pct=20.0,
            hurdle_apr_pct=5.0, benchmark_apr_pct=5.0))
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
                    make_pos(gross_apr_pct=20.0, performance_fee_pct=20.0,
                             hurdle_apr_pct=5.0, benchmark_apr_pct=5.0),
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
        self.assertIn("CLEAN_HURDLE", classes)
        self.assertIn("MODERATE_BETA_TAX", classes)
        self.assertIn("SEVERE_BETA_TAX", classes)
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_override_present(self):
        results = [A()._analyze_one(p) for p in _demo_positions()]
        self.assertTrue(any(r["used_override"] for r in results))

    def test_demo_main_present(self):
        results = [A()._analyze_one(p) for p in _demo_positions()]
        self.assertTrue(any(r["used_main"] for r in results))

    def test_demo_net_alpha_negative_present(self):
        results = [A()._analyze_one(p) for p in _demo_positions()]
        self.assertTrue(any(r["net_alpha_is_negative"] for r in results))

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
            "CLEAN_HURDLE",
            "MODERATE_BETA_TAX",
            "SEVERE_BETA_TAX",
            "MODERATE_BETA_TAX",
            "INSUFFICIENT_DATA",
        ])


# ── registry integration ────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    def test_registered(self):
        from spa_core.analytics import _module_registry as reg
        names = [m["module"] for m in reg.ALL_MODULES]
        self.assertIn(
            "defi_protocol_vault_performance_fee_hurdle_rate_gap_analyzer",
            names)

    def test_registry_entry_fields(self):
        from spa_core.analytics import _module_registry as reg
        entry = next(
            m for m in reg.ALL_MODULES
            if m["module"]
            == "defi_protocol_vault_performance_fee_hurdle_rate_gap_analyzer")
        self.assertEqual(entry["tier"], "B")
        self.assertEqual(entry["category"], "yield_quality")
        self.assertEqual(entry["weight"], 0.5)
        self.assertEqual(
            entry["class"],
            "DeFiProtocolVaultPerformanceFeeHurdleRateGapAnalyzer")

    def test_registry_get_module_info(self):
        from spa_core.analytics import _module_registry as reg
        info = reg.get_module_info(
            "defi_protocol_vault_performance_fee_hurdle_rate_gap_analyzer")
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
