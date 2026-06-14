"""
tests/test_strategy_run_day.py — MP-437

Тесты для метода run_day() стратегий S0–S3.

Стратегии S0, S1, S2, S3 получили тонкий адаптер run_day(apy_map) для
совместимости с cycle_runner, не ломая существующий backtest().

Группы:
  TestS0Baseline              — 2 теста
  TestS1ConservativeLending   — 2 теста
  TestS2LPStable              — 2 теста
  TestS3YieldLoop             — 2 теста (+ 1 дополнительный граничный)

Итого: 9 тестов
"""
from __future__ import annotations

import sys
import os
import unittest

# Корень проекта в sys.path
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.strategies.baseline import BaselineStrategy
from spa_core.strategies.s1_conservative_lending import ConservativeLendingStrategy
from spa_core.strategies.s2_lp_stable import LPStableStrategy
from spa_core.strategies.s3_yield_loop import YieldLoopStrategy


# ──────────────────────────────────────────────────────────────────────────────
# S0 — Baseline (Equal Weight)
# ──────────────────────────────────────────────────────────────────────────────

class TestS0Baseline(unittest.TestCase):
    """run_day() для S0 BaselineStrategy."""

    def setUp(self) -> None:
        self.strategy = BaselineStrategy()

    def test_run_day_no_apy_map_returns_fallback(self) -> None:
        """run_day() без аргументов возвращает fallback float > 0."""
        result = self.strategy.run_day()
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0.0)

    def test_run_day_with_apy_map_returns_average(self) -> None:
        """run_day(apy_map) возвращает среднее по переданным APY."""
        apy_map = {
            "aave_v3": 3.5,
            "compound_v3": 4.8,
            "morpho": 6.5,
        }
        result = self.strategy.run_day(apy_map)
        self.assertIsInstance(result, float)
        # Среднее 3.5+4.8+6.5 = 14.8 / 3 ≈ 4.933
        self.assertAlmostEqual(result, (3.5 + 4.8 + 6.5) / 3, places=6)


# ──────────────────────────────────────────────────────────────────────────────
# S1 — Conservative Lending
# ──────────────────────────────────────────────────────────────────────────────

class TestS1ConservativeLending(unittest.TestCase):
    """run_day() для S1 ConservativeLendingStrategy."""

    def setUp(self) -> None:
        self.strategy = ConservativeLendingStrategy()

    def test_run_day_no_apy_map_returns_fallback(self) -> None:
        """run_day() без аргументов возвращает fallback 5.0%."""
        result = self.strategy.run_day()
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 5.0, places=6)

    def test_run_day_with_apy_map_returns_allowed_average(self) -> None:
        """run_day(apy_map) использует только разрешённые T1-протоколы."""
        apy_map = {
            "aave-v3": 5.0,          # разрешён
            "compound-v3": 4.5,      # разрешён
            "unknown-protocol": 99.0, # НЕ разрешён — должен игнорироваться
        }
        result = self.strategy.run_day(apy_map)
        self.assertIsInstance(result, float)
        # Ожидаем среднее только по aave-v3 и compound-v3 → (5.0 + 4.5) / 2 = 4.75
        self.assertAlmostEqual(result, (5.0 + 4.5) / 2, places=6)


# ──────────────────────────────────────────────────────────────────────────────
# S2 — LP Stablecoin Pairs
# ──────────────────────────────────────────────────────────────────────────────

class TestS2LPStable(unittest.TestCase):
    """run_day() для S2 LPStableStrategy."""

    def setUp(self) -> None:
        self.strategy = LPStableStrategy()

    def test_run_day_no_apy_map_returns_fallback(self) -> None:
        """run_day() без аргументов возвращает fallback 10.0%."""
        result = self.strategy.run_day()
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 10.0, places=6)

    def test_run_day_with_apy_map_applies_fee_premium(self) -> None:
        """run_day(apy_map) прибавляет FEE_APY_PREMIUM к lending-пулам."""
        # aave-v3 — lending fallback → эффективный APY = 4.0 + 4.5 = 8.5%
        # curve-usdc — LP пул → эффективный APY = 9.5%
        # Среднее = (8.5 + 9.5) / 2 = 9.0%
        apy_map = {
            "aave-v3": 4.0,
            "curve-usdc": 9.5,
        }
        result = self.strategy.run_day(apy_map)
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0.0)
        # Оба попадают в MIN_APY(5)..MAX_APY(25) → среднее ~9.0
        self.assertAlmostEqual(result, (8.5 + 9.5) / 2, places=6)


# ──────────────────────────────────────────────────────────────────────────────
# S3 — Yield Loop
# ──────────────────────────────────────────────────────────────────────────────

class TestS3YieldLoop(unittest.TestCase):
    """run_day() для S3 YieldLoopStrategy."""

    def setUp(self) -> None:
        self.strategy = YieldLoopStrategy()

    def test_run_day_no_apy_map_returns_fallback(self) -> None:
        """run_day() без аргументов возвращает fallback 18.0%."""
        result = self.strategy.run_day()
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 18.0, places=6)

    def test_run_day_with_apy_map_uses_aave_deposit_key(self) -> None:
        """run_day(apy_map) находит aave-v3-usdc-ethereum и вычисляет loop APY."""
        apy_map = {"aave-v3-usdc-ethereum": 4.6}
        result = self.strategy.run_day(apy_map)
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0.0)
        # deposit_apy=4.6, borrow_rate=min(4.6*0.8+0.5, 4.6+2.0)=4.18
        # net_apy = 4.6 + 0.60*(4.6-4.18) ≈ 4.852
        self.assertAlmostEqual(result, 4.852, places=2)

    def test_run_day_empty_apy_map_uses_fallback(self) -> None:
        """run_day({}) с пустым словарём возвращает fallback 18.0%."""
        result = self.strategy.run_day({})
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 18.0, places=6)


# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
