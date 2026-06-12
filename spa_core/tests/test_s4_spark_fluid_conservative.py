"""
spa_core/tests/test_s4_spark_fluid_conservative.py — MP-391

75+ unittest-кейсов для стратегии S4 Conservative Spark+Fluid.

Классы тестов:
  - TestS4Init (8)               — id, name, tier, allocation, начальное состояние
  - TestS4WeightedAPY (14)       — формула, fallback, спайк-нормализация, edge cases
  - TestS4SimulateDay (14)       — структура ответа, yield, реинвестирование, edge cases
  - TestS4VPortfolioFormat (11)  — обязательные ключи, корректные значения
  - TestS4RiskFlags (10)         — GSM gate, базовые флаги, edge cases
  - TestS4Constants (10)         — все константы, веса, суммирование аллокации
  - TestS4EdgeCases (10)         — capital=0, пустой apy_map, отрицательный APY
  - TestS4Registry (5)           — регистрация в REGISTRY, handler_class, enabled
  - TestS4GetStats (7)           — get_stats: ключи, значения, корректность

Правила:
  - stdlib only, никаких внешних зависимостей
  - Все тесты изолированы (отдельные инстансы)
  - Комментарии на русском
"""
from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

# ─── sys.path (позволяет запускать из любого CWD) ─────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

# ─── Импорты тестируемых модулей ──────────────────────────────────────────────
from spa_core.strategies.s4_spark_fluid_conservative import (
    S4ConservativeSparkFluid,
    STRATEGY_ID,
    STRATEGY_NAME,
    TIER,
    DESCRIPTION,
    ALLOCATION,
    FALLBACK_APY,
    RISK_SCORES,
    WEIGHTED_APY_EXPECTED,
    RISK_BLENDED,
    GSM_PAUSE_DELAY_THRESHOLD_H,
    FLUID_APY_SPIKE_THRESHOLD,
    FLUID_APY_NORMALIZED,
    TARGET_APY_MIN,
    TARGET_APY_MAX,
)
from spa_core.strategies.strategy_registry import REGISTRY


# ─── Вспомогательные данные ───────────────────────────────────────────────────

# Стандартная apy_map с дефолтными значениями
APY_MAP_STD = {
    "spark_susds":       5.5,
    "fluid_fusdc":       6.5,
    "morpho_steakhouse": 6.5,
}

# APY_MAP с высокими значениями
APY_MAP_HIGH = {
    "spark_susds":       10.0,
    "fluid_fusdc":       12.0,
    "morpho_steakhouse": 11.0,
}

# APY_MAP с нулями
APY_MAP_ZERO = {
    "spark_susds":       0.0,
    "fluid_fusdc":       0.0,
    "morpho_steakhouse": 0.0,
}

# APY_MAP с Fluid spike (>15% → нормализуется до 9%)
APY_MAP_FLUID_SPIKE = {
    "spark_susds":       5.5,
    "fluid_fusdc":       20.0,   # спайк — должен нормализоваться до 9%
    "morpho_steakhouse": 6.5,
}

# Частичная APY_MAP (только Spark)
APY_MAP_PARTIAL_SPARK = {"spark_susds": 6.0}


# =============================================================================
# БЛОК 1: TestS4Init — Инициализация
# =============================================================================

class TestS4Init(unittest.TestCase):

    def test_strategy_id_correct(self):
        """strategy_id == 'S4'."""
        s = S4ConservativeSparkFluid()
        self.assertEqual(s.strategy_id, "S4")

    def test_strategy_name_correct(self):
        """strategy_name == 'S4 Conservative Spark+Fluid'."""
        s = S4ConservativeSparkFluid()
        self.assertEqual(s.strategy_name, "S4 Conservative Spark+Fluid")

    def test_tier_is_t1t2(self):
        """tier == 'T1+T2'."""
        s = S4ConservativeSparkFluid()
        self.assertEqual(s.tier, "T1+T2")

    def test_allocation_spark_60pct(self):
        """Spark sUSDS аллокация = 60% от капитала при инициализации."""
        s = S4ConservativeSparkFluid(capital=100_000.0)
        self.assertAlmostEqual(s._positions["spark_susds"], 60_000.0, places=4)

    def test_allocation_fluid_25pct(self):
        """Fluid fUSDC аллокация = 25% от капитала."""
        s = S4ConservativeSparkFluid(capital=100_000.0)
        self.assertAlmostEqual(s._positions["fluid_fusdc"], 25_000.0, places=4)

    def test_allocation_morpho_15pct(self):
        """Morpho Steakhouse аллокация = 15% от капитала."""
        s = S4ConservativeSparkFluid(capital=100_000.0)
        self.assertAlmostEqual(s._positions["morpho_steakhouse"], 15_000.0, places=4)

    def test_initial_days_simulated_zero(self):
        """Начальный счётчик дней = 0."""
        s = S4ConservativeSparkFluid()
        self.assertEqual(s._days_simulated, 0)

    def test_initial_total_yield_zero(self):
        """Начальный total_yield_usd = 0.0."""
        s = S4ConservativeSparkFluid()
        self.assertAlmostEqual(s._total_yield_usd, 0.0, places=10)


# =============================================================================
# БЛОК 2: TestS4WeightedAPY — Взвешенный APY
# =============================================================================

class TestS4WeightedAPY(unittest.TestCase):

    def setUp(self):
        self.s = S4ConservativeSparkFluid()

    def test_with_default_apy_map(self):
        """Взвешенный APY с дефолтными значениями ≈ 5.9%."""
        result = self.s.compute_weighted_apy(APY_MAP_STD)
        expected = 0.60 * 5.5 + 0.25 * 6.5 + 0.15 * 6.5
        self.assertAlmostEqual(result, expected, places=6)

    def test_default_apy_equals_weighted_apy_expected(self):
        """compute_weighted_apy(FALLBACK_APY) ≈ WEIGHTED_APY_EXPECTED = 5.9 (±0.01%)."""
        result = self.s.compute_weighted_apy(FALLBACK_APY)
        self.assertAlmostEqual(result, WEIGHTED_APY_EXPECTED, delta=0.01)

    def test_formula_exact_value(self):
        """Точная проверка: 0.60*5.5 + 0.25*6.5 + 0.15*6.5 = 5.9."""
        result = self.s.compute_weighted_apy(APY_MAP_STD)
        self.assertAlmostEqual(result, 5.9, places=5)

    def test_with_empty_map_uses_fallback(self):
        """Пустая apy_map → все значения из FALLBACK_APY."""
        result_fallback = self.s.compute_weighted_apy(FALLBACK_APY)
        result_empty    = self.s.compute_weighted_apy({})
        self.assertAlmostEqual(result_fallback, result_empty, places=6)

    def test_partial_map_uses_fallback_for_missing(self):
        """Частичная apy_map → fallback для отсутствующих протоколов."""
        apy_map = {"spark_susds": 6.0}
        expected = (
            0.60 * 6.0
            + 0.25 * FALLBACK_APY["fluid_fusdc"]
            + 0.15 * FALLBACK_APY["morpho_steakhouse"]
        )
        self.assertAlmostEqual(self.s.compute_weighted_apy(apy_map), expected, places=6)

    def test_fluid_spike_normalization_applied(self):
        """Fluid APY > 15% нормализуется до 9% в compute_weighted_apy."""
        result = self.s.compute_weighted_apy(APY_MAP_FLUID_SPIKE)
        # fluid_fusdc 20% → нормализуется до 9%
        expected = 0.60 * 5.5 + 0.25 * FLUID_APY_NORMALIZED + 0.15 * 6.5
        self.assertAlmostEqual(result, expected, places=6)

    def test_fluid_exactly_at_threshold_not_normalized(self):
        """Fluid APY = 15.0% (ровно порог) — НЕ нормализуется."""
        apy_map = {"spark_susds": 5.5, "fluid_fusdc": 15.0, "morpho_steakhouse": 6.5}
        result = self.s.compute_weighted_apy(apy_map)
        expected = 0.60 * 5.5 + 0.25 * 15.0 + 0.15 * 6.5
        self.assertAlmostEqual(result, expected, places=6)

    def test_fluid_above_threshold_normalized(self):
        """Fluid APY = 15.01% (выше порога) → нормализуется до 9%."""
        apy_map = {"spark_susds": 5.5, "fluid_fusdc": 15.01, "morpho_steakhouse": 6.5}
        result = self.s.compute_weighted_apy(apy_map)
        expected = 0.60 * 5.5 + 0.25 * FLUID_APY_NORMALIZED + 0.15 * 6.5
        self.assertAlmostEqual(result, expected, places=4)

    def test_all_zero_apy(self):
        """Все APY = 0 → weighted_apy = 0."""
        self.assertAlmostEqual(self.s.compute_weighted_apy(APY_MAP_ZERO), 0.0, places=6)

    def test_equal_apy_preserves_value(self):
        """Все APY одинаковы → weighted_apy = этому значению (веса → 1.0)."""
        apy_map = {"spark_susds": 10.0, "fluid_fusdc": 10.0, "morpho_steakhouse": 10.0}
        self.assertAlmostEqual(self.s.compute_weighted_apy(apy_map), 10.0, places=6)

    def test_spark_dominates_due_to_weight(self):
        """Spark sUSDS имеет наибольший вес 60% — его APY сильнее влияет."""
        # spark=10, fluid=5, morpho=5 → 0.60*10 + 0.25*5 + 0.15*5 = 6+1.25+0.75 = 8.0
        apy_map = {"spark_susds": 10.0, "fluid_fusdc": 5.0, "morpho_steakhouse": 5.0}
        result = self.s.compute_weighted_apy(apy_map)
        self.assertAlmostEqual(result, 8.0, places=6)

    def test_high_apy_map_correct(self):
        """Высокие APY дают соответствующий взвешенный результат."""
        result = self.s.compute_weighted_apy(APY_MAP_HIGH)
        expected = 0.60 * 10.0 + 0.25 * 12.0 + 0.15 * 11.0
        self.assertAlmostEqual(result, expected, places=6)

    def test_returns_float(self):
        """compute_weighted_apy возвращает float."""
        result = self.s.compute_weighted_apy(APY_MAP_STD)
        self.assertIsInstance(result, float)

    def test_weighted_apy_expected_within_tolerance(self):
        """WEIGHTED_APY_EXPECTED в пределах ±0.01 от реального weighted average."""
        s_tmp = S4ConservativeSparkFluid()
        actual = s_tmp.compute_weighted_apy(FALLBACK_APY)
        self.assertAlmostEqual(actual, WEIGHTED_APY_EXPECTED, delta=0.01)


# =============================================================================
# БЛОК 3: TestS4SimulateDay — Симуляция дня
# =============================================================================

class TestS4SimulateDay(unittest.TestCase):

    def setUp(self):
        self.s = S4ConservativeSparkFluid(capital=100_000.0)

    def test_returns_dict(self):
        """simulate_day возвращает dict."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertIsInstance(result, dict)

    def test_has_daily_yield_usd_key(self):
        """Результат содержит ключ daily_yield_usd."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertIn("daily_yield_usd", result)

    def test_has_cumulative_pnl_key(self):
        """Результат содержит ключ cumulative_pnl."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertIn("cumulative_pnl", result)

    def test_has_positions_key(self):
        """Результат содержит ключ positions."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertIn("positions", result)
        self.assertIsInstance(result["positions"], dict)

    def test_has_weighted_apy_key(self):
        """Результат содержит ключ weighted_apy."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertIn("weighted_apy", result)

    def test_positive_yield_with_positive_apy(self):
        """Положительные APY → daily_yield_usd > 0."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertGreater(result["daily_yield_usd"], 0.0)

    def test_zero_yield_with_zero_apy(self):
        """Все APY = 0 → daily_yield_usd = 0."""
        result = self.s.simulate_day(APY_MAP_ZERO)
        self.assertAlmostEqual(result["daily_yield_usd"], 0.0, places=10)

    def test_balance_grows_after_simulate(self):
        """После simulate_day сумма позиций растёт."""
        before = sum(self.s._positions.values())
        self.s.simulate_day(APY_MAP_STD)
        after = sum(self.s._positions.values())
        self.assertGreater(after, before)

    def test_reinvest_yield_to_spark_position(self):
        """Yield реинвестируется — позиция Spark sUSDS становится больше."""
        initial_spark = self.s._positions["spark_susds"]
        self.s.simulate_day(APY_MAP_STD)
        self.assertGreater(self.s._positions["spark_susds"], initial_spark)

    def test_days_simulated_increments(self):
        """simulate_day увеличивает _days_simulated на 1."""
        self.s.simulate_day(APY_MAP_STD)
        self.assertEqual(self.s._days_simulated, 1)

    def test_multiple_calls_accumulate_yield(self):
        """Несколько вызовов накапливают _total_yield_usd монотонно."""
        self.s.simulate_day(APY_MAP_STD)
        y1 = self.s._total_yield_usd
        self.s.simulate_day(APY_MAP_STD)
        y2 = self.s._total_yield_usd
        self.assertGreater(y2, y1)

    def test_cumulative_pnl_equals_total_yield(self):
        """cumulative_pnl совпадает с _total_yield_usd после simulate_day."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertAlmostEqual(result["cumulative_pnl"], self.s._total_yield_usd, places=6)

    def test_yield_formula_exact(self):
        """Точная проверка формулы: yield = Σ pos_i * apy_i / 100 / 365."""
        s = S4ConservativeSparkFluid(capital=100_000.0)
        expected = 0.0
        for protocol, weight in ALLOCATION.items():
            pos = 100_000.0 * weight
            apy = APY_MAP_STD[protocol]
            expected += pos * apy / 100.0 / 365.0
        result = s.simulate_day(APY_MAP_STD)
        self.assertAlmostEqual(result["daily_yield_usd"], expected, places=4)

    def test_equity_history_grows_per_call(self):
        """Каждый вызов simulate_day добавляет точку в _equity_history."""
        self.s.simulate_day(APY_MAP_STD)
        self.assertEqual(len(self.s._equity_history), 1)
        self.s.simulate_day(APY_MAP_STD)
        self.assertEqual(len(self.s._equity_history), 2)


# =============================================================================
# БЛОК 4: TestS4VPortfolioFormat — Формат VPortfolio
# =============================================================================

class TestS4VPortfolioFormat(unittest.TestCase):

    def setUp(self):
        self.s = S4ConservativeSparkFluid(capital=100_000.0)
        self.s.simulate_day(APY_MAP_STD)
        self.d = self.s.to_vportfolio_format()

    def test_has_strategy_id(self):
        """to_vportfolio_format содержит strategy_id = 'S4'."""
        self.assertIn("strategy_id", self.d)
        self.assertEqual(self.d["strategy_id"], "S4")

    def test_has_capital_usd(self):
        """to_vportfolio_format содержит capital_usd = 100K."""
        self.assertIn("capital_usd", self.d)
        self.assertAlmostEqual(self.d["capital_usd"], 100_000.0, places=2)

    def test_has_allocation_key(self):
        """to_vportfolio_format содержит ключ allocation."""
        self.assertIn("allocation", self.d)
        self.assertIsInstance(self.d["allocation"], dict)

    def test_allocation_correct_keys(self):
        """allocation содержит все три протокола."""
        for proto in ["spark_susds", "fluid_fusdc", "morpho_steakhouse"]:
            self.assertIn(proto, self.d["allocation"])

    def test_has_apy_key_with_expected_value(self):
        """to_vportfolio_format содержит apy = WEIGHTED_APY_EXPECTED = 5.9."""
        self.assertIn("apy", self.d)
        self.assertAlmostEqual(self.d["apy"], WEIGHTED_APY_EXPECTED, places=4)

    def test_has_tier_t1t2(self):
        """to_vportfolio_format содержит tier = 'T1+T2'."""
        self.assertIn("tier", self.d)
        self.assertEqual(self.d["tier"], "T1+T2")

    def test_has_status_active(self):
        """to_vportfolio_format содержит status = 'active'."""
        self.assertIn("status", self.d)
        self.assertEqual(self.d["status"], "active")

    def test_has_positions_with_three_protocols(self):
        """to_vportfolio_format содержит positions с тремя протоколами."""
        self.assertIn("positions", self.d)
        for proto in ["spark_susds", "fluid_fusdc", "morpho_steakhouse"]:
            self.assertIn(proto, self.d["positions"])

    def test_has_risk_flags(self):
        """to_vportfolio_format содержит risk_flags."""
        self.assertIn("risk_flags", self.d)
        self.assertIsInstance(self.d["risk_flags"], list)

    def test_has_risk_blended(self):
        """to_vportfolio_format содержит risk_blended ≈ 0.31."""
        self.assertIn("risk_blended", self.d)
        self.assertAlmostEqual(self.d["risk_blended"], RISK_BLENDED, places=4)

    def test_format_is_json_serializable(self):
        """to_vportfolio_format возвращает JSON-сериализуемый dict."""
        json_str = json.dumps(self.d)
        self.assertIsInstance(json_str, str)


# =============================================================================
# БЛОК 5: TestS4RiskFlags — Флаги риска и GSM gate
# =============================================================================

class TestS4RiskFlags(unittest.TestCase):

    def setUp(self):
        self.s = S4ConservativeSparkFluid()

    def test_get_risk_flags_returns_list(self):
        """get_risk_flags() возвращает список."""
        result = self.s.get_risk_flags()
        self.assertIsInstance(result, list)

    def test_fluid_spike_flag_always_present(self):
        """'fluid_spike_normalization' всегда присутствует в risk_flags."""
        self.assertIn("fluid_spike_normalization", self.s.get_risk_flags())

    def test_no_gsm_warning_when_hours_equals_48(self):
        """GSM gate предупреждения НЕТ при gsm_hours = 48.0 (на пороге)."""
        flags = self.s.get_risk_flags(gsm_hours=48.0)
        self.assertNotIn("gsm_gate_warning", flags)

    def test_no_gsm_warning_when_hours_above_48(self):
        """GSM gate предупреждения НЕТ при gsm_hours > 48.0."""
        flags = self.s.get_risk_flags(gsm_hours=72.0)
        self.assertNotIn("gsm_gate_warning", flags)

    def test_gsm_warning_when_hours_zero(self):
        """'gsm_gate_warning' присутствует при gsm_hours = 0."""
        flags = self.s.get_risk_flags(gsm_hours=0)
        self.assertIn("gsm_gate_warning", flags)

    def test_gsm_warning_when_hours_below_threshold(self):
        """'gsm_gate_warning' присутствует при gsm_hours < 48 (например, 24h)."""
        flags = self.s.get_risk_flags(gsm_hours=24.0)
        self.assertIn("gsm_gate_warning", flags)

    def test_gsm_warning_just_below_threshold(self):
        """'gsm_gate_warning' присутствует при gsm_hours = 47.99 (чуть ниже порога)."""
        flags = self.s.get_risk_flags(gsm_hours=47.99)
        self.assertIn("gsm_gate_warning", flags)

    def test_default_no_gsm_warning(self):
        """По умолчанию (gsm_hours=48) предупреждение GSM отсутствует."""
        flags = self.s.get_risk_flags()
        self.assertNotIn("gsm_gate_warning", flags)

    def test_risk_flags_are_strings(self):
        """Все флаги риска — строки."""
        for flag in self.s.get_risk_flags():
            self.assertIsInstance(flag, str)

    def test_get_risk_flags_returns_independent_copy(self):
        """get_risk_flags() возвращает независимую копию — мутация не влияет."""
        flags = self.s.get_risk_flags()
        flags.append("extra_injected_flag")
        self.assertNotIn("extra_injected_flag", self.s.get_risk_flags())


# =============================================================================
# БЛОК 6: TestS4Constants — Проверка констант
# =============================================================================

class TestS4Constants(unittest.TestCase):

    def test_strategy_id_value(self):
        """STRATEGY_ID == 'S4'."""
        self.assertEqual(STRATEGY_ID, "S4")

    def test_strategy_name_value(self):
        """STRATEGY_NAME == 'S4 Conservative Spark+Fluid'."""
        self.assertEqual(STRATEGY_NAME, "S4 Conservative Spark+Fluid")

    def test_tier_value(self):
        """TIER == 'T1+T2'."""
        self.assertEqual(TIER, "T1+T2")

    def test_allocation_spark_weight(self):
        """ALLOCATION['spark_susds'] = 0.60."""
        self.assertAlmostEqual(ALLOCATION["spark_susds"], 0.60, places=9)

    def test_allocation_fluid_weight(self):
        """ALLOCATION['fluid_fusdc'] = 0.25."""
        self.assertAlmostEqual(ALLOCATION["fluid_fusdc"], 0.25, places=9)

    def test_allocation_morpho_weight(self):
        """ALLOCATION['morpho_steakhouse'] = 0.15."""
        self.assertAlmostEqual(ALLOCATION["morpho_steakhouse"], 0.15, places=9)

    def test_allocation_sums_to_one(self):
        """ALLOCATION веса суммируются к 1.0 (покрывают весь капитал)."""
        self.assertAlmostEqual(sum(ALLOCATION.values()), 1.0, places=9)

    def test_fallback_spark_apy(self):
        """FALLBACK_APY['spark_susds'] = 5.5."""
        self.assertAlmostEqual(FALLBACK_APY["spark_susds"], 5.5, places=4)

    def test_fallback_fluid_apy(self):
        """FALLBACK_APY['fluid_fusdc'] = 6.5."""
        self.assertAlmostEqual(FALLBACK_APY["fluid_fusdc"], 6.5, places=4)

    def test_fallback_morpho_apy(self):
        """FALLBACK_APY['morpho_steakhouse'] = 6.5."""
        self.assertAlmostEqual(FALLBACK_APY["morpho_steakhouse"], 6.5, places=4)


# =============================================================================
# БЛОК 7: TestS4EdgeCases — Граничные случаи
# =============================================================================

class TestS4EdgeCases(unittest.TestCase):

    def test_zero_capital_positions_are_zero(self):
        """При capital=0 все позиции = 0."""
        s = S4ConservativeSparkFluid(capital=0.0)
        for val in s._positions.values():
            self.assertEqual(val, 0.0)

    def test_zero_capital_simulate_day_no_error(self):
        """simulate_day с capital=0 не вызывает исключений."""
        s = S4ConservativeSparkFluid(capital=0.0)
        result = s.simulate_day(APY_MAP_STD)
        self.assertIsInstance(result, dict)

    def test_zero_capital_simulate_yields_zero(self):
        """При capital=0 daily_yield_usd = 0.0."""
        s = S4ConservativeSparkFluid(capital=0.0)
        result = s.simulate_day(APY_MAP_STD)
        self.assertAlmostEqual(result["daily_yield_usd"], 0.0, places=10)

    def test_empty_apy_map_no_error(self):
        """Пустая apy_map не вызывает исключений."""
        s = S4ConservativeSparkFluid(capital=100_000.0)
        result = s.simulate_day({})
        self.assertIsInstance(result, dict)

    def test_empty_apy_map_uses_fallback_apy(self):
        """При пустой apy_map используется FALLBACK_APY → тот же yield что с FALLBACK_APY."""
        s_fb = S4ConservativeSparkFluid(capital=100_000.0)
        s_em = S4ConservativeSparkFluid(capital=100_000.0)
        r_fb = s_fb.simulate_day(FALLBACK_APY)
        r_em = s_em.simulate_day({})
        self.assertAlmostEqual(r_fb["daily_yield_usd"], r_em["daily_yield_usd"], places=6)

    def test_negative_apy_skipped(self):
        """Отрицательные APY пропускаются — не уменьшают позицию."""
        s = S4ConservativeSparkFluid(capital=100_000.0)
        before = sum(s._positions.values())
        result = s.simulate_day({
            "spark_susds":       -5.0,
            "fluid_fusdc":       -3.0,
            "morpho_steakhouse": -1.0,
        })
        after = sum(s._positions.values())
        self.assertAlmostEqual(before, after, places=10)
        self.assertAlmostEqual(result["daily_yield_usd"], 0.0, places=10)

    def test_365_day_simulation_no_error(self):
        """365 вызовов simulate_day работают без ошибок."""
        s = S4ConservativeSparkFluid(capital=100_000.0)
        for _ in range(365):
            s.simulate_day(APY_MAP_STD)
        self.assertEqual(s._days_simulated, 365)

    def test_equity_history_ring_buffer_limit(self):
        """Кольцевой буфер _equity_history не превышает 365 точек."""
        s = S4ConservativeSparkFluid(capital=100_000.0)
        for _ in range(400):
            s.simulate_day(APY_MAP_STD)
        self.assertLessEqual(len(s._equity_history), 365)

    def test_large_capital_no_overflow(self):
        """Большой капитал ($1B) работает корректно."""
        s = S4ConservativeSparkFluid(capital=1_000_000_000.0)
        result = s.simulate_day(APY_MAP_STD)
        self.assertGreater(result["daily_yield_usd"], 0.0)
        self.assertTrue(math.isfinite(result["daily_yield_usd"]))

    def test_fluid_spike_in_simulate_day(self):
        """simulate_day: Fluid APY 20% нормализуется до 9% при расчёте yield."""
        s_norm   = S4ConservativeSparkFluid(capital=100_000.0)
        s_spike  = S4ConservativeSparkFluid(capital=100_000.0)
        # С нормализованным (9%) флюидом
        apy_norm = {"spark_susds": 5.5, "fluid_fusdc": 9.0, "morpho_steakhouse": 6.5}
        r_norm   = s_norm.simulate_day(apy_norm)
        # Со спайком (20%) → должен нормализоваться до 9%
        r_spike  = s_spike.simulate_day(APY_MAP_FLUID_SPIKE)
        self.assertAlmostEqual(r_norm["daily_yield_usd"], r_spike["daily_yield_usd"], places=4)


# =============================================================================
# БЛОК 8: TestS4Registry — Регистрация в REGISTRY
# =============================================================================

class TestS4Registry(unittest.TestCase):

    def test_s4_registered_in_registry(self):
        """S4 зарегистрирован в REGISTRY."""
        meta = REGISTRY.get("S4")
        self.assertIsNotNone(meta, "S4 не найден в REGISTRY — авто-регистрация не сработала")

    def test_s4_handler_class_correct(self):
        """handler_class = 'S4ConservativeSparkFluid'."""
        meta = REGISTRY.get("S4")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.handler_class, "S4ConservativeSparkFluid")

    def test_s4_risk_tier_is_t2(self):
        """risk_tier в REGISTRY = 'T2' (ближайший валидный тир для T1+T2 стратегии)."""
        meta = REGISTRY.get("S4")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.risk_tier, "T2")

    def test_s4_enabled(self):
        """S4 стратегия enabled = True."""
        meta = REGISTRY.get("S4")
        self.assertIsNotNone(meta)
        self.assertTrue(meta.enabled)

    def test_s4_instantiable(self):
        """S4ConservativeSparkFluid инстанцируется без ошибок."""
        s = S4ConservativeSparkFluid()
        self.assertIsNotNone(s)
        self.assertEqual(s.strategy_id, "S4")


# =============================================================================
# БЛОК 9: TestS4GetStats — Метод get_stats()
# =============================================================================

class TestS4GetStats(unittest.TestCase):

    def setUp(self):
        self.s = S4ConservativeSparkFluid(capital=100_000.0)

    def test_get_stats_returns_dict(self):
        """get_stats() возвращает dict."""
        stats = self.s.get_stats()
        self.assertIsInstance(stats, dict)

    def test_get_stats_required_keys(self):
        """get_stats() содержит все обязательные ключи."""
        stats = self.s.get_stats()
        required = [
            "strategy_id", "strategy_name", "tier", "capital_usd",
            "current_equity", "days_simulated", "total_yield_usd",
            "weighted_apy_expected", "risk_blended", "risk_flags",
            "allocation", "fallback_apy",
        ]
        for key in required:
            self.assertIn(key, stats, f"get_stats() отсутствует ключ '{key}'")

    def test_get_stats_strategy_id_correct(self):
        """get_stats() strategy_id == 'S4'."""
        self.assertEqual(self.s.get_stats()["strategy_id"], "S4")

    def test_get_stats_weighted_apy_expected(self):
        """get_stats() weighted_apy_expected == 5.9."""
        self.assertAlmostEqual(
            self.s.get_stats()["weighted_apy_expected"], WEIGHTED_APY_EXPECTED, places=4
        )

    def test_get_stats_risk_blended(self):
        """get_stats() risk_blended ≈ 0.31."""
        self.assertAlmostEqual(
            self.s.get_stats()["risk_blended"], RISK_BLENDED, places=4
        )

    def test_get_stats_allocation_correct(self):
        """get_stats() allocation совпадает с ALLOCATION константой."""
        stats = self.s.get_stats()
        self.assertEqual(stats["allocation"], dict(ALLOCATION))

    def test_get_stats_after_simulate_day(self):
        """get_stats() корректен после вызова simulate_day."""
        self.s.simulate_day(APY_MAP_STD)
        stats = self.s.get_stats()
        self.assertEqual(stats["days_simulated"], 1)
        self.assertGreater(stats["total_yield_usd"], 0.0)


# ─── Точка входа ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    unittest.main(verbosity=2)
