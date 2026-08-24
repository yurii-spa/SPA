#!/usr/bin/env python3
"""Ремонт кнопок состоялся — а сторож всё равно зовёт чинить путь отправки.

Замер цикла #370 на ЖИВОМ отчёте (`data/owner_decision_pending.json`, 24.08 16:00Z).
Шаг 0-офис печатал:

    ⚠️ КНОПОК НЕТ у 4 доставленных сообщений с вариантами; свежайшее
    2026-08-24T11:21:37Z … [наша дверь, журнал говорит «кнопки были» — чинить путь
    между сборкой клавиатуры и отправкой, карточка owner-decision-ezhednevnuyu-…]

Запись того же сообщения в журнале пушей, поле в поле:

    "pushed_at": "2026-08-24T11:21:36.944191+00:00",
    "message_ids": [9048, 9056],
    "buttons_fixed_at": "2026-08-24T13:16:47.939426+00:00",
    "answered_at": "2026-08-24T13:28:59.691046+00:00"

То есть штатный ремонт (`heal_buttonless`) кнопки ДОСЛАЛ вторым сообщением, и владелец
нажал. Чинить «путь между сборкой клавиатуры и отправкой» по этой записи нечего, а
находка неснимаема ПО ПОСТРОЕНИЮ: сообщение 9048 кнопок задним числом не отрастит.

Каждый тест ниже — положительный контроль: на модуле ДО правки он краснеет, и краснеет
ровно тем, на что жаловался замер. Правка ничего не прячет — починенное переезжает на
свою полку со своим счётчиком, и вместе с ним печатается число, которого не мерил никто:
сколько владелец просидел с вопросом, на который нечем ответить.

Дат-литералов здесь нет намеренно (правило `.claude/rules/deployment.md`): предмет — не
календарь, а РАЗНИЦА двух отметок, поэтому фикстуры относительные (`_freshness.ts`).
"""
from __future__ import annotations

import unittest

from spa_core.telegram.buttonless_audit import (JOIN_HEALED, JOIN_OWN_CONTRADICTS,
                                                attribute_send, scan, summary_line)

from ._freshness import ts

CARD = "owner-decision-ezhednevnuyu-proverku-analitiki-nekomu-g"
PREVIEW = "🧑‍⚖️ <b>Нужно твоё решение</b>\n\n<b>Ежедневную проверку аналитики некому гонять —"

#: Живой случай 24.08: отправка без кнопок, ремонт через 1.92 ч, второй message_id.
SENT_AGO_H = 5.0
FIXED_AGO_H = SENT_AGO_H - 1.92


def _channel(**over):
    """Запись ОБЩЕГО журнала канала (`alert_history.json`) — как её видит скан."""
    rec = {"ok": True, "offers_choice": True, "buttons": False,
           "ts": ts(hours_ago=SENT_AGO_H), "preview": PREVIEW, "message_id": 9048}
    rec.update(over)
    return rec


def _push(**over):
    """Запись журнала пушей (`telegram_owner_decisions.json`) — живая, поле в поле."""
    rec = {"pid": "20d50e93", "card_id": CARD, "buttons": True,
           "message_ids": [9048, 9056],
           "pushed_at": ts(hours_ago=SENT_AGO_H),
           "buttons_fixed_at": ts(hours_ago=FIXED_AGO_H)}
    rec.update(over)
    return rec


class HealedIsNotAnOpenDefect(unittest.TestCase):
    """Досланные вдогонку кнопки обязаны читаться иначе, чем недосланные."""

    def test_repaired_send_is_not_reported_as_a_send_path_defect(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ живой находки 24.08.

        До правки: `own_door_says_buttons` — «чинить путь между сборкой клавиатуры и
        отправкой», по записи, где ремонт уже отработал.
        """
        by_id = {9048: _push()}
        cause = attribute_send(_channel(), by_id, 0, have_journal=True)
        self.assertEqual(cause["code"], JOIN_HEALED)
        self.assertNotEqual(cause["code"], JOIN_OWN_CONTRADICTS)
        self.assertIn("досланы вдогонку", cause["text"])
        self.assertEqual(cause["card_id"], CARD)

    def test_the_owner_wait_is_measured_and_named(self):
        """Число, которого не мерил никто: 11:21:37 → 13:16:47 = 1.92 ч без ответа."""
        cause = attribute_send(_channel(), {9048: _push()}, 0, have_journal=True)
        self.assertAlmostEqual(cause["waited_h"], 1.92, places=1)

    def test_the_healing_message_is_named(self):
        """Кнопки приехали ВТОРЫМ сообщением — его номер есть, и он назван."""
        cause = attribute_send(_channel(), {9048: _push()}, 0, have_journal=True)
        self.assertEqual(cause["healed_by"], 9056)

    def test_repair_without_a_returned_id_is_unmeasured_not_invented(self):
        """Досылка не оставила id ⇒ «не измерено», а не выдуманный номер.

        Ремонт всё равно СОСТОЯЛСЯ: отметку без удавшейся отправки не ставят.
        """
        cause = attribute_send(_channel(), {9048: _push(message_ids=[9048])}, 0,
                               have_journal=True)
        self.assertEqual(cause["code"], JOIN_HEALED)
        self.assertIsNone(cause["healed_by"])


class UnrepairedStaysLoud(unittest.TestCase):
    """Обратный контроль: без отметки о ремонте вердикт остаётся прежним, громким."""

    def test_no_repair_mark_still_calls_to_fix_the_send_path(self):
        cause = attribute_send(_channel(), {9048: _push(buttons_fixed_at=None)}, 0,
                               have_journal=True)
        self.assertEqual(cause["code"], JOIN_OWN_CONTRADICTS)

    def test_blank_repair_mark_is_not_a_repair(self):
        """Пустая строка — не отметка. Сомнение решается в пользу ГРОМКОГО вердикта."""
        cause = attribute_send(_channel(), {9048: _push(buttons_fixed_at="   ")}, 0,
                               have_journal=True)
        self.assertEqual(cause["code"], JOIN_OWN_CONTRADICTS)

    def test_repair_earlier_than_the_send_leaves_the_wait_unmeasured(self):
        """Ремонт РАНЬШЕ отправки ⇒ часы врут ⇒ «не измерено», а не ноль (урок #291)."""
        cause = attribute_send(_channel(), {9048: _push(
            buttons_fixed_at=ts(hours_ago=SENT_AGO_H + 1))}, 0, have_journal=True)
        self.assertEqual(cause["code"], JOIN_HEALED)
        self.assertIsNone(cause["waited_h"])


class ScanKeepsBothShelves(unittest.TestCase):
    """Починенное не исчезает — оно переезжает. Вычеркнуть его было бы fail-OPEN."""

    def _scan_live(self):
        """Живой отчёт 24.08: один починенный + один настоящий незакрытый."""
        other = _channel(message_id=8955, ts=ts(hours_ago=SENT_AGO_H + 20),
                         preview="🧑‍⚖️ <b>Нужно твоё решение</b>\n\n<b>Внутридневная")
        return scan([_channel(), other], pushes=[_push()])

    def test_repaired_case_leaves_the_alarm_count(self):
        rep = self._scan_live()
        self.assertEqual(rep["buttonless_count"], 1)
        self.assertEqual([r["message_id"] for r in rep["buttonless"]], [8955])

    def test_repaired_case_is_still_in_the_report_with_its_own_count(self):
        """Не подавление: у записи своя полка, свой счётчик и вся её фактура."""
        rep = self._scan_live()
        self.assertEqual(rep["healed_count"], 1)
        self.assertEqual([r["message_id"] for r in rep["healed"]], [9048])
        self.assertEqual(rep["healed"][0]["cause"]["card_id"], CARD)

    def test_the_message_is_counted_as_offering_a_choice_either_way(self):
        """Переезд на другую полку не меняет знаменателя — оба сообщения с вариантами."""
        self.assertEqual(self._scan_live()["with_choice"], 2)


class SummaryLineSaysBoth(unittest.TestCase):
    """Строка шага 0-офис: тревога — про незакрытые, ремонт — назван отдельно."""

    def test_alarm_headline_counts_only_the_unrepaired(self):
        line = summary_line(scan([_channel(), _channel(message_id=8955)],
                                 pushes=[_push()]))
        self.assertIn("КНОПОК НЕТ у 1 ", line)
        self.assertNotIn("КНОПОК НЕТ у 2 ", line)

    def test_repair_is_named_next_to_the_alarm_with_the_wait(self):
        line = summary_line(scan([_channel(), _channel(message_id=8955)],
                                 pushes=[_push()]))
        self.assertIn("досланы вдогонку: 1", line)
        self.assertIn("1.92", line)

    def test_all_repaired_is_not_reported_as_all_with_buttons(self):
        """Единственная находка починена: «все с кнопками» здесь было бы неправдой."""
        line = summary_line(scan([_channel()], pushes=[_push()]))
        self.assertNotIn("⚠️", line)
        self.assertNotIn("все с кнопками", line)
        self.assertIn("досланы вдогонку: 1", line)

    def test_clean_channel_still_reads_clean(self):
        """Обратный контроль: где ремонта не было вовсе, строка прежняя."""
        line = summary_line(scan([_channel(buttons=True)], pushes=[_push()]))
        self.assertIn("все с кнопками", line)
        self.assertNotIn("досланы вдогонку", line)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
