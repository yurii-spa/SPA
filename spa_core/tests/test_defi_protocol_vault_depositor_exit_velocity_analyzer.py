"""
Tests for MP-1172: DeFiProtocolVaultDepositorExitVelocityAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_depositor_exit_velocity_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_depositor_exit_velocity_analyzer import (
    DeFiProtocolVaultDepositorExitVelocityAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    RATE_CEILING_PCT,
    ACCEL_CEILING_PCT,
    MULT_CEILING,
    ACCEL_THRESHOLD_PCT,
    CALM_RATE_PCT,
    ELEVATED_RATE_PCT,
    RUN_RATE_PCT,
    BASELINE_SPIKE_MULT,
    RAPID_DRAIN_DAYS,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    tvl_usd=10_000_000.0,
    net_outflow_24h_usd=50_000.0,
    net_outflow_prev_24h_usd=40_000.0,
    outflow_3d_avg_usd=60_000.0,
):
    return {
        "vault": vault,
        "tvl_usd": tvl_usd,
        "net_outflow_24h_usd": net_outflow_24h_usd,
        "net_outflow_prev_24h_usd": net_outflow_prev_24h_usd,
        "outflow_3d_avg_usd": outflow_3d_avg_usd,
    }


def A():
    return DeFiProtocolVaultDepositorExitVelocityAnalyzer()


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
        self.assertGreater(RATE_CEILING_PCT, 0)
        self.assertGreater(ACCEL_CEILING_PCT, 0)
        self.assertGreater(MULT_CEILING, 1.0)
        self.assertGreater(ACCEL_THRESHOLD_PCT, 0)
        self.assertLess(CALM_RATE_PCT, ELEVATED_RATE_PCT)
        self.assertLess(ELEVATED_RATE_PCT, RUN_RATE_PCT)
        self.assertGreaterEqual(BASELINE_SPIKE_MULT, 1.0)
        self.assertGreater(RAPID_DRAIN_DAYS, 0)
        self.assertEqual(LOG_CAP, 100)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "tvl_usd", "net_outflow_24h_usd",
            "net_outflow_prev_24h_usd", "outflow_rate_pct",
            "prev_outflow_rate_pct", "acceleration_pct", "acceleration_ratio",
            "vs_baseline_ratio", "days_to_50pct_drain", "is_net_inflow",
            "is_accelerating", "score", "classification", "recommendation",
            "grade", "flags",
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
        r = A().analyze({"token": "AltKey", "tvl_usd": 1_000_000.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T", "tvl_usd": 1_000_000.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"tvl_usd": 1_000_000.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "EXIT_NOW", "REDUCE_OR_EXIT", "MONITOR_CLOSELY", "HOLD",
            "VERIFY_DATA",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "CALM", "ELEVATED", "DRAINING", "BANK_RUN", "INSUFFICIENT_DATA",
        })

    def test_is_net_inflow_is_bool(self):
        self.assertIsInstance(self.r["is_net_inflow"], bool)

    def test_is_accelerating_is_bool(self):
        self.assertIsInstance(self.r["is_accelerating"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_tvl_passthrough(self):
        r = A().analyze(make_pos(tvl_usd=10_000_000.0))
        self.assertAlmostEqual(r["tvl_usd"], 10_000_000.0)

    def test_tvl_negative_insufficient(self):
        r = A().analyze(make_pos(tvl_usd=-50.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_outflow_rate_pct(self):
        # 50k / 10M = 0.5%
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=50_000.0))
        self.assertAlmostEqual(r["outflow_rate_pct"], 0.5, places=4)

    def test_prev_outflow_rate_pct(self):
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_prev_24h_usd=100_000.0))
        self.assertAlmostEqual(r["prev_outflow_rate_pct"], 1.0, places=4)

    def test_acceleration_pct(self):
        # rate 2% now, 1% prev → accel 1%
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=200_000.0,
                                 net_outflow_prev_24h_usd=100_000.0))
        self.assertAlmostEqual(r["acceleration_pct"], 1.0, places=4)

    def test_acceleration_ratio(self):
        # 2% / 1% = 2.0
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=200_000.0,
                                 net_outflow_prev_24h_usd=100_000.0))
        self.assertAlmostEqual(r["acceleration_ratio"], 2.0, places=4)

    def test_acceleration_ratio_none_when_prev_zero(self):
        r = A().analyze(make_pos(net_outflow_prev_24h_usd=0.0))
        self.assertIsNone(r["acceleration_ratio"])

    def test_acceleration_ratio_none_when_prev_inflow(self):
        r = A().analyze(make_pos(net_outflow_prev_24h_usd=-50_000.0))
        self.assertIsNone(r["acceleration_ratio"])

    def test_vs_baseline_ratio(self):
        # 120k / 60k = 2.0
        r = A().analyze(make_pos(net_outflow_24h_usd=120_000.0,
                                 outflow_3d_avg_usd=60_000.0))
        self.assertAlmostEqual(r["vs_baseline_ratio"], 2.0, places=4)

    def test_vs_baseline_ratio_none_when_no_baseline(self):
        r = A().analyze(make_pos(outflow_3d_avg_usd=0.0))
        self.assertIsNone(r["vs_baseline_ratio"])

    def test_days_to_50pct_drain(self):
        # 0.5 * 10M / 100k = 50 days
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=100_000.0))
        self.assertAlmostEqual(r["days_to_50pct_drain"], 50.0, places=4)

    def test_days_to_50pct_drain_none_when_inflow(self):
        r = A().analyze(make_pos(net_outflow_24h_usd=-50_000.0))
        self.assertIsNone(r["days_to_50pct_drain"])

    def test_days_to_50pct_drain_none_when_zero_outflow(self):
        r = A().analyze(make_pos(net_outflow_24h_usd=0.0))
        self.assertIsNone(r["days_to_50pct_drain"])

    def test_is_net_inflow_true(self):
        r = A().analyze(make_pos(net_outflow_24h_usd=-100_000.0))
        self.assertTrue(r["is_net_inflow"])

    def test_is_net_inflow_false(self):
        r = A().analyze(make_pos(net_outflow_24h_usd=100_000.0))
        self.assertFalse(r["is_net_inflow"])

    def test_is_accelerating_true(self):
        # accel must exceed ACCEL_THRESHOLD_PCT (1%)
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=400_000.0,
                                 net_outflow_prev_24h_usd=100_000.0))
        self.assertTrue(r["is_accelerating"])

    def test_is_accelerating_false_decel(self):
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=50_000.0,
                                 net_outflow_prev_24h_usd=200_000.0))
        self.assertFalse(r["is_accelerating"])

    def test_is_accelerating_boundary(self):
        # accel exactly 1% → not > threshold → false
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=200_000.0,
                                 net_outflow_prev_24h_usd=100_000.0))
        self.assertFalse(r["is_accelerating"])

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(tvl_usd=10_000_003.3333,
                                 net_outflow_24h_usd=50_111.1111))
        for k in ("tvl_usd", "net_outflow_24h_usd", "outflow_rate_pct",
                  "acceleration_pct"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_calm(self):
        # rate 0.5% < CALM, not accelerating → CALM
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=50_000.0,
                                 net_outflow_prev_24h_usd=50_000.0))
        self.assertEqual(r["classification"], "CALM")

    def test_elevated_by_rate(self):
        # rate 5% (> CALM 2%, <= ELEVATED 8%) → ELEVATED
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=500_000.0,
                                 net_outflow_prev_24h_usd=500_000.0))
        self.assertEqual(r["classification"], "ELEVATED")

    def test_elevated_by_acceleration(self):
        # rate 1.5% (< CALM) but accelerating from 0.2% → ELEVATED
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=150_000.0,
                                 net_outflow_prev_24h_usd=20_000.0))
        self.assertEqual(r["classification"], "ELEVATED")

    def test_draining_by_rate(self):
        # rate 12% (> ELEVATED 8%) → DRAINING
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=1_200_000.0,
                                 net_outflow_prev_24h_usd=1_200_000.0))
        self.assertEqual(r["classification"], "DRAINING")

    def test_draining_by_acceleration(self):
        # rate 7% (<= ELEVATED) but accel >= 10% (from -3% to 7%) → DRAINING
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=700_000.0,
                                 net_outflow_prev_24h_usd=-300_000.0))
        self.assertEqual(r["classification"], "DRAINING")

    def test_bank_run(self):
        # rate 30% (> RUN 20%) → BANK_RUN
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=3_000_000.0,
                                 net_outflow_prev_24h_usd=1_000_000.0))
        self.assertEqual(r["classification"], "BANK_RUN")

    def test_calm_rate_boundary(self):
        # rate exactly 2% (not > CALM) and not accelerating → CALM
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=200_000.0,
                                 net_outflow_prev_24h_usd=200_000.0))
        self.assertEqual(r["classification"], "CALM")

    def test_elevated_rate_boundary(self):
        # rate exactly 8% (not > ELEVATED) → ELEVATED (since > CALM)
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=800_000.0,
                                 net_outflow_prev_24h_usd=800_000.0))
        self.assertEqual(r["classification"], "ELEVATED")

    def test_run_rate_boundary(self):
        # rate exactly 20% (not > RUN) → DRAINING
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=2_000_000.0,
                                 net_outflow_prev_24h_usd=2_000_000.0))
        self.assertEqual(r["classification"], "DRAINING")

    def test_net_inflow_is_calm(self):
        r = A().analyze(make_pos(net_outflow_24h_usd=-500_000.0,
                                 net_outflow_prev_24h_usd=-400_000.0))
        self.assertEqual(r["classification"], "CALM")

    def test_insufficient_no_tvl(self):
        r = A().analyze(make_pos(tvl_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(net_outflow_24h_usd=50_000.0,
                             net_outflow_prev_24h_usd=50_000.0),
                    make_pos(net_outflow_24h_usd=500_000.0,
                             net_outflow_prev_24h_usd=500_000.0),
                    make_pos(net_outflow_24h_usd=1_200_000.0,
                             net_outflow_prev_24h_usd=1_200_000.0),
                    make_pos(net_outflow_24h_usd=3_000_000.0,
                             net_outflow_prev_24h_usd=1_000_000.0),
                    make_pos(tvl_usd=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "CALM", "ELEVATED", "DRAINING", "BANK_RUN",
                "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_exit_now_bank_run(self):
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=3_000_000.0,
                                 net_outflow_prev_24h_usd=1_000_000.0))
        self.assertEqual(r["recommendation"], "EXIT_NOW")

    def test_reduce_draining(self):
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=1_200_000.0,
                                 net_outflow_prev_24h_usd=1_200_000.0))
        self.assertEqual(r["recommendation"], "REDUCE_OR_EXIT")

    def test_monitor_elevated(self):
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=500_000.0,
                                 net_outflow_prev_24h_usd=500_000.0))
        self.assertEqual(r["recommendation"], "MONITOR_CLOSELY")

    def test_hold_calm(self):
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=50_000.0,
                                 net_outflow_prev_24h_usd=50_000.0))
        self.assertEqual(r["recommendation"], "HOLD")

    def test_verify_insufficient(self):
        r = A().analyze(make_pos(tvl_usd=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_calm_flag(self):
        r = A().analyze(make_pos(net_outflow_24h_usd=50_000.0,
                                 net_outflow_prev_24h_usd=50_000.0))
        self.assertIn("CALM", r["flags"])

    def test_elevated_flag(self):
        r = A().analyze(make_pos(net_outflow_24h_usd=500_000.0,
                                 net_outflow_prev_24h_usd=500_000.0))
        self.assertIn("ELEVATED", r["flags"])

    def test_draining_flag(self):
        r = A().analyze(make_pos(net_outflow_24h_usd=1_200_000.0,
                                 net_outflow_prev_24h_usd=1_200_000.0))
        self.assertIn("DRAINING", r["flags"])

    def test_bank_run_flag(self):
        r = A().analyze(make_pos(net_outflow_24h_usd=3_000_000.0,
                                 net_outflow_prev_24h_usd=1_000_000.0))
        self.assertIn("BANK_RUN", r["flags"])

    def test_accelerating_flag(self):
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=400_000.0,
                                 net_outflow_prev_24h_usd=100_000.0))
        self.assertIn("ACCELERATING_OUTFLOWS", r["flags"])

    def test_accelerating_flag_absent(self):
        r = A().analyze(make_pos(net_outflow_24h_usd=50_000.0,
                                 net_outflow_prev_24h_usd=200_000.0))
        self.assertNotIn("ACCELERATING_OUTFLOWS", r["flags"])

    def test_net_inflow_flag(self):
        r = A().analyze(make_pos(net_outflow_24h_usd=-100_000.0))
        self.assertIn("NET_INFLOW", r["flags"])

    def test_net_inflow_flag_absent(self):
        r = A().analyze(make_pos(net_outflow_24h_usd=100_000.0))
        self.assertNotIn("NET_INFLOW", r["flags"])

    def test_above_baseline_spike_flag(self):
        # 200k / 60k = 3.33 >= 2.0
        r = A().analyze(make_pos(net_outflow_24h_usd=200_000.0,
                                 outflow_3d_avg_usd=60_000.0))
        self.assertIn("ABOVE_BASELINE_SPIKE", r["flags"])

    def test_above_baseline_spike_flag_absent_low_ratio(self):
        # 60k / 60k = 1.0 < 2.0
        r = A().analyze(make_pos(net_outflow_24h_usd=60_000.0,
                                 outflow_3d_avg_usd=60_000.0))
        self.assertNotIn("ABOVE_BASELINE_SPIKE", r["flags"])

    def test_above_baseline_spike_flag_absent_no_baseline(self):
        r = A().analyze(make_pos(outflow_3d_avg_usd=0.0))
        self.assertNotIn("ABOVE_BASELINE_SPIKE", r["flags"])

    def test_rapid_drain_flag(self):
        # days = 0.5*10M/1.5M = 3.33 <= 5
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=1_500_000.0))
        self.assertIn("RAPID_DRAIN", r["flags"])

    def test_rapid_drain_flag_absent_slow(self):
        # days = 50 > 5
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=100_000.0))
        self.assertNotIn("RAPID_DRAIN", r["flags"])

    def test_rapid_drain_flag_absent_inflow(self):
        r = A().analyze(make_pos(net_outflow_24h_usd=-100_000.0))
        self.assertNotIn("RAPID_DRAIN", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(tvl_usd=0.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_tvl(self):
        r = A().analyze(make_pos(tvl_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(tvl_usd=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(tvl_usd=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_insufficient_none_fields(self):
        r = A().analyze({})
        self.assertIsNone(r["acceleration_ratio"])
        self.assertIsNone(r["vs_baseline_ratio"])
        self.assertIsNone(r["days_to_50pct_drain"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("tvl_usd", "net_outflow_24h_usd", "outflow_rate_pct",
                  "acceleration_pct", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["is_net_inflow"])
        self.assertFalse(r["is_accelerating"])

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_valid_with_tvl(self):
        r = A().analyze(make_pos(tvl_usd=1_000_000.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_higher_rate_scores_lower(self):
        low = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                   net_outflow_24h_usd=50_000.0,
                                   net_outflow_prev_24h_usd=50_000.0,
                                   outflow_3d_avg_usd=0.0))
        high = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                    net_outflow_24h_usd=1_500_000.0,
                                    net_outflow_prev_24h_usd=1_500_000.0,
                                    outflow_3d_avg_usd=0.0))
        self.assertGreater(low["score"], high["score"])

    def test_accelerating_scores_lower(self):
        steady = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                      net_outflow_24h_usd=500_000.0,
                                      net_outflow_prev_24h_usd=500_000.0,
                                      outflow_3d_avg_usd=0.0))
        accel = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                     net_outflow_24h_usd=500_000.0,
                                     net_outflow_prev_24h_usd=100_000.0,
                                     outflow_3d_avg_usd=0.0))
        self.assertGreater(steady["score"], accel["score"])

    def test_above_baseline_scores_lower(self):
        at_baseline = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                           net_outflow_24h_usd=60_000.0,
                                           net_outflow_prev_24h_usd=60_000.0,
                                           outflow_3d_avg_usd=60_000.0))
        spike = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                     net_outflow_24h_usd=180_000.0,
                                     net_outflow_prev_24h_usd=180_000.0,
                                     outflow_3d_avg_usd=60_000.0))
        self.assertGreater(at_baseline["score"], spike["score"])

    def test_net_inflow_high_score(self):
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=-500_000.0,
                                 net_outflow_prev_24h_usd=-400_000.0,
                                 outflow_3d_avg_usd=0.0))
        self.assertGreater(r["score"], 85.0)

    def test_bank_run_low_score(self):
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=3_000_000.0,
                                 net_outflow_prev_24h_usd=500_000.0,
                                 outflow_3d_avg_usd=200_000.0))
        self.assertLess(r["score"], 40.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=1e12,
                                 net_outflow_prev_24h_usd=1e11,
                                 outflow_3d_avg_usd=1e6))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(tvl_usd=10_000_000.0,
                                 net_outflow_24h_usd=9_000_000.0,
                                 net_outflow_prev_24h_usd=100_000.0,
                                 outflow_3d_avg_usd=100_000.0))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(net_outflow_24h_usd=50_000.0),
                    make_pos(net_outflow_24h_usd=500_000.0),
                    make_pos(net_outflow_24h_usd=3_000_000.0),
                    make_pos(tvl_usd=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(net_outflow_24h_usd=-500_000.0),
                    make_pos(net_outflow_24h_usd=3_000_000.0,
                             net_outflow_prev_24h_usd=500_000.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Calm", tvl_usd=10_000_000.0,
                     net_outflow_24h_usd=50_000.0,
                     net_outflow_prev_24h_usd=50_000.0,
                     outflow_3d_avg_usd=60_000.0),
            make_pos(vault="Run", tvl_usd=3_000_000.0,
                     net_outflow_24h_usd=900_000.0,
                     net_outflow_prev_24h_usd=300_000.0,
                     outflow_3d_avg_usd=150_000.0),
            make_pos(vault="Mid", tvl_usd=5_000_000.0,
                     net_outflow_24h_usd=250_000.0,
                     net_outflow_prev_24h_usd=100_000.0,
                     outflow_3d_avg_usd=120_000.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_highest_run_risk_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["highest_run_risk_vault"]],
                         min(scores.values()))

    def test_calmest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["calmest_vault"]], max(scores.values()))

    def test_highest_run_risk_is_run(self):
        self.assertEqual(self.res["aggregate"]["highest_run_risk_vault"], "Run")

    def test_calmest_is_calm(self):
        self.assertEqual(self.res["aggregate"]["calmest_vault"], "Calm")

    def test_bank_run_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["bank_run_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["highest_run_risk_vault"])
        self.assertIsNone(res["aggregate"]["calmest_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(tvl_usd=0.0),
            make_pos(tvl_usd=0.0),
        ])
        self.assertIsNone(res["aggregate"]["highest_run_risk_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["bank_run_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["highest_run_risk_vault"], "Solo")
        self.assertEqual(res["aggregate"]["calmest_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good"),
            make_pos(vault="Ins", tvl_usd=0.0),
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
                make_pos(vault="big", tvl_usd=10_000_000.0,
                         net_outflow_24h_usd=1e12,
                         net_outflow_prev_24h_usd=1e11,
                         outflow_3d_avg_usd=1e6),
                make_pos(vault="ins", tvl_usd=0.0),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            json.loads(raw)

    def test_log_none_fields_serialize_null(self):
        res = A().analyze(make_pos(tvl_usd=0.0))
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
            "tvl_usd": "10000000",
            "net_outflow_24h_usd": "50000",
            "net_outflow_prev_24h_usd": "40000",
            "outflow_3d_avg_usd": "60000",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "tvl_usd": 1_000_000.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(tvl_usd=0.0),
            make_pos(net_outflow_24h_usd=3_000_000.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(net_outflow_24h_usd=3_000_000.0),
                    make_pos(tvl_usd=0.0),
                    make_pos(tvl_usd=10_000_000.0,
                             net_outflow_24h_usd=1e12,
                             net_outflow_prev_24h_usd=1e11,
                             outflow_3d_avg_usd=1e6),
                    make_pos(net_outflow_24h_usd=-1e9,
                             net_outflow_prev_24h_usd=-1e9),
                    make_pos(outflow_3d_avg_usd=-1e9)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(tvl_usd=1e15, net_outflow_24h_usd=1e12))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(net_outflow_24h_usd=-1e6,
                                 outflow_3d_avg_usd=-1e6))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_none_fields_are_none_or_finite(self):
        for pos in [make_pos(), make_pos(tvl_usd=0.0),
                    make_pos(net_outflow_24h_usd=-100_000.0)]:
            r = A().analyze(pos)
            for k in ("acceleration_ratio", "vs_baseline_ratio",
                      "days_to_50pct_drain"):
                v = r[k]
                if v is not None:
                    self.assertTrue(math.isfinite(v))

    def test_zero_outflow_calm(self):
        r = A().analyze(make_pos(net_outflow_24h_usd=0.0,
                                 net_outflow_prev_24h_usd=0.0))
        self.assertEqual(r["classification"], "CALM")


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

    def test_demo_includes_insufficient(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_includes_bank_run_and_calm(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("BANK_RUN", classes)
        self.assertIn("CALM", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("CALM", "ELEVATED", "DRAINING", "BANK_RUN",
                  "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
