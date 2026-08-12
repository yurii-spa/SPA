"""Доставка карточек петли до `origin/main` (ADR-066, цикл #170).

Каждый тест — положительный контроль реальной аварии 08.08, а не украшение:

* карточка, рождённая агентом в прод-дереве, на origin не попадала НИКОГДА
  (замер: 11 карточек с `finding_key:` в дереве, 7 на origin, и все семь
  приземлились лишь потому, что родились в worktree разработчика; из
  рождённых в рантайме — **0 из 4**, все четыре `needs-owner`);
* провал доставки обязан быть НАЗВАН — «тихий ноль» и есть тот класс fail-OPEN,
  из-за которого потеря жила незамеченной;
* пачка отклоняется ЦЕЛИКОМ: доставить «сколько получилось» — это молчаливое
  обрезание, запрещённое правилом «no silent caps»;
* обязательный шаг 0-офис печатал по мосту одну строку `generated_at`: ветка
  разбора звалась `findings_bridge.json`, а отчёт зовётся
  `findings_bridge_report.json` — мёртвая проводка при живых деталях (#144).

Пушер здесь ВСЕГДА инъектируется: тест, ушедший в сеть или в очередь владельца,
фальсифицирует и то и другое.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import tempfile
import unittest

from spa_core.monitoring import card_delivery as cd
from spa_core.monitoring import findings_bridge as fb
from spa_core.tests._freshness import ts

NOW = dt.datetime(2030, 3, 1, 12, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: injected-clock — часы инъектируются
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Pusher:
    """Инъектируемый пушер: считает ВЫЗОВЫ (а не файлы) — так видно, ушла ли
    пачка одним коммитом или рассыпалась пофайлово (урок цикла #53)."""

    def __init__(self, rc=0, out="ok", boom=None):
        self.rc, self.out, self.boom = rc, out, boom
        self.calls = []

    def __call__(self, root, paths, message, allow_overwrite=False):
        # `allow_overwrite` записываем, а не игнорируем: осознанная перезапись —
        # это то, чем перенос правки на свежий origin отличается от слепого
        # затирания, и тест обязан видеть разницу (цикл #200).
        self.calls.append({"root": root, "paths": list(paths), "message": message,
                           "allow_overwrite": allow_overwrite})
        if self.boom:
            raise self.boom
        return self.rc, self.out


def mkroot(td, cards=("inbox-a.md",)):
    """Дерево с каталогом карточек. Карточки — реальные файлы, как в проде."""
    tracker = os.path.join(td, cd.TRACKER_REL)
    os.makedirs(tracker, exist_ok=True)
    os.makedirs(os.path.join(td, "data"), exist_ok=True)
    paths = []
    for name in cards:
        p = os.path.join(tracker, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"---\nstatus: new\n---\n\n# {name}\n")
        paths.append(os.path.realpath(p))
    # realpath: на macOS /var — симлинк на /private/var, и доставка нормализует
    # пути так же. Сравнивать надо одну и ту же форму, иначе тест ловит симлинк,
    # а не поведение.
    return os.path.realpath(td), paths


class DeliversWhatTheLoopCreated(unittest.TestCase):
    def test_card_born_in_the_tree_is_handed_to_the_pusher(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ аварии: раньше пуша не было ни одной строкой."""
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td, ("owner-decision-kritichnaya.md",))
            p = Pusher()
            r = cd.deliver(paths, root=root, now=NOW, pusher=p)
            self.assertEqual(r["status"], cd.DELIVERED)
            self.assertEqual(len(p.calls), 1)
            self.assertEqual(p.calls[0]["paths"], paths)
            self.assertEqual(r["delivered"],
                             [os.path.join(cd.TRACKER_REL, "owner-decision-kritichnaya.md")])

    def test_whole_batch_is_one_call(self):
        """Пачка = ОДИН коммит. Пофайлово = N коммитов и красный промежуточный main."""
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td, ("a.md", "b.md", "c.md"))
            p = Pusher()
            cd.deliver(paths, root=root, now=NOW, pusher=p)
            self.assertEqual(len(p.calls), 1)
            self.assertEqual(len(p.calls[0]["paths"]), 3)

    def test_duplicates_collapse_but_order_survives(self):
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td, ("a.md", "b.md"))
            p = Pusher()
            cd.deliver([paths[1], paths[0], paths[1]], root=root, now=NOW, pusher=p)
            self.assertEqual(p.calls[0]["paths"], [paths[1], paths[0]])

    def test_relative_paths_are_resolved_against_root(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td, ("a.md",))
            p = Pusher()
            r = cd.deliver([os.path.join(cd.TRACKER_REL, "a.md")], root=root, now=NOW, pusher=p)
            self.assertEqual(r["status"], cd.DELIVERED)


class FailureIsNamedNeverSilent(unittest.TestCase):
    def test_pusher_nonzero_is_failed_with_reason(self):
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            r = cd.deliver(paths, root=root, now=NOW, pusher=Pusher(rc=4, out="отказ стража"))
            self.assertEqual(r["status"], cd.FAILED)
            self.assertEqual(r["delivered"], [])
            self.assertEqual(r["returncode"], 4)
            self.assertIn("отказ стража", r["output"])
            self.assertTrue(r["reason"])

    def test_pusher_exception_is_unchecked_not_success(self):
        """«Не измерено» ≠ «доставлено» — урок правила доставки 2026-08-04."""
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            r = cd.deliver(paths, root=root, now=NOW, pusher=Pusher(boom=RuntimeError("таймаут")))
            self.assertEqual(r["status"], cd.UNCHECKED)
            self.assertIn("таймаут", r["reason"])
            self.assertEqual(r["delivered"], [])

    def test_missing_pusher_tool_is_unchecked_not_delivered(self):
        """Реальный дефолтный пушер в дереве без push_to_github.py: rc=None."""
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            r = cd.deliver(paths, root=root, now=NOW)  # дефолтный пушер, сети не будет
            self.assertEqual(r["status"], cd.UNCHECKED)
            self.assertEqual(r["delivered"], [])

    def test_disabled_is_named_and_pusher_never_called(self):
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            p = Pusher()
            r = cd.deliver(paths, root=root, now=NOW, pusher=p, env={cd.ENV_FLAG: "0"})
            self.assertEqual(r["status"], cd.DISABLED)
            self.assertEqual(p.calls, [])
            self.assertIn("НЕ попали", r["reason"])

    def test_empty_batch_is_idle_not_ok(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td)
            p = Pusher()
            r = cd.deliver([], root=root, now=NOW, pusher=p)
            self.assertEqual(r["status"], cd.IDLE)
            self.assertEqual(p.calls, [])

    def test_not_delivered_statuses_are_enumerated(self):
        """Читателю квитанции нельзя помнить список наизусть — он в модуле."""
        for st in (cd.FAILED, cd.REFUSED, cd.UNCHECKED, cd.DISABLED):
            self.assertIn(st, cd.NOT_DELIVERED)
        self.assertNotIn(cd.DELIVERED, cd.NOT_DELIVERED)

    def test_render_shows_the_refusal(self):
        r = {"status": cd.FAILED, "attempted": ["a"], "reason": "пушер вернул 4"}
        self.assertIn("FAILED", cd.render(r))
        self.assertIn("пушер вернул 4", cd.render(r))
        self.assertIn("DELIVERED", cd.render({"status": cd.DELIVERED, "attempted": ["a"],
                                              "delivered": ["a"]}))


class RefusesTheWholeBatch(unittest.TestCase):
    def test_path_outside_tracker_refuses_everything(self):
        """Доставить «сколько получилось» = молчаливое обрезание. Отказ целиком."""
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td, ("a.md",))
            outsider = os.path.join(root, "spa_core", "risk", "policy.py")
            os.makedirs(os.path.dirname(outsider), exist_ok=True)
            open(outsider, "w").close()
            p = Pusher()
            r = cd.deliver(paths + [outsider], root=root, now=NOW, pusher=p)
            self.assertEqual(r["status"], cd.REFUSED)
            self.assertEqual(p.calls, [])
            self.assertTrue(any("вне" in b["reason"] for b in r["refused"]))

    def test_board_md_is_never_delivered(self):
        """`_BOARD.md` — общая память: база из прод-дерева неизмерима ⇒ пушер
        отказал бы fail-CLOSED (ADR-070 п.7) и уронил бы всю пачку."""
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td, ("a.md", "_BOARD.md"))
            p = Pusher()
            r = cd.deliver(paths, root=root, now=NOW, pusher=p)
            self.assertEqual(r["status"], cd.REFUSED)
            self.assertEqual(p.calls, [])
            self.assertTrue(any("общая память" in b["reason"] for b in r["refused"]))

    def test_missing_file_is_refused_named(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td)
            ghost = os.path.join(root, cd.TRACKER_REL, "ghost.md")
            r = cd.deliver([ghost], root=root, now=NOW, pusher=Pusher())
            self.assertEqual(r["status"], cd.REFUSED)
            self.assertIn("нет на диске", r["refused"][0]["reason"])

    def test_non_md_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td)
            junk = os.path.join(root, cd.TRACKER_REL, "notes.txt")
            open(junk, "w").close()
            r = cd.deliver([junk], root=root, now=NOW, pusher=Pusher())
            self.assertEqual(r["status"], cd.REFUSED)


class ReceiptSurvivesOnDisk(unittest.TestCase):
    def _receipt(self, root):
        return json.load(open(os.path.join(root, cd.STATUS_REL)))

    def test_receipt_written_on_success(self):
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            r = cd.deliver(paths, root=root, now=NOW, pusher=Pusher())
            self.assertEqual(self._receipt(root)["status"], cd.DELIVERED)
            self.assertEqual(self._receipt(root)["generated_at"], r["generated_at"])

    def test_receipt_written_on_failure_too(self):
        """Квитанция только об успехе — это и есть тихая потеря."""
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td)
            cd.deliver(paths, root=root, now=NOW, pusher=Pusher(rc=1))
            self.assertEqual(self._receipt(root)["status"], cd.FAILED)

    def test_receipt_written_on_refusal_too(self):
        with tempfile.TemporaryDirectory() as td:
            root, paths = mkroot(td, ("a.md", "_BOARD.md"))
            cd.deliver(paths, root=root, now=NOW, pusher=Pusher())
            self.assertEqual(self._receipt(root)["status"], cd.REFUSED)


class BridgeHandsItsCardsToDelivery(unittest.TestCase):
    """Проводка, а не деталь: мост обязан ЗВАТЬ доставку (урок #144)."""

    def _findings(self, td, findings):
        os.makedirs(os.path.join(td, "data"), exist_ok=True)
        json.dump({"findings": findings}, open(os.path.join(td, "data",
                  "architecture_conformance.json"), "w"))

    def test_created_card_is_delivered(self):
        with tempfile.TemporaryDirectory() as td:
            self._findings(td, [{"key": "k1", "severity": "CRITICAL", "message": "зомби"}])
            seen = {}

            def fake_deliver(paths, root=None, now=None):
                seen["paths"] = list(paths)
                return {"status": cd.DELIVERED, "attempted": list(paths),
                        "delivered": list(paths), "reason": "", "generated_at": now.isoformat()}

            r = fb.run_bridge(root=td, now=NOW,
                              create=lambda root, f: os.path.join(td, "card-k1.md"),
                              close=lambda root, p: True, notify=lambda root, p: True,
                              deliver=fake_deliver)
            self.assertEqual(seen["paths"], [os.path.join(td, "card-k1.md")])
            self.assertEqual(r["delivery"]["status"], cd.DELIVERED)

    def test_closed_card_is_delivered_too(self):
        """Закрытая только в дереве карточка остаётся на origin ОТКРЫТОЙ —
        очередь показывает работу, которой нет (класс #147)."""
        with tempfile.TemporaryDirectory() as td:
            self._findings(td, [])
            state = {"findings": {"gone": {"first_seen": NOW.isoformat(), "seen_count": 3,
                                           "severity": "WARN", "card": os.path.join(td, "old.md"),
                                           "status": "carded"}}, "daily": {}}
            json.dump(state, open(os.path.join(td, fb.STATE_REL), "w"))
            seen = {}

            def fake_deliver(paths, root=None, now=None):
                seen["paths"] = list(paths)
                return {"status": cd.DELIVERED, "attempted": list(paths), "delivered": list(paths)}

            fb.run_bridge(root=td, now=NOW, create=lambda root, f: None,
                          close=lambda root, p: True, notify=lambda root, p: True,
                          deliver=fake_deliver)
            self.assertEqual(seen["paths"], [os.path.join(td, "old.md")])

    def test_delivery_blowup_never_kills_the_bridge(self):
        with tempfile.TemporaryDirectory() as td:
            self._findings(td, [{"key": "k1", "severity": "CRITICAL", "message": "зомби"}])

            def boom(paths, root=None, now=None):
                raise RuntimeError("сеть легла")

            r = fb.run_bridge(root=td, now=NOW,
                              create=lambda root, f: os.path.join(td, "card-k1.md"),
                              close=lambda root, p: True, notify=lambda root, p: True,
                              deliver=boom)
            self.assertEqual(len(r["created"]), 1)
            self.assertEqual(r["delivery"]["status"], "UNCHECKED")
            self.assertIn("сеть легла", r["delivery"]["reason"])

    def test_report_always_carries_a_delivery_block(self):
        with tempfile.TemporaryDirectory() as td:
            self._findings(td, [])
            r = fb.run_bridge(root=td, now=NOW, create=lambda root, f: None,
                              close=lambda root, p: True, notify=lambda root, p: True)
            self.assertIn("delivery", r)
            self.assertEqual(r["delivery"]["status"], cd.IDLE)
            saved = json.load(open(os.path.join(td, fb.REPORT_REL)))
            self.assertIn("delivery", saved)


class OfficeStepSeesTheBridge(unittest.TestCase):
    """Шаг 0-офис ОБЯЗАН показывать мост. Ветка звалась `findings_bridge.json` —
    такого файла не производит никто, и печаталась одна строка `generated_at`,
    хотя манифест требует «deferred читать ОБЯЗАТЕЛЬНО»."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "consume_office_reports_cd",
            os.path.join(REPO_ROOT, "scripts", "consume_office_reports.py"))
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def summarize(self, report):
        return "\n".join(self.mod._summarize_json("data/findings_bridge_report.json", report))

    def test_real_report_name_is_the_one_the_producer_writes(self):
        self.assertEqual(os.path.basename(fb.REPORT_REL), "findings_bridge_report.json")

    def test_deferred_is_shouted(self):
        out = self.summarize({"created": [], "closed": [], "deferred": ["k9"],
                              "waiting_hysteresis": [], "open_cards": 3})
        self.assertIn("k9", out)
        self.assertIn("ОТЛОЖЕНО", out)

    def test_failed_delivery_is_shouted(self):
        out = self.summarize({"created": [], "closed": [], "deferred": [],
                              "delivery": {"status": cd.FAILED, "attempted": ["a.md"],
                                           "delivered": [], "reason": "пушер вернул 4"}})
        self.assertIn("ДОСТАВКА КАРТОЧЕК FAILED", out)
        self.assertIn("пушер вернул 4", out)

    def test_missing_delivery_block_is_named(self):
        out = self.summarize({"created": [], "closed": [], "deferred": []})
        self.assertIn("НЕ ИЗМЕРЕНА", out)

    def test_successful_delivery_is_quiet_but_present(self):
        # Фикстура приведена к ФОРМЕ ПРОИЗВОДИТЕЛЯ (`findings_bridge.py` строит
        # отчёт одним литералом, все ключи безусловны) — намеренно, цикл #176.
        # Прежний вариант перечислял три ключа из десяти, и утверждение «тихо»
        # делалось о документе, которого не пишет никто: с появлением строки
        # «СХЕМА РАЗОШЛАСЬ» (сторож ветки, читающей несуществующие поля) такой
        # обрезок честно объявлялся дрейфом. Проверка УСИЛЕНА, а не ослаблена:
        # «успешная доставка молчит» теперь утверждается о настоящей форме, и
        # ⚠️ по-прежнему запрещено — включая ⚠️ о возрасте и о схеме.
        # ИЗМЕНЕНО НАМЕРЕННО (цикл #204, ADR-081, инвариант #16 — обоснование
        # здесь и в `docs/journal/2026-W33.md`): в квитанцию добавлен блок
        # `debt`, и производитель пишет его БЕЗУСЛОВНО. Утверждение теста —
        # «успешная доставка молчит» — оставлено ДОСЛОВНО, включая запрет ⚠️;
        # правится ровно фикстура, и правится в ту сторону, которую требует
        # комментарий выше: «форма ПРОИЗВОДИТЕЛЯ, а не обрезок». Квитанция без
        # блока долга — это отчёт СТАРОГО образца, и ⚠️ «долг НЕ ИЗМЕРЕН» на
        # него честна: молчание там означало бы «долга нет», чего никто не
        # мерил. Проверка усилена: успех обязан молчать при ИЗМЕРЕННОМ нуле, а
        # неизмеренный долг обязан быть слышен (`test_consume_office_reports.py`
        # ::test_receipt_without_debt_block_says_unmeasured_not_zero).
        out = self.summarize({"generated_at": ts(hours_ago=0.1),
                              "created": [], "closed": [], "deferred": [],
                              "waiting_hysteresis": [], "escalated": [],
                              "sources_unread": [], "open_cards": 0,
                              "delivery": {"status": cd.DELIVERED, "attempted": ["a.md"],
                                           "delivered": ["a.md"],
                                           "debt": {"count": 0, "paths": [],
                                                    "oldest_hours": None, "stale": [],
                                                    "stale_after": cd.DEBT_STALE_ATTEMPTS,
                                                    "dropped": [], "retried": []}}})
        self.assertIn("DELIVERED", out)
        self.assertNotIn("⚠️", out)

    def test_unread_source_is_named(self):
        out = self.summarize({"created": [], "closed": [], "deferred": [],
                              "sources_unread": ["data/house_view_gap.json"]})
        self.assertIn("ИСТОЧНИК НЕ ПРОЧИТАН", out)


# ══════════════════════════════════════════════════════════════════════════════
# АВАРИЯ 2026-08-12 (цикл #200): доставка умела только РОЖДАТЬ карточку
#
# `delivery.status=FAILED, returncode=4, attempted 3, delivered 0`. Пушер судит
# по базе РАБОЧЕЙ КОПИИ (`HEAD:<путь>`), а карточка, рождённая мостом в
# прод-дереве, в HEAD этого дерева не попадает никогда ⇒ создание проходит
# (`absent_in_base` + нет на remote), а любое ОБНОВЛЕНИЕ — `absent_in_base` +
# файл на remote ЕСТЬ ⇒ `DIVERGED` ⇒ отказ. Навсегда.
#
# Каждый тест ниже — воспроизведение конкретной половины той аварии; на
# непочиненном модуле все они красные (`plan_batch`/`rebase_card` там нет).
# ══════════════════════════════════════════════════════════════════════════════

def card(status: str = "new", extra: str = "", body: str = "\n# карточка\n") -> bytes:
    """Карточка в той же форме, что пишет `orchestrator_queue create`."""
    return (f"---\ntrackerStatus:\n  type: inbox\nstatus: {status}\n"
            f"finding_key: \"B3:k\"\n{extra}---\n{body}").encode("utf-8")


class Remote:
    """Инъектируемое чтение origin. Ключ — ИМЯ файла (пути в тестах временные).

    Значение: ``bytes`` — есть на origin · ``None`` — нет (создание) ·
    строка — «не измерено» с этой причиной. Три исхода, а не два: схлопывание
    «нет файла» и «не смогли посмотреть» и есть тот fail-OPEN, из-за которого
    слепота выглядела бы чистым созданием.
    """

    def __init__(self, table=None):
        self.table = table or {}
        self.reads = []

    def __call__(self, root, repo_path):
        self.reads.append(repo_path)
        v = self.table.get(os.path.basename(repo_path))
        if v is None:
            return cd.REMOTE_ABSENT, None, "на origin файла нет"
        if isinstance(v, str):
            return cd.REMOTE_UNMEASURED, None, v
        return cd.REMOTE_PRESENT, v, ""


def write(root, name, blob: bytes) -> str:
    p = os.path.join(root, cd.TRACKER_REL, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(blob)
    return os.path.realpath(p)


class UpdateOfALiveCardIsDelivered(unittest.TestCase):
    def test_closure_of_a_card_already_on_origin_reaches_origin(self):
        """ГЛАВНЫЙ положительный контроль: раньше здесь был вечный код 4."""
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td, ())
            p = write(root, "inbox-nahodka.md", card("done"))
            pusher = Pusher()
            r = cd.deliver([p], root=root, now=NOW, pusher=pusher,
                           reader=Remote({"inbox-nahodka.md": card("new")}))
            self.assertEqual(r["status"], cd.DELIVERED)
            self.assertEqual(pusher.calls[0]["paths"], [p])
            self.assertEqual(len(r["rebased"]), 1)
            self.assertIn("status: done", r["rebased"][0]["status_line"])

    def test_overwrite_is_conscious_and_only_after_reading_remote(self):
        """Флаг перезаписи — следствие ПРОЧИТАННОГО remote, а не привычка."""
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td, ())
            p = write(root, "inbox-nahodka.md", card("done"))
            pusher = Pusher()
            reader = Remote({"inbox-nahodka.md": card("new")})
            cd.deliver([p], root=root, now=NOW, pusher=pusher, reader=reader)
            self.assertTrue(pusher.calls[0]["allow_overwrite"])
            self.assertEqual(reader.reads, ["nimbalyst-local/tracker/inbox-nahodka.md"])

    def test_creation_never_asks_for_overwrite(self):
        """Рождение карточки ничего не перезаписывает — флага быть не должно."""
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td, ())
            p = write(root, "inbox-new.md", card("new"))
            pusher = Pusher()
            r = cd.deliver([p], root=root, now=NOW, pusher=pusher, reader=Remote())
            self.assertEqual(r["status"], cd.DELIVERED)
            self.assertFalse(pusher.calls[0]["allow_overwrite"])
            self.assertEqual(r["rebased"], [])

    def test_identical_remote_is_not_pushed_again(self):
        """Наша версия и есть версия origin — пушить нечего, и это не «успех»."""
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td, ())
            p = write(root, "inbox-same.md", card("done"))
            pusher = Pusher()
            r = cd.deliver([p], root=root, now=NOW, pusher=pusher,
                           reader=Remote({"inbox-same.md": card("done")}))
            self.assertEqual(r["status"], cd.IDLE)
            self.assertEqual(pusher.calls, [])
            self.assertEqual(r["already_on_origin"],
                             ["nimbalyst-local/tracker/inbox-same.md"])

    def test_receipt_records_the_remote_sha(self):
        """Окно между чтением и пушем есть — потеря обязана быть вычислимой."""
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td, ())
            p = write(root, "inbox-nahodka.md", card("done"))
            remote = card("new")
            r = cd.deliver([p], root=root, now=NOW, pusher=Pusher(),
                           reader=Remote({"inbox-nahodka.md": remote}))
            self.assertEqual(r["rebased"][0]["remote_sha"], cd.blob_sha(remote)[:8])


class BlindCopyMayNotStompWhatItNeverSaw(unittest.TestCase):
    """Второй дефект того же корня: мост судит «карточку никто не трогал» по
    СВОЕЙ стухшей копии, которая не видит ни ответа владельца, ни захвата."""

    def _refusal(self, extra_on_origin):
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td, ())
            p = write(root, "inbox-nahodka.md", card("done"))
            pusher = Pusher()
            r = cd.deliver([p], root=root, now=NOW, pusher=pusher,
                           reader=Remote({"inbox-nahodka.md": card("needs-owner",
                                                                  extra=extra_on_origin)}))
            return r, pusher

    def test_owner_answer_on_origin_cancels_the_closure(self):
        r, pusher = self._refusal("owner_choice: variant_2\n")
        self.assertEqual(r["status"], cd.REFUSED)
        self.assertEqual(pusher.calls, [])
        self.assertIn("owner_choice", r["rebase_refused"][0]["reason"])
        self.assertIn("origin", r["rebase_refused"][0]["reason"])

    def test_card_claimed_by_a_session_is_not_closed_behind_its_back(self):
        r, pusher = self._refusal("claimed_by: pid4242\n")
        self.assertEqual(r["status"], cd.REFUSED)
        self.assertEqual(pusher.calls, [])
        self.assertIn("claimed_by", r["rebase_refused"][0]["reason"])

    def test_body_changed_on_origin_is_refused_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td, ())
            p = write(root, "inbox-nahodka.md", card("done"))
            r = cd.deliver([p], root=root, now=NOW, pusher=Pusher(),
                           reader=Remote({"inbox-nahodka.md":
                                          card("new", body="\n# карточка\n\nдописано на origin\n")}))
            self.assertEqual(r["status"], cd.REFUSED)
            self.assertIn("status:", r["rebase_refused"][0]["reason"])
            self.assertIn("вручную", r["rebase_refused"][0]["reason"])


class OneStuckCardNoLongerDropsTheOthers(unittest.TestCase):
    def test_the_real_batch_of_2026_08_12(self):
        """Форма аварии дословно: два застрявших обновления + одно создание.

        Раньше пачка была атомарной ⇒ создание НЕ доехало из-за чужих отказов
        (`…docs-system-briefing-md-po` не попало на origin вовсе).
        """
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td, ())
            stuck1 = write(root, "inbox-health.md", card("done"))
            stuck2 = write(root, "inbox-postura.md", card("done"))
            fresh = write(root, "inbox-briefing.md", card("new"))
            pusher = Pusher()
            r = cd.deliver([stuck1, stuck2, fresh], root=root, now=NOW, pusher=pusher,
                           reader=Remote({
                               "inbox-health.md": card("new", extra="claimed_by: pid1\n"),
                               "inbox-postura.md": card("new", extra="owner_choice: yes\n"),
                           }))
            self.assertEqual(r["status"], cd.PARTIAL)
            self.assertEqual(pusher.calls[0]["paths"], [fresh])
            self.assertEqual(len(r["rebase_refused"]), 2)

    def test_partial_never_reads_as_success(self):
        self.assertIn(cd.PARTIAL, cd.NOT_DELIVERED)
        line = cd.render({"status": cd.PARTIAL, "attempted": ["a", "b"],
                          "rebased": [], "reason": "ЗАСТРЯЛО 1"})
        self.assertIn("⚠️", line)
        self.assertIn("ЗАСТРЯЛО 1", line)


class UnmeasuredRemoteIsNamedNotAssumed(unittest.TestCase):
    def test_unreadable_origin_is_left_to_the_pusher_and_named(self):
        """«Не смогли посмотреть» ≠ «там ничего нет». Решает пушер (он fail-CLOSED),
        а квитанция обязана сказать, что перенос НЕ проверялся."""
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td, ())
            p = write(root, "inbox-nahodka.md", card("done"))
            pusher = Pusher()
            r = cd.deliver([p], root=root, now=NOW, pusher=pusher,
                           reader=Remote({"inbox-nahodka.md": "сеть недоступна"}))
            self.assertEqual(pusher.calls[0]["paths"], [p])
            self.assertFalse(pusher.calls[0]["allow_overwrite"])
            self.assertEqual(r["rebase_unmeasured"][0]["reason"], "сеть недоступна")

    def test_default_reader_without_pusher_tool_is_unmeasured_not_absent(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td, ())
            state, blob, why = cd._default_remote_reader(root, "nimbalyst-local/tracker/a.md")
            self.assertEqual(state, cd.REMOTE_UNMEASURED)
            self.assertIsNone(blob)
            self.assertIn(cd.PUSHER_REL, why)


class RebaseIsProvableNotHeuristic(unittest.TestCase):
    def test_only_the_status_line_may_differ(self):
        merged, why = cd.rebase_card(card("done"), card("new"))
        self.assertEqual(merged, card("done"))
        self.assertEqual(why, "")

    def test_result_is_built_from_remote_bytes(self):
        """Результат строится ИЗ remote — иначе «перенос» был бы просто нашей копией."""
        remote = card("new")
        merged, _ = cd.rebase_card(card("done"), remote)
        self.assertIn(b"finding_key", merged)
        self.assertEqual(merged.replace(b"status: done", b"status: new"), remote)

    def test_not_a_card_is_refused_on_both_sides(self):
        self.assertIsNone(cd.rebase_card(b"just text\n", card("new"))[0])
        self.assertIsNone(cd.rebase_card(card("done"), b"just text\n")[0])

    def test_missing_status_line_is_refused(self):
        no_status = b"---\ntrackerStatus:\n  type: inbox\n---\n\n# x\n"
        self.assertIsNone(cd.rebase_card(no_status, card("new"))[0])
        self.assertIsNone(cd.rebase_card(card("done"), no_status)[0])


# ══════════════════════════════════════════════════════════════════════════════
# ДЫРА В САМОЙ ПОЧИНКЕ (цикл #201, найдена при подъёме работы #200)
#
# `--allow-overwrite` — флаг КОМАНДЫ, а не файла: `push_to_github.guard_overwrite`
# при нём отдаёт DIVERGED в перезапись молча и снимает стража общей памяти. Значит
# один доказанный перенос в пачке разоружал стража для ВСЕХ её путей — в том числе
# для того, чей origin прочитать не удалось и у которого пушер был единственной
# защитой. Обещание «не измерено ⇒ решает пушер, он fail-CLOSED» держалось только
# в пачке из ОДНОЙ карточки — ровно в той, где оно не могло сломаться, и ровно её
# проверял тест `test_unreadable_origin_is_left_to_the_pusher_and_named`.
#
# Цена: ответ владельца (`owner_choice`, кнопки ADR-069), появившийся на origin,
# стирается слепой копией — то самое, что запрещает п.3 ADR-080 и инвариант #14.
# ══════════════════════════════════════════════════════════════════════════════

class UnmeasuredCardDoesNotRideUnderSomeoneElsesOverwrite(unittest.TestCase):
    def _mixed(self, td):
        """Пачка 12.08 в самом опасном составе: перенос + непрочитанный origin."""
        root, _ = mkroot(td, ())
        rebased = write(root, "inbox-perenos.md", card("done"))
        blind = write(root, "inbox-slepaya.md", card("done"))
        reader = Remote({"inbox-perenos.md": card("new"),
                         "inbox-slepaya.md": "сеть недоступна"})
        return root, rebased, blind, reader

    def test_unmeasured_card_is_held_out_of_the_overwrite_batch(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: до починки слепой путь уезжал под чужим флагом."""
        with tempfile.TemporaryDirectory() as td:
            root, rebased, blind, reader = self._mixed(td)
            pusher = Pusher()
            r = cd.deliver([rebased, blind], root=root, now=NOW,
                           pusher=pusher, reader=reader)
            self.assertEqual(pusher.calls[0]["paths"], [rebased])
            self.assertNotIn(blind, pusher.calls[0]["paths"])
            self.assertTrue(pusher.calls[0]["allow_overwrite"])
            self.assertEqual([h["path"] for h in r["held"]],
                             ["nimbalyst-local/tracker/inbox-slepaya.md"])
            self.assertIn("ПРИДЕРЖАНА", r["held"][0]["reason"])

    def test_held_card_is_not_counted_as_delivered(self):
        """Придержанное не смеет попасть в `delivered`: это и есть тихая потеря."""
        with tempfile.TemporaryDirectory() as td:
            root, rebased, blind, reader = self._mixed(td)
            r = cd.deliver([rebased, blind], root=root, now=NOW,
                           pusher=Pusher(), reader=reader)
            self.assertNotIn("nimbalyst-local/tracker/inbox-slepaya.md", r["delivered"])

    def test_a_batch_with_a_held_card_never_reads_as_success(self):
        """Пушер вернул 0, но пачка НЕ доставлена целиком — статус обязан это сказать."""
        with tempfile.TemporaryDirectory() as td:
            root, rebased, blind, reader = self._mixed(td)
            r = cd.deliver([rebased, blind], root=root, now=NOW,
                           pusher=Pusher(rc=0), reader=reader)
            self.assertEqual(r["status"], cd.PARTIAL)
            self.assertIn(r["status"], cd.NOT_DELIVERED)
            self.assertIn("inbox-slepaya.md", r["reason"])
            self.assertIn("⚠️", cd.render(r))

    def test_owner_answer_we_could_not_read_is_never_overwritten(self):
        """Суть аварии, а не её форма: под чужим флагом пушер молча перезаписал бы
        карточку, на которой владелец УЖЕ нажал кнопку, — а мы этого не видели."""
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td, ())
            rebased = write(root, "inbox-perenos.md", card("done"))
            blind = write(root, "own-vopros.md", card("done"))
            # На origin у неё ответ владельца. Прочитать мы его не смогли —
            # значит и права затирать у нас нет НИКАКОГО.
            pusher = Pusher()
            cd.deliver([rebased, blind], root=root, now=NOW, pusher=pusher,
                       reader=Remote({"inbox-perenos.md": card("new"),
                                      "own-vopros.md": "HTTP 502 при чтении origin"}))
            self.assertNotIn(blind, pusher.calls[0]["paths"])

    def test_without_a_rebase_the_unmeasured_card_still_rides(self):
        """Контроль в ОБРАТНУЮ сторону: чинили состав пачки, а не саму доставку.
        Нет переноса ⇒ нет флага ⇒ пушер сам fail-CLOSED, и путь едет как раньше."""
        with tempfile.TemporaryDirectory() as td:
            root, _ = mkroot(td, ())
            blind = write(root, "inbox-slepaya.md", card("done"))
            pusher = Pusher()
            r = cd.deliver([blind], root=root, now=NOW, pusher=pusher,
                           reader=Remote({"inbox-slepaya.md": "сеть недоступна"}))
            self.assertEqual(pusher.calls[0]["paths"], [blind])
            self.assertFalse(pusher.calls[0]["allow_overwrite"])
            self.assertEqual(r["held"], [])


if __name__ == "__main__":
    unittest.main()
