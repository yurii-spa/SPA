#!/usr/bin/env python3
"""Правка свода правил без записи в журнал обязана быть ОТКЛОНЕНА.

Решение владельца 16.09: агент может сам коммитить свои инструкции (`CLAUDE.md`,
`.claude/rules/*.md`) — вместе со следом, а не вместо него.

**Почему проверка, а не строка в списке разрешений.** Список читается, а не исполняется:
фраза «diff трогает только эти файлы» ничего не проверяет. Условие без исполнителя держится
на внимательности, а она по ЭТОМУ месту отказывала дважды: инвариант #17 отсутствовал в
`CLAUDE.md` 16 суток (ADR-344), раздел `deployment.md` — шесть дней. Оба раза файл менялся
БЕЗ СЛЕДА.

Сцены здесь — настоящие одноразовые git-деревья: вердикт зависит от ИНДЕКСА, и проверять
его на выдуманных списках значило бы проверять не то, что исполняется в pre-commit.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "_crj", ROOT / "scripts" / "check_rules_change_is_journalled.py")
crj = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crj)


class PathsAreRecognisedInEveryForm(unittest.TestCase):
    """Опознание — не мелочь: промах здесь освобождает целый каталог молча."""

    def test_the_constitution_and_area_rules_are_instructions(self):
        for p in ("CLAUDE.md", "./CLAUDE.md",
                  ".claude/rules/adapters.md", "./.claude/rules/site-copy.md"):
            self.assertTrue(crj.is_instruction(p), p)

    def test_a_lookalike_is_not_an_instruction(self):
        """`landing/CLAUDE.md` — не конституция; `.txt` в правилах — не правило."""
        for p in ("landing/CLAUDE.md", "docs/CLAUDE.md", ".claude/rules/notes.txt",
                  ".claude/settings.json"):
            self.assertFalse(crj.is_instruction(p), p)

    def test_lstrip_would_have_freed_every_area_rule(self):
        """Положительный контроль НА СОБСТВЕННУЮ ошибку (замер 16.09).

        Первая редакция нормализовала путь через `lstrip("./")` — это НАБОР СИМВОЛОВ,
        а не префикс: у `.claude/rules/x.md` он съедает ведущую точку, путь перестаёт
        начинаться с `.claude/`, и все правила областей выпадают из-под проверки.
        Тест держит разницу, чтобы её нельзя было вернуть незаметно.
        """
        self.assertEqual(".claude/rules/x.md".lstrip("./"), "claude/rules/x.md")
        self.assertTrue(crj.is_instruction(".claude/rules/x.md"),
                        "правило области снова выпало из-под проверки")


class _Repo(unittest.TestCase):
    """Одноразовое git-дерево: вердикт решает ИНДЕКС, а не список в памяти."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="spa_crj_"))
        self._run("init", "-q", "-b", "main")
        self._run("config", "user.email", "t@t")
        self._run("config", "user.name", "t")
        (self.d / "seed.txt").write_text("seed\n", encoding="utf-8")
        self._run("add", "seed.txt")
        self._run("commit", "-q", "-m", "seed")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _run(self, *args):
        return subprocess.run(["git", *args], cwd=str(self.d), capture_output=True, text=True)

    def _write(self, rel, text):
        p = self.d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        self._run("add", rel)

    def _verdict(self):
        paths = crj.staged_files(self.d)
        return crj.verdict(paths, crj.journal_added_lines(self.d, paths))


class TheTraceIsRequiredAndMustBeReal(_Repo):
    def test_changing_the_constitution_without_a_journal_is_refused(self):
        self._write("CLAUDE.md", "# правила\nновый пункт\n")
        code, text = self._verdict()
        self.assertEqual(code, crj.EXIT_REFUSED)
        self.assertIn("CLAUDE.md", text)

    def test_changing_an_area_rule_without_a_journal_is_refused(self):
        self._write(".claude/rules/adapters.md", "# правило\nновая строка\n")
        code, _ = self._verdict()
        self.assertEqual(code, crj.EXIT_REFUSED)

    def test_a_journal_line_lets_it_through(self):
        """Обратная сторона: со следом правка проходит — иначе разрешение пустое."""
        self._write("CLAUDE.md", "# правила\nновый пункт\n")
        self._write("docs/journal/2026-W38.md", "## 16.09\nдобавил пункт X, потому что Y\n")
        code, text = self._verdict()
        self.assertEqual(code, crj.EXIT_OK, text)

    def test_an_EMPTY_journal_file_is_not_a_trace(self):
        """«Файл в коммите» и «в журнале что-то написано» — разные факты.

        Пустой журнал в наборе получить легко, ничего не написав; если бы он считался,
        условие обходилось бы одним `touch`.
        """
        self._write("docs/journal/2026-W38.md", "")
        self._write("CLAUDE.md", "# правила\nновый пункт\n")
        code, _ = self._verdict()
        self.assertEqual(code, crj.EXIT_REFUSED,
                         "пустой журнальный файл засчитан за след")

    def test_code_untouched_by_the_rule_passes(self):
        """Контроль на само население: обычная правка кода проверки не касается."""
        self._write("spa_core/x.py", "x = 1\n")
        code, _ = self._verdict()
        self.assertEqual(code, crj.EXIT_OK)


class NotMeasuredIsItsOwnOutcome(unittest.TestCase):
    """Инв. #17: «не смогли проверить» не выдаётся за «проверено, чисто»."""

    def test_outside_a_git_tree_the_cli_returns_two(self):
        d = Path(tempfile.mkdtemp(prefix="spa_crj_nogit_"))
        try:
            self.assertEqual(crj.main(["--repo", str(d)]), crj.EXIT_NOT_MEASURED)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_the_three_exit_codes_are_distinct(self):
        self.assertEqual(len({crj.EXIT_OK, crj.EXIT_REFUSED, crj.EXIT_NOT_MEASURED}), 3)


class TheCheckIsActuallyWiredIntoPreCommit(unittest.TestCase):
    """Проверка, которую никто не зовёт, — украшение (правило «проводка при рождении»)."""

    def test_the_pre_commit_hook_calls_it(self):
        src = (ROOT / "scripts" / "pre_commit_check.sh").read_text(encoding="utf-8")
        self.assertIn("check_rules_change_is_journalled.py", src)

    def test_the_hook_distinguishes_refusal_from_not_measured(self):
        """Оба исхода обязаны быть разведены: иначе третий сольётся с отказом."""
        src = (ROOT / "scripts" / "pre_commit_check.sh").read_text(encoding="utf-8")
        self.assertIn("-eq 1", src)
        self.assertIn("-eq 2", src)


if __name__ == "__main__":
    unittest.main()
