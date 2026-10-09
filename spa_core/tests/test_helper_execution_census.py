"""Приёмка переписи «зовёт ли тест помощника» (ADR-674, заказ G107 п. 2).

У КАЖДОГО звена здесь есть обратная сторона с НАЗВАННЫМ звеном: звено порвано ⇒
находки нет (или исход меняется на названный). Проверка, никогда не видевшая
настоящей поломки, — украшение (`.claude/rules/deployment.md`).

Литеральных дат, литеральных pid и ``git init`` в батарее нет ПО ПОСТРОЕНИЮ:
единственный вход меры — ПУТЬ дерева, поэтому сцена целиком выкладывается
фикстурой, а часов, номеров процессов и git-окружения мера не спрашивает вовсе.
Это закреплено отдельной проверкой (:func:`test_measure_has_no_door_to_the_machine`).
"""
from __future__ import annotations

import ast
import pathlib
import unittest

from spa_core.monitoring import helper_execution_census as hx
from spa_core.monitoring import membership_reach_census as reach
from spa_core.monitoring import no_regression_census as census


def parse(src: str) -> ast.Module:
    return ast.parse(src)


def scene(tmp: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    """Выложить дерево из описания. Единственный вход меры — путь."""
    for rel, body in files.items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return tmp


def classify_scene(tmp: pathlib.Path, files: dict[str, str], test_rel: str,
                   hop: str, collector: dict | None = None) -> tuple[str, dict]:
    """Исход ОДНОЙ пары на выложенной сцене."""
    root = scene(tmp, files)
    tree = parse((root / test_rel).read_text(encoding="utf-8"))
    rule = collector if collector is not None else hx.collector_rule(str(root))
    return hx.classify(tree, test_rel, hop, root, {}, rule)


# ─────────────────────────── точечный путь выражения ─────────────────────────

class DottedPath(unittest.TestCase):
    def test_a_bare_name_is_its_own_dotted_path(self):
        node = parse("f()").body[0].value.func  # type: ignore[attr-defined]
        self.assertEqual(hx._dotted_of(node), "f")

    def test_an_attribute_chain_is_read_whole(self):
        node = parse("a.b.f()").body[0].value.func  # type: ignore[attr-defined]
        self.assertEqual(hx._dotted_of(node), "a.b.f")

    def test_a_chain_broken_by_a_non_name_has_NO_dotted_path(self):
        """Обратная сторона: выдумать имя для ``obj[0].f`` значило бы завести
        второй способ принадлежности. Звено порвано ⇒ пути нет."""
        node = parse("obj[0].f()").body[0].value.func  # type: ignore[attr-defined]
        self.assertIsNone(hx._dotted_of(node))


# ──────────────────────────── притязания импорта ─────────────────────────────

class Claims(unittest.TestCase):
    def test_plain_import_claims_the_FULL_dotted_name_not_the_root(self):
        """Положительный контроль на ЗАНИЖЕНИЕ завышения: будь притязанием корень
        ``a``, зов ``a.c.g()`` сошёл бы за обращение к ``a/b.py``."""
        node = parse("import a.b").body[0]
        claims, star = hx._claims(node)  # type: ignore[arg-type]
        self.assertEqual(set(claims), {"a.b"})
        self.assertNotIn("a", claims)
        self.assertFalse(star)

    def test_an_alias_claims_the_alias(self):
        node = parse("import a.b as x").body[0]
        claims, _ = hx._claims(node)  # type: ignore[arg-type]
        self.assertEqual(set(claims), {"x"})

    def test_from_import_claims_the_imported_name(self):
        node = parse("from a.b import c").body[0]
        claims, star = hx._claims(node)  # type: ignore[arg-type]
        self.assertEqual(set(claims), {"c"})
        self.assertFalse(star)

    def test_star_import_declares_NO_name_and_says_so(self):
        node = parse("from a.b import *").body[0]
        claims, star = hx._claims(node)  # type: ignore[arg-type]
        self.assertEqual(set(claims), set())
        self.assertTrue(star)


class Covers(unittest.TestCase):
    def test_a_claim_covers_its_own_attribute(self):
        self.assertTrue(hx._covers("risk", "risk.policy"))
        self.assertTrue(hx._covers("risk", "risk"))

    def test_a_claim_does_NOT_cover_a_longer_NAME(self):
        """Та же граница, что у ``_matches`` соседа: ``risk`` не ловит
        ``riskwire``. Сравнение подстрокой и есть подмена именем."""
        self.assertFalse(hx._covers("risk", "riskwire"))
        self.assertFalse(hx._covers("risk", "riskwire.desk"))


# ──────────────────────────── зовы и упоминания ──────────────────────────────

class CallsAndReferences(unittest.TestCase):
    def test_the_import_statement_itself_is_NOT_a_reference(self):
        """Обратная сторона: считай оператор импорта упоминанием — и ни одна
        пара никогда не стала бы `only_imported`, то есть ответ заказа всегда
        был бы нулём."""
        calls, refs, _ = hx._call_and_reference_paths(parse("import helper"))
        self.assertEqual(calls, frozenset())
        self.assertEqual(refs, frozenset())

    def test_a_call_inside_a_function_is_found(self):
        calls, _, _ = hx._call_and_reference_paths(
            parse("def t():\n    helper.f()\n"))
        self.assertIn("helper.f", calls)

    def test_a_reference_without_a_call_is_a_reference_only(self):
        calls, refs, _ = hx._call_and_reference_paths(parse("x = helper\n"))
        self.assertEqual(calls, frozenset())
        self.assertIn("helper", refs)

    def test_a_broken_chain_call_is_counted_and_not_guessed(self):
        calls, _, broken = hx._call_and_reference_paths(parse("d['k'].f()\n"))
        self.assertEqual(broken, 1)
        self.assertEqual(calls, frozenset())


class ModuleScope(unittest.TestCase):
    def test_a_module_level_import_is_in_module_scope(self):
        tree = parse("from helper import test_x\n")
        self.assertEqual(len(hx._module_scope_imports(tree)), 1)

    def test_an_import_under_a_module_level_try_still_names_the_module(self):
        tree = parse("try:\n    from helper import test_x\nexcept ImportError:\n    pass\n")
        self.assertEqual(len(hx._module_scope_imports(tree)), 1)

    def test_an_import_inside_a_function_is_NOT_in_module_scope(self):
        """Обратная сторона: собиратель видит только пространство МОДУЛЯ."""
        tree = parse("def t():\n    from helper import test_x\n")
        self.assertEqual(hx._module_scope_imports(tree), frozenset())


# ───────────────────────────── значение присваивания ─────────────────────────

class ValueCalls(unittest.TestCase):
    def test_a_direct_call_is_the_value(self):
        value = parse("m = f()").body[0].value  # type: ignore[attr-defined]
        self.assertEqual(len(hx._value_calls(value)), 1)

    def test_a_conditional_expression_passes_the_value_through(self):
        """Положительный контроль, найденный разбором собственного вывода:
        `test_autonomy_mandate.py` пишет ``mod = import_module(…) if … else None``."""
        value = parse("m = f() if c else None").body[0].value  # type: ignore[attr-defined]
        self.assertEqual(len(hx._value_calls(value)), 1)

    def test_a_transforming_wrapper_does_NOT_pass_the_value_through(self):
        """Обратная сторона: через ``str(…)`` значением становится уже не
        модуль, и назвать имя именем модуля значило бы гадать."""
        value = parse("m = str(f())").body[0].value  # type: ignore[attr-defined]
        calls = hx._value_calls(value)
        self.assertEqual([hx._dotted_of(c.func) for c in calls], ["str"])


# ──────────────────────────── исход одной пары ───────────────────────────────

HELPER = {"helper.py": "import spa_core.risk.policy\n\n\ndef f():\n    return 1\n"}


class ClassifyOnePair(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_called_first_hop_is_CALLED(self):
        outcome, ev = classify_scene(
            self.tmp, {**HELPER,
                       "test_x.py": "import helper\n\n\ndef test_a():\n    helper.f()\n"},
            "test_x.py", "helper.py")
        self.assertEqual(outcome, hx.CALLED)
        self.assertEqual(ev["called_as"], ["helper"])

    def test_an_unmentioned_first_hop_is_ONLY_IMPORTED(self):
        """ОТВЕТ ЗАКАЗА в чистом виде: имя ввезено и не упомянуто ни разу."""
        outcome, ev = classify_scene(
            self.tmp, {**HELPER,
                       "test_x.py": "import helper\n\n\ndef test_a():\n    assert 1\n"},
            "test_x.py", "helper.py")
        self.assertEqual(outcome, hx.ONLY_IMPORTED)
        self.assertEqual(ev["claims"], ["helper"])

    def test_a_referenced_but_uncalled_first_hop_is_UNDECIDED(self):
        """Третий исход, а не ноль: подменённый ``monkeypatch.setattr`` модуль
        зовётся КОСВЕННО, и объявить такую пару «не зовёт» значило бы выдать
        неизвестное за находку."""
        outcome, ev = classify_scene(
            self.tmp,
            {**HELPER,
             "test_x.py": "import helper\n\n\ndef test_a(monkeypatch):\n"
                          "    monkeypatch.setattr(helper, 'f', lambda: 2)\n"},
            "test_x.py", "helper.py")
        self.assertEqual(outcome, hx.USED)
        self.assertEqual(ev["used_as"], ["helper"])
        self.assertIn(outcome, hx.UNDECIDED)

    def test_the_ROOT_of_a_dotted_claim_blocks_the_negative_verdict(self):
        """Положительный контроль на дыру, найденную в первой редакции: при
        ``import pkg.helper`` имя ``pkg``, переданное в ``getattr``, делает
        решение НЕИЗВЕСТНЫМ. Звено порвано (корень не учитывается) ⇒ пара
        ложно уехала бы в `only_imported`."""
        files = {
            "pkg/__init__.py": "",
            "pkg/helper.py": "import spa_core.risk.policy\n",
            "test_x.py": "import pkg.helper\n\n\ndef test_a():\n"
                         "    getattr(pkg, 'helper')\n",
        }
        outcome, _ = classify_scene(self.tmp, files, "test_x.py", "pkg/helper.py")
        self.assertEqual(outcome, hx.USED)

    def test_CALLED_requires_the_FULL_dotted_claim(self):
        """Обратная сторона предыдущего: зов СОСЕДНЕГО подмодуля того же пакета
        обращением к первому шагу НЕ является."""
        files = {
            "pkg/__init__.py": "",
            "pkg/helper.py": "import spa_core.risk.policy\n",
            "pkg/other.py": "def g():\n    return 1\n",
            "test_x.py": "import pkg.helper\nimport pkg.other\n\n\n"
                         "def test_a():\n    pkg.other.g()\n",
        }
        outcome, _ = classify_scene(self.tmp, files, "test_x.py", "pkg/helper.py")
        self.assertNotEqual(outcome, hx.CALLED)
        self.assertEqual(outcome, hx.USED)

    def test_a_star_import_hides_the_name_and_is_NOT_called_overstatement(self):
        outcome, ev = classify_scene(
            self.tmp, {**HELPER,
                       "test_x.py": "from helper import *\n\n\ndef test_a():\n    assert 1\n"},
            "test_x.py", "helper.py")
        self.assertEqual(outcome, hx.HIDDEN)
        self.assertEqual(ev["hidden_by"], ["star_import"])

    def test_an_opaque_import_bound_to_a_name_and_called_is_CALLED(self):
        """Форма, которую сосед читает наравне с оператором импорта (ADR-468/469):
        притязанием служит ЦЕЛЬ ПРИСВОЕНИЯ."""
        outcome, ev = classify_scene(
            self.tmp,
            {**HELPER,
             "test_x.py": "import importlib\n\nh = importlib.import_module('helper')\n\n\n"
                          "def test_a():\n    h.f()\n"},
            "test_x.py", "helper.py")
        self.assertEqual(outcome, hx.CALLED)
        self.assertEqual(ev["called_as"], ["h"])

    def test_an_opaque_import_never_used_is_ONLY_IMPORTED(self):
        outcome, _ = classify_scene(
            self.tmp,
            {**HELPER,
             "test_x.py": "import importlib\n\nh = importlib.import_module('helper')\n\n\n"
                          "def test_a():\n    assert 1\n"},
            "test_x.py", "helper.py")
        self.assertEqual(outcome, hx.ONLY_IMPORTED)

    def test_an_opaque_import_through_a_conditional_still_binds_the_name(self):
        outcome, _ = classify_scene(
            self.tmp,
            {**HELPER,
             "test_x.py": "import importlib\nimport sys\n\n"
                          "h = importlib.import_module('helper') if sys else None\n\n\n"
                          "def test_a():\n    h.f()\n"},
            "test_x.py", "helper.py")
        self.assertEqual(outcome, hx.CALLED)

    def test_a_SPEC_returning_form_declares_no_module_name(self):
        """Обратная сторона: ``spec_from_file_location`` возвращает СПЕЦ, и
        считать присвоенное имя именем МОДУЛЯ значило бы выдать спец за модуль."""
        outcome, ev = classify_scene(
            self.tmp,
            {**HELPER,
             "test_x.py": "import importlib.util\n\n"
                          "s = importlib.util.spec_from_file_location('helper', 'helper.py')\n\n\n"
                          "def test_a():\n    assert s\n"},
            "test_x.py", "helper.py")
        self.assertEqual(outcome, hx.HIDDEN)
        self.assertEqual(ev["hidden_by"], ["opaque_import_without_a_name"])

    def test_an_unresolvable_first_hop_is_NO_BINDING_not_silence(self):
        """Собственный КОНТРОЛЬ: сосед провёл дугу, а имени для неё нет. Это
        названное расхождение, а не «не зовёт»."""
        outcome, _ = classify_scene(
            self.tmp, {**HELPER,
                       "other.py": "",
                       "test_x.py": "import helper\n\n\ndef test_a():\n    helper.f()\n"},
            "test_x.py", "other.py")
        self.assertEqual(outcome, hx.NO_BINDING)


# ───────────────────────────── правило собирателя ────────────────────────────

class CollectorRule(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_declared_pattern_is_read_from_the_file_not_assumed(self):
        (self.tmp / "pytest.ini").write_text(
            "[pytest]\npython_functions = check_*\n", encoding="utf-8")
        rule = hx.collector_rule(str(self.tmp))
        self.assertEqual(rule["state"], "declared")
        self.assertEqual(rule["patterns"], ["check_*"])
        self.assertIn("pytest.ini", rule["source"])

    def test_no_declaration_falls_back_to_the_pytest_default_and_SAYS_so(self):
        (self.tmp / "pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
        rule = hx.collector_rule(str(self.tmp))
        self.assertEqual(rule["state"], "default")
        self.assertEqual(rule["patterns"], list(hx._PYTEST_DEFAULT_FUNCTIONS))
        self.assertIn("умолчание", rule["source"])

    def test_a_missing_file_is_the_default_with_its_own_named_reason(self):
        rule = hx.collector_rule(str(self.tmp))
        self.assertEqual(rule["state"], "default")
        self.assertIn("нет", rule["source"])

    def test_an_unparsable_file_is_UNMEASURED_not_the_default(self):
        """Третий исход: отсутствие инструмента — самостоятельный исход, а не
        число и не скип (урок `pyflakes`, #465)."""
        (self.tmp / "pytest.ini").write_text("[[[not ini", encoding="utf-8")
        rule = hx.collector_rule(str(self.tmp))
        self.assertEqual(rule["state"], "unmeasured")
        self.assertIn("pytest.ini", rule["why"])


class Reexport(unittest.TestCase):
    SHIM = ("from helper import test_x\n\n")

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.files = {
            "helper.py": "import spa_core.risk.policy\n\n\ndef test_x():\n    assert 1\n",
        }

    def test_a_reexport_shim_is_NOT_counted_as_overstatement(self):
        """Положительный контроль на ложь: у ТЕСТА имя действительно не зовётся,
        но зовёт его СОБИРАТЕЛЬ, и код исполняется."""
        outcome, ev = classify_scene(self.tmp, {**self.files, "test_s.py": self.SHIM},
                                     "test_s.py", "helper.py")
        self.assertEqual(outcome, hx.REEXPORTED)
        self.assertEqual(ev["collected_as"], ["test_x"])
        self.assertIn(outcome, hx.EXECUTED_BY_SOMEONE_ELSE)

    def test_a_name_the_collector_does_NOT_collect_stays_overstatement(self):
        """Обратная сторона по ИМЕНИ: звено (совпадение с образцом) порвано."""
        files = {"helper.py": "import spa_core.risk.policy\n\n\ndef helper_fn():\n    pass\n",
                 "test_s.py": "from helper import helper_fn\n"}
        outcome, _ = classify_scene(self.tmp, files, "test_s.py", "helper.py")
        self.assertEqual(outcome, hx.ONLY_IMPORTED)

    def test_an_import_inside_a_function_is_NOT_a_reexport(self):
        """Обратная сторона по ОБЛАСТИ: звено (пространство модуля) порвано —
        собиратель такое имя не видит."""
        files = {**self.files,
                 "test_s.py": "def test_a():\n    from helper import test_x\n"}
        outcome, _ = classify_scene(self.tmp, files, "test_s.py", "helper.py")
        self.assertEqual(outcome, hx.ONLY_IMPORTED)

    def test_an_unmeasured_collector_rule_does_NOT_fall_back_to_overstatement(self):
        """Обратная сторона по ПРАВИЛУ: правило не измерено ⇒ решение не
        принимается, а не подменяется умолчанием."""
        outcome, ev = classify_scene(
            self.tmp, {**self.files, "test_s.py": self.SHIM}, "test_s.py",
            "helper.py", collector={"state": "unmeasured", "why": "сцена"})
        self.assertEqual(outcome, hx.HIDDEN)
        self.assertIn("collector_rule_not_measured", ev["hidden_by"])

    def test_a_collector_rule_not_passed_at_all_is_also_undecided(self):
        outcome, _ = classify_scene(
            self.tmp, {**self.files, "test_s.py": self.SHIM}, "test_s.py",
            "helper.py", collector=None)
        # ``collector=None`` здесь означает «не подан»: правило читается со
        # сцены, где pytest.ini нет ⇒ умолчание, и пара есть пересылка.
        self.assertEqual(outcome, hx.REEXPORTED)


# ──────────────────────────────── перепись ───────────────────────────────────

def reach_doc(findings: list[dict]) -> dict:
    """Документ соседа — ВХОДОМ. Население меры не считается здесь второй раз."""
    return {"findings": findings, "unmeasured_reason": ""}


class Measure(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _measure(self, files, findings, **kw):
        scene(self.tmp, files)
        return hx.measure(str(self.tmp), reach_doc=reach_doc(findings), **kw)

    def test_the_list_of_outcomes_is_CLOSED_and_sums_to_the_population(self):
        """Инв. #17: сумма исходов равна населению, иначе перечень не закрыт."""
        files = {**HELPER,
                 "test_a.py": "import helper\n\n\ndef test_a():\n    helper.f()\n",
                 "test_b.py": "import helper\n\n\ndef test_b():\n    assert 1\n"}
        doc = self._measure(files, [
            {"file": "test_a.py", "surface": "risk", "depth": 1,
             "chain": ["test_a.py", "helper.py"]},
            {"file": "test_b.py", "surface": "risk", "depth": 1,
             "chain": ["test_b.py", "helper.py"]},
        ])
        self.assertEqual(doc["population"], 2)
        self.assertEqual(doc["sum_of_counts"], doc["population"])
        self.assertEqual(sum(doc["counts"].values()), 2)
        self.assertEqual(doc["counts"][hx.CALLED], 1)
        self.assertEqual(doc["counts"][hx.ONLY_IMPORTED], 1)
        self.assertEqual(len(doc["rows"]), 2)

    def test_per_surface_sums_match_the_rows(self):
        files = {**HELPER,
                 "test_a.py": "import helper\n\n\ndef test_a():\n    helper.f()\n"}
        doc = self._measure(files, [
            {"file": "test_a.py", "surface": "risk", "depth": 1,
             "chain": ["test_a.py", "helper.py"]},
            {"file": "test_a.py", "surface": "security", "depth": 1,
             "chain": ["test_a.py", "helper.py"]},
        ])
        for surface, local in doc["per_surface"].items():
            self.assertEqual(sum(local.values()),
                             len([r for r in doc["rows"] if r["surface"] == surface]))

    def test_an_unmeasured_neighbour_makes_US_unmeasured(self):
        doc = hx.measure(str(self.tmp),
                         reach_doc={"findings": [], "unmeasured_reason": "дерева нет"})
        self.assertTrue(doc["unmeasured_reason"])
        self.assertEqual(hx.verdict(doc), "unmeasured")
        self.assertEqual(hx.EXIT_CODES[hx.verdict(doc)], 2)

    def test_zero_findings_is_NOT_printed_as_no_overstatement(self):
        """fail-OPEN тише красного теста: «все нули» на пустом населении
        читались бы как «завышения нет»."""
        doc = hx.measure(str(self.tmp), reach_doc=reach_doc([]))
        self.assertEqual(hx.verdict(doc), "unmeasured")
        self.assertIn("нулевое население", doc["unmeasured_reason"])
        self.assertTrue(hx.format_report(doc).startswith("НЕ ИЗМЕРЕНО"))

    def test_a_disagreeing_binder_makes_the_number_UNUSABLE(self):
        """fail-CLOSED: пока расхождение механизмов не названо, остаток нельзя
        объявлять ответом."""
        files = {**HELPER, "other.py": "",
                 "test_a.py": "import helper\n\n\ndef test_a():\n    assert 1\n"}
        doc = self._measure(files, [
            {"file": "test_a.py", "surface": "risk", "depth": 1,
             "chain": ["test_a.py", "other.py"]},
        ])
        self.assertEqual(doc["counts"][hx.NO_BINDING], 1)
        self.assertFalse(doc["binder_agrees_with_the_graph"])
        self.assertEqual(hx.verdict(doc), "binder_disagrees_with_the_graph")
        self.assertEqual(hx.EXIT_CODES[hx.verdict(doc)], 2)
        self.assertIn("КОНТРОЛЬ РАСХОДИТСЯ", hx.format_report(doc))

    def test_a_finding_without_a_first_hop_is_named_not_dropped(self):
        files = {**HELPER,
                 "test_a.py": "import helper\n\n\ndef test_a():\n    helper.f()\n"}
        doc = self._measure(files, [
            {"file": "test_a.py", "surface": "risk", "depth": 1,
             "chain": ["test_a.py"]},
        ])
        self.assertEqual(doc["counts"][hx.NO_BINDING], 1)
        self.assertIn("первого шага", doc["rows"][0]["why"])

    def test_an_unparsable_test_is_counted_PER_PAIR_not_per_file(self):
        """Обратная сторона дефекта, найденного при сборке: исход, посчитанный
        один раз на ФАЙЛ, разошёлся бы с населением на втором вхождении."""
        files = {**HELPER, "test_bad.py": "def test_a(:\n"}
        doc = self._measure(files, [
            {"file": "test_bad.py", "surface": "risk", "depth": 1,
             "chain": ["test_bad.py", "helper.py"]},
            {"file": "test_bad.py", "surface": "security", "depth": 1,
             "chain": ["test_bad.py", "helper.py"]},
        ])
        self.assertEqual(doc["counts"][hx.NOT_PARSED], 2)
        self.assertEqual(doc["sum_of_counts"], doc["population"])
        self.assertEqual(len(doc["rows"]), 2)

    def test_an_overstatement_reds_and_its_absence_does_not(self):
        files = {**HELPER,
                 "test_a.py": "import helper\n\n\ndef test_a():\n    helper.f()\n",
                 "test_b.py": "import helper\n\n\ndef test_b():\n    assert 1\n"}
        found = self._measure(files, [
            {"file": "test_b.py", "surface": "risk", "depth": 1,
             "chain": ["test_b.py", "helper.py"]}])
        self.assertEqual(hx.verdict(found), "overstatement_measured")
        self.assertEqual(hx.EXIT_CODES[hx.verdict(found)], 1)

        clean = self._measure(files, [
            {"file": "test_a.py", "surface": "risk", "depth": 1,
             "chain": ["test_a.py", "helper.py"]}])
        self.assertEqual(hx.verdict(clean), "no_overstatement_found")
        self.assertEqual(hx.EXIT_CODES[hx.verdict(clean)], 0)

    def test_every_verdict_has_an_exit_code(self):
        self.assertEqual(set(hx.EXIT_CODES), {
            "unmeasured", "binder_disagrees_with_the_graph",
            "overstatement_measured", "no_overstatement_found"})


# ─────────────────────── цена «ввоз исполняет тело модуля» ───────────────────

class ImportTimePrice(unittest.TestCase):
    MODULE_LEVEL = {
        "helper.py": "import spa_core.risk.policy\n\n\ndef f():\n    return 1\n",
        "test_a.py": "import helper\n\n\ndef test_a():\n    assert 1\n",
    }
    GUARDED = {
        "helper.py": "def f():\n    import spa_core.risk.policy\n    return 1\n",
        "test_a.py": "import helper\n\n\ndef test_a():\n    assert 1\n",
    }
    FINDING = [{"file": "test_a.py", "surface": "risk", "depth": 1,
                "chain": ["test_a.py", "helper.py"]}]

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _doc(self, files, **kw):
        scene(self.tmp, files)
        return hx.measure(str(self.tmp), reach_doc=reach_doc(self.FINDING), **kw)

    def test_the_price_is_NOT_ASKED_by_default_and_prints_no_zero(self):
        """Урок ADR-673: не спрошено ⇒ третий исход, а не ноль."""
        doc = self._doc(self.MODULE_LEVEL)
        self.assertEqual(doc["import_time_price"], {"state": "not_asked"})
        self.assertNotIn("road_runs_at_import_time", doc["import_time_price"])
        self.assertIn("НЕ СПРОШЕНА", hx.format_report(doc))

    def test_a_module_level_road_DOES_run_at_import_time(self):
        doc = self._doc(self.MODULE_LEVEL, price_import_time=True)
        price = doc["import_time_price"]
        self.assertEqual(price["state"], "asked")
        self.assertEqual(price["road_runs_at_import_time"], 1)
        self.assertEqual(price["road_does_not_run_at_import_time"], 0)

    def test_a_road_hidden_inside_a_function_does_NOT_run_at_import_time(self):
        """Обратная сторона с НАЗВАННЫМ звеном: дуга внутри функции при импорте
        не исполняется, поэтому код поверхности не исполняется ВОВСЕ."""
        doc = self._doc(self.GUARDED, price_import_time=True)
        price = doc["import_time_price"]
        self.assertEqual(price["road_runs_at_import_time"], 0)
        self.assertEqual(price["road_does_not_run_at_import_time"], 1)

    def test_nothing_to_price_is_said_and_not_shown_as_zero(self):
        files = {**self.MODULE_LEVEL,
                 "test_b.py": "import helper\n\n\ndef test_b():\n    helper.f()\n"}
        scene(self.tmp, files)
        doc = hx.measure(str(self.tmp), price_import_time=True, reach_doc=reach_doc(
            [{"file": "test_b.py", "surface": "risk", "depth": 1,
              "chain": ["test_b.py", "helper.py"]}]))
        self.assertEqual(doc["import_time_price"]["state"], "no_pairs_to_price")


# ─────────────────────────────── отчёт ───────────────────────────────────────

class Report(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        scene(self.tmp, {**HELPER,
                         "test_b.py": "import helper\n\n\ndef test_b():\n    assert 1\n"})
        self.doc = hx.measure(str(self.tmp), reach_doc=reach_doc(
            [{"file": "test_b.py", "surface": "risk", "depth": 1,
              "chain": ["test_b.py", "helper.py"]}]))

    def test_the_report_names_EVERY_outcome_of_the_closed_list(self):
        text = hx.format_report(self.doc)
        for name in hx.OUTCOMES:
            self.assertIn(name, text)

    def test_the_report_prints_the_BRACKET_not_a_single_number(self):
        text = hx.format_report(self.doc)
        self.assertIn("ВИЛКА завышения", text)
        self.assertIn("НЕ МЕНЬШЕ", text)
        self.assertIn("НЕ БОЛЬШЕ", text)

    def test_the_report_names_WHERE_the_collector_rule_came_from(self):
        self.assertIn("правило собирателя", hx.format_report(self.doc))
        self.assertIn(self.doc["collector_rule"]["source"],
                      hx.format_report(self.doc))

    def test_the_report_names_the_lower_bound_AS_a_lower_bound(self):
        text = hx.format_report(self.doc)
        self.assertIn("НИЖНЯЯ ГРАНИЦА", text)

    def test_a_list_that_does_not_sum_is_called_out(self):
        """Обратная сторона инв. #17: разошедшаяся сумма обязана быть НАЗВАНА,
        а не напечатана молча."""
        doc = dict(self.doc, sum_of_counts=self.doc["population"] + 1)
        self.assertIn("перечень исходов НЕ закрыт", hx.format_report(doc))

    def test_the_report_says_what_it_does_NOT_report(self):
        self.assertIn("НЕ ДОКЛАДЫВАЕТ", hx.format_report(self.doc))


# ────────────────── правило не переписано второй копией (ADR-522) ────────────

class RuleIsNotCopied(unittest.TestCase):
    def test_the_opaque_forms_are_the_NEIGHBOURS_list_not_a_second_one(self):
        """Переименование формы у соседа обязано КРАСНИТЬ здесь."""
        self.assertTrue(hx._MODULE_RETURNING <= set(census._OPAQUE_IMPORTERS),
                        f"{hx._MODULE_RETURNING} ⊄ {set(census._OPAQUE_IMPORTERS)}")

    def test_opaque_names_are_read_by_the_NEIGHBOURS_function(self):
        """Доказательство проводки, а не наличия имени: подменяем функцию
        СОСЕДА и смотрим, изменился ли наш ответ."""
        call = parse("importlib.import_module('x')").body[0].value  # type: ignore[attr-defined]
        self.assertEqual(hx.reach_census_opaque(call), {"x"})
        original = census._opaque_import_names
        try:
            census._opaque_import_names = lambda _node: {"ПОДМЕНА"}  # type: ignore[assignment]
            self.assertEqual(hx.reach_census_opaque(call), {"ПОДМЕНА"})
        finally:
            census._opaque_import_names = original  # type: ignore[assignment]

    def test_the_relative_import_arithmetic_is_the_NEIGHBOURS_copy(self):
        import tempfile
        with tempfile.TemporaryDirectory() as raw:
            root = scene(pathlib.Path(raw), {
                "pkg/__init__.py": "", "pkg/helper.py": "",
                "pkg/test_x.py": "from . import helper\n"})
            node = parse((root / "pkg/test_x.py").read_text()).body[0]
            # Набор НАДМНОЖЕСТВО: сосед кладёт в дугу и якорь пакета
            # (``pkg/__init__.py``), потому что ввоз подмодуля исполняет и тело
            # пакета. Сужать это здесь значило бы завести второе правило дуги.
            self.assertEqual(
                hx._node_targets(node, "pkg/test_x.py", root, {}),  # type: ignore[arg-type]
                {"pkg/helper.py", "pkg/__init__.py"})
            original = reach._relative_edges
            try:
                reach._relative_edges = lambda *_a, **_k: ["ПОДМЕНА"]  # type: ignore[assignment]
                self.assertEqual(
                    hx._node_targets(node, "pkg/test_x.py", root, {}),  # type: ignore[arg-type]
                    {"ПОДМЕНА"})
            finally:
                reach._relative_edges = original  # type: ignore[assignment]

    def test_absolute_names_are_resolved_by_the_NEIGHBOURS_function(self):
        import tempfile
        with tempfile.TemporaryDirectory() as raw:
            root = scene(pathlib.Path(raw), {"helper.py": "", "test_x.py": "import helper\n"})
            node = parse("import helper").body[0]
            self.assertEqual(
                hx._node_targets(node, "test_x.py", root, {}),  # type: ignore[arg-type]
                {"helper.py"})
            original = reach._resolve
            try:
                reach._resolve = lambda *_a, **_k: "ПОДМЕНА"  # type: ignore[assignment]
                self.assertEqual(
                    hx._node_targets(node, "test_x.py", root, {}),  # type: ignore[arg-type]
                    {"ПОДМЕНА"})
            finally:
                reach._resolve = original  # type: ignore[assignment]

    def test_the_surfaces_are_the_neighbours_and_not_redeclared_here(self):
        source = pathlib.Path(hx.__file__).read_text(encoding="utf-8")
        self.assertNotIn("DECLARED_SURFACES: dict", source)
        self.assertNotIn("DECLARED_SURFACES = {", source)


# ────────────────────── у меры нет двери к машине ────────────────────────────

class NoDoorToTheMachine(unittest.TestCase):
    def test_measure_has_no_door_to_the_machine(self):
        """Единственный вход меры — ПУТЬ. Ни часов, ни pid, ни сети, ни git:
        поэтому в батарее нет ни литеральной даты, ни литерального pid, ни
        ``git init`` — не по дисциплине автора, а по построению меры."""
        source = pathlib.Path(hx.__file__).read_text(encoding="utf-8")
        for door in ("import time", "import datetime", "import subprocess",
                     "import socket", "import os.path", "os.kill(",
                     "datetime.now", "time.time("):
            self.assertNotIn(door, source, f"дверь к машине: {door}")

    def test_the_same_tree_measures_the_same_twice(self):
        """Детерминизм: та же сцена ⇒ тот же документ."""
        import tempfile
        with tempfile.TemporaryDirectory() as raw:
            root = scene(pathlib.Path(raw), {
                **HELPER,
                "test_b.py": "import helper\n\n\ndef test_b():\n    assert 1\n"})
            finding = reach_doc([{"file": "test_b.py", "surface": "risk",
                                  "depth": 1, "chain": ["test_b.py", "helper.py"]}])
            first = hx.measure(str(root), reach_doc=finding)
            second = hx.measure(str(root), reach_doc=finding)
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()


# ──────────────── проводка: у прибора без артефакта один читатель ────────────

def _office_aliases(module_suffix: str) -> tuple[set[str], list[ast.Call]]:
    """Имена, под которыми шаг 0-офис ввозит прибор, и все зовы файла.

    Мерится ФОРМА ВЫЗОВА, а не наличие импорта: зелёный храповик непозванных
    модулей читателем НЕ является — один импорт ради чужого правила гасит его
    молча (ADR-547, урок #760).
    """
    office = (pathlib.Path(hx.__file__).parents[2]
              / "scripts" / "consume_office_reports.py")
    tree = ast.parse(office.read_text(encoding="utf-8"))
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module \
                and node.module.endswith(module_suffix):
            aliases |= {a.asname or a.name for a in node.names}
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    return aliases, calls


class OfficeWiring(unittest.TestCase):
    def test_the_office_step_CALLS_the_instrument_and_prints_it(self):
        """Артефакта прибор не производит НАМЕРЕННО (ADR-524), поэтому читатель
        у него ровно один — шаг 0-офис, и он обязан ЗВАТЬ и замер, и отрисовку."""
        aliases, calls = _office_aliases("helper_execution_census")
        self.assertTrue(aliases, "шаг 0-офис не ввозит прибор вовсе")
        called = {c.func.id for c in calls
                  if isinstance(c.func, ast.Name) and c.func.id in aliases}
        self.assertEqual(len(called), 2,
                         f"офис зовёт {sorted(called)}: нужны и замер, и отрисовка")

    def test_the_probe_reds_on_a_module_the_office_does_not_read(self):
        """Обратная сторона с НАЗВАННЫМ звеном: та же проба на имени, которого
        в шаге 0-офис нет, обязана дать ПУСТО — иначе она зелена всегда и
        проводки не мерит вовсе."""
        aliases, _ = _office_aliases("ПРИБОРА_С_ТАКИМ_ИМЕНЕМ_НЕТ")
        self.assertEqual(aliases, set())

    def test_the_office_step_does_not_ask_the_expensive_axis(self):
        """Ось цены требует ВТОРОГО графа; такт шага 0-офис дороже ответа.
        Не спрошено ⇒ прибор говорит это вслух, а не печатает ноль."""
        office = (pathlib.Path(hx.__file__).parents[2]
                  / "scripts" / "consume_office_reports.py")
        source = office.read_text(encoding="utf-8")
        self.assertNotIn("price_import_time=True", source)


# ─────────── дыры, найденные МУТАЦИОННЫМ замером (цикл #811) ────────────────
# Каждый тест ниже убивает НАЗВАННОГО выжившего мутанта. Он не «ещё одна
# проверка»: до него соответствующая правка прибора проходила молча.

class OutcomeNamesAreLiteral(unittest.TestCase):
    def test_the_outcome_names_are_pinned_to_LITERALS_not_to_themselves(self):
        """Сверка с собственной константой зелена ПО ПОСТРОЕНИЮ (урок #722):
        переименуй исход — и обе стороны сравнения поедут вместе. Имена
        машинные, их читает шаг 0-офис, поэтому они закреплены ЛИТЕРАЛАМИ."""
        self.assertEqual(list(hx.OUTCOMES), [
            "first_hop_called_by_the_test",
            "first_hop_reexported_for_the_collector",
            "first_hop_only_imported",
            "first_hop_used_but_not_called",
            "binding_not_declared_by_the_form",
            "first_hop_not_bound_in_the_test",
            "test_file_not_parsed",
        ])
        self.assertEqual(list(hx.UNDECIDED), [
            "first_hop_used_but_not_called",
            "binding_not_declared_by_the_form",
            "first_hop_not_bound_in_the_test",
            "test_file_not_parsed",
        ])
        self.assertEqual(list(hx.EXECUTED_BY_SOMEONE_ELSE),
                         ["first_hop_reexported_for_the_collector"])
        self.assertEqual(len(set(hx.OUTCOMES)), len(hx.OUTCOMES))


class EvidenceIsSilentWhenNothingIsHidden(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_no_hidden_form_means_NO_hidden_by_field(self):
        """Всегда заполненное поле есть ложное успокоение (урок ADR-673)."""
        _outcome, ev = classify_scene(
            self.tmp, {**HELPER,
                       "test_x.py": "import helper\n\n\ndef test_a():\n    assert 1\n"},
            "test_x.py", "helper.py")
        self.assertNotIn("hidden_by", ev)

    def test_a_scene_without_broken_calls_reports_NO_broken_call_files(self):
        scene(self.tmp, {**HELPER,
                         "test_b.py": "import helper\n\n\ndef test_b():\n    assert 1\n"})
        doc = hx.measure(str(self.tmp), reach_doc=reach_doc(
            [{"file": "test_b.py", "surface": "risk", "depth": 1,
              "chain": ["test_b.py", "helper.py"]}]))
        self.assertEqual(doc["broken_call_files"], [])

    def test_a_scene_WITH_a_broken_call_names_the_file(self):
        """Обратная сторона: звено (счёт оборванных зовов) порвано ⇒ файл не
        назван, и цена меры исчезла бы молча."""
        scene(self.tmp, {**HELPER,
                         "test_c.py": "import helper\n\n\ndef test_c():\n"
                                      "    d = {}\n    d['k'].f()\n"})
        doc = hx.measure(str(self.tmp), reach_doc=reach_doc(
            [{"file": "test_c.py", "surface": "risk", "depth": 1,
              "chain": ["test_c.py", "helper.py"]}]))
        self.assertEqual(doc["broken_call_files"], ["test_c.py"])


class UndecidednessAppliesOnlyToModuleScope(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.files = {
            "helper.py": "import spa_core.risk.policy\n\n\ndef test_x():\n    assert 1\n"}

    def test_an_unmeasured_rule_does_NOT_touch_a_function_scope_binding(self):
        """Собиратель не видит имени, ввезённого внутри функции, — поэтому
        неизмеренность ЕГО правила про такую пару ничего не говорит, и
        «только ввезено» остаётся «только ввезено»."""
        outcome, _ = classify_scene(
            self.tmp,
            {**self.files,
             "test_s.py": "def test_a():\n    from helper import test_x\n"},
            "test_s.py", "helper.py",
            collector={"state": "unmeasured", "why": "сцена"})
        self.assertEqual(outcome, hx.ONLY_IMPORTED)

    def test_a_PARTIAL_collector_match_is_not_a_shim(self):
        """Обратная сторона: файл, ввозящий и собираемое, и НЕ собираемое имя,
        пересылкой не является — иначе любой модульный импорт с одним `test_*`
        среди имён уехал бы из ответа заказа."""
        files = {"helper.py": "import spa_core.risk.policy\n\n\n"
                              "def test_x():\n    assert 1\n\n\ndef helper_fn():\n    pass\n",
                 "test_s.py": "from helper import test_x, helper_fn\n"}
        outcome, _ = classify_scene(self.tmp, files, "test_s.py", "helper.py")
        self.assertEqual(outcome, hx.ONLY_IMPORTED)

    def test_the_tool_pytest_section_name_is_honoured_too(self):
        (self.tmp / "pytest.ini").write_text(
            "[tool:pytest]\npython_functions = check_*\n", encoding="utf-8")
        rule = hx.collector_rule(str(self.tmp))
        self.assertEqual(rule["patterns"], ["check_*"])


class PopulationBoundaries(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_depth_ZERO_row_is_NOT_part_of_the_population(self):
        """Глубина 0 у соседа значит «правило видит пару УЖЕ сегодня» — это не
        дорога через помощника, и спрашивать о ней нечего."""
        scene(self.tmp, {**HELPER,
                         "test_a.py": "import helper\n\n\ndef test_a():\n    assert 1\n"})
        doc = hx.measure(str(self.tmp), reach_doc=reach_doc(
            [{"file": "test_a.py", "surface": "risk", "depth": 0,
              "chain": ["test_a.py", "helper.py"]}]))
        self.assertEqual(hx.verdict(doc), "unmeasured")

    def test_premise_the_unmeasured_document_always_carries_a_zero_population(self):
        """Доказательство РАВНОСИЛЬНОСТИ, а не ещё одна проверка: `or` в
        вердикте нельзя отличить от `and`, потому что второй операнд истинен
        всегда, когда истинен первый. Это свойство предпосылки, и вот оно."""
        doc = hx._unmeasured("сцена", 3)
        self.assertEqual(doc["population"], 0)
        self.assertEqual(doc["sum_of_counts"], 0)
        self.assertTrue(doc["unmeasured_reason"])


class PriceBoundary(unittest.TestCase):
    TWO_HOPS = {
        "deep.py": "import spa_core.risk.policy\n",
        "helper.py": "import deep\n\n\ndef f():\n    return 1\n",
        "test_a.py": "import helper\n\n\ndef test_a():\n    assert 1\n",
    }
    FINDING = [{"file": "test_a.py", "surface": "risk", "depth": 2,
                "chain": ["test_a.py", "helper.py", "deep.py"]}]

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        scene(self.tmp, self.TWO_HOPS)

    def _price(self, max_depth):
        return hx.measure(str(self.tmp), reach_doc=reach_doc(self.FINDING),
                          max_depth=max_depth,
                          price_import_time=True)["import_time_price"]

    def test_a_road_exactly_at_the_limit_still_counts_as_running(self):
        self.assertEqual(self._price(2)["road_runs_at_import_time"], 1)

    def test_a_road_one_hop_PAST_the_limit_does_not(self):
        """Обратная сторона границы с НАЗВАННЫМ звеном: предел есть ВЫБОР, и
        сдвиг его на одну дугу обязан менять ответ."""
        self.assertEqual(self._price(1)["road_runs_at_import_time"], 0)
        self.assertEqual(self._price(1)["road_does_not_run_at_import_time"], 1)


class ReportBranches(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _doc(self, extra_files=None, findings=None, **kw):
        files = {**HELPER,
                 "test_b.py": "import helper\n\n\ndef test_b():\n    assert 1\n",
                 "test_a.py": "import helper\n\n\ndef test_a():\n    helper.f()\n"}
        files.update(extra_files or {})
        scene(self.tmp, files)
        rows = findings or [{"file": "test_b.py", "surface": "risk", "depth": 1,
                             "chain": ["test_b.py", "helper.py"]}]
        return hx.measure(str(self.tmp), reach_doc=reach_doc(rows), **kw)

    def test_a_healthy_sum_does_NOT_print_the_not_closed_warning(self):
        """Всегда печатаемое предупреждение не отличимо от настоящего."""
        self.assertNotIn("перечень исходов НЕ закрыт",
                         hx.format_report(self._doc()))

    def test_an_asked_price_prints_the_numbers_and_drops_the_not_asked_line(self):
        text = hx.format_report(self._doc(price_import_time=True))
        self.assertNotIn("НЕ СПРОШЕНА", text)
        self.assertIn("цена «ввоз исполняет тело модуля»: из 1", text)

    def test_a_single_finding_does_not_claim_there_are_MORE(self):
        self.assertNotIn("ещё", hx.format_report(self._doc()))

    def test_eleven_findings_name_the_remainder_exactly(self):
        files = {f"test_n{i}.py": "import helper\n\n\ndef test_n():\n    assert 1\n"
                 for i in range(11)}
        rows = [{"file": f"test_n{i}.py", "surface": "risk", "depth": 1,
                 "chain": [f"test_n{i}.py", "helper.py"]} for i in range(11)]
        text = hx.format_report(self._doc(extra_files=files, findings=rows))
        self.assertIn("ещё 1 находок(и)", text)

    def test_the_listing_names_the_CLAIM_and_only_the_findings(self):
        rows = [{"file": "test_b.py", "surface": "risk", "depth": 1,
                 "chain": ["test_b.py", "helper.py"]},
                {"file": "test_a.py", "surface": "risk", "depth": 1,
                 "chain": ["test_a.py", "helper.py"]}]
        text = hx.format_report(self._doc(findings=rows))
        listed = [l for l in text.split("\n") if f"[{hx.ONLY_IMPORTED}]" in l]
        self.assertEqual(len(listed), 1)
        self.assertIn("test_b.py", listed[0])
        self.assertIn("притязание helper", listed[0])


class CommandLine(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        scene(self.tmp, {**HELPER,
                         "test_b.py": "import helper\n\n\ndef test_b():\n    assert 1\n"})

    def test_json_output_is_PARSED_not_compared_as_text(self):
        import contextlib
        import io
        import json as _json
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = hx.main(["--root", str(self.tmp), "--json"])
        doc = _json.loads(buf.getvalue())
        self.assertEqual(code, 2)  # на сцене у соседа нет предписанных каталогов
        self.assertIn("counts", doc)
        self.assertIn("unmeasured_reason", doc)

    def test_the_plain_output_is_the_report_and_not_json(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            hx.main(["--root", str(self.tmp)])
        text = buf.getvalue()
        self.assertTrue(text.startswith("НЕ ИЗМЕРЕНО"), text[:80])
        self.assertNotIn('"counts"', text)


class MoreMutationGaps(unittest.TestCase):
    """Вторая волна: выжившие мутанты, разобранные после усиления батареи."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_test_that_declares_the_surface_ITSELF_runs_it_at_import_time(self):
        """Дефект, найденный мутационным замером: во ВТОРОМ роде графа глубина 0
        значит «сам тест ввозит поверхность верхним уровнем», и тогда её код
        исполняется ввозом тем более. Отсечь такую пару значило бы ответить
        «не исполняется» о паре, которая исполняется наверняка."""
        scene(self.tmp, {
            "helper.py": "import spa_core.risk.policy\n\n\ndef f():\n    return 1\n",
            "test_a.py": "import spa_core.risk.policy\nimport helper\n\n\n"
                         "def test_a():\n    assert 1\n"})
        price = hx.measure(str(self.tmp), price_import_time=True, reach_doc=reach_doc(
            [{"file": "test_a.py", "surface": "risk", "depth": 1,
              "chain": ["test_a.py", "helper.py"]}]))["import_time_price"]
        self.assertEqual(price["road_runs_at_import_time"], 1)
        self.assertEqual(price["road_does_not_run_at_import_time"], 0)

    def test_an_empty_declaration_is_NOT_a_declaration(self):
        """Обратная сторона: `python_functions =` без значений означало бы
        «собирается НИЧЕГО», и такое правило встало бы на место умолчания."""
        (self.tmp / "pytest.ini").write_text(
            "[pytest]\npython_functions =\n", encoding="utf-8")
        rule = hx.collector_rule(str(self.tmp))
        self.assertEqual(rule["state"], "default")
        self.assertEqual(rule["patterns"], list(hx._PYTEST_DEFAULT_FUNCTIONS))

    def test_a_price_that_had_nothing_to_measure_is_PRINTED_as_such(self):
        """Ветвь отчёта, которую ни одна сцена не исполняла: «нечего оценивать»
        и «не измерено» обязаны печататься своими словами, а не строкой
        спрошенной оси (у той и ключей-то нет)."""
        base = {"population": 1, "max_depth": 3, "sum_of_counts": 1,
                "counts": {name: 0 for name in hx.OUTCOMES}, "rows": [],
                "per_surface": {}, "broken_call_files": [],
                "binder_agrees_with_the_graph": True, "unmeasured_reason": "",
                "collector_rule": {"state": "default", "source": "сцена",
                                   "patterns": ["test*"]}}
        empty = hx.format_report(
            dict(base, import_time_price={"state": "no_pairs_to_price"}))
        self.assertIn("[НЕ ИЗМЕРЕНО] цена", empty)
        unmeasured = hx.format_report(dict(base, import_time_price={
            "state": "unmeasured", "why": "дерева нет"}))
        self.assertIn("дерева нет", unmeasured)

    def test_exactly_ten_findings_do_not_claim_a_remainder(self):
        """Граница списка находок: при ровно десяти остатка НЕТ, и печатать
        «ещё 0» значило бы называть ноль находкой."""
        files = {"helper.py": "import spa_core.risk.policy\n"}
        files.update({f"test_t{i}.py": "import helper\n\n\ndef test_t():\n    assert 1\n"
                      for i in range(10)})
        scene(self.tmp, files)
        rows = [{"file": f"test_t{i}.py", "surface": "risk", "depth": 1,
                 "chain": [f"test_t{i}.py", "helper.py"]} for i in range(10)]
        doc = hx.measure(str(self.tmp), reach_doc=reach_doc(rows))
        self.assertEqual(doc["counts"][hx.ONLY_IMPORTED], 10)
        self.assertNotIn("ещё", hx.format_report(doc))

    def test_premise_an_unresolvable_name_adds_no_member_a_path_can_match(self):
        """Равносильность, а не проверка: мутант, пускающий в набор цели `None`,
        вердикта не меняет, потому что первый шаг дороги есть ПУТЬ-строка, и
        `None` ею не станет ни при каком дереве."""
        node = parse("import nothing_like_this").body[0]
        root = scene(self.tmp, {"test_x.py": "import nothing_like_this\n"})
        targets = hx._node_targets(node, "test_x.py", root, {})  # type: ignore[arg-type]
        self.assertEqual(targets, set())
        self.assertNotIn(None, targets | {"test_x.py"})

    def test_premise_the_parse_cache_is_a_cache_and_nothing_more(self):
        """Равносильность мутанта `if rel not in trees` → True: повторный разбор
        того же файла даёт то же дерево, поэтому кэш влияет на ЦЕНУ, а не на
        ответ. Доказано сравнением документов, а не объявлено."""
        root = scene(self.tmp, {
            "helper.py": "import spa_core.risk.policy\n",
            "test_a.py": "import helper\n\n\ndef test_a():\n    assert 1\n"})
        rows = [{"file": "test_a.py", "surface": s, "depth": 1,
                 "chain": ["test_a.py", "helper.py"]}
                for s in ("risk", "security")]
        doc = hx.measure(str(root), reach_doc=reach_doc(rows))
        self.assertEqual(doc["counts"][hx.ONLY_IMPORTED], 2)
        self.assertEqual({r["outcome"] for r in doc["rows"]}, {hx.ONLY_IMPORTED})

    def test_premise_an_opaque_call_without_a_simple_target_claims_nothing(self):
        """Равносильность мутанта `not targets or value is None` → `and`: вторая
        охрана (`if not names`) и пустой спуск по не-выражению поглощают его."""
        tree = parse("import importlib\nd = {}\n"
                     "d['k'] = importlib.import_module('helper')\n")
        root = scene(self.tmp, {"helper.py": "import spa_core.risk.policy\n"})
        bound, hidden = hx._opaque_claims(tree, root, {})
        self.assertEqual(bound, {})
        self.assertIn("helper.py", hidden)


class DocumentKeysAreClosed(unittest.TestCase):
    """Ключи документа — машинный ИНТЕРФЕЙС, и их перечень обязан быть закрыт.

    Отчёт шага 0-офис есть проза, но `--json` читает машина, и молчаливое
    переименование ключа ломает её, не покраснев нигде. Мутационный замер нашёл
    этот класс целиком: переименования ключей переживали батарею, потому что ни
    один тест не спрашивал ПЕРЕЧЕНЬ.
    """

    DOC_KEYS = {"population", "max_depth", "counts", "sum_of_counts", "rows",
                "per_surface", "import_time_price", "collector_rule",
                "broken_call_files", "binder_agrees_with_the_graph",
                "unmeasured_reason"}
    ROW_KEYS = {"file", "surface", "depth", "first_hop", "outcome"}

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        scene(self.tmp, {**HELPER,
                         "test_b.py": "import helper\n\n\ndef test_b():\n    assert 1\n"})
        self.doc = hx.measure(str(self.tmp), reach_doc=reach_doc(
            [{"file": "test_b.py", "surface": "risk", "depth": 1,
              "chain": ["test_b.py", "helper.py"]}]))

    def test_a_measured_document_carries_exactly_these_keys(self):
        self.assertEqual(set(self.doc), self.DOC_KEYS)
        self.assertEqual(set(self.doc["counts"]), set(hx.OUTCOMES))

    def test_an_unmeasured_document_carries_the_SAME_keys(self):
        """Иначе читатель, разбирающий оба исхода, молча ронял бы один из них."""
        self.assertEqual(set(hx._unmeasured("сцена", 3)), self.DOC_KEYS)

    def test_a_row_carries_exactly_these_keys_plus_its_evidence(self):
        row = self.doc["rows"][0]
        self.assertTrue(self.ROW_KEYS <= set(row), sorted(set(row)))
        self.assertEqual(set(row) - self.ROW_KEYS, {"claims"})

    def test_an_unparsed_row_names_WHY_and_keeps_the_same_skeleton(self):
        scene(self.tmp, {"test_bad.py": "def t(:\n"})
        doc = hx.measure(str(self.tmp), reach_doc=reach_doc(
            [{"file": "test_bad.py", "surface": "risk", "depth": 1,
              "chain": ["test_bad.py", "helper.py"]}]))
        row = doc["rows"][0]
        self.assertTrue(self.ROW_KEYS <= set(row))
        self.assertEqual(set(row) - self.ROW_KEYS, {"why"})
        self.assertTrue(row["why"])

    def test_the_price_axis_carries_exactly_these_keys_in_each_state(self):
        self.assertEqual(set(self.doc["import_time_price"]), {"state"})
        asked = hx.measure(str(self.tmp), price_import_time=True, reach_doc=reach_doc(
            [{"file": "test_b.py", "surface": "risk", "depth": 1,
              "chain": ["test_b.py", "helper.py"]}]))["import_time_price"]
        self.assertEqual(set(asked), {"state", "priced_pairs",
                                      "road_runs_at_import_time",
                                      "road_does_not_run_at_import_time"})

    def test_the_collector_rule_carries_exactly_these_keys_in_each_state(self):
        self.assertEqual(set(self.doc["collector_rule"]),
                         {"state", "source", "patterns"})
        (self.tmp / "pytest.ini").write_text("[[[not ini", encoding="utf-8")
        self.assertEqual(set(hx.collector_rule(str(self.tmp))), {"state", "why"})


class OfficeStepPaysForOneGraphOnly(unittest.TestCase):
    def test_the_office_step_passes_the_NEIGHBOURS_document_down(self):
        """Решение о ЦЕНЕ, закреплённое тестом: граф импортов дерева стои́т ~34 с,
        а шаг 0-офис уже выходит за собственный предел 180 с (карточка
        `inbox-shag-0-ofis-idet-5-minut-pri-predele-180`). Пересчёт того же
        графа второй секцией добавлял **36 с** — замерено; передача документа
        входом оставляет **8 с**. Без этой проверки правка вернула бы второй
        граф МОЛЧА, и срок шага уехал бы без единого красного.
        """
        office = (pathlib.Path(hx.__file__).parents[2]
                  / "scripts" / "consume_office_reports.py")
        tree = ast.parse(office.read_text(encoding="utf-8"))
        aliases, _ = _office_aliases("helper_execution_census")
        passed_down = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in aliases
            and any(kw.arg == "reach_doc" for kw in node.keywords)
        ]
        self.assertEqual(len(passed_down), 1,
                         "замер секции обязан получать документ соседа входом")

    def test_the_measure_accepts_that_document_and_does_not_recount(self):
        """Обратная сторона с НАЗВАННЫМ звеном: подан документ соседа с ОДНОЙ
        находкой ⇒ население РОВНО один, то есть второй раз ничего не считалось."""
        import tempfile
        with tempfile.TemporaryDirectory() as raw:
            root = scene(pathlib.Path(raw), {
                **HELPER,
                "test_b.py": "import helper\n\n\ndef test_b():\n    assert 1\n"})
            doc = hx.measure(str(root), reach_doc=reach_doc(
                [{"file": "test_b.py", "surface": "risk", "depth": 1,
                  "chain": ["test_b.py", "helper.py"]}]))
            self.assertEqual(doc["population"], 1)
