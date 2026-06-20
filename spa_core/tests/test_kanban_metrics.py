"""Tests for spa_core.reporting.kanban_metrics (MP-1580 / Improvement 5).

15 unit tests across:
  - TestCategoryOf        (3)
  - TestCollectTickets    (5)
  - TestComputeMetrics    (4)
  - TestRunAndRender      (3)

Run:
  python3 -m unittest spa_core.tests.test_kanban_metrics -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from spa_core.reporting.kanban_metrics import (
    category_of,
    collect_tickets,
    compute_from_file,
    compute_metrics,
    main,
    render_markdown,
    run,
)


class TestCategoryOf(unittest.TestCase):
    def test_mp(self):
        self.assertEqual(category_of("MP-1503"), "MP")

    def test_lowercase_uppercased(self):
        self.assertEqual(category_of("web-12"), "WEB")

    def test_no_prefix_is_other(self):
        self.assertEqual(category_of("12345"), "OTHER")
        self.assertEqual(category_of(""), "OTHER")


class TestCollectTickets(unittest.TestCase):
    def test_done_column_marks_done(self):
        board = {"columns": {"done": [{"id": "MP-1"}], "backlog": [{"id": "MP-2"}]}}
        t = collect_tickets(board)
        self.assertTrue(t["MP-1"])
        self.assertFalse(t["MP-2"])

    def test_status_done_marks_done(self):
        board = {"columns": {"backlog": [{"id": "MP-3", "status": "done"}]}}
        self.assertTrue(collect_tickets(board)["MP-3"])

    def test_dedup_done_wins(self):
        board = {"columns": {
            "done": [{"id": "MP-9"}],
            "backlog": [{"id": "MP-9"}]}}
        t = collect_tickets(board)
        self.assertEqual(len(t), 1)
        self.assertTrue(t["MP-9"])

    def test_tasks_list_included(self):
        board = {"columns": {}, "tasks": [{"id": "WEB-1", "status": "done"},
                                          {"id": "WEB-2", "status": "backlog"}]}
        t = collect_tickets(board)
        self.assertTrue(t["WEB-1"])
        self.assertFalse(t["WEB-2"])

    def test_ignores_non_dict_and_empty_ids(self):
        board = {"columns": {"done": ["junk", {"id": ""}, {"id": "MP-7"}]}}
        t = collect_tickets(board)
        self.assertEqual(set(t), {"MP-7"})


class TestComputeMetrics(unittest.TestCase):
    def test_overall_counts(self):
        m = compute_metrics({"MP-1": True, "MP-2": False, "WEB-1": True})
        self.assertEqual(m["total"], 3)
        self.assertEqual(m["done"], 2)
        self.assertEqual(m["open"], 1)
        self.assertAlmostEqual(m["completion_pct"], 66.67, places=1)

    def test_by_category(self):
        m = compute_metrics({"MP-1": True, "MP-2": False, "WEB-1": True})
        self.assertEqual(m["by_category"]["MP"]["done"], 1)
        self.assertEqual(m["by_category"]["MP"]["total"], 2)
        self.assertEqual(m["by_category"]["WEB"]["completion_pct"], 100.0)

    def test_empty_board(self):
        m = compute_metrics({})
        self.assertEqual(m["total"], 0)
        self.assertEqual(m["completion_pct"], 0.0)
        self.assertEqual(m["by_category"], {})

    def test_categories_sorted(self):
        m = compute_metrics({"ZED-1": True, "ABC-1": False})
        self.assertEqual(list(m["by_category"].keys()), ["ABC", "ZED"])


class TestRunAndRender(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = Path(self.tmp)
        self.board = self.dir / "KANBAN.json"
        self.board.write_text(json.dumps({
            "done_count": 2,
            "columns": {
                "done": [{"id": "MP-1"}, {"id": "WEB-1"}],
                "backlog": [{"id": "MP-2"}],
            },
        }), encoding="utf-8")

    def test_run_writes_output(self):
        out = self.dir / "kanban_metrics.json"
        m = run(kanban_path=self.board, out_path=out, write=True)
        self.assertTrue(out.exists())
        saved = json.loads(out.read_text())
        self.assertEqual(saved["done"], m["done"])
        self.assertEqual(m["board_done_count"], 2)

    def test_compute_from_missing_file_safe(self):
        m = compute_from_file(self.dir / "nope.json")
        self.assertEqual(m["total"], 0)

    def test_render_markdown_has_table(self):
        m = run(kanban_path=self.board, write=False)
        md = render_markdown(m)
        self.assertIn("| Category | Done | Total | % |", md)
        self.assertIn("MP", md)


class TestCLI(unittest.TestCase):
    def test_main_check_exit_zero(self):
        tmp = tempfile.mkdtemp()
        board = Path(tmp) / "KANBAN.json"
        board.write_text(json.dumps({"columns": {"done": [{"id": "MP-1"}]}}), encoding="utf-8")
        self.assertEqual(main(["--check", "--kanban", str(board)]), 0)


if __name__ == "__main__":
    unittest.main()
