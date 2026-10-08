# LLM_FORBIDDEN
"""Батарея переписи «переживают ли имена упавших тестов раннер» (ADR-528, G87 п. 1).

Каждый тест — положительный контроль на КОНКРЕТНОЕ порванное звено, и звено
названо в имени теста. Обратная сторона проверяется тоже: на исправном контуре
прибор говорит `record_survives_as_artifact`, а не молчит.

**Сцена — ВХОД, а не окружение.** Разобранные воркфлоу подаются аргументом
(`measure(root, workflows=…)`), поэтому ни один тест здесь не ходит в живой
GitHub и не зависит от того, что сегодня лежит в `.github/`. Исключение —
тесты, чей ПРЕДМЕТ есть именно настоящее дерево: они названы словом
`real_tree` и объявлены таковыми. С заказом G106 п. 2 их стало больше: каждый
из пяти шагов, закрытых поимённо, получил СВОЙ контроль — вред закрывался не
пакетом, и проверяться он обязан так же.

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

    # ── пять шагов заказа G106 п. 2: у КАЖДОГО свой контроль ────────────────
    # Заказ (хвост ADR-528) запретил закрывать эти пять пакетом, и проверка
    # обязана быть такой же: один общий тест «на дереве всё зелено» покраснел
    # бы ОДНИМ именем на любую из пяти потерь, а чинить пришлось бы угадывая.
    # Каждый метод ниже называет свой шаг и падает за него.

    def _real_row(self, workflow: str, step: str) -> dict:
        doc = c.measure(_REPO_ROOT)
        rows = [r for r in doc["rows"]
                if r["workflow"] == workflow and r["step"] == step]
        self.assertEqual(1, len(rows),
                         f"в {workflow} ожидался ровно один шаг «{step}», "
                         f"найдено {len(rows)}: переименование шага НЕ есть "
                         f"его исправность")
        return rows[0]

    def test_real_tree_ci_spa_core_step_record_outlives_the_runner(self):
        row = self._real_row("ci.yml", "Run spa_core/tests (unit)")
        self.assertEqual(c.SURVIVES, row["outcome"], row["why"])

    def test_real_tree_ci_tests_root_step_record_outlives_the_runner(self):
        row = self._real_row("ci.yml", "Run tests/ root (integration)")
        self.assertEqual(c.SURVIVES, row["outcome"], row["why"])

    def test_real_tree_ci_scripts_step_record_outlives_the_runner(self):
        row = self._real_row("ci.yml", "Run scripts/ gate tests + colocated suites")
        self.assertEqual(c.SURVIVES, row["outcome"], row["why"])

    def test_real_tree_proof_gate_dd_pack_step_record_outlives_the_runner(self):
        row = self._real_row("proof-gate.yml", "DD_PACK head staleness test")
        self.assertEqual(c.SURVIVES, row["outcome"], row["why"])

    def test_real_tree_proof_gate_proof_chain_step_record_outlives_the_runner(self):
        row = self._real_row("proof-gate.yml", "Proof-chain + equity-track unit tests")
        self.assertEqual(c.SURVIVES, row["outcome"], row["why"])

    def test_real_tree_both_branches_of_the_dd_pack_step_declare_the_record(self):
        """Ветка `else` без записи оставила бы вред ровно на своём пути.

        Прибор судит шаг ЦЕЛИКОМ и обеих ветвей не различает: одной записи в
        `run` ему достаточно. Поэтому утверждение «запись объявлена в КАЖДОЙ
        ветке» мерится здесь, а не там.
        """
        import yaml  # noqa: PLC0415 — тест-домен, не рантайм (инв. #4)
        doc = yaml.safe_load(
            Path(_REPO_ROOT, ".github", "workflows", "proof-gate.yml")
            .read_text(encoding="utf-8"))
        steps = doc["jobs"]["proof-gate"]["steps"]
        run = [s for s in steps if s.get("name") == "DD_PACK head staleness test"][0]["run"]
        # Продолжения строк СКЛЕИВАЮТСЯ до подсчёта: иначе один прогон, разбитый
        # `\` на две строки, считался бы двумя ветками, и тест мерил бы перенос
        # строки вместо ветвления (замерено на собственной правке этого цикла).
        unfolded = run.replace("\\\n", " ")
        real = [line for line in unfolded.splitlines()
                if "pytest" in line and "--collect-only" not in line]
        self.assertEqual(2, len(real), f"ожидались две ветки прогона, видно: {real}")
        self.assertEqual(
            2, run.count("--junitxml="),
            "одна из ветвей `if/else` не объявляет junit-записи: исполнится "
            "ровно одна, и без записи останется именно тот путь, которым "
            f"прогон и пойдёт. run:\n{run}")


class RecordPathSurvivesTheWorkingDirectory(unittest.TestCase):
    """ЧЕГО ПРИБОР НЕ ВИДИТ: рабочий каталог шага (заказ G106 п. 2).

    `_covers` сравнивает СТРОКИ: `path: reports/` покрывает
    `reports/junit-x.xml` при любом рабочем каталоге шага. Но шаг
    `ci.yml::Run spa_core/tests (unit)` делает `cd spa_core`, и запись,
    объявленная там как `reports/junit-x.xml`, легла бы в
    `spa_core/reports/` — выгрузка от корня её НЕ забрала бы, а прибор всё
    равно сказал бы `record_survives_as_artifact`. То есть собственная правка
    заказа опирается на свойство, которого мера не измеряет, — и поэтому
    свойство измеряется ОТДЕЛЬНО, а не считается очевидным.

    Проверка идёт по всем воркфлоу, а не по одному известному шагу: следующий
    шаг с `cd` попадёт в неё сам.
    """

    _UPLOAD_ROOTS = ("reports",)

    def test_a_step_that_changes_directory_declares_a_record_outside_it(self):
        import re  # noqa: PLC0415
        import yaml  # noqa: PLC0415
        wf_dir = Path(_REPO_ROOT, ".github", "workflows")
        checked = 0
        for path in sorted(wf_dir.glob("*.yml")):
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for job_name, job in (doc.get("jobs") or {}).items():
                for step in (job.get("steps") or []):
                    if not isinstance(step, dict) or not c._is_pytest_step(step):
                        continue
                    run = step.get("run") or ""
                    cds = re.findall(r"^\s*cd\s+([^\s;&|]+)", run, re.M)
                    if not cds:
                        continue
                    cwd = os.path.normpath(os.path.join(*cds))
                    for form, rec in c.record_paths(step):
                        checked += 1
                        effective = os.path.normpath(os.path.join(cwd, rec))
                        self.assertTrue(
                            effective.split(os.sep)[0] in self._UPLOAD_ROOTS,
                            f"{path.name}::{job_name} :: {step.get('name')}: "
                            f"запись {form} «{rec}» при рабочем каталоге «{cwd}» "
                            f"ляжет в «{effective}» — выгрузка объявляет "
                            f"{self._UPLOAD_ROOTS} от КОРНЯ рабочей копии и этот "
                            f"путь не заберёт; прибор этого не видит по построению")
        self.assertGreater(checked, 0,
                           "ни одного шага с `cd` и записью не найдено — "
                           "предпосылка теста НЕ ОБЕСПЕЧЕНА, и это третий "
                           "исход, а не зелёный: шаг `cd spa_core` в ci.yml "
                           "есть, значит сцена или разбор сломались")


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

        Все ТРИ кода добываются СЦЕНОЙ в одноразовом дереве, и это не придирка
        к чистоте: до заказа G106 п. 2 код 1 брался у живого `.github/` прода —
        то есть тест держался на том, что в репозитории ЕСТЬ незакрытая находка.
        Пять находок закрыты, живое дерево отвечает 0, и прежняя строка
        покраснела бы ОТ ИСПРАВЛЕНИЯ вреда. Чинить это понижением проверки
        («ну пусть будет 0») значило бы перестать мерить таблицу вовсе: 0 она
        теперь отдаёт и на пустом населении. Поэтому 1 добывается порванным
        контуром на входе, 2 — отсутствием воркфлоу, 0 — живым деревом.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(2, c.main(["--root", tmp]), "нет воркфлоу ⇒ НЕ ИЗМЕРЕНО")
        with tempfile.TemporaryDirectory() as tmp:
            wf = Path(tmp, ".github", "workflows")
            wf.mkdir(parents=True)
            Path(wf, "w.yml").write_text(
                "jobs:\n"
                "  test:\n"
                "    steps:\n"
                "      - name: writer without any record\n"
                "        run: python -m pytest tests/\n",
                encoding="utf-8")
            # Население ВТОРОЙ оси (G106 п. 3): код возврата теперь ХУДШИЙ из
            # двух, и на дереве без площадок второй оси сцена отвечала бы 2 —
            # то есть перестала бы мерить таблицу ПИСАТЕЛЯ. Ни одной метки
            # канала в этих файлах нет: сцена даёт население, а не находку.
            # ТРЕТЬЯ ось (возраст записи, G106 п. 1) добавила к коду возврата
            # своё слагаемое, и её пустое население честно отвечает 2 (класс
            # `vacuous_guard_census`). Поэтому сцена усилена НАСЕЛЕНИЕМ третьей
            # оси — один читатель записи своего прогона; проверка не понижена:
            # предмет теста (таблица кодов ПИСАТЕЛЯ) мерится по-прежнему, а
            # сцена перестала молча зависеть от пустоты соседней оси
            # (намеренная правка теста, инв. #16 — в журнале W41).
            _tree(tmp, {"a/x.py": "P = '--junitxml'\n", "a/x.sh": "echo ok\n",
                        "CLAUDE.md": "протокол\n",
                        "docs/ORCHESTRATOR_PROTOCOL.md": "протокол\n",
                        ".claude/rules/r.md": "правило\n"})
            self.assertEqual(1, c.main(["--root", tmp]), "есть находка ⇒ код 1")
        self.assertEqual(0, c.main(["--root", _REPO_ROOT]),
                         "на живом дереве находок нет ⇒ код 0")

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


# ── ось читателей ВНЕ узкого населения (заказ G106 п. 3, ADR-650) ────────────

def _tree(tmp: str, files: dict) -> str:
    """Одноразовое дерево-сцена: сцена есть ВХОД, а не живое дерево репозитория."""
    for rel, text in files.items():
        path = Path(tmp, *rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp


class WhereTheMarkLives(unittest.TestCase):
    """Проза, НАЗЫВАЮЩАЯ канал, читателем не делает — и это измеряется."""

    def test_a_python_mark_in_a_comment_is_prose_and_not_executable_text(self):
        """Порванное звено: суждение по ПОДСТРОКЕ.

        Ровно эта форма и числится у узкой оси единственным читателем лога
        шага — слово в комментарии.
        """
        executed, prose = c._python_text("# имена читает ci_verdict\nx = 1\n")
        self.assertEqual((), c._channels_in(executed))
        self.assertEqual(c.CH_STEP_LOG, c._channels_in(prose)[0][0])

    def test_a_python_mark_in_a_docstring_is_prose(self):
        executed, prose = c._python_text('"""Читатель — ci_verdict."""\nx = 1\n')
        self.assertEqual((), c._channels_in(executed))
        self.assertTrue(c._channels_in(prose))

    def test_a_function_docstring_is_prose_too_and_the_body_stays_executable(self):
        src = 'def f():\n    """про ci_verdict"""\n    return "--junitxml"\n'
        executed, prose = c._python_text(src)
        self.assertEqual((c.CH_LOCAL_RECORD,),
                         tuple(ch for ch, _ in c._channels_in(executed)))
        self.assertEqual((c.CH_STEP_LOG,),
                         tuple(ch for ch, _ in c._channels_in(prose)))

    def test_a_cyrillic_docstring_does_not_shift_the_cut(self):
        """Порванное звено: резать по `col_offset` узлов ``ast``.

        Там шкала БАЙТОВАЯ, а у токенайзера символьная; на кириллице (её здесь
        большинство) смешение двух шкал отрезало бы строку не там и утащило
        исполняемый текст в прозу. Правило токена позиций не требует вовсе.
        """
        src = ('"""Очень длинная кириллическая шапка модуля про вердикт."""\n'
               'URL = "/actions/runs?branch=main"\n')
        executed, prose = c._python_text(src)
        self.assertIn("/actions/runs", executed)
        self.assertNotIn("/actions/runs", prose)

    def test_a_string_passed_to_a_call_is_executable_not_prose(self):
        """Строка-АРГУМЕНТ прозой не является: прозой объявлены только
        строки-ОПЕРАТОРЫ. Именно так читает запись настоящий читатель."""
        executed, _ = c._python_text('open("reports/junitxml")\n')
        self.assertTrue(c._channels_in(executed))

    def test_an_unparsable_python_file_is_the_third_outcome(self):
        """Не ноль и не проза: разобрать нечем ⇒ названная причина (инв. #17)."""
        with self.assertRaises(c._Unparsed):
            c._python_text("def f(:\n")

    def test_a_shell_comment_is_prose_and_a_command_is_executable(self):
        executed, prose = c._shell_text('# зовём ci_verdict\ngh run view --log\n')
        self.assertIn("--log", executed)
        self.assertIn("ci_verdict", prose)

    def test_a_markdown_code_span_is_a_command_and_the_prose_is_not(self):
        executed, prose = c._doc_text(
            "судить по сводке, а не по коду: `grep \" passed\" <лог>`\n")
        self.assertIn("grep", executed)
        self.assertNotIn("grep", prose)

    def test_a_doc_that_only_NAMES_the_channel_is_prose_and_not_a_reader(self):
        """Выживший мутант: сцена проверяла исход, а не РАЗЛИЧИЕ.

        Если `_doc_text` отдаст весь документ исполняемым, прежние проверки
        остались бы зелёными (команда-то в нём есть). Различение даёт только
        документ, где метка стои́т ТОЛЬКО в прозе: он читателем не является.
        Это та же подмена, что «проза, называющая предмет, не есть его
        производитель».
        """
        executed, prose = c._doc_text("вердикт печатает ci_verdict, и это важно\n")
        self.assertEqual((), c._channels_in(executed))
        self.assertTrue(c._channels_in(prose))

    def test_a_fenced_block_is_executable_text_too(self):
        executed, _ = c._doc_text("текст\n```\ngh run view --log\n```\n")
        self.assertIn("--log", executed)

    def test_a_workflow_is_read_through_its_parsed_strings(self):
        self.assertIn("python3 scripts/ci_verdict.py",
                      c._yaml_strings({"jobs": {"t": {"steps": [
                          {"run": "python3 scripts/ci_verdict.py r.xml"}]}}})[-1]
                      if False else
                      "\n".join(c._yaml_strings({"jobs": {"t": {"steps": [
                          {"run": "python3 scripts/ci_verdict.py r.xml"}]}}})))


class RoleIsNotMention(unittest.TestCase):
    """Зов писателя и чтение лога — разные вещи, и исход у каждого свой."""

    def test_invoking_the_writer_is_not_reading_the_log(self):
        self.assertEqual(c.ROLE_INVOKES,
                         c._role_of("python3 scripts/ci_verdict.py reports/j.xml"))

    def test_a_command_whose_input_is_a_log_is_a_reader(self):
        self.assertEqual(c.ROLE_READS, c._role_of('grep " passed" <лог>'))

    def test_the_api_log_endpoint_is_a_reader_too(self):
        self.assertEqual(c.ROLE_READS, c._role_of("GET /actions/jobs/42/logs"))

    def test_a_site_that_both_invokes_and_reads_is_a_reader(self):
        """Порядок проверки есть часть утверждения: зов не отменяет чтения."""
        self.assertEqual(c.ROLE_READS,
                         c._role_of("python3 scripts/ci_verdict.py j.xml\n"
                                    "gh run view 1 --log | grep ' passed'"))

    def test_an_unknown_form_is_the_third_outcome_not_a_reader(self):
        self.assertEqual(c.ROLE_UNMEASURED, c._role_of("слово ci-verdict рядом"))


class WidePopulation(unittest.TestCase):
    """Население четырёх родов: что в него входит и что ОБЪЯВЛЕНО вне него."""

    def test_the_narrow_population_is_not_scanned_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"scripts/a.py": "x = 'ci_verdict'\n",
                        "spa_core/monitoring/b.py": "x = 'ci_verdict'\n",
                        "spa_core/ci/c.py": "x = 'ci_verdict'\n"})
            sites, scanned, _, _ = c._wide_reader_axis(tmp, workflows={})
            self.assertEqual(1, scanned[c.KIND_CODE])
            self.assertEqual(["spa_core/ci/c.py"], [s["site"] for s in sites])

    def test_shell_in_the_declared_dirs_is_counted_because_the_py_filter_missed_it(self):
        """Каталог ``scripts/`` узкой осью объявлен, а ``*.sh`` она не видит —
        это и есть одна из цен её нуля, и здесь она закрыта числом."""
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"scripts/hook.sh": 'gh run view "$1" --log | grep " passed"\n'})
            sites, scanned, _, _ = c._wide_reader_axis(tmp, workflows={})
            self.assertEqual(1, scanned[c.KIND_SHELL])
            self.assertEqual([(c.KIND_SHELL, c.ROLE_READS)],
                             [(s["kind"], s["role"]) for s in sites])

    def test_tests_directories_are_skipped_in_the_wide_axis_as_well(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"spa_core/tests/t.py": "x = 'ci_verdict'\n"})
            sites, scanned, _, _ = c._wide_reader_axis(tmp, workflows={})
            self.assertEqual(0, scanned[c.KIND_CODE])
            self.assertEqual([], sites)

    def test_the_instrument_and_the_writer_stay_out_of_their_own_population(self):
        """Сверять прибор сам с собой — тавтология (ADR-504); у узкой оси это
        объявлено исключениями, и вторая ось обязана держать те же.

        Сцена объявляет исключение ВНЕ двух узких каталогов НАМЕРЕННО: оба
        сегодняшних исключения — ``.py`` внутри них, то есть широкая ось до
        ветки исключений на них не доходит вовсе (её снимает фильтр узкого
        населения). Мутация этой ветки на прежней сцене ВЫЖИЛА — сцена
        проверяла исход, не различая его причину.
        """
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/mine.py": "x = 'ci_verdict'\n",
                        "a/other.py": "y = 'ci_verdict'\n"})
            with mock.patch.dict(c.READER_EXCLUSIONS,
                                 {"a/mine.py": "сам прибор"}, clear=False):
                sites, scanned, _, _ = c._wide_reader_axis(tmp, workflows={})
            self.assertEqual(["a/other.py"], [s["site"] for s in sites])
            self.assertEqual(1, scanned[c.KIND_CODE],
                             "исключённая площадка не входит и в просмотренные")

    def test_all_channels_of_one_site_are_reported_without_ladder_masking(self):
        """Узкая ось отдаёт ОДИН канал на файл, и второй теряется молча."""
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "A = '--junitxml'\nB = 'ci_verdict'\n"})
            sites, _, _, _ = c._wide_reader_axis(tmp, workflows={})
            self.assertEqual({c.CH_LOCAL_RECORD, c.CH_STEP_LOG},
                             {s["channel"] for s in sites})

    def test_a_kind_with_no_population_is_unmeasured_and_not_clean(self):
        """Класс ``vacuous_guard_census``: нули на пустом населении fail-OPEN."""
        with tempfile.TemporaryDirectory() as tmp:
            _, scanned, _, kinds = c._wide_reader_axis(tmp, workflows={})
            self.assertEqual(set(c.WIDE_KINDS), set(kinds))
            for kind in c.WIDE_KINDS:
                self.assertEqual(0, scanned[kind])
                self.assertTrue(kinds[kind].strip(), kind)

    def test_a_missing_protocol_doc_is_an_unmeasured_site_with_its_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"CLAUDE.md": "`grep \" passed\" <лог>`\n"})
            _, scanned, site_unmeasured, _ = c._wide_reader_axis(tmp, workflows={})
            self.assertEqual(1, scanned[c.KIND_DOC])
            missing = {row["site"] for row in site_unmeasured}
            self.assertIn("docs/ORCHESTRATOR_PROTOCOL.md", missing)
            for row in site_unmeasured:
                self.assertTrue(row["reason"].strip(), row["site"])

    def test_an_unparsable_site_is_named_and_does_not_become_prose(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "def f(:\n    'ci_verdict'\n"})
            sites, _, site_unmeasured, kinds = c._wide_reader_axis(tmp, workflows={})
            self.assertEqual([c.EV_UNMEASURED], [s["evidence"] for s in sites])
            self.assertIn("a/x.py", [r["site"] for r in site_unmeasured])
            self.assertNotIn(c.KIND_CODE, kinds,
                             "одна неразобранная площадка не есть неизмеренный РОД")

    def test_every_declared_protocol_doc_entry_is_a_declared_choice(self):
        self.assertTrue(c.PROTOCOL_DOCS)
        self.assertTrue(c.PROTOCOL_DOC_GLOBS)
        for price in c.LOWER_BOUND_PRICES:
            self.assertTrue(price.strip())


class WideReportAndExitCode(unittest.TestCase):
    """Отчёт обязан печатать КАЖДЫЙ ноль, а «не измерено» — быть отличимым."""

    def _doc(self, tmp, steps=None):
        workflows = _wf(steps) if steps is not None else {}
        return c.measure(tmp, workflows=workflows)

    def test_every_kind_and_every_evidence_and_every_role_is_printed_at_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = c.format_report(self._doc(tmp))
            for name in c.WIDE_KINDS + c.WIDE_EVIDENCE + c.WIDE_ROLES:
                self.assertIn(name, report, name)

    def test_the_conclusion_says_lower_bound_even_with_nothing_found_outside(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "x = 1\n"})
            report = c.format_report(self._doc(tmp))
            self.assertIn("НЕ подтверждает ноль", report)

    def test_the_conclusion_calls_the_narrow_number_a_lower_bound_when_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "P = 'scripts/ci_verdict.py'\n"})
            report = c.format_report(self._doc(tmp))
            self.assertIn("НИЖНЯЯ ГРАНИЦА", report)
            self.assertIn("role_invokes_the_writer 1", report)

    def test_the_wide_axis_is_printed_even_when_the_writer_axis_is_unmeasured(self):
        """Молчание о второй оси читалось бы как её ноль: воркфлоу не разобраны,
        но дерево-то измерено, и у трёх родов ответ есть."""
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "P = 'scripts/ci_verdict.py'\n"})
            doc = c.measure(tmp)          # воркфлоу нет ⇒ ось писателя НЕ ИЗМЕРЕНА
            self.assertTrue(doc["unmeasured_reason"])
            self.assertEqual(c.KIND_WORKFLOW,
                             next(iter(k for k in doc["wide_kind_unmeasured"]
                                       if k == c.KIND_WORKFLOW)))
            report = c.format_report(doc)
            self.assertIn("ось ПИСАТЕЛЯ", report)
            self.assertIn("a/x.py", report)

    def test_the_exit_code_is_the_worse_of_the_two_axes(self):
        """Положительный контроль на проводку кода возврата: писательская ось
        в порядке, а род второй оси не измерен ⇒ успехом это быть не вправе."""
        import contextlib
        import io
        import yaml  # noqa: PLC0415 — тест-домен, не рантайм (инв. #4)
        with tempfile.TemporaryDirectory() as tmp:
            wf = {"jobs": {"test": {"steps": [
                {"name": "p", "run": "python3 -m pytest --junitxml=reports/j.xml"},
                {"name": "u", "uses": "actions/upload-artifact@v4",
                 "if": "!cancelled()", "with": {"path": "reports/"}}]}}}
            _tree(tmp, {".github/workflows/w.yml": yaml.safe_dump(wf)})
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = c.main(["--root", tmp])
            self.assertEqual("names_outlive_the_runner",
                             c.verdict(c.measure(tmp)),
                             "ось писателя обязана быть зелёной в этой сцене")
            self.assertEqual(2, rc, "неизмеренный РОД обязан быть отличим от успеха")
            self.assertIn("НЕ ИЗМЕРЕН РОД", buf.getvalue())

    def test_counts_of_the_wide_axis_sum_to_the_number_of_sites(self):
        doc = c.measure(_REPO_ROOT)
        total = sum(sum(row.values()) for row in doc["wide_counts"].values())
        self.assertEqual(len(doc["wide_sites"]), total)
        self.assertEqual(len(doc["wide_sites"]),
                         sum(c.wide_roles(doc["wide_sites"]).values()))


class RealTreeWideAxis(unittest.TestCase):
    """Предмет этих тестов — НАСТОЯЩЕЕ дерево, и это объявлено в имени класса."""

    def test_real_tree_the_human_protocol_reads_the_step_log(self):
        """Ответ заказа G106 п. 3 на этом дереве: читатель лога шага есть, и он
        ЧЕЛОВЕК в протоколе — то есть ровно то население, которого узкая ось не
        видит по построению."""
        doc = c.measure(_REPO_ROOT)
        reading = [s for s in doc["wide_sites"]
                   if s["channel"] == c.CH_STEP_LOG and s["role"] == c.ROLE_READS]
        self.assertTrue(reading, "в CLAUDE.md стои́т команда чтения лога джобы")
        self.assertIn(c.KIND_DOC, {s["kind"] for s in reading})

    def test_real_tree_the_only_narrow_step_log_reader_carries_its_mark_in_prose(self):
        """Обратная сторона того же замера: единственный «читатель» лога шага
        внутри узкого населения держит метку в КОММЕНТАРИИ, то есть узкая
        единица сама не доказана исполняемым текстом."""
        doc = c.measure(_REPO_ROOT)
        narrow = [r["reader"] for r in doc["readers"]
                  if r["channel"] == c.CH_STEP_LOG]
        self.assertTrue(narrow)
        for rel in narrow:
            executed, prose = c._python_text(
                open(os.path.join(_REPO_ROOT, rel), encoding="utf-8").read())
            self.assertEqual((), c._channels_in(executed), rel)
            self.assertTrue(c._channels_in(prose), rel)

    def test_real_tree_every_kind_has_a_population(self):
        doc = c.measure(_REPO_ROOT)
        self.assertEqual({}, doc["wide_kind_unmeasured"])
        for kind in c.WIDE_KINDS:
            self.assertGreater(doc["wide_scanned"][kind], 0, kind)


# ── ось ВОЗРАСТА записи (заказ G106 п. 1, ADR-651) ───────────────────────────
#
# Заказ запретил спрашивать настройку («поставить ли больше») и велел спросить
# СПРОС — у читателя. Поэтому у батареи две половины: предложение (срок у
# шага выгрузки, замером у воркфлоу) и спрос (какое ХРАНИЛИЩЕ читатель
# спрашивает). Третий исход у каждой половины свой, и подмена одного другим
# проверяется отдельным тестом: «возраст ноль» и «срока в дереве нет» — не
# одно и то же, хотя оба печатаются без большого числа.


def _ret(name, path, retention=None, cond="!cancelled()"):
    """Шаг выгрузки с объявленным (или НЕ объявленным) сроком."""
    step = {"name": name, "uses": "actions/upload-artifact@v4",
            "if": cond, "with": {"path": path}}
    if retention is not None:
        step["with"]["retention-days"] = retention
    return step


class RetentionIsMeasuredNotReprinted(unittest.TestCase):
    """Предложение: срок читается у ВОРКФЛОУ, и у него три исхода."""

    def _rows(self, steps):
        rows, counts = c._retention_axis(_wf(steps))
        return rows, counts

    def test_a_literal_retention_is_read_as_a_number(self):
        rows, counts = self._rows([_ret("u", "reports/", 14)])
        self.assertEqual(c.RET_DECLARED, rows[0]["outcome"])
        self.assertEqual(14, rows[0]["days"])
        self.assertEqual(1, counts[c.RET_DECLARED])

    def test_a_missing_retention_is_the_third_outcome_and_never_the_number_90(self):
        """Порванное звено: подставить умолчание GitHub (90 дн.) за замер.

        Настройки репозитория в дереве нет НИ ОДНОЙ строкой, поэтому «срок не
        объявлен» обязано быть отдельным значением, а не числом из памяти
        (инв. #17 и дословный урок `.claude/rules/site-numbers.md`).
        """
        rows, counts = self._rows([_ret("u", "reports/")])
        self.assertEqual(c.RET_NOT_DECLARED, rows[0]["outcome"])
        self.assertIsNone(rows[0]["days"])
        self.assertIn("РЕПОЗИТОРИЯ", rows[0]["why"])
        self.assertEqual(1, counts[c.RET_NOT_DECLARED])
        self.assertNotIn("90", rows[0]["why"])

    def test_an_expression_retention_is_unmeasured_not_a_number(self):
        rows, _ = self._rows([_ret("u", "reports/", "${{ env.KEEP }}")])
        self.assertEqual(c.RET_UNMEASURED, rows[0]["outcome"])
        self.assertIsNone(rows[0]["days"])
        self.assertIn("выражение", rows[0]["why"])

    def test_a_non_numeric_retention_is_unmeasured_and_the_axis_does_not_raise(self):
        rows, _ = self._rows([_ret("u", "reports/", "fourteen")])
        self.assertEqual(c.RET_UNMEASURED, rows[0]["outcome"])
        self.assertIn("не число", rows[0]["why"])

    def test_only_an_upload_that_covers_a_record_path_carries_the_record(self):
        """Порванное звено: считать несущим запись ЛЮБОЙ шаг выгрузки.

        Тогда срок у выгрузки чужого артефакта (отчёт свежести сайта) попал бы
        в сравнение со спросом на ЗАПИСЬ ИМЁН — сравнение разнородного.
        """
        rows, _ = self._rows([_step("p", run=PYTEST_WITH_JUNIT),
                              _ret("other", "data/site_freshness_report.json", 3),
                              _ret("records", "reports/", 14)])
        by_step = {row["step"]: row for row in rows}
        self.assertEqual([], by_step["other"]["carries_record"])
        self.assertEqual(["reports/junit-x.xml"],
                         by_step["records"]["carries_record"])

    def test_the_shortest_retention_is_taken_over_record_carrying_uploads_only(self):
        """Порванное звено: минимум по ВСЕМ выгрузкам.

        Сцена различающая: чужая выгрузка объявляет срок КОРОЧЕ (3 дн.), и
        наивный минимум доложил бы 3 вместо 14 — то есть сравнил бы спрос на
        запись имён со сроком чужого файла.
        """
        doc = c.measure(_REPO_ROOT, workflows=_wf(
            [_step("p", run=PYTEST_WITH_JUNIT),
             _ret("other", "data/x.json", 3),
             _ret("records", "reports/", 14)]))
        answer = c.age_answer(doc)
        self.assertEqual(14, answer["shortest_record_retention_days"])
        self.assertEqual(1, answer["record_carrying_uploads"])

    def test_an_undecidable_coverage_is_counted_and_not_called_carried(self):
        rows, _ = self._rows([_step("p", run=PYTEST_WITH_JUNIT),
                              _ret("u", "${{ env.DIR }}/reports", 14)])
        row = next(r for r in rows if r["step"] == "u")
        self.assertEqual([], row["carries_record"])
        self.assertEqual(1, row["coverage_undecided"])

    def test_a_record_carrying_upload_without_a_declared_term_is_named_as_supply_unmeasured(self):
        doc = c.measure(_REPO_ROOT, workflows=_wf(
            [_step("p", run=PYTEST_WITH_JUNIT), _ret("u", "reports/")]))
        answer = c.age_answer(doc)
        self.assertEqual(1, answer["supply_unmeasured"])
        self.assertIsNone(answer["shortest_record_retention_days"])
        self.assertIn("короткий срок НЕ ИЗМЕРЕН", c.format_report(doc))

    def test_the_codomain_of_coverage_is_exactly_three_values(self):
        """Почему мутант `covered is True` → `covered` ЭКВИВАЛЕНТЕН, а не выжил
        на дыре сцены.

        Замер мутаций цикла #807 оставил ровно одного «выжившего», и прежде чем
        называть его дырой, у функции спрошена ОБЛАСТЬ ЗНАЧЕНИЙ: она ровно
        ``{True, False, None}``. На таком множестве `x is True` и `x`
        различаются только если существует истинное значение, не равное
        ``True``, — а его нет, и теперь это ЗАКРЕПЛЕНО. Если область значений
        однажды расширится (скажем, числом совпавших путей), тест покраснеет
        первым, и форма `covered is True` вернёт свой смысл.
        """
        cases = [("reports/", "reports/j.xml"), ("reports/", "../reports/j.xml"),
                 ("reports/", "other/j.xml"), ("rep*/", "reports/j.xml"),
                 ("${{ e }}/r", "reports/j.xml"), ("reports/", "${{ e }}/j.xml"),
                 ("", "reports/j.xml"), ("reports/", "")]
        seen = {c._covers(up, rec) for up, rec in cases}
        self.assertEqual({True, False, None}, seen)
        for value in seen:
            self.assertIn(value, (True, False, None))

    def test_the_retention_outcomes_sum_to_the_number_of_upload_steps(self):
        rows, counts = self._rows([_ret("a", "reports/", 14), _ret("b", "x/"),
                                   _ret("c", "y/", "${{ e }}")])
        self.assertEqual(len(rows), sum(counts.values()))
        self.assertEqual(set(c.RETENTIONS), set(counts))


class AgeDemandIsMeasuredAtTheReader(unittest.TestCase):
    """Спрос: какое ХРАНИЛИЩЕ спрашивает читатель. Три исхода различимы."""

    def _rows(self, tmp, workflows=None):
        doc = c.measure(tmp, workflows=workflows if workflows is not None else {})
        return doc, {row["site"]: row for row in doc["age_demand_rows"]}

    def test_a_reader_handed_the_record_of_its_own_run_demands_age_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "P = '--junitxml'\n"})
            doc, by_site = self._rows(tmp)
            row = by_site["a/x.py"]
            self.assertEqual(c.DEMAND_LOCAL, row["demand"])
            self.assertEqual(c.STORE_LOCAL, row["store"])
            self.assertEqual(0, row["age_days"])

    def test_a_reader_of_the_run_log_has_NO_number_and_that_is_not_the_same_as_zero(self):
        """Порванное звено: склеить «возраст ноль» и «срока в дереве нет».

        Это ровно подмена, запрещённая инв. #17: первое ИЗМЕРЕНО и равно нулю,
        второе не измерено вовсе, и чинится оно в другом месте (настройка
        репозитория, а не `retention-days`).
        """
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "CMD = 'ci_verdict'\n",
                        "a/y.py": "P = '--junitxml'\n"})
            _doc, by_site = self._rows(tmp)
            log_row, own_row = by_site["a/x.py"], by_site["a/y.py"]
            self.assertEqual(c.DEMAND_RUN_LOG, log_row["demand"])
            self.assertIsNone(log_row["age_days"])
            self.assertIn("РЕПОЗИТОРИЯ", log_row["why"])
            self.assertEqual(0, own_row["age_days"])
            self.assertIsNot(log_row["age_days"], own_row["age_days"])

    def test_a_reader_of_the_api_conclusion_asks_the_run_log_store_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "URL = '/actions/runs?head_sha=x'\n"})
            _doc, by_site = self._rows(tmp)
            self.assertEqual(c.DEMAND_RUN_LOG, by_site["a/x.py"]["demand"])
            self.assertEqual(c.STORE_RUN_LOG, by_site["a/x.py"]["store"])

    def test_a_site_that_downloads_the_artifact_asks_the_artifact_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "CMD = 'gh run download 123'\nP = '--junitxml'\n"})
            _doc, by_site = self._rows(tmp)
            row = by_site["a/x.py"]
            self.assertEqual(c.DEMAND_ARTIFACT, row["demand"])
            self.assertEqual(c.STORE_ARTIFACT, row["store"])
            self.assertEqual(["gh run download"], row["fetch_marks"])

    def test_the_download_overrides_the_channel_because_only_it_is_governed_by_retention(self):
        """Порванное звено: решать спрос ТОЛЬКО по карте каналов.

        Файл, который и берёт `conclusion`, и тянет артефакт, по карте ушёл бы
        в `run_log_store` — и единственный спрос, который `retention-days`
        действительно связывает, стал бы невидим.
        """
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "U = '/actions/runs'\nC = 'gh run download'\n"})
            _doc, by_site = self._rows(tmp)
            self.assertEqual(c.DEMAND_ARTIFACT, by_site["a/x.py"]["demand"])

    def test_a_download_mark_in_a_comment_asks_nothing(self):
        """Порванное звено: суждение по ПОДСТРОКЕ. Проза ничего не скачивает."""
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "# когда-то звали gh run download\nP = '--junitxml'\n"})
            doc, by_site = self._rows(tmp)
            self.assertEqual(c.DEMAND_LOCAL, by_site["a/x.py"]["demand"])
            self.assertEqual(0, doc["age_demand_counts"][c.DEMAND_ARTIFACT])
            self.assertEqual([c.EV_PROSE],
                             [s["evidence"] for s in doc["fetch_sites"]])

    def test_a_prose_only_reader_site_is_excluded_from_the_population_and_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "# читает ci_verdict\nx = 1\n"})
            doc, by_site = self._rows(tmp)
            self.assertEqual({}, by_site)
            self.assertEqual(1, doc["age_excluded"]["prose_only"])

    def test_an_unparsed_reader_site_is_the_third_outcome_of_demand(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "def f(:\n    'ci_verdict'\n"})
            doc, by_site = self._rows(tmp)
            self.assertEqual(c.DEMAND_UNMEASURED, by_site["a/x.py"]["demand"])
            self.assertEqual(c.ANSWER_UNMEASURED, c.age_answer(doc)["label"])

    def test_the_demand_outcomes_sum_to_the_population(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "P = '--junitxml'\n",
                        "a/y.py": "C = 'ci_verdict'\n",
                        "a/z.py": "U = '/actions/runs'\n"})
            doc, _ = self._rows(tmp)
            self.assertEqual(len(doc["age_demand_rows"]),
                             sum(doc["age_demand_counts"].values()))
            self.assertEqual(set(c.DEMANDS), set(doc["age_demand_counts"]))

    def test_one_site_is_not_counted_twice_for_the_same_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "A = '--junitxml'\nB = '<testsuite'\n"})
            doc, _ = self._rows(tmp)
            self.assertEqual(1, len(doc["age_demand_rows"]))

    def test_the_fetch_axis_does_not_skip_the_narrow_population(self):
        """Выбор с причиной: скачивающий может жить и в узких каталогах, и ось
        читателей его бы не увидела — там он уже «пройден»."""
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"scripts/dl.py": "C = 'gh run download'\n"})
            sites, scanned, _ = c._fetch_axis(tmp, {})
            self.assertEqual(["scripts/dl.py"], [s["site"] for s in sites])
            self.assertEqual(1, scanned[c.KIND_CODE])

    def test_an_unreadable_fetch_site_is_named_and_does_not_vanish(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "def f(:\n    'gh run download'\n"})
            sites, _scanned, unmeasured = c._fetch_axis(tmp, {})
            self.assertEqual([c.EV_UNMEASURED], [s["evidence"] for s in sites])
            row = next(r for r in unmeasured if r["site"] == "a/x.py")
            self.assertIn("разобрать нечем", row["reason"])
            for other in unmeasured:
                self.assertTrue(other["reason"].strip(), other["site"])


class TheProducerOfTheRecordIsNotItsReader(unittest.TestCase):
    """Порванное звено: считать воркфлоу, ОБЪЯВИВШИЙ запись, её читателем."""

    def _doc(self, run, tmp):
        return c.measure(tmp, workflows=_wf([_step("p", run=run)]))

    def test_a_workflow_declaring_the_record_is_a_writer_and_leaves_the_population(self):
        """Сцена РАЗЛИЧАЮЩАЯ: без этой ветки воркфлоу попадал бы в спрос как
        читатель записи своего прогона, и население оси раздувалось бы ровно
        на производителей — то есть ноль спроса считался бы на неверном
        знаменателе."""
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc(PYTEST_WITH_JUNIT, tmp)
            self.assertEqual([], doc["age_demand_rows"])
            self.assertEqual(1, doc["age_excluded"]["writer_sites"])
            self.assertIn("воркфлоу-ПИСАТЕЛЕЙ записи 1", c.format_report(doc))

    def test_a_workflow_that_READS_a_ready_record_stays_in_the_population(self):
        """Обратная сторона: ``<testsuite`` есть чтение готовой записи, а не её
        объявление, и в перечень меток писателя он не входит НАМЕРЕННО. Без
        этого различения ветка исключения съела бы настоящего читателя."""
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._doc("grep '<testsuite' reports/j.xml", tmp)
            self.assertEqual([".github/workflows/w.yml"],
                             [row["site"] for row in doc["age_demand_rows"]])
            self.assertEqual(0, doc["age_excluded"]["writer_sites"])

    def test_the_same_mark_in_python_is_NOT_a_writer_exclusion(self):
        """Исключение привязано к РОДУ площадки, а не к метке: ``--junitxml`` в
        питоне есть чтение записи своего прогона (так читает настоящий
        `no_regression_census`), и вынести его значило бы потерять единственный
        измеренный спрос с нулевым возрастом."""
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "P = '--junitxml'\n"})
            doc = c.measure(tmp, workflows={})
            self.assertEqual([c.DEMAND_LOCAL],
                             [row["demand"] for row in doc["age_demand_rows"]])
            self.assertEqual(0, doc["age_excluded"]["writer_sites"])


class AgeAnswerAndExitCode(unittest.TestCase):
    """Вердикт оси, оба числа рядом и ХРАПОВИК на появление спроса."""

    def _main(self, tmp, steps):
        import contextlib
        import io
        import yaml  # noqa: PLC0415 — тест-домен, не рантайм (инв. #4)
        _tree(tmp, {".github/workflows/w.yml":
                    yaml.safe_dump({"jobs": {"test": {"steps": steps}}})})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = c.main(["--root", tmp])
        return rc, buf.getvalue()

    _GOOD = [{"name": "p", "run": PYTEST_WITH_JUNIT},
             {"name": "u", "uses": "actions/upload-artifact@v4",
              "if": "!cancelled()",
              "with": {"path": "reports/", "retention-days": 14}}]

    def test_nobody_asking_the_artifact_store_is_code_zero_and_the_setting_is_called_a_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"CLAUDE.md": "`grep \" passed\" <лог>`\n",
                        "docs/ORCHESTRATOR_PROTOCOL.md": "x\n",
                        ".claude/rules/r.md": "x\n", "a/t.sh": "echo ok\n",
                        "a/x.py": "P = '--junitxml'\n"})
            rc, out = self._main(tmp, self._GOOD)
            self.assertEqual(0, rc)
            self.assertIn(c.ANSWER_NOBODY,
                          [c.ANSWER_NOBODY])          # имя исхода объявлено
            self.assertIn("не связывает никого", out)
            self.assertIn("ИЗМЕРЕН и равен нулю", out)

    def test_the_first_downloader_makes_the_question_live_and_raises_the_code_to_one(self):
        """ХРАПОВИК: ноль спроса держится ровно до появления скачивающего.

        Сцена отличается от предыдущей ровно одним файлом — и этого обязано
        хватить, чтобы вердикт и код возврата сменились.
        """
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"CLAUDE.md": "x\n",
                        "docs/ORCHESTRATOR_PROTOCOL.md": "x\n",
                        ".claude/rules/r.md": "x\n", "a/t.sh": "echo ok\n",
                        "a/x.py": "P = '--junitxml'\n",
                        "a/dl.py": "C = 'gh run download'\nP = '<testsuite'\n"})
            rc, out = self._main(tmp, self._GOOD)
            self.assertEqual(1, rc)
            self.assertIn("спрашивают поимённо", out)
            self.assertIn("a/dl.py", out)

    def test_unmeasured_demand_is_code_two_and_never_reads_as_nobody(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"CLAUDE.md": "x\n",
                        "docs/ORCHESTRATOR_PROTOCOL.md": "x\n",
                        ".claude/rules/r.md": "x\n", "a/t.sh": "echo ok\n",
                        "a/x.py": "def f(:\n    'ci_verdict'\n"})
            rc, out = self._main(tmp, self._GOOD)
            self.assertEqual(2, rc)
            self.assertIn("ОТВЕТ ЗАКАЗА: НЕ ИЗМЕРЕНО", out)
            self.assertNotIn("не связывает никого", out)

    def test_an_empty_reader_population_is_unmeasured_and_not_nobody(self):
        """Класс `vacuous_guard_census`: «спроса нет» на пустом населении
        читалось бы как ответ, а он не измерялся."""
        with tempfile.TemporaryDirectory() as tmp:
            doc = c.measure(tmp, workflows=_wf(self._GOOD))
            self.assertEqual([], doc["age_demand_rows"])
            self.assertEqual(c.ANSWER_UNMEASURED, c.age_answer(doc)["label"])

    def test_the_report_prints_both_numbers_demand_and_supply(self):
        """Односторонний ответ: спрос без объявленного срока сравнивать не с чем."""
        doc = c.measure(_REPO_ROOT, workflows=_wf(self._GOOD))
        report = c.format_report(doc)
        for name in c.DEMANDS + c.RETENTIONS:
            self.assertIn(name, report, name)
        self.assertIn("несут запись имён", report)
        self.assertIn("короткий срок", report)

    def test_every_price_of_this_axis_is_declared_in_advance(self):
        self.assertTrue(c.AGE_PRICES)
        for price in c.AGE_PRICES:
            self.assertTrue(price.strip())

    def test_a_fetch_site_outside_the_reader_population_is_named_as_a_finding_about_the_population(self):
        """Площадка скачивает артефакт, но ни одна ось читателей её не видит:
        это находка о НАСЕЛЕНИИ, и молчать о ней значило бы выдать неполное
        население за полное."""
        with tempfile.TemporaryDirectory() as tmp:
            # `gh run download` содержит подстроку `gh run `, то есть МЕТКУ
            # канала `conclusion`, — такая площадка в население читателей
            # попадает сама. Различающая сцена поэтому берёт признак
            # скачивания, каналом не являющийся вовсе.
            _tree(tmp, {"a/dl.py": "U = '/actions/artifacts/12'\n"})
            doc = c.measure(tmp, workflows=_wf(self._GOOD))
            self.assertEqual(["a/dl.py"], doc["fetch_outside_population"])
            self.assertIn("ЧИТАТЕЛЕМ НЕ ЗОВЁТСЯ", c.format_report(doc))

    def test_the_age_axis_is_printed_even_when_the_workflows_are_unmeasured(self):
        """Молчание об оси читалось бы как её ноль. Предложение при этом честно
        пусто (сроки живут в воркфлоу), а спрос измерен — он про дерево."""
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"a/x.py": "P = '--junitxml'\n"})
            doc = c.measure(tmp)                   # воркфлоу нет вовсе
            self.assertTrue(doc["unmeasured_reason"])
            self.assertEqual(1, doc["age_demand_counts"][c.DEMAND_LOCAL])
            self.assertEqual([], doc["retention_rows"])
            report = c.format_report(doc)
            self.assertIn("ось ВОЗРАСТА записи", report)


class ProtocolDocListHasOneHome(unittest.TestCase):
    """Правило населения документов — ОДНА копия на обе оси (класс «два дома»)."""

    def test_both_axes_see_the_same_protocol_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            _tree(tmp, {"CLAUDE.md": "`gh run download 1` и `grep \" passed\" <лог>`\n",
                        "docs/ORCHESTRATOR_PROTOCOL.md": "x\n",
                        ".claude/rules/a.md": "x\n",
                        ".claude/rules/b.md": "x\n"})
            _s, wide_scanned, _u, _k = c._wide_reader_axis(tmp, workflows={})
            _s2, fetch_scanned, _u2 = c._fetch_axis(tmp, {})
            self.assertEqual(4, wide_scanned[c.KIND_DOC])
            self.assertEqual(wide_scanned[c.KIND_DOC], fetch_scanned[c.KIND_DOC])

    def test_a_missing_glob_directory_is_the_third_outcome_not_an_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            unmeasured: list[dict] = []
            docs = c._protocol_docs(tmp, unmeasured)
            self.assertEqual(list(c.PROTOCOL_DOCS), docs)
            self.assertEqual([p for p in c.PROTOCOL_DOC_GLOBS],
                             [r["site"] for r in unmeasured])
            for row in unmeasured:
                self.assertTrue(row["reason"].strip())


class RealTreeAgeAxis(unittest.TestCase):
    """Предмет — НАСТОЯЩЕЕ дерево; ответ заказа G106 п. 1 на нём."""

    def setUp(self):
        self.doc = c.measure(_REPO_ROOT)
        self.answer = c.age_answer(self.doc)

    def test_real_tree_no_code_here_asks_the_artifact_store(self):
        """Ответ замера: срок выгрузки не связывает НИ ОДНОГО читателя дерева.

        Храповик в обе стороны: появится скачивающий — тест покраснеет и вопрос
        «достаточно ли срока» станет живым, как и требует заказ.
        """
        self.assertEqual(0, self.doc["age_demand_counts"][c.DEMAND_ARTIFACT],
                         f"скачивают: {self.answer['asking_sites']}")
        self.assertEqual(c.ANSWER_NOBODY, self.answer["label"])

    def test_real_tree_every_record_carrying_upload_declares_its_term(self):
        self.assertEqual(0, self.answer["supply_unmeasured"])
        self.assertTrue(self.answer["record_carrying_uploads"])
        self.assertIsInstance(self.answer["shortest_record_retention_days"], int)

    def test_real_tree_the_demand_is_not_an_empty_population(self):
        self.assertTrue(self.doc["age_demand_rows"])
        self.assertEqual(len(self.doc["age_demand_rows"]),
                         sum(self.doc["age_demand_counts"].values()))

    def test_real_tree_someone_does_ask_the_run_log_store_whose_term_is_not_in_the_tree(self):
        """Вторая половина ответа: спрос на запись СТАРШЕ своего прогона есть, и
        хранилище у него другое — лог прогона, чей срок в дереве не объявлен."""
        self.assertTrue(self.doc["age_demand_counts"][c.DEMAND_RUN_LOG])
        self.assertIn(c.RUN_LOG_WHY, c.format_report(self.doc))

    def test_real_tree_the_fetch_axis_scanned_more_than_the_reader_axis(self):
        """Население оси скачивания ШИРЕ по построению (узкие каталоги она не
        пропускает) — и это число, а не обещание."""
        self.assertGreater(self.doc["fetch_scanned"][c.KIND_CODE],
                           self.doc["wide_scanned"][c.KIND_CODE])
