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


# ── авария цикла #419: расхождение, которое УЖЕ разобрано ────────────────────
# Форма снята с живой карточки `own-pererazdavat-li-srezannoe-zaschitami`:
# телеграм-ответ владельца вытеснен более поздним ответом интерактивной сессии
# (ADR-160), и origin называет вытесненное ТРЕМЯ полями, поле в поле с нашим.
# Значения здесь — из фикстуры аварии 08.08 выше, а не «сегодня».
_SUPERSEDE_REGISTER = (b"owner_choice_superseded: 1\n"
                       b"owner_choice_superseded_at: 2026-08-08T21:11:37.367367+00:00\n"
                       b"owner_choice_superseded_via: telegram\n")

_LATER_ANSWER = (b"owner_choice: 2\n"
                 b"owner_answered_at: 2026-08-09T10:00:00+00:00\n"
                 b"owner_answer_via: interactive-session\n")


def _origin_with(extra: bytes) -> bytes:
    """ORIGIN_CARD плюс строки frontmatter — форма origin в этой аварии."""
    return ORIGIN_CARD.replace(b"priority: high\n", b"priority: high\n" + extra)


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

    # ── третий исход: расходились, и владелец УЖЕ решил (цикл #419) ──────────

    def test_superseded_answer_is_not_a_conflict(self):
        """origin называет НАШ ответ вытесненным — звать человека не на что.

        Положительный контроль настоящей аварии 29.08: шаг 0-офис каждый цикл
        печатал «⛔ ДВА РАЗНЫХ ОТВЕТА ВЛАДЕЛЬЦА, нужен человек» по карточке, где
        владелец ответил вариантом 3 (ADR-160), а вытесненный вариант 2 записан
        на origin поимённо. До правки этот тест краснеет: вердикт `conflict`.
        """
        origin = _origin_with(_LATER_ANSWER + _SUPERSEDE_REGISTER)
        e = self.env(remote={f"{TRACKER}/owner-decision-morfo.md": origin})
        r = oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher,
                    write_status=False)
        self.assertEqual(r["conflicts"], [], "разобранное расхождение — не конфликт")
        self.assertEqual(len(r["superseded"]), 1)
        self.assertEqual(r["status"], oad.IDLE, "везти нечего и никто не блокирует")
        self.assertIn("ВЫТЕСНЕН", r["superseded"][0]["reason"])
        self.assertEqual(e.pushed, [],
                         "вытесненный ответ наружу не везётся: он вытесненный")

    def test_partial_supersede_is_still_a_conflict(self):
        """Покрыто ЧАСТИЧНО — это спор, а не разобранный спор (fail-CLOSED)."""
        origin = _origin_with(_LATER_ANSWER + b"owner_choice_superseded: 1\n")
        e = self.env(remote={f"{TRACKER}/owner-decision-morfo.md": origin})
        r = oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher,
                    write_status=False)
        self.assertEqual(r["superseded"], [])
        self.assertEqual(len(r["conflicts"]), 1)
        reason = r["conflicts"][0]["reason"]
        self.assertIn("ДРУГОЙ ответ владельца", reason)
        self.assertIn("owner_choice_superseded_at", reason,
                      "непокрытое поле обязано быть названо поимённо")
        self.assertEqual(e.pushed, [])

    def test_supersede_naming_another_value_is_still_a_conflict(self):
        """Регистр называет НЕ наш ответ — вытеснили что-то другое, спор жив."""
        register = _SUPERSEDE_REGISTER.replace(b"owner_choice_superseded: 1\n",
                                               b"owner_choice_superseded: 9\n")
        origin = _origin_with(_LATER_ANSWER + register)
        e = self.env(remote={f"{TRACKER}/owner-decision-morfo.md": origin})
        r = oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher,
                    write_status=False)
        self.assertEqual(r["superseded"], [])
        self.assertEqual(len(r["conflicts"]), 1)
        self.assertIn("origin вытеснил", r["conflicts"][0]["reason"])

    def test_supersede_does_not_silence_an_untouched_field(self):
        """Регистр покрывает выбор, но НЕ канал — молчать по каналу нельзя."""
        origin = _origin_with(_LATER_ANSWER
                              + b"owner_choice_superseded: 1\n"
                              + b"owner_choice_superseded_at: 2026-08-08T21:11:37.367367+00:00\n")
        e = self.env(remote={f"{TRACKER}/owner-decision-morfo.md": origin})
        r = oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher,
                    write_status=False)
        self.assertEqual(len(r["conflicts"]), 1)
        self.assertIn("owner_choice_superseded_via", r["conflicts"][0]["reason"])

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


# ── авария цикла #427: НЕОТВЕЧЕННАЯ карточка читалась как несущая ответ ───────
# Форма снята с прод-дерева 29.08 дословно. Штатная карточка владельца рождается
# со строкой `owner_choice: ""` и носит её, пока владелец не ответил. Сторож
# читает БАЙТЫ frontmatter, и двухсимвольный токен `""` попадал в след как
# ЗНАЧЕНИЕ — то есть неотвеченная карточка предъявлялась как несущая ответ.
UNANSWERED_CARD = b"""---
trackerStatus:
  type: owner-decision
title: "\xd0\xa2\xd0\xb8\xd1\x80"
status: needs-owner
priority: high
owner: yuriycooleshov@gmail.com
owner_choice: ""
blocks: ""
created: 2026-08-29
---

## \xd0\xa7\xd1\x82\xd0\xbe \xd1\x81\xd0\xbb\xd1\x83\xd1\x87\xd0\xb8\xd0\xbb\xd0\xbe\xd1\x81\xd1\x8c

\xd0\x92\xd0\xbe\xd0\xbf\xd1\x80\xd0\xbe\xd1\x81 \xd0\xb2\xd0\xbb\xd0\xb0\xd0\xb4\xd0\xb5\xd0\xbb\xd1\x8c\xd1\x86\xd1\x83, \xd0\xbe\xd1\x82\xd0\xb2\xd0\xb5\xd1\x82\xd0\xb0 \xd0\xb5\xd1\x89\xd1\x91 \xd0\xbd\xd0\xb5\xd1\x82.
"""

# Та же карточка на origin: владелец ОТВЕТИЛ, сессия разобрала, статус терминальный.
ANSWERED_ON_ORIGIN = UNANSWERED_CARD.replace(
    b'status: needs-owner\n', b'status: ingested\n').replace(
    b'owner_choice: ""\n', b'owner_choice: "2"\n')


class UnansweredCardIsNotAnAnswerTest(unittest.TestCase):
    """Пустой YAML-скаляр — ОТСУТСТВИЕ значения, а не значение.

    Каждый тест — положительный контроль замера 29.08 (цикл #427) на живом
    прод-дереве: из 68 карточек, которые сторож считал несущими ответ владельца,
    у 10 ответа не было вовсе.
    """

    CARD = "owner-decision-tier-steakhouse-2026-08-29.md"

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_owner_choice_is_not_a_trace(self):
        """`owner_choice: ""` — это «ответа ещё нет», а не ответ со значением `""`."""
        self.assertEqual(oad.trace_fields(UNANSWERED_CARD), {},
                         "неотвеченная карточка предъявлена как несущая след ответа")

    def test_real_answer_is_still_a_trace(self):
        """Обратный контроль: починка не должна ослепить сторожа на настоящем ответе."""
        self.assertEqual(oad.trace_fields(ANSWERED_ON_ORIGIN).get("owner_choice"), '"2"')

    def test_unanswered_local_vs_answered_origin_is_not_a_conflict(self):
        """Замер 29.08 дословно: три карточки звали человека там, где спора нет.

        Наша копия просто не отвечена, origin отвечен и `ingested`. Шаг 0-офис
        печатал «⛔ ДВА РАЗНЫХ ОТВЕТА ВЛАДЕЛЬЦА, нужен человек» КАЖДЫЙ цикл.
        """
        merged, reason, _ = oad.merge_trace(UNANSWERED_CARD, ANSWERED_ON_ORIGIN)
        self.assertIsNone(merged, "везти с неотвеченной карточки нечего")
        self.assertNotIn("ДРУГОЙ ответ владельца", reason)
        self.assertIn("нет следа ответа владельца", reason)

    def test_unanswered_card_is_skipped_by_scan_entirely(self):
        """Она не попадает НИ в один вердикт: следа нет — карточка не наша."""
        e = _Env(self.tmp, {self.CARD: UNANSWERED_CARD},
                 {f"{TRACKER}/{self.CARD}": ANSWERED_ON_ORIGIN})
        self.assertEqual([i for i in oad.scan(e.root, reader=e.reader)
                          if i.get("card") == self.CARD], [])

    def test_unanswered_card_absent_on_origin_is_never_delivered(self):
        """Тихая половина аварии: доставка ответа, которого владелец не давал.

        Карточки на origin нет ⇒ вердикт был `absent_on_origin`, и она уехала бы
        туда под коммитом «след решения владельца → origin».
        """
        e = _Env(self.tmp, {self.CARD: UNANSWERED_CARD}, {})
        oad.run(root=e.root, now=NOW, reader=e.reader, pusher=e.pusher,
                write_status=False)
        self.assertEqual(e.pushed, [], "неотвеченная карточка уехала на origin как ответ")

    def test_genuine_two_answers_still_call_for_a_human(self):
        """Обратный контроль сторожа: настоящий спор двух ответов остаётся CONFLICT."""
        ours = UNANSWERED_CARD.replace(b'owner_choice: ""\n', b'owner_choice: "1"\n')
        _, reason, _ = oad.merge_trace(ours, ANSWERED_ON_ORIGIN)
        self.assertIn("ДРУГОЙ ответ владельца", reason)

    def test_empty_supersede_register_covers_nothing(self):
        """Пустой регистр вытеснения не «покрывает» расхождение, а молчит о нём."""
        remote = ANSWERED_ON_ORIGIN.replace(
            b'blocks: ""\n', b'blocks: ""\nowner_choice_superseded: ""\n')
        ok, why = oad.clash_superseded({"owner_choice": ('"2"', '"1"')}, remote)
        self.assertFalse(ok)
        self.assertIn("owner_choice_superseded", why)


# ── авария цикла #428: `1` и `"1"` объявлялись ДВУМЯ РАЗНЫМИ ответами ────────
# Замер 30.08 на живом прод-дереве против origin `a04fd645e`: расхождений шесть,
# из них ДВА состоят РОВНО из кавычек, ещё у двух кавычки дают одно расхождение
# из трёх. Настоящий спор — ОДИН. Формы ниже сняты с тех самых карточек.

#: `owner-decision-AI1-approach-2026-08-29`: на origin `"1"`, у нас `1`. Ответ
#: владельца ОДИН и тот же (вариант 1), спора нет ни в каком виде.
QUOTED_ONE_ON_ORIGIN = UNANSWERED_CARD.replace(
    b'status: needs-owner\n', b'status: ingested\n').replace(
    b'owner_choice: ""\n', b'owner_choice: "1"\n')

#: Наша копия той же карточки: кнопка бота пишет скаляр БЕЗ кавычек.
BARE_ONE_LOCAL = UNANSWERED_CARD.replace(
    b'status: needs-owner\n', b'status: owner-done\n').replace(
    b'owner_choice: ""\n',
    b"owner_choice: 1\n"
    b"owner_answered_at: 2026-08-29T21:00:14.472042+00:00\n"
    b"owner_answer_via: telegram\n")


class QuotingIsNotADisagreementTest(unittest.TestCase):
    """Кавычки вокруг скаляра — способ записи, а не другой ответ владельца.

    Каждый тест — положительный контроль замера 30.08 (цикл #428): шаг 0-офис
    печатал `⛔ ДВА РАЗНЫХ ОТВЕТА ВЛАДЕЛЬЦА, нужен человек` по карточкам, где обе
    копии несут ОДИН вариант. Обратные контроли (склейка) стоят рядом: сторож
    обязан остаться громким там, где ответы действительно разные.
    """

    def test_quoted_and_bare_one_is_not_a_conflict(self):
        """`owner-decision-AI1-approach` дословно: `"1"` против `1`.

        До правки: вердикт `conflict` и призыв человека каждый цикл.
        """
        _, reason, _ = oad.merge_trace(BARE_ONE_LOCAL, QUOTED_ONE_ON_ORIGIN)
        self.assertNotIn("ДРУГОЙ ответ владельца", reason)

    def test_matching_variant_unblocks_the_missing_provenance(self):
        """Спор снят — и наружу уезжает ровно то, чего на origin не было.

        Замер живой карточки: у нас, кроме варианта, есть отметка времени и канал,
        а на origin их нет. Пока вариант читался спорным, они не ехали НИКОГДА —
        ложный ⛔ держал доставку. Проверяем не только молчание сторожа, но и то,
        что после него доставка делает свою работу и не трогает чужого.
        """
        merged, reason, added = oad.merge_trace(BARE_ONE_LOCAL, QUOTED_ONE_ON_ORIGIN)
        self.assertEqual(reason, "")
        self.assertEqual(sorted(added), ["owner_answer_via", "owner_answered_at"])
        self.assertNotIn("owner_choice", added,
                         "совпавший вариант переписывать нечем и незачем")
        self.assertIn(b'owner_choice: "1"\n', merged,
                      "написание origin остаётся origin'ным — своё мы не навязываем")

    def test_trace_fully_on_origin_in_quotes_is_already_delivered(self):
        """Наш след целиком на origin, отличается только написанием — везти нечего."""
        ours = UNANSWERED_CARD.replace(b'owner_choice: ""\n', b"owner_choice: 1\n")
        merged, reason, added = oad.merge_trace(ours, QUOTED_ONE_ON_ORIGIN)
        self.assertIsNone(merged)
        self.assertEqual(added, {})
        self.assertIn("уже на origin", reason)

    def test_quoted_conflict_disappears_from_scan_verdicts(self):
        """Сквозь `scan`, а не только через `merge_trace`: вердикт больше не `conflict`."""
        card = "owner-decision-AI1-approach-2026-08-29.md"
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            e = _Env(tmp, {card: BARE_ONE_LOCAL},
                     {f"{TRACKER}/{card}": QUOTED_ONE_ON_ORIGIN})
            verdicts = [i["verdict"] for i in oad.scan(e.root, reader=e.reader)
                        if i.get("card") == card]
            self.assertEqual(verdicts, [oad.NEEDS_TRACE],
                             "кавычки сняты с вердикта, а не сам вердикт")

    def test_single_quotes_are_the_same_scalar_too(self):
        """YAML знает два написания кавычек — сторож обязан знать оба."""
        origin = QUOTED_ONE_ON_ORIGIN.replace(b'owner_choice: "1"\n',
                                              b"owner_choice: '1'\n")
        _, reason, _ = oad.merge_trace(BARE_ONE_LOCAL, origin)
        self.assertNotIn("ДРУГОЙ ответ владельца", reason)

    def test_quoted_supersede_register_still_covers_the_clash(self):
        """Регистр вытеснения нормализуется ТЕМ ЖЕ сравнением, иначе — новый класс ⛔.

        Если бы кавычки снимались только в `merge_trace`, вытеснение, объявленное
        на origin в кавычках, перестало бы покрывать наше расхождение — сторож
        сменил бы один ложный призыв человека на другой.
        """
        ok, why = oad.clash_superseded(
            {"owner_choice": ('"2"', "1")},
            ANSWERED_ON_ORIGIN.replace(b'blocks: ""\n',
                                       b'blocks: ""\nowner_choice_superseded: "1"\n'))
        self.assertTrue(ok, why)

    # ── обратные контроли: склеить два РАЗНЫХ ответа правка не смеет ─────────

    def test_different_variants_in_quotes_still_call_for_a_human(self):
        """`owner-decision-partiya-2-karantina` дословно: на origin `"4"`, у нас `1`.

        Единственный НАСТОЯЩИЙ спор из шести. Он обязан пережить эту правку — ради
        него она и сделана: до неё он лежал в одном ряду с четырьмя ложными.
        """
        origin = QUOTED_ONE_ON_ORIGIN.replace(b'owner_choice: "1"\n',
                                              b'owner_choice: "4"\n')
        _, reason, _ = oad.merge_trace(BARE_ONE_LOCAL, origin)
        self.assertIn("ДРУГОЙ ответ владельца", reason)
        self.assertIn('"4"', reason, "спорное значение обязано быть названо дословно")

    def test_inner_whitespace_is_not_stripped(self):
        """`"1 "` против `1` — РАЗНЫЕ скаляры: снимается пара кавычек, не содержимое."""
        origin = QUOTED_ONE_ON_ORIGIN.replace(b'owner_choice: "1"\n',
                                              b'owner_choice: "1 "\n')
        _, reason, _ = oad.merge_trace(BARE_ONE_LOCAL, origin)
        self.assertIn("ДРУГОЙ ответ владельца", reason)

    def test_channel_divergence_is_provenance_not_a_disagreement(self):
        """`aave-na-arbitrum`/`tret-flota`: вариант один, а канал и отметка разные.

        **НАМЕРЕННОЕ изменение утверждения (инвариант #16), ADR-175.** Этот тест
        написан циклом #428 как ГРАНИЦА его правки: «правка про кавычки, и только
        про них; разбор „провенанс ответа ≠ ответ“ — другой корень». Тот корень
        разобран циклом #429, и предмет теста сдвинут решением, а не подгонкой под
        зелёный. Замер 30.08 на живом дереве: из ЧЕТЫРЁХ «⛔ нужен человек» два
        были спором о решении (origin «4» против «1»; «2» против «1»), а два —
        вот этой формой: один и тот же вариант, разные канал и отметка. Звать
        человека выбирать сторону там, где сторона одна, — шум, в котором тонет
        настоящий спор (тот же счёт, что у кавычек в #428).

        Что тест продолжает держать, слово в слово и БОЛЬШЕ прежнего:
        расхождение не замолчано (причина есть и называет разошедшиеся поля),
        совпавший `owner_choice` в ней не назван, и — новое — по такой карточке
        НИЧЕГО не везётся: наша отметка затёрла бы origin'ную.
        """
        origin = QUOTED_ONE_ON_ORIGIN.replace(
            b'owner_choice: "1"\n',
            b'owner_choice: "1"\n'
            b'owner_answered_at: "2026-08-29T20:30:00Z"\n'
            b'owner_answer_via: "interactive"\n')
        merged, reason, _ = oad.merge_trace(BARE_ONE_LOCAL, origin)

        self.assertIsNone(merged, "провенанс origin затёрт нашей отметкой")
        self.assertTrue(reason.startswith(oad.PROVENANCE_MARK), reason)
        self.assertNotIn("ДРУГОЙ ответ владельца", reason,
                         "вариант один — человека звать не на что")
        self.assertIn("owner_answer_via", reason,
                      "расхождение замолчано — невидимое хуже ложного")
        self.assertNotIn("owner_choice:", reason,
                         "вариант совпал — по нему спора нет и называть его нечего")

    def test_unparseable_quoting_is_refused_not_guessed(self):
        """Fail-CLOSED: чего функция не берётся разобрать, то остаётся неравным."""
        self.assertEqual(oad.unquote_scalar('"a\\nb"'), '"a\\nb"',
                         "экранирование помимо \\\\ и \\\" разбирать не беремся")
        self.assertEqual(oad.unquote_scalar('"a"b"'), '"a"b"',
                         "кавычка внутри двойных без экрана — это не один скаляр")
        self.assertEqual(oad.unquote_scalar('"недописанный'), '"недописанный')
        self.assertFalse(oad.same_scalar('"a\\nb"', "a\\nb"))

    def test_quoted_null_is_a_value_not_an_absence(self):
        """Порядок проверок: пустой скаляр судится по СЫРОМУ написанию.

        Нормализуй мы раньше, строка `"null"` (настоящее значение) стала бы
        неотличима от `null` (объявленное отсутствие ответа).
        """
        card = UNANSWERED_CARD.replace(b'owner_choice: ""\n',
                                       b'owner_choice: "null"\n')
        self.assertEqual(oad.trace_fields(card).get("owner_choice"), '"null"')
        bare = UNANSWERED_CARD.replace(b'owner_choice: ""\n', b"owner_choice: null\n")
        self.assertEqual(oad.trace_fields(bare), {})


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

    def test_superseded_is_printed_but_not_as_a_conflict(self):
        """Вытеснение видно — и НЕ зовёт человека (авария цикла #419)."""
        text = "\n".join(self._lines({"status": "IDLE", "reason": "r", "pending": [],
                                      "already_on_origin": [], "conflicts": [],
                                      "superseded": [{"card": "own-z.md",
                                                      "reason": "ВЫТЕСНЕН вариантом 3"}],
                                      "unmeasured": []}))
        self.assertIn("own-z.md", text)
        self.assertIn("ВЫТЕСНЕН", text)
        self.assertNotIn("ДВА РАЗНЫХ ОТВЕТА ВЛАДЕЛЬЦА", text)

    def test_unmeasured_is_printed(self):
        text = "\n".join(self._lines({"status": "REFUSED", "reason": "r", "pending": [],
                                      "already_on_origin": [], "conflicts": [],
                                      "unmeasured": [{"card": "own-y.md", "reason": "сеть"}]}))
        self.assertIn("own-y.md", text)

    def test_provenance_is_printed_but_never_as_a_disagreement(self):
        """Читатель провенанса — обязательный шаг цикла, и он не зовёт человека зря.

        Именно шаг 0-офис печатал «⛔ ДВА РАЗНЫХ ОТВЕТА ВЛАДЕЛЬЦА, нужен человек»
        по `aave-na-arbitrum` и `tret-flota` 30.08, где вариант был ОДИН (ADR-175).
        """
        text = "\n".join(self._lines(
            {"status": oad.IDLE, "already_on_origin": [], "delivered": [], "pending": [],
             "conflicts": [], "unmeasured": [], "superseded": [],
             "provenance": [{"card": "owner-decision-aave.md",
                             "reason": "тот же ВЫБОР владельца, разошёлся лишь провенанс"}],
             "reason": "тест"}))

        self.assertIn("owner-decision-aave.md", text)
        self.assertIn("человек не нужен", text)
        self.assertNotIn("ДВА РАЗНЫХ ОТВЕТА", text,
                         "провенанс напечатан как спор — ровно шум 30.08")


class RenderTest(unittest.TestCase):
    def test_missing_receipt_is_not_silence(self):
        self.assertIn("НЕ ИЗМЕРЕНО", oad.render({}))

    def test_delivered_render_names_count(self):
        line = oad.render({"status": oad.DELIVERED, "delivered": ["a.md", "b.md"]})
        self.assertIn("2", line)

    def test_superseded_render_names_count(self):
        line = oad.render({"status": oad.IDLE, "already_on_origin": [],
                           "superseded": [{"card": "x"}]})
        self.assertIn("ВЫТЕСНЕНО", line)

    def test_refused_render_shows_reason(self):
        line = oad.render({"status": oad.REFUSED, "reason": "ДРУГОЙ ответ",
                           "pending": [{"card": "x"}], "conflicts": [{"card": "x"}]})
        self.assertIn("REFUSED", line)
        self.assertIn("РАЗНЫЕ ОТВЕТЫ", line)


class TreeUnderJudgementTest(unittest.TestCase):
    """О КАКОМ дереве сторож выносит вердикт — и не подменяет ли он его своим.

    Авария 2026-08-30 (цикл #429), обе стороны замерены в одну минуту одним кодом:

        из /tmp/spa_c429 (git-worktree на origin/main):  IDLE — «весь след решений
                                                         владельца на origin (78 карточк(и))»
        тот же код, --root прод-дерева:                  UNCHECKED — недоставлено 4

    Четыре ответа владельца (AI1-approach · otkat-vetki-1249 · morpho-steakhouse ·
    urovni-dokazatelnosti) лежали ВНЕ git, а протокольная проверка показывала
    зелёное. Причина не в пути, а в ДЕФОЛТЕ: ``REPO_ROOT`` — каталог, где случайно
    лежит файл модуля. Worktree на ``origin/main`` сверялся сам с собой и совпасть
    мог только полностью, а зелёная строка читается как «ответы владельца в git».

    Работать из изолированного worktree ТРЕБУЕТ сам протокол (§3.4) — значит эту
    зелень видел именно тот, кто проверяет по правилам.
    """

    def setUp(self):
        import tempfile
        self._ours = tempfile.TemporaryDirectory()
        self._live = tempfile.TemporaryDirectory()
        self.ours, self.live = self._ours.name, self._live.name
        self._saved_env = os.environ.get("SPA_LIVE_ROOT")
        from spa_core.utils import live_paths
        self._lp = live_paths
        self._saved_default = live_paths.DEFAULT_LIVE_ROOT

    def tearDown(self):
        self._lp.DEFAULT_LIVE_ROOT = self._saved_default
        if self._saved_env is None:
            os.environ.pop("SPA_LIVE_ROOT", None)
        else:
            os.environ["SPA_LIVE_ROOT"] = self._saved_env
        self._ours.cleanup()
        self._live.cleanup()

    def _no_live_tree(self):
        from pathlib import Path
        os.environ.pop("SPA_LIVE_ROOT", None)
        self._lp.DEFAULT_LIVE_ROOT = Path(os.path.join(self.ours, "no-such-prod-tree"))

    # ── ГЛАВНЫЙ положительный контроль ────────────────────────────────────────

    def test_unnamed_root_judges_the_live_tree_not_our_own(self):
        """Авария 30.08 дословно: ответ лежит в ЖИВОМ дереве, а сверяют наше.

        Наше дерево пусто (worktree на origin/main — там сверять нечего), живое
        несёт карточку, чей след на origin отсутствует. ``root`` не назван.
        До починки сторож брал каталог собственного кода и отвечал IDLE.
        """
        name = "owner-decision-morfo.md"
        _Env(self.ours, {}, {})                                   # наше дерево: пусто
        env = _Env(self.live, {name: LOCAL_CARD},
                   {f"{TRACKER}/{name}": ORIGIN_CARD})            # живое: след не на origin
        os.environ["SPA_LIVE_ROOT"] = self.live

        r = oad.run(now=NOW, reader=env.reader, pusher=env.pusher, write_status=False)

        self.assertEqual([f["card"] for f in r["pending"]], [name],
                         "сторож не увидел недоставленный след ЖИВОГО дерева — "
                         "значит судил не то дерево (авария 30.08)")
        self.assertEqual(r["root"], self.live)
        self.assertEqual(r["root_source"], oad.ROOT_LIVE)
        self.assertNotEqual(r["status"], oad.IDLE)

    def test_no_live_tree_and_no_root_is_not_green(self):
        """Живого дерева не видно, никто его не назвал — «не измерено», не IDLE.

        Fail-CLOSED. «Везти нечего» на дереве собственного кода означает
        «сравнивать было нечего»: оно совпадает с origin ПО ПОСТРОЕНИЮ.
        """
        self._no_live_tree()
        env = _Env(self.ours, {}, {})

        r = oad.run(now=NOW, reader=env.reader, pusher=env.pusher, write_status=False)

        self.assertEqual(r["root_source"], oad.ROOT_OWN_TREE)
        self.assertEqual(r["status"], oad.UNCHECKED,
                         "пустой замер выдан за доставленный след — ровно форма аварии 30.08")
        self.assertIn("НЕ ИЗМЕРЕНО", r["reason"])
        # Отказ обязан стоять ДО перечисления и ДО пуша: иначе сторож повёз бы на
        # origin след из дерева, которое никто не выбирал.
        self.assertEqual(r["scanned"], 0)
        self.assertEqual(env.pushed, [], "отказ наступил ПОСЛЕ пуша — это не отказ")

    def test_named_tree_with_nothing_to_carry_is_still_idle(self):
        """Обратный контроль: настоящее «всё доставлено» не перекрашено в отказ.

        Без него починка могла бы «покраснеть всегда» и этим ничего не измерять.
        """
        name = "owner-decision-morfo.md"
        env = _Env(self.live, {name: LOCAL_CARD},
                   {f"{TRACKER}/{name}": LOCAL_CARD})   # след УЖЕ на origin
        os.environ["SPA_LIVE_ROOT"] = self.live

        r = oad.run(now=NOW, reader=env.reader, pusher=env.pusher, write_status=False)

        self.assertEqual(r["status"], oad.IDLE)
        self.assertEqual(r["root_source"], oad.ROOT_LIVE)

    def test_explicit_root_is_taken_verbatim(self):
        """Кто назвал дерево — тот его и выбрал; живое дерево его не перебивает.

        Контроль против ПЕРЕ-починки: мост (`findings_bridge`) зовёт сторожа с
        явным ``root``, и подмена этого корня живым деревом увела бы прод-прогон
        в другое дерево — новый дефект вместо старого.
        """
        os.environ["SPA_LIVE_ROOT"] = self.live
        _Env(self.live, {"owner-decision-morfo.md": LOCAL_CARD}, {})
        env = _Env(self.ours, {}, {})

        r = oad.run(root=self.ours, now=NOW, reader=env.reader,
                    pusher=env.pusher, write_status=False)

        self.assertEqual(r["root"], self.ours)
        self.assertEqual(r["root_source"], oad.ROOT_EXPLICIT)
        self.assertEqual(r["pending"], [])

    def test_scan_alone_also_resolves_the_tree(self):
        """``scan`` — публичная дверь, и у неё был ТОТ ЖЕ дефолт.

        Починка только в ``run`` оставила бы вторую дверь с прежним поведением
        (урок «одна снятая точка вызова оставила 1364 теста зелёными»).
        """
        name = "owner-decision-morfo.md"
        env = _Env(self.live, {name: LOCAL_CARD},
                   {f"{TRACKER}/{name}": ORIGIN_CARD})
        os.environ["SPA_LIVE_ROOT"] = self.live

        found = oad.scan(reader=env.reader)

        self.assertEqual([f["card"] for f in found], [name])

    def test_scan_refuses_an_unnamed_tree_instead_of_listing_its_own(self):
        """У ``scan`` тот же отказ, и он не перечисляет каталог своего кода.

        Без этого условие в ``scan`` было бы неокрашиваемым: ``run`` отказывает
        раньше и до ветки не доводит, а дверь-то публичная.
        """
        self._no_live_tree()
        env = _Env(self.ours, {}, {})

        found = oad.scan(reader=env.reader)

        self.assertEqual([f["verdict"] for f in found], [oad.UNMEASURED])
        self.assertIn("НЕ ИЗМЕРЕНО", found[0]["reason"])

    def test_judged_tree_is_named_in_receipt_and_line(self):
        """Провенанс виден снаружи: чьё дерево сверено — часть вердикта.

        Иначе «весь след на origin», сказанное о worktree, снова читается как
        «ответы владельца в git» — и отличить одно от другого нечем.
        """
        env = _Env(self.ours, {}, {})
        r = oad.run(root=self.ours, now=NOW, reader=env.reader,
                    pusher=env.pusher, write_status=False)

        line = oad.render(r)
        self.assertIn(self.ours, line)
        self.assertIn(oad.ROOT_EXPLICIT, line)

    def test_live_tree_is_not_announced_as_a_foreign_one(self):
        """И обратно: у живого дерева хвоста «дерево: …» нет — иначе шум в каждой строке."""
        name = "owner-decision-morfo.md"
        env = _Env(self.live, {name: LOCAL_CARD}, {f"{TRACKER}/{name}": LOCAL_CARD})
        os.environ["SPA_LIVE_ROOT"] = self.live

        line = oad.render(oad.run(now=NOW, reader=env.reader,
                                  pusher=env.pusher, write_status=False))

        self.assertNotIn("дерево:", line)

class ProvenanceIsNotADisagreementTest(unittest.TestCase):
    """«Как записан ответ» ≠ «какой ответ». ADR-175.

    Замер 30.08 (цикл #429), прод-дерево против `origin/main`: сторож поднял ЧЕТЫРЕ
    «⛔ ДВА РАЗНЫХ ОТВЕТА ВЛАДЕЛЬЦА, нужен человек».

      настоящий спор о решении (2): `partiya-2-karantina` origin «4» против нашей «1»
                                    `tier-steakhouse`     origin «2» против нашей «1»
      один и тот же выбор   (2): `aave-na-arbitrum`, `tret-flota` — вариант «1» с обеих
                                    сторон, разошлись канал (`interactive`/`telegram`) и
                                    отметка (пачечная 20:30:00Z против посекундной 21:01:5xZ)

    Ровно половина эскалаций была ни о чём — тот же счёт, что 30.08 у кавычек
    (ADR-173), и та же цена: настоящий спор тонет среди ложных. Граница узкая:
    расходится `owner_choice` ⇒ по-прежнему человек, сторону не выбирает никто.
    """

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _origin_with(choice: bytes) -> bytes:
        """Копия origin: свой канал, своя отметка и НАЗВАННЫЙ вариант."""
        return QUOTED_ONE_ON_ORIGIN.replace(
            b'owner_choice: "1"\n',
            b'owner_choice: ' + choice + b'\n'
            b'owner_answered_at: "2026-08-29T20:30:00Z"\n'
            b'owner_answer_via: "interactive"\n')

    # ── ГЛАВНЫЙ положительный контроль ────────────────────────────────────────

    def test_same_choice_other_channel_is_not_a_conflict(self):
        """`aave-na-arbitrum` дословно: вариант «1» с обеих сторон, канал разный."""
        env = _Env(self.tmp, {"owner-decision-aave.md": BARE_ONE_LOCAL},
                   {f"{TRACKER}/owner-decision-aave.md": self._origin_with(b'"1"')})

        found = oad.scan(root=self.tmp, reader=env.reader)

        self.assertEqual([f["verdict"] for f in found], [oad.PROVENANCE],
                         "один и тот же выбор владельца объявлен спором о решении")

    def test_different_choice_still_calls_a_human(self):
        """ОБРАТНЫЙ контроль: `partiya-2-karantina` — origin «4» против нашей «1».

        Без него починка могла бы «перестать звать человека» вообще и этим
        сломать единственное, чего сторожу нельзя, — выбор стороны молча.
        """
        env = _Env(self.tmp, {"owner-decision-partiya.md": BARE_ONE_LOCAL},
                   {f"{TRACKER}/owner-decision-partiya.md": self._origin_with(b'"4"')})

        found = oad.scan(root=self.tmp, reader=env.reader)

        self.assertEqual([f["verdict"] for f in found], [oad.CONFLICT])
        self.assertIn("ДРУГОЙ ответ владельца", found[0]["reason"])

    def test_live_shape_of_2026_08_30_splits_two_and_two(self):
        """Форма аварии целиком: четыре расхождения ⇒ два спора и два провенанса.

        Поштучные тесты выше не отвечают на вопрос, ради которого правка делалась:
        сколько ложных эскалаций уходит и сколько настоящих ОСТАЁТСЯ.
        """
        cards, remote = {}, {}
        for name, choice in (("aave", b'"1"'), ("tret-flota", b'"1"'),
                             ("partiya", b'"4"'), ("steakhouse", b'"2"')):
            fn = f"owner-decision-{name}.md"
            cards[fn] = BARE_ONE_LOCAL
            remote[f"{TRACKER}/{fn}"] = self._origin_with(choice)
        env = _Env(self.tmp, cards, remote)

        r = oad.run(root=self.tmp, now=NOW, reader=env.reader,
                    pusher=env.pusher, write_status=False)

        self.assertEqual(len(r["conflicts"]), 2, r["conflicts"])
        self.assertEqual(len(r["provenance"]), 2, r["provenance"])
        self.assertEqual(env.pushed, [], "по спорному/провенансному следу везти нечего")

    def test_provenance_does_not_block_the_verdict_but_is_named(self):
        """Как вытеснение: не держит статус в отказе, но и не исчезает.

        Невидимое расхождение ничем не отличалось бы от того, что сторож перестал
        смотреть на эти поля.
        """
        env = _Env(self.tmp, {"owner-decision-aave.md": BARE_ONE_LOCAL},
                   {f"{TRACKER}/owner-decision-aave.md": self._origin_with(b'"1"')})

        r = oad.run(root=self.tmp, now=NOW, reader=env.reader,
                    pusher=env.pusher, write_status=False)

        self.assertEqual(r["status"], oad.IDLE)
        self.assertEqual(r["conflicts"], [])
        self.assertEqual(len(r["provenance"]), 1)
        self.assertIn("провенанс", r["reason"])
        self.assertIn("ПРОВЕНАНС", oad.render(r))
        self.assertNotIn("РАЗНЫЕ ОТВЕТЫ", oad.render(r))


if __name__ == "__main__":
    unittest.main()
