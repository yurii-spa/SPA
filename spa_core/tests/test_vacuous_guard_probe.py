"""Зонд вырожденности: сторож прибора, у каждой проверки обратная сторона.

Заказ **G44 п. 1** приказа владельца «Portfolio CIO», решение — ADR-420.

**Главная сцена — НАСТОЯЩИЙ контур:** крошечный git-репозиторий с четырьмя
сторожами, по которому зонд гоняет настоящий pytest в настоящем одноразовом
дереве. Каждый сторож — положительный контроль своего исхода:

* читает перечень и с пустым перечнем зеленеет ⇒ `vacuous_pass` (ВРЕД);
* считает длину перечня ⇒ `refuses_empty`, и упавший тест НАЗВАН;
* краснота приходит от СОСЕДА ⇒ `refuses_empty` у зонда, но перепись назовёт
  это `refuses_elsewhere` (зонд имена пишет, приписывает перепись);
* красен на базе ⇒ `unmeasured` — третий исход, не вердикт.

Опасная ошибка здесь одна: назвать сторожа исправным. Поэтому каждая сцена
идёт с обратной, а предпосылки опыта (перемена применилась, дерево
восстановлено, pytest вообще собрал тесты) проверяются, а не считаются.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spa_core.monitoring import copy_independence_probe as base
from spa_core.monitoring import vacuous_guard_census as vgc
from spa_core.monitoring import vacuous_guard_probe as probe

#: Неподвижные часы: прибор берёт их параметром.
# FROZEN-DATE-OK: injected-clock — час передаётся в measure/run параметром now=
_NOW = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)

_GUARDS = {
    "test_vacuous.py": (
        "from pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parent.parent\n"
        "SCAN_DIRS = ('pkg_a', 'pkg_b')\n"
        "def test_scan():\n"
        "    offenders = []\n"
        "    for d in SCAN_DIRS:\n"
        "        base_dir = ROOT / d\n"
        "        if not base_dir.exists():\n"
        "            continue\n"
        "        offenders.extend(str(p) for p in base_dir.rglob('*.bad'))\n"
        "    assert not offenders\n"),
    "test_strict.py": (
        "NAMES = ('x', 'y')\n"
        "def test_all_present():\n"
        "    assert len(NAMES) == 2\n"),
    "test_neighbour.py": (
        "NAMES = ('x', 'y')\n"
        "DERIVED = [n.upper() for n in NAMES]\n"
        "def test_consumer():\n"
        "    for n in NAMES:\n"
        "        assert isinstance(n, str)\n"
        "def test_neighbour_counts():\n"
        "    assert len(DERIVED) == 2\n"),
    "test_red.py": (
        "ITEMS = ('a', 'b')\n"
        "def test_always_red():\n"
        "    assert list(ITEMS) == ['nope']\n"),
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


def _build_contour(repo: Path) -> None:
    (repo / "tests").mkdir(parents=True)
    for name, src in _GUARDS.items():
        (repo / "tests" / name).write_text(src, encoding="utf-8")
    _git(repo, "init", "-q", ".")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=probe@spa", "-c", "user.name=probe",
         "commit", "-qm", "contour")


class TheFailedTestNamesAreReadNotInvented(unittest.TestCase):
    def test_only_the_short_summary_lines_are_read(self):
        out = ("FAILED tests/t.py::test_a - AssertionError: boom\n"
               "FAILED tests/t.py::test_b\n"
               "1 failed, 2 passed\n"
               "passed tests/t.py::test_c\n")
        self.assertEqual(probe.failed_tests(out),
                         ["tests/t.py::test_a", "tests/t.py::test_b"])

    def test_an_output_without_a_summary_yields_nothing(self):
        """ОБРАТНАЯ СТОРОНА: выдуманное имя хуже отсутствующего."""
        self.assertEqual(probe.failed_tests("1 failed in 0.1s"), [])
        self.assertEqual(probe.failed_tests(""), [])


class AGuardThatRanNothingIsNotAVacuousGuard(unittest.TestCase):
    """Ошибка в ОПАСНУЮ сторону: файл со всеми пропущенными тестами зелен всегда."""

    def test_the_passed_count_is_read_from_the_summary(self):
        self.assertEqual(probe.passed_count("3 passed, 1 skipped in 0.2s"), 3)
        self.assertEqual(probe.passed_count("1 skipped in 0.1s"), 0,
                         "сводка есть, «passed» в ней нет ⇒ прошло НОЛЬ")
        self.assertEqual(probe.passed_count("no tests ran in 0.01s"), 0)

    def test_a_missing_summary_is_the_third_outcome_not_a_zero(self):
        """ОБРАТНАЯ СТОРОНА: ноль вместо «не разобрано» снял бы сторожа с учёта."""
        self.assertIsNone(probe.passed_count("что-то совсем другое"))
        self.assertIsNone(probe.passed_count(""))

    def test_the_word_passed_outside_the_summary_is_not_counted(self):
        """`FAILED …::test_passed_records` не есть «прошло 0 тестов»."""
        out = ("FAILED tests/t.py::test_passed_records - boom\n"
               "1 failed, 4 passed in 0.3s\n")
        self.assertEqual(probe.passed_count(out), 4)

    def test_a_fully_skipped_guard_is_unmeasured_not_vacuous(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _build_contour(repo)
            (repo / "tests" / "test_skipped.py").write_text(
                "import pytest\n"
                "DIRS = ('a', 'b')\n"
                "@pytest.mark.skip(reason='чужая среда')\n"
                "def test_scan():\n"
                "    for d in DIRS:\n"
                "        assert d\n", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, "-c", "user.email=probe@spa", "-c", "user.name=probe",
                 "commit", "-qm", "skipped guard")
            rows = vgc.measure(repo, now=_NOW)["rows"]
            row = [r for r in rows if r["guard"].endswith("test_skipped.py")][0]
            doc = probe.measure(repo, now=_NOW, rows=[row], everything=True)
        entry = doc["entries"][0]
        self.assertEqual(entry["verdict"], probe.VERDICT_UNMEASURED)
        self.assertEqual(entry["baseline_passed"], 0)
        self.assertIn("НИ ОДНОГО теста", entry["evidence"])

    def test_a_guard_that_DID_run_keeps_its_verdict(self):
        """ОБРАТНАЯ СТОРОНА: иначе проверка сняла бы с учёта весь класс."""
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _build_contour(repo)
            rows = vgc.measure(repo, now=_NOW)["rows"]
            row = [r for r in rows if r["guard"].endswith("test_vacuous.py")][0]
            doc = probe.measure(repo, now=_NOW, rows=[row], everything=True)
        self.assertEqual(doc["entries"][0]["verdict"], probe.VERDICT_VACUOUS)
        self.assertEqual(doc["entries"][0]["baseline_passed"], 1)


class TheSampleRuleIsPartOfTheMeasurement(unittest.TestCase):
    ROWS = [{"key": f"g{i}|N", "empty_without_edit":
             vgc.EMPTY_REACHABLE if i < 3 else vgc.EMPTY_EDIT} for i in range(30)]

    def test_every_reachable_row_is_always_probed(self):
        chosen = probe.select(self.ROWS, sample=5)
        reachable = [r for r in chosen
                     if r["empty_without_edit"] == vgc.EMPTY_REACHABLE]
        self.assertEqual(len(reachable), 3, "опасный подкласс берётся ЦЕЛИКОМ")
        self.assertEqual(len(chosen), 8)

    def test_the_draw_is_reproducible_by_its_named_seed(self):
        first = [r["key"] for r in probe.select(self.ROWS, sample=5)]
        again = [r["key"] for r in probe.select(self.ROWS, sample=5)]
        self.assertEqual(first, again)
        other = [r["key"] for r in probe.select(self.ROWS, sample=5, seed=7)]
        self.assertNotEqual(first, other, "зерно обязано что-то решать")

    def test_everything_takes_the_whole_population(self):
        self.assertEqual(len(probe.select(self.ROWS, everything=True)),
                         len(self.ROWS))

    def test_a_sample_larger_than_the_rest_is_not_an_error(self):
        self.assertEqual(len(probe.select(self.ROWS, sample=999)), len(self.ROWS))


class LiveContourEachVerdictHasItsPositiveControl(unittest.TestCase):
    """Настоящий pytest в настоящем одноразовом дереве. Медленно — цена правды."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = TemporaryDirectory()
        repo = Path(cls._tmp.name) / "repo"
        repo.mkdir()
        _build_contour(repo)
        cls.repo = repo
        cls.doc = probe.measure(repo, now=_NOW, everything=True)
        cls.by_guard = {Path(e["guard"]).name: e for e in cls.doc["entries"]}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_a_guard_green_on_an_emptied_list_is_named_vacuous(self):
        entry = self.by_guard["test_vacuous.py"]
        self.assertEqual(entry["verdict"], probe.VERDICT_VACUOUS, entry["evidence"])
        self.assertEqual(entry["empty_code"], 0)
        self.assertEqual(entry["empty_literal"], "()")

    def test_a_guard_that_counts_its_list_refuses_the_emptiness(self):
        """ОБРАТНАЯ СТОРОНА вырожденности: иначе вердикт стоял бы у всех."""
        entry = self.by_guard["test_strict.py"]
        self.assertEqual(entry["verdict"], probe.VERDICT_REFUSES, entry["evidence"])
        self.assertEqual(entry["failed_tests"],
                         ["tests/test_strict.py::test_all_present"])

    def test_the_names_of_the_fallen_are_recorded_for_the_census(self):
        """Приписывание — дело переписи; зонд обязан дать ей ИМЕНА."""
        entry = self.by_guard["test_neighbour.py"]
        self.assertEqual(entry["verdict"], probe.VERDICT_REFUSES)
        self.assertEqual(entry["failed_tests"],
                         ["tests/test_neighbour.py::test_neighbour_counts"])

    def test_a_guard_red_at_baseline_is_unmeasured_not_a_verdict(self):
        entry = self.by_guard["test_red.py"]
        self.assertEqual(entry["verdict"], probe.VERDICT_UNMEASURED)
        self.assertIn("НЕ зелен на базе", entry["evidence"])

    def test_the_working_tree_is_untouched_and_the_disposable_one_is_gone(self):
        """СВОЙ контур намеренно: сосед по классу пишет в общий журнал зонда,
        и «дерево чисто» тогда мерило бы порядок тестов, а не поведение зонда."""
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _build_contour(repo)
            probe.measure(repo, now=_NOW, everything=True)
            out = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo),
                                 capture_output=True, text=True)
            self.assertEqual(out.stdout.strip(), "")
            trees = subprocess.run(["git", "worktree", "list"], cwd=str(repo),
                                   capture_output=True, text=True).stdout
            self.assertNotIn(probe.TREE_PREFIX, trees)

    def test_every_outcome_carries_its_reason(self):
        for entry in self.doc["entries"]:
            self.assertIn(entry["verdict"],
                          (probe.VERDICT_VACUOUS, probe.VERDICT_REFUSES,
                           probe.VERDICT_UNMEASURED))
            self.assertTrue(entry["evidence"], "исход без основания — не исход")

    def test_the_census_turns_the_recorded_names_into_ATTRIBUTION(self):
        """Сквозная сцена: зонд → журнал → перепись. Ради неё всё и строилось."""
        ledger = self.repo / vgc.PROBE_LEDGER
        ledger.parent.mkdir(parents=True, exist_ok=True)
        probe.run(self.repo, dest=ledger, everything=True, now=_NOW)
        doc = vgc.measure(self.repo, now=_NOW)
        by_key = {r["key"]: r for r in doc["rows"]}
        self.assertEqual(by_key["tests/test_vacuous.py|SCAN_DIRS"]["verdict"],
                         vgc.VERDICT_VACUOUS)
        self.assertEqual(by_key["tests/test_strict.py|NAMES"]["verdict"],
                         vgc.VERDICT_REFUSES)
        self.assertEqual(by_key["tests/test_neighbour.py|NAMES"]["verdict"],
                         vgc.VERDICT_ELSEWHERE,
                         "упал сосед — потребитель перечня остался вырожденным")
        self.assertEqual(by_key["tests/test_red.py|ITEMS"]["verdict"],
                         vgc.VERDICT_UNMEASURED)
        self.assertEqual(doc["status"], "CRITICAL")


class TheExperimentRefusesWhenItsOwnPREMISEFails(unittest.TestCase):
    """Непоставленный опыт обязан отказать, а не выдать «зелено»."""

    def _repo(self, tmp: str) -> Path:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        _build_contour(repo)
        return repo

    def _row(self, repo: Path, guard: str, name: str) -> dict:
        rows = vgc.measure(repo, now=_NOW)["rows"]
        return [r for r in rows if r["guard"].endswith(guard) and r["name"] == name][0]

    def test_a_mutation_that_did_not_apply_is_unmeasured_not_green(self):
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            row = self._row(repo, "test_vacuous.py", "SCAN_DIRS")
            with mock.patch.object(base, "replace_constant",
                                   side_effect=lambda src, *a, **k: src):
                doc = probe.measure(repo, now=_NOW, rows=[row], everything=True)
        entry = doc["entries"][0]
        self.assertEqual(entry["verdict"], probe.VERDICT_UNMEASURED)
        self.assertIn("не применилось", entry["evidence"])

    def test_a_tree_that_did_not_restore_is_a_loud_refusal(self):
        """Недостоверны становятся ВСЕ дальнейшие опыты — значит, стоп."""
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            row = self._row(repo, "test_vacuous.py", "SCAN_DIRS")
            with mock.patch.object(base, "sha256", side_effect=["a", "b"]):
                out = probe.run(repo, write=False, rows=[row], everything=True)
        self.assertEqual(out["doc"]["status"], "UNMEASURED")
        self.assertIn("не восстановлено", out["doc"]["reason"])

    def test_collecting_nothing_is_unmeasured_not_vacuous(self):
        """Код 5 — «не собрано ни одного теста». Это НЕ зелено."""
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            row = self._row(repo, "test_vacuous.py", "SCAN_DIRS")
            with mock.patch.object(probe, "run_guard",
                                   side_effect=[(0, ""), (5, "no tests ran")]):
                doc = probe.measure(repo, now=_NOW, rows=[row], everything=True)
        entry = doc["entries"][0]
        self.assertEqual(entry["verdict"], probe.VERDICT_UNMEASURED)
        self.assertIn("не собрано ни одного теста", entry["evidence"])

    def test_a_baseline_that_ran_out_of_time_is_not_called_red(self):
        """Срок — не краснота: о не уложившемся прогоне сказать нечего."""
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            row = self._row(repo, "test_vacuous.py", "SCAN_DIRS")
            with mock.patch.object(probe, "run_guard",
                                   return_value=(-1, "прогон не уложился в 420 с")):
                doc = probe.measure(repo, now=_NOW, rows=[row], everything=True)
        entry = doc["entries"][0]
        self.assertEqual(entry["verdict"], probe.VERDICT_UNMEASURED)
        self.assertIn("не уложился", entry["evidence"])
        self.assertNotIn("НЕ зелен", entry["evidence"])

    def test_a_guard_edited_in_the_working_tree_is_not_measured_by_proxy(self):
        """Одноразовое дерево несёт HEAD — то есть НЕ правленого сторожа."""
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            row = self._row(repo, "test_vacuous.py", "SCAN_DIRS")
            (repo / "tests" / "test_vacuous.py").write_text(
                _GUARDS["test_vacuous.py"] + "\n# правка\n", encoding="utf-8")
            doc = probe.measure(repo, now=_NOW, rows=[row], everything=True)
        entry = doc["entries"][0]
        self.assertEqual(entry["verdict"], probe.VERDICT_UNMEASURED)
        self.assertIn("изменён в рабочем дереве", entry["evidence"])

    def test_a_value_with_no_empty_of_its_kind_is_refused_before_any_run(self):
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            row = dict(self._row(repo, "test_vacuous.py", "SCAN_DIRS"),
                       value="42", empty_literal=None)
            doc = probe.measure(repo, now=_NOW, rows=[row], everything=True)
        self.assertEqual(doc["entries"][0]["verdict"], probe.VERDICT_UNMEASURED)
        self.assertIn("пустого литерала того же рода не получить",
                      doc["entries"][0]["evidence"])


class ALeftoverDisposableTreeIsNamedByITSOwnPrefix(unittest.TestCase):
    """Зонд, ищущий ЧУЖОЙ префикс, свои брошенные деревья не увидит никогда."""

    def test_the_probe_names_a_tree_of_its_own_prefix(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _build_contour(repo)
            left = Path(tmp) / (probe.TREE_PREFIX + "leftover")
            _git(repo, "worktree", "add", "--detach", str(left), "HEAD")
            named = base.stale_disposable_trees(repo, prefix=probe.TREE_PREFIX)
            self.assertEqual([Path(p).name for p in named], [left.name])
            row = vgc.measure(repo, now=_NOW)["rows"][0]
            doc = probe.measure(repo, now=_NOW, rows=[row], everything=True)
            self.assertEqual(len(doc["stale_disposable_trees"]), 1)
            self.assertTrue(left.is_dir(), "чужой опыт зонд не снимает")

    def test_the_neighbours_prefix_does_not_name_our_tree(self):
        """ОБРАТНАЯ СТОРОНА: умолчание соседа назвало бы ноль — и молча."""
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _build_contour(repo)
            left = Path(tmp) / (probe.TREE_PREFIX + "leftover")
            _git(repo, "worktree", "add", "--detach", str(left), "HEAD")
            self.assertEqual(base.stale_disposable_trees(repo), [],
                             "префикс соседа наши деревья не называет")


class TheReportAndTheExitCodeSayTheSameThing(unittest.TestCase):
    def test_a_refusal_prints_the_reason_and_exits_two(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(probe.main(["--root", str(Path(tmp) / "nope"),
                                         "--no-write"]), 2)

    def test_the_report_names_the_sample_rule_and_the_disposable_tree(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _build_contour(repo)
            row = vgc.measure(repo, now=_NOW)["rows"][0]
            doc = probe.measure(repo, now=_NOW, rows=[row], everything=True)
        text = "\n".join(probe.report(doc))
        self.assertIn("[ВЫБОРКА]", text)
        self.assertIn("[ДЕРЕВО ОПЫТА]", text)
        self.assertTrue(doc["what_it_does_not_prove"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TheTimeoutPathSurvivesAStdlibShadow(unittest.TestCase):
    """Разз­атенение stdlib у входа, запускаемого ПО ПУТИ (цикл #638).

    Класс найден не рассуждением, а АВАРИЕЙ собственного прогона: зонд умер на
    52-й строке из 100, журнал не записан. Причина — `sys.path[0]` у запуска по
    пути есть каталог скрипта, а в `spa_core/monitoring/` живёт свой
    `signal.py` (RTMR, ADR-053). `subprocess.run(..., timeout=)` по
    срабатыванию срока зовёт `process.kill()` → `signal.SIGKILL`, и вместо
    третьего исхода «не уложился в срок» приходит `AttributeError`.

    Опасная форма здесь именно эта: ломается ПУТЬ ОТКАЗА, а не путь успеха.
    Пока ни один прогон не упирался в срок, фитиль не виден ничем.
    """

    @staticmethod
    def _unshadow_source() -> str:
        """Строки раззатенения, ВЫРЕЗАННЫЕ ИЗ МОДУЛЯ, а не переписанные сюда.

        Выжившие мутации батареи цикла #638: подмена `realpath` на `abspath`
        и порча `_HERE` в САМОМ модуле оставляли весь набор зелёным — сцена
        несла СВОЮ копию правила и проверяла копию, а не починку. Это ровно
        класс «одно правило — две копии» (ADR-417/418), и опаснее он тем, что
        вторая копия живёт у сторожа: правка модуля не двигает вердикт вовсе.

        Теперь сцена берёт настоящие строки по координате AST: от присваивания
        `_HERE` до присваивания `sys.path[:]` включительно. Испортишь модуль —
        испортится сцена, и авария вернётся.
        """
        import ast as _ast
        source = Path(probe.__file__).resolve().read_text(encoding="utf-8")
        tree = _ast.parse(source)
        first = last = None
        for node in tree.body:
            if isinstance(node, _ast.Assign) and any(
                    isinstance(t, _ast.Name) and t.id == "_HERE"
                    for t in node.targets):
                first = node.lineno
            if isinstance(node, _ast.Assign) and any(
                    isinstance(t, _ast.Subscript)
                    and isinstance(t.value, _ast.Attribute)
                    and t.value.attr == "path"
                    and isinstance(t.value.value, _ast.Name)
                    and t.value.value.id == "sys"
                    for t in node.targets):
                last = node.end_lineno or node.lineno
        if first is None or last is None or last < first:
            raise AssertionError(
                "в модуле нет блока раззатенения `_HERE` → `sys.path[:]` — "
                "вырезать нечего, и сцена НЕ имеет права подставить свою копию")
        lines = source.splitlines(keepends=True)[first - 1:last]
        return "import os, sys\n" + "".join(lines)

    _BODY = (
        "import subprocess, sys\n"
        "try:\n"
        "    subprocess.run([sys.executable, '-c', 'import time; time.sleep(30)'],\n"
        "                   timeout=1)\n"
        "    print('NO_TIMEOUT')\n"
        "except subprocess.TimeoutExpired:\n"
        "    print('TIMEOUT_REACHED')\n"
        "except AttributeError as exc:\n"
        "    print('CRASHED:' + str(exc)[:40])\n")

    def _scene(self, tmp: Path, *, unshadow: bool) -> str:
        """Каталог с ЗАТЕНЯЮЩИМ `signal.py` и скриптом, зовомым ПО ПУТИ."""
        (tmp / "signal.py").write_text("SEVERITIES = ('info',)\n", encoding="utf-8")
        script = tmp / "runner.py"
        script.write_text((self._unshadow_source() if unshadow else "") + self._BODY,
                          encoding="utf-8")
        proc = subprocess.run([__import__("sys").executable, str(script)],
                              capture_output=True, text=True, timeout=120)
        return (proc.stdout + proc.stderr).strip()

    def test_without_the_fix_the_REFUSAL_path_crashes(self):
        """Обратная сторона: без раззатенения срок ломает прибор, а не мерит."""
        with TemporaryDirectory() as td:
            out = self._scene(Path(td), unshadow=False)
        self.assertIn("CRASHED:", out, out)
        self.assertNotIn("TIMEOUT_REACHED", out, out)

    def test_with_the_fix_the_timeout_becomes_the_THIRD_outcome(self):
        with TemporaryDirectory() as td:
            out = self._scene(Path(td), unshadow=True)
        self.assertIn("TIMEOUT_REACHED", out, out)

    def test_the_shadow_is_REAL_in_this_repository_not_hypothetical(self):
        """Сцена не выдумана: затеняющий модуль лежит рядом с зондом."""
        shadow = Path(probe.__file__).resolve().parent / "signal.py"
        self.assertTrue(shadow.is_file(),
                        "сцена описывает затенение, которого в дереве нет — "
                        "контроль стал бы украшением")

    def test_the_entry_unshadows_BEFORE_it_imports_anything_that_pulls_signal(self):
        """Проводка мерится КООРДИНАТОЙ, а не подстрокой.

        Раззатенение обязано стоять ВЫШЕ первого ввоза, способного втянуть
        `subprocess` (а с ним и `signal`). Проверка по номеру строки узла AST:
        совпадение текста пережило бы перенос строк вниз, то есть пережило бы
        ровно ту поломку, ради которой написано.
        """
        import ast as _ast
        source = Path(probe.__file__).resolve().read_text(encoding="utf-8")
        tree = _ast.parse(source)
        unshadow_line = None
        for node in tree.body:
            if isinstance(node, _ast.Assign) and any(
                    isinstance(t, _ast.Subscript)
                    and isinstance(t.value, _ast.Attribute)
                    and t.value.attr == "path"
                    and isinstance(t.value.value, _ast.Name)
                    and t.value.value.id == "sys"
                    for t in node.targets):
                unshadow_line = node.lineno
                break
        self.assertIsNotNone(
            unshadow_line, "у входа нет присваивания `sys.path[:]` — "
                           "раззатенения нет вовсе")
        allowed = {"os", "sys", "__future__"}
        first_risky = None
        for node in tree.body:
            if isinstance(node, _ast.Import):
                names = {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, _ast.ImportFrom):
                names = {(node.module or "").split(".")[0]}
            else:
                continue
            if names - allowed:
                first_risky = node.lineno
                break
        self.assertIsNotNone(first_risky, "у входа нет ни одного ввоза — "
                                          "сцена описывает не тот файл")
        self.assertLess(
            unshadow_line, first_risky,
            f"раззатенение на строке {unshadow_line} стои́т НИЖЕ первого ввоза "
            f"(строка {first_risky}) — к этому моменту `signal` уже затенён")


class TheDECLAREDSampleRuleIsPinnedToWhatTheDecisionClaims(unittest.TestCase):
    """Выжившие батареи #638: `SAMPLE_SEED` и `DEFAULT_SAMPLE` не пинил никто.

    Оба числа объявлены в ADR-420 как ЧАСТЬ замера («все строки с достижимой
    пустотой + выборка 70, зерно 20260919»). Не закреплённые, они уезжают
    молча, и тогда решение продолжает утверждать про выборку то, чего больше
    нет: врёт не код, а ДОКУМЕНТ — и врёт беззвучно.

    Обратная сторона названа: тест НЕ утверждает, что именно эти числа верны.
    Он утверждает, что изменить их нельзя, не тронув решение, которое их
    объявило.
    """

    def test_the_seed_is_the_one_the_decision_names(self):
        self.assertEqual(probe.SAMPLE_SEED, 20260919)

    def test_the_default_sample_is_the_one_the_decision_names(self):
        self.assertEqual(probe.DEFAULT_SAMPLE, 70)

    def test_the_constants_are_the_DEFAULTS_that_reach_the_sample_rule(self):
        """Объявленное число обязано быть тем, которое реально применяется.

        `sample_rule` строится из АРГУМЕНТОВ `select`/`measure`; закрепить
        константы и не закрепить умолчания значило бы закрепить надпись, а не
        поведение.
        """
        import inspect
        params = inspect.signature(probe.select).parameters
        self.assertEqual(params["seed"].default, probe.SAMPLE_SEED)
        self.assertEqual(params["sample"].default, probe.DEFAULT_SAMPLE)

    def test_the_report_SAYS_the_rule_it_used(self):
        """Правило выборки, не названное в отчёте, читателю недоступно."""
        rule = (f"все строки с достижимой пустотой + случайная выборка "
                f"{probe.DEFAULT_SAMPLE} из остальных, зерно {probe.SAMPLE_SEED}")
        doc = {"status": "MEASURED", "probed": 1, "population": 1,
               "counts": {probe.VERDICT_VACUOUS: 0, probe.VERDICT_REFUSES: 1,
                          probe.VERDICT_UNMEASURED: 0},
               "sample_rule": rule, "sample_seed": probe.SAMPLE_SEED,
               "tree_sha": "deadbeefcafe", "entries": []}
        text = "\n".join(probe.report(doc))
        self.assertIn(str(probe.SAMPLE_SEED), text,
                      "зерно не названо — выборку нельзя воспроизвести")
        self.assertIn("достижимой пустотой", text,
                      "правило выборки не названо — читатель не знает, "
                      "что подкласс взят ЦЕЛИКОМ, а не случайно")


class TheExitCodeKeepsTheThreeOutcomesApart(unittest.TestCase):
    """Код возврата — то место, где различие читает ЗОВУЩИЙ скрипт (инв. #17).

    До цикла #642 `main()` читал `doc.get("counts") or {}`: поля нет ⇒ пусто ⇒
    ложь ⇒ код 0. «Поля нет» и «находок ноль» выходили одним и тем же успехом, и
    зовущему различить их было нечем. Контроль здесь в ОБЕ стороны: полный
    артефакт с нулём обязан дать 0, урезанный — 2 с названным полем.
    """

    def _main_with(self, doc: dict):
        import contextlib
        import io
        for name, stub in (("run", lambda *a, **k: {"doc": doc, "path": None}),
                           ("report", lambda *a, **k: [])):
            original = getattr(probe, name)
            setattr(probe, name, stub)
            self.addCleanup(lambda n=name, o=original: setattr(probe, n, o))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = probe.main(["--no-write"])
        return code, buf.getvalue()

    def test_a_complete_artifact_with_zero_findings_exits_clean(self):
        code, _ = self._main_with({"status": "MEASURED", "counts": {probe.VERDICT_VACUOUS: 0, probe.VERDICT_UNMEASURED: 0}})
        self.assertEqual(code, 0, "измеренный ноль обязан выходить нулём")

    def test_an_artifact_without_counts_is_not_measured_and_never_exits_clean(self):
        code, out = self._main_with({"status": "MEASURED"})
        self.assertEqual(code, 2, "отсутствие наблюдения кодом 0 не выдаётся")
        self.assertIn("НЕ ИЗМЕРЕНО", out)
        self.assertIn("counts", out, "пропавшее поле обязано быть НАЗВАНО")

    def test_counts_of_the_wrong_kind_is_absence_not_an_empty_tally(self):
        code, out = self._main_with({"status": "MEASURED", "counts": "ноль"})
        self.assertEqual(code, 2, "мусор в поле замером не является")
        self.assertIn("НЕ ИЗМЕРЕНО", out)

    def test_a_finding_still_exits_one(self):
        code, _ = self._main_with({"status": "MEASURED", "counts": {probe.VERDICT_VACUOUS: 3, probe.VERDICT_UNMEASURED: 0}})
        self.assertEqual(code, 1, "находки обязаны выходить кодом 1")

    def test_unmeasured_status_still_wins_over_the_tally(self):
        code, _ = self._main_with({"status": "UNMEASURED", "counts": {probe.VERDICT_VACUOUS: 0, probe.VERDICT_UNMEASURED: 0}})
        self.assertEqual(code, 2, "«не измерено» у всего замера кодом 0 не выдаётся")
