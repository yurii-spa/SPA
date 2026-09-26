"""Проба `ownership_door_green_on_linux`: принадлежность процесса разрешается НА LINUX.

Замер, ради которого проба написана (цикл #703, 26.09): прогон `SPA CI` 36222500219 —
первый с 26.08, доведённый до сводки, — дал девятнадцать падений в двух файлах, и все
девятнадцать несли одну строку `ps вернул 1: error: unsupported SysV option`.
`ps -A -Ewww` принимает BSD `ps` (macOS) и отвергает ЦЕЛИКОМ procps-ng (раннер:
`ps from procps-ng 4.0.4`, прогон 36265638906). Снимок процессов на Linux не снимался
вовсе ⇒ принадлежность была `OWNERSHIP_UNKNOWN` ВСЕГДА, и предохранитель
`scripts/shadow/safe_terminate.py` (ADR-452) там ничего не завершал, выглядя исправным.

Предмет пробы — ПЛАТФОРМА, поэтому она спрашивает у раннера, а не у себя: локальный
прогон на Маке отвечает о BSD `ps` и о Linux не говорит НИЧЕГО — ровно этим дефект и
прожил месяц.

Каждый тест ниже — положительный контроль: он краснеет на ОДНОМ порванном звене, и звено
названо в имени. Обратная сторона проверяется тоже: на целом контуре проба говорит
`satisfied`, а не молчит.

Сети здесь нет ни в одном тесте: ответ API — ВХОД пробы (`fetch=`). История репозитория —
тоже вход: сцена создаёт ОДНОРАЗОВЫЙ репозиторий и объявляет имя его ветки сама
(`git init -b main`), потому что `init.defaultBranch` берётся у ХОСТА и на `ubuntu-latest`
даёт `master` (ADR-479). Ни литеральной даты, ни литерального pid тут нет вовсе.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import card_acceptance as ca

PROBE = "ownership_door_green_on_linux"

#: Имя ветки одноразовой сцены. Объявлено ОДНИМ местом и передаётся `git init -b`.
FIXTURE_BRANCH = "main"

UNKNOWN_SHA = "0" * 40


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def _run(sha: str, conclusion: str | None, status: str = "completed",
         name: str = "Ownership door (Linux)") -> dict:
    return {"head_sha": sha, "conclusion": conclusion, "status": status,
            "name": name, "created_at": "2026-09-26T19:19:14Z"}


def _fetch(runs, error: str = "сеть недоступна"):
    """Ответ API как ВХОД. `runs is None` — двери не ответили."""
    def fetch(url: str):
        if runs is None:
            return None, error
        return {"workflow_runs": runs}, None
    return fetch


class Scene(unittest.TestCase):
    """Одноразовый репозиторий: вершина `origin/main`, её предок и коммит ВНЕ истории."""

    def setUp(self):
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        _git(self.root, "init", "-b", FIXTURE_BRANCH, "-q")
        _git(self.root, "config", "user.email", "t@example.invalid")
        _git(self.root, "config", "user.name", "t")
        _git(self.root, "remote", "add", "origin", "https://github.com/o/r.git")
        (self.root / "a").write_text("a", encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", "a")
        self.ancestor = _git(self.root, "rev-parse", "HEAD")
        (self.root / "b").write_text("b", encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", "b")
        self.tip = _git(self.root, "rev-parse", "HEAD")
        _git(self.root, "update-ref", f"refs/remotes/origin/{FIXTURE_BRANCH}", self.tip)
        # Коммит, которого в истории вершины НЕТ: ветка-зонд, не доставленная в main.
        _git(self.root, "checkout", "-q", "-b", "probe/side", self.ancestor)
        (self.root / "c").write_text("c", encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", "c")
        self.off_main = _git(self.root, "rev-parse", "HEAD")
        _git(self.root, "checkout", "-q", FIXTURE_BRANCH)

    def probe(self, runs, **kw):
        return ca.PROBES[PROBE](None, repo_root=str(self.root),
                                fetch=_fetch(runs, **kw))


class TheProbeIsRegisteredAndCallable(unittest.TestCase):

    def test_the_name_is_in_the_registry_so_it_will_ever_be_measured(self):
        """Незарегистрированное имя даёт unmeasured НАВСЕГДА, а выглядит как «нечем сегодня»."""
        self.assertIn(PROBE, ca.PROBES)
        self.assertIsNone(ca.validate_spec(PROBE))

    def test_the_registry_entry_points_at_this_probe_and_not_a_namesake(self):
        self.assertIs(ca.PROBES[PROBE], ca._probe_ownership_door_green_on_linux)

    def test_the_workflow_it_asks_about_exists_in_the_tree(self):
        """Проба, спрашивающая о несуществующей джобе, была бы `unmeasured` навсегда."""
        path = (Path(ca.REPO_ROOT) / ".github" / "workflows"
                / ca.OWNERSHIP_DOOR_WORKFLOW)
        self.assertTrue(path.is_file(), f"{path} нет — спрашивать не о чем")


class TheWholeContourIsGreen(Scene):

    def test_green_on_a_commit_inside_main_history_is_satisfied(self):
        v, why = self.probe([_run(self.ancestor, "success")])
        self.assertEqual(v, ca.SATISFIED, why)
        self.assertIn(self.ancestor[:9], why)

    def test_green_on_the_tip_itself_is_satisfied(self):
        v, why = self.probe([_run(self.tip, "success")])
        self.assertEqual(v, ca.SATISFIED, why)


class EachBrokenLinkIsNamed(Scene):

    def test_link_verdict__a_failing_run_is_not_satisfied(self):
        v, why = self.probe([_run(self.tip, "failure")])
        self.assertEqual(v, ca.NOT_SATISFIED, why)
        self.assertIn("failure", why)

    def test_link_delivery__green_on_a_branch_outside_main_is_unmeasured(self):
        """Зелёное на ветке-зонде не есть доставленное (класс `pr_work_arrived_on_main`)."""
        v, why = self.probe([_run(self.off_main, "success")])
        self.assertEqual(v, ca.UNMEASURED, why)
        self.assertIn("не доставлено", why)

    def test_link_identity__a_sha_this_tree_never_saw_is_unmeasured(self):
        v, why = self.probe([_run(UNKNOWN_SHA, "success")])
        self.assertEqual(v, ca.UNMEASURED, why)
        self.assertIn("неизвестен", why)

    def test_link_network__no_answer_from_the_api_is_unmeasured(self):
        v, why = self.probe(None, error="соединение закрыто")
        self.assertEqual(v, ca.UNMEASURED, why)
        self.assertIn("соединение закрыто", why)

    def test_link_population__no_runs_at_all_is_unmeasured_not_green(self):
        v, why = self.probe([])
        self.assertEqual(v, ca.UNMEASURED, why)

    def test_link_repo__a_directory_without_a_repository_is_unmeasured(self):
        with TemporaryDirectory() as td:
            v, why = ca.PROBES[PROBE](None, repo_root=td,
                                      fetch=_fetch([_run(self.tip, "success")]))
        self.assertEqual(v, ca.UNMEASURED, why)
        self.assertIn("нет репозитория", why)

    def test_link_origin__an_origin_that_is_not_github_is_unmeasured(self):
        _git(self.root, "remote", "set-url", "origin", "/tmp/somewhere.git")
        v, why = self.probe([_run(self.tip, "success")])
        self.assertEqual(v, ca.UNMEASURED, why)


class NotMeasuredIsNeverPassedOffAsClean(Scene):

    def test_a_cancelled_run_is_not_a_verdict(self):
        """Отмена — НЕ «не падало». Принять её за чистоту значит выдать НЕ ИЗМЕРЕНО за успех."""
        v, why = self.probe([_run(self.tip, "cancelled")])
        self.assertEqual(v, ca.UNMEASURED, why)

    def test_a_running_run_is_skipped_and_the_verdict_below_it_is_taken(self):
        v, why = self.probe([_run(self.tip, None, status="in_progress"),
                             _run(self.ancestor, "success")])
        self.assertEqual(v, ca.SATISFIED, why)
        self.assertIn("пропущено без вердикта: 1", why)

    def test_a_window_full_of_cancellations_is_unmeasured(self):
        v, why = self.probe([_run(self.tip, "cancelled")] * 3)
        self.assertEqual(v, ca.UNMEASURED, why)
        self.assertIn("вердикта нет ни у одного", why)

    def test_a_success_without_a_sha_names_nothing_and_is_unmeasured(self):
        v, why = self.probe([_run("", "success")])
        self.assertEqual(v, ca.UNMEASURED, why)


class TheVerdictIsNotMatchedBySubSTRING(Scene):
    """Проба обязана читать ПОЛЕ вердикта, а не искать слово в ответе (ADR-333)."""

    def test_a_failure_whose_name_contains_the_word_success_is_not_satisfied(self):
        v, why = self.probe([_run(self.tip, "failure", name="success door")])
        self.assertEqual(v, ca.NOT_SATISFIED, why)

    def test_a_conclusion_that_merely_contains_success_is_not_success(self):
        v, why = self.probe([_run(self.tip, "unsuccessful")])
        self.assertEqual(v, ca.NOT_SATISFIED, why)


if __name__ == '__main__':
    unittest.main()
