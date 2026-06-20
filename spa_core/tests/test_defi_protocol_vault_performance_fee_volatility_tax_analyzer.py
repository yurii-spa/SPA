"""
Tests for MP-1203: DeFiProtocolVaultPerformanceFeeVolatilityTaxAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_performance_fee_volatility_tax_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_performance_fee_volatility_tax_analyzer import (  # noqa: E501
    DeFiProtocolVaultPerformanceFeeVolatilityTaxAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _coerce_num,
    _coerce_returns,
    _coerce_perf_fee_pct,
    _pstdev,
    _geom_mean_period,
    _annualise_geom,
    _simulate_net_path,
    _net_geom_period,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    MIN_SAMPLES,
    DEFAULT_PERIODS_PER_YEAR,
    DEFAULT_INITIAL_NAV,
    DEFAULT_PERF_FEE_PCT,
    NEUTRAL_FRACTION,
    MILD_FRACTION,
    MODERATE_FRACTION,
    HIGH_PERF_FEE_PCT,
    HIGH_GROSS_VOL_PCT,
    HIGH_VOL_TAX_FRACTION,
    ASYMMETRY_FACTOR,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    period_returns=None,
    perf_fee_pct=None,
    periods_per_year=None,
    gross_apr_pct=None,
    gross_return_vol_pct=None,
):
    pos = {"vault": vault}
    if period_returns is not None:
        pos["period_returns"] = period_returns
    if perf_fee_pct is not None:
        pos["perf_fee_pct"] = perf_fee_pct
    if periods_per_year is not None:
        pos["periods_per_year"] = periods_per_year
    if gross_apr_pct is not None:
        pos["gross_apr_pct"] = gross_apr_pct
    if gross_return_vol_pct is not None:
        pos["gross_return_vol_pct"] = gross_return_vol_pct
    return pos


def A():
    return DeFiProtocolVaultPerformanceFeeVolatilityTaxAnalyzer()


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

    def test_mean_negative(self):
        self.assertAlmostEqual(_mean([-2.0, 2.0]), 0.0)

    def test_safe_div_ok(self):
        self.assertAlmostEqual(_safe_div(6.0, 3.0, None), 2.0)

    def test_safe_div_zero_den(self):
        self.assertIsNone(_safe_div(6.0, 0.0, None))

    def test_safe_div_neg_den(self):
        self.assertIsNone(_safe_div(6.0, -2.0, None))

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

    def test_perf_fee_clamps_high(self):
        self.assertEqual(_coerce_perf_fee_pct(150.0), 100.0)

    def test_perf_fee_clamps_negative(self):
        self.assertEqual(_coerce_perf_fee_pct(-5.0), 0.0)

    def test_perf_fee_valid(self):
        self.assertEqual(_coerce_perf_fee_pct(20.0), 20.0)

    def test_perf_fee_none(self):
        self.assertIsNone(_coerce_perf_fee_pct(None))

    def test_perf_fee_bad_str(self):
        self.assertIsNone(_coerce_perf_fee_pct("xyz"))

    def test_perf_fee_str_ok(self):
        self.assertEqual(_coerce_perf_fee_pct("15"), 15.0)

    def test_pstdev_short(self):
        self.assertEqual(_pstdev([1.0]), 0.0)

    def test_pstdev_constant(self):
        self.assertEqual(_pstdev([2.0, 2.0, 2.0]), 0.0)

    def test_pstdev_values(self):
        self.assertTrue(_pstdev([1.0, 3.0]) > 0.0)

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


# ── coercion of return vectors ─────────────────────────────────────────────────

class TestCoerceVectors(unittest.TestCase):
    def test_returns_keeps_negatives(self):
        self.assertEqual(_coerce_returns([2.0, -1.0, 3.0]), [2.0, -1.0, 3.0])

    def test_returns_skips_nonnumeric(self):
        self.assertEqual(_coerce_returns([2.0, "x", None, 3.0]), [2.0, 3.0])

    def test_returns_skips_bool(self):
        self.assertEqual(_coerce_returns([True, 2.0]), [2.0])

    def test_returns_skips_nan_inf(self):
        self.assertEqual(
            _coerce_returns([1.0, float("nan"), float("inf"), 2.0]), [1.0, 2.0])

    def test_returns_empty(self):
        self.assertEqual(_coerce_returns([]), [])

    def test_returns_none(self):
        self.assertEqual(_coerce_returns(None), [])

    def test_returns_preserves_order(self):
        self.assertEqual(_coerce_returns([3.0, 1.0, 2.0]), [3.0, 1.0, 2.0])

    def test_returns_zero_allowed(self):
        self.assertEqual(_coerce_returns([0.0, 1.0]), [0.0, 1.0])


# ── geometric mean / annualisation ─────────────────────────────────────────────

class TestGeomAnnualise(unittest.TestCase):
    def test_geom_constant(self):
        gm = _geom_mean_period([2.0, 2.0, 2.0])
        self.assertAlmostEqual(gm, 0.02, places=10)

    def test_geom_empty_none(self):
        self.assertIsNone(_geom_mean_period([]))

    def test_geom_breaks_on_total_loss(self):
        self.assertIsNone(_geom_mean_period([5.0, -100.0]))

    def test_geom_breaks_below_minus_100(self):
        self.assertIsNone(_geom_mean_period([-150.0, 5.0]))

    def test_geom_handles_negative(self):
        gm = _geom_mean_period([10.0, -5.0])
        self.assertTrue(math.isfinite(gm))

    def test_annualise_geom_positive(self):
        apr = _annualise_geom(0.02, 12.0)
        self.assertAlmostEqual(apr, (1.02 ** 12 - 1) * 100.0, places=4)

    def test_annualise_geom_nonpositive_base(self):
        self.assertIsNone(_annualise_geom(-1.5, 12.0))

    def test_annualise_geom_finite(self):
        apr = _annualise_geom(0.01, 365.0)
        self.assertTrue(math.isfinite(apr))


# ── net path simulation ─────────────────────────────────────────────────────────

class TestSimulateNetPath(unittest.TestCase):
    def test_zero_fee_no_crystallization(self):
        factors, cryst = _simulate_net_path([10.0, -5.0, 10.0], 0.0, 1.0)
        self.assertEqual(cryst, 0)
        # With no fee, net factors equal gross factors.
        self.assertAlmostEqual(factors[0], 1.10, places=6)
        self.assertAlmostEqual(factors[1], 0.95, places=6)

    def test_fee_crystallizes_on_new_high(self):
        factors, cryst = _simulate_net_path([10.0, 10.0], 20.0, 1.0)
        # Both periods reach new highs → fee both periods.
        self.assertEqual(cryst, 2)

    def test_no_fee_on_drawdown(self):
        # Up then down: only the up-leg crystallizes.
        factors, cryst = _simulate_net_path([10.0, -5.0], 20.0, 1.0)
        self.assertEqual(cryst, 1)

    def test_factors_positive(self):
        factors, _c = _simulate_net_path([5.0, -3.0, 7.0], 20.0, 1.0)
        for f in factors:
            self.assertGreater(f, 0.0)

    def test_fee_reduces_factor_on_up_leg(self):
        gross_factors, _c0 = _simulate_net_path([10.0], 0.0, 1.0)
        net_factors, _c1 = _simulate_net_path([10.0], 20.0, 1.0)
        self.assertLess(net_factors[0], gross_factors[0])

    def test_smooth_path_single_ascent_no_extra_drag(self):
        # A monotone equal-return path: net geom ≈ gross net (fee taken on the ascent).
        factors, cryst = _simulate_net_path([3.0, 3.0, 3.0, 3.0], 20.0, 1.0)
        self.assertEqual(cryst, 4)
        self.assertTrue(all(f > 0.0 for f in factors))

    def test_net_geom_period_constant(self):
        factors, _c = _simulate_net_path([2.0, 2.0, 2.0], 0.0, 1.0)
        gm = _net_geom_period(factors)
        self.assertAlmostEqual(gm, 0.02, places=10)

    def test_net_geom_empty_none(self):
        self.assertIsNone(_net_geom_period([]))

    def test_net_geom_nonpositive_none(self):
        self.assertIsNone(_net_geom_period([1.0, 0.0, 1.0]))


# ── perf_fee == 0 → zero volatility tax (NEUTRAL) ──────────────────────────────

class TestZeroFeeNeutral(unittest.TestCase):
    def test_zero_fee_choppy_tax_zero(self):
        r = A()._analyze_one(make_pos(
            period_returns=[10.0, -5.0, 10.0, -5.0],
            perf_fee_pct=0.0, periods_per_year=12.0))
        self.assertAlmostEqual(r["volatility_tax_pct"], 0.0, places=6)
        self.assertEqual(r["classification"], "NEUTRAL")
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE_NET")
        finite_check(self, r)

    def test_zero_fee_smooth_realised_equals_gross(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0, 2.0],
            perf_fee_pct=0.0, periods_per_year=12.0))
        self.assertAlmostEqual(
            r["realised_net_apr_pct"], r["gross_apr_pct"], places=4)
        self.assertAlmostEqual(
            r["smooth_net_apr_pct"], r["gross_apr_pct"], places=4)

    def test_zero_fee_score_full(self):
        r = A()._analyze_one(make_pos(
            period_returns=[10.0, -5.0, 10.0, -5.0],
            perf_fee_pct=0.0, periods_per_year=12.0))
        self.assertAlmostEqual(r["score"], 100.0, places=2)

    def test_omitted_fee_defaults_zero(self):
        r = A()._analyze_one(make_pos(
            period_returns=[3.0, 2.0, 4.0], periods_per_year=12.0))
        self.assertAlmostEqual(r["perf_fee_pct"], DEFAULT_PERF_FEE_PCT, places=6)
        self.assertAlmostEqual(r["volatility_tax_pct"], 0.0, places=6)

    def test_neutral_tax_flag(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0], perf_fee_pct=0.0,
            periods_per_year=12.0))
        self.assertIn("NEUTRAL_TAX", r["flags"])


# ── smooth path → tax ≈ 0 ; volatile path → tax > 0 ────────────────────────────

class TestVolatilityTax(unittest.TestCase):
    def test_smooth_equal_path_tax_near_zero(self):
        r = A()._analyze_one(make_pos(
            period_returns=[1.5, 1.5, 1.5, 1.5, 1.5, 1.5],
            perf_fee_pct=20.0, periods_per_year=12.0))
        # Smooth monotone ascent → realised net ≈ smooth net.
        self.assertLess(r["tax_fraction"], NEUTRAL_FRACTION)
        self.assertEqual(r["classification"], "NEUTRAL")

    def test_choppy_path_positive_tax(self):
        r = A()._analyze_one(make_pos(
            period_returns=[12.0, -8.0, 12.0, -8.0, 12.0, -8.0],
            perf_fee_pct=20.0, periods_per_year=12.0))
        self.assertGreater(r["volatility_tax_pct"], 0.0)
        self.assertLess(r["realisation_ratio"], 1.0)

    def test_realised_below_smooth_on_choppy(self):
        r = A()._analyze_one(make_pos(
            period_returns=[10.0, -5.0, 10.0, -5.0],
            perf_fee_pct=20.0, periods_per_year=12.0))
        self.assertLess(r["realised_net_apr_pct"], r["smooth_net_apr_pct"])

    def test_smooth_realised_below_gross(self):
        r = A()._analyze_one(make_pos(
            period_returns=[10.0, -5.0, 10.0, -5.0],
            perf_fee_pct=20.0, periods_per_year=12.0))
        self.assertLess(r["realised_net_apr_pct"], r["gross_apr_pct"])

    def test_tax_grows_with_fee(self):
        small = A()._analyze_one(make_pos(
            period_returns=[10.0, -5.0, 10.0, -5.0],
            perf_fee_pct=5.0, periods_per_year=12.0))
        big = A()._analyze_one(make_pos(
            period_returns=[10.0, -5.0, 10.0, -5.0],
            perf_fee_pct=30.0, periods_per_year=12.0))
        self.assertGreater(big["volatility_tax_pct"], small["volatility_tax_pct"])

    def test_tax_grows_with_volatility(self):
        smooth = A()._analyze_one(make_pos(
            period_returns=[3.0, 2.5, 3.0, 2.5],
            perf_fee_pct=20.0, periods_per_year=12.0))
        choppy = A()._analyze_one(make_pos(
            period_returns=[12.0, -8.0, 12.0, -8.0],
            perf_fee_pct=20.0, periods_per_year=12.0))
        self.assertGreater(
            choppy["volatility_tax_pct"], smooth["volatility_tax_pct"])

    def test_fee_drag_total_ge_volatility_tax(self):
        r = A()._analyze_one(make_pos(
            period_returns=[10.0, -5.0, 10.0, -5.0],
            perf_fee_pct=20.0, periods_per_year=12.0))
        # fee_drag_total = gross - realised >= volatility_tax = smooth - realised
        # because smooth <= gross for positive gross.
        self.assertGreaterEqual(
            r["fee_drag_total_pct"] + 1e-6, r["volatility_tax_pct"])

    def test_crystallization_count_positive_choppy(self):
        r = A()._analyze_one(make_pos(
            period_returns=[10.0, -5.0, 10.0, -5.0],
            perf_fee_pct=20.0, periods_per_year=12.0))
        self.assertGreater(r["crystallization_count"], 0)


# ── classification thresholds ───────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_neutral_override(self):
        # Near-zero approximated tax (low vol) → NEUTRAL.
        r = A()._analyze_one(make_pos(
            gross_apr_pct=20.0, perf_fee_pct=20.0, gross_return_vol_pct=0.5))
        self.assertEqual(r["classification"], "NEUTRAL")

    def test_severe_override_high_vol(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=30.0, perf_fee_pct=20.0, gross_return_vol_pct=8.0))
        self.assertEqual(r["classification"], "SEVERE_TAX")

    def test_negative_gross_severe(self):
        r = A()._analyze_one(make_pos(
            period_returns=[-2.0, -3.0, -1.0], perf_fee_pct=20.0,
            periods_per_year=12.0))
        self.assertEqual(r["classification"], "SEVERE_TAX")
        self.assertIn("NEGATIVE_GROSS", r["flags"])

    def test_classification_monotone_with_tax(self):
        # Increasing approximated tax via vol crosses class boundaries upward.
        labels = []
        for vol in (0.5, 3.0, 6.0, 12.0):
            r = A()._analyze_one(make_pos(
                gross_apr_pct=40.0, perf_fee_pct=20.0,
                gross_return_vol_pct=vol))
            labels.append(r["tax_fraction"])
        for i in range(len(labels) - 1):
            self.assertLessEqual(labels[i], labels[i + 1])

    def test_neutral_boundary_override(self):
        # tax_fraction exactly at NEUTRAL_FRACTION → NEUTRAL.
        # smooth = 100*(1-0.2)=80 ; tax = NEUTRAL_FRACTION*80 desired.
        # Choose vol so approx_tax = NEUTRAL_FRACTION * smooth.
        smooth = 100.0 * (1 - 0.20)
        target_tax = NEUTRAL_FRACTION * smooth
        # approx_tax = fee_frac * 0.5 * (vol/100)^2 * ppy * 100 ; ppy default 365
        # solve for vol
        fee_frac = 0.20
        ppy = DEFAULT_PERIODS_PER_YEAR
        var_proxy = target_tax / (fee_frac * ASYMMETRY_FACTOR * ppy * 100.0)
        vol = math.sqrt(var_proxy) * 100.0
        r = A()._analyze_one(make_pos(
            gross_apr_pct=100.0, perf_fee_pct=20.0, gross_return_vol_pct=vol))
        self.assertEqual(r["classification"], "NEUTRAL")


# ── realisation ratio / tax fraction ────────────────────────────────────────────

class TestRatios(unittest.TestCase):
    def test_realisation_ratio_bounds(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            if r["realisation_ratio"] is not None:
                self.assertGreaterEqual(r["realisation_ratio"], 0.0)
                self.assertLessEqual(r["realisation_ratio"], 1.0)

    def test_tax_fraction_bounds(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            if r["tax_fraction"] is not None:
                self.assertGreaterEqual(r["tax_fraction"], 0.0)
                self.assertLessEqual(r["tax_fraction"], 1.0)

    def test_realisation_plus_tax_complement(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=40.0, perf_fee_pct=20.0, gross_return_vol_pct=6.0))
        self.assertAlmostEqual(
            r["realisation_ratio"] + r["tax_fraction"], 1.0, places=4)

    def test_full_realisation_when_no_tax(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0], perf_fee_pct=0.0,
            periods_per_year=12.0))
        self.assertAlmostEqual(r["realisation_ratio"], 1.0, places=4)
        self.assertAlmostEqual(r["tax_fraction"], 0.0, places=4)

    def test_nonpositive_smooth_tax_zero(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=-5.0, perf_fee_pct=20.0, gross_return_vol_pct=4.0))
        self.assertEqual(r["tax_fraction"], 0.0)
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── override path ────────────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def test_override_used(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=30.0, perf_fee_pct=20.0, gross_return_vol_pct=8.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_samples"])
        self.assertIn("TAX_FROM_OVERRIDE", r["flags"])
        finite_check(self, r)

    def test_override_smooth_net_computed(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=30.0, perf_fee_pct=20.0, gross_return_vol_pct=0.0))
        self.assertAlmostEqual(r["smooth_net_apr_pct"], 24.0, places=4)

    def test_override_zero_vol_zero_tax(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=30.0, perf_fee_pct=20.0, gross_return_vol_pct=0.0))
        self.assertAlmostEqual(r["volatility_tax_pct"], 0.0, places=6)

    def test_override_missing_vol_zero_tax(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=30.0, perf_fee_pct=20.0))
        self.assertAlmostEqual(r["volatility_tax_pct"], 0.0, places=6)

    def test_override_requires_gross(self):
        r = A()._analyze_one(make_pos(perf_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_requires_fee(self):
        r = A()._analyze_one(make_pos(gross_apr_pct=30.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_bad_gross(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=float("nan"), perf_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_crystallization_none(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=30.0, perf_fee_pct=20.0, gross_return_vol_pct=4.0))
        self.assertIsNone(r["crystallization_count"])

    def test_override_negative_vol_treated_zero(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=30.0, perf_fee_pct=20.0, gross_return_vol_pct=-4.0))
        self.assertAlmostEqual(r["volatility_tax_pct"], 0.0, places=6)

    def test_override_tax_capped_at_smooth(self):
        # Huge vol → tax cannot exceed smooth net; realised floored at 0.
        r = A()._analyze_one(make_pos(
            gross_apr_pct=30.0, perf_fee_pct=20.0, gross_return_vol_pct=100.0))
        self.assertGreaterEqual(r["realised_net_apr_pct"], 0.0)
        self.assertLessEqual(
            r["volatility_tax_pct"], r["smooth_net_apr_pct"] + 1e-6)

    def test_samples_take_precedence(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0], perf_fee_pct=10.0,
            gross_apr_pct=99.0, gross_return_vol_pct=50.0))
        self.assertTrue(r["used_samples"])
        self.assertFalse(r["used_override"])


# ── insufficient data ────────────────────────────────────────────────────────────

class TestInsufficient(unittest.TestCase):
    def test_single_sample_no_override(self):
        r = A()._analyze_one(make_pos(period_returns=[2.0]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_empty_returns_no_override(self):
        r = A()._analyze_one(make_pos(period_returns=[]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_data_at_all(self):
        r = A()._analyze_one({"vault": "x"})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_dirty_samples(self):
        r = A()._analyze_one(make_pos(
            period_returns=["bad", None, float("nan")]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_geom_break_total_loss(self):
        r = A()._analyze_one(make_pos(
            period_returns=[5.0, -100.0, 3.0], periods_per_year=12.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_shape(self):
        r = A()._analyze_one(make_pos(period_returns=[2.0]))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertIsNone(r["realisation_ratio"])
        self.assertIsNone(r["tax_fraction"])
        self.assertIsNone(r["volatility_tax_pct"])
        self.assertIsNone(r["gross_apr_pct"])


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_high_volatility_tax_flag(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=40.0, perf_fee_pct=20.0, gross_return_vol_pct=10.0))
        self.assertIn("HIGH_VOLATILITY_TAX", r["flags"])

    def test_no_high_vol_tax_flag_when_low(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=40.0, perf_fee_pct=20.0, gross_return_vol_pct=0.3))
        self.assertNotIn("HIGH_VOLATILITY_TAX", r["flags"])

    def test_high_perf_fee_flag(self):
        r = A()._analyze_one(make_pos(
            period_returns=[3.0, 1.0, 4.0], perf_fee_pct=25.0,
            periods_per_year=12.0))
        self.assertIn("HIGH_PERF_FEE", r["flags"])

    def test_no_high_perf_fee_flag_when_low(self):
        r = A()._analyze_one(make_pos(
            period_returns=[3.0, 1.0, 4.0], perf_fee_pct=10.0,
            periods_per_year=12.0))
        self.assertNotIn("HIGH_PERF_FEE", r["flags"])

    def test_high_gross_vol_flag(self):
        r = A()._analyze_one(make_pos(
            period_returns=[12.0, -8.0, 12.0, -8.0], perf_fee_pct=20.0,
            periods_per_year=12.0))
        self.assertIn("HIGH_GROSS_VOL", r["flags"])

    def test_no_high_gross_vol_flag_when_smooth(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.1, 2.0, 1.9], perf_fee_pct=20.0,
            periods_per_year=12.0))
        self.assertNotIn("HIGH_GROSS_VOL", r["flags"])

    def test_negative_gross_flag(self):
        r = A()._analyze_one(make_pos(
            period_returns=[-2.0, -3.0, -1.0], perf_fee_pct=20.0,
            periods_per_year=12.0))
        self.assertIn("NEGATIVE_GROSS", r["flags"])

    def test_classification_in_flags(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=40.0, perf_fee_pct=20.0, gross_return_vol_pct=8.0))
        self.assertIn(r["classification"], r["flags"])

    def test_neutral_uses_neutral_tax_flag(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0], perf_fee_pct=0.0,
            periods_per_year=12.0))
        self.assertIn("NEUTRAL_TAX", r["flags"])
        self.assertNotIn("NEUTRAL", r["flags"])

    def test_override_has_override_flag(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=30.0, perf_fee_pct=20.0, gross_return_vol_pct=4.0))
        self.assertIn("TAX_FROM_OVERRIDE", r["flags"])

    def test_sample_path_no_override_flag(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0], perf_fee_pct=20.0,
            periods_per_year=12.0))
        self.assertNotIn("TAX_FROM_OVERRIDE", r["flags"])


# ── scoring ─────────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_neutral_high_score(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0, 2.0], perf_fee_pct=0.0,
            periods_per_year=12.0))
        self.assertGreaterEqual(r["score"], 85)

    def test_severe_low_score(self):
        r = A()._analyze_one(make_pos(
            gross_apr_pct=30.0, perf_fee_pct=20.0, gross_return_vol_pct=10.0))
        self.assertLess(r["score"], 40)

    def test_score_in_range_all_demo(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_score_monotonic_in_fee_override(self):
        a = A()._analyze_one(make_pos(
            gross_apr_pct=30.0, perf_fee_pct=5.0, gross_return_vol_pct=8.0))
        b = A()._analyze_one(make_pos(
            gross_apr_pct=30.0, perf_fee_pct=30.0, gross_return_vol_pct=8.0))
        self.assertGreater(a["score"], b["score"])

    def test_score_monotonic_in_fee_samples(self):
        small = A()._analyze_one(make_pos(
            period_returns=[10.0, -5.0, 10.0, -5.0], perf_fee_pct=5.0,
            periods_per_year=12.0))
        big = A()._analyze_one(make_pos(
            period_returns=[10.0, -5.0, 10.0, -5.0], perf_fee_pct=30.0,
            periods_per_year=12.0))
        self.assertGreater(small["score"], big["score"])

    def test_score_monotonic_in_volatility(self):
        smooth = A()._analyze_one(make_pos(
            gross_apr_pct=30.0, perf_fee_pct=20.0, gross_return_vol_pct=2.0))
        choppy = A()._analyze_one(make_pos(
            gross_apr_pct=30.0, perf_fee_pct=20.0, gross_return_vol_pct=9.0))
        self.assertGreater(smooth["score"], choppy["score"])


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
            "lowest_tax_vault", "highest_tax_vault", "avg_score",
            "negative_gross_count", "position_count",
        ):
            self.assertIn(key, agg)

    def test_aggregate_all_insufficient(self):
        out = A().analyze_portfolio([{"vault": "x"}, {"vault": "y"}])
        agg = out["aggregate"]
        self.assertIsNone(agg["lowest_tax_vault"])
        self.assertEqual(agg["avg_score"], 0.0)
        self.assertEqual(agg["position_count"], 2)

    def test_lowest_tax_has_highest_score(self):
        out = A().analyze_portfolio(_demo_positions())
        scored = [
            r for r in out["positions"]
            if r["classification"] != "INSUFFICIENT_DATA"]
        best = max(scored, key=lambda r: r["score"])
        self.assertEqual(out["aggregate"]["lowest_tax_vault"], best["token"])

    def test_highest_tax_has_lowest_score(self):
        out = A().analyze_portfolio(_demo_positions())
        scored = [
            r for r in out["positions"]
            if r["classification"] != "INSUFFICIENT_DATA"]
        worst = min(scored, key=lambda r: r["score"])
        self.assertEqual(out["aggregate"]["highest_tax_vault"], worst["token"])

    def test_negative_gross_count(self):
        positions = [
            make_pos(vault="neg", period_returns=[-2.0, -3.0, -1.0],
                     perf_fee_pct=20.0, periods_per_year=12.0),
            make_pos(vault="ok", period_returns=[2.0, 2.0, 2.0],
                     perf_fee_pct=0.0, periods_per_year=12.0),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["negative_gross_count"], 1)


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

    def test_dirty_returns_filtered(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, "bad", None, 3.0, float("nan")],
            perf_fee_pct=10.0, periods_per_year=12.0))
        self.assertEqual(r["sample_count"], 2)
        finite_check(self, r)

    def test_token_field_alias(self):
        r = A()._analyze_one({
            "token": "T1", "period_returns": [2.0, 2.0],
            "periods_per_year": 12.0})
        self.assertEqual(r["token"], "T1")

    def test_unknown_token(self):
        r = A()._analyze_one({"period_returns": [2.0, 2.0]})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_default_periods_per_year(self):
        r = A()._analyze_one({"period_returns": [2.0, 2.0]})
        self.assertAlmostEqual(r["periods_per_year"], DEFAULT_PERIODS_PER_YEAR)

    def test_invalid_ppy_falls_back(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0], periods_per_year=-5.0))
        self.assertAlmostEqual(r["periods_per_year"], DEFAULT_PERIODS_PER_YEAR)

    def test_negative_returns_valid(self):
        r = A()._analyze_one(make_pos(
            period_returns=[-2.0, -1.0, 3.0], perf_fee_pct=10.0,
            periods_per_year=12.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")
        finite_check(self, r)

    def test_fee_clamped_in_output(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0], perf_fee_pct=150.0,
            periods_per_year=12.0))
        self.assertLessEqual(r["perf_fee_pct"], 100.0)

    def test_huge_volatility_no_overflow(self):
        r = A()._analyze_one(make_pos(
            period_returns=[80.0, -40.0, 80.0, -40.0], perf_fee_pct=20.0,
            periods_per_year=365.0))
        finite_check(self, r)


# ── annualisation behavior in module ────────────────────────────────────────────

class TestAnnualisation(unittest.TestCase):
    def test_gross_apr_matches_geom_compound(self):
        returns = [2.0, 2.0, 2.0]
        r = A()._analyze_one(make_pos(
            period_returns=returns, perf_fee_pct=0.0, periods_per_year=12.0))
        expected = (1.02 ** 12 - 1) * 100.0
        self.assertAlmostEqual(r["gross_apr_pct"], expected, places=3)

    def test_higher_ppy_higher_apr_positive(self):
        low = A()._analyze_one(make_pos(
            period_returns=[1.0, 1.0, 1.0], perf_fee_pct=0.0,
            periods_per_year=12.0))
        high = A()._analyze_one(make_pos(
            period_returns=[1.0, 1.0, 1.0], perf_fee_pct=0.0,
            periods_per_year=52.0))
        self.assertGreater(high["gross_apr_pct"], low["gross_apr_pct"])


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

    def test_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for _ in range(5):
                A().analyze_portfolio(
                    _demo_positions(),
                    cfg={"log_path": path, "log_cap": 3}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

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


# ── CLI / demo validity ─────────────────────────────────────────────────────────

class TestDemo(unittest.TestCase):
    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 5)

    def test_demo_has_each_class(self):
        results = [A()._analyze_one(p) for p in _demo_positions()]
        classes = {r["classification"] for r in results}
        self.assertIn("NEUTRAL", classes)
        self.assertIn("SEVERE_TAX", classes)
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_all_keys_present(self):
        expected = set(A()._insufficient("x").keys())
        for p in _demo_positions():
            r = A()._analyze_one(p)
            self.assertEqual(set(r.keys()), expected)

    def test_demo_override_present(self):
        results = [A()._analyze_one(p) for p in _demo_positions()]
        self.assertTrue(any(r["used_override"] for r in results))

    def test_demo_determinism(self):
        first = A().analyze_portfolio(_demo_positions())["positions"]
        second = A().analyze_portfolio(_demo_positions())["positions"]
        self.assertEqual(
            [r["score"] for r in first], [r["score"] for r in second])


# ── registry integration ────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    def test_registered(self):
        from spa_core.analytics import _module_registry as reg
        names = [m["module"] for m in reg.ALL_MODULES]
        self.assertIn(
            "defi_protocol_vault_performance_fee_volatility_tax_analyzer", names)

    def test_registry_entry_fields(self):
        from spa_core.analytics import _module_registry as reg
        entry = next(
            m for m in reg.ALL_MODULES
            if m["module"]
            == "defi_protocol_vault_performance_fee_volatility_tax_analyzer")
        self.assertEqual(entry["tier"], "B")
        self.assertEqual(entry["category"], "yield_quality")
        self.assertEqual(entry["weight"], 0.5)
        self.assertEqual(
            entry["class"],
            "DeFiProtocolVaultPerformanceFeeVolatilityTaxAnalyzer")


# ── constants sanity ─────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_thresholds_ordered(self):
        self.assertLess(NEUTRAL_FRACTION, MILD_FRACTION)
        self.assertLess(MILD_FRACTION, MODERATE_FRACTION)

    def test_min_samples(self):
        self.assertEqual(MIN_SAMPLES, 2)

    def test_default_ppy(self):
        self.assertEqual(DEFAULT_PERIODS_PER_YEAR, 365.0)

    def test_default_initial_nav(self):
        self.assertEqual(DEFAULT_INITIAL_NAV, 1.0)

    def test_default_perf_fee(self):
        self.assertEqual(DEFAULT_PERF_FEE_PCT, 0.0)

    def test_high_perf_fee_positive(self):
        self.assertGreater(HIGH_PERF_FEE_PCT, 0.0)

    def test_high_gross_vol_positive(self):
        self.assertGreater(HIGH_GROSS_VOL_PCT, 0.0)

    def test_asymmetry_factor_range(self):
        self.assertGreater(ASYMMETRY_FACTOR, 0.0)
        self.assertLessEqual(ASYMMETRY_FACTOR, 1.0)

    def test_high_vol_tax_fraction(self):
        self.assertEqual(HIGH_VOL_TAX_FRACTION, MILD_FRACTION)

    def test_log_cap(self):
        self.assertEqual(LOG_CAP, 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
