"""
Tests for MP-1181: DeFiProtocolVaultAPRSourceDispersionAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_apr_source_dispersion_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_apr_source_dispersion_analyzer import (
    DeFiProtocolVaultAPRSourceDispersionAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _median,
    _stdev,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    MIN_SOURCES,
    TIGHT_CONSENSUS_RATIO,
    MINOR_DISPERSION_RATIO,
    MODERATE_DISPERSION_RATIO,
    DISPERSION_CEILING,
    HEADLINE_GAP_CEILING,
    HEADLINE_OUTLIER_PCT,
    WIDE_SPREAD_PCT,
    DISPERSION_RATIO_CAP,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=12.0,
    source_aprs_pct=None,
):
    if source_aprs_pct is None:
        source_aprs_pct = [12.0, 11.8, 12.1, 12.05]
    return {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "source_aprs_pct": source_aprs_pct,
    }


def A():
    return DeFiProtocolVaultAPRSourceDispersionAnalyzer()


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

    def test_median_empty(self):
        self.assertEqual(_median([]), 0.0)

    def test_median_single(self):
        self.assertAlmostEqual(_median([5.0]), 5.0)

    def test_median_odd(self):
        self.assertAlmostEqual(_median([3.0, 1.0, 2.0]), 2.0)

    def test_median_even(self):
        self.assertAlmostEqual(_median([1.0, 2.0, 3.0, 4.0]), 2.5)

    def test_median_unsorted(self):
        self.assertAlmostEqual(_median([10.0, 2.0, 8.0, 4.0]), 6.0)

    def test_stdev_empty(self):
        self.assertEqual(_stdev([], 0.0), 0.0)

    def test_stdev_zero_when_uniform(self):
        self.assertAlmostEqual(_stdev([5.0, 5.0, 5.0], 5.0), 0.0)

    def test_stdev_population(self):
        # population stdev of [2,4,4,4,5,5,7,9] mean 5 = 2.0
        vals = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        self.assertAlmostEqual(_stdev(vals, _mean(vals)), 2.0, places=6)

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
        self.assertLess(TIGHT_CONSENSUS_RATIO, MINOR_DISPERSION_RATIO)
        self.assertLess(MINOR_DISPERSION_RATIO, MODERATE_DISPERSION_RATIO)
        self.assertEqual(MIN_SOURCES, 2)
        self.assertGreater(DISPERSION_CEILING, 0)
        self.assertGreater(HEADLINE_GAP_CEILING, 0)
        self.assertGreater(HEADLINE_OUTLIER_PCT, 0)
        self.assertGreater(WIDE_SPREAD_PCT, 0)
        self.assertGreater(DISPERSION_RATIO_CAP, 0)
        self.assertEqual(LOG_CAP, 100)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "headline_apr_pct", "source_count", "median_apr_pct",
            "mean_apr_pct", "apr_spread_pct", "dispersion_ratio",
            "headline_vs_median_pct", "headline_is_outlier", "wide_spread",
            "score", "classification", "recommendation", "grade", "flags",
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
        r = A().analyze({"token": "AltKey", "headline_apr_pct": 12.0,
                         "source_aprs_pct": [12.0, 12.1]})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T", "headline_apr_pct": 12.0,
                         "source_aprs_pct": [12.0, 12.1]})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"headline_apr_pct": 12.0,
                         "source_aprs_pct": [12.0, 12.1]})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "TRUST_HEADLINE", "MINOR_CONFIDENCE_DISCOUNT",
            "VERIFY_ACROSS_SOURCES", "AVOID_OR_VERIFY", "VERIFY_DATA",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "TIGHT_CONSENSUS", "MINOR_DISPERSION", "MODERATE_DISPERSION",
            "HIGH_DISPERSION", "INSUFFICIENT_DATA", "INSUFFICIENT_SOURCES",
        })

    def test_headline_is_outlier_is_bool(self):
        self.assertIsInstance(self.r["headline_is_outlier"], bool)

    def test_wide_spread_is_bool(self):
        self.assertIsInstance(self.r["wide_spread"], bool)

    def test_source_count_is_int(self):
        self.assertIsInstance(self.r["source_count"], int)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_headline_passthrough(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0))
        self.assertAlmostEqual(r["headline_apr_pct"], 12.0)

    def test_headline_negative_clamped_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=-3.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_source_count(self):
        r = A().analyze(make_pos(source_aprs_pct=[10.0, 11.0, 12.0]))
        self.assertEqual(r["source_count"], 3)

    def test_source_count_filters_negatives(self):
        r = A().analyze(make_pos(source_aprs_pct=[10.0, -5.0, 12.0]))
        self.assertEqual(r["source_count"], 2)

    def test_source_count_filters_none(self):
        r = A().analyze(make_pos(source_aprs_pct=[10.0, None, 12.0]))
        self.assertEqual(r["source_count"], 2)

    def test_source_count_filters_nonnumeric(self):
        r = A().analyze(make_pos(source_aprs_pct=[10.0, "bad", 12.0]))
        self.assertEqual(r["source_count"], 2)

    def test_source_count_filters_bool(self):
        # bool is excluded explicitly
        r = A().analyze(make_pos(source_aprs_pct=[10.0, True, 12.0]))
        self.assertEqual(r["source_count"], 2)

    def test_median(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[10.0, 12.0, 14.0]))
        self.assertAlmostEqual(r["median_apr_pct"], 12.0, places=4)

    def test_mean(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[10.0, 12.0, 14.0]))
        self.assertAlmostEqual(r["mean_apr_pct"], 12.0, places=4)

    def test_apr_spread(self):
        # max 14 - min 10 = 4
        r = A().analyze(make_pos(source_aprs_pct=[10.0, 12.0, 14.0]))
        self.assertAlmostEqual(r["apr_spread_pct"], 4.0, places=4)

    def test_dispersion_ratio_zero_when_uniform(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[12.0, 12.0, 12.0]))
        self.assertAlmostEqual(r["dispersion_ratio"], 0.0, places=4)

    def test_dispersion_ratio_value(self):
        # sources [9,12,15] mean 12, pop stdev sqrt(18/3? ) -> var=((9-12)^2+
        # 0+(15-12)^2)/3 = (9+0+9)/3=6, stdev=sqrt(6)=2.449; CoV=0.2041
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[9.0, 12.0, 15.0]))
        expected = math.sqrt(6.0) / 12.0
        self.assertAlmostEqual(r["dispersion_ratio"], round(expected, 4),
                               places=4)

    def test_headline_vs_median_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[10.0, 12.0, 14.0]))
        self.assertAlmostEqual(r["headline_vs_median_pct"], 0.0, places=4)

    def test_headline_vs_median_value(self):
        # headline 15, median 12 → |15-12|/12*100 = 25
        r = A().analyze(make_pos(headline_apr_pct=15.0,
                                 source_aprs_pct=[10.0, 12.0, 14.0]))
        self.assertAlmostEqual(r["headline_vs_median_pct"], 25.0, places=4)

    def test_headline_is_outlier_true(self):
        # gap 25% > 15% threshold
        r = A().analyze(make_pos(headline_apr_pct=15.0,
                                 source_aprs_pct=[10.0, 12.0, 14.0]))
        self.assertTrue(r["headline_is_outlier"])

    def test_headline_is_outlier_false(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[10.0, 12.0, 14.0]))
        self.assertFalse(r["headline_is_outlier"])

    def test_headline_is_outlier_boundary(self):
        # gap exactly 15% is NOT > 15 → not outlier
        # median 10, headline 11.5 → 15%
        r = A().analyze(make_pos(headline_apr_pct=11.5,
                                 source_aprs_pct=[8.0, 10.0, 12.0]))
        self.assertAlmostEqual(r["headline_vs_median_pct"], 15.0, places=4)
        self.assertFalse(r["headline_is_outlier"])

    def test_wide_spread_true(self):
        # spread 20-5 = 15 >= 10
        r = A().analyze(make_pos(source_aprs_pct=[5.0, 12.0, 20.0]))
        self.assertTrue(r["wide_spread"])

    def test_wide_spread_boundary(self):
        # spread exactly 10 → flagged
        r = A().analyze(make_pos(source_aprs_pct=[10.0, 15.0, 20.0]))
        self.assertAlmostEqual(r["apr_spread_pct"], 10.0, places=4)
        self.assertTrue(r["wide_spread"])

    def test_wide_spread_false(self):
        r = A().analyze(make_pos(source_aprs_pct=[10.0, 11.0, 12.0]))
        self.assertFalse(r["wide_spread"])

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(headline_apr_pct=13.3333,
                                 source_aprs_pct=[9.1111, 12.5555, 15.7777]))
        for k in ("headline_apr_pct", "median_apr_pct", "mean_apr_pct",
                  "apr_spread_pct", "dispersion_ratio",
                  "headline_vs_median_pct"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_tight_consensus(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[12.0, 12.05, 11.98, 12.02]))
        self.assertEqual(r["classification"], "TIGHT_CONSENSUS")

    def test_minor_dispersion(self):
        # CoV ~0.10
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[11.0, 12.0, 13.0]))
        self.assertEqual(r["classification"], "MINOR_DISPERSION")

    def test_moderate_dispersion(self):
        # sources [9,12,15] CoV ~0.204
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[9.0, 12.0, 15.0]))
        self.assertEqual(r["classification"], "MODERATE_DISPERSION")

    def test_high_dispersion(self):
        # sources [5,12,25] high CoV
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[5.0, 12.0, 25.0]))
        self.assertEqual(r["classification"], "HIGH_DISPERSION")

    def test_tight_boundary(self):
        # CoV exactly 0.05. mean 12, need stdev 0.6. Use [11.4,12.6] →
        # var ((-0.6)^2+(0.6)^2)/2 = 0.36, stdev 0.6, CoV 0.05
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[11.4, 12.6]))
        self.assertAlmostEqual(r["dispersion_ratio"], 0.05, places=4)
        self.assertEqual(r["classification"], "TIGHT_CONSENSUS")

    def test_minor_boundary(self):
        # CoV exactly 0.15: mean 12, stdev 1.8 → [10.2,13.8]
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[10.2, 13.8]))
        self.assertAlmostEqual(r["dispersion_ratio"], 0.15, places=4)
        self.assertEqual(r["classification"], "MINOR_DISPERSION")

    def test_moderate_boundary(self):
        # CoV exactly 0.30: mean 12, stdev 3.6 → [8.4,15.6]
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[8.4, 15.6]))
        self.assertAlmostEqual(r["dispersion_ratio"], 0.30, places=4)
        self.assertEqual(r["classification"], "MODERATE_DISPERSION")

    def test_above_moderate_high(self):
        # CoV 0.35: mean 12, stdev 4.2 → [7.8,16.2]
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[7.8, 16.2]))
        self.assertAlmostEqual(r["dispersion_ratio"], 0.35, places=4)
        self.assertEqual(r["classification"], "HIGH_DISPERSION")

    def test_insufficient_no_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_sources_one(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[12.0]))
        self.assertEqual(r["classification"], "INSUFFICIENT_SOURCES")

    def test_insufficient_sources_empty(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0, source_aprs_pct=[]))
        self.assertEqual(r["classification"], "INSUFFICIENT_SOURCES")

    def test_insufficient_sources_all_filtered(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[None, -5.0, "x"]))
        self.assertEqual(r["classification"], "INSUFFICIENT_SOURCES")

    def test_min_sources_exactly_two(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[12.0, 12.0]))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_SOURCES")

    def test_classification_known_value(self):
        for pos in [make_pos(source_aprs_pct=[12.0, 12.0]),
                    make_pos(source_aprs_pct=[9.0, 12.0, 15.0]),
                    make_pos(source_aprs_pct=[5.0, 25.0]),
                    make_pos(source_aprs_pct=[12.0]),
                    make_pos(headline_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "TIGHT_CONSENSUS", "MINOR_DISPERSION", "MODERATE_DISPERSION",
                "HIGH_DISPERSION", "INSUFFICIENT_DATA", "INSUFFICIENT_SOURCES",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_trust_tight(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[12.0, 12.02, 11.99]))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_minor_discount(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[11.0, 12.0, 13.0]))
        self.assertEqual(r["recommendation"], "MINOR_CONFIDENCE_DISCOUNT")

    def test_verify_moderate(self):
        # moderate, headline aligned → VERIFY_ACROSS_SOURCES
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[9.0, 12.0, 15.0]))
        self.assertEqual(r["recommendation"], "VERIFY_ACROSS_SOURCES")

    def test_avoid_high(self):
        # high dispersion, headline aligned with median
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[5.0, 12.0, 25.0]))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_avoid_outlier_moderate_override(self):
        # moderate dispersion + headline outlier → AVOID override
        # sources [9,12,15] median 12 CoV moderate; headline 18 → gap 50%
        r = A().analyze(make_pos(headline_apr_pct=18.0,
                                 source_aprs_pct=[9.0, 12.0, 15.0]))
        self.assertTrue(r["headline_is_outlier"])
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_outlier_minor_no_override(self):
        # minor dispersion but headline outlier → no override (only >=MODERATE)
        # sources [11,12,13] CoV minor, median 12; headline 15 → gap 25%
        r = A().analyze(make_pos(headline_apr_pct=15.0,
                                 source_aprs_pct=[11.0, 12.0, 13.0]))
        self.assertTrue(r["headline_is_outlier"])
        self.assertEqual(r["recommendation"], "MINOR_CONFIDENCE_DISCOUNT")

    def test_outlier_tight_no_override(self):
        # tight consensus but headline outlier → no override
        r = A().analyze(make_pos(headline_apr_pct=15.0,
                                 source_aprs_pct=[12.0, 12.02, 11.99]))
        self.assertTrue(r["headline_is_outlier"])
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_verify_insufficient_data(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_verify_insufficient_sources(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[12.0]))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_tight_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[12.0, 12.02, 11.99]))
        self.assertIn("TIGHT_CONSENSUS", r["flags"])

    def test_minor_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[11.0, 12.0, 13.0]))
        self.assertIn("MINOR_DISPERSION", r["flags"])

    def test_moderate_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[9.0, 12.0, 15.0]))
        self.assertIn("MODERATE_DISPERSION", r["flags"])

    def test_high_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[5.0, 12.0, 25.0]))
        self.assertIn("HIGH_DISPERSION", r["flags"])

    def test_headline_outlier_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=18.0,
                                 source_aprs_pct=[9.0, 12.0, 15.0]))
        self.assertIn("HEADLINE_OUTLIER", r["flags"])

    def test_headline_outlier_flag_absent(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[9.0, 12.0, 15.0]))
        self.assertNotIn("HEADLINE_OUTLIER", r["flags"])

    def test_wide_spread_flag(self):
        r = A().analyze(make_pos(source_aprs_pct=[5.0, 12.0, 25.0]))
        self.assertIn("WIDE_SPREAD", r["flags"])

    def test_wide_spread_flag_absent(self):
        r = A().analyze(make_pos(source_aprs_pct=[11.0, 12.0, 13.0]))
        self.assertNotIn("WIDE_SPREAD", r["flags"])

    def test_insufficient_data_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_insufficient_sources_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[12.0]))
        self.assertEqual(r["flags"], ["INSUFFICIENT_SOURCES"])

    def test_classification_flags_mutually_exclusive(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[12.0, 12.02, 11.99]))
        self.assertIn("TIGHT_CONSENSUS", r["flags"])
        self.assertNotIn("HIGH_DISPERSION", r["flags"])

    def test_high_and_outlier_and_wide_together(self):
        r = A().analyze(make_pos(headline_apr_pct=30.0,
                                 source_aprs_pct=[5.0, 9.0, 25.0]))
        self.assertIn("HIGH_DISPERSION", r["flags"])
        self.assertIn("HEADLINE_OUTLIER", r["flags"])
        self.assertIn("WIDE_SPREAD", r["flags"])


# ── insufficient data / sources ───────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_insufficient_metrics_none(self):
        r = A().analyze({})
        self.assertIsNone(r["median_apr_pct"])
        self.assertIsNone(r["mean_apr_pct"])
        self.assertIsNone(r["apr_spread_pct"])
        self.assertIsNone(r["dispersion_ratio"])
        self.assertIsNone(r["headline_vs_median_pct"])

    def test_insufficient_bools_false(self):
        r = A().analyze({})
        self.assertFalse(r["headline_is_outlier"])
        self.assertFalse(r["wide_spread"])

    def test_insufficient_source_count_zero(self):
        r = A().analyze({})
        self.assertEqual(r["source_count"], 0)

    def test_insufficient_no_inf_nan(self):
        finite_check(self, A().analyze({}))

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    # INSUFFICIENT_SOURCES specifics
    def test_sources_score_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[12.0]))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_sources_metrics_none(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[12.0]))
        self.assertIsNone(r["median_apr_pct"])
        self.assertIsNone(r["dispersion_ratio"])
        self.assertIsNone(r["headline_vs_median_pct"])

    def test_sources_keeps_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[12.0]))
        self.assertAlmostEqual(r["headline_apr_pct"], 12.0)

    def test_sources_count_preserved(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[12.0]))
        self.assertEqual(r["source_count"], 1)

    def test_sources_json_serializable(self):
        json.dumps(A().analyze(make_pos(headline_apr_pct=12.0,
                                        source_aprs_pct=[12.0])))

    def test_sources_no_inf_nan(self):
        finite_check(self, A().analyze(make_pos(headline_apr_pct=12.0,
                                                source_aprs_pct=[12.0])))

    def test_sources_missing_field(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 12.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_SOURCES")

    def test_valid_with_sources(self):
        r = A().analyze(make_pos())
        self.assertNotIn(r["classification"],
                         ("INSUFFICIENT_DATA", "INSUFFICIENT_SOURCES"))


# ── scoring ───────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_consistent_scores_higher(self):
        tight = A().analyze(make_pos(headline_apr_pct=12.0,
                                     source_aprs_pct=[12.0, 12.02, 11.99]))
        dispersed = A().analyze(make_pos(headline_apr_pct=12.0,
                                         source_aprs_pct=[5.0, 12.0, 25.0]))
        self.assertGreater(tight["score"], dispersed["score"])

    def test_perfect_consensus_full_score(self):
        # zero dispersion, headline == median → 100
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[12.0, 12.0, 12.0]))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_near_consensus_high(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[12.0, 12.01, 11.99]))
        self.assertGreater(r["score"], 95.0)

    def test_worst_case_low_score(self):
        # huge dispersion + headline far outlier
        r = A().analyze(make_pos(headline_apr_pct=100.0,
                                 source_aprs_pct=[1.0, 50.0, 100.0]))
        self.assertLess(r["score"], 30.0)

    def test_known_score(self):
        # sources [9,12,15] CoV = sqrt(6)/12; median 12; headline 12 gap 0
        # disp_frac = clamp(CoV/0.30); agreement 60*(1-frac)
        # alignment 40 (gap 0)
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[9.0, 12.0, 15.0]))
        cov = math.sqrt(6.0) / 12.0
        disp_frac = min(cov / DISPERSION_CEILING, 1.0)
        expected = 60.0 * (1.0 - disp_frac) + 40.0
        self.assertAlmostEqual(r["score"], round(expected, 2), places=1)

    def test_known_score_with_gap(self):
        # tight sources but headline off median
        # sources [12,12,12] CoV 0; agreement 60
        # headline 15 median 12 → gap 25; gap_frac=clamp(25/30)=0.8333
        # alignment 40*(1-0.8333)=6.667 → total 66.67
        r = A().analyze(make_pos(headline_apr_pct=15.0,
                                 source_aprs_pct=[12.0, 12.0, 12.0]))
        gap = 25.0
        gap_frac = min(gap / HEADLINE_GAP_CEILING, 1.0)
        expected = 60.0 + 40.0 * (1.0 - gap_frac)
        self.assertAlmostEqual(r["score"], round(expected, 2), places=1)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=1e6,
                                 source_aprs_pct=[1.0, 1e6]))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(headline_apr_pct=1e9,
                                 source_aprs_pct=[1.0, 1e9, 1e6]))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(source_aprs_pct=[12.0, 12.0]),
                    make_pos(source_aprs_pct=[9.0, 12.0, 15.0]),
                    make_pos(source_aprs_pct=[5.0, 25.0]),
                    make_pos(headline_apr_pct=0.0),
                    make_pos(source_aprs_pct=[12.0])]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(source_aprs_pct=[12.0, 12.0]),
                    make_pos(headline_apr_pct=100.0,
                             source_aprs_pct=[1.0, 50.0, 100.0])]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_bigger_gap_lower_score(self):
        small = A().analyze(make_pos(headline_apr_pct=12.5,
                                     source_aprs_pct=[12.0, 12.0, 12.0]))
        big = A().analyze(make_pos(headline_apr_pct=18.0,
                                   source_aprs_pct=[12.0, 12.0, 12.0]))
        self.assertGreater(small["score"], big["score"])


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Tight", source_aprs_pct=[12.0, 12.02, 11.99]),
            make_pos(vault="Dispersed", source_aprs_pct=[5.0, 12.0, 25.0]),
            make_pos(vault="Mid", source_aprs_pct=[9.0, 12.0, 15.0]),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_consistent_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_consistent_vault"]],
                         max(scores.values()))

    def test_most_dispersed_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_dispersed_vault"]],
                         min(scores.values()))

    def test_most_consistent_is_tight(self):
        self.assertEqual(self.res["aggregate"]["most_consistent_vault"],
                         "Tight")

    def test_most_dispersed_is_dispersed(self):
        self.assertEqual(self.res["aggregate"]["most_dispersed_vault"],
                         "Dispersed")

    def test_high_dispersion_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["high_dispersion_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_high_dispersion_count_exact(self):
        res = A().analyze_portfolio([
            make_pos(vault="A", source_aprs_pct=[5.0, 25.0]),
            make_pos(vault="B", source_aprs_pct=[3.0, 30.0]),
            make_pos(vault="C", source_aprs_pct=[12.0, 12.0]),
        ])
        self.assertEqual(res["aggregate"]["high_dispersion_count"], 2)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_consistent_vault"])
        self.assertIsNone(res["aggregate"]["most_dispersed_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=0.0),
            make_pos(headline_apr_pct=12.0, source_aprs_pct=[12.0]),
        ])
        self.assertIsNone(res["aggregate"]["most_consistent_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["high_dispersion_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_consistent_vault"], "Solo")
        self.assertEqual(res["aggregate"]["most_dispersed_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good"),
            make_pos(vault="Ins", headline_apr_pct=0.0),
            make_pos(vault="OneSrc", source_aprs_pct=[12.0]),
        ])
        scored = [p["score"] for p in res["positions"]
                  if p["classification"] not in (
                      "INSUFFICIENT_DATA", "INSUFFICIENT_SOURCES")]
        self.assertAlmostEqual(res["aggregate"]["avg_score"],
                               round(sum(scored) / len(scored), 2))

    def test_insufficient_sources_excluded_from_best(self):
        # an INSUFFICIENT_SOURCES (score 0) must not become most_dispersed
        res = A().analyze_portfolio([
            make_pos(vault="Good", source_aprs_pct=[12.0, 12.0]),
            make_pos(vault="OneSrc", source_aprs_pct=[12.0]),
        ])
        self.assertEqual(res["aggregate"]["most_consistent_vault"], "Good")
        self.assertEqual(res["aggregate"]["most_dispersed_vault"], "Good")


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
                         source_aprs_pct=[1.0, 1e9, 1e6]),
                make_pos(vault="ins", headline_apr_pct=0.0),
                make_pos(vault="onesrc", source_aprs_pct=[12.0]),
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
    def test_int_sources_accepted(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[10, 12, 14]))
        self.assertEqual(r["source_count"], 3)

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "headline_apr_pct": 12.0,
                         "source_aprs_pct": [12.0, 12.0]})
        self.assertIn("classification", r)

    def test_sources_not_a_list(self):
        r = A().analyze({"vault": "S", "headline_apr_pct": 12.0,
                         "source_aprs_pct": "notalist"})
        self.assertEqual(r["classification"], "INSUFFICIENT_SOURCES")

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(headline_apr_pct=0.0),
            make_pos(source_aprs_pct=[5.0, 25.0]),
            make_pos(source_aprs_pct=[12.0]),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(source_aprs_pct=[5.0, 12.0, 25.0]),
                    make_pos(headline_apr_pct=0.0),
                    make_pos(source_aprs_pct=[12.0]),
                    make_pos(source_aprs_pct=[]),
                    make_pos(headline_apr_pct=1e9,
                             source_aprs_pct=[1.0, 1e9, 1e6]),
                    make_pos(headline_apr_pct=-1e9),
                    make_pos(source_aprs_pct=[0.0, 0.0])]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_zero_sources_no_crash(self):
        # all-zero sources → mean 0 → dispersion_ratio safe_div sentinel 0
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[0.0, 0.0]))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=1e12,
                                 source_aprs_pct=[1.0, 1e9, 1e6]))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_headline_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        finite_check(self, r)

    def test_mixed_garbage_sources(self):
        r = A().analyze(make_pos(headline_apr_pct=12.0,
                                 source_aprs_pct=[12.0, None, "x", -3.0, 13.0,
                                                  float("inf")]))
        # only 12.0 and 13.0 are valid
        self.assertEqual(r["source_count"], 2)
        finite_check(self, r)


# ── CLI smoke ─────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_demo_positions_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 6)

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

    def test_demo_includes_insufficient_data(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_includes_insufficient_sources(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("INSUFFICIENT_SOURCES", classes)

    def test_demo_includes_tight_and_high(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("TIGHT_CONSENSUS", classes)
        self.assertIn("HIGH_DISPERSION", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("TIGHT_CONSENSUS", "MINOR_DISPERSION", "MODERATE_DISPERSION",
                  "HIGH_DISPERSION", "INSUFFICIENT_DATA",
                  "INSUFFICIENT_SOURCES"):
            self.assertIn(c, classes)

    def test_demo_includes_avoid_and_trust(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("AVOID_OR_VERIFY", recs)
        self.assertIn("TRUST_HEADLINE", recs)

    def test_demo_includes_headline_outlier(self):
        res = A().analyze_portfolio(_demo_positions())
        outlier = any("HEADLINE_OUTLIER" in p["flags"]
                      for p in res["positions"])
        self.assertTrue(outlier)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
