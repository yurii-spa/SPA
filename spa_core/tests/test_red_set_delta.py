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


#: ЖИВАЯ ПАРА ДЛЯ ОСИ ПЕРЕЕЗДА (ADR-1077, цикл #1222) — ровно та, у которой
#: цикл #1219 намерил переезд РУКАМИ по артефактам `ctl-manifest`
#: (`.claude/rules/deployment.md`, § «СОСЕД ПО ПРОЦЕССУ»). Номера шардов ниже
#: вычитаны из таблицы ТОГО замера, а НЕ из ответа прибора.
_SHARD_FIXTURE = (Path(__file__).resolve().parent / "fixtures"
                  / "red_set_delta_shards.json")
SHARD_PREV_RUN, SHARD_CURR_RUN = "45091782823", "45108124169"

#: пришло И переехало — род ДЕФЕКТА, то есть ровно то, за чем прежняя редакция
#: прибора велела бы гнаться
KNOWN_MOVED_ARRIVALS = {
    ("spa_core/tests/test_hermetic_launchd_door.py"
     "::test_the_prod_code_really_does_call_a_mutating_launchctl"): (8, 11),
    ("spa_core/tests/test_tb_sanitizer_probe.py::TbSanitizerProbeDiscriminates"
     "::test_a_sanitizer_that_is_never_called_is_unmeasured_not_refused"): (11, 6),
    ("spa_core/tests/test_tb_sanitizer_probe.py::TbSanitizerProbeDiscriminates"
     "::test_the_unittest_queue_cut_out_is_refused_and_not_by_substring"): (11, 6),
}
#: пришло и НЕ переезжало — без этого члена «все переехали» было бы свойством
#: пары, а не ответом оси
KNOWN_STAYED_ARRIVAL = (
    "spa_core/tests/test_ledger_census_reader.py::LedgerCensusReaderWiring"
    "::test_whole_contour_is_intact_on_the_real_tree")
#: ушло, переехало И было починено СОДЕРЖАНИЕМ (цикл #1218) — два ответа у
#: одной оси, предмет пункта 5 заказа G1064
KNOWN_MOVED_DEPARTURE = (
    "spa_core/tests/test_script_path_launch_imports.py"
    "::TestPathLaunchImportRatchet::test_no_new_script_breaks_when_launched_by_path")


def _shard_pair() -> tuple[dict, dict, rsd.ShardMap, rsd.ShardMap]:
    raw = json.loads(_SHARD_FIXTURE.read_text(encoding="utf-8"))
    return (raw["runs"][SHARD_PREV_RUN], raw["runs"][SHARD_CURR_RUN],
            rsd.shard_map_of({"shards": _shards_from(raw, SHARD_PREV_RUN)},
                             label="прежний план"),
            rsd.shard_map_of({"shards": _shards_from(raw, SHARD_CURR_RUN)},
                             label="текущий план"))


def _shards_from(raw: dict, run: str) -> list:
    """Карта фикстуры (файл → шард) в ФОРМУ ПРОИЗВОДИТЕЛЯ (`shards: [{…}]`).

    Фикстура хранит карту плоской — так её читают глазами, — а прибор обязан
    разбирать РОВНО ту форму, которую пишет `ci_control.cmd_plan`. Разворот
    живёт здесь, а не в приборе: иначе у вопроса «какую форму мы читаем» стало
    бы два ответа.
    """
    buckets: dict[int, list[str]] = {}
    for path, shard in raw["shard_maps"][run].items():
        buckets.setdefault(shard, []).append(path)
    return [{"shard": k, "files": v} for k, v in sorted(buckets.items())]


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


# ───────────────── ось ПЕРЕЕЗДА (шард) — ADR-1077, цикл #1222 ────────────────

class TheShardAxisIsMeasuredOnTheLivePair(unittest.TestCase):
    """Живая пара 45091782823 → 45108124169: та, что мерили РУКАМИ циклом #1219.

    Известные члены по обе стороны вычитаны из таблицы ТОГО замера
    (`.claude/rules/deployment.md`), а не из ответа прибора.
    """

    def setUp(self):
        self.prev, self.curr, self.pm, self.cm = _shard_pair()
        self.d = rsd.delta(self.prev, self.curr,
                           prev_shards=self.pm, curr_shards=self.cm)

    def test_both_shard_maps_are_measured(self):
        self.assertTrue(self.pm.measured, self.pm.reason)
        self.assertTrue(self.cm.measured, self.cm.reason)
        self.assertTrue(self.d.shard_axis_measured)

    def test_every_known_defect_arrival_MOVED_with_the_numbers_of_the_hand_measure(self):
        got = {t.nodeid: (t.shard, t.shard_prev, t.shard_curr)
               for t in self.d.defect_arrivals}
        self.assertEqual(set(got), set(KNOWN_MOVED_ARRIVALS),
                         "состав пришедших имён рода дефекта разошёлся с замером #1219")
        for nodeid, (was, now_) in KNOWN_MOVED_ARRIVALS.items():
            with self.subTest(name=nodeid):
                self.assertEqual(got[nodeid], (rsd.SHARD_MOVED, was, now_))

    def test_three_of_three_arrivals_to_chase_become_a_THIRD_outcome(self):
        """Прежняя редакция велела бы гнаться за тремя именами. Все три переехали."""
        self.assertEqual(len(self.d.defect_arrivals), 3)
        self.assertEqual(self.d.chase, (),
                         "«гнаться» обязано опустеть: вердикта о содержании нет")
        self.assertEqual(len(self.d.shard_blind_arrivals), 3)

    def test_an_arrival_that_did_NOT_move_exists_in_the_same_pair(self):
        """Иначе «все переехали» было бы свойством ПАРЫ, а не ответом оси."""
        stayed = [t for t in self.d.arrived if t.shard == rsd.SHARD_SAME]
        self.assertEqual([t.nodeid for t in stayed], [KNOWN_STAYED_ARRIVAL])
        self.assertEqual(stayed[0].shard_prev, stayed[0].shard_curr)
        self.assertIsNone(stayed[0].shard_why)

    def test_the_departure_that_moved_is_not_declared_fixed(self):
        """Пункт 5 заказа G1064: «переехал» ≠ «не регрессия» и ≠ «починен»."""
        moved = {t.nodeid: (t.shard_prev, t.shard_curr)
                 for t in self.d.moved_departures}
        self.assertIn(KNOWN_MOVED_DEPARTURE, moved)
        self.assertEqual(moved[KNOWN_MOVED_DEPARTURE], (1, 11))
        line = [ln for ln in rsd.format_delta(self.d) if "ПЕРЕЕХАЛО" in ln]
        self.assertTrue(line, "отчёт о переехавших ушедших именах молчит")
        self.assertIn("НЕ объявляет", line[0])

    def test_the_sum_over_the_shard_axis_equals_the_number_of_transitions(self):
        for title, rows in (("ПРИШЛО", self.d.arrived), ("УШЛО", self.d.departed)):
            with self.subTest(side=title):
                groups = self.d.by_shard(rows)
                self.assertEqual(sum(len(v) for v in groups.values()), len(rows))

    def test_the_report_names_the_third_outcome_not_a_regression(self):
        lines = rsd.format_delta(self.d)
        third = [ln for ln in lines if "ТРЕТИЙ исход" in ln]
        self.assertTrue(third, "третий исход в отчёте не назван")
        tail = [ln for ln in lines if ln.strip().startswith("→ гнаться")]
        self.assertIn("за 0 именем", tail[0])

    def test_every_row_of_the_report_carries_the_shard_axis(self):
        # строка ИМЕНИ опознаётся ярлыком рода в квадратных скобках, а не
        # значком в начале: значок стои́т и у сводных строк отчёта, и счёт по
        # нему ответил бы о другом населении.
        marks = tuple(f"[{rod}]" for rod in rsd.RODS)
        rows = [ln for ln in rsd.format_delta(self.d)
                if any(m in ln for m in marks)]
        self.assertEqual(len(rows), len(self.d.arrived) + len(self.d.departed))
        for ln in rows:
            with self.subTest(line=ln[:60]):
                self.assertIn("⟂", ln)


class TheShardAxisRefusesByNAME(unittest.TestCase):
    """Каждое порванное звено карты — НАЗВАННЫЙ отказ, а не «шард тот же»."""

    def _ok_map(self):
        return rsd.shard_map_of({"shards": [{"shard": 0, "files": ["a.py"]},
                                            {"shard": 1, "files": ["b.py"]}]})

    def test_a_map_that_is_not_a_mapping_refuses(self):
        m = rsd.shard_map_of(["a.py"])
        self.assertEqual(m.status, rsd.UNMEASURED)
        self.assertIn("не словарь", m.reason)

    def test_a_map_without_the_shards_list_refuses(self):
        m = rsd.shard_map_of({"files": ["a.py"]})
        self.assertEqual(m.status, rsd.UNMEASURED)
        self.assertIn("`shards`", m.reason)

    def test_a_row_without_a_shard_number_refuses(self):
        m = rsd.shard_map_of({"shards": [{"files": ["a.py"]}]})
        self.assertEqual(m.status, rsd.UNMEASURED)
        self.assertIn("без номера шарда", m.reason)

    def test_a_files_field_that_is_not_a_list_refuses(self):
        m = rsd.shard_map_of({"shards": [{"shard": 3, "files": "a.py"}]})
        self.assertEqual(m.status, rsd.UNMEASURED)
        self.assertIn("`files`", m.reason)

    def test_a_file_that_is_not_a_path_refuses(self):
        m = rsd.shard_map_of({"shards": [{"shard": 3, "files": [None]}]})
        self.assertEqual(m.status, rsd.UNMEASURED)
        self.assertIn("это не путь", m.reason)

    def test_one_file_in_two_shards_refuses_instead_of_choosing(self):
        m = rsd.shard_map_of({"shards": [{"shard": 1, "files": ["a.py"]},
                                         {"shard": 7, "files": ["a.py"]}]})
        self.assertEqual(m.status, rsd.UNMEASURED)
        self.assertIn("выбрать один из двух", m.reason)

    def test_a_map_with_no_files_at_all_refuses(self):
        """Иначе «файла нет в населении» сказалось бы о КАЖДОМ имени."""
        m = rsd.shard_map_of({"shards": [{"shard": 0, "files": []}]})
        self.assertEqual(m.status, rsd.UNMEASURED)
        self.assertIn("ни одного файла", m.reason)

    def test_a_raw_manifest_instead_of_a_ShardMap_refuses(self):
        """Второй разбор манифеста разошёлся бы с первым молча (класс ADR-220)."""
        prev, curr, pm, _ = _shard_pair()
        d = rsd.delta(prev, curr, prev_shards={"shards": []}, curr_shards=pm)
        self.assertEqual(d.status, rsd.MEASURED)
        self.assertFalse(d.shard_axis_measured)
        self.assertIn("`ShardMap`", d.prev_shards.reason)
        self.assertTrue(all(t.shard == rsd.SHARD_UNMEASURED for t in d.arrived))

    def test_no_map_at_all_is_UNMEASURED_at_every_transition_not_silence(self):
        prev, curr = _runs()
        d = rsd.delta(prev, curr)
        self.assertEqual(d.status, rsd.MEASURED)
        self.assertFalse(d.shard_axis_measured)
        self.assertTrue(d.arrived, "сцена без переходов ничего бы не проверила")
        for t in d.arrived + d.departed:
            with self.subTest(name=t.nodeid):
                self.assertEqual(t.shard, rsd.SHARD_UNMEASURED)
                # причина НАЗЫВАЕТ и сторону («прежнего прогона»), и повод —
                # поэтому проверяется вхождением, а не равенством: сторона есть
                # часть ответа, без неё две слепые карты неразличимы.
                self.assertIn(rsd.NO_SHARD_MAP_REASON, t.shard_why)
        self.assertEqual(d.chase, ())

    def test_a_blind_axis_does_NOT_ruin_the_rod_delta(self):
        """Разница ПО ПРЕДМЕТУ: ростер отвечает о красноте, карта — о соседстве."""
        prev, curr = _runs()
        with_map = rsd.delta(prev, curr, prev_shards=self._ok_map(),
                             curr_shards=self._ok_map())
        without = rsd.delta(prev, curr)
        self.assertEqual(without.status, rsd.MEASURED)
        self.assertEqual([t.nodeid for t in without.arrived],
                         [t.nodeid for t in with_map.arrived])
        self.assertEqual([t.rod for t in without.arrived],
                         [t.rod for t in with_map.arrived])

    def test_a_file_missing_from_one_map_is_ABSENT_not_SAME(self):
        prev, curr, pm, cm = _shard_pair()
        thin = rsd.ShardMap(status=rsd.MEASURED, reason=None, run=pm.run,
                            by_file={k: v for k, v in pm.by_file.items()
                                     if "test_tb_sanitizer_probe" not in k})
        d = rsd.delta(prev, curr, prev_shards=thin, curr_shards=cm)
        absent = [t for t in d.arrived if t.shard == rsd.SHARD_ABSENT]
        self.assertTrue(absent, "выпавший из карты файл не назван отсутствующим")
        for t in absent:
            with self.subTest(name=t.nodeid):
                self.assertIn("нет в населении прежнего прогона", t.shard_why)
                self.assertIsNone(t.shard_prev)
        self.assertEqual(d.chase, (), "ABSENT «гнаться» не открывает")

    def test_half_a_delta_still_carries_the_shard_maps_it_was_given(self):
        """Ростер слеп, а карта прочитана — это РАЗНЫЕ немочи, и обе названы."""
        _, curr, pm, cm = _shard_pair()
        d = rsd.delta(None, curr, prev_shards=pm, curr_shards=cm)
        self.assertEqual(d.status, rsd.UNMEASURED)
        self.assertTrue(d.shard_axis_measured)


class TheShardVocabularyIsClosedAndREACHABLE(unittest.TestCase):
    """Род обязан быть ДОСТИЖИМ до того, как печатать его ноль (урок #1163)."""

    def test_every_shard_verdict_has_a_human_label(self):
        self.assertEqual(set(rsd.SHARD_LABEL), set(rsd.SHARD_VERDICTS))

    def test_every_shard_verdict_is_actually_produced_by_the_reader(self):
        prev, curr, pm, cm = _shard_pair()
        thin = rsd.ShardMap(status=rsd.MEASURED, reason=None, run=pm.run,
                            by_file={k: v for k, v in pm.by_file.items()
                                     if "test_tb_sanitizer_probe" not in k})
        seen = set()
        for pair in ((pm, cm), (thin, cm), (None, None)):
            d = rsd.delta(prev, curr, prev_shards=pair[0], curr_shards=pair[1])
            seen.update(t.shard for t in d.arrived + d.departed)
        self.assertEqual(seen, set(rsd.SHARD_VERDICTS),
                         "исход объявлен и НЕДОСТИЖИМ — его ноль был бы "
                         "свойством прибора, а не замером")

    def test_every_shard_verdict_has_its_own_tag_in_the_report(self):
        tags = {v: rsd.shard_tag(rsd.Transition(
            nodeid="a.py::t", identity="a::t", rod=rsd.ROD_DEFECT,
            rod_from="curr", shard=v, shard_prev=1, shard_curr=2))
            for v in rsd.SHARD_VERDICTS}
        self.assertEqual(len(set(tags.values())), len(rsd.SHARD_VERDICTS),
                         f"два исхода печатаются одним словом: {tags}")


if __name__ == "__main__":
    unittest.main()
