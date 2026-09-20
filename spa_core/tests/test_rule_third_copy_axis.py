"""Третья ось переписи копий: ТРИ копии одного правила (заказ G53 п. 1).

Заказ G53 п. 1 (хвост [ADR-430](../../docs/decisions/ADR-430-one-copy-was-not-an-answer.md))
приказал спросить ОБЕ существующие оси об ОДНОМ имени: пара «сторож ×
исполнитель» и пара «исполнитель × исполнитель» могут описывать одно правило, и
тогда копий у него три, а не две. Замер даёт **ноль** — и ноль этот не ответ, а
структура: находкой первой оси имя становится при РОВНО ОДНОМ исполнителе,
находкой второй — при РОВНО ДВУХ.

Поэтому главный тест этого файла — положительный контроль НА МОЛЧАНИЕ: в сцене,
где три копии есть НА САМОМ ДЕЛЕ, пересечение осей по-прежнему равно нулю, а
отвечает новая координата. Если однажды пересечение научится видеть такую сцену,
тест покраснеет — и правильно сделает: основание третьей оси придётся перемерить,
а не унаследовать.

Сцены строит `_tree` СОСЕДНЕГО файла, а не своя копия: этот прибор ищет вторые
копии правил, и заводить вторую копию правила «как выглядит дерево сцены» прямо
в его наборе было бы смешно.
"""
from __future__ import annotations

import datetime as dt
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import spa_core.monitoring.rule_second_copy_census as rsc
from spa_core.tests.test_rule_second_copy_peer_axis import _tree

# FROZEN-DATE-OK: injected-clock — дата подаётся в `measure(..., now=)`
# аргументом; ни одна сцена не спрашивает часы машины.
_NOW = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)

#: Величина сцены. Выбрана так, чтобы НЕ совпасть с порогом `_POLICY`
#: соседнего файла (0.07): иначе всякая находка уезжала бы владельцем и сцена
#: мерила бы право чинить вместо своего предмета.
_VALUE = "42"

#: Три копии одного правила: два исполнителя и сторож, и ни один не достаёт
#: другого. Именно эту сцену пересечение осей не видит по построению.
_THREE_COPIES = {
    "spa_core__left.py": f"LIMIT = {_VALUE}\n",
    "spa_core__right.py": f"LIMIT = {_VALUE}\n",
    "spa_core__tests__test_limit.py": f"LIMIT = {_VALUE}\n_read = (LIMIT,)\n",
}


#: Та же сцена ПЛЮС правило с одним исполнителем и своим сторожем: без него
#: первая ось пуста, и пересечение было бы пустым ПО ДРУГОЙ причине
#: («пересекать нечего»). Вердикт «структурно» обязан стоять на двух НЕпустых
#: населениях, иначе он приписывает устройству прибора свойство дерева.
_BOTH_AXES = dict(_THREE_COPIES, **{
    "spa_core__solo.py": "SOLO = 9\n",
    "spa_core__tests__test_solo.py": "SOLO = 9\n_read = (SOLO,)\n",
})


def _constitution(**fields) -> str:
    return json.dumps(fields)


def _triples(doc: dict) -> list:
    return [r for r in doc["triple_rows"] if r["verdict"] == rsc.CLASS_TRIPLE]


def _measure(files: dict, **tree_kwargs) -> dict:
    with TemporaryDirectory() as tmp:
        return rsc.measure(_tree(Path(tmp), **tree_kwargs, **files), now=_NOW)


class TheIntersectionIsEmptyByConstruction(unittest.TestCase):
    """Ноль пересечения — структура, и прибор обязан сказать это числами."""

    @staticmethod
    def _rows(names):
        return [{"verdict": rsc.CLASS_TWO_COPIES, "name": n} for n in names]

    @staticmethod
    def _peer(names):
        return [{"verdict": rsc.CLASS_PEER_TWO_COPIES, "name": n} for n in names]

    def test_shared_name_is_named_not_only_counted(self):
        """Имя, о котором говорят обе оси, обязано быть НАЗВАНО."""
        out = rsc.axes_intersection(
            self._rows(["A"]), self._peer(["A"]),
            {"A": [("spa_core/x.py", "1"), ("spa_core/y.py", "1")]})
        self.assertEqual(out["verdict"], rsc.INTERSECTION_NON_EMPTY)
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["names"], ["A"])

    def test_disjoint_histograms_are_empty_by_construction(self):
        out = rsc.axes_intersection(
            self._rows(["A"]), self._peer(["B"]),
            {"A": [("spa_core/x.py", "1")],
             "B": [("spa_core/y.py", "1"), ("spa_core/z.py", "1")]})
        self.assertEqual(out["verdict"], rsc.INTERSECTION_EMPTY_BY_CONSTRUCTION)
        self.assertEqual(out["count"], 0)
        self.assertIn("СТРУКТУРНЫЙ", out["reason"])

    def test_overlapping_histograms_make_the_zero_a_measurement(self):
        """Гистограммы пересеклись ⇒ ноль ИЗМЕРЕН, и это ДРУГОЙ вердикт.

        Обратная сторона предыдущего теста: если условия осей однажды сойдутся,
        пустое пересечение начнёт что-то значить — и прибор обязан назвать это
        иначе, а не тем же словом.
        """
        out = rsc.axes_intersection(
            self._rows(["A"]), self._peer(["B"]),
            {"A": [("spa_core/x.py", "1"), ("spa_core/q.py", "1")],
             "B": [("spa_core/y.py", "1"), ("spa_core/z.py", "1")]})
        self.assertEqual(out["verdict"], rsc.INTERSECTION_EMPTY_MEASURED)
        self.assertIn("ИЗМЕРЕНО", out["reason"])

    def test_an_empty_axis_is_a_different_zero(self):
        """Пустая сторона ⇒ пересекать НЕЧЕГО, и это НЕ «структурно».

        Собственная ошибка первой редакции, найденная этим тестом: ноль от
        пустой оси объявлялся структурным, то есть свойство ДЕРЕВА выдавалось
        за устройство прибора.
        """
        out = rsc.axes_intersection(
            [], self._peer(["B"]),
            {"B": [("spa_core/y.py", "1"), ("spa_core/z.py", "1")]})
        self.assertEqual(out["verdict"],
                         rsc.INTERSECTION_EMPTY_NOTHING_TO_INTERSECT)
        self.assertIn("НЕЧЕГО", out["reason"])
        self.assertIn("0", out["reason"])

    def test_four_verdicts_give_four_different_reasons(self):
        """Четыре исхода различимы не только ярлыком, но и основанием."""
        reasons = set()
        for rows, peer, declared in (
            (self._rows(["A"]), self._peer(["A"]),
             {"A": [("spa_core/x.py", "1"), ("spa_core/y.py", "1")]}),
            (self._rows(["A"]), self._peer(["B"]),
             {"A": [("spa_core/x.py", "1")],
              "B": [("spa_core/y.py", "1"), ("spa_core/z.py", "1")]}),
            (self._rows(["A"]), self._peer(["B"]),
             {"A": [("spa_core/x.py", "1"), ("spa_core/q.py", "1")],
              "B": [("spa_core/y.py", "1"), ("spa_core/z.py", "1")]}),
            ([], self._peer(["B"]),
             {"B": [("spa_core/y.py", "1"), ("spa_core/z.py", "1")]}),
        ):
            reasons.add(rsc.axes_intersection(rows, peer, declared)["reason"])
        self.assertEqual(len(reasons), 4)

    def test_the_histograms_are_reported_not_just_the_verdict(self):
        """Читатель обязан видеть ЧИСЛА, по которым вынесен вердикт."""
        out = rsc.axes_intersection(
            self._rows(["A"]), self._peer(["B"]),
            {"A": [("spa_core/x.py", "1")],
             "B": [("spa_core/y.py", "1"), ("spa_core/z.py", "1")]})
        self.assertEqual(out["executors_per_name"],
                         {"axis_one": {"1": 1}, "axis_two": {"2": 1}})

    def test_only_findings_enter_the_populations(self):
        """Корзины-не-находки в пересечение не входят."""
        out = rsc.axes_intersection(
            [{"verdict": rsc.CLASS_VALUE_DIFFERS, "name": "A"}],
            [{"verdict": rsc.CLASS_PEER_VALUE_DIFFERS, "name": "A"}],
            {"A": [("spa_core/x.py", "1"), ("spa_core/y.py", "1")]})
        self.assertEqual(out["axis_one_names"], 0)
        self.assertEqual(out["axis_two_names"], 0)


class ThreeCopiesAreInvisibleToTheOldQuestion(unittest.TestCase):
    """Положительный контроль НА МОЛЧАНИЕ — сердце этого файла."""

    def test_the_intersection_stays_zero_while_three_copies_exist(self):
        """Обе оси НЕпусты, три копии есть — пересечение всё равно ноль."""
        doc = _measure(_BOTH_AXES)
        self.assertEqual(doc["axes_intersection"]["axis_one_names"], 1)
        self.assertEqual(doc["axes_intersection"]["axis_two_names"], 1)
        self.assertEqual(doc["axes_intersection"]["count"], 0)
        self.assertEqual(doc["axes_intersection"]["verdict"],
                         rsc.INTERSECTION_EMPTY_BY_CONSTRUCTION)
        self.assertEqual(doc["triple_counts"][rsc.CLASS_TRIPLE], 1,
                         "новая координата обязана увидеть то, о чём молчит пересечение")

    def test_a_scene_without_the_first_axis_reports_the_other_zero(self):
        """Обратная сторона: одна ось пуста ⇒ ДРУГОЙ вердикт, не «структурно»."""
        doc = _measure(_THREE_COPIES)
        self.assertEqual(doc["axes_intersection"]["verdict"],
                         rsc.INTERSECTION_EMPTY_NOTHING_TO_INTERSECT)
        self.assertEqual(doc["triple_counts"][rsc.CLASS_TRIPLE], 1)

    def test_neither_old_axis_names_three_copies(self):
        """Первая ось зовёт это неоднозначностью, вторая — парой; ТРЁХ не видит никто."""
        doc = _measure(_THREE_COPIES)
        self.assertEqual(doc["counts"][rsc.CLASS_TWO_COPIES], 0)
        self.assertEqual(doc["counts"][rsc.CLASS_AMBIGUOUS], 1)
        self.assertEqual(doc["peer_counts"][rsc.CLASS_PEER_TWO_COPIES], 1)

    def test_the_axis_does_not_touch_status(self):
        """Ось мерит поверхность числом и приговора не выносит."""
        doc = _measure(_THREE_COPIES)
        self.assertEqual(doc["status"], "CLEAN")

    def test_the_name_is_counted_once_however_many_guards(self):
        scene = dict(_THREE_COPIES)
        scene["spa_core__tests__test_limit_two.py"] = f"LIMIT = {_VALUE}\n_read = (LIMIT,)\n"
        doc = _measure(scene)
        self.assertEqual(doc["triple_counts"][rsc.CLASS_TRIPLE], 2)
        self.assertEqual(doc["triple_names"], 1,
                         "имён одно, пар две — смешать их значило бы соврать масштабом")

    def test_without_a_guard_there_is_no_triple(self):
        scene = {k: v for k, v in _THREE_COPIES.items() if "tests" not in k}
        doc = _measure(scene)
        self.assertEqual(doc["triple_counts"][rsc.CLASS_TRIPLE], 0)
        self.assertEqual(doc["peer_counts"][rsc.CLASS_PEER_TWO_COPIES], 1,
                         "вторая ось пару по-прежнему видит — изменилась ТРЕТЬЯ")

    def test_a_third_executor_takes_the_name_off_both_axes(self):
        """Имя у трёх исполнителей одного правила не называет — и тройки нет."""
        scene = dict(_THREE_COPIES)
        scene["spa_core__third.py"] = f"LIMIT = {_VALUE}\n"
        doc = _measure(scene)
        self.assertEqual(doc["peer_counts"][rsc.CLASS_PEER_MANY], 1)
        self.assertEqual(doc["triple_counts"][rsc.CLASS_TRIPLE], 0)


class TheGuardSideIsJudgedByDoorsAndValue(unittest.TestCase):
    """Сторож рядом с парой — ещё не третья копия."""

    def test_a_door_to_one_executor_is_not_a_finding(self):
        scene = dict(_THREE_COPIES)
        scene["spa_core__tests__test_limit.py"] = (
            f"from spa_core.left import LIMIT as _L\nLIMIT = {_VALUE}\n_read = (LIMIT, _L)\n")
        doc = _measure(scene)
        self.assertEqual(doc["triple_counts"][rsc.CLASS_TRIPLE_DOOR_ONE], 1)
        self.assertEqual(doc["triple_counts"][rsc.CLASS_TRIPLE], 0)

    def test_a_door_to_both_executors_is_its_own_basket(self):
        scene = dict(_THREE_COPIES)
        scene["spa_core__tests__test_limit.py"] = (
            "from spa_core.left import LIMIT as _L\n"
            "from spa_core.right import LIMIT as _R\n"
            f"LIMIT = {_VALUE}\n_read = (LIMIT, _L, _R)\n")
        doc = _measure(scene)
        self.assertEqual(doc["triple_counts"][rsc.CLASS_TRIPLE_DOOR_BOTH], 1)
        self.assertEqual(doc["triple_counts"][rsc.CLASS_TRIPLE], 0)

    def test_an_equal_name_with_a_different_value_is_not_a_finding(self):
        """`SILENT` замера 20.09: равное имя при разном значении — соглашение."""
        scene = dict(_THREE_COPIES)
        scene["spa_core__tests__test_limit.py"] = "LIMIT = 7\n_read = (LIMIT,)\n"
        doc = _measure(scene)
        self.assertEqual(doc["triple_counts"][rsc.CLASS_TRIPLE_VALUE_DIFFERS], 1)
        self.assertEqual(doc["triple_counts"][rsc.CLASS_TRIPLE], 0)

    def test_a_non_constant_guard_value_is_a_third_outcome(self):
        scene = dict(_THREE_COPIES)
        scene["spa_core__tests__test_limit.py"] = (
            "import os\nLIMIT = int(os.environ.get('X', '1'))\n_read = (LIMIT,)\n")
        doc = _measure(scene)
        self.assertEqual(doc["triple_counts"][rsc.CLASS_TRIPLE_NOT_CONSTANT], 1)
        self.assertEqual(doc["triple_counts"][rsc.CLASS_TRIPLE], 0)

    def test_an_unreadable_guard_is_unmeasured_not_a_finding(self):
        """Текст не перечитан ⇒ вопрос о двери НЕ ИЗМЕРЕН, и это СВОЯ корзина."""
        rows, counts = rsc.triple_copies(
            [{"verdict": rsc.CLASS_PEER_TWO_COPIES, "name": "LIMIT",
              "value": _VALUE, "left": "spa_core/left.py",
              "right": "spa_core/right.py"}],
            {"LIMIT": [("spa_core/tests/test_limit.py", _VALUE)]},
            source_of=lambda rel: None, imports_of=lambda rel: set(),
            thresholds={}, constitution={}, constitution_unread=None)
        self.assertEqual(counts[rsc.CLASS_TRIPLE_UNMEASURED], 1)
        self.assertEqual(counts[rsc.CLASS_TRIPLE], 0)
        self.assertEqual(counts[rsc.CLASS_TRIPLE_NOT_CONSTANT], 0,
                         "«сравнить нечем» и «спросить некого» — разные исходы")
        self.assertIn("не перечитан", rows[0]["reason"])

    def test_a_private_guard_name_is_not_a_guard_side(self):
        scene = dict(_THREE_COPIES)
        scene["spa_core__tests__test_limit.py"] = f"_LIMIT = {_VALUE}\n_read = (_LIMIT,)\n"
        doc = _measure(scene)
        self.assertEqual(doc["triple_counts"][rsc.CLASS_TRIPLE], 0)

    def test_the_unmeasured_row_is_not_counted_as_a_name(self):
        """Строка «не измерено» именем НАХОДКИ не является.

        Первая редакция этого теста повторяла правило выражением прямо в себе
        и поэтому не проверяла ничего: мутация «считать все строки» её
        переживала. Спрашивается сам прибор.
        """
        self.assertEqual(rsc.triple_name_count([
            {"verdict": rsc.CLASS_TRIPLE, "name": "LIMIT"},
            {"verdict": rsc.CLASS_TRIPLE_UNMEASURED, "name": "OTHER"},
        ]), 1)

    def test_a_peer_row_that_is_not_a_finding_never_makes_a_triple(self):
        """Ось берёт ТОЛЬКО находки соседней оси.

        Строка `peer_door_unmeasured` — не пара, а признание в незнании; сделать
        из неё тройку значило бы построить находку на «не измерено».
        """
        rows, counts = rsc.triple_copies(
            [{"verdict": rsc.CLASS_PEER_UNMEASURED, "name": "LIMIT",
              "value": _VALUE, "left": "spa_core/left.py",
              "right": "spa_core/right.py"}],
            {"LIMIT": [("spa_core/tests/test_limit.py", _VALUE)]},
            source_of=lambda rel: f"LIMIT = {_VALUE}\n", imports_of=lambda rel: set(),
            thresholds={}, constitution={}, constitution_unread=None)
        self.assertEqual(rows, [])
        self.assertEqual(counts[rsc.CLASS_TRIPLE], 0)


class TheRightToFixIsAskedFirstAndAtTwoSurfaces(unittest.TestCase):
    """Право чинить спрашивается раньше способа — и у ДВУХ поверхностей."""

    @staticmethod
    def _one(thresholds, constitution, unread=None):
        rows, _ = rsc.triple_copies(
            [{"verdict": rsc.CLASS_PEER_TWO_COPIES, "name": "LIMIT",
              "value": "100000.0", "left": "spa_core/left.py",
              "right": "spa_core/right.py"}],
            {"LIMIT": [("spa_core/tests/test_limit.py", "100000.0")]},
            source_of=lambda rel: "LIMIT = 100000.0\n", imports_of=lambda rel: set(),
            thresholds=thresholds, constitution=constitution,
            constitution_unread=unread)
        return rows[0]

    def test_risk_policy_wins_over_the_shelf(self):
        """Обе поверхности совпали ⇒ предмет №1, а не витрина."""
        row = self._one({"100000.0": ["min_cash_pct"]},
                        {"100000.0": ["start_capital_usd"]})
        self.assertEqual(row["remedy"], rsc.REMEDY_OWNER)
        self.assertIn("min_cash_pct", row["remedy_evidence"])

    def test_the_shelf_field_is_named_in_the_evidence(self):
        row = self._one({}, {"100000.0": ["start_capital_usd"]})
        self.assertEqual(row["remedy"], rsc.REMEDY_CONSTITUTION)
        self.assertIn("start_capital_usd", row["remedy_evidence"])
        self.assertIn(rsc.CONSTITUTION_FILE, row["remedy_evidence"])

    def test_an_unread_shelf_is_unmeasured_not_permission_to_fix(self):
        row = self._one({}, {}, unread="витрина порогов не прочитана (тест)")
        self.assertEqual(row["remedy"], rsc.REMEDY_RIGHT_UNMEASURED)
        self.assertIn("не прочитана", row["remedy_evidence"])

    def test_no_match_anywhere_is_subject_unproven(self):
        row = self._one({}, {})
        self.assertEqual(row["remedy"], rsc.REMEDY_UNPROVEN)
        self.assertIn("не доказывает", row["remedy_evidence"])

    def test_a_tree_without_a_shelf_never_grants_the_right_to_fix(self):
        """Сквозной контроль: витрины в дереве нет ⇒ право НЕ ИЗМЕРЕНО.

        Отсутствие витрины ОБЪЯВЛЕНО сценой (`shelf=None`), а не унаследовано
        от того, что общий помощник её не кладёт. Заказ G54 п. 1 начал
        спрашивать витрину у всех трёх осей и положил её в помощник по
        умолчанию — предпосылка этого контроля молча исчезла бы, а сам он
        покраснел бы по причине, к предмету отношения не имеющей (инв. #16:
        правка намеренная, утверждения дословно на месте).
        """
        doc = _measure(_THREE_COPIES, shelf=None)
        self.assertIsNotNone(doc["constitution_unread"])
        self.assertEqual(doc["triple_remedy_counts"][rsc.REMEDY_RIGHT_UNMEASURED], 1)
        self.assertEqual(doc["triple_remedy_counts"][rsc.REMEDY_UNPROVEN], 0)

    def test_a_shelf_in_the_tree_is_read_and_names_the_subject(self):
        scene = dict(_THREE_COPIES)
        scene["landing__src__lib__constitution.json"] = _constitution(start_capital_usd=42)
        doc = _measure(scene)
        self.assertIsNone(doc["constitution_unread"])
        self.assertEqual(doc["triple_remedy_counts"][rsc.REMEDY_CONSTITUTION], 1)
        self.assertIn("start_capital_usd", _triples(doc)[0]["remedy_evidence"])


class TheShelfIsReadHonestly(unittest.TestCase):
    """Витрина порогов как вторая поверхность решения."""

    def _values(self, text=None):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            if text is not None:
                path = root / "landing" / "src" / "lib"
                path.mkdir(parents=True)
                (path / "constitution.json").write_text(text, encoding="utf-8")
            return rsc.constitution_values(root)

    def test_nested_fields_are_named_by_full_path(self):
        values, unread = self._values(json.dumps({"caps": {"t1": 0.4}}))
        self.assertIsNone(unread)
        self.assertIn("caps.t1", values["0.4"])

    def test_a_list_index_is_part_of_the_path(self):
        values, _ = self._values(json.dumps({"bands": [1.0, 30.0]}))
        self.assertIn("bands.[1]", values["30.0"])

    def test_a_flag_is_not_a_threshold(self):
        values, _ = self._values(json.dumps({"enabled": True}))
        self.assertEqual(values, {})

    def test_both_spellings_of_a_whole_number_are_keyed(self):
        """`CAPITAL = 100000` и `100000.0` — одна величина, и обе записи ищутся."""
        values, _ = self._values(json.dumps({"start_capital_usd": 100000}))
        self.assertIn("start_capital_usd", values.get("100000", []))
        self.assertIn("start_capital_usd", values.get("100000.0", []))

    def test_a_missing_shelf_gives_a_reason_not_an_empty_dict(self):
        values, unread = self._values(None)
        self.assertEqual(values, {})
        self.assertIsNotNone(unread)
        self.assertIn(rsc.CONSTITUTION_FILE, unread)

    def test_a_broken_shelf_names_the_error(self):
        values, unread = self._values("{ не json")
        self.assertEqual(values, {})
        self.assertIn("JSONDecodeError", unread)


class TheReportSpeaksTheNumbers(unittest.TestCase):
    """У числа обязан быть читатель, и молчание обязано быть НАЗВАНО."""

    def _lines(self, doc):
        return "\n".join(rsc.report(doc))

    def test_the_intersection_line_carries_the_histograms(self):
        text = self._lines(_measure(_BOTH_AXES))
        self.assertIn("[ПЕРЕСЕЧЕНИЕ ОСЕЙ]", text)
        self.assertIn("'1': 1", text)
        self.assertIn("'2': 1", text)

    def test_the_triple_line_carries_pairs_and_names(self):
        text = self._lines(_measure(_THREE_COPIES))
        self.assertIn("[ТРИ КОПИИ] сторож × два исполнителя 1 пар(ы) на 1 имён(и)", text)

    def test_a_document_without_the_intersection_says_so(self):
        doc = _measure(_THREE_COPIES)
        doc.pop("axes_intersection")
        self.assertIn("[ПЕРЕСЕЧЕНИЕ ОСЕЙ] НЕ ИЗМЕРЕНО", self._lines(doc))

    def test_a_document_without_the_third_axis_says_so(self):
        doc = _measure(_THREE_COPIES)
        doc.pop("triple_counts")
        self.assertIn("[ТРИ КОПИИ] НЕ ИЗМЕРЕНЫ", self._lines(doc))

    def test_truncation_is_declared_with_both_numbers(self):
        doc = _measure(_THREE_COPIES)
        doc["triple_rows"] = doc["triple_rows"] * 3
        text = "\n".join(rsc.report(doc, max_rows=1))
        self.assertIn("показаны 1 тройки из 3", text)

    def test_an_unmeasured_row_is_printed_with_its_reason(self):
        doc = _measure(_THREE_COPIES)
        doc["triple_rows"] = [{"verdict": rsc.CLASS_TRIPLE_UNMEASURED,
                               "name": "LIMIT", "guard": "spa_core/tests/test_x.py",
                               "reason": "текст сторожа не перечитан"}]
        self.assertIn("[НЕ ИЗМЕРЕНО] LIMIT", self._lines(doc))

    def test_the_absence_of_a_ratchet_is_said_aloud(self):
        """Остаток G52 п. 2: рост числа не сторожит никто, и это НАЗВАНО."""
        self.assertIn("храповика у этого числа сегодня НЕТ",
                      self._lines(_measure(_THREE_COPIES)))

    def test_the_office_rendering_truncates_but_keeps_the_head(self):
        lines = rsc.format_report(_measure(_THREE_COPIES), max_rows=5)
        self.assertTrue(any("[ТРИ КОПИИ]" in line for line in lines))

    def test_what_it_does_not_prove_names_the_structural_zero(self):
        doc = _measure(_THREE_COPIES)
        self.assertTrue(any("ПО ПОСТРОЕНИЮ" in line
                            for line in doc["what_it_does_not_prove"]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
