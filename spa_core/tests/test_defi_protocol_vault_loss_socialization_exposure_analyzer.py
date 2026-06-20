"""
Tests for MP-1163: DeFiProtocolVaultLossSocializationExposureAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_loss_socialization_exposure_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_loss_socialization_exposure_analyzer import (
    DeFiProtocolVaultLossSocializationExposureAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    HIGH_HAIRCUT_PCT,
    MODERATE_HAIRCUT_PCT,
    LOW_COVERAGE_PCT,
    CONCENTRATED_SHARE_PCT,
    SUBORDINATED_LOSS_MULTIPLIER,
    SENTINEL,
    LOG_PATH,
    LOG_CAP,
)


# fixtures

def make_pos(
    vault="USDC-Vault",
    vault_tvl_usd=1000000.0,
    position_usd=10000.0,
    outstanding_bad_debt_usd=0.0,
    insurance_buffer_usd=0.0,
    has_loss_backstop=False,
    subordinated_tranche=False,
):
    return {
        "vault": vault,
        "vault_tvl_usd": vault_tvl_usd,
        "position_usd": position_usd,
        "outstanding_bad_debt_usd": outstanding_bad_debt_usd,
        "insurance_buffer_usd": insurance_buffer_usd,
        "has_loss_backstop": has_loss_backstop,
        "subordinated_tranche": subordinated_tranche,
    }


def A():
    return DeFiProtocolVaultLossSocializationExposureAnalyzer()


def finite_check(testcase, result):
    for v in result.values():
        if isinstance(v, float):
            testcase.assertTrue(math.isfinite(v), f"non-finite: {v}")


# helper-function tests

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

    def test_clamp_within(self):
        self.assertEqual(_clamp(5, 0, 10), 5)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1, 0, 10), 0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(11, 0, 10), 10)

    def test_clamp_exact_bounds(self):
        self.assertEqual(_clamp(0, 0, 10), 0)
        self.assertEqual(_clamp(10, 0, 10), 10)

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

    def test_constants_sane(self):
        self.assertLess(MODERATE_HAIRCUT_PCT, HIGH_HAIRCUT_PCT)
        self.assertEqual(LOW_COVERAGE_PCT, 50.0)
        self.assertEqual(CONCENTRATED_SHARE_PCT, 25.0)
        self.assertEqual(SUBORDINATED_LOSS_MULTIPLIER, 2.0)
        self.assertEqual(SENTINEL, 0.0)


# structural / contract tests

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "vault_tvl_usd", "position_usd",
            "outstanding_bad_debt_usd", "insurance_buffer_usd",
            "has_loss_backstop", "subordinated_tranche", "position_share_pct",
            "uncovered_loss_usd", "buffer_coverage_pct", "my_loss_exposure_usd",
            "estimated_share_price_haircut_pct", "score", "classification",
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
        r = A().analyze({"token": "AltKey", "vault_tvl_usd": 1000.0,
                         "position_usd": 100.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "vault_tvl_usd": 1000.0, "position_usd": 100.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"vault_tvl_usd": 1000.0, "position_usd": 100.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "HOLD", "HOLD_WITH_CAUTION", "REDUCE_EXPOSURE", "EXIT",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_bool_fields(self):
        self.assertIsInstance(self.r["has_loss_backstop"], bool)
        self.assertIsInstance(self.r["subordinated_tranche"], bool)


# metrics correctness

class TestMetrics(unittest.TestCase):
    def test_position_share_calc(self):
        # 10000 / 1000000 * 100 = 1%
        r = A().analyze(make_pos(vault_tvl_usd=1000000.0, position_usd=10000.0))
        self.assertAlmostEqual(r["position_share_pct"], 1.0, places=4)

    def test_position_share_sentinel_zero_tvl(self):
        # tvl 0 but position > 0 -> still sufficient, share sentinel 0
        r = A().analyze(make_pos(vault_tvl_usd=0.0, position_usd=10000.0))
        self.assertEqual(r["position_share_pct"], SENTINEL)

    def test_position_share_clamped_100(self):
        r = A().analyze(make_pos(vault_tvl_usd=1000.0, position_usd=5000.0))
        self.assertLessEqual(r["position_share_pct"], 100.0)

    def test_uncovered_loss_calc(self):
        # bad debt 300k, buffer 50k -> 250k uncovered
        r = A().analyze(make_pos(outstanding_bad_debt_usd=300000.0,
                                 insurance_buffer_usd=50000.0))
        self.assertAlmostEqual(r["uncovered_loss_usd"], 250000.0, places=2)

    def test_uncovered_loss_zero_when_covered(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=100000.0,
                                 insurance_buffer_usd=200000.0))
        self.assertAlmostEqual(r["uncovered_loss_usd"], 0.0)

    def test_uncovered_loss_never_negative(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=10000.0,
                                 insurance_buffer_usd=1000000.0))
        self.assertGreaterEqual(r["uncovered_loss_usd"], 0.0)

    def test_buffer_coverage_calc(self):
        # buffer 50k / debt 100k * 100 = 50%
        r = A().analyze(make_pos(outstanding_bad_debt_usd=100000.0,
                                 insurance_buffer_usd=50000.0))
        self.assertAlmostEqual(r["buffer_coverage_pct"], 50.0, places=2)

    def test_buffer_coverage_clamped_100(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=100000.0,
                                 insurance_buffer_usd=500000.0))
        self.assertLessEqual(r["buffer_coverage_pct"], 100.0)

    def test_buffer_coverage_sentinel_no_debt(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=0.0,
                                 insurance_buffer_usd=50000.0))
        self.assertEqual(r["buffer_coverage_pct"], SENTINEL)

    def test_my_loss_exposure_calc(self):
        # share 1% of 250k uncovered = 2500
        r = A().analyze(make_pos(vault_tvl_usd=1000000.0, position_usd=10000.0,
                                 outstanding_bad_debt_usd=300000.0,
                                 insurance_buffer_usd=50000.0))
        self.assertAlmostEqual(r["my_loss_exposure_usd"], 2500.0, places=2)

    def test_my_loss_exposure_subordinated_amplified(self):
        senior = A().analyze(make_pos(vault_tvl_usd=1000000.0,
                                      position_usd=10000.0,
                                      outstanding_bad_debt_usd=300000.0,
                                      insurance_buffer_usd=50000.0,
                                      subordinated_tranche=False))
        junior = A().analyze(make_pos(vault_tvl_usd=1000000.0,
                                      position_usd=10000.0,
                                      outstanding_bad_debt_usd=300000.0,
                                      insurance_buffer_usd=50000.0,
                                      subordinated_tranche=True))
        self.assertGreater(junior["my_loss_exposure_usd"],
                           senior["my_loss_exposure_usd"])

    def test_my_loss_exposure_capped_at_position(self):
        # huge uncovered loss, large share, subordinated -> capped at position
        r = A().analyze(make_pos(vault_tvl_usd=100000.0, position_usd=80000.0,
                                 outstanding_bad_debt_usd=100000.0,
                                 insurance_buffer_usd=0.0,
                                 subordinated_tranche=True))
        self.assertLessEqual(r["my_loss_exposure_usd"], r["position_usd"])

    def test_my_loss_exposure_zero_no_loss(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=0.0))
        self.assertAlmostEqual(r["my_loss_exposure_usd"], 0.0)

    def test_haircut_calc(self):
        # uncovered 250k / tvl 1M * 100 = 25%
        r = A().analyze(make_pos(vault_tvl_usd=1000000.0,
                                 outstanding_bad_debt_usd=300000.0,
                                 insurance_buffer_usd=50000.0))
        self.assertAlmostEqual(r["estimated_share_price_haircut_pct"], 25.0,
                               places=2)

    def test_haircut_zero_no_loss(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=0.0))
        self.assertAlmostEqual(r["estimated_share_price_haircut_pct"], 0.0)

    def test_haircut_sentinel_zero_tvl(self):
        r = A().analyze(make_pos(vault_tvl_usd=0.0, position_usd=10000.0,
                                 outstanding_bad_debt_usd=100000.0))
        self.assertEqual(r["estimated_share_price_haircut_pct"], SENTINEL)

    def test_tvl_negative_clamped(self):
        r = A().analyze(make_pos(vault_tvl_usd=-100.0, position_usd=1000.0))
        self.assertAlmostEqual(r["vault_tvl_usd"], 0.0)

    def test_position_negative_clamped(self):
        r = A().analyze(make_pos(position_usd=-100.0))
        self.assertAlmostEqual(r["position_usd"], 0.0)

    def test_bad_debt_negative_clamped(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=-100.0))
        self.assertAlmostEqual(r["outstanding_bad_debt_usd"], 0.0)


# classification behaviour

class TestClassification(unittest.TestCase):
    def test_low_no_loss(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=0.0))
        self.assertEqual(r["classification"], "LOW")

    def test_moderate(self):
        # small uncovered: haircut between 0 and MODERATE (1%)
        r = A().analyze(make_pos(vault_tvl_usd=1000000.0,
                                 outstanding_bad_debt_usd=5000.0,
                                 insurance_buffer_usd=0.0))
        self.assertEqual(r["classification"], "MODERATE")

    def test_elevated(self):
        # haircut between MODERATE (1%) and HIGH (5%)
        r = A().analyze(make_pos(vault_tvl_usd=1000000.0,
                                 outstanding_bad_debt_usd=30000.0,
                                 insurance_buffer_usd=0.0))
        self.assertEqual(r["classification"], "ELEVATED")

    def test_high_loss_exposure(self):
        # haircut >= 5%
        r = A().analyze(make_pos(vault_tvl_usd=1000000.0,
                                 outstanding_bad_debt_usd=200000.0,
                                 insurance_buffer_usd=0.0))
        self.assertEqual(r["classification"], "HIGH_LOSS_EXPOSURE")

    def test_classification_known_value(self):
        for debt in [0.0, 5000.0, 30000.0, 200000.0]:
            r = A().analyze(make_pos(vault_tvl_usd=1000000.0,
                                     outstanding_bad_debt_usd=debt))
            self.assertIn(r["classification"], {
                "LOW", "MODERATE", "ELEVATED", "HIGH_LOSS_EXPOSURE",
                "INSUFFICIENT_DATA",
            })


# recommendation behaviour

class TestRecommendation(unittest.TestCase):
    def test_hold_when_low(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=0.0))
        self.assertEqual(r["recommendation"], "HOLD")

    def test_hold_with_caution_when_moderate(self):
        r = A().analyze(make_pos(vault_tvl_usd=1000000.0,
                                 outstanding_bad_debt_usd=5000.0))
        self.assertEqual(r["recommendation"], "HOLD_WITH_CAUTION")

    def test_reduce_when_elevated(self):
        r = A().analyze(make_pos(vault_tvl_usd=1000000.0,
                                 outstanding_bad_debt_usd=30000.0))
        self.assertEqual(r["recommendation"], "REDUCE_EXPOSURE")

    def test_exit_when_high(self):
        r = A().analyze(make_pos(vault_tvl_usd=1000000.0,
                                 outstanding_bad_debt_usd=200000.0))
        self.assertEqual(r["recommendation"], "EXIT")

    def test_hold_when_insufficient(self):
        r = A().analyze(make_pos(vault_tvl_usd=0.0, position_usd=0.0))
        self.assertEqual(r["recommendation"], "HOLD")


# flags

class TestFlags(unittest.TestCase):
    def test_no_bad_debt_flag(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=0.0))
        self.assertIn("NO_BAD_DEBT", r["flags"])

    def test_no_bad_debt_flag_absent(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=10000.0))
        self.assertNotIn("NO_BAD_DEBT", r["flags"])

    def test_fully_covered_flag(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=10000.0,
                                 insurance_buffer_usd=50000.0))
        self.assertIn("FULLY_COVERED", r["flags"])

    def test_partially_covered_flag(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=100000.0,
                                 insurance_buffer_usd=30000.0))
        self.assertIn("PARTIALLY_COVERED", r["flags"])

    def test_uncovered_loss_flag(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=100000.0,
                                 insurance_buffer_usd=30000.0))
        self.assertIn("UNCOVERED_LOSS", r["flags"])

    def test_uncovered_loss_flag_absent_when_covered(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=10000.0,
                                 insurance_buffer_usd=50000.0))
        self.assertNotIn("UNCOVERED_LOSS", r["flags"])

    def test_has_backstop_flag(self):
        r = A().analyze(make_pos(has_loss_backstop=True))
        self.assertIn("HAS_BACKSTOP", r["flags"])
        self.assertNotIn("NO_BACKSTOP", r["flags"])

    def test_no_backstop_flag(self):
        r = A().analyze(make_pos(has_loss_backstop=False))
        self.assertIn("NO_BACKSTOP", r["flags"])
        self.assertNotIn("HAS_BACKSTOP", r["flags"])

    def test_subordinated_tranche_flag(self):
        r = A().analyze(make_pos(subordinated_tranche=True))
        self.assertIn("SUBORDINATED_TRANCHE", r["flags"])

    def test_subordinated_tranche_flag_absent(self):
        r = A().analyze(make_pos(subordinated_tranche=False))
        self.assertNotIn("SUBORDINATED_TRANCHE", r["flags"])

    def test_large_haircut_flag(self):
        r = A().analyze(make_pos(vault_tvl_usd=1000000.0,
                                 outstanding_bad_debt_usd=200000.0))
        self.assertIn("LARGE_HAIRCUT", r["flags"])

    def test_large_haircut_flag_absent(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=0.0))
        self.assertNotIn("LARGE_HAIRCUT", r["flags"])

    def test_concentrated_position_flag(self):
        # share >= 25%
        r = A().analyze(make_pos(vault_tvl_usd=100000.0, position_usd=50000.0))
        self.assertIn("CONCENTRATED_POSITION", r["flags"])

    def test_concentrated_position_flag_absent(self):
        r = A().analyze(make_pos(vault_tvl_usd=1000000.0, position_usd=10000.0))
        self.assertNotIn("CONCENTRATED_POSITION", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(vault_tvl_usd=0.0, position_usd=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])


# insufficient data

class TestInsufficientData(unittest.TestCase):
    def test_no_vault_no_position(self):
        r = A().analyze(make_pos(vault_tvl_usd=0.0, position_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(vault_tvl_usd=0.0, position_usd=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation_hold(self):
        r = A().analyze(make_pos(vault_tvl_usd=0.0, position_usd=0.0))
        self.assertEqual(r["recommendation"], "HOLD")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_tvl_present_is_sufficient(self):
        r = A().analyze(make_pos(vault_tvl_usd=1000.0, position_usd=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_position_present_is_sufficient(self):
        r = A().analyze(make_pos(vault_tvl_usd=0.0, position_usd=1000.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)


# scoring monotonicity

class TestScoring(unittest.TestCase):
    def test_lower_haircut_scores_higher(self):
        low = A().analyze(make_pos(vault_tvl_usd=1000000.0,
                                   outstanding_bad_debt_usd=5000.0))
        high = A().analyze(make_pos(vault_tvl_usd=1000000.0,
                                    outstanding_bad_debt_usd=200000.0))
        self.assertGreater(low["score"], high["score"])

    def test_safe_vault_scores_high(self):
        r = A().analyze(make_pos(outstanding_bad_debt_usd=0.0,
                                 has_loss_backstop=True,
                                 subordinated_tranche=False))
        self.assertGreater(r["score"], 85.0)

    def test_risky_vault_scores_low(self):
        r = A().analyze(make_pos(vault_tvl_usd=1000000.0,
                                 outstanding_bad_debt_usd=300000.0,
                                 insurance_buffer_usd=0.0,
                                 has_loss_backstop=False,
                                 subordinated_tranche=True))
        self.assertLess(r["score"], 55.0)

    def test_higher_coverage_scores_higher(self):
        high_cov = A().analyze(make_pos(vault_tvl_usd=1000000.0,
                                        outstanding_bad_debt_usd=100000.0,
                                        insurance_buffer_usd=90000.0))
        low_cov = A().analyze(make_pos(vault_tvl_usd=1000000.0,
                                       outstanding_bad_debt_usd=100000.0,
                                       insurance_buffer_usd=10000.0))
        self.assertGreater(high_cov["score"], low_cov["score"])

    def test_backstop_scores_higher(self):
        with_bs = A().analyze(make_pos(has_loss_backstop=True))
        without_bs = A().analyze(make_pos(has_loss_backstop=False))
        self.assertGreater(with_bs["score"], without_bs["score"])

    def test_senior_scores_higher_than_junior(self):
        senior = A().analyze(make_pos(subordinated_tranche=False))
        junior = A().analyze(make_pos(subordinated_tranche=True))
        self.assertGreater(senior["score"], junior["score"])

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(vault_tvl_usd=1000.0, position_usd=1e9,
                                 outstanding_bad_debt_usd=1e9,
                                 subordinated_tranche=True))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(vault_tvl_usd=1000.0,
                                 outstanding_bad_debt_usd=1e9,
                                 subordinated_tranche=True))
        self.assertGreaterEqual(r["score"], 0.0)


# portfolio aggregate

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Safe", outstanding_bad_debt_usd=0.0,
                     has_loss_backstop=True),
            make_pos(vault="Risky", vault_tvl_usd=1000000.0,
                     outstanding_bad_debt_usd=300000.0,
                     insurance_buffer_usd=0.0, subordinated_tranche=True),
            make_pos(vault="Mid", vault_tvl_usd=1000000.0,
                     outstanding_bad_debt_usd=20000.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_safest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["safest_vault"]], max(scores.values()))

    def test_riskiest_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["riskiest_vault"]], min(scores.values()))

    def test_safest_is_safe(self):
        self.assertEqual(self.res["aggregate"]["safest_vault"], "Safe")

    def test_riskiest_is_risky(self):
        self.assertEqual(self.res["aggregate"]["riskiest_vault"], "Risky")

    def test_high_exposure_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["high_exposure_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["safest_vault"])
        self.assertIsNone(res["aggregate"]["riskiest_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(vault_tvl_usd=0.0, position_usd=0.0),
            make_pos(vault_tvl_usd=0.0, position_usd=0.0),
        ])
        self.assertIsNone(res["aggregate"]["safest_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["safest_vault"], "Solo")
        self.assertEqual(res["aggregate"]["riskiest_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_high_exposure_count_counts_classification(self):
        res = A().analyze_portfolio([
            make_pos(vault="H", vault_tvl_usd=1000000.0,
                     outstanding_bad_debt_usd=300000.0),
        ])
        self.assertEqual(res["aggregate"]["high_exposure_count"], 1)


# logging

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
                make_pos(vault="big", vault_tvl_usd=1000.0, position_usd=1e9,
                         outstanding_bad_debt_usd=1e9,
                         subordinated_tranche=True),
                make_pos(vault="ins", vault_tvl_usd=0.0, position_usd=0.0),
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

    def test_log_does_not_touch_production(self):
        before = os.path.exists(LOG_PATH)
        A().analyze(make_pos())
        after = os.path.exists(LOG_PATH)
        self.assertEqual(before, after)


# robustness

class TestRobustness(unittest.TestCase):
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "vault": "S",
            "vault_tvl_usd": "1000000",
            "position_usd": "10000",
            "outstanding_bad_debt_usd": "5000",
            "insurance_buffer_usd": "1000",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "vault_tvl_usd": 1000.0,
                         "position_usd": 100.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(vault_tvl_usd=0.0, position_usd=0.0),
            make_pos(outstanding_bad_debt_usd=300000.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(vault_tvl_usd=0.0, position_usd=0.0),
                    make_pos(outstanding_bad_debt_usd=0.0),
                    make_pos(vault_tvl_usd=0.0, position_usd=1000.0),
                    make_pos(outstanding_bad_debt_usd=1e12,
                             insurance_buffer_usd=0.0),
                    make_pos(subordinated_tranche=True),
                    make_pos(vault_tvl_usd=-100.0),
                    make_pos(position_usd=-100.0)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(vault_tvl_usd=1e12, position_usd=1e12,
                                 outstanding_bad_debt_usd=1e12,
                                 insurance_buffer_usd=1e6))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_zero_tvl_with_position_no_crash(self):
        r = A().analyze(make_pos(vault_tvl_usd=0.0, position_usd=10000.0,
                                 outstanding_bad_debt_usd=50000.0))
        self.assertIn("classification", r)
        finite_check(self, r)


# CLI smoke

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

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
