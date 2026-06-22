"""
spa_core/tests/test_s1_t1t2_balanced.py

Tests for S1T1T2BalancedStrategy (spa_core/strategies/s1_t1t2_balanced.py).

MP-1459 (v10.75) — Sprint 1 coverage expansion.

Run:
    python3 -m unittest spa_core.tests.test_s1_t1t2_balanced -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.s1_t1t2_balanced import (
    S1T1T2BalancedStrategy,
    TARGET_WEIGHTS,
    DEFAULT_APY,
    STRATEGY_ID,
    STRATEGY_RISK_LEVEL,
    KILL_DRAWDOWN_PCT,
    TARGET_APY_MIN,
    TARGET_APY_MAX,
)


class TestS1T1T2Constants(unittest.TestCase):
    """Проверка констант модуля."""

    def test_target_weights_sum_to_one(self):
        total = sum(TARGET_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=10)

    def test_target_weights_keys(self):
        expected = {"aave_v3", "morpho_blue", "compound_v3"}
        self.assertEqual(set(TARGET_WEIGHTS.keys()), expected)

    def test_default_apy_keys_match_weights(self):
        self.assertEqual(set(DEFAULT_APY.keys()), set(TARGET_WEIGHTS.keys()))

    def test_strategy_id(self):
        self.assertEqual(STRATEGY_ID, "s1_t1t2_balanced")

    def test_kill_drawdown_pct(self):
        self.assertAlmostEqual(KILL_DRAWDOWN_PCT, 0.05)

    def test_target_apy_range(self):
        self.assertLess(TARGET_APY_MIN, TARGET_APY_MAX)


class TestS1T1T2Init(unittest.TestCase):
    """Проверка инициализации стратегии."""

    def test_default_capital(self):
        s = S1T1T2BalancedStrategy()
        self.assertAlmostEqual(s.capital, 100_000.0)

    def test_custom_capital(self):
        s = S1T1T2BalancedStrategy(capital=50_000.0)
        self.assertAlmostEqual(s.capital, 50_000.0)

    def test_positions_initialized(self):
        s = S1T1T2BalancedStrategy(capital=100_000.0)
        for k in TARGET_WEIGHTS:
            self.assertIn(k, s._positions)

    def test_positions_sum_to_capital(self):
        s = S1T1T2BalancedStrategy(capital=100_000.0)
        total = sum(s._positions.values())
        self.assertAlmostEqual(total, 100_000.0, places=5)

    def test_positions_proportional_to_weights(self):
        s = S1T1T2BalancedStrategy(capital=100_000.0)
        for protocol, weight in TARGET_WEIGHTS.items():
            expected = 100_000.0 * weight
            self.assertAlmostEqual(s._positions[protocol], expected, places=5)

    def test_days_simulated_zero(self):
        s = S1T1T2BalancedStrategy()
        self.assertEqual(s._days_simulated, 0)

    def test_total_yield_zero(self):
        s = S1T1T2BalancedStrategy()
        self.assertAlmostEqual(s._total_yield_usd, 0.0)

    def test_equity_history_empty(self):
        s = S1T1T2BalancedStrategy()
        self.assertEqual(len(s._equity_history), 0)

    def test_strategy_id_attribute(self):
        s = S1T1T2BalancedStrategy()
        self.assertEqual(s.strategy_id, STRATEGY_ID)

    def test_risk_level_attribute(self):
        s = S1T1T2BalancedStrategy()
        self.assertEqual(s.risk_level, STRATEGY_RISK_LEVEL)


class TestS1T1T2SimulateDay(unittest.TestCase):
    """Проверка метода simulate_day."""

    def test_simulate_day_returns_dict(self):
        s = S1T1T2BalancedStrategy()
        result = s.simulate_day({})
        self.assertIsInstance(result, dict)

    def test_simulate_day_keys(self):
        s = S1T1T2BalancedStrategy()
        result = s.simulate_day({})
        self.assertIn("daily_yield_usd", result)
        self.assertIn("positions", result)
        self.assertIn("weighted_apy", result)

    def test_simulate_day_increments_counter(self):
        s = S1T1T2BalancedStrategy()
        s.simulate_day({})
        self.assertEqual(s._days_simulated, 1)
        s.simulate_day({})
        self.assertEqual(s._days_simulated, 2)

    def test_simulate_day_positive_yield_with_defaults(self):
        s = S1T1T2BalancedStrategy(capital=100_000.0)
        result = s.simulate_day({})
        self.assertGreater(result["daily_yield_usd"], 0.0)

    def test_simulate_day_yield_accumulates(self):
        s = S1T1T2BalancedStrategy(capital=100_000.0)
        r1 = s.simulate_day({})
        r2 = s.simulate_day({})
        # второй день должен иметь слегка больший yield (позиции выросли)
        self.assertGreater(r2["daily_yield_usd"], 0.0)
        self.assertAlmostEqual(
            s._total_yield_usd, r1["daily_yield_usd"] + r2["daily_yield_usd"], places=8
        )

    def test_simulate_day_positions_grow(self):
        s = S1T1T2BalancedStrategy(capital=100_000.0)
        initial_equity = s.current_equity
        s.simulate_day({})
        self.assertGreater(s.current_equity, initial_equity)

    def test_simulate_day_uses_apy_map(self):
        s1 = S1T1T2BalancedStrategy(capital=100_000.0)
        s2 = S1T1T2BalancedStrategy(capital=100_000.0)
        # Высокий APY → больше yield
        high_apy_map = {"aave_v3": 20.0, "morpho_blue": 20.0, "compound_v3": 20.0}
        low_apy_map  = {"aave_v3": 1.0, "morpho_blue": 1.0, "compound_v3": 1.0}
        r_high = s1.simulate_day(high_apy_map)
        r_low  = s2.simulate_day(low_apy_map)
        self.assertGreater(r_high["daily_yield_usd"], r_low["daily_yield_usd"])

    def test_simulate_day_zero_apy_skipped(self):
        s = S1T1T2BalancedStrategy(capital=100_000.0)
        # apy_map с нулевым APY → все пропускаются → yield = 0
        result = s.simulate_day({"aave_v3": 0.0, "morpho_blue": 0.0, "compound_v3": 0.0})
        self.assertAlmostEqual(result["daily_yield_usd"], 0.0, places=10)

    def test_simulate_day_equity_history_grows(self):
        s = S1T1T2BalancedStrategy()
        for _ in range(5):
            s.simulate_day({})
        self.assertEqual(len(s._equity_history), 5)

    def test_simulate_day_equity_history_ringbuffer(self):
        from spa_core.strategies.s1_t1t2_balanced import _EQUITY_HISTORY_MAX
        s = S1T1T2BalancedStrategy()
        for _ in range(_EQUITY_HISTORY_MAX + 10):
            s.simulate_day({})
        self.assertLessEqual(len(s._equity_history), _EQUITY_HISTORY_MAX)


class TestS1T1T2WeightedApy(unittest.TestCase):
    """Проверка compute_weighted_apy."""

    def test_default_apy_produces_expected_weighted(self):
        s = S1T1T2BalancedStrategy()
        # 0.40*4.2 + 0.40*6.5 + 0.20*4.8 = 1.68 + 2.60 + 0.96 = 5.24
        expected = 0.40 * 4.2 + 0.40 * 6.5 + 0.20 * 4.8
        self.assertAlmostEqual(s.compute_weighted_apy({}), expected, places=5)

    def test_custom_apy_map_used(self):
        s = S1T1T2BalancedStrategy()
        apy_map = {"aave_v3": 5.0, "morpho_blue": 8.0, "compound_v3": 6.0}
        expected = 0.40 * 5.0 + 0.40 * 8.0 + 0.20 * 6.0
        self.assertAlmostEqual(s.compute_weighted_apy(apy_map), expected, places=5)

    def test_partial_apy_map_uses_defaults(self):
        s = S1T1T2BalancedStrategy()
        apy_map = {"aave_v3": 10.0}  # остальные — из DEFAULT_APY
        expected = (
            0.40 * 10.0
            + 0.40 * DEFAULT_APY["morpho_blue"]
            + 0.20 * DEFAULT_APY["compound_v3"]
        )
        self.assertAlmostEqual(s.compute_weighted_apy(apy_map), expected, places=5)


class TestS1T1T2CurrentEquity(unittest.TestCase):
    """Проверка current_equity."""

    def test_initial_equity_equals_capital(self):
        s = S1T1T2BalancedStrategy(capital=100_000.0)
        self.assertAlmostEqual(s.current_equity, 100_000.0, places=5)

    def test_equity_grows_after_simulate(self):
        s = S1T1T2BalancedStrategy(capital=100_000.0)
        s.simulate_day({})
        self.assertGreater(s.current_equity, 100_000.0)


class TestS1T1T2VPortfolioFormat(unittest.TestCase):
    """Проверка to_vportfolio_format."""

    def test_returns_dict(self):
        s = S1T1T2BalancedStrategy()
        result = s.to_vportfolio_format()
        self.assertIsInstance(result, dict)

    def test_required_keys(self):
        s = S1T1T2BalancedStrategy()
        result = s.to_vportfolio_format()
        required = {
            "strategy_id", "capital_usd", "positions", "cash_usd",
            "equity_history", "daily_returns", "created_at", "last_updated",
            "total_yield_usd", "days_simulated", "peak_equity", "status",
            "current_equity", "drawdown_pct", "total_return_pct",
        }
        for key in required:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_strategy_id_matches(self):
        s = S1T1T2BalancedStrategy()
        result = s.to_vportfolio_format()
        self.assertEqual(result["strategy_id"], STRATEGY_ID)

    def test_status_active(self):
        s = S1T1T2BalancedStrategy()
        result = s.to_vportfolio_format()
        self.assertEqual(result["status"], "active")

    def test_total_return_pct_initial_zero(self):
        s = S1T1T2BalancedStrategy(capital=100_000.0)
        result = s.to_vportfolio_format()
        self.assertAlmostEqual(result["total_return_pct"], 0.0, places=5)

    def test_total_return_pct_positive_after_simulate(self):
        s = S1T1T2BalancedStrategy(capital=100_000.0)
        for _ in range(30):
            s.simulate_day({})
        result = s.to_vportfolio_format()
        self.assertGreater(result["total_return_pct"], 0.0)

    def test_capital_usd_matches(self):
        s = S1T1T2BalancedStrategy(capital=50_000.0)
        result = s.to_vportfolio_format()
        self.assertAlmostEqual(result["capital_usd"], 50_000.0)


if __name__ == "__main__":
    unittest.main()
