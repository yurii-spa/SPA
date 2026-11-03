# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — every time is passed to goal_graph as `now`/`at`; nothing reads the wall clock
"""STUDIO-AUTONOMY-01, S1: цель → граф → допуск → действие на стенде → машинный исход.

Всё — во временном каталоге (``tmp_path``): стенд помечен ``.studio_stand``, рабочий трекер и данные
не открываются. Сценарий и отказы — из приёмки E1 и E3 задания.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from spa_core.studio_os import goal_graph as gg

T0, T1, LATE = "2026-10-29T10:00:00Z", "2026-10-29T10:05:00Z", "2026-10-29T12:00:00Z"
EXPIRES = "2026-10-29T11:00:00Z"
CONTENT = "status: ready\n"
SHA = hashlib.sha256(CONTENT.encode()).hexdigest()


def _goal(**kw):
    base = dict(source="telegram", transport_id="msg-101", owner="owner", at=T0,
                outcome="файл статуса на стенде содержит status: ready")
    base.update(kw)
    return gg.goal_record("Подготовь файл статуса на стенде", **base)


def _plan():
    return {"tasks": [
        {"id": "t1", "outcome": "черновик создан",
         "operations": [{"op": "write_file", "path": "notes/draft.md", "content": "draft\n"}],
         "check": {"kind": "file_contains", "path": "notes/draft.md", "text": "draft"}},
        {"id": "t2", "outcome": "статус готов", "depends_on": ["t1"],
         "operations": [{"op": "write_file", "path": "notes/status.md", "content": CONTENT}],
         "check": {"kind": "file_sha256", "path": "notes/status.md", "sha256": SHA}},
    ]}


@pytest.fixture
def stand(tmp_path):
    s = tmp_path / "stand"
    s.mkdir()
    (s / ".studio_stand").write_text("S1 stand\n")
    return s


def _lease(g, tid, run, worker="worker", now=T0, ttl=3600):
    return gg.claim(run, g, tid, worker=worker, process=f"{worker}:proc", now=now, ttl_s=ttl)


def _graph():
    res = gg.validate_plan(_goal(), _plan(), scope=["notes"])
    assert res["ok"], res["refusals"]
    return res["graph"]


# ── сквозной сценарий ────────────────────────────────────────────────────────────────────────────
def test_goal_to_graph_to_admission_to_stand_action_to_machine_result(stand, tmp_path):
    run = tmp_path / "run"
    g = _graph()
    assert gg.ready_tasks(g, []) == ["t1"]                       # t2 ждёт зависимость
    for tid in g["order"]:
        ap = gg.approve_task(g, tid, approver="agent:cycle", role="agent", at=T0, expires_at=EXPIRES)
        lease = _lease(g, tid, run)
        out = gg.execute_on_stand(g, tid, ap, stand=stand, run_dir=run, now=T1, author="worker", lease=lease)
        assert out["state"] == "applied"
        res = gg.machine_result(g, tid, stand=stand, run_dir=run, now=T1, lease=lease)
        assert res["verdict"] == gg.SATISFIED, res
    assert gg.done_tasks(run, g["version"]) == ["t1", "t2"]
    assert (stand / "notes" / "status.md").read_text() == CONTENT
    states = [json.loads(x)["state"] for x in (run / gg.JOURNAL_FILE).read_text().splitlines()
              if "state" in json.loads(x)]
    assert states == ["started", "applied", f"checked:{gg.SATISFIED}"] * 2


# ── E1: цель и граф ──────────────────────────────────────────────────────────────────────────────
def test_repeat_of_the_same_transport_message_is_the_same_goal_a_new_note_is_new():
    assert _goal()["goal_id"] == _goal(at=T1)["goal_id"]
    assert _goal()["goal_id"] != _goal(transport_id="msg-102")["goal_id"]


def test_goal_change_is_a_new_version_linked_to_the_old_one_and_invalidates_approvals(stand, tmp_path):
    old = _goal()
    new = gg.revise_goal(old, text="Подготовь файл статуса и журнал", outcome="оба файла есть",
                         transport_id="msg-103", at=T1)
    assert new["supersedes"] == old["version"] and new["version"] != old["version"]
    g_old = _graph()
    ap = gg.approve_task(g_old, "t1", approver="a", role="agent", at=T0, expires_at=EXPIRES)
    g_new = gg.validate_plan(new, _plan(), scope=["notes"])["graph"]
    assert "допуск выдан другой версии цели или плана" in gg.admission(g_new, "t1", ap, now=T1)


@pytest.mark.parametrize("mutate,needle", [
    (lambda p: p["tasks"][0].update(depends_on=["t2"]), "цикл"),
    (lambda p: p["tasks"][1].update(depends_on=["t9"]), "не существует"),
    (lambda p: p["tasks"][0]["operations"][0].update(path="spa_core/x.py"), "вне объявленного scope"),
    (lambda p: p["tasks"][0]["operations"][0].update(path="../etc/x"), "вне объявленного scope"),
    (lambda p: p["tasks"][0].update(outcome=""), "нет ожидаемого результата"),
    (lambda p: p["tasks"][0].pop("check"), "проверка результата не годится"),
    (lambda p: p["tasks"][0]["operations"].append({"op": "rm_rf", "path": "notes"}), "вне словаря"),
    (lambda p: p["tasks"][1].update(id="t1"), "повторяются"),
])
def test_invalid_plan_is_refused_whole_and_has_no_version(mutate, needle):
    p = _plan()
    mutate(p)
    res = gg.validate_plan(_goal(), p, scope=["notes"])
    assert res["ok"] is False and res["graph"] is None
    assert any(needle in r for r in res["refusals"]), res["refusals"]


def test_unknown_probe_name_is_refused():
    p = _plan()
    p["tasks"][0]["check"] = {"kind": "card_probe", "probe": "no_such_probe_xyz"}
    res = gg.validate_plan(_goal(), p, scope=["notes"])
    assert not res["ok"] and any("неизвестна реестру" in r for r in res["refusals"])


def test_existing_backlog_task_is_a_dependency_only_by_exact_id():
    p = _plan()
    p["tasks"][0]["depends_on"] = ["inbox-existing-card"]
    ok = gg.validate_plan(_goal(), p, scope=["notes"], existing={"inbox-existing-card": {"done": False}})
    assert ok["ok"] and gg.ready_tasks(ok["graph"], []) == []          # не выполнена — ждём
    done = gg.validate_plan(_goal(), p, scope=["notes"], existing={"inbox-existing-card": {"done": True}})
    assert gg.ready_tasks(done["graph"], []) == ["t1"]
    near = gg.validate_plan(_goal(), p, scope=["notes"], existing={"inbox-existing-card-2": {"done": True}})
    assert not near["ok"]                                               # похожее имя — не совпадение


# ── E3: полномочия ───────────────────────────────────────────────────────────────────────────────
def test_hidden_owner_subject_is_refused_and_subject_comes_from_the_operation():
    p = _plan()
    p["tasks"][0]["operations"][0]["path"] = "spa_core/risk/policy.py"
    p["tasks"][0]["owner_subject"] = "none"
    res = gg.validate_plan(_goal(), p, scope=["notes", "spa_core"])
    assert not res["ok"] and any("скрытый предмет" in r for r in res["refusals"])
    assert gg.operation_subject({"op": "write_file", "path": "landing/x.astro"}) == "public"
    assert gg.operation_subject({"op": "delete", "path": "notes/a"}) == "irreversible"
    assert gg.operation_subject({"op": "mystery"}) == "unknown"


def test_owner_subject_needs_owner_and_model_role_never_approves():
    p = _plan()
    p["tasks"][0]["operations"][0]["path"] = "landing/draft.md"
    p["tasks"][0]["check"]["path"] = "landing/draft.md"
    g = gg.validate_plan(_goal(), p, scope=["notes", "landing"])["graph"]
    with pytest.raises(gg.Refused, match="только владелец"):
        gg.approve_task(g, "t1", approver="agent:cycle", role="agent", at=T0, expires_at=EXPIRES)
    with pytest.raises(gg.Refused, match="ответ модели — не разрешение"):
        gg.approve_task(_graph(), "t1", approver="claude", role="model", at=T0, expires_at=EXPIRES)


def test_stale_changed_expired_or_revoked_approval_produces_no_effect(stand, tmp_path):
    g = _graph()
    ap = gg.approve_task(g, "t1", approver="a", role="agent", at=T0, expires_at=EXPIRES)
    assert "срок допуска истёк" in gg.admission(g, "t1", ap, now=LATE)
    assert "допуск отозван" in gg.admission(g, "t1", ap, now=T1, revoked=[gg._sha(ap)])
    assert any("другой задачи" in w for w in gg.admission(g, "t2", ap, now=T1))
    g2 = json.loads(json.dumps(g))
    g2["tasks"]["t1"]["operations"][0]["content"] = "other\n"
    assert "операции изменились после допуска" in gg.admission(g2, "t1", ap, now=T1)
    with pytest.raises(gg.Refused, match="не допущено"):
        gg.execute_on_stand(g, "t1", ap, stand=stand, run_dir=tmp_path / "run", now=LATE, author="w",
                            lease=None)
    assert not (stand / "notes").exists()                               # эффекта нет


def test_action_never_leaves_the_stand_and_never_touches_an_unmarked_tree(tmp_path):
    g = _graph()
    ap = gg.approve_task(g, "t1", approver="a", role="agent", at=T0, expires_at=EXPIRES)
    plain = tmp_path / "work_tree"
    plain.mkdir()
    with pytest.raises(gg.Refused, match="не помечен как стенд"):
        gg.execute_on_stand(g, "t1", ap, stand=plain, run_dir=tmp_path / "run", now=T1, author="w",
                            lease=None)
    assert list(plain.iterdir()) == []


def test_repeat_does_not_create_a_second_effect_and_partial_state_is_not_done(stand, tmp_path):
    run = tmp_path / "run"
    g = _graph()
    ap = gg.approve_task(g, "t1", approver="a", role="agent", at=T0, expires_at=EXPIRES)
    lease = _lease(g, "t1", run)
    first = gg.execute_on_stand(g, "t1", ap, stand=stand, run_dir=run, now=T1, author="w", lease=lease)
    again = gg.execute_on_stand(g, "t1", ap, stand=stand, run_dir=run, now=T1, author="w", lease=lease)
    assert again["repeated"] is True and again["op_key"] == first["op_key"]
    assert len((run / gg.JOURNAL_FILE).read_text().splitlines()) == 3          # claim + started + applied
    assert gg.done_tasks(run, g["version"]) == []                       # applied ≠ done
    with pytest.raises(gg.Refused, match="проверять нечего"):
        gg.machine_result(g, "t2", stand=stand, run_dir=run, now=T1, lease=lease)


def test_machine_result_has_three_distinct_outcomes(stand, tmp_path):
    run = tmp_path / "run"
    p = _plan()
    p["tasks"][1]["check"]["sha256"] = "0" * 64
    g = gg.validate_plan(_goal(), p, scope=["notes"])["graph"]
    leases = {}
    for tid in ("t1", "t2"):
        ap = gg.approve_task(g, tid, approver="a", role="agent", at=T0, expires_at=EXPIRES)
        leases[tid] = _lease(g, tid, run)
        gg.execute_on_stand(g, tid, ap, stand=stand, run_dir=run, now=T1, author="w", lease=leases[tid])
    assert gg.machine_result(g, "t1", stand=stand, run_dir=run, now=T1, lease=leases["t1"])["verdict"] == gg.SATISFIED
    assert gg.machine_result(g, "t2", stand=stand, run_dir=run, now=T1, lease=leases["t2"])["verdict"] == gg.NOT_SATISFIED
    assert gg.done_tasks(run, g["version"]) == ["t1"]                  # неудача не стала done
    # третий исход: проверка не смогла измерить (файл стал каталогом)
    p3 = _plan()
    g3 = gg.validate_plan(_goal(transport_id="msg-9"), p3, scope=["notes"])["graph"]
    run3 = tmp_path / "run3"
    stand3 = tmp_path / "stand3"
    stand3.mkdir()
    (stand3 / ".studio_stand").write_text("x")
    ap = gg.approve_task(g3, "t1", approver="a", role="agent", at=T0, expires_at=EXPIRES)
    l3 = _lease(g3, "t1", run3)
    gg.execute_on_stand(g3, "t1", ap, stand=stand3, run_dir=run3, now=T1, author="w", lease=l3)
    # подмена файла каталогом — не удаление данных: стенд одноразовый, файл переименован рядом
    (stand3 / "notes" / "draft.md").rename(stand3 / "notes" / "draft.md.moved")
    (stand3 / "notes" / "draft.md").mkdir()
    assert gg.machine_result(g3, "t1", stand=stand3, run_dir=run3, now=T1, lease=l3)["verdict"] == gg.UNMEASURED
