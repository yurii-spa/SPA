#!/usr/bin/env python3
"""Кнопки действий под алертом (задание владельца 2026-08-07).

Что здесь пиннится — и почему именно это:

* **Проводка, а не только деталь.** Урок цикла #144: удалённая точка вызова оставила
  22 своих и 1342 смежных теста зелёными, пока фича была мертва в проде. Поэтому есть
  тесты на ``telegram_client.send_message`` — единственную точку, через которую алерты
  уходят от ВСЕХ мониторов, — а не только на сам реестр вариантов.
* **Отсутствие регрессии.** Дайджест / ✅-пульс обязаны уходить БЕЗ кнопок и без
  единого лишнего байта в payload: fail-CLOSED к вчерашнему поведению.
* **Инвариант #1.** У рода `risk` рекомендация обязана вести к решению ВЛАДЕЛЬЦА,
  а не к «агент починит»: агенту risk-логика запрещена.
* **Инвариант #15.** Карточка `needs-owner` обязана иметь ровно четыре заголовка §2.4.
* **Тесты не пишут в живое состояние.** Инцидент «прогон тестов может заглушить
  настоящую тревогу»: журнал алертов под pytest обязан уезжать во временный файл.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from spa_core.telegram import alert_actions as aa
from spa_core.tests._freshness import now_utc

# Время — ВХОД, а не окружение: и маячок, и проверка получают ОДИН И ТОТ ЖЕ момент,
# поэтому тест не зависит от календаря. Литеральной даты здесь нет намеренно — ни один
# ассерт про конкретную дату не спрашивает, важна только общая точка отсчёта у обеих
# сторон (правило `.claude/rules/deployment.md`, преференция №1).
FIXED_NOW = now_utc()

PROBLEM = "🚨 SPA — агент com.spa.daily_cycle не работает (exit 78)"
RISK = "🚨 SPA — HARD_KILL: drawdown 10.4% превысил порог"
DIGEST = "SPA — Ежедневный отчёт\n\nПортфель $100,000. ⚠️ один пул под наблюдением."
PULSE = "✅ Dashboard check OK — 12/12 agents"


def _fresh_beacon(dirpath: Path, now=FIXED_NOW) -> Path:
    """Маячок «живой бот с новым кодом» — без него кнопки не вешаются (интерлок ADR-069).

    ``now`` совпадает с тем временем, которое тест передаёт в ``register_alert``:
    маячок обязан быть свежим ОТНОСИТЕЛЬНО часов проверки. ``now=None`` — реальные часы
    (для пути, который идёт без инъекции времени, как в проде).
    """
    path = Path(dirpath) / "beacon.json"
    aa.publish_handler_beacon(now=now, beacon_path=path)
    return path


class Classification(unittest.TestCase):
    def test_problem_alert_is_classified_by_kind(self):
        self.assertEqual(aa.classify_problem(PROBLEM), "agent_down")
        self.assertEqual(aa.classify_problem(RISK), "risk")
        self.assertEqual(aa.classify_problem("❌ GAP DETECTED — цикл не отработал"),
                         "cycle_gap")
        self.assertEqual(aa.classify_problem("⚠️ Артефакт stale: 476ч при SLO 26ч"),
                         "data_stale")

    def test_digest_gets_no_buttons_even_though_body_has_a_warning_sign(self):
        """⚠️ в ТЕЛЕ отчёта — не проблема. Иначе кнопки уехали бы на дайджест."""
        self.assertIsNone(aa.classify_problem(DIGEST))

    def test_green_pulse_gets_no_buttons(self):
        self.assertIsNone(aa.classify_problem(PULSE))

    def test_empty_and_unknown_text_fail_closed(self):
        self.assertIsNone(aa.classify_problem(""))
        self.assertIsNone(aa.classify_problem(None))
        self.assertIsNone(aa.classify_problem("Турнир завершён, лидер variant-N"))

    def test_generic_problem_falls_back_to_the_generic_kind(self):
        self.assertEqual(aa.classify_problem("❌ Что-то пошло не так"), "problem")


class OptionsRegistry(unittest.TestCase):
    def test_every_kind_has_exactly_one_recommendation(self):
        for kind in aa._KIND_OPTIONS:
            opts = aa.options_for(kind)
            rec = aa.recommended_option(kind)
            marked = [o for o in opts if o.id == rec.id]
            self.assertEqual(len(marked), 1, kind)

    def test_risk_alerts_recommend_the_owner_not_a_fix(self):
        """Инвариант #1: risk-логику агент не трогает — рекомендация ведёт к владельцу."""
        rec = aa.recommended_option("risk")
        self.assertEqual(rec.id, "own")
        self.assertEqual(rec.card_type, "owner-decision")

    def test_no_option_executes_anything_only_cards(self):
        """Ни один вариант не исполняет код: максимум — заводит карточку (или ничего)."""
        for opt in aa._ALL_OPTIONS.values():
            self.assertIn(opt.card_type, (None, "inbox", "owner-decision"))

    def test_recommended_label_is_marked_for_the_owner(self):
        kind = "agent_down"
        rec = aa.recommended_option(kind)
        self.assertIn("⭐", aa.label_for(rec, kind, "ru"))
        other = [o for o in aa.options_for(kind) if o.id != rec.id][0]
        self.assertNotIn("⭐", aa.label_for(other, kind, "ru"))


class Keyboard(unittest.TestCase):
    def test_every_callback_data_fits_the_telegram_64_byte_limit(self):
        for kind in aa._KIND_OPTIONS:
            kb = aa.build_keyboard("deadbeef", kind, "ru")
            for row in kb["inline_keyboard"]:
                for btn in row:
                    self.assertLessEqual(len(btn["callback_data"].encode("utf-8")), 64)

    def test_keyboard_has_a_button_per_offered_option(self):
        kb = aa.build_keyboard("deadbeef", "agent_down", "ru")
        flat = [b for row in kb["inline_keyboard"] for b in row]
        self.assertEqual(len(flat), len(aa.options_for("agent_down")))
        self.assertTrue(all(b["callback_data"].startswith("act:aa:deadbeef:") for b in flat))


class StatePathSafety(unittest.TestCase):
    def test_under_pytest_the_journal_never_touches_the_live_data_dir(self):
        """Прогон тестов не имеет права писать в живое состояние алертов."""
        p = aa._state_path()
        self.assertNotEqual(p, aa.STATE_PATH)
        self.assertNotIn("SPA_Claude/data", str(p))

    def test_explicit_override_wins(self):
        self.assertEqual(aa._state_path("/tmp/x.json"), Path("/tmp/x.json"))


class HandlerInterlock(unittest.TestCase):
    """Кнопка появляется, ТОЛЬКО если есть живой бот, умеющий её обработать.

    Мониторы перечитывают код каждый запуск, бот — долгоживущий (KeepAlive, аптайм
    сутками). Без интерлока кнопки поехали бы раньше обработчика, а нажатие по старому
    боту не «ничего не делает»: неизвестный `act:`-глагол уходит в ветку по умолчанию и
    ПЕРЕПИСЫВАЕТ сообщение алерта панелью — то есть стирает саму тревогу.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.state = self.dir / "alerts.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_live_handler_means_no_buttons_at_all(self):
        missing = self.dir / "nope.json"
        self.assertFalse(aa.handler_available(now=FIXED_NOW, beacon_path=missing))
        self.assertIsNone(aa.register_alert(PROBLEM, now=FIXED_NOW,
                                            state_path=self.state, beacon_path=missing))

    def test_fresh_beacon_enables_buttons(self):
        b = _fresh_beacon(self.dir)
        self.assertTrue(aa.handler_available(now=FIXED_NOW, beacon_path=b))
        self.assertIsNotNone(aa.register_alert(PROBLEM, now=FIXED_NOW,
                                               state_path=self.state, beacon_path=b))

    def test_stale_beacon_is_refused(self):
        """Бот умер — маячок перестал обновляться; кнопки гаснут сами, без вмешательства."""
        b = _fresh_beacon(self.dir)
        later = FIXED_NOW + timedelta(hours=1)
        self.assertFalse(aa.handler_available(now=later, beacon_path=b))

    def test_beacon_without_the_capability_is_refused(self):
        b = self.dir / "old.json"
        b.write_text(json.dumps({"updated_at": FIXED_NOW.isoformat(),
                                 "capabilities": ["menus"]}))
        self.assertFalse(aa.handler_available(now=FIXED_NOW, beacon_path=b))

    def test_garbage_beacon_fails_closed(self):
        b = self.dir / "junk.json"
        b.write_text("{не json")
        self.assertFalse(aa.handler_available(now=FIXED_NOW, beacon_path=b))

    def test_beacon_under_pytest_never_touches_the_live_data_dir(self):
        self.assertNotEqual(aa._beacon_path(), aa.BEACON_PATH)

    def test_the_bot_publishes_the_beacon_on_its_real_poll_entrypoint(self):
        """Проводка: маячок ставит настоящая точка входа бота, а не только тест."""
        from spa_core.telegram.bot import TelegramBot

        b = self.dir / "from_bot.json"
        bot = TelegramBot.__new__(TelegramBot)  # без сети и Keychain
        # Маячок НЕ ставится тестом руками: проверяется, что его ставит сама точка
        # входа. Иначе тест был бы зелёным и с вырезанной проводкой (мутация M8).
        with mock.patch.object(aa, "_beacon_path", return_value=b), \
             mock.patch.object(TelegramBot, "get_updates", return_value=[]):
            self.assertEqual(bot.run_once(), 0)
        self.assertTrue(b.exists())
        self.assertTrue(aa.handler_available(beacon_path=b))


class RegisterAndChoose(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "alerts.json"
        self.tracker = Path(self.tmp.name) / "tracker"
        self.tracker.mkdir()
        self.beacon = _fresh_beacon(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _register(self, text=PROBLEM):
        out = aa.register_alert(text, now=FIXED_NOW, state_path=self.state,
                                beacon_path=self.beacon)
        self.assertIsNotNone(out)
        return out

    def test_non_problem_is_not_registered_at_all(self):
        self.assertIsNone(aa.register_alert(DIGEST, now=FIXED_NOW, state_path=self.state,
                                            beacon_path=self.beacon))
        self.assertFalse(self.state.exists())

    def test_registered_alert_keeps_the_text_verbatim(self):
        alert_id, _kb = self._register()
        doc = json.loads(self.state.read_text())
        entry = doc["alerts"][-1]
        self.assertEqual(entry["id"], alert_id)
        self.assertEqual(entry["text"], PROBLEM)
        self.assertEqual(entry["kind"], "agent_down")

    def test_tap_creates_an_inbox_card_the_orchestrator_will_pick_up(self):
        alert_id, _kb = self._register()
        res = aa.record_choice(alert_id, "fix", state_path=self.state,
                               tracker_dir=self.tracker, now=FIXED_NOW)
        self.assertTrue(res.ok)
        self.assertEqual(res.card_type, "inbox")
        card = Path(res.card_path)
        self.assertTrue(card.exists())
        body = card.read_text()
        self.assertIn("status: new", body)          # new = очередь оркестратора
        self.assertIn(PROBLEM, body)                # алерт процитирован дословно
        self.assertIn("alert_id: {}".format(alert_id), body)

    def test_same_button_twice_does_not_create_a_second_card(self):
        alert_id, _kb = self._register()
        first = aa.record_choice(alert_id, "fix", state_path=self.state,
                                 tracker_dir=self.tracker, now=FIXED_NOW)
        second = aa.record_choice(alert_id, "fix", state_path=self.state,
                                  tracker_dir=self.tracker, now=FIXED_NOW)
        self.assertTrue(second.ok)
        self.assertTrue(second.already)
        self.assertEqual(first.card_path, second.card_path)
        self.assertEqual(len(list(self.tracker.glob("*.md"))), 1)

    def test_a_different_button_is_a_different_intent_and_does_create_a_card(self):
        alert_id, _kb = self._register()
        aa.record_choice(alert_id, "fix", state_path=self.state,
                         tracker_dir=self.tracker, now=FIXED_NOW)
        res = aa.record_choice(alert_id, "own", state_path=self.state,
                               tracker_dir=self.tracker, now=FIXED_NOW)
        self.assertTrue(res.ok)
        self.assertFalse(res.already)
        self.assertEqual(len(list(self.tracker.glob("*.md"))), 2)

    def test_owner_decision_card_follows_the_mandatory_four_section_format(self):
        """Инвариант #15: карточка владельцу — ровно эти четыре заголовка."""
        alert_id, _kb = self._register(RISK)
        res = aa.record_choice(alert_id, "own", state_path=self.state,
                               tracker_dir=self.tracker, now=FIXED_NOW)
        body = Path(res.card_path).read_text()
        for header in ("## Что случилось и почему это важно",
                       "## Что от тебя нужно",
                       "## Как понять, что готово",
                       "## Что будет после"):
            self.assertIn(header, body)
        self.assertIn("status: needs-owner", body)
        self.assertTrue(res.notify_needed)

    def test_expected_button_creates_no_card_but_is_recorded(self):
        alert_id, _kb = self._register()
        res = aa.record_choice(alert_id, "skip", state_path=self.state,
                               tracker_dir=self.tracker, now=FIXED_NOW)
        self.assertTrue(res.ok)
        self.assertIsNone(res.card_path)
        self.assertEqual(len(list(self.tracker.glob("*.md"))), 0)
        doc = json.loads(self.state.read_text())
        self.assertIn("skip", doc["alerts"][-1]["choices"])

    def test_aged_out_alert_refuses_honestly_instead_of_inventing_text(self):
        res = aa.record_choice("00000000", "fix", state_path=self.state,
                               tracker_dir=self.tracker, now=FIXED_NOW)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "alert_not_found")
        self.assertEqual(len(list(self.tracker.glob("*.md"))), 0)
        self.assertIn("вытеснен", aa.confirmation_text(res, "ru"))

    def test_unknown_option_is_refused(self):
        alert_id, _kb = self._register()
        res = aa.record_choice(alert_id, "nuke-the-portfolio", state_path=self.state,
                               tracker_dir=self.tracker, now=FIXED_NOW)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "unknown_option")

    def test_card_creation_failure_never_raises_to_the_bot(self):
        alert_id, _kb = self._register()
        with mock.patch("spa_core.owner_queue.queue.create_card",
                        side_effect=OSError("disk full")):
            res = aa.record_choice(alert_id, "fix", state_path=self.state,
                                   tracker_dir=self.tracker, now=FIXED_NOW)
        self.assertFalse(res.ok)
        self.assertTrue(res.reason.startswith("card_failed:"))
        self.assertIn("Не получилось", aa.confirmation_text(res, "ru"))

    def test_journal_is_ring_buffered(self):
        for i in range(aa.HISTORY_MAX + 5):
            aa.register_alert("🚨 проблема номер {}".format(i), now=FIXED_NOW,
                              state_path=self.state, beacon_path=self.beacon)
        doc = json.loads(self.state.read_text())
        self.assertEqual(len(doc["alerts"]), aa.HISTORY_MAX)


class Wiring(unittest.TestCase):
    """Фича обязана быть ЖИВОЙ на пути, которым реально ходят мониторы."""

    def setUp(self):
        # В тестовом окружении бот не запущен, поэтому интерлок (правильно) погасил бы
        # кнопки. Подменяем ПУТЬ к маячку на свежий — сама функция проверки настоящая,
        # так что тест проводки не обходит интерлок, а удовлетворяет его.
        self.tmp = tempfile.TemporaryDirectory()
        # маячок по РЕАЛЬНЫМ часам: этот путь идёт без инъекции времени, как в проде
        self.beacon = _fresh_beacon(self.tmp.name, now=None)
        self._p_beacon = mock.patch.object(aa, "_beacon_path", return_value=self.beacon)
        self._p_beacon.start()

    def tearDown(self):
        self._p_beacon.stop()
        self.tmp.cleanup()

    def test_problem_alert_leaves_telegram_client_with_buttons(self):
        from spa_core.alerts import telegram_client as tc

        captured = {}

        def fake_post(payload):
            captured.update(payload)
            return True

        with mock.patch.object(tc, "_post_message", side_effect=fake_post):
            self.assertTrue(tc.send_message(PROBLEM))
        self.assertIn("reply_markup", captured)
        kb = json.loads(captured["reply_markup"])
        flat = [b for row in kb["inline_keyboard"] for b in row]
        self.assertTrue(flat)
        self.assertTrue(any("⭐" in b["text"] for b in flat),
                        "ровно один вариант обязан быть помечен рекомендацией")

    def test_digest_leaves_telegram_client_exactly_as_before(self):
        from spa_core.alerts import telegram_client as tc

        captured = {}
        with mock.patch.object(tc, "_post_message",
                               side_effect=lambda p: captured.update(p) or True):
            tc.send_message(DIGEST)
        self.assertNotIn("reply_markup", captured)
        self.assertEqual(set(captured), {"text", "parse_mode"})

    def test_actions_false_forces_the_old_path(self):
        from spa_core.alerts import telegram_client as tc

        captured = {}
        with mock.patch.object(tc, "_post_message",
                               side_effect=lambda p: captured.update(p) or True):
            tc.send_message(PROBLEM, actions=False)
        self.assertNotIn("reply_markup", captured)

    def test_a_broken_button_layer_never_blocks_the_alert_itself(self):
        from spa_core.alerts import telegram_client as tc

        captured = {}
        with mock.patch.object(aa, "register_alert", side_effect=RuntimeError("boom")), \
             mock.patch.object(tc, "_post_message",
                               side_effect=lambda p: captured.update(p) or True):
            self.assertTrue(tc.send_message(PROBLEM))
        self.assertEqual(captured.get("text"), PROBLEM)


class _Transport:
    def __init__(self):
        self.sends = []
        self.edits = []
        self.answered = []

    def send_message(self, chat_id, text, reply_markup=None):
        self.sends.append((chat_id, text, reply_markup))
        return {"ok": True}

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        self.edits.append((chat_id, message_id, text, reply_markup))
        return {"ok": True}

    def answer_callback(self, callback_id):
        self.answered.append(callback_id)


class RouterTap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "alerts.json"
        self.tracker = Path(self.tmp.name) / "tracker"
        self.tracker.mkdir()
        self.beacon = _fresh_beacon(self.tmp.name)
        self.transport = _Transport()
        from spa_core.telegram.router import Router

        self.router = Router(self.transport, owner_chat_id="42")

    def tearDown(self):
        self.tmp.cleanup()

    def _tap(self, data, chat_id="42"):
        # Язык ответа берётся из настроек владельца; в тесте фиксируем RU явно,
        # чтобы проверка не зависела от живого data/telegram/user_prefs.json.
        with mock.patch("spa_core.telegram.prefs.get_lang", return_value="ru"), \
             mock.patch.object(aa, "_state_path", return_value=self.state), \
             mock.patch("spa_core.owner_queue.queue.TRACKER_DIR", self.tracker):
            return self.router.handle_callback(data, chat_id, message_id=7,
                                               callback_id="cb1")

    def test_tap_answers_the_spinner_creates_a_card_and_replies_with_a_NEW_message(self):
        alert_id, _kb = aa.register_alert(PROBLEM, now=FIXED_NOW, state_path=self.state,
                                          beacon_path=self.beacon)
        self._tap("act:aa:{}:fix".format(alert_id))
        self.assertEqual(self.transport.answered, ["cb1"])
        self.assertEqual(len(self.transport.sends), 1)
        self.assertEqual(self.transport.edits, [],
                         "алерт обязан остаться в чате — правим не его, а отвечаем новым")
        self.assertEqual(len(list(self.tracker.glob("*.md"))), 1)
        self.assertIn("Завёл карточку", self.transport.sends[0][1])

    def test_non_owner_tap_creates_nothing(self):
        alert_id, _kb = aa.register_alert(PROBLEM, now=FIXED_NOW, state_path=self.state,
                                          beacon_path=self.beacon)
        self._tap("act:aa:{}:fix".format(alert_id), chat_id="999")
        self.assertEqual(self.transport.sends, [])
        self.assertEqual(len(list(self.tracker.glob("*.md"))), 0)

    def test_navigation_callbacks_still_edit_in_place(self):
        """Положительный контроль: обычные кнопки меню не задеты новой веткой."""
        with mock.patch.object(aa, "_state_path", return_value=self.state):
            self.router.handle_callback("nav:home", "42", message_id=7, callback_id="cb2")
        self.assertEqual(len(self.transport.edits), 1)
        self.assertEqual(self.transport.sends, [])

    def test_unknown_alert_id_replies_honestly_and_does_not_crash(self):
        self._tap("act:aa:ffffffff:fix")
        self.assertEqual(len(self.transport.sends), 1)
        self.assertIn("вытеснен", self.transport.sends[0][1])
        self.assertEqual(len(list(self.tracker.glob("*.md"))), 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
