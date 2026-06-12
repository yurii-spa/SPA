"""
spa_core/tests/test_s3_aave_arb_morpho.py — MP-381

75+ unittest-кейсов для S3AaveArbMorpho:

Классы:
  TestS3Init           (8)  — id, name, tier, allocation, gas_savings constant
  TestS3WeightedAPY    (12) — с map, fallback, partial, все комбинации
  TestS3SimulateDay    (12) — dict returned, positive yield, balance grows
  TestS3VPortfolioFormat (10) — все ключи присутствуют
  TestS3GasSavings     (10) — 0 txs=0, 10 txs=0.90, negative input handling
  TestS3RiskFlags       (8) — l2_bridge_risk + multi_chain_complexity
  TestS3Constants      (10) — значения аллокаций, APY
  TestS3EdgeCases       (5) — zero capital, empty map

Правила:
  - stdlib only
  - Все тесты изолированы (отдельные инстансы)
  - Комментарии на русском
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

# ─── sys.path ─────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

# ─── Импорты тестируемого модуля ──────────────────────────────────────────────
from spa_core.strategies.s3_aave_arb_morpho import (
    S3AaveArbMorpho,
    STRATEGY_ID,
    STRATEGY_NAME,
    TIER,
    ALLOCATION,
    FALLBACK_APY,
    WEIGHTED_APY_EXPECTED,
    GAS_SAVINGS_PER_TX_USD,
    RISK_FLAGS,
    TARGET_APY_MIN,
    TARGET_APY_MAX,
    KILL_DRAWDOWN_PCT,
)

# ─── Вспомогательные APY-карты ────────────────────────────────────────────────

APY_DEFAULT = {
    "aave_arbitrum":    4.1,
    "morpho_steakhouse": 6.5,
    "aave_mainnet":     3.2,
}
APY_HIGH = {
    "aave_arbitrum":    10.0,
    "morpho_steakhouse": 12.0,
    "aave_mainnet":     9.0,
}
APY_ZERO = {
    "aave_arbitrum":    0.0,
    "morpho_steakhouse": 0.0,
    "aave_mainnet":     0.0,
}


# ═══════════════════════════════════════════════════════════════════════════════
# TestS3Init — 8 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestS3Init(unittest.TestCase):
    """Тесты инициализации S3AaveArbMorpho."""

    def setUp(self):
        self.s3 = S3AaveArbMorpho()

    def test_strategy_id_correct(self):
        """strategy_id должен равняться 'S3'."""
        self.assertEqual(self.s3.strategy_id, "S3")

    def test_strategy_name_correct(self):
        """strategy_name должен совпадать с STRATEGY_NAME."""
        self.assertEqual(self.s3.strategy_name, STRATEGY_NAME)

    def test_tier_is_t1(self):
        """tier должен быть 'T1'."""
        self.assertEqual(self.s3.tier, "T1")

    def test_default_capital(self):
        """Дефолтный капитал — $100,000."""
        self.assertEqual(self.s3.capital, 100_000.0)

    def test_custom_capital(self):
        """Можно передать произвольный капитал."""
        s3 = S3AaveArbMorpho(capital=50_000.0)
        self.assertEqual(s3.capital, 50_000.0)

    def test_positions_initialized(self):
        """Позиции должны быть инициализированы по ALLOCATION."""
        self.assertIn("aave_arbitrum", self.s3._positions)
        self.assertIn("morpho_steakhouse", self.s3._positions)
        self.assertIn("aave_mainnet", self.s3._positions)

    def test_position_sum_equals_capital(self):
        """Сумма позиций должна равняться начальному капиталу."""
        total = sum(self.s3._positions.values())
        self.assertAlmostEqual(total, 100_000.0, places=6)

    def test_gas_savings_constant_accessible(self):
        """Константа GAS_SAVINGS_PER_TX_USD должна быть доступна."""
        self.assertEqual(GAS_SAVINGS_PER_TX_USD, 0.09)


# ═══════════════════════════════════════════════════════════════════════════════
# TestS3WeightedAPY — 12 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestS3WeightedAPY(unittest.TestCase):
    """Тесты compute_weighted_apy."""

    def setUp(self):
        self.s3 = S3AaveArbMorpho()

    def test_weighted_apy_default_values(self):
        """При дефолтных APY результат ≈ 4.685%."""
        result = self.s3.compute_weighted_apy(APY_DEFAULT)
        self.assertAlmostEqual(result, 4.685, places=3)

    def test_weighted_apy_empty_map_uses_fallback(self):
        """При пустом apy_map используются FALLBACK_APY."""
        result = self.s3.compute_weighted_apy({})
        # 0.55*4.1 + 0.30*6.5 + 0.15*3.2 = 4.685
        self.assertAlmostEqual(result, 4.685, places=3)

    def test_weighted_apy_high_values(self):
        """При высоких APY результат вычисляется корректно."""
        result = self.s3.compute_weighted_apy(APY_HIGH)
        expected = 0.55 * 10.0 + 0.30 * 12.0 + 0.15 * 9.0
        self.assertAlmostEqual(result, expected, places=6)

    def test_weighted_apy_formula_aave_arbitrum(self):
        """Вес aave_arbitrum = 0.55 применяется корректно.

        Ключи morpho_steakhouse и aave_mainnet отсутствуют в карте →
        используются FALLBACK_APY для них.
        """
        # Только aave_arbitrum в карте; остальные — отсутствуют → fallback
        apy_map = {"aave_arbitrum": 10.0}
        result = self.s3.compute_weighted_apy(apy_map)
        expected = (
            0.55 * 10.0
            + 0.30 * FALLBACK_APY["morpho_steakhouse"]
            + 0.15 * FALLBACK_APY["aave_mainnet"]
        )
        self.assertAlmostEqual(result, expected, places=6)

    def test_weighted_apy_partial_map_arbitrum_only(self):
        """Частичная карта — только aave_arbitrum; остальные из FALLBACK_APY."""
        result = self.s3.compute_weighted_apy({"aave_arbitrum": 5.0})
        expected = 0.55 * 5.0 + 0.30 * FALLBACK_APY["morpho_steakhouse"] + 0.15 * FALLBACK_APY["aave_mainnet"]
        self.assertAlmostEqual(result, expected, places=6)

    def test_weighted_apy_partial_map_morpho_only(self):
        """Частичная карта — только morpho_steakhouse; остальные из FALLBACK_APY."""
        result = self.s3.compute_weighted_apy({"morpho_steakhouse": 8.0})
        expected = 0.55 * FALLBACK_APY["aave_arbitrum"] + 0.30 * 8.0 + 0.15 * FALLBACK_APY["aave_mainnet"]
        self.assertAlmostEqual(result, expected, places=6)

    def test_weighted_apy_partial_map_mainnet_only(self):
        """Частичная карта — только aave_mainnet; остальные из FALLBACK_APY."""
        result = self.s3.compute_weighted_apy({"aave_mainnet": 5.0})
        expected = 0.55 * FALLBACK_APY["aave_arbitrum"] + 0.30 * FALLBACK_APY["morpho_steakhouse"] + 0.15 * 5.0
        self.assertAlmostEqual(result, expected, places=6)

    def test_weighted_apy_positive_result(self):
        """Weighted APY всегда > 0 при разумных входных данных."""
        result = self.s3.compute_weighted_apy(APY_DEFAULT)
        self.assertGreater(result, 0.0)

    def test_weighted_apy_returns_float(self):
        """Возвращаемое значение — float."""
        result = self.s3.compute_weighted_apy(APY_DEFAULT)
        self.assertIsInstance(result, float)

    def test_weighted_apy_all_zeros_from_map(self):
        """При APY = 0 для всех в карте используются FALLBACK_APY (ключи есть)."""
        # FALLBACK_APY применяется только если ключ отсутствует
        # Если ключ есть и равен 0 — считаем 0
        result = self.s3.compute_weighted_apy(APY_ZERO)
        # 0.55*0 + 0.30*0 + 0.15*0 = 0
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_weighted_apy_matches_expected_constant(self):
        """Дефолтный weighted_apy ≈ WEIGHTED_APY_EXPECTED (4.7%)."""
        result = self.s3.compute_weighted_apy(APY_DEFAULT)
        self.assertAlmostEqual(result, WEIGHTED_APY_EXPECTED, delta=0.1)

    def test_weighted_apy_unknown_keys_ignored(self):
        """Посторонние ключи в apy_map не влияют на расчёт."""
        apy_map = dict(APY_DEFAULT)
        apy_map["unknown_protocol"] = 999.0
        result = self.s3.compute_weighted_apy(apy_map)
        expected = self.s3.compute_weighted_apy(APY_DEFAULT)
        self.assertAlmostEqual(result, expected, places=6)


# ═══════════════════════════════════════════════════════════════════════════════
# TestS3SimulateDay — 12 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestS3SimulateDay(unittest.TestCase):
    """Тесты simulate_day."""

    def setUp(self):
        self.s3 = S3AaveArbMorpho()

    def test_simulate_day_returns_dict(self):
        """simulate_day должен возвращать dict."""
        result = self.s3.simulate_day(APY_DEFAULT)
        self.assertIsInstance(result, dict)

    def test_simulate_day_keys_present(self):
        """Возвращаемый dict содержит нужные ключи."""
        result = self.s3.simulate_day(APY_DEFAULT)
        self.assertIn("daily_yield_usd", result)
        self.assertIn("positions", result)
        self.assertIn("weighted_apy", result)

    def test_simulate_day_positive_yield(self):
        """Daily yield должен быть > 0 при положительных APY."""
        result = self.s3.simulate_day(APY_DEFAULT)
        self.assertGreater(result["daily_yield_usd"], 0.0)

    def test_simulate_day_equity_grows(self):
        """Equity должна расти после simulate_day."""
        equity_before = self.s3.current_equity
        self.s3.simulate_day(APY_DEFAULT)
        self.assertGreater(self.s3.current_equity, equity_before)

    def test_simulate_day_counter_increments(self):
        """days_simulated должен увеличиваться после каждого дня."""
        self.s3.simulate_day(APY_DEFAULT)
        self.assertEqual(self.s3._days_simulated, 1)
        self.s3.simulate_day(APY_DEFAULT)
        self.assertEqual(self.s3._days_simulated, 2)

    def test_simulate_day_empty_map_uses_fallback(self):
        """При пустом apy_map используется FALLBACK_APY (yield > 0)."""
        result = self.s3.simulate_day({})
        self.assertGreater(result["daily_yield_usd"], 0.0)

    def test_simulate_day_zero_apy_no_yield(self):
        """При всех APY = 0 yield должен быть 0."""
        result = self.s3.simulate_day(APY_ZERO)
        self.assertAlmostEqual(result["daily_yield_usd"], 0.0, places=10)

    def test_simulate_day_positions_dict_returned(self):
        """positions в результате — dict с тремя протоколами."""
        result = self.s3.simulate_day(APY_DEFAULT)
        self.assertIn("aave_arbitrum", result["positions"])
        self.assertIn("morpho_steakhouse", result["positions"])
        self.assertIn("aave_mainnet", result["positions"])

    def test_simulate_day_high_apy_yields_more(self):
        """Более высокие APY дают больший yield."""
        s3_default = S3AaveArbMorpho()
        s3_high    = S3AaveArbMorpho()
        r_default  = s3_default.simulate_day(APY_DEFAULT)
        r_high     = s3_high.simulate_day(APY_HIGH)
        self.assertGreater(r_high["daily_yield_usd"], r_default["daily_yield_usd"])

    def test_simulate_day_total_yield_accumulates(self):
        """_total_yield_usd накапливается после нескольких дней."""
        for _ in range(5):
            self.s3.simulate_day(APY_DEFAULT)
        self.assertGreater(self.s3._total_yield_usd, 0.0)

    def test_simulate_day_equity_history_grows(self):
        """_equity_history пополняется после каждого дня."""
        self.s3.simulate_day(APY_DEFAULT)
        self.assertEqual(len(self.s3._equity_history), 1)
        self.s3.simulate_day(APY_DEFAULT)
        self.assertEqual(len(self.s3._equity_history), 2)

    def test_simulate_day_equity_history_ring_buffer(self):
        """Ring-buffer истории не превышает 365 точек."""
        for _ in range(370):
            self.s3.simulate_day(APY_DEFAULT)
        self.assertLessEqual(len(self.s3._equity_history), 365)


# ═══════════════════════════════════════════════════════════════════════════════
# TestS3VPortfolioFormat — 10 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestS3VPortfolioFormat(unittest.TestCase):
    """Тесты to_vportfolio_format."""

    def setUp(self):
        self.s3 = S3AaveArbMorpho()
        self.vp = self.s3.to_vportfolio_format()

    def test_vportfolio_strategy_id(self):
        """strategy_id совпадает с STRATEGY_ID."""
        self.assertEqual(self.vp["strategy_id"], STRATEGY_ID)

    def test_vportfolio_strategy_name(self):
        """strategy_name совпадает с STRATEGY_NAME."""
        self.assertEqual(self.vp["strategy_name"], STRATEGY_NAME)

    def test_vportfolio_capital_usd(self):
        """capital_usd равен начальному капиталу."""
        self.assertEqual(self.vp["capital_usd"], 100_000.0)

    def test_vportfolio_positions_present(self):
        """positions содержит все три протокола."""
        self.assertIn("aave_arbitrum", self.vp["positions"])
        self.assertIn("morpho_steakhouse", self.vp["positions"])
        self.assertIn("aave_mainnet", self.vp["positions"])

    def test_vportfolio_tier_field(self):
        """tier поле присутствует и равно 'T1'."""
        self.assertEqual(self.vp["tier"], "T1")

    def test_vportfolio_gas_savings_field(self):
        """gas_savings_per_tx_usd присутствует и равен 0.09."""
        self.assertEqual(self.vp["gas_savings_per_tx_usd"], 0.09)

    def test_vportfolio_risk_flags_field(self):
        """risk_flags присутствует в формате vportfolio."""
        self.assertIn("risk_flags", self.vp)
        self.assertIsInstance(self.vp["risk_flags"], list)

    def test_vportfolio_status_active(self):
        """status должен быть 'active'."""
        self.assertEqual(self.vp["status"], "active")

    def test_vportfolio_required_keys(self):
        """Все обязательные ключи VPortfolio присутствуют."""
        required = [
            "strategy_id", "capital_usd", "positions", "cash_usd",
            "equity_history", "daily_returns", "created_at", "last_updated",
            "total_yield_usd", "days_simulated", "peak_equity", "status",
            "current_equity", "drawdown_pct", "total_return_pct",
        ]
        for key in required:
            self.assertIn(key, self.vp, f"Ключ '{key}' отсутствует в vportfolio_format")

    def test_vportfolio_returns_dict(self):
        """to_vportfolio_format возвращает dict."""
        self.assertIsInstance(self.vp, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# TestS3GasSavings — 10 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestS3GasSavings(unittest.TestCase):
    """Тесты get_gas_savings_estimate."""

    def setUp(self):
        self.s3 = S3AaveArbMorpho()

    def test_gas_savings_zero_txs(self):
        """0 транзакций → экономия 0.0."""
        self.assertAlmostEqual(self.s3.get_gas_savings_estimate(0), 0.0, places=6)

    def test_gas_savings_one_tx(self):
        """1 транзакция → экономия = GAS_SAVINGS_PER_TX_USD."""
        result = self.s3.get_gas_savings_estimate(1)
        self.assertAlmostEqual(result, GAS_SAVINGS_PER_TX_USD, places=6)

    def test_gas_savings_ten_txs(self):
        """10 транзакций → экономия ≈ $0.90."""
        result = self.s3.get_gas_savings_estimate(10)
        self.assertAlmostEqual(result, 0.90, places=6)

    def test_gas_savings_hundred_txs(self):
        """100 транзакций → экономия ≈ $9.00."""
        result = self.s3.get_gas_savings_estimate(100)
        self.assertAlmostEqual(result, 9.0, places=6)

    def test_gas_savings_negative_input(self):
        """Отрицательный n_txs → возвращает 0.0."""
        self.assertAlmostEqual(self.s3.get_gas_savings_estimate(-5), 0.0, places=6)

    def test_gas_savings_large_number(self):
        """Большое количество транзакций работает корректно."""
        result = self.s3.get_gas_savings_estimate(1000)
        self.assertAlmostEqual(result, 1000 * GAS_SAVINGS_PER_TX_USD, places=6)

    def test_gas_savings_returns_float(self):
        """get_gas_savings_estimate возвращает float."""
        result = self.s3.get_gas_savings_estimate(5)
        self.assertIsInstance(result, float)

    def test_gas_savings_proportional(self):
        """Экономия линейно пропорциональна числу транзакций."""
        r5  = self.s3.get_gas_savings_estimate(5)
        r10 = self.s3.get_gas_savings_estimate(10)
        self.assertAlmostEqual(r10, 2 * r5, places=6)

    def test_gas_savings_minus_one(self):
        """n_txs = -1 → 0.0."""
        self.assertAlmostEqual(self.s3.get_gas_savings_estimate(-1), 0.0, places=6)

    def test_gas_savings_constant_value(self):
        """GAS_SAVINGS_PER_TX_USD = 0.09."""
        self.assertEqual(GAS_SAVINGS_PER_TX_USD, 0.09)


# ═══════════════════════════════════════════════════════════════════════════════
# TestS3RiskFlags — 8 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestS3RiskFlags(unittest.TestCase):
    """Тесты get_risk_flags."""

    def setUp(self):
        self.s3 = S3AaveArbMorpho()

    def test_risk_flags_returns_list(self):
        """get_risk_flags возвращает list."""
        self.assertIsInstance(self.s3.get_risk_flags(), list)

    def test_risk_flags_contains_l2_bridge_risk(self):
        """Флаг l2_bridge_risk присутствует."""
        self.assertIn("l2_bridge_risk", self.s3.get_risk_flags())

    def test_risk_flags_contains_multi_chain_complexity(self):
        """Флаг multi_chain_complexity присутствует."""
        self.assertIn("multi_chain_complexity", self.s3.get_risk_flags())

    def test_risk_flags_count(self):
        """Ровно 2 risk-флага."""
        self.assertEqual(len(self.s3.get_risk_flags()), 2)

    def test_risk_flags_returns_copy(self):
        """get_risk_flags возвращает копию (не мутирует RISK_FLAGS)."""
        flags = self.s3.get_risk_flags()
        flags.append("injected_flag")
        self.assertEqual(len(self.s3.get_risk_flags()), 2)

    def test_risk_flags_module_constant(self):
        """Модульная константа RISK_FLAGS содержит оба флага."""
        self.assertIn("l2_bridge_risk", RISK_FLAGS)
        self.assertIn("multi_chain_complexity", RISK_FLAGS)

    def test_risk_flags_no_unknown_flags(self):
        """get_risk_flags не содержит неожиданных флагов."""
        known = {"l2_bridge_risk", "multi_chain_complexity"}
        for flag in self.s3.get_risk_flags():
            self.assertIn(flag, known)

    def test_risk_flags_consistent_across_calls(self):
        """Повторные вызовы возвращают одинаковые флаги."""
        flags1 = self.s3.get_risk_flags()
        flags2 = self.s3.get_risk_flags()
        self.assertEqual(sorted(flags1), sorted(flags2))


# ═══════════════════════════════════════════════════════════════════════════════
# TestS3Constants — 10 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestS3Constants(unittest.TestCase):
    """Тесты значений констант стратегии."""

    def test_strategy_id_value(self):
        """STRATEGY_ID == 'S3'."""
        self.assertEqual(STRATEGY_ID, "S3")

    def test_strategy_name_value(self):
        """STRATEGY_NAME содержит 'Aave Arbitrum' и 'Morpho'."""
        self.assertIn("Aave Arbitrum", STRATEGY_NAME)
        self.assertIn("Morpho", STRATEGY_NAME)

    def test_tier_value(self):
        """TIER == 'T1'."""
        self.assertEqual(TIER, "T1")

    def test_allocation_aave_arbitrum(self):
        """Вес aave_arbitrum = 0.55."""
        self.assertAlmostEqual(ALLOCATION["aave_arbitrum"], 0.55, places=6)

    def test_allocation_morpho_steakhouse(self):
        """Вес morpho_steakhouse = 0.30."""
        self.assertAlmostEqual(ALLOCATION["morpho_steakhouse"], 0.30, places=6)

    def test_allocation_aave_mainnet(self):
        """Вес aave_mainnet = 0.15."""
        self.assertAlmostEqual(ALLOCATION["aave_mainnet"], 0.15, places=6)

    def test_allocation_sum_equals_one(self):
        """Сумма весов ALLOCATION = 1.0."""
        total = sum(ALLOCATION.values())
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_fallback_apy_aave_arbitrum(self):
        """FALLBACK_APY['aave_arbitrum'] == 4.1."""
        self.assertAlmostEqual(FALLBACK_APY["aave_arbitrum"], 4.1, places=6)

    def test_fallback_apy_morpho_steakhouse(self):
        """FALLBACK_APY['morpho_steakhouse'] == 6.5."""
        self.assertAlmostEqual(FALLBACK_APY["morpho_steakhouse"], 6.5, places=6)

    def test_fallback_apy_aave_mainnet(self):
        """FALLBACK_APY['aave_mainnet'] == 3.2."""
        self.assertAlmostEqual(FALLBACK_APY["aave_mainnet"], 3.2, places=6)


# ═══════════════════════════════════════════════════════════════════════════════
# TestS3EdgeCases — 5 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestS3EdgeCases(unittest.TestCase):
    """Граничные случаи."""

    def test_zero_capital_init(self):
        """S3 с нулевым капиталом инициализируется без ошибок."""
        s3 = S3AaveArbMorpho(capital=0.0)
        self.assertEqual(s3.capital, 0.0)
        self.assertAlmostEqual(s3.current_equity, 0.0, places=6)

    def test_zero_capital_simulate_day(self):
        """simulate_day при нулевом капитале → yield = 0."""
        s3 = S3AaveArbMorpho(capital=0.0)
        result = s3.simulate_day(APY_DEFAULT)
        self.assertAlmostEqual(result["daily_yield_usd"], 0.0, places=10)

    def test_empty_apy_map_simulate_day(self):
        """Пустая apy_map → fallback APY, yield > 0."""
        s3 = S3AaveArbMorpho()
        result = s3.simulate_day({})
        self.assertGreater(result["daily_yield_usd"], 0.0)

    def test_vportfolio_zero_capital_no_division_error(self):
        """to_vportfolio_format при capital=0 не вызывает ZeroDivisionError."""
        s3 = S3AaveArbMorpho(capital=0.0)
        vp = s3.to_vportfolio_format()
        self.assertAlmostEqual(vp["total_return_pct"], 0.0, places=6)

    def test_get_stats_returns_all_fields(self):
        """get_stats возвращает dict со всеми ожидаемыми полями."""
        s3 = S3AaveArbMorpho()
        stats = s3.get_stats()
        for key in [
            "strategy_id", "strategy_name", "tier", "capital_usd",
            "current_equity", "total_yield_usd", "days_simulated",
            "total_return_pct", "weighted_apy_expected",
            "gas_savings_per_tx_usd", "risk_flags", "allocation",
        ]:
            self.assertIn(key, stats, f"Ключ '{key}' отсутствует в get_stats()")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
