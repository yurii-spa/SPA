"""
Tests for MP-1162: DeFiProtocolVaultManagementFeeAccrualAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_management_fee_accrual_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_management_fee_accrual_analyzer import (
    DeFiProtocolVaultManagementFeeAccrualAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    HIGH_MGMT_FEE_PCT,
    MODERATE_MGMT_FEE_PCT,
    LOW_MGMT_FEE_PCT,
    EXCESSIVE_MGMT_FEE_PCT,
    FEE_HALF_YIELD_PCT,
    DAYS_PER_YEAR,
    SENTINEL,
    LOG_PATH,
    LOG_CAP,
)


# fixtures

def make_pos(
    vault="USDC-Vault",
    management_fee_pct_annual=0.5,
    position_usd=10000.0,
    days_held=90.0,
    gross_apr_pct=8.0,
    accrual_basis_days=365.0,
):
    return {
        "vault": vault,
        "management_fee_pct_annual": management_fee_pct_annual,
        "position_usd": position_usd,
        "days_held": days_held,
        "gross_apr_pct": gross_apr_pct,
        "accrual_basis_days": accrual_basis_days,
    }


def A():
    return DeFiProtocolVaultManagementFeeAccrualAnalyzer()


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
        self.assertEqual(DAYS_PER_YEAR, 365.0)
        self.assertLess(LOW_MGMT_FEE_PCT, MODERATE_MGMT_FEE_PCT)
        self.assertLess(MODERATE_MGMT_FEE_PCT, HIGH_MGMT_FEE_PCT)
        self.assertLess(HIGH_MGMT_FEE_PCT, EXCESSIVE_MGMT_FEE_PCT)
        self.assertEqual(FEE_HALF_YIELD_PCT, 50.0)
        self.assertEqual(SENTINEL, 0.0)


# structural / contract tests

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "management_fee_pct_annual", "position_usd", "days_held",
            "gross_apr_pct", "accrual_basis_days", "accrued_fee_pct",
            "accrued_fee_usd", "annual_fee_drag_pct", "net_apr_pct",
            "fee_as_pct_of_gross_yield", "daily_fee_usd", "score",
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
        r = A().analyze({"token": "AltKey", "management_fee_pct_annual": 1.0,
                         "position_usd": 1000.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "management_fee_pct_annual": 1.0,
                         "position_usd": 1000.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"management_fee_pct_annual": 1.0,
                         "position_usd": 1000.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "HOLD_OK", "ACCEPTABLE", "REVIEW_FEE", "AVOID_HIGH_FEE",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})


# metrics correctness

class TestMetrics(unittest.TestCase):
    def test_fee_clamped_high(self):
        r = A().analyze(make_pos(management_fee_pct_annual=200.0))
        self.assertAlmostEqual(r["management_fee_pct_annual"], 100.0)

    def test_fee_clamped_low(self):
        r = A().analyze(make_pos(management_fee_pct_annual=-5.0,
                                 position_usd=1000.0))
        self.assertAlmostEqual(r["management_fee_pct_annual"], 0.0)

    def test_position_usd_negative_clamped(self):
        r = A().analyze(make_pos(position_usd=-100.0))
        self.assertAlmostEqual(r["position_usd"], 0.0)

    def test_days_held_negative_clamped(self):
        r = A().analyze(make_pos(days_held=-10.0))
        self.assertAlmostEqual(r["days_held"], 0.0)

    def test_accrued_fee_pct_calc(self):
        # 2% annual, 365/2 days, basis 365 -> 1.0%
        r = A().analyze(make_pos(management_fee_pct_annual=2.0,
                                 days_held=182.5, accrual_basis_days=365.0))
        self.assertAlmostEqual(r["accrued_fee_pct"], 1.0, places=4)

    def test_accrued_fee_usd_calc(self):
        # accrued 1% of 10000 = 100
        r = A().analyze(make_pos(management_fee_pct_annual=2.0,
                                 days_held=182.5, position_usd=10000.0))
        self.assertAlmostEqual(r["accrued_fee_usd"], 100.0, places=2)

    def test_accrued_fee_full_year(self):
        # 1% annual, 365 days -> 1.0%
        r = A().analyze(make_pos(management_fee_pct_annual=1.0,
                                 days_held=365.0, accrual_basis_days=365.0))
        self.assertAlmostEqual(r["accrued_fee_pct"], 1.0, places=4)

    def test_annual_fee_drag_equals_fee(self):
        r = A().analyze(make_pos(management_fee_pct_annual=1.5))
        self.assertAlmostEqual(r["annual_fee_drag_pct"], 1.5)

    def test_net_apr_calc(self):
        # gross 8, fee 0.5 -> net 7.5
        r = A().analyze(make_pos(gross_apr_pct=8.0,
                                 management_fee_pct_annual=0.5))
        self.assertAlmostEqual(r["net_apr_pct"], 7.5, places=4)

    def test_net_apr_can_be_negative(self):
        r = A().analyze(make_pos(gross_apr_pct=2.0,
                                 management_fee_pct_annual=5.0))
        self.assertAlmostEqual(r["net_apr_pct"], -3.0, places=4)

    def test_daily_fee_usd_calc(self):
        # 365% annual on 10000 -> 100/day; use 3.65% -> 1/day
        r = A().analyze(make_pos(management_fee_pct_annual=3.65,
                                 position_usd=10000.0))
        self.assertAlmostEqual(r["daily_fee_usd"], 1.0, places=4)

    def test_fee_as_pct_of_gross_yield_calc(self):
        # fee accrued pct vs gross yield period pct.
        # fee 2% annual over 365 days -> 2% accrued.
        # gross 8% annual over 365 days -> 8% gross yield.
        # 2/8 = 25%
        r = A().analyze(make_pos(management_fee_pct_annual=2.0,
                                 gross_apr_pct=8.0, days_held=365.0))
        self.assertAlmostEqual(r["fee_as_pct_of_gross_yield"], 25.0, places=2)

    def test_fee_as_pct_of_gross_yield_sentinel_zero_gross(self):
        r = A().analyze(make_pos(gross_apr_pct=0.0,
                                 management_fee_pct_annual=1.0))
        self.assertEqual(r["fee_as_pct_of_gross_yield"], SENTINEL)

    def test_fee_as_pct_of_gross_yield_sentinel_negative_gross(self):
        r = A().analyze(make_pos(gross_apr_pct=-5.0,
                                 management_fee_pct_annual=1.0))
        self.assertEqual(r["fee_as_pct_of_gross_yield"], SENTINEL)

    def test_accrual_basis_default_when_zero(self):
        # accrual_basis_days=0 -> falls back to 365
        r = A().analyze(make_pos(management_fee_pct_annual=1.0,
                                 days_held=365.0, accrual_basis_days=0.0))
        self.assertAlmostEqual(r["accrual_basis_days"], 365.0)
        self.assertAlmostEqual(r["accrued_fee_pct"], 1.0, places=4)

    def test_zero_position_no_crash(self):
        r = A().analyze(make_pos(position_usd=0.0,
                                 management_fee_pct_annual=1.0))
        self.assertAlmostEqual(r["accrued_fee_usd"], 0.0)
        self.assertAlmostEqual(r["daily_fee_usd"], 0.0)

    def test_zero_days_held_zero_accrued(self):
        r = A().analyze(make_pos(days_held=0.0,
                                 management_fee_pct_annual=2.0))
        self.assertAlmostEqual(r["accrued_fee_pct"], 0.0)


# classification behaviour

class TestClassification(unittest.TestCase):
    def test_low_fee(self):
        r = A().analyze(make_pos(management_fee_pct_annual=0.3))
        self.assertEqual(r["classification"], "LOW_FEE")

    def test_moderate_fee(self):
        r = A().analyze(make_pos(management_fee_pct_annual=1.0))
        self.assertEqual(r["classification"], "MODERATE_FEE")

    def test_high_fee(self):
        r = A().analyze(make_pos(management_fee_pct_annual=2.0))
        self.assertEqual(r["classification"], "HIGH_FEE")

    def test_excessive_fee(self):
        r = A().analyze(make_pos(management_fee_pct_annual=4.0))
        self.assertEqual(r["classification"], "EXCESSIVE_FEE")

    def test_excessive_above(self):
        r = A().analyze(make_pos(management_fee_pct_annual=10.0))
        self.assertEqual(r["classification"], "EXCESSIVE_FEE")

    def test_low_fee_boundary(self):
        # just below MODERATE is still LOW
        r = A().analyze(make_pos(management_fee_pct_annual=0.99))
        self.assertEqual(r["classification"], "LOW_FEE")

    def test_classification_known_value(self):
        for fee in [0.1, 1.0, 2.0, 4.0, 8.0]:
            r = A().analyze(make_pos(management_fee_pct_annual=fee))
            self.assertIn(r["classification"], {
                "LOW_FEE", "MODERATE_FEE", "HIGH_FEE", "EXCESSIVE_FEE",
                "INSUFFICIENT_DATA",
            })


# recommendation behaviour

class TestRecommendation(unittest.TestCase):
    def test_hold_ok_when_low(self):
        r = A().analyze(make_pos(management_fee_pct_annual=0.3))
        self.assertEqual(r["recommendation"], "HOLD_OK")

    def test_acceptable_when_moderate(self):
        r = A().analyze(make_pos(management_fee_pct_annual=1.0))
        self.assertEqual(r["recommendation"], "ACCEPTABLE")

    def test_review_when_high(self):
        r = A().analyze(make_pos(management_fee_pct_annual=2.0))
        self.assertEqual(r["recommendation"], "REVIEW_FEE")

    def test_avoid_when_excessive(self):
        r = A().analyze(make_pos(management_fee_pct_annual=5.0))
        self.assertEqual(r["recommendation"], "AVOID_HIGH_FEE")

    def test_hold_ok_when_insufficient(self):
        r = A().analyze(make_pos(management_fee_pct_annual=0.0,
                                 position_usd=0.0))
        self.assertEqual(r["recommendation"], "HOLD_OK")


# flags

class TestFlags(unittest.TestCase):
    def test_zero_management_fee_flag(self):
        r = A().analyze(make_pos(management_fee_pct_annual=0.0,
                                 position_usd=1000.0))
        self.assertIn("ZERO_MANAGEMENT_FEE", r["flags"])

    def test_low_management_fee_flag(self):
        r = A().analyze(make_pos(management_fee_pct_annual=0.3))
        self.assertIn("LOW_MANAGEMENT_FEE", r["flags"])

    def test_low_management_fee_flag_absent(self):
        r = A().analyze(make_pos(management_fee_pct_annual=1.0))
        self.assertNotIn("LOW_MANAGEMENT_FEE", r["flags"])

    def test_high_management_fee_flag(self):
        r = A().analyze(make_pos(management_fee_pct_annual=2.0))
        self.assertIn("HIGH_MANAGEMENT_FEE", r["flags"])

    def test_high_management_fee_flag_boundary(self):
        r = A().analyze(make_pos(management_fee_pct_annual=HIGH_MGMT_FEE_PCT))
        self.assertIn("HIGH_MANAGEMENT_FEE", r["flags"])

    def test_high_management_fee_flag_absent(self):
        r = A().analyze(make_pos(management_fee_pct_annual=1.5))
        self.assertNotIn("HIGH_MANAGEMENT_FEE", r["flags"])

    def test_excessive_fee_flag(self):
        r = A().analyze(make_pos(management_fee_pct_annual=4.0))
        self.assertIn("EXCESSIVE_FEE", r["flags"])

    def test_excessive_fee_flag_absent(self):
        r = A().analyze(make_pos(management_fee_pct_annual=2.5))
        self.assertNotIn("EXCESSIVE_FEE", r["flags"])

    def test_negative_net_apr_flag(self):
        r = A().analyze(make_pos(gross_apr_pct=1.0,
                                 management_fee_pct_annual=3.0))
        self.assertIn("NEGATIVE_NET_APR", r["flags"])

    def test_negative_net_apr_flag_absent(self):
        r = A().analyze(make_pos(gross_apr_pct=8.0,
                                 management_fee_pct_annual=0.5))
        self.assertNotIn("NEGATIVE_NET_APR", r["flags"])

    def test_fee_exceeds_half_yield_flag(self):
        # fee 5% annual, gross 8% -> fee/gross = 62.5% > 50
        r = A().analyze(make_pos(management_fee_pct_annual=5.0,
                                 gross_apr_pct=8.0, days_held=365.0))
        self.assertIn("FEE_EXCEEDS_HALF_YIELD", r["flags"])

    def test_fee_exceeds_half_yield_flag_absent(self):
        # fee 1% annual, gross 8% -> 12.5% < 50
        r = A().analyze(make_pos(management_fee_pct_annual=1.0,
                                 gross_apr_pct=8.0, days_held=365.0))
        self.assertNotIn("FEE_EXCEEDS_HALF_YIELD", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(management_fee_pct_annual=0.0,
                                 position_usd=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])


# insufficient data

class TestInsufficientData(unittest.TestCase):
    def test_no_fee_no_position(self):
        r = A().analyze(make_pos(management_fee_pct_annual=0.0,
                                 position_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(management_fee_pct_annual=0.0,
                                 position_usd=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation_hold_ok(self):
        r = A().analyze(make_pos(management_fee_pct_annual=0.0,
                                 position_usd=0.0))
        self.assertEqual(r["recommendation"], "HOLD_OK")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_fee_present_is_sufficient(self):
        r = A().analyze(make_pos(management_fee_pct_annual=1.0,
                                 position_usd=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_position_present_is_sufficient(self):
        r = A().analyze(make_pos(management_fee_pct_annual=0.0,
                                 position_usd=1000.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)


# scoring monotonicity

class TestScoring(unittest.TestCase):
    def test_lower_fee_scores_higher(self):
        low = A().analyze(make_pos(management_fee_pct_annual=0.2))
        high = A().analyze(make_pos(management_fee_pct_annual=1.8))
        self.assertGreater(low["score"], high["score"])

    def test_low_fee_scores_high(self):
        r = A().analyze(make_pos(management_fee_pct_annual=0.1,
                                 gross_apr_pct=10.0))
        self.assertGreater(r["score"], 85.0)

    def test_excessive_fee_scores_low(self):
        r = A().analyze(make_pos(management_fee_pct_annual=8.0,
                                 gross_apr_pct=4.0))
        self.assertLess(r["score"], 55.0)

    def test_higher_net_ratio_scores_higher(self):
        # same fee, higher gross -> more of yield survives -> higher score
        high_gross = A().analyze(make_pos(management_fee_pct_annual=1.0,
                                          gross_apr_pct=20.0))
        low_gross = A().analyze(make_pos(management_fee_pct_annual=1.0,
                                         gross_apr_pct=2.0))
        self.assertGreater(high_gross["score"], low_gross["score"])

    def test_positive_net_apr_scores_higher(self):
        pos = A().analyze(make_pos(management_fee_pct_annual=1.0,
                                   gross_apr_pct=8.0))
        neg = A().analyze(make_pos(management_fee_pct_annual=1.0,
                                   gross_apr_pct=0.5))
        self.assertGreater(pos["score"], neg["score"])

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(management_fee_pct_annual=100.0,
                                 gross_apr_pct=1000.0, position_usd=1e9))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(management_fee_pct_annual=100.0,
                                 gross_apr_pct=-50.0))
        self.assertGreaterEqual(r["score"], 0.0)


# portfolio aggregate

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Cheap", management_fee_pct_annual=0.2,
                     gross_apr_pct=10.0),
            make_pos(vault="Expensive", management_fee_pct_annual=5.0,
                     gross_apr_pct=4.0),
            make_pos(vault="Mid", management_fee_pct_annual=1.0,
                     gross_apr_pct=8.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_cheapest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["cheapest_vault"]], max(scores.values()))

    def test_most_expensive_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_expensive_vault"]],
                         min(scores.values()))

    def test_cheapest_is_cheap(self):
        self.assertEqual(self.res["aggregate"]["cheapest_vault"], "Cheap")

    def test_most_expensive_is_expensive(self):
        self.assertEqual(self.res["aggregate"]["most_expensive_vault"],
                         "Expensive")

    def test_high_fee_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["high_fee_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["cheapest_vault"])
        self.assertIsNone(res["aggregate"]["most_expensive_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(management_fee_pct_annual=0.0, position_usd=0.0),
            make_pos(management_fee_pct_annual=0.0, position_usd=0.0),
        ])
        self.assertIsNone(res["aggregate"]["cheapest_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["cheapest_vault"], "Solo")
        self.assertEqual(res["aggregate"]["most_expensive_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_high_fee_count_counts_excessive(self):
        res = A().analyze_portfolio([
            make_pos(vault="X", management_fee_pct_annual=5.0),
        ])
        self.assertEqual(res["aggregate"]["high_fee_count"], 1)


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
                make_pos(vault="big", management_fee_pct_annual=100.0,
                         position_usd=1e9, gross_apr_pct=1000.0),
                make_pos(vault="ins", management_fee_pct_annual=0.0,
                         position_usd=0.0),
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
            "management_fee_pct_annual": "1.0",
            "position_usd": "10000",
            "days_held": "90",
            "gross_apr_pct": "8",
            "accrual_basis_days": "365",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "management_fee_pct_annual": 1.0,
                         "position_usd": 1000.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(management_fee_pct_annual=0.0, position_usd=0.0),
            make_pos(management_fee_pct_annual=5.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(management_fee_pct_annual=0.0, position_usd=0.0),
                    make_pos(days_held=0.0),
                    make_pos(management_fee_pct_annual=200.0),
                    make_pos(gross_apr_pct=0.0),
                    make_pos(gross_apr_pct=-50.0),
                    make_pos(accrual_basis_days=0.0),
                    make_pos(position_usd=-100.0)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(management_fee_pct_annual=100.0,
                                 position_usd=1e12, gross_apr_pct=1e6,
                                 days_held=1e6))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_gross_apr_no_crash(self):
        r = A().analyze(make_pos(gross_apr_pct=-10.0))
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
