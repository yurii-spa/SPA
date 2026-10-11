"""Адрес находки: МЕСТО против ИМЕНИ — заказ G115 п. 1 (хвост ADR-541).

## Что измерялось ДО написания файла

Заказ назвал вред: «три отказа подряд спотыкаются об одно — признак отвечает о
МЕСТЕ в коде, кортеж личностей адресуется ИМЕНЕМ». Замер 11.10 против живого
артефакта переписи (56 читателей, 2474 списка, усечённых 0): находок **71**,
разрешимы дописанным именем **36**, разрешимы ТОЛЬКО адресом места **12**,
не разрешимы ничем **23**. Среди двенадцати — ровно те имена, что отвергнуты
ADR-503 и ADR-541 (`record_generated_at` n=126, `value` n=93, `window_s` n=11,
`trade_id` n=10).

## Почему проверок несколько, а не одна

У ответа ДВА независимых отказа, и они чинятся разным:

| отказ | чем он является | лечит ли адрес места |
|---|---|---|
| населения у имени нет | свойство ГЛОБАЛЬНОЙ координаты | да, по построению |
| поле пишут стенные часы | свойство КОДА производителя | только если часы в ЧУЖОМ файле |

Поэтому у каждой половины здесь контроль в обе стороны, и отдельно закреплён
третий исход: укорочённый перечень мест часов не имеет права читаться как «в
этом файле часов нет» (инв. #17), а ненайденное население — как «население
ноль».

Часы в этом файле не участвуют вовсе: предмет — состав ответа и форма кода.
Литеральных дат нет; живое ``data/`` не читается — все сцены собраны руками.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from spa_core.monitoring import candidate_denominator as cd
from spa_core.monitoring import finding_address_price as ap
from spa_core.monitoring import list_identity_census as census
from spa_core.monitoring.identity_field_kind import (
    CLOCK_NAMED_READ, NOT_DERIVED, UNMEASURED, WALL_CLOCK,
)

REPO = Path(__file__).resolve().parents[2]
OFFICE = REPO / "scripts" / "consume_office_reports.py"

IDENT = ("code", "id", "protocol")


def _office():
    """Шаг 0-офис — модулем, а не разбором текста (тот же приём, что у соседа)."""
    spec = importlib.util.spec_from_file_location("_office_under_test", OFFICE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(outcome: str, n, composition, *, module: str = "m.a",
         coord: str = ".x", candidates=None) -> dict:
    """Одна строка зонда — ровно та форма, которую производит `classify_list`."""
    out = {"outcome": outcome, "n": n, "module": module, "coord": coord}
    if composition is not None:
        out[ap.COMPOSITION_KEY] = dict(composition)
    out["candidates"] = (sorted(k for k, v in (composition or {}).items()
                                if v == ap.ELIGIBLE)
                         if candidates is None else list(candidates))
    return out


def _axis(population) -> dict:
    """Ось населения В ТОЙ ЖЕ форме, в которой её отдаёт сосед.

    Собирается руками, а не зовом соседа, намеренно: предмет этого файла —
    ПОТРЕБЛЕНИЕ оси, и сцена обязана уметь назвать население, которого настоящий
    сосед на такой выдумке не произвёл бы.
    """
    return {"status": "MEASURED",
            "rows": [{"field": name, "counted": counted,
                      "eligible_anywhere": broad}
                     for name, (counted, broad) in population.items()]}


def _kind(fields) -> dict:
    return {"fields": dict(fields)}


def _clock_row(verdict: str, *, wall=(), read=(), wall_count=None,
               read_count=None) -> dict:
    """Строка рода В ТОЙ ЖЕ форме, что печатает `identity_field_kind.census`."""
    return {"verdict": verdict, "why_unmeasured": "",
            "wall_clock_sites": list(wall),
            "clock_named_read_sites": list(read),
            "wall_clock_count": len(wall) if wall_count is None else wall_count,
            "clock_named_read_count": (len(read) if read_count is None
                                       else read_count)}


class WhatResolvesAFinding(unittest.TestCase):
    """Главное число заказа — и контроль в обе стороны на КАЖДОЕ слагаемое."""

    def test_a_candidate_eligible_only_here_is_resolvable_only_by_place(self):
        rows = [_row("unnamed_candidate_outside", 8, {"message": ap.ELIGIBLE})]
        out = ap.tally(rows, _axis({"message": (1, 1)}), IDENT)
        self.assertEqual(out["status"], "MEASURED")
        self.assertEqual(out["place_only"], 1)
        self.assertEqual(out["verdicts"], {"place_only": 1})
        self.assertEqual(out["verdict"], "PLACE_RESOLVES_WHAT_A_NAME_CANNOT")
        self.assertEqual(out["place_only_rows"][0]["unsupported_names"],
                         ["message"])

    def test_positive_control_raise_the_population_and_the_name_suffices(self):
        """ОБРАТНАЯ сторона: то же место, население 2 ⇒ место не покупает НИЧЕГО."""
        rows = [_row("unnamed_candidate_outside", 8, {"message": ap.ELIGIBLE})]
        out = ap.tally(rows, _axis({"message": (2, 2)}), IDENT)
        self.assertEqual(out["place_only"], 0)
        self.assertEqual(out["verdicts"], {"name_addressable": 1})
        self.assertEqual(out["verdict"], "NO_POPULATION_FOR_PLACE_ADDRESSING")
        self.assertEqual(out["place_only_rows"], [])

    def test_one_supported_candidate_is_enough_to_make_the_name_suffice(self):
        rows = [_row("unnamed_candidate_outside", 8,
                     {"message": ap.ELIGIBLE, "label": ap.ELIGIBLE})]
        out = ap.tally(rows, _axis({"message": (1, 1), "label": (4, 4)}), IDENT)
        self.assertEqual(out["verdicts"], {"name_addressable": 1})
        self.assertEqual(out["verdicts"], {"name_addressable": 1})
        self.assertEqual(
            ap.classify(rows[0], {"message": {ap.BROAD_READING: 1,
                                              ap.NARROW_READING: 1},
                                  "label": {ap.BROAD_READING: 4,
                                            ap.NARROW_READING: 4}},
                        IDENT, ap.BROAD_READING)["supported_names"], ["label"])

    def test_a_name_already_in_the_tuple_is_not_a_candidate(self):
        rows = [_row("unnamed_candidate_outside", 8, {"protocol": ap.ELIGIBLE})]
        out = ap.tally(rows, _axis({"protocol": (9, 9)}), IDENT)
        self.assertEqual(out["verdicts"], {"no_candidate": 1})

    def test_positive_control_drop_it_from_the_tuple_and_it_counts_again(self):
        """ОБРАТНАЯ сторона: то же поле вне кортежа — уже кандидат."""
        rows = [_row("unnamed_candidate_outside", 8, {"protocol": ap.ELIGIBLE})]
        out = ap.tally(rows, _axis({"protocol": (1, 1)}), ("code", "id"))
        self.assertEqual(out["verdicts"], {"place_only": 1})

    def test_an_ineligible_field_is_no_candidate_at_all(self):
        rows = [_row("unnamed_no_candidate", 8, {"note": "not_unique"})]
        out = ap.tally(rows, _axis({"note": (0, 0)}), IDENT)
        self.assertEqual(out["verdicts"], {"no_candidate": 1})
        self.assertEqual(out["place_only"], 0)

    def test_no_candidate_is_not_folded_into_place_only(self):
        rows = [_row("unnamed_no_candidate", 4, {}, module="m.b"),
                _row("unnamed_candidate_outside", 8, {"message": ap.ELIGIBLE})]
        out = ap.tally(rows, _axis({"message": (1, 1)}), IDENT)
        self.assertEqual(out["verdicts"], {"no_candidate": 1, "place_only": 1})
        self.assertEqual(out["findings_total"], 2)


class TheThirdOutcomeIsNeverAZero(unittest.TestCase):
    """«Не измерено» не имеет права читаться как ответ (инв. #17)."""

    def test_a_row_without_composition_is_unmeasured_not_no_candidate(self):
        rows = [_row("unnamed_candidate_outside", 8, None)]
        out = ap.tally(rows, _axis({"message": (1, 1)}), IDENT)
        self.assertEqual(out["verdicts"], {"unmeasured": 1})
        self.assertIn("состав", out["unmeasured_rows"][0]["reason"])
        self.assertEqual(out["place_only"], 0)

    def test_a_candidate_absent_from_the_axis_is_unmeasured_not_unsupported(self):
        rows = [_row("unnamed_candidate_outside", 8, {"ghost": ap.ELIGIBLE})]
        out = ap.tally(rows, _axis({"message": (1, 1)}), IDENT)
        self.assertEqual(out["verdicts"], {"unmeasured": 1})
        self.assertIn("населения", out["unmeasured_rows"][0]["reason"])

    def test_an_unmeasured_axis_refuses_the_whole_section(self):
        rows = [_row("unnamed_candidate_outside", 8, {"message": ap.ELIGIBLE})]
        for axis in (None, {}, {"status": "UNMEASURED", "reason": "нет"},
                     {"status": "MEASURED"}):
            with self.subTest(axis=axis):
                out = ap.tally(rows, axis, IDENT)
                self.assertEqual(out["status"], "UNMEASURED")
                self.assertNotIn("place_only", out)
                self.assertIn("это не", out["reason"])

    def test_the_price_is_unmeasured_when_it_was_not_measured(self):
        out = ap.tally([], _axis({"message": (1, 1)}), IDENT)
        self.assertEqual(out["reader_price"]["status"], "UNMEASURED")
        self.assertIn("не мерили", out["reader_price"]["reason"])

    def test_a_row_without_a_length_is_named_not_counted_as_a_singleton(self):
        rows = [_row("unnamed_candidate_outside", None,
                     {"message": ap.ELIGIBLE})]
        out = ap.tally(rows, _axis({"message": (1, 1)}), IDENT)
        self.assertEqual(out["findings_total"], 0)
        self.assertEqual(out["findings_without_length"][0]["reason"],
                         "у строки нет длины")

    def test_a_singleton_is_outside_the_denominator(self):
        rows = [_row("unnamed_candidate_outside", 1, {"message": ap.ELIGIBLE})]
        out = ap.tally(rows, _axis({"message": (1, 1)}), IDENT)
        self.assertEqual(out["findings_total"], 0)
        self.assertEqual(out["findings_without_length"], [])

    def test_outcomes_outside_the_subject_are_not_findings(self):
        for outcome in ("named", "named_by_value", "unnamed_not_dicts",
                        "unnamed_empty"):
            with self.subTest(outcome=outcome):
                rows = [_row(outcome, 8, {"message": ap.ELIGIBLE})]
                out = ap.tally(rows, _axis({"message": (1, 1)}), IDENT)
                self.assertEqual(out["findings_total"], 0)


class TheRowsNameTheirKeys(unittest.TestCase):
    """Ключи напечатанных строк — утверждение, и подмена ИМЕНИ ключа тиха.

    Батарея первого прохода мерила ЧИСЛА строк и была слепа к их именам: мутант
    `"coord" → "MUT"` в составе места не менял ни одного счёта, и читатель
    артефакта получил бы место без адреса при зелёных тестах (урок #786).
    """

    def test_a_finding_row_carries_exactly_the_place_and_the_verdict(self):
        row = ap.classify(_row("unnamed_candidate_outside", 8,
                               {"message": ap.ELIGIBLE}),
                          {"message": {ap.BROAD_READING: 1,
                                       ap.NARROW_READING: 1}},
                          IDENT, ap.BROAD_READING)
        self.assertEqual(
            sorted(row), ["candidates", "coord", "module", "n", "outcome",
                          "population_unmeasured", "reason", "unsupported_names",
                          "verdict"])
        self.assertEqual(row["module"], "m.a")
        self.assertEqual(row["coord"], ".x")
        self.assertEqual(row["n"], 8)
        self.assertEqual(row["outcome"], "unnamed_candidate_outside")
        # Причина у РАЗРЕШЁННОГО вердикта пуста, и это тоже утверждение:
        # непустая причина рядом с вердиктом читалась бы как отказ.
        self.assertEqual(row["reason"], "")

    def test_a_name_addressable_row_says_which_name_suffices(self):
        row = ap.classify(_row("unnamed_candidate_outside", 8,
                               {"label": ap.ELIGIBLE}),
                          {"label": {ap.BROAD_READING: 4,
                                     ap.NARROW_READING: 4}},
                          IDENT, ap.BROAD_READING)
        self.assertEqual(sorted(row),
                         ["candidates", "coord", "module", "n", "outcome",
                          "reason", "supported_names", "verdict"])
        self.assertEqual(row["reason"], "")

    def test_a_row_without_a_length_names_the_place_too(self):
        rows = [_row("unnamed_candidate_outside", None,
                     {"message": ap.ELIGIBLE}, module="m.z", coord=".q")]
        out = ap.tally(rows, _axis({"message": (1, 1)}), IDENT)
        self.assertEqual(out["findings_without_length"],
                         [{"module": "m.z", "coord": ".q",
                           "outcome": "unnamed_candidate_outside",
                           "reason": "у строки нет длины"}])

    def test_an_unstable_key_row_names_the_place_and_the_links(self):
        rows = [_row("unnamed_candidate_outside", 8, {"m": ap.ELIGIBLE},
                     module="m.k", coord=".a[7].b")]
        out = ap.tally(rows, _axis({"m": (1, 1)}), IDENT)
        self.assertEqual(out["place_key"]["key_positional"],
                         [{"module": "m.k", "coord": ".a[7].b",
                           "positional_links": ["[7]"]}])

    def test_a_kind_row_names_the_place_and_each_candidate(self):
        rows = [_row("unnamed_candidate_outside", 8, {"stamp": ap.ELIGIBLE},
                     module="m.one", coord=".days")]
        out = ap.tally(rows, _axis({"stamp": (1, 1)}), IDENT,
                       kind_census=lambda names: _kind(
                           {"stamp": _clock_row(NOT_DERIVED)}))
        self.assertEqual(out["kind_at_place"]["rows"],
                         [{"module": "m.one", "coord": ".days",
                           "verdict": "place_resolves",
                           "candidates": {"stamp": {"outcome": "clean_here",
                                                    "why": ""}}}])

    def test_the_sections_own_keys_are_pinned_too(self):
        """Имена ключей РАЗДЕЛА, а не только строк: их подмена тоже тиха."""
        out = ap.tally([_row("unnamed_candidate_outside", 8,
                             {"m": ap.ELIGIBLE})],
                       _axis({"m": (1, 1)}), IDENT,
                       kind_census=lambda names: _kind(
                           {"m": _clock_row(NOT_DERIVED)}))
        self.assertEqual(
            sorted(out),
            ["findings_total", "findings_without_length", "global_evidence_min",
             "identity_fields_today", "kind_at_place", "place_key",
             "place_only", "place_only_rows", "population_histogram",
             "reader_price", "reading_disagreement", "status",
             "unmeasured_rows", "verdict", "verdict_reasons", "verdicts",
             "verdicts_narrow_reading", "what_it_does_not_prove"])
        self.assertEqual(sorted(out["place_key"]),
                         ["key_positional", "key_unmeasured",
                          "producers_touched", "rows_needed"])
        self.assertEqual(sorted(out["kind_at_place"]),
                         ["imported_refusals", "rows", "status", "verdicts"])
        self.assertEqual(sorted(out["reading_disagreement"]),
                         ["gap", "place_only_broad", "place_only_narrow",
                          "places_only_narrow_says"])

    def test_the_price_section_names_its_own_keys(self):
        out = ap.reader_price(REPO, roots=("spa_core/monitoring",))
        self.assertEqual(
            sorted(out),
            ["files_parsed", "files_unmeasured", "one_sidedness",
             "place_available", "runtime_sites", "sites_in_tests",
             "sites_runtime", "sites_total", "status"])

    def test_the_price_row_names_the_door_the_place_and_the_file(self):
        out = ap.reader_price(REPO, roots=("spa_core/monitoring",))
        self.assertTrue(out["runtime_sites"])
        self.assertEqual(sorted(out["runtime_sites"][0]),
                         ["coord_in_scope", "door", "function", "in_tests",
                          "line", "module", "place_available",
                          "producer_in_scope"])


class TheNamesOfThePlaceAreAClaim(unittest.TestCase):
    """Каждое имя в двух перечнях — утверждение о коде, и оно мерится."""

    def test_every_coord_name_is_recognised(self):
        for name in sorted(ap._COORD_NAMES):
            with self.subTest(name=name):
                sites, _ = ap.door_sites(f"def f({name}):\n"
                                         f"    return indexed(items)\n")
                self.assertEqual(sites[0]["place_available"], "coord_only")

    def test_every_producer_name_is_recognised(self):
        for name in sorted(ap._PRODUCER_NAMES):
            with self.subTest(name=name):
                sites, _ = ap.door_sites(f"def f({name}):\n"
                                         f"    return indexed(items)\n")
                self.assertEqual(sites[0]["place_available"], "producer_only")

    def test_a_name_from_neither_set_is_not_a_place(self):
        sites, _ = ap.door_sites("def f(whatever):\n"
                                 "    return indexed(items)\n")
        self.assertEqual(sites[0]["place_available"], "neither")

    def test_both_default_roots_contribute_files(self):
        """Каждый корень — утверждение: пустой корень не нашёл бы ни двери."""
        for root in ap.DEFAULT_ROOTS:
            with self.subTest(root=root):
                self.assertTrue((REPO / root).is_dir(), root)
        narrow = ap.reader_price(REPO, roots=("spa_core",))
        both = ap.reader_price(REPO, roots=ap.DEFAULT_ROOTS)
        self.assertGreaterEqual(both["files_parsed"], narrow["files_parsed"])
        self.assertGreater(both["files_parsed"], 0)

    def test_the_doors_are_the_two_the_rule_exports(self):
        from spa_core.monitoring import run_identity_key_price as rikp
        for door in ap.IDENTITY_DOORS:
            with self.subTest(door=door):
                self.assertTrue(callable(getattr(rikp, door)), door)


class TwoReadingsOfThePopulation(unittest.TestCase):
    """Дефект ADR-503/541 (ADR-695) не повторяется: прочтений ДВА, и оба видны."""

    def test_the_disagreement_is_a_number_not_a_silent_choice(self):
        rows = [_row("unnamed_candidate_outside", 8,
                     {"message": ap.ELIGIBLE}, module="m.a", coord=".a"),
                _row("unnamed_candidate_outside", 6,
                     {"label": ap.ELIGIBLE}, module="m.b", coord=".b")]
        # `label`: узкое число 1 (перепись печатает одну строку), широкое 4.
        out = ap.tally(rows, _axis({"message": (1, 1), "label": (1, 4)}), IDENT)
        self.assertEqual(out["place_only"], 1)
        self.assertEqual(out["reading_disagreement"]["place_only_narrow"], 2)
        self.assertEqual(out["reading_disagreement"]["gap"], 1)
        self.assertEqual(out["reading_disagreement"]["places_only_narrow_says"],
                         ["m.b.b"])
        self.assertTrue(any("ADR-695" in r for r in out["verdict_reasons"]))

    def test_a_name_the_census_never_prints_is_unmeasured_narrowly(self):
        """``counted is None`` — третий исход соседа, и ноль из него не делается."""
        rows = [_row("unnamed_candidate_outside", 8, {"message": ap.ELIGIBLE})]
        out = ap.tally(rows, _axis({"message": (None, 5)}), IDENT)
        self.assertEqual(out["verdicts"], {"name_addressable": 1})
        self.assertEqual(out["verdicts_narrow_reading"], {"unmeasured": 1})

    def test_a_mixed_finding_is_place_only_and_names_the_unmeasured_half(self):
        """Один кандидат измерен и не подпёрт, другой НЕ измерен.

        Вердикт `place_only` держится на ПЕРВОМ (адрес его разрешает заведомо),
        а про второй сказано вслух: иначе «только местом» читалось бы как
        «про имя всё измерено». На сегодняшнем населении таких строк ноль —
        поэтому поведение закреплено сценой, а не замером.
        """
        rows = [_row("unnamed_candidate_outside", 8,
                     {"weak": ap.ELIGIBLE, "ghost": ap.ELIGIBLE})]
        out = ap.tally(rows, _axis({"weak": (1, 1)}), IDENT)
        row = out["place_only_rows"][0]
        self.assertEqual(out["verdicts"], {"place_only": 1})
        self.assertEqual(row["unsupported_names"], ["weak"])
        self.assertEqual(row["population_unmeasured"], ["ghost"])

    def test_the_histogram_shows_what_a_different_threshold_would_do(self):
        rows = [_row("unnamed_candidate_outside", 8, {"a": ap.ELIGIBLE},
                     module="m.a"),
                _row("unnamed_candidate_outside", 8, {"b": ap.ELIGIBLE},
                     module="m.b"),
                _row("unnamed_candidate_outside", 8, {"c": ap.ELIGIBLE},
                     module="m.c"),
                _row("unnamed_candidate_outside", 8, {"d": ap.ELIGIBLE},
                     module="m.d")]
        out = ap.tally(rows, _axis({"a": (1, 1), "b": (2, 2), "c": (9, 9),
                                    "d": (None, None)}), IDENT)
        self.assertEqual(out["population_histogram"][ap.BROAD_READING],
                         {"1": 1, "2": 1, "5+": 1, "unmeasured": 1})

    def test_the_last_named_bucket_is_four_and_five_is_the_tail(self):
        """Граница ведра пинится ОБЕИМИ сторонами: 4 своим именем, 5 — хвостом."""
        rows = [_row("unnamed_candidate_outside", 8, {"four": ap.ELIGIBLE},
                     module="m.a"),
                _row("unnamed_candidate_outside", 8, {"five": ap.ELIGIBLE},
                     module="m.b")]
        out = ap.tally(rows, _axis({"four": (4, 4), "five": (5, 5)}), IDENT)
        self.assertEqual(out["population_histogram"][ap.BROAD_READING],
                         {"4": 1, "5+": 1})

    def test_the_best_candidate_decides_the_bucket_not_the_first(self):
        rows = [_row("unnamed_candidate_outside", 8,
                     {"weak": ap.ELIGIBLE, "strong": ap.ELIGIBLE})]
        out = ap.tally(rows, _axis({"weak": (1, 1), "strong": (3, 3)}), IDENT)
        self.assertEqual(out["population_histogram"][ap.BROAD_READING],
                         {"3": 1})

    def test_the_threshold_is_the_one_ADR_503_named(self):
        self.assertEqual(ap.GLOBAL_EVIDENCE_MIN, 2)


class TheSecondRefusalIsTheKindAtTheProducer(unittest.TestCase):
    """Населения адрес не требует; часы у производителя он лечит НЕ всегда."""

    def _rows(self):
        return [_row("unnamed_candidate_outside", 8, {"stamp": ap.ELIGIBLE},
                     module="spa_core.monitoring.mine", coord=".days")]

    def test_a_clock_in_the_producers_own_file_is_not_cured_by_an_address(self):
        kind = _kind({"stamp": _clock_row(
            WALL_CLOCK, wall=["spa_core/monitoring/mine.py:12 "
                              "wall_clock_derived (dt.now())"])})
        out = ap.tally(self._rows(), _axis({"stamp": (1, 1)}), IDENT,
                       kind_census=lambda names: kind)
        self.assertEqual(out["place_only"], 1)
        section = out["kind_at_place"]
        self.assertEqual(section["verdicts"], {"place_refused_by_clock": 1})
        self.assertEqual(section["imported_refusals"], 0)
        self.assertTrue(any("НЕ лечит" in r for r in out["verdict_reasons"]))

    def test_positive_control_a_clock_in_a_foreign_file_is_an_imported_refusal(self):
        """ОБРАТНАЯ сторона — и это ровно вред, названный заказом."""
        kind = _kind({"stamp": _clock_row(
            WALL_CLOCK, wall=["spa_core/monitoring/other.py:12 "
                              "wall_clock_derived (dt.now())"])})
        out = ap.tally(self._rows(), _axis({"stamp": (1, 1)}), IDENT,
                       kind_census=lambda names: kind)
        section = out["kind_at_place"]
        self.assertEqual(section["verdicts"], {"place_resolves": 1})
        self.assertEqual(section["imported_refusals"], 1)
        self.assertTrue(any("ЧУЖОГО файла" in r
                            for r in out["verdict_reasons"]))

    def test_a_truncated_site_list_is_unmeasured_not_clean(self):
        """Укорочение не читается как «в этом файле часов нет»."""
        kind = _kind({"stamp": _clock_row(
            WALL_CLOCK, wall=["spa_core/monitoring/other.py:1 x"],
            wall_count=9)})
        outcome, why = ap.clock_at_place("stamp",
                                        "spa_core.monitoring.mine",
                                        kind["fields"]["stamp"])
        self.assertEqual(outcome, "unmeasured")
        self.assertIn("укорочен", why)
        out = ap.tally(self._rows(), _axis({"stamp": (1, 1)}), IDENT,
                       kind_census=lambda names: kind)
        self.assertEqual(out["kind_at_place"]["verdicts"], {"unmeasured": 1})

    def test_no_clock_anywhere_is_clean_at_this_place(self):
        kind = _kind({"stamp": _clock_row(NOT_DERIVED)})
        out = ap.tally(self._rows(), _axis({"stamp": (1, 1)}), IDENT,
                       kind_census=lambda names: kind)
        self.assertEqual(out["kind_at_place"]["verdicts"],
                         {"place_resolves": 1})
        self.assertEqual(out["kind_at_place"]["imported_refusals"], 0)

    def test_a_named_read_counts_as_a_clock_too(self):
        kind = _kind({"stamp": _clock_row(
            CLOCK_NAMED_READ,
            read=["spa_core/monitoring/mine.py:7 clock_named_read (x)"])})
        outcome, _ = ap.clock_at_place("stamp", "spa_core.monitoring.mine",
                                       kind["fields"]["stamp"])
        self.assertEqual(outcome, "clock_here")

    def test_an_unmeasured_kind_verdict_stays_unmeasured(self):
        row = dict(_clock_row(UNMEASURED),
                   why_unmeasured="производитель поля не найден в дереве")
        outcome, why = ap.clock_at_place("stamp", "spa_core.monitoring.mine",
                                        row)
        self.assertEqual(outcome, "unmeasured")
        self.assertIn("не найден", why)

    def test_a_place_without_a_producer_name_is_unmeasured(self):
        outcome, why = ap.clock_at_place("stamp", None,
                                        _clock_row(NOT_DERIVED))
        self.assertEqual(outcome, "unmeasured")
        self.assertIn("производителя", why)
        self.assertIsNone(ap.producer_file(None))
        self.assertIsNone(ap.producer_file(""))

    def test_the_kind_is_unmeasured_when_nobody_asked_it(self):
        out = ap.tally(self._rows(), _axis({"stamp": (1, 1)}), IDENT)
        self.assertEqual(out["kind_at_place"]["status"], "UNMEASURED")
        self.assertIn("это не «лечит»", out["kind_at_place"]["reason"])

    def test_a_broken_kind_document_refuses_rather_than_cures(self):
        for doc in (None, {}, {"fields": []}):
            with self.subTest(doc=doc):
                section = ap.kind_at_place([], doc)
                self.assertEqual(section["status"], "UNMEASURED")

    def test_one_clean_candidate_out_of_several_resolves_the_place(self):
        rows = [_row("unnamed_candidate_outside", 8,
                     {"stamp": ap.ELIGIBLE, "order": ap.ELIGIBLE},
                     module="spa_core.monitoring.mine", coord=".days")]
        kind = _kind({
            "stamp": _clock_row(WALL_CLOCK,
                                wall=["spa_core/monitoring/mine.py:1 x"]),
            "order": _clock_row(NOT_DERIVED)})
        out = ap.tally(rows, _axis({"stamp": (1, 1), "order": (1, 1)}), IDENT,
                       kind_census=lambda names: kind)
        self.assertEqual(out["kind_at_place"]["verdicts"],
                         {"place_resolves": 1})

    def test_the_kind_is_asked_about_the_place_only_candidates(self):
        """Род спрашивается ровно у тех имён, о которых спор, и не шире."""
        asked = []

        def _census(names):
            asked.append(list(names))
            return _kind({n: _clock_row(NOT_DERIVED) for n in names})

        rows = [_row("unnamed_candidate_outside", 8, {"stamp": ap.ELIGIBLE},
                     module="m.a", coord=".a"),
                _row("unnamed_candidate_outside", 8, {"wide": ap.ELIGIBLE},
                     module="m.b", coord=".b")]
        ap.tally(rows, _axis({"stamp": (1, 1), "wide": (7, 7)}), IDENT,
                 kind_census=_census)
        self.assertEqual(asked, [["stamp"]])


class TheKeyOfThePlaceItself(unittest.TestCase):
    """Таблица адресов ключуется координатой, и она бывает позиционной сама."""

    def test_a_positional_link_in_the_places_own_coord_is_found(self):
        self.assertEqual(ap.positional_links(".findings[8].legs"), ["[8]"])
        self.assertEqual(ap.positional_links(".a[3].b[12]"), ["[3]", "[12]"])

    def test_a_named_index_is_not_positional(self):
        self.assertEqual(ap.positional_links('.days[date="2026-09-11"].legs'),
                         [])
        self.assertEqual(ap.positional_links('.x[protocol="aave_v3"]'), [])
        self.assertEqual(ap.positional_links(None), [])

    def test_the_table_names_its_rows_producers_and_unstable_keys(self):
        rows = [_row("unnamed_candidate_outside", 8, {"m": ap.ELIGIBLE},
                     module="m.a", coord=".findings[8].legs"),
                _row("unnamed_candidate_outside", 8, {"m": ap.ELIGIBLE},
                     module="m.a", coord=".other"),
                _row("unnamed_candidate_outside", 8, {"m": ap.ELIGIBLE},
                     module="m.b", coord=".third")]
        out = ap.tally(rows, _axis({"m": (1, 1)}), IDENT)
        key = out["place_key"]
        self.assertEqual(key["rows_needed"], 3)
        self.assertEqual(key["producers_touched"], 2)
        self.assertEqual([r["coord"] for r in key["key_positional"]],
                         [".findings[8].legs"])
        self.assertTrue(any("САМА позиционна" in r
                            for r in out["verdict_reasons"]))

    def test_a_place_without_a_coord_is_unmeasured_not_stable(self):
        """Оба вида отсутствия адреса: нет ключа ВОВСЕ и ПУСТАЯ строка."""
        for coord in (None, ""):
            with self.subTest(coord=coord):
                rows = [_row("unnamed_candidate_outside", 8,
                             {"m": ap.ELIGIBLE}, coord=coord)]
                out = ap.tally(rows, _axis({"m": (1, 1)}), IDENT)
                self.assertEqual(
                    out["place_key"]["key_unmeasured"],
                    [{"module": "m.a", "coord": coord,
                      "reason": "у места нет адреса-координаты"}])
                self.assertEqual(out["place_key"]["key_positional"], [])

    def test_the_shortest_real_finding_is_two_elements(self):
        """Нижняя кромка знаменателя пинится: n=2 — находка, n=1 — нет."""
        for n, expect in ((2, 1), (1, 0)):
            with self.subTest(n=n):
                rows = [_row("unnamed_candidate_outside", n,
                             {"m": ap.ELIGIBLE})]
                out = ap.tally(rows, _axis({"m": (1, 1)}), IDENT)
                self.assertEqual(out["findings_total"], expect)


class ThePriceOfTheCoordinateToReaders(unittest.TestCase):
    """Цена меряется ЗОВАМИ дверей личности, а не на глаз."""

    SCENE = (
        "def with_both(module, coord):\n"
        "    return indexed(items, element_identity(items))\n"
        "\n"
        "def with_coord_only(path):\n"
        "    return element_identity(items)\n"
        "\n"
        "def with_neither():\n"
        "    return indexed(items)\n"
        "\n"
        "def not_a_door():\n"
        "    return something_else(items)\n"
    )

    def test_the_three_classes_of_availability(self):
        sites, why = ap.door_sites(self.SCENE)
        self.assertIsNone(why)
        got = {s["function"]: s["place_available"] for s in sites}
        self.assertEqual(got, {"with_both": "both",
                               "with_coord_only": "coord_only",
                               "with_neither": "neither"})

    def test_both_doors_are_counted_not_just_one(self):
        sites, _ = ap.door_sites(self.SCENE)
        self.assertEqual(sorted({s["door"] for s in sites}),
                         ["element_identity", "indexed"])
        self.assertEqual(len(sites), 4)

    def test_an_attribute_call_is_a_door_too(self):
        sites, _ = ap.door_sites("def f(coord):\n    return mod.indexed(x)\n")
        self.assertEqual([s["door"] for s in sites], ["indexed"])
        self.assertEqual(sites[0]["place_available"], "coord_only")

    def test_a_name_bound_by_assignment_counts_as_available(self):
        sites, _ = ap.door_sites("def f():\n"
                                 "    coord = '.x'\n"
                                 "    module = 'm'\n"
                                 "    return indexed(items)\n")
        self.assertEqual(sites[0]["place_available"], "both")

    def test_an_enclosing_scope_counts_too(self):
        sites, _ = ap.door_sites("def outer(module, coord):\n"
                                 "    def inner():\n"
                                 "        return indexed(items)\n")
        self.assertEqual(sites[0]["place_available"], "both")
        self.assertEqual(sites[0]["function"], "inner")

    def test_a_file_that_does_not_parse_is_a_reason_not_a_zero(self):
        sites, why = ap.door_sites("def f(:\n")
        self.assertEqual(sites, [])
        self.assertIn("не разобран", str(why))

    def test_a_missing_root_is_unmeasured_with_a_cause(self):
        out = ap.reader_price(REPO, roots=("no_such_dir",))
        self.assertEqual(out["status"], "UNMEASURED")
        self.assertEqual(out["files_unmeasured"]["no_such_dir"],
                         "каталога нет в дереве")

    def test_the_live_tree_is_measured_and_test_sites_are_counted_apart(self):
        out = ap.reader_price(REPO)
        self.assertEqual(out["status"], "MEASURED")
        self.assertGreater(out["files_parsed"], 100)
        # Зовы В ТЕСТАХ из знаменателя не исчезают: переписать их всё равно
        # придётся, и спрятать их значило бы занизить цену.
        self.assertEqual(out["sites_total"],
                         out["sites_runtime"] + out["sites_in_tests"])
        self.assertGreater(out["sites_in_tests"], 0)
        self.assertEqual(sum(out["place_available"].values()),
                         out["sites_runtime"])

    def test_the_one_sidedness_of_the_price_is_said_aloud(self):
        out = ap.reader_price(REPO, roots=("spa_core/monitoring",))
        self.assertIn("ВЕРХНЯЯ граница", out["one_sidedness"])


class TheReportSaysTheNumbersAndTheirLimits(unittest.TestCase):

    def _measured(self) -> dict:
        rows = [_row("unnamed_candidate_outside", 8, {"message": ap.ELIGIBLE},
                     module="m.a", coord=".findings[2]"),
                _row("unnamed_no_candidate", 4, {"note": "not_unique"},
                     module="m.b", coord=".other")]
        return ap.tally(rows, _axis({"message": (1, 1), "note": (0, 0)}),
                        IDENT, price=ap.reader_price(REPO,
                                                     roots=("spa_core/monitoring",)),
                        kind_census=lambda names: _kind(
                            {n: _clock_row(NOT_DERIVED) for n in names}))

    def test_it_prints_the_headline_numbers(self):
        text = "\n".join(ap.report(self._measured()))
        self.assertIn("PLACE_RESOLVES_WHAT_A_NAME_CANNOT", text)
        self.assertIn("находок 2", text)
        self.assertIn("разрешимы ТОЛЬКО местом 1", text)
        self.assertIn("порог населения 2", text)
        # Числа таблицы печатаются ИЗ своих ключей: подмена имени ключа дала бы
        # «строк None», и проверка обязана это увидеть.
        self.assertIn("таблица адресов: строк 1 · производителей 1", text)
        self.assertIn("ключ САМ позиционен у 1", text)
        self.assertIn("ключа нет у 0", text)
        self.assertIn("зовов дверей", text)
        self.assertIn("два прочтения населения: узкое 1 против широкого 1 "
                      "(расхождение 0)", text)
        self.assertNotIn("None", text)
        self.assertIn("ВТОРОЙ отказ", text)
        self.assertIn("НЕ ДОКАЗЫВАЕТ", text)

    def test_a_missing_section_is_not_measured_rather_than_clean(self):
        for axis in (None, "строка", {"status": "UNMEASURED",
                                      "reason": "оси нет"}):
            with self.subTest(axis=axis):
                text = "\n".join(ap.report(axis))
                self.assertIn("НЕ ИЗМЕРЕНО", text)
                self.assertNotIn("PLACE_RESOLVES_WHAT_A_NAME_CANNOT", text)

    def test_the_price_is_named_as_unmeasured_when_it_was_not_measured(self):
        out = ap.tally([_row("unnamed_candidate_outside", 8,
                             {"message": ap.ELIGIBLE})],
                       _axis({"message": (1, 1)}), IDENT)
        text = "\n".join(ap.report(out))
        self.assertIn("цена читателям: НЕ ИЗМЕРЕНО", text)
        self.assertIn("ВТОРОЙ отказ (род у производителя): НЕ ИЗМЕРЕНО", text)

    def test_the_row_list_is_shortened_and_says_so(self):
        rows = [_row("unnamed_candidate_outside", 8, {"m": ap.ELIGIBLE},
                     module=f"m.{i}", coord=f".c{i}") for i in range(12)]
        out = ap.tally(rows, _axis({"m": (1, 1)}), IDENT)
        text = "\n".join(ap.report(out, max_rows=3))
        self.assertIn("ещё 9 мест (укорочено)", text)
        self.assertNotIn("укорочено", "\n".join(ap.report(out,
                                                          max_rows=None)))

    def test_what_it_does_not_prove_says_all_four_things(self):
        claims = self._measured()["what_it_does_not_prove"]
        self.assertEqual(len(claims), 4)
        for needle in ("АДРЕС находки", "МИНИМУМ", "верхняя граница",
                       "замер, а не правило"):
            self.assertTrue(any(needle in c for c in claims), needle)


class TheModuleDeclaresNoGate(unittest.TestCase):
    """Прибор только ЧИТАЕТ: ни одного дописанного имени, ни одного порога."""

    def test_it_never_mutates_the_identity_tuple(self):
        source = (REPO / "spa_core" / "monitoring"
                  / "finding_address_price.py").read_text(encoding="utf-8")
        for forbidden in ("_IDENTITY_FIELDS.append", "_IDENTITY_FIELDS +=",
                          "_MEASURED_IDENTITY_FIELDS", "atomic_save",
                          "approved"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_the_subject_outcomes_are_the_censuss_own_pair(self):
        self.assertEqual(sorted(ap.FINDING_OUTCOMES),
                         sorted(census._DICT_OUTCOMES))

    def test_the_eligible_mark_is_the_one_the_probe_writes(self):
        self.assertEqual(ap.ELIGIBLE, cd.ELIGIBLE)
        self.assertEqual(ap.COMPOSITION_KEY, cd.COMPOSITION_KEY)

    def test_the_readings_are_the_keys_the_neighbour_prints(self):
        row = cd.tally([_row("unnamed_candidate_outside", 5,
                             {"message": ap.ELIGIBLE})],
                       {"message": 1})["rows"][0]
        for reading in ap.READINGS:
            self.assertIn(reading, row)


class WiredIntoTheCensus(unittest.TestCase):
    """Проводка: раздел есть у свода, у отчёта и у читателя-офиса."""

    def _rows(self) -> dict:
        return {"m.a": {"entry": "run", "truncated": False, "lists": [
            {"outcome": "unnamed_candidate_outside", "n": 5, "coord": ".x",
             "candidates": ["detail"],
             ap.COMPOSITION_KEY: {"detail": ap.ELIGIBLE}},
            {"outcome": "named", "n": 9, "coord": ".y", "field": "protocol",
             ap.COMPOSITION_KEY: {"detail": ap.ELIGIBLE}},
        ]}}

    def test_the_tally_carries_the_section(self):
        counts = census.tally(self._rows())
        section = counts["finding_address"]
        self.assertEqual(section["status"], "MEASURED")
        self.assertEqual(section["findings_total"], 1)

    def test_the_population_axis_is_computed_once_and_shared(self):
        """ОДИН объект на два ключа: второй зов дал бы второе число."""
        calls = []
        real = census.cand_denom.tally

        def _counting(rows, counted):
            calls.append(1)
            return real(rows, counted)

        census.cand_denom.tally = _counting
        try:
            counts = census.tally(self._rows())
        finally:
            census.cand_denom.tally = real
        self.assertEqual(len(calls), 1)
        # И это ТОТ ЖЕ объект, что напечатан соседним разделом: вердикт адреса
        # обязан относиться к числу, которое читатель видит.
        self.assertEqual(
            counts["candidate_denominator"]["rows"][0]["eligible_anywhere"],
            2)
        self.assertEqual(counts["finding_address"]["verdicts"],
                         {"name_addressable": 1})

    def test_without_a_tree_the_price_and_the_kind_stay_unmeasured(self):
        counts = census.tally(self._rows())
        self.assertEqual(counts["finding_address"]["reader_price"]["status"],
                         "UNMEASURED")
        self.assertEqual(counts["finding_address"]["kind_at_place"]["status"],
                         "UNMEASURED")

    def test_with_a_tree_both_are_measured(self):
        counts = census.tally(self._rows(), tree_root=REPO)
        section = counts["finding_address"]
        self.assertEqual(section["reader_price"]["status"], "MEASURED")
        # Кандидатов, разрешимых только местом, на этой сцене нет ⇒ род
        # спрашивать не о чем, и раздел честно говорит «измерено, строк ноль».
        self.assertEqual(section["kind_at_place"]["status"], "MEASURED")
        self.assertEqual(section["kind_at_place"]["rows"], [])

    def test_the_report_prints_the_section(self):
        doc = {"status": "FINDING", "counts": census.tally(self._rows()),
               "invoked_by": {}, "advisory": "—"}
        text = "\n".join(census.report(doc))
        self.assertIn("[АДРЕС НАХОДКИ]", text)

    def test_an_old_style_doc_says_NOT_MEASURED_rather_than_nothing_resolves(self):
        counts = census.tally(self._rows())
        counts.pop("finding_address")
        doc = {"status": "FINDING", "counts": counts, "invoked_by": {},
               "advisory": "—"}
        text = "\n".join(census.report(doc))
        self.assertIn("отчёт СТАРОГО ОБРАЗЦА", text)
        # Отрицание прицеливается в вердикт ЭТОГО раздела (урок #834): слово
        # «ВЕРДИКТ» печатают и соседние оси.
        self.assertNotIn("PLACE_RESOLVES_WHAT_A_NAME_CANNOT", text)
        self.assertNotIn("NO_POPULATION_FOR_PLACE_ADDRESSING", text)

    def test_the_section_is_printed_even_without_candidates(self):
        """Третий исход раздела не имеет права исчезнуть на чистом документе."""
        counts = census.tally({"m.a": {"entry": "run", "truncated": False,
                                       "lists": []}})
        doc = {"status": "CLEAN", "counts": counts, "invoked_by": {},
               "advisory": "—"}
        self.assertIn("[АДРЕС НАХОДКИ]", "\n".join(census.report(doc)))

    def test_the_office_declares_the_key_as_read(self):
        declared = _office()._READ_SCHEMA[census.ARTIFACT]
        self.assertIn("counts.finding_address", declared)


if __name__ == "__main__":                                    # pragma: no cover
    unittest.main()
