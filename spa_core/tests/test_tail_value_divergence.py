#!/usr/bin/env python3
"""Заказ G74 п. 1: расходятся ли ЗНАЧЕНИЯ по путям многозначного хвоста.

Каждый тест здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: сцена, в которой порвано ровно
одно звено, и проверка краснеет именно от него.

Отдельно стои́т пара :class:`TheHarnessReallyIsolatesTheDataDir`. Весь ответ
на вторую половину заказа держится на утверждении о МЕХАНИЗМЕ — «autouse-
фикстура уводит ``SPA_DATA_DIR`` всякого теста без метки ``live_data``». Такое
утверждение без прогона есть проза, и ноль дошедших подстановок был бы
украшением. Пара проверяет его В ОБЕ СТОРОНЫ и в настоящем прогоне.
"""
from __future__ import annotations

import ast
import os
import tempfile
import textwrap
import unittest
from pathlib import Path

import pytest

from spa_core.monitoring import rule_second_copy_census as C
from spa_core.tests import data_dir_guard
from spa_core.tests import test_registry_ambiguity_scope as N


# ---------------------------------------------------------------------------
# `repr` обратно в значение: нечитаемое — ТРЕТИЙ исход, не `None`
# ---------------------------------------------------------------------------
class TypedValueTest(unittest.TestCase):

    def test_literal_round_trips(self):
        for value in (0, 1.5, "текст", [1, 2], {"a": 1}, None, True):
            ok, back = C._typed_value(repr(value))
            self.assertTrue(ok, repr(value))
            self.assertEqual(back, value)

    def test_nan_is_not_a_literal_and_says_so(self):
        # Достижимый случай: json.dumps(float('nan')) пишет `NaN`, json.loads
        # читает его обратно, и repr даёт `nan` — литералом это не является.
        ok, back = C._typed_value(repr(float("nan")))
        self.assertFalse(ok)
        self.assertIsNone(back)

    def test_opaque_repr_is_not_a_literal(self):
        ok, _ = C._typed_value("<object object at 0x1>")
        self.assertFalse(ok)

    def test_a_name_is_not_read_as_a_value(self):
        ok, _ = C._typed_value("some_name")
        self.assertFalse(ok)


# ---------------------------------------------------------------------------
# Род значения: разница ПЕЧАТИ расхождением не является
# ---------------------------------------------------------------------------
class ValueKindTest(unittest.TestCase):

    def test_int_and_float_of_one_magnitude_are_one_value(self):
        self.assertEqual(C._value_kind(5_000_000), C._value_kind(5000000.0))

    def test_bool_is_not_a_number(self):
        # `True` и `1` решают по-разному, и слить их значило бы потерять
        # ровно то различие, ради которого третий исход и заводится.
        self.assertNotEqual(C._value_kind(True), C._value_kind(1))
        self.assertEqual(C._value_kind(True)[0], "bool")

    def test_none_has_its_own_kind(self):
        self.assertEqual(C._value_kind(None)[0], "null")

    def test_dict_key_order_does_not_make_a_new_value(self):
        self.assertEqual(C._value_kind({"a": 1, "b": 2}),
                         C._value_kind({"b": 2, "a": 1}))

    def test_list_order_does_make_a_new_value(self):
        self.assertNotEqual(C._value_kind([1, 2]), C._value_kind([2, 1]))

    def test_unserialisable_value_does_not_raise(self):
        kind, canon = C._value_kind({1, 2})
        self.assertEqual(kind, "set")
        self.assertTrue(canon)


# ---------------------------------------------------------------------------
# Расхождение значений по путям одного хвоста
# ---------------------------------------------------------------------------
class ValueDivergenceTest(unittest.TestCase):

    @staticmethod
    def _flat(**pairs):
        return {k: v for k, v in pairs.items()}

    def test_identical_text_is_agreement(self):
        flat = self._flat(a="'CRITICAL'", b="'CRITICAL'")
        out = C._value_divergence(["a", "b"], flat)
        self.assertEqual(out["value_outcome"], C.VALUE_AGREE)
        self.assertEqual(out["distinct_text"], 1)

    def test_different_values_are_divergence(self):
        out = C._value_divergence(["a", "b"], self._flat(a="24", b="30"))
        self.assertEqual(out["value_outcome"], C.VALUE_DIFFER)
        self.assertEqual(out["distinct_value"], 2)

    def test_text_only_divergence_is_its_own_outcome(self):
        # Ровно тот случай, ради которого сравнение идёт ДВУМЯ правилами:
        # объявить это расхождением значило бы выдать разницу печати за
        # разницу значения и завысить ответ заказа.
        out = C._value_divergence(["a", "b"],
                                  self._flat(a="5000000", b="5000000.0"))
        self.assertEqual(out["value_outcome"], C.VALUE_TEXT_ONLY)
        self.assertEqual(out["distinct_text"], 2)
        self.assertEqual(out["distinct_value"], 1)

    def test_unreadable_value_is_a_third_outcome_not_a_divergence(self):
        out = C._value_divergence(["a", "b"], self._flat(a="nan", b="0"))
        self.assertEqual(out["value_outcome"], C.VALUE_OPAQUE)
        self.assertIsNone(out["distinct_value"])
        self.assertEqual(out["opaque_total"], 1)

    def test_identical_text_wins_over_unreadability(self):
        # Тексты совпали ⇒ значения совпали, каким бы нечитаемым ни был
        # литерал. Объявить это «не измерено» значило бы отказать там, где
        # ответ доказан.
        out = C._value_divergence(["a", "b"], self._flat(a="nan", b="nan"))
        self.assertEqual(out["value_outcome"], C.VALUE_AGREE)

    def test_kinds_differ_when_a_count_meets_a_list(self):
        out = C._value_divergence(["a", "b"], self._flat(a="0", b="[]"))
        self.assertTrue(out["kinds_differ"])
        self.assertEqual(sorted(out["kinds"]), ["list", "number"])

    def test_kinds_do_not_differ_between_two_numbers(self):
        out = C._value_divergence(["a", "b"], self._flat(a="1", b="2"))
        self.assertFalse(out["kinds_differ"])

    def test_opaque_sample_is_truncated_but_the_count_is_not(self):
        paths = [f"p{i}" for i in range(C.COSTED_SAMPLE + 3)]
        flat = {p: "nan" for p in paths}
        flat[paths[0]] = "inf"          # чтобы тексты не совпали
        out = C._value_divergence(paths, flat)
        self.assertEqual(out["opaque_total"], len(paths))
        self.assertLessEqual(len(out["opaque_paths"]), C.COSTED_SAMPLE)


# ---------------------------------------------------------------------------
# Метки pytest: фикстура спрашивает ближайшую, значит читать надо все три уровня
# ---------------------------------------------------------------------------
def _tree(text: str) -> ast.AST:
    return ast.parse(text)


class MarkNamesTest(unittest.TestCase):

    def _marks_of_first_function(self, text):
        tree = _tree(text)
        fn = tree.body[-1]
        return C._pytest_mark_names(fn.decorator_list)

    def test_plain_mark_is_found(self):
        self.assertEqual(
            self._marks_of_first_function(
                "import pytest\n@pytest.mark.live_data\ndef test_x():\n    pass\n"),
            {"live_data"})

    def test_called_mark_is_found(self):
        self.assertEqual(
            self._marks_of_first_function(
                "import pytest\n@pytest.mark.live_data()\ndef test_x():\n    pass\n"),
            {"live_data"})

    def test_mark_imported_directly_is_found(self):
        self.assertEqual(
            self._marks_of_first_function(
                "from pytest import mark\n@mark.live_data\ndef test_x():\n    pass\n"),
            {"live_data"})

    def test_a_fixture_is_not_a_mark(self):
        self.assertEqual(
            self._marks_of_first_function(
                "import pytest\n@pytest.fixture\ndef test_x():\n    pass\n"),
            set())

    def test_a_foreign_decorator_is_not_a_mark(self):
        self.assertEqual(
            self._marks_of_first_function(
                "import unittest\n@unittest.skip('x')\ndef test_x():\n    pass\n"),
            set())


class ModuleMarksTest(unittest.TestCase):

    def test_single_module_mark_is_found(self):
        self.assertEqual(
            C._module_marks(_tree("import pytest\npytestmark = pytest.mark.live_data\n")),
            {"live_data"})

    def test_list_of_module_marks_is_found(self):
        self.assertEqual(
            C._module_marks(_tree(
                "import pytest\npytestmark = [pytest.mark.live_data, pytest.mark.slow]\n")),
            {"live_data", "slow"})

    def test_annotated_module_mark_is_found(self):
        self.assertEqual(
            C._module_marks(_tree(
                "import pytest\npytestmark: list = [pytest.mark.live_data]\n")),
            {"live_data"})

    def test_another_module_variable_is_not_a_mark(self):
        self.assertEqual(
            C._module_marks(_tree("import pytest\nMARKS = pytest.mark.live_data\n")),
            set())


# ---------------------------------------------------------------------------
# Какому тесту принадлежит решающая строка
# ---------------------------------------------------------------------------
_CLASS_SRC = """import pytest


class Helper:
    def helper(self):
        x = 1


class TestOne:
    def test_alpha(self):
        x = 1
        y = 2

    def not_a_test(self):
        z = 3


def test_beta():
    w = 4


def helper_at_module_level():
    v = 5
"""


class LocateTestTest(unittest.TestCase):

    def setUp(self):
        self.tree = _tree(_CLASS_SRC)

    def _at(self, needle):
        line = _CLASS_SRC.splitlines().index(needle) + 1
        return C._locate_test(self.tree, line)

    def test_line_inside_a_class_method_names_class_and_method(self):
        self.assertEqual(self._at("        y = 2")["test"],
                         "TestOne::test_alpha")

    def test_line_inside_a_module_level_test_names_the_function(self):
        self.assertEqual(self._at("    w = 4")["test"], "test_beta")

    def test_line_inside_a_non_test_method_belongs_to_no_test(self):
        self.assertIsNone(self._at("        z = 3"))

    def test_line_inside_a_module_level_helper_belongs_to_no_test(self):
        self.assertIsNone(self._at("    v = 5"))

    def test_line_inside_a_plain_class_belongs_to_no_test(self):
        self.assertIsNone(self._at("        x = 1"))

    def test_marks_accumulate_from_module_class_and_function(self):
        src = ("import pytest\n"
               "pytestmark = pytest.mark.alpha\n"
               "\n"
               "@pytest.mark.beta\n"
               "class TestX:\n"
               "    @pytest.mark.gamma\n"
               "    def test_y(self):\n"
               "        q = 1\n")
        line = src.splitlines().index("        q = 1") + 1
        found = C._locate_test(_tree(src), line)
        self.assertEqual(found["marks"], ["alpha", "beta", "gamma"])


# ---------------------------------------------------------------------------
# Достижимость вердикта подстановкой в живой документ
# ---------------------------------------------------------------------------
class ReachTest(unittest.TestCase):

    _SRC = ("import pytest\n"
            "\n"
            "class TestPlain:\n"
            "    def test_a(self):\n"
            "        a = 1\n"
            "\n"
            "class TestLive:\n"
            "    @pytest.mark.live_data\n"
            "    def test_b(self):\n"
            "        b = 2\n"
            "\n"
            "def helper():\n"
            "    c = 3\n")

    def _reach_at(self, needle, src=None):
        src = src or self._SRC
        line = src.splitlines().index(needle) + 1
        return C._reach_of(_tree(src), line)

    def test_unparsed_file_is_its_own_outcome(self):
        out = C._reach_of(None, 10)
        self.assertEqual(out["reach"], C.REACH_FILE_UNPARSED)

    def test_missing_line_is_not_an_absent_test(self):
        out = C._reach_of(_tree(self._SRC), None)
        self.assertEqual(out["reach"], C.REACH_NO_TEST)
        self.assertIn("строка", out["reason"])

    def test_line_outside_any_test_is_its_own_outcome(self):
        self.assertEqual(self._reach_at("    c = 3")["reach"], C.REACH_NO_TEST)

    def test_plain_test_is_isolated_and_the_guard_is_named(self):
        out = self._reach_at("        a = 1")
        self.assertEqual(out["reach"], C.REACH_ISOLATED)
        self.assertIn(C.ISOLATION_GUARD, out["reason"])
        self.assertIn(C.ISOLATION_MARKER, out["reason"])

    def test_marked_test_can_be_reached(self):
        out = self._reach_at("        b = 2")
        self.assertEqual(out["reach"], C.REACH_LIVE)

    def test_class_level_mark_opts_the_method_out(self):
        src = ("import pytest\n"
               "@pytest.mark.live_data\n"
               "class TestX:\n"
               "    def test_y(self):\n"
               "        d = 4\n")
        self.assertEqual(self._reach_at("        d = 4", src)["reach"],
                         C.REACH_LIVE)

    def test_module_level_mark_opts_the_method_out(self):
        src = ("import pytest\n"
               "pytestmark = pytest.mark.live_data\n"
               "class TestX:\n"
               "    def test_y(self):\n"
               "        e = 5\n")
        self.assertEqual(self._reach_at("        e = 5", src)["reach"],
                         C.REACH_LIVE)


# ---------------------------------------------------------------------------
# Сведение: ноль обязан быть отличим от «не измерено»
# ---------------------------------------------------------------------------
def _costed(outcome=C.VALUE_DIFFER, reach=C.REACH_ISOLATED, kinds_differ=False):
    return {"file": "spa_core/tests/test_x.py", "line": 7, "field": "f",
            "paths": 2, "value_outcome": outcome, "distinct_text": 2,
            "distinct_value": 2, "kinds": ["number", "list"],
            "kinds_differ": kinds_differ, "reach": reach,
            "test": "TestX::test_y"}


def _scope(rows):
    return {"status": "MEASURED", "rows": rows}


def _row(costed, name="doc"):
    return {"census": name, "costs_a_reader": bool(costed),
            "costed_touches": len(costed), "costed_all": costed}


class AggregateTest(unittest.TestCase):

    def test_a_non_dict_scope_is_unmeasured(self):
        out = C.tail_value_divergence(None)
        self.assertEqual(out["status"], "UNMEASURED")
        self.assertIn("НЕ", out["reason"].upper())

    def test_an_unmeasured_scope_stays_unmeasured(self):
        out = C.tail_value_divergence({"status": "UNMEASURED",
                                       "reason": "реестр не ввезён"})
        self.assertEqual(out["status"], "UNMEASURED")
        self.assertIn("реестр не ввезён", out["reason"])

    def test_a_scope_without_rows_is_unmeasured_not_empty(self):
        out = C.tail_value_divergence({"status": "MEASURED"})
        self.assertEqual(out["status"], "UNMEASURED")

    def test_a_costing_row_without_its_population_refuses(self):
        # Инв. #17 в чистом виде: строка объявила цену читателю, а перечня в
        # ней нет. Сосчитать это нулём расхождений значило бы выдать
        # непрочитанное население за измеренное отсутствие вреда.
        row = {"census": "doc", "costs_a_reader": True, "costed_touches": 3}
        out = C.tail_value_divergence(_scope([row]))
        self.assertEqual(out["status"], "UNMEASURED")
        self.assertIn("doc", out["reason"])

    def test_no_costing_row_is_its_own_verdict(self):
        out = C.tail_value_divergence(_scope([{"census": "d",
                                               "costs_a_reader": False}]))
        self.assertEqual(out["verdict"], C.DIVERGENCE_NOTHING_COSTED)
        self.assertEqual(out["costed_total"], 0)

    def test_agreement_everywhere_is_its_own_verdict(self):
        out = C.tail_value_divergence(
            _scope([_row([_costed(outcome=C.VALUE_AGREE)])]))
        self.assertEqual(out["verdict"], C.DIVERGENCE_NONE)
        self.assertEqual(out["diverging"], 0)

    def test_divergence_nobody_can_see_is_not_called_harmless(self):
        out = C.tail_value_divergence(_scope([_row([_costed()])]))
        self.assertEqual(out["verdict"], C.DIVERGENCE_ARTIFACT_ONLY)
        self.assertEqual(out["diverging"], 1)
        self.assertEqual(out["diverging_reaching_a_verdict"], 0)

    def test_a_reachable_divergence_changes_the_verdict(self):
        # Обратная сторона предыдущего: без неё «до вердикта не доходит» было
        # бы утверждением, которое прибор не способен опровергнуть никогда.
        out = C.tail_value_divergence(
            _scope([_row([_costed(reach=C.REACH_LIVE)])]))
        self.assertEqual(out["verdict"], C.DIVERGENCE_REACHES)
        self.assertEqual(out["diverging_reaching_a_verdict"], 1)

    def test_counts_cover_every_read(self):
        costed = [_costed(), _costed(outcome=C.VALUE_AGREE),
                  _costed(outcome=C.VALUE_TEXT_ONLY),
                  _costed(outcome=C.VALUE_OPAQUE)]
        out = C.tail_value_divergence(_scope([_row(costed)]))
        self.assertEqual(out["costed_total"], 4)
        self.assertEqual(sum(out["value_counts"].values()), 4)
        self.assertEqual(sum(out["reach_counts"].values()), 4)

    def test_text_only_divergence_is_not_counted_as_divergence(self):
        out = C.tail_value_divergence(
            _scope([_row([_costed(outcome=C.VALUE_TEXT_ONLY)])]))
        self.assertEqual(out["diverging"], 0)
        self.assertEqual(out["verdict"], C.DIVERGENCE_NONE)

    def test_kind_conflicts_are_counted_separately(self):
        out = C.tail_value_divergence(
            _scope([_row([_costed(kinds_differ=True), _costed()])]))
        self.assertEqual(out["kinds_differ"], 1)

    def test_documents_are_counted_not_reads(self):
        out = C.tail_value_divergence(
            _scope([_row([_costed()], name="a"),
                    _row([_costed(), _costed()], name="b")]))
        self.assertEqual(out["documents_costing"], 2)
        self.assertEqual(out["costed_total"], 3)

    def test_blindness_is_stated_not_implied(self):
        out = C.tail_value_divergence(_scope([_row([_costed()])]))
        self.assertTrue(out["blind"])
        self.assertTrue(any("фикстур" in b for b in out["blind"]))


# ---------------------------------------------------------------------------
# Проводка: перечень стоящих чтений обязан доезжать ЦЕЛИКОМ
# ---------------------------------------------------------------------------
class WiringTest(unittest.TestCase):

    @staticmethod
    def _measure_fn():
        tree = ast.parse(Path(C.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "measure":
                return node
        raise AssertionError("в переписи нет функции `measure`")

    def test_measure_binds_the_step_and_returns_that_binding(self):
        # Проверка по ФОРМЕ ЗОВА, а не по подстроке: тест на вхождение имени
        # пережил бы любое расцепление — вызов остался бы, а ключ уехал бы
        # пустым (или наоборот).
        fn = self._measure_fn()
        bound = None
        for node in ast.walk(fn):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "tail_value_divergence"
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                bound = node.targets[0].id
        self.assertIsNotNone(bound, "шаг не позван из `measure`")
        returned = False
        for node in ast.walk(fn):
            if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
                continue
            for key, value in zip(node.value.keys, node.value.values):
                if (isinstance(key, ast.Constant)
                        and key.value == "tail_value_divergence"
                        and isinstance(value, ast.Name) and value.id == bound):
                    returned = True
        self.assertTrue(returned,
                        "результат шага не уехал в документ переписи")

    def test_the_step_is_fed_by_the_neighbour_not_by_a_second_road(self):
        fn = self._measure_fn()
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "tail_value_divergence"):
                self.assertEqual(len(node.args), 1)
                self.assertIsInstance(node.args[0], ast.Name)
                return
        raise AssertionError("зова шага в `measure` нет")

    def test_costed_all_is_the_full_list_not_a_sample(self):
        # Первая редакция везла только `costed_sample` (три строки), и ответ
        # заказа был бы 3 вместо 38, не сказав об усечении ни слова.
        readers = [{"file": "spa_core/tests/test_x.py",
                    "touches": [{"form": C.TOUCH_DECIDES, "field": "f",
                                 "line": n, "field_path": None,
                                 "field_path_outcome": "unresolved"}
                                for n in range(C.COSTED_SAMPLE + 4)]}]
        owners = {"f": ["a.f", "b.f"]}
        flat = {"a.f": "1", "b.f": "2"}
        costed, counts = C._costed_touches(readers, owners, {"f"}, flat,
                                           lambda rel, line: C._reach_of(None, line))
        self.assertEqual(len(costed), C.COSTED_SAMPLE + 4)
        self.assertEqual(counts[C.COST_DECIDES_AMBIGUOUS], C.COSTED_SAMPLE + 4)

    def test_each_costed_read_carries_its_divergence_and_its_reach(self):
        readers = [{"file": "spa_core/tests/test_x.py",
                    "touches": [{"form": C.TOUCH_DECIDES, "field": "f",
                                 "line": 3, "field_path": None,
                                 "field_path_outcome": "unresolved"}]}]
        costed, _ = C._costed_touches(
            readers, {"f": ["a.f", "b.f"]}, {"f"}, {"a.f": "1", "b.f": "2"},
            lambda rel, line: C._reach_of(None, line))
        self.assertEqual(costed[0]["value_outcome"], C.VALUE_DIFFER)
        self.assertEqual(costed[0]["reach"], C.REACH_FILE_UNPARSED)

    def test_without_the_two_inputs_the_old_shape_survives(self):
        # Сосед зовёт `_costed_touches` и без новых входов; молчаливая
        # поломка старой формы была бы починкой заказа ценой чужого шага.
        readers = [{"file": "f.py",
                    "touches": [{"form": C.TOUCH_DECIDES, "field": "f",
                                 "line": 3, "field_path": None,
                                 "field_path_outcome": "unresolved"}]}]
        costed, _ = C._costed_touches(readers, {"f": ["a.f", "b.f"]}, {"f"})
        self.assertNotIn("value_outcome", costed[0])
        self.assertEqual(costed[0]["field"], "f")


# ---------------------------------------------------------------------------
# Отчёт: отсутствие шага обязано ЗВУЧАТЬ, а не молчать
# ---------------------------------------------------------------------------
def _doc(div):
    return {"status": "CLEAN", "counts": {}, "remedy_counts": {},
            "tail_value_divergence": div}


class ReportTest(unittest.TestCase):

    def _lines(self, div):
        return [l for l in C.report(_doc(div))
                if "РАСХОЖДЕНИЕ ЗНАЧЕНИЙ" in l]

    def test_absent_step_is_reported_as_not_measured(self):
        lines = [l for l in C.report({"status": "CLEAN", "counts": {},
                                      "remedy_counts": {}})
                 if "РАСХОЖДЕНИЕ ЗНАЧЕНИЙ" in l]
        self.assertTrue(lines)
        self.assertIn("НЕ ИЗМЕРЕНО", lines[0])

    def test_unmeasured_step_prints_its_reason(self):
        lines = self._lines({"status": "UNMEASURED", "reason": "реестра нет"})
        self.assertTrue(any("реестра нет" in l for l in lines))

    def test_measured_step_prints_both_numbers(self):
        div = C.tail_value_divergence(
            _scope([_row([_costed(), _costed(outcome=C.VALUE_AGREE)])]))
        lines = self._lines(div)
        body = "\n".join(lines)
        self.assertIn(C.DIVERGENCE_ARTIFACT_ONLY, body)
        self.assertIn(C.ISOLATION_GUARD, body)

    def test_missing_counts_are_named_not_substituted(self):
        # Проверка ИМЕННО заглавной строки: «НЕ ИЗМЕРЕН» звучит и в строке о
        # достижимости, поэтому поиск по всему отчёту прошёл бы и тогда,
        # когда учёт молча напечатан нулями (батарея это и показала).
        lines = self._lines({"status": "MEASURED", "verdict": "v",
                             "costed_total": 1, "documents_costing": 1,
                             "kinds_differ": 0,
                             "isolation_guard": C.ISOLATION_GUARD,
                             "isolation_marker": C.ISOLATION_MARKER})
        headline = next(l for l in lines if "вердикт" in l)
        self.assertIn("учёт по исходам НЕ ИЗМЕРЕН", headline)
        self.assertNotIn("РАСХОДЯТСЯ", headline)

    def test_missing_reach_counts_are_named_not_substituted(self):
        lines = self._lines({"status": "MEASURED", "verdict": "v",
                             "costed_total": 1, "documents_costing": 1,
                             "kinds_differ": 0, "value_counts": {},
                             "isolation_guard": C.ISOLATION_GUARD,
                             "isolation_marker": C.ISOLATION_MARKER})
        reach_line = next(l for l in lines if "ДОСТИЖИМОСТЬ" in l)
        self.assertIn("НЕ ИЗМЕРЕНА", reach_line)


# ---------------------------------------------------------------------------
# Утверждение о МЕХАНИЗМЕ, на котором держится весь ответ, — в обе стороны
# ---------------------------------------------------------------------------
class TheHarnessReallyIsolatesTheDataDir(unittest.TestCase):
    """Прибор объявляет 38 чтений недостижимыми ПО ПОСТРОЕНИЮ.

    Основание — поведение чужой autouse-фикстуры. Прочесть его из docstring
    значило бы повторить ровно тот дефект, который заказ G70 назвал у
    соседа: «причина отказа, которую никто не померил». Пара ниже меряет.
    """

    def test_a_plain_test_never_sees_the_live_data_dir(self):
        # Эта сторона держит вывод `isolated_…`: вердикт такого теста живому
        # документу недоступен, и ноль подстановок у него есть свойство
        # фикстуры.
        raw = os.environ.get(data_dir_guard.DATA_DIR_ENV
                             if hasattr(data_dir_guard, "DATA_DIR_ENV")
                             else "SPA_DATA_DIR")
        self.assertIsNotNone(raw, "фикстура изоляции не выставила переменную")
        self.assertIn(data_dir_guard.SANDBOX_PREFIX, raw)
        self.assertNotEqual(Path(raw).resolve(),
                            data_dir_guard.LIVE_DATA_DIR.resolve())


@pytest.mark.live_data
def test_a_marked_test_escapes_the_sandbox():
    """Обратная сторона: метка `live_data` действительно снимает изоляцию.

    Без неё вывод «недостижимо» был бы неопровержим по построению — прибор
    не смог бы назвать достижимым ни один тест, и `REACH_LIVE` оставался бы
    украшением.
    """
    raw = os.environ.get("SPA_DATA_DIR")
    assert raw is None or data_dir_guard.SANDBOX_PREFIX not in raw, (
        "метка `live_data` не сняла изоляцию — тогда и REACH_LIVE не значит "
        "того, что прибор им называет")


# ---------------------------------------------------------------------------
# Целый контур: сцена соседа, а не вторая её копия
# ---------------------------------------------------------------------------
#: Читатель сцены с ПЯТЬЮ стоящими чтениями — больше, чем `COSTED_SAMPLE`.
#: Четырёх не хватило бы: усечение до образца на трёх строках выглядит
#: правдоподобно ровно до тех пор, пока строк не стало больше трёх.
_MANY_READS_SRC = textwrap.dedent("""
    from spa_core.monitoring import scene_census


    def test_one():
        doc = scene_census.measure(".")
        row = doc["rows"][0]
        assert row["verdict"] == "ok"


    def test_two():
        doc = scene_census.measure(".")
        row = doc["rows"][0]
        assert row["verdict"] == "ok"


    def test_three():
        doc = scene_census.measure(".")
        row = doc["rows"][0]
        assert row["verdict"] == "ok"


    def test_four():
        doc = scene_census.measure(".")
        row = doc["rows"][0]
        assert row["verdict"] == "ok"


    def test_five():
        doc = scene_census.measure(".")
        row = doc["rows"][0]
        assert row["verdict"] == "ok"
""")


class WholeContourTest(unittest.TestCase):
    """Сцена берётся У СОСЕДА (`test_registry_ambiguity_scope`).

    Вторая копия строителя сцены и была бы ровно тем дефектом, который вся
    эта перепись ищет: одно правило, две копии.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        N._scene_tree(self.tmp)
        (self.tmp / "spa_core" / "tests" / "test_many_reads.py").write_text(
            _MANY_READS_SRC, encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def _row(self):
        got = N._measure(self.tmp)
        self.assertEqual(got["status"], "MEASURED", got.get("reason"))
        row = next(r for r in got["rows"] if r["census"] == "scene_census")
        return got, row

    def test_the_full_population_reaches_the_answer_not_a_sample(self):
        _, row = self._row()
        self.assertGreater(row["costed_touches"], C.COSTED_SAMPLE)
        self.assertEqual(len(row["costed_all"]), row["costed_touches"])
        self.assertLessEqual(len(row["costed_sample"]), C.COSTED_SAMPLE)

    def test_the_flat_map_reaches_the_comparison(self):
        # Без неё каждое стоящее чтение уехало бы БЕЗ исхода расхождения, и
        # сведение объявило бы `values_agree` ноль у всех — тихо.
        _, row = self._row()
        for item in row["costed_all"]:
            self.assertIn("value_outcome", item)
        self.assertTrue(any(i["value_outcome"] == C.VALUE_DIFFER
                            for i in row["costed_all"]))

    def test_the_scene_tail_really_carries_two_kinds(self):
        # Предпосылка сцены названа ЗАМЕРОМ, а не подразумевается: если
        # документ сцены однажды станет однородным, тест выше перестанет
        # что-либо проверять — и скажет об этом здесь, а не молча.
        _, row = self._row()
        diverging = [i for i in row["costed_all"]
                     if i["value_outcome"] == C.VALUE_DIFFER]
        self.assertTrue(diverging)
        self.assertTrue(any(i["kinds_differ"] for i in diverging))

    def test_reach_is_measured_for_every_costed_read(self):
        _, row = self._row()
        for item in row["costed_all"]:
            self.assertIn(item["reach"], C._REACH_OUTCOMES)

    def test_the_aggregate_reads_this_contour_end_to_end(self):
        got, _ = self._row()
        div = C.tail_value_divergence(got)
        self.assertEqual(div["status"], "MEASURED")
        self.assertGreater(div["costed_total"], C.COSTED_SAMPLE)
        self.assertEqual(div["verdict"], C.DIVERGENCE_ARTIFACT_ONLY)

# ---------------------------------------------------------------------------
# Заказ G75 п. 4: ненаблюдённая достижимость — ТРЕТИЙ исход, а не класс
# ---------------------------------------------------------------------------
class AbsentReachIsNotAnOutcome(unittest.TestCase):
    """Два украшения внутри самого прибора, снятые циклом #678.

    До правки достижимость читалась так::

        reach = str((item.get("reach_outcome") or {}).get("reach")
                    if isinstance(item.get("reach_outcome"), dict)
                    else item.get("reach"))

    Здесь два разных дефекта, и каждый проверяется отдельно.

    **Второе имя.** Ключа ``reach_outcome`` не писал НИ ОДИН производитель
    (замер #678: 0 из 2 живых артефактов; они несут ``reach``/``reach_reason``).
    Второе имя одного предмета — внутри прибора, который ищет вторые копии.

    **Исход с именем ``"None"``.** ``str()`` поверх отсутствующего значения
    заводил в счётчик класс, буквально названный ``"None"``. Вред не в
    счётчике: ``reaching`` считает только :data:`REACH_LIVE`, поэтому
    ненаблюдённая достижимость молча становилась «до вердикта не доходит» —
    ровно тем вердиктом, на котором стои́т весь вывод ADR-458.

    Контроль обязан идти В ОБЕ СТОРОНЫ: правка, обратившая КАЖДОЕ чтение в
    отказ, прошла бы отрицательную половину и уничтожила прибор. Поэтому
    :meth:`test_a_known_reach_still_measures` и его сосед по вердикту —
    такая же часть контроля, как и сами отказы.
    """

    _BASE = {"file": "spa_core/tests/test_x.py", "line": 7, "field": "f",
             "paths": 2, "value_outcome": C.VALUE_DIFFER, "distinct_text": 2,
             "distinct_value": 2, "kinds": ["number", "list"],
             "kinds_differ": False}

    def _run(self, **over):
        item = dict(self._BASE)
        item.update(over)
        item.pop("__drop_reach", None)
        if over.get("__drop_reach"):
            item.pop("reach", None)
        return C.tail_value_divergence(_scope([_row([item])]))

    # --- отрицательная половина: дефект вернулся ⇒ красное ----------------
    def test_a_read_without_reach_refuses_instead_of_counting(self):
        out = self._run(__drop_reach=True)
        self.assertEqual(out["status"], "UNMEASURED")
        self.assertNotIn("verdict", out)
        # Статуса мало: «не записано» и «записан незнакомый класс» чинятся
        # разным, и отказ, который их сливает, — снова счётчик (замер #678:
        # без этой строки мутация `str(item.get("reach"))` ВЫЖИВАЛА, потому
        # что подменяла один третий исход другим, оставаясь UNMEASURED).
        self.assertEqual(out["unmeasured_class"], C.UNMEASURED_REACH_ABSENT)

    def test_the_absent_reach_never_becomes_a_class_called_none(self):
        # Сторож ровно того выражения, что снято: класса `"None"` в счётчике
        # не появляется, потому что счётчик до него не доходит вовсе.
        out = self._run(__drop_reach=True)
        self.assertNotIn("reach_counts", out)
        self.assertNotIn("None", str(out.get("reach_counts", "")))

    def test_the_refusal_names_which_read_is_unmeasured(self):
        # Отказ без адреса — снова счётчик: нечего проверить, нечего чинить.
        out = self._run(__drop_reach=True)
        self.assertIn("spa_core/tests/test_x.py:7", out["reason"])

    def test_an_unmeasured_reach_is_not_read_as_not_reaching(self):
        # Сердцевина инв. #17 здесь: «не наблюдено» и «измеренно не доходит»
        # обязаны быть РАЗНЫМИ исходами. До правки оба давали
        # DIVERGENCE_ARTIFACT_ONLY со статусом MEASURED.
        absent = self._run(__drop_reach=True)
        measured_miss = self._run(reach=C.REACH_ISOLATED)
        self.assertEqual(absent["status"], "UNMEASURED")
        self.assertEqual(measured_miss["status"], "MEASURED")
        self.assertEqual(measured_miss["verdict"], C.DIVERGENCE_ARTIFACT_ONLY)

    def test_the_second_name_for_reach_is_gone_from_the_code(self):
        # Ветка была мертва СЕГОДНЯ — по одному вызывающему, а не по коду.
        # Сторож смотрит на исходник, потому что поведением мёртвую ветку
        # не поймать: в том и был её род.
        src = Path(C.__file__).read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines()
                          if not l.lstrip().startswith("#"))
        self.assertNotIn("reach_outcome", code)

    def test_a_reach_class_nobody_declared_refuses_too(self):
        # Та же дыра с другой стороны: незнакомый класс не есть REACH_LIVE и
        # молча попадал бы в «не доходит».
        out = self._run(reach="a_class_no_one_declared")
        self.assertEqual(out["status"], "UNMEASURED")
        self.assertIn("a_class_no_one_declared", out["reason"])
        self.assertEqual(out["unmeasured_class"],
                         C.UNMEASURED_REACH_UNDECLARED)

    def test_a_reach_of_the_wrong_kind_is_absence_not_a_class(self):
        # `observed(..., kind=str)`: мусор в поле не есть замер.
        out = self._run(reach={"reach": C.REACH_LIVE})
        self.assertEqual(out["status"], "UNMEASURED")
        # Род не тот ⇒ наблюдения НЕТ (доктрина `observed`), а не «чужой
        # класс». Без этой строки снятие `kind=str` выживало: словарь просто
        # проваливался в соседний отказ.
        self.assertEqual(out["unmeasured_class"], C.UNMEASURED_REACH_ABSENT)

    # --- положительная половина: прибор ЖИВ -------------------------------
    def test_a_known_reach_still_measures(self):
        out = self._run(reach=C.REACH_LIVE)
        self.assertEqual(out["status"], "MEASURED")
        self.assertEqual(out["reach_counts"][C.REACH_LIVE], 1)
        self.assertEqual(out["verdict"], C.DIVERGENCE_REACHES)

    def test_every_declared_class_is_still_countable(self):
        # Без этого «отказ на всё» прошёл бы отрицательную половину целиком.
        for cls in C._REACH_OUTCOMES:
            with self.subTest(reach=cls):
                out = self._run(reach=cls)
                self.assertEqual(out["status"], "MEASURED")
                self.assertEqual(out["reach_counts"][cls], 1)

    def test_kind_conflicts_are_still_counted_with_reach_present(self):
        # Счёт родов переехал выше проверки достижимости; сцена доказывает,
        # что переезд ничего не потерял.
        out = self._run(reach=C.REACH_LIVE, kinds_differ=True)
        self.assertEqual(out["kinds_differ"], 1)


if __name__ == "__main__":
    unittest.main()
