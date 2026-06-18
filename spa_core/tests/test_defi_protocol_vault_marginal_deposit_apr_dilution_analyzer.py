"""
Tests for MP-1194: DeFiProtocolVaultMarginalDepositAPRDilutionAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_marginal_deposit_apr_dilution_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_marginal_deposit_apr_dilution_analyzer import (  # noqa: E501
    DeFiProtocolVaultMarginalDepositAPRDilutionAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DEFAULT_NEW_DEPOSIT_USD,
    ALIGN_TOLERANCE_PCT,
    DILUTION_SCORE_CEILING_PCT,
    MINOR_DILUTION_PCT,
    MODERATE_DILUTION_PCT,
    MIN_SLEEVES,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def sleeve(apr_pct, allocation_usd=1_000_000.0, capacity_remaining_usd=0.0):
    return {
        "apr_pct": apr_pct,
        "allocation_usd": allocation_usd,
        "capacity_remaining_usd": capacity_remaining_usd,
    }


def make_pos(
    vault="USDC-Vault",
    headline_apr_pct=12.0,
    sleeves=None,
    new_deposit_usd=100000.0,
):
    pos = {
        "vault": vault,
        "headline_apr_pct": headline_apr_pct,
    }
    if sleeves is None:
        # Default: two sleeves; top has ample capacity → ALIGNED-ish.
        sleeves = [
            sleeve(12.0, 1_000_000.0, 5_000_000.0),
            sleeve(8.0, 500_000.0, 2_000_000.0),
        ]
    pos["sleeves"] = sleeves
    if new_deposit_usd is not None:
        pos["new_deposit_usd"] = new_deposit_usd
    return pos


def A():
    return DeFiProtocolVaultMarginalDepositAPRDilutionAnalyzer()


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
        self.assertGreater(ALIGN_TOLERANCE_PCT, 0)
        self.assertGreater(DILUTION_SCORE_CEILING_PCT, 0)
        self.assertLess(MINOR_DILUTION_PCT, MODERATE_DILUTION_PCT)
        self.assertGreater(DEFAULT_NEW_DEPOSIT_USD, 0)
        self.assertGreaterEqual(MIN_SLEEVES, 1)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "headline_apr_pct", "marginal_apr_pct",
            "weighted_avg_apr_pct", "dilution_pct", "dilution_ratio",
            "top_sleeve_apr_pct", "top_sleeve_capacity_remaining_usd",
            "total_remaining_capacity_usd", "new_deposit_usd",
            "deployable_usd", "undeployed_usd", "sleeve_count",
            "fully_absorbed", "top_sleeve_constrained", "score",
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
        r = A().analyze({"token": "AltKey", "headline_apr_pct": 12.0,
                         "sleeves": [sleeve(12.0, 1e6, 5e6)]})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "headline_apr_pct": 12.0,
                         "sleeves": [sleeve(12.0, 1e6, 5e6)]})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"headline_apr_pct": 12.0,
                         "sleeves": [sleeve(12.0, 1e6, 5e6)]})
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
            "MARGINAL_ABOVE_HEADLINE", "ALIGNED", "MINOR_DILUTION",
            "MODERATE_DILUTION", "SEVERE_DILUTION", "INSUFFICIENT_DATA",
        })

    def test_fully_absorbed_is_bool(self):
        self.assertIsInstance(self.r["fully_absorbed"], bool)

    def test_top_sleeve_constrained_is_bool(self):
        self.assertIsInstance(self.r["top_sleeve_constrained"], bool)

    def test_sleeve_count_is_int(self):
        self.assertIsInstance(self.r["sleeve_count"], int)


# ── marginal routing correctness ──────────────────────────────────────────────

class TestRouting(unittest.TestCase):
    def test_all_into_top_sleeve(self):
        # Top sleeve 12% with ample capacity absorbs the whole deposit.
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(12.0, 1e6, 5e6), sleeve(8.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["marginal_apr_pct"], 12.0)

    def test_split_across_two_sleeves(self):
        # Top sleeve (20%) cap 40k, then 8% sleeve takes remaining 60k.
        # marginal = (40k*20 + 60k*8)/100k = (800k + 480k)/100k = 12.8
        r = A().analyze(make_pos(
            headline_apr_pct=14.0,
            sleeves=[sleeve(20.0, 1e6, 40000.0),
                     sleeve(8.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["marginal_apr_pct"], 12.8)

    def test_descending_fill_order(self):
        # Even if listed low-first, fill descending: 20% first.
        r = A().analyze(make_pos(
            headline_apr_pct=14.0,
            sleeves=[sleeve(8.0, 1e6, 5e6),
                     sleeve(20.0, 1e6, 40000.0)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["marginal_apr_pct"], 12.8)

    def test_undeployed_idle_drag(self):
        # Total capacity 50k < deposit 100k; 50k idle at 0%.
        # marginal = (50k*10 + 50k*0)/100k = 5.0
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, 1e6, 50000.0)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["marginal_apr_pct"], 5.0)
        self.assertAlmostEqual(r["undeployed_usd"], 50000.0)
        self.assertAlmostEqual(r["deployable_usd"], 50000.0)
        self.assertFalse(r["fully_absorbed"])

    def test_fully_absorbed_when_capacity_ample(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, 1e6, 1e6)],
            new_deposit_usd=100000.0))
        self.assertTrue(r["fully_absorbed"])
        self.assertAlmostEqual(r["undeployed_usd"], 0.0)

    def test_deployable_capped_by_capacity(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, 1e6, 30000.0)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["deployable_usd"], 30000.0)
        self.assertAlmostEqual(r["total_remaining_capacity_usd"], 30000.0)

    def test_total_remaining_capacity_sum(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, 1e6, 20000.0),
                     sleeve(8.0, 1e6, 30000.0)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["total_remaining_capacity_usd"], 50000.0)

    def test_top_sleeve_apr_is_highest(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(8.0, 1e6, 5e6),
                     sleeve(20.0, 1e6, 5e6),
                     sleeve(12.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["top_sleeve_apr_pct"], 20.0)

    def test_top_sleeve_capacity_reported(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(20.0, 1e6, 1234.0),
                     sleeve(8.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["top_sleeve_capacity_remaining_usd"], 1234.0)

    def test_top_sleeve_constrained_true(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(20.0, 1e6, 1000.0),
                     sleeve(8.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertTrue(r["top_sleeve_constrained"])

    def test_top_sleeve_constrained_false(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(20.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertFalse(r["top_sleeve_constrained"])

    def test_marginal_zero_when_no_capacity(self):
        # Zero remaining capacity everywhere → all idle at 0%.
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(20.0, 1e6, 0.0), sleeve(8.0, 1e6, 0.0)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["marginal_apr_pct"], 0.0)
        self.assertAlmostEqual(r["undeployed_usd"], 100000.0)

    def test_three_sleeve_cascade(self):
        # 20% cap 10k, 12% cap 20k, 8% cap ample.
        # fill: 10k*20 + 20k*12 + 70k*8 = 200k + 240k + 560k = 1000k /100k=10.0
        r = A().analyze(make_pos(
            headline_apr_pct=12.0,
            sleeves=[sleeve(20.0, 1e6, 10000.0),
                     sleeve(12.0, 1e6, 20000.0),
                     sleeve(8.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["marginal_apr_pct"], 10.0)

    def test_default_deposit_used(self):
        r = A().analyze({"vault": "V", "headline_apr_pct": 10.0,
                         "sleeves": [sleeve(10.0, 1e6, 1e9)]})
        self.assertAlmostEqual(r["new_deposit_usd"], DEFAULT_NEW_DEPOSIT_USD)

    def test_negative_deposit_clamped_insufficient(self):
        # negative → max(0,..)=0 → new_deposit<=0 → insufficient
        r = A().analyze(make_pos(new_deposit_usd=-100.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_allocation_clamped(self):
        # negative allocation clamped to 0 in weighting; no crash.
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, -500.0, 5e6)],
            new_deposit_usd=100000.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")
        finite_check(self, r)

    def test_negative_capacity_clamped(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, 1e6, -50000.0)],
            new_deposit_usd=100000.0))
        # capacity clamped to 0 → all idle → marginal 0
        self.assertAlmostEqual(r["marginal_apr_pct"], 0.0)


# ── weighted average computation ──────────────────────────────────────────────

class TestWeightedAvg(unittest.TestCase):
    def test_alloc_weighted(self):
        # 12% on 3M, 8% on 1M → (12*3 + 8*1)/4 = 44/4 = 11.0
        r = A().analyze(make_pos(
            headline_apr_pct=11.0,
            sleeves=[sleeve(12.0, 3_000_000.0, 5e6),
                     sleeve(8.0, 1_000_000.0, 5e6)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["weighted_avg_apr_pct"], 11.0)

    def test_zero_alloc_mean_fallback(self):
        # All allocations zero → simple mean of aprs: (12+8)/2 = 10.0
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(12.0, 0.0, 5e6), sleeve(8.0, 0.0, 5e6)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["weighted_avg_apr_pct"], 10.0)

    def test_single_sleeve_weighted_avg(self):
        r = A().analyze(make_pos(
            headline_apr_pct=15.0,
            sleeves=[sleeve(15.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["weighted_avg_apr_pct"], 15.0)

    def test_weighted_avg_finite(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertTrue(math.isfinite(r["weighted_avg_apr_pct"]))


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_dilution_pct(self):
        # headline 14, marginal 12.8 → dilution 1.2
        r = A().analyze(make_pos(
            headline_apr_pct=14.0,
            sleeves=[sleeve(20.0, 1e6, 40000.0), sleeve(8.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["dilution_pct"], 1.2)

    def test_dilution_pct_negative_marginal_above(self):
        # headline 8, marginal routes into 12% sleeve → dilution negative
        r = A().analyze(make_pos(
            headline_apr_pct=8.0,
            sleeves=[sleeve(12.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["dilution_pct"], -4.0)

    def test_dilution_ratio(self):
        # marginal/headline = 12.8/14 ≈ 0.9143
        r = A().analyze(make_pos(
            headline_apr_pct=14.0,
            sleeves=[sleeve(20.0, 1e6, 40000.0), sleeve(8.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["dilution_ratio"], round(12.8 / 14.0, 4))

    def test_dilution_ratio_one_when_aligned(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(r["dilution_ratio"], 1.0)

    def test_passthrough_headline(self):
        r = A().analyze(make_pos(headline_apr_pct=13.0))
        self.assertAlmostEqual(r["headline_apr_pct"], 13.0)

    def test_new_deposit_passthrough(self):
        r = A().analyze(make_pos(new_deposit_usd=250000.0))
        self.assertAlmostEqual(r["new_deposit_usd"], 250000.0)

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(
            headline_apr_pct=13.3333,
            sleeves=[sleeve(11.1111, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        for k in ("headline_apr_pct", "marginal_apr_pct",
                  "weighted_avg_apr_pct", "dilution_pct"):
            self.assertEqual(r[k], round(r[k], 4))

    def test_sleeve_count(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(12.0, 1e6, 5e6), sleeve(8.0, 1e6, 5e6),
                     sleeve(6.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertEqual(r["sleeve_count"], 3)

    def test_deployable_undeployed_sum_to_deposit(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, 1e6, 30000.0)],
            new_deposit_usd=100000.0))
        self.assertAlmostEqual(
            r["deployable_usd"] + r["undeployed_usd"], 100000.0)


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_marginal_above_headline(self):
        # dilution -4 < -0.5
        r = A().analyze(make_pos(
            headline_apr_pct=8.0,
            sleeves=[sleeve(12.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertEqual(r["classification"], "MARGINAL_ABOVE_HEADLINE")

    def test_marginal_above_boundary(self):
        # dilution -0.51 < -0.5: headline 10, marginal 10.51
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.51, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertEqual(r["classification"], "MARGINAL_ABOVE_HEADLINE")

    def test_aligned(self):
        # dilution 0.0, |0| <= 0.5
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertEqual(r["classification"], "ALIGNED")

    def test_aligned_boundary_positive(self):
        # dilution exactly 0.5
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(9.5, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertEqual(r["classification"], "ALIGNED")

    def test_aligned_boundary_negative(self):
        # dilution exactly -0.5
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.5, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertEqual(r["classification"], "ALIGNED")

    def test_minor_dilution(self):
        # dilution 2.5, <= 3
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(7.5, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertEqual(r["classification"], "MINOR_DILUTION")

    def test_minor_dilution_boundary(self):
        # dilution exactly 3
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(7.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertEqual(r["classification"], "MINOR_DILUTION")

    def test_moderate_dilution(self):
        # dilution 5, <= 8
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(5.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertEqual(r["classification"], "MODERATE_DILUTION")

    def test_moderate_dilution_boundary(self):
        # dilution exactly 8
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(2.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertEqual(r["classification"], "MODERATE_DILUTION")

    def test_severe_dilution(self):
        # dilution 9 > 8
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(1.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertEqual(r["classification"], "SEVERE_DILUTION")

    def test_severe_dilution_just_above(self):
        # dilution 8.01 > 8
        r = A().analyze(make_pos(
            headline_apr_pct=10.01,
            sleeves=[sleeve(2.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertEqual(r["classification"], "SEVERE_DILUTION")

    def test_severe_via_capacity_routing(self):
        # 20% sleeve tiny cap, deposit forced into 5% → severe dilution.
        # marginal = (1000*20 + 99000*5)/100000 = 5.15; dilution 8.85 > 8
        r = A().analyze(make_pos(
            headline_apr_pct=14.0,
            sleeves=[sleeve(20.0, 1e6, 1000.0), sleeve(5.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertEqual(r["classification"], "SEVERE_DILUTION")

    def test_classification_known_value(self):
        for pos in [
            make_pos(headline_apr_pct=8.0,
                     sleeves=[sleeve(12.0, 1e6, 5e6)]),
            make_pos(headline_apr_pct=10.0,
                     sleeves=[sleeve(10.0, 1e6, 5e6)]),
            make_pos(headline_apr_pct=10.0,
                     sleeves=[sleeve(7.5, 1e6, 5e6)]),
            make_pos(headline_apr_pct=10.0,
                     sleeves=[sleeve(5.0, 1e6, 5e6)]),
            make_pos(headline_apr_pct=10.0,
                     sleeves=[sleeve(1.0, 1e6, 5e6)]),
            make_pos(headline_apr_pct=0.0, sleeves=[]),
        ]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "MARGINAL_ABOVE_HEADLINE", "ALIGNED", "MINOR_DILUTION",
                "MODERATE_DILUTION", "SEVERE_DILUTION", "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_trust_marginal_above(self):
        r = A().analyze(make_pos(
            headline_apr_pct=8.0, sleeves=[sleeve(12.0, 1e6, 5e6)]))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_trust_aligned(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(10.0, 1e6, 5e6)]))
        self.assertEqual(r["recommendation"], "TRUST_HEADLINE")

    def test_discount_slightly_minor(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(7.5, 1e6, 5e6)]))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE_SLIGHTLY")

    def test_discount_moderate(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(5.0, 1e6, 5e6)]))
        self.assertEqual(r["recommendation"], "DISCOUNT_HEADLINE")

    def test_avoid_severe(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(1.0, 1e6, 5e6)]))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_insufficient_rec(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, sleeves=[]))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_aligned_flag(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(10.0, 1e6, 5e6)]))
        self.assertIn("ALIGNED", r["flags"])

    def test_minor_dilution_flag(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(7.5, 1e6, 5e6)]))
        self.assertIn("MINOR_DILUTION", r["flags"])

    def test_moderate_dilution_flag(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(5.0, 1e6, 5e6)]))
        self.assertIn("MODERATE_DILUTION", r["flags"])

    def test_severe_dilution_flag(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(1.0, 1e6, 5e6)]))
        self.assertIn("SEVERE_DILUTION", r["flags"])

    def test_marginal_above_headline_flag(self):
        r = A().analyze(make_pos(
            headline_apr_pct=8.0, sleeves=[sleeve(12.0, 1e6, 5e6)]))
        self.assertIn("MARGINAL_ABOVE_HEADLINE", r["flags"])

    def test_top_sleeve_constrained_flag(self):
        r = A().analyze(make_pos(
            headline_apr_pct=14.0,
            sleeves=[sleeve(20.0, 1e6, 1000.0), sleeve(8.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertIn("TOP_SLEEVE_CAPACITY_CONSTRAINED", r["flags"])

    def test_top_sleeve_constrained_flag_absent(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertNotIn("TOP_SLEEVE_CAPACITY_CONSTRAINED", r["flags"])

    def test_deposit_not_fully_absorbed_flag(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, 1e6, 50000.0)],
            new_deposit_usd=100000.0))
        self.assertIn("DEPOSIT_NOT_FULLY_ABSORBED", r["flags"])

    def test_deposit_fully_absorbed_no_flag(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, 1e6, 1e6)],
            new_deposit_usd=100000.0))
        self.assertNotIn("DEPOSIT_NOT_FULLY_ABSORBED", r["flags"])

    def test_headline_above_current_average_flag(self):
        # headline 14 > weighted avg 10 + 0.5 → flag
        r = A().analyze(make_pos(
            headline_apr_pct=14.0,
            sleeves=[sleeve(10.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertIn("HEADLINE_ABOVE_CURRENT_AVERAGE", r["flags"])

    def test_headline_above_current_average_absent(self):
        # headline equals weighted avg → no flag
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertNotIn("HEADLINE_ABOVE_CURRENT_AVERAGE", r["flags"])

    def test_sparse_sleeves_flag(self):
        # single sleeve → 0<1<2 → sparse
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertIn("SPARSE_SLEEVES", r["flags"])

    def test_sparse_sleeves_absent_two_sleeves(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, 1e6, 5e6), sleeve(8.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertNotIn("SPARSE_SLEEVES", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, sleeves=[]))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_one_classification_flag_only(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(5.0, 1e6, 5e6)]))
        class_flags = {"MARGINAL_ABOVE_HEADLINE", "ALIGNED", "MINOR_DILUTION",
                       "MODERATE_DILUTION", "SEVERE_DILUTION"}
        present = [f for f in r["flags"] if f in class_flags]
        self.assertEqual(len(present), 1)


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_sleeves(self):
        r = A().analyze(make_pos(headline_apr_pct=10.0, sleeves=[]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_missing_sleeves_key(self):
        r = A().analyze({"vault": "V", "headline_apr_pct": 10.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_headline_zero(self):
        r = A().analyze(make_pos(
            headline_apr_pct=0.0, sleeves=[sleeve(10.0, 1e6, 5e6)]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_headline_negative(self):
        r = A().analyze(make_pos(
            headline_apr_pct=-5.0, sleeves=[sleeve(10.0, 1e6, 5e6)]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_new_deposit_zero(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(10.0, 1e6, 5e6)],
            new_deposit_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_new_deposit_negative(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(10.0, 1e6, 5e6)],
            new_deposit_usd=-1000.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_non_finite_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("inf"),
                         "sleeves": [sleeve(10.0, 1e6, 5e6)]})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_nan_headline(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("nan"),
                         "sleeves": [sleeve(10.0, 1e6, 5e6)]})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_non_finite_sleeve_aprs(self):
        # both sleeves have non-finite apr → discarded → no valid sleeves
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(float("nan"), 1e6, 5e6),
                     sleeve(float("inf"), 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, sleeves=[]))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(headline_apr_pct=0.0, sleeves=[]))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_insufficient_none_fields(self):
        r = A().analyze({})
        self.assertIsNone(r["marginal_apr_pct"])
        self.assertIsNone(r["weighted_avg_apr_pct"])
        self.assertIsNone(r["dilution_ratio"])
        self.assertIsNone(r["top_sleeve_apr_pct"])
        self.assertIsNone(r["top_sleeve_capacity_remaining_usd"])
        self.assertIsNone(r["total_remaining_capacity_usd"])
        self.assertIsNone(r["deployable_usd"])
        self.assertIsNone(r["undeployed_usd"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("headline_apr_pct", "dilution_pct", "new_deposit_usd",
                  "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["fully_absorbed"])
        self.assertFalse(r["top_sleeve_constrained"])
        self.assertEqual(r["sleeve_count"], 0)

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_insufficient_has_all_keys(self):
        r = A().analyze({})
        valid = A().analyze(make_pos())
        self.assertEqual(set(r.keys()), set(valid.keys()))

    def test_valid_with_sleeves(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(10.0, 1e6, 5e6)]))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_sleeves_not_list_insufficient(self):
        r = A().analyze({"vault": "S", "headline_apr_pct": 10.0,
                         "sleeves": "notalist"})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_sleeves_non_dict_entries_skipped(self):
        # non-dict entries skipped; one valid dict remains
        r = A().analyze({"vault": "S", "headline_apr_pct": 10.0,
                         "sleeves": ["junk", 42, sleeve(10.0, 1e6, 5e6)]})
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["sleeve_count"], 1)


# ── scoring monotonicity & bounds ─────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_smaller_dilution_scores_higher(self):
        small = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(9.8, 1e6, 5e6)]))
        big = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(2.0, 1e6, 5e6)]))
        self.assertGreater(small["score"], big["score"])

    def test_marginal_above_high_score(self):
        r = A().analyze(make_pos(
            headline_apr_pct=8.0, sleeves=[sleeve(12.0, 1e6, 5e6)]))
        self.assertGreater(r["score"], 85.0)

    def test_aligned_high_score(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(10.0, 1e6, 5e6)]))
        self.assertGreater(r["score"], 85.0)

    def test_severe_dilution_low_score(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(1.0, 1e6, 5e6)]))
        self.assertLess(r["score"], 55.0)

    def test_zero_marginal_low_score(self):
        # no capacity → marginal 0 → very low score
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(10.0, 1e6, 0.0)],
            new_deposit_usd=100000.0))
        self.assertLess(r["score"], 40.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(
            headline_apr_pct=1e-9,
            sleeves=[sleeve(1e12, 1e6, 1e15)],
            new_deposit_usd=100000.0))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(
            headline_apr_pct=1e9,
            sleeves=[sleeve(0.0, 1e6, 1e15)],
            new_deposit_usd=100000.0))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [
            make_pos(headline_apr_pct=8.0, sleeves=[sleeve(12.0, 1e6, 5e6)]),
            make_pos(headline_apr_pct=10.0, sleeves=[sleeve(10.0, 1e6, 5e6)]),
            make_pos(headline_apr_pct=10.0, sleeves=[sleeve(7.5, 1e6, 5e6)]),
            make_pos(headline_apr_pct=10.0, sleeves=[sleeve(5.0, 1e6, 5e6)]),
            make_pos(headline_apr_pct=10.0, sleeves=[sleeve(1.0, 1e6, 5e6)]),
            make_pos(headline_apr_pct=0.0, sleeves=[]),
        ]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [
            make_pos(headline_apr_pct=10.0, sleeves=[sleeve(10.0, 1e6, 5e6)]),
            make_pos(headline_apr_pct=10.0, sleeves=[sleeve(1.0, 1e6, 5e6)]),
        ]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_marginal_equals_headline_full_score(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0, sleeves=[sleeve(10.0, 1e6, 5e6)]))
        self.assertAlmostEqual(r["score"], 100.0)

    def test_monotonic_decreasing_with_dilution(self):
        scores = []
        for apr in (10.0, 9.0, 8.0, 6.0, 3.0, 1.0):
            r = A().analyze(make_pos(
                headline_apr_pct=10.0, sleeves=[sleeve(apr, 1e6, 5e6)]))
            scores.append(r["score"])
        for a, b in zip(scores, scores[1:]):
            self.assertGreaterEqual(a, b)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Aligned", headline_apr_pct=10.0,
                     sleeves=[sleeve(10.0, 1e6, 5e6)]),
            make_pos(vault="Severe", headline_apr_pct=10.0,
                     sleeves=[sleeve(1.0, 1e6, 5e6)]),
            make_pos(vault="Mid", headline_apr_pct=10.0,
                     sleeves=[sleeve(5.0, 1e6, 5e6)]),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_aligned_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_aligned_vault"]],
                         max(scores.values()))

    def test_least_aligned_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["least_aligned_vault"]],
                         min(scores.values()))

    def test_most_aligned_is_aligned(self):
        self.assertEqual(self.res["aggregate"]["most_aligned_vault"],
                         "Aligned")

    def test_least_aligned_is_severe(self):
        self.assertEqual(self.res["aggregate"]["least_aligned_vault"],
                         "Severe")

    def test_severe_dilution_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["severe_dilution_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_aligned_vault"])
        self.assertIsNone(res["aggregate"]["least_aligned_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_empty_severe_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["severe_dilution_count"], 0)

    def test_empty_avg_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(headline_apr_pct=0.0, sleeves=[]),
            make_pos(headline_apr_pct=0.0, sleeves=[]),
        ])
        self.assertIsNone(res["aggregate"]["most_aligned_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["severe_dilution_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_aligned_vault"], "Solo")
        self.assertEqual(res["aggregate"]["least_aligned_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", headline_apr_pct=10.0,
                     sleeves=[sleeve(10.0, 1e6, 5e6)]),
            make_pos(vault="Ins", headline_apr_pct=0.0, sleeves=[]),
        ])
        scored = [p["score"] for p in res["positions"]
                  if p["classification"] != "INSUFFICIENT_DATA"]
        self.assertAlmostEqual(res["aggregate"]["avg_score"],
                               round(sum(scored) / len(scored), 2))

    def test_severe_count_multiple(self):
        res = A().analyze_portfolio([
            make_pos(vault="S1", headline_apr_pct=10.0,
                     sleeves=[sleeve(1.0, 1e6, 5e6)]),
            make_pos(vault="S2", headline_apr_pct=10.0,
                     sleeves=[sleeve(0.5, 1e6, 5e6)]),
            make_pos(vault="Aligned", headline_apr_pct=10.0,
                     sleeves=[sleeve(10.0, 1e6, 5e6)]),
        ])
        self.assertEqual(res["aggregate"]["severe_dilution_count"], 2)

    def test_aggregate_ignores_insufficient_for_ranking(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", headline_apr_pct=10.0,
                     sleeves=[sleeve(10.0, 1e6, 5e6)]),
            make_pos(vault="Ins", headline_apr_pct=0.0, sleeves=[]),
        ])
        self.assertEqual(res["aggregate"]["most_aligned_vault"], "Good")
        self.assertEqual(res["aggregate"]["least_aligned_vault"], "Good")


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
                         sleeves=[sleeve(1e12, 1e6, 1e15)]),
                make_pos(vault="ins", headline_apr_pct=0.0, sleeves=[]),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            json.loads(raw)

    def test_log_none_fields_serialize_null(self):
        res = A().analyze(make_pos(headline_apr_pct=0.0, sleeves=[]))
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
            "sleeves": [{"apr_pct": "10", "allocation_usd": "1000000",
                         "capacity_remaining_usd": "5000000"}],
            "new_deposit_usd": "100000",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_sleeve_fields(self):
        # allocation/capacity missing → default 0; apr present → valid
        r = A().analyze({
            "vault": "S",
            "headline_apr_pct": 10.0,
            "sleeves": [{"apr_pct": 10.0}],
            "new_deposit_usd": 100000.0,
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")
        # no capacity → all idle → marginal 0
        self.assertAlmostEqual(r["marginal_apr_pct"], 0.0)

    def test_sleeves_as_tuple(self):
        r = A().analyze({"vault": "S", "headline_apr_pct": 10.0,
                         "sleeves": (sleeve(10.0, 1e6, 5e6),),
                         "new_deposit_usd": 100000.0})
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_none_capacity_treated_zero(self):
        r = A().analyze({
            "vault": "S",
            "headline_apr_pct": 10.0,
            "sleeves": [{"apr_pct": 10.0, "allocation_usd": 1e6,
                         "capacity_remaining_usd": None}],
            "new_deposit_usd": 100000.0,
        })
        self.assertAlmostEqual(r["marginal_apr_pct"], 0.0)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(headline_apr_pct=0.0, sleeves=[]),
            make_pos(headline_apr_pct=10.0, sleeves=[sleeve(1.0, 1e6, 5e6)]),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [
            make_pos(),
            make_pos(headline_apr_pct=8.0, sleeves=[sleeve(12.0, 1e6, 5e6)]),
            make_pos(headline_apr_pct=10.0, sleeves=[sleeve(1.0, 1e6, 5e6)]),
            make_pos(headline_apr_pct=0.0, sleeves=[]),
            make_pos(headline_apr_pct=1e-9,
                     sleeves=[sleeve(1e12, 1e6, 1e15)]),
            make_pos(headline_apr_pct=1e12,
                     sleeves=[sleeve(1e-12, 1e6, 1e15)]),
            make_pos(headline_apr_pct=10.0,
                     sleeves=[sleeve(1e-12, 1e6, 5e6),
                              sleeve(1e12, 1e6, 5e6)]),
            make_pos(headline_apr_pct=10.0,
                     sleeves=[sleeve(-50.0, 1e6, 5e6)]),
        ]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(
            headline_apr_pct=1e12,
            sleeves=[sleeve(1e9, 1e6, 1e15)],
            new_deposit_usd=1e12))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_tiny_headline_no_inf(self):
        r = A().analyze(make_pos(
            headline_apr_pct=1e-12,
            sleeves=[sleeve(10.0, 1e6, 5e6)]))
        finite_check(self, r)

    def test_negative_apr_sleeve_no_crash(self):
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(-8.0, 1e6, 5e6)]))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_none_fields_are_none_or_finite(self):
        for pos in [
            make_pos(),
            make_pos(headline_apr_pct=0.0, sleeves=[]),
            make_pos(headline_apr_pct=10.0, sleeves=[sleeve(10.0, 1e6, 5e6)]),
        ]:
            r = A().analyze(pos)
            for k in ("marginal_apr_pct", "weighted_avg_apr_pct",
                      "dilution_ratio", "top_sleeve_apr_pct",
                      "top_sleeve_capacity_remaining_usd",
                      "total_remaining_capacity_usd", "deployable_usd",
                      "undeployed_usd"):
                v = r[k]
                if v is not None:
                    self.assertTrue(math.isfinite(v))

    def test_nan_headline_treated_as_insufficient(self):
        r = A().analyze({"vault": "X", "headline_apr_pct": float("nan"),
                         "sleeves": [sleeve(10.0, 1e6, 5e6)]})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        finite_check(self, r)

    def test_analyze_matches_portfolio_single(self):
        pos = make_pos(headline_apr_pct=10.0, sleeves=[sleeve(5.0, 1e6, 5e6)])
        single = A().analyze(pos)
        port = A().analyze_portfolio([pos])
        self.assertEqual(single["classification"],
                         port["positions"][0]["classification"])
        self.assertEqual(single["score"], port["positions"][0]["score"])

    def test_mixed_finite_nonfinite_sleeves(self):
        # one finite, one nan apr → keep finite only
        r = A().analyze(make_pos(
            headline_apr_pct=10.0,
            sleeves=[sleeve(float("nan"), 1e6, 5e6),
                     sleeve(10.0, 1e6, 5e6)],
            new_deposit_usd=100000.0))
        self.assertEqual(r["sleeve_count"], 1)
        self.assertAlmostEqual(r["marginal_apr_pct"], 10.0)


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

    def test_demo_includes_aligned_and_dilution(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("ALIGNED", classes)
        self.assertTrue(
            "SEVERE_DILUTION" in classes or "MODERATE_DILUTION" in classes
            or "MINOR_DILUTION" in classes)

    def test_demo_includes_severe(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("SEVERE_DILUTION", classes)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)

    def test_demo_aggregate_present(self):
        res = A().analyze_portfolio(_demo_positions())
        agg = res["aggregate"]
        self.assertIn("most_aligned_vault", agg)
        self.assertIn("least_aligned_vault", agg)


if __name__ == "__main__":
    unittest.main()
