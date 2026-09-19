"""Зонд копий: сторож прибора, у каждой проверки обратная сторона.

Заказ **G43 п. 2** приказа владельца «Portfolio CIO», решение — ADR-419.

## Что здесь проверяется и почему именно так

Зонд отвечает на два вопроса — «читает ли сторож свою константу» и «краснеет
ли он от правки исполнителя». Ошибиться он может в обе стороны, и опасна одна
из них — та, что снимает пару с учёта. Первая редакция назвала нечувствительный
вердикт «константа не читается» и сняла бы ПЯТЬ живых пар; поправку нашёл
перечитанный исходник, а не прогон. Поэтому у каждой сцены есть обратная.

**Главная сцена — НАСТОЯЩИЙ контур, а не подделка:** заводится крошечный
git-репозиторий с исполнителем и ЧЕТЫРЬМЯ сторожами, и зонд гоняет по нему
настоящий pytest в настоящем одноразовом дереве. Каждый из четырёх сторожей —
положительный контроль своего исхода, и исход у каждого свой:

* читает константу, исполнителя не достаёт ⇒ `drift_silent` (ВРЕД);
* вердикт к своей константе нечувствителен ⇒ `verdict_insensitive`;
* читает и достаёт исполнителя ⇒ `drift_loud`;
* красен на базе ⇒ `unmeasured` (третий исход, не вердикт).

Литеральных дат и номеров процессов здесь нет: часы прибора инъектируются
параметром ``now``, а деревья — временные.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import copy_independence_probe as probe

#: Неподвижные часы: прибор берёт их параметром.
# FROZEN-DATE-OK: injected-clock — час передаётся в measure/run параметром now=
_NOW = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)


class MutationIsStrongAndTwoSided(unittest.TestCase):
    """Одна слабая перемена оставила бы порог зелёным и соврала бы «не читает»."""

    def test_a_number_gets_two_opposite_mutants(self):
        self.assertEqual(probe.mutate_values("10"), ["1000010", "-999990"])

    def test_a_threshold_mutant_actually_crosses_the_threshold(self):
        """Ровно та сцена, ради которой перемен две: `len(x) >= 10` при 36."""
        low, high = sorted(int(m) for m in probe.mutate_values("10"))
        self.assertFalse(36 >= high, "верхняя перемена обязана порог НЕ пройти")
        self.assertTrue(36 >= low, "нижняя перемена обязана порог пройти")

    def test_a_container_gets_empty_and_grown(self):
        self.assertEqual(probe.mutate_values("('a', 'b')"),
                         ["()", "('a', 'b', '_PROBE_MUTANT')"])

    def test_a_bool_is_not_mutated_as_a_number(self):
        """ОБРАТНАЯ СТОРОНА: `True + 1_000_000` было бы числом, а не другим флагом."""
        self.assertEqual(probe.mutate_values("True"), ["False"])

    def test_a_nonliteral_value_yields_nothing(self):
        """Третий исход: «перемены нет» ≠ «вердикт не изменился»."""
        self.assertEqual(probe.mutate_values("Path(__file__).resolve()"), [])


class ReplacementGoesByCoordinateNotByText(unittest.TestCase):
    """Имя встречается в файле многократно — текстовая замена попала бы не туда."""

    SRC = ('SEED = 42\n'
           'def f():\n'
           '    return "SEED = 42 is the rule"\n')

    def test_only_the_toplevel_assignment_is_replaced(self):
        out = probe.replace_constant(self.SRC, "SEED", "SEED = 7")
        self.assertIn("SEED = 7\n", out)
        self.assertIn('return "SEED = 42 is the rule"', out,
                      "строка внутри функции — не правило и не трогается")

    def test_two_toplevel_assignments_refuse_the_experiment(self):
        """ОБРАТНАЯ СТОРОНА: координата не единственна ⇒ опыт не ставится."""
        with self.assertRaises(probe.NotMeasured):
            probe.replace_constant("SEED = 1\nSEED = 2\n", "SEED", "SEED = 7")

    def test_a_missing_name_refuses_too(self):
        with self.assertRaises(probe.NotMeasured):
            probe.replace_constant("OTHER = 1\n", "SEED", "SEED = 7")

    def test_a_multiline_value_is_replaced_whole(self):
        out = probe.replace_constant("SEED = (\n    42,\n)\nX = 1\n", "SEED", "SEED = ()")
        self.assertEqual(out, "SEED = ()\nX = 1\n")


def _rmtree(path: Path) -> None:
    shutil.rmtree(path)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


def _build_contour(repo: Path) -> None:
    """Крошечный настоящий репозиторий: исполнитель и четыре сторожа."""
    (repo / "spa_core" / "tests").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "conftest.py").write_text("", encoding="utf-8")
    (repo / "spa_core" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "spa_core" / "e.py").write_text("SEED = 42\n", encoding="utf-8")
    # Пороги RiskPolicy — предпосылка ПЕРЕПИСИ: без них она отвечает UNMEASURED,
    # и сцена мерила бы её отказ вместо своего предмета.
    (repo / "spa_core" / "risk").mkdir()
    (repo / "spa_core" / "risk" / "policy.py").write_text(
        "MAX_DRAWDOWN = 0.07\n", encoding="utf-8")

    # 1. читает свою константу, исполнителя не достаёт ⇒ снос врозь МОЛЧА
    (repo / "spa_core" / "tests" / "test_silent.py").write_text(
        "SEED = 42\n\n\ndef test_seed():\n    assert SEED == 42\n", encoding="utf-8")
    # 2. константу не читает ⇒ она мертва
    (repo / "spa_core" / "tests" / "test_dead.py").write_text(
        "SEED = 42\n\n\ndef test_nothing():\n    assert True\n", encoding="utf-8")
    # 3. читает свою И достаёт исполнителя ⇒ снос врозь с краснотой
    (repo / "spa_core" / "tests" / "test_loud.py").write_text(
        "from spa_core.e import SEED as THEIRS\n\nSEED = 42\n\n\n"
        "def test_agree():\n    assert THEIRS == SEED\n", encoding="utf-8")
    # 4. красен на базе ⇒ мерить изменение вердикта не от чего
    (repo / "spa_core" / "tests" / "test_red.py").write_text(
        "SEED = 42\n\n\ndef test_broken():\n    assert SEED == 0\n", encoding="utf-8")
    # 5. ОБЕ оси разом: своя константа читается, но в утверждении не участвует,
    #    а исполнителя сторож достаёт. Сцена существует ради ПОРЯДКА вердиктов.
    (repo / "spa_core" / "tests" / "test_both.py").write_text(
        "from spa_core.e import SEED as THEIRS\n\nSEED = 42\n_read = SEED\n\n\n"
        "def test_agree():\n    assert THEIRS == 42\n", encoding="utf-8")

    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "probe@example.invalid")
    _git(repo, "config", "user.name", "probe")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "contour")


def _row(guard: str) -> dict:
    return {"guard": f"spa_core/tests/{guard}", "executor": "spa_core/e.py",
            "name": "SEED", "value": "42", "verdict": "two_copies"}


class LiveContourEachVerdictHasItsPositiveControl(unittest.TestCase):
    """Настоящий pytest в настоящем одноразовом дереве. Медленно — и это цена правды."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = TemporaryDirectory()
        repo = Path(cls._tmp.name) / "repo"
        repo.mkdir()
        _build_contour(repo)
        cls.repo = repo
        cls.doc = probe.measure(
            repo, now=_NOW,
            rows=[_row("test_silent.py"), _row("test_dead.py"),
                  _row("test_loud.py"), _row("test_red.py"), _row("test_both.py")])
        cls.by_guard = {Path(e["guard"]).name: e for e in cls.doc["entries"]}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_a_guard_that_reads_its_constant_but_not_the_executor_drifts_silently(self):
        entry = self.by_guard["test_silent.py"]
        self.assertEqual(entry["verdict"], probe.VERDICT_DRIFT_SILENT, entry["evidence"])
        self.assertTrue(entry["guard_mutation_changed"])
        self.assertFalse(entry["executor_mutation_changed"])

    def test_a_guard_whose_verdict_ignores_its_constant_is_named_toothless(self):
        entry = self.by_guard["test_dead.py"]
        self.assertEqual(entry["verdict"], probe.VERDICT_INSENSITIVE, entry["evidence"])
        self.assertFalse(entry["guard_mutation_changed"])
        self.assertIn("executor_mutation_changed", entry,
                      "ось вреда меряется ВСЕГДА — иначе молчание сойдёт за ответ")
        self.assertIn("НЕ «константа не читается»", entry["evidence"])

    def test_a_guard_reaching_the_executor_drifts_loudly(self):
        entry = self.by_guard["test_loud.py"]
        self.assertEqual(entry["verdict"], probe.VERDICT_DRIFT_LOUD, entry["evidence"])
        self.assertTrue(entry["executor_mutation_changed"])

    def test_a_guard_red_at_baseline_is_unmeasured_not_a_verdict(self):
        entry = self.by_guard["test_red.py"]
        self.assertEqual(entry["verdict"], probe.VERDICT_UNMEASURED)
        self.assertIn("НЕ зелен на базе", entry["evidence"])

    def test_the_disposable_tree_is_removed_and_the_repo_is_untouched(self):
        """Батарея, оставившая дерево изменённым, делает недостоверным всё."""
        out = subprocess.run(["git", "status", "--porcelain"], cwd=str(self.repo),
                             capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "",
                         "рабочее дерево обязано остаться нетронутым")
        trees = subprocess.run(["git", "worktree", "list"], cwd=str(self.repo),
                               capture_output=True, text=True).stdout
        self.assertNotIn("spa_copy_probe_", trees, "одноразовое дерево не снято")

    def test_toothless_verdict_is_asked_BEFORE_the_drift_axis(self):
        """Сторож, нечувствительный к своей константе И краснеющий от чужой.

        Порядок вердиктов здесь — предмет, а не стиль: если спросить про снос
        врозь первым, пара назовётся `drift_loud`, и «у правила нет зубов»
        никогда не будет сказано вслух.
        """
        entry = self.by_guard["test_both.py"]
        self.assertFalse(entry["guard_mutation_changed"])
        self.assertTrue(entry["executor_mutation_changed"])
        self.assertEqual(entry["verdict"], probe.VERDICT_INSENSITIVE, entry["evidence"])

    def test_the_order_s_own_method_is_measured_and_named_degenerate(self):
        """Поправка к заказу — ЧИСЛО в документе, а не фраза в ADR."""
        # Измерено 3 из 4: красный на базе сторож опыта не получает вовсе.
        # Сдвинул вердикт ОДИН — тот, что достаёт исполнителя ввозом; у двух
        # остальных «не сдвинул», и это ровно вырожденность способа заказа.
        self.assertEqual(self.doc["executor_mutation_changed_verdict"], 2)
        self.assertEqual(self.doc["executor_mutation_measured"], 4)
        text = "\n".join(probe.report(self.doc))
        self.assertIn("[СПОСОБ ЗАКАЗА]", text)
        self.assertIn("описывает ВРЕД", text)

    def test_every_verdict_is_one_of_the_declared_four(self):
        for entry in self.doc["entries"]:
            self.assertIn(entry["verdict"], probe._VERDICTS)
            self.assertTrue(entry["evidence"], "исход без основания — не исход")


class AKilledExperimentLeavesATreeAndItIsNamed(unittest.TestCase):
    """Убитый опыт рабочее дерево не портит, но одноразовое оставляет висеть."""

    def test_a_leftover_disposable_tree_is_named(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _build_contour(repo)
            left = Path(tmp) / (probe.TREE_PREFIX + "leftover")
            _git(repo, "worktree", "add", "--detach", str(left), "HEAD")
            named = probe.stale_disposable_trees(repo)
            self.assertEqual([Path(p).name for p in named], [left.name])
            doc = probe.measure(repo, now=_NOW, rows=[_row("test_silent.py")])
        self.assertEqual(len(doc["stale_disposable_trees"]), 1)
        self.assertIn("ОСТАЛИСЬ ВИСЕТЬ", "\n".join(probe.report(doc)))

    def test_a_clean_repo_names_nothing(self):
        """ОБРАТНАЯ СТОРОНА: иначе строка стояла бы всегда и ничего не значила."""
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _build_contour(repo)
            self.assertEqual(probe.stale_disposable_trees(repo), [])
            doc = probe.measure(repo, now=_NOW, rows=[_row("test_silent.py")])
        self.assertEqual(doc["stale_disposable_trees"], [])
        self.assertNotIn("ОСТАЛИСЬ ВИСЕТЬ", "\n".join(probe.report(doc)))

    def test_the_probe_does_not_reap_a_neighbours_tree(self):
        """Снять чужое дерево значило бы убить соседний живой опыт."""
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _build_contour(repo)
            left = Path(tmp) / (probe.TREE_PREFIX + "neighbour")
            _git(repo, "worktree", "add", "--detach", str(left), "HEAD")
            probe.measure(repo, now=_NOW, rows=[_row("test_silent.py")])
            self.assertTrue(left.is_dir(), "чужое дерево обязано остаться на месте")


class TheExperimentRefusesWhenItsOwnPremiseFails(unittest.TestCase):
    """Молча не применившаяся перемена и невосстановленное дерево — отказ, не ответ."""

    def _stand(self, tmp: str):
        repo = Path(tmp) / "repo"
        repo.mkdir()
        _build_contour(repo)
        return repo, repo / "spa_core" / "tests" / "test_silent.py"

    def test_a_mutation_that_does_not_apply_is_a_refusal(self):
        with TemporaryDirectory() as tmp:
            repo, guard = self._stand(tmp)
            src = guard.read_text(encoding="utf-8")
            with self.assertRaises(probe.NotMeasured) as caught:
                # Перемена, равная исходному значению: подмена «применилась»,
                # а значение не сдвинулось — и без проверки это выглядело бы
                # как честное «вердикт не изменился».
                probe._side_changes_verdict(
                    guard, src, "SEED", "42", ["42"], repo,
                    "spa_core/tests/test_silent.py", probe.sha256(guard), 0)
            self.assertIn("не применилась", str(caught.exception))
            self.assertEqual(guard.read_text(encoding="utf-8"), src)

    def test_a_tree_not_restored_is_a_loud_refusal(self):
        with TemporaryDirectory() as tmp:
            repo, guard = self._stand(tmp)
            src = guard.read_text(encoding="utf-8")
            with self.assertRaises(probe.NotMeasured) as caught:
                probe._side_changes_verdict(
                    guard, src, "SEED", "42", ["7"], repo,
                    "spa_core/tests/test_silent.py", "0" * 64, 0)
            self.assertIn("не восстановлено", str(caught.exception))


class OwnerSubjectIsNotTouched(unittest.TestCase):
    """Граница ADR-285 проходит по ПРЕДМЕТУ, и одноразовое дерево её не отменяет."""

    def test_an_owner_subject_pair_is_skipped_with_a_reason(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _build_contour(repo)
            row = dict(_row("test_silent.py"), remedy="owner_subject")
            doc = probe.measure(repo, now=_NOW, rows=[row])
        (entry,) = doc["entries"]
        self.assertEqual(entry["verdict"], probe.VERDICT_UNMEASURED)
        self.assertIn("предмет владельца", entry["evidence"])


class RefusalsAreNamedNotSilent(unittest.TestCase):
    """«Не измерено» обязано быть отличимо от «измерено и ничего нет» (инв. #17)."""

    def test_a_tree_without_git_is_unmeasured(self):
        """Дерево-контур есть, истории нет: одноразовое дерево заводить не от чего."""
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _build_contour(repo)
            _rmtree(repo / ".git")
            doc = probe.run(repo, write=False, now=_NOW)["doc"]
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("sha рабочего дерева не прочитан", str(doc["reason"]))
        self.assertIn("НЕ ИЗМЕРЕНО", "\n".join(probe.report(doc)))

    def test_an_unreadable_population_is_unmeasured_too(self):
        """Отказ ПЕРЕПИСИ обязан стать исходом ЗОНДА, а не трассировкой."""
        with TemporaryDirectory() as tmp:
            outcome = probe.run(Path(tmp), write=False, now=_NOW)
        self.assertFalse(outcome["measured"])
        self.assertEqual(outcome["doc"]["status"], "UNMEASURED")
        self.assertIn("не прочитан", str(outcome["doc"]["reason"]))

    def test_a_dirty_side_is_not_measured_against_head(self):
        """Одноразовое дерево несёт HEAD — правка в рабочем дереве в него не попала."""
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _build_contour(repo)
            (repo / "spa_core" / "e.py").write_text("SEED = 42\n# правка\n",
                                                    encoding="utf-8")
            doc = probe.measure(repo, now=_NOW, rows=[_row("test_silent.py")])
        (entry,) = doc["entries"]
        self.assertEqual(entry["verdict"], probe.VERDICT_UNMEASURED)
        self.assertIn("изменена в рабочем дереве", entry["evidence"])

    def test_pytest_is_asked_as_its_own_question(self):
        """Код возврата рабочего прогона на вопрос «инструмент есть?» не отвечает."""
        available, version = probe.pytest_available(Path(sys.prefix))
        self.assertTrue(available)
        self.assertIn("pytest", version.lower())


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
        code, _ = self._main_with({"status": "MEASURED", "counts": {probe.VERDICT_UNMEASURED: 0, probe.VERDICT_DRIFT_SILENT: 0}})
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
        code, _ = self._main_with({"status": "MEASURED", "counts": {probe.VERDICT_UNMEASURED: 0, probe.VERDICT_DRIFT_SILENT: 2}})
        self.assertEqual(code, 1, "находки обязаны выходить кодом 1")

    def test_unmeasured_status_still_wins_over_the_tally(self):
        code, _ = self._main_with({"status": "UNMEASURED", "counts": {probe.VERDICT_UNMEASURED: 0, probe.VERDICT_DRIFT_SILENT: 0}})
        self.assertEqual(code, 2, "«не измерено» у всего замера кодом 0 не выдаётся")



if __name__ == "__main__":
    unittest.main()
