"""Контроли прибора «личность репозитория, куда ведёт `cd`» (ЗАКАЗ #579, ADR-360).

Каждый контроль воспроизводит РЕАЛЬНОЕ свойство нашего хоста или реальную
ловушку заказа, а не выдуманную фикстуру. Главный из них — `test_shallow_...`:
он строит НЕПОЛНЫЙ клон и показывает, что наивная сверка «корневой коммит»
объявила бы два клона одного репозитория разными. Прод-дерево на этой машине
именно такое (443 коммита, `--is-shallow-repository` = true), поэтому контроль
не гипотетический.
"""
from __future__ import annotations

import io
import sys
import json
import shutil
import unittest
import subprocess
import contextlib
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from shell_git_cd_repo_identity import (           # noqa: E402
    repo_facts, histories_intersect, identity_of, subject_keys, main,
    unmeasurable_here, ABSENT_MARK,
)


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, timeout=60)


def make_repo(path: Path, commits: int = 3, name: str = "seed") -> Path:
    """Настоящий маленький репозиторий: контроль должен мерить git, а не макет."""
    path.mkdir(parents=True, exist_ok=True)
    git(["init", "-q", "-b", "main"], path)
    git(["config", "user.email", "t@t"], path)
    git(["config", "user.name", "t"], path)
    for i in range(commits):
        (path / f"{name}{i}.txt").write_text(f"{name} {i}\n", encoding="utf-8")
        git(["add", "-A"], path)
        git(["commit", "-qm", f"{name} {i}"], path)
    return path


class IdentityIsHistoryIntersection(unittest.TestCase):
    """Что объявлено личностью — и что ею НЕ является."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ident-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_two_clones_of_one_repo_are_the_same_identity(self):
        origin = make_repo(self.tmp / "origin", commits=4)
        clone = self.tmp / "clone"
        git(["clone", "-q", str(origin), str(clone)], self.tmp)
        a, _ = repo_facts(str(origin))
        b, _ = repo_facts(str(clone))
        same, why = histories_intersect(a, b)
        self.assertIs(same, True, why)

    def test_unrelated_repos_are_provably_other_identity(self):
        """Аналог `~/Documents/earn-defi`: совсем другой репозиторий рядом."""
        a = make_repo(self.tmp / "spa", commits=3, name="spa")
        b = make_repo(self.tmp / "earn", commits=3, name="earn")
        verdict, detail = identity_of(str(b), repo_facts(str(a))[0])
        self.assertEqual(verdict, "other_identity", detail)

    def test_identical_origin_url_does_not_make_identity(self):
        """origin — КОНФИГ. Две несвязанные истории с одним URL обязаны
        остаться РАЗНЫМИ личностями, иначе прибор доверяет подделываемому."""
        a = make_repo(self.tmp / "a", commits=3, name="a")
        b = make_repo(self.tmp / "b", commits=3, name="b")
        for r in (a, b):
            git(["remote", "add", "origin", "https://example.invalid/same.git"], r)
        fa, fb = repo_facts(str(a))[0], repo_facts(str(b))[0]
        self.assertEqual(fa["origin"], fb["origin"])          # URL совпал…
        verdict, detail = identity_of(str(b), fa)
        self.assertEqual(verdict, "other_identity", detail)   # …личность нет

    def test_missing_origin_does_not_destroy_identity(self):
        """Копия без `origin` остаётся тем же репозиторием."""
        origin = make_repo(self.tmp / "origin", commits=3)
        clone = self.tmp / "clone"
        git(["clone", "-q", str(origin), str(clone)], self.tmp)
        git(["remote", "remove", "origin"], clone)
        self.assertEqual(repo_facts(str(clone))[0]["origin"], "")
        verdict, detail = identity_of(str(clone), repo_facts(str(origin))[0])
        self.assertEqual(verdict, "same_identity", detail)


class ShallowCloneIsTheTrap(unittest.TestCase):
    """ГЛАВНЫЙ контроль: корневой коммит есть функция ГЛУБИНЫ клона.

    Прод-дерево на этой машине неполное. Наивная сверка `--max-parents=0`
    объявила бы его и полное зеркало разными репозиториями — уверенная ложная
    находка. Контроль воспроизводит это на настоящем неполном клоне."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="shallow-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.full = make_repo(self.tmp / "full", commits=6)
        self.shallow = self.tmp / "shallow"
        git(["clone", "-q", "--depth", "1", "file://" + str(self.full),
             str(self.shallow)], self.tmp)

    def test_the_naive_root_commit_check_would_lie(self):
        """Предпосылка контроля: якоря РАЗНЫЕ. Не обеспечилась — падать ГРОМКО."""
        if repo_facts(str(self.shallow))[0]["shallow"] is not True:
            self.fail("предпосылка не обеспечена: клон не получился неполным — "
                      "контроль о ловушке обрезки без обрезки ничего не мерит")
        a = repo_facts(str(self.full))[0]["anchors"]
        b = repo_facts(str(self.shallow))[0]["anchors"]
        self.assertNotEqual(a, b, "якоря совпали — ловушка не воспроизведена")

    def test_but_intersection_proves_the_same_identity(self):
        full = repo_facts(str(self.full))[0]
        shallow = repo_facts(str(self.shallow))[0]
        same, why = histories_intersect(shallow, full)
        self.assertIs(same, True, f"обрезка истории сломала вердикт: {why}")
        self.assertIn("якорь", why)

    def test_verdict_is_same_identity_in_both_directions(self):
        f, s = repo_facts(str(self.full))[0], repo_facts(str(self.shallow))[0]
        self.assertEqual(identity_of(str(self.shallow), f)[0], "same_identity")
        self.assertEqual(identity_of(str(self.full), s)[0], "same_identity")


class ThirdOutcomeNeverFoldsIntoTheFirst(unittest.TestCase):
    """Инвариант #17: «не измерено» отличимо от «та же» и от «другая»."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="third-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ref = repo_facts(str(make_repo(self.tmp / "ref")))[0]

    def test_absent_directory_is_undetermined_not_other(self):
        """Каталога нет на ЭТОЙ машине — скрипт может исполняться там, где он
        есть. Это третий исход, а не приговор «другой репозиторий»."""
        verdict, detail = identity_of(str(self.tmp / "nope"), self.ref)
        self.assertEqual(verdict, "undetermined")
        self.assertIn("нет на этой машине", detail["why"])

    def test_existing_non_repo_is_other_identity_with_a_named_reason(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        verdict, detail = identity_of(str(plain), self.ref)
        self.assertEqual(verdict, "other_identity")
        self.assertIn("рабочей копией git не является", detail["why"])

    def test_repo_without_head_is_undetermined(self):
        """Пустой репозиторий: якоря нет вовсе — судить не о чем."""
        empty = self.tmp / "empty"
        empty.mkdir()
        git(["init", "-q", "-b", "main"], empty)
        verdict, detail = identity_of(str(empty), self.ref)
        self.assertEqual(verdict, "undetermined", detail)


class SameIdentityIsNotSameRevision(unittest.TestCase):
    """«Та же история» ≠ «та же ревизия» — и второе есть опасность
    `/tmp/spa_cNNN`, поэтому оно ДОКЛАДЫВАЕТСЯ, а не решается."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rev-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_linked_worktree_on_another_revision_is_still_same_identity(self):
        main_repo = make_repo(self.tmp / "main", commits=5)
        old = git(["rev-parse", "HEAD~3"], main_repo).stdout.strip()
        wt = self.tmp / "wt"
        git(["worktree", "add", "-q", "--detach", str(wt), old], main_repo)
        ref = repo_facts(str(main_repo))[0]
        verdict, detail = identity_of(str(wt), ref)
        self.assertEqual(verdict, "same_identity", detail)
        self.assertFalse(detail["same_revision"],
                         "ревизии обязаны отличаться — иначе контроль пуст")
        self.assertTrue(detail["linked_worktree"],
                        "признак связанной копии обязан быть ДОЛОЖЕН")


class TheReportAndTheRatchet(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rep-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_json_mode_prints_exactly_one_document(self):
        """Дефект, найденный у прибора ADR-356 и воспроизведённый здесь:
        `--json` печатал документ, а следом человеческую строку вердикта —
        потребитель давится на разборе. stdout обязан быть ЧИСТЫМ."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            main(["--root", str(REPO), "--json"])
        json.loads(out.getvalue())          # разбор ОДНОГО документа целиком

    def test_subject_excludes_undetermined_to_avoid_double_counting(self):
        """`undetermined` — населённый предмет ADR-356. Считать его и здесь
        значило бы изобразить рост класса там, где класс один."""
        rows = [{"file": "a.sh", "line": 1, "identity": "undetermined", "basis": "n/a"},
                {"file": "b.sh", "line": 2, "identity": "same_identity", "basis": "by_host"},
                {"file": "c.sh", "line": 3, "identity": "same_identity", "basis": "by_construction"},
                {"file": "d.sh", "line": 4, "identity": "other_identity", "basis": "n/a"}]
        self.assertEqual(subject_keys(rows), ["b.sh:2", "d.sh:4"])

    def test_hijackable_copy_location_is_in_the_subject(self):
        """Зов идёт за своей копией, но МЕСТО копии перебивается экспортом
        `BASH_SOURCE` (bash 3.2.57 прод-хоста) ⇒ личность кодом не
        гарантирована, и усреднять её с честным `by_construction` нельзя."""
        rows = [{"file": "secure_git_push.sh", "line": 52,
                 "identity": "same_identity",
                 "basis": "by_construction_hijackable"}]
        self.assertEqual(subject_keys(rows), ["secure_git_push.sh:52"])

    def test_by_construction_is_never_in_the_subject(self):
        rows = [{"file": "x.sh", "line": 9, "identity": "same_identity",
                 "basis": "by_construction"}]
        self.assertEqual(subject_keys(rows), [])

    def test_missing_baseline_is_unmeasured_not_clean(self):
        """«Базы нет» никогда не выдаётся за «чисто» — код 2, а не 0."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(["--root", str(REPO), "--json",
                       "--baseline", str(self.tmp / "absent.json")])
        self.assertEqual(rc, 2)

    def test_root_that_is_not_a_working_copy_is_unmeasured(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(["--root", str(plain), "--json"])
        self.assertEqual(rc, 2)


class AForeignHostMustRefuseNotGreen(unittest.TestCase):
    """Предмет `by_host` измерим только там, где приколоченные пути есть.

    На ubuntu (где идёт CI) литерала `/Users/yuriikulieshov/...` нет, каждая
    такая цель честно становится `undetermined`, и предмет ВЫГЛЯДИТ пустым.
    Храповик тогда посоветовал бы сократить базу до нуля — «не измерено»,
    выданное за УЛУЧШЕНИЕ. Хост обязан отказать вслух."""

    def test_absent_pinned_target_is_reported_as_unmeasurable(self):
        """Настоящая цель, которой на этой машине нет, — через настоящий
        `identity_of`, а не через выдуманную строку причины."""
        with tempfile.TemporaryDirectory() as td:
            ref = repo_facts(str(make_repo(Path(td) / "ref")))[0]
            verdict, detail = identity_of(str(Path(td) / "no-such-tree"), ref)
        self.assertEqual(verdict, "undetermined")
        self.assertIn(ABSENT_MARK, detail["why"])
        rows = [{"file": "deploy.sh", "line": 7, "identity": verdict,
                 "basis": "n/a", "identity_detail": detail}]
        self.assertEqual(unmeasurable_here(rows), ["deploy.sh:7"])

    def test_undetermined_from_environment_is_not_counted_as_unmeasurable(self):
        """Каталог из ОКРУЖЕНИЯ — тоже `undetermined`, но это предмет ADR-356,
        а не «хост не тот». Смешать их значило бы отказывать всегда."""
        rows = [{"file": "DEPLOY.sh", "line": 50, "identity": "undetermined",
                 "basis": "n/a", "identity_detail": {
                     "why": "каталог задаёт ОКРУЖЕНИЕ (ADR-356)"}}]
        self.assertEqual(unmeasurable_here(rows), [])

    def test_ratchet_refuses_with_code_2_when_targets_are_absent(self):
        """Собираем дерево, где приколоченная цель заведомо отсутствует, и
        требуем код 2 — не 0 и не «предмет сократился»."""
        with tempfile.TemporaryDirectory() as td:
            tree = make_repo(Path(td) / "tree")
            (tree / "scripts").mkdir()
            probe = tree / "scripts" / "ghost.sh"
            probe.write_text("#!/bin/bash\ncd /definitely/not/here\n"
                             "git status\n", encoding="utf-8")
            probe.chmod(0o755)
            git(["add", "-A"], tree)
            git(["commit", "-qm", "ghost"], tree)
            base = Path(td) / "b.json"
            base.write_text(json.dumps({"subject": []}), encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = main(["--root", str(tree), "--baseline", str(base)])
            text = out.getvalue() + err.getvalue()
        self.assertEqual(rc, 2, text)
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertIn("сокращать её по этому прогону запрещено", text)

    def test_refusal_does_not_depend_on_a_baseline_being_passed(self):
        """БЕЗ базы пустой предмет напечатал бы «✅ предмет пуст» — то же
        «не измерено», выданное за «чисто», только без храповика."""
        with tempfile.TemporaryDirectory() as td:
            tree = make_repo(Path(td) / "tree")
            (tree / "scripts").mkdir()
            probe = tree / "scripts" / "ghost.sh"
            probe.write_text("#!/bin/bash\ncd /definitely/not/here\n"
                             "git status\n", encoding="utf-8")
            probe.chmod(0o755)
            git(["add", "-A"], tree)
            git(["commit", "-qm", "ghost"], tree)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = main(["--root", str(tree)])          # база НЕ передана
            text = out.getvalue() + err.getvalue()
        self.assertEqual(rc, 2, text)
        self.assertNotIn("предмет пуст", text)


class GuardOnTheGuard(unittest.TestCase):
    """Зелёный храповик не значит ничего, пока не показано, что он умеет
    краснеть ПОИМЁННО на настоящем дереве."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="guard-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_empty_baseline_makes_the_real_tree_run_red_by_name(self):
        empty = self.tmp / "empty.json"
        empty.write_text(json.dumps({"subject": []}), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(["--root", str(REPO), "--baseline", str(empty)])
        text = out.getvalue() + err.getvalue()
        self.assertEqual(rc, 3, text)
        self.assertIn("ХРАПОВИК: предмет ВЫРОС", text)
        self.assertIn("git_autopush.sh", text,
                      "храповик обязан назвать зовы ПОИМЁННО, а не числом")

    def test_shipped_baseline_is_green_and_covers_the_measured_subject(self):
        base = REPO / "scripts" / "shell_git_cd_repo_identity_baseline.json"
        self.assertTrue(base.is_file(), "база храповика не доставлена")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(["--root", str(REPO), "--baseline", str(base)])
        self.assertIn(rc, (0,), out.getvalue() + err.getvalue())


if __name__ == "__main__":
    unittest.main()
