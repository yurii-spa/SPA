"""Тридцатидневный отчёт оживлён шагом дневного цикла — решение владельца 25.08 (вариант 1).

Карточка «Три отчёта о доказательной базе трека молчат 2 месяца — оживить или
убрать в архив», ADR-140.

Замер 24.08: тридцатидневный отчёт последний раз выдал результат **29 июня** —
56 дней назад; недельный — **20 июня**, ровно один файл; ежедневный в Телеграм не
отправлялся вовсе. Общий корень: обёртка `scripts/run_daily_simulation.py`, из
которой все три запускались, **сама никем не звалась**. Умер не отчёт, а вся
цепочка вместе с корнем — и по отдельности это было не видно, потому что каждый
из трёх выглядел вызываемым: его звал сосед.

Владелец выбрал оживить ТОЛЬКО тридцатидневный (внутри существующего цикла, без
нового агента); недельный и ежедневный — в архив.

Предмет этого файла — ровно два утверждения: **шаг вызывается** и **молчание
видно**. Содержимое отчёта проверяется своими тестами (цикл #373).
"""
from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.paper_trading import cycle_reporting as cr

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — часы инъектируются ПАРОЙ
# с отметками: `now=NOW` уходит входом, а возраст файла ставится относительно
# того же NOW. Обе стороны закреплены, поэтому сдвиг календаря тест не трогает.


class TheStepIsActuallyCalled(unittest.TestCase):
    """Дефект был не в отчёте, а в том, что его никто не звал."""

    def test_post_cycle_advisory_calls_the_generator(self):
        src = inspect.getsource(cr.run_post_cycle_advisory)
        self.assertIn("_generate_evidence_report_30d", src,
                      "шаг снова никем не вызывается — ровно исходный дефект")

    def test_the_cycle_calls_post_cycle_advisory(self):
        """Вторая половина цепочки: обёртка тоже обязана быть вызвана.

        Именно на такой цепочке дефект и спрятался: каждое звено выглядело
        вызываемым, потому что его звал сосед, а корень не звал никто.
        """
        from spa_core.paper_trading import cycle_runner
        self.assertIn("run_post_cycle_advisory",
                      inspect.getsource(cycle_runner.run_cycle))

    def test_no_new_agent_was_introduced(self):
        """Условие владельца дословно: «без нового агента»."""
        plists = sorted(Path("launchd").glob("*.plist")) if Path("launchd").is_dir() else []
        for pl in plists:
            with self.subTest(plist=pl.name):
                self.assertNotIn("evidence_report", pl.read_text(encoding="utf-8"),
                                 "появился отдельный агент под отчёт")


class SilenceIsVisible(unittest.TestCase):
    """«Молчит 56 дней» обязано быть ВИДНО, а не обнаруживаться замером.

    Время — ВХОД функции, а не окружение (`.claude/rules/deployment.md`), поэтому
    тесты ниже не протухают от сдвига календаря.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ev30_"))

    def _report(self, age_hours: float) -> Path:
        p = self.tmp / "evidence_report_30d.txt"
        p.write_text("report", encoding="utf-8")
        import os
        ts = (NOW - timedelta(hours=age_hours)).timestamp()
        os.utime(p, (ts, ts))
        return p

    def test_fresh_report_is_fresh(self):
        v = cr.evidence_report_freshness(self._report(1.0), now=NOW)
        self.assertEqual(v["status"], "fresh")
        self.assertAlmostEqual(v["age_hours"], 1.0, places=2)

    def test_two_month_silence_is_stale_with_the_number(self):
        """Тот самый случай: 56 дней. Названо числом, а не флагом."""
        v = cr.evidence_report_freshness(self._report(56 * 24), now=NOW)
        self.assertEqual(v["status"], "stale")
        self.assertAlmostEqual(v["age_hours"], 56 * 24, places=1)

    def test_missing_report_is_missing_not_stale_and_not_fresh(self):
        """Инв. #17: три исхода, не два. Отсутствие ≠ «старый на ноль часов»."""
        v = cr.evidence_report_freshness(self.tmp / "no_such_file.txt", now=NOW)
        self.assertEqual(v["status"], "missing")
        self.assertIsNone(v["age_hours"])

    def test_threshold_boundary_is_inclusive(self):
        limit = cr.EVIDENCE_REPORT_MAX_AGE_H
        self.assertEqual(
            cr.evidence_report_freshness(self._report(limit), now=NOW)["status"], "fresh")
        self.assertEqual(
            cr.evidence_report_freshness(self._report(limit + 0.1), now=NOW)["status"],
            "stale")

    def test_one_missed_run_does_not_ring(self):
        """Порог выбран так, чтобы одиночный сбой не звенел, а цепочка — звенела."""
        self.assertGreater(cr.EVIDENCE_REPORT_MAX_AGE_H, 24.0)
        self.assertLess(cr.EVIDENCE_REPORT_MAX_AGE_H, 48.0)


class TheStepNeverBreaksTheCycle(unittest.TestCase):
    """Шаг fail-safe, как и все соседние в этом хвосте."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ev30run_"))
        (self.tmp / "data").mkdir()
        (self.tmp / "docs").mkdir()

    def test_generation_failure_does_not_raise(self):
        import spa_core.paper_trading.cycle_reporting as mod
        saved = mod._generate_evidence_report_30d.__globals__.get("__name__")
        self.assertTrue(saved)
        # Пустой data-каталог: производители отчёта не найдут своих файлов.
        mod._generate_evidence_report_30d(ddir=self.tmp / "data", now_dt=NOW)

    def test_freshness_stamp_is_written_even_when_generation_fails(self):
        """Иначе молчание отчёта снова стало бы невидимым — ровно исходный дефект."""
        import sys
        import spa_core.paper_trading.cycle_reporting as mod
        saved = sys.modules.pop("generate_evidence_report", None)

        class _Boom:
            def __getattr__(self, name):
                raise ImportError("генератор недоступен")

        sys.modules["generate_evidence_report"] = _Boom()
        try:
            mod._generate_evidence_report_30d(ddir=self.tmp / "data", now_dt=NOW)
        finally:
            sys.modules.pop("generate_evidence_report", None)
            if saved is not None:
                sys.modules["generate_evidence_report"] = saved

        stamp = self.tmp / "data" / mod.EVIDENCE_FRESHNESS_STATUS
        self.assertTrue(stamp.exists(), "отметка свежести не записана после сбоя")
        self.assertEqual(json.loads(stamp.read_text())["status"], "missing")


class TheOtherTwoAreArchived(unittest.TestCase):
    """Недельный и ежедневный — в `attic/`, с записью, откуда их достать."""

    def test_weekly_left_scripts(self):
        self.assertFalse(Path("scripts/weekly_evidence_report.py").exists(),
                         "недельный отчёт всё ещё в scripts/")
        self.assertTrue(Path("attic/scripts/weekly_evidence_report.py").exists())

    def test_daily_telegram_left_alerts(self):
        self.assertFalse(Path("spa_core/alerts/daily_evidence_report.py").exists(),
                         "ежедневный отчёт всё ещё в spa_core/alerts/")
        self.assertTrue(Path("attic/alerts/daily_evidence_report.py").exists())

    def test_manifest_says_where_to_get_them_back(self):
        text = Path("attic/MANIFEST.md").read_text(encoding="utf-8")
        self.assertIn("weekly_evidence_report.py", text)
        self.assertIn("daily_evidence_report.py", text)
        self.assertIn("git mv attic/", text, "не сказано, как достать обратно")

    def test_the_thirty_day_report_stayed(self):
        """Обратный контроль: в архив уехали ДВА отчёта, а не три."""
        self.assertTrue(Path("scripts/generate_evidence_report.py").exists())

    def test_the_dead_root_was_left_alone_and_says_why(self):
        """Корень цепочки НЕ архивирован — он не входит в тройку отчётов.

        Замер, полученный попыткой: стоит убрать корень, и храповик немедленно
        объявляет `run_health_check` новым сиротой. Значит сегодня тот числится
        подключённым только потому, что его зовёт скрипт, который сам не зовёт
        никто. Отдельная находка и отдельное решение.
        """
        self.assertTrue(Path("scripts/run_daily_simulation.py").exists())
        self.assertTrue(Path("scripts/run_health_check.py").exists())
        wrapper = Path("scripts/run_daily_simulation.py").read_text(encoding="utf-8")
        self.assertIn("ADR-140", wrapper,
                      "снятый шаг не назван — молча исчезнувший шаг неотличим от небывшего")


if __name__ == "__main__":
    unittest.main()
