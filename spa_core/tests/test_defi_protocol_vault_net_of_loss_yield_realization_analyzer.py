"""
Tests for MP-1204: DeFiProtocolVaultNetOfLossYieldRealizationAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_net_of_loss_yield_realization_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_net_of_loss_yield_realization_analyzer import (  # noqa: E501
    DeFiProtocolVaultNetOfLossYieldRealizationAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _coerce_num,
    _coerce_yield_samples,
    _coerce_loss_samples,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    MIN_SAMPLES,
    DEFAULT_PERIODS_PER_YEAR,
    CLEAN_FRACTION,
    MILD_FRACTION,
    MODERATE_FRACTION,
    FREQUENT_LOSS_FRACTION,
    SINGLE_LARGE_LOSS_FRACTION,
    FEW_SAMPLES_N,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    yield_samples=None,
    loss_samples=None,
    net_return_samples=None,
    periods_per_year=None,
    headline_yield_apr_pct=None,
    loss_drag_apr_pct=None,
):
    pos = {"vault": vault}
    if yield_samples is not None:
        pos["yield_samples"] = yield_samples
    if loss_samples is not None:
        pos["loss_samples"] = loss_samples
    if net_return_samples is not None:
        pos["net_return_samples"] = net_return_samples
    if periods_per_year is not None:
        pos["periods_per_year"] = periods_per_year
    if headline_yield_apr_pct is not None:
        pos["headline_yield_apr_pct"] = headline_yield_apr_pct
    if loss_drag_apr_pct is not None:
        pos["loss_drag_apr_pct"] = loss_drag_apr_pct
    return pos


def A():
    return DeFiProtocolVaultNetOfLossYieldRealizationAnalyzer()


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


# ── coercion of yield / loss vectors ───────────────────────────────────────────

class TestCoerceYield(unittest.TestCase):
    def test_yield_keeps_positives(self):
        self.assertEqual(_coerce_yield_samples([2.0, 1.0, 3.0]), [2.0, 1.0, 3.0])

    def test_yield_clamps_negative_to_zero(self):
        self.assertEqual(_coerce_yield_samples([2.0, -1.0, 3.0]), [2.0, 0.0, 3.0])

    def test_yield_zero_kept(self):
        self.assertEqual(_coerce_yield_samples([0.0, 1.0]), [0.0, 1.0])

    def test_yield_skips_nonnumeric(self):
        self.assertEqual(
            _coerce_yield_samples([2.0, "x", None, 3.0]), [2.0, 3.0])

    def test_yield_skips_bool(self):
        self.assertEqual(_coerce_yield_samples([True, 2.0]), [2.0])

    def test_yield_skips_nan_inf(self):
        self.assertEqual(
            _coerce_yield_samples([1.0, float("nan"), float("inf"), 2.0]),
            [1.0, 2.0])

    def test_yield_empty(self):
        self.assertEqual(_coerce_yield_samples([]), [])

    def test_yield_none(self):
        self.assertEqual(_coerce_yield_samples(None), [])

    def test_yield_preserves_order(self):
        self.assertEqual(_coerce_yield_samples([3.0, 1.0, 2.0]), [3.0, 1.0, 2.0])

    def test_yield_str_numeric(self):
        self.assertEqual(_coerce_yield_samples(["2.5", "1.0"]), [2.5, 1.0])


class TestCoerceLoss(unittest.TestCase):
    def test_loss_positive_magnitude(self):
        self.assertEqual(_coerce_loss_samples([2.0, 1.0]), [2.0, 1.0])

    def test_loss_negative_to_magnitude(self):
        self.assertEqual(_coerce_loss_samples([-2.0, -1.0]), [2.0, 1.0])

    def test_loss_mixed_signs(self):
        self.assertEqual(_coerce_loss_samples([2.0, -3.0, 1.0]), [2.0, 3.0, 1.0])

    def test_loss_zero_kept(self):
        self.assertEqual(_coerce_loss_samples([0.0, 2.0]), [0.0, 2.0])

    def test_loss_skips_nonnumeric(self):
        self.assertEqual(_coerce_loss_samples([2.0, "x", None]), [2.0])

    def test_loss_skips_bool(self):
        self.assertEqual(_coerce_loss_samples([True, 2.0]), [2.0])

    def test_loss_skips_nan_inf(self):
        self.assertEqual(
            _coerce_loss_samples([1.0, float("nan"), float("-inf"), 2.0]),
            [1.0, 2.0])

    def test_loss_empty(self):
        self.assertEqual(_coerce_loss_samples([]), [])

    def test_loss_none(self):
        self.assertEqual(_coerce_loss_samples(None), [])

    def test_loss_preserves_order(self):
        self.assertEqual(_coerce_loss_samples([3.0, -1.0, 2.0]), [3.0, 1.0, 2.0])


# ── core arithmetic ─────────────────────────────────────────────────────────────

class TestCoreArithmetic(unittest.TestCase):
    def test_headline_equals_mean_times_ppy(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0], loss_samples=[], periods_per_year=12.0))
        self.assertAlmostEqual(r["headline_yield_apr_pct"], 24.0, places=4)

    def test_loss_drag_equals_mean_times_ppy(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0], loss_samples=[1.0, 1.0, 1.0],
            periods_per_year=12.0))
        self.assertAlmostEqual(r["loss_drag_apr_pct"], 12.0, places=4)

    def test_loss_drag_zero_when_empty(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[], periods_per_year=12.0))
        self.assertAlmostEqual(r["loss_drag_apr_pct"], 0.0, places=6)

    def test_net_realized_is_difference(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0], loss_samples=[0.75, 0.75, 0.75],
            periods_per_year=12.0))
        self.assertAlmostEqual(
            r["net_realized_apr_pct"],
            r["headline_yield_apr_pct"] - r["loss_drag_apr_pct"], places=6)

    def test_overstatement_equals_loss_drag(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0], loss_samples=[0.5, 0.5, 0.5],
            periods_per_year=12.0))
        self.assertAlmostEqual(
            r["overstatement_pct"], r["loss_drag_apr_pct"], places=6)

    def test_realization_ratio_matches(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[0.5, 0.5],
            periods_per_year=12.0))
        # headline 24, loss 6, net 18, ratio 0.75
        self.assertAlmostEqual(r["realization_ratio"], 0.75, places=4)

    def test_loss_fraction_matches(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[0.5, 0.5],
            periods_per_year=12.0))
        self.assertAlmostEqual(r["loss_fraction"], 0.25, places=4)

    def test_realization_plus_loss_complement(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[0.4, 0.4],
            periods_per_year=12.0))
        self.assertAlmostEqual(
            r["realization_ratio"] + r["loss_fraction"], 1.0, places=4)

    def test_worst_loss_epoch(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[0.5, 1.2, 0.3],
            periods_per_year=12.0))
        self.assertAlmostEqual(r["worst_loss_epoch_pct"], 1.2, places=4)

    def test_loss_epoch_count_excludes_zero(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[0.0, 0.5, 0.0, 0.3],
            periods_per_year=12.0))
        self.assertEqual(r["loss_epoch_count"], 2)

    def test_masked_epoch_fraction(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[0.0, 0.5, 0.0, 0.3],
            periods_per_year=12.0))
        self.assertAlmostEqual(r["masked_epoch_fraction"], 0.5, places=4)

    def test_gross_yield_total(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 3.0, 1.0], loss_samples=[],
            periods_per_year=12.0))
        self.assertAlmostEqual(r["gross_yield_total"], 6.0, places=4)

    def test_loss_total(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[0.5, 1.0, 0.5],
            periods_per_year=12.0))
        self.assertAlmostEqual(r["loss_total"], 2.0, places=4)

    def test_sample_count(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0], loss_samples=[],
            periods_per_year=12.0))
        self.assertEqual(r["sample_count"], 4)

    def test_net_is_negative_flag_false_when_clean(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[], periods_per_year=12.0))
        self.assertFalse(r["net_is_negative"])

    def test_net_is_negative_when_losses_exceed(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[3.0, 3.0],
            periods_per_year=12.0))
        self.assertTrue(r["net_is_negative"])


# ── clean yield (no losses) ─────────────────────────────────────────────────────

class TestCleanYield(unittest.TestCase):
    def test_clean_classification(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0], loss_samples=[],
            periods_per_year=12.0))
        self.assertEqual(r["classification"], "CLEAN_YIELD")

    def test_clean_net_equals_headline(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0], loss_samples=[],
            periods_per_year=12.0))
        self.assertAlmostEqual(
            r["net_realized_apr_pct"], r["headline_yield_apr_pct"], places=6)

    def test_clean_realization_full(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0], loss_samples=[],
            periods_per_year=12.0))
        self.assertAlmostEqual(r["realization_ratio"], 1.0, places=6)
        self.assertAlmostEqual(r["loss_fraction"], 0.0, places=6)

    def test_clean_score_full(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0], loss_samples=[],
            periods_per_year=12.0))
        self.assertAlmostEqual(r["score"], 100.0, places=2)

    def test_clean_recommendation(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0], loss_samples=[],
            periods_per_year=12.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_clean_recurring_flag(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0], loss_samples=[],
            periods_per_year=12.0))
        self.assertIn("CLEAN_RECURRING", r["flags"])

    def test_clean_all_zero_losses(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0], loss_samples=[0.0, 0.0, 0.0, 0.0],
            periods_per_year=12.0))
        self.assertEqual(r["classification"], "CLEAN_YIELD")
        self.assertEqual(r["loss_epoch_count"], 0)

    def test_clean_omitted_loss_samples(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0], periods_per_year=12.0))
        self.assertEqual(r["classification"], "CLEAN_YIELD")
        finite_check(self, r)


# ── classification thresholds ───────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_clean_boundary(self):
        # loss_fraction just below CLEAN_FRACTION → CLEAN_YIELD.
        # headline 24 (yield 2*12). loss_drag = 0.04*24 = 0.96 → loss per period 0.08
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[0.08, 0.08],
            periods_per_year=12.0))
        self.assertLessEqual(r["loss_fraction"], CLEAN_FRACTION)
        self.assertEqual(r["classification"], "CLEAN_YIELD")

    def test_mild_loss_drag(self):
        # loss_fraction ~0.15
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[0.3, 0.3],
            periods_per_year=12.0))
        self.assertEqual(r["classification"], "MILD_LOSS_DRAG")

    def test_mild_boundary(self):
        # loss_fraction just below 0.20 → MILD_LOSS_DRAG
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[0.38, 0.38],
            periods_per_year=12.0))
        self.assertLessEqual(r["loss_fraction"], MILD_FRACTION)
        self.assertGreater(r["loss_fraction"], CLEAN_FRACTION)
        self.assertEqual(r["classification"], "MILD_LOSS_DRAG")

    def test_moderate_loss_drag(self):
        # loss_fraction ~0.35
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[0.7, 0.7],
            periods_per_year=12.0))
        self.assertEqual(r["classification"], "MODERATE_LOSS_DRAG")

    def test_moderate_boundary(self):
        # loss_fraction exactly 0.50
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[1.0, 1.0],
            periods_per_year=12.0))
        self.assertAlmostEqual(r["loss_fraction"], MODERATE_FRACTION, places=4)
        self.assertEqual(r["classification"], "MODERATE_LOSS_DRAG")

    def test_severe_loss_drag_above_moderate(self):
        # loss_fraction ~0.75 (not net negative)
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[1.5, 1.5],
            periods_per_year=12.0))
        self.assertEqual(r["classification"], "SEVERE_LOSS_DRAG")

    def test_severe_via_net_negative(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[3.0, 3.0],
            periods_per_year=12.0))
        self.assertEqual(r["classification"], "SEVERE_LOSS_DRAG")
        self.assertTrue(r["net_is_negative"])

    def test_net_negative_overrides_low_fraction(self):
        # losses equal yield → net exactly 0 → net_is_negative True → SEVERE.
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[2.0, 2.0],
            periods_per_year=12.0))
        self.assertTrue(r["net_is_negative"])
        self.assertEqual(r["classification"], "SEVERE_LOSS_DRAG")

    def test_classification_monotone_with_loss(self):
        labels = []
        for loss in (0.0, 0.3, 0.7, 1.5):
            r = A()._analyze_one(make_pos(
                yield_samples=[2.0, 2.0], loss_samples=[loss, loss],
                periods_per_year=12.0))
            labels.append(r["loss_fraction"])
        for i in range(len(labels) - 1):
            self.assertLessEqual(labels[i], labels[i + 1])


# ── ratios bounds ────────────────────────────────────────────────────────────────

class TestRatios(unittest.TestCase):
    def test_realization_ratio_bounds(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            if r["realization_ratio"] is not None:
                self.assertGreaterEqual(r["realization_ratio"], 0.0)
                self.assertLessEqual(r["realization_ratio"], 1.0)

    def test_loss_fraction_bounds(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            if r["loss_fraction"] is not None:
                self.assertGreaterEqual(r["loss_fraction"], 0.0)
                self.assertLessEqual(r["loss_fraction"], 1.0)

    def test_loss_fraction_capped_at_one(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[10.0, 10.0],
            periods_per_year=12.0))
        self.assertLessEqual(r["loss_fraction"], 1.0)

    def test_realization_zero_when_net_negative(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[5.0, 5.0],
            periods_per_year=12.0))
        self.assertAlmostEqual(r["realization_ratio"], 0.0, places=6)


# ── override path ────────────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def test_override_used(self):
        r = A()._analyze_one(make_pos(
            headline_yield_apr_pct=24.0, loss_drag_apr_pct=9.0))
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_samples"])
        self.assertIn("LOSS_FROM_OVERRIDE", r["flags"])
        finite_check(self, r)

    def test_override_net_computed(self):
        r = A()._analyze_one(make_pos(
            headline_yield_apr_pct=24.0, loss_drag_apr_pct=9.0))
        self.assertAlmostEqual(r["net_realized_apr_pct"], 15.0, places=4)

    def test_override_overstatement(self):
        r = A()._analyze_one(make_pos(
            headline_yield_apr_pct=24.0, loss_drag_apr_pct=9.0))
        self.assertAlmostEqual(r["overstatement_pct"], 9.0, places=4)

    def test_override_loss_fraction(self):
        r = A()._analyze_one(make_pos(
            headline_yield_apr_pct=24.0, loss_drag_apr_pct=9.0))
        self.assertAlmostEqual(r["loss_fraction"], 9.0 / 24.0, places=4)

    def test_override_no_loss_drag_defaults_zero(self):
        r = A()._analyze_one(make_pos(headline_yield_apr_pct=20.0))
        self.assertAlmostEqual(r["loss_drag_apr_pct"], 0.0, places=6)
        self.assertEqual(r["classification"], "CLEAN_YIELD")

    def test_override_negative_loss_to_magnitude(self):
        r = A()._analyze_one(make_pos(
            headline_yield_apr_pct=24.0, loss_drag_apr_pct=-9.0))
        self.assertAlmostEqual(r["loss_drag_apr_pct"], 9.0, places=4)

    def test_override_requires_headline(self):
        r = A()._analyze_one(make_pos(loss_drag_apr_pct=9.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_nonpositive_headline_insufficient(self):
        r = A()._analyze_one(make_pos(
            headline_yield_apr_pct=0.0, loss_drag_apr_pct=5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_negative_headline_insufficient(self):
        r = A()._analyze_one(make_pos(
            headline_yield_apr_pct=-5.0, loss_drag_apr_pct=2.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_bad_headline_insufficient(self):
        r = A()._analyze_one(make_pos(
            headline_yield_apr_pct=float("nan"), loss_drag_apr_pct=2.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_sample_metrics_none(self):
        r = A()._analyze_one(make_pos(
            headline_yield_apr_pct=24.0, loss_drag_apr_pct=9.0))
        self.assertIsNone(r["masked_epoch_fraction"])
        self.assertIsNone(r["worst_loss_epoch_pct"])
        self.assertIsNone(r["loss_epoch_count"])
        self.assertIsNone(r["gross_yield_total"])
        self.assertIsNone(r["loss_total"])

    def test_override_no_sample_only_flags(self):
        # Override with huge loss drag should not raise FREQUENT/SINGLE/FEW flags.
        r = A()._analyze_one(make_pos(
            headline_yield_apr_pct=24.0, loss_drag_apr_pct=9.0))
        self.assertNotIn("FREQUENT_LOSS_EPOCHS", r["flags"])
        self.assertNotIn("SINGLE_LARGE_LOSS", r["flags"])
        self.assertNotIn("FEW_SAMPLES", r["flags"])

    def test_override_net_negative_severe(self):
        r = A()._analyze_one(make_pos(
            headline_yield_apr_pct=10.0, loss_drag_apr_pct=15.0))
        self.assertTrue(r["net_is_negative"])
        self.assertEqual(r["classification"], "SEVERE_LOSS_DRAG")
        self.assertIn("NET_NEGATIVE_YIELD", r["flags"])

    def test_samples_take_precedence(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0], loss_samples=[0.0],
            headline_yield_apr_pct=99.0, loss_drag_apr_pct=50.0,
            periods_per_year=12.0))
        self.assertTrue(r["used_samples"])
        self.assertFalse(r["used_override"])

    def test_override_str_inputs(self):
        r = A()._analyze_one(make_pos(
            headline_yield_apr_pct="24.0", loss_drag_apr_pct="9.0"))
        self.assertAlmostEqual(r["net_realized_apr_pct"], 15.0, places=4)


# ── net_return_samples single signed stream ─────────────────────────────────────

class TestNetReturnStream(unittest.TestCase):
    def test_signed_stream_splits(self):
        r = A()._analyze_one(make_pos(
            net_return_samples=[2.0, -1.0, 2.0, -1.0], periods_per_year=12.0))
        # yields: 2,2 ; losses: 1,1
        self.assertAlmostEqual(r["headline_yield_apr_pct"], 24.0, places=4)
        self.assertAlmostEqual(r["loss_drag_apr_pct"], 12.0, places=4)

    def test_signed_stream_all_positive(self):
        r = A()._analyze_one(make_pos(
            net_return_samples=[2.0, 2.0, 2.0], periods_per_year=12.0))
        self.assertEqual(r["classification"], "CLEAN_YIELD")

    def test_signed_stream_insufficient_yields(self):
        # Only one positive part → fewer than MIN_SAMPLES yields → override path.
        r = A()._analyze_one(make_pos(
            net_return_samples=[2.0, -1.0, -1.0]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_yield_samples_preferred_over_net(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[3.0, 3.0], net_return_samples=[1.0, 1.0],
            periods_per_year=12.0))
        self.assertAlmostEqual(r["headline_yield_apr_pct"], 36.0, places=4)


# ── insufficient data ────────────────────────────────────────────────────────────

class TestInsufficient(unittest.TestCase):
    def test_single_sample_no_override(self):
        r = A()._analyze_one(make_pos(yield_samples=[2.0]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_empty_yields_no_override(self):
        r = A()._analyze_one(make_pos(yield_samples=[]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_data_at_all(self):
        r = A()._analyze_one({"vault": "x"})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_dirty_yields(self):
        r = A()._analyze_one(make_pos(
            yield_samples=["bad", None, float("nan")]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_yield_headline_insufficient(self):
        # All yields zero → headline 0 → no positive yield to net → INSUFFICIENT_DATA.
        r = A()._analyze_one(make_pos(
            yield_samples=[0.0, 0.0, 0.0], loss_samples=[1.0, 1.0, 1.0],
            periods_per_year=12.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_shape(self):
        r = A()._analyze_one(make_pos(yield_samples=[2.0]))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertIsNone(r["realization_ratio"])
        self.assertIsNone(r["loss_fraction"])
        self.assertIsNone(r["net_realized_apr_pct"])
        self.assertIsNone(r["headline_yield_apr_pct"])

    def test_insufficient_recommendation(self):
        r = A()._analyze_one(make_pos(yield_samples=[2.0]))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_insufficient_net_is_negative_false(self):
        r = A()._analyze_one(make_pos(yield_samples=[2.0]))
        self.assertFalse(r["net_is_negative"])


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_classification_in_flags(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[0.7, 0.7],
            periods_per_year=12.0))
        self.assertIn(r["classification"], r["flags"])

    def test_net_negative_flag(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[3.0, 3.0],
            periods_per_year=12.0))
        self.assertIn("NET_NEGATIVE_YIELD", r["flags"])

    def test_no_net_negative_flag_when_clean(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0], loss_samples=[],
            periods_per_year=12.0))
        self.assertNotIn("NET_NEGATIVE_YIELD", r["flags"])

    def test_frequent_loss_epochs_flag(self):
        # 3 of 4 epochs have loss → masked fraction 0.75 >= 0.5
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0],
            loss_samples=[0.2, 0.2, 0.0, 0.2], periods_per_year=12.0))
        self.assertIn("FREQUENT_LOSS_EPOCHS", r["flags"])

    def test_no_frequent_loss_when_rare(self):
        # 1 of 4 epochs has loss → masked fraction 0.25 < 0.5
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0],
            loss_samples=[0.0, 0.2, 0.0, 0.0], periods_per_year=12.0))
        self.assertNotIn("FREQUENT_LOSS_EPOCHS", r["flags"])

    def test_single_large_loss_flag(self):
        # one big loss dominates total → worst/total >= 0.5
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0],
            loss_samples=[3.0, 0.1, 0.1, 0.0], periods_per_year=12.0))
        self.assertIn("SINGLE_LARGE_LOSS", r["flags"])

    def test_no_single_large_loss_when_spread(self):
        # losses spread evenly → worst/total < 0.5
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0],
            loss_samples=[0.5, 0.5, 0.5, 0.5], periods_per_year=12.0))
        self.assertNotIn("SINGLE_LARGE_LOSS", r["flags"])

    def test_no_single_large_loss_when_no_losses(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0], loss_samples=[],
            periods_per_year=12.0))
        self.assertNotIn("SINGLE_LARGE_LOSS", r["flags"])

    def test_few_samples_flag(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[], periods_per_year=12.0))
        self.assertIn("FEW_SAMPLES", r["flags"])

    def test_no_few_samples_flag_when_enough(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0], loss_samples=[],
            periods_per_year=12.0))
        self.assertNotIn("FEW_SAMPLES", r["flags"])

    def test_clean_recurring_flag(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0], loss_samples=[],
            periods_per_year=12.0))
        self.assertIn("CLEAN_RECURRING", r["flags"])

    def test_no_clean_recurring_when_loss(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[0.7, 0.7],
            periods_per_year=12.0))
        self.assertNotIn("CLEAN_RECURRING", r["flags"])

    def test_loss_from_override_flag(self):
        r = A()._analyze_one(make_pos(
            headline_yield_apr_pct=24.0, loss_drag_apr_pct=9.0))
        self.assertIn("LOSS_FROM_OVERRIDE", r["flags"])

    def test_sample_path_no_override_flag(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0], loss_samples=[],
            periods_per_year=12.0))
        self.assertNotIn("LOSS_FROM_OVERRIDE", r["flags"])

    def test_override_no_few_samples_even_with_n_small(self):
        r = A()._analyze_one(make_pos(
            headline_yield_apr_pct=24.0, loss_drag_apr_pct=2.0))
        self.assertNotIn("FEW_SAMPLES", r["flags"])


# ── scoring ─────────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_clean_high_score(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0, 2.0, 2.0], loss_samples=[],
            periods_per_year=12.0))
        self.assertGreaterEqual(r["score"], 85)

    def test_severe_low_score(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[5.0, 5.0],
            periods_per_year=12.0))
        self.assertLess(r["score"], 40)

    def test_score_in_range_all_demo(self):
        for p in _demo_positions():
            r = A()._analyze_one(p)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_score_monotonic_in_loss_samples(self):
        small = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[0.2, 0.2],
            periods_per_year=12.0))
        big = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[1.0, 1.0],
            periods_per_year=12.0))
        self.assertGreater(small["score"], big["score"])

    def test_score_monotonic_in_loss_override(self):
        a = A()._analyze_one(make_pos(
            headline_yield_apr_pct=24.0, loss_drag_apr_pct=2.0))
        b = A()._analyze_one(make_pos(
            headline_yield_apr_pct=24.0, loss_drag_apr_pct=12.0))
        self.assertGreater(a["score"], b["score"])

    def test_score_formula(self):
        # headline 24, loss 6 → ratio 0.75, loss_fraction 0.25
        # score = 70*0.75 + 30*0.75 = 52.5 + 22.5 = 75
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[0.5, 0.5],
            periods_per_year=12.0))
        self.assertAlmostEqual(r["score"], 75.0, places=2)

    def test_insufficient_score_zero(self):
        r = A()._analyze_one(make_pos(yield_samples=[2.0]))
        self.assertEqual(r["score"], 0.0)

    def test_net_negative_score_low(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[10.0, 10.0],
            periods_per_year=12.0))
        # realization 0 → score = 30*(1-1)=0
        self.assertLessEqual(r["score"], 30)


# ── recommendation mapping ───────────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_clean_trust(self):
        self.assertEqual(A()._recommend("CLEAN_YIELD"), "TRUST_HEADLINE")

    def test_mild_discount_slightly(self):
        self.assertEqual(
            A()._recommend("MILD_LOSS_DRAG"), "DISCOUNT_HEADLINE_SLIGHTLY")

    def test_moderate_discount(self):
        self.assertEqual(
            A()._recommend("MODERATE_LOSS_DRAG"), "DISCOUNT_HEADLINE")

    def test_severe_avoid(self):
        self.assertEqual(
            A()._recommend("SEVERE_LOSS_DRAG"), "AVOID_OR_VERIFY")

    def test_insufficient_avoid(self):
        self.assertEqual(
            A()._recommend("INSUFFICIENT_DATA"), "AVOID_OR_VERIFY")


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
            "cleanest_yield_vault", "worst_loss_drag_vault", "avg_score",
            "net_negative_count", "position_count",
        ):
            self.assertIn(key, agg)

    def test_aggregate_all_insufficient(self):
        out = A().analyze_portfolio([{"vault": "x"}, {"vault": "y"}])
        agg = out["aggregate"]
        self.assertIsNone(agg["cleanest_yield_vault"])
        self.assertEqual(agg["avg_score"], 0.0)
        self.assertEqual(agg["position_count"], 2)

    def test_cleanest_has_highest_score(self):
        out = A().analyze_portfolio(_demo_positions())
        scored = [
            r for r in out["positions"]
            if r["classification"] != "INSUFFICIENT_DATA"]
        best = max(scored, key=lambda r: r["score"])
        self.assertEqual(out["aggregate"]["cleanest_yield_vault"], best["token"])

    def test_worst_has_lowest_score(self):
        out = A().analyze_portfolio(_demo_positions())
        scored = [
            r for r in out["positions"]
            if r["classification"] != "INSUFFICIENT_DATA"]
        worst = min(scored, key=lambda r: r["score"])
        self.assertEqual(
            out["aggregate"]["worst_loss_drag_vault"], worst["token"])

    def test_net_negative_count(self):
        positions = [
            make_pos(vault="neg", yield_samples=[2.0, 2.0],
                     loss_samples=[5.0, 5.0], periods_per_year=12.0),
            make_pos(vault="ok", yield_samples=[2.0, 2.0],
                     loss_samples=[], periods_per_year=12.0),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["net_negative_count"], 1)

    def test_position_count(self):
        agg = A().analyze_portfolio(_demo_positions())["aggregate"]
        self.assertEqual(agg["position_count"], len(_demo_positions()))


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

    def test_dirty_yields_filtered(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, "bad", None, 3.0, float("nan")],
            loss_samples=[], periods_per_year=12.0))
        self.assertEqual(r["sample_count"], 2)
        finite_check(self, r)

    def test_dirty_losses_filtered(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0],
            loss_samples=[1.0, "bad", None, float("inf"), 2.0],
            periods_per_year=12.0))
        # losses coerced to [1.0, 2.0], total 3.0
        self.assertAlmostEqual(r["loss_total"], 3.0, places=4)
        finite_check(self, r)

    def test_token_field_alias(self):
        r = A()._analyze_one({
            "token": "T1", "yield_samples": [2.0, 2.0],
            "periods_per_year": 12.0})
        self.assertEqual(r["token"], "T1")

    def test_unknown_token(self):
        r = A()._analyze_one({"yield_samples": [2.0, 2.0]})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_default_periods_per_year(self):
        r = A()._analyze_one({"yield_samples": [2.0, 2.0]})
        self.assertAlmostEqual(r["periods_per_year"], DEFAULT_PERIODS_PER_YEAR)

    def test_invalid_ppy_falls_back(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], periods_per_year=-5.0))
        self.assertAlmostEqual(r["periods_per_year"], DEFAULT_PERIODS_PER_YEAR)

    def test_zero_ppy_falls_back(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], periods_per_year=0.0))
        self.assertAlmostEqual(r["periods_per_year"], DEFAULT_PERIODS_PER_YEAR)

    def test_huge_losses_no_overflow(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[5.0, 5.0], loss_samples=[1e6, 1e6],
            periods_per_year=365.0))
        finite_check(self, r)

    def test_negative_loss_inputs_coerced(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[-0.5, -0.5],
            periods_per_year=12.0))
        self.assertAlmostEqual(r["loss_drag_apr_pct"], 6.0, places=4)

    def test_stray_negative_yield_clamped(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[2.0, -2.0, 2.0], loss_samples=[],
            periods_per_year=12.0))
        # negative clamped to 0 → mean = 4/3
        self.assertAlmostEqual(
            r["headline_yield_apr_pct"], (4.0 / 3.0) * 12.0, places=4)


# ── annualisation behavior ───────────────────────────────────────────────────────

class TestAnnualisation(unittest.TestCase):
    def test_headline_scales_with_ppy(self):
        low = A()._analyze_one(make_pos(
            yield_samples=[1.0, 1.0], loss_samples=[], periods_per_year=12.0))
        high = A()._analyze_one(make_pos(
            yield_samples=[1.0, 1.0], loss_samples=[], periods_per_year=52.0))
        self.assertGreater(
            high["headline_yield_apr_pct"], low["headline_yield_apr_pct"])

    def test_loss_drag_scales_with_ppy(self):
        low = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[1.0, 1.0],
            periods_per_year=12.0))
        high = A()._analyze_one(make_pos(
            yield_samples=[2.0, 2.0], loss_samples=[1.0, 1.0],
            periods_per_year=52.0))
        self.assertGreater(
            high["loss_drag_apr_pct"], low["loss_drag_apr_pct"])

    def test_default_ppy_365(self):
        r = A()._analyze_one(make_pos(
            yield_samples=[0.1, 0.1]))
        self.assertAlmostEqual(r["headline_yield_apr_pct"], 0.1 * 365.0, places=4)


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

    def test_no_write_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio(_demo_positions(), cfg={"log_path": path})
            self.assertFalse(os.path.exists(path))


# ── CLI / demo validity ─────────────────────────────────────────────────────────

class TestDemo(unittest.TestCase):
    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 5)

    def test_demo_has_each_class(self):
        results = [A()._analyze_one(p) for p in _demo_positions()]
        classes = {r["classification"] for r in results}
        self.assertIn("CLEAN_YIELD", classes)
        self.assertIn("MILD_LOSS_DRAG", classes)
        self.assertIn("SEVERE_LOSS_DRAG", classes)
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

    def test_demo_json_serializable(self):
        out = A().analyze_portfolio(_demo_positions())
        json.dumps(out)


# ── registry integration ────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):
    def test_registered(self):
        from spa_core.analytics import _module_registry as reg
        names = [m["module"] for m in reg.ALL_MODULES]
        self.assertIn(
            "defi_protocol_vault_net_of_loss_yield_realization_analyzer", names)

    def test_registry_entry_fields(self):
        from spa_core.analytics import _module_registry as reg
        entry = next(
            m for m in reg.ALL_MODULES
            if m["module"]
            == "defi_protocol_vault_net_of_loss_yield_realization_analyzer")
        self.assertEqual(entry["tier"], "B")
        self.assertEqual(entry["category"], "yield_quality")
        self.assertEqual(entry["weight"], 0.5)
        self.assertEqual(
            entry["class"],
            "DeFiProtocolVaultNetOfLossYieldRealizationAnalyzer")

    def test_registry_tier_b_count(self):
        from spa_core.analytics import _module_registry as reg
        self.assertGreaterEqual(reg.tier_counts()["B"], 455)

    def test_registry_all_modules_count(self):
        from spa_core.analytics import _module_registry as reg
        self.assertGreaterEqual(len(reg.ALL_MODULES), 647)


# ── constants sanity ─────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_thresholds_ordered(self):
        self.assertLess(CLEAN_FRACTION, MILD_FRACTION)
        self.assertLess(MILD_FRACTION, MODERATE_FRACTION)

    def test_min_samples(self):
        self.assertEqual(MIN_SAMPLES, 2)

    def test_default_ppy(self):
        self.assertEqual(DEFAULT_PERIODS_PER_YEAR, 365.0)

    def test_frequent_loss_fraction(self):
        self.assertEqual(FREQUENT_LOSS_FRACTION, 0.5)

    def test_single_large_loss_fraction(self):
        self.assertEqual(SINGLE_LARGE_LOSS_FRACTION, 0.5)

    def test_few_samples_n(self):
        self.assertEqual(FEW_SAMPLES_N, 4)

    def test_log_cap(self):
        self.assertEqual(LOG_CAP, 100)

    def test_clean_fraction_positive(self):
        self.assertGreater(CLEAN_FRACTION, 0.0)

    def test_moderate_fraction_below_one(self):
        self.assertLess(MODERATE_FRACTION, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
