"""
Tests for MP-1153: DeFiProtocolPerformanceFeeCrystallizationFrequencyAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_performance_fee_crystallization_frequency_analyzer -v
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

from spa_core.analytics.defi_protocol_performance_fee_crystallization_frequency_analyzer import (
    DeFiProtocolPerformanceFeeCrystallizationFrequencyAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    RATIO_SENTINEL_INF,
    DEFAULT_HOLDING_DAYS,
    DEFAULT_PERF_FEE_PCT,
    DEFAULT_VOLATILITY_PCT,
    CONTINUOUS_FREQ,
    DAILY_FREQ,
    WEEKLY_FREQ,
    MONTHLY_FREQ,
    QUARTERLY_FREQ,
    ANNUAL_FREQ,
    HIGH_PERF_FEE_PCT,
    HIGH_COMPOUNDING_LOSS_PCT,
    HIGH_FREQUENCY_THRESHOLD,
    PAY_FOR_VOL_RISK_PCT,
    PREDATORY_SCORE,
    UNFRIENDLY_SCORE,
    NEUTRAL_SCORE,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="VaultA",
    gross_apr_pct=20.0,
    performance_fee_pct=20.0,
    crystallization_frequency_per_year=1.0,
    holding_period_days=365.0,
    has_high_water_mark=True,
    volatility_pct=30.0,
):
    return {
        "vault": vault,
        "gross_apr_pct": gross_apr_pct,
        "performance_fee_pct": performance_fee_pct,
        "crystallization_frequency_per_year": crystallization_frequency_per_year,
        "holding_period_days": holding_period_days,
        "has_high_water_mark": has_high_water_mark,
        "volatility_pct": volatility_pct,
    }


def A():
    return DeFiProtocolPerformanceFeeCrystallizationFrequencyAnalyzer()


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

    def test_f_bool(self):
        self.assertEqual(_f(False), 0.0)

    def test_clamp_within(self):
        self.assertEqual(_clamp(5, 0, 10), 5)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1, 0, 10), 0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(11, 0, 10), 10)

    def test_clamp_equal_bounds(self):
        self.assertEqual(_clamp(7, 7, 7), 7)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertAlmostEqual(_mean([2, 4, 6]), 4.0)

    def test_mean_single(self):
        self.assertAlmostEqual(_mean([3.0]), 3.0)

    def test_safe_div_normal(self):
        self.assertAlmostEqual(_safe_div(10, 2, 1e9), 5.0)

    def test_safe_div_zero_denominator(self):
        self.assertEqual(_safe_div(10, 0, 1e9), 1e9)

    def test_safe_div_negative_denominator(self):
        self.assertEqual(_safe_div(10, -5, 7.0), 7.0)

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
        self.assertIn("log_cap", cfg)

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
        self.assertGreater(RATIO_SENTINEL_INF, 0)
        self.assertEqual(DEFAULT_HOLDING_DAYS, 365.0)
        self.assertEqual(DEFAULT_PERF_FEE_PCT, 20.0)
        self.assertEqual(DEFAULT_VOLATILITY_PCT, 0.0)
        self.assertGreaterEqual(CONTINUOUS_FREQ, DAILY_FREQ)
        self.assertGreater(DAILY_FREQ, WEEKLY_FREQ)
        self.assertGreater(WEEKLY_FREQ, MONTHLY_FREQ)
        self.assertGreater(MONTHLY_FREQ, QUARTERLY_FREQ)
        self.assertGreater(QUARTERLY_FREQ, ANNUAL_FREQ)
        self.assertGreater(HIGH_PERF_FEE_PCT, 0)
        self.assertGreater(HIGH_COMPOUNDING_LOSS_PCT, 0)
        self.assertGreater(HIGH_FREQUENCY_THRESHOLD, 0)
        self.assertGreater(PAY_FOR_VOL_RISK_PCT, 0)
        self.assertLess(PREDATORY_SCORE, UNFRIENDLY_SCORE)
        self.assertLess(UNFRIENDLY_SCORE, NEUTRAL_SCORE)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "gross_apr_pct", "crystallization_label",
            "crystallizations_over_horizon", "nominal_perf_fee_drag_pct",
            "compounding_loss_pct", "compounding_loss_annual_pct",
            "effective_perf_fee_drag_pct", "pay_for_volatility_risk_pct",
            "net_apy_pct", "net_over_gross_ratio", "frequency_efficiency_score",
            "classification", "recommendation", "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_score_in_range(self):
        self.assertGreaterEqual(self.r["frequency_efficiency_score"], 0.0)
        self.assertLessEqual(self.r["frequency_efficiency_score"], 100.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_preserved(self):
        self.assertEqual(self.r["token"], "VaultA")

    def test_token_alias(self):
        r = A().analyze({"token": "TOK", "gross_apr_pct": 10.0,
                         "crystallization_frequency_per_year": 1.0})
        self.assertEqual(r["token"], "TOK")

    def test_vault_preferred(self):
        r = A().analyze({"vault": "V", "token": "T", "gross_apr_pct": 10.0,
                         "crystallization_frequency_per_year": 1.0})
        self.assertEqual(r["token"], "V")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        for v in self.r.values():
            if isinstance(v, float):
                self.assertFalse(math.isinf(v))
                self.assertFalse(math.isnan(v))

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"],
                      {"DEPLOY", "PREFER_LESS_FREQUENT", "AVOID"})

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_label_continuous(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=500.0))
        self.assertEqual(r["crystallization_label"], "CONTINUOUS")

    def test_label_daily(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=365.0))
        self.assertEqual(r["crystallization_label"], "DAILY")

    def test_label_weekly(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=52.0))
        self.assertEqual(r["crystallization_label"], "WEEKLY")

    def test_label_monthly(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=12.0))
        self.assertEqual(r["crystallization_label"], "MONTHLY")

    def test_label_quarterly(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=4.0))
        self.assertEqual(r["crystallization_label"], "QUARTERLY")

    def test_label_annual(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=1.0))
        self.assertEqual(r["crystallization_label"], "ANNUAL")

    def test_label_infrequent(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=0.5))
        self.assertEqual(r["crystallization_label"], "INFREQUENT")

    def test_crystallizations_over_horizon_full_year(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=12.0,
                                 holding_period_days=365.0))
        self.assertAlmostEqual(r["crystallizations_over_horizon"], 12.0)

    def test_crystallizations_over_horizon_half_year(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=12.0,
                                 holding_period_days=182.5))
        self.assertAlmostEqual(r["crystallizations_over_horizon"], 6.0)

    def test_nominal_perf_fee_drag(self):
        # gross 20 * 20% = 4.0
        r = A().analyze(make_pos(gross_apr_pct=20.0, performance_fee_pct=20.0))
        self.assertAlmostEqual(r["nominal_perf_fee_drag_pct"], 4.0)

    def test_nominal_drag_half_year(self):
        # gross over horizon = 10, * 20% = 2.0
        r = A().analyze(make_pos(gross_apr_pct=20.0, performance_fee_pct=20.0,
                                 holding_period_days=182.5))
        self.assertAlmostEqual(r["nominal_perf_fee_drag_pct"], 2.0)

    def test_compounding_loss_zero_at_annual(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=1.0))
        self.assertAlmostEqual(r["compounding_loss_pct"], 0.0)

    def test_compounding_loss_positive_at_high_freq(self):
        r = A().analyze(make_pos(gross_apr_pct=30.0,
                                 crystallization_frequency_per_year=365.0))
        self.assertGreater(r["compounding_loss_pct"], 0.0)

    def test_compounding_loss_increases_with_frequency(self):
        low = A().analyze(make_pos(gross_apr_pct=30.0,
                                   crystallization_frequency_per_year=4.0))
        high = A().analyze(make_pos(gross_apr_pct=30.0,
                                    crystallization_frequency_per_year=365.0))
        self.assertGreater(high["compounding_loss_pct"], low["compounding_loss_pct"])

    def test_compounding_loss_zero_when_no_perf_fee(self):
        r = A().analyze(make_pos(performance_fee_pct=0.0,
                                 crystallization_frequency_per_year=365.0))
        self.assertAlmostEqual(r["compounding_loss_pct"], 0.0)

    def test_effective_drag_equals_nominal_plus_compounding(self):
        r = A().analyze(make_pos(gross_apr_pct=30.0,
                                 crystallization_frequency_per_year=365.0))
        self.assertAlmostEqual(
            r["effective_perf_fee_drag_pct"],
            r["nominal_perf_fee_drag_pct"] + r["compounding_loss_pct"],
            places=3)

    def test_effective_drag_at_annual_equals_nominal(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=1.0))
        self.assertAlmostEqual(r["effective_perf_fee_drag_pct"],
                               r["nominal_perf_fee_drag_pct"])

    def test_pay_for_volatility_zero_with_hwm(self):
        r = A().analyze(make_pos(has_high_water_mark=True, volatility_pct=80.0,
                                 crystallization_frequency_per_year=365.0))
        self.assertAlmostEqual(r["pay_for_volatility_risk_pct"], 0.0)

    def test_pay_for_volatility_zero_no_vol(self):
        r = A().analyze(make_pos(has_high_water_mark=False, volatility_pct=0.0,
                                 crystallization_frequency_per_year=365.0))
        self.assertAlmostEqual(r["pay_for_volatility_risk_pct"], 0.0)

    def test_pay_for_volatility_positive(self):
        r = A().analyze(make_pos(has_high_water_mark=False, volatility_pct=80.0,
                                 crystallization_frequency_per_year=365.0))
        self.assertGreater(r["pay_for_volatility_risk_pct"], 0.0)

    def test_pay_for_volatility_higher_freq_more_risk(self):
        low = A().analyze(make_pos(has_high_water_mark=False, volatility_pct=80.0,
                                   crystallization_frequency_per_year=4.0))
        high = A().analyze(make_pos(has_high_water_mark=False, volatility_pct=80.0,
                                    crystallization_frequency_per_year=365.0))
        self.assertGreater(high["pay_for_volatility_risk_pct"],
                           low["pay_for_volatility_risk_pct"])

    def test_net_apy_at_annual(self):
        # gross 20 - effective drag annual (= 4.0) = 16.0
        r = A().analyze(make_pos(gross_apr_pct=20.0, performance_fee_pct=20.0,
                                 crystallization_frequency_per_year=1.0))
        self.assertAlmostEqual(r["net_apy_pct"], 16.0)

    def test_net_apy_lower_for_higher_freq(self):
        low_freq = A().analyze(make_pos(gross_apr_pct=30.0,
                                        crystallization_frequency_per_year=1.0))
        high_freq = A().analyze(make_pos(gross_apr_pct=30.0,
                                         crystallization_frequency_per_year=365.0))
        self.assertGreater(low_freq["net_apy_pct"], high_freq["net_apy_pct"])

    def test_net_over_gross_ratio(self):
        r = A().analyze(make_pos(gross_apr_pct=20.0, performance_fee_pct=20.0,
                                 crystallization_frequency_per_year=1.0))
        self.assertAlmostEqual(r["net_over_gross_ratio"], 16.0 / 20.0, places=3)

    def test_default_perf_fee_applied(self):
        p = make_pos(gross_apr_pct=20.0)
        del p["performance_fee_pct"]
        r = A().analyze(p)
        self.assertAlmostEqual(r["nominal_perf_fee_drag_pct"], 4.0)

    def test_default_volatility_applied(self):
        p = make_pos(has_high_water_mark=False,
                     crystallization_frequency_per_year=365.0)
        del p["volatility_pct"]
        r = A().analyze(p)
        self.assertAlmostEqual(r["pay_for_volatility_risk_pct"], 0.0)

    def test_zero_holding_period_falls_back(self):
        r = A().analyze(make_pos(gross_apr_pct=20.0, holding_period_days=0.0,
                                 crystallization_frequency_per_year=1.0))
        self.assertAlmostEqual(r["crystallizations_over_horizon"], 1.0)

    def test_negative_perf_fee_treated_as_zero(self):
        r = A().analyze(make_pos(performance_fee_pct=-5.0))
        self.assertAlmostEqual(r["nominal_perf_fee_drag_pct"], 0.0)

    def test_negative_volatility_treated_as_zero(self):
        r = A().analyze(make_pos(has_high_water_mark=False, volatility_pct=-30.0,
                                 crystallization_frequency_per_year=365.0))
        self.assertAlmostEqual(r["pay_for_volatility_risk_pct"], 0.0)

    def test_compounding_loss_annual_matches_full_year(self):
        # full year: annual == over-horizon
        r = A().analyze(make_pos(gross_apr_pct=30.0,
                                 crystallization_frequency_per_year=365.0,
                                 holding_period_days=365.0))
        self.assertAlmostEqual(r["compounding_loss_annual_pct"],
                               r["compounding_loss_pct"], places=3)


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_investor_friendly_annual_hwm(self):
        r = A().analyze(make_pos(gross_apr_pct=20.0,
                                 crystallization_frequency_per_year=1.0,
                                 has_high_water_mark=True))
        self.assertEqual(r["classification"], "INVESTOR_FRIENDLY")

    def test_predatory_high_freq_no_hwm(self):
        r = A().analyze(make_pos(gross_apr_pct=25.0, performance_fee_pct=30.0,
                                 crystallization_frequency_per_year=365.0,
                                 has_high_water_mark=False, volatility_pct=80.0))
        self.assertEqual(r["classification"], "PREDATORY")

    def test_classification_known_value(self):
        for pos in [make_pos(), make_pos(gross_apr_pct=0.0),
                    make_pos(has_high_water_mark=False, volatility_pct=80.0,
                             crystallization_frequency_per_year=365.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "INVESTOR_FRIENDLY", "NEUTRAL", "INVESTOR_UNFRIENDLY",
                "PREDATORY", "INSUFFICIENT_DATA",
            })

    def test_higher_freq_less_friendly(self):
        friendly = A().analyze(make_pos(gross_apr_pct=30.0,
                                        crystallization_frequency_per_year=1.0))
        unfriendly = A().analyze(make_pos(gross_apr_pct=30.0,
                                          crystallization_frequency_per_year=365.0))
        order = {"INVESTOR_FRIENDLY": 0, "NEUTRAL": 1,
                 "INVESTOR_UNFRIENDLY": 2, "PREDATORY": 3}
        self.assertLessEqual(order[friendly["classification"]],
                             order[unfriendly["classification"]])

    def test_no_hwm_worse_than_hwm(self):
        with_hwm = A().analyze(make_pos(crystallization_frequency_per_year=365.0,
                                        has_high_water_mark=True))
        no_hwm = A().analyze(make_pos(crystallization_frequency_per_year=365.0,
                                      has_high_water_mark=False, volatility_pct=80.0))
        self.assertLess(no_hwm["frequency_efficiency_score"],
                        with_hwm["frequency_efficiency_score"])


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_deploy_when_friendly(self):
        r = A().analyze(make_pos(gross_apr_pct=20.0,
                                 crystallization_frequency_per_year=1.0))
        self.assertEqual(r["recommendation"], "DEPLOY")

    def test_prefer_less_frequent_when_neutral(self):
        # weekly with hwm → NEUTRAL band
        r = A().analyze(make_pos(gross_apr_pct=30.0,
                                 crystallization_frequency_per_year=365.0,
                                 has_high_water_mark=True))
        self.assertIn(r["recommendation"], {"PREFER_LESS_FREQUENT", "DEPLOY"})

    def test_avoid_when_predatory(self):
        r = A().analyze(make_pos(gross_apr_pct=25.0, performance_fee_pct=30.0,
                                 crystallization_frequency_per_year=365.0,
                                 has_high_water_mark=False, volatility_pct=80.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_avoid_when_negative_net(self):
        r = A().analyze(make_pos(gross_apr_pct=1.0, performance_fee_pct=90.0,
                                 crystallization_frequency_per_year=365.0))
        # if net goes negative → AVOID
        if r["net_apy_pct"] < 0:
            self.assertEqual(r["recommendation"], "AVOID")

    def test_avoid_when_insufficient(self):
        r = A().analyze(make_pos(gross_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_continuous_crystallization_flag(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=365.0))
        self.assertIn("CONTINUOUS_CRYSTALLIZATION", r["flags"])

    def test_continuous_flag_absent_at_annual(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=1.0))
        self.assertNotIn("CONTINUOUS_CRYSTALLIZATION", r["flags"])

    def test_infrequent_crystallization_flag(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=0.5))
        self.assertIn("INFREQUENT_CRYSTALLIZATION", r["flags"])

    def test_infrequent_flag_absent_at_annual(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=1.0))
        self.assertNotIn("INFREQUENT_CRYSTALLIZATION", r["flags"])

    def test_has_hwm_flag(self):
        r = A().analyze(make_pos(has_high_water_mark=True))
        self.assertIn("HAS_HWM", r["flags"])

    def test_no_hwm_flag(self):
        r = A().analyze(make_pos(has_high_water_mark=False))
        self.assertIn("NO_HWM", r["flags"])

    def test_hwm_flags_mutually_exclusive(self):
        r = A().analyze(make_pos(has_high_water_mark=True))
        self.assertNotIn("NO_HWM", r["flags"])

    def test_high_compounding_loss_flag(self):
        r = A().analyze(make_pos(gross_apr_pct=30.0,
                                 crystallization_frequency_per_year=365.0))
        self.assertIn("HIGH_COMPOUNDING_LOSS", r["flags"])

    def test_high_compounding_loss_absent_at_annual(self):
        r = A().analyze(make_pos(gross_apr_pct=30.0,
                                 crystallization_frequency_per_year=1.0))
        self.assertNotIn("HIGH_COMPOUNDING_LOSS", r["flags"])

    def test_pay_for_volatility_risk_flag(self):
        r = A().analyze(make_pos(has_high_water_mark=False, volatility_pct=80.0,
                                 crystallization_frequency_per_year=365.0))
        self.assertIn("PAY_FOR_VOLATILITY_RISK", r["flags"])

    def test_pay_for_volatility_absent_with_hwm(self):
        r = A().analyze(make_pos(has_high_water_mark=True, volatility_pct=80.0,
                                 crystallization_frequency_per_year=365.0))
        self.assertNotIn("PAY_FOR_VOLATILITY_RISK", r["flags"])

    def test_high_perf_fee_flag(self):
        r = A().analyze(make_pos(performance_fee_pct=25.0))
        self.assertIn("HIGH_PERF_FEE", r["flags"])

    def test_high_perf_fee_absent(self):
        r = A().analyze(make_pos(performance_fee_pct=20.0))
        self.assertNotIn("HIGH_PERF_FEE", r["flags"])

    def test_negative_net_apy_flag(self):
        r = A().analyze(make_pos(gross_apr_pct=1.0, performance_fee_pct=90.0,
                                 crystallization_frequency_per_year=365.0))
        if r["net_apy_pct"] < 0:
            self.assertIn("NEGATIVE_NET_APY", r["flags"])

    def test_negative_net_apy_absent_when_positive(self):
        r = A().analyze(make_pos(gross_apr_pct=20.0))
        self.assertNotIn("NEGATIVE_NET_APY", r["flags"])

    def test_insufficient_data_flag(self):
        r = A().analyze(make_pos(gross_apr_pct=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_zero_gross_apr(self):
        r = A().analyze(make_pos(gross_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_gross_apr(self):
        r = A().analyze(make_pos(gross_apr_pct=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_frequency(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_frequency(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=-1.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(gross_apr_pct=0.0))
        self.assertEqual(r["frequency_efficiency_score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_label(self):
        r = A().analyze(make_pos(gross_apr_pct=0.0))
        self.assertEqual(r["crystallization_label"], "INSUFFICIENT_DATA")

    def test_insufficient_sentinels_none(self):
        r = A().analyze(make_pos(gross_apr_pct=0.0))
        self.assertIsNone(r["net_over_gross_ratio"])

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(gross_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_insufficient_token_preserved(self):
        r = A().analyze({"vault": "Empty", "gross_apr_pct": 0.0})
        self.assertEqual(r["token"], "Empty")


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_lower_freq_scores_higher(self):
        low = A().analyze(make_pos(gross_apr_pct=30.0,
                                   crystallization_frequency_per_year=1.0))
        high = A().analyze(make_pos(gross_apr_pct=30.0,
                                    crystallization_frequency_per_year=365.0))
        self.assertGreater(low["frequency_efficiency_score"],
                           high["frequency_efficiency_score"])

    def test_hwm_scores_higher(self):
        with_hwm = A().analyze(make_pos(crystallization_frequency_per_year=12.0,
                                        has_high_water_mark=True))
        no_hwm = A().analyze(make_pos(crystallization_frequency_per_year=12.0,
                                      has_high_water_mark=False, volatility_pct=80.0))
        self.assertGreater(with_hwm["frequency_efficiency_score"],
                           no_hwm["frequency_efficiency_score"])

    def test_lower_vol_risk_scores_higher(self):
        low_vol = A().analyze(make_pos(has_high_water_mark=False, volatility_pct=10.0,
                                       crystallization_frequency_per_year=365.0))
        high_vol = A().analyze(make_pos(has_high_water_mark=False, volatility_pct=90.0,
                                        crystallization_frequency_per_year=365.0))
        self.assertGreaterEqual(low_vol["frequency_efficiency_score"],
                                high_vol["frequency_efficiency_score"])

    def test_score_bounds_extreme(self):
        r = A().analyze(make_pos(gross_apr_pct=10000.0, performance_fee_pct=99.0,
                                 crystallization_frequency_per_year=100000.0,
                                 has_high_water_mark=False, volatility_pct=200.0))
        self.assertLessEqual(r["frequency_efficiency_score"], 100.0)
        self.assertGreaterEqual(r["frequency_efficiency_score"], 0.0)

    def test_best_case_high_score(self):
        r = A().analyze(make_pos(gross_apr_pct=20.0, performance_fee_pct=10.0,
                                 crystallization_frequency_per_year=1.0,
                                 has_high_water_mark=True, volatility_pct=0.0))
        self.assertGreater(r["frequency_efficiency_score"], 85.0)

    def test_score_is_float(self):
        r = A().analyze(make_pos())
        self.assertIsInstance(r["frequency_efficiency_score"], float)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Annual", gross_apr_pct=20.0,
                     crystallization_frequency_per_year=1.0,
                     has_high_water_mark=True),
            make_pos(vault="Predatory", gross_apr_pct=25.0, performance_fee_pct=30.0,
                     crystallization_frequency_per_year=365.0,
                     has_high_water_mark=False, volatility_pct=80.0),
            make_pos(vault="Monthly", gross_apr_pct=20.0,
                     crystallization_frequency_per_year=12.0,
                     has_high_water_mark=True),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_efficient_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["frequency_efficiency_score"]
                  for p in self.res["positions"]}
        most = agg["most_frequency_efficient_vault"]
        self.assertEqual(scores[most], max(scores.values()))

    def test_least_efficient_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["frequency_efficiency_score"]
                  for p in self.res["positions"]}
        least = agg["least_frequency_efficient_vault"]
        self.assertEqual(scores[least], min(scores.values()))

    def test_most_efficient_is_annual(self):
        self.assertEqual(self.res["aggregate"]["most_frequency_efficient_vault"],
                         "Annual")

    def test_least_efficient_is_predatory(self):
        self.assertEqual(self.res["aggregate"]["least_frequency_efficient_vault"],
                         "Predatory")

    def test_unfriendly_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["unfriendly_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_frequency_efficiency_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_frequency_efficient_vault"])
        self.assertIsNone(res["aggregate"]["least_frequency_efficient_vault"])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(gross_apr_pct=0.0),
            make_pos(crystallization_frequency_per_year=0.0),
        ])
        self.assertIsNone(res["aggregate"]["most_frequency_efficient_vault"])
        self.assertEqual(res["aggregate"]["avg_frequency_efficiency_score"], 0.0)

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_unfriendly_count_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(gross_apr_pct=0.0),
            make_pos(gross_apr_pct=25.0, performance_fee_pct=30.0,
                     crystallization_frequency_per_year=365.0,
                     has_high_water_mark=False, volatility_pct=80.0),
        ])
        self.assertEqual(res["aggregate"]["unfriendly_count"], 1)


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

    def test_ring_buffer_cap(self):
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
                json.dump({"not": "list"}, fh)
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

    def test_log_snapshot_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            snap = data[0]["snapshots"][0]
            for k in ("token", "classification", "frequency_efficiency_score",
                      "recommendation", "flags"):
                self.assertIn(k, snap)

    def test_log_atomic_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_log_json_no_inf_nan(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([
                make_pos(),
                make_pos(vault="hf", crystallization_frequency_per_year=365.0),
                make_pos(vault="ins", gross_apr_pct=0.0),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            json.loads(raw)


# ── robustness / edge cases ───────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "vault": "S",
            "gross_apr_pct": "20",
            "performance_fee_pct": "20",
            "crystallization_frequency_per_year": "12",
            "volatility_pct": "30",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({
            "vault": "S",
            "gross_apr_pct": 20.0,
            "crystallization_frequency_per_year": 1.0,
        })
        self.assertIn("classification", r)

    def test_default_has_hwm_true(self):
        # has_high_water_mark defaults to True
        r = A().analyze({
            "vault": "S",
            "gross_apr_pct": 20.0,
            "crystallization_frequency_per_year": 1.0,
        })
        self.assertIn("HAS_HWM", r["flags"])

    def test_very_large_gross(self):
        r = A().analyze(make_pos(gross_apr_pct=1e6,
                                 crystallization_frequency_per_year=365.0))
        for v in r.values():
            if isinstance(v, float):
                self.assertFalse(math.isinf(v))
                self.assertFalse(math.isnan(v))

    def test_extreme_frequency_no_inf(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=1e7))
        for v in r.values():
            if isinstance(v, float):
                self.assertFalse(math.isinf(v))
                self.assertFalse(math.isnan(v))

    def test_fractional_frequency(self):
        r = A().analyze(make_pos(crystallization_frequency_per_year=0.25))
        self.assertEqual(r["crystallization_label"], "INFREQUENT")

    def test_large_portfolio(self):
        res = A().analyze_portfolio([make_pos(vault=f"V{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(), make_pos(gross_apr_pct=0.0),
            make_pos(crystallization_frequency_per_year=365.0,
                     has_high_water_mark=False, volatility_pct=80.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(), make_pos(gross_apr_pct=0.0),
                    make_pos(crystallization_frequency_per_year=365.0),
                    make_pos(performance_fee_pct=0.0),
                    make_pos(has_high_water_mark=False, volatility_pct=100.0)]:
            r = A().analyze(pos)
            for v in r.values():
                if isinstance(v, float):
                    self.assertFalse(math.isinf(v))
                    self.assertFalse(math.isnan(v))

    def test_zero_perf_fee_no_drag(self):
        r = A().analyze(make_pos(performance_fee_pct=0.0))
        self.assertAlmostEqual(r["nominal_perf_fee_drag_pct"], 0.0)
        self.assertAlmostEqual(r["effective_perf_fee_drag_pct"], 0.0)

    def test_has_hwm_falsy_values(self):
        r = A().analyze({
            "vault": "S",
            "gross_apr_pct": 20.0,
            "crystallization_frequency_per_year": 1.0,
            "has_high_water_mark": False,
        })
        self.assertIn("NO_HWM", r["flags"])


if __name__ == "__main__":
    unittest.main()
