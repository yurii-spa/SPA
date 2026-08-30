#!/usr/bin/env python3
"""Сторож журнала отправок называет ФАКТ, а лекарство — только в своём домене.

Авария, которую воспроизводит каждый тест (замер шага 0-офис 30.08, цикл #433)
------------------------------------------------------------------------------
ADR-177 снял ложный диагноз у `buttonless_reason`: многовыборная карточка больше не
объявляется дефектом разбора. Тот же корень остался во ВТОРОЙ двери — у
`buttonless_audit`, который судит ЖУРНАЛ ОТПРАВОК и тела карточки не читает по
построению. Его текст `own_door_no_options` кончался словами «— чинить РАЗБОР
карточки».

Замер на живом отчёте `data/owner_decision_pending.json` (30.08 11:36Z), карточка
`owner-decision-storozh-vspleskov-apy-nikto-ne-zovet-2026-08-29`. Два вердикта об
ОДНОЙ карточке в ОДНОМ отчёте говорили противоположное:

* `buttonless_audit`  → «наша дверь, вариантов в журнале нет — чинить РАЗБОР карточки»;
* `buttonless_reason` → `multiselect_card`, лекарство «разбор НЕ трогать: он отказывает
  верно — одна кнопка не выражает ответ «1 и 3»».

Первый звал следующую сессию сломать ровно тот отказ, который второй объявил верным.
Права назначать это лекарство у первого нет: ПОЧЕМУ вариантов не собралось, решается
по ТЕЛУ карточки, которого он не читает.

Что здесь закреплено (ADR-178, вариант 1 карточки
`inbox-vtoroi-storozh-knopok-povtoryaet-diagnoz`):

1. `own_door_no_options` говорит только измеренное и НЕ назначает чинить разбор;
2. храповик: ни один текст `_JOIN_TEXT` не зовёт чинить разбор;
3. лекарства, которые этот модуль устанавливает СВОИМ измерением, не тронуты —
   иначе «убрали лишнее» незаметно превратилось бы в «обеднили все находки»;
4. обратный контроль: настоящий дефект разбора по-прежнему называется своим именем
   у `buttonless_reason` и по-прежнему зовёт к `parse_options`. Новый текст гасит
   ложный призыв, а не настоящую находку.

LLM_FORBIDDEN. Только stdlib + pytest.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spa_core.telegram import buttonless_audit as ba
from spa_core.telegram import buttonless_reason as br

# Форма живой записи канала и живой записи журнала отправок (сверено с
# `data/alert_history.json` / `data/telegram_owner_decisions.json` 30.08): сообщение
# доставлено, выбор предлагало, кнопок не несло, а в журнале у той же `message_id`
# вариантов нет.
LIVE_CARD = "owner-decision-storozh-vspleskov-apy-nikto-ne-zovet-2026-08-29"
CHANNEL_ENTRY = {
    "ok": True,
    "offers_choice": True,
    "buttons": False,
    "message_id": 9311,
    "ts": "2026-08-30T00:38:51.290843+00:00",
    "preview": "🧑‍⚖️ <b>Нужно твоё решение</b>",
}
PUSH_RECORD = {"message_ids": [9311], "card_id": LIVE_CARD, "buttons": False}

# Перечень, форму которого разбор НЕ знает (тире вместо «Вариант N»): состояние, которое
# ДЕЙСТВИТЕЛЬНО лечится разбором. Взято из `test_multi_question_card.py`, чтобы обратный
# контроль стоял на уже проверенном образце, а не на выдуманном.
CARD_UNKNOWN_FORM = """---
title: "Судьба воронки чекапа"
---

## Что от тебя нужно

Варианты:

— похоронить чекап (рекомендую);
— воскресить чекап.
"""


class OwnDoorTextStatesTheFact(unittest.TestCase):
    """Текст `own_door_no_options` — измерение, а не назначение."""

    def test_text_does_not_prescribe_fixing_the_parse(self):
        # Код сверяем СТРОКОЙ, а не только константой: так тест краснеет по
        # ПОВЕДЕНИЮ (в тексте стоит призыв), а не по отсутствию имени.
        self.assertEqual(ba.JOIN_OWN_NO_OPTIONS, "own_door_no_options")
        text = ba._JOIN_TEXT[ba.JOIN_OWN_NO_OPTIONS]
        self.assertNotIn("чинить РАЗБОР", text)
        self.assertNotIn("чинить разбор", text.lower().replace("РАЗБОР", "разбор"))

    def test_text_keeps_the_measured_fact(self):
        """Убрать лекарство — не то же самое, что обеднить находку."""
        text = ba._JOIN_TEXT[ba.JOIN_OWN_NO_OPTIONS]
        self.assertIn("наша дверь", text)
        self.assertIn("вариантов в журнале нет", text)

    def test_reader_is_sent_to_the_guard_that_may_judge(self):
        """Читатель не остаётся без адреса: причину знает тот, кто читает тело."""
        self.assertIn("buttonless_reason", ba._JOIN_TEXT[ba.JOIN_OWN_NO_OPTIONS])


class NoTextPrescribesTheParse(unittest.TestCase):
    """Храповик на весь словарь: класс не возвращается через соседний код."""

    def test_no_join_text_calls_to_fix_the_parse(self):
        offenders = [code for code, text in ba._JOIN_TEXT.items()
                     if "чинить разбор" in text.lower()]
        self.assertEqual(offenders, [],
                         "лекарство «чинить разбор» назначается по ТЕЛУ карточки, "
                         "которого этот модуль не читает")


class RemediesInsideOwnDomainSurvive(unittest.TestCase):
    """Обратный контроль на саму починку: лишнее убрано, нужное осталось.

    Без этого класса «снять лекарство» могло бы тихо стать «снять все лекарства»:
    строка про спор двух НАШИХ записей и строка про чужого отправителя опираются на
    измерение самого модуля и обязаны продолжать называть работу.
    """

    def test_contradiction_between_our_own_records_still_names_the_path(self):
        text = ba._JOIN_TEXT[ba.JOIN_OWN_CONTRADICTS]
        self.assertIn("чинить путь", text)

    def test_other_sender_still_sends_the_reader_after_the_sender(self):
        text = ba._JOIN_TEXT[ba.JOIN_OTHER_SENDER]
        self.assertIn("искать отправителя", text)


class OfficeLineOnTheLiveShape(unittest.TestCase):
    """Сквозь `scan` + `summary_line` — ровно та строка, что печатает шаг 0-офис."""

    def _line(self) -> str:
        report = ba.scan([dict(CHANNEL_ENTRY)], pushes=[dict(PUSH_RECORD)])
        return ba.summary_line(report)

    def test_cause_is_own_door_no_options(self):
        report = ba.scan([dict(CHANNEL_ENTRY)], pushes=[dict(PUSH_RECORD)])
        self.assertEqual(report["buttonless_count"], 1)
        cause = report["buttonless"][0]["cause"]
        self.assertEqual(cause["code"], "own_door_no_options")
        self.assertEqual(cause["card_id"], LIVE_CARD)

    def test_office_line_no_longer_calls_to_fix_the_parse(self):
        line = self._line()
        self.assertIn("КНОПОК НЕТ", line)
        self.assertIn(LIVE_CARD, line, "карточку по-прежнему называем поимённо")
        self.assertNotIn("чинить РАЗБОР", line)


class RealParseDefectKeepsItsName(unittest.TestCase):
    """Обратный контроль: там, где разбор ВИНОВАТ, его по-прежнему зовут чинить.

    Судит `buttonless_reason` — тот, у кого для этого есть тело карточки. Сверку с ref
    подменяем на единственной двери к git (`_origin_body`): живой `git show` означал бы,
    что вердикт зависит от состояния очереди, а проверяем мы разбор тела.
    """

    def _explain(self, body: str) -> br.Reason:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "own-tema.md"
            path.write_text(body, encoding="utf-8")
            with mock.patch.object(br, "_origin_body",
                                   return_value=(body, "deadbeef0")):
                return br.explain(path, ref="origin/main")

    def test_unknown_form_is_still_our_parse_defect(self):
        reason = self._explain(CARD_UNKNOWN_FORM)
        self.assertEqual(reason.code, "unreadable_options_in_card")
        self.assertIn("parse_options", reason.remedy)


if __name__ == "__main__":
    unittest.main()
