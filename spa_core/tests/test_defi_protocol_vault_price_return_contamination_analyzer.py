"""
Tests for MP-1199: DeFiProtocolVaultPriceReturnContaminationAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_price_return_contamination_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_price_return_contamination_analyzer import (  # noqa: E501
    DeFiProtocolVaultPriceReturnContaminationAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _coerce_num,
    _pair_samples,
    _pstdev,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    MIN_SAMPLES,
    DEFAULT_PERIODS_PER_YEAR,
    PURE_YIELD_FRAC,
    LIGHT_CONTAM_FRAC,
    MODERATE_CONTAM_FRAC,
    RALLY_INFLATED_FRAC,
    APPRECIATION_FRAC,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Vault",
    headline_apr_pct=20.0,
    total_return_samples=None,
    price_return_samples=None,
    recurring_yield_apr_pct=None,
    price_return_contribution_pct=None,
    periods_per_year=None,
):
    pos = {"vault": vault, "headline_apr_pct": headline_apr_pct}
    if total_return_samples is not None:
        pos["total_return_samples"] = total_return_samples
    if price_return_samples is not None:
        pos["price_return_samples"] = price_return_samples
    if recurring_yield_apr_pct is not None:
        pos["recurring_yield_apr_pct"] = recurring_yield_apr_pct
    if price_return_contribution_pct is not None:
        pos["price_return_contribution_pct"] = price_return_contribution_pct
    if periods_per_year is not None:
        pos["periods_per_year"] = periods_per_year
    return pos


def A():
    return DeFiProtocolVaultPriceReturnContaminationAnalyzer()


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


# ── _pair_samples tests ─────────────────────────────────────────────────────────

class TestPairSamples(unittest.TestCase):
    def test_basic_pairing(self):
        t, p = _pair_samples([1.0, 2.0], [0.5, 0.5])
        self.assertEqual(t, [1.0, 2.0])
        self.assertEqual(p, [0.5, 0.5])

    def test_skip_bad_total(self):
        t, p = _pair_samples([1.0, float("nan"), 3.0], [0.1, 0.2, 0.3])
        self.assertEqual(t, [1.0, 3.0])
        self.assertEqual(p, [0.1, 0.3])

    def test_skip_bad_price(self):
        t, p = _pair_samples([1.0, 2.0, 3.0], [0.1, "bad", 0.3])
        self.assertEqual(t, [1.0, 3.0])
        self.assertEqual(p, [0.1, 0.3])

    def test_skip_both_bad(self):
        t, p = _pair_samples([1.0, None, 3.0], [0.1, None, 0.3])
        self.assertEqual(t, [1.0, 3.0])
        self.assertEqual(p, [0.1, 0.3])

    def test_unequal_length_zips_shortest(self):
        t, p = _pair_samples([1.0, 2.0, 3.0], [0.1, 0.2])
        self.assertEqual(len(t), 2)
        self.assertEqual(len(p), 2)

    def test_empty_inputs(self):
        t, p = _pair_samples(None, None)
        self.assertEqual(t, [])
        self.assertEqual(p, [])

    def test_order_preserved(self):
        t, p = _pair_samples([3.0, 1.0, 2.0], [0.3, 0.1, 0.2])
        self.assertEqual(t, [3.0, 1.0, 2.0])

    def test_inf_skipped(self):
        t, p = _pair_samples([1.0, float("inf")], [0.1, 0.2])
        self.assertEqual(t, [1.0])

    def test_string_numbers_paired(self):
        t, p = _pair_samples(["1.0", "2.0"], ["0.1", "0.2"])
        self.assertEqual(t, [1.0, 2.0])
        self.assertEqual(p, [0.1, 0.2])


# ── _pstdev tests ───────────────────────────────────────────────────────────────

class TestPstdev(unittest.TestCase):
    def test_single_value(self):
        self.assertEqual(_pstdev([5.0]), 0.0)

    def test_empty(self):
        self.assertEqual(_pstdev([]), 0.0)

    def test_constant(self):
        self.assertEqual(_pstdev([3.0, 3.0, 3.0]), 0.0)

    def test_known_value(self):
        # pstdev of [2,4] = 1.0
        self.assertAlmostEqual(_pstdev([2.0, 4.0]), 1.0)

    def test_finite(self):
        self.assertTrue(math.isfinite(_pstdev([1.0, 2.0, 3.0, 4.0])))


# ── decomposition math tests ────────────────────────────────────────────────────

class TestDecompositionMath(unittest.TestCase):
    def test_recurring_equals_total_minus_price(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0,
            total_return_samples=[0.05, 0.05],
            price_return_samples=[0.02, 0.02],
            periods_per_year=100.0))
        # recurring per period = 0.03 → *100 = 3.0
        self.assertAlmostEqual(r["recurring_yield_apr_pct"], 3.0)
        self.assertAlmostEqual(r["price_return_contribution_pct"], 2.0)
        self.assertAlmostEqual(r["total_window_apr_pct"], 5.0)

    def test_total_equals_recurring_plus_price(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.04, 0.06],
            price_return_samples=[0.01, 0.03],
            periods_per_year=100.0))
        self.assertAlmostEqual(
            r["recurring_yield_apr_pct"] + r["price_return_contribution_pct"],
            r["total_window_apr_pct"])

    def test_negative_price_raises_recurring_above_headline(self):
        # price negative → recurring = total - (negative) > total
        r = A()._analyze_one(make_pos(
            headline_apr_pct=5.0,
            total_return_samples=[0.05, 0.05],
            price_return_samples=[-0.02, -0.02],
            periods_per_year=100.0))
        self.assertAlmostEqual(r["price_return_contribution_pct"], -2.0)
        self.assertAlmostEqual(r["recurring_yield_apr_pct"], 7.0)
        self.assertGreater(
            r["recurring_yield_apr_pct"], r["headline_apr_pct"])

    def test_overstatement_is_headline_minus_recurring(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=22.0,
            total_return_samples=[0.06, 0.06],
            price_return_samples=[0.04, 0.04],
            periods_per_year=100.0))
        # recurring = 0.02*100 = 2.0; overstatement = 22 - 2 = 20
        self.assertAlmostEqual(r["overstatement_pct"], 20.0)

    def test_realization_ratio(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=10.0,
            total_return_samples=[0.05, 0.05],
            price_return_samples=[0.04, 0.04],
            periods_per_year=100.0))
        # recurring = 1.0; ratio = 1.0/10.0 = 0.1
        self.assertAlmostEqual(r["realization_ratio"], 0.1)

    def test_periods_per_year_default(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.01, 0.01],
            price_return_samples=[0.0, 0.0]))
        self.assertAlmostEqual(r["periods_per_year"], DEFAULT_PERIODS_PER_YEAR)

    def test_periods_per_year_effect(self):
        lo = A()._analyze_one(make_pos(
            total_return_samples=[0.01, 0.01],
            price_return_samples=[0.0, 0.0],
            periods_per_year=100.0))
        hi = A()._analyze_one(make_pos(
            total_return_samples=[0.01, 0.01],
            price_return_samples=[0.0, 0.0],
            periods_per_year=200.0))
        self.assertAlmostEqual(
            hi["recurring_yield_apr_pct"],
            2.0 * lo["recurring_yield_apr_pct"])

    def test_invalid_ppy_falls_back_to_default(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.01, 0.01],
            price_return_samples=[0.0, 0.0],
            periods_per_year=-5.0))
        self.assertAlmostEqual(r["periods_per_year"], DEFAULT_PERIODS_PER_YEAR)

    def test_nan_ppy_falls_back(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.01, 0.01],
            price_return_samples=[0.0, 0.0],
            periods_per_year=float("nan")))
        self.assertAlmostEqual(r["periods_per_year"], DEFAULT_PERIODS_PER_YEAR)

    def test_sample_count_reported(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.01, 0.02, 0.03],
            price_return_samples=[0.0, 0.0, 0.0]))
        self.assertEqual(r["sample_count"], 3)

    def test_used_samples_flag(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.01, 0.02],
            price_return_samples=[0.0, 0.0]))
        self.assertTrue(r["used_samples"])
        self.assertFalse(r["used_override"])

    def test_price_volatility_computed(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.05, 0.05, 0.05],
            price_return_samples=[0.01, 0.03, 0.05]))
        self.assertIsNotNone(r["price_return_volatility_pct"])
        self.assertGreater(r["price_return_volatility_pct"], 0.0)

    def test_recurring_volatility_computed(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.05, 0.07, 0.09],
            price_return_samples=[0.01, 0.01, 0.01]))
        self.assertIsNotNone(r["recurring_yield_volatility_pct"])

    def test_filters_nonfinite_pairs(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.05, float("nan"), 0.05, "bad"],
            price_return_samples=[0.02, 0.02, 0.02, 0.02]))
        self.assertEqual(r["sample_count"], 2)


# ── classification tests ────────────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_pure_yield(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=8.0,
            total_return_samples=[0.022, 0.022, 0.022],
            price_return_samples=[0.0, 0.0005, -0.0005],
            periods_per_year=365.0))
        self.assertEqual(r["classification"], "PURE_YIELD")

    def test_lightly_contaminated(self):
        # price ~10% of magnitude
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10],
            price_return_samples=[0.01, 0.01],
            periods_per_year=100.0))
        self.assertEqual(r["classification"], "LIGHTLY_CONTAMINATED")

    def test_moderately_contaminated(self):
        # price ~33% of magnitude
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.06, 0.06],
            price_return_samples=[0.02, 0.02],
            periods_per_year=100.0))
        self.assertEqual(r["classification"], "MODERATELY_CONTAMINATED")

    def test_price_driven(self):
        # price > 50% of magnitude
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10],
            price_return_samples=[0.08, 0.08],
            periods_per_year=100.0))
        self.assertEqual(r["classification"], "PRICE_DRIVEN")

    def test_pure_yield_boundary(self):
        # contamination exactly at PURE_YIELD_FRAC: price=5, rec=95 → 0.05
        r = A()._analyze_one(make_pos(
            total_return_samples=[1.0, 1.0],
            price_return_samples=[0.05, 0.05],
            periods_per_year=1.0))
        self.assertLessEqual(r["contamination_fraction"], PURE_YIELD_FRAC)
        self.assertEqual(r["classification"], "PURE_YIELD")

    def test_light_boundary(self):
        # price=20, rec=80 → 0.20
        r = A()._analyze_one(make_pos(
            total_return_samples=[1.0, 1.0],
            price_return_samples=[0.20, 0.20],
            periods_per_year=1.0))
        self.assertAlmostEqual(r["contamination_fraction"], 0.20)
        self.assertEqual(r["classification"], "LIGHTLY_CONTAMINATED")

    def test_moderate_boundary(self):
        # price=50, rec=50 → 0.50
        r = A()._analyze_one(make_pos(
            total_return_samples=[1.0, 1.0],
            price_return_samples=[0.50, 0.50],
            periods_per_year=1.0))
        self.assertAlmostEqual(r["contamination_fraction"], 0.50)
        self.assertEqual(r["classification"], "MODERATELY_CONTAMINATED")

    def test_above_moderate_is_price_driven(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[1.0, 1.0],
            price_return_samples=[0.51, 0.51],
            periods_per_year=1.0))
        self.assertGreater(r["contamination_fraction"], MODERATE_CONTAM_FRAC)
        self.assertEqual(r["classification"], "PRICE_DRIVEN")

    def test_zero_contamination_pure(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.05, 0.05],
            price_return_samples=[0.0, 0.0],
            periods_per_year=100.0))
        self.assertAlmostEqual(r["contamination_fraction"], 0.0)
        self.assertEqual(r["classification"], "PURE_YIELD")


# ── contamination_fraction bounds ────────────────────────────────────────────────

class TestContaminationBounds(unittest.TestCase):
    def test_fraction_in_unit_range_various(self):
        cases = [
            ([0.05, 0.05], [0.0, 0.0]),
            ([0.05, 0.05], [0.05, 0.05]),
            ([0.05, 0.05], [-0.03, -0.03]),
            ([0.10, 0.02], [0.09, 0.01]),
            ([-0.05, -0.05], [-0.05, -0.05]),
        ]
        for tot, pri in cases:
            r = A()._analyze_one(make_pos(
                total_return_samples=tot, price_return_samples=pri,
                periods_per_year=100.0))
            cf = r["contamination_fraction"]
            self.assertGreaterEqual(cf, 0.0)
            self.assertLessEqual(cf, 1.0)

    def test_all_price_fraction_near_one(self):
        # recurring = 0, all is price
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.05, 0.05],
            price_return_samples=[0.05, 0.05],
            periods_per_year=100.0))
        self.assertAlmostEqual(r["contamination_fraction"], 1.0)

    def test_negative_price_still_in_range(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.03, 0.03],
            price_return_samples=[-0.06, -0.06],
            periods_per_year=100.0))
        self.assertGreaterEqual(r["contamination_fraction"], 0.0)
        self.assertLessEqual(r["contamination_fraction"], 1.0)


# ── score tests ──────────────────────────────────────────────────────────────────

class TestScore(unittest.TestCase):
    def test_score_in_range(self):
        for r in A().analyze_portfolio(_demo_positions())["positions"]:
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_pure_yield_high_score(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.05, 0.05, 0.05],
            price_return_samples=[0.0, 0.0, 0.0],
            periods_per_year=100.0))
        self.assertGreaterEqual(r["score"], 95.0)

    def test_price_driven_low_score(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10],
            price_return_samples=[0.09, 0.09],
            periods_per_year=100.0))
        self.assertLess(r["score"], 50.0)

    def test_score_monotonic_more_price_lower_score(self):
        low_contam = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10],
            price_return_samples=[0.01, 0.01],
            periods_per_year=100.0))
        high_contam = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10],
            price_return_samples=[0.08, 0.08],
            periods_per_year=100.0))
        self.assertGreater(low_contam["score"], high_contam["score"])

    def test_score_monotonic_chain(self):
        scores = []
        for price in [0.0, 0.02, 0.04, 0.06, 0.08]:
            r = A()._analyze_one(make_pos(
                total_return_samples=[0.10, 0.10],
                price_return_samples=[price, price],
                periods_per_year=100.0))
            scores.append(r["score"])
        for a, b in zip(scores, scores[1:]):
            self.assertGreaterEqual(a, b)

    def test_score_clamped_max(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.05, 0.05],
            price_return_samples=[0.0, 0.0],
            periods_per_year=100.0))
        self.assertLessEqual(r["score"], 100.0)

    def test_override_score_neutral_stability(self):
        # override path → stability full weight (1.0)
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0,
            recurring_yield_apr_pct=18.0,
            price_return_contribution_pct=2.0))
        # contamination = 2/20 = 0.1, purity=0.9 → 70*0.9 + 30*1.0 = 93
        self.assertAlmostEqual(r["score"], 93.0, places=1)

    def test_high_price_vol_lowers_score(self):
        smooth = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10, 0.10],
            price_return_samples=[0.03, 0.03, 0.03],
            periods_per_year=100.0))
        volatile = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10, 0.10],
            price_return_samples=[0.0, 0.03, 0.06],
            periods_per_year=100.0))
        # same mean price contribution but volatile has price vol penalty
        self.assertGreaterEqual(smooth["score"], volatile["score"])


# ── flag tests ──────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_pure_yield_flags(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.05, 0.05],
            price_return_samples=[0.0, 0.0],
            periods_per_year=100.0))
        self.assertIn("PURE_YIELD", r["flags"])
        self.assertIn("GENUINE_YIELD", r["flags"])

    def test_price_rally_inflated_flag(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10],
            price_return_samples=[0.04, 0.04],
            periods_per_year=100.0))
        self.assertIn("PRICE_RALLY_INFLATED", r["flags"])

    def test_no_rally_flag_when_price_negative(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10],
            price_return_samples=[-0.04, -0.04],
            periods_per_year=100.0))
        self.assertNotIn("PRICE_RALLY_INFLATED", r["flags"])

    def test_recurring_negative_flag(self):
        # total < price → recurring negative
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.02, 0.02],
            price_return_samples=[0.05, 0.05],
            periods_per_year=100.0))
        self.assertIn("RECURRING_YIELD_NEGATIVE", r["flags"])
        self.assertLess(r["recurring_yield_apr_pct"], 0.0)

    def test_mean_reversion_exposed_flag(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10, 0.10],
            price_return_samples=[0.0, 0.04, 0.08],
            periods_per_year=100.0))
        self.assertIn("MEAN_REVERSION_EXPOSED", r["flags"])

    def test_no_mean_reversion_flag_when_price_constant(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10],
            price_return_samples=[0.03, 0.03],
            periods_per_year=100.0))
        self.assertNotIn("MEAN_REVERSION_EXPOSED", r["flags"])

    def test_headline_from_appreciation_flag(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10],
            price_return_samples=[0.08, 0.08],
            periods_per_year=100.0))
        self.assertIn("HEADLINE_FROM_APPRECIATION", r["flags"])

    def test_no_appreciation_flag_when_low_contam(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10],
            price_return_samples=[0.01, 0.01],
            periods_per_year=100.0))
        self.assertNotIn("HEADLINE_FROM_APPRECIATION", r["flags"])

    def test_override_flag(self):
        r = A()._analyze_one(make_pos(
            recurring_yield_apr_pct=10.0,
            price_return_contribution_pct=2.0))
        self.assertIn("CONTRIBUTION_FROM_OVERRIDE", r["flags"])

    def test_no_override_flag_when_samples(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.05, 0.05],
            price_return_samples=[0.0, 0.0]))
        self.assertNotIn("CONTRIBUTION_FROM_OVERRIDE", r["flags"])

    def test_genuine_yield_only_when_pure(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10],
            price_return_samples=[0.08, 0.08],
            periods_per_year=100.0))
        self.assertNotIn("GENUINE_YIELD", r["flags"])

    def test_classification_flag_present(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.06, 0.06],
            price_return_samples=[0.02, 0.02],
            periods_per_year=100.0))
        self.assertIn(r["classification"], r["flags"])


# ── override path tests ─────────────────────────────────────────────────────────

class TestOverridePath(unittest.TestCase):
    def test_both_overrides(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=30.0,
            recurring_yield_apr_pct=6.0,
            price_return_contribution_pct=24.0))
        self.assertAlmostEqual(r["recurring_yield_apr_pct"], 6.0)
        self.assertAlmostEqual(r["price_return_contribution_pct"], 24.0)
        self.assertTrue(r["used_override"])
        self.assertFalse(r["used_samples"])

    def test_recurring_override_only_derives_price(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0,
            recurring_yield_apr_pct=8.0))
        # price = headline - recurring = 12
        self.assertAlmostEqual(r["price_return_contribution_pct"], 12.0)

    def test_price_override_only_derives_recurring(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=20.0,
            price_return_contribution_pct=14.0))
        # recurring = headline - price = 6
        self.assertAlmostEqual(r["recurring_yield_apr_pct"], 6.0)

    def test_samples_take_precedence_over_override(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.05, 0.05],
            price_return_samples=[0.0, 0.0],
            recurring_yield_apr_pct=999.0,
            price_return_contribution_pct=999.0,
            periods_per_year=100.0))
        self.assertTrue(r["used_samples"])
        self.assertFalse(r["used_override"])
        self.assertNotAlmostEqual(r["recurring_yield_apr_pct"], 999.0)

    def test_single_sample_falls_back_to_override(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.05],
            price_return_samples=[0.01],
            recurring_yield_apr_pct=10.0,
            price_return_contribution_pct=2.0))
        self.assertFalse(r["used_samples"])
        self.assertTrue(r["used_override"])
        self.assertAlmostEqual(r["recurring_yield_apr_pct"], 10.0)

    def test_override_nan_recurring_insufficient(self):
        r = A()._analyze_one(make_pos(
            recurring_yield_apr_pct=float("nan"),
            price_return_contribution_pct=2.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_nan_price_insufficient(self):
        r = A()._analyze_one(make_pos(
            recurring_yield_apr_pct=10.0,
            price_return_contribution_pct=float("inf")))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_override_volatility_none(self):
        r = A()._analyze_one(make_pos(
            recurring_yield_apr_pct=10.0,
            price_return_contribution_pct=2.0))
        self.assertIsNone(r["price_return_volatility_pct"])
        self.assertIsNone(r["recurring_yield_volatility_pct"])

    def test_override_sample_count_zero(self):
        r = A()._analyze_one(make_pos(
            recurring_yield_apr_pct=10.0,
            price_return_contribution_pct=2.0))
        self.assertEqual(r["sample_count"], 0)


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
            total_return_samples=[0.05, 0.05],
            price_return_samples=[0.0, 0.0]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_inf_headline(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=float("inf"),
            total_return_samples=[0.05, 0.05],
            price_return_samples=[0.0, 0.0]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_single_pair_no_override(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.05],
            price_return_samples=[0.01]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_uninterpretable_pairs(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=["x", None, {}],
            price_return_samples=["y", None, []]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_headline_no_data(self):
        r = A()._analyze_one(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_zero_degenerate(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=0.0,
            total_return_samples=[0.0, 0.0],
            price_return_samples=[0.0, 0.0]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_nulls(self):
        r = A()._analyze_one(make_pos())
        self.assertIsNone(r["recurring_yield_apr_pct"])
        self.assertIsNone(r["price_return_contribution_pct"])
        self.assertIsNone(r["contamination_fraction"])
        self.assertIsNone(r["headline_apr_pct"])
        self.assertIsNone(r["realization_ratio"])

    def test_insufficient_score_zero(self):
        r = A()._analyze_one(make_pos())
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A()._analyze_one(make_pos())
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")


# ── recommendation tests ─────────────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_trust_for_pure(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.05, 0.05],
            price_return_samples=[0.0, 0.0],
            periods_per_year=100.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_slight_discount_for_light(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10],
            price_return_samples=[0.01, 0.01],
            periods_per_year=100.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE_SLIGHTLY")

    def test_discount_for_moderate(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.06, 0.06],
            price_return_samples=[0.02, 0.02],
            periods_per_year=100.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE")

    def test_avoid_for_price_driven(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10],
            price_return_samples=[0.08, 0.08],
            periods_per_year=100.0))
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
            make_pos(vault="HONEST",
                     total_return_samples=[0.05, 0.05],
                     price_return_samples=[0.0, 0.0],
                     periods_per_year=100.0),
            make_pos(vault="CONTAMINATED",
                     total_return_samples=[0.10, 0.10],
                     price_return_samples=[0.09, 0.09],
                     periods_per_year=100.0),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["most_honest_vault"], "HONEST")
        self.assertEqual(agg["least_honest_vault"], "CONTAMINATED")

    def test_aggregate_all_insufficient(self):
        positions = [
            make_pos(vault="X"),
            make_pos(vault="Y", headline_apr_pct=float("nan")),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertIsNone(agg["most_honest_vault"])
        self.assertIsNone(agg["least_honest_vault"])
        self.assertEqual(agg["avg_score"], 0.0)
        self.assertEqual(agg["position_count"], 2)

    def test_aggregate_price_driven_count(self):
        positions = [
            make_pos(vault="A",
                     total_return_samples=[0.10, 0.10],
                     price_return_samples=[0.09, 0.09],
                     periods_per_year=100.0),
            make_pos(vault="B",
                     total_return_samples=[0.10, 0.10],
                     price_return_samples=[0.08, 0.08],
                     periods_per_year=100.0),
            make_pos(vault="C",
                     total_return_samples=[0.05, 0.05],
                     price_return_samples=[0.0, 0.0],
                     periods_per_year=100.0),
        ]
        agg = A().analyze_portfolio(positions)["aggregate"]
        self.assertEqual(agg["price_driven_count"], 2)

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
        self.assertIsNone(out["aggregate"]["most_honest_vault"])

    def test_analyze_single_public(self):
        r = A().analyze(make_pos(
            total_return_samples=[0.05, 0.05],
            price_return_samples=[0.0, 0.0],
            periods_per_year=100.0))
        self.assertEqual(r["classification"], "PURE_YIELD")


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

    def test_finite_price_driven(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10],
            price_return_samples=[0.09, 0.09],
            periods_per_year=100.0))
        finite_check(self, r)

    def test_finite_negative_recurring(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.02, 0.02],
            price_return_samples=[0.08, 0.08],
            periods_per_year=100.0))
        finite_check(self, r)

    def test_finite_override(self):
        r = A()._analyze_one(make_pos(
            recurring_yield_apr_pct=6.0,
            price_return_contribution_pct=24.0))
        finite_check(self, r)

    def test_no_inf_nan_extreme_values(self):
        r = A()._analyze_one(make_pos(
            headline_apr_pct=1e6,
            total_return_samples=[1e5, 1e5],
            price_return_samples=[1e5, 1e5],
            periods_per_year=1.0))
        finite_check(self, r)

    def test_grade_present(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.05, 0.05],
            price_return_samples=[0.0, 0.0],
            periods_per_year=100.0))
        self.assertIn(r["grade"], ("A", "B", "C", "D", "F"))

    def test_all_demo_float_fields_finite_deep(self):
        out = A().analyze_portfolio(_demo_positions())
        for r in out["positions"]:
            for k, v in r.items():
                if isinstance(v, float):
                    self.assertTrue(
                        math.isfinite(v), f"{k}={v} not finite")


# ── grade boundary on actual results ─────────────────────────────────────────────

class TestGradeMapping(unittest.TestCase):
    def test_pure_yield_grade_a(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.05, 0.05],
            price_return_samples=[0.0, 0.0],
            periods_per_year=100.0))
        self.assertEqual(r["grade"], "A")

    def test_price_driven_low_grade(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.10, 0.10],
            price_return_samples=[0.095, 0.095],
            periods_per_year=100.0))
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
                make_pos(total_return_samples=[0.05, 0.05],
                         price_return_samples=[0.0, 0.0]),
                cfg=cfg, write_log=True)
            self.assertTrue(os.path.exists(log_path))


# ── demo / structural tests ──────────────────────────────────────────────────────

class TestDemoStructure(unittest.TestCase):
    def test_demo_has_five(self):
        self.assertEqual(len(_demo_positions()), 5)

    def test_demo_classifications_present(self):
        out = A().analyze_portfolio(_demo_positions())
        classes = {r["classification"] for r in out["positions"]}
        self.assertIn("PURE_YIELD", classes)
        self.assertIn("PRICE_DRIVEN", classes)
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_has_override(self):
        out = A().analyze_portfolio(_demo_positions())
        self.assertTrue(any(r["used_override"] for r in out["positions"]))

    def test_demo_has_samples(self):
        out = A().analyze_portfolio(_demo_positions())
        self.assertTrue(any(r["used_samples"] for r in out["positions"]))

    def test_required_keys_present(self):
        r = A()._analyze_one(make_pos(
            total_return_samples=[0.05, 0.05],
            price_return_samples=[0.0, 0.0]))
        for key in (
            "token", "headline_apr_pct", "recurring_yield_apr_pct",
            "price_return_contribution_pct", "total_window_apr_pct",
            "overstatement_pct", "realization_ratio", "contamination_fraction",
            "price_return_volatility_pct", "recurring_yield_volatility_pct",
            "coefficient_of_variation", "periods_per_year", "sample_count",
            "used_samples", "used_override", "score", "classification",
            "recommendation", "grade", "flags",
        ):
            self.assertIn(key, r)

    def test_insufficient_keys_match(self):
        full = A()._analyze_one(make_pos(
            total_return_samples=[0.05, 0.05],
            price_return_samples=[0.0, 0.0]))
        insuff = A()._analyze_one(make_pos())
        self.assertEqual(set(full.keys()), set(insuff.keys()))

    def test_token_fallback_unknown(self):
        r = A()._analyze_one({
            "headline_apr_pct": 10.0,
            "total_return_samples": [0.05, 0.05],
            "price_return_samples": [0.0, 0.0]})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_token_from_vault(self):
        r = A()._analyze_one(make_pos(vault="MyVault",
                                      total_return_samples=[0.05, 0.05],
                                      price_return_samples=[0.0, 0.0]))
        self.assertEqual(r["token"], "MyVault")

    def test_token_from_token_field(self):
        r = A()._analyze_one({
            "token": "TKN",
            "headline_apr_pct": 10.0,
            "total_return_samples": [0.05, 0.05],
            "price_return_samples": [0.0, 0.0]})
        self.assertEqual(r["token"], "TKN")

    def test_constants_sane(self):
        self.assertEqual(MIN_SAMPLES, 2)
        self.assertLess(PURE_YIELD_FRAC, LIGHT_CONTAM_FRAC)
        self.assertLess(LIGHT_CONTAM_FRAC, MODERATE_CONTAM_FRAC)
        self.assertEqual(RALLY_INFLATED_FRAC, 0.20)
        self.assertEqual(APPRECIATION_FRAC, 0.50)
        self.assertEqual(DEFAULT_PERIODS_PER_YEAR, 365.0)


# ── honesty-angle scenario tests ─────────────────────────────────────────────────

class TestHonestyScenarios(unittest.TestCase):
    def test_22pct_headline_14pp_price(self):
        # headline 22%, ~14pp price, recurring ~8%
        r = A()._analyze_one(make_pos(
            headline_apr_pct=22.0,
            recurring_yield_apr_pct=8.0,
            price_return_contribution_pct=14.0))
        self.assertAlmostEqual(r["recurring_yield_apr_pct"], 8.0)
        self.assertAlmostEqual(r["price_return_contribution_pct"], 14.0)
        self.assertAlmostEqual(r["overstatement_pct"], 14.0)
        # contamination = 14/22 ≈ 0.636 → PRICE_DRIVEN
        self.assertEqual(r["classification"], "PRICE_DRIVEN")

    def test_token_crash_recurring_above_headline(self):
        # token fell: price negative, recurring exceeds headline
        r = A()._analyze_one(make_pos(
            headline_apr_pct=2.0,
            recurring_yield_apr_pct=10.0,
            price_return_contribution_pct=-8.0))
        self.assertGreater(
            r["recurring_yield_apr_pct"], r["headline_apr_pct"])
        self.assertLess(r["price_return_contribution_pct"], 0.0)

    def test_negative_recurring_masks_bleed(self):
        # all the "yield" was price; recurring actually negative (fee/IL bleed)
        r = A()._analyze_one(make_pos(
            headline_apr_pct=15.0,
            recurring_yield_apr_pct=-3.0,
            price_return_contribution_pct=18.0))
        self.assertIn("RECURRING_YIELD_NEGATIVE", r["flags"])
        self.assertLess(r["recurring_yield_apr_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
