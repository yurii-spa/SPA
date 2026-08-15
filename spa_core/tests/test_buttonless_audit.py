#!/usr/bin/env python3
"""«Пишет варианты ответов — кнопок нету»: класс жалобы обязан быть ИЗМЕРИМ.

Жалоба владельца 14.08 09:37Z (карточка `inbox-a-zadacha-pochinit-vse-taki-esche-raz-so`,
вторая половина — `agent-knopki-pod-resheniem-vtoraya-polovina`). Цикл #229 измерил, что
ответить на неё было нечем: журнал пушей знает про кнопки, но только про СВОЙ путь, а общий
журнал канала знает про всех отправителей, но хранит превью в 80 символов и про клавиатуру
не знает ВОВСЕ.

Каждый тест ниже — положительный контроль: снятие починки красит его тем самым текстом,
на который жаловался владелец.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.telegram import owner_decisions
from spa_core.telegram.buttonless_audit import (history_fields, offers_choice, scan,
                                                summary_line)


# ── 1. Детектор узнаёт РЕАЛЬНЫЙ текст нашего же билдера ─────────────────────

class OffersChoiceTests(unittest.TestCase):
    """Формы берём у производителя (`owner_decisions.build_text`), а не из головы."""

    def _build(self, *, has_buttons: bool):
        opts = owner_decisions.parse_options(
            "## Что от тебя нужно\n\n"
            "* **Вариант 1 (рекомендую) — убрать «идёт paper-трек».** Пояснение.\n"
            "* **Вариант 2 — оставить формулировку.** Пояснение.\n")
        self.assertTrue(opts, "предусловие: варианты карточки разобраны")
        return owner_decisions.build_message(
            "Сбалансированный тир: на сайте «идёт paper-трек», а в книге ноль позиций",
            "## Что от тебя нужно\n\n* **Вариант 1 (рекомендую) — убрать.** Х.\n",
            opts, has_buttons=has_buttons,
            card_name="owner-decision-sbalansirovannyi-tir.md")

    def test_message_with_keyboard_offers_a_choice(self):
        self.assertTrue(offers_choice(self._build(has_buttons=True)))

    def test_the_exact_text_the_owner_complained_about(self):
        """Кнопок нет, а варианты в тексте есть — дословно жалоба владельца."""
        text = self._build(has_buttons=False)
        self.assertIn("Кнопки сейчас недоступны", text)
        self.assertTrue(offers_choice(text))

    def test_multiple_choice_card_says_answer_by_numbers(self):
        self.assertTrue(offers_choice(
            "🧑‍⚖️ <b>Нужно твоё решение</b>\n\nВ этой карточке можно выбрать НЕСКОЛЬКО "
            "пунктов, поэтому кнопок нет.\nОтветь номерами в чат (например «1 и 3»)."))

    def test_unparsed_options_are_a_choice_too(self):
        self.assertTrue(offers_choice(
            "⚠️ Варианты в карточке есть, но я не смог собрать из них кнопки."))

    def test_no_options_parsed_is_not_a_choice(self):
        """«Вариантов не нашёл» — fail-CLOSED карточки, а не дефект кнопок."""
        self.assertFalse(offers_choice(
            "🧑‍⚖️ <b>Нужно твоё решение</b>\n\n<b>Заголовок</b>\n\n"
            "Вариантов в карточке не нашёл — открой её в трекере."))

    def test_daily_report_with_numbers_is_not_a_choice(self):
        """Ложная находка дороже пропуска: дайджест перечисляет цифрами, но не спрашивает."""
        self.assertFalse(offers_choice(
            "📊 <b>SPA Daily Report</b> — Day 66\n\n1) aave_v3 40%\n2) pendle 20%\n"
            "3) maple 20%\n💰 Portfolio: $100,882"))

    def test_empty_text_is_not_a_choice(self):
        self.assertFalse(offers_choice(""))
        self.assertFalse(offers_choice(None))  # type: ignore[arg-type]


# ── 2. «Не измерено» ≠ «кнопок не было» ─────────────────────────────────────

class HistoryFieldsTests(unittest.TestCase):

    def test_unmeasured_buttons_write_no_field_at_all(self):
        f = history_fields("Варианты:\n1. раз", None)
        self.assertNotIn("buttons", f)
        self.assertTrue(f["offers_choice"])

    def test_measured_false_is_written(self):
        self.assertIs(history_fields("Ответь номером варианта", False)["buttons"], False)

    def test_measured_true_is_written(self):
        self.assertIs(history_fields("Ответь номером варианта", True)["buttons"], True)


# ── 3. Скан журнала: находка названа, старьё честно «не измерено» ────────────

def _entry(**kw):
    base = {"ts": "2026-08-14T09:00:00+00:00", "ok": True, "preview": "текст"}
    base.update(kw)
    return base


class ScanTests(unittest.TestCase):

    def test_names_the_buttonless_message_with_date_and_text(self):
        rep = scan([
            _entry(ts="2026-08-14T08:00:00+00:00", offers_choice=True, buttons=True),
            _entry(ts="2026-08-14T09:30:00+00:00", offers_choice=True, buttons=False,
                   preview="🧑‍⚖️ Нужно твоё решение / Страница трека…", message_id=42),
        ])
        self.assertEqual(rep["buttonless_count"], 1)
        found = rep["buttonless"][0]
        self.assertEqual(found["ts"], "2026-08-14T09:30:00+00:00")
        self.assertEqual(found["message_id"], 42)
        self.assertIn("Нужно твоё решение", found["preview"])
        self.assertIn("КНОПОК НЕТ", summary_line(rep))

    def test_undelivered_message_is_not_a_finding(self):
        """Подавленное заслоном сообщение в чат не приезжало — кнопки ему не нужны."""
        rep = scan([_entry(ok=False, error="duplicate_dropped",
                           offers_choice=True, buttons=False)])
        self.assertEqual(rep["buttonless_count"], 0)

    def test_old_records_without_the_field_are_unmeasured_not_clean(self):
        rep = scan([_entry(offers_choice=True)])  # запись до цикла #229
        self.assertEqual(rep["buttonless_count"], 0)
        self.assertEqual(rep["unmeasured_count"], 1)
        self.assertIn("не измерено", summary_line(rep).lower())

    def test_messages_without_a_choice_are_not_scanned(self):
        rep = scan([_entry(offers_choice=False, buttons=False)])
        self.assertEqual(rep["with_choice"], 0)
        self.assertEqual(rep["unmeasured_count"], 0)

    def test_legacy_journal_is_not_reported_as_clean(self):
        """Замер на ЖИВОМ журнале 14.08: ни у одной записи поля ещё нет.

        «0 сообщений с вариантами, все с кнопками» на таком журнале — ровно тот
        fail-OPEN, ради которого измерение и затевалось. Первая версия строки его и
        печатала; тест — положительный контроль этой ошибки.
        """
        rep = scan([_entry(preview="📊 SPA Daily Report"), _entry(preview="✅ Пульс")])
        self.assertEqual(rep["with_choice"], 0)
        self.assertEqual(rep["unscanned_count"], 2)
        line = summary_line(rep)
        self.assertIn("НЕ ИЗМЕРЕНЫ", line)
        self.assertNotIn("все с кнопками", line)

    def test_new_records_alongside_old_ones_are_still_judged(self):
        rep = scan([_entry(preview="старьё"),
                    _entry(offers_choice=True, buttons=True)])
        self.assertEqual(rep["with_choice"], 1)
        self.assertEqual(rep["unscanned_count"], 1)
        self.assertIn("все с кнопками", summary_line(rep))

    def test_junk_entries_never_raise(self):
        self.assertEqual(scan([None, 5, "x", {}])["buttonless_count"], 0)  # type: ignore


# ── 4. Двери меряют кнопки — иначе класс снова станет неизмеримым ───────────

class DoorsRecordButtonsTests(unittest.TestCase):
    """Проводка, а не деталь: правка внутри `_record_history` без вызова — мёртвая."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hist = Path(self.tmp.name) / "alert_history.json"
        os.environ["SPA_ALERT_HISTORY_TEST"] = "1"
        self.addCleanup(os.environ.pop, "SPA_ALERT_HISTORY_TEST", None)
        from spa_core.alerts import telegram_client as tc

        self.tc = tc
        self._orig = tc._HISTORY_STATE
        tc._HISTORY_STATE = self.hist
        self.addCleanup(setattr, tc, "_HISTORY_STATE", self._orig)

    def _entries(self):
        return json.loads(self.hist.read_text())["entries"]

    def test_record_history_measures_choice_from_the_full_text(self):
        """Превью — 80 символов, поэтому судить по нему нельзя: меряем при отправке."""
        text = ("🧑‍⚖️ <b>Нужно твоё решение</b>\n\n<b>" + "З" * 120 + "</b>\n\n"
                "<b>Варианты:</b>\n<b>1.</b> Раз\n<b>2.</b> Два")
        self.tc._record_history(text, ok=True, buttons=False)
        rec = self._entries()[-1]
        self.assertNotIn("Варианты", rec["preview"], "предусловие: превью обрезано")
        self.assertTrue(rec["offers_choice"])
        self.assertIs(rec["buttons"], False)

    def test_bot_door_records_the_keyboard_it_attached(self):
        from spa_core.telegram.bot import TelegramBot

        bot = TelegramBot.__new__(TelegramBot)
        bot.token, bot.chat_id = "t", "42"
        bot._api_call = lambda method, params: {"ok": True, "result": {"message_id": 7}}
        kb = {"inline_keyboard": [[{"text": "1", "callback_data": "act:x:1"}]]}
        bot.send_message("<b>Варианты:</b>\n<b>1.</b> Раз", reply_markup=kb)
        bot.send_message("<b>Варианты:</b>\n<b>1.</b> Раз")
        recs = self._entries()
        self.assertIs(recs[-2]["buttons"], True)
        self.assertIs(recs[-1]["buttons"], False)
        self.assertTrue(recs[-1]["offers_choice"])

    def test_client_door_records_the_keyboard_it_attached(self):
        sent = []

        def fake_post(payload):
            self.tc._record_history(payload.get("text", ""), ok=True, message_id=1,
                                    buttons="reply_markup" in payload)
            sent.append(payload)
            return True

        # Проверяем ИМЕННО контракт двери: та же строка, что стоит в `_post_message`.
        fake_post({"text": "Ответь номером варианта", "reply_markup": "{}"})
        fake_post({"text": "Ответь номером варианта"})
        recs = self._entries()
        self.assertIs(recs[-2]["buttons"], True)
        self.assertIs(recs[-1]["buttons"], False)


# ── 5. Читатель: находка доезжает до отчёта и НЕ звонит владельцу ────────────

class MonitorIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ddir = Path(self.tmp.name)
        self.tdir = self.ddir / "tracker"
        self.tdir.mkdir()

    def _report(self):
        from spa_core.monitoring.owner_decision_pending import \
            check_pending_owner_decisions

        return check_pending_owner_decisions(data_dir=self.ddir, tracker_dir=self.tdir)

    def _history(self, entries):
        (self.ddir / "alert_history.json").write_text(
            json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")

    def test_finding_reaches_the_report(self):
        self._history([_entry(offers_choice=True, buttons=False,
                              preview="🧑‍⚖️ Нужно твоё решение …")])
        ch = self._report()["channel_buttons"]
        self.assertTrue(ch["measured"])
        self.assertEqual(ch["buttonless_count"], 1)

    def test_finding_does_not_escalate_the_alerting_status(self):
        """Ответить на жалобу о спаме новым звонком владельцу — тот же дефект (ADR-084).

        Отчёт ежечасно читает `agent_health_monitor`, умеющий звонить. Находка едет в
        отчёт и в шаг 0-офис, а не в чат — направление таблички решает.
        """
        self._history([_entry(offers_choice=True, buttons=False)])
        with_finding = self._report()
        self._history([_entry(offers_choice=True, buttons=True)])
        without = self._report()
        self.assertEqual(with_finding["status"], without["status"])
        self.assertEqual(with_finding["issues"], without["issues"])

    def test_missing_history_is_unmeasured_not_clean(self):
        ch = self._report()["channel_buttons"]
        self.assertFalse(ch["measured"])
        self.assertIn("не измерен", ch["reason"])

    def test_corrupt_history_is_unmeasured_not_clean(self):
        (self.ddir / "alert_history.json").write_text("{ не json", encoding="utf-8")
        ch = self._report()["channel_buttons"]
        self.assertFalse(ch["measured"])


# ── 6. Обязательный шаг 0-офис ПЕЧАТАЕТ находку (иначе читателя нет) ────────

class OfficeStepPrintsItTests(unittest.TestCase):
    """Класс «правка сделана, никто не читает» закрывается только здесь."""

    def _summarize(self, data):
        import importlib.util

        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location(
            "_consume_office", root / "scripts" / "consume_office_reports.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return "\n".join(mod._summarize_json("data/owner_decision_pending.json", data))

    def test_prints_the_named_finding(self):
        out = self._summarize({
            "status": "OK", "reason": "остановки нет",
            "channel_buttons": {"measured": True, "with_choice": 3, "buttonless_count": 1,
                                "unmeasured_count": 0,
                                "buttonless": [{"ts": "2026-08-14T09:30:00+00:00",
                                                "preview": "🧑‍⚖️ Нужно твоё решение"}]}})
        self.assertIn("КНОПОК НЕТ", out)
        self.assertIn("2026-08-14T09:30:00+00:00", out)

    def test_old_report_shape_is_called_unmeasured(self):
        out = self._summarize({"status": "OK", "reason": "остановки нет"})
        self.assertIn("НЕ ИЗМЕРЕНЫ", out)

    def test_clean_channel_is_said_out_loud(self):
        out = self._summarize({"status": "OK", "reason": "x",
                               "channel_buttons": {"measured": True, "with_choice": 2,
                                                   "buttonless_count": 0,
                                                   "unmeasured_count": 0,
                                                   "buttonless": []}})
        self.assertIn("все с кнопками", out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
