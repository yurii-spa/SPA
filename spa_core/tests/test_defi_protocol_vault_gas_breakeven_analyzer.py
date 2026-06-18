"""
Tests for MP-1164: DeFiProtocolVaultGasBreakevenAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_gas_breakeven_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_gas_breakeven_analyzer import (
    DeFiProtocolVaultGasBreakevenAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DAYS_PER_YEAR,
    NEGLIGIBLE_GAS_PCT,
    LOW_GAS_PCT,
    MODERATE_GAS_PCT,
    GAS_DRAG_SCORE_CEILING_PCT,
    SMALL_POSITION_USD,
    HIGH_COMPOUND_GAS_SHARE_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    position_usd=10000.0,
    deposit_gas_usd=5.0,
    withdrawal_gas_usd=5.0,
    compound_gas_usd=2.0,
    compounds_per_year=12.0,
    apr_pct=6.0,
    holding_days=365.0,
):
    return {
        "vault": vault,
        "position_usd": position_usd,
        "deposit_gas_usd": deposit_gas_usd,
        "withdrawal_gas_usd": withdrawal_gas_usd,
        "compound_gas_usd": compound_gas_usd,
        "compounds_per_year": compounds_per_year,
        "apr_pct": apr_pct,
        "holding_days": holding_days,
    }


def A():
    return DeFiProtocolVaultGasBreakevenAnalyzer()


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

    def test_f_default_used_for_none(self):
        self.assertEqual(_f(None, 365.0), 365.0)

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
        self.assertAlmostEqual(_mean([2, 4, 6]), 4.0)

    def test_mean_single(self):
        self.assertAlmostEqual(_mean([8.0]), 8.0)

    def test_safe_div_normal(self):
        self.assertAlmostEqual(_safe_div(10, 2, 1e9), 5.0)

    def test_safe_div_zero_denominator(self):
        self.assertEqual(_safe_div(10, 0, 1e9), 1e9)

    def test_safe_div_negative_denominator(self):
        self.assertEqual(_safe_div(10, -5, 7.0), 7.0)

    def test_safe_div_none_sentinel(self):
        self.assertIsNone(_safe_div(10, 0, None))

    def test_safe_div_zero_sentinel(self):
        self.assertEqual(_safe_div(5, 0, 0.0), 0.0)

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

    def test_build_default_cfg_extra_key(self):
        cfg = _build_default_cfg({"extra": 1})
        self.assertEqual(cfg["extra"], 1)

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

    def test_grade_zero(self):
        self.assertEqual(_grade_from_score(0.0), "F")

    def test_grade_hundred(self):
        self.assertEqual(_grade_from_score(100.0), "A")

    def test_constants_sane(self):
        self.assertEqual(DAYS_PER_YEAR, 365.0)
        self.assertLess(NEGLIGIBLE_GAS_PCT, LOW_GAS_PCT)
        self.assertLess(LOW_GAS_PCT, MODERATE_GAS_PCT)
        self.assertGreater(GAS_DRAG_SCORE_CEILING_PCT, 0)
        self.assertGreater(SMALL_POSITION_USD, 0)
        self.assertGreater(HIGH_COMPOUND_GAS_SHARE_PCT, 0)

    def test_band_thresholds_positive(self):
        self.assertGreater(NEGLIGIBLE_GAS_PCT, 0.0)
        self.assertGreater(MODERATE_GAS_PCT, LOW_GAS_PCT)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "position_usd", "deposit_gas_usd", "withdrawal_gas_usd",
            "compound_gas_usd", "compounds_per_year", "apr_pct", "holding_days",
            "holding_years", "total_fixed_gas_usd", "annual_compound_gas_usd",
            "gross_yield_usd", "total_gas_usd", "net_yield_usd", "gas_drag_pct",
            "net_apr_pct", "breakeven_position_usd", "breakeven_days",
            "compound_gas_share_pct", "covers_horizon", "score",
            "classification", "recommendation", "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_score_in_range(self):
        self.assertGreaterEqual(self.r["score"], 0.0)
        self.assertLessEqual(self.r["score"], 100.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_preserved(self):
        self.assertEqual(self.r["token"], "USDC-Vault")

    def test_token_field_alias(self):
        r = A().analyze({"token": "AltKey", "position_usd": 10000.0,
                         "apr_pct": 6.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "position_usd": 10000.0, "apr_pct": 6.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"position_usd": 10000.0, "apr_pct": 6.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "DEPLOY", "DEPLOY_IF_LONG_HOLD", "RECONSIDER_SIZE", "AVOID",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "NEGLIGIBLE_GAS", "LOW_GAS", "MODERATE_GAS", "HIGH_GAS",
            "NEVER_BREAKS_EVEN", "INSUFFICIENT_DATA",
        })

    def test_covers_horizon_is_bool(self):
        self.assertIsInstance(self.r["covers_horizon"], bool)

    def test_breakeven_position_present(self):
        self.assertIn("breakeven_position_usd", self.r)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_position_negative_clamped(self):
        r = A().analyze(make_pos(position_usd=-100.0))
        self.assertAlmostEqual(r["position_usd"], 0.0)

    def test_deposit_gas_negative_clamped(self):
        r = A().analyze(make_pos(deposit_gas_usd=-5.0))
        self.assertAlmostEqual(r["deposit_gas_usd"], 0.0)

    def test_withdrawal_gas_negative_clamped(self):
        r = A().analyze(make_pos(withdrawal_gas_usd=-5.0))
        self.assertAlmostEqual(r["withdrawal_gas_usd"], 0.0)

    def test_compound_gas_negative_clamped(self):
        r = A().analyze(make_pos(compound_gas_usd=-2.0))
        self.assertAlmostEqual(r["compound_gas_usd"], 0.0)

    def test_compounds_negative_clamped(self):
        r = A().analyze(make_pos(compounds_per_year=-12.0))
        self.assertAlmostEqual(r["compounds_per_year"], 0.0)

    def test_apr_negative_clamped(self):
        r = A().analyze(make_pos(apr_pct=-6.0))
        self.assertAlmostEqual(r["apr_pct"], 0.0)

    def test_holding_days_negative_clamped(self):
        r = A().analyze(make_pos(holding_days=-30.0))
        self.assertAlmostEqual(r["holding_days"], 0.0)

    def test_holding_days_default(self):
        r = A().analyze({"vault": "X", "position_usd": 10000.0, "apr_pct": 6.0})
        self.assertAlmostEqual(r["holding_days"], 365.0)

    def test_total_fixed_gas_sum(self):
        r = A().analyze(make_pos(deposit_gas_usd=5.0, withdrawal_gas_usd=7.0))
        self.assertAlmostEqual(r["total_fixed_gas_usd"], 12.0)

    def test_annual_compound_gas(self):
        r = A().analyze(make_pos(compound_gas_usd=2.0, compounds_per_year=12.0))
        self.assertAlmostEqual(r["annual_compound_gas_usd"], 24.0)

    def test_holding_years(self):
        r = A().analyze(make_pos(holding_days=365.0))
        self.assertAlmostEqual(r["holding_years"], 1.0)

    def test_holding_years_half(self):
        r = A().analyze(make_pos(holding_days=182.5))
        self.assertAlmostEqual(r["holding_years"], 0.5)

    def test_gross_yield_usd(self):
        # 10000 * 6% * 1yr = 600
        r = A().analyze(make_pos(position_usd=10000.0, apr_pct=6.0,
                                 holding_days=365.0))
        self.assertAlmostEqual(r["gross_yield_usd"], 600.0)

    def test_total_gas_usd(self):
        # fixed 10 + 24/yr * 1yr = 34
        r = A().analyze(make_pos(deposit_gas_usd=5.0, withdrawal_gas_usd=5.0,
                                 compound_gas_usd=2.0, compounds_per_year=12.0,
                                 holding_days=365.0))
        self.assertAlmostEqual(r["total_gas_usd"], 34.0)

    def test_net_yield_usd(self):
        # gross 600 - gas 34 = 566
        r = A().analyze(make_pos(position_usd=10000.0, apr_pct=6.0,
                                 deposit_gas_usd=5.0, withdrawal_gas_usd=5.0,
                                 compound_gas_usd=2.0, compounds_per_year=12.0,
                                 holding_days=365.0))
        self.assertAlmostEqual(r["net_yield_usd"], 566.0)

    def test_gas_drag_pct(self):
        # gas 34 / position 10000 * 100 = 0.34
        r = A().analyze(make_pos(position_usd=10000.0, deposit_gas_usd=5.0,
                                 withdrawal_gas_usd=5.0, compound_gas_usd=2.0,
                                 compounds_per_year=12.0, holding_days=365.0))
        self.assertAlmostEqual(r["gas_drag_pct"], 0.34)

    def test_gas_drag_zero_position(self):
        # position 0 → safe_div sentinel 0 (but apr keeps it from insufficient)
        r = A().analyze(make_pos(position_usd=0.0, apr_pct=6.0))
        self.assertAlmostEqual(r["gas_drag_pct"], 0.0)

    def test_net_apr_pct(self):
        # apr 6 - annualised drag 0.34/1yr = 5.66
        r = A().analyze(make_pos(position_usd=10000.0, apr_pct=6.0,
                                 deposit_gas_usd=5.0, withdrawal_gas_usd=5.0,
                                 compound_gas_usd=2.0, compounds_per_year=12.0,
                                 holding_days=365.0))
        self.assertAlmostEqual(r["net_apr_pct"], 5.66)

    def test_net_apr_horizon_guard(self):
        # holding 0 → annualised drag safe_div sentinel 0 → net_apr == apr
        r = A().analyze(make_pos(position_usd=10000.0, apr_pct=6.0,
                                 holding_days=0.0))
        self.assertAlmostEqual(r["net_apr_pct"], 6.0)

    def test_breakeven_position_usd(self):
        # gas 34 / (6%/yr * 1yr) = 34/0.06 = 566.667
        r = A().analyze(make_pos(position_usd=10000.0, apr_pct=6.0,
                                 deposit_gas_usd=5.0, withdrawal_gas_usd=5.0,
                                 compound_gas_usd=2.0, compounds_per_year=12.0,
                                 holding_days=365.0))
        self.assertAlmostEqual(r["breakeven_position_usd"], 34.0 / 0.06,
                               places=2)

    def test_breakeven_position_none_zero_apr(self):
        r = A().analyze(make_pos(position_usd=10000.0, apr_pct=0.0))
        self.assertIsNone(r["breakeven_position_usd"])

    def test_breakeven_position_none_zero_horizon(self):
        r = A().analyze(make_pos(position_usd=10000.0, apr_pct=6.0,
                                 holding_days=0.0))
        self.assertIsNone(r["breakeven_position_usd"])

    def test_breakeven_days(self):
        # fixed gas 10 / (10000*6%/365) = 10 / 1.6438 = 6.0833 days
        r = A().analyze(make_pos(position_usd=10000.0, apr_pct=6.0,
                                 deposit_gas_usd=5.0, withdrawal_gas_usd=5.0))
        daily = 10000.0 * 6.0 / 100.0 / 365.0
        self.assertAlmostEqual(r["breakeven_days"], 10.0 / daily, places=2)

    def test_breakeven_days_none_zero_apr(self):
        r = A().analyze(make_pos(position_usd=10000.0, apr_pct=0.0))
        self.assertIsNone(r["breakeven_days"])

    def test_breakeven_days_none_zero_position(self):
        r = A().analyze(make_pos(position_usd=0.0, apr_pct=6.0))
        self.assertIsNone(r["breakeven_days"])

    def test_covers_horizon_true(self):
        r = A().analyze(make_pos(position_usd=100000.0, apr_pct=6.0,
                                 deposit_gas_usd=5.0, withdrawal_gas_usd=5.0))
        self.assertTrue(r["covers_horizon"])

    def test_covers_horizon_false(self):
        r = A().analyze(make_pos(position_usd=100.0, apr_pct=2.0,
                                 deposit_gas_usd=50.0, withdrawal_gas_usd=50.0,
                                 holding_days=30.0))
        self.assertFalse(r["covers_horizon"])

    def test_compound_gas_share(self):
        # compound 24, fixed 10, total 34 → share 24/34*100
        r = A().analyze(make_pos(deposit_gas_usd=5.0, withdrawal_gas_usd=5.0,
                                 compound_gas_usd=2.0, compounds_per_year=12.0,
                                 holding_days=365.0))
        self.assertAlmostEqual(r["compound_gas_share_pct"], 24.0 / 34.0 * 100.0,
                               places=2)

    def test_compound_gas_share_zero_no_compound(self):
        r = A().analyze(make_pos(compound_gas_usd=0.0, compounds_per_year=0.0))
        self.assertAlmostEqual(r["compound_gas_share_pct"], 0.0)

    def test_free_entry_exit_metrics(self):
        r = A().analyze(make_pos(deposit_gas_usd=0.0, withdrawal_gas_usd=0.0))
        self.assertAlmostEqual(r["total_fixed_gas_usd"], 0.0)

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos())
        for k in ("position_usd", "total_gas_usd", "gas_drag_pct",
                  "net_apr_pct", "gross_yield_usd"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_negligible_gas(self):
        # huge position → tiny drag
        r = A().analyze(make_pos(position_usd=1000000.0, apr_pct=6.0,
                                 deposit_gas_usd=5.0, withdrawal_gas_usd=5.0,
                                 compound_gas_usd=2.0, compounds_per_year=12.0))
        self.assertEqual(r["classification"], "NEGLIGIBLE_GAS")

    def test_low_gas(self):
        # drag in (2, 5]
        r = A().analyze(make_pos(position_usd=1000.0, apr_pct=20.0,
                                 deposit_gas_usd=15.0, withdrawal_gas_usd=15.0,
                                 compound_gas_usd=0.0, compounds_per_year=0.0,
                                 holding_days=365.0))
        # drag = 30/1000*100 = 3.0 → LOW
        self.assertAlmostEqual(r["gas_drag_pct"], 3.0)
        self.assertEqual(r["classification"], "LOW_GAS")

    def test_moderate_gas(self):
        # drag in (5, 15]
        r = A().analyze(make_pos(position_usd=1000.0, apr_pct=20.0,
                                 deposit_gas_usd=50.0, withdrawal_gas_usd=50.0,
                                 compound_gas_usd=0.0, compounds_per_year=0.0,
                                 holding_days=365.0))
        # drag = 100/1000*100 = 10.0 → MODERATE
        self.assertAlmostEqual(r["gas_drag_pct"], 10.0)
        self.assertEqual(r["classification"], "MODERATE_GAS")

    def test_high_gas(self):
        # drag > 15 but still covers horizon
        r = A().analyze(make_pos(position_usd=1000.0, apr_pct=50.0,
                                 deposit_gas_usd=90.0, withdrawal_gas_usd=90.0,
                                 compound_gas_usd=0.0, compounds_per_year=0.0,
                                 holding_days=365.0))
        # drag = 180/1000*100 = 18 ; gross = 500 > 180 → covers
        self.assertGreater(r["gas_drag_pct"], MODERATE_GAS_PCT)
        self.assertTrue(r["covers_horizon"])
        self.assertEqual(r["classification"], "HIGH_GAS")

    def test_never_breaks_even_no_apr(self):
        r = A().analyze(make_pos(position_usd=10000.0, apr_pct=0.0,
                                 deposit_gas_usd=5.0, withdrawal_gas_usd=5.0))
        self.assertEqual(r["classification"], "NEVER_BREAKS_EVEN")

    def test_never_breaks_even_negative_net(self):
        # gas exceeds gross yield over horizon
        r = A().analyze(make_pos(position_usd=100.0, apr_pct=2.0,
                                 deposit_gas_usd=50.0, withdrawal_gas_usd=50.0,
                                 holding_days=30.0))
        self.assertFalse(r["covers_horizon"])
        self.assertEqual(r["classification"], "NEVER_BREAKS_EVEN")

    def test_negligible_boundary(self):
        # exactly 2% drag → NEGLIGIBLE (<=)
        r = A().analyze(make_pos(position_usd=1000.0, apr_pct=20.0,
                                 deposit_gas_usd=10.0, withdrawal_gas_usd=10.0,
                                 compound_gas_usd=0.0, compounds_per_year=0.0,
                                 holding_days=365.0))
        self.assertAlmostEqual(r["gas_drag_pct"], 2.0)
        self.assertEqual(r["classification"], "NEGLIGIBLE_GAS")

    def test_low_boundary(self):
        # exactly 5% drag → LOW (<=)
        r = A().analyze(make_pos(position_usd=1000.0, apr_pct=20.0,
                                 deposit_gas_usd=25.0, withdrawal_gas_usd=25.0,
                                 compound_gas_usd=0.0, compounds_per_year=0.0,
                                 holding_days=365.0))
        self.assertAlmostEqual(r["gas_drag_pct"], 5.0)
        self.assertEqual(r["classification"], "LOW_GAS")

    def test_moderate_boundary(self):
        # exactly 15% drag → MODERATE (<=)
        r = A().analyze(make_pos(position_usd=1000.0, apr_pct=30.0,
                                 deposit_gas_usd=75.0, withdrawal_gas_usd=75.0,
                                 compound_gas_usd=0.0, compounds_per_year=0.0,
                                 holding_days=365.0))
        self.assertAlmostEqual(r["gas_drag_pct"], 15.0)
        self.assertEqual(r["classification"], "MODERATE_GAS")

    def test_classification_known_value(self):
        for pos in [make_pos(),
                    make_pos(position_usd=1000000.0),
                    make_pos(position_usd=100.0, apr_pct=1.0,
                             deposit_gas_usd=50.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "NEGLIGIBLE_GAS", "LOW_GAS", "MODERATE_GAS", "HIGH_GAS",
                "NEVER_BREAKS_EVEN", "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_deploy_when_negligible(self):
        r = A().analyze(make_pos(position_usd=1000000.0, apr_pct=6.0))
        self.assertEqual(r["recommendation"], "DEPLOY")

    def test_deploy_when_low(self):
        r = A().analyze(make_pos(position_usd=1000.0, apr_pct=20.0,
                                 deposit_gas_usd=15.0, withdrawal_gas_usd=15.0,
                                 compound_gas_usd=0.0, compounds_per_year=0.0))
        self.assertEqual(r["recommendation"], "DEPLOY")

    def test_deploy_if_long_hold_when_moderate(self):
        r = A().analyze(make_pos(position_usd=1000.0, apr_pct=20.0,
                                 deposit_gas_usd=50.0, withdrawal_gas_usd=50.0,
                                 compound_gas_usd=0.0, compounds_per_year=0.0))
        self.assertEqual(r["recommendation"], "DEPLOY_IF_LONG_HOLD")

    def test_reconsider_size_when_high(self):
        r = A().analyze(make_pos(position_usd=1000.0, apr_pct=50.0,
                                 deposit_gas_usd=90.0, withdrawal_gas_usd=90.0,
                                 compound_gas_usd=0.0, compounds_per_year=0.0))
        self.assertEqual(r["recommendation"], "RECONSIDER_SIZE")

    def test_avoid_when_never_breaks_even(self):
        r = A().analyze(make_pos(position_usd=10000.0, apr_pct=0.0,
                                 deposit_gas_usd=5.0, withdrawal_gas_usd=5.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_avoid_when_insufficient(self):
        r = A().analyze(make_pos(position_usd=0.0, apr_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_small_position_gas_heavy_flag(self):
        r = A().analyze(make_pos(position_usd=500.0, apr_pct=20.0,
                                 deposit_gas_usd=50.0, withdrawal_gas_usd=50.0,
                                 compound_gas_usd=0.0, compounds_per_year=0.0))
        self.assertIn("SMALL_POSITION_GAS_HEAVY", r["flags"])

    def test_small_position_gas_heavy_absent_large(self):
        r = A().analyze(make_pos(position_usd=1000000.0, apr_pct=6.0))
        self.assertNotIn("SMALL_POSITION_GAS_HEAVY", r["flags"])

    def test_small_position_gas_heavy_absent_low_drag(self):
        # small position but tiny gas → low drag → no flag
        r = A().analyze(make_pos(position_usd=500.0, apr_pct=20.0,
                                 deposit_gas_usd=1.0, withdrawal_gas_usd=1.0,
                                 compound_gas_usd=0.0, compounds_per_year=0.0))
        self.assertNotIn("SMALL_POSITION_GAS_HEAVY", r["flags"])

    def test_covers_horizon_flag(self):
        r = A().analyze(make_pos(position_usd=100000.0, apr_pct=6.0))
        self.assertIn("COVERS_HORIZON", r["flags"])

    def test_covers_horizon_flag_absent(self):
        r = A().analyze(make_pos(position_usd=100.0, apr_pct=2.0,
                                 deposit_gas_usd=50.0, withdrawal_gas_usd=50.0,
                                 holding_days=30.0))
        self.assertNotIn("COVERS_HORIZON", r["flags"])

    def test_never_breaks_even_flag(self):
        r = A().analyze(make_pos(position_usd=10000.0, apr_pct=0.0))
        self.assertIn("NEVER_BREAKS_EVEN", r["flags"])

    def test_never_breaks_even_flag_absent(self):
        r = A().analyze(make_pos(position_usd=100000.0, apr_pct=6.0))
        self.assertNotIn("NEVER_BREAKS_EVEN", r["flags"])

    def test_high_compound_gas_flag(self):
        # compound dominates fixed
        r = A().analyze(make_pos(deposit_gas_usd=1.0, withdrawal_gas_usd=1.0,
                                 compound_gas_usd=5.0, compounds_per_year=52.0,
                                 holding_days=365.0))
        self.assertIn("HIGH_COMPOUND_GAS", r["flags"])

    def test_high_compound_gas_flag_absent(self):
        r = A().analyze(make_pos(deposit_gas_usd=50.0, withdrawal_gas_usd=50.0,
                                 compound_gas_usd=0.0, compounds_per_year=0.0))
        self.assertNotIn("HIGH_COMPOUND_GAS", r["flags"])

    def test_free_entry_exit_flag(self):
        r = A().analyze(make_pos(deposit_gas_usd=0.0, withdrawal_gas_usd=0.0))
        self.assertIn("FREE_ENTRY_EXIT", r["flags"])

    def test_free_entry_exit_flag_absent(self):
        r = A().analyze(make_pos(deposit_gas_usd=5.0, withdrawal_gas_usd=5.0))
        self.assertNotIn("FREE_ENTRY_EXIT", r["flags"])

    def test_negative_net_flag(self):
        r = A().analyze(make_pos(position_usd=100.0, apr_pct=2.0,
                                 deposit_gas_usd=50.0, withdrawal_gas_usd=50.0,
                                 holding_days=30.0))
        self.assertIn("NEGATIVE_NET", r["flags"])

    def test_negative_net_flag_absent(self):
        r = A().analyze(make_pos(position_usd=100000.0, apr_pct=6.0))
        self.assertNotIn("NEGATIVE_NET", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(position_usd=0.0, apr_pct=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_small_position_boundary(self):
        # exactly at SMALL_POSITION_USD with high drag → flagged
        r = A().analyze(make_pos(position_usd=SMALL_POSITION_USD, apr_pct=30.0,
                                 deposit_gas_usd=60.0, withdrawal_gas_usd=60.0,
                                 compound_gas_usd=0.0, compounds_per_year=0.0))
        # drag = 120/1000*100 = 12 > 5 → flagged
        self.assertIn("SMALL_POSITION_GAS_HEAVY", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_position_no_apr(self):
        r = A().analyze(make_pos(position_usd=0.0, apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(position_usd=0.0, apr_pct=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation_avoid(self):
        r = A().analyze(make_pos(position_usd=0.0, apr_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_only_position_is_sufficient(self):
        r = A().analyze(make_pos(position_usd=10000.0, apr_pct=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_only_apr_is_sufficient(self):
        r = A().analyze(make_pos(position_usd=0.0, apr_pct=6.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_inputs_treated_as_zero(self):
        r = A().analyze(make_pos(position_usd=-100.0, apr_pct=-6.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_breakeven_none(self):
        r = A().analyze({})
        self.assertIsNone(r["breakeven_position_usd"])
        self.assertIsNone(r["breakeven_days"])

    def test_insufficient_all_numeric_zero(self):
        r = A().analyze({})
        for k in ("position_usd", "total_gas_usd", "gas_drag_pct",
                  "net_apr_pct", "score", "gross_yield_usd"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["covers_horizon"])

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_larger_position_scores_higher(self):
        small = A().analyze(make_pos(position_usd=1000.0))
        large = A().analyze(make_pos(position_usd=1000000.0))
        self.assertGreater(large["score"], small["score"])

    def test_cheaper_fixed_gas_scores_higher(self):
        cheap = A().analyze(make_pos(deposit_gas_usd=1.0, withdrawal_gas_usd=1.0,
                                     compound_gas_usd=0.0, compounds_per_year=0.0))
        dear = A().analyze(make_pos(deposit_gas_usd=80.0, withdrawal_gas_usd=80.0,
                                    compound_gas_usd=0.0, compounds_per_year=0.0))
        self.assertGreater(cheap["score"], dear["score"])

    def test_covers_horizon_scores_higher(self):
        covers = A().analyze(make_pos(position_usd=100000.0, apr_pct=6.0,
                                      deposit_gas_usd=5.0, withdrawal_gas_usd=5.0,
                                      compound_gas_usd=0.0, compounds_per_year=0.0))
        nocover = A().analyze(make_pos(position_usd=100.0, apr_pct=2.0,
                                       deposit_gas_usd=50.0, withdrawal_gas_usd=50.0,
                                       holding_days=30.0))
        self.assertGreater(covers["score"], nocover["score"])

    def test_lower_drag_scores_higher(self):
        low = A().analyze(make_pos(position_usd=1000000.0, apr_pct=6.0))
        high = A().analyze(make_pos(position_usd=1000.0, apr_pct=50.0,
                                    deposit_gas_usd=90.0, withdrawal_gas_usd=90.0,
                                    compound_gas_usd=0.0, compounds_per_year=0.0))
        self.assertGreater(low["score"], high["score"])

    def test_negligible_scores_high(self):
        r = A().analyze(make_pos(position_usd=10000000.0, apr_pct=6.0,
                                 deposit_gas_usd=1.0, withdrawal_gas_usd=1.0,
                                 compound_gas_usd=0.0, compounds_per_year=0.0))
        self.assertGreater(r["score"], 85.0)

    def test_never_breaks_even_scores_low(self):
        r = A().analyze(make_pos(position_usd=100.0, apr_pct=1.0,
                                 deposit_gas_usd=80.0, withdrawal_gas_usd=80.0,
                                 holding_days=30.0))
        self.assertLess(r["score"], 55.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(position_usd=1e12, apr_pct=1e6,
                                 deposit_gas_usd=1e6, withdrawal_gas_usd=1e6,
                                 compound_gas_usd=1e6, compounds_per_year=1e6,
                                 holding_days=1e6))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(position_usd=1.0, apr_pct=0.0,
                                 deposit_gas_usd=1000.0, withdrawal_gas_usd=1000.0))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(),
                    make_pos(position_usd=1000000.0),
                    make_pos(holding_days=0.0),
                    make_pos(apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Cheap", position_usd=1000000.0, apr_pct=6.0,
                     deposit_gas_usd=2.0, withdrawal_gas_usd=2.0,
                     compound_gas_usd=0.0, compounds_per_year=0.0),
            make_pos(vault="Expensive", position_usd=200.0, apr_pct=2.0,
                     deposit_gas_usd=50.0, withdrawal_gas_usd=50.0,
                     holding_days=30.0),
            make_pos(vault="Mid", position_usd=5000.0, apr_pct=10.0,
                     deposit_gas_usd=30.0, withdrawal_gas_usd=30.0,
                     compound_gas_usd=0.0, compounds_per_year=0.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_cheapest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["cheapest_vault"]], max(scores.values()))

    def test_most_expensive_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_expensive_vault"]],
                         min(scores.values()))

    def test_cheapest_is_cheap(self):
        self.assertEqual(self.res["aggregate"]["cheapest_vault"], "Cheap")

    def test_most_expensive_is_expensive(self):
        self.assertEqual(self.res["aggregate"]["most_expensive_vault"],
                         "Expensive")

    def test_high_gas_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["high_gas_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["cheapest_vault"])
        self.assertIsNone(res["aggregate"]["most_expensive_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(position_usd=0.0, apr_pct=0.0),
            make_pos(position_usd=0.0, apr_pct=0.0),
        ])
        self.assertIsNone(res["aggregate"]["cheapest_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["high_gas_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["cheapest_vault"], "Solo")
        self.assertEqual(res["aggregate"]["most_expensive_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_high_gas_count_counts_classification(self):
        res = A().analyze_portfolio([
            make_pos(vault="H", position_usd=10000.0, apr_pct=0.0),
        ])
        self.assertEqual(res["aggregate"]["high_gas_count"], 1)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", position_usd=1000000.0, apr_pct=6.0),
            make_pos(vault="Ins", position_usd=0.0, apr_pct=0.0),
        ])
        scored = [p["score"] for p in res["positions"]
                  if p["classification"] != "INSUFFICIENT_DATA"]
        self.assertAlmostEqual(res["aggregate"]["avg_score"],
                               round(sum(scored) / len(scored), 2))


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

    def test_ring_buffer_cap_3(self):
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
                make_pos(vault="big", position_usd=1e12, apr_pct=1e6,
                         deposit_gas_usd=1e6, withdrawal_gas_usd=1e6,
                         compound_gas_usd=1e6, compounds_per_year=1e6),
                make_pos(vault="ins", position_usd=0.0, apr_pct=0.0),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            json.loads(raw)

    def test_log_snapshot_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            snap = data[0]["snapshots"][0]
            for k in ("token", "classification", "score",
                      "recommendation", "flags"):
                self.assertIn(k, snap)

    def test_log_has_aggregate(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([make_pos()],
                                  cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIn("aggregate", data[0])

    def test_log_does_not_touch_production(self):
        before = os.path.exists(LOG_PATH)
        A().analyze(make_pos())
        after = os.path.exists(LOG_PATH)
        self.assertEqual(before, after)

    def test_no_write_analyze_does_not_create_production_log(self):
        before = os.path.exists(LOG_PATH)
        A().analyze_portfolio(_demo_positions())
        after = os.path.exists(LOG_PATH)
        self.assertEqual(before, after)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "vault": "S",
            "position_usd": "10000",
            "deposit_gas_usd": "5",
            "withdrawal_gas_usd": "5",
            "compound_gas_usd": "2",
            "compounds_per_year": "12",
            "apr_pct": "6",
            "holding_days": "365",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "position_usd": 10000.0, "apr_pct": 6.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(position_usd=0.0, apr_pct=0.0),
            make_pos(position_usd=1000000.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(position_usd=1000000.0),
                    make_pos(holding_days=0.0),
                    make_pos(position_usd=0.0, apr_pct=0.0),
                    make_pos(position_usd=1e12, apr_pct=1e6),
                    make_pos(apr_pct=0.0),
                    make_pos(deposit_gas_usd=1e9, withdrawal_gas_usd=1e9),
                    make_pos(compounds_per_year=1e9, compound_gas_usd=1e9),
                    make_pos(position_usd=-100.0)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_zero_holding_days_no_crash(self):
        r = A().analyze(make_pos(holding_days=0.0))
        self.assertAlmostEqual(r["holding_years"], 0.0)
        finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(position_usd=1e12, apr_pct=1e9,
                                 deposit_gas_usd=1e9, withdrawal_gas_usd=1e9,
                                 compound_gas_usd=1e9, compounds_per_year=1e9,
                                 holding_days=1e9))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_huge_gas_no_inf(self):
        r = A().analyze(make_pos(position_usd=1.0, apr_pct=1.0,
                                 deposit_gas_usd=1e12, withdrawal_gas_usd=1e12))
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(position_usd=-100.0, apr_pct=6.0,
                                 deposit_gas_usd=-5.0, withdrawal_gas_usd=-5.0,
                                 compound_gas_usd=-2.0, compounds_per_year=-12.0,
                                 holding_days=-5.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_breakeven_position_finite_or_none(self):
        for pos in [make_pos(), make_pos(apr_pct=0.0),
                    make_pos(holding_days=0.0),
                    make_pos(position_usd=1e12, apr_pct=1e-9)]:
            r = A().analyze(pos)
            bp = r["breakeven_position_usd"]
            if bp is not None:
                self.assertTrue(math.isfinite(bp))


# ── CLI smoke ─────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_demo_positions_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 3)

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

    def test_demo_has_varied_classifications(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertGreater(len(classes), 1)

    def test_demo_includes_insufficient(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_includes_good_low_gas(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertTrue(
            "NEGLIGIBLE_GAS" in classes or "LOW_GAS" in classes)

    def test_demo_includes_bad(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertTrue(
            "HIGH_GAS" in classes or "NEVER_BREAKS_EVEN" in classes)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
