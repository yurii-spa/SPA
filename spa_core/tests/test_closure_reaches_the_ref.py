"""Закрытие карточки доезжает до `origin/main` — обе оси (ADR-806, цикл #929).

ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ АВАРИИ 2026-10-25. Замер цикла #929 на живом дереве
против `origin/main` 546687543:

| вопрос | знаменатель | находок |
|---|---|---|
| дошло ли закрытие МОСТА? | 52 записи журнала моста | **0** (52/52 сошлись) |
| закрыта в дереве, открыта на ref? | 671 терминальная карточка | **41** |

Пересечение осей ПУСТО, и это построение, а не случайность: из 41 карточки
журнал моста не знает ни одной как `closed`. Пять мост завёл, а закрыл их
ИНТЕЙК как дубли; шестая лежит в журнале как `carded`; остальные 35 закрыты
сессиями через `queue.set_status`, чей `TRACKER_DIR` по построению указывает в
ЖИВОЕ дерево (карточка-призрак 22.08). Доставки у этой записи нет ничьей:
`orphan_candidates` пропускала карточку строкой `if name in on_ref: continue`
ДО чтения статуса — то есть про статус не спрашивала ни разу.

Цена: старейшему непришедшему закрытию **54.5 суток**, медиане 37.7, младшему
0.7 — класс ЖИВОЙ. Очередь, которую протокол §3.4 велит читать из worktree на
`origin/main`, предъявляла циклам 41 задачу, снятую неделями раньше.

Каждый тест ниже — звено того контура, и каждый обязан КРАСНЕТЬ, если звено
порвать. Направление находки ОДНО: дерево впереди, ref позади. Обратное
(`ref` закрыт, дерево открыто) проверяется отдельным ОБРАТНЫМ контролем и
находкой быть НЕ ДОЛЖНО — замер #928 показал 17 таких карточек, и все 17 были
ложными: прод-копия просто отстала.
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout

from spa_core.monitoring import bridge_closure_drift as bcd
from spa_core.monitoring import card_delivery as cd
from spa_core.owner_queue.origin_view import Unmeasured


def lookup(statuses: dict, sha: str = "deadbeefcafe"):
    """Сверка с ref, подставленная значением: {card_id: статус}. Ключа нет ⇒ на ref нет."""
    def _lookup(card_ids):
        return {cid: st for cid, st in statuses.items() if cid in card_ids}, sha
    return _lookup


def raising_lookup(exc: Exception):
    def _lookup(card_ids):
        raise exc
    return _lookup


# ── ось ЗНАМЕНАТЕЛЯ: scan_tracker ───────────────────────────────────────────

class ClosureThatNeverArrived(unittest.TestCase):
    def test_closed_here_open_on_ref_is_a_finding(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: ровно те 41 карточка, что морили очередь."""
        r = bcd.scan_tracker({"inbox-snyataya": "done", "inbox-zhivaya": "new"},
                             lookup({"inbox-snyataya": "new", "inbox-zhivaya": "new"}))
        self.assertEqual(r["verdict"], bcd.VERDICT_FINDINGS)
        self.assertEqual(r["open_on_ref"],
                         [{"card_id": "inbox-snyataya", "tree_status": "done",
                           "ref_status": "new"}])
        # Знаменатель — ТЕРМИНАЛЬНЫЕ карточки дерева, а не все подряд: живая
        # карточка в него не входит, иначе «сошлось» считалось бы от числа,
        # к предмету отношения не имеющего.
        self.assertEqual(r["checked"], 1)
        self.assertEqual(r["agreed"], 0)

    def test_ref_ahead_of_tree_is_NOT_a_finding(self):
        """ОБРАТНЫЙ КОНТРОЛЬ замера #928: прод отстаёт — это законно, не находка.

        17 карточек `owner-done` в проде против `ingested` на origin оказались
        ложными ВСЕ. Краснеть на этом значило бы краснеть на верном состоянии,
        а дрейф у рождения и у закрытия смотрит в РАЗНЫЕ стороны.
        """
        r = bcd.scan_tracker({"owner-decision-otvechen": "needs-owner"},
                             lookup({"owner-decision-otvechen": "ingested"}))
        self.assertEqual(r["verdict"], bcd.VERDICT_OK)
        self.assertEqual(r["open_on_ref"], [])
        # И в знаменатель он не попал: карточка не закрыта ЗДЕСЬ.
        self.assertEqual(r["checked"], 0)

    def test_both_sides_closed_is_agreement_not_a_finding(self):
        r = bcd.scan_tracker({"inbox-a": "done", "inbox-b": "ingested",
                              "inbox-c": "owner-done"},
                             lookup({"inbox-a": "done", "inbox-b": "ingested",
                                     "inbox-c": "owner-done"}))
        self.assertEqual(r["verdict"], bcd.VERDICT_OK)
        self.assertEqual((r["checked"], r["agreed"]), (3, 3))

    def test_absent_on_ref_is_its_own_list_not_a_finding(self):
        """Направление РОЖДЕНИЯ — своя карточка. Сложить два списка значит
        предъявить циклу работу, которой нет (замер #929: таких 28)."""
        r = bcd.scan_tracker({"inbox-rozhdena-zdes": "done"}, lookup({}))
        self.assertEqual(r["verdict"], bcd.VERDICT_OK)
        self.assertEqual(r["absent_on_ref"], ["inbox-rozhdena-zdes"])
        self.assertEqual(r["open_on_ref"], [])

    def test_unreadable_card_is_a_third_outcome_not_silence(self):
        """Карточка без разбираемого `status:` названа, а не выпала молча."""
        r = bcd.scan_tracker({"inbox-a": "done"}, lookup({"inbox-a": "done"}),
                             unreadable=["inbox-slomana"])
        self.assertEqual(r["unreadable"], ["inbox-slomana"])
        # И она НЕ засчитана в «сошлось»: иначе мусор красил бы ось зелёным.
        self.assertEqual(r["agreed"], 1)


class TheBoardIsNotACard(unittest.TestCase):
    """Доска — производный индекс, а не карточка очереди.

    Дыра покрытия, найденная мутационным замером #929 (выжила мутация
    `TRACKER_NOT_A_CARD = frozenset()`): без исключения `_BOARD.md` попадает
    в `unreadable` КАЖДЫЙ прогон — третий исход начинает кормиться мусором,
    и настоящая нечитаемая карточка перестаёт быть заметной среди него.
    """

    def test_board_is_neither_a_status_nor_an_unreadable_card(self):
        with tempfile.TemporaryDirectory() as td:
            tracker = os.path.join(td, cd.TRACKER_REL)
            os.makedirs(tracker)
            with open(os.path.join(tracker, "_BOARD.md"), "w", encoding="utf-8") as f:
                f.write("# Доска\n\nникакого frontmatter тут нет\n")
            with open(os.path.join(tracker, "inbox-a.md"), "w", encoding="utf-8") as f:
                f.write(card("done"))
            statuses, unreadable, read = bcd.read_tracker_statuses(td)
        self.assertTrue(read)
        self.assertEqual(statuses, {"inbox-a": "done"})
        self.assertEqual(unreadable, [],
                         "доска не карточка: ни в статусы, ни в третий исход")

    def test_a_really_unreadable_card_still_reaches_the_third_outcome(self):
        """ОБРАТНЫЙ контроль: исключение доски не глушит настоящую находку."""
        with tempfile.TemporaryDirectory() as td:
            tracker = os.path.join(td, cd.TRACKER_REL)
            os.makedirs(tracker)
            with open(os.path.join(tracker, "inbox-slomana.md"), "w", encoding="utf-8") as f:
                f.write("тело без frontmatter\n")
            statuses, unreadable, read = bcd.read_tracker_statuses(td)
        self.assertTrue(read)
        self.assertEqual(statuses, {})
        self.assertEqual(unreadable, ["inbox-slomana"])

    def test_a_missing_tracker_dir_is_not_read_rather_than_empty(self):
        statuses, unreadable, read = bcd.read_tracker_statuses(
            os.path.join(tempfile.gettempdir(), "spa-net-takogo-dereva-929"))
        self.assertFalse(read, "«каталога нет» обязано отличаться от «каталог пуст»")
        self.assertEqual((statuses, unreadable), ({}, []))


class UnmeasuredIsNotZero(unittest.TestCase):
    """«Находок нет» и «судить было нечем» — разные утверждения (инв. #17)."""

    def test_tracker_not_read_is_unmeasured(self):
        r = bcd.scan_tracker({}, lookup({}), tracker_read=False)
        self.assertEqual(r["verdict"], bcd.VERDICT_UNMEASURED)
        self.assertIn("каталог очереди не прочитан", r["unmeasured_reason"])

    def test_missing_lookup_is_unmeasured(self):
        r = bcd.scan_tracker({"inbox-a": "done"}, None)
        self.assertEqual(r["verdict"], bcd.VERDICT_UNMEASURED)

    def test_failing_lookup_is_unmeasured_and_keeps_the_unreadable_list(self):
        r = bcd.scan_tracker({"inbox-a": "done"},
                             raising_lookup(Unmeasured("ref не разрешился")),
                             unreadable=["inbox-slomana"])
        self.assertEqual(r["verdict"], bcd.VERDICT_UNMEASURED)
        self.assertIn("ref не разрешился", r["unmeasured_reason"])
        self.assertEqual(r["unreadable"], ["inbox-slomana"],
                         "третий исход не смеет исчезать от неудачи сверки")

    def test_read_and_empty_is_ok_not_unmeasured(self):
        """ИЗМЕРЕННАЯ пустота — положительный контроль против fail-CLOSED наоборот."""
        r = bcd.scan_tracker({"inbox-a": "new"}, lookup({"inbox-a": "new"}))
        self.assertEqual(r["verdict"], bcd.VERDICT_OK)
        self.assertIsNone(r["unmeasured_reason"])


class TheTwoAxesAreIndependent(unittest.TestCase):
    """Сердце ADR-806: зелень оси журнала НЕ есть ответ про очередь."""

    def test_clean_ledger_does_not_hide_a_tracker_finding(self):
        """ВОСПРОИЗВЕДЁННЫЙ ЗАМЕР #929: журнал 52/52 сошёлся, очередь — 41 находка."""
        both = bcd.scan_both(
            findings={"B2:stale:x": {"status": "closed",
                                     "card": "/prod/tracker/inbox-dovezena.md"}},
            tree_statuses={"inbox-dovezena": "done", "inbox-zabyta": "done"},
            origin_lookup=lookup({"inbox-dovezena": "done", "inbox-zabyta": "new"}))
        self.assertEqual(both["verdict"], bcd.VERDICT_OK, "ось журнала чиста — и верно")
        self.assertEqual(both["tracker"]["verdict"], bcd.VERDICT_FINDINGS)
        self.assertEqual([r["card_id"] for r in both["tracker"]["open_on_ref"]],
                         ["inbox-zabyta"])

    def test_unmeasured_tracker_does_not_turn_green_from_a_clean_ledger(self):
        both = bcd.scan_both(findings={}, tree_statuses=None,
                             origin_lookup=lookup({}), tracker_read=False)
        self.assertEqual(both["verdict"], bcd.VERDICT_OK)
        self.assertEqual(both["tracker"]["verdict"], bcd.VERDICT_UNMEASURED)


class TheProducerActuallyWritesBothAxes(unittest.TestCase):
    """Измеритель без ПРОИЗВОДИТЕЛЯ — находка без читателя.

    Шаг 0-офис читает `data/loop_health.json`, а не зовёт перепись сам. Если
    `loop_health` перестанет класть ось знаменателя в свой блок, строка у
    читателя замолчит — и замолчит ТИХО, как молчали 41 закрытие.
    """

    def test_loop_health_block_carries_the_tracker_axis(self):
        from spa_core.monitoring import loop_health
        import datetime as dt

        report = loop_health.compute(
            {"findings": {}}, lambda card: "new", dt.datetime.now(dt.timezone.utc),
            origin_lookup=lookup({"inbox-zabyta": "new"}),
            state_read=True,
            tree_statuses={"inbox-zabyta": "done"}, tracker_read=True)
        drift = report["closure_drift"]
        self.assertIn("tracker", drift, "производитель ось знаменателя не пишет")
        self.assertEqual(drift["tracker"]["verdict"], bcd.VERDICT_FINDINGS)
        self.assertEqual([r["card_id"] for r in drift["tracker"]["open_on_ref"]],
                         ["inbox-zabyta"])

    def test_run_actually_reads_the_queue_off_the_disk(self):
        """Дыра покрытия, найденная мутационным замером #929 (мутация 12/13).

        `compute` можно позвать правильно и всё равно ничего не измерить: ось
        питается тем, что `run` прочитал С ДИСКА. Подмени чтение пустотой — и
        на ЗДОРОВОМ дереве ось навсегда скажет «не измерено», то есть тихо
        выродится в ту же тишину, из которой выросли 41 закрытие.
        """
        from spa_core.monitoring import loop_health

        with tempfile.TemporaryDirectory() as td:
            tracker = os.path.join(td, cd.TRACKER_REL)
            os.makedirs(tracker)
            os.makedirs(os.path.join(td, "data"))
            with open(os.path.join(tracker, "inbox-zabyta.md"), "w", encoding="utf-8") as f:
                f.write(card("done"))
            report = loop_health.run(td, origin_lookup=lookup({"inbox-zabyta": "new"}))
        axis = report["closure_drift"]["tracker"]
        self.assertEqual(axis["verdict"], bcd.VERDICT_FINDINGS,
                         f"очередь с диска не прочитана: {axis.get('unmeasured_reason')}")
        self.assertEqual([r["card_id"] for r in axis["open_on_ref"]], ["inbox-zabyta"])

    def test_a_caller_that_forgets_the_tracker_gets_unmeasured_not_green(self):
        """Умолчание fail-CLOSED: забывший вызывающий не утверждает «сошлось»."""
        from spa_core.monitoring import loop_health
        import datetime as dt

        report = loop_health.compute(
            {"findings": {}}, lambda card: "new", dt.datetime.now(dt.timezone.utc),
            origin_lookup=lookup({}), state_read=True)
        self.assertEqual(report["closure_drift"]["tracker"]["verdict"],
                         bcd.VERDICT_UNMEASURED)


class TheExitCodeAnswersForBothAxes(unittest.TestCase):
    """Код возврата — единственный канал для вызывающего, и он обязан быть
    fail-CLOSED: «не измерено» ЛЮБОЙ оси важнее зелени другой."""

    def _run(self, report):
        buf = io.StringIO()
        orig = bcd.run
        bcd.run = lambda root=None: report
        try:
            with redirect_stdout(buf):
                code = bcd.main(["--root", "/nowhere"])
        finally:
            bcd.run = orig
        return code, buf.getvalue()

    def _ledger(self, **kw):
        base = {"verdict": bcd.VERDICT_OK, "unmeasured_reason": None, "ref_sha": "abc",
                "checked": 1, "agreed": 1, "open_on_origin": [], "absent_on_origin": []}
        base.update(kw)
        return base

    def _tracker(self, **kw):
        base = {"verdict": bcd.VERDICT_OK, "unmeasured_reason": None, "ref_sha": "abc",
                "checked": 1, "agreed": 1, "open_on_ref": [], "absent_on_ref": [],
                "unreadable": []}
        base.update(kw)
        return base

    def test_all_clean_is_zero(self):
        code, out = self._run({**self._ledger(), "tracker": self._tracker()})
        self.assertEqual(code, 0)
        self.assertIn("ось знаменателя", out)

    def test_tracker_finding_alone_turns_the_run_red(self):
        """Звено, которого не было до ADR-806: прежний `main` вернул бы 0."""
        code, out = self._run({**self._ledger(),
                               "tracker": self._tracker(
                                   verdict=bcd.VERDICT_FINDINGS,
                                   open_on_ref=[{"card_id": "inbox-zabyta",
                                                 "tree_status": "done",
                                                 "ref_status": "new"}])})
        self.assertEqual(code, 1)
        self.assertIn("inbox-zabyta", out)

    def test_unmeasured_tracker_beats_a_clean_ledger(self):
        code, _ = self._run({**self._ledger(),
                             "tracker": self._tracker(verdict=bcd.VERDICT_UNMEASURED,
                                                      unmeasured_reason="нечем")})
        self.assertEqual(code, 2)

    def test_a_receipt_without_the_tracker_block_is_unmeasured_not_green(self):
        """Квитанция старого образца не имеет права читаться как «сошлось»."""
        code, out = self._run(self._ledger())
        self.assertEqual(code, 2)
        self.assertIn("НЕ ИЗМЕРЕНА", out)


# ── ось ДОСТАВКИ: orphan_candidates ─────────────────────────────────────────

def _git(root, *args):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)
    assert r.returncode == 0, f"git {args}: {r.stdout}{r.stderr}"
    return r.stdout


def card(status: str = "new", title: str = "t") -> str:
    return f"---\ntrackerStatus:\n  type: inbox\ntitle: \"{title}\"\nstatus: {status}\n---\n\nтело\n"


def scene(td: str, on_ref: dict, tree_override: dict | None = None) -> str:
    """Репозиторий `main`: карточки в истории, затем часть переписана на диске.

    Имя ветки задаётся ЯВНО (`git init -b main`): `init.defaultBranch` есть
    свойство ХОСТА, и тест, умолчавший о нём, зелен здесь и красен в CI
    (`.claude/rules/deployment.md`, раздел про git-окружение).
    """
    root = os.path.realpath(td)
    tracker = os.path.join(root, cd.TRACKER_REL)
    os.makedirs(tracker, exist_ok=True)
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    _git(root, "init", "-b", "main", "--quiet")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    for name, body in on_ref.items():
        with open(os.path.join(tracker, name), "w", encoding="utf-8") as f:
            f.write(body)
    with open(os.path.join(root, "data", ".keep"), "w", encoding="utf-8") as f:
        f.write("")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "база", "--quiet")
    for name, body in (tree_override or {}).items():
        with open(os.path.join(tracker, name), "w", encoding="utf-8") as f:
            f.write(body)
    return root


def ask(root, ref_statuses=None, **kw):
    kw.setdefault("ref", "main")
    kw.setdefault("fetch", False)
    if ref_statuses is not None:
        kw["ref_statuses"] = ref_statuses
    return cd.orphan_candidates(root, **kw)


class TheClosureIsHandedToDelivery(unittest.TestCase):
    def test_closed_here_open_on_ref_becomes_a_candidate(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: закрытие, которое не везёт никто."""
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-snyataya.md": card("new")},
                         tree_override={"inbox-snyataya.md": card("done")})
            r = ask(root)
            self.assertEqual(r["status"], cd.ORPHAN_MEASURED, r["reason"])
            self.assertEqual(r["closed_here_open_on_ref"],
                             [{"path": os.path.join(cd.TRACKER_REL, "inbox-snyataya.md"),
                               "tree_status": "done", "ref_status": "new"}])
            self.assertEqual(r["candidates"],
                             [os.path.join(cd.TRACKER_REL, "inbox-snyataya.md")],
                             "названо, но не повезено — это находка без читателя")

    def test_an_ordinary_update_is_still_NOT_a_candidate(self):
        """Контракт ДО ADR-806 не ослаблен: судьба обновления — дело переноса.

        Взять все присутствующие на ref значило бы гонять через `plan_batch`
        всю очередь (840 карточек) вместо тех, что правда не доехали.
        """
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-est.md": card("new")},
                         tree_override={"inbox-est.md": card("new", title="правленый")})
            r = ask(root)
            self.assertEqual(r["candidates"], [])
            self.assertEqual(r["closed_here_open_on_ref"], [])

    def test_agreement_on_both_sides_is_not_a_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-a.md": card("done")})
            r = ask(root)
            self.assertEqual(r["candidates"], [])
            self.assertEqual(r["closed_here_open_on_ref"], [])

    def test_ref_ahead_of_tree_is_not_a_candidate(self):
        """ОБРАТНЫЙ КОНТРОЛЬ #928: прод отстаёт — везти оттуда нечего."""
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-a.md": card("done")},
                         tree_override={"inbox-a.md": card("new")})
            r = ask(root)
            self.assertEqual(r["candidates"], [])
            self.assertEqual(r["closed_here_open_on_ref"], [])

    def test_birth_and_closure_are_counted_apart(self):
        """«Не доехал файл» и «не доехал его статус» — разные аварии."""
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-snyataya.md": card("new")},
                         tree_override={"inbox-snyataya.md": card("done"),
                                        "inbox-rozhdena.md": card("new")})
            r = ask(root)
            self.assertEqual(len(r["closed_here_open_on_ref"]), 1)
            self.assertEqual(sorted(r["candidates"]),
                             sorted([os.path.join(cd.TRACKER_REL, "inbox-rozhdena.md"),
                                     os.path.join(cd.TRACKER_REL, "inbox-snyataya.md")]))
            self.assertIn("нет на main и не закрыто 1", r["reason"])
            self.assertIn("закрыто здесь и открыто на main 1", r["reason"])

    def test_a_failing_ref_read_is_named_and_does_not_eat_the_birth_axis(self):
        """Падение ОДНОЙ оси не смеет ни молчать, ни уронить вторую."""
        def boom(root, ids, ref):
            raise RuntimeError("ref не прочитан")

        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-snyataya.md": card("new")},
                         tree_override={"inbox-snyataya.md": card("done"),
                                        "inbox-rozhdena.md": card("new")})
            r = ask(root, ref_statuses=boom)
            self.assertEqual(r["status"], cd.ORPHAN_MEASURED)
            self.assertIn("ref не прочитан", r["closures_unmeasured"])
            self.assertEqual(r["closed_here_open_on_ref"], [])
            self.assertEqual(r["candidates"],
                             [os.path.join(cd.TRACKER_REL, "inbox-rozhdena.md")],
                             "рождения обязаны уехать и при слепой второй оси")

    def test_board_is_never_a_closure_candidate(self):
        """Доска — общая память: пушер отказал бы и уронил ВСЮ пачку."""
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"_BOARD.md": card("new"),
                                     "inbox-a.md": card("new")},
                         tree_override={"_BOARD.md": card("done")})
            r = ask(root)
            board = os.path.join(cd.TRACKER_REL, "_BOARD.md")
            self.assertNotIn(board, r["candidates"])
            self.assertNotIn(board, [c["path"] for c in r["closed_here_open_on_ref"]])


class TheLineNamesTheClosures(unittest.TestCase):
    """Находка без печати — находка без читателя."""

    def test_render_names_the_closure_count_apart_from_births(self):
        receipt = {"orphans": {"status": cd.ORPHAN_MEASURED, "candidates": ["a", "b"],
                               "over_limit": [], "limit": 25, "status_unreadable": [],
                               "closed_here_open_on_ref": [{"path": "b"}],
                               "closures_unmeasured": None}}
        line = cd.render_orphans(receipt)
        self.assertIn("сирот взято 2", line)
        self.assertIn("закрытий, не доехавших наверх: 1", line)

    def test_render_never_hides_unmeasured_closures(self):
        receipt = {"orphans": {"status": cd.ORPHAN_MEASURED, "candidates": [],
                               "over_limit": [], "limit": 25, "status_unreadable": [],
                               "closed_here_open_on_ref": [],
                               "closures_unmeasured": "ref не прочитан"}}
        self.assertIn("закрытия НЕ ИЗМЕРЕНЫ", cd.render_orphans(receipt))


class WiringReachesThePusher(unittest.TestCase):
    def test_a_stuck_closure_is_pushed_without_any_caller_asking(self):
        """Сквозной контроль: `deliver([])` — никто ничего не заказывал."""
        seen = {}

        def fake_pusher(root, paths, message, allow_overwrite=False):
            seen["paths"] = list(paths)
            return 0, "OK"

        def present_everywhere(root, repo_path):
            # Файл на origin ЕСТЬ и отличается — ровно состояние 41 карточки.
            return cd.REMOTE_PRESENT, card("new").encode(), ""

        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-snyataya.md": card("new")},
                         tree_override={"inbox-snyataya.md": card("done")})
            receipt = cd.deliver([], root=root, pusher=fake_pusher,
                                 reader=present_everywhere, use_debt=False,
                                 env={cd.ENV_FLAG: "1"},
                                 write_status=False,
                                 orphans=lambda r: ask(r))
        self.assertTrue(seen.get("paths"), f"закрытие до пушера не дошло: {receipt}")
        self.assertIn("inbox-snyataya.md", " ".join(seen["paths"]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
