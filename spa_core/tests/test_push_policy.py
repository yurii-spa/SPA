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


def test_current_record_exposes_incident_details(tmp_path, sent):
    # own-28: self_heal reads the pending incident's fingerprint through this
    # accessor to NAME what was down in its recovered push.
    assert push_policy.current_record("core_agent_down", data_dir=str(tmp_path)) == {}
    push_policy.push_critical(
        "core_agent_down", "CRITICAL", "down", "b",
        data_dir=str(tmp_path), dedup_key="uptime:com.spa.daily_cycle",
    )
    rec = push_policy.current_record("core_agent_down", data_dir=str(tmp_path))
    assert rec.get("state") == "bad"
    assert rec.get("fingerprint") == "uptime:com.spa.daily_cycle"
    # Read-only: it must be a COPY — mutating it must not leak into the state.
    rec["state"] = "ok"
    assert push_policy.current_state("core_agent_down", data_dir=str(tmp_path)) == "bad"


def test_core_agent_down_resolve_emits_checkmark(tmp_path, sent):
    # own-28 end-to-end at the policy layer: a pending core_agent_down entry,
    # then resolve → exactly one «✅ …» push and the class returns to ok.
    push_policy.push_critical(
        "core_agent_down", "CRITICAL", "SPA Core Agent DOWN", "x",
        data_dir=str(tmp_path), dedup_key="uptime:com.spa.daily_cycle",
    )
    assert len(sent) == 1
    ok = push_policy.resolve(
        "core_agent_down", "агенты восстановлены", "все живы",
        data_dir=str(tmp_path),
    )
    assert ok is True
    assert len(sent) == 2 and sent[1].startswith("✅")
    assert push_policy.current_state("core_agent_down", data_dir=str(tmp_path)) == "ok"


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
    # Носитель заменён `kill_switch` → `cycle_gap` 2026-08-20 (ADR-089 §2,
    # решение владельца вар. 1): стоп-кран выведен из-под дневного потолка
    # (`push_policy.CEILING_EXEMPT_KEYS`), поэтому ключом-примером для ПОТОЛКА
    # он больше служить не может. Проверка не ослаблена ни на одно утверждение —
    # ровно те же три assert'а о том же свойстве, сменился только рутинный
    # ключ-носитель. Новое поведение стоп-крана закрыто отдельным файлом
    # `test_killswitch_alert_survives_a_noisy_day.py` (11 тестов, 9 краснеют
    # на неисправленном origin), включая ОБРАТНЫЙ контроль «рутинная тревога
    # сверх потолка по-прежнему демотируется». Инв. #16: изменение намеренное,
    # обосновано здесь и записано в `docs/journal/2026-W34.md`.
    ceiling = 3
    keys = ["cycle_gap", "cycle_failed", "system_critical",
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
    # Copy is now Russian (owner task «алерты простым языком», 2026-07-20/27):
    # the coalesced notice reads «Ещё критические события…». The assertion still
    # checks the SAME property — exactly one overflow notice — only the expected
    # user-facing wording follows the intentional copy change (journal 2026-W31).
    coalesced = [t for t in sent if "Ещё критические события" in t]
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
    # Same property (the last send IS the coalesced ceiling notice); only the
    # expected wording follows the intentional RU copy change (journal 2026-W31).
    assert "лимит уведомлений" in sent[-1].lower()
    queued = push_policy.drain_digest_queue(data_dir=str(tmp_path), clear=False)
    assert any(i["reason"] == "ceiling_exceeded" for i in queued)


def test_oneshot_lead_never_records_persistent_bad_state(tmp_path, sent):
    # A one-shot push must NOT leave a persistent "bad" state (that would silence the next lead).
    push_policy.push_critical("pilot_request", "INFO", "lead", "b", data_dir=str(tmp_path))
    assert push_policy.current_state("pilot_request", data_dir=str(tmp_path)) == "ok"


# ── per-incident fingerprint (dedup_key) — the 2026-08-05 false-suppression fix
# Prod measurement: core_agent_down stuck "bad" (no sender resolves it) ⇒ every
# LATER, DIFFERENT incident sharing the class was refused (watchdog booked
# alerts_undelivered [self_heal, threat_reactor], refused_by_push_policy).
# POSITIVE CONTROLS: each test reproduces the false cut and REDS on unfixed code.
def test_new_incident_fingerprint_pushes_through_stuck_bad_class(tmp_path, sent):
    # Incident A (agent X down) → entry push, class goes bad.
    assert push_policy.push_critical(
        "core_agent_down", "CRITICAL", "down", "agent X",
        data_dir=str(tmp_path), dedup_key="com.spa.x",
    ) is True
    assert len(sent) == 1

    # Incident A persists (same fingerprint) → SILENT: real dedup NOT weakened.
    assert push_policy.push_critical(
        "core_agent_down", "CRITICAL", "down", "agent X",
        data_dir=str(tmp_path), dedup_key="com.spa.x",
    ) is False
    assert len(sent) == 1

    # Incident B — a DIFFERENT agent down while the class is still "bad".
    # Unfixed code silences it as "still bad" (the measured false cut);
    # fixed code recognises a new fingerprint = a new incident and pushes.
    assert push_policy.push_critical(
        "core_agent_down", "CRITICAL", "down", "agent Y",
        data_dir=str(tmp_path), dedup_key="com.spa.y",
    ) is True
    assert len(sent) == 2

    # Incident B persisting → silent again (dedup intact for the new incident).
    assert push_policy.push_critical(
        "core_agent_down", "CRITICAL", "down", "agent Y",
        data_dir=str(tmp_path), dedup_key="com.spa.y",
    ) is False
    assert len(sent) == 2


def test_no_fingerprint_keeps_legacy_class_level_dedup(tmp_path, sent):
    # Callers that pass no dedup_key keep the old class-level edge-trigger
    # bit-for-bit (None == None): entry once, then silence while bad.
    assert push_policy.push_critical(
        "system_critical", "CRITICAL", "t", "b", data_dir=str(tmp_path)
    ) is True
    assert push_policy.push_critical(
        "system_critical", "CRITICAL", "t", "b", data_dir=str(tmp_path)
    ) is False
    assert len(sent) == 1


def test_undelivered_entry_is_retried_until_delivered_once(tmp_path, monkeypatch):
    # Prod measurement: kill_switch stuck "bad" with entry_pushed=false since
    # 2026-07-04 — the entry send FAILED, the bad state was still recorded, and
    # the alert was permanently swallowed (never delivered, never retried).
    captured: list[str] = []
    transport_up = {"up": False}

    def flaky_send(text: str) -> bool:
        if transport_up["up"]:
            captured.append(text)
            return True
        return False

    monkeypatch.setattr(push_policy, "_send", flaky_send)

    # Entry attempt with the transport DOWN → not sent, state recorded bad.
    assert push_policy.push_critical(
        "kill_switch", "CRITICAL", "Kill", "fired", data_dir=str(tmp_path)
    ) is False
    assert captured == []
    assert push_policy.current_state("kill_switch", data_dir=str(tmp_path)) == "bad"

    # Transport recovers. Unfixed code: "still bad → silent" — the kill-switch
    # alert is eaten forever. Fixed code: entry never delivered → retry ONCE.
    transport_up["up"] = True
    assert push_policy.push_critical(
        "kill_switch", "CRITICAL", "Kill", "fired", data_dir=str(tmp_path)
    ) is True
    assert len(captured) == 1

    # Delivered → subsequent persistence is silent (dedup NOT weakened).
    assert push_policy.push_critical(
        "kill_switch", "CRITICAL", "Kill", "fired", data_dir=str(tmp_path)
    ) is False
    assert len(captured) == 1


def test_ceiling_demoted_entry_is_delivered_when_ceiling_frees(tmp_path, sent):
    # An entry demoted by the daily ceiling (entry_pushed=False) must be
    # delivered when capacity is available again (next UTC day), not lost.
    #
    # Носитель заменён `kill_switch` → `system_critical` 2026-08-20 (ADR-089 §2):
    # стоп-кран потолком больше не демотируется в принципе, то есть предусловие
    # «entry_pushed=False из-за потолка» на нём воспроизвести НЕЛЬЗЯ. Свойство,
    # которое мерит тест (недоставленная запись досылается, а не теряется
    # навсегда), не изменилось и проверяется тем же кодом. Для стоп-крана та же
    # досылка проверена отдельно — `test_a_refused_transport_is_retried_next_time`
    # в `test_killswitch_alert_survives_a_noisy_day.py`, только предусловием там
    # служит отказ ТРАНСПОРТА, а не потолок. Инв. #16: намеренно, обосновано,
    # записано в `docs/journal/2026-W34.md`.
    day1, day2 = _dt(day=3), _dt(day=4)
    # Exhaust a ceiling of 1 with another key.
    assert push_policy.push_critical(
        "cycle_failed", "CRITICAL", "c", "b",
        data_dir=str(tmp_path), daily_ceiling=1, now=day1,
    ) is True
    # system_critical enters bad over the ceiling → coalesced, entry NOT delivered.
    assert push_policy.push_critical(
        "system_critical", "CRITICAL", "Kill", "fired",
        data_dir=str(tmp_path), daily_ceiling=1, now=day1,
    ) is False
    sent_after_day1 = len(sent)
    # Next day, condition still bad: unfixed code stays silent forever; fixed
    # code delivers the never-delivered entry exactly once.
    assert push_policy.push_critical(
        "system_critical", "CRITICAL", "Kill", "fired",
        data_dir=str(tmp_path), daily_ceiling=1, now=day2,
    ) is True
    assert len(sent) == sent_after_day1 + 1
    # And once delivered — silent again.
    assert push_policy.push_critical(
        "system_critical", "CRITICAL", "Kill", "fired",
        data_dir=str(tmp_path), daily_ceiling=1, now=day2,
    ) is False
