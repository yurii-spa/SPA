"""
Tests for MP-1188: DeFiProtocolVaultEntryFeeAmortizationAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_entry_fee_amortization_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_entry_fee_amortization_analyzer import (
    DeFiProtocolVaultEntryFeeAmortizationAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DEFAULT_HOLDING_HORIZON_DAYS,
    NEGLIGIBLE_FRACTION,
    MILD_FRACTION,
    MODERATE_FRACTION,
    HIGH_DEPOSIT_FEE,
    SHORT_HORIZON_DAYS,
    DAYS_PER_YEAR,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=20.0,
    deposit_fee_pct=0.2,
    exit_fee_pct=0.2,
    holding_horizon_days=90.0,
):
    return {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "deposit_fee_pct": deposit_fee_pct,
        "exit_fee_pct": exit_fee_pct,
        "holding_horizon_days": holding_horizon_days,
    }


def A():
    return DeFiProtocolVaultEntryFeeAmortizationAnalyzer()


def finite_check(testcase, result):
    for v in result.values():
        if isinstance(v, float):
            testcase.assertTrue(math.isfinite(v), f"non-finite: {v}")


# ── helper-function tests ─────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    def test_f_valid(self):
        self.assertEqual(_f("3.5"), 3.5)
        self.assertEqual(_f(7), 7.0)

    def test_f_none_default(self):
        self.assertEqual(_f(None), 0.0)
        self.assertEqual(_f(None, 9.0), 9.0)

    def test_f_bad_value(self):
        self.assertEqual(_f("abc"), 0.0)
        self.assertEqual(_f([], 1.0), 1.0)

    def test_f_negative(self):
        self.assertEqual(_f("-5"), -5.0)

    def test_f_int_zero(self):
        self.assertEqual(_f(0), 0.0)

    def test_f_dict_default(self):
        self.assertEqual(_f({}, 2.0), 2.0)

    def test_f_float_passthrough(self):
        self.assertEqual(_f(4.25), 4.25)

    def test_f_string_number(self):
        self.assertEqual(_f("30"), 30.0)

    def test_f_bool_true(self):
        self.assertEqual(_f(True), 1.0)

    def test_f_inf_passthrough(self):
        self.assertTrue(math.isinf(_f(float("inf"))))

    def test_clamp_within(self):
        self.assertEqual(_clamp(5, 0, 10), 5)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1, 0, 10), 0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(11, 0, 10), 10)

    def test_clamp_exact_bounds(self):
        self.assertEqual(_clamp(0, 0, 10), 0)
        self.assertEqual(_clamp(10, 0, 10), 10)

    def test_clamp_unit_interval(self):
        self.assertEqual(_clamp(1.5, 0.0, 1.0), 1.0)
        self.assertEqual(_clamp(-0.2, 0.0, 1.0), 0.0)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertEqual(_mean([2.0, 4.0]), 3.0)

    def test_mean_single(self):
        self.assertEqual(_mean([9.0]), 9.0)

    def test_mean_negatives(self):
        self.assertEqual(_mean([-2.0, 2.0]), 0.0)

    def test_safe_div_normal(self):
        self.assertEqual(_safe_div(10.0, 2.0, None), 5.0)

    def test_safe_div_zero_den(self):
        self.assertIsNone(_safe_div(10.0, 0.0, None))

    def test_safe_div_neg_den(self):
        self.assertEqual(_safe_div(10.0, -1.0, 0.0), 0.0)

    def test_safe_div_sentinel_value(self):
        self.assertEqual(_safe_div(1.0, 0.0, -1.0), -1.0)

    def test_build_default_cfg_keys(self):
        cfg = _build_default_cfg()
        self.assertIn("log_path", cfg)
        self.assertIn("log_cap", cfg)

    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg["log_cap"], 5)

    def test_build_default_cfg_extra(self):
        cfg = _build_default_cfg({"x": 1})
        self.assertEqual(cfg["x"], 1)

    def test_build_default_cfg_default_cap(self):
        self.assertEqual(_build_default_cfg()["log_cap"], LOG_CAP)

    def test_build_default_cfg_none(self):
        cfg = _build_default_cfg(None)
        self.assertEqual(cfg["log_path"], LOG_PATH)

    def test_grade_a(self):
        self.assertEqual(_grade_from_score(90), "A")

    def test_grade_b(self):
        self.assertEqual(_grade_from_score(72), "B")

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

    def test_grade_boundary_55(self):
        self.assertEqual(_grade_from_score(55), "C")

    def test_grade_boundary_40(self):
        self.assertEqual(_grade_from_score(40), "D")

    def test_grade_just_below_85(self):
        self.assertEqual(_grade_from_score(84.99), "B")

    def test_grade_just_below_40(self):
        self.assertEqual(_grade_from_score(39.99), "F")

    def test_grade_zero(self):
        self.assertEqual(_grade_from_score(0), "F")

    def test_grade_hundred(self):
        self.assertEqual(_grade_from_score(100), "A")


# ── constants ─────────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_default_horizon(self):
        self.assertEqual(DEFAULT_HOLDING_HORIZON_DAYS, 30.0)

    def test_fraction_ordering(self):
        self.assertGreater(NEGLIGIBLE_FRACTION, MILD_FRACTION)
        self.assertGreater(MILD_FRACTION, MODERATE_FRACTION)

    def test_fractions_in_unit(self):
        for v in (NEGLIGIBLE_FRACTION, MILD_FRACTION, MODERATE_FRACTION):
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

    def test_negligible_value(self):
        self.assertEqual(NEGLIGIBLE_FRACTION, 0.90)

    def test_mild_value(self):
        self.assertEqual(MILD_FRACTION, 0.75)

    def test_moderate_value(self):
        self.assertEqual(MODERATE_FRACTION, 0.55)

    def test_high_deposit_fee(self):
        self.assertEqual(HIGH_DEPOSIT_FEE, 1.0)

    def test_short_horizon_days(self):
        self.assertEqual(SHORT_HORIZON_DAYS, 14.0)

    def test_days_per_year(self):
        self.assertEqual(DAYS_PER_YEAR, 365.0)

    def test_log_cap_value(self):
        self.assertEqual(LOG_CAP, 100)

    def test_log_path_str(self):
        self.assertIsInstance(LOG_PATH, str)
        self.assertIn("vault_entry_fee_amortization_log.json", LOG_PATH)


# ── structure ─────────────────────────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_token(self):
        self.assertIn("token", self.r)

    def test_has_headline(self):
        self.assertIn("headline_apr_pct", self.r)

    def test_has_deposit_fee(self):
        self.assertIn("deposit_fee_pct", self.r)

    def test_has_exit_fee(self):
        self.assertIn("exit_fee_pct", self.r)

    def test_has_round_trip_fee(self):
        self.assertIn("round_trip_fee_pct", self.r)

    def test_has_horizon(self):
        self.assertIn("holding_horizon_days", self.r)

    def test_has_annualized_fee_drag(self):
        self.assertIn("annualized_fee_drag_pct", self.r)

    def test_has_net_apr(self):
        self.assertIn("net_apr_pct", self.r)

    def test_has_retained_fraction(self):
        self.assertIn("retained_fraction", self.r)

    def test_has_fee_drag_fraction(self):
        self.assertIn("fee_drag_fraction", self.r)

    def test_has_breakeven_horizon_days(self):
        self.assertIn("breakeven_horizon_days", self.r)

    def test_has_breakeven_beyond_horizon(self):
        self.assertIn("breakeven_beyond_horizon", self.r)

    def test_has_score(self):
        self.assertIn("score", self.r)

    def test_has_classification(self):
        self.assertIn("classification", self.r)

    def test_has_recommendation(self):
        self.assertIn("recommendation", self.r)

    def test_has_grade(self):
        self.assertIn("grade", self.r)

    def test_has_flags(self):
        self.assertIn("flags", self.r)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_value(self):
        self.assertEqual(self.r["token"], "USDC-Vault")

    def test_token_fallback(self):
        r = A().analyze({"token": "TKN", "headline_apr_pct": 10.0})
        self.assertEqual(r["token"], "TKN")

    def test_token_unknown(self):
        r = A().analyze({"headline_apr_pct": 10.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_score_range(self):
        self.assertGreaterEqual(self.r["score"], 0.0)
        self.assertLessEqual(self.r["score"], 100.0)

    def test_finite(self):
        finite_check(self, self.r)

    def test_all_keys_present(self):
        expected = {
            "token", "headline_apr_pct", "deposit_fee_pct", "exit_fee_pct",
            "round_trip_fee_pct", "holding_horizon_days",
            "annualized_fee_drag_pct", "net_apr_pct", "retained_fraction",
            "fee_drag_fraction", "breakeven_horizon_days",
            "breakeven_beyond_horizon", "score", "classification",
            "recommendation", "grade", "flags",
        }
        self.assertEqual(set(self.r.keys()), expected)


# ── metrics ───────────────────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_round_trip_fee(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.3, exit_fee_pct=0.2))
        self.assertAlmostEqual(r["round_trip_fee_pct"], 0.5, places=4)

    def test_round_trip_fee_only_deposit(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.5, exit_fee_pct=0.0))
        self.assertAlmostEqual(r["round_trip_fee_pct"], 0.5, places=4)

    def test_deposit_fee_clamped_low(self):
        r = A().analyze(make_pos(deposit_fee_pct=-1.0))
        self.assertEqual(r["deposit_fee_pct"], 0.0)

    def test_exit_fee_clamped_low(self):
        r = A().analyze(make_pos(exit_fee_pct=-2.0))
        self.assertEqual(r["exit_fee_pct"], 0.0)

    def test_annualized_drag_30d(self):
        # fee 1.0 over 30d → 1.0*365/30 = 12.1667
        r = A().analyze(make_pos(headline_apr_pct=50.0, deposit_fee_pct=0.5,
                                 exit_fee_pct=0.5, holding_horizon_days=30.0))
        self.assertAlmostEqual(r["annualized_fee_drag_pct"],
                               1.0 * 365.0 / 30.0, places=4)

    def test_annualized_drag_365d(self):
        # fee 0.5 over 365d → 0.5
        r = A().analyze(make_pos(headline_apr_pct=50.0, deposit_fee_pct=0.5,
                                 exit_fee_pct=0.0, holding_horizon_days=365.0))
        self.assertAlmostEqual(r["annualized_fee_drag_pct"], 0.5, places=4)

    def test_drag_scales_with_horizon(self):
        short = A().analyze(make_pos(headline_apr_pct=50.0, deposit_fee_pct=0.5,
                                     exit_fee_pct=0.0,
                                     holding_horizon_days=30.0))
        long = A().analyze(make_pos(headline_apr_pct=50.0, deposit_fee_pct=0.5,
                                    exit_fee_pct=0.0,
                                    holding_horizon_days=365.0))
        self.assertGreater(short["annualized_fee_drag_pct"],
                           long["annualized_fee_drag_pct"])

    def test_net_apr_positive(self):
        # headline 20, fee 0.5 over 365 → drag 0.5, net 19.5
        r = A().analyze(make_pos(headline_apr_pct=20.0, deposit_fee_pct=0.5,
                                 exit_fee_pct=0.0, holding_horizon_days=365.0))
        self.assertAlmostEqual(r["net_apr_pct"], 19.5, places=4)

    def test_net_apr_negative(self):
        # headline 5, fee 2.0 over 30 → drag 24.33, net -19.33
        r = A().analyze(make_pos(headline_apr_pct=5.0, deposit_fee_pct=1.0,
                                 exit_fee_pct=1.0, holding_horizon_days=30.0))
        self.assertLess(r["net_apr_pct"], 0.0)

    def test_net_apr_not_clamped_to_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=5.0, deposit_fee_pct=1.0,
                                 exit_fee_pct=1.0, holding_horizon_days=30.0))
        self.assertLess(r["net_apr_pct"], 0.0)
        self.assertAlmostEqual(r["net_apr_pct"],
                               5.0 - 2.0 * 365.0 / 30.0, places=4)

    def test_retained_fraction_full(self):
        # tiny fee, long horizon → retained ~1
        r = A().analyze(make_pos(headline_apr_pct=20.0, deposit_fee_pct=0.001,
                                 exit_fee_pct=0.0, holding_horizon_days=365.0))
        self.assertGreaterEqual(r["retained_fraction"], 0.99)

    def test_retained_fraction_zero_when_net_negative(self):
        r = A().analyze(make_pos(headline_apr_pct=5.0, deposit_fee_pct=1.0,
                                 exit_fee_pct=1.0, holding_horizon_days=30.0))
        self.assertEqual(r["retained_fraction"], 0.0)

    def test_retained_fraction_half(self):
        # headline 20, drag 10 → net 10, retained 0.5
        # fee F over 30 = 10 → F = 10*30/365 = 0.82192
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 deposit_fee_pct=0.82192, exit_fee_pct=0.0,
                                 holding_horizon_days=30.0))
        self.assertAlmostEqual(r["retained_fraction"], 0.5, places=2)

    def test_fee_drag_fraction_complement(self):
        # when net >= 0: fee_drag_fraction == 1 - retained
        r = A().analyze(make_pos(headline_apr_pct=20.0, deposit_fee_pct=0.2,
                                 exit_fee_pct=0.2, holding_horizon_days=90.0))
        self.assertAlmostEqual(
            r["fee_drag_fraction"], 1.0 - r["retained_fraction"], places=4)

    def test_fee_drag_fraction_capped(self):
        r = A().analyze(make_pos(headline_apr_pct=5.0, deposit_fee_pct=1.0,
                                 exit_fee_pct=1.0, holding_horizon_days=30.0))
        self.assertEqual(r["fee_drag_fraction"], 1.0)

    def test_breakeven_horizon_math(self):
        # fee 1.0, headline 20 → breakeven = 1.0*365/20 = 18.25
        r = A().analyze(make_pos(headline_apr_pct=20.0, deposit_fee_pct=0.5,
                                 exit_fee_pct=0.5, holding_horizon_days=30.0))
        self.assertAlmostEqual(r["breakeven_horizon_days"], 18.25, places=4)

    def test_breakeven_zero_when_no_fee(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, exit_fee_pct=0.0))
        self.assertEqual(r["breakeven_horizon_days"], 0.0)

    def test_breakeven_beyond_horizon_true(self):
        # fee 1.0, headline 5 → breakeven 73d, horizon 30 → beyond
        r = A().analyze(make_pos(headline_apr_pct=5.0, deposit_fee_pct=0.5,
                                 exit_fee_pct=0.5, holding_horizon_days=30.0))
        self.assertTrue(r["breakeven_beyond_horizon"])

    def test_breakeven_beyond_horizon_false(self):
        # breakeven 18.25, horizon 90 → not beyond
        r = A().analyze(make_pos(headline_apr_pct=20.0, deposit_fee_pct=0.5,
                                 exit_fee_pct=0.5, holding_horizon_days=90.0))
        self.assertFalse(r["breakeven_beyond_horizon"])

    def test_breakeven_beyond_false_when_no_fee(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, exit_fee_pct=0.0))
        self.assertFalse(r["breakeven_beyond_horizon"])

    def test_horizon_default_applied(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "deposit_fee_pct": 0.2, "exit_fee_pct": 0.2})
        self.assertEqual(r["holding_horizon_days"],
                         DEFAULT_HOLDING_HORIZON_DAYS)

    def test_horizon_default_when_zero(self):
        r = A().analyze(make_pos(holding_horizon_days=0.0))
        self.assertEqual(r["holding_horizon_days"],
                         DEFAULT_HOLDING_HORIZON_DAYS)

    def test_horizon_default_when_negative(self):
        r = A().analyze(make_pos(holding_horizon_days=-5.0))
        self.assertEqual(r["holding_horizon_days"],
                         DEFAULT_HOLDING_HORIZON_DAYS)

    def test_zero_fee_negligible(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, exit_fee_pct=0.0))
        self.assertEqual(r["classification"], "NEGLIGIBLE")
        self.assertEqual(r["score"], 100.0)
        self.assertEqual(r["breakeven_horizon_days"], 0.0)
        self.assertEqual(r["retained_fraction"], 1.0)

    def test_finite_all_metrics(self):
        r = A().analyze(make_pos())
        finite_check(self, r)


# ── classification ────────────────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_negligible(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, deposit_fee_pct=0.1,
                                 exit_fee_pct=0.0, holding_horizon_days=365.0))
        self.assertEqual(r["classification"], "NEGLIGIBLE")

    def test_mild(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, deposit_fee_pct=0.2,
                                 exit_fee_pct=0.0, holding_horizon_days=30.0))
        self.assertEqual(r["classification"], "MILD")

    def test_moderate(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, deposit_fee_pct=0.25,
                                 exit_fee_pct=0.2, holding_horizon_days=30.0))
        self.assertEqual(r["classification"], "MODERATE")

    def test_heavy(self):
        r = A().analyze(make_pos(headline_apr_pct=18.0, deposit_fee_pct=0.5,
                                 exit_fee_pct=0.5, holding_horizon_days=30.0))
        self.assertEqual(r["classification"], "HEAVY")

    def test_fee_trap(self):
        r = A().analyze(make_pos(headline_apr_pct=5.0, deposit_fee_pct=1.0,
                                 exit_fee_pct=1.0, holding_horizon_days=30.0))
        self.assertEqual(r["classification"], "FEE_TRAP")

    def test_classify_boundary_negligible(self):
        c = A()._classify(NEGLIGIBLE_FRACTION, 10.0)
        self.assertEqual(c, "NEGLIGIBLE")

    def test_classify_boundary_mild(self):
        c = A()._classify(MILD_FRACTION, 10.0)
        self.assertEqual(c, "MILD")

    def test_classify_boundary_moderate(self):
        c = A()._classify(MODERATE_FRACTION, 10.0)
        self.assertEqual(c, "MODERATE")

    def test_classify_below_moderate_heavy(self):
        c = A()._classify(MODERATE_FRACTION - 0.01, 5.0)
        self.assertEqual(c, "HEAVY")

    def test_classify_just_below_negligible(self):
        c = A()._classify(NEGLIGIBLE_FRACTION - 0.001, 10.0)
        self.assertEqual(c, "MILD")

    def test_classify_just_below_mild(self):
        c = A()._classify(MILD_FRACTION - 0.001, 10.0)
        self.assertEqual(c, "MODERATE")

    def test_classify_net_negative_overrides(self):
        # even with high retained input, net<=0 → FEE_TRAP
        c = A()._classify(0.95, -1.0)
        self.assertEqual(c, "FEE_TRAP")

    def test_classify_net_zero_fee_trap(self):
        c = A()._classify(0.0, 0.0)
        self.assertEqual(c, "FEE_TRAP")

    def test_classify_one(self):
        self.assertEqual(A()._classify(1.0, 10.0), "NEGLIGIBLE")

    def test_classify_clamps_above_one(self):
        self.assertEqual(A()._classify(5.0, 10.0), "NEGLIGIBLE")

    def test_net_negative_is_fee_trap_via_analyze(self):
        r = A().analyze(make_pos(headline_apr_pct=3.0, deposit_fee_pct=0.5,
                                 exit_fee_pct=0.5, holding_horizon_days=20.0))
        self.assertEqual(r["classification"], "FEE_TRAP")


# ── recommendation ────────────────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_insufficient(self):
        self.assertEqual(A()._recommend("INSUFFICIENT_DATA"), "VERIFY_DATA")

    def test_negligible(self):
        self.assertEqual(A()._recommend("NEGLIGIBLE"), "NO_ACTION")

    def test_mild(self):
        self.assertEqual(A()._recommend("MILD"), "MONITOR")

    def test_moderate(self):
        self.assertEqual(A()._recommend("MODERATE"), "EXTEND_HORIZON")

    def test_heavy(self):
        self.assertEqual(A()._recommend("HEAVY"), "EXTEND_HORIZON_OR_AVOID")

    def test_fee_trap(self):
        self.assertEqual(A()._recommend("FEE_TRAP"), "AVOID")

    def test_negligible_via_analyze(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, exit_fee_pct=0.0))
        self.assertEqual(r["recommendation"], "NO_ACTION")

    def test_fee_trap_via_analyze(self):
        r = A().analyze(make_pos(headline_apr_pct=5.0, deposit_fee_pct=1.0,
                                 exit_fee_pct=1.0, holding_horizon_days=30.0))
        self.assertEqual(r["recommendation"], "AVOID")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_negligible_flag(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, exit_fee_pct=0.0))
        self.assertIn("NEGLIGIBLE", r["flags"])

    def test_mild_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, deposit_fee_pct=0.2,
                                 exit_fee_pct=0.0, holding_horizon_days=30.0))
        self.assertIn("MILD", r["flags"])

    def test_moderate_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, deposit_fee_pct=0.25,
                                 exit_fee_pct=0.2, holding_horizon_days=30.0))
        self.assertIn("MODERATE", r["flags"])

    def test_heavy_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=18.0, deposit_fee_pct=0.5,
                                 exit_fee_pct=0.5, holding_horizon_days=30.0))
        self.assertIn("HEAVY", r["flags"])

    def test_fee_trap_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=5.0, deposit_fee_pct=1.0,
                                 exit_fee_pct=1.0, holding_horizon_days=30.0))
        self.assertIn("FEE_TRAP", r["flags"])

    def test_breakeven_beyond_horizon_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=5.0, deposit_fee_pct=0.5,
                                 exit_fee_pct=0.5, holding_horizon_days=30.0))
        self.assertIn("BREAKEVEN_BEYOND_HORIZON", r["flags"])

    def test_no_breakeven_beyond_when_long_horizon(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, deposit_fee_pct=0.1,
                                 exit_fee_pct=0.0, holding_horizon_days=365.0))
        self.assertNotIn("BREAKEVEN_BEYOND_HORIZON", r["flags"])

    def test_high_deposit_fee_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=50.0, deposit_fee_pct=1.5,
                                 exit_fee_pct=0.0, holding_horizon_days=365.0))
        self.assertIn("HIGH_DEPOSIT_FEE", r["flags"])

    def test_high_deposit_fee_boundary(self):
        r = A().analyze(make_pos(headline_apr_pct=50.0, deposit_fee_pct=1.0,
                                 exit_fee_pct=0.0, holding_horizon_days=365.0))
        self.assertIn("HIGH_DEPOSIT_FEE", r["flags"])

    def test_no_high_deposit_fee_flag(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.5, exit_fee_pct=0.5))
        self.assertNotIn("HIGH_DEPOSIT_FEE", r["flags"])

    def test_short_horizon_penalty_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=50.0, deposit_fee_pct=0.2,
                                 exit_fee_pct=0.0, holding_horizon_days=10.0))
        self.assertIn("SHORT_HORIZON_PENALTY", r["flags"])

    def test_short_horizon_boundary(self):
        r = A().analyze(make_pos(headline_apr_pct=50.0, deposit_fee_pct=0.2,
                                 exit_fee_pct=0.0, holding_horizon_days=14.0))
        self.assertIn("SHORT_HORIZON_PENALTY", r["flags"])

    def test_no_short_horizon_penalty_when_no_fee(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, exit_fee_pct=0.0,
                                 holding_horizon_days=10.0))
        self.assertNotIn("SHORT_HORIZON_PENALTY", r["flags"])

    def test_no_short_horizon_penalty_when_long(self):
        r = A().analyze(make_pos(holding_horizon_days=90.0))
        self.assertNotIn("SHORT_HORIZON_PENALTY", r["flags"])

    def test_net_negative_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=5.0, deposit_fee_pct=1.0,
                                 exit_fee_pct=1.0, holding_horizon_days=30.0))
        self.assertIn("NET_NEGATIVE", r["flags"])

    def test_no_net_negative_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, deposit_fee_pct=0.1,
                                 exit_fee_pct=0.0, holding_horizon_days=365.0))
        self.assertNotIn("NET_NEGATIVE", r["flags"])

    def test_flags_no_duplicates(self):
        r = A().analyze(make_pos())
        self.assertEqual(len(r["flags"]), len(set(r["flags"])))

    def test_insufficient_flag(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 0.0})
        self.assertIn("INSUFFICIENT_DATA", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_zero_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_none_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": None})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("nan")})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("inf")})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_headline(self):
        r = A().analyze({"vault": "X"})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_score_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["score"], 0.0)

    def test_grade_f(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["grade"], "F")

    def test_sentinels_null(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertIsNone(r["annualized_fee_drag_pct"])
        self.assertIsNone(r["net_apr_pct"])
        self.assertIsNone(r["retained_fraction"])
        self.assertIsNone(r["fee_drag_fraction"])
        self.assertIsNone(r["breakeven_horizon_days"])

    def test_breakeven_beyond_false(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertFalse(r["breakeven_beyond_horizon"])

    def test_recommendation(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_token_preserved(self):
        r = A().analyze(make_pos(vault="ZZZ", headline_apr_pct=0.0))
        self.assertEqual(r["token"], "ZZZ")

    def test_horizon_default_in_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["holding_horizon_days"],
                         DEFAULT_HOLDING_HORIZON_DAYS)

    def test_json_serializable(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        json.dumps(r)


# ── scoring ───────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_score_full_retention(self):
        self.assertAlmostEqual(A()._score(1.0), 100.0, places=4)

    def test_score_zero(self):
        self.assertAlmostEqual(A()._score(0.0), 0.0, places=4)

    def test_score_half(self):
        self.assertAlmostEqual(A()._score(0.5), 50.0, places=4)

    def test_score_monotonic(self):
        prev = -1.0
        for f in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
            s = A()._score(f)
            self.assertGreaterEqual(s, prev)
            prev = s

    def test_score_clamps_above(self):
        self.assertLessEqual(A()._score(2.0), 100.0)

    def test_score_clamps_below(self):
        self.assertGreaterEqual(A()._score(-1.0), 0.0)

    def test_score_in_range_random(self):
        for f in (0.05, 0.33, 0.71, 0.99):
            s = A()._score(f)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)

    def test_score_idempotent(self):
        p = make_pos()
        s1 = A().analyze(p)["score"]
        s2 = A().analyze(p)["score"]
        self.assertEqual(s1, s2)

    def test_score_finite(self):
        for f in (0.0, 0.5, 1.0):
            self.assertTrue(math.isfinite(A()._score(f)))

    def test_negligible_higher_than_trap(self):
        neg = A().analyze(make_pos(deposit_fee_pct=0.0, exit_fee_pct=0.0,
                                   holding_horizon_days=365.0))["score"]
        trap = A().analyze(make_pos(headline_apr_pct=5.0, deposit_fee_pct=1.0,
                                    exit_fee_pct=1.0,
                                    holding_horizon_days=30.0))["score"]
        self.assertGreater(neg, trap)

    def test_score_matches_retained(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0, deposit_fee_pct=0.2,
                                 exit_fee_pct=0.2, holding_horizon_days=90.0))
        self.assertAlmostEqual(
            r["score"], 100.0 * r["retained_fraction"], places=1)

    def test_grade_matches_score(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, exit_fee_pct=0.0))
        self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_score_monotonic_with_horizon(self):
        # longer horizon → less drag → higher score
        short = A().analyze(make_pos(headline_apr_pct=20.0, deposit_fee_pct=0.5,
                                     exit_fee_pct=0.0,
                                     holding_horizon_days=30.0))["score"]
        long = A().analyze(make_pos(headline_apr_pct=20.0, deposit_fee_pct=0.5,
                                    exit_fee_pct=0.0,
                                    holding_horizon_days=365.0))["score"]
        self.assertGreater(long, short)


# ── portfolio / aggregate ─────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def test_positions_key(self):
        res = A().analyze_portfolio([make_pos()])
        self.assertIn("positions", res)

    def test_aggregate_key(self):
        res = A().analyze_portfolio([make_pos()])
        self.assertIn("aggregate", res)

    def test_position_count(self):
        res = A().analyze_portfolio([make_pos(), make_pos()])
        self.assertEqual(res["aggregate"]["position_count"], 2)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)
        self.assertIsNone(res["aggregate"]["lowest_fee_drag_vault"])
        self.assertIsNone(res["aggregate"]["highest_fee_drag_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["fee_trap_count"], 0)
        self.assertEqual(res["aggregate"]["avg_net_apr_pct"], 0.0)

    def test_all_insufficient(self):
        res = A().analyze_portfolio([make_pos(headline_apr_pct=0.0)])
        self.assertIsNone(res["aggregate"]["lowest_fee_drag_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)

    def test_lowest_fee_drag_identified(self):
        res = A().analyze_portfolio([
            make_pos(vault="GOOD", deposit_fee_pct=0.0, exit_fee_pct=0.0,
                     holding_horizon_days=365.0),
            make_pos(vault="BAD", headline_apr_pct=5.0, deposit_fee_pct=1.0,
                     exit_fee_pct=1.0, holding_horizon_days=30.0),
        ])
        self.assertEqual(res["aggregate"]["lowest_fee_drag_vault"], "GOOD")

    def test_highest_fee_drag_identified(self):
        res = A().analyze_portfolio([
            make_pos(vault="GOOD", deposit_fee_pct=0.0, exit_fee_pct=0.0,
                     holding_horizon_days=365.0),
            make_pos(vault="BAD", headline_apr_pct=5.0, deposit_fee_pct=1.0,
                     exit_fee_pct=1.0, holding_horizon_days=30.0),
        ])
        self.assertEqual(res["aggregate"]["highest_fee_drag_vault"], "BAD")

    def test_avg_score(self):
        res = A().analyze_portfolio([
            make_pos(deposit_fee_pct=0.0, exit_fee_pct=0.0),
            make_pos(deposit_fee_pct=0.0, exit_fee_pct=0.0),
        ])
        self.assertAlmostEqual(res["aggregate"]["avg_score"], 100.0, places=2)

    def test_fee_trap_count(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=5.0, deposit_fee_pct=1.0,
                     exit_fee_pct=1.0, holding_horizon_days=30.0),
            make_pos(headline_apr_pct=5.0, deposit_fee_pct=1.0,
                     exit_fee_pct=1.0, holding_horizon_days=30.0),
            make_pos(deposit_fee_pct=0.0, exit_fee_pct=0.0),
        ])
        self.assertEqual(res["aggregate"]["fee_trap_count"], 2)

    def test_avg_net_apr(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=20.0, deposit_fee_pct=0.0,
                     exit_fee_pct=0.0, holding_horizon_days=365.0),
        ])
        self.assertAlmostEqual(res["aggregate"]["avg_net_apr_pct"], 20.0,
                               places=2)

    def test_aggregate_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for v in res["aggregate"].values():
            if isinstance(v, float):
                self.assertTrue(math.isfinite(v))

    def test_mixed_with_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="LIVE", deposit_fee_pct=0.0, exit_fee_pct=0.0),
            make_pos(headline_apr_pct=0.0),
        ])
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["lowest_fee_drag_vault"], "LIVE")


# ── logging ───────────────────────────────────────────────────────────────────

class TestLogging(unittest.TestCase):
    def _cfg(self, path):
        return {"log_path": path, "log_cap": LOG_CAP}

    def test_write_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg=self._cfg(p), write_log=True)
            self.assertTrue(os.path.exists(p))

    def test_write_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg=self._cfg(p), write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_no_write_when_flag_false(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg=self._cfg(p), write_log=False)
            self.assertFalse(os.path.exists(p))

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            cfg = {"log_path": p, "log_cap": 3}
            for _ in range(10):
                A().analyze(make_pos(), cfg=cfg, write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_ring_buffer_cap_over_100(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            cfg = {"log_path": p, "log_cap": LOG_CAP}
            for _ in range(LOG_CAP + 20):
                A().analyze(make_pos(), cfg=cfg, write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), LOG_CAP)

    def test_log_entry_fields(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            A().analyze_portfolio([make_pos()], cfg=self._cfg(p),
                                  write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            entry = data[0]
            self.assertIn("ts", entry)
            self.assertIn("position_count", entry)
            self.assertIn("aggregate", entry)
            self.assertIn("snapshots", entry)

    def test_atomic_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg=self._cfg(p), write_log=True)
            self.assertFalse(os.path.exists(p + ".tmp"))

    def test_corrupt_log_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            with open(p, "w") as fh:
                fh.write("not json{{")
            A().analyze(make_pos(), cfg=self._cfg(p), write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_non_list_log_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            with open(p, "w") as fh:
                json.dump({"x": 1}, fh)
            A().analyze(make_pos(), cfg=self._cfg(p), write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_appends(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg=self._cfg(p), write_log=True)
            A().analyze(make_pos(), cfg=self._cfg(p), write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 2)

    def test_snapshot_content(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            A().analyze_portfolio([make_pos(vault="SNAP")],
                                  cfg=self._cfg(p), write_log=True)
            with open(p) as fh:
                data = json.load(fh)
            snap = data[0]["snapshots"][0]
            self.assertEqual(snap["token"], "SNAP")
            self.assertIn("classification", snap)
            self.assertIn("score", snap)
            self.assertIn("recommendation", snap)
            self.assertIn("flags", snap)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_no_nan_in_output(self):
        for p in _demo_positions():
            r = A().analyze(p)
            finite_check(self, r)

    def test_string_inputs(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": "20",
                         "deposit_fee_pct": "0.2", "exit_fee_pct": "0.2",
                         "holding_horizon_days": "90"})
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_extreme_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=1e9, deposit_fee_pct=1.0,
                                 exit_fee_pct=1.0, holding_horizon_days=30.0))
        finite_check(self, r)

    def test_huge_horizon(self):
        r = A().analyze(make_pos(holding_horizon_days=1e9))
        finite_check(self, r)
        self.assertGreaterEqual(r["retained_fraction"], 0.0)
        self.assertLessEqual(r["retained_fraction"], 1.0)

    def test_tiny_horizon(self):
        r = A().analyze(make_pos(headline_apr_pct=50.0, deposit_fee_pct=0.5,
                                 exit_fee_pct=0.0,
                                 holding_horizon_days=0.001))
        finite_check(self, r)

    def test_inf_deposit_fee(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "deposit_fee_pct": float("inf"),
                         "exit_fee_pct": 0.0,
                         "holding_horizon_days": 30.0})
        finite_check(self, r)

    def test_inf_exit_fee(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "deposit_fee_pct": 0.0,
                         "exit_fee_pct": float("inf"),
                         "holding_horizon_days": 30.0})
        finite_check(self, r)

    def test_nan_deposit_fee(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "deposit_fee_pct": float("nan"),
                         "exit_fee_pct": 0.2,
                         "holding_horizon_days": 30.0})
        finite_check(self, r)

    def test_inf_horizon(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "deposit_fee_pct": 0.2, "exit_fee_pct": 0.2,
                         "holding_horizon_days": float("inf")})
        self.assertEqual(r["holding_horizon_days"],
                         DEFAULT_HOLDING_HORIZON_DAYS)

    def test_nan_horizon(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "deposit_fee_pct": 0.2, "exit_fee_pct": 0.2,
                         "holding_horizon_days": float("nan")})
        self.assertEqual(r["holding_horizon_days"],
                         DEFAULT_HOLDING_HORIZON_DAYS)

    def test_none_horizon(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "deposit_fee_pct": 0.2, "exit_fee_pct": 0.2,
                         "holding_horizon_days": None})
        self.assertEqual(r["holding_horizon_days"],
                         DEFAULT_HOLDING_HORIZON_DAYS)

    def test_none_fees(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 20.0,
                         "deposit_fee_pct": None, "exit_fee_pct": None,
                         "holding_horizon_days": 90.0})
        self.assertEqual(r["round_trip_fee_pct"], 0.0)
        self.assertEqual(r["classification"], "NEGLIGIBLE")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_idempotent_full(self):
        p = make_pos()
        self.assertEqual(A().analyze(p), A().analyze(p))

    def test_determinism_portfolio(self):
        ps = _demo_positions()
        self.assertEqual(
            A().analyze_portfolio(ps)["positions"],
            A().analyze_portfolio(ps)["positions"])

    def test_all_outputs_json(self):
        for p in _demo_positions():
            json.dumps(A().analyze(p))

    def test_retained_fraction_bounded(self):
        for p in _demo_positions():
            r = A().analyze(p)
            if r["retained_fraction"] is not None:
                self.assertGreaterEqual(r["retained_fraction"], 0.0)
                self.assertLessEqual(r["retained_fraction"], 1.0)

    def test_fee_drag_fraction_bounded(self):
        for p in _demo_positions():
            r = A().analyze(p)
            if r["fee_drag_fraction"] is not None:
                self.assertGreaterEqual(r["fee_drag_fraction"], 0.0)
                self.assertLessEqual(r["fee_drag_fraction"], 1.0)


# ── CLI / demo ────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_demo_count(self):
        self.assertEqual(len(_demo_positions()), 6)

    def test_demo_runs(self):
        res = A().analyze_portfolio(_demo_positions())
        self.assertEqual(len(res["positions"]), 6)

    def test_demo_has_insufficient(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("NEGLIGIBLE", "MILD", "MODERATE", "HEAVY", "FEE_TRAP",
                  "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_includes_no_action_and_avoid(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("NO_ACTION", recs)
        self.assertIn("AVOID", recs)

    def test_demo_includes_high_deposit_fee(self):
        res = A().analyze_portfolio(_demo_positions())
        hit = any("HIGH_DEPOSIT_FEE" in p["flags"]
                  for p in res["positions"])
        self.assertTrue(hit)

    def test_demo_includes_net_negative(self):
        res = A().analyze_portfolio(_demo_positions())
        hit = any("NET_NEGATIVE" in p["flags"] for p in res["positions"])
        self.assertTrue(hit)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)

    def test_demo_avg_score_in_range(self):
        res = A().analyze_portfolio(_demo_positions())
        self.assertGreaterEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertLessEqual(res["aggregate"]["avg_score"], 100.0)

    def test_demo_fee_trap_count(self):
        res = A().analyze_portfolio(_demo_positions())
        self.assertGreaterEqual(res["aggregate"]["fee_trap_count"], 1)


if __name__ == "__main__":
    unittest.main()
