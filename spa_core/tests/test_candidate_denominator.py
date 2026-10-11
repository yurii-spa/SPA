"""Разница «поле ЕСТЬ» против «поле ГОДНО» — заказ G115 п. 3 (хвост ADR-541).

## Что измерялось ДО написания файла

Перепись `list_identity_census` печатает кандидату население и длину. Население
считается по спискам, у которых поле ГОДНО, **и только среди списков без
личности**: инкремент стоит под условием `outcome == "unnamed_candidate_outside"`.
Замер живого артефакта 09.10: словарных списков с личностью — **69**, без
личности с кандидатом — **56**. То есть больше половины словарного населения из
счёта имени выпадает по признаку, который к самому имени не относится, и об этом
не говорит ни одна строка отчёта.

Мерило ADR-503 (решение 2 ADR-541) отвергло всю четвёрку словами «население
n ≤ 2». Заказ спрашивает, не свойство ли это самой переписи.

## Почему проверок несколько, а не одна

Разница у имени раскладывается на ДВЕ разные разницы, и они говорят
ПРОТИВОПОЛОЖНОЕ:

| разница | что значит | куда идёт |
|---|---|---|
| `eligible_anywhere − counted` | тот же предикат на широком знаменателе даёт больше | **артефакт знаменателя**, вердикт |
| `present − eligible_anywhere` | поле есть там, где оно НЕ годно | свидетельство ПРОТИВ имени, своё число |

Поэтому у каждой половины здесь свой контроль в обе стороны: сцена, где есть
только вторая разница, обязана давать `NOT_AN_ARTIFACT` — иначе прибор
продвигал бы имя наблюдением, которое его опровергает.

Часы в этом файле не участвуют вовсе: предмет — состав ответа, а не свежесть.
Литеральных дат нет; живое `data/` не читается — все сцены собраны руками.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from spa_core.monitoring import _list_identity_probe as probe
from spa_core.monitoring import candidate_denominator as cd
from spa_core.monitoring import list_identity_census as census
from spa_core.monitoring.run_identity_key_price import scalar_refusal

REPO = Path(__file__).resolve().parents[2]
OFFICE = REPO / "scripts" / "consume_office_reports.py"


def _office():
    """Шаг 0-офис — модулем, а не разбором текста.

    Читается ИМЕННО объявленный словарь, а не литерал в исходнике: объявление,
    собранное из двух кусков, разбор текста прочёл бы пустым и назвал бы
    исправную проводку отсутствующей.
    """
    spec = importlib.util.spec_from_file_location("_office_under_test", OFFICE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _list(outcome: str, n: int, composition: dict, *, module: str = "m.a",
          coord: str = ".x") -> dict:
    """Одна строка зонда — ровно та форма, которую производит `classify_list`."""
    return {"outcome": outcome, "n": n, "module": module, "coord": coord,
            cd.COMPOSITION_KEY: dict(composition)}


class TheArtifactOfTheDenominator(unittest.TestCase):
    """Главная находка заказа: НАЗВАННЫЙ список из счёта имени выпадает."""

    def test_eligible_on_a_named_list_is_invisible_to_the_census_and_named_here(self):
        rows = [
            _list("unnamed_candidate_outside", 5, {"message": cd.ELIGIBLE}),
            _list("named", 9, {"message": cd.ELIGIBLE}, module="m.b"),
            _list("named", 7, {"message": cd.ELIGIBLE}, module="m.c"),
        ]
        axis = cd.tally(rows, {"message": 1})
        row = axis["rows"][0]
        self.assertEqual(row["field"], "message")
        # Население переписи — ВХОД, и оно напечатано как есть.
        self.assertEqual(row["counted"], 1)
        # Тот же предикат на широком знаменателе даёт втрое больше.
        self.assertEqual(row["eligible_anywhere"], 3)
        self.assertEqual(row["eligible_on_named_lists"], 2)
        self.assertEqual(axis["verdict"], "DENOMINATOR_ARTIFACT")
        self.assertEqual([r["field"] for r in axis["counted_understates"]],
                         ["message"])

    def test_positive_control_without_named_lists_there_is_no_artifact(self):
        """ОБРАТНАЯ сторона: та же сцена без списков с личностью — чисто."""
        rows = [_list("unnamed_candidate_outside", 5, {"message": cd.ELIGIBLE})]
        axis = cd.tally(rows, {"message": 1})
        self.assertEqual(axis["verdict"], "NOT_AN_ARTIFACT")
        self.assertEqual(axis["counted_understates"], [])
        self.assertEqual(axis["rows"][0]["eligible_anywhere"], 1)

    def test_a_name_the_census_never_prints_is_named_not_a_zero(self):
        """Поле, годное ТОЛЬКО у названных списков, переписи не видно вовсе."""
        rows = [_list("named", 9, {"ticket": cd.ELIGIBLE})]
        axis = cd.tally(rows, {})
        self.assertEqual(axis["names_invisible_to_the_census"], ["ticket"])
        row = axis["rows"][0]
        self.assertIsNone(row["counted"])
        self.assertTrue(row["counted_unmeasured"])
        self.assertEqual(row["eligible_anywhere"], 1)
        self.assertEqual(axis["verdict"], "DENOMINATOR_ARTIFACT")

    def test_the_two_sets_are_printed_as_NESTED_not_as_peers(self):
        """Невидимое имя занижено ТОЖЕ: сложи два числа — имён станет больше."""
        rows = [_list("named", 9, {"ticket": cd.ELIGIBLE})]
        axis = cd.tally(rows, {})
        text = "\n".join(cd.report(axis))
        self.assertIn("из них не печатается переписью вовсе", text)
        self.assertEqual(len(axis["counted_understates"]), 1)
        self.assertEqual(len(axis["names_invisible_to_the_census"]), 1)


class TheSecondDifferenceArguesAGAINSTTheName(unittest.TestCase):
    """`present − eligible` не есть поправка населения, и вердиктом не правит."""

    def test_present_but_refused_is_its_own_number(self):
        rows = [
            _list("unnamed_candidate_outside", 5,
                  {"detail": cd.ELIGIBLE, "note": "not_unique"}),
            _list("named", 9, {"note": "not_unique"}, module="m.b"),
            _list("named", 4, {"note": "not_scalar"}, module="m.c"),
        ]
        axis = cd.tally(rows, {"detail": 1})
        note = {r["field"]: r for r in axis["rows"]}["note"]
        self.assertEqual(note["present"], 3)
        self.assertEqual(note["eligible_anywhere"], 0)
        self.assertEqual(note["refused_causes"],
                         {"not_scalar": 1, "not_unique": 2})
        self.assertEqual([r["field"] for r in axis["gap_is_unfitness"]], ["note"])

    def test_positive_control_a_pure_unfitness_gap_is_NOT_an_artifact(self):
        """Прибор не вправе продвигать имя числом, которое его опровергает."""
        rows = [
            _list("unnamed_candidate_outside", 5,
                  {"detail": cd.ELIGIBLE, "note": "not_unique"}),
            _list("unnamed_no_candidate", 9, {"note": "not_unique"},
                  module="m.b"),
        ]
        axis = cd.tally(rows, {"detail": 1})
        self.assertTrue(axis["gap_is_unfitness"])
        self.assertEqual(axis["counted_understates"], [])
        self.assertEqual(axis["verdict"], "NOT_AN_ARTIFACT")

    def test_the_report_says_the_second_difference_is_not_a_correction(self):
        rows = [_list("unnamed_candidate_outside", 5,
                      {"detail": cd.ELIGIBLE, "note": "not_unique"})]
        text = "\n".join(cd.report(cd.tally(rows, {"detail": 1})))
        self.assertIn("ВТОРАЯ РАЗНИЦА (ПРОТИВ имени)", text)
        self.assertIn("это не поправка населения", text)


class PopulationIsAnInputNotARecomputation(unittest.TestCase):
    """Одна копия правила: число переписи печатается ЕЁ, а не пересчётом."""

    def test_disagreement_between_census_and_composition_is_said_aloud(self):
        rows = [_list("unnamed_candidate_outside", 5, {"detail": cd.ELIGIBLE})]
        axis = cd.tally(rows, {"detail": 4})
        self.assertEqual(axis["counted_disagrees"],
                         [{"field": "detail", "census": 4,
                           "recomputed_from_composition": 1}])
        # Напечатано число ПЕРЕПИСИ, а не пересчёт: иначе отчёт нёс бы два
        # числа под одним именем.
        self.assertEqual(axis["rows"][0]["counted"], 4)
        text = "\n".join(cd.report(axis))
        self.assertIn("зонд разошёлся", text)

    def test_positive_control_agreement_prints_no_disagreement(self):
        rows = [_list("unnamed_candidate_outside", 5, {"detail": cd.ELIGIBLE})]
        axis = cd.tally(rows, {"detail": 1})
        self.assertEqual(axis["counted_disagrees"], [])
        self.assertNotIn("зонд разошёлся", "\n".join(cd.report(axis)))

    def test_no_population_at_all_is_UNMEASURED_not_a_zero_difference(self):
        axis = cd.tally([_list("named", 3, {"a": cd.ELIGIBLE})], None)
        self.assertEqual(axis["status"], "UNMEASURED")
        self.assertIn("не от чего", axis["reason"])
        self.assertIn("это не «разницы нет»", axis["reason"])
        # Отчёт обязан НАЗВАТЬ причину, а не только слово «НЕ ИЗМЕРЕНО»:
        # мутант, подменивший ключ чтения причины, оставлял слово на месте.
        self.assertEqual(cd.report(axis), [f"НЕ ИЗМЕРЕНО: {axis['reason']}"])


class ThirdOutcomesAreNotZeros(unittest.TestCase):
    """Инв. #17 у каждой двери этого прибора."""

    def test_a_dict_list_without_composition_is_unmeasured_not_empty(self):
        rows = [{"outcome": "named", "n": 5, "module": "m.a", "coord": ".x"}]
        axis = cd.tally(rows, {})
        self.assertEqual(axis["lists_seen"], 1)
        self.assertEqual(len(axis["lists_unmeasured"]), 1)
        self.assertIn("не поставил состав", axis["lists_unmeasured"][0]["reason"])
        # И такая строка в знаменатель разницы НЕ идёт.
        self.assertEqual(axis["dict_lists_multi"], 0)
        self.assertIn("НЕ ИЗМЕРЕНО", "\n".join(cd.report(axis)))

    def test_absent_composition_and_empty_composition_are_different_answers(self):
        self.assertIsNone(cd.composition_of({"outcome": "named"}))
        self.assertEqual(cd.composition_of({cd.COMPOSITION_KEY: {}}), {})

    def test_an_outcome_denying_candidates_while_naming_one_is_a_contradiction(self):
        rows = [_list("unnamed_no_candidate", 5, {"detail": cd.ELIGIBLE})]
        axis = cd.tally(rows, {})
        self.assertEqual(len(axis["probe_contradictions"]), 1)
        self.assertEqual(axis["probe_contradictions"][0]["field"], "detail")
        # Противоречие НЕ сложено в население — иначе улика погасла бы числом.
        self.assertEqual(axis["rows"][0]["eligible_on_named_lists"], 0)
        self.assertIn("НЕ ИЗМЕРЕНО", "\n".join(cd.report(axis)))

    def test_singletons_are_counted_apart_and_never_in_the_wide_number(self):
        rows = [_list("named", 1, {"detail": cd.ELIGIBLE}),
                _list("unnamed_candidate_outside", 4, {"detail": cd.ELIGIBLE},
                      module="m.b")]
        axis = cd.tally(rows, {"detail": 1})
        row = axis["rows"][0]
        self.assertEqual(row["eligible_singletons"], 1)
        self.assertEqual(row["present_singletons"], 1)
        self.assertEqual(row["eligible_anywhere"], 1)
        self.assertEqual(row["present"], 1)
        self.assertEqual(axis["verdict"], "NOT_AN_ARTIFACT")

    def test_a_name_seen_only_in_singletons_is_a_number_not_a_silence(self):
        """Счётчик синглтонов посчитан — значит он обязан быть НАПЕЧАТАН.

        Строки такому имени не даётся намеренно (перепись его тоже не считает,
        годность в списке из одного тривиальна), но без отдельного числа
        наблюдение исчезало бы молча — и исчезало, пока число не завели.
        """
        rows = [_list("named", 1, {"solo": cd.ELIGIBLE}),
                _list("unnamed_candidate_outside", 4, {"detail": cd.ELIGIBLE},
                      module="m.b")]
        axis = cd.tally(rows, {"detail": 1})
        self.assertEqual([r["field"] for r in axis["rows"]], ["detail"])
        self.assertEqual(axis["names_only_on_singletons"], ["solo"])
        self.assertIn("имён только в синглтонах", "\n".join(cd.report(axis)))

    def test_the_singleton_only_number_is_NOT_MEASURED_when_absent(self):
        """Обратная сторона: нет числа ⇒ «не измерено», а не «таких имён нет»."""
        axis = cd.tally([_list("named", 1, {"solo": cd.ELIGIBLE})], {})
        axis.pop("names_only_on_singletons")
        self.assertIn("НЕ ИЗМЕРЕНО", cd.report(axis)[0])

    def test_non_dict_outcomes_take_no_part(self):
        for outcome in ("named_by_value", "unnamed_not_dicts", "unnamed_empty"):
            axis = cd.tally([_list(outcome, 5, {"detail": cd.ELIGIBLE})], {})
            self.assertEqual(axis["lists_seen"], 0, outcome)
            self.assertEqual(axis["names"], 0, outcome)


class TheSceneTheMutationRunAsked(unittest.TestCase):
    """Дыры СЦЕНЫ, названные мутационным прогоном (проход 1: 609/335/274).

    Каждый тест здесь закрывает КОНКРЕТНОГО выжившего мутанта, и названы они
    потому, что без них утверждения прибора нечем опровергнуть: прогон говорит
    не «код плох», а «проверки на это нет ни одной».
    """

    def test_the_multi_denominator_counts_only_lists_longer_than_one(self):
        """Мутант `not singleton` → `singleton`: знаменатель считал бы ОБРАТНОЕ."""
        rows = [_list("named", 1, {"a": cd.ELIGIBLE}),
                _list("named", 5, {"a": cd.ELIGIBLE}, module="m.b"),
                _list("named", 9, {"a": cd.ELIGIBLE}, module="m.c")]
        axis = cd.tally(rows, {})
        self.assertEqual(axis["lists_seen"], 3)
        self.assertEqual(axis["dict_lists_multi"], 2)

    def test_two_elements_are_not_a_singleton_and_one_is(self):
        """Мутанты `1` → `2` и `1` → `0` у порога синглтона: граница ПРЕДЪЯВЛЕНА."""
        two = cd.tally([_list("named", 2, {"a": cd.ELIGIBLE})], {})
        self.assertEqual(two["dict_lists_multi"], 1)
        self.assertEqual(two["rows"][0]["eligible_anywhere"], 1)
        self.assertEqual(two["rows"][0]["eligible_singletons"], 0)
        one = cd.tally([_list("named", 1, {"a": cd.ELIGIBLE})], {})
        self.assertEqual(one["dict_lists_multi"], 0)
        self.assertEqual(one["rows"], [])
        self.assertEqual(one["names_only_on_singletons"], ["a"])

    def test_a_row_without_a_length_is_unmeasured_not_a_singleton(self):
        """Длина — наблюдение (инв. #17): без неё строка не идёт в синглтоны."""
        rows = [{"outcome": "named", "module": "m.a", "coord": ".x",
                 cd.COMPOSITION_KEY: {"a": cd.ELIGIBLE}}]
        axis = cd.tally(rows, {})
        self.assertEqual(axis["dict_lists_multi"], 0)
        self.assertEqual(axis["names_only_on_singletons"], [])
        self.assertEqual(len(axis["lists_unmeasured"]), 1)
        self.assertIsNone(axis["lists_unmeasured"][0]["n"])
        self.assertIn("нет длины", axis["lists_unmeasured"][0]["reason"])

    def test_an_invisible_name_eligible_once_is_still_understated(self):
        """Мутант `base = 0` → `1`: имя без строки переписи выпало бы из занижения."""
        axis = cd.tally([_list("named", 9, {"ticket": cd.ELIGIBLE})], {})
        self.assertEqual([r["field"] for r in axis["counted_understates"]],
                         ["ticket"])
        self.assertEqual(axis["counted_understates"][0]["counted"], None)
        self.assertEqual(axis["counted_understates"][0]["eligible_anywhere"], 1)
        self.assertEqual(
            axis["counted_understates"][0]["hidden_by_named_lists"], 1)

    def test_every_row_of_every_perimeter_list_carries_its_declared_keys(self):
        """Мутанты, подменяющие ИМЯ ключа: состав строк пришпилен ДОСЛОВНО.

        Сверка документа с самим собой переживает переименование; поэтому имена
        ключей перечислены литералами, а не взяты у прибора.
        """
        rows = [
            _list("unnamed_candidate_outside", 5,
                  {"detail": cd.ELIGIBLE, "note": "not_unique"}),
            _list("named", 9, {"detail": cd.ELIGIBLE}, module="m.b",
                  coord=".y"),
            _list("unnamed_no_candidate", 4, {"ghost": cd.ELIGIBLE},
                  module="m.c", coord=".z"),
            {"outcome": "named", "module": "m.d", "coord": ".w",
             "n": 3},
        ]
        rows.append({"outcome": "named", "module": "m.e", "coord": ".v",
                     cd.COMPOSITION_KEY: {"lost": cd.ELIGIBLE}})
        axis = cd.tally(rows, {"detail": 1})
        # Состав сверяется у КАЖДОГО элемента, а не у первого: у
        # `lists_unmeasured` ДВА места дописывания (нет состава / нет длины), и
        # пин только по `[0]` оставлял второе без проверки — ровно это и сказал
        # мутационный прогон.
        for row in axis["rows"]:
            self.assertEqual(
                set(row),
                {"field", "counted", "counted_unmeasured", "eligible_anywhere",
                 "present", "eligible_on_named_lists", "eligible_singletons",
                 "present_singletons", "refused_causes"})
        for row in axis["counted_understates"]:
            self.assertEqual(set(row), {"field", "counted", "gap",
                                        "eligible_anywhere",
                                        "hidden_by_named_lists"})
        for row in axis["gap_is_unfitness"]:
            self.assertEqual(set(row), {"field", "present",
                                        "eligible_anywhere",
                                        "refused_causes"})
        self.assertEqual(len(axis["lists_unmeasured"]), 2)
        for row in axis["lists_unmeasured"]:
            self.assertEqual(set(row),
                             {"module", "coord", "outcome", "n", "reason"})
        no_composition, no_length = axis["lists_unmeasured"]
        self.assertEqual((no_composition["module"], no_composition["coord"],
                          no_composition["outcome"], no_composition["n"]),
                         ("m.d", ".w", "named", 3))
        self.assertEqual((no_length["module"], no_length["coord"],
                          no_length["outcome"], no_length["n"]),
                         ("m.e", ".v", "named", None))
        for row in axis["probe_contradictions"]:
            self.assertEqual(set(row),
                             {"field", "module", "coord", "n", "reason"})
        self.assertEqual((axis["probe_contradictions"][0]["module"],
                          axis["probe_contradictions"][0]["coord"],
                          axis["probe_contradictions"][0]["n"]),
                         ("m.c", ".z", 4))
        # `hidden_by_named_lists` у имени, годного ТОЛЬКО в противоречии,
        # обязан быть НУЛЁМ: подмени умолчание `.get(name, 0)` — и ноль стал бы
        # единицей на наблюдении, которого нет.
        ghost = {r["field"]: r for r in axis["counted_understates"]}["ghost"]
        self.assertEqual(ghost["hidden_by_named_lists"], 0)
        self.assertEqual(ghost["gap"], 1)
        self.assertEqual(
            set(axis["adjudicated"][0]), {"field", "absent_today", "why"})
        self.assertNotIn("detail", {r["field"] for r in axis["adjudicated"]},
                         "`detail` не из рассуждённых — сцена верна")

    def test_the_adjudicated_row_of_a_present_name_carries_its_keys(self):
        axis = cd.tally(
            [_list("unnamed_candidate_outside", 9, {"message": cd.ELIGIBLE})],
            {"message": 1})
        row = {r["field"]: r for r in axis["adjudicated"]}["message"]
        self.assertEqual(set(row),
                         {"field", "absent_today", "counted",
                          "eligible_anywhere", "present",
                          "eligible_on_named_lists", "refused_causes",
                          "counted_understates"})

    def test_every_section_of_the_report_prints_its_content(self):
        """Мутанты `or []` → `and []` и подмены ключей чтения в отчёте.

        `axis.get(X) or []` при `and` отдаёт ПУСТО на НЕПУСТОМ входе, и раздел
        исчезает молча. Поэтому у каждого перечня есть строка, которую печатает
        ТОЛЬКО он, и сцена требует её дословно.
        """
        rows = [
            _list("unnamed_candidate_outside", 5,
                  {"detail": cd.ELIGIBLE, "note": "not_unique"}),
            _list("named", 9, {"detail": cd.ELIGIBLE, "ticket": cd.ELIGIBLE},
                  module="m.b", coord=".y"),
            _list("unnamed_no_candidate", 4, {"ghost": cd.ELIGIBLE},
                  module="m.c", coord=".z"),
            # две СТАРШИЕ беды, и каждая со своей причиной: состава нет …
            {"outcome": "named", "module": "m.d", "coord": ".w", "n": 3},
            # … и длины нет.
            {"outcome": "named", "module": "m.e", "coord": ".v",
             cd.COMPOSITION_KEY: {"lost": cd.ELIGIBLE}},
        ]
        axis = cd.tally(rows, {"detail": 1, "phantom": 4})
        text = "\n".join(cd.report(axis))
        # Строки пришпилены ЧИСЛАМИ, а не словами: мутант, подменивший ключ
        # чтения или склейку `or []`, оставляет слова на месте и меняет ровно
        # число — именно это и пережило первый мутационный проход.
        for needle in (
                "знаменатель разницы: словарных списков длиннее одного 3 из 5 "
                "словарных вообще; имён в замере 5; имён только в синглтонах "
                "(вне знаменателя обеими сторонами) 0",
                "ВЕРДИКТ DENOMINATOR_ARTIFACT: население занижено у 3 имён, из "
                "них не печатается переписью вовсе 2",
                "ПОЧЕМУ: у 3 имён ТОТ ЖЕ предикат",
                "сильнейшее: detail — перепись печатает 1, годно на 2",
                "ПОЧЕМУ: 2 имён перепись не печатает НИ ОДНОЙ строкой",
                "НЕ В ОТЧЁТЕ ПЕРЕПИСИ: ghost, ticket",
                "ВТОРАЯ РАЗНИЦА (ПРОТИВ имени): у 1 имён",
                "РАССУЖДЕНО value: НЕ ИЗМЕРЕНО",
                "у phantom перепись печатает 4, а состав даёт 0",
                "«ghost»",
                "(m.c .z)",
                "нет длины",
                "(m.e .v)",
        ):
            self.assertTrue(needle in text, f"раздел не напечатал: {needle!r}")

    def test_the_invisible_list_is_shortened_with_a_tail_and_whole_without(self):
        """Мутанты `max_rows is None` → `is not None` и `==` → `!=` у хвоста."""
        rows = [_list("named", 9,
                      {f"n{i}": cd.ELIGIBLE for i in range(5)})]
        axis = cd.tally(rows, {})
        whole = "\n".join(cd.report(axis))
        self.assertIn("НЕ В ОТЧЁТЕ ПЕРЕПИСИ: n0, n1, n2, n3, n4", whole)
        self.assertNotIn("… ещё", whole)
        short = "\n".join(cd.report(axis, max_rows=2))
        self.assertIn("НЕ В ОТЧЁТЕ ПЕРЕПИСИ: n0, n1; … ещё 3", short)


class TheAdjudicatedNames(unittest.TestCase):
    """Перечень — ЗАПИСЬ О РЕШЕНИИ, и имя, истлевшее за три дня, не ноль."""

    def test_every_pinned_name_gets_a_row_in_the_declared_order(self):
        axis = cd.tally([], {})
        self.assertEqual([r["field"] for r in axis["adjudicated"]],
                         list(cd.ADJUDICATED_NAMES))

    def test_a_name_absent_today_is_a_third_outcome_not_zeros(self):
        axis = cd.tally([], {})
        row = axis["adjudicated"][0]
        self.assertTrue(row["absent_today"])
        self.assertNotIn("counted", row)
        self.assertIn("это не нули", row["why"])
        # Отчёт везёт ПРИЧИНУ, а не только метку: ключ её чтения пинится
        # строкой целиком.
        self.assertIn(f"РАССУЖДЕНО value: НЕ ИЗМЕРЕНО — {row['why']}",
                      "\n".join(cd.report(axis)))

    def test_an_adjudicated_name_without_a_census_row_prints_NO_ROW(self):
        """`best_net_usd` живьём: населения нет, годность есть.

        Пинится и строка («СТРОКИ НЕТ» вместо `None`), и вердикт: мутант
        `base = 0` → `1` в этой ветке опрокинул бы именно его.
        """
        axis = cd.tally([_list("named", 12, {"best_net_usd": cd.ELIGIBLE})], {})
        row = {r["field"]: r for r in axis["adjudicated"]}["best_net_usd"]
        self.assertIsNone(row["counted"])
        self.assertEqual(row["eligible_anywhere"], 1)
        self.assertTrue(row["counted_understates"])
        self.assertIn(
            "РАССУЖДЕНО best_net_usd: перепись печатает СТРОКИ НЕТ · годно 1 "
            "(из них у названных списков 1) · ЕСТЬ 1 ⇒ мерило судило по "
            "УЗКОМУ числу", "\n".join(cd.report(axis)))

    def test_an_adjudicated_name_eligible_nowhere_does_not_understate(self):
        """Мутант `eligible > base` с умолчанием `1`: ноль годности ПРЕДЪЯВЛЕН."""
        axis = cd.tally(
            [_list("named", 5, {"message": "not_unique"}),
             _list("named", 7, {"message": "not_scalar"}, module="m.b")], {})
        row = {r["field"]: r for r in axis["adjudicated"]}["message"]
        self.assertEqual(row["eligible_anywhere"], 0)
        self.assertEqual(row["present"], 2)
        self.assertEqual(row["refused_causes"],
                         {"not_scalar": 1, "not_unique": 1})
        self.assertFalse(row["counted_understates"])
        self.assertIn("РАССУЖДЕНО message: перепись печатает СТРОКИ НЕТ · "
                      "годно 0 (из них у названных списков 0) · ЕСТЬ 2 ⇒ "
                      "низкое население НЕ артефакт знаменателя",
                      "\n".join(cd.report(axis)))

    def test_the_strongest_understated_name_is_the_one_with_the_biggest_gap(self):
        """`gap` — ОДНА копия правила «насколько занижено».

        Сцена различает именно её: у имени БЕЗ строки переписи разрыв больше, и
        прежняя вторая копия (`counted or 0`) считала его тем же числом только
        по совпадению.
        """
        axis = cd.tally(
            [_list("unnamed_candidate_outside", 9, {"small": cd.ELIGIBLE}),
             _list("named", 8, {"small": cd.ELIGIBLE, "big": cd.ELIGIBLE},
                   module="m.b"),
             _list("named", 7, {"small": cd.ELIGIBLE, "big": cd.ELIGIBLE},
                   module="m.c"),
             _list("named", 6, {"big": cd.ELIGIBLE}, module="m.d")],
            {"small": 1})
        gaps = {r["field"]: r["gap"] for r in axis["counted_understates"]}
        self.assertEqual(gaps, {"small": 2, "big": 3})
        self.assertIn("сильнейшее: big — перепись печатает None, годно на 3",
                      " ".join(axis["verdict_reasons"]))

    def test_the_ruler_of_ADR_503_is_restated_only_when_the_wide_number_differs(self):
        narrow = cd.tally(
            [_list("unnamed_candidate_outside", 93, {"value": cd.ELIGIBLE})],
            {"value": 1})
        row = {r["field"]: r for r in narrow["adjudicated"]}["value"]
        self.assertFalse(row["counted_understates"])
        self.assertIn("НЕ артефакт знаменателя", "\n".join(cd.report(narrow)))

        wide = cd.tally(
            [_list("unnamed_candidate_outside", 93, {"value": cd.ELIGIBLE}),
             _list("named", 40, {"value": cd.ELIGIBLE}, module="m.b")],
            {"value": 1})
        row = {r["field"]: r for r in wide["adjudicated"]}["value"]
        self.assertTrue(row["counted_understates"])
        text = "\n".join(cd.report(wide))
        # Строка рассуждённого имени пришпилена ЦЕЛИКОМ: все четыре её числа
        # читаются из своих ключей, и мутант, подменивший любой из них, меняет
        # ровно её — словами это не видно.
        self.assertTrue(
            "РАССУЖДЕНО value: перепись печатает 1 · годно 2 (из них у "
            "названных списков 1) · ЕСТЬ 2 ⇒ мерило судило по УЗКОМУ числу"
            in text, text[:400])
        self.assertIn("мерило ADR-503", text)

    def test_the_restated_names_are_joined_by_a_separator(self):
        """Два рассуждённых имени разом: склейка перечня предъявлена.

        На ОДНОМ имени разделитель не исполняется вовсе, и мутант, подменивший
        его, выживал — сцена из одного имени об этом молчит по построению.
        """
        axis = cd.tally(
            [_list("unnamed_candidate_outside", 9, {"message": cd.ELIGIBLE,
                                                    "window_s": cd.ELIGIBLE}),
             _list("named", 7, {"message": cd.ELIGIBLE,
                                "window_s": cd.ELIGIBLE}, module="m.b")],
            {"message": 1, "window_s": 1})
        self.assertIn("среди РАССУЖДЕННЫХ имён таких 2: message, window_s",
                      " ".join(axis["verdict_reasons"]))

    def test_a_name_with_none_of_the_side_counts_shows_zeros_not_ones(self):
        """Мутанты `0` → `1` у умолчаний `.get(name, 0)`: нули ПРЕДЪЯВЛЕНЫ.

        Имя, которое годно только у безымянного списка длиннее одного, обязано
        дать ноль по ТРЁМ соседним счётчикам сразу; подмени умолчание — и
        каждый из них стал бы единицей на пустом наблюдении.
        """
        axis = cd.tally(
            [_list("unnamed_candidate_outside", 9, {"solo": cd.ELIGIBLE})],
            {"solo": 1})
        row = axis["rows"][0]
        self.assertEqual(row["eligible_on_named_lists"], 0)
        self.assertEqual(row["eligible_singletons"], 0)
        self.assertEqual(row["present_singletons"], 0)
        self.assertEqual(row["refused_causes"], {})
        self.assertEqual(axis["counted_understates"], [])
        self.assertEqual(axis["gap_is_unfitness"], [])
        adj = cd.tally(
            [_list("unnamed_candidate_outside", 9, {"message": cd.ELIGIBLE})],
            {"message": 1})
        row = {r["field"]: r for r in adj["adjudicated"]}["message"]
        self.assertEqual(row["eligible_on_named_lists"], 0)
        self.assertFalse(row["counted_understates"])


class ThereIsNoGate(unittest.TestCase):
    """Разница — наблюдение. Запрет пинится СОСТАВОМ имён, а не прозой."""

    def test_the_forbidden_names_are_pinned_at_the_consumer(self):
        for name in ("denominator_gate", "admit_by_denominator",
                     "reject_by_denominator", "fit_by_denominator",
                     "admit_by_presence", "reject_by_presence"):
            self.assertIn(name, census._NO_GATE_NAMES, name)

    def test_the_module_defines_none_of_them(self):
        public = {n for n in dir(cd) if not n.startswith("_")}
        self.assertEqual(public & set(census._NO_GATE_NAMES), set())

    def test_what_it_does_not_prove_says_all_four_things(self):
        """Все ЧЕТЫРЕ оговорки пришпилены: пин двух оставлял две без проверки."""
        axis = cd.tally([_list("named", 3, {"a": cd.ELIGIBLE})], {})
        said = axis["what_it_does_not_prove"]
        self.assertEqual(len(said), 4)
        joined = " ".join(said)
        for needle in ("присутствие не есть годность", "ПРОТИВ имени",
                       "НИЖНИЕ границы",
                       "ни одно имя не дописано в _IDENTITY_FIELDS"):
            self.assertTrue(needle in joined, f"оговорка пропала: {needle!r}")


class TheConstantsAgreeWithTheirSources(unittest.TestCase):
    """Пины сверяются С КОДОМ, а не сами с собой."""

    def test_dict_outcomes_is_the_censuss_own_set_widened_by_NAMED(self):
        self.assertEqual(set(cd.DICT_OUTCOMES),
                         set(census._DICT_OUTCOMES) | {cd.NAMED_OUTCOME})
        # И разница — РОВНО `named`: предмет заказа именно в ней.
        self.assertEqual(set(cd.DICT_OUTCOMES) - set(census._DICT_OUTCOMES),
                         {"named"})

    def test_NAMED_OUTCOME_is_the_string_the_probe_actually_produces(self):
        row = probe.classify_list([{"protocol": "a", "x": 1},
                                   {"protocol": "b", "x": 1}])
        self.assertEqual(row["outcome"], cd.NAMED_OUTCOME)

    def test_ELIGIBLE_is_the_causeless_verdict_of_the_one_rule(self):
        self.assertEqual(scalar_refusal(["a", "b"]), cd.ELIGIBLE)
        self.assertNotEqual(scalar_refusal(["a", "a"]), cd.ELIGIBLE)

    def test_COMPOSITION_KEY_is_the_key_the_probe_writes(self):
        row = probe.classify_list([{"a": 1, "b": 2}, {"a": 1, "b": 3}])
        self.assertIn(cd.COMPOSITION_KEY, row)


class TheProbeNowAnswersAboutNamedListsToo(unittest.TestCase):
    """Ровно то звено, которого не было: состав у списка С личностью."""

    def test_a_named_list_carries_the_composition(self):
        row = probe.classify_list([{"protocol": "a", "ticket": 1},
                                   {"protocol": "b", "ticket": 2}])
        self.assertEqual(row["outcome"], "named")
        self.assertEqual(row[cd.COMPOSITION_KEY], {"ticket": cd.ELIGIBLE})

    def test_a_list_with_no_identity_carries_it_as_before(self):
        row = probe.classify_list([{"a": 1, "b": 2}, {"a": 1, "b": 3}])
        self.assertEqual(row[cd.COMPOSITION_KEY],
                         {"a": "not_unique", "b": cd.ELIGIBLE})
        self.assertEqual(row["candidates"], ["b"])

    def test_candidates_outside_is_exactly_the_eligible_half(self):
        items = [{"a": 1, "b": 2, "c": [1]}, {"a": 1, "b": 3, "c": [2]}]
        composition = probe.outside_fields(items)
        self.assertEqual(
            probe.candidates_outside(items),
            [name for name, cause in composition.items() if cause == cd.ELIGIBLE])
        # И контроль, что причина не пустая у негодных: иначе равенство выше
        # держалось бы на том, что негодных нет вовсе.
        self.assertEqual(composition["a"], "not_unique")
        self.assertEqual(composition["c"], "not_scalar")

    def test_identity_fields_never_appear_in_the_composition(self):
        items = [{"protocol": "a", "q": 1}, {"protocol": "b", "q": 2}]
        self.assertNotIn("protocol", probe.outside_fields(items))
        self.assertIn("q", probe.outside_fields(items))

    def test_the_union_of_keys_is_taken_not_the_keys_of_the_first_element(self):
        items = [{"a": 1}, {"a": 2, "late": 9}]
        self.assertEqual(probe.outside_fields(items),
                         {"a": cd.ELIGIBLE, "late": "field_absent"})

    def test_the_composition_is_sorted(self):
        items = [{"z": 1, "a": 2}, {"z": 3, "a": 4}]
        self.assertEqual(list(probe.outside_fields(items)), ["a", "z"])


class WiredIntoTheCensus(unittest.TestCase):
    """Проводка: раздел есть у свода, у отчёта и у читателя-офиса."""

    def _rows(self) -> dict:
        return {"m.a": {"entry": "run", "truncated": False, "lists": [
            dict(_list("unnamed_candidate_outside", 5,
                       {"detail": cd.ELIGIBLE}), candidates=["detail"],
                 coord=".x"),
            dict(_list("named", 9, {"detail": cd.ELIGIBLE}), field="protocol",
                 coord=".y"),
        ]}}

    def test_the_tally_carries_the_section(self):
        counts = census.tally(self._rows())
        axis = counts["candidate_denominator"]
        self.assertEqual(axis["status"], "MEASURED")
        self.assertEqual([r["field"] for r in axis["counted_understates"]],
                         ["detail"])

    def test_the_population_is_the_censuss_own_number(self):
        counts = census.tally(self._rows())
        row = counts["candidate_denominator"]["rows"][0]
        self.assertEqual(row["counted"],
                         counts["candidate_fields_outside"]["detail"])
        self.assertEqual(counts["candidate_denominator"]["counted_disagrees"],
                         [])

    def test_the_report_prints_the_section(self):
        doc = {"status": "FINDING", "counts": census.tally(self._rows()),
               "invoked_by": {}, "advisory": "—"}
        text = "\n".join(census.report(doc))
        self.assertIn("[ЗНАМЕНАТЕЛЬ ИМЕНИ]", text)
        self.assertIn("ВЕРДИКТ DENOMINATOR_ARTIFACT", text)

    def test_an_old_style_doc_says_NOT_MEASURED_rather_than_no_difference(self):
        counts = census.tally(self._rows())
        counts.pop("candidate_denominator")
        doc = {"status": "FINDING", "counts": counts, "invoked_by": {},
               "advisory": "—"}
        text = "\n".join(census.report(doc))
        self.assertIn("отчёт СТАРОГО ОБРАЗЦА", text)
        # Отрицание прицеливается в вердикт ЭТОГО раздела, а не в слово
        # «ВЕРДИКТ»: его печатают и соседние оси, и утверждение про весь текст
        # было бы утверждением об ИХ разделах (урок #834).
        self.assertNotIn("ВЕРДИКТ DENOMINATOR_ARTIFACT", text)
        self.assertNotIn("ВЕРДИКТ NOT_AN_ARTIFACT", text)

    def test_the_section_is_printed_even_without_candidates(self):
        """Третий исход раздела не имеет права исчезнуть на чистом документе."""
        counts = census.tally({"m.a": {"entry": "run", "truncated": False,
                                       "lists": []}})
        doc = {"status": "CLEAN", "counts": counts, "invoked_by": {},
               "advisory": "—"}
        self.assertIn("[ЗНАМЕНАТЕЛЬ ИМЕНИ]", "\n".join(census.report(doc)))

    def test_the_office_declares_the_key_as_read(self):
        declared = _office()._READ_SCHEMA[census.ARTIFACT]
        self.assertIn("counts.candidate_denominator", declared)


if __name__ == "__main__":                                    # pragma: no cover
    unittest.main()
