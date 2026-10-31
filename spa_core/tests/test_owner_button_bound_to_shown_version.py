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


# ── S1-R5-01 (ARB раунд 5): журнал отправок не сокращается ниже прежнего общего лимита ─────────────
def _pending(n, tmp_path):
    return {"pushes": [{"pid": str(i), "card": str(tmp_path / f"c{i}.md"), "card_id": f"c{i}",
                        "choice": None, "snapshots": {f"v{i}": {"question_sha256": "x", "options": [],
                                                                  "message_ids": [i]}}}
                       for i in range(n)]}


@pytest.mark.parametrize("n", [60, 200])
def test_saving_the_journal_keeps_every_pending_record_up_to_the_previous_limit(tmp_path, n):
    j = tmp_path / "pushes.json"
    od._save(_pending(n, tmp_path), j)
    kept = json.loads(j.read_text(encoding="utf-8"))["pushes"]
    assert [r["pid"] for r in kept] == [str(i) for i in range(n)]       # ни одна не потеряна
    assert all(r["snapshots"] for r in kept)


def test_one_card_send_and_its_outcome_do_not_shrink_the_other_records(scene):
    j = scene["journal"]
    j.write_text(json.dumps(_pending(150, scene["card"].parent)), encoding="utf-8")
    p = _send(scene)
    od.mark_send_outcome(p.pid, ok=True, message_id={"message_id": 999}, state_path=j)
    pids = [r["pid"] for r in json.loads(j.read_text(encoding="utf-8"))["pushes"]]
    assert pids[:150] == [str(i) for i in range(150)] and pids[-1] == p.pid


def test_many_resends_keep_every_previous_send_snapshot_and_address(scene):
    for i in range(60):                                                  # 60 отправок ОДНОЙ карточки
        scene["card"].write_text(HEADER + OLD.replace("Оставить журнал", f"Оставить журнал {i}"),
                                 encoding="utf-8")
        _send(scene, message_id=1000 + i)
    rec = json.loads(scene["journal"].read_text(encoding="utf-8"))["pushes"][0]
    assert len(rec["snapshots"]) == 60
    assert sorted(m for s in rec["snapshots"].values() for m in s["message_ids"]) == \
        list(range(1000, 1060))
    assert len(rec["history"]) == 59                                     # прошлые отправки не усечены


# ── S1-R5-02 (ARB раунд 5): новая запись без доказуемой версии не получает legacy-полномочий ───────
@pytest.fixture()
def unversioned(scene, monkeypatch):
    """Новая отправка, у которой версия НЕ посчиталась (предусмотренный исход helper — None)."""
    monkeypatch.setattr(od, "_question_version_of_text", lambda text: None)
    a = _send(scene, message_id=501)
    monkeypatch.undo()
    monkeypatch.setattr(od, "materialize_card", lambda p, live_root=None: Path(p))
    monkeypatch.setattr(alert_actions, "handler_available", lambda **k: True)
    monkeypatch.setattr(oa, "record_status_write", lambda *a, **k: None)
    scene["card"].write_text(HEADER + NEW, encoding="utf-8")            # вопрос изменился
    scene["a"] = a
    return scene


def _unchanged_and_unanswered(scene):
    text = scene["card"].read_text(encoding="utf-8")
    assert text == HEADER + NEW and "owner_choice" not in text


def test_unversioned_new_record_button_is_refused(unversioned):
    a = unversioned["a"]
    res = _press(unversioned, _cb(a))
    assert res["ok"] is False and res["reason"] == "version_unknown", res
    _unchanged_and_unanswered(unversioned)


def test_unversioned_new_record_reply_is_refused(unversioned):
    res = od.resolve_text_answer("1", "42", owner_chat_id="42", reply_to_message_id=501,
                                 state_path=unversioned["journal"])
    assert res["ok"] is False and res["reason"] == "version_unknown", res
    _unchanged_and_unanswered(unversioned)


def test_unversioned_new_record_menu_button_is_refused(unversioned, monkeypatch):
    from spa_core.telegram.views import decisions as dv
    monkeypatch.setattr(od, "find_push", lambda pid, state_path=None:
                        od.find_push.__wrapped__(pid, state_path=unversioned["journal"])
                        if hasattr(od.find_push, "__wrapped__") else
                        json.loads(unversioned["journal"].read_text())["pushes"][-1])
    monkeypatch.setattr(od, "card_details", lambda pid, limit=None: "детали")
    _text, kb = dv.render_item(unversioned["a"].pid)
    cbs = [b["callback_data"] for row in kb["inline_keyboard"] for b in row
           if str(b.get("callback_data", "")).startswith(od.CALLBACK_PREFIX)
           and not b["callback_data"].endswith(":more")]
    for cb in cbs:                                                       # каждая кнопка меню
        res = _press(unversioned, cb)
        assert res["ok"] is False and res["reason"] == "version_unknown", (cb, res)
    _unchanged_and_unanswered(unversioned)


def test_unversioned_heal_does_not_grant_authority(unversioned, monkeypatch):
    a = unversioned["a"]
    heal = od.Heal(pid=a.pid, card=str(unversioned["card"]), text="досылка", keyboard={"k": 1},
                   options=[od.ParsedOption(num="1", label="Удалить журнал", recommended=False)],
                   ack=False, question_sha256=None)                      # досылка без версии
    monkeypatch.setattr(od, "buttonless_pushes", lambda **kw: [heal])
    od.heal_buttonless(lambda t, k: {"message_id": 777}, state_path=unversioned["journal"])
    res = od.record_choice(a.pid, "1", "42", owner_chat_id="42", state_path=unversioned["journal"])
    assert res["ok"] is False and res["reason"] == "version_unknown", res
    _unchanged_and_unanswered(unversioned)


def test_true_legacy_record_keeps_its_named_limit(scene):
    """Запись ДО протокола R3b (без маркера) — прежняя ветка с её пределом, как и было названо."""
    j = scene["journal"]
    j.write_text(json.dumps({"pushes": [{"pid": "p1", "card": str(scene["card"]), "card_id": "c",
                                         "options": [{"num": "1", "label": "Оставить журнал"}],
                                         "choice": None}]}), encoding="utf-8")
    res = od.record_choice("p1", "1", "42", owner_chat_id="42", state_path=j)
    assert res["ok"] is True


# ── S1-R6-01 (ARB раунд 6): НОВАЯ досылка к старой (legacy) записи — через настоящий heal-путь ──────
def _legacy_journal(scene, message_ids=(101,), choice=None, history=None):
    rec = {"pid": od.make_pid(scene["card"].stem), "card": str(scene["card"]),
           "card_id": scene["card"].stem, "title": "Проверка", "buttons": False, "options": [],
           "choice": choice, "message_ids": list(message_ids)}
    if history is not None:
        rec["old_field"] = history
    scene["journal"].write_text(json.dumps({"pushes": [rec]}), encoding="utf-8")
    return rec


def _real_heal(scene):
    sent = []

    def sender(text, keyboard):                                          # фиктивный транспорт
        sent.append((text, keyboard))
        return {"message_id": 777}
    fixed = od.heal_buttonless(sender, state_path=scene["journal"], beacon_path=scene["beacon"])
    return fixed, sent


def test_new_heal_to_a_legacy_record_with_unknown_version_grants_no_authority(scene, monkeypatch):
    rec = _legacy_journal(scene)
    monkeypatch.setattr(od, "_question_version_of_text", lambda text: None)   # версия не посчиталась
    fixed, sent = _real_heal(scene)
    monkeypatch.undo()
    monkeypatch.setattr(oa, "record_status_write", lambda *a, **k: None)
    assert fixed == [rec["pid"]] and len(sent) == 1
    cb = sent[0][1]["inline_keyboard"][0][0]["callback_data"]
    scene["card"].write_text(HEADER + NEW, encoding="utf-8")            # вопрос изменился
    before = scene["card"].read_bytes()
    res = _press(scene, cb)
    assert res["ok"] is False and res["reason"] == "version_unknown", res
    rep = od.resolve_text_answer("1", "42", owner_chat_id="42", reply_to_message_id=777,
                                 state_path=scene["journal"])
    assert rep["ok"] is False and rep["reason"] == "version_unknown", rep
    assert scene["card"].read_bytes() == before                         # побайтно не изменена
    after = json.loads(scene["journal"].read_text(encoding="utf-8"))["pushes"][0]
    assert after["message_ids"][:1] == [101] and 777 in after["message_ids"]   # сведения об отправках целы


def test_new_heal_to_a_legacy_record_with_a_version_binds_to_the_shown_snapshot(scene):
    rec = _legacy_journal(scene)
    fixed, sent = _real_heal(scene)
    assert fixed == [rec["pid"]]
    cb = sent[0][1]["inline_keyboard"][0][0]["callback_data"]
    assert od.VERSION_SEP in cb                                          # кнопка несёт метку показанного
    scene["card"].write_text(HEADER + NEW, encoding="utf-8")
    assert _press(scene, cb)["reason"] == "question_changed"            # устаревший — отказ
    scene["card"].write_text(HEADER + OLD, encoding="utf-8")
    ok = _press(scene, cb)
    assert ok["ok"] is True and ok["label"].startswith("Оставить журнал")  # актуальный — принят


def test_untouched_legacy_record_keeps_its_named_compatibility_limit(scene):
    """Без новой досылки запись до R3b остаётся в прежней границе (как названо в ADR-857)."""
    rec = _legacy_journal(scene)
    doc = json.loads(scene["journal"].read_text(encoding="utf-8"))
    doc["pushes"][0]["options"] = [{"num": "1", "label": "Оставить журнал"}]
    scene["journal"].write_text(json.dumps(doc), encoding="utf-8")
    res = od.record_choice(rec["pid"], "1", "42", owner_chat_id="42", state_path=scene["journal"])
    assert res["ok"] is True
