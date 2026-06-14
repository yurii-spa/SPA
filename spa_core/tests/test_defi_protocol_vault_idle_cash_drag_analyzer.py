"""
Tests for MP-1157: DeFiProtocolVaultIdleCashDragAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_idle_cash_drag_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_idle_cash_drag_analyzer import (
    DeFiProtocolVaultIdleCashDragAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DEFAULT_TARGET_BUFFER_PCT,
    HEAVY_BUFFER_PCT,
    MOSTLY_IDLE_PCT,
    EFFICIENT_DEPLOYED_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    total_tvl_usd=100_000_000.0,
    idle_cash_usd=3_000_000.0,
    strategy_apr_pct=8.0,
    target_buffer_pct=5.0,
    deployed_usd=None,
):
    p = {
        "vault": vault,
        "total_tvl_usd": total_tvl_usd,
        "strategy_apr_pct": strategy_apr_pct,
        "target_buffer_pct": target_buffer_pct,
    }
    if idle_cash_usd is not None:
        p["idle_cash_usd"] = idle_cash_usd
    if deployed_usd is not None:
        p["deployed_usd"] = deployed_usd
    return p


def A():
    return DeFiProtocolVaultIdleCashDragAnalyzer()


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
        self.assertGreater(DEFAULT_TARGET_BUFFER_PCT, 0)
        self.assertGreater(MOSTLY_IDLE_PCT, HEAVY_BUFFER_PCT)
        self.assertGreater(EFFICIENT_DEPLOYED_PCT, 0)
        self.assertLessEqual(EFFICIENT_DEPLOYED_PCT, 100)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "total_tvl_usd", "idle_cash_usd", "idle_pct",
            "deployed_pct", "strategy_apr_pct", "effective_apr_pct",
            "apr_drag_pct", "target_buffer_pct", "excess_idle_pct",
            "recoverable_apr_pct", "efficiency_score", "classification",
            "recommendation", "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_score_in_range(self):
        self.assertGreaterEqual(self.r["efficiency_score"], 0.0)
        self.assertLessEqual(self.r["efficiency_score"], 100.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_preserved(self):
        self.assertEqual(self.r["token"], "USDC-Vault")

    def test_token_field_alias(self):
        r = A().analyze({"token": "AltKey", "total_tvl_usd": 1e6})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T", "total_tvl_usd": 1e6})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"total_tvl_usd": 1e6})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        for v in self.r.values():
            if isinstance(v, float):
                self.assertFalse(math.isinf(v))
                self.assertFalse(math.isnan(v))

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"],
                      {"DEPLOY", "DEPLOY_CAUTIOUSLY", "AVOID"})

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_idle_plus_deployed_is_100(self):
        self.assertAlmostEqual(
            self.r["idle_pct"] + self.r["deployed_pct"], 100.0, places=4)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_idle_pct_basic(self):
        # 3M idle / 100M = 3%
        r = A().analyze(make_pos(total_tvl_usd=100_000_000.0,
                                 idle_cash_usd=3_000_000.0))
        self.assertAlmostEqual(r["idle_pct"], 3.0)

    def test_deployed_pct_basic(self):
        r = A().analyze(make_pos(total_tvl_usd=100_000_000.0,
                                 idle_cash_usd=3_000_000.0))
        self.assertAlmostEqual(r["deployed_pct"], 97.0)

    def test_idle_from_deployed(self):
        # tvl 100, deployed 80 → idle 20 → 20%
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=None,
                                 deployed_usd=80.0))
        self.assertAlmostEqual(r["idle_pct"], 20.0)

    def test_idle_cash_preferred_over_deployed(self):
        # both given → idle_cash wins
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=10.0,
                                 deployed_usd=50.0))
        self.assertAlmostEqual(r["idle_pct"], 10.0)

    def test_idle_defaults_zero_when_neither(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=None,
                                 deployed_usd=None))
        self.assertAlmostEqual(r["idle_pct"], 0.0)

    def test_idle_clamped_to_tvl(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=200.0))
        self.assertAlmostEqual(r["idle_pct"], 100.0)

    def test_idle_negative_clamped_zero(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=-50.0))
        self.assertAlmostEqual(r["idle_pct"], 0.0)

    def test_idle_from_deployed_over_tvl(self):
        # deployed > tvl → idle clamped to 0
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=None,
                                 deployed_usd=150.0))
        self.assertAlmostEqual(r["idle_pct"], 0.0)

    def test_effective_apr_basic(self):
        # 8% gross, 97% deployed → 7.76%
        r = A().analyze(make_pos(strategy_apr_pct=8.0,
                                 total_tvl_usd=100.0, idle_cash_usd=3.0))
        self.assertAlmostEqual(r["effective_apr_pct"], 8.0 * 0.97)

    def test_apr_drag_basic(self):
        r = A().analyze(make_pos(strategy_apr_pct=8.0,
                                 total_tvl_usd=100.0, idle_cash_usd=3.0))
        self.assertAlmostEqual(r["apr_drag_pct"],
                               8.0 - 8.0 * 0.97)

    def test_apr_drag_zero_when_fully_deployed(self):
        r = A().analyze(make_pos(strategy_apr_pct=8.0,
                                 total_tvl_usd=100.0, idle_cash_usd=0.0))
        self.assertAlmostEqual(r["apr_drag_pct"], 0.0)

    def test_apr_drag_nonnegative(self):
        r = A().analyze(make_pos(strategy_apr_pct=8.0,
                                 total_tvl_usd=100.0, idle_cash_usd=50.0))
        self.assertGreaterEqual(r["apr_drag_pct"], 0.0)

    def test_excess_idle_basic(self):
        # idle 30%, target 5% → excess 25%
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=30.0,
                                 target_buffer_pct=5.0))
        self.assertAlmostEqual(r["excess_idle_pct"], 25.0)

    def test_excess_idle_zero_when_under_target(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=3.0,
                                 target_buffer_pct=5.0))
        self.assertAlmostEqual(r["excess_idle_pct"], 0.0)

    def test_recoverable_apr_basic(self):
        # gross 10%, excess idle 25% → recoverable 2.5%
        r = A().analyze(make_pos(strategy_apr_pct=10.0, total_tvl_usd=100.0,
                                 idle_cash_usd=30.0, target_buffer_pct=5.0))
        self.assertAlmostEqual(r["recoverable_apr_pct"], 2.5)

    def test_recoverable_apr_zero_when_no_excess(self):
        r = A().analyze(make_pos(strategy_apr_pct=10.0, total_tvl_usd=100.0,
                                 idle_cash_usd=3.0, target_buffer_pct=5.0))
        self.assertAlmostEqual(r["recoverable_apr_pct"], 0.0)

    def test_negative_strategy_apr_treated_zero(self):
        r = A().analyze(make_pos(strategy_apr_pct=-5.0))
        self.assertAlmostEqual(r["strategy_apr_pct"], 0.0)

    def test_target_buffer_default(self):
        r = A().analyze({"vault": "V", "total_tvl_usd": 100.0,
                         "idle_cash_usd": 3.0, "strategy_apr_pct": 8.0})
        self.assertAlmostEqual(r["target_buffer_pct"], DEFAULT_TARGET_BUFFER_PCT)

    def test_target_buffer_clamped(self):
        r = A().analyze(make_pos(target_buffer_pct=200.0))
        self.assertAlmostEqual(r["target_buffer_pct"], 100.0)


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_fully_deployed(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=3.0,
                                 target_buffer_pct=5.0))
        self.assertEqual(r["classification"], "FULLY_DEPLOYED")

    def test_lean_buffer(self):
        # idle 10%, above target 5%, below heavy 20%
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=10.0,
                                 target_buffer_pct=5.0))
        self.assertEqual(r["classification"], "LEAN_BUFFER")

    def test_heavy_buffer(self):
        # idle 30%, above heavy 20%, below mostly 50%
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=30.0,
                                 target_buffer_pct=5.0))
        self.assertEqual(r["classification"], "HEAVY_BUFFER")

    def test_mostly_idle(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=70.0,
                                 target_buffer_pct=5.0))
        self.assertEqual(r["classification"], "MOSTLY_IDLE")

    def test_classification_known_value(self):
        for pos in [make_pos(), make_pos(idle_cash_usd=70_000_000.0),
                    make_pos(total_tvl_usd=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "FULLY_DEPLOYED", "LEAN_BUFFER", "HEAVY_BUFFER",
                "MOSTLY_IDLE", "INSUFFICIENT_DATA",
            })

    def test_boundary_idle_equals_target_fully_deployed(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=5.0,
                                 target_buffer_pct=5.0))
        self.assertEqual(r["classification"], "FULLY_DEPLOYED")

    def test_boundary_heavy_buffer_at_20(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=20.0,
                                 target_buffer_pct=5.0))
        self.assertEqual(r["classification"], "HEAVY_BUFFER")

    def test_boundary_mostly_idle_at_50(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=50.0,
                                 target_buffer_pct=5.0))
        self.assertEqual(r["classification"], "MOSTLY_IDLE")

    def test_high_target_buffer_keeps_fully_deployed(self):
        # idle 15% but target 30% → still fully deployed band? idle<heavy? no
        # idle 15% < heavy 20% and idle<=target 30% → FULLY_DEPLOYED
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=15.0,
                                 target_buffer_pct=30.0))
        self.assertEqual(r["classification"], "FULLY_DEPLOYED")


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_deploy_when_fully_deployed(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=3.0))
        self.assertEqual(r["recommendation"], "DEPLOY")

    def test_deploy_when_lean_buffer(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=10.0))
        self.assertEqual(r["recommendation"], "DEPLOY")

    def test_deploy_cautiously_when_heavy(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=30.0))
        self.assertEqual(r["recommendation"], "DEPLOY_CAUTIOUSLY")

    def test_avoid_when_mostly_idle(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=70.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_avoid_when_insufficient(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertEqual(r["recommendation"], "AVOID")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_fully_deployed_flag(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=3.0))
        self.assertIn("FULLY_DEPLOYED", r["flags"])

    def test_fully_deployed_flag_absent(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=30.0))
        self.assertNotIn("FULLY_DEPLOYED", r["flags"])

    def test_capital_efficient_flag(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=3.0))
        self.assertIn("CAPITAL_EFFICIENT", r["flags"])

    def test_capital_efficient_flag_absent(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=30.0))
        self.assertNotIn("CAPITAL_EFFICIENT", r["flags"])

    def test_excess_idle_cash_flag(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=30.0,
                                 target_buffer_pct=5.0))
        self.assertIn("EXCESS_IDLE_CASH", r["flags"])

    def test_excess_idle_cash_flag_absent(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=3.0,
                                 target_buffer_pct=5.0))
        self.assertNotIn("EXCESS_IDLE_CASH", r["flags"])

    def test_heavy_buffer_flag(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=30.0))
        self.assertIn("HEAVY_BUFFER", r["flags"])

    def test_heavy_buffer_flag_absent(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=10.0))
        self.assertNotIn("HEAVY_BUFFER", r["flags"])

    def test_mostly_idle_flag(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=70.0))
        self.assertIn("MOSTLY_IDLE", r["flags"])

    def test_mostly_idle_flag_absent(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=10.0))
        self.assertNotIn("MOSTLY_IDLE", r["flags"])

    def test_zero_strategy_yield_flag(self):
        r = A().analyze(make_pos(strategy_apr_pct=0.0))
        self.assertIn("ZERO_STRATEGY_YIELD", r["flags"])

    def test_zero_strategy_yield_flag_absent(self):
        r = A().analyze(make_pos(strategy_apr_pct=8.0))
        self.assertNotIn("ZERO_STRATEGY_YIELD", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_mostly_idle_also_heavy_buffer(self):
        # mostly idle (>=50) is also >= heavy threshold
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=70.0))
        self.assertIn("HEAVY_BUFFER", r["flags"])
        self.assertIn("MOSTLY_IDLE", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_zero_tvl(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_negative_tvl(self):
        r = A().analyze(make_pos(total_tvl_usd=-100.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertEqual(r["efficiency_score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_insufficient_zero_metrics(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertEqual(r["idle_pct"], 0.0)
        self.assertEqual(r["deployed_pct"], 0.0)
        self.assertEqual(r["apr_drag_pct"], 0.0)

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_zero_idle_is_sufficient(self):
        # zero idle, tvl present → analyzable (fully deployed)
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_more_deployed_scores_higher(self):
        low_deploy = A().analyze(make_pos(total_tvl_usd=100.0,
                                          idle_cash_usd=60.0))
        high_deploy = A().analyze(make_pos(total_tvl_usd=100.0,
                                           idle_cash_usd=5.0))
        self.assertGreater(high_deploy["efficiency_score"],
                           low_deploy["efficiency_score"])

    def test_less_excess_idle_scores_higher(self):
        much_excess = A().analyze(make_pos(total_tvl_usd=100.0,
                                           idle_cash_usd=40.0,
                                           target_buffer_pct=5.0))
        little_excess = A().analyze(make_pos(total_tvl_usd=100.0,
                                             idle_cash_usd=8.0,
                                             target_buffer_pct=5.0))
        self.assertGreater(little_excess["efficiency_score"],
                           much_excess["efficiency_score"])

    def test_mostly_idle_scores_low(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=80.0,
                                 target_buffer_pct=5.0))
        self.assertLess(r["efficiency_score"], 55.0)

    def test_fully_deployed_scores_high(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=2.0,
                                 target_buffer_pct=5.0))
        self.assertGreater(r["efficiency_score"], 85.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=0.0,
                                 target_buffer_pct=0.0))
        self.assertLessEqual(r["efficiency_score"], 100.0)
        self.assertGreaterEqual(r["efficiency_score"], 0.0)

    def test_score_floor_all_idle(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=100.0,
                                 target_buffer_pct=5.0))
        self.assertGreaterEqual(r["efficiency_score"], 0.0)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Efficient", total_tvl_usd=100.0, idle_cash_usd=2.0),
            make_pos(vault="Idle", total_tvl_usd=100.0, idle_cash_usd=80.0),
            make_pos(vault="Mid", total_tvl_usd=100.0, idle_cash_usd=25.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_idle_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["efficiency_score"]
                  for p in self.res["positions"]}
        most = agg["most_idle_vault"]
        self.assertEqual(scores[most], min(scores.values()))

    def test_least_idle_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["efficiency_score"]
                  for p in self.res["positions"]}
        least = agg["least_idle_vault"]
        self.assertEqual(scores[least], max(scores.values()))

    def test_most_idle_is_idle(self):
        self.assertEqual(self.res["aggregate"]["most_idle_vault"], "Idle")

    def test_least_idle_is_efficient(self):
        self.assertEqual(self.res["aggregate"]["least_idle_vault"], "Efficient")

    def test_mostly_idle_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["mostly_idle_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_efficiency_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_idle_vault"])
        self.assertIsNone(res["aggregate"]["least_idle_vault"])

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(total_tvl_usd=0.0), make_pos(total_tvl_usd=-1.0),
        ])
        self.assertIsNone(res["aggregate"]["most_idle_vault"])
        self.assertEqual(res["aggregate"]["avg_efficiency_score"], 0.0)

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)


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
                make_pos(vault="idle", idle_cash_usd=90_000_000.0),
                make_pos(vault="ins", total_tvl_usd=0.0),
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
            for k in ("token", "classification", "efficiency_score",
                      "recommendation", "flags"):
                self.assertIn(k, snap)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "vault": "S",
            "total_tvl_usd": "100",
            "idle_cash_usd": "10",
            "strategy_apr_pct": "8",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "total_tvl_usd": 100.0})
        self.assertIn("classification", r)

    def test_only_tvl_given(self):
        r = A().analyze({"vault": "S", "total_tvl_usd": 100.0})
        # no idle, no deployed → idle 0 → fully deployed
        self.assertEqual(r["classification"], "FULLY_DEPLOYED")

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio([make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(), make_pos(total_tvl_usd=0.0),
            make_pos(idle_cash_usd=80_000_000.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(), make_pos(total_tvl_usd=0.0),
                    make_pos(idle_cash_usd=100_000_000.0),
                    make_pos(idle_cash_usd=0.0, strategy_apr_pct=0.0),
                    make_pos(total_tvl_usd=1.0, idle_cash_usd=1.0)]:
            r = A().analyze(pos)
            for v in r.values():
                if isinstance(v, float):
                    self.assertFalse(math.isinf(v))
                    self.assertFalse(math.isnan(v))

    def test_deployed_zero_no_crash(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=None,
                                 deployed_usd=0.0))
        self.assertIn("classification", r)
        self.assertAlmostEqual(r["idle_pct"], 100.0)

    def test_idle_cash_zero_explicit(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, idle_cash_usd=0.0,
                                 deployed_usd=50.0))
        # explicit idle 0 preferred → idle 0
        self.assertAlmostEqual(r["idle_pct"], 0.0)


# ── CLI smoke ─────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_demo_positions_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

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


if __name__ == "__main__":
    unittest.main()
