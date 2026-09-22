"""Счёт хвостов — свойство ПРАВИЛА уплощения, а не только документа.

Заказ G72 п. 2 (ADR-449 → ADR-450). Цикл #673 объяснил свой ноль числом:
«хвостов у документа соседа 115, многозначен ровно один». Число это снято
правилом :func:`rule_second_copy_census._flatten_doc`, которое разворачивает
словари и НЕ разворачивает списки, — то есть всё, что живёт внутри элементов
списка, в счёт не вошло вовсе. Ровно та же форма дефекта, что ищет сама
перепись: величина, объявленная свойством предмета, оказывается свойством
прибора.

Каждый тест ниже — положительный контроль: сцена, в которой два правила
уплощения дают РАЗНЫЙ ответ, и разница обязана доехать отдельными числами, а
не слиться в одно.
"""

import ast
import unittest
from pathlib import Path

from spa_core.monitoring import rule_second_copy_census as C

ROOT = Path(__file__).resolve().parents[2]
PRODUCER_SRC = ROOT / "spa_core" / "monitoring" / "rule_second_copy_census.py"


class NameTailTests(unittest.TestCase):
    """Индекс элемента списка именем поля не является."""

    def test_index_is_stripped_and_the_field_name_survives(self):
        self.assertEqual(C._name_tail("findings[0].file"), "file")

    def test_scalar_element_keeps_the_name_of_its_list(self):
        """`findings[0]` читателю доступен только как `findings`."""
        self.assertEqual(C._name_tail("findings[0]"), "findings")

    def test_nested_indices_are_all_stripped(self):
        self.assertEqual(C._name_tail("rows[0][12]"), "rows")

    def test_a_path_without_indices_is_the_old_rule_verbatim(self):
        """На путях старого правила обе формы обязаны совпадать.

        Иначе «правило не переписано» было бы обещанием, а не проверкой.
        """
        for path in ("status", "counts.callees", "consumers.by_name"):
            self.assertEqual(C._name_tail(path), path.rsplit(".", 1)[-1])


class DeepFlattenTests(unittest.TestCase):
    """Второе правило: что оно видит, что теряет и где честно молчит."""

    DOC = {"status": "OK",
           "counts": {"critical": 1},
           "findings": [{"kind": "a", "file": "x.py"},
                        {"kind": "b", "file": "y.py"}]}

    def test_the_two_rules_disagree_on_the_same_document(self):
        """Если бы они отвечали одинаково, весь заказ был бы пуст."""
        shallow = C._flatten_doc(self.DOC)
        deep, _ = C._flatten_doc_deep(self.DOC)
        self.assertIn("findings", shallow)
        self.assertNotIn("findings", deep)
        self.assertIn("findings[0].file", deep)
        self.assertNotIn("findings[0].file", shallow)

    def test_the_deep_rule_sees_names_the_old_one_never_counted(self):
        deep, _ = C._flatten_doc_deep(self.DOC)
        tails = {C._name_tail(key) for key in deep}
        shallow_tails = {C._name_tail(key) for key in C._flatten_doc(self.DOC)}
        self.assertIn("file", tails)
        self.assertNotIn("file", shallow_tails)

    def test_an_empty_list_is_named_and_not_swallowed(self):
        deep, _ = C._flatten_doc_deep({"findings": []})
        self.assertEqual(deep, {"findings": "[]"})

    def test_an_empty_dict_is_named_and_not_swallowed(self):
        deep, _ = C._flatten_doc_deep({"counts": {}})
        self.assertEqual(deep, {"counts": "{}"})

    def test_depth_limit_is_a_third_outcome_not_a_value(self):
        """Предел не растворяется в карте: «не разобрано» ≠ «значение».

        Инв. #17: путь, упершийся в предел, обязан быть НАЗВАН отдельно, а не
        подставлен значением и не потерян молча.
        """
        doc = value = {}
        for _ in range(C.DEEP_FLATTEN_MAX_DEPTH + 3):
            nxt = {}
            value["deeper"] = nxt
            value = nxt
        value["leaf"] = 1
        deep, capped = C._flatten_doc_deep(doc)
        self.assertTrue(capped, "предел глубины не назван ни одним путём")
        for path in capped:
            self.assertNotIn(path, deep,
                             "упершийся в предел путь выдан за значение")

    def test_a_shallow_document_never_reaches_the_limit(self):
        """Обратная сторона: предел не срабатывает там, где его нет."""
        _, capped = C._flatten_doc_deep(self.DOC)
        self.assertEqual(capped, [])


class ListCensusTests(unittest.TestCase):
    """Сколько было чего разворачивать — иначе ноль читается как свойство."""

    def test_counts_lists_and_their_elements_including_nested(self):
        lists, elements = C._list_census(
            {"a": [1, 2, 3], "b": {"c": [{"d": [4]}]}})
        self.assertEqual((lists, elements), (3, 5))

    def test_a_document_without_lists_answers_zero(self):
        self.assertEqual(C._list_census({"a": {"b": 1}}), (0, 0))


def _reader(file, touches):
    return {"file": file, "channel": "code", "roads": ["x"],
            "touches": touches}


def _touch(field, *, form=None, line=1):
    return {"road": "r", "line": line, "field": field, "field_path": None,
            "field_path_outcome": C.PATH_BOUND_NAME,
            "form": C.TOUCH_DECIDES if form is None else form}


class FlattenRuleScopeTests(unittest.TestCase):
    """Ответ заказа: чьим свойством оказалась многозначность хвостов."""

    # Хвост `file` многозначен ТОЛЬКО при развёртывании списков: в верхнем
    # уровне он один, внутри элементов — два.
    CLEAN = {"file": "top.py",
             "counts": {"critical": 0},
             "findings": [{"kind": "a", "file": "x.py"},
                          {"kind": "b", "file": "y.py"}]}

    def _scope(self, clean=None, widened=None, readers=()):
        clean = self.CLEAN if clean is None else clean
        widened = clean if widened is None else widened
        flat_clean = C._flatten_doc(clean)
        flat_widened = C._flatten_doc(widened)
        changed = sorted(key for key in set(flat_clean) | set(flat_widened)
                         if flat_clean.get(key) != flat_widened.get(key))
        return C._flatten_rule_scope(clean, widened, flat_clean, changed,
                                     list(readers))

    def test_ambiguity_is_named_a_property_of_the_rule_when_it_is(self):
        scope = self._scope()
        self.assertEqual(scope["verdict"], C.FLATTEN_RULE_DEPENDENT)
        self.assertEqual(scope["ambiguous_shallow"], 0)
        self.assertEqual(scope["ambiguous_deep"], 2)
        self.assertEqual(scope["ambiguous_only_deep"], ["file", "kind"])

    def test_the_reverse_side_a_document_whose_lists_add_no_ambiguity(self):
        """Счётчик, отвечающий одно и то же, ответом не является."""
        scope = self._scope(clean={"rows": [{"alpha": 1}, {"alpha": 2}],
                                   "beta": 3})
        self.assertEqual(scope["ambiguous_deep"], 1)   # alpha × 2 элемента
        scope = self._scope(clean={"rows": [{"alpha": 1}], "beta": 3})
        self.assertEqual(scope["ambiguous_deep"], 0)
        self.assertEqual(scope["verdict"], C.FLATTEN_DOC_PROPERTY)

    def test_no_lists_is_a_third_verdict_not_a_measured_zero(self):
        """Пустота ПО ПОСТРОЕНИЮ отличима от измеренного совпадения."""
        scope = self._scope(clean={"a": {"b": 1}, "c": 2})
        self.assertEqual(scope["verdict"], C.FLATTEN_NO_LISTS)
        self.assertEqual(scope["lists_in_doc"], 0)
        self.assertNotEqual(C.FLATTEN_NO_LISTS, C.FLATTEN_DOC_PROPERTY)

    def test_the_cost_of_the_deep_rule_is_named_not_hidden(self):
        """Развернув список, глубокое правило ТЕРЯЕТ имя самого списка.

        Молчать об этом значило бы выдать «точнее» за «строго больше».
        """
        scope = self._scope()
        self.assertIn("findings", scope["tails_only_shallow"])
        self.assertIn("kind", scope["tails_only_deep"])

    # --- вред у потребителя ------------------------------------------------

    def test_a_reader_of_a_list_element_field_is_invisible_to_the_old_rule(self):
        """Сдвинулся `findings[0].file`; читатель решает по `file`.

        Нынешнее население `decides_on_moved` такого читателя не видит: у
        старого правила сдвинулся ключ `findings`, и хвост у него `findings`.
        """
        widened = {"file": "top.py", "counts": {"critical": 0},
                   "findings": [{"kind": "a", "file": "ИНОЕ.py"},
                                {"kind": "b", "file": "y.py"}]}
        readers = [_reader("a.py", [_touch("file")])]
        scope = self._scope(widened=widened, readers=readers)
        # Хвост `file` есть и у старого правила (верхний уровень), но он НЕ
        # сдвинулся; сдвинулся он только внутри элемента списка. Потому
        # разница здесь — правила, а не наличия имени.
        self.assertEqual(len(scope["touches_admitted_by_deep_only"]), 1)
        self.assertEqual(scope["readers_admitted_by_deep"], 1)
        self.assertEqual(scope["readers_admitted_by_shallow"], 0)
        self.assertEqual(scope["files_only_by_deep"], ["a.py"])

    def test_containment_is_not_one_way_and_that_is_measured(self):
        """Обратный класс: имя самого списка видит только СТАРОЕ правило.

        Объявить глубокое правило «строго более допускающим» было бы
        рассуждением, а не замером, — и число говорит против него.
        """
        widened = {"file": "top.py", "counts": {"critical": 0},
                   "findings": [{"kind": "a", "file": "x.py"}]}
        readers = [_reader("b.py", [_touch("findings")])]
        scope = self._scope(widened=widened, readers=readers)
        self.assertEqual(len(scope["touches_admitted_by_shallow_only"]), 1)
        self.assertEqual(scope["touches_admitted_by_deep_only"], [])

    def test_a_touch_without_a_field_is_the_third_outcome(self):
        """Инв. #17: «имя не разобрано» не есть ни один из двух классов."""
        readers = [_reader("a.py", [_touch(None)])]
        scope = self._scope(readers=readers)
        self.assertEqual(len(scope["deciding_field_unmeasured"]), 1)
        self.assertEqual(scope["touches_admitted_by_deep_only"], [])
        self.assertEqual(scope["touches_admitted_by_shallow_only"], [])
        self.assertEqual(scope["readers_admitted_by_deep"], 0)

    def test_a_printing_touch_is_in_neither_population(self):
        readers = [_reader("a.py", [_touch("kind", form=C.TOUCH_PRINTS)])]
        widened = {"file": "top.py", "counts": {"critical": 0},
                   "findings": [{"kind": "ИНОЕ", "file": "x.py"}]}
        scope = self._scope(widened=widened, readers=readers)
        self.assertEqual(scope["readers_admitted_by_deep"], 0)
        self.assertEqual(scope["deciding_field_unmeasured"], [])

    def test_the_step_stays_advisory_and_names_its_order(self):
        scope = self._scope()
        self.assertFalse(scope["applied"])
        self.assertEqual(scope["order"], "G72.2")
        self.assertEqual(scope["max_depth_declared"], C.DEEP_FLATTEN_MAX_DEPTH)

    def test_the_depth_limit_reaches_the_document(self):
        doc = value = {}
        for _ in range(C.DEEP_FLATTEN_MAX_DEPTH + 3):
            nxt = {}
            value["deeper"] = nxt
            value = nxt
        value["leaf"] = 1
        scope = self._scope(clean=doc)
        self.assertTrue(scope["paths_depth_capped"])

    def test_ambiguous_paths_are_sampled_but_the_count_is_whole(self):
        """Усечение ПОКАЗА названо своим полем, а не молчанием."""
        rows = [{"file": f"f{n}.py"} for n in range(10)]
        scope = self._scope(clean={"rows": rows})
        entry = scope["ambiguous_tails_deep"]["file"]
        self.assertEqual(entry["paths"], 10)
        self.assertEqual(len(entry["sample"]), C.AMBIGUOUS_PATH_SAMPLE)


class WiringTests(unittest.TestCase):
    """Замер доезжает до документа ПО ФОРМЕ ЗОВА, а не по подстроке."""

    def _harm_body(self):
        tree = ast.parse(PRODUCER_SRC.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and node.name == "neighbour_population_harm"):
                return node
        self.fail("в производителе нет `neighbour_population_harm`")

    def test_the_harm_step_calls_the_measurement(self):
        body = self._harm_body()
        calls = [n for n in ast.walk(body)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "_flatten_rule_scope"]
        self.assertEqual(len(calls), 1,
                         "шаг не зовёт замер правила уплощения")

    def test_the_result_is_bound_and_returned_under_its_own_key(self):
        """Зов без выхода в документ — украшение, а не проводка."""
        body = self._harm_body()
        bound = None
        for node in ast.walk(body):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "_flatten_rule_scope"
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                bound = node.targets[0].id
        self.assertIsNotNone(bound, "результат замера никуда не связан")
        returned = False
        for node in ast.walk(body):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if (isinstance(key, ast.Constant)
                        and key.value == "flatten_scope"
                        and isinstance(value, ast.Name)
                        and value.id == bound):
                    returned = True
        self.assertTrue(returned,
                        "`flatten_scope` не отдан из шага связанным значением")


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
