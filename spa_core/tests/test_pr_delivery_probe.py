"""Контроль пробы приёмки `pr_work_arrived_on_main` — ADR-477, `.claude/rules/acceptance.md` §3.

Правило требует от НОВОЙ пробы ровно этого: зелёная на целом контуре, красная на
КАЖДОМ порванном звене — с названным звеном, — и непроходимая подстрокой.

Контур: реестр проб → порог → репозиторий → адрес origin → список PR → файлы PR →
дверь к базе → часы → вердикт. Ни сеть, ни git, ни календарь тесты не трогают: всё
перечисленное приходит входами.

FROZEN-DATE-OK: injected-clock — якорь NOW = datetime(2026, 9, 25, …) передаётся
АРГУМЕНТОМ в C._probe_pr_work_arrived_on_main(..., now=…), и даты PR в фикстурах —
литералы; обе стороны замера закреплены, стенные часы в вердикт не входят.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring import card_acceptance as C

REPO = Path(__file__).resolve().parents[2]

NOW = datetime(2026, 9, 25, 23, 30, tzinfo=timezone.utc)
BORN_PR50 = "2026-08-29T03:00:48Z"
LOST_PATH = "docs/research/RS-portfolio-cio-audit-2026-08-29.md"

PROBE = "pr_work_arrived_on_main"


def _pull(number, created_at, title="проба", draft=True):
    return {"number": number, "created_at": created_at, "title": title,
            "draft": draft, "base": {"ref": "main"}}


def _fetch(pulls, files_by_pr, boom_on=None):
    """Поддельный `_github_json`: возвращает `(данные, причина)`, как настоящий."""
    def fetch(url):
        if boom_on and boom_on in url:
            return None, "сеть недоступна"
        if "/pulls?" in url:
            return pulls, None
        number = int(url.split("/pulls/")[1].split("/")[0])
        return files_by_pr.get(number, []), None
    return fetch


def _added(*paths):
    return [{"filename": p, "status": "added"} for p in paths]


def _door(present=(), boom=False):
    def exists_on_base(base_ref, path):
        if boom:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "_probe_ctl_census", REPO / "scripts" / "pr_delivery_census.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            raise mod.BaseUnreadable("ветка не найдена локально")
        return path in present
    return exists_on_base


def _run(pulls, files, door, *, now=NOW, arg=None, root=None):
    return C._probe_pr_work_arrived_on_main(
        arg, repo_root=root or str(REPO), fetch=_fetch(pulls, files),
        now=now, exists_on_base=door)


class TheWholeCircuitIsGreen(unittest.TestCase):
    def test_every_added_path_present_on_main_satisfies_the_criterion(self):
        state, why = _run([_pull(50, BORN_PR50)], {50: _added(LOST_PATH)},
                          _door(present=(LOST_PATH,)))
        self.assertEqual(state, C.SATISFIED, why)

    def test_a_pr_out_of_reach_does_not_block_the_criterion_but_is_counted(self):
        """PR из одних правок прибору неразрешим — он НАЗВАН числом, а не проглочен."""
        state, why = _run([_pull(9, BORN_PR50)],
                          {9: [{"filename": "data/x.json", "status": "modified"}]}, _door())
        self.assertEqual(state, C.SATISFIED, why)
        # Именно ЧИСЛО вне досягаемости, а не слово: «вне досягаемости прибора 0» при
        # одном таком PR было бы тихой потерей населения.
        self.assertIn("вне досягаемости прибора 1", why)

    def test_a_fresh_pr_with_absent_paths_does_not_fail_the_criterion(self):
        born = (NOW - timedelta(days=2)).isoformat()
        state, _ = _run([_pull(51, born)], {51: _added("docs/new.md")}, _door(present=()))
        self.assertEqual(state, C.SATISFIED)


class EachBrokenLinkRedens(unittest.TestCase):
    """По одному звену за тест, и звено названо в имени теста."""

    def test_link_delivery_a_long_open_pr_with_paths_absent_on_main(self):
        state, why = _run([_pull(50, BORN_PR50)], {50: _added(LOST_PATH)}, _door(present=()))
        self.assertEqual(state, C.NOT_SATISFIED)
        self.assertIn("#50", why)
        self.assertIn(LOST_PATH, why)

    def test_link_base_door_refusing_is_unmeasured_not_a_failure(self):
        state, why = _run([_pull(50, BORN_PR50)], {50: _added(LOST_PATH)}, _door(boom=True))
        self.assertEqual(state, C.UNMEASURED, why)
        # Причина обязана назвать ИМЕННО дверь: «не измерено» без причины — то же
        # молчание, только с вежливым словом.
        self.assertIn("база не прочитана", why)
        self.assertIn("ветка не найдена", why)

    def test_link_pulls_endpoint_refusing_is_unmeasured(self):
        state, why = C._probe_pr_work_arrived_on_main(
            None, repo_root=str(REPO), fetch=_fetch([], {}, boom_on="/pulls?"),
            now=NOW, exists_on_base=_door())
        self.assertEqual(state, C.UNMEASURED, why)

    def test_link_files_endpoint_refusing_is_unmeasured(self):
        state, why = C._probe_pr_work_arrived_on_main(
            None, repo_root=str(REPO), fetch=_fetch([_pull(50, BORN_PR50)], {},
                                                    boom_on="/files"),
            now=NOW, exists_on_base=_door())
        self.assertEqual(state, C.UNMEASURED, why)

    def test_link_repository_missing_is_unmeasured_and_names_the_root(self):
        state, why = _run([_pull(50, BORN_PR50)], {50: _added(LOST_PATH)}, _door(),
                          root="/nonexistent-tree-b7f3a1")
        self.assertEqual(state, C.UNMEASURED)
        self.assertIn("/nonexistent-tree-b7f3a1", why)

    def test_link_threshold_argument_that_is_not_a_number_is_unmeasured(self):
        state, why = _run([_pull(50, BORN_PR50)], {50: _added(LOST_PATH)}, _door(),
                          arg="позавчера")
        self.assertEqual(state, C.UNMEASURED)
        self.assertIn("порог", why)

    def test_link_the_clock_reaches_the_verdict(self):
        """Тот же PR при двух `now` обязан давать РАЗНЫЕ вердикты.

        Совпади они — часы в вердикт не входят, и порог сторожил бы воздух
        (`.claude/rules/deployment.md`: «половина инъекции — та же бомба»).
        """
        args = ([_pull(50, BORN_PR50)], {50: _added(LOST_PATH)}, _door(present=()))
        late, _ = _run(*args, now=NOW)
        early, _ = _run(*args, now=datetime(2026, 8, 30, tzinfo=timezone.utc))
        self.assertEqual(late, C.NOT_SATISFIED)
        self.assertEqual(early, C.SATISFIED)


class TheProbeIsRegisteredAndCannotBePassedByText(unittest.TestCase):

    def test_the_probe_is_in_the_registry_and_the_spec_validates(self):
        self.assertIn(PROBE, C.PROBES)
        self.assertIsNone(C.validate_spec(PROBE))
        self.assertIsNone(C.validate_spec(f"{PROBE}:14"))

    def test_a_typo_in_the_name_is_refused_at_declaration_time(self):
        self.assertIsNotNone(C.validate_spec("pr_work_arrived_on_maim"))

    def test_a_pr_titled_delivered_is_still_not_satisfied(self):
        """ADR-333: проба меряет исход. Слово «доставлено» её не проходит."""
        state, _ = _run([_pull(50, BORN_PR50, "ДОСТАВЛЕНО: всё доехало, satisfied")],
                        {50: _added(LOST_PATH)}, _door(present=()))
        self.assertEqual(state, C.NOT_SATISFIED)

    def test_the_three_verdicts_are_three_distinct_values(self):
        self.assertEqual(len({C.SATISFIED, C.NOT_SATISFIED, C.UNMEASURED}), 3)


if __name__ == "__main__":
    unittest.main()
