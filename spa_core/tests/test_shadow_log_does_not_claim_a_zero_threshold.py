"""«Порог не спрашивали» и «порог равен нулю» — разные вещи.

Замер 30.08. В логе цикла стояло:

    ADR-060 SHADOW: HOLD | gain 0.000pp (need 0.000) | cost $0.00 | payback None

Читается как «порог выгоды равен нулю», то есть как отключённый гейт (fail-open).
На деле `required_gain_pp` — поле со значением по умолчанию 0.0, а присваивается оно
ПОСЛЕ раннего выхода «нет материальных ног»: двигать было нечего, и порог не
участвовал вовсе. Сам гейт цел — предложения не существовало.

Вред не в цифре, а в том, ЧТО прочтёт человек, разбирающий инцидент через месяц: он
увидит нулевой порог рядом с решением и заключит, что защита была выключена.
"""
import tempfile
import unittest
from pathlib import Path

from spa_core.paper_trading.allocation_rationale import write_shadow_rationale

_LOGGER = "spa.paper_trading.allocation_rationale"
BOOK = {"compound_v3": 40000.0, "maple": 20000.0, "fluid_usdc": 20000.0}
APY = {"compound_v3": 7.87, "maple": 5.03, "fluid_usdc": 4.93, "morpho_blue": 4.19}
CAPS = {"compound_v3": 0.40, "maple": 0.20, "fluid_usdc": 0.20, "morpho_blue": 0.20}


class TestShadowLogDoesNotClaimAZeroThreshold(unittest.TestCase):

    def _shadow_line(self, current, target):
        with tempfile.TemporaryDirectory() as d:
            with self.assertLogs(_LOGGER, level="INFO") as cm:
                write_shadow_rationale(
                    data_dir=Path(d), current_positions=current,
                    target_positions=target, apy_pct=APY,
                    apy_sources={k: "live" for k in APY}, capital_usd=100000.0,
                    cycle_date="2026-08-30", run_ts="2026-08-30T23:32:45+00:00",
                    tier_caps=CAPS, trades=[], write=False)
        lines = [r for r in cm.output if "ADR-060 SHADOW" in r]
        self.assertTrue(lines, "строка ADR-060 SHADOW не появилась вовсе")
        return lines[-1]

    def test_no_move_says_the_threshold_was_not_consulted(self):
        """Цель равна книге ⇒ ходов нет ⇒ порог не спрашивали."""
        line = self._shadow_line(BOOK, dict(BOOK))
        self.assertNotIn(
            "need 0.000", line,
            "лог сообщает нулевой порог там, где порог не применялся — "
            f"это читается как отключённый гейт: {line}")
        self.assertIn("не оценивался", line, line)

    def test_a_real_move_still_prints_the_number(self):
        """Обратный контроль: где порог применён, он обязан быть ЧИСЛОМ."""
        target = {"compound_v3": 40000.0, "maple": 20000.0, "morpho_blue": 20000.0}
        line = self._shadow_line(BOOK, target)
        self.assertNotIn("не оценивался", line,
                         f"ход есть, а порог объявлен неспрошенным: {line}")
        self.assertRegex(line, r"need \d+\.\d{3}", line)


if __name__ == "__main__":
    unittest.main()
