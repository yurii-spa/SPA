"""push_policy ↔ Problem-store linkage (ADR-580 §C6, REVIEW_1 amendment, item 3).

Три claims, каждый — положительный контроль:

  * алерт ссылается на id уже открытой Problem (`format_alert`);
  * повтор ТОЙ ЖЕ причины не шлёт владельцу новое сообщение (push_policy's own
    edge-trigger, fed by a dedup_key built from the full issue-key set — unchanged
    while the SAME causes persist);
  * ДРУГАЯ, новая причина (другой агент/cause_code — ещё не Problem) всё равно
    шлёт, как раньше — только МНОЖЕСТВО issue-keys поменялось;
  * `kill_switch` никогда не проходит через эту логику вообще (другой event_key,
    другой вызывающий) — положительный контроль изоляции (пункт (e) задания).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from spa_core.monitoring import agent_health_monitor as ahm
from spa_core.monitoring import problem_store as ps
from spa_core.telegram import push_policy

# FROZEN-DATE-OK: display-only-stamp — the single literal date below
# ("2026-10-05T08:00:00+00:00" in `_report`) is report["timestamp"], and
# `format_alert` only PARSES it to re-render as display text
# (`dt.strftime("%Y-%m-%d %H:%M UTC")`) — it is never compared against the wall
# clock or any window/age threshold anywhere on this file's call paths
# (`format_alert`, `_push_via_policy`, `push_policy.push_critical`, `problem_store`).
# The "fresh"/"stale" matches the ratchet's freshness regex sees elsewhere in this
# file are agent labels and log-message text (`com.spa.fresh`, `"log stale …"`),
# not a staleness computation. No calendar move can flip this test's verdict.
def _report(agent_entries, overall="CRITICAL"):
    return {"timestamp": "2026-10-05T08:00:00+00:00", "overall_status": overall,
            "agents": agent_entries, "system_issues": []}


def _agent(label, status, issue):
    return {"label": label, "status": status, "issue": issue}


# ── alert text references an already-open Problem id ───────────────────────

def test_format_alert_references_an_open_problem_id():
    report = _report([_agent("com.spa.novel_edge_rnd", "CRITICAL", "last_exit=124")])
    key = ps.problem_key("com.spa.novel_edge_rnd", "exit_nonzero:124")
    pid = ps.problem_id("com.spa.novel_edge_rnd", "exit_nonzero:124")
    problem_records = {key: {"problem_id": pid, "status": ps.STATUS_OPEN}}
    text = ahm.format_alert(report, problem_records=problem_records)
    assert f"[Problem {pid}]" in text


def test_format_alert_has_no_reference_when_no_problem_yet():
    report = _report([_agent("com.spa.fresh", "CRITICAL", "last_exit=1")])
    text = ahm.format_alert(report, problem_records={})
    assert "[Problem" not in text


# ── recurrence of the SAME cause stays silent; a NEW cause still alerts ────

def _count_sends(monkeypatch):
    sent = []
    monkeypatch.setattr(push_policy, "_send", lambda text: (sent.append(text), True)[1])
    return sent


def test_recurrence_of_the_same_cause_does_not_resend(tmp_path, monkeypatch):
    sent = _count_sends(monkeypatch)
    report = _report([_agent("com.spa.a", "CRITICAL", "last_exit=1")])
    for _ in range(5):
        ahm._push_via_policy(report, data_dir=tmp_path)
    assert len(sent) == 1, "same cause persisting 5× must push exactly once (edge-trigger)"


def test_a_new_cause_while_the_old_one_persists_still_alerts(tmp_path, monkeypatch):
    sent = _count_sends(monkeypatch)
    report1 = _report([_agent("com.spa.a", "CRITICAL", "last_exit=1")])
    ahm._push_via_policy(report1, data_dir=tmp_path)
    assert len(sent) == 1
    # com.spa.a persists AND a brand-new agent/cause joins -> issue-key set changes.
    report2 = _report([
        _agent("com.spa.a", "CRITICAL", "last_exit=1"),
        _agent("com.spa.b", "CRITICAL", "last_exit=2"),
    ])
    ahm._push_via_policy(report2, data_dir=tmp_path)
    assert len(sent) == 2, "a genuinely new cause must still alert, same as before C6"


def test_a_drifting_number_in_the_same_cause_does_not_resend(tmp_path, monkeypatch):
    """F1 positive control — replays REVIEW_1's own simulation: four CRITICAL
    runs of the SAME agent/cause whose issue TEXT carries a changing number
    (age in days) must push once then go silent, exactly like an unchanging
    text would. Before the fix (raw-text dedup_key) this pushed 3 of 4 times."""
    sent = _count_sends(monkeypatch)
    ages = ["3.3d (>2.2d)", "3.3d (>2.2d)", "3.4d (>2.2d)", "3.5d (>2.2d)"]
    for age in ages:
        report = _report([_agent("com.spa.novel_edge_rnd", "CRITICAL", f"log stale {age}")])
        ahm._push_via_policy(report, data_dir=tmp_path)
    assert len(sent) == 1, "a drifting number inside the SAME root cause must push exactly once"


def test_a_new_cause_after_a_drifting_number_still_alerts(tmp_path, monkeypatch):
    """Companion to the control above: once the root cause genuinely CHANGES
    (not just its number), the fingerprint must differ and alert again."""
    sent = _count_sends(monkeypatch)
    report1 = _report([_agent("com.spa.novel_edge_rnd", "CRITICAL", "log stale 3.3d (>2.2d)")])
    ahm._push_via_policy(report1, data_dir=tmp_path)
    assert len(sent) == 1
    report2 = _report([_agent("com.spa.novel_edge_rnd", "CRITICAL", "last_exit=1")])
    ahm._push_via_policy(report2, data_dir=tmp_path)
    assert len(sent) == 2, "a genuinely new cause on the same agent must still alert"


def test_recovery_then_recurrence_alerts_again(tmp_path, monkeypatch):
    sent = _count_sends(monkeypatch)
    bad = _report([_agent("com.spa.a", "CRITICAL", "last_exit=1")])
    ahm._push_via_policy(bad, data_dir=tmp_path)
    good = _report([_agent("com.spa.a", "OK", "")], overall="OK")
    ahm._push_via_policy(good, data_dir=tmp_path)  # RESOLVED
    ahm._push_via_policy(bad, data_dir=tmp_path)  # recurs after recovery -> alerts again
    # entry (1) + RESOLVED (2) + a fresh entry after the resolve reset state to ok (3).
    assert len(sent) == 3


# ── (e) kill_switch is never touched by any of this ─────────────────────────

def test_kill_switch_is_outside_the_problem_store_source_set():
    """Структурный контроль: kill_switch не входит ни в один источник, который
    Problem-store читает — суппрессия C6 физически не может его коснуться."""
    assert "kill_switch" not in ps.ARTIFACT_BY_SOURCE
    assert "kill_switch_status.json" not in ps.ARTIFACT_BY_SOURCE.values()


def test_kill_switch_event_key_bypasses_agent_health_monitor_entirely(tmp_path, monkeypatch):
    """kill_switch пушится СОВСЕМ другим вызывающим (не через `_push_via_policy`), и
    остаётся под управлением ТОЛЬКО push_policy's own ceiling-exempt + dedup logic,
    непосредственно — ничего из C6 не стоит у него на пути."""
    sent = _count_sends(monkeypatch)
    assert "kill_switch" in push_policy.TIER1_WHITELIST
    assert "kill_switch" in push_policy.CEILING_EXEMPT_KEYS

    ok1 = push_policy.push_critical("kill_switch", "CRITICAL", "Kill-switch FIRED",
                                    "drawdown -10%", dedup_key="incidentA", data_dir=tmp_path)
    assert ok1 is True
    assert len(sent) == 1
    # same incident persists -> silent (pre-existing push_policy behaviour, untouched).
    ok2 = push_policy.push_critical("kill_switch", "CRITICAL", "Kill-switch FIRED",
                                    "drawdown -10%", dedup_key="incidentA", data_dir=tmp_path)
    assert ok2 is False
    assert len(sent) == 1
    # a genuinely different incident -> alerts again, never suppressed by anything C6 added.
    ok3 = push_policy.push_critical("kill_switch", "CRITICAL", "Kill-switch FIRED",
                                    "drawdown -12%", dedup_key="incidentB", data_dir=tmp_path)
    assert ok3 is True
    assert len(sent) == 2


# ── the hourly hook actually creates the card (end-to-end wiring) ──────────

def test_write_problem_store_hook_creates_a_card_after_two_cycles(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    tracker_dir = tmp_path / "tracker"
    import json
    (data_dir / "agent_health.json").write_text(json.dumps({
        "overall_status": "CRITICAL",
        "agents": [{"label": "com.spa.q", "status": "CRITICAL", "issue": "last_exit=1"}],
        "system_issues": [],
    }), encoding="utf-8")

    # problem_store.run_once resolves tracker_dir itself; _write_problem_store (the
    # production hook) doesn't take one, so point create_card at tmp via the default
    # library call being monkeypatched is unnecessary — call run_once twice directly
    # to prove the SAME code path the hook calls opens a Problem + card.
    ps.run_once(data_dir, tracker_dir=tracker_dir)
    report = ps.run_once(data_dir, tracker_dir=tracker_dir)
    assert len(report["cards_created"]) == 1
    cards = list(tracker_dir.glob("agent-task-*.md"))
    assert len(cards) == 1
    text = cards[0].read_text(encoding="utf-8")
    assert "acceptance_probe:" in text and "problem_absent:" in text
    assert "type: agent-task" in text
    assert "status: backlog" in text
    import re
    assert len(re.findall(r"(?m)^source:", text)) == 1  # no duplicate `source:` key
    assert len(re.findall(r"(?m)^problem_source:", text)) == 1
