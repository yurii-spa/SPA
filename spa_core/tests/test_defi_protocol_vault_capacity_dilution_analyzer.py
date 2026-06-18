"""
Tests for MP-1166: DeFiProtocolVaultCapacityDilutionAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_capacity_dilution_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_capacity_dilution_analyzer import (
    DeFiProtocolVaultCapacityDilutionAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DECAY_EXPONENT_MIN,
    DECAY_EXPONENT_MAX,
    AMPLE_UTILIZATION_PCT,
    APPROACHING_UTILIZATION_PCT,
    OVER_UTILIZATION_PCT,
    AT_CAPACITY_TOLERANCE_PCT,
    DILUTION_SCORE_CEILING_PCT,
    HEADROOM_SCORE_CEILING_PCT,
    SEVERE_DILUTION_PCT,
    NEGLIGIBLE_DILUTION_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=10.0,
    current_tvl_usd=10_000_000.0,
    optimal_capacity_tvl_usd=50_000_000.0,
    your_deposit_usd=100_000.0,
    capacity_decay_exponent=1.0,
):
    return {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
        "current_tvl_usd": current_tvl_usd,
        "optimal_capacity_tvl_usd": optimal_capacity_tvl_usd,
        "your_deposit_usd": your_deposit_usd,
        "capacity_decay_exponent": capacity_decay_exponent,
    }


def A():
    return DeFiProtocolVaultCapacityDilutionAnalyzer()


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
        self.assertEqual(_f(None, 1.0), 1.0)

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
        self.assertLess(DECAY_EXPONENT_MIN, DECAY_EXPONENT_MAX)
        self.assertLess(AMPLE_UTILIZATION_PCT, APPROACHING_UTILIZATION_PCT)
        self.assertLess(APPROACHING_UTILIZATION_PCT, OVER_UTILIZATION_PCT)
        self.assertGreater(AT_CAPACITY_TOLERANCE_PCT, 0)
        self.assertGreater(DILUTION_SCORE_CEILING_PCT, 0)
        self.assertGreater(HEADROOM_SCORE_CEILING_PCT, 0)

    def test_flag_thresholds_positive(self):
        self.assertGreater(SEVERE_DILUTION_PCT, 0.0)
        self.assertGreater(NEGLIGIBLE_DILUTION_PCT, 0.0)
        self.assertLess(NEGLIGIBLE_DILUTION_PCT, SEVERE_DILUTION_PCT)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "headline_apr_pct", "current_tvl_usd",
            "optimal_capacity_tvl_usd", "your_deposit_usd",
            "capacity_decay_exponent", "post_deposit_tvl_usd",
            "over_capacity_usd", "utilization_pct", "effective_apr_pct",
            "dilution_pct", "apr_lost_pct", "headroom_usd", "headroom_pct",
            "over_capacity", "at_capacity", "score", "classification",
            "recommendation", "grade", "flags",
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
                         "optimal_capacity_tvl_usd": 50_000_000.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "headline_apr_pct": 10.0,
                         "optimal_capacity_tvl_usd": 50_000_000.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"headline_apr_pct": 10.0,
                         "optimal_capacity_tvl_usd": 50_000_000.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "DEPLOY", "DEPLOY_SOON", "DEPLOY_REDUCED_SIZE", "AVOID",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "AMPLE_HEADROOM", "APPROACHING_CAPACITY", "OVER_CAPACITY",
            "SEVERELY_DILUTED", "INSUFFICIENT_DATA",
        })

    def test_over_capacity_is_bool(self):
        self.assertIsInstance(self.r["over_capacity"], bool)

    def test_at_capacity_is_bool(self):
        self.assertIsInstance(self.r["at_capacity"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_apr_negative_clamped(self):
        r = A().analyze(make_pos(headline_apr_pct=-10.0))
        # apr<=0 → insufficient
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_current_tvl_negative_clamped(self):
        r = A().analyze(make_pos(current_tvl_usd=-1000.0))
        self.assertAlmostEqual(r["current_tvl_usd"], 0.0)

    def test_capacity_negative_clamped(self):
        r = A().analyze(make_pos(optimal_capacity_tvl_usd=-100.0))
        # capacity<=0 → insufficient
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_deposit_negative_clamped(self):
        r = A().analyze(make_pos(your_deposit_usd=-500.0))
        self.assertAlmostEqual(r["your_deposit_usd"], 0.0)

    def test_decay_exponent_clamped_low(self):
        r = A().analyze(make_pos(capacity_decay_exponent=0.01))
        self.assertAlmostEqual(r["capacity_decay_exponent"], DECAY_EXPONENT_MIN)

    def test_decay_exponent_clamped_high(self):
        r = A().analyze(make_pos(capacity_decay_exponent=99.0))
        self.assertAlmostEqual(r["capacity_decay_exponent"], DECAY_EXPONENT_MAX)

    def test_decay_exponent_default(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": 10.0,
                         "current_tvl_usd": 1000.0,
                         "optimal_capacity_tvl_usd": 50_000_000.0})
        self.assertAlmostEqual(r["capacity_decay_exponent"], 1.0)

    def test_post_deposit_tvl_sum(self):
        r = A().analyze(make_pos(current_tvl_usd=1_000_000.0,
                                 your_deposit_usd=200_000.0))
        self.assertAlmostEqual(r["post_deposit_tvl_usd"], 1_200_000.0)

    def test_over_capacity_usd_zero_under(self):
        r = A().analyze(make_pos(current_tvl_usd=1_000_000.0,
                                 your_deposit_usd=100_000.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertAlmostEqual(r["over_capacity_usd"], 0.0)

    def test_over_capacity_usd_positive(self):
        r = A().analyze(make_pos(current_tvl_usd=120_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertAlmostEqual(r["over_capacity_usd"], 70_000_000.0)

    def test_utilization_pct(self):
        # post 25M / capacity 50M *100 = 50
        r = A().analyze(make_pos(current_tvl_usd=24_900_000.0,
                                 your_deposit_usd=100_000.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertAlmostEqual(r["utilization_pct"], 50.0)

    def test_effective_apr_equals_headline_under_capacity(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_tvl_usd=1_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertAlmostEqual(r["effective_apr_pct"], 10.0)

    def test_effective_apr_diluted_over_capacity(self):
        # post 100M, capacity 50M, exp 1 → 10 * (50/100)^1 = 5
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_tvl_usd=100_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0,
                                 capacity_decay_exponent=1.0))
        self.assertAlmostEqual(r["effective_apr_pct"], 5.0)

    def test_effective_apr_exponent_steeper(self):
        # post 100M, capacity 50M, exp 2 → 10 * (0.5)^2 = 2.5
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_tvl_usd=100_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0,
                                 capacity_decay_exponent=2.0))
        self.assertAlmostEqual(r["effective_apr_pct"], 2.5)

    def test_effective_apr_at_capacity(self):
        # post == capacity → headline holds
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_tvl_usd=50_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertAlmostEqual(r["effective_apr_pct"], 10.0)

    def test_dilution_pct_zero_under(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_tvl_usd=1_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertAlmostEqual(r["dilution_pct"], 0.0)

    def test_dilution_pct_over(self):
        # effective 5, headline 10 → dilution 50%
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_tvl_usd=100_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0,
                                 capacity_decay_exponent=1.0))
        self.assertAlmostEqual(r["dilution_pct"], 50.0)

    def test_dilution_pct_clamped_max(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_tvl_usd=1e12,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=1.0,
                                 capacity_decay_exponent=3.0))
        self.assertLessEqual(r["dilution_pct"], 100.0)
        self.assertGreaterEqual(r["dilution_pct"], 0.0)

    def test_apr_lost_pct(self):
        # headline 10, effective 5 → lost 5
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_tvl_usd=100_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0,
                                 capacity_decay_exponent=1.0))
        self.assertAlmostEqual(r["apr_lost_pct"], 5.0)

    def test_apr_lost_pct_zero_under(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_tvl_usd=1_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertAlmostEqual(r["apr_lost_pct"], 0.0)

    def test_headroom_usd(self):
        # capacity 50M - current 10M = 40M
        r = A().analyze(make_pos(current_tvl_usd=10_000_000.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertAlmostEqual(r["headroom_usd"], 40_000_000.0)

    def test_headroom_usd_zero_when_over(self):
        r = A().analyze(make_pos(current_tvl_usd=120_000_000.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertAlmostEqual(r["headroom_usd"], 0.0)

    def test_headroom_pct(self):
        # headroom 40M / capacity 50M * 100 = 80
        r = A().analyze(make_pos(current_tvl_usd=10_000_000.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertAlmostEqual(r["headroom_pct"], 80.0)

    def test_over_capacity_flag_true(self):
        r = A().analyze(make_pos(current_tvl_usd=120_000_000.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertTrue(r["over_capacity"])

    def test_over_capacity_flag_false(self):
        r = A().analyze(make_pos(current_tvl_usd=1_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertFalse(r["over_capacity"])

    def test_at_capacity_true(self):
        r = A().analyze(make_pos(current_tvl_usd=50_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertTrue(r["at_capacity"])

    def test_at_capacity_false(self):
        r = A().analyze(make_pos(current_tvl_usd=1_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertFalse(r["at_capacity"])

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos())
        for k in ("utilization_pct", "effective_apr_pct", "dilution_pct",
                  "headroom_pct", "post_deposit_tvl_usd"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_ample_headroom(self):
        # util 20% → AMPLE
        r = A().analyze(make_pos(current_tvl_usd=10_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertEqual(r["classification"], "AMPLE_HEADROOM")

    def test_approaching_capacity(self):
        # util 90% → APPROACHING
        r = A().analyze(make_pos(current_tvl_usd=45_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertAlmostEqual(r["utilization_pct"], 90.0)
        self.assertEqual(r["classification"], "APPROACHING_CAPACITY")

    def test_over_capacity(self):
        # util 120% → OVER
        r = A().analyze(make_pos(current_tvl_usd=60_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertAlmostEqual(r["utilization_pct"], 120.0)
        self.assertEqual(r["classification"], "OVER_CAPACITY")

    def test_severely_diluted(self):
        # util 200% → SEVERE
        r = A().analyze(make_pos(current_tvl_usd=100_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertAlmostEqual(r["utilization_pct"], 200.0)
        self.assertEqual(r["classification"], "SEVERELY_DILUTED")

    def test_ample_boundary(self):
        # util exactly 70% → AMPLE (<=)
        r = A().analyze(make_pos(current_tvl_usd=35_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertAlmostEqual(r["utilization_pct"], 70.0)
        self.assertEqual(r["classification"], "AMPLE_HEADROOM")

    def test_approaching_boundary(self):
        # util exactly 100% → APPROACHING (<=)
        r = A().analyze(make_pos(current_tvl_usd=50_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertAlmostEqual(r["utilization_pct"], 100.0)
        self.assertEqual(r["classification"], "APPROACHING_CAPACITY")

    def test_over_boundary(self):
        # util exactly 150% → OVER (<=)
        r = A().analyze(make_pos(current_tvl_usd=75_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertAlmostEqual(r["utilization_pct"], 150.0)
        self.assertEqual(r["classification"], "OVER_CAPACITY")

    def test_insufficient_no_apr(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_no_capacity(self):
        r = A().analyze(make_pos(optimal_capacity_tvl_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(),
                    make_pos(current_tvl_usd=100_000_000.0),
                    make_pos(current_tvl_usd=45_000_000.0, your_deposit_usd=0.0),
                    make_pos(headline_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "AMPLE_HEADROOM", "APPROACHING_CAPACITY", "OVER_CAPACITY",
                "SEVERELY_DILUTED", "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_deploy_when_ample(self):
        r = A().analyze(make_pos(current_tvl_usd=10_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertEqual(r["recommendation"], "DEPLOY")

    def test_deploy_soon_when_approaching(self):
        r = A().analyze(make_pos(current_tvl_usd=45_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertEqual(r["recommendation"], "DEPLOY_SOON")

    def test_deploy_reduced_when_over(self):
        r = A().analyze(make_pos(current_tvl_usd=60_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertEqual(r["recommendation"], "DEPLOY_REDUCED_SIZE")

    def test_avoid_when_severe(self):
        r = A().analyze(make_pos(current_tvl_usd=100_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_avoid_when_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_ample_headroom_flag(self):
        r = A().analyze(make_pos(current_tvl_usd=10_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertIn("AMPLE_HEADROOM", r["flags"])

    def test_approaching_capacity_flag(self):
        r = A().analyze(make_pos(current_tvl_usd=45_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertIn("APPROACHING_CAPACITY", r["flags"])

    def test_over_capacity_flag(self):
        r = A().analyze(make_pos(current_tvl_usd=60_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertIn("OVER_CAPACITY", r["flags"])

    def test_severely_diluted_flag(self):
        # dilution >= 33%
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_tvl_usd=100_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0,
                                 capacity_decay_exponent=1.0))
        self.assertIn("SEVERELY_DILUTED", r["flags"])

    def test_severely_diluted_flag_absent_low_dilution(self):
        r = A().analyze(make_pos(current_tvl_usd=10_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertNotIn("SEVERELY_DILUTED", r["flags"])

    def test_your_deposit_tips_over_flag(self):
        # current under capacity, deposit pushes over
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_tvl_usd=49_000_000.0,
                                 your_deposit_usd=5_000_000.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertIn("YOUR_DEPOSIT_TIPS_OVER", r["flags"])

    def test_your_deposit_tips_over_absent_when_already_over(self):
        r = A().analyze(make_pos(current_tvl_usd=60_000_000.0,
                                 your_deposit_usd=1_000_000.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertNotIn("YOUR_DEPOSIT_TIPS_OVER", r["flags"])

    def test_your_deposit_tips_over_absent_when_stays_under(self):
        r = A().analyze(make_pos(current_tvl_usd=10_000_000.0,
                                 your_deposit_usd=1_000_000.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertNotIn("YOUR_DEPOSIT_TIPS_OVER", r["flags"])

    def test_no_headroom_flag(self):
        r = A().analyze(make_pos(current_tvl_usd=120_000_000.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertIn("NO_HEADROOM", r["flags"])

    def test_no_headroom_flag_absent(self):
        r = A().analyze(make_pos(current_tvl_usd=10_000_000.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertNotIn("NO_HEADROOM", r["flags"])

    def test_negligible_dilution_flag(self):
        r = A().analyze(make_pos(current_tvl_usd=10_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertIn("NEGLIGIBLE_DILUTION", r["flags"])

    def test_negligible_dilution_flag_absent_when_diluted(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_tvl_usd=100_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0,
                                 capacity_decay_exponent=1.0))
        self.assertNotIn("NEGLIGIBLE_DILUTION", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_apr(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_no_capacity(self):
        r = A().analyze(make_pos(optimal_capacity_tvl_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation_avoid(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_negative_inputs_insufficient(self):
        r = A().analyze(make_pos(headline_apr_pct=-10.0,
                                 optimal_capacity_tvl_usd=-50.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_breakeven_fields_none(self):
        r = A().analyze({})
        self.assertFalse(r["over_capacity"])
        self.assertFalse(r["at_capacity"])

    def test_insufficient_all_numeric_zero(self):
        r = A().analyze({})
        for k in ("headline_apr_pct", "post_deposit_tvl_usd",
                  "utilization_pct", "effective_apr_pct", "dilution_pct",
                  "headroom_usd", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_only_apr_without_capacity_insufficient(self):
        r = A().analyze({"headline_apr_pct": 10.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_more_headroom_scores_higher(self):
        ample = A().analyze(make_pos(current_tvl_usd=5_000_000.0,
                                     your_deposit_usd=0.0,
                                     optimal_capacity_tvl_usd=50_000_000.0))
        tight = A().analyze(make_pos(current_tvl_usd=48_000_000.0,
                                     your_deposit_usd=0.0,
                                     optimal_capacity_tvl_usd=50_000_000.0))
        self.assertGreater(ample["score"], tight["score"])

    def test_less_dilution_scores_higher(self):
        low = A().analyze(make_pos(current_tvl_usd=10_000_000.0,
                                   your_deposit_usd=0.0,
                                   optimal_capacity_tvl_usd=50_000_000.0))
        high = A().analyze(make_pos(current_tvl_usd=200_000_000.0,
                                    your_deposit_usd=0.0,
                                    optimal_capacity_tvl_usd=50_000_000.0))
        self.assertGreater(low["score"], high["score"])

    def test_not_over_scores_higher(self):
        under = A().analyze(make_pos(current_tvl_usd=40_000_000.0,
                                     your_deposit_usd=0.0,
                                     optimal_capacity_tvl_usd=50_000_000.0))
        over = A().analyze(make_pos(current_tvl_usd=60_000_000.0,
                                    your_deposit_usd=0.0,
                                    optimal_capacity_tvl_usd=50_000_000.0))
        self.assertGreater(under["score"], over["score"])

    def test_ample_scores_high(self):
        r = A().analyze(make_pos(current_tvl_usd=1_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertGreater(r["score"], 85.0)

    def test_severe_scores_low(self):
        r = A().analyze(make_pos(current_tvl_usd=500_000_000.0,
                                 your_deposit_usd=0.0,
                                 optimal_capacity_tvl_usd=50_000_000.0))
        self.assertLess(r["score"], 40.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(headline_apr_pct=1e6,
                                 current_tvl_usd=1e12,
                                 your_deposit_usd=1e12,
                                 optimal_capacity_tvl_usd=1.0,
                                 capacity_decay_exponent=3.0))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(current_tvl_usd=1e12,
                                 optimal_capacity_tvl_usd=1.0))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(),
                    make_pos(current_tvl_usd=100_000_000.0),
                    make_pos(current_tvl_usd=45_000_000.0, your_deposit_usd=0.0),
                    make_pos(headline_apr_pct=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(current_tvl_usd=1_000_000.0, your_deposit_usd=0.0),
                    make_pos(current_tvl_usd=500_000_000.0, your_deposit_usd=0.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Least", current_tvl_usd=5_000_000.0,
                     your_deposit_usd=0.0,
                     optimal_capacity_tvl_usd=50_000_000.0),
            make_pos(vault="Most", current_tvl_usd=500_000_000.0,
                     your_deposit_usd=0.0,
                     optimal_capacity_tvl_usd=50_000_000.0),
            make_pos(vault="Mid", current_tvl_usd=40_000_000.0,
                     your_deposit_usd=0.0,
                     optimal_capacity_tvl_usd=50_000_000.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_least_diluted_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["least_diluted_vault"]],
                         max(scores.values()))

    def test_most_diluted_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_diluted_vault"]],
                         min(scores.values()))

    def test_least_diluted_is_least(self):
        self.assertEqual(self.res["aggregate"]["least_diluted_vault"], "Least")

    def test_most_diluted_is_most(self):
        self.assertEqual(self.res["aggregate"]["most_diluted_vault"], "Most")

    def test_over_capacity_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["over_capacity_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["least_diluted_vault"])
        self.assertIsNone(res["aggregate"]["most_diluted_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=0.0),
            make_pos(headline_apr_pct=0.0),
        ])
        self.assertIsNone(res["aggregate"]["least_diluted_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["over_capacity_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["least_diluted_vault"], "Solo")
        self.assertEqual(res["aggregate"]["most_diluted_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", current_tvl_usd=1_000_000.0,
                     your_deposit_usd=0.0,
                     optimal_capacity_tvl_usd=50_000_000.0),
            make_pos(vault="Ins", headline_apr_pct=0.0),
        ])
        scored = [p["score"] for p in res["positions"]
                  if p["classification"] != "INSUFFICIENT_DATA"]
        self.assertAlmostEqual(res["aggregate"]["avg_score"],
                               round(sum(scored) / len(scored), 2))


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
                make_pos(vault="big", headline_apr_pct=1e6,
                         current_tvl_usd=1e12, your_deposit_usd=1e12,
                         optimal_capacity_tvl_usd=1.0,
                         capacity_decay_exponent=3.0),
                make_pos(vault="ins", headline_apr_pct=0.0),
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
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "vault": "S",
            "headline_apr_pct": "10",
            "current_tvl_usd": "10000000",
            "optimal_capacity_tvl_usd": "50000000",
            "your_deposit_usd": "100000",
            "capacity_decay_exponent": "1.0",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "headline_apr_pct": 10.0,
                         "optimal_capacity_tvl_usd": 50_000_000.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(headline_apr_pct=0.0),
            make_pos(current_tvl_usd=200_000_000.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(current_tvl_usd=200_000_000.0),
                    make_pos(current_tvl_usd=0.0, your_deposit_usd=0.0),
                    make_pos(headline_apr_pct=0.0),
                    make_pos(headline_apr_pct=1e6, current_tvl_usd=1e12),
                    make_pos(optimal_capacity_tvl_usd=1.0),
                    make_pos(capacity_decay_exponent=3.0,
                             current_tvl_usd=1e12),
                    make_pos(your_deposit_usd=1e12),
                    make_pos(current_tvl_usd=-100.0)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_zero_current_tvl_no_crash(self):
        r = A().analyze(make_pos(current_tvl_usd=0.0, your_deposit_usd=0.0))
        finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=1e9,
                                 current_tvl_usd=1e12,
                                 your_deposit_usd=1e12,
                                 optimal_capacity_tvl_usd=1e9,
                                 capacity_decay_exponent=3.0))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_tiny_capacity_no_inf(self):
        r = A().analyze(make_pos(current_tvl_usd=1e12,
                                 optimal_capacity_tvl_usd=1e-9))
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0,
                                 current_tvl_usd=-100.0,
                                 your_deposit_usd=-50.0,
                                 optimal_capacity_tvl_usd=50_000_000.0,
                                 capacity_decay_exponent=-5.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_effective_apr_never_negative(self):
        for pos in [make_pos(),
                    make_pos(current_tvl_usd=1e12,
                             optimal_capacity_tvl_usd=1.0,
                             capacity_decay_exponent=3.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["effective_apr_pct"], 0.0)


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

    def test_demo_includes_ample(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("AMPLE_HEADROOM", classes)

    def test_demo_includes_over_or_severe(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertTrue(
            "OVER_CAPACITY" in classes or "SEVERELY_DILUTED" in classes)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
