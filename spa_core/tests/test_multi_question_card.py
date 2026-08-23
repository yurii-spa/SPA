#!/usr/bin/env python3
"""Карточка с НЕСКОЛЬКИМИ вопросами — состояние, а не безымянный отказ разбора.

Авария, которую воспроизводит каждый тест (замер цикла #359, 23.08)
------------------------------------------------------------------------------
`owner-decision-vnutridnevnaya-prosadka-slepota-teper-sl` (`needs-owner` с 18.08,
доставлена владельцу 23.08 14:40Z) задаёт ПЯТЬ независимых вопросов. `parse_options`
отказался собирать кнопки — и это ВЕРНО: нажатие «1» закрывает карточку целиком, а
четыре оставшихся вопроса умирают молча. Но снаружи отказ был безымянным, и оба
читателя вывели из него неправду:

* владельцу ушло «⚠️ Варианты в карточке есть, но я не смог собрать из них кнопки…
  **заведи мне это как дефект**» — просьба оформить наш дефект там, где дефекта нет;
* сторож `buttonless_reason` назвал причину `unreadable_options_in_card` с лекарством
  «научить `parse_options` этой форме».

Второе опаснее первого: выучить форму значит собрать пять кнопок, первая из которых
закрывает карточку с четырьмя открытыми вопросами. То есть отчёт звал следующую сессию
починить работающий отказ — сломав его. Настоящее лекарство названо в классовой карточке
`inbox-vopros-s-dvumya-resheniyami-nechem-otvet` (вариант 1) и уже проверено на живой
карточке `own-rnd-killswitch-rearm-policy-missing`: карточку ДЕЛЯТ на отдельные вопросы,
и кнопки собираются штатным путём.

Обратные контроли здесь обязательны и их четыре: карточка с настоящими вариантами ·
карточка-поручение без выбора · многовыборная карточка (`allows_multiple` — своё,
давно названное состояние) · карточка с НЕИЗВЕСТНОЙ разбору формой перечня (у неё
диагноз «мой дефект разбора» обязан остаться прежним). Без них признак «несколько
вопросов» тихо съел бы соседние состояния и погасил настоящий дефект разбора.

LLM_FORBIDDEN. Только stdlib + pytest.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spa_core.telegram import buttonless_audit, buttonless_reason
from spa_core.telegram import owner_decisions as od

# ── фикстуры ─────────────────────────────────────────────────────────────────
#
# Тело живой карточки приведено СЛОВО В СЛОВО в части, которую читает разбор (секция
# «Что от тебя нужно»), — иначе тест проверял бы выдуманный образец. Живой файл трекера
# при этом НЕ читается: очередь дрейфует, а тест обязан судить о коде.

CARD_FIVE_QUESTIONS = """---
title: "Внутридневная просадка: слепота теперь слышна"
status: needs-owner
---

## Что случилось и почему это важно

Внутридневной контроль просадки (ADR-068) уже построен и считает честно.

## Что от тебя нужно

Решить по каждому пункту (моя рекомендация приведена):

1. **Мягкий тир (просадка 5–10%) внутри дня сейчас только записывается.** Остановка новых
   покупок происходит лишь на следующем суточном цикле — до 24 часов спустя.
   *Рекомендация:* к go-live мягкий тир тоже должен действовать в течение минут.

2. **Когда просадку вычислить НЕ ИЗ ЧЕГО, суточная проверка пишет «мягкой остановки не требуется».**
   *Рекомендация:* при невычислимой просадке запрещать НАРАЩИВАНИЕ.

3. **Сколько минут слепоты — уже тревога?** Правила «молчит N минут → будить владельца» нет.
   *Рекомендация:* 30 минут подряд «НЕ ИЗМЕРЕНО» → сообщение в Telegram.

4. **На реальных деньгах живым входом остаётся только отклонение стейблов от доллара.**
   Позиции берутся из последнего суточного цикла, цен активов сенсор не видит. Для стейбл-книги
   этого достаточно, для любой нестейбл-экспозиции — нет.
   *Рекомендация:* до cutover либо ограничить книгу стейблами, либо завести живой источник
   оценки позиций (отдельная задача, оценю после твоего ответа).

5. **Установка/перезапуск агента в проде — твоё действие.** Я ничего в прод-дереве не двигал.

## Как понять, что готово

По каждому из пунктов 1–4 есть твой ответ.
"""

#: Два перечня в одной карточке: номер «1» повторяется. Отказ существовал и до #359 —
#: у него не было имени.
CARD_TWO_LISTS = """---
title: "Две развилки в одной карточке"
---

## Что от тебя нужно

**Решение 1 — что делать с кэшем.**

1. Оставить как есть.
2. Разместить в T1.

**Решение 2 — что делать с фидом.**

1. Чинить сейчас.
2. Отложить до go-live.
"""

#: Составная метка: семьи «А» и «Б» — два решения, пять вариантов, дубля номера нет.
CARD_TWO_FAMILIES = """---
title: "Политика возврата и смысл мягкой ступени"
---

## Что от тебя нужно

- **Вариант А1 — снятие за владельцем, но с обязательным сроком.**
- **Вариант А2 — автоматический возврат через N дней восстановления.**
- **Вариант Б1 — мягкая ступень запрещает наращивание.**
- **Вариант Б2 — мягкая ступень только записывается.**
"""

#: Обратный контроль: настоящий выбор одного решения.
CARD_REAL_CHOICE = """---
title: "Оживить фиды вне Ethereum"
---

## Что от тебя нужно

- **Вариант 1 (рекомендация агента) — оживить фиды вне Ethereum.** Кэш встанет в работу.
- **Вариант 2 — оставить кэш на месте.** Доходность ниже, зато ничего не трогаем.
"""

#: Обратный контроль: поручение, выбора нет вовсе.
CARD_NO_CHOICE = """---
title: "Добавить ключ Etherscan на сервер"
---

## Что от тебя нужно

Зайти в панель Railway и добавить переменную `ETHERSCAN_API_KEY` — без неё не работает
проверка кошельков.
"""

#: Обратный контроль: многовыборная карточка — своё состояние со своим текстом.
CARD_MULTISELECT = """---
title: "Что чиним первым"
---

## Что от тебя нужно

Выбери, как поступаем — можно взять несколько:

- **Вариант 1 — починить сторожа.**
- **Вариант 2 — переустановить агента.**
"""

#: Обратный контроль: форма перечня разбору НЕИЗВЕСТНА (выбор написан, кнопок нет).
#: Диагноз «мой дефект разбора» обязан остаться ровно таким — иначе новый признак
#: погасил бы настоящий дефект.
CARD_UNKNOWN_FORM = """---
title: "Судьба воронки чекапа"
---

## Что от тебя нужно

Варианты:

— похоронить чекап (рекомендую);
— воскресить чекап.
"""


class MultiQuestionDetection(unittest.TestCase):
    """Признак измеряет СОСТОЯНИЕ, а не одну выученную форму."""

    def test_five_questions_named_with_count(self):
        """Живая карточка 18.08: пять вопросов, отказ верен, причина НАЗВАНА."""
        self.assertEqual(od.parse_options(CARD_FIVE_QUESTIONS), [],
                         "отказ обязан остаться: одно нажатие похоронило бы 4 вопроса")
        mq = od.multi_question(CARD_FIVE_QUESTIONS)
        self.assertIsNotNone(mq, "состояние «вопросов несколько» обязано иметь имя")
        self.assertEqual(mq.code, od.MQ_QUESTION_ITEMS)
        self.assertEqual(mq.count, 5, "число вопросов измеряется, а не описывается словом")

    def test_duplicate_number_is_named(self):
        self.assertEqual(od.parse_options(CARD_TWO_LISTS), [])
        mq = od.multi_question(CARD_TWO_LISTS)
        self.assertIsNotNone(mq)
        self.assertEqual(mq.code, od.MQ_DUPLICATE_NUMBER)

    def test_mixed_families_are_named(self):
        self.assertEqual(od.parse_options(CARD_TWO_FAMILIES), [])
        mq = od.multi_question(CARD_TWO_FAMILIES)
        self.assertIsNotNone(mq)
        self.assertEqual(mq.code, od.MQ_MIXED_FAMILIES)

    def test_real_choice_is_not_multi_question(self):
        """Обратный контроль: у настоящего выбора признак молчит, кнопки остаются."""
        self.assertEqual(len(od.parse_options(CARD_REAL_CHOICE)), 2)
        self.assertIsNone(od.multi_question(CARD_REAL_CHOICE))

    def test_instruction_card_is_not_multi_question(self):
        """Обратный контроль: «выбора нет» ≠ «вопросов несколько»."""
        self.assertEqual(od.parse_options(CARD_NO_CHOICE), [])
        self.assertIsNone(od.multi_question(CARD_NO_CHOICE))

    def test_multiselect_keeps_its_own_state(self):
        """Обратный контроль: многовыборная карточка названа СВОИМ именем, не новым."""
        self.assertTrue(od.allows_multiple(CARD_MULTISELECT))
        self.assertEqual(od.parse_options(CARD_MULTISELECT), [])
        self.assertIsNone(od.multi_question(CARD_MULTISELECT),
                          "«ответов можно несколько» — это ОДИН вопрос")

    def test_unknown_form_stays_a_parser_defect(self):
        """Обратный контроль: неизвестная форма перечня — по-прежнему НАШ дефект."""
        self.assertEqual(od.parse_options(CARD_UNKNOWN_FORM), [])
        self.assertIsNone(od.multi_question(CARD_UNKNOWN_FORM))
        self.assertTrue(od.has_unparsed_options(CARD_UNKNOWN_FORM))


class MessageToOwner(unittest.TestCase):
    """Что читает владелец. Текст и состояние обязаны говорить ОДНО."""

    def _text(self, body: str) -> str:
        return od.build_message("Заголовок", body, od.parse_options(body),
                                card_name="карточка.md")

    def test_owner_is_not_asked_to_file_our_defect(self):
        """Ушедшее 23.08 14:40Z «заведи мне это как дефект» — на многовопросной карточке
        неправда: дефекта нет, отказ верен."""
        text = self._text(CARD_FIVE_QUESTIONS)
        self.assertNotIn("заведи мне это как дефект", text)
        self.assertNotIn("не смог собрать из них кнопки", text)

    def test_owner_is_told_the_real_state_and_who_fixes_it(self):
        text = self._text(CARD_FIVE_QUESTIONS)
        self.assertIn("5 отдельных вопросов", text)
        self.assertIn("не варианты одного решения", text)
        self.assertIn("Разделить вопрос на отдельные карточки", text,
                      "лечение — наша работа, и это обязано быть сказано владельцу")

    def test_unknown_form_still_asks_for_a_defect(self):
        """Обратный контроль: там, где дефект РЕАЛЬНО наш, просьба остаётся."""
        text = self._text(CARD_UNKNOWN_FORM)
        self.assertIn("не смог собрать из них кнопки", text)

    def test_multiselect_text_unchanged(self):
        """Обратный контроль: многовыборной карточке достаётся её прежний текст."""
        text = self._text(CARD_MULTISELECT)
        self.assertIn("можно выбрать НЕСКОЛЬКО пунктов", text)
        self.assertNotIn("отдельных вопросов", text)

    def test_channel_audit_still_sees_a_choice(self):
        """Сторож канала обязан ВИДЕТЬ такое сообщение: владелец не может ответить
        нажатием, и это настоящая цена. Переписать текст мимо сторожа = сделать отчёт
        зеленее, ничего не починив."""
        self.assertTrue(buttonless_audit.offers_choice(self._text(CARD_FIVE_QUESTIONS)))


class ReasonForTheGuard(unittest.TestCase):
    """Что читает сторож и КУДА он посылает следующую сессию."""

    def _explain(self, body: str) -> buttonless_reason.Reason:
        """Сторож на карточке, у которой дерево и `origin` СОВПАДАЮТ.

        Сверку с ref подменяем на уровне единственной двери к git (`_origin_body`):
        живой `git show` в тесте означал бы, что вердикт зависит от состояния очереди,
        а проверяем мы разбор тела. Ветка «дерево отстало от origin» проверена своим
        тестом в `test_buttonless_reason.py` и здесь не дублируется.
        """
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "own-tema.md"
            path.write_text(body, encoding="utf-8")
            with mock.patch.object(buttonless_reason, "_origin_body",
                                   return_value=(body, "deadbeef0")):
                return buttonless_reason.explain(path, ref="origin/main")

    def test_multi_question_gets_its_own_code_and_remedy(self):
        # Код сверяем СТРОКОЙ, а не константой модуля: на неисправленном origin
        # константы нет вовсе, и тест краснел бы «нет атрибута» — то есть по
        # ПОДГОТОВКЕ. Со строкой он краснеет по ПОВЕДЕНИЮ
        # ('unreadable_options_in_card' != 'multi_question_card') — ровно тем
        # вердиктом, который сторож выдал на живой карточке 23.08.
        reason = self._explain(CARD_FIVE_QUESTIONS)
        self.assertEqual(reason.code, "multi_question_card")
        self.assertEqual(buttonless_reason.CODE_MULTI_QUESTION, "multi_question_card")
        self.assertTrue(reason.measured)
        self.assertIn("разделить карточку", reason.remedy.lower())
        self.assertNotIn("научить `parse_options`", reason.remedy,
                         "звать чинить работающий отказ значит звать его сломать")

    def test_unknown_form_still_points_at_the_parser(self):
        """Обратный контроль: настоящий дефект разбора не переименован."""
        reason = self._explain(CARD_UNKNOWN_FORM)
        self.assertEqual(reason.code, "unreadable_options_in_card")


if __name__ == "__main__":
    unittest.main()
