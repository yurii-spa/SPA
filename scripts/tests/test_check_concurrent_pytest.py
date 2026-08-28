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


def _ps_line(pid: int, command: str) -> str:
    # ps -o pid=,lstart=,command= — lstart is a fixed 5-token ctime string.
    return f"{pid} Thu Aug 28 10:00:00 2026 {command}"


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


if __name__ == "__main__":
    unittest.main()
