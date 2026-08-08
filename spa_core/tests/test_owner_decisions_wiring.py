#!/usr/bin/env python3
"""Проводка решений владельца: пуш → нажатие → карточка закрыта; и тот же вход из меню.

Почему сквозь РОУТЕР, а не только по деталям — урок #144: снятая точка вызова оставила
22 своих и 1342 смежных теста зелёными, пока фича была мертва в проде. Части здесь уже
покрыты (`test_owner_decisions_telegram.py`); этот файл пиннит именно ПРОВОДКУ:

* callback `act:od:` дошёл до обработчика, а не утонул в общем `act:`-разборе;
* чужое нажатие отсекается роутером ДО записи (вторая, независимая линия к проверке
  внутри писателя — защита не должна держаться на одном звене);
* экран «Мои решения» достижим из меню и зарегистрирован в реестре вьюх, иначе экран
  есть, а дойти до него нельзя;
* оба входа (пуш и меню) показывают ОДИН И ТОТ ЖЕ набор вариантов — разъехавшись, они
  разъедутся молча;
* уведомление доходит даже к отправителю, не знающему про кнопки (эта авария случилась
  при разработке: `reply_markup` уронил отправку, и владелец не узнал бы о решении вовсе).

Время — вход, а не окружение: все отметки от одного `FIXED_NOW`, литеральных дат нет.
"""
from __future__ import annotations

import json

import pytest

from spa_core.owner_queue import notify as N
from spa_core.telegram import alert_actions as aa
from spa_core.telegram import menus
from spa_core.telegram import owner_decisions as od
from spa_core.telegram import prefs as prefs_store
from spa_core.telegram.router import Router
from spa_core.telegram.views import VIEW_REGISTRY, decisions as V
from spa_core.tests._freshness import now_utc

FIXED_NOW = now_utc()
OWNER = "424242"
STRANGER = "999999"

CARD = """---
trackerStatus:
  type: owner-decision
title: "Деньги лежат в кэше"
status: needs-owner
created: 2026-08-07
---

## Что случилось и почему это важно

Освободившийся бюджет никто не перекладывает — он ложится в кэш и лежит.

## Что от тебя нужно

* **Вариант 1 (рекомендую) — перезаполнять освободившийся бюджет.** Текст.
* **Вариант 2 — оставить как есть.** Текст.
"""


class MockTransport:
    def __init__(self):
        self.edits, self.sends, self.answers = [], [], []

    def edit_message_text(self, chat_id, message_id, text, reply_markup):
        self.edits.append((chat_id, message_id, text, reply_markup))
        return {"ok": True}

    def send_message(self, chat_id, text, reply_markup):
        self.sends.append((chat_id, text, reply_markup))
        return {"ok": True}

    def answer_callback(self, callback_id):
        self.answers.append(callback_id)


@pytest.fixture()
def journal(tmp_path, monkeypatch):
    """Журнал решений уезжает во временный файл — и это ПРОВЕРЯЕТСЯ, а не постулируется.

    Роутер и вьюхи зовут `find_push`/`record_choice` без `state_path` (сигнатуры
    фиксированы), поэтому изоляция держится на резолве пути внутри модуля.
    """
    path = tmp_path / "telegram_owner_decisions.json"
    monkeypatch.setattr(od, "STATE_PATH", path, raising=True)
    monkeypatch.setenv("SPA_OWNER_DECISIONS_TEST", "1")
    assert od._state_path() == path, "изоляция журнала не сработала"
    return path


@pytest.fixture()
def beacon(tmp_path, monkeypatch):
    path = tmp_path / "telegram_bot_capabilities.json"
    path.write_text(json.dumps({
        "schema_version": 1, "capabilities": [aa.CAPABILITY],
        "updated_at": FIXED_NOW.isoformat(),
    }))
    monkeypatch.setattr(aa, "BEACON_PATH", path, raising=True)
    return path


@pytest.fixture()
def router(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_store, "PREFS_FILE", tmp_path / "user_prefs.json",
                        raising=True)
    return Router(MockTransport(), OWNER)


@pytest.fixture()
def card(tmp_path):
    p = tmp_path / "own-cash.md"
    p.write_text(CARD, encoding="utf-8")
    return p


def _push(card_path, journal_path, beacon_path):
    prep = od.register_push(card_path, "Деньги лежат в кэше", CARD, now=FIXED_NOW,
                            state_path=journal_path, beacon_path=beacon_path)
    assert prep.keyboard is not None, "кнопки обязаны были собраться"
    return prep


# ── нажатие сквозь роутер ────────────────────────────────────────────────────


def test_tap_through_the_router_closes_the_card(card, journal, beacon, router, monkeypatch):
    """Полная проводка: кнопка из пуша → роутер → решение записано в карточку."""
    monkeypatch.setattr("spa_core.owner_queue.owner_answer._owner_chat_id",
                        lambda explicit=None: OWNER)
    prep = _push(card, journal, beacon)
    data = prep.keyboard["inline_keyboard"][0][0]["callback_data"]

    router.handle_callback(data, OWNER, message_id=7, callback_id="cb1")

    text = card.read_text(encoding="utf-8")
    assert "status: owner-done" in text
    assert "owner_choice: 1" in text
    # Ответ — НОВЫМ сообщением: сам вопрос обязан остаться в переписке.
    assert router.transport.sends and not router.transport.edits
    assert "Записал" in router.transport.sends[0][1]


def test_stranger_tap_is_stopped_by_the_router_before_any_write(card, journal, beacon,
                                                                monkeypatch):
    """Чужой chat_id не доходит до писателя вовсе — и карточка не меняется ни на байт."""
    monkeypatch.setattr(prefs_store, "PREFS_FILE", card.parent / "prefs.json", raising=True)
    r = Router(MockTransport(), OWNER)
    prep = _push(card, journal, beacon)
    data = prep.keyboard["inline_keyboard"][0][0]["callback_data"]
    before = card.read_text(encoding="utf-8")

    assert r.handle_callback(data, STRANGER, message_id=7, callback_id="cb2") is None

    assert card.read_text(encoding="utf-8") == before
    assert r.transport.sends == []


def test_details_button_shows_the_card_without_deciding(card, journal, beacon, router):
    """«Подробнее» — это чтение. Оно НЕ имеет права закрыть карточку."""
    prep = _push(card, journal, beacon)
    more = prep.keyboard["inline_keyboard"][-1][0]["callback_data"]

    router.handle_callback(more, OWNER, message_id=7, callback_id="cb3")

    assert "status: needs-owner" in card.read_text(encoding="utf-8")
    assert "никто не перекладывает" in router.transport.sends[0][1]


def test_tap_on_a_forgotten_card_answers_instead_of_silence(journal, router):
    """Журнал вытеснил карточку — владелец обязан получить фразу, а не молчание.

    Молчащая кнопка неотличима от сломанной, а из отпуска логи не посмотреть.
    """
    router.handle_callback("act:od:deadbeef:1", OWNER, message_id=7, callback_id="cb4")
    assert router.transport.sends, "ответ обязателен при любом исходе"
    assert "не нашёл" in router.transport.sends[0][1].lower()


# ── вход из меню ─────────────────────────────────────────────────────────────


def test_decisions_screen_is_registered_and_reachable_from_home():
    """Экран есть — но до него ещё надо дойти: реестр вьюх + дерево меню."""
    assert "decisions" in VIEW_REGISTRY and "decisions.item" in VIEW_REGISTRY
    assert "decisions" in menus.TREE["home"]["children"]
    assert menus.parent_of("decisions.item") == "decisions"


def test_menu_item_offers_exactly_the_same_options_as_the_push(card, journal, beacon):
    """Два входа — один набор вариантов. Разъедутся — разъедутся молча."""
    prep = _push(card, journal, beacon)
    _text, kb = V.render_item(prep.pid, "ru")
    from_menu = [b[0]["callback_data"] for b in kb["inline_keyboard"]
                 if b[0]["callback_data"].startswith(od.CALLBACK_PREFIX)]
    from_push = [b[0]["callback_data"] for b in prep.keyboard["inline_keyboard"]]
    assert from_menu == from_push


def test_answered_card_shows_the_answer_and_no_more_buttons(card, journal, beacon,
                                                            monkeypatch):
    """Отвеченное решение не предлагает выбрать заново — иначе владелец решит дважды."""
    monkeypatch.setattr("spa_core.owner_queue.owner_answer._owner_chat_id",
                        lambda explicit=None: OWNER)
    prep = _push(card, journal, beacon)
    od.record_choice(prep.pid, "1", OWNER, now=FIXED_NOW, state_path=journal)

    text, kb = V.render_item(prep.pid, "ru")

    assert "Уже отвечено: вариант 1" in text
    assert not [b for b in kb["inline_keyboard"]
                if b[0]["callback_data"].startswith(od.CALLBACK_PREFIX)]


# ── доставка уведомления ─────────────────────────────────────────────────────


def test_notification_reaches_a_sender_that_knows_nothing_about_buttons(card, journal,
                                                                        beacon, monkeypatch):
    """Положительный контроль реальной аварии из разработки этой же задачи.

    `reply_markup` передавался ВСЕГДА; отправитель со старой сигнатурой падал на нём,
    исключение глоталось, и владелец не получал уведомления вовсе — кнопки утащили бы
    за собой само сообщение. Оформление терять можно, уведомление о решении — нет.
    """
    sent = {}

    class OldSender:
        def send_message(self, text, parse_mode="HTML"):  # без reply_markup
            sent["text"] = text
            return {"ok": True}

    monkeypatch.setattr("spa_core.telegram.bot.TelegramBot", OldSender, raising=True)
    N.notify_needs_owner(card)
    assert "Нужно твоё решение" in sent.get("text", "")
