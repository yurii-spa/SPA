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
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring.agent_health_monitor import check_system

# FROZEN-DATE-OK: обе стороны времени — ВХОД теста (предпочтение №1
# `.claude/rules/deployment.md`). Часы приходят в `check_system(now=_NOW)`, отметка
# защёлки выставляется от тех же часов (`_run(..., age_h=)` → `os.utime`), поэтому
# движение календаря на вердикт не влияет вовсе. Сама дата к тому же и предмет: это
# дословная хронология аварии 10.08.2026, ради которой сторож написан. Ровно
# ПОЛОВИНЧАТОЕ закрепление (часы пинали, mtime — нет) и уронило этот файл 12.08.
_NOW = datetime(2026, 8, 10, 13, 0, tzinfo=timezone.utc)


class TestKillSwitchVisibility(unittest.TestCase):

    def _run(self, latch: dict | None, *, age_h: float = 3.0):
        """Обе стороны времени закреплены: и часы (`now=`), и отметка защёлки.

        Возраст стоп-крана монитор берёт из mtime ФАЙЛА, а не из поля JSON. Пока
        фикстура пиналa только часы, mtime оставался «сейчас» настоящего календаря,
        и с 12.08 тест падал (45.48ч вместо <24) по причине, не имеющей отношения к
        проверяемому поведению, — тот самый класс, о котором предупреждает сам его
        докстринг и `.claude/rules/deployment.md` (предпочтение №1: закреплять ОБЕ
        стороны). Ставим mtime явно — тест снова бессмертен.
        """
        with TemporaryDirectory() as t:
            d = Path(t)
            if latch is not None:
                p = d / "kill_switch_active.json"
                p.write_text(json.dumps(latch), encoding="utf-8")
                stamp = (_NOW - timedelta(hours=age_h)).timestamp()
                os.utime(p, (stamp, stamp))
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
        """Время — вход, а не окружение: иначе тест сгниёт от смены календаря.

        Проверка УСИЛЕНА: раньше утверждалось лишь «меньше суток» (что было верно
        только потому, что календарь ещё не ушёл), теперь — ТОЧНЫЙ возраст между
        закреплённой отметкой и закреплёнными часами.
        """
        checks, _, _ = self._run({"reason": "x"}, age_h=3.0)
        self.assertIsNotNone(checks["kill_switch_age_h"])
        self.assertAlmostEqual(checks["kill_switch_age_h"], 3.0, places=1)

    def test_age_follows_the_stamp_not_the_wall_clock(self):
        """Положительный контроль к самой фикстуре: сдвинули отметку — сдвинулся возраст.

        Без него `_run` мог бы тихо перестать выставлять mtime, и первый тест снова
        мерил бы настоящий календарь, ничего об этом не сказав.
        """
        checks, _, _ = self._run({"reason": "x"}, age_h=30.0)
        self.assertAlmostEqual(checks["kill_switch_age_h"], 30.0, places=1)


if __name__ == "__main__":
    unittest.main()
