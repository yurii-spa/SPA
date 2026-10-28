"""Сквозная цепочка студии на временных данных: план → полномочия → одобрение версии → проба.

Каждое звено проверено в обе стороны: проходит на целом контуре и отказывает на своём
разрыве с понятной причиной (правило приёмки п. 3). Модель не вызывается.

ARB 27.10 (R2, ADR-839): одобрение чужой задачи / не той роли / не того предмета / не той пробы
не даёт «готово»; итог пишется только запуском одобренной пробы реестра, а «проверено» в пульте
ставит запись этого запуска, а не слово вызывающего.
"""
import hashlib
import json

import pytest

from spa_core.studio_os import work_packet as wp
from spa_core.studio_os.memory import arch_review as ar

CODE = "code-v1"
PROBE = "problem_absent:com.spa.x.stale_log"


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
    ap = wp.approve(pkt, version=pkt["version"], approver="session-1", role="agent", at="t", probe=PROBE)
    assert ap["task_id"] == pkt["task_id"] and ap["probe"] == PROBE and ap["subject"] == "none"
    assert wp.ready(pkt, ap, wp.bind_probe(PROBE))
    assert "ПАКЕТ ПЕРЕДАЧИ" in wp.render(pkt) and pkt["task_id"] in wp.render(pkt)


def test_changed_plan_does_not_inherit_the_old_approval(tmp_path):
    pkt, card, run, _ = _pkt(tmp_path, subject="none")
    ap = wp.approve(pkt, version=pkt["version"], approver="s", role="agent", at="t", probe=PROBE)
    rec = json.loads((run / ar.PREP_RECORD_FILE).read_text())
    rec["sections"]["PLAN"] = "1. другой план"
    (run / ar.PREP_RECORD_FILE).write_text(json.dumps(rec))
    pkt2 = wp.build(card, run, root=tmp_path, code_now=CODE)
    assert pkt2["version"] != pkt["version"]
    assert not wp.ready(pkt2, ap, PROBE)
    with pytest.raises(wp.Refused, match="ДРУГОЙ версии"):
        wp.approve(pkt2, version=pkt["version"], approver="s", role="agent", at="t", probe=PROBE)


def test_undeclared_subject_needs_the_owner(tmp_path):
    pkt, *_ = _pkt(tmp_path)
    assert wp.authority(pkt) == "owner"
    with pytest.raises(wp.Refused, match="не объявлен"):
        wp.approve(pkt, version=pkt["version"], approver="s", role="agent", at="t", probe=PROBE)
    assert wp.approve(pkt, version=pkt["version"], approver="Юрий", role="owner", at="t", probe=PROBE)


def test_money_subject_needs_the_owner(tmp_path):
    pkt, *_ = _pkt(tmp_path, subject="money")
    with pytest.raises(wp.Refused, match="решение владельца"):
        wp.approve(pkt, version=pkt["version"], approver="s", role="agent", at="t", probe=PROBE)


def test_model_answer_is_never_an_approval(tmp_path):
    pkt, *_ = _pkt(tmp_path, subject="none")
    with pytest.raises(wp.Refused, match="не разрешение"):
        wp.approve(pkt, version=pkt["version"], approver="claude", role="model", at="t", probe=PROBE)


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
        wp.approve(pkt2, version=pkt2["version"] or "x", approver="s", role="agent", at="t", probe=PROBE)


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


def _problems(dirpath, status="CLOSED", pid="com.spa.x.stale_log"):
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "problems.json").write_text(json.dumps({"problems": {pid: {
        "problem_id": pid, "status": status, "consecutive_absences": 2}}}), encoding="utf-8")


@pytest.fixture
def repo_data(tmp_path, monkeypatch):
    """Рабочие данные пробы (``<REPO_ROOT>/data``) — во временном каталоге, а не в дереве."""
    from spa_core.monitoring import card_acceptance as ca
    root = tmp_path / "repo"
    monkeypatch.setattr(ca, "REPO_ROOT", str(root))
    return root / "data"


def test_outcome_comes_from_a_real_probe_run_and_is_shown_as_verified(tmp_path, repo_data):
    from spa_core.studio_os import owner_view as ov
    pkt, card, run, _ = _pkt(tmp_path, subject="none")
    with pytest.raises(wp.Refused, match="нет одобрения"):
        wp.record_outcome(run, pkt, at="t")
    ap = wp.approve(pkt, version=pkt["version"], approver="Юрий", role="owner",
                    at="2026-10-27T19:20:00+00:00", probe=PROBE)
    wp.record_approval(run, ap)
    with pytest.raises(wp.Refused, match="не переписывается"):
        wp.record_approval(run, ap)
    _problems(repo_data, status="OPEN")
    with pytest.raises(wp.Refused, match="не подтвердила"):
        wp.record_outcome(run, pkt, at="t")
    assert not (run / wp.OUTCOME_FILE).exists(), "не подтверждённый итог не пишется"
    _problems(repo_data, status="CLOSED")
    out = json.loads(wp.record_outcome(run, pkt, at="2026-10-27T19:21:00+00:00").read_text())
    assert out["runner"] == wp.RUNNER and out["verdict"] == "satisfied" and out["run_id"]
    assert out["probe"] == PROBE and out["task_id"] == pkt["task_id"] and out["version"] == pkt["version"]
    st = ar.preparation_state(run, card_text=card.read_text(encoding="utf-8"), root=tmp_path, code_now=CODE)
    d = wp.decisions_for(run, st)
    assert d["execution"]["verified"] is True
    view = ov._record_preparation_ru({**st, **d})
    assert view["head"].startswith("Выполнено и проверено") and "Юрий" in view["approval"]
    assert "импорт оператора" in view["approval"]
    assert "CLOSED" in view["result"]
    assert view.get("outcome") == "итог", "текст ожидаемого итога плана затёрт записью исполнения"


def test_caller_cannot_supply_the_verdict():
    import inspect
    params = inspect.signature(wp.record_outcome).parameters
    assert "verdict" not in params and "detail" not in params and "probe" not in params


def test_arb_wrong_task_agent_role_money_subject_unregistered_probe_is_not_ready(tmp_path):
    pkt, *_ = _pkt(tmp_path, subject="money")
    wrong = {"task_id": "task-b", "version": pkt["version"], "role": "agent", "subject": "money",
             "probe": "unregistered_probe:x"}
    why = wp.readiness(pkt, wrong, "unregistered_probe:x")
    assert not wp.ready(pkt, wrong, "unregistered_probe:x")
    text = " | ".join(why)
    assert "другой задачи" in text and "решение владельца" in text and "неизвестна реестру" in text


@pytest.mark.parametrize("field,value,needle", [
    ("task_id", "inbox-other", "другой задачи"),
    ("version", "v-other", "другой версии"),
    ("subject", "money", "предмет"),
    ("probe", "problem_absent:com.spa.other", "не та, что была одобрена"),
    ("role", "model", "не одобряет"),
])
def test_each_substitution_in_the_approval_is_refused(tmp_path, field, value, needle):
    pkt, *_ = _pkt(tmp_path, subject="none")
    ap = wp.approve(pkt, version=pkt["version"], approver="s", role="agent", at="t", probe=PROBE)
    assert wp.ready(pkt, ap, PROBE)
    bad = {**ap, field: value}
    assert any(needle in r for r in wp.readiness(pkt, bad, PROBE)), wp.readiness(pkt, bad, PROBE)


def test_subject_changed_after_approval_is_refused(tmp_path):
    pkt, *_ = _pkt(tmp_path, subject="none")
    ap = wp.approve(pkt, version=pkt["version"], approver="s", role="agent", at="t", probe=PROBE)
    assert any("предмет" in r for r in wp.readiness({**pkt, "owner_subject": "money"}, ap, PROBE))


def test_arb_unregistered_unrun_probe_never_reaches_the_outcome_file(tmp_path, repo_data):
    pkt, card, run, _ = _pkt(tmp_path, subject="money")
    (run / wp.APPROVAL_FILE).write_text(json.dumps({
        "task_id": pkt["task_id"], "version": pkt["version"], "subject": "money", "role": "owner",
        "probe": "unregistered_probe:x", "approver": "owner-test", "at": "t"}), encoding="utf-8")
    with pytest.raises(wp.Refused, match="неизвестна реестру"):
        wp.record_outcome(run, pkt, at="t")
    assert not (run / wp.OUTCOME_FILE).exists()
    with pytest.raises(wp.Refused, match="неизвестна реестру"):
        wp.approve(pkt, version=pkt["version"], approver="o", role="owner", at="t", probe="unregistered_probe:x")


def test_hand_written_satisfied_outcome_is_not_shown_as_verified(tmp_path):
    """Прежняя форма итога (вердикт со слов вызывающего) — «записан, но не подтверждён»."""
    from spa_core.studio_os import owner_view as ov
    pkt, card, run, _ = _pkt(tmp_path, subject="none")
    wp.record_approval(run, wp.approve(pkt, version=pkt["version"], approver="Юрий", role="owner", at="t",
                                       probe=PROBE))
    (run / wp.OUTCOME_FILE).write_text(json.dumps({
        "schema": wp.SCHEMA, "task_id": pkt["task_id"], "version": pkt["version"], "probe": PROBE,
        "verdict": "satisfied", "detail": "no probe was run", "at": "t"}), encoding="utf-8")
    st = ar.preparation_state(run, card_text=card.read_text(encoding="utf-8"), root=tmp_path, code_now=CODE)
    d = wp.decisions_for(run, st)
    assert d["execution"]["verified"] is False
    view = ov._record_preparation_ru({**st, **d})
    assert not view["head"].startswith("Выполнено и проверено") and "НЕ подтверждён" in view["head"]


def test_forged_run_record_and_overridden_inputs_are_not_verified(tmp_path, repo_data):
    pkt, card, run, _ = _pkt(tmp_path, subject="none")
    wp.record_approval(run, wp.approve(pkt, version=pkt["version"], approver="s", role="agent", at="t",
                                       probe=PROBE))
    other = tmp_path / "fake-data"
    _problems(other)
    wp.record_outcome(run, pkt, at="t", data_dir=str(other))
    st = ar.preparation_state(run, card_text=card.read_text(encoding="utf-8"), root=tmp_path, code_now=CODE)
    d = wp.decisions_for(run, st)
    assert d["execution"]["verified"] is False and "подставленных" in d["execution"]["not_verified_because"]
    oc = json.loads((run / wp.OUTCOME_FILE).read_text())
    oc["inputs"] = {"repo_root": None, "data_dir": None, "tracker_dir": None}  # подделка без пересчёта run_id
    (run / wp.OUTCOME_FILE).write_text(json.dumps(oc))
    d = wp.decisions_for(run, st)
    assert d["execution"]["verified"] is False and "run_id" in d["execution"]["not_verified_because"]


def test_entry_gate_holds_an_owner_subject_card_without_a_valid_approval(tmp_path, repo_data, monkeypatch):
    from spa_core.owner_queue import cockpit_dispatch as cd
    monkeypatch.setattr(ar, "code_identity", lambda root: CODE)  # снимок кода подготовки = текущий
    pkt, card, run, _ = _pkt(tmp_path, subject="money")
    prep = tmp_path / "prep"
    assert cd.approval_gate(card, PROBE, prep, tmp_path), "без одобрения карточка money не берётся"
    assert cd.approval_gate(card, PROBE, None, tmp_path), "нет подготовки — тоже не берётся"
    wp.record_approval(run, wp.approve(pkt, version=pkt["version"], approver="Юрий", role="owner", at="t",
                                       probe=PROBE))
    assert cd.approval_gate(card, PROBE, prep, tmp_path) is None
    assert "не та" in cd.approval_gate(card, "problem_absent:com.spa.other", prep, tmp_path)


def test_entry_gate_keeps_the_old_path_for_cards_outside_owner_subjects(tmp_path):
    from spa_core.owner_queue import cockpit_dispatch as cd
    for subject in ("none", None):
        card = _card(tmp_path, subject)
        assert cd.approval_gate(card, PROBE, None, None) is None


def test_approval_of_an_older_plan_version_is_shown_as_not_valid(tmp_path):
    from spa_core.studio_os import owner_view as ov
    pkt, card, run, _ = _pkt(tmp_path, subject="none")
    wp.record_approval(run, wp.approve(pkt, version=pkt["version"], approver="Юрий", role="owner", at="t", probe=PROBE))
    rec = json.loads((run / ar.PREP_RECORD_FILE).read_text())
    rec["sections"]["PLAN"] = "1. другой план"
    (run / ar.PREP_RECORD_FILE).write_text(json.dumps(rec))
    st = ar.preparation_state(run, card_text=card.read_text(encoding="utf-8"), root=tmp_path, code_now=CODE)
    d = wp.decisions_for(run, st)
    assert d["approval"]["valid"] is False
    assert "ПРЕЖНЕЙ версии" in ov._record_preparation_ru({**st, **d})["approval"]


def test_approval_replaced_after_the_run_is_not_verified(tmp_path, repo_data):
    pkt, card, run, _ = _pkt(tmp_path, subject="none")
    wp.record_approval(run, wp.approve(pkt, version=pkt["version"], approver="s", role="agent", at="t",
                                       probe=PROBE))
    _problems(repo_data)
    wp.record_outcome(run, pkt, at="t")
    st = ar.preparation_state(run, card_text=card.read_text(encoding="utf-8"), root=tmp_path, code_now=CODE)
    assert wp.decisions_for(run, st)["execution"]["verified"] is True
    ap = json.loads((run / wp.APPROVAL_FILE).read_text())
    (run / wp.APPROVAL_FILE).write_text(json.dumps({**ap, "approver": "кто-то другой"}))
    d = wp.decisions_for(run, st)
    assert d["execution"]["verified"] is False and "одобрение изменилось" in d["execution"]["not_verified_because"]
