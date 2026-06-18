"""
Tests for MP-1202: DeFiProtocolVaultDollarWeightedReturnGapAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_dollar_weighted_return_gap_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_dollar_weighted_return_gap_analyzer import (  # noqa: E501
    DeFiProtocolVaultDollarWeightedReturnGapAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _coerce_num,
    _coerce_returns,
    _coerce_flows,
    _pstdev,
    _geom_mean_period,
    _annualise_geom,
    _simulate_balances,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    MIN_SAMPLES,
    DEFAULT_PERIODS_PER_YEAR,
    DEFAULT_INITIAL_CAPITAL,
    ALIGNED_FRACTION,
    MILD_FRACTION,
    MODERATE_FRACTION,
    LARGE_LATE_INFLOW_FRAC,
    FLOWS_DOMINATE_MULT,
    STABLE_FLOW_CV,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    period_returns=None,
    period_flows=None,
    initial_capital=None,
    periods_per_year=None,
    twr_apr_pct=None,
    dollar_weighted_apr_pct=None,
):
    pos = {"vault": vault}
    if period_returns is not None:
        pos["period_returns"] = period_returns
    if period_flows is not None:
        pos["period_flows"] = period_flows
    if initial_capital is not None:
        pos["initial_capital"] = initial_capital
    if periods_per_year is not None:
        pos["periods_per_year"] = periods_per_year
    if twr_apr_pct is not None:
        pos["twr_apr_pct"] = twr_apr_pct
    if dollar_weighted_apr_pct is not None:
        pos["dollar_weighted_apr_pct"] = dollar_weighted_apr_pct
    return pos


def A():
    return DeFiProtocolVaultDollarWeightedReturnGapAnalyzer()


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


# ── coercion of return / flow vectors ──────────────────────────────────────────

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

    def test_flows_none_raw(self):
        self.assertIsNone(_coerce_flows(None, 3))

    def test_flows_empty_raw(self):
        self.assertIsNone(_coerce_flows([], 3))

    def test_flows_valid(self):
        self.assertEqual(_coerce_flows([1.0, -2.0, 0.0], 3), [1.0, -2.0, 0.0])

    def test_flows_length_mismatch(self):
        self.assertIsNone(_coerce_flows([1.0, 2.0], 3))

    def test_flows_bad_element_invalidates(self):
        self.assertIsNone(_coerce_flows([1.0, "x", 2.0], 3))

    def test_flows_bool_invalidates(self):
        self.assertIsNone(_coerce_flows([1.0, True, 2.0], 3))

    def test_flows_negative_allowed(self):
        self.assertEqual(_coerce_flows([-5.0, -1.0], 2), [-5.0, -1.0])


# ── geometric mean / annualisation ─────────────────────────────────────────────

class TestGeomAnnualise(unittest.TestCase):
    def test_geom_constant(self):
        gm = _geom_mean_period([2.0, 2.0, 2.0])
        self.assertAlmostEqual(gm, 0.02, places=10)

    def test_geom_empty_none(self):
        self.assertIsNone(_geom_mean_period([]))

    def test_geom_breaks_on_total_loss(self):
        # -100% return → factor 0 → geometric link undefined.
        self.assertIsNone(_geom_mean_period([5.0, -100.0]))

    def test_geom_breaks_below_minus_100(self):
        self.assertIsNone(_geom_mean_period([-150.0, 5.0]))

    def test_geom_handles_negative(self):
        gm = _geom_mean_period([10.0, -5.0])
        self.assertTrue(math.isfinite(gm))

    def test_annualise_geom_positive(self):
        # (1.02)^12 - 1 in pct
        apr = _annualise_geom(0.02, 12.0)
        self.assertAlmostEqual(apr, (1.02 ** 12 - 1) * 100.0, places=4)

    def test_annualise_geom_nonpositive_base(self):
        self.assertIsNone(_annualise_geom(-1.5, 12.0))

    def test_annualise_geom_finite(self):
        apr = _annualise_geom(0.01, 365.0)
        self.assertTrue(math.isfinite(apr))


# ── balance simulation / DWR ────────────────────────────────────────────────────

class TestSimulate(unittest.TestCase):
    def test_no_flows_capital_compounds(self):
        caps, bals, final = _simulate_balances([10.0, 10.0], None, 100.0)
        self.assertAlmostEqual(caps[0], 100.0, places=6)
        self.assertAlmostEqual(caps[1], 110.0, places=6)
        self.assertAlmostEqual(final, 121.0, places=6)

    def test_flows_added_end_of_period(self):
        caps, bals, final = _simulate_balances([0.0, 0.0], [50.0, 0.0], 100.0)
        # period 0: cap 100, return 0 → 100, +50 = 150
        self.assertAlmostEqual(caps[0], 100.0, places=6)
        self.assertAlmostEqual(caps[1], 150.0, places=6)
        self.assertAlmostEqual(final, 150.0, places=6)

    def test_negative_flow_withdraws(self):
        caps, bals, final = _simulate_balances([0.0, 0.0], [-30.0, 0.0], 100.0)
        self.assertAlmostEqual(caps[1], 70.0, places=6)

    def test_dwr_equals_mean_no_flows_constant(self):
        # Constant returns, no flows → capital-weighted mean == return.
        caps, _b, _f2 = _simulate_balances([2.0, 2.0, 2.0], None, 1.0)
        sum_cap = sum(caps)
        dwr = sum(c * r for c, r in zip(caps, [2.0, 2.0, 2.0])) / sum_cap
        self.assertAlmostEqual(dwr, 2.0, places=6)

    def test_late_inflow_lowers_dwr_when_returns_drop(self):
        returns = [5.0, 5.0, 0.0, 0.0]
        # Big inflow before the low-return periods → capital concentrated in low rs.
        flows = [0.0, 1000.0, 0.0, 0.0]
        caps, _b, _f2 = _simulate_balances(returns, flows, 10.0)
        dwr = (sum(c * r for c, r in zip(caps, returns)) / sum(caps))
        # Flow-neutral baseline
        ncaps, _nb, _nf = _simulate_balances(returns, None, 10.0)
        ndwr = (sum(c * r for c, r in zip(ncaps, returns)) / sum(ncaps))
        self.assertLess(dwr, ndwr)


# ── zero-flow → no gap (ALIGNED) ───────────────────────────────────────────────

class TestZeroFlowAligned(unittest.TestCase):
    def test_zero_flows_constant_gap_zero(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0, 2.0], periods_per_year=12.0))
        self.assertAlmostEqual(r["behavior_gap_pct"], 0.0, places=6)
        self.assertEqual(r["classification"], "ALIGNED")
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")
        finite_check(self, r)

    def test_zero_flows_varying_gap_zero(self):
        # No flows → DWR baseline equals actual DWR for ANY return path.
        r = A()._analyze_one(make_pos(
            period_returns=[5.0, 1.0, 3.0, 2.0, 4.0], periods_per_year=12.0))
        self.assertAlmostEqual(r["behavior_gap_pct"], 0.0, places=6)
        self.assertEqual(r["classification"], "ALIGNED")

    def test_zero_flows_score_full(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0, 2.0], periods_per_year=12.0))
        self.assertAlmostEqual(r["score"], 100.0, places=2)

    def test_omitted_flows_total_net_zero(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 3.0], periods_per_year=12.0))
        self.assertAlmostEqual(r["total_net_flow"], 0.0, places=6)

    def test_aligned_timing_flag(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0], periods_per_year=12.0))
        self.assertIn("ALIGNED_TIMING", r["flags"])


# ── adverse timing → positive gap ──────────────────────────────────────────────

class TestAdverseTiming(unittest.TestCase):
    def test_inflow_before_drop_positive_gap(self):
        r = A()._analyze_one(make_pos(
            period_returns=[6.0, 6.0, 0.5, 0.4],
            period_flows=[0.0, 1000.0, 0.0, 0.0],
            initial_capital=50.0, periods_per_year=12.0))
        self.assertGreater(r["behavior_gap_pct"], 0.0)
        self.assertLess(r["realization_ratio"], 1.0)

    def test_severe_gap_classification(self):
        r = A()._analyze_one(make_pos(
            period_returns=[8.0, 8.0, 0.2, 0.2, 0.2, 0.1],
            period_flows=[0.0, 0.0, 5000.0, 0.0, 0.0, 0.0],
            initial_capital=10.0, periods_per_year=12.0))
        self.assertIn(r["classification"], ("MODERATE_GAP", "SEVERE_GAP"))
        self.assertGreater(r["gap_fraction"], MILD_FRACTION)

    def test_gap_grows_with_larger_late_inflow(self):
        base_returns = [6.0, 6.0, 0.5, 0.5]
        small = A()._analyze_one(make_pos(
            period_returns=base_returns,
            period_flows=[0.0, 50.0, 0.0, 0.0],
            initial_capital=100.0, periods_per_year=12.0))
        big = A()._analyze_one(make_pos(
            period_returns=base_returns,
            period_flows=[0.0, 5000.0, 0.0, 0.0],
            initial_capital=100.0, periods_per_year=12.0))
        self.assertGreater(big["gap_fraction"], small["gap_fraction"])

    def test_aligned_flow_no_gap(self):
        # An inflow before a HIGH-return period helps the depositor (no positive gap
        # against the neutral baseline → still aligned / negative gap clamped).
        r = A()._analyze_one(make_pos(
            period_returns=[0.5, 0.5, 6.0, 6.0],
            period_flows=[0.0, 1000.0, 0.0, 0.0],
            initial_capital=50.0, periods_per_year=12.0))
        # Depositor realises >= baseline → gap_fraction clamped to 0 → ALIGNED.
        self.assertEqual(r["classification"], "ALIGNED")


# ── classification thresholds ───────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_aligned_override(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=20.0, dollar_weighted_apr_pct=19.5))
        self.assertEqual(r["classification"], "ALIGNED")

    def test_mild_override(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=20.0, dollar_weighted_apr_pct=17.0))
        self.assertEqual(r["classification"], "MILD_GAP")

    def test_moderate_override(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=20.0, dollar_weighted_apr_pct=12.0))
        self.assertEqual(r["classification"], "MODERATE_GAP")

    def test_severe_override(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=20.0, dollar_weighted_apr_pct=5.0))
        self.assertEqual(r["classification"], "SEVERE_GAP")

    def test_negative_depositor_return_severe(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=20.0, dollar_weighted_apr_pct=-3.0))
        self.assertEqual(r["classification"], "SEVERE_GAP")
        self.assertIn("DEPOSITOR_RETURN_NEGATIVE", r["flags"])

    def test_aligned_boundary(self):
        # gap_fraction exactly at ALIGNED_FRACTION → ALIGNED.
        r = A()._analyze_one(make_pos(
            twr_apr_pct=100.0,
            dollar_weighted_apr_pct=100.0 * (1 - ALIGNED_FRACTION)))
        self.assertEqual(r["classification"], "ALIGNED")

    def test_mild_boundary(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=100.0,
            dollar_weighted_apr_pct=100.0 * (1 - MILD_FRACTION)))
        self.assertEqual(r["classification"], "MILD_GAP")

    def test_moderate_boundary(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=100.0,
            dollar_weighted_apr_pct=100.0 * (1 - MODERATE_FRACTION)))
        self.assertEqual(r["classification"], "MODERATE_GAP")


# ── realization ratio / gap fraction ────────────────────────────────────────────

class TestRatios(unittest.TestCase):
    def test_realization_ratio_bounds(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            if r["realization_ratio"] is not None:
                self.assertGreaterEqual(r["realization_ratio"], 0.0)
                self.assertLessEqual(r["realization_ratio"], 1.0)

    def test_gap_fraction_bounds(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            if r["gap_fraction"] is not None:
                self.assertGreaterEqual(r["gap_fraction"], 0.0)
                self.assertLessEqual(r["gap_fraction"], 1.0)

    def test_realization_plus_gap_complement(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=20.0, dollar_weighted_apr_pct=14.0))
        self.assertAlmostEqual(
            r["realization_ratio"] + r["gap_fraction"], 1.0, places=4)

    def test_full_realization_ratio_one(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=20.0, dollar_weighted_apr_pct=20.0))
        self.assertAlmostEqual(r["realization_ratio"], 1.0, places=6)
        self.assertAlmostEqual(r["gap_fraction"], 0.0, places=6)

    def test_dwr_above_baseline_clamped(self):
        # DWR > baseline → realization clamped to 1, gap clamped to 0.
        r = A()._analyze_one(make_pos(
            twr_apr_pct=20.0, dollar_weighted_apr_pct=25.0))
        self.assertAlmostEqual(r["realization_ratio"], 1.0, places=6)
        self.assertAlmostEqual(r["gap_fraction"], 0.0, places=6)

    def test_nonpositive_baseline_gap_zero(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=-5.0, dollar_weighted_apr_pct=-6.0))
        self.assertEqual(r["gap_fraction"], 0.0)
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── override path ────────────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def test_override_both_used(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=30.0, dollar_weighted_apr_pct=18.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_samples"])
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])
        self.assertAlmostEqual(r["behavior_gap_pct"], 12.0, places=4)
        finite_check(self, r)

    def test_override_requires_both_twr_only(self):
        r = A()._analyze_one(make_pos(twr_apr_pct=30.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_requires_both_dwr_only(self):
        r = A()._analyze_one(make_pos(dollar_weighted_apr_pct=18.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_bad_twr(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=float("nan"), dollar_weighted_apr_pct=18.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_sample_metrics_none(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=30.0, dollar_weighted_apr_pct=18.0))
        self.assertIsNone(r["twr_period_pct"])
        self.assertIsNone(r["dwr_period_pct"])
        self.assertIsNone(r["total_net_flow"])
        self.assertIsNone(r["flow_volatility"])
        self.assertIsNone(r["peak_capital"])

    def test_override_no_sample_flags(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=30.0, dollar_weighted_apr_pct=5.0))
        for sample_flag in (
            "CHASING_DETECTED", "LARGE_LATE_INFLOW", "FLOWS_DOMINATE",
            "STABLE_FLOWS",
        ):
            self.assertNotIn(sample_flag, r["flags"])

    def test_override_stability_neutral_high_score_when_realised(self):
        # Full realisation on override path → score should be 100 (stability neutral).
        r = A()._analyze_one(make_pos(
            twr_apr_pct=20.0, dollar_weighted_apr_pct=20.0))
        self.assertAlmostEqual(r["score"], 100.0, places=2)

    def test_samples_take_precedence_over_override(self):
        # With >= MIN_SAMPLES returns, the sample path is used, not the override.
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0],
            twr_apr_pct=99.0, dollar_weighted_apr_pct=1.0))
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

    def test_explicit_zero_capital_no_inflow(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 3.0], initial_capital=0.0,
            period_flows=[0.0, 0.0], periods_per_year=12.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_explicit_zero_capital_with_inflow_ok(self):
        # Zero capital but a positive inflow bootstraps the balance → valid.
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 3.0], initial_capital=0.0,
            period_flows=[100.0, 0.0], periods_per_year=12.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_shape(self):
        r = A()._analyze_one(make_pos(period_returns=[2.0]))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertIsNone(r["realization_ratio"])
        self.assertIsNone(r["gap_fraction"])
        self.assertIsNone(r["behavior_gap_pct"])


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_chasing_detected(self):
        # Inflows precede below-mean returns.
        r = A()._analyze_one(make_pos(
            period_returns=[6.0, 0.2, 6.0, 0.2, 6.0, 0.2],
            period_flows=[100.0, 0.0, 100.0, 0.0, 100.0, 0.0],
            initial_capital=10.0, periods_per_year=12.0))
        self.assertIn("CHASING_DETECTED", r["flags"])

    def test_no_chasing_when_inflows_precede_high(self):
        r = A()._analyze_one(make_pos(
            period_returns=[0.2, 6.0, 0.2, 6.0, 0.2, 6.0],
            period_flows=[100.0, 0.0, 100.0, 0.0, 100.0, 0.0],
            initial_capital=10.0, periods_per_year=12.0))
        self.assertNotIn("CHASING_DETECTED", r["flags"])

    def test_large_late_inflow_flag(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0, 2.0],
            period_flows=[0.0, 0.0, 0.0, 1000.0],
            initial_capital=100.0, periods_per_year=12.0))
        self.assertIn("LARGE_LATE_INFLOW", r["flags"])

    def test_no_large_late_inflow_when_early(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0, 2.0],
            period_flows=[1000.0, 0.0, 0.0, 0.0],
            initial_capital=100.0, periods_per_year=12.0))
        self.assertNotIn("LARGE_LATE_INFLOW", r["flags"])

    def test_flows_dominate_flag(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0],
            period_flows=[0.0, 1000.0, 0.0],
            initial_capital=10.0, periods_per_year=12.0))
        self.assertIn("FLOWS_DOMINATE", r["flags"])

    def test_stable_flows_flag(self):
        r = A()._analyze_one(make_pos(
            period_returns=[1.5, 1.5, 1.5, 1.5],
            period_flows=[10.0, 10.0, 10.0, 10.0],
            initial_capital=100.0, periods_per_year=12.0))
        self.assertIn("STABLE_FLOWS", r["flags"])

    def test_depositor_return_negative_flag(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=20.0, dollar_weighted_apr_pct=-2.0))
        self.assertIn("DEPOSITOR_RETURN_NEGATIVE", r["flags"])

    def test_classification_in_flags(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=20.0, dollar_weighted_apr_pct=12.0))
        self.assertIn(r["classification"], r["flags"])

    def test_aligned_uses_aligned_timing_flag(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=20.0, dollar_weighted_apr_pct=20.0))
        self.assertIn("ALIGNED_TIMING", r["flags"])
        self.assertNotIn("ALIGNED", r["flags"])


# ── scoring ─────────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_aligned_high_score(self):
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0, 2.0], periods_per_year=12.0))
        self.assertGreaterEqual(r["score"], 85)

    def test_severe_low_score(self):
        r = A()._analyze_one(make_pos(
            twr_apr_pct=20.0, dollar_weighted_apr_pct=-5.0))
        self.assertLess(r["score"], 40)

    def test_score_in_range_all_demo(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_score_monotonic_in_gap_override(self):
        a = A()._analyze_one(make_pos(
            twr_apr_pct=20.0, dollar_weighted_apr_pct=18.0))
        b = A()._analyze_one(make_pos(
            twr_apr_pct=20.0, dollar_weighted_apr_pct=10.0))
        self.assertGreater(a["score"], b["score"])

    def test_score_monotonic_in_gap_samples(self):
        small = A()._analyze_one(make_pos(
            period_returns=[6.0, 6.0, 1.0, 1.0],
            period_flows=[0.0, 20.0, 0.0, 0.0],
            initial_capital=100.0, periods_per_year=12.0))
        big = A()._analyze_one(make_pos(
            period_returns=[6.0, 6.0, 1.0, 1.0],
            period_flows=[0.0, 5000.0, 0.0, 0.0],
            initial_capital=100.0, periods_per_year=12.0))
        self.assertGreater(small["score"], big["score"])


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
            "most_aligned_vault", "widest_gap_vault", "avg_score",
            "negative_depositor_count", "position_count",
        ):
            self.assertIn(key, agg)

    def test_aggregate_all_insufficient(self):
        out = A().analyze_portfolio([{"vault": "x"}, {"vault": "y"}])
        agg = out["aggregate"]
        self.assertIsNone(agg["most_aligned_vault"])
        self.assertEqual(agg["avg_score"], 0.0)
        self.assertEqual(agg["position_count"], 2)

    def test_most_aligned_has_highest_score(self):
        out = A().analyze_portfolio(_demo_positions())
        scored = [
            r for r in out["positions"]
            if r["classification"] != "INSUFFICIENT_DATA"]
        best = max(scored, key=lambda r: r["score"])
        self.assertEqual(
            out["aggregate"]["most_aligned_vault"], best["token"])

    def test_widest_gap_has_lowest_score(self):
        out = A().analyze_portfolio(_demo_positions())
        scored = [
            r for r in out["positions"]
            if r["classification"] != "INSUFFICIENT_DATA"]
        worst = min(scored, key=lambda r: r["score"])
        self.assertEqual(
            out["aggregate"]["widest_gap_vault"], worst["token"])

    def test_negative_depositor_count(self):
        positions = [
            make_pos(vault="neg", twr_apr_pct=20.0, dollar_weighted_apr_pct=-3.0),
            make_pos(vault="ok", twr_apr_pct=20.0, dollar_weighted_apr_pct=19.0),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["negative_depositor_count"], 1)


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
            periods_per_year=12.0))
        self.assertEqual(r["sample_count"], 2)
        finite_check(self, r)

    def test_flow_length_mismatch_treated_zero(self):
        # Mismatched flows are dropped → behaves as zero-flow (ALIGNED).
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0, 2.0],
            period_flows=[10.0, 10.0],  # wrong length
            periods_per_year=12.0))
        self.assertAlmostEqual(r["total_net_flow"], 0.0, places=6)
        self.assertEqual(r["classification"], "ALIGNED")

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

    def test_default_initial_capital_used(self):
        # Flows given, no initial_capital → default 1.0 base.
        r = A()._analyze_one(make_pos(
            period_returns=[2.0, 2.0],
            period_flows=[1.0, 1.0], periods_per_year=12.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_returns_valid(self):
        r = A()._analyze_one(make_pos(
            period_returns=[-2.0, -1.0, 3.0], periods_per_year=12.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")
        finite_check(self, r)


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


# ── CLI / demo validity ─────────────────────────────────────────────────────────

class TestDemo(unittest.TestCase):
    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 5)

    def test_demo_has_each_class(self):
        results = [A()._analyze_one(p) for p in _demo_positions()]
        classes = {r["classification"] for r in results}
        self.assertIn("ALIGNED", classes)
        self.assertIn("SEVERE_GAP", classes)
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_all_keys_present(self):
        expected = set(A()._insufficient("x").keys())
        for p in _demo_positions():
            r = A()._analyze_one(p)
            self.assertEqual(set(r.keys()), expected)

    def test_demo_override_present(self):
        results = [A()._analyze_one(p) for p in _demo_positions()]
        self.assertTrue(any(r["used_override"] for r in results))


# ── registry integration ────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    def test_registered(self):
        from spa_core.analytics import _module_registry as reg
        names = [m["module"] for m in reg.ALL_MODULES]
        self.assertIn(
            "defi_protocol_vault_dollar_weighted_return_gap_analyzer", names)

    def test_registry_entry_fields(self):
        from spa_core.analytics import _module_registry as reg
        entry = next(
            m for m in reg.ALL_MODULES
            if m["module"]
            == "defi_protocol_vault_dollar_weighted_return_gap_analyzer")
        self.assertEqual(entry["tier"], "B")
        self.assertEqual(entry["category"], "yield_quality")
        self.assertEqual(entry["weight"], 0.5)
        self.assertEqual(
            entry["class"],
            "DeFiProtocolVaultDollarWeightedReturnGapAnalyzer")


# ── constants sanity ─────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_thresholds_ordered(self):
        self.assertLess(ALIGNED_FRACTION, MILD_FRACTION)
        self.assertLess(MILD_FRACTION, MODERATE_FRACTION)

    def test_min_samples(self):
        self.assertEqual(MIN_SAMPLES, 2)

    def test_default_ppy(self):
        self.assertEqual(DEFAULT_PERIODS_PER_YEAR, 365.0)

    def test_default_initial_capital(self):
        self.assertEqual(DEFAULT_INITIAL_CAPITAL, 1.0)

    def test_large_late_inflow_frac(self):
        self.assertGreater(LARGE_LATE_INFLOW_FRAC, 0.0)
        self.assertLessEqual(LARGE_LATE_INFLOW_FRAC, 1.0)

    def test_flows_dominate_mult(self):
        self.assertGreater(FLOWS_DOMINATE_MULT, 1.0)

    def test_stable_flow_cv_positive(self):
        self.assertGreater(STABLE_FLOW_CV, 0.0)

    def test_log_cap(self):
        self.assertEqual(LOG_CAP, 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
