"""Сторож живости CI на PR — ADR-145.

Авария 2026-08-26 (PR #46): событие `pull_request` не создало НИ ОДНОГО прогона
Actions. Не «прогон упал» — прогона не было вовсе. На странице PR стояла зелёная
галочка стороннего деплоя, и PR выглядел проверенным.

Каждый тест ниже — эта авария или её обратная сторона. Сеть не трогается: сборщик
принимает `fetch` входом.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "check_pr_ci_runs", REPO / "scripts" / "check_pr_ci_runs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load()


def _fetch(pulls, runs_by_sha, boom_on=None):
    """Поддельный API. `boom_on` — url-подстрока, на которой он ОТКАЗЫВАЕТ."""
    def fetch(url):
        if boom_on and boom_on in url:
            raise OSError("сеть недоступна")
        if "/pulls?" in url:
            return pulls
        sha = url.split("head_sha=")[1].split("&")[0]
        return {"workflow_runs": runs_by_sha.get(sha, [])}
    return fetch


def _pull(number, sha, title="проба"):
    return {"number": number, "title": title, "head": {"sha": sha}}


class TheOriginalAccidentIsCaught(unittest.TestCase):
    """Положительный контроль: воспроизведённая авария обязана красить сторожа."""

    def test_a_head_with_zero_runs_is_the_defect(self):
        rep = M.audit("o/r", _fetch([_pull(46, "c7586a5")], {"c7586a5": []}))
        self.assertEqual(rep["state"], M.NO_RUNS)
        self.assertEqual(M.exit_code(rep), M.EXIT_DEFECT)

    def test_a_third_party_green_tick_does_not_count_as_a_run(self):
        """Сердце аварии: галочка БЫЛА, прогонов НЕ БЫЛО — и PR выглядел зелёным.

        Считай сторож любую проверку прогоном, он молчал бы ровно в том случае,
        ради которого написан.
        """
        rep = M.audit("o/r", _fetch(
            [_pull(46, "c7586a5")],
            {"c7586a5": [{"name": "Cloudflare Pages", "conclusion": "success"}]}))
        self.assertEqual(rep["state"], M.NO_RUNS)

    def test_the_defect_names_the_pr_and_the_sha(self):
        """«Что-то не так» бесполезно: сторож НАЗЫВАЕТ, а не сигналит."""
        rep = M.audit("o/r", _fetch([_pull(46, "c7586a5")], {"c7586a5": []}))
        text = M.render(rep)
        self.assertIn("#46", text)
        self.assertIn("c7586a5", text)

    def test_one_bad_pr_among_good_ones_still_reddens(self):
        """Иначе один проверенный PR прикрывал бы непроверенный соседний."""
        rep = M.audit("o/r", _fetch(
            [_pull(41, "aaaaaaa"), _pull(46, "c7586a5")],
            {"aaaaaaa": [{"name": "SPA CI"}], "c7586a5": []}))
        self.assertEqual(rep["state"], M.NO_RUNS)


class TheReverseControl(unittest.TestCase):
    """Обратная сторона: сторож, который краснеет всегда, — не сторож."""

    def test_a_head_with_a_real_run_is_checked(self):
        rep = M.audit("o/r", _fetch(
            [_pull(44, "7543ba7")], {"7543ba7": [{"name": "SPA CI"}]}))
        self.assertEqual(rep["state"], M.CHECKED)
        self.assertEqual(M.exit_code(rep), M.EXIT_OK)

    def test_a_failing_run_is_still_a_run(self):
        """Сторож отвечает на «прогон БЫЛ?», а не «прогон зелёный?».

        Красный CI ловят другие проверки. Смешать два вопроса — значит получить
        сторожа, который отвечает не на свой (`.claude/rules/deployment.md`).
        """
        rep = M.audit("o/r", _fetch(
            [_pull(44, "7543ba7")],
            {"7543ba7": [{"name": "SPA CI", "conclusion": "failure"}]}))
        self.assertEqual(rep["state"], M.CHECKED)

    def test_no_open_pulls_is_not_a_defect(self):
        rep = M.audit("o/r", _fetch([], {}))
        self.assertEqual(rep["state"], M.CHECKED)
        self.assertEqual(M.exit_code(rep), M.EXIT_OK)


class AbsenceOfMeasurementIsItsOwnOutcome(unittest.TestCase):
    """Инвариант #17: молчание сторожа обязано отличаться от его одобрения."""

    def test_network_failure_on_runs_is_unchecked_not_ok(self):
        rep = M.audit("o/r", _fetch([_pull(46, "c7586a5")], {}, boom_on="actions/runs"))
        self.assertEqual(rep["state"], M.UNCHECKED)
        self.assertEqual(M.exit_code(rep), M.EXIT_UNMEASURED)
        self.assertIsNone(rep["pulls"][0]["runs"])

    def test_network_failure_on_the_pull_list_is_unchecked_not_ok(self):
        rep = M.audit("o/r", _fetch([], {}, boom_on="/pulls?"))
        self.assertEqual(rep["state"], M.UNCHECKED)
        self.assertEqual(M.exit_code(rep), M.EXIT_UNMEASURED)

    def test_a_pull_without_a_sha_is_unchecked_not_zero_runs(self):
        """«Не с чем сверять» ≠ «прогонов ноль» — иначе мусор в ответе API станет аварией."""
        rep = M.audit("o/r", _fetch([{"number": 9, "title": "x", "head": {}}], {}))
        self.assertEqual(rep["state"], M.UNCHECKED)

    def test_the_three_outcomes_have_three_different_exit_codes(self):
        """Два кода на три исхода — это и есть класс, который инвариант запрещает."""
        codes = {M.EXIT_OK, M.EXIT_DEFECT, M.EXIT_UNMEASURED}
        self.assertEqual(len(codes), 3)

    def test_a_defect_outranks_an_unmeasured_neighbour(self):
        """Найденный дефект не должен теряться за «не измерили соседа»."""
        rep = M.audit("o/r", _fetch(
            [_pull(46, "c7586a5"), {"number": 9, "title": "x", "head": {}}],
            {"c7586a5": []}))
        self.assertEqual(rep["state"], M.NO_RUNS)

    def test_junk_from_the_api_never_raises(self):
        for junk in (None, {}, "text", 42):
            with self.subTest(junk=junk):
                rep = M.audit("o/r", lambda url, j=junk: j)
                self.assertIn(rep["state"], {M.CHECKED, M.NO_RUNS, M.UNCHECKED})


class TheGuardCannotLiveOnTheEventItGuards(unittest.TestCase):
    """Самое важное утверждение файла — и его легче всего потерять при правке.

    Сторож, запускаемый событием `pull_request`, НЕ СПОСОБЕН увидеть, что это
    событие не сработало: не запустился CI — не запустился и он. Вход обязан быть
    независимым.
    """

    def setUp(self):
        self.wf = (REPO / ".github" / "workflows" / "pr-ci-liveness.yml").read_text(
            encoding="utf-8")

    def test_the_workflow_exists(self):
        self.assertTrue(self.wf.strip())

    def test_it_runs_on_a_schedule(self):
        self.assertIn("schedule:", self.wf)
        self.assertIn("cron:", self.wf)

    def test_it_does_not_trigger_on_pull_request(self):
        """Ровно то, ради чего файл написан: вход НЕ тот, что сторожим."""
        self.assertNotIn("pull_request:", self.wf,
                         "сторож повешен на событие, которое сам сторожит — "
                         "он не увидит его отсутствия")

    def test_it_keeps_a_manual_entrance(self):
        """Без ручного входа восстановление после аварии упирается в хаки."""
        self.assertIn("workflow_dispatch:", self.wf)

    def test_it_calls_the_script_that_exists(self):
        self.assertIn("check_pr_ci_runs.py", self.wf)
        self.assertTrue((REPO / "scripts" / "check_pr_ci_runs.py").is_file())

    def test_it_asks_for_actions_read_permission(self):
        """Без него запрос прогонов вернёт отказ, и сторож станет вечным `unchecked`."""
        self.assertIn("actions: read", self.wf)


class EveryWorkflowKeepsAManualEntrance(unittest.TestCase):
    """Обход аварии не должен упираться в запрещённые приёмы.

    Когда событие не срабатывает, единственный законный способ получить проверку —
    ручной запуск: пустой коммит и «закрыть-открыть PR» запрещены прямо.
    """

    def test_every_pr_gating_workflow_can_be_dispatched(self):
        wf_dir = REPO / ".github" / "workflows"
        self.assertTrue(wf_dir.is_dir())
        files = sorted(wf_dir.glob("*.yml"))
        self.assertTrue(files, "workflow'ов не найдено — проверка ничего не значит")
        for f in files:
            text = f.read_text(encoding="utf-8")
            if "pull_request:" not in text:
                continue  # не гейтит PR — ручной вход ему не обязателен
            with self.subTest(workflow=f.name):
                self.assertIn("workflow_dispatch:", text,
                              f"{f.name} гейтит PR, но запустить его вручную нельзя — "
                              "после несработавшего события проверку не добрать")


if __name__ == "__main__":
    unittest.main()
