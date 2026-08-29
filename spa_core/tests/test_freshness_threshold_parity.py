"""Сверка двух домов срока годности (ADR-158 / карточка «порог живёт в двух местах»).

Каждый тест — воспроизведение реального свойства, замеренного 28.08, а не выдумка:

  1. Порог хранится в ДВУХ местах — `manifest.produces[].slo_hours` и
     `AGENT_OUTPUT_FILES` в `uptime_monitor.py`. Сверки между ними не было ни одной.
  2. На живом дереве сверка сразу нашла настоящее расхождение: `com.spa.daily_cycle`
     монитор судит по `data/paper_trading_status.json`, которого НЕТ среди объявленных
     продуктов агента в манифесте.
  3. Главное свойство конструкции: при ПУСТОМ пересечении вердикт обязан быть
     «сравнивать нечего», а не «всё сошлось». Зелёный вердикт на пустом множестве —
     сторож, который не может сработать.
"""
from __future__ import annotations

import unittest

from spa_core.monitoring import freshness_threshold_parity as p


class TestFindsRealDivergence(unittest.TestCase):
    def test_same_artifact_different_hours_is_recorded_not_alarmed(self):
        """ИЗМЕНЁН НАМЕРЕННО 29.08 (инв. #16), прежнее имя —
        `test_same_artifact_different_hours_is_a_finding`.

        Тест закреплял правило «разные числа = находка». Правило оказалось неверным:
        окно живости и срок годности продукта отвечают на РАЗНЫЕ вопросы, а свежесть
        продукта против `slo_hours` сторожит проверка B2 напрямую, каждые 6 ч. Посылка
        «продукт протухнет незамеченным» ложна. На исправном флоте правило давало 12
        находок из 12 — то есть краснело на ВЕРНОЕ состояние.

        Проверка не отключена: числа считаются и лежат в отчёте, а предмет сверки сужен
        до тождества файла (`different_artifact`), где разногласие настоящее.
        """
        r = p.compare({"a": {"data/x.json": 3.0}}, {"a": ("data/x.json", 6.0)})
        self.assertEqual(r["verdict"], p.AGREES)
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["threshold_notes"][0]["manifest_hours"], 3.0)
        self.assertEqual(r["threshold_notes"][0]["monitor_hours"], 6.0)

    def test_different_artifact_for_the_same_agent_is_a_finding(self):
        """Авария, найденная на живом дереве: живость `daily_cycle` судят по файлу,
        которого нет в его объявленном контракте."""
        r = p.compare({"a": {"data/declared.json": 3.0}}, {"a": ("data/watched.json", 3.0)})
        self.assertEqual(r["verdict"], p.DIFFERENT_ARTIFACT)

    def test_agreement_is_silent(self):
        """Обратный контроль: сошлись — молчим."""
        r = p.compare({"a": {"data/x.json": 3.0}}, {"a": ("data/x.json", 3.0)})
        self.assertEqual(r["verdict"], p.AGREES)
        self.assertEqual(r["findings"], [])


class TestEmptyIntersectionIsItsOwnAnswer(unittest.TestCase):
    """Главный тест конструкции."""

    def test_no_overlap_is_not_compared_not_agreement(self):
        r = p.compare({"a": {"data/x.json": 3.0}}, {"b": ("data/y.json", 3.0)})
        self.assertEqual(r["compared"], 0)
        self.assertEqual(r["verdict"], p.NOT_COMPARED)
        self.assertNotEqual(r["verdict"], p.AGREES,
                            "пустое пересечение, объявленное согласием, — сторож, "
                            "который не может сработать")

    def test_both_sources_empty_is_also_not_compared(self):
        self.assertEqual(p.compare({}, {})["verdict"], p.NOT_COMPARED)


class TestToleranceIsForArithmeticNotForSlack(unittest.TestCase):
    def test_rounding_noise_does_not_fire(self):
        """1800 секунд → 0.5 ч: перевод не обязан давать находку."""
        r = p.compare({"a": {"data/x.json": 0.5}}, p.monitor_thresholds({"a": ("data/x.json", 1800)}))
        self.assertEqual(r["verdict"], p.AGREES)

    def test_a_real_difference_is_not_swallowed(self):
        """ИЗМЕНЁН НАМЕРЕННО 29.08 (инв. #16) вместе с тестом выше — та же причина.

        Смысл контроля сохранён и даже усилен: настоящая разница чисел не должна
        ПРОПАДАТЬ. Она и не пропадает — она записана. Изменилось только то, кем
        она считается: наблюдением, а не аварией. Допуск по-прежнему защищает лишь
        от арифметики с плавающей точкой, а не даёт люфт.
        """
        r = p.compare({"a": {"data/x.json": 0.5}}, {"a": ("data/x.json", 0.6)})
        self.assertEqual(r["findings"], [])
        self.assertEqual(len(r["threshold_notes"]), 1)


class TestMonitorParsing(unittest.TestCase):
    def test_entries_without_a_file_are_skipped(self):
        """`(None, 0)` — демон, судимый по PID/порту, а не по файлу."""
        self.assertEqual(p.monitor_thresholds({"d": (None, 0)}), {})

    def test_seconds_become_hours(self):
        self.assertEqual(p.monitor_thresholds({"a": ("data/x.json", 3600)}), {"a": ("data/x.json", 1.0)})


class TestLiveTreeStillHasTheKnownFinding(unittest.TestCase):
    """Положительный контроль на ЖИВОМ дереве — иначе тест проверял бы фикстуру."""

    def test_live_audit_runs_and_reports_a_verdict(self):
        r = p.audit()
        self.assertIn(r["verdict"], (p.AGREES, p.NOT_COMPARED,
                                     p.THRESHOLD_MISMATCH, p.DIFFERENT_ARTIFACT))
        self.assertGreater(r["manifest_agents"], 0, "манифест обязан давать сроки")
        self.assertGreater(r["monitor_agents"], 0, "карта монитора обязана давать сроки")


if __name__ == "__main__":
    unittest.main()


class TwoNumbersAnswerTwoDifferentQuestions(unittest.TestCase):
    """Сверка выдала 12 «расхождений» на ИСПРАВНОМ флоте — дефект был в ней самой.

    Порог `uptime_monitor` отвечает «ЖИВ ЛИ АГЕНТ» и выводится из расписания с запасом
    1.25–1.5 такта, чтобы один пропуск не мигал. `slo_hours` манифеста отвечает «СВЕЖ ЛИ
    ПРОДУКТ ДЛЯ ПОТРЕБИТЕЛЯ» и назначается двумя ролями по цене опоздания (ADR-158).

    Я сузил проверку дважды за день. Сначала счёл дефектом случай «монитор лояльнее»:
    продукт протухает через 26 ч, а тревога о молчании — через 36 ч. Посылка «десять
    часов никто не знает» оказалась ЛОЖНОЙ: свежесть продукта против `slo_hours`
    сторожит проверка B2 каждые 6 ч и напрямую. Соотношения между окнами не требуется
    ни в какую сторону — это ровно ошибка «три вопроса — три сторожа» из
    .claude/rules/deployment.md, допущенная в собственной проверке.
    """

    def test_looser_monitor_is_not_a_finding_because_B2_watches_the_product(self):
        r = p.compare({"a": {"data/x.json": 26.0}}, {"a": ("data/x.json", 36.0)})
        self.assertEqual(r["findings"], [])
        self.assertEqual(len(r["threshold_notes"]), 1)

    def test_stricter_monitor_is_not_a_finding_either(self):
        r = p.compare({"a": {"data/x.json": 168.0}}, {"a": ("data/x.json", 1.0)})
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["verdict"], p.AGREES)

    def test_the_difference_is_recorded_so_checked_is_not_unchecked(self):
        """«Сверено, соотношение такое-то» не должно быть неотличимо от «не сверяли»."""
        r = p.compare({"a": {"data/x.json": 26.0}}, {"a": ("data/x.json", 36.0)})
        self.assertEqual(r["compared"], 1)
        self.assertIn("НОРМА", r["threshold_notes"][0]["note"])

    def test_equal_numbers_produce_no_note_at_all(self):
        r = p.compare({"a": {"data/x.json": 26.0}}, {"a": ("data/x.json", 26.0)})
        self.assertEqual(r["threshold_notes"], [])
        self.assertEqual(r["findings"], [])

    def test_different_file_is_the_one_real_subject_left(self):
        """Сужение не тронуло предмет, где разногласие настоящее — тождество файла."""
        r = p.compare({"a": {"data/x.json": 26.0}}, {"a": ("data/y.json", 26.0)})
        self.assertEqual([f["verdict"] for f in r["findings"]], [p.DIFFERENT_ARTIFACT])
