#!/usr/bin/env python3
"""Тесты сторожа доставки следа решения владельца (ADR-086).

Каждый тест — положительный контроль настоящей аварии, а не украшение. Авария
измерена 2026-08-15 (цикл #247) на живом прод-дереве против `origin/main`:
след ответа владельца несут 9 карточек, у ДВУХ его на origin нет ВОВСЕ —
`own-rnd-duty-is-concentration-adr055` (вариант A, 08.08) и
`owner-decision-morfo-40-knigi-…` (вариант 1, 08.08). Обе там же, где их назвали
ещё в #178, неделю спустя.

Форма аварии воспроизводится дословно, включая то, что делает её нетривиальной:
**на origin тело карточки БОГАЧЕ** (инжестирующая сессия переписала раздел ответа
своим разбором), поэтому пуш нашей копии целиком не «доставил бы», а потерял бы
работу сессии. Тесты держат обе границы сразу: след обязан доехать, тело и
`status:` обязаны остаться origin'ными.

Время — ВХОД (`now=NOW`), и обе стороны закреплены: часы инъектируются, а отметки в
фикстурах — это не «сегодня», а ЗАПИСАННЫЕ моменты ответа владельца из аварии 08.08,
предмет проверки сам по себе (сторож обязан довезти именно их, байт в байт). Сдвиг
календаря на этот набор не влияет ни одним тестом.
"""
# FROZEN-DATE-OK: injected-clock — часы приходят входом (`now=NOW`, 2026-03-04), а
# литеральные отметки в фикстурах суть ЗНАЧЕНИЯ следа ответа владельца из аварии
# 2026-08-08 (`owner_answered_at`), которые сторож переносит дословно. Ни одна
# проверка не сравнивает их с текущей датой, поэтому календарь их не задевает.
from __future__ import annotations

import datetime as dt
import json
import os
import unittest

from spa_core.monitoring import owner_answer_delivery as oad

NOW = dt.datetime(2026, 3, 4, 5, 6, 7, tzinfo=dt.timezone.utc)  # вход, не календарь

TRACKER = os.path.join("nimbalyst-local", "tracker")

# ── формы карточки: ровно то, что пишет бот, и ровно то, что лежит на origin ──

ORIGIN_CARD = b"""---
trackerStatus:
  type: owner-decision
title: "\xd0\x9c\xd0\xbe\xd1\x80\xd1\x84\xd0\xbe"
status: ingested
source: nimbalyst
created: 2026-08-02
priority: high
---

## \xd0\xa7\xd1\x82\xd0\xbe \xd1\x81\xd0\xbb\xd1\x83\xd1\x87\xd0\xb8\xd0\xbb\xd0\xbe\xd1\x81\xd1\x8c

\xd0\xa2\xd0\xb5\xd0\xba\xd1\x81\xd1\x82 \xd0\xba\xd0\xb0\xd1\x80\xd1\x82\xd0\xbe\xd1\x87\xd0\xba\xd0\xb8.

## OTVET VLADELTSA: variant 1

\xd0\x9f\xd0\xbe\xd0\xb4\xd1\x80\xd0\xbe\xd0\xb1\xd0\xbd\xd1\x8b\xd0\xb9 \xd1\x80\xd0\xb0\xd0\xb7\xd0\xb1\xd0\xbe\xd1\x80 \xd1\x81\xd0\xb5\xd1\x81\xd1\x81\xd0\xb8\xd0\xb8, \xd0\xba\xd0\xbe\xd1\x82\xd0\xbe\xd1\x80\xd1\x8b\xd0\xb9 \xd1\x82\xd0\xb5\xd1\x80\xd1\x8f\xd1\x82\xd1\x8c \xd0\xbd\xd0\xb5\xd0\xbb\xd1\x8c\xd0\xb7\xd1\x8f.
"""

# Прод-копия: тот же заголовок + СЛЕД, но тело — сырой блок бота (беднее origin).
LOCAL_CARD = b"""---
trackerStatus:
  type: owner-decision
title: "\xd0\x9c\xd0\xbe\xd1\x80\xd1\x84\xd0\xbe"
status: owner-done
source: nimbalyst
created: 2026-08-02
priority: high
owner_choice: 1
owner_answered_at: 2026-08-08T21:11:37.367367+00:00
owner_answer_via: telegram
owner_answered_by: 258651137
---

## \xd0\xa7\xd1\x82\xd0\xbe \xd1\x81\xd0\xbb\xd1\x83\xd1\x87\xd0\xb8\xd0\xbb\xd0\xbe\xd1\x81\xd1\x8c

\xd0\xa2\xd0\xb5\xd0\xba\xd1\x81\xd1\x82 \xd0\xba\xd0\xb0\xd1\x80\xd1\x82\xd0\xbe\xd1\x87\xd0\xba\xd0\xb8.

---

## \xd0\xa0\xd0\xb5\xd1\x88\xd0\xb5\xd0\xbd\xd0\xb8\xd0\xb5 \xd0\xb2\xd0\xbb\xd0\xb0\xd0\xb4\xd0\xb5\xd0\xbb\xd1\x8c\xd1\x86\xd0\xb0

**\xd0\x92\xd0\xb0\xd1\x80\xd0\xb8\xd0\xb0\xd0\xbd\xd1\x82 1**
"""

NO_TRACE_CARD = b"""---
type: inbox
status: new
---

# \xd0\x91\xd0\xb5\xd0\xb7 \xd0\xbe\xd1\x82\xd0\xb2\xd0\xb5\xd1\x82\xd0\xb0
"""


class _Env:
    """Дерево на диске + управляемый origin. Ничего живого не трогает."""

    def __init__(self, tmp: str, cards: dict, remote: dict):
        self.root = tmp
        self.tracker = os.path.join(tmp, TRACKER)
        os.makedirs(self.tracker, exist_ok=True)
        os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
        for name, blob in cards.items():
            with open(os.path.join(self.tracker, name), "wb") as f:
                f.write(blob)
        self.remote = remote            # repo_path -> bytes | None (нет на origin)
        self.pushed: list = []          # что реально ушло бы наружу
        self.messages: list = []

    def reader(self, root, repo_path):
        if repo_path not in self.remote:
            return oad.REMOTE_ABSENT, None, "на origin файла нет"
        blob = self.remote[repo_path]
        if blob is None:
            return oad.REMOTE_UNMEASURED, None, "сеть недоступна"
        return oad.REMOTE_PRESENT, blob, ""

    def pusher(self, root, items, message):
        self.pushed.extend(items)
        self.messages.append(message)
        return True, "abcdef1234"

    def failing_pusher(self, root, items, message):
        return False, "HTTPError: 422"

    def pushed_by(self, card):
        for item in self.pushed:
            if item["card"] == card:
                return item["content"]
        return None


class OwnerAnswerDeliveryTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def env(self, cards=None, remote=None):
        name = "owner-decision-morfo.md"
        cards = cards if cards is not None else {name: LOCAL_CARD}
        remote = remote if remote is not None else {f"{TRACKER}/{name}": ORIGIN_CARD}
        return _Env(self.tmp, cards, remote)

    # ── ГЛАВНЫЙ положительный контроль ────────────────────────────────────────

    def test_answer_recorded_only_in_tree_reaches_origin(self):
        """Авария 08.08 дословно: ответ есть в дереве, на origin его нет ни минуты.

        Критерий приёмки карточки: дерево «потеряно» — ответ на origin ЕСТЬ.
        """
        e = self.env()
        r = oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher,
                    write_status=False)
        self.assertEqual(r["status"], oad.DELIVERED, r["reason"])
        self.assertEqual(r["delivered"], ["owner-decision-morfo.md"])
        sent = e.pushed_by("owner-decision-morfo.md")
        self.assertIsNotNone(sent, "наружу не ушло НИЧЕГО — след остался вне git")
        fields = oad.trace_fields(sent)
        self.assertEqual(fields["owner_choice"], "1")
        self.assertEqual(fields["owner_answered_at"], "2026-08-08T21:11:37.367367+00:00")
        self.assertEqual(fields["owner_answer_via"], "telegram")
        self.assertEqual(fields["owner_answered_by"], "258651137")

    def test_body_of_origin_is_never_touched(self):
        """Тело на origin БОГАЧЕ нашего — доставка обязана его не задеть.

        Именно поэтому карточку нельзя просто отдать `card_delivery.deliver`:
        пуш нашей копии стёр бы разбор инжестирующей сессии.
        """
        e = self.env()
        oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher, write_status=False)
        sent = e.pushed_by("owner-decision-morfo.md")
        self.assertEqual(oad.card_parts(sent)[1], oad.card_parts(ORIGIN_CARD)[1])
        self.assertIn(b"OTVET VLADELTSA", sent)

    def test_status_line_of_origin_is_never_touched(self):
        """`status:` не переносится: наша копия бывает СТАРШЕ origin.

        И отдельно — инвариант #14: агент не пишет `owner-done` даже формально.
        """
        e = self.env()
        oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher, write_status=False)
        sent = e.pushed_by("owner-decision-morfo.md")
        self.assertIn(b"\nstatus: ingested\n", sent)
        self.assertNotIn(b"status: owner-done", sent)

    def test_local_card_on_disk_is_not_modified(self):
        """Сторож ТОЛЬКО читает дерево: писателем ответа остаётся бот."""
        e = self.env()
        before = open(os.path.join(e.tracker, "owner-decision-morfo.md"), "rb").read()
        oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher, write_status=False)
        after = open(os.path.join(e.tracker, "owner-decision-morfo.md"), "rb").read()
        self.assertEqual(before, after)

    # ── границы: где сторож обязан ОТКАЗАТЬ ──────────────────────────────────

    def test_conflicting_answer_on_origin_refuses(self):
        """На origin ДРУГОЙ выбор владельца — выбирать сторону молча запрещено."""
        other = ORIGIN_CARD.replace(b"priority: high\n",
                                    b"priority: high\nowner_choice: 2\n")
        e = self.env(remote={f"{TRACKER}/owner-decision-morfo.md": other})
        r = oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher,
                    write_status=False)
        self.assertIn(r["status"], oad.NOT_DELIVERED)
        self.assertEqual(len(r["conflicts"]), 1)
        self.assertIn("ДРУГОЙ ответ владельца", r["conflicts"][0]["reason"])
        self.assertEqual(e.pushed, [], "при конфликте наружу не должно уйти ничего")

    def test_unmeasured_origin_is_not_green(self):
        """Прочитать origin не удалось — это НЕ «след на месте»."""
        e = self.env(remote={f"{TRACKER}/owner-decision-morfo.md": None})
        r = oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher,
                    write_status=False)
        self.assertIn(r["status"], oad.NOT_DELIVERED)
        self.assertEqual([u["card"] for u in r["unmeasured"]], ["owner-decision-morfo.md"])
        self.assertEqual(e.pushed, [])

    def test_failed_push_is_named_not_swallowed(self):
        e = self.env()
        r = oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.failing_pusher,
                    write_status=False)
        self.assertEqual(r["status"], oad.FAILED)
        self.assertIn("422", r["reason"])
        self.assertEqual(r["delivered"], [])

    def test_disabled_by_env_still_counts_pending(self):
        """Выключено владельцем ≠ доставлено: недоставленное остаётся названным."""
        e = self.env()
        r = oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher,
                    env={oad.ENV_FLAG: "0"}, write_status=False)
        self.assertEqual(r["status"], oad.DISABLED)
        self.assertEqual(len(r["pending"]), 1)
        self.assertEqual(e.pushed, [])

    # ── штатные состояния ────────────────────────────────────────────────────

    def test_trace_already_on_origin_is_idle(self):
        e = self.env(remote={f"{TRACKER}/owner-decision-morfo.md": LOCAL_CARD})
        r = oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher,
                    write_status=False)
        self.assertEqual(r["status"], oad.IDLE, r["reason"])
        self.assertEqual(r["already_on_origin"], ["owner-decision-morfo.md"])
        self.assertEqual(e.pushed, [])

    def test_card_absent_on_origin_is_delivered_whole(self):
        """Карточки на origin нет вовсе — терять нечего, везём как создание."""
        e = self.env(remote={})
        r = oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher,
                    write_status=False)
        self.assertEqual(r["status"], oad.DELIVERED, r["reason"])
        self.assertEqual(e.pushed_by("owner-decision-morfo.md"), LOCAL_CARD)

    def test_cards_without_answer_are_ignored(self):
        e = self.env(cards={"inbox-plain.md": NO_TRACE_CARD}, remote={})
        r = oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher,
                    write_status=False)
        self.assertEqual(r["scanned"], 0)
        self.assertEqual(r["status"], oad.IDLE)
        self.assertEqual(e.pushed, [])

    def test_board_is_never_delivered(self):
        """`_BOARD.md` — общая память, её не везёт никто и никогда."""
        board = LOCAL_CARD.replace(b"title:", b"title:")
        e = self.env(cards={"_BOARD.md": board}, remote={})
        r = oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher,
                    write_status=False)
        self.assertEqual(r["scanned"], 0)
        self.assertEqual(e.pushed, [])

    def test_time_is_an_input(self):
        e = self.env()
        r = oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher,
                    write_status=False)
        self.assertEqual(r["generated_at"], NOW.isoformat())

    def test_receipt_is_written_atomically(self):
        e = self.env()
        oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher, write_status=True)
        with open(os.path.join(e.root, oad.STATUS_REL), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["status"], oad.DELIVERED)
        self.assertEqual(saved["delivered"], ["owner-decision-morfo.md"])


class VerifyTraceOnlyTest(unittest.TestCase):
    """Независимое доказательство переноса. Конструктор себе не судья."""

    def test_accepts_added_trace_only(self):
        merged, why, added = oad.merge_trace(LOCAL_CARD, ORIGIN_CARD)
        self.assertIsNotNone(merged, why)
        self.assertEqual(sorted(added), sorted(["owner_choice", "owner_answered_at",
                                                "owner_answer_via", "owner_answered_by"]))
        ok, why2 = oad.verify_trace_only(ORIGIN_CARD, merged)
        self.assertTrue(ok, why2)

    def test_rejects_changed_body(self):
        merged, _why, _a = oad.merge_trace(LOCAL_CARD, ORIGIN_CARD)
        tampered = merged.replace(b"OTVET VLADELTSA", b"PODMENA")
        ok, why = oad.verify_trace_only(ORIGIN_CARD, tampered)
        self.assertFalse(ok)
        self.assertIn("тело", why)

    def test_rejects_changed_frontmatter_line(self):
        merged, _why, _a = oad.merge_trace(LOCAL_CARD, ORIGIN_CARD)
        tampered = merged.replace(b"status: ingested", b"status: owner-done")
        ok, why = oad.verify_trace_only(ORIGIN_CARD, tampered)
        self.assertFalse(ok)
        self.assertIn("изменены или пропали", why)

    def test_rejects_dropped_frontmatter_line(self):
        merged, _why, _a = oad.merge_trace(LOCAL_CARD, ORIGIN_CARD)
        tampered = merged.replace(b"priority: high\n", b"")
        ok, why = oad.verify_trace_only(ORIGIN_CARD, tampered)
        self.assertFalse(ok)

    def test_rejects_foreign_added_key(self):
        merged, _why, _a = oad.merge_trace(LOCAL_CARD, ORIGIN_CARD)
        tampered = merged.replace(b"owner_choice: 1\n",
                                  b"owner_choice: 1\nclaimed_by: agent\n")
        ok, why = oad.verify_trace_only(ORIGIN_CARD, tampered)
        self.assertFalse(ok)
        self.assertIn("не из следа", why)

    def test_rejects_identical_candidate(self):
        ok, why = oad.verify_trace_only(ORIGIN_CARD, ORIGIN_CARD)
        self.assertFalse(ok)
        self.assertIn("ничем не отличается", why)

    def test_merge_refuses_when_local_has_no_trace(self):
        merged, why, _a = oad.merge_trace(NO_TRACE_CARD, ORIGIN_CARD)
        self.assertIsNone(merged)
        self.assertIn("нет следа", why)

    def test_merge_refuses_non_card(self):
        merged, why, _a = oad.merge_trace(LOCAL_CARD, b"not a card at all")
        self.assertIsNone(merged)
        self.assertIn("не карточка", why)


class OwnerGateTest(unittest.TestCase):
    """Отправитель не умеет отправить `landing/**` — проверка ДО, а не после."""

    def test_pusher_refuses_path_outside_tracker(self):
        ok, why = oad._default_pusher(
            "/nonexistent-root",
            [{"repo_path": "landing/src/pages/index.astro", "content": b"x",
              "card": "index.astro"}],
            "msg")
        self.assertFalse(ok)
        # Отказ обязан быть ИМЕННО по пути. Корня нет вовсе — значит проверка
        # прошла РАНЬШЕ загрузки пушера, а не была погашена его отсутствием.
        self.assertIn("вне трекера", why)

    def test_pusher_gate_precedes_tool_lookup(self):
        """Годный путь при отсутствующем пушере даёт ДРУГОЙ отказ — гейт не эхо."""
        ok, why = oad._default_pusher(
            "/nonexistent-root",
            [{"repo_path": f"{TRACKER}/own-x.md", "content": b"x", "card": "own-x.md"}],
            "msg")
        self.assertFalse(ok)
        self.assertIn("инструмента доставки нет", why)


class BridgeWiringTest(unittest.TestCase):
    """Проводка, а не деталь: удалённый вызов оставил бы всё зелёным (урок #144)."""

    def test_bridge_report_carries_owner_answer_block(self):
        from spa_core.monitoring import findings_bridge as fb
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
            os.makedirs(os.path.join(tmp, TRACKER), exist_ok=True)
            called: list = []

            def fake_answers(root, now):
                called.append(root)
                return {"status": oad.IDLE, "delivered": [], "already_on_origin": [],
                        "pending": [], "reason": "тест"}

            report = fb.run_bridge(root=tmp, now=NOW,
                                   create=lambda *a, **k: None,
                                   close=lambda *a, **k: None,
                                   notify=lambda *a, **k: True,
                                   deliver=lambda *a, **k: {"status": "IDLE"},
                                   retract=lambda *a, **k: True,
                                   deliver_answers=fake_answers)
            self.assertIn("owner_answer_delivery", report,
                          "мост не позвал сторожа — след владельца снова вне git")
            self.assertEqual(called, [tmp])
            self.assertEqual(report["owner_answer_delivery"]["status"], oad.IDLE)

    def test_bridge_survives_guard_explosion_but_names_it(self):
        from spa_core.monitoring import findings_bridge as fb

        def boom(root, now):
            raise RuntimeError("сеть легла")

        block = fb._deliver_owner_answers("/tmp", NOW, boom)
        self.assertEqual(block["status"], "UNCHECKED")
        self.assertIn("сеть легла", block["reason"])


class OfficeStepReaderTest(unittest.TestCase):
    """У находки обязан быть ЧИТАТЕЛЬ. Артефакт без обязательного читателя — это
    ровно тот дефект, ради которого заведён шаг 0-офис (аудит 05.08): 12 аналитиков
    месяцами писали отчёты, которые никто не был обязан открыть.
    """

    @staticmethod
    def _consume():
        import importlib.util
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[2]
        path = root / "scripts" / "consume_office_reports.py"
        spec = importlib.util.spec_from_file_location("_cor_for_test", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @staticmethod
    def _report(block):
        rep = {"generated_at": NOW.isoformat(), "created": [], "closed": [], "deferred": [],
               "waiting_hysteresis": [], "escalated": [], "sources_unread": [],
               "open_cards": 0, "delivery": {"status": "IDLE", "delivered": [],
                                             "debt": {"count": 0}}}
        if block is not None:
            rep["owner_answer_delivery"] = block
        return rep

    def _lines(self, block):
        m = self._consume()
        return m._summarize_json("data/findings_bridge_report.json", self._report(block),
                                 now=NOW)

    def test_missing_block_is_printed_as_unmeasured_not_silence(self):
        text = "\n".join(self._lines(None))
        self.assertIn("НЕ ИЗМЕРЕН", text)
        self.assertIn("owner_answer_delivery", text)

    def test_delivered_is_printed(self):
        text = "\n".join(self._lines({"status": "DELIVERED", "delivered": ["a.md", "b.md"],
                                      "commit": "abc12345", "already_on_origin": [],
                                      "pending": [], "conflicts": [], "unmeasured": []}))
        self.assertIn("abc12345", text)

    def test_conflict_is_printed_loudly(self):
        text = "\n".join(self._lines({"status": "REFUSED", "reason": "r",
                                      "pending": [{"card": "q"}], "already_on_origin": [],
                                      "conflicts": [{"card": "own-x.md", "reason": "два ответа"}],
                                      "unmeasured": []}))
        self.assertIn("ДВА РАЗНЫХ ОТВЕТА ВЛАДЕЛЬЦА", text)
        self.assertIn("own-x.md", text)

    def test_unmeasured_is_printed(self):
        text = "\n".join(self._lines({"status": "REFUSED", "reason": "r", "pending": [],
                                      "already_on_origin": [], "conflicts": [],
                                      "unmeasured": [{"card": "own-y.md", "reason": "сеть"}]}))
        self.assertIn("own-y.md", text)


class RenderTest(unittest.TestCase):
    def test_missing_receipt_is_not_silence(self):
        self.assertIn("НЕ ИЗМЕРЕНО", oad.render({}))

    def test_delivered_render_names_count(self):
        line = oad.render({"status": oad.DELIVERED, "delivered": ["a.md", "b.md"]})
        self.assertIn("2", line)

    def test_refused_render_shows_reason(self):
        line = oad.render({"status": oad.REFUSED, "reason": "ДРУГОЙ ответ",
                           "pending": [{"card": "x"}], "conflicts": [{"card": "x"}]})
        self.assertIn("REFUSED", line)
        self.assertIn("РАЗНЫЕ ОТВЕТЫ", line)


if __name__ == "__main__":
    unittest.main()
