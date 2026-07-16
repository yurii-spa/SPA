"""Tests for spa_core/telegram/push_policy.py — the single Tier-1 push authority.

Covers the gate behaviours that kill the flood:
  * whitelist (off-list → digest, never push)
  * edge-trigger (push on entry, SILENT while persisting, one RESOLVED on exit)
  * held-protocol scoping (peg/red-flag off-held → digest)
  * daily ceiling (caps pushes, coalesces the overflow once)
  * digest queue (demoted events accumulate, drainable)

Transport is fully mocked — NOTHING is sent to Telegram (we patch
``push_policy._send``). State is written to a tmp data dir.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from spa_core.telegram import push_policy


@pytest.fixture
def sent(monkeypatch):
    """Capture every (text) push_policy would transmit; mock the transport."""
    captured: list[str] = []

    def fake_send(text: str) -> bool:
        captured.append(text)
        return True

    monkeypatch.setattr(push_policy, "_send", fake_send)
    return captured


def _dt(h=12, m=0, day=1):
    return datetime(2026, 6, day, h, m, tzinfo=timezone.utc)


# ── whitelist ────────────────────────────────────────────────────────────────
def test_unwhitelisted_event_is_demoted_not_pushed(tmp_path, sent):
    ok = push_policy.push_critical(
        "totally_made_up", "CRITICAL", "x", "y", data_dir=str(tmp_path)
    )
    assert ok is False
    assert sent == []  # nothing pushed
    queued = push_policy.drain_digest_queue(data_dir=str(tmp_path), clear=False)
    assert any(i["event_key"] == "totally_made_up" for i in queued)
    assert queued[-1]["reason"] == "not_whitelisted"


# ── edge-trigger ─────────────────────────────────────────────────────────────
def test_edge_trigger_pushes_on_entry_silent_while_persisting(tmp_path, sent):
    # 1st CRITICAL → push (entry transition)
    assert push_policy.push_critical(
        "kill_switch", "CRITICAL", "Kill", "fired", data_dir=str(tmp_path)
    ) is True
    assert len(sent) == 1

    # 2nd, 3rd while still bad → SILENT (the re-fire fix)
    assert push_policy.push_critical(
        "kill_switch", "CRITICAL", "Kill", "fired", data_dir=str(tmp_path)
    ) is False
    assert push_policy.push_critical(
        "kill_switch", "CRITICAL", "Kill", "fired", data_dir=str(tmp_path)
    ) is False
    assert len(sent) == 1  # still only the entry push

    assert push_policy.current_state("kill_switch", data_dir=str(tmp_path)) == "bad"


def test_resolve_pushes_once_on_exit_transition(tmp_path, sent):
    push_policy.push_critical(
        "cycle_failed", "CRITICAL", "Cycle", "down", data_dir=str(tmp_path)
    )
    assert len(sent) == 1
    # bad → ok: one RESOLVED
    assert push_policy.resolve(
        "cycle_failed", "Recovered", data_dir=str(tmp_path)
    ) is True
    assert len(sent) == 2
    assert "✅" in sent[1] or "RESOLVED" in sent[1] or "Recovered" in sent[1]
    assert push_policy.current_state("cycle_failed", data_dir=str(tmp_path)) == "ok"

    # A second resolve with no intervening bad state → SILENT no-op
    assert push_policy.resolve(
        "cycle_failed", "Recovered", data_dir=str(tmp_path)
    ) is False
    assert len(sent) == 2


def test_resolve_without_prior_bad_is_silent(tmp_path, sent):
    assert push_policy.resolve(
        "system_critical", "ok", data_dir=str(tmp_path)
    ) is False
    assert sent == []


def test_reentry_after_resolve_pushes_again(tmp_path, sent):
    push_policy.push_critical("kill_switch", "CRITICAL", "k", "f", data_dir=str(tmp_path))
    push_policy.resolve("kill_switch", "ok", data_dir=str(tmp_path))
    assert len(sent) == 2
    # New bad transition → push again (it is a fresh edge)
    assert push_policy.push_critical(
        "kill_switch", "CRITICAL", "k", "f again", data_dir=str(tmp_path)
    ) is True
    assert len(sent) == 3


# ── held-protocol scoping ────────────────────────────────────────────────────
def test_peg_break_not_held_is_demoted(tmp_path, sent):
    ok = push_policy.push_critical(
        "peg_break", "CRITICAL", "Peg", "USDC", held_protocol=False,
        data_dir=str(tmp_path),
    )
    assert ok is False
    assert sent == []
    queued = push_policy.drain_digest_queue(data_dir=str(tmp_path), clear=False)
    assert any(i["reason"] == "not_held_protocol" for i in queued)


def test_peg_break_held_is_pushed(tmp_path, sent):
    ok = push_policy.push_critical(
        "peg_break", "CRITICAL", "Peg", "USDC", held_protocol=True,
        data_dir=str(tmp_path),
    )
    assert ok is True
    assert len(sent) == 1


def test_advisory_peg_flap_does_not_prime_edge_state(tmp_path, sent):
    # Off-held flap is demoted and must NOT mark the edge bad (else a later
    # genuine held break would be wrongly suppressed).
    push_policy.push_critical(
        "peg_break", "CRITICAL", "Peg", "x", held_protocol=False,
        data_dir=str(tmp_path),
    )
    assert push_policy.current_state("peg_break", data_dir=str(tmp_path)) in (None, "ok")
    # Now a held break must still push.
    assert push_policy.push_critical(
        "peg_break", "CRITICAL", "Peg", "x", held_protocol=True,
        data_dir=str(tmp_path),
    ) is True
    assert len(sent) == 1


# ── daily ceiling ────────────────────────────────────────────────────────────
def test_daily_ceiling_caps_pushes_and_coalesces_once(tmp_path, sent):
    ceiling = 3
    keys = ["kill_switch", "cycle_failed", "system_critical",
            "agent_health_critical", "core_agent_down", "rules_critical"]
    pushed = 0
    for k in keys:
        if push_policy.push_critical(
            k, "CRITICAL", k, "b", data_dir=str(tmp_path), daily_ceiling=ceiling
        ):
            pushed += 1
    # Exactly `ceiling` genuine entry pushes…
    assert pushed == ceiling
    # …plus EXACTLY ONE coalesced "more events" notice.
    coalesced = [t for t in sent if "more critical events" in t]
    assert len(coalesced) == 1
    # Total transmissions = ceiling entries + 1 coalesced.
    assert len(sent) == ceiling + 1


def test_ceiling_resets_on_new_utc_day(tmp_path, sent):
    # Fill the ceiling on day 1.
    for k in ["kill_switch", "cycle_failed"]:
        push_policy.push_critical(
            k, "CRITICAL", k, "b", data_dir=str(tmp_path),
            daily_ceiling=2, now=_dt(day=1),
        )
    assert len(sent) == 2
    # New day → a fresh whitelisted event pushes again.
    assert push_policy.push_critical(
        "system_critical", "CRITICAL", "s", "b", data_dir=str(tmp_path),
        daily_ceiling=2, now=_dt(day=2),
    ) is True
    assert len(sent) == 3


# ── state survival / atomicity ───────────────────────────────────────────────
def test_state_persists_across_calls(tmp_path, sent):
    push_policy.push_critical("kill_switch", "CRITICAL", "k", "f", data_dir=str(tmp_path))
    state_file = tmp_path / "telegram" / "push_state.json"
    assert state_file.exists()
    # A fresh process (new call) reads the persisted edge state → stays silent.
    assert push_policy.push_critical(
        "kill_switch", "CRITICAL", "k", "f", data_dir=str(tmp_path)
    ) is False


def test_never_raises_on_bad_state_file(tmp_path, sent):
    sdir = tmp_path / "telegram"
    sdir.mkdir(parents=True)
    (sdir / "push_state.json").write_text("{ this is not json")
    # Must not raise; corrupt state → treated as empty → entry pushes.
    assert push_policy.push_critical(
        "kill_switch", "CRITICAL", "k", "f", data_dir=str(tmp_path)
    ) is True


def test_send_false_flag_runs_gate_without_transport(tmp_path, sent):
    # send=False still applies the edge-trigger, but never touches transport.
    assert push_policy.push_critical(
        "kill_switch", "CRITICAL", "k", "f", data_dir=str(tmp_path), send=False
    ) is True
    assert sent == []  # transport untouched
    # State recorded → next call silent.
    assert push_policy.push_critical(
        "kill_switch", "CRITICAL", "k", "f", data_dir=str(tmp_path), send=False
    ) is False


# ── one-shot keys (leads) — bypass edge-trigger, keep the ceiling ─────────────
def test_oneshot_lead_pushes_every_occurrence(tmp_path, sent):
    # pilot_request is a ONESHOT key: each lead is a distinct real event, so unlike the
    # edge-trigger keys it must push on EVERY occurrence (not go silent on the 2nd).
    assert "pilot_request" in push_policy.TIER1_WHITELIST
    assert "pilot_request" in push_policy.ONESHOT_KEYS
    for i in range(3):
        assert push_policy.push_critical(
            "pilot_request", "INFO", f"lead {i}", "b", data_dir=str(tmp_path)
        ) is True
    assert len(sent) == 3  # all three pinged (edge-trigger would have sent only 1)


def test_oneshot_lead_respects_daily_ceiling(tmp_path, sent):
    # Under a ceiling of 2, the 1st+2nd leads push, the 3rd coalesces once (single notice),
    # the 4th is demoted to the digest — the flood guard still applies to one-shot keys.
    for i in range(4):
        push_policy.push_critical(
            "pilot_request", "INFO", f"lead {i}", "b",
            data_dir=str(tmp_path), daily_ceiling=2, now=_dt(day=2),
        )
    # 2 real pushes + 1 coalesced notice = 3 sends; 4th demoted (not sent).
    assert len(sent) == 3
    assert "ceiling" in sent[-1].lower()
    queued = push_policy.drain_digest_queue(data_dir=str(tmp_path), clear=False)
    assert any(i["reason"] == "ceiling_exceeded" for i in queued)


def test_oneshot_lead_never_records_persistent_bad_state(tmp_path, sent):
    # A one-shot push must NOT leave a persistent "bad" state (that would silence the next lead).
    push_policy.push_critical("pilot_request", "INFO", "lead", "b", data_dir=str(tmp_path))
    assert push_policy.current_state("pilot_request", data_dir=str(tmp_path)) == "ok"
