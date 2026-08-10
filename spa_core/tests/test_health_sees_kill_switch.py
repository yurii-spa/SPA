"""Сторож здоровья обязан видеть включённый стоп-кран.

Авария 2026-08-10. Стоп-кран был включён в 00:52 UTC внешним агентом
(`threat_reactor` → `kill_switch_checker`), торговля стояла **13 часов** — и всё это
время `agent_health` показывал `critical_flags: 0`. Сторож молчал ровно о самом
серьёзном событии в системе.

Путь уведомления чинили 07.08, но только для срабатывания ВНУТРИ цикла. Защёлку
поставил другой агент, и этот путь остался немым: шестой случай класса «проверка
честно отвечает на свой вопрос, а читается как ответ на нужный».

Дороже всего то, что молчание было **убедительным**: я сам несколько витков подряд
докладывал владельцу «критичных флагов 0, трек свежий», читая этого сторожа вместо
факта на диске.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring.agent_health_monitor import check_system

_NOW = datetime(2026, 8, 10, 13, 0, tzinfo=timezone.utc)


class TestKillSwitchVisibility(unittest.TestCase):

    def _run(self, latch: dict | None):
        with TemporaryDirectory() as t:
            d = Path(t)
            if latch is not None:
                (d / "kill_switch_active.json").write_text(
                    json.dumps(latch), encoding="utf-8")
            return check_system(data_dir=str(d), now=_NOW)

    def test_an_active_latch_is_CRITICAL(self):
        """Сердце аварии: включённый стоп-кран обязан быть критичным."""
        checks, status, issues = self._run({"reason": "threat_reactor: HALT"})
        self.assertIs(checks["kill_switch_active"], True)
        self.assertGreaterEqual(checks["critical_flags"], 1)
        self.assertEqual(status, "CRITICAL")
        self.assertTrue([i for i in issues if "СТОП-КРАН" in i],
                        "остановка обязана быть названа словами, а не только числом")

    def test_the_reason_is_surfaced(self):
        checks, _, _ = self._run({"reason": "threat_reactor: emergency breaker: HALT"})
        self.assertIn("emergency breaker", checks["kill_switch_reason"])

    def test_a_latch_without_a_reason_says_so(self):
        """Причина не записана — это факт, а не пустая строка.

        В настоящей аварии причина как раз НЕ сохранилась, и решение о снятии
        пришлось принимать вслепую.
        """
        checks, _, _ = self._run({})
        self.assertIn("не записана", checks["kill_switch_reason"])

    def test_no_latch_is_not_critical(self):
        """Сторона, без которой сторож стал бы вечно красным."""
        checks, status, _ = self._run(None)
        self.assertIs(checks["kill_switch_active"], False)
        self.assertNotEqual(status, "CRITICAL")

    def test_age_uses_the_injected_clock(self):
        """Время — вход, а не окружение: иначе тест сгниёт от смены календаря."""
        checks, _, _ = self._run({"reason": "x"})
        self.assertIsNotNone(checks["kill_switch_age_h"])
        self.assertLess(abs(checks["kill_switch_age_h"]), 24)


if __name__ == "__main__":
    unittest.main()
