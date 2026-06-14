"""
spa_core/tests/test_pendle_yt.py — Unit tests for S10 Pendle YT Speculation Strategy

Coverage (57 tests):
  1-8   PendleYTConfig validation and defaults
  9-19  entry_gate logic (cushion check, boundary conditions)
  20-30 daily_pnl calculation (bull / base / bear, inactive guard)
  31-42 simulate_day state transitions (active/inactive, exit triggers)
  43-50 should_exit (maturity threshold, apy below implied, both)
  51-54 net_apy_annualized math verification
  55-57 scenario_analysis all 3 scenarios
  58-61 to_vportfolio_format structure and field presence
  62-64 capital cap enforcement (max 30%)
  65-67 make_strategy factory
  68-70 PendleYTStrategy edge cases (zero capital, large capital, exact boundary)
  71-74 STRATEGY_REGISTRY integration (S10 present, config fields)
  75-77 Bonus: multi-day simulation correctness

Run:
    cd spa_core
    python -m pytest tests/test_pendle_yt.py -v
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup so tests run from any working directory
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_SPA_ROOT = _HERE.parent.parent   # SPA_Claude/
sys.path.insert(0, str(_SPA_ROOT))

from spa_core.strategies.pendle_yt import (
    PENDLE_MATURITY_DAYS,
    YT_LEVERAGE_MULTIPLIER,
    PendleYTConfig,
    PendleYTStrategy,
    make_strategy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_strategy(capital: float = 100_000.0) -> PendleYTStrategy:
    return PendleYTStrategy(capital=capital)


def _active_strategy(capital: float = 100_000.0, apy: float = 0.15) -> PendleYTStrategy:
    s = _default_strategy(capital)
    s.current_apy = apy
    s.is_active = True
    return s


# ===========================================================================
# 1-8: PendleYTConfig — defaults and validation
# ===========================================================================

class TestPendleYTConfigDefaults:
    def test_default_max_capital_pct(self):
        cfg = PendleYTConfig()
        assert cfg.max_capital_pct == 0.30

    def test_default_min_apy_cushion(self):
        cfg = PendleYTConfig()
        assert cfg.min_apy_cushion == 0.25

    def test_default_implied_yield_annual(self):
        cfg = PendleYTConfig()
        assert cfg.implied_yield_annual == 0.08

    def test_default_yt_price_pct(self):
        cfg = PendleYTConfig()
        assert cfg.yt_price_pct == 0.25

    def test_default_exit_at_maturity_pct(self):
        cfg = PendleYTConfig()
        assert cfg.exit_at_maturity_pct == 0.60

    def test_config_override_max_capital(self):
        cfg = PendleYTConfig(max_capital_pct=0.20)
        assert cfg.max_capital_pct == 0.20

    def test_config_invalid_max_capital_zero(self):
        with pytest.raises(ValueError, match="max_capital_pct"):
            PendleYTConfig(max_capital_pct=0.0)

    def test_config_invalid_yt_price_pct_one(self):
        with pytest.raises(ValueError, match="yt_price_pct"):
            PendleYTConfig(yt_price_pct=1.0)


# ===========================================================================
# 9-19: entry_gate logic
# ===========================================================================

class TestEntryGate:
    def test_entry_gate_above_threshold(self):
        # threshold = 8% * 1.25 = 10%, apy=15% → True
        s = _default_strategy()
        s.current_apy = 0.15
        assert s.entry_gate() is True

    def test_entry_gate_exactly_at_threshold_false(self):
        # current_apy == threshold → must be STRICTLY greater
        s = _default_strategy()
        s.current_apy = 0.10   # 8% * 1.25 = 10% exactly
        assert s.entry_gate() is False

    def test_entry_gate_below_threshold(self):
        s = _default_strategy()
        s.current_apy = 0.09   # below 10%
        assert s.entry_gate() is False

    def test_entry_gate_at_implied_only(self):
        s = _default_strategy()
        s.current_apy = 0.08   # exactly implied — no cushion
        assert s.entry_gate() is False

    def test_entry_gate_zero_apy(self):
        s = _default_strategy()
        s.current_apy = 0.0
        assert s.entry_gate() is False

    def test_entry_gate_custom_cushion_larger(self):
        cfg = PendleYTConfig(min_apy_cushion=0.50)  # 50% cushion → threshold 12%
        s = PendleYTStrategy(capital=100_000.0, config=cfg)
        s.current_apy = 0.11   # below 12%
        assert s.entry_gate() is False

    def test_entry_gate_custom_cushion_larger_above(self):
        cfg = PendleYTConfig(min_apy_cushion=0.50)
        s = PendleYTStrategy(capital=100_000.0, config=cfg)
        s.current_apy = 0.13   # above 12%
        assert s.entry_gate() is True

    def test_entry_gate_custom_implied_higher(self):
        cfg = PendleYTConfig(implied_yield_annual=0.10)  # threshold = 10%*1.25=12.5%
        s = PendleYTStrategy(capital=100_000.0, config=cfg)
        s.current_apy = 0.12   # below 12.5%
        assert s.entry_gate() is False

    def test_entry_gate_custom_implied_higher_above(self):
        cfg = PendleYTConfig(implied_yield_annual=0.10)
        s = PendleYTStrategy(capital=100_000.0, config=cfg)
        s.current_apy = 0.13   # above 12.5%
        assert s.entry_gate() is True

    def test_entry_gate_very_high_apy(self):
        s = _default_strategy()
        s.current_apy = 0.50
        assert s.entry_gate() is True

    def test_entry_gate_just_above_threshold(self):
        s = _default_strategy()
        s.current_apy = 0.10 + 1e-9   # just above 10%
        assert s.entry_gate() is True


# ===========================================================================
# 20-30: daily_pnl
# ===========================================================================

class TestDailyPnl:
    def test_daily_pnl_inactive_is_zero(self):
        s = _default_strategy()
        s.current_apy = 0.20
        s.is_active = False
        assert s.daily_pnl() == 0.0

    def test_daily_pnl_bull_scenario(self):
        # apy=20%, implied=8%, leverage=3.5, capital_deployed=30K
        s = _active_strategy(capital=100_000.0, apy=0.20)
        expected = (0.20 - 0.08) * 3.5 * 30_000.0 / 365.0
        assert abs(s.daily_pnl() - expected) < 1e-6

    def test_daily_pnl_base_scenario(self):
        # apy=12%, implied=8%
        s = _active_strategy(capital=100_000.0, apy=0.12)
        expected = (0.12 - 0.08) * 3.5 * 30_000.0 / 365.0
        assert abs(s.daily_pnl() - expected) < 1e-6

    def test_daily_pnl_bear_scenario_zero(self):
        # apy=6% < implied=8% → pnl=0 (YT worthless, no daily gain modelled)
        s = _active_strategy(capital=100_000.0, apy=0.06)
        assert s.daily_pnl() == 0.0

    def test_daily_pnl_at_implied_zero(self):
        # apy exactly at implied → no excess → 0
        s = _active_strategy(capital=100_000.0, apy=0.08)
        assert s.daily_pnl() == 0.0

    def test_daily_pnl_positive_when_above_implied(self):
        s = _active_strategy(capital=100_000.0, apy=0.15)
        assert s.daily_pnl() > 0.0

    def test_daily_pnl_scales_with_capital(self):
        s1 = _active_strategy(capital=100_000.0, apy=0.15)
        s2 = _active_strategy(capital=200_000.0, apy=0.15)
        assert abs(s2.daily_pnl() - 2 * s1.daily_pnl()) < 1e-6

    def test_daily_pnl_scales_with_excess_apy(self):
        s1 = _active_strategy(capital=100_000.0, apy=0.12)  # excess 4%
        s2 = _active_strategy(capital=100_000.0, apy=0.16)  # excess 8%
        assert abs(s2.daily_pnl() / s1.daily_pnl() - 2.0) < 1e-6

    def test_daily_pnl_custom_max_capital_pct(self):
        cfg = PendleYTConfig(max_capital_pct=0.50)
        s = PendleYTStrategy(capital=100_000.0, config=cfg, current_apy=0.20, is_active=True)
        expected = (0.20 - 0.08) * 3.5 * 50_000.0 / 365.0
        assert abs(s.daily_pnl() - expected) < 1e-6

    def test_daily_pnl_uses_leverage_multiplier(self):
        s = _active_strategy(capital=100_000.0, apy=0.20)
        # Verify 3.5x multiplier is used
        base = (0.20 - 0.08) * 30_000.0 / 365.0   # without leverage
        assert abs(s.daily_pnl() / base - YT_LEVERAGE_MULTIPLIER) < 1e-6

    def test_daily_pnl_just_above_implied(self):
        s = _active_strategy(capital=100_000.0, apy=0.08 + 1e-6)
        assert s.daily_pnl() > 0.0


# ===========================================================================
# 31-42: simulate_day
# ===========================================================================

class TestSimulateDay:
    def test_simulate_day_inactive_does_nothing(self):
        s = _default_strategy()
        s.is_active = False
        state = s.simulate_day(apy=0.20)
        assert state["day"] == 0
        assert state["daily_pnl"] == 0.0
        assert state["accumulated_yield"] == 0.0
        assert state["is_active"] is False
        assert state["exited"] is False

    def test_simulate_day_increments_days_held(self):
        s = _active_strategy(apy=0.15)
        s.simulate_day(apy=0.15)
        assert s.days_held == 1

    def test_simulate_day_accumulates_yield(self):
        s = _active_strategy(capital=100_000.0, apy=0.15)
        state = s.simulate_day(apy=0.15)
        assert state["daily_pnl"] > 0.0
        assert state["accumulated_yield"] == pytest.approx(state["daily_pnl"], rel=1e-6)

    def test_simulate_day_updates_current_apy(self):
        s = _active_strategy(apy=0.10)
        s.simulate_day(apy=0.20)
        assert s.current_apy == 0.20

    def test_simulate_day_returns_correct_keys(self):
        s = _active_strategy(apy=0.15)
        state = s.simulate_day(apy=0.15)
        for key in ("day", "apy", "is_active", "daily_pnl", "accumulated_yield", "exited"):
            assert key in state

    def test_simulate_day_multi_day_accumulation(self):
        s = _active_strategy(capital=100_000.0, apy=0.15)
        total = 0.0
        for _ in range(5):
            state = s.simulate_day(apy=0.15)
            total += state["daily_pnl"]
        assert abs(s.accumulated_yield - total) < 1e-6

    def test_simulate_day_exit_on_low_apy(self):
        s = _active_strategy(apy=0.15)
        # Drop below implied → should exit
        state = s.simulate_day(apy=0.05)
        assert state["exited"] is True
        assert s.is_active is False

    def test_simulate_day_no_exit_above_implied(self):
        s = _active_strategy(apy=0.15)
        state = s.simulate_day(apy=0.15)
        assert state["exited"] is False
        assert s.is_active is True

    def test_simulate_day_exit_at_maturity_threshold(self):
        s = _active_strategy(apy=0.20)
        threshold = s.exit_day_threshold
        # Simulate exactly threshold days
        for _ in range(threshold - 1):
            s.simulate_day(apy=0.20)
        assert s.is_active is True
        state = s.simulate_day(apy=0.20)  # day = threshold
        assert state["exited"] is True
        assert s.is_active is False

    def test_simulate_day_once_exited_stays_inactive(self):
        s = _active_strategy(apy=0.15)
        s.simulate_day(apy=0.05)   # triggers exit
        state2 = s.simulate_day(apy=0.20)
        assert state2["exited"] is False
        assert state2["daily_pnl"] == 0.0

    def test_simulate_day_zero_apy_exits(self):
        s = _active_strategy(apy=0.15)
        state = s.simulate_day(apy=0.0)
        assert state["exited"] is True

    def test_simulate_day_accumulated_yield_matches_sum(self):
        s = _active_strategy(capital=100_000.0, apy=0.15)
        pnl_sum = 0.0
        for i in range(10):
            state = s.simulate_day(apy=0.15)
            pnl_sum += state["daily_pnl"]
        assert abs(s.accumulated_yield - pnl_sum) < 1e-4


# ===========================================================================
# 43-50: should_exit
# ===========================================================================

class TestShouldExit:
    def test_should_exit_false_when_healthy(self):
        s = _active_strategy(apy=0.15)
        s.days_held = 50
        assert s.should_exit() is False

    def test_should_exit_apy_below_implied(self):
        s = _active_strategy(apy=0.05)   # 5% < implied 8%
        s.days_held = 10
        assert s.should_exit() is True

    def test_should_exit_exactly_at_implied_false(self):
        # apy == implied → not below implied, but no profit either
        # should_exit checks STRICTLY less than
        s = _active_strategy(apy=0.08)
        s.days_held = 10
        assert s.should_exit() is False

    def test_should_exit_just_below_implied(self):
        s = _active_strategy(apy=0.08 - 1e-9)
        s.days_held = 10
        assert s.should_exit() is True

    def test_should_exit_at_maturity_threshold(self):
        s = _active_strategy(apy=0.20)
        s.days_held = s.exit_day_threshold
        assert s.should_exit() is True

    def test_should_exit_one_day_before_threshold(self):
        s = _active_strategy(apy=0.20)
        s.days_held = s.exit_day_threshold - 1
        assert s.should_exit() is False

    def test_should_exit_threshold_default_value(self):
        s = _default_strategy()
        # 60% of 182 = 109.2 → floor = 109
        assert s.exit_day_threshold == math.floor(182 * 0.60)

    def test_should_exit_custom_exit_pct(self):
        cfg = PendleYTConfig(exit_at_maturity_pct=0.50)  # 50% of 182 = 91
        s = PendleYTStrategy(capital=100_000.0, config=cfg, current_apy=0.20, is_active=True)
        s.days_held = 91
        assert s.should_exit() is True


# ===========================================================================
# 51-54: net_apy_annualized
# ===========================================================================

class TestNetApyAnnualized:
    def test_net_apy_zero_days(self):
        s = _default_strategy()
        assert s.net_apy_annualized() == 0.0

    def test_net_apy_zero_capital(self):
        s = PendleYTStrategy(capital=0.0)
        s.days_held = 30
        assert s.net_apy_annualized() == 0.0

    def test_net_apy_formula_consistency(self):
        # After N days at constant apy, net_apy should ≈ (apy - implied) * leverage
        s = _active_strategy(capital=100_000.0, apy=0.20)
        for _ in range(100):
            s.simulate_day(apy=0.20)
        # Expected: (20%-8%) * 3.5 = 42% net
        expected_net = (0.20 - 0.08) * YT_LEVERAGE_MULTIPLIER
        assert abs(s.net_apy_annualized() - expected_net) < 1e-4

    def test_net_apy_grows_with_yield(self):
        s1 = _active_strategy(capital=100_000.0, apy=0.12)
        s2 = _active_strategy(capital=100_000.0, apy=0.20)
        for _ in range(30):
            s1.simulate_day(apy=0.12)
            s2.simulate_day(apy=0.20)
        assert s2.net_apy_annualized() > s1.net_apy_annualized()


# ===========================================================================
# 55-57: scenario_analysis
# ===========================================================================

class TestScenarioAnalysis:
    def test_scenario_analysis_returns_three_scenarios(self):
        s = _default_strategy()
        result = s.scenario_analysis()
        assert set(result.keys()) == {"bull", "base", "bear"}

    def test_scenario_analysis_bull_gross_apy(self):
        s = _default_strategy()
        result = s.scenario_analysis()
        # gross_apy = implied + (20%-8%)*3.5 = 0.08 + 0.42 = 0.50
        assert abs(result["bull"]["gross_apy"] - 0.50) < 1e-4

    def test_scenario_analysis_bull_net_apy(self):
        s = _default_strategy()
        result = s.scenario_analysis()
        # net_apy = (20%-8%)*3.5 = 0.42
        assert abs(result["bull"]["net_apy"] - 0.42) < 1e-4

    def test_scenario_analysis_base_gross_apy(self):
        s = _default_strategy()
        result = s.scenario_analysis()
        # gross_apy = 0.08 + (12%-8%)*3.5 = 0.08 + 0.14 = 0.22
        assert abs(result["base"]["gross_apy"] - 0.22) < 1e-4

    def test_scenario_analysis_base_net_apy(self):
        s = _default_strategy()
        result = s.scenario_analysis()
        # net_apy = (12%-8%)*3.5 = 0.14
        assert abs(result["base"]["net_apy"] - 0.14) < 1e-4

    def test_scenario_analysis_bear_verdict(self):
        s = _default_strategy()
        result = s.scenario_analysis()
        assert result["bear"]["verdict"] == "max_loss"

    def test_scenario_analysis_bull_verdict(self):
        s = _default_strategy()
        result = s.scenario_analysis()
        assert result["bull"]["verdict"] == "profit"

    def test_scenario_analysis_bear_max_loss_value(self):
        s = _default_strategy(capital=100_000.0)
        result = s.scenario_analysis()
        # max_loss = -(yt_price_pct * capital_deployed) = -(0.25 * 30_000) = -7_500
        expected_loss = -(0.25 * 30_000.0)
        assert abs(result["bear"]["pnl_usd"] - expected_loss) < 1e-2

    def test_scenario_analysis_bear_gross_apy_zero(self):
        s = _default_strategy()
        result = s.scenario_analysis()
        assert result["bear"]["gross_apy"] == 0.0

    def test_scenario_analysis_bull_pnl_positive(self):
        s = _default_strategy(capital=100_000.0)
        result = s.scenario_analysis()
        assert result["bull"]["pnl_usd"] > 0.0

    def test_scenario_analysis_holding_days_correct(self):
        s = _default_strategy()
        result = s.scenario_analysis()
        expected_days = math.floor(PENDLE_MATURITY_DAYS * 0.60)
        assert result["bull"]["holding_days"] == expected_days

    def test_scenario_analysis_bear_net_apy_is_negative(self):
        s = _default_strategy()
        result = s.scenario_analysis()
        assert result["bear"]["net_apy"] < 0.0


# ===========================================================================
# 58-61: to_vportfolio_format
# ===========================================================================

class TestToVportfolioFormat:
    def test_vportfolio_required_keys_present(self):
        s = _active_strategy(capital=100_000.0, apy=0.15)
        vp = s.to_vportfolio_format()
        required = {
            "strategy_id", "strategy_name", "tier", "risk_level",
            "is_active", "capital_total", "capital_deployed",
            "capital_deployed_pct", "current_apy", "days_held",
            "accumulated_yield", "net_apy_annualized",
            "entry_gate_open", "should_exit_now",
            "implied_yield_annual", "max_capital_pct",
        }
        assert required <= set(vp.keys())

    def test_vportfolio_strategy_id(self):
        s = _default_strategy()
        assert s.to_vportfolio_format()["strategy_id"] == "S10"

    def test_vportfolio_tier(self):
        s = _default_strategy()
        assert s.to_vportfolio_format()["tier"] == "T3"

    def test_vportfolio_capital_deployed_equals_30pct(self):
        s = _default_strategy(capital=100_000.0)
        vp = s.to_vportfolio_format()
        assert abs(vp["capital_deployed"] - 30_000.0) < 1e-2

    def test_vportfolio_entry_gate_true_when_above_threshold(self):
        s = _default_strategy()
        s.current_apy = 0.15
        vp = s.to_vportfolio_format()
        assert vp["entry_gate_open"] is True

    def test_vportfolio_should_exit_now_false_when_inactive(self):
        s = _default_strategy()
        s.is_active = False
        vp = s.to_vportfolio_format()
        assert vp["should_exit_now"] is False


# ===========================================================================
# 62-64: capital cap enforcement
# ===========================================================================

class TestCapitalCapEnforcement:
    def test_capital_deployed_max_30pct(self):
        s = _default_strategy(capital=100_000.0)
        assert abs(s.capital_deployed - 30_000.0) < 1e-2

    def test_capital_deployed_scales_proportionally(self):
        s1 = _default_strategy(capital=50_000.0)
        s2 = _default_strategy(capital=200_000.0)
        assert abs(s1.capital_deployed - 15_000.0) < 1e-2
        assert abs(s2.capital_deployed - 60_000.0) < 1e-2

    def test_capital_cap_config_override(self):
        cfg = PendleYTConfig(max_capital_pct=0.10)
        s = PendleYTStrategy(capital=100_000.0, config=cfg)
        assert abs(s.capital_deployed - 10_000.0) < 1e-2


# ===========================================================================
# 65-67: make_strategy factory
# ===========================================================================

class TestMakeStrategyFactory:
    def test_make_strategy_returns_pendle_yt_strategy(self):
        s = make_strategy(100_000.0)
        assert isinstance(s, PendleYTStrategy)

    def test_make_strategy_uses_default_config(self):
        s = make_strategy(100_000.0)
        assert s.config.max_capital_pct == 0.30
        assert s.config.implied_yield_annual == 0.08

    def test_make_strategy_config_override(self):
        s = make_strategy(100_000.0, max_capital_pct=0.20, implied_yield_annual=0.10)
        assert s.config.max_capital_pct == 0.20
        assert s.config.implied_yield_annual == 0.10


# ===========================================================================
# 68-70: PendleYTStrategy edge cases
# ===========================================================================

class TestEdgeCases:
    def test_zero_capital_pnl_is_zero(self):
        s = PendleYTStrategy(capital=0.0)
        s.is_active = True
        s.current_apy = 0.20
        assert s.daily_pnl() == 0.0

    def test_large_capital_pnl_scales(self):
        s1 = _active_strategy(capital=100_000.0, apy=0.20)
        s2 = _active_strategy(capital=10_000_000.0, apy=0.20)
        assert abs(s2.daily_pnl() / s1.daily_pnl() - 100.0) < 1e-6

    def test_exact_threshold_days_triggers_exit(self):
        s = _active_strategy(apy=0.20)
        threshold = s.exit_day_threshold
        s.days_held = threshold
        assert s.should_exit() is True


# ===========================================================================
# 71-74: STRATEGY_REGISTRY integration
# ===========================================================================

class TestStrategyRegistryIntegration:
    @pytest.fixture(autouse=True)
    def _import_registry(self):
        from spa_core.paper_trading.strategy_registry import STRATEGY_REGISTRY, get_strategy
        self.STRATEGY_REGISTRY = STRATEGY_REGISTRY
        self.get_strategy = get_strategy

    def test_s10_present_in_registry(self):
        assert "S10" in self.STRATEGY_REGISTRY

    def test_s10_name(self):
        cfg = self.STRATEGY_REGISTRY["S10"]
        assert cfg.name == "Pendle YT Speculation"

    def test_s10_tier(self):
        cfg = self.STRATEGY_REGISTRY["S10"]
        assert cfg.tier == "T3"

    def test_s10_allocations_sum_lte_one(self):
        cfg = self.STRATEGY_REGISTRY["S10"]
        total = sum(cfg.allocations.values())
        assert total <= 1.0 + 1e-9

    def test_s10_kill_drawdown(self):
        cfg = self.STRATEGY_REGISTRY["S10"]
        assert cfg.kill_drawdown_pct == pytest.approx(0.30, rel=1e-6)

    def test_s10_target_apy_range(self):
        cfg = self.STRATEGY_REGISTRY["S10"]
        assert cfg.target_apy_min < cfg.target_apy_max
        assert cfg.target_apy_min == pytest.approx(14.0)
        assert cfg.target_apy_max == pytest.approx(42.0)

    def test_s10_status_active(self):
        cfg = self.STRATEGY_REGISTRY["S10"]
        assert cfg.status == "active"

    def test_s10_strategy_class(self):
        cfg = self.STRATEGY_REGISTRY["S10"]
        assert cfg.strategy_class == "PendleYTStrategy"


# ===========================================================================
# 75-77 (Bonus): multi-day simulation correctness
# ===========================================================================

class TestMultiDaySimulation:
    def test_bull_run_109_days(self):
        """Full bull run for 109 days (60% of 182) at 20% APY."""
        s = PendleYTStrategy(capital=100_000.0, is_active=True)
        threshold = s.exit_day_threshold  # 109
        total_pnl = 0.0
        exited = False
        for day in range(threshold):
            state = s.simulate_day(apy=0.20)
            total_pnl += state["daily_pnl"]
            if state["exited"]:
                exited = True
                break
        assert exited is True
        # Expected total: net_apy * capital_deployed * holding_days/365
        expected = 0.42 * 30_000.0 * (threshold / 365.0)
        assert abs(total_pnl - expected) < 1.0   # within $1 tolerance

    def test_bear_run_exits_immediately_on_low_apy(self):
        """Bear scenario: first day with apy<implied triggers exit."""
        s = PendleYTStrategy(capital=100_000.0, is_active=True)
        state = s.simulate_day(apy=0.05)
        assert state["exited"] is True
        assert state["daily_pnl"] == 0.0   # below implied → no gain

    def test_mixed_apy_run(self):
        """Mixed APY: profit days then drop below implied → exit."""
        s = PendleYTStrategy(capital=100_000.0, is_active=True)
        # 5 profitable days
        for _ in range(5):
            state = s.simulate_day(apy=0.15)
            assert not state["exited"]
        # Then drop
        state = s.simulate_day(apy=0.07)
        assert state["exited"] is True
        # Accumulated yield from the 5 profitable days is still intact
        assert s.accumulated_yield > 0.0


# ===========================================================================
# Module-level constants sanity
# ===========================================================================

class TestModuleConstants:
    def test_pendle_maturity_days(self):
        assert PENDLE_MATURITY_DAYS == 182

    def test_yt_leverage_multiplier(self):
        assert YT_LEVERAGE_MULTIPLIER == 3.5

    def test_exit_day_threshold_default(self):
        s = _default_strategy()
        assert s.exit_day_threshold == 109   # floor(182 * 0.60)
