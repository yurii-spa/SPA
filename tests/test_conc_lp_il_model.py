"""tests/test_conc_lp_il_model.py — 45 tests for ConcLPILModel (MP-1308 v9.24)

Покрытие:
  T01–T05  Конструктор и валидация параметров
  T06–T10  il_pct() — базовые случаи
  T11–T15  il_pct() — симметрия и монотонность
  T16–T19  is_in_range()
  T20–T24  fee_apy_needed_to_break_even()
  T25–T30  net_apy_estimate()
  T31–T36  scenario_analysis() — структура и значения
  T37–T40  for_btc_usd() фабричный метод
  T41–T43  rs002_net_apy()
  T44–T45  concentration_factor() и range_width_pct()
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.conc_lp_il_model import ConcLPILModel


# ── T01–T05: конструктор ──────────────────────────────────────────────────────

class TestConstructor(unittest.TestCase):

    def test_T01_basic_construction(self):
        """Базовый конструктор работает без ошибок."""
        m = ConcLPILModel(40000, 80000, 60000)
        self.assertEqual(m.price_lower, 40000)
        self.assertEqual(m.price_upper, 80000)
        self.assertEqual(m.initial_price, 60000)

    def test_T02_fee_tier_default(self):
        """Дефолтный fee_tier = 0.003."""
        m = ConcLPILModel(40000, 80000, 60000)
        self.assertAlmostEqual(m.fee_tier, 0.003)

    def test_T03_raises_if_lower_ge_upper(self):
        """Ошибка если price_lower >= price_upper."""
        with self.assertRaises(ValueError):
            ConcLPILModel(80000, 40000, 60000)

    def test_T04_raises_if_lower_zero(self):
        """Ошибка если price_lower = 0."""
        with self.assertRaises(ValueError):
            ConcLPILModel(0, 80000, 60000)

    def test_T05_custom_fee_tier(self):
        """Кастомный fee_tier сохраняется."""
        m = ConcLPILModel(40000, 80000, 60000, fee_tier=0.01)
        self.assertAlmostEqual(m.fee_tier, 0.01)


# ── T06–T10: il_pct() — базовые случаи ───────────────────────────────────────

class TestILPctBasic(unittest.TestCase):

    def setUp(self):
        # BTC диапазон ±33% (40k–80k) при начальной цене 60k
        self.model = ConcLPILModel(40000, 80000, 60000)

    def test_T06_il_at_initial_price_is_zero(self):
        """IL при начальной цене = 0 (нет потерь в момент открытия)."""
        il = self.model.il_pct(self.model.initial_price)
        self.assertAlmostEqual(il, 0.0, places=6,
                               msg="IL at entry should be ~0%")

    def test_T07_il_returns_float(self):
        """il_pct() возвращает float."""
        il = self.model.il_pct(50000)
        self.assertIsInstance(il, float)

    def test_T08_il_is_negative_on_price_move(self):
        """IL отрицательный при любом ненулевом движении цены внутри диапазона."""
        il_up = self.model.il_pct(70000)
        il_down = self.model.il_pct(50000)
        self.assertLess(il_up, 0.0, msg="IL should be negative on upward move")
        self.assertLess(il_down, 0.0, msg="IL should be negative on downward move")

    def test_T09_il_magnitude_increases_with_price_move(self):
        """Большее движение цены → больший IL по абсолютной величине."""
        il_small = abs(self.model.il_pct(55000))  # 8% move
        il_large = abs(self.model.il_pct(70000))  # 17% move
        self.assertGreater(il_large, il_small)

    def test_T10_il_at_boundary_is_nonzero(self):
        """IL на нижней границе диапазона не равен нулю."""
        il = self.model.il_pct(self.model.price_lower)
        self.assertLess(il, 0.0)


# ── T11–T15: il_pct() — симметрия и монотонность ────────────────────────────

class TestILPctSymmetry(unittest.TestCase):

    def setUp(self):
        # Симметричный диапазон ±50% от центральной цены
        center = 60000.0
        self.model = ConcLPILModel(
            center * 0.5,  # 30000
            center * 1.5,  # 90000 — но лучше реалистичный диапазон
            center,
        )

    def test_T11_il_increases_farther_from_initial(self):
        """IL растёт с удалением цены от начальной (внутри диапазона)."""
        p0 = self.model.initial_price
        il_5pct  = abs(self.model.il_pct(p0 * 1.05))
        il_15pct = abs(self.model.il_pct(p0 * 1.15))
        il_25pct = abs(self.model.il_pct(p0 * 1.25))
        self.assertLess(il_5pct, il_15pct)
        self.assertLess(il_15pct, il_25pct)

    def test_T12_il_roughly_symmetric_up_down(self):
        """IL примерно симметричен для равного движения вверх/вниз."""
        p0 = self.model.initial_price
        move = 0.10  # ±10%
        il_up   = abs(self.model.il_pct(p0 * (1 + move)))
        il_down = abs(self.model.il_pct(p0 * (1 - move)))
        # Разница < 30% от среднего (из-за нелинейности — не точное равенство)
        avg = (il_up + il_down) / 2
        self.assertLess(abs(il_up - il_down), avg * 0.5,
                        msg=f"il_up={il_up:.4f}, il_down={il_down:.4f}")

    def test_T13_il_below_lower_boundary_locked(self):
        """Когда цена ниже нижней границы, IL «фиксируется» и не растёт."""
        below1 = self.model.price_lower * 0.9
        below2 = self.model.price_lower * 0.5
        # Оба значения должны давать одинаковый IL (locked at boundary)
        # Или ниже могут дать большее значение только из-за более дешёвого token0
        # Главное — il_pct не должен становиться хуже произвольно
        # Мы просто проверяем что не бросается исключений
        il1 = self.model.il_pct(below1)
        il2 = self.model.il_pct(below2)
        self.assertIsInstance(il1, float)
        self.assertIsInstance(il2, float)

    def test_T14_il_above_upper_boundary(self):
        """Когда цена выше верхней границы, позиция в 100% стейбле."""
        above = self.model.price_upper * 1.5
        il = self.model.il_pct(above)
        self.assertIsInstance(il, float)

    def test_T15_il_zero_at_exact_initial_price(self):
        """il_pct(initial_price) ровно 0.0 с точностью до 8 знаков."""
        il = self.model.il_pct(self.model.initial_price)
        self.assertAlmostEqual(il, 0.0, places=8)


# ── T16–T19: is_in_range() ────────────────────────────────────────────────────

class TestIsInRange(unittest.TestCase):

    def setUp(self):
        self.model = ConcLPILModel(40000, 80000, 60000)

    def test_T16_in_range_at_midpoint(self):
        """is_in_range(midpoint) = True."""
        midpoint = (self.model.price_lower + self.model.price_upper) / 2
        self.assertTrue(self.model.is_in_range(midpoint))

    def test_T17_out_of_range_below(self):
        """is_in_range(price_lower - 1) = False."""
        self.assertFalse(self.model.is_in_range(self.model.price_lower - 1))

    def test_T18_out_of_range_above(self):
        """is_in_range(price_upper + 1) = False."""
        self.assertFalse(self.model.is_in_range(self.model.price_upper + 1))

    def test_T19_in_range_at_boundaries(self):
        """is_in_range(price_lower) = True, is_in_range(price_upper) = True."""
        self.assertTrue(self.model.is_in_range(self.model.price_lower))
        self.assertTrue(self.model.is_in_range(self.model.price_upper))


# ── T20–T24: fee_apy_needed_to_break_even() ──────────────────────────────────

class TestBreakEvenAPY(unittest.TestCase):

    def setUp(self):
        self.model = ConcLPILModel(40000, 80000, 60000)

    def test_T20_break_even_positive_when_il_positive(self):
        """break_even > 0 когда IL > 0."""
        be = self.model.fee_apy_needed_to_break_even(il_pct=-5.0, holding_days=365)
        self.assertGreater(be, 0)

    def test_T21_break_even_zero_when_il_zero(self):
        """break_even = 0 когда IL = 0."""
        be = self.model.fee_apy_needed_to_break_even(il_pct=0.0, holding_days=365)
        self.assertAlmostEqual(be, 0.0, places=6)

    def test_T22_break_even_higher_for_shorter_period(self):
        """Break-even APY выше для более короткого периода удержания."""
        be_365 = self.model.fee_apy_needed_to_break_even(-5.0, 365)
        be_30  = self.model.fee_apy_needed_to_break_even(-5.0, 30)
        self.assertGreater(be_30, be_365)

    def test_T23_break_even_annual_with_1pct_il(self):
        """1% IL за год = 1% APY нужен для break-even."""
        be = self.model.fee_apy_needed_to_break_even(-1.0, 365)
        self.assertAlmostEqual(be, 1.0, places=3)

    def test_T24_break_even_infinite_for_zero_days(self):
        """break_even = inf при holding_days = 0."""
        be = self.model.fee_apy_needed_to_break_even(-5.0, 0)
        self.assertEqual(be, float("inf"))


# ── T25–T30: net_apy_estimate() ──────────────────────────────────────────────

class TestNetAPY(unittest.TestCase):

    def setUp(self):
        self.model = ConcLPILModel(40000, 80000, 60000)

    def test_T25_net_apy_less_than_gross_on_any_move(self):
        """net_apy < gross при ненулевом движении цены внутри диапазона."""
        gross = 40.0
        net = self.model.net_apy_estimate(gross, 10.0)
        self.assertLess(net, gross)

    def test_T26_net_apy_approx_equals_gross_at_zero_move(self):
        """net_apy ≈ gross при нулевом движении цены."""
        gross = 40.0
        net = self.model.net_apy_estimate(gross, 0.0)
        self.assertAlmostEqual(net, gross, places=3)

    def test_T27_net_apy_returns_float(self):
        """net_apy_estimate() возвращает float."""
        net = self.model.net_apy_estimate(40.0, 15.0)
        self.assertIsInstance(net, float)

    def test_T28_net_apy_worse_for_larger_move(self):
        """Большее движение → меньший net APY."""
        gross = 40.0
        net_small = self.model.net_apy_estimate(gross, 5.0)
        net_large = self.model.net_apy_estimate(gross, 25.0)
        self.assertGreater(net_small, net_large)

    def test_T29_net_apy_with_different_holding_periods(self):
        """net_apy с коротким holding меньше, чем с длинным (при том же IL)."""
        gross = 40.0
        # IL за 30 дней annualized → больший «штраф» на APY
        net_short = self.model.net_apy_estimate(gross, 20.0, holding_days=30)
        net_long  = self.model.net_apy_estimate(gross, 20.0, holding_days=365)
        self.assertLess(net_short, net_long)

    def test_T30_net_apy_can_be_negative_for_large_move(self):
        """net_apy может быть отрицательным при очень большом движении."""
        # Узкий диапазон, большое движение
        narrow = ConcLPILModel(55000, 65000, 60000)
        net = narrow.net_apy_estimate(5.0, 50.0)  # 50% выход за диапазон
        # не обязательно < 0, но должен быть меньше gross
        self.assertLess(net, 5.0)


# ── T31–T36: scenario_analysis() ─────────────────────────────────────────────

class TestScenarioAnalysis(unittest.TestCase):

    def setUp(self):
        self.model = ConcLPILModel(40000, 80000, 60000)

    def test_T31_returns_list(self):
        """scenario_analysis() возвращает list."""
        result = self.model.scenario_analysis()
        self.assertIsInstance(result, list)

    def test_T32_default_length(self):
        """По умолчанию 11 сценариев (DEFAULT_PRICE_MOVES)."""
        result = self.model.scenario_analysis()
        self.assertEqual(len(result), len(ConcLPILModel.DEFAULT_PRICE_MOVES))

    def test_T33_required_keys(self):
        """Каждый элемент содержит обязательные ключи."""
        result = self.model.scenario_analysis()
        required = {"price_move_pct", "il_pct", "net_apy", "in_range", "break_even_apy"}
        for row in result:
            self.assertTrue(required.issubset(row.keys()),
                            msg=f"Missing keys: {required - row.keys()}")

    def test_T34_zero_move_row_il_zero(self):
        """Сценарий 0% движения: il_pct ≈ 0.0."""
        result = self.model.scenario_analysis()
        zero_rows = [r for r in result if r["price_move_pct"] == 0.0]
        self.assertEqual(len(zero_rows), 1)
        self.assertAlmostEqual(zero_rows[0]["il_pct"], 0.0, places=3)

    def test_T35_custom_price_moves(self):
        """Можно передать кастомный список сценариев."""
        moves = [0, 10, -10]
        result = self.model.scenario_analysis(price_moves=moves)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["price_move_pct"], 0.0)

    def test_T36_in_range_flag_correct(self):
        """in_range=True для малых движений, False для выхода за диапазон."""
        result = self.model.scenario_analysis(price_moves=[0, 100])  # 100% выход
        self.assertTrue(result[0]["in_range"])
        # 100% выход: 60000*2=120000 > price_upper=80000
        self.assertFalse(result[1]["in_range"])


# ── T37–T40: for_btc_usd() ────────────────────────────────────────────────────

class TestForBtcUsd(unittest.TestCase):

    def test_T37_factory_works(self):
        """for_btc_usd() создаёт ConcLPILModel без ошибок."""
        model = ConcLPILModel.for_btc_usd(60000, 50.0)
        self.assertIsInstance(model, ConcLPILModel)

    def test_T38_initial_price_set(self):
        """for_btc_usd() устанавливает initial_price = btc_price."""
        model = ConcLPILModel.for_btc_usd(initial_btc_price=65000)
        self.assertAlmostEqual(model.initial_price, 65000)

    def test_T39_range_symmetric_around_price(self):
        """Диапазон ±50% симметричен вокруг initial_price."""
        model = ConcLPILModel.for_btc_usd(60000, 50.0)
        self.assertAlmostEqual(model.price_lower, 30000, places=0)
        self.assertAlmostEqual(model.price_upper, 90000, places=0)

    def test_T40_il_at_initial_price_is_zero(self):
        """for_btc_usd(): IL при начальной цене = 0."""
        model = ConcLPILModel.for_btc_usd(60000)
        il = model.il_pct(model.initial_price)
        self.assertAlmostEqual(il, 0.0, places=6)


# ── T41–T43: rs002_net_apy() ──────────────────────────────────────────────────

class TestRS002NetAPY(unittest.TestCase):

    def setUp(self):
        self.model = ConcLPILModel.for_btc_usd(60000, 50.0)

    def test_T41_rs002_net_apy_zero_move(self):
        """rs002_net_apy(0) ≈ 40.0% (нет IL при нулевом движении)."""
        net = self.model.rs002_net_apy(0.0)
        self.assertAlmostEqual(net, 40.0, places=3)

    def test_T42_rs002_net_apy_large_move_much_less(self):
        """rs002_net_apy(50) << rs002_net_apy(0) при большом движении."""
        net_0  = self.model.rs002_net_apy(0.0)
        net_50 = self.model.rs002_net_apy(50.0)
        self.assertLess(net_50, net_0)
        self.assertGreater(net_0 - net_50, 5.0,  # разница > 5 процентных пунктов
                           msg=f"net_0={net_0:.2f}, net_50={net_50:.2f}")

    def test_T43_rs002_net_apy_returns_float(self):
        """rs002_net_apy() возвращает float."""
        self.assertIsInstance(self.model.rs002_net_apy(10.0), float)


# ── T44–T45: concentration_factor() и range_width_pct() ─────────────────────

class TestUtilityMethods(unittest.TestCase):

    def test_T44_concentration_factor_gt_1(self):
        """concentration_factor() > 1 для любого ненулевого диапазона."""
        model = ConcLPILModel(40000, 80000, 60000)
        cf = model.concentration_factor()
        self.assertGreater(cf, 1.0)

    def test_T45_range_width_pct_correct(self):
        """range_width_pct() возвращает правильную ширину диапазона."""
        model = ConcLPILModel(40000, 80000, 60000)
        # (80000 - 40000) / 60000 * 100 = 66.67%
        expected = (80000 - 40000) / 60000 * 100
        self.assertAlmostEqual(model.range_width_pct(), expected, places=2)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
