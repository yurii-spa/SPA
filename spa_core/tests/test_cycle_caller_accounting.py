"""Обёртка цикла записывает, кто её позвал.

08.08 дневной цикл отработал **8 раз не по расписанию**, и кто именно его звал —
система не записывала. Разбор в тот день дважды упёрся в догадки.

Риск не теоретический: сессия, умершая в пределах двух часов до 08:00, может стоить
дня трека — а трек дорисовывать запрещено, значит потеря необратима. Без имени
вызывающего чинить нечего.

Владелец выбрал 09.08 вариант 1: **учёт, а не запрет**. Сессиям по-прежнему можно
звать живой цикл (вчерашний внеплановый прогон 09:50 дал диагноз, легший в ADR-073 —
польза была настоящей). Сначала факты, через неделю по ним решаем про запрет.

Тесты держат три вещи: строка существует, различает расписание и ручной вызов, и —
главное — **учёт не может уронить цикл**. Лечение, опаснее болезни, здесь означало бы
потерю дня трека из-за строчки логирования.
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

_WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "run_daily_paper_cycle.sh"


class TestAccountingExists(unittest.TestCase):

    def setUp(self):
        self.text = _WRAPPER.read_text(encoding="utf-8")

    def test_the_caller_line_is_emitted(self):
        self.assertIn("CYCLE_CALLER", self.text,
                      "без метки разбор снова упрётся в догадки")

    def test_it_records_the_parent_process(self):
        """Имя и аргументы родителя — это и есть ответ на «кто звал»."""
        self.assertIn("$PPID", self.text)
        self.assertRegex(self.text, r"ps -o comm= -p")
        self.assertRegex(self.text, r"ps -o args= -p")

    def test_it_separates_scheduled_from_ad_hoc(self):
        """Без различения счёт «8 прогонов» снова ничего не скажет."""
        self.assertIn("scheduled", self.text)
        self.assertIn("ad-hoc", self.text)
        self.assertIn("launchd", self.text)

    def test_the_line_reaches_both_the_log_and_stdout(self):
        """`tee` обязателен: launchd-stdout — то, по чему судят о живости агента."""
        m = re.search(r"CYCLE_CALLER[^\n]*", self.text)
        self.assertIn('tee -a "$LOG_FILE"', m.group(0))


class TestAccountingCannotBreakTheCycle(unittest.TestCase):
    """Сторона, где ошибка стоит дня трека."""

    def setUp(self):
        self.text = _WRAPPER.read_text(encoding="utf-8")

    def test_the_wrapper_is_still_valid_bash(self):
        r = subprocess.run(["bash", "-n", str(_WRAPPER)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_failures_of_ps_are_swallowed(self):
        """`ps` может не ответить; цикл от этого не имеет права не начаться."""
        block = self.text[self.text.index("CALLER_NAME="):self.text.index("CYCLE_CALLER")]
        self.assertEqual(block.count("2>/dev/null"), 2,
                         "оба вызова ps обязаны глушить ошибку")
        self.assertIn("|| true", block)

    def test_an_unmeasurable_caller_is_recorded_not_fatal(self):
        """Пустой ответ `ps` не ломает строку и не роняет цикл.

        Правлено 10.08 (обоснование обязательно, `CLAUDE.md` §16; журнал W32).
        Состояния «unknown» больше НЕТ, и это не ослабление, а следствие починки
        самого признака: он перестал зависеть от `ps`. Раньше вердикт выводился из
        родителя, и «`ps` промолчал» было третьим исходом. Теперь вердикт — метка
        окружения: она либо есть (расписание), либо нет (ручной запуск), и третьего
        состояния тут быть не может.

        Проверяемое свойство сохранено полностью: имя родителя по-прежнему остаётся
        справочным полем и по-прежнему не роняет строку, когда `ps` промолчал.
        """
        self.assertIn("${CALLER_NAME:-?}", self.text)
        self.assertIn("ppid=$PPID", self.text)

    def test_no_set_e_was_introduced(self):
        """Обёртка намеренно без `set -e` — учёт не смеет это менять.

        Ищем исполняемую строку, а не упоминание: в шапке `set -e` назван в
        комментарии, объясняющем, почему его нет.
        """
        executable = [ln.strip() for ln in self.text.splitlines()
                      if ln.strip() and not ln.strip().startswith("#")]
        self.assertFalse([ln for ln in executable if re.match(r"set\s+-[a-z]*e", ln)],
                         "включение set -e оборвало бы цикл на первой мелкой ошибке")


class TestItActuallyClassifies(unittest.TestCase):
    """Положительный контроль: логика запускается, а не только читается глазами."""

    def _classify(self, comm: str) -> str:
        script = (
            f'CALLER_NAME="{comm}"; '
            'case "${CALLER_NAME##*/}" in launchd) K=scheduled;; "") K=unknown;; '
            '*) K=ad-hoc;; esac; printf "%s" "$K"')
        return subprocess.run(["bash", "-c", script], capture_output=True,
                              text=True).stdout

    def test_launchd_is_scheduled(self):
        self.assertEqual(self._classify("/sbin/launchd"), "scheduled")
        self.assertEqual(self._classify("launchd"), "scheduled")

    def test_a_shell_is_ad_hoc(self):
        self.assertEqual(self._classify("/bin/zsh"), "ad-hoc")

    def test_empty_is_unknown(self):
        self.assertEqual(self._classify(""), "unknown")


if __name__ == "__main__":
    unittest.main()
