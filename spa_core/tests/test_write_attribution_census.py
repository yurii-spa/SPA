"""ADR-820 (заказ G819 п. 1): есть ли канал, приписывающий запись ЗАПУЩЕННОМУ.

Каждый тест — положительный контроль на ОДНО звено. ADR-819 закрыл вопрос «пишет
ли файл кто-то» и назвал остаток дословно: «след говорит КОГДА, а не КТО». Заказ
G819 п. 1 запретил искать прибор прежде, чем спрошено, СУЩЕСТВУЕТ ли канал
вообще, и велел замерить население артефактов, несущих имя производителя внутри.

Предмет набора — РАЗЛИЧЕНИЕ, на котором стои́т вся дверь: имя КОДА
(`generated_by`, `monitor`, `producer` — литерал пишущего модуля, печатается
одинаково, кто бы его ни позвал) против точки ВХОДА прогона (`invoked_by.entry`,
снимается у самого процесса). Первое на атрибуцию ПОХОЖЕ и ею не является —
ровно поэтому оно опаснее пустоты, и ровно это сломалось в ADR-819, где снимок
писал библиотечный зов из другого процесса.

Часов в этом наборе нет ни одной двери: перепись атрибуции про время не
спрашивает, и якорей-литералов здесь поэтому тоже нет.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import slo_keepability as sk
from spa_core.monitoring import slo_proposal as sp

REPO = Path(__file__).resolve().parents[2]


def _write(path: Path, doc) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc) if not isinstance(doc, str) else doc)
    return path


class AttributionDoor(unittest.TestCase):
    """Дверь :func:`slo_proposal.write_attribution` — пять исходов, каждый свой."""

    def test_entry_stamp_is_the_only_channel_that_names_the_launched(self):
        kind, why = sp.write_attribution("spa_core/monitoring/findings_bridge.py",
                                         [], present=True)
        self.assertEqual(kind, sp.ATTRIBUTION_ENTRY_NAMED)
        self.assertIn("точку входа прогона", why)

    def test_code_name_is_not_attribution_and_the_reason_is_named(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на дефект ADR-819.

        `generated_by` печатается ОДИНАКОВО, кто бы модуль ни позвал, поэтому
        библиотечный зов из чужого процесса она не отличает — именно так снимок
        `data/governance_proposals.json` писал не свой агент.
        """
        kind, why = sp.write_attribution(None, ["generated_by"], present=True)
        self.assertEqual(kind, sp.ATTRIBUTION_CODE_ONLY)
        self.assertNotEqual(kind, sp.ATTRIBUTION_ENTRY_NAMED)
        self.assertIn("литерал пишущего модуля", why)

    def test_entry_stamp_wins_over_a_code_name_standing_next_to_it(self):
        """Оба на месте ⇒ канал ЕСТЬ: имя кода его не отменяет."""
        kind, _ = sp.write_attribution("x.py", ["generated_by", "producer"],
                                       present=True)
        self.assertEqual(kind, sp.ATTRIBUTION_ENTRY_NAMED)

    def test_nothing_at_all_is_its_own_outcome(self):
        kind, why = sp.write_attribution(None, [], present=True)
        self.assertEqual(kind, sp.ATTRIBUTION_ABSENT)
        self.assertNotEqual(kind, sp.ATTRIBUTION_CODE_ONLY)
        self.assertIn("не существует", why)

    def test_absent_carrier_is_separated_from_absent_channel(self):
        """«Файла нет» ≠ «в файле ничего нет».

        Склеить их значило бы потерять единственный признак замера не в том
        дереве: гора «носителя нет» об этом говорит, гора «ничего нет» — нет.
        """
        kind, why = sp.write_attribution(None, None, present=False)
        self.assertEqual(kind, sp.ATTRIBUTION_CARRIER_ABSENT)
        self.assertNotEqual(kind, sp.ATTRIBUTION_ABSENT)
        self.assertIn("носителя", why)

    def test_presence_unmeasured_is_not_absence(self):
        kind, why = sp.write_attribution(None, [], present=None)
        self.assertEqual(kind, sp.ATTRIBUTION_UNMEASURED)
        self.assertNotEqual(kind, sp.ATTRIBUTION_CARRIER_ABSENT)
        self.assertIn("НЕ ИЗМЕРЕНО", why)

    def test_presence_is_judged_by_KIND_not_by_truthiness(self):
        """Носитель притязания ПРОСТОЙ намеренно (ADR-819, прогон мутаций #943).

        `pytest-subtests` печатает `SUBFAILED`, а прибор дельты собирает имена
        по `^(?:FAILED|ERROR)` — утверждение, живущее ТОЛЬКО под `subTest`,
        мутации не видно, и прибор зовёт это «дырой покрытия». Перечень под
        `subTest` оставлен расширением, а не носителем.
        """
        self.assertEqual(sp.write_attribution(None, [], present=1)[0],
                         sp.ATTRIBUTION_UNMEASURED)
        self.assertEqual(sp.write_attribution(None, [], present="да")[0],
                         sp.ATTRIBUTION_UNMEASURED)
        for odd in (0, [], {}, 1.0, "нет"):
            with self.subTest(present=odd):
                self.assertEqual(sp.write_attribution(None, [], present=odd)[0],
                                 sp.ATTRIBUTION_UNMEASURED)

    def test_an_unreadable_entry_stamp_is_unmeasured_not_absent(self):
        """Отметка есть, но не разобрана ⇒ НЕ ИЗМЕРЕНО.

        Подстановка «канала нет» здесь была бы ответом за писавшего.
        """
        kind, why = sp.write_attribution("", ["generated_by"], present=True)
        self.assertEqual(kind, sp.ATTRIBUTION_UNMEASURED)
        self.assertNotEqual(kind, sp.ATTRIBUTION_CODE_ONLY)
        self.assertIn("не прочитана", why)
        self.assertEqual(sp.write_attribution("   ", [], present=True)[0],
                         sp.ATTRIBUTION_UNMEASURED)
        self.assertEqual(sp.write_attribution(42, [], present=True)[0],
                         sp.ATTRIBUTION_UNMEASURED)

    def test_unlisted_stamps_are_unmeasured_not_an_empty_channel(self):
        kind, why = sp.write_attribution(None, None, present=True)
        self.assertEqual(kind, sp.ATTRIBUTION_UNMEASURED)
        self.assertIn("НЕ ИЗМЕРЕН", why)
        self.assertEqual(sp.write_attribution(None, "generated_by", present=True)[0],
                         sp.ATTRIBUTION_UNMEASURED)
        self.assertEqual(sp.write_attribution(None, 7, present=True)[0],
                         sp.ATTRIBUTION_UNMEASURED)

    def test_every_outcome_has_its_own_name(self):
        names = {sp.ATTRIBUTION_ENTRY_NAMED, sp.ATTRIBUTION_CODE_ONLY,
                 sp.ATTRIBUTION_ABSENT, sp.ATTRIBUTION_CARRIER_ABSENT,
                 sp.ATTRIBUTION_UNMEASURED}
        self.assertEqual(len(names), 5)


class AttributionObservation(unittest.TestCase):
    """Проба одного артефакта: что он несёт и почему, если ничего."""

    def test_entry_is_read_from_the_nested_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = _write(Path(tmp) / "a.json",
                         {"invoked_by": {"schema": "call_provenance.v1",
                                         "entry": "spa_core/x.py"}})
            obs = sk.write_attribution_observation(art)
        self.assertEqual(obs["entry"], "spa_core/x.py")
        self.assertEqual(obs["code_keys"], [])
        self.assertEqual(obs["why"], "")

    def test_code_keys_are_listed_in_the_declared_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = _write(Path(tmp) / "a.json",
                         {"source": "cycle_runner", "generated_by": "x.py"})
            obs = sk.write_attribution_observation(art)
        self.assertEqual(obs["code_keys"], ["generated_by", "source"])
        self.assertIsNone(obs["entry"])

    def test_a_stamp_without_the_entry_field_names_that_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = _write(Path(tmp) / "a.json", {"invoked_by": {"measured": True}})
            obs = sk.write_attribution_observation(art)
        self.assertIsNone(obs["entry"])
        self.assertIn("поля `entry` в ней нет", obs["why"])

    def test_a_stamp_of_the_wrong_shape_is_handed_to_the_door_as_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = _write(Path(tmp) / "a.json", {"invoked_by": "findings_bridge"})
            obs = sk.write_attribution_observation(art)
            kind, _ = sp.write_attribution(obs["entry"], obs["code_keys"],
                                           present=obs["present"])
        self.assertIn("не объект", obs["why"])
        self.assertEqual(kind, sp.ATTRIBUTION_UNMEASURED)

    def test_missing_file_is_present_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs = sk.write_attribution_observation(Path(tmp) / "нет.json")
        self.assertIs(obs["present"], False)
        self.assertIsNone(obs["code_keys"])

    def test_non_json_artifact_is_present_but_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = _write(Path(tmp) / "a.json", "не json вовсе")
            obs = sk.write_attribution_observation(art)
            kind, _ = sp.write_attribution(obs["entry"], obs["code_keys"],
                                           present=obs["present"])
        self.assertIs(obs["present"], True)
        self.assertIn("не разобран как JSON", obs["why"])
        self.assertEqual(kind, sp.ATTRIBUTION_UNMEASURED)

    def test_root_that_is_not_an_object_has_no_top_level_stamp_at_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = _write(Path(tmp) / "a.json", [1, 2, 3])
            obs = sk.write_attribution_observation(art)
        self.assertIn("не объект", obs["why"])
        self.assertIsNone(obs["code_keys"])

    def test_unreadable_directory_is_measured_as_nothing_at_all(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на fail-OPEN: каталога нет ⇒ проб нет."""
        obs = sk.write_attribution_observation(Path("/нет/такого/a.json"),
                                               dir_readable=False)
        self.assertIsNone(obs["present"])
        self.assertIn("каталог данных НЕ ПРОЧИТАН", obs["why"])


def _agent(label, artifacts, intent="active"):
    return {"label": label, "intent": intent,
            "produces": [{"artifact": a, "slo_hours": 24.0} for a in artifacts]}


class AttributionCensus(unittest.TestCase):
    """Перепись: население — там, где у вопроса «кто записал» ЕСТЬ предмет."""

    OK_REALITY = {"status": "OK", "findings": []}

    def _scene(self, tmp):
        data = Path(tmp) / "data"
        _write(data / "двое.json", {"generated_by": "spa_core/x.py"})
        _write(data / "двое-пусто.json", {"status": "OK"})
        _write(data / "один.json", {"invoked_by": {"entry": "spa_core/y.py"}})
        return data

    def test_co_produced_artifacts_are_the_population(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._scene(tmp)
            agents = [_agent("com.spa.а", ["data/двое.json", "data/двое-пусто.json"]),
                      _agent("com.spa.б", ["data/двое.json", "data/двое-пусто.json"]),
                      _agent("com.spa.в", ["data/один.json"])]
            sec = sk.write_attribution_census(self.OK_REALITY, agents, Path(tmp), data)
        self.assertEqual(sec["status"], "OK")
        self.assertEqual(sec["population"], 2)
        self.assertEqual(sec["population_homes"]["co_produced"], 2)
        self.assertEqual(sorted(r["artifact"] for r in sec["rows"]),
                         ["data/двое-пусто.json", "data/двое.json"])

    def test_the_single_producer_artifact_is_counted_but_not_asked(self):
        """ИНВЕНТАРЬ и НАСЕЛЕНИЕ ВОПРОСА — разные числа, и это ответ заказа.

        Артефакт с точкой входа и ОДНИМ производителем поднимает инвентарь и НЕ
        поднимает население: канал, существующий в системе, вопроса не решает,
        если у населения вопроса его нет.
        """
        with tempfile.TemporaryDirectory() as tmp:
            data = self._scene(tmp)
            agents = [_agent("com.spa.а", ["data/двое.json"]),
                      _agent("com.spa.б", ["data/двое.json"]),
                      _agent("com.spa.в", ["data/один.json"])]
            sec = sk.write_attribution_census(self.OK_REALITY, agents, Path(tmp), data)
        self.assertEqual(sec["inventory_population"], 2)
        self.assertEqual(sec["inventory"][sp.ATTRIBUTION_ENTRY_NAMED], 1)
        self.assertEqual(sec["population"], 1)
        self.assertEqual(sec["tally"].get(sp.ATTRIBUTION_ENTRY_NAMED), None)

    def test_a_code_name_at_a_co_produced_artifact_is_the_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._scene(tmp)
            agents = [_agent("com.spa.а", ["data/двое.json", "data/двое-пусто.json"]),
                      _agent("com.spa.б", ["data/двое.json", "data/двое-пусто.json"])]
            sec = sk.write_attribution_census(self.OK_REALITY, agents, Path(tmp), data)
        self.assertEqual([r["artifact"] for r in sec["findings"]], ["data/двое.json"])
        self.assertEqual(sec["tally"][sp.ATTRIBUTION_ABSENT], 1)

    def test_an_entry_stamp_at_a_co_produced_artifact_is_not_a_finding(self):
        """Контроль в ОБРАТНУЮ сторону: канал на месте ⇒ находки нет."""
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            _write(data / "x.json", {"invoked_by": {"entry": "spa_core/y.py"},
                                     "generated_by": "spa_core/y.py"})
            agents = [_agent("com.spa.а", ["data/x.json"]),
                      _agent("com.spa.б", ["data/x.json"])]
            sec = sk.write_attribution_census(self.OK_REALITY, agents, Path(tmp), data)
        self.assertEqual(sec["findings"], [])
        self.assertEqual(sec["tally"], {sp.ATTRIBUTION_ENTRY_NAMED: 1})

    def test_the_second_home_comes_from_the_ADR_819_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._scene(tmp)
            reality = {"status": "OK", "findings": [
                {"artifact": "data/один.json", "agent": "com.spa.ушёл"}]}
            agents = [_agent("com.spa.в", ["data/один.json"])]
            sec = sk.write_attribution_census(reality, agents, Path(tmp), data)
        self.assertEqual(sec["population"], 1)
        self.assertEqual(sec["population_homes"],
                         {"co_produced": 0, "misdeclared": 1})
        self.assertEqual(sec["rows"][0]["home"], "misdeclared")

    def test_an_artifact_in_both_homes_is_counted_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._scene(tmp)
            reality = {"status": "OK", "findings": [
                {"artifact": "data/двое.json", "agent": "com.spa.ушёл"}]}
            agents = [_agent("com.spa.а", ["data/двое.json"]),
                      _agent("com.spa.б", ["data/двое.json"])]
            sec = sk.write_attribution_census(reality, agents, Path(tmp), data)
        self.assertEqual(sec["population"], 1)
        self.assertEqual(sec["population_homes"],
                         {"co_produced": 1, "misdeclared": 0})

    def test_an_unmeasured_fourth_section_leaves_the_home_unmeasured_not_zero(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на инв. #17 у ВХОДА переписи.

        Ноль здесь означал бы «находок ADR-819 нет», то есть ответ на вопрос,
        которого никто не задавал.
        """
        with tempfile.TemporaryDirectory() as tmp:
            data = self._scene(tmp)
            agents = [_agent("com.spa.а", ["data/двое.json"]),
                      _agent("com.spa.б", ["data/двое.json"])]
            sec = sk.write_attribution_census(
                {"status": sp.TRACE_UNMEASURED, "cause": "перечня нет"},
                agents, Path(tmp), data)
        self.assertIsNone(sec["population_homes"]["misdeclared"])
        self.assertIn("перечня нет", sec["population_cause"])
        self.assertEqual(sec["population_homes"]["co_produced"], 1)

    def test_a_fourth_section_without_a_findings_list_is_also_unmeasured(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = self._scene(tmp)
            sec = sk.write_attribution_census(
                {"status": "OK"}, [_agent("com.spa.в", ["data/один.json"])],
                Path(tmp), data)
        self.assertIsNone(sec["population_homes"]["misdeclared"])
        self.assertIn("перечня находок", sec["population_cause"])

    def test_unreadable_data_dir_yields_no_absences_and_no_findings(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на fail-OPEN целой переписью сразу."""
        agents = [_agent("com.spa.а", ["data/x.json"]),
                  _agent("com.spa.б", ["data/x.json"])]
        sec = sk.write_attribution_census(
            self.OK_REALITY, agents, Path("/нет/дерева"), Path("/нет/дерева/data"))
        self.assertEqual(sec["findings"], [])
        self.assertEqual(sec["tally"], {sp.ATTRIBUTION_UNMEASURED: 1})
        self.assertIs(sec["data_dir_readable"], False)
        self.assertNotIn(sp.ATTRIBUTION_CARRIER_ABSENT, sec["tally"])

    def test_an_empty_constitution_is_unmeasured_not_an_empty_population(self):
        sec = sk.write_attribution_census(self.OK_REALITY, [], REPO, REPO / "data")
        self.assertEqual(sec["status"], sp.ATTRIBUTION_UNMEASURED)
        self.assertIsNone(sec["population"])
        self.assertIsNone(sec["inventory"])
        self.assertIn("ни одного объявленного артефакта", sec["cause"])

    def test_a_missing_artifact_at_a_co_produced_pair_is_carrier_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir(parents=True)
            agents = [_agent("com.spa.а", ["data/нет.json"]),
                      _agent("com.spa.б", ["data/нет.json"])]
            sec = sk.write_attribution_census(self.OK_REALITY, agents, Path(tmp), data)
        self.assertEqual(sec["tally"], {sp.ATTRIBUTION_CARRIER_ABSENT: 1})
        self.assertEqual(sec["findings"], [])

    def test_one_artifact_is_observed_once_for_both_numbers(self):
        """Инвентарь и население читают ОДНУ пробу — иначе два ответа на один вопрос."""
        with tempfile.TemporaryDirectory() as tmp:
            data = self._scene(tmp)
            agents = [_agent("com.spa.а", ["data/двое.json"]),
                      _agent("com.spa.б", ["data/двое.json"])]
            sec = sk.write_attribution_census(self.OK_REALITY, agents, Path(tmp), data)
        self.assertEqual(sec["inventory"][sp.ATTRIBUTION_CODE_ONLY], 1)
        self.assertEqual(sec["tally"][sp.ATTRIBUTION_CODE_ONLY], 1)


class ReaderExists(unittest.TestCase):
    """У записки обязан быть ЧИТАТЕЛЬ — и читатель здесь ДРУГОЙ (ADR-820)."""

    def test_the_office_renderer_prints_the_line_through_the_named_door(self):
        """Меряется AST: `report()` — вывод, который цикл читает НА САМОМ ДЕЛЕ.

        Замер 26.10: четыре строки ADR-816…819 объявлены «строкой шага 0-офис»,
        а зовёт их только `findings_bridge`, чей stdout уходит в лог агента.
        """
        tree = ast.parse((REPO / "spa_core" / "monitoring"
                          / "slo_keepability.py").read_text())
        report = [n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "report"]
        self.assertEqual(len(report), 1)
        calls = [n for n in ast.walk(report[0])
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "write_attribution_line"]
        self.assertEqual(len(calls), 1, "строку 0-офиса не печатает никто")

    def test_measure_wires_the_section_into_the_document(self):
        tree = ast.parse((REPO / "spa_core" / "monitoring"
                          / "slo_keepability.py").read_text())
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "write_attribution_census"]
        self.assertEqual(len(calls), 1, "перепись не вызвана из `measure`")

    def test_the_document_carries_the_section_under_its_declared_name(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ, найденный своим же прибором мутаций.

        Прогон 26.10: мутация «секция попадает в документ под ДРУГИМ именем»
        ВЫЖИЛА — перепись считалась, строка 0-офиса честно печатала «НЕ
        ИЗМЕРЕНО: секции нет», и ни один тест не падал. Зов переписи (AST выше)
        и ПРИСУТСТВИЕ её в документе — разные утверждения, и первое второго не
        доказывает.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            (tree / "scripts").mkdir()
            _write(tree / "architecture" / "manifest.json",
                   {"agents": [_agent("com.spa.а", ["data/x.json"]),
                               _agent("com.spa.б", ["data/x.json"])]})
            _write(tree / "data" / "x.json", {"generated_by": "spa_core/y.py"})
            doc = sk.measure(tree / "architecture" / "manifest.json", root=tree,
                             data_dir=tree / "data", scripts_dir=tree / "scripts")
        self.assertIn("declared_write_attribution", doc)
        section = doc["declared_write_attribution"]
        self.assertEqual(section["status"], "OK")
        self.assertEqual(section["population"], 1)
        # Строка 0-офиса несёт «НЕ ИЗМЕРЕНО» и как МЕТКУ ведра (их счёт 0), и
        # как отказ целой секции — различает их ПРИЧИНА, а не слово.
        line = sk.write_attribution_line(doc)
        self.assertNotIn("в замере нет", line)
        self.assertIn("население 1", line)

    def test_the_fourth_section_is_measured_exactly_once(self):
        """Второй прогон ЧЕТВЁРТОЙ переписи дал бы два ответа на один вопрос."""
        tree = ast.parse((REPO / "spa_core" / "monitoring"
                          / "slo_keepability.py").read_text())
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "producer_reality_census"]
        self.assertEqual(len(calls), 1)


class OfficeLine(unittest.TestCase):
    """Строка 0-офиса: прибор старой версии и прибор без находок РАЗЛИЧИМЫ."""

    def test_no_section_says_so(self):
        self.assertIn("НЕ ИЗМЕРЕНО", sk.write_attribution_line({}))
        self.assertIn("ДО ADR-820", sk.write_attribution_line({}))

    def test_not_ok_status_names_the_cause(self):
        line = sk.write_attribution_line({"declared_write_attribution": {
            "status": sp.ATTRIBUTION_UNMEASURED, "cause": "населения нет"}})
        self.assertIn("населения нет", line)

    def test_the_finding_is_named_not_merely_counted(self):
        line = sk.write_attribution_line({"declared_write_attribution": {
            "status": "OK", "population": 9, "inventory_population": 231,
            "population_homes": {"co_produced": 8, "misdeclared": 1},
            "tally": {sp.ATTRIBUTION_CODE_ONLY: 3, sp.ATTRIBUTION_ABSENT: 5},
            "inventory": {sp.ATTRIBUTION_ENTRY_NAMED: 14},
            "findings": [{"artifact": "data/system_health.json",
                          "code_keys": ["generated_by"]}]}})
        self.assertIn("data/system_health.json", line)
        self.assertIn("generated_by", line)
        self.assertIn("точку входа прогона несут 0", line)
        self.assertIn("имя КОДА вместо атрибуции 3", line)
        self.assertIn("231", line)

    def test_an_unmeasured_home_is_said_not_zeroed(self):
        line = sk.write_attribution_line({"declared_write_attribution": {
            "status": "OK", "population": 8, "inventory_population": 231,
            "population_homes": {"co_produced": 8, "misdeclared": None},
            "tally": {}, "inventory": {}, "findings": []}})
        self.assertIn("с находкой ADR-819 НЕ ИЗМЕРЕНО", line)


class LiveConstitution(unittest.TestCase):
    """Замер на живой конституции — предмет заказа G819 п. 1.

    Про `data/` здесь НЕ спрашивается ни одной строкой: живой каталог в git не
    живёт, и на чистом клоне ответ про него получился бы ПО ПОСТРОЕНИЮ. Замер
    артефактов назван в ADR-820 числами и воспроизводится прибором с
    `--data-dir` прод-дерева.
    """

    def test_the_co_produced_population_is_eight(self):
        man = json.loads((REPO / "architecture" / "manifest.json").read_text())
        produced: dict = {}
        for agent in man["agents"]:
            for pr in (agent.get("produces") or []):
                if isinstance(pr, dict) and pr.get("artifact"):
                    produced.setdefault(pr["artifact"], set()).add(agent["label"])
        multi = {a for a, labels in produced.items() if len(labels) >= 2}
        self.assertEqual(len(multi), 8,
                         "население вопроса сдвинулось — перемерить заказ")
        self.assertEqual(len(produced), 231)

    def test_every_co_producer_pair_has_distinct_wrappers(self):
        """Почему канал к ЗАПУЩЕННОМУ здесь применим в принципе.

        У всех восьми пар обёртки РАЗНЫЕ — значит отметка точки входа их
        различила бы. Отсутствие канала поэтому не свойство мира, а свойство
        писателей: имя КОДА у них одно и то же по построению.
        """
        man = json.loads((REPO / "architecture" / "manifest.json").read_text())
        by_label = {a["label"]: a for a in man["agents"]}
        produced: dict = {}
        for agent in man["agents"]:
            for pr in (agent.get("produces") or []):
                if isinstance(pr, dict) and pr.get("artifact"):
                    produced.setdefault(pr["artifact"], set()).add(agent["label"])
        for artifact, labels in produced.items():
            if len(labels) < 2:
                continue
            programs = {by_label[l].get("program") for l in labels}
            self.assertEqual(len(programs), len(labels),
                             f"{artifact}: обёртки производителей совпали")


if __name__ == "__main__":
    unittest.main()
