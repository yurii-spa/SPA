"""Перепись разрешимости невычисленных путей (заказ G46 п. 2, ADR-424).

Контроль у каждой проверки в ОБЕ стороны: расширение обязано брать ту форму,
ради которой написано, и обязано НЕ брать соседнюю. Литеральных дат нет;
живое `data/` не читается ни одной проверкой — все сцены строятся в
одноразовом каталоге.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import call_sourced_input_census as csi
from spa_core.monitoring import unresolved_path_census as upc

REPO = Path(__file__).resolve().parents[2]


def _site(source: str, *, filename: str = "spa_core/tests/test_scene.py",
          here: Path | None = None) -> upc.Site:
    """Первое невычисленное место обхода в разобранном тексте.

    Сцена собирается тем же кодом, что и население переписи, — иначе тест
    проверял бы СВОЮ сборку, а не прибор.
    """
    tree = ast.parse(source, filename=filename)
    parents = csi._parents(tree)
    module_scope = csi._assignments_toplevel(tree)
    imports, targets = upc.imported_names(tree), upc.loop_target_names(tree)
    for node, call in csi._enumeration_sites(tree):
        kind, base = csi.source_of(call)
        if kind is None:
            continue
        nearest, chain = csi._enclosing(node, parents, tree)
        scopes = [csi._assignments(s) for s in chain] + [module_scope]
        owner = next((c for c in chain if isinstance(c, ast.ClassDef)), None)
        extras = {
            upc.EXT_BASE_ATTR: upc.base_class_attrs(tree, owner),
            upc.EXT_PARAM_DEFAULT: upc.parameter_defaults(chain),
            upc.EXT_HELPER_RETURN: upc.helper_returns(tree, scopes),
            upc.EXT_CALLSITE_ARG: upc.call_site_arguments(tree, chain),
            "_params_no_default": upc._params_without_default(chain),
        }
        return upc.Site(
            guard=filename, line=node.lineno, kind=kind,
            anchor=ast.unparse(base), scope=getattr(nearest, "name", "<module>"),
            base=base, here=here or (REPO / filename), scopes=scopes,
            extras=extras, loops=upc.loop_literals(node, parents, scopes),
            imports=imports, loop_targets=targets)
    raise AssertionError("в сцене нет ни одного места обхода")


class BaseClassAttributes(unittest.TestCase):
    """`self.X` из БАЗОВОГО класса того же файла."""

    SOURCE = '''
import unittest
from pathlib import Path

class _Base(unittest.TestCase):
    def setUp(self):
        self.data_dir = Path("spa_core") / "risk"

class TestChild(_Base):
    def test_walks(self):
        for item in self.data_dir.rglob("*.py"):
            print(item)
'''

    def test_the_attribute_of_a_base_class_is_found(self):
        site = _site(self.SOURCE)
        self.assertIn("self.data_dir", site.extras[upc.EXT_BASE_ATTR])

    def test_the_census_computer_alone_does_NOT_find_it(self):
        """Обратная сторона: без расширения путь не вычисляется.

        Без этой проверки «расширение работает» означало бы лишь, что путь
        вычислился хоть как-нибудь, — в том числе и без всякого расширения.
        """
        site = _site(self.SOURCE)
        self.assertIsNone(upc._resolve_with(site, ()))
        self.assertIsNotNone(upc._resolve_with(site, (upc.EXT_BASE_ATTR,)))

    def test_a_cycle_in_the_bases_does_not_hang(self):
        source = '''
class A(B):
    def setUp(self):
        self.d = "x"

class B(A):
    def test_walks(self):
        for item in self.d.rglob("*"):
            print(item)
'''
        tree = ast.parse(source)
        owner = next(n for n in ast.walk(tree)
                     if isinstance(n, ast.ClassDef) and n.name == "B")
        self.assertIn("self.d", upc.base_class_attrs(tree, owner))

    def test_no_owner_class_means_no_attributes(self):
        self.assertEqual(upc.base_class_attrs(ast.parse("x = 1"), None), {})


class ParameterDefaults(unittest.TestCase):

    def test_positional_default_is_taken_and_a_bare_parameter_is_not(self):
        tree = ast.parse('def f(a, b="spa_core", *, c="scripts", d=None): pass')
        func = tree.body[0]
        found = upc.parameter_defaults([func])
        self.assertEqual(sorted(found), ["b", "c", "d"])
        self.assertNotIn("a", found,
                         "параметр без умолчания решает зовущий — подставлять нечего")

    def test_a_bare_parameter_is_listed_as_caller_supplied(self):
        tree = ast.parse('def f(a, b="x"): pass')
        found = upc._params_without_default([tree.body[0]])
        self.assertEqual(sorted(found), ["a"])


class HelperReturns(unittest.TestCase):

    def test_a_single_return_is_substituted(self):
        source = '''
from pathlib import Path

class T:
    def stand(self):
        return Path("spa_core") / "risk"

    def test_walks(self):
        data = self.stand()
        for item in data.rglob("*.py"):
            print(item)
'''
        site = _site(source)
        self.assertIsNone(upc._resolve_with(site, ()))
        self.assertIsNotNone(upc._resolve_with(site, (upc.EXT_HELPER_RETURN,)))

    def test_two_returns_are_refused_not_guessed(self):
        func = ast.parse('def f(x):\n    if x: return 1\n    return 2').body[0]
        self.assertIsNone(upc._sole_return(func),
                          "две ветки return — два пути; выбор из них был бы решением за код")


class LoopVariables(unittest.TestCase):
    """Переменная цикла по ЛИТЕРАЛЬНОМУ перечню — и подстановка, а не область."""

    SOURCE = '''
from pathlib import Path
ROOT = Path("/tmp/scene")
DIRS = ("spa_core", "scripts")

def test_walks():
    for d in DIRS:
        base = ROOT / d
        for py in base.rglob("*.py"):
            print(py)
'''

    def test_every_value_of_the_literal_list_becomes_a_path(self):
        site = _site(self.SOURCE)
        values = upc._resolve_with(site, (upc.EXT_LOOP_LITERAL,))
        self.assertIsNotNone(values)
        self.assertEqual(len(values), 2, "перечень из двух элементов даёт два пути")

    def test_without_the_extension_the_site_stays_unresolved(self):
        self.assertIsNone(upc._resolve_with(_site(self.SOURCE), ()))

    def test_a_non_literal_list_is_refused(self):
        source = '''
from pathlib import Path
ROOT = Path("/tmp/scene")

def test_walks(names):
    for d in names:
        base = ROOT / d
        for py in base.rglob("*.py"):
            print(py)
'''
        site = _site(source)
        self.assertEqual(site.loops, {},
                         "перечень не литеральный — подставлять нечего")

    def test_substitution_touches_only_loads(self):
        tree = ast.parse("d = 1\nx = ROOT / d")
        swapped = upc._Substitute("d", ast.Constant("scripts")).visit(tree)
        self.assertIsInstance(swapped.body[0].targets[0], ast.Name,
                              "цель присваивания подменяться не должна")
        self.assertIsInstance(swapped.body[1].value.right, ast.Constant)


class CallSiteArguments(unittest.TestCase):

    def test_one_agreed_argument_binds_and_two_different_do_not(self):
        agreed = '''
from pathlib import Path
ROOT = Path("/tmp/scene")

def walk(directory):
    for py in directory.rglob("*.py"):
        print(py)

def test_a():
    walk(ROOT / "spa_core")

def test_b():
    walk(ROOT / "spa_core")
'''
        split = agreed.replace('walk(ROOT / "spa_core")\n\ndef test_b():\n    walk(ROOT / "spa_core")',
                               'walk(ROOT / "spa_core")\n\ndef test_b():\n    walk(ROOT / "scripts")')
        self.assertIsNotNone(upc._resolve_with(_site(agreed), (upc.EXT_CALLSITE_ARG,)))
        self.assertIsNone(
            upc._resolve_with(_site(split), (upc.EXT_CALLSITE_ARG,)),
            "разные выражения у разных вызовов — путь не один, и угадывать его нельзя")


class ReferencedNames(unittest.TestCase):
    """Имя-ЗНАЧЕНИЕ против имени вызываемого."""

    def test_the_constructor_is_not_blamed_for_the_path(self):
        node = ast.parse("Path(data)", mode="eval").body
        names = [upc._key_of(n) for n in upc.referenced(node)]
        self.assertEqual(names, ["data"])

    def test_an_imported_namespace_is_not_blamed_either(self):
        node = ast.parse("pathlib.Path(d)", mode="eval").body
        self.assertEqual([upc._key_of(n) for n in upc.referenced(node, {"pathlib"})],
                         ["d"])

    def test_a_value_used_the_same_way_IS_blamed(self):
        node = ast.parse("base.rglob('*.py')", mode="eval").body
        self.assertEqual([upc._key_of(n) for n in upc.referenced(node, {"pathlib"})],
                         ["base"],
                         "`base` — значение, и форма записи тут та же самая")


class RemainderReasons(unittest.TestCase):
    """У каждой причины остатка — своя сцена, и она называется своим именем."""

    def _reason(self, source: str) -> str:
        return upc.why_unresolved(_site(source))[0]

    def test_caller_supplied(self):
        self.assertEqual(self._reason('''
def walk(directory):
    for py in directory.rglob("*.py"):
        print(py)
'''), upc.WHY_CALLER)

    def test_external_call(self):
        self.assertEqual(self._reason('''
import os
def test_walks():
    for py in os.scandir(os.path.dirname("x")):
        print(py)
'''), upc.WHY_EXTERNAL)

    def test_subscript(self):
        self.assertEqual(self._reason('''
WRAPPERS = {}
def test_walks(name):
    for py in WRAPPERS[name].rglob("*.py"):
        print(py)
'''), upc.WHY_SUBSCRIPT)

    def test_imported_name(self):
        self.assertEqual(self._reason('''
from somewhere import ANALYTICS_DIR
def test_walks():
    for py in ANALYTICS_DIR.rglob("*.py"):
        print(py)
'''), upc.WHY_IMPORTED)

    def test_loop_variable_not_over_a_literal(self):
        self.assertEqual(self._reason('''
def test_walks(names):
    for d in names:
        for py in d.rglob("*.py"):
            print(py)
'''), upc.WHY_LOOP_VAR)

    def test_self_binding_reads_as_caller_supplied_not_as_a_cycle(self):
        """`root = Path(root)` — форма записи, а не замкнутый круг."""
        self.assertEqual(self._reason('''
from pathlib import Path
def walk(root):
    root = Path(root)
    for py in root.rglob("*.py"):
        print(py)
'''), upc.WHY_CALLER)


class PlaceOfTheResolvedPath(unittest.TestCase):

    def test_inside_outside_and_fixture_are_three_different_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertEqual(upc._place([root / "spa_core"], root)[0], csi.PLACE_REPO)
            self.assertEqual(upc._place([Path("/etc")], root)[0], csi.PLACE_OUTSIDE)
            self.assertEqual(upc._place([csi._FIXTURE], root)[0], csi.PLACE_FIXTURE)


class MeasureOnARealContour(unittest.TestCase):
    """Положительный контроль на настоящем контуре: дерево со сторожами."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "repo"
        for rel in csi.GUARD_DIRS:
            (cls.root / rel).mkdir(parents=True, exist_ok=True)
        (cls.root / "spa_core" / "risk").mkdir(parents=True, exist_ok=True)
        (cls.root / "spa_core" / "risk" / "policy.py").write_text("x = 1\n",
                                                                  encoding="utf-8")
        # Каталог НАЗВАН, а не взят первым из реестра: глубина сторожа входит
        # в его собственный `parents[2]`, и «первый попавшийся» каталог сделал
        # бы сцену зависимой от порядка в чужой константе.
        guard = cls.root / "spa_core" / "tests" / "test_scene_guard.py"
        guard.parent.mkdir(parents=True, exist_ok=True)
        guard.write_text('''
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

class _Base(unittest.TestCase):
    def setUp(self):
        self.area = ROOT / "spa_core" / "risk"

class TestChild(_Base):
    def test_walks(self):
        for item in self.area.rglob("*.py"):
            self.assertTrue(item)

def test_caller_decides(directory):
    for item in directory.rglob("*.py"):
        print(item)
''', encoding="utf-8")
        cls.doc = upc.measure(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_base_class_site_is_resolved_and_lands_in_the_tree(self):
        resolved = [r for r in self.doc["rows"] if r["resolved_by"]]
        self.assertTrue(resolved, "ни одна строка не разрешена — контур вхолостую")
        self.assertEqual(resolved[0]["resolved_by"], upc.EXT_BASE_ATTR)
        self.assertEqual(resolved[0]["place"], csi.PLACE_REPO)
        self.assertEqual(self.doc["new_repo_population"], 1)

    def test_the_caller_supplied_site_stays_in_the_remainder_by_name(self):
        rest = [r for r in self.doc["rows"] if not r["resolved_by"]]
        self.assertEqual([r["reason"] for r in rest], [upc.WHY_CALLER])

    def test_extensions_that_changed_nothing_are_named_ornaments(self):
        """Расширение без предельного вклада обязано быть НАЗВАНО.

        Это и есть встроенная защита от украшения: на контуре, где работает
        одно расширение, остальные четыре обязаны предъявить ноль — и прибор
        обязан сказать это вслух, а не умолчать.
        """
        self.assertEqual(self.doc["marginal_contribution"][upc.EXT_BASE_ATTR], 1)
        self.assertIn(upc.EXT_PARAM_DEFAULT, self.doc["ornament_extensions"])

    def test_a_missing_tree_is_a_loud_refusal_not_an_empty_census(self):
        with self.assertRaises(upc.NotMeasured):
            upc.measure(self.root / "нет-такого-дерева")

    def test_run_writes_the_document_and_names_its_producer(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.json"
            outcome = upc.run(self.root, dest=dest)
            self.assertTrue(outcome["measured"])
            doc = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(doc["generated_by"], upc.PRODUCER)
            self.assertEqual(doc["status"], "MEASURED")

    def test_the_report_is_not_vacuous_on_a_real_document(self):
        lines = upc.report(self.doc)
        self.assertGreaterEqual(len(lines), 6)
        self.assertTrue(any("РАЗРЕШИМО УЖЕСТОЧЕНИЕМ" in line for line in lines))
        self.assertTrue(any(upc.WHY_CALLER in line for line in lines),
                        "остаток обязан быть назван ПРИЧИНОЙ, а не числом")


class TheInstrumentRunsFromTheCommandLine(unittest.TestCase):

    def test_exit_code_two_when_the_tree_is_absent(self):
        proc = subprocess.run(
            [sys.executable, "-m", "spa_core.monitoring.unresolved_path_census",
             "--root", "/нет/такого/дерева", "--no-write"],
            cwd=str(REPO), capture_output=True, text=True, timeout=180)
        self.assertEqual(proc.returncode, 2,
                         "«не измерено» обязано выходить своим кодом, а не нулём")
        self.assertIn("НЕ ИЗМЕРЕНО", proc.stdout)


if __name__ == "__main__":
    unittest.main()
