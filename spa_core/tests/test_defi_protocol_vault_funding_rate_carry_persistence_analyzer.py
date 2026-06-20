"""
Tests for MP-1196: DeFiProtocolVaultFundingRateCarryPersistenceAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_funding_rate_carry_persistence_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_funding_rate_carry_persistence_analyzer import (  # noqa: E501
    DeFiProtocolVaultFundingRateCarryPersistenceAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    MIN_SAMPLES,
    PERSISTENT_NEG_FRAC,
    MOSTLY_NEG_FRAC,
    MIXED_NEG_FRAC,
    DEEP_NEGATIVE_APR,
    SPIKE_RATIO,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="ETH-Basis",
    headline_apr_pct=12.0,
    funding_rate_samples=None,
):
    pos = {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
    }
    if funding_rate_samples is not None:
        pos["funding_rate_samples"] = funding_rate_samples
    else:
        pos["funding_rate_samples"] = [11.0, 12.0, 13.0]
    return pos


def A():
    return DeFiProtocolVaultFundingRateCarryPersistenceAnalyzer()


def finite_check(testcase, result):
    for v in result.values():
        if isinstance(v, float):
            testcase.assertTrue(math.isfinite(v), f"non-finite: {v}")


# ── helper-function tests ─────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    def test_f_valid_str(self):
        self.assertEqual(_f("3.5"), 3.5)

    def test_f_valid_int(self):
        self.assertEqual(_f(7), 7.0)

    def test_f_none_default(self):
        self.assertEqual(_f(None), 0.0)

    def test_f_none_custom_default(self):
        self.assertEqual(_f(None, 9.0), 9.0)

    def test_f_bad_str(self):
        self.assertEqual(_f("abc"), 0.0)

    def test_f_bad_list_default(self):
        self.assertEqual(_f([], 1.0), 1.0)

    def test_f_negative(self):
        self.assertEqual(_f("-5"), -5.0)

    def test_f_int_zero(self):
        self.assertEqual(_f(0), 0.0)

    def test_f_dict_default(self):
        self.assertEqual(_f({}, 2.0), 2.0)

    def test_f_float_passthrough(self):
        self.assertEqual(_f(4.25), 4.25)

    def test_f_negative_float(self):
        self.assertEqual(_f(-3.7), -3.7)

    def test_clamp_within(self):
        self.assertEqual(_clamp(5, 0, 10), 5)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1, 0, 10), 0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(11, 0, 10), 10)

    def test_clamp_exact_low(self):
        self.assertEqual(_clamp(0, 0, 10), 0)

    def test_clamp_exact_high(self):
        self.assertEqual(_clamp(10, 0, 10), 10)

    def test_clamp_unit_high(self):
        self.assertEqual(_clamp(1.5, 0.0, 1.0), 1.0)

    def test_clamp_unit_low(self):
        self.assertEqual(_clamp(-0.2, 0.0, 1.0), 0.0)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertAlmostEqual(_mean([2, 4, 6]), 4.0)

    def test_mean_single(self):
        self.assertAlmostEqual(_mean([8.0]), 8.0)

    def test_mean_negative(self):
        self.assertAlmostEqual(_mean([-2.0, 2.0]), 0.0)

    def test_mean_all_negative(self):
        self.assertAlmostEqual(_mean([-4.0, -6.0]), -5.0)

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

    def test_safe_div_negative_numerator(self):
        self.assertAlmostEqual(_safe_div(-10, 2, 0.0), -5.0)

    def test_build_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    def test_build_default_cfg_override_cap(self):
        cfg = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg["log_cap"], 5)
        self.assertEqual(cfg["log_path"], LOG_PATH)

    def test_build_default_cfg_none(self):
        cfg = _build_default_cfg(None)
        self.assertIn("log_path", cfg)

    def test_build_default_cfg_extra_key(self):
        cfg = _build_default_cfg({"extra": 1})
        self.assertEqual(cfg["extra"], 1)

    def test_build_default_cfg_override_path(self):
        cfg = _build_default_cfg({"log_path": "/x"})
        self.assertEqual(cfg["log_path"], "/x")

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

    def test_grade_boundary_a(self):
        self.assertEqual(_grade_from_score(85), "A")

    def test_grade_boundary_b(self):
        self.assertEqual(_grade_from_score(70), "B")

    def test_grade_boundary_c(self):
        self.assertEqual(_grade_from_score(55), "C")

    def test_grade_boundary_d(self):
        self.assertEqual(_grade_from_score(40), "D")

    def test_grade_below_d(self):
        self.assertEqual(_grade_from_score(39.9), "F")

    def test_grade_zero(self):
        self.assertEqual(_grade_from_score(0.0), "F")

    def test_grade_hundred(self):
        self.assertEqual(_grade_from_score(100.0), "A")

    def test_constants_ordered(self):
        self.assertLess(PERSISTENT_NEG_FRAC, MOSTLY_NEG_FRAC)
        self.assertLess(MOSTLY_NEG_FRAC, MIXED_NEG_FRAC)

    def test_constants_sane(self):
        self.assertGreaterEqual(MIN_SAMPLES, 2)
        self.assertLess(DEEP_NEGATIVE_APR, 0)
        self.assertGreater(SPIKE_RATIO, 1.0)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "headline_apr_pct", "realized_blended_apr_pct",
            "overstatement_pct", "realization_ratio",
            "negative_funding_fraction", "positive_funding_fraction",
            "avg_negative_funding_apr", "avg_positive_funding_apr",
            "min_funding_apr", "max_funding_apr", "sample_count",
            "sign_flips", "funding_flips_negative", "deep_negative",
            "headline_from_spike", "realized_negative_carry", "stable_carry",
            "score", "classification", "recommendation", "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_score_in_range(self):
        self.assertGreaterEqual(self.r["score"], 0.0)
        self.assertLessEqual(self.r["score"], 100.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_preserved(self):
        self.assertEqual(self.r["token"], "ETH-Basis")

    def test_token_field_alias(self):
        r = A().analyze({"token": "AltKey", "headline_apr_pct": 12.0,
                         "funding_rate_samples": [10.0, 11.0]})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "headline_apr_pct": 12.0,
                         "funding_rate_samples": [10.0, 11.0]})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"headline_apr_pct": 12.0,
                         "funding_rate_samples": [10.0, 11.0]})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "TRUST_HEADLINE", "DISCOUNT_HEADLINE_SLIGHTLY",
            "DISCOUNT_HEADLINE", "AVOID_OR_VERIFY",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "PERSISTENT_POSITIVE", "MOSTLY_POSITIVE", "REGIME_MIXED",
            "FUNDING_UNRELIABLE", "INSUFFICIENT_DATA",
        })

    def test_sample_count_int(self):
        self.assertIsInstance(self.r["sample_count"], int)

    def test_sign_flips_int(self):
        self.assertIsInstance(self.r["sign_flips"], int)

    def test_funding_flips_negative_bool(self):
        self.assertIsInstance(self.r["funding_flips_negative"], bool)

    def test_deep_negative_bool(self):
        self.assertIsInstance(self.r["deep_negative"], bool)

    def test_headline_from_spike_bool(self):
        self.assertIsInstance(self.r["headline_from_spike"], bool)

    def test_realized_negative_carry_bool(self):
        self.assertIsInstance(self.r["realized_negative_carry"], bool)

    def test_stable_carry_bool(self):
        self.assertIsInstance(self.r["stable_carry"], bool)


# ── realized carry / overstatement correctness ────────────────────────────────

class TestRealizedAndOverstatement(unittest.TestCase):
    def test_realized_is_mean(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, 12.0, 14.0]))
        self.assertAlmostEqual(r["realized_blended_apr_pct"], 12.0)

    def test_realized_mean_signed(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 funding_rate_samples=[20.0, -10.0]))
        self.assertAlmostEqual(r["realized_blended_apr_pct"], 5.0)

    def test_realized_negative_mean(self):
        r = A().analyze(make_pos(headline_apr_pct=5.0,
                                 funding_rate_samples=[-10.0, -20.0]))
        self.assertAlmostEqual(r["realized_blended_apr_pct"], -15.0)

    def test_overstatement_headline_minus_realized(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[6.0, 6.0]))
        self.assertAlmostEqual(
            r["overstatement_pct"],
            r["headline_apr_pct"] - r["realized_blended_apr_pct"])

    def test_overstatement_value(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 funding_rate_samples=[10.0, 10.0]))
        self.assertAlmostEqual(r["overstatement_pct"], 10.0)

    def test_overstatement_negative_when_realized_higher(self):
        r = A().analyze(make_pos(headline_apr_pct=8.0,
                                 funding_rate_samples=[12.0, 12.0]))
        self.assertAlmostEqual(r["overstatement_pct"], -4.0)

    def test_realization_ratio(self):
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 funding_rate_samples=[10.0, 10.0]))
        self.assertAlmostEqual(r["realization_ratio"], 0.5)

    def test_realization_ratio_one(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 funding_rate_samples=[10.0, 10.0]))
        self.assertAlmostEqual(r["realization_ratio"], 1.0)

    def test_realization_ratio_negative(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 funding_rate_samples=[-5.0, -5.0]))
        self.assertAlmostEqual(r["realization_ratio"], -0.5)

    def test_realization_ratio_above_one(self):
        r = A().analyze(make_pos(headline_apr_pct=8.0,
                                 funding_rate_samples=[12.0, 12.0]))
        self.assertAlmostEqual(r["realization_ratio"], 1.5)

    def test_min_max_funding(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[5.0, -3.0, 18.0]))
        self.assertAlmostEqual(r["min_funding_apr"], -3.0)
        self.assertAlmostEqual(r["max_funding_apr"], 18.0)

    def test_avg_negative(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, -4.0, -8.0]))
        self.assertAlmostEqual(r["avg_negative_funding_apr"], -6.0)

    def test_avg_positive(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, 20.0, -4.0]))
        self.assertAlmostEqual(r["avg_positive_funding_apr"], 15.0)

    def test_avg_negative_zero_when_none(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, 12.0]))
        self.assertAlmostEqual(r["avg_negative_funding_apr"], 0.0)

    def test_avg_positive_zero_when_none(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[-10.0, -12.0]))
        self.assertAlmostEqual(r["avg_positive_funding_apr"], 0.0)

    def test_sample_count(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[1.0, 2.0, 3.0, 4.0]))
        self.assertEqual(r["sample_count"], 4)

    def test_negative_fraction(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, -1.0, -2.0, 8.0]))
        self.assertAlmostEqual(r["negative_funding_fraction"], 0.5)

    def test_positive_fraction(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, -1.0, -2.0, 8.0]))
        self.assertAlmostEqual(r["positive_funding_fraction"], 0.5)

    def test_fractions_with_zero_sample(self):
        # zero is neither positive nor negative
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, 0.0, -5.0, 8.0]))
        self.assertAlmostEqual(r["negative_funding_fraction"], 0.25)
        self.assertAlmostEqual(r["positive_funding_fraction"], 0.5)

    def test_headline_passthrough(self):
        r = A().analyze(make_pos(headline_apr_pct=13.0))
        self.assertAlmostEqual(r["headline_apr_pct"], 13.0)

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(headline_apr_pct=13.3333,
                                 funding_rate_samples=[7.7777, 3.3333, 1.1]))
        for k in ("headline_apr_pct", "realized_blended_apr_pct",
                  "overstatement_pct", "negative_funding_fraction",
                  "min_funding_apr", "max_funding_apr"):
            self.assertEqual(r[k], round(r[k], 4))

    def test_score_rounded_2(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[7.3, 5.1, 9.9]))
        self.assertEqual(r["score"], round(r["score"], 2))


# ── sign flips ────────────────────────────────────────────────────────────────

class TestSignFlips(unittest.TestCase):
    def test_no_flips_all_positive(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[1.0, 2.0, 3.0]))
        self.assertEqual(r["sign_flips"], 0)

    def test_no_flips_all_negative(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[-1.0, -2.0, -3.0]))
        self.assertEqual(r["sign_flips"], 0)

    def test_one_flip(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[5.0, -5.0]))
        self.assertEqual(r["sign_flips"], 1)

    def test_alternating_flips(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[5.0, -5.0, 5.0, -5.0]))
        self.assertEqual(r["sign_flips"], 3)

    def test_zero_treated_as_non_negative(self):
        # 0 is non-negative, so 5,0 → no flip; 0,-5 → flip
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[5.0, 0.0, -5.0]))
        self.assertEqual(r["sign_flips"], 1)

    def test_zero_between_positives_no_flip(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[5.0, 0.0, 8.0]))
        self.assertEqual(r["sign_flips"], 0)

    def test_two_flips(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, -3.0, 7.0]))
        self.assertEqual(r["sign_flips"], 2)


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_persistent_positive_no_negatives(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[11.0, 12.0, 13.0]))
        self.assertEqual(r["classification"], "PERSISTENT_POSITIVE")

    def test_persistent_boundary(self):
        # neg_frac exactly 0.05: 1 negative of 20
        samples = [10.0] * 19 + [-1.0]
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=samples))
        self.assertAlmostEqual(r["negative_funding_fraction"], 0.05)
        self.assertEqual(r["classification"], "PERSISTENT_POSITIVE")

    def test_mostly_positive(self):
        # neg_frac 1/6 ≈ 0.167
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[
                                     10.0, 9.0, 11.0, -2.0, 10.0, 10.0]))
        self.assertEqual(r["classification"], "MOSTLY_POSITIVE")

    def test_mostly_boundary(self):
        # neg_frac exactly 0.20: 1 of 5
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[
                                     10.0, 10.0, 10.0, 10.0, -2.0]))
        self.assertAlmostEqual(r["negative_funding_fraction"], 0.2)
        self.assertEqual(r["classification"], "MOSTLY_POSITIVE")

    def test_regime_mixed(self):
        # neg_frac 0.40: 2 of 5
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[
                                     10.0, 10.0, 10.0, -2.0, -3.0]))
        self.assertAlmostEqual(r["negative_funding_fraction"], 0.4)
        self.assertEqual(r["classification"], "REGIME_MIXED")

    def test_regime_mixed_boundary(self):
        # neg_frac exactly 0.45: 9 of 20
        samples = [10.0] * 11 + [-1.0] * 9
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=samples))
        self.assertAlmostEqual(r["negative_funding_fraction"], 0.45)
        self.assertEqual(r["classification"], "REGIME_MIXED")

    def test_funding_unreliable(self):
        # neg_frac 0.50
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, -2.0, 10.0, -3.0]))
        self.assertAlmostEqual(r["negative_funding_fraction"], 0.5)
        self.assertEqual(r["classification"], "FUNDING_UNRELIABLE")

    def test_funding_unreliable_just_above_mixed(self):
        # neg_frac 0.50 just above 0.45
        samples = [10.0] * 10 + [-1.0] * 10
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=samples))
        self.assertEqual(r["classification"], "FUNDING_UNRELIABLE")

    def test_funding_unreliable_all_negative(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[-5.0, -6.0, -7.0]))
        self.assertEqual(r["classification"], "FUNDING_UNRELIABLE")

    def test_classification_known_values(self):
        for samples in [
            [10.0, 11.0],
            [10.0, 10.0, 10.0, 10.0, -2.0],
            [10.0, 10.0, 10.0, -2.0, -3.0],
            [10.0, -2.0, -3.0, -4.0],
        ]:
            r = A().analyze(make_pos(headline_apr_pct=12.0,
                                     funding_rate_samples=samples))
            self.assertIn(r["classification"], {
                "PERSISTENT_POSITIVE", "MOSTLY_POSITIVE", "REGIME_MIXED",
                "FUNDING_UNRELIABLE",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_trust_persistent(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[11.0, 12.0, 13.0]))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_discount_slightly_mostly(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[
                                     10.0, 9.0, 11.0, -2.0, 10.0, 10.0]))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE_SLIGHTLY")

    def test_discount_mixed(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[
                                     10.0, 10.0, 10.0, -2.0, -3.0]))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE")

    def test_avoid_unreliable(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, -2.0, 10.0, -3.0]))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_avoid_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_persistent_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[11.0, 12.0, 13.0]))
        self.assertIn("PERSISTENT_POSITIVE", r["flags"])

    def test_mostly_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[
                                     10.0, 9.0, 11.0, -2.0, 10.0, 10.0]))
        self.assertIn("MOSTLY_POSITIVE", r["flags"])

    def test_mixed_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[
                                     10.0, 10.0, 10.0, -2.0, -3.0]))
        self.assertIn("REGIME_MIXED", r["flags"])

    def test_unreliable_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, -2.0, 10.0, -3.0]))
        self.assertIn("FUNDING_UNRELIABLE", r["flags"])

    def test_funding_flips_negative_flag_true(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, -2.0, 10.0]))
        self.assertIn("FUNDING_FLIPS_NEGATIVE", r["flags"])
        self.assertTrue(r["funding_flips_negative"])

    def test_funding_flips_negative_flag_false(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, 11.0, 12.0]))
        self.assertNotIn("FUNDING_FLIPS_NEGATIVE", r["flags"])
        self.assertFalse(r["funding_flips_negative"])

    def test_deep_negative_flag_true(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, -15.0]))
        self.assertIn("DEEP_NEGATIVE_REGIME", r["flags"])
        self.assertTrue(r["deep_negative"])

    def test_deep_negative_boundary(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[
                                     10.0, DEEP_NEGATIVE_APR]))
        self.assertTrue(r["deep_negative"])

    def test_deep_negative_flag_false(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, -5.0]))
        self.assertNotIn("DEEP_NEGATIVE_REGIME", r["flags"])
        self.assertFalse(r["deep_negative"])

    def test_headline_from_spike_true(self):
        # realized blended 8, headline 12 → 12 >= 1.25*8=10 → spike
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[8.0, 8.0]))
        self.assertIn("HEADLINE_FROM_SPIKE", r["flags"])
        self.assertTrue(r["headline_from_spike"])

    def test_headline_from_spike_boundary(self):
        # realized 8, headline exactly 10 = 1.25*8
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 funding_rate_samples=[8.0, 8.0]))
        self.assertTrue(r["headline_from_spike"])

    def test_headline_from_spike_false(self):
        # realized 10, headline 12 → 12 < 1.25*10=12.5 → not spike
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, 10.0]))
        self.assertNotIn("HEADLINE_FROM_SPIKE", r["flags"])
        self.assertFalse(r["headline_from_spike"])

    def test_headline_from_spike_false_negative_realized(self):
        # realized negative → spike requires realized>0 → false
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[-5.0, -6.0]))
        self.assertFalse(r["headline_from_spike"])

    def test_realized_negative_carry_true(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[-5.0, -6.0]))
        self.assertIn("REALIZED_NEGATIVE_CARRY", r["flags"])
        self.assertTrue(r["realized_negative_carry"])

    def test_realized_negative_carry_false(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, 11.0]))
        self.assertNotIn("REALIZED_NEGATIVE_CARRY", r["flags"])
        self.assertFalse(r["realized_negative_carry"])

    def test_stable_carry_true(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[11.0, 12.0, 13.0]))
        self.assertIn("STABLE_CARRY", r["flags"])
        self.assertTrue(r["stable_carry"])

    def test_stable_carry_false_with_negative(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[11.0, -2.0]))
        self.assertNotIn("STABLE_CARRY", r["flags"])
        self.assertFalse(r["stable_carry"])

    def test_stable_carry_false_with_flips(self):
        # all-negative has 0 flips but len(neg)>0 → not stable
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[-1.0, -2.0]))
        self.assertFalse(r["stable_carry"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_one_classification_flag_only(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[
                                     10.0, 10.0, 10.0, -2.0, -3.0]))
        class_flags = {"PERSISTENT_POSITIVE", "MOSTLY_POSITIVE",
                       "REGIME_MIXED", "FUNDING_UNRELIABLE"}
        present = [f for f in r["flags"] if f in class_flags]
        self.assertEqual(len(present), 1)


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_headline_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_headline_negative(self):
        r = A().analyze(make_pos(headline_apr_pct=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_headline_missing(self):
        r = A().analyze({"vault": "V",
                         "funding_rate_samples": [10.0, 11.0]})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_non_finite_headline_inf(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("inf"),
                         "funding_rate_samples": [10.0, 11.0]})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("nan"),
                         "funding_rate_samples": [10.0, 11.0]})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_one_sample(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_empty_samples(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_samples(self):
        r = A().analyze({"vault": "V", "headline_apr_pct": 12.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_non_finite_samples(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[
                                     float("nan"), float("inf")]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_non_numeric_samples(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=["a", None, {}]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_one_valid_one_nan(self):
        # only one valid → still insufficient
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, float("nan")]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_insufficient_none_fields(self):
        r = A().analyze({})
        self.assertIsNone(r["realized_blended_apr_pct"])
        self.assertIsNone(r["realization_ratio"])
        self.assertIsNone(r["negative_funding_fraction"])
        self.assertIsNone(r["positive_funding_fraction"])
        self.assertIsNone(r["avg_negative_funding_apr"])
        self.assertIsNone(r["avg_positive_funding_apr"])
        self.assertIsNone(r["min_funding_apr"])
        self.assertIsNone(r["max_funding_apr"])
        self.assertIsNone(r["sign_flips"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        self.assertAlmostEqual(r["headline_apr_pct"], 0.0)
        self.assertAlmostEqual(r["overstatement_pct"], 0.0)
        self.assertAlmostEqual(r["score"], 0.0)

    def test_insufficient_sample_count_zero(self):
        r = A().analyze({})
        self.assertEqual(r["sample_count"], 0)

    def test_insufficient_booleans_false(self):
        r = A().analyze({})
        self.assertFalse(r["funding_flips_negative"])
        self.assertFalse(r["deep_negative"])
        self.assertFalse(r["headline_from_spike"])
        self.assertFalse(r["realized_negative_carry"])
        self.assertFalse(r["stable_carry"])

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_insufficient_no_inf_nan(self):
        finite_check(self, A().analyze({}))

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_insufficient_has_all_keys(self):
        r = A().analyze({})
        valid = A().analyze(make_pos())
        self.assertEqual(set(r.keys()), set(valid.keys()))

    def test_valid_not_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, 11.0]))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── non-finite sample filtering ───────────────────────────────────────────────

class TestSampleFiltering(unittest.TestCase):
    def test_nan_filtered_rest_used(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[
                                     10.0, float("nan"), 14.0]))
        self.assertEqual(r["sample_count"], 2)
        self.assertAlmostEqual(r["realized_blended_apr_pct"], 12.0)

    def test_inf_filtered(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[
                                     10.0, float("inf"), 14.0]))
        self.assertEqual(r["sample_count"], 2)

    def test_neg_inf_filtered(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[
                                     10.0, float("-inf"), 14.0]))
        self.assertEqual(r["sample_count"], 2)

    def test_non_numeric_filtered(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[
                                     10.0, "bad", None, 14.0]))
        self.assertEqual(r["sample_count"], 2)
        self.assertAlmostEqual(r["realized_blended_apr_pct"], 12.0)

    def test_string_number_coerced(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=["10.0", "14.0"]))
        self.assertEqual(r["sample_count"], 2)
        self.assertAlmostEqual(r["realized_blended_apr_pct"], 12.0)

    def test_dict_sample_filtered(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[10.0, {}, 14.0]))
        self.assertEqual(r["sample_count"], 2)

    def test_filtered_all_finite_output(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[
                                     10.0, float("nan"), -3.0, 14.0]))
        finite_check(self, r)


# ── scoring monotonicity & bounds ─────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_all_positive_aligned_high_score(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[12.0, 12.0, 12.0]))
        self.assertAlmostEqual(r["score"], 100.0)

    def test_all_positive_grade_a(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[12.0, 12.0]))
        self.assertEqual(r["grade"], "A")

    def test_more_negatives_lower_score(self):
        few = A().analyze(make_pos(headline_apr_pct=12.0,
                                   funding_rate_samples=[
                                       10.0, 10.0, 10.0, -2.0]))
        many = A().analyze(make_pos(headline_apr_pct=12.0,
                                    funding_rate_samples=[
                                        10.0, -2.0, -3.0, -4.0]))
        self.assertGreater(few["score"], many["score"])

    def test_realized_closer_to_headline_higher_score(self):
        # same neg_frac (0), realized closer to headline scores higher
        close = A().analyze(make_pos(headline_apr_pct=12.0,
                                     funding_rate_samples=[12.0, 12.0]))
        far = A().analyze(make_pos(headline_apr_pct=12.0,
                                   funding_rate_samples=[4.0, 4.0]))
        self.assertGreater(close["score"], far["score"])

    def test_negative_carry_low_score(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[-5.0, -6.0, -7.0]))
        self.assertLess(r["score"], 55.0)

    def test_score_in_range_many(self):
        for samples in [
            [12.0, 12.0],
            [10.0, 10.0, -2.0],
            [10.0, -2.0, -3.0],
            [-5.0, -6.0],
            [25.0, -15.0, 30.0, -20.0],
        ]:
            r = A().analyze(make_pos(headline_apr_pct=12.0,
                                     funding_rate_samples=samples))
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for samples in [
            [12.0, 12.0],
            [10.0, -2.0, -3.0, -4.0],
        ]:
            r = A().analyze(make_pos(headline_apr_pct=12.0,
                                     funding_rate_samples=samples))
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_monotonic_decreasing_neg_frac(self):
        scores = []
        base = [10.0] * 10
        for k in range(0, 6):
            samples = [10.0] * (10 - k) + [-5.0] * k
            r = A().analyze(make_pos(headline_apr_pct=12.0,
                                     funding_rate_samples=samples))
            scores.append(r["score"])
        for a, b in zip(scores, scores[1:]):
            self.assertGreaterEqual(a, b)

    def test_score_floor_zero_extreme(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 funding_rate_samples=[-1e9, -1e9]))
        self.assertGreaterEqual(r["score"], 0.0)
        self.assertLessEqual(r["score"], 100.0)

    def test_honesty_clamped_above_headline(self):
        # realized > headline → honesty clamps to 1, reliability 1 → 100
        r = A().analyze(make_pos(headline_apr_pct=8.0,
                                 funding_rate_samples=[20.0, 20.0]))
        self.assertAlmostEqual(r["score"], 100.0)

    def test_unreliable_low_score(self):
        r = A().analyze(make_pos(headline_apr_pct=25.0,
                                 funding_rate_samples=[
                                     25.0, -15.0, 30.0, -20.0]))
        self.assertLess(r["score"], 55.0)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Honest", headline_apr_pct=12.0,
                     funding_rate_samples=[12.0, 12.0, 12.0]),
            make_pos(vault="Bad", headline_apr_pct=25.0,
                     funding_rate_samples=[25.0, -15.0, 30.0, -20.0]),
            make_pos(vault="Mid", headline_apr_pct=10.0,
                     funding_rate_samples=[
                         10.0, 9.0, 11.0, -2.0, 10.0, 10.0]),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_honest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_honest_vault"]],
                         max(scores.values()))

    def test_least_honest_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["least_honest_vault"]],
                         min(scores.values()))

    def test_most_honest_is_honest(self):
        self.assertEqual(self.res["aggregate"]["most_honest_vault"], "Honest")

    def test_least_honest_is_bad(self):
        self.assertEqual(self.res["aggregate"]["least_honest_vault"], "Bad")

    def test_unreliable_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["unreliable_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_honest_vault"])
        self.assertIsNone(res["aggregate"]["least_honest_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_empty_unreliable_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["unreliable_count"], 0)

    def test_empty_avg_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=0.0),
            make_pos(headline_apr_pct=0.0),
        ])
        self.assertIsNone(res["aggregate"]["most_honest_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["unreliable_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_honest_vault"], "Solo")
        self.assertEqual(res["aggregate"]["least_honest_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", headline_apr_pct=12.0,
                     funding_rate_samples=[12.0, 12.0]),
            make_pos(vault="Ins", headline_apr_pct=0.0),
        ])
        scored = [p["score"] for p in res["positions"]
                  if p["classification"] != "INSUFFICIENT_DATA"]
        self.assertAlmostEqual(res["aggregate"]["avg_score"],
                               round(sum(scored) / len(scored), 2))

    def test_unreliable_count_multiple(self):
        res = A().analyze_portfolio([
            make_pos(vault="U1", headline_apr_pct=12.0,
                     funding_rate_samples=[10.0, -2.0, -3.0, -4.0]),
            make_pos(vault="U2", headline_apr_pct=12.0,
                     funding_rate_samples=[10.0, -2.0, 10.0, -3.0]),
            make_pos(vault="Honest", headline_apr_pct=12.0,
                     funding_rate_samples=[12.0, 12.0]),
        ])
        self.assertEqual(res["aggregate"]["unreliable_count"], 2)

    def test_aggregate_ignores_insufficient_for_ranking(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", headline_apr_pct=12.0,
                     funding_rate_samples=[12.0, 12.0]),
            make_pos(vault="Ins", headline_apr_pct=0.0),
        ])
        self.assertEqual(res["aggregate"]["most_honest_vault"], "Good")
        self.assertEqual(res["aggregate"]["least_honest_vault"], "Good")

    def test_portfolio_all_finite(self):
        for p in self.res["positions"]:
            finite_check(self, p)


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
                make_pos(vault="big", headline_apr_pct=1e9,
                         funding_rate_samples=[1e9, -1e9]),
                make_pos(vault="ins", headline_apr_pct=0.0),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            json.loads(raw)

    def test_log_none_fields_serialize_null(self):
        res = A().analyze(make_pos(headline_apr_pct=0.0))
        raw = json.dumps(res)
        self.assertIn("null", raw)
        json.loads(raw)

    def test_log_snapshot_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            snap = data[0]["snapshots"][0]
            for k in ("token", "classification", "score", "recommendation",
                      "flags"):
                self.assertIn(k, snap)

    def test_log_aggregate_present(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIn("aggregate", data[0])
            self.assertIn("ts", data[0])


# ── demo / CLI ────────────────────────────────────────────────────────────────

class TestDemo(unittest.TestCase):
    def test_demo_positions_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

    def test_demo_portfolio_runs(self):
        res = A().analyze_portfolio(_demo_positions())
        self.assertEqual(len(res["positions"]), len(_demo_positions()))
        json.dumps(res)

    def test_demo_has_persistent(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("PERSISTENT_POSITIVE", classes)

    def test_demo_has_unreliable(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("FUNDING_UNRELIABLE", classes)

    def test_demo_has_insufficient(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_all_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)

    def test_demo_volatile_unreliable(self):
        res = A().analyze_portfolio(_demo_positions())
        by = {p["token"]: p for p in res["positions"]}
        self.assertEqual(by["SOL-Basis-Volatile"]["classification"],
                         "FUNDING_UNRELIABLE")

    def test_demo_stable_persistent(self):
        res = A().analyze_portfolio(_demo_positions())
        by = {p["token"]: p for p in res["positions"]}
        self.assertEqual(by["ETH-Basis-Stable"]["classification"],
                         "PERSISTENT_POSITIVE")


if __name__ == "__main__":
    unittest.main()
