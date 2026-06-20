"""
spa_core/tests/test_s2_lp_stable.py

Tests for _S2Position and LPStableStrategy
(spa_core/strategies/s2_lp_stable.py).

MP-1459 (v10.75) — Sprint 1 coverage expansion.

Run:
    python3 -m unittest spa_core.tests.test_s2_lp_stable -v
"""
from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.s2_lp_stable import (
    _S2Position,
    LPStableStrategy,
    STRATEGY_ID,
    LP_POOL_PREFIXES,
    LENDING_PREFIXES,
    FEE_APY_PREMIUM,
    MAX_CONCENTRATION,
    MIN_APY,
    MAX_APY,
    MIN_TVL_USD,
    CASH_BUFFER,
    REBALANCE_DAYS,
    REBALANCE_APY_GAP,
    MAX_POSITIONS,
    MAX_IL_PCT,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _lp_protocol(key="curve-3pool-usdc", apy=9.0, tvl=20_000_000) -> dict:
    return {"protocol_key": key, "apy": apy, "tvl_usd": tvl, "tier": "T2"}


def _lending_protocol(key="aave-v3-usdc", apy=5.0, tvl=15_000_000) -> dict:
    return {"protocol_key": key, "apy": apy, "tvl_usd": tvl, "tier": "T1"}


def _hist_row(timestamp="2026-01-01", protocol_key="curve-3pool-usdc",
              apy=9.0, tvl=20_000_000) -> dict:
    return {
        "timestamp": timestamp,
        "protocol_key": protocol_key,
        "apy": apy,
        "tvl_usd": tvl,
        "tier": "T2",
    }


def _make_history(n_days=30, key="curve-3pool-usdc", apy=9.0) -> list[dict]:
    start = date(2026, 1, 1)
    return [
        _hist_row(str(start + timedelta(days=i)), protocol_key=key, apy=apy)
        for i in range(n_days)
    ]


# ─── _S2Position Tests ────────────────────────────────────────────────────────

class TestS2Position(unittest.TestCase):

    def test_daily_interest_positive(self):
        p = _S2Position("curve-3pool", "lp", 10_000.0, 9.0, current_apy=9.0)
        self.assertGreater(p.daily_interest(), 0.0)

    def test_daily_interest_formula(self):
        # 36500 * 10 / 100 / 365 = 10.0
        p = _S2Position("curve-3pool", "lp", 36500.0, 10.0, current_apy=10.0)
        self.assertAlmostEqual(p.daily_interest(), 10.0, places=6)

    def test_daily_interest_reduced_by_il(self):
        # Позиция с накопленным IL
        p = _S2Position("curve-3pool", "lp", 10_000.0, 9.0,
                        current_apy=9.0, il_accumulated=1.0)
        # Без IL: 10000 * 9/100/365 ≈ 2.466
        # С IL (net_apy=9 - 1*365 → отрицательный → max(0, ...) = 0) → 0
        # но при il_accumulated=1% annual_il_rate = 1*365 = 365 >> 9, so net=max(0, 9-365)=0
        p_no_il = _S2Position("curve-3pool", "lp", 10_000.0, 9.0, current_apy=9.0)
        self.assertLessEqual(p.daily_interest(), p_no_il.daily_interest())

    def test_apply_il_small_deviation(self):
        p = _S2Position("curve-3pool", "lp", 10_000.0, 9.0)
        p.apply_il(0.1)  # 0.1% deviation
        # IL = (0.1/100)^2 / 2 * 100 = 0.00005 %
        self.assertGreater(p.il_accumulated, 0.0)
        self.assertLess(p.il_accumulated, 0.01)

    def test_apply_il_large_deviation(self):
        p = _S2Position("curve-3pool", "lp", 10_000.0, 9.0)
        p.apply_il(5.0)  # 5% peg deviation
        self.assertGreater(p.il_accumulated, 0.0)

    def test_il_starts_zero(self):
        p = _S2Position("curve-3pool", "lp", 10_000.0, 9.0)
        self.assertAlmostEqual(p.il_accumulated, 0.0)

    def test_days_held_starts_zero(self):
        p = _S2Position("curve-3pool", "lp", 10_000.0, 9.0)
        self.assertEqual(p.days_held, 0)

    def test_pool_type_stored(self):
        p = _S2Position("curve-3pool", "lp", 10_000.0, 9.0)
        self.assertEqual(p.pool_type, "lp")


# ─── LPStableStrategy Filter Tests ───────────────────────────────────────────

class TestLPStableStrategyFilters(unittest.TestCase):

    def setUp(self):
        self.s = LPStableStrategy()

    def test_is_lp_pool_true(self):
        self.assertTrue(self.s._is_lp_pool("curve-3pool-usdc"))

    def test_is_lp_pool_false(self):
        self.assertFalse(self.s._is_lp_pool("aave-v3-usdc"))

    def test_is_lending_base_true(self):
        self.assertTrue(self.s._is_lending_base("aave-v3-usdc"))

    def test_is_lending_base_false(self):
        self.assertFalse(self.s._is_lending_base("unknown-proto"))

    def test_effective_apy_lp_pool(self):
        p = _lp_protocol(key="curve-3pool-usdc", apy=9.0)
        eff = self.s._effective_apy(p)
        self.assertAlmostEqual(eff, 9.0)

    def test_effective_apy_lending_adds_premium(self):
        p = _lending_protocol(key="aave-v3-usdc", apy=4.5)
        eff = self.s._effective_apy(p)
        self.assertAlmostEqual(eff, 4.5 + FEE_APY_PREMIUM)

    def test_effective_apy_unknown_returns_zero(self):
        p = {"protocol_key": "unknown-xyz", "apy": 5.0, "tvl_usd": 1e8}
        eff = self.s._effective_apy(p)
        self.assertAlmostEqual(eff, 0.0)

    def test_is_allowed_lp_pool_valid(self):
        p = _lp_protocol(key="curve-3pool-usdc", apy=9.0, tvl=20_000_000)
        self.assertTrue(self.s._is_allowed(p))

    def test_is_allowed_lending_base_valid(self):
        # lending + FEE_APY_PREMIUM → effective APY in range
        p = _lending_protocol(key="aave-v3-usdc", apy=5.0, tvl=15_000_000)
        # effective = 5.0 + 4.5 = 9.5 → должен быть разрешён
        self.assertTrue(self.s._is_allowed(p))

    def test_is_allowed_tvl_too_low(self):
        p = _lp_protocol(key="curve-3pool-usdc", apy=9.0, tvl=1_000_000)
        self.assertFalse(self.s._is_allowed(p))

    def test_is_allowed_apy_too_low_after_fee(self):
        # lending с очень низким APY → effective ниже MIN_APY
        p = _lending_protocol(key="aave-v3-usdc", apy=0.1, tvl=15_000_000)
        # effective = 0.1 + 4.5 = 4.6 < MIN_APY=5.0 → false
        self.assertFalse(self.s._is_allowed(p))

    def test_is_allowed_apy_too_high(self):
        p = _lp_protocol(key="curve-3pool-usdc", apy=30.0, tvl=20_000_000)
        self.assertFalse(self.s._is_allowed(p))

    def test_is_allowed_unknown_protocol(self):
        p = {"protocol_key": "unknown-xyz", "apy": 9.0, "tvl_usd": 20_000_000}
        self.assertFalse(self.s._is_allowed(p))


# ─── LPStableStrategy.run_day Tests ──────────────────────────────────────────

class TestLPStableRunDay(unittest.TestCase):

    def setUp(self):
        self.s = LPStableStrategy()

    def test_run_day_returns_float(self):
        self.assertIsInstance(self.s.run_day(), float)

    def test_run_day_empty_returns_fallback(self):
        self.assertGreater(self.s.run_day({}), 0.0)

    def test_run_day_none_returns_fallback(self):
        self.assertGreater(self.s.run_day(None), 0.0)

    def test_run_day_lp_pool_used(self):
        apy_map = {"curve-3pool-usdc": 10.0}
        result = self.s.run_day(apy_map)
        self.assertAlmostEqual(result, 10.0)

    def test_run_day_lending_adds_premium(self):
        apy_map = {"aave-v3-usdc": 5.0}
        result = self.s.run_day(apy_map)
        self.assertAlmostEqual(result, 5.0 + FEE_APY_PREMIUM)

    def test_run_day_unknown_filtered(self):
        apy_map = {"unknown-xyz": 9.0}
        # Все отфильтрованы → fallback
        result = self.s.run_day(apy_map)
        self.assertGreater(result, 0.0)


# ─── LPStableStrategy.backtest Tests ─────────────────────────────────────────

class TestLPStableBacktest(unittest.TestCase):

    def setUp(self):
        self.s = LPStableStrategy()

    def test_backtest_empty_returns_empty(self):
        result = self.s.backtest([], initial_capital=100_000.0)
        self.assertEqual(result["strategy_id"], STRATEGY_ID)
        self.assertEqual(result["equity_curve"], [])
        self.assertEqual(result["trades"], [])

    def test_backtest_returns_required_keys(self):
        history = _make_history(5)
        result = self.s.backtest(history, initial_capital=100_000.0)
        self.assertIn("strategy_id", result)
        self.assertIn("equity_curve", result)
        self.assertIn("trades", result)
        self.assertIn("metrics", result)

    def test_backtest_strategy_id_correct(self):
        history = _make_history(5)
        result = self.s.backtest(history)
        self.assertEqual(result["strategy_id"], STRATEGY_ID)

    def test_backtest_equity_curve_length(self):
        n = 10
        history = _make_history(n_days=n)
        result = self.s.backtest(history, initial_capital=100_000.0)
        self.assertEqual(len(result["equity_curve"]), n)

    def test_backtest_equity_curve_fields(self):
        history = _make_history(5)
        result = self.s.backtest(history)
        for entry in result["equity_curve"]:
            self.assertIn("date", entry)
            self.assertIn("total_capital", entry)
            self.assertIn("avg_il_pct", entry)
            self.assertIn("strategy", entry)

    def test_backtest_disallowed_protocols_excluded(self):
        start = date(2026, 1, 1)
        history = [
            {"timestamp": str(start + timedelta(days=i)),
             "protocol_key": "unknown-proto", "apy": 9.0, "tvl_usd": 20_000_000}
            for i in range(10)
        ]
        result = self.s.backtest(history)
        open_trades = [t for t in result["trades"] if t["action"] == "OPEN"]
        self.assertEqual(len(open_trades), 0)

    def test_backtest_capital_grows_with_lp(self):
        history = _make_history(30, key="curve-3pool-usdc", apy=10.0)
        result = self.s.backtest(history, initial_capital=100_000.0)
        if result["equity_curve"]:
            final = result["equity_curve"][-1]["total_capital"]
            self.assertGreaterEqual(final, 100_000.0)

    def test_backtest_strategy_id(self):
        result = self.s.backtest([])
        self.assertEqual(result["strategy_id"], STRATEGY_ID)


if __name__ == "__main__":
    unittest.main()
