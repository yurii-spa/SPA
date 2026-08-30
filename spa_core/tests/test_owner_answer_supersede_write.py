#!/usr/bin/env python3
"""Писатель ответа владельца ЗАПИСЫВАЕТ вытеснение, которое сам же и производит (ADR-180).

Каждый тест — положительный контроль настоящей аварии, а не украшение.

**Авария.** Прод-дерево, карточка `owner-decision-mandat-samostoyatelnoi-raboty-konchaetsy`,
19.08: владелец нажал **вариант 1 в 21:52:36.7**, затем **вариант 3 в 21:52:40.2** — 3.5
секунды, один канал, один бот (промах пальцем и поправка). `record_owner_answer` затёр
`owner_choice: 1` на `3`, и первый ответ перестал существовать для КАЖДОГО машинного
читателя следа: в теле остались обе секции «Решение владельца», во frontmatter — только
последняя.

**Почему это не мелочь.** У сторожа доставки (`owner_answer_delivery`, ADR-163) есть третий
исход `superseded` — «расхождение уже разобрано, вот вытесненный ответ поимённо». Регистр
`owner_choice_superseded` / `_at` / `_via` ЧИТАЛСЯ и не писался НИКЕМ. ADR-163 объяснил это
так: «бот вытеснения не наблюдает — он видит только свой канал». Довод верен для
МЕЖканального вытеснения (ответ интерактивной сессии боту не виден) и неверен ровно для
случая, который бот производит САМ: старое значение у него в руках — строкой выше он
читает его для проверки идемпотентности.

Время — ВХОД: часы инъектируются (`now=`), отметки в фикстурах закреплены. Календарь ни на
один тест здесь не влияет.
"""
# FROZEN-DATE-OK: injected-clock — часы приходят входом (`now=`), а литеральные отметки суть
# ЗНАЧЕНИЯ следа ответа владельца, которые регистр вытеснения обязан назвать дословно. Ни
# одна проверка не сравнивает их с текущей датой.
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import owner_answer_delivery as oad
from spa_core.owner_queue import owner_answer as oa

OWNER = "258651137"

#: Моменты нажатий из аварии 19.08 — предмет проверки, а не «сегодня».
FIRST_PRESS = datetime(2026, 8, 19, 21, 52, 36, 704276, tzinfo=timezone.utc)
SECOND_PRESS = datetime(2026, 8, 19, 21, 52, 40, 210211, tzinfo=timezone.utc)
THIRD_PRESS = datetime(2026, 8, 19, 21, 53, 1, 55000, tzinfo=timezone.utc)

CARD = """---
trackerStatus:
  type: owner-decision
title: Мандат самостоятельной работы кончается сегодня — продлеваем, сужаем или закрываем?
status: needs-owner
created: 2026-08-19
owner_choice: ""
---

## Что от тебя нужно

**Вариант 1 — Продлить мандат в прежних границах ещё на две недели.**

**Вариант 2 — Сузить мандат.**

**Вариант 3 — Мандат кончился, продлевать не нужно.**
"""


#: Копия на origin: следа ответа там НЕТ ВОВСЕ — это измеренная норма (ADR-086: поля
#: ответа рождаются в прод-дереве и в git не уезжают), а НЕ пустой скаляр. Пустую строку
#: перенос отказывается дополнять по отдельной причине (ADR-176), и брать её фикстурой
#: значило бы мерить не то.
ORIGIN_CARD = "".join(ln for ln in CARD.splitlines(True)
                      if not ln.startswith("owner_choice:")).encode("utf-8")


def _card(tmp: str, text: str = CARD) -> Path:
    p = Path(tmp, "owner-decision-mandat-samostoyatelnoi-raboty-konchaetsy.md")
    p.write_text(text, encoding="utf-8")
    return p


def _press(path: Path, choice: str, label: str, when: datetime) -> dict:
    return oa.record_owner_answer(path, choice_num=choice, choice_label=label,
                                  actor_chat_id=OWNER, owner_chat_id=OWNER, now=when)


def _fm(path: Path) -> dict:
    from spa_core.owner_queue.queue import _parse_frontmatter, _split_frontmatter

    return _parse_frontmatter(_split_frontmatter(path.read_text(encoding="utf-8"))[0])


class SupersedeIsRecorded(unittest.TestCase):
    """Авария 19.08 дословно: второе нажатие обязано НАЗВАТЬ вытесненный ответ."""

    def test_second_press_records_the_answer_it_overwrites(self):
        with TemporaryDirectory() as tmp:
            p = _card(tmp)
            _press(p, "1", "Продлить мандат", FIRST_PRESS)
            r = _press(p, "3", "Мандат кончился", SECOND_PRESS)

            fm = _fm(p)
            self.assertEqual(fm["owner_choice"], "3", "новый ответ обязан быть записан")
            self.assertEqual(fm["owner_choice_superseded"], "1",
                             "вытесненный ответ владельца обязан быть НАЗВАН, а не стёрт")
            self.assertEqual(fm["owner_choice_superseded_at"], FIRST_PRESS.isoformat(),
                             "вытеснена конкретная запись — с её собственной отметкой")
            self.assertEqual(fm["owner_choice_superseded_via"], "telegram")
            self.assertEqual(r["superseded"]["owner_choice_superseded"], "1",
                             "вызывающий обязан узнать о вытеснении из возврата, не из файла")

    def test_body_keeps_every_answer_section(self):
        """Проза остаётся полной: регистр — не замена рассказу, а его машинная половина.

        Регистр скалярный и называет НЕПОСРЕДСТВЕННО вытесненный ответ; вся цепочка
        нажатий живёт в теле, и поэтому секции «Решение владельца» не схлопываются.
        """
        with TemporaryDirectory() as tmp:
            p = _card(tmp)
            _press(p, "1", "Продлить мандат", FIRST_PRESS)
            _press(p, "3", "Мандат кончился", SECOND_PRESS)
            self.assertEqual(p.read_text(encoding="utf-8").count(oa.ANSWER_HEADING), 2)

    def test_third_press_names_the_second_not_the_first(self):
        """Регистр называет ИМЕННО вытесненный сейчас ответ, а не первый из цепочки."""
        with TemporaryDirectory() as tmp:
            p = _card(tmp)
            _press(p, "1", "Продлить мандат", FIRST_PRESS)
            _press(p, "3", "Мандат кончился", SECOND_PRESS)
            _press(p, "2", "Сузить мандат", THIRD_PRESS)

            fm = _fm(p)
            self.assertEqual(fm["owner_choice"], "2")
            self.assertEqual(fm["owner_choice_superseded"], "3")
            self.assertEqual(fm["owner_choice_superseded_at"], SECOND_PRESS.isoformat())
            self.assertEqual(p.read_text(encoding="utf-8").count(oa.ANSWER_HEADING), 3)


class SupersedeIsNotInvented(unittest.TestCase):
    """Обратные контроли: регистр НЕ пишется там, где вытеснять нечего."""

    def test_first_answer_writes_no_register(self):
        """Пустой скаляр — ОТСУТСТВИЕ ответа, а не ответ со значением «пусто»."""
        with TemporaryDirectory() as tmp:
            p = _card(tmp)
            _press(p, "1", "Продлить мандат", FIRST_PRESS)
            text = p.read_text(encoding="utf-8")
            self.assertNotIn("owner_choice_superseded", text,
                             "первый ответ ничего не вытесняет — регистра быть не должно")

    def test_every_empty_scalar_spelling_is_absence(self):
        """Ни одно написание пустоты не имеет права стать «вытесненным ответом»."""
        for empty in oa.EMPTY_SCALARS:
            with self.subTest(empty=empty), TemporaryDirectory() as tmp:
                p = _card(tmp, CARD.replace('owner_choice: ""', f"owner_choice: {empty}"))
                _press(p, "1", "Продлить мандат", FIRST_PRESS)
                self.assertNotIn("owner_choice_superseded", p.read_text(encoding="utf-8"),
                                 f"{empty!r} — это «ответа нет», вытеснять нечего")

    def test_same_choice_pressed_twice_changes_nothing(self):
        """Идемпотентность ADR-075 не тронута: тот же вариант из двух чатов — один ответ."""
        with TemporaryDirectory() as tmp:
            p = _card(tmp)
            _press(p, "1", "Продлить мандат", FIRST_PRESS)
            before = p.read_text(encoding="utf-8")
            r = _press(p, "1", "Продлить мандат", SECOND_PRESS)
            self.assertTrue(r["already"])
            self.assertEqual(p.read_text(encoding="utf-8"), before,
                             "повторное то же нажатие не имеет права ничего переписать")

    def test_provenance_is_never_fabricated(self):
        """Отвеченная РУКАМИ карточка не получает выдуманных отметки и канала.

        Неполный регистр — честный вход для сторожа: `clash_superseded` читает его как
        «покрыто частично» и по-прежнему зовёт человека (fail-CLOSED). Дописать сюда
        сегодняшний момент значило бы приписать вытесненному ответу время, которого у
        него не было.
        """
        with TemporaryDirectory() as tmp:
            p = _card(tmp, CARD.replace('owner_choice: ""', "owner_choice: 1"))
            _press(p, "3", "Мандат кончился", SECOND_PRESS)

            fm = _fm(p)
            self.assertEqual(fm["owner_choice_superseded"], "1")
            self.assertNotIn("owner_choice_superseded_at", fm,
                             "отметки у вытесненного ответа не было — выдумывать её нельзя")
            self.assertNotIn("owner_choice_superseded_via", fm)

    def test_provenance_without_a_choice_is_not_a_register(self):
        """Провенанс без решения не называет вытесненный ОТВЕТ — регистра нет вовсе."""
        with TemporaryDirectory() as tmp:
            p = _card(tmp, CARD.replace(
                'owner_choice: ""',
                'owner_choice: ""\nowner_answered_at: 2026-08-19T21:52:36.704276+00:00\n'
                "owner_answer_via: telegram"))
            _press(p, "3", "Мандат кончился", SECOND_PRESS)
            self.assertNotIn("owner_choice_superseded", p.read_text(encoding="utf-8"))


class WriterAndReaderAgree(unittest.TestCase):
    """ПРОВОДКА: то, что пишет бот, сторож доставки обязан прочитать как `superseded`.

    Проверяется не имя поля, а СМЫКАНИЕ двух половин на форме живой аварии: нажатия
    идут подряд (3.5 с), доставки между ними не было, поэтому на origin след уезжает
    уже вместе с регистром — и следующая копия, застрявшая на вытесненном ответе,
    перестаёт быть «⛔ два разных ответа владельца».
    """

    def test_carried_trace_makes_a_stale_copy_read_as_superseded(self):
        with TemporaryDirectory() as tmp:
            prod = _card(tmp)
            _press(prod, "1", "Продлить мандат", FIRST_PRESS)
            stale = Path(tmp, "stale.md")            # копия, застрявшая на первом ответе
            stale.write_text(prod.read_text(encoding="utf-8"), encoding="utf-8")

            _press(prod, "3", "Мандат кончился", SECOND_PRESS)

            # 1. след (вместе с регистром) уезжает на origin обычным переносом
            origin = ORIGIN_CARD
            merged, why, added = oad.merge_trace(prod.read_bytes(), origin)
            self.assertIsNotNone(merged, f"перенос обязан состояться, а сказал: {why}")
            self.assertIn("owner_choice_superseded", added,
                          "регистр обязан уехать вместе со следом, иначе сторож слеп")

            # 2. отставшая копия против origin — третий исход, а не вызов человека
            _, why2, _ = oad.merge_trace(stale.read_bytes(), merged)
            self.assertIn(oad.SUPERSEDED_MARK, why2, why2)
            self.assertNotIn("ДРУГОЙ ответ владельца", why2)

    def test_without_the_register_the_same_state_calls_a_human(self):
        """Обратный контроль: снимите регистр — и сторож обязан снова звать человека."""
        with TemporaryDirectory() as tmp:
            prod = _card(tmp)
            _press(prod, "1", "Продлить мандат", FIRST_PRESS)
            stale = Path(tmp, "stale.md")
            stale.write_text(prod.read_text(encoding="utf-8"), encoding="utf-8")
            _press(prod, "3", "Мандат кончился", SECOND_PRESS)

            stripped = "".join(ln for ln in prod.read_text(encoding="utf-8").splitlines(True)
                               if not ln.startswith("owner_choice_superseded"))
            merged, _, _ = oad.merge_trace(stripped.encode("utf-8"), ORIGIN_CARD)
            _, why, _ = oad.merge_trace(stale.read_bytes(), merged)
            self.assertIn("ДРУГОЙ ответ владельца", why, why)
            self.assertNotIn(oad.SUPERSEDED_MARK, why)


    def test_register_written_empty_on_origin_refuses_instead_of_duplicating(self):
        """Fail-CLOSED ADR-176 обязан покрывать и регистр, а не только поля ответа.

        Строка ``owner_choice_superseded: ""`` физически есть на origin ⇒ дописать рядом
        вторую с тем же ключом значит сделать frontmatter противоречивым: читатель берёт
        ПЕРВОЕ вхождение, и вытеснение уехало бы в git невидимым. Проверка обязана
        спрашивать про ТЕ ключи, которые дописываются, — иначе она покрывает только
        половину, которую помнила, когда её писали.
        """
        with TemporaryDirectory() as tmp:
            prod = _card(tmp)
            _press(prod, "1", "Продлить мандат", FIRST_PRESS)
            _press(prod, "3", "Мандат кончился", SECOND_PRESS)

            origin = ORIGIN_CARD.replace(b"created: 2026-08-19\n",
                                         b'created: 2026-08-19\nowner_choice_superseded: ""\n')
            merged, why, _ = oad.merge_trace(prod.read_bytes(), origin)
            self.assertIsNone(merged, "дописывать второй ключ рядом с пустым запрещено")
            self.assertIn("owner_choice_superseded", why, why)


class OneVocabularyForBothHalves(unittest.TestCase):
    """Имена полей и написания пустоты объявлены ОДИН раз (ADR-163: «другое имя — сторож слеп»)."""

    def test_guard_and_writer_share_the_very_same_objects(self):
        self.assertIs(oad.SUPERSEDED_FIELDS, oa.SUPERSEDED_FIELDS)
        self.assertIs(oad.EMPTY_SCALARS, oa.EMPTY_SCALARS)


if __name__ == "__main__":
    unittest.main()
