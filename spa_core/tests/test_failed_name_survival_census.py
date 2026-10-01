# LLM_FORBIDDEN
"""Батарея переписи «переживают ли имена упавших тестов раннер» (ADR-528, G87 п. 1).

Каждый тест — положительный контроль на КОНКРЕТНОЕ порванное звено, и звено
названо в имени теста. Обратная сторона проверяется тоже: на исправном контуре
прибор говорит `record_survives_as_artifact`, а не молчит.

**Сцена — ВХОД, а не окружение.** Разобранные воркфлоу подаются аргументом
(`measure(root, workflows=…)`), поэтому ни один тест здесь не ходит в живой
GitHub и не зависит от того, что сегодня лежит в `.github/`. Исключение —
два теста, чей ПРЕДМЕТ есть именно настоящее дерево: они названы словом
`real_tree` и объявлены таковыми.

Литеральных дат и литеральных pid здесь нет вовсе — предмет не про время и не
про личность процесса.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import failed_name_survival_census as c

_REPO_ROOT = str(Path(__file__).resolve().parents[2])


def _step(name, run=None, env=None, **extra):
    step = {"name": name}
    if run is not None:
        step["run"] = run
    if env is not None:
        step["env"] = env
    step.update(extra)
    return step


#: «Условия нет вовсе» — отдельное значение, а не пустая строка: GitHub
#: пропускает шаг без `if:` после упавшего, и спутать это с `if: ''` нельзя.
_NO_CONDITION = object()


def _upload(name, path, cond=_NO_CONDITION):
    step = {"name": name, "uses": "actions/upload-artifact@v4",
            "with": {"path": path}}
    if cond is not _NO_CONDITION:
        step["if"] = cond
    return step


def _wf(steps, job="test"):
    return {"w.yml": {"jobs": {job: {"steps": steps}}}}


def _one(steps, job="test"):
    doc = c.measure(_REPO_ROOT, workflows=_wf(steps, job))
    rows = doc["rows"]
    assert len(rows) == 1, f"ожидался один писатель, вышло {len(rows)}: {rows}"
    return rows[0]


PYTEST_WITH_JUNIT = "python -m pytest spa_core/tests/ --junitxml=reports/junit-x.xml"


class WriterLeg(unittest.TestCase):
    """Нога ПИСАТЕЛЯ: покидает ли запись раннер."""

    def test_covering_upload_that_runs_on_failure_is_the_healthy_contour(self):
        row = _one([_step("run", PYTEST_WITH_JUNIT),
                    _upload("up", "reports/", "${{ !cancelled() }}")])
        self.assertEqual(c.SURVIVES, row["outcome"])
        self.assertIn("исполняется при отказе", row["why"])

    def test_upload_without_a_condition_is_skipped_exactly_when_needed(self):
        """Порванное звено: выгрузка объявлена и на пути ОТКАЗА не исполняется."""
        row = _one([_step("run", PYTEST_WITH_JUNIT),
                    _upload("up", "reports/")])
        self.assertEqual(c.NOT_ON_FAILURE, row["outcome"])
        self.assertIn("ПРОПУСКАЕТ", row["why"])

    def test_continue_on_error_at_the_writer_is_the_second_path_and_is_named(self):
        """Второй путь к тому же исходу — и он НАЗВАН, а не домыслен."""
        row = _one([_step("run", PYTEST_WITH_JUNIT, **{"continue-on-error": True}),
                    _upload("up", "reports/")])
        self.assertEqual(c.SURVIVES, row["outcome"])
        self.assertIn("continue-on-error", row["why"])

    def test_upload_in_another_job_does_not_save_this_jobs_record(self):
        """Порванное звено: выгрузка есть, но в ЧУЖОЙ джобе."""
        doc = c.measure(_REPO_ROOT, workflows={"w.yml": {"jobs": {
            "test": {"steps": [_step("run", PYTEST_WITH_JUNIT)]},
            "lint": {"steps": [_upload("up", "reports/", "${{ always() }}")]},
        }}})
        rows = [r for r in doc["rows"] if r["job"] == "test"]
        self.assertEqual([c.DIES], [r["outcome"] for r in rows])

    def test_a_step_that_writes_no_record_is_its_own_outcome(self):
        row = _one([_step("run", "python -m pytest spa_core/tests/ -q")])
        self.assertEqual(c.NO_RECORD, row["outcome"])
        self.assertIn("только в логе", row["why"])

    def test_installing_pytest_is_not_a_writer(self):
        """Порванное звено: суждение по ПОДСТРОКЕ вместо вызова.

        `pip install pytest` ничего не пишет; попав в население, он раздул бы
        `no_record_written` на вред, которого нет. Соседний сторож судит по
        подстроке намеренно (его вопрос требует ошибаться в сторону находки) —
        здесь та же ошибка идёт в сторону ЗАВЫШЕНИЯ вреда.
        """
        doc = c.measure(_REPO_ROOT, workflows=_wf([
            _step("deps", "pip install pytest pytest-timeout pyyaml"),
            _step("also deps", "python -m pip install --quiet pytest"),
        ]))
        self.assertEqual(0, doc["population"], doc["rows"])

    def test_pytest_invoked_as_a_bare_command_is_a_writer(self):
        """Обратная сторона: вызов без `-m` тоже писатель."""
        row = _one([_step("run", "pytest spa_core/tests/ --junitxml=reports/j.xml"),
                    _upload("up", "reports/", "${{ always() }}")])
        self.assertEqual(c.SURVIVES, row["outcome"])


class RecordForms(unittest.TestCase):
    """Три распознаваемые формы объявления записи — и их покрытие."""

    def test_stream_env_variable_is_a_record(self):
        row = _one([_step("run", "python -m pytest spa_core/tests/ -q",
                          env={"SPA_PYTEST_STREAM": "reports/stream.jsonl"}),
                    _upload("up", "reports/", "${{ always() }}")])
        self.assertEqual(c.SURVIVES, row["outcome"])
        self.assertIn({"form": "stream_env", "path": "reports/stream.jsonl"},
                      row["records"])

    def test_tee_is_a_record(self):
        row = _one([_step("run", "python -m pytest spa_core/tests/ -q 2>&1 "
                                 "| tee test_output.txt"),
                    _upload("up", "test_output.txt", "${{ always() }}")])
        self.assertEqual(c.SURVIVES, row["outcome"])
        self.assertIn({"form": "tee", "path": "test_output.txt"}, row["records"])

    def test_directory_prefix_covers_a_file_inside_it(self):
        self.assertTrue(c._covers("reports/", "reports/junit-x.xml"))
        self.assertTrue(c._covers("reports", "reports/junit-x.xml"))

    def test_glob_covers_a_matching_file(self):
        self.assertTrue(c._covers("reports/*.xml", "reports/junit-x.xml"))
        self.assertFalse(c._covers("reports/*.xml", "reports/stream.jsonl"))

    def test_an_unrelated_path_covers_nothing(self):
        self.assertFalse(c._covers("data/pipeline_health.json",
                                   "reports/junit-x.xml"))


class ThirdOutcome(unittest.TestCase):
    """Третий исход обязателен и никогда не выдаётся за «чисто» (инв. #17)."""

    def test_a_substituted_upload_path_cannot_be_decided(self):
        row = _one([_step("run", PYTEST_WITH_JUNIT),
                    _upload("up", "${{ env.OUT }}/reports", "${{ always() }}")])
        self.assertEqual(c.UNMEASURED, row["outcome"])
        self.assertIn("подстановку", row["why"])

    def test_an_unknown_condition_token_cannot_be_decided(self):
        row = _one([_step("run", PYTEST_WITH_JUNIT),
                    _upload("up", "reports/", "${{ github.ref == 'refs/heads/x' }}")])
        self.assertEqual(c.UNMEASURED, row["outcome"])
        self.assertIn("не содержит ни одного известного токена", row["why"])

    def test_missing_workflows_dir_is_unmeasured_with_a_named_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = c.measure(tmp)
            self.assertEqual("unmeasured", c.verdict(doc))
            self.assertIn("каталога воркфлоу нет", doc["unmeasured_reason"])
            self.assertIn("НЕ ИЗМЕРЕНО", c.format_report(doc))

    def test_an_empty_workflows_dir_is_unmeasured_not_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".github", "workflows"))
            with self.assertRaises(c.Unmeasured) as ctx:
                c.load_workflows(tmp)
            self.assertIn("ни одного воркфлоу", str(ctx.exception))

    def test_an_unparseable_workflow_refuses_instead_of_being_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            wf = Path(tmp, ".github", "workflows")
            wf.mkdir(parents=True)
            (wf / "broken.yml").write_text("jobs: [\n  unterminated: {",
                                           encoding="utf-8")
            with self.assertRaises(c.Unmeasured) as ctx:
                c.load_workflows(tmp)
            self.assertIn("не разобран", str(ctx.exception))

    def test_an_empty_population_is_unmeasured_not_green(self):
        """Сторож без населения зелен по построению — и это ничего не значит."""
        doc = c.measure(_REPO_ROOT, workflows={"w.yml": {"jobs": {}}})
        self.assertEqual(0, doc["population"])
        self.assertEqual("unmeasured", c.verdict(doc))


class SeverityLadder(unittest.TestCase):
    """Вердикт шага с НЕСКОЛЬКИМИ записями — вердикт худшей (fail-CLOSED)."""

    def test_one_dead_record_beats_one_that_survives(self):
        row = _one([_step("run", PYTEST_WITH_JUNIT,
                          env={"SPA_PYTEST_STREAM": "elsewhere/stream.jsonl"}),
                    _upload("up", "reports/", "${{ always() }}")])
        self.assertEqual(c.DIES, row["outcome"])

    def test_an_undecidable_record_beats_one_that_survives(self):
        """«Не знаю» не прячется за «уцелело» — но и не прячет названный вред."""
        doc = c.measure(_REPO_ROOT, workflows=_wf([
            _step("run", "python -m pytest x --junitxml=reports/j.xml",
                  env={"SPA_PYTEST_STREAM": "${{ env.S }}/stream.jsonl"}),
            _upload("up", "reports/", "${{ always() }}")]))
        self.assertEqual(c.UNMEASURED, doc["rows"][0]["outcome"])

    def test_a_named_harm_beats_dont_know(self):
        doc = c.measure(_REPO_ROOT, workflows=_wf([
            _step("run", "python -m pytest x --junitxml=gone/j.xml",
                  env={"SPA_PYTEST_STREAM": "${{ env.S }}/stream.jsonl"}),
            _upload("up", "reports/", "${{ always() }}")]))
        self.assertEqual(c.DIES, doc["rows"][0]["outcome"])


class Bookkeeping(unittest.TestCase):
    """Сумма равна населению, каждый ноль объявлен, перечень исходов ЗАКРЫТ."""

    def test_counts_sum_to_population_on_the_real_tree(self):
        doc = c.measure(_REPO_ROOT)
        self.assertNotEqual("", str(doc["population"]))
        self.assertGreater(doc["population"], 0, doc.get("unmeasured_reason"))
        self.assertEqual(doc["population"], sum(doc["counts"].values()))

    def test_every_outcome_name_is_printed_even_at_zero(self):
        doc = c.measure(_REPO_ROOT, workflows=_wf([
            _step("run", PYTEST_WITH_JUNIT),
            _upload("up", "reports/", "${{ always() }}")]))
        report = c.format_report(doc)
        for name in c.OUTCOMES:
            self.assertIn(name, report, name)

    def test_the_outcome_list_is_exercised_not_compared_with_itself(self):
        """Урок #722: перечень, сверенный сам с собой, зелен ПО ПОСТРОЕНИЮ.

        Поэтому проверяется не равенство списков, а то, что КАЖДЫЙ исход
        прибор действительно выдаёт на какой-то сцене.
        """
        scenes = {
            c.SURVIVES: [_step("r", PYTEST_WITH_JUNIT),
                         _upload("u", "reports/", "${{ always() }}")],
            c.NOT_ON_FAILURE: [_step("r", PYTEST_WITH_JUNIT),
                               _upload("u", "reports/")],
            c.DIES: [_step("r", PYTEST_WITH_JUNIT)],
            c.NO_RECORD: [_step("r", "python -m pytest x -q")],
            c.UNMEASURED: [_step("r", PYTEST_WITH_JUNIT),
                           _upload("u", "reports/", "${{ github.ref == 'x' }}")],
        }
        produced = {name: _one(steps)["outcome"] for name, steps in scenes.items()}
        self.assertEqual(scenes.keys(), set(c.OUTCOMES))
        for expected, got in produced.items():
            self.assertEqual(expected, got, f"сцена {expected} дала {got}")

    def test_verdict_names_the_two_measured_outcomes_apart(self):
        doc_all_green = c.measure(_REPO_ROOT, workflows=_wf([
            _step("r", PYTEST_WITH_JUNIT),
            _upload("u", "reports/", "${{ always() }}")]))
        self.assertEqual("names_outlive_the_runner", c.verdict(doc_all_green))
        doc_red = c.measure(_REPO_ROOT, workflows=_wf([_step("r", PYTEST_WITH_JUNIT)]))
        self.assertEqual("names_die_with_the_runner", c.verdict(doc_red))


class NamesShownIsMeasured(unittest.TestCase):
    """Число печати ИЗМЕРЯЕТСЯ у ci_verdict, а не перепечатывается из текста."""

    def test_the_limit_is_read_from_the_source(self):
        self.assertIsInstance(c.names_shown(_REPO_ROOT), int)

    def test_a_missing_source_yields_not_measured_not_a_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(c.names_shown(tmp))

    def test_the_report_says_not_measured_rather_than_a_number(self):
        doc = c.measure(_REPO_ROOT, workflows=_wf([_step("r", PYTEST_WITH_JUNIT)]))
        doc["names_shown"] = None
        self.assertIn("_NAMES_SHOWN, замером): НЕ ИЗМЕРЕНО", c.format_report(doc))


class ReaderLeg(unittest.TestCase):
    """Вторая ось: КАНАЛ читателя. В сумму населения не входит."""

    def test_the_gate_is_the_union_of_the_marks(self):
        """Порванное звено: отдельные «ворота» разошлись бы с метками.

        Файл, который берёт прогон по `actions/workflows/`, обязан попасть в
        население — у метки этого канала он есть, и второго списка, способного
        его отвергнуть, не существует.
        """
        self.assertEqual(c.CH_API, c._channel_of("url = '/actions/workflows/test.yml'"))
        self.assertIsNone(c._channel_of("ничего про вердикт CI тут нет"))

    def test_api_conclusion_carries_no_names_at_all(self):
        self.assertEqual(c.CH_API, c._channel_of("GET /actions/runs?branch=main"))

    def test_a_record_given_as_input_is_its_own_channel(self):
        self.assertEqual(c.CH_LOCAL_RECORD, c._channel_of("--junitxml запись"))

    def test_every_exclusion_carries_a_named_reason(self):
        self.assertTrue(c.READER_EXCLUSIONS)
        for path, reason in c.READER_EXCLUSIONS.items():
            self.assertTrue(reason.strip(), path)

    def test_the_instrument_does_not_count_itself(self):
        """Сверять прибор сам с собой — тавтология (ADR-504)."""
        doc = c.measure(_REPO_ROOT)
        self.assertNotIn("spa_core/monitoring/failed_name_survival_census.py",
                         [r["reader"] for r in doc["readers"]])

    def test_the_number_of_scanned_files_is_printed(self):
        doc = c.measure(_REPO_ROOT)
        self.assertIsInstance(doc["reader_files_scanned"], int)
        self.assertIn(str(doc["reader_files_scanned"]), c.format_report(doc))


class RealTree(unittest.TestCase):
    """Предмет этих двух — НАСТОЯЩЕЕ дерево, и это объявлено в имени класса."""

    def test_real_tree_test_yml_records_outlive_the_runner(self):
        """Контроль доставки ADR-528: пропажа шага выгрузки красит набор."""
        doc = c.measure(_REPO_ROOT)
        rows = [r for r in doc["rows"] if r["workflow"] == "test.yml"]
        self.assertTrue(rows, "в test.yml не найдено ни одного писателя")
        bad = [f"{r['step']}: {r['outcome']} — {r['why']}"
               for r in rows if r["outcome"] != c.SURVIVES]
        self.assertEqual([], bad,
                         "запись имён в test.yml снова не покидает раннер")

    def test_real_tree_population_is_not_vacuous(self):
        doc = c.measure(_REPO_ROOT)
        self.assertGreaterEqual(doc["population"], 5, doc["rows"])


if __name__ == "__main__":
    unittest.main()


class MutationsFoundTheseGaps(unittest.TestCase):
    """Дыры, найденные МУТАЦИОННЫМ замером батареи, а не чтением глазами.

    Каждый тест здесь существует потому, что мутация соответствующей строки
    прибора ВЫЖИВАЛА — то есть прибор можно было сломать ровно так, и набор
    этого не замечал.
    """

    def test_the_limit_is_the_value_of_that_name_and_not_of_any_int(self):
        """Выжившая мутация: `target.id == "_NAMES_SHOWN"` → `!=`.

        Батарея проверяла только `isinstance(…, int)`, поэтому прибор мог
        вернуть ЛЮБУЮ целую константу модуля (`RC_GREEN` = 0) и выглядеть
        измеряющим. Эталон добывается независимо — разбором того же файла по
        ДРУГОМУ правилу, а не вторым вызовом того же кода.
        """
        import ast as _ast
        source = Path(_REPO_ROOT, "scripts", "ci_verdict.py").read_text(encoding="utf-8")
        wanted = [n.value.value
                  for n in _ast.walk(_ast.parse(source))
                  if isinstance(n, _ast.Assign)
                  and any(isinstance(t, _ast.Name) and t.id == "_NAMES_SHOWN"
                          for t in n.targets)
                  and isinstance(n.value, _ast.Constant)]
        self.assertEqual(1, len(wanted), "эталон не однозначен")
        self.assertEqual(wanted[0], c.names_shown(_REPO_ROOT))

    def test_a_glob_char_alone_does_not_make_a_path_covered(self):
        """Выжившая мутация: `and` → `or` в ветке glob у `_covers`."""
        self.assertFalse(c._covers("reports/*.xml", "elsewhere/junit.xml"))
        self.assertFalse(c._covers("other/*", "reports/junit.xml"))

    def test_a_pytest_invoked_by_absolute_path_is_still_a_writer(self):
        """Выжившая мутация: `rsplit("/", 1)[-1]` → `[0]`."""
        self.assertTrue(c._invokes_pytest("/usr/local/bin/pytest spa_core/tests/"))
        self.assertTrue(c._invokes_pytest("python -m pytest x"))
        self.assertFalse(c._invokes_pytest("echo pytest-is-a-word"))

    def test_a_workflow_whose_jobs_are_not_a_mapping_is_not_a_finding(self):
        """Выжившая мутация: ветка `jobs` не словарь не исполнялась ни раз."""
        self.assertEqual([], c._steps_of({"jobs": ["test"]}))
        self.assertEqual([], c._steps_of({}))
        self.assertEqual([], c._steps_of({"jobs": {"t": "not a mapping"}}))
        self.assertEqual([], c._steps_of({"jobs": {"t": {"steps": "not a list"}}}))

    def test_a_step_without_a_name_is_identified_by_its_index(self):
        """Выжившая мутация: `step.get("name") or f"#{index}"`."""
        doc = c.measure(_REPO_ROOT, workflows={"w.yml": {"jobs": {"test": {"steps": [
            {"run": "python -m pytest x --junitxml=reports/j.xml"}]}}}})
        self.assertEqual("#0", doc["rows"][0]["step"])

    def test_the_conclusion_line_appears_only_when_nothing_survives(self):
        """Выжившая мутация: условие ветки ВЫВОД в `format_report`."""
        dead = c.measure(_REPO_ROOT, workflows=_wf([_step("r", PYTEST_WITH_JUNIT)]))
        self.assertIn("ВЫВОД: раннер не покидает НИ ОДНА запись", c.format_report(dead))
        alive = c.measure(_REPO_ROOT, workflows=_wf([
            _step("r", PYTEST_WITH_JUNIT),
            _upload("u", "reports/", "${{ always() }}")]))
        self.assertNotIn("ВЫВОД:", c.format_report(alive))

    def test_a_surviving_row_is_not_printed_but_a_broken_one_is(self):
        """Выжившая мутация: `if row["outcome"] == SURVIVES: continue`."""
        mixed = c.measure(_REPO_ROOT, workflows={"w.yml": {"jobs": {
            "a": {"steps": [_step("good", PYTEST_WITH_JUNIT),
                            _upload("u", "reports/", "${{ always() }}")]},
            "b": {"steps": [_step("bad", PYTEST_WITH_JUNIT)]}}}})
        report = c.format_report(mixed)
        self.assertIn("bad", report)
        self.assertNotIn(":: good —", report)

    def test_cli_return_code_is_the_verdict_and_not_a_constant(self):
        """Выжившие мутации: таблица кодов возврата у `main` не звалась ни раз.

        Корень подаётся ВХОДОМ (`--root`), поэтому тест не зовёт прибор на живом
        дереве и не зависит от того, что лежит в `.github/` прода.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(2, c.main(["--root", tmp]))
        self.assertEqual(1, c.main(["--root", _REPO_ROOT]))

    def test_cli_json_mode_prints_the_measurement(self):
        """Выжившая мутация: ветка `--json` не исполнялась ни раз."""
        import contextlib
        import io
        import json as _json
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            c.main(["--root", _REPO_ROOT, "--json"])
        doc = _json.loads(buf.getvalue())
        self.assertEqual(doc["population"], sum(doc["counts"].values()))

    def test_only_python_files_are_scanned_and_tests_are_skipped(self):
        """Выжившие мутации: фильтр `.py` и отсев каталога `tests`."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp, "scripts")
            base.mkdir()
            (base / "reader.py").write_text("GET /actions/runs", encoding="utf-8")
            (base / "not_python.txt").write_text("GET /actions/runs", encoding="utf-8")
            (base / "tests").mkdir()
            (base / "tests" / "t_reader.py").write_text("GET /actions/runs",
                                                        encoding="utf-8")
            readers, counts, scanned = c._reader_axis(tmp)
            self.assertEqual(["scripts/reader.py"], [r["reader"] for r in readers])
            self.assertEqual(1, counts[c.CH_API])
            self.assertEqual(1, scanned, "просмотрено обязано считать только .py вне tests")

    def test_a_missing_tree_leaves_the_reader_axis_empty_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            readers, counts, scanned = c._reader_axis(tmp)
            self.assertEqual([], readers)
            self.assertEqual(0, scanned)
            self.assertEqual({name: 0 for name in c.READER_CHANNELS}, counts)

    def test_an_empty_population_is_not_printed_as_clean(self):
        """Дыра, найденная перечитыванием отчёта: нули на пустом населении.

        Класс `vacuous_guard_census` — сторож без населения зелен ПО
        ПОСТРОЕНИЮ, и такой отчёт fail-OPEN тише красного, поэтому опаснее.
        """
        doc = c.measure(_REPO_ROOT, workflows={"w.yml": {"jobs": {}}})
        report = c.format_report(doc)
        self.assertIn("НЕ ИЗМЕРЕНО", report)
        self.assertNotIn("record_survives_as_artifact 0", report)
