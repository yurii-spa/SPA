"""
Tests for MP-1159: DeFiProtocolVaultRoundTripCostAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_round_trip_cost_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_round_trip_cost_analyzer import (
    DeFiProtocolVaultRoundTripCostAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DAYS_PER_YEAR,
    CHEAP_DAYS,
    FAIR_DAYS,
    EXPENSIVE_DAYS,
    HIGH_ROUND_TRIP_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    deposit_fee_pct=0.1,
    withdrawal_fee_pct=0.1,
    entry_slippage_pct=0.0,
    exit_slippage_pct=0.0,
    apr_advantage_pct=5.0,
    expected_holding_days=30.0,
):
    return {
        "vault": vault,
        "deposit_fee_pct": deposit_fee_pct,
        "withdrawal_fee_pct": withdrawal_fee_pct,
        "entry_slippage_pct": entry_slippage_pct,
        "exit_slippage_pct": exit_slippage_pct,
        "apr_advantage_pct": apr_advantage_pct,
        "expected_holding_days": expected_holding_days,
    }


def A():
    return DeFiProtocolVaultRoundTripCostAnalyzer()


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
        self.assertLess(CHEAP_DAYS, FAIR_DAYS)
        self.assertLess(FAIR_DAYS, EXPENSIVE_DAYS)
        self.assertGreater(HIGH_ROUND_TRIP_PCT, 0)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "deposit_fee_pct", "withdrawal_fee_pct",
            "entry_slippage_pct", "exit_slippage_pct", "round_trip_cost_pct",
            "apr_advantage_pct", "daily_advantage_pct", "breakeven_days",
            "expected_holding_days", "net_gain_pct", "covers_horizon",
            "cost_score", "classification", "recommendation", "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_score_in_range(self):
        self.assertGreaterEqual(self.r["cost_score"], 0.0)
        self.assertLessEqual(self.r["cost_score"], 100.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_preserved(self):
        self.assertEqual(self.r["token"], "USDC-Vault")

    def test_token_field_alias(self):
        r = A().analyze({"token": "AltKey", "deposit_fee_pct": 0.1,
                         "apr_advantage_pct": 5.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T", "deposit_fee_pct": 0.1,
                         "apr_advantage_pct": 5.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"deposit_fee_pct": 0.1, "apr_advantage_pct": 5.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        for v in self.r.values():
            if isinstance(v, float):
                self.assertFalse(math.isinf(v))
                self.assertFalse(math.isnan(v))

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "ROTATE", "ROTATE_IF_LONG_HOLD", "STAY", "AVOID",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_covers_horizon_is_bool(self):
        self.assertIsInstance(self.r["covers_horizon"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_round_trip_cost_sum(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.1, withdrawal_fee_pct=0.2,
                                 entry_slippage_pct=0.05, exit_slippage_pct=0.05))
        self.assertAlmostEqual(r["round_trip_cost_pct"], 0.4)

    def test_round_trip_cost_zero(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0))
        self.assertAlmostEqual(r["round_trip_cost_pct"], 0.0)

    def test_each_component_clamped(self):
        r = A().analyze(make_pos(deposit_fee_pct=200.0, withdrawal_fee_pct=0.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0))
        self.assertAlmostEqual(r["deposit_fee_pct"], 100.0)

    def test_negative_fee_clamped(self):
        r = A().analyze(make_pos(deposit_fee_pct=-5.0, withdrawal_fee_pct=0.1))
        self.assertAlmostEqual(r["deposit_fee_pct"], 0.0)

    def test_daily_advantage_basic(self):
        # apr 5% / 365 = 0.0136986%
        r = A().analyze(make_pos(apr_advantage_pct=5.0))
        self.assertAlmostEqual(r["daily_advantage_pct"], 5.0 / 365.0, places=6)

    def test_breakeven_basic(self):
        # cost 0.2%, daily 5/365=0.0136986 → ~14.6 days
        r = A().analyze(make_pos(deposit_fee_pct=0.1, withdrawal_fee_pct=0.1,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0))
        self.assertAlmostEqual(r["breakeven_days"], 0.2 / (5.0 / 365.0), places=2)

    def test_breakeven_none_when_no_advantage(self):
        r = A().analyze(make_pos(apr_advantage_pct=0.0, deposit_fee_pct=0.1))
        self.assertIsNone(r["breakeven_days"])

    def test_breakeven_none_when_negative_advantage(self):
        r = A().analyze(make_pos(apr_advantage_pct=-5.0, deposit_fee_pct=0.1))
        self.assertIsNone(r["breakeven_days"])

    def test_net_gain_basic(self):
        # apr 5%, 30 days, cost 0.2% → 5*30/365 - 0.2
        r = A().analyze(make_pos(deposit_fee_pct=0.1, withdrawal_fee_pct=0.1,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0, expected_holding_days=30.0))
        self.assertAlmostEqual(r["net_gain_pct"], 5.0 * 30.0 / 365.0 - 0.2,
                               places=4)

    def test_net_gain_negative_short_horizon(self):
        # cost 1%, tiny horizon → negative
        r = A().analyze(make_pos(deposit_fee_pct=0.5, withdrawal_fee_pct=0.5,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0, expected_holding_days=1.0))
        self.assertLess(r["net_gain_pct"], 0.0)

    def test_covers_horizon_true(self):
        # breakeven ~14.6 days < 30 day horizon
        r = A().analyze(make_pos(deposit_fee_pct=0.1, withdrawal_fee_pct=0.1,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0, expected_holding_days=30.0))
        self.assertTrue(r["covers_horizon"])

    def test_covers_horizon_false_short(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.1, withdrawal_fee_pct=0.1,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0, expected_holding_days=5.0))
        self.assertFalse(r["covers_horizon"])

    def test_covers_horizon_false_no_advantage(self):
        r = A().analyze(make_pos(apr_advantage_pct=0.0, deposit_fee_pct=0.1,
                                 expected_holding_days=30.0))
        self.assertFalse(r["covers_horizon"])

    def test_covers_horizon_false_zero_horizon(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.1, withdrawal_fee_pct=0.1,
                                 apr_advantage_pct=5.0, expected_holding_days=0.0))
        self.assertFalse(r["covers_horizon"])

    def test_holding_days_negative_clamped(self):
        r = A().analyze(make_pos(expected_holding_days=-10.0))
        self.assertAlmostEqual(r["expected_holding_days"], 0.0)

    def test_apr_advantage_preserved(self):
        r = A().analyze(make_pos(apr_advantage_pct=7.5))
        self.assertAlmostEqual(r["apr_advantage_pct"], 7.5)


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_cheap(self):
        # cost 0.05%, apr 5% → breakeven ~3.65 days <= 7
        r = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.05,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0))
        self.assertEqual(r["classification"], "CHEAP")

    def test_fair(self):
        # breakeven ~14.6 days in (7, 30]
        r = A().analyze(make_pos(deposit_fee_pct=0.1, withdrawal_fee_pct=0.1,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0))
        self.assertEqual(r["classification"], "FAIR")

    def test_expensive(self):
        # cost 1.2%, apr 6% → breakeven 73 days in (30, 90]
        r = A().analyze(make_pos(deposit_fee_pct=0.5, withdrawal_fee_pct=0.5,
                                 entry_slippage_pct=0.1, exit_slippage_pct=0.1,
                                 apr_advantage_pct=6.0))
        self.assertEqual(r["classification"], "EXPENSIVE")

    def test_prohibitive(self):
        # cost 1.2%, apr 3% → breakeven 146 days > 90
        r = A().analyze(make_pos(deposit_fee_pct=0.5, withdrawal_fee_pct=0.5,
                                 entry_slippage_pct=0.1, exit_slippage_pct=0.1,
                                 apr_advantage_pct=3.0))
        self.assertEqual(r["classification"], "PROHIBITIVE")

    def test_never_breaks_even(self):
        r = A().analyze(make_pos(apr_advantage_pct=0.0, deposit_fee_pct=0.1,
                                 withdrawal_fee_pct=0.1))
        self.assertEqual(r["classification"], "NEVER_BREAKS_EVEN")

    def test_insufficient_when_nothing(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_boundary_cheap_at_7(self):
        # breakeven exactly 7 days → CHEAP. cost 0.13424..., apr 7
        # daily = 7/365; cost = 7 * 7/365 = 0.13424657...
        cost = 7.0 * (7.0 / 365.0)
        r = A().analyze(make_pos(deposit_fee_pct=cost, withdrawal_fee_pct=0.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=7.0))
        self.assertEqual(r["classification"], "CHEAP")

    def test_classification_known_value(self):
        for pos in [make_pos(), make_pos(apr_advantage_pct=0.0),
                    make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                             entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                             apr_advantage_pct=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "CHEAP", "FAIR", "EXPENSIVE", "PROHIBITIVE",
                "NEVER_BREAKS_EVEN", "INSUFFICIENT_DATA",
            })

    def test_free_entry_with_advantage_is_cheap(self):
        # zero cost but positive advantage → breakeven 0 → CHEAP
        r = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0))
        self.assertEqual(r["classification"], "CHEAP")


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_rotate_when_cheap_covers(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.05,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0, expected_holding_days=30.0))
        self.assertEqual(r["recommendation"], "ROTATE")

    def test_rotate_when_fair_covers(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.1, withdrawal_fee_pct=0.1,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0, expected_holding_days=30.0))
        self.assertEqual(r["recommendation"], "ROTATE")

    def test_rotate_if_long_hold_when_expensive(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.5, withdrawal_fee_pct=0.5,
                                 entry_slippage_pct=0.1, exit_slippage_pct=0.1,
                                 apr_advantage_pct=6.0, expected_holding_days=14.0))
        self.assertEqual(r["recommendation"], "ROTATE_IF_LONG_HOLD")

    def test_stay_when_prohibitive(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.5, withdrawal_fee_pct=0.5,
                                 entry_slippage_pct=0.1, exit_slippage_pct=0.1,
                                 apr_advantage_pct=3.0, expected_holding_days=14.0))
        self.assertEqual(r["recommendation"], "STAY")

    def test_stay_when_never_breaks_even(self):
        r = A().analyze(make_pos(apr_advantage_pct=0.0, deposit_fee_pct=0.1,
                                 withdrawal_fee_pct=0.1))
        self.assertEqual(r["recommendation"], "STAY")

    def test_avoid_when_insufficient(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_stay_when_cheap_but_horizon_short(self):
        # cheap break-even but horizon doesn't cover → STAY
        r = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.05,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0, expected_holding_days=1.0))
        self.assertEqual(r["recommendation"], "STAY")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_free_entry_exit_flag(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0))
        self.assertIn("FREE_ENTRY_EXIT", r["flags"])

    def test_free_entry_exit_flag_absent_with_cost(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.1, apr_advantage_pct=5.0))
        self.assertNotIn("FREE_ENTRY_EXIT", r["flags"])

    def test_free_entry_exit_flag_absent_no_advantage(self):
        # zero cost AND zero advantage → insufficient, not free-entry
        r = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=0.0))
        self.assertNotIn("FREE_ENTRY_EXIT", r["flags"])

    def test_breaks_even_in_horizon_flag(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.1, withdrawal_fee_pct=0.1,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0, expected_holding_days=30.0))
        self.assertIn("BREAKS_EVEN_IN_HORIZON", r["flags"])

    def test_breaks_even_in_horizon_flag_absent(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.1, withdrawal_fee_pct=0.1,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0, expected_holding_days=2.0))
        self.assertNotIn("BREAKS_EVEN_IN_HORIZON", r["flags"])

    def test_never_breaks_even_flag(self):
        r = A().analyze(make_pos(apr_advantage_pct=0.0, deposit_fee_pct=0.1,
                                 withdrawal_fee_pct=0.1))
        self.assertIn("NEVER_BREAKS_EVEN", r["flags"])

    def test_never_breaks_even_flag_absent(self):
        r = A().analyze(make_pos(apr_advantage_pct=5.0))
        self.assertNotIn("NEVER_BREAKS_EVEN", r["flags"])

    def test_high_round_trip_cost_flag(self):
        r = A().analyze(make_pos(deposit_fee_pct=1.0, withdrawal_fee_pct=1.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0))
        self.assertIn("HIGH_ROUND_TRIP_COST", r["flags"])

    def test_high_round_trip_cost_flag_at_2(self):
        r = A().analyze(make_pos(deposit_fee_pct=1.0, withdrawal_fee_pct=1.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0))
        self.assertIn("HIGH_ROUND_TRIP_COST", r["flags"])

    def test_high_round_trip_cost_flag_absent(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.1, withdrawal_fee_pct=0.1,
                                 apr_advantage_pct=5.0))
        self.assertNotIn("HIGH_ROUND_TRIP_COST", r["flags"])

    def test_negative_net_at_horizon_flag(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.5, withdrawal_fee_pct=0.5,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0, expected_holding_days=1.0))
        self.assertIn("NEGATIVE_NET_AT_HORIZON", r["flags"])

    def test_negative_net_at_horizon_flag_absent(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.1, withdrawal_fee_pct=0.1,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0, expected_holding_days=60.0))
        self.assertNotIn("NEGATIVE_NET_AT_HORIZON", r["flags"])

    def test_negative_net_flag_absent_zero_horizon(self):
        # zero horizon → net flag suppressed
        r = A().analyze(make_pos(deposit_fee_pct=0.5, withdrawal_fee_pct=0.5,
                                 apr_advantage_pct=5.0, expected_holding_days=0.0))
        self.assertNotIn("NEGATIVE_NET_AT_HORIZON", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_cost_no_advantage(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=0.0))
        self.assertEqual(r["cost_score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=0.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_insufficient_breakeven_none(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=0.0))
        self.assertIsNone(r["breakeven_days"])

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_only_cost_is_sufficient(self):
        # cost present, no advantage → NEVER_BREAKS_EVEN (assessable)
        r = A().analyze(make_pos(deposit_fee_pct=0.1, withdrawal_fee_pct=0.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_only_advantage_is_sufficient(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_cheaper_scores_higher(self):
        cheap = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.05,
                                     entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                     apr_advantage_pct=5.0,
                                     expected_holding_days=60.0))
        pricey = A().analyze(make_pos(deposit_fee_pct=0.8, withdrawal_fee_pct=0.8,
                                      entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                      apr_advantage_pct=5.0,
                                      expected_holding_days=60.0))
        self.assertGreater(cheap["cost_score"], pricey["cost_score"])

    def test_cheap_scores_high(self):
        r = A().analyze(make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.05,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                 apr_advantage_pct=5.0, expected_holding_days=60.0))
        self.assertGreater(r["cost_score"], 85.0)

    def test_never_breaks_even_scores_low(self):
        r = A().analyze(make_pos(apr_advantage_pct=0.0, deposit_fee_pct=1.0,
                                 withdrawal_fee_pct=1.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0))
        self.assertLess(r["cost_score"], 55.0)

    def test_covers_horizon_scores_higher_than_not(self):
        covers = A().analyze(make_pos(deposit_fee_pct=0.1, withdrawal_fee_pct=0.1,
                                      entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                                      apr_advantage_pct=5.0,
                                      expected_holding_days=60.0))
        no_cover = A().analyze(make_pos(deposit_fee_pct=0.1, withdrawal_fee_pct=0.1,
                                        entry_slippage_pct=0.0,
                                        exit_slippage_pct=0.0,
                                        apr_advantage_pct=5.0,
                                        expected_holding_days=1.0))
        self.assertGreater(covers["cost_score"], no_cover["cost_score"])

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(deposit_fee_pct=50.0, withdrawal_fee_pct=50.0,
                                 entry_slippage_pct=50.0, exit_slippage_pct=50.0,
                                 apr_advantage_pct=1.0, expected_holding_days=1.0))
        self.assertLessEqual(r["cost_score"], 100.0)
        self.assertGreaterEqual(r["cost_score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(apr_advantage_pct=0.0, deposit_fee_pct=2.0,
                                 withdrawal_fee_pct=2.0,
                                 entry_slippage_pct=0.0, exit_slippage_pct=0.0))
        self.assertGreaterEqual(r["cost_score"], 0.0)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Cheap", deposit_fee_pct=0.0, withdrawal_fee_pct=0.05,
                     entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                     apr_advantage_pct=5.0, expected_holding_days=60.0),
            make_pos(vault="Pricey", deposit_fee_pct=0.8, withdrawal_fee_pct=0.8,
                     entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                     apr_advantage_pct=3.0, expected_holding_days=14.0),
            make_pos(vault="Mid", deposit_fee_pct=0.1, withdrawal_fee_pct=0.1,
                     entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                     apr_advantage_pct=5.0, expected_holding_days=30.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_cheapest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["cost_score"] for p in self.res["positions"]}
        cheapest = agg["cheapest_vault"]
        self.assertEqual(scores[cheapest], max(scores.values()))

    def test_most_expensive_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["cost_score"] for p in self.res["positions"]}
        priciest = agg["most_expensive_vault"]
        self.assertEqual(scores[priciest], min(scores.values()))

    def test_cheapest_is_cheap_vault(self):
        self.assertEqual(self.res["aggregate"]["cheapest_vault"], "Cheap")

    def test_most_expensive_is_pricey_vault(self):
        self.assertEqual(self.res["aggregate"]["most_expensive_vault"], "Pricey")

    def test_rotate_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["rotate_count"], 1)

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

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                     entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                     apr_advantage_pct=0.0),
            make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                     entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                     apr_advantage_pct=0.0),
        ])
        self.assertIsNone(res["aggregate"]["cheapest_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_rotate_count_counts_long_hold(self):
        # ROTATE_IF_LONG_HOLD also startswith ROTATE
        res = A().analyze_portfolio([
            make_pos(vault="Exp", deposit_fee_pct=0.5, withdrawal_fee_pct=0.5,
                     entry_slippage_pct=0.1, exit_slippage_pct=0.1,
                     apr_advantage_pct=6.0, expected_holding_days=14.0),
        ])
        self.assertEqual(res["aggregate"]["rotate_count"], 1)


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
                make_pos(vault="big", deposit_fee_pct=50.0,
                         withdrawal_fee_pct=50.0),
                make_pos(vault="ins", deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                         entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                         apr_advantage_pct=0.0),
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
            for k in ("token", "classification", "cost_score",
                      "recommendation", "flags"):
                self.assertIn(k, snap)

    def test_log_does_not_touch_production(self):
        before = os.path.exists(LOG_PATH)
        A().analyze(make_pos())
        after = os.path.exists(LOG_PATH)
        self.assertEqual(before, after)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "vault": "S",
            "deposit_fee_pct": "0.1",
            "withdrawal_fee_pct": "0.1",
            "entry_slippage_pct": "0",
            "exit_slippage_pct": "0",
            "apr_advantage_pct": "5",
            "expected_holding_days": "30",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "apr_advantage_pct": 5.0})
        self.assertIn("classification", r)

    def test_only_advantage_given(self):
        r = A().analyze({"vault": "S", "apr_advantage_pct": 5.0})
        # zero cost, positive advantage → CHEAP
        self.assertEqual(r["classification"], "CHEAP")

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(apr_advantage_pct=0.0, deposit_fee_pct=0.1),
            make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                     entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                     apr_advantage_pct=0.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(apr_advantage_pct=0.0),
                    make_pos(apr_advantage_pct=-5.0),
                    make_pos(deposit_fee_pct=50.0, withdrawal_fee_pct=50.0,
                             entry_slippage_pct=50.0, exit_slippage_pct=50.0),
                    make_pos(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0,
                             entry_slippage_pct=0.0, exit_slippage_pct=0.0,
                             apr_advantage_pct=0.0),
                    make_pos(expected_holding_days=0.0)]:
            r = A().analyze(pos)
            for v in r.values():
                if isinstance(v, float):
                    self.assertFalse(math.isinf(v))
                    self.assertFalse(math.isnan(v))

    def test_zero_advantage_no_crash(self):
        r = A().analyze(make_pos(apr_advantage_pct=0.0))
        self.assertIn("classification", r)

    def test_negative_advantage_never_breaks(self):
        r = A().analyze(make_pos(apr_advantage_pct=-3.0))
        self.assertIsNone(r["breakeven_days"])

    def test_huge_cost_no_crash(self):
        r = A().analyze(make_pos(deposit_fee_pct=99.0, withdrawal_fee_pct=99.0,
                                 entry_slippage_pct=99.0, exit_slippage_pct=99.0,
                                 apr_advantage_pct=5.0))
        self.assertIn("classification", r)
        self.assertLessEqual(r["round_trip_cost_pct"], 400.0)


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

    def test_demo_includes_cheap(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("CHEAP", classes)

    def test_demo_includes_never_breaks_even(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("NEVER_BREAKS_EVEN", classes)


if __name__ == "__main__":
    unittest.main()
