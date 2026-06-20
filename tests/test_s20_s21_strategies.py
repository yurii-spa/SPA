"""
tests/test_s20_s21_strategies.py — MP-1511 (Sprint v11.27)

30 tests for:
  - S20CurveConvex (s20_curve_convex.py): Curve/Convex Yield Optimizer
  - S21AaveLoop    (s21_aave_loop.py):    Aave V3 Recursive USDC Loop

Tests are stdlib-only, no external deps, pure unit tests.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from spa_core.strategies.s20_curve_convex import (
    S20CurveConvex,
    CURVE_POOLS,
    POOL_ALLOCATION,
    CASH_BUFFER,
    TARGET_APY_MIN,
    TARGET_APY_MAX,
    STRATEGY_ID as S20_ID,
)
from spa_core.strategies.s21_aave_loop import (
    S21AaveLoop,
    LTV,
    MAX_LOOPS,
    HEALTH_FACTOR_MIN,
    STRATEGY_ID as S21_ID,
    _compute_effective_apy,
    _compute_effective_multiplier,
    _compute_health_factor,
)


# ══════════════════════════════════════════════════════════════════════════════
# S20 CurveConvex — 15 tests
# ══════════════════════════════════════════════════════════════════════════════

class TestS20CurveConvex:

    def setup_method(self):
        self.s20 = S20CurveConvex()
        # Base APY data covering all pools (9%, 8%, 7% as fractions)
        self.apy_ok = {
            "curve_3pool": 0.09,
            "curve_frax_usdc": 0.08,
            "curve_susd": 0.07,
        }
        self.apy_empty = {}

    # ── Identity ──────────────────────────────────────────────────────────────

    def test_strategy_id(self):
        """STRATEGY_ID is S20_CRV."""
        assert self.s20.STRATEGY_ID == "S20_CRV"

    def test_tier_t2(self):
        """Tier must be T2."""
        assert self.s20.TIER == "T2"

    def test_chain_ethereum(self):
        """Chain must be ethereum."""
        assert self.s20.CHAIN == "ethereum"

    # ── select_pool ───────────────────────────────────────────────────────────

    def test_select_pool_best_apy(self):
        """Returns the pool with the highest APY among eligible ones."""
        pool = self.s20.select_pool(self.apy_ok)
        # 3pool has 9% APY, highest
        assert pool == "3pool"

    def test_select_pool_none_if_empty(self):
        """Returns None when apy_data is empty."""
        assert self.s20.select_pool(self.apy_empty) is None

    def test_select_pool_respects_min_apy_floor(self):
        """Pool with APY below its own floor is excluded."""
        # frax_usdc floor is 6% (0.06). Give it only 5%.
        data = {"curve_frax_usdc": 0.05, "curve_3pool": 0.045}
        pool = self.s20.select_pool(data)
        # 3pool floor is 4%, 4.5% passes; frax_usdc 5% < 6% floor, excluded
        assert pool == "3pool"

    def test_select_pool_excludes_apy_below_global_min(self):
        """Pool APY below 1% global minimum is excluded."""
        data = {"curve_3pool": 0.005}  # 0.5% < 1% global min
        assert self.s20.select_pool(data) is None

    def test_select_pool_excludes_apy_above_global_max(self):
        """Pool APY above 30% global maximum is excluded as anomalous."""
        data = {"curve_3pool": 0.35}  # 35% > 30% → anomaly
        assert self.s20.select_pool(data) is None

    def test_select_pool_handles_non_numeric(self):
        """Non-numeric APY values are skipped gracefully."""
        data = {"curve_3pool": "N/A", "curve_frax_usdc": 0.08}
        pool = self.s20.select_pool(data)
        assert pool == "frax_usdc"

    # ── get_allocation ────────────────────────────────────────────────────────

    def test_get_allocation_pool_plus_cash(self):
        """80% to pool, 20% cash when pool qualifies."""
        capital = 100_000.0
        alloc = self.s20.get_allocation(capital, self.apy_ok)
        assert "curve_3pool" in alloc
        assert "cash" in alloc
        assert abs(alloc["curve_3pool"] - capital * POOL_ALLOCATION) < 1e-6
        assert abs(alloc["cash"] - capital * CASH_BUFFER) < 1e-6

    def test_get_allocation_fallback_cash(self):
        """100% cash when no pool qualifies."""
        alloc = self.s20.get_allocation(100_000.0, self.apy_empty)
        assert alloc == {"cash": 100_000.0}

    def test_get_allocation_zero_capital(self):
        """Zero capital → zero allocation values."""
        alloc = self.s20.get_allocation(0.0, self.apy_ok)
        assert all(v == 0.0 for v in alloc.values())

    def test_get_allocation_negative_capital_clamped(self):
        """Negative capital is clamped to 0."""
        alloc = self.s20.get_allocation(-5000.0, self.apy_ok)
        assert all(v == 0.0 for v in alloc.values())

    # ── blended_apy ───────────────────────────────────────────────────────────

    def test_blended_apy_correct(self):
        """blended_apy = 80% × best_pool_apy_pct."""
        expected = POOL_ALLOCATION * 9.0  # 3pool at 9%
        assert abs(self.s20.blended_apy(self.apy_ok) - expected) < 1e-4

    def test_blended_apy_zero_on_empty(self):
        """Returns 0 when no pool qualifies."""
        assert self.s20.blended_apy(self.apy_empty) == 0.0

    # ── risk_check ────────────────────────────────────────────────────────────

    def test_risk_check_ok(self):
        """Risk check passes with valid APY data."""
        ok, reason = self.s20.risk_check(self.apy_ok)
        assert ok is True
        assert reason == "ok"

    def test_risk_check_fails_no_pool(self):
        """Risk check fails when no pool qualifies."""
        ok, reason = self.s20.risk_check(self.apy_empty)
        assert ok is False
        assert "pool" in reason.lower() or "apy" in reason.lower()

    # ── backtest_stats ────────────────────────────────────────────────────────

    def test_backtest_stats_structure(self):
        """backtest_stats returns dict with expected keys."""
        stats = self.s20.backtest_stats()
        for key in ("sharpe", "max_dd", "annual_return", "win_rate"):
            assert key in stats

    # ── to_dict ───────────────────────────────────────────────────────────────

    def test_to_dict_has_strategy_id(self):
        """to_dict includes strategy_id field."""
        d = self.s20.to_dict(100_000.0, self.apy_ok)
        assert d["strategy_id"] == "S20_CRV"

    def test_available_pools(self):
        """available_pools returns list of all configured pool names."""
        pools = self.s20.available_pools()
        assert set(pools) == set(CURVE_POOLS.keys())


# ══════════════════════════════════════════════════════════════════════════════
# S21 AaveLoop — 15 tests
# ══════════════════════════════════════════════════════════════════════════════

class TestS21AaveLoop:

    def setup_method(self):
        self.s21 = S21AaveLoop()
        # Realistic Aave V3 USDC rates where supply < borrow (common)
        self.apy_ok = {
            "aave_v3_usdc_supply": 0.048,   # 4.8% supply
            "aave_v3_usdc_borrow": 0.055,   # 5.5% borrow
        }
        # Profitable: supply > borrow, net loop APY is positive
        self.apy_profitable = {
            "aave_v3_usdc_supply": 0.065,   # 6.5% supply > borrow
            "aave_v3_usdc_borrow": 0.040,   # 4.0% borrow → profitable loop
        }
        self.apy_empty = {}

    # ── Note on MAX_LOOPS ─────────────────────────────────────────────────────
    # MAX_LOOPS = 2 gives HF ≈ 1.44 > 1.35 floor (safe).
    # MAX_LOOPS = 3 would give HF ≈ 1.28 < 1.35 floor (fails risk gate).
    # Tests below are written for MAX_LOOPS = 2.

    # ── Identity ──────────────────────────────────────────────────────────────

    def test_strategy_id(self):
        """STRATEGY_ID is S21_LOOP."""
        assert self.s21.STRATEGY_ID == "S21_LOOP"

    def test_tier_t2(self):
        """Tier must be T2."""
        assert self.s21.TIER == "T2"

    # ── compute_loop_apy ──────────────────────────────────────────────────────

    def test_compute_loop_apy_zero_loops(self):
        """0 loops → same as plain supply APY."""
        apy = self.s21.compute_loop_apy(0.06, 0.04, n_loops=0)
        assert abs(apy - 6.0) < 1e-4

    def test_compute_loop_apy_increases_with_profitable_spread(self):
        """Loop APY increases with loops when supply > borrow (profitable spread)."""
        s, b = 0.065, 0.040
        apy_0 = self.s21.compute_loop_apy(s, b, n_loops=0)
        apy_3 = self.s21.compute_loop_apy(s, b, n_loops=3)
        assert apy_3 > apy_0

    def test_compute_loop_apy_caps_at_max_loops(self):
        """n_loops capped at MAX_LOOPS even if higher value passed."""
        s, b = 0.06, 0.04
        apy_cap = self.s21.compute_loop_apy(s, b, n_loops=MAX_LOOPS)
        apy_over = self.s21.compute_loop_apy(s, b, n_loops=MAX_LOOPS + 10)
        assert abs(apy_cap - apy_over) < 1e-6

    # ── optimal_loops ─────────────────────────────────────────────────────────

    def test_optimal_loops_profitable_spread(self):
        """Returns >0 loops when supply > borrow."""
        loops = self.s21.optimal_loops(0.065, 0.040)
        assert loops > 0

    def test_optimal_loops_zero_when_borrow_exceeds_supply(self):
        """Returns 0 loops when borrow APY > supply APY (no benefit from looping)."""
        loops = self.s21.optimal_loops(0.030, 0.060)
        assert loops == 0

    # ── get_allocation ────────────────────────────────────────────────────────

    def test_get_allocation_profitable(self):
        """Returns loop position + cash when strategy is profitable."""
        alloc = self.s21.get_allocation(100_000.0, self.apy_profitable)
        assert "aave_v3_usdc_loop" in alloc
        assert "cash" in alloc
        total = sum(alloc.values())
        assert abs(total - 100_000.0) < 1e-4

    def test_get_allocation_cash_fallback(self):
        """Falls back to cash when risk_check fails."""
        alloc = self.s21.get_allocation(100_000.0, self.apy_empty)
        assert alloc == {"cash": 100_000.0}

    def test_get_allocation_zero_capital(self):
        """Zero capital → zero values."""
        alloc = self.s21.get_allocation(0.0, self.apy_profitable)
        assert all(v == 0.0 for v in alloc.values())

    # ── health_factor_estimate ────────────────────────────────────────────────

    def test_health_factor_infinite_at_zero_loops(self):
        """Health factor is infinite with 0 loops (no debt)."""
        hf = self.s21.health_factor_estimate(100_000.0, n_loops=0)
        assert hf == float("inf")

    def test_health_factor_above_minimum(self):
        """Estimated HF with MAX_LOOPS and safe LTV must exceed HEALTH_FACTOR_MIN."""
        hf = self.s21.health_factor_estimate(100_000.0)
        assert hf >= HEALTH_FACTOR_MIN

    # ── risk_check ────────────────────────────────────────────────────────────

    def test_risk_check_missing_supply_key(self):
        """Fails if supply APY key missing."""
        ok, reason = self.s21.risk_check({"aave_v3_usdc_borrow": 0.04})
        assert ok is False
        assert "supply" in reason.lower()

    def test_risk_check_missing_borrow_key(self):
        """Fails if borrow APY key missing."""
        ok, reason = self.s21.risk_check({"aave_v3_usdc_supply": 0.05})
        assert ok is False
        assert "borrow" in reason.lower()

    def test_risk_check_passes_profitable(self):
        """Risk check passes when spread is profitable."""
        ok, reason = self.s21.risk_check(self.apy_profitable)
        assert ok is True
        assert reason == "ok"

    def test_risk_check_fails_out_of_bounds(self):
        """Fails when supply APY is out of RiskPolicy bounds."""
        ok, reason = self.s21.risk_check({
            "aave_v3_usdc_supply": 0.0005,  # 0.05% < 1% floor
            "aave_v3_usdc_borrow": 0.005,
        })
        assert ok is False

    # ── Module-level math helpers ─────────────────────────────────────────────

    def test_effective_multiplier_zero_loops(self):
        """0 loops → multiplier of 1.0 (just original deposit)."""
        m = _compute_effective_multiplier(0.80, 0)
        assert abs(m - 1.0) < 1e-8

    def test_effective_multiplier_increases_with_loops(self):
        """Multiplier strictly increases with loop count."""
        m0 = _compute_effective_multiplier(0.80, 0)
        m1 = _compute_effective_multiplier(0.80, 1)
        m3 = _compute_effective_multiplier(0.80, 3)
        assert m3 > m1 > m0

    def test_health_factor_no_debt(self):
        """_compute_health_factor returns inf when debt is zero."""
        assert _compute_health_factor(100_000.0, 0.0) == float("inf")

    def test_health_factor_formula(self):
        """_compute_health_factor matches manual formula."""
        # deposit=100, debt=50, threshold=0.85 → HF = 100*0.85/50 = 1.7
        hf = _compute_health_factor(100.0, 50.0, liquidation_threshold=0.85)
        assert abs(hf - 1.7) < 1e-6
