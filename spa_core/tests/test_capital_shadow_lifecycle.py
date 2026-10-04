# FROZEN-DATE-OK: injected-clock — every freshness judgement gets now=NOW (fixed 2026-10-04T12:00Z) and fixture stamps are pinned relative to that same anchor
"""Lifecycle tests for RM-LIVE-01 capital_shadow (ADR-556).

Fakes stand in for ``simulate``/``rpc``/``tokens`` (interface only — see each module's docstring);
nothing here ever touches a real network. Every test uses its own tmp ``data_dir``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.capital_shadow import contract, incidents, intent as intent_mod, ledger, machine, read, readiness, \
    reconcile, run as run_mod, runbook, verify
from spa_core.investment_cio import contract as cio_contract
from spa_core.utils.atomic import atomic_save

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)


# ── fixtures ────────────────────────────────────────────────────────────────────────────────────

def _seed_common(data_dir: Path) -> None:
    atomic_save({"generated_at": "2026-10-04T11:00:00Z", "triggered": False, "state": "CLEAR"},
               str(data_dir / "kill_switch_status.json"))
    atomic_save({"policy_compliant": True, "policy_version": "v1.0", "generated_at": "2026-10-04T11:00:00Z"},
               str(data_dir / "current_positions.json"))
    atomic_save([{"trade_id": "T001", "ts": "2026-10-01T00:00:00Z", "from_allocation": {"aave_v3": 0.0},
                 "to_allocation": {"aave_v3": 1000.0}}], str(data_dir / "trades.json"))
    atomic_save({"scores": [{"slug": "aave-v3", "grade": "B"}]}, str(data_dir / "risk_scores.json"))
    atomic_save({"ready": False}, str(data_dir / "golive_status.json"))
    atomic_save({"active": False}, str(data_dir / "live_trading_gate.json"))


def _pin() -> dict:
    # review #12: pin "measured" is contract.MEASURED ("MEASURED"), the SAME string rpc.py's real
    # pin_block() uses — not an invented "PASS" that happened not to matter until the pin-measured
    # gate was added this round (build_scenario_intents/build_current_intents now refuse to build
    # an ACTION intent unless pin.get("state") == contract.MEASURED exactly).
    return {"state": contract.MEASURED, "number": 100, "hash": "0x" + "cd" * 32, "operators": ["Allnodes", "dRPC"]}


def _sim_pass_module(result_patch: dict | None = None):
    class _Mod:
        @staticmethod
        def simulate_intent(an_intent, *, client=None, now=None):
            # review N2: the REAL simulator encodes an APPROVE amount in BASE units (what actually
            # goes on-chain) — this fake must do the same, via the SAME scaling authority
            # (intent.to_base_units_for_intent / tokens.to_base_units), or machine.policy_violation's
            # now-fixed base-units comparison would RISK_BLOCK a perfectly correct approve.
            amount_value = an_intent.get("notional")
            if an_intent.get("action_type") == contract.ACTION_APPROVE:
                base = intent_mod.to_base_units_for_intent(an_intent)
                if base is not None:
                    amount_value = base
            rec = {"schema": contract.SCHEMA_SIMULATION, "intent_id": an_intent["intent_id"],
                  "label": contract.SIM_LABEL, "not_proven": list(contract.NOT_PROVEN),
                  "trust_model": contract.TRUST_MODEL, "chain_id": an_intent.get("network_or_venue"),
                  "block": an_intent.get("pinned_block"), "sender": "0x" + "11" * 20,
                  "checks": [{"check": "code_nonempty", "state": "PASS", "detail": ""}],
                  "call": {"signature": "supply(address,uint256)", "selector": "0xabcdef12",
                           "args_readable": [{"name": "amount", "type": "uint256",
                                              "value": amount_value}]},
                  "gas_estimate": 120_000, "result": contract.SIM_PASS, "revert_reason": None,
                  "post_state": {"delta": an_intent.get("notional"), "shares": an_intent.get("notional")},
                  "security_events": [], "venue": an_intent.get("instrument"),
                  "instrument": an_intent.get("instrument"), "simulated_at": "2026-10-04T12:00:00Z"}
            if result_patch:
                rec.update(result_patch)
            return rec
    return _Mod()


# ── CURRENT_STATE: never manufactures an action ─────────────────────────────────────────────────

def _allow_cio(monkeypatch, stance=cio_contract.STANCE_RECOMMEND):
    """build_current_intents consults the CIO FIRST (review #11): with no investment_cio ledger at
    all, every sleeve abstains before its own book is even read. These tests are about the BOOK's
    own HOLD/no-new-trade logic, so the CIO check is monkeypatched to a settled RECOMMEND."""
    monkeypatch.setattr(intent_mod, "read_cio_state", lambda data_dir, now: {
        "state": contract.MEASURED, "value": {"recommendation_id": "rec-1", "stance": stance}, "as_of": None,
        "digest": "d", "reason": None})


def test_current_state_no_action_on_hold(tmp_path, monkeypatch):
    _seed_common(tmp_path)
    _allow_cio(monkeypatch)
    atomic_save({"decision_shadow": {"verdict": "HOLD", "message": "gain 0.09pp < band"}},
               str(tmp_path / "allocation_rationale.json"))
    intents = intent_mod.build_current_intents(tmp_path, NOW, _pin())
    conservative = next(i for i in intents if i["sleeve_id"] == "defi_conservative")
    assert conservative["action_type"] == contract.ACTION_NO_ACTION
    assert "HOLD" in conservative["reason"]
    assert set(conservative.keys()) == set(contract.INTENT_FIELDS)


def test_current_state_no_action_when_cio_abstains(tmp_path):
    _seed_common(tmp_path)
    atomic_save({"decision_shadow": {"verdict": "RECOMMEND"}}, str(tmp_path / "allocation_rationale.json"))
    # no investment_cio ledger at all -> read.latest() -> NOT_MEASURED -> CIO abstains
    intents = intent_mod.build_current_intents(tmp_path, NOW, _pin())
    for i in intents:
        assert i["action_type"] == contract.ACTION_NO_ACTION
        assert "CIO" in i["reason"]


def test_current_state_balanced_aggressive_no_action_when_book_exits(tmp_path, monkeypatch):
    _seed_common(tmp_path)
    _allow_cio(monkeypatch)
    atomic_save({"sleeve": "B", "regime": "EXIT", "positions": [], "cycles_completed": 2}, str(
        tmp_path / "hy_paper_trading.json"))
    atomic_save({"sleeve": "C", "regime": "EXIT", "positions": [], "cycles_completed": 13}, str(
        tmp_path / "lp_paper_trading.json"))
    intents = intent_mod.build_current_intents(tmp_path, NOW, _pin())
    balanced = next(i for i in intents if i["sleeve_id"] == "defi_balanced")
    aggressive = next(i for i in intents if i["sleeve_id"] == "defi_aggressive")
    assert balanced["action_type"] == contract.ACTION_NO_ACTION
    assert "EXIT" in balanced["reason"]
    assert aggressive["action_type"] == contract.ACTION_NO_ACTION
    assert "EXIT" in aggressive["reason"]


def test_current_state_never_manufactures_action_without_rationale_file(tmp_path, monkeypatch):
    _seed_common(tmp_path)
    _allow_cio(monkeypatch)
    intents = intent_mod.build_current_intents(tmp_path, NOW, _pin())
    assert all(i["action_type"] == contract.ACTION_NO_ACTION for i in intents)
    conservative = next(i for i in intents if i["sleeve_id"] == "defi_conservative")
    assert "rationale" in conservative["reason"]


def test_current_state_no_action_when_cio_insufficient_evidence(tmp_path, monkeypatch):
    _seed_common(tmp_path)
    _allow_cio(monkeypatch, stance=cio_contract.STANCE_INSUFFICIENT)
    atomic_save({"decision_shadow": {"verdict": "RECOMMEND"}}, str(tmp_path / "allocation_rationale.json"))
    intents = intent_mod.build_current_intents(tmp_path, NOW, _pin())
    for i in intents:
        assert i["action_type"] == contract.ACTION_NO_ACTION
        assert "INSUFFICIENT_EVIDENCE" in i["reason"]


# ── scenario pipeline: VALIDATED -> SIMULATED -> SHADOW_EXECUTED, reconciliation recorded,
#    but the STATE never crosses contract.SCENARIO_MAX_STATE (review #12) ──────────────────────

def test_scenario_reaches_shadow_executed_never_past_ceiling(tmp_path):
    _seed_common(tmp_path)
    intents = intent_mod.build_scenario_intents(NOW, _pin(), "happy")
    sim_mod = _sim_pass_module()
    outcomes = []
    for an_intent in intents:
        run_mod._validate(tmp_path, an_intent, NOW)
        rep = run_mod._simulate_and_execute(tmp_path, an_intent, NOW, simulate_mod=sim_mod, client=None)
        outcomes.append((an_intent, rep))

    maple_intent, maple_rep = next((i, r) for i, r in outcomes if i["network_or_venue"] == "maple")
    assert maple_rep["outcome"] == "SIMULATION_FAILED"  # PERMISSIONED_VENUES -> NOT_SIMULATABLE

    spot_intent, spot_rep = next((i, r) for i, r in outcomes if i["action_type"] == contract.ACTION_SPOT_ORDER)
    assert spot_rep["outcome"] == "SIMULATED"  # exchange_sim path stops here — never a verdict, never shadow-executed

    on_chain_actions = [(i, r) for i, r in outcomes if i["network_or_venue"] != "maple"
                       and i["action_type"] != contract.ACTION_SPOT_ORDER]
    assert len(on_chain_actions) == 4  # APPROVE+SUPPLY aave_v3, DEPOSIT_4626 fluid_fusdc, WITHDRAW compound_v3
    # this test's fake simulator always PASSes (it does not model the real simulator's inability to
    # prove a withdrawable balance) — every on-chain action reaches SHADOW_EXECUTED here. The real
    # simulator's WITHDRAW/REDEEM limitation is exercised separately, against the REAL module.
    for an_intent, rep in on_chain_actions:
        assert rep["outcome"] == "SHADOW_EXECUTED"
        assert machine.current_state(tmp_path, an_intent["intent_id"]) == contract.S_SHADOW_EXECUTED
        # reconciliation is now a FORWARD test only (review #4) — nothing is recorded in the SAME
        # pass that shadow-executed the intent; there is no later block yet to forward-reconcile
        # against. See test_forward_reconciliation_scenario_records_row_but_never_advances below.
        rec_rows = [e for e in ledger.read_all(tmp_path) if e.get("kind") == "reconciliation"
                   and e["payload"].get("intent_id") == an_intent["intent_id"]]
        assert rec_rows == []
        # ...and the intent's own STATE never advances past the ceiling, by construction.
        with pytest.raises(machine.IllegalTransition):
            machine.advance(tmp_path, an_intent, contract.S_RECONCILED, {}, NOW)
        with pytest.raises(machine.IllegalTransition):
            machine.advance(tmp_path, an_intent, contract.S_MANUAL_PILOT_READY, {}, NOW)


def test_scenario_withdraw_cannot_reach_sim_pass_with_real_simulator(tmp_path):
    """The real on-chain simulator declares no position-token storage slot, so it can never prove
    a withdrawable balance for WITHDRAW/REDEEM — NOT_MEASURED (-> SIMULATION_FAILED here) is the
    correct, expected outcome, never a silently-assumed PASS. Uses the REAL
    spa_core.capital_shadow.simulate module with a FAKE RpcClient (no real network, deterministic:
    the fake's ``pin_block`` reports NOT_MEASURED exactly like a real quorum shortfall would)."""
    _seed_common(tmp_path)
    from spa_core.capital_shadow import simulate as real_simulate

    class _FakeClient:
        security_events: list = []

        def pin_block(self):
            return {"state": contract.NOT_MEASURED, "reason": "test fake: no live RPC quorum consulted"}

    an_intent = next(i for i in intent_mod.build_scenario_intents(NOW, _pin(), "withdraw_real")
                     if i["action_type"] == contract.ACTION_WITHDRAW)
    run_mod._validate(tmp_path, an_intent, NOW)
    rep = run_mod._simulate_and_execute(tmp_path, an_intent, NOW, simulate_mod=real_simulate, client=_FakeClient())
    assert rep["outcome"] == "SIMULATION_FAILED"
    sim = ledger.load_simulation(tmp_path, an_intent["intent_id"])
    assert sim["result"] != contract.SIM_PASS


def test_scenario_never_reaches_runbook(tmp_path):
    _seed_common(tmp_path)
    intents = intent_mod.build_scenario_intents(NOW, _pin(), "no_runbook")
    fake_report = {"readiness_state": contract.R_MANUAL_PILOT_READY, "candidate_sleeve": "defi_conservative"}
    with pytest.raises(runbook.RunbookRefused):
        runbook.generate(fake_report, intents[0], None)


# ── illegal transitions / idempotency / TOCTOU / expiry ─────────────────────────────────────────

def test_illegal_transition_refused(tmp_path):
    _seed_common(tmp_path)
    an_intent = intent_mod.build_scenario_intents(NOW, _pin(), "illegal")[0]
    machine.record_intent(tmp_path, an_intent, NOW)
    with pytest.raises(machine.IllegalTransition):
        machine.advance(tmp_path, an_intent, contract.S_SHADOW_EXECUTED, {}, NOW)  # DRAFT -> SHADOW_EXECUTED


def test_duplicate_transition_is_idempotent(tmp_path):
    _seed_common(tmp_path)
    an_intent = intent_mod.build_scenario_intents(NOW, _pin(), "dup")[0]
    machine.record_intent(tmp_path, an_intent, NOW)
    e1 = machine.advance(tmp_path, an_intent, contract.S_VALIDATED, {}, NOW)
    e2 = machine.advance(tmp_path, an_intent, contract.S_VALIDATED, {}, NOW)
    assert e1["seq"] == e2["seq"]
    assert sum(1 for e in ledger.read_all(tmp_path) if e["kind"] == "transition") == 1


def test_duplicate_intent_is_idempotent(tmp_path):
    _seed_common(tmp_path)
    an_intent = intent_mod.build_scenario_intents(NOW, _pin(), "dupintent")[0]
    _, created1 = machine.record_intent(tmp_path, an_intent, NOW)
    _, created2 = machine.record_intent(tmp_path, an_intent, NOW)
    assert created1 is True and created2 is False


def test_toctou_recheck_detects_kill_switch_flip(tmp_path):
    _seed_common(tmp_path)
    an_intent = intent_mod.build_scenario_intents(NOW, _pin(), "toctou")[0]
    atomic_save({"generated_at": "2026-10-04T12:30:00Z", "triggered": True, "state": "HARD_KILL"},
               str(tmp_path / "kill_switch_status.json"))
    rc = machine.recheck(an_intent, tmp_path, NOW)
    assert rc["verdict"] == contract.S_RISK_BLOCKED
    assert "kill_switch" in rc["mismatches"]


def test_toctou_recheck_clean_when_nothing_changed(tmp_path):
    _seed_common(tmp_path)
    an_intent = intent_mod.build_scenario_intents(NOW, _pin(), "clean")[0]
    rc = machine.recheck(an_intent, tmp_path, NOW)
    # the scenario intent's own risk_snapshot is all NOT_MEASURED by construction, and a fresh
    # read of this seeded world is ALSO measured-absent for those same fields where unseeded
    # (cio/derisk/depeg) -> no spurious mismatch on fields that were never populated either side.
    assert rc["verdict"] in (None, contract.S_RISK_BLOCKED)  # kill_switch/current_positions ARE seeded


def test_expiry_computed_from_now_not_stored_state(tmp_path):
    _seed_common(tmp_path)
    an_intent = intent_mod._base_fields(
        now=NOW, pin=_pin(), sleeve_id="defi_conservative", strategy_id="x", action_type=contract.ACTION_SUPPLY,
        network_or_venue=1, instrument="aave_v3", from_asset="USDC", to_asset="USDC", notional=100.0,
        notional_unit="USDC", source_recommendation_id=None, source_role_id=contract.SOURCE_ROLE_ID,
        source_book_decision=None, risk_snapshot={k: {"state": contract.NOT_MEASURED, "value": None, "as_of":
        None, "digest": None, "reason": "x"} for k in ("kill_switch", "derisk", "riskpolicy_verdict",
        "riskpolicy_version", "cio_recommendation_id", "cio_stance", "book_state_digest", "depeg")}, unknowns=[],
        reason="expiry test", scenario=f"{contract.SCENARIO_TEST_PREFIX}expiry", ttl_s=10)
    machine.record_intent(tmp_path, an_intent, NOW)
    assert machine.is_expired(an_intent, NOW) is False
    later = NOW + timedelta(seconds=20)
    assert machine.is_expired(an_intent, later) is True
    with pytest.raises(machine.IntentExpired):
        machine.advance(tmp_path, an_intent, contract.S_VALIDATED, {}, later)
    entry = machine.advance(tmp_path, an_intent, contract.S_EXPIRED, {}, later)
    assert entry["payload"]["to_state"] == contract.S_EXPIRED


# ── readiness: today's conservative sleeve is NOT MANUAL_PILOT_READY, by construction ──────────

def test_readiness_set_equality_gate_check():
    assert set(contract.SYSTEM_GATES) == set(readiness._GATE_BUILDERS.keys())
    assert len(contract.SYSTEM_GATES) >= 10  # a short/empty list must never pass by construction


def test_readiness_conservative_unreachable_today(tmp_path):
    _seed_common(tmp_path)  # kill_switch CLEAR, RiskPolicy PASS — still must not reach MANUAL_PILOT_READY
    reports = readiness.evaluate(tmp_path, [], NOW)
    conservative = reports["defi_conservative"]
    assert conservative["readiness_state"] != contract.R_MANUAL_PILOT_READY
    gate_names = {b["gate"] for b in conservative["blocking_conditions"]}
    # four BLOCKS_ALL_PILOTS system blockers named in ADR-556: counterparty, offhost anchor, plus
    # whatever else is unmet today (reconciliation/simulation never having run in this fixture).
    assert "counterparty_evidence" in gate_names
    assert "offhost_anchor" in gate_names
    assert conservative["system_checks"]["counterparty_evidence"]["state"] == contract.GATE_UNKNOWN
    assert conservative["system_checks"]["offhost_anchor"]["state"] == contract.GATE_FAIL
    assert conservative["readiness_display"] != contract.R_MANUAL_PILOT_READY


def test_readiness_all_six_sleeves_reported(tmp_path):
    _seed_common(tmp_path)
    reports = readiness.evaluate(tmp_path, [], NOW)
    # review N5: readiness.evaluate() now returns ONLY sleeve reports — "venue_canary" moved to its
    # OWN top-level key, built separately by read.latest() via readiness.venue_canary_section();
    # a sleeve map containing it would leak non-sleeve diagnostic evidence into the very set
    # test_mission_control_contract.py compares 1:1 against read.latest()["readiness"].
    assert set(reports.keys()) == {"defi_conservative", "defi_balanced", "defi_aggressive", "cash",
                                   "trading_research", "market_neutral_basis"}
    for sleeve_id in ("cash", "trading_research", "market_neutral_basis"):
        assert reports[sleeve_id]["readiness_state"] == contract.R_NOT_READY
    for sleeve_id, report in reports.items():
        assert set(report.keys()) == set(contract.READINESS_FIELDS)

    # the venue_canary section is still available, but ONLY via the separate public function.
    venue_canary = readiness.venue_canary_section([])
    assert venue_canary["sleeve_id"] == "scenario_canary"


def test_readiness_protocol_evidence_fails_on_default_graded_protocol(tmp_path):
    _seed_common(tmp_path)
    atomic_save([{"trade_id": "T002", "ts": "2026-10-02T00:00:00Z", "from_allocation": {},
                 "to_allocation": {"maple": 500.0, "fluid_fusdc": 300.0}}], str(tmp_path / "trades.json"))
    reports = readiness.evaluate(tmp_path, [], NOW)
    gate = reports["defi_conservative"]["system_checks"]["protocol_evidence"]
    assert gate["state"] == contract.GATE_FAIL
    assert "maple" in gate["evidence"]["default_graded"] or "fluid_fusdc" in gate["evidence"]["default_graded"]


# ── runbook: never a signing payload, refuses for non-ready sleeves ─────────────────────────────

def test_runbook_refuses_when_not_manual_pilot_ready(tmp_path):
    _seed_common(tmp_path)
    reports = readiness.evaluate(tmp_path, [], NOW)
    an_intent = intent_mod.build_current_intents(tmp_path, NOW, _pin())[0]
    with pytest.raises(runbook.RunbookRefused):
        runbook.generate(reports["defi_conservative"], an_intent, None)


def test_runbook_never_contains_raw_calldata(tmp_path):
    # HIGH review finding #2 changed runbook.generate's signature (data_dir/now) and made it build
    # every displayed argument from the PINNED REGISTRY, never from the simulation's own call — so
    # this fixture now needs a real action_type/network_or_venue to exercise that path, and a
    # synthetic-looking sender in the FAKE simulation to prove it never leaks through.
    _seed_common(tmp_path)
    fake_report = {"readiness_state": contract.R_MANUAL_PILOT_READY, "candidate_sleeve": "defi_conservative",
                  "evidence_refs": ["risk_scores.json"]}
    # review N3 added an expiry check (machine.is_expired) to runbook.generate — needs an
    # expires_at field this hand-built fixture didn't carry before.
    fake_intent = {"scenario": contract.SCENARIO_CURRENT, "intent_id": "deadbeef", "instrument": "aave_v3",
                  "action_type": contract.ACTION_SUPPLY, "network_or_venue": "aave_v3", "from_asset": "USDC",
                  "notional": 1000.0, "sleeve_id": "defi_conservative",
                  "expires_at": (NOW + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    # the simulation's own sender/onBehalfOf is a synthetic, NEVER-FUNDED placeholder (see
    # simulate.synthetic_sender) — it must never appear in a runbook.
    synthetic_sender = "0x" + "11" * 20
    fake_sim = {"call": {"signature": "supply(address,uint256,address,uint16)", "selector": "0xabcdef12",
               "args_readable": f"asset=0xdead, amount=1000, onBehalfOf={synthetic_sender}, referralCode=0"},
               "block": {"number": 100, "hash": "0x" + "ab" * 32, "operators": ["Allnodes", "dRPC"]}}
    text = runbook.generate(fake_report, fake_intent, fake_sim, data_dir=tmp_path, now=NOW)
    assert text is not None
    import re
    assert re.search(r"0x[0-9a-fA-F]{65,}", text) is None, "no hex string longer than a bare 32-byte block hash"
    assert '"data"' not in text
    assert "OWNER_DECISION_REQUIRED" in text
    assert "<= 1h" in text or "expires_at" in text
    # HIGH finding #2's exact regression: the simulation's own synthetic sender/onBehalfOf must
    # never appear next to the printed OWNER_SAFE label (previously only a bare `assert` — removed
    # under `python -O` — stood between that and an owner's hardware wallet).
    assert synthetic_sender not in text, "the simulation's own synthetic sender must never appear in a runbook"


# ── verify: ABORT without a configured owner Safe ───────────────────────────────────────────────

def test_verify_aborts_without_owner_safe(tmp_path):
    # CRITICAL review finding #1 changed verify()'s signature to (intent_id, payload_hex, *,
    # to_address, data_dir, now, client=None) — to_address is now required (the wallet-shown tx
    # target must be checked against the pinned registry, the exact field the old signature never
    # even accepted). The value here does not matter for THIS test: no owner Safe is configured at
    # all, so the result is ABORT regardless of what to_address names.
    _seed_common(tmp_path)
    an_intent = intent_mod.build_scenario_intents(NOW, _pin(), "verify")[0]
    machine.record_intent(tmp_path, an_intent, NOW)
    # review N1e added --value/--operation/--chain-id as REQUIRED wallet-field inputs; any value
    # does for THIS test (ABORT is driven by the missing owner Safe regardless).
    result = verify.verify(an_intent["intent_id"], "0x" + "00" * 4, to_address="0x" + "22" * 20, value=0,
                           operation=0, chain_id=1, data_dir=tmp_path, now=NOW)
    assert result["verdict"] == "ABORT"
    assert any("Safe" in m for m in result["mismatches"])


def test_verify_cli_exit_code(tmp_path, monkeypatch, capsys):
    _seed_common(tmp_path)
    # the "maple" fixture is permissioned — simulate.simulate_intent refuses it before any network
    # I/O, so this smoke test of the CLI's exit code / output shape never reaches for a live RPC.
    an_intent = next(i for i in intent_mod.build_scenario_intents(NOW, _pin(), "cli")
                     if i["network_or_venue"] == "maple")
    machine.record_intent(tmp_path, an_intent, NOW)
    # --to-address/--value/--operation/--chain-id are now all required (CRITICAL #1 / review N1e)
    # — any values do: "maple" has no pinned address at all, so the mismatch fires regardless.
    rc = verify.main(["--intent", an_intent["intent_id"], "--payload", "0x1234", "--to-address",
                      "0x" + "33" * 20, "--value", "0", "--operation", "0", "--chain-id", "1",
                      "--data-dir", str(tmp_path)])
    assert rc == contract.EXIT_FAIL
    out = capsys.readouterr().out
    assert "ABORT" in out


# ── read: separate verifier recomputes from the ledger, detects tampering ──────────────────────

def test_read_verifier_recomputes_readiness(tmp_path):
    _seed_common(tmp_path)
    summary = run_mod.run_cycle(tmp_path, NOW, live_rpc=False)
    assert summary["current_intents"] == 3
    result = read.latest(tmp_path, now=NOW)
    assert result["state"] == contract.MEASURED
    assert result["integrity"] == "OK"
    assert "defi_conservative" in result["readiness"]


def test_read_verifier_detects_tampering(tmp_path):
    _seed_common(tmp_path)
    run_mod.run_cycle(tmp_path, NOW, live_rpc=False)
    ledger_path = tmp_path / contract.DATA_SUBDIR / contract.LEDGER
    lines = ledger_path.read_text().splitlines()
    tampered = json.loads(lines[0])
    tampered["payload"]["sleeve_id"] = "TAMPERED"
    lines[0] = json.dumps(tampered)
    ledger_path.write_text("\n".join(lines) + "\n")
    result = read.latest(tmp_path, now=NOW)
    assert result["state"] == contract.NOT_MEASURED
    assert result["integrity"] == "BROKEN"


# ── incidents: sticky, alert dispatched, never auto-clear ──────────────────────────────────────

def test_incident_sticky_and_alert_called(tmp_path):
    calls = {"created": [], "dispatched": []}

    class _SpyDispatcher:
        def create_alert(self, level, title, message, adapter_id=None):
            calls["created"].append((title, message))
            return object()

        def dispatch(self, alert):
            calls["dispatched"].append(alert)
            return {"channels_succeeded": ["log"]}

    row = incidents.raise_incident(tmp_path, "ledger_broken", "chain broke at seq=3", now=NOW,
                                   dispatcher=_SpyDispatcher())
    assert row["status"] == "OPEN"
    assert len(calls["created"]) == 1 and len(calls["dispatched"]) == 1
    assert incidents.open_incidents(tmp_path) == [row]

    with pytest.raises(ValueError):
        incidents.clear_incident(tmp_path, row["incident_id"], "")
    assert incidents.open_incidents(tmp_path) == [row]  # still open: no auto-clear

    # MEDIUM review finding #11b / N4-ii (owner-boundary fix): "ledger_broken" is one of the kinds
    # that additionally require the OWNER's own out-of-band confirmation file (never a caller-
    # supplied token argument — clear_incident no longer takes one at all) containing the EXACT
    # nonce raise_incident minted for this incident. Dedicated coverage of the full flow (missing
    # file, wrong nonce, right nonce) lives in test_capital_shadow_owner_boundary.py; this call is
    # updated here only so the pre-existing "sticky, never auto-clears" story in this test still
    # runs end to end.
    with pytest.raises(ValueError):
        incidents.clear_incident(tmp_path, row["incident_id"], "ledger repaired, anchors verified")
    confirmations_dir = tmp_path / contract.DATA_SUBDIR / incidents.CONFIRMATIONS_SUBDIR
    confirmations_dir.mkdir(parents=True, exist_ok=True)
    atomic_save({"nonce": row["confirmation_nonce"]}, str(confirmations_dir / f"{row['incident_id']}.json"))
    cleared = incidents.clear_incident(tmp_path, row["incident_id"], "ledger repaired, anchors verified")
    assert cleared["status"] == "CLEARED"
    assert incidents.open_incidents(tmp_path) == []


def test_incident_unknown_kind_rejected(tmp_path):
    with pytest.raises(ValueError):
        incidents.raise_incident(tmp_path, "not_a_real_kind", "x", now=NOW, dispatcher=None)


# ── REAL-SHAPED REGRESSION TESTS ─────────────────────────────────────────────────────────────────
# Found by an integration run against a copy of real production data (not this module's own
# fixtures). Each fixture below is the MINIMAL real shape that reproduces the defect, copied from
# the real file, not invented.

def test_regression_network_or_venue_is_a_tokens_venues_key():
    """Defect #1: network_or_venue used to be the chain id (1); simulate.simulate_intent resolves
    the whole venue (including chain_id) by looking this field up in tokens.VENUES — a chain id
    there means every simulation refuses at venue_lookup before any network I/O, so NO simulation
    ever reaches the ledger."""
    from spa_core.capital_shadow import tokens
    intents = intent_mod.build_scenario_intents(NOW, _pin(), "venue_regression")
    on_chain = [i for i in intents if i["action_type"] != contract.ACTION_SPOT_ORDER]
    for i in on_chain:
        assert tokens.venue(i["network_or_venue"]) is not None, \
            f"{i['network_or_venue']!r} must be a tokens.VENUES key, not a chain id"
        assert i["network_or_venue"] in ("aave_v3", "compound_v3", "fluid_fusdc", "maple", "morpho_blue_base")


def test_regression_data_freshness_reads_the_cycle_not_the_last_trade(tmp_path):
    """Defect #2: a conservative book that keeps recommending HOLD can have a `trades.json` whose
    last entry is WEEKS old — that is a healthy, cycling book, not stale data. Freshness must come
    from the daily cycle's own output (current_positions.json), not the last rebalance."""
    _seed_common(tmp_path)
    # real minimal shape: current_positions.json is FRESH (this run), trades.json's last trade is
    # old (533h, as found in the real integration run) because the book has been holding.
    atomic_save({"generated_at": "2026-10-04T11:30:00+00:00", "source": "cycle_runner",
                "execution_mode": "read_only_simulation", "policy_compliant": True, "policy_version": "v1.0"},
               str(tmp_path / "current_positions.json"))
    atomic_save([{"trade_id": "T007", "ts": "2026-06-20T21:23:06.104513+00:00", "from_allocation": {},
                 "to_allocation": {"aave_v3": 1000.0}}], str(tmp_path / "trades.json"))
    gate = readiness._data_freshness_gate(tmp_path, "defi_conservative", NOW)
    assert gate["state"] == contract.GATE_PASS
    assert gate["evidence"]["source"] == "current_positions.json"
    assert gate["evidence"]["age_hours"] < 1.0


def test_regression_strategy_evidence_reads_nested_sleeves_key():
    """Defect #3: build_sleeves() returns {"schema", "generated_at", "sleeves": {sleeve_id: {...}},
    ...} — the per-sleeve projection is nested under "sleeves", never at the top level."""
    real_shaped_doc = {
        "schema": "investment-cio-sleeves/1", "generated_at": "2026-10-04T12:00:00+00:00",
        "sleeves": {"defi_conservative": {"maturity": {"state": "MEASURED", "value": "MATURE", "unit": None,
                                                        "source": "x", "as_of": None, "n": 102, "note": None}}},
    }
    gate = readiness._strategy_evidence_gate(real_shaped_doc, "defi_conservative")
    assert gate["state"] == contract.GATE_PASS
    assert contract.value_of(gate["evidence"]) == "MATURE"
    # the OLD (buggy) behaviour read sleeves_doc[sleeve_id] directly on the FULL real-shaped doc —
    # that key only ever exists at the top level in a doc with no "sleeves" wrapper at all, so on
    # the REAL doc shape it always missed, reporting every sleeve "not projected":
    missing_sleeve = readiness._strategy_evidence_gate(real_shaped_doc, "defi_balanced")
    assert missing_sleeve["state"] == contract.GATE_UNKNOWN
    assert missing_sleeve["evidence"] == "sleeve not projected by investment_cio.sleeves"


def test_regression_liquidity_evidence_reads_books_exit_share_illiquid(tmp_path):
    """Defect #4: real shape is books.<book>.exit.{share_illiquid, max_illiquid_share, policy_ok,
    share_basis} — not a top-level share_illiquid."""
    _seed_common(tmp_path)
    (tmp_path / "defi_engine").mkdir(exist_ok=True)
    atomic_save({
        "schema": "defi-engine-status/1", "generated_at": "2026-10-04T02:01:58Z",
        "books": {"conservative": {"exit": {
            "measured": True, "share_basis": "NAV (measured cash included)", "share_illiquid": 0.19704,
            "illiquid_threshold_hours": 72.0, "max_illiquid_share": 0.25, "policy_ok": True,
            "illiquid_positions": ["maple"],
        }}},
    }, str(tmp_path / "defi_engine" / "status.json"))
    gate = readiness._liquidity_evidence_gate(tmp_path, "defi_conservative")
    assert gate["state"] == contract.GATE_PASS
    assert gate["evidence"]["share_illiquid"] == 0.19704
    assert gate["evidence"]["policy_ok"] is True


def test_regression_liquidity_evidence_fails_when_policy_not_ok(tmp_path):
    _seed_common(tmp_path)
    (tmp_path / "defi_engine").mkdir(exist_ok=True)
    atomic_save({"books": {"balanced": {"exit": {
        "share_basis": "deployed notional (book state carries no cash)", "share_illiquid": 0.375137,
        "max_illiquid_share": 0.25, "policy_ok": False, "illiquid_positions": ["maple", "susde"],
    }}}}, str(tmp_path / "defi_engine" / "status.json"))
    gate = readiness._liquidity_evidence_gate(tmp_path, "defi_balanced")
    assert gate["state"] == contract.GATE_FAIL


def test_regression_observability_reads_agents_list_by_label(tmp_path):
    """Defect #5: agent_health.json has no top-level "status" — it has "agents", a list of
    {"label", "status", ...} rows."""
    _seed_common(tmp_path)
    atomic_save({
        "timestamp": "2026-10-04T12:00:00Z", "overall_status": "OK", "healthy_count": 87, "total_agents": 87,
        "agents": [
            {"label": "com.spa.daily_cycle", "status": "OK", "pid": 0, "last_exit": 0, "log_age_min": 670.8,
             "category": "daily", "loaded": True, "issue": "", "note": ""},
            {"label": "com.spa.hy_cycle", "status": "OK", "pid": 0, "last_exit": 0, "log_age_min": 32.6,
             "category": "mid_freq", "loaded": True, "issue": "", "note": ""},
            {"label": "com.spa.lp_cycle", "status": "CRITICAL", "pid": 0, "last_exit": 1, "log_age_min": 999.0,
             "category": "mid_freq", "loaded": True, "issue": "crashed", "note": ""},
        ],
    }, str(tmp_path / "agent_health.json"))
    assert readiness._observability_gate(tmp_path, "defi_conservative")["state"] == contract.GATE_PASS
    assert readiness._observability_gate(tmp_path, "defi_balanced")["state"] == contract.GATE_PASS
    assert readiness._observability_gate(tmp_path, "defi_aggressive")["state"] == contract.GATE_FAIL


def test_regression_kill_switch_reads_explicit_state_field(tmp_path):
    """Defect #6 (confirmed already-correct, pinned with a real-shaped fixture): real
    kill_switch_status.json HAS a "state" field (e.g. "CLEAR_PARTIAL") — read it directly, never
    the triggered-bool fallback, when it is present."""
    atomic_save({
        "generated_at": "2026-10-04T02:55:35.989979+00:00", "triggered": False, "state": "CLEAR_PARTIAL",
        "reason": "no trigger fired; partial: red_flags PARTIAL", "triggers": [], "allocation": {},
    }, str(tmp_path / "kill_switch_status.json"))
    cell = intent_mod.read_kill_switch_state(tmp_path)
    assert cell["value"] == "CLEAR_PARTIAL"
    assert cell["reason"] is None  # no fallback reason attached — it was read directly


def test_regression_golive_reads_go_live_state_field(tmp_path):
    """Defect #7 (confirmed already-correct, pinned with a real-shaped fixture): real
    golive_status.json has go_live_state (e.g. "gate_passed_owner_decision_pending"), not just a
    bare "ready" bool."""
    _seed_common(tmp_path)
    atomic_save({
        "ready": False, "passed": 27, "total": 29, "go_live_state": "gate_passed_owner_decision_pending",
        "timestamp": "2026-10-04T02:00:00Z",
    }, str(tmp_path / "golive_status.json"))
    preconditions = readiness._owner_preconditions(tmp_path)
    assert preconditions["golive_decision"]["state"] == contract.PRECONDITION_PENDING
    assert preconditions["golive_decision"]["decision_ref"] == "golive_status.json:go_live_state"


def test_regression_book_verdict_reason_is_named_alongside_cio(tmp_path, monkeypatch):
    """Defect #8: real allocation_rationale.json carries decision_shadow.decision (not "verdict")
    + a reasons list — and a NO_ACTION forced by the CIO must still name the book's own finding,
    not hide it."""
    _seed_common(tmp_path)
    _allow_cio(monkeypatch, stance=cio_contract.STANCE_INSUFFICIENT)
    atomic_save({
        "generated_at": "2026-10-04T08:00:03Z", "cycle_date": "2026-10-04", "book_id": "conservative",
        "decision_shadow": {
            "decision": "HOLD",
            "reasons": ["gain_below_band:0.098pp<0.500pp", "payback_too_long:351.3d",
                       "move_turnover_over_budget:45.0%>15%"],
            "apy_now_pp": 4.18922, "apy_opt_pp": 4.28756, "gain_pp": 0.09834, "required_gain_pp": 0.5,
        },
    }, str(tmp_path / "allocation_rationale.json"))
    intents = intent_mod.build_current_intents(tmp_path, NOW, _pin())
    conservative = next(i for i in intents if i["sleeve_id"] == "defi_conservative")
    assert conservative["action_type"] == contract.ACTION_NO_ACTION
    assert "INSUFFICIENT_EVIDENCE" in conservative["reason"]
    assert "HOLD" in conservative["reason"]
    assert "gain_below_band" in conservative["reason"]


# ── FORWARD RECONCILIATION (ADR-556 review #4) ───────────────────────────────────────────────────

def _shadow_execute_deposit(tmp_path, monkeypatch, *, scenario=False, shares=1000.0, old_block=100,
                            sleeve_id="defi_balanced", venue="fluid_fusdc", notional=1000.0):
    """Builds, validates, simulates (fake PASS) and shadow-executes ONE DEPOSIT_4626 intent at
    ``old_block``. Returns the intent dict.

    For a non-scenario (current-state) intent, ``machine.recheck``'s review #8 current-value
    gate ALWAYS blocks on depeg (permanently NOT_MEASURED — no real source exists) regardless of
    anything else. That gate is tested on its own elsewhere; here it is bypassed so the FORWARD
    RECONCILIATION machinery (review #4/#9), which is what these tests are actually about, can be
    exercised in isolation. Default sleeve is "defi_balanced" (not conservative): review #9 makes
    ``book_mark`` mandatory for DEPOSIT_4626, and conservative's own book (``trades.json``) carries
    no per-protocol mark at all (permanently NOT_MEASURED there, by design) — balanced's book
    (``hy_paper_trading.json``) does, and is seeded here with a matching position.
    """
    if not scenario:
        # recheck() is entirely out of scope for these tests (it has its own dedicated tests) —
        # bypass it cleanly rather than fighting its mismatch-detection with fixture bookkeeping.
        monkeypatch.setattr(machine, "recheck", lambda an_intent, data_dir, now: {"mismatches": {}, "verdict":
                           None, "fresh_risk_snapshot": {}, "current_blockers": []})
        book_relpath = {"defi_conservative": "trades.json", "defi_balanced": "hy_paper_trading.json",
                       "defi_aggressive": "lp_paper_trading.json"}[sleeve_id]
        if book_relpath != "trades.json":
            atomic_save({"sleeve": "B", "regime": "ENTER", "positions": [{"protocol": venue, "opened": "2026-10-01",
                        "notional_usd": notional}], "last_cycle_at": "2026-10-04T11:00:00Z"},
                       str(tmp_path / book_relpath))
    if scenario:
        an_intent = next(i for i in intent_mod.build_scenario_intents(NOW, _pin(), "fwd")
                         if i["action_type"] == contract.ACTION_DEPOSIT_4626)
    else:
        an_intent = intent_mod._base_fields(
            now=NOW, pin=_pin(), sleeve_id=sleeve_id, strategy_id="x", action_type=contract.ACTION_DEPOSIT_4626,
            network_or_venue=venue, instrument=venue, from_asset="USDC", to_asset=venue, notional=notional,
            notional_unit="USDC", source_recommendation_id=None, source_role_id=contract.SOURCE_ROLE_ID,
            source_book_decision="RECOMMEND", risk_snapshot={k: {"state": contract.NOT_MEASURED, "value": None,
            "as_of": None, "digest": None, "reason": "fixture"} for k in ("kill_switch", "derisk",
            "riskpolicy_verdict", "riskpolicy_version", "cio_recommendation_id", "cio_stance", "book_state_digest",
            "depeg")}, unknowns=[], reason="fixture", scenario=contract.SCENARIO_CURRENT)
    sim_mod = _sim_pass_module({"block": {"number": old_block, "hash": "0x" + "ab" * 32, "operators": ["Allnodes",
                                "dRPC"]}, "post_state": {"delta": notional, "shares": shares}})
    run_mod._validate(tmp_path, an_intent, NOW)
    rep = run_mod._simulate_and_execute(tmp_path, an_intent, NOW, simulate_mod=sim_mod, client=None)
    assert rep["outcome"] == "SHADOW_EXECUTED"
    return an_intent


class _FakeForwardClient:
    def __init__(self, block):
        self._block = block
        self.security_events = []

    def pin_block(self):
        return {"state": contract.MEASURED, "number": self._block, "hash": "0x" + "cd" * 32,
               "operators": ["Allnodes", "dRPC"]}


class _FakeForwardSimulate:
    def __init__(self, preview_shares, *, code_present=True, asset_ok=True, chain_ok=True, code_ok=True,
                decimals_ok=True):
        self._preview_shares = preview_shares
        self._code_present = code_present
        self._asset_ok = asset_ok
        self._chain_ok = chain_ok
        self._code_ok = code_ok
        self._decimals_ok = decimals_ok

    def preview_deposit_at(self, venue, amount, *, client):
        pinned = client.pin_block()
        return {"state": contract.MEASURED, "preview_shares": self._preview_shares, "block": pinned["number"],
               "code_present": self._code_present, "asset_ok": self._asset_ok, "reason": None}

    def reverify_venue_at_current_block(self, venue, asset_symbol, *, client):
        pinned = client.pin_block()
        return {"state": contract.MEASURED, "block": pinned["number"], "chain_ok": self._chain_ok,
               "code_ok": self._code_ok, "decimals_ok": self._decimals_ok, "reason": None}


def test_forward_reconciliation_skips_when_no_later_block_exists(tmp_path, monkeypatch):
    an_intent = _shadow_execute_deposit(tmp_path, monkeypatch, old_block=100)
    same_block_client = _FakeForwardClient(100)  # NOT later than the simulation's own block 100
    reports = run_mod._run_forward_reconciliation(tmp_path, NOW, rpc_mod=None,
                                                  simulate_mod=_FakeForwardSimulate(1000.0), client=same_block_client)
    assert reports == []
    assert [e for e in ledger.read_all(tmp_path) if e.get("kind") == "reconciliation"] == []


def test_forward_reconciliation_deposit_matched_advances_to_reconciled(tmp_path, monkeypatch):
    an_intent = _shadow_execute_deposit(tmp_path, monkeypatch, old_block=100, shares=1000.0)
    later_client = _FakeForwardClient(150)
    reports = run_mod._run_forward_reconciliation(tmp_path, NOW, rpc_mod=None,
                                                  simulate_mod=_FakeForwardSimulate(1000.0), client=later_client)
    assert len(reports) == 1
    assert reports[0]["outcome"] == contract.REC_MATCHED
    assert reports[0]["old_block"] == 100 and reports[0]["new_block"] == 150
    rec_row = ledger.find_by_key(tmp_path, "reconciliation", ("reconciliation", an_intent["intent_id"], 150))
    assert rec_row is not None
    assert rec_row["payload"]["fields"]["shares_vs_preview"]["outcome"] == contract.REC_MATCHED
    assert rec_row["payload"]["fields"]["intended_delta"]["note"].startswith("consistency check only")
    assert machine.current_state(tmp_path, an_intent["intent_id"]) == contract.S_RECONCILED

    # idempotent: a second forward pass does nothing more — it is already reconciled.
    again = run_mod._run_forward_reconciliation(tmp_path, NOW, rpc_mod=None,
                                                simulate_mod=_FakeForwardSimulate(1000.0), client=_FakeForwardClient(200))
    assert again == []


def test_forward_reconciliation_deposit_mismatch_advances_to_reconciliation_failed(tmp_path, monkeypatch):
    an_intent = _shadow_execute_deposit(tmp_path, monkeypatch, old_block=100, shares=1000.0)
    later_client = _FakeForwardClient(150)
    # 50% off — far outside the 0.5% forward tolerance (the vault's share price moving a LITTLE is
    # expected and allowed; this is not that).
    reports = run_mod._run_forward_reconciliation(tmp_path, NOW, rpc_mod=None,
                                                  simulate_mod=_FakeForwardSimulate(500.0), client=later_client)
    assert reports[0]["outcome"] == contract.REC_MISMATCH
    assert machine.current_state(tmp_path, an_intent["intent_id"]) == contract.S_RECONCILIATION_FAILED


def test_forward_reconciliation_deposit_tolerates_half_percent_share_price_move(tmp_path, monkeypatch):
    an_intent = _shadow_execute_deposit(tmp_path, monkeypatch, old_block=100, shares=1000.0)
    later_client = _FakeForwardClient(150)
    reports = run_mod._run_forward_reconciliation(tmp_path, NOW, rpc_mod=None,
                                                  simulate_mod=_FakeForwardSimulate(1004.0),  # 0.4% move
                                                  client=later_client)
    assert reports[0]["outcome"] == contract.REC_MATCHED


def test_forward_reconciliation_supply_stays_not_measured_and_does_not_advance(tmp_path, monkeypatch):
    monkeypatch.setattr(machine, "recheck", lambda an_intent, data_dir, now: {"mismatches": {}, "verdict": None,
                       "fresh_risk_snapshot": {}, "current_blockers": []})
    an_intent = intent_mod._base_fields(
        now=NOW, pin=_pin(), sleeve_id="defi_conservative", strategy_id="x", action_type=contract.ACTION_SUPPLY,
        network_or_venue="aave_v3", instrument="aave_v3", from_asset="USDC", to_asset="USDC", notional=1000.0,
        notional_unit="USDC", source_recommendation_id=None, source_role_id=contract.SOURCE_ROLE_ID,
        source_book_decision="RECOMMEND", risk_snapshot={k: {"state": contract.NOT_MEASURED, "value": None,
        "as_of": None, "digest": None, "reason": "fixture"} for k in ("kill_switch", "derisk", "riskpolicy_verdict",
        "riskpolicy_version", "cio_recommendation_id", "cio_stance", "book_state_digest", "depeg")}, unknowns=[],
        reason="fixture", scenario=contract.SCENARIO_CURRENT)
    sim_mod = _sim_pass_module({"block": {"number": 100, "hash": "0x" + "ab" * 32, "operators": ["Allnodes",
                                "dRPC"]}, "post_state": {"delta": 1000.0}})
    run_mod._validate(tmp_path, an_intent, NOW)
    run_mod._simulate_and_execute(tmp_path, an_intent, NOW, simulate_mod=sim_mod, client=None)

    reports = run_mod._run_forward_reconciliation(tmp_path, NOW, rpc_mod=None,
                                                  simulate_mod=_FakeForwardSimulate(0.0), client=_FakeForwardClient(150))
    assert len(reports) == 1
    assert reports[0]["outcome"] == contract.REC_NOT_MEASURED
    rec_row = ledger.find_by_key(tmp_path, "reconciliation", ("reconciliation", an_intent["intent_id"], 150))
    assert rec_row["payload"]["fields"]["position_after"]["outcome"] == contract.REC_NOT_MEASURED
    # NOT_MEASURED never advances the machine — it stays exactly where an honest "cannot know" leaves it.
    assert machine.current_state(tmp_path, an_intent["intent_id"]) == contract.S_SHADOW_EXECUTED

    # review #9: NOT_MEASURED is NOT final — it is retried on a later run (never stranded), at a
    # genuinely later block, up to the intent's own expiry.
    again = run_mod._run_forward_reconciliation(tmp_path, NOW, rpc_mod=None,
                                                simulate_mod=_FakeForwardSimulate(0.0), client=_FakeForwardClient(300))
    assert len(again) == 1
    assert again[0]["outcome"] == contract.REC_NOT_MEASURED
    assert again[0]["new_block"] == 300
    rec_row_2 = ledger.find_by_key(tmp_path, "reconciliation", ("reconciliation", an_intent["intent_id"], 300))
    assert rec_row_2 is not None
    assert machine.current_state(tmp_path, an_intent["intent_id"]) == contract.S_SHADOW_EXECUTED

    # ...but never retried past the intent's own expiry.
    far_future = NOW + timedelta(seconds=contract.INTENT_TTL_SHADOW_S + 3600)
    past_expiry = run_mod._run_forward_reconciliation(tmp_path, far_future, rpc_mod=None,
                                                      simulate_mod=_FakeForwardSimulate(0.0),
                                                      client=_FakeForwardClient(400))
    assert past_expiry == []


def test_forward_reconciliation_scenario_records_row_but_never_advances(tmp_path, monkeypatch):
    an_intent = _shadow_execute_deposit(tmp_path, monkeypatch, scenario=True, old_block=100, shares=1000.0)
    later_client = _FakeForwardClient(150)
    reports = run_mod._run_forward_reconciliation(tmp_path, NOW, rpc_mod=None,
                                                  simulate_mod=_FakeForwardSimulate(1000.0), client=later_client)
    assert len(reports) == 1
    rec_row = ledger.find_by_key(tmp_path, "reconciliation", ("reconciliation", an_intent["intent_id"], 150))
    assert rec_row is not None  # the row IS recorded...
    # ...but the state never crosses the TEST_SCENARIO ceiling (contract.SCENARIO_MAX_STATE).
    assert machine.current_state(tmp_path, an_intent["intent_id"]) == contract.S_SHADOW_EXECUTED
    with pytest.raises(machine.IllegalTransition):
        machine.advance(tmp_path, an_intent, contract.S_RECONCILED, {}, NOW)


def test_readiness_reconciliation_gate_per_venue(tmp_path):
    _seed_common(tmp_path)
    atomic_save([{"trade_id": "T1", "ts": "2026-10-01T00:00:00Z", "from_allocation": {},
                 "to_allocation": {"aave_v3": 1000.0, "fluid_fusdc": 500.0}}], str(tmp_path / "trades.json"))
    entries = [
        {"seq": 1, "kind": "reconciliation", "payload": {"venue": "aave_v3", "outcome": contract.REC_MATCHED,
         "sleeve_id": "defi_conservative"}},
        {"seq": 2, "kind": "reconciliation", "payload": {"venue": "fluid_fusdc", "outcome": contract.REC_MISMATCH,
         "sleeve_id": "defi_conservative"}},
        # a scenario-canary row for the SAME venue must never satisfy a real sleeve's gate (review #3).
        {"seq": 3, "kind": "reconciliation", "payload": {"venue": "fluid_fusdc", "outcome": contract.REC_MATCHED,
         "sleeve_id": "scenario_canary"}},
    ]
    gate = readiness._reconciliation_gate(tmp_path, entries, "defi_conservative")
    assert gate["state"] == contract.GATE_FAIL
    assert gate["evidence"]["not_matched"] == ["fluid_fusdc"]

    entries[1]["payload"]["outcome"] = contract.REC_MATCHED
    gate = readiness._reconciliation_gate(tmp_path, entries, "defi_conservative")
    assert gate["state"] == contract.GATE_PASS


# ── --no-rpc GUARANTEES NO NETWORK ───────────────────────────────────────────────────────────────

def test_no_rpc_mode_never_touches_the_network(tmp_path, monkeypatch):
    _seed_common(tmp_path)
    called = []

    def _poisoned_urlopen(*args, **kwargs):
        called.append((args, kwargs))
        raise AssertionError("network I/O attempted despite --no-rpc")

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", _poisoned_urlopen)

    # default (live_rpc=False, no client injected) — run.py must install a client that refuses
    # every call BEFORE simulate.simulate_intent ever gets a chance to build its own live one.
    summary = run_mod.run_cycle(tmp_path, NOW, scenario="netguard", live_rpc=False)
    assert called == []
    assert summary["current_intents"] == 3
    # review #12: --no-rpc means pin.state != MEASURED, so every scenario ACTION intent refuses to
    # be built at all (NO_ACTION "no pinned block") — never silently simulated against no quorum.
    assert summary["scenario_intents"] == 6
    assert all(r["outcome"] == "NO_ACTION" for r in summary["per_intent"])


def test_no_rpc_refusing_client_answers_without_any_io():
    cl = run_mod._RefusingClient()
    assert cl.pin_block()["state"] == contract.NOT_MEASURED
    assert cl.quorum("eth_call", [], None)["state"] == contract.NOT_MEASURED


# ── read.latest() SUMMARY BLOCK FOR MISSION CONTROL ─────────────────────────────────────────────

def test_read_latest_summary_block_shape_and_content(tmp_path):
    _seed_common(tmp_path)
    run_mod.run_cycle(tmp_path, NOW, scenario="summary", live_rpc=False)
    result = read.latest(tmp_path, now=NOW)
    assert result["state"] == contract.MEASURED
    summary = result["summary"]
    assert set(summary.keys()) == {
        "last_simulation", "last_shadow_execution", "last_reconciliation",
        "last_simulation_canary", "last_shadow_execution_canary", "last_reconciliation_canary",
        "current_state_intent_counts", "scenario_intent_counts", "open_incidents", "owner_decisions_pending",
        "current_execution_mode", "automated_live_execution", "real_capital_usd", "top_blockers", "generated_at",
    }
    assert summary["current_execution_mode"] == contract.LAYER_MODE
    assert summary["automated_live_execution"] == contract.AUTOMATED_LIVE_EXECUTION
    assert summary["real_capital_usd"] == contract.REAL_CAPITAL_USD
    assert summary["current_state_intent_counts"].get("NO_ACTION") == 3
    assert sum(summary["scenario_intent_counts"].values()) == 6
    assert summary["owner_decisions_pending"] <= 4
    assert len(summary["top_blockers"]) <= 5
    assert summary["open_incidents"]["count"] == 0
    assert summary["open_incidents"]["kinds"] == []
    # secret-free / path-free: no filesystem path or secret-shaped token anywhere in the block.
    blob = json.dumps(summary, default=str)
    assert str(tmp_path) not in blob
    assert "/" not in blob.replace("http", "")  # no path separators outside an (absent) URL
    if summary["last_simulation"] is not None:
        assert set(summary["last_simulation"].keys()) == {"intent_id", "venue", "action", "result", "block", "at"}
        assert len(summary["last_simulation"]["intent_id"]) == 12
    if summary["last_reconciliation"] is not None:
        assert set(summary["last_reconciliation"].keys()) == {"intent_id", "venue", "outcome", "blocks", "at"}


def test_read_latest_owner_decisions_pending_is_deduplicated(tmp_path):
    reports = {
        "defi_conservative": {"owner_preconditions": {"golive_decision": {"state": "PENDING"},
                              "custody": {"state": "PENDING"}}},
        "defi_balanced": {"owner_preconditions": {"golive_decision": {"state": "PENDING"},
                          "custody": {"state": "PENDING"}}},
    }
    assert read._owner_decisions_pending(reports) == 2  # not 4 — deduplicated by precondition name


def test_read_latest_top_blockers_counts_across_defi_sleeves():
    def _checks(**overrides):
        base = {g: {"state": contract.GATE_PASS} for g in contract.SYSTEM_GATES}
        base.update(overrides)
        return base

    reports = {
        "defi_conservative": {"system_checks": _checks(counterparty_evidence={"state": contract.GATE_UNKNOWN})},
        "defi_balanced": {"system_checks": _checks(counterparty_evidence={"state": contract.GATE_UNKNOWN},
                         risk_evidence={"state": contract.GATE_FAIL})},
        "defi_aggressive": {"system_checks": _checks(counterparty_evidence={"state": contract.GATE_UNKNOWN})},
        "cash": {"system_checks": _checks(offhost_anchor={"state": contract.GATE_FAIL})},  # NOT a DeFi sleeve
    }
    top = read._top_blockers(reports, top_n=5)
    assert top[0] == {"gate": "counterparty_evidence", "count": 3}
    assert all(b["gate"] != "offhost_anchor" or False for b in top)  # cash's own blocker never counted
    assert "offhost_anchor" not in {b["gate"] for b in top}


# ── #13: concurrent runners — TWO REAL CLI subprocesses on the SAME data dir ────────────────────

def test_concurrent_run_cycle_subprocesses_one_locked_chain_intact(tmp_path):
    """Two REAL ``python -m spa_core.capital_shadow.run`` processes against the SAME data_dir,
    launched together: the top-level run lock (review #13) must serialise them — one succeeds
    (exit 0) and the other is locked out (exit 75, LOCKED), OR both succeed because the first
    finished before the second even tried; either way the ledger chain stays intact and NEVER
    shows interleaved/corrupted lines."""
    import subprocess
    import sys as _sys

    _seed_common(tmp_path)
    cmd = [_sys.executable, "-m", "spa_core.capital_shadow.run", "--data-dir", str(tmp_path),
          "--now", "2026-10-04T12:00:00Z"]
    env = dict(__import__("os").environ)
    p1 = subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parents[2]), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env)
    p2 = subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parents[2]), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env)
    out1, err1 = p1.communicate(timeout=60)
    out2, err2 = p2.communicate(timeout=60)

    codes = {p1.returncode, p2.returncode}
    # every observed exit code must be one of: OK, or LOCKED (never an unexpected crash).
    assert codes <= {contract.EXIT_OK, contract.EXIT_LOCKED}, (p1.returncode, p2.returncode, out1, err1, out2, err2)
    # at least one of them must have actually run the cycle.
    assert contract.EXIT_OK in codes

    chain = ledger.verify_chain(tmp_path)
    assert chain["ok"] is True, chain
    # no interleaved/corrupted line: read_all must parse cleanly end to end.
    entries = ledger.read_all(tmp_path)
    assert len(entries) > 0


def test_canary_deposit_reconciles_matched_without_a_book_but_a_real_intent_needs_the_book(tmp_path):
    """A TEST_SCENARIO canary holds no book position: book_mark does not apply to it, so a forward
    re-read with matching shares/code/asset is MATCHED (canary evidence never reaches a sleeve gate).
    The SAME comparison for a CURRENT-STATE intent without a book position stays NOT_MEASURED."""
    from types import SimpleNamespace
    canary = next(i for i in intent_mod.build_scenario_intents(NOW, _pin(), "rec")
                  if i["action_type"] == contract.ACTION_DEPOSIT_4626)
    sim = {"block": {"number": 100}, "post_state": {"shares_returned": 820_000_000}}
    client = SimpleNamespace(pin_block=lambda: {"state": contract.MEASURED, "number": 120, "hash": "0x" + "cd" * 32,
                                                "operators": ["Allnodes", "dRPC"]})
    sim_mod = SimpleNamespace(preview_deposit_at=lambda venue, amount, client: {
        "state": contract.MEASURED, "preview_shares": 820_000_000, "block": 120, "code_present": True,
        "asset_ok": True, "reason": None})
    r = reconcile.forward_reconcile(canary, sim, client=client, now=NOW, simulate_mod=sim_mod, data_dir=tmp_path)
    assert r["outcome"] == contract.REC_MATCHED, r
    real = dict(canary, scenario=contract.SCENARIO_CURRENT, sleeve_id="defi_balanced")
    r2 = reconcile.forward_reconcile(real, sim, client=client, now=NOW, simulate_mod=sim_mod, data_dir=tmp_path)
    assert r2["outcome"] == contract.REC_NOT_MEASURED, r2


# ── ROUND-5 REVIEW REGRESSION TESTS ─────────────────────────────────────────────────────────────
# Each test below fails without the corresponding fix; see run.py/machine.py/readiness.py/read.py/
# intent.py inline review comments for the matching N-number.

def test_n2_policy_violation_compares_base_units_not_human_notional():
    """review N2: machine.policy_violation must compare the simulated APPROVE amount (BASE units,
    what is actually encoded on-chain) against the intent's own notional ALSO converted to base
    units — never the bare human float. A correct 1000 USDC approve (1_000_000_000 base units at 6
    decimals) must PASS; the OLD (buggy) comparison against the raw human float 1000.0 would have
    rejected this exact, correct call."""
    an_intent = next(i for i in intent_mod.build_scenario_intents(NOW, _pin(), "n2")
                     if i["action_type"] == contract.ACTION_APPROVE)
    assert an_intent["network_or_venue"] == "aave_v3" and an_intent["notional"] == 1000.0
    correct_base_units = intent_mod.to_base_units_for_intent(an_intent)
    assert correct_base_units == 1_000_000_000  # 1000 USDC @ 6 decimals

    sim_correct = {"gas_estimate": 50_000, "call": {"args_readable": [
        {"name": "amount", "value": correct_base_units}]}}
    assert machine.policy_violation(an_intent, sim_correct) is None

    # the OLD bug: comparing against the bare human notional (1000.0) instead of base units. A
    # call that actually encodes the CORRECT base-units amount must never be flagged by it — but a
    # call using the raw human float as if it WERE base units (1000 base units == $0.001, a huge
    # under-approval) must be CAUGHT, never coincidentally accepted.
    sim_human_units_only = {"gas_estimate": 50_000, "call": {"args_readable": [
        {"name": "amount", "value": an_intent["notional"]}]}}
    violation = machine.policy_violation(an_intent, sim_human_units_only)
    assert violation is not None and "base units" in violation


def test_n4_read_summary_surfaces_a_broken_incident_store(tmp_path, monkeypatch):
    """review N4: a torn/tampered incidents store must surface in read.latest()'s summary as
    ``open_incidents == {"state": "BROKEN", "reason": <str>, "count": None, "kinds": []}`` — never
    silently read as "zero open incidents" (which looks identical to a healthy, quiet system)."""
    _seed_common(tmp_path)
    run_mod.run_cycle(tmp_path, NOW, scenario="n4", live_rpc=False)

    def _broken_store_state(data_dir):
        return {"state": "BROKEN", "reason": "incidents store is BROKEN (reason=torn_line, break_at=2, "
                "entries=3)"}

    def _raise_if_called(data_dir):
        raise AssertionError("open_incidents must never be called when the store is BROKEN")

    monkeypatch.setattr(incidents, "store_state", _broken_store_state)
    monkeypatch.setattr(incidents, "open_incidents", _raise_if_called)
    result = read.latest(tmp_path, now=NOW)
    assert result["state"] == contract.MEASURED  # the LEDGER (not the incidents store) is intact
    open_incs = result["summary"]["open_incidents"]
    assert open_incs["state"] == "BROKEN"
    assert open_incs["reason"] is not None
    assert open_incs["count"] is None
    assert open_incs["kinds"] == []


def test_n4_read_summary_reports_ok_incident_store_normally(tmp_path):
    _seed_common(tmp_path)
    run_mod.run_cycle(tmp_path, NOW, scenario="n4ok", live_rpc=False)
    result = read.latest(tmp_path, now=NOW)
    open_incs = result["summary"]["open_incidents"]
    assert open_incs["state"] == "OK"
    assert open_incs["reason"] is None
    assert open_incs["count"] == 0


def test_n5_venue_canary_is_a_separate_top_level_key_never_inside_readiness(tmp_path):
    """review N5: read.latest()["readiness"] must contain ONLY sleeve reports (every value has a
    "readiness_state" key) — venue_canary lives at its OWN top-level key."""
    _seed_common(tmp_path)
    run_mod.run_cycle(tmp_path, NOW, scenario="n5", live_rpc=False)
    result = read.latest(tmp_path, now=NOW)
    assert "venue_canary" not in result["readiness"]
    assert all("readiness_state" in v for v in result["readiness"].values())
    assert "venue_canary" in result
    assert result["venue_canary"]["sleeve_id"] == "scenario_canary"


def test_n6_blocked_trade_stays_retry_eligible_within_window_then_goes_stale(tmp_path, monkeypatch):
    """review N6: a trade blocked by a risk blocker (here: the permanently-unmeasured depeg gate,
    seeded by _seed_common) must stay eligible for retry while the first blocked attempt is
    younger than intent_mod.TRADE_RETRY_WINDOW_S — it must NEVER be permanently consumed by a
    blocked NO_ACTION. Past the window it is finalized exactly once as "trade stale", and only
    THEN is it permanently consumed (no more per-protocol attempts)."""
    _seed_common(tmp_path)
    _allow_cio(monkeypatch)
    atomic_save({"decision_shadow": {"verdict": "RECOMMEND"}}, str(tmp_path / "allocation_rationale.json"))

    t0 = NOW
    intents_t0 = intent_mod.build_current_intents(tmp_path, t0, _pin())
    conservative_t0 = next(i for i in intents_t0 if i["sleeve_id"] == "defi_conservative")
    assert conservative_t0["action_type"] == contract.ACTION_NO_ACTION
    assert "blocked by current risk state" in conservative_t0["reason"]
    machine.record_intent(tmp_path, conservative_t0, t0)

    # within the window (1h later): RETRY-eligible — attempted again, never silently dropped just
    # because a blocked attempt for this SAME trade/protocol already exists on the ledger. The
    # reason text is stable (same blocking condition), so this reproduces the SAME intent_id as
    # t0 by design (review: a content hash has no "now" field) — record_intent is correctly
    # idempotent on it; what matters is that build_current_intents keeps OFFERING the retry
    # rather than silently going to "already consumed" before the window has elapsed.
    t1 = t0 + timedelta(hours=1)
    intents_t1 = intent_mod.build_current_intents(tmp_path, t1, _pin())
    conservative_t1 = next(i for i in intents_t1 if i["sleeve_id"] == "defi_conservative")
    assert conservative_t1["action_type"] == contract.ACTION_NO_ACTION
    assert "blocked by current risk state" in conservative_t1["reason"]
    assert "stale" not in conservative_t1["reason"]
    machine.record_intent(tmp_path, conservative_t1, t1)

    # still within the window at 48h (two daily cycles) — this is EXACTLY the gap the round-3
    # re-review found broken at the old 6h TTL-shaped window: still RETRY, never stale.
    t_mid = t0 + timedelta(hours=48)
    intents_mid = intent_mod.build_current_intents(tmp_path, t_mid, _pin())
    conservative_mid = next(i for i in intents_mid if i["sleeve_id"] == "defi_conservative")
    assert conservative_mid["action_type"] == contract.ACTION_NO_ACTION
    assert "blocked by current risk state" in conservative_mid["reason"]
    assert "stale" not in conservative_mid["reason"]
    machine.record_intent(tmp_path, conservative_mid, t_mid)

    # past the window (72h+): finalized ONCE as "trade stale".
    t2 = t0 + timedelta(seconds=intent_mod.TRADE_RETRY_WINDOW_S + 3600)
    intents_t2 = intent_mod.build_current_intents(tmp_path, t2, _pin())
    conservative_t2 = next(i for i in intents_t2 if i["sleeve_id"] == "defi_conservative")
    assert conservative_t2["action_type"] == contract.ACTION_NO_ACTION
    assert "stale" in conservative_t2["reason"]
    machine.record_intent(tmp_path, conservative_t2, t2)

    # ...and from then on permanently consumed — only the generic "already consumed" message.
    t3 = t2 + timedelta(hours=1)
    intents_t3 = intent_mod.build_current_intents(tmp_path, t3, _pin())
    conservative_t3 = next(i for i in intents_t3 if i["sleeve_id"] == "defi_conservative")
    assert conservative_t3["action_type"] == contract.ACTION_NO_ACTION
    assert "already consumed" in conservative_t3["reason"]


def test_n6_round3_trade_cleared_after_one_daily_cycle_still_rebuilds_a_real_action(tmp_path, monkeypatch):
    """review N6 round-3 re-review's exact scenario: a trade blocked on day 0 and UNBLOCKED on
    day +1 (one daily cycle later, 24h) must still produce a REAL action intent — at the OLD
    window (contract.INTENT_TTL_SHADOW_S == 6h) this trade would already have been finalized
    "stale" long before the first daily cycle ever got a chance to retry it, and the original
    symptom (a cleared trade never executed) would have survived the first N6 fix."""
    _seed_common(tmp_path)
    _allow_cio(monkeypatch)
    atomic_save({"decision_shadow": {"verdict": "RECOMMEND"}}, str(tmp_path / "allocation_rationale.json"))

    t0 = NOW
    intents_t0 = intent_mod.build_current_intents(tmp_path, t0, _pin())
    conservative_t0 = next(i for i in intents_t0 if i["sleeve_id"] == "defi_conservative")
    assert conservative_t0["action_type"] == contract.ACTION_NO_ACTION
    assert "blocked by current risk state" in conservative_t0["reason"]
    machine.record_intent(tmp_path, conservative_t0, t0)

    # day +1 (24h later, one daily cycle): the blocking condition clears. (The real depeg gate is
    # permanently unmeasured and can never clear on its own — monkeypatched here so the test is
    # about the RETRY WINDOW, not about depeg ever becoming measured.)
    monkeypatch.setattr(intent_mod, "risk_blockers", lambda risk_snapshot: [])
    t1 = t0 + timedelta(hours=24)
    intents_t1 = intent_mod.build_current_intents(tmp_path, t1, _pin())
    conservative_t1 = next(i for i in intents_t1 if i["sleeve_id"] == "defi_conservative")
    assert conservative_t1["action_type"] == contract.ACTION_SUPPLY
    assert conservative_t1["network_or_venue"] == "aave_v3"
    assert conservative_t1["notional"] == 1000.0


def test_n6_no_action_on_missing_pin_is_date_scoped_to_avoid_id_collision(tmp_path, monkeypatch):
    """review N6: a NO_ACTION built on a constant NOT_MEASURED pin must not collide (same
    intent_id) across two different days — strategy_id carries the date so each day's blocked
    attempt gets its own ledger row, never silently deduplicated as "already recorded". The
    permanently-unmeasured depeg gate (no real source exists) would otherwise ALWAYS win the
    "blocked by current risk state" branch first — risk_blockers is monkeypatched to [] here so
    the "no pinned block" branch (the one review N6 actually date-scopes) is the one exercised."""
    _seed_common(tmp_path)
    _allow_cio(monkeypatch)
    atomic_save({"decision_shadow": {"verdict": "RECOMMEND"}}, str(tmp_path / "allocation_rationale.json"))
    monkeypatch.setattr(intent_mod, "risk_blockers", lambda risk_snapshot: [])
    no_pin = {"state": contract.NOT_MEASURED, "number": None, "hash": None, "operators": []}

    day1 = NOW
    day2 = NOW + timedelta(days=1)
    intents_day1 = intent_mod.build_current_intents(tmp_path, day1, no_pin)
    intents_day2 = intent_mod.build_current_intents(tmp_path, day2, no_pin)
    conservative_day1 = next(i for i in intents_day1 if i["sleeve_id"] == "defi_conservative")
    conservative_day2 = next(i for i in intents_day2 if i["sleeve_id"] == "defi_conservative")
    assert conservative_day1["action_type"] == contract.ACTION_NO_ACTION
    assert conservative_day2["action_type"] == contract.ACTION_NO_ACTION
    assert "no pinned block" in conservative_day1["reason"]
    assert "no pinned block" in conservative_day2["reason"]
    assert conservative_day1["intent_id"] != conservative_day2["intent_id"]
    assert conservative_day1["strategy_id"] != conservative_day2["strategy_id"]
    assert day1.strftime("%Y-%m-%d") in conservative_day1["strategy_id"]
    assert day2.strftime("%Y-%m-%d") in conservative_day2["strategy_id"]


# ── #5 remainder: security-event escalation from the PIN client and forward-reconciliation clients

class _SecurityEventClient:
    """A fake RpcClient-shaped object whose security_events list grows across calls, exactly like
    the real rpc.RpcClient accumulates quorum-disagreement/forbidden-method events. Each call's
    event carries its OWN call count in the detail text — distinct real events, deliberately never
    identical-content duplicates (review round-3 L3's identity-set dedup is keyed on (kind,
    detail); a fake that emitted the exact same detail text every call would be indistinguishable
    from "the same event read twice" by construction, and could never test "N real events -> N
    incidents" at all)."""

    def __init__(self, block=100):
        self._block = block
        self.security_events = []
        self._n = 0

    def pin_block(self):
        self._n += 1
        self.security_events.append({"kind": "quorum_disagreement", "detail": f"2-of-3 quorum reached, "
                                     f"1 dissenting operator (call #{self._n})"})
        return {"state": contract.MEASURED, "number": self._block, "hash": "0x" + "cd" * 32,
               "operators": ["Allnodes", "dRPC"]}


def test_5_remainder_get_pin_escalates_the_pin_clients_own_security_events(tmp_path):
    """review #5 remainder: _get_pin's OWN client (used for the run's pinned block) must escalate
    its security_events to incidents too — not just the per-intent simulation/reconciliation
    clients."""
    client = _SecurityEventClient()

    class _SpyDispatcher:
        def create_alert(self, level, title, message, adapter_id=None):
            return object()

        def dispatch(self, alert):
            return {"channels_succeeded": ["log"]}

    pin = run_mod._get_pin(1, live_rpc=True, client=client, data_dir=tmp_path, now=NOW,
                          dispatcher=_SpyDispatcher())
    assert pin["state"] == contract.MEASURED
    open_incs = incidents.open_incidents(tmp_path)
    assert len(open_incs) == 1
    assert open_incs[0]["kind"] == "quorum_disagreement"


def test_5_remainder_forward_reconciliation_escalates_and_never_duplicates_across_intents(
        tmp_path, monkeypatch):
    """review #5 remainder: _run_forward_reconciliation must escalate security_events raised by
    the client it REUSES across MULTIPLE pending intents in one pass — every REAL event becomes
    exactly ONE incident, never re-escalated just because the same (growing) security_events list
    is inspected again for the NEXT intent sharing the client."""
    intent_a = _shadow_execute_deposit(tmp_path, monkeypatch, old_block=100, sleeve_id="defi_balanced",
                                       venue="fluid_fusdc", notional=1000.0)
    intent_b = _shadow_execute_deposit(tmp_path, monkeypatch, old_block=100, sleeve_id="defi_aggressive",
                                       venue="fluid_fusdc", notional=1000.0)
    client = _SecurityEventClient(block=150)

    run_mod._run_forward_reconciliation(tmp_path, NOW, rpc_mod=None,
                                        simulate_mod=_FakeForwardSimulate(1000.0), client=client)
    # the SAME client was reused for BOTH intents (pin_block called at least once per intent) —
    # every event it ever recorded must be escalated EXACTLY once, never duplicated.
    assert len(client.security_events) >= 2
    open_incs = incidents.open_incidents(tmp_path)
    assert len(open_incs) == len(client.security_events)


# ── #10 caveat: observability gate is an ALLOWLIST (PASS only on exactly OK/HEALTHY) ────────────

def test_10_observability_gate_allowlist_fails_on_unknown_status(tmp_path):
    _seed_common(tmp_path)
    atomic_save({
        "timestamp": "2026-10-04T12:00:00Z", "overall_status": "OK", "healthy_count": 1, "total_agents": 1,
        "agents": [{"label": "com.spa.daily_cycle", "status": "DEGRADED", "pid": 0, "last_exit": 0,
                   "log_age_min": 1.0, "category": "daily", "loaded": True, "issue": "", "note": ""}],
    }, str(tmp_path / "agent_health.json"))
    gate = readiness._observability_gate(tmp_path, "defi_conservative")
    assert gate["state"] == contract.GATE_FAIL
    assert gate["evidence"]["status"] == "DEGRADED"


def test_10_observability_gate_allowlist_passes_on_ok_and_healthy_only(tmp_path):
    _seed_common(tmp_path)
    for status in ("OK", "HEALTHY"):
        atomic_save({
            "timestamp": "2026-10-04T12:00:00Z", "overall_status": status, "healthy_count": 1,
            "total_agents": 1,
            "agents": [{"label": "com.spa.daily_cycle", "status": status, "pid": 0, "last_exit": 0,
                       "log_age_min": 1.0, "category": "daily", "loaded": True, "issue": "", "note": ""}],
        }, str(tmp_path / "agent_health.json"))
        gate = readiness._observability_gate(tmp_path, "defi_conservative")
        assert gate["state"] == contract.GATE_PASS, status


# ── N1(b): kill_switch_clear gate must ALSO require freshness (generated_at within 26h) ─────────

def test_n1b_kill_switch_clear_gate_fails_on_a_stale_clear(tmp_path):
    atomic_save({"generated_at": "2026-10-03T09:00:00Z", "triggered": False, "state": "CLEAR"},
               str(tmp_path / "kill_switch_status.json"))  # 27h before NOW (2026-10-04T12:00:00Z)
    gate = readiness._kill_switch_gate(tmp_path, NOW)
    assert gate["state"] == contract.GATE_FAIL
    assert gate["evidence"]["age_hours"] > 26.0


def test_n1b_kill_switch_clear_gate_passes_on_a_fresh_clear(tmp_path):
    atomic_save({"generated_at": "2026-10-04T11:00:00Z", "triggered": False, "state": "CLEAR"},
               str(tmp_path / "kill_switch_status.json"))  # 1h before NOW
    gate = readiness._kill_switch_gate(tmp_path, NOW)
    assert gate["state"] == contract.GATE_PASS


# ── #15 caveat: SPOT_ORDER's shadow fixture funds the order with its OWN notional, never a
#    silent 0.0 that would reject every spot order out of the gate ─────────────────────────────

def test_15_spot_order_fixture_funds_cash_explicitly_never_defaults_to_zero(tmp_path):
    an_intent = next(i for i in intent_mod.build_scenario_intents(NOW, _pin(), "n15")
                     if i["action_type"] == contract.ACTION_SPOT_ORDER)
    run_mod._validate(tmp_path, an_intent, NOW)
    rep = run_mod._simulate_and_execute(tmp_path, an_intent, NOW, simulate_mod=None, client=None)
    assert rep["outcome"] == "SIMULATED"
    sim = ledger.load_simulation(tmp_path, an_intent["intent_id"])
    order = sim["call"]["args_readable"][0]["value"]
    assert order["cash"] == an_intent["notional"]
    assert order["cash"] > 0.0


# ── round-3 item 2: a SPOT_ORDER partial fill must NEVER be recorded as a clean SIM_PASS ────────

def test_round3_spot_order_partial_fill_is_never_recorded_as_sim_pass(tmp_path):
    """review round-3 item 2: exchange_sim.simulate_order sets accepted=True for BOTH a full fill
    AND a STATUS_PARTIAL one — the OLD run.py read only "accepted" and recorded a partial fill as
    SIM_PASS, advancing the intent to SIMULATED exactly like a clean pass. Drives the REAL
    run.py SPOT_ORDER path with a notional that exceeds the hardcoded book's liquidity (1,000,000
    units at price 1.0) — the fill really is STATUS_PARTIAL, not a test double standing in for
    one."""
    from spa_core.capital_shadow import exchange_sim as real_exchange_sim
    an_intent = intent_mod._base_fields(
        now=NOW, pin=_pin(), sleeve_id=intent_mod.CANARY_SLEEVE, strategy_id="scenario_canary:spot_partial",
        action_type=contract.ACTION_SPOT_ORDER, network_or_venue="binance_spot", instrument="binance_spot",
        from_asset="USDC", to_asset="USDC", notional=2_000_000.0, notional_unit="USDC",
        source_recommendation_id=None, source_role_id=contract.SOURCE_ROLE_ID, source_book_decision=None,
        risk_snapshot={k: {"state": contract.NOT_MEASURED, "value": None, "as_of": None, "digest": None,
        "reason": "TEST_SCENARIO — not a real decision"} for k in ("kill_switch", "derisk", "riskpolicy_verdict",
        "riskpolicy_version", "cio_recommendation_id", "cio_stance", "book_state_digest", "depeg")},
        unknowns=[], reason="round-3 item 2 fixture: notional exceeds the hardcoded book liquidity",
        scenario=f"{contract.SCENARIO_TEST_PREFIX}spot_partial")
    run_mod._validate(tmp_path, an_intent, NOW)
    rep = run_mod._simulate_and_execute(tmp_path, an_intent, NOW, simulate_mod=None, client=None)

    assert rep["outcome"] == "SIMULATION_FAILED"  # NEVER "SIMULATED" — a partial fill is not a pass
    sim = ledger.load_simulation(tmp_path, an_intent["intent_id"])
    assert sim["result"] != contract.SIM_PASS
    assert sim["result"] == "PARTIAL"
    assert sim["post_state"]["status"] == real_exchange_sim.STATUS_PARTIAL
    assert sim["post_state"]["partial_fill"] is True
    # the machine itself must never have advanced to S_SIMULATED (a PASS-shaped state).
    assert machine.current_state(tmp_path, an_intent["intent_id"]) == contract.S_SIMULATION_FAILED


# ── round-3 item L1: policy_violation must fail-CLOSED when it cannot verify ────────────────────

def test_l1_policy_violation_unresolvable_base_units_is_a_violation():
    """review round-3 L1: if the intent's own notional cannot be resolved to base units (unknown
    venue/token/decimals), that IS a violation (fail-closed) — the OLD guard silently skipped the
    whole comparison and returned "no violation" (None) whenever `expected` was None."""
    an_intent = {"constraints": {}, "action_type": contract.ACTION_APPROVE, "notional": 1000.0,
                "network_or_venue": "not_a_real_venue", "notional_unit": "USDC", "from_asset": "USDC"}
    sim = {"gas_estimate": 50_000, "call": {"args_readable": [{"name": "amount", "value": 1_000_000_000}]}}
    violation = machine.policy_violation(an_intent, sim)
    assert violation is not None
    assert "cannot resolve" in violation


def test_l1_policy_violation_bool_approve_amount_is_a_violation():
    """review round-3 L1: a bool amount value (e.g. a malformed simulated call) must never be
    silently treated as "not a violation" just because isinstance(True, int) is True in Python."""
    an_intent = next(i for i in intent_mod.build_scenario_intents(NOW, _pin(), "l1bool")
                     if i["action_type"] == contract.ACTION_APPROVE)
    sim = {"gas_estimate": 50_000, "call": {"args_readable": [{"name": "amount", "value": True}]}}
    violation = machine.policy_violation(an_intent, sim)
    assert violation is not None
    assert "not a plain integer" in violation


def test_l1_policy_violation_float_approve_amount_is_a_violation():
    """review round-3 L1: base units are always an exact integer — a float value (even one that
    happens to equal the expected integer numerically) must never pass silently."""
    an_intent = next(i for i in intent_mod.build_scenario_intents(NOW, _pin(), "l1float")
                     if i["action_type"] == contract.ACTION_APPROVE)
    expected = intent_mod.to_base_units_for_intent(an_intent)
    sim = {"gas_estimate": 50_000, "call": {"args_readable": [{"name": "amount", "value": float(expected)}]}}
    violation = machine.policy_violation(an_intent, sim)
    assert violation is not None
    assert "not a plain integer" in violation


def test_l3_one_event_yields_one_incident_across_pin_and_forward_reconciliation(tmp_path, monkeypatch):
    """review round-3 L3: when ONE client is shared between _get_pin and
    _run_forward_reconciliation (both run inside the SAME run_cycle), the client's
    security_events list is read at BOTH sites — without a single shared identity tracker, each
    site's own "start from zero" memory re-escalated the same real events again (measured: 6 real
    events -> 16 incidents). Threading ONE shared `escalated` set through both calls — exactly as
    run_cycle now does — must yield exactly one incident per distinct real event, never one per
    site."""
    an_intent = _shadow_execute_deposit(tmp_path, monkeypatch, old_block=100, sleeve_id="defi_balanced",
                                        venue="fluid_fusdc", notional=1000.0)
    client = _SecurityEventClient(block=150)
    escalated: set = set()

    # site 1: _get_pin touches the client and escalates its (so far: one) event.
    run_mod._get_pin(1, live_rpc=True, client=client, data_dir=tmp_path, now=NOW, escalated=escalated)
    # site 2: forward reconciliation REUSES the SAME client (its pin_block() is called again,
    # appending another distinct event) and must escalate ONLY what site 1 did not already.
    run_mod._run_forward_reconciliation(tmp_path, NOW, rpc_mod=None, simulate_mod=_FakeForwardSimulate(1000.0),
                                        client=client, escalated=escalated)

    assert len(client.security_events) >= 2
    open_incs = incidents.open_incidents(tmp_path)
    assert len(open_incs) == len(client.security_events)


# ── round-3 item L4: kill_armed must catch the REAL writer's states, not an imagined allowlist ──

def test_l4_kill_armed_catches_the_real_writers_triggered_state(tmp_path):
    """review round-3 L4: the REAL writer (spa_core/governance/kill_switch.py, ADR-531) publishes
    state="TRIGGERED" — the OLD kill_armed only matched "HARD_KILL"/"ARMED" (names the real writer
    never writes), so a genuinely triggered kill-switch never forced readiness_state to BLOCKED
    via this independent hard-block signal."""
    _seed_common(tmp_path)
    atomic_save({"generated_at": "2026-10-04T11:00:00Z", "triggered": True, "state": "TRIGGERED",
                "reason": "drawdown >= 10%"}, str(tmp_path / "kill_switch_status.json"))
    reports = readiness.evaluate(tmp_path, [], NOW)
    assert reports["defi_conservative"]["readiness_state"] == contract.R_BLOCKED


def test_l4_kill_armed_treats_clear_partial_as_armed_too(tmp_path):
    """review round-3 L4: CLEAR_PARTIAL ("all measured but partial/not-yet-applicable triggers")
    is NOT full confidence of safety and must be armed too — fail-closed treats anything other
    than the exact string "CLEAR" as armed, never an allowlist of specific "bad" names."""
    _seed_common(tmp_path)
    atomic_save({"generated_at": "2026-10-04T11:00:00Z", "triggered": False, "state": "CLEAR_PARTIAL",
                "reason": "no trigger fired; partial: red_flags PARTIAL"},
               str(tmp_path / "kill_switch_status.json"))
    reports = readiness.evaluate(tmp_path, [], NOW)
    assert reports["defi_conservative"]["readiness_state"] == contract.R_BLOCKED


def test_l4_kill_armed_false_on_exact_clear(tmp_path):
    """the exact string "CLEAR" (and only that) is NOT armed — kill_armed must not become so
    aggressive that it blocks everything regardless of state."""
    _seed_common(tmp_path)  # kill_switch_status.json state == "CLEAR"
    reports = readiness.evaluate(tmp_path, [], NOW)
    assert reports["defi_conservative"]["readiness_state"] != contract.R_BLOCKED


# ── round-3 item L5: readiness evidence filters on BOTH sleeve_id AND scenario ───────────────────

def test_l5_scenario_row_with_a_real_sleeve_id_never_satisfies_the_reconciliation_gate(tmp_path):
    """review round-3 L5: a row whose OWNING intent's scenario starts with the TEST_SCENARIO
    prefix must never feed a real sleeve's gates, WHATEVER its sleeve_id — the OLD filter
    (sleeve_id equality alone) relied entirely on every scenario-intent-builder always setting
    CANARY_SLEEVE; this reproduces the one case that filter cannot catch: a scenario row that
    (by a hypothetical bug elsewhere) carries a REAL sleeve_id."""
    _seed_common(tmp_path)
    atomic_save([{"trade_id": "T1", "ts": "2026-10-01T00:00:00Z", "from_allocation": {},
                 "to_allocation": {"aave_v3": 1000.0}}], str(tmp_path / "trades.json"))
    entries = [
        {"seq": 1, "kind": "intent", "payload": {"intent_id": "fake-scenario-leak", "sleeve_id":
         "defi_conservative", "scenario": f"{contract.SCENARIO_TEST_PREFIX}leak"}},
        {"seq": 2, "kind": "reconciliation", "payload": {"intent_id": "fake-scenario-leak", "venue": "aave_v3",
         "outcome": contract.REC_MATCHED, "sleeve_id": "defi_conservative"}},
    ]
    gate = readiness._reconciliation_gate(tmp_path, entries, "defi_conservative")
    # the only row claiming MATCHED belongs to a scenario intent — it must not count, so the gate
    # reports the venue MISSING, never a clean PASS.
    assert gate["state"] == contract.GATE_FAIL
    assert "aave_v3" in gate["evidence"]["missing"]


def test_l5_scenario_intent_ids_reads_off_the_intent_row_never_the_evidence_payload(tmp_path):
    """_scenario_intent_ids must read the owning intent's OWN scenario field — simulation /
    reconciliation / unwind_probe payloads carry no scenario field of their own (confirmed by
    reading ledger.record_simulation_entry and reconcile.forward_reconcile)."""
    entries = [
        {"seq": 1, "kind": "intent", "payload": {"intent_id": "a", "scenario":
         f"{contract.SCENARIO_TEST_PREFIX}x"}},
        {"seq": 2, "kind": "intent", "payload": {"intent_id": "b", "scenario": contract.SCENARIO_CURRENT}},
    ]
    ids = readiness._scenario_intent_ids(entries)
    assert ids == {"a"}


# ── round-3 item L5: the scenario ceiling (and every scenario-prefix check) is case-insensitive ──

def test_l5_scenario_ceiling_is_case_insensitive_on_the_prefix(tmp_path):
    """review round-3 L5: a lowercase "test_scenario:..." intent must be treated as a scenario
    intent EXACTLY like the canonical uppercase form — the OLD case-sensitive match let it bypass
    machine.py's scenario ceiling entirely (treated as CURRENT_STATE, free to advance past
    SHADOW_EXECUTED like a real decision)."""
    _seed_common(tmp_path)
    an_intent = intent_mod._base_fields(
        now=NOW, pin=_pin(), sleeve_id=intent_mod.CANARY_SLEEVE, strategy_id="scenario_canary:case",
        action_type=contract.ACTION_SUPPLY, network_or_venue="aave_v3", instrument="aave_v3", from_asset="USDC",
        to_asset="USDC", notional=1000.0, notional_unit="USDC", source_recommendation_id=None,
        source_role_id=contract.SOURCE_ROLE_ID, source_book_decision=None,
        risk_snapshot={k: {"state": contract.NOT_MEASURED, "value": None, "as_of": None, "digest": None,
        "reason": "fixture"} for k in ("kill_switch", "derisk", "riskpolicy_verdict", "riskpolicy_version",
        "cio_recommendation_id", "cio_stance", "book_state_digest", "depeg")}, unknowns=[],
        reason="round-3 L5 fixture", scenario="test_scenario:case")  # deliberately lowercase
    assert machine._is_scenario(an_intent) is True
    machine.record_intent(tmp_path, an_intent, NOW)
    machine.advance(tmp_path, an_intent, contract.S_VALIDATED, {}, NOW)
    machine.advance(tmp_path, an_intent, contract.S_SIMULATED, {}, NOW)
    machine.advance(tmp_path, an_intent, contract.S_SHADOW_READY, {}, NOW)
    machine.advance(tmp_path, an_intent, contract.S_SHADOW_EXECUTED, {}, NOW)
    # the ceiling (contract.SCENARIO_MAX_STATE == S_SHADOW_EXECUTED) must refuse the NEXT step too
    # — exactly as it does for the canonical uppercase prefix.
    with pytest.raises(machine.IllegalTransition):
        machine.advance(tmp_path, an_intent, contract.S_RECONCILED, {}, NOW)


def test_l5_is_test_scenario_case_insensitive_shared_helper():
    assert intent_mod.is_test_scenario("test_scenario:x") is True
    assert intent_mod.is_test_scenario("TEST_SCENARIO:x") is True
    assert intent_mod.is_test_scenario("Test_Scenario:x") is True
    assert intent_mod.is_test_scenario(contract.SCENARIO_CURRENT) is False
    assert intent_mod.is_test_scenario(None) is False


# ── round-3 item 7 (M2): run.py's --data-dir default must honour SPA_DATA_DIR ───────────────────

def test_m2_main_honours_spa_data_dir_when_no_data_dir_flag_given(tmp_path, monkeypatch):
    """review round-3 M2: scripts/check_agent_before_deploy.sh sets SPA_DATA_DIR to a sandbox for
    its trial run — with the OLD hard-coded relative default ("data"), a gate trial with no
    explicit --data-dir still wrote into the PRODUCTION data/capital_shadow (measured at a real
    deploy, 08:13). main() with SPA_DATA_DIR set and NO --data-dir must write ONLY under that
    sandbox, never under any "data" relative to CWD."""
    monkeypatch.setenv("SPA_DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # a CWD-relative "data" would also happen to land under tmp_path
    # here by coincidence — prove it did NOT take that path by checking the EXACT sandbox dir.
    rc = run_mod.main(["--now", NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "--no-rpc"])
    assert rc == contract.EXIT_OK
    assert (tmp_path / contract.DATA_SUBDIR / contract.LEDGER).exists()


def test_m2_explicit_data_dir_flag_still_wins_over_spa_data_dir(tmp_path, monkeypatch):
    """review round-3 M2: an explicit --data-dir must still win over SPA_DATA_DIR."""
    sandbox = tmp_path / "spa_data_dir_sandbox"
    explicit = tmp_path / "explicit_data_dir"
    monkeypatch.setenv("SPA_DATA_DIR", str(sandbox))
    rc = run_mod.main(["--data-dir", str(explicit), "--now", NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "--no-rpc"])
    assert rc == contract.EXIT_OK
    assert (explicit / contract.DATA_SUBDIR / contract.LEDGER).exists()
    assert not (sandbox / contract.DATA_SUBDIR / contract.LEDGER).exists()


def test_final_rereview_scenario_intent_ids_is_case_insensitive():
    """Final re-review L5-r: readiness kept its own case-SENSITIVE prefix check, so evidence owned
    by a ``test_scenario:`` (lowercase) intent still counted for a real sleeve."""
    entries = [
        {"seq": 1, "kind": "intent", "payload": {"intent_id": "lo", "scenario": "test_scenario:lower"}},
        {"seq": 2, "kind": "intent", "payload": {"intent_id": "mx", "scenario": "Test_Scenario:mixed"}},
        {"seq": 3, "kind": "intent", "payload": {"intent_id": "cur", "scenario": contract.SCENARIO_CURRENT}},
    ]
    assert readiness._scenario_intent_ids(entries) == {"lo", "mx"}


def test_final_rereview_default_data_dir_is_this_code_trees_own_data(tmp_path, monkeypatch):
    """Final re-review L-new: with SPA_DATA_DIR unset, the default fell back to the LIVE tree, so a
    run from any worktree appended to the production ledger. It must be this code tree's own data/."""
    monkeypatch.delenv("SPA_DATA_DIR", raising=False)
    seen = {}

    class _Stop(BaseException):  # main() turns ordinary exceptions into exit codes
        pass

    def fake_run_cycle(data_dir, now, **kw):  # capture the resolved dir; run nothing
        seen["data_dir"] = Path(data_dir)
        raise _Stop()
    monkeypatch.setattr(run_mod, "run_cycle", fake_run_cycle)
    with pytest.raises(_Stop):
        run_mod.main(["--now", NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "--no-rpc"])
    assert seen["data_dir"] == Path(run_mod.__file__).resolve().parents[2] / "data"
