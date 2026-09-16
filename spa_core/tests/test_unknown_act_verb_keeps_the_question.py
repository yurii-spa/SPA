#!/usr/bin/env python3
"""Неизвестный `act:`-глагол больше не переписывает вопрос владельца (ADR-399).

Опасность, ради которой ADR-069 §6 завёл маячок: старый бот, получив нажатие с
глаголом, которого его код не знает, проваливался в ветку по умолчанию
``Router._apply_action`` → ``"settings"``, и ``handle_callback`` правил НАЖАТОЕ
сообщение панелью настроек — стирал сам вопрос. Чтобы этого не случалось, отправитель
снимал кнопки всякий раз, когда маячок бота старше 300 с, — то есть на КАЖДОМ
перезапуске бота (~2 в сутки), и владелец получал «⚠️ Кнопки сейчас недоступны».

Опасность закрывается у источника: неизвестный глагол — это расхождение версий кода,
а не просьба открыть настройки. Сообщение не трогается, владелец получает НОВОЕ
короткое объяснение, а нажатие бот с нужным кодом получит повторно.

Контроль в обе стороны: известные глаголы по-прежнему правят панель на месте
(ни один существующий тест меню не меняется), неизвестный — не правит ничего.
Время в фикстурах не участвует; настройки уводятся во временный файл.
"""
from __future__ import annotations

import pytest

from spa_core.telegram import prefs as prefs_store
from spa_core.telegram.router import Router

OWNER = "424242"


class MockTransport:
    def __init__(self):
        self.edits = []     # (chat_id, message_id, text, keyboard)
        self.sends = []     # (chat_id, text, keyboard)
        self.answers = []   # callback_id

    def edit_message_text(self, chat_id, message_id, text, reply_markup):
        self.edits.append((chat_id, message_id, text, reply_markup))
        return {"ok": True}

    def send_message(self, chat_id, text, reply_markup):
        self.sends.append((chat_id, text, reply_markup))
        return {"ok": True, "result": {"message_id": 1}}

    def answer_callback(self, callback_id):
        self.answers.append(callback_id)


@pytest.fixture()
def router(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_store, "PREFS_PATH", tmp_path / "prefs.json", raising=False)
    return Router(MockTransport(), OWNER)


def test_unknown_verb_leaves_the_tapped_message_untouched(router):
    """Сама авария ADR-069 §6: нажатие стирало вопрос. Теперь правок — ноль."""
    out = router.handle_callback("act:od2:abcdef12:1", OWNER, 777, "cb")
    assert router.transport.edits == [], "сообщение переписано — вопрос владельца стёрт"
    assert router.transport.answers == ["cb"], "спиннер обязан погаснуть"
    assert isinstance(out, dict)


def test_unknown_verb_is_answered_out_loud_with_a_new_message(router):
    """Молчащая кнопка неотличима от сломанной: ответ — НОВЫМ сообщением, не правкой."""
    router.handle_callback("act:od2:abcdef12:1", OWNER, 777, "cb")
    assert len(router.transport.sends) == 1
    chat_id, text, kb = router.transport.sends[0]
    assert chat_id == OWNER
    assert "не распознал" in text
    assert "act:od2" in text, "владелец должен видеть, КАКОЙ глагол не узнан"
    assert "оставил как есть" in text
    assert kb and kb.get("inline_keyboard")


def test_unknown_verb_parses_to_none_not_to_settings(router):
    """Ветка по умолчанию «settings» и была дефектом; теперь её нет."""
    assert router.parse_callback("act:nosuchverb:1", OWNER) is None
    assert router._apply_action("nosuchverb:1", OWNER) is None


def test_known_verbs_still_edit_in_place(router):
    """Обратный контроль: известный глагол правит панель на месте, как и раньше."""
    router.handle_callback("act:warnlevel:critical", OWNER, 777, "cb")
    assert len(router.transport.edits) == 1
    assert router.transport.sends == []
    assert router.parse_callback("act:togglelang:1", OWNER) == ("settings", "", 0)


def test_stranger_gets_nothing_for_an_unknown_verb(router):
    """Fail-closed по владельцу не ослаблен: чужой чат — ни правки, ни ответа."""
    router.handle_callback("act:nosuchverb:1", "999", 777, "cb")
    assert router.transport.edits == []
    assert router.transport.sends == []
