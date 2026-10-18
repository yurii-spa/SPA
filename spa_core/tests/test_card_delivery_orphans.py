"""Сироты доставки: карточки, которых на origin нет ВООБЩЕ (ADR-781, цикл #899).

ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ АВАРИИ 2026-10-18. Шаг 0a цикла #899 нашёл в прод-дереве
**31** карточку в НЕтерминальном статусе, которых на `origin/main` не было ни
одним байтом и ни в одном коммите; старейшей **291 ч (12.1 суток)**, и девять из
них — `needs-owner`, то есть вопросы владельцу, которых для очереди НЕ
СУЩЕСТВУЕТ (`list` сверяется с origin, протокол велит читать очередь из worktree
на origin/main).

Почему молчали все: вход доставки — список ВЫЗЫВАЮЩЕГО, а единственный живой
вызывающий кладёт туда «что мост тронул за ЭТОТ прогон». Карточки
`problem_store` (16), `owner_queue.intake` (14) и внешней сессии ARB (1) в этот
список не попадали НИКОГДА, а долг (ADR-081) помнит только то, что доставка УЖЕ
пыталась везти — карточку, которую не заказывал никто, он не видит ни разу.

Каждый тест ниже — звено того контура, и каждый обязан КРАСНЕТЬ, если звено
порвать. Сцена делается настоящим git-репозиторием в одноразовом каталоге:
«нет на ref» нельзя изобразить подстановкой, не потеряв предмет.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest

from spa_core.monitoring import card_delivery as cd


def _git(root, *args):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)
    assert r.returncode == 0, f"git {args}: {r.stdout}{r.stderr}"
    return r.stdout


def card(status: str = "new", title: str = "t") -> str:
    return f"---\ntrackerStatus:\n  type: inbox\ntitle: \"{title}\"\nstatus: {status}\n---\n\nтело\n"


def scene(td: str, on_ref: dict | None = None, only_local: dict | None = None) -> str:
    """Репозиторий с веткой `main`: часть карточек в истории, часть — только на диске.

    Имя ветки задаётся ЯВНО (`git init -b main`): `init.defaultBranch` есть
    свойство ХОСТА (Apple Git даёт `main`, ubuntu-latest — `master`), и тест,
    умолчавший о нём, зелен здесь и красен в CI
    (`.claude/rules/deployment.md`, раздел про git-окружение).
    """
    root = os.path.realpath(td)
    tracker = os.path.join(root, cd.TRACKER_REL)
    os.makedirs(tracker, exist_ok=True)
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    _git(root, "init", "-b", "main", "--quiet")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    for name, body in (on_ref or {}).items():
        with open(os.path.join(tracker, name), "w", encoding="utf-8") as f:
            f.write(body)
    # Якорь базового коммита: git не хранит пустых каталогов, а сцена «на ref
    # НЕТ НИ ОДНОЙ карточки» обязана оставаться репозиторием с историей.
    with open(os.path.join(root, "data", ".keep"), "w", encoding="utf-8") as f:
        f.write("")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "база", "--quiet")
    for name, body in (only_local or {}).items():
        with open(os.path.join(tracker, name), "w", encoding="utf-8") as f:
            f.write(body)
    return root


def ask(root, **kw):
    """Опрос сирот без сети: `fetch` в сцене спрашивать некого."""
    kw.setdefault("ref", "main")
    kw.setdefault("fetch", False)
    return cd.orphan_candidates(root, **kw)


class OrphanIsFound(unittest.TestCase):
    def test_non_terminal_card_absent_on_ref_is_a_candidate(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: ровно те 31 карточка, что молчали 12 суток."""
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-staryi.md": card("new")},
                         only_local={"agent-task-sboi.md": card("backlog"),
                                     "owner-decision-vopros.md": card("needs-owner")})
            r = ask(root)
            self.assertEqual(r["status"], cd.ORPHAN_MEASURED, r["reason"])
            self.assertEqual(sorted(r["candidates"]),
                             [os.path.join(cd.TRACKER_REL, "agent-task-sboi.md"),
                              os.path.join(cd.TRACKER_REL, "owner-decision-vopros.md")])
            self.assertEqual(r["scanned"], 3)

    def test_card_present_on_ref_is_not_a_candidate(self):
        """ОБРАТНЫЙ КОНТРОЛЬ: судьба ОБНОВЛЕНИЯ — дело переноса, не этого опроса.

        Если бы опрос брал и присутствующие на origin, каждый прогон тащил бы
        всю очередь в `plan_batch` — и перенос решал бы судьбу 840 карточек
        вместо тех, которых правда нет.
        """
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-est.md": card("new")})
            r = ask(root)
            self.assertEqual(r["status"], cd.ORPHAN_MEASURED)
            self.assertEqual(r["candidates"], [])

    def test_terminal_card_absent_on_ref_is_counted_not_carried(self):
        """Закрытая карточка очереди не нужна — но «не повезли» обязано быть СЧИТАНО."""
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-baza.md": card("new")},
                         only_local={"inbox-zakryta.md": card("done"),
                                     "inbox-ingested.md": card("ingested"),
                                     "inbox-zhivaya.md": card("in-progress")})
            r = ask(root)
            self.assertEqual(r["candidates"],
                             [os.path.join(cd.TRACKER_REL, "inbox-zhivaya.md")])
            self.assertEqual(r["terminal"], 2)

    def test_board_is_never_even_looked_at(self):
        """Доска — общая память: пушер отказал бы и уронил ВСЮ пачку (NEVER_DELIVER).

        Утверждение сильнее, чем «не кандидат»: доска обязана НЕ ПОПАСТЬ В
        ОПРОС ВОВСЕ. Слабая форма («candidates пуст») проходила и без
        исключения `NEVER_DELIVER` — доска просто падала в соседний исход
        `status_unreadable` (у неё нет frontmatter), и мутация «не исключать
        доску» ВЫЖИЛА на замере #899. Это ровно тот класс, против которого
        написан весь модуль: зелёный ответ на свой вопрос вместо нужного.
        """
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-baza.md": card("new")},
                         only_local={"_BOARD.md": "# доска\n",
                                     "inbox-sirota.md": card("new")})
            r = ask(root)
            self.assertEqual(r["candidates"],
                             [os.path.join(cd.TRACKER_REL, "inbox-sirota.md")])
            self.assertEqual(r["status_unreadable"], [])
            self.assertNotIn("_BOARD.md", str(r))
            # Доски нет и в ЗНАМЕНАТЕЛЕ: 3 файла на диске, в опросе 2.
            self.assertEqual(r["scanned"], 2)

    def test_unparsable_status_is_a_third_outcome_not_a_candidate(self):
        """Карточка без разбираемого `status:` — НАЗВАНА, а не молча нетерминальна."""
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-baza.md": card("new")},
                         only_local={"inbox-bez-statusa.md": "---\ntitle: x\n---\n\nтело\n",
                                     "inbox-ne-kartochka.md": "просто текст\n"})
            r = ask(root)
            self.assertEqual(r["candidates"], [])
            self.assertEqual(sorted(r["status_unreadable"]),
                             [os.path.join(cd.TRACKER_REL, "inbox-bez-statusa.md"),
                              os.path.join(cd.TRACKER_REL, "inbox-ne-kartochka.md")])

    def test_oldest_goes_first(self):
        """Сирота 12 суток не ждёт, пока уедут свежие: порядок — по возрасту файла."""
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-baza.md": card("new")},
                         only_local={"inbox-svezhaya.md": card("new"),
                                     "inbox-staraya.md": card("new")})
            tracker = os.path.join(root, cd.TRACKER_REL)
            os.utime(os.path.join(tracker, "inbox-staraya.md"), (1_000_000, 1_000_000))
            os.utime(os.path.join(tracker, "inbox-svezhaya.md"), (2_000_000, 2_000_000))
            r = ask(root)
            self.assertEqual(r["candidates"],
                             [os.path.join(cd.TRACKER_REL, "inbox-staraya.md"),
                              os.path.join(cd.TRACKER_REL, "inbox-svezhaya.md")])

    def test_cap_is_named_and_the_remainder_printed(self):
        """«Сколько получилось» молча — форма тихой потери: потолок НАЗВАН, остаток виден."""
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-baza.md": card("new")},
                         only_local={f"inbox-{i}.md": card("new") for i in range(5)})
            r = ask(root, limit=2)
            self.assertEqual(len(r["candidates"]), 2)
            self.assertEqual(len(r["over_limit"]), 3)
            self.assertIn("потолке 2", r["reason"])


class UnmeasuredIsNotEmpty(unittest.TestCase):
    """Третий исход (инв. #17): «не измерено» ≠ «сирот нет» и ≠ «есть сироты»."""

    def test_tree_without_git_refuses_to_answer(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, cd.TRACKER_REL))
            with open(os.path.join(td, cd.TRACKER_REL, "inbox-a.md"), "w",
                      encoding="utf-8") as f:
                f.write(card("new"))
            r = ask(td)
            self.assertEqual(r["status"], cd.ORPHAN_UNMEASURED)
            self.assertEqual(r["candidates"], [])
            self.assertIn("не под git", r["reason"])

    def test_unknown_ref_is_unmeasured_with_the_git_answer_named(self):
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-baza.md": card("new")},
                         only_local={"inbox-sirota.md": card("new")})
            r = ask(root, ref="origin/net-takoi-vetki")
            self.assertEqual(r["status"], cd.ORPHAN_UNMEASURED)
            self.assertEqual(r["candidates"], [])
            self.assertIn("НЕ ИЗМЕРЕНО", r["reason"])

    def test_missing_tracker_dir_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as td:
            r = ask(td)
            self.assertEqual(r["status"], cd.ORPHAN_UNMEASURED)
            self.assertIn(cd.TRACKER_REL, r["reason"])

    def test_stale_cache_is_named_when_fetch_fails(self):
        """Ответ КЭША обязан быть помечен кэшем (ADR-361), а не выдан за ответ сервера."""
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-baza.md": card("new")},
                         only_local={"inbox-sirota.md": card("new")})
            calls = []

            def git(r, args, timeout=cd.ORPHAN_GIT_TIMEOUT):
                calls.append(args[0])
                if args[0] == "fetch":
                    return 128, "fatal: 'origin' does not appear to be a git repository"
                return cd._git(r, args, timeout)

            r = cd.orphan_candidates(root, ref="main", fetch=True, git=git)
            self.assertIn("fetch", calls)
            self.assertFalse(r["ref_fresh"])
            self.assertEqual(r["status"], cd.ORPHAN_MEASURED)
            self.assertIn("кэш", r["reason"])
            self.assertEqual(r["candidates"],
                             [os.path.join(cd.TRACKER_REL, "inbox-sirota.md")])

    def test_green_line_demands_BOTH_axes_measured(self):
        """Зелёная строка молчит только когда измерены ОБЕ оси — долг И сироты.

        Соседний тест (`test_card_delivery_debt.py::
        test_render_stays_quiet_when_debt_is_measured_zero`) утверждает ровно
        это, и цикл #899 дописал его фикстуру вердиктом сирот, а не ослабил
        утверждение (инв. #16; запись в `docs/journal/2026-W42.md`): до правки
        он описывал квитанцию СТАРОГО образца, у которой вторая ось не измерена
        честно — и требовал от неё тишины.
        """
        measured = {"status": cd.DELIVERED, "attempted": ["x"], "delivered": ["x"],
                    "debt": {"count": 0, "oldest_hours": None, "stale": []},
                    "orphans": {"status": cd.ORPHAN_MEASURED, "candidates": []}}
        self.assertNotIn("НЕ ИЗМЕРЕН", cd.render(measured))
        for axis in ("debt", "orphans"):
            half = dict(measured)
            half.pop(axis)
            self.assertIn("НЕ ИЗМЕРЕН", cd.render(half), axis)

    def test_render_never_hides_an_unmeasured_scan(self):
        self.assertIn("НЕ ИЗМЕРЕНЫ", cd.render_orphans({}))
        self.assertIn("НЕ ИЗМЕРЕНЫ", cd.render_orphans(
            {"orphans": {"status": cd.ORPHAN_UNMEASURED, "reason": "дерево не под git"}}))
        self.assertEqual("", cd.render_orphans(
            {"orphans": {"status": cd.ORPHAN_MEASURED, "candidates": []}}))

    def test_idle_reason_separates_no_orphans_from_unmeasured_orphans(self):
        """Авария класса: «доставлять нечего» звучало как ответ про ОБА вопроса."""
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-baza.md": card("new")})
            measured = cd.deliver([], root=root, now=None, pusher=lambda *a, **k: (0, ""),
                                  write_status=False, use_debt=False,
                                  orphans=lambda r: ask(r))
            self.assertEqual(measured["status"], cd.IDLE)
            self.assertNotIn("НЕ ИЗМЕРЕНЫ", measured["reason"])
            blind = cd.deliver([], root=root, now=None, pusher=lambda *a, **k: (0, ""),
                               write_status=False, use_debt=False,
                               orphans=lambda r: {"status": cd.ORPHAN_UNMEASURED,
                                                  "candidates": [], "reason": "git молчит"})
            self.assertEqual(blind["status"], cd.IDLE)
            self.assertIn("НЕ ИЗМЕРЕНЫ", blind["reason"])


class WiringReachesThePusher(unittest.TestCase):
    """Опрос без проводки был бы «находка есть, а читателя нет» — класс #820."""

    class Pusher:
        def __init__(self):
            self.calls = []

        def __call__(self, root, paths, message, allow_overwrite=False):
            self.calls.append({"paths": list(paths), "message": message})
            return 0, "ok"

    def test_orphan_is_handed_to_the_pusher_without_any_caller_asking(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: заказ ПУСТ, а карточка всё равно едет."""
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-baza.md": card("new")},
                         only_local={"owner-decision-vopros.md": card("needs-owner")})
            pusher = self.Pusher()
            r = cd.deliver([], root=root, pusher=pusher, write_status=False,
                           use_debt=False, orphans=lambda rt: ask(rt),
                           reader=lambda rt, rel: (cd.REMOTE_ABSENT, None, "нет на origin"))
            self.assertEqual(r["status"], cd.DELIVERED, r["reason"])
            self.assertEqual([os.path.basename(p) for p in pusher.calls[0]["paths"]],
                             ["owner-decision-vopros.md"])
            self.assertEqual(r["orphans"]["status"], cd.ORPHAN_MEASURED)

    def test_switch_off_leaves_the_order_exactly_as_asked(self):
        """Выключатель обязан выключать — и ПРЕМИССА теста обязана быть настоящей.

        Сцена нарочно содержит сироту, которую опрос НАШЁЛ БЫ (`orphans=`
        передан явно): без этого замер #899 показал, что мутация «игнорировать
        `use_orphans`» ВЫЖИВАЕТ — умолчательный опрос в одноразовом репозитории
        честно отвечает «не измерено» (нет `origin`), и выключенное от
        включённого становится неотличимо по построению.
        """
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={"inbox-baza.md": card("new")},
                         only_local={"owner-decision-vopros.md": card("needs-owner")})
            self.assertEqual(len(ask(root)["candidates"]), 1, "премиса сцены не обеспечена")
            pusher = self.Pusher()
            r = cd.deliver([], root=root, pusher=pusher, write_status=False,
                           use_debt=False, use_orphans=False, orphans=lambda rt: ask(rt))
            self.assertEqual(r["status"], cd.IDLE)
            self.assertEqual(pusher.calls, [])
            self.assertIn("НЕ ИЗМЕРЕНЫ", r["reason"])

    def test_a_falling_scan_does_not_drop_the_ordered_cards(self):
        """Сбой опроса не смеет уронить заказанное — и не смеет выглядеть «сирот нет»."""
        with tempfile.TemporaryDirectory() as td:
            root = scene(td, on_ref={})
            path = os.path.join(root, cd.TRACKER_REL, "inbox-zakaz.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(card("new"))
            pusher = self.Pusher()

            def boom(_root):
                raise RuntimeError("git упал")

            r = cd.deliver([path], root=root, pusher=pusher, write_status=False,
                           use_debt=False, orphans=boom,
                           reader=lambda rt, rel: (cd.REMOTE_ABSENT, None, "нет"))
            self.assertEqual(r["status"], cd.DELIVERED, r["reason"])
            self.assertEqual(r["orphans"]["status"], cd.ORPHAN_UNMEASURED)
            self.assertIn("git упал", r["orphans"]["reason"])


class TheTerminalSetIsNotRewrittenFromMemory(unittest.TestCase):
    def test_terminal_set_matches_step_0a(self):
        """Копия множества обязана совпадать с НАСТОЯЩИМ определением шага 0a.

        `spa_core/` не читает `scripts/` (расслоение), поэтому множество
        скопировано литералом — а копия без сверки и есть тот дефект, против
        которого в этом модуле уже стоят такие же тесты на `_TRAIL_KEY`.
        """
        import importlib.util
        from spa_core.monitoring.architecture_conformance import REPO_ROOT

        path = os.path.join(REPO_ROOT, "scripts", "check_undelivered_work.py")
        if not os.path.isfile(path):
            self.fail(f"шага 0a нет по пути {path} — сверять копию НЕ С ЧЕМ, "
                      "и это отказ, а не повод промолчать")
        spec = importlib.util.spec_from_file_location("_step0a_for_orphans", path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(set(cd.ORPHAN_TERMINAL), set(mod.CARD_TERMINAL_STATUSES))


if __name__ == "__main__":
    unittest.main()
