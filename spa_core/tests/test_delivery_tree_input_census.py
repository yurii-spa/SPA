"""Перепись «обязательный шаг не умеет назвать дерево прогона» — ADR-926.

Каждая сцена ниже — НАСТОЯЩАЯ авария в её НАСТОЯЩЕМ месте, а не выдуманная форма.
Урок цикла #1047 дословно: прибор ADR-932 отвечал «✅ ПУСТ» при девятнадцати зелёных
тестах и одиннадцати из одиннадцати убитых мутантах — и аварию, восстановленную в
настоящем коде, не нашёл ни в одной из двух её форм. Поэтому главный контроль здесь —
``test_control_a_*``: файл шага 1г берётся ДО починки (из git-истории, а не из
рукотворной сцены) и прибор ОБЯЗАН назвать его `UNNAMEABLE`.

Этот прибор уже дважды отвечал «ПУСТ» на непустом классе, и оба вакуума закреплены
сценами: поверхность из ОДНОГО места объявления (``test_surface_covers_the_prompt``) и
argv, собранный переменной (``test_long_run_through_an_argv_variable``).
"""
from __future__ import annotations

import ast
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CENSUS_PATH = ROOT / "scripts" / "delivery_tree_input_census.py"
STEP_PATH = ROOT / "scripts" / "import_time_anchor_bombs.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Регистрация ДО исполнения обязательна: `@dataclass` спрашивает
    # `sys.modules[cls.__module__]`, и у незарегистрированного модуля получает None.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


census = _load(CENSUS_PATH, "spa_delivery_tree_input_census")


def _scene(tmp: Path, step_source: str | None = None) -> Path:
    """Одноразовое дерево с ПОЛНОЙ поверхностью шагов и подменяемым шагом 1г.

    Копируются оба места объявления и КАЖДЫЙ названный там скрипт: неполное дерево
    дало бы `UNMEASURED` у двадцати шагов и утопило бы вердикт о предмете. Это не
    удобство сцены — это требование самого прибора (поверхность неполна ⇒ отказ).
    """
    (tmp / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp / "docs").mkdir(parents=True, exist_ok=True)
    for place in census.DECLARATION_PLACES:
        dst = tmp / place
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / place, dst)
    for step in census.declared_steps(tmp):
        src, dst = ROOT / step, tmp / step
        if src.is_file() and not dst.exists():
            shutil.copy2(src, dst)
    if step_source is not None:
        (tmp / "scripts" / "import_time_anchor_bombs.py").write_text(
            step_source, encoding="utf-8")
    return tmp


def _pre_fix_source() -> str:
    """Исходник шага 1г ДО починки — из git, а не переписанный руками."""
    proc = subprocess.run(
        ["git", "show", "origin/main:scripts/import_time_anchor_bombs.py"],
        cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0 or "argparse" not in proc.stdout:
        raise unittest.SkipTest(
            "предпосылка НЕ ОБЕСПЕЧЕНА: git не отдал версию шага 1г с origin/main "
            f"(код {proc.returncode}) — восстановить аварию нечем, и выдавать это "
            "за пройденный контроль запрещено")
    return proc.stdout


class ControlOnTheRealAccident(unittest.TestCase):
    """Контроль A: настоящая авария в её настоящем месте."""

    def test_control_a_pre_fix_step_is_unnameable(self) -> None:
        pre = _pre_fix_source()
        # Предпосылка сцены ПРОВЕРЯЕТСЯ, а не предполагается: если на origin/main уже
        # лежит починенный файл, сцена изображала бы аварию, которой нет.
        self.assertNotIn("--repo-root", pre,
                         "версия с origin/main уже несёт вход — аварию восстановить нечем")
        with tempfile.TemporaryDirectory(prefix="spa_dtic_") as d:
            c = census.measure(_scene(Path(d), pre))
            step = next(s for s in c.steps if s.step.endswith("import_time_anchor_bombs.py"))
            self.assertEqual(step.verdict, "UNNAMEABLE", step.reason)
            self.assertTrue(step.long_runs, "прогон не найден — мера не дошла до двери")
            self.assertIn("scripts/import_time_anchor_bombs.py",
                          [s.step for s in c.subject])

    def test_control_b_declared_but_unwired_input_is_half(self) -> None:
        """Контроль B: вход ОБЪЯВЛЕН, но до прогона не доехал (форма ADR-932)."""
        fixed = STEP_PATH.read_text(encoding="utf-8")
        self.assertIn("bombs(args.lag_min, root)", fixed)
        half = fixed.replace("bombs(args.lag_min, root)", "bombs(args.lag_min)")
        with tempfile.TemporaryDirectory(prefix="spa_dtic_") as d:
            c = census.measure(_scene(Path(d), half))
            step = next(s for s in c.steps if s.step.endswith("import_time_anchor_bombs.py"))
            self.assertEqual(step.verdict, "HALF", step.reason)
            self.assertIn("repo_root", step.tree_dests)

    def test_the_delivered_step_is_nameable(self) -> None:
        """Исход карточки: починенный шаг 1г умеет назвать дерево."""
        with tempfile.TemporaryDirectory(prefix="spa_dtic_") as d:
            c = census.measure(_scene(Path(d)))
            step = next(s for s in c.steps if s.step.endswith("import_time_anchor_bombs.py"))
            self.assertEqual(step.verdict, "NAMEABLE", step.reason)
            self.assertEqual(c.subject, [], render_subject(c))


def render_subject(c) -> str:
    return "предмет класса НЕ пуст: " + ", ".join(f"{s.step}={s.verdict}" for s in c.subject)


class SurfaceIsDeclaredInTwoPlaces(unittest.TestCase):
    """Первый вакуум прибора: поверхность из ОДНОГО места не видит предмет."""

    def test_surface_covers_the_prompt(self) -> None:
        steps = census.declared_steps(ROOT)
        self.assertIn("scripts/import_time_anchor_bombs.py", steps,
                      "дверь, по которой класс найден, выпала из поверхности")
        self.assertIn("scripts/agent_orchestrator.sh",
                      steps["scripts/import_time_anchor_bombs.py"],
                      "шаг 1г обязателен потому, что его называет ПРОМПТ — именно его "
                      "сессия и исполняет")

    def test_a_surface_from_the_document_alone_would_miss_declared_steps(self) -> None:
        """Контроль на первый вакуум прибора: ОДНО место объявления неполно.

        Утверждение держится не на одном шаге, а на РАЗНОСТИ двух мест: шаги,
        названные только в промпте, существуют (замер 06.11 — `book_second_record.py`,
        `capital_observability_census.py`, `publish_site_numbers.py`). Привязать
        контроль к одному имени значило бы погасить его первой же правкой документа —
        а вакуум бы остался.
        """
        steps = census.declared_steps(ROOT)
        doc = "docs/ORCHESTRATOR_PROTOCOL.md"
        prompt_only = [k for k, places in steps.items() if doc not in places]
        self.assertTrue(prompt_only,
                        "ни одного шага вне документа — перемерить, остались ли два "
                        "места объявления, прежде чем верить «поверхность полна»")
        for step in prompt_only:
            self.assertIn("scripts/agent_orchestrator.sh", steps[step])

    def test_an_unreadable_place_is_a_refusal_not_a_smaller_surface(self) -> None:
        with tempfile.TemporaryDirectory(prefix="spa_dtic_") as d:
            tmp = _scene(Path(d))
            (tmp / "scripts" / "agent_orchestrator.sh").unlink()
            with self.assertRaises(census.NotMeasured) as cm:
                census.declared_steps(tmp)
            self.assertIn("agent_orchestrator.sh", str(cm.exception))

    def test_a_place_without_a_single_step_is_a_refusal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="spa_dtic_") as d:
            tmp = _scene(Path(d))
            (tmp / "docs" / "ORCHESTRATOR_PROTOCOL.md").write_text("нет ссылок", encoding="utf-8")
            with self.assertRaises(census.NotMeasured):
                census.declared_steps(tmp)


class LongRunDetection(unittest.TestCase):
    """Второй вакуум прибора: argv почти никогда не стои́т в самом вызове."""

    def _runs(self, src: str) -> list:
        tree = ast.parse(src)
        sources = census._argv_sources(tree)
        return [n for n in ast.walk(tree)
                if isinstance(n, ast.Call) and census._is_long_run(n, sources)]

    def test_long_run_through_an_argv_variable(self) -> None:
        src = ('import subprocess, sys\n'
               'def go(root):\n'
               '    cmd = [sys.executable, "-m", "pytest", "-q"]\n'
               '    return subprocess.run(cmd, cwd=root)\n')
        self.assertEqual(len(self._runs(src)), 1,
                         "argv, собранный переменной, прибором не увиден — ровно тот "
                         "вакуум, из-за которого перепись отвечала NO_LONG_RUN")

    def test_long_run_inline(self) -> None:
        src = ('import subprocess\n'
               'subprocess.run(["python3", "-m", "pytest"], cwd="/x")\n')
        self.assertEqual(len(self._runs(src)), 1)

    def test_a_git_child_is_not_a_long_run(self) -> None:
        src = ('import subprocess\n'
               'subprocess.run(["git", "status", "--porcelain"], cwd="/x")\n')
        self.assertEqual(self._runs(src), [],
                         "любой дочерний процесс стал бы предметом — это шум, а не класс")

    def test_a_non_spawner_call_is_not_a_long_run(self) -> None:
        src = 'print(["-m", "pytest"])\n'
        self.assertEqual(self._runs(src), [])


class CwdIsTheQuestion(unittest.TestCase):
    """Доехал ли вход до `cwd=` — и формы, в которых он не доезжает."""

    def _verdict(self, src: str) -> str:
        with tempfile.TemporaryDirectory(prefix="spa_dtic_") as d:
            tmp = Path(d)
            (tmp / "scripts").mkdir()
            f = tmp / "scripts" / "x.py"
            f.write_text(src, encoding="utf-8")
            return census.measure_file(f, "scripts/x.py").verdict

    def test_two_parameter_hops_reach_the_door(self) -> None:
        src = ('import argparse, subprocess, sys\n'
               'ROOT = "/prod"\n'
               'def inner(files, root):\n'
               '    cmd = [sys.executable, "-m", "pytest", *files]\n'
               '    return subprocess.run(cmd, cwd=root)\n'
               'def outer(root=ROOT):\n'
               '    return inner([], root)\n'
               'def main():\n'
               '    ap = argparse.ArgumentParser()\n'
               '    ap.add_argument("--repo-root")\n'
               '    args = ap.parse_args()\n'
               '    return outer(args.repo_root)\n')
        self.assertEqual(self._verdict(src), "NAMEABLE",
                         "засев не прошёл два хопа через параметры — а авария отстоит "
                         "от двери именно на два")

    def test_a_missing_cwd_keyword_is_unnameable(self) -> None:
        src = ('import argparse, subprocess, sys\n'
               'def main():\n'
               '    ap = argparse.ArgumentParser()\n'
               '    ap.add_argument("--repo-root")\n'
               '    args = ap.parse_args()\n'
               '    return subprocess.run([sys.executable, "-m", "pytest"])\n')
        self.assertEqual(self._verdict(src), "HALF",
                         "прогон без cwd= идёт там, где СТОЯЛ вызывающий — назвать "
                         "дерево нечем, сколько бы флагов ни было объявлено")

    def test_a_module_constant_cwd_is_unnameable(self) -> None:
        src = ('import subprocess, sys\n'
               'ROOT = "/prod"\n'
               'def main():\n'
               '    return subprocess.run([sys.executable, "-m", "pytest"], cwd=ROOT)\n')
        self.assertEqual(self._verdict(src), "UNNAMEABLE")

    def test_data_dir_is_not_a_tree_input(self) -> None:
        src = ('import argparse, subprocess, sys\n'
               'ROOT = "/prod"\n'
               'def main():\n'
               '    ap = argparse.ArgumentParser()\n'
               '    ap.add_argument("--data-dir")\n'
               '    args = ap.parse_args()\n'
               '    print(args.data_dir)\n'
               '    return subprocess.run([sys.executable, "-m", "pytest"], cwd=ROOT)\n')
        self.assertEqual(self._verdict(src), "UNNAMEABLE",
                         "--data-dir называет каталог ДАННЫХ, а не дерево прогона; "
                         "приравнять их значило бы объявить названным то, о чём "
                         "никто не спрашивал")

    def test_no_child_run_is_outside_the_subject(self) -> None:
        src = 'import json\nprint(json.dumps({}))\n'
        self.assertEqual(self._verdict(src), "NO_LONG_RUN")

    def test_an_unparsed_file_is_unmeasured_not_clean(self) -> None:
        src = 'def broken(:\n'
        self.assertEqual(self._verdict(src), "UNMEASURED")


class StepOneGInputOutcomes(unittest.TestCase):
    """Три исхода входа `--repo-root` у самого шага 1г (инв. #17)."""

    step = _load(STEP_PATH, "spa_import_time_anchor_bombs")

    def test_default_tree_is_own_and_flagged_as_default(self) -> None:
        tree, named = self.step.resolve_repo_root(None)
        self.assertEqual(tree, self.step.ROOT)
        self.assertFalse(named, "умолчание обязано быть РАЗЛИЧИМО от названного дерева")

    def test_named_tree_is_returned_and_flagged(self) -> None:
        tree, named = self.step.resolve_repo_root(str(ROOT))
        self.assertEqual(tree, ROOT.resolve())
        self.assertTrue(named)

    def test_a_missing_tree_refuses_instead_of_falling_back(self) -> None:
        with self.assertRaises(self.step.NotMeasured) as cm:
            self.step.resolve_repo_root("/nope/definitely/not/here")
        self.assertIn("не существует", str(cm.exception))

    def test_a_tree_that_is_not_spa_refuses_with_its_own_reason(self) -> None:
        with tempfile.TemporaryDirectory(prefix="spa_dtic_") as d:
            with self.assertRaises(self.step.NotMeasured) as cm:
                self.step.resolve_repo_root(d)
            self.assertIn("не похож на дерево SPA", str(cm.exception))

    def test_an_empty_name_refuses(self) -> None:
        with self.assertRaises(self.step.NotMeasured):
            self.step.resolve_repo_root("   ")

    def test_the_cli_prints_which_tree_it_measures(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(STEP_PATH), "--repo-root", "/nope/not/here"],
            capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("НЕ ИЗМЕРЕНО", proc.stdout)

    def test_the_help_declares_the_input(self) -> None:
        proc = subprocess.run([sys.executable, str(STEP_PATH), "--help"],
                              capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--repo-root", proc.stdout,
                      "«умеет ли прибор принять дерево» — ОТДЕЛЬНЫЙ вопрос, и он "
                      "задаётся --help, а не кодом возврата рабочего прогона")


class ThirdOutcomeOfTheCensusItself(unittest.TestCase):
    def test_a_named_unreadable_tree_refuses(self) -> None:
        self.assertEqual(census.main(["--repo-root", "/nope/not/here"]), 2)

    def test_the_live_tree_measures_without_unmeasured_steps(self) -> None:
        c = census.measure(ROOT)
        self.assertEqual([s.step for s in c.unmeasured], [],
                         "шаг назван в объявлении, а файла в дереве нет — это отказ, "
                         "а не вычитание из населения")
        self.assertGreater(len(c.steps), 10)

    def test_the_class_population_is_named_not_assumed(self) -> None:
        """Население класса ИЗМЕРЕНО: сколько шагов вообще поднимают долгий прогон."""
        c = census.measure(ROOT)
        with_runs = [s for s in c.steps if s.verdict != "NO_LONG_RUN"]
        self.assertEqual(len(with_runs), 1,
                         "население класса изменилось — перемерить и записать новое "
                         "число, а не править ожидание: " + ", ".join(
                             f"{s.step}={s.verdict}" for s in with_runs))
        self.assertEqual(with_runs[0].step, "scripts/import_time_anchor_bombs.py")


class TaintBudget(unittest.TestCase):
    def test_exhausted_rounds_are_unmeasured_not_clean(self) -> None:
        """Исчерпание предела кругов — третий исход, а не «чисто»."""
        src = ('import argparse, subprocess, sys\n'
               'def f0(root):\n'
               '    return subprocess.run([sys.executable, "-m", "pytest"], cwd=root)\n')
        chain = "".join(f"def f{i}(root):\n    return f{i-1}(root)\n"
                        for i in range(1, census.TAINT_ROUNDS + 4))
        src += chain
        src += ('def main():\n'
                '    ap = argparse.ArgumentParser()\n'
                '    ap.add_argument("--repo-root")\n'
                '    args = ap.parse_args()\n'
                f'    return f{census.TAINT_ROUNDS + 3}(args.repo_root)\n')
        with tempfile.TemporaryDirectory(prefix="spa_dtic_") as d:
            tmp = Path(d) / "scripts"
            tmp.mkdir(parents=True)
            f = tmp / "x.py"
            f.write_text(src, encoding="utf-8")
            v = census.measure_file(f, "scripts/x.py")
        self.assertEqual(v.verdict, "UNMEASURED", v.reason)
        self.assertIn("исчерпал предел", v.reason)


class NoSubstringMeasurement(unittest.TestCase):
    """Проба/перепись судит ВЕРДИКТ, а не подстроку в исходнике (ADR-333)."""

    def test_a_flag_in_a_comment_does_not_make_a_tree_nameable(self) -> None:
        src = ('import subprocess, sys\n'
               'ROOT = "/prod"\n'
               '# --repo-root: когда-нибудь добавим\n'
               '"""и в докстринге тоже --repo-root"""\n'
               'def main():\n'
               '    return subprocess.run([sys.executable, "-m", "pytest"], cwd=ROOT)\n')
        with tempfile.TemporaryDirectory(prefix="spa_dtic_") as d:
            tmp = Path(d) / "scripts"
            tmp.mkdir(parents=True)
            f = tmp / "x.py"
            f.write_text(src, encoding="utf-8")
            self.assertEqual(census.measure_file(f, "scripts/x.py").verdict, "UNNAMEABLE")


if __name__ == "__main__":
    unittest.main()
