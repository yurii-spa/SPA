"""Память чистых выводов из текста исходника (`spa_core.utils.source_memo`).

Память введена ради цены переписи G16 (замер 2026-10-22: 1320 с → ~575 с на
одном дереве при тождественном отчёте). Её единственное право на существование —
ответ из памяти ТОЖДЕСТВЕН вычислению. Каждый тест ниже — положительный контроль
одной формы, в которой память могла бы соврать, и краснеет, если ключ потеряет
соответствующий вход:

* тот же текст под ДРУГИМ путём (путь попадает в ответ);
* тот же текст при ДРУГОМ наборе искомых видов;
* изменённый текст (промах обязан случиться сам, без отметок времени);
* правка вызывающим отданного ему ответа (не должна протечь в следующий);
* синтаксическая ошибка (не запоминается, поднимается каждый раз).
"""
from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import cio_target_producers as producers
from spa_core.monitoring import judge_alone_price as jap
from spa_core.monitoring import ledger_parse_census as lpc
from spa_core.monitoring import pre_trade_recheck_census as ptr
from spa_core.utils.source_memo import SourceMemo

_BOOK_WRITER = (
    "import json\n"
    "def go(p):\n"
    "    book = {'positions': optimize(), 'note': 'x'}\n"
    "    json.dump(book, open('current_positions.json', 'w'))\n"
)


class SourceMemoCoreTests(unittest.TestCase):

    def test_a_changed_text_is_a_miss_and_an_equal_text_a_hit(self):
        memo = SourceMemo("t", immutable=True)
        calls = []
        f = lambda t: memo.get(t, None, lambda: calls.append(t) or len(t))  # noqa: E731
        self.assertEqual(f("ab"), 2)
        self.assertEqual(f("ab"), 2)
        self.assertEqual(f("abc"), 3)
        self.assertEqual(calls, ["ab", "abc"])
        self.assertEqual((memo.hits, memo.misses), (1, 2))

    def test_extra_inputs_are_part_of_the_key(self):
        memo = SourceMemo("t", immutable=True)
        self.assertEqual(memo.get("x", "A", lambda: "A"), "A")
        self.assertEqual(memo.get("x", "B", lambda: "B"), "B")

    def test_a_mutable_answer_is_handed_out_as_a_copy(self):
        memo = SourceMemo("t")
        first = memo.get("x", None, lambda: [{"k": 1}])
        first[0]["k"] = 99
        first.append("junk")
        self.assertEqual(memo.get("x", None, lambda: None), [{"k": 1}])

    def test_a_failure_is_not_remembered(self):
        memo = SourceMemo("t")
        boom = []

        def compute():
            boom.append(1)
            raise SyntaxError("bad")
        for _ in range(2):
            with self.assertRaises(SyntaxError):
                memo.get("x", None, compute)
        self.assertEqual(len(boom), 2)
        self.assertEqual(len(memo), 0)


class ProducerMemoTests(unittest.TestCase):

    def test_same_text_under_two_paths_answers_with_each_path(self):
        a = producers.book_writes_of("spa_core/a.py", _BOOK_WRITER)
        b = producers.book_writes_of("spa_core/b.py", _BOOK_WRITER)
        self.assertEqual([w["module"] for w in a], ["spa_core/a.py"])
        self.assertEqual([w["module"] for w in b], ["spa_core/b.py"])

    def test_memo_answer_equals_direct_analysis_even_after_caller_edits(self):
        tree = ast.parse(_BOOK_WRITER)
        direct = producers._book_shaped_writes(
            "spa_core/c.py", tree, producers._string_constants(tree))
        got = producers.book_writes_of("spa_core/c.py", _BOOK_WRITER)
        self.assertEqual(got, direct)
        got[0]["provenance"] = "OFFLINE"          # так делает _enumerate_producers
        self.assertEqual(producers.book_writes_of("spa_core/c.py", _BOOK_WRITER), direct)
        lits, called = producers.source_facts(_BOOK_WRITER)
        self.assertEqual(set(lits), producers._string_constants(tree))
        self.assertIn("optimize", called)

    def test_syntax_error_still_reaches_the_caller(self):
        with self.assertRaises(SyntaxError):
            producers.source_facts("def (:\n")


class LedgerMemoTests(unittest.TestCase):

    def test_calls_depend_on_path_and_on_the_wanted_views(self):
        src = ("from spa_core.research_factory import read\n"
               "read.latest()\n")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "spa_core").mkdir()
            (root / "spa_core" / "one.py").write_text(src, encoding="utf-8")
            (root / "spa_core" / "two.py").write_text(src, encoding="utf-8")

            class M:
                def __init__(self, id_, view):
                    self.id, self.view = id_, view
            latest = M("L", "spa_core.research_factory.read:latest")
            other = M("O", "spa_core.research_factory.read:other")
            first = lpc.view_call_sites([latest], root)
            self.assertEqual(first["L"].calls, {"spa_core/one.py": 1, "spa_core/two.py": 1})
            # Тот же текст, ДРУГОЙ вид: память обязана промахнуться.
            second = lpc.view_call_sites([other], root)
            self.assertEqual(second["O"].calls, {})
            self.assertEqual(lpc.view_call_sites([latest], root)["L"].calls,
                             first["L"].calls)


class GateAndJudgeMemoTests(unittest.TestCase):

    def test_gate_axis_answers_from_text_not_from_memory_of_another_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "m.py"
            p.write_text(f"import {ptr.GATE_MODULE_DOTTED}\n", encoding="utf-8")
            self.assertIs(ptr._imports_gate(p), True)
            p.write_text("import os\n", encoding="utf-8")
            self.assertIs(ptr._imports_gate(p), False)
            p.write_text("def (:\n", encoding="utf-8")
            self.assertIsNone(ptr._imports_gate(p))

    def test_judge_facts_follow_the_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "spa_core").mkdir()
            f = root / "spa_core" / "r.py"
            f.write_text("from spa_core.paper_trading import shadow_trigger_eval as ste\n"
                         "ste.load_history()\n", encoding="utf-8")
            self.assertEqual(jap.attribute_readers(root)["via_judge_module"],
                             ["spa_core/r.py"])
            f.write_text("x.load_history()\n", encoding="utf-8")
            out = jap.attribute_readers(root)
            self.assertEqual(out["via_judge_module"], [])
            self.assertEqual(out["unresolved"], ["spa_core/r.py"])


if __name__ == "__main__":
    unittest.main()
