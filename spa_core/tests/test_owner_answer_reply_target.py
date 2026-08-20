#!/usr/bin/env python3
"""Владелец ОТВЕЧАЕТ РЕПЛАЕМ на конкретный вопрос — а мы этого не видели по построению.

Авария 2026-08-20 (замер цикла #317, живые данные прода)
--------------------------------------------------------
Владелец дважды прислал «Ответ 1» — в 11:08 и в 11:16 (второй раз бот записал в лог:
«create_card: открытая карточка с тем же вопросом уже есть (inbox-otvet-1.md)»). Оба раза
ответ был отвергнут с причиной ``ambiguous``: открытых решений в журнале отправок было
**14**, и разбор честно отказался угадывать, к какому из них относится «1».

Отказ был правильным — и всё равно ответ владельца потерялся. Потому что адресат БЫЛ
известен точно, просто не нам:

* Телеграм кладёт в обновление ``reply_to_message`` — сообщение, на которое отвечают.
  Бот это поле не читал **вообще**: в разбор уходили только текст и chat_id.
* В журнале отправок не было ни одного ``message_id`` — ни у одной из 38 записей. То есть
  даже прочитав поле, сопоставить его с карточкой было НЕЧЕМ.

Две половины одного замка, и обе отсутствовали. Поэтому «ответить с телефона» не работало
ровно тогда, когда было нужнее всего: у карточки без кнопок (а такая в очереди была —
``own-rnd-killswitch-rearm-policy-missing``, задаёт два независимых решения и кнопок не
получает by design) текстовый ответ — ЕДИНСТВЕННЫЙ канал.

Что здесь проверяется
---------------------
Каждый тест — положительный контроль над этой аварией: на неисправленном коде краснеет.
Плюс обратные контроли, потому что подсказка обязана работать ТОЛЬКО В ПЛЮС — реплай,
который ни на что не указывает, не имеет права сделать разбор хуже, чем он был без реплая.

Fail-CLOSED не ослаблен ни на строку: снятый вопрос, чужая личность и уже записанный
ответ отвергаются и при точном совпадении адреса. Инвариант #14 цел — запись по-прежнему
идёт единственным owner-путём ``record_owner_answer`` со сверкой личности ВНУТРИ писателя.

Сети и живого Телеграма здесь нет. Время — вход, а не окружение.
"""
from __future__ import annotations

import json
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
title: "Тестовый вопрос владельцу"
status: needs-owner
---

## Что случилось и почему это важно

Вопрос, на который владелец отвечает с телефона.

## Что от тебя нужно

**Вариант 1.** Сделать так. (⭐ рекомендация агента)
**Вариант 2.** Сделать иначе.

## Как понять, что готово

Ты ответил номером варианта.

## Что будет после

Агент исполнит выбранное.
"""


@pytest.fixture(autouse=True)
def handler_alive(monkeypatch: pytest.MonkeyPatch):
    """Обработчик нажатий ЖИВ — иначе кнопок нет по ДРУГОЙ причине (ADR-069).

    На Linux-раннере живого бота нет вовсе, и без подмены тест молча мерил бы не то, что
    заявляет.
    """
    from spa_core.telegram import alert_actions

    monkeypatch.setattr(alert_actions, "handler_available", lambda **kw: True)


def _tracker(tmp_path: Path) -> Path:
    d = tmp_path / "nimbalyst-local" / "tracker"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _register(tmp_path: Path, state: Path, name: str, title: str | None = None):
    card = _tracker(tmp_path) / f"{name}.md"
    card.write_text(CARD, encoding="utf-8")
    return od.register_push(card, title or f"Вопрос {name}", CARD, now=NOW,
                            state_path=state, live_root=tmp_path)


def _send(tmp_path: Path, state: Path, name: str, *, message_id: int,
          ok: bool = True, title: str | None = None) -> str:
    """Отправка с адресом, который вернул Телеграм. Вернуть pid."""
    prep = _register(tmp_path, state, name, title)
    od.mark_send_outcome(prep.pid, ok=ok, message_id=message_id, now=NOW, state_path=state)
    return prep.pid


def _send_plain(tmp_path: Path, state: Path, name: str, title: str | None = None) -> str:
    """Отправка СТАРЫМ вызовом — без единого нового аргумента.

    Нужна тестам, которые утверждают «прежнее поведение не тронуто»: если их подготовка
    зовёт новый код, они краснеют на неисправленном origin по причине подготовки и
    измеряют не то, что заявляют. Такой «положительный контроль» — украшение.
    """
    prep = _register(tmp_path, state, name, title)
    od.mark_send_outcome(prep.pid, ok=True, now=NOW, state_path=state)
    return prep.pid


def _records(state: Path):
    return json.loads(state.read_text(encoding="utf-8"))["pushes"]


def _rec(state: Path, pid: str):
    return next(r for r in _records(state) if r["pid"] == pid)


# ── половина первая: журнал обязан помнить, КАКОЕ сообщение он послал ────────


def test_the_journal_remembers_the_message_it_sent(tmp_path: Path):
    """АВАРИЯ 20.08, половина 1: у всех 38 записей журнала ``message_id`` не было."""
    state = tmp_path / "state.json"
    pid = _send(tmp_path, state, "own-a", message_id=5001)

    assert _rec(state, pid)["message_ids"] == [5001]


def test_a_dropped_send_leaves_no_address_behind(tmp_path: Path):
    """Заслон уронил сообщение ⇒ адрес НЕ запоминается, даже если он назван.

    Записать адрес несостоявшейся отправки значило бы разрешить ответ на сообщение,
    которого владелец никогда не видел, — тот же fail-OPEN, что и «buttons: true» до
    отправки, ради которого `mark_send_outcome` и заводилась.
    """
    state = tmp_path / "state.json"
    pid = _send(tmp_path, state, "own-a", message_id=5001, ok=False)

    assert not _rec(state, pid).get("message_ids")
    assert _rec(state, pid)["delivered"] is False


def test_the_healed_button_message_is_remembered_too(tmp_path: Path):
    """У одного решения законно ДВА сообщения: текст без кнопок и до-доставка кнопок.

    Владелец видит в чате оба и отвечает на то, что под рукой, — значит помнить надо оба,
    а не последнее. Затирание вернуло бы ровно ту же потерю адресата.
    """
    state = tmp_path / "state.json"
    pid = _send(tmp_path, state, "own-a", message_id=5001)
    od.mark_buttons_delivered(pid, message_id=5002, now=NOW, state_path=state)

    assert _rec(state, pid)["message_ids"] == [5001, 5002]


def test_the_same_address_is_never_stored_twice(tmp_path: Path):
    """Идемпотентность: повтор той же отметки не растит запись."""
    state = tmp_path / "state.json"
    pid = _send(tmp_path, state, "own-a", message_id=5001)
    od.mark_send_outcome(pid, ok=True, message_id=5001, now=NOW, state_path=state)

    assert _rec(state, pid)["message_ids"] == [5001]


@pytest.mark.parametrize("payload, expected", [
    ({"ok": True, "result": {"message_id": 77, "chat": {"id": 42}}}, 77),
    ({"message_id": 77}, 77),
    (77, 77),
    (None, None),
    (False, None),
    (True, None),
    ({"ok": True, "result": {}}, None),
    ({"ok": False, "description": "flood"}, None),
    ("не словарь", None),
])
def test_the_address_is_read_from_what_senders_actually_return(payload, expected):
    """Отправители возвращают РАЗНОЕ — от полного ответа API до ``None``. Не бросаем."""
    assert od.message_id_of(payload) == expected


# ── половина вторая: бот обязан прочитать реплай из обновления ───────────────


def test_the_bot_reads_the_reply_target_from_the_update():
    """АВАРИЯ 20.08, половина 2: ``reply_to_message`` не читался ВООБЩЕ."""
    upd = {"message_id": 900, "text": "Ответ 1",
           "reply_to_message": {"message_id": 5001, "text": "🧑‍⚖️ Нужно твоё решение"}}

    assert B._reply_to_message_id(upd) == 5001


@pytest.mark.parametrize("msg", [
    {"message_id": 900, "text": "Ответ 1"},          # обычное сообщение, не реплай
    {"reply_to_message": None},
    {"reply_to_message": {}},
    {"reply_to_message": {"message_id": None}},
    {"reply_to_message": {"message_id": ""}},
    {"reply_to_message": "мусор"},
    None,
    "не словарь",
])
def test_a_non_reply_yields_no_address(msg):
    """Ничего не выводим и не угадываем: поля нет — ответа на этот вопрос у нас нет."""
    assert B._reply_to_message_id(msg) is None


# ── замок в сборе: 14 открытых вопросов, ответ попадает в НУЖНЫЙ ─────────────


def _fourteen_open(tmp_path: Path, state: Path) -> list[str]:
    """Живое состояние прода 20.08: четырнадцать открытых решений разом."""
    return [_send(tmp_path, state, f"own-{i:02d}", message_id=5000 + i)
            for i in range(1, 15)]


def test_the_answer_of_20_08_is_refused_when_nothing_points_at_a_card(tmp_path: Path):
    """Предусловие аварии — оно ОСТАЁТСЯ верным: без адреса отказ не ослаблен.

    Этот тест ЗЕЛЁН и на неисправленном origin — намеренно: он описывает поведение,
    которое чинить не надо, и красный тут означал бы, что починка ослабила отказ.
    """
    state = tmp_path / "state.json"
    for i in range(1, 15):
        _send_plain(tmp_path, state, f"own-{i:02d}")

    res = od.resolve_text_answer("Ответ 1", OWNER, owner_chat_id=OWNER,
                                 state_path=state, now=NOW)

    assert res is not None and res["ok"] is False
    assert res["reason"] == "ambiguous"
    assert res["candidates_total"] == 14


def test_a_reply_names_the_card_when_fourteen_questions_are_open(tmp_path: Path):
    """ГЛАВНОЕ: тот же «Ответ 1», но реплаем — и решение уходит в НУЖНУЮ карточку."""
    state = tmp_path / "state.json"
    pids = _fourteen_open(tmp_path, state)
    target = pids[6]  # седьмой вопрос, message_id=5007 — не первый и не последний

    res = od.resolve_text_answer("Ответ 1", OWNER, owner_chat_id=OWNER,
                                 reply_to_message_id=5007, state_path=state, now=NOW)

    assert res is not None and res["ok"] is True, f"ответ владельца снова потерян: {res}"
    assert res["choice"] == "1"
    assert res["card_id"] == "own-07", "ответ записан не в тот вопрос"
    assert res["resolved_by"] == "reply_to", "чем определён адресат — не записано"
    # ЭФФЕКТ, а не возвращаемое значение: решение обязано лежать В КАРТОЧКЕ.
    card_text = (_tracker(tmp_path) / "own-07.md").read_text(encoding="utf-8")
    assert ANSWER_HEADING in card_text
    assert _rec(state, target)["choice"] == "1"


def test_the_thirteen_other_questions_stay_untouched(tmp_path: Path):
    """Точный адрес — это ещё и обещание НЕ трогать соседей."""
    state = tmp_path / "state.json"
    pids = _fourteen_open(tmp_path, state)

    od.resolve_text_answer("Ответ 1", OWNER, owner_chat_id=OWNER,
                           reply_to_message_id=5007, state_path=state, now=NOW)

    answered = [r["pid"] for r in _records(state) if r.get("choice")]
    assert answered == [pids[6]], "ответ протёк в чужие карточки"


def test_a_reply_to_the_healed_button_message_answers_the_same_card(tmp_path: Path):
    """Владелец отвечает на ДОСЛАННОЕ сообщение — это тот же вопрос, не другой."""
    state = tmp_path / "state.json"
    _fourteen_open(tmp_path, state)
    pid = _send(tmp_path, state, "own-heal", message_id=6001)
    od.mark_buttons_delivered(pid, message_id=6002, now=NOW, state_path=state)

    res = od.resolve_text_answer("Ответ 2", OWNER, owner_chat_id=OWNER,
                                 reply_to_message_id=6002, state_path=state, now=NOW)

    assert res is not None and res["ok"] is True
    assert res["card_id"] == "own-heal" and res["choice"] == "2"


# ── обратные контроли: подсказка работает ТОЛЬКО В ПЛЮС ─────────────────────


def test_a_reply_to_an_unrelated_message_is_no_worse_than_no_reply(tmp_path: Path):
    """Реплай на постороннее сообщение НЕ имеет права ухудшить разбор.

    Владелец вправе ответить реплаем на что угодно — на свой же старый текст, на сводку,
    на «⚠️ открытых вопросов несколько». Раз адрес ни на что не указывает, работает ровно
    тот же разбор, что и без реплая: тот же отказ, теми же словами.
    """
    state = tmp_path / "state.json"
    _fourteen_open(tmp_path, state)

    without = od.resolve_text_answer("Ответ 1", OWNER, owner_chat_id=OWNER,
                                     state_path=state, now=NOW)
    stray = od.resolve_text_answer("Ответ 1", OWNER, owner_chat_id=OWNER,
                                   reply_to_message_id=999999, state_path=state, now=NOW)

    assert stray == without


def test_without_a_reply_the_single_open_question_path_is_unchanged(tmp_path: Path):
    """Обратный контроль: ровно один открытый вопрос отвечается как и раньше.

    Тоже ЗЕЛЁН на неисправленном origin — и обязан быть: он про НЕтронутое.
    """
    state = tmp_path / "state.json"
    _send_plain(tmp_path, state, "own-only")

    res = od.resolve_text_answer("Ответ 1", OWNER, owner_chat_id=OWNER,
                                 state_path=state, now=NOW)

    assert res is not None and res["ok"] is True
    assert res["via"] == "text"
    assert "resolved_by" not in res, "адресат взят не из реплая — говорить обратное нельзя"


def test_an_ordinary_message_stays_an_ordinary_message_even_as_a_reply(tmp_path: Path):
    """Реплай не превращает обычную речь в ответ: разбор формы не тронут."""
    state = tmp_path / "state.json"
    _send(tmp_path, state, "own-only", message_id=7001)

    res = od.resolve_text_answer("почини график на дашборде", OWNER, owner_chat_id=OWNER,
                                 reply_to_message_id=7001, state_path=state, now=NOW)

    assert res is None, "поручение владельца перехвачено как ответ"


def test_two_numbers_are_still_refused_even_with_an_exact_address(tmp_path: Path):
    """«1 и 3» — записать можно ровно один вариант. Точный адрес этого не меняет."""
    state = tmp_path / "state.json"
    _send(tmp_path, state, "own-only", message_id=7001)

    res = od.resolve_text_answer("Ответ 1 и 3", OWNER, owner_chat_id=OWNER,
                                 reply_to_message_id=7001, state_path=state, now=NOW)

    assert res is not None and res["ok"] is False and res["reason"] == "multiple_choices"


# ── fail-CLOSED при ТОЧНОМ адресе ───────────────────────────────────────────


def test_a_reply_cannot_answer_a_question_that_was_withdrawn(tmp_path: Path):
    """Вопрос сняли (находка оказалась ложной) — точный адрес его не воскрешает."""
    state = tmp_path / "state.json"
    _send(tmp_path, state, "own-gone", message_id=8001)
    od.mark_withdrawn(_tracker(tmp_path) / "own-gone.md", now=NOW, state_path=state)

    res = od.resolve_text_answer("Ответ 1", OWNER, owner_chat_id=OWNER,
                                 reply_to_message_id=8001, state_path=state, now=NOW)

    assert res is not None and res["ok"] is False and res["reason"] == "card_withdrawn"
    assert res["reason"] in od.PRESERVE_ON_REFUSAL, "слова владельца обязаны сохраниться"


def test_a_reply_does_not_overwrite_an_answer_already_given(tmp_path: Path):
    """Второй ответ на тот же вопрос ничего не переписывает."""
    state = tmp_path / "state.json"
    _send(tmp_path, state, "own-a", message_id=8101)
    first = od.resolve_text_answer("Ответ 1", OWNER, owner_chat_id=OWNER,
                                   reply_to_message_id=8101, state_path=state, now=NOW)
    assert first["ok"] is True, "предусловие: первый ответ записан"

    again = od.resolve_text_answer("Ответ 2", OWNER, owner_chat_id=OWNER,
                                   reply_to_message_id=8101, state_path=state, now=NOW)

    assert again is not None and again["ok"] is False
    assert again["reason"] == "already_answered" and again["choice"] == "1"


def test_a_stranger_cannot_answer_by_replying(tmp_path: Path):
    """Инвариант #14: канал другой, личность та же. Точный адрес её не подменяет."""
    state = tmp_path / "state.json"
    _send(tmp_path, state, "own-a", message_id=8201)

    res = od.resolve_text_answer("Ответ 1", STRANGER, owner_chat_id=OWNER,
                                 reply_to_message_id=8201, state_path=state, now=NOW)

    assert res is not None and res["ok"] is False and res["reason"] == "not_owner"
    card_text = (_tracker(tmp_path) / "own-a.md").read_text(encoding="utf-8")
    assert ANSWER_HEADING not in card_text, "чужой ответ попал в карточку"


def test_an_unknown_option_is_refused_at_an_exact_address(tmp_path: Path):
    """В карточке два варианта — «Ответ 9» не записывается даже реплаем."""
    state = tmp_path / "state.json"
    _send(tmp_path, state, "own-a", message_id=8301)

    res = od.resolve_text_answer("Ответ 9", OWNER, owner_chat_id=OWNER,
                                 reply_to_message_id=8301, state_path=state, now=NOW)

    assert res is not None and res["ok"] is False and res["reason"] == "unknown_option"


def test_a_broken_journal_never_crashes_the_lookup(tmp_path: Path):
    """Разбор ответа владельца не имеет права уронить бота — даже на битом журнале."""
    state = tmp_path / "state.json"
    state.write_text("{не json", encoding="utf-8")

    assert od._push_by_message_id(5001, state_path=state) is None


# ── проводка: сквозь живой путь доставки ────────────────────────────────────


def test_the_delivery_path_keeps_the_address_end_to_end(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Сквозной контроль проводки: ответ Телеграма → журнал → ответ владельца.

    Мутируй проводку (верни в ``notify_needs_owner`` сжатие ``ok=bool(ok)`` без
    ``result=ok``) — покраснеет здесь, а не в чате владельца через неделю.
    """
    from spa_core.owner_queue import notify as notify_mod

    state = tmp_path / "state.json"
    card = _tracker(tmp_path) / "owner-decision-probe-reply.md"
    card.write_text(CARD, encoding="utf-8")

    class _RealisticBot:
        """Отправитель, который возвращает то же, что настоящий Telegram API."""

        def send_message(self, text, **kw):
            return {"ok": True, "result": {"message_id": 9101, "chat": {"id": 42}}}

    monkeypatch.setattr(od, "_state_path", lambda override=None: state)
    monkeypatch.setattr(od, "_live_tracker_dir", lambda override=None: card.parent)
    monkeypatch.setattr("spa_core.telegram.bot.TelegramBot", _RealisticBot)

    notify_mod.notify_needs_owner(card)

    rec = _records(state)[0]
    assert rec["delivered"] is True, "предусловие: сообщение уехало"
    assert rec["message_ids"] == [9101], "адрес сообщения потерян на пути доставки"

    res = od.resolve_text_answer("Ответ 1", OWNER, owner_chat_id=OWNER,
                                 reply_to_message_id=9101, state_path=state, now=NOW)
    assert res is not None and res["ok"] is True
    assert res["resolved_by"] == "reply_to"


def _owner_bot(monkeypatch: pytest.MonkeyPatch, sent: list):
    """Бот, у которого владелец — владелец, а отправка никуда не ходит."""
    bot = B.TelegramBot.__new__(B.TelegramBot)
    monkeypatch.setattr(bot, "send_message",
                        lambda text, chat_id=None, **kw: sent.append(text), raising=False)
    monkeypatch.setattr(bot, "_get_router",
                        lambda: type("R", (), {"is_owner": staticmethod(lambda c: True)})(),
                        raising=False)
    monkeypatch.setattr(bot, "_handle_long_document", lambda *a, **kw: False, raising=False)
    return bot


def test_the_update_carries_the_reply_target_all_the_way_into_the_resolver(
        monkeypatch: pytest.MonkeyPatch):
    """ПРОВОДКА, а не деталь: входим с ОБНОВЛЕНИЕМ Телеграма, как живой опрос.

    Первая версия этого теста звала ``_handle_owner_text_answer`` напрямую и мутацию
    ПРОПУСТИЛА: снятый на месте вызова аргумент оставлял все 37 тестов зелёными, хотя это
    ровно тот обрыв, что стоил владельцу двух ответов 20.08. Проверять надо шов, а не
    деталь по обе стороны от него — поэтому здесь ``_handle_inbox_intake(msg, …)``.

    Мутируй место вызова (убери ``reply_to_message_id=_reply_to_message_id(msg)``) —
    покраснеет здесь.
    """
    seen = {}

    def _fake_resolve(text, chat_id, **kw):
        seen["text"] = text
        seen["reply_to"] = kw.get("reply_to_message_id")
        return {"ok": True, "choice": "1", "label": "сделать так", "via": "text"}

    monkeypatch.setattr(od, "resolve_text_answer", _fake_resolve)
    sent: list = []
    bot = _owner_bot(monkeypatch, sent)

    msg = {"message_id": 900, "text": "Ответ 1",
           "chat": {"id": int(OWNER)},
           "reply_to_message": {"message_id": 5007,
                                "text": "🧑‍⚖️ Нужно твоё решение\n\nВарианты:\n1. Одобрить"}}

    handled = bot._handle_inbox_intake(msg, "Ответ 1", OWNER)

    assert handled is True
    assert seen.get("reply_to") == 5007, "адресат не доехал из обновления до разбора"
    assert sent, "владелец не получил подтверждения"


def test_an_ordinary_update_without_a_reply_reaches_the_resolver_unchanged(
        monkeypatch: pytest.MonkeyPatch):
    """Обратный контроль шва: не реплай ⇒ в разбор уходит ``None``, а не мусор."""
    seen = {}

    def _fake_resolve(text, chat_id, **kw):
        seen["reply_to"] = kw.get("reply_to_message_id")
        return {"ok": True, "choice": "1", "label": "сделать так", "via": "text"}

    monkeypatch.setattr(od, "resolve_text_answer", _fake_resolve)
    sent: list = []
    bot = _owner_bot(monkeypatch, sent)

    bot._handle_inbox_intake({"message_id": 900, "text": "Ответ 1",
                              "chat": {"id": int(OWNER)}}, "Ответ 1", OWNER)

    assert "reply_to" in seen, "разбор ответа вообще не был вызван"
    assert seen["reply_to"] is None
