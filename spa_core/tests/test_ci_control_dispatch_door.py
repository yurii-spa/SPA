#!/usr/bin/env python3
# LLM_FORBIDDEN
"""Батарея ДВЕРИ ЗАКАЗА контрольного прогона (ADR-1083, цикл #1229).

Каждая проверка здесь — положительный контроль НАСТОЯЩЕЙ аварии, а не украшение
(`.claude/rules/deployment.md`, § «Проверка сторожа сторожей»).

**Авария, ради которой дверь написана** (замер 2026-11-24, цикл #1228, ADR-1082): цикл
#1227 заказал ДВА контрольных прогона с промежутком 2.5 мин; второй (`45292542397`) встал
в группе `ci-control` ОЖИДАЮЩИМ, был отменён приходом расписанного `45293308721` через
346 с и вердикта не вынес НИ В ОДНУ сторону — а цикл, его заказавший, записал его номер в
заказ как якорь дельты. Дверь `cancellation_cause` объясняет это ПОСЛЕ факта; вопроса «а
что станет с моим заказом, если я подам его СЕЙЧАС» до ADR-1083 не задавал никто, потому
что заказывал прогон `curl` рукой.

Часы и сеть — ВХОДЫ (`.claude/rules/deployment.md`, § про инъекцию и § про границу
подпроцесса): иначе батарея отвечала бы на вопрос «что сегодня у GitHub», а не «цела ли
проводка». Литеральный якорь ниже — закреплённый момент сцены, обе стороны каждого
сравнения от него происходят.

# FROZEN-DATE-OK: injected-clock — якорь NOW уходит входом `now=` в
# order_control_run()/group_occupancy()/next_cron_moment(); стенных часов ни одна сцена
# не касается, подпроцессов батарея не поднимает.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "ci_control_verdict_door", ROOT / "scripts" / "ci_control_verdict.py")
cv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cv)

NOW = dt.datetime(2026, 11, 24, 2, 35, 0, tzinfo=dt.timezone.utc)

#: Объявление ровно той формы, что живёт в `ci-control.yml` на момент замера.
WF_OURS = """name: SPA CI control (sharded full suite)

on:
  schedule:
    - cron: "23 */6 * * *"   # каждые 6 ч
  workflow_dispatch:
    inputs:
      sha:
        required: false

concurrency:
  group: ci-control
  cancel-in-progress: false

jobs:
  manifest:
    runs-on: ubuntu-latest
"""


def _tree(tmp: Path, files: dict) -> Path:
    wf = tmp / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (wf / name).write_text(text, encoding="utf-8")
    return tmp


def _row(rid, status, *, event="workflow_dispatch", sha="a" * 40,
         created="2026-11-24T02:30:00Z", conclusion=None):
    return {"id": rid, "status": status, "conclusion": conclusion, "event": event,
            "head_sha": sha, "head_branch": "main", "created_at": created,
            "updated_at": created, "html_url": f"https://x/{rid}"}


def _fetch_of(runs_by_wf, *, single=None):
    """Дверь к API входом. `single` — ответ на запрос ОДНОГО прогона."""
    seen = []

    def fetch(path):
        seen.append(path)
        if "/actions/runs/" in path:
            if single is None:
                raise AssertionError("строка прогона не объявлена сценой")
            return single
        for wf, rows in runs_by_wf.items():
            if f"/workflows/{wf}/runs" in path:
                return {"workflow_runs": rows}
        return {"workflow_runs": []}

    fetch.seen = seen
    return fetch


class _Post:
    """Дверь подачи входом — и СЧЁТЧИК: «не подал» есть утверждение, а не надежда."""

    def __init__(self, code=204, raises=None):
        self.code, self.raises, self.calls = code, raises, []

    def __call__(self, path, payload):
        self.calls.append((path, payload))
        if self.raises is not None:
            raise self.raises
        return self.code


# ───────────────────── объявление воркфлоу: читается у ФАЙЛА ─────────────────

class DeclarationIsAskedOfTheFile(unittest.TestCase):
    """Группа и `cancel-in-progress` — свойство ВОРКФЛОУ, а не литерал прибора.

    Поменяй кто-нибудь `cancel-in-progress` на `true`, и механизм ПЕРЕВЕРНЁТСЯ: заказ
    станет снимать идущий прогон вместо того, чтобы встать за ним. Совет, выведенный из
    копии объявления, остался бы прежним и уверенным (класс ADR-220).
    """

    def test_block_form_is_read_whole(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            d = cv.concurrency_declaration(_tree(Path(td), {"ci-control.yml": WF_OURS}))
        self.assertEqual(d["state"], cv.DECL_READ)
        self.assertEqual(d["group"], "ci-control")
        self.assertEqual(d["cancel_in_progress"], "false")
        self.assertEqual(d["crons"], ['"23 */6 * * *"'.strip('"')])
        self.assertEqual(d["sharers"], ["ci-control.yml"])

    def test_a_neighbour_declaring_the_same_group_is_named(self):
        """Группа объявлена БЕЗ `github.ref` ⇒ вытеснить заказ вправе ЧУЖОЙ воркфлоу."""
        import tempfile
        other = WF_OURS.replace("name: SPA CI control (sharded full suite)",
                                "name: Someone else")
        with tempfile.TemporaryDirectory() as td:
            d = cv.concurrency_declaration(_tree(Path(td), {
                "ci-control.yml": WF_OURS, "zz-other.yml": other}))
        self.assertEqual(d["state"], cv.DECL_READ)
        self.assertEqual(sorted(d["sharers"]), ["ci-control.yml", "zz-other.yml"])

    def test_a_workflow_with_a_different_group_is_not_a_sharer(self):
        import tempfile
        other = WF_OURS.replace("group: ci-control", "group: spa-ci-push")
        with tempfile.TemporaryDirectory() as td:
            d = cv.concurrency_declaration(_tree(Path(td), {
                "ci-control.yml": WF_OURS, "zz-other.yml": other}))
        self.assertEqual(d["sharers"], ["ci-control.yml"])

    def test_no_concurrency_block_is_ABSENT_not_unmeasured(self):
        """«Группы нет» и «не прочитали» — РАЗНЫЕ утверждения с разным действием."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            d = cv.concurrency_declaration(_tree(Path(td), {
                "ci-control.yml": WF_OURS.split("concurrency:")[0]}))
        self.assertEqual(d["state"], cv.DECL_ABSENT)
        self.assertIsNotNone(d["why"])

    def test_missing_file_is_UNMEASURED_not_absent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            d = cv.concurrency_declaration(Path(td))
        self.assertEqual(d["state"], cv.DECL_UNMEASURED)
        self.assertIn("не прочитан", d["why"])

    def test_inline_concurrency_is_UNMEASURED_not_absent(self):
        """Форма не понята ≠ группы нет. Подставить второе было бы догадкой."""
        import tempfile
        inline = WF_OURS.replace(
            "concurrency:\n  group: ci-control\n  cancel-in-progress: false",
            "concurrency: {group: ci-control, cancel-in-progress: false}")
        with tempfile.TemporaryDirectory() as td:
            d = cv.concurrency_declaration(_tree(Path(td), {"ci-control.yml": inline}))
        self.assertEqual(d["state"], cv.DECL_UNMEASURED)
        self.assertIn("инлайн", d["why"])

    def test_an_unreadable_neighbour_is_UNMEASURED_not_an_empty_sharer_list(self):
        """Пустой перечень соседей совпал бы с честным нулём — класс «ложный ноль»."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tree = _tree(Path(td), {"ci-control.yml": WF_OURS})
            (tree / ".github" / "workflows" / "broken.yml").write_bytes(b"\xff\xfe\x00q")
            d = cv.concurrency_declaration(tree)
        self.assertEqual(d["state"], cv.DECL_UNMEASURED)
        self.assertIn("broken.yml", d["why"])


# ─────────────────────────── такт расписания ─────────────────────────────────

class ScheduleIsParsedOrNamedUnparsed(unittest.TestCase):
    """Ближайший третий в группе — расписанный прогон, и его момент НАЗЫВАЕТСЯ."""

    def test_the_declared_form_gives_the_next_moment(self):
        self.assertEqual(cv.next_cron_moment("23 */6 * * *", NOW),
                         dt.datetime(2026, 11, 24, 6, 23, tzinfo=dt.timezone.utc))

    def test_the_moment_is_strictly_later_than_now(self):
        at = dt.datetime(2026, 11, 24, 6, 23, tzinfo=dt.timezone.utc)
        self.assertEqual(cv.next_cron_moment("23 */6 * * *", at),
                         dt.datetime(2026, 11, 24, 12, 23, tzinfo=dt.timezone.utc))

    def test_it_crosses_midnight(self):
        at = dt.datetime(2026, 11, 24, 19, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(cv.next_cron_moment("23 */6 * * *", at),
                         dt.datetime(2026, 11, 25, 0, 23, tzinfo=dt.timezone.utc))

    def test_an_unparsed_form_is_None_not_a_guess(self):
        for bad in ("23 */6 * *", "23 */6 1 * *", "@daily", "", "x */6 * * *",
                    "23 */0 * * *", "99 */6 * * *"):
            with self.subTest(bad=bad):
                self.assertIsNone(cv.next_cron_moment(bad, NOW))


# ──────────────────── занятость группы: четыре исхода ────────────────────────

class OccupancyHasFourOutcomes(unittest.TestCase):
    """`free` · `queued_behind` · `would_displace` · `unmeasured` — инв. #17."""

    def setUp(self):
        self.decl = {"state": cv.DECL_READ, "group": "ci-control",
                     "cancel_in_progress": "false", "crons": ["23 */6 * * *"],
                     "sharers": ["ci-control.yml"], "why": None}

    def test_empty_group_is_free(self):
        occ = cv.group_occupancy(fetch=_fetch_of({"ci-control.yml": [
            _row("1", "completed", conclusion="failure")]}),
            decl=self.decl, now=NOW)
        self.assertEqual(occ["state"], cv.OCC_FREE)
        self.assertEqual(occ["next_scheduled"], "2026-11-24T06:23:00+00:00")

    def test_a_running_run_with_no_pending_is_queued_behind(self):
        occ = cv.group_occupancy(fetch=_fetch_of({"ci-control.yml": [
            _row("45304210098", "in_progress")]}), decl=self.decl, now=NOW)
        self.assertEqual(occ["state"], cv.OCC_QUEUED_BEHIND)
        self.assertEqual([r["id"] for r in occ["running"]], ["45304210098"])
        self.assertEqual(occ["waiting"], [])

    def test_a_pending_run_means_my_order_would_displace_it(self):
        """РОВНО авария ADR-1082: ожидающий в группе один, третий его отменяет."""
        occ = cv.group_occupancy(fetch=_fetch_of({"ci-control.yml": [
            _row("45293308721", "in_progress", event="schedule"),
            _row("45292542397", "queued")]}), decl=self.decl, now=NOW)
        self.assertEqual(occ["state"], cv.OCC_WOULD_DISPLACE)
        self.assertEqual([r["id"] for r in occ["waiting"]], ["45292542397"])

    def test_a_pending_run_alone_also_refuses(self):
        """`queued` без идущего: «ждёт раннера» и «ждёт группу» строкой НЕРАЗЛИЧИМЫ,

        и ответ fail-CLOSED — лишний отказ дешевле убитого чужого замера.
        """
        occ = cv.group_occupancy(fetch=_fetch_of({"ci-control.yml": [
            _row("7", "queued")]}), decl=self.decl, now=NOW)
        self.assertEqual(occ["state"], cv.OCC_WOULD_DISPLACE)

    def test_a_dead_api_is_UNMEASURED_not_free(self):
        """Fail-OPEN здесь тише красного и потому опаснее: «свободно» пригласило бы

        подачу, которая отменила бы чужой прогон.
        """
        def boom(path):
            raise urllib.error.URLError("сеть недоступна")
        occ = cv.group_occupancy(fetch=boom, decl=self.decl, now=NOW)
        self.assertEqual(occ["state"], cv.OCC_UNMEASURED)
        self.assertIn("не прочитан", occ["why"])

    def test_a_listing_without_rows_is_UNMEASURED_not_empty(self):
        occ = cv.group_occupancy(fetch=lambda p: {"total_count": 0},
                                 decl=self.decl, now=NOW)
        self.assertEqual(occ["state"], cv.OCC_UNMEASURED)
        self.assertIn("строк не несёт", occ["why"])

    def test_an_unknown_status_is_UNMEASURED_not_ignored(self):
        """Молча пропустить незнакомый статус значило бы ответить «в группе пусто»."""
        occ = cv.group_occupancy(fetch=_fetch_of({"ci-control.yml": [
            _row("9", "hibernating")]}), decl=self.decl, now=NOW)
        self.assertEqual(occ["state"], cv.OCC_UNMEASURED)
        self.assertIn("hibernating", occ["why"])

    def test_EVERY_sharer_is_asked_not_only_our_own_file(self):
        """Спроси только свой файл — и чужой сосед по группе остался бы невидимым.

        Сцена РАЗЛИЧАЮЩАЯ: ожидающий живёт ТОЛЬКО в соседнем воркфлоу, и у меры,
        спрашивающей один файл, ответ был бы `free`.
        """
        decl = dict(self.decl, sharers=["ci-control.yml", "zz-other.yml"])
        fetch = _fetch_of({"ci-control.yml": [],
                           "zz-other.yml": [_row("55", "queued", event="schedule")]})
        occ = cv.group_occupancy(fetch=fetch, decl=decl, now=NOW)
        self.assertEqual(occ["state"], cv.OCC_WOULD_DISPLACE)
        self.assertEqual(occ["waiting"][0]["workflow"], "zz-other.yml")
        self.assertEqual(sum("zz-other.yml" in p for p in fetch.seen), 1)

    def test_an_unmeasured_declaration_poisons_the_occupancy(self):
        occ = cv.group_occupancy(
            fetch=_fetch_of({}),
            decl={"state": cv.DECL_UNMEASURED, "group": None,
                  "cancel_in_progress": None, "crons": [], "sharers": [],
                  "why": "воркфлоу не прочитан"}, now=NOW)
        self.assertEqual(occ["state"], cv.OCC_UNMEASURED)

    def test_an_absent_group_is_free_not_unmeasured(self):
        """Группы нет ⇒ вытеснять нечему. Это заработанный ответ, а не осторожность."""
        occ = cv.group_occupancy(
            fetch=_fetch_of({}),
            decl={"state": cv.DECL_ABSENT, "group": None, "cancel_in_progress": None,
                  "crons": [], "sharers": [], "why": "группы нет"}, now=NOW)
        self.assertEqual(occ["state"], cv.OCC_FREE)


# ───────────────────────── заказ: подача судится ДО ──────────────────────────

class TheOrderIsJudgedBeforeItIsPosted(unittest.TestCase):
    """Гейт стои́т ДО подачи, и «не подал» проверяется СЧЁТЧИКОМ подачи."""

    def _tree(self, td, wf=WF_OURS):
        return _tree(Path(td), {"ci-control.yml": wf})

    def test_a_pending_run_refuses_and_NOTHING_is_posted(self):
        import tempfile
        post = _Post()
        with tempfile.TemporaryDirectory() as td:
            doc = cv.order_control_run(
                "b" * 40,
                fetch=_fetch_of({"ci-control.yml": [
                    _row("45293308721", "in_progress", event="schedule"),
                    _row("45292542397", "queued")]}),
                post=post, root=self._tree(td), now=NOW)
        self.assertEqual(doc["state"], cv.ORD_REFUSED)
        self.assertEqual(post.calls, [], "подача состоялась ВОПРЕКИ отказу гейта")
        self.assertEqual(cv.order_exit_code(doc), 3)
        self.assertIn("45292542397", doc["why"])

    def test_an_unmeasured_group_refuses_and_NOTHING_is_posted(self):
        import tempfile
        post = _Post()

        def boom(path):
            raise urllib.error.URLError("сеть недоступна")
        with tempfile.TemporaryDirectory() as td:
            doc = cv.order_control_run("b" * 40, fetch=boom, post=post,
                                       root=self._tree(td), now=NOW)
        self.assertEqual(doc["state"], cv.ORD_UNMEASURED)
        self.assertEqual(post.calls, [], "вслепую подали заказ")
        self.assertEqual(cv.order_exit_code(doc), 2)

    def test_cancel_in_progress_true_INVERTS_the_mechanism_and_refuses(self):
        """Объявление воркфлоу изменилось ⇒ прежний совет был бы уверенным и неверным."""
        import tempfile
        post = _Post()
        flipped = WF_OURS.replace("cancel-in-progress: false",
                                  "cancel-in-progress: true")
        with tempfile.TemporaryDirectory() as td:
            doc = cv.order_control_run(
                "b" * 40,
                fetch=_fetch_of({"ci-control.yml": [_row("1", "in_progress")]}),
                post=post, root=self._tree(td, flipped), now=NOW)
        self.assertEqual(doc["state"], cv.ORD_REFUSED)
        self.assertEqual(post.calls, [])
        self.assertIn("cancel-in-progress: true", doc["why"])

    def test_the_bypass_posts_AND_is_printed(self):
        """Обход осознанный, и он ПЕЧАТАЕТСЯ: молчащий обход хуже ошибки."""
        import tempfile
        post = _Post()
        born = "2026-11-24T02:36:00Z"
        with tempfile.TemporaryDirectory() as td:
            doc = cv.order_control_run(
                "b" * 40,
                fetch=_fetch_of({"ci-control.yml": [
                    _row("1", "in_progress"), _row("2", "queued"),
                    _row("9", "in_progress", sha="b" * 40, created=born)]},
                    single=_row("9", "in_progress", sha="b" * 40, created=born)),
                post=post, root=self._tree(td), now=NOW, allow_displace=True)
        self.assertEqual(doc["state"], cv.ORD_ALIVE)
        self.assertEqual(len(post.calls), 1)
        self.assertTrue(any("ОБХОД ОБЪЯВЛЕН" in ln
                            for ln in cv.format_order(doc)))

    def test_question_mode_never_posts(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            doc = cv.order_control_run(
                "b" * 40,
                fetch=_fetch_of({"ci-control.yml": [_row("1", "in_progress")]}),
                post=None, root=self._tree(td), now=NOW)
        self.assertEqual(doc["state"], cv.OCC_QUEUED_BEHIND)
        self.assertEqual(doc["posted"], None)
        self.assertEqual(cv.order_exit_code(doc), 1)

    def test_question_mode_on_a_free_group_is_zero(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            doc = cv.order_control_run("b" * 40, fetch=_fetch_of({"ci-control.yml": []}),
                                       post=None, root=self._tree(td), now=NOW)
        self.assertEqual(cv.order_exit_code(doc), 0)


class ThePostCarriesTheShaInTheINPUT(unittest.TestCase):
    """ПОЛНАЯ sha идёт во ВХОД `inputs.sha`, в `ref` — ВЕТКА.

    Положительный контроль названной ловушки: sha в `ref` даёт HTTP 422 и прогон не
    стартует ВОВСЕ (замер #1228, заказ G1069 п. 1).
    """

    def test_ref_is_the_branch_and_inputs_carry_the_full_sha(self):
        import tempfile
        post = _Post()
        sha, born = "c" * 40, "2026-11-24T02:36:00Z"
        with tempfile.TemporaryDirectory() as td:
            cv.order_control_run(
                sha, fetch=_fetch_of({"ci-control.yml": [
                    _row("9", "in_progress", sha=sha, created=born)]},
                    single=_row("9", "in_progress", sha=sha, created=born)),
                post=post, root=_tree(Path(td), {"ci-control.yml": WF_OURS}),
                branch="main", now=NOW)
        path, payload = post.calls[0]
        self.assertTrue(path.endswith("/workflows/ci-control.yml/dispatches"), path)
        self.assertEqual(payload["ref"], "main")
        self.assertEqual(payload["inputs"]["sha"], sha)
        self.assertEqual(len(payload["inputs"]["sha"]), 40)


class AnOrderIsNotAnAnchorUntilItIsAlive(unittest.TestCase):
    """HTTP 204 говорит «подача принята» — это ДРУГОЕ утверждение, чем «прогон жив».

    Авария #1228 ровно здесь: номер принятой подачи уехал в заказ якорем дельты, а
    прогона не было.
    """

    def _scene(self, td, rows, single=None, post=None):
        return cv.order_control_run(
            "d" * 40, fetch=_fetch_of({"ci-control.yml": rows}, single=single),
            post=post or _Post(), root=_tree(Path(td), {"ci-control.yml": WF_OURS}),
            now=NOW)

    def test_a_run_that_cannot_be_found_is_UNVERIFIED_not_success(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            doc = self._scene(td, [])
        self.assertEqual(doc["state"], cv.ORD_ORDERED_UNVERIFIED)
        self.assertEqual(cv.order_exit_code(doc), 1)
        self.assertIn("ПОКА нет", doc["why"])

    def test_a_run_born_BEFORE_the_order_is_not_mine(self):
        """Чужой прогон на той же sha не делает мой заказ подтверждённым."""
        import tempfile
        old = _row("8", "in_progress", sha="d" * 40,
                   created="2026-11-24T01:00:00Z")
        with tempfile.TemporaryDirectory() as td:
            doc = self._scene(td, [old], single=old)
        self.assertEqual(doc["state"], cv.ORD_ORDERED_UNVERIFIED)

    def test_a_run_already_completed_is_NOT_an_anchor(self):
        import tempfile
        born = "2026-11-24T02:36:00Z"
        dead = _row("9", "completed", sha="d" * 40, created=born,
                    conclusion="cancelled")
        with tempfile.TemporaryDirectory() as td:
            doc = self._scene(td, [dead], single=dead)
        self.assertEqual(doc["state"], cv.ORD_ORDERED_UNVERIFIED)
        self.assertIn("якорем дельты его брать НЕЛЬЗЯ", doc["why"])

    def test_liveness_unmeasured_is_UNVERIFIED(self):
        import tempfile
        born = "2026-11-24T02:36:00Z"
        alive = _row("9", "in_progress", sha="d" * 40, created=born)
        with tempfile.TemporaryDirectory() as td:
            doc = self._scene(td, [alive], single={"id": "9"})
        self.assertEqual(doc["state"], cv.ORD_ORDERED_UNVERIFIED)
        self.assertEqual(cv.order_exit_code(doc), 1)

    def test_a_non_204_is_its_OWN_outcome(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            doc = self._scene(td, [], post=_Post(code=200))
        self.assertEqual(doc["state"], cv.ORD_POST_REFUSED)
        self.assertEqual(cv.order_exit_code(doc), 4)
        self.assertIn("204", doc["why"])

    def test_a_network_failure_on_post_is_its_OWN_outcome(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            doc = self._scene(
                td, [], post=_Post(raises=urllib.error.HTTPError(
                    "u", 422, "Unprocessable", {}, None)))
        self.assertEqual(doc["state"], cv.ORD_POST_REFUSED)
        self.assertEqual(cv.order_exit_code(doc), 4)
        self.assertIn("422", doc["why"])

    def test_the_happy_path_is_alive_and_zero(self):
        import tempfile
        born = "2026-11-24T02:36:00Z"
        alive = _row("45304210098", "in_progress", sha="d" * 40, created=born)
        with tempfile.TemporaryDirectory() as td:
            doc = self._scene(td, [alive], single=alive)
        self.assertEqual(doc["state"], cv.ORD_ALIVE)
        self.assertEqual(cv.order_exit_code(doc), 0)
        self.assertEqual(doc["identity"]["run"]["id"], "45304210098")


class FiveOutcomesAreDistinguishableByCode(unittest.TestCase):
    """Код возврата различает все пять, иначе читателю остаётся только проза."""

    def test_each_state_has_its_own_code(self):
        table = {cv.ORD_ALIVE: 0, cv.ORD_ORDERED_UNVERIFIED: 1, cv.ORD_UNMEASURED: 2,
                 cv.ORD_REFUSED: 3, cv.ORD_POST_REFUSED: 4,
                 cv.OCC_FREE: 0, cv.OCC_QUEUED_BEHIND: 1, cv.OCC_WOULD_DISPLACE: 3}
        for state, code in table.items():
            with self.subTest(state=state):
                self.assertEqual(cv.order_exit_code({"state": state}), code)
        self.assertEqual(len(set(table.values())), 5)


class TheDoorIsSINGLE(unittest.TestCase):
    """Группа НЕ объявлена литералом в приборе: второй копии нет (класс ADR-220)."""

    def test_the_group_name_is_not_a_literal_of_the_prober(self):
        src = (ROOT / "scripts" / "ci_control_verdict.py").read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("#"))
        self.assertNotIn('"ci-control"', code)
        self.assertNotIn("'ci-control'", code)

    def test_the_workflow_file_is_named_once(self):
        src = (ROOT / "scripts" / "ci_control_verdict.py").read_text(encoding="utf-8")
        self.assertEqual(src.count('"ci-control.yml"'), 1,
                         "второй литерал имени воркфлоу разошёлся бы с первым молча")


class TheLiveWorkflowStillMatchesTheSceneForm(unittest.TestCase):
    """Сцена выше описывает ЖИВОЙ воркфлоу — паритет, а не фантазия.

    Разойдись форма файла со сценой, батарея осталась бы зелёной, отвечая о форме,
    которой в дереве нет (дословный урок § «ОКНО ДОСТАВКИ»).
    """

    def test_the_real_workflow_declares_the_group_in_the_block_form(self):
        d = cv.concurrency_declaration(ROOT)
        self.assertEqual(d["state"], cv.DECL_READ, d["why"])
        self.assertEqual(d["group"], "ci-control")
        self.assertEqual(d["cancel_in_progress"], "false")
        self.assertTrue(d["crons"], "расписание воркфлоу не объявлено")
        self.assertIn(cv.WORKFLOW_FILE, d["sharers"])

    def test_every_cron_of_the_real_workflow_is_parsed(self):
        d = cv.concurrency_declaration(ROOT)
        for expr in d["crons"]:
            with self.subTest(cron=expr):
                self.assertIsNotNone(
                    cv.next_cron_moment(expr, NOW),
                    f"такт {expr!r} не разобран — предупреждение двери останется "
                    f"без ближайшего третьего")


if __name__ == "__main__":
    unittest.main()
