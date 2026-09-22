"""Хвост координаты — не имя поля, и разница между ними есть ЧИСЛО.

Заказ G71 п. 2 (ADR-448 → ADR-449). Население ``decides_on_moved`` у шага
:func:`neighbour_population_harm` объявляется сверкой ХВОСТА координаты
читателя с хвостами сдвинувшихся полей документа соседа. Хвост именем поля не
является: в одном документе соседа живут и ``callees``, и ``counts.callees``.
До этого заказа слепота была названа ПРОЗОЙ в ``blind`` — и ровно про такой
случай написана память «названо в прозе не значит починено: мерить надо у
потребителя».

Каждый тест ниже — положительный контроль: сцена, в которой правило по хвосту
и правило по полному пути дают РАЗНЫЙ ответ, и разница обязана доехать до
документа отдельными числами, а не слиться в одно.
"""

import ast
import unittest
from pathlib import Path

from spa_core.monitoring import rule_second_copy_census as C

ROOT = Path(__file__).resolve().parents[2]
NEIGHBOUR_SRC = ROOT / "spa_core" / "monitoring" / "census_consumer_census.py"


def _expr(text: str) -> ast.AST:
    """Единственное выражение модуля — как узел."""
    return ast.parse(text).body[0].value


class CoordinatePathTests(unittest.TestCase):
    """Разборщик полного пути: что он умеет и где честно молчит."""

    ANCHORS = {"doc"}

    def _path(self, text, consts=None):
        return C._coordinate_path(_expr(text), consts or {}, self.ANCHORS)

    def test_subscript_chain_gives_the_full_path_not_the_tail(self):
        """`doc["consumers"]["by_name"]` — это `consumers.by_name`."""
        path, outcome = self._path('doc["consumers"]["by_name"]')
        self.assertEqual(path, "consumers.by_name")
        self.assertEqual(outcome, C.PATH_FROM_ANCHOR)

    def test_the_two_rules_disagree_on_the_same_node(self):
        """Обратная сторона: терминальная координата даёт ХВОСТ.

        Если бы оба правила отвечали одинаково, весь заказ был бы пуст —
        поэтому расхождение проверяется на ОДНОМ узле, а не на двух сценах.
        """
        node = _expr('doc["counts"]["callees"]')
        self.assertEqual(C._terminal_coordinate(node, {}, {"doc": None}),
                         "callees")
        self.assertEqual(C._coordinate_path(node, {}, self.ANCHORS)[0],
                         "counts.callees")

    def test_get_chain_is_walked_to_the_anchor(self):
        path, outcome = self._path('doc.get("counts", {}).get("critical")')
        self.assertEqual(path, "counts.critical")
        self.assertEqual(outcome, C.PATH_FROM_ANCHOR)

    def test_observed_form_is_walked_to_the_anchor(self):
        path, outcome = self._path('observed(doc, "counts", kind=dict)')
        self.assertEqual(path, "counts")
        self.assertEqual(outcome, C.PATH_FROM_ANCHOR)

    def test_transparent_wrapper_does_not_add_a_key(self):
        """`len(...)` имя числа не меняет — и пути не удлиняет."""
        self.assertEqual(self._path('len(doc["callees"])')[0], "callees")

    def test_string_constant_key_is_resolved_through_consts(self):
        path, _ = self._path('doc[KEY]', consts={"KEY": "counts"})
        self.assertEqual(path, "counts")

    # --- третий исход: НЕ ноль и НЕ «поле не сдвинулось» -----------------

    def test_foreign_name_is_a_third_outcome_not_a_path(self):
        """`row["file"]` внутри обхода: якоря под ним нет."""
        path, outcome = self._path('row["file"]')
        self.assertIsNone(path)
        self.assertEqual(outcome, C.PATH_BOUND_NAME)

    def test_non_literal_key_is_a_third_outcome(self):
        path, outcome = self._path('doc[key]')
        self.assertIsNone(path)
        self.assertEqual(outcome, C.PATH_NON_LITERAL)

    def test_bare_anchor_is_not_a_read(self):
        path, outcome = self._path('doc')
        self.assertIsNone(path)
        self.assertEqual(outcome, C.PATH_NOT_A_READ)

    def test_depth_limit_is_a_third_outcome_not_a_crash(self):
        node = _expr('doc["a"]')
        path, outcome = C._coordinate_path(
            node, {}, self.ANCHORS, depth=C._TERNARY_NESTING_LIMIT + 1)
        self.assertIsNone(path)
        self.assertEqual(outcome, C.PATH_DEPTH)


class FinderDeclarationTests(unittest.TestCase):
    """Путь искателя ОБЪЯВЛЕН — и объявление сверяется с документом соседа."""

    def test_every_finder_declares_both_tail_and_path(self):
        self.assertEqual(set(C._FINDER_FIELD), set(C._FINDER_FIELD_PATH))

    def test_declared_path_ends_with_the_declared_tail(self):
        for name, tail in C._FINDER_FIELD.items():
            self.assertEqual(C._FINDER_FIELD_PATH[name].rsplit(".", 1)[-1],
                             tail, name)

    def test_declared_path_exists_in_the_neighbours_document(self):
        """Объявление, не сверенное с предметом, — вторая копия правила.

        Читается ЛИТЕРАЛ документа соседа (`doc = {...}`), а не его прогон:
        вопрос здесь про ФОРМУ документа, и платить за прогон соседа минуту,
        чтобы узнать имена ключей, значило бы мерить не то.
        """
        tree = ast.parse(NEIGHBOUR_SRC.read_text(encoding="utf-8"))
        literal = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "doc"
                    and isinstance(node.value, ast.Dict)):
                literal = node.value
        self.assertIsNotNone(
            literal, "у соседа не найден литерал документа — сверить объявление "
                     "не с чем; это НЕ «объявление верно»")
        shape = {}
        for key, value in zip(literal.keys, literal.values):
            if not isinstance(key, ast.Constant):
                continue
            inner = set()
            if isinstance(value, ast.Dict):
                inner = {k.value for k in value.keys
                         if isinstance(k, ast.Constant)}
            shape[key.value] = inner
        for name, path in C._FINDER_FIELD_PATH.items():
            head, _, tail = path.partition(".")
            self.assertIn(head, shape, f"{name}: у соседа нет ключа {head}")
            self.assertIn(tail, shape[head], f"{name}: у соседа нет {path}")


def _reader(file, touches):
    return {"file": file, "channel": "code", "roads": ["x"], "touches": touches}


def _touch(field, path, outcome, *, tail_moved, path_moved,
           form=None, line=1):
    form = C.TOUCH_DECIDES if form is None else form
    return {"road": "r", "line": line, "field": field, "field_path": path,
            "field_path_outcome": outcome, "form": form,
            "could_change": bool(form == C.TOUCH_DECIDES and tail_moved),
            "could_change_by_path": bool(form == C.TOUCH_DECIDES
                                         and path_moved)}


class CoordinateScopeTests(unittest.TestCase):
    """Два населения, их разность и запрет сливать разность с неизмеренным."""

    FLAT = {"status": "'OK'", "callees": "{}", "counts.callees": "3",
            "counts.critical": "0", "consumers.by_name": "[]"}

    def test_tail_admits_a_reader_of_a_field_that_did_not_move(self):
        """Сдвинулся `counts.callees`; читатель решает по `callees`."""
        readers = [_reader("a.py", [_touch("callees", "callees",
                                           C.PATH_FROM_ANCHOR,
                                           tail_moved=True, path_moved=False)])]
        scope = C._coordinate_scope(self.FLAT, ["counts.callees"], readers)
        self.assertEqual(scope["readers_by_tail"], 1)
        self.assertEqual(scope["readers_by_path"], 0)
        self.assertFalse(scope["sets_coincide"])
        self.assertEqual(scope["files_only_by_tail"], ["a.py"])
        self.assertEqual(len(scope["touches_admitted_by_tail_only"]), 1)
        self.assertEqual(scope["deciding_admitted_by_tail_path_unmeasured"], [])

    def test_reverse_side_sets_coincide_when_the_path_itself_moved(self):
        """Обратная сторона: правило не кричит там, где расхождения нет."""
        readers = [_reader("a.py", [_touch("callees", "counts.callees",
                                           C.PATH_FROM_ANCHOR,
                                           tail_moved=True, path_moved=True)])]
        scope = C._coordinate_scope(self.FLAT, ["counts.callees"], readers)
        self.assertEqual((scope["readers_by_tail"], scope["readers_by_path"]),
                         (1, 1))
        self.assertTrue(scope["sets_coincide"])
        self.assertEqual(scope["touches_admitted_by_tail_only"], [])

    def test_unresolved_path_is_not_counted_as_a_surplus_reader(self):
        """Инв. #17: «лишний» и «не измерено» — два разных утверждения."""
        readers = [_reader("a.py", [_touch("file", None, C.PATH_BOUND_NAME,
                                           tail_moved=True, path_moved=False)])]
        scope = C._coordinate_scope(self.FLAT, ["consumers.by_name"], readers)
        self.assertEqual(scope["touches_admitted_by_tail_only"], [],
                         "неизмеренный путь выдан за доказанно лишний")
        self.assertEqual(
            len(scope["deciding_admitted_by_tail_path_unmeasured"]), 1)
        self.assertEqual(scope["readers_by_tail"], 1)
        self.assertEqual(scope["readers_by_path"], 0)

    def test_printing_touch_is_in_neither_population(self):
        readers = [_reader("a.py", [_touch("callees", "counts.callees",
                                           C.PATH_FROM_ANCHOR,
                                           tail_moved=True, path_moved=True,
                                           form=C.TOUCH_PRINTS)])]
        scope = C._coordinate_scope(self.FLAT, ["counts.callees"], readers)
        self.assertEqual((scope["readers_by_tail"], scope["readers_by_path"]),
                         (0, 0))

    def test_path_only_counter_is_not_an_ornament(self):
        """Счётчик, который не умеет сказать «единица», нулём не доказывает.

        Сцена невозможна для разобранного пути — и именно поэтому счётчик
        обязан быть проверен: иначе его ноль в живом замере был бы украшением.
        """
        readers = [_reader("a.py", [_touch("x", "y.x", C.PATH_FROM_ANCHOR,
                                           tail_moved=False, path_moved=True)])]
        scope = C._coordinate_scope(self.FLAT, ["y.x"], readers)
        self.assertEqual(len(scope["touches_admitted_by_path_only"]), 1)
        self.assertEqual(scope["files_only_by_path"], ["a.py"])

    def test_ambiguous_tails_are_counted_over_the_whole_document(self):
        """Многозначность — свойство ДОКУМЕНТА, а не только разности."""
        scope = C._coordinate_scope(self.FLAT, [], [])
        self.assertIn("callees", scope["ambiguous_tails"])
        self.assertEqual(scope["ambiguous_tails"]["callees"],
                         ["callees", "counts.callees"])
        self.assertEqual(scope["ambiguous_tails_total"], 1)
        self.assertEqual(scope["ambiguous_tails_among_moved"], [])

    def test_ambiguous_tail_among_moved_is_reported_separately(self):
        scope = C._coordinate_scope(self.FLAT, ["counts.callees"], [])
        self.assertEqual(scope["ambiguous_tails_among_moved"], ["callees"])

    def test_path_outcomes_are_tallied_for_every_touch(self):
        readers = [_reader("a.py", [
            _touch("callees", "counts.callees", C.PATH_FROM_ANCHOR,
                   tail_moved=True, path_moved=True),
            _touch("file", None, C.PATH_BOUND_NAME,
                   tail_moved=False, path_moved=False)])]
        scope = C._coordinate_scope(self.FLAT, ["counts.callees"], readers)
        self.assertEqual(scope["path_outcomes"],
                         {C.PATH_FROM_ANCHOR: 1, C.PATH_BOUND_NAME: 1})


class ReaderTouchWiringTests(unittest.TestCase):
    """Путь доезжает до чтения ПО ФОРМЕ ЗОВА, а не по совпадению подстроки."""

    SOURCE = (
        "from spa_core.monitoring import census_consumer_census\n"
        "doc = census_consumer_census.measure(root)\n"
        "if doc['counts']['critical']:\n"
        "    print(doc['counts']['critical'])\n"
        "for row in doc['consumers']['by_name']:\n"
        "    if row['file']:\n"
        "        print(row['file'])\n")

    def _touches(self):
        tree = ast.parse(self.SOURCE)
        item = C._reader_touches("x.py", tree, C.NEIGHBOUR_CENSUS,
                                 "census_consumers.json", ())
        return item["touches"]

    def test_every_touch_carries_a_path_key(self):
        touches = self._touches()
        self.assertTrue(touches, "сцена не дала ни одного чтения")
        for touch in touches:
            self.assertIn("field_path", touch)
            self.assertIn("field_path_outcome", touch)

    def test_the_deciding_touch_resolves_to_the_full_path(self):
        paths = {t["field_path"] for t in self._touches()}
        self.assertIn("counts.critical", paths)
        self.assertIn("consumers.by_name", paths)

    def test_a_read_straight_off_the_producer_call_resolves(self):
        """`ccc.measure(t)["counts"]` — документ рождается зовом, и он якорь.

        Форма взята не из головы: замер #673 нашёл ровно её у двух РЕШАЮЩИХ
        чтений `test_census_consumer_census.py`, и до правки прибор объявлял
        их путь неизмеримым — то есть занижал собственную измеримость.
        """
        # Якорь в сцене обязан быть: цикл чтений у читателя БЕЗ единого
        # присваивания документа не запускается вовсе, и без этой строки
        # тест зеленел бы по пустоте, ничего не проверив.
        source = ("from spa_core.monitoring import census_consumer_census "
                  "as ccc\n"
                  "doc = ccc.measure(tree)\n"
                  "if ccc.measure(tree)['counts']:\n"
                  "    pass\n")
        item = C._reader_touches("x.py", ast.parse(source), C.NEIGHBOUR_CENSUS,
                                 "census_consumers.json", ())
        rows = [t for t in item["touches"] if t["field"] == "counts"]
        self.assertEqual(len(rows), 1, "сцена не дала чтения `counts`")
        self.assertEqual(rows[0]["field_path"], "counts")
        self.assertEqual(rows[0]["field_path_outcome"], C.PATH_FROM_ANCHOR)

    def test_a_foreign_call_under_the_chain_stays_a_third_outcome(self):
        """Обратная сторона: якорем становится ЗОВ ПРОИЗВОДИТЕЛЯ, не любой.

        Без этой стороны предыдущая ветка объявляла бы документом всё, до
        чего дотянется цепь, — и путь выдумывался бы там, где его нет.
        """
        path, outcome = C._coordinate_path(
            _expr('other.measure(tree)["counts"]'), {}, {"doc"},
            makers=frozenset({"ccc"}))
        self.assertIsNone(path)
        self.assertEqual(outcome, C.PATH_BOUND_NAME)


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
