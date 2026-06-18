"""
Tests for MP-1215: DeFiProtocolVaultPerformanceFeeGrossOfReserveContributionBaseGapAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_performance_fee_gross_of_reserve_contribution_base_gap_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_performance_fee_gross_of_reserve_contribution_base_gap_analyzer import (  # noqa: E501
    DeFiProtocolVaultPerformanceFeeGrossOfReserveContributionBaseGapAnalyzer,
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
    HIGH_RESERVE_DIVERSION_PCT,
    EPS,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    gross_yield_pct=None,
    net_of_reserve_yield_pct=None,
    performance_fee_pct=None,
    reserve_contribution_rate_pct=None,
    fee_on_reserve_gap_pct=None,
    fee_charged_pct=None,
):
    pos = {"vault": vault}
    if gross_yield_pct is not None:
        pos["gross_yield_pct"] = gross_yield_pct
    if net_of_reserve_yield_pct is not None:
        pos["net_of_reserve_yield_pct"] = net_of_reserve_yield_pct
    if performance_fee_pct is not None:
        pos["performance_fee_pct"] = performance_fee_pct
    if reserve_contribution_rate_pct is not None:
        pos["reserve_contribution_rate_pct"] = reserve_contribution_rate_pct
    if fee_on_reserve_gap_pct is not None:
        pos["fee_on_reserve_gap_pct"] = fee_on_reserve_gap_pct
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
        self.assertGreater(HIGH_RESERVE_DIVERSION_PCT, 0.0)

    def test_high_reserve_diversion_value(self):
        self.assertEqual(HIGH_RESERVE_DIVERSION_PCT, 20.0)

    def test_log_path_filename(self):
        self.assertTrue(LOG_PATH.endswith(
            "vault_performance_fee_gross_of_reserve_contribution_base_gap_log.json"))


# ── main path classification ──────────────────────────────────────────────────

class TestMainPathClassification(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfReserveContributionBaseGapAnalyzer())

    def test_clean_net_of_reserve_base(self):
        # net_of_reserve == gross → reserve contribution consumed nothing → CLEAN.
        r = self.an.analyze(make_pos(
            gross_yield_pct=18.0, net_of_reserve_yield_pct=18.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "CLEAN_NET_OF_RESERVE_BASE")
        self.assertIn("CLEAN_NET_BASE", r["flags"])
        self.assertLessEqual(r["fee_on_reserve_fraction"], CLEAN_FRACTION)
        self.assertGreaterEqual(r["score"], 85.0)
        self.assertEqual(r["grade"], "A")
        self.assertEqual(r["recommendation"], "TRUST_FEE_STRUCTURE")

    def test_clean_default_net_zero_is_full(self):
        # no net supplied → default 0 → whole yield consumed → FULL.
        r = self.an.analyze(make_pos(
            gross_yield_pct=18.0, performance_fee_pct=20.0))
        self.assertEqual(r["net_of_reserve_yield_pct"], 0.0)
        self.assertIn("FULL_FEE_ON_RESERVE", r["flags"])

    def test_mild_fee_on_reserve_gap(self):
        # gross 20, net 18 → fraction = 0.1 → MILD.
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, net_of_reserve_yield_pct=18.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "MILD_FEE_ON_RESERVE_GAP")
        self.assertEqual(r["recommendation"], "MINOR_FEE_ON_RESERVE")
        self.assertGreater(r["fee_on_reserve_fraction"], CLEAN_FRACTION)
        self.assertLessEqual(r["fee_on_reserve_fraction"], MILD_FRACTION)

    def test_moderate_fee_on_reserve_gap(self):
        # gross 16, net 8 → fraction = 0.5 → MODERATE (at boundary).
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0, net_of_reserve_yield_pct=8.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "MODERATE_FEE_ON_RESERVE_GAP")
        self.assertAlmostEqual(r["fee_on_reserve_fraction"], 0.5, places=4)
        self.assertIn("FEE_ON_RESERVE_CONTRIBUTION", r["flags"])
        self.assertEqual(r["recommendation"], "DEMAND_NET_OF_RESERVE_BASE")

    def test_severe_fee_on_reserve_gap(self):
        # gross 20, net 4 → fraction = 0.8 → SEVERE.
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, net_of_reserve_yield_pct=4.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "SEVERE_FEE_ON_RESERVE_GAP")
        self.assertGreater(r["fee_on_reserve_fraction"], MODERATE_FRACTION)
        self.assertEqual(r["recommendation"], "AVOID_FEE_ON_RESERVE")

    def test_severe_net_negative(self):
        # reserve contribution drove net negative, fee on gross → net_fair negative.
        r = self.an.analyze(make_pos(
            gross_yield_pct=12.0, net_of_reserve_yield_pct=-3.0,
            performance_fee_pct=50.0))
        self.assertEqual(r["classification"], "SEVERE_FEE_ON_RESERVE_GAP")
        self.assertTrue(r["net_is_negative"])
        self.assertIn("NET_NEGATIVE_AFTER_FEE", r["flags"])
        self.assertEqual(r["recommendation"], "AVOID_FEE_ON_RESERVE")

    def test_fee_on_reserve_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0, net_of_reserve_yield_pct=8.0,
            performance_fee_pct=20.0))
        self.assertIn("FEE_ON_RESERVE_CONTRIBUTION", r["flags"])

    def test_full_fee_on_reserve_flag(self):
        # net <= 0 with positive gross → FULL_FEE_ON_RESERVE.
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0, net_of_reserve_yield_pct=0.0,
            performance_fee_pct=20.0))
        self.assertIn("FULL_FEE_ON_RESERVE", r["flags"])

    def test_high_reserve_diversion_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0, net_of_reserve_yield_pct=8.0,
            performance_fee_pct=20.0, reserve_contribution_rate_pct=25.0))
        self.assertIn("HIGH_RESERVE_DIVERSION", r["flags"])

    def test_low_reserve_diversion_no_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=18.0, net_of_reserve_yield_pct=18.0,
            performance_fee_pct=20.0, reserve_contribution_rate_pct=5.0))
        self.assertNotIn("HIGH_RESERVE_DIVERSION", r["flags"])

    def test_high_reserve_diversion_at_threshold(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0, net_of_reserve_yield_pct=8.0,
            performance_fee_pct=20.0, reserve_contribution_rate_pct=20.0))
        self.assertIn("HIGH_RESERVE_DIVERSION", r["flags"])

    def test_reserve_contribution_echoed(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0, net_of_reserve_yield_pct=8.0,
            performance_fee_pct=20.0, reserve_contribution_rate_pct=12.5))
        self.assertEqual(r["reserve_contribution_rate_pct"], 12.5)


# ── math correctness ──────────────────────────────────────────────────────────

class TestMath(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfReserveContributionBaseGapAnalyzer())

    def test_moderate_geometry(self):
        # gross 16, net 8, fee 20%.
        # fee_charged=0.2*16=3.2; fair=0.2*8=1.6; gap=1.6; consumed=8.
        # fraction=1.6/3.2=0.5.
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0, net_of_reserve_yield_pct=8.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["fee_charged_pct"], 3.2)
        self.assertAlmostEqual(r["fair_fee_pct"], 1.6)
        self.assertAlmostEqual(r["fee_on_reserve_gap_pct"], 1.6)
        self.assertAlmostEqual(r["reserve_consumed_yield_pct"], 8.0)
        self.assertAlmostEqual(r["fee_on_reserve_fraction"], 0.5, places=4)
        self.assertAlmostEqual(r["overstatement_pct"], 1.6)

    def test_net_return_fields(self):
        # gross 16, net 8, fee 20%.
        # net_after = 8 - 3.2 = 4.8 ; net_fair = 8 - 1.6 = 6.4.
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0, net_of_reserve_yield_pct=8.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["net_return_after_fee_pct"], 4.8)
        self.assertAlmostEqual(r["net_return_fair_pct"], 6.4)
        self.assertAlmostEqual(r["realization_ratio"], 4.8 / 6.4, places=4)

    def test_clean_geometry_zero_gap(self):
        # net == gross → fee_charged == fair → gap 0.
        r = self.an.analyze(make_pos(
            gross_yield_pct=18.0, net_of_reserve_yield_pct=18.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r["fee_on_reserve_gap_pct"], 0.0)
        self.assertAlmostEqual(r["reserve_consumed_yield_pct"], 0.0)
        self.assertEqual(r["fee_on_reserve_fraction"], 0.0)
        self.assertEqual(r["realization_ratio"], 1.0)
        self.assertEqual(r["score"], 100.0)

    def test_score_formula(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0, net_of_reserve_yield_pct=8.0,
            performance_fee_pct=20.0))
        rr = r["realization_ratio"]
        frac = r["fee_on_reserve_fraction"]
        expected = 70.0 * rr + 30.0 * (1.0 - frac)
        self.assertAlmostEqual(r["score"], round(expected, 2), places=2)

    def test_fee_rate_clamped_over_100(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=18.0, net_of_reserve_yield_pct=18.0,
            performance_fee_pct=250.0))
        self.assertEqual(r["performance_fee_pct"], 100.0)

    def test_fee_rate_negative_clamped(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=18.0, net_of_reserve_yield_pct=10.0,
            performance_fee_pct=-20.0))
        self.assertEqual(r["performance_fee_pct"], 0.0)
        self.assertEqual(r["fee_charged_pct"], 0.0)
        self.assertEqual(r["fee_on_reserve_gap_pct"], 0.0)

    def test_fee_rate_zero(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, net_of_reserve_yield_pct=10.0,
            performance_fee_pct=0.0))
        self.assertEqual(r["performance_fee_pct"], 0.0)
        self.assertEqual(r["fee_charged_pct"], 0.0)
        self.assertEqual(r["fee_on_reserve_gap_pct"], 0.0)
        self.assertEqual(r["fee_on_reserve_fraction"], 0.0)
        self.assertEqual(r["classification"], "CLEAN_NET_OF_RESERVE_BASE")

    def test_net_above_gross_no_gap(self):
        # net > gross → fair >= charged → gap 0, fraction 0 → CLEAN.
        r = self.an.analyze(make_pos(
            gross_yield_pct=10.0, net_of_reserve_yield_pct=12.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["fee_on_reserve_gap_pct"], 0.0)
        self.assertEqual(r["reserve_consumed_yield_pct"], 0.0)
        self.assertEqual(r["classification"], "CLEAN_NET_OF_RESERVE_BASE")

    def test_negative_net_fair_fee_zero(self):
        # net negative → fair_fee uses max(0, net) = 0.
        r = self.an.analyze(make_pos(
            gross_yield_pct=12.0, net_of_reserve_yield_pct=-3.0,
            performance_fee_pct=50.0))
        self.assertEqual(r["fair_fee_pct"], 0.0)
        self.assertAlmostEqual(r["fee_charged_pct"], 6.0)

    def test_gap_bounded_by_fee_charged(self):
        for net in (0.0, 2.0, 5.0, 9.9):
            r = self.an.analyze(make_pos(
                gross_yield_pct=10.0, net_of_reserve_yield_pct=net,
                performance_fee_pct=20.0))
            self.assertLessEqual(r["fee_on_reserve_gap_pct"],
                                 r["fee_charged_pct"] + 1e-9)
            self.assertLessEqual(r["fee_on_reserve_fraction"], 1.0)
            self.assertGreaterEqual(r["fee_on_reserve_fraction"], 0.0)

    def test_string_numeric_inputs(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct="16", net_of_reserve_yield_pct="8",
            performance_fee_pct="20"))
        self.assertEqual(r["classification"], "MODERATE_FEE_ON_RESERVE_GAP")

    def test_fraction_scale_free(self):
        # Doubling gross/net at the same fee leaves the scale-free fraction
        # unchanged (it is gap/fee_charged, both scale linearly).
        r1 = self.an.analyze(make_pos(
            gross_yield_pct=16.0, net_of_reserve_yield_pct=8.0,
            performance_fee_pct=20.0))
        r2 = self.an.analyze(make_pos(
            gross_yield_pct=32.0, net_of_reserve_yield_pct=16.0,
            performance_fee_pct=20.0))
        self.assertAlmostEqual(r1["fee_on_reserve_fraction"],
                               r2["fee_on_reserve_fraction"], places=6)
        self.assertEqual(r1["classification"], r2["classification"])


# ── override path ─────────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfReserveContributionBaseGapAnalyzer())

    def test_override_basic(self):
        # gap 4.8, fee_charged 12 → fraction 0.4 → MODERATE.
        r = self.an.analyze(make_pos(
            gross_yield_pct=24.0, fee_on_reserve_gap_pct=4.8,
            fee_charged_pct=12.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_main"])
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])
        self.assertAlmostEqual(r["fee_on_reserve_fraction"], 0.4, places=4)
        self.assertEqual(r["classification"], "MODERATE_FEE_ON_RESERVE_GAP")

    def test_override_geometry_none(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=24.0, fee_on_reserve_gap_pct=4.8,
            fee_charged_pct=12.0))
        self.assertIsNone(r["net_of_reserve_yield_pct"])
        self.assertIsNone(r["reserve_consumed_yield_pct"])
        self.assertIsNone(r["net_return_after_fee_pct"])
        self.assertIsNone(r["net_return_fair_pct"])
        self.assertIsNone(r["performance_fee_pct"])

    def test_override_geometry_flags_suppressed(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=24.0, fee_on_reserve_gap_pct=4.8,
            fee_charged_pct=12.0))
        self.assertNotIn("FEE_ON_RESERVE_CONTRIBUTION", r["flags"])
        self.assertNotIn("FULL_FEE_ON_RESERVE", r["flags"])
        self.assertNotIn("NET_NEGATIVE_AFTER_FEE", r["flags"])

    def test_override_negative_gap_magnitude(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=24.0, fee_on_reserve_gap_pct=-4.8,
            fee_charged_pct=12.0))
        self.assertAlmostEqual(r["fee_on_reserve_gap_pct"], 4.8, places=4)

    def test_override_gap_capped_at_fee_charged(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=24.0, fee_on_reserve_gap_pct=99.0,
            fee_charged_pct=12.0))
        self.assertEqual(r["fee_on_reserve_gap_pct"], 12.0)
        self.assertEqual(r["fee_on_reserve_fraction"], 1.0)
        self.assertEqual(r["fair_fee_pct"], 0.0)

    def test_override_realization_anchor(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=24.0, fee_on_reserve_gap_pct=3.0,
            fee_charged_pct=12.0))
        frac = r["fee_on_reserve_fraction"]
        self.assertAlmostEqual(r["realization_ratio"], 1.0 - frac, places=4)

    def test_override_denominator_is_fee_charged(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=24.0, fee_on_reserve_gap_pct=3.0,
            fee_charged_pct=12.0))
        self.assertAlmostEqual(r["fee_on_reserve_fraction"], 3.0 / 12.0,
                               places=4)

    def test_override_high_reserve_diversion_still_flagged(self):
        # HIGH_RESERVE_DIVERSION is not geometry-only → still raised on override.
        r = self.an.analyze(make_pos(
            gross_yield_pct=24.0, fee_on_reserve_gap_pct=3.0,
            fee_charged_pct=12.0, reserve_contribution_rate_pct=30.0))
        self.assertIn("HIGH_RESERVE_DIVERSION", r["flags"])
        self.assertIn("GAP_FROM_OVERRIDE", r["flags"])

    def test_override_requires_positive_fee_charged(self):
        # fee_charged = 0 → not override path → falls to main path.
        r = self.an.analyze(make_pos(
            gross_yield_pct=24.0, fee_on_reserve_gap_pct=3.0,
            fee_charged_pct=0.0, performance_fee_pct=20.0,
            net_of_reserve_yield_pct=24.0))
        self.assertFalse(r["used_override"])
        self.assertTrue(r["used_main"])

    def test_override_clean_when_small_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=24.0, fee_on_reserve_gap_pct=0.3,
            fee_charged_pct=12.0))
        self.assertEqual(r["classification"], "CLEAN_NET_OF_RESERVE_BASE")
        self.assertIn("CLEAN_NET_BASE", r["flags"])

    def test_override_severe_when_large_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=24.0, fee_on_reserve_gap_pct=10.0,
            fee_charged_pct=12.0))
        self.assertEqual(r["classification"], "SEVERE_FEE_ON_RESERVE_GAP")


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfReserveContributionBaseGapAnalyzer())

    def test_missing_gross(self):
        r = self.an.analyze(make_pos(performance_fee_pct=20.0,
                                     net_of_reserve_yield_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_zero_gross(self):
        r = self.an.analyze(make_pos(gross_yield_pct=0.0,
                                     performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_gross(self):
        r = self.an.analyze(make_pos(gross_yield_pct=-5.0,
                                     performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_gross(self):
        r = self.an.analyze(make_pos(gross_yield_pct=float("nan"),
                                     performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_gross(self):
        r = self.an.analyze(make_pos(gross_yield_pct=float("inf"),
                                     performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_fee_main_path(self):
        r = self.an.analyze(make_pos(gross_yield_pct=10.0,
                                     net_of_reserve_yield_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_invalid_fee_main_path(self):
        r = self.an.analyze(make_pos(gross_yield_pct=10.0,
                                     net_of_reserve_yield_pct=5.0,
                                     performance_fee_pct=float("nan")))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_fee_main_path(self):
        r = self.an.analyze(make_pos(gross_yield_pct=10.0,
                                     performance_fee_pct=float("inf")))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_all_none(self):
        r = self.an.analyze(make_pos(gross_yield_pct=10.0))
        # gross present but no fee → INSUFFICIENT.
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        for k in ("net_return_after_fee_pct", "fee_charged_pct",
                  "fee_on_reserve_gap_pct", "realization_ratio",
                  "fee_on_reserve_fraction",
                  "reserve_consumed_yield_pct"):
            self.assertIsNone(r[k])

    def test_insufficient_recommendation(self):
        r = self.an.analyze(make_pos(performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"], "AVOID_FEE_ON_RESERVE")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfReserveContributionBaseGapAnalyzer())

    def test_clean_net_base_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=18.0, net_of_reserve_yield_pct=18.0,
            performance_fee_pct=20.0))
        self.assertIn("CLEAN_NET_BASE", r["flags"])

    def test_classification_always_in_flags(self):
        for net in (18.0, 16.0, 8.0, 4.0):
            r = self.an.analyze(make_pos(
                gross_yield_pct=18.0, net_of_reserve_yield_pct=net,
                performance_fee_pct=20.0))
            self.assertIn(r["classification"], r["flags"])

    def test_no_clean_net_base_when_gap(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0, net_of_reserve_yield_pct=8.0,
            performance_fee_pct=20.0))
        self.assertNotIn("CLEAN_NET_BASE", r["flags"])

    def test_no_full_fee_on_reserve_when_positive_net(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0, net_of_reserve_yield_pct=8.0,
            performance_fee_pct=20.0))
        self.assertNotIn("FULL_FEE_ON_RESERVE", r["flags"])

    def test_no_fee_on_reserve_when_clean(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=18.0, net_of_reserve_yield_pct=18.0,
            performance_fee_pct=20.0))
        self.assertNotIn("FEE_ON_RESERVE_CONTRIBUTION", r["flags"])


# ── aggregate ─────────────────────────────────────────────────────────────────

class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfReserveContributionBaseGapAnalyzer())

    def test_portfolio_structure(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertIn("positions", out)
        self.assertIn("aggregate", out)
        self.assertEqual(len(out["positions"]), 5)
        agg = out["aggregate"]
        self.assertEqual(agg["position_count"], 5)
        self.assertIn("cleanest_vault", agg)
        self.assertIn("worst_reserve_gap_vault", agg)

    def test_aggregate_cleanest_and_worst(self):
        positions = [
            make_pos(vault="Clean", gross_yield_pct=18.0,
                     net_of_reserve_yield_pct=18.0,
                     performance_fee_pct=20.0),
            make_pos(vault="Bad", gross_yield_pct=12.0,
                     net_of_reserve_yield_pct=-3.0,
                     performance_fee_pct=50.0),
        ]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["cleanest_vault"], "Clean")
        self.assertEqual(agg["worst_reserve_gap_vault"], "Bad")

    def test_aggregate_all_insufficient(self):
        positions = [make_pos(vault="X"), make_pos(vault="Y")]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertIsNone(agg["cleanest_vault"])
        self.assertIsNone(agg["worst_reserve_gap_vault"])
        self.assertEqual(agg["avg_score"], 0.0)
        self.assertEqual(agg["position_count"], 2)

    def test_aggregate_net_negative_count(self):
        positions = [
            make_pos(vault="A", gross_yield_pct=18.0,
                     net_of_reserve_yield_pct=18.0,
                     performance_fee_pct=20.0),
            make_pos(vault="B", gross_yield_pct=12.0,
                     net_of_reserve_yield_pct=-3.0,
                     performance_fee_pct=50.0),
        ]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["net_negative_count"], 1)

    def test_aggregate_avg_score(self):
        positions = [
            make_pos(vault="A", gross_yield_pct=18.0,
                     net_of_reserve_yield_pct=18.0,
                     performance_fee_pct=20.0),
            make_pos(vault="B", gross_yield_pct=18.0,
                     net_of_reserve_yield_pct=18.0,
                     performance_fee_pct=20.0),
        ]
        agg = self.an.analyze_portfolio(positions)["aggregate"]
        self.assertAlmostEqual(agg["avg_score"], 100.0, places=2)


# ── ring-buffer log ───────────────────────────────────────────────────────────

class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfReserveContributionBaseGapAnalyzer())

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
                    [make_pos(gross_yield_pct=16.0,
                              net_of_reserve_yield_pct=8.0,
                              performance_fee_pct=20.0)],
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
                [make_pos(gross_yield_pct=16.0,
                          net_of_reserve_yield_pct=8.0,
                          performance_fee_pct=20.0)],
                cfg=cfg, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            self.an.analyze(make_pos(gross_yield_pct=16.0,
                                     net_of_reserve_yield_pct=8.0,
                                     performance_fee_pct=20.0),
                            cfg=cfg, write_log=True)
            self.assertFalse(os.path.exists(log_path + ".tmp"))

    def test_no_write_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            self.an.analyze(make_pos(gross_yield_pct=16.0,
                                     net_of_reserve_yield_pct=8.0,
                                     performance_fee_pct=20.0),
                            cfg=cfg, write_log=False)
            self.assertFalse(os.path.exists(log_path))

    def test_log_atomic_via_replace(self):
        # after a write, the tmp is gone and the final file is valid JSON list.
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
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfReserveContributionBaseGapAnalyzer())

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
            for net in (-5.0, 0.0, gross * 0.5, gross, gross + 5.0):
                for fee in (0.0, 10.0, 20.0, 50.0, 100.0):
                    r = self.an.analyze(make_pos(
                        gross_yield_pct=gross,
                        net_of_reserve_yield_pct=net,
                        performance_fee_pct=fee))
                    self.assertGreaterEqual(r["score"], 0.0)
                    self.assertLessEqual(r["score"], 100.0)
                    self.assertGreaterEqual(
                        r["fee_on_reserve_fraction"], 0.0)
                    self.assertLessEqual(
                        r["fee_on_reserve_fraction"], 1.0)
                    self.assertGreaterEqual(r["realization_ratio"], 0.0)
                    self.assertLessEqual(r["realization_ratio"], 1.0)
                    self.assertTrue(_all_floats_finite(r))

    def test_fraction_monotone_with_reserve(self):
        # holding gross/fee fixed, lower net (more reserve contribution) → larger
        # (or equal) fraction (monotone non-decreasing).
        prev = -1.0
        for net in (20.0, 16.0, 12.0, 8.0, 4.0, 0.0):
            r = self.an.analyze(make_pos(
                gross_yield_pct=20.0, net_of_reserve_yield_pct=net,
                performance_fee_pct=20.0))
            self.assertGreaterEqual(r["fee_on_reserve_fraction"], prev)
            prev = r["fee_on_reserve_fraction"]

    def test_token_fallback(self):
        r = self.an.analyze({"token": "TKN", "gross_yield_pct": 18.0,
                             "net_of_reserve_yield_pct": 18.0,
                             "performance_fee_pct": 20.0})
        self.assertEqual(r["token"], "TKN")

    def test_unknown_token(self):
        r = self.an.analyze({"gross_yield_pct": 18.0,
                             "net_of_reserve_yield_pct": 18.0,
                             "performance_fee_pct": 20.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_result_keys_stable(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0, net_of_reserve_yield_pct=8.0,
            performance_fee_pct=20.0))
        ins = self.an._insufficient("X")
        self.assertEqual(set(r.keys()), set(ins.keys()))

    def test_override_keys_stable(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=24.0, fee_on_reserve_gap_pct=4.8,
            fee_charged_pct=12.0))
        ins = self.an._insufficient("X")
        self.assertEqual(set(r.keys()), set(ins.keys()))

    def test_sample_count_zero(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=16.0, net_of_reserve_yield_pct=8.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["sample_count"], 0)


# ── grades / score boundaries ─────────────────────────────────────────────────

class TestGradesAndScore(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfReserveContributionBaseGapAnalyzer())

    def test_clean_grade_a(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=18.0, net_of_reserve_yield_pct=18.0,
            performance_fee_pct=20.0))
        self.assertEqual(r["grade"], "A")

    def test_severe_lower_grade(self):
        clean = self.an.analyze(make_pos(
            gross_yield_pct=18.0, net_of_reserve_yield_pct=18.0,
            performance_fee_pct=20.0))
        severe = self.an.analyze(make_pos(
            gross_yield_pct=12.0, net_of_reserve_yield_pct=-3.0,
            performance_fee_pct=50.0))
        self.assertLess(severe["score"], clean["score"])

    def test_score_zero_insufficient(self):
        r = self.an.analyze(make_pos(performance_fee_pct=20.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_grade_matches_score(self):
        for gross, net, fee in (
            (18.0, 18.0, 20.0),
            (16.0, 8.0, 20.0),
            (12.0, -3.0, 50.0),
            (20.0, 18.0, 20.0),
        ):
            r = self.an.analyze(make_pos(
                gross_yield_pct=gross, net_of_reserve_yield_pct=net,
                performance_fee_pct=fee))
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_grade_boundary_b_c(self):
        # A moderate gap with a mid realization should land in B/C band, not A.
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, net_of_reserve_yield_pct=12.0,
            performance_fee_pct=20.0))
        self.assertIn(r["grade"], ("B", "C", "D"))
        self.assertLess(r["score"], 85.0)


# ── CLI / demo ────────────────────────────────────────────────────────────────

class TestDemo(unittest.TestCase):
    def setUp(self):
        self.an = (
            DeFiProtocolVaultPerformanceFeeGrossOfReserveContributionBaseGapAnalyzer())

    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 5)

    def test_demo_classifications(self):
        out = self.an.analyze_portfolio(_demo_positions())
        classes = {p["token"]: p["classification"] for p in out["positions"]}
        self.assertEqual(
            classes["USDC-Vault-CleanNetBase"], "CLEAN_NET_OF_RESERVE_BASE")
        self.assertEqual(
            classes["stETH-Vault-ModerateReserve"],
            "MODERATE_FEE_ON_RESERVE_GAP")
        self.assertEqual(
            classes["GOV-Vault-SevereReserve"],
            "SEVERE_FEE_ON_RESERVE_GAP")
        self.assertEqual(
            classes["LST-Vault-OverrideGap"],
            "MODERATE_FEE_ON_RESERVE_GAP")
        self.assertEqual(
            classes["MYSTERY-Vault-NoData"], "INSUFFICIENT_DATA")

    def test_demo_json_serialisable(self):
        out = self.an.analyze_portfolio(_demo_positions())
        s = json.dumps(out)
        self.assertIsInstance(s, str)

    def test_demo_runs_all_paths(self):
        out = self.an.analyze_portfolio(_demo_positions())
        used_override = any(p["used_override"] for p in out["positions"])
        used_main = any(p["used_main"] for p in out["positions"])
        self.assertTrue(used_override)
        self.assertTrue(used_main)


if __name__ == "__main__":
    unittest.main(verbosity=2)
