"""
Tests for MP-1200: DeFiProtocolVaultHarvestYieldConcentrationAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_harvest_yield_concentration_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_harvest_yield_concentration_analyzer import (  # noqa: E501
    DeFiProtocolVaultHarvestYieldConcentrationAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _coerce_num,
    _coerce_harvests,
    _pstdev,
    _median,
    _gini,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    MIN_SAMPLES,
    WINDFALL_MULTIPLE_DEFAULT,
    DIVERSE_IDX,
    MILD_IDX,
    CONCENTRATED_IDX,
    SINGLE_EVENT_SHARE,
    HIGH_CV,
    FEW_HARVESTS_N,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    headline_apr_pct=20.0,
    harvest_yield_samples=None,
    recurring_apr_pct=None,
    windfall_multiple=None,
):
    pos = {"vault": vault, "headline_apr_pct": headline_apr_pct}
    if harvest_yield_samples is not None:
        pos["harvest_yield_samples"] = harvest_yield_samples
    if recurring_apr_pct is not None:
        pos["recurring_apr_pct"] = recurring_apr_pct
    if windfall_multiple is not None:
        pos["windfall_multiple"] = windfall_multiple
    return pos


def A():
    return DeFiProtocolVaultHarvestYieldConcentrationAnalyzer()


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

    def test_clamp_within(self):
        self.assertEqual(_clamp(5, 0, 10), 5)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1, 0, 10), 0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(11, 0, 10), 10)

    def test_clamp_unit_high(self):
        self.assertEqual(_clamp(1.5, 0.0, 1.0), 1.0)

    def test_clamp_unit_low(self):
        self.assertEqual(_clamp(-0.2, 0.0, 1.0), 0.0)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertAlmostEqual(_mean([2, 4, 6]), 4.0)

    def test_mean_negative(self):
        self.assertAlmostEqual(_mean([-1.0, 1.0]), 0.0)

    def test_safe_div_normal(self):
        self.assertAlmostEqual(_safe_div(10.0, 4.0, None), 2.5)

    def test_safe_div_zero_den(self):
        self.assertIsNone(_safe_div(10.0, 0.0, None))

    def test_safe_div_negative_den(self):
        self.assertIsNone(_safe_div(10.0, -1.0, None))

    def test_safe_div_sentinel_value(self):
        self.assertEqual(_safe_div(5.0, 0.0, 0.0), 0.0)

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

    def test_grade_boundary_85(self):
        self.assertEqual(_grade_from_score(85), "A")

    def test_grade_boundary_70(self):
        self.assertEqual(_grade_from_score(70), "B")

    def test_grade_boundary_55(self):
        self.assertEqual(_grade_from_score(55), "C")

    def test_grade_boundary_40(self):
        self.assertEqual(_grade_from_score(40), "D")

    def test_grade_below_40(self):
        self.assertEqual(_grade_from_score(39.9), "F")

    def test_build_default_cfg_defaults(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 7})
        self.assertEqual(cfg["log_cap"], 7)


# ── _coerce_num tests ───────────────────────────────────────────────────────────

class TestCoerceNum(unittest.TestCase):
    def test_int(self):
        self.assertEqual(_coerce_num(3), 3.0)

    def test_float(self):
        self.assertEqual(_coerce_num(2.5), 2.5)

    def test_negative(self):
        self.assertEqual(_coerce_num(-1.5), -1.5)

    def test_zero(self):
        self.assertEqual(_coerce_num(0), 0.0)

    def test_numeric_string(self):
        self.assertEqual(_coerce_num("4.25"), 4.25)

    def test_negative_string(self):
        self.assertEqual(_coerce_num("-2"), -2.0)

    def test_whitespace_string(self):
        self.assertEqual(_coerce_num("  3.0  "), 3.0)

    def test_empty_string(self):
        self.assertIsNone(_coerce_num(""))

    def test_garbage_string(self):
        self.assertIsNone(_coerce_num("abc"))

    def test_nan(self):
        self.assertIsNone(_coerce_num(float("nan")))

    def test_inf(self):
        self.assertIsNone(_coerce_num(float("inf")))

    def test_neg_inf(self):
        self.assertIsNone(_coerce_num(float("-inf")))

    def test_none(self):
        self.assertIsNone(_coerce_num(None))

    def test_bool_true_rejected(self):
        self.assertIsNone(_coerce_num(True))

    def test_bool_false_rejected(self):
        self.assertIsNone(_coerce_num(False))

    def test_dict(self):
        self.assertIsNone(_coerce_num({}))

    def test_list(self):
        self.assertIsNone(_coerce_num([1]))

    def test_nan_string(self):
        self.assertIsNone(_coerce_num("nan"))


# ── _coerce_harvests tests ──────────────────────────────────────────────────────

class TestCoerceHarvests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_coerce_harvests([1, 2, 3]), [1.0, 2.0, 3.0])

    def test_empty(self):
        self.assertEqual(_coerce_harvests([]), [])

    def test_none(self):
        self.assertEqual(_coerce_harvests(None), [])

    def test_skip_negative(self):
        self.assertEqual(_coerce_harvests([1.0, -2.0, 3.0]), [1.0, 3.0])

    def test_skip_nonfinite(self):
        self.assertEqual(
            _coerce_harvests([1.0, float("nan"), float("inf"), 2.0]),
            [1.0, 2.0])

    def test_skip_garbage(self):
        self.assertEqual(_coerce_harvests([1.0, "x", None, {}, 2.0]),
                         [1.0, 2.0])

    def test_string_numbers(self):
        self.assertEqual(_coerce_harvests(["1.5", "2.5"]), [1.5, 2.5])

    def test_order_preserved(self):
        self.assertEqual(_coerce_harvests([3.0, 1.0, 2.0]), [3.0, 1.0, 2.0])

    def test_zero_kept(self):
        self.assertEqual(_coerce_harvests([0.0, 1.0]), [0.0, 1.0])

    def test_bool_rejected(self):
        self.assertEqual(_coerce_harvests([True, 1.0]), [1.0])


# ── _pstdev / _median tests ──────────────────────────────────────────────────────

class TestPstdevMedian(unittest.TestCase):
    def test_pstdev_single(self):
        self.assertEqual(_pstdev([5.0]), 0.0)

    def test_pstdev_empty(self):
        self.assertEqual(_pstdev([]), 0.0)

    def test_pstdev_constant(self):
        self.assertEqual(_pstdev([3.0, 3.0, 3.0]), 0.0)

    def test_pstdev_known(self):
        self.assertAlmostEqual(_pstdev([2.0, 4.0]), 1.0)

    def test_pstdev_finite(self):
        self.assertTrue(math.isfinite(_pstdev([1.0, 2.0, 3.0, 4.0])))

    def test_median_empty(self):
        self.assertEqual(_median([]), 0.0)

    def test_median_odd(self):
        self.assertEqual(_median([1.0, 3.0, 2.0]), 2.0)

    def test_median_even(self):
        self.assertEqual(_median([1.0, 2.0, 3.0, 4.0]), 2.5)

    def test_median_single(self):
        self.assertEqual(_median([7.0]), 7.0)


# ── _gini tests ─────────────────────────────────────────────────────────────────

class TestGini(unittest.TestCase):
    def test_all_equal_zero(self):
        self.assertAlmostEqual(_gini([5.0, 5.0, 5.0, 5.0]), 0.0)

    def test_empty(self):
        self.assertEqual(_gini([]), 0.0)

    def test_all_zero(self):
        self.assertEqual(_gini([0.0, 0.0]), 0.0)

    def test_single(self):
        # one value → perfectly "equal" within itself
        self.assertAlmostEqual(_gini([10.0]), 0.0)

    def test_concentrated_high(self):
        g = _gini([0.0, 0.0, 0.0, 100.0])
        self.assertGreater(g, 0.5)

    def test_in_unit_range(self):
        for vals in ([1, 2, 3], [10, 1, 1], [5, 5, 100], [0, 0, 1]):
            g = _gini([float(v) for v in vals])
            self.assertGreaterEqual(g, 0.0)
            self.assertLessEqual(g, 1.0)

    def test_monotonic_more_skew_higher(self):
        even = _gini([100.0, 100.0, 100.0, 100.0])
        skew = _gini([100.0, 100.0, 100.0, 1000.0])
        self.assertGreater(skew, even)

    def test_finite(self):
        self.assertTrue(math.isfinite(_gini([1.0, 50.0, 3.0])))


# ── concentration math tests ─────────────────────────────────────────────────────

class TestConcentrationMath(unittest.TestCase):
    def test_even_series_index_near_zero(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 100]))
        self.assertAlmostEqual(r["concentration_index"], 0.0, places=3)

    def test_even_series_realization_one(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 100]))
        self.assertAlmostEqual(r["realization_ratio"], 1.0)

    def test_even_series_recurring_equals_headline(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=12.0,
            harvest_yield_samples=[50, 50, 50, 50, 50]))
        self.assertAlmostEqual(r["recurring_apr_pct"], 12.0)
        self.assertAlmostEqual(r["overstatement_pct"], 0.0)

    def test_single_event_index_high(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[1, 1, 1, 1000]))
        self.assertGreater(r["concentration_index"], 0.6)

    def test_hhi_bounds(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[10, 20, 30, 40]))
        n = r["sample_count"]
        self.assertGreaterEqual(r["hhi"], 1.0 / n - 1e-9)
        self.assertLessEqual(r["hhi"], 1.0)

    def test_effective_harvests_le_n(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[10, 20, 30, 40, 50]))
        self.assertLessEqual(r["effective_harvests"], r["sample_count"] + 1e-9)

    def test_effective_harvests_even_near_n(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 100]))
        self.assertAlmostEqual(r["effective_harvests"], 4.0, places=2)

    def test_top_event_share(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 100]))
        self.assertAlmostEqual(r["top_event_share"], 0.25)

    def test_top3_event_share(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[10, 10, 10, 10]))
        # 3 of 4 equal shares = 0.75
        self.assertAlmostEqual(r["top3_event_share"], 0.75)

    def test_top3_with_two_samples(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[10, 10]))
        # top3 caps at all available = 1.0
        self.assertAlmostEqual(r["top3_event_share"], 1.0)

    def test_realization_ratio_lump(self):
        # [1,1,1,1,996]: median=1, total=1000 → 1*5/1000 = 0.005
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[1, 1, 1, 1, 996]))
        self.assertAlmostEqual(r["realization_ratio"], 0.005, places=4)

    def test_recurring_is_headline_times_realization(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=40.0,
            harvest_yield_samples=[1, 1, 1, 1, 996]))
        self.assertAlmostEqual(
            r["recurring_apr_pct"], 40.0 * r["realization_ratio"], places=4)

    def test_overstatement_is_headline_minus_recurring(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=40.0,
            harvest_yield_samples=[1, 1, 1, 1, 996]))
        self.assertAlmostEqual(
            r["overstatement_pct"],
            r["headline_apr_pct"] - r["recurring_apr_pct"], places=4)

    def test_harvest_total_reported(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[10, 20, 30]))
        self.assertAlmostEqual(r["harvest_total"], 60.0)

    def test_median_harvest_reported(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[10, 20, 30]))
        self.assertAlmostEqual(r["median_harvest"], 20.0)

    def test_sample_count(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[10, 20, 30, 40]))
        self.assertEqual(r["sample_count"], 4)

    def test_used_samples_flag(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[10, 20]))
        self.assertTrue(r["used_samples"])
        self.assertFalse(r["used_override"])

    def test_cv_computed(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[10, 20, 30, 40]))
        self.assertIsNotNone(r["coefficient_of_variation"])
        self.assertGreater(r["coefficient_of_variation"], 0.0)

    def test_cv_zero_for_constant(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[50, 50, 50]))
        self.assertAlmostEqual(r["coefficient_of_variation"], 0.0)

    def test_filters_negative_and_nonfinite(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, -5, float("nan"), "bad", 100]))
        self.assertEqual(r["sample_count"], 2)

    def test_windfall_multiple_override(self):
        # base median small → high multiple suppresses windfall flagging
        loose = A()._analyze_one(make_pos(
            harvest_yield_samples=[10, 10, 10, 60], windfall_multiple=10.0))
        self.assertEqual(loose["windfall_count"], 0)
        tight = A()._analyze_one(make_pos(
            harvest_yield_samples=[10, 10, 10, 60], windfall_multiple=2.0))
        self.assertGreaterEqual(tight["windfall_count"], 1)

    def test_invalid_windfall_multiple_falls_back(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[10, 10, 10, 200],
            windfall_multiple=-3.0))
        # default 4.0: 200 > 4*10 = 40 → windfall
        self.assertEqual(r["windfall_count"], 1)


# ── classification tests ────────────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_diverse_recurring(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 100, 100]))
        self.assertEqual(r["classification"], "DIVERSE_RECURRING")

    def test_windfall_dominated(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[1, 1, 1, 1, 1000]))
        self.assertEqual(r["classification"], "WINDFALL_DOMINATED")

    def test_mildly_lumpy(self):
        # [100,100,100,400] → index ~0.18
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 400]))
        self.assertEqual(r["classification"], "MILDLY_LUMPY")

    def test_concentrated(self):
        # tune to land in (0.30, 0.60]
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 600]))
        self.assertEqual(r["classification"], "CONCENTRATED")

    def test_diverse_boundary(self):
        # index exactly at DIVERSE_IDX still diverse
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 100]))
        self.assertLessEqual(r["concentration_index"], DIVERSE_IDX)
        self.assertEqual(r["classification"], "DIVERSE_RECURRING")

    def test_classification_monotonic_with_lump(self):
        order = []
        for big in [100, 200, 600, 5000]:
            r = A()._analyze_one(make_pos(
                harvest_yield_samples=[100, 100, 100, big]))
            order.append(r["concentration_index"])
        for a, b in zip(order, order[1:]):
            self.assertLessEqual(a, b)


# ── concentration_index bounds ───────────────────────────────────────────────────

class TestIndexBounds(unittest.TestCase):
    def test_index_in_unit_range_various(self):
        cases = [
            [100, 100, 100, 100],
            [100, 100, 100, 400],
            [1, 1, 1, 1000],
            [10, 20, 30, 40, 50],
            [0, 0, 100],
        ]
        for s in cases:
            r = A()._analyze_one(make_pos(harvest_yield_samples=s))
            if r["classification"] == "INSUFFICIENT_DATA":
                continue
            self.assertGreaterEqual(r["concentration_index"], 0.0)
            self.assertLessEqual(r["concentration_index"], 1.0)

    def test_realization_in_unit_range(self):
        for s in ([100, 100, 100, 100], [1, 1, 1000], [10, 20, 30]):
            r = A()._analyze_one(make_pos(harvest_yield_samples=s))
            self.assertGreaterEqual(r["realization_ratio"], 0.0)
            self.assertLessEqual(r["realization_ratio"], 1.0)


# ── score tests ──────────────────────────────────────────────────────────────────

class TestScore(unittest.TestCase):
    def test_score_in_range(self):
        for r in A().analyze_portfolio(_demo_positions())["positions"]:
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_even_high_score(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 100, 100]))
        self.assertGreaterEqual(r["score"], 95.0)

    def test_windfall_low_score(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[1, 1, 1, 1, 1000]))
        self.assertLess(r["score"], 40.0)

    def test_score_monotonic_more_lump_lower(self):
        scores = []
        for big in [100, 300, 800, 3000]:
            r = A()._analyze_one(make_pos(
                harvest_yield_samples=[100, 100, 100, big]))
            scores.append(r["score"])
        for a, b in zip(scores, scores[1:]):
            self.assertGreaterEqual(a, b)

    def test_score_clamped_max(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 100]))
        self.assertLessEqual(r["score"], 100.0)

    def test_override_score(self):
        # realization=6/20=0.3, evenness=1-0.7=0.3 → 70*0.3+30*0.3=30
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, recurring_apr_pct=6.0))
        self.assertAlmostEqual(r["score"], 30.0, places=1)

    def test_override_full_runrate_high_score(self):
        # recurring == headline → realization=1, evenness=1 → 100
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, recurring_apr_pct=20.0))
        self.assertAlmostEqual(r["score"], 100.0, places=1)


# ── flag tests ──────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_classification_flag_present(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 400]))
        self.assertIn(r["classification"], r["flags"])

    def test_smooth_recurring_flag(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 100]))
        self.assertIn("SMOOTH_RECURRING", r["flags"])

    def test_single_event_dominated_flag(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[1, 1, 1, 1000]))
        self.assertIn("SINGLE_EVENT_DOMINATED", r["flags"])

    def test_no_single_event_flag_when_even(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 100]))
        self.assertNotIn("SINGLE_EVENT_DOMINATED", r["flags"])

    def test_windfall_present_flag(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[10, 10, 10, 10, 500]))
        self.assertIn("WINDFALL_PRESENT", r["flags"])

    def test_no_windfall_flag_when_even(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 100]))
        self.assertNotIn("WINDFALL_PRESENT", r["flags"])

    def test_high_dispersion_flag(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[1, 1, 1, 1, 1000]))
        self.assertIn("HIGH_DISPERSION", r["flags"])

    def test_few_harvests_flag(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100]))
        self.assertIn("FEW_HARVESTS", r["flags"])

    def test_no_few_harvests_flag_when_many(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 100, 100]))
        self.assertNotIn("FEW_HARVESTS", r["flags"])

    def test_override_flag(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, recurring_apr_pct=6.0))
        self.assertIn("RUN_RATE_FROM_OVERRIDE", r["flags"])

    def test_no_override_flag_when_samples(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100]))
        self.assertNotIn("RUN_RATE_FROM_OVERRIDE", r["flags"])

    def test_override_no_sample_only_flags(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, recurring_apr_pct=6.0))
        # sample-only flags must not appear on override path
        self.assertNotIn("SINGLE_EVENT_DOMINATED", r["flags"])
        self.assertNotIn("WINDFALL_PRESENT", r["flags"])
        self.assertNotIn("HIGH_DISPERSION", r["flags"])
        self.assertNotIn("FEW_HARVESTS", r["flags"])


# ── override path tests ─────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def test_override_basic(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, recurring_apr_pct=6.0))
        self.assertAlmostEqual(r["recurring_apr_pct"], 6.0)
        self.assertAlmostEqual(r["realization_ratio"], 0.3)
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_samples"])

    def test_override_overstatement(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, recurring_apr_pct=6.0))
        self.assertAlmostEqual(r["overstatement_pct"], 14.0)

    def test_override_sample_metrics_none(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, recurring_apr_pct=6.0))
        for k in ("hhi", "effective_harvests", "top_event_share",
                  "top3_event_share", "gini", "windfall_count",
                  "windfall_share", "coefficient_of_variation",
                  "harvest_total", "median_harvest"):
            self.assertIsNone(r[k])

    def test_override_sample_count_zero(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, recurring_apr_pct=6.0))
        self.assertEqual(r["sample_count"], 0)

    def test_samples_take_precedence(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100],
            recurring_apr_pct=999.0))
        self.assertTrue(r["used_samples"])
        self.assertFalse(r["used_override"])

    def test_single_sample_falls_back_to_override(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0,
            harvest_yield_samples=[100],
            recurring_apr_pct=8.0))
        self.assertFalse(r["used_samples"])
        self.assertTrue(r["used_override"])
        self.assertAlmostEqual(r["recurring_apr_pct"], 8.0)

    def test_override_recurring_above_headline_clamps(self):
        # recurring > headline → realization clamps to 1
        r = A()._analyze_one(make_pos(
            headline_apr_pct=10.0, recurring_apr_pct=15.0))
        self.assertAlmostEqual(r["realization_ratio"], 1.0)
        self.assertAlmostEqual(r["recurring_apr_pct"], 10.0)

    def test_override_negative_insufficient(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, recurring_apr_pct=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_nan_insufficient(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, recurring_apr_pct=float("nan")))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_zero_run_rate(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, recurring_apr_pct=0.0))
        self.assertAlmostEqual(r["realization_ratio"], 0.0)
        self.assertEqual(r["classification"], "WINDFALL_DOMINATED")


# ── insufficient-data tests ─────────────────────────────────────────────────────

class TestInsufficient(unittest.TestCase):
    def test_no_data_at_all(self):
        r = A()._analyze_one(make_pos())
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["score"], 0.0)
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_nan_headline(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=float("nan"),
            harvest_yield_samples=[100, 100, 100]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_headline(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=float("inf"),
            harvest_yield_samples=[100, 100, 100]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_headline(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=0.0,
            harvest_yield_samples=[100, 100, 100]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_headline(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=-5.0,
            harvest_yield_samples=[100, 100, 100]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_single_sample_no_override(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_uninterpretable(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=["x", None, {}, -1]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_zero_harvests(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[0, 0, 0, 0]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_nulls(self):
        r = A()._analyze_one(make_pos())
        for k in ("headline_apr_pct", "recurring_apr_pct", "overstatement_pct",
                  "realization_ratio", "concentration_index", "hhi",
                  "effective_harvests", "top_event_share", "gini",
                  "windfall_share", "harvest_total", "median_harvest"):
            self.assertIsNone(r[k])

    def test_insufficient_score_zero(self):
        r = A()._analyze_one(make_pos())
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A()._analyze_one(make_pos())
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")


# ── recommendation tests ─────────────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_trust_for_diverse(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 100]))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_slight_discount_for_mild(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 400]))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE_SLIGHTLY")

    def test_discount_for_concentrated(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 600]))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE")

    def test_avoid_for_windfall(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[1, 1, 1, 1000]))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")


# ── portfolio / aggregate tests ─────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def test_portfolio_structure(self):
        out = A().analyze_portfolio(_demo_positions())
        self.assertIn("positions", out)
        self.assertIn("aggregate", out)
        self.assertEqual(len(out["positions"]), 5)

    def test_aggregate_picks_best_worst(self):
        positions = [
            make_pos(vault="RECURRING",
                     harvest_yield_samples=[100, 100, 100, 100]),
            make_pos(vault="LUMPY",
                     harvest_yield_samples=[1, 1, 1, 1000]),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["most_recurring_vault"], "RECURRING")
        self.assertEqual(agg["most_lumpy_vault"], "LUMPY")

    def test_aggregate_all_insufficient(self):
        positions = [
            make_pos(vault="X"),
            make_pos(vault="Y", headline_apr_pct=float("nan")),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertIsNone(agg["most_recurring_vault"])
        self.assertIsNone(agg["most_lumpy_vault"])
        self.assertEqual(agg["avg_score"], 0.0)
        self.assertEqual(agg["position_count"], 2)

    def test_aggregate_windfall_count(self):
        positions = [
            make_pos(vault="A", harvest_yield_samples=[1, 1, 1, 1000]),
            make_pos(vault="B", harvest_yield_samples=[1, 1, 1, 2000]),
            make_pos(vault="C", harvest_yield_samples=[100, 100, 100, 100]),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["windfall_dominated_count"], 2)

    def test_aggregate_position_count(self):
        agg = A().analyze_portfolio(_demo_positions())["aggregate"]
        self.assertEqual(agg["position_count"], 5)

    def test_aggregate_avg_score(self):
        agg = A().analyze_portfolio(_demo_positions())["aggregate"]
        self.assertGreaterEqual(agg["avg_score"], 0.0)
        self.assertLessEqual(agg["avg_score"], 100.0)

    def test_empty_portfolio(self):
        out = A().analyze_portfolio([])
        self.assertEqual(out["positions"], [])
        self.assertEqual(out["aggregate"]["position_count"], 0)
        self.assertIsNone(out["aggregate"]["most_recurring_vault"])

    def test_analyze_single_public(self):
        r = A().analyze(make_pos(
            harvest_yield_samples=[100, 100, 100, 100]))
        self.assertEqual(r["classification"], "DIVERSE_RECURRING")


# ── finiteness / sentinel tests ─────────────────────────────────────────────────

class TestFiniteness(unittest.TestCase):
    def test_all_demo_finite(self):
        out = A().analyze_portfolio(_demo_positions())
        for r in out["positions"]:
            finite_check(self, r)

    def test_aggregate_finite(self):
        out = A().analyze_portfolio(_demo_positions())
        for v in out["aggregate"].values():
            if isinstance(v, float):
                self.assertTrue(math.isfinite(v))

    def test_finite_windfall(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[1, 1, 1, 1000]))
        finite_check(self, r)

    def test_finite_extreme_values(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=1e6,
            harvest_yield_samples=[1e9, 1.0, 1.0]))
        finite_check(self, r)

    def test_finite_override(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, recurring_apr_pct=6.0))
        finite_check(self, r)

    def test_grade_present(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 100]))
        self.assertIn(r["grade"], ("A", "B", "C", "D", "F"))

    def test_all_demo_float_fields_finite_deep(self):
        out = A().analyze_portfolio(_demo_positions())
        for r in out["positions"]:
            for k, v in r.items():
                if isinstance(v, float):
                    self.assertTrue(
                        math.isfinite(v), f"{k}={v} not finite")


# ── grade mapping tests ──────────────────────────────────────────────────────────

class TestGradeMapping(unittest.TestCase):
    def test_diverse_grade_a(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100, 100]))
        self.assertEqual(r["grade"], "A")

    def test_windfall_low_grade(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[1, 1, 1, 1, 2000]))
        self.assertIn(r["grade"], ("D", "F"))


# ── logging tests ────────────────────────────────────────────────────────────────

class TestLogging(unittest.TestCase):
    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "sub", "log.json")
            cfg = {"log_path": log_path, "log_cap": 5}
            A().analyze_portfolio(
                _demo_positions(), cfg=cfg, write_log=True)
            self.assertTrue(os.path.exists(log_path))
            with open(log_path) as fh:
                log = json.load(fh)
            self.assertEqual(len(log), 1)
            self.assertIn("aggregate", log[0])
            self.assertIn("snapshots", log[0])

    def test_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 3}
            for _ in range(6):
                A().analyze_portfolio(
                    _demo_positions(), cfg=cfg, write_log=True)
            with open(log_path) as fh:
                log = json.load(fh)
            self.assertEqual(len(log), 3)

    def test_log_cap_default_100(self):
        self.assertEqual(LOG_CAP, 100)

    def test_log_recovers_from_corrupt(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            with open(log_path, "w") as fh:
                fh.write("{ not json")
            cfg = {"log_path": log_path, "log_cap": 5}
            A().analyze_portfolio(
                _demo_positions(), cfg=cfg, write_log=True)
            with open(log_path) as fh:
                log = json.load(fh)
            self.assertEqual(len(log), 1)

    def test_no_tmp_left_behind(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 5}
            A().analyze_portfolio(
                _demo_positions(), cfg=cfg, write_log=True)
            self.assertFalse(os.path.exists(log_path + ".tmp"))

    def test_no_log_when_write_false(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 5}
            A().analyze_portfolio(_demo_positions(), cfg=cfg, write_log=False)
            self.assertFalse(os.path.exists(log_path))

    def test_log_single_analyze(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "log.json")
            cfg = {"log_path": log_path, "log_cap": 5}
            A().analyze(
                make_pos(harvest_yield_samples=[100, 100, 100]),
                cfg=cfg, write_log=True)
            self.assertTrue(os.path.exists(log_path))


# ── demo / structural tests ──────────────────────────────────────────────────────

class TestDemoStructure(unittest.TestCase):
    def test_demo_has_five(self):
        self.assertEqual(len(_demo_positions()), 5)

    def test_demo_classifications_present(self):
        out = A().analyze_portfolio(_demo_positions())
        classes = {r["classification"] for r in out["positions"]}
        self.assertIn("DIVERSE_RECURRING", classes)
        self.assertIn("WINDFALL_DOMINATED", classes)
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_has_override(self):
        out = A().analyze_portfolio(_demo_positions())
        self.assertTrue(any(r["used_override"] for r in out["positions"]))

    def test_demo_has_samples(self):
        out = A().analyze_portfolio(_demo_positions())
        self.assertTrue(any(r["used_samples"] for r in out["positions"]))

    def test_required_keys_present(self):
        r = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100]))
        for key in (
            "token", "headline_apr_pct", "recurring_apr_pct",
            "overstatement_pct", "realization_ratio", "concentration_index",
            "hhi", "effective_harvests", "top_event_share", "top3_event_share",
            "gini", "windfall_count", "windfall_share",
            "coefficient_of_variation", "harvest_total", "median_harvest",
            "sample_count", "used_samples", "used_override", "score",
            "classification", "recommendation", "grade", "flags",
        ):
            self.assertIn(key, r)

    def test_insufficient_keys_match(self):
        full = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100]))
        insuff = A()._analyze_one(make_pos())
        self.assertEqual(set(full.keys()), set(insuff.keys()))

    def test_override_keys_match(self):
        full = A()._analyze_one(make_pos(
            harvest_yield_samples=[100, 100, 100]))
        ov = A()._analyze_one(make_pos(
            headline_apr_pct=20.0, recurring_apr_pct=6.0))
        self.assertEqual(set(full.keys()), set(ov.keys()))

    def test_token_fallback_unknown(self):
        r = A()._analyze_one({
            "headline_apr_pct": 10.0,
            "harvest_yield_samples": [100, 100, 100]})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_token_from_vault(self):
        r = A()._analyze_one(make_pos(
            vault="MyVault", harvest_yield_samples=[100, 100, 100]))
        self.assertEqual(r["token"], "MyVault")

    def test_token_from_token_field(self):
        r = A()._analyze_one({
            "token": "TKN",
            "headline_apr_pct": 10.0,
            "harvest_yield_samples": [100, 100, 100]})
        self.assertEqual(r["token"], "TKN")

    def test_constants_sane(self):
        self.assertEqual(MIN_SAMPLES, 2)
        self.assertEqual(WINDFALL_MULTIPLE_DEFAULT, 4.0)
        self.assertLess(DIVERSE_IDX, MILD_IDX)
        self.assertLess(MILD_IDX, CONCENTRATED_IDX)
        self.assertEqual(SINGLE_EVENT_SHARE, 0.50)
        self.assertEqual(HIGH_CV, 1.0)
        self.assertEqual(FEW_HARVESTS_N, 4)


# ── honesty-angle scenario tests ─────────────────────────────────────────────────

class TestHonestyScenarios(unittest.TestCase):
    def test_airdrop_windfall_overstates_headline(self):
        # 40% headline, one airdrop harvest dwarfs the rest → run-rate << headline
        r = A()._analyze_one(make_pos(
            headline_apr_pct=40.0,
            harvest_yield_samples=[50, 45, 55, 48, 1800, 52]))
        self.assertEqual(r["classification"], "WINDFALL_DOMINATED")
        self.assertLess(r["recurring_apr_pct"], 15.0)
        self.assertGreater(r["overstatement_pct"], 25.0)
        self.assertIn("SINGLE_EVENT_DOMINATED", r["flags"])

    def test_steady_yield_headline_trustworthy(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=10.0,
            harvest_yield_samples=[100, 99, 101, 100, 102, 98]))
        self.assertEqual(r["classification"], "DIVERSE_RECURRING")
        self.assertAlmostEqual(r["recurring_apr_pct"], 10.0, delta=1.0)
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_two_lumps_concentrated(self):
        # two big bribe epochs among small ones
        r = A()._analyze_one(make_pos(
            headline_apr_pct=25.0,
            harvest_yield_samples=[10, 10, 10, 500, 500]))
        self.assertIn(r["classification"], ("CONCENTRATED", "WINDFALL_DOMINATED"))
        self.assertLess(r["recurring_apr_pct"], r["headline_apr_pct"])


if __name__ == "__main__":
    unittest.main()
