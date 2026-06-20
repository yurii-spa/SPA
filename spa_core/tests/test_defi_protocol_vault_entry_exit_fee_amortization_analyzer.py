"""
Tests for MP-1205: DeFiProtocolVaultEntryExitFeeAmortizationAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_entry_exit_fee_amortization_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_entry_exit_fee_amortization_analyzer import (  # noqa: E501
    DeFiProtocolVaultEntryExitFeeAmortizationAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _coerce_num,
    _coerce_fee,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DEFAULT_HOLDING_DAYS,
    DAYS_PER_YEAR,
    CLEAN_FRACTION,
    MILD_FRACTION,
    MODERATE_FRACTION,
    SHORT_HOLD_DAYS,
    HIGH_ROUND_TRIP_FEE_PCT,
    EPS,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    headline_apr_pct=None,
    entry_fee_pct=None,
    exit_fee_pct=None,
    round_trip_fee_pct=None,
    holding_days=None,
    amortized_fee_drag_apr_pct=None,
):
    pos = {"vault": vault}
    if headline_apr_pct is not None:
        pos["headline_apr_pct"] = headline_apr_pct
    if entry_fee_pct is not None:
        pos["entry_fee_pct"] = entry_fee_pct
    if exit_fee_pct is not None:
        pos["exit_fee_pct"] = exit_fee_pct
    if round_trip_fee_pct is not None:
        pos["round_trip_fee_pct"] = round_trip_fee_pct
    if holding_days is not None:
        pos["holding_days"] = holding_days
    if amortized_fee_drag_apr_pct is not None:
        pos["amortized_fee_drag_apr_pct"] = amortized_fee_drag_apr_pct
    return pos


def A():
    return DeFiProtocolVaultEntryExitFeeAmortizationAnalyzer()


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

    def test_f_negative_float(self):
        self.assertEqual(_f(-3.7), -3.7)

    def test_f_int(self):
        self.assertEqual(_f(5), 5.0)

    def test_f_zero(self):
        self.assertEqual(_f(0), 0.0)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1.0, 0.0, 1.0), 0.0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(2.0, 0.0, 1.0), 1.0)

    def test_clamp_mid(self):
        self.assertEqual(_clamp(0.5, 0.0, 1.0), 0.5)

    def test_clamp_exact_lo(self):
        self.assertEqual(_clamp(0.0, 0.0, 1.0), 0.0)

    def test_clamp_exact_hi(self):
        self.assertEqual(_clamp(1.0, 0.0, 1.0), 1.0)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertAlmostEqual(_mean([1.0, 2.0, 3.0]), 2.0)

    def test_mean_negative(self):
        self.assertAlmostEqual(_mean([-2.0, 2.0]), 0.0)

    def test_mean_single(self):
        self.assertAlmostEqual(_mean([7.0]), 7.0)

    def test_safe_div_ok(self):
        self.assertAlmostEqual(_safe_div(6.0, 3.0, None), 2.0)

    def test_safe_div_zero_den(self):
        self.assertIsNone(_safe_div(6.0, 0.0, None))

    def test_safe_div_neg_den(self):
        self.assertIsNone(_safe_div(6.0, -2.0, None))

    def test_safe_div_sentinel_value(self):
        self.assertEqual(_safe_div(6.0, 0.0, -1.0), -1.0)

    def test_coerce_num_bool_true(self):
        self.assertIsNone(_coerce_num(True))

    def test_coerce_num_bool_false(self):
        self.assertIsNone(_coerce_num(False))

    def test_coerce_num_none(self):
        self.assertIsNone(_coerce_num(None))

    def test_coerce_num_nan(self):
        self.assertIsNone(_coerce_num(float("nan")))

    def test_coerce_num_inf(self):
        self.assertIsNone(_coerce_num(float("inf")))

    def test_coerce_num_neg_inf(self):
        self.assertIsNone(_coerce_num(float("-inf")))

    def test_coerce_num_str(self):
        self.assertEqual(_coerce_num("2.5"), 2.5)

    def test_coerce_num_neg_str(self):
        self.assertEqual(_coerce_num("-2.5"), -2.5)

    def test_coerce_num_empty_str(self):
        self.assertIsNone(_coerce_num("   "))

    def test_coerce_num_bad_str(self):
        self.assertIsNone(_coerce_num("xyz"))

    def test_coerce_num_int(self):
        self.assertEqual(_coerce_num(4), 4.0)

    def test_coerce_num_zero(self):
        self.assertEqual(_coerce_num(0), 0.0)

    def test_coerce_num_list_rejected(self):
        self.assertIsNone(_coerce_num([1.0]))

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

    def test_grade_boundary_55(self):
        self.assertEqual(_grade_from_score(55), "C")

    def test_grade_boundary_40(self):
        self.assertEqual(_grade_from_score(40), "D")

    def test_grade_just_below_85(self):
        self.assertEqual(_grade_from_score(84.99), "B")

    def test_grade_just_below_40(self):
        self.assertEqual(_grade_from_score(39.99), "F")

    def test_build_default_cfg_defaults(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg["log_cap"], 5)

    def test_build_default_cfg_extra_key(self):
        cfg = _build_default_cfg({"log_path": "/x"})
        self.assertEqual(cfg["log_path"], "/x")

    def test_build_default_cfg_none(self):
        cfg = _build_default_cfg(None)
        self.assertEqual(cfg["log_cap"], LOG_CAP)


# ── _coerce_fee ─────────────────────────────────────────────────────────────────

class TestCoerceFee(unittest.TestCase):
    def test_fee_positive(self):
        self.assertEqual(_coerce_fee(1.5), 1.5)

    def test_fee_negative_to_magnitude(self):
        self.assertEqual(_coerce_fee(-1.5), 1.5)

    def test_fee_zero(self):
        self.assertEqual(_coerce_fee(0.0), 0.0)

    def test_fee_none_zero(self):
        self.assertEqual(_coerce_fee(None), 0.0)

    def test_fee_bool_zero(self):
        self.assertEqual(_coerce_fee(True), 0.0)

    def test_fee_nan_zero(self):
        self.assertEqual(_coerce_fee(float("nan")), 0.0)

    def test_fee_inf_zero(self):
        self.assertEqual(_coerce_fee(float("inf")), 0.0)

    def test_fee_neg_inf_zero(self):
        self.assertEqual(_coerce_fee(float("-inf")), 0.0)

    def test_fee_str_numeric(self):
        self.assertEqual(_coerce_fee("2.5"), 2.5)

    def test_fee_neg_str(self):
        self.assertEqual(_coerce_fee("-2.5"), 2.5)

    def test_fee_bad_str_zero(self):
        self.assertEqual(_coerce_fee("xyz"), 0.0)

    def test_fee_int(self):
        self.assertEqual(_coerce_fee(3), 3.0)


# ── holding-path math correctness ────────────────────────────────────────────────

class TestHoldingMath(unittest.TestCase):
    def test_drag_formula_basic(self):
        # round_trip 2.0, holding 365 → drag = 2.0
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=2.0, holding_days=365.0))
        self.assertAlmostEqual(r["amortized_fee_drag_apr_pct"], 2.0, places=4)

    def test_drag_half_pct_30_days(self):
        # 0.5% round-trip held 30 days ≈ 6.0833
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, round_trip_fee_pct=0.5, holding_days=30.0))
        self.assertAlmostEqual(
            r["amortized_fee_drag_apr_pct"], 0.5 * 365.0 / 30.0, places=4)
        self.assertAlmostEqual(
            r["amortized_fee_drag_apr_pct"], 6.0833, places=3)

    def test_drag_half_pct_365_days(self):
        # 0.5% round-trip held 365 days = 0.5
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, round_trip_fee_pct=0.5, holding_days=365.0))
        self.assertAlmostEqual(r["amortized_fee_drag_apr_pct"], 0.5, places=4)

    def test_drag_half_pct_730_days(self):
        # 0.5% round-trip held 730 days = 0.25
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, round_trip_fee_pct=0.5, holding_days=730.0))
        self.assertAlmostEqual(r["amortized_fee_drag_apr_pct"], 0.25, places=4)

    def test_drag_scales_inversely_with_hold(self):
        short = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, round_trip_fee_pct=1.0, holding_days=30.0))
        long = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, round_trip_fee_pct=1.0, holding_days=365.0))
        self.assertGreater(
            short["amortized_fee_drag_apr_pct"],
            long["amortized_fee_drag_apr_pct"])

    def test_drag_scales_with_fee(self):
        small = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, round_trip_fee_pct=0.5, holding_days=90.0))
        big = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, round_trip_fee_pct=2.0, holding_days=90.0))
        self.assertGreater(
            big["amortized_fee_drag_apr_pct"],
            small["amortized_fee_drag_apr_pct"])

    def test_drag_zero_when_no_fee(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.0, holding_days=365.0))
        self.assertAlmostEqual(r["amortized_fee_drag_apr_pct"], 0.0, places=6)

    def test_drag_180_days(self):
        # 1.0% round-trip held 180 days
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days=180.0))
        self.assertAlmostEqual(
            r["amortized_fee_drag_apr_pct"], 1.0 * 365.0 / 180.0, places=4)


# ── entry+exit summation vs round_trip override ──────────────────────────────────

class TestRoundTripResolution(unittest.TestCase):
    def test_entry_plus_exit(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, entry_fee_pct=0.3, exit_fee_pct=0.4,
            holding_days=365.0))
        self.assertAlmostEqual(r["round_trip_fee_pct"], 0.7, places=4)

    def test_override_takes_precedence(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, entry_fee_pct=5.0, exit_fee_pct=5.0,
            round_trip_fee_pct=1.0, holding_days=365.0))
        self.assertAlmostEqual(r["round_trip_fee_pct"], 1.0, places=4)

    def test_override_zero_takes_precedence(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, entry_fee_pct=5.0, exit_fee_pct=5.0,
            round_trip_fee_pct=0.0, holding_days=365.0))
        self.assertAlmostEqual(r["round_trip_fee_pct"], 0.0, places=4)

    def test_negative_override_falls_to_sum(self):
        # negative round_trip override is invalid → use entry + exit
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, entry_fee_pct=0.3, exit_fee_pct=0.4,
            round_trip_fee_pct=-1.0, holding_days=365.0))
        self.assertAlmostEqual(r["round_trip_fee_pct"], 0.7, places=4)

    def test_nan_override_falls_to_sum(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, entry_fee_pct=0.3, exit_fee_pct=0.4,
            round_trip_fee_pct=float("nan"), holding_days=365.0))
        self.assertAlmostEqual(r["round_trip_fee_pct"], 0.7, places=4)

    def test_entry_only(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, entry_fee_pct=0.5, holding_days=365.0))
        self.assertAlmostEqual(r["round_trip_fee_pct"], 0.5, places=4)

    def test_exit_only(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, exit_fee_pct=0.6, holding_days=365.0))
        self.assertAlmostEqual(r["round_trip_fee_pct"], 0.6, places=4)

    def test_no_fees_zero_round_trip(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, holding_days=365.0))
        self.assertAlmostEqual(r["round_trip_fee_pct"], 0.0, places=4)

    def test_negative_entry_to_abs(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, entry_fee_pct=-0.3, exit_fee_pct=0.4,
            holding_days=365.0))
        self.assertAlmostEqual(r["round_trip_fee_pct"], 0.7, places=4)

    def test_negative_exit_to_abs(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, entry_fee_pct=0.3, exit_fee_pct=-0.4,
            holding_days=365.0))
        self.assertAlmostEqual(r["round_trip_fee_pct"], 0.7, places=4)

    def test_string_fees(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, entry_fee_pct="0.3", exit_fee_pct="0.4",
            holding_days=365.0))
        self.assertAlmostEqual(r["round_trip_fee_pct"], 0.7, places=4)


# ── net / overstatement / ratios / breakeven ─────────────────────────────────────

class TestCoreMetrics(unittest.TestCase):
    def test_net_realized_is_difference(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=2.0, holding_days=365.0))
        self.assertAlmostEqual(
            r["net_realized_apr_pct"],
            r["headline_apr_pct"] - r["amortized_fee_drag_apr_pct"], places=6)

    def test_net_realized_value(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=3.0, holding_days=365.0))
        self.assertAlmostEqual(r["net_realized_apr_pct"], 9.0, places=4)

    def test_overstatement_equals_drag(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=2.0, holding_days=365.0))
        self.assertAlmostEqual(
            r["overstatement_pct"], r["amortized_fee_drag_apr_pct"], places=6)

    def test_realization_ratio_value(self):
        # headline 12, drag 3 → net 9 → ratio 0.75
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=3.0, holding_days=365.0))
        self.assertAlmostEqual(r["realization_ratio"], 0.75, places=4)

    def test_fee_drag_fraction_value(self):
        # headline 12, drag 3 → fraction 0.25
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=3.0, holding_days=365.0))
        self.assertAlmostEqual(r["fee_drag_fraction"], 0.25, places=4)

    def test_realization_plus_fraction_complement(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=2.4, holding_days=365.0))
        self.assertAlmostEqual(
            r["realization_ratio"] + r["fee_drag_fraction"], 1.0, places=4)

    def test_breakeven_days_value(self):
        # round_trip 1.0, headline 12 → breakeven = 1/12*365
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days=365.0))
        self.assertAlmostEqual(
            r["breakeven_days"], 1.0 / 12.0 * 365.0, places=4)

    def test_breakeven_none_when_no_fee(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.0, holding_days=365.0))
        self.assertIsNone(r["breakeven_days"])

    def test_breakeven_scales_with_fee(self):
        small = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.5, holding_days=365.0))
        big = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=2.0, holding_days=365.0))
        self.assertGreater(big["breakeven_days"], small["breakeven_days"])

    def test_holding_days_reported(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days=120.0))
        self.assertAlmostEqual(r["holding_days"], 120.0, places=4)

    def test_net_negative_when_drag_exceeds(self):
        # short hold, big fee → drag > headline → net negative
        r = A()._analyze_one(make_pos(
            headline_apr_pct=10.0, round_trip_fee_pct=3.0, holding_days=20.0))
        self.assertTrue(r["net_is_negative"])

    def test_net_negative_when_hold_below_breakeven(self):
        # breakeven for 1.0 fee @ 12 APR is ~30.4 days; hold 20 < breakeven → net neg
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days=20.0))
        self.assertTrue(r["net_is_negative"])

    def test_net_positive_when_hold_above_breakeven(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days=365.0))
        self.assertFalse(r["net_is_negative"])

    def test_net_is_negative_false_clean(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.1, holding_days=730.0))
        self.assertFalse(r["net_is_negative"])

    def test_net_exactly_zero_is_negative(self):
        # drag exactly equals headline → net 0 → net_is_negative True
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=12.0, holding_days=365.0))
        self.assertTrue(r["net_is_negative"])


# ── classification thresholds ───────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_clean_low_fee(self):
        # headline 12, drag 0.05 → fraction ~0.0042 ≤ 0.05
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.1, holding_days=730.0))
        self.assertEqual(r["classification"], "CLEAN_LOW_FEE")

    def test_clean_boundary_exact(self):
        # fraction exactly 0.05: drag = 0.05*12 = 0.6 → round_trip 0.6 @ 365 days
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.6, holding_days=365.0))
        self.assertAlmostEqual(r["fee_drag_fraction"], 0.05, places=4)
        self.assertEqual(r["classification"], "CLEAN_LOW_FEE")

    def test_just_above_clean_is_mild(self):
        # fraction slightly above 0.05
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.66, holding_days=365.0))
        self.assertGreater(r["fee_drag_fraction"], CLEAN_FRACTION)
        self.assertEqual(r["classification"], "MILD_FEE_DRAG")

    def test_mild_fee_drag(self):
        # fraction ~0.1667
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=2.0, holding_days=365.0))
        self.assertEqual(r["classification"], "MILD_FEE_DRAG")

    def test_mild_boundary_exact(self):
        # fraction exactly 0.20: drag = 0.20*12 = 2.4
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=2.4, holding_days=365.0))
        self.assertAlmostEqual(r["fee_drag_fraction"], 0.20, places=4)
        self.assertEqual(r["classification"], "MILD_FEE_DRAG")

    def test_just_above_mild_is_moderate(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=2.5, holding_days=365.0))
        self.assertGreater(r["fee_drag_fraction"], MILD_FRACTION)
        self.assertEqual(r["classification"], "MODERATE_FEE_DRAG")

    def test_moderate_fee_drag(self):
        # fraction ~0.35
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=4.2, holding_days=365.0))
        self.assertEqual(r["classification"], "MODERATE_FEE_DRAG")

    def test_moderate_boundary_exact(self):
        # fraction exactly 0.50: drag = 0.50*12 = 6.0
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=6.0, holding_days=365.0))
        self.assertAlmostEqual(r["fee_drag_fraction"], 0.50, places=4)
        self.assertEqual(r["classification"], "MODERATE_FEE_DRAG")

    def test_just_above_moderate_is_severe(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=6.5, holding_days=365.0))
        self.assertGreater(r["fee_drag_fraction"], MODERATE_FRACTION)
        self.assertEqual(r["classification"], "SEVERE_FEE_DRAG")

    def test_severe_fee_drag_above_moderate(self):
        # fraction ~0.75, not net negative
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=9.0, holding_days=365.0))
        self.assertEqual(r["classification"], "SEVERE_FEE_DRAG")
        self.assertFalse(r["net_is_negative"])

    def test_severe_via_net_negative(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=10.0, round_trip_fee_pct=3.0, holding_days=20.0))
        self.assertEqual(r["classification"], "SEVERE_FEE_DRAG")
        self.assertTrue(r["net_is_negative"])

    def test_net_negative_overrides_classification(self):
        # drag exactly equals headline → net 0 → SEVERE
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=12.0, holding_days=365.0))
        self.assertTrue(r["net_is_negative"])
        self.assertEqual(r["classification"], "SEVERE_FEE_DRAG")

    def test_classification_monotone_with_fee(self):
        fractions = []
        for fee in (0.1, 1.0, 3.0, 9.0):
            r = A()._analyze_one(make_pos(
                headline_apr_pct=12.0, round_trip_fee_pct=fee,
                holding_days=365.0))
            fractions.append(r["fee_drag_fraction"])
        for i in range(len(fractions) - 1):
            self.assertLessEqual(fractions[i], fractions[i + 1])


# ── ratios bounds ────────────────────────────────────────────────────────────────

class TestRatios(unittest.TestCase):
    def test_realization_ratio_bounds(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            if r["realization_ratio"] is not None:
                self.assertGreaterEqual(r["realization_ratio"], 0.0)
                self.assertLessEqual(r["realization_ratio"], 1.0)

    def test_fee_drag_fraction_bounds(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            if r["fee_drag_fraction"] is not None:
                self.assertGreaterEqual(r["fee_drag_fraction"], 0.0)
                self.assertLessEqual(r["fee_drag_fraction"], 1.0)

    def test_fee_drag_fraction_capped_at_one(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=100.0, holding_days=10.0))
        self.assertLessEqual(r["fee_drag_fraction"], 1.0)

    def test_realization_zero_when_net_negative(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=10.0, round_trip_fee_pct=5.0, holding_days=10.0))
        self.assertAlmostEqual(r["realization_ratio"], 0.0, places=6)


# ── override path ────────────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def test_override_used(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=9.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_holding"])
        self.assertIn("DRAG_FROM_OVERRIDE", r["flags"])
        finite_check(self, r)

    def test_override_net_computed(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=9.0))
        self.assertAlmostEqual(r["net_realized_apr_pct"], 15.0, places=4)

    def test_override_overstatement(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=9.0))
        self.assertAlmostEqual(r["overstatement_pct"], 9.0, places=4)

    def test_override_fee_drag_fraction(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=9.0))
        self.assertAlmostEqual(r["fee_drag_fraction"], 9.0 / 24.0, places=4)

    def test_override_realization_ratio(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=9.0))
        self.assertAlmostEqual(r["realization_ratio"], 15.0 / 24.0, places=4)

    def test_override_zero_drag_clean(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, amortized_fee_drag_apr_pct=0.0))
        self.assertAlmostEqual(r["amortized_fee_drag_apr_pct"], 0.0, places=6)
        self.assertEqual(r["classification"], "CLEAN_LOW_FEE")

    def test_override_classification_moderate(self):
        # fraction 0.375 → MODERATE
        r = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=9.0))
        self.assertEqual(r["classification"], "MODERATE_FEE_DRAG")

    def test_override_holding_geometry_none(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=9.0))
        self.assertIsNone(r["round_trip_fee_pct"])
        self.assertIsNone(r["breakeven_days"])
        self.assertIsNone(r["holding_days"])

    def test_override_suppresses_holding_flags(self):
        # supply short-hold + high fee fields, but override path → no holding flags
        r = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=9.0,
            entry_fee_pct=5.0, exit_fee_pct=5.0, holding_days=5.0))
        self.assertNotIn("SHORT_HOLD_PENALTY", r["flags"])
        self.assertNotIn("HIGH_ROUND_TRIP_FEE", r["flags"])

    def test_override_takes_precedence_over_holding(self):
        # both drag override and holding fields present → override path
        r = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=2.0,
            round_trip_fee_pct=10.0, holding_days=30.0))
        self.assertTrue(r["used_override"])
        self.assertAlmostEqual(r["amortized_fee_drag_apr_pct"], 2.0, places=4)

    def test_override_net_negative_severe(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=10.0, amortized_fee_drag_apr_pct=15.0))
        self.assertTrue(r["net_is_negative"])
        self.assertEqual(r["classification"], "SEVERE_FEE_DRAG")
        self.assertIn("NET_NEGATIVE_AFTER_FEES", r["flags"])

    def test_override_str_inputs(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct="24.0", amortized_fee_drag_apr_pct="9.0"))
        self.assertAlmostEqual(r["net_realized_apr_pct"], 15.0, places=4)

    def test_override_negative_drag_falls_to_holding(self):
        # negative drag override invalid → holding path used
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, amortized_fee_drag_apr_pct=-5.0,
            round_trip_fee_pct=1.0, holding_days=365.0))
        self.assertFalse(r["used_override"])
        self.assertTrue(r["used_holding"])

    def test_override_nan_drag_falls_to_holding(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0,
            amortized_fee_drag_apr_pct=float("nan"),
            round_trip_fee_pct=1.0, holding_days=365.0))
        self.assertFalse(r["used_override"])
        self.assertTrue(r["used_holding"])

    def test_override_requires_positive_headline(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=0.0, amortized_fee_drag_apr_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_negative_headline_insufficient(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=-5.0, amortized_fee_drag_apr_pct=2.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")


# ── insufficient data ────────────────────────────────────────────────────────────

class TestInsufficient(unittest.TestCase):
    def test_no_headline(self):
        r = A()._analyze_one(make_pos(
            round_trip_fee_pct=1.0, holding_days=30.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_headline(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=0.0, round_trip_fee_pct=1.0, holding_days=30.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_headline(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=-3.0, round_trip_fee_pct=1.0, holding_days=30.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_headline(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=float("nan"), round_trip_fee_pct=1.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_headline(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=float("inf"), round_trip_fee_pct=1.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_bad_str_headline(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct="abc", round_trip_fee_pct=1.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_bool_headline(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=True, round_trip_fee_pct=1.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_data_at_all(self):
        r = A()._analyze_one({"vault": "x"})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_shape(self):
        r = A()._analyze_one(make_pos(round_trip_fee_pct=1.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertIsNone(r["realization_ratio"])
        self.assertIsNone(r["fee_drag_fraction"])
        self.assertIsNone(r["net_realized_apr_pct"])
        self.assertIsNone(r["headline_apr_pct"])
        self.assertIsNone(r["amortized_fee_drag_apr_pct"])

    def test_insufficient_recommendation(self):
        r = A()._analyze_one(make_pos(round_trip_fee_pct=1.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_insufficient_net_is_negative_false(self):
        r = A()._analyze_one(make_pos(round_trip_fee_pct=1.0))
        self.assertFalse(r["net_is_negative"])

    def test_insufficient_flags_used_false(self):
        r = A()._analyze_one(make_pos(round_trip_fee_pct=1.0))
        self.assertFalse(r["used_override"])
        self.assertFalse(r["used_holding"])


# ── holding-day defaults / coercion ──────────────────────────────────────────────

class TestHoldingDays(unittest.TestCase):
    def test_default_holding_days(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0))
        self.assertAlmostEqual(r["holding_days"], DEFAULT_HOLDING_DAYS, places=4)

    def test_zero_holding_falls_back(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days=0.0))
        self.assertAlmostEqual(r["holding_days"], DEFAULT_HOLDING_DAYS, places=4)

    def test_negative_holding_falls_back(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days=-30.0))
        self.assertAlmostEqual(r["holding_days"], DEFAULT_HOLDING_DAYS, places=4)

    def test_nan_holding_falls_back(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0,
            holding_days=float("nan")))
        self.assertAlmostEqual(r["holding_days"], DEFAULT_HOLDING_DAYS, places=4)

    def test_inf_holding_falls_back(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0,
            holding_days=float("inf")))
        self.assertAlmostEqual(r["holding_days"], DEFAULT_HOLDING_DAYS, places=4)

    def test_string_holding_days(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days="180"))
        self.assertAlmostEqual(r["holding_days"], 180.0, places=4)

    def test_bool_holding_falls_back(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days=True))
        self.assertAlmostEqual(r["holding_days"], DEFAULT_HOLDING_DAYS, places=4)


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_classification_in_flags_first(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=4.2, holding_days=365.0))
        self.assertEqual(r["flags"][0], r["classification"])

    def test_classification_in_flags(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=4.2, holding_days=365.0))
        self.assertIn(r["classification"], r["flags"])

    def test_net_negative_flag(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=10.0, round_trip_fee_pct=3.0, holding_days=20.0))
        self.assertIn("NET_NEGATIVE_AFTER_FEES", r["flags"])

    def test_no_net_negative_flag_clean(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.1, holding_days=730.0))
        self.assertNotIn("NET_NEGATIVE_AFTER_FEES", r["flags"])

    def test_clean_low_fee_hold_flag(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.1, holding_days=730.0))
        self.assertIn("CLEAN_LOW_FEE_HOLD", r["flags"])

    def test_no_clean_flag_when_fee_drag(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=4.2, holding_days=365.0))
        self.assertNotIn("CLEAN_LOW_FEE_HOLD", r["flags"])

    def test_clean_low_fee_hold_flag_override(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=0.5))
        self.assertEqual(r["classification"], "CLEAN_LOW_FEE")
        self.assertIn("CLEAN_LOW_FEE_HOLD", r["flags"])

    def test_short_hold_penalty_flag(self):
        # holding 30 < 60 → SHORT_HOLD_PENALTY
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.5, holding_days=30.0))
        self.assertIn("SHORT_HOLD_PENALTY", r["flags"])

    def test_no_short_hold_penalty_when_long(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.5, holding_days=365.0))
        self.assertNotIn("SHORT_HOLD_PENALTY", r["flags"])

    def test_short_hold_boundary_exact(self):
        # holding exactly 60 → NOT below SHORT_HOLD_DAYS → no flag
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.5,
            holding_days=SHORT_HOLD_DAYS))
        self.assertNotIn("SHORT_HOLD_PENALTY", r["flags"])

    def test_short_hold_just_below_boundary(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.5, holding_days=59.9))
        self.assertIn("SHORT_HOLD_PENALTY", r["flags"])

    def test_high_round_trip_fee_flag(self):
        # round_trip 1.5 >= 1.0 → HIGH_ROUND_TRIP_FEE
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.5, holding_days=365.0))
        self.assertIn("HIGH_ROUND_TRIP_FEE", r["flags"])

    def test_high_round_trip_boundary_exact(self):
        # round_trip exactly 1.0 → at/above → flag present
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0,
            round_trip_fee_pct=HIGH_ROUND_TRIP_FEE_PCT, holding_days=365.0))
        self.assertIn("HIGH_ROUND_TRIP_FEE", r["flags"])

    def test_no_high_round_trip_when_low(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.5, holding_days=365.0))
        self.assertNotIn("HIGH_ROUND_TRIP_FEE", r["flags"])

    def test_drag_from_override_flag(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=9.0))
        self.assertIn("DRAG_FROM_OVERRIDE", r["flags"])

    def test_holding_path_no_override_flag(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days=365.0))
        self.assertNotIn("DRAG_FROM_OVERRIDE", r["flags"])

    def test_override_no_short_hold_flag(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=9.0))
        self.assertNotIn("SHORT_HOLD_PENALTY", r["flags"])

    def test_override_no_high_fee_flag(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=9.0))
        self.assertNotIn("HIGH_ROUND_TRIP_FEE", r["flags"])

    def test_both_holding_flags_together(self):
        # short hold AND high fee
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.5, holding_days=30.0))
        self.assertIn("SHORT_HOLD_PENALTY", r["flags"])
        self.assertIn("HIGH_ROUND_TRIP_FEE", r["flags"])


# ── scoring ─────────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_clean_high_score(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.1, holding_days=730.0))
        self.assertGreaterEqual(r["score"], 85)

    def test_clean_score_full(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.0, holding_days=365.0))
        self.assertAlmostEqual(r["score"], 100.0, places=2)

    def test_severe_low_score(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=10.0, round_trip_fee_pct=5.0, holding_days=10.0))
        self.assertLess(r["score"], 40)

    def test_score_in_range_all_demo(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_score_monotonic_in_fee(self):
        small = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.5, holding_days=365.0))
        big = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=4.0, holding_days=365.0))
        self.assertGreater(small["score"], big["score"])

    def test_score_monotonic_in_hold(self):
        short = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days=90.0))
        long = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days=365.0))
        self.assertGreater(long["score"], short["score"])

    def test_score_monotonic_override(self):
        a = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=2.0))
        b = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=12.0))
        self.assertGreater(a["score"], b["score"])

    def test_score_formula(self):
        # headline 12, drag 3 → ratio 0.75, fraction 0.25
        # score = 70*0.75 + 30*0.75 = 52.5 + 22.5 = 75
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=3.0, holding_days=365.0))
        self.assertAlmostEqual(r["score"], 75.0, places=2)

    def test_score_formula_override(self):
        # headline 24, drag 6 → ratio 0.75, fraction 0.25 → score 75
        r = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=6.0))
        self.assertAlmostEqual(r["score"], 75.0, places=2)

    def test_insufficient_score_zero(self):
        r = A()._analyze_one(make_pos(round_trip_fee_pct=1.0))
        self.assertEqual(r["score"], 0.0)

    def test_net_negative_score_low(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=10.0, round_trip_fee_pct=10.0, holding_days=10.0))
        # realization 0 → score = 30*(1-1)=0
        self.assertLessEqual(r["score"], 30)

    def test_score_grade_consistency(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── recommendation mapping ───────────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_clean_trust(self):
        self.assertEqual(A()._recommend("CLEAN_LOW_FEE"), "TRUST_HEADLINE")

    def test_mild_discount_slightly(self):
        self.assertEqual(
            A()._recommend("MILD_FEE_DRAG"), "DISCOUNT_HEADLINE_SLIGHTLY")

    def test_moderate_discount(self):
        self.assertEqual(
            A()._recommend("MODERATE_FEE_DRAG"), "DISCOUNT_HEADLINE")

    def test_severe_avoid(self):
        self.assertEqual(
            A()._recommend("SEVERE_FEE_DRAG"), "AVOID_OR_VERIFY")

    def test_insufficient_avoid(self):
        self.assertEqual(
            A()._recommend("INSUFFICIENT_DATA"), "AVOID_OR_VERIFY")

    def test_recommendation_via_result_clean(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=0.1, holding_days=730.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_recommendation_via_result_mild(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=2.0, holding_days=365.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE_SLIGHTLY")

    def test_recommendation_via_result_moderate(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=4.2, holding_days=365.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE")

    def test_recommendation_via_result_severe(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=10.0, round_trip_fee_pct=5.0, holding_days=10.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")


# ── _classify direct ─────────────────────────────────────────────────────────────

class TestClassifyDirect(unittest.TestCase):
    def test_classify_net_negative(self):
        self.assertEqual(A()._classify(0.01, True), "SEVERE_FEE_DRAG")

    def test_classify_clean(self):
        self.assertEqual(A()._classify(0.05, False), "CLEAN_LOW_FEE")

    def test_classify_clean_below(self):
        self.assertEqual(A()._classify(0.0, False), "CLEAN_LOW_FEE")

    def test_classify_mild(self):
        self.assertEqual(A()._classify(0.20, False), "MILD_FEE_DRAG")

    def test_classify_mild_mid(self):
        self.assertEqual(A()._classify(0.10, False), "MILD_FEE_DRAG")

    def test_classify_moderate(self):
        self.assertEqual(A()._classify(0.50, False), "MODERATE_FEE_DRAG")

    def test_classify_moderate_mid(self):
        self.assertEqual(A()._classify(0.35, False), "MODERATE_FEE_DRAG")

    def test_classify_severe(self):
        self.assertEqual(A()._classify(0.51, False), "SEVERE_FEE_DRAG")

    def test_classify_severe_high(self):
        self.assertEqual(A()._classify(1.0, False), "SEVERE_FEE_DRAG")


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
            "cleanest_fee_vault", "worst_fee_drag_vault", "avg_score",
            "net_negative_count", "position_count",
        ):
            self.assertIn(key, agg)

    def test_aggregate_all_insufficient(self):
        out = A().analyze_portfolio([{"vault": "x"}, {"vault": "y"}])
        agg = out["aggregate"]
        self.assertIsNone(agg["cleanest_fee_vault"])
        self.assertIsNone(agg["worst_fee_drag_vault"])
        self.assertEqual(agg["avg_score"], 0.0)
        self.assertEqual(agg["net_negative_count"], 0)
        self.assertEqual(agg["position_count"], 2)

    def test_aggregate_empty(self):
        out = A().analyze_portfolio([])
        agg = out["aggregate"]
        self.assertIsNone(agg["cleanest_fee_vault"])
        self.assertEqual(agg["position_count"], 0)

    def test_cleanest_has_highest_score(self):
        out = A().analyze_portfolio(_demo_positions())
        scored = [
            r for r in out["positions"]
            if r["classification"] != "INSUFFICIENT_DATA"]
        best = max(scored, key=lambda r: r["score"])
        self.assertEqual(out["aggregate"]["cleanest_fee_vault"], best["token"])

    def test_worst_has_lowest_score(self):
        out = A().analyze_portfolio(_demo_positions())
        scored = [
            r for r in out["positions"]
            if r["classification"] != "INSUFFICIENT_DATA"]
        worst = min(scored, key=lambda r: r["score"])
        self.assertEqual(
            out["aggregate"]["worst_fee_drag_vault"], worst["token"])

    def test_net_negative_count(self):
        positions = [
            make_pos(vault="neg", headline_apr_pct=10.0,
                     round_trip_fee_pct=5.0, holding_days=10.0),
            make_pos(vault="ok", headline_apr_pct=12.0,
                     round_trip_fee_pct=0.1, holding_days=730.0),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["net_negative_count"], 1)

    def test_net_negative_count_zero(self):
        positions = [
            make_pos(vault="a", headline_apr_pct=12.0,
                     round_trip_fee_pct=0.1, holding_days=730.0),
            make_pos(vault="b", headline_apr_pct=12.0,
                     round_trip_fee_pct=0.2, holding_days=730.0),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["net_negative_count"], 0)

    def test_position_count(self):
        agg = A().analyze_portfolio(_demo_positions())["aggregate"]
        self.assertEqual(agg["position_count"], len(_demo_positions()))

    def test_avg_score_excludes_insufficient(self):
        positions = [
            make_pos(vault="a", headline_apr_pct=12.0,
                     round_trip_fee_pct=0.0, holding_days=365.0),
            make_pos(vault="bad", round_trip_fee_pct=1.0),  # insufficient
        ]
        out = A().analyze_portfolio(positions)
        agg = out["aggregate"]
        # avg only over the one scored (100.0)
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
            make_pos(headline_apr_pct=10.0, round_trip_fee_pct=100.0,
                     holding_days=1.0),
            make_pos(headline_apr_pct=12.0, amortized_fee_drag_apr_pct=50.0),
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
            "token": "T1", "headline_apr_pct": 12.0,
            "round_trip_fee_pct": 1.0, "holding_days": 365.0})
        self.assertEqual(r["token"], "T1")

    def test_unknown_token(self):
        r = A()._analyze_one({"headline_apr_pct": 12.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_vault_preferred_over_token(self):
        r = A()._analyze_one({
            "vault": "V", "token": "T", "headline_apr_pct": 12.0})
        self.assertEqual(r["token"], "V")

    def test_huge_fee_no_overflow(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=10.0, round_trip_fee_pct=1e6, holding_days=1.0))
        finite_check(self, r)

    def test_tiny_holding_no_overflow(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=10.0, round_trip_fee_pct=1.0, holding_days=0.001))
        finite_check(self, r)

    def test_negative_round_trip_override_uses_sum(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, entry_fee_pct=0.5, exit_fee_pct=0.5,
            round_trip_fee_pct=-2.0, holding_days=365.0))
        self.assertAlmostEqual(r["round_trip_fee_pct"], 1.0, places=4)


# ── rounding ─────────────────────────────────────────────────────────────────────

class TestRounding(unittest.TestCase):
    def test_drag_rounded_4dp(self):
        # 0.5 round-trip @ 30 days → 6.08333... → 6.0833
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, round_trip_fee_pct=0.5, holding_days=30.0))
        self.assertEqual(r["amortized_fee_drag_apr_pct"],
                         round(0.5 * 365.0 / 30.0, 4))

    def test_score_rounded_2dp(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days=137.0))
        self.assertEqual(r["score"], round(r["score"], 2))

    def test_ratio_rounded_4dp(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days=137.0))
        self.assertEqual(r["realization_ratio"],
                         round(r["realization_ratio"], 4))

    def test_breakeven_rounded_4dp(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=7.0, round_trip_fee_pct=1.0, holding_days=365.0))
        self.assertEqual(r["breakeven_days"], round(r["breakeven_days"], 4))


# ── result keys / shape ──────────────────────────────────────────────────────────

class TestResultShape(unittest.TestCase):
    def test_holding_result_keys(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days=365.0))
        expected = set(A()._insufficient("x").keys())
        self.assertEqual(set(r.keys()), expected)

    def test_override_result_keys(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=24.0, amortized_fee_drag_apr_pct=9.0))
        expected = set(A()._insufficient("x").keys())
        self.assertEqual(set(r.keys()), expected)

    def test_insufficient_result_keys(self):
        r = A()._analyze_one(make_pos(round_trip_fee_pct=1.0))
        expected = set(A()._insufficient("x").keys())
        self.assertEqual(set(r.keys()), expected)

    def test_all_demo_same_keys(self):
        expected = set(A()._insufficient("x").keys())
        for p in _demo_positions():
            r = A()._analyze_one(p)
            self.assertEqual(set(r.keys()), expected)

    def test_sample_count_zero(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days=365.0))
        self.assertEqual(r["sample_count"], 0)

    def test_used_holding_true_on_holding(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0, round_trip_fee_pct=1.0, holding_days=365.0))
        self.assertTrue(r["used_holding"])
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
                    make_pos(headline_apr_pct=12.0, round_trip_fee_pct=1.0,
                             holding_days=365.0),
                    cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertLessEqual(len(data), LOG_CAP)
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
        # uses a temp cfg path → real LOG_PATH must not be written by this test
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
        self.assertIn("CLEAN_LOW_FEE", classes)
        self.assertIn("MILD_FEE_DRAG", classes)
        self.assertIn("MODERATE_FEE_DRAG", classes)
        self.assertIn("SEVERE_FEE_DRAG", classes)
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_all_keys_present(self):
        expected = set(A()._insufficient("x").keys())
        for p in _demo_positions():
            r = A()._analyze_one(p)
            self.assertEqual(set(r.keys()), expected)

    def test_demo_override_present(self):
        results = [A()._analyze_one(p) for p in _demo_positions()]
        self.assertTrue(any(r["used_override"] for r in results))

    def test_demo_holding_present(self):
        results = [A()._analyze_one(p) for p in _demo_positions()]
        self.assertTrue(any(r["used_holding"] for r in results))

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
            "CLEAN_LOW_FEE",
            "MILD_FEE_DRAG",
            "SEVERE_FEE_DRAG",
            "MODERATE_FEE_DRAG",
            "INSUFFICIENT_DATA",
        ])


# ── registry integration ────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    def test_registered(self):
        from spa_core.analytics import _module_registry as reg
        names = [m["module"] for m in reg.ALL_MODULES]
        self.assertIn(
            "defi_protocol_vault_entry_exit_fee_amortization_analyzer", names)

    def test_registry_entry_fields(self):
        from spa_core.analytics import _module_registry as reg
        entry = next(
            m for m in reg.ALL_MODULES
            if m["module"]
            == "defi_protocol_vault_entry_exit_fee_amortization_analyzer")
        self.assertEqual(entry["tier"], "B")
        self.assertEqual(entry["category"], "yield_quality")
        self.assertEqual(entry["weight"], 0.5)
        self.assertEqual(
            entry["class"],
            "DeFiProtocolVaultEntryExitFeeAmortizationAnalyzer")

    def test_registry_tier_b_count(self):
        from spa_core.analytics import _module_registry as reg
        self.assertEqual(reg.tier_counts()["B"], 456)

    def test_registry_all_modules_count(self):
        from spa_core.analytics import _module_registry as reg
        self.assertEqual(len(reg.ALL_MODULES), 648)


# ── constants sanity ─────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_thresholds_ordered(self):
        self.assertLess(CLEAN_FRACTION, MILD_FRACTION)
        self.assertLess(MILD_FRACTION, MODERATE_FRACTION)

    def test_default_holding_days(self):
        self.assertEqual(DEFAULT_HOLDING_DAYS, 365.0)

    def test_days_per_year(self):
        self.assertEqual(DAYS_PER_YEAR, 365.0)

    def test_clean_fraction(self):
        self.assertEqual(CLEAN_FRACTION, 0.05)

    def test_mild_fraction(self):
        self.assertEqual(MILD_FRACTION, 0.20)

    def test_moderate_fraction(self):
        self.assertEqual(MODERATE_FRACTION, 0.50)

    def test_short_hold_days(self):
        self.assertEqual(SHORT_HOLD_DAYS, 60.0)

    def test_high_round_trip_fee(self):
        self.assertEqual(HIGH_ROUND_TRIP_FEE_PCT, 1.0)

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
