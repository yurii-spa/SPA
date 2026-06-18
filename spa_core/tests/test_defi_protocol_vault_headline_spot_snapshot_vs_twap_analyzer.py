"""
Tests for MP-1193: DeFiProtocolVaultHeadlineSpotSnapshotVsTWAPAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_headline_spot_snapshot_vs_twap_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_headline_spot_snapshot_vs_twap_analyzer import (  # noqa: E501
    DeFiProtocolVaultHeadlineSpotSnapshotVsTWAPAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    REP_TOLERANCE_PCT,
    PREMIUM_SCORE_CEILING_PCT,
    MINOR_PREMIUM_PCT,
    MODERATE_PREMIUM_PCT,
    SPOT_AT_PEAK_FRACTION,
    MIN_SAMPLES,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=10.0,
    rate_samples_pct=None,
    twap_apr_pct=9.0,
    window_days=30.0,
):
    pos = {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "window_days": window_days,
    }
    if rate_samples_pct is not None:
        pos["rate_samples_pct"] = rate_samples_pct
    if twap_apr_pct is not None:
        pos["twap_apr_pct"] = twap_apr_pct
    return pos


def A():
    return DeFiProtocolVaultHeadlineSpotSnapshotVsTWAPAnalyzer()


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
        self.assertEqual(_f(None, 3.0), 3.0)

    def test_f_float_passthrough(self):
        self.assertEqual(_f(4.25), 4.25)

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

    def test_mean_negative(self):
        self.assertAlmostEqual(_mean([-2.0, 2.0]), 0.0)

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
        self.assertGreater(REP_TOLERANCE_PCT, 0)
        self.assertGreater(PREMIUM_SCORE_CEILING_PCT, 0)
        self.assertLess(MINOR_PREMIUM_PCT, MODERATE_PREMIUM_PCT)
        self.assertGreater(SPOT_AT_PEAK_FRACTION, 0.0)
        self.assertLessEqual(SPOT_AT_PEAK_FRACTION, 1.0)
        self.assertGreaterEqual(MIN_SAMPLES, 2)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "headline_apr_pct", "twap_apr_pct", "twap_source",
            "window_days", "premium_pct", "premium_ratio",
            "representativeness_ratio", "representativeness_pct",
            "peak_sample_pct", "trough_sample_pct", "sample_range_pct",
            "sample_count", "spot_at_peak", "overstated", "score",
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
        r = A().analyze({"token": "AltKey", "headline_apr_pct": 10.0,
                         "twap_apr_pct": 9.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "headline_apr_pct": 10.0, "twap_apr_pct": 9.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"headline_apr_pct": 10.0, "twap_apr_pct": 9.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
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
            "UNDERSTATED", "REPRESENTATIVE", "MINOR_PREMIUM",
            "MODERATE_PREMIUM", "SEVERE_PREMIUM", "INSUFFICIENT_DATA",
        })

    def test_overstated_is_bool(self):
        self.assertIsInstance(self.r["overstated"], bool)

    def test_spot_at_peak_is_bool(self):
        self.assertIsInstance(self.r["spot_at_peak"], bool)

    def test_sample_count_is_int(self):
        self.assertIsInstance(self.r["sample_count"], int)

    def test_twap_source_string(self):
        self.assertIsInstance(self.r["twap_source"], str)


# ── twap source / precedence ──────────────────────────────────────────────────

class TestTwapSource(unittest.TestCase):
    def test_override_source(self):
        r = A().analyze(make_pos(twap_apr_pct=9.0))
        self.assertEqual(r["twap_source"], "override")

    def test_override_value_used(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=7.0))
        self.assertAlmostEqual(r["twap_apr_pct"], 7.0)

    def test_samples_source(self):
        r = A().analyze(make_pos(rate_samples_pct=[8.0, 10.0],
                                 twap_apr_pct=None))
        self.assertEqual(r["twap_source"], "samples")

    def test_samples_mean_used(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[8.0, 12.0],
                                 twap_apr_pct=None))
        self.assertAlmostEqual(r["twap_apr_pct"], 10.0)

    def test_override_wins_over_samples(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[1.0, 1.0],
                                 twap_apr_pct=8.0))
        self.assertEqual(r["twap_source"], "override")
        self.assertAlmostEqual(r["twap_apr_pct"], 8.0)

    def test_non_finite_override_falls_back_to_samples(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[8.0, 10.0],
                                 twap_apr_pct=float("inf")))
        self.assertEqual(r["twap_source"], "samples")

    def test_nan_override_falls_back_to_samples(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[8.0, 10.0],
                                 twap_apr_pct=float("nan")))
        self.assertEqual(r["twap_source"], "samples")

    def test_samples_filter_non_finite(self):
        # inf/nan filtered; two finite remain → samples mean
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[8.0, float("inf"),
                                                   12.0, float("nan")],
                                 twap_apr_pct=None))
        self.assertEqual(r["twap_source"], "samples")
        self.assertAlmostEqual(r["twap_apr_pct"], 10.0)
        self.assertEqual(r["sample_count"], 2)

    def test_sample_count_counts_finite_only(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[8.0, 9.0, 10.0],
                                 twap_apr_pct=5.0))
        self.assertEqual(r["sample_count"], 3)

    def test_override_with_no_samples_zero_count(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=9.0))
        self.assertEqual(r["sample_count"], 0)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_premium_pct(self):
        # spot 10 - twap 8 = 2
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=8.0))
        self.assertAlmostEqual(r["premium_pct"], 2.0)

    def test_premium_pct_negative_understated(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=14.0))
        self.assertAlmostEqual(r["premium_pct"], -4.0)

    def test_premium_ratio(self):
        # spot/twap = 10/8 = 1.25
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=8.0))
        self.assertAlmostEqual(r["premium_ratio"], 1.25)

    def test_representativeness_ratio(self):
        # twap/spot = 8/10 = 0.8
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=8.0))
        self.assertAlmostEqual(r["representativeness_ratio"], 0.8)

    def test_representativeness_pct(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=8.0))
        self.assertAlmostEqual(r["representativeness_pct"], 80.0)

    def test_representativeness_ratio_clamped_nonnegative(self):
        # negative twap → ratio negative → clamped to 0
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=-5.0))
        self.assertAlmostEqual(r["representativeness_ratio"], 0.0)
        self.assertAlmostEqual(r["representativeness_pct"], 0.0)

    def test_overstated_true(self):
        # premium 2 > 1.0
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=8.0))
        self.assertTrue(r["overstated"])

    def test_overstated_false(self):
        # premium 0.5 <= 1.0
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=9.5))
        self.assertFalse(r["overstated"])

    def test_passthrough_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, twap_apr_pct=10.0))
        self.assertAlmostEqual(r["headline_apr_pct"], 12.0)

    def test_window_days_passthrough(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=9.0,
                                 window_days=45.0))
        self.assertAlmostEqual(r["window_days"], 45.0)

    def test_window_days_negative_clamped(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=9.0,
                                 window_days=-30.0))
        self.assertAlmostEqual(r["window_days"], 0.0)

    def test_window_days_default(self):
        r = A().analyze({"vault": "V", "headline_apr_pct": 10.0,
                         "twap_apr_pct": 9.0})
        self.assertAlmostEqual(r["window_days"], 30.0)

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=8.3333))
        for k in ("headline_apr_pct", "twap_apr_pct", "premium_pct"):
            self.assertEqual(r[k], round(r[k], 4))

    def test_peak_trough_range(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[8.0, 12.0, 9.0],
                                 twap_apr_pct=None))
        self.assertAlmostEqual(r["peak_sample_pct"], 12.0)
        self.assertAlmostEqual(r["trough_sample_pct"], 8.0)
        self.assertAlmostEqual(r["sample_range_pct"], 4.0)

    def test_peak_trough_none_without_samples(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=9.0))
        self.assertIsNone(r["peak_sample_pct"])
        self.assertIsNone(r["trough_sample_pct"])
        self.assertIsNone(r["sample_range_pct"])

    def test_peak_trough_single_sample_with_override(self):
        # one sample (below MIN for twap) but override supplies twap;
        # peak/trough still computed from the single finite sample.
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[7.5],
                                 twap_apr_pct=9.0))
        self.assertAlmostEqual(r["peak_sample_pct"], 7.5)
        self.assertAlmostEqual(r["trough_sample_pct"], 7.5)
        self.assertAlmostEqual(r["sample_range_pct"], 0.0)

    def test_premium_ratio_none_on_zero_twap(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=0.0,
                                 rate_samples_pct=None))
        # twap 0 → insufficient (twap_used None? No: override 0 is finite)
        # 0 is finite so twap_used=0; premium_ratio safe_div(spot,0)=None
        self.assertIsNone(r["premium_ratio"])

    def test_representativeness_zero_on_zero_twap(self):
        # twap/spot = 0/10 = 0.0 (denominator spot>0 so not sentinel)
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=0.0))
        self.assertAlmostEqual(r["representativeness_ratio"], 0.0)
        self.assertAlmostEqual(r["representativeness_pct"], 0.0)


# ── spot at peak ──────────────────────────────────────────────────────────────

class TestSpotAtPeak(unittest.TestCase):
    def test_spot_at_peak_true(self):
        # spot 20 >= peak 20.4 * 0.98 = 19.992
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 rate_samples_pct=[8.0, 9.0, 10.0, 11.0, 20.4],
                                 twap_apr_pct=None))
        self.assertTrue(r["spot_at_peak"])

    def test_spot_at_peak_false_below_fraction(self):
        # spot 10 vs peak 20 → not at peak
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[5.0, 20.0],
                                 twap_apr_pct=None))
        self.assertFalse(r["spot_at_peak"])

    def test_spot_at_peak_false_without_samples(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=9.0))
        self.assertFalse(r["spot_at_peak"])

    def test_spot_at_peak_boundary(self):
        # peak 10, spot 9.8 = 10*0.98 → at peak (>=)
        r = A().analyze(make_pos(headline_apr_pct=9.8,
                                 rate_samples_pct=[10.0, 5.0],
                                 twap_apr_pct=None))
        self.assertTrue(r["spot_at_peak"])

    def test_spot_at_peak_just_below_boundary(self):
        r = A().analyze(make_pos(headline_apr_pct=9.7,
                                 rate_samples_pct=[10.0, 5.0],
                                 twap_apr_pct=None))
        self.assertFalse(r["spot_at_peak"])

    def test_spot_at_peak_false_negative_peak(self):
        # peak <= 0 → not at peak
        r = A().analyze(make_pos(headline_apr_pct=5.0,
                                 rate_samples_pct=[-1.0, -2.0],
                                 twap_apr_pct=8.0))
        self.assertFalse(r["spot_at_peak"])


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_understated(self):
        # premium -4 < -1
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=14.0))
        self.assertEqual(r["classification"], "UNDERSTATED")

    def test_understated_boundary(self):
        # premium -1.01 < -1
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=11.01))
        self.assertEqual(r["classification"], "UNDERSTATED")

    def test_representative(self):
        # premium 0.5, |premium| <= 1
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=9.5))
        self.assertEqual(r["classification"], "REPRESENTATIVE")

    def test_representative_boundary_positive(self):
        # premium exactly 1
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=9.0))
        self.assertEqual(r["classification"], "REPRESENTATIVE")

    def test_representative_boundary_negative(self):
        # premium exactly -1
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=11.0))
        self.assertEqual(r["classification"], "REPRESENTATIVE")

    def test_minor_premium(self):
        # premium 2.5, <= 3
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=7.5))
        self.assertEqual(r["classification"], "MINOR_PREMIUM")

    def test_minor_premium_boundary(self):
        # premium exactly 3
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=7.0))
        self.assertEqual(r["classification"], "MINOR_PREMIUM")

    def test_moderate_premium(self):
        # premium 5, <= 8
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=5.0))
        self.assertEqual(r["classification"], "MODERATE_PREMIUM")

    def test_moderate_premium_boundary(self):
        # premium exactly 8
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=2.0))
        self.assertEqual(r["classification"], "MODERATE_PREMIUM")

    def test_severe_premium(self):
        # premium 9 > 8
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=1.0))
        self.assertEqual(r["classification"], "SEVERE_PREMIUM")

    def test_severe_premium_just_above(self):
        # premium 8.01 > 8
        r = A().analyze(make_pos(headline_apr_pct=10.01, twap_apr_pct=2.0))
        self.assertEqual(r["classification"], "SEVERE_PREMIUM")

    def test_classification_known_value(self):
        for pos in [make_pos(twap_apr_pct=14.0),
                    make_pos(twap_apr_pct=9.5),
                    make_pos(twap_apr_pct=7.5),
                    make_pos(twap_apr_pct=5.0),
                    make_pos(twap_apr_pct=1.0),
                    make_pos(headline_apr_pct=0.0, twap_apr_pct=None,
                             rate_samples_pct=None)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "UNDERSTATED", "REPRESENTATIVE", "MINOR_PREMIUM",
                "MODERATE_PREMIUM", "SEVERE_PREMIUM", "INSUFFICIENT_DATA",
            })

    def test_classification_from_samples(self):
        # spot 20, samples mean 11.68 → premium 8.32 → severe
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 rate_samples_pct=[8.0, 9.0, 10.0, 11.0, 20.4],
                                 twap_apr_pct=None))
        self.assertEqual(r["classification"], "SEVERE_PREMIUM")


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_trust_understated(self):
        r = A().analyze(make_pos(twap_apr_pct=14.0))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_trust_representative(self):
        r = A().analyze(make_pos(twap_apr_pct=9.5))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_discount_slightly_minor(self):
        r = A().analyze(make_pos(twap_apr_pct=7.5))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE_SLIGHTLY")

    def test_discount_moderate(self):
        r = A().analyze(make_pos(twap_apr_pct=5.0))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE")

    def test_avoid_severe(self):
        r = A().analyze(make_pos(twap_apr_pct=1.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_insufficient_rec(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, twap_apr_pct=None,
                                 rate_samples_pct=None))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_understated_flag(self):
        r = A().analyze(make_pos(twap_apr_pct=14.0))
        self.assertIn("UNDERSTATED", r["flags"])

    def test_representative_flag(self):
        r = A().analyze(make_pos(twap_apr_pct=9.5))
        self.assertIn("REPRESENTATIVE", r["flags"])

    def test_minor_premium_flag(self):
        r = A().analyze(make_pos(twap_apr_pct=7.5))
        self.assertIn("MINOR_PREMIUM", r["flags"])

    def test_moderate_premium_flag(self):
        r = A().analyze(make_pos(twap_apr_pct=5.0))
        self.assertIn("MODERATE_PREMIUM", r["flags"])

    def test_severe_premium_flag(self):
        r = A().analyze(make_pos(twap_apr_pct=1.0))
        self.assertIn("SEVERE_PREMIUM", r["flags"])

    def test_spot_overstates_twap_flag(self):
        # premium 2 > 1.0
        r = A().analyze(make_pos(twap_apr_pct=8.0))
        self.assertIn("SPOT_OVERSTATES_TWAP", r["flags"])

    def test_spot_overstates_twap_flag_absent(self):
        r = A().analyze(make_pos(twap_apr_pct=9.5))
        self.assertNotIn("SPOT_OVERSTATES_TWAP", r["flags"])

    def test_spot_snapshot_at_peak_flag(self):
        # spot 20 at peak 20.4 + overstated
        r = A().analyze(make_pos(headline_apr_pct=20.0,
                                 rate_samples_pct=[8.0, 9.0, 10.0, 11.0, 20.4],
                                 twap_apr_pct=None))
        self.assertIn("SPOT_SNAPSHOT_AT_PEAK", r["flags"])

    def test_spot_snapshot_at_peak_absent_when_not_overstated(self):
        # spot at peak but premium small → no peak flag
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[10.0, 9.8],
                                 twap_apr_pct=None))
        self.assertNotIn("SPOT_SNAPSHOT_AT_PEAK", r["flags"])

    def test_negative_twap_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=-3.0))
        self.assertIn("NEGATIVE_TWAP", r["flags"])

    def test_negative_twap_flag_absent(self):
        r = A().analyze(make_pos(twap_apr_pct=8.0))
        self.assertNotIn("NEGATIVE_TWAP", r["flags"])

    def test_sparse_samples_flag(self):
        # 2 samples, twap derived from samples (not override) → 0<2<3 → sparse
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[8.0, 10.0],
                                 twap_apr_pct=None))
        self.assertIn("SPARSE_SAMPLES", r["flags"])

    def test_sparse_samples_flag_one_sample_override_not_flagged(self):
        # 1 sample but override present → override suppresses SPARSE
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[8.0],
                                 twap_apr_pct=9.0))
        self.assertNotIn("SPARSE_SAMPLES", r["flags"])

    def test_sparse_samples_absent_with_three_samples(self):
        # twap from 3 samples (>=3), source not override → not flagged
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[8.0, 9.0, 10.0],
                                 twap_apr_pct=None))
        self.assertNotIn("SPARSE_SAMPLES", r["flags"])

    def test_sparse_samples_absent_zero_samples(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=9.0))
        self.assertNotIn("SPARSE_SAMPLES", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, twap_apr_pct=None,
                                 rate_samples_pct=None))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_one_classification_flag_only(self):
        r = A().analyze(make_pos(twap_apr_pct=5.0))
        class_flags = {"UNDERSTATED", "REPRESENTATIVE", "MINOR_PREMIUM",
                       "MODERATE_PREMIUM", "SEVERE_PREMIUM"}
        present = [f for f in r["flags"] if f in class_flags]
        self.assertEqual(len(present), 1)


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_spot_no_twap(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, twap_apr_pct=None,
                                 rate_samples_pct=None))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_spot_zero_with_twap(self):
        # spot <= 0 → insufficient even with twap override
        r = A().analyze(make_pos(headline_apr_pct=0.0, twap_apr_pct=9.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_spot_negative(self):
        r = A().analyze(make_pos(headline_apr_pct=-5.0, twap_apr_pct=9.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_twap_no_samples(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=None,
                                 rate_samples_pct=None))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_single_sample_below_min_no_override(self):
        # 1 sample < MIN_SAMPLES and no override → cannot derive twap
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[8.0], twap_apr_pct=None))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_nan_samples_no_override(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[float("nan"),
                                                   float("inf")],
                                 twap_apr_pct=None))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_empty_samples_no_override(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[], twap_apr_pct=None))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, twap_apr_pct=None,
                                 rate_samples_pct=None))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, twap_apr_pct=None,
                                 rate_samples_pct=None))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_insufficient_none_fields(self):
        r = A().analyze({})
        self.assertIsNone(r["twap_apr_pct"])
        self.assertIsNone(r["premium_ratio"])
        self.assertIsNone(r["representativeness_ratio"])
        self.assertIsNone(r["representativeness_pct"])
        self.assertIsNone(r["peak_sample_pct"])
        self.assertIsNone(r["trough_sample_pct"])
        self.assertIsNone(r["sample_range_pct"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("headline_apr_pct", "window_days", "premium_pct", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["overstated"])
        self.assertFalse(r["spot_at_peak"])
        self.assertEqual(r["sample_count"], 0)
        self.assertEqual(r["twap_source"], "none")

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_insufficient_has_all_keys(self):
        r = A().analyze({})
        valid = A().analyze(make_pos())
        self.assertEqual(set(r.keys()), set(valid.keys()))

    def test_valid_with_override(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=9.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_valid_with_samples(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 rate_samples_pct=[8.0, 10.0],
                                 twap_apr_pct=None))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring monotonicity & bounds ─────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_smaller_premium_scores_higher(self):
        small = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=9.5))
        big = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=2.0))
        self.assertGreater(small["score"], big["score"])

    def test_understated_high_score(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=14.0))
        self.assertGreater(r["score"], 85.0)

    def test_representative_high_score(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=9.8))
        self.assertGreater(r["score"], 85.0)

    def test_severe_premium_low_score(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=1.0))
        self.assertLess(r["score"], 55.0)

    def test_negative_twap_low_score(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=-5.0))
        self.assertLess(r["score"], 40.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(headline_apr_pct=1e-9, twap_apr_pct=1e12))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=1e9, twap_apr_pct=-1e9))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(twap_apr_pct=14.0),
                    make_pos(twap_apr_pct=9.5),
                    make_pos(twap_apr_pct=7.5),
                    make_pos(twap_apr_pct=5.0),
                    make_pos(twap_apr_pct=1.0),
                    make_pos(headline_apr_pct=0.0, twap_apr_pct=None,
                             rate_samples_pct=None)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(twap_apr_pct=14.0),
                    make_pos(twap_apr_pct=1.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_spot_at_twap_full_score(self):
        # spot == twap → premium 0, ratio 1 → 100
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=10.0))
        self.assertAlmostEqual(r["score"], 100.0)

    def test_monotonic_decreasing_with_premium(self):
        scores = []
        for twap in (10.0, 9.0, 8.0, 6.0, 3.0, 1.0):
            r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=twap))
            scores.append(r["score"])
        for a, b in zip(scores, scores[1:]):
            self.assertGreaterEqual(a, b)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Rep", headline_apr_pct=10.0, twap_apr_pct=9.8),
            make_pos(vault="Severe", headline_apr_pct=10.0, twap_apr_pct=1.0),
            make_pos(vault="Mid", headline_apr_pct=10.0, twap_apr_pct=5.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_representative_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_representative_vault"]],
                         max(scores.values()))

    def test_least_representative_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["least_representative_vault"]],
                         min(scores.values()))

    def test_most_representative_is_rep(self):
        self.assertEqual(self.res["aggregate"]["most_representative_vault"],
                         "Rep")

    def test_least_representative_is_severe(self):
        self.assertEqual(self.res["aggregate"]["least_representative_vault"],
                         "Severe")

    def test_severe_premium_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["severe_premium_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_representative_vault"])
        self.assertIsNone(res["aggregate"]["least_representative_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_empty_severe_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["severe_premium_count"], 0)

    def test_empty_avg_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=0.0, twap_apr_pct=None,
                     rate_samples_pct=None),
            make_pos(headline_apr_pct=0.0, twap_apr_pct=None,
                     rate_samples_pct=None),
        ])
        self.assertIsNone(res["aggregate"]["most_representative_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["severe_premium_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_representative_vault"], "Solo")
        self.assertEqual(res["aggregate"]["least_representative_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", headline_apr_pct=10.0, twap_apr_pct=9.8),
            make_pos(vault="Ins", headline_apr_pct=0.0, twap_apr_pct=None,
                     rate_samples_pct=None),
        ])
        scored = [p["score"] for p in res["positions"]
                  if p["classification"] != "INSUFFICIENT_DATA"]
        self.assertAlmostEqual(res["aggregate"]["avg_score"],
                               round(sum(scored) / len(scored), 2))

    def test_severe_count_multiple(self):
        res = A().analyze_portfolio([
            make_pos(vault="S1", twap_apr_pct=1.0),
            make_pos(vault="S2", twap_apr_pct=0.5),
            make_pos(vault="Rep", twap_apr_pct=9.8),
        ])
        self.assertEqual(res["aggregate"]["severe_premium_count"], 2)

    def test_aggregate_ignores_insufficient_for_ranking(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", twap_apr_pct=9.8),
            make_pos(vault="Ins", headline_apr_pct=0.0, twap_apr_pct=None,
                     rate_samples_pct=None),
        ])
        self.assertEqual(res["aggregate"]["most_representative_vault"], "Good")
        self.assertEqual(res["aggregate"]["least_representative_vault"], "Good")


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
                make_pos(vault="big", headline_apr_pct=1e-9,
                         twap_apr_pct=1e12),
                make_pos(vault="ins", headline_apr_pct=0.0,
                         twap_apr_pct=None, rate_samples_pct=None),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            json.loads(raw)

    def test_log_none_fields_serialize_null(self):
        res = A().analyze(make_pos(headline_apr_pct=0.0, twap_apr_pct=None,
                                   rate_samples_pct=None))
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

    def test_log_entry_has_ts(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIn("ts", data[0])

    def test_log_appends(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 2)

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
            "headline_apr_pct": "10",
            "twap_apr_pct": "8",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_string_samples_coerced(self):
        r = A().analyze({
            "vault": "S",
            "headline_apr_pct": "10",
            "rate_samples_pct": ["8.0", "12.0"],
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertAlmostEqual(r["twap_apr_pct"], 10.0)

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "headline_apr_pct": 10.0,
                         "twap_apr_pct": 8.0})
        self.assertIn("classification", r)

    def test_samples_as_tuple(self):
        r = A().analyze({"vault": "S", "headline_apr_pct": 10.0,
                         "rate_samples_pct": (8.0, 12.0)})
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_samples_not_list_ignored(self):
        # a non-list samples value is ignored; no override → insufficient
        r = A().analyze({"vault": "S", "headline_apr_pct": 10.0,
                         "rate_samples_pct": "notalist"})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(headline_apr_pct=0.0, twap_apr_pct=None,
                     rate_samples_pct=None),
            make_pos(twap_apr_pct=1.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(twap_apr_pct=14.0),
                    make_pos(twap_apr_pct=1.0),
                    make_pos(headline_apr_pct=0.0, twap_apr_pct=None,
                             rate_samples_pct=None),
                    make_pos(headline_apr_pct=1e-9, twap_apr_pct=1e12),
                    make_pos(headline_apr_pct=1e12, twap_apr_pct=-1e12),
                    make_pos(headline_apr_pct=10.0,
                             rate_samples_pct=[1e-12, 1e12],
                             twap_apr_pct=None),
                    make_pos(twap_apr_pct=-50.0)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=1e12, twap_apr_pct=1e9))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_tiny_twap_no_inf(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=1e-12))
        finite_check(self, r)

    def test_zero_twap_no_inf(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=0.0))
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, twap_apr_pct=-8.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_none_fields_are_none_or_finite(self):
        for pos in [make_pos(),
                    make_pos(headline_apr_pct=0.0, twap_apr_pct=None,
                             rate_samples_pct=None),
                    make_pos(headline_apr_pct=10.0,
                             rate_samples_pct=[8.0, 10.0], twap_apr_pct=None)]:
            r = A().analyze(pos)
            for k in ("twap_apr_pct", "premium_ratio",
                      "representativeness_ratio", "representativeness_pct",
                      "peak_sample_pct", "trough_sample_pct",
                      "sample_range_pct"):
                v = r[k]
                if v is not None:
                    self.assertTrue(math.isfinite(v))

    def test_nan_spot_treated_as_insufficient(self):
        # nan headline → _f keeps nan? float('nan') is finite? no. spot<=0
        # comparison with nan is False, but twap derivable; ensure no crash
        r = A().analyze({"vault": "X", "headline_apr_pct": float("nan"),
                         "twap_apr_pct": 9.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        finite_check(self, r)

    def test_analyze_matches_portfolio_single(self):
        pos = make_pos(twap_apr_pct=5.0)
        single = A().analyze(pos)
        port = A().analyze_portfolio([pos])
        self.assertEqual(single["classification"],
                         port["positions"][0]["classification"])
        self.assertEqual(single["score"], port["positions"][0]["score"])


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

    def test_demo_includes_representative_and_premium(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("REPRESENTATIVE", classes)
        self.assertTrue(
            "SEVERE_PREMIUM" in classes or "MODERATE_PREMIUM" in classes
            or "MINOR_PREMIUM" in classes)

    def test_demo_includes_severe(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("SEVERE_PREMIUM", classes)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)

    def test_demo_aggregate_present(self):
        res = A().analyze_portfolio(_demo_positions())
        agg = res["aggregate"]
        self.assertIn("most_representative_vault", agg)
        self.assertIn("least_representative_vault", agg)


if __name__ == "__main__":
    unittest.main()
