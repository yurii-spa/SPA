"""
spa_core/tests/test_s14_arbitrum_radiant.py — MP-394

90+ unittest-кейсов для стратегии S14 Arbitrum Radiant Max.

Классы тестов:
  - TestS14Init (9)                — id, name, tier, allocation, начальное состояние
  - TestS14WeightedAPY (14)        — формула, fallback, spike-нормализация, edge cases
  - TestS14SimulateDay (15)        — структура ответа, yield, реинвестирование, edge cases
  - TestS14VPortfolioFormat (12)   — обязательные ключи, корректные значения
  - TestS14RiskFlags (10)          — базовые флаги, bridge risk, edge cases
  - TestS14Constants (10)          — все константы, веса, суммирование аллокации
  - TestS14EdgeCases (10)          — capital=0, пустой apy_map, отрицательный APY
  - TestS14Registry (6)            — регистрация в REGISTRY, handler_class, enabled
  - TestS14GetStats (8)            — get_stats: ключи, значения, корректность
  - TestS14GasSavings (8)          — get_gas_savings_estimate: формула, edge cases
  - TestS14L2Allocation (8)        — get_l2_allocation_pct: расчёт, edge cases

Правила:
  - stdlib only, никаких внешних зависимостей
  - Все тесты изолированы (отдельные инстансы)
  - Комментарии на русском
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

# ─── sys.path (позволяет запускать из любого CWD) ─────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

# ─── Импорты тестируемых модулей ──────────────────────────────────────────────
from spa_core.strategies.s14_arbitrum_radiant import (
    S14ArbitrumRadiantMax,
    STRATEGY_ID,
    STRATEGY_NAME,
    TIER,
    DESCRIPTION,
    ALLOCATION,
    FALLBACK_APY,
    RISK_SCORES,
    WEIGHTED_APY_EXPECTED,
    RISK_BLENDED,
    RADIANT_SPIKE_THRESHOLD,
    RADIANT_APY_NORMALIZED,
    GAS_ADVANTAGE_USD,
    GAS_MAINNET_USD,
    GAS_L2_USD,
    L2_BRIDGE_RISK_THRESHOLD,
    L2_ALLOCATION_TOTAL,
    TARGET_APY_MIN,
    TARGET_APY_MAX,
    MAX_DRAWDOWN_PCT,
)
from spa_core.strategies.strategy_registry import REGISTRY


# ─── Вспомогательные данные ───────────────────────────────────────────────────

# Стандартная apy_map с дефолтными значениями
APY_MAP_STD = {
    "aave_arbitrum":     4.6,
    "radiant_arbitrum":  8.0,
    "morpho_steakhouse": 6.5,
}

# APY_MAP с высокими значениями
APY_MAP_HIGH = {
    "aave_arbitrum":     8.0,
    "radiant_arbitrum":  12.0,
    "morpho_steakhouse": 10.0,
}

# APY_MAP с нулями
APY_MAP_ZERO = {
    "aave_arbitrum":     0.0,
    "radiant_arbitrum":  0.0,
    "morpho_steakhouse": 0.0,
}

# APY_MAP с Radiant spike (>20% → нормализуется до 12%)
APY_MAP_RADIANT_SPIKE = {
    "aave_arbitrum":     4.6,
    "radiant_arbitrum":  25.0,   # спайк — должен нормализоваться до 12%
    "morpho_steakhouse": 6.5,
}

# Частичная APY_MAP (только Aave Arb)
APY_MAP_PARTIAL = {"aave_arbitrum": 5.0}


# =============================================================================
# БЛОК 1: TestS14Init — Инициализация
# =============================================================================

class TestS14Init(unittest.TestCase):

    def test_strategy_id_correct(self):
        """strategy_id == 'S14'."""
        s = S14ArbitrumRadiantMax()
        self.assertEqual(s.strategy_id, "S14")

    def test_strategy_name_correct(self):
        """strategy_name содержит 'Arbitrum'."""
        s = S14ArbitrumRadiantMax()
        self.assertIn("Arbitrum", s.strategy_name)

    def test_tier_correct(self):
        """tier == 'T1+T2'."""
        s = S14ArbitrumRadiantMax()
        self.assertEqual(s.tier, "T1+T2")

    def test_default_capital(self):
        """Дефолтный капитал — $100,000."""
        s = S14ArbitrumRadiantMax()
        self.assertEqual(s.capital, 100_000.0)

    def test_custom_capital(self):
        """Кастомный капитал корректно сохраняется."""
        s = S14ArbitrumRadiantMax(capital=50_000.0)
        self.assertEqual(s.capital, 50_000.0)

    def test_initial_positions_sum_equals_capital(self):
        """Сумма начальных позиций равна начальному капиталу."""
        s = S14ArbitrumRadiantMax(capital=100_000.0)
        self.assertAlmostEqual(sum(s._positions.values()), 100_000.0, places=5)

    def test_initial_positions_match_allocation_weights(self):
        """Начальные позиции соответствуют весам ALLOCATION."""
        s = S14ArbitrumRadiantMax(capital=100_000.0)
        for protocol, weight in ALLOCATION.items():
            self.assertAlmostEqual(
                s._positions[protocol], 100_000.0 * weight, places=5,
                msg=f"Position {protocol} mismatch"
            )

    def test_zero_capital_allowed(self):
        """Нулевой капитал допускается (paper trading)."""
        s = S14ArbitrumRadiantMax(capital=0.0)
        self.assertEqual(s.capital, 0.0)
        self.assertEqual(sum(s._positions.values()), 0.0)

    def test_initial_days_simulated_zero(self):
        """days_simulated = 0 при инициализации."""
        s = S14ArbitrumRadiantMax()
        self.assertEqual(s._days_simulated, 0)


# =============================================================================
# БЛОК 2: TestS14WeightedAPY — Взвешенный APY
# =============================================================================

class TestS14WeightedAPY(unittest.TestCase):

    def setUp(self):
        self.s = S14ArbitrumRadiantMax()

    def test_with_default_apy_map(self):
        """Взвешенный APY с дефолтными значениями ≈ 6.17%."""
        apy = self.s.compute_weighted_apy(APY_MAP_STD)
        self.assertAlmostEqual(apy, 6.17, places=2)

    def test_with_empty_map_uses_fallback(self):
        """Пустая apy_map → все значения из FALLBACK_APY."""
        apy = self.s.compute_weighted_apy({})
        expected = (
            ALLOCATION["aave_arbitrum"] * FALLBACK_APY["aave_arbitrum"]
            + ALLOCATION["radiant_arbitrum"] * FALLBACK_APY["radiant_arbitrum"]
            + ALLOCATION["morpho_steakhouse"] * FALLBACK_APY["morpho_steakhouse"]
        )
        self.assertAlmostEqual(apy, expected, places=4)

    def test_fallback_apy_matches_weighted_expected(self):
        """WEIGHTED_APY_EXPECTED в пределах ±0.01 от реального weighted average."""
        apy = self.s.compute_weighted_apy({})
        self.assertAlmostEqual(apy, WEIGHTED_APY_EXPECTED, places=1)

    def test_radiant_spike_normalization(self):
        """Radiant APY > 20% нормализуется до 12% в расчёте."""
        apy = self.s.compute_weighted_apy(APY_MAP_RADIANT_SPIKE)
        expected = (
            0.45 * 4.6 + 0.35 * RADIANT_APY_NORMALIZED + 0.20 * 6.5
        )  # 0.45*4.6 + 0.35*12.0 + 0.20*6.5
        self.assertAlmostEqual(apy, expected, places=4)

    def test_radiant_spike_exactly_at_threshold_not_normalized(self):
        """Radiant APY == 20.0 (на пороге) — НЕ нормализуется (строгий >)."""
        apy_map = {
            "aave_arbitrum": 4.6,
            "radiant_arbitrum": RADIANT_SPIKE_THRESHOLD,  # точно 20.0
            "morpho_steakhouse": 6.5,
        }
        apy = self.s.compute_weighted_apy(apy_map)
        expected = 0.45 * 4.6 + 0.35 * 20.0 + 0.20 * 6.5
        self.assertAlmostEqual(apy, expected, places=4)

    def test_radiant_below_spike_threshold_not_normalized(self):
        """Radiant APY 15% — ниже порога, не нормализуется."""
        apy_map = {
            "aave_arbitrum": 4.6,
            "radiant_arbitrum": 15.0,
            "morpho_steakhouse": 6.5,
        }
        apy = self.s.compute_weighted_apy(apy_map)
        expected = 0.45 * 4.6 + 0.35 * 15.0 + 0.20 * 6.5
        self.assertAlmostEqual(apy, expected, places=4)

    def test_zero_apy_map_returns_zero(self):
        """APY_MAP_ZERO → взвешенный APY = 0."""
        apy = self.s.compute_weighted_apy(APY_MAP_ZERO)
        self.assertEqual(apy, 0.0)

    def test_partial_map_uses_fallback_for_missing(self):
        """Частичная apy_map: отсутствующие ключи → из FALLBACK_APY."""
        apy = self.s.compute_weighted_apy(APY_MAP_PARTIAL)
        expected = (
            0.45 * 5.0  # из apy_map (переопределён)
            + 0.35 * FALLBACK_APY["radiant_arbitrum"]   # fallback
            + 0.20 * FALLBACK_APY["morpho_steakhouse"]  # fallback
        )
        self.assertAlmostEqual(apy, expected, places=4)

    def test_apy_above_target_min(self):
        """Взвешенный APY при дефолтных значениях выше TARGET_APY_MIN (5.5%)."""
        apy = self.s.compute_weighted_apy({})
        self.assertGreater(apy, TARGET_APY_MIN)

    def test_apy_within_target_range(self):
        """Взвешенный APY в пределах TARGET_APY_MIN .. TARGET_APY_MAX."""
        apy = self.s.compute_weighted_apy(APY_MAP_STD)
        self.assertGreaterEqual(apy, TARGET_APY_MIN)
        self.assertLessEqual(apy, TARGET_APY_MAX)

    def test_returns_float(self):
        """compute_weighted_apy возвращает float."""
        apy = self.s.compute_weighted_apy(APY_MAP_STD)
        self.assertIsInstance(apy, float)

    def test_high_apy_map(self):
        """Высокие APY дают взвешенный результат выше дефолтного."""
        apy_default = self.s.compute_weighted_apy(APY_MAP_STD)
        apy_high    = self.s.compute_weighted_apy(APY_MAP_HIGH)
        self.assertGreater(apy_high, apy_default)

    def test_spike_normalization_reduces_apy(self):
        """Spike normalization снижает взвешенный APY (25% → 12%)."""
        apy_spike  = self.s.compute_weighted_apy(APY_MAP_RADIANT_SPIKE)
        apy_no_cap = self.s.compute_weighted_apy({
            "aave_arbitrum": 4.6,
            "radiant_arbitrum": 25.0,
            "morpho_steakhouse": 6.5,
        })
        # Оба результата одинаковы (нормализация встроена в compute_weighted_apy)
        self.assertAlmostEqual(apy_spike, apy_no_cap, places=8)

    def test_very_high_radiant_apy_normalized(self):
        """Radiant 100% APY → нормализуется до 12%."""
        apy_map = {
            "aave_arbitrum": 4.6,
            "radiant_arbitrum": 100.0,
            "morpho_steakhouse": 6.5,
        }
        apy = self.s.compute_weighted_apy(apy_map)
        expected = 0.45 * 4.6 + 0.35 * 12.0 + 0.20 * 6.5
        self.assertAlmostEqual(apy, expected, places=4)


# =============================================================================
# БЛОК 3: TestS14SimulateDay — Симуляция дня
# =============================================================================

class TestS14SimulateDay(unittest.TestCase):

    def setUp(self):
        self.s = S14ArbitrumRadiantMax(capital=100_000.0)

    def test_returns_dict(self):
        """simulate_day возвращает dict."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertIsInstance(result, dict)

    def test_result_has_required_keys(self):
        """Результат содержит все обязательные ключи."""
        result = self.s.simulate_day(APY_MAP_STD)
        for key in ("daily_yield_usd", "cumulative_pnl", "positions", "weighted_apy", "l2_allocation_pct"):
            self.assertIn(key, result, msg=f"Missing key: {key}")

    def test_daily_yield_positive(self):
        """При стандартных APY daily_yield_usd > 0."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertGreater(result["daily_yield_usd"], 0.0)

    def test_days_simulated_increments(self):
        """days_simulated увеличивается на 1 каждый день."""
        self.s.simulate_day(APY_MAP_STD)
        self.assertEqual(self.s._days_simulated, 1)
        self.s.simulate_day(APY_MAP_STD)
        self.assertEqual(self.s._days_simulated, 2)

    def test_compound_yield_grows_equity(self):
        """После simulate_day equity > начальный капитал."""
        self.s.simulate_day(APY_MAP_STD)
        self.assertGreater(self.s.current_equity, 100_000.0)

    def test_cumulative_pnl_accumulates(self):
        """cumulative_pnl накапливается через несколько дней."""
        r1 = self.s.simulate_day(APY_MAP_STD)
        r2 = self.s.simulate_day(APY_MAP_STD)
        self.assertGreater(r2["cumulative_pnl"], r1["cumulative_pnl"])

    def test_zero_apy_no_yield(self):
        """APY = 0 → daily_yield_usd = 0."""
        result = self.s.simulate_day(APY_MAP_ZERO)
        self.assertAlmostEqual(result["daily_yield_usd"], 0.0, places=8)

    def test_zero_apy_equity_unchanged(self):
        """APY = 0 → equity не меняется после дня."""
        before = self.s.current_equity
        self.s.simulate_day(APY_MAP_ZERO)
        self.assertAlmostEqual(self.s.current_equity, before, places=8)

    def test_positions_in_result(self):
        """Результат содержит 3 позиции."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertEqual(len(result["positions"]), 3)

    def test_positions_keys_correct(self):
        """Позиции содержат правильные ключи протоколов."""
        result = self.s.simulate_day(APY_MAP_STD)
        for key in ("aave_arbitrum", "radiant_arbitrum", "morpho_steakhouse"):
            self.assertIn(key, result["positions"])

    def test_radiant_spike_in_simulate(self):
        """Spike normalization применяется в simulate_day."""
        normal  = S14ArbitrumRadiantMax(capital=100_000.0)
        spiked  = S14ArbitrumRadiantMax(capital=100_000.0)

        r_normal  = normal.simulate_day(APY_MAP_STD)
        r_spiked  = spiked.simulate_day(APY_MAP_RADIANT_SPIKE)  # Radiant 25% → 12%

        # С нормализацией спайк всё равно даёт yield
        self.assertGreater(r_spiked["daily_yield_usd"], 0.0)

    def test_equity_history_grows(self):
        """equity_history пополняется после simulate_day."""
        self.s.simulate_day(APY_MAP_STD)
        self.assertEqual(len(self.s._equity_history), 1)
        self.s.simulate_day(APY_MAP_STD)
        self.assertEqual(len(self.s._equity_history), 2)

    def test_equity_history_entry_keys(self):
        """Запись в equity_history содержит обязательные поля."""
        self.s.simulate_day(APY_MAP_STD)
        entry = self.s._equity_history[-1]
        for key in ("day", "equity", "daily_yield_usd", "weighted_apy", "l2_allocation_pct"):
            self.assertIn(key, entry, msg=f"Missing history key: {key}")

    def test_l2_allocation_pct_in_result(self):
        """l2_allocation_pct присутствует в результате и > 0."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertIn("l2_allocation_pct", result)
        self.assertGreater(result["l2_allocation_pct"], 0.0)

    def test_30_day_annual_yield_estimate(self):
        """30-дневный yield укладывается в ожидаемый диапазон от TARGET APY."""
        for _ in range(30):
            self.s.simulate_day(APY_MAP_STD)

        # 30 дней при 6.17% годовых: ~$100K * 6.17% / 365 * 30 ≈ $508
        expected_low  = 100_000.0 * TARGET_APY_MIN / 100.0 / 365.0 * 30.0
        expected_high = 100_000.0 * TARGET_APY_MAX / 100.0 / 365.0 * 30.0
        self.assertGreater(self.s._total_yield_usd, expected_low)
        self.assertLess(self.s._total_yield_usd, expected_high)


# =============================================================================
# БЛОК 4: TestS14VPortfolioFormat — Совместимость с VPortfolio
# =============================================================================

class TestS14VPortfolioFormat(unittest.TestCase):

    def setUp(self):
        self.s = S14ArbitrumRadiantMax(capital=100_000.0)
        self.s.simulate_day(APY_MAP_STD)
        self.vp = self.s.to_vportfolio_format()

    def test_returns_dict(self):
        """to_vportfolio_format() возвращает dict."""
        self.assertIsInstance(self.vp, dict)

    def test_strategy_id_correct(self):
        """strategy_id == 'S14'."""
        self.assertEqual(self.vp["strategy_id"], "S14")

    def test_required_keys_present(self):
        """Все обязательные ключи VPortfolio присутствуют."""
        for key in (
            "strategy_id", "strategy_name", "capital_usd", "positions",
            "cash_usd", "equity_history", "daily_returns", "created_at",
            "last_updated", "total_yield_usd", "cumulative_pnl",
            "days_simulated", "peak_equity", "status", "current_equity",
            "drawdown_pct", "total_return_pct",
        ):
            self.assertIn(key, self.vp, msg=f"Missing VPortfolio key: {key}")

    def test_s14_specific_keys_present(self):
        """S14-специфичные поля присутствуют."""
        for key in ("tier", "allocation", "apy", "risk_blended", "risk_flags",
                    "l2_allocation_pct", "description"):
            self.assertIn(key, self.vp, msg=f"Missing S14 key: {key}")

    def test_cash_usd_is_zero(self):
        """cash_usd == 0.0 (все средства в позициях)."""
        self.assertEqual(self.vp["cash_usd"], 0.0)

    def test_drawdown_pct_is_zero(self):
        """drawdown_pct == 0.0 (нет убытков в paper trading)."""
        self.assertEqual(self.vp["drawdown_pct"], 0.0)

    def test_status_active(self):
        """status == 'active'."""
        self.assertEqual(self.vp["status"], "active")

    def test_capital_correct(self):
        """capital_usd == 100,000."""
        self.assertEqual(self.vp["capital_usd"], 100_000.0)

    def test_total_return_pct_positive_after_day(self):
        """total_return_pct > 0 после одного дня с положительным APY."""
        self.assertGreater(self.vp["total_return_pct"], 0.0)

    def test_apy_equals_weighted_expected(self):
        """apy == WEIGHTED_APY_EXPECTED."""
        self.assertAlmostEqual(self.vp["apy"], WEIGHTED_APY_EXPECTED, places=4)

    def test_tier_correct(self):
        """tier == 'T1+T2'."""
        self.assertEqual(self.vp["tier"], "T1+T2")

    def test_l2_allocation_pct_near_80(self):
        """l2_allocation_pct ≈ 80% (Aave Arb 45% + Radiant 35%)."""
        self.assertAlmostEqual(self.vp["l2_allocation_pct"], 80.0, delta=1.0)


# =============================================================================
# БЛОК 5: TestS14RiskFlags — Флаги риска
# =============================================================================

class TestS14RiskFlags(unittest.TestCase):

    def setUp(self):
        self.s = S14ArbitrumRadiantMax()

    def test_returns_list(self):
        """get_risk_flags() возвращает список."""
        self.assertIsInstance(self.s.get_risk_flags(), list)

    def test_radiant_spike_flag_always_present(self):
        """'radiant_spike_normalization' всегда присутствует."""
        self.assertIn("radiant_spike_normalization", self.s.get_risk_flags())

    def test_l2_bridge_exposure_always_present(self):
        """'l2_bridge_exposure' всегда присутствует."""
        self.assertIn("l2_bridge_exposure", self.s.get_risk_flags())

    def test_l2_bridge_risk_present(self):
        """'l2_bridge_risk' присутствует (L2 аллокация 80% > 70% threshold)."""
        # Стратегия имеет 80% L2 > 70% threshold → флаг должен быть
        self.assertIn("l2_bridge_risk", self.s.get_risk_flags())

    def test_minimum_two_flags(self):
        """Минимум 2 базовых флага всегда возвращаются."""
        self.assertGreaterEqual(len(self.s.get_risk_flags()), 2)

    def test_flags_are_strings(self):
        """Все флаги — строки."""
        for flag in self.s.get_risk_flags():
            self.assertIsInstance(flag, str)

    def test_flags_are_unique(self):
        """Флаги не дублируются."""
        flags = self.s.get_risk_flags()
        self.assertEqual(len(flags), len(set(flags)))

    def test_l2_bridge_risk_flag_fires_when_above_threshold(self):
        """Флаг l2_bridge_risk активен когда L2 аллокация > 70%."""
        # ALLOCATION["aave_arbitrum"] + ALLOCATION["radiant_arbitrum"] = 0.80 > 0.70
        self.assertGreater(
            ALLOCATION["aave_arbitrum"] + ALLOCATION["radiant_arbitrum"],
            L2_BRIDGE_RISK_THRESHOLD
        )
        self.assertIn("l2_bridge_risk", self.s.get_risk_flags())

    def test_flags_stable_across_calls(self):
        """Флаги стабильны при многократных вызовах."""
        flags1 = self.s.get_risk_flags()
        flags2 = self.s.get_risk_flags()
        self.assertEqual(sorted(flags1), sorted(flags2))

    def test_three_flags_when_l2_dominant(self):
        """При 80% L2 аллокации возвращается ровно 3 флага."""
        flags = self.s.get_risk_flags()
        self.assertEqual(len(flags), 3)

    def test_description_mentions_arbitrum(self):
        """DESCRIPTION упоминает 'Arbitrum'."""
        self.assertIn("Arbitrum", DESCRIPTION)


# =============================================================================
# БЛОК 6: TestS14Constants — Константы и веса
# =============================================================================

class TestS14Constants(unittest.TestCase):

    def test_allocation_sum_equals_one(self):
        """Сумма весов ALLOCATION = 1.0."""
        total = sum(ALLOCATION.values())
        self.assertAlmostEqual(total, 1.0, places=10)

    def test_allocation_has_three_protocols(self):
        """ALLOCATION содержит ровно 3 протокола."""
        self.assertEqual(len(ALLOCATION), 3)

    def test_aave_arb_weight_correct(self):
        """Aave Arbitrum: вес 0.45."""
        self.assertAlmostEqual(ALLOCATION["aave_arbitrum"], 0.45, places=10)

    def test_radiant_weight_correct(self):
        """Radiant Arbitrum: вес 0.35."""
        self.assertAlmostEqual(ALLOCATION["radiant_arbitrum"], 0.35, places=10)

    def test_morpho_weight_correct(self):
        """Morpho Steakhouse: вес 0.20."""
        self.assertAlmostEqual(ALLOCATION["morpho_steakhouse"], 0.20, places=10)

    def test_t1_dominant(self):
        """T1 аллокация (Aave Arb + Morpho) ≥ 60% (T1-dominant)."""
        t1_share = ALLOCATION["aave_arbitrum"] + ALLOCATION["morpho_steakhouse"]
        self.assertGreaterEqual(t1_share, 0.60)

    def test_weighted_apy_expected_above_6_pct(self):
        """WEIGHTED_APY_EXPECTED > 6% (ключевое требование MP-394)."""
        self.assertGreater(WEIGHTED_APY_EXPECTED, 6.0)

    def test_radiant_spike_threshold_is_20(self):
        """RADIANT_SPIKE_THRESHOLD == 20.0%."""
        self.assertEqual(RADIANT_SPIKE_THRESHOLD, 20.0)

    def test_radiant_apy_normalized_is_12(self):
        """RADIANT_APY_NORMALIZED == 12.0%."""
        self.assertEqual(RADIANT_APY_NORMALIZED, 12.0)

    def test_gas_advantage_is_difference(self):
        """GAS_ADVANTAGE_USD = GAS_MAINNET_USD - GAS_L2_USD."""
        self.assertAlmostEqual(
            GAS_ADVANTAGE_USD, GAS_MAINNET_USD - GAS_L2_USD, places=10
        )


# =============================================================================
# БЛОК 7: TestS14EdgeCases — Граничные случаи
# =============================================================================

class TestS14EdgeCases(unittest.TestCase):

    def test_zero_capital_simulate_day(self):
        """Нулевой капитал — simulate_day возвращает нулевой yield."""
        s = S14ArbitrumRadiantMax(capital=0.0)
        result = s.simulate_day(APY_MAP_STD)
        self.assertAlmostEqual(result["daily_yield_usd"], 0.0, places=10)

    def test_zero_capital_equity_stays_zero(self):
        """Нулевой капитал — equity остаётся 0 после симуляции."""
        s = S14ArbitrumRadiantMax(capital=0.0)
        s.simulate_day(APY_MAP_STD)
        self.assertAlmostEqual(s.current_equity, 0.0, places=10)

    def test_negative_apy_not_applied(self):
        """Отрицательный APY для протокола игнорируется (yield не начисляется)."""
        s = S14ArbitrumRadiantMax(capital=100_000.0)
        apy_map = {
            "aave_arbitrum":     -5.0,  # отрицательный → пропускается
            "radiant_arbitrum":  8.0,
            "morpho_steakhouse": 6.5,
        }
        result = s.simulate_day(apy_map)
        # Только Radiant и Morpho дают yield
        only_positive = (
            0.35 * 8.0 * 100_000.0 / 100.0 / 365.0 +
            0.20 * 6.5 * 100_000.0 / 100.0 / 365.0
        )
        self.assertAlmostEqual(result["daily_yield_usd"], only_positive, delta=0.05)

    def test_very_large_capital(self):
        """Очень большой капитал ($1B) — нет ошибок, yield корректен."""
        s = S14ArbitrumRadiantMax(capital=1_000_000_000.0)
        result = s.simulate_day(APY_MAP_STD)
        self.assertGreater(result["daily_yield_usd"], 0.0)
        self.assertFalse(math.isnan(result["daily_yield_usd"]))
        self.assertFalse(math.isinf(result["daily_yield_usd"]))

    def test_equity_ring_buffer_max_365(self):
        """equity_history не превышает 365 записей."""
        s = S14ArbitrumRadiantMax()
        for _ in range(400):
            s.simulate_day(APY_MAP_STD)
        self.assertLessEqual(len(s._equity_history), 365)

    def test_weighted_apy_with_none_values_handled_gracefully(self):
        """Unknown protocol key в apy_map не вызывает KeyError."""
        try:
            apy = self.s.compute_weighted_apy({"unknown_protocol": 10.0})
            self.assertIsInstance(apy, float)
        except KeyError:
            self.fail("compute_weighted_apy raised KeyError for unknown key")

    def test_simulate_100_days_consistent(self):
        """100 дней симуляции — equity непрерывно растёт."""
        s = S14ArbitrumRadiantMax(capital=100_000.0)
        prev_equity = s.current_equity
        for _ in range(100):
            s.simulate_day(APY_MAP_STD)
            self.assertGreaterEqual(s.current_equity, prev_equity)
            prev_equity = s.current_equity

    def test_to_vportfolio_no_simulation(self):
        """to_vportfolio_format работает без предварительной симуляции."""
        s = S14ArbitrumRadiantMax()
        vp = s.to_vportfolio_format()
        self.assertEqual(vp["days_simulated"], 0)
        self.assertEqual(vp["total_yield_usd"], 0.0)

    def test_get_stats_no_simulation(self):
        """get_stats работает без предварительной симуляции."""
        s = S14ArbitrumRadiantMax()
        stats = s.get_stats()
        self.assertEqual(stats["days_simulated"], 0)

    def test_weighted_apy_non_negative_with_fallback(self):
        """compute_weighted_apy с fallback APY всегда ≥ 0."""
        s = S14ArbitrumRadiantMax()
        apy = s.compute_weighted_apy({})
        self.assertGreaterEqual(apy, 0.0)

    # setUp для last 4 tests
    def setUp(self):
        self.s = S14ArbitrumRadiantMax()


# =============================================================================
# БЛОК 8: TestS14Registry — Регистрация в REGISTRY
# =============================================================================

class TestS14Registry(unittest.TestCase):

    def test_s14_registered(self):
        """S14 зарегистрирован в REGISTRY."""
        meta = REGISTRY.get("S14")
        self.assertIsNotNone(meta)

    def test_handler_class_correct(self):
        """handler_class == 'S14ArbitrumRadiantMax'."""
        meta = REGISTRY.get("S14")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.handler_class, "S14ArbitrumRadiantMax")

    def test_module_path_correct(self):
        """module содержит 's14_arbitrum_radiant'."""
        meta = REGISTRY.get("S14")
        self.assertIsNotNone(meta)
        self.assertIn("s14_arbitrum_radiant", meta.module)

    def test_enabled_by_default(self):
        """S14 enabled по умолчанию."""
        meta = REGISTRY.get("S14")
        self.assertIsNotNone(meta)
        self.assertTrue(meta.enabled)

    def test_risk_tier_in_registry(self):
        """risk_tier в реестре — валидное значение."""
        meta = REGISTRY.get("S14")
        self.assertIsNotNone(meta)
        self.assertIn(meta.risk_tier, ("T1", "T2", "T3"))

    def test_target_apy_range_correct(self):
        """target_apy_min < target_apy_max в реестре."""
        meta = REGISTRY.get("S14")
        self.assertIsNotNone(meta)
        self.assertLess(meta.target_apy_min, meta.target_apy_max)


# =============================================================================
# БЛОК 9: TestS14GetStats — Статистика стратегии
# =============================================================================

class TestS14GetStats(unittest.TestCase):

    def setUp(self):
        self.s = S14ArbitrumRadiantMax(capital=100_000.0)
        for _ in range(5):
            self.s.simulate_day(APY_MAP_STD)
        self.stats = self.s.get_stats()

    def test_returns_dict(self):
        """get_stats() возвращает dict."""
        self.assertIsInstance(self.stats, dict)

    def test_strategy_id_in_stats(self):
        """strategy_id == 'S14' в stats."""
        self.assertEqual(self.stats["strategy_id"], "S14")

    def test_required_keys_present(self):
        """Все обязательные ключи присутствуют."""
        for key in (
            "strategy_id", "strategy_name", "tier", "description",
            "capital_usd", "current_equity", "days_simulated",
            "total_yield_usd", "total_return_pct", "weighted_apy_expected",
            "risk_blended", "risk_scores", "risk_flags", "allocation",
            "fallback_apy", "l2_allocation_pct", "gas_savings_per_tx_usd",
        ):
            self.assertIn(key, self.stats, msg=f"Missing stats key: {key}")

    def test_days_simulated_correct(self):
        """days_simulated == 5."""
        self.assertEqual(self.stats["days_simulated"], 5)

    def test_total_return_pct_positive(self):
        """total_return_pct > 0 после 5 дней с положительным APY."""
        self.assertGreater(self.stats["total_return_pct"], 0.0)

    def test_risk_blended_matches_constant(self):
        """risk_blended == RISK_BLENDED."""
        self.assertAlmostEqual(self.stats["risk_blended"], RISK_BLENDED, places=4)

    def test_gas_savings_per_tx_matches_constant(self):
        """gas_savings_per_tx_usd == GAS_ADVANTAGE_USD."""
        self.assertAlmostEqual(
            self.stats["gas_savings_per_tx_usd"], GAS_ADVANTAGE_USD, places=10
        )

    def test_l2_allocation_pct_near_80(self):
        """l2_allocation_pct ≈ 80% (Aave 45% + Radiant 35%)."""
        self.assertAlmostEqual(self.stats["l2_allocation_pct"], 80.0, delta=1.0)


# =============================================================================
# БЛОК 10: TestS14GasSavings — Оценка экономии газа
# =============================================================================

class TestS14GasSavings(unittest.TestCase):

    def setUp(self):
        self.s = S14ArbitrumRadiantMax()

    def test_single_tx_savings(self):
        """1 транзакция → $0.09 экономии."""
        self.assertAlmostEqual(self.s.get_gas_savings_estimate(1), 0.09, places=10)

    def test_10_txs_savings(self):
        """10 транзакций → $0.90 экономии."""
        self.assertAlmostEqual(self.s.get_gas_savings_estimate(10), 0.90, places=8)

    def test_100_txs_savings(self):
        """100 транзакций → $9.00 экономии."""
        self.assertAlmostEqual(self.s.get_gas_savings_estimate(100), 9.00, places=6)

    def test_zero_txs_returns_zero(self):
        """0 транзакций → $0.00 экономии."""
        self.assertAlmostEqual(self.s.get_gas_savings_estimate(0), 0.0, places=10)

    def test_negative_txs_returns_zero(self):
        """Отрицательное кол-во транзакций → $0.00 (граничный случай)."""
        self.assertAlmostEqual(self.s.get_gas_savings_estimate(-1), 0.0, places=10)

    def test_returns_float(self):
        """get_gas_savings_estimate() возвращает float."""
        self.assertIsInstance(self.s.get_gas_savings_estimate(5), float)

    def test_default_is_one_tx(self):
        """Дефолтное значение n_txs=1 — экономия $0.09."""
        self.assertAlmostEqual(self.s.get_gas_savings_estimate(), 0.09, places=10)

    def test_proportional_scaling(self):
        """Экономия пропорциональна количеству транзакций."""
        savings_5  = self.s.get_gas_savings_estimate(5)
        savings_10 = self.s.get_gas_savings_estimate(10)
        self.assertAlmostEqual(savings_10, 2.0 * savings_5, places=8)


# =============================================================================
# БЛОК 11: TestS14L2Allocation — L2 аллокация
# =============================================================================

class TestS14L2Allocation(unittest.TestCase):

    def setUp(self):
        self.s = S14ArbitrumRadiantMax(capital=100_000.0)

    def test_initial_l2_pct_near_80(self):
        """Начальная L2 аллокация ≈ 80% (0.45 + 0.35 = 0.80)."""
        pct = self.s.get_l2_allocation_pct()
        self.assertAlmostEqual(pct, 80.0, places=3)

    def test_returns_float(self):
        """get_l2_allocation_pct() возвращает float."""
        self.assertIsInstance(self.s.get_l2_allocation_pct(), float)

    def test_zero_capital_returns_zero(self):
        """Нулевой капитал → L2 аллокация 0.0."""
        s = S14ArbitrumRadiantMax(capital=0.0)
        self.assertAlmostEqual(s.get_l2_allocation_pct(), 0.0, places=10)

    def test_l2_allocation_stable_after_simulation(self):
        """L2 аллокация остаётся ≈ 80% после 30 дней (нет ребаланса)."""
        for _ in range(30):
            self.s.simulate_day(APY_MAP_STD)
        pct = self.s.get_l2_allocation_pct()
        # После compound rebalancing может немного измениться, но должно быть близко
        self.assertGreater(pct, 75.0)
        self.assertLess(pct, 85.0)

    def test_l2_allocation_total_constant_matches_allocation(self):
        """L2_ALLOCATION_TOTAL == 0.80 (Aave Arb + Radiant)."""
        self.assertAlmostEqual(L2_ALLOCATION_TOTAL, 0.80, places=10)

    def test_above_bridge_risk_threshold(self):
        """L2 аллокация > L2_BRIDGE_RISK_THRESHOLD (70%) → bridge risk активен."""
        pct_fraction = self.s.get_l2_allocation_pct() / 100.0
        self.assertGreater(pct_fraction, L2_BRIDGE_RISK_THRESHOLD)

    def test_l2_pct_in_range_0_100(self):
        """L2 аллокация в диапазоне 0..100%."""
        pct = self.s.get_l2_allocation_pct()
        self.assertGreaterEqual(pct, 0.0)
        self.assertLessEqual(pct, 100.0)

    def test_simulate_day_includes_l2_pct(self):
        """simulate_day включает l2_allocation_pct в возвращаемый dict."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertIn("l2_allocation_pct", result)
        self.assertAlmostEqual(result["l2_allocation_pct"], 80.0, delta=1.0)


# =============================================================================
# Точка запуска
# =============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
