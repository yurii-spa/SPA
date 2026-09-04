#!/usr/bin/env python3
"""`worktree_of` обязана читать поле `cwd` записи, а не только её файлы (цикл #475).

**Авария, которую воспроизводит каждый тест здесь.** 2026-09-04, 03:00 местного: два
`pytest` с `ppid=1`, 96 % CPU каждый, 1 ч 03 мин стены, `cwd=/private/tmp/spa_c474`.
Заказчик — сессия `cycle-20144`, pid 20144 — измеренно мёртв (`ps` пуст). Сторож
`scripts/check_concurrent_pytest.py`, написанный циклом #417 РОВНО про таких сирот,
ответил не «ОСИРОТЕВШИЙ ПРОГОН», а «дерево /tmp/spa_c474 не объявлено в журнале —
заказчик НЕ НАЗВАН», то есть UNMEASURED. Восьмой случай класса подряд нашли ГЛАЗАМИ.

Ответ лежал в самой записи. `log_session_change` пишет поле `cwd` ТОЛЬКО когда среди
объявленных путей есть относительный — то есть ровно тогда, когда из файлов дерево не
выводится (см. его `_announce_cwd`). Поле завели 24.08 для шага 0a, и читал его РОВНО
ОДИН потребитель — `declaring_tree`. Второму, `classify_orphan`, тот же факт не дали:
он спрашивал дерево у файлов и получал «не названо». Источник без всех своих
потребителей — тот же класс, что измеритель без читателя.

**Почему проверки здесь не опираются на двойника.** У `scripts/tests/test_check_concurrent_pytest.py`
есть `_FakeOwner`, и его `worktree_of` — КОПИЯ настоящей реализации. Двойник, повторяющий
предмет, не способен покраснеть от дефекта предмета: с ним сторож оставался зелёным всё
время, пока настоящий `worktree_of` молчал. Поэтому здесь соседом выступает НАСТОЯЩИЙ
`scripts/check_undelivered_work.py`.

**Личность процесса — по правилу `.claude/rules/deployment.md`, без литеральных pid.**
Там, где нужен ЖИВОЙ номер, берётся `os.getpid()` (жив на любом хосте по построению).
Там, где нужен МЁРТВЫЙ держатель, номер остаётся своим и живым, а расходится ОТМЕТКА
СТАРТА — тогда вердикт «процесса больше нет» приходит из проверки тождества, а не из
везения с занятым номером, и тест одинаков на каждой машине.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    """Скрипты лежат вне пакета — грузим по пути и КЛАДЁМ В sys.modules.

    Без записи в `sys.modules` `@dataclass` внутри модуля не находит собственное
    пространство имён и падает на импорте (замерено при написании этих тестов)."""
    spec = importlib.util.spec_from_file_location(name, _REPO_ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


owner = _load("check_undelivered_work", "scripts/check_undelivered_work.py")
ccp = _load("check_concurrent_pytest", "scripts/check_concurrent_pytest.py")

# Дерево аварии. Именно ЭТА пара форм и разошлась: macOS отдаёт `cwd` через `/private`,
# git регистрирует то же дерево без него. Нормализация — часть предмета проверки.
INCIDENT_CWD = "/private/tmp/spa_c474"
INCIDENT_TREE = "/tmp/spa_c474"


def _ps_start_of(pid: int) -> str:
    """Отметка старта ЖИВОГО процесса, снятая у ТОЙ ЖЕ двери, которой потом ответит код."""
    return owner._ps_lstart(pid)


def _announce(*, files, cwd=None, session="cycle-20144", session_pid=None,
              session_pid_start=None, ts="2026-09-03T23:22:11Z"):
    """Запись журнала в той же форме, в какой её пишет `log_session_change.record`.

    `ts` литерален НАМЕРЕННО и предметом не является: сравнений со «сейчас» ни одна
    проверка здесь не делает — судится ТОЖДЕСТВО процесса, а не свежесть записи.
    """
    entry = {"ts": ts, "session": session, "files": list(files)}
    if cwd is not None:
        entry["cwd"] = cwd
    if session_pid is not None:
        entry["session_pid"] = session_pid
    if session_pid_start is not None:
        entry["session_pid_start"] = session_pid_start
    return entry


# ── 1. сам источник: поле `cwd` называет дерево ──────────────────────────────

class TestWorktreeOfReadsAnnounceCwd(unittest.TestCase):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ. Каждый тест класса краснеет на коде до #475."""

    def test_relative_files_plus_cwd_name_the_tree(self):
        """Дословная запись цикла #474: пути относительные, дерево названо полем `cwd`."""
        entry = _announce(files=["spa_core/owner_queue/owner_answer.py",
                                 "scripts/orchestrator_queue.py"],
                          cwd=INCIDENT_CWD)
        self.assertEqual(owner.worktree_of(entry), INCIDENT_TREE)

    def test_cwd_goes_through_the_same_door_as_paths(self):
        """`/private/tmp/...` обязан свестись к тому же дереву, что и путь внутри него.

        Иначе сверка `worktree_of(запись) == дерево процесса` не сошлась бы ни разу:
        `lsof` отдаёт `cwd` с `/private`, а `tree_of_path` — так, как дерево зарегистрировал git."""
        from_cwd = owner.worktree_of(_announce(files=["a.py"], cwd=INCIDENT_CWD))
        from_path = owner.tree_of_path(f"{INCIDENT_CWD}/spa_core/x.py")
        self.assertEqual(from_cwd, from_path)

    def test_empty_file_list_still_reads_the_cwd(self):
        """Объявление с пустым списком файлов — известный род записи, и дерево у неё есть."""
        self.assertEqual(owner.worktree_of(_announce(files=[], cwd=INCIDENT_CWD)),
                         INCIDENT_TREE)


# ── 2. сужения: чего поле `cwd` делать НЕ должно ─────────────────────────────

class TestCwdNeverWidensTheAnswer(unittest.TestCase):
    """Обратный контроль: починка не имеет права снять ни одного прежнего отказа."""

    def test_files_win_over_cwd(self):
        """Сужение 1. Дерево, выведенное из путей, поле `cwd` не переопределяет НИКОГДА."""
        entry = _announce(files=[f"{INCIDENT_TREE}/spa_core/x.py"],
                          cwd="/private/tmp/spa_c999")
        self.assertEqual(owner.worktree_of(entry), INCIDENT_TREE)

    def test_two_trees_in_files_stay_a_refusal(self):
        """Сужение 2. Неоднозначность — это ОТКАЗ, а не пробел, и `cwd` его не снимает.

        Запись, объявившая файлы в двух деревьях, дерева не имеет (в живом журнале таких
        ярлыков 26 из 630). Если бы `cwd` её «спасал», правило «не угадывать» уходило бы
        с чёрного хода."""
        entry = _announce(files=[f"{INCIDENT_TREE}/spa_core/a.py",
                                 "/tmp/spa_c473/spa_core/b.py"],
                          cwd=INCIDENT_CWD)
        self.assertIsNone(owner.worktree_of(entry))

    def test_entry_without_cwd_is_unchanged(self):
        """Сужение 3, fail-CLOSED. Нет поля — прежний ответ «дерево не названо»."""
        self.assertIsNone(owner.worktree_of(_announce(files=["notes.md"])))
        self.assertIsNone(owner.worktree_of(_announce(files=[])))

    def test_relative_cwd_is_not_an_answer(self):
        """Относительный `cwd` сам требует базы и на вопрос «какое дерево» не отвечает."""
        for bad in ("tmp/spa_c474", "", "   ", None):
            with self.subTest(cwd=bad):
                self.assertIsNone(owner.worktree_of(_announce(files=["a.py"], cwd=bad)))

    def test_non_string_cwd_does_not_crash_the_guard(self):
        """Битая запись обязана дать «не измерено», а не уронить сторожа."""
        for bad in (123, ["/tmp/x"], {"path": "/tmp/x"}):
            with self.subTest(cwd=bad):
                self.assertIsNone(owner.worktree_of(_announce(files=["a.py"], cwd=bad)))


# ── 3. ПРОВОДКА: доходит ли факт до того, кто выносит вердикт ────────────────

class TestOrphanVerdictReachesTheRealWiring(unittest.TestCase):
    """Проверяется ФОРМА ВЫЗОВА, а не наличие функции: идём через `classify_orphan`
    с НАСТОЯЩИМ соседом. С двойником, копирующим `worktree_of`, эти тесты зелены
    даже на сломанном предмете — ровно поэтому они здесь, а не рядом с двойником."""

    def _proc(self):
        """Сегодняшний сирота: родителя нет, дерево — то самое."""
        proc = ccp.PytestProc(pid=os.getpid(), ppid=1,
                              lstart="Fri Sep  4 01:57:05 2026",
                              command="python3 -m pytest tests/ spa_core/tests/ -q")
        proc.cwd = INCIDENT_CWD
        return proc

    def test_dead_requester_is_named_an_orphan(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ аварии 2026-09-04. До #475 здесь было UNMEASURED.

        Номер держателя — свой, ЖИВОЙ (`os.getpid()`); мёртвым его делает РАСХОЖДЕНИЕ
        отметки старта, то есть проверка тождества, а не везение со свободным номером.
        Поэтому тест судит об одном и том же на каждом хосте."""
        entry = _announce(files=["spa_core/owner_queue/owner_answer.py"],
                          cwd=INCIDENT_CWD,
                          session_pid=os.getpid(),
                          session_pid_start="Thu Aug 28 10:00:00 2026")
        verdict, why = ccp.classify_orphan(self._proc(), owner=owner, entries=[entry])
        self.assertEqual(verdict, ccp.ORPHAN, why)
        self.assertIn("cycle-20144", why)
        self.assertIn(INCIDENT_TREE, why)

    def test_live_requester_is_not_called_an_orphan(self):
        """Обратный контроль: починка не имеет права объявить сиротой ожидаемый прогон.

        Здесь и номер, и отметка старта — настоящие, снятые у той же двери."""
        pid = os.getpid()
        entry = _announce(files=["spa_core/owner_queue/owner_answer.py"],
                          cwd=INCIDENT_CWD,
                          session_pid=pid,
                          session_pid_start=_ps_start_of(pid))
        verdict, why = ccp.classify_orphan(self._proc(), owner=owner, entries=[entry])
        self.assertEqual(verdict, ccp.ATTENDED, why)

    def test_unrelated_tree_still_unmeasured(self):
        """Fail-CLOSED цел: запись о ЧУЖОМ дереве заказчиком этого прогона не становится."""
        entry = _announce(files=["spa_core/owner_queue/owner_answer.py"],
                          cwd="/private/tmp/spa_c473",
                          session_pid=os.getpid(),
                          session_pid_start="Thu Aug 28 10:00:00 2026")
        verdict, _why = ccp.classify_orphan(self._proc(), owner=owner, entries=[entry])
        self.assertEqual(verdict, ccp.UNMEASURED)

    def test_live_parent_is_never_an_orphan(self):
        """Порядок вопросов не тронут: живой родитель отвечает раньше журнала."""
        proc = self._proc()
        proc.ppid = os.getpid()
        verdict, _why = ccp.classify_orphan(proc, owner=owner, entries=[])
        self.assertEqual(verdict, ccp.ATTENDED)


if __name__ == "__main__":
    unittest.main()
