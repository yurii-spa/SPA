"""R3b (ARB 30.10, раунд 4): нажатие привязано к НЕИЗМЕННОМУ снимку показанного вопроса.

Воспроизведение ARB: сообщение A (вариант 1 «Оставить журнал») → карточка изменена → отправка B
(вариант 1 «Удалить журнал»). До правки кнопка A после отправки B записывала «Удалить журнал»:
``make_pid`` зависит только от карточки, ``register_push`` заменял запись, кнопка не несла версии.

Только временные данные и фиктивный транспорт; реального Telegram, денег и прод-данных нет.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.owner_queue import owner_answer as oa
from spa_core.owner_queue import queue as q
from spa_core.telegram import alert_actions
from spa_core.telegram import owner_decisions as od

HEADER = "---\ntrackerStatus:\n  type: owner-decision\ntitle: Проверка\nstatus: needs-owner\n---\n\n"
OLD = ("## Что от тебя нужно\n\n- **Вариант 1 — Оставить журнал.**\n"
       "- **Вариант 2 — Архивировать журнал.**\n")
NEW = ("## Что от тебя нужно\n\n- **Вариант 1 — Удалить журнал.**\n"
       "- **Вариант 2 — Оставить журнал.**\n")


@pytest.fixture()
def scene(tmp_path, monkeypatch):
    monkeypatch.setattr(od, "materialize_card", lambda p, live_root=None: Path(p))
    monkeypatch.setattr(od, "ack_allowed", lambda *a, **k: (False, "test"))
    monkeypatch.setattr(alert_actions, "handler_available", lambda **k: True)
    monkeypatch.setattr(oa, "record_status_write", lambda *a, **k: None)
    card = tmp_path / "owner-decision-demo.md"
    card.write_text(HEADER + OLD, encoding="utf-8")
    return {"card": card, "journal": tmp_path / "pushes.json", "beacon": tmp_path / "beacon.json"}


def _send(scene, message_id=None):
    p = od.register_push(scene["card"], "Проверка", q.load_card(scene["card"]).body,
                         state_path=scene["journal"], beacon_path=scene["beacon"])
    if message_id is not None:                                           # фиктивный транспорт: «уехало»
        od.mark_send_outcome(p.pid, ok=True, message_id={"message_id": message_id},
                             state_path=scene["journal"])
    return p


def _press(scene, cb):
    pid, choice = od.parse_callback(cb)
    return od.record_choice(pid, choice, "42", owner_chat_id="42", state_path=scene["journal"])


def _cb(prep, row=0):
    return prep.keyboard["inline_keyboard"][row][0]["callback_data"]


def test_old_button_after_a_changed_question_was_resent_does_not_answer_the_new_one(scene):
    a = _send(scene)
    cb_a = _cb(a)
    scene["card"].write_text(HEADER + NEW, encoding="utf-8")
    assert _press(scene, cb_a)["reason"] == "question_changed"           # до повторной отправки
    b = _send(scene)
    cb_b = _cb(b)
    assert cb_a != cb_b, "кнопки двух разных вопросов неотличимы"
    res = _press(scene, cb_a)                                            # старая кнопка ПОСЛЕ отправки B
    assert res["ok"] is False and res["reason"] == "question_changed", res
    assert "owner_choice" not in scene["card"].read_text(encoding="utf-8")


def test_button_b_records_the_option_of_b_and_a_repeat_has_no_second_effect(scene):
    _send(scene)
    scene["card"].write_text(HEADER + NEW, encoding="utf-8")
    b = _send(scene)
    res = _press(scene, _cb(b))
    assert res["ok"] is True and res["label"].startswith("Удалить журнал"), res
    text1 = scene["card"].read_text(encoding="utf-8")
    again = _press(scene, _cb(b))
    assert again["ok"] is True and again.get("already") is True
    assert scene["card"].read_text(encoding="utf-8") == text1            # второго эффекта нет


def test_resending_an_unchanged_question_keeps_the_old_button_meaning(scene):
    a1 = _send(scene)
    a2 = _send(scene)
    assert _cb(a1) == _cb(a2)                                            # тот же вопрос — та же кнопка
    res = _press(scene, _cb(a1))
    assert res["ok"] is True and res["label"].startswith("Оставить журнал")


def test_history_of_sends_and_snapshots_is_kept(scene):
    a = _send(scene, message_id=101)
    scene["card"].write_text(HEADER + NEW, encoding="utf-8")
    b = _send(scene, message_id=202)
    doc = json.loads(scene["journal"].read_text(encoding="utf-8"))
    recs = [r for r in doc["pushes"] if r.get("pid") == a.pid]
    assert len(recs) == 1
    snaps = recs[0]["snapshots"]
    assert len(snaps) == 2                                               # оба показанных вопроса в журнале
    labels = sorted(s["options"][0]["label"] for s in snaps.values())
    assert labels[0].startswith("Оставить") and labels[1].startswith("Удалить")
    assert sorted(m for s in snaps.values() for m in s["message_ids"]) == [101, 202]
    assert recs[0]["history"], "прежняя запись отправки не сохранена"
    del b


def test_reply_to_the_old_message_is_bound_to_the_old_snapshot(scene):
    _send(scene, message_id=101)
    scene["card"].write_text(HEADER + NEW, encoding="utf-8")
    _send(scene, message_id=202)
    old = od.resolve_text_answer("1", "42", owner_chat_id="42", reply_to_message_id=101,
                                 state_path=scene["journal"])
    assert old["ok"] is False and old["reason"] == "question_changed", old
    new = od.resolve_text_answer("1", "42", owner_chat_id="42", reply_to_message_id=202,
                                 state_path=scene["journal"])
    assert new["ok"] is True and new["label"].startswith("Удалить журнал"), new


def test_heal_binds_its_buttons_to_the_snapshot_it_showed(scene, monkeypatch):
    a = _send(scene)
    scene["card"].write_text(HEADER + NEW, encoding="utf-8")
    shown = q.load_card(scene["card"]).body
    prep = od.prepare("Проверка", shown, scene["card"].stem, beacon_path=scene["beacon"])
    heal = od.Heal(pid=prep.pid, card=str(scene["card"]), text="досылка", keyboard=prep.keyboard,
                   options=list(prep.options), ack=prep.ack,
                   question_sha256=od._question_version_of_text(shown))
    monkeypatch.setattr(od, "buttonless_pushes", lambda **kw: [heal])
    assert od.heal_buttonless(lambda t, k: {"message_id": 303}, state_path=scene["journal"]) == [a.pid]
    assert _press(scene, _cb(a))["reason"] == "question_changed"         # кнопка A смысла не меняет
    res = _press(scene, _cb(prep))
    assert res["ok"] is True and res["label"].startswith("Удалить журнал")


def test_versionless_button_on_a_versioned_record_is_refused(scene):
    a = _send(scene)
    res = od.record_choice(a.pid, "1", "42", owner_chat_id="42", state_path=scene["journal"])
    assert res["ok"] is False and res["reason"] == "version_unknown", res
    unknown = od.record_choice(a.pid, "1@deadbeef0000", "42", owner_chat_id="42",
                               state_path=scene["journal"])
    assert unknown["ok"] is False and unknown["reason"] == "version_unknown"
    assert "owner_choice" not in scene["card"].read_text(encoding="utf-8")


def test_change_between_check_and_write_is_still_refused_inside_the_lock(scene, monkeypatch):
    a = _send(scene)
    real = od._question_version_of

    def check_then_change(c):
        v = real(c)
        with q.card_write_lock(scene["card"]):
            scene["card"].write_text(HEADER + NEW, encoding="utf-8")
        return v
    monkeypatch.setattr(od, "_question_version_of", check_then_change)
    res = _press(scene, _cb(a))
    assert res["ok"] is False and res["reason"] == "question_changed"
    assert scene["card"].read_text(encoding="utf-8") == HEADER + NEW


def test_button_a_after_the_card_returned_to_a_records_the_option_of_a_not_of_b(scene):
    """A → B отправлен → карточка вернулась к тексту A: кнопка A пишет вариант ИЗ СНИМКА A."""
    a = _send(scene)
    scene["card"].write_text(HEADER + NEW, encoding="utf-8")
    _send(scene)
    scene["card"].write_text(HEADER + OLD, encoding="utf-8")
    res = _press(scene, _cb(a))
    assert res["ok"] is True and res["label"].startswith("Оставить журнал"), res


def test_resending_the_same_question_keeps_every_message_of_its_snapshot(scene):
    _send(scene, message_id=101)
    _send(scene, message_id=202)
    rec = json.loads(scene["journal"].read_text(encoding="utf-8"))["pushes"][0]
    assert len(rec["snapshots"]) == 1
    (snap,) = rec["snapshots"].values()
    assert snap["message_ids"] == [101, 202]                            # адреса обеих отправок сохранены
    res = od.resolve_text_answer("1", "42", owner_chat_id="42", reply_to_message_id=101,
                                 state_path=scene["journal"])
    assert res["ok"] is True and res.get("resolved_by") == "reply_to"
