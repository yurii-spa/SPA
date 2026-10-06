"""spa_core/tests/test_claude_work_derivation.py — RM-TRUTH-01 / ADR-580 Director OS v2 design
§3: "what is Claude working on", derived purely from ``data/session_changes.jsonl`` + the house
liveness rule (``scripts/check_undelivered_work.session_state`` — loaded, never copied). Every
host door (``ps``, ``cmd_probe``) is injected; nothing here touches the real machine.
"""
from __future__ import annotations

from datetime import datetime, timezone

from spa_core.studio_os import company_truth as ct

NOW = datetime(2026, 10, 5, 14, 0, 0, tzinfo=timezone.utc)
LSTART = "Mon Oct  5 13:00:00 2026"


def _fake_ps_alive(pid):
    return (0, LSTART)


def _fake_ps_dead(pid):
    return (1, "")


def _fake_cmd(pid):
    return (0, "/usr/bin/python3 -m spa_core.something")


def _entry(session, card=None, card_state="claim", pid=4242, summary="working"):
    e = {"session": session, "ts": "2026-10-05T13:00:05Z", "summary": summary,
         "session_pid": pid, "session_pid_start": LSTART}
    if card:
        e["card"] = card
        e["card_state"] = card_state
    return e


def _tracker(card_id, title="Карточка", status="in-progress", body="", **extra):
    return {f"{card_id}.md": {"fm": {"title": title, "status": status, **extra}, "body": body,
                              "trail": [], "path": None}}


def test_active_claim_gives_card_stage_and_blocker():
    tracker = _tracker("agent-fix-thing", title="Исправить сторожа", status="blocked")
    log = [_entry("cycle-1", card="agent-fix-thing")]

    def lineage_fn(q):
        return {"state": "FOUND", "stages": {"IDEA": {"state": "DONE"}, "TASK": {"state": "DONE"},
                                             "ASSIGNED": {"state": "DONE"}, "RUN": {"state": "DONE"},
                                             "ARTIFACT": {"state": "MISSING"}}}

    out = ct.claude_work(log, tracker, {"current": {"epic": "RM-TRUTH-01"}}, lineage_fn, None, NOW,
                         total_claude_processes=1, measure_host=True, ps_probe=_fake_ps_alive, cmd_probe=_fake_cmd)
    assert out["state"] == ct.MEASURED
    assert len(out["active"]) == 1
    a = out["active"][0]
    assert a["card"] == "agent-fix-thing" and a["card_title"] == "Исправить сторожа"
    assert a["stage"] == "ARTIFACT"
    assert a["blocker"] == "статус карточки blocked"
    assert out["epic"] == "RM-TRUTH-01"
    assert "RM-TRUTH-01" in out["display_ru"]


def test_done_record_gives_no_active_work():
    log = [_entry("cycle-2", card="agent-x", card_state="done")]
    out = ct.claude_work(log, {}, {"current": None}, lambda q: None, None, NOW, total_claude_processes=0,
                         measure_host=True, ps_probe=_fake_ps_alive, cmd_probe=_fake_cmd)
    assert out["active"] == []
    assert out["state"] == ct.MEASURED_ZERO


def test_dead_pid_is_not_confirmed_and_not_shown_active():
    log = [_entry("cycle-3", card="agent-y")]
    out = ct.claude_work(log, {}, {"current": None}, lambda q: None, None, NOW, total_claude_processes=0,
                         measure_host=True, ps_probe=_fake_ps_dead, cmd_probe=_fake_cmd)
    assert out["active"] == []
    assert out["state"] == ct.MEASURED_ZERO


def test_no_log_is_not_measured():
    out = ct.claude_work(None, {}, {"current": None}, lambda q: None, None, NOW, total_claude_processes=0)
    assert out["state"] == ct.NOT_MEASURED
    assert out["display_ru"] == out["unknown_ru"]


def test_two_processes_one_announced_gives_undeclared_one():
    log = [_entry("cycle-4", card="agent-z")]
    out = ct.claude_work(log, {}, {"current": None}, lambda q: None, None, NOW, total_claude_processes=2,
                         measure_host=True, ps_probe=_fake_ps_alive, cmd_probe=_fake_cmd)
    assert len(out["active"]) == 1
    assert out["undeclared"] == 1


def test_epic_is_the_in_progress_roadmap_item_never_the_first_queued():
    """Regression of the live C1 defect: no IN_PROGRESS epic ⇒ 'эпик в работе не объявлен',
    never the first QUEUED roadmap item standing in for it."""
    roadmap = {"items": [{"n": 1, "epic": "Something queued", "state": "QUEUED"}], "current": None}
    out = ct.claude_work([], {}, roadmap, lambda q: None, None, NOW, total_claude_processes=0, measure_host=True)
    assert out["epic"] is None
    assert "Something queued" not in str(out)


def test_measure_host_false_gives_liveness_unknown_not_dead():
    log = [_entry("cycle-5", card="agent-w")]
    out = ct.claude_work(log, {}, {"current": None}, lambda q: None, None, NOW, total_claude_processes=0,
                         measure_host=False)
    assert out["active"] == []
    assert out["state"] == ct.NOT_MEASURED
    assert "не удалось проверить" in out["display_ru"]


def test_next_step_falls_back_to_the_lineage_next_stage_when_no_section_in_the_card():
    tracker = _tracker("agent-fallback", body="без секции следующего шага")

    def lineage_fn(q):
        return {"state": "FOUND", "stages": {s: {"state": "DONE"} for s in
                                             ("IDEA", "TASK", "ASSIGNED", "RUN")} | {"ARTIFACT": {"state": "MISSING"}}}
    log = [_entry("cycle-6", card="agent-fallback")]
    out = ct.claude_work(log, tracker, {"current": None}, lineage_fn, None, NOW, total_claude_processes=1,
                         measure_host=True, ps_probe=_fake_ps_alive, cmd_probe=_fake_cmd)
    a = out["active"][0]
    assert a["stage"] == "ARTIFACT"
    assert "REVIEW" in a["next_step"] or "проверка" in a["next_step"]


def test_blocker_from_open_problem_matching_card_owner():
    tracker = _tracker("agent-blocked-by-problem", owner="agent_health")
    problems = {"problems": {"k1": {"status": "OPEN", "agent": "agent_health", "cause_code": "cycle_lag"}}}
    log = [_entry("cycle-7", card="agent-blocked-by-problem")]
    out = ct.claude_work(log, tracker, {"current": None}, lambda q: {"state": "NOT_FOUND"}, problems, NOW,
                         total_claude_processes=1, measure_host=True, ps_probe=_fake_ps_alive, cmd_probe=_fake_cmd)
    assert out["active"][0]["blocker"] == "cycle_lag"
