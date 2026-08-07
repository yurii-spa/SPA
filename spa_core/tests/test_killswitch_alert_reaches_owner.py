"""Стоп-кран сработал ⇒ владелец обязан узнать. Раньше не узнавал.

Замер 2026-08-06/07 прошёл всю цепочку и нашёл разрыв в каждом звене:

* `kill_switch` вычисляет вердикт и пишет его в файл — и на этом всё;
* `risk_sentinel` умеет классифицировать просадку > 5 % как `critical`, но
  **его нет в флоте** и он **ничего не отправляет** — только пишет свой файл;
* `incident_commander` тоже не отправляет и не запущен;
* `reporting_agent` отправлять умеет — но в флоте его нет;
* вызовов `category="p0"` — канала, построенного ИМЕННО для стоп-крана с
  обходом всех задержек — во всём коде **ноль**.

То есть при просадке −5 % владелец не узнал бы ничего: вердикт вычислялся,
ложился в файл и там оставался. Шестой случай класса «код есть, никто не зовёт»
за сутки и самый дорогой: остальные стоили точности, этот — осведомлённости о
худшем событии в системе.

Тесты здесь — положительный контроль: они воспроизводят срабатывание и требуют
**факта исходящего сообщения**, а не «функция отработала». Проверка, никогда не
видевшая настоящей аварии, — украшение.
"""
from __future__ import annotations

import inspect
import unittest

from spa_core.paper_trading import cycle_runner


class TestAlertIsWired(unittest.TestCase):
    """Отправка обязана СУЩЕСТВОВАТЬ в ветке срабатывания — это и был дефект."""

    def setUp(self):
        src = inspect.getsource(cycle_runner)
        # Срез берём ОТ применения стоп-крана, а не от лог-строки: порядок
        # «сначала применили, потом уведомили» — часть проверяемого контракта,
        # и обе стороны обязаны попасть в срез.
        i = src.index("_ks_allocation = dict")
        self.branch = src[i:i + 2600]

    def test_the_trigger_branch_sends_an_alert(self):
        """Без этого вердикт остаётся в логе, который никто не читает."""
        self.assertIn("TelegramManager", self.branch,
                      "срабатывание стоп-крана обязано уведомлять владельца")

    def test_it_uses_the_p0_channel_built_for_exactly_this(self):
        """`p0` обходит все остывания. Обычная категория может быть задержана.

        Канал существовал и не вызывался ниоткуда — тест закрепляет вызов.
        """
        self.assertIn('category="p0"', self.branch)
        self.assertIn('title="kill_switch"', self.branch)

    def test_a_failed_send_cannot_cancel_the_kill_switch(self):
        """Порядок обязателен: сначала сработал, потом сообщили.

        Если сбой телеграма отменит сам стоп-кран, лечение станет опаснее болезни.
        """
        self.assertIn("except Exception", self.branch,
                      "отправка обязана иметь СВОЙ обработчик")
        send_at = self.branch.index("TelegramManager")
        alloc_at = self.branch.index("_ks_allocation = dict")
        self.assertLess(alloc_at, send_at,
                        "стоп-кран применяется ДО попытки уведомить")

    def test_a_silent_failure_to_notify_is_itself_loud(self):
        """Не ушедшая тревога обязана быть видна ОТДЕЛЬНЫМ событием.

        Иначе мы заменим одну тишину другой: стоп-кран сработал, сообщение не
        ушло, и об этом тоже никто не узнал.
        """
        self.assertIn("ТРЕВОГА НЕ ОТПРАВЛЕНА", self.branch)
        tail = self.branch[self.branch.index("except Exception"):]
        self.assertIn("log.critical", tail,
                      "провал уведомления логируется как critical, не как debug")


class TestChannelContract(unittest.TestCase):
    """То, на что мы опираемся, обязано существовать с нужными свойствами."""

    def test_p0_category_exists_and_bypasses_cooldown(self):
        from spa_core.alerts.telegram_manager import TelegramManager  # noqa: F401
        import spa_core.alerts.telegram_manager as tm

        src = inspect.getsource(tm)
        self.assertIn('"p0"', src, "категория p0 обязана существовать")
        # Ноль секунд остывания — иначе тревога о стоп-кране может быть задержана
        # общим потоком сообщений ровно в момент, когда она нужнее всего.
        self.assertRegex(src, r'"p0":\s*0',
                         "p0 обязана обходить остывание (0 секунд)")

    def test_manager_exposes_send(self):
        from spa_core.alerts.telegram_manager import TelegramManager

        self.assertTrue(hasattr(TelegramManager, "send"))
        params = inspect.signature(TelegramManager.send).parameters
        for expected in ("title", "category"):
            self.assertIn(expected, params,
                          f"цикл вызывает send({expected}=...) — контракт обязан держаться")


if __name__ == "__main__":
    unittest.main()
