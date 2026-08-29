"""Кэш-буфер сравнивается В ЦЕНТАХ: план РОВНО на 5 % — не нарушение (авария 29.08).

Трое суток подряд перераздача ADR-072 отклонялась с «After trade, cash buffer 5.0% <
minimum 5.0%», и 33.7 % капитала стояли без работы: дневная доходность 4.21 % → 3.17 %.
Утверждение ложно как арифметика — 5.0 не меньше 5.0.

Воспроизвести отказ удалось, только повторив СПОСОБ СЧЁТА гейта. `PortfolioState.cash_usd`
это `капитал − sum(позиции)`, поэтому на каждой ноге остаток получается как
`капитал − sum(предыдущие) − сумма`, а НЕ последовательным вычитанием. На реальных ногах
(доли вида 22105.260000000006) это дало

    остаток 4999.999999999996  →  доля 0.04999999999999996  <  0.05   ⇒ ОТКАЗ

Последовательное вычитание тех же чисел даёт ровно 5000.0. То есть план, ложащийся РОВНО на
обязательный буфер, отвергался из-за ошибки в последних битах.

Порог НЕ изменён. Изменена точность сравнения: деньги измеряются в центах, и полцента ниже
буфера — не нарушение буфера. Настоящее нарушение (на цент и больше) по-прежнему отвергается,
и это здесь проверяется отдельно — иначе «починка» была бы ослаблением гейта.
"""
from __future__ import annotations

import unittest

from spa_core.risk.policy import PortfolioState, Position, RiskPolicy

# Ноги ровно те, что подал прод 29.08 (из записи ADR-072 REJECTED, без округления).
LEGS = [
    ("compound_v3", 37894.74),
    ("aave_v3", 22105.260000000006),
    ("maple", 18947.37),
    ("fluid_usdc", 9473.68),
    ("morpho_blue_base", 6578.950000000001),
]
CAPITAL = 100_000.0


def _pos(key: str, amount: float) -> Position:
    return Position(protocol_key=key, tier="T2", asset="USDC", amount_usd=amount,
                    apy_at_open=4.0, current_apy=4.0, unrealized_pnl_usd=0.0,
                    days_held=1, chain="ethereum")


def _cash_violations(result) -> list[str]:
    return [v for v in result.violations if "cash buffer" in v]


class TheRealIncidentOf29Aug(unittest.TestCase):
    """Положительный контроль: те же числа, тот же порядок, тот же способ счёта."""

    def test_the_gate_arithmetic_really_lands_below_the_threshold(self):
        """Сначала докажем, что авария не выдумана: сырая арифметика гейта."""
        prior: list[float] = []
        last = None
        for _key, amount in LEGS:
            cash = CAPITAL - sum(prior)
            last = cash - amount
            prior.append(amount)
        self.assertLess(last, 5000.0, "числа аварии не воспроизводятся — контроль пуст")
        self.assertGreater(last, 4999.99, "это уже НАСТОЯЩЕЕ нарушение, а не шум")

    def test_no_leg_is_refused_for_the_cash_buffer(self):
        """Главное: ни одна нога не отвергается из-за буфера на этих числах."""
        state = PortfolioState(total_capital_usd=CAPITAL, positions=[])
        policy = RiskPolicy()
        for key, amount in LEGS:
            res = policy.check_new_position(
                state, key, "T2", amount_usd=amount, current_apy=4.0,
                tvl_usd=50_000_000.0, chain="ethereum")
            self.assertEqual(_cash_violations(res), [],
                             f"{key}: план ровно на 5 % снова читается как нарушение буфера")
            state.positions.append(_pos(key, amount))


class TheRuleItselfIsNotWeakened(unittest.TestCase):
    """Обратная сторона, и она здесь важнее: настоящее нарушение обязано отвергаться."""

    def _check(self, held: float, amount: float):
        state = PortfolioState(total_capital_usd=CAPITAL, positions=[_pos("held", held)])
        return RiskPolicy().check_new_position(
            state, "new", "T2", amount_usd=amount, current_apy=4.0,
            tvl_usd=50_000_000.0, chain="ethereum")

    def test_one_cent_below_the_buffer_is_still_refused(self):
        self.assertTrue(_cash_violations(self._check(90_000.0, 5_000.01)))

    def test_a_dollar_below_the_buffer_is_still_refused(self):
        self.assertTrue(_cash_violations(self._check(90_000.0, 5_001.0)))

    def test_a_thousand_below_the_buffer_is_still_refused(self):
        self.assertTrue(_cash_violations(self._check(90_000.0, 6_000.0)))

    def test_exactly_on_the_buffer_is_allowed(self):
        self.assertEqual(_cash_violations(self._check(90_000.0, 5_000.0)), [])

    def test_comfortably_above_the_buffer_is_allowed(self):
        self.assertEqual(_cash_violations(self._check(90_000.0, 1_000.0)), [])


class ThresholdIsUnchanged(unittest.TestCase):
    def test_min_cash_pct_is_still_five_percent(self):
        """Чинилась ТОЧНОСТЬ СРАВНЕНИЯ, а не порог: RiskPolicy v1.0 не тронут."""
        cfg = RiskPolicy().config
        self.assertEqual(cfg.min_cash_pct, 0.05)
        self.assertEqual(cfg.version, "v1.0")


if __name__ == "__main__":
    unittest.main()
