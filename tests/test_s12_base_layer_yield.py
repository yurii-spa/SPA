"""
tests/test_s12_base_layer_yield.py — MP-462

Unit-тесты для S12 Base Layer Yield strategy.
22 теста, покрывающих: константы, веса, phase gating, kill-switch,
run_day(), get_info(), edge cases.

Запуск:
    python3 tests/test_s12_base_layer_yield.py -v
    python3 -m pytest tests/test_s12_base_layer_yield.py -v
"""
import datetime
import unittest
import sys
import os
from unittest import mock

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.expanduser("~/Documents/SPA_Claude"))

from spa_core.strategies.s12_base_layer_yield import (
    S12BaseLayerYield,
    STRATEGY_ID,
    STRATEGY_NAME,
    TIER,
    RISK_SCORE,
    TARGET_APY_PCT,
    DESCRIPTION,
    BASE_WEIGHTS,
    PHASE1_WEIGHTS,
    GAS_KILL_WEIGHTS,
    BASE_PHASE_2_DATE,
    MIN_DAYS_PAPER,
    MIN_SHARPE,
    MAX_BASE_ALLOCATION,
    _is_phase2_active,
    _weighted_apy,
)


class TestS12Constants(unittest.TestCase):
    """Тест 1–8: Константы стратегии."""

    def test_strategy_id(self):
        """strategy_id должен быть 's12_base_layer_yield'."""
        self.assertEqual(STRATEGY_ID, "s12_base_layer_yield")

    def test_tier_is_T3(self):
        """Tier должен быть T3 (нет SPEC — Base это not advisory-only)."""
        self.assertEqual(TIER, "T3")

    def test_risk_score_in_range(self):
        """Risk score 0.40 — должен быть в диапазоне 0.30–0.60."""
        self.assertGreaterEqual(RISK_SCORE, 0.30)
        self.assertLessEqual(RISK_SCORE, 0.60)

    def test_target_apy_in_range(self):
        """Target APY 6.0% — должен быть в диапазоне 4.0–8.0%."""
        self.assertGreater(TARGET_APY_PCT, 4.0)
        self.assertLess(TARGET_APY_PCT, 8.0)

    def test_phase2_date_format(self):
        """BASE_PHASE_2_DATE должен быть ISO-форматом 'YYYY-MM-DD'."""
        import re
        self.assertRegex(BASE_PHASE_2_DATE, r"^\d{4}-\d{2}-\d{2}$")

    def test_min_days_paper(self):
        """ADR-023: MIN_DAYS_PAPER должен быть 30."""
        self.assertEqual(MIN_DAYS_PAPER, 30)

    def test_min_sharpe(self):
        """ADR-023: MIN_SHARPE должен быть 1.0."""
        self.assertEqual(MIN_SHARPE, 1.0)

    def test_max_base_allocation(self):
        """ADR-025: MAX_BASE_ALLOCATION <= 0.20."""
        self.assertLessEqual(MAX_BASE_ALLOCATION, 0.20)


class TestS12Weights(unittest.TestCase):
    """Тест 9–14: Веса аллокации."""

    def test_base_weights_sum_to_one(self):
        """BASE_WEIGHTS должны суммироваться в 1.0."""
        self.assertAlmostEqual(sum(BASE_WEIGHTS.values()), 1.0, places=5)

    def test_phase1_weights_sum_to_one(self):
        """PHASE1_WEIGHTS должны суммироваться в 1.0."""
        self.assertAlmostEqual(sum(PHASE1_WEIGHTS.values()), 1.0, places=5)

    def test_morpho_blue_base_in_base_weights(self):
        """morpho-blue-base должен присутствовать в BASE_WEIGHTS."""
        self.assertIn("morpho-blue-base", BASE_WEIGHTS)

    def test_aave_v3_base_in_base_weights(self):
        """aave-v3-base должен присутствовать в BASE_WEIGHTS."""
        self.assertIn("aave-v3-base", BASE_WEIGHTS)

    def test_phase1_no_base_adapters(self):
        """PHASE1_WEIGHTS не должны содержать Base chain адаптеры."""
        self.assertNotIn("morpho-blue-base", PHASE1_WEIGHTS)
        self.assertNotIn("aave-v3-base", PHASE1_WEIGHTS)

    def test_gas_kill_weights_sum_to_one(self):
        """GAS_KILL_WEIGHTS должны суммироваться в 1.0."""
        self.assertAlmostEqual(sum(GAS_KILL_WEIGHTS.values()), 1.0, places=5)


def _phase2_active_on(iso_date: str) -> bool:
    """``_is_phase2_active()`` так, как оно ответило бы в день ``iso_date``.

    Подменяется ТОЛЬКО имя ``datetime`` внутри модуля стратегии и только на
    время вызова; продакшн-код не меняется. Стандартная библиотека, без
    зависимостей (инвариант #4).
    """
    import spa_core.strategies.s12_base_layer_yield as s12

    class _FrozenDate(datetime.date):
        @classmethod
        def today(cls):
            return datetime.date.fromisoformat(iso_date)

    class _FrozenDatetime:
        date = _FrozenDate

    with mock.patch.object(s12, "datetime", _FrozenDatetime):
        return s12._is_phase2_active()


class TestS12PhaseGating(unittest.TestCase):
    """Тест 15–16: Phase gating."""

    def test_phase_gate_is_before_the_boundary(self):
        """До BASE_PHASE_2_DATE фаза 2 НЕ активна — при явно заданной дате.

        ── 2026-08-01, цикл #64 — тест УСИЛЕН, а не ослаблен (инвариант #16) ────
        Было: ``test_phase1_active_currently`` — «Сегодня (2026-06-12) должна
        быть Phase 1», то есть голое ``assertFalse(_is_phase2_active())`` без
        какой-либо даты. Такой тест проверяет КАЛЕНДАРЬ, а не код: он был
        истинным ровно до 2026-08-01 и с этого дня красит CI навсегда
        (``AssertionError: 'phase2' != 'phase1'`` у близнеца в S13; здесь —
        ``True is not false``). Причём проверял он всегда ровно одну ветку — ту,
        которую случайно выбрало сегодняшнее число.

        Стало: обе ветки границы проверяются явно и детерминированно, поэтому
        покрытие СТРОГО больше прежнего, а результат не зависит от того, когда
        запущен прогон. Продакшн-код не менялся ни строкой: дата подставляется
        подменой ``datetime`` в модуле стратегии (``_is_phase2_active`` читает
        ``datetime.date.today()``), сама константа ``BASE_PHASE_2_DATE`` не
        тронута — двигать её значит менять замысел, и это вопрос владельца
        (карточка ``owner-decision-nastupila-faza-2-1-avgusta-vklyuchaem-sd``).

        Замечание про часы: функция берёт ЛОКАЛЬНУЮ дату, не UTC — поэтому
        машина в UTC+2 переходит границу на два часа раньше раннера в UTC.
        """
        self.assertFalse(_phase2_active_on("2026-07-31"))
        self.assertFalse(_phase2_active_on("2026-06-12"))

    def test_phase_gate_is_on_and_after_the_boundary(self):
        """В день BASE_PHASE_2_DATE и позже фаза 2 активна (граница включающая)."""
        self.assertTrue(_phase2_active_on(BASE_PHASE_2_DATE))
        self.assertTrue(_phase2_active_on("2026-08-01"))
        self.assertTrue(_phase2_active_on("2026-12-31"))

    def test_phase_gate_reads_the_real_clock_by_default(self):
        """Контроль на подменяльщик: без подмены функция берёт настоящую дату.

        Без этого оба теста выше можно было бы удовлетворить заглушкой, которая
        вообще не смотрит на часы.
        """
        today = datetime.date.today().isoformat()
        self.assertEqual(_is_phase2_active(), today >= BASE_PHASE_2_DATE)

    def test_phase1_weights_when_phase1(self):
        """В Phase 1 get_target_weights() возвращает PHASE1_WEIGHTS."""
        strategy = S12BaseLayerYield()
        # Принудительно выставляем Phase 1, газ OK
        strategy.phase2_active   = False
        strategy.gas_kill_switch = False
        weights = strategy.get_target_weights()
        self.assertNotIn("morpho-blue-base", weights)
        self.assertNotIn("aave-v3-base", weights)


class TestS12RunDay(unittest.TestCase):
    """Тест 17–22: run_day()."""

    def setUp(self):
        self.strategy = S12BaseLayerYield()

    def test_run_day_returns_dict(self):
        """run_day() должен возвращать dict."""
        result = self.strategy.run_day({})
        self.assertIsInstance(result, dict)

    def test_run_day_has_required_keys(self):
        """run_day() результат должен содержать все обязательные ключи."""
        result = self.strategy.run_day({})
        for key in ["strategy_id", "apy_pct", "weights", "mode",
                    "gas_kill_switch", "phase2_active"]:
            self.assertIn(key, result)

    def test_run_day_apy_positive(self):
        """APY результат run_day() должен быть > 0."""
        result = self.strategy.run_day({})
        self.assertGreater(result["apy_pct"], 0)

    def test_run_day_strategy_id_matches(self):
        """strategy_id в run_day() должен совпадать с константой."""
        result = self.strategy.run_day({"morpho-blue-base": 6.5, "aave-v3-base": 4.8})
        self.assertEqual(result["strategy_id"], STRATEGY_ID)

    def test_run_day_with_live_apy_data(self):
        """run_day() с live APY-данными должен вернуть APY > 3%."""
        live = {
            "morpho-blue-base": 6.5,
            "aave-v3-base":     5.0,
            "morpho_steakhouse": 8.0,
            "aave_v3":          3.5,
        }
        result = self.strategy.run_day(live)
        self.assertGreater(result["apy_pct"], 3.0)

    def test_run_day_mode_valid(self):
        """mode в run_day() должен быть одним из допустимых значений."""
        result = self.strategy.run_day({})
        self.assertIn(result["mode"],
                      ["phase2_base", "phase1_fallback", "gas_kill"])


class TestS12GetInfo(unittest.TestCase):
    """Тест 23–25: get_info()."""

    def setUp(self):
        self.strategy = S12BaseLayerYield()

    def test_get_info_returns_dict(self):
        """get_info() должен возвращать dict."""
        info = self.strategy.get_info()
        self.assertIsInstance(info, dict)

    def test_get_info_has_required_keys(self):
        """get_info() должен содержать все обязательные ключи."""
        info = self.strategy.get_info()
        for key in ["strategy_id", "name", "tier", "risk_score",
                    "target_apy_pct", "description"]:
            self.assertIn(key, info)

    def test_get_info_values_correct(self):
        """Значения get_info() должны совпадать с константами модуля."""
        info = self.strategy.get_info()
        self.assertEqual(info["strategy_id"], STRATEGY_ID)
        self.assertEqual(info["tier"], TIER)
        self.assertAlmostEqual(info["risk_score"], RISK_SCORE)
        self.assertAlmostEqual(info["target_apy_pct"], TARGET_APY_PCT)


class TestS12WeightedApy(unittest.TestCase):
    """Тест 26–27: _weighted_apy() helper."""

    def test_weighted_apy_uses_defaults_when_empty(self):
        """_weighted_apy() с пустым apy_map использует дефолты (>0)."""
        result = _weighted_apy(PHASE1_WEIGHTS, {})
        self.assertGreater(result, 0.0)

    def test_weighted_apy_uses_provided_values(self):
        """_weighted_apy() использует переданные APY-данные."""
        apy_map = {"morpho_steakhouse": 10.0, "aave_v3": 5.0}
        # PHASE1_WEIGHTS: morpho_steakhouse=0.80, aave_v3=0.20
        # Expected: 0.80*10.0 + 0.20*5.0 = 8.0 + 1.0 = 9.0
        result = _weighted_apy(PHASE1_WEIGHTS, apy_map)
        self.assertAlmostEqual(result, 9.0, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
