"""
Tests for MP-1152: DeFiProtocolPerformanceFeeHighWaterMarkAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_performance_fee_high_water_mark_analyzer -v
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

from spa_core.analytics.defi_protocol_performance_fee_high_water_mark_analyzer import (
    DeFiProtocolPerformanceFeeHighWaterMarkAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    RATIO_SENTINEL_INF,
    DEFAULT_HOLDING_DAYS,
    DEFAULT_MGMT_FEE_PCT,
    DEFAULT_PERF_FEE_PCT,
    DEFAULT_HURDLE_PCT,
    HIGH_MGMT_FEE_PCT,
    HIGH_PERF_FEE_PCT,
    LOW_FEE_DRAG_PCT,
    MODERATE_FEE_DRAG_PCT,
    HIGH_FEE_DRAG_PCT,
    AT_HWM_TOLERANCE_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="VaultA",
    gross_apr_pct=12.0,
    management_fee_pct=2.0,
    performance_fee_pct=20.0,
    current_nav=1.0,
    high_water_mark=1.0,
    holding_period_days=365.0,
    hurdle_rate_pct=0.0,
):
    return {
        "vault": vault,
        "gross_apr_pct": gross_apr_pct,
        "management_fee_pct": management_fee_pct,
        "performance_fee_pct": performance_fee_pct,
        "current_nav": current_nav,
        "high_water_mark": high_water_mark,
        "holding_period_days": holding_period_days,
        "hurdle_rate_pct": hurdle_rate_pct,
    }


def A():
    return DeFiProtocolPerformanceFeeHighWaterMarkAnalyzer()


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
        self.assertEqual(_f(True), 1.0)

    def test_clamp_within(self):
        self.assertEqual(_clamp(5, 0, 10), 5)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1, 0, 10), 0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(11, 0, 10), 10)

    def test_clamp_equal_bounds(self):
        self.assertEqual(_clamp(5, 5, 5), 5)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertAlmostEqual(_mean([2, 4, 6]), 4.0)

    def test_mean_single(self):
        self.assertAlmostEqual(_mean([7.5]), 7.5)

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
        self.assertGreater(RATIO_SENTINEL_INF, 0)
        self.assertEqual(DEFAULT_HOLDING_DAYS, 365.0)
        self.assertEqual(DEFAULT_MGMT_FEE_PCT, 2.0)
        self.assertEqual(DEFAULT_PERF_FEE_PCT, 20.0)
        self.assertEqual(DEFAULT_HURDLE_PCT, 0.0)
        self.assertGreater(HIGH_MGMT_FEE_PCT, 0)
        self.assertGreater(HIGH_PERF_FEE_PCT, 0)
        self.assertLess(LOW_FEE_DRAG_PCT, MODERATE_FEE_DRAG_PCT)
        self.assertLess(MODERATE_FEE_DRAG_PCT, HIGH_FEE_DRAG_PCT)
        self.assertGreater(AT_HWM_TOLERANCE_PCT, 0)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "gross_apr_pct", "underwater_pct", "is_underwater",
            "gross_yield_over_horizon_pct", "recovery_to_hwm_pct",
            "gross_above_hwm_pct", "mgmt_fee_drag_pct",
            "perf_fee_drag_with_hwm_pct", "perf_fee_drag_no_hwm_pct",
            "hwm_savings_pct", "total_fee_drag_annual_pct", "net_apy_pct",
            "net_over_gross_ratio", "fee_efficiency_score",
            "classification", "recommendation", "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_score_in_range(self):
        self.assertGreaterEqual(self.r["fee_efficiency_score"], 0.0)
        self.assertLessEqual(self.r["fee_efficiency_score"], 100.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_preserved(self):
        self.assertEqual(self.r["token"], "VaultA")

    def test_token_alias(self):
        r = A().analyze({"token": "TOK", "gross_apr_pct": 10.0, "current_nav": 1.0})
        self.assertEqual(r["token"], "TOK")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T", "gross_apr_pct": 10.0,
                         "current_nav": 1.0})
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
                      {"DEPLOY", "NEGOTIATE_TERMS", "AVOID"})

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_is_underwater_is_bool(self):
        self.assertIsInstance(self.r["is_underwater"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_gross_yield_over_horizon_full_year(self):
        r = A().analyze(make_pos(gross_apr_pct=12.0, holding_period_days=365.0))
        self.assertAlmostEqual(r["gross_yield_over_horizon_pct"], 12.0)

    def test_gross_yield_over_horizon_half_year(self):
        r = A().analyze(make_pos(gross_apr_pct=10.0, holding_period_days=182.5))
        self.assertAlmostEqual(r["gross_yield_over_horizon_pct"], 5.0)

    def test_underwater_pct_zero_at_peak(self):
        r = A().analyze(make_pos(current_nav=1.0, high_water_mark=1.0))
        self.assertAlmostEqual(r["underwater_pct"], 0.0)

    def test_underwater_pct_value(self):
        # (1.0 - 0.9)/1.0*100 = 10
        r = A().analyze(make_pos(current_nav=0.9, high_water_mark=1.0))
        self.assertAlmostEqual(r["underwater_pct"], 10.0)

    def test_is_underwater_true(self):
        r = A().analyze(make_pos(current_nav=0.9, high_water_mark=1.0))
        self.assertTrue(r["is_underwater"])

    def test_is_underwater_false_at_peak(self):
        r = A().analyze(make_pos(current_nav=1.0, high_water_mark=1.0))
        self.assertFalse(r["is_underwater"])

    def test_is_underwater_false_above_hwm(self):
        r = A().analyze(make_pos(current_nav=1.2, high_water_mark=1.0))
        self.assertFalse(r["is_underwater"])

    def test_recovery_to_hwm_pct(self):
        # (1.0 - 0.9)/0.9*100 = 11.1111
        r = A().analyze(make_pos(current_nav=0.9, high_water_mark=1.0))
        self.assertAlmostEqual(r["recovery_to_hwm_pct"], 11.1111, places=3)

    def test_recovery_zero_at_peak(self):
        r = A().analyze(make_pos(current_nav=1.0, high_water_mark=1.0))
        self.assertAlmostEqual(r["recovery_to_hwm_pct"], 0.0)

    def test_gross_above_hwm_at_peak(self):
        # at peak, all gross is above HWM
        r = A().analyze(make_pos(gross_apr_pct=12.0, current_nav=1.0,
                                 high_water_mark=1.0))
        self.assertAlmostEqual(r["gross_above_hwm_pct"], 12.0)

    def test_gross_above_hwm_underwater(self):
        # gross 15, recovery 11.1111 → above = 3.8889
        r = A().analyze(make_pos(gross_apr_pct=15.0, current_nav=0.9,
                                 high_water_mark=1.0))
        self.assertAlmostEqual(r["gross_above_hwm_pct"], 3.8889, places=3)

    def test_gross_above_hwm_zero_when_deep_underwater(self):
        # gross small, deep underwater → 0 above hwm
        r = A().analyze(make_pos(gross_apr_pct=5.0, current_nav=0.5,
                                 high_water_mark=1.0))
        self.assertAlmostEqual(r["gross_above_hwm_pct"], 0.0)

    def test_mgmt_fee_drag_full_year(self):
        r = A().analyze(make_pos(management_fee_pct=2.0, holding_period_days=365.0))
        self.assertAlmostEqual(r["mgmt_fee_drag_pct"], 2.0)

    def test_mgmt_fee_drag_half_year(self):
        r = A().analyze(make_pos(management_fee_pct=2.0, holding_period_days=182.5))
        self.assertAlmostEqual(r["mgmt_fee_drag_pct"], 1.0)

    def test_perf_fee_drag_with_hwm_at_peak(self):
        # gross 12 * 20% = 2.4
        r = A().analyze(make_pos(gross_apr_pct=12.0, performance_fee_pct=20.0,
                                 current_nav=1.0, high_water_mark=1.0))
        self.assertAlmostEqual(r["perf_fee_drag_with_hwm_pct"], 2.4)

    def test_perf_fee_drag_no_hwm_at_peak_equals_with(self):
        r = A().analyze(make_pos(gross_apr_pct=12.0, current_nav=1.0,
                                 high_water_mark=1.0))
        self.assertAlmostEqual(r["perf_fee_drag_with_hwm_pct"],
                               r["perf_fee_drag_no_hwm_pct"])

    def test_perf_fee_drag_with_hwm_underwater_lower(self):
        r = A().analyze(make_pos(gross_apr_pct=15.0, current_nav=0.9,
                                 high_water_mark=1.0))
        self.assertLess(r["perf_fee_drag_with_hwm_pct"],
                        r["perf_fee_drag_no_hwm_pct"])

    def test_perf_fee_drag_no_hwm_underwater(self):
        # gross 15 * 20% = 3.0
        r = A().analyze(make_pos(gross_apr_pct=15.0, performance_fee_pct=20.0,
                                 current_nav=0.9, high_water_mark=1.0))
        self.assertAlmostEqual(r["perf_fee_drag_no_hwm_pct"], 3.0)

    def test_perf_fee_drag_with_hwm_underwater_value(self):
        # above_hwm 3.8889 * 20% = 0.7778
        r = A().analyze(make_pos(gross_apr_pct=15.0, performance_fee_pct=20.0,
                                 current_nav=0.9, high_water_mark=1.0))
        self.assertAlmostEqual(r["perf_fee_drag_with_hwm_pct"], 0.7778, places=3)

    def test_hwm_savings_zero_at_peak(self):
        r = A().analyze(make_pos(current_nav=1.0, high_water_mark=1.0))
        self.assertAlmostEqual(r["hwm_savings_pct"], 0.0)

    def test_hwm_savings_positive_underwater(self):
        r = A().analyze(make_pos(gross_apr_pct=15.0, current_nav=0.9,
                                 high_water_mark=1.0))
        self.assertGreater(r["hwm_savings_pct"], 0.0)

    def test_hwm_savings_value(self):
        # no_hwm 3.0 - with_hwm 0.7778 = 2.2222
        r = A().analyze(make_pos(gross_apr_pct=15.0, performance_fee_pct=20.0,
                                 current_nav=0.9, high_water_mark=1.0))
        self.assertAlmostEqual(r["hwm_savings_pct"], 2.2222, places=3)

    def test_total_fee_drag_at_peak(self):
        # mgmt 2.0 + perf 2.4 = 4.4
        r = A().analyze(make_pos(gross_apr_pct=12.0, management_fee_pct=2.0,
                                 performance_fee_pct=20.0,
                                 current_nav=1.0, high_water_mark=1.0))
        self.assertAlmostEqual(r["total_fee_drag_annual_pct"], 4.4)

    def test_net_apy_at_peak(self):
        # gross 12 - mgmt 2 - perf 2.4 = 7.6
        r = A().analyze(make_pos(gross_apr_pct=12.0, management_fee_pct=2.0,
                                 performance_fee_pct=20.0,
                                 current_nav=1.0, high_water_mark=1.0))
        self.assertAlmostEqual(r["net_apy_pct"], 7.6)

    def test_net_apy_underwater_higher_than_peak_equivalent(self):
        # HWM protection raises net apy underwater
        r = A().analyze(make_pos(gross_apr_pct=15.0, current_nav=0.9,
                                 high_water_mark=1.0))
        # net = 15 - 2 - 0.7778 = 12.2222
        self.assertAlmostEqual(r["net_apy_pct"], 12.2222, places=3)

    def test_net_over_gross_ratio(self):
        r = A().analyze(make_pos(gross_apr_pct=12.0))
        self.assertAlmostEqual(r["net_over_gross_ratio"], 7.6 / 12.0, places=3)

    def test_hwm_defaults_to_current_nav(self):
        # hwm = 0 → uses current_nav, so at peak
        r = A().analyze(make_pos(current_nav=1.5, high_water_mark=0.0))
        self.assertFalse(r["is_underwater"])
        self.assertAlmostEqual(r["underwater_pct"], 0.0)

    def test_hwm_none_defaults_to_current_nav(self):
        p = make_pos(current_nav=1.5)
        p["high_water_mark"] = None
        r = A().analyze(p)
        self.assertFalse(r["is_underwater"])

    def test_default_mgmt_fee_applied(self):
        p = make_pos()
        del p["management_fee_pct"]
        r = A().analyze(p)
        self.assertAlmostEqual(r["mgmt_fee_drag_pct"], 2.0)

    def test_default_perf_fee_applied(self):
        p = make_pos(gross_apr_pct=12.0)
        del p["performance_fee_pct"]
        r = A().analyze(p)
        self.assertAlmostEqual(r["perf_fee_drag_with_hwm_pct"], 2.4)

    def test_zero_holding_period_falls_back(self):
        r = A().analyze(make_pos(gross_apr_pct=12.0, holding_period_days=0.0))
        self.assertAlmostEqual(r["gross_yield_over_horizon_pct"], 12.0)

    def test_hurdle_reduces_perf_fee(self):
        no_hurdle = A().analyze(make_pos(gross_apr_pct=12.0, hurdle_rate_pct=0.0))
        with_hurdle = A().analyze(make_pos(gross_apr_pct=12.0, hurdle_rate_pct=5.0))
        self.assertLess(with_hurdle["perf_fee_drag_with_hwm_pct"],
                        no_hurdle["perf_fee_drag_with_hwm_pct"])

    def test_hurdle_value(self):
        # gross 12, hurdle 5, base = 7, perf 20% = 1.4
        r = A().analyze(make_pos(gross_apr_pct=12.0, performance_fee_pct=20.0,
                                 hurdle_rate_pct=5.0,
                                 current_nav=1.0, high_water_mark=1.0))
        self.assertAlmostEqual(r["perf_fee_drag_with_hwm_pct"], 1.4)

    def test_negative_mgmt_fee_treated_as_zero(self):
        r = A().analyze(make_pos(management_fee_pct=-5.0))
        self.assertAlmostEqual(r["mgmt_fee_drag_pct"], 0.0)

    def test_negative_perf_fee_treated_as_zero(self):
        r = A().analyze(make_pos(performance_fee_pct=-5.0))
        self.assertAlmostEqual(r["perf_fee_drag_with_hwm_pct"], 0.0)

    def test_negative_hurdle_treated_as_zero(self):
        a = A().analyze(make_pos(gross_apr_pct=12.0, hurdle_rate_pct=-5.0))
        b = A().analyze(make_pos(gross_apr_pct=12.0, hurdle_rate_pct=0.0))
        self.assertAlmostEqual(a["perf_fee_drag_with_hwm_pct"],
                               b["perf_fee_drag_with_hwm_pct"])

    def test_underwater_pct_capped_100(self):
        r = A().analyze(make_pos(current_nav=0.01, high_water_mark=1.0))
        self.assertLessEqual(r["underwater_pct"], 100.0)


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_low_fee_drag(self):
        # low fees: mgmt 0.5, perf 5% on gross 8 = 0.4 → total 0.9 < 1.5
        r = A().analyze(make_pos(gross_apr_pct=8.0, management_fee_pct=0.5,
                                 performance_fee_pct=5.0))
        self.assertEqual(r["classification"], "LOW_FEE_DRAG")

    def test_moderate_fee_drag(self):
        # mgmt 1.0 + perf 20% on 10 = 2.0 → total 3.0
        r = A().analyze(make_pos(gross_apr_pct=10.0, management_fee_pct=1.0,
                                 performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "MODERATE_FEE_DRAG")

    def test_high_fee_drag(self):
        # mgmt 2 + perf 2.4 = 4.4 → HIGH (between 4 and 8)
        r = A().analyze(make_pos(gross_apr_pct=12.0, management_fee_pct=2.0,
                                 performance_fee_pct=20.0))
        self.assertEqual(r["classification"], "HIGH_FEE_DRAG")

    def test_excessive_fee_drag(self):
        # mgmt 4 + perf 30% on 20 = 6 → total 10 >= 8
        r = A().analyze(make_pos(gross_apr_pct=20.0, management_fee_pct=4.0,
                                 performance_fee_pct=30.0))
        self.assertEqual(r["classification"], "EXCESSIVE_FEE_DRAG")

    def test_classification_known_value(self):
        for pos in [make_pos(), make_pos(gross_apr_pct=0.0),
                    make_pos(management_fee_pct=5.0, performance_fee_pct=40.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "LOW_FEE_DRAG", "MODERATE_FEE_DRAG", "HIGH_FEE_DRAG",
                "EXCESSIVE_FEE_DRAG", "INSUFFICIENT_DATA",
            })

    def test_low_threshold_boundary(self):
        # total drag exactly below threshold → LOW
        r = A().analyze(make_pos(gross_apr_pct=5.0, management_fee_pct=0.5,
                                 performance_fee_pct=10.0))
        self.assertIn(r["classification"], {"LOW_FEE_DRAG", "MODERATE_FEE_DRAG"})


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_deploy_when_low_drag(self):
        r = A().analyze(make_pos(gross_apr_pct=8.0, management_fee_pct=0.5,
                                 performance_fee_pct=5.0))
        self.assertEqual(r["recommendation"], "DEPLOY")

    def test_negotiate_when_high_drag(self):
        r = A().analyze(make_pos(gross_apr_pct=12.0, management_fee_pct=2.0,
                                 performance_fee_pct=20.0))
        self.assertEqual(r["recommendation"], "NEGOTIATE_TERMS")

    def test_avoid_when_excessive(self):
        r = A().analyze(make_pos(gross_apr_pct=20.0, management_fee_pct=4.0,
                                 performance_fee_pct=30.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_avoid_when_negative_net(self):
        # huge fees > gross → negative net → AVOID
        r = A().analyze(make_pos(gross_apr_pct=1.0, management_fee_pct=5.0,
                                 performance_fee_pct=50.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_avoid_when_insufficient(self):
        r = A().analyze(make_pos(gross_apr_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_underwater_flag(self):
        r = A().analyze(make_pos(current_nav=0.9, high_water_mark=1.0))
        self.assertIn("UNDERWATER", r["flags"])

    def test_underwater_flag_absent_at_peak(self):
        r = A().analyze(make_pos(current_nav=1.0, high_water_mark=1.0))
        self.assertNotIn("UNDERWATER", r["flags"])

    def test_hwm_protection_active_flag(self):
        r = A().analyze(make_pos(gross_apr_pct=15.0, current_nav=0.9,
                                 high_water_mark=1.0))
        self.assertIn("HWM_PROTECTION_ACTIVE", r["flags"])

    def test_at_high_water_mark_flag(self):
        r = A().analyze(make_pos(current_nav=1.0, high_water_mark=1.0))
        self.assertIn("AT_HIGH_WATER_MARK", r["flags"])

    def test_at_high_water_mark_absent_when_underwater(self):
        r = A().analyze(make_pos(current_nav=0.9, high_water_mark=1.0))
        self.assertNotIn("AT_HIGH_WATER_MARK", r["flags"])

    def test_no_hwm_protection_flag_at_peak(self):
        r = A().analyze(make_pos(current_nav=1.0, high_water_mark=1.0))
        self.assertIn("NO_HWM_PROTECTION", r["flags"])

    def test_no_hwm_protection_when_underwater_but_zero_perf_fee(self):
        # underwater but perf fee = 0 → no savings to give → NO_HWM_PROTECTION
        r = A().analyze(make_pos(gross_apr_pct=5.0, performance_fee_pct=0.0,
                                 current_nav=0.5, high_water_mark=1.0))
        self.assertIn("NO_HWM_PROTECTION", r["flags"])
        self.assertNotIn("HWM_PROTECTION_ACTIVE", r["flags"])

    def test_high_mgmt_fee_flag(self):
        r = A().analyze(make_pos(management_fee_pct=3.0))
        self.assertIn("HIGH_MGMT_FEE", r["flags"])

    def test_high_mgmt_fee_absent(self):
        r = A().analyze(make_pos(management_fee_pct=2.0))
        self.assertNotIn("HIGH_MGMT_FEE", r["flags"])

    def test_high_perf_fee_flag(self):
        r = A().analyze(make_pos(performance_fee_pct=25.0))
        self.assertIn("HIGH_PERF_FEE", r["flags"])

    def test_high_perf_fee_absent(self):
        r = A().analyze(make_pos(performance_fee_pct=20.0))
        self.assertNotIn("HIGH_PERF_FEE", r["flags"])

    def test_negative_net_apy_flag(self):
        r = A().analyze(make_pos(gross_apr_pct=1.0, management_fee_pct=5.0,
                                 performance_fee_pct=50.0))
        self.assertIn("NEGATIVE_NET_APY", r["flags"])

    def test_negative_net_apy_absent_when_positive(self):
        r = A().analyze(make_pos(gross_apr_pct=12.0))
        self.assertNotIn("NEGATIVE_NET_APY", r["flags"])

    def test_hurdle_applied_flag(self):
        r = A().analyze(make_pos(hurdle_rate_pct=5.0))
        self.assertIn("HURDLE_APPLIED", r["flags"])

    def test_hurdle_applied_absent(self):
        r = A().analyze(make_pos(hurdle_rate_pct=0.0))
        self.assertNotIn("HURDLE_APPLIED", r["flags"])

    def test_excessive_total_fee_drag_flag(self):
        r = A().analyze(make_pos(gross_apr_pct=20.0, management_fee_pct=4.0,
                                 performance_fee_pct=30.0))
        self.assertIn("EXCESSIVE_TOTAL_FEE_DRAG", r["flags"])

    def test_excessive_total_fee_drag_absent(self):
        r = A().analyze(make_pos(gross_apr_pct=8.0, management_fee_pct=0.5,
                                 performance_fee_pct=5.0))
        self.assertNotIn("EXCESSIVE_TOTAL_FEE_DRAG", r["flags"])

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

    def test_zero_nav(self):
        r = A().analyze(make_pos(current_nav=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_nav(self):
        r = A().analyze(make_pos(current_nav=-1.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(gross_apr_pct=0.0))
        self.assertEqual(r["fee_efficiency_score"], 0.0)
        self.assertEqual(r["grade"], "F")

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
    def test_lower_fees_score_higher(self):
        cheap = A().analyze(make_pos(gross_apr_pct=12.0, management_fee_pct=0.5,
                                     performance_fee_pct=5.0))
        pricey = A().analyze(make_pos(gross_apr_pct=12.0, management_fee_pct=4.0,
                                      performance_fee_pct=40.0))
        self.assertGreater(cheap["fee_efficiency_score"],
                           pricey["fee_efficiency_score"])

    def test_higher_mgmt_scores_lower(self):
        low = A().analyze(make_pos(gross_apr_pct=12.0, management_fee_pct=1.0))
        high = A().analyze(make_pos(gross_apr_pct=12.0, management_fee_pct=4.0))
        self.assertGreater(low["fee_efficiency_score"],
                           high["fee_efficiency_score"])

    def test_higher_perf_scores_lower(self):
        low = A().analyze(make_pos(gross_apr_pct=12.0, performance_fee_pct=10.0))
        high = A().analyze(make_pos(gross_apr_pct=12.0, performance_fee_pct=40.0))
        self.assertGreater(low["fee_efficiency_score"],
                           high["fee_efficiency_score"])

    def test_negative_net_scores_low(self):
        r = A().analyze(make_pos(gross_apr_pct=1.0, management_fee_pct=5.0,
                                 performance_fee_pct=50.0))
        self.assertLess(r["fee_efficiency_score"], 40.0)

    def test_score_bounds_extreme(self):
        r = A().analyze(make_pos(gross_apr_pct=1000.0, management_fee_pct=0.0,
                                 performance_fee_pct=0.0))
        self.assertLessEqual(r["fee_efficiency_score"], 100.0)
        self.assertGreaterEqual(r["fee_efficiency_score"], 0.0)

    def test_zero_fees_scores_high(self):
        r = A().analyze(make_pos(gross_apr_pct=12.0, management_fee_pct=0.0,
                                 performance_fee_pct=0.0))
        self.assertGreater(r["fee_efficiency_score"], 80.0)

    def test_hwm_protection_boosts_score(self):
        underwater = A().analyze(make_pos(gross_apr_pct=15.0, current_nav=0.9,
                                          high_water_mark=1.0))
        peak = A().analyze(make_pos(gross_apr_pct=15.0, current_nav=1.0,
                                    high_water_mark=1.0))
        # underwater enjoys HWM protection → higher net → higher score
        self.assertGreater(underwater["fee_efficiency_score"],
                           peak["fee_efficiency_score"])


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Cheap", gross_apr_pct=12.0, management_fee_pct=0.5,
                     performance_fee_pct=5.0),
            make_pos(vault="Pricey", gross_apr_pct=20.0, management_fee_pct=4.0,
                     performance_fee_pct=30.0),
            make_pos(vault="Mid", gross_apr_pct=12.0, management_fee_pct=2.0,
                     performance_fee_pct=20.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_efficient_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["fee_efficiency_score"]
                  for p in self.res["positions"]}
        most = agg["most_fee_efficient_vault"]
        self.assertEqual(scores[most], max(scores.values()))

    def test_least_efficient_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["fee_efficiency_score"]
                  for p in self.res["positions"]}
        least = agg["least_fee_efficient_vault"]
        self.assertEqual(scores[least], min(scores.values()))

    def test_most_efficient_is_cheap(self):
        self.assertEqual(self.res["aggregate"]["most_fee_efficient_vault"], "Cheap")

    def test_high_fee_drag_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["high_fee_drag_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_fee_efficiency_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_fee_efficient_vault"])
        self.assertIsNone(res["aggregate"]["least_fee_efficient_vault"])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(gross_apr_pct=0.0), make_pos(current_nav=0.0),
        ])
        self.assertIsNone(res["aggregate"]["most_fee_efficient_vault"])
        self.assertEqual(res["aggregate"]["avg_fee_efficiency_score"], 0.0)

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_high_fee_drag_count_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(gross_apr_pct=0.0),
            make_pos(gross_apr_pct=20.0, management_fee_pct=4.0,
                     performance_fee_pct=30.0),
        ])
        self.assertEqual(res["aggregate"]["high_fee_drag_count"], 1)


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

    def test_log_snapshot_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            snap = data[0]["snapshots"][0]
            for k in ("token", "classification", "fee_efficiency_score",
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
                make_pos(vault="uw", current_nav=0.9, high_water_mark=1.0),
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
            "gross_apr_pct": "12",
            "management_fee_pct": "2",
            "performance_fee_pct": "20",
            "current_nav": "1.0",
            "high_water_mark": "1.0",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({
            "vault": "S",
            "gross_apr_pct": 12.0,
            "current_nav": 1.0,
        })
        self.assertIn("classification", r)

    def test_very_large_gross(self):
        r = A().analyze(make_pos(gross_apr_pct=1e6))
        for v in r.values():
            if isinstance(v, float):
                self.assertFalse(math.isinf(v))
                self.assertFalse(math.isnan(v))

    def test_very_small_nav(self):
        r = A().analyze(make_pos(current_nav=1e-9, high_water_mark=1.0))
        self.assertIn("classification", r)
        for v in r.values():
            if isinstance(v, float):
                self.assertFalse(math.isinf(v))

    def test_nav_above_hwm(self):
        r = A().analyze(make_pos(current_nav=2.0, high_water_mark=1.0))
        self.assertFalse(r["is_underwater"])
        self.assertAlmostEqual(r["underwater_pct"], 0.0)

    def test_large_portfolio(self):
        res = A().analyze_portfolio([make_pos(vault=f"V{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(), make_pos(gross_apr_pct=0.0),
            make_pos(current_nav=0.9, high_water_mark=1.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(), make_pos(gross_apr_pct=0.0),
                    make_pos(current_nav=0.5, high_water_mark=1.0),
                    make_pos(performance_fee_pct=0.0),
                    make_pos(management_fee_pct=0.0)]:
            r = A().analyze(pos)
            for v in r.values():
                if isinstance(v, float):
                    self.assertFalse(math.isinf(v))
                    self.assertFalse(math.isnan(v))

    def test_zero_perf_fee_no_perf_drag(self):
        r = A().analyze(make_pos(gross_apr_pct=12.0, performance_fee_pct=0.0))
        self.assertAlmostEqual(r["perf_fee_drag_with_hwm_pct"], 0.0)

    def test_zero_mgmt_fee_no_mgmt_drag(self):
        r = A().analyze(make_pos(gross_apr_pct=12.0, management_fee_pct=0.0))
        self.assertAlmostEqual(r["mgmt_fee_drag_pct"], 0.0)

    def test_score_is_float(self):
        r = A().analyze(make_pos())
        self.assertIsInstance(r["fee_efficiency_score"], float)


if __name__ == "__main__":
    unittest.main()
