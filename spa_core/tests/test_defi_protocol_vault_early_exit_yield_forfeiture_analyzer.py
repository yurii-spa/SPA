"""
Tests for MP-1216: DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_early_exit_yield_forfeiture_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_early_exit_yield_forfeiture_analyzer import (  # noqa: E501
    DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _coerce_num,
    _coerce_signed,
    _coerce_count,
    _coerce_mode,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    CLEAN_FRACTION,
    MILD_FRACTION,
    MODERATE_FRACTION,
    HIGH_COOLDOWN_DAYS,
    MODE_CLIFF,
    MODE_LINEAR,
    EPS,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    total_accrued_yield_pct=None,
    pending_yield_pct=None,
    vesting_progress_pct=None,
    forfeit_mode=None,
    cooldown_days=None,
    forfeited_yield_pct=None,
):
    pos = {"vault": vault}
    if total_accrued_yield_pct is not None:
        pos["total_accrued_yield_pct"] = total_accrued_yield_pct
    if pending_yield_pct is not None:
        pos["pending_yield_pct"] = pending_yield_pct
    if vesting_progress_pct is not None:
        pos["vesting_progress_pct"] = vesting_progress_pct
    if forfeit_mode is not None:
        pos["forfeit_mode"] = forfeit_mode
    if cooldown_days is not None:
        pos["cooldown_days"] = cooldown_days
    if forfeited_yield_pct is not None:
        pos["forfeited_yield_pct"] = forfeited_yield_pct
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


# ── helper tests ────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    def test_f_none_default(self):
        self.assertEqual(_f(None), 0.0)

    def test_f_none_custom_default(self):
        self.assertEqual(_f(None, 3.0), 3.0)

    def test_f_bad_string(self):
        self.assertEqual(_f("x", 1.0), 1.0)

    def test_f_numeric_string(self):
        self.assertEqual(_f("2.5"), 2.5)

    def test_f_int(self):
        self.assertEqual(_f(4), 4.0)

    def test_clamp_above(self):
        self.assertEqual(_clamp(5, 0, 1), 1)

    def test_clamp_below(self):
        self.assertEqual(_clamp(-5, 0, 1), 0)

    def test_clamp_in_range(self):
        self.assertEqual(_clamp(0.5, 0, 1), 0.5)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertEqual(_mean([2, 4]), 3.0)

    def test_safe_div_ok(self):
        self.assertEqual(_safe_div(10, 2, None), 5.0)

    def test_safe_div_zero(self):
        self.assertIsNone(_safe_div(10, 0, None))

    def test_safe_div_negative(self):
        self.assertIsNone(_safe_div(10, -1, None))

    def test_coerce_num_int(self):
        self.assertEqual(_coerce_num(3), 3.0)

    def test_coerce_num_float(self):
        self.assertEqual(_coerce_num(3.5), 3.5)

    def test_coerce_num_string(self):
        self.assertEqual(_coerce_num("3.5"), 3.5)

    def test_coerce_num_bool_true(self):
        self.assertIsNone(_coerce_num(True))

    def test_coerce_num_bool_false(self):
        self.assertIsNone(_coerce_num(False))

    def test_coerce_num_none(self):
        self.assertIsNone(_coerce_num(None))

    def test_coerce_num_non_numeric(self):
        self.assertIsNone(_coerce_num("abc"))

    def test_coerce_num_empty_string(self):
        self.assertIsNone(_coerce_num(""))

    def test_coerce_num_whitespace_string(self):
        self.assertIsNone(_coerce_num("   "))

    def test_coerce_num_nan(self):
        self.assertIsNone(_coerce_num(float("nan")))

    def test_coerce_num_inf(self):
        self.assertIsNone(_coerce_num(float("inf")))

    def test_coerce_num_neg_inf(self):
        self.assertIsNone(_coerce_num(float("-inf")))

    def test_coerce_signed_negative(self):
        self.assertEqual(_coerce_signed(-5), -5.0)

    def test_coerce_signed_negative_string(self):
        self.assertEqual(_coerce_signed("-2.5"), -2.5)

    def test_coerce_signed_none(self):
        self.assertIsNone(_coerce_signed(None))

    def test_coerce_count_int(self):
        self.assertEqual(_coerce_count(3), 3)

    def test_coerce_count_string(self):
        self.assertEqual(_coerce_count("4"), 4)

    def test_coerce_count_zero(self):
        self.assertEqual(_coerce_count(0), 0)

    def test_coerce_count_negative(self):
        self.assertIsNone(_coerce_count(-1))

    def test_coerce_count_none(self):
        self.assertIsNone(_coerce_count(None))

    def test_coerce_count_non_numeric(self):
        self.assertIsNone(_coerce_count("x"))

    def test_coerce_count_float_truncates(self):
        self.assertEqual(_coerce_count(3.9), 3)

    def test_coerce_mode_cliff_lower(self):
        self.assertEqual(_coerce_mode("cliff"), MODE_CLIFF)

    def test_coerce_mode_cliff_upper(self):
        self.assertEqual(_coerce_mode("CLIFF"), MODE_CLIFF)

    def test_coerce_mode_linear_lower(self):
        self.assertEqual(_coerce_mode("linear"), MODE_LINEAR)

    def test_coerce_mode_linear_upper(self):
        self.assertEqual(_coerce_mode("LINEAR"), MODE_LINEAR)

    def test_coerce_mode_linear_padded(self):
        self.assertEqual(_coerce_mode("  Linear  "), MODE_LINEAR)

    def test_coerce_mode_unknown(self):
        self.assertEqual(_coerce_mode("weird"), MODE_CLIFF)

    def test_coerce_mode_none(self):
        self.assertEqual(_coerce_mode(None), MODE_CLIFF)

    def test_coerce_mode_non_str(self):
        self.assertEqual(_coerce_mode(123), MODE_CLIFF)

    def test_build_default_cfg_defaults(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg["log_cap"], 5)
        self.assertEqual(cfg["log_path"], LOG_PATH)

    def test_build_default_cfg_extra_key(self):
        cfg = _build_default_cfg({"log_path": "/tmp/x.json"})
        self.assertEqual(cfg["log_path"], "/tmp/x.json")

    def test_grade_a_boundary(self):
        self.assertEqual(_grade_from_score(85), "A")

    def test_grade_a_above(self):
        self.assertEqual(_grade_from_score(90), "A")

    def test_grade_b_boundary(self):
        self.assertEqual(_grade_from_score(70), "B")

    def test_grade_b_mid(self):
        self.assertEqual(_grade_from_score(75), "B")

    def test_grade_c_boundary(self):
        self.assertEqual(_grade_from_score(55), "C")

    def test_grade_c_mid(self):
        self.assertEqual(_grade_from_score(60), "C")

    def test_grade_d_boundary(self):
        self.assertEqual(_grade_from_score(40), "D")

    def test_grade_d_mid(self):
        self.assertEqual(_grade_from_score(45), "D")

    def test_grade_f(self):
        self.assertEqual(_grade_from_score(10), "F")


# ── constants ─────────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_clean_fraction(self):
        self.assertEqual(CLEAN_FRACTION, 0.05)

    def test_mild_fraction(self):
        self.assertEqual(MILD_FRACTION, 0.20)

    def test_moderate_fraction(self):
        self.assertEqual(MODERATE_FRACTION, 0.50)

    def test_high_cooldown_days(self):
        self.assertEqual(HIGH_COOLDOWN_DAYS, 14.0)

    def test_mode_cliff(self):
        self.assertEqual(MODE_CLIFF, "CLIFF")

    def test_mode_linear(self):
        self.assertEqual(MODE_LINEAR, "LINEAR")

    def test_log_cap(self):
        self.assertEqual(LOG_CAP, 100)

    def test_thresholds_ordered(self):
        self.assertLess(CLEAN_FRACTION, MILD_FRACTION)
        self.assertLess(MILD_FRACTION, MODERATE_FRACTION)

    def test_eps_positive(self):
        self.assertGreater(EPS, 0.0)

    def test_log_path_filename(self):
        self.assertTrue(LOG_PATH.endswith(
            "vault_early_exit_yield_forfeiture_log.json"))


# ── main path: no forfeiture / classification bands ───────────────────────────

class TestMainPathClassification(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer()

    def test_no_forfeiture_zero_pending(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=18.0, pending_yield_pct=0.0,
            forfeit_mode="CLIFF"))
        self.assertEqual(r["classification"], "NO_FORFEITURE")
        self.assertEqual(r["forfeiture_fraction"], 0.0)
        self.assertEqual(r["realization_ratio"], 1.0)
        self.assertEqual(r["score"], 100.0)
        self.assertEqual(r["grade"], "A")
        self.assertEqual(r["recommendation"], "EXIT_ANYTIME")
        self.assertIn("FULLY_VESTED_EXIT", r["flags"])

    def test_cliff_forfeited_equals_pending(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        self.assertAlmostEqual(r["forfeited_yield_pct"], 6.0)

    def test_cliff_fraction_is_pending_over_total(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        self.assertAlmostEqual(r["forfeiture_fraction"], 6.0 / 15.0, places=4)

    def test_band_no_at_boundary(self):
        # fraction exactly 0.05 → NO_FORFEITURE.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=20.0, pending_yield_pct=1.0,
            forfeit_mode="CLIFF"))
        self.assertAlmostEqual(r["forfeiture_fraction"], 0.05, places=4)
        self.assertEqual(r["classification"], "NO_FORFEITURE")

    def test_band_mild(self):
        # fraction 0.10 → MILD.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=20.0, pending_yield_pct=2.0,
            forfeit_mode="CLIFF"))
        self.assertAlmostEqual(r["forfeiture_fraction"], 0.10, places=4)
        self.assertEqual(r["classification"], "MILD_FORFEITURE")

    def test_band_mild_at_boundary(self):
        # fraction exactly 0.20 → MILD.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=20.0, pending_yield_pct=4.0,
            forfeit_mode="CLIFF"))
        self.assertAlmostEqual(r["forfeiture_fraction"], 0.20, places=4)
        self.assertEqual(r["classification"], "MILD_FORFEITURE")

    def test_band_moderate(self):
        # fraction 0.40 → MODERATE.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        self.assertAlmostEqual(r["forfeiture_fraction"], 0.40, places=4)
        self.assertEqual(r["classification"], "MODERATE_FORFEITURE")

    def test_band_moderate_at_boundary(self):
        # fraction exactly 0.50 → MODERATE.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=20.0, pending_yield_pct=10.0,
            forfeit_mode="CLIFF"))
        self.assertAlmostEqual(r["forfeiture_fraction"], 0.50, places=4)
        self.assertEqual(r["classification"], "MODERATE_FORFEITURE")

    def test_band_severe(self):
        # fraction 0.80 → SEVERE.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=20.0, pending_yield_pct=16.0,
            forfeit_mode="CLIFF"))
        self.assertAlmostEqual(r["forfeiture_fraction"], 0.80, places=4)
        self.assertEqual(r["classification"], "SEVERE_FORFEITURE")

    def test_recommendation_mild(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=20.0, pending_yield_pct=2.0,
            forfeit_mode="CLIFF"))
        self.assertEqual(r["recommendation"], "MINOR_EXIT_COST")

    def test_recommendation_moderate(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=20.0, pending_yield_pct=10.0,
            forfeit_mode="CLIFF"))
        self.assertEqual(r["recommendation"], "DELAY_EXIT_TO_VEST")

    def test_recommendation_severe(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=20.0, pending_yield_pct=16.0,
            forfeit_mode="CLIFF"))
        self.assertEqual(r["recommendation"], "AVOID_EARLY_EXIT")


# ── LINEAR mode ────────────────────────────────────────────────────────────────

class TestLinearMode(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer()

    def test_linear_far_along_mild(self):
        # total 20, pending 8, vested 80% → forfeited 8*0.2=1.6 → frac 0.08.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=20.0, pending_yield_pct=8.0,
            vesting_progress_pct=80.0, forfeit_mode="LINEAR"))
        self.assertAlmostEqual(r["forfeited_yield_pct"], 1.6, places=4)
        self.assertAlmostEqual(r["forfeiture_fraction"], 0.08, places=4)
        self.assertEqual(r["classification"], "MILD_FORFEITURE")

    def test_linear_zero_progress_full_pending(self):
        # vested 0% → forfeited == pending (behaves like cliff on pending).
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=20.0, pending_yield_pct=8.0,
            vesting_progress_pct=0.0, forfeit_mode="LINEAR"))
        self.assertAlmostEqual(r["forfeited_yield_pct"], 8.0, places=4)

    def test_linear_full_progress_no_forfeiture(self):
        # vested 100% → forfeited 0 → NO_FORFEITURE.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=20.0, pending_yield_pct=8.0,
            vesting_progress_pct=100.0, forfeit_mode="LINEAR"))
        self.assertAlmostEqual(r["forfeited_yield_pct"], 0.0, places=4)
        self.assertEqual(r["classification"], "NO_FORFEITURE")

    def test_linear_formula(self):
        # forfeited == pending * (1 - vesting_fraction).
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=30.0, pending_yield_pct=10.0,
            vesting_progress_pct=40.0, forfeit_mode="LINEAR"))
        self.assertAlmostEqual(r["forfeited_yield_pct"], 10.0 * 0.6, places=4)

    def test_linear_vesting_clamp_over_100(self):
        # vesting_progress_pct > 100 → vesting_fraction clamps to 1.0.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=20.0, pending_yield_pct=8.0,
            vesting_progress_pct=150.0, forfeit_mode="LINEAR"))
        self.assertAlmostEqual(r["forfeited_yield_pct"], 0.0, places=4)
        self.assertEqual(r["vesting_progress_pct"], 100.0)

    def test_linear_vesting_clamp_negative(self):
        # negative vesting_progress_pct → 0.0.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=20.0, pending_yield_pct=8.0,
            vesting_progress_pct=-30.0, forfeit_mode="LINEAR"))
        self.assertAlmostEqual(r["forfeited_yield_pct"], 8.0, places=4)
        self.assertEqual(r["vesting_progress_pct"], 0.0)

    def test_linear_safe_fraction_differs_from_realization(self):
        # partial vesting → safe_fraction (1 - pending/total) != realization.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=20.0, pending_yield_pct=8.0,
            vesting_progress_pct=80.0, forfeit_mode="LINEAR"))
        self.assertAlmostEqual(r["safe_fraction"], 1.0 - 8.0 / 20.0, places=4)
        self.assertNotAlmostEqual(r["safe_fraction"], r["realization_ratio"],
                                  places=3)


# ── geometry / clamping ─────────────────────────────────────────────────────

class TestGeometryClamping(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer()

    def test_pending_over_total_clamps(self):
        # pending > total → clamps to total → full forfeiture (CLIFF).
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=10.0, pending_yield_pct=25.0,
            forfeit_mode="CLIFF"))
        self.assertAlmostEqual(r["pending_yield_pct"], 10.0, places=4)
        self.assertAlmostEqual(r["forfeited_yield_pct"], 10.0, places=4)
        self.assertEqual(r["forfeiture_fraction"], 1.0)
        self.assertTrue(r["full_forfeiture"])

    def test_pending_negative_clamps_to_zero(self):
        # negative pending → 0 → NO_FORFEITURE.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=10.0, pending_yield_pct=-5.0,
            forfeit_mode="CLIFF"))
        self.assertAlmostEqual(r["pending_yield_pct"], 0.0, places=4)
        self.assertEqual(r["classification"], "NO_FORFEITURE")

    def test_kept_yield_pct(self):
        # kept == total - forfeited.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        self.assertAlmostEqual(r["kept_yield_pct"], 9.0, places=4)

    def test_safe_fraction_equals_realization_cliff(self):
        # CLIFF: safe_fraction == realization_ratio.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        self.assertAlmostEqual(r["safe_fraction"], r["realization_ratio"],
                               places=4)

    def test_safe_fraction_formula_main(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        self.assertAlmostEqual(r["safe_fraction"], 1.0 - 6.0 / 15.0, places=4)

    def test_full_forfeiture_flag(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=12.0, pending_yield_pct=12.0,
            forfeit_mode="CLIFF"))
        self.assertTrue(r["full_forfeiture"])
        self.assertIn("FULL_FORFEITURE", r["flags"])

    def test_no_full_forfeiture_partial(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        self.assertFalse(r["full_forfeiture"])
        self.assertNotIn("FULL_FORFEITURE", r["flags"])

    def test_realization_ratio_formula(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        self.assertAlmostEqual(r["realization_ratio"],
                               1.0 - r["forfeiture_fraction"], places=4)


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer()

    def test_classification_first_flag(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        self.assertEqual(r["flags"][0], r["classification"])

    def test_classification_always_in_flags(self):
        for pending in (0.0, 2.0, 6.0, 16.0):
            r = self.an.analyze(make_pos(
                total_accrued_yield_pct=20.0, pending_yield_pct=pending,
                forfeit_mode="CLIFF"))
            self.assertIn(r["classification"], r["flags"])

    def test_pending_at_risk_flag(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        self.assertIn("PENDING_YIELD_AT_RISK", r["flags"])

    def test_no_pending_at_risk_when_zero(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=0.0,
            forfeit_mode="CLIFF"))
        self.assertNotIn("PENDING_YIELD_AT_RISK", r["flags"])

    def test_cliff_vesting_flag(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        self.assertIn("CLIFF_VESTING", r["flags"])
        self.assertNotIn("LINEAR_VESTING", r["flags"])

    def test_linear_vesting_flag(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=20.0, pending_yield_pct=8.0,
            vesting_progress_pct=80.0, forfeit_mode="LINEAR"))
        self.assertIn("LINEAR_VESTING", r["flags"])
        self.assertNotIn("CLIFF_VESTING", r["flags"])

    def test_long_cooldown_flag_at_threshold(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF", cooldown_days=14.0))
        self.assertIn("LONG_COOLDOWN", r["flags"])

    def test_long_cooldown_flag_above(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF", cooldown_days=21.0))
        self.assertIn("LONG_COOLDOWN", r["flags"])

    def test_no_long_cooldown_below(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF", cooldown_days=7.0))
        self.assertNotIn("LONG_COOLDOWN", r["flags"])

    def test_no_long_cooldown_when_missing(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        self.assertNotIn("LONG_COOLDOWN", r["flags"])

    def test_fully_vested_exit_flag(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=0.0,
            forfeit_mode="CLIFF"))
        self.assertIn("FULLY_VESTED_EXIT", r["flags"])


# ── override path ─────────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer()

    def test_override_basic(self):
        # forfeited 3 of total 24 → fraction 0.125 → MILD.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=24.0, forfeited_yield_pct=3.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_main"])
        self.assertAlmostEqual(r["forfeiture_fraction"], 0.125, places=4)
        self.assertEqual(r["classification"], "MILD_FORFEITURE")

    def test_override_gap_flag(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=24.0, forfeited_yield_pct=3.0))
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])

    def test_override_geometry_none(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=24.0, forfeited_yield_pct=3.0))
        self.assertIsNone(r["pending_yield_pct"])
        self.assertIsNone(r["vesting_progress_pct"])
        self.assertIsNone(r["forfeit_mode"])

    def test_override_geometry_flags_suppressed(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=24.0, forfeited_yield_pct=3.0))
        self.assertNotIn("PENDING_YIELD_AT_RISK", r["flags"])
        self.assertNotIn("FULL_FORFEITURE", r["flags"])
        self.assertNotIn("CLIFF_VESTING", r["flags"])
        self.assertNotIn("LINEAR_VESTING", r["flags"])

    def test_override_clamped_to_total(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=24.0, forfeited_yield_pct=99.0))
        self.assertAlmostEqual(r["forfeited_yield_pct"], 24.0, places=4)
        self.assertEqual(r["forfeiture_fraction"], 1.0)

    def test_override_negative_magnitude(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=24.0, forfeited_yield_pct=-3.0))
        self.assertAlmostEqual(r["forfeited_yield_pct"], 3.0, places=4)
        self.assertAlmostEqual(r["forfeiture_fraction"], 0.125, places=4)

    def test_override_fraction_formula(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=24.0, forfeited_yield_pct=6.0))
        self.assertAlmostEqual(r["forfeiture_fraction"], 6.0 / 24.0, places=4)

    def test_override_realization_anchor(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=24.0, forfeited_yield_pct=6.0))
        self.assertAlmostEqual(r["realization_ratio"],
                               1.0 - r["forfeiture_fraction"], places=4)

    def test_override_safe_fraction_anchored(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=24.0, forfeited_yield_pct=6.0))
        self.assertAlmostEqual(r["safe_fraction"], r["realization_ratio"],
                               places=4)

    def test_override_classification_still_computed(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=24.0, forfeited_yield_pct=18.0))
        self.assertEqual(r["classification"], "SEVERE_FORFEITURE")

    def test_override_long_cooldown_still_flagged(self):
        # LONG_COOLDOWN is not geometry-only → still raised on override.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=24.0, forfeited_yield_pct=3.0,
            cooldown_days=30.0))
        self.assertIn("LONG_COOLDOWN", r["flags"])
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])

    def test_override_zero_clean(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=24.0, forfeited_yield_pct=0.0))
        # forfeited 0 → fraction 0 → NO_FORFEITURE; still override path
        # (0.0 is finite).
        self.assertTrue(r["used_override"])
        self.assertEqual(r["classification"], "NO_FORFEITURE")


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer()

    def _assert_insufficient(self, r):
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["recommendation"], "AVOID_EARLY_EXIT")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_missing_total(self):
        r = self.an.analyze(make_pos(pending_yield_pct=5.0,
                                     forfeit_mode="CLIFF"))
        self._assert_insufficient(r)

    def test_none_total(self):
        r = self.an.analyze({"vault": "X", "total_accrued_yield_pct": None})
        self._assert_insufficient(r)

    def test_nan_total(self):
        r = self.an.analyze(make_pos(total_accrued_yield_pct=float("nan")))
        self._assert_insufficient(r)

    def test_inf_total(self):
        r = self.an.analyze(make_pos(total_accrued_yield_pct=float("inf")))
        self._assert_insufficient(r)

    def test_zero_total(self):
        r = self.an.analyze(make_pos(total_accrued_yield_pct=0.0))
        self._assert_insufficient(r)

    def test_negative_total(self):
        r = self.an.analyze(make_pos(total_accrued_yield_pct=-5.0))
        self._assert_insufficient(r)

    def test_non_numeric_string_total(self):
        r = self.an.analyze(make_pos(total_accrued_yield_pct="abc"))
        self._assert_insufficient(r)

    def test_insufficient_numeric_fields_none(self):
        r = self.an.analyze(make_pos(pending_yield_pct=5.0))
        for k in ("total_accrued_yield_pct", "pending_yield_pct",
                  "vesting_progress_pct", "forfeited_yield_pct",
                  "kept_yield_pct", "forfeiture_fraction",
                  "realization_ratio", "safe_fraction", "cooldown_days"):
            self.assertIsNone(r[k])


# ── token / vault key ─────────────────────────────────────────────────────────

class TestTokenKey(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer()

    def test_vault_key(self):
        r = self.an.analyze({"vault": "V", "total_accrued_yield_pct": 10.0,
                             "pending_yield_pct": 0.0})
        self.assertEqual(r["token"], "V")

    def test_token_key_fallback(self):
        r = self.an.analyze({"token": "TKN", "total_accrued_yield_pct": 10.0,
                             "pending_yield_pct": 0.0})
        self.assertEqual(r["token"], "TKN")

    def test_vault_preferred_over_token(self):
        r = self.an.analyze({"vault": "V", "token": "TKN",
                             "total_accrued_yield_pct": 10.0,
                             "pending_yield_pct": 0.0})
        self.assertEqual(r["token"], "V")

    def test_unknown_token(self):
        r = self.an.analyze({"total_accrued_yield_pct": 10.0,
                             "pending_yield_pct": 0.0})
        self.assertEqual(r["token"], "UNKNOWN")


# ── scoring ─────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer()

    def test_score_in_bounds(self):
        for pending in (0.0, 2.0, 6.0, 10.0, 16.0, 20.0):
            r = self.an.analyze(make_pos(
                total_accrued_yield_pct=20.0, pending_yield_pct=pending,
                forfeit_mode="CLIFF"))
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_score_monotone_with_forfeiture(self):
        prev = 101.0
        for pending in (0.0, 2.0, 6.0, 10.0, 16.0, 20.0):
            r = self.an.analyze(make_pos(
                total_accrued_yield_pct=20.0, pending_yield_pct=pending,
                forfeit_mode="CLIFF"))
            self.assertLessEqual(r["score"], prev + 1e-9)
            prev = r["score"]

    def test_score_insufficient_zero(self):
        r = self.an.analyze(make_pos())
        self.assertEqual(r["score"], 0.0)

    def test_score_weighting_linear_case(self):
        # total 20, pending 8, vested 80%, LINEAR.
        # forfeited 1.6 → fraction 0.08 → realization 0.92.
        # safe_fraction = 1 - 8/20 = 0.6.
        # score = 70*0.92 + 30*0.6 = 64.4 + 18.0 = 82.4.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=20.0, pending_yield_pct=8.0,
            vesting_progress_pct=80.0, forfeit_mode="LINEAR"))
        self.assertAlmostEqual(r["score"], 82.4, places=2)

    def test_score_cliff_case(self):
        # total 15, pending 6, CLIFF → realization 0.6, safe 0.6.
        # score = 70*0.6 + 30*0.6 = 60.0.
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        self.assertAlmostEqual(r["score"], 60.0, places=2)

    def test_score_no_forfeiture_full(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=0.0,
            forfeit_mode="CLIFF"))
        self.assertEqual(r["score"], 100.0)


# ── aggregate ─────────────────────────────────────────────────────────────────

class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer()

    def test_empty_list(self):
        agg = self.an.analyze_portfolio([])["aggregate"]
        self.assertIsNone(agg["cleanest_vault"])
        self.assertIsNone(agg["worst_forfeiture_vault"])
        self.assertEqual(agg["avg_score"], 0.0)
        self.assertEqual(agg["full_forfeiture_count"], 0)
        self.assertEqual(agg["position_count"], 0)

    def test_all_insufficient(self):
        positions = [make_pos(vault="X"), make_pos(vault="Y")]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertIsNone(agg["cleanest_vault"])
        self.assertIsNone(agg["worst_forfeiture_vault"])
        self.assertEqual(agg["avg_score"], 0.0)
        self.assertEqual(agg["full_forfeiture_count"], 0)
        self.assertEqual(agg["position_count"], 2)

    def test_cleanest_and_worst(self):
        positions = [
            make_pos(vault="Clean", total_accrued_yield_pct=20.0,
                     pending_yield_pct=0.0, forfeit_mode="CLIFF"),
            make_pos(vault="Bad", total_accrued_yield_pct=20.0,
                     pending_yield_pct=20.0, forfeit_mode="CLIFF"),
        ]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["cleanest_vault"], "Clean")
        self.assertEqual(agg["worst_forfeiture_vault"], "Bad")

    def test_full_forfeiture_count(self):
        positions = [
            make_pos(vault="A", total_accrued_yield_pct=20.0,
                     pending_yield_pct=20.0, forfeit_mode="CLIFF"),
            make_pos(vault="B", total_accrued_yield_pct=12.0,
                     pending_yield_pct=12.0, forfeit_mode="CLIFF"),
            make_pos(vault="C", total_accrued_yield_pct=20.0,
                     pending_yield_pct=2.0, forfeit_mode="CLIFF"),
        ]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["full_forfeiture_count"], 2)

    def test_position_count_includes_insufficient(self):
        positions = [
            make_pos(vault="A", total_accrued_yield_pct=20.0,
                     pending_yield_pct=2.0, forfeit_mode="CLIFF"),
            make_pos(vault="Bad"),
        ]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["position_count"], 2)

    def test_avg_score(self):
        positions = [
            make_pos(vault="A", total_accrued_yield_pct=20.0,
                     pending_yield_pct=0.0, forfeit_mode="CLIFF"),
            make_pos(vault="B", total_accrued_yield_pct=20.0,
                     pending_yield_pct=0.0, forfeit_mode="CLIFF"),
        ]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertAlmostEqual(agg["avg_score"], 100.0, places=2)


# ── public API shape ──────────────────────────────────────────────────────────

class TestApiShape(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer()

    def test_analyze_single_returns_dict(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        self.assertIsInstance(r, dict)
        self.assertNotIn("positions", r)

    def test_portfolio_structure(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertIn("positions", out)
        self.assertIn("aggregate", out)
        self.assertEqual(len(out["positions"]), len(_demo_positions()))

    def test_result_keys_stable_main(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        ins = self.an._insufficient("X")
        self.assertEqual(set(r.keys()), set(ins.keys()))

    def test_result_keys_stable_override(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=24.0, forfeited_yield_pct=3.0))
        ins = self.an._insufficient("X")
        self.assertEqual(set(r.keys()), set(ins.keys()))

    def test_documented_keys_present(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        for k in ("token", "total_accrued_yield_pct", "pending_yield_pct",
                  "vesting_progress_pct", "forfeited_yield_pct",
                  "kept_yield_pct", "forfeiture_fraction",
                  "realization_ratio", "safe_fraction", "full_forfeiture",
                  "forfeit_mode", "cooldown_days", "sample_count",
                  "used_override", "used_main", "score", "classification",
                  "recommendation", "grade", "flags"):
            self.assertIn(k, r)

    def test_sample_count_zero(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        self.assertEqual(r["sample_count"], 0)

    def test_used_main_flag(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
            forfeit_mode="CLIFF"))
        self.assertTrue(r["used_main"])
        self.assertFalse(r["used_override"])


# ── ring-buffer log ───────────────────────────────────────────────────────────

class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer()

    def _pos(self):
        return make_pos(total_accrued_yield_pct=15.0, pending_yield_pct=6.0,
                        forfeit_mode="CLIFF")

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "sub", "log.json")
            cfg = {"log_path": log_path, "log_cap": 100}
            self.an.analyze_portfolio(_demo_positions(), cfg=cfg,
                                      write_log=True)
            self.assertTrue(os.path.exists(log_path))
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)
            self.assertIn("aggregate", data[0])
            self.assertIn("snapshots", data[0])

    def test_no_write_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            self.an.analyze(self._pos(), cfg=cfg, write_log=False)
            self.assertFalse(os.path.exists(log_path))

    def test_log_appends(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 10}
            self.an.analyze([self._pos()] and self._pos(), cfg=cfg,
                            write_log=True)
            self.an.analyze(self._pos(), cfg=cfg, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 2)

    def test_log_ring_cap(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            for _ in range(5):
                self.an.analyze(self._pos(), cfg=cfg, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_log_keeps_newest(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 2}
            for i in range(4):
                pos = make_pos(vault="V%d" % i,
                               total_accrued_yield_pct=15.0,
                               pending_yield_pct=6.0, forfeit_mode="CLIFF")
                self.an.analyze(pos, cfg=cfg, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            tokens = [e["snapshots"][0]["token"] for e in data]
            self.assertEqual(tokens, ["V2", "V3"])

    def test_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            self.an.analyze(self._pos(), cfg=cfg, write_log=True)
            self.assertFalse(os.path.exists(log_path + ".tmp"))

    def test_log_corrupt_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            with open(log_path, "w") as fh:
                fh.write("not json{{{")
            cfg = {"log_path": log_path, "log_cap": 3}
            self.an.analyze(self._pos(), cfg=cfg, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_log_non_list_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            with open(log_path, "w") as fh:
                json.dump({"not": "a list"}, fh)
            cfg = {"log_path": log_path, "log_cap": 3}
            self.an.analyze(self._pos(), cfg=cfg, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_log_atomic_valid_json_list(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 10}
            self.an.analyze_portfolio(_demo_positions(), cfg=cfg,
                                      write_log=True)
            self.assertFalse(os.path.exists(log_path + ".tmp"))
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)


# ── invariants / finiteness ───────────────────────────────────────────────────

class TestInvariants(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer()

    def test_all_floats_finite_demo(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertTrue(_all_floats_finite(out))

    def test_no_infinity_or_nan_in_demo(self):
        out = self.an.analyze_portfolio(_demo_positions())
        s = json.dumps(out)
        self.assertNotIn("Infinity", s)
        self.assertNotIn("NaN", s)

    def test_score_bounds_grid(self):
        for total in (1.0, 5.0, 12.0, 30.0, 100.0):
            for pending in (0.0, total * 0.25, total * 0.5, total, total * 2):
                for mode in ("CLIFF", "LINEAR"):
                    for vp in (0.0, 50.0, 100.0):
                        r = self.an.analyze(make_pos(
                            total_accrued_yield_pct=total,
                            pending_yield_pct=pending,
                            vesting_progress_pct=vp, forfeit_mode=mode))
                        self.assertGreaterEqual(r["score"], 0.0)
                        self.assertLessEqual(r["score"], 100.0)
                        self.assertGreaterEqual(r["forfeiture_fraction"], 0.0)
                        self.assertLessEqual(r["forfeiture_fraction"], 1.0)
                        self.assertGreaterEqual(r["realization_ratio"], 0.0)
                        self.assertLessEqual(r["realization_ratio"], 1.0)
                        self.assertTrue(_all_floats_finite(r))

    def test_fraction_monotone_cliff(self):
        prev = -1.0
        for pending in (0.0, 2.0, 6.0, 10.0, 16.0, 20.0):
            r = self.an.analyze(make_pos(
                total_accrued_yield_pct=20.0, pending_yield_pct=pending,
                forfeit_mode="CLIFF"))
            self.assertGreaterEqual(r["forfeiture_fraction"], prev)
            prev = r["forfeiture_fraction"]

    def test_grade_matches_score(self):
        for pending in (0.0, 2.0, 6.0, 10.0, 16.0, 20.0):
            r = self.an.analyze(make_pos(
                total_accrued_yield_pct=20.0, pending_yield_pct=pending,
                forfeit_mode="CLIFF"))
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_string_numeric_inputs(self):
        r = self.an.analyze(make_pos(
            total_accrued_yield_pct="15", pending_yield_pct="6",
            forfeit_mode="CLIFF"))
        self.assertEqual(r["classification"], "MODERATE_FORFEITURE")


# ── CLI / demo ────────────────────────────────────────────────────────────────

class TestDemo(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer()

    def test_demo_positions_is_list(self):
        self.assertIsInstance(_demo_positions(), list)
        self.assertGreater(len(_demo_positions()), 0)

    def test_demo_runs_clean(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertTrue(_all_floats_finite(out))

    def test_demo_classifications(self):
        out = self.an.analyze_portfolio(_demo_positions())
        classes = {p["token"]: p["classification"] for p in out["positions"]}
        self.assertEqual(
            classes["USDC-Vault-FullyCrystallized"], "NO_FORFEITURE")
        self.assertEqual(
            classes["stETH-Vault-CliffExit"], "MODERATE_FORFEITURE")
        self.assertEqual(
            classes["GOV-Vault-FullForfeit"], "SEVERE_FORFEITURE")
        self.assertEqual(
            classes["LST-Vault-LinearVesting"], "MILD_FORFEITURE")
        self.assertEqual(
            classes["RWA-Vault-OverrideForfeit"], "MILD_FORFEITURE")
        self.assertEqual(
            classes["MYSTERY-Vault-NoData"], "INSUFFICIENT_DATA")

    def test_demo_json_serialisable(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertIsInstance(json.dumps(out), str)

    def test_demo_runs_all_paths(self):
        out = self.an.analyze_portfolio(_demo_positions())
        used_override = any(p["used_override"] for p in out["positions"])
        used_main = any(p["used_main"] for p in out["positions"])
        self.assertTrue(used_override)
        self.assertTrue(used_main)


if __name__ == "__main__":
    unittest.main(verbosity=2)
