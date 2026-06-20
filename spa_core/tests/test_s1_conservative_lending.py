"""
spa_core/tests/test_s1_conservative_lending.py

Tests for _S1Position and ConservativeLendingStrategy
(spa_core/strategies/s1_conservative_lending.py).

MP-1459 (v10.75) — Sprint 1 coverage expansion.

Run:
    python3 -m unittest spa_core.tests.test_s1_conservative_lending -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.s1_conservative_lending import (
    _S1Position,
    ConservativeLendingStrategy,
    STRATEGY_ID,
    ALLOWED_PROTOCOL_PREFIXES,
    MAX_CONCENTRATION,
    MIN_APY,
    MAX_APY,
    MIN_TVL_USD,
    CASH_BUFFER,
    REBALANCE_THRESHOLD,
    MAX_POSITIONS,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _protocol(key="aave-v3-usdc", apy=5.0, tvl=10_000_000, tier="T1") -> dict:
    return {"protocol_key": key, "apy": apy, "tvl_usd": tvl, "tier": tier}


def _hist_row(timestamp="2026-01-01", protocol_key="aave-v3-usdc", apy=5.0, tvl=10_000_000) -> dict:
    return {
        "timestamp": timestamp,
        "protocol_key": protocol_key,
        "apy": apy,
        "tvl_usd": tvl,
        "tier": "T1",
    }


def _make_history(n_days=30, protocol_key="aave-v3-usdc", apy=5.0) -> list[dict]:
    from datetime import date, timedelta
    start = date(2026, 1, 1)
    return [
        _hist_row(
            timestamp=str(start + timedelta(days=i)),
            protocol_key=protocol_key,
            apy=apy,
        )
        for i in range(n_days)
    ]


# ─── _S1Position Tests ────────────────────────────────────────────────────────

class TestS1Position(unittest.TestCase):

    def test_daily_interest_positive(self):
        p = _S1Position("aave-v3", 10_000.0, 5.0, current_apy=5.0)
        interest = p.daily_interest()
        self.assertGreater(interest, 0.0)

    def test_daily_interest_formula(self):
        p = _S1Position("aave-v3", 36500.0, 5.0, current_apy=10.0)
        # 36500 * 10 / 100 / 365 = 10.0
        self.assertAlmostEqual(p.daily_interest(), 10.0, places=6)

    def test_daily_interest_zero_apy(self):
        p = _S1Position("aave-v3", 10_000.0, 0.0, current_apy=0.0)
        self.assertAlmostEqual(p.daily_interest(), 0.0)

    def test_effective_weight_basic(self):
        p = _S1Position("aave-v3", 40_000.0, 5.0)
        w = p.effective_weight(100_000.0)
        self.assertAlmostEqual(w, 0.40)

    def test_effective_weight_zero_capital(self):
        p = _S1Position("aave-v3", 10_000.0, 5.0)
        w = p.effective_weight(0.0)
        self.assertAlmostEqual(w, 0.0)

    def test_interest_earned_starts_zero(self):
        p = _S1Position("aave-v3", 10_000.0, 5.0)
        self.assertAlmostEqual(p.interest_earned, 0.0)


# ─── ConservativeLendingStrategy._is_allowed Tests ───────────────────────────

class TestConservativeLendingAllowedFilter(unittest.TestCase):

    def setUp(self):
        self.s = ConservativeLendingStrategy()

    def test_allowed_aave_v3(self):
        p = _protocol(key="aave-v3-usdc", apy=5.0, tvl=10_000_000)
        self.assertTrue(self.s._is_allowed(p))

    def test_allowed_compound_v3(self):
        p = _protocol(key="compound-v3-usdc", apy=5.0, tvl=10_000_000)
        self.assertTrue(self.s._is_allowed(p))

    def test_allowed_morpho(self):
        p = _protocol(key="morpho-steakhouse", apy=6.0, tvl=10_000_000)
        self.assertTrue(self.s._is_allowed(p))

    def test_blocked_unknown_protocol(self):
        p = _protocol(key="unknown-protocol", apy=5.0, tvl=10_000_000)
        self.assertFalse(self.s._is_allowed(p))

    def test_blocked_apy_too_low(self):
        p = _protocol(key="aave-v3-usdc", apy=0.5, tvl=10_000_000)
        self.assertFalse(self.s._is_allowed(p))

    def test_blocked_apy_too_high(self):
        p = _protocol(key="aave-v3-usdc", apy=15.0, tvl=10_000_000)
        self.assertFalse(self.s._is_allowed(p))

    def test_blocked_tvl_too_low(self):
        p = _protocol(key="aave-v3-usdc", apy=5.0, tvl=1_000_000)
        self.assertFalse(self.s._is_allowed(p))

    def test_min_apy_boundary_allowed(self):
        p = _protocol(key="aave-v3-usdc", apy=MIN_APY, tvl=MIN_TVL_USD)
        self.assertTrue(self.s._is_allowed(p))

    def test_max_apy_boundary_allowed(self):
        p = _protocol(key="aave-v3-usdc", apy=MAX_APY, tvl=MIN_TVL_USD)
        self.assertTrue(self.s._is_allowed(p))

    def test_min_tvl_boundary_allowed(self):
        p = _protocol(key="aave-v3-usdc", apy=5.0, tvl=MIN_TVL_USD)
        self.assertTrue(self.s._is_allowed(p))


# ─── ConservativeLendingStrategy.run_day Tests ───────────────────────────────

class TestConservativeLendingRunDay(unittest.TestCase):

    def setUp(self):
        self.s = ConservativeLendingStrategy()

    def test_run_day_returns_float(self):
        result = self.s.run_day()
        self.assertIsInstance(result, float)

    def test_run_day_empty_map_returns_fallback(self):
        result = self.s.run_day({})
        self.assertGreater(result, 0.0)

    def test_run_day_none_returns_fallback(self):
        result = self.s.run_day(None)
        self.assertGreater(result, 0.0)

    def test_run_day_with_allowed_protocols(self):
        apy_map = {
            "aave-v3-usdc": 5.5,
            "compound-v3-usdc": 4.8,
        }
        result = self.s.run_day(apy_map)
        self.assertAlmostEqual(result, (5.5 + 4.8) / 2.0, places=5)

    def test_run_day_filters_disallowed_protocols(self):
        apy_map = {
            "unknown-protocol": 5.5,
        }
        # Disallowed protocols excluded → fallback
        result = self.s.run_day(apy_map)
        self.assertGreater(result, 0.0)

    def test_run_day_filters_apy_out_of_range(self):
        apy_map = {
            "aave-v3-usdc": 0.1,   # below MIN_APY
            "compound-v3-usdc": 50.0,  # above MAX_APY
        }
        # All filtered → fallback
        result = self.s.run_day(apy_map)
        self.assertGreater(result, 0.0)


# ─── ConservativeLendingStrategy.backtest Tests ───────────────────────────────

class TestConservativeLendingBacktest(unittest.TestCase):

    def setUp(self):
        self.s = ConservativeLendingStrategy()

    def test_backtest_empty_data_returns_empty_result(self):
        result = self.s.backtest([], initial_capital=100_000.0)
        self.assertEqual(result["strategy_id"], STRATEGY_ID)
        self.assertEqual(result["equity_curve"], [])
        self.assertEqual(result["trades"], [])

    def test_backtest_returns_required_keys(self):
        history = _make_history(n_days=5)
        result = self.s.backtest(history, initial_capital=100_000.0)
        self.assertIn("strategy_id", result)
        self.assertIn("equity_curve", result)
        self.assertIn("trades", result)
        self.assertIn("metrics", result)

    def test_backtest_strategy_id_correct(self):
        history = _make_history(n_days=5)
        result = self.s.backtest(history)
        self.assertEqual(result["strategy_id"], STRATEGY_ID)

    def test_backtest_equity_curve_length(self):
        n = 10
        history = _make_history(n_days=n)
        result = self.s.backtest(history, initial_capital=100_000.0)
        self.assertEqual(len(result["equity_curve"]), n)

    def test_backtest_capital_grows(self):
        history = _make_history(n_days=30, apy=5.0)
        result = self.s.backtest(history, initial_capital=100_000.0)
        final = result["equity_curve"][-1]["total_capital"]
        self.assertGreater(final, 100_000.0)

    def test_backtest_metrics_present(self):
        history = _make_history(n_days=30)
        result = self.s.backtest(history)
        m = result["metrics"]
        self.assertIn("strategy_id", m)
        self.assertIn("initial_capital_usd", m)
        self.assertIn("final_capital_usd", m)

    def test_backtest_multiple_protocols(self):
        from datetime import date, timedelta
        start = date(2026, 1, 1)
        history = []
        for i in range(30):
            d = str(start + timedelta(days=i))
            history.append(_hist_row(d, "aave-v3-usdc",     apy=4.5, tvl=50_000_000))
            history.append(_hist_row(d, "compound-v3-usdc", apy=5.0, tvl=30_000_000))
        result = self.s.backtest(history, initial_capital=100_000.0)
        self.assertEqual(len(result["equity_curve"]), 30)

    def test_backtest_disallowed_protocols_excluded(self):
        from datetime import date, timedelta
        start = date(2026, 1, 1)
        history = [
            _hist_row(str(start + timedelta(days=i)), "unknown-proto", apy=8.0)
            for i in range(10)
        ]
        result = self.s.backtest(history, initial_capital=100_000.0)
        # Нет разрешённых протоколов — позиции не открываются, trades пустые
        open_trades = [t for t in result["trades"] if t["action"] == "OPEN"]
        self.assertEqual(len(open_trades), 0)

    def test_backtest_equity_curve_date_field(self):
        history = _make_history(n_days=5)
        result = self.s.backtest(history)
        for entry in result["equity_curve"]:
            self.assertIn("date", entry)
            self.assertIn("total_capital", entry)
            self.assertIn("strategy", entry)


if __name__ == "__main__":
    unittest.main()
