"""ADR-055: правило «ниже медианы» обязано смотреть на ход, а не на прошлое.

Положительный контроль — авария 2026-08-30, числа взяты из настоящей записи
сделки T030 (`data/trades.json`), не придуманы:

    from_allocation: compound_v3 37894.74 · maple 18947.37 · fluid_usdc 9473.68
    to_allocation:   + aave_v3 22105.26 (22.1 % капитала) под 3.26 %
                     + morpho_blue_base 6578.95

Медиана допущенных в тот момент — 4.93 %. Ход открыл ЧЕТВЕРТЬ книги в самом
низкодоходном протоколе набора. Правило, спрошенное про книгу ДО хода, честно
вернуло [] (aave_v3 там не было вовсе), и ничто не возразило в момент решения.

Снять правку `below_median_cap_target` — и оба теста ниже краснеют.
"""
import unittest
from pathlib import Path
import tempfile

from spa_core.paper_trading.allocation_rationale import write_shadow_rationale

FROM = {"compound_v3": 37894.74, "maple": 18947.37, "fluid_usdc": 9473.68}
TO = {"compound_v3": 37894.74, "maple": 18947.37, "fluid_usdc": 9473.68,
      "morpho_blue_base": 6578.95, "aave_v3": 22105.26}
# Живой снимок оркестратора того же цикла.
APY = {"compound_v3": 7.87, "maple": 5.03, "fluid_usdc": 4.93,
       "morpho_blue_base": 4.45, "aave_v3": 3.26}
SRC = {k: "live" for k in APY}
CAPS = {"compound_v3": 0.40, "aave_v3": 0.40,  # T1
        "maple": 0.20, "fluid_usdc": 0.20, "morpho_blue_base": 0.20}


def _doc(current, target):
    with tempfile.TemporaryDirectory() as d:
        return write_shadow_rationale(
            data_dir=Path(d), current_positions=current, target_positions=target,
            apy_pct=APY, apy_sources=SRC, tvl_sources={k: "live" for k in APY},
            capital_usd=100000.0, cycle_date="2026-08-30",
            run_ts="2026-08-30T20:46:11.778272+00:00",
            tier_caps=CAPS, trades=[], write=False)


class TestBelowMedianSeesTheTarget(unittest.TestCase):

    def test_the_move_that_created_econ10_is_named_at_decision_time(self):
        """Ход СОЗДАЁТ 22.1 % под 3.26 % — это должно быть видно сразу."""
        doc = _doc(FROM, TO)
        introduced = doc.get("below_median_cap_introduced")
        self.assertIsNotNone(
            introduced,
            "нет поля below_median_cap_introduced — правило по-прежнему "
            "спрашивают только о книге ДО хода")
        self.assertIn(
            "aave_v3", introduced,
            f"ход открыл 22.1 % капитала в худшем протоколе набора, "
            f"а правило этого не назвало: {introduced}")

    def test_the_old_wiring_was_silent_by_construction(self):
        """Обратный контроль: книга ДО хода нарушения НЕ содержит.

        Это и есть причина, по которой дефект жил незамеченным: старая проводка
        возвращала [] совершенно честно. Если этот тест покраснеет, значит
        нарушение видно и по старому входу, и вся находка была бы ложной.
        """
        doc = _doc(FROM, TO)
        self.assertEqual(
            [r.get("protocol") for r in doc.get("below_median_cap") or []], [],
            "книга ДО хода не содержала aave_v3 — нарушения тут быть не может")

    def test_a_move_that_introduces_nothing_stays_quiet(self):
        """Контроль в обратную сторону: без нарушения поле пустое."""
        good = dict(FROM)
        good["morpho_blue_base"] = 6578.95   # 4.45 % — выше медианы
        doc = _doc(FROM, good)
        self.assertEqual(doc.get("below_median_cap_introduced"), [],
                         "ход без концентрации ниже медианы не должен ничего называть")


if __name__ == "__main__":
    unittest.main()
