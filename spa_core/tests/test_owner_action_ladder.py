"""S4 K4 (E7.2) · стенд: запись владельца → допуск → взятие → проверка, и отказы — на НАСТОЯЩИХ функциях.

Сцена — та же, что у ``test_cockpit_loop`` (настоящий ``mission_intake.submit`` с проверенным автором, захват шага
0b, ``take_card``/``close_verified``), рабочий трекер недоступен. Здесь проверяется то, чего там нет:
* лестница «запись принята → допуск → работа взята → результат проверен» в «Моих записях» — четыре разных события;
* неразрешённая операция: запись с предметом владельца (``owner_subject: money``) без одобрения НЕ берётся —
  право проверяется в исполнительном пути (``cockpit_dispatch.approval_gate`` → ``dispatch``), не скрытием кнопки;
* повторное нажатие / второй исполнитель / недоступный исполнитель — второго эффекта нет;
* ответ владельца переживает смену сессии (перечитан с диска свежим модулем) и не принимается от чужого чата.

Чего стенд НЕ закрывает (назван пробелом в S4_STATUS): ответ через Telegram не привязан к ВЕРСИИ вопроса
(«старый экран») — это механизм ADR-762, он выключен решением владельца и здесь не включается.
"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.owner_queue import cockpit_dispatch as cd
from spa_core.owner_queue import cockpit_loop as cl
from spa_core.owner_queue import owner_answer as oa
from spa_core.tests.test_cockpit_loop import (NOW, SPEC, _close, _fm, _no_real_classifier, _row,  # noqa: F401
                                              _submit, scene)

OWNER, STRANGER = "111", "999"


def _stages(row):
    return {s["key"]: s for s in row["stages"]}


def test_ladder_tells_recorded_taken_and_verified_apart(scene):
    card = _submit(scene)
    st = _stages(_row(scene, card)[0])
    assert st["recorded"]["done"] and not st["taken"]["done"] and not st["verified"]["done"]
    assert "не требуется" in st["permission"]["text"]
    cl.take_card(card, SPEC, executor="executor-a", claim=scene.claim)
    st = _stages(_row(scene, card)[0])
    assert st["taken"]["done"] and "executor-a" in st["taken"]["text"] and not st["verified"]["done"]
    _close(scene, card, ca.SATISFIED)
    st = _stages(_row(scene, card)[0])
    assert st["verified"]["done"] and "пробой" in st["verified"]["text"]


def test_not_accepted_result_is_not_called_verified(scene):
    card = _submit(scene)
    cl.take_card(card, SPEC, executor="executor-a", claim=scene.claim)
    _close(scene, card, ca.NOT_SATISFIED, detail="числа не сошлись")
    st = _stages(_row(scene, card)[0])
    assert not st["verified"]["done"]


def test_owner_subject_without_approval_is_refused_in_the_execution_path(scene):
    card = _submit(scene, sid="cockpitloop-0002")
    cl._set_fields(card, {"owner_subject": "money"})
    reason = cd.approval_gate(card, SPEC)
    assert reason, "запись с предметом владельца без одобрения обязана получить отказ на границе"
    st = _stages(_row(scene, card)[0])
    assert st["permission"]["done"] is False and "проверяется перед исполнением" in st["permission"]["text"]
    assert _fm(card).get("status") == "new" and not _fm(card).get("claimed_by")


def test_repeat_press_and_second_executor_make_no_second_effect(scene):
    card = _submit(scene, sid="cockpitloop-0003")
    first = cl.take_card(card, SPEC, executor="executor-a", claim=scene.claim)
    again = cl.take_card(card, SPEC, executor="executor-a", claim=scene.claim)
    assert first.get("taken") and again.get("noop")
    with pytest.raises(cl.TakeRefused):
        cl.take_card(card, SPEC, executor="executor-b", claim=scene.claim)
    assert _fm(card).get("status") == "in-progress"
    assert "executor-a" in str(_fm(card).get("claimed_by")) and "executor-b" not in card.read_text(encoding="utf-8")


def test_unavailable_executor_leaves_the_record_retryable_not_closed(scene):
    card = _submit(scene, sid="cockpitloop-0004")
    cl.take_card(card, SPEC, executor="executor-a", claim=scene.claim)

    def boom(_spec):
        raise RuntimeError("исполнитель недоступен")
    res = cl.close_verified(card, now=NOW, runner=boom, outbox_path=scene.obox, notify=scene.notify)
    assert not res.get("closed") and _fm(card).get("status") != "done"


def _decision_card(tmp: Path) -> Path:
    p = tmp / "owner-decision-proba.md"
    p.write_text("---\ntrackerStatus:\n  type: owner-decision\ntitle: Проба\nstatus: needs-owner\n---\n\n"
                 "## Что случилось и почему это важно\nтест\n\n## Что от тебя нужно\n1. Да\n2. Нет\n\n"
                 "## Как понять, что готово\nответ\n\n## Что будет после\nничего\n", encoding="utf-8")
    return p


def test_owner_answer_survives_a_new_session_and_a_repeat_is_not_a_second_decision(tmp_path):
    card = _decision_card(tmp_path)
    oa.record_owner_answer(card, choice_num="1", choice_label="Да", actor_chat_id=OWNER, owner_chat_id=OWNER, now=NOW)
    text1 = card.read_text(encoding="utf-8")
    # «новая сессия»: независимая копия модуля под другим именем — ответ берётся ТОЛЬКО с диска.
    # (reload общего модуля сломал бы тождество классов у соседних тестов — так и случилось в первом прогоне)
    spec = importlib.util.spec_from_file_location("_oa_fresh_session", Path(oa.__file__))
    assert spec is not None and spec.loader is not None
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    fresh.record_owner_answer(card, choice_num="1", choice_label="Да", actor_chat_id=OWNER, owner_chat_id=OWNER, now=NOW)
    text2 = card.read_text(encoding="utf-8")
    assert text1.count(fresh.ANSWER_HEADING) == 1 and text2.count(fresh.ANSWER_HEADING) == 1
    fm = ca.parse_frontmatter(text2)
    assert str(fm.get("owner_choice")) == "1"


def test_answer_from_a_stranger_creates_no_permission(tmp_path):
    card = _decision_card(tmp_path)
    with pytest.raises(oa.NotTheOwner):
        oa.record_owner_answer(card, choice_num="1", choice_label="Да", actor_chat_id=STRANGER,
                               owner_chat_id=OWNER, now=NOW)
    assert ca.parse_frontmatter(card.read_text(encoding="utf-8")).get("status") == "needs-owner"


# ── находки ревью S4 ────────────────────────────────────────────────────────────────────────────────────────

def test_taken_without_a_recorded_gate_pass_is_not_called_permitted(scene):
    """claimed_by пишут и пути мимо dispatch — «взята» не доказывает пройденную границу допуска."""
    from spa_core.studio_os import owner_view as ow
    st = {s["key"]: s for s in ow.record_stages({"card": "x", "owner_subject": "money", "claimed_by": "session-x"})}
    assert st["permission"]["done"] is False and "НЕ записано" in st["permission"]["text"]
    st = {s["key"]: s for s in ow.record_stages({"card": "x", "owner_subject": "money", "claimed_by": "s",
                                                  "approval_passed_at": "2026-11-01T12:00:00Z"})}
    assert st["permission"]["done"] is True


def test_dispatch_records_the_gate_pass_only_when_it_passed(scene, monkeypatch):
    card = _submit(scene, sid="cockpitloop-0005")
    cl._set_fields(card, {"owner_subject": "money", "acceptance_probe": SPEC})
    monkeypatch.setattr(cd, "candidates", lambda tracker_dir=None: [card])
    monkeypatch.setattr(cd, "probe_for", lambda p: (SPEC, None))
    monkeypatch.setattr(cd, "approval_gate", lambda *a, **k: "одобрения нет")
    res = cd.dispatch(executor="executor-a", tracker_dir=scene.tracker, claim=scene.claim, now=NOW, flush=False)
    assert res["taken"] is None and not _fm(card).get("approval_passed_at")
    monkeypatch.setattr(cd, "approval_gate", lambda *a, **k: None)
    res = cd.dispatch(executor="executor-a", tracker_dir=scene.tracker, claim=scene.claim, now=NOW, flush=False)
    assert res["taken"] and _fm(card).get("approval_passed_at") and _fm(card).get("approval_passed_by")
