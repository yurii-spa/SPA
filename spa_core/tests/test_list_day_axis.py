"""Признак «ряд ли это»: день РАЗЛИЧАЕТ элементы — или не различает ничем.

Заказ **G113 п. 2** приказа владельца «Portfolio CIO» (поставлен ADR-539,
02.10), решение — ADR-692.

## Что здесь проверяется, а что НЕТ

Предмет — ОДНО утверждение: совпадает ли множество элементов списка с
множеством дней. Правила «ряд ⇒ годность» в приборе нет, и батарея это
закрепляет СОСТАВОМ публичных имён, а не чтением докстринга: прозаическая
оговорка «гейта нет» ветшает молча, имя — краснеет.

## Почему у каждой проверки есть обратная сторона

Проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`). Поэтому у каждого утверждения здесь стои́т
контроль в обе стороны: отказ ПО НАЗВАННОЙ причине (а не просто «не ряд») и
прохождение целого контура. Дни в фикстурах — ПРЕДМЕТ замера, поэтому они
литеральные; часов прибор не читает ВООБЩЕ, поэтому инъектировать нечего и
календарь хоста на вердикт не влияет ни в одной проверке.
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: сама дата и есть предмет — прибор отвечает на вопрос «эти
# значения суть дни и различны ли они». Часов модуль не читает ни одной дверью
# (ни `datetime.now`, ни `date.today`), поэтому от календаря хоста вердикт не
# зависит по построению, а не по пометке.
from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import unittest
from pathlib import Path

from spa_core.monitoring import list_day_axis as axis
from spa_core.monitoring import list_identity_census as census
from spa_core.monitoring._list_identity_probe import classify_list

REPO = Path(__file__).resolve().parents[2]
OFFICE = REPO / "scripts" / "consume_office_reports.py"


def _office():
    spec = importlib.util.spec_from_file_location("_office_day_axis", OFFICE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _days(*values) -> list:
    return [{"day": v} for v in values]


class DayOfAValue(unittest.TestCase):
    """Значение → день, и у каждого отказа СВОЯ названная причина."""

    def test_an_iso_day_is_a_day(self):
        self.assertEqual(axis.day_of("2026-10-02")[0], dt.date(2026, 10, 2))

    def test_a_real_date_object_is_a_day(self):
        self.assertEqual(axis.day_of(dt.date(2026, 10, 2))[0],
                         dt.date(2026, 10, 2))

    def test_an_aware_stamp_gives_its_UTC_day_and_says_it_is_aware(self):
        day, aware, _ = axis.day_of("2026-10-02T23:30:00+00:00")
        self.assertEqual((day, aware), (dt.date(2026, 10, 2), True))

    def test_a_timezone_can_move_the_day_and_that_is_measured_not_assumed(self):
        """Тот же ИНСТАНТ в другом поясе — другой календарный день.

        Утверждение прибора («день по UTC») проверяется на паре, где выбор
        соглашения ВИДЕН: без приведения к UTC день был бы 3-м числом.
        """
        day, aware, _ = axis.day_of("2026-10-03T01:00:00+03:00")
        self.assertEqual((day, aware), (dt.date(2026, 10, 2), True))

    def test_a_naive_stamp_is_taken_as_written_and_is_not_called_aware(self):
        day, aware, _ = axis.day_of("2026-10-02T23:30:00")
        self.assertEqual((day, aware), (dt.date(2026, 10, 2), False))

    def test_a_bool_is_refused_by_name_not_treated_as_a_number(self):
        self.assertEqual(axis.day_of(True), (None, False, "not_a_day_bool"))

    def test_a_number_is_refused_by_name(self):
        self.assertEqual(axis.day_of(20261002)[2], "not_a_day_not_text")

    def test_a_short_string_is_refused_by_name(self):
        self.assertEqual(axis.day_of("2026-10")[2], "not_a_day_too_short")

    def test_the_basic_format_is_refused_ON_PURPOSE_and_says_so(self):
        """``20261002`` питоний разбор ПРИНИМАЕТ — прибор отказывает.

        Это названный односторонний отказ: восьмизначное число куда чаще КОД,
        чем день, и принять его значило бы изготовить находку из формата.
        Контроль держит именно решение, а не случайность разбора: разбор
        показан рядом.

        ПРИЧИНА у восьмизначного — ``too_short`` (строка короче ``ГГГГ-ММ-ДД``),
        и это замер, а не описка: сначала мерится ДЛИНА. Так что отказ назван
        дважды и по-разному — поэтому ветка про дефис проверяется ОТДЕЛЬНО,
        на подлежащем нужной длины, а не предполагается достигнутой.
        """
        self.assertEqual(dt.datetime.fromisoformat("20261002").date(),
                         dt.date(2026, 10, 2))
        self.assertEqual(axis.day_of("20261002")[2], "not_a_day_too_short")

    def test_a_long_enough_unhyphenated_stamp_is_refused_by_ITS_own_reason(self):
        """Обратная сторона: ветка про дефис ДОСТИГАЕТСЯ и говорит своё.

        Без этой проверки ветка ``not_a_day_unhyphenated`` не исполнялась бы ни
        одним тестом — то есть существовала бы как украшение.
        """
        self.assertEqual(axis.day_of("2026100212")[2],
                         "not_a_day_unhyphenated")

    def test_an_unparsable_but_hyphenated_head_is_refused_by_name(self):
        self.assertEqual(axis.day_of("2026-99-99")[2], "not_a_day_unparsed")

    def test_a_Z_suffixed_stamp_is_parsed_as_UTC_and_called_aware(self):
        """`Z` — тот же пояс, записанный иначе; без замены он не разбирается."""
        day, aware, cause = axis.day_of("2026-10-02T23:30:00Z")
        self.assertEqual((day, aware, cause),
                         (dt.date(2026, 10, 2), True, ""))

    def test_BOTH_hyphens_are_required_not_either_of_them(self):
        """Конъюнкция, а не дизъюнкция: один дефис на месте — ещё не день.

        Мутант `and -> or` меняет ПРИЧИНУ отказа, не вердикт, поэтому
        проверяется именно причина — иначе подмена пережила бы батарею.
        """
        for text in ("2026-1002T1", "20261-02-0"):
            with self.subTest(text=text):
                self.assertEqual(axis.day_of(text)[2],
                                 "not_a_day_unhyphenated")

    def test_a_whole_day_with_an_unparsed_TAIL_still_yields_its_day(self):
        """Хвост, на день не влияющий, не вправе забрать у нас день."""
        day, aware, cause = axis.day_of("2026-10-02 и ещё что-то")
        self.assertEqual((day, aware, cause), (dt.date(2026, 10, 2), False, ""))


class DayAxisOfOneField(unittest.TestCase):
    """Ось ли дня это поле — вердикт решает, причина объясняет."""

    def test_distinct_days_one_per_element_make_it_an_axis(self):
        row = axis.day_axis_of_field(_days("2026-10-01", "2026-10-02"), "day")
        self.assertTrue(row["axis"])
        self.assertEqual((row["n"], row["days"]), (2, 2))

    def test_repeated_days_are_refused_and_THAT_is_the_strong_half(self):
        """Дни повторяются ⇒ день не различает элементы ни при каком имени."""
        row = axis.day_axis_of_field(
            _days("2026-10-01", "2026-10-01", "2026-10-02"), "day")
        self.assertEqual((row["axis"], row["reason"]), (False, "day_repeats"))

    def test_a_missing_field_is_refused_by_its_own_reason(self):
        items = [{"day": "2026-10-01"}, {"other": 1}]
        row = axis.day_axis_of_field(items, "day")
        self.assertEqual((row["axis"], row["reason"]), (False, "field_absent"))

    def test_a_gap_in_days_does_NOT_cancel_the_axis_but_IS_observed(self):
        """Смежность — наблюдение рядом, не вердикт: порог запрещён заказом."""
        row = axis.day_axis_of_field(_days("2026-10-01", "2026-10-03"), "day")
        self.assertTrue(row["axis"])
        self.assertEqual((row["contiguous"], row["span_days"]), (False, 3))

    def test_contiguous_days_are_marked_contiguous(self):
        row = axis.day_axis_of_field(_days("2026-10-01", "2026-10-02"), "day")
        self.assertEqual((row["contiguous"], row["span_days"]), (True, 2))

    def test_mixing_aware_with_naive_is_FLAGGED_and_still_an_axis(self):
        row = axis.day_axis_of_field(
            _days("2026-10-01T10:00:00+00:00", "2026-10-02T10:00:00"), "day")
        self.assertTrue(row["axis"])
        self.assertTrue(row["mixed_awareness"])

    def test_a_uniform_list_is_not_flagged_for_mixed_awareness(self):
        """Обратная сторона: пометка не стои́т там, где смешения нет."""
        row = axis.day_axis_of_field(
            _days("2026-10-01T10:00:00+00:00", "2026-10-02T10:00:00+00:00"),
            "day")
        self.assertFalse(row["mixed_awareness"])


class DayAxisOfOneList(unittest.TestCase):
    """Шесть исходов списка, и каждый отличим от остальных."""

    def test_a_day_series_is_named_with_the_field_that_makes_it_one(self):
        row = axis.day_axis_of_list(
            [{"day": "2026-10-01", "v": 1}, {"day": "2026-10-02", "v": 1}])
        self.assertEqual(row["outcome"], axis.DAY_SERIES)
        self.assertEqual(row["fields"], ["day"])

    def test_the_field_name_is_an_OUTPUT_so_ANY_name_can_be_the_axis(self):
        """Списка «датных имён» у прибора нет — и это проверяется именем.

        Поле названо так, что ни в одном реестре имён его быть не может;
        осью дня оно становится по ЗНАЧЕНИЯМ. Появись здесь скрытый список
        имён — тест покраснеет.
        """
        row = axis.day_axis_of_list([{"zzz_unlisted": "2026-10-01"},
                                     {"zzz_unlisted": "2026-10-02"}])
        self.assertEqual(row["outcome"], axis.DAY_SERIES)
        self.assertEqual(row["fields"], ["zzz_unlisted"])

    def test_a_field_present_in_only_SOME_elements_is_not_an_axis(self):
        """Население кандидатов — ПЕРЕСЕЧЕНИЕ ключей, не ключи первого."""
        row = axis.day_axis_of_list([{"day": "2026-10-01", "x": 1},
                                     {"day": "2026-10-02"}])
        self.assertEqual(row["fields"], ["day"])

    def test_repeated_days_make_the_list_NOT_a_series_with_the_reason_named(self):
        row = axis.day_axis_of_list(
            [{"day": "2026-10-01"}, {"day": "2026-10-01"}])
        self.assertEqual(row["outcome"], axis.NOT_DAY_SERIES)
        self.assertEqual(row["reasons"], {"day_repeats": 1})

    def test_a_list_with_no_day_bearing_field_is_not_a_series(self):
        """Причина НАЗЫВАЕТСЯ, и она про длину: «a» короче ``ГГГГ-ММ-ДД``."""
        row = axis.day_axis_of_list([{"id": "a"}, {"id": "b"}])
        self.assertEqual(row["outcome"], axis.NOT_DAY_SERIES)
        self.assertEqual(row["reasons"], {"not_a_day_too_short": 1})

    def test_a_day_SHAPED_but_impossible_value_is_refused_as_unparsed(self):
        """Второй сосед той же развилки: длина прошла, разбор — нет."""
        row = axis.day_axis_of_list([{"id": "2026-99-99"},
                                     {"id": "2026-88-88"}])
        self.assertEqual(row["reasons"], {"not_a_day_unparsed": 1})

    def test_scalar_days_are_a_series_BY_VALUE_and_kept_apart(self):
        """У такого ряда нет ПОЛЯ вовсе — слить его с `day_series` значило бы
        доложить про поле там, где поля нет."""
        row = axis.day_axis_of_list(["2026-10-01", "2026-10-02"])
        self.assertEqual(row["outcome"], axis.DAY_SERIES_BY_VALUE)
        self.assertEqual(row["identity"], "by_value")

    def test_repeated_scalar_days_are_not_applicable_with_a_reason(self):
        row = axis.day_axis_of_list(["2026-10-01", "2026-10-01"])
        self.assertEqual(row["outcome"], axis.NOT_APPLICABLE)
        self.assertEqual(row["reason"],
                         "not_dicts_and_values_are_not_distinct_days")

    def test_a_singleton_is_TRIVIAL_and_never_counted_as_a_finding(self):
        """Биекция на одном элементе — свойство построения, не наблюдение."""
        for one in ([{"day": "2026-10-01"}], ["2026-10-01"]):
            with self.subTest(one=one):
                self.assertEqual(axis.day_axis_of_list(one)["outcome"],
                                 axis.TRIVIAL_SINGLETON)

    def test_an_empty_list_is_not_applicable_not_a_refusal(self):
        row = axis.day_axis_of_list([])
        self.assertEqual((row["outcome"], row["reason"]),
                         (axis.NOT_APPLICABLE, "empty"))

    def test_a_non_list_is_the_THIRD_outcome_with_its_type_named(self):
        row = axis.day_axis_of_list({"day": "2026-10-01"})
        self.assertEqual(row["outcome"], axis.UNMEASURED)
        self.assertIn("dict", row["reason"])


class TheTallyKeepsItsDenominatorHonest(unittest.TestCase):
    """Число-находка и его знаменатель печатаются только вместе."""

    def _rows(self) -> list:
        return [
            dict(axis.day_axis_of_list(_days("2026-10-01", "2026-10-02")),
                 module="m.a", coord=".series"),
            dict(axis.day_axis_of_list(_days("2026-10-01", "2026-10-01")),
                 module="m.b", coord=".records"),
            dict(axis.day_axis_of_list([{"day": "2026-10-01"}]),
                 module="m.c", coord=".one"),
            dict(axis.day_axis_of_list([]), module="m.d", coord=".empty"),
        ]

    def test_singletons_and_inapplicable_lists_stay_OUT_of_the_denominator(self):
        doc = axis.tally(self._rows())
        self.assertEqual(doc["answered_yes"], 1)
        self.assertEqual(doc["denominator_of_finding"], 2)
        self.assertEqual(doc["trivial_singletons"], 1)
        self.assertEqual(doc["not_applicable"], 1)

    def test_strength_of_a_field_is_the_LONGEST_list_it_indexed(self):
        rows = [
            dict(axis.day_axis_of_list(_days("2026-10-01", "2026-10-02")),
                 module="m.a", coord=".short"),
            dict(axis.day_axis_of_list(
                _days(*[f"2026-10-{d:02d}" for d in range(1, 11)])),
                module="m.b", coord=".long"),
        ]
        doc = axis.tally(rows)
        self.assertEqual(doc["axis_fields"]["day"], 2)
        self.assertEqual(doc["axis_field_strength"]["day"], 10)

    def test_a_name_in_ONE_reader_is_not_equated_with_one_in_MANY(self):
        """Два населения имени, и одного мало — замер 11.10 на живом дереве.

        `forward_date` дал 11 списков у ОДНОГО читателя, `cycle_date` — 11 у
        девяти. По числу списков они равны; по числу читателей различаются в
        девять раз. Сцена воспроизводит именно это: равные счёты списков при
        разном числе читателей. Мутант, считающий читателей как списки (или
        наоборот), краснеет здесь.
        """
        rows = []
        for i in range(3):
            rows.append(dict(axis.day_axis_of_list(
                [{"one_reader": "2026-10-01"}, {"one_reader": "2026-10-02"}]),
                module="m.only", coord=f".nested[{i}]"))
        for i in range(3):
            rows.append(dict(axis.day_axis_of_list(
                [{"many": "2026-10-01"}, {"many": "2026-10-02"}]),
                module=f"m.{i}", coord=".top"))
        doc = axis.tally(rows)
        self.assertEqual(doc["axis_fields"]["one_reader"],
                         doc["axis_fields"]["many"], "счёт списков должен быть равным")
        self.assertEqual(doc["axis_field_readers"]["one_reader"], 1)
        self.assertEqual(doc["axis_field_readers"]["many"], 3)

    def test_a_row_without_a_named_reader_adds_no_phantom_reader(self):
        """Обратная сторона: безымянный читатель не считается читателем."""
        doc = axis.tally([axis.day_axis_of_list(_days("2026-10-01", "2026-10-02"))])
        self.assertEqual(doc["axis_fields"]["day"], 1)
        self.assertEqual(doc["axis_field_readers"].get("day", 0), 0)

    def test_the_report_prints_BOTH_populations_of_a_name(self):
        rows = [dict(axis.day_axis_of_list(_days("2026-10-01", "2026-10-02")),
                     module="m.a", coord=".x")]
        lines = axis.report(axis.tally(rows))
        self.assertTrue(any("читател" in line and "списк" in line
                            for line in lines),
                        f"напечатано одно население вместо двух: {lines}")

    def test_an_unmeasured_row_is_counted_by_cause_and_never_silently_dropped(self):
        doc = axis.tally([{"outcome": axis.UNMEASURED, "reason": "зонд молчал"}])
        self.assertEqual(doc["unmeasured_causes"], {"зонд молчал": 1})
        self.assertEqual(doc["answered_yes"], 0)

    def test_an_unmeasured_row_without_a_reason_still_gets_a_name(self):
        """Безымянная причина — тоже причина, а не исчезновение строки."""
        doc = axis.tally([{"outcome": axis.UNMEASURED}])
        self.assertEqual(sum(doc["unmeasured_causes"].values()), 1)

    def test_an_empty_population_prints_NO_share_instead_of_zero_percent(self):
        """Доли без населения НЕТ: ноль процентов был бы утверждением."""
        lines = axis.report(axis.tally([]))
        self.assertTrue(any("доли НЕТ" in line for line in lines),
                        f"ожидал честное «доли НЕТ», получил: {lines}")

    def test_the_report_refuses_an_empty_document_outright(self):
        self.assertIn("НЕ ИЗМЕРЕНО", axis.report({})[0])


class ThereIsNoRuleAndNoThreshold(unittest.TestCase):
    """Заказ: сначала замер, потом правило. Правила здесь нет — и это ИЗМЕРИМО."""

    def test_no_gate_shaped_name_exists_on_the_public_surface(self):
        for name in axis._NO_GATE_NAMES:
            with self.subTest(name=name):
                self.assertFalse(hasattr(axis, name),
                                 f"{name} появилось в приборе — это гейт, и "
                                 "вводить его вправе только ADR")

    def test_the_report_says_out_loud_that_no_threshold_was_assigned(self):
        lines = axis.report(axis.tally(
            [dict(axis.day_axis_of_list(_days("2026-10-01", "2026-10-02")))]))
        self.assertTrue(any("порога НЕТ" in line for line in lines))

    def test_the_module_never_reads_a_clock(self):
        """Часов у прибора нет ни одной двери — поэтому и пинать нечего."""
        tree = ast.parse(Path(axis.__file__).read_text(encoding="utf-8"))
        doors = {"now", "today", "utcnow", "time"}
        hits = [node.func.attr for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in doors]
        self.assertEqual(hits, [], f"прибор потрогал часы: {hits}")


class TheDocumentIsACONTRACTAndItsNamesArePinnedVERBATIM(unittest.TestCase):
    """Имена ключей и значения исходов — ДОСЛОВНО, а не через свои же константы.

    Найдено мутациями (цикл #832): сравнение `outcome == axis.DAY_SERIES`
    переименование САМОЙ константы переживает — обе стороны меняются вместе.
    Это ровно класс «строки контракта сверяются САМИ С СОБОЙ и мутанта
    переживают». А имена здесь настоящий контракт: по ним артефакт читает
    офис, и смена любого молча оставила бы его раздел пустым.
    """

    def test_every_outcome_value_is_pinned(self):
        self.assertEqual(
            {axis.DAY_SERIES, axis.DAY_SERIES_BY_VALUE, axis.TRIVIAL_SINGLETON,
             axis.NOT_DAY_SERIES, axis.NOT_APPLICABLE, axis.UNMEASURED},
            {"day_series", "day_series_by_value", "day_series_trivial_singleton",
             "not_day_series", "not_applicable", "unmeasured"})

    def test_every_key_of_the_tally_is_pinned(self):
        doc = axis.tally([
            dict(axis.day_axis_of_list(_days("2026-10-01", "2026-10-02")),
                 module="m.a", coord=".s"),
        ])
        self.assertEqual(set(doc), {
            "lists_seen", "outcomes", "answered_yes", "denominator_of_finding",
            "day_series_by_value", "trivial_singletons", "not_applicable",
            "axis_fields", "axis_field_readers", "axis_field_strength",
            "refusal_reasons", "mixed_awareness_axes", "non_contiguous_axes",
            "unmeasured_causes", "series_rows"})

    def test_every_key_of_a_series_row_is_pinned(self):
        doc = axis.tally([
            dict(axis.day_axis_of_list(_days("2026-10-01", "2026-10-02")),
                 module="m.a", coord=".s"),
        ])
        self.assertEqual(doc["series_rows"],
                         [{"coord": ".s", "n": 2, "module": "m.a",
                           "fields": ["day"]}])

    def test_every_key_of_an_axis_row_is_pinned(self):
        row = axis.day_axis_of_field(_days("2026-10-01", "2026-10-02"), "day")
        self.assertEqual(set(row), {
            "field", "n", "days", "mixed_awareness", "axis", "reason",
            "span_days", "contiguous", "first_day", "last_day"})

    def test_the_forbidden_gate_names_are_pinned_verbatim(self):
        """Иначе пин сам себя и проверяет: мутант переименует и имя, и запрет."""
        self.assertEqual(set(axis._NO_GATE_NAMES), {
            "is_fit", "admit_field", "reject_field", "apply_threshold",
            "unfit_for_identity", "series_gate", "must_be_series"})

    def test_a_non_list_reports_length_zero_not_a_guess(self):
        self.assertEqual(axis.day_axis_of_list({"day": "2026-10-01"})["n"], 0)


class TheObservationsBesideTheVerdictAreCOUNTEDNotJustFlagged(unittest.TestCase):
    """Оговорки-наблюдения: мутант, считающий их вдвое, обязан краснеть."""

    def _doc(self) -> dict:
        return axis.tally([
            # смешанный пояс, дни смежны
            dict(axis.day_axis_of_list(
                [{"a": "2026-10-01T10:00:00+00:00"},
                 {"a": "2026-10-02T10:00:00"}]), module="m.mixed", coord=".m"),
            # разрыв в днях, пояса нет
            dict(axis.day_axis_of_list(_days("2026-10-01", "2026-10-05")),
                 module="m.gap", coord=".g"),
            # ни того, ни другого — обратный контроль
            dict(axis.day_axis_of_list(_days("2026-10-01", "2026-10-02")),
                 module="m.plain", coord=".p"),
        ])

    def test_each_observation_is_counted_exactly_once(self):
        doc = self._doc()
        self.assertEqual(doc["mixed_awareness_axes"], 1)
        self.assertEqual(doc["non_contiguous_axes"], 1)
        self.assertEqual(doc["answered_yes"], 3,
                         "оговорки не вправе менять вердикт")

    def test_the_report_prints_both_observations_with_their_counts(self):
        lines = axis.report(self._doc())
        self.assertTrue(any("смешанный пояс 1" in line and
                            "с разрывом в днях 1" in line for line in lines),
                        f"счёты оговорок не напечатаны: {lines}")

    def test_a_population_without_either_prints_NO_caveat_line(self):
        """Обратная сторона: строки нет там, где нечего оговаривать."""
        doc = axis.tally([dict(axis.day_axis_of_list(
            _days("2026-10-01", "2026-10-02")), module="m", coord=".x")])
        self.assertFalse(any("оговорки-наблюдения" in line
                             for line in axis.report(doc)))

    def test_by_value_count_is_zero_when_no_such_list_was_seen(self):
        doc = axis.tally([dict(axis.day_axis_of_list(
            _days("2026-10-01", "2026-10-02")), module="m", coord=".x")])
        self.assertEqual(doc["day_series_by_value"], 0)


class AwarenessOfEveryDAYBEARINGFormIsClaimedAndChecked(unittest.TestCase):
    """«Наивна или осознана» — утверждение о КАЖДОЙ форме, не только о строке.

    Найдено мутациями: объявить голую `date` осознанной мог бы мутант, и ни
    один тест не краснел — потому что смешанность проверялась только на
    строках со временем. Сцены ниже делают пояс НАБЛЮДАЕМЫМ у каждой формы:
    смешай форму с заведомо осознанной отметкой, и признак смешения обязан
    встать.
    """

    def test_a_bare_date_object_is_naive_and_mixing_shows_it(self):
        row = axis.day_axis_of_field(
            [{"d": dt.date(2026, 10, 1)},
             {"d": dt.datetime(2026, 10, 2, 10, tzinfo=dt.timezone.utc)}], "d")
        self.assertTrue(row["axis"])
        self.assertTrue(row["mixed_awareness"],
                        "голая date объявлена осознанной — пояса у неё нет")

    def test_a_date_only_string_is_naive_and_mixing_shows_it(self):
        row = axis.day_axis_of_field(
            _days("2026-10-01", "2026-10-02T10:00:00+00:00"), "day")
        self.assertTrue(row["axis"])
        self.assertTrue(row["mixed_awareness"],
                        "отметка без времени объявлена осознанной")

    def test_a_stamp_with_an_unparsed_tail_is_naive_and_mixing_shows_it(self):
        row = axis.day_axis_of_field(
            _days("2026-10-01 и ещё что-то", "2026-10-02T10:00:00+00:00"),
            "day")
        self.assertTrue(row["axis"])
        self.assertTrue(row["mixed_awareness"])

    def test_all_naive_forms_together_are_NOT_called_mixed(self):
        """Обратная сторона: три наивные формы согласны между собой."""
        row = axis.day_axis_of_field(
            [{"d": dt.date(2026, 10, 1)}, {"d": "2026-10-02"},
             {"d": dt.datetime(2026, 10, 3, 10)}], "d")
        self.assertFalse(row["mixed_awareness"])


class AnEmptyPopulationIsALLZerosNotOnes(unittest.TestCase):
    """Умолчания счётчиков — утверждение: пустое население даёт НУЛИ.

    Найдено мутациями: `.get(исход, 0)` с подменённым умолчанием переживал
    батарею, потому что ни одна сцена не оставляла счётчик без слагаемых.
    """

    def test_every_count_of_an_empty_tally_is_exactly_zero(self):
        doc = axis.tally([])
        self.assertEqual(doc, {
            "lists_seen": 0, "outcomes": {}, "answered_yes": 0,
            "denominator_of_finding": 0, "day_series_by_value": 0,
            "trivial_singletons": 0, "not_applicable": 0,
            "axis_fields": {}, "axis_field_readers": {},
            "axis_field_strength": {}, "refusal_reasons": {},
            "mixed_awareness_axes": 0, "non_contiguous_axes": 0,
            "unmeasured_causes": {}, "series_rows": []})


class TheReportPRINTSTheNumbersItWasGiven(unittest.TestCase):
    """Отрисовка сверяется ЗНАЧЕНИЯМИ, а не наличием слов.

    Найдено мутациями: склейка `doc.get(X) or {}`, подменённая на `and {}`,
    отдаёт ПУСТО при непустом входе — строка печатается, числа в ней
    обнуляются, и проверка по словам этого не видит.
    """

    def _doc(self) -> dict:
        return axis.tally([
            dict(axis.day_axis_of_list(
                _days(*[f"2026-10-{d:02d}" for d in range(1, 8)])),
                module="m.long", coord=".seven"),
            dict(axis.day_axis_of_list(_days("2026-10-01", "2026-10-01")),
                 module="m.rep", coord=".rep"),
            {"outcome": axis.UNMEASURED, "reason": "зонд молчал",
             "module": "m.mute", "coord": ".q"},
        ])

    def test_the_share_is_printed_with_its_denominator(self):
        line = axis.report(self._doc())[0]
        self.assertIn("применимых списков 2", line)
        self.assertIn("РЯД ПО ДНЮ 1", line)
        self.assertIn("50.0%", line)

    def test_the_field_line_carries_BOTH_populations_and_the_strength(self):
        line = next(ln for ln in axis.report(self._doc())
                    if "осью дня оказались" in ln)
        self.assertIn("day×1 списк. у 1 читател. (макс. длина 7)", line)

    def test_the_refusal_line_carries_its_cause_and_count(self):
        lines = axis.report(self._doc())
        self.assertTrue(any("почему НЕ ряд: day_repeats×1" in ln
                            for ln in lines), f"причина без числа: {lines}")

    def test_the_unmeasured_line_carries_its_cause_and_count(self):
        lines = axis.report(self._doc())
        self.assertTrue(any("НЕ ИЗМЕРЕНО: зонд молчал×1" in ln
                            for ln in lines), f"не измерено без числа: {lines}")

    def test_the_SECOND_line_carries_all_three_of_its_counts(self):
        """Синглтоны · ряд по значению · неприменимо — ЗНАЧЕНИЯМИ, не словами."""
        doc = axis.tally([
            dict(axis.day_axis_of_list(_days("2026-10-01", "2026-10-02")),
                 module="m.a", coord=".s"),
            dict(axis.day_axis_of_list([{"day": "2026-10-01"}]),
                 module="m.b", coord=".one"),
            dict(axis.day_axis_of_list(["2026-10-01", "2026-10-02"]),
                 module="m.c", coord=".val"),
            dict(axis.day_axis_of_list([]), module="m.d", coord=".empty"),
        ])
        line = axis.report(doc)[1]
        self.assertIn("тривиальных синглтонов 1", line)
        self.assertIn("ряд САМИМИ значениями 1", line)
        self.assertIn("неприменимо 1", line)

    def test_a_series_row_is_printed_with_module_coord_length_and_fields(self):
        doc = axis.tally([dict(axis.day_axis_of_list(
            _days("2026-10-01", "2026-10-02")), module="m.a", coord=".s")])
        line = next(ln for ln in axis.report(doc) if ln.startswith("  [РЯД] "))
        self.assertEqual(line, "  [РЯД] m.a .s длина 2 по ['day']")

    def test_the_unmeasured_cause_is_named_even_when_the_row_gave_none(self):
        doc = axis.tally([{"outcome": axis.UNMEASURED}])
        lines = axis.report(doc)
        self.assertTrue(any("НЕ ИЗМЕРЕНО: безымянная причина×1" in ln
                            for ln in lines), f"причина без имени: {lines}")

    def test_names_with_EQUAL_populations_are_ordered_by_name(self):
        """Тай-брейк — ИМЯ: иначе порядок решал бы порядок обхода словаря."""
        rows = [
            dict(axis.day_axis_of_list([{"zeta": "2026-10-01"},
                                        {"zeta": "2026-10-02"}]),
                 module="m.z", coord=".z"),
            dict(axis.day_axis_of_list([{"alpha": "2026-10-01"},
                                        {"alpha": "2026-10-02"}]),
                 module="m.a", coord=".a"),
        ]
        line = next(ln for ln in axis.report(axis.tally(rows))
                    if "осью дня оказались" in ln)
        self.assertLess(line.index("alpha"), line.index("zeta"))

    def test_two_causes_are_joined_by_the_declared_separator(self):
        doc = axis.tally([
            dict(axis.day_axis_of_list(_days("2026-10-01", "2026-10-01")),
                 module="m.a", coord=".rep"),
            dict(axis.day_axis_of_list([{"id": "a"}, {"id": "b"}]),
                 module="m.b", coord=".short"),
        ])
        line = next(ln for ln in axis.report(doc) if "почему НЕ ряд" in ln)
        self.assertIn("day_repeats×1 · not_a_day_too_short×1", line)

    def test_ONE_caveat_alone_still_prints_the_caveat_line(self):
        """Оговорки соединены ИЛИ, не И: одной довольно."""
        only_gap = axis.tally([dict(axis.day_axis_of_list(
            _days("2026-10-01", "2026-10-05")), module="m", coord=".g")])
        only_mixed = axis.tally([dict(axis.day_axis_of_list(
            [{"d": "2026-10-01"},
             {"d": "2026-10-02T10:00:00+00:00"}]), module="m", coord=".m")])
        for doc, needle in ((only_gap, "с разрывом в днях 1"),
                            (only_mixed, "смешанный пояс 1")):
            with self.subTest(needle=needle):
                lines = axis.report(doc)
                self.assertTrue(any("оговорки-наблюдения" in ln and needle in ln
                                    for ln in lines),
                                f"одна оговорка не напечатана: {lines}")


class ShorteningSaysItShortened(unittest.TestCase):
    """Укороченный перечень обязан СКАЗАТЬ об этом и назвать полное число."""

    def _big(self) -> dict:
        rows = []
        for i in range(9):
            rows.append(dict(axis.day_axis_of_list(
                [{f"f{i}": "2026-10-01"}, {f"f{i}": "2026-10-02"}]),
                module=f"m.{i}", coord=f".c{i}"))
        return axis.tally(rows)

    def test_the_field_list_is_shortened_and_the_total_is_named(self):
        lines = axis.report(self._big())
        self.assertTrue(any("перечень имён укорочен: всего 9" in line
                            for line in lines), f"нет строки об укорочении: {lines}")

    def test_the_series_list_is_shortened_and_the_total_is_named(self):
        lines = axis.report(self._big())
        self.assertTrue(any("перечень рядов укорочен: всего 9" in line
                            for line in lines), f"нет строки об укорочении: {lines}")

    def test_a_short_population_is_NOT_declared_shortened(self):
        """Обратная сторона: порог не срабатывает там, где резать нечего."""
        doc = axis.tally([dict(axis.day_axis_of_list(
            _days("2026-10-01", "2026-10-02")), module="m", coord=".x")])
        lines = axis.report(doc)
        self.assertFalse(any("укорочен" in line for line in lines))

    def test_the_declared_defaults_are_the_ones_actually_applied(self):
        """Умолчания — утверждение: 6 имён и 5 рядов, не «сколько-нибудь»."""
        lines = axis.report(self._big())
        shown = [ln for ln in lines if ln.startswith("  [РЯД] ")]
        self.assertEqual(len(shown), 5)
        head = next(ln for ln in lines if "осью дня оказались" in ln)
        self.assertEqual(head.count(" · "), 5, "имён в голове должно быть 6")


class RefusalReasonsComeFromTheREFUSEDListsOnly(unittest.TestCase):
    """Причины собираются у `not_day_series`, и у синглтона они ЕСТЬ."""

    def test_a_singleton_without_a_day_carries_reasons_but_is_not_counted(self):
        """Сцена, на которой мутант `== -> !=` виден.

        Синглтон без датного поля причину НЕСЁТ (ветка причин исполняется), но
        в свод причин идти не вправе: он не отказ, он тривиальность.
        """
        single = axis.day_axis_of_list([{"id": "a"}])
        self.assertEqual(single["outcome"], axis.TRIVIAL_SINGLETON)
        self.assertIn("reasons", single)
        doc = axis.tally([dict(single, module="m.one", coord=".o")])
        self.assertEqual(doc["refusal_reasons"], {})

    def test_reasons_of_a_refused_list_DO_reach_the_tally(self):
        doc = axis.tally([dict(axis.day_axis_of_list(
            _days("2026-10-01", "2026-10-01")), module="m", coord=".r")])
        self.assertEqual(doc["refusal_reasons"], {"day_repeats": 1})

    def test_field_absent_is_UNREACHABLE_because_candidates_are_an_INTERSECTION(self):
        """Причина `field_absent` у списка не возникает ПО ПОСТРОЕНИЮ.

        Поле, которого нет у кого-то, в кандидаты не попадает вовсе, поэтому
        отсеивать его среди причин было нечем — мутация показала ветвь
        недостижимой, и ветвь снята. Здесь закреплено само свойство: причина
        отсутствует, а поле, присутствующее у всех, причину даёт.
        """
        row = axis.day_axis_of_list([{"id": "a", "day": "2026-10-01"},
                                     {"id": "b"}])
        self.assertNotIn("field_absent", row.get("reasons") or {})
        self.assertEqual(row.get("fields_examined"), 1,
                         "в кандидаты обязано попасть ровно пересечение")

    def test_but_the_FIELD_level_measure_still_names_field_absent(self):
        """Обратная сторона: у ПОЛЯ, спрошенного напрямую, причина жива."""
        row = axis.day_axis_of_field([{"day": "2026-10-01"}, {"other": 1}],
                                     "day")
        self.assertEqual(row["reason"], "field_absent")


class TheProbeAnnotatesEveryListItWalks(unittest.TestCase):
    """Звено 1: ось дня ставится в зонде, где ещё живы ЗНАЧЕНИЯ."""

    def test_a_classified_list_carries_its_day_axis(self):
        row = classify_list(_days("2026-10-01", "2026-10-02"))
        self.assertEqual(row["day_axis"]["outcome"], axis.DAY_SERIES)

    def test_the_axis_is_set_even_when_the_list_has_NO_identity(self):
        """Вопросы независимы: мерить ось только у названных значило бы
        отбирать население ЧУЖИМ признаком."""
        row = classify_list([{"day": "2026-10-01"}, {"day": "2026-10-01"}])
        self.assertEqual(row["outcome"], "unnamed_no_candidate")
        self.assertEqual(row["day_axis"]["outcome"], axis.NOT_DAY_SERIES)

    def test_even_an_empty_list_gets_an_axis_row(self):
        self.assertEqual(classify_list([])["day_axis"]["outcome"],
                         axis.NOT_APPLICABLE)

    def test_a_scalar_list_gets_an_axis_row_too(self):
        row = classify_list(["2026-10-01", "2026-10-02"])
        self.assertEqual(row["day_axis"]["outcome"], axis.DAY_SERIES_BY_VALUE)


class TheCensusFoldsTheAxisIntoItsCounts(unittest.TestCase):
    """Звено 2: свод переписи несёт раздел оси и честный знаменатель."""

    @staticmethod
    def _rows(**over) -> dict:
        base = {
            "m.good": {"entry": "measure", "truncated": False, "lists": [
                classify_list(_days("2026-10-01", "2026-10-02")),
                classify_list(_days("2026-10-01", "2026-10-01")),
            ]},
            "m.cut": {"entry": "measure", "truncated": True, "lists": [
                classify_list(_days("2026-10-05", "2026-10-06")),
            ]},
            "m.silent": {"cause": "no_entry_point", "reason": "точки входа нет"},
        }
        base.update(over)
        return base

    def test_the_counts_carry_the_day_axis_section(self):
        counts = census.tally(self._rows())
        self.assertIn("day_axis", counts)
        self.assertEqual(counts["day_axis"]["answered_yes"], 1)
        self.assertEqual(counts["day_axis"]["denominator_of_finding"], 2)

    def test_a_truncated_reader_is_EXCLUDED_and_counted_not_dropped(self):
        """Недосмотренное население даёт «не измерено», а не долю."""
        day_axis = census.tally(self._rows())["day_axis"]
        self.assertEqual(day_axis["readers_excluded_truncated"], 1)
        self.assertNotIn("m.cut", [r.get("module")
                                   for r in day_axis["series_rows"]])

    def test_a_reader_that_never_answered_does_not_enter_the_population(self):
        day_axis = census.tally(self._rows())["day_axis"]
        self.assertEqual(day_axis["lists_seen"], 2)

    def test_a_row_the_probe_left_WITHOUT_an_axis_becomes_unmeasured(self):
        """Расхождение зонда со сводом обязано быть ВИДНЫМ, а не исчезнуть.

        Живой зонд таких строк не делает; именно поэтому контроль нужен — иначе
        первое же расхождение прошло бы молча.
        """
        rows = self._rows(**{"m.raw": {"entry": "measure", "truncated": False,
                                       "lists": [{"n": 2, "outcome": "named",
                                                  "coord": ".x"}]}})
        day_axis = census.tally(rows)["day_axis"]
        self.assertEqual(sum(day_axis["unmeasured_causes"].values()), 1)

    def test_the_series_row_names_the_module_and_the_coordinate(self):
        row = census.tally(self._rows())["day_axis"]["series_rows"][0]
        self.assertEqual(row["module"], "m.good")
        self.assertEqual(row["fields"], ["day"])


class TheOfficeActuallyRENDERSTheAxis(unittest.TestCase):
    """Звено 3: ветка офиса проверяется ВЫЗОВОМ, не подстрокой (ADR-333)."""

    @classmethod
    def setUpClass(cls):
        cls.office = _office()

    @staticmethod
    def _doc(**over) -> dict:
        counts = {
            "lists_total": 3, "outcomes": {"named": 1}, "singletons": 1,
            "scalar_lists_multi": 0, "denominator_of_finding": 1,
            "candidate_fields_outside": {}, "candidate_field_strength": {},
            "finding_rows": [], "truncated_readers": [],
            "unmeasured_causes": {}, "readers_measured": 2,
            "day_axis": axis.tally([
                dict(axis.day_axis_of_list(_days("2026-10-01", "2026-10-02")),
                     module="m.a", coord=".series"),
                dict(axis.day_axis_of_list(_days("2026-10-01", "2026-10-01")),
                     module="m.b", coord=".records"),
            ]),
        }
        counts.update(over)
        doc = {"schema": census.SCHEMA,
               "generated_at": "2026-10-11T04:00:00+00:00",
               "status": "CLEAN", "reason": "", "advisory": "только читает",
               "invoked_by": {"schema": "call_provenance.v1", "measured": True,
                              "entry": "spa_core/monitoring/findings_bridge.py",
                              "inside_tree": True, "doors_agree": True,
                              "read_by": "sys.modules['__main__'].__file__"},
               "counts": counts}
        return doc

    def _render(self, doc: dict) -> str:
        # SCHEMA-GAP-OK: сцена про ОСЬ ДНЯ — прочие оси того же артефакта суть предмет своих файлов, и их отсутствие здесь не отставание фикстуры
        return "\n".join(self.office._summarize_json(
            "list_identity_census.json", doc,
            now=dt.datetime(2026, 10, 11, 5, 0, tzinfo=dt.timezone.utc),
            root=str(REPO), artifact_root=str(REPO)))

    def test_the_office_prints_the_measured_answer(self):
        text = self._render(self._doc())
        self.assertTrue("ОСЬ ДНЯ" in text, f"оси дня нет в отчёте офиса:\n{text}")
        self.assertTrue("РЯД ПО ДНЮ 1" in text,
                        "число-находка не напечатано офисом")

    def test_a_document_WITHOUT_the_section_is_called_old_not_zero(self):
        """«Раздела нет» и «рядов ноль» обязаны быть различимы (инв. #17)."""
        doc = self._doc()
        doc["counts"].pop("day_axis")
        text = self._render(doc)
        self.assertTrue("СТАРОГО ОБРАЗЦА" in text,
                        f"отсутствие раздела выдано за замер:\n{text}")

    def test_the_schema_declares_the_section_so_its_removal_reddens(self):
        declared = self.office._READ_SCHEMA["list_identity_census.json"]
        self.assertIn("counts.day_axis", declared)

    def test_positive_control_the_declared_key_is_really_consumed(self):
        """Объявление без чтения — `_HOLLOW_MARK`. Мерится РАЗНИЦА вывода."""
        with_axis = self._render(self._doc())
        without = self._doc()
        without["counts"]["day_axis"] = axis.tally([])
        self.assertNotEqual(with_axis, self._render(without))


class TheRuleLivesInExactlyONEHouse(unittest.TestCase):
    """Вторая копия правила — тот класс, который эта семья и ловит."""

    @staticmethod
    def _parses_dates_itself(path: Path, func: str) -> bool:
        """Разбирает ли ИМЕННО эта функция даты сама.

        Вопрос задаётся ФУНКЦИИ, а не файлу, и это не придирка: у зонда есть
        СВОЙ законный разбор отметки — пина часов (`main` читает
        ``SPA_CENSUS_PINNED_NOW``). Подстрока по всему файлу считает его
        второй копией правила про дни и краснеет на верном коде; заодно
        `assertNotIn` на целом файле выгружает файл в лог. Поэтому мера — AST
        и область ОДНОЙ функции.
        """
        tree = ast.parse(path.read_text(encoding="utf-8"))
        target = next((n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef) and n.name == func),
                      None)
        assert target is not None, f"{func} не найдена в {path.name}"
        return any(isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute)
                   and n.func.attr in ("fromisoformat", "strptime")
                   for n in ast.walk(target))

    def test_neither_the_probe_nor_the_census_reimplements_the_rule(self):
        for mod, func in (("spa_core/monitoring/_list_identity_probe.py",
                           "classify_list"),
                          ("spa_core/monitoring/list_identity_census.py",
                           "tally")):
            with self.subTest(mod=mod):
                self.assertFalse(self._parses_dates_itself(REPO / mod, func),
                                 f"{mod}:{func} разбирает дни сам — "
                                 "правило раздвоено")

    def test_positive_control_the_measure_DOES_see_a_second_copy(self):
        """Мерка обязана ловить настоящую вторую копию — иначе украшение."""
        self.assertTrue(self._parses_dates_itself(Path(axis.__file__), "day_of"))

    def test_the_census_imports_the_rule_rather_than_naming_it(self):
        tree = ast.parse((REPO / "spa_core/monitoring/list_identity_census.py")
                         .read_text(encoding="utf-8"))
        imported = {node.module for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.module}
        self.assertIn("spa_core.monitoring.list_day_axis", imported)


if __name__ == "__main__":                                 # pragma: no cover
    unittest.main()
