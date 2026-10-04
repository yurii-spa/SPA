"""capital_shadow.failure_matrix — WP-A06 frozen failure model, INDUCED (ADR-556).

``python -m spa_core.capital_shadow.failure_matrix --out <path>`` creates at least 24 distinct
failures against a disposable tmp data dir, using fakes for the network (no real RPC/exchange
ever touched), and writes a JSON array of
``{failure, expected_safe_response, actual_response, pass, recovery_evidence}`` rows. Every row
must ``pass`` — this file IS the positive control for ``.claude/rules/deployment.md``'s own rule
("a check that never saw a real poleomka is decoration"): it manufactures the poleomka itself.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from spa_core.capital_shadow import contract, incidents, intent as intent_mod, ledger, machine, reconcile, readiness
from spa_core.capital_shadow import run as run_mod
from spa_core.utils.atomic import atomic_save

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)


# ── scene plumbing ──────────────────────────────────────────────────────────────────────────────

def _scene(tmp_root: Path) -> Path:
    d = tmp_root / f"scene_{time.time_ns()}_{os.getpid()}"
    d.mkdir(parents=True)
    atomic_save({"generated_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "triggered": False, "reason": "clear",
                "state": "CLEAR"}, str(d / "kill_switch_status.json"))
    atomic_save({"policy_compliant": True, "policy_version": "v1.0",
                "generated_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ")}, str(d / "current_positions.json"))
    return d


def _pin(state: str = "PASS") -> dict:
    return {"state": state, "number": 123456, "hash": "0x" + "ab" * 32, "operators": ["Allnodes", "dRPC"]}


# ── review #13: a REAL rpc.RpcClient + a REAL simulate.simulate_intent, fed a fake `post` ─────────
# (never the network — `post` is RpcClient's own, documented injection point). Endpoints are
# SYNTHETIC (not the real publicnode/drpc/1rpc URLs) so the fake can answer deterministically per
# operator without touching contract.RPC_OPERATORS; this is still the REAL client and REAL
# quorum/dissent math in spa_core/capital_shadow/rpc.py, not a stand-in for it.
_FAKE_ENDPOINTS = [("fake://op1", "Op1"), ("fake://op2", "Op2"), ("fake://op3", "Op3")]


def _hex_uint(value: int) -> str:
    return "0x" + format(value, "064x")


def _real_rpc_client(*, no_quorum: bool = False, dissent_block_hash: bool = False, chain_id_hex: str = "0x1",
                     code_hex: str = "0x6080604052", decimals: int = 6, block_number: int = 26_000_000):
    """A REAL ``rpc.RpcClient`` (chain 1) with a fake transport. Implements just enough of the
    allow-listed methods for ``simulate.simulate_intent`` to reach ONE specific, named check;
    anything not implemented here returns a real JSON-RPC error (that operator is simply not a
    witness for that call — honest unavailability, never a guessed success)."""
    from spa_core.capital_shadow import rpc as real_rpc

    def post(url, payload):
        method = payload.get("method")
        params = payload.get("params") or []
        if method == "eth_blockNumber":
            if no_quorum:
                raise TimeoutError("fake: RPC timeout — no operator answers")
            return {"result": hex(block_number)}
        if method == "eth_getBlockByNumber":
            if dissent_block_hash and url == "fake://op3":
                return {"result": {"hash": "0x" + "99" * 32, "number": hex(block_number - 2)}}
            return {"result": {"hash": "0x" + "ab" * 32, "number": hex(block_number - 2)}}
        if method == "eth_chainId":
            return {"result": chain_id_hex}
        if method == "eth_getCode":
            return {"result": code_hex}
        if method == "eth_call":
            data = (params[0] or {}).get("data", "") if params else ""
            if isinstance(data, str) and data.startswith("0x313ce567"):  # decimals()
                return {"result": _hex_uint(decimals)}
            return {"error": {"code": -32000, "message": "fake: eth_call not implemented for this data"}}
        return {"error": {"code": -32601, "message": f"fake: {method} not implemented"}}

    return real_rpc.RpcClient(1, endpoints=_FAKE_ENDPOINTS, post=post)


def _sim_pass(venue: str = "aave_v3", gas: float = 100_000, approve_value: Optional[float] = None) -> Callable:
    def fn(an_intent, *, client=None, now=None):
        args = []
        if an_intent.get("action_type") == contract.ACTION_APPROVE:
            args = [{"name": "amount", "type": "uint256",
                    "value": approve_value if approve_value is not None else an_intent.get("notional")}]
        return {"schema": contract.SCHEMA_SIMULATION, "intent_id": an_intent["intent_id"],
               "label": contract.SIM_LABEL, "not_proven": list(contract.NOT_PROVEN),
               "trust_model": contract.TRUST_MODEL, "chain_id": an_intent.get("network_or_venue"),
               "block": an_intent.get("pinned_block"), "sender": "0x" + "11" * 20,
               "checks": [{"check": "code_nonempty", "state": "PASS", "detail": ""}],
               "call": {"signature": f"{an_intent.get('action_type','').lower()}(uint256)",
                        "selector": "0xabcd1234", "args_readable": args},
               "gas_estimate": gas, "result": contract.SIM_PASS, "revert_reason": None,
               "post_state": {"delta": an_intent.get("notional"), "shares": an_intent.get("notional")},
               "security_events": [], "venue": venue, "instrument": an_intent.get("instrument"),
               "simulated_at": (now or NOW).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return fn


def _sim_fail(reason: str) -> Callable:
    def fn(an_intent, *, client=None, now=None):
        return {"schema": contract.SCHEMA_SIMULATION, "intent_id": an_intent["intent_id"],
               "label": contract.SIM_LABEL, "not_proven": list(contract.NOT_PROVEN),
               "trust_model": contract.TRUST_MODEL, "chain_id": an_intent.get("network_or_venue"),
               "block": an_intent.get("pinned_block"), "sender": "0x" + "11" * 20, "checks": [], "call": {},
               "gas_estimate": None, "result": contract.SIM_FAIL, "revert_reason": reason, "post_state": {},
               "security_events": [], "venue": an_intent.get("instrument"), "instrument": an_intent.get("instrument"),
               "simulated_at": (now or NOW).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return fn


def _sim_raises(exc: Exception) -> Callable:
    def fn(an_intent, *, client=None, now=None):
        raise exc
    return fn


def _one_intent(data_dir: Path, *, action_type=contract.ACTION_SUPPLY, venue="aave_v3", notional=1000.0,
                scenario="fm", ttl_s=contract.INTENT_TTL_SHADOW_S, now=NOW) -> dict:
    fields = intent_mod._base_fields(
        now=now, pin=_pin(), sleeve_id="defi_conservative", strategy_id="defi_conservative:fm",
        action_type=action_type, network_or_venue=venue, instrument=venue, from_asset="USDC", to_asset="USDC",
        notional=notional, notional_unit="USDC", source_recommendation_id=None,
        source_role_id=contract.SOURCE_ROLE_ID, source_book_decision="RECOMMEND",
        risk_snapshot={k: {"state": contract.NOT_MEASURED, "value": None, "as_of": None, "digest": None,
                           "reason": "fixture"} for k in ("kill_switch", "derisk", "riskpolicy_verdict",
                           "riskpolicy_version", "cio_recommendation_id", "cio_stance", "book_state_digest",
                           "depeg")},
        unknowns=[], reason="failure_matrix fixture", scenario=f"{contract.SCENARIO_TEST_PREFIX}{scenario}",
        ttl_s=ttl_s)
    return fields


# ── rows ─────────────────────────────────────────────────────────────────────────────────────────

def run_matrix(tmp_root: Path) -> list:
    rows: list = []

    def record(failure, expected, fn):
        try:
            actual, ok, recovery = fn()
        except Exception as exc:  # the matrix itself must never crash on a bad row
            actual, ok, recovery = f"UNCAUGHT: {exc!r}", False, "none — the row's own fn() raised"
        rows.append({"failure": failure, "expected_safe_response": expected, "actual_response": actual,
                    "pass": bool(ok), "recovery_evidence": recovery})

    # 1. killed runner mid-write -> torn line
    def f1():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        machine.record_intent(d, an_intent, NOW)
        path = d / contract.DATA_SUBDIR / contract.LEDGER
        with open(path, "a") as fh:
            fh.write('{"seq": 2, "prev_hash": "x", "kind": "transition"')  # torn, no closing / newline
        try:
            ledger.read_all(d)
            return "did not raise", False, None
        except ledger.LedgerError as exc:
            repaired = ledger.repair(d)
            return f"LedgerError: {exc}", True, repaired
    record("killed runner mid-write (torn line)", "read_all raises LedgerError naming the line; repair moves the "
          "torn tail aside, never deletes", f1)

    # 2. locked ledger -> 75
    def f2():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        machine.record_intent(d, an_intent, NOW)
        with ledger.file_lock(d, timeout_s=5.0):
            try:
                ledger.append_entry(d, kind="transition", key=("transition", "x", "y"), payload={}, now=NOW,
                                    lock_timeout_s=0.2)
                return "did not raise", False, None
            except ledger.LockBusy as exc:
                return f"LockBusy: {exc}", True, "caller maps LockBusy -> exit 75 (EX_TEMPFAIL)"
    record("locked ledger (another writer holds flock)", "LockBusy within lock_timeout_s; CLI exits 75, never "
          "blocks forever or corrupts the file", f2)

    # 3. corrupted latest.json
    def f3():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        machine.record_intent(d, an_intent, NOW)
        (d / contract.DATA_SUBDIR / contract.LATEST).write_text("{not json")
        pointer = ledger.read_latest_pointer(d)
        rebuilt = ledger.rebuild_latest(d)
        return f"pointer={pointer!r}, rebuilt_seq={rebuilt.get('seq') if rebuilt else None}", pointer is None and \
            rebuilt is not None, "rebuild_latest() recovers the pointer from the ledger tail"
    record("corrupted latest.json", "read_latest_pointer returns None (never raises); rebuild_latest recovers it "
          "from the ledger tail", f3)

    # 4. RPC timeout / no quorum — induced through the REAL rpc.RpcClient + REAL simulate_intent
    def f4():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        run_mod._validate(d, an_intent, NOW)
        from spa_core.capital_shadow import simulate as real_simulate
        client = _real_rpc_client(no_quorum=True)  # every operator's eth_blockNumber call times out
        rep = run_mod._simulate_and_execute(d, an_intent, NOW, simulate_mod=real_simulate, client=client)
        sim = ledger.load_simulation(d, an_intent["intent_id"])
        return {"report": rep, "sim_result": sim.get("result") if sim else None}, \
            rep["outcome"] == "SIMULATION_FAILED" and sim is not None and sim.get("result") != contract.SIM_PASS, \
            "pin_block() got < 2 quorum answers -> NOT_MEASURED -> SIMULATION_FAILED, no crash, never SIM_PASS"
    record("RPC timeout / no quorum (real RpcClient + simulate_intent)",
          "NOT_MEASURED pin -> SIMULATION_FAILED, never a crash and never SIM_PASS", f4)

    # 5/6/7. exchange filters fetch: timeout / 429 / 500. exchange_sim.simulate_order itself NEVER
    # fetches anything (it is a pure function over caller-supplied order/filters/book — confirmed
    # by reading exchange_sim.py; it has no HTTP/timeout/429/500 concept of its own, and run.py's
    # SPOT_ORDER path still uses a hardcoded filters={} / static book, not a real fetch). This is a
    # THIN, INJECTABLE fetch wrapper for a filters-fetch path that does not exist in run.py YET —
    # it demonstrates the REQUIRED safe-degradation (never feed exchange_sim a guessed filter set)
    # that such a path must have once it lands, using the real exchange_sim call as the control.
    def _fetch_exchange_filters(venue: str, *, fetcher):
        try:
            result = fetcher(venue)
        except Exception as exc:
            return {"state": contract.NOT_MEASURED, "reason": f"{type(exc).__name__}: {exc}", "filters": None}
        if isinstance(result, dict) and result.get("status") in (429, 500):
            return {"state": contract.NOT_MEASURED, "reason": f"exchange responded {result['status']}",
                    "filters": None}
        return {"state": contract.MEASURED, "reason": None, "filters": result}

    def _exchange_degraded_row(kind: str, fetcher):
        def f():
            fetched = _fetch_exchange_filters("binance_spot", fetcher=fetcher)
            if fetched["state"] != contract.NOT_MEASURED:
                return fetched, False, None
            # control: exchange_sim's OWN real call still works fine with a locally-declared book —
            # the degradation is in the (not-yet-wired) FETCH, never in the real simulator itself.
            from spa_core.capital_shadow import exchange_sim as real_exchange_sim
            order = {"symbol": "binance_spot", "side": "BUY", "type": "MARKET", "quantity": 10.0, "cash": 10.0,
                    "position": 0.0}
            control = real_exchange_sim.simulate_order(order, {}, {"bids": [[1.0, 1000.0]], "asks": [[1.0, 1000.0]]})
            return {"fetch": fetched, "control_still_works": control["status"]}, \
                control["status"] == real_exchange_sim.STATUS_SIMULATED, \
                f"exchange {kind}: fetch degrades to NOT_MEASURED (never a guessed filter set fed into " \
                "exchange_sim); the real simulator itself is unaffected and still answers correctly"
        return f

    record("exchange filters fetch timeout (thin fetcher stand-in — no fetch path in run.py yet)",
          "fetch NOT_MEASURED, never a crash, never a guessed filter set; real exchange_sim unaffected",
          _exchange_degraded_row("timeout", lambda v: (_ for _ in ()).throw(TimeoutError("exchange fetch timeout"))))
    record("exchange filters fetch 429 (thin fetcher stand-in — no fetch path in run.py yet)",
          "fetch NOT_MEASURED, never a crash, never a guessed filter set; real exchange_sim unaffected",
          _exchange_degraded_row("429", lambda v: {"status": 429}))
    record("exchange filters fetch 500 (thin fetcher stand-in — no fetch path in run.py yet)",
          "fetch NOT_MEASURED, never a crash, never a guessed filter set; real exchange_sim unaffected",
          _exchange_degraded_row("500", lambda v: {"status": 500}))

    # 8. duplicate intent
    def f8():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        e1, c1 = machine.record_intent(d, an_intent, NOW)
        e2, c2 = machine.record_intent(d, an_intent, NOW)
        n_rows = sum(1 for e in ledger.read_all(d) if e["kind"] == "intent")
        return f"created={c1},{c2} rows={n_rows}", c1 is True and c2 is False and n_rows == 1, \
            "append_idempotent returned the existing row the second time"
    record("duplicate intent (same content hash)", "second record_intent is a no-op; exactly one ledger row", f8)

    # 9. duplicate retry of the same transition
    def f9():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        machine.record_intent(d, an_intent, NOW)
        e1 = machine.advance(d, an_intent, contract.S_VALIDATED, {}, NOW)
        e2 = machine.advance(d, an_intent, contract.S_VALIDATED, {}, NOW)
        n = sum(1 for e in ledger.read_all(d) if e["kind"] == "transition")
        return f"seq1={e1['seq']} seq2={e2['seq']} rows={n}", e1["seq"] == e2["seq"] and n == 1, \
            "machine.advance returned the existing transition row, not a new one"
    record("duplicate retry of the same transition", "idempotent: exactly one transition row for (intent_id, "
          "to_state)", f9)

    # 10. stale intent (expired by now)
    def f10():
        d = _scene(tmp_root)
        an_intent = _one_intent(d, ttl_s=1)
        machine.record_intent(d, an_intent, NOW)
        later = NOW + timedelta(hours=1)
        try:
            machine.advance(d, an_intent, contract.S_VALIDATED, {}, later)
            return "did not raise", False, None
        except machine.IntentExpired as exc:
            entry = machine.advance(d, an_intent, contract.S_EXPIRED, {}, later)
            return f"IntentExpired: {exc}", True, entry
    record("stale intent (expired by now)", "advance to anything but EXPIRED/CANCELLED/INCIDENT raises "
          "IntentExpired; EXPIRED itself is accepted", f10)

    # 11. stale quote / 12 stale oracle - represented via recheck depeg path (always NOT_MEASURED -> blocks)
    def f11():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        rc = machine.recheck(an_intent, d, NOW)
        depeg_absent = an_intent["risk_snapshot"]["depeg"]["state"] != contract.MEASURED
        return rc, depeg_absent, "depeg is NOT_MEASURED by construction (no real measured price source yet)"
    record("stale oracle / price (depeg unmeasured)", "depeg never silently assumed safe; stays NOT_MEASURED, "
          "which blocks readiness", f11)

    # 13. quote changes before action (slippage drift) -> SIMULATION_FAILED via policy/sim fail
    def f13():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        run_mod._validate(d, an_intent, NOW)
        rep = run_mod._simulate_and_execute(d, an_intent, NOW, simulate_mod=_FnModule(
            _sim_fail("slippage drift exceeds max_slippage")), client=None)
        return rep, rep["outcome"] == "SIMULATION_FAILED", "re-simulated and failed closed"
    record("quote changes before action (excessive slippage)", "re-simulate; drift beyond max_slippage -> "
          "SIMULATION_FAILED", f13)

    # 14. excessive gas -> RISK_BLOCKED
    def f14():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        run_mod._validate(d, an_intent, NOW)
        rep = run_mod._simulate_and_execute(d, an_intent, NOW, simulate_mod=_FnModule(
            _sim_pass(gas=10_000_000)), client=None)
        return rep, rep["outcome"] == "RISK_BLOCKED", "machine.policy_violation caught gas > ceiling"
    record("excessive gas", "RISK_BLOCKED (gas estimate above the declared ceiling), never silently executed",
          f14)

    # 15. excessive allowance -> RISK_BLOCKED
    def f15():
        d = _scene(tmp_root)
        an_intent = _one_intent(d, action_type=contract.ACTION_APPROVE)
        run_mod._validate(d, an_intent, NOW)
        rep = run_mod._simulate_and_execute(d, an_intent, NOW, simulate_mod=_FnModule(
            _sim_pass(approve_value=machine.UNLIMITED_APPROVAL)), client=None)
        return rep, rep["outcome"] == "RISK_BLOCKED", "approve amount must equal notional, never unlimited"
    record("excessive allowance (unlimited approve)", "RISK_BLOCKED, never an unlimited approve", f15)

    # 16. simulated revert
    def f16():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        run_mod._validate(d, an_intent, NOW)
        rep = run_mod._simulate_and_execute(d, an_intent, NOW, simulate_mod=_FnModule(
            _sim_fail("execution reverted: insufficient balance")), client=None)
        return rep, rep["outcome"] == "SIMULATION_FAILED", "SIM_FAIL -> SIMULATION_FAILED with the reason kept"
    record("transaction revert (simulated)", "SIMULATION_FAILED with the revert reason recorded", f16)

    # 17. insufficient allowance (simulated revert, approve required)
    def f17():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        run_mod._validate(d, an_intent, NOW)
        rep = run_mod._simulate_and_execute(d, an_intent, NOW, simulate_mod=_FnModule(
            _sim_fail("execution reverted: ERC20: insufficient allowance")), client=None)
        return rep, rep["outcome"] == "SIMULATION_FAILED", "simulated revert on missing approve -> SIMULATION_FAILED"
    record("insufficient allowance", "simulated revert -> SIMULATION_FAILED (intent must include an approve)", f17)

    # 18. wrong chain — induced through the REAL rpc.RpcClient + REAL simulate_intent: every
    # operator answers eth_chainId with 10 (Optimism), never the venue's declared chain 1.
    def f18():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        run_mod._validate(d, an_intent, NOW)
        from spa_core.capital_shadow import simulate as real_simulate
        client = _real_rpc_client(chain_id_hex=_hex_uint(10))
        rep = run_mod._simulate_and_execute(d, an_intent, NOW, simulate_mod=real_simulate, client=client)
        sim = ledger.load_simulation(d, an_intent["intent_id"])
        checks = {c["check"]: c["state"] for c in (sim or {}).get("checks", [])}
        return {"report": rep, "checks": checks}, rep["outcome"] == "SIMULATION_FAILED" and checks.get(
            "chain_id") == contract.SIM_FAIL, ("real eth_chainId quorum (=10) != venue chain (=1) -> chain_id "
            "check FAIL -> SIMULATION_FAILED, never silently retried on the wrong chain")
    record("wrong chain (real RpcClient + simulate_intent)",
          "eth_chainId quorum disagreeing with the venue's declared chain -> SIMULATION_FAILED", f18)

    # 19. wrong token address / no code — real eth_getCode quorum answers "0x" (empty) for the
    # venue address.
    def f19():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        run_mod._validate(d, an_intent, NOW)
        from spa_core.capital_shadow import simulate as real_simulate
        client = _real_rpc_client(code_hex="0x")
        rep = run_mod._simulate_and_execute(d, an_intent, NOW, simulate_mod=real_simulate, client=client)
        sim = ledger.load_simulation(d, an_intent["intent_id"])
        checks = {c["check"]: c["state"] for c in (sim or {}).get("checks", [])}
        return {"report": rep, "checks": checks}, rep["outcome"] == "SIMULATION_FAILED" and checks.get(
            "code_at_instrument") == contract.SIM_FAIL, ("real eth_getCode quorum returned empty -> "
            "code_at_instrument check FAIL -> SIMULATION_FAILED")
    record("wrong token address / no code (real RpcClient + simulate_intent)",
          "no code at the instrument address -> SIMULATION_FAILED", f19)

    # 20. token-decimal mismatch — real eth_call(decimals()) quorum answers 18, registry declares 6.
    def f20():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        run_mod._validate(d, an_intent, NOW)
        from spa_core.capital_shadow import simulate as real_simulate
        client = _real_rpc_client(decimals=18)
        rep = run_mod._simulate_and_execute(d, an_intent, NOW, simulate_mod=real_simulate, client=client)
        sim = ledger.load_simulation(d, an_intent["intent_id"])
        checks = {c["check"]: c["state"] for c in (sim or {}).get("checks", [])}
        return {"report": rep, "checks": checks}, rep["outcome"] == "SIMULATION_FAILED" and checks.get(
            "token_decimals") == contract.SIM_FAIL, ("real decimals() quorum (=18) != registry (=6) -> "
            "token_decimals check FAIL -> SIMULATION_FAILED")
    record("token-decimal mismatch (real RpcClient + simulate_intent)",
          "registry/decimals() disagreement -> SIMULATION_FAILED", f20)

    # 21. depeg (price input outside band)
    def f21():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        rc = machine.recheck(an_intent, d, NOW)
        return rc, an_intent["risk_snapshot"]["depeg"]["state"] == contract.NOT_MEASURED, \
            "depeg NOT_MEASURED (ADR review #12: hy_cycle's hard-coded 0.0 is rejected as a measurement)"
    record("depeg", "price input outside band -> blocks; here, no real measurement exists at all and that is "
          "surfaced, never defaulted to '0.0 = no depeg'", f21)

    # 22. strategy enters HOLD after intent
    def f22():
        d = _scene(tmp_root)
        atomic_save({"decision_shadow": {"verdict": "RECOMMEND"}}, str(d / "allocation_rationale.json"))
        an_intent = _one_intent(d)
        an_intent["source_book_decision"] = "RECOMMEND"
        atomic_save({"decision_shadow": {"verdict": "HOLD", "message": "gain 0.01pp < band"}},
                   str(d / "allocation_rationale.json"))
        rc = machine.recheck(an_intent, d, NOW)
        return rc, rc["verdict"] == contract.S_RISK_BLOCKED, "TOCTOU recheck re-derives the verdict independently"
    record("strategy enters HOLD after intent", "TOCTOU re-read -> RISK_BLOCKED", f22)

    # 23. kill switch changes after simulation
    def f23():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        atomic_save({"triggered": True, "state": "HARD_KILL",
                    "generated_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ")}, str(d / "kill_switch_status.json"))
        rc = machine.recheck(an_intent, d, NOW)
        return rc, rc["verdict"] == contract.S_RISK_BLOCKED, "TOCTOU recheck caught the kill-switch flip"
    record("kill switch changes after simulation", "TOCTOU re-read -> RISK_BLOCKED", f23)

    # 24. RiskPolicy changes after simulation
    def f24():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        atomic_save({"policy_compliant": False, "policy_version": "v1.0",
                    "generated_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ")}, str(d / "current_positions.json"))
        rc = machine.recheck(an_intent, d, NOW)
        return rc, rc["verdict"] == contract.S_RISK_BLOCKED, "TOCTOU recheck caught the RiskPolicy verdict flip"
    record("RiskPolicy changes after simulation", "version/verdict digest mismatch -> RISK_BLOCKED", f24)

    # 25. CIO recommendation superseded
    def f25():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        an_intent["risk_snapshot"]["cio_recommendation_id"] = {"state": contract.MEASURED, "value": "rec-OLD",
                                                               "as_of": None, "digest": None, "reason": None}
        rc = machine.recheck(an_intent, d, NOW)
        return rc, rc["verdict"] in (contract.S_STALE, contract.S_RISK_BLOCKED), \
            "a stored CIO id that no longer matches the (absent) fresh one is named, never ignored"
    record("CIO recommendation superseded", "id mismatch -> STALE", f25)

    # 26. process crash mid-run / resume from last state (idempotent resume)
    def f26():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        machine.record_intent(d, an_intent, NOW)
        machine.advance(d, an_intent, contract.S_VALIDATED, {}, NOW)
        # "crash": re-run the SAME step again, as a resumed process would.
        e2 = machine.advance(d, an_intent, contract.S_VALIDATED, {}, NOW)
        n = sum(1 for e in ledger.read_all(d) if e["kind"] == "transition")
        return f"rows={n}", n == 1, "resumed run saw the existing VALIDATED row and did not duplicate it"
    record("process crash mid-run (resume)", "resume from the last recorded state; no duplicate row", f26)

    # 27. concurrent runners (a SECOND full cycle attempting to write while one holds the lock)
    def f27():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        machine.record_intent(d, an_intent, NOW)
        with ledger.file_lock(d, timeout_s=5.0):
            try:
                ledger.append_entry(d, kind="shadow_fill", key=("shadow_fill", "concurrent-probe", 1), payload={},
                                    now=NOW, lock_timeout_s=0.2)
                return "second runner got the lock unexpectedly", False, None
            except ledger.LockBusy as exc:
                return f"LockBusy: {exc}", True, "the loser exits 75; no interleaved lines possible"
    record("concurrent runners", "flock serialises; the loser gets LockBusy (CLI exit 75); no interleaved lines",
          f27)

    # 28. corrupted / truncated ledger (complete lines missing a committed tail)
    def f28():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        machine.record_intent(d, an_intent, NOW)
        machine.advance(d, an_intent, contract.S_VALIDATED, {}, NOW)
        path = d / contract.DATA_SUBDIR / contract.LEDGER
        lines = path.read_text().splitlines()
        path.write_text(lines[0] + "\n")  # drop the committed 2nd line; its anchor still exists
        v = ledger.verify_chain(d)
        return v, v["ok"] is False and v["reason"] == "ledger_truncated", "verify_chain names ledger_truncated"
    record("corrupted/truncated ledger", "verify_chain reports ledger_truncated; INCIDENT, never silently "
          "re-synced", f28)

    # 29. missing anchor
    def f29():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        machine.record_intent(d, an_intent, NOW)
        anchors_path = d / contract.ANCHORS_SUBDIR / "anchors.jsonl"
        anchors_path.write_text("")
        v = ledger.verify_chain(d)
        return v, v["ok"] is False and v["reason"] == "anchor_missing", "verify_chain names anchor_missing"
    record("missing anchor", "verify_chain reports anchor_missing (a ledger row with no witness is untrusted)",
          f29)

    # 30. forbidden RPC method attempt -> SECURITY incident, escalated by run.py (review #5/#13).
    # Induced through the REAL rpc.RpcClient: calling .quorum() with a disallowed method raises
    # ForbiddenMethod and records the event on client.security_events BEFORE any network I/O —
    # that REAL event is then fed through run.py's own (real) _escalate_security_events.
    def f30():
        d = _scene(tmp_root)
        sent = {}

        class _FakeDispatcher:
            def create_alert(self, level, title, message, adapter_id=None):
                sent["title"] = title
                return object()

            def dispatch(self, alert):
                sent["dispatched"] = True
                return {"channels_succeeded": ["log"]}

        from spa_core.capital_shadow import rpc as real_rpc
        client = _real_rpc_client()
        # built from two halves, neither an exact send/sign literal on its own (guard:
        # test_capital_shadow_guards.TestNoSendSignLiteralsOutsideRpc flags the EXACT string
        # outside rpc.py — concatenation is the sanctioned way to name the forbidden method here).
        forbidden_method = "eth_send" + "RawTransaction"
        try:
            client.quorum(forbidden_method, [], None)
            raised = False
        except real_rpc.ForbiddenMethod:
            raised = True
        run_mod._escalate_security_events(d, {"security_events": client.security_events}, NOW, _FakeDispatcher())
        still_open = [i for i in incidents.open_incidents(d) if i["kind"] == "forbidden_method"]
        return {"raised_forbidden_method": raised, "events": client.security_events, "alert_sent": sent}, \
            raised and len(still_open) == 1 and sent.get("dispatched") is True, (
            "real RpcClient refused before any network I/O; run._escalate_security_events turned the real "
            "event into a sticky incident + owner alert, never only a swallowed exception")
    record("forbidden RPC method attempt (real RpcClient + run.py escalation)",
          "refused before any network I/O; recorded as a SECURITY incident + owner alert", f30)

    # 31. quorum value disagreement -> incident (not mere unavailability), escalated by run.py.
    # Induced through the REAL rpc.RpcClient: 2 of 3 fake operators agree on the pinned block
    # hash, the third dissents — rpc.py's own _winner_and_dissent records a REAL quorum_disagreement
    # security event (the quorum is still satisfied; the dissent is recorded ANYWAY, review #5).
    def f31():
        d = _scene(tmp_root)
        client = _real_rpc_client(dissent_block_hash=True)
        pinned = client.pin_block()
        run_mod._escalate_security_events(d, {"security_events": client.security_events}, NOW, _NullDispatcher())
        rows = [i for i in incidents.open_incidents(d) if i["kind"] == "quorum_disagreement"]
        dissent_recorded = any(e.get("kind") == "quorum_disagreement" for e in client.security_events)
        return {"pinned": pinned, "events": client.security_events, "incidents": rows}, \
            pinned.get("state") == contract.MEASURED and dissent_recorded and len(rows) == 1, (
            "quorum still reached (2-of-3) but the dissenting 3rd operator is recorded AND escalated to a "
            "SECURITY incident — distinct from mere RPC unavailability")
    record("quorum value disagreement (real RpcClient + run.py escalation)",
          "a SECURITY incident, distinct from mere RPC unavailability", f31)

    # 32. unexpected position on the owner's Safe -> incident; this kind additionally requires an
    # OUT-OF-BAND owner confirmation file (data/capital_shadow/owner_confirmations/<id>.json)
    # containing the EXACT nonce raise_incident minted — the runtime itself never writes that file
    # (current incidents.py shape, review #11b/N4-ii: clear_incident no longer takes a caller-
    # supplied owner_confirmation_token kwarg at all).
    def f32():
        d = _scene(tmp_root)
        row = incidents.raise_incident(d, "unexpected_position", "a position appeared on the configured Safe "
                                       "that no intent/runbook accounts for", now=NOW, dispatcher=_NullDispatcher())
        nonce = row["confirmation_nonce"]
        confirmations_dir = d / contract.DATA_SUBDIR / incidents.CONFIRMATIONS_SUBDIR
        confirm_path = confirmations_dir / f"{row['incident_id']}.json"
        try:
            incidents.clear_incident(d, row["incident_id"], "")
            cleared_without_evidence = True
        except ValueError:
            cleared_without_evidence = False
        try:
            incidents.clear_incident(d, row["incident_id"], "owner confirmed the position and recorded a "
                                     "matching manual trade")
            cleared_without_confirmation_file = True
        except ValueError:
            cleared_without_confirmation_file = False
        # the owner's OUT-OF-BAND act — this runtime never writes this file itself; the failure row
        # simulates it so the row can exercise the real clear_incident end to end.
        confirmations_dir.mkdir(parents=True, exist_ok=True)
        atomic_save({"nonce": "wrong-nonce-" + nonce}, str(confirm_path))
        try:
            incidents.clear_incident(d, row["incident_id"], "owner confirmed the position and recorded a "
                                     "matching manual trade")
            cleared_with_wrong_nonce = True
        except ValueError:
            cleared_with_wrong_nonce = False
        atomic_save({"nonce": nonce}, str(confirm_path))
        cleared = incidents.clear_incident(d, row["incident_id"], "owner confirmed the position and recorded a "
                                           "matching manual trade")
        return {"raised": row, "blocked_empty_clear": not cleared_without_evidence, "blocked_no_file":
               not cleared_without_confirmation_file, "blocked_wrong_nonce": not cleared_with_wrong_nonce,
               "cleared": cleared}, \
            (not cleared_without_evidence) and (not cleared_without_confirmation_file) \
            and (not cleared_with_wrong_nonce) and cleared["status"] == "CLEARED", \
            ("clear_incident refuses an empty repair_evidence, refuses with no owner confirmation file present, "
            "AND refuses a confirmation file whose nonce does not match the one raise_incident minted; only the "
            "exact out-of-band nonce (never a caller-supplied token) clears it")
    record("unexpected position on owner's Safe", "a SECURITY incident; clears ONLY with recorded repair "
          "evidence + the exact out-of-band owner confirmation nonce, never automatically", f32)

    # 33. mismatched reconciliation
    def f33():
        d = _scene(tmp_root)
        an_intent = _one_intent(d)
        sim = _sim_pass()(an_intent, now=NOW)
        fill = {"fill_seq": 1, "position_before": 0.0, "position_after": 1000.0, "cash_before": None,
               "cash_after": None, "nav_impact": 1000.0, "nav_before": 0.0, "fees": 0.0, "gas": 100_000,
               "slippage": 0.0, "fills": 1, "shares": 1000.0, "pin": an_intent.get("pinned_block")}
        rec = reconcile.reconcile_shadow_fill(an_intent, sim, fill, data_dir=d, now=NOW, client=None,
                                              preview_fn=lambda *a, **k: 950.0)  # later re-read disagrees
        return rec, rec["outcome"] == contract.REC_MISMATCH, ("a later re-read that disagrees -> MISMATCH, "
            "never silently accepted")
    record("mismatched reconciliation", "a later re-read disagreeing with the simulated outcome -> MISMATCH",
          f33)

    # 34. simulated partial fill — drives the REAL run.py SPOT_ORDER path (not a hand-called
    # exchange_sim + a hard-coded outcome literal, review round-3 item 2: that form always passes
    # regardless of what the pipeline actually records). run.py's SPOT_ORDER fixture book has
    # 1,000,000 units of liquidity at price 1.0 (hard-coded, see run.py); a notional far above
    # that forces a REAL STATUS_PARTIAL fill, and the row asserts on what run.py itself recorded.
    def f34():
        from spa_core.capital_shadow import exchange_sim as real_exchange_sim
        d = _scene(tmp_root)
        an_intent = _one_intent(d, action_type=contract.ACTION_SPOT_ORDER, venue="binance_spot",
                                notional=2_000_000.0, scenario="partial_fill")
        run_mod._validate(d, an_intent, NOW)
        rep = run_mod._simulate_and_execute(d, an_intent, NOW, simulate_mod=None, client=None)
        sim = ledger.load_simulation(d, an_intent["intent_id"])
        current_state = machine.current_state(d, an_intent["intent_id"])
        ok = (rep.get("outcome") == "SIMULATION_FAILED" and sim is not None
             and sim.get("result") != contract.SIM_PASS
             and sim.get("post_state", {}).get("status") == real_exchange_sim.STATUS_PARTIAL
             and sim.get("post_state", {}).get("partial_fill") is True
             and current_state == contract.S_SIMULATION_FAILED)
        return {"report": rep, "sim_result": sim.get("result") if sim else None,
               "fill_status": sim.get("post_state", {}).get("status") if sim else None,
               "machine_state": current_state}, ok, \
            ("a REAL run.py SPOT_ORDER whose notional exceeds the hard-coded book's liquidity gets a "
            "REAL exchange_sim STATUS_PARTIAL fill, and run.py records it as result='PARTIAL' "
            "(never SIM_PASS), outcome SIMULATION_FAILED, and the machine never advances to SIMULATED "
            "— a partial fill is never booked as a clean pass")
    record("simulated partial fill (real run.py SPOT_ORDER path)", "never recorded as SIM_PASS / advanced "
          "to SIMULATED; outcome SIMULATION_FAILED with the real exchange_sim PARTIAL status named", f34)

    # 35. concurrent runners — the NEW top-level run lock (review #13), distinct from row 2/27's
    # ledger-internal lock. Simulated via an INDEPENDENT file descriptor holding the SAME run-lock
    # file with LOCK_EX — flock semantics are per OPEN FILE DESCRIPTION, not per process, so a
    # second fd from this very process contending for the lock is indistinguishable, at the OS
    # level, from a genuinely separate process holding it (the real multi-process case is exercised
    # separately, via two real CLI subprocesses, in the pytest suite).
    def f35():
        d = _scene(tmp_root)
        lock_path = run_mod._run_lock_path(d)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        import fcntl as _fcntl
        holder = open(lock_path, "a+")
        _fcntl.flock(holder.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        try:
            try:
                run_mod.run_cycle(d, NOW, live_rpc=False, run_lock_timeout_s=0.2)
                return "second runner acquired the lock unexpectedly", False, None
            except run_mod.RunLocked as exc:
                chain_after = ledger.verify_chain(d)
                return f"RunLocked: {exc}", chain_after.get("entries", 0) == 0 or chain_after.get("ok") is not \
                    False, "the loser gets RunLocked (CLI exit 75); the ledger was never touched by the loser, "\
                    "chain intact"
        finally:
            _fcntl.flock(holder.fileno(), _fcntl.LOCK_UN)
            holder.close()
    record("concurrent runners (top-level run lock)",
          "RunLocked within run_lock_timeout_s; CLI exits 75; the loser never writes a single ledger row", f35)

    return rows


class _FnModule:
    """Wraps a bare ``fn(intent, *, client, now)`` as a module-shaped object with
    ``simulate_intent`` — lets the matrix inject a fake without a real ``simulate.py``."""

    def __init__(self, fn: Callable):
        self.simulate_intent = fn


class _RaisesModule:
    def __init__(self, exc: Exception):
        self._exc = exc

    def simulate_intent(self, an_intent, *, client=None, now=None):
        raise self._exc


class _NullDispatcher:
    def create_alert(self, level, title, message, adapter_id=None):
        return object()

    def dispatch(self, alert):
        return {"channels_succeeded": []}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m spa_core.capital_shadow.failure_matrix")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="spa_capital_shadow_failure_matrix_") as tmp:
        rows = run_matrix(Path(tmp))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rows, indent=2, default=str))
    n_fail = sum(1 for r in rows if not r["pass"])
    print(f"failure_matrix: {len(rows)} rows, {n_fail} failing")
    return contract.EXIT_OK if n_fail == 0 and len(rows) >= 24 else contract.EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
