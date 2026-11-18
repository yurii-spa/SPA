"""Батарея прибора `spa_core/monitoring/red_set_delta.py` (цикл #1194).

# LLM_FORBIDDEN

Каждая проверка здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: она либо воспроизводит замер
на ЖИВЫХ документах двух контрольных прогонов, либо рвёт ОДНО звено и требует
названного отказа. Проба «зелёная на целом контуре, красная на каждом
порванном звене» — требование `.claude/rules/acceptance.md` п. 3.

ЖИВОЙ ВХОД И ИЗВЕСТНЫЙ ЧЛЕН (форма G1029 п. 2). Предмет прибора — дельта двух
документов, поэтому «живым деревом» для него является живой ДОКУМЕНТ, а не
каталог: в `fixtures/red_set_delta_runs.json` лежит дистиллят двух настоящих
артефактов `ci-control-report` (прогоны 44287563961 и 44302538342). Известные
члены по обе стороны названы НЕ из ответа прибора, а вычитаны из артефакта
руками до того, как прибор был написан:

* род обморока — `test_child_env_census::test_every_outcome_the_doors_return_is_declared`
  (пришло) и три имени `test_known_member_probe_census`;
* род дефекта — два имени `test_office_absent_artifact_producer_aware` (ушло,
  починено циклом #1193).

ДАТ В ЭТОМ ФАЙЛЕ НЕТ ни одной: прибор о свежести не судит, календарной двери у
него не существует, поэтому и фикстура времени не несёт.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from spa_core.monitoring import red_set_delta as rsd

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "red_set_delta_runs.json"

#: Известные члены, вычитанные из артефакта РУКАМИ — не из ответа прибора.
KNOWN_ARRIVED_WALLCLOCK = (
    "spa_core/tests/test_child_env_census.py"
    "::test_every_outcome_the_doors_return_is_declared")
KNOWN_DEPARTED_DEFECT = (
    "spa_core/tests/test_office_absent_artifact_producer_aware.py"
    "::Scenes::test_third_outcome_closes_itself_on_the_next_run")


def _runs() -> tuple[dict, dict]:
    doc = json.loads(_FIXTURE.read_text(encoding="utf-8"))["runs"]
    return doc["44287563961"], doc["44302538342"]


class TheIdentityTranslationIsClosed(unittest.TestCase):
    """Правило перевода pytest → junit: закрытое, и обе формы названы."""

    def test_a_class_segment_becomes_a_dotted_prefix(self):
        self.assertEqual(
            rsd.junit_identity("spa_core/tests/test_x.py::C::test_y"),
            "spa_core.tests.test_x.C::test_y")

    def test_a_module_level_test_keeps_the_module_alone(self):
        self.assertEqual(
            rsd.junit_identity("spa_core/tests/test_x.py::test_y"),
            "spa_core.tests.test_x::test_y")

    def test_nested_classes_all_join_the_prefix(self):
        self.assertEqual(
            rsd.junit_identity("a/b/test_x.py::C::D::test_y"),
            "a.b.test_x.C.D::test_y")

    def test_a_name_without_a_test_part_is_the_module_itself(self):
        self.assertEqual(rsd.junit_identity("a/test_x.py"), "a.test_x")


class TheLiveDocumentsAreMeasuredAndKnownMembersAreShown(unittest.TestCase):
    """ЗАМЕР ЖИВЫХ ДОКУМЕНТОВ. Население литералом не закрепляется — только
    свойство: известный член обязан выйти СВОИМ родом (урок #1119)."""

    def test_both_rosters_are_measured(self):
        prev, curr = _runs()
        for label, doc in (("прежний", prev), ("текущий", curr)):
            with self.subTest(document=label):
                roster = rsd.roster_of(doc)
                self.assertEqual(roster.status, rsd.MEASURED, roster.reason)
                self.assertGreater(len(roster.names), 0)

    def test_every_rod_axis_name_joins_the_roster(self):
        """Если бы правило перевода врало, ростер отказал бы — это и есть
        проверка перевода на ЖИВЫХ данных, а не на выдуманной форме."""
        prev, curr = _runs()
        for doc in (prev, curr):
            roster = rsd.roster_of(doc)
            self.assertEqual(roster.status, rsd.MEASURED, roster.reason)
            self.assertEqual(set(roster.rods), set(roster.names))

    def test_the_known_arrived_name_comes_out_as_a_wallclock_faint(self):
        prev, curr = _runs()
        d = rsd.delta(prev, curr)
        self.assertEqual(d.status, rsd.MEASURED, d.reason)
        rows = {t.nodeid: t.rod for t in d.arrived}
        self.assertIn(KNOWN_ARRIVED_WALLCLOCK, rows,
                      "известный пришедший член не найден — замер, не нашедший "
                      "известного члена, мерой класса не является")
        self.assertEqual(rows[KNOWN_ARRIVED_WALLCLOCK], rsd.ROD_WALLCLOCK)

    def test_the_known_departed_name_comes_out_as_a_defect(self):
        prev, curr = _runs()
        d = rsd.delta(prev, curr)
        rows = {t.nodeid: t.rod for t in d.departed}
        self.assertIn(KNOWN_DEPARTED_DEFECT, rows)
        self.assertEqual(rows[KNOWN_DEPARTED_DEFECT], rsd.ROD_DEFECT)

    def test_not_one_arrival_of_this_delta_carries_a_verdict(self):
        """Предмет находки цикла #1194: предписанное чтение выдало бы ЧЕТЫРЕ
        пришедших имени за регрессию, а вердикта о них нет ни одного."""
        prev, curr = _runs()
        d = rsd.delta(prev, curr)
        self.assertEqual(len(d.arrived), 4)
        self.assertEqual(d.defect_arrivals, ())
        self.assertEqual(
            {t.rod for t in d.arrived}, {rsd.ROD_WALLCLOCK},
            "все четыре пришедших имени обязаны выйти родом часов")

    def test_the_rod_of_a_departure_is_asked_of_the_document_that_had_it(self):
        prev, curr = _runs()
        d = rsd.delta(prev, curr)
        self.assertTrue(d.departed)
        for row in d.departed:
            with self.subTest(name=row.nodeid):
                self.assertEqual(row.rod_from, "prev")
        for row in d.arrived:
            with self.subTest(name=row.nodeid):
                self.assertEqual(row.rod_from, "curr")

    def test_the_sum_over_rods_equals_the_number_of_transitions(self):
        """Тождество инв. #17: без него остаток исчезал бы молча."""
        prev, curr = _runs()
        d = rsd.delta(prev, curr)
        for rows in (d.arrived, d.departed):
            self.assertEqual(
                sum(len(v) for v in d.by_rod(rows).values()), len(rows))

    def test_the_report_names_the_faint_as_not_a_regression(self):
        prev, curr = _runs()
        text = "\n".join(rsd.format_delta(rsd.delta(prev, curr)))
        self.assertIn("РЕГРЕССИЕЙ НЕ ЯВЛЯЕТСЯ", text)
        self.assertIn("гнаться стои́т за 0", text)

    def test_the_report_refuses_to_call_a_departed_faint_a_fix(self):
        """Сцена взята ТЕМИ ЖЕ живыми документами, но в обратном порядке: тогда
        четыре имени рода часов УХОДЯТ, и отчёт обязан сказать, что они НЕ
        починены — сторож лишь успел дойти до вердикта.

        Дыру нашла мутация M14 спецификации `RSD-1055`: без этой проверки строку
        можно было вырезать, и набор упавших имён не менялся.
        """
        prev, curr = _runs()
        d = rsd.delta(curr, prev)                      # обратный порядок — нарочно
        departed = {t.nodeid: t.rod for t in d.departed}
        self.assertIn(KNOWN_ARRIVED_WALLCLOCK, departed)
        self.assertEqual(departed[KNOWN_ARRIVED_WALLCLOCK], rsd.ROD_WALLCLOCK)
        self.assertIn("НЕ ПОЧИНЕНО", "\n".join(rsd.format_delta(d)))


class EveryBrokenLinkRefusesByNAME(unittest.TestCase):
    """Порванное звено ⇒ `unmeasured` с НАЗВАННОЙ причиной, а не «пришло 0»."""

    def _curr(self) -> dict:
        return copy.deepcopy(_runs()[1])

    def test_a_document_that_is_not_a_mapping_refuses(self):
        d = rsd.delta(_runs()[0], ["не", "словарь"])
        self.assertEqual(d.status, rsd.UNMEASURED)
        self.assertIn("не словарь", d.reason)

    def test_a_document_without_a_roster_refuses(self):
        doc = self._curr()
        doc.pop("failures")
        d = rsd.delta(_runs()[0], doc)
        self.assertEqual(d.status, rsd.UNMEASURED)
        self.assertIn("failures", d.reason)

    def test_a_roster_row_without_a_nodeid_refuses(self):
        doc = self._curr()
        doc["failures"][0] = {"outcome": "failed"}
        d = rsd.delta(_runs()[0], doc)
        self.assertEqual(d.status, rsd.UNMEASURED)
        self.assertIn("nodeid", d.reason)

    def test_a_document_without_the_ROD_AXIS_refuses_instead_of_guessing(self):
        """Самое дорогое звено: без оси родов «все имена — дефекты» было бы
        догадкой, а выглядело бы замером."""
        doc = self._curr()
        doc["cause_axis"] = {}
        d = rsd.delta(_runs()[0], doc)
        self.assertEqual(d.status, rsd.UNMEASURED)
        self.assertIn("cause_axis.fork", d.reason)
        self.assertEqual(d.arrived, ())

    def test_a_rod_axis_that_is_not_a_list_refuses(self):
        doc = self._curr()
        doc["cause_axis"]["fork"]["wallclock_names"] = "одно имя строкой"
        d = rsd.delta(_runs()[0], doc)
        self.assertEqual(d.status, rsd.UNMEASURED)
        self.assertIn("wallclock_names", d.reason)

    def test_a_rod_name_outside_the_roster_refuses(self):
        doc = self._curr()
        doc["cause_axis"]["fork"]["wallclock_names"].append(
            "spa_core.tests.test_nobody::test_nothing")
        d = rsd.delta(_runs()[0], doc)
        self.assertEqual(d.status, rsd.UNMEASURED)
        self.assertIn("test_nobody", d.reason)

    def test_two_roster_rows_with_one_identity_refuse(self):
        doc = self._curr()
        # Столкновение НЕ выдумано: пакет `test_a` с модулем `B.py` и класс
        # `B` в модуле `test_a.py` дают junit одну и ту же идентичность.
        doc["failures"].append({"nodeid": "spa_core/tests/test_a.py::B::test_c"})
        doc["failures"].append({"nodeid": "spa_core/tests/test_a/B.py::test_c"})
        d = rsd.delta(_runs()[0], doc)
        self.assertEqual(d.status, rsd.UNMEASURED)
        self.assertIn("одну идентичность", d.reason)

    def test_half_a_delta_is_not_a_delta(self):
        d = rsd.delta(None, _runs()[1])
        self.assertEqual(d.status, rsd.UNMEASURED)
        text = "\n".join(rsd.format_delta(d))
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertNotIn("ПРИШЛО", text)


class ZeroIsMeasuredNotMissing(unittest.TestCase):
    """Третий исход отделён от второго: «переходов нет» — ЗАМЕР."""

    def test_the_same_document_against_itself_is_measured_empty(self):
        _, curr = _runs()
        d = rsd.delta(curr, copy.deepcopy(curr))
        self.assertEqual(d.status, rsd.MEASURED_EMPTY)
        self.assertTrue(d.measured)
        self.assertFalse(d.has_findings)
        self.assertIn("ИЗМЕРЕНО И РАВНО НУЛЮ", "\n".join(rsd.format_delta(d)))

    def test_an_empty_red_set_is_a_measurement_not_a_refusal(self):
        green = {"run": {"id": "0"}, "sha": "0" * 40, "failures": [],
                 "cause_axis": {"fork": {"wallclock_names": [],
                                         "runner_environment_names": []}}}
        roster = rsd.roster_of(green)
        self.assertEqual(roster.status, rsd.MEASURED)
        self.assertEqual(roster.names, {})

    def test_an_unmeasured_delta_IS_a_finding(self):
        """«Не измерено» молчать не имеет права — иначе оно неотличимо от нуля."""
        self.assertTrue(rsd.delta(None, None).has_findings)


class TheOutcomeVocabularyIsClosed(unittest.TestCase):
    """Перечни — мерка, которой прибор мерит сам себя (урок #1130)."""

    def test_every_declared_status_is_used_by_the_reader(self):
        _, curr = _runs()
        prev, _ = _runs()
        seen = {
            rsd.delta(prev, curr).status,
            rsd.delta(curr, copy.deepcopy(curr)).status,
            rsd.delta(None, curr).status,
        }
        self.assertEqual(seen, set(rsd.STATUSES))

    def test_every_rod_has_a_human_label(self):
        self.assertEqual(set(rsd.ROD_LABEL), set(rsd.RODS))

    def test_the_runner_environment_rod_is_read_from_the_live_document(self):
        _, curr = _runs()
        roster = rsd.roster_of(curr)
        self.assertIn(rsd.ROD_RUNNER_ENV, set(roster.rods.values()),
                      "ось окружения раннера объявлена документом — прибор "
                      "обязан её прочитать, а не числить все имена дефектами")


class TheInstrumentOnlyReads(unittest.TestCase):
    """ADVISORY: ни записи, ни подпроцесса, ни двери к календарю."""

    def test_the_module_opens_no_door_to_the_world(self):
        source = (Path(__file__).resolve().parents[1]
                  / "monitoring" / "red_set_delta.py").read_text(encoding="utf-8")
        for forbidden in ("import subprocess", "import urllib", "datetime",
                          "os.getpid", "open(", "write_text"):
            with self.subTest(door=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
