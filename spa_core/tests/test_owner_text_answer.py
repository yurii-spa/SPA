#!/usr/bin/env python3
"""Владелец отвечает на карточку решения ТЕКСТОМ — потому что мы сами его об этом просим.

Когда кнопок нет, ``owner_decisions.build_message`` пишет владельцу дословно:
«⚠️ Кнопки сейчас недоступны … **Ответь номером варианта в чат, я разберу.**»
Разбирать было НЕЧЕМ: ни одна строка кода не читала текстовый ответ. Сообщение уходило в
общий классификатор — и решение владельца становилось обычной inbox-задачей, которую никто
не исполнял.

Каждый тест здесь — положительный контроль над РЕАЛЬНЫМ прод-событием:

* **12.08** — владелец прислал процитированную тревогу и строку «Ответ 1». Карточки
  ``owner-decision-sait-packages-astro-avtonomnaya-pravka-z`` нет ни в трекере, ни в
  журнале отправок: ответ применять НЕ К ЧЕМУ. Родилась карточка
  ``inbox-zadacha-i-otvet-nuzhno-tvoe-reshenie`` — и тишина.
* **10.08** — владелец прислал ЗАДАЧУ («присылать не просто "нужно твоё решение", а и
  кнопки»), процитировав ту же тревогу. Ответом это не является, и разбираться обязано
  как раньше: обратный контроль против захвата обычной речи.
* оба раза дефект молчал, поэтому здесь проверяется ЭФФЕКТ (что записано в карточке, что
  увидел владелец, вызван ли обычный классификатор), а не возвращаемое значение.

Инвариант #14 не ослаблен ни на строку: запись идёт единственным owner-путём
``record_owner_answer`` со сверкой личности ВНУТРИ писателя — чужой «Ответ 1» отклоняется.

Сети и живого Телеграма здесь нет. Время — вход, а не окружение.
"""
from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from spa_core.owner_queue.owner_answer import ANSWER_HEADING
from spa_core.telegram import bot as B
from spa_core.telegram import owner_decisions as od
from spa_core.tests._freshness import now_utc

NOW = now_utc()
OWNER = "42"
STRANGER = "987654321"

CARD = """---
trackerStatus:
  type: owner-decision
title: "Сайт: автономная правка задела owner-gated область"
status: needs-owner
---

## Что случилось и почему это важно

Автономный оркестратор хотел изменить публичный сайт, но правка задевает owner-gated
область. Такое не уезжает в live само — только с твоего одобрения (инвариант #8).

## Что от тебя нужно

Посмотри изменение и выбери:

* **Вариант 1 — одобрить.** Правка уезжает в live как есть.
* **Вариант 2 (рекомендую) — отклонить.** Оркестратор не трогает эту область.
* **Вариант 3 — отложить.** Оставить карточку открытой и вернуться позже.

## Как понять, что готово

Ты ответил номером варианта.

## Что будет после

Одобришь → изменение уезжает в live. Отклонишь → поверхность не трогаем.
"""

# Дословно то, что владелец прислал 12.08 (карточка inbox-zadacha-i-otvet-nuzhno-tvoe-reshenie).
OWNER_MSG_12_08 = """Задача и ответ "🧑‍⚖️ Нужно твоё решение

Сайт: packages.astro — автономная правка задела owner-gated область, нужно решение

Автономный оркестратор хотел изменить публичный сайт, но правка задевает owner-gated область (числа доходности / нейминг тиров / legal / solicitation). Такое не уезжает в live само — только с твоего одобрения (инвариант #8).

Варианты:
1. Одобрить
2. Отклонить ⭐ рекомендую
3. Отложить

⚠️ Кнопки сейчас недоступны — бот не подтвердил, что готов их обработать. Ответь номером варианта в чат, я разберу.

📄 owner-decision-sait-packages-astro-avtonomnaya-pravka-z.md"
Ответ 1"""

# Дословно то, что владелец прислал 10.08 — это ЗАДАЧА, а не ответ.
OWNER_MSG_10_08 = """Задача присылать в телеграм не просто нужно твое решение а и кнопки с вариантами чтобы я нажал ты забрал и взял в работу
Сейчас приходит вот так и это не удобно "🧑‍⚖️ Нужно твоё решение

Варианты:
1. Одобрить
2. Отклонить ⭐ рекомендую

⚠️ Кнопки сейчас недоступны — бот не подтвердил, что готов их обработать. Ответь номером варианта в чат, я разберу.

📄 owner-decision-sait-packages-astro-avtonomnaya-pravka-z.md\""""

GHOST_CARD_ID = "owner-decision-sait-packages-astro-avtonomnaya-pravka-z"


def _card(tmp_path: Path, name: str = "own-site.md", text: str = CARD) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _push(tmp_path: Path, state: Path, name: str = "own-site.md",
          title: str = "Сайт: правка задела owner-gated область") -> tuple:
    """Отправить карточку владельцу (как это делает живой цикл) и вернуть (карточка, pid)."""
    card = _card(tmp_path, name)
    prep = od.register_push(card, title, CARD, now=NOW, state_path=state)
    return card, prep.pid


# ── что вообще считается ответом ─────────────────────────────────────────────


def test_the_owners_message_of_12_08_is_recognised_as_an_answer():
    """«Ответ 1» в конце процитированной тревоги — это ОТВЕТ, а не новая задача."""
    parsed = od.parse_text_answer(OWNER_MSG_12_08)
    assert parsed is not None, "живое сообщение владельца не распознано как ответ"
    assert parsed.nums == ("1",)
    assert parsed.card_id == GHOST_CARD_ID, "адресат берётся из процитированной тревоги"


def test_the_owners_message_of_10_08_is_a_task_not_an_answer():
    """Обратный контроль: пожелание про кнопки — ЗАДАЧА, разбор её не перехватывает."""
    assert od.parse_text_answer(OWNER_MSG_10_08) is None


@pytest.mark.parametrize("text, nums", [
    ("Ответ 1", ("1",)),
    ("ответ: 2", ("2",)),
    ("Вариант Б2", ("Б2",)),
    ("выбираю 3", ("3",)),
    ("1", ("1",)),
    ("  2. ", ("2",)),
    ("Ответ 1 и 3", ("1", "3")),
])
def test_answer_forms_the_owner_actually_uses(text, nums):
    parsed = od.parse_text_answer(text)
    assert parsed is not None and parsed.nums == nums


@pytest.mark.parametrize("text", [
    "сделай 2 отчёта и пришли к утру",
    "вариант 2 мне не нравится, поясни почему рекомендуешь",
    "почини график на дашборде",
    "1 сентября будет поздно",
    "",
    "   ",
])
def test_ordinary_speech_is_never_hijacked_as_an_answer(text):
    """Число в обычной речи ответом НЕ является — иначе разбор украдёт поручение."""
    assert od.parse_text_answer(text) is None


def test_the_promise_and_the_parser_cannot_drift_apart():
    """Текст обещания и разбор проверяются ВМЕСТЕ: обещаем ровно то, что умеем.

    Сообщение без кнопок собирается тем же ``build_message``, что и в проде; владелец
    дописывает строку ответа — и она обязана разобраться. Разъедутся формулировка и
    разбор — покраснеет здесь, а не в чате владельца.
    """
    options = od.parse_options(CARD)
    msg = od.build_message("Сайт: правка задела owner-gated область", CARD, options,
                           has_buttons=False, card_name="own-site.md")
    assert "Ответь номером варианта" in msg, "изменилось обещание — проверь разбор"
    parsed = od.parse_text_answer(msg + "\nОтвет 1")
    assert parsed is not None and parsed.nums == ("1",)
    assert parsed.card_id == "own-site"


# ── запись решения ───────────────────────────────────────────────────────────


def test_owner_answer_by_text_closes_the_card_end_to_end(tmp_path):
    """Тот же путь, что у кнопки: «Ответ 1» → решение В КАРТОЧКЕ, авторство записано."""
    state = tmp_path / "state.json"
    card, pid = _push(tmp_path, state)

    res = od.resolve_text_answer("Ответ 1", OWNER, owner_chat_id=OWNER,
                                 state_path=state, now=NOW)

    assert res is not None and res["ok"] is True
    assert res["choice"] == "1" and res["via"] == "text"
    text = card.read_text(encoding="utf-8")
    assert "status: owner-done" in text and "status: needs-owner" not in text
    assert "owner_choice: 1" in text
    assert f"owner_answered_by: {OWNER}" in text
    assert ANSWER_HEADING in text
    assert od.find_push(pid, state_path=state)["choice"] == "1"


def test_quoted_alert_answers_the_card_it_quotes_not_the_newest_one(tmp_path):
    """Владелец переслал тревогу — записываем в ТУ карточку, а не в самую свежую."""
    state = tmp_path / "state.json"
    old, _ = _push(tmp_path, state, "own-old.md", "Старый вопрос")
    new, _ = _push(tmp_path, state, "own-new.md", "Свежий вопрос")

    res = od.resolve_text_answer("📄 own-old.md\nОтвет 2", OWNER, owner_chat_id=OWNER,
                                 state_path=state, now=NOW)

    assert res["ok"] is True and res["card_id"] == "own-old"
    assert "status: owner-done" in old.read_text(encoding="utf-8")
    assert "status: needs-owner" in new.read_text(encoding="utf-8"), "соседняя карточка не тронута"


def test_bare_number_answers_the_single_open_question(tmp_path):
    """Один открытый вопрос ⇒ голое «1» однозначно, и его достаточно."""
    state = tmp_path / "state.json"
    card, _ = _push(tmp_path, state)

    res = od.resolve_text_answer("1", OWNER, owner_chat_id=OWNER,
                                 state_path=state, now=NOW)

    assert res["ok"] is True
    assert "owner_choice: 1" in card.read_text(encoding="utf-8")


# ── отказы: fail-CLOSED, и КАЖДЫЙ назван вслух ───────────────────────────────


def test_answer_to_a_card_that_does_not_exist_is_refused_and_named(tmp_path):
    """АВАРИЯ 12.08 дословно: карточки нет ⇒ ничего не записано, владелец слышит почему."""
    state = tmp_path / "state.json"
    card, _ = _push(tmp_path, state)  # открытая карточка ЕСТЬ — но владелец ответил не ей

    res = od.resolve_text_answer(OWNER_MSG_12_08, OWNER, owner_chat_id=OWNER,
                                 state_path=state, now=NOW)

    assert res["ok"] is False and res["reason"] == "card_unknown"
    assert res["card_id"] == GHOST_CARD_ID
    assert "status: needs-owner" in card.read_text(encoding="utf-8"), \
        "ответ по несуществующей карточке НЕ ИМЕЕТ ПРАВА закрыть соседнюю"
    reply = od.text_answer_reply(res)
    assert GHOST_CARD_ID in reply and "Ничего не записал" in reply
    assert res["reason"] in od.PRESERVE_ON_REFUSAL, "слова владельца обязаны сохраниться"


def test_bare_number_with_several_open_questions_is_refused_not_guessed(tmp_path):
    """Два открытых вопроса ⇒ «1» неоднозначно. Угадывать = решить за владельца."""
    state = tmp_path / "state.json"
    a, _ = _push(tmp_path, state, "own-a.md", "Первый вопрос")
    b, _ = _push(tmp_path, state, "own-b.md", "Второй вопрос")

    res = od.resolve_text_answer("1", OWNER, owner_chat_id=OWNER,
                                 state_path=state, now=NOW)

    assert res["ok"] is False and res["reason"] == "ambiguous"
    assert "status: needs-owner" in a.read_text(encoding="utf-8")
    assert "status: needs-owner" in b.read_text(encoding="utf-8")
    reply = od.text_answer_reply(res)
    assert "own-a" in reply and "own-b" in reply, "владельцу названы кандидаты, а не код ошибки"


def test_bare_number_with_no_open_question_is_refused(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"schema_version": 1, "pushes": []}), encoding="utf-8")

    res = od.resolve_text_answer("1", OWNER, owner_chat_id=OWNER,
                                 state_path=state, now=NOW)

    assert res["ok"] is False and res["reason"] == "no_open_decision"
    assert "нет ни одного открытого вопроса" in od.text_answer_reply(res)


def test_two_numbers_are_never_collapsed_into_one_choice(tmp_path):
    """«1 и 3» — записать можно ровно один вариант; выбрать первый = решить за владельца."""
    state = tmp_path / "state.json"
    card, _ = _push(tmp_path, state)

    res = od.resolve_text_answer("Ответ 1 и 3", OWNER, owner_chat_id=OWNER,
                                 state_path=state, now=NOW)

    assert res["ok"] is False and res["reason"] == "multiple_choices"
    assert "status: needs-owner" in card.read_text(encoding="utf-8")


def test_option_absent_from_the_card_is_refused(tmp_path):
    """В карточке три варианта; «Ответ 9» не выдумывается в четвёртый."""
    state = tmp_path / "state.json"
    card, _ = _push(tmp_path, state)

    res = od.resolve_text_answer("Ответ 9", OWNER, owner_chat_id=OWNER,
                                 state_path=state, now=NOW)

    assert res["ok"] is False and res["reason"] == "unknown_option"
    assert "status: needs-owner" in card.read_text(encoding="utf-8")


def test_a_stranger_cannot_close_the_owners_card_by_text(tmp_path):
    """Инвариант #14 на текстовом пути: чужой «Ответ 1» не меняет карточку ни на байт."""
    state = tmp_path / "state.json"
    card, _ = _push(tmp_path, state)
    before = card.read_text(encoding="utf-8")

    res = od.resolve_text_answer("Ответ 1", STRANGER, owner_chat_id=OWNER,
                                 state_path=state, now=NOW)

    assert res["ok"] is False and res["reason"] == "not_owner"
    assert card.read_text(encoding="utf-8") == before


def test_unverifiable_identity_is_refused_not_allowed(tmp_path):
    """Fail-CLOSED: chat_id владельца не подтверждён ⇒ отказ, а не «наверное, он»."""
    state = tmp_path / "state.json"
    card, _ = _push(tmp_path, state)

    res = od.resolve_text_answer("Ответ 1", OWNER, owner_chat_id="",
                                 state_path=state, now=NOW)

    assert res["ok"] is False and res["reason"] == "not_owner"
    assert "status: needs-owner" in card.read_text(encoding="utf-8")


def test_answer_to_a_card_that_vanished_from_the_tree_is_refused(tmp_path):
    """Карточку отправили, потом дерево её потеряло — записывать некуда, и это сказано."""
    state = tmp_path / "state.json"
    card, _ = _push(tmp_path, state)
    card.unlink()

    res = od.resolve_text_answer("📄 own-site.md\nОтвет 1", OWNER, owner_chat_id=OWNER,
                                 state_path=state, now=NOW)

    assert res["ok"] is False and res["reason"] == "card_gone"
    assert res["reason"] in od.PRESERVE_ON_REFUSAL


def test_answering_twice_does_not_write_a_second_decision(tmp_path):
    """Владелец ответил, потом повторил — второй секции «Решение владельца» не появляется."""
    state = tmp_path / "state.json"
    card, _ = _push(tmp_path, state)
    od.resolve_text_answer("Ответ 1", OWNER, owner_chat_id=OWNER, state_path=state, now=NOW)
    after_first = card.read_text(encoding="utf-8")

    res = od.resolve_text_answer("Ответ 1", OWNER, owner_chat_id=OWNER,
                                 state_path=state, now=NOW)

    assert res["ok"] is False and res["reason"] == "already_answered"
    assert card.read_text(encoding="utf-8") == after_first
    assert after_first.count(ANSWER_HEADING) == 1
    assert res["reason"] not in od.PRESERVE_ON_REFUSAL, "терять тут нечего — дубля не заводим"
    assert "уже записан" in od.text_answer_reply(res)


def test_a_repeat_with_a_DIFFERENT_number_is_not_read_as_a_repeat(tmp_path):
    """«Уже записано» говорится только при совпадении номера — иначе это новый ответ.

    Иначе любой поздний «2» после отвеченного «1» получал бы бодрое «уже записал
    вариант 1», и владелец считал бы, что его услышали.
    """
    state = tmp_path / "state.json"
    _push(tmp_path, state)
    od.resolve_text_answer("Ответ 1", OWNER, owner_chat_id=OWNER, state_path=state, now=NOW)

    res = od.resolve_text_answer("Ответ 2", OWNER, owner_chat_id=OWNER,
                                 state_path=state, now=NOW)

    assert res["ok"] is False and res["reason"] == "no_open_decision"


def test_a_withdrawn_question_does_not_take_an_answer(tmp_path):
    """Вопрос сняли (находка исчезла) ⇒ голое «1» не имеет открытого адресата."""
    state = tmp_path / "state.json"
    card, _ = _push(tmp_path, state)
    assert od.mark_withdrawn(card, now=NOW, state_path=state) is True

    res = od.resolve_text_answer("1", OWNER, owner_chat_id=OWNER,
                                 state_path=state, now=NOW)

    assert res["ok"] is False and res["reason"] == "no_open_decision"


# ── проводка: правка бесполезна, если бот её не зовёт ────────────────────────


@pytest.fixture()
def wired(monkeypatch, tmp_path):
    """Бот без Keychain/сети: перехват отправленных сообщений, карточек и классификатора."""
    sent: list[str] = []
    saved: list[str] = []
    classified: list[str] = []

    monkeypatch.setattr(B, "get_token", lambda: "T", raising=False)
    monkeypatch.setattr(B, "get_chat_id", lambda: OWNER, raising=False)
    bot = B.TelegramBot(token="T", chat_id=OWNER)
    monkeypatch.setattr(bot, "send_message", lambda text, *a, **k: sent.append(text))
    monkeypatch.setattr(bot, "_classify_route",
                        lambda text, chat_id, source: classified.append(text))

    from spa_core.telegram import inbox_intake as II

    monkeypatch.setattr(II, "save_inbox_task",
                        lambda text, source="telegram", **k: (saved.append(text),
                                                              (tmp_path / "c.md", "Заголовок"))[1])

    # Журнал решений — свой на тест (под pytest модуль уводит его в общий временный файл).
    state = tmp_path / "state.json"
    monkeypatch.setenv("SPA_OWNER_DECISIONS_TEST", "1")
    monkeypatch.setattr(od, "STATE_PATH", state, raising=False)
    return types.SimpleNamespace(bot=bot, sent=sent, saved=saved,
                                 classified=classified, state=state, tmp=tmp_path)


def test_bot_routes_the_owners_answer_to_the_card_not_to_the_inbox(wired):
    """ПРОВОДКА: «Ответ 1» в живом боте закрывает карточку и НЕ становится задачей."""
    card, _ = _push(wired.tmp, wired.state)

    handled = wired.bot._handle_inbox_intake({"text": "Ответ 1"}, "Ответ 1", OWNER)

    assert handled is True
    assert wired.classified == [], "ответ владельца ушёл в классификатор — дефект вернулся"
    assert wired.saved == [], "решение владельца снова стало обычной задачей"
    assert "owner_choice: 1" in card.read_text(encoding="utf-8")
    assert wired.sent and "Записал" in wired.sent[0]


def test_bot_answers_the_ghost_card_out_loud_and_keeps_the_message(wired):
    """АВАРИЯ 12.08 через живой бот: карточки нет ⇒ владелец слышит правду, текст сохранён."""
    handled = wired.bot._handle_inbox_intake({"text": OWNER_MSG_12_08}, OWNER_MSG_12_08, OWNER)

    assert handled is True
    assert wired.classified == []
    assert wired.saved == [OWNER_MSG_12_08], "слова владельца потеряны"
    assert wired.sent and GHOST_CARD_ID in wired.sent[0]
    assert "Ничего не записал" in wired.sent[0]


def test_bot_still_treats_an_ordinary_task_as_a_task(wired):
    """Обратный контроль: сообщение 10.08 — задача, обычный путь не тронут."""
    handled = wired.bot._handle_inbox_intake({"text": OWNER_MSG_10_08}, OWNER_MSG_10_08, OWNER)

    assert handled is True
    assert wired.classified == [OWNER_MSG_10_08], "задача перехвачена разбором ответов"
    assert wired.sent == []
