#!/usr/bin/env python3
"""Tests for scripts/check_concurrent_pytest.py — pre-flight pytest collision check.

Covers the two documented hazards separately (journal, cycle #352 / #377):
  * same-cwd collision (data corruption risk) -> MUST be reported as
    'collision' and exit 1.
  * different-cwd concurrent runs (maybe-slow, not corruption) -> reported
    as informational 'clear', exit 0.
  * ps enumeration failure -> fail-CLOSED 'unmeasured', exit 2 (never silently
    reads as 'clear').

All subprocess calls are mocked — no real ps/lsof dependency, deterministic.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from scripts import check_concurrent_pytest as ccp  # noqa: E402


def _ps_line(pid: int, command: str, ppid: int = 42) -> str:
    # ps -o pid=,ppid=,lstart=,command= — lstart is a fixed 5-token ctime string.
    #
    # ppid добавлен в формат вместе с проверкой сирот (цикл #417). Правка
    # ОСОЗНАННАЯ (инв. #16): она не ослабляет ни одной проверки — ни одного
    # assert не снято и не сужено, изменился только вход, который эти assert
    # получают. Умолчание 42 (родитель жив) выбрано намеренно: старые тесты
    # проверяли столкновение, а не сиротство, и должны продолжать судить
    # именно о нём.
    return f"{pid} {ppid} Thu Aug 28 10:00:00 2026 {command}"


class TestListPytestProcesses(unittest.TestCase):
    def test_parses_pytest_lines(self):
        raw = "\n".join([
            _ps_line(111, "python3 -m pytest spa_core/tests/ -q"),
            _ps_line(222, "/bin/bash -c sleep 10"),  # not pytest — must be excluded
        ])
        with mock.patch.object(ccp, "_run", return_value=raw):
            procs = ccp.list_pytest_processes()
        self.assertEqual([p.pid for p in procs], [111])

    def test_excludes_self_pid(self):
        raw = _ps_line(999, "python3 -m pytest tests/")
        with mock.patch.object(ccp, "_run", return_value=raw):
            procs = ccp.list_pytest_processes(self_pid=999)
        self.assertEqual(procs, [])

    def test_excludes_own_tool_invocation(self):
        # A sibling invocation of THIS checker must never self-report as a
        # 'pytest' collision (its argv contains 'pytest' as a substring of
        # the script name it inspects, not an actual pytest run).
        raw = _ps_line(333, "python3 scripts/check_concurrent_pytest.py --cwd /x")
        with mock.patch.object(ccp, "_run", return_value=raw):
            procs = ccp.list_pytest_processes()
        self.assertEqual(procs, [])

    def test_ps_failure_returns_none(self):
        with mock.patch.object(ccp, "_run", return_value=None):
            procs = ccp.list_pytest_processes()
        self.assertIsNone(procs)

    def test_malformed_line_skipped_not_crashed(self):
        raw = "not-a-pid garbage line without enough tokens"
        with mock.patch.object(ccp, "_run", return_value=raw):
            procs = ccp.list_pytest_processes()
        self.assertEqual(procs, [])


class TestResolveCwd(unittest.TestCase):
    def test_parses_lsof_n_line(self):
        with mock.patch.object(ccp, "_run", return_value="p123\nn/tmp/some_tree\n"):
            cwd = ccp.resolve_cwd(123)
        self.assertEqual(cwd, "/tmp/some_tree")

    def test_lsof_failure_returns_none(self):
        with mock.patch.object(ccp, "_run", return_value=None):
            cwd = ccp.resolve_cwd(123)
        self.assertIsNone(cwd)


class TestCheck(unittest.TestCase):
    def _mk_proc(self, pid, cwd, command="python3 -m pytest spa_core/tests/"):
        return ccp.PytestProc(pid=pid, lstart="Thu Aug 28 10:00:00 2026", command=command)

    def test_same_cwd_is_collision(self):
        target = "/tmp/tree_a"
        procs = [self._mk_proc(111, target)]
        with mock.patch.object(ccp, "list_pytest_processes", return_value=procs), \
             mock.patch.object(ccp, "resolve_cwd", return_value=target):
            report = ccp.check(target)
        self.assertEqual(report["status"], "collision")
        self.assertEqual(len(report["same_cwd"]), 1)
        self.assertEqual(report["same_cwd"][0]["pid"], 111)

    def test_different_cwd_is_clear_not_collision(self):
        target = "/tmp/tree_a"
        procs = [self._mk_proc(111, "/tmp/tree_b")]
        with mock.patch.object(ccp, "list_pytest_processes", return_value=procs), \
             mock.patch.object(ccp, "resolve_cwd", return_value="/tmp/tree_b"):
            report = ccp.check(target)
        self.assertEqual(report["status"], "clear")
        self.assertEqual(len(report["same_cwd"]), 0)
        self.assertEqual(len(report["other_cwd"]), 1)

    def test_no_processes_is_clear(self):
        with mock.patch.object(ccp, "list_pytest_processes", return_value=[]):
            report = ccp.check("/tmp/tree_a")
        self.assertEqual(report["status"], "clear")

    def test_ps_enumeration_failure_is_unmeasured_not_clear(self):
        # Fail-CLOSED: an unmeasured state must NEVER read as 'clear' — a
        # broken ps/lsof toolchain must not masquerade as "no collision".
        with mock.patch.object(ccp, "list_pytest_processes", return_value=None):
            report = ccp.check("/tmp/tree_a")
        self.assertEqual(report["status"], "unmeasured")

    def test_unresolved_cwd_process_is_not_silently_dropped(self):
        target = "/tmp/tree_a"
        procs = [self._mk_proc(111, None)]
        with mock.patch.object(ccp, "list_pytest_processes", return_value=procs), \
             mock.patch.object(ccp, "resolve_cwd", return_value=None):
            report = ccp.check(target)
        self.assertEqual(report["status"], "clear")  # not a collision (unproven)
        self.assertEqual(len(report["unresolved"]), 1)  # but visible, not lost

    def test_relative_and_symlinked_cwd_paths_normalised(self):
        # os.path.realpath must be applied on BOTH sides, else a target passed
        # with a trailing slash or via a symlinked /tmp path would falsely
        # miss a genuine same-directory collision.
        procs = [self._mk_proc(111, "/tmp/tree_a/")]
        with mock.patch.object(ccp, "list_pytest_processes", return_value=procs), \
             mock.patch.object(ccp, "resolve_cwd", return_value="/tmp/tree_a/"):
            report = ccp.check("/tmp/tree_a")
        self.assertEqual(report["status"], "collision")


class TestMainExitCodes(unittest.TestCase):
    def test_collision_exit_1(self):
        with mock.patch.object(ccp, "check", return_value={
            "status": "collision", "target_cwd": "/x", "same_cwd": [], "other_cwd": [], "unresolved": [],
        }):
            rc = ccp.main(["--cwd", "/x"])
        self.assertEqual(rc, 1)

    def test_clear_exit_0(self):
        with mock.patch.object(ccp, "check", return_value={
            "status": "clear", "target_cwd": "/x", "same_cwd": [], "other_cwd": [], "unresolved": [],
        }):
            rc = ccp.main(["--cwd", "/x"])
        self.assertEqual(rc, 0)

    def test_unmeasured_exit_2(self):
        with mock.patch.object(ccp, "check", return_value={
            "status": "unmeasured", "reason": "boom", "target_cwd": "/x",
        }):
            rc = ccp.main(["--cwd", "/x"])
        self.assertEqual(rc, 2)




# ---------------------------------------------------------------------------
# Третий риск: прогон, заказчик которого мёртв (цикл #417)
#
# Каждый тест ниже — воспроизведение настоящей аварии либо ЛОЖНОЙ ТРЕВОГИ,
# которая сделала бы проверку непригодной. Шесть случаев за сутки 27–28.08
# (#398, #401 ×2, #408, #415 ×2, #417); у последнего 64 минуты ядра.
# ---------------------------------------------------------------------------

class _FakeOwner:
    """Замена соседа `check_undelivered_work` — без `ps`, без журнала на диске.

    Отвечает ровно на те три вопроса, которые проверка ему задаёт, и ни на один
    больше: где корень дерева, какое дерево у записи, умер ли объявленный
    долгоживущий процесс."""

    DEFAULT_LOG = "/dev/null"

    def __init__(self, entries=(), gone=frozenset()):
        self._entries = list(entries)
        self._gone = set(gone)

    def tree_of_path(self, path):
        parts = Path(path).parts
        for i, part in enumerate(parts):
            if i > 0 and part in ("spa_core", "scripts", "tests", "docs", "data"):
                return str(Path(*parts[:i]))
        return None

    def worktree_of(self, entry):
        roots = {self.tree_of_path(f) for f in entry.get("files") or ()}
        roots.discard(None)
        return next(iter(roots)) if len(roots) == 1 else None

    def shared_log(self):
        # Настоящий сосед отдаёт журнал ГЛАВНОГО дерева; здесь важен только сам
        # факт, что путь разрешился — содержимое даёт read_entries.
        return "/fake/session_changes.jsonl", None

    def read_entries(self, log_path, last):
        # Настоящий возвращает (записи, число битых строк) — двойник обязан
        # повторять ФОРМУ, иначе он проверяет несуществующий контракт.
        return list(self._entries), 0

    def durable_process_gone(self, entry):
        return entry.get("session") in self._gone


def _entry(session, tree, *, session_pid=None):
    e = {"session": session, "files": [f"{tree}/spa_core/x.py"]}
    if session_pid is not None:
        e["session_pid"] = session_pid
    return e


def _proc(pid, *, ppid, cwd):
    return ccp.PytestProc(pid=pid, ppid=ppid, lstart="Thu Aug 28 10:00:00 2026",
                          command="python3 -m pytest spa_core/tests/ -q", cwd=cwd)


class TestOrphanClassification(unittest.TestCase):
    def test_orphan_named_when_requesting_session_is_measured_dead(self):
        """Авария 28.08: pid 27998, ppid=1, /tmp/spa_c416, 64 мин ядра, заказчик мёртв."""
        owner = _FakeOwner(entries=[_entry("cycle-14573", "/tmp/spa_c416", session_pid=14573)],
                           gone={"cycle-14573"})
        verdict, why = ccp.classify_orphan(_proc(27998, ppid=1, cwd="/tmp/spa_c416"), owner=owner)
        self.assertEqual(verdict, ccp.ORPHAN)
        self.assertIn("cycle-14573", why)

    def test_my_own_backgrounded_run_is_not_an_orphan(self):
        """ЛОЖНАЯ ТРЕВОГА, которая обесценила бы проверку целиком.

        Любой `nohup python3 -m pytest … &` получает ppid=1, как только его
        оболочка завершилась. Судить по одному ppid значило бы каждый цикл
        объявлять сиротой СОБСТВЕННЫЙ живой приёмочный прогон — и звать его
        снять."""
        owner = _FakeOwner(entries=[_entry("cycle-59813", "/tmp/spa_c417", session_pid=59813)],
                           gone=set())
        verdict, why = ccp.classify_orphan(_proc(64443, ppid=1, cwd="/tmp/spa_c417"), owner=owner)
        self.assertEqual(verdict, ccp.ATTENDED)
        self.assertIn("жив", why)

    def test_unannounced_tree_is_unmeasured_not_orphan(self):
        """Заказчик НЕ НАЗВАН — это не «заказчик мёртв». На догадке не убивают."""
        owner = _FakeOwner(entries=[_entry("cycle-1", "/tmp/spa_other", session_pid=1)])
        verdict, why = ccp.classify_orphan(_proc(500, ppid=1, cwd="/tmp/spa_unknown"), owner=owner)
        self.assertEqual(verdict, ccp.UNMEASURED)
        self.assertIn("НЕ НАЗВАН", why)

    def test_announcement_without_durable_process_is_unmeasured(self):
        """Запись без `session_pid` не доказывает НИ жизни, НИ смерти сессии."""
        owner = _FakeOwner(entries=[_entry("cycle-7", "/tmp/spa_c7")])
        verdict, _ = ccp.classify_orphan(_proc(700, ppid=1, cwd="/tmp/spa_c7"), owner=owner)
        self.assertEqual(verdict, ccp.UNMEASURED)

    def test_live_parent_is_attended_without_touching_the_log(self):
        """ppid != 1 ⇒ родитель держит процесс; журнал для этого не нужен."""
        owner = _FakeOwner(entries=[], gone=set())
        verdict, _ = ccp.classify_orphan(_proc(800, ppid=999, cwd="/tmp/spa_c8"), owner=owner)
        self.assertEqual(verdict, ccp.ATTENDED)

    def test_unresolved_cwd_is_unmeasured(self):
        """Без дерева заказчика не найти — молчать об этом нельзя."""
        verdict, _ = ccp.classify_orphan(_proc(900, ppid=1, cwd=None), owner=_FakeOwner())
        self.assertEqual(verdict, ccp.UNMEASURED)

    def test_missing_sibling_module_is_unmeasured_not_clear(self):
        """Сосед не загрузился ⇒ живость нечем мерить. Fail-CLOSED: не «сирот нет»."""
        verdict, why = ccp.classify_orphan(_proc(1000, ppid=1, cwd="/tmp/spa_c9"), owner=None)
        self.assertEqual(verdict, ccp.UNMEASURED)
        self.assertIn("нечем мерить", why)


class TestOrphanExitCodes(unittest.TestCase):
    def _run_main(self, procs, owner, target_cwd):
        def fake_check(cwd, self_pid=None):
            for p in procs:
                p.orphan, p.orphan_why = ccp.classify_orphan(p, owner=owner)
            same = [p for p in procs if p.cwd == target_cwd]
            return {"status": "collision" if same else "clear", "target_cwd": target_cwd,
                    "same_cwd": [vars(p) for p in same],
                    "other_cwd": [vars(p) for p in procs if p.cwd != target_cwd],
                    "unresolved": [],
                    "orphans": [vars(p) for p in procs if p.orphan == ccp.ORPHAN],
                    "orphan_unmeasured": [vars(p) for p in procs if p.orphan == ccp.UNMEASURED]}
        with mock.patch.object(ccp, "check", fake_check):
            return ccp.main(["--cwd", target_cwd])

    def test_confirmed_orphan_exits_3_not_0(self):
        """Код 0 значит «чисто», а занятое трупом ядро — не чисто.

        Находка, живущая только в печатном тексте, имеет необязательного
        читателя; именно так класс пережил шесть рецидивов за сутки."""
        owner = _FakeOwner(entries=[_entry("dead", "/tmp/spa_dead", session_pid=1)], gone={"dead"})
        rc = self._run_main([_proc(1, ppid=1, cwd="/tmp/spa_dead")], owner, "/tmp/spa_mine")
        self.assertEqual(rc, 3)

    def test_attended_background_run_keeps_exit_0(self):
        """Обратный контроль: починка не смеет краснеть на здоровом состоянии."""
        owner = _FakeOwner(entries=[_entry("alive", "/tmp/spa_bg", session_pid=2)], gone=set())
        rc = self._run_main([_proc(2, ppid=1, cwd="/tmp/spa_bg")], owner, "/tmp/spa_mine")
        self.assertEqual(rc, 0)

    def test_unmeasured_owner_keeps_exit_0(self):
        """«Не измерено» само по себе не повод объявлять сироту."""
        owner = _FakeOwner(entries=[])
        rc = self._run_main([_proc(3, ppid=1, cwd="/tmp/spa_x")], owner, "/tmp/spa_mine")
        self.assertEqual(rc, 0)

    def test_collision_outranks_orphan(self):
        """Код 1 — про доверие к ТВОЕМУ числу, код 3 — только про машину."""
        owner = _FakeOwner(entries=[_entry("dead", "/tmp/spa_mine", session_pid=1)], gone={"dead"})
        rc = self._run_main([_proc(4, ppid=1, cwd="/tmp/spa_mine")], owner, "/tmp/spa_mine")
        self.assertEqual(rc, 1)


class TestPsParsesPpid(unittest.TestCase):
    def test_ppid_is_read_from_ps(self):
        raw = _ps_line(111, "python3 -m pytest spa_core/tests/ -q", ppid=1)
        with mock.patch.object(ccp, "_run", return_value=raw):
            procs = ccp.list_pytest_processes()
        self.assertEqual([(p.pid, p.ppid) for p in procs], [(111, 1)])

    def test_line_without_ppid_column_is_dropped_not_guessed(self):
        """Старый формат `ps` не должен молча читаться как ppid=<кусок даты>."""
        with mock.patch.object(ccp, "_run", return_value="111 Thu Aug 28 10:00:00 2026 pytest"):
            procs = ccp.list_pytest_processes()
        self.assertEqual(procs, [])




class TestDurableAnnouncementIsNotShadowed(unittest.TestCase):
    """Найдено ЖИВЫМ прогоном (#417), а не рассуждением — и это разные вещи.

    Поверх собственного объявления с `session_pid` сессия пишет короткие
    служебные записи (захват карточки), у которых долгоживущего процесса нет ПО
    ПОСТРОЕНИЮ. Выбор «последней записи о дереве» терял единственное измеримое
    свидетельство и на ЖИВОМ прогоне отвечал «не измерено» — ответ честный и
    бесполезный: сирота и живой прогон становились неотличимы."""

    def _owner(self, gone):
        return _FakeOwner(entries=[
            _entry("cycle-59813", "/tmp/spa_c417", session_pid=59813),   # объявление
            _entry("pid59813", "/tmp/spa_c417"),                         # захват карточки
        ], gone=gone)

    def test_bare_later_entry_does_not_shadow_the_durable_one(self):
        verdict, why = ccp.classify_orphan(
            _proc(64443, ppid=1, cwd="/tmp/spa_c417"), owner=self._owner(set()))
        self.assertEqual(verdict, ccp.ATTENDED)
        self.assertIn("pid59813", why)

    def test_and_the_same_shadowing_must_not_hide_a_real_death(self):
        """Обратный контроль: правило выбора не смеет прятать настоящую смерть."""
        verdict, _ = ccp.classify_orphan(
            _proc(64443, ppid=1, cwd="/tmp/spa_c417"), owner=self._owner({"cycle-59813"}))
        self.assertEqual(verdict, ccp.ORPHAN)


if __name__ == "__main__":
    unittest.main()
