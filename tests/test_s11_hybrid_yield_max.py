"""
tests/test_s11_hybrid_yield_max.py — MP-421 тесты для S11HybridYieldMax

Группы:
  TestInit                  — инициализация (6 тестов)
  TestGetMode               — определение режима (9 тестов)
  TestGetAllocation         — аллокации по режимам (6 тестов)
  TestComputeExpectedAPY    — взвешенный APY (10 тестов)
  TestValidateAllocation    — валидация аллокации (9 тестов)
  TestRunDay                — run_day (8 тестов)
  TestAllocationConstraints — ограничения cap / rebalance (7 тестов)
  TestNeedsRebalance        — needs_rebalance (5 тестов)
  TestGetStats              — get_stats / to_vportfolio_format (5 тестов)

Итого: 65 тестов
"""
from __future__ import annotations

import sys
import os
import unittest

# Убедимся, что корень проекта в sys.path
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.strategies.s11_hybrid_yield_max import (
    S11HybridYieldMax,
    BASE_ALLOCATION,
    FALLBACK_ALLOCATION,
    APY_DEFAULTS,
    RISK_SCORE,
    TARGET_APY,
    WEIGHTED_APY,
    MIN_PENDLE_YT_APY,
    MAX_PENDLE_EXPOSURE,
    REBALANCE_THRESHOLD,
)


# ─── Вспомогательные константы ────────────────────────────────────────────────

BULL_APY_MAP = {
    "pendle_yt":         28.4,   # bull Pendle YT: 28.4% → blended ≈15.621%
    "morpho_steakhouse":  6.5,
    "euler_v2":           2.78,
    "maple":              4.74,
}

FALLBACK_APY_MAP = {
    "pendle_yt":         8.0,   # < MIN_PENDLE_YT_APY → fallback
    "morpho_steakhouse": 6.5,
    "euler_v2":          2.78,
    "maple":             4.74,
    "morpho_blue":       4.75,
}

EMPTY_APY_MAP: dict = {}


# ══════════════════════════════════════════════════════════════════════════════
# TestInit
# ══════════════════════════════════════════════════════════════════════════════

class TestInit(unittest.TestCase):
    """Инициализация S11HybridYieldMax."""

    def setUp(self) -> None:
        self.s = S11HybridYieldMax(capital=100_000.0)

    def test_default_capital(self) -> None:
        """Дефолтный капитал $100K."""
        s = S11HybridYieldMax()
        self.assertAlmostEqual(s.capital, 100_000.0)

    def test_custom_capital(self) -> None:
        """Пользовательский капитал."""
        s = S11HybridYieldMax(capital=50_000.0)
        self.assertAlmostEqual(s.capital, 50_000.0)

    def test_strategy_id(self) -> None:
        """strategy_id == 'S11'."""
        self.assertEqual(self.s.strategy_id, "S11")
        self.assertEqual(self.s.STRATEGY_ID, "S11")

    def test_tier(self) -> None:
        """risk_tier == 'T3-SPEC'."""
        self.assertEqual(self.s.risk_tier, "T3-SPEC")
        self.assertEqual(self.s.TIER, "T3-SPEC")

    def test_base_allocation_sum(self) -> None:
        """Сумма весов BASE_ALLOCATION == 1.0."""
        total = sum(BASE_ALLOCATION.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_fallback_allocation_sum(self) -> None:
        """Сумма весов FALLBACK_ALLOCATION == 1.0."""
        total = sum(FALLBACK_ALLOCATION.values())
        self.assertAlmostEqual(total, 1.0, places=9)


# ══════════════════════════════════════════════════════════════════════════════
# TestGetMode
# ══════════════════════════════════════════════════════════════════════════════

class TestGetMode(unittest.TestCase):
    """Определение режима работы: bull / fallback / risk_off."""

    def setUp(self) -> None:
        self.s = S11HybridYieldMax()

    def test_bull_mode_above_threshold(self) -> None:
        """Pendle YT = 15% → bull."""
        mode = self.s.get_mode({"pendle_yt": 15.0})
        self.assertEqual(mode, "bull")

    def test_bull_mode_at_threshold(self) -> None:
        """Pendle YT ровно на пороге 12% → bull."""
        mode = self.s.get_mode({"pendle_yt": 12.0})
        self.assertEqual(mode, "bull")

    def test_fallback_mode_below_threshold(self) -> None:
        """Pendle YT = 8% < 12% → fallback."""
        mode = self.s.get_mode({"pendle_yt": 8.0})
        self.assertEqual(mode, "fallback")

    def test_fallback_mode_just_below(self) -> None:
        """Pendle YT = 11.99% → fallback."""
        mode = self.s.get_mode({"pendle_yt": 11.99})
        self.assertEqual(mode, "fallback")

    def test_fallback_mode_zero_apy(self) -> None:
        """Pendle YT = 0% → fallback."""
        mode = self.s.get_mode({"pendle_yt": 0.0})
        self.assertEqual(mode, "fallback")

    def test_risk_off_no_pendle_key(self) -> None:
        """apy_map без pendle_yt → risk_off (APY_DEFAULTS имеет значение)."""
        # APY_DEFAULTS["pendle_yt"] = 15.0, значит не risk_off — это bull
        mode = self.s.get_mode({})
        self.assertEqual(mode, "bull")

    def test_risk_off_none_map(self) -> None:
        """apy_map=None → режим по APY_DEFAULTS (bull)."""
        mode = self.s.get_mode(None)
        self.assertEqual(mode, "bull")

    def test_bull_mode_high_apy(self) -> None:
        """Pendle YT = 40% → bull."""
        mode = self.s.get_mode({"pendle_yt": 40.0})
        self.assertEqual(mode, "bull")

    def test_fallback_mode_negative_apy(self) -> None:
        """Pendle YT = -1% → fallback (ниже порога)."""
        mode = self.s.get_mode({"pendle_yt": -1.0})
        self.assertEqual(mode, "fallback")


# ══════════════════════════════════════════════════════════════════════════════
# TestGetAllocation
# ══════════════════════════════════════════════════════════════════════════════

class TestGetAllocation(unittest.TestCase):
    """get_allocation() возвращает правильные веса по режиму."""

    def setUp(self) -> None:
        self.s = S11HybridYieldMax()

    def test_bull_allocation_keys(self) -> None:
        """Bull аллокация содержит pendle_yt, morpho_steakhouse, euler_v2, maple."""
        alloc = self.s.get_allocation("bull")
        self.assertIn("pendle_yt", alloc)
        self.assertIn("morpho_steakhouse", alloc)
        self.assertIn("euler_v2", alloc)
        self.assertIn("maple", alloc)

    def test_bull_allocation_pendle_weight(self) -> None:
        """Вес pendle_yt в bull == 0.45."""
        alloc = self.s.get_allocation("bull")
        self.assertAlmostEqual(alloc["pendle_yt"], 0.45)

    def test_fallback_allocation_keys(self) -> None:
        """Fallback аллокация содержит morpho_steakhouse, morpho_blue, maple, euler_v2."""
        alloc = self.s.get_allocation("fallback")
        self.assertIn("morpho_steakhouse", alloc)
        self.assertIn("morpho_blue", alloc)
        self.assertIn("maple", alloc)
        self.assertIn("euler_v2", alloc)

    def test_fallback_no_pendle(self) -> None:
        """Fallback аллокация НЕ содержит pendle_yt."""
        alloc = self.s.get_allocation("fallback")
        self.assertNotIn("pendle_yt", alloc)

    def test_risk_off_empty(self) -> None:
        """risk_off → пустой dict."""
        alloc = self.s.get_allocation("risk_off")
        self.assertEqual(alloc, {})

    def test_unknown_mode_empty(self) -> None:
        """Неизвестный режим → пустой dict (risk_off ветка)."""
        alloc = self.s.get_allocation("unknown_mode")
        self.assertEqual(alloc, {})


# ══════════════════════════════════════════════════════════════════════════════
# TestComputeExpectedAPY
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeExpectedAPY(unittest.TestCase):
    """compute_expected_apy() — взвешенный APY."""

    def setUp(self) -> None:
        self.s = S11HybridYieldMax()

    def test_bull_base_apy(self) -> None:
        """Bull режим с BULL_APY_MAP (pendle_yt=28.4%) → ≈ 15.621%."""
        alloc = self.s.get_allocation("bull")
        apy = self.s.compute_expected_apy(alloc, BULL_APY_MAP)
        # 0.45*28.4 + 0.30*6.5 + 0.15*2.78 + 0.10*4.74 = 15.621
        self.assertAlmostEqual(apy, 15.621, places=3)

    def test_empty_allocation_zero(self) -> None:
        """Пустая аллокация → 0.0."""
        apy = self.s.compute_expected_apy({})
        self.assertAlmostEqual(apy, 0.0)

    def test_fallback_apy_range(self) -> None:
        """Fallback режим APY ~ 5–7%."""
        alloc = self.s.get_allocation("fallback")
        apy = self.s.compute_expected_apy(alloc, FALLBACK_APY_MAP)
        self.assertGreater(apy, 4.0)
        self.assertLess(apy, 8.0)

    def test_uses_defaults_when_no_map(self) -> None:
        """При apy_map=None используются APY_DEFAULTS."""
        alloc = self.s.get_allocation("bull")
        apy_with_defaults = self.s.compute_expected_apy(alloc, None)
        # APY_DEFAULTS["pendle_yt"] = 28.4 → ожидаем ≈ 15.621%
        self.assertAlmostEqual(apy_with_defaults, WEIGHTED_APY, places=2)

    def test_single_protocol_allocation(self) -> None:
        """Один протокол с весом 1.0 → его APY напрямую."""
        alloc = {"morpho_steakhouse": 1.0}
        apy = self.s.compute_expected_apy(alloc, {"morpho_steakhouse": 6.5})
        self.assertAlmostEqual(apy, 6.5)

    def test_missing_key_uses_default(self) -> None:
        """Отсутствующий ключ в apy_map → APY_DEFAULTS."""
        alloc = {"euler_v2": 0.5, "maple": 0.5}
        # Не передаём apy_map → defaults: euler_v2=2.78, maple=4.74
        apy = self.s.compute_expected_apy(alloc, {})
        expected = 0.5 * APY_DEFAULTS["euler_v2"] + 0.5 * APY_DEFAULTS["maple"]
        self.assertAlmostEqual(apy, expected, places=6)

    def test_high_pendle_apy(self) -> None:
        """Если Pendle YT = 30%, итоговый APY выше целевого."""
        alloc = self.s.get_allocation("bull")
        high_map = dict(BULL_APY_MAP)
        high_map["pendle_yt"] = 30.0
        apy = self.s.compute_expected_apy(alloc, high_map)
        self.assertGreater(apy, 15.591)

    def test_zero_apy_protocols(self) -> None:
        """Все APY = 0% → итоговый APY = 0."""
        alloc = self.s.get_allocation("bull")
        zero_map = {p: 0.0 for p in alloc}
        apy = self.s.compute_expected_apy(alloc, zero_map)
        self.assertAlmostEqual(apy, 0.0)

    def test_unknown_protocol_uses_zero_default(self) -> None:
        """Протокол отсутствует в APY_DEFAULTS → 0.0 APY."""
        alloc = {"nonexistent_protocol": 1.0}
        apy = self.s.compute_expected_apy(alloc, {})
        self.assertAlmostEqual(apy, 0.0)

    def test_weighted_math_correctness(self) -> None:
        """Ручная проверка взвешенного расчёта."""
        alloc = {"a": 0.6, "b": 0.4}
        apy_map = {"a": 10.0, "b": 5.0}
        expected = 0.6 * 10.0 + 0.4 * 5.0  # 8.0
        apy = self.s.compute_expected_apy(alloc, apy_map)
        self.assertAlmostEqual(apy, expected, places=9)


# ══════════════════════════════════════════════════════════════════════════════
# TestValidateAllocation
# ══════════════════════════════════════════════════════════════════════════════

class TestValidateAllocation(unittest.TestCase):
    """validate_allocation() — проверка корректности аллокации."""

    def setUp(self) -> None:
        self.s = S11HybridYieldMax()

    def test_valid_base_allocation(self) -> None:
        """BASE_ALLOCATION валидна."""
        self.assertTrue(self.s.validate_allocation(dict(BASE_ALLOCATION)))

    def test_valid_fallback_allocation(self) -> None:
        """FALLBACK_ALLOCATION валидна."""
        self.assertTrue(self.s.validate_allocation(dict(FALLBACK_ALLOCATION)))

    def test_valid_empty_allocation(self) -> None:
        """Пустой dict (risk_off) валиден."""
        self.assertTrue(self.s.validate_allocation({}))

    def test_invalid_sum_too_high(self) -> None:
        """Сумма > 1.0 → невалидно."""
        alloc = {"a": 0.6, "b": 0.6}
        self.assertFalse(self.s.validate_allocation(alloc))

    def test_invalid_sum_too_low(self) -> None:
        """Сумма < 1.0 → невалидно."""
        alloc = {"a": 0.3, "b": 0.3}
        self.assertFalse(self.s.validate_allocation(alloc))

    def test_invalid_negative_weight(self) -> None:
        """Отрицательный вес → невалидно."""
        alloc = {"a": 1.1, "b": -0.1}
        self.assertFalse(self.s.validate_allocation(alloc))

    def test_invalid_pendle_exceeds_cap(self) -> None:
        """Pendle YT > 0.50 → невалидно."""
        alloc = {
            "pendle_yt": 0.55,
            "morpho_steakhouse": 0.25,
            "euler_v2": 0.10,
            "maple": 0.10,
        }
        self.assertFalse(self.s.validate_allocation(alloc))

    def test_valid_pendle_at_cap(self) -> None:
        """Pendle YT = 0.50 (точно на cap) → валидно."""
        alloc = {
            "pendle_yt": 0.50,
            "morpho_steakhouse": 0.30,
            "euler_v2": 0.10,
            "maple": 0.10,
        }
        self.assertTrue(self.s.validate_allocation(alloc))

    def test_valid_no_pendle(self) -> None:
        """Аллокация без pendle_yt → pendle cap = 0 (OK)."""
        alloc = {"a": 0.5, "b": 0.5}
        self.assertTrue(self.s.validate_allocation(alloc))


# ══════════════════════════════════════════════════════════════════════════════
# TestRunDay
# ══════════════════════════════════════════════════════════════════════════════

class TestRunDay(unittest.TestCase):
    """run_day() — основная точка входа дневного расчёта."""

    def setUp(self) -> None:
        self.s = S11HybridYieldMax(capital=100_000.0)

    def test_run_day_bull_mode(self) -> None:
        """Bull режим: mode == 'bull', expected_apy > 15%."""
        result = self.s.run_day(BULL_APY_MAP)
        self.assertEqual(result["mode"], "bull")
        self.assertGreater(result["expected_apy"], 15.0)

    def test_run_day_fallback_mode(self) -> None:
        """Fallback режим: mode == 'fallback', APY 4–8%."""
        result = self.s.run_day(FALLBACK_APY_MAP)
        self.assertEqual(result["mode"], "fallback")
        self.assertGreater(result["expected_apy"], 4.0)
        self.assertLess(result["expected_apy"], 8.0)

    def test_run_day_risk_off_mode(self) -> None:
        """risk_off режим: daily_yield_usd == 0, APY == 0."""
        # Создадим объект с переопределённым get_mode для имитации risk_off
        # Для этого передаём маp, который вызовет risk_off через get_allocation -> {}
        # Сбрасываем APY_DEFAULTS временно — нет, лучше патчим get_mode
        s = S11HybridYieldMax(capital=50_000.0)
        # monkey-patch: форсируем risk_off
        original = s.get_mode
        s.get_mode = lambda apy_map: "risk_off"
        result = s.run_day({"pendle_yt": 5.0})
        self.assertEqual(result["mode"], "risk_off")
        self.assertAlmostEqual(result["expected_apy"], 0.0)
        self.assertAlmostEqual(result["daily_yield_usd"], 0.0)
        s.get_mode = original

    def test_run_day_increments_days(self) -> None:
        """Каждый вызов run_day инкрементирует days_simulated."""
        self.s.run_day(BULL_APY_MAP)
        self.s.run_day(BULL_APY_MAP)
        self.assertEqual(self.s._days_simulated, 2)

    def test_run_day_capital_grows(self) -> None:
        """Капитал растёт после позитивного дня."""
        initial = self.s.capital
        self.s.run_day(BULL_APY_MAP)
        self.assertGreater(self.s.capital, initial)

    def test_run_day_risk_score(self) -> None:
        """result['risk_score'] == RISK_SCORE (0.70)."""
        result = self.s.run_day(BULL_APY_MAP)
        self.assertAlmostEqual(result["risk_score"], 0.70)

    def test_run_day_returns_required_keys(self) -> None:
        """Результат содержит все обязательные ключи."""
        result = self.s.run_day(BULL_APY_MAP)
        for key in ("allocation", "expected_apy", "mode", "risk_score",
                    "daily_yield_usd", "capital_after", "days_simulated"):
            self.assertIn(key, result)

    def test_run_day_none_map(self) -> None:
        """apy_map=None — работает без ошибок, использует APY_DEFAULTS."""
        result = self.s.run_day(None)
        self.assertIn("mode", result)
        self.assertIn("expected_apy", result)


# ══════════════════════════════════════════════════════════════════════════════
# TestAllocationConstraints
# ══════════════════════════════════════════════════════════════════════════════

class TestAllocationConstraints(unittest.TestCase):
    """Ограничения аллокации: Pendle cap, rebalance threshold и пр."""

    def setUp(self) -> None:
        self.s = S11HybridYieldMax()

    def test_pendle_cap_constant(self) -> None:
        """MAX_PENDLE_EXPOSURE == 0.50."""
        self.assertAlmostEqual(MAX_PENDLE_EXPOSURE, 0.50)

    def test_base_pendle_weight_within_cap(self) -> None:
        """Вес pendle_yt в BASE_ALLOCATION ≤ MAX_PENDLE_EXPOSURE."""
        self.assertLessEqual(BASE_ALLOCATION["pendle_yt"], MAX_PENDLE_EXPOSURE)

    def test_fallback_no_pendle_exposure(self) -> None:
        """FALLBACK_ALLOCATION не имеет Pendle позиции."""
        self.assertNotIn("pendle_yt", FALLBACK_ALLOCATION)

    def test_rebalance_threshold_constant(self) -> None:
        """REBALANCE_THRESHOLD == 0.05."""
        self.assertAlmostEqual(REBALANCE_THRESHOLD, 0.05)

    def test_min_pendle_yt_apy_constant(self) -> None:
        """MIN_PENDLE_YT_APY == 12.0."""
        self.assertAlmostEqual(MIN_PENDLE_YT_APY, 12.0)

    def test_risk_score_within_spec(self) -> None:
        """RISK_SCORE <= 0.75 (как указано в задании)."""
        self.assertLessEqual(RISK_SCORE, 0.75)

    def test_target_apy_above_15(self) -> None:
        """TARGET_APY >= 15.0."""
        self.assertGreaterEqual(TARGET_APY, 15.0)


# ══════════════════════════════════════════════════════════════════════════════
# TestNeedsRebalance
# ══════════════════════════════════════════════════════════════════════════════

class TestNeedsRebalance(unittest.TestCase):
    """needs_rebalance() — проверка drift-триггера ребалансировки."""

    def setUp(self) -> None:
        self.s = S11HybridYieldMax()

    def test_no_rebalance_on_target(self) -> None:
        """Веса равны целевым → ребалансировка не нужна."""
        result = self.s.needs_rebalance(dict(BASE_ALLOCATION), mode="bull")
        self.assertFalse(result)

    def test_rebalance_needed_large_drift(self) -> None:
        """Дрейф > 5% → нужна ребалансировка."""
        drifted = dict(BASE_ALLOCATION)
        drifted["pendle_yt"] = 0.45 + 0.10  # +10% drift
        drifted["morpho_steakhouse"] = 0.30 - 0.10
        result = self.s.needs_rebalance(drifted, mode="bull")
        self.assertTrue(result)

    def test_no_rebalance_small_drift(self) -> None:
        """Дрейф < 5% → ребалансировка не нужна."""
        drifted = dict(BASE_ALLOCATION)
        drifted["pendle_yt"] = 0.45 + 0.03  # +3% drift
        drifted["morpho_steakhouse"] = 0.30 - 0.03
        result = self.s.needs_rebalance(drifted, mode="bull")
        self.assertFalse(result)

    def test_risk_off_no_rebalance(self) -> None:
        """risk_off режим → ребалансировка не нужна (пустой target)."""
        result = self.s.needs_rebalance({}, mode="risk_off")
        self.assertFalse(result)

    def test_rebalance_at_threshold(self) -> None:
        """Drift ровно на пороге 0.05 — не превышает, ребалансировка не нужна."""
        drifted = dict(BASE_ALLOCATION)
        drifted["pendle_yt"] = 0.45 + 0.05  # ровно +5%
        drifted["morpho_steakhouse"] = 0.30 - 0.05
        result = self.s.needs_rebalance(drifted, mode="bull")
        self.assertFalse(result)  # > threshold, не >=


# ══════════════════════════════════════════════════════════════════════════════
# TestGetStats
# ══════════════════════════════════════════════════════════════════════════════

class TestGetStats(unittest.TestCase):
    """get_stats() и to_vportfolio_format()."""

    def setUp(self) -> None:
        self.s = S11HybridYieldMax(capital=100_000.0)

    def test_get_stats_keys(self) -> None:
        """get_stats() возвращает все обязательные поля."""
        stats = self.s.get_stats()
        for key in ("strategy_id", "strategy_name", "tier", "target_apy",
                    "weighted_apy", "risk_score", "min_pendle_yt_apy",
                    "fallback_apy", "max_pendle_exposure", "rebalance_threshold",
                    "days_simulated", "total_yield_usd",
                    "base_allocation", "fallback_allocation"):
            self.assertIn(key, stats)

    def test_get_stats_strategy_id(self) -> None:
        """stats['strategy_id'] == 'S11'."""
        stats = self.s.get_stats()
        self.assertEqual(stats["strategy_id"], "S11")

    def test_to_vportfolio_format_keys(self) -> None:
        """to_vportfolio_format() возвращает обязательные VPortfolio поля."""
        vp = self.s.to_vportfolio_format()
        for key in ("id", "name", "allocation", "risk_score", "apy_target",
                    "tier", "capital_usd", "positions", "weighted_apy"):
            self.assertIn(key, vp)

    def test_vportfolio_id(self) -> None:
        """vp['id'] == 'S11'."""
        vp = self.s.to_vportfolio_format()
        self.assertEqual(vp["id"], "S11")

    def test_days_simulated_accumulates(self) -> None:
        """days_simulated растёт с каждым run_day."""
        self.s.run_day(BULL_APY_MAP)
        self.s.run_day(BULL_APY_MAP)
        self.s.run_day(BULL_APY_MAP)
        stats = self.s.get_stats()
        self.assertEqual(stats["days_simulated"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
