"""Брифинг обязан называть отставание git-индекса и указывать на зеркало (ADR-152).

Авария 27.08, воспроизведённая дважды за час. Сессия честно доложила владельцу
«последний ADR — 078», тогда как на origin их **129** — включая ADR-125 о старте
трёх пакетов, о котором владелец и спрашивал. Сессия не проглядела: у неё физически
не было файла. Индекс рабочего дерева отставал на **1139** коммитов.

Отставание — ШТАТНОЕ свойство, а не поломка: пуши уходят в origin напрямую через API
и локального индекса не касаются, а синхронизация возит только `spa_core/`, `scripts/`,
`tests/`, `architecture/`. `docs/` и `nimbalyst-local/` не возятся НИКОГДА и не должны —
они пишутся локально, и merge затёр бы незапушенное.

Поэтому лечение — не синхронизация рабочего дерева (она опасна и всё равно не принесла
бы `docs/`), а отдельное read-only зеркало плюс **видимая строка**: сессия должна узнать
о своей слепоте раньше, чем начнёт рассуждать по устаревшим документам.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "update_system_briefing.py"


def _mod():
    spec = importlib.util.spec_from_file_location("briefing", str(_SCRIPT))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class TestLagIsSurfaced(unittest.TestCase):

    def setUp(self):
        self.m = _mod()

    def test_the_section_names_the_lag_and_the_mirror(self):
        out = self.m.build_git_index_lag_section()
        self.assertIn("Git index vs origin", out)
        self.assertIn("отстаёт от origin/main", out)

    def test_it_is_wired_into_the_briefing(self):
        """Секция, не попавшая в сборку, не существует для читателя (урок #144)."""
        src = _SCRIPT.read_text(encoding="utf-8")
        self.assertIn("build_git_index_lag_section() +", src,
                      "секция обязана вызываться в main(), а не только существовать")

    def test_lag_is_called_normal_not_an_alarm(self):
        """Ложная тревога учит выключать проверку — отставание штатно."""
        out = self.m.build_git_index_lag_section()
        self.assertIn("штатно", out)


class TestPositiveControls(unittest.TestCase):
    """Проверка обязана краснеть на настоящих поломках, а не только зеленеть."""

    def setUp(self):
        self.m = _mod()

    def test_a_missing_mirror_is_reported_as_missing(self):
        """Сердце ADR-152: без зеркала сверяться НЕ С ЧЕМ, и это надо сказать."""
        with mock.patch.object(self.m.os.path, "isdir", return_value=False):
            out = self.m.build_git_index_lag_section()
        self.assertIn("отсутствует", out)
        self.assertIn("устаревш", out)

    def test_unmeasurable_lag_is_UNCHECKED_not_zero(self):
        """«Не смогли посмотреть» ≠ «отставания нет» (инвариант #17)."""
        with mock.patch.object(self.m.subprocess, "run",
                               side_effect=OSError("git недоступен")):
            out = self.m.build_git_index_lag_section()
        self.assertIn("НЕ ИЗМЕРЕНО", out)
        self.assertNotIn("отстаёт от origin/main на **0**", out)

    def test_the_measured_number_comes_from_git_not_a_literal(self):
        """Иначе строка показывала бы одно и то же навсегда."""
        fake = mock.Mock(returncode=0, stdout="4242\n")
        with mock.patch.object(self.m.subprocess, "run", return_value=fake):
            out = self.m.build_git_index_lag_section()
        self.assertIn("**4242**", out)


if __name__ == "__main__":
    unittest.main()
