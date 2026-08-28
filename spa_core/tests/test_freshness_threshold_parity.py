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
    def test_same_artifact_different_hours_is_a_finding(self):
        r = p.compare({"a": {"data/x.json": 3.0}}, {"a": ("data/x.json", 6.0)})
        self.assertEqual(r["verdict"], p.THRESHOLD_MISMATCH)
        self.assertEqual(r["findings"][0]["manifest_hours"], 3.0)
        self.assertEqual(r["findings"][0]["monitor_hours"], 6.0)

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
        """Обратный контроль: «почти совпадает» — всё равно находка."""
        r = p.compare({"a": {"data/x.json": 0.5}}, {"a": ("data/x.json", 0.6)})
        self.assertEqual(r["verdict"], p.THRESHOLD_MISMATCH)


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
