"""Батарея переписи «у находки нет читателя внутри цикла» (ADR-526, заказ G86 п. 4).

Каждый тест — либо положительный контроль РЕАЛЬНОЙ формы (авария ADR-475 и состояние
кустодиана на 25.09 / на 30.09), либо контроль в обратную сторону с поимённо порванным
звеном. Часов в приборе нет: время приходит входом ``now=``, поэтому литеральных дат в
батарее нет вовсе, а отметки сцены вычисляются от якоря.

Проверяется и то, чего перепись НЕ вправе утверждать: порядок ног (писатель раньше
читателя) и односторонность оси формы.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import unittest

from spa_core.monitoring import finding_reader_census as frc

# Якорь сцены. Всё время в тестах отсчитывается от него и уходит в `measure(now=…)`.
# FROZEN-DATE-OK: injected-clock — прибор принимает часы входом `measure(..., now=NOW)`,
# отметки времени артефактов сцены выставляются `os.utime` от того же якоря, и стенных
# часов в батарее нет ни одних.
# Якорь намеренно УВЕДЁН от стенных часов на месяцы: совпадение якоря с сегодняшним днём
# делало бы батарею зелёной и тогда, когда прибор часы НЕ принимает (мутация `now or …` →
# `now and …` выжила ровно поэтому). Расстояние до стенных часов и есть контроль проводки.
NOW = dt.datetime(2026, 3, 15, 12, 0, tzinfo=dt.timezone.utc)

REPO = pathlib.Path(__file__).resolve().parents[2]


def _agent(label, artifact, *, intent="active", slo=13, consumes=()):
    return {
        "label": label,
        "intent": intent,
        "produces": [{"artifact": artifact, "slo_hours": slo}],
        "consumes": list(consumes),
    }


class _Scene:
    """Одноразовое дерево: конституция + `data/` + исходники."""

    def __init__(self, tmp):
        self.root = pathlib.Path(tmp)
        (self.root / "architecture").mkdir(parents=True, exist_ok=True)
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        (self.root / "spa_core").mkdir(parents=True, exist_ok=True)
        (self.root / "scripts").mkdir(parents=True, exist_ok=True)
        # Нейтральный модуль в сцене ОБЯЗАТЕЛЕН: пустое дерево исходников — это
        # честное «не измерено» (о читателе в коде спросить нечем), и сцена без
        # него отвечала бы на другой вопрос. Отдельный контроль на сам этот
        # третий исход — `ThirdOutcomesAreLoud`.
        (self.root / "spa_core" / "_unrelated.py").write_text(
            "VALUE = 1\n", encoding="utf-8")

    def manifest(self, agents=(), artifacts=()):
        (self.root / "architecture" / "manifest.json").write_text(
            json.dumps({"agents": list(agents), "artifacts": list(artifacts)},
                       ensure_ascii=False), encoding="utf-8")
        return self

    def artifact(self, rel, doc, *, age_hours=1.0):
        full = self.root / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        ts = (NOW - dt.timedelta(hours=age_hours)).timestamp()
        os.utime(full, (ts, ts))
        return self

    def module(self, rel, source):
        full = self.root / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(source, encoding="utf-8")
        return self

    def wrapper(self, program, target):
        """Обёртка агента в ФОРМЕ живого дерева: режим B, цель — второй аргумент.

        Форма взята с `scripts/agent_intraday_equity.sh` дословно; разбор её делает
        `entrypoint_import_probe.resolve_wrapper_target`, а не вторая копия правила.
        """
        full = self.root / "scripts" / program
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(
            "#!/bin/bash\n"
            f"exec /bin/bash {self.root}/scripts/agent_template.sh lbl {target} --run\n",
            encoding="utf-8")
        return self

    def measure(self):
        return frc.measure(self.root, data_dir=str(self.root / "data"), now=NOW)


def _row(doc, artifact):
    return next(r for r in doc["rows"] if r["artifact"] == artifact)


class TheClaimsOfTheInstrumentItself(unittest.TestCase):
    """То, что прибор УТВЕРЖДАЕТ о себе, обязано быть закреплено, а не подразумеваться."""

    def test_the_advisory_claim_is_pinned(self):
        self.assertIs(frc.APPLIED, False)
        self.assertEqual(frc.ORDER, "G86.4")

    def test_the_verdict_names_are_pinned_to_literals_not_to_the_modules_own_tuple(self):
        """Сверять перечень с ним же самим — зелено ПО ПОСТРОЕНИЮ (урок цикла #722)."""
        self.assertEqual(frc.VERDICTS, (
            "writer_retired",
            "writer_not_loaded",
            "writer_silent",
            "read_by_the_cycle",
            "read_by_another_declared_consumer",
            "read_by_another_agent",
            "read_in_code_by_another_module",
            "no_reader_found",
            "unmeasured",
        ))
        self.assertEqual(frc.SHAPES, ("finding_key_present",
                                      "finding_key_absent_not_proof",
                                      "shape_unmeasured"))
        self.assertEqual(frc.CYCLE_CONSUMER, "orchestrator_protocol")


class TheClockIsAnInput(unittest.TestCase):
    """Часы приходят входом — и это проверяется СМЕНОЙ вердикта, а не наличием параметра."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.scene = _Scene(self._tmp.name)
        self.scene.manifest(agents=[_agent("com.spa.x", "data/x.json", slo=13)])
        self.scene.artifact("data/x.json", {"ok": True}, age_hours=5.0)

    def test_moving_the_injected_clock_forward_makes_the_writer_silent(self):
        near = frc.measure(self.scene.root, data_dir=str(self.scene.root / "data"),
                           now=NOW)
        far = frc.measure(self.scene.root, data_dir=str(self.scene.root / "data"),
                          now=NOW + dt.timedelta(hours=20))
        self.assertEqual(_row(near, "data/x.json")["verdict"], "no_reader_found")
        self.assertEqual(_row(far, "data/x.json")["verdict"], "writer_silent")

    def test_the_age_is_measured_against_the_injected_clock_to_two_decimals(self):
        self.scene.artifact("data/x.json", {"ok": True}, age_hours=2.345)
        doc = frc.measure(self.scene.root, data_dir=str(self.scene.root / "data"),
                          now=NOW)
        self.assertEqual(_row(doc, "data/x.json")["age_hours"], 2.35)


class TheOrderOfTheLegs(unittest.TestCase):
    """Писатель спрашивается ПЕРВЫМ — и это не косметика, а разные починки."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.scene = _Scene(self._tmp.name)

    def test_the_accident_of_adr_475_is_writer_not_loaded_not_a_missing_reader(self):
        """25.09: агент НЕ загружен, артефакта нет. Объявить читателя = вечный красный."""
        self.scene.manifest(
            agents=[_agent("com.spa.site_freshness",
                           "data/site_freshness_report.json", intent="designed")])
        doc = self.scene.measure()
        self.assertEqual(_row(doc, "data/site_freshness_report.json")["verdict"],
                         "writer_not_loaded")
        self.assertEqual(doc["verdicts"]["no_reader_found"], 0)

    def test_a_live_writer_with_no_reader_anywhere_is_the_finding(self):
        """30.09: агент пишет каждые 6 ч, читателя нет ни у кого — вред заказа."""
        self.scene.manifest(
            agents=[_agent("com.spa.site_freshness", "data/site_freshness_report.json")])
        self.scene.artifact("data/site_freshness_report.json",
                            {"ok": False, "fails": [{"code": "PUBLISHER_STUCK"}],
                             "n_fails": 1}, age_hours=5.3)
        doc = self.scene.measure()
        self.assertEqual(_row(doc, "data/site_freshness_report.json")["verdict"],
                         "no_reader_found")
        self.assertEqual(doc["verdicts"]["no_reader_found"], 1)

    def test_declaring_the_cycle_as_consumer_is_what_closes_the_finding(self):
        """Контроль ЗАКРЫТИЯ: ровно объявление потребителя меняет вердикт."""
        agents = [_agent("com.spa.site_freshness", "data/site_freshness_report.json")]
        self.scene.manifest(agents=agents, artifacts=[{
            "path": "data/site_freshness_report.json", "status": "active",
            "consumers": [frc.CYCLE_CONSUMER]}])
        self.scene.artifact("data/site_freshness_report.json",
                            {"ok": False, "fails": [], "n_fails": 0}, age_hours=5.3)
        doc = self.scene.measure()
        self.assertEqual(_row(doc, "data/site_freshness_report.json")["verdict"],
                         "read_by_the_cycle")
        self.assertEqual(doc["findings"], [])

    def test_an_active_agent_that_stopped_writing_is_writer_silent_not_a_missing_reader(self):
        """Третья починка третьим именем: агент объявлен живым, а артефакта нет."""
        self.scene.manifest(
            agents=[_agent("com.spa.self_heal", "data/self_heal_status.json")])
        doc = self.scene.measure()
        self.assertEqual(_row(doc, "data/self_heal_status.json")["verdict"],
                         "writer_silent")

    def test_a_retired_agent_is_its_own_outcome(self):
        self.scene.manifest(
            agents=[_agent("com.spa.gone", "data/gone.json", intent="retired")])
        self.assertEqual(_row(self.scene.measure(), "data/gone.json")["verdict"],
                         "writer_retired")

    def test_staleness_beyond_the_declared_slo_is_not_an_observed_writer(self):
        self.scene.manifest(
            agents=[_agent("com.spa.x", "data/x.json", slo=13)])
        self.scene.artifact("data/x.json", {"ok": True}, age_hours=14.0)
        row = _row(self.scene.measure(), "data/x.json")
        self.assertEqual(row["verdict"], "writer_silent")
        self.assertTrue(row["note"].startswith("stale:"), row)

    def test_without_a_declared_slo_presence_is_the_observation_and_it_is_said_aloud(self):
        """«Файл есть» слабее, чем «писатель жив» — и признак это называет."""
        self.scene.manifest(agents=[_agent("com.spa.x", "data/x.json", slo=None)])
        self.scene.artifact("data/x.json", {"ok": True}, age_hours=900.0)
        row = _row(self.scene.measure(), "data/x.json")
        self.assertTrue(row["writer_observed"])
        self.assertEqual(row["note"], "freshness_undeclared")


class WhoCountsAsAReader(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.scene = _Scene(self._tmp.name)
        self.scene.artifact("data/x.json", {"ok": True}, age_hours=1.0)

    def _agents(self, **kw):
        return [_agent("com.spa.x", "data/x.json", **kw)]

    def test_another_declared_consumer_is_named_declared_and_not_read(self):
        self.scene.manifest(agents=self._agents(), artifacts=[{
            "path": "data/x.json", "status": "active", "consumers": ["digest_daily"]}])
        row = _row(self.scene.measure(), "data/x.json")
        self.assertEqual(row["verdict"], "read_by_another_declared_consumer")
        self.assertEqual(row["declared_consumers"], ["digest_daily"])

    def test_a_retired_artifacts_row_does_not_count_as_a_declaration(self):
        """Строка `artifacts[]` не активна ⇒ она не объявляет потребителя вовсе."""
        self.scene.manifest(agents=self._agents(), artifacts=[{
            "path": "data/x.json", "status": "retired",
            "consumers": [frc.CYCLE_CONSUMER]}])
        self.assertEqual(_row(self.scene.measure(), "data/x.json")["verdict"],
                         "no_reader_found")

    def test_another_agent_consuming_the_path_is_a_declared_reader(self):
        agents = self._agents() + [
            {"label": "com.spa.y", "intent": "active", "produces": [],
             "consumes": ["data/x.json"]}]
        self.scene.manifest(agents=agents)
        self.assertEqual(_row(self.scene.measure(), "data/x.json")["verdict"],
                         "read_by_another_agent")

    def test_the_producer_consuming_its_own_output_is_not_a_reader(self):
        """Чтение своего вывода — вопрос ADR-524, а не этот. Иначе авария ADR-475
        оправдалась бы сама собой: кустодиан читает СВОЙ прошлый отчёт."""
        self.scene.manifest(agents=self._agents(consumes=["data/x.json"]))
        self.assertEqual(_row(self.scene.measure(), "data/x.json")["verdict"],
                         "no_reader_found")

    def test_a_module_that_reads_the_file_is_a_reader(self):
        self.scene.manifest(agents=self._agents())
        self.scene.module("spa_core/reader.py",
                          'import json\n'
                          'def go():\n'
                          '    return json.load(open("data/x.json"))\n')
        row = _row(self.scene.measure(), "data/x.json")
        self.assertEqual(row["verdict"], "read_in_code_by_another_module")
        self.assertEqual(row["code_readers"], ["spa_core/reader.py"])

    def test_a_module_that_reads_only_what_it_writes_is_not_a_reader(self):
        """Тот же модуль пишет и читает — это «предыдущий прогон», не читатель."""
        self.scene.manifest(agents=self._agents())
        self.scene.module("scripts/writer.py",
                          'import json\n'
                          'def go():\n'
                          '    prev = json.load(open("data/x.json"))\n'
                          '    json.dump(prev, open("data/x.json", "w"))\n')
        self.assertEqual(_row(self.scene.measure(), "data/x.json")["verdict"],
                         "no_reader_found")

    def test_a_test_file_is_a_fixture_and_not_a_reader_of_the_tree(self):
        self.scene.manifest(agents=self._agents())
        self.scene.module("spa_core/tests/test_thing.py",
                          'import json\n'
                          'def test_go():\n'
                          '    json.load(open("data/x.json"))\n')
        self.assertEqual(_row(self.scene.measure(), "data/x.json")["verdict"],
                         "no_reader_found")

    def test_a_test_module_outside_the_tests_directory_is_also_a_fixture(self):
        """Два признака фикстуры, и каждый достаточен сам по себе."""
        self.scene.manifest(agents=self._agents())
        self.scene.module("scripts/test_helper.py",
                          'import json\n'
                          'def test_go():\n'
                          '    json.load(open("data/x.json"))\n')
        self.assertEqual(_row(self.scene.measure(), "data/x.json")["verdict"],
                         "no_reader_found")

    def test_the_listed_readers_are_capped_and_the_cap_does_not_change_the_verdict(self):
        self.scene.manifest(agents=self._agents())
        for i in range(6):
            self.scene.module(f"spa_core/r{i}.py",
                              'import json\n'
                              f'def go{i}():\n'
                              '    return json.load(open("data/x.json"))\n')
        row = _row(self.scene.measure(), "data/x.json")
        self.assertEqual(row["verdict"], "read_in_code_by_another_module")
        self.assertEqual(len(row["code_readers"]), 4)


class TheShapeAxisIsOneSidedAndSaysSo(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.scene = _Scene(self._tmp.name)
        self.scene.manifest(agents=[_agent("com.spa.x", "data/x.json")])

    def test_a_declared_finding_key_is_proof(self):
        self.scene.artifact("data/x.json", {"ok": False, "fails": []})
        row = _row(self.scene.measure(), "data/x.json")
        self.assertEqual(row["shape"], "finding_key_present")
        self.assertEqual(row["shape_reason"], "fails")

    def test_an_empty_list_today_still_counts_as_carrying_findings(self):
        """Форма спрашивается у СХЕМЫ, а не у спокойного дня (инв. #17)."""
        self.scene.artifact("data/x.json", {"findings": []})
        self.assertEqual(_row(self.scene.measure(), "data/x.json")["shape"],
                         "finding_key_present")

    def test_a_miss_is_named_not_proof_and_never_clean(self):
        self.scene.artifact("data/x.json", {"по_агентам": {"com.spa.y": ["тревога"]}})
        self.assertEqual(_row(self.scene.measure(), "data/x.json")["shape"],
                         "finding_key_absent_not_proof")

    def test_the_key_match_is_exact_and_not_a_substring(self):
        """`failsafe` не есть `fails`: подстрока сделала бы ось шире, чем утверждение."""
        self.scene.artifact("data/x.json", {"failsafe": True, "no_errors_here": 1})
        self.assertEqual(_row(self.scene.measure(), "data/x.json")["shape"],
                         "finding_key_absent_not_proof")

    def test_a_jsonl_artifact_is_shape_unmeasured_and_not_judged_as_a_document(self):
        """`.jsonl` не документ: разбирать его как JSON значило бы выдумать ответ."""
        self.scene.manifest(agents=[_agent("com.spa.x", "data/x.jsonl")])
        (self.scene.root / "data" / "x.jsonl").write_text(
            '{"fails": []}\n', encoding="utf-8")
        ts = (NOW - dt.timedelta(hours=1)).timestamp()
        os.utime(self.scene.root / "data" / "x.jsonl", (ts, ts))
        row = _row(self.scene.measure(), "data/x.jsonl")
        self.assertEqual(row["shape"], "shape_unmeasured")
        self.assertEqual(row["shape_reason"], "not_a_json_artifact")

    def test_the_report_marks_only_the_rows_that_carry_findings(self):
        self.scene.manifest(agents=[_agent("com.spa.a", "data/a.json"),
                                    _agent("com.spa.b", "data/b.json")])
        self.scene.artifact("data/a.json", {"fails": []}, age_hours=1)
        self.scene.artifact("data/b.json", {"nav": 1}, age_hours=1)
        text = frc.format_report(self.scene.measure())
        self.assertIn("data/a.json (возраст 1.0ч, НЕСЁТ НАХОДКИ)", text)
        self.assertIn("data/b.json (возраст 1.0ч, finding_key_absent_not_proof)", text)

    def test_a_non_mapping_document_is_shape_unmeasured(self):
        (self.scene.root / "data" / "x.json").write_text("[1, 2]", encoding="utf-8")
        ts = (NOW - dt.timedelta(hours=1)).timestamp()
        os.utime(self.scene.root / "data" / "x.json", (ts, ts))
        self.assertEqual(_row(self.scene.measure(), "data/x.json")["shape"],
                         "shape_unmeasured")

    def test_the_report_names_the_measured_vocabulary_so_the_bound_is_a_number(self):
        self.scene.artifact("data/x.json", {"ok": True, "a": 1, "b": 2})
        text = frc.format_report(self.scene.measure())
        self.assertIn("ЗАКРЫТ", text)
        self.assertIn(str(len(frc.FINDING_KEYS)), text)
        self.assertIn("доказательством обратного НЕ является", text)


class ThirdOutcomesAreLoud(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.scene = _Scene(self._tmp.name)

    def test_an_unparsed_source_tree_is_unmeasured_not_a_missing_reader(self):
        """Спросить о читателе в коде нечем ⇒ третий исход, а не находка."""
        self.scene.manifest(agents=[_agent("com.spa.x", "data/x.json")])
        self.scene.artifact("data/x.json", {"ok": True}, age_hours=1)
        (self.scene.root / "spa_core" / "_unrelated.py").unlink()
        doc = self.scene.measure()
        self.assertEqual(_row(doc, "data/x.json")["verdict"],
                         "unmeasured:no_source_tree_parsed")
        self.assertEqual(frc.verdict(doc), 2)

    def test_a_missing_data_tree_is_unmeasured_and_not_clean(self):
        self.scene.manifest(agents=[_agent("com.spa.x", "data/x.json")])
        doc = frc.measure(self.scene.root, data_dir=str(self.scene.root / "nope"),
                          now=NOW)
        self.assertTrue(doc["unmeasured"].startswith("data_dir_absent:"))
        self.assertEqual(frc.verdict(doc), 2)
        self.assertIn("НЕ ИЗМЕРЕНО", frc.format_report(doc))

    def test_an_unreadable_manifest_is_unmeasured(self):
        (self.scene.root / "architecture" / "manifest.json").write_text(
            "{не json", encoding="utf-8")
        doc = frc.measure(self.scene.root, data_dir=str(self.scene.root / "data"),
                          now=NOW)
        self.assertTrue(doc["unmeasured"].startswith("manifest_unreadable:"))
        self.assertEqual(frc.verdict(doc), 2)

    def test_a_directory_artifact_is_unmeasured_with_a_named_reason(self):
        """Разбор читателей видит ИМЯ ФАЙЛА с расширением; каталога он не видит."""
        self.scene.manifest(agents=[_agent("com.spa.x", "data/statements", slo=None)])
        (self.scene.root / "data" / "statements").mkdir()
        self.scene.artifact("data/statements/2026-08.json", {"nav": 1}, age_hours=2)
        row = _row(self.scene.measure(), "data/statements")
        self.assertEqual(row["verdict"],
                         "unmeasured:code_reader_not_measurable_for_a_directory")

    def test_an_empty_directory_artifact_is_not_an_observed_writer(self):
        self.scene.manifest(agents=[_agent("com.spa.x", "data/statements", slo=None)])
        (self.scene.root / "data" / "statements").mkdir()
        row = _row(self.scene.measure(), "data/statements")
        self.assertEqual(row["note"], "directory_empty")
        self.assertEqual(row["verdict"], "writer_silent")

    def test_a_manifest_declaring_no_produced_artifact_is_unmeasured(self):
        self.scene.manifest(agents=[{"label": "com.spa.x", "intent": "active",
                                     "produces": [], "consumes": []}])
        doc = self.scene.measure()
        self.assertEqual(doc["unmeasured"], "manifest_declares_no_produced_artifact")
        self.assertEqual(frc.verdict(doc), 2)

    def test_main_returns_the_verdict_code_and_the_json_form_omits_the_rows(self):
        """Проводка CLI: код возврата и есть вердикт, а не «напечаталось без ошибки»."""
        import contextlib, io
        self.scene.manifest(agents=[_agent("com.spa.x", "data/x.json")])
        self.scene.artifact("data/x.json", {"ok": True}, age_hours=1)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = frc.main(["--root", str(self.scene.root),
                             "--data-dir", str(self.scene.root / "data"), "--json"],
                            now=NOW)
        self.assertEqual(code, 1)
        printed = json.loads(buf.getvalue())
        self.assertNotIn("rows", printed)
        self.assertEqual(printed["verdicts"]["no_reader_found"], 1)

    def test_an_os_refusal_on_stat_is_a_named_third_outcome(self):
        """Дверь к ОС подставляется ВХОДОМ: `chmod` решал бы хост, а не код."""
        def _denied(_path):
            raise PermissionError("denied")
        mtime, why = frc._artifact_mtime("/любой/путь", stat=_denied)
        self.assertIsNone(mtime)
        self.assertEqual(why, "stat_failed:PermissionError")

    def test_an_os_refusal_on_scandir_is_its_own_named_third_outcome(self):
        d = self.scene.root / "data" / "dir"
        d.mkdir()

        def _denied(_path):
            raise OSError("denied")
        mtime, why = frc._artifact_mtime(str(d), scandir=_denied)
        self.assertIsNone(mtime)
        self.assertEqual(why, "scandir_failed:OSError")

    def test_the_wholly_unmeasured_doc_reports_zero_population_and_zero_verdicts(self):
        """«Не измерено» обязано выглядеть как ноль ИЗМЕРЕННОГО, а не как население."""
        doc = frc._unmeasured_whole("проверка")
        self.assertEqual(doc["population"], 0)
        self.assertEqual(set(doc["verdicts"].values()), {0})
        self.assertEqual(doc["applied"], False)
        self.assertEqual(doc["order"], "G86.4")

    def test_an_unparsable_module_is_named_and_the_list_is_capped(self):
        """Неразобранный модуль — не молчание: он попадает в отчёт поимённо."""
        self.scene.manifest(agents=[_agent("com.spa.x", "data/x.json")])
        self.scene.artifact("data/x.json", {"ok": True}, age_hours=1)
        for i in range(5):
            self.scene.module(f"spa_core/broken{i}.py", "def (:\n")
        doc = self.scene.measure()
        self.assertEqual(len(doc["unparsed"]), 5)
        self.assertTrue(all(u["reason"].startswith("unparsed:") for u in doc["unparsed"]))
        text = frc.format_report(doc)
        self.assertIn("[не разобрано] модулей 5:", text)
        self.assertEqual(text.split("[не разобрано] модулей 5: ")[1]
                         .split("\n")[0].count(","), 2)

    def test_the_three_return_codes_are_distinct(self):
        self.scene.manifest(agents=[_agent("com.spa.x", "data/x.json")])
        self.scene.artifact("data/x.json", {"ok": True}, age_hours=1)
        clean = self.scene.measure()
        self.assertEqual(frc.verdict(clean), 1)  # находка названа
        self.scene.manifest(agents=[_agent("com.spa.x", "data/x.json")],
                            artifacts=[{"path": "data/x.json", "status": "active",
                                        "consumers": [frc.CYCLE_CONSUMER]}])
        self.assertEqual(frc.verdict(self.scene.measure()), 0)


class TheTallyIsCheckable(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.scene = _Scene(self._tmp.name)

    def test_every_verdict_is_declared_even_at_zero(self):
        """Инв. #17: «такого исхода нет» и «исход не считался» обязаны различаться."""
        self.scene.manifest(agents=[_agent("com.spa.x", "data/x.json")])
        self.scene.artifact("data/x.json", {"ok": True}, age_hours=1)
        doc = self.scene.measure()
        self.assertEqual(set(doc["verdicts"]), set(frc.VERDICTS))
        self.assertEqual(sum(doc["verdicts"].values()), doc["population"])

    def test_the_sum_equals_the_population_on_a_mixed_scene(self):
        agents = [
            _agent("com.spa.a", "data/a.json"),
            _agent("com.spa.b", "data/b.json", intent="retired"),
            _agent("com.spa.c", "data/c.json", intent="designed"),
            _agent("com.spa.d", "data/d.json"),
        ]
        self.scene.manifest(agents=agents, artifacts=[{
            "path": "data/d.json", "status": "active",
            "consumers": [frc.CYCLE_CONSUMER]}])
        self.scene.artifact("data/a.json", {"fails": []}, age_hours=1)
        self.scene.artifact("data/d.json", {"ok": True}, age_hours=1)
        doc = self.scene.measure()
        self.assertEqual(doc["population"], 4)
        self.assertEqual(sum(doc["verdicts"].values()), 4)
        self.assertEqual(sum(doc["shape"].values()), 4)


class TheClosureOfTheOrderIsPinnedToTheRealTree(unittest.TestCase):
    """Сторож самого закрытия: снять его молча теперь нельзя."""

    def _manifest(self):
        return json.loads((REPO / "architecture" / "manifest.json")
                          .read_text(encoding="utf-8"))

    def test_the_custodian_report_is_declared_as_read_by_the_cycle(self):
        art = [a for a in self._manifest()["artifacts"]
               if a["path"] == "data/site_freshness_report.json"]
        self.assertEqual(len(art), 1, "строка кустодиана в artifacts[] должна быть одна")
        self.assertEqual(art[0]["status"], "active")
        self.assertIn(frc.CYCLE_CONSUMER, art[0]["consumers"])

    def test_the_declared_slo_does_not_disagree_with_the_producer(self):
        """Два объявления об одном файле — второй дом порога (урок ADR-513)."""
        man = self._manifest()
        art = next(a for a in man["artifacts"]
                   if a["path"] == "data/site_freshness_report.json")
        produced = next(p for ag in man["agents"] if ag["label"] == "com.spa.site_freshness"
                        for p in ag["produces"]
                        if p["artifact"] == "data/site_freshness_report.json")
        self.assertEqual(art["slo_hours"], produced["slo_hours"])

    def test_the_office_can_summarise_it_so_it_is_not_read_hollow(self):
        """Объявить артефакт и не уметь его разобрать = `ПРОЧИТАН ВХОЛОСТУЮ`."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_office_probe", REPO / "scripts" / "consume_office_reports.py")
        office = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(office)
        doc = {"ts": (NOW - dt.timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "ok": False, "n_fails": 1, "snapshot_age_h": 16.9, "api_age_h": 16.9,
               "stale_48h": False, "site_as_of": "2026-09-27",
               "fails": [{"code": "PUBLISHER_STUCK", "detail": "витрина не двигалась",
                          "severity": "FAIL"}]}
        lines = office._summarize_json("data/site_freshness_report.json", doc, now=NOW)
        self.assertFalse(any(ln.startswith(office._HOLLOW_MARK) for ln in lines), lines)
        self.assertTrue(any("PUBLISHER_STUCK" in ln for ln in lines), lines)

    def test_the_office_step_calls_this_census(self):
        """Проводка: секция обязана быть позвана из шага 0-офис, а не существовать рядом."""
        src = (REPO / "scripts" / "consume_office_reports.py").read_text(encoding="utf-8")
        self.assertIn("finding_reader_census", src)


class TheDeclarationAxisAsksTheCode(unittest.TestCase):
    """Заказ **G105 п. 3**: исходы «объявлен другим потребителем» и «объявлен другим
    агентом» суть ОБЪЯВЛЕНИЯ — спросить у кода, читает ли названный потребитель путь.

    Крайние значения оси обязаны быть ДОКАЗАТЕЛЬСТВАМИ, а вся неуверенность — уходить
    в середину с названной причиной. Поэтому у каждого теста ниже порвано ровно одно
    звено, и оно названо в имени.
    """

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.scene = _Scene(self._tmp.name)
        self.scene.artifact("data/x.json", {"ok": True}, age_hours=1.0)

    def _declare(self, consumers, agents=None):
        self.scene.manifest(
            agents=agents or [_agent("com.spa.x", "data/x.json")],
            artifacts=[{"path": "data/x.json", "status": "active",
                        "consumers": list(consumers)}])
        return self

    def _claim(self, artifact="data/x.json"):
        row = _row(self.scene.measure(), artifact)
        self.assertIn(row["verdict"], frc.DECLARATION_VERDICTS,
                      "сцена обязана давать именно ОБЪЯВЛЕНИЕ, иначе ось не спрашивается")
        return row

    # ── доказательство «читает» ─────────────────────────────────────────────────────
    def test_a_consumer_whose_own_file_reads_the_path_is_confirmed(self):
        self._declare(["reader"]).scene.module(
            "spa_core/reader.py",
            'import json\n'
            'def go():\n'
            '    return json.load(open("data/x.json"))\n')
        row = self._claim()
        self.assertEqual(row["claim"], "declaration_confirmed")
        self.assertEqual(row["claim_pairs"][0]["detail"], "spa_core/reader.py")

    def test_an_agent_label_is_resolved_through_its_wrapper_to_the_module_it_runs(self):
        """Ярлык агента адресом не является: адрес даёт РАЗБОР ОБЁРТКИ (переиспользован)."""
        agents = [_agent("com.spa.x", "data/x.json"),
                  {"label": "com.spa.y", "intent": "active", "produces": [],
                   "consumes": ["data/x.json"], "program": "agent_y.sh"}]
        self.scene.manifest(agents=agents)
        self.scene.wrapper("agent_y.sh", "spa_core.ymod")
        self.scene.module("spa_core/ymod.py",
                          'import json\n'
                          'def go():\n'
                          '    return json.load(open("data/x.json"))\n')
        row = _row(self.scene.measure(), "data/x.json")
        self.assertEqual(row["verdict"], "read_by_another_agent")
        self.assertEqual(row["claim"], "declaration_confirmed")

    # ── доказательство «не читает» = находка заказа ─────────────────────────────────
    def test_a_consumer_that_never_names_the_path_anywhere_is_the_finding(self):
        """Живая форма находки 08.10: `data/fleet_economics.json` объявлен за
        `telegram_daily_digest`, а тот — модуль БЕЗ репозиторных импортов, и имени
        файла в нём нет вовсе. Читать нечем, и объявление пусто."""
        self._declare(["reader"]).scene.module(
            "spa_core/reader.py",
            'import json\n'
            'def go():\n'
            '    return json.load(open("data/other.json"))\n')
        row = self._claim()
        self.assertEqual(row["claim"], "declaration_unbacked")
        doc = self.scene.measure()
        self.assertEqual([r["artifact"] for r in doc["claim_findings"]], ["data/x.json"])
        self.assertIn("ОБЪЯВЛЕНИЕ ПУСТО", frc.format_report(doc))

    def test_a_reader_unreachable_from_the_declared_consumer_still_leaves_it_empty(self):
        """Длинный ход того же ответа: читатель в дереве ЕСТЬ, но из названного
        потребителя он не достижим импортом — значит ЭТОТ потребитель не читает.
        Короткий ход (путь не упомянут нигде) сюда не доходит, и ветка своя."""
        self._declare(["deaf"])
        self.scene.module("spa_core/deaf.py", "VALUE = 1\n")
        self.scene.module("spa_core/stranger.py",
                          'import json\n'
                          'def go():\n'
                          '    return json.load(open("data/x.json"))\n')
        row = self._claim()
        self.assertEqual(row["claim"], "declaration_unbacked")

    def test_the_empty_declaration_raises_the_lower_bound_of_the_missing_reader(self):
        """Находка оси обязана ВОЙТИ в границу снизу, иначе вред остаётся за объявлением."""
        self._declare(["reader"]).scene.module("spa_core/reader.py", "VALUE = 2\n")
        doc = self.scene.measure()
        self.assertEqual(doc["verdicts"]["no_reader_found"], 0)
        self.assertEqual(doc["no_reader_lower_bound"], 1)
        self.assertEqual(frc.verdict(doc), 1, "пустое объявление обязано краснить вердикт")

    def test_without_the_axis_the_same_scene_would_be_called_clean(self):
        """Отрицательный контроль САМОГО заказа: до оси этот ряд считался прочитанным."""
        self._declare(["reader"]).scene.module("spa_core/reader.py", "VALUE = 2\n")
        doc = self.scene.measure()
        self.assertFalse(doc["findings"], "главная ось эту форму не видит — в этом и заказ")
        self.assertTrue(doc["claim_findings"])

    # ── третий исход: причина названа, находкой не объявляется ──────────────────────
    def test_a_read_only_inside_the_import_closure_is_unmeasured_not_confirmed(self):
        """Импорт не есть вызов. Замыкание входа агента в живом дереве — 600+ файлов,
        и «кто-то в замыкании читает» отвечало бы «да» почти на любой артефакт."""
        self._declare(["reader"])
        self.scene.module("spa_core/reader.py", "import spa_core.deep\nVALUE = 1\n")
        self.scene.module("spa_core/deep.py",
                          'import json\n'
                          'def go():\n'
                          '    return json.load(open("data/x.json"))\n')
        row = self._claim()
        self.assertEqual(row["claim"], "declaration_unmeasured")
        self.assertTrue(row["claim_pairs"][0]["detail"].startswith(
            "read_reachable_only_through_the_import_closure:"))

    def test_a_path_named_but_with_no_parsed_read_site_is_unmeasured_not_a_finding(self):
        """Живая форма: `_load_json(ddir / "equity_curve_daily.json")` — помощник, которого
        разбор не опознал. Назвать это находкой значило бы оболгать настоящего читателя."""
        self._declare(["reader"]).scene.module(
            "spa_core/reader.py",
            'NAME = "x.json"\n'
            'def go(fetch):\n'
            '    return fetch(NAME)\n')
        row = self._claim()
        self.assertEqual(row["claim"], "declaration_unmeasured")
        self.assertTrue(row["claim_pairs"][0]["detail"].startswith(
            "named_in_code_but_no_read_site_parsed:"))

    def test_a_filename_inside_prose_is_not_a_mention_and_the_row_stays_a_finding(self):
        """Обратная сторона предыдущего: `f"копится (outcomes.jsonl)"` упоминанием НЕ
        является — хвост литерала там не есть имя файла. Иначе любая прозаическая
        строка закрывала бы находку."""
        self._declare(["reader"]).scene.module(
            "spa_core/reader.py",
            'def go(n):\n'
            '    return f"копится (x.json) — {n} дн."\n')
        self.assertEqual(self._claim()["claim"], "declaration_unbacked")

    def test_a_confirmation_by_an_ambiguous_file_name_is_not_proof(self):
        """Заказ G105 п. 2 числом: разбор опознаёт ИМЯ ФАЙЛА, и `latest.json` в живом
        дереве носят трое. Попадание по такому имени этот путь не доказывает."""
        agents = [_agent("com.spa.x", "data/a/latest.json"),
                  _agent("com.spa.z", "data/b/latest.json")]
        self.scene.artifact("data/a/latest.json", {"ok": True}, age_hours=1.0)
        self.scene.artifact("data/b/latest.json", {"ok": True}, age_hours=1.0)
        self.scene.manifest(agents=agents, artifacts=[
            {"path": "data/a/latest.json", "status": "active", "consumers": ["reader"]}])
        self.scene.module("spa_core/reader.py",
                          'import json\n'
                          'def go():\n'
                          '    return json.load(open("data/a/latest.json"))\n')
        doc = self.scene.measure()
        row = _row(doc, "data/a/latest.json")
        self.assertEqual(row["claim"], "declaration_unmeasured")
        self.assertIn("confirmed_only_by_an_ambiguous_basename",
                      row["claim_pairs"][0]["detail"])
        self.assertEqual(doc["ambiguity"]["ambiguous_names"], 1)
        self.assertEqual(doc["ambiguity"]["rows_sharing_a_name"], 2)

    def test_the_same_name_in_one_place_only_lets_the_confirmation_stand(self):
        """Контроль в обратную сторону: неоднозначность, а не само имя, гасит ответ."""
        self._declare(["reader"]).scene.module(
            "spa_core/reader.py",
            'import json\n'
            'def go():\n'
            '    return json.load(open("data/x.json"))\n')
        self.assertEqual(self._claim()["claim"], "declaration_confirmed")

    def test_prose_in_the_consumer_field_is_not_a_code_address(self):
        """Живая форма: потребитель `owner audit (append-only removal log)` — человек."""
        self._declare(["owner audit (append-only removal log)"])
        row = self._claim()
        self.assertEqual(row["claim"], "declaration_unmeasured")
        self.assertEqual(row["claim_pairs"][0]["detail"],
                         "consumer_name_is_not_a_code_address")

    def test_one_word_naming_two_files_is_unmeasured_and_not_the_first_match(self):
        """Живая форма: `cycle_health_monitor` лежит и в `monitoring/`, и в `analytics/`."""
        self._declare(["twin"])
        self.scene.module("spa_core/twin.py", "VALUE = 1\n")
        self.scene.module("scripts/twin.py", "VALUE = 2\n")
        row = self._claim()
        self.assertEqual(row["claim"], "declaration_unmeasured")
        self.assertEqual(row["claim_pairs"][0]["detail"],
                         "consumer_name_resolves_to_2_code_addresses")

    def test_a_declared_module_path_that_does_not_exist_is_unmeasured(self):
        self._declare(["spa_core/gone.py"])
        self.assertEqual(self._claim()["claim_pairs"][0]["detail"],
                         "consumer_path_absent:spa_core/gone.py")

    def test_an_agent_label_absent_from_the_constitution_is_unmeasured(self):
        self._declare(["com.spa.nowhere"])
        self.assertEqual(self._claim()["claim_pairs"][0]["detail"],
                         "consumer_agent_absent_from_the_constitution")

    def test_an_agent_without_a_wrapper_file_is_unmeasured_not_unbacked(self):
        agents = [_agent("com.spa.x", "data/x.json"),
                  {"label": "com.spa.y", "intent": "active", "produces": [],
                   "consumes": [], "program": "agent_missing.sh"}]
        self._declare(["com.spa.y"], agents=agents)
        self.assertEqual(self._claim()["claim_pairs"][0]["detail"],
                         "consumer_wrapper_absent:agent_missing.sh")

    def test_a_directory_artifact_is_unmeasured_on_this_axis_too(self):
        """Разбор читателей каталога не видит ВОВСЕ (ADR-526) — и здесь тоже."""
        self.scene.artifact("data/dir/a.json", {"ok": True}, age_hours=1.0)
        self.scene.manifest(
            agents=[_agent("com.spa.x", "data/dir")],
            artifacts=[{"path": "data/dir", "status": "active", "consumers": ["reader"]}])
        self.scene.module("spa_core/reader.py", "VALUE = 1\n")
        row = _row(self.scene.measure(), "data/dir")
        self.assertEqual(row["claim_pairs"][0]["detail"],
                         "code_reader_not_measurable_for_a_directory")

    # ── сведение пар в ряд ──────────────────────────────────────────────────────────
    def test_one_confirmed_consumer_confirms_the_row(self):
        """«Читает хоть кто-то из названных» и есть вопрос ряда."""
        self._declare(["reader", "deaf"])
        self.scene.module("spa_core/reader.py",
                          'import json\n'
                          'def go():\n'
                          '    return json.load(open("data/x.json"))\n')
        self.scene.module("spa_core/deaf.py", "VALUE = 1\n")
        doc = self.scene.measure()
        row = _row(doc, "data/x.json")
        self.assertEqual(row["claim"], "declaration_confirmed")
        self.assertEqual(doc["claim_pairs"]["declaration_unbacked"], 1,
                         "пара остаётся пустой, даже когда ряд закрыт соседом")
        self.assertFalse(doc["claim_findings"], "ряд закрыт — находкой он не объявляется")

    def test_a_row_is_called_empty_only_when_every_declaration_is_empty(self):
        self._declare(["deaf", "mute"])
        self.scene.module("spa_core/deaf.py", "VALUE = 1\n")
        self.scene.module("spa_core/mute.py", "VALUE = 2\n")
        self.assertEqual(self._claim()["claim"], "declaration_unbacked")

    def test_a_mixed_row_of_empty_and_unmeasured_is_unmeasured_not_a_finding(self):
        self._declare(["deaf", "owner audit (append-only removal log)"])
        self.scene.module("spa_core/deaf.py", "VALUE = 1\n")
        self.assertEqual(self._claim()["claim"], "declaration_unmeasured")

    # ── свойства оси как оси ────────────────────────────────────────────────────────
    def test_the_axis_names_are_pinned_to_literals_not_to_the_modules_own_tuple(self):
        self.assertEqual(frc.CLAIMS, ("declaration_confirmed", "declaration_unbacked",
                                      "declaration_unmeasured"))
        self.assertEqual(frc.DECLARATION_VERDICTS,
                         ("read_by_another_declared_consumer", "read_by_another_agent"))

    def test_the_axis_is_not_a_summand_and_the_verdict_sum_still_equals_the_population(self):
        self._declare(["reader"]).scene.module("spa_core/reader.py", "VALUE = 1\n")
        doc = self.scene.measure()
        self.assertEqual(sum(doc["verdicts"].values()), doc["population"])
        self.assertEqual(sum(doc["claims"].values()), 1)

    def test_every_axis_outcome_is_declared_even_at_zero(self):
        """Инв. #17: «такого исхода нет» и «исход не считался» — разное."""
        self._declare([frc.CYCLE_CONSUMER])
        doc = self.scene.measure()
        self.assertEqual(set(doc["claims"]), set(frc.CLAIMS))
        self.assertEqual(sum(doc["claims"].values()), 0)

    def test_a_row_that_is_not_a_declaration_is_never_asked(self):
        self.scene.manifest(agents=[_agent("com.spa.x", "data/x.json")])
        doc = self.scene.measure()
        self.assertEqual(_row(doc, "data/x.json")["verdict"], "no_reader_found")
        self.assertNotIn("claim", _row(doc, "data/x.json"))

    def test_the_report_prints_the_axis_and_the_ambiguity_number(self):
        self._declare(["reader"]).scene.module("spa_core/reader.py", "VALUE = 1\n")
        text = frc.format_report(self.scene.measure())
        self.assertIn("объявление против кода", text)
        self.assertIn("заказ G105 п. 2", text)
        self.assertIn("граница снизу", text)

    def test_the_old_disclaimer_about_the_declared_consumer_is_gone(self):
        """Прибор больше не вправе говорить «не докладываю», когда он докладывает."""
        self._declare(["reader"]).scene.module("spa_core/reader.py", "VALUE = 1\n")
        text = frc.format_report(self.scene.measure())
        self.assertNotIn("читает ли объявленный потребитель файл на самом деле", text)


if __name__ == "__main__":
    unittest.main()
