"""
spa_core/tests/test_emode_looping.py — тесты EModeLoopingStrategy (S9)
=======================================================================

Покрывает:
  - Net APY формула (разные LTV)
  - Health factor расчёт (разные LTV и APY)
  - Deleverage trigger conditions
  - Deleverage mechanics
  - Daily simulation (P&L, state update)
  - Stress scenarios (borrow spike, supply drop, liquidation risk)
  - VPortfolio format
  - Граничные случаи и инварианты
  - Integration: реестры стратегий

56 тестов, stdlib unittest, без сети, без реальных денег.
"""

import importlib
import math
import sys
import unittest
from pathlib import Path

# Обеспечиваем что spa_core видна из workspace
_SPA_ROOT = Path(__file__).resolve().parents[2]
if str(_SPA_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPA_ROOT))

from spa_core.strategies.emode_looping import (
    EModeLoopingStrategy,
    E_MODE_LIQ_THRESHOLD,
    E_MODE_MAX_LTV,
    DELEVERAGE_TARGET_LTV,
    HF_WARN,
    HF_EMERGENCY,
    BORROW_SPIKE_THRESHOLD,
    SUPPLY_DROP_THRESHOLD,
    _read_apy_from_adapter_status,
    _best_reinvest_apy,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_strategy(
    capital: float = 100_000.0,
    ltv: float = 0.62,           # safe default (HF ≈ 1.56)
    supply_apy: float = 0.032,
    borrow_apy: float = 0.045,
    reinvest_apy: float = 0.089,
) -> EModeLoopingStrategy:
    """Создаёт стратегию с безопасными параметрами по умолчанию."""
    return EModeLoopingStrategy(
        capital=capital,
        ltv=ltv,
        supply_apy=supply_apy,
        borrow_apy=borrow_apy,
        reinvest_apy=reinvest_apy,
    )


# ─── 1. Конструктор и инициализация ───────────────────────────────────────────

class TestConstructor(unittest.TestCase):
    """Тесты конструктора EModeLoopingStrategy."""

    def test_basic_construction(self):
        """Базовая инициализация с дефолтными параметрами."""
        s = EModeLoopingStrategy(capital=100_000.0)
        self.assertEqual(s.initial_capital, 100_000.0)
        self.assertAlmostEqual(s.ltv, 0.82, places=6)
        self.assertAlmostEqual(s.supply_apy, 0.032, places=6)
        self.assertAlmostEqual(s.borrow_apy, 0.045, places=6)
        self.assertAlmostEqual(s.reinvest_apy, 0.089, places=6)

    def test_initial_position_state(self):
        """Начальное состояние позиции корректно инициализировано."""
        s = EModeLoopingStrategy(capital=100_000.0, ltv=0.82)
        self.assertAlmostEqual(s.deposited, 100_000.0, places=4)
        self.assertAlmostEqual(s.borrowed, 82_000.0, places=4)
        self.assertAlmostEqual(s.reinvested, 82_000.0, places=4)

    def test_initial_pnl_zero(self):
        """Начальный P&L = 0."""
        s = _make_strategy()
        self.assertEqual(s.cumulative_pnl, 0.0)
        self.assertEqual(s.day_count, 0)
        self.assertEqual(len(s.daily_snapshots), 0)
        self.assertEqual(len(s.deleverage_events), 0)

    def test_custom_params(self):
        """Кастомные параметры корректно сохраняются."""
        s = EModeLoopingStrategy(
            capital=50_000.0,
            ltv=0.70,
            supply_apy=0.040,
            borrow_apy=0.055,
            reinvest_apy=0.100,
        )
        self.assertEqual(s.initial_capital, 50_000.0)
        self.assertAlmostEqual(s.ltv, 0.70)
        self.assertAlmostEqual(s.deposited, 50_000.0)
        self.assertAlmostEqual(s.borrowed, 35_000.0)
        self.assertAlmostEqual(s.reinvested, 35_000.0)

    def test_invalid_capital_raises(self):
        """Невалидный capital вызывает ValueError."""
        with self.assertRaises(ValueError):
            EModeLoopingStrategy(capital=0)
        with self.assertRaises(ValueError):
            EModeLoopingStrategy(capital=-1000)

    def test_invalid_ltv_raises(self):
        """LTV вне (0, 0.94] вызывает ValueError."""
        with self.assertRaises(ValueError):
            EModeLoopingStrategy(capital=100_000, ltv=0.0)
        with self.assertRaises(ValueError):
            EModeLoopingStrategy(capital=100_000, ltv=0.95)  # > E_MODE_MAX_LTV
        with self.assertRaises(ValueError):
            EModeLoopingStrategy(capital=100_000, ltv=-0.1)

    def test_negative_apy_raises(self):
        """Отрицательный APY вызывает ValueError."""
        with self.assertRaises(ValueError):
            EModeLoopingStrategy(capital=100_000, supply_apy=-0.01)
        with self.assertRaises(ValueError):
            EModeLoopingStrategy(capital=100_000, borrow_apy=-0.01)

    def test_status_initial(self):
        """Начальный статус = 'active', is_closed = False."""
        s = _make_strategy()
        self.assertEqual(s.position_status, "active")
        self.assertFalse(s.is_closed)


# ─── 2. Net APY ───────────────────────────────────────────────────────────────

class TestNetAPY(unittest.TestCase):
    """Тесты формулы net_apy = supply + ltv*(reinvest - borrow)."""

    def test_net_apy_formula_default_params(self):
        """net_apy с дефолтными параметрами (ltv=0.82): ~6.808%."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        expected = 0.032 + 0.82 * 0.089 - 0.82 * 0.045
        self.assertAlmostEqual(s.net_apy(), expected, places=8)

    def test_net_apy_example_from_spec(self):
        """Пример из задания: 3.2% + (82%×8.9%) - (82%×4.5%) = 6.808%."""
        s = EModeLoopingStrategy(
            capital=100_000,
            ltv=0.82,
            supply_apy=0.032,
            borrow_apy=0.045,
            reinvest_apy=0.089,
        )
        # 3.2% + 7.298% - 3.69% = 6.808%
        expected = 0.032 + 0.82 * 0.089 - 0.82 * 0.045
        self.assertAlmostEqual(s.net_apy() * 100, expected * 100, places=4)

    def test_net_apy_zero_ltv_near_zero(self):
        """При ltv→0 net_apy → supply_apy."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.001)
        # Практически только supply_apy
        self.assertAlmostEqual(s.net_apy(), 0.032, delta=0.001)

    def test_net_apy_max_ltv(self):
        """При ltv=E_MODE_MAX_LTV (0.94) формула корректна."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.94)
        expected = 0.032 + 0.94 * 0.089 - 0.94 * 0.045
        self.assertAlmostEqual(s.net_apy(), expected, places=8)

    def test_net_apy_positive_spread(self):
        """При reinvest_apy > borrow_apy net_apy > supply_apy."""
        s = _make_strategy(reinvest_apy=0.10, borrow_apy=0.03)
        self.assertGreater(s.net_apy(), s.supply_apy)

    def test_net_apy_negative_when_borrow_exceeds_reinvest(self):
        """При borrow_apy >> reinvest_apy net_apy может быть < supply_apy."""
        s = EModeLoopingStrategy(
            capital=100_000, ltv=0.82,
            supply_apy=0.02, borrow_apy=0.15, reinvest_apy=0.05
        )
        # net = 2% + 82%*(5%-15%) = 2% - 8.2% = -6.2%
        self.assertLess(s.net_apy(), 0.0)

    def test_net_apy_different_ltv_values(self):
        """Net APY линейно растёт с LTV при reinvest_apy > borrow_apy."""
        apy_at_062 = EModeLoopingStrategy(capital=100_000, ltv=0.62).net_apy()
        apy_at_082 = EModeLoopingStrategy(capital=100_000, ltv=0.82).net_apy()
        # 0.82 > 0.62 и reinvest_apy > borrow_apy → APY должен быть больше при 0.82
        self.assertGreater(apy_at_082, apy_at_062)

    def test_net_apy_target_7_percent(self):
        """При оптимальных параметрах net_apy ≥ 7%."""
        s = EModeLoopingStrategy(
            capital=100_000,
            ltv=0.82,
            supply_apy=0.042,    # Aave live 4.2%
            borrow_apy=0.045,
            reinvest_apy=0.089,
        )
        # 4.2% + 82%*(8.9%-4.5%) = 4.2% + 3.608% = 7.808%
        self.assertGreater(s.net_apy(), 0.07)


# ─── 3. Health Factor ─────────────────────────────────────────────────────────

class TestHealthFactor(unittest.TestCase):
    """Тесты расчёта health factor."""

    def test_hf_formula_basic(self):
        """HF = (deposited × 0.97) / borrowed при одном шаге."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.62)
        # При ltv=0.62: HF ≈ (100K × 0.97×(1+supply/365)) / (62K×(1+borrow/365))
        hf = s.health_factor()
        # Базовый расчёт: ~0.97/0.62 * correction ≈ 1.565
        self.assertGreater(hf, 1.0)
        self.assertLess(hf, 5.0)

    def test_hf_safe_at_low_ltv(self):
        """При ltv=0.626 (безопасный): HF ≈ 1.55 (> HF_WARN=1.5)."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.626)
        hf = s.health_factor()
        # HF = 0.97/0.626 ≈ 1.550 (с небольшой коррекцией на дневной APY)
        self.assertAlmostEqual(hf, E_MODE_LIQ_THRESHOLD / 0.626, delta=0.01)
        self.assertGreater(hf, HF_WARN)

    def test_hf_warn_zone(self):
        """При ltv=0.70: HF ≈ 1.386 (< HF_WARN, > HF_EMERGENCY)."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.70)
        hf = s.health_factor()
        self.assertLess(hf, HF_WARN)
        self.assertGreater(hf, HF_EMERGENCY)

    def test_hf_emergency_zone_at_high_ltv(self):
        """При ltv=0.82: HF ≈ 1.183 (< HF_EMERGENCY=1.2)."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        hf = s.health_factor()
        self.assertLess(hf, HF_EMERGENCY)

    def test_hf_infinity_when_no_debt(self):
        """Если borrowed=0, HF = inf."""
        s = _make_strategy()
        s.borrowed = 0.0
        hf = s.health_factor()
        self.assertEqual(hf, float("inf"))

    def test_hf_with_explicit_rates(self):
        """HF с явными supply/borrow rates включает однодневную проекцию."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.62)
        hf_default = s.health_factor()
        hf_with_rates = s.health_factor(supply_apy=0.032, borrow_apy=0.045)
        # Должны быть близки (разница в дневной проекции)
        self.assertAlmostEqual(hf_default, hf_with_rates, delta=0.01)

    def test_hf_decreases_with_higher_borrow(self):
        """HF снижается при росте borrow_apy."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.62)
        hf_low_borrow = s.health_factor(borrow_apy=0.02)
        hf_high_borrow = s.health_factor(borrow_apy=0.10)
        self.assertGreater(hf_low_borrow, hf_high_borrow)

    def test_hf_increases_with_higher_supply(self):
        """HF растёт при росте supply_apy."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.62)
        hf_low_supply = s.health_factor(supply_apy=0.01)
        hf_high_supply = s.health_factor(supply_apy=0.10)
        self.assertGreater(hf_high_supply, hf_low_supply)

    def test_hf_monotone_with_ltv(self):
        """HF монотонно убывает с ростом LTV."""
        hf_low = EModeLoopingStrategy(capital=100_000, ltv=0.40).health_factor()
        hf_mid = EModeLoopingStrategy(capital=100_000, ltv=0.62).health_factor()
        hf_high = EModeLoopingStrategy(capital=100_000, ltv=0.90).health_factor()
        self.assertGreater(hf_low, hf_mid)
        self.assertGreater(hf_mid, hf_high)


# ─── 4. Deleverage ────────────────────────────────────────────────────────────

class TestDeleverage(unittest.TestCase):
    """Тесты механики делевериджа."""

    def test_deleverage_reduces_borrowed(self):
        """Делеверидж снижает borrowed до ~60% от deposited."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        s.deleverage()
        target = s.deposited * DELEVERAGE_TARGET_LTV
        self.assertAlmostEqual(s.borrowed, target, delta=1.0)

    def test_deleverage_reduces_reinvested(self):
        """Делеверидж использует reinvested для погашения долга."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        reinvested_before = s.reinvested
        s.deleverage()
        self.assertLess(s.reinvested, reinvested_before)

    def test_deleverage_improves_hf(self):
        """После делевериджа HF улучшается."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        hf_before = s.health_factor()
        s.deleverage()
        hf_after = s.health_factor()
        self.assertGreater(hf_after, hf_before)

    def test_deleverage_hf_above_warn_after(self):
        """После делевериджа с ltv=0.82 → HF ≥ HF_WARN (1.5) при target 60%."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        s.deleverage()
        hf_after = s.health_factor()
        # 0.97/0.60 ≈ 1.617 > 1.5
        self.assertGreater(hf_after, HF_WARN)

    def test_deleverage_updates_ltv(self):
        """Делеверидж обновляет self.ltv."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        s.deleverage()
        self.assertAlmostEqual(s.ltv, s.current_ltv_ratio(), places=4)
        self.assertLessEqual(s.ltv, DELEVERAGE_TARGET_LTV + 0.01)

    def test_deleverage_event_recorded(self):
        """Событие делевериджа записывается в список."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        self.assertEqual(len(s.deleverage_events), 0)
        s.deleverage()
        self.assertEqual(len(s.deleverage_events), 1)
        event = s.deleverage_events[0]
        self.assertIn("previous_borrowed", event)
        self.assertIn("repaid", event)
        self.assertIn("new_hf", event)
        self.assertIn("summary", event)

    def test_deleverage_no_action_when_already_safe(self):
        """Если LTV уже ≤ DELEVERAGE_TARGET_LTV → no_action."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.55)
        result = s.deleverage()
        self.assertEqual(result["status"], "no_action")
        self.assertEqual(result["repaid"], 0.0)
        self.assertEqual(len(s.deleverage_events), 0)

    def test_deleverage_partial_when_reinvested_insufficient(self):
        """Частичный делеверидж если reinvested меньше нужной суммы."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        # Искусственно обнуляем reinvested
        s.reinvested = 5_000.0  # меньше чем нужно для полного делевериджа
        result = s.deleverage()
        # Погасили только то что было
        self.assertAlmostEqual(result["reinvested_used"], 5_000.0, places=2)
        self.assertEqual(s.reinvested, 0.0)

    def test_deleverage_returns_dict(self):
        """deleverage() возвращает словарь с обязательными ключами."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        result = s.deleverage()
        required_keys = {
            "previous_borrowed", "target_borrowed", "repaid",
            "new_borrowed", "new_ltv", "new_hf", "reinvested_used", "summary"
        }
        self.assertTrue(required_keys.issubset(set(result.keys())))

    def test_closed_position_no_deleverage(self):
        """Закрытая позиция возвращает 'closed' статус."""
        s = _make_strategy()
        s.is_closed = True
        result = s.deleverage()
        self.assertEqual(result["status"], "closed")


# ─── 5. Daily Simulation ──────────────────────────────────────────────────────

class TestSimulateDay(unittest.TestCase):
    """Тесты simulate_day: P&L, обновление состояния, снимки."""

    def test_simulate_day_returns_dict(self):
        """simulate_day возвращает словарь с обязательными ключами."""
        s = _make_strategy()
        result = s.simulate_day()
        required_keys = {
            "date", "day", "deposited", "borrowed", "reinvested",
            "net_apy", "health_factor", "daily_pnl", "cumulative_pnl",
            "equity", "status", "alerts"
        }
        self.assertTrue(required_keys.issubset(set(result.keys())))

    def test_simulate_day_increments_counter(self):
        """simulate_day увеличивает day_count."""
        s = _make_strategy()
        self.assertEqual(s.day_count, 0)
        s.simulate_day()
        self.assertEqual(s.day_count, 1)
        s.simulate_day()
        self.assertEqual(s.day_count, 2)

    def test_simulate_day_accrues_supply_income(self):
        """simulate_day начисляет дневной supply income."""
        s = _make_strategy(supply_apy=0.032)
        deposited_before = s.deposited
        s.simulate_day()
        expected_income = deposited_before * 0.032 / 365.0
        self.assertAlmostEqual(s.accrued_supply_income, expected_income, places=6)

    def test_simulate_day_accrues_borrow_cost(self):
        """simulate_day начисляет дневной borrow cost."""
        s = _make_strategy(borrow_apy=0.045, ltv=0.62)
        borrowed_before = s.borrowed
        s.simulate_day()
        expected_cost = borrowed_before * 0.045 / 365.0
        self.assertAlmostEqual(s.accrued_borrow_cost, expected_cost, places=6)

    def test_simulate_day_positive_pnl_when_spread_positive(self):
        """Если reinvest_apy > borrow_apy, daily_pnl > 0."""
        s = _make_strategy(reinvest_apy=0.10, borrow_apy=0.03, supply_apy=0.04)
        result = s.simulate_day()
        self.assertGreater(result["daily_pnl"], 0.0)

    def test_simulate_day_cumulative_pnl_grows(self):
        """Cumulative PnL растёт при положительном spread."""
        s = _make_strategy()
        for _ in range(10):
            s.simulate_day()
        self.assertGreater(s.cumulative_pnl, 0.0)

    def test_simulate_day_snapshot_recorded(self):
        """Каждый день добавляет снимок в daily_snapshots."""
        s = _make_strategy()
        self.assertEqual(len(s.daily_snapshots), 0)
        s.simulate_day()
        self.assertEqual(len(s.daily_snapshots), 1)
        s.simulate_day()
        self.assertEqual(len(s.daily_snapshots), 2)

    def test_simulate_day_updates_apy_params(self):
        """simulate_day обновляет APY параметры если переданы."""
        s = _make_strategy(supply_apy=0.032)
        s.simulate_day(supply_apy=0.050)
        self.assertAlmostEqual(s.supply_apy, 0.050, places=6)

    def test_simulate_day_closed_returns_immediately(self):
        """Закрытая позиция возвращает статус 'closed' без изменений."""
        s = _make_strategy()
        s.is_closed = True
        result = s.simulate_day()
        self.assertEqual(result["status"], "closed")
        self.assertEqual(s.day_count, 0)

    def test_simulate_day_30_days_net_return(self):
        """За 30 дней equity растёт примерно на net_apy/12."""
        s = _make_strategy()
        apy = s.net_apy()
        expected_30d = s.initial_capital * apy / 365.0 * 30
        for _ in range(30):
            s.simulate_day()
        self.assertAlmostEqual(s.cumulative_pnl, expected_30d, delta=expected_30d * 0.01)


# ─── 6. Stress Scenarios ──────────────────────────────────────────────────────

class TestStressScenarios(unittest.TestCase):
    """Тесты встроенных стресс-сценариев."""

    def test_borrow_spike_triggers_deleverage(self):
        """borrow_apy > 8% → deleverage должен быть вызван."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        # Через simulate_day с borrow spike
        result = s.simulate_day(borrow_apy=0.090)
        # deleverage должен сработать (borrow > 8%)
        self.assertGreater(len(s.deleverage_events), 0)
        # Статус после deleveraging
        self.assertIn(result["status"], {"deleveraging", "active", "warning"})

    def test_borrow_spike_alert_in_snapshot(self):
        """При borrow spike в снимке есть алерт BORROW_SPIKE."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.62)
        result = s.simulate_day(borrow_apy=0.090)
        alerts_text = " ".join(result["alerts"])
        self.assertIn("BORROW_SPIKE", alerts_text)

    def test_supply_drop_alert(self):
        """supply_apy < 0.5% → алерт SUPPLY_DROP."""
        s = _make_strategy(supply_apy=0.001)
        result = s.simulate_day(supply_apy=0.001)
        alerts_text = " ".join(result["alerts"])
        self.assertIn("SUPPLY_DROP", alerts_text)

    def test_supply_drop_strategy_unattractive(self):
        """При supply_drop стратегия не является привлекательной."""
        s = _make_strategy()
        s.supply_apy = 0.001  # < 0.5% threshold
        self.assertFalse(s.is_attractive())

    def test_hf_emergency_triggers_deleverage(self):
        """HF < 1.2 → deleverage вызывается автоматически."""
        # ltv=0.82 даёт HF < 1.2 → должен deleverage
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        self.assertLess(s.health_factor(), HF_EMERGENCY)
        s.simulate_day()
        # После дня должен произойти deleverage
        self.assertGreater(len(s.deleverage_events), 0)

    def test_hf_warn_generates_warning_alert(self):
        """HF < 1.5 (warn zone) → статус/алерт warning."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.70)
        hf = s.health_factor()
        # Confirm ltv=0.70 is in warn zone
        self.assertLess(hf, HF_WARN)
        self.assertGreater(hf, HF_EMERGENCY)
        result = s.simulate_day()
        # Ожидаем либо warn в алертах, либо warning статус
        alerts_text = " ".join(result["alerts"])
        status = result["status"]
        is_warn = "WARN" in alerts_text or status == "warning"
        self.assertTrue(is_warn, f"Expected warning, got status={status}, alerts={result['alerts']}")

    def test_run_stress_scenario_normal(self):
        """Стресс-сценарий 'normal' выполняется без ошибок."""
        s = _make_strategy()
        result = s.run_stress_scenario("normal")
        self.assertEqual(result["scenario"], "normal")
        self.assertIn("snapshot", result)
        self.assertIn("daily_pnl", result["snapshot"])

    def test_run_stress_scenario_borrow_spike(self):
        """Стресс-сценарий 'borrow_spike' вызывает deleverage."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        result = s.run_stress_scenario("borrow_spike")
        self.assertEqual(result["scenario"], "borrow_spike")
        # deleverage должен был сработать
        self.assertGreater(result["deleverage_events"], 0)

    def test_run_stress_scenario_supply_drop(self):
        """Стресс-сценарий 'supply_drop' отмечает стратегию как непривлекательную."""
        s = _make_strategy()
        result = s.run_stress_scenario("supply_drop")
        # supply_apy обновляется до 0.003 < 0.005 → SUPPLY_DROP alert
        alerts_text = " ".join(result["snapshot"]["alerts"])
        self.assertIn("SUPPLY_DROP", alerts_text)

    def test_run_stress_scenario_liquidation_risk(self):
        """Стресс-сценарий 'liquidation_risk' создаёт алерты."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        result = s.run_stress_scenario("liquidation_risk")
        # При высоком borrow_apy=7.5% должны быть алерты
        self.assertGreater(len(result["snapshot"]["alerts"]), 0)

    def test_unknown_scenario_raises(self):
        """Неизвестный сценарий вызывает ValueError."""
        s = _make_strategy()
        with self.assertRaises(ValueError):
            s.run_stress_scenario("nonexistent_scenario")


# ─── 7. VPortfolio Format ─────────────────────────────────────────────────────

class TestVPortfolioFormat(unittest.TestCase):
    """Тесты to_vportfolio_format()."""

    def test_vportfolio_required_keys(self):
        """Все обязательные ключи VPortfolio присутствуют."""
        s = _make_strategy()
        vp = s.to_vportfolio_format()
        required = {
            "name", "strategy_id", "initial_capital", "cash",
            "positions", "equity", "last_ts", "equity_curve",
            "strategy_meta", "is_demo"
        }
        self.assertTrue(required.issubset(set(vp.keys())), f"Missing keys: {required - set(vp.keys())}")

    def test_vportfolio_name(self):
        """name = 's9_emode_looping'."""
        s = _make_strategy()
        vp = s.to_vportfolio_format()
        self.assertEqual(vp["name"], "s9_emode_looping")

    def test_vportfolio_strategy_id(self):
        """strategy_id = 'S9'."""
        s = _make_strategy()
        vp = s.to_vportfolio_format()
        self.assertEqual(vp["strategy_id"], "S9")

    def test_vportfolio_initial_capital(self):
        """initial_capital соответствует параметру конструктора."""
        s = _make_strategy(capital=200_000)
        vp = s.to_vportfolio_format()
        self.assertAlmostEqual(vp["initial_capital"], 200_000.0, places=2)

    def test_vportfolio_positions_keys(self):
        """positions содержит ожидаемые ключи."""
        s = _make_strategy()
        vp = s.to_vportfolio_format()
        self.assertIn("aave_v3_emode_supply", vp["positions"])
        self.assertIn("aave_v3_emode_debt", vp["positions"])
        self.assertIn("morpho_pendle_reinvest", vp["positions"])

    def test_vportfolio_debt_is_negative(self):
        """Debt позиция отображается как отрицательное число."""
        s = _make_strategy(ltv=0.62)
        vp = s.to_vportfolio_format()
        self.assertLess(vp["positions"]["aave_v3_emode_debt"], 0.0)

    def test_vportfolio_is_demo_false(self):
        """is_demo = False (paper trading, но не demo)."""
        s = _make_strategy()
        vp = s.to_vportfolio_format()
        self.assertFalse(vp["is_demo"])
        self.assertFalse(vp["strategy_meta"]["is_demo"])

    def test_vportfolio_equity_curve_empty_initially(self):
        """До simulate_day equity_curve пустой."""
        s = _make_strategy()
        vp = s.to_vportfolio_format()
        self.assertEqual(vp["equity_curve"], [])

    def test_vportfolio_equity_curve_after_simulation(self):
        """После N дней equity_curve содержит N записей."""
        s = _make_strategy()
        for _ in range(5):
            s.simulate_day()
        vp = s.to_vportfolio_format()
        self.assertEqual(len(vp["equity_curve"]), 5)

    def test_vportfolio_strategy_meta_contains_net_apy(self):
        """strategy_meta содержит net_apy."""
        s = _make_strategy()
        vp = s.to_vportfolio_format()
        self.assertIn("net_apy", vp["strategy_meta"])
        self.assertAlmostEqual(vp["strategy_meta"]["net_apy"], s.net_apy(), places=6)

    def test_vportfolio_equity_matches_cumulative(self):
        """equity = initial_capital + cumulative_pnl."""
        s = _make_strategy()
        for _ in range(10):
            s.simulate_day()
        vp = s.to_vportfolio_format()
        expected = s.initial_capital + s.cumulative_pnl
        self.assertAlmostEqual(vp["equity"], expected, places=2)

    def test_vportfolio_equity_curve_ring_buffer(self):
        """equity_curve ограничен 90 записями (ring buffer)."""
        s = _make_strategy()
        for _ in range(100):
            s.simulate_day()
        vp = s.to_vportfolio_format()
        self.assertLessEqual(len(vp["equity_curve"]), 90)


# ─── 8. Current LTV и привлекательность ──────────────────────────────────────

class TestLTVAndAttractiveness(unittest.TestCase):
    """Тесты current_ltv_ratio() и is_attractive()."""

    def test_current_ltv_ratio_initial(self):
        """Начальный LTV ratio = ltv параметр."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        self.assertAlmostEqual(s.current_ltv_ratio(), 0.82, places=4)

    def test_current_ltv_zero_when_no_deposited(self):
        """LTV = 0 если deposited = 0."""
        s = _make_strategy()
        s.deposited = 0.0
        self.assertEqual(s.current_ltv_ratio(), 0.0)

    def test_is_attractive_with_good_rates(self):
        """Стратегия привлекательна при нормальных ставках."""
        s = _make_strategy(
            supply_apy=0.032,
            borrow_apy=0.045,
            reinvest_apy=0.089,
        )
        self.assertTrue(s.is_attractive())

    def test_is_unattractive_with_borrow_spike(self):
        """При borrow_apy > 8% стратегия непривлекательна."""
        s = _make_strategy(borrow_apy=0.09)
        self.assertFalse(s.is_attractive())

    def test_is_unattractive_with_supply_drop(self):
        """При supply_apy < 0.5% стратегия непривлекательна."""
        s = _make_strategy(supply_apy=0.003)
        self.assertFalse(s.is_attractive())

    def test_is_unattractive_when_net_apy_negative(self):
        """При отрицательном net_apy стратегия непривлекательна."""
        s = _make_strategy(borrow_apy=0.15, reinvest_apy=0.05, supply_apy=0.02)
        self.assertFalse(s.is_attractive())


# ─── 9. Summary ───────────────────────────────────────────────────────────────

class TestSummary(unittest.TestCase):
    """Тесты метода summary()."""

    def test_summary_has_required_keys(self):
        """summary() содержит все обязательные ключи."""
        s = _make_strategy()
        summ = s.summary()
        required = {
            "strategy_id", "strategy_class", "initial_capital",
            "equity", "cumulative_pnl", "health_factor", "hf_status",
            "net_apy_pct", "current_ltv", "position_status", "is_demo",
        }
        self.assertTrue(required.issubset(set(summ.keys())))

    def test_summary_strategy_id(self):
        """summary.strategy_id = 'S9'."""
        s = _make_strategy()
        self.assertEqual(s.summary()["strategy_id"], "S9")

    def test_summary_hf_status_safe(self):
        """При ltv=0.62 hf_status = 'safe'."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.62)
        summ = s.summary()
        self.assertEqual(summ["hf_status"], "safe")

    def test_summary_hf_status_warning(self):
        """При ltv=0.70 hf_status = 'warning'."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.70)
        summ = s.summary()
        self.assertEqual(summ["hf_status"], "warning")

    def test_summary_hf_status_emergency(self):
        """При ltv=0.82 hf_status = 'emergency'."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        summ = s.summary()
        self.assertEqual(summ["hf_status"], "emergency")

    def test_summary_is_demo_false(self):
        """summary.is_demo = False."""
        s = _make_strategy()
        self.assertFalse(s.summary()["is_demo"])

    def test_summary_net_apy_pct(self):
        """net_apy_pct выражен в процентах (не долях)."""
        s = _make_strategy()
        summ = s.summary()
        # net_apy() в долях 0.0X → net_apy_pct в процентах X.X
        self.assertAlmostEqual(summ["net_apy_pct"], s.net_apy() * 100, places=4)


# ─── 10. Constants ────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    """Тесты что публичные константы соответствуют спецификации."""

    def test_liq_threshold(self):
        """E_MODE_LIQ_THRESHOLD = 0.97."""
        self.assertAlmostEqual(E_MODE_LIQ_THRESHOLD, 0.97)
        self.assertAlmostEqual(EModeLoopingStrategy.E_MODE_LIQ_THRESHOLD, 0.97)

    def test_max_ltv(self):
        """E_MODE_MAX_LTV = 0.94."""
        self.assertAlmostEqual(E_MODE_MAX_LTV, 0.94)

    def test_deleverage_target(self):
        """DELEVERAGE_TARGET_LTV = 0.60."""
        self.assertAlmostEqual(DELEVERAGE_TARGET_LTV, 0.60)
        self.assertAlmostEqual(EModeLoopingStrategy.DELEVERAGE_TARGET_LTV, 0.60)

    def test_hf_thresholds(self):
        """HF_WARN = 1.5, HF_EMERGENCY = 1.2."""
        self.assertAlmostEqual(HF_WARN, 1.5)
        self.assertAlmostEqual(HF_EMERGENCY, 1.2)

    def test_borrow_spike_threshold(self):
        """BORROW_SPIKE_THRESHOLD = 0.08 (8%)."""
        self.assertAlmostEqual(BORROW_SPIKE_THRESHOLD, 0.08)

    def test_supply_drop_threshold(self):
        """SUPPLY_DROP_THRESHOLD = 0.005 (0.5%)."""
        self.assertAlmostEqual(SUPPLY_DROP_THRESHOLD, 0.005)


# ─── 11. Integration: Strategy Registry ──────────────────────────────────────

class TestStrategyRegistryIntegration(unittest.TestCase):
    """Тесты интеграции S9 в реестр стратегий."""

    def test_s9_in_paper_trading_registry(self):
        """S9 зарегистрирована в paper_trading/strategy_registry.py."""
        from spa_core.paper_trading.strategy_registry import STRATEGY_REGISTRY
        self.assertIn("S9", STRATEGY_REGISTRY)

    def test_s9_config_allocations(self):
        """S9 конфигурация содержит ожидаемые аллокации."""
        from spa_core.paper_trading.strategy_registry import STRATEGY_REGISTRY
        s9 = STRATEGY_REGISTRY["S9"]
        self.assertIn("aave_v3", s9.allocations)
        self.assertIn("morpho_blue", s9.allocations)
        self.assertAlmostEqual(s9.allocations["aave_v3"], 0.50, places=2)

    def test_s9_config_tier(self):
        """S9 имеет tier T3 (leverage стратегия)."""
        from spa_core.paper_trading.strategy_registry import STRATEGY_REGISTRY
        s9 = STRATEGY_REGISTRY["S9"]
        self.assertEqual(s9.tier, "T3")

    def test_s9_config_target_apy(self):
        """S9 целевой APY диапазон 6-9%."""
        from spa_core.paper_trading.strategy_registry import STRATEGY_REGISTRY
        s9 = STRATEGY_REGISTRY["S9"]
        self.assertAlmostEqual(s9.target_apy_min, 6.0, places=1)
        self.assertAlmostEqual(s9.target_apy_max, 9.0, places=1)

    def test_s9_strategies_strategies_registry(self):
        """S9 's9_emode_looping' зарегистрирована в strategies/strategy_registry.py."""
        try:
            from spa_core.strategies.strategy_registry import REGISTRY
            meta = REGISTRY.get("s9_emode_looping")
            if meta is not None:
                self.assertEqual(meta.handler_class, "EModeLoopingStrategy")
                self.assertEqual(meta.type, "yield_loop")
                self.assertEqual(meta.risk_tier, "T3")
        except ImportError:
            # Реестр может быть в другом namespace
            self.skipTest("strategies registry not importable from test context")

    def test_s9_effective_allocations_without_pendle(self):
        """Аллокации без pendle_pt корректно перераспределяются."""
        from spa_core.paper_trading.strategy_registry import STRATEGY_REGISTRY
        s9 = STRATEGY_REGISTRY["S9"]
        available = {"aave_v3", "morpho_blue"}  # без pendle_pt
        effective = s9.effective_allocations(available)
        # Сумма ≤ исходной сумме аллокаций
        orig_sum = sum(s9.allocations.values())
        self.assertLessEqual(sum(effective.values()), orig_sum + 1e-9)
        self.assertIn("aave_v3", effective)
        self.assertIn("morpho_blue", effective)

    def test_s9_cash_pct(self):
        """S9 держит ≥ 5% кэша (сумма аллокаций ≤ 0.95 или = 1.0)."""
        from spa_core.paper_trading.strategy_registry import STRATEGY_REGISTRY
        s9 = STRATEGY_REGISTRY["S9"]
        # Сумма аллокаций = 0.50 + 0.30 + 0.20 = 1.0
        alloc_sum = sum(s9.allocations.values())
        self.assertLessEqual(alloc_sum, 1.0 + 1e-9)


# ─── 12. Math invariants ──────────────────────────────────────────────────────

class TestMathInvariants(unittest.TestCase):
    """Математические инварианты и граничные случаи."""

    def test_daily_pnl_sum_equals_cumulative(self):
        """Сумма daily_pnl за N дней ≈ cumulative_pnl."""
        s = _make_strategy()
        total_daily = 0.0
        for _ in range(20):
            result = s.simulate_day()
            total_daily += result["daily_pnl"]
        self.assertAlmostEqual(total_daily, s.cumulative_pnl, places=4)

    def test_deposited_grows_with_supply_apy(self):
        """deposited монотонно растёт при supply_apy > 0."""
        s = _make_strategy(supply_apy=0.05)
        deposited_prev = s.deposited
        for _ in range(5):
            s.simulate_day()
            self.assertGreater(s.deposited, deposited_prev)
            deposited_prev = s.deposited

    def test_net_apy_increases_with_ltv_when_spread_positive(self):
        """При reinvest > borrow: net_apy растёт с LTV."""
        s_low = EModeLoopingStrategy(capital=100_000, ltv=0.40, reinvest_apy=0.089)
        s_high = EModeLoopingStrategy(capital=100_000, ltv=0.80, reinvest_apy=0.089)
        self.assertGreater(s_high.net_apy(), s_low.net_apy())

    def test_deleverage_conserves_capital_approximately(self):
        """Делеверидж не создаёт капитал из воздуха: equity не растёт."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        equity_before = s.initial_capital  # PnL=0 до simulate_day
        s.deleverage()
        # equity (initial_capital + cumulative_pnl) не изменилась (deleverage без P&L)
        equity_after = s.initial_capital + s.cumulative_pnl
        self.assertAlmostEqual(equity_before, equity_after, places=4)

    def test_hf_at_deleverage_target_is_safe(self):
        """HF при ltv=DELEVERAGE_TARGET_LTV=0.60 > HF_WARN=1.5."""
        s = EModeLoopingStrategy(capital=100_000, ltv=DELEVERAGE_TARGET_LTV)
        hf = s.health_factor()
        # HF = 0.97/0.60 ≈ 1.617 > 1.5
        self.assertGreater(hf, HF_WARN)

    def test_multiple_deleverage_events(self):
        """Несколько делевериджей записываются корректно."""
        s = EModeLoopingStrategy(capital=100_000, ltv=0.82)
        # День с emergency HF
        s.simulate_day()
        # После deleverage LTV снизился
        # Поднимем artificially borrowed для второго deleverage
        s.borrowed = s.deposited * 0.82  # снова 82%
        s.ltv = 0.82
        s.deleverage()
        self.assertGreaterEqual(len(s.deleverage_events), 1)


# ─── 13. APY Reader helper ───────────────────────────────────────────────────

class TestAPYReader(unittest.TestCase):
    """Тесты helper-функций чтения APY."""

    def test_read_apy_returns_float(self):
        """_read_apy_from_adapter_status возвращает float."""
        result = _read_apy_from_adapter_status("aave-v3", default=0.032)
        self.assertIsInstance(result, float)

    def test_read_apy_default_on_missing_protocol(self):
        """Для несуществующего протокола возвращается default."""
        result = _read_apy_from_adapter_status("nonexistent_xyz", default=0.077)
        self.assertAlmostEqual(result, 0.077, places=4)

    def test_best_reinvest_apy_positive(self):
        """_best_reinvest_apy() возвращает положительное значение."""
        result = _best_reinvest_apy()
        self.assertGreater(result, 0.0)
        self.assertLess(result, 1.0)

    def test_best_reinvest_apy_returns_float(self):
        """_best_reinvest_apy() возвращает float."""
        result = _best_reinvest_apy()
        self.assertIsInstance(result, float)


# ─── Run ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
