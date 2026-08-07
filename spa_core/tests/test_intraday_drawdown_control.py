"""Просадку надо замечать в течение минут, а не суток.

Стоп-кран вычислялся ТОЛЬКО в дневном цикле — раз в 24 часа. На бумаге терпимо,
на реальных деньгах нет: между прогонами может пройти всё падение целиком, и
владелец узнает о нём через сутки. Владелец отметил это отдельным блокером
go-live.

Проверка живёт в `cycle_health_monitor`, который launchd уже запускает каждые
**300 секунд** — существующий частый ритм. Новый агент означал бы ещё одного
производителя, за которым надо следить, а именно от таких за сутки нашлось
шесть штук, и каждый молчал.

Ключевое свойство: проверка НЕ двигает капитал. Она вычисляет вердикт и
уведомляет; применяет его дневной цикл. Здесь только раннее обнаружение.
"""
from __future__ import annotations

import inspect
import unittest

from spa_core.monitoring import cycle_health_monitor as chm


class TestIntradayCheckIsWired(unittest.TestCase):

    def setUp(self):
        src = inspect.getsource(chm)
        self.tail = src[src.index("save_health_report(report"):]

    def test_the_five_minute_agent_computes_the_drawdown(self):
        """Без этого просадка замечается раз в сутки."""
        self.assertIn("run_kill_switch_check", self.tail,
                      "частый агент обязан вычислять вердикт стоп-крана")

    def test_it_notifies_through_the_p0_channel(self):
        self.assertIn('category="p0"', self.tail)
        self.assertIn('title="kill_switch"', self.tail)

    def test_a_failed_alert_is_announced_not_swallowed(self):
        """Несработавшая тревога обязана быть видна отдельным событием."""
        self.assertIn("ТРЕВОГА НЕ ОТПРАВЛЕНА", self.tail)

    def test_the_check_cannot_break_the_monitor_it_lives_in(self):
        """Сторож не имеет права ронять то, что охраняет."""
        self.assertIn("except Exception", self.tail)
        self.assertIn("пропущена", self.tail)

    def test_it_only_notifies_and_never_moves_capital(self):
        """Применяет вердикт дневной цикл. Здесь — только обнаружение.

        Иначе два независимых пути двигали бы капитал по одному событию.
        """
        for forbidden in ("allocate", "target_usd", "execute_trades", "atomic_save"):
            self.assertNotIn(forbidden, self.tail,
                             f"внутридневная проверка не должна вызывать {forbidden}")

    def test_it_runs_only_when_writing(self):
        """Сухой прогон не должен слать тревоги — иначе любой ручной вызов
        мониторинга разбудит владельца."""
        src = inspect.getsource(chm)
        write_at = src.index("if write_output:")
        ks_at = src.index("run_kill_switch_check")
        self.assertLess(write_at, ks_at)


class TestCadenceContract(unittest.TestCase):
    """То, на чём держится «внутридневной», обязано существовать."""

    def test_the_host_monitor_has_a_cli_entrypoint(self):
        self.assertTrue(hasattr(chm, "main"))

    def test_kill_switch_check_is_importable(self):
        from spa_core.governance.kill_switch import run_kill_switch_check

        self.assertTrue(callable(run_kill_switch_check))


if __name__ == "__main__":
    unittest.main()
