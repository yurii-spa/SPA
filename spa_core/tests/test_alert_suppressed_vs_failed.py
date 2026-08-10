"""«Подавлено» и «провалено» — разные исходы, и печать обязана их различать.

Замер 2026-08-10. Цикл печатал четыре строки `FAILED` подряд (`daily_summary`,
`red_flags`, `gap`, `weekly`), и это выглядело как поломка рассылок. Разбор показал:
`send_*` возвращает `False` и при настоящем провале, и при подавлении «уже отправлено
сегодня» — а рассылки были просто повторными, потому что цикл в тот день отработал
52 раза вместо одного.

Цена смешения — не косметическая. Настоящий отказ отправки выглядел бы ровно так же и
утонул бы среди штатных повторов. У проекта уже есть закрытый случай, когда алерт
стоп-крана был заглушен с 4 июля и это заметили спустя недели.

Тип возврата `send_*` намеренно НЕ менялся: у него много вызывающих, и такая правка
сломала бы их молча. Отдельный вопрос отвечает отдельной функцией.
"""
from __future__ import annotations

import inspect
import unittest
from unittest import mock

from spa_core.alerts import alert_manager
from spa_core.paper_trading import cycle_runner


class TestPublicSuppressionView(unittest.TestCase):

    def test_the_public_helper_exists_and_delegates(self):
        self.assertTrue(hasattr(alert_manager, "already_sent_today"))
        with mock.patch.object(alert_manager, "_already_sent_today",
                               return_value=True) as inner:
            self.assertTrue(alert_manager.already_sent_today("daily_summary"))
        inner.assert_called_once_with("daily_summary")

    def test_send_return_type_is_unchanged(self):
        """Контракт `send_*` не тронут — иначе сломались бы чужие вызывающие."""
        # Аннотация может прийти строкой (отложенные аннотации) — сравниваем по
        # смыслу, а не по представлению, иначе тест ловил бы стиль файла, не контракт.
        ann = inspect.signature(alert_manager.send_daily_summary).return_annotation
        self.assertIn(ann, (bool, "bool"), f"контракт send_* изменился: {ann!r}")


class TestThreeOutcomesInTheReport(unittest.TestCase):
    """Печать цикла обязана показывать три исхода, а не два."""

    def setUp(self):
        self.src = inspect.getsource(cycle_runner)

    def test_a_suppressed_alert_is_not_called_FAILED(self):
        self.assertIn("skipped (already sent today)", self.src)

    def test_a_real_failure_is_still_called_FAILED(self):
        """Сторона, без которой правка стала бы глушилкой."""
        block = self.src[self.src.index("for name, ok in alerts.items()"):]
        block = block[:400]
        self.assertIn('label = "FAILED"', block,
                      "настоящий отказ обязан остаться отказом")

    def test_a_sent_alert_is_still_sent(self):
        block = self.src[self.src.index("for name, ok in alerts.items()"):][:400]
        self.assertIn('label = "sent"', block)

    def test_the_lookup_failure_does_not_break_the_print(self):
        """Если функция недоступна, печать обязана продолжиться, а не упасть.

        Учёт не может быть дороже того, что он учитывает.
        """
        block = self.src[self.src.index("already_sent_today as _sent_today") - 200:]
        self.assertIn("except Exception", block[:400])
        self.assertIn("_sent_today = None", block[:400])


if __name__ == "__main__":
    unittest.main()
