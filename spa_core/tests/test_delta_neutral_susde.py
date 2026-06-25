#!/usr/bin/env python3
"""Tests for spa_core.strategies.delta_neutral_susde (SPA-V467 / MP-157).

DeltaNeutralSUSDeStrategy — S8 delta-neutral sUSDe funding harvest paper sim.

Coverage:
  - Constructor & validation (T01–T05)
  - Gate conditions / is_active (T06–T16)
  - Gate details report (T17–T19)
  - gross_yield (T20–T23)
  - net_yield (T24–T29)
  - daily_yield_usd (T30–T32)
  - simulate_day: bull market → positive yield (T33–T37)
  - simulate_day: bear market → 0 loss, 0 gain (T38–T42)
  - simulate_day: neutral/inactive regimes (T43–T46)
  - simulate_historical_scenario: bull_2024 (T47–T50)
  - simulate_historical_scenario: bear_2022 → 0 return (T51–T54)
  - simulate_historical_scenario: neutral_sideways → inactive (T55–T57)
  - simulate_historical_scenario: base_case (T58–T59)
  - simulate_historical_scenario: invalid inputs (T60–T61)
  - to_vportfolio_format (T62–T66)
  - risk_metrics (T67–T71)
  - position_sizing (T72–T76)
  - check_exit_conditions (T77–T82)
  - Integration with paper_trading strategy_registry S8 entry (T83–T88)
  - Integration with strategies strategy_registry VALID_TYPES (T89–T90)
  - State tracking / reset_state (T91–T93)
  - repr (T94)
  - Determinism with rng_seed (T95–T96)
  - Import hygiene (T97–T100)

Run:  python3 -m unittest spa_core.tests.test_delta_neutral_susde -v
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.delta_neutral_susde import (
    EXECUTION_FRICTION,
    FUNDING_KILL_HOURS,
    FUNDING_KILL_THRESHOLD,
    FUNDING_RATE_GATE,
    HOURS_PER_FUNDING_OBSERVATION,
    INTERNAL_ALLOC_PERP,
    INTERNAL_ALLOC_SUSDE,
    MAX_CAPITAL_PCT,
    PERP_BORROW_RATE_DEFAULT,
    STRATEGY_ID,
    STRATEGY_VERSION,
    SUSDE_APY_GATE,
    DeltaNeutralSUSDeStrategy,
    _SCENARIOS,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make(capital: float = 100_000, max_pct: float = 0.20, seed: int = 42):
    return DeltaNeutralSUSDeStrategy(capital=capital, max_capital_pct=max_pct, rng_seed=seed)


# ─── T01–T05: Constructor & validation ────────────────────────────────────────

class TestConstructor(unittest.TestCase):
    """T01–T05: Constructor field assignment and validation."""

    def test_T01_capital_assigned(self):
        s = _make(capital=50_000)
        self.assertEqual(s.capital, 50_000.0)

    def test_T02_max_capital_usd_derived(self):
        s = _make(capital=100_000, max_pct=0.20)
        self.assertAlmostEqual(s.max_capital_usd, 20_000.0, places=4)

    def test_T03_max_capital_usd_custom_pct(self):
        s = _make(capital=80_000, max_pct=0.15)
        self.assertAlmostEqual(s.max_capital_usd, 12_000.0, places=4)

    def test_T04_invalid_capital_raises(self):
        with self.assertRaises((ValueError, Exception)):
            DeltaNeutralSUSDeStrategy(capital=0)
        with self.assertRaises((ValueError, Exception)):
            DeltaNeutralSUSDeStrategy(capital=-1000)

    def test_T05_invalid_max_pct_raises(self):
        with self.assertRaises((ValueError, Exception)):
            DeltaNeutralSUSDeStrategy(capital=100_000, max_capital_pct=0.0)
        with self.assertRaises((ValueError, Exception)):
            DeltaNeutralSUSDeStrategy(capital=100_000, max_capital_pct=1.5)


# ─── T06–T16: Gate conditions / is_active ─────────────────────────────────────

class TestIsActive(unittest.TestCase):
    """T06–T16: Gate conditions for strategy activation."""

    def setUp(self):
        self.s = _make()

    def test_T06_bull_all_gates_passed(self):
        self.assertTrue(self.s.is_active(0.18, 0.12, "bull"))

    def test_T07_bull_min_gate_boundary(self):
        # Exactly at gate threshold
        self.assertTrue(self.s.is_active(SUSDE_APY_GATE, FUNDING_RATE_GATE, "bull"))

    def test_T08_bear_always_inactive(self):
        # Even with high APY, bear regime = inactive
        self.assertFalse(self.s.is_active(0.25, 0.20, "bear"))

    def test_T09_bear_regardless_of_apy(self):
        self.assertFalse(self.s.is_active(0.30, 0.30, "bear"))

    def test_T10_neutral_regime_inactive(self):
        self.assertFalse(self.s.is_active(0.18, 0.12, "neutral"))

    def test_T11_susde_apy_below_gate(self):
        # 8% < 12% gate
        self.assertFalse(self.s.is_active(0.08, 0.12, "bull"))

    def test_T12_susde_apy_just_below_gate(self):
        self.assertFalse(self.s.is_active(0.1199, 0.05, "bull"))

    def test_T13_negative_funding_bull_regime_inactive(self):
        # funding < 0 → inactive even in "bull" regime
        self.assertFalse(self.s.is_active(0.20, -0.01, "bull"))

    def test_T14_negative_funding_bear(self):
        self.assertFalse(self.s.is_active(0.05, -0.06, "bear"))

    def test_T15_zero_funding_at_gate(self):
        # funding = 0.0 exactly → at gate → active if susde ok
        self.assertTrue(self.s.is_active(0.15, 0.0, "bull"))

    def test_T16_susde_high_but_funding_negative(self):
        # sUSDe 25%, but funding -5% → inactive
        self.assertFalse(self.s.is_active(0.25, -0.05, "bull"))


# ─── T17–T19: Gate details report ─────────────────────────────────────────────

class TestGateDetails(unittest.TestCase):
    """T17–T19: gate_details returns structured report."""

    def setUp(self):
        self.s = _make()

    def test_T17_all_gates_passed_structure(self):
        details = self.s.gate_details(0.18, 0.12, "bull")
        self.assertTrue(details["active"])
        self.assertEqual(details["failed_gates"], [])
        self.assertIn("susde_apy_gate", details["passed_gates"])
        self.assertIn("funding_rate_gate", details["passed_gates"])
        self.assertIn("market_regime_gate", details["passed_gates"])

    def test_T18_bear_regime_gate_fails(self):
        details = self.s.gate_details(0.18, 0.12, "bear")
        self.assertFalse(details["active"])
        self.assertIn("market_regime_gate", details["failed_gates"])
        self.assertGreater(len(details["blockers"]), 0)

    def test_T19_two_gates_failed_reported(self):
        details = self.s.gate_details(0.08, -0.05, "neutral")
        self.assertFalse(details["active"])
        # At least susde_apy + funding + regime failed
        self.assertGreaterEqual(len(details["failed_gates"]), 2)


# ─── T20–T23: gross_yield ─────────────────────────────────────────────────────

class TestGrossYield(unittest.TestCase):
    """T20–T23: gross_yield = susde_apy + funding_rate."""

    def setUp(self):
        self.s = _make()

    def test_T20_bull_2024_gross(self):
        # 18% + 12% = 30%
        self.assertAlmostEqual(self.s.gross_yield(0.18, 0.12), 0.30, places=8)

    def test_T21_base_case_gross(self):
        # 15% + 3% = 18%
        self.assertAlmostEqual(self.s.gross_yield(0.15, 0.03), 0.18, places=8)

    def test_T22_high_bull_gross(self):
        # 22% + 6% = 28%
        self.assertAlmostEqual(self.s.gross_yield(0.22, 0.06), 0.28, places=8)

    def test_T23_zero_funding_gross(self):
        # 15% + 0% = 15%
        self.assertAlmostEqual(self.s.gross_yield(0.15, 0.0), 0.15, places=8)


# ─── T24–T29: net_yield ───────────────────────────────────────────────────────

class TestNetYield(unittest.TestCase):
    """T24–T29: net_yield = gross - perp_borrow_rate - EXECUTION_FRICTION."""

    def setUp(self):
        self.s = _make()

    def test_T24_bull_2024_net(self):
        # 18% + 12% - 2% - 0.5% = 27.5%
        expected = 0.18 + 0.12 - PERP_BORROW_RATE_DEFAULT - EXECUTION_FRICTION
        self.assertAlmostEqual(self.s.net_yield(0.18, 0.12), expected, places=8)

    def test_T25_net_less_than_gross(self):
        gross = self.s.gross_yield(0.18, 0.06)
        net = self.s.net_yield(0.18, 0.06)
        self.assertLess(net, gross)

    def test_T26_custom_borrow_rate(self):
        # Higher borrow rate → lower net
        net_default = self.s.net_yield(0.18, 0.06)
        net_high_borrow = self.s.net_yield(0.18, 0.06, perp_borrow_rate=0.05)
        self.assertLess(net_high_borrow, net_default)

    def test_T27_net_base_case(self):
        # 15% + 3% - 2% - 0.5% = 15.5%
        expected = 0.15 + 0.03 - 0.02 - 0.005
        self.assertAlmostEqual(self.s.net_yield(0.15, 0.03), expected, places=8)

    def test_T28_execution_friction_constant(self):
        self.assertAlmostEqual(EXECUTION_FRICTION, 0.005, places=8)

    def test_T29_default_borrow_rate_constant(self):
        self.assertAlmostEqual(PERP_BORROW_RATE_DEFAULT, 0.02, places=8)


# ─── T30–T32: daily_yield_usd ─────────────────────────────────────────────────

class TestDailyYieldUsd(unittest.TestCase):
    """T30–T32: daily_yield_usd = capital * net_yield / 365."""

    def setUp(self):
        self.s = _make(capital=100_000)

    def test_T30_daily_yield_positive_bull(self):
        usd = self.s.daily_yield_usd(0.18, 0.12)
        net = self.s.net_yield(0.18, 0.12)
        expected = self.s.max_capital_usd * net / 365.0
        self.assertAlmostEqual(usd, expected, places=6)

    def test_T31_custom_capital_deployed(self):
        usd = self.s.daily_yield_usd(0.18, 0.12, capital_deployed=30_000)
        net = self.s.net_yield(0.18, 0.12)
        expected = 30_000 * net / 365.0
        self.assertAlmostEqual(usd, expected, places=6)

    def test_T32_annual_yield_reasonable_range(self):
        # Bull: ~$4K–$7K per year on $20K capital deployed
        daily = self.s.daily_yield_usd(0.18, 0.12)
        annual = daily * 365
        self.assertGreater(annual, 3_000)
        self.assertLess(annual, 10_000)


# ─── T33–T37: simulate_day: bull market ───────────────────────────────────────

class TestSimulateDayBull(unittest.TestCase):
    """T33–T37: simulate_day in bull market → active, positive yield."""

    def setUp(self):
        self.s = _make()

    def test_T33_bull_returns_active_true(self):
        result = self.s.simulate_day(0.18, 0.12, "bull")
        self.assertTrue(result["active"])

    def test_T34_bull_daily_return_positive(self):
        result = self.s.simulate_day(0.22, 0.06, "bull")
        self.assertGreater(result["daily_return_pct"], 0.0)

    def test_T35_bull_yield_usd_positive(self):
        result = self.s.simulate_day(0.18, 0.12, "bull")
        self.assertGreater(result["yield_usd"], 0.0)

    def test_T36_bull_net_yield_in_target_range(self):
        # Bull: net_yield annualized should be ~13–32%
        result = self.s.simulate_day(0.18, 0.06, "bull")
        annual_net = result["net_yield_annual"]
        self.assertGreater(annual_net, 0.10)
        self.assertLess(annual_net, 0.40)

    def test_T37_bull_result_contains_expected_keys(self):
        result = self.s.simulate_day(0.18, 0.12, "bull")
        expected_keys = {
            "active", "daily_return_pct", "yield_usd",
            "gross_yield_annual", "net_yield_annual",
            "capital_deployed", "market_regime", "gate_passed",
            "reason", "susde_apy", "funding_rate_annual",
        }
        for key in expected_keys:
            self.assertIn(key, result, msg=f"Missing key: {key}")


# ─── T38–T42: simulate_day: bear market → 0 loss ─────────────────────────────

class TestSimulateDayBear(unittest.TestCase):
    """T38–T42: Bear market → strategy inactive → 0% loss, 0% gain."""

    def setUp(self):
        self.s = _make()

    def test_T38_bear_returns_active_false(self):
        result = self.s.simulate_day(0.05, -0.06, "bear")
        self.assertFalse(result["active"])

    def test_T39_bear_yield_usd_exactly_zero(self):
        result = self.s.simulate_day(0.05, -0.06, "bear")
        self.assertEqual(result["yield_usd"], 0.0)

    def test_T40_bear_daily_return_exactly_zero(self):
        result = self.s.simulate_day(0.05, -0.06, "bear")
        self.assertEqual(result["daily_return_pct"], 0.0)

    def test_T41_bear_reason_correct(self):
        result = self.s.simulate_day(0.22, 0.15, "bear")
        self.assertIn("bear", result["reason"])

    def test_T42_bear_high_apy_still_inactive(self):
        # Even 30% APY — bear regime deactivates
        result = self.s.simulate_day(0.30, 0.20, "bear")
        self.assertFalse(result["active"])
        self.assertEqual(result["yield_usd"], 0.0)


# ─── T43–T46: simulate_day: neutral / low APY ─────────────────────────────────

class TestSimulateDayNeutral(unittest.TestCase):
    """T43–T46: Neutral / below-gate regimes → inactive → 0% P&L."""

    def setUp(self):
        self.s = _make()

    def test_T43_neutral_regime_inactive(self):
        result = self.s.simulate_day(0.18, 0.12, "neutral")
        self.assertFalse(result["active"])
        self.assertEqual(result["yield_usd"], 0.0)

    def test_T44_susde_below_gate_bull_inactive(self):
        result = self.s.simulate_day(0.08, 0.06, "bull")
        self.assertFalse(result["active"])
        self.assertIn("susde_apy_below_gate", result["reason"])

    def test_T45_negative_funding_bull_inactive(self):
        result = self.s.simulate_day(0.20, -0.03, "bull")
        self.assertFalse(result["active"])
        self.assertIn("funding_negative", result["reason"])

    def test_T46_inactive_no_negative_return(self):
        # Critical property: inactive always means >= 0 return
        for regime in ("bear", "neutral"):
            r = self.s.simulate_day(0.04, -0.10, regime)
            self.assertGreaterEqual(r["daily_return_pct"], 0.0)
            self.assertGreaterEqual(r["yield_usd"], 0.0)


# ─── T47–T50: simulate_historical_scenario: bull_2024 ─────────────────────────

class TestScenarioBull2024(unittest.TestCase):
    """T47–T50: bull_2024 scenario — active, positive yield."""

    def setUp(self):
        self.s = _make(seed=42)

    def test_T47_bull_2024_many_active_days(self):
        result = self.s.simulate_historical_scenario(365, "bull_2024")
        # In bull_2024 most days should be active (susde ~18% > 12% gate)
        self.assertGreater(result["active_days"], 250)  # > 68% active

    def test_T48_bull_2024_positive_annualized_return(self):
        result = self.s.simulate_historical_scenario(365, "bull_2024")
        self.assertGreater(result["annualized_return_pct"], 0.10)

    def test_T49_bull_2024_sharpe_positive(self):
        result = self.s.simulate_historical_scenario(365, "bull_2024")
        self.assertGreater(result["sharpe_estimate"], 0.0)

    def test_T50_bull_2024_result_keys_complete(self):
        result = self.s.simulate_historical_scenario(30, "bull_2024")
        expected_keys = {
            "scenario", "days", "active_days", "inactive_days",
            "total_yield_usd", "annualized_return_pct",
            "avg_susde_apy", "avg_funding_rate",
            "max_drawdown_pct", "sharpe_estimate",
            "daily_returns", "risk_metrics",
        }
        for k in expected_keys:
            self.assertIn(k, result, msg=f"Missing key: {k}")


# ─── T51–T54: simulate_historical_scenario: bear_2022 ─────────────────────────

class TestScenarioBear2022(unittest.TestCase):
    """T51–T54: bear_2022 — strategy inactive → 0 return, 0 loss."""

    def setUp(self):
        self.s = _make(seed=42)

    def test_T51_bear_zero_active_days(self):
        result = self.s.simulate_historical_scenario(90, "bear_2022")
        self.assertEqual(result["active_days"], 0)

    def test_T52_bear_zero_total_yield(self):
        result = self.s.simulate_historical_scenario(90, "bear_2022")
        self.assertEqual(result["total_yield_usd"], 0.0)

    def test_T53_bear_zero_annualized_return(self):
        result = self.s.simulate_historical_scenario(90, "bear_2022")
        self.assertEqual(result["annualized_return_pct"], 0.0)

    def test_T54_bear_zero_max_drawdown(self):
        # Delta-neutral → no loss in bear when inactive
        result = self.s.simulate_historical_scenario(90, "bear_2022")
        self.assertAlmostEqual(result["max_drawdown_pct"], 0.0, places=8)


# ─── T55–T57: simulate_historical_scenario: neutral_sideways ──────────────────

class TestScenarioNeutral(unittest.TestCase):
    """T55–T57: neutral_sideways — sUSDe below gate → inactive."""

    def setUp(self):
        self.s = _make(seed=42)

    def test_T55_neutral_all_inactive(self):
        result = self.s.simulate_historical_scenario(60, "neutral_sideways")
        # sUSDe ~8% → below 12% gate → all inactive
        self.assertEqual(result["active_days"], 0)

    def test_T56_neutral_zero_yield(self):
        result = self.s.simulate_historical_scenario(60, "neutral_sideways")
        self.assertEqual(result["total_yield_usd"], 0.0)

    def test_T57_neutral_gate_triggers_counted(self):
        result = self.s.simulate_historical_scenario(30, "neutral_sideways")
        # Should have recorded susde_apy_below_gate or neutral_inactive triggers
        gate_counts = result["gate_trigger_counts"]
        total_triggers = sum(gate_counts.values())
        self.assertEqual(total_triggers, 30)  # all 30 days triggered


# ─── T58–T59: simulate_historical_scenario: base_case ────────────────────────

class TestScenarioBaseCase(unittest.TestCase):
    """T58–T59: base_case — moderate bull, active, positive yield."""

    def setUp(self):
        self.s = _make(seed=42)

    def test_T58_base_case_has_active_days(self):
        result = self.s.simulate_historical_scenario(180, "base_case")
        self.assertGreater(result["active_days"], 0)

    def test_T59_base_case_positive_yield_when_active(self):
        result = self.s.simulate_historical_scenario(180, "base_case")
        if result["active_days"] > 0:
            # Net yield on active days should be in range 10–20%
            net_active = result["net_yield_on_active_days"]
            self.assertGreater(net_active, 0.05)


# ─── T60–T61: simulate_historical_scenario: invalid inputs ────────────────────

class TestScenarioInvalidInputs(unittest.TestCase):
    """T60–T61: Invalid scenario/days raises ValueError."""

    def setUp(self):
        self.s = _make()

    def test_T60_unknown_scenario_raises(self):
        with self.assertRaises(ValueError):
            self.s.simulate_historical_scenario(30, "unknown_scenario_xyz")

    def test_T61_zero_days_raises(self):
        with self.assertRaises(ValueError):
            self.s.simulate_historical_scenario(0, "bull_2024")


# ─── T62–T66: to_vportfolio_format ───────────────────────────────────────────

class TestToVPortfolioFormat(unittest.TestCase):
    """T62–T66: VPortfolio-compatible output structure."""

    def setUp(self):
        self.s = _make(capital=100_000)

    def test_T62_strategy_id_correct(self):
        vp = self.s.to_vportfolio_format()
        self.assertEqual(vp["strategy_id"], STRATEGY_ID)

    def test_T63_allocations_correct(self):
        vp = self.s.to_vportfolio_format()
        self.assertEqual(vp["allocations"]["susde_spot"], INTERNAL_ALLOC_SUSDE)
        self.assertEqual(vp["allocations"]["perp_short_hedge"], INTERNAL_ALLOC_PERP)

    def test_T64_active_bull_true(self):
        vp = self.s.to_vportfolio_format(susde_apy=0.18, funding_rate_annual=0.12, market_regime="bull")
        self.assertTrue(vp["active"])

    def test_T65_inactive_bear_false(self):
        vp = self.s.to_vportfolio_format(susde_apy=0.05, funding_rate_annual=-0.06, market_regime="bear")
        self.assertFalse(vp["active"])

    def test_T66_gate_condition_in_output(self):
        vp = self.s.to_vportfolio_format()
        self.assertIn("gate_condition", vp)
        gc = vp["gate_condition"]
        self.assertEqual(gc["susde_apy_min"], SUSDE_APY_GATE)
        self.assertEqual(gc["funding_rate_min"], FUNDING_RATE_GATE)


# ─── T67–T71: risk_metrics ────────────────────────────────────────────────────

class TestRiskMetrics(unittest.TestCase):
    """T67–T71: risk_metrics structure and values."""

    def setUp(self):
        self.s = _make()

    def test_T67_max_drawdown_is_zero(self):
        rm = self.s.risk_metrics()
        self.assertEqual(rm["max_drawdown_historical_pct"], 0.0)

    def test_T68_expected_drawdown_bear_zero(self):
        rm = self.s.risk_metrics()
        self.assertEqual(rm["expected_drawdown_bear_pct"], 0.0)

    def test_T69_bull_2024_sharpe_above_3(self):
        rm = self.s.risk_metrics(scenario="bull_2024")
        self.assertGreater(rm["sharpe_estimate"], 3.0)

    def test_T70_key_risks_populated(self):
        rm = self.s.risk_metrics()
        self.assertIsInstance(rm["key_risks"], list)
        self.assertGreater(len(rm["key_risks"]), 3)
        for risk in rm["key_risks"]:
            self.assertIn("risk", risk)
            self.assertIn("mitigation", risk)

    def test_T71_volatility_profile_low(self):
        rm = self.s.risk_metrics()
        self.assertEqual(rm["volatility_profile"], "low")


# ─── T72–T76: position_sizing ─────────────────────────────────────────────────

class TestPositionSizing(unittest.TestCase):
    """T72–T76: Position sizing matrix per spread thresholds."""

    def setUp(self):
        self.s = _make(capital=100_000)

    def test_T72_full_position_above_15pct(self):
        result = self.s.position_sizing(spread_net=0.20)
        self.assertEqual(result["action"], "full_position")
        self.assertAlmostEqual(result["capital_pct"], MAX_CAPITAL_PCT, places=6)

    def test_T73_reduced_position_10_to_15pct(self):
        result = self.s.position_sizing(spread_net=0.12)
        self.assertEqual(result["action"], "reduced_position")
        self.assertLess(result["capital_pct"], MAX_CAPITAL_PCT)
        self.assertGreater(result["capital_pct"], 0.0)

    def test_T74_hold_no_add_6_to_10pct(self):
        result = self.s.position_sizing(spread_net=0.08)
        self.assertEqual(result["action"], "hold_no_add")

    def test_T75_wind_down_below_6pct(self):
        result = self.s.position_sizing(spread_net=0.04)
        self.assertEqual(result["action"], "wind_down_24h")
        self.assertEqual(result["capital_pct"], 0.0)

    def test_T76_immediate_exit_negative_spread(self):
        result = self.s.position_sizing(spread_net=-0.02)
        self.assertEqual(result["action"], "immediate_exit")
        self.assertEqual(result["capital_usd"], 0.0)


# ─── T77–T82: check_exit_conditions ──────────────────────────────────────────

class TestCheckExitConditions(unittest.TestCase):
    """T77–T82: Exit conditions — OR logic, any trigger → should_exit=True."""

    def setUp(self):
        self.s = _make()

    def test_T77_no_conditions_no_exit(self):
        result = self.s.check_exit_conditions(
            susde_apy=0.15,
            funding_negative_days=0,
            susde_depeg_pct=0.001,
            portfolio_drawdown_pct=0.01,
            spread_net=0.15,
        )
        self.assertFalse(result["should_exit"])
        self.assertEqual(result["triggered_conditions"], [])

    def test_T78_susde_apy_below_8pct_triggers_exit(self):
        result = self.s.check_exit_conditions(susde_apy=0.06)
        self.assertTrue(result["should_exit"])
        self.assertIn("susde_apy_below_8pct", result["triggered_conditions"])

    def test_T79_funding_negative_3days_triggers_exit(self):
        result = self.s.check_exit_conditions(susde_apy=0.15, funding_negative_days=3)
        self.assertTrue(result["should_exit"])
        self.assertIn("funding_negative_3days", result["triggered_conditions"])

    def test_T80_susde_depeg_triggers_exit(self):
        result = self.s.check_exit_conditions(susde_apy=0.15, susde_depeg_pct=0.006)
        self.assertTrue(result["should_exit"])
        self.assertIn("susde_depeg_above_50bps", result["triggered_conditions"])

    def test_T81_portfolio_drawdown_triggers_exit(self):
        result = self.s.check_exit_conditions(susde_apy=0.15, portfolio_drawdown_pct=0.05)
        self.assertTrue(result["should_exit"])
        self.assertIn("portfolio_drawdown_5pct", result["triggered_conditions"])

    def test_T82_spread_below_6pct_triggers_exit(self):
        result = self.s.check_exit_conditions(susde_apy=0.15, spread_net=0.04)
        self.assertTrue(result["should_exit"])
        self.assertIn("spread_below_6pct", result["triggered_conditions"])


# ─── T83–T88: Integration with paper_trading strategy_registry ───────────────

class TestPaperTradingRegistryS8(unittest.TestCase):
    """T83–T88: S8 is correctly registered in paper_trading STRATEGY_REGISTRY."""

    @classmethod
    def setUpClass(cls):
        from spa_core.paper_trading.strategy_registry import (
            STRATEGY_REGISTRY,
            S8_DELTA_NEUTRAL_SUSDE,
            get_strategy,
            active_strategies,
        )
        cls.registry = STRATEGY_REGISTRY
        cls.s8 = S8_DELTA_NEUTRAL_SUSDE
        cls.get_strategy = staticmethod(get_strategy)
        cls.active_strategies = staticmethod(active_strategies)

    def test_T83_s8_in_registry(self):
        self.assertIn("S8", self.registry)

    def test_T84_s8_allocations_correct(self):
        self.assertEqual(self.s8.allocations["susde_spot"], 0.50)
        self.assertEqual(self.s8.allocations["perp_short_hedge"], 0.50)

    def test_T85_s8_allocations_sum_to_one(self):
        total = sum(self.s8.allocations.values())
        self.assertAlmostEqual(total, 1.0, places=8)

    def test_T86_s8_strategy_class_set(self):
        self.assertEqual(self.s8.strategy_class, "DeltaNeutralSUSDeStrategy")

    def test_T87_s8_gate_condition_callable(self):
        self.assertTrue(callable(self.s8.gate_condition))
        # bull: susde=18% → True
        self.assertTrue(self.s8.gate_condition({"susde": 0.18}))
        # bear: susde=8% → False
        self.assertFalse(self.s8.gate_condition({"susde": 0.08}))

    def test_T88_s8_target_apy_range(self):
        self.assertEqual(self.s8.target_apy_min, 0.0)
        self.assertEqual(self.s8.target_apy_max, 24.0)


# ─── T89–T90: Integration with strategies.strategy_registry ──────────────────

class TestStrategiesRegistryS8(unittest.TestCase):
    """T89–T90: DeltaNeutralSUSDeStrategy self-registers in strategies.strategy_registry."""

    def test_T89_delta_neutral_type_valid(self):
        from spa_core.strategies.strategy_registry import VALID_TYPES
        self.assertIn("delta_neutral", VALID_TYPES)

    def test_T90_s8_in_strategies_registry(self):
        # Import triggers _register_s8() side-effect
        import importlib
        importlib.import_module("spa_core.strategies.delta_neutral_susde")
        from spa_core.strategies.strategy_registry import REGISTRY
        s8 = REGISTRY.get(STRATEGY_ID)
        self.assertIsNotNone(s8, f"{STRATEGY_ID} not found in REGISTRY")
        self.assertEqual(s8.handler_class, "DeltaNeutralSUSDeStrategy")
        self.assertEqual(s8.risk_tier, "T2")


# ─── T91–T93: State tracking / reset_state ───────────────────────────────────

class TestStateTracking(unittest.TestCase):
    """T91–T93: Internal state accumulates correctly and resets cleanly."""

    def test_T91_active_days_tracked(self):
        s = _make()
        for _ in range(5):
            s.simulate_day(0.18, 0.12, "bull")
        self.assertEqual(s._days_active, 5)

    def test_T92_inactive_days_tracked(self):
        s = _make()
        for _ in range(3):
            s.simulate_day(0.05, -0.06, "bear")
        self.assertEqual(s._days_inactive, 3)

    def test_T93_reset_state_clears_counters(self):
        s = _make()
        for _ in range(10):
            s.simulate_day(0.18, 0.12, "bull")
        s.reset_state()
        self.assertEqual(s._days_active, 0)
        self.assertEqual(s._days_inactive, 0)
        self.assertEqual(s._cumulative_yield_usd, 0.0)


# ─── T94: repr ───────────────────────────────────────────────────────────────

class TestRepr(unittest.TestCase):
    """T94: __repr__ contains key fields."""

    def test_T94_repr_contains_capital_and_pct(self):
        s = _make(capital=100_000, max_pct=0.20)
        r = repr(s)
        self.assertIn("DeltaNeutralSUSDeStrategy", r)
        self.assertIn("100,000", r)
        self.assertIn("20%", r)


# ─── T95–T96: Determinism with rng_seed ──────────────────────────────────────

class TestDeterminism(unittest.TestCase):
    """T95–T96: Reproducible results with identical rng_seed."""

    def test_T95_same_seed_same_result(self):
        s1 = _make(seed=42)
        s2 = _make(seed=42)
        r1 = s1.simulate_historical_scenario(100, "bull_2024")
        r2 = s2.simulate_historical_scenario(100, "bull_2024")
        self.assertEqual(r1["total_yield_usd"], r2["total_yield_usd"])
        self.assertEqual(r1["active_days"], r2["active_days"])

    def test_T96_different_seed_different_result(self):
        s1 = _make(seed=1)
        s2 = _make(seed=999)
        r1 = s1.simulate_historical_scenario(365, "bull_2024")
        r2 = s2.simulate_historical_scenario(365, "bull_2024")
        # Different seeds → different daily returns sequences
        # (same aggregate stats likely differ)
        self.assertNotEqual(r1["daily_returns"], r2["daily_returns"])


# ─── T97–T100: Import hygiene ────────────────────────────────────────────────

class TestImportHygiene(unittest.TestCase):
    """T97–T100: No forbidden imports (LLM, execution, risk agents)."""

    def test_T97_no_llm_sdk_imports(self):
        """delta_neutral_susde.py must not import LLM/anthropic SDK."""
        import ast
        src = Path(__file__).resolve().parents[2] / "spa_core" / "strategies" / "delta_neutral_susde.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        forbidden = {"anthropic", "openai", "langchain", "llm"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in getattr(node, "names", []):
                    name = alias.name or ""
                    self.assertFalse(
                        any(f in name.lower() for f in forbidden),
                        msg=f"Forbidden import found: {name}",
                    )

    def test_T98_no_execution_domain_imports(self):
        """delta_neutral_susde.py must not import spa_core.execution."""
        import ast
        src = Path(__file__).resolve().parents[2] / "spa_core" / "strategies" / "delta_neutral_susde.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(
                    "execution", node.module,
                    msg=f"Forbidden execution import: {node.module}",
                )

    def test_T99_stdlib_only_top_level_imports(self):
        """delta_neutral_susde.py must use only stdlib + spa_core imports."""
        import ast
        src = Path(__file__).resolve().parents[2] / "spa_core" / "strategies" / "delta_neutral_susde.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        allowed_prefixes = ("spa_core", "strategies", "__future__")
        stdlib_known = {
            "math", "random", "dataclasses", "typing",
            "json", "os", "sys", "pathlib", "datetime", "collections",
            "functools", "itertools", "statistics",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    self.assertIn(
                        root, stdlib_known,
                        msg=f"Non-stdlib top-level import: {alias.name}",
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root not in stdlib_known:
                    ok = any(node.module.startswith(p) for p in allowed_prefixes)
                    self.assertTrue(ok, msg=f"Non-stdlib/non-spa import: {node.module}")

    def test_T100_module_compiles_without_error(self):
        """delta_neutral_susde.py compiles cleanly."""
        import py_compile
        src = str(
            Path(__file__).resolve().parents[2] / "spa_core" / "strategies" / "delta_neutral_susde.py"
        )
        try:
            py_compile.compile(src, doraise=True)
        except py_compile.PyCompileError as e:
            self.fail(f"Compilation failed: {e}")


# ─── T101–T110: Allocation cap enforcement ───────────────────────────────────

class TestAllocationCap(unittest.TestCase):
    """T101–T110: enforce_allocation_cap clamps the sUSDe sleeve weight to the cap."""

    def setUp(self):
        self.s = _make(capital=100_000, max_pct=0.20)

    def test_T101_over_cap_request_is_clamped_pct(self):
        r = self.s.enforce_allocation_cap(requested_pct=0.30)
        self.assertTrue(r["capped"])
        self.assertAlmostEqual(r["allowed_pct"], 0.20, places=8)
        self.assertAlmostEqual(r["allowed_usd"], 20_000.0, places=4)

    def test_T102_under_cap_request_passes_through(self):
        r = self.s.enforce_allocation_cap(requested_pct=0.10)
        self.assertFalse(r["capped"])
        self.assertAlmostEqual(r["allowed_pct"], 0.10, places=8)
        self.assertAlmostEqual(r["allowed_usd"], 10_000.0, places=4)

    def test_T103_at_cap_boundary_not_flagged(self):
        r = self.s.enforce_allocation_cap(requested_pct=0.20)
        self.assertFalse(r["capped"])
        self.assertAlmostEqual(r["allowed_pct"], 0.20, places=8)

    def test_T104_over_cap_request_usd_is_clamped(self):
        r = self.s.enforce_allocation_cap(requested_usd=50_000)
        self.assertTrue(r["capped"])
        self.assertAlmostEqual(r["allowed_usd"], 20_000.0, places=4)

    def test_T105_default_request_is_the_cap(self):
        r = self.s.enforce_allocation_cap()
        self.assertAlmostEqual(r["allowed_pct"], 0.20, places=8)
        self.assertAlmostEqual(r["allowed_usd"], 20_000.0, places=4)

    def test_T106_negative_request_floored_to_zero(self):
        r = self.s.enforce_allocation_cap(requested_pct=-0.5)
        self.assertAlmostEqual(r["allowed_pct"], 0.0, places=8)

    def test_T107_custom_cap_respected(self):
        s = _make(capital=100_000, max_pct=0.15)
        r = s.enforce_allocation_cap(requested_pct=0.50)
        self.assertAlmostEqual(r["allowed_pct"], 0.15, places=8)
        self.assertAlmostEqual(r["allowed_usd"], 15_000.0, places=4)

    def test_T108_cap_never_exceeds_configured(self):
        for req in (0.0, 0.05, 0.20, 0.25, 1.0):
            r = self.s.enforce_allocation_cap(requested_pct=req)
            self.assertLessEqual(r["allowed_pct"], self.s.max_capital_pct + 1e-12)

    def test_T109_cap_constant_is_config_not_hardcoded_at_callsite(self):
        # Cap comes from the instance config, not a literal.
        self.assertEqual(self.s.max_capital_pct, MAX_CAPITAL_PCT)

    def test_T110_vportfolio_exposes_cap(self):
        vp = self.s.to_vportfolio_format()
        self.assertIn("allocation_cap", vp)
        self.assertAlmostEqual(vp["allocation_cap"]["max_capital_pct"], 0.20, places=8)


# ─── T111–T126: Negative-funding kill ────────────────────────────────────────

class TestFundingKill(unittest.TestCase):
    """T111–T126: deterministic, fail-closed negative-funding kill (Variant-N pattern)."""

    def setUp(self):
        # 24h kill window, 8h per observation → 3 consecutive sub-threshold obs to kill.
        self.s = _make()

    def test_T111_positive_funding_no_kill(self):
        for _ in range(10):
            r = self.s.funding_kill_check(0.0001)
        self.assertFalse(r["triggered"])
        self.assertFalse(self.s.is_killed)

    def test_T112_kill_fires_after_N_periods_not_before(self):
        # threshold 0.0, kill at 24h, 8h/obs → needs 3 sub-threshold obs.
        r1 = self.s.funding_kill_check(-0.001)   # 8h
        self.assertFalse(r1["triggered"])
        r2 = self.s.funding_kill_check(-0.001)   # 16h
        self.assertFalse(r2["triggered"])
        r3 = self.s.funding_kill_check(-0.001)   # 24h → fires
        self.assertTrue(r3["triggered"])

    def test_T113_kill_not_before_exact_boundary(self):
        # 2 obs = 16h < 24h → no kill yet
        self.s.funding_kill_check(-0.001)
        r = self.s.funding_kill_check(-0.001)
        self.assertFalse(r["triggered"])
        self.assertAlmostEqual(r["sub_threshold_hours"], 16.0, places=6)

    def test_T114_streak_resets_on_recovery(self):
        self.s.funding_kill_check(-0.001)   # 8h
        self.s.funding_kill_check(-0.001)   # 16h
        r = self.s.funding_kill_check(0.0005)  # recovers → reset
        self.assertEqual(r["sub_threshold_hours"], 0.0)
        self.assertFalse(r["triggered"])
        # Now two more negatives should NOT kill (streak was reset)
        self.s.funding_kill_check(-0.001)   # 8h
        r2 = self.s.funding_kill_check(-0.001)  # 16h
        self.assertFalse(r2["triggered"])

    def test_T115_positive_funding_never_kills_long_run(self):
        for _ in range(100):
            r = self.s.funding_kill_check(0.0003)
        self.assertFalse(r["triggered"])

    def test_T116_fail_closed_on_none(self):
        r = self.s.funding_kill_check(None)
        self.assertTrue(r["triggered"])
        self.assertIn("fail-closed", r["reason"])

    def test_T117_fail_closed_on_nan(self):
        r = self.s.funding_kill_check(float("nan"))
        self.assertTrue(r["triggered"])
        self.assertIn("fail-closed", r["reason"])

    def test_T118_fail_closed_on_inf(self):
        r = self.s.funding_kill_check(float("inf"))
        self.assertTrue(r["triggered"])

    def test_T119_killed_stays_killed(self):
        self.s.funding_kill_check(None)  # kill immediately
        r = self.s.funding_kill_check(0.05)  # even great funding can't un-kill
        self.assertTrue(r["triggered"])

    def test_T120_reset_clears_kill(self):
        self.s.funding_kill_check(None)
        self.assertTrue(self.s.is_killed)
        self.s.reset_state()
        self.assertFalse(self.s.is_killed)
        self.assertEqual(self.s._sub_threshold_hours, 0.0)

    def test_T121_killed_simulate_day_zero_yield(self):
        self.s.funding_kill_check(None)  # kill
        result = self.s.simulate_day(0.18, 0.12, "bull")  # would normally be active
        self.assertFalse(result["active"])
        self.assertEqual(result["yield_usd"], 0.0)
        self.assertEqual(result["reason"], "funding_kill_active")

    def test_T122_killed_vportfolio_inactive(self):
        self.s.funding_kill_check(None)
        vp = self.s.to_vportfolio_format(susde_apy=0.18, funding_rate_annual=0.12, market_regime="bull")
        self.assertFalse(vp["active"])
        self.assertTrue(vp["funding_kill"]["killed"])

    def test_T123_custom_threshold_below_zero(self):
        # Tolerate small negative funding (threshold -0.0005); -0.0002 is NOT sub-threshold.
        s = DeltaNeutralSUSDeStrategy(capital=100_000, funding_kill_threshold=-0.0005)
        for _ in range(10):
            r = s.funding_kill_check(-0.0002)
        self.assertFalse(r["triggered"])

    def test_T124_custom_kill_hours(self):
        # 8h kill window, 8h/obs → first sub-threshold obs kills.
        s = DeltaNeutralSUSDeStrategy(capital=100_000, funding_kill_hours=8.0)
        r = s.funding_kill_check(-0.001)
        self.assertTrue(r["triggered"])

    def test_T125_funding_signal_from_feed_reads_latest(self):
        class FakeFeed:
            def latest(self):
                return ("2026-06-25", -0.0009)
        rate = self.s.funding_signal_from_feed(feed=FakeFeed())
        self.assertAlmostEqual(rate, -0.0009, places=8)

    def test_T126_funding_signal_fail_closed_on_feed_error(self):
        class BrokenFeed:
            def latest(self):
                raise RuntimeError("no venue returned data")
        rate = self.s.funding_signal_from_feed(feed=BrokenFeed())
        self.assertIsNone(rate)  # None → caller's funding_kill_check fails closed
        # End-to-end: a None signal kills the sleeve.
        r = self.s.funding_kill_check(rate)
        self.assertTrue(r["triggered"])

    def test_T127_config_constants_exposed(self):
        self.assertEqual(FUNDING_KILL_THRESHOLD, 0.0)
        self.assertEqual(FUNDING_KILL_HOURS, 24.0)
        self.assertEqual(HOURS_PER_FUNDING_OBSERVATION, 8.0)


if __name__ == "__main__":
    unittest.main()
