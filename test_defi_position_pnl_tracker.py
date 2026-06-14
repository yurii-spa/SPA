"""
Tests for MP-899 DeFiPositionPnLTracker
Run: python3 -m unittest spa_core.tests.test_defi_position_pnl_tracker -v
"""

import json
import math
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_position_pnl_tracker import (
    analyze,
    log_result,
    _safe_div,
    _safe_mean,
    _performance_label,
    _status,
    _build_flags,
    _recommendation,
    _analyse_position,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def make_pos(**overrides) -> dict:
    base = {
        "protocol": "Aave V3",
        "position_type": "LENDING",
        "entry_value_usd": 10_000.0,
        "current_value_usd": 10_000.0,
        "fees_earned_usd": 300.0,
        "rewards_earned_usd": 0.0,
        "il_loss_usd": 0.0,
        "gas_costs_usd": 20.0,
        "days_held": 90,
    }
    base.update(overrides)
    return base


def expected_net_pnl(pos: dict) -> float:
    entry   = float(pos["entry_value_usd"])
    current = float(pos["current_value_usd"])
    fees    = float(pos["fees_earned_usd"])
    rewards = float(pos.get("rewards_earned_usd", 0.0))
    il      = float(pos["il_loss_usd"])
    gas     = float(pos["gas_costs_usd"])
    return (current - entry + fees + rewards) - il - gas


def expected_annualized(pos: dict, benchmark: float = 5.0) -> float:
    entry = float(pos["entry_value_usd"])
    days  = int(pos["days_held"])
    net   = expected_net_pnl(pos)
    pct   = (net / entry * 100) if entry > 0 else 0.0
    return (pct / days * 365) if days > 0 else 0.0


# ===========================================================================
# 1. _safe_div
# ===========================================================================
class TestSafeDiv(unittest.TestCase):

    def test_normal(self):
        self.assertAlmostEqual(_safe_div(10.0, 4.0), 2.5)

    def test_zero_denominator(self):
        self.assertEqual(_safe_div(100.0, 0.0), 0.0)

    def test_zero_numerator(self):
        self.assertEqual(_safe_div(0.0, 5.0), 0.0)

    def test_negative_numerator(self):
        self.assertAlmostEqual(_safe_div(-6.0, 3.0), -2.0)

    def test_both_zero(self):
        self.assertEqual(_safe_div(0.0, 0.0), 0.0)


# ===========================================================================
# 2. _safe_mean
# ===========================================================================
class TestSafeMean(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(_safe_mean([]), 0.0)

    def test_single(self):
        self.assertEqual(_safe_mean([7.0]), 7.0)

    def test_multiple(self):
        self.assertAlmostEqual(_safe_mean([1.0, 2.0, 3.0]), 2.0)

    def test_negatives(self):
        self.assertAlmostEqual(_safe_mean([-4.0, 4.0]), 0.0)


# ===========================================================================
# 3. _performance_label
# ===========================================================================
class TestPerformanceLabel(unittest.TestCase):

    def test_loss_negative_pnl(self):
        self.assertEqual(_performance_label(-100.0, 20.0), "LOSS")

    def test_exceptional(self):
        self.assertEqual(_performance_label(100.0, 15.0), "EXCEPTIONAL")

    def test_exceptional_exactly_10(self):
        # alpha=10 is NOT > 10, so should be OUTPERFORM
        self.assertEqual(_performance_label(100.0, 10.0), "OUTPERFORM")

    def test_outperform(self):
        self.assertEqual(_performance_label(100.0, 3.0), "OUTPERFORM")

    def test_outperform_near_zero(self):
        self.assertEqual(_performance_label(1.0, 0.01), "OUTPERFORM")

    def test_underperform(self):
        self.assertEqual(_performance_label(100.0, -6.0), "UNDERPERFORM")

    def test_underperform_exactly_minus5(self):
        # alpha=-5 IS <= -5, so UNDERPERFORM
        self.assertEqual(_performance_label(100.0, -5.0), "UNDERPERFORM")

    def test_benchmark_negative_small(self):
        self.assertEqual(_performance_label(100.0, -2.0), "BENCHMARK")

    def test_benchmark_zero_alpha(self):
        # alpha=0 is not >0 and not <=-5, so BENCHMARK
        self.assertEqual(_performance_label(50.0, 0.0), "BENCHMARK")


# ===========================================================================
# 4. _status
# ===========================================================================
class TestStatus(unittest.TestCase):

    def test_profitable(self):
        self.assertEqual(_status(150.0, 10_000.0), "PROFITABLE")

    def test_losing(self):
        self.assertEqual(_status(-200.0, 10_000.0), "LOSING")

    def test_breakeven_near_zero(self):
        self.assertEqual(_status(50.0, 10_000.0), "BREAKEVEN")

    def test_breakeven_exactly_threshold(self):
        # threshold = 10000 * 0.01 = 100; net_pnl = 100 → NOT > threshold
        self.assertEqual(_status(100.0, 10_000.0), "BREAKEVEN")

    def test_just_above_profitable_threshold(self):
        self.assertEqual(_status(101.0, 10_000.0), "PROFITABLE")

    def test_zero_entry(self):
        # threshold = 0; net_pnl=0 → BREAKEVEN
        self.assertEqual(_status(0.0, 0.0), "BREAKEVEN")

    def test_large_loss(self):
        self.assertEqual(_status(-5000.0, 10_000.0), "LOSING")


# ===========================================================================
# 5. _build_flags
# ===========================================================================
class TestBuildFlags(unittest.TestCase):

    def test_no_flags(self):
        flags = _build_flags(il_drag_pct=1.0, gas_costs_usd=10.0,
                              entry_value_usd=10_000.0, alpha_pct=3.0,
                              days_held=30)
        self.assertEqual(flags, [])

    def test_high_il(self):
        flags = _build_flags(il_drag_pct=6.0, gas_costs_usd=10.0,
                              entry_value_usd=10_000.0, alpha_pct=3.0,
                              days_held=30)
        self.assertIn("HIGH_IL", flags)

    def test_high_il_exactly_5_not_flagged(self):
        flags = _build_flags(il_drag_pct=5.0, gas_costs_usd=10.0,
                              entry_value_usd=10_000.0, alpha_pct=3.0,
                              days_held=30)
        self.assertNotIn("HIGH_IL", flags)

    def test_gas_heavy(self):
        flags = _build_flags(il_drag_pct=1.0, gas_costs_usd=300.0,
                              entry_value_usd=10_000.0, alpha_pct=3.0,
                              days_held=30)
        self.assertIn("GAS_HEAVY", flags)

    def test_gas_heavy_boundary_not_flagged(self):
        # exactly 2% → not strictly greater
        flags = _build_flags(il_drag_pct=1.0, gas_costs_usd=200.0,
                              entry_value_usd=10_000.0, alpha_pct=3.0,
                              days_held=30)
        self.assertNotIn("GAS_HEAVY", flags)

    def test_below_benchmark(self):
        flags = _build_flags(il_drag_pct=1.0, gas_costs_usd=10.0,
                              entry_value_usd=10_000.0, alpha_pct=-1.0,
                              days_held=30)
        self.assertIn("BELOW_BENCHMARK", flags)

    def test_short_hold(self):
        flags = _build_flags(il_drag_pct=1.0, gas_costs_usd=10.0,
                              entry_value_usd=10_000.0, alpha_pct=3.0,
                              days_held=3)
        self.assertIn("SHORT_HOLD", flags)

    def test_short_hold_boundary_7_days(self):
        # days_held = 7 → NOT < 7, so no flag
        flags = _build_flags(il_drag_pct=1.0, gas_costs_usd=10.0,
                              entry_value_usd=10_000.0, alpha_pct=3.0,
                              days_held=7)
        self.assertNotIn("SHORT_HOLD", flags)

    def test_multiple_flags(self):
        flags = _build_flags(il_drag_pct=10.0, gas_costs_usd=500.0,
                              entry_value_usd=10_000.0, alpha_pct=-8.0,
                              days_held=2)
        self.assertIn("HIGH_IL", flags)
        self.assertIn("GAS_HEAVY", flags)
        self.assertIn("BELOW_BENCHMARK", flags)
        self.assertIn("SHORT_HOLD", flags)

    def test_zero_entry_gas_heavy_not_flagged(self):
        # entry=0 → guard: gas heavy requires entry>0
        flags = _build_flags(il_drag_pct=1.0, gas_costs_usd=500.0,
                              entry_value_usd=0.0, alpha_pct=3.0,
                              days_held=30)
        self.assertNotIn("GAS_HEAVY", flags)


# ===========================================================================
# 6. _recommendation
# ===========================================================================
class TestRecommendation(unittest.TestCase):

    def test_exceptional(self):
        r = _recommendation("EXCEPTIONAL", 25.0, 12.5, [])
        self.assertIn("25.0%", r)
        self.assertIn("12.5%", r)
        self.assertIn("Hold", r)

    def test_outperform(self):
        r = _recommendation("OUTPERFORM", 10.0, 3.0, [])
        self.assertIn("3.0%", r)
        self.assertIn("benchmark", r)

    def test_benchmark(self):
        r = _recommendation("BENCHMARK", 2.0, -1.5, [])
        self.assertIn("-1.5%", r)

    def test_underperform(self):
        r = _recommendation("UNDERPERFORM", 1.0, -7.0, [])
        self.assertIn("-7.0%", r)
        self.assertIn("exit", r)

    def test_loss_with_flags(self):
        r = _recommendation("LOSS", -5.0, -20.0, ["HIGH_IL", "GAS_HEAVY"])
        self.assertIn("-5.0%", r)
        self.assertIn("HIGH_IL", r)

    def test_loss_no_flags(self):
        r = _recommendation("LOSS", -3.0, -15.0, [])
        self.assertIn("review strategy", r)


# ===========================================================================
# 7. _analyse_position
# ===========================================================================
class TestAnalysePosition(unittest.TestCase):

    def _pos(self, **kw):
        return make_pos(**kw)

    def test_basic_structure(self):
        result = _analyse_position(make_pos(), benchmark_apy_pct=5.0)
        for key in ("protocol", "position_type", "entry_value_usd",
                    "current_value_usd", "gross_pnl_usd", "net_pnl_usd",
                    "net_pnl_pct", "annualized_return_pct", "fee_yield_pct",
                    "reward_yield_pct", "il_drag_pct", "alpha_pct",
                    "performance_label", "status", "flags", "recommendation"):
            self.assertIn(key, result)

    def test_gross_pnl(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_200,
                       fees_earned_usd=100, rewards_earned_usd=50,
                       il_loss_usd=0, gas_costs_usd=0, days_held=30)
        r = _analyse_position(pos, 5.0)
        self.assertAlmostEqual(r["gross_pnl_usd"], 350.0)

    def test_net_pnl(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_200,
                       fees_earned_usd=100, rewards_earned_usd=50,
                       il_loss_usd=80, gas_costs_usd=30, days_held=30)
        r = _analyse_position(pos, 5.0)
        # gross = 350, net = 350 - 80 - 30 = 240
        self.assertAlmostEqual(r["net_pnl_usd"], 240.0)

    def test_net_pnl_pct(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       fees_earned_usd=500, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=0, days_held=365)
        r = _analyse_position(pos, 5.0)
        self.assertAlmostEqual(r["net_pnl_pct"], 5.0)

    def test_annualized_return(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       fees_earned_usd=500, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=0, days_held=365)
        r = _analyse_position(pos, 5.0)
        self.assertAlmostEqual(r["annualized_return_pct"], 5.0)

    def test_annualized_zero_days(self):
        pos = make_pos(days_held=0)
        r = _analyse_position(pos, 5.0)
        self.assertEqual(r["annualized_return_pct"], 0.0)

    def test_zero_entry(self):
        pos = make_pos(entry_value_usd=0)
        r = _analyse_position(pos, 5.0)
        self.assertEqual(r["net_pnl_pct"], 0.0)
        self.assertEqual(r["fee_yield_pct"], 0.0)
        self.assertEqual(r["il_drag_pct"], 0.0)
        self.assertEqual(r["reward_yield_pct"], 0.0)

    def test_alpha_pct(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       fees_earned_usd=1000, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=0, days_held=365)
        r = _analyse_position(pos, 5.0)
        # annualized = 10%, alpha = 5%
        self.assertAlmostEqual(r["alpha_pct"], 5.0)

    def test_exceptional_label(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       fees_earned_usd=2000, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=0, days_held=365)
        r = _analyse_position(pos, 5.0)
        # annualized = 20%, alpha = 15% → EXCEPTIONAL
        self.assertEqual(r["performance_label"], "EXCEPTIONAL")

    def test_loss_label(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=9_000,
                       fees_earned_usd=0, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=0, days_held=90)
        r = _analyse_position(pos, 5.0)
        self.assertEqual(r["performance_label"], "LOSS")

    def test_profitable_status(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       fees_earned_usd=500, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=0, days_held=90)
        r = _analyse_position(pos, 5.0)
        self.assertEqual(r["status"], "PROFITABLE")

    def test_losing_status(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=9_000,
                       fees_earned_usd=0, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=0, days_held=90)
        r = _analyse_position(pos, 5.0)
        self.assertEqual(r["status"], "LOSING")

    def test_breakeven_status(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       fees_earned_usd=50, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=50, days_held=90)
        r = _analyse_position(pos, 5.0)
        # net_pnl = 0 → BREAKEVEN
        self.assertEqual(r["status"], "BREAKEVEN")

    def test_high_il_flag(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       il_loss_usd=600, days_held=90)
        r = _analyse_position(pos, 5.0)
        self.assertIn("HIGH_IL", r["flags"])

    def test_gas_heavy_flag(self):
        pos = make_pos(entry_value_usd=10_000, gas_costs_usd=250, days_held=90)
        r = _analyse_position(pos, 5.0)
        self.assertIn("GAS_HEAVY", r["flags"])

    def test_short_hold_flag(self):
        pos = make_pos(days_held=3)
        r = _analyse_position(pos, 5.0)
        self.assertIn("SHORT_HOLD", r["flags"])

    def test_below_benchmark_flag(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       fees_earned_usd=10, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=0, days_held=365)
        r = _analyse_position(pos, 5.0)
        self.assertIn("BELOW_BENCHMARK", r["flags"])

    def test_fee_yield_pct(self):
        pos = make_pos(entry_value_usd=10_000, fees_earned_usd=500)
        r = _analyse_position(pos, 5.0)
        self.assertAlmostEqual(r["fee_yield_pct"], 5.0)

    def test_reward_yield_pct(self):
        pos = make_pos(entry_value_usd=10_000, rewards_earned_usd=200)
        r = _analyse_position(pos, 5.0)
        self.assertAlmostEqual(r["reward_yield_pct"], 2.0)

    def test_il_drag_pct(self):
        pos = make_pos(entry_value_usd=10_000, il_loss_usd=300)
        r = _analyse_position(pos, 5.0)
        self.assertAlmostEqual(r["il_drag_pct"], 3.0)

    def test_protocol_name_preserved(self):
        pos = make_pos(protocol="Morpho Steakhouse")
        r = _analyse_position(pos, 5.0)
        self.assertEqual(r["protocol"], "Morpho Steakhouse")

    def test_position_type_preserved(self):
        pos = make_pos(position_type="LP")
        r = _analyse_position(pos, 5.0)
        self.assertEqual(r["position_type"], "LP")


# ===========================================================================
# 8. analyze() — aggregate
# ===========================================================================
class TestAnalyze(unittest.TestCase):

    def test_empty_returns_zeros(self):
        result = analyze([])
        self.assertEqual(result["positions"], [])
        self.assertEqual(result["total_net_pnl_usd"], 0.0)
        self.assertEqual(result["total_fees_earned_usd"], 0.0)
        self.assertEqual(result["total_il_loss_usd"], 0.0)
        self.assertIsNone(result["best_performer"])
        self.assertIsNone(result["worst_performer"])
        self.assertEqual(result["average_alpha_pct"], 0.0)
        self.assertIn("timestamp", result)

    def test_single_position_structure(self):
        result = analyze([make_pos()])
        self.assertEqual(len(result["positions"]), 1)

    def test_total_net_pnl(self):
        p1 = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                      fees_earned_usd=100, rewards_earned_usd=0,
                      il_loss_usd=0, gas_costs_usd=20, days_held=30)
        p2 = make_pos(protocol="Compound", entry_value_usd=5_000,
                      current_value_usd=5_000, fees_earned_usd=50,
                      rewards_earned_usd=0, il_loss_usd=0, gas_costs_usd=10,
                      days_held=30)
        result = analyze([p1, p2])
        expected = (100 - 20) + (50 - 10)
        self.assertAlmostEqual(result["total_net_pnl_usd"], expected)

    def test_best_performer(self):
        p1 = make_pos(protocol="Aave",
                      entry_value_usd=10_000, current_value_usd=10_000,
                      fees_earned_usd=500, rewards_earned_usd=0,
                      il_loss_usd=0, gas_costs_usd=0, days_held=365)
        p2 = make_pos(protocol="Compound",
                      entry_value_usd=10_000, current_value_usd=10_000,
                      fees_earned_usd=200, rewards_earned_usd=0,
                      il_loss_usd=0, gas_costs_usd=0, days_held=365)
        result = analyze([p1, p2])
        self.assertEqual(result["best_performer"], "Aave")

    def test_worst_performer(self):
        p1 = make_pos(protocol="Aave",
                      entry_value_usd=10_000, current_value_usd=10_000,
                      fees_earned_usd=500, rewards_earned_usd=0,
                      il_loss_usd=0, gas_costs_usd=0, days_held=365)
        p2 = make_pos(protocol="BadPool",
                      entry_value_usd=10_000, current_value_usd=9_000,
                      fees_earned_usd=0, rewards_earned_usd=0,
                      il_loss_usd=0, gas_costs_usd=0, days_held=90)
        result = analyze([p1, p2])
        self.assertEqual(result["worst_performer"], "BadPool")

    def test_average_alpha(self):
        p1 = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                      fees_earned_usd=1000, rewards_earned_usd=0,
                      il_loss_usd=0, gas_costs_usd=0, days_held=365)
        p2 = make_pos(protocol="Compound",
                      entry_value_usd=10_000, current_value_usd=10_000,
                      fees_earned_usd=700, rewards_earned_usd=0,
                      il_loss_usd=0, gas_costs_usd=0, days_held=365)
        result = analyze([p1, p2])
        # Aave: annualized=10%, alpha=5%; Compound: annualized=7%, alpha=2%
        self.assertAlmostEqual(result["average_alpha_pct"], 3.5)

    def test_total_fees_earned(self):
        p1 = make_pos(entry_value_usd=10_000, fees_earned_usd=500, days_held=30)
        p2 = make_pos(protocol="B", entry_value_usd=20_000, fees_earned_usd=400,
                      days_held=30)
        result = analyze([p1, p2])
        # fee_yield_pct = fees/entry*100; total_fees = sum(pct*entry/100)
        self.assertAlmostEqual(result["total_fees_earned_usd"], 900.0)

    def test_total_il_loss(self):
        p1 = make_pos(entry_value_usd=10_000, il_loss_usd=200, days_held=30)
        p2 = make_pos(protocol="B", entry_value_usd=20_000, il_loss_usd=300,
                      days_held=30)
        result = analyze([p1, p2])
        self.assertAlmostEqual(result["total_il_loss_usd"], 500.0)

    def test_timestamp_is_recent(self):
        result = analyze([make_pos()])
        self.assertAlmostEqual(result["timestamp"], time.time(), delta=5.0)

    def test_config_benchmark_applied(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       fees_earned_usd=1000, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=0, days_held=365)
        r_default = analyze([pos])
        r_custom  = analyze([pos], config={"benchmark_apy_pct": 2.0})
        # Higher benchmark → lower alpha
        self.assertGreater(
            r_custom["positions"][0]["alpha_pct"],
            r_default["positions"][0]["alpha_pct"],
        )

    def test_multiple_positions_count(self):
        positions = [make_pos(protocol=f"P{i}") for i in range(5)]
        result = analyze(positions)
        self.assertEqual(len(result["positions"]), 5)

    def test_zero_entry_no_crash(self):
        pos = make_pos(entry_value_usd=0, current_value_usd=0,
                       fees_earned_usd=0, gas_costs_usd=0, days_held=0)
        result = analyze([pos])
        self.assertEqual(len(result["positions"]), 1)
        self.assertEqual(result["positions"][0]["net_pnl_pct"], 0.0)

    def test_lp_position_type(self):
        pos = make_pos(position_type="LP")
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["position_type"], "LP")

    def test_staking_position_type(self):
        pos = make_pos(position_type="STAKING")
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["position_type"], "STAKING")

    def test_vault_position_type(self):
        pos = make_pos(position_type="VAULT")
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["position_type"], "VAULT")

    def test_underperform_label_present(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       fees_earned_usd=10, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=0, days_held=365)
        result = analyze([pos], config={"benchmark_apy_pct": 15.0})
        self.assertEqual(result["positions"][0]["performance_label"], "UNDERPERFORM")

    def test_benchmark_label_present(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       fees_earned_usd=450, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=0, days_held=365)
        result = analyze([pos], config={"benchmark_apy_pct": 5.0})
        # annualized = 4.5%, alpha = -0.5% → BENCHMARK
        self.assertEqual(result["positions"][0]["performance_label"], "BENCHMARK")

    def test_outperform_label_present(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       fees_earned_usd=800, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=0, days_held=365)
        result = analyze([pos], config={"benchmark_apy_pct": 5.0})
        # annualized = 8%, alpha = 3% → OUTPERFORM
        self.assertEqual(result["positions"][0]["performance_label"], "OUTPERFORM")

    def test_recommendation_not_empty(self):
        result = analyze([make_pos()])
        for pos in result["positions"]:
            self.assertIsInstance(pos["recommendation"], str)
            self.assertGreater(len(pos["recommendation"]), 0)

    def test_flags_is_list(self):
        result = analyze([make_pos()])
        self.assertIsInstance(result["positions"][0]["flags"], list)

    def test_ten_positions(self):
        positions = [make_pos(protocol=f"Protocol-{i}", entry_value_usd=1000.0 * (i + 1))
                     for i in range(10)]
        result = analyze(positions)
        self.assertEqual(len(result["positions"]), 10)

    def test_rewards_contribute_to_gross_pnl(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       fees_earned_usd=0, rewards_earned_usd=500,
                       il_loss_usd=0, gas_costs_usd=0, days_held=365)
        result = analyze([pos])
        self.assertAlmostEqual(result["positions"][0]["gross_pnl_usd"], 500.0)

    def test_il_reduces_net_pnl(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       fees_earned_usd=500, rewards_earned_usd=0,
                       il_loss_usd=200, gas_costs_usd=0, days_held=365)
        result = analyze([pos])
        self.assertAlmostEqual(result["positions"][0]["net_pnl_usd"], 300.0)

    def test_gas_reduces_net_pnl(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       fees_earned_usd=500, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=100, days_held=365)
        result = analyze([pos])
        self.assertAlmostEqual(result["positions"][0]["net_pnl_usd"], 400.0)


# ===========================================================================
# 9. log_result()
# ===========================================================================
class TestLogResult(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def test_creates_file(self):
        result = analyze([make_pos()])
        log_result(result, data_dir=self.tmp_dir)
        self.assertTrue(os.path.exists(os.path.join(self.tmp_dir, "position_pnl_log.json")))

    def test_appends(self):
        result = analyze([make_pos()])
        log_result(result, data_dir=self.tmp_dir)
        log_result(result, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "position_pnl_log.json")) as fh:
            log = json.load(fh)
        self.assertEqual(len(log), 2)

    def test_ring_buffer_cap(self):
        result = analyze([make_pos()])
        for _ in range(110):
            log_result(result, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "position_pnl_log.json")) as fh:
            log = json.load(fh)
        self.assertLessEqual(len(log), 100)

    def test_valid_json_written(self):
        result = analyze([make_pos()])
        log_result(result, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "position_pnl_log.json")) as fh:
            log = json.load(fh)
        self.assertIsInstance(log, list)

    def test_corrupt_log_recovers(self):
        log_path = os.path.join(self.tmp_dir, "position_pnl_log.json")
        with open(log_path, "w") as fh:
            fh.write("not json!!!")
        result = analyze([make_pos()])
        log_result(result, data_dir=self.tmp_dir)
        with open(log_path) as fh:
            log = json.load(fh)
        self.assertEqual(len(log), 1)

    def test_non_list_log_recovers(self):
        log_path = os.path.join(self.tmp_dir, "position_pnl_log.json")
        with open(log_path, "w") as fh:
            json.dump({"bad": "format"}, fh)
        result = analyze([make_pos()])
        log_result(result, data_dir=self.tmp_dir)
        with open(log_path) as fh:
            log = json.load(fh)
        self.assertIsInstance(log, list)

    def test_empty_result_logged(self):
        result = analyze([])
        log_result(result, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "position_pnl_log.json")) as fh:
            log = json.load(fh)
        self.assertEqual(len(log), 1)


# ===========================================================================
# 10. Edge cases & integration
# ===========================================================================
class TestEdgeCases(unittest.TestCase):

    def test_all_zeros_position(self):
        pos = make_pos(entry_value_usd=0, current_value_usd=0,
                       fees_earned_usd=0, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=0, days_held=0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertEqual(p["net_pnl_usd"], 0.0)
        self.assertEqual(p["net_pnl_pct"], 0.0)
        self.assertEqual(p["annualized_return_pct"], 0.0)

    def test_very_large_values(self):
        pos = make_pos(entry_value_usd=1_000_000, current_value_usd=1_050_000,
                       fees_earned_usd=50_000, rewards_earned_usd=10_000,
                       il_loss_usd=5_000, gas_costs_usd=500, days_held=365)
        result = analyze([pos])
        self.assertIsInstance(result["positions"][0]["net_pnl_usd"], float)

    def test_single_day_hold(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       fees_earned_usd=10, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=5, days_held=1)
        result = analyze([pos])
        p = result["positions"][0]
        # annualized = 5/10000*100/1*365
        expected_ann = (5 / 10_000 * 100 / 1) * 365
        self.assertAlmostEqual(p["annualized_return_pct"], expected_ann)

    def test_negative_current_value(self):
        # Should not crash; net_pnl will be very negative
        pos = make_pos(current_value_usd=0.0, entry_value_usd=10_000.0,
                       fees_earned_usd=0, days_held=30)
        result = analyze([pos])
        self.assertLess(result["positions"][0]["net_pnl_usd"], 0)

    def test_custom_benchmark_zero(self):
        pos = make_pos(entry_value_usd=10_000, current_value_usd=10_000,
                       fees_earned_usd=100, rewards_earned_usd=0,
                       il_loss_usd=0, gas_costs_usd=0, days_held=365)
        result = analyze([pos], config={"benchmark_apy_pct": 0.0})
        # alpha = annualized - 0 = annualized
        p = result["positions"][0]
        self.assertAlmostEqual(p["alpha_pct"], p["annualized_return_pct"])

    def test_missing_config_uses_default(self):
        result = analyze([make_pos()])
        # Should not raise
        self.assertIsNotNone(result)

    def test_positions_list_returned(self):
        positions = [make_pos(protocol=f"P{i}") for i in range(3)]
        result = analyze(positions)
        self.assertEqual(len(result["positions"]), 3)

    def test_best_worst_same_when_single(self):
        result = analyze([make_pos(protocol="OnlyOne")])
        self.assertEqual(result["best_performer"], "OnlyOne")
        self.assertEqual(result["worst_performer"], "OnlyOne")

    def test_all_positions_exceptional(self):
        positions = [
            make_pos(protocol=f"P{i}", entry_value_usd=10_000,
                     current_value_usd=10_000, fees_earned_usd=3000,
                     rewards_earned_usd=0, il_loss_usd=0, gas_costs_usd=0,
                     days_held=365)
            for i in range(4)
        ]
        result = analyze(positions)
        for p in result["positions"]:
            self.assertEqual(p["performance_label"], "EXCEPTIONAL")

    def test_lp_with_high_il(self):
        pos = make_pos(position_type="LP",
                       entry_value_usd=50_000, current_value_usd=48_000,
                       fees_earned_usd=1500, rewards_earned_usd=500,
                       il_loss_usd=3000, gas_costs_usd=150, days_held=60)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertIn("HIGH_IL", p["flags"])


if __name__ == "__main__":
    unittest.main()
