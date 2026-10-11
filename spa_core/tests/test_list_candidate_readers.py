"""ТРЕТЬЯ ось кандидата — число РАЗНЫХ ЧИТАТЕЛЕЙ (заказ G114 пп. 1, 2).

Заказ (хвост [ADR-540](../../docs/decisions/ADR-540-a-pair-of-numbers-cannot-be-the-rule.md)):

> «1. **Третья ось у кандидата — ЧИСЛО РАЗНЫХ ЧИТАТЕЛЕЙ, а не число списков.**
>  Население сегодня считает списки; `message×3` может означать три находки
>  одного прибора и три разных подсистемы, и это разные свидетельства.
>  Замерить, у скольких имён население собрано из одного читателя, — и только
>  после замера решать, нужна ли ось.
>  2. **Класс совпадения — предмет, а не побочный счёт.** Замерить, сколько
>  классов РАСПАДАЕТСЯ, если в координату добавить третью ось из п. 1.»

## Что здесь мерится и чего мерить нельзя

Предмет батареи — ПРИБОР, а не сегодняшнее население: числа живого артефакта
меняются со скоростью кода (урок ADR-540, где пример самой сильной улики
подвинулся за одиннадцать часов), поэтому сцены здесь — фикстуры с явными
числами, и ни одна не читает живое `data/`.

Контроль у каждого утверждения двусторонний: порванное звено краснеет, целое
проходит. Отдельно проверяется то, что легко подменить и трудно заметить:

* **третий исход** у имени, у класса и у самой оси — назван и ОТЛИЧИМ от нуля
  (инв. #17); проверка требует РАЗНЫХ причин, иначе мутант, подменивший причину
  одной ветки причиной другой, выжил бы;
* **население оси = население списков**: вклад записывается там же и тем же
  условием, что инкремент населения, и мутант, расширивший условие, обязан
  краснеть на СИНГЛТОНЕ, который в население не входит;
* **«освобождено» ≠ «класс распался»**: имя, ушедшее в группу из двух,
  различимо лишь от половины класса; мутант, считающий освобождёнными всех
  членов распавшегося класса, умирает на классе из трёх имён;
* **состав ключей — ДОСЛОВНО** (урок #832): сверка документа самого с собой
  переживает переименование ключа.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import copy
import importlib.util
import inspect
import unittest
from pathlib import Path

from spa_core.monitoring import field_readers
from spa_core.monitoring import list_identity_census as census
from spa_core.tests._freshness import ts

REPO = Path(__file__).resolve().parents[2]
OFFICE = REPO / "scripts" / "consume_office_reports.py"
ARTIFACT_REL = "data/list_identity_census.json"


def _office():
    spec = importlib.util.spec_from_file_location("_office_readers", OFFICE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _grid(freq, strength):
    """Сетка — НАСТОЯЩАЯ: классы совпадения берутся у неё, а не из головы."""
    return census.threshold_grid(freq, strength)


def _axis(freq, strength, readers, grid=None):
    return census.reader_axis(freq, strength, readers,
                              grid if grid is not None else _grid(freq, strength))


def _readers(**spec) -> dict:
    """``alpha=["m.one", "m.two"]`` → свод читателей в форме правила."""
    return field_readers.tally_readers(
        [(field, module) for field, mods in spec.items() for module in mods])


class TheRuleOfCountingReadersHasOneCopyAndThreeOutcomes(unittest.TestCase):
    """Правило живёт в `field_readers`; его третий исход СЧИТАЕТСЯ, не теряется."""

    def test_one_reader_with_many_lists_is_still_one_reader(self):
        tally = _readers(alpha=["m.one", "m.one", "m.one"])
        self.assertEqual(tally["alpha"]["readers"], ["m.one"])
        self.assertEqual(field_readers.readers_of(tally, "alpha"), 1)

    def test_many_readers_are_counted_once_each(self):
        tally = _readers(alpha=["m.two", "m.one", "m.two"])
        self.assertEqual(tally["alpha"]["readers"], ["m.one", "m.two"])
        self.assertEqual(field_readers.readers_of(tally, "alpha"), 2)

    def test_an_unnamed_reader_is_counted_not_dropped(self):
        tally = field_readers.tally_readers([("alpha", "m.one"),
                                             ("alpha", None)])
        self.assertEqual(tally["alpha"]["readers"], ["m.one"])
        self.assertEqual(tally["alpha"][field_readers.NAMELESS_KEY], 1)

    def test_a_lower_bound_is_not_a_measurement(self):
        """Есть безымянные вклады ⇒ число читателей НЕ ИЗМЕРЕНО, а не «один»."""
        tally = field_readers.tally_readers([("alpha", "m.one"),
                                             ("alpha", "")])
        self.assertIsNone(field_readers.readers_of(tally, "alpha"))

    def test_positive_control_without_the_nameless_counter_the_bound_passes(self):
        """Контроль на сам счётчик: убери его — заниженное число станет замером."""
        tally = field_readers.tally_readers([("alpha", "m.one"),
                                             ("alpha", None)])
        tally["alpha"].pop(field_readers.NAMELESS_KEY)
        self.assertEqual(field_readers.readers_of(tally, "alpha"), 1,
                         "без счётчика нижняя граница неотличима от замера — "
                         "ровно поэтому он и считается")

    def test_a_field_nobody_supported_is_unmeasured_not_zero(self):
        self.assertIsNone(field_readers.readers_of(_readers(alpha=["m.one"]),
                                                   "beta"))

    def test_the_reader_list_is_sorted_so_the_artifact_is_byte_stable(self):
        self.assertEqual(_readers(alpha=["m.z", "m.a"])["alpha"]["readers"],
                         ["m.a", "m.z"])

    def test_the_name_of_the_third_outcome_is_pinned_verbatim(self):
        self.assertEqual(field_readers.NAMELESS_KEY, "nameless")

    def test_the_keys_of_a_row_are_pinned_verbatim(self):
        self.assertEqual(set(_readers(alpha=["m.one"])["alpha"]),
                         {"readers", "nameless"})


class TheAxisAnswersTheOrdersQuestionWithANumber(unittest.TestCase):
    """«У скольких имён население собрано из ОДНОГО читателя» — число рядом."""

    def test_the_three_outcomes_of_a_name_partition_the_names(self):
        axis = _axis({"alpha": 2, "beta": 2, "gamma": 2},
                     {"alpha": 9, "beta": 8, "gamma": 7},
                     field_readers.tally_readers(
                         [("alpha", "m.one"), ("alpha", "m.one"),
                          ("beta", "m.one"), ("beta", "m.two"),
                          ("gamma", "m.one"), ("gamma", None)]))
        self.assertEqual(axis["single_reader_names"], ["alpha"])
        self.assertEqual(axis["multi_reader_names"], ["beta"])
        self.assertEqual([row["field"] for row in axis["readers_unmeasured"]],
                         ["gamma"])
        # Перечень ЗАКРЫТ: сумма трёх исходов равна числу имён, и имя не может
        # исчезнуть из всех трёх молча.
        self.assertEqual(
            len(axis["single_reader_names"]) + len(axis["multi_reader_names"])
            + len(axis["readers_unmeasured"]), axis["names"])

    def test_population_above_one_at_a_single_reader_is_named(self):
        """ВОТ ответ заказа: ×N у одного прибора — не N свидетельств."""
        axis = _axis({"alpha": 11}, {"alpha": 7}, _readers(alpha=["m.one"] * 11))
        self.assertEqual(axis["population_overstated"],
                         [{"field": "alpha", "population": 11, "readers": 1}])

    def test_population_above_one_at_two_readers_is_not_named(self):
        """Обратная сторона: ширина есть ⇒ в находку имя не идёт."""
        axis = _axis({"alpha": 11}, {"alpha": 7},
                     _readers(alpha=["m.one"] * 10 + ["m.two"]))
        self.assertEqual(axis["population_overstated"], [])

    def test_a_singleton_population_is_not_called_overstated(self):
        """×1 у одного читателя — не завышение: завышать там нечего."""
        axis = _axis({"alpha": 1}, {"alpha": 7}, _readers(alpha=["m.one"]))
        self.assertEqual(axis["single_reader_names"], ["alpha"])
        self.assertEqual(axis["population_overstated"], [])

    def test_the_boundary_of_the_finding_is_population_two(self):
        """×2 у одного читателя УЖЕ завышение: порог стои́т на двух, не на трёх."""
        axis = _axis({"alpha": 2}, {"alpha": 7}, _readers(alpha=["m.one"] * 2))
        self.assertEqual(axis["population_overstated"],
                         [{"field": "alpha", "population": 2, "readers": 1}])

    def test_a_name_with_unmeasured_readers_carries_its_own_cause(self):
        axis = _axis({"alpha": 2}, {"alpha": 7},
                     field_readers.tally_readers([("alpha", "m.one"),
                                                  ("alpha", None)]))
        why = axis["readers_unmeasured"][0]["why"]
        self.assertIn("вкладов без названного читателя: 1", why)
        # ЧИСЛО названных читателей — часть причины: нижняя граница без её
        # величины не есть наблюдение. Мутант, читающий здесь не тот ключ,
        # напечатал бы «названных читателей 0» при одном названном.
        self.assertIn("названных читателей 1", why)
        self.assertIn("нижняя граница", why)

    def test_a_row_carries_the_readers_by_name_and_the_flag(self):
        axis = _axis({"alpha": 2, "beta": 2}, {"alpha": 9, "beta": 8},
                     field_readers.tally_readers(
                         [("alpha", "m.two"), ("alpha", "m.one"),
                          ("beta", None)]))
        alpha = next(r for r in axis["rows"] if r["field"] == "alpha")
        beta = next(r for r in axis["rows"] if r["field"] == "beta")
        self.assertEqual(alpha["reader_names"], ["m.one", "m.two"])
        self.assertEqual(alpha["readers"], 2)
        self.assertIs(alpha["readers_unmeasured"], False)
        self.assertIsNone(beta["readers"])
        self.assertIs(beta["readers_unmeasured"], True)
        self.assertEqual(beta["contributions_nameless"], 1)

    def test_the_two_unmeasured_causes_of_a_name_differ(self):
        """Мутант, подменивший одну причину другой, обязан краснеть."""
        with_nameless = _axis({"alpha": 2}, {"alpha": 7},
                              field_readers.tally_readers(
                                  [("alpha", None), ("alpha", None)]))
        no_contribution = _axis({"alpha": 2}, {"alpha": 7}, {})
        self.assertNotEqual(with_nameless["readers_unmeasured"][0]["why"],
                            no_contribution["readers_unmeasured"][0]["why"])
        self.assertIn("ни одного вклада",
                      no_contribution["readers_unmeasured"][0]["why"])

    def test_the_rows_follow_the_same_order_as_the_candidate_list(self):
        """Порядок — ОДНОЙ копией: голова всех перечней обязана совпадать."""
        freq, strength = {"alpha": 9, "beta": 1}, {"alpha": 2, "beta": 93}
        axis = _axis(freq, strength, _readers(alpha=["m.one"], beta=["m.two"]))
        self.assertEqual([row["field"] for row in axis["rows"]],
                         [name for name, _ in
                          census._ranked_by_length(freq, strength)])
        self.assertEqual(axis["rows"][0]["field"], "beta")


class TheAxisVerdictIsComputedNotDeclared(unittest.TestCase):
    """«Только после замера решать, нужна ли ось» — вердикт из наблюдений."""

    def test_neither_condition_present_means_the_axis_is_not_needed(self):
        axis = _axis({"alpha": 1}, {"alpha": 7}, _readers(alpha=["m.one"]))
        self.assertEqual(axis["axis_verdict"], "NOT_NEEDED")
        self.assertEqual(axis["axis_verdict_reasons"], [])

    def test_an_overstated_population_alone_makes_the_axis_needed(self):
        axis = _axis({"alpha": 11}, {"alpha": 7}, _readers(alpha=["m.one"] * 11))
        self.assertEqual(axis["axis_verdict"], "NEEDED")
        self.assertEqual(len(axis["axis_verdict_reasons"]), 1)
        self.assertIn("читатель ОДИН", axis["axis_verdict_reasons"][0])

    def test_a_split_class_alone_makes_the_axis_needed(self):
        """Ни одного завышенного населения — вердикт держит ТОЛЬКО класс."""
        axis = _axis({"alpha": 1, "beta": 1}, {"alpha": 7, "beta": 7},
                     _readers(alpha=["m.one"], beta=["m.one", "m.two"]))
        self.assertEqual(axis["population_overstated"], [])
        self.assertEqual(axis["axis_verdict"], "NEEDED")
        # Причина несёт ТРИ числа, и каждое читается своим ключом: распавшиеся,
        # всего и освобождённые. Мутант, подменивший любой из ключей, печатает
        # вместо числа `None`, и проверка по одному числу его пропускала.
        self.assertIn("РАЗБИВАЕТ 1 из 1", axis["axis_verdict_reasons"][0])
        self.assertIn("различимыми 2 имён", axis["axis_verdict_reasons"][0])

    def test_the_strongest_overstated_name_is_the_one_printed(self):
        """Представитель выбран не на глаз: он сильнейший по населению."""
        axis = _axis({"alpha": 3, "beta": 11}, {"alpha": 7, "beta": 7},
                     _readers(alpha=["m.one"] * 3, beta=["m.two"] * 11))
        self.assertIn("beta×11", axis["axis_verdict_reasons"][0])


class TheClassOfCoincidenceIsTheSubject(unittest.TestCase):
    """Заказ G114 п. 2: сколько классов РАСПАДАЕТСЯ от третьего числа."""

    def test_a_class_splits_when_the_reader_counts_differ(self):
        axis = _axis({"alpha": 1, "beta": 1}, {"alpha": 7, "beta": 7},
                     _readers(alpha=["m.one"], beta=["m.one", "m.two"]))
        classes = axis["classes"]
        self.assertEqual(classes["classes_total"], 1)
        self.assertEqual(classes["classes_split"], 1)
        self.assertEqual(classes["classes_intact"], 0)
        self.assertEqual(classes["names_freed"], ["alpha", "beta"])
        self.assertEqual(classes["names_still_blind"], [])
        # Строка класса — ДОСЛОВНО: координата, состав, вердикт и раскладка по
        # читателям. Сверка «класс распался» по одному счётчику не замечает,
        # что строка потеряла координату или назвала не тех.
        self.assertEqual(classes["rows"], [{
            "population": 1, "max_length": 7, "names": ["alpha", "beta"],
            "readers_by_name": {"alpha": 1, "beta": 2},
            "groups": [["alpha"], ["beta"]], "verdict": "split",
            "names_freed": ["alpha", "beta"]}])

    def test_a_class_stays_intact_when_every_name_has_one_reader(self):
        """И ТОГДА слепое пятно остаётся — отдельным числом, а не молчанием."""
        axis = _axis({"alpha": 1, "beta": 1}, {"alpha": 7, "beta": 7},
                     _readers(alpha=["m.one"], beta=["m.two"]))
        classes = axis["classes"]
        self.assertEqual(classes["classes_split"], 0)
        self.assertEqual(classes["classes_intact"], 1)
        self.assertEqual(classes["names_freed"], [])
        self.assertEqual(classes["names_still_blind"], ["alpha", "beta"])
        self.assertEqual(classes["rows"][0]["verdict"], "intact")
        self.assertEqual(classes["rows"][0]["groups"], [["alpha", "beta"]])

    def test_only_a_name_alone_in_its_group_is_called_freed(self):
        """Класс из трёх: одно имя различимо от всех, два — лишь от него."""
        axis = _axis({"alpha": 1, "beta": 1, "gamma": 1},
                     {"alpha": 7, "beta": 7, "gamma": 7},
                     _readers(alpha=["m.one"], beta=["m.one"],
                              gamma=["m.one", "m.two"]))
        classes = axis["classes"]
        self.assertEqual(classes["classes_split"], 1)
        self.assertEqual(classes["names_freed"], ["gamma"])
        self.assertEqual(classes["names_still_blind"], ["alpha", "beta"])

    def test_a_class_with_an_unmeasured_member_is_neither_split_nor_intact(self):
        axis = _axis({"alpha": 1, "beta": 1}, {"alpha": 7, "beta": 7},
                     field_readers.tally_readers([("alpha", "m.one"),
                                                  ("beta", None)]))
        classes = axis["classes"]
        self.assertEqual(classes["classes_unmeasured"], 1)
        self.assertEqual(classes["classes_split"], 0)
        self.assertEqual(classes["classes_intact"], 0)
        # Строка ТРЕТЬЕГО исхода — тоже дословно, и состав её ключей СВОЙ:
        # раскладки по читателям в ней нет (её и мерить нечем), а причина есть.
        self.assertEqual(classes["rows"], [{
            "population": 1, "max_length": 7, "names": ["alpha", "beta"],
            "verdict": "unmeasured",
            "why": "у имени класса число читателей не измерено"}])
        self.assertIn("не измерено", classes["rows"][0]["why"])

    def test_classes_are_taken_from_the_grid_not_recounted(self):
        """Пара имён с РАЗНОЙ координатой класса не образует — и его нет."""
        axis = _axis({"alpha": 1, "beta": 2}, {"alpha": 7, "beta": 9},
                     _readers(alpha=["m.one"], beta=["m.two"]))
        self.assertEqual(axis["classes"]["classes_total"], 0)
        self.assertEqual(axis["classes"]["names_still_blind"], [])

    def test_a_grid_that_was_not_measured_leaves_the_classes_unmeasured(self):
        axis = _axis({"alpha": 2}, {"alpha": 7}, _readers(alpha=["m.one"]),
                     grid={"status": "UNMEASURED", "reason": "кандидатов нет"})
        self.assertEqual(axis["status"], "MEASURED")
        self.assertEqual(axis["classes"]["status"], "UNMEASURED")
        self.assertIn("не из чего брать", axis["classes"]["reason"])

    def test_a_grid_without_a_collision_list_is_unmeasured_not_empty(self):
        grid = _grid({"alpha": 1, "beta": 1}, {"alpha": 7, "beta": 7})
        grid.pop("collisions")
        axis = _axis({"alpha": 1, "beta": 1}, {"alpha": 7, "beta": 7},
                     _readers(alpha=["m.one"], beta=["m.two"]), grid=grid)
        self.assertEqual(axis["classes"]["status"], "UNMEASURED")
        self.assertIn("перечня классов совпадения", axis["classes"]["reason"])


class TheAxisItselfHasThreeOutcomes(unittest.TestCase):
    """Третий исход у ОСИ отличим от нуля и от исхода соседней ветки."""

    def test_no_candidates_is_not_one_reader_everywhere(self):
        axis = _axis({}, {}, {})
        self.assertEqual(axis["status"], "UNMEASURED")
        self.assertIn("кандидатов нет", axis["reason"])

    def test_no_reader_tally_at_all_is_not_one_reader_everywhere(self):
        axis = census.reader_axis({"alpha": 2}, {"alpha": 7}, None, {})
        self.assertEqual(axis["status"], "UNMEASURED")
        self.assertIn("свода читателей нет", axis["reason"])

    def test_the_two_refusals_of_the_axis_differ(self):
        self.assertNotEqual(
            _axis({}, {}, {})["reason"],
            census.reader_axis({"alpha": 2}, {"alpha": 7}, None, {})["reason"])


class TheReportPrintsTheNumberBesideItsDenominator(unittest.TestCase):

    AXIS = None

    def setUp(self):
        self.AXIS = _axis(
            {"alpha": 11, "beta": 1, "gamma": 1},
            {"alpha": 7, "beta": 7, "gamma": 7},
            _readers(alpha=["m.one"] * 11, beta=["m.one"],
                     gamma=["m.one", "m.two"]))

    def test_it_prints_both_halves_of_the_question(self):
        text = "\n".join(census.reader_axis_report(self.AXIS))
        self.assertIn("имён 3", text)
        self.assertIn("из ОДНОГО читателя у 2", text)
        self.assertIn("из нескольких у 1", text)

    def test_it_prints_the_overstated_population_by_name(self):
        text = "\n".join(census.reader_axis_report(self.AXIS))
        self.assertIn("НАСЕЛЕНИЕ НАЗЫВАЕТ ШИРИНОЙ НЕ ШИРИНУ: ", text)
        self.assertIn("alpha×11 списк. у ОДНОГО читателя", text)

    def test_it_joins_the_overstated_names_into_one_line(self):
        """Разделитель — часть строки: без него два имени склеятся в одно."""
        axis = _axis({"alpha": 11, "beta": 3}, {"alpha": 7, "beta": 7},
                     _readers(alpha=["m.one"] * 11, beta=["m.two"] * 3))
        self.assertIn("alpha×11 списк. у ОДНОГО читателя · beta×3 списк. у "
                      "ОДНОГО читателя",
                      "\n".join(census.reader_axis_report(axis)))

    def test_nothing_overstated_is_said_aloud_about_THIS_answer(self):
        """Пустая находка — утверждение об ЭТОМ ответе, а не молчание."""
        axis = _axis({"alpha": 1}, {"alpha": 7}, _readers(alpha=["m.one"]))
        self.assertIn("ширину свидетельства не завышает",
                      "\n".join(census.reader_axis_report(axis)))

    def test_an_unmeasured_class_row_prints_its_why_not_a_reader_map(self):
        axis = _axis({"alpha": 1, "beta": 1}, {"alpha": 7, "beta": 7},
                     field_readers.tally_readers([("alpha", "m.one"),
                                                  ("beta", None)]))
        text = "\n".join(census.reader_axis_report(axis))
        self.assertIn("(1, 7) unmeasured: alpha, beta — у имени класса число "
                      "читателей не измерено", text)

    def test_a_class_row_without_its_names_says_so_instead_of_printing_none(self):
        axis = _axis({"alpha": 1, "beta": 1}, {"alpha": 7, "beta": 7},
                     _readers(alpha=["m.one"], beta=["m.one", "m.two"]))
        axis["classes"]["rows"][0].pop("names")
        self.assertIn("состав класса НЕ ИЗМЕРЕН",
                      "\n".join(census.reader_axis_report(axis)))

    def test_it_joins_the_per_name_rows_into_one_line(self):
        text = "\n".join(census.reader_axis_report(self.AXIS))
        self.assertIn("alpha×11 у 1 читател. · beta×1 у 1 читател.", text)

    def test_it_prints_the_class_numbers_not_just_their_label(self):
        """Метка без числа — украшение: подмена ключа печатает `None`."""
        text = "\n".join(census.reader_axis_report(self.AXIS))
        self.assertIn("классов совпадающей координаты 1 ⇒ РАСПАЛОСЬ 1 · цело 0 "
                      "· НЕ ИЗМЕРЕНО 0", text)

    def test_it_prints_how_many_names_stay_blind(self):
        """Ось НЕ закрывает слепое пятно, и это напечатано числом."""
        text = "\n".join(census.reader_axis_report(self.AXIS))
        self.assertIn("различимыми стали 2 имён, СЛЕПЫМИ ОСТАЛИСЬ 0", text)

    def test_it_prints_the_split_class_row_and_hides_the_intact_one(self):
        """Печатается то, что РАСПАЛОСЬ; целый класс в хвост отчёта не идёт."""
        axis = _axis({"alpha": 1, "beta": 1, "delta": 2, "eps": 2},
                     {"alpha": 7, "beta": 7, "delta": 5, "eps": 5},
                     _readers(alpha=["m.one"], beta=["m.one", "m.two"],
                              delta=["m.one", "m.one"], eps=["m.two", "m.two"]))
        text = "\n".join(census.reader_axis_report(axis))
        self.assertIn("(1, 7) split: alpha, beta ⇒ читателей "
                      "{'alpha': 1, 'beta': 2}", text)
        self.assertNotIn("delta, eps", text.split("КЛАССЫ")[-1]
                         .split("поимённо")[0])

    def test_it_prints_the_per_name_line_with_both_numbers(self):
        text = "\n".join(census.reader_axis_report(self.AXIS))
        self.assertIn("поимённо (порядок — тот же, что у перечня кандидатов): ",
                      text)
        self.assertIn("alpha×11 у 1 читател.", text)
        self.assertIn("gamma×1 у 2 читател.", text)

    def test_an_unmeasured_name_is_printed_as_such_not_as_a_count(self):
        axis = _axis({"alpha": 2}, {"alpha": 7},
                     field_readers.tally_readers([("alpha", "m.one"),
                                                  ("alpha", None)]))
        text = "\n".join(census.reader_axis_report(axis))
        self.assertIn("alpha×2 у НЕ ИЗМЕРЕНО", text)
        self.assertIn("НЕ ИЗМЕРЕНО у alpha: вкладов без названного читателя: 1",
                      text)

    def test_an_unmeasured_axis_prints_its_cause_not_zeros(self):
        text = "\n".join(census.reader_axis_report(_axis({}, {}, {})))
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertIn("кандидатов нет", text)
        self.assertNotIn("из ОДНОГО читателя у 0", text)

    def test_an_absent_fold_is_said_aloud(self):
        self.assertIn("свода нет вовсе",
                      "\n".join(census.reader_axis_report({})))

    def test_a_fold_without_its_three_outcomes_is_unmeasured(self):
        axis = copy.deepcopy(self.AXIS)
        axis.pop("single_reader_names")
        self.assertIn("не назвал все три исхода",
                      "\n".join(census.reader_axis_report(axis)))

    def test_a_fold_without_the_count_of_names_is_unmeasured(self):
        """`or 0` здесь напечатал бы «имён 0» на своде, который молчит."""
        axis = copy.deepcopy(self.AXIS)
        axis.pop("names")
        lines = census.reader_axis_report(axis)
        self.assertIn("скольким именам", lines[0])
        # Сама строка отказа произносит «имён 0» в кавычках — как то, чего быть
        # не должно. Поэтому мерится ГОЛОВА отчёта: её не существует.
        self.assertFalse(any(
            line.startswith("ось ЧИТАТЕЛЕЙ (заказ G114 п. 1): имён 0")
            for line in lines))

    def test_each_absent_section_of_the_fold_has_its_OWN_cause(self):
        """Четыре разных пропажи — четыре разных ответа, а не один на всех."""
        said = {}
        for key in ("population_overstated", "classes", "rows"):
            axis = copy.deepcopy(self.AXIS)
            axis.pop(key)
            said[key] = "\n".join(census.reader_axis_report(axis))
        self.assertIn("перечня имён с завышенным населением",
                      said["population_overstated"])
        self.assertIn("раздела классов в своде", said["classes"])
        self.assertIn("поимённых строк оси в своде", said["rows"])
        self.assertEqual(len(set(said.values())), 3)

    def test_a_class_fold_without_its_lists_is_unmeasured_not_zero(self):
        for key, needle in (("names_freed", "какие имена стали различимыми"),
                            ("names_still_blind", "какие имена стали различимыми"),
                            ("rows", "поимённых строк классов")):
            axis = copy.deepcopy(self.AXIS)
            axis["classes"].pop(key)
            text = "\n".join(census.reader_axis_report(axis))
            self.assertIn(needle, text)
            self.assertNotIn("СЛЕПЫМИ ОСТАЛИСЬ 0", text.split("поимённо")[0]
                             if key != "rows" else "")

    def test_an_unmeasured_class_fold_prints_its_reason(self):
        axis = _axis({"alpha": 2}, {"alpha": 7}, _readers(alpha=["m.one"]),
                     grid={"status": "UNMEASURED", "reason": "сетки нет"})
        # Причина — СВОЯ, а не пересказ чужой: отказывает тут свод классов, и
        # он называет, чего не может именно он.
        self.assertIn("КЛАССЫ (G114 п. 2) · НЕ ИЗМЕРЕНО: сетки пары чисел нет "
                      "или она не измерена",
                      "\n".join(census.reader_axis_report(axis)))

    def test_shortening_cuts_the_per_name_list_and_says_so(self):
        text = "\n".join(census.reader_axis_report(self.AXIS, max_rows=1))
        self.assertIn("ещё 2", text)

    def test_shortening_never_hides_the_finding(self):
        """Укорочение режет поимённый перечень, а не находку заказа."""
        text = "\n".join(census.reader_axis_report(self.AXIS, max_rows=1))
        self.assertIn("alpha×11 списк. у ОДНОГО читателя", text)
        self.assertIn("СЛЕПЫМИ ОСТАЛИСЬ", text)

    def test_the_verdict_is_printed_with_its_reasons(self):
        text = "\n".join(census.reader_axis_report(self.AXIS))
        self.assertIn("ВЕРДИКТ ОСИ (вычислен, не объявлен): NEEDED", text)
        self.assertIn("читатель ОДИН", text)

    def test_a_verdict_without_reasons_says_which_population_refused_it(self):
        axis = _axis({"alpha": 1}, {"alpha": 7}, _readers(alpha=["m.one"]))
        text = "\n".join(census.reader_axis_report(axis))
        self.assertIn("NOT_NEEDED", text)
        self.assertIn("ни одно из двух условий", text)

    def test_reasons_absent_and_reasons_empty_are_different_answers(self):
        """Пустой перечень = вердикт NOT_NEEDED; отсутствие = нет замера."""
        axis = copy.deepcopy(self.AXIS)
        axis.pop("axis_verdict_reasons")
        text = "\n".join(census.reader_axis_report(axis))
        self.assertIn("перечня причин у вердикта нет вовсе", text)
        self.assertNotIn("ни одно из двух условий", text)


class TheAxisStandsOnTheSamePopulationAsTheListAxis(unittest.TestCase):
    """Два числа одной координаты обязаны говорить об ОДНОМ предмете."""

    ROWS = {
        "m.one": {"lists": [
            {"coord": ".items", "n": 9, "outcome": "unnamed_candidate_outside",
             "candidates": ["alpha"]},
            {"coord": ".pair", "n": 2, "outcome": "unnamed_candidate_outside",
             "candidates": ["alpha"]},
        ]},
        "m.two": {"lists": [
            # СИНГЛТОН: в население не входит (годность тривиальна), значит и
            # читателем этого имени `m.two` не становится. Мутант, записавший
            # вклад вне условия населения, краснеет ЗДЕСЬ.
            {"coord": ".one", "n": 1, "outcome": "unnamed_candidate_outside",
             "candidates": ["alpha"]},
            # Список, НАЗВАВШИЙ себя полем: кандидата не даёт вовсе.
            {"coord": ".named", "n": 5, "outcome": "named", "field": "protocol"},
        ]},
    }

    def test_the_tally_carries_both_the_readers_and_the_axis(self):
        counts = census.tally(self.ROWS)
        self.assertEqual(counts["candidate_readers"]["alpha"]["readers"],
                         ["m.one"])
        self.assertEqual(counts["candidate_reader_axis"]["status"], "MEASURED")

    def test_a_singleton_does_not_make_its_module_a_reader(self):
        counts = census.tally(self.ROWS)
        self.assertEqual(counts["candidate_fields_outside"], {"alpha": 2})
        self.assertNotIn("m.two",
                         counts["candidate_readers"]["alpha"]["readers"])

    def test_the_reader_count_never_exceeds_the_population(self):
        counts = census.tally(self.ROWS)
        for name, population in counts["candidate_fields_outside"].items():
            seen = field_readers.readers_of(counts["candidate_readers"], name)
            self.assertIsNotNone(seen)
            self.assertLessEqual(seen, population)

    def test_the_census_report_prints_the_reader_block(self):
        counts = census.tally(self.ROWS)
        doc = {"status": "FINDING", "counts": counts, "advisory": "ЧИТАЕТ",
               "invoked_by": None, "generated_at": ts(hours_ago=1)}
        text = "\n".join(census.report(doc))
        self.assertIn("[ЧИТАТЕЛИ] ось ЧИТАТЕЛЕЙ", text)
        self.assertLess(text.index("[НАХОДКА]"), text.index("[ЧИТАТЕЛИ]"),
                        "число читателей напечатано не рядом с населением")

    def test_a_document_without_the_section_is_called_old_not_empty(self):
        counts = census.tally(self.ROWS)
        counts.pop("candidate_reader_axis")
        doc = {"status": "FINDING", "counts": counts, "advisory": "ЧИТАЕТ",
               "invoked_by": None, "generated_at": ts(hours_ago=1)}
        block = [line for line in census.report(doc) if "[ЧИТАТЕЛИ]" in line]
        self.assertEqual(len(block), 1)
        self.assertIn("СТАРОГО ОБРАЗЦА", block[0])

    def test_the_block_is_printed_even_without_candidates(self):
        """Кандидатов нет ⇒ ось говорит это САМА, а не исчезает из отчёта."""
        counts = census.tally({"m.two": self.ROWS["m.two"]})
        doc = {"status": "CLEAN", "counts": counts, "advisory": "ЧИТАЕТ",
               "invoked_by": None, "generated_at": ts(hours_ago=1)}
        text = "\n".join(census.report(doc))
        self.assertIn("[ЧИТАТЕЛИ]", text)
        self.assertIn("кандидатов нет", text)


class TheOfficeReadsTheSection(unittest.TestCase):
    """ADR-333: проводка мерится ВЫЗОВОМ на живом документе, не наличием строки."""

    @staticmethod
    def _doc() -> dict:
        counts = census.tally(TheAxisStandsOnTheSamePopulationAsTheListAxis.ROWS)
        return {
            "schema": census.SCHEMA, "status": "FINDING",
            # Отметка ОТНОСИТЕЛЬНАЯ: литеральная дата здесь была бы бомбой —
            # она выпала бы из окна свежести от хода календаря, а не от кода.
            # Часы инъектировать некуда: отметку читает чужой шаг 0-офис.
            "generated_at": ts(hours_ago=1),
            "reason": "списков без личности с годным полем ВНЕ списка имён: 2",
            "advisory": "прибор только ЧИТАЕТ",
            "invoked_by": {"schema": "call_provenance.v1", "measured": True,
                           "entry": "spa_core/monitoring/findings_bridge.py",
                           "inside_tree": True, "doors_agree": True,
                           "read_by": "sys.modules['__main__'].__file__"},
            "counts": counts,
        }

    def test_the_office_declares_the_section_as_read(self):
        declared = _office()._READ_SCHEMA["list_identity_census.json"]
        self.assertIn("counts.candidate_reader_axis", declared)

    def test_the_office_prints_the_axis_beside_the_candidate(self):
        office = _office()
        lines = office._summarize_json(ARTIFACT_REL, self._doc(),
                                       root=str(REPO), artifact_root=str(REPO))
        text = "\n".join(lines)
        # РАЗЛИЧИМОСТЬ сцены, а не только исход (урок #786): метка `[ЧИТАТЕЛИ]`
        # стои́т и в сообщении «СТАРОГО ОБРАЗЦА», поэтому сцена требует того,
        # что печатает ТОЛЬКО измеренный раздел.
        self.assertIn("[ЧИТАТЕЛИ] ось ЧИТАТЕЛЕЙ (заказ G114 п. 1)", text)
        self.assertIn("из ОДНОГО читателя у 1", text)
        self.assertFalse(any(l.startswith(office._HOLLOW_MARK) for l in lines))

    def test_the_office_calls_the_axis_old_when_the_section_is_gone(self):
        office = _office()
        doc = self._doc()
        doc["counts"].pop("candidate_reader_axis")
        block = [line for line in
                 office._summarize_json(ARTIFACT_REL, doc, root=str(REPO),
                                        artifact_root=str(REPO))
                 if "[ЧИТАТЕЛИ]" in line]
        self.assertEqual(len(block), 1)
        self.assertIn("СТАРОГО ОБРАЗЦА", block[0])


class TheAxisInstallsNoGate(unittest.TestCase):
    """Заказ велел ЗАМЕРИТЬ ось, а не назначить по ней порог."""

    def test_the_pin_of_public_names_covers_the_reader_axis_too(self):
        for name in ("readers_gate", "admit_by_readers", "reject_by_readers",
                     "fit_by_readers"):
            self.assertIn(name, census._NO_GATE_NAMES)
        public = {name for name in dir(census) if not name.startswith("_")}
        self.assertEqual(public & set(census._NO_GATE_NAMES), set())

    def test_the_axis_takes_no_argument_that_would_select_a_name(self):
        self.assertEqual(set(inspect.signature(census.reader_axis).parameters),
                         {"freq", "strength", "readers", "grid"})

    def test_it_adds_no_name_to_the_identity_fields(self):
        before = tuple(census.probe.IDENTITY_FIELDS)
        _axis({"alpha": 2}, {"alpha": 7}, _readers(alpha=["m.one"]))
        self.assertEqual(tuple(census.probe.IDENTITY_FIELDS), before)

    def test_the_report_says_the_reader_is_a_module_not_a_subsystem(self):
        """Заказ говорит «подсистемы»; измеряются МОДУЛИ, и это сказано."""
        axis = _axis({"alpha": 2}, {"alpha": 7}, _readers(alpha=["m.one"]))
        text = "\n".join(census.reader_axis_report(axis))
        self.assertIn("МОДУЛЬ, а не подсистема", text)
        self.assertIn("ГЕЙТА НЕТ", text)


class TheContractOfTheFoldIsPinnedVerbatim(unittest.TestCase):
    """Состав ключей — литералами: сверка документа с собой переживает мутанта."""

    def test_every_key_of_the_axis_is_pinned(self):
        axis = _axis({"alpha": 2}, {"alpha": 7}, _readers(alpha=["m.one"]))
        self.assertEqual(set(axis), {
            "status", "names", "single_reader_names", "multi_reader_names",
            "readers_unmeasured", "population_overstated", "rows", "classes",
            "axis_verdict", "axis_verdict_reasons", "what_it_does_not_prove"})

    def test_every_key_of_a_row_is_pinned(self):
        axis = _axis({"alpha": 2}, {"alpha": 7}, _readers(alpha=["m.one"]))
        self.assertEqual(set(axis["rows"][0]), {
            "field", "population", "readers", "readers_unmeasured",
            "reader_names", "contributions_nameless"})

    def test_every_key_of_the_classes_fold_is_pinned(self):
        axis = _axis({"alpha": 1, "beta": 1}, {"alpha": 7, "beta": 7},
                     _readers(alpha=["m.one"], beta=["m.two"]))
        self.assertEqual(set(axis["classes"]), {
            "status", "classes_total", "classes_split", "classes_intact",
            "classes_unmeasured", "names_freed", "names_still_blind", "rows"})
        self.assertEqual(set(axis["classes"]["rows"][0]), {
            "population", "max_length", "names", "readers_by_name", "groups",
            "verdict", "names_freed"})

    def test_the_verdict_values_are_pinned(self):
        self.assertEqual(
            _axis({"alpha": 1}, {"alpha": 7},
                  _readers(alpha=["m.one"]))["axis_verdict"], "NOT_NEEDED")
        self.assertEqual(
            _axis({"alpha": 11}, {"alpha": 7},
                  _readers(alpha=["m.one"] * 11))["axis_verdict"], "NEEDED")

    def test_the_limits_of_the_measure_travel_in_the_document(self):
        """Все ЧЕТЫРЕ оговорки — дословно: прочитавший их и есть защита от гейта.

        Проверка по двум словам из четырёх оставляла половину груза без
        контроля — мутант, подменивший третью или четвёртую строку, выживал
        (замер мутаций этого цикла).
        """
        axis = _axis({"alpha": 2}, {"alpha": 7}, _readers(alpha=["m.one"]))
        joined = " ".join(axis["what_it_does_not_prove"])
        self.assertEqual(len(axis["what_it_does_not_prove"]), 4)
        for needle in ("МОДУЛЬ, а не подсистема", "слепое пятно",
                       "наблюдение ОДНОГО ответа",
                       "ни одно имя не дописано в _IDENTITY_FIELDS"):
            self.assertIn(needle, joined)


if __name__ == "__main__":
    unittest.main()
