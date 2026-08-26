#!/usr/bin/env python3
"""Владелец ответил номером, а открытых вопросов несколько — спрашиваем, а не гадаем.

Что здесь закрывается (карточка `inbox-golyi-otvet-vladeltsa-1-2-pri-voprose-be`)
------------------------------------------------------------------------------
Голое число от владельца при нескольких открытых вопросах привязать НЕ К ЧЕМУ, и
угадывать запрещено (ADR-075: применённое не то решение владельца дороже
неприменённого). Исход был один: отказ текстом + сообщение сохранялось inbox-ЗАДАЧЕЙ
с заголовком «1» / «2». Ответ владельца не терялся физически, но переставал быть
ответом: в очереди он лежал как работа, а вопрос продолжал висеть `needs-owner`.

Замеры, каждый из которых воспроизведён тестом ниже:

* **20.08** — «Ответ 1» дважды отвергнут как ``ambiguous`` при 14 открытых вопросах
  (замер записан в докстринге ``resolve_text_answer``). Оба ответа не применились.
* **22.08 10:05 / 11:09 / 13:26** и **23.08 04:54** — четыре карточки-следа
  (`inbox-1-2`, `inbox-2`, `inbox-1-3`, `inbox-2-2`) с заголовками «1» и «2».

Починка НЕ добавляет ни одной догадки: адресата называет САМ владелец нажатием, а
кнопка появляется ТОЛЬКО у того вопроса, чей снимок вариантов этот номер содержит —
кнопка в «такого варианта нет» хуже её отсутствия (цикл #191, «кнопка вела в НИКУДА»).

Сети и живого Телеграма здесь нет. Время — вход, а не окружение.
"""
from __future__ import annotations

import types

import pytest

from spa_core.telegram import bot as B
from spa_core.telegram import inbox_intake as II
from spa_core.telegram import owner_decisions as od
from spa_core.tests._freshness import now_utc

NOW = now_utc()
OWNER = "42"

# Карточка с тремя разобранными вариантами — ровно та форма, под которую рисуются кнопки.
CARD_WITH_OPTIONS = """---
trackerStatus:
  type: owner-decision
title: "Вопрос с вариантами"
status: needs-owner
---

## Что случилось и почему это важно

Нужно решение.

## Что от тебя нужно

* **Вариант 1 — одобрить.** Делаем как предложено.
* **Вариант 2 (рекомендую) — отклонить.** Не делаем.
* **Вариант 3 — отложить.** Возвращаемся позже.

## Как понять, что готово

Ты ответил номером варианта.

## Что будет после

Исполню выбранное.
"""

# Карточка-ПОРУЧЕНИЕ: вариантов нет вовсе. Именно такую владельцу отправили 22.08 в
# 09:14 (buttons=FALSE, options=[]) — и голое «1» через 50 минут привязать было не к чему.
CARD_WITHOUT_OPTIONS = """---
trackerStatus:
  type: owner-decision
title: "Поручение без вариантов"
status: needs-owner
---

## Что случилось и почему это важно

Нашёл проблему, чиню.

## Что от тебя нужно

Посмотри и скажи, продолжать ли.

## Как понять, что готово

Ты ответил.

## Что будет после

Продолжу.
"""


def _push(tmp_path, state, name, title, body=CARD_WITH_OPTIONS):
    """Отправить карточку владельцу так же, как это делает живой цикл."""
    card = tmp_path / name
    card.write_text(body, encoding="utf-8")
    prep = od.register_push(card, title, body, now=NOW, state_path=state)
    return card, prep.pid


# ── разбор: что именно возвращается при неоднозначном адресате ────────────────


def test_ambiguous_result_carries_every_candidate_with_its_pid_and_option(tmp_path):
    """Отказ теперь НЕСЁТ материал для переспроса: pid, номер и «предлагает ли вариант».

    Без pid переспросить нечем: `callback_data` строится именно из него. До починки
    отказ отдавал только имена карточек (и не больше пяти) — по ним кнопку не собрать.
    """
    state = tmp_path / "state.json"
    a, pid_a = _push(tmp_path, state, "own-a.md", "Первый вопрос")
    b, pid_b = _push(tmp_path, state, "own-b.md", "Второй вопрос")

    res = od.resolve_text_answer("2", OWNER, owner_chat_id=OWNER, state_path=state, now=NOW)

    assert res["ok"] is False and res["reason"] == "ambiguous"
    assert res["num"] == "2"
    pids = {a["pid"] for a in res["addressees"]}
    assert pids == {pid_a, pid_b}
    assert all(a["offers"] for a in res["addressees"]), "обе карточки предлагают вариант 2"
    # Ничего не записано ни в одну карточку — догадки нет.
    assert "status: needs-owner" in a.read_text(encoding="utf-8")
    assert "status: needs-owner" in b.read_text(encoding="utf-8")


def test_picker_builds_one_button_per_question_that_really_offers_that_option(tmp_path):
    """Кнопка — только у вопроса, чей снимок вариантов содержит присланный номер."""
    state = tmp_path / "state.json"
    _a, pid_a = _push(tmp_path, state, "own-a.md", "Вопрос с вариантами")
    _b, pid_b = _push(tmp_path, state, "own-b.md", "Поручение без вариантов",
                      body=CARD_WITHOUT_OPTIONS)

    res = od.resolve_text_answer("2", OWNER, owner_chat_id=OWNER, state_path=state, now=NOW)
    picker = od.build_answer_addressee_picker(res)

    assert picker is not None, "переспросить было чем, а мы промолчали"
    text, keyboard = picker
    rows = keyboard["inline_keyboard"]
    assert len(rows) == 1, "кнопка досталась и карточке БЕЗ вариантов — она ведёт в никуда"
    assert rows[0][0]["callback_data"] == od.build_callback(pid_a, "2")
    assert od.parse_callback(rows[0][0]["callback_data"]) == (pid_a, "2")
    assert pid_b not in rows[0][0]["callback_data"]
    # Пропущенный вопрос НАЗВАН, а не спрятан.
    assert "не предлагают" in text


def test_the_tap_writes_the_choice_into_the_card_the_owner_pointed_at(tmp_path):
    """Сквозной эффект: нажатие кнопки переспроса закрывает ИМЕННО тот вопрос.

    Это и есть смысл починки — ответ владельца применяется, а не оседает в очереди.
    Путь записи прежний (`record_choice`), инвариант #14 не ослаблен.
    """
    state = tmp_path / "state.json"
    a, _ = _push(tmp_path, state, "own-a.md", "Первый вопрос")
    b, _ = _push(tmp_path, state, "own-b.md", "Второй вопрос")

    res = od.resolve_text_answer("2", OWNER, owner_chat_id=OWNER, state_path=state, now=NOW)
    _text, keyboard = od.build_answer_addressee_picker(res)
    # Владелец нажал кнопку ВТОРОГО вопроса.
    target = [row[0] for row in keyboard["inline_keyboard"]
              if od.parse_callback(row[0]["callback_data"])[0]
              == od.make_pid("own-b")][0]
    pid, choice = od.parse_callback(target["callback_data"])

    out = od.record_choice(pid, choice, OWNER, owner_chat_id=OWNER, now=NOW, state_path=state)

    assert out["ok"] is True
    assert "owner_choice: 2" in b.read_text(encoding="utf-8")
    assert "status: needs-owner" in a.read_text(encoding="utf-8"), "закрыт СОСЕДНИЙ вопрос"


def test_no_candidate_offers_that_option_means_no_buttons_and_a_named_reason(tmp_path):
    """Ни один открытый вопрос варианта не предлагает ⇒ кнопок нет, и это СКАЗАНО.

    Обратная сторона того же правила: молчаливое отсутствие кнопок владелец читает как
    поломку бота, а не как «вариантов с таким номером нет».
    """
    state = tmp_path / "state.json"
    _push(tmp_path, state, "own-a.md", "Поручение раз", body=CARD_WITHOUT_OPTIONS)
    _push(tmp_path, state, "own-b.md", "Поручение два", body=CARD_WITHOUT_OPTIONS)

    res = od.resolve_text_answer("2", OWNER, owner_chat_id=OWNER, state_path=state, now=NOW)

    assert od.build_answer_addressee_picker(res) is None
    reply = od.text_answer_reply(res)
    assert "не предлагает" in reply, "причина отсутствия кнопок не названа"


def test_a_long_queue_of_candidates_names_what_did_not_fit(tmp_path):
    """Потолок кнопок НАЗЫВАЕТСЯ вслух: молчаливая обрезка читается как «больше нет».

    Замер 20.08 — 14 открытых вопросов одновременно; список кнопок нужно резать,
    но не молча (правило «no silent caps»).
    """
    state = tmp_path / "state.json"
    total = od.PICKER_MAX_BUTTONS + 3
    for i in range(total):
        _push(tmp_path, state, f"own-{i}.md", f"Вопрос номер {i}")

    res = od.resolve_text_answer("1", OWNER, owner_chat_id=OWNER, state_path=state, now=NOW)
    text, keyboard = od.build_answer_addressee_picker(res)

    assert len(keyboard["inline_keyboard"]) == od.PICKER_MAX_BUTTONS
    assert f"…и ещё {total - od.PICKER_MAX_BUTTONS}" in text


# ── проводка: правка бесполезна, если бот её не зовёт ────────────────────────


@pytest.fixture()
def wired(monkeypatch, tmp_path):
    """Бот без Keychain/сети: перехват отправленных сообщений и созданных карточек."""
    sent: list[dict] = []
    tasks: list[str] = []
    unapplied: list[dict] = []
    classified: list[str] = []

    monkeypatch.setattr(B, "get_token", lambda: "T", raising=False)
    monkeypatch.setattr(B, "get_chat_id", lambda: OWNER, raising=False)
    bot = B.TelegramBot(token="T", chat_id=OWNER)
    monkeypatch.setattr(
        bot, "send_message",
        lambda text, *a, **k: sent.append({"text": text,
                                           "reply_markup": k.get("reply_markup")}))
    monkeypatch.setattr(bot, "_classify_route",
                        lambda text, chat_id, source: classified.append(text))
    monkeypatch.setattr(II, "save_inbox_task",
                        lambda text, source="telegram", **k: (tasks.append(text),
                                                              (tmp_path / "t.md", "Задание"))[1])
    monkeypatch.setattr(II, "save_unapplied_owner_answer",
                        lambda text, **k: (unapplied.append({"text": text, **k}),
                                           (tmp_path / "u.md", "Ответ"))[1])

    state = tmp_path / "state.json"
    monkeypatch.setenv("SPA_OWNER_DECISIONS_TEST", "1")
    monkeypatch.setattr(od, "STATE_PATH", state, raising=False)
    return types.SimpleNamespace(bot=bot, sent=sent, tasks=tasks, unapplied=unapplied,
                                 classified=classified, state=state, tmp=tmp_path)


def test_bot_asks_with_buttons_instead_of_filing_the_answer_as_a_task(wired):
    """АВАРИЯ 22.08 через живой бот: голое «2» больше не становится ЗАДАЧЕЙ «2».

    Положительный контроль над прод-событием: до починки здесь появлялась inbox-карточка
    с заголовком «2» и телом «## Задание (из Telegram)», а владелец получал текст без
    единой кнопки.
    """
    _push(wired.tmp, wired.state, "own-a.md", "Первый вопрос")
    _push(wired.tmp, wired.state, "own-b.md", "Второй вопрос")

    handled = wired.bot._handle_inbox_intake({"text": "2"}, "2", OWNER)

    assert handled is True
    assert wired.classified == [], "ответ владельца ушёл в общий классификатор"
    assert wired.tasks == [], "ответ владельца снова стал обычной ЗАДАЧЕЙ"
    assert len(wired.sent) == 1
    keyboard = wired.sent[0]["reply_markup"]
    assert keyboard and len(keyboard["inline_keyboard"]) == 2, "переспрос уехал без кнопок"
    # Слова владельца сохранены — но карточкой, названной честно.
    assert len(wired.unapplied) == 1
    assert wired.unapplied[0]["text"] == "2" and wired.unapplied[0]["num"] == "2"
    assert wired.unapplied[0]["asked_with_buttons"] is True


def test_bot_still_files_a_bare_number_as_a_task_when_nothing_is_open(wired):
    """ОБРАТНЫЙ контроль: открытых вопросов нет ⇒ «2» по-прежнему задание.

    Владелец вправе прислать «2» как поручение, и догадка запрещена в обе стороны.
    Это ровно случай 23.08 04:54Z (`inbox-2-2`): ближайшая отправка была накануне в
    19:41Z и к тому моменту уже отвечена — открытых вопросов у бота не было ни одного.
    """
    wired.state.write_text('{"schema_version": 1, "pushes": []}', encoding="utf-8")

    handled = wired.bot._handle_inbox_intake({"text": "2"}, "2", OWNER)

    assert handled is True
    assert wired.tasks == ["2"], "обратный контроль сломан: поручение перестало быть задачей"
    assert wired.unapplied == []
    assert wired.sent[0]["reply_markup"] is None
    assert "нет ни одного открытого вопроса" in wired.sent[0]["text"]


def test_bot_keeps_the_words_and_names_the_reason_when_there_is_nothing_to_offer(wired):
    """Кандидаты есть, но варианта такого нет ⇒ текст с причиной, карточка — честная."""
    _push(wired.tmp, wired.state, "own-a.md", "Поручение раз", body=CARD_WITHOUT_OPTIONS)
    _push(wired.tmp, wired.state, "own-b.md", "Поручение два", body=CARD_WITHOUT_OPTIONS)

    handled = wired.bot._handle_inbox_intake({"text": "2"}, "2", OWNER)

    assert handled is True
    assert wired.sent[0]["reply_markup"] is None, "нарисована кнопка, ведущая в никуда"
    assert "не предлагает" in wired.sent[0]["text"]
    assert len(wired.unapplied) == 1
    assert wired.unapplied[0]["asked_with_buttons"] is False


def test_an_ordinary_task_is_never_hijacked_by_the_picker(wired):
    """Обратный контроль: обычная речь с числом — задача, переспрос её не трогает."""
    _push(wired.tmp, wired.state, "own-a.md", "Первый вопрос")
    _push(wired.tmp, wired.state, "own-b.md", "Второй вопрос")
    msg = "сделай 2 отчёта и пришли к утру"

    handled = wired.bot._handle_inbox_intake({"text": msg}, msg, OWNER)

    assert handled is True
    assert wired.classified == [msg], "поручение перехвачено разбором ответов"
    assert wired.unapplied == [] and wired.sent == []


# ── карточка «неприменённый ответ» — она обязана читаться как ОТВЕТ ───────────


def test_the_preserved_card_says_it_is_an_answer_not_a_task(tmp_path, monkeypatch):
    """Тело карточки называет вещь своим именем и перечисляет ИЗМЕРЕННОЕ, не догадки."""
    written = {}

    def fake_create_card(kind, title, body, status="new", source="telegram", **kw):
        written.update(kind=kind, title=title, body=body, status=status, source=source)
        return tmp_path / "card.md"

    monkeypatch.setattr(II, "create_card", fake_create_card)

    _path, title = II.save_unapplied_owner_answer(
        "2", num="2",
        candidates=[{"card_id": "own-a", "title": "Первый вопрос", "offers": True},
                    {"card_id": "own-b", "title": "Второй вопрос", "offers": False}],
        asked_with_buttons=True)

    assert "Неприменённый ответ владельца" in title and "«2»" in title
    body = written["body"]
    assert body.startswith(II.UNAPPLIED_ANSWER_HEADING)
    assert "## Задание" not in body, "карточка снова читается как работа"
    assert "own-a" in body and "own-b" in body
    assert "предлагает этот вариант" in body and "этого варианта НЕ предлагает" in body
    assert "Задачей это НЕ исполнять" in body


def test_two_questions_with_similar_titles_get_distinguishable_buttons(tmp_path):
    """Подписи кнопок обязаны РАЗЛИЧАТЬСЯ — иначе владелец выбирает вслепую.

    Замер на живой очереди 23.08: при подписи в 30 символов («BUTTON_LABEL_MAX», размер
    для подписи ВАРИАНТА) два соседних вопроса давали одну и ту же строку
    «Закрытие вопроса владельца…». Кнопка снова обещала бы больше, чем даёт.
    """
    state = tmp_path / "state.json"
    long_a = "Закрытие вопроса владельца из рабочего дерева читается сторожем как чужое"
    long_b = "Закрытие вопроса владельца из ветки читается сторожем как потерянное"
    _push(tmp_path, state, "own-a.md", long_a)
    _push(tmp_path, state, "own-b.md", long_b)

    res = od.resolve_text_answer("1", OWNER, owner_chat_id=OWNER, state_path=state, now=NOW)
    _text, keyboard = od.build_answer_addressee_picker(res)

    labels = [row[0]["text"] for row in keyboard["inline_keyboard"]]
    assert len(labels) == 2 and len(set(labels)) == 2, f"подписи неразличимы: {labels}"


def test_identical_titles_fall_back_to_the_card_name(tmp_path):
    """Заголовки совпадают дословно ⇒ различаем именем карточки, а не выдумкой."""
    state = tmp_path / "state.json"
    _push(tmp_path, state, "own-a.md", "Один и тот же заголовок")
    _push(tmp_path, state, "own-b.md", "Один и тот же заголовок")

    res = od.resolve_text_answer("1", OWNER, owner_chat_id=OWNER, state_path=state, now=NOW)
    _text, keyboard = od.build_answer_addressee_picker(res)

    labels = [row[0]["text"] for row in keyboard["inline_keyboard"]]
    assert sorted(labels) == ["own-a", "own-b"], labels
