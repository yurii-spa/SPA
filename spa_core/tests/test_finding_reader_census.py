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


if __name__ == "__main__":
    unittest.main()
