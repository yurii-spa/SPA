"""Память повторной работы у двух переписей: ответ тот же, работа — один раз.

Замер 2026-10-17 (CI #6, группа G01, ``ci_run6_failure_analysis.md``): тесты
переписей упирались в потолок 180 с на тест не потому, что повисли, а потому,
что прибор повторял уже сделанную работу:

* ``modular_constant_operand.census`` — четыре ступени над ОДНИМ файлом заново
  разбирали тот же исходник и заново гоняли ось по той же копии дерева
  (90 с → 45 с на живом дереве после памяти);
* ``run_identity_key_price.reader_population`` — заново разбирала все ~2480
  модулей на каждый зов (4,8 с → 0,25 с со второго зова).

Здесь — контроль в обе стороны (правило «у каждой проверки положительный
контроль»): память ДАЁТ тот же ответ, ПРОМАХИВАЕТСЯ при изменённом входе,
ОТДАЁТ независимые копии и НЕ ЖИВЁТ вне прогона. Плюс контроль того, что она
вообще срабатывает: иначе «стало быстрее» держалось бы на рассуждении.
"""
from __future__ import annotations

import ast
import tempfile
import textwrap
import unittest
from pathlib import Path

from spa_core.monitoring import identity_field_kind as field_kind
from spa_core.monitoring import modular_constant_operand as mco
from spa_core.monitoring import run_identity_key_price as g16


def _src(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


#: Прямая площадка: постоянная в самом выражении поля.
DIRECT = """
    _HOUR = 3600.0

    def rows(now, stamp):
        return {"age_hours": (now - stamp).total_seconds() / _HOUR}
"""

#: Транзитивная площадка — включает ступень `module_chain`.
TRANSITIVE = """
    HI = 300
    LO = 60
    SPAN = HI - LO

    def view():
        return {"span": SPAN}
"""

#: Затенённая постоянная — включает ступень `module_shadow_cost` со вторым
#: прогоном `module_sites(drop_shadowed=False)`.
SHADOWED = """
    LIMIT = 10

    def other(LIMIT):
        return LIMIT

    def view(x):
        return {"gap": LIMIT - x}
"""

BROKEN = "def (:\n"


def _scene(root: Path, files: dict) -> Path:
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_src(body), encoding="utf-8")
    return root


_FILES = {"spa_core/direct.py": DIRECT,
          "spa_core/transitive.py": TRANSITIVE,
          "scripts/shadowed.py": SHADOWED,
          "scripts/broken.py": BROKEN}


class OperandCensusMemoGivesTheSameAnswer(unittest.TestCase):
    """Ответ с памятью тождествен ответу без неё — на сцене со всеми ступенями."""

    def test_census_with_memo_equals_census_without_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), _FILES)
            with_memo = mco.census(root)
            without = mco.census.__wrapped__(root)   # тело без памяти прогона
        self.assertEqual(with_memo, without)
        # Сцена обязана задевать все ступени, иначе равенство ничего не мерит.
        self.assertGreaterEqual(with_memo["direct"], 1)
        self.assertGreaterEqual(with_memo["transitive"], 1)
        self.assertTrue(with_memo["chain"]["rows"])
        self.assertGreaterEqual(with_memo["shadow_cost"]["dropped_constants"], 1)
        self.assertIn("scripts/broken.py", with_memo["files_unmeasured"])

    def test_the_memo_actually_saves_work(self):
        """Положительный контроль: без этого «быстрее» держалось бы на слове."""
        calls = {"n": 0}
        real = field_kind.scope_table_steps

        def counting(*a, **k):
            calls["n"] += 1
            return real(*a, **k)

        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), _FILES)
            field_kind.scope_table_steps = counting
            try:
                mco.census.__wrapped__(root)
                without = calls["n"]
                calls["n"] = 0
                mco.census(root)
                with_memo = calls["n"]
            finally:
                field_kind.scope_table_steps = real
        self.assertGreater(without, 0)
        self.assertLess(with_memo, without)


class OperandCensusMemoLivesOneRunOneFile(unittest.TestCase):

    def test_no_memo_outside_a_run(self):
        self.assertEqual(mco._RUN_MEMO, [])
        self.assertIsNone(mco._file_memo(_src(DIRECT)))
        tree = ast.parse(_src(DIRECT))
        first = mco.module_constants(tree)
        first["INJECTED"] = "1"
        self.assertNotIn("INJECTED", mco.module_constants(tree))

    def test_memo_is_removed_even_when_the_run_raises(self):
        real = mco.module_sites

        def boom(source, **kw):
            raise RuntimeError("сцена: ступень упала посреди прогона")

        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(Path(tmp), {"spa_core/direct.py": DIRECT})
            mco.module_sites = boom
            try:
                with self.assertRaises(RuntimeError):
                    mco.census(root)
            finally:
                mco.module_sites = real
        self.assertEqual(mco._RUN_MEMO, [])

    def test_inside_a_run_copies_are_independent(self):
        @mco._with_run_memo
        def run():
            tree = mco._parse(_src(DIRECT))
            first = mco.module_constants(tree)
            first.pop("_HOUR")
            second = mco.module_constants(tree)
            shadow = mco.shadowed_anywhere(tree)
            shadow.add("INJECTED")
            answers, _conv = mco._axis_answers_converged(tree)
            answers.append(("INJECTED", 0, ""))
            again, _conv2 = mco._axis_answers_converged(tree)
            return second, mco.shadowed_anywhere(tree), again

        consts, shadow, answers = run()
        self.assertEqual(consts, {"_HOUR": "3600.0"})
        self.assertNotIn("INJECTED", shadow)
        self.assertNotIn(("INJECTED", 0, ""), answers)

    def test_a_changed_source_is_a_miss(self):
        """Тот же «файл», другой текст ⇒ новый разбор и новый ответ."""
        @mco._with_run_memo
        def run():
            before = mco.module_sites(_src(DIRECT))
            changed = _src(DIRECT).replace("3600.0", "60.0")
            after = mco.module_sites(changed)
            back = mco.module_sites(_src(DIRECT))
            return before, after, back

        before, after, back = run()
        self.assertEqual(before[1], {"_HOUR": "3600.0"})
        self.assertEqual(after[1], {"_HOUR": "60.0"})
        self.assertIn("60.0", after[0][0].how)
        self.assertEqual(back, before)

    def test_a_parse_failure_is_remembered_as_a_failure(self):
        @mco._with_run_memo
        def run():
            return (mco.module_sites(BROKEN), mco.module_shadow_cost(BROKEN),
                    mco.axis_limit_cost(BROKEN))

        sites, cost, limit = run()
        self.assertIsNone(sites[0])
        self.assertIn("не разобрано", sites[2])
        self.assertIn("не разобрано", cost.reason)
        self.assertIn("не разобрано", limit.reason)

    def test_a_fresh_copy_equals_a_deep_copy(self):
        """Повторный разбор вместо глубокой копии — то же дерево, байт в байт."""
        source = _src(TRANSITIVE + SHADOWED)

        @mco._with_run_memo
        def run():
            tree = mco._parse(source)
            return tree, mco._fresh_copy(tree)

        tree, fresh = run()
        self.assertIsNot(fresh, tree)
        self.assertEqual(ast.dump(fresh, include_attributes=True),
                         ast.dump(ast.parse(source), include_attributes=True))


class ImportGraphMemoIsKeyedByText(unittest.TestCase):
    """Память импортов `reader_population`: ключ — текст модуля."""

    def _tree(self, root: Path, body: str) -> Path:
        files = {
            "spa_core/__init__.py": "",
            "spa_core/loader.py": "X = 1\n",
            "spa_core/reader.py": body,
        }
        return _scene(root, files)

    def test_same_answer_with_and_without_memo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(Path(tmp), "import spa_core.loader\n")
            g16._IMPORT_DEPS_MEMO.clear()
            cold = g16.reader_population(root, loaders=("spa_core.loader",))
            warm = g16.reader_population(root, loaders=("spa_core.loader",))
        self.assertEqual(cold, warm)
        self.assertIn("spa_core.reader", cold[0])

    def test_a_changed_file_is_a_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(Path(tmp), "import json\n")
            first = g16.reader_population(root, loaders=("spa_core.loader",))
            (root / "spa_core/reader.py").write_text("import spa_core.loader\n",
                                                     encoding="utf-8")
            second = g16.reader_population(root, loaders=("spa_core.loader",))
        self.assertNotIn("spa_core.reader", first[0])
        self.assertIn("spa_core.reader", second[0])

    def test_the_second_call_does_not_parse_again(self):
        calls = {"n": 0}
        real = ast.parse

        def counting(*a, **k):
            calls["n"] += 1
            return real(*a, **k)

        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(Path(tmp), "import spa_core.loader\n")
            g16._IMPORT_DEPS_MEMO.clear()
            ast.parse = counting
            try:
                g16.reader_population(root, loaders=("spa_core.loader",))
                cold = calls["n"]
                calls["n"] = 0
                g16.reader_population(root, loaders=("spa_core.loader",))
                warm = calls["n"]
            finally:
                ast.parse = real
        self.assertGreater(cold, 0)
        self.assertEqual(warm, 0)

    def test_returned_population_is_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(Path(tmp), "import spa_core.loader\n")
            first, _ = g16.reader_population(root, loaders=("spa_core.loader",))
            first["spa_core.reader"].add("INJECTED")
            first["spa_core.ghost"] = {"INJECTED"}
            second, _ = g16.reader_population(root, loaders=("spa_core.loader",))
        self.assertNotIn("INJECTED", second["spa_core.reader"])
        self.assertNotIn("spa_core.ghost", second)

    def test_a_syntax_error_is_still_an_empty_edge_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree(Path(tmp), "def (:\n")
            edges = g16._import_edges(g16._first_party_modules(root))
            again = g16._import_edges(g16._first_party_modules(root))
        self.assertEqual(edges["spa_core.reader"], set())
        self.assertEqual(again, edges)


if __name__ == "__main__":
    unittest.main()
