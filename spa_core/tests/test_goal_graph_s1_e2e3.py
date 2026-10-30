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


def _hold_lock(card, held, hold_s):
    import time
    with q.card_write_lock(card):
        held.set()
        time.sleep(hold_s)


def test_every_mapped_card_editor_waits_for_the_shared_lock(tmp_path):
    """ПОВЕДЕНИЕ, а не пометка (R1): пока другой процесс держит общую блокировку карточки,
    писатель ждёт — запись не происходит раньше, чем блокировка отпущена."""
    import time
    from datetime import datetime, timezone
    from spa_core.owner_queue import cockpit_loop, intake
    guard = _guard()
    writers = {
        "cockpit_loop._set_fields": lambda c: cockpit_loop._set_fields(c, {"dispatch": "taken"}),
        "intake._stamp_seen": lambda c: intake._stamp_seen(c, datetime(2026, 10, 30, tzinfo=timezone.utc)),
        "check_card_claim._atomic_write": lambda c: guard._atomic_write(c, Path(c).read_text() + "x\n"),
        "queue.set_acceptance_probe": lambda c: q.set_acceptance_probe(c, "tier_promotion_loop_closed"),
    }
    ctx = mp.get_context("fork")
    for name, write in writers.items():
        card = tmp_path / f"agent-{name.replace('.', '-')}.md"
        card.write_text(_CARD)
        held = ctx.Event()
        holder = ctx.Process(target=_hold_lock, args=(str(card), held, 1.0))
        holder.start()
        assert held.wait(10)
        t0 = time.monotonic()
        before = card.read_bytes()
        try:
            write(card)
        except Exception:  # noqa: BLE001 — предмет теста ожидание, а не принятие правки
            pass
        waited = time.monotonic() - t0
        holder.join(10)
        assert waited >= 0.7, f"{name} не ждал общую блокировку ({waited:.2f} с)"
        del before
    # Писатели, чью запись в изоляции не поднять, держат ту же пометку протокола.
    from spa_core.owner_queue import owner_answer
    from spa_core.telegram import owner_decisions
    for fn in (owner_answer._write_answer, owner_decisions.refresh_live_copy_from_ref,
               owner_decisions.materialize_card):
        assert getattr(fn, "__card_writer__", False), fn.__name__


# ── E2 (writer_map п. 4): создание карточки — имя занимается одним атомарным шагом ──────────────
def _creator(tracker, i, out):
    p = q.create_card("inbox", "Одна и та же задача", f"тело {i}",
                      tracker_dir=tracker, merge_open_twin=False)
    out.put((str(p), i))


def test_concurrent_create_card_never_overwrites_a_sibling(tmp_path):
    ctx = mp.get_context("fork")
    out = ctx.Queue()
    ps = [ctx.Process(target=_creator, args=(tmp_path, i, out)) for i in range(8)]
    for p in ps:
        p.start()
    for p in ps:
        p.join(30)
    got = [out.get(timeout=5) for _ in ps]
    paths = {p for p, _ in got}
    assert len(paths) == 8                                              # 8 создателей — 8 карточек
    for path, i in got:
        assert f"тело {i}" in Path(path).read_text()                    # ни одна не затёрта соседом
    assert not list(tmp_path.glob("*.tmp"))                             # временные файлы убраны


def test_create_card_takes_the_next_suffix_when_the_name_is_taken(tmp_path):
    first = q.create_card("inbox", "Задача", "a", tracker_dir=tmp_path,
                          merge_open_twin=False)
    second = q.create_card("inbox", "Задача", "b", tracker_dir=tmp_path,
                           merge_open_twin=False)
    assert first != second and second.stem.endswith("-2")
    assert "a" in first.read_text() and "b" in second.read_text()


# ── E2.6: охват писателей и ворота опасной общей операции ────────────────────────────────────────
_EXPECTED_COVERED = {
    "spa_core/owner_queue/queue.py::set_status", "spa_core/owner_queue/queue.py::create_card",
    "spa_core/owner_queue/queue.py::set_acceptance_probe",
    "spa_core/owner_queue/cockpit_loop.py::_set_fields", "spa_core/owner_queue/intake.py::_stamp_seen",
    "spa_core/owner_queue/owner_answer.py::_write_answer",
    "spa_core/telegram/owner_decisions.py::refresh_live_copy_from_ref",
    "spa_core/telegram/owner_decisions.py::materialize_card",
    "scripts/check_card_claim.py::_atomic_write",
}


def test_writer_coverage_names_every_writer_and_the_one_left_outside():
    cov = q.card_writer_coverage()
    assert set(cov["covered"]) == _EXPECTED_COVERED
    assert cov["uncovered"] == ["scripts/repair_phantom_intake_cards.py::repair"]
    assert cov["unmeasured"] == [] and cov["complete"] is False


def test_unreadable_writer_is_unmeasured_not_covered():
    cov = q.card_writer_coverage((("spa_core/owner_queue/queue.py", "set_status"),
                                  ("spa_core/owner_queue/no_such_module.py", "write")))
    assert cov["covered"] == ["spa_core/owner_queue/queue.py::set_status"]
    assert [u["writer"] for u in cov["unmeasured"]] == ["spa_core/owner_queue/no_such_module.py::write"]
    assert cov["complete"] is False


def test_gate_closed_on_the_live_tracker_open_on_a_copy_and_open_at_full_coverage(tmp_path, monkeypatch):
    live = tmp_path / "live"
    live.mkdir()
    monkeypatch.setattr(q, "TRACKER_DIR", live)                         # живой трекер — подменён на tmp
    closed = q.shared_tracker_operation_gate("op", live)
    assert closed["allowed"] is False and "repair_phantom_intake_cards.py::repair" in closed["why"]
    (tmp_path / "copy").mkdir()
    assert q.shared_tracker_operation_gate("op", tmp_path / "copy")["allowed"] is True
    monkeypatch.setattr(q, "CARD_WRITERS", tuple(w for w in q.CARD_WRITERS
                                                 if not w[0].endswith("repair_phantom_intake_cards.py")))
    monkeypatch.setattr(q.card_writer_coverage, "__defaults__", (q.CARD_WRITERS,))
    assert q.shared_tracker_operation_gate("op", live)["allowed"] is True   # положительный контроль


def test_repair_apply_on_the_live_tracker_is_refused_and_writes_nothing(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_rp", Path(q.__file__).resolve().parents[2] / "scripts" / "repair_phantom_intake_cards.py")
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)
    card = tmp_path / "owner-decision-x.md"
    card.write_text(_CARD)
    before = card.read_bytes()
    monkeypatch.setattr(q, "TRACKER_DIR", tmp_path)
    assert rp.main(["--tracker-dir", str(tmp_path), "--apply"]) == 3
    assert card.read_bytes() == before and sorted(p.name for p in tmp_path.iterdir()) == [card.name]


# ── E2 приёмка: SIGKILL держателя блокировки на границе записи ──────────────────────────────────
def _killed_holder(card, ready):
    import os
    import time
    with q.card_write_lock(card):
        Path(str(card) + ".partial.tmp").write_text("недописано")      # шаг записи начат
        ready.set()
        time.sleep(60)
        os._exit(0)                                                     # сюда не доходит


def test_sigkill_of_the_lock_holder_neither_blocks_nor_corrupts_the_card(tmp_path):
    import os
    import signal
    import time
    card = tmp_path / "agent-k.md"
    card.write_text(_CARD)
    ctx = mp.get_context("fork")
    ready = ctx.Event()
    holder = ctx.Process(target=_killed_holder, args=(str(card), ready))
    holder.start()
    assert ready.wait(10)
    os.kill(holder.pid, signal.SIGKILL)
    holder.join(10)
    assert card.read_text() == _CARD                                    # карточка цела: старые байты
    t0 = time.monotonic()
    q.set_status(card, "in-progress")                                   # блокировка освобождена ОС
    assert time.monotonic() - t0 < 5
    assert "status: in-progress" in card.read_text()


def test_create_exclusive_does_not_overwrite_a_name_taken_after_the_check(tmp_path, monkeypatch):
    """Детерминированная гонка: имя занято соседом МЕЖДУ проверкой и записью."""
    target = tmp_path / "inbox-x.md"
    target.write_text("сосед успел первым")
    monkeypatch.setattr(Path, "exists", lambda self: False if self == target else Path.is_file(self)
                        or Path.is_dir(self))
    assert q._create_exclusive(target, "мой текст") is False
    assert target.read_text() == "сосед успел первым"
    assert not list(tmp_path.glob("*.tmp"))


# ── R1 (ARB 30.10): общий протокол охватывает ЧТЕНИЕ → проверку → запись у claim/release ─────────
def _guard():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_r1_guard", Path(q.__file__).resolve().parents[2] / "scripts" / "check_card_claim.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _QuietAnnouncer:
    """Фиктивный объявитель: общий журнал объявлений в тесте не трогается."""
    RUN_ID_FIELD = "run_id"

    def record(self, **kw):
        return None


def _pause_after_read(guard, read_done, hold_s=1.0):
    """Управляемая точка МЕЖДУ чтением карточки и заменой: сигнал соседу и пауза."""
    import time
    real = guard._set_claim_fields

    def paused(text, values):
        read_done.set()
        time.sleep(hold_s)
        return real(text, values)
    guard._set_claim_fields = paused


def _protocol_editor(card, read_done, out):
    """Сторонний писатель на общем протоколе: правит карточку, как только сосед прочитал её."""
    assert read_done.wait(20)
    with q.card_write_lock(card):
        text = Path(card).read_text(encoding="utf-8")
        Path(card).write_text(text.replace("---\n\n", "owner_note: changed-by-owner\n---\n\n", 1)
                              if "---\n\n" in text else text + "\nowner_note: changed-by-owner\n",
                              encoding="utf-8")
    out.put("edited")


_HELD = ("---\ntrackerStatus:\n  type: inbox\ntitle: t\nstatus: in-progress\n"
         "claimed_by: me\nclaimed_at: 2026-10-30T08:00:00Z\n---\n\nтело\n")


def _releaser(card, tracker, log, read_done, out):
    guard = _guard()
    _pause_after_read(guard, read_done)
    res = guard.release_card(card, log=log, session="me", tracker_dir=tracker, self_anchor=None,
                             announcer=_QuietAnnouncer())
    out.put("released" if res.get("released") else f"not released {res}")


def test_release_card_does_not_overwrite_a_protocol_writer_between_read_and_replace(tmp_path):
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    card = tracker / "inbox-r1.md"
    card.write_text(_HELD, encoding="utf-8")
    log = tmp_path / "log.jsonl"
    log.write_text("")
    ctx = mp.get_context("fork")
    read_done, out = ctx.Event(), ctx.Queue()
    ps = [ctx.Process(target=_releaser, args=(str(card), tracker, log, read_done, out)),
          ctx.Process(target=_protocol_editor, args=(str(card), read_done, out))]
    for p in ps:
        p.start()
    for p in ps:
        p.join(60)
    assert sorted(out.get(timeout=5) for _ in ps) == ["edited", "released"]
    text = card.read_text(encoding="utf-8")
    assert "owner_note: changed-by-owner" in text, "правка стороннего писателя затёрта"
    assert "claimed_by" not in text                                     # и снятие на месте


def _claimer(tracker, log, read_done, out):
    from spa_core.tests import test_card_claim_frontmatter_release as sc
    guard = _guard()
    _pause_after_read(guard, read_done)
    guard.claim_card(tracker / f"{sc.CARD}.md", log=log, tracker_dir=tracker,
                     sibling=guard.load_sibling(), session="cycle-808", now=sc.NOW,
                     grace_hours=3.0, ps=sc.DEAD, self_anchor=sc.SELF_ANCHOR,
                     announcer=_QuietAnnouncer())
    out.put("claimed")


def test_claim_card_does_not_overwrite_a_protocol_writer_between_read_and_replace(tmp_path):
    from spa_core.tests import test_card_claim_frontmatter_release as sc
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    log = tmp_path / "session_changes.jsonl"
    sc._scene(tracker, log)
    card = tracker / f"{sc.CARD}.md"
    ctx = mp.get_context("fork")
    read_done, out = ctx.Event(), ctx.Queue()
    ps = [ctx.Process(target=_claimer, args=(tracker, log, read_done, out)),
          ctx.Process(target=_protocol_editor, args=(str(card), read_done, out))]
    for p in ps:
        p.start()
    for p in ps:
        p.join(60)
    assert sorted(out.get(timeout=5) for _ in ps) == ["claimed", "edited"]
    text = card.read_text(encoding="utf-8")
    assert "owner_note: changed-by-owner" in text, "правка стороннего писателя затёрта"
    assert "claimed_by: cycle-808" in text


def test_missing_protocol_refuses_before_any_write(tmp_path, monkeypatch):
    guard = _guard()
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    card = tracker / "inbox-r1.md"
    card.write_text(_HELD, encoding="utf-8")
    before = card.read_bytes()
    monkeypatch.setitem(sys.modules, "spa_core.owner_queue.queue", None)   # import ⇒ ImportError
    with pytest.raises(guard.SharedProtocolUnavailable):
        guard.release_card(card, log=tmp_path / "log.jsonl", session="me", tracker_dir=tracker,
                           self_anchor=None, announcer=_QuietAnnouncer())
    with pytest.raises(guard.SharedProtocolUnavailable):
        guard._atomic_write(card, "затёрто")
    assert card.read_bytes() == before
    assert sorted(p.name for p in tracker.iterdir()) == [card.name]     # и временных файлов нет


# ── R2 (ARB 30.10): неизвестный корень — не испытательная копия ────────────────────────────────
def test_unknown_root_outside_temp_is_refused(tmp_path):
    outside = Path.home() / ".spa_r2_never_created_dir"
    gate = q.shared_tracker_operation_gate("op", outside)
    assert gate["allowed"] is False and "вне временного каталога" in gate["why"]


def test_changing_the_configured_tracker_does_not_make_the_repo_tracker_a_copy(monkeypatch, tmp_path):
    monkeypatch.setattr(q, "TRACKER_DIR", tmp_path / "configured")
    repo_tracker = Path(q.__file__).resolve().parents[2] / "nimbalyst-local" / "tracker"
    gate = q.shared_tracker_operation_gate("op", repo_tracker)
    assert gate["allowed"] is False                                     # рабочий корень, охват неполон
    assert "охват писателей" in gate["why"]


def test_symlink_into_a_production_root_is_refused(tmp_path, monkeypatch):
    prod = tmp_path / "prod_tracker"
    prod.mkdir()
    monkeypatch.setattr(q, "TRACKER_DIR", prod)
    link = tmp_path / "looks_like_a_copy"
    link.symlink_to(prod)
    assert q.shared_tracker_operation_gate("op", link)["allowed"] is False


def test_copy_containing_a_production_root_is_refused(tmp_path, monkeypatch):
    outer = tmp_path / "outer"
    (outer / "inner_prod").mkdir(parents=True)
    monkeypatch.setattr(q, "TRACKER_DIR", outer / "inner_prod")
    gate = q.shared_tracker_operation_gate("op", outer)
    assert gate["allowed"] is False and "пересекается" in gate["why"]


def test_card_links_break_isolation(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "agent-a.md").write_text(_CARD)
    copy = tmp_path / "copy"
    copy.mkdir()
    import os
    os.link(work / "agent-a.md", copy / "agent-a.md")                  # жёсткая ссылка на «рабочий» файл
    gate = q.shared_tracker_operation_gate("op", copy)
    assert gate["allowed"] is False and "жёсткая ссылка" in gate["why"]
    copy2 = tmp_path / "copy2"
    copy2.mkdir()
    (copy2 / "agent-a.md").symlink_to(work / "agent-a.md")
    assert q.shared_tracker_operation_gate("op", copy2)["allowed"] is False
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "agent-a.md").write_text(_CARD)
    assert q.shared_tracker_operation_gate("op", clean)["allowed"] is True   # положительный контроль


# ── R3 (ARB 30.10): версия вопроса сверяется ВНУТРИ транзакции записи ответа ────────────────────
_Q_NEW = _Q.replace("X.", "X изменён после показа владельцу.")


def test_question_changed_after_the_fast_check_is_refused_inside_the_write(tmp_path, monkeypatch):
    """Детерминированная гонка: быстрая сверка прошла, вопрос изменён ДО записи."""
    from spa_core.owner_queue.owner_answer import question_version
    from spa_core.telegram import owner_decisions as od
    card = tmp_path / "owner-decision-q.md"
    card.write_text(_Q)
    journal = _push_journal(tmp_path, card, question_version(_Q))
    real = od._question_version_of

    def check_then_change(c):
        v = real(c)                                                     # быстрая сверка видит старый вопрос
        with q.card_write_lock(card):                                   # сосед на общем протоколе меняет его
            card.write_text(_Q_NEW)
        return v
    monkeypatch.setattr(od, "_question_version_of", check_then_change)
    res = od.record_choice("p1", "1", "42", owner_chat_id="42", state_path=journal)
    assert res == {"ok": False, "reason": "question_changed", "card": str(card)}
    assert card.read_text() == _Q_NEW                                   # правка соседа цела, ответа нет
    assert json.loads(journal.read_text())["pushes"][0]["choice"] is None


def _change_question_while_press_waits(card, go, out):
    assert go.wait(20)
    with q.card_write_lock(card):
        Path(card).write_text(_Q_NEW)
    out.put("changed")


def _press_after_fast_check(card, journal, go, out):
    import time
    from spa_core.telegram import owner_decisions as od
    real = od._question_version_of

    def check_then_wait(c):
        v = real(c)
        go.set()                                                        # сосед меняет вопрос
        time.sleep(1.0)
        return v
    od._question_version_of = check_then_wait
    out.put(od.record_choice("p1", "1", "42", owner_chat_id="42", state_path=journal)["reason"]
            if True else None)


def test_two_processes_question_change_between_press_and_write_is_not_answered(tmp_path):
    from spa_core.owner_queue.owner_answer import question_version
    card = tmp_path / "owner-decision-q.md"
    card.write_text(_Q)
    journal = _push_journal(tmp_path, card, question_version(_Q))
    ctx = mp.get_context("fork")
    go, out = ctx.Event(), ctx.Queue()
    ps = [ctx.Process(target=_press_after_fast_check, args=(str(card), journal, go, out)),
          ctx.Process(target=_change_question_while_press_waits, args=(str(card), go, out))]
    for p in ps:
        p.start()
    for p in ps:
        p.join(60)
    assert sorted(out.get(timeout=5) for _ in ps) == ["changed", "question_changed"]
    assert Path(card).read_text() == _Q_NEW and "owner_choice" not in Path(card).read_text()


def test_heal_records_the_version_of_the_text_it_sent_not_a_fresh_read(tmp_path, monkeypatch):
    """Фиктивный отправитель меняет карточку во время отправки досылки: в журнал уходит
    версия ОТПРАВЛЕННОГО текста, и нажатие по ней на изменённый вопрос — отказ."""
    from spa_core.owner_queue.owner_answer import question_version
    from spa_core.telegram import owner_decisions as od
    card = tmp_path / "owner-decision-q.md"
    card.write_text(_Q)
    journal = _push_journal(tmp_path, card, None)
    sent_version = question_version(_Q)
    heal = od.Heal(pid="p1", card=str(card), text="досылка: " + _Q, keyboard={"k": 1},
                   options=[od.ParsedOption(num="1", label="Да", recommended=False)],
                   ack=False, question_sha256=sent_version)
    monkeypatch.setattr(od, "buttonless_pushes", lambda **kw: [heal])
    sent = []

    def fake_send(text, keyboard):
        sent.append(text)
        card.write_text(_Q_NEW)                                         # вопрос изменился ВО ВРЕМЯ отправки
        return {"message_id": 7}
    assert od.heal_buttonless(fake_send, state_path=journal) == ["p1"]
    rec = json.loads(journal.read_text())["pushes"][0]
    assert rec["question_sha256"] == sent_version != question_version(_Q_NEW)
    # R3b: нажатие идёт настоящей меткой досланного снимка (``<номер>@<версия>``);
    # кнопка без метки на записи со снимками отвергается отдельно (version_unknown).
    res = od.record_choice("p1", "1" + od.VERSION_SEP + od.version_tag(sent_version), "42",
                           owner_chat_id="42", state_path=journal)
    assert res["reason"] == "question_changed" and "owner_choice" not in card.read_text()


def test_heal_built_from_the_card_body_carries_that_bodys_version(tmp_path):
    from spa_core.owner_queue.owner_answer import question_version
    from spa_core.owner_queue.queue import load_card
    from spa_core.telegram import owner_decisions as od
    card = tmp_path / "owner-decision-q.md"
    card.write_text(_Q)
    assert od._question_version_of_text(load_card(card).body) == question_version(_Q)


def test_register_push_versions_the_shown_body(tmp_path, monkeypatch):
    from spa_core.owner_queue.owner_answer import question_version
    from spa_core.owner_queue.queue import load_card
    from spa_core.telegram import owner_decisions as od
    card = tmp_path / "owner-decision-q.md"
    card.write_text(_Q)
    journal = tmp_path / "pushes.json"
    monkeypatch.setattr(od, "materialize_card", lambda p, live_root=None: Path(p))
    shown = load_card(card).body
    card.write_text(_Q_NEW)                                             # файл уже другой, показан — прежний
    od.register_push(card, "Вопрос", shown, state_path=journal, beacon_path=tmp_path / "no_beacon.json")
    rec = json.loads(journal.read_text())["pushes"][-1]
    assert rec["question_sha256"] == question_version(_Q) != question_version(_Q_NEW)


def test_legacy_record_without_version_is_a_named_limit_not_invented_consent(tmp_path):
    from spa_core.telegram import owner_decisions as od
    card = tmp_path / "owner-decision-q.md"
    card.write_text(_Q)
    journal = _push_journal(tmp_path, card, None)
    rec = json.loads(journal.read_text())["pushes"][0]
    assert rec["question_sha256"] is None                               # версия не выдумывается
    res = od.record_choice("p1", "1", "42", owner_chat_id="42", state_path=journal)
    assert res["ok"] is True                                            # предел: сверки нет (ADR-857)
    assert json.loads(journal.read_text())["pushes"][0].get("question_sha256") is None


def test_claim_with_missing_protocol_is_refused_before_it_is_announced(tmp_path, monkeypatch):
    from spa_core.tests import test_card_claim_frontmatter_release as sc
    guard = _guard()
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    log = tmp_path / "session_changes.jsonl"
    sc._scene(tracker, log)
    card = tracker / f"{sc.CARD}.md"
    before = card.read_bytes()
    calls = []

    class _Recording(_QuietAnnouncer):
        def record(self, **kw):
            calls.append(kw)
    sibling = guard.load_sibling()
    monkeypatch.setitem(sys.modules, "spa_core.owner_queue.queue", None)
    with pytest.raises(guard.SharedProtocolUnavailable):
        guard.claim_card(card, log=log, tracker_dir=tracker, sibling=sibling,
                         session="cycle-808", now=sc.NOW, grace_hours=3.0, ps=sc.DEAD,
                         self_anchor=sc.SELF_ANCHOR, announcer=_Recording())
    assert calls == [], "захват объявлен, хотя записать его нельзя"
    assert card.read_bytes() == before
