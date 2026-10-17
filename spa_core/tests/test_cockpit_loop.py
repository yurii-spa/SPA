"""Сквозной путь записи из пульта (ADR-763): исполнитель, проверка пробой, уведомление, «Мои записи».

Каждый тест — положительный контроль одного критерия заказа ARB 16.10; на `origin/main` до этой
правки красны все (модуля `cockpit_loop` нет, «Мои записи» не различают проверенное и закрытое).

  * задача не теряется при падении на границе «закрыто пробой → уведомление» (дочистка приёмом);
  * повторная доставка не запускает второго исполнения (отдельно от дедупа сообщений);
  * «сделано» — только после `satisfied`; приём/взятие ≠ исполнение; `unmeasured` ≠ разрешение;
  * при ошибке владелец видит причину и следующий шаг простыми словами;
  * доставка в Telegram — НЕ МЕНЕЕ ОДНОГО РАЗА: неуверенная отправка повторяется (это закреплено,
    а не скрыто).

Время — вход (`now=` от реальных часов, литеральных дат нет); Telegram — список в памяти;
`history_check` (за ним `claude`) — заглушка шва.

# LLM_FORBIDDEN
"""
# FROZEN-DATE-OK: injected-clock — NOW передаётся в cockpit_loop.take_card/close_verified/claim_card/mi.submit/run_note_intake через now=/at=

from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.owner_queue import cockpit_loop as cl
from spa_core.owner_queue import intake as oi
from spa_core.owner_queue import queue as q
from spa_core.studio_os import mission_control as mc
from spa_core.studio_os import mission_intake as mi
from spa_core.studio_os import owner_view as ov
from spa_core.telegram import inbox_intake as ii

# Время — ВХОД сцены, а не стенные часы на импорте (test_no_import_time_clock_in_tests): вызовы получают now=NOW.
NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)
START = (NOW - timedelta(hours=2)).strftime("%a %b %d %H:%M:%S %Y")
SPEC = "contract_manifest_parity_agrees"      # имя из реестра; исход задаёт runner сцены


class _Crash(BaseException):
    """Падение процесса посреди шага (не Exception: его никто по дороге не глотает)."""


def _guard():
    spec = importlib.util.spec_from_file_location(
        "_t_cockpit_card_claim", Path(ca.REPO_ROOT) / "scripts" / "check_card_claim.py")
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    return g


@pytest.fixture(autouse=True)
def _no_real_classifier(monkeypatch, tmp_path):
    """Ни один тест файла не ходит к НАСТОЯЩЕМУ `claude` — ни на Mac, где бинарь есть, ни на CI.

    Контрольный прогон 39003158532: тест приёма зелёный на Mac, потому что приём звал живой
    классификатор (LLM), и красный на CI, где бинаря нет. Подмена делает исход одинаковым везде:
    позвал классификатор ⇒ «недоступен» ⇒ карточка остаётся `new` ⇒ тест красный на ЛЮБОЙ машине.
    """
    from spa_core.telegram import ask_router
    monkeypatch.setattr(ask_router, "_CLAUDE", str(tmp_path / "no-real-claude-in-tests"))


@pytest.fixture
def scene(tmp_path):
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    log = tmp_path / "session_changes.jsonl"
    log.write_text("", encoding="utf-8")
    g = _guard()
    sib = g.load_sibling()
    anchors = {"executor-a": (os.getpid(), START), "executor-b": (999_003, START)}

    def claim(path, executor):
        g.claim_card(Path(path).stem, log=str(log), session=executor, tracker_dir=str(tracker), now=NOW,
                     sibling=sib, ps=lambda _pid: (0, START), self_anchor=anchors[executor])

    sent: list = []

    class S:
        pass
    s = S()
    s.tmp, s.tracker, s.claim, s.sent = tmp_path, tracker, claim, sent
    s.obox = tmp_path / "data" / "intake_outbox.json"
    s.notify = lambda text: sent.append(text) or True
    return s


def _submit(s, text="Проверить сводку по пакетам", sid="cockpitloop-0001", kind="task", source_voice=False):
    body = {"text": text, "kind": kind, "submission_id": sid}
    if source_voice:
        body["transcript"] = text
    # Провенанс (ARB 16.10): пометка записи — слово владельца только при `author: owner`. Сцена этого
    # файла — записи владельца, и автора устанавливает СЕРВЕР (проверенная подпись Access), как в
    # соседнем test_cockpit_dispatch.py. Прежняя форма дописывала `author: owner` только когда поля
    # НЕТ, а `submit` с 241c9832d пишет его ВСЕГДА (`not-established`) — дописка не срабатывала, и
    # приём звал НАСТОЯЩИЙ классификатор (`claude`): на Mac тест ходил к LLM, на CI (бинаря нет)
    # краснел «new ≠ accepted» (контрольный прогон 39003158532, шард 4).
    prov = mi.provenance_for("public", verified_email="owner@example.org", owner_emails=("owner@example.org",))
    res = mi.submit(json.dumps(body).encode("utf-8"), actor="local", tracker_dir=s.tracker, now=NOW,
                    provenance=prov)
    card = s.tracker / res["card"]
    assert _fm(card).get("author") == "owner"
    return card


def _fm(p):
    return ca.parse_frontmatter(Path(p).read_text(encoding="utf-8"))


def _row(s, path):
    rec = mc.cockpit_records(mc._cards(s.tracker), NOW, source="tracker")
    view = ov.my_records({"intake": {"my_records": rec}}, None)
    return next(r for r in view["rows"] if r["technical"]["карточка"] == Path(path).name), view


def _intake(s, at=NOW):
    return oi.run_note_intake(at, tracker_dir=s.tracker, repo_root=s.tmp, notify=s.notify,
                              history=lambda _b: {"verdict": "NEW", "response": ""}, ingest=False)


def _taken(s, executor="executor-a"):
    card = _submit(s)
    cl.take_card(card, SPEC, executor=executor, claim=s.claim)
    return card


def _close(s, card, verdict, at=NOW, detail="деталь замера"):
    return cl.close_verified(card, now=at, runner=lambda _s: (verdict, detail), outbox_path=s.obox,
                             notify=s.notify)


# ── исполнитель: одно исполнение на карточку ────────────────────────────────────────────────────────
def test_take_refuses_an_unregistered_probe_and_leaves_the_card_new(scene):
    card = _submit(scene)
    with pytest.raises(cl.TakeRefused):
        cl.take_card(card, "no_such_probe", executor="executor-a", claim=scene.claim)
    assert _fm(card)["status"] == "new" and "claimed_by" not in _fm(card)


def test_redelivery_same_executor_is_noop_other_executor_is_refused(scene):
    card = _taken(scene)
    trail_before = card.read_text(encoding="utf-8")
    again = cl.take_card(card, SPEC, executor="executor-a", claim=scene.claim)
    assert again == {"taken": False, "noop": True, "card": card.name, "executor": "executor-a", "probe": SPEC}
    assert card.read_text(encoding="utf-8") == trail_before          # ни строки не переписано
    with pytest.raises(cl.TakeRefused, match="второе исполнение"):
        cl.take_card(card, SPEC, executor="executor-b", claim=scene.claim)
    assert _fm(card)["claimed_by"] == "executor-a"


def test_two_takes_racing_from_new_second_is_refused_by_the_claim(scene):
    """Гонка из `new`: проверка статуса в карточке пропустила бы обоих — отказывает захват шага 0b."""
    card = _submit(scene)
    scene.claim(card, "executor-a")                 # A успел захватить, статус ещё new
    with pytest.raises(cl.TakeRefused, match="захват не состоялся"):
        cl.take_card(card, SPEC, executor="executor-b", claim=scene.claim)
    assert _fm(card)["status"] == "new"


def test_in_progress_card_without_a_claim_is_refused_not_free(scene):
    card = _submit(scene)
    q.set_acceptance_probe(card, SPEC)
    q.set_status(card, "in-progress")               # взята мимо двери — кто исполняет, не измерено
    with pytest.raises(cl.TakeRefused, match="НЕ ИЗМЕРЕНО"):
        cl.take_card(card, SPEC, executor="executor-a", claim=scene.claim)


def test_repeated_submit_and_intake_do_not_touch_a_card_in_work(scene):
    card = _taken(scene)
    _submit(scene)                                   # та же отправка ещё раз
    _intake(scene)
    assert len(list(scene.tracker.glob("inbox-*.md"))) == 1
    assert _fm(card)["status"] == "in-progress" and scene.sent == []


# ── проверка: «сделано» только после satisfied ──────────────────────────────────────────────────────
def test_intake_is_not_execution_close_refuses_a_card_nobody_took(scene):
    card = _submit(scene)
    _intake(scene)
    assert _fm(card)["status"] == "new"
    with pytest.raises(cl.CloseRefused):
        _close(scene, card, ca.SATISFIED)
    row, _ = _row(scene, card)
    assert row["state_kind"] == "accepted" and row["state"] == "принято, ждёт исполнителя"


@pytest.mark.parametrize("verdict,kind", [(ca.NOT_SATISFIED, "not_satisfied"), (ca.UNMEASURED, "unmeasured")])
def test_not_satisfied_or_unmeasured_never_closes_and_says_why(scene, verdict, kind):
    card = _taken(scene)
    res = _close(scene, card, verdict)
    fm = _fm(card)
    assert res["closed"] is False and fm["status"] == "in-progress" and "verified_by_probe" not in fm
    assert fm["acceptance_verdict"] == kind
    row, view = _row(scene, card)
    assert row["state_kind"] == "not_accepted" and row["verified"] is False
    assert row["reason"] == cl.REASON_RU[kind][0] and row["next_step"] == cl.REASON_RU[kind][1]
    assert row["state"].startswith("в работе — не принято: ") and "; следующий шаг: " in row["state"]
    assert not [t for _p, t in ov.main_texts(view) if ov.jargon_hits(t)]
    assert len(scene.sent) == 1 and "Следующий шаг" in scene.sent[0]


def test_a_crashing_probe_is_unmeasured_not_done(scene):
    card = _taken(scene)

    def boom(_spec):
        raise RuntimeError("нечем мерить")
    res = cl.close_verified(card, now=NOW, runner=boom, outbox_path=scene.obox, notify=scene.notify)
    assert res["verdict"] == ca.UNMEASURED and _fm(card)["status"] == "in-progress"


def test_one_notice_per_state_change_not_per_remeasure(scene):
    card = _taken(scene)
    _close(scene, card, ca.NOT_SATISFIED)
    _close(scene, card, ca.NOT_SATISFIED, at=NOW + timedelta(minutes=5))
    assert len(scene.sent) == 1
    _close(scene, card, ca.UNMEASURED, at=NOW + timedelta(minutes=6))       # смена состояния
    assert len(scene.sent) == 2


def test_satisfied_closes_once_with_one_done_notice_and_verified_record(scene):
    card = _taken(scene)
    res = _close(scene, card, ca.SATISFIED)
    fm = _fm(card)
    assert res["verified"] and fm["status"] == "done" and fm["verified_by_probe"] == SPEC
    assert "closed_by:cockpit_loop/probe" in card.read_text(encoding="utf-8")
    assert len(scene.sent) == 1 and SPEC in scene.sent[0] and "сделано и проверено пробой" in scene.sent[0]
    assert "Мадрид" in scene.sent[0]
    _close(scene, card, ca.SATISFIED)
    cl.sweep_notices(tracker_dir=scene.tracker, outbox_path=scene.obox)
    _intake(scene)
    assert len(scene.sent) == 1
    row, _ = _row(scene, card)
    assert row["state_kind"] == "done_verified" and row["verified"] is True
    assert row["state"].startswith("сделано и проверено")


def test_done_without_a_probe_never_reads_as_verified(scene):
    card = _taken(scene)
    q.set_status(card, "done", closed_by="session", evidence="руками")      # закрыли мимо пробы
    row, _ = _row(scene, card)
    assert row["state_kind"] == "done_unverified" and row["verified"] is False
    assert "сделано и проверено" not in row["state"]
    res = cl.close_verified(card, now=NOW, outbox_path=scene.obox, notify=scene.notify)
    assert res["verified"] is False and scene.sent == []                    # «сделано» не объявляется


def test_in_progress_without_a_probe_is_not_accepted_with_reason(scene):
    rec = {"state": "MEASURED", "items": [{"card": "inbox-x.md", "title": "x", "status": "in-progress",
                                           "kind": "task"}], "total": 1, "source": "t", "measured_at": None}
    row = ov.my_records({"intake": {"my_records": rec}}, None)["rows"][0]
    assert row["state_kind"] == "not_accepted" and row["reason"] and row["next_step"]


# ── падение на границах и семантика доставки ────────────────────────────────────────────────────────
def test_crash_after_done_before_notice_is_recovered_by_the_next_intake_run(scene, monkeypatch):
    card = _taken(scene)

    def crash(*a, **k):
        raise _Crash()
    monkeypatch.setattr(oi, "_outbox_put", crash)
    with pytest.raises(_Crash):
        _close(scene, card, ca.SATISFIED)
    monkeypatch.undo()
    fm = _fm(card)
    assert fm["status"] == "done" and fm["verified_by_probe"] == SPEC and "owner_notice" not in fm
    assert scene.sent == []
    _intake(scene)                                   # следующий прогон приёма дочищает
    assert len(scene.sent) == 1 and "сделано и проверено" in scene.sent[0]
    _intake(scene)
    assert len(scene.sent) == 1


def test_crash_after_verified_stamp_before_done_reprobes_not_reports(scene, monkeypatch):
    card = _taken(scene)

    def crash(*a, **k):
        raise _Crash()
    monkeypatch.setattr(q, "set_status", crash)
    with pytest.raises(_Crash):
        _close(scene, card, ca.SATISFIED)
    monkeypatch.undo()
    row, _ = _row(scene, card)
    assert _fm(card)["status"] == "in-progress" and row["verified"] is False and scene.sent == []
    _close(scene, card, ca.SATISFIED)
    assert _fm(card)["status"] == "done" and len(scene.sent) == 1


def test_failed_send_keeps_the_notice_until_telegram_accepts(scene):
    card = _taken(scene)
    cl.close_verified(card, now=NOW, runner=lambda _s: (ca.SATISFIED, "ok"), outbox_path=scene.obox,
                      notify=lambda _t: False)
    assert [i["key"] for i in oi._outbox_load(scene.obox)] == [f"{card.name}#{cl.EVENT_DONE}"]
    oi.flush_outbox(notify=scene.notify, path=scene.obox)
    assert len(scene.sent) == 1 and oi._outbox_load(scene.obox) == []


def test_delivery_is_at_least_once_an_uncertain_send_repeats(scene, monkeypatch):
    """Падение между отправкой и вычёркиванием ПОВТОРЯЕТ сообщение — это закреплено, а не скрыто:
    exactly-once здесь не обещается."""
    card = _taken(scene)
    real_drop = oi._outbox_drop
    calls = {"n": 0}

    def drop_crashes_once(keys, path=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _Crash()
        return real_drop(keys, path)
    monkeypatch.setattr(oi, "_outbox_drop", drop_crashes_once)
    with pytest.raises(_Crash):
        _close(scene, card, ca.SATISFIED)
    oi.flush_outbox(notify=scene.notify, path=scene.obox)
    assert len(scene.sent) == 2 and scene.sent[0] == scene.sent[1]
    assert "НЕ МЕНЕЕ ОДНОГО РАЗА" in (oi.flush_outbox.__doc__ or "")
    assert "НЕ МЕНЕЕ ОДНОГО РАЗА" in (cl.__doc__ or "")


def test_intake_notice_and_done_notice_of_one_card_do_not_replace_each_other(scene):
    card = _taken(scene)
    oi._outbox_put(card.name, "📥 Создал задачу", NOW, scene.obox)          # не доставлено с приёма
    cl.close_verified(card, now=NOW, runner=lambda _s: (ca.SATISFIED, "ok"), outbox_path=scene.obox,
                      notify=lambda _t: False)
    assert sorted(i["key"] for i in oi._outbox_load(scene.obox)) == sorted(
        [card.name, f"{card.name}#{cl.EVENT_DONE}"])


def test_executor_failure_blocks_with_reason_and_next_step_once(scene):
    card = _taken(scene)
    cl.report_failure(card, "тест упал на чистом дереве", next_step="починить тест и перемерить",
                      now=NOW, outbox_path=scene.obox, notify=scene.notify)
    cl.report_failure(card, "тест упал на чистом дереве", next_step="починить тест и перемерить",
                      now=NOW, outbox_path=scene.obox, notify=scene.notify)
    assert _fm(card)["status"] == "blocked" and len(scene.sent) == 1
    row, _ = _row(scene, card)
    assert row["state_kind"] == "not_accepted" and row["state"].startswith("остановлено — не принято: ")
    assert "тест упал" in row["reason"] and row["next_step"] == "починить тест и перемерить"
    with pytest.raises(ValueError):
        cl.report_failure(card, "  ", now=NOW, outbox_path=scene.obox, notify=scene.notify)


def test_non_cockpit_cards_get_no_owner_notice_from_this_path(scene):
    path, _ = ii.save_inbox_task("Задание из Телеграма", source="telegram", tracker_dir=scene.tracker)
    cl.take_card(path, SPEC, executor="executor-a", claim=scene.claim)
    cl.close_verified(path, now=NOW, runner=lambda _s: (ca.SATISFIED, "ok"), outbox_path=scene.obox,
                      notify=scene.notify)
    assert _fm(path)["status"] == "done" and scene.sent == []


def test_intake_seams_default_to_the_production_paths():
    import inspect
    sig = inspect.signature(oi.run_note_intake)
    # + шов `classify=None` (провенанс пульта, ARB 16.10): по умолчанию — боевой классификатор.
    assert [p.default for n, p in sig.parameters.items() if n != "now"] == [None, None, None, None, True, None]
    assert oi._outbox_path() == oi._REPO / "data" / "intake_outbox.json"


# ── провенанс: «Ваша запись» — только запись владельца ──────────────────────────────────────────────
@pytest.mark.parametrize("fields,label", [
    ({"author": "owner"}, "Ваша запись"),
    ({"author": "agent", "author_identity": "arb-demo-1"}, "Запись агента arb-demo-1"),
    ({"author": "not-established"}, "Запись (автор не установлен)"),
    ({"author": ""}, "Запись (автор не установлен)"),
])
def test_notice_names_the_author_and_says_yours_only_for_the_owner(scene, fields, label):
    card = _taken(scene)
    cl._set_fields(card, fields)
    _close(scene, card, ca.NOT_SATISFIED)
    _close(scene, card, ca.NOT_SATISFIED, at=NOW + timedelta(minutes=5))
    _close(scene, card, ca.SATISFIED, at=NOW + timedelta(minutes=6))
    _close(scene, card, ca.SATISFIED, at=NOW + timedelta(minutes=7))
    assert len(scene.sent) == 2                                     # одно на карточку и событие
    for text in scene.sent:
        assert label in text
        if label != "Ваша запись":
            assert "Ваша запись" not in text


def test_missing_author_field_is_never_read_as_the_owner():
    assert cl.record_label({}) == "Запись (автор не установлен)"
    assert cl.record_label({"author": "agent"}) == "Запись агента (имя не установлено)"
