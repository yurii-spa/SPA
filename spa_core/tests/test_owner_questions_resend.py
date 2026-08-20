#!/usr/bin/env python3
"""Пересылка открытых вопросов владельцу (решение 20.08, вариант 2) + честный их счёт.

Каждый тест — положительный контроль на аварию 2026-08-20, а не украшение:

* владельцу отказали в его ответе «Ответ 1» как «неоднозначно при **14** открытых» —
  одиннадцать из тех четырнадцати были УЖЕ ЗАКРЫТЫ (`ingested`), живых было три;
* его же решение «пришлите заново, по одному», исполненное по тому счёту, отправило бы
  14 сообщений, 11 из них — о решённом (ровно тот спам, на который он жаловался дважды);
* а исполненное без снятия дедупа/анти-шторма — не отправило бы НИ ОДНОГО, молча.

Время и темп здесь ВХОД, а не окружение: ни одна проверка не ждёт по-настоящему и ни
одна не завязана на календарь (`.claude/rules/deployment.md`).
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spa_core.telegram import owner_decisions as OD

# `resend` — НОВЫЙ модуль, и на чистом origin его нет. Импорт держим ОТЛОЖЕННЫМ
# намеренно: с импортом наверху весь файл падал бы на сборке, и положительный контроль
# мерил бы ОТСУТСТВИЕ МОДУЛЯ вместо поведения — украшение, а не проверка (урок #317).
# Так на неисправленном origin проверки счёта открытых вопросов и флага солиситации
# честно ЗАПУСКАЮТСЯ и краснеют по делу.

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)

CARD_TMPL = """---
trackerStatus:
  type: owner-decision
title: {title}
status: {status}
---

## Что случилось и почему это важно

Тестовая карточка {name}.

## Что от тебя нужно

**Вариант 1 — сделать так.** (⭐ рекомендация агента)

**Вариант 2 — сделать иначе.**

## Как понять, что готово

Ответ записан.

## Что будет после

Беру в работу.
"""


def write_card(tracker: Path, name: str, status: str = "needs-owner") -> Path:
    p = tracker / f"{name}.md"
    p.write_text(CARD_TMPL.format(title=f"Вопрос {name}", status=status, name=name),
                 encoding="utf-8")
    return p


class OpenPushCountTest(unittest.TestCase):
    """`open_pushes` обязан считать вопросы по КАРТОЧКЕ, а не по своему журналу."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.tracker = self.root / "tracker"
        self.tracker.mkdir()
        self.state = self.root / "state.json"
        self.addCleanup(self._tmp.cleanup)

    def _state_with(self, cards) -> None:
        self.state.write_text(json.dumps({"pushes": [
            {"pid": f"p{i}", "card": str(p), "card_id": p.stem,
             "title": p.stem, "pushed_at": NOW.isoformat()}
            for i, p in enumerate(cards)
        ]}), encoding="utf-8")

    def test_closed_card_is_not_an_open_question(self):
        """АВАРИЯ 20.08: 11 закрытых карточек считались открытыми вопросами навсегда.

        Журнал узнаёт только о тех ответах, что пришли через него; карточку, закрытую
        циклом (`ingested`), он держит «ждущей» вечно.
        """
        live = write_card(self.tracker, "own-live")
        done = write_card(self.tracker, "own-ingested", status="ingested")
        answered = write_card(self.tracker, "own-owner-done", status="owner-done")
        self._state_with([live, done, answered])

        ids = [r["card_id"] for r in OD.open_pushes(state_path=self.state)]
        self.assertEqual(ids, ["own-live"],
                         "закрытая карточка обязана уйти из счёта открытых вопросов")

    def test_unreadable_status_stays_open(self):
        """Обратный контроль: не прочитали статус ⇒ вопрос ОСТАЁТСЯ открытым.

        Асимметрия намеренная. Потерять вопрос владельца молча дороже, чем показать
        лишний: второе он видит и поправит, первое — нет.
        """
        broken = self.tracker / "own-broken.md"
        broken.write_text("не карточка вовсе, фронтматтера нет", encoding="utf-8")
        self._state_with([broken])
        self.assertEqual([r["card_id"] for r in OD.open_pushes(state_path=self.state)],
                         ["own-broken"])

    def test_missing_card_file_still_excluded(self):
        """Прежнее поведение не тронуто: карточки нет на диске — отвечать не на что."""
        gone = self.tracker / "own-gone.md"
        self._state_with([gone])          # файл СОЗНАТЕЛЬНО не создаём
        self.assertEqual(OD.open_pushes(state_path=self.state), [])

    def test_answered_push_still_excluded(self):
        """Обратный контроль: ответ в журнале по-прежнему закрывает вопрос."""
        card = write_card(self.tracker, "own-answered")
        self.state.write_text(json.dumps({"pushes": [
            {"pid": "p0", "card": str(card), "card_id": card.stem,
             "title": card.stem, "choice": "1", "pushed_at": NOW.isoformat()},
        ]}), encoding="utf-8")
        self.assertEqual(OD.open_pushes(state_path=self.state), [])

    def test_ambiguity_refusal_is_not_weakened(self):
        """Инвариант: на ДВУХ живых кандидатах отказ «неоднозначно» обязан остаться.

        Честнее стал список, а не правило. Тест краснеет, если «починка» счёта
        превратится в угадывание за владельца.
        """
        a = write_card(self.tracker, "own-a")
        b = write_card(self.tracker, "own-b")
        self._state_with([a, b])
        res = OD.resolve_text_answer("Ответ 1", "42", owner_chat_id="42",
                                     state_path=self.state, now=NOW)
        self.assertIsNotNone(res)
        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("reason"), "ambiguous")
        self.assertEqual(res.get("candidates_total"), 2)


class ResendTest(unittest.TestCase):
    """Сама рассылка: солиситирована, размерена по темпу, доставка ИЗМЕРЕНА."""

    def setUp(self):
        global R
        from spa_core.owner_queue import resend as R  # noqa: PLW0603 — см. шапку файла

        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.tracker = self.root / "tracker"
        self.tracker.mkdir()
        self.report = self.root / "report.json"
        self.addCleanup(self._tmp.cleanup)

    def test_resend_lifts_dedup_because_the_owner_asked(self):
        """АВАРИЯ: исполнение решения владельца гасится НАШЕЙ защитой от нас самих.

        Текст вопроса побуквенно тот же, что уходил вчера ⇒ дедуп (окно 30 мин) молча
        роняет каждое сообщение, и владелец, попросивший прислать вопросы заново, не
        получает ни одного. Мерим АРГУМЕНТ, дошедший до отправителя, а не намерение.
        """
        write_card(self.tracker, "own-one")
        seen = {}

        def fake_notify(path, *, dry_run=False, owner_requested=False):
            seen["owner_requested"] = owner_requested
            return "текст"

        with mock.patch("spa_core.owner_queue.notify.notify_needs_owner", fake_notify), \
             mock.patch.object(R, "_measure_delivery", return_value=(True, True, 77)):
            rep = R.resend_open_questions(tracker_dir=self.tracker, now=NOW,
                                          sleep=lambda s: None,
                                          report_path=self.report)
        self.assertTrue(seen.get("owner_requested"),
                        "вопрос, который владелец ПОПРОСИЛ прислать, обязан идти "
                        "солиситированным — иначе дедуп гасит его молча")
        self.assertTrue(rep.ok)
        self.assertEqual(rep.delivered, 1)

    def test_undelivered_message_is_named_not_counted_away(self):
        """АВАРИЯ #309: журнал показывал успех, владелец не получал ничего.

        Лимит потока (12/мин на ВСЕХ отправителей) роняет сообщение молча. Рассылка
        обязана назвать потерянное поимённо и НЕ считаться успешной.
        """
        write_card(self.tracker, "own-lost")
        with mock.patch("spa_core.owner_queue.notify.notify_needs_owner",
                        lambda *a, **k: "текст"), \
             mock.patch.object(R, "_measure_delivery", return_value=(False, False, None)):
            rep = R.resend_open_questions(tracker_dir=self.tracker, now=NOW,
                                          sleep=lambda s: None,
                                          report_path=self.report)
        self.assertFalse(rep.ok)
        self.assertEqual(rep.failed, 1)
        self.assertIn("own-lost", R.summary_line(rep))
        self.assertIn("НЕ ДОСТАВЛЕНО", R.summary_line(rep))

    def test_pacing_stays_under_the_shared_flood_limit(self):
        """АВАРИЯ: пачка вопросов подряд упирается в 12/мин, и ХВОСТ гаснет без следа.

        Темп обязан оставлять запас чужим отправителям (тревоги агентов идут через тот
        же лимит). Проверяем ЭФФЕКТ — сколько сообщений влезает в минуту.
        """
        for i in range(4):
            write_card(self.tracker, f"own-{i}")
        slept = []
        with mock.patch("spa_core.owner_queue.notify.notify_needs_owner",
                        lambda *a, **k: "текст"), \
             mock.patch.object(R, "_measure_delivery", return_value=(True, True, 1)):
            R.resend_open_questions(tracker_dir=self.tracker, now=NOW,
                                    sleep=slept.append, report_path=self.report)
        self.assertEqual(len(slept), 3, "пауза держится МЕЖДУ сообщениями, "
                                        "после последнего она ничего не защищает")
        from spa_core.alerts.telegram_client import MAX_MSGS_PER_MIN
        per_min = 60.0 / slept[0]
        self.assertLessEqual(per_min, MAX_MSGS_PER_MIN / 2,
                             "рассылка обязана занимать не больше половины общего "
                             "лимита — вторая половина принадлежит тревогам агентов")

    def test_dry_run_sends_nothing_and_touches_no_live_state(self):
        """Сухой прогон не отправляет и не регистрирует: нажимать нечего (#216)."""
        write_card(self.tracker, "own-dry")
        calls = []

        def fake_notify(path, *, dry_run=False, owner_requested=False):
            calls.append(dry_run)
            return "текст"

        with mock.patch("spa_core.owner_queue.notify.notify_needs_owner", fake_notify):
            rep = R.resend_open_questions(tracker_dir=self.tracker, now=NOW,
                                          dry_run=True, sleep=lambda s: None,
                                          report_path=self.report)
        self.assertEqual(calls, [True])
        self.assertEqual(rep.delivered, 0)
        self.assertEqual(rep.failed, 0)
        self.assertIn("сухой прогон", R.summary_line(rep))

    def test_closed_cards_are_not_resent(self):
        """АВАРИЯ: вариант 2 по старому счёту прислал бы 11 сообщений о РЕШЁННОМ.

        Это ровно тот поток одинаковых сообщений, на который владелец жаловался
        09.08 и 13.08 — то есть исполнение его решения воспроизвело бы его жалобу.
        """
        write_card(self.tracker, "own-live")
        for i in range(3):
            write_card(self.tracker, f"own-closed-{i}", status="ingested")
        sent = []
        with mock.patch("spa_core.owner_queue.notify.notify_needs_owner",
                        lambda p, **k: sent.append(Path(p).stem) or "текст"), \
             mock.patch.object(R, "_measure_delivery", return_value=(True, True, 1)):
            rep = R.resend_open_questions(tracker_dir=self.tracker, now=NOW,
                                          sleep=lambda s: None,
                                          report_path=self.report)
        self.assertEqual(sent, ["own-live"])
        self.assertEqual(rep.total, 1)

    def test_report_lands_on_disk(self):
        """«Переслал» обязано быть измерением, а не утверждением."""
        write_card(self.tracker, "own-r")
        with mock.patch("spa_core.owner_queue.notify.notify_needs_owner",
                        lambda *a, **k: "текст"), \
             mock.patch.object(R, "_measure_delivery", return_value=(True, True, 5)):
            R.resend_open_questions(tracker_dir=self.tracker, now=NOW,
                                    sleep=lambda s: None, report_path=self.report)
        doc = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["outcomes"][0]["message_id"], 5)

    def test_one_failed_send_does_not_stop_the_rest(self):
        """Fail-CLOSED по отчёту, но не по рассылке: упавшая отправка не рвёт очередь."""
        write_card(self.tracker, "own-a")
        write_card(self.tracker, "own-b")
        calls = {"n": 0}

        def flaky(path, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("сеть отвалилась")
            return "текст"

        with mock.patch("spa_core.owner_queue.notify.notify_needs_owner", flaky), \
             mock.patch.object(R, "_measure_delivery", return_value=(True, True, 1)):
            rep = R.resend_open_questions(tracker_dir=self.tracker, now=NOW,
                                          sleep=lambda s: None,
                                          report_path=self.report)
        self.assertEqual(rep.total, 2)
        self.assertEqual(rep.delivered, 1)
        self.assertEqual(rep.failed, 1)
        self.assertIn("send_raised", rep.outcomes[0].reason)


class MeasureDeliveryTest(unittest.TestCase):
    """Сам ИЗМЕРИТЕЛЬ доставки, без подмен.

    Заведён по своей же мутации: рассылочные тесты подменяли ``_measure_delivery``
    целиком, поэтому мутация «считать доставленным ВСЁ» пережила все 14 проверок
    зелёными. Подменять измеритель и при этом утверждать, что доставка измеряется, —
    ровно тот fail-OPEN, который этот модуль заводился ловить.
    """

    def setUp(self):
        global R
        from spa_core.owner_queue import resend as R  # noqa: PLW0603

        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.state = self.root / "state.json"
        self.addCleanup(self._tmp.cleanup)

    def _write(self, rec: dict) -> None:
        self.state.write_text(json.dumps({"pushes": [rec]}), encoding="utf-8")

    def test_delivered_record_is_read_as_delivered(self):
        self._write({"pid": "p", "card_id": "own-x", "card": "/nope/own-x.md",
                     "delivered": True, "buttons": True, "message_ids": [7]})
        self.assertEqual(R._measure_delivery(Path("/nope/own-x.md"),
                                             state_path=self.state), (True, True, 7))

    def test_failed_send_is_not_delivered(self):
        """`delivered: false` ставит `mark_send_outcome`, когда заслон уронил отправку."""
        self._write({"pid": "p", "card_id": "own-x", "card": "/nope/own-x.md",
                     "delivered": False, "buttons": False})
        self.assertEqual(R._measure_delivery(Path("/nope/own-x.md"),
                                             state_path=self.state), (False, False, None))

    def test_absent_record_is_not_success(self):
        """НЕ ИЗМЕРЕНО ≠ ДОСТАВЛЕНО — записи нет, значит подтверждения нет."""
        self.state.write_text(json.dumps({"pushes": []}), encoding="utf-8")
        self.assertEqual(R._measure_delivery(Path("/nope/own-x.md"),
                                             state_path=self.state), (False, False, None))

    def test_intent_is_not_mistaken_for_outcome(self):
        """`buttons: true` ставится ДО отправки — само по себе доставкой не является.

        На этой подмене намерения исходом стоял класс #309: журнал утверждал успех,
        владелец не получал ничего.
        """
        self._write({"pid": "p", "card_id": "own-x", "card": "/nope/own-x.md",
                     "buttons": True})          # `delivered` СОЗНАТЕЛЬНО отсутствует
        delivered, _, _ = R._measure_delivery(Path("/nope/own-x.md"),
                                              state_path=self.state)
        self.assertFalse(delivered)


class NotifyOwnerRequestedTest(unittest.TestCase):
    """Флаг снимает заслоны ТОЛЬКО по просьбе владельца и только на одну отправку."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.tracker = self.root / "tracker"
        self.tracker.mkdir()
        self.addCleanup(self._tmp.cleanup)

    def test_anti_storm_is_bypassed_only_when_owner_asked(self):
        """АВАРИЯ: анти-шторм (окно 6 ч) глушит ИСПОЛНЕНИЕ решения владельца.

        Он поставлен против НАШЕЙ инициативы. Просьба владельца — не шторм.
        """
        card = write_card(self.tracker, "own-throttled")
        from spa_core.owner_queue import notify as N

        calls = []
        with mock.patch.object(OD, "throttle_state",
                               side_effect=lambda *a, **k: calls.append(1) or (False, "стоп")), \
             mock.patch.object(N, "log"):
            # Без флага — заслон спрошен и отправка подавлена (поведение НЕ ослаблено).
            out = N.notify_needs_owner(card, owner_requested=False)
            self.assertIn("anti-storm", out)
            self.assertEqual(len(calls), 1)

    def test_without_the_flag_dedup_stays_on(self):
        """Обратный контроль: обычное уведомление по-прежнему идёт с дедупом.

        Если бы починка сняла дедуп «заодно», вернулась бы петля спама 09.08/13.08.
        """
        card = write_card(self.tracker, "own-normal")
        from spa_core.owner_queue import notify as N

        seen = {}

        class FakeBot:
            def send_message(self, text, parse_mode="HTML", **extra):
                seen.update(extra)
                return {"result": {"message_id": 11}}

        with mock.patch.object(OD, "throttle_state", return_value=(True, "")), \
             mock.patch("spa_core.telegram.bot.TelegramBot", FakeBot):
            N.notify_needs_owner(card, owner_requested=False)
        self.assertIs(seen.get("dedup"), True)

        seen.clear()
        with mock.patch.object(OD, "throttle_state", return_value=(True, "")), \
             mock.patch("spa_core.telegram.bot.TelegramBot", FakeBot):
            N.notify_needs_owner(card, owner_requested=True)
        self.assertIs(seen.get("dedup"), False,
                      "по просьбе владельца дедуп обязан пропустить повтор")


if __name__ == "__main__":
    unittest.main()
