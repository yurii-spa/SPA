"""Проба `ci_main_verdict_green`: вердикт CI о ВЕРШИНЕ main — приёмка карточки красного CI.

Замер 24.09 (цикл #692), ради которого проба написана: последний зелёный `SPA Tests`
о `main` — 26.08; за 29 суток после него **627 `failure`, 82 `cancelled`, ни одного
`success`**, и ни один отчёт цикла об этом не сказал. Механизм молчания назван в
карточке: цикл докладывал «соседи N passed» по СВОЕМУ набору файлов, а предписанный
прогон четырёх каталогов — тот, что гейтит CI, — не запускал никто.

Каждый тест здесь — положительный контроль: он краснеет на конкретном ПОРВАННОМ
звене, и звено названо в имени теста. Обратная сторона проверяется тоже — что на
исправном контуре проба говорит `satisfied`, а не молчит.

Сети здесь нет ни в одном тесте: ответ API — ВХОД пробы (`fetch=`), а не окружение.
Тест, ходящий в живой GitHub, отвечал бы на вопрос «что сегодня на origin», а не
«верно ли проба разбирает ответ», и краснел бы от чужого пуша. Ни литеральной даты,
ни литерального pid тут нет вовсе.
"""
from __future__ import annotations

import unittest

from spa_core.monitoring import card_acceptance as ca

HEAD = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
OLD = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
RUNS_URL_MARK = "/actions/workflows/"


def _run(sha: str, conclusion: str | None, status: str = "completed") -> dict:
    return {"head_sha": sha, "conclusion": conclusion, "status": status,
            "created_at": "2026-09-24T10:32:28Z"}


def _fetch(runs: list | None, head_sha: str | None = HEAD,
           runs_error: str = "boom", head_error: str = "boom"):
    """Ответ API как ВХОД. `None` в runs/head_sha = этой двери не ответили."""
    def fetch(url: str):
        if RUNS_URL_MARK in url:
            if runs is None:
                return None, runs_error
            return {"workflow_runs": runs}, None
        if head_sha is None:
            return None, head_error
        return {"sha": head_sha}, None
    return fetch


class RepoRoot:
    """Корень, который _is_git_repo признаёт. Настоящий репозиторий — сам worktree."""


import os as _os
_REPO = ca.REPO_ROOT


class TheProbeIsRegisteredAndCallable(unittest.TestCase):

    def test_the_name_is_in_the_registry_so_it_will_ever_be_measured(self):
        """Незарегистрированное имя даёт unmeasured НАВСЕГДА, а выглядит как «нечем сегодня»."""
        self.assertIn("ci_main_verdict_green", ca.PROBES)
        self.assertIsNone(ca.validate_spec("ci_main_verdict_green"))

    def test_the_registry_entry_points_at_this_probe_and_not_a_namesake(self):
        self.assertIs(ca.PROBES["ci_main_verdict_green"],
                      ca._probe_ci_main_verdict_green)


class TheVerdictIsReadFromOrigin(unittest.TestCase):

    def test_green_on_the_head_is_satisfied(self):
        """Обратная сторона: на исправном контуре проба обязана ГОВОРИТЬ, а не молчать."""
        v, d = ca._probe_ci_main_verdict_green(
            None, repo_root=_REPO, fetch=_fetch([_run(HEAD, "success")]))
        self.assertEqual(v, ca.SATISFIED, d)
        self.assertIn(HEAD[:9], d)

    def test_failure_is_not_satisfied_and_names_the_sha(self):
        v, d = ca._probe_ci_main_verdict_green(
            None, repo_root=_REPO, fetch=_fetch([_run(HEAD, "failure")]))
        self.assertEqual(v, ca.NOT_SATISFIED, d)
        self.assertIn("failure", d)
        self.assertIn(HEAD[:9], d)

    def test_a_failure_is_never_reported_as_merely_unmeasured(self):
        """Находка обязана быть находкой: unmeasured читается как «нечем проверить»."""
        v, _ = ca._probe_ci_main_verdict_green(
            None, repo_root=_REPO, fetch=_fetch([_run(HEAD, "failure")]))
        self.assertNotEqual(v, ca.UNMEASURED)


class CancelledIsNotAVerdict(unittest.TestCase):
    """Порванное звено: отмена, принятая за «не падало», — подделка чистоты (инв. #17)."""

    def test_all_cancelled_is_unmeasured_not_satisfied(self):
        v, d = ca._probe_ci_main_verdict_green(
            None, repo_root=_REPO,
            fetch=_fetch([_run(HEAD, "cancelled"), _run(OLD, "cancelled")]))
        self.assertEqual(v, ca.UNMEASURED, d)
        self.assertNotEqual(v, ca.SATISFIED)

    def test_cancelled_does_not_mask_a_failure_behind_it(self):
        """Отмена пропускается, но вердикт за ней обязан быть найден, а не потерян."""
        v, d = ca._probe_ci_main_verdict_green(
            None, repo_root=_REPO,
            fetch=_fetch([_run(HEAD, "cancelled"), _run(HEAD, "failure")]))
        self.assertEqual(v, ca.NOT_SATISFIED, d)

    def test_a_run_still_in_flight_is_not_a_verdict(self):
        """Звено `status`, ИЗОЛИРОВАННОЕ от звена `conclusion`.

        Первая редакция этого теста давала незавершённому прогону `conclusion=None`
        — и мутация, снявшая проверку `status`, ВЫЖИЛА: отказ давала вторая
        проверка, а не та, что проверяется. Поле `conclusion` осмысленно только при
        `status == completed`; доверять ему раньше и есть предмет этого теста.
        """
        v, _ = ca._probe_ci_main_verdict_green(
            None, repo_root=_REPO,
            fetch=_fetch([_run(HEAD, "success", status="in_progress")]))
        self.assertEqual(v, ca.UNMEASURED)

    def test_a_queued_run_carrying_a_stale_conclusion_is_not_a_verdict(self):
        v, _ = ca._probe_ci_main_verdict_green(
            None, repo_root=_REPO,
            fetch=_fetch([_run(HEAD, "success", status="queued"),
                          _run(HEAD, "failure")]))
        self.assertEqual(v, ca.NOT_SATISFIED)

    def test_the_skipped_count_is_reported_so_partial_coverage_is_visible(self):
        _, d = ca._probe_ci_main_verdict_green(
            None, repo_root=_REPO,
            fetch=_fetch([_run(HEAD, "cancelled"), _run(HEAD, "success")]))
        self.assertIn("1", d)


class GreenOnAStaleShaIsNotGreenOnTheHead(unittest.TestCase):
    """Зелёный о позавчерашнем коммите ничего не говорит о вершине — и выглядит как разрешение."""

    def test_success_on_an_older_sha_is_unmeasured(self):
        v, d = ca._probe_ci_main_verdict_green(
            None, repo_root=_REPO, fetch=_fetch([_run(OLD, "success")], head_sha=HEAD))
        self.assertEqual(v, ca.UNMEASURED, d)
        self.assertIn(OLD[:9], d)
        self.assertIn(HEAD[:9], d)

    def test_the_same_sha_is_what_makes_it_satisfied(self):
        """Контроль НА контроль: различие даёт именно sha, а не что-то ещё в сцене."""
        v, _ = ca._probe_ci_main_verdict_green(
            None, repo_root=_REPO, fetch=_fetch([_run(HEAD, "success")], head_sha=HEAD))
        self.assertEqual(v, ca.SATISFIED)


class EveryDoorThatDoesNotAnswerIsTheThirdOutcome(unittest.TestCase):

    def test_runs_door_silent_is_unmeasured_with_a_named_reason(self):
        v, d = ca._probe_ci_main_verdict_green(
            None, repo_root=_REPO, fetch=_fetch(None, runs_error="HTTP 503"))
        self.assertEqual(v, ca.UNMEASURED)
        self.assertIn("HTTP 503", d)

    def test_head_door_silent_is_unmeasured_and_never_satisfied(self):
        """Вторая дверь — своя. Инъекция «половиной» и есть та же бомба (правило про pid)."""
        v, d = ca._probe_ci_main_verdict_green(
            None, repo_root=_REPO,
            fetch=_fetch([_run(HEAD, "success")], head_sha=None, head_error="HTTP 404"))
        self.assertEqual(v, ca.UNMEASURED, d)
        self.assertIn("HTTP 404", d)

    def test_no_runs_at_all_is_unmeasured_not_clean(self):
        """Пустой список — «не измерено», и НЕ «не падало»: разница в том, что
        второе выглядит разрешением закрыть карточку (инв. #17)."""
        v, d = ca._probe_ci_main_verdict_green(
            None, repo_root=_REPO, fetch=_fetch([]))
        self.assertEqual(v, ca.UNMEASURED, d)
        self.assertIn("нет вовсе", d)

    def test_a_malformed_answer_is_unmeasured(self):
        def fetch(url):
            if RUNS_URL_MARK in url:
                return {"unexpected": 1}, None
            return {"sha": HEAD}, None
        v, _ = ca._probe_ci_main_verdict_green(None, repo_root=_REPO, fetch=fetch)
        self.assertEqual(v, ca.UNMEASURED)

    def test_absent_repository_is_unmeasured(self):
        v, d = ca._probe_ci_main_verdict_green(
            None, repo_root=_os.sep + _os.path.join("nonexistent", "tree"),
            fetch=_fetch([_run(HEAD, "success")]))
        self.assertEqual(v, ca.UNMEASURED, d)


class TheSlugIsReadFromTheRemote(unittest.TestCase):
    """Правило разбора НЕ копируется сюда: прибор зовётся от настоящего репозитория.

    Вторая копия мерки расходится с первой молча (ADR-220) — поэтому тест заводит
    одноразовый репозиторий, ставит ему origin и спрашивает САМ `_github_slug`.
    """

    def _repo_with_remote(self, url: str) -> str:
        import subprocess, tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        subprocess.run(["git", "init", "-q", d], check=True)
        subprocess.run(["git", "-C", d, "remote", "add", "origin", url], check=True)
        return d

    def test_a_github_remote_is_parsed_in_each_shape_it_is_written(self):
        for url in ("https://github.com/yurii-spa/SPA",
                    "https://github.com/yurii-spa/SPA.git",
                    "git@github.com:yurii-spa/SPA.git",
                    "ssh://git@github.com/yurii-spa/SPA.git"):
            with self.subTest(url=url):
                self.assertEqual(ca._github_slug(self._repo_with_remote(url)),
                                 "yurii-spa/SPA")

    def test_a_non_github_remote_is_not_invented(self):
        """Порванное звено: выдумать slug значило бы спросить не тот репозиторий."""
        self.assertIsNone(ca._github_slug(self._repo_with_remote(
            "https://gitlab.com/a/b.git")))

    def test_a_repo_without_a_remote_is_not_invented_either(self):
        import subprocess, tempfile, shutil
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        subprocess.run(["git", "init", "-q", d], check=True)
        self.assertIsNone(ca._github_slug(d))

    def test_the_probe_refuses_when_the_remote_is_not_github(self):
        v, d = ca._probe_ci_main_verdict_green(
            None, repo_root=self._repo_with_remote("https://gitlab.com/a/b.git"),
            fetch=_fetch([_run(HEAD, "success")]))
        self.assertEqual(v, ca.UNMEASURED, d)


class RunProbeWrapsFailuresAsUnmeasured(unittest.TestCase):

    def test_an_exception_inside_the_probe_is_unmeasured_never_satisfied(self):
        boom = lambda arg: (_ for _ in ()).throw(RuntimeError("x"))
        saved = ca.PROBES["ci_main_verdict_green"]
        ca.PROBES["ci_main_verdict_green"] = boom
        try:
            v, d = ca.run_probe("ci_main_verdict_green")
        finally:
            ca.PROBES["ci_main_verdict_green"] = saved
        self.assertEqual(v, ca.UNMEASURED)
        self.assertIn("RuntimeError", d)


if __name__ == "__main__":
    unittest.main()


class TheTestEnvironmentIsNotAskedOverTheNetwork(unittest.TestCase):
    """Порванное звено: живой вызов из набора отвечал бы на чужой вопрос.

    Сторож живой сети поймал это в цикле #692 на первой же редакции пробы:
    `test_every_registered_probe_returns_a_known_verdict` гоняет КАЖДУЮ пробу без
    инъекции, и моя полезла в GitHub. Отказ обязан быть НАЗВАН, а не случиться молча.
    """

    def test_without_injection_under_spa_env_ci_the_probe_refuses_by_name(self):
        import os
        saved = os.environ.get("SPA_ENV")
        os.environ["SPA_ENV"] = "ci"
        try:
            v, d = ca._probe_ci_main_verdict_green(None, repo_root=_REPO)
        finally:
            if saved is None:
                os.environ.pop("SPA_ENV", None)
            else:
                os.environ["SPA_ENV"] = saved
        self.assertEqual(v, ca.UNMEASURED, d)
        self.assertIn("SPA_ENV=ci", d)

    def test_with_injection_the_refusal_does_not_fire(self):
        """Контроль в обратную сторону: отказ про СЕТЬ, а не про окружение вообще."""
        import os
        saved = os.environ.get("SPA_ENV")
        os.environ["SPA_ENV"] = "ci"
        try:
            v, d = ca._probe_ci_main_verdict_green(
                None, repo_root=_REPO, fetch=_fetch([_run(HEAD, "success")]))
        finally:
            if saved is None:
                os.environ.pop("SPA_ENV", None)
            else:
                os.environ["SPA_ENV"] = saved
        self.assertEqual(v, ca.SATISFIED, d)
