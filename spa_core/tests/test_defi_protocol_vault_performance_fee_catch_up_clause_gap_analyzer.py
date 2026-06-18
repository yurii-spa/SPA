"""
Tests for MP-1212: DeFiProtocolVaultPerformanceFeeCatchUpClauseGapAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_performance_fee_catch_up_clause_gap_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_performance_fee_catch_up_clause_gap_analyzer import (  # noqa: E501
    DeFiProtocolVaultPerformanceFeeCatchUpClauseGapAnalyzer,
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
    HIGH_CATCHUP_RATE_PCT,
    EPS,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    gross_return_pct=None,
    hurdle_rate_pct=None,
    performance_fee_pct=None,
    catch_up_rate_pct=None,
    catchup_gap_pct=None,
    fee_charged_pct=None,
):
    pos = {"vault": vault}
    if gross_return_pct is not None:
        pos["gross_return_pct"] = gross_return_pct
    if hurdle_rate_pct is not None:
        pos["hurdle_rate_pct"] = hurdle_rate_pct
    if performance_fee_pct is not None:
        pos["performance_fee_pct"] = performance_fee_pct
    if catch_up_rate_pct is not None:
        pos["catch_up_rate_pct"] = catch_up_rate_pct
    if catchup_gap_pct is not None:
        pos["catchup_gap_pct"] = catchup_gap_pct
    if fee_charged_pct is not None:
        pos["fee_charged_pct"] = fee_charged_pct
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

    def test_mean(self):
        self.assertEqual(_mean([]), 0.0)
        self.assertEqual(_mean([2, 4]), 3.0)

    def test_safe_div(self):
        self.assertEqual(_safe_div(10, 2, None), 5.0)
        self.assertIsNone(_safe_div(10, 0, None))
        self.assertIsNone(_safe_div(10, -1, None))

    def test_coerce_num(self):
        self.assertEqual(_coerce_num(3), 3.0)
        self.assertEqual(_coerce_num("3.5"), 3.5)
        self.assertIsNone(_coerce_num(True))
        self.assertIsNone(_coerce_num(False))
        self.assertIsNone(_coerce_num(None))
        self.assertIsNone(_coerce_num("abc"))
        self.assertIsNone(_coerce_num(""))
        self.assertIsNone(_coerce_num(float("nan")))
        self.assertIsNone(_coerce_num(float("inf")))

    def test_coerce_signed(self):
        self.assertEqual(_coerce_signed(-5), -5.0)
        self.assertEqual(_coerce_signed("-2.5"), -2.5)
        self.assertIsNone(_coerce_signed(None))

    def test_coerce_count(self):
        self.assertEqual(_coerce_count(3), 3)
        self.assertEqual(_coerce_count("4"), 4)
        self.assertEqual(_coerce_count(0), 0)
        self.assertIsNone(_coerce_count(-1))
        self.assertIsNone(_coerce_count(None))
        self.assertIsNone(_coerce_count("x"))

    def test_build_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)
        cfg2 = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg2["log_cap"], 5)

    def test_grade_from_score(self):
        self.assertEqual(_grade_from_score(90), "A")
        self.assertEqual(_grade_from_score(85), "A")
        self.assertEqual(_grade_from_score(75), "B")
        self.assertEqual(_grade_from_score(70), "B")
        self.assertEqual(_grade_from_score(60), "C")
        self.assertEqual(_grade_from_score(55), "C")
        self.assertEqual(_grade_from_score(45), "D")
        self.assertEqual(_grade_from_score(40), "D")
        self.assertEqual(_grade_from_score(10), "F")

    def test_thresholds_ordered(self):
        self.assertLess(CLEAN_FRACTION, MILD_FRACTION)
        self.assertLess(MILD_FRACTION, MODERATE_FRACTION)
        self.assertGreater(EPS, 0.0)
        self.assertGreater(HIGH_CATCHUP_RATE_PCT, 0.0)


# ── main path classification ──────────────────────────────────────────────────

class TestMainPathClassification(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeCatchUpClauseGapAnalyzer())

    def test_clean_hard_hurdle_low_catchup(self):
        # catch-up barely above the straight fee, gross only just clears hurdle →
        # recoup ≈ 0 → CLEAN.
        r = self.an.analyze(make_pos(
            gross_return_pct=10.5, hurdle_rate_pct=10.0,
            performance_fee_pct=20.0, catch_up_rate_pct=22.0))
        self.assertEqual(r["classification"], "CLEAN_HARD_HURDLE")
        self.assertIn("HURDLE_HONOURED", r["flags"])
        self.assertLessEqual(r["catchup_recoup_fraction"], CLEAN_FRACTION)
        self.assertGreaterEqual(r["score"], 85.0)
        self.assertEqual(r["grade"], "A")
        self.assertEqual(r["recommendation"], "TRUST_FEE_STRUCTURE")

    def test_no_hurdle_is_clean(self):
        # hurdle = 0 → nothing to exempt → nothing to claw back → CLEAN.
        r = self.an.analyze(make_pos(
            gross_return_pct=18.0, hurdle_rate_pct=0.0,
            performance_fee_pct=20.0, catch_up_rate_pct=100.0))
        self.assertEqual(r["classification"], "CLEAN_HARD_HURDLE")
        self.assertEqual(r["catchup_gap_pct"], 0.0)
        self.assertEqual(r["catchup_recoup_fraction"], 0.0)
        self.assertEqual(r["hurdle_value_pct"], 0.0)

    def test_no_hurdle_default_missing(self):
        # no hurdle_rate_pct supplied → default 0 → CLEAN.
        r = self.an.analyze(make_pos(
            gross_return_pct=18.0, performance_fee_pct=20.0,
            catch_up_rate_pct=100.0))
        self.assertEqual(r["hurdle_rate_pct"], 0.0)
        self.assertEqual(r["classification"], "CLEAN_HARD_HURDLE")

    def test_mild_catchup_gap(self):
        # gross 14, hurdle 8, fee 20%, catch_up 25% → partial, recoup ≈ 0.156.
        r = self.an.analyze(make_pos(
            gross_return_pct=14.0, hurdle_rate_pct=8.0,
            performance_fee_pct=20.0, catch_up_rate_pct=25.0))
        self.assertEqual(r["classification"], "MILD_CATCHUP_GAP")
        self.assertEqual(r["recommendation"], "MINOR_CATCHUP_GAP")
        self.assertGreater(r["catchup_recoup_fraction"], CLEAN_FRACTION)
        self.assertLessEqual(r["catchup_recoup_fraction"], MILD_FRACTION)

    def test_moderate_catchup_gap(self):
        # gross 14, hurdle 8, fee 20%, catch_up 30% → recoup = 0.375 → MODERATE.
        r = self.an.analyze(make_pos(
            gross_return_pct=14.0, hurdle_rate_pct=8.0,
            performance_fee_pct=20.0, catch_up_rate_pct=30.0))
        self.assertEqual(r["classification"], "MODERATE_CATCHUP_GAP")
        self.assertAlmostEqual(r["catchup_recoup_fraction"], 0.375, places=4)
        self.assertIn("FEE_ON_HURDLE_BAND", r["flags"])
        self.assertEqual(r["recommendation"], "DEMAND_HARD_HURDLE")

    def test_severe_full_catchup(self):
        # gross 20, hurdle 10, fee 20%, catch_up 100% → full catch-up, recoup=1.
        r = self.an.analyze(make_pos(
            gross_return_pct=20.0, hurdle_rate_pct=10.0,
            performance_fee_pct=20.0, catch_up_rate_pct=100.0))
        self.assertEqual(r["classification"], "SEVERE_CATCHUP_GAP")
        self.assertAlmostEqual(r["catchup_recoup_fraction"], 1.0, places=4)
        self.assertIn("FULL_CATCHUP", r["flags"])
        self.assertIn("HIGH_CATCHUP_RATE", r["flags"])
        self.assertEqual(r["recommendation"], "AVOID_CATCHUP_CLAUSE")

    def test_fee_on_hurdle_band_flag(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=14.0, hurdle_rate_pct=8.0,
            performance_fee_pct=20.0, catch_up_rate_pct=30.0))
        self.assertIn("FEE_ON_HURDLE_BAND", r["flags"])

    def test_high_catchup_rate_flag(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=20.0, hurdle_rate_pct=10.0,
            performance_fee_pct=20.0, catch_up_rate_pct=100.0))
        self.assertIn("HIGH_CATCHUP_RATE", r["flags"])

    def test_low_catchup_rate_no_flag(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=10.5, hurdle_rate_pct=10.0,
            performance_fee_pct=20.0, catch_up_rate_pct=22.0))
        self.assertNotIn("HIGH_CATCHUP_RATE", r["flags"])

    def test_catch_up_default_100(self):
        # no catch_up_rate_pct supplied → default 100% → full catch-up.
        r = self.an.analyze(make_pos(
            gross_return_pct=20.0, hurdle_rate_pct=10.0,
            performance_fee_pct=20.0))
        self.assertIsNone(r["catch_up_rate_pct"])
        self.assertAlmostEqual(r["catchup_recoup_fraction"], 1.0, places=4)
        self.assertEqual(r["classification"], "SEVERE_CATCHUP_GAP")


# ── math correctness ──────────────────────────────────────────────────────────

class TestMath(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeCatchUpClauseGapAnalyzer())

    def test_partial_catchup_geometry(self):
        # gross 14, hurdle 8, fee 20%, catch_up 30%.
        # fee_frac=0.2, excess=6, fair=1.2, full_fee=2.8.
        # x_full=0.2*8/(0.3-0.2)=16; excess 6<16 → partial.
        # fee_charged=min(0.3*6, 2.8)=1.8; gap=0.6; hurdle_value=0.2*8=1.6.
        # recoup=0.6/1.6=0.375.
        r = self.an.analyze(make_pos(
            gross_return_pct=14.0, hurdle_rate_pct=8.0,
            performance_fee_pct=20.0, catch_up_rate_pct=30.0))
        self.assertAlmostEqual(r["excess_return_pct"], 6.0)
        self.assertAlmostEqual(r["fair_fee_pct"], 1.2)
        self.assertAlmostEqual(r["fee_charged_pct"], 1.8)
        self.assertAlmostEqual(r["catchup_gap_pct"], 0.6)
        self.assertAlmostEqual(r["hurdle_value_pct"], 1.6)
        self.assertAlmostEqual(r["catchup_recoup_fraction"], 0.375, places=4)
        self.assertAlmostEqual(r["overstatement_pct"], 0.6)

    def test_full_catchup_geometry(self):
        # gross 20, hurdle 10, fee 20%, catch_up 100%.
        # excess=10, fair=2, full_fee=4. x_full=0.2*10/0.8=2.5; excess>=2.5 → full.
        # fee_charged=4; gap=2; hurdle_value=2; recoup=1.0.
        r = self.an.analyze(make_pos(
            gross_return_pct=20.0, hurdle_rate_pct=10.0,
            performance_fee_pct=20.0, catch_up_rate_pct=100.0))
        self.assertAlmostEqual(r["fee_charged_pct"], 4.0)
        self.assertAlmostEqual(r["fair_fee_pct"], 2.0)
        self.assertAlmostEqual(r["catchup_gap_pct"], 2.0)
        self.assertAlmostEqual(r["hurdle_value_pct"], 2.0)
        self.assertAlmostEqual(r["catchup_recoup_fraction"], 1.0, places=4)

    def test_partial_vs_full_boundary(self):
        # At exactly x_full the result equals full catch-up; below it is strictly
        # less. Compare a partial against a full for the same hurdle.
        partial = self.an.analyze(make_pos(
            gross_return_pct=14.0, hurdle_rate_pct=8.0,
            performance_fee_pct=20.0, catch_up_rate_pct=30.0))
        full = self.an.analyze(make_pos(
            gross_return_pct=20.0, hurdle_rate_pct=10.0,
            performance_fee_pct=20.0, catch_up_rate_pct=100.0))
        self.assertLess(partial["catchup_recoup_fraction"],
                        full["catchup_recoup_fraction"])

    def test_catch_up_rate_at_fee_frac_never_full(self):
        # catch_up_rate == fee_frac → x_full = inf → never full; fee_charged is
        # capped at the straight fee on the excess.
        r = self.an.analyze(make_pos(
            gross_return_pct=20.0, hurdle_rate_pct=10.0,
            performance_fee_pct=20.0, catch_up_rate_pct=20.0))
        # catch_up_rate=0.2, fee_frac=0.2, excess=10 → fee_charged=min(0.2*10,4)=2
        # fair=0.2*10=2 → gap=0 → CLEAN.
        self.assertAlmostEqual(r["fee_charged_pct"], 2.0)
        self.assertAlmostEqual(r["catchup_gap_pct"], 0.0)
        self.assertEqual(r["classification"], "CLEAN_HARD_HURDLE")

    def test_fee_charged_capped_at_full_fee(self):
        # a high catch-up rate can never push the fee above fee_frac*gross.
        r = self.an.analyze(make_pos(
            gross_return_pct=20.0, hurdle_rate_pct=2.0,
            performance_fee_pct=20.0, catch_up_rate_pct=100.0))
        full_fee = 0.2 * 20.0
        self.assertLessEqual(r["fee_charged_pct"], full_fee + 1e-9)

    def test_score_formula(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=14.0, hurdle_rate_pct=8.0,
            performance_fee_pct=20.0, catch_up_rate_pct=30.0))
        rr = r["realization_ratio"]
        frac = r["catchup_recoup_fraction"]
        expected = 70.0 * rr + 30.0 * (1.0 - frac)
        self.assertAlmostEqual(r["score"], round(expected, 2), places=2)

    def test_clean_score_high(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=18.0, hurdle_rate_pct=0.0,
            performance_fee_pct=20.0, catch_up_rate_pct=100.0))
        # no hurdle → fair == charged → realization 1.0, recoup 0 → score 100.
        self.assertEqual(r["realization_ratio"], 1.0)
        self.assertEqual(r["score"], 100.0)

    def test_fee_rate_clamped_over_100(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=18.0, hurdle_rate_pct=0.0,
            performance_fee_pct=250.0))
        self.assertEqual(r["performance_fee_pct"], 100.0)

    def test_fee_rate_zero(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=20.0, hurdle_rate_pct=8.0,
            performance_fee_pct=0.0, catch_up_rate_pct=100.0))
        self.assertEqual(r["performance_fee_pct"], 0.0)
        self.assertEqual(r["fee_charged_pct"], 0.0)
        self.assertEqual(r["catchup_gap_pct"], 0.0)
        self.assertEqual(r["catchup_recoup_fraction"], 0.0)
        self.assertEqual(r["classification"], "CLEAN_HARD_HURDLE")

    def test_fee_rate_negative_clamped(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=20.0, hurdle_rate_pct=8.0,
            performance_fee_pct=-20.0, catch_up_rate_pct=100.0))
        self.assertEqual(r["performance_fee_pct"], 0.0)
        self.assertEqual(r["fee_charged_pct"], 0.0)
        self.assertEqual(r["catchup_gap_pct"], 0.0)

    def test_negative_hurdle_clamped_zero(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=18.0, hurdle_rate_pct=-5.0,
            performance_fee_pct=20.0, catch_up_rate_pct=100.0))
        self.assertEqual(r["hurdle_rate_pct"], 0.0)
        self.assertEqual(r["classification"], "CLEAN_HARD_HURDLE")

    def test_gross_below_hurdle_no_excess(self):
        # gross under the hurdle → excess 0, fair 0, fee 0, no gap, clean.
        r = self.an.analyze(make_pos(
            gross_return_pct=5.0, hurdle_rate_pct=10.0,
            performance_fee_pct=20.0, catch_up_rate_pct=100.0))
        self.assertEqual(r["excess_return_pct"], 0.0)
        self.assertEqual(r["fee_charged_pct"], 0.0)
        self.assertEqual(r["catchup_gap_pct"], 0.0)
        self.assertEqual(r["classification"], "CLEAN_HARD_HURDLE")

    def test_hurdle_value_caps_gap(self):
        # the catchup_gap can never exceed hurdle_value → recoup in [0,1].
        for catch in (25.0, 40.0, 60.0, 100.0):
            r = self.an.analyze(make_pos(
                gross_return_pct=20.0, hurdle_rate_pct=10.0,
                performance_fee_pct=20.0, catch_up_rate_pct=catch))
            self.assertLessEqual(r["catchup_gap_pct"],
                                 r["hurdle_value_pct"] + 1e-9)
            self.assertLessEqual(r["catchup_recoup_fraction"], 1.0)
            self.assertGreaterEqual(r["catchup_recoup_fraction"], 0.0)

    def test_net_return_fields(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=20.0, hurdle_rate_pct=10.0,
            performance_fee_pct=20.0, catch_up_rate_pct=100.0))
        # net_after = 20 - 4 = 16 ; net_fair = 20 - 2 = 18.
        self.assertAlmostEqual(r["net_return_after_fee_pct"], 16.0)
        self.assertAlmostEqual(r["net_return_fair_pct"], 18.0)
        self.assertAlmostEqual(r["realization_ratio"], 16.0 / 18.0, places=4)

    def test_net_never_negative_main_path(self):
        # by construction fair_fee <= gross, so the fair net is non-negative.
        r = self.an.analyze(make_pos(
            gross_return_pct=12.0, hurdle_rate_pct=2.0,
            performance_fee_pct=100.0, catch_up_rate_pct=100.0))
        self.assertFalse(r["net_is_negative"])
        self.assertGreaterEqual(r["net_return_fair_pct"], 0.0)


# ── override path ─────────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeCatchUpClauseGapAnalyzer())

    def test_override_basic(self):
        # gap 4.8, fee_charged 12 → recoup = 0.4 → MODERATE.
        r = self.an.analyze(make_pos(
            gross_return_pct=24.0, catchup_gap_pct=4.8,
            fee_charged_pct=12.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_main"])
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])
        self.assertAlmostEqual(r["catchup_recoup_fraction"], 0.4, places=4)
        self.assertEqual(r["classification"], "MODERATE_CATCHUP_GAP")

    def test_override_geometry_none(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=24.0, catchup_gap_pct=4.8,
            fee_charged_pct=12.0))
        self.assertIsNone(r["hurdle_rate_pct"])
        self.assertIsNone(r["excess_return_pct"])
        self.assertIsNone(r["hurdle_value_pct"])
        self.assertIsNone(r["net_return_after_fee_pct"])
        self.assertIsNone(r["net_return_fair_pct"])
        self.assertIsNone(r["performance_fee_pct"])

    def test_override_geometry_flags_suppressed(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=24.0, catchup_gap_pct=4.8,
            fee_charged_pct=12.0))
        self.assertNotIn("FEE_ON_HURDLE_BAND", r["flags"])
        self.assertNotIn("FULL_CATCHUP", r["flags"])
        self.assertNotIn("HIGH_CATCHUP_RATE", r["flags"])
        self.assertNotIn("NET_NEGATIVE_AFTER_FEE", r["flags"])

    def test_override_negative_gap_magnitude(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=24.0, catchup_gap_pct=-4.8,
            fee_charged_pct=12.0))
        self.assertAlmostEqual(r["catchup_gap_pct"], 4.8, places=4)

    def test_override_gap_capped_at_fee_charged(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=24.0, catchup_gap_pct=99.0,
            fee_charged_pct=12.0))
        self.assertEqual(r["catchup_gap_pct"], 12.0)
        self.assertEqual(r["catchup_recoup_fraction"], 1.0)
        self.assertEqual(r["fair_fee_pct"], 0.0)

    def test_override_realization_anchor(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=24.0, catchup_gap_pct=3.0,
            fee_charged_pct=12.0))
        frac = r["catchup_recoup_fraction"]
        self.assertAlmostEqual(r["realization_ratio"], 1.0 - frac, places=4)

    def test_override_denominator_is_fee_charged(self):
        # recoup uses fee_charged as the denominator on the override path.
        r = self.an.analyze(make_pos(
            gross_return_pct=24.0, catchup_gap_pct=3.0,
            fee_charged_pct=12.0))
        self.assertAlmostEqual(r["catchup_recoup_fraction"], 3.0 / 12.0,
                               places=4)

    def test_override_with_high_catchup_rate_no_geometry_flag(self):
        # override path: HIGH_CATCHUP_RATE is geometry-only → suppressed.
        r = self.an.analyze(make_pos(
            gross_return_pct=24.0, catchup_gap_pct=3.0,
            fee_charged_pct=12.0, catch_up_rate_pct=100.0))
        self.assertNotIn("HIGH_CATCHUP_RATE", r["flags"])
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])
        # but the rate is still echoed back on the result.
        self.assertEqual(r["catch_up_rate_pct"], 100.0)

    def test_override_requires_positive_fee_charged(self):
        # fee_charged = 0 → not override path → falls to main path.
        r = self.an.analyze(make_pos(
            gross_return_pct=24.0, catchup_gap_pct=3.0,
            fee_charged_pct=0.0, performance_fee_pct=20.0,
            hurdle_rate_pct=0.0))
        self.assertFalse(r["used_override"])
        self.assertTrue(r["used_main"])

    def test_override_clean_when_small_gap(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=24.0, catchup_gap_pct=0.3,
            fee_charged_pct=12.0))
        self.assertEqual(r["classification"], "CLEAN_HARD_HURDLE")
        self.assertIn("HURDLE_HONOURED", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeCatchUpClauseGapAnalyzer())

    def test_missing_gross(self):
        r = self.an.analyze(make_pos(performance_fee_pct=20.0,
                                     hurdle_rate_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_zero_gross(self):
        r = self.an.analyze(make_pos(gross_return_pct=0.0,
                                     performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_gross(self):
        r = self.an.analyze(make_pos(gross_return_pct=-5.0,
                                     performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_gross(self):
        r = self.an.analyze(make_pos(gross_return_pct=float("nan"),
                                     performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_gross(self):
        r = self.an.analyze(make_pos(gross_return_pct=float("inf"),
                                     performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_fee_main_path(self):
        r = self.an.analyze(make_pos(gross_return_pct=10.0,
                                     hurdle_rate_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_invalid_fee_main_path(self):
        r = self.an.analyze(make_pos(gross_return_pct=10.0,
                                     hurdle_rate_pct=5.0,
                                     performance_fee_pct=float("nan")))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_all_none(self):
        r = self.an.analyze(make_pos(gross_return_pct=10.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        for k in ("net_return_after_fee_pct", "fee_charged_pct",
                  "catchup_gap_pct", "realization_ratio",
                  "catchup_recoup_fraction", "hurdle_value_pct"):
            self.assertIsNone(r[k])

    def test_insufficient_recommendation(self):
        r = self.an.analyze(make_pos(performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"], "AVOID_CATCHUP_CLAUSE")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeCatchUpClauseGapAnalyzer())

    def test_hurdle_honoured_flag(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=18.0, hurdle_rate_pct=0.0,
            performance_fee_pct=20.0))
        self.assertIn("HURDLE_HONOURED", r["flags"])

    def test_full_catchup_flag(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=20.0, hurdle_rate_pct=10.0,
            performance_fee_pct=20.0, catch_up_rate_pct=100.0))
        self.assertIn("FULL_CATCHUP", r["flags"])

    def test_no_full_catchup_when_partial(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=14.0, hurdle_rate_pct=8.0,
            performance_fee_pct=20.0, catch_up_rate_pct=30.0))
        self.assertNotIn("FULL_CATCHUP", r["flags"])

    def test_classification_always_in_flags(self):
        for catch in (22.0, 25.0, 30.0, 100.0):
            r = self.an.analyze(make_pos(
                gross_return_pct=18.0, hurdle_rate_pct=8.0,
                performance_fee_pct=20.0, catch_up_rate_pct=catch))
            self.assertIn(r["classification"], r["flags"])

    def test_no_full_catchup_without_hurdle(self):
        # hurdle 0 → no FULL_CATCHUP even with 100% catch-up.
        r = self.an.analyze(make_pos(
            gross_return_pct=18.0, hurdle_rate_pct=0.0,
            performance_fee_pct=20.0, catch_up_rate_pct=100.0))
        self.assertNotIn("FULL_CATCHUP", r["flags"])


# ── aggregate ─────────────────────────────────────────────────────────────────

class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeCatchUpClauseGapAnalyzer())

    def test_portfolio_structure(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertIn("positions", out)
        self.assertIn("aggregate", out)
        self.assertEqual(len(out["positions"]), 5)
        agg = out["aggregate"]
        self.assertEqual(agg["position_count"], 5)
        self.assertIn("cleanest_vault", agg)
        self.assertIn("worst_catchup_vault", agg)

    def test_aggregate_cleanest_and_worst(self):
        positions = [
            make_pos(vault="Clean", gross_return_pct=18.0,
                     hurdle_rate_pct=0.0, performance_fee_pct=20.0),
            make_pos(vault="Bad", gross_return_pct=20.0,
                     hurdle_rate_pct=10.0, performance_fee_pct=20.0,
                     catch_up_rate_pct=100.0),
        ]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["cleanest_vault"], "Clean")
        self.assertEqual(agg["worst_catchup_vault"], "Bad")

    def test_aggregate_all_insufficient(self):
        positions = [make_pos(vault="X"), make_pos(vault="Y")]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertIsNone(agg["cleanest_vault"])
        self.assertIsNone(agg["worst_catchup_vault"])
        self.assertEqual(agg["avg_score"], 0.0)
        self.assertEqual(agg["position_count"], 2)

    def test_aggregate_net_negative_count(self):
        # net-negative is structurally unreachable on the main path → count 0.
        agg = self.an.analyze_portfolio(_demo_positions())["aggregate"]
        self.assertEqual(agg["net_negative_count"], 0)

    def test_aggregate_avg_score(self):
        positions = [
            make_pos(vault="A", gross_return_pct=18.0, hurdle_rate_pct=0.0,
                     performance_fee_pct=20.0),
            make_pos(vault="B", gross_return_pct=18.0, hurdle_rate_pct=0.0,
                     performance_fee_pct=20.0),
        ]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertAlmostEqual(agg["avg_score"], 100.0, places=2)


# ── ring-buffer log ───────────────────────────────────────────────────────────

class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeCatchUpClauseGapAnalyzer())

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

    def test_log_ring_cap(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            for _ in range(5):
                self.an.analyze_portfolio(
                    [make_pos(gross_return_pct=14.0, hurdle_rate_pct=8.0,
                              performance_fee_pct=20.0,
                              catch_up_rate_pct=30.0)],
                    cfg=cfg, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_log_corrupt_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            with open(log_path, "w") as fh:
                fh.write("not json{{{")
            cfg = {"log_path": log_path, "log_cap": 3}
            self.an.analyze_portfolio(
                [make_pos(gross_return_pct=14.0, hurdle_rate_pct=8.0,
                          performance_fee_pct=20.0, catch_up_rate_pct=30.0)],
                cfg=cfg, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            self.an.analyze(make_pos(gross_return_pct=14.0, hurdle_rate_pct=8.0,
                                     performance_fee_pct=20.0,
                                     catch_up_rate_pct=30.0),
                            cfg=cfg, write_log=True)
            self.assertFalse(os.path.exists(log_path + ".tmp"))

    def test_no_write_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            self.an.analyze(make_pos(gross_return_pct=14.0, hurdle_rate_pct=8.0,
                                     performance_fee_pct=20.0,
                                     catch_up_rate_pct=30.0),
                            cfg=cfg, write_log=False)
            self.assertFalse(os.path.exists(log_path))


# ── invariants / finiteness ───────────────────────────────────────────────────

class TestInvariants(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeCatchUpClauseGapAnalyzer())

    def test_all_floats_finite(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertTrue(_all_floats_finite(out))

    def test_no_infinity_or_nan_in_demo(self):
        out = self.an.analyze_portfolio(_demo_positions())
        s = json.dumps(out)
        self.assertNotIn("Infinity", s)
        self.assertNotIn("NaN", s)

    def test_score_bounds_random_grid(self):
        for gross in (1.0, 5.0, 12.0, 30.0, 100.0):
            for hurdle in (0.0, 2.0, 8.0, gross, gross + 5.0):
                for fee in (0.0, 10.0, 20.0, 50.0, 100.0):
                    for catch in (10.0, 30.0, 100.0):
                        r = self.an.analyze(make_pos(
                            gross_return_pct=gross, hurdle_rate_pct=hurdle,
                            performance_fee_pct=fee, catch_up_rate_pct=catch))
                        self.assertGreaterEqual(r["score"], 0.0)
                        self.assertLessEqual(r["score"], 100.0)
                        self.assertGreaterEqual(
                            r["catchup_recoup_fraction"], 0.0)
                        self.assertLessEqual(
                            r["catchup_recoup_fraction"], 1.0)
                        self.assertGreaterEqual(r["realization_ratio"], 0.0)
                        self.assertLessEqual(r["realization_ratio"], 1.0)
                        self.assertTrue(_all_floats_finite(r))

    def test_recoup_monotone_with_catchup_rate(self):
        # holding gross/hurdle/fee fixed, higher catch-up rate → larger (or equal)
        # recoup fraction (monotone non-decreasing).
        prev = -1.0
        for catch in (20.0, 25.0, 30.0, 50.0, 100.0):
            r = self.an.analyze(make_pos(
                gross_return_pct=20.0, hurdle_rate_pct=10.0,
                performance_fee_pct=20.0, catch_up_rate_pct=catch))
            self.assertGreaterEqual(r["catchup_recoup_fraction"], prev)
            prev = r["catchup_recoup_fraction"]

    def test_token_fallback(self):
        r = self.an.analyze({"token": "TKN", "gross_return_pct": 18.0,
                             "hurdle_rate_pct": 0.0,
                             "performance_fee_pct": 20.0})
        self.assertEqual(r["token"], "TKN")

    def test_unknown_token(self):
        r = self.an.analyze({"gross_return_pct": 18.0,
                             "hurdle_rate_pct": 0.0,
                             "performance_fee_pct": 20.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_string_numeric_inputs(self):
        r = self.an.analyze(make_pos(
            gross_return_pct="14", hurdle_rate_pct="8",
            performance_fee_pct="20", catch_up_rate_pct="30"))
        self.assertEqual(r["classification"], "MODERATE_CATCHUP_GAP")

    def test_result_keys_stable(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=14.0, hurdle_rate_pct=8.0,
            performance_fee_pct=20.0, catch_up_rate_pct=30.0))
        ins = self.an._insufficient("X")
        self.assertEqual(set(r.keys()), set(ins.keys()))

    def test_override_keys_stable(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=24.0, catchup_gap_pct=4.8, fee_charged_pct=12.0))
        ins = self.an._insufficient("X")
        self.assertEqual(set(r.keys()), set(ins.keys()))


# ── grades / score boundaries ─────────────────────────────────────────────────

class TestGradesAndScore(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeCatchUpClauseGapAnalyzer())

    def test_clean_grade_a(self):
        r = self.an.analyze(make_pos(
            gross_return_pct=18.0, hurdle_rate_pct=0.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["grade"], "A")

    def test_severe_lower_grade(self):
        clean = self.an.analyze(make_pos(
            gross_return_pct=18.0, hurdle_rate_pct=0.0,
            performance_fee_pct=20.0))
        severe = self.an.analyze(make_pos(
            gross_return_pct=20.0, hurdle_rate_pct=10.0,
            performance_fee_pct=20.0, catch_up_rate_pct=100.0))
        self.assertLess(severe["score"], clean["score"])

    def test_score_zero_insufficient(self):
        r = self.an.analyze(make_pos(performance_fee_pct=20.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_grade_matches_score(self):
        for gross, hurdle, fee, catch in (
            (18.0, 0.0, 20.0, 100.0),
            (14.0, 8.0, 20.0, 30.0),
            (20.0, 10.0, 20.0, 100.0),
        ):
            r = self.an.analyze(make_pos(
                gross_return_pct=gross, hurdle_rate_pct=hurdle,
                performance_fee_pct=fee, catch_up_rate_pct=catch))
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── CLI / demo ────────────────────────────────────────────────────────────────

class TestDemo(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeCatchUpClauseGapAnalyzer())

    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 5)

    def test_demo_classifications(self):
        out = self.an.analyze_portfolio(_demo_positions())
        classes = {p["token"]: p["classification"] for p in out["positions"]}
        self.assertEqual(
            classes["USDC-Vault-CleanHardHurdle"], "CLEAN_HARD_HURDLE")
        self.assertEqual(
            classes["stETH-Vault-ModerateCatchup"], "MODERATE_CATCHUP_GAP")
        self.assertEqual(
            classes["GOV-Vault-SevereCatchup"], "SEVERE_CATCHUP_GAP")
        self.assertEqual(
            classes["LST-Vault-OverrideGap"], "MODERATE_CATCHUP_GAP")
        self.assertEqual(
            classes["MYSTERY-Vault-NoData"], "INSUFFICIENT_DATA")

    def test_demo_json_serialisable(self):
        out = self.an.analyze_portfolio(_demo_positions())
        s = json.dumps(out)
        self.assertIsInstance(s, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
