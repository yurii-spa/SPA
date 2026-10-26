"""Совпадает ли ОБЪЯВЛЕННОЕ со-производство с ДЕЙСТВИТЕЛЬНЫМ (ADR-817).

Заказ **G816 п. 2** стоячего приказа владельца «Portfolio CIO», дословно:
«новая дверь спрашивает конституцию и об этом не отвечает по построению;
артефакт, объявленный за двумя, а пишущийся одним, сегодня получает воздержание
ЗАСЛУЖЕННО по форме и НЕЗАСЛУЖЕННО по сути. Мерить наблюдённым списком
производителей, НЕ сводя оси.»

ADR-816 дал объявленной оси ПРАВОМОЧИЕ отрицать: артефакт за несколькими
производителями снимается с суда, потому что «такт ОДНОГО из них не есть такт
артефакта». Это ДОВОД, и у довода есть предпосылка — что со-производители
действительно идут. Предпосылку правомочие не проверяет ПО ПОСТРОЕНИЮ: оно
спрашивает конституцию, а конституция о действительности не знает.

Соврать здесь можно ровно пятью способами, и каждый ниже — отдельный тест:

1. выдать молчащего производителя за работающего (воздержание держится на
   мнимом со-производстве, поагентная находка погашена зря);
2. выдать НЕНАБЛЮДЁННОГО производителя за молчащего — ноль вместо ``None``,
   то есть превратить отсутствие наблюдения в доказательство (инв. #17);
3. требовать правомочия у положительного ответа: дождаться всех при двух уже
   наблюдённых и объявить «не измерено» там, где ответ получен;
4. СВЕСТИ оси — пустить наблюдение внутрь правомочия и вернуть поагентную
   находку, что заказ G815 п. 2 запрещает дословно;
5. сложить ПАРЫ с АРТЕФАКТАМИ: воздержаний четыре, предпосылок две, и одно
   число на два предмета отвечает на третий, никем не заданный вопрос;
6. подтвердить со-производство при НЕ ПОСЧИТАННЫХ производителях — выдать
   неизмеренное за измеренное (способ найден СОБСТВЕННОЙ батареей мутаций,
   мутация 10: прежняя сцена шестого контроля давала один ответ обеими ветками
   и потому не различала ничего).

Числа сцен — ИЗМЕРЕННЫЕ на живом флоте 26.10 и названные в ADR-817, а не
выдуманные: ``data/deployment_acceptance.json`` и ``data/deployment_drift.json``
(срок 15 ч) объявлены за ``system_health_morning`` (``calendar:08:00``) и
``system_health_evening`` (``calendar:20:00``); в окне наблюдения 792 ч прогонов
у первого **12**, у второго **11**.

Литеральных дат и стенных часов в файле НЕТ по построению у чистых функций
(предмет — «счёт прогонов → вердикт предпосылки»); единственный сквозной тест
берёт стенд и впрыснутые часы у ``test_slo_keepability``, своей копии сцены
здесь нет — две копии одного стенда и были бы тем, против чего ADR-220.
"""
from __future__ import annotations

import unittest

from spa_core.monitoring import slo_keepability as sk
from spa_core.monitoring import slo_proposal as sp
from spa_core.tests.test_slo_keepability import _StandCase

#: ИЗМЕРЕННАЯ сцена живой конституции (26.10).
_MORNING = "com.spa.system_health_morning"
_EVENING = "com.spa.system_health_evening"
_MORNING_RUNS = 12          # прогонов в окне 792 ч
_EVENING_RUNS = 11
_DEPLOY_SLO = 15.0          # срок `deployment_acceptance.json` / `deployment_drift.json`
_DEPLOY_MEDIAN = 12.0       # наблюдённый такт АРТЕФАКТА (агенты в 12 ч друг от друга)
_DAILY_MORNING = "calendar:08:00"
_DAILY_EVENING = "calendar:20:00"


class TheActualCoProductionIsAskedOfObservation(unittest.TestCase):
    """Четыре исхода двери, и каждый — свой способ соврать."""

    def test_two_observed_producers_confirm_the_premise(self):
        """Измеренный случай 26.10: оба идут ⇒ воздержание заслуженно и по сути."""
        kind, why = sk.co_production_actual(
            {_MORNING: _MORNING_RUNS, _EVENING: _EVENING_RUNS})
        self.assertEqual(kind, sk.CO_PRODUCTION_CONFIRMED, why)
        self.assertIn(_MORNING, why, "производители обязаны быть НАЗВАНЫ в доводе")
        self.assertIn(_EVENING, why)

    def test_one_running_producer_makes_the_abstention_undeserved(self):
        """Способ соврать №1 — ровно предмет заказа G816 п. 2."""
        kind, why = sk.co_production_actual({_MORNING: _MORNING_RUNS, _EVENING: 0})
        self.assertEqual(kind, sk.CO_PRODUCTION_NOMINAL, why)
        self.assertIn(_EVENING, why, "молчащий производитель обязан быть НАЗВАН")

    def test_a_nominal_co_production_is_a_finding_of_the_section(self):
        """Носитель отдельным тестом: вердикт мало назвать, он обязан быть НАХОДКОЙ."""
        out = sk.co_production_census(
            _abstention_section(), _co_produced_agents(),
            {_MORNING: _MORNING_RUNS, _EVENING: 0})
        self.assertEqual(len(out["findings"]), 1, out)
        self.assertEqual(out["findings"][0]["co_production"], sk.CO_PRODUCTION_NOMINAL)

    def test_no_producer_running_is_its_own_state_not_a_nominal_one(self):
        """«Идёт один» и «не идёт никто» лечатся разным, и путать их нельзя."""
        kind, why = sk.co_production_actual({_MORNING: 0, _EVENING: 0})
        self.assertEqual(kind, sk.CO_PRODUCTION_NONE_RUNNING, why)
        self.assertIn("не говорит ничего", why,
                      "про СРОК отсутствие такта не говорит ничего — это обязано быть сказано")

    def test_an_unobserved_producer_is_the_third_outcome_not_a_silent_one(self):
        """Способ соврать №2: ноль вместо `None` (инв. #17)."""
        kind, why = sk.co_production_actual({_MORNING: _MORNING_RUNS, _EVENING: None})
        self.assertEqual(kind, sk.CO_PRODUCTION_UNMEASURED, why)

    def test_zero_and_None_give_OPPOSITE_verdicts_on_the_same_scene(self):
        """Носитель различия: подстановка нуля вернула бы находку из воздуха."""
        silent, _ = sk.co_production_actual({_MORNING: _MORNING_RUNS, _EVENING: 0})
        unseen, _ = sk.co_production_actual({_MORNING: _MORNING_RUNS, _EVENING: None})
        self.assertEqual(silent, sk.CO_PRODUCTION_NOMINAL)
        self.assertEqual(unseen, sk.CO_PRODUCTION_UNMEASURED)
        self.assertNotEqual(silent, unseen,
                            "«лог не прочитан» и «прогонов нет» слиты в один ответ")

    def test_an_empty_producer_set_is_unmeasured_with_a_named_cause(self):
        kind, why = sk.co_production_actual({})
        self.assertEqual(kind, sk.CO_PRODUCTION_UNMEASURED, why)
        self.assertTrue(why.strip())

    def test_a_non_dict_input_is_unmeasured_not_a_crash(self):
        kind, why = sk.co_production_actual(None)
        self.assertEqual(kind, sk.CO_PRODUCTION_UNMEASURED, why)

    def test_a_boolean_run_count_is_not_a_number_of_runs(self):
        """`True` — не «один прогон»: подстановка сделала бы из флага свидетеля."""
        kind, _ = sk.co_production_actual({_MORNING: True, _EVENING: True})
        self.assertEqual(kind, sk.CO_PRODUCTION_UNMEASURED)


class ThePremiseIsAsymmetricAndThatIsProvable(unittest.TestCase):
    """Та же асимметрия, что у правомочия ADR-816, и по той же причине."""

    def test_two_witnesses_are_enough_even_with_an_unobserved_third(self):
        """Способ соврать №3: ждать всех там, где ответ уже получен."""
        kind, why = sk.co_production_actual(
            {_MORNING: _MORNING_RUNS, _EVENING: _EVENING_RUNS, "com.spa.third": None})
        self.assertEqual(kind, sk.CO_PRODUCTION_CONFIRMED, why)

    def test_one_witness_with_an_unobserved_second_is_NOT_enough(self):
        """Обратная сторона несимметрична: «идёт один» требует всех остальных."""
        kind, why = sk.co_production_actual({_MORNING: _MORNING_RUNS, _EVENING: None})
        self.assertNotEqual(kind, sk.CO_PRODUCTION_NOMINAL, why)
        self.assertEqual(kind, sk.CO_PRODUCTION_UNMEASURED, why)

    def test_a_silent_third_does_not_undo_two_witnesses(self):
        kind, why = sk.co_production_actual(
            {_MORNING: _MORNING_RUNS, _EVENING: _EVENING_RUNS, "com.spa.third": 0})
        self.assertEqual(kind, sk.CO_PRODUCTION_CONFIRMED, why)


class TheProducerCountHasExactlyOneDefinition(unittest.TestCase):
    """Копия счёта рядом с дверью — форма, на которой выжила мутация №2 ADR-814."""

    def test_two_agents_on_one_artifact_are_two_producers(self):
        labels = sk.declared_producer_labels(_co_produced_agents(), "data/shared.json")
        self.assertEqual(labels, sorted([_MORNING, _EVENING]))

    def test_one_agent_declaring_the_artifact_TWICE_is_still_ONE_producer(self):
        """Латентный дефект того же класса: воздержание, выписанное себе в одиночку.

        Замер 26.10 на живой конституции — таких артефактов **0** из 231
        (измерено и равно нулю), поэтому ни один живой вердикт правкой не двинут;
        дефект закрыт ДО появления населения, а не после.
        """
        agents = [{"label": _MORNING, "schedule": _DAILY_MORNING, "produces": [
            {"artifact": "data/twice.json", "slo_hours": _DEPLOY_SLO},
            {"artifact": "data/twice.json", "slo_hours": _DEPLOY_SLO}]}]
        self.assertEqual(sk.declared_producer_labels(agents, "data/twice.json"),
                         [_MORNING])

    def test_a_doubly_declared_artifact_keeps_its_finding(self):
        """Носитель вреда отдельным тестом: опечатка не вправе гасить находку."""
        agents = [{"label": _MORNING, "schedule": _DAILY_MORNING, "produces": [
            {"artifact": "data/twice.json", "slo_hours": _DEPLOY_SLO},
            {"artifact": "data/twice.json", "slo_hours": _DEPLOY_SLO}]}]
        out = sk.declared_axis_census(agents, {"data/twice.json": _DEPLOY_MEDIAN})
        kinds = {r["declared_vs_floor"] for r in out["findings"] + out["abstained"]}
        self.assertNotIn(sp.DECLARED_CO_PRODUCED, kinds,
                         "агент выписал себе воздержание в одиночку — находка погашена опечаткой")

    def test_a_nameless_agent_is_not_a_producer(self):
        agents = [{"label": "", "produces": [{"artifact": "data/x.json", "slo_hours": 1}]},
                  {"label": _MORNING, "produces": [{"artifact": "data/x.json", "slo_hours": 1}]}]
        self.assertEqual(sk.declared_producer_labels(agents, "data/x.json"), [_MORNING])

    def test_the_declared_axis_counts_THROUGH_the_door_not_beside_it(self):
        """Контроль ДВЕРИ движением: убери второго агента — воздержание обязано уйти."""
        alone = [a for a in _co_produced_agents() if a["label"] == _MORNING]
        out = sk.declared_axis_census(alone, {"data/shared.json": _DEPLOY_MEDIAN})
        kinds = {r["declared_vs_floor"] for r in out["findings"] + out["abstained"]}
        self.assertNotIn(sp.DECLARED_CO_PRODUCED, kinds)


class TheTwoAxesAreNotMerged(unittest.TestCase):
    """Способ соврать №4 — то, что заказ G815 п. 2 запрещает дословно."""

    def test_the_standing_still_knows_nothing_about_observation(self):
        """Правомочие спрашивает ЧИСЛО объявленных и ответа соседа не видит."""
        self.assertIs(sp.declared_axis_standing(2)[0], False)
        self.assertIs(sp.declared_axis_standing(1)[0], True)

    def test_a_nominal_premise_does_NOT_resurrect_the_per_agent_finding(self):
        """Воздержание остаётся воздержанием: находку возвращает РЕШЕНИЕ, не замер."""
        section = _abstention_section()
        out = sk.co_production_census(section, _co_produced_agents(),
                                     {_MORNING: _MORNING_RUNS, _EVENING: 0})
        self.assertEqual(len(out["findings"]), 1, "предпосылка названа мнимой")
        for row in section["abstained"]:
            self.assertEqual(row["declared_vs_floor"], sp.DECLARED_CO_PRODUCED,
                             "наблюдение переписало вердикт объявленной оси — оси сведены")


class TheCensusNamesItsPopulation(unittest.TestCase):
    """Способ соврать №5: сложить ПАРЫ с АРТЕФАКТАМИ."""

    def test_pairs_and_artifacts_are_reported_as_TWO_numbers(self):
        out = sk.co_production_census(
            _abstention_section(), _co_produced_agents(),
            {_MORNING: _MORNING_RUNS, _EVENING: _EVENING_RUNS})
        self.assertEqual(out["population"], 1, "предпосылка ОДНА на файл")
        self.assertEqual(out["abstained_pairs"], 2, "воздержания выписаны ПАРАМ")
        self.assertNotEqual(out["population"], out["abstained_pairs"])

    def test_rows_name_each_producer_and_its_run_count(self):
        """«Находок нет» без имён неотличимо от «население пусто»."""
        out = sk.co_production_census(
            _abstention_section(), _co_produced_agents(),
            {_MORNING: _MORNING_RUNS, _EVENING: _EVENING_RUNS})
        row = out["rows"][0]
        self.assertEqual(row["declared_producers"], sorted([_MORNING, _EVENING]))
        self.assertEqual(row["observed_runs"][_MORNING], _MORNING_RUNS)
        self.assertEqual(row["observed_runs"][_EVENING], _EVENING_RUNS)

    def test_an_abstention_whose_STANDING_was_unmeasured_stays_in_the_report(self):
        """Иначе строка просто исчезнет и станет неотличима от «её не было»."""
        section = {"abstained": [{"artifact": "data/shared.json", "agent": _MORNING,
                                  "declared_vs_floor": sp.DECLARED_STANDING_UNMEASURED}]}
        out = sk.co_production_census(section, _co_produced_agents(), {})
        self.assertEqual(out["population"], 1)
        self.assertEqual(out["rows"][0]["co_production"], sk.CO_PRODUCTION_UNMEASURED)
        self.assertEqual(out["findings"], [])

    def test_an_unmeasured_STANDING_is_not_confirmed_by_running_producers(self):
        """ДЫРА ПОКРЫТИЯ, найденная собственной батареей (мутация 10, ADR-817).

        Прежняя сцена этого теста давала ``unmeasured`` ОБЕИМИ ветками — у неё
        не было прогонов вовсе, — и снятие заслона вердикта не меняло: тест
        держал верное притязание и НИЧЕГО не различал. Сцена, которая различает,
        обязана дать ветками ПРОТИВОПОЛОЖНЫЕ ответы: правомочие НЕ ИЗМЕРЕНО, а
        прогоны у обоих производителей идут. Без заслона это читается
        ``confirmed`` — то есть со-производство подтверждается при НЕ
        ПОСЧИТАННЫХ производителях, и неизмеренное выдаётся за измеренное.
        """
        section = {"abstained": [{"artifact": "data/shared.json", "agent": _MORNING,
                                  "declared_vs_floor": sp.DECLARED_STANDING_UNMEASURED}]}
        out = sk.co_production_census(
            section, _co_produced_agents(),
            {_MORNING: _MORNING_RUNS, _EVENING: _EVENING_RUNS})
        row = out["rows"][0]
        self.assertEqual(row["co_production"], sk.CO_PRODUCTION_UNMEASURED,
                         "прогоны подтвердили со-производство, которого НЕ ПОСЧИТАЛИ")
        self.assertNotEqual(row["co_production"], sk.CO_PRODUCTION_CONFIRMED)

    def test_an_unmeasured_STANDING_names_the_STANDING_and_not_the_runs(self):
        """Носитель причины отдельным тестом: вердикт мало вернуть, его надо ОБЪЯСНИТЬ.

        «Производителей не посчитали» и «прогонов не наблюдали» чинятся разным, и
        одна причина на два состояния вернула бы ADR-813 на этаж выше.
        """
        section = {"abstained": [{"artifact": "data/shared.json", "agent": _MORNING,
                                  "declared_vs_floor": sp.DECLARED_STANDING_UNMEASURED}]}
        out = sk.co_production_census(
            section, _co_produced_agents(),
            {_MORNING: _MORNING_RUNS, _EVENING: _EVENING_RUNS})
        self.assertIn("правомочие", out["rows"][0]["note"])
        self.assertEqual(out["rows"][0]["observed_runs"], {},
                         "прогоны не спрашивались — предпосылка вопроса не обеспечена")

    def test_a_missing_abstention_list_is_unmeasured_not_an_empty_census(self):
        out = sk.co_production_census({}, _co_produced_agents(), {})
        self.assertEqual(out["status"], sk.CO_PRODUCTION_UNMEASURED)
        self.assertIsNone(out["population"])
        self.assertTrue(out["cause"].strip())

    def test_an_artifact_above_the_floor_is_NOT_in_this_population(self):
        """Вред — только ПОГАШЕННАЯ находка, и меряется ровно то население."""
        out = sk.co_production_census({"abstained": []}, _co_produced_agents(),
                                      {_MORNING: _MORNING_RUNS, _EVENING: 0})
        self.assertEqual(out["population"], 0)
        self.assertEqual(out["findings"], [])


class TheOfficeLineIsTheOnlyFormAndHasAThirdOutcome(unittest.TestCase):
    """Строка шага 0-офис проверяема отдельно — в мосте её проверить нечем."""

    def test_a_missing_section_says_so_instead_of_printing_zero(self):
        line = sk.co_production_line({})
        self.assertIn("НЕ ИЗМЕРЕНО", line)
        self.assertIn("declared_co_production", line)

    def test_a_section_that_failed_to_measure_names_its_cause(self):
        line = sk.co_production_line({"declared_co_production": {
            "status": sk.CO_PRODUCTION_UNMEASURED, "cause": "перечня воздержаний нет"}})
        self.assertIn("НЕ ИЗМЕРЕНО", line)
        self.assertIn("перечня воздержаний нет", line)

    def test_a_present_section_reports_artifacts_and_pairs_separately(self):
        line = sk.co_production_line({"declared_co_production": {
            "status": "OK", "population": 2, "abstained_pairs": 4,
            "tally": {sk.CO_PRODUCTION_CONFIRMED: 2}, "findings": []}})
        self.assertIn("артефактов 2", line)
        self.assertIn("4 воздержавшихся пар", line)
        self.assertIn("действительно 2", line)
        self.assertIn("МНИМО 0", line)

    def test_missing_sub_keys_are_not_printed_as_zero(self):
        """«Находок нет» и «находки не посчитаны» обязаны быть различимы."""
        line = sk.co_production_line({"declared_co_production": {
            "status": "OK", "population": 1}})
        self.assertIn("НЕ ИЗМЕРЕНО", line)
        self.assertNotIn("МНИМО 0", line)


class TheSectionReachesTheMeasurementEndToEnd(_StandCase):
    """Сквозной контроль на НАСТОЯЩЕМ приборе: сцена, логи, впрыснутые часы.

    Стенд и часы берутся у ``test_slo_keepability`` — своей копии сцены здесь нет.
    """

    def test_two_running_co_producers_confirm_the_premise_through_measure(self):
        self.stand.agent(_MORNING, [("data/shared.json", _DEPLOY_SLO)],
                         schedule=_DAILY_MORNING, name="morning")
        self.stand.agent(_EVENING, [("data/shared.json", _DEPLOY_SLO)],
                         schedule=_DAILY_EVENING, name="evening")
        self.stand.runs("morning", [0, 24, 48, 72])
        self.stand.runs("evening", [12, 36, 60, 84])
        doc = self.stand.measure()
        section = doc["declared_co_production"]
        self.assertEqual(section["status"], "OK")
        self.assertEqual(section["population"], 1)
        self.assertEqual(section["abstained_pairs"], 2)
        self.assertEqual(section["findings"], [])
        self.assertEqual(section["rows"][0]["co_production"],
                         sk.CO_PRODUCTION_CONFIRMED)

    def test_a_co_producer_that_never_runs_is_a_finding_through_measure(self):
        """Предмет заказа на настоящем приборе: воздержание на мнимой предпосылке."""
        self.stand.agent(_MORNING, [("data/shared.json", _DEPLOY_SLO)],
                         schedule=_DAILY_MORNING, name="morning")
        self.stand.agent(_EVENING, [("data/shared.json", _DEPLOY_SLO)],
                         schedule=_DAILY_EVENING, name="evening")
        self.stand.runs("morning", [0, 24, 48, 72])
        # Лог второго агента СУЩЕСТВУЕТ и канонической формы, но своих прогонов
        # в нём нет: это НАБЛЮДЕНИЕ нуля, а не отсутствие наблюдения.
        self.stand.runs("evening", [6, 30], name="somebody_else")
        doc = self.stand.measure()
        section = doc["declared_co_production"]
        self.assertEqual(len(section["findings"]), 1, section)
        self.assertEqual(section["findings"][0]["co_production"],
                         sk.CO_PRODUCTION_NOMINAL)
        self.assertEqual(section["findings"][0]["observed_runs"][_EVENING], 0)

    def test_a_co_producer_without_a_log_is_unmeasured_through_measure(self):
        """Лога НЕТ ⇒ `None`, и находкой это не выдаётся (инв. #17)."""
        self.stand.agent(_MORNING, [("data/shared.json", _DEPLOY_SLO)],
                         schedule=_DAILY_MORNING, name="morning")
        self.stand.agent(_EVENING, [("data/shared.json", _DEPLOY_SLO)],
                         schedule=_DAILY_EVENING, name="evening")
        self.stand.runs("morning", [0, 24, 48, 72])
        doc = self.stand.measure()
        section = doc["declared_co_production"]
        self.assertEqual(section["findings"], [])
        self.assertEqual(section["rows"][0]["co_production"],
                         sk.CO_PRODUCTION_UNMEASURED)
        self.assertIsNone(section["rows"][0]["observed_runs"][_EVENING])

    def test_the_verdict_and_tally_of_the_neighbour_axis_do_not_move(self):
        """Третья секция не складывается с вердиктами ни одним числом."""
        self.stand.agent(_MORNING, [("data/shared.json", _DEPLOY_SLO)],
                         schedule=_DAILY_MORNING, name="morning")
        self.stand.agent(_EVENING, [("data/shared.json", _DEPLOY_SLO)],
                         schedule=_DAILY_EVENING, name="evening")
        self.stand.runs("morning", [0, 24, 48, 72])
        self.stand.runs("evening", [12, 36, 60, 84])
        doc = self.stand.measure()
        self.assertEqual(sum(doc["tally"].values()), doc["population"],
                         "секция предпосылки просочилась в сумму вердиктов")
        for key in doc["tally"]:
            self.assertNotIn("co_production", key)


def _co_produced_agents() -> list:
    """Сцена живой конституции: ОДИН артефакт за ДВУМЯ суточными агентами."""
    return [
        {"label": _MORNING, "schedule": _DAILY_MORNING,
         "produces": [{"artifact": "data/shared.json", "slo_hours": _DEPLOY_SLO}]},
        {"label": _EVENING, "schedule": _DAILY_EVENING,
         "produces": [{"artifact": "data/shared.json", "slo_hours": _DEPLOY_SLO}]},
    ]


def _abstention_section() -> dict:
    """Секция объявленной оси с ДВУМЯ воздержавшимися парами на ОДИН артефакт."""
    return {"abstained": [
        {"artifact": "data/shared.json", "agent": _MORNING,
         "declared_vs_floor": sp.DECLARED_CO_PRODUCED},
        {"artifact": "data/shared.json", "agent": _EVENING,
         "declared_vs_floor": sp.DECLARED_CO_PRODUCED},
    ]}


if __name__ == "__main__":
    unittest.main()
