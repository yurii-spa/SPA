"""
spa_core/tests/test_s2_pendle_morpho.py — MP-380

75+ unittest-кейсов для стратегии S2 Pendle PT + Morpho Heavy.

Классы тестов:
  - TestS2Init (8)         — id, name, tier, allocation values, risk_flags
  - TestS2WeightedAPY (12) — с apy_map, с fallback, partial map, edge cases
  - TestS2SimulateDay (12) — returns dict, yield positive, balance grows, reinvest
  - TestS2VPortfolioFormat (10) — ключи: strategy_id, allocation, apy, tier
  - TestS2Registry (5)     — S2 зарегистрирован, инстанцируемый
  - TestS2RiskFlags (8)    — maturity_risk и t2_liquidity_risk присутствуют
  - TestS2Constants (10)   — все константы верные значения
  - TestS2EdgeCases (10)   — zero capital, empty apy_map, негативные входы

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
from spa_core.strategies.s2_pendle_morpho import (
    S2PendleMorpho,
    STRATEGY_ID,
    STRATEGY_NAME,
    TIER,
    ALLOCATION,
    FALLBACK_APY,
    WEIGHTED_APY_EXPECTED,
    RISK_FLAGS,
    TARGET_APY_MIN,
    TARGET_APY_MAX,
)
from spa_core.strategies.strategy_registry import REGISTRY


# ─── Вспомогательные данные ───────────────────────────────────────────────────

# Стандартная apy_map с дефолтными значениями
APY_MAP_STD = {
    "pendle_pt":         8.0,
    "morpho_steakhouse": 6.5,
    "compound_v3":       4.8,
}

# APY_MAP с высокими значениями
APY_MAP_HIGH = {
    "pendle_pt":         15.0,
    "morpho_steakhouse": 12.0,
    "compound_v3":       10.0,
}

# APY_MAP с нулями
APY_MAP_ZERO = {
    "pendle_pt":         0.0,
    "morpho_steakhouse": 0.0,
    "compound_v3":       0.0,
}

# Частичная APY_MAP (только один протокол)
APY_MAP_PARTIAL = {"pendle_pt": 9.0}


# =============================================================================
# БЛОК 1: TestS2Init — Инициализация
# =============================================================================

class TestS2Init(unittest.TestCase):

    def test_strategy_id_correct(self):
        """strategy_id == 'S2'."""
        s = S2PendleMorpho()
        self.assertEqual(s.strategy_id, "S2")

    def test_strategy_name_correct(self):
        """strategy_name == 'Pendle PT + Morpho Heavy'."""
        s = S2PendleMorpho()
        self.assertEqual(s.strategy_name, "Pendle PT + Morpho Heavy")

    def test_tier_is_t2(self):
        """tier == 'T2' (Pendle PT определяет тир)."""
        s = S2PendleMorpho()
        self.assertEqual(s.tier, "T2")

    def test_allocation_pendle_50pct(self):
        """Pendle PT аллокация = 50% от капитала при инициализации."""
        s = S2PendleMorpho(capital=100_000.0)
        self.assertAlmostEqual(s._positions["pendle_pt"], 50_000.0, places=4)

    def test_allocation_morpho_35pct(self):
        """Morpho Steakhouse аллокация = 35% от капитала."""
        s = S2PendleMorpho(capital=100_000.0)
        self.assertAlmostEqual(s._positions["morpho_steakhouse"], 35_000.0, places=4)

    def test_allocation_compound_15pct(self):
        """Compound V3 аллокация = 15% от капитала."""
        s = S2PendleMorpho(capital=100_000.0)
        self.assertAlmostEqual(s._positions["compound_v3"], 15_000.0, places=4)

    def test_initial_days_simulated_zero(self):
        """Начальный счётчик дней = 0."""
        s = S2PendleMorpho()
        self.assertEqual(s._days_simulated, 0)

    def test_initial_total_yield_zero(self):
        """Начальный total_yield_usd = 0.0."""
        s = S2PendleMorpho()
        self.assertEqual(s._total_yield_usd, 0.0)


# =============================================================================
# БЛОК 2: TestS2WeightedAPY — Взвешенный APY
# =============================================================================

class TestS2WeightedAPY(unittest.TestCase):

    def setUp(self):
        self.s = S2PendleMorpho()

    def test_with_default_apy_map(self):
        """Взвешенный APY с дефолтными значениями ≈ 7.0%."""
        result = self.s.compute_weighted_apy(APY_MAP_STD)
        expected = 0.50 * 8.0 + 0.35 * 6.5 + 0.15 * 4.8
        self.assertAlmostEqual(result, expected, places=6)

    def test_default_apy_equals_weighted_apy_expected(self):
        """compute_weighted_apy(FALLBACK_APY) ≈ WEIGHTED_APY_EXPECTED = 7.0 (±0.01%)."""
        result = self.s.compute_weighted_apy(FALLBACK_APY)
        # 0.50*8.0 + 0.35*6.5 + 0.15*4.8 = 6.995 ≈ 7.0 (WEIGHTED_APY_EXPECTED — округлённое)
        self.assertAlmostEqual(result, WEIGHTED_APY_EXPECTED, delta=0.01)

    def test_formula_exact_value(self):
        """Проверка точного числа: 0.50*8.0 + 0.35*6.5 + 0.15*4.8 = 6.995."""
        result = self.s.compute_weighted_apy(APY_MAP_STD)
        self.assertAlmostEqual(result, 6.995, places=5)

    def test_with_empty_map_uses_fallback(self):
        """Пустая apy_map → все значения из FALLBACK_APY."""
        result_fallback = self.s.compute_weighted_apy(FALLBACK_APY)
        result_empty    = self.s.compute_weighted_apy({})
        self.assertAlmostEqual(result_fallback, result_empty, places=6)

    def test_partial_map_uses_fallback_for_missing(self):
        """Частичная apy_map → fallback для отсутствующих протоколов."""
        apy_map = {"pendle_pt": 9.0}  # morpho и compound не переданы
        expected = (
            0.50 * 9.0
            + 0.35 * FALLBACK_APY["morpho_steakhouse"]
            + 0.15 * FALLBACK_APY["compound_v3"]
        )
        self.assertAlmostEqual(self.s.compute_weighted_apy(apy_map), expected, places=6)

    def test_all_zero_apy(self):
        """Все APY = 0 → weighted_apy = 0."""
        self.assertAlmostEqual(self.s.compute_weighted_apy(APY_MAP_ZERO), 0.0, places=6)

    def test_equal_apy_preserves_value(self):
        """Все APY одинаковы → weighted_apy = этому значению (веса суммируются к 1)."""
        apy_map = {"pendle_pt": 10.0, "morpho_steakhouse": 10.0, "compound_v3": 10.0}
        self.assertAlmostEqual(self.s.compute_weighted_apy(apy_map), 10.0, places=6)

    def test_high_apy_map(self):
        """Высокие APY дают соответствующий взвешенный результат."""
        result = self.s.compute_weighted_apy(APY_MAP_HIGH)
        expected = 0.50 * 15.0 + 0.35 * 12.0 + 0.15 * 10.0
        self.assertAlmostEqual(result, expected, places=6)

    def test_pendle_dominates_due_to_weight(self):
        """Pendle PT имеет наибольший вес 50% — его APY сильнее влияет."""
        # pendle=10, morpho=5, compound=5 → 0.50*10 + 0.35*5 + 0.15*5 = 5+1.75+0.75 = 7.5
        apy_map = {"pendle_pt": 10.0, "morpho_steakhouse": 5.0, "compound_v3": 5.0}
        result = self.s.compute_weighted_apy(apy_map)
        self.assertAlmostEqual(result, 7.5, places=6)

    def test_custom_apy_formula(self):
        """Произвольные значения — формула работает корректно."""
        apy_map = {"pendle_pt": 6.0, "morpho_steakhouse": 7.0, "compound_v3": 5.0}
        expected = 0.50 * 6.0 + 0.35 * 7.0 + 0.15 * 5.0
        self.assertAlmostEqual(self.s.compute_weighted_apy(apy_map), expected, places=6)

    def test_allocation_weights_sum_to_one(self):
        """ALLOCATION веса суммируются к 1.0 (покрывают весь капитал)."""
        self.assertAlmostEqual(sum(ALLOCATION.values()), 1.0, places=9)

    def test_returns_float(self):
        """compute_weighted_apy возвращает float."""
        result = self.s.compute_weighted_apy(APY_MAP_STD)
        self.assertIsInstance(result, float)


# =============================================================================
# БЛОК 3: TestS2SimulateDay — Симуляция дня
# =============================================================================

class TestS2SimulateDay(unittest.TestCase):

    def setUp(self):
        self.s = S2PendleMorpho(capital=100_000.0)

    def test_returns_dict(self):
        """simulate_day возвращает dict."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertIsInstance(result, dict)

    def test_has_daily_yield_usd_key(self):
        """Результат содержит ключ daily_yield_usd."""
        result = self.s.simulate_day(APY_MAP_STD)
        self.assertIn("daily_yield_usd", result)

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

    def test_reinvest_yield_to_position(self):
        """Yield реинвестируется — позиция Pendle PT становится больше."""
        initial_pendle = self.s._positions["pendle_pt"]
        self.s.simulate_day(APY_MAP_STD)
        self.assertGreater(self.s._positions["pendle_pt"], initial_pendle)

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

    def test_yield_formula_exact(self):
        """Точная проверка формулы: yield = Σ pos_i * apy_i / 100 / 365."""
        s = S2PendleMorpho(capital=100_000.0)
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
# БЛОК 4: TestS2VPortfolioFormat — Формат VPortfolio
# =============================================================================

class TestS2VPortfolioFormat(unittest.TestCase):

    def setUp(self):
        self.s = S2PendleMorpho(capital=100_000.0)
        self.s.simulate_day(APY_MAP_STD)
        self.d = self.s.to_vportfolio_format()

    def test_has_strategy_id(self):
        """to_vportfolio_format содержит strategy_id = 'S2'."""
        self.assertIn("strategy_id", self.d)
        self.assertEqual(self.d["strategy_id"], "S2")

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
        for proto in ["pendle_pt", "morpho_steakhouse", "compound_v3"]:
            self.assertIn(proto, self.d["allocation"])

    def test_has_apy_key(self):
        """to_vportfolio_format содержит ключ apy = WEIGHTED_APY_EXPECTED."""
        self.assertIn("apy", self.d)
        self.assertAlmostEqual(self.d["apy"], WEIGHTED_APY_EXPECTED, places=4)

    def test_has_tier_t2(self):
        """to_vportfolio_format содержит tier = 'T2'."""
        self.assertIn("tier", self.d)
        self.assertEqual(self.d["tier"], "T2")

    def test_has_status_active(self):
        """to_vportfolio_format содержит status = 'active'."""
        self.assertIn("status", self.d)
        self.assertEqual(self.d["status"], "active")

    def test_has_positions_with_three_protocols(self):
        """to_vportfolio_format содержит positions с тремя протоколами."""
        self.assertIn("positions", self.d)
        for proto in ["pendle_pt", "morpho_steakhouse", "compound_v3"]:
            self.assertIn(proto, self.d["positions"])

    def test_has_risk_flags(self):
        """to_vportfolio_format содержит risk_flags."""
        self.assertIn("risk_flags", self.d)
        self.assertIsInstance(self.d["risk_flags"], list)

    def test_format_is_json_serializable(self):
        """to_vportfolio_format возвращает JSON-сериализуемый dict."""
        json_str = json.dumps(self.d)
        self.assertIsInstance(json_str, str)


# =============================================================================
# БЛОК 5: TestS2Registry — Регистрация в REGISTRY
# =============================================================================

class TestS2Registry(unittest.TestCase):

    def test_s2_registered_in_registry(self):
        """S2 зарегистрирован в REGISTRY (spa_core.strategies.strategy_registry)."""
        meta = REGISTRY.get("S2")
        self.assertIsNotNone(meta, "S2 не найден в REGISTRY — авто-регистрация не сработала")

    def test_s2_handler_class_correct(self):
        """handler_class = 'S2PendleMorpho'."""
        meta = REGISTRY.get("S2")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.handler_class, "S2PendleMorpho")

    def test_s2_risk_tier_is_t2(self):
        """risk_tier = 'T2' в REGISTRY."""
        meta = REGISTRY.get("S2")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.risk_tier, "T2")

    def test_s2_enabled(self):
        """S2 стратегия enabled = True."""
        meta = REGISTRY.get("S2")
        self.assertIsNotNone(meta)
        self.assertTrue(meta.enabled)

    def test_s2_instantiable(self):
        """S2PendleMorpho инстанцируется без ошибок."""
        s = S2PendleMorpho()
        self.assertIsNotNone(s)
        self.assertEqual(s.strategy_id, "S2")


# =============================================================================
# БЛОК 6: TestS2RiskFlags — Флаги риска
# =============================================================================

class TestS2RiskFlags(unittest.TestCase):

    def setUp(self):
        self.s = S2PendleMorpho()

    def test_get_risk_flags_returns_list(self):
        """get_risk_flags() возвращает список."""
        result = self.s.get_risk_flags()
        self.assertIsInstance(result, list)

    def test_pendle_maturity_risk_present(self):
        """'pendle_maturity_risk' присутствует в risk_flags."""
        self.assertIn("pendle_maturity_risk", self.s.get_risk_flags())

    def test_t2_liquidity_risk_present(self):
        """'t2_liquidity_risk' присутствует в risk_flags."""
        self.assertIn("t2_liquidity_risk", self.s.get_risk_flags())

    def test_risk_flags_count_is_two(self):
        """Количество флагов риска = 2."""
        self.assertEqual(len(self.s.get_risk_flags()), 2)

    def test_risk_flags_are_strings(self):
        """Все флаги риска — строки."""
        for flag in self.s.get_risk_flags():
            self.assertIsInstance(flag, str)

    def test_risk_flags_constant_matches(self):
        """RISK_FLAGS константа совпадает с get_risk_flags()."""
        self.assertEqual(self.s.get_risk_flags(), RISK_FLAGS)

    def test_get_risk_flags_returns_copy(self):
        """get_risk_flags() возвращает независимую копию — мутация не влияет."""
        flags = self.s.get_risk_flags()
        flags.append("extra_flag")
        self.assertNotIn("extra_flag", self.s.get_risk_flags())

    def test_risk_flags_match_vportfolio(self):
        """risk_flags в to_vportfolio_format() совпадают с get_risk_flags()."""
        vp = self.s.to_vportfolio_format()
        self.assertEqual(vp["risk_flags"], self.s.get_risk_flags())


# =============================================================================
# БЛОК 7: TestS2Constants — Проверка констант
# =============================================================================

class TestS2Constants(unittest.TestCase):

    def test_strategy_id_value(self):
        """STRATEGY_ID == 'S2'."""
        self.assertEqual(STRATEGY_ID, "S2")

    def test_strategy_name_value(self):
        """STRATEGY_NAME == 'Pendle PT + Morpho Heavy'."""
        self.assertEqual(STRATEGY_NAME, "Pendle PT + Morpho Heavy")

    def test_tier_value(self):
        """TIER == 'T2'."""
        self.assertEqual(TIER, "T2")

    def test_allocation_pendle_weight(self):
        """ALLOCATION['pendle_pt'] = 0.50."""
        self.assertAlmostEqual(ALLOCATION["pendle_pt"], 0.50, places=9)

    def test_allocation_morpho_weight(self):
        """ALLOCATION['morpho_steakhouse'] = 0.35."""
        self.assertAlmostEqual(ALLOCATION["morpho_steakhouse"], 0.35, places=9)

    def test_allocation_compound_weight(self):
        """ALLOCATION['compound_v3'] = 0.15."""
        self.assertAlmostEqual(ALLOCATION["compound_v3"], 0.15, places=9)

    def test_fallback_pendle_apy(self):
        """FALLBACK_APY['pendle_pt'] = 8.0."""
        self.assertAlmostEqual(FALLBACK_APY["pendle_pt"], 8.0, places=4)

    def test_fallback_morpho_apy(self):
        """FALLBACK_APY['morpho_steakhouse'] = 6.5."""
        self.assertAlmostEqual(FALLBACK_APY["morpho_steakhouse"], 6.5, places=4)

    def test_fallback_compound_apy(self):
        """FALLBACK_APY['compound_v3'] = 4.8."""
        self.assertAlmostEqual(FALLBACK_APY["compound_v3"], 4.8, places=4)

    def test_weighted_apy_expected(self):
        """WEIGHTED_APY_EXPECTED = 7.0."""
        self.assertAlmostEqual(WEIGHTED_APY_EXPECTED, 7.0, places=4)


# =============================================================================
# БЛОК 8: TestS2EdgeCases — Граничные случаи
# =============================================================================

class TestS2EdgeCases(unittest.TestCase):

    def test_zero_capital_positions_are_zero(self):
        """При capital=0 все позиции = 0."""
        s = S2PendleMorpho(capital=0.0)
        for val in s._positions.values():
            self.assertEqual(val, 0.0)

    def test_zero_capital_simulate_day_no_error(self):
        """simulate_day с capital=0 не вызывает исключений."""
        s = S2PendleMorpho(capital=0.0)
        result = s.simulate_day(APY_MAP_STD)
        self.assertIsInstance(result, dict)

    def test_zero_capital_simulate_yields_zero(self):
        """При capital=0 daily_yield_usd = 0.0."""
        s = S2PendleMorpho(capital=0.0)
        result = s.simulate_day(APY_MAP_STD)
        self.assertAlmostEqual(result["daily_yield_usd"], 0.0, places=10)

    def test_empty_apy_map_no_error(self):
        """Пустая apy_map не вызывает исключений."""
        s = S2PendleMorpho(capital=100_000.0)
        result = s.simulate_day({})
        self.assertIsInstance(result, dict)

    def test_empty_apy_map_uses_fallback_apy(self):
        """При пустой apy_map используется FALLBACK_APY → тот же yield, что с FALLBACK_APY."""
        s_fb = S2PendleMorpho(capital=100_000.0)
        s_em = S2PendleMorpho(capital=100_000.0)
        r_fb = s_fb.simulate_day(FALLBACK_APY)
        r_em = s_em.simulate_day({})
        self.assertAlmostEqual(r_fb["daily_yield_usd"], r_em["daily_yield_usd"], places=6)

    def test_negative_apy_skipped(self):
        """Отрицательные APY пропускаются — не уменьшают позицию."""
        s = S2PendleMorpho(capital=100_000.0)
        before = sum(s._positions.values())
        result = s.simulate_day({
            "pendle_pt": -5.0,
            "morpho_steakhouse": -3.0,
            "compound_v3": -1.0,
        })
        after = sum(s._positions.values())
        self.assertAlmostEqual(before, after, places=10)
        self.assertAlmostEqual(result["daily_yield_usd"], 0.0, places=10)

    def test_365_day_simulation_no_error(self):
        """365 вызовов simulate_day работают без ошибок."""
        s = S2PendleMorpho(capital=100_000.0)
        for _ in range(365):
            s.simulate_day(APY_MAP_STD)
        self.assertEqual(s._days_simulated, 365)

    def test_equity_history_ring_buffer_limit(self):
        """Кольцевой буфер _equity_history не превышает 365 точек."""
        s = S2PendleMorpho(capital=100_000.0)
        for _ in range(400):
            s.simulate_day(APY_MAP_STD)
        self.assertLessEqual(len(s._equity_history), 365)

    def test_large_capital_no_overflow(self):
        """Большой капитал ($1B) работает корректно."""
        s = S2PendleMorpho(capital=1_000_000_000.0)
        result = s.simulate_day(APY_MAP_STD)
        self.assertGreater(result["daily_yield_usd"], 0.0)
        self.assertTrue(math.isfinite(result["daily_yield_usd"]))

    def test_get_stats_returns_dict(self):
        """get_stats() возвращает dict со всеми обязательными полями."""
        s = S2PendleMorpho(capital=100_000.0)
        stats = s.get_stats()
        self.assertIsInstance(stats, dict)
        for key in ["strategy_id", "strategy_name", "tier", "capital_usd",
                    "current_equity", "days_simulated", "total_yield_usd",
                    "weighted_apy_expected", "risk_flags", "allocation", "fallback_apy"]:
            self.assertIn(key, stats, f"get_stats() отсутствует ключ '{key}'")


# ─── Точка входа ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    unittest.main(verbosity=2)
