"""ADR-181: точка безубыточности — проверяемое утверждение, не абзац прозы.

Этот файл ЗАМОРАЖИВАЕТ числа, названные владельцу в карточке ADR-181.
Если кто-то меняет константы cost_model (газ/слиппедж/мост) или профиль
недели — эти тесты краснеют, и карточку владельцу надо ПЕРЕСЧИТАТЬ, а не
молча оставить со старыми числами. Это намеренная связь, не хрупкость.

Профиль недели — переигрывание 22 перекладок (2026-08-22..29) через
доставленный churn_damper.decide(): прошло 3 хода (2 де-риска + 1
дискреционный), 7 ног, односторонний оборот 47.9% капитала. Доходность
книги — замер 30 evidenced-дней equity-кривой: $15.65/день на $100k =
5.71% годовых. Оба — измеренные входы, передаются явно (время и живые
файлы в тесте не участвуют).
"""
import unittest

from spa_core.backtesting.tier1.cost_model import GAS_USD_PER_POSITION_CHANGE
from spa_core.backtesting.tier1.pilot_breakeven import (
    breakeven_capital_usd,
    leg_gas_usd,
    min_position_usd,
    model_gas_leg_usd,
    proportional_rate_annual,
)

# Измеренные входы ADR-181 (см. docstring): не менять без пересчёта карточки.
YIELD_ANNUAL = 0.0571          # 30 evidenced-дней equity-кривой, на $100k
LEGS_PER_WEEK = 7              # переигранная неделя: 3 хода, 7 ног
TURNOVER_FRAC_WEEK = 0.479     # односторонний оборот $47,895 на $100k
PAYBACK_PILOT_DAYS = 45        # колонка «реальный пилот» ADR-060 §3


class BreakevenClaims(unittest.TestCase):
    """Утверждения, названные владельцу. Каждое — число из карточки."""

    def test_mainnet_at_model_constants_needs_more_than_current_book(self):
        # Главное утверждение ADR-181: при модельном газе $12/ногу книга
        # $100k НИЖЕ безубытка (посчитано: ~$117.5k).
        b = breakeven_capital_usd(YIELD_ANNUAL, model_gas_leg_usd("ethereum"),
                                  LEGS_PER_WEEK, TURNOVER_FRAC_WEEK)
        self.assertIsNotNone(b)
        self.assertGreater(b, 100_000)
        self.assertLess(b, 140_000)

    def test_mainnet_with_2x_margin_needs_half_a_million(self):
        b = breakeven_capital_usd(YIELD_ANNUAL, model_gas_leg_usd("ethereum"),
                                  LEGS_PER_WEEK, TURNOVER_FRAC_WEEK, coverage=2.0)
        self.assertIsNotNone(b)
        self.assertGreater(b, 400_000)
        self.assertLess(b, 650_000)

    def test_l2_breakeven_is_thousands_not_hundreds_of_thousands(self):
        for chain in ("arbitrum", "optimism", "base"):
            b = breakeven_capital_usd(YIELD_ANNUAL, model_gas_leg_usd(chain),
                                      LEGS_PER_WEEK, TURNOVER_FRAC_WEEK)
            self.assertIsNotNone(b, chain)
            self.assertLess(b, 3_000, chain)

    def test_coverage_5x_unreachable_at_measured_turnover_on_any_chain(self):
        # Структурный потолок: слиппедж 8бп × 47.9%/нед × 52 ≈ 1.99%/год;
        # 5 × 1.99% > 5.71% доходности ⇒ покрытие 5× недостижимо даже при
        # НУЛЕВОМ газе. Капитал эту часть издержек не лечит.
        self.assertGreater(5 * proportional_rate_annual(TURNOVER_FRAC_WEEK),
                           YIELD_ANNUAL)
        self.assertIsNone(breakeven_capital_usd(
            YIELD_ANNUAL, 0.0, LEGS_PER_WEEK, TURNOVER_FRAC_WEEK, coverage=5.0))

    def test_breakeven_monotonic_in_gas(self):
        cheap = breakeven_capital_usd(YIELD_ANNUAL, 0.25, LEGS_PER_WEEK,
                                      TURNOVER_FRAC_WEEK)
        dear = breakeven_capital_usd(YIELD_ANNUAL, 12.0, LEGS_PER_WEEK,
                                     TURNOVER_FRAC_WEEK)
        self.assertLess(cheap, dear)


class PilotPositionClaims(unittest.TestCase):
    """Owner-директива «~1000 USDT на стратегию»: где такой размер жив."""

    def test_1000_usdt_never_pays_back_on_mainnet_at_model_gas(self):
        # $12/ногу, выгода 1пп, окупаемость 45 дн ⇒ минимум ~$55k.
        p = min_position_usd(model_gas_leg_usd("ethereum"), gain_pp=1.0,
                             max_payback_days=PAYBACK_PILOT_DAYS)
        self.assertIsNotNone(p)
        self.assertGreater(p, 50_000)

    def test_1000_usdt_fails_even_on_arbitrum_at_model_gas_and_1pp(self):
        # Неожиданное: при модельных $0.25/ногу минимум ~$1,155 > $1,000.
        # На 1пп выгоды пилот НЕ проходит и на Arbitrum; проходит при ≥2пп
        # или на Base ($0.15/ногу ⇒ ~$693).
        p_arb = min_position_usd(model_gas_leg_usd("arbitrum"), 1.0,
                                 PAYBACK_PILOT_DAYS)
        self.assertGreater(p_arb, 1_000)
        p_arb2 = min_position_usd(model_gas_leg_usd("arbitrum"), 2.0,
                                  PAYBACK_PILOT_DAYS)
        self.assertLess(p_arb2, 1_000)
        p_base = min_position_usd(model_gas_leg_usd("base"), 1.0,
                                  PAYBACK_PILOT_DAYS)
        self.assertLess(p_base, 1_000)

    def test_cross_chain_move_at_1pp_never_pays_back_any_size(self):
        # Мост 5бп + слиппедж 8бп = 13бп ≥ выгода 1пп за 45 дн (12.3бп):
        # кросс-чейн ход при 1пп мёртв ЛЮБОГО размера, на любой цепочке.
        self.assertIsNone(min_position_usd(0.0, 1.0, PAYBACK_PILOT_DAYS,
                                           cross_chain=True))
        # при 2пп — жив и на модельном газе
        self.assertIsNotNone(min_position_usd(
            model_gas_leg_usd("arbitrum"), 2.0, PAYBACK_PILOT_DAYS,
            cross_chain=True))

    def test_gas_price_flips_the_mainnet_verdict(self):
        # Тот же mainnet при газе $0.05/ногу (замер 30.08: 0.073 Gwei ×
        # ETH $2,491 × 250k газа) — минимум ~$209: вердикт «mainnet мёртв
        # для пилота» держится ТОЛЬКО на неизмеренной константе 20 Gwei.
        # Сам спот здесь — параметр примера, не утверждение о сети.
        p = min_position_usd(0.05, 1.0, PAYBACK_PILOT_DAYS)
        self.assertIsNotNone(p)
        self.assertLess(p, 1_000)


class ModelWiring(unittest.TestCase):
    def test_leg_gas_usd_reproduces_model_constant(self):
        # Константа $12 ≈ 20 Gwei × 250k газа × ETH ~$2,400: проверка, что
        # формула и константа говорят об одном масштабе (±20%).
        self.assertAlmostEqual(leg_gas_usd(20.0, 2400.0), 12.0, delta=2.4)

    def test_model_gas_table_still_says_what_the_adr_measured(self):
        # Якорь на константы: их смена обязана перекрасить этот файл.
        self.assertEqual(GAS_USD_PER_POSITION_CHANGE["ethereum"], 12.0)
        self.assertEqual(GAS_USD_PER_POSITION_CHANGE["arbitrum"], 0.25)
        self.assertEqual(GAS_USD_PER_POSITION_CHANGE["base"], 0.15)


if __name__ == "__main__":
    unittest.main()
