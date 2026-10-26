"""ADR-819 (заказ G818 п. 1): пишет ли артефакт ещё КТО-ТО, если производитель отставной.

Каждый тест здесь — положительный контроль на ОДНО звено. Воздержание ADR-818
(«агент не идёт — такта нет, срок судить не о чем») ВЕРНО и этим набором не
оспаривается; предмет набора — второй вопрос, живущий ВНУТРИ того воздержания:
девять пар конституции 26.10 были сняты с суда заслуженно, и ОДНА из девяти
скрывала живой дефект конституции — `data/governance_proposals.json` пишется
дневным циклом каждые сутки, а объявлен за `com.spa.governance_watcher`, которого
не запускают.

Часы здесь ВХОД, и отметки записи выставляются ОТНОСИТЕЛЬНО того же входа
(`.claude/rules/deployment.md`, приём №1): обе стороны сравнения закреплены, поэтому
календарь этот набор не трогает. Якорь-литерал `NOW` при этом в файле ЕСТЬ, и
пометка ниже обязательна — первая редакция докстроки утверждала обратное и была
НЕВЕРНА, храповик замороженных дат сказал это сразу.
"""
# FROZEN-DATE-OK: injected-clock — `NOW` уходит входом `now=` в
# `write_trace_observation` и `producer_reality_census`, а возраст каждого артефакта
# выставляется `os.utime` от ТОГО ЖЕ `NOW` (см. `_write`): обе стороны сравнения
# происходят от якоря, стенных часов в наборе нет ни одной двери.
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring import slo_keepability as sk
from spa_core.monitoring import slo_proposal as sp

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
REPO = Path(__file__).resolve().parents[2]


def _write(path: Path, doc, *, age_hours: float, now: datetime = NOW) -> Path:
    """Артефакт с ЗАДАННЫМ возрастом записи. Возраст — вход, а не свойство хоста."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc) if not isinstance(doc, str) else doc)
    stamp = (now - timedelta(hours=age_hours)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


class WriteTraceDoor(unittest.TestCase):
    """Дверь :func:`slo_proposal.write_trace` — пять исходов, каждый свой."""

    def test_fresh_trace_at_a_stopped_producer_is_a_finding(self):
        kind, why = sp.write_trace(4.8, 4.8, 168.0, present=True)
        self.assertEqual(kind, sp.TRACE_MISDECLARED)
        self.assertIn("КТО-ТО ДРУГОЙ", why)

    def test_stale_trace_means_nobody_writes_it(self):
        kind, why = sp.write_trace(1401.6, 1401.6, 168.0, present=True)
        self.assertEqual(kind, sp.TRACE_UNMAINTAINED)
        self.assertIn("не пишет его никто", why)

    def test_absent_artifact_is_its_own_outcome_not_merely_stale(self):
        """«Файла нет» и «файл старый» — РАЗНЫЕ положения дел.

        Склеить их значило бы потерять единственный признак того, что замер
        сделан не в том дереве: гора «отсутствует» об этом говорит, гора
        «старый» — нет.
        """
        kind, _ = sp.write_trace(None, None, 168.0, present=False)
        self.assertEqual(kind, sp.TRACE_ABSENT)
        self.assertNotEqual(kind, sp.TRACE_UNMAINTAINED)

    def test_two_probes_disagreeing_is_neither_finding_nor_unmaintained(self):
        """Так выглядит СКОПИРОВАННЫЙ файл: `mtime` свежий, своя отметка старая."""
        kind, why = sp.write_trace(1.0, 900.0, 168.0, present=True)
        self.assertEqual(kind, sp.TRACE_DISPUTED)
        self.assertNotIn(kind, (sp.TRACE_MISDECLARED, sp.TRACE_UNMAINTAINED))
        self.assertIn("ПРОТИВОПОЛОЖНОЕ", why)

    def test_disputed_in_the_other_direction_too(self):
        kind, _ = sp.write_trace(900.0, 1.0, 168.0, present=True)
        self.assertEqual(kind, sp.TRACE_DISPUTED)

    def test_second_probe_absent_leaves_the_verdict_on_one(self):
        kind, why = sp.write_trace(4.0, None, 168.0, present=True)
        self.assertEqual(kind, sp.TRACE_MISDECLARED)
        self.assertIn("вторая проба недоступна", why)

    def test_presence_unmeasured_is_not_absence(self):
        kind, why = sp.write_trace(None, None, 168.0, present=None)
        self.assertEqual(kind, sp.TRACE_UNMEASURED)
        self.assertNotEqual(kind, sp.TRACE_ABSENT)
        self.assertIn("НЕ ИЗМЕРЕНО", why)

    def test_presence_must_be_a_boolean_not_a_truthy_value(self):
        """НОСИТЕЛЬ ПРИТЯЗАНИЯ ЗДЕСЬ ПРОСТОЙ, А НЕ `subTest` — и это замер.

        Прогон мутаций 26.10: мутация «`present` судится ПРАВДИВОСТЬЮ, а не
        родом» ВЫЖИЛА, хотя тест её ловил и падал. Причина — у прибора дельты
        (`scripts/delta_mutation_run.py`, `_FAILED_LINE`) имена упавших
        собираются по `^(?:FAILED|ERROR)`, а `pytest-subtests` печатает
        `SUBFAILED(...)`: набор имён НЕ МЕНЯЕТСЯ, и прибор зовёт это «дырой
        покрытия». Класс известен (ADR-761, цикл #876) и ЖИВ. Притязание было
        верно — невидим был носитель, поэтому каждый случай несёт ещё и ПРОСТОЕ
        утверждение, а перечень под `subTest` оставлен как расширение.
        """
        kind, why = sp.write_trace(4.0, None, 168.0, present="да")
        self.assertEqual(kind, sp.TRACE_UNMEASURED)
        self.assertIn("НЕ ИЗМЕРЕНО", why)
        self.assertEqual(sp.write_trace(4.0, None, 168.0, present=1)[0],
                         sp.TRACE_UNMEASURED)
        for odd in (0, [], {}, 1.0, "нет"):
            with self.subTest(present=odd):
                kind, _ = sp.write_trace(4.0, None, 168.0, present=odd)
                self.assertEqual(kind, sp.TRACE_UNMEASURED)

    def test_without_a_declared_slo_there_is_no_threshold_at_all(self):
        """Порога нет ⇒ НЕ ИЗМЕРЕНО, а не свой порог.

        Выдуманная граница свежести была бы ВТОРЫМ правилом рядом с
        конституцией — тем самым «третьим местом для чисел».
        """
        kind, why = sp.write_trace(4.0, None, None, present=True)
        self.assertEqual(kind, sp.TRACE_UNMEASURED)
        self.assertIn("порога у вопроса нет", why)
        # Ноль и отрицательный срок — РАЗНЫЕ входы и оба не порог; простыми
        # утверждениями, а не только под `subTest` (см. соседний тест: прибор
        # дельты `SUBFAILED` не видит, и носитель обязан быть ему виден).
        self.assertEqual(sp.write_trace(4.0, None, 0, present=True)[0],
                         sp.TRACE_UNMEASURED)
        self.assertEqual(sp.write_trace(4.0, None, -5, present=True)[0],
                         sp.TRACE_UNMEASURED)
        self.assertEqual(sp.write_trace(4.0, None, True, present=True)[0],
                         sp.TRACE_UNMEASURED)
        for bad in ("168", [], {}, float("nan") * 0 if False else "0"):
            with self.subTest(slo=bad):
                kind, _ = sp.write_trace(4.0, None, bad, present=True)
                self.assertEqual(kind, sp.TRACE_UNMEASURED)

    def test_bool_is_not_a_number_anywhere_in_this_door(self):
        """`True` есть `int` в Python — и ни сроком, ни возрастом быть не вправе.

        Простым утверждением по той же причине, что и у двух соседей.
        """
        self.assertIsNone(sp._as_number(True))
        self.assertIsNone(sp._as_number(False))
        self.assertEqual(sp._as_number(5), 5.0)
        self.assertEqual(sp.write_trace(True, None, 168.0, present=True)[0],
                         sp.TRACE_UNMEASURED)
        self.assertEqual(sp.write_trace(4.0, None, True, present=True)[0],
                         sp.TRACE_UNMEASURED)

    def test_age_unmeasured_while_the_file_is_there(self):
        kind, why = sp.write_trace(None, None, 168.0, present=True)
        self.assertEqual(kind, sp.TRACE_UNMEASURED)
        self.assertIn("возраст записи НЕ ИЗМЕРЕН", why)

    def test_threshold_is_the_declared_slo_and_nothing_else(self):
        """ОДИН и тот же возраст по обе стороны СВОЕГО срока даёт РАЗНЫЙ вердикт.

        Это и есть проверка того, что порог взят у конституции: подставь дверь
        любую свою константу — одна из двух сцен перестанет отвечать.
        """
        fresh, _ = sp.write_trace(100.0, None, 168.0, present=True)
        stale, _ = sp.write_trace(100.0, None, 24.0, present=True)
        self.assertEqual(fresh, sp.TRACE_MISDECLARED)
        self.assertEqual(stale, sp.TRACE_UNMAINTAINED)

    def test_the_boundary_belongs_to_fresh(self):
        """Ровно на сроке — обещание ВЫПОЛНЕНО (как и у соседних дверей: `>=`)."""
        kind, _ = sp.write_trace(168.0, None, 168.0, present=True)
        self.assertEqual(kind, sp.TRACE_MISDECLARED)


class WriteStampProbe(unittest.TestCase):
    """Вторая проба: что считается ОТМЕТКОЙ ЗАПИСИ, а что предметной датой."""

    def test_iso_with_microseconds_and_offset_is_parsed(self):
        parsed = sk.parse_write_stamp("2026-08-29T02:17:22.193074+00:00")
        self.assertIsNotNone(parsed)

    def test_iso_with_z_is_parsed(self):
        self.assertIsNotNone(sk.parse_write_stamp("2026-10-26T07:00:32Z"))

    def test_epoch_number_is_parsed(self):
        """`data/basis_trade_opportunities.json` несёт `generated_at` ЧИСЛОМ."""
        self.assertIsNotNone(sk.parse_write_stamp(1787969783.8265972))

    def test_unparsable_stamp_is_absence_not_a_date(self):
        for bad in (None, "", "вчера", True, [], {}):
            with self.subTest(raw=bad):
                self.assertIsNone(sk.parse_write_stamp(bad))

    def test_domain_date_is_never_taken_for_a_write_stamp(self):
        """`as_of` ОТСТАЁТ от записи — замер: 66 суток в `data/dfb/pools.json`.

        Принять предметную дату за отметку записи значило бы объявить живой
        файл беспризорным по дате, которая про запись не говорит вовсе.
        """
        with tempfile.TemporaryDirectory() as tmp:
            art = _write(Path(tmp) / "a.json",
                         {"as_of": "2026-06-25", "as_of_utc": "2026-06-25T00:00:00Z"},
                         age_hours=2.0)
            obs = sk.write_trace_observation(art, now=NOW)
        self.assertIsNone(obs["stamp_key"])
        self.assertIn("предметные даты", obs["why"])
        self.assertAlmostEqual(obs["mtime_age_hours"], 2.0, places=3)

    def test_write_stamp_is_found_and_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = _write(Path(tmp) / "a.json",
                         {"generated_at": (NOW - timedelta(hours=3)).isoformat()},
                         age_hours=3.0)
            obs = sk.write_trace_observation(art, now=NOW)
        self.assertEqual(obs["stamp_key"], "generated_at")
        self.assertAlmostEqual(obs["stamp_age_hours"], 3.0, places=2)

    def test_missing_file_is_present_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs = sk.write_trace_observation(Path(tmp) / "нет.json", now=NOW)
        self.assertIs(obs["present"], False)

    def test_unreadable_directory_is_measured_as_nothing_at_all(self):
        """Каталога нет ⇒ ПРОБ НЕТ, а не «артефакт отсутствует».

        Иначе одна отсутствующая директория выдала бы НЕ ИЗМЕРЕНО за
        измеренный ответ целой переписью сразу — fail-OPEN тише красного.
        """
        obs = sk.write_trace_observation(Path("/нет/такого"), now=NOW,
                                         dir_readable=False)
        self.assertIsNone(obs["present"])
        self.assertIn("каталог данных НЕ ПРОЧИТАН", obs["why"])

    def test_non_json_artifact_still_yields_the_first_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = _write(Path(tmp) / "a.json", "не json вовсе", age_hours=5.0)
            obs = sk.write_trace_observation(art, now=NOW)
        self.assertIs(obs["present"], True)
        self.assertAlmostEqual(obs["mtime_age_hours"], 5.0, places=3)
        self.assertIsNone(obs["stamp_age_hours"])
        self.assertIn("не разобран как JSON", obs["why"])

    def test_artifact_path_honours_a_data_dir_outside_the_tree(self):
        """`data/x` берётся из ЖИВОГО каталога, а не из дерева замера (ADR-364)."""
        self.assertEqual(
            sk.artifact_file("data/x.json", Path("/tree"), Path("/live/data")),
            Path("/live/data/x.json"))
        self.assertEqual(
            sk.artifact_file("logs/y.log", Path("/tree"), Path("/live/data")),
            Path("/tree/logs/y.log"))


def _pair(agent, artifact, slo, *, axis=None):
    return {"agent": agent, "artifact": artifact, "slo_hours": slo,
            "intent": "retired",
            "declared_vs_floor": axis or sp.DECLARED_PRODUCER_NOT_RUNNING}


class RealityCensus(unittest.TestCase):
    """Перепись: население — пары из `not_running`, вердикт оси НЕ переписан."""

    def _scene(self, tmp):
        data = Path(tmp) / "data"
        _write(data / "живой.json",
               {"generated_at": (NOW - timedelta(hours=4)).isoformat()},
               age_hours=4.0)
        _write(data / "мёртвый.json",
               {"generated_at": (NOW - timedelta(hours=1400)).isoformat()},
               age_hours=1400.0)
        return data

    def test_the_one_живой_artifact_is_the_only_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._scene(tmp)
            declared = {"not_running": [
                _pair("com.spa.ушёл", "data/живой.json", 168.0),
                _pair("com.spa.ушёл2", "data/мёртвый.json", 168.0),
                _pair("com.spa.ушёл3", "data/нет-такого.json", 168.0)]}
            sec = sk.producer_reality_census(declared, [], Path(tmp), data, now=NOW)
        self.assertEqual(sec["status"], "OK")
        self.assertEqual(sec["population"], 3)
        self.assertEqual([r["artifact"] for r in sec["findings"]], ["data/живой.json"])
        self.assertEqual(len(sec["unmaintained"]), 2)
        self.assertEqual(sec["tally"][sp.TRACE_ABSENT], 1)

    def test_an_active_co_producer_withdraws_the_finding(self):
        """Файл пишет ОБЪЯВЛЕННЫЙ живой агент ⇒ «объявлен не тот» НЕ следует.

        Население случая ИЗМЕРЕНО циклом #942 и равно нулю; ветка написана
        против ПЕРВОГО такого артефакта, а не про запас — без неё он родил бы
        ложную находку молча.
        """
        with tempfile.TemporaryDirectory() as tmp:
            data = self._scene(tmp)
            agents = [{"label": "com.spa.живой", "intent": "active",
                       "produces": [{"artifact": "data/живой.json",
                                     "slo_hours": 24.0}]}]
            declared = {"not_running": [_pair("com.spa.ушёл", "data/живой.json", 168.0)]}
            sec = sk.producer_reality_census(declared, agents, Path(tmp), data, now=NOW)
        self.assertEqual(sec["findings"], [])
        self.assertEqual(sec["tally"], {sk.TRACE_ACTIVE_PRODUCER: 1})

    def test_unreadable_data_dir_yields_no_findings_and_no_absences(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на fail-OPEN: каталога нет ⇒ всё НЕ ИЗМЕРЕНО."""
        declared = {"not_running": [
            _pair("com.spa.ушёл", "data/живой.json", 168.0),
            _pair("com.spa.ушёл2", "data/мёртвый.json", 168.0)]}
        sec = sk.producer_reality_census(
            declared, [], Path("/нет/дерева"), Path("/нет/дерева/data"), now=NOW)
        self.assertEqual(sec["findings"], [])
        self.assertEqual(sec["unmaintained"], [])
        self.assertEqual(sec["tally"], {sp.TRACE_UNMEASURED: 2})
        self.assertIs(sec["data_dir_readable"], False)

    def test_unread_intent_label_is_not_judged_about_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._scene(tmp)
            declared = {"not_running": [_pair(
                "com.spa.?", "data/живой.json", 168.0,
                axis=sp.DECLARED_PRODUCER_STANDING_UNMEASURED)]}
            sec = sk.producer_reality_census(declared, [], Path(tmp), data, now=NOW)
        self.assertEqual(sec["findings"], [])
        self.assertEqual(sec["tally"], {sp.TRACE_UNMEASURED: 1})

    def test_missing_not_running_list_is_unmeasured_not_empty(self):
        sec = sk.producer_reality_census({}, [], REPO, REPO / "data", now=NOW)
        self.assertEqual(sec["status"], sp.TRACE_UNMEASURED)
        self.assertIsNone(sec["population"])
        self.assertIn("not_running", sec["cause"])

    def test_pairs_and_artifacts_are_counted_separately(self):
        """Два отставных производителя ОДНОГО файла — две пары, один артефакт."""
        with tempfile.TemporaryDirectory() as tmp:
            data = self._scene(tmp)
            declared = {"not_running": [
                _pair("com.spa.а", "data/живой.json", 168.0),
                _pair("com.spa.б", "data/живой.json", 24.0)]}
            sec = sk.producer_reality_census(declared, [], Path(tmp), data, now=NOW)
        self.assertEqual((sec["population"], sec["artifacts"]), (2, 1))

    def test_each_pair_is_judged_by_its_own_declared_slo(self):
        """Порог берётся у ПАРЫ: один и тот же файл, два срока, два вердикта."""
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            _write(data / "x.json", {}, age_hours=100.0)
            declared = {"not_running": [
                _pair("com.spa.а", "data/x.json", 168.0),
                _pair("com.spa.б", "data/x.json", 24.0)]}
            sec = sk.producer_reality_census(declared, [], Path(tmp), data, now=NOW)
        kinds = {r["agent"]: r["write_trace"] for r in sec["rows"]}
        self.assertEqual(kinds["com.spa.а"], sp.TRACE_MISDECLARED)
        self.assertEqual(kinds["com.spa.б"], sp.TRACE_UNMAINTAINED)


class ReaderExists(unittest.TestCase):
    """У записки обязан быть ЧИТАТЕЛЬ — третий цикл подряд этот класс."""

    def test_the_bridge_prints_the_line_through_the_named_door(self):
        """Меряется AST, а не подстрокой: имя в комментарии читателем не является."""
        tree = ast.parse((REPO / "spa_core" / "monitoring" / "findings_bridge.py").read_text())
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "producer_reality_line"
                 and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == "slo_keepability"]
        self.assertEqual(len(calls), 1, "строку шага 0-офис никто не печатает")

    def test_measure_wires_the_section_into_the_document(self):
        tree = ast.parse((REPO / "spa_core" / "monitoring" / "slo_keepability.py").read_text())
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "producer_reality_census"]
        self.assertEqual(len(calls), 1, "перепись не вызвана из `measure`")


class OfficeLine(unittest.TestCase):
    """Строка 0-офиса: прибор старой версии и прибор без находок РАЗЛИЧИМЫ."""

    def test_no_section_says_so(self):
        self.assertIn("НЕ ИЗМЕРЕНО", sk.producer_reality_line({}))

    def test_not_ok_status_names_the_cause(self):
        line = sk.producer_reality_line({"declared_producer_reality": {
            "status": sp.TRACE_UNMEASURED, "cause": "перечня нет"}})
        self.assertIn("перечня нет", line)

    def test_the_finding_is_named_not_merely_counted(self):
        line = sk.producer_reality_line({"declared_producer_reality": {
            "status": "OK", "population": 9, "artifacts": 9, "tally": {},
            "findings": [{"artifact": "data/g.json", "agent": "com.spa.g"}],
            "unmaintained": [{}] * 8}})
        self.assertIn("data/g.json", line)
        self.assertIn("com.spa.g", line)
        self.assertIn("ОБЪЯВЛЕН НЕ ТОТ ПРОИЗВОДИТЕЛЬ 1", line)
        self.assertIn("никто не пишет 8", line)

    def test_absent_counts_are_said_not_zeroed(self):
        line = sk.producer_reality_line({"declared_producer_reality": {
            "status": "OK", "population": None, "artifacts": None,
            "tally": {}, "findings": None, "unmaintained": None}})
        self.assertEqual(line.count("НЕ ИЗМЕРЕНО"), 4)


class LiveConstitution(unittest.TestCase):
    """Замер на живой конституции — предмет заказа G818 п. 1."""

    def test_the_nine_pairs_are_still_the_population(self):
        man = json.loads((REPO / "architecture" / "manifest.json").read_text())
        declared = sk.declared_axis_census(man["agents"], {})
        self.assertEqual(len(declared["not_running"]), 9,
                         "население вопроса сдвинулось — перемерить заказ")

    def test_the_axis_verdict_is_not_rewritten_by_the_new_section(self):
        """Оси НЕ сведены (заказ G815 п. 2): вердикт пары остался прежним."""
        man = json.loads((REPO / "architecture" / "manifest.json").read_text())
        declared = sk.declared_axis_census(man["agents"], {})
        self.assertTrue(all(
            r["declared_vs_floor"] == sp.DECLARED_PRODUCER_NOT_RUNNING
            for r in declared["not_running"]))
        self.assertEqual(declared["tally"].get(sp.CURATED_ABOVE), 216)


if __name__ == "__main__":
    unittest.main()
