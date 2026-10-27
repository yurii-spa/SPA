"""Сквозная цепочка студии на временных данных: план → полномочия → одобрение версии → проба.

Каждое звено проверено в обе стороны: проходит на целом контуре и отказывает на своём
разрыве с понятной причиной (правило приёмки п. 3). Модель не вызывается.
"""
import hashlib
import json

import pytest

from spa_core.studio_os import work_packet as wp
from spa_core.studio_os.memory import arch_review as ar

CODE = "code-v1"


def _card(tmp_path, subject=None, request="Проверь, что ложная тревога закрыта."):
    fm = "---\ntitle: Проверить ложную тревогу\nstatus: new\n" + (f"owner_subject: {subject}\n" if subject else "") + "---\n"
    p = tmp_path / "inbox-demo.md"
    p.write_text(fm + f"\n## Задание (из пульта)\n{request}\n", encoding="utf-8")
    return p


def _prep(tmp_path, card, *, plan="1. прочитать; 2. проба", ok=True):
    src = tmp_path / "src.txt"
    src.write_text("источник", encoding="utf-8")
    run = tmp_path / "prep" / "inbox-demo" / "20261027T000000Z-x"
    run.mkdir(parents=True)
    req = ar.request_text_of(card.read_text(encoding="utf-8"))
    rec = {"kind": ar.KIND_PREP, "status": "ok" if ok else "error",
           "request_sha256": hashlib.sha256(req.encode()).hexdigest(),
           "sources_sha256": {str(src): hashlib.sha256(src.read_bytes()).hexdigest()},
           "input_identity": "ident-1", "input_identity_parts": {"code_identity": CODE},
           "preparation": {"form": "plan", "acceptable": True},
           "sections": {"OUTCOME": "итог", "PLAN": plan, "ACCEPTANCE PROPOSAL": "problem_absent:x"}}
    (run / ar.PREP_RECORD_FILE).write_text(json.dumps(rec), encoding="utf-8")
    return run, src


def _pkt(tmp_path, **kw):
    card = _card(tmp_path, kw.pop("subject", None))
    run, src = _prep(tmp_path, card, **kw)
    return wp.build(card, run, root=tmp_path, code_now=CODE), card, run, src


def test_whole_chain_passes_for_a_current_plan_inside_the_agents_scope(tmp_path):
    pkt, *_ = _pkt(tmp_path, subject="none")
    assert pkt["status"] == "awaiting_approval" and pkt["version"]
    assert wp.authority(pkt) == "agent"
    ap = wp.approve(pkt, version=pkt["version"], approver="session-1", role="agent", at="t")
    probe = wp.bind_probe("problem_absent:com.spa.x.stale_log")
    assert wp.ready(pkt, ap, probe)
    assert "ПАКЕТ ПЕРЕДАЧИ" in wp.render(pkt) and pkt["task_id"] in wp.render(pkt)


def test_changed_plan_does_not_inherit_the_old_approval(tmp_path):
    pkt, card, run, _ = _pkt(tmp_path, subject="none")
    ap = wp.approve(pkt, version=pkt["version"], approver="s", role="agent", at="t")
    rec = json.loads((run / ar.PREP_RECORD_FILE).read_text())
    rec["sections"]["PLAN"] = "1. другой план"
    (run / ar.PREP_RECORD_FILE).write_text(json.dumps(rec))
    pkt2 = wp.build(card, run, root=tmp_path, code_now=CODE)
    assert pkt2["version"] != pkt["version"]
    assert not wp.ready(pkt2, ap, "problem_absent:x")
    with pytest.raises(wp.Refused, match="ДРУГОЙ версии"):
        wp.approve(pkt2, version=pkt["version"], approver="s", role="agent", at="t")


def test_undeclared_subject_needs_the_owner(tmp_path):
    pkt, *_ = _pkt(tmp_path)
    assert wp.authority(pkt) == "owner"
    with pytest.raises(wp.Refused, match="не объявлен"):
        wp.approve(pkt, version=pkt["version"], approver="s", role="agent", at="t")
    assert wp.approve(pkt, version=pkt["version"], approver="Юрий", role="owner", at="t")


def test_money_subject_needs_the_owner(tmp_path):
    pkt, *_ = _pkt(tmp_path, subject="money")
    with pytest.raises(wp.Refused, match="решение владельца"):
        wp.approve(pkt, version=pkt["version"], approver="s", role="agent", at="t")


def test_model_answer_is_never_an_approval(tmp_path):
    pkt, *_ = _pkt(tmp_path, subject="none")
    with pytest.raises(wp.Refused, match="не разрешение"):
        wp.approve(pkt, version=pkt["version"], approver="claude", role="model", at="t")


def test_unknown_probe_is_refused_in_plain_words():
    with pytest.raises(wp.Refused, match="неизвестна реестру"):
        wp.bind_probe("no_such_probe_name:x")
    with pytest.raises(wp.Refused, match="не объявлена"):
        wp.bind_probe("")


def test_stale_preparation_cannot_be_approved(tmp_path):
    pkt, card, run, src = _pkt(tmp_path, subject="none")
    src.write_text("источник изменился", encoding="utf-8")
    pkt2 = wp.build(card, run, root=tmp_path, code_now=CODE)
    assert pkt2["status"] == "plan_not_current"
    with pytest.raises(wp.Refused, match="устарела"):
        wp.approve(pkt2, version=pkt2["version"] or "x", approver="s", role="agent", at="t")


def test_no_preparation_is_a_packet_not_an_error(tmp_path):
    card = _card(tmp_path, "none")
    pkt = wp.build(card, None, root=tmp_path)
    assert pkt["status"] == "no_plan" and "prepare-record" in pkt["next_step"]


def test_dispatch_prompt_carries_the_packet_and_never_breaks_on_failure(tmp_path):
    from spa_core.owner_queue import cockpit_dispatch as cd
    card = _card(tmp_path, "none")
    run, _ = _prep(tmp_path, card)
    note = cd.packet_note(str(card), tmp_path / "prep", tmp_path)
    assert "ПАКЕТ ПЕРЕДАЧИ" in note and "inbox-demo" in note
    broken = cd.packet_note(str(tmp_path / "нет-такой.md"), tmp_path / "prep", tmp_path)
    assert broken.startswith("ПАКЕТ ПЕРЕДАЧИ НЕ СОБРАН")


def test_approval_and_outcome_are_written_once_and_shown_in_the_cockpit(tmp_path):
    from spa_core.studio_os import owner_view as ov
    pkt, card, run, _ = _pkt(tmp_path, subject="none")
    with pytest.raises(wp.Refused, match="нет одобрения"):
        wp.record_outcome(run, pkt, probe="problem_absent:x", verdict="satisfied", detail="d", at="t")
    ap = wp.approve(pkt, version=pkt["version"], approver="Юрий", role="owner", at="2026-10-27T19:20:00+00:00")
    wp.record_approval(run, ap)
    with pytest.raises(wp.Refused, match="не переписывается"):
        wp.record_approval(run, ap)
    wp.record_outcome(run, pkt, probe="problem_absent:x", verdict="satisfied", detail="условие отсутствует",
                      at="2026-10-27T19:21:00+00:00")
    st = ar.preparation_state(run, card_text=card.read_text(encoding="utf-8"), root=tmp_path, code_now=CODE)
    view = ov._record_preparation_ru({**st, **wp.decisions_for(run, st)})
    assert view["head"].startswith("Выполнено и проверено") and "Юрий" in view["approval"]
    assert "условие отсутствует" in view["result"]


def test_approval_of_an_older_plan_version_is_shown_as_not_valid(tmp_path):
    from spa_core.studio_os import owner_view as ov
    pkt, card, run, _ = _pkt(tmp_path, subject="none")
    wp.record_approval(run, wp.approve(pkt, version=pkt["version"], approver="Юрий", role="owner", at="t"))
    rec = json.loads((run / ar.PREP_RECORD_FILE).read_text())
    rec["sections"]["PLAN"] = "1. другой план"
    (run / ar.PREP_RECORD_FILE).write_text(json.dumps(rec))
    st = ar.preparation_state(run, card_text=card.read_text(encoding="utf-8"), root=tmp_path, code_now=CODE)
    d = wp.decisions_for(run, st)
    assert d["approval"]["valid"] is False
    assert "ПРЕЖНЕЙ версии" in ov._record_preparation_ru({**st, **d})["approval"]
