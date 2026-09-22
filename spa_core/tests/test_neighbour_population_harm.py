"""Заказ G68 п. 1: ВРЕД занижения населения зовущих, а не его поверхность.

ADR-445 измерил, у скольких переписей население зовущих занижено формой
вопроса соседа. Незаданный вопрос — меняет ли занижение хоть один ВЫВОД.
Класс, измеренный по поверхности и не спрошенный у исхода, есть та же
«структура вместо исхода», против которой написано правило приёмки.

Каждый тест здесь — положительный контроль с ОБРАТНОЙ стороной: проверяется
не только что прибор говорит нужное на исправном стенде, но и что он ЗАГОВОРИЛ
БЫ иначе, будь состояние обратным. Стенд одноразовый; живой трекер, живое
`data/` и рабочее дерево не трогаются.

Время и личность процесса здесь не участвуют: прибор читает только исходники
стенда, поэтому ни литеральной даты, ни литерального pid в файле нет вовсе
(`.claude/rules/deployment.md`).
"""
from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import census_consumer_census as neighbour
from spa_core.monitoring.rule_second_copy_census import (
    CENSUS_CONSUMERS,
    DECISION_CHANGED,
    DECISION_NOT_EXECUTED,
    DECISION_UNCHANGED,
    NEIGHBOUR_CENSUS,
    NEIGHBOUR_VERDICT_FIELDS,
    PRODUCER,
    ROAD_ARTIFACT,
    ROAD_DYNAMIC,
    ROAD_FINDER,
    ROAD_RENDERER,
    ROAD_RUN,
    SHAPE_AT_IMPORT_LINE,
    SHAPE_NO_LINE,
    TOUCH_DECIDES,
    TOUCH_PRINTS,
    TOUCH_UNRESOLVED,
    _decision_form,
    _decision_projection,
    _flatten_doc,
    _import_line,
    _name_loads,
    _neighbour_names,
    _parent_map,
    _reader_touches,
    _widened_population,
    neighbour_population_harm,
    report,
)
from spa_core.monitoring import rule_second_copy_census as rscc

NEIGHBOUR_REL = "spa_core/monitoring/census_consumer_census.py"
PRODUCER_REL = PRODUCER
OFFICE_REL = "scripts/consume_office_reports.py"

#: Заглушка соседа: у неё есть верхнеуровневый `run(root=…)` (иначе сосед не
#: числит её переписью) и отрисовщик, РАЗРЕШАЕМЫЙ печатью самого модуля.
NEIGHBOUR_STUB = '''
def measure(root):
    return {"status": "OK"}


def format_report(doc):
    return ["stub"]


def run(root=None, *, write=True):
    return measure(root)


def main(argv=None):
    print("\\n".join(format_report({})))
    return 0
'''

#: Заглушка производителя: нужна, чтобы читатель
#: `consumer_registry_completeness` на стенде не был вырожденным (иначе он
#: отвечает UNMEASURED в обоих прогонах и сверка ничего не меряет).
PRODUCER_STUB = '''
def measure(root):
    return {"status": "CLEAN"}


def report(doc):
    return ["p"]


def format_report(doc, *, max_rows=5):
    return report(doc)


def run(root=None, *, dest=None, write=True):
    return measure(root)


def main(argv=None):
    print("\\n".join(report({})))
    return 0
'''


def _scale(sites) -> dict:
    """Масштаб невидимости в той форме, в какой его отдаёт ADR-445."""
    return {"status": "CRITICAL", "sites": list(sites),
            "counts": {"sites": len(list(sites))}}


class Stand:
    """Одноразовое дерево. Прибор читает ИСХОДНИКИ, поэтому стенд — файлы."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.write(NEIGHBOUR_REL, NEIGHBOUR_STUB)
        self.write(PRODUCER_REL, PRODUCER_STUB)

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def close(self) -> None:
        self._tmp.cleanup()


class FlattenDocTests(unittest.TestCase):
    def test_nested_dicts_become_dotted_paths(self) -> None:
        flat = _flatten_doc({"counts": {"critical": 1}, "status": "OK"})
        self.assertEqual(flat["counts.critical"], repr(1))
        self.assertEqual(flat["status"], repr("OK"))

    def test_a_list_is_a_leaf_not_an_index_path(self) -> None:
        """Путь внутрь элемента списка назвал бы координатой ИНДЕКС."""
        flat = _flatten_doc({"rows": [{"a": 1}]})
        self.assertIn("rows", flat)
        self.assertNotIn("rows.0", flat)
        self.assertNotIn("rows.0.a", flat)

    def test_an_empty_dict_is_recorded_not_lost(self) -> None:
        """Обратная сторона: пустой словарь обязан иметь путь, иначе его
        появление/исчезновение прибор бы не заметил вовсе."""
        self.assertEqual(_flatten_doc({"by_road": {}}), {"by_road": "{}"})

    def test_two_docs_differing_inside_a_list_are_reported_as_differing(self) -> None:
        one = _flatten_doc({"rows": [{"file": "a"}]})
        two = _flatten_doc({"rows": [{"file": "a"}, {"file": "b"}]})
        self.assertNotEqual(one["rows"], two["rows"])


class ImportLineTests(unittest.TestCase):
    def test_symbol_form(self) -> None:
        tree = ast.parse("x = 1\nfrom pkg.mod import thing\n")
        self.assertEqual(_import_line(tree, "mod"), 2)

    def test_package_form_leaves_no_dotted_text(self) -> None:
        tree = ast.parse("\n\nfrom pkg import mod\n")
        self.assertEqual(_import_line(tree, "mod"), 3)

    def test_aliased_plain_import(self) -> None:
        tree = ast.parse("import pkg.mod as m\n")
        self.assertEqual(_import_line(tree, "mod"), 1)

    def test_no_import_is_zero_not_a_guess(self) -> None:
        self.assertEqual(_import_line(ast.parse("y = 2\n"), "mod"), 0)


class WidenedPopulationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stand = Stand()
        self.addCleanup(self.stand.close)
        self.stand.write("scripts/reader.py",
                         "\nfrom spa_core.monitoring import "
                         "census_consumer_census\n")
        self.sites = [{"census": "census_consumer_census",
                       "file": "scripts/reader.py"}]

    def test_shape_without_line_puts_zero(self) -> None:
        got = _widened_population(self.stand.root, self.sites,
                                  shape=SHAPE_NO_LINE)
        self.assertEqual([item["line"] for item in got], [0])

    def test_shape_at_import_line_resolves_the_real_line(self) -> None:
        got = _widened_population(self.stand.root, self.sites,
                                  shape=SHAPE_AT_IMPORT_LINE)
        self.assertEqual([item["line"] for item in got], [2])

    def test_root_argument_stays_absent_so_root_agreement_does_not_move(self) -> None:
        """Подставить сюда строку значило бы сдвинуть ещё и согласие о
        значении `root` — то есть измерить вред от собственной подстановки."""
        got = _widened_population(self.stand.root, self.sites,
                                  shape=SHAPE_NO_LINE)
        self.assertEqual([item["root_argument"] for item in got], [None])

    def test_unreadable_file_under_the_line_shape_does_not_crash(self) -> None:
        self.stand.write("scripts/broken.py", "def (:\n")
        got = _widened_population(
            self.stand.root,
            [{"census": "census_consumer_census", "file": "scripts/broken.py"}],
            shape=SHAPE_AT_IMPORT_LINE)
        self.assertEqual([item["line"] for item in got], [0])


class DecisionFormTests(unittest.TestCase):
    def _form(self, source: str, *, needle: str = "value") -> str:
        tree = ast.parse(source)
        parents = _parent_map(tree)
        loads = _name_loads(tree)
        node = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.Name) and n.id == needle
                    and isinstance(n.ctx, ast.Load))
        return _decision_form(parents, node, loads)

    def test_assert_statement_decides(self) -> None:
        self.assertEqual(self._form("assert value\n"), TOUCH_DECIDES)

    def test_if_test_decides(self) -> None:
        self.assertEqual(self._form("if value:\n    pass\n"), TOUCH_DECIDES)

    def test_if_body_does_not_decide(self) -> None:
        """Обратная сторона предыдущего: то же имя в ТЕЛЕ ветки решением не
        является, и назвать его решающим значило бы объявить решением всякое
        упоминание внутри условного блока.

        Сцена нарочно ДОХОДИТ до `if`: форма `keep = {…value…}` обрывала разбор
        на присваивании, и ветка условия не осматривалась вовсе — батарея
        поймала это выжившей мутацией «тело ветки тоже решает».
        """
        self.assertEqual(self._form("if flag:\n    bag.append(value)\n"),
                         TOUCH_UNRESOLVED)

    def test_the_if_scene_really_reaches_the_condition_node(self) -> None:
        """Контроль контроля: у сцены выше подъём обязан ДОЙТИ до `ast.If`,
        иначе тест выше зелен по построению и ничего не охраняет."""
        tree = ast.parse("if flag:\n    bag.append(value)\n")
        parents = _parent_map(tree)
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.Name)
                    and n.id == "value" and isinstance(n.ctx, ast.Load))
        chain = []
        while node is not None:
            node = parents.get(id(node))
            if node is not None:
                chain.append(type(node))
        self.assertIn(ast.If, chain)

    def test_comprehension_guard_decides(self) -> None:
        self.assertEqual(self._form("rows = [x for x in y if value]\n"),
                         TOUCH_DECIDES)

    def test_comprehension_element_does_not_decide(self) -> None:
        self.assertEqual(self._form("rows = [value for x in y]\n"),
                         TOUCH_UNRESOLVED)

    def test_unittest_assertion_decides(self) -> None:
        self.assertEqual(self._form("self.assertIn('a', value)\n"),
                         TOUCH_DECIDES)

    def test_print_only_prints(self) -> None:
        self.assertEqual(self._form("print(value)\n"), TOUCH_PRINTS)

    def test_fstring_only_prints(self) -> None:
        self.assertEqual(self._form("out = f'n={value}'\n"), TOUCH_PRINTS)

    def test_one_binding_hop_reaches_the_assertion(self) -> None:
        """`files = {…}` затем `assertIn(…, files)` есть ОДНО чтение с
        решением; разорвать их значило бы объявить решающий тест печатающим."""
        self.assertEqual(
            self._form("files = value\nself.assertIn('a', files)\n"),
            TOUCH_DECIDES)

    def test_two_binding_hops_are_the_third_outcome(self) -> None:
        """Предел объявлен: цепочка переприсваиваний уводит от предмета, и её
        честное имя — третий исход, а не «решает»/«печатает»."""
        self.assertEqual(
            self._form("a = value\nb = a\nself.assertIn('x', b)\n"),
            TOUCH_UNRESOLVED)

    def test_value_only_stored_is_unresolved_not_silent_no(self) -> None:
        self.assertEqual(self._form("bag = {'k': value}\n"), TOUCH_UNRESOLVED)

    def test_name_loads_excludes_assignment_targets(self) -> None:
        """Цель присваивания — тоже узел `Name`; считать её чтением значило бы
        сделать ветку «читателя нет» недостижимой."""
        loads = _name_loads(ast.parse("value = 1\n"))
        self.assertEqual(loads.get("value", []), [])


class NeighbourNamesTests(unittest.TestCase):
    def test_all_five_import_forms_are_parsed(self) -> None:
        source = ("from spa_core.monitoring import census_consumer_census\n"
                  "import spa_core.monitoring.census_consumer_census as c2\n"
                  "from spa_core.monitoring.census_consumer_census import "
                  "format_report as fr\n"
                  "import importlib\n"
                  "MOD = 'spa_core.monitoring.census_consumer_census'\n"
                  "n = importlib.import_module(MOD)\n")
        seen = _neighbour_names(ast.parse(source), NEIGHBOUR_CENSUS,
                                {"MOD": NEIGHBOUR_CENSUS})
        self.assertEqual(seen["aliases"], {"census_consumer_census", "c2"})
        self.assertEqual(seen["symbols"], {"fr": "format_report"})
        self.assertEqual(seen["dynamic"], {NEIGHBOUR_CENSUS})

    def test_a_renamed_symbol_keeps_the_name_it_has_AT_THE_NEIGHBOUR(self) -> None:
        """Ввоз `as` переименовывает, и сверка по имени ЧИТАТЕЛЯ объявила бы
        ввоз отрисовщика отсутствующим — ровно так первый заход замера не увидел
        шаг 0-офис."""
        seen = _neighbour_names(ast.parse(
            "from spa_core.monitoring.census_consumer_census import "
            "format_report as _ccc_report\n"), NEIGHBOUR_CENSUS, {})
        self.assertEqual(set(seen["symbols"].values()), {"format_report"})

    def test_a_dynamic_import_of_someone_else_is_not_our_road(self) -> None:
        seen = _neighbour_names(ast.parse(
            "import importlib\nn = importlib.import_module('json')\n"),
            NEIGHBOUR_CENSUS, {})
        self.assertEqual(seen["dynamic"], set())


class ReaderTouchesTests(unittest.TestCase):
    def _touches(self, source: str, *, rel: str = "scripts/r.py",
                 renderers=("format_report",)) -> dict:
        return _reader_touches(rel, ast.parse(source), NEIGHBOUR_CENSUS,
                               "census_consumer_census.json", renderers)

    def test_finder_call_is_the_finder_road_and_its_guard_decides(self) -> None:
        got = self._touches(
            "from spa_core.monitoring import census_consumer_census as n\n"
            "bad = [x for x in y if n.find_by_name_consumers(root, c)]\n")
        self.assertIn(ROAD_FINDER, got["roads"])
        self.assertEqual([(t["field"], t["form"]) for t in got["touches"]],
                         [("by_name", TOUCH_DECIDES)])

    def test_a_renamed_imported_finder_is_still_a_finder(self) -> None:
        """Сверка по имени У ЧИТАТЕЛЯ потеряла бы искатель, ввезённый `as` —
        батарея поймала это выжившей мутацией `called = func.id`."""
        got = self._touches(
            "from spa_core.monitoring.census_consumer_census import "
            "find_by_name_consumers as fbnc\n"
            "rows = [x for x in y if fbnc(root, c)]\n")
        self.assertIn(ROAD_FINDER, got["roads"])
        self.assertEqual([t["field"] for t in got["touches"]], ["by_name"])

    def test_dynamic_import_road_carries_its_reads(self) -> None:
        """Без пятой дороги прибор не видел бы СВОИХ двух читателей — тех,
        чьё решение и есть предмет заказа."""
        got = self._touches(
            "import importlib\n"
            "MOD = 'spa_core.monitoring.census_consumer_census'\n"
            "n = importlib.import_module(MOD)\n"
            "rows = [r for r in z if n.find_cli_consumers(root, c)]\n")
        self.assertIn(ROAD_DYNAMIC, got["roads"])
        self.assertEqual([t["field"] for t in got["touches"]], ["cli"])

    def test_renderer_import_alone_is_a_road(self) -> None:
        got = self._touches(
            "from spa_core.monitoring.census_consumer_census import "
            "format_report as fr\n")
        self.assertIn(ROAD_RENDERER, got["roads"])

    def test_artifact_filename_is_a_road(self) -> None:
        got = self._touches("NAME = 'census_consumer_census.json'\n")
        self.assertIn(ROAD_ARTIFACT, got["roads"])

    def test_a_file_touching_nothing_has_no_road(self) -> None:
        self.assertEqual(self._touches("import json\nx = json\n")["roads"], [])

    def test_doc_read_names_the_last_applied_key_and_marks_the_verdict(self) -> None:
        got = self._touches(
            "from spa_core.monitoring import census_consumer_census as n\n"
            "doc = n.run(root=root)\n"
            "print(doc['counts']['critical'])\n")
        self.assertIn(ROAD_RUN, got["roads"])
        self.assertEqual([(t["field"], t["form"]) for t in got["touches"]],
                         [("critical", TOUCH_PRINTS)])

    def test_the_inner_link_of_a_subscript_chain_is_not_a_second_read(self) -> None:
        """Считать `counts` вторым чтением значило бы приписать читателю
        контейнер вместе с каждым его элементом."""
        got = self._touches(
            "from spa_core.monitoring import census_consumer_census as n\n"
            "doc = n.run(root=root)\n"
            "print(doc['counts']['critical'])\n")
        self.assertNotIn("counts", [t["field"] for t in got["touches"]])

    def test_channel_of_a_test_file_is_counted_separately(self) -> None:
        got = self._touches(
            "from spa_core.monitoring import census_consumer_census as n\n"
            "assert n.find_fleet_consumers(root, c)\n",
            rel="spa_core/tests/test_x.py")
        self.assertEqual(got["channel"], "test")


class HarmOnAStandTests(unittest.TestCase):
    """Вся координата на одноразовом дереве, с обеими сторонами каждого ответа."""

    def setUp(self) -> None:
        self.stand = Stand()
        self.addCleanup(self.stand.close)
        self.stand.write(
            "spa_core/monitoring/bridge.py",
            "from spa_core.monitoring import census_consumer_census\n"
            "def step(root):\n"
            "    doc = census_consumer_census.run(root=root)\n"
            "    print(doc['counts']['critical'])\n")
        self.stand.write(
            "tests/test_pop.py",
            "from spa_core.monitoring import census_consumer_census as n\n"
            "class T:\n"
            "    def test_it(self, root=None):\n"
            "        doc = n.measure(root)\n"
            "        files = {s['file'] for s in doc['consumers']['by_name']}\n"
            "        self.assertIn('x', files)\n")
        self.sites = [{"census": "census_consumer_census",
                       "file": "spa_core/monitoring/bridge.py"}]

    def _harm(self, sites=None, registry=None) -> dict:
        return neighbour_population_harm(
            self.stand.root, _scale(self.sites if sites is None else sites),
            registry)

    def test_the_verdict_of_the_neighbour_does_not_move(self) -> None:
        harm = self._harm()
        self.assertEqual(harm["status"], "MEASURED")
        self.assertEqual(harm["verdict_fields_moved"], [])
        self.assertIn("understatement_moves_no_verdict",
                      [f["kind"] for f in harm["findings"]])

    def test_the_population_field_DOES_move(self) -> None:
        """Обратная сторона предыдущего: если бы не сдвинулось НИЧЕГО, ответ
        «вердикт не сдвинулся» был бы вырожденным."""
        harm = self._harm()
        self.assertIn("consumers.by_name", harm["moved_fields"])
        self.assertGreater(harm["counts"]["doc_fields_moved"], 0)

    def test_a_neighbour_whose_verdict_DERIVES_from_the_population_is_named(self) -> None:
        """Контроль на обратное состояние: прибор обязан ЗАГОВОРИТЬ, когда
        вердикт соседа действительно стои́т на населении."""
        real = neighbour.measure

        def derived(root):
            rows = neighbour.find_by_name_consumers(
                root, neighbour.find_callees(root))
            return {"status": f"S{len(rows)}", "overall": f"S{len(rows)}",
                    "counts": {"critical": len(rows), "warn": 0,
                               "unchecked": 0},
                    "findings": []}

        neighbour.measure = derived
        try:
            harm = self._harm()
        finally:
            neighbour.measure = real
        self.assertIn("status", harm["verdict_fields_moved"])
        self.assertNotIn("understatement_moves_no_verdict",
                         [f["kind"] for f in harm["findings"]])

    def test_a_reader_deciding_on_the_moved_field_is_named(self) -> None:
        harm = self._harm()
        named = [f["file"] for f in harm["findings"]
                 if f["kind"] == "reader_decides_on_moved_field"]
        self.assertIn("tests/test_pop.py", named)

    def test_a_reader_deciding_on_an_UNMOVED_field_is_NOT_named(self) -> None:
        """Обратная сторона ответа: решение по полю, которое НЕ сдвинулось,
        измениться не может, и назвать такого читателя значило бы выдать
        «решает» за «решает иначе» (выжившая мутация батареи)."""
        self.stand.write(
            "spa_core/monitoring/verdict_reader.py",
            "from spa_core.monitoring import census_consumer_census as n\n"
            "def step(root):\n"
            "    doc = n.measure(root)\n"
            "    assert doc['counts']['critical'] == 0\n")
        harm = self._harm()
        named = [f["file"] for f in harm["findings"]
                 if f["kind"] == "reader_decides_on_moved_field"]
        self.assertNotIn("spa_core/monitoring/verdict_reader.py", named)
        # контроль контроля: читатель НАЙДЕН и его чтение признано решением,
        # иначе тест был бы зелен по построению
        reader = next(r for r in harm["readers"]
                      if r["file"] == "spa_core/monitoring/verdict_reader.py")
        self.assertEqual([(t["field"], t["form"]) for t in reader["touches"]],
                         [("critical", TOUCH_DECIDES)])

    def test_a_reader_only_printing_the_verdict_is_NOT_named(self) -> None:
        """Обратная сторона: печать не есть решение, и объявить её решением
        значило бы выдать сдвиг ЧИСЛА В ОТЧЁТЕ за сдвиг вывода."""
        harm = self._harm()
        named = [f["file"] for f in harm["findings"]
                 if f["kind"] == "reader_decides_on_moved_field"]
        self.assertNotIn("spa_core/monitoring/bridge.py", named)

    def test_the_unpaid_reader_is_a_THIRD_outcome_with_a_price(self) -> None:
        harm = self._harm()
        unpaid = [e for e in harm["executed"]
                  if e["outcome"] == DECISION_NOT_EXECUTED]
        self.assertEqual(len(unpaid), 1)
        self.assertEqual(unpaid[0]["key"], "invisible_consumer_scale")
        self.assertEqual(unpaid[0]["field"], "blanked_to_zero")
        self.assertGreater(unpaid[0]["cost_s"], 0)
        self.assertIn("ОСТАТОК", unpaid[0]["reason"])

    def test_the_executed_reader_carries_both_projections(self) -> None:
        harm = self._harm()
        executed = [e for e in harm["executed"]
                    if e["outcome"] in (DECISION_CHANGED, DECISION_UNCHANGED)]
        self.assertEqual(len(executed), 1)
        self.assertIn("before", executed[0])
        self.assertIn("after", executed[0])

    def test_a_widening_that_lands_on_a_declared_reader_CHANGES_the_decision(self) -> None:
        """Положительный контроль исхода: место ввоза, попадающее на
        объявленного реестром читателя, меняет его вывод — и прибор говорит
        CRITICAL, а не «в отчёте сдвинулось число»."""
        self.stand.write(
            OFFICE_REL,
            "from spa_core.monitoring.rule_second_copy_census import report\n"
            "def show(doc):\n"
            "    print('\\n'.join(report(doc)))\n")
        harm = self._harm(sites=[{"census": "rule_second_copy_census",
                                  "file": OFFICE_REL}])
        changed = [e for e in harm["executed"]
                   if e["outcome"] == DECISION_CHANGED]
        self.assertEqual([e["key"] for e in changed],
                         ["consumer_registry_completeness"])
        self.assertEqual(harm["status"], "CRITICAL")
        self.assertIn("reader_decision_changed",
                      [f["kind"] for f in harm["findings"]])

    def test_the_same_widening_elsewhere_leaves_the_decision_alone(self) -> None:
        """Обратная сторона: та же форма расширения, но мимо объявленного
        читателя, вывода не меняет — иначе контроль выше был бы истинным ПО
        ПОСТРОЕНИЮ."""
        harm = self._harm(sites=[{"census": "rule_second_copy_census",
                                  "file": "spa_core/monitoring/bridge.py"}])
        self.assertEqual([e["outcome"] for e in harm["executed"]
                          if e["key"] == "consumer_registry_completeness"],
                         [DECISION_UNCHANGED])
        self.assertEqual(harm["status"], "MEASURED")

    def test_shape_sensitivity_is_a_number_and_it_is_zero_here(self) -> None:
        harm = self._harm()
        self.assertEqual(harm["counts"]["shape_sensitive_sites"], 0)
        self.assertEqual(harm["shape_sensitive_sites"], [])

    def test_a_spec_WITHOUT_a_scope_is_not_shape_sensitive(self) -> None:
        """Область — весь смысл этого счётчика: место, попавшее на запись БЕЗ
        объявленной области, разрешается путём, и строка там ни при чём
        (выжившая мутация батареи сняла именно фильтр по области)."""
        unscoped = next(spec["path"] for spec in CENSUS_CONSUMERS
                        if not spec.get("scope"))
        harm = self._harm(sites=[{"census": "census_consumer_census",
                                  "file": unscoped}])
        self.assertEqual(harm["shape_sensitive_sites"], [])

    def test_shape_sensitivity_speaks_when_a_scoped_spec_matches(self) -> None:
        """Обратная сторона: ветка «форма способна изменить ответ» достижима,
        и молчание прибора есть замер, а не отсутствие ветки."""
        scoped = next(spec["path"] for spec in CENSUS_CONSUMERS
                      if spec.get("scope"))
        harm = self._harm(sites=[{"census": "census_consumer_census",
                                  "file": scoped}])
        self.assertEqual(harm["shape_sensitive_sites"], [scoped])

    def test_the_declared_verdict_fields_are_not_chosen_after_the_fact(self) -> None:
        """Запрет G62: список полей вердикта объявлен константой модуля, и
        замер обязан печатать ИМЕННО его."""
        harm = self._harm()
        self.assertEqual(harm["verdict_fields_declared"],
                         list(NEIGHBOUR_VERDICT_FIELDS))
        self.assertEqual(harm["counts"]["verdict_fields_declared"],
                         len(NEIGHBOUR_VERDICT_FIELDS))


class ThirdOutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stand = Stand()
        self.addCleanup(self.stand.close)

    def test_scale_unmeasured_is_not_no_harm(self) -> None:
        """Перечень мест НА МЕСТЕ намеренно: без него отказ давал бы ВТОРОЙ
        сторож, причина совпадала бы подстрокой, и снятие первого прошло бы
        незамеченным (выжившая мутация батареи)."""
        got = neighbour_population_harm(
            self.stand.root,
            {"status": "UNMEASURED", "reason": "x", "sites": []}, None)
        self.assertEqual(got["status"], "UNMEASURED")
        self.assertIn("масштаб невидимости не измерен", got["reason"])
        self.assertIn("НЕ «вреда нет»", got["reason"])

    def test_scale_without_a_site_list_is_unmeasured(self) -> None:
        got = neighbour_population_harm(self.stand.root,
                                        {"status": "CRITICAL"}, None)
        self.assertEqual(got["status"], "UNMEASURED")
        self.assertIn("перечня мест", got["reason"])

    def test_a_missing_neighbour_name_is_unmeasured_and_names_it(self) -> None:
        real = neighbour.OUTPUT_FILENAME
        del neighbour.OUTPUT_FILENAME
        try:
            got = neighbour_population_harm(self.stand.root, _scale([]), None)
        finally:
            neighbour.OUTPUT_FILENAME = real
        self.assertEqual(got["status"], "UNMEASURED")
        self.assertIn("OUTPUT_FILENAME", got["reason"])

    def test_the_neighbour_is_restored_even_when_its_measure_raises(self) -> None:
        """Проба подменяет соседа на время двух прогонов. Не вернуть его
        значило бы сломать КАЖДОГО последующего читателя в том же процессе."""
        real_measure = neighbour.measure
        real_callees = neighbour.find_callees
        real_by_name = neighbour.find_by_name_consumers

        def boom(root):
            raise RuntimeError("стенд")

        neighbour.measure = boom
        try:
            with self.assertRaises(RuntimeError):
                neighbour_population_harm(self.stand.root, _scale([]), None)
        finally:
            neighbour.measure = real_measure
        self.assertIs(neighbour.find_callees, real_callees)
        self.assertIs(neighbour.find_by_name_consumers, real_by_name)


class DecisionProjectionTests(unittest.TestCase):
    def test_a_document_without_counts_is_not_a_document_with_empty_counts(self) -> None:
        """Инв. #17: `doc.get("counts") or {}` приравнивало ДВА РАЗНЫХ решения —
        «счётчиков нет» и «счётчики пусты». Сторож класса поймал это на
        доставке, и форма чинилась у ПИСАТЕЛЯ, а не в базе сторожа."""
        absent = _decision_projection({"status": "MEASURED"})
        empty = _decision_projection({"status": "MEASURED", "counts": {},
                                      "findings": [], "declared_unseen": []})
        self.assertNotEqual(absent, empty)
        self.assertFalse(absent["counts_observed"])
        self.assertTrue(empty["counts_observed"])
        self.assertIsNone(absent["finding_kinds"])
        self.assertEqual(empty["finding_kinds"], [])

    def test_a_changed_finding_kind_is_a_changed_decision(self) -> None:
        one = _decision_projection({"status": "MEASURED", "counts": {},
                                    "findings": [{"kind": "a"}],
                                    "declared_unseen": []})
        two = _decision_projection({"status": "MEASURED", "counts": {},
                                    "findings": [{"kind": "b"}],
                                    "declared_unseen": []})
        self.assertNotEqual(one, two)

    def test_a_changed_site_count_is_NOT_a_changed_decision(self) -> None:
        """Сверять документ целиком значило бы объявлять решение изменившимся
        всякий раз, когда в отчёте сдвинулось число мест."""
        one = _decision_projection({"status": "MEASURED",
                                    "counts": {"sites": 26}, "findings": [],
                                    "declared_unseen": []})
        two = _decision_projection({"status": "MEASURED",
                                    "counts": {"sites": 35}, "findings": [],
                                    "declared_unseen": []})
        self.assertEqual(one, two)


class WiringTests(unittest.TestCase):
    """Проводка меряется ФОРМОЙ ЗОВА, а не наличием имени в файле."""

    def setUp(self) -> None:
        self.source = Path(rscc.__file__).read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_measure_calls_the_coordinate_and_carries_it_under_its_key(self) -> None:
        measure = next(n for n in self.tree.body
                       if isinstance(n, ast.FunctionDef) and n.name == "measure")
        bound = set()
        for node in ast.walk(measure):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "neighbour_population_harm"):
                bound |= {t.id for t in node.targets
                          if isinstance(t, ast.Name)}
        self.assertTrue(bound, "measure() не зовёт neighbour_population_harm()")
        carried = {}
        for node in ast.walk(measure):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (isinstance(key, ast.Constant)
                            and isinstance(value, ast.Name)):
                        carried[key.value] = value.id
        self.assertIn("neighbour_population_harm", carried)
        self.assertIn(carried["neighbour_population_harm"], bound)

    def test_the_clean_run_of_the_registry_reader_is_handed_in_not_recomputed(self) -> None:
        """Второй прогон читателя стоил бы 21 с ни за что: чистый результат
        уже посчитан выше в `measure`, и он обязан ПЕРЕДАВАТЬСЯ."""
        measure = next(n for n in self.tree.body
                       if isinstance(n, ast.FunctionDef) and n.name == "measure")
        call = next(node for node in ast.walk(measure)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "neighbour_population_harm")
        self.assertEqual(len(call.args), 3, "координата зовётся не тремя входами")
        self.assertEqual([a.id for a in call.args[1:]
                          if isinstance(a, ast.Name)],
                         ["invisible_scale", "registry_completeness"])


class ReportTests(unittest.TestCase):
    def _lines(self, harm) -> list:
        return report({"status": "CLEAN", "rows": [], "classified": 0,
                       "neighbour_population_harm": harm})

    def test_the_section_prints_the_answer(self) -> None:
        lines = self._lines({
            "status": "MEASURED",
            "counts": {"doc_fields": 116, "doc_fields_moved": 4,
                       "verdict_fields_declared": 5, "verdict_fields_moved": 0,
                       "widened_by": 51, "readers": 4, "readers_by_road": {},
                       "touches": 20, "touches_deciding": 5,
                       "touches_printing": 5, "touches_unresolved": 10,
                       "readers_deciding_on_moved": 1,
                       "readers_decision_changed": 0,
                       "readers_decision_unchanged": 1,
                       "readers_not_executed": 1,
                       "shape_sensitive_sites": 0, "files_unreadable": 0},
            "moved_fields": ["consumers.by_name"],
            "verdict_fields_moved": [], "executed": [], "findings": [],
            "blind": []})
        joined = "\n".join(lines)
        self.assertIn("[ВРЕД ЗАНИЖЕНИЯ]", joined)
        self.assertIn("решение измениться НЕ МОЖЕТ", joined)
        self.assertIn("ответ от формы НЕ зависит", joined)

    def test_unmeasured_prints_the_reason(self) -> None:
        joined = "\n".join(self._lines({"status": "UNMEASURED",
                                        "reason": "соседа нет"}))
        self.assertIn("НЕ ИЗМЕРЕН: соседа нет", joined)

    def test_a_document_without_counts_is_NOT_zero_counts(self) -> None:
        """Инв. #17 и регрессия #664: «счётчиков нет» и «счётчики нулевые» —
        разные утверждения, и второе вместо первого есть fail-OPEN."""
        joined = "\n".join(self._lines({"status": "MEASURED"}))
        self.assertIn("НЕ нулевые счётчики", joined)

    def test_a_missing_coordinate_is_named_not_skipped(self) -> None:
        joined = "\n".join(report({"status": "CLEAN", "rows": [],
                                   "classified": 0}))
        self.assertIn("[ВРЕД ЗАНИЖЕНИЯ] НЕ ИЗМЕРЕН", joined)


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
