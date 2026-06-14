"""
Tests for MP-1154: DeFiProtocolDepositCapHeadroomAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_deposit_cap_headroom_analyzer -v
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

from spa_core.analytics.defi_protocol_deposit_cap_headroom_analyzer import (
    DeFiProtocolDepositCapHeadroomAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DAYS_SENTINEL_NEVER,
    PCT_SENTINEL_MAX,
    NEAR_CAP_PCT,
    CAP_REACHED_PCT,
    TIGHT_HEADROOM_PCT,
    AMPLE_HEADROOM_PCT,
    FAST_FILL_DAYS,
    DILUTION_RISK_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    deposit_cap_usd=100_000_000.0,
    current_tvl_usd=25_000_000.0,
    intended_deposit_usd=0.0,
    recent_inflow_usd_7d=0.0,
    cap_is_hard=True,
    base_apy_pct=8.0,
):
    return {
        "vault": vault,
        "deposit_cap_usd": deposit_cap_usd,
        "current_tvl_usd": current_tvl_usd,
        "intended_deposit_usd": intended_deposit_usd,
        "recent_inflow_usd_7d": recent_inflow_usd_7d,
        "cap_is_hard": cap_is_hard,
        "base_apy_pct": base_apy_pct,
    }


def A():
    return DeFiProtocolDepositCapHeadroomAnalyzer()


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

    def test_clamp_within(self):
        self.assertEqual(_clamp(5, 0, 10), 5)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1, 0, 10), 0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(11, 0, 10), 10)

    def test_clamp_exact_bounds(self):
        self.assertEqual(_clamp(0, 0, 10), 0)
        self.assertEqual(_clamp(10, 0, 10), 10)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertAlmostEqual(_mean([2, 4, 6]), 4.0)

    def test_mean_single(self):
        self.assertAlmostEqual(_mean([8.0]), 8.0)

    def test_safe_div_normal(self):
        self.assertAlmostEqual(_safe_div(10, 2, 1e9), 5.0)

    def test_safe_div_zero_denominator(self):
        self.assertEqual(_safe_div(10, 0, 1e9), 1e9)

    def test_safe_div_negative_denominator(self):
        self.assertEqual(_safe_div(10, -5, 7.0), 7.0)

    def test_build_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg["log_cap"], 5)
        self.assertEqual(cfg["log_path"], LOG_PATH)

    def test_build_default_cfg_none(self):
        cfg = _build_default_cfg(None)
        self.assertIn("log_path", cfg)

    def test_grade_from_score_bands(self):
        self.assertEqual(_grade_from_score(90), "A")
        self.assertEqual(_grade_from_score(72), "B")
        self.assertEqual(_grade_from_score(60), "C")
        self.assertEqual(_grade_from_score(45), "D")
        self.assertEqual(_grade_from_score(10), "F")

    def test_grade_boundaries(self):
        self.assertEqual(_grade_from_score(85), "A")
        self.assertEqual(_grade_from_score(70), "B")
        self.assertEqual(_grade_from_score(55), "C")
        self.assertEqual(_grade_from_score(40), "D")
        self.assertEqual(_grade_from_score(39.9), "F")

    def test_constants_sane(self):
        self.assertGreater(DAYS_SENTINEL_NEVER, 0)
        self.assertGreater(PCT_SENTINEL_MAX, 0)
        self.assertEqual(CAP_REACHED_PCT, 100.0)
        self.assertGreater(NEAR_CAP_PCT, TIGHT_HEADROOM_PCT)
        self.assertGreater(TIGHT_HEADROOM_PCT, AMPLE_HEADROOM_PCT)
        self.assertGreater(FAST_FILL_DAYS, 0)
        self.assertGreater(DILUTION_RISK_PCT, 0)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "deposit_cap_usd", "current_tvl_usd", "cap_utilization_pct",
            "remaining_headroom_usd", "intended_deposit_usd", "intended_fits",
            "fillable_pct_of_intended", "days_to_cap_at_current_inflow",
            "projected_dilution_pct", "cap_is_hard", "headroom_score",
            "classification", "recommendation", "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_score_in_range(self):
        self.assertGreaterEqual(self.r["headroom_score"], 0.0)
        self.assertLessEqual(self.r["headroom_score"], 100.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_preserved(self):
        self.assertEqual(self.r["token"], "USDC-Vault")

    def test_token_field_alias(self):
        r = A().analyze({"token": "AltKey", "deposit_cap_usd": 1e6,
                         "current_tvl_usd": 1e5})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T", "deposit_cap_usd": 1e6,
                         "current_tvl_usd": 1e5})
        self.assertEqual(r["token"], "V")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        for v in self.r.values():
            if isinstance(v, float):
                self.assertFalse(math.isinf(v))
                self.assertFalse(math.isnan(v))

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"],
                      {"DEPLOY", "DEPLOY_PARTIAL", "WAIT_OR_SKIP"})

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_utilization_basic(self):
        # 25M / 100M = 25%
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=25_000_000.0))
        self.assertAlmostEqual(r["cap_utilization_pct"], 25.0)

    def test_utilization_full(self):
        r = A().analyze(make_pos(deposit_cap_usd=10_000_000.0,
                                 current_tvl_usd=10_000_000.0))
        self.assertAlmostEqual(r["cap_utilization_pct"], 100.0)

    def test_utilization_over_cap(self):
        r = A().analyze(make_pos(deposit_cap_usd=10_000_000.0,
                                 current_tvl_usd=12_000_000.0))
        self.assertAlmostEqual(r["cap_utilization_pct"], 120.0)

    def test_remaining_headroom_basic(self):
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=25_000_000.0))
        self.assertAlmostEqual(r["remaining_headroom_usd"], 75_000_000.0)

    def test_remaining_headroom_zero_when_full(self):
        r = A().analyze(make_pos(deposit_cap_usd=10_000_000.0,
                                 current_tvl_usd=10_000_000.0))
        self.assertAlmostEqual(r["remaining_headroom_usd"], 0.0)

    def test_remaining_headroom_zero_when_over(self):
        r = A().analyze(make_pos(deposit_cap_usd=10_000_000.0,
                                 current_tvl_usd=15_000_000.0))
        self.assertAlmostEqual(r["remaining_headroom_usd"], 0.0)

    def test_intended_fits_true(self):
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=25_000_000.0,
                                 intended_deposit_usd=1_000_000.0))
        self.assertTrue(r["intended_fits"])

    def test_intended_fits_false(self):
        r = A().analyze(make_pos(deposit_cap_usd=30_000_000.0,
                                 current_tvl_usd=29_000_000.0,
                                 intended_deposit_usd=5_000_000.0))
        self.assertFalse(r["intended_fits"])

    def test_fillable_pct_full_when_fits(self):
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=25_000_000.0,
                                 intended_deposit_usd=1_000_000.0))
        self.assertAlmostEqual(r["fillable_pct_of_intended"], 100.0)

    def test_fillable_pct_partial(self):
        # headroom 1M, intended 4M → 25%
        r = A().analyze(make_pos(deposit_cap_usd=30_000_000.0,
                                 current_tvl_usd=29_000_000.0,
                                 intended_deposit_usd=4_000_000.0))
        self.assertAlmostEqual(r["fillable_pct_of_intended"], 25.0)

    def test_fillable_pct_zero_when_full(self):
        r = A().analyze(make_pos(deposit_cap_usd=10_000_000.0,
                                 current_tvl_usd=10_000_000.0,
                                 intended_deposit_usd=1_000_000.0))
        self.assertAlmostEqual(r["fillable_pct_of_intended"], 0.0)

    def test_fillable_pct_full_when_no_intended(self):
        r = A().analyze(make_pos(intended_deposit_usd=0.0))
        self.assertAlmostEqual(r["fillable_pct_of_intended"], 100.0)

    def test_days_to_cap_basic(self):
        # headroom 7M, inflow 7d = 7M → 1M/day → 7 days
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=93_000_000.0,
                                 recent_inflow_usd_7d=7_000_000.0))
        self.assertAlmostEqual(r["days_to_cap_at_current_inflow"], 7.0)

    def test_days_to_cap_none_when_no_inflow(self):
        r = A().analyze(make_pos(recent_inflow_usd_7d=0.0))
        self.assertIsNone(r["days_to_cap_at_current_inflow"])

    def test_days_to_cap_zero_when_already_full(self):
        r = A().analyze(make_pos(deposit_cap_usd=10_000_000.0,
                                 current_tvl_usd=10_000_000.0,
                                 recent_inflow_usd_7d=1_000_000.0))
        self.assertAlmostEqual(r["days_to_cap_at_current_inflow"], 0.0)

    def test_projected_dilution_positive(self):
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=10_000_000.0,
                                 recent_inflow_usd_7d=10_000_000.0,
                                 base_apy_pct=10.0))
        # fresh 10M / (10M+10M) = 0.5 * 10% = 5%
        self.assertAlmostEqual(r["projected_dilution_pct"], 5.0)

    def test_projected_dilution_zero_when_no_inflow(self):
        r = A().analyze(make_pos(recent_inflow_usd_7d=0.0, base_apy_pct=10.0))
        self.assertAlmostEqual(r["projected_dilution_pct"], 0.0)

    def test_projected_dilution_zero_when_no_apy(self):
        r = A().analyze(make_pos(recent_inflow_usd_7d=10_000_000.0,
                                 base_apy_pct=0.0))
        self.assertAlmostEqual(r["projected_dilution_pct"], 0.0)

    def test_negative_intended_treated_as_zero(self):
        r = A().analyze(make_pos(intended_deposit_usd=-1000.0))
        self.assertAlmostEqual(r["intended_deposit_usd"], 0.0)

    def test_negative_inflow_treated_as_zero(self):
        r = A().analyze(make_pos(recent_inflow_usd_7d=-500.0))
        self.assertIsNone(r["days_to_cap_at_current_inflow"])

    def test_cap_is_hard_preserved(self):
        r = A().analyze(make_pos(cap_is_hard=False))
        self.assertFalse(r["cap_is_hard"])


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_ample_headroom(self):
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=20_000_000.0))
        self.assertEqual(r["classification"], "AMPLE_HEADROOM")

    def test_moderate_headroom(self):
        # 50% util
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=50_000_000.0))
        self.assertEqual(r["classification"], "MODERATE_HEADROOM")

    def test_tight_headroom(self):
        # 80% util
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=80_000_000.0))
        self.assertEqual(r["classification"], "TIGHT_HEADROOM")

    def test_cap_reached(self):
        r = A().analyze(make_pos(deposit_cap_usd=10_000_000.0,
                                 current_tvl_usd=10_000_000.0))
        self.assertEqual(r["classification"], "CAP_REACHED")

    def test_cap_exceeded_is_cap_reached(self):
        r = A().analyze(make_pos(deposit_cap_usd=10_000_000.0,
                                 current_tvl_usd=12_000_000.0))
        self.assertEqual(r["classification"], "CAP_REACHED")

    def test_classification_known_value(self):
        for pos in [make_pos(), make_pos(current_tvl_usd=80_000_000.0),
                    make_pos(deposit_cap_usd=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "AMPLE_HEADROOM", "MODERATE_HEADROOM", "TIGHT_HEADROOM",
                "CAP_REACHED", "INSUFFICIENT_DATA",
            })

    def test_boundary_ample_to_moderate(self):
        # exactly 40% → MODERATE (>=40)
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=40_000_000.0))
        self.assertEqual(r["classification"], "MODERATE_HEADROOM")

    def test_boundary_moderate_to_tight(self):
        # exactly 75% → TIGHT (>=75)
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=75_000_000.0))
        self.assertEqual(r["classification"], "TIGHT_HEADROOM")


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_deploy_when_ample_no_intended(self):
        r = A().analyze(make_pos(current_tvl_usd=20_000_000.0,
                                 intended_deposit_usd=0.0))
        self.assertEqual(r["recommendation"], "DEPLOY")

    def test_deploy_when_intended_fits(self):
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=25_000_000.0,
                                 intended_deposit_usd=1_000_000.0))
        self.assertEqual(r["recommendation"], "DEPLOY")

    def test_deploy_partial_when_partial_fit(self):
        r = A().analyze(make_pos(deposit_cap_usd=30_000_000.0,
                                 current_tvl_usd=29_000_000.0,
                                 intended_deposit_usd=5_000_000.0))
        self.assertEqual(r["recommendation"], "DEPLOY_PARTIAL")

    def test_wait_or_skip_when_cap_reached(self):
        r = A().analyze(make_pos(deposit_cap_usd=10_000_000.0,
                                 current_tvl_usd=10_000_000.0,
                                 intended_deposit_usd=1_000_000.0))
        self.assertEqual(r["recommendation"], "WAIT_OR_SKIP")

    def test_wait_or_skip_when_tight_no_intended(self):
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=80_000_000.0,
                                 intended_deposit_usd=0.0))
        self.assertEqual(r["recommendation"], "WAIT_OR_SKIP")

    def test_wait_or_skip_when_insufficient(self):
        r = A().analyze(make_pos(deposit_cap_usd=0.0))
        self.assertEqual(r["recommendation"], "WAIT_OR_SKIP")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_ample_headroom_flag(self):
        r = A().analyze(make_pos(current_tvl_usd=20_000_000.0))
        self.assertIn("AMPLE_HEADROOM", r["flags"])

    def test_near_cap_flag(self):
        # 92% util
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=92_000_000.0))
        self.assertIn("NEAR_CAP", r["flags"])

    def test_near_cap_absent_when_full(self):
        # at cap → CAP_REACHED not NEAR_CAP
        r = A().analyze(make_pos(deposit_cap_usd=10_000_000.0,
                                 current_tvl_usd=10_000_000.0))
        self.assertNotIn("NEAR_CAP", r["flags"])
        self.assertIn("CAP_REACHED", r["flags"])

    def test_cap_reached_flag(self):
        r = A().analyze(make_pos(deposit_cap_usd=10_000_000.0,
                                 current_tvl_usd=10_000_000.0))
        self.assertIn("CAP_REACHED", r["flags"])

    def test_intended_fits_flag(self):
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=25_000_000.0,
                                 intended_deposit_usd=1_000_000.0))
        self.assertIn("INTENDED_FITS", r["flags"])

    def test_intended_exceeds_flag(self):
        r = A().analyze(make_pos(deposit_cap_usd=30_000_000.0,
                                 current_tvl_usd=29_000_000.0,
                                 intended_deposit_usd=5_000_000.0))
        self.assertIn("INTENDED_EXCEEDS_HEADROOM", r["flags"])

    def test_no_intended_flag_when_zero(self):
        r = A().analyze(make_pos(intended_deposit_usd=0.0))
        self.assertNotIn("INTENDED_FITS", r["flags"])
        self.assertNotIn("INTENDED_EXCEEDS_HEADROOM", r["flags"])

    def test_fast_filling_flag(self):
        # headroom 3.5M, inflow 7M/7d → 1M/day → 3.5 days <= 7
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=96_500_000.0,
                                 recent_inflow_usd_7d=7_000_000.0))
        self.assertIn("FAST_FILLING", r["flags"])

    def test_fast_filling_absent_when_slow(self):
        # huge headroom, small inflow
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=20_000_000.0,
                                 recent_inflow_usd_7d=100_000.0))
        self.assertNotIn("FAST_FILLING", r["flags"])

    def test_fast_filling_absent_when_no_inflow(self):
        r = A().analyze(make_pos(recent_inflow_usd_7d=0.0))
        self.assertNotIn("FAST_FILLING", r["flags"])

    def test_hard_cap_flag(self):
        r = A().analyze(make_pos(cap_is_hard=True))
        self.assertIn("HARD_CAP", r["flags"])
        self.assertNotIn("SOFT_CAP", r["flags"])

    def test_soft_cap_flag(self):
        r = A().analyze(make_pos(cap_is_hard=False))
        self.assertIn("SOFT_CAP", r["flags"])
        self.assertNotIn("HARD_CAP", r["flags"])

    def test_dilution_risk_flag(self):
        # fresh 10M / (10M+10M) = 0.5 * 10% = 5% >= 3
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=10_000_000.0,
                                 recent_inflow_usd_7d=10_000_000.0,
                                 base_apy_pct=10.0))
        self.assertIn("DILUTION_RISK", r["flags"])

    def test_dilution_risk_absent_when_low(self):
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=90_000_000.0,
                                 recent_inflow_usd_7d=100_000.0,
                                 base_apy_pct=5.0))
        self.assertNotIn("DILUTION_RISK", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_zero_cap(self):
        r = A().analyze(make_pos(deposit_cap_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_negative_cap(self):
        r = A().analyze(make_pos(deposit_cap_usd=-100.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_tvl(self):
        r = A().analyze(make_pos(current_tvl_usd=-100.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(deposit_cap_usd=0.0))
        self.assertEqual(r["headroom_score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_sentinels_none(self):
        r = A().analyze(make_pos(deposit_cap_usd=0.0))
        self.assertIsNone(r["days_to_cap_at_current_inflow"])

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(deposit_cap_usd=0.0))
        self.assertEqual(r["recommendation"], "WAIT_OR_SKIP")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_zero_tvl_is_ample(self):
        # zero tvl with valid cap → 0% util → ample, not insufficient
        r = A().analyze(make_pos(deposit_cap_usd=10_000_000.0,
                                 current_tvl_usd=0.0))
        self.assertEqual(r["classification"], "AMPLE_HEADROOM")


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_more_headroom_scores_higher(self):
        low_util = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                        current_tvl_usd=10_000_000.0))
        high_util = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                         current_tvl_usd=90_000_000.0))
        self.assertGreater(low_util["headroom_score"],
                           high_util["headroom_score"])

    def test_intended_fits_scores_higher(self):
        fits = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                    current_tvl_usd=50_000_000.0,
                                    intended_deposit_usd=1_000_000.0))
        no_fit = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                      current_tvl_usd=50_000_000.0,
                                      intended_deposit_usd=60_000_000.0))
        self.assertGreater(fits["headroom_score"], no_fit["headroom_score"])

    def test_soft_cap_scores_higher(self):
        hard = A().analyze(make_pos(cap_is_hard=True))
        soft = A().analyze(make_pos(cap_is_hard=False))
        self.assertGreater(soft["headroom_score"], hard["headroom_score"])

    def test_slow_fill_scores_higher(self):
        slow = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                    current_tvl_usd=20_000_000.0,
                                    recent_inflow_usd_7d=100_000.0))
        fast = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                    current_tvl_usd=20_000_000.0,
                                    recent_inflow_usd_7d=80_000_000.0))
        self.assertGreater(slow["headroom_score"], fast["headroom_score"])

    def test_cap_reached_scores_low(self):
        r = A().analyze(make_pos(deposit_cap_usd=10_000_000.0,
                                 current_tvl_usd=10_000_000.0))
        self.assertLess(r["headroom_score"], 55.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(deposit_cap_usd=1e15,
                                 current_tvl_usd=0.0,
                                 cap_is_hard=False))
        self.assertLessEqual(r["headroom_score"], 100.0)
        self.assertGreaterEqual(r["headroom_score"], 0.0)

    def test_empty_vault_scores_well(self):
        r = A().analyze(make_pos(deposit_cap_usd=100_000_000.0,
                                 current_tvl_usd=0.0,
                                 cap_is_hard=False))
        self.assertGreater(r["headroom_score"], 70.0)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Ample", deposit_cap_usd=100_000_000.0,
                     current_tvl_usd=10_000_000.0, cap_is_hard=False),
            make_pos(vault="Full", deposit_cap_usd=10_000_000.0,
                     current_tvl_usd=10_000_000.0),
            make_pos(vault="Mid", deposit_cap_usd=100_000_000.0,
                     current_tvl_usd=60_000_000.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_headroom_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["headroom_score"]
                  for p in self.res["positions"]}
        most = agg["most_headroom_vault"]
        self.assertEqual(scores[most], max(scores.values()))

    def test_least_headroom_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["headroom_score"]
                  for p in self.res["positions"]}
        least = agg["least_headroom_vault"]
        self.assertEqual(scores[least], min(scores.values()))

    def test_most_headroom_is_ample(self):
        self.assertEqual(self.res["aggregate"]["most_headroom_vault"], "Ample")

    def test_cap_reached_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["cap_reached_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_headroom_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_headroom_vault"])
        self.assertIsNone(res["aggregate"]["least_headroom_vault"])

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(deposit_cap_usd=0.0), make_pos(current_tvl_usd=-1.0),
        ])
        self.assertIsNone(res["aggregate"]["most_headroom_vault"])
        self.assertEqual(res["aggregate"]["avg_headroom_score"], 0.0)

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)


# ── logging ───────────────────────────────────────────────────────────────────

class TestLogging(unittest.TestCase):
    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            self.assertTrue(os.path.exists(path))
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_no_write_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path})
            self.assertFalse(os.path.exists(path))

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            cfg = {"log_path": path, "log_cap": 3}
            for _ in range(6):
                A().analyze_portfolio([make_pos()], cfg=cfg, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_ring_buffer_cap_100_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            cfg = {"log_path": path, "log_cap": LOG_CAP}
            for _ in range(105):
                A().analyze(make_pos(), cfg=cfg, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 100)

    def test_corrupt_log_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as fh:
                fh.write("{not valid json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_non_list_log_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as fh:
                json.dump({"not": "a list"}, fh)
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_log_entry_has_snapshots(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([make_pos(), make_pos(vault="B")],
                                  cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(data[0]["position_count"], 2)
            self.assertEqual(len(data[0]["snapshots"]), 2)

    def test_atomic_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_log_json_no_inf_nan(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([
                make_pos(),
                make_pos(vault="full", deposit_cap_usd=1e6, current_tvl_usd=1e6),
                make_pos(vault="ins", deposit_cap_usd=0.0),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            json.loads(raw)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "vault": "S",
            "deposit_cap_usd": "100000000",
            "current_tvl_usd": "25000000",
            "intended_deposit_usd": "1000000",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({
            "vault": "S",
            "deposit_cap_usd": 100_000_000.0,
            "current_tvl_usd": 25_000_000.0,
        })
        self.assertIn("classification", r)

    def test_default_cap_is_hard_true(self):
        r = A().analyze({
            "vault": "S",
            "deposit_cap_usd": 100_000_000.0,
            "current_tvl_usd": 25_000_000.0,
        })
        self.assertTrue(r["cap_is_hard"])

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio([make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(), make_pos(deposit_cap_usd=0.0),
            make_pos(current_tvl_usd=80_000_000.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(), make_pos(deposit_cap_usd=0.0),
                    make_pos(current_tvl_usd=0.0),
                    make_pos(recent_inflow_usd_7d=1e12),
                    make_pos(deposit_cap_usd=1.0, current_tvl_usd=1.0)]:
            r = A().analyze(pos)
            for v in r.values():
                if isinstance(v, float):
                    self.assertFalse(math.isinf(v))
                    self.assertFalse(math.isnan(v))


# ── CLI smoke ─────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_demo_positions_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

    def test_demo_runs_through_portfolio(self):
        res = A().analyze_portfolio(_demo_positions())
        self.assertEqual(len(res["positions"]), len(_demo_positions()))
        self.assertIn("aggregate", res)

    def test_demo_json_serializable(self):
        res = A().analyze_portfolio(_demo_positions())
        json.dumps(res)

    def test_demo_no_inf_nan(self):
        res = A().analyze_portfolio(_demo_positions())
        raw = json.dumps(res)
        self.assertNotIn("Infinity", raw)
        self.assertNotIn("NaN", raw)


if __name__ == "__main__":
    unittest.main()
