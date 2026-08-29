"""Цель агента из заголовка обёртки — третий источник паспорта (ADR-154, 29.08).

Замер: у 16 агентов из 95 не было деловой цели, потому что их точка входа — не один
python-модуль с докстрингом, а многошаговый shell-скрипт. При этом автор КАЖДОЙ такой
обёртки написал в её шапке, зачем она нужна, — то есть источник существовал и не
читался. После подключения: цели нет у 4, и это честные 4.

Главное здесь — не находки, а ОТКАЗ. Шапка обёртки часто описывает МЕХАНИЗМ запуска
(«launchd wrapper for com.spa.dashboard», «launchd CANNOT exec miniconda-python»), и
такая «цель» ХУЖЕ пустой: выглядит знанием, а на вопрос «зачем он есть» не отвечает.
Ровно этот класс уже стоил цикла 28.08, когда наивный выводитель выдал `inbox_watch`
цель из докстринга служебного `log_session_change`.

Второй закреплённый принцип — ПОРЯДОК источников: заголовок спрашивается только там,
где докстринг молчит, поэтому новый источник не может отнять уже выведенную цель.
Регрессия невозможна по построению, а не по внимательности (сверка по всем 95:
регрессий 0, находок 20).
"""
from __future__ import annotations

import importlib.util
import textwrap
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_fap", _REPO / "scripts" / "fill_agent_passports.py")
fap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fap)


def _wrapper(tmp: Path, name: str, body: str) -> str:
    (tmp / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp / "scripts" / name).write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    fap.REPO = tmp
    return name


class GoalIsReadFromTheWrapperHeader(unittest.TestCase):
    def setUp(self):
        self._repo = fap.REPO
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        fap.REPO = self._repo

    def test_title_line_is_the_goal(self):
        n = _wrapper(self.tmp, "a.sh", """
            #!/bin/bash
            # scripts/a.sh — DAILY snapshot of ALL data/*.json into data/backups/.
            set -e
        """)
        self.assertEqual(fap.goal_from_wrapper_header(n),
                         "DAILY snapshot of ALL data/*.json into data/backups/.")

    def test_decorative_frame_is_not_prose(self):
        n = _wrapper(self.tmp, "b.sh", """
            #!/bin/bash
            # ============================================================
            # scripts/b.sh — событийный ЛЁГКИЙ интейк Inbox.
            # ============================================================
        """)
        self.assertEqual(fap.goal_from_wrapper_header(n), "событийный ЛЁГКИЙ интейк Inbox.")

    def test_wrapped_sentence_is_joined(self):
        """Строчная буква в начале строки — продолжение фразы, её надо доклеить."""
        n = _wrapper(self.tmp, "c.sh", """
            #!/bin/bash
            # c.sh — reads tunnel token from Keychain, finds cloudflared
            # binary across common install paths, and execs the tunnel.
        """)
        self.assertIn("execs the tunnel.", fap.goal_from_wrapper_header(n))

    def test_new_sentence_is_not_glued_without_punctuation(self):
        """Прописная — уже НОВАЯ фраза; сшивать её без знака нельзя, дописывать точку — выдумывать."""
        n = _wrapper(self.tmp, "d.sh", """
            #!/bin/bash
            # d.sh — claude-code-kanban backup monitor (ENV_SETUP v3 §4.1)
            # Read-only web monitor over ~/.claude (tasks/teams/sessions).
        """)
        self.assertEqual(fap.goal_from_wrapper_header(n),
                         "claude-code-kanban backup monitor (ENV_SETUP v3 §4.1)")


class RefusalIsTheMainFeature(unittest.TestCase):
    """Выводитель ОБЯЗАН отказываться: чужая/механическая цель хуже пустой."""

    def setUp(self):
        self._repo = fap.REPO
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        fap.REPO = self._repo

    def test_pure_mechanism_header_yields_nothing(self):
        """Настоящий com.spa.dashboard: вся шапка про запуск и ни слова о деле."""
        n = _wrapper(self.tmp, "e.sh", """
            #!/bin/bash
            # scripts/e.sh - launchd wrapper for com.spa.dashboard
            # Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
            # launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
            # Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
        """)
        self.assertEqual(fap.goal_from_wrapper_header(n), "",
                         "механизм запуска — не деловая цель; пустое честнее")

    def test_mechanism_line_is_skipped_but_real_goal_below_is_found(self):
        """Настоящий com.spa.work_digest: механика сверху, дело — строкой ниже."""
        n = _wrapper(self.tmp, "f.sh", """
            #!/bin/bash
            # scripts/f.sh — launchd wrapper for com.spa.work_digest
            # «Что сделано за вчера» (РАБОТА/девелопмент, простым языком) → Telegram, 09:00.
        """)
        self.assertEqual(
            fap.goal_from_wrapper_header(n),
            "«Что сделано за вчера» (РАБОТА/девелопмент, простым языком) → Telegram, 09:00.")

    def test_interpreter_and_missing_program_are_not_files(self):
        for prog in ("python3", "bash", None, "нет-такого-файла.sh"):
            self.assertEqual(fap.goal_from_wrapper_header(prog), "", prog)


class SourceOrderMakesRegressionImpossible(unittest.TestCase):
    """Заголовок спрашивается ТОЛЬКО там, где докстринг молчит."""

    def test_docstring_wins_over_wrapper_header(self):
        entry = {"program": "daily_backup.sh"}
        real = fap.goal_from_docstring
        try:
            fap.goal_from_docstring = lambda _m: "цель из докстринга"
            self.assertEqual(fap.derive(entry)["goal"], "цель из докстринга")
        finally:
            fap.goal_from_docstring = real

    def test_wrapper_header_fills_only_the_silence(self):
        real = fap.goal_from_docstring
        try:
            fap.goal_from_docstring = lambda _m: ""
            got = fap.derive({"program": "daily_backup.sh"})["goal"]
        finally:
            fap.goal_from_docstring = real
        self.assertTrue(got, "докстринг молчит — заголовок обёртки обязан ответить")


if __name__ == "__main__":
    unittest.main()
