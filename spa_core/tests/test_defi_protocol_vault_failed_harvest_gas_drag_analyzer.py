"""
Tests for MP-1232: DeFiProtocolVaultFailedHarvestGasDragAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_failed_harvest_gas_drag_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_failed_harvest_gas_drag_analyzer import (  # noqa: E501
    DeFiProtocolVaultFailedHarvestGasDragAnalyzer,
    _f,
    _clamp,
    _mean,
    _coerce_num,
    _coerce_count,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    CLEAN_FRACTION,
    MILD_FRACTION,
    MODERATE_FRACTION,
    HIGH_GAS_DRAG_PCT_OF_YIELD,
    EPS,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    gross_yield_pct=None,
    harvest_attempts=None,
    failed_harvests=None,
    avg_gas_cost_per_attempt_usd=None,
    position_size_usd=None,
    failed_gas_drag_pct=None,
    gas_drag_basis_pct=None,
    **extra,
):
    p = {"vault": vault}
    if gross_yield_pct is not None:
        p["gross_yield_pct"] = gross_yield_pct
    if harvest_attempts is not None:
        p["harvest_attempts"] = harvest_attempts
    if failed_harvests is not None:
        p["failed_harvests"] = failed_harvests
    if avg_gas_cost_per_attempt_usd is not None:
        p["avg_gas_cost_per_attempt_usd"] = avg_gas_cost_per_attempt_usd
    if position_size_usd is not None:
        p["position_size_usd"] = position_size_usd
    if failed_gas_drag_pct is not None:
        p["failed_gas_drag_pct"] = failed_gas_drag_pct
    if gas_drag_basis_pct is not None:
        p["gas_drag_basis_pct"] = gas_drag_basis_pct
    p.update(extra)
    return p


# ── helper tests ──────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    def test_f_none(self):
        self.assertEqual(_f(None), 0.0)

    def test_f_default(self):
        self.assertEqual(_f(None, 3.0), 3.0)

    def test_f_numeric_string(self):
        self.assertEqual(_f("2.5"), 2.5)

    def test_f_garbage(self):
        self.assertEqual(_f("abc", 1.0), 1.0)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1, 0, 1), 0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(2, 0, 1), 1)

    def test_clamp_mid(self):
        self.assertEqual(_clamp(0.4, 0, 1), 0.4)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_vals(self):
        self.assertEqual(_mean([2, 4]), 3.0)

    def test_coerce_num_bool_rejected(self):
        self.assertIsNone(_coerce_num(True))
        self.assertIsNone(_coerce_num(False))

    def test_coerce_num_nan(self):
        self.assertIsNone(_coerce_num(float("nan")))

    def test_coerce_num_inf(self):
        self.assertIsNone(_coerce_num(float("inf")))
        self.assertIsNone(_coerce_num(float("-inf")))

    def test_coerce_num_str(self):
        self.assertEqual(_coerce_num("12.5"), 12.5)

    def test_coerce_num_empty_str(self):
        self.assertIsNone(_coerce_num("  "))

    def test_coerce_num_none(self):
        self.assertIsNone(_coerce_num(None))

    def test_coerce_num_int(self):
        self.assertEqual(_coerce_num(7), 7.0)

    def test_coerce_count_basic(self):
        self.assertEqual(_coerce_count(5), 5)

    def test_coerce_count_float(self):
        self.assertEqual(_coerce_count(5.9), 5)

    def test_coerce_count_negative(self):
        self.assertIsNone(_coerce_count(-1))

    def test_coerce_count_none(self):
        self.assertIsNone(_coerce_count(None))

    def test_coerce_count_bool(self):
        self.assertIsNone(_coerce_count(True))

    def test_coerce_count_str(self):
        self.assertEqual(_coerce_count("3"), 3)

    def test_build_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    def test_build_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 7})
        self.assertEqual(cfg["log_cap"], 7)

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


# ── insufficient-data tests ───────────────────────────────────────────────────

class TestInsufficient(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultFailedHarvestGasDragAnalyzer()

    def test_no_gross_yield(self):
        r = self.an.analyze(make_pos(harvest_attempts=10, failed_harvests=1))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_gross_yield(self):
        r = self.an.analyze(make_pos(gross_yield_pct=0.0, harvest_attempts=10))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_gross_yield(self):
        r = self.an.analyze(make_pos(gross_yield_pct=-5.0, harvest_attempts=10))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_gross_yield(self):
        r = self.an.analyze(
            make_pos(gross_yield_pct=float("nan"), harvest_attempts=10))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_attempts_main(self):
        r = self.an.analyze(make_pos(gross_yield_pct=12.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_attempts(self):
        r = self.an.analyze(make_pos(gross_yield_pct=12.0, harvest_attempts=0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_attempts(self):
        r = self.an.analyze(make_pos(gross_yield_pct=12.0, harvest_attempts=-3))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = self.an.analyze(make_pos(gross_yield_pct=12.0))
        self.assertEqual(r["score"], 0.0)

    def test_insufficient_grade_f(self):
        r = self.an.analyze(make_pos(gross_yield_pct=12.0))
        self.assertEqual(r["grade"], "F")

    def test_insufficient_flags(self):
        r = self.an.analyze(make_pos(gross_yield_pct=12.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_insufficient_recommendation(self):
        r = self.an.analyze(make_pos(gross_yield_pct=12.0))
        self.assertEqual(r["recommendation"], "AVOID_FAILED_HARVEST_DRAG")

    def test_insufficient_fields_none(self):
        r = self.an.analyze(make_pos(gross_yield_pct=12.0))
        for k in ("failure_rate", "failed_gas_drag_pct",
                  "net_yield_after_failed_gas_pct", "realization_ratio",
                  "wasted_gas_fraction"):
            self.assertIsNone(r[k])


# ── main-path classification tests ────────────────────────────────────────────

class TestMainClassification(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultFailedHarvestGasDragAnalyzer()

    def test_reliable_no_failures(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0, harvest_attempts=50, failed_harvests=0,
            avg_gas_cost_per_attempt_usd=2.0, position_size_usd=250000.0))
        self.assertEqual(r["classification"], "RELIABLE_HARVESTING")

    def test_reliable_one_in_fifty(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0, harvest_attempts=50, failed_harvests=1,
            avg_gas_cost_per_attempt_usd=2.0, position_size_usd=250000.0))
        self.assertEqual(r["classification"], "RELIABLE_HARVESTING")

    def test_reliable_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0, harvest_attempts=50, failed_harvests=0,
            avg_gas_cost_per_attempt_usd=2.0, position_size_usd=250000.0))
        self.assertIn("RELIABLE_KEEPER", r["flags"])

    def test_mild(self):
        # failure_rate 0.10
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0, harvest_attempts=50, failed_harvests=5,
            avg_gas_cost_per_attempt_usd=1.0, position_size_usd=500000.0))
        self.assertEqual(r["classification"], "MILD_HARVEST_FAILURE_DRAG")

    def test_moderate(self):
        # failure_rate 0.40
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16,
            avg_gas_cost_per_attempt_usd=1.0, position_size_usd=500000.0))
        self.assertEqual(r["classification"], "MODERATE_HARVEST_FAILURE_DRAG")

    def test_severe_high_failrate(self):
        # failure_rate 0.75 (no net-negative because gas drag tiny)
        r = self.an.analyze(make_pos(
            gross_yield_pct=30.0, harvest_attempts=40, failed_harvests=30,
            avg_gas_cost_per_attempt_usd=0.01, position_size_usd=1000000.0))
        self.assertEqual(r["classification"], "SEVERE_HARVEST_FAILURE_DRAG")

    def test_severe_net_negative(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=6.0, harvest_attempts=60, failed_harvests=45,
            avg_gas_cost_per_attempt_usd=25.0, position_size_usd=9000.0))
        self.assertEqual(r["classification"], "SEVERE_HARVEST_FAILURE_DRAG")
        self.assertTrue(r["net_is_negative"])

    def test_net_negative_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=6.0, harvest_attempts=60, failed_harvests=45,
            avg_gas_cost_per_attempt_usd=25.0, position_size_usd=9000.0))
        self.assertIn("NET_NEGATIVE_AFTER_GAS", r["flags"])
        self.assertIn("FULL_GAS_WASTED_ON_FAILURES", r["flags"])

    def test_failed_harvest_gas_drag_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16,
            avg_gas_cost_per_attempt_usd=8.0, position_size_usd=120000.0))
        self.assertIn("FAILED_HARVEST_GAS_DRAG", r["flags"])

    def test_classification_in_flags(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16,
            avg_gas_cost_per_attempt_usd=1.0, position_size_usd=500000.0))
        self.assertIn(r["classification"], r["flags"])

    def test_boundary_clean_fraction(self):
        # exactly 0.05 → reliable (<=)
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0, harvest_attempts=100, failed_harvests=5,
            avg_gas_cost_per_attempt_usd=0.01, position_size_usd=1000000.0))
        self.assertEqual(r["failure_rate"], CLEAN_FRACTION)
        self.assertEqual(r["classification"], "RELIABLE_HARVESTING")

    def test_boundary_mild_fraction(self):
        # exactly 0.20 → mild (<=)
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0, harvest_attempts=100, failed_harvests=20,
            avg_gas_cost_per_attempt_usd=0.01, position_size_usd=1000000.0))
        self.assertEqual(r["failure_rate"], MILD_FRACTION)
        self.assertEqual(r["classification"], "MILD_HARVEST_FAILURE_DRAG")

    def test_boundary_moderate_fraction(self):
        # exactly 0.50 → moderate (<=)
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0, harvest_attempts=100, failed_harvests=50,
            avg_gas_cost_per_attempt_usd=0.01, position_size_usd=1000000.0))
        self.assertEqual(r["failure_rate"], MODERATE_FRACTION)
        self.assertEqual(r["classification"], "MODERATE_HARVEST_FAILURE_DRAG")

    def test_above_moderate_is_severe(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0, harvest_attempts=100, failed_harvests=51,
            avg_gas_cost_per_attempt_usd=0.01, position_size_usd=1000000.0))
        self.assertEqual(r["classification"], "SEVERE_HARVEST_FAILURE_DRAG")


# ── geometry / metric tests ───────────────────────────────────────────────────

class TestGeometry(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultFailedHarvestGasDragAnalyzer()

    def test_failure_rate_value(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16,
            avg_gas_cost_per_attempt_usd=1.0, position_size_usd=500000.0))
        self.assertAlmostEqual(r["failure_rate"], 0.4, places=4)

    def test_failed_clamped_to_attempts(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=10, failed_harvests=99,
            avg_gas_cost_per_attempt_usd=0.01, position_size_usd=1000000.0))
        self.assertEqual(r["failed_harvests"], 10)
        self.assertEqual(r["failure_rate"], 1.0)

    def test_gas_per_attempt_pct(self):
        # 8 usd / 120000 usd * 100 = 0.006667%
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16,
            avg_gas_cost_per_attempt_usd=8.0, position_size_usd=120000.0))
        self.assertAlmostEqual(r["gas_per_attempt_pct"], 8.0 / 120000.0 * 100.0,
                               places=6)

    def test_failed_gas_drag_value(self):
        # gas_per_attempt = 0.006667, failed 16 → 0.10667
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16,
            avg_gas_cost_per_attempt_usd=8.0, position_size_usd=120000.0))
        expected = 8.0 / 120000.0 * 100.0 * 16
        self.assertAlmostEqual(r["failed_gas_drag_pct"], round(expected, 4),
                               places=4)

    def test_total_gas_drag_value(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16,
            avg_gas_cost_per_attempt_usd=8.0, position_size_usd=120000.0))
        expected = 8.0 / 120000.0 * 100.0 * 40
        self.assertAlmostEqual(r["total_gas_drag_pct"], round(expected, 4),
                               places=4)

    def test_wasted_gas_fraction_equals_failure_rate(self):
        # under uniform per-attempt cost wasted_gas_fraction == failure_rate
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16,
            avg_gas_cost_per_attempt_usd=8.0, position_size_usd=120000.0))
        self.assertAlmostEqual(r["wasted_gas_fraction"], r["failure_rate"],
                               places=4)

    def test_net_yield_after_failed_gas(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16,
            avg_gas_cost_per_attempt_usd=8.0, position_size_usd=120000.0))
        drag = 8.0 / 120000.0 * 100.0 * 16
        self.assertAlmostEqual(r["net_yield_after_failed_gas_pct"],
                               round(14.0 - drag, 4), places=4)

    def test_zero_gas_no_drag(self):
        # no gas cost supplied → drag 0, realization 1.0
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16))
        self.assertEqual(r["failed_gas_drag_pct"], 0.0)
        self.assertEqual(r["realization_ratio"], 1.0)

    def test_zero_gas_classification_by_failrate(self):
        # 40% failure rate, but zero gas → still classified MODERATE by failrate
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16))
        self.assertEqual(r["classification"], "MODERATE_HARVEST_FAILURE_DRAG")

    def test_realization_ratio_range(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16,
            avg_gas_cost_per_attempt_usd=8.0, position_size_usd=120000.0))
        self.assertGreaterEqual(r["realization_ratio"], 0.0)
        self.assertLessEqual(r["realization_ratio"], 1.0)

    def test_realization_zero_when_net_negative(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=6.0, harvest_attempts=60, failed_harvests=45,
            avg_gas_cost_per_attempt_usd=25.0, position_size_usd=9000.0))
        self.assertEqual(r["realization_ratio"], 0.0)

    def test_overstatement_equals_drag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16,
            avg_gas_cost_per_attempt_usd=8.0, position_size_usd=120000.0))
        self.assertEqual(r["overstatement_pct"], r["failed_gas_drag_pct"])

    def test_gas_drag_yield_fraction(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16,
            avg_gas_cost_per_attempt_usd=8.0, position_size_usd=120000.0))
        drag = 8.0 / 120000.0 * 100.0 * 16
        self.assertAlmostEqual(r["gas_drag_yield_fraction"],
                               round(drag / 14.0, 4), places=4)

    def test_high_gas_drag_flag(self):
        # drag >= 25% of yield (1.2 of 4.0 = 30%) but net still positive.
        r = self.an.analyze(make_pos(
            gross_yield_pct=4.0, harvest_attempts=20, failed_harvests=8,
            avg_gas_cost_per_attempt_usd=150.0, position_size_usd=100000.0))
        self.assertFalse(r["net_is_negative"])
        self.assertIn("HIGH_GAS_DRAG", r["flags"])

    def test_no_high_gas_drag_flag_when_small(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0, harvest_attempts=50, failed_harvests=1,
            avg_gas_cost_per_attempt_usd=2.0, position_size_usd=250000.0))
        self.assertNotIn("HIGH_GAS_DRAG", r["flags"])

    def test_used_main_true(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16))
        self.assertTrue(r["used_main"])
        self.assertFalse(r["used_override"])

    def test_default_failed_zero(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40))
        self.assertEqual(r["failed_harvests"], 0)
        self.assertEqual(r["failure_rate"], 0.0)

    def test_gas_only_with_position(self):
        # gas supplied but no position size → no drag
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16,
            avg_gas_cost_per_attempt_usd=8.0))
        self.assertEqual(r["failed_gas_drag_pct"], 0.0)


# ── override-path tests ───────────────────────────────────────────────────────

class TestOverride(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultFailedHarvestGasDragAnalyzer()

    def test_override_used(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, failed_gas_drag_pct=4.0, gas_drag_basis_pct=10.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_main"])

    def test_override_fraction(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, failed_gas_drag_pct=4.0, gas_drag_basis_pct=10.0))
        self.assertAlmostEqual(r["wasted_gas_fraction"], 0.4, places=4)

    def test_override_classification_moderate(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, failed_gas_drag_pct=4.0, gas_drag_basis_pct=10.0))
        self.assertEqual(r["classification"], "MODERATE_HARVEST_FAILURE_DRAG")

    def test_override_flag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, failed_gas_drag_pct=4.0, gas_drag_basis_pct=10.0))
        self.assertIn("DRAG_FROM_OVERRIDE", r["flags"])

    def test_override_negative_taken_as_magnitude(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, failed_gas_drag_pct=-4.0, gas_drag_basis_pct=10.0))
        self.assertAlmostEqual(r["failed_gas_drag_pct"], 4.0, places=4)

    def test_override_drag_capped_at_basis(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, failed_gas_drag_pct=50.0, gas_drag_basis_pct=10.0))
        self.assertEqual(r["failed_gas_drag_pct"], 10.0)
        self.assertEqual(r["wasted_gas_fraction"], 1.0)

    def test_override_geometry_none(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, failed_gas_drag_pct=4.0, gas_drag_basis_pct=10.0))
        for k in ("harvest_attempts", "failed_harvests", "failure_rate",
                  "gas_per_attempt_pct"):
            self.assertIsNone(r[k])

    def test_override_no_geometry_flags(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, failed_gas_drag_pct=4.0, gas_drag_basis_pct=10.0))
        self.assertNotIn("FAILED_HARVEST_GAS_DRAG", r["flags"])

    def test_override_needs_positive_basis(self):
        # basis 0 → falls through to main path; no attempts → insufficient
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, failed_gas_drag_pct=4.0, gas_drag_basis_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_clean(self):
        # tiny fraction → reliable
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, failed_gas_drag_pct=0.2, gas_drag_basis_pct=10.0))
        self.assertEqual(r["classification"], "RELIABLE_HARVESTING")

    def test_override_net_negative(self):
        # drag exceeds gross yield → net negative → severe
        r = self.an.analyze(make_pos(
            gross_yield_pct=5.0, failed_gas_drag_pct=8.0, gas_drag_basis_pct=10.0))
        self.assertTrue(r["net_is_negative"])
        self.assertEqual(r["classification"], "SEVERE_HARVEST_FAILURE_DRAG")

    def test_override_realization_anchored(self):
        # realization anchored to 1 - wasted_gas_fraction when not net-negative
        r = self.an.analyze(make_pos(
            gross_yield_pct=100.0, failed_gas_drag_pct=4.0, gas_drag_basis_pct=10.0))
        # net = 100 - 4 = 96; realization = 96/100 = 0.96
        self.assertAlmostEqual(r["realization_ratio"], 0.96, places=4)

    def test_override_precedence_over_attempts(self):
        # both override + attempts present → override wins
        r = self.an.analyze(make_pos(
            gross_yield_pct=20.0, harvest_attempts=40, failed_harvests=10,
            failed_gas_drag_pct=4.0, gas_drag_basis_pct=10.0))
        self.assertTrue(r["used_override"])


# ── scoring tests ─────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultFailedHarvestGasDragAnalyzer()

    def test_reliable_high_score(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0, harvest_attempts=50, failed_harvests=0,
            avg_gas_cost_per_attempt_usd=2.0, position_size_usd=250000.0))
        self.assertGreaterEqual(r["score"], 95.0)

    def test_severe_low_score(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=6.0, harvest_attempts=60, failed_harvests=45,
            avg_gas_cost_per_attempt_usd=25.0, position_size_usd=9000.0))
        self.assertLessEqual(r["score"], 20.0)

    def test_score_range(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16,
            avg_gas_cost_per_attempt_usd=8.0, position_size_usd=120000.0))
        self.assertGreaterEqual(r["score"], 0.0)
        self.assertLessEqual(r["score"], 100.0)

    def test_score_monotonic_in_failrate(self):
        low = self.an.analyze(make_pos(
            gross_yield_pct=15.0, harvest_attempts=100, failed_harvests=5,
            avg_gas_cost_per_attempt_usd=0.01, position_size_usd=1000000.0))
        high = self.an.analyze(make_pos(
            gross_yield_pct=15.0, harvest_attempts=100, failed_harvests=45,
            avg_gas_cost_per_attempt_usd=0.01, position_size_usd=1000000.0))
        self.assertGreater(low["score"], high["score"])

    def test_grade_matches_score(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0, harvest_attempts=50, failed_harvests=0,
            avg_gas_cost_per_attempt_usd=2.0, position_size_usd=250000.0))
        self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_recommendation_reliable(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0, harvest_attempts=50, failed_harvests=0,
            avg_gas_cost_per_attempt_usd=2.0, position_size_usd=250000.0))
        self.assertEqual(r["recommendation"], "TRUST_KEEPER_RELIABILITY")

    def test_recommendation_moderate(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16))
        self.assertEqual(r["recommendation"], "DEMAND_KEEPER_FIX")

    def test_recommendation_mild(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=15.0, harvest_attempts=50, failed_harvests=5))
        self.assertEqual(r["recommendation"], "MINOR_FAILED_HARVEST_DRAG")

    def test_recommendation_severe(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=6.0, harvest_attempts=60, failed_harvests=45,
            avg_gas_cost_per_attempt_usd=25.0, position_size_usd=9000.0))
        self.assertEqual(r["recommendation"], "AVOID_FAILED_HARVEST_DRAG")


# ── aggregate tests ───────────────────────────────────────────────────────────

class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultFailedHarvestGasDragAnalyzer()

    def test_portfolio_structure(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertIn("positions", out)
        self.assertIn("aggregate", out)

    def test_position_count(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertEqual(out["aggregate"]["position_count"], 5)

    def test_cleanest_and_worst(self):
        out = self.an.analyze_portfolio(_demo_positions())
        agg = out["aggregate"]
        self.assertEqual(agg["cleanest_vault"], "USDC-Vault-ReliableKeeper")
        self.assertEqual(agg["worst_failed_harvest_drag_vault"],
                         "BAL-Vault-GasBleed")

    def test_net_negative_count(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertGreaterEqual(out["aggregate"]["net_negative_count"], 1)

    def test_avg_score_range(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertGreaterEqual(out["aggregate"]["avg_score"], 0.0)
        self.assertLessEqual(out["aggregate"]["avg_score"], 100.0)

    def test_all_insufficient_aggregate(self):
        out = self.an.analyze_portfolio([make_pos(gross_yield_pct=0.0)])
        agg = out["aggregate"]
        self.assertIsNone(agg["cleanest_vault"])
        self.assertIsNone(agg["worst_failed_harvest_drag_vault"])
        self.assertEqual(agg["avg_score"], 0.0)

    def test_empty_portfolio(self):
        out = self.an.analyze_portfolio([])
        self.assertEqual(out["aggregate"]["position_count"], 0)
        self.assertEqual(out["positions"], [])


# ── logging tests ─────────────────────────────────────────────────────────────

class TestLogging(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultFailedHarvestGasDragAnalyzer()

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "sub", "log.json")
            self.an.analyze_portfolio(
                _demo_positions(), cfg={"log_path": log_path}, write_log=True)
            self.assertTrue(os.path.exists(log_path))

    def test_log_is_list(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            self.an.analyze_portfolio(
                _demo_positions(), cfg={"log_path": log_path}, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            for _ in range(6):
                self.an.analyze_portfolio(
                    _demo_positions(), cfg=cfg, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_log_entry_fields(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            self.an.analyze_portfolio(
                _demo_positions(), cfg={"log_path": log_path}, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            entry = data[0]
            self.assertIn("ts", entry)
            self.assertIn("aggregate", entry)
            self.assertIn("snapshots", entry)

    def test_log_corrupt_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            with open(log_path, "w") as fh:
                fh.write("not json{")
            self.an.analyze_portfolio(
                _demo_positions(), cfg={"log_path": log_path}, write_log=True)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_no_log_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            self.an.analyze_portfolio(
                _demo_positions(), cfg={"log_path": log_path})
            self.assertFalse(os.path.exists(log_path))

    def test_single_analyze_log(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            self.an.analyze(make_pos(
                gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16),
                cfg={"log_path": log_path}, write_log=True)
            self.assertTrue(os.path.exists(log_path))


# ── robustness / no-inf-nan tests ─────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def setUp(self):
        self.an = DeFiProtocolVaultFailedHarvestGasDragAnalyzer()

    def test_no_nan_in_output(self):
        out = self.an.analyze_portfolio(_demo_positions())
        s = json.dumps(out)
        self.assertNotIn("NaN", s)
        self.assertNotIn("Infinity", s)

    def test_token_field_fallback(self):
        r = self.an.analyze({"token": "X", "gross_yield_pct": 12.0,
                             "harvest_attempts": 10})
        self.assertEqual(r["token"], "X")

    def test_unknown_token(self):
        r = self.an.analyze({"gross_yield_pct": 12.0, "harvest_attempts": 10})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_string_numeric_inputs(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct="14.0", harvest_attempts="40", failed_harvests="16"))
        self.assertEqual(r["classification"], "MODERATE_HARVEST_FAILURE_DRAG")

    def test_nan_failed_defaults_zero(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40,
            failed_harvests=float("nan")))
        self.assertEqual(r["failed_harvests"], 0)

    def test_gas_negative_ignored(self):
        # negative gas cost → treated as no drag
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16,
            avg_gas_cost_per_attempt_usd=-5.0, position_size_usd=120000.0))
        self.assertEqual(r["failed_gas_drag_pct"], 0.0)

    def test_huge_position_tiny_drag(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=2,
            avg_gas_cost_per_attempt_usd=5.0, position_size_usd=1e12))
        self.assertEqual(r["classification"], "RELIABLE_HARVESTING")

    def test_demo_runs(self):
        out = self.an.analyze_portfolio(_demo_positions())
        self.assertEqual(len(out["positions"]), 5)

    def test_result_keys_stable(self):
        r = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16))
        expected = {
            "token", "gross_yield_pct", "harvest_attempts", "failed_harvests",
            "failure_rate", "gas_per_attempt_pct", "failed_gas_drag_pct",
            "total_gas_drag_pct", "net_yield_after_failed_gas_pct",
            "overstatement_pct", "realization_ratio", "wasted_gas_fraction",
            "gas_drag_yield_fraction", "net_is_negative", "sample_count",
            "used_override", "used_main", "score", "classification",
            "recommendation", "grade", "flags",
        }
        self.assertEqual(set(r.keys()), expected)

    def test_insufficient_keys_match_normal(self):
        r1 = self.an.analyze(make_pos(gross_yield_pct=12.0))
        r2 = self.an.analyze(make_pos(
            gross_yield_pct=14.0, harvest_attempts=40, failed_harvests=16))
        self.assertEqual(set(r1.keys()), set(r2.keys()))


# ── registry test ─────────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    def test_registered(self):
        from spa_core.analytics import _module_registry as reg
        names = {m["module"] for m in reg.ALL_MODULES}
        self.assertIn(
            "defi_protocol_vault_failed_harvest_gas_drag_analyzer", names)

    def test_class_name_in_registry(self):
        from spa_core.analytics import _module_registry as reg
        entry = reg.get_module_info(
            "defi_protocol_vault_failed_harvest_gas_drag_analyzer")
        self.assertIsNotNone(entry)
        self.assertEqual(
            entry["class"], "DeFiProtocolVaultFailedHarvestGasDragAnalyzer")
        self.assertEqual(entry["tier"], "B")


if __name__ == "__main__":
    unittest.main(verbosity=2)
