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

    def __call__(self, root, paths, message):
        self.calls.append({"root": root, "paths": list(paths), "message": message})
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
        out = self.summarize({"generated_at": ts(hours_ago=0.1),
                              "created": [], "closed": [], "deferred": [],
                              "waiting_hysteresis": [], "escalated": [],
                              "sources_unread": [], "open_cards": 0,
                              "delivery": {"status": cd.DELIVERED, "attempted": ["a.md"],
                                           "delivered": ["a.md"]}})
        self.assertIn("DELIVERED", out)
        self.assertNotIn("⚠️", out)

    def test_unread_source_is_named(self):
        out = self.summarize({"created": [], "closed": [], "deferred": [],
                              "sources_unread": ["data/house_view_gap.json"]})
        self.assertIn("ИСТОЧНИК НЕ ПРОЧИТАН", out)


if __name__ == "__main__":
    unittest.main()
