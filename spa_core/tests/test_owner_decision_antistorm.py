"""Анти-шторм отправок решений владельцу (инцидент 2026-08-20).

Живой замер: 200+ копий одной карточки
(`owner-decision-sait-packages-astro-avtonomnaya-pravka-z`) за ночь + пачка из 20
в 10:58 — петля «сторож говорит „не отправлено“ → цикл гасит отправкой» при
журнале, который держит ОДНУ запись на pid (replace) и потому не видел повторов.

Каждый тест воспроизводит кусок инцидента. Offline, журнал — во временном файле.

Run:
    python3 -m unittest spa_core.tests.test_owner_decision_antistorm -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.telegram import owner_decisions as od

CARD_ID = "owner-decision-sait-packages-astro-avtonomnaya-pravka-z"
NOW = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)

CARD_BODY = (
    "## Что случилось\n\nПравка задела owner-gated область.\n\n"
    "## Что от тебя нужно\n\n1. Одобрить\n2. Отклонить — рекомендую\n3. Отложить\n"
)


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "journal.json"
        self.card = Path(self.tmp.name) / f"{CARD_ID}.md"
        self.card.write_text(
            "---\ntype: owner-decision\nstatus: needs-owner\n---\n\n# Сайт\n\n"
            + CARD_BODY, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _push(self, when: datetime):
        od.register_push(self.card, "Сайт", CARD_BODY,
                         now=when, state_path=self.state,
                         live_root=self.tmp.name)


class TestSendCount(_Base):
    def test_replace_semantics_now_counts(self):
        # До фикса replace прятал повторы: после 3 отправок журнал выглядел как 1.
        for i in range(3):
            self._push(NOW + timedelta(hours=7 * i))
        rec = od._push_by_card_id(CARD_ID, state_path=self.state)
        self.assertEqual(rec.get("send_count"), 3)

    def test_answer_resets_count(self):
        self._push(NOW)
        doc = od._load(od._state_path(self.state))
        doc["pushes"][-1]["choice"] = "2"
        od._save(doc, od._state_path(self.state))
        self._push(NOW + timedelta(hours=7))
        rec = od._push_by_card_id(CARD_ID, state_path=self.state)
        self.assertEqual(rec.get("send_count"), 1)


class TestThrottleState(_Base):
    def test_first_send_allowed(self):
        allowed, why = od.throttle_state(CARD_ID, now=NOW, state_path=self.state)
        self.assertTrue(allowed, why)

    def test_repeat_within_window_suppressed(self):
        # Ровно инцидент: повтор через минуты после предыдущей отправки.
        self._push(NOW)
        allowed, why = od.throttle_state(
            CARD_ID, now=NOW + timedelta(minutes=20), state_path=self.state)
        self.assertFalse(allowed)
        self.assertIn("anti-storm", why)

    def test_repeat_after_window_allowed(self):
        self._push(NOW)
        allowed, _ = od.throttle_state(
            CARD_ID, now=NOW + timedelta(hours=7), state_path=self.state)
        self.assertTrue(allowed)

    def test_cap_silences_forever_until_answered(self):
        for i in range(od.STORM_MAX_SENDS):
            self._push(NOW + timedelta(hours=7 * i))
        allowed, why = od.throttle_state(
            CARD_ID, now=NOW + timedelta(days=30), state_path=self.state)
        self.assertFalse(allowed)
        self.assertIn("потолок", why)

    def test_answered_card_gets_new_life(self):
        # Ответ владельца обнуляет и окно, и потолок: новый вопрос той же
        # карточки (переоткрытие) обязан доехать.
        for i in range(od.STORM_MAX_SENDS):
            self._push(NOW + timedelta(hours=7 * i))
        doc = od._load(od._state_path(self.state))
        doc["pushes"][-1]["choice"] = "2"
        od._save(doc, od._state_path(self.state))
        allowed, _ = od.throttle_state(
            CARD_ID, now=NOW + timedelta(days=30, minutes=1),
            state_path=self.state)
        self.assertTrue(allowed)

    def test_unreadable_journal_fails_open(self):
        # Нечитаемый журнал не смеет ПРЯТАТЬ вопрос владельцу.
        allowed, _ = od.throttle_state(
            CARD_ID, now=NOW, state_path=Path("/nonexistent/dir/journal.json"))
        self.assertTrue(allowed)


class TestNotifyGate(_Base):
    """Гейт в notify_needs_owner: подавленная отправка не шлёт и не регистрирует."""

    def _notify(self, monkey_send):
        import spa_core.owner_queue.notify as notify_mod
        import spa_core.telegram.bot as bot_mod

        class _FakeBot:
            sent = []

            def __init__(self):
                pass

            def send_message(self, msg, **kw):
                _FakeBot.sent.append(msg)
                return True

        _FakeBot.sent = monkey_send
        orig = bot_mod.TelegramBot
        bot_mod.TelegramBot = _FakeBot  # type: ignore[misc]
        try:
            return notify_mod.notify_needs_owner(self.card)
        finally:
            bot_mod.TelegramBot = orig  # type: ignore[misc]

    def test_suppressed_when_recent_unanswered_push_exists(self):
        # Журнал: отправка была только что, ответа нет → notify молчит.
        self._push(datetime.now(timezone.utc))
        import os
        os.environ["SPA_OWNER_DECISIONS_TEST"] = "1"
        try:
            # Направляем модульный STATE_PATH в наш журнал через monkeypatch _state_path.
            orig = od._state_path
            od._state_path = lambda override=None: self.state  # type: ignore[assignment]
            try:
                sent: list = []
                msg = self._notify(sent)
                self.assertIn("anti-storm", msg)
                self.assertEqual(sent, [])  # ничего не ушло
            finally:
                od._state_path = orig  # type: ignore[assignment]
        finally:
            os.environ.pop("SPA_OWNER_DECISIONS_TEST", None)

    def test_dry_run_never_suppressed(self):
        # Сухой прогон ничего не шлёт — гейт его не трогает (текст обязан собраться).
        self._push(datetime.now(timezone.utc))
        import spa_core.owner_queue.notify as notify_mod

        orig = od._state_path
        od._state_path = lambda override=None: self.state  # type: ignore[assignment]
        try:
            msg = notify_mod.notify_needs_owner(self.card, dry_run=True)
            self.assertNotIn("anti-storm", msg)
        finally:
            od._state_path = orig  # type: ignore[assignment]


if __name__ == "__main__":
    unittest.main(verbosity=2)
