"""У ОТРИЦАНИЯ объявленной оси должно быть ПРАВОМОЧИЕ (ADR-816).

Заказ **G815 п. 2** стоячего приказа владельца «Portfolio CIO»: четыре пары
``deployment_*`` на объявленной оси — артефакт с ДВУМЯ производителями;
объявленная ось судит АГЕНТА, наблюдённая — АРТЕФАКТ, расхождение здесь ВЕРНО,
и сводить две оси в одно число запрещено.

Замер 26.10 на живой конституции (231 пара «агент × артефакт» со сроком): ниже
пола на объявленной оси **6** пар, и **4** из них — один и тот же случай.
``data/deployment_acceptance.json`` и ``data/deployment_drift.json`` (срок 15 ч)
объявлены за ``system_health_morning`` (``calendar:08:00``) и
``system_health_evening`` (``calendar:20:00``). Такт каждого 24 ч ⇒ пол 26 ч, и
поагентно срок 15 ч читается «ниже пола». У АРТЕФАКТА наблюдённый такт **12 ч**,
и срок он держит — ``slo_keepability`` зовёт обе пары ``keepable``.

**Правило не ново, ново его ИСПОЛНЕНИЕ.** Докстрока ``slo_keepability.measure``
говорит это дословно и теми же двумя агентами в примере: «судить такую пару
поагентно значило бы печатать находку там, где обещание выдерживается». Прозой
оно прожило до ADR-816, и четыре пары всплывали в каждой переписи заново — у
записки нет читателя.

Каждый тест ниже — положительный контроль на ИЗМЕРЕННУЮ пару, а не на
выдуманную: числа взяты из строк живого прибора (``slo_keepability --json``) и
названы в ADR-816.

Литеральных дат и стенных часов в файле НЕТ по построению: предмет — чистые
функции «такт · срок · правомочие → вердикт», времени в них не участвует.
"""
from __future__ import annotations

import unittest

from spa_core.monitoring import slo_keepability as sk
from spa_core.monitoring import slo_proposal as sp

#: ИЗМЕРЕННЫЕ пары живой конституции. Расписание и срок — дословно из
#: `architecture/manifest.json`, медиана — из строки прибора по тому же артефакту.
_DAILY_MORNING = "calendar:08:00"
_DAILY_EVENING = "calendar:20:00"
_DEPLOY_SLO = 15.0          # срок `deployment_acceptance.json` / `deployment_drift.json`
_DEPLOY_MEDIAN = 12.0       # наблюдённый такт АРТЕФАКТА (два агента в 12 ч друг от друга)
_HEALTH_SLO = 26.0          # `system_health.json` — те же два производителя, срок выше пола


class StandingIsAskedOfTheDeclaredWorld(unittest.TestCase):
    """Три исхода правомочия, и третий — не украшение (инв. #17)."""

    def test_one_declared_producer_gives_standing(self):
        standing, why = sp.declared_axis_standing(1)
        self.assertIs(standing, True, why)

    def test_two_declared_producers_remove_standing(self):
        standing, why = sp.declared_axis_standing(2)
        self.assertIs(standing, False, why)
        self.assertIn("2", why, "число производителей обязано быть НАЗВАНО в причине")

    def test_uncounted_producers_are_a_third_outcome_not_an_assumed_one(self):
        """Подстановка единицы вернула бы ровно тот дефект, что закрывает дверь.

        Широкий проход по формам. ВНИМАНИЕ: утверждение под ``subTest`` мутациям
        по дельте НЕВИДИМО — набор упавших ИМЁН от него не меняется, и мутация
        «артефакт без производителя получил правомочие» этот проход ПЕРЕЖИЛА
        (замер батареи ADR-816: выжил 1 из 11). Поэтому каждая граница, которую
        эта дверь обязана держать, продублирована ОТДЕЛЬНЫМ тестом ниже —
        проход остаётся как обзор, а носителем claim'а он быть не может.
        """
        for value in (None, "2", 1.0, True, False, 0, -1):
            with self.subTest(co_producers=value):
                standing, why = sp.declared_axis_standing(value)
                self.assertIsNone(standing, f"«не посчитали» выдано за ответ: {why}")
                self.assertTrue(why.strip(), "третий исход без названной причины")

    def test_zero_declared_producers_is_unmeasured_not_a_denial(self):
        """Носитель claim'а вне ``subTest`` — его и убивает мутация.

        Артефакт без объявленного производителя судить НЕ О ЧЕМ: такта нет,
        пола нет. Вернуть здесь «правомочия нет» значило бы сказать, что ось
        воздержалась из-за со-производства, которого не существует, — то есть
        назвать верную причину неверной.
        """
        standing, why = sp.declared_axis_standing(0)
        self.assertIsNone(standing, why)
        self.assertIn("0", why, "число производителей не названо в причине")

    def test_a_negative_producer_count_is_unmeasured(self):
        standing, why = sp.declared_axis_standing(-1)
        self.assertIsNone(standing, why)

    def test_a_non_integer_producer_count_is_unmeasured(self):
        for value, label in ((None, "не посчитали вовсе"), ("2", "строка вместо числа"),
                             (1.0, "дробное"), (True, "булево")):
            standing, why = sp.declared_axis_standing(value)
            self.assertIsNone(standing, f"{label}: выдано за ответ — {why}")


class TheFourMeasuredDeploymentPairsStopBeingFindings(unittest.TestCase):
    """Положительный контроль на настоящую ложную находку."""

    def test_without_standing_the_pair_reads_as_a_finding(self):
        """Та же пара БЕЗ вопроса о правомочии — ровно то, что печаталось до ADR-816."""
        floor, _ = sp.architect_floor(_DAILY_MORNING)
        self.assertEqual(floor, 26.0, "пол суточного агента сдвинулся — замер устарел")
        axis, note = sp.audit_curated(_DEPLOY_SLO, floor, _DEPLOY_MEDIAN)
        self.assertEqual(axis, sp.CURATED_MARGIN_ONLY, note)

    def test_with_two_declared_producers_the_axis_abstains(self):
        for schedule in (_DAILY_MORNING, _DAILY_EVENING):
            with self.subTest(schedule=schedule):
                axis, note = sp.audit_declared(_DEPLOY_SLO, schedule, _DEPLOY_MEDIAN, 2)
                self.assertEqual(axis, sp.DECLARED_CO_PRODUCED, note)

    def test_the_abstention_names_what_it_would_have_said(self):
        """Воздержание обязано быть ЧИТАЕМЫМ, иначе находка просто исчезает.

        Проверяется СУЩЕСТВО, а не внутренний ярлык: ярлыка отрицания здесь нет
        и быть не может — правомочие спрашивается РАНЬШЕ, чем медиана делит
        отрицание на два состояния (см. порядок вопросов в ``audit_declared``).
        Поэтому причина обязана назвать оба числа сравнения и сам факт, что
        отрицание отклонено.
        """
        _, note = sp.audit_declared(_DEPLOY_SLO, _DAILY_MORNING, _DEPLOY_MEDIAN, 2)
        self.assertIn("15", note, "не назван срок, о котором шла речь")
        self.assertIn("26", note, "не назван пол, против которого сравнивали")
        self.assertIn("отрицание", note, "не сказано, что именно отклонено")
        self.assertIn("наблюдённая ось", note, "не сказано, кто отвечает вместо неё")

    def test_uncounted_producers_abstain_separately_from_co_production(self):
        """«Не посчитали» и «их несколько» лечатся разным — и различимы."""
        axis, note = sp.audit_declared(_DEPLOY_SLO, _DAILY_MORNING, _DEPLOY_MEDIAN, None)
        self.assertEqual(axis, sp.DECLARED_STANDING_UNMEASURED, note)
        self.assertNotEqual(sp.DECLARED_STANDING_UNMEASURED, sp.DECLARED_CO_PRODUCED)


class RealFindingsSurviveTheDoor(unittest.TestCase):
    """Контроль ОБРАТНОЙ стороны: лекарство не смеет глушить сторожа (инв. #16)."""

    def test_single_producer_remnants_stay_findings(self):
        # Оба остатка замера 26.10, названные поимённо в ADR-815: производитель
        # ОДИН, утверждение про артефакт верно, находка обязана остаться.
        for slo, schedule, median, who in (
                (7, "interval:21600s", 6.001, "architecture_conformance: такт 6 ч, срок 7 ч"),
                (1, "interval:3600s", 1.0, "chief_investment: 1 ч/1 ч, случай ADR-549")):
            with self.subTest(who=who):
                axis, note = sp.audit_declared(slo, schedule, median, 1)
                self.assertIn(axis, (sp.CURATED_BELOW, sp.CURATED_MARGIN_ONLY),
                              f"{who} — находка ПОГАШЕНА правомочием: {note}")

    def test_a_broken_promise_is_not_excused_by_co_production(self):
        """Со-производство снимает отрицание ОСИ, а не само нарушение.

        Пара, где медиана ПРЕВЫШАЕТ срок, на объявленной оси воздерживается —
        но нарушение меряет наблюдённая ось, и там предмет АРТЕФАКТ целиком.
        Проверяем, что воздержание не выдаётся за «выдерживает».
        """
        axis, note = sp.audit_declared(_DEPLOY_SLO, _DAILY_MORNING, 40.0, 2)
        self.assertNotEqual(axis, sp.CURATED_ABOVE, note)
        self.assertEqual(axis, sp.DECLARED_CO_PRODUCED, note)


class StandingIsAsymmetricByConstruction(unittest.TestCase):
    """Правомочие спрашивается ТОЛЬКО у отрицания, и это доказуемо, а не вкус."""

    def test_a_positive_verdict_needs_no_standing(self):
        # `data/system_health.json`: те же ДВА производителя, срок 26 ч, пол 26 ч.
        # «Этот агент один способен держать срок» для файла ДОСТАТОЧНО.
        axis, note = sp.audit_declared(_HEALTH_SLO, _DAILY_MORNING, _DEPLOY_MEDIAN, 2)
        self.assertEqual(axis, sp.CURATED_ABOVE, note)

    def test_the_positive_verdict_is_identical_with_and_without_co_producers(self):
        for count in (1, 2, 7, None):
            with self.subTest(co_producers=count):
                axis, _ = sp.audit_declared(_HEALTH_SLO, _DAILY_MORNING,
                                            _DEPLOY_MEDIAN, count)
                self.assertEqual(axis, sp.CURATED_ABOVE,
                                 "правомочие израсходовано на утверждение, которому "
                                 "оно не нужно — положительная сторона потеряна")


class TheDoorDelegatesAndKeepsNoSecondCopyOfTheRule(unittest.TestCase):
    """Контроль ДВЕРИ: пол и сравнение остаются чужими (урок мутации №2, ADR-814)."""

    def test_the_verdict_moves_with_the_schedule_it_was_given(self):
        """Расписание — вход: подмени его, и вердикт обязан поехать."""
        # Часовой агент: пол 2 ч, срок 15 ч — выше пола, правомочие не при чём.
        axis, note = sp.audit_declared(_DEPLOY_SLO, "interval:3600s", _DEPLOY_MEDIAN, 2)
        self.assertEqual(axis, sp.CURATED_ABOVE, note)

    def test_an_unparsable_schedule_is_the_third_outcome_of_the_floor(self):
        axis, note = sp.audit_declared(_DEPLOY_SLO, "по понедельникам", _DEPLOY_MEDIAN, 2)
        self.assertEqual(axis, sp.CURATED_UNMEASURED, note)

    def test_the_margin_rule_is_not_reimplemented_here(self):
        """Пол приходит из единственной двери, а не из копии рядом."""
        floor, _ = sp.architect_floor(_DAILY_MORNING)
        self.assertEqual(floor, sp.floor_from_tact(24.0))


class TheCensusCountsProducersFromTheConstitution(unittest.TestCase):
    """Число производителей берётся из ОБЪЯВЛЕННОГО мира, а не из наблюдения.

    Взять его из ``rows[].producers`` значило бы свести две оси в одно число —
    то, что заказ G815 п. 2 запрещает дословно.
    """

    #: Сцена — две пары агентов на один артефакт, дословно форма живой конституции.
    _AGENTS = [
        {"label": "com.spa.morning", "schedule": _DAILY_MORNING,
         "produces": [{"artifact": "data/shared.json", "slo_hours": _DEPLOY_SLO},
                      {"artifact": "data/mine.json", "slo_hours": _DEPLOY_SLO}]},
        {"label": "com.spa.evening", "schedule": _DAILY_EVENING,
         "produces": [{"artifact": "data/shared.json", "slo_hours": _DEPLOY_SLO}]},
    ]

    def test_the_co_produced_artifact_abstains_and_the_lone_one_does_not(self):
        out = sk.declared_axis_census(self._AGENTS,
                                      {"data/shared.json": _DEPLOY_MEDIAN,
                                       "data/mine.json": _DEPLOY_MEDIAN})
        self.assertEqual(out["population"], 3)
        by_pair = {(r["agent"], r["artifact"]): r for r in
                   out["findings"] + out["abstained"]}
        self.assertEqual(by_pair[("com.spa.morning", "data/shared.json")]["declared_vs_floor"],
                         sp.DECLARED_CO_PRODUCED)
        self.assertEqual(by_pair[("com.spa.evening", "data/shared.json")]["declared_vs_floor"],
                         sp.DECLARED_CO_PRODUCED)
        lone = by_pair[("com.spa.morning", "data/mine.json")]
        self.assertIn(lone["declared_vs_floor"],
                      (sp.CURATED_BELOW, sp.CURATED_MARGIN_ONLY),
                      "единственный производитель потерял находку")

    def test_the_declared_producer_count_ignores_observation_entirely(self):
        """Медианы нет вовсе — правомочие всё равно измерено по конституции."""
        out = sk.declared_axis_census(self._AGENTS, {})
        kinds = {r["artifact"]: r["declared_vs_floor"] for r in out["abstained"]}
        self.assertEqual(kinds.get("data/shared.json"), sp.DECLARED_CO_PRODUCED)

    def test_abstentions_are_named_not_merely_counted(self):
        """Иначе четыре пары исчезают из отчёта и неотличимы от «их не было»."""
        out = sk.declared_axis_census(self._AGENTS, {"data/shared.json": _DEPLOY_MEDIAN})
        self.assertEqual(len(out["abstained"]), 2)
        for row in out["abstained"]:
            self.assertEqual(row["declared_producers"], 2)
            self.assertTrue(row["note"].strip())

    def test_a_pair_without_a_deadline_is_not_a_pair_of_this_axis(self):
        out = sk.declared_axis_census(
            [{"label": "com.spa.x", "schedule": _DAILY_MORNING,
              "produces": [{"artifact": "data/no_slo.json"}]}], {})
        self.assertEqual(out["population"], 0)
        self.assertEqual(out["tally"], {})


class TheOfficeLineIsTheOnlyFormAndHasAThirdOutcome(unittest.TestCase):
    """Строка шага 0-офис проверяема отдельно — в мосте её проверить нечем."""

    def test_a_missing_section_says_so_instead_of_printing_zero(self):
        line = sk.declared_axis_line({})
        self.assertIn("НЕ ИЗМЕРЕНО", line)
        self.assertIn("declared_axis", line)

    def test_a_present_section_reports_all_three_counts(self):
        line = sk.declared_axis_line({"declared_axis": {
            "population": 231, "tally": {sp.CURATED_ABOVE: 225},
            "findings": [{}, {}], "abstained": [{}, {}, {}, {}]}})
        for number in ("231", "225", "2", "4"):
            self.assertIn(number, line)

    def test_missing_sub_keys_are_not_printed_as_zero(self):
        """«Находок нет» и «находки не посчитаны» обязаны быть различимы."""
        line = sk.declared_axis_line({"declared_axis": {"population": 1}})
        self.assertEqual(line.count("НЕ ИЗМЕРЕНО"), 3, line)
        self.assertNotIn("находок 0", line)


if __name__ == "__main__":
    unittest.main()
