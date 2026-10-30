# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — every time is passed as `now`/`at`; the dispatcher gate gets an explicit `now`
"""STUDIO-AUTONOMY-01 S1, приёмка E1/E2/E3 через РЕАЛЬНЫЕ интерфейсы на временных данных.

Процессы — настоящие (`multiprocessing`, `subprocess` CLI), падение на границе записи — настоящий
выход процесса между двумя записями журнала. Рабочий трекер и данные не открываются.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import subprocess
import sys
from pathlib import Path

import pytest

from spa_core.owner_queue import cockpit_dispatch as cd
from spa_core.owner_queue import owner_census as oc
from spa_core.owner_queue import queue as q
from spa_core.studio_os import goal_graph as gg

T0, T1, T2, LATE = ("2026-10-29T10:00:00+00:00", "2026-10-29T10:05:00+00:00",
                    "2026-10-29T10:30:00+00:00", "2026-10-29T12:00:00+00:00")
EXPIRES = "2026-10-29T11:00:00+00:00"
REPO = Path(__file__).resolve().parents[2]


def _goal():
    return gg.goal_record("Подготовь файл на стенде", source="telegram", transport_id="m1", owner="owner",
                          outcome="файл есть", at=T0)


def _graph():
    plan = {"tasks": [{"id": "t1", "outcome": "файл", "check": {"kind": "file_contains", "path": "notes/a.md",
                                                                  "text": "ok"},
                       "operations": [{"op": "write_file", "path": "notes/a.md", "content": "ok\n"},
                                      {"op": "write_file", "path": "notes/b.md", "content": "ok-b\n"}]}]}
    return gg.validate_plan(_goal(), plan, scope=["notes"])["graph"]


def _stand(tmp_path, name="stand"):
    s = tmp_path / name
    s.mkdir()
    (s / ".studio_stand").write_text("stand\n")
    return s


def _ap(g, approver="agent:cycle"):
    return gg.approve_task(g, "t1", approver=approver, role="agent", at=T0, expires_at=EXPIRES)


# ── E2.3 захват: живой чужой — отказ; после перехвата прежний не пишет ─────────────────────────
def test_stale_worker_after_takeover_cannot_write_or_close(tmp_path):
    g, run, stand = _graph(), tmp_path / "run", _stand(tmp_path)
    old = gg.claim(run, g, "t1", worker="w-old", process="p1", now=T0, ttl_s=600)
    with pytest.raises(gg.Conflict, match="держит w-old"):
        gg.claim(run, g, "t1", worker="w-new", process="p2", now=T1, ttl_s=600)
    new = gg.claim(run, g, "t1", worker="w-new", process="p2", now=T2, ttl_s=600)   # после истечения
    assert new["generation"] == old["generation"] + 1 and new["takeover_of"] == old["generation"]
    with pytest.raises(gg.Conflict, match="захват устарел"):
        gg.execute_on_stand(g, "t1", _ap(g), stand=stand, run_dir=run, now=T2, author="w-old", lease=old)
    assert not (stand / "notes").exists()
    gg.execute_on_stand(g, "t1", _ap(g), stand=stand, run_dir=run, now=T2, author="w-new", lease=new)
    with pytest.raises(gg.Conflict, match="захват устарел"):
        gg.machine_result(g, "t1", stand=stand, run_dir=run, now=T2, lease=old)
    assert gg.done_tasks(run, g["version"]) == []


def _claim_proc(run, g, worker, out):
    try:
        lease = gg.claim(Path(run), g, "t1", worker=worker, process=worker, now=T0, ttl_s=600)
        out.put(("ok", lease["generation"]))
    except gg.Conflict:
        out.put(("conflict", worker))


def test_two_processes_claim_the_same_task_exactly_one_wins(tmp_path):
    g, run = _graph(), tmp_path / "run"
    ctx = mp.get_context("fork")
    out = ctx.Queue()
    procs = [ctx.Process(target=_claim_proc, args=(str(run), g, f"w{i}", out)) for i in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
    res = sorted(out.get(timeout=5)[0] for _ in procs)
    assert res.count("ok") == 1 and res.count("conflict") == 3


def test_expected_state_mismatch_is_a_conflict_not_an_overwrite(tmp_path):
    g, run = _graph(), tmp_path / "run"
    lease = gg.claim(run, g, "t1", worker="w", process="p", now=T0, ttl_s=600)
    with pytest.raises(gg.Conflict, match="ожидалось состояние «applied»"):
        gg._transition(run, {"graph_version": g["version"], "task_id": "t1", "state": "checked:satisfied",
                             "at": T1}, expected="applied", lease=lease, now=T1)
    assert gg.task_state(run, g["version"], "t1") == "new"


# ── E2.4 падение между записями + восстановление ─────────────────────────────────────────────────
_CRASH = r"""
import os, sys, json
sys.path.insert(0, {repo!r})
from pathlib import Path
from spa_core.studio_os import goal_graph as gg
g = json.loads(Path({graph!r}).read_text()); ap = json.loads(Path({ap!r}).read_text())
lease = json.loads(Path({lease!r}).read_text())
real = gg._transition
def crash_after_started(run_dir, row, **kw):
    real(run_dir, row, **kw)
    if row["state"] == "started" and {after_first_op!r} == "no":
        os._exit(9)                                           # SIGKILL-подобный выход: finally не исполняется
gg._transition = crash_after_started
orig = gg.os.replace
def replace_then_die(a, b):
    orig(a, b)
    if {after_first_op!r} == "yes":
        os._exit(9)
gg.os.replace = replace_then_die
gg.execute_on_stand(g, "t1", ap, stand=Path({stand!r}), run_dir=Path({run!r}), now={now!r}, author="w", lease=lease)
"""


def _crash_run(tmp_path, after_first_op):
    g, run, stand = _graph(), tmp_path / "run", _stand(tmp_path)
    ap, lease = _ap(g), gg.claim(tmp_path / "run", g, "t1", worker="w", process="p", now=T0, ttl_s=3600)
    files = {}
    for k, v in (("graph", g), ("ap", ap), ("lease", lease)):
        files[k] = tmp_path / f"{k}.json"
        files[k].write_text(json.dumps(v))
    code = _CRASH.format(repo=str(REPO), graph=str(files["graph"]), ap=str(files["ap"]),
                         lease=str(files["lease"]), stand=str(stand), run=str(run), now=T1,
                         after_first_op=after_first_op)
    rc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60).returncode
    assert rc == 9
    return g, run, stand, ap, lease


def test_crash_after_started_blocks_blind_retry_and_recovery_aborts_honestly(tmp_path):
    g, run, stand, ap, lease = _crash_run(tmp_path, after_first_op="no")
    assert gg.task_state(run, g["version"], "t1") == "started"
    assert gg.done_tasks(run, g["version"]) == []                         # незавершённое не done
    with pytest.raises(gg.Refused, match="не завершена"):
        gg.execute_on_stand(g, "t1", ap, stand=stand, run_dir=run, now=T1, author="w", lease=lease)
    rec = gg.recover(g, "t1", stand=stand, run_dir=run, now=T1, author="w", lease=lease)
    assert rec["state"] == "aborted:crash"
    again = gg.recover(g, "t1", stand=stand, run_dir=run, now=T1, author="w", lease=lease)
    assert again["recovered"] is False                                    # повтор восстановления — без записи
    out = gg.execute_on_stand(g, "t1", ap, stand=stand, run_dir=run, now=T1, author="w", lease=lease)
    assert out["state"] == "applied"                                      # новая попытка — явная


def test_crash_mid_operations_partial_effect_is_named_and_not_done(tmp_path):
    g, run, stand, ap, lease = _crash_run(tmp_path, after_first_op="yes")
    assert (stand / "notes" / "a.md").exists() and not (stand / "notes" / "b.md").exists()
    rec = gg.recover(g, "t1", stand=stand, run_dir=run, now=T1, author="w", lease=lease)
    assert rec["state"] == "aborted:crash"
    assert [e["sha256"] is not None for e in rec["effects"]] == [True, False]


def test_recovery_confirms_a_fully_applied_attempt(tmp_path):
    g, run, stand, ap, lease = _crash_run(tmp_path, after_first_op="no")
    for op in g["tasks"]["t1"]["operations"]:                             # эффект дописан до падения журнала
        (stand / op["path"]).parent.mkdir(parents=True, exist_ok=True)
        (stand / op["path"]).write_text(op["content"])
    rec = gg.recover(g, "t1", stand=stand, run_dir=run, now=T1, author="w", lease=lease)
    assert rec["state"] == "applied"
    assert gg.machine_result(g, "t1", stand=stand, run_dir=run, now=T1, lease=lease)["verdict"] == gg.SATISFIED


# ── E3 полномочия ────────────────────────────────────────────────────────────────────────────────
def test_revocation_between_operations_stops_new_effects_and_keeps_the_done_ones(tmp_path):
    g, run, stand = _graph(), tmp_path / "run", _stand(tmp_path)
    lease = gg.claim(run, g, "t1", worker="w", process="p", now=T0, ttl_s=3600)
    calls = {"n": 0}

    def revoked_now():
        calls["n"] += 1
        return calls["n"] > 1                                             # отозвано после первой операции
    out = gg.execute_on_stand(g, "t1", _ap(g), stand=stand, run_dir=run, now=T1, author="w", lease=lease,
                              revoked_now=revoked_now)
    assert out["state"] == "aborted:revoked" and [e["path"] for e in out["effects"]] == ["notes/a.md"]
    assert not (stand / "notes" / "b.md").exists()
    assert gg.done_tasks(run, g["version"]) == []


def test_self_approval_and_uncovered_entries_are_refused(tmp_path):
    g, run, stand = _graph(), tmp_path / "run", _stand(tmp_path)
    lease = gg.claim(run, g, "t1", worker="w", process="p", now=T0, ttl_s=3600)
    with pytest.raises(gg.Refused, match="самодопуск"):
        gg.execute_on_stand(g, "t1", _ap(g, approver="w"), stand=stand, run_dir=run, now=T1, author="w", lease=lease)
    for entry in ("hourly_cycle", "telegram_callbacks", "something_new"):
        with pytest.raises(gg.Refused, match="не охвачен"):
            gg.execute_on_stand(g, "t1", _ap(g), stand=stand, run_dir=run, now=T1, author="w", lease=lease,
                                entry=entry)
    assert not (stand / "notes").exists()


def test_cockpit_dispatcher_takes_a_graph_card_only_with_a_valid_admission(tmp_path):
    g = _graph()
    run = tmp_path / "graph_run"
    run.mkdir()
    (run / "graph.json").write_text(json.dumps(g))
    fm = {"goal_graph_run": str(run), "goal_graph_task": "t1"}
    assert "нет допуска" in cd._goal_graph_gate(fm, now=None)
    (run / "approval.json").write_text(json.dumps(_ap(g)))
    from datetime import datetime
    assert cd._goal_graph_gate(fm, now=datetime.fromisoformat(T1)) is None
    assert "срок допуска истёк" in cd._goal_graph_gate(fm, now=datetime.fromisoformat(LATE))
    assert cd._goal_graph_gate({}, now=None) is False                     # прежний путь не тронут
    (run / "graph.json").write_text("{broken")
    assert "не проверен" in cd._goal_graph_gate(fm, now=None)             # сбой — отказ


def test_cli_is_the_same_contract_end_to_end(tmp_path):
    stand, run = _stand(tmp_path), tmp_path / "run"
    (tmp_path / "goal.json").write_text(json.dumps(_goal()))
    plan = {"tasks": [{"id": "t1", "outcome": "f", "check": {"kind": "file_contains", "path": "notes/a.md", "text": "ok"},
                       "operations": [{"op": "write_file", "path": "notes/a.md", "content": "ok\n"}]}]}
    (tmp_path / "plan.json").write_text(json.dumps(plan))

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "spa_core.studio_os.goal_graph", *args], cwd=REPO,
                              capture_output=True, text=True, timeout=60)
    r = cli("validate", "--goal", str(tmp_path / "goal.json"), "--plan", str(tmp_path / "plan.json"),
            "--scope", "notes", "--out", str(tmp_path / "graph.json"))
    assert r.returncode == 0, r.stderr
    g = json.loads((tmp_path / "graph.json").read_text())
    common = ["--graph", str(tmp_path / "graph.json"), "--task", "t1", "--run-dir", str(run), "--now", T1]
    r = cli("claim", *common, "--worker", "w", "--process", "p", "--ttl", "3600", "--out", str(tmp_path / "lease.json"))
    assert r.returncode == 0, r.stderr
    (tmp_path / "ap.json").write_text(json.dumps(gg.approve_task(g, "t1", approver="a", role="agent", at=T0,
                                                                 expires_at=EXPIRES)))
    st = ["--stand", str(stand), "--lease", str(tmp_path / "lease.json"), "--worker", "w"]
    r = cli("execute", *common, *st, "--approval", str(tmp_path / "ap.json"))
    assert r.returncode == 0 and json.loads(r.stdout)["state"] == "applied", r.stderr
    r = cli("result", *common, *st)
    assert json.loads(r.stdout)["verdict"] == gg.SATISFIED
    bad = cli("validate", "--goal", str(tmp_path / "goal.json"), "--plan", str(tmp_path / "plan.json"),
              "--scope", "other", "--out", str(tmp_path / "g2.json"))
    assert bad.returncode == 1 and "вне объявленного scope" in bad.stderr
    rows = [json.loads(x) for x in (run / gg.JOURNAL_FILE).read_text().splitlines()]
    assert [r.get("entry") for r in rows if r.get("state") == "started"] == ["goal_graph_cli"]


# ── E1.5 выбор следующей работы ──────────────────────────────────────────────────────────────────
def test_select_next_records_a_reason_and_does_not_starve_product_work():
    cands = [{"task_id": "find-1", "kind": "internal", "priority": 1},
             {"task_id": "prod-1", "kind": "product", "priority": 3},
             {"task_id": "inc-1", "kind": "incident", "priority": 5}]
    assert gg.select_next(cands)["task_id"] == "find-1"
    s = gg.select_next(cands, recent_kinds=["product", "internal", "internal"])
    assert s["task_id"] == "prod-1" and "не вытесняется" in s["reason"]
    assert gg.select_next(cands, incident=True, recent_kinds=["internal"] * 5)["task_id"] == "inc-1"
    assert gg.select_next([])["task_id"] is None


# ── E2.2 общий протокол записи статуса карточки ──────────────────────────────────────────────────
_CARD = "---\ntitle: t\nstatus: backlog\ntrackerStatus:\n  type: agent-task\n---\nbody\n"


def test_set_status_refuses_a_stale_revision_and_keeps_the_other_writers_bytes(tmp_path):
    card = tmp_path / "agent-x.md"
    card.write_text(_CARD)
    rev = q.card_revision(card)
    card.write_text(_CARD.replace("body", "body edited by the owner"))      # посторонняя правка
    with pytest.raises(q.StaleCardRevision):
        q.set_status(card, "in-progress", expected_revision=rev)
    assert "edited by the owner" in card.read_text() and "status: backlog" in card.read_text()
    q.set_status(card, "in-progress", expected_revision=q.card_revision(card))
    assert "status: in-progress" in card.read_text() and "edited by the owner" in card.read_text()


def _set_proc(card, rev, out):
    try:
        q.set_status(card, "in-progress", expected_revision=rev)
        out.put("ok")
    except q.StaleCardRevision:
        out.put("stale")


def test_two_writers_with_the_same_read_revision_one_wins_one_is_refused(tmp_path):
    card = tmp_path / "agent-y.md"
    card.write_text(_CARD)
    rev = q.card_revision(card)
    ctx = mp.get_context("fork")
    out = ctx.Queue()
    ps = [ctx.Process(target=_set_proc, args=(str(card), rev, out)) for _ in range(3)]
    for p in ps:
        p.start()
    for p in ps:
        p.join(30)
    res = sorted(out.get(timeout=5) for _ in ps)
    assert res == ["ok", "stale", "stale"]
    assert not any(p.name.endswith(".lock") for p in tmp_path.iterdir())   # трекер без посторонних файлов


# ── E1.4 разбор очереди владельца ────────────────────────────────────────────────────────────────
def test_owner_census_classifies_everyone_and_the_sum_matches(tmp_path):
    t = tmp_path / "tracker"
    t.mkdir()
    cards = {
        "owner-decision-a": "status: needs-owner",
        "owner-decision-b": "status: ingested\nowner_choice: 1",
        "owner-decision-c": "status: ingested\nclosed_by_class: ADR-285",
        "own-d": "status: owner-done",
        "inbox-e": "status: needs-owner",
        "inbox-f": "status: new",
    }
    for name, fm in cards.items():
        (t / f"{name}.md").write_text(f"---\ntitle: {name}\n{fm}\n---\nbody\n")
    res = oc.census(t)
    assert res["population"] == 4                                         # own-d терминальна, inbox-f не владельцу
    assert res["counts"]["needs_decision"] == 2 and res["counts"]["answer_recorded"] == 1
    assert res["counts"]["agent_work"] == 1 and sum(res["counts"].values()) == res["population"]
    assert oc.census(tmp_path / "nope")["measured"] is False


# ── E3.4 ответ кнопкой относится к той версии вопроса, что была отправлена ─────────────────────
_Q = ("---\ntitle: Вопрос\nstatus: needs-owner\ntrackerStatus:\n  type: owner-decision\n---\n"
      "## Что случилось и почему это важно\nX.\n## Что от тебя нужно\n1. Да\n2. Нет\n")


def _push_journal(tmp_path, card, version):
    j = tmp_path / "pushes.json"
    j.write_text(json.dumps({"pushes": [{"pid": "p1", "card": str(card), "card_id": card.stem,
                                         "options": [{"num": "1", "label": "Да"}], "choice": None,
                                         "question_sha256": version}]}))
    return j


def test_button_answer_to_a_changed_question_is_not_written(tmp_path):
    from spa_core.owner_queue.owner_answer import question_version
    from spa_core.telegram import owner_decisions as od
    card = tmp_path / "owner-decision-q.md"
    card.write_text(_Q)
    journal = _push_journal(tmp_path, card, question_version(_Q))
    card.write_text(_Q.replace("X.", "X изменён после отправки."))         # вопрос поменяли
    res = od.record_choice("p1", "1", "42", owner_chat_id="42", state_path=journal)
    assert res == {"ok": False, "reason": "question_changed", "card": str(card)}
    assert "status: needs-owner" in card.read_text() and "owner_choice" not in card.read_text()
    assert "question_changed" in od.PRESERVE_ON_REFUSAL                   # слова владельца сохраняются


def test_button_answer_to_the_sent_version_is_written_and_identity_still_checked(tmp_path):
    from spa_core.owner_queue.owner_answer import question_version
    from spa_core.telegram import owner_decisions as od
    card = tmp_path / "owner-decision-q.md"
    card.write_text(_Q)
    journal = _push_journal(tmp_path, card, question_version(_Q))
    assert od.record_choice("p1", "1", "99", owner_chat_id="42", state_path=journal)["reason"] == "not_owner"
    res = od.record_choice("p1", "1", "42", owner_chat_id="42", state_path=journal)
    assert res["ok"] is True and "owner_choice" in card.read_text()


# ── E2.6 редакторы frontmatter на общем протоколе ───────────────────────────────────────────────
def _slow_editor(card, out):
    import time
    try:
        with q.card_write_lock(card):                                   # держим, как редактор между чтением и записью
            text = Path(card).read_text()
            time.sleep(0.6)
            Path(card).write_text(text.replace("title: t", "title: t\ndispatch: taken"))
        out.put("edited")
    except Exception as exc:  # noqa: BLE001
        out.put(f"err {exc}")


def _status_writer(card, out):
    import time
    time.sleep(0.2)                                                     # стартует, пока редактор держит карточку
    q.set_status(card, "in-progress")
    out.put("status")


def test_editor_and_set_status_in_two_processes_lose_no_update(tmp_path):
    card = tmp_path / "agent-z.md"
    card.write_text(_CARD)
    ctx = mp.get_context("fork")
    out = ctx.Queue()
    ps = [ctx.Process(target=_slow_editor, args=(str(card), out)),
          ctx.Process(target=_status_writer, args=(str(card), out))]
    for p in ps:
        p.start()
    for p in ps:
        p.join(30)
    assert sorted(out.get(timeout=5) for _ in ps) == ["edited", "status"]
    text = card.read_text()
    assert "dispatch: taken" in text and "status: in-progress" in text   # обе правки на месте


def test_nested_write_in_the_same_thread_does_not_deadlock(tmp_path):
    card = tmp_path / "agent-n.md"
    card.write_text(_CARD)
    with q.card_write_lock(card):
        q.set_status(card, "in-progress")                               # вложенный писатель
    assert "status: in-progress" in card.read_text()


def test_every_mapped_card_editor_carries_the_shared_lock():
    import inspect
    from spa_core.owner_queue import cockpit_loop, intake, owner_answer
    from spa_core.telegram import owner_decisions
    for fn in (cockpit_loop._set_fields, intake._stamp_seen, owner_answer._write_answer,
               owner_decisions.refresh_live_copy_from_ref):
        assert getattr(fn, "__card_writer__", False), fn.__name__
    assert "card_write_lock(target)" in inspect.getsource(owner_decisions.materialize_card)
    src = (REPO / "scripts" / "check_card_claim.py").read_text(encoding="utf-8")
    assert "with card_write_lock(path):" in src
    assert "_card_write_lock(path, expected_revision)" in inspect.getsource(q.set_status)
