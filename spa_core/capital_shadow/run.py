"""capital_shadow.run — the WRITER (ADR-556 binding review #10: writer != certifier).

CURRENT_STATE pass (never manufactures an action) + an optional TEST_SCENARIO pass → validate →
simulate (only intents that need it) → shadow execution (hypothetical fill) → reconcile →
readiness. Writes only under ``data/capital_shadow*``. Exit 0 OK · 2 unexpected/ledger error ·
75 ledger lock held by another run.

Nothing here signs, broadcasts, or moves a single unit of real value (``REAL_CAPITAL_USD == 0``,
``LAYER_MODE == SHADOW``, enforced independently by ``ledger.append_entry``'s money-path guard).

# LLM_FORBIDDEN
"""
from __future__ import annotations

import argparse
import os
import contextlib
import fcntl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.capital_shadow import contract, incidents, intent as intent_mod, ledger, machine, reconcile, readiness


def _iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_pin(chain_id: int, *, live_rpc: bool, rpc_mod: Any = None, client: Any = None, data_dir: Any = None,
            now: Any = None, dispatcher: Any = None, escalated: Optional[set] = None) -> dict:
    if not live_rpc:
        return {"state": contract.NOT_MEASURED, "number": None, "hash": None, "operators": [],
               "reason": "--no-rpc (default): no live RPC quorum was consulted"}
    if rpc_mod is None:
        try:
            from spa_core.capital_shadow import rpc as rpc_mod  # noqa: F401
        except ImportError:
            return {"state": contract.NOT_MEASURED, "number": None, "hash": None, "operators": [],
                    "reason": "spa_core.capital_shadow.rpc not available"}
    c = client or rpc_mod.RpcClient(chain_id)
    pin = c.pin_block()
    # review #5 remainder: the PIN client's own security_events (forbidden-method/quorum-dissent)
    # must be escalated too, not only the per-intent simulation client's. review round-3 L3:
    # `escalated` (same identity set threaded through every escalation site in run_cycle) is what
    # stops this client's events being re-raised again at the simulate/forward-reconciliation
    # sites when the SAME client object is shared across all three.
    if data_dir is not None and now is not None:
        _escalate_security_events(data_dir, {"security_events": getattr(c, "security_events", [])}, now,
                                  dispatcher, escalated=escalated)
    return pin


def _is_scenario(an_intent: dict) -> bool:
    # review round-3 L5: delegates to intent.is_test_scenario (case-INSENSITIVE on the prefix) —
    # same shared check as machine.py's scenario ceiling, read.py and reconcile.py.
    return intent_mod.is_test_scenario(an_intent.get("scenario"))


class _RefusingClient:
    """Installed whenever ``--no-rpc`` (the default) is in effect and no client was explicitly
    injected: GUARANTEES zero network I/O. ``simulate.simulate_intent``/``unwind_probe``/the
    forward-reconciliation previews all accept a ``client`` and use it INSTEAD OF constructing
    their own live ``RpcClient`` — passing this one in means every call that would otherwise reach
    a live endpoint instead gets an immediate, honest ``NOT_MEASURED`` with no request ever built,
    no socket ever opened.
    """
    security_events: list = []

    def pin_block(self) -> dict:
        return {"state": contract.NOT_MEASURED, "number": None, "hash": None, "operators": [],
               "reason": "--no-rpc: refusing all network I/O by construction"}

    def quorum(self, method: str, params: list, block_number) -> dict:
        return {"state": contract.NOT_MEASURED,
               "reason": "--no-rpc: refusing all network I/O by construction"}


class RunLocked(Exception):
    """Another process holds the top-level run lock (review #13) — this run must not proceed
    concurrently with it. Maps to exit 75 (EX_TEMPFAIL), same convention as ``ledger.LockBusy``."""


def _run_lock_path(data_dir: Path) -> Path:
    return Path(data_dir) / contract.DATA_SUBDIR / ".run.lock"


@contextlib.contextmanager
def _run_lock(data_dir: Path, *, timeout_s: float = 2.0, poll_s: float = 0.05):
    """A SEPARATE lock file from the ledger's own ``.ledger.lock`` (review #13), held for the
    WHOLE ``run_cycle`` — never nested with a second acquisition of the SAME lock from the same
    process (that would self-deadlock a plain ``flock``). Every ``machine.advance`` call made
    while this is held therefore reads ``current_state`` and appends its transition without racing
    a second, concurrent ``run_cycle`` in another process: the second one fails to acquire this
    lock and never reaches a single ``machine.advance`` call at all."""
    path = _run_lock_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RunLocked(f"run lock held by another process: {path}")
                time.sleep(poll_s)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


def _validate(data_dir: Path, an_intent: dict, now: datetime) -> bool:
    machine.record_intent(data_dir, an_intent, now)
    try:
        machine.advance(data_dir, an_intent, contract.S_VALIDATED,
                        {"check": "schema_complete", "fields": sorted(an_intent.keys())}, now)
        return True
    except (machine.IllegalTransition, machine.IntentExpired):
        return False


def _escalate_security_events(data_dir: Path, sim_record: dict, now: datetime, dispatcher: Any, *,
                              escalated: Optional[set] = None) -> None:
    """review #5 HIGH: a security event on the simulation record (forbidden-method attempt,
    quorum disagreement INCLUDING minority dissent — ``rpc.RpcClient`` records both) used to sit
    inside the simulation evidence and never become an incident. Every event is escalated, one
    incident each; unrecognised kinds are never invented into the fixed taxonomy.

    review round-3 L3: when ONE client is shared across ``_get_pin``, every per-intent
    ``_simulate_and_execute`` call, and ``_run_forward_reconciliation``, its ``security_events``
    list is read (in full, or in some overlapping slice) at EACH of those sites — the OLD code
    had no shared memory across sites, so the SAME real event became a FRESH incident every time
    it was seen again (measured: 6 real events -> 16 incidents). ``escalated`` is an identity set
    keyed by ``(kind, repr(detail))`` — not the client's identity, not a list index, which both
    break the moment two different call sites see the SAME event through two differently-sliced
    lists. It MUST be the SAME set object threaded through every escalation site within one
    ``run_cycle`` for "one event -> one incident" to hold HOWEVER clients are shared; the default
    ``None`` only dedups duplicate events WITHIN this one call's own list (correct for a single
    standalone call, e.g. a failure_matrix row that never shares a client across sites).
    Known, accepted limitation: two materially DIFFERENT real events that happen to carry an
    identical ``(kind, detail)`` pair are indistinguishable by this identity and the second is
    treated as a duplicate — in practice ``rpc.RpcClient``'s own detail text names the block/
    operators involved, which makes a real collision implausible; a content hash is used, not an
    object/list identity, specifically so repeated READS of the same growing list are the case
    this guards against, not the event's own uniqueness."""
    seen_this_call: set = set()
    for ev in (sim_record.get("security_events") or []):
        if not isinstance(ev, dict):
            continue
        kind = ev.get("kind")
        if kind not in incidents.KINDS:
            continue
        detail = ev.get("detail")
        identity = (kind, repr(detail))
        if identity in seen_this_call:
            continue
        seen_this_call.add(identity)
        if escalated is not None:
            if identity in escalated:
                continue
            escalated.add(identity)
        detail_text = detail if isinstance(detail, str) else repr(detail)
        incidents.raise_incident(data_dir, kind, detail_text, now=now, dispatcher=dispatcher)


def _simulate_and_execute(data_dir: Path, an_intent: dict, now: datetime, *, simulate_mod: Any,
                           client: Any, dispatcher: Any = None, escalated: Optional[set] = None) -> dict:
    """VALIDATED -> SIMULATED -> SHADOW_READY -> SHADOW_EXECUTED -> (reconcile). Returns a small
    per-intent report. Never advances a TEST_SCENARIO intent past SHADOW_EXECUTED
    (contract.SCENARIO_MAX_STATE, review #12) — a reconciliation OUTCOME may still be recorded
    (it is a ledger row, not a state transition)."""
    intent_id = an_intent["intent_id"]
    scenario = _is_scenario(an_intent)
    report: dict = {"intent_id": intent_id, "sleeve_id": an_intent.get("sleeve_id"), "outcome": None}

    # SPOT_ORDER is routed to exchange_sim.simulate_order, never simulate.simulate_intent — there
    # is no on-chain venue, no block, no calldata. It never feeds a sleeve verdict: its sleeve_id
    # is structurally never a pilot candidate (readiness._NEVER_CANDIDATE), and the pipeline stops
    # right after this (no shadow execution / reconciliation for a centralised-exchange fixture).
    if an_intent.get("action_type") == contract.ACTION_SPOT_ORDER:
        exchange_mod = None
        try:
            from spa_core.capital_shadow import exchange_sim as exchange_mod  # noqa: F401
        except ImportError:
            pass
        if exchange_mod is None:
            report["outcome"] = "SIMULATE_UNAVAILABLE"
            return report
        # review #15 caveat: exchange_sim.simulate_order defaults a MISSING "cash" to 0.0 and
        # correctly REJECTS an order the account can't afford — this is SHADOW mode, so there is
        # no real balance to read; ASSUMED_FULL_FUNDING is an explicit, labelled modelling choice
        # (fund the hypothetical order with exactly its own notional), never exchange_sim's own
        # silent 0.0 default (which would reject every order here).
        assumed_full_funding_usd = an_intent.get("notional") or 0.0
        order = {"symbol": an_intent.get("network_or_venue"), "side": "BUY", "type": "MARKET",
                 "quantity": an_intent.get("notional"), "cash": assumed_full_funding_usd, "position": 0.0}
        book = {"bids": [[1.0, 1_000_000.0]], "asks": [[1.0, 1_000_000.0]]}
        fill = exchange_mod.simulate_order(order, {}, book)
        # review round-3 item 2: exchange_sim sets accepted=True for BOTH a full STATUS_SIMULATED
        # fill AND a STATUS_PARTIAL one — "accepted" means "the order was not rejected outright",
        # never "this is a clean pass". A partial fill is NOT a full simulation and must never be
        # recorded as SIM_PASS / advance like one (that would book a partial fill as a clean pass
        # in the real pipeline, exactly the gap failure_matrix row 34 must now catch for real).
        is_partial = fill.get("status") == getattr(exchange_mod, "STATUS_PARTIAL", "PARTIAL")
        if is_partial:
            sim_result = "PARTIAL"
            revert_reason = fill.get("reason") or "partial fill — not a full simulation"
            is_pass = False
        elif fill.get("accepted"):
            sim_result = contract.SIM_PASS
            revert_reason = fill.get("reason")
            is_pass = True
        else:
            sim_result = contract.SIM_FAIL
            revert_reason = fill.get("reason")
            is_pass = False
        sim_record = {"schema": contract.SCHEMA_SIMULATION, "intent_id": intent_id,
                      "label": exchange_mod.LABEL, "not_proven": list(contract.NOT_PROVEN),
                      "trust_model": "deterministic local match against a caller-supplied book — "
                                    "never a venue call", "chain_id": None, "block": {"number": None,
                      "hash": None, "operators": []}, "sender": None, "checks": [],
                      "call": {"signature": "exchange_sim.simulate_order", "selector": None, "args_readable":
                               [{"name": "order", "type": "dict", "value": order}]},
                      "gas_estimate": None, "result": sim_result, "revert_reason": revert_reason,
                      "post_state": fill, "security_events": [], "simulated_at": _iso(now)}
        ledger.record_simulation_entry(data_dir, an_intent, sim_record, now)
        to_state = contract.S_SIMULATED if is_pass else contract.S_SIMULATION_FAILED
        machine.advance(data_dir, an_intent, to_state, {"exchange_sim": is_pass}, now)
        report["outcome"] = "SIMULATED" if is_pass else "SIMULATION_FAILED"
        return report

    if an_intent.get("network_or_venue") in contract.PERMISSIONED_VENUES:
        sim_record = {"schema": contract.SCHEMA_SIMULATION, "intent_id": intent_id,
                      "label": contract.SIM_LABEL, "not_proven": list(contract.NOT_PROVEN),
                      "trust_model": contract.TRUST_MODEL, "chain_id": an_intent.get("network_or_venue"),
                      "block": an_intent.get("pinned_block"), "sender": None, "checks": [],
                      "call": {}, "gas_estimate": None, "result": contract.SIM_NOT_SIMULATABLE,
                      "revert_reason": "permissioned venue: synthetic sender reverts on allow-lists",
                      "post_state": {}, "security_events": [], "simulated_at": _iso(now)}
        ledger.record_simulation_entry(data_dir, an_intent, sim_record, now)
        machine.advance(data_dir, an_intent, contract.S_SIMULATION_FAILED,
                        {"reason": "NOT_SIMULATABLE: permissioned venue"}, now)
        report["outcome"] = "SIMULATION_FAILED"
        return report

    if simulate_mod is None:
        report["outcome"] = "SIMULATE_UNAVAILABLE"
        return report

    try:
        sim_record = simulate_mod.simulate_intent(an_intent, client=client, now=now)
    except Exception as exc:
        machine.advance(data_dir, an_intent, contract.S_SIMULATION_FAILED, {"reason": f"simulate raised: {exc!r}"},
                        now)
        report["outcome"] = "SIMULATION_FAILED"
        return report
    ledger.record_simulation_entry(data_dir, an_intent, sim_record, now)
    _escalate_security_events(data_dir, sim_record, now, dispatcher, escalated=escalated)

    if sim_record.get("result") != contract.SIM_PASS:
        machine.advance(data_dir, an_intent, contract.S_SIMULATION_FAILED,
                        {"reason": sim_record.get("revert_reason") or sim_record.get("result")}, now)
        report["outcome"] = "SIMULATION_FAILED"
        return report

    violation = machine.policy_violation(an_intent, sim_record)
    if violation is not None:
        machine.advance(data_dir, an_intent, contract.S_RISK_BLOCKED, {"reason": violation}, now)
        report["outcome"] = "RISK_BLOCKED"
        return report

    machine.advance(data_dir, an_intent, contract.S_SIMULATED, {"result": sim_record.get("result")}, now)

    # TOCTOU recheck (review #9) protects a REAL decision from going stale between simulation and
    # shadow execution. A TEST_SCENARIO fixture never had a real risk_snapshot to begin with (its
    # fields are deliberately NOT_MEASURED placeholders — build_scenario_intents takes no data_dir
    # and cannot read the world) — comparing a placeholder against the live world would flag every
    # run as "changed" regardless of whether anything actually did. ``machine.recheck`` itself still
    # performs that exact comparison when called directly (used by tests and by ``verify.py``); it
    # is only skipped HERE, in the scenario branch of the pipeline.
    if not scenario:
        rc = machine.recheck(an_intent, data_dir, now)
        if rc["verdict"] is not None:
            machine.advance(data_dir, an_intent, rc["verdict"], {"mismatches": rc["mismatches"]}, now)
            report["outcome"] = rc["verdict"]
            return report

    machine.advance(data_dir, an_intent, contract.S_SHADOW_READY, {"check": "toctou_recheck_clean"}, now)

    post_state = sim_record.get("post_state") or {}
    delta = post_state.get("delta") if isinstance(post_state, dict) else None
    if delta is None:
        notional = an_intent.get("notional") or 0.0
        action_type = an_intent.get("action_type")
        # review #10: APPROVE used to fall into the `else` branch below and get booked as a
        # -notional POSITION — an approval moves no position at all, only an allowance.
        if action_type in (contract.ACTION_SUPPLY, contract.ACTION_DEPOSIT_4626):
            delta = notional
        elif action_type in (contract.ACTION_WITHDRAW, contract.ACTION_REDEEM_4626):
            delta = -notional
        else:
            delta = 0.0
    # gas_estimate is a CELL (dict: {"state","value",...}) on the real simulator, not a bare number
    # (found via an integration run) — contract.value_of() is the sanctioned way to read a number
    # out of a cell; an absent/non-measured cell yields None, never a dict compared as a number.
    gas_raw = sim_record.get("gas_estimate")
    gas = contract.value_of(gas_raw) if isinstance(gas_raw, dict) else gas_raw
    # the REAL simulator's DEPOSIT_4626 post_state names it "shares_returned", not "shares" (found
    # via an integration run); kept with a fallback for fixtures using the simpler name.
    shares = post_state.get("shares_returned", post_state.get("shares")) if isinstance(post_state, dict) else None
    # review #10: fees/slippage/position_before were hard-coded 0.0 — a fabricated MEASURED zero,
    # indistinguishable from "we checked and it really is zero". None here means NOT_MEASURED
    # (nothing in this shadow fill actually measures any of the three).
    fill = {"fill_seq": 1, "position_before": None, "position_after": 0.0 + delta, "cash_before": None,
           "cash_after": None, "nav_impact": delta, "nav_before": 0.0, "fees": None, "gas": gas,
           "slippage": None, "fills": 1, "shares": shares, "pin": an_intent.get("pinned_block")}
    ledger.append_idempotent(data_dir, kind="shadow_fill", key=("shadow_fill", intent_id, 1),
                             payload={"intent_id": intent_id, "sleeve_id": an_intent.get("sleeve_id"), **fill},
                             now=now)
    machine.advance(data_dir, an_intent, contract.S_SHADOW_EXECUTED, {"fill": fill}, now)
    # Reconciliation is now a FORWARD test only (ADR-556 review #4): it happens at the START of a
    # LATER run, once a block strictly later than this one exists, via _run_forward_reconciliation
    # below — never here, immediately, at the same block (a same-block "forward" test is not a
    # forward test, it is a self-comparison).
    report["outcome"] = "SHADOW_EXECUTED"
    return report


def _run_forward_reconciliation(data_dir: Path, now: datetime, *, rpc_mod: Any, simulate_mod: Any,
                                client: Any, dispatcher: Any = None, escalated: Optional[set] = None) -> list:
    """At the START of every run (review #4): for every earlier SHADOW_EXECUTED intent not yet
    FINALLY reconciled — scenario or current-state — re-read the chain at a NEW pinned block.
    MATCHED/MISMATCH are final (review #9): once recorded, never revisited. A ``NOT_MEASURED``
    outcome is NOT final — it is retried on later runs (never stranding the intent) up to the
    intent's own ``expires_at``; past that, ``machine.advance`` would refuse the transition anyway
    (review #12 — expiry checked before idempotency), so the attempt is simply skipped, loudly
    nowhere since there is nothing more this layer can do for an expired intent. Returns ``[]``
    (touches nothing) when no pending intent exists, or no simulate module is available at all."""
    if simulate_mod is None:
        try:
            from spa_core.capital_shadow import simulate as simulate_mod  # noqa: F401
        except ImportError:
            return []

    entries = ledger.read_all(data_dir)
    latest_recon_by_intent: dict = {}
    for e in entries:
        if e.get("kind") != "reconciliation":
            continue
        iid = e["payload"]["intent_id"]
        if iid not in latest_recon_by_intent or e["seq"] > latest_recon_by_intent[iid]["seq"]:
            latest_recon_by_intent[iid] = e
    finally_reconciled_ids = {iid for iid, e in latest_recon_by_intent.items()
                             if e["payload"].get("outcome") != contract.REC_NOT_MEASURED}
    pending_ids: list = []
    seen: set = set()
    for e in entries:
        if e.get("kind") != "transition" or e["payload"].get("to_state") != contract.S_SHADOW_EXECUTED:
            continue
        iid = e["payload"]["intent_id"]
        if iid in seen or iid in finally_reconciled_ids:
            continue
        seen.add(iid)
        pending_ids.append(iid)
    if not pending_ids:
        return []

    intents_by_id = {e["payload"]["intent_id"]: e["payload"] for e in entries if e.get("kind") == "intent"}
    try:
        from spa_core.capital_shadow import tokens as tokens_mod
    except ImportError:
        tokens_mod = None
    clients_by_chain: dict = {}
    # review #5 remainder / round-3 L3: these clients are REUSED across intents within one pass,
    # so their security_events list keeps growing. The OLD per-client slice-index dedup here was
    # its OWN separate bookkeeping from _get_pin's / _simulate_and_execute's — when the SAME
    # client object is ALSO shared with those sites (an explicitly-injected client, not one built
    # locally here), each site's independent "start from 0" memory re-escalated the same real
    # event once per site. `escalated` is now the ONE shared content-identity set threaded through
    # every escalation call in run_cycle; a local set is created here only when none was supplied
    # (a standalone call to this function, e.g. in a test, still dedups correctly across the
    # multiple intents reconciled within THIS call).
    if escalated is None:
        escalated = set()

    def _client_for(chain_id):
        if client is not None:
            return client
        if chain_id in clients_by_chain:
            return clients_by_chain[chain_id]
        if rpc_mod is None:
            return None
        c = rpc_mod.RpcClient(chain_id)
        clients_by_chain[chain_id] = c
        return c

    def _escalate_new(cl) -> None:
        events = getattr(cl, "security_events", None) or []
        if events:
            _escalate_security_events(data_dir, {"security_events": events}, now, dispatcher,
                                      escalated=escalated)

    reports = []
    for intent_id in pending_ids:
        an_intent = intents_by_id.get(intent_id)
        simulation = ledger.load_simulation(data_dir, intent_id)
        if an_intent is None or simulation is None:
            continue
        if machine.is_expired(an_intent, now):
            continue  # nothing more this layer can do — a transition would be refused anyway
        venue = an_intent.get("network_or_venue")
        ven = tokens_mod.venue(venue) if (tokens_mod is not None and isinstance(venue, str)) else None
        chain_id = ven["chain_id"] if ven else None
        cl = _client_for(chain_id)
        if cl is None:
            continue  # no RPC layer reachable at all (no client, no rpc_mod) — try again later

        rec = reconcile.forward_reconcile(an_intent, simulation, client=cl, now=now, simulate_mod=simulate_mod,
                                          data_dir=data_dir)
        _escalate_new(cl)
        if rec is None:
            continue  # no LATER block exists yet — skip, try again on a later run

        new_block = rec["new_block"]
        entry, created = ledger.append_idempotent(data_dir, kind="reconciliation",
                                                  key=("reconciliation", intent_id, new_block), payload=rec, now=now)
        if created and not _is_scenario(an_intent):
            # current-state intents advance the machine; TEST_SCENARIO intents stay <= SHADOW_EXECUTED
            # (contract.SCENARIO_MAX_STATE) — the row above is still recorded either way.
            if rec["outcome"] == contract.REC_MATCHED:
                machine.advance(data_dir, an_intent, contract.S_RECONCILED, {"reconciliation": rec["outcome"]}, now)
            elif rec["outcome"] == contract.REC_MISMATCH:
                machine.advance(data_dir, an_intent, contract.S_RECONCILIATION_FAILED,
                                {"reconciliation": rec["outcome"]}, now)
            # REC_NOT_MEASURED: no transition — stays SHADOW_EXECUTED (an honest "cannot know" is not
            # a failure and is not pretended to be a pass).
        reports.append({"intent_id": intent_id, "sleeve_id": an_intent.get("sleeve_id"), "outcome": rec["outcome"],
                       "old_block": rec["old_block"], "new_block": new_block})
    return reports


def run_cycle(data_dir: Path, now: Optional[datetime] = None, *, scenario: Optional[str] = None,
             live_rpc: bool = False, simulate_mod: Any = None, rpc_mod: Any = None, client: Any = None,
             dispatcher: Any = None, run_lock_timeout_s: float = 2.0) -> dict:
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # --no-rpc (the default) MUST guarantee zero network I/O: install a client that refuses every
    # call by construction, rather than merely skipping OUR OWN pin fetch and trusting every other
    # call site (simulate.simulate_intent, the forward-reconciliation previews) to also stay off
    # the network when given client=None — they do not; client=None means THEY build their own
    # live RpcClient (found via an integration run).
    if not live_rpc and client is None:
        client = _RefusingClient()

    # review #13: a top-level run lock around the WHOLE cycle — a second, truly concurrent
    # run_cycle (another OS process) fails to acquire this and never reaches a single
    # machine.advance call, so current_state reads inside this cycle never race one in another
    # process. A SEPARATE lock file from the ledger's own .ledger.lock (never nested with it).
    with _run_lock(data_dir, timeout_s=run_lock_timeout_s):
        try:
            chain = ledger.verify_chain(data_dir)
        except ledger.LedgerError as exc:
            # review #5 HIGH: read_all() used to raise straight out of verify_chain, before the
            # incident was ever raised — the incident is now raised FIRST, then the error is
            # re-raised so main() still exits 2 (this run cannot proceed on a broken ledger).
            incidents.raise_incident(data_dir, "ledger_broken", f"ledger unreadable: {exc}", now=now,
                                     dispatcher=dispatcher)
            raise
        if not chain.get("ok", False) and chain.get("entries", 0) > 0:
            incidents.raise_incident(data_dir, "ledger_broken",
                                     f"ledger chain broken at seq={chain.get('break_at')} "
                                     f"reason={chain.get('reason')}", now=now, dispatcher=dispatcher)

        if simulate_mod is None:
            try:
                from spa_core.capital_shadow import simulate as simulate_mod  # noqa: F401 — lazy, optional sibling
            except ImportError:
                simulate_mod = None

        if rpc_mod is None and client is None:
            # live_rpc=True and no client/rpc_mod injected by the caller: the forward-reconciliation
            # pass needs ITS OWN way to build a real per-chain RpcClient (simulate.simulate_intent
            # builds its own internally and never shares it — a separate, later pin is the whole
            # point of a FORWARD test).
            try:
                from spa_core.capital_shadow import rpc as rpc_mod  # noqa: F401 — lazy, optional sibling
            except ImportError:
                rpc_mod = None

        # review round-3 L3: ONE shared content-identity set for every escalation call this cycle
        # makes — pin, forward reconciliation, and every per-intent simulation — so a client
        # shared across those sites never has the same real security event turned into more than
        # one incident (measured before this fix: 6 real events -> 16 incidents).
        escalated: set = set()

        forward_reports = _run_forward_reconciliation(data_dir, now, rpc_mod=rpc_mod, simulate_mod=simulate_mod,
                                                      client=client, dispatcher=dispatcher, escalated=escalated)

        pin = _get_pin(1, live_rpc=live_rpc, rpc_mod=rpc_mod, client=client, data_dir=data_dir, now=now,
                      dispatcher=dispatcher, escalated=escalated)

        current_intents = intent_mod.build_current_intents(data_dir, now, pin)
        per_intent_reports = []
        for an_intent in current_intents:
            if not _validate(data_dir, an_intent, now):
                per_intent_reports.append({"intent_id": an_intent["intent_id"], "outcome": "INVALID_OR_EXPIRED"})
                continue
            if an_intent["action_type"] == contract.ACTION_NO_ACTION:
                per_intent_reports.append({"intent_id": an_intent["intent_id"], "sleeve_id": an_intent["sleeve_id"],
                                           "outcome": "NO_ACTION"})
                continue
            per_intent_reports.append(_simulate_and_execute(data_dir, an_intent, now, simulate_mod=simulate_mod,
                                                            client=client, dispatcher=dispatcher,
                                                            escalated=escalated))

        scenario_intents = []
        if scenario:
            scenario_intents = intent_mod.build_scenario_intents(now, pin, scenario)
            for an_intent in scenario_intents:
                if not _validate(data_dir, an_intent, now):
                    per_intent_reports.append({"intent_id": an_intent["intent_id"], "outcome": "INVALID_OR_EXPIRED"})
                    continue
                if an_intent["action_type"] == contract.ACTION_NO_ACTION:
                    # review #12: a scenario intent is ALSO forced to NO_ACTION when the pin isn't
                    # MEASURED — it must be reported as cleanly as a current-state NO_ACTION, never
                    # fed into _simulate_and_execute (which would otherwise simulate a no-op action
                    # and then trip policy_violation's gas-not-measured check for the wrong reason).
                    per_intent_reports.append({"intent_id": an_intent["intent_id"],
                                              "sleeve_id": an_intent["sleeve_id"], "outcome": "NO_ACTION"})
                    continue
                per_intent_reports.append(_simulate_and_execute(data_dir, an_intent, now, simulate_mod=simulate_mod,
                                                                client=client, dispatcher=dispatcher,
                                                                escalated=escalated))

        # review N5: readiness.evaluate() now returns ONLY sleeve reports — venue_canary moved to
        # its own top-level key (read.latest() builds it separately via venue_canary_section()).
        entries = ledger.read_all(data_dir)
        reports = readiness.evaluate(data_dir, entries, now)
        for sleeve_id, report in reports.items():
            ledger.append_idempotent(data_dir, kind="readiness",
                                     key=("readiness", sleeve_id, now.strftime("%Y-%m-%d")), payload=report,
                                     now=now)

        summary = {
            "generated_at": _iso(now), "current_intents": len(current_intents),
            "scenario_intents": len(scenario_intents), "per_intent": per_intent_reports,
            "forward_reconciliations": forward_reports,
            "readiness_states": {sid: r["readiness_state"] for sid, r in reports.items()},
            "authorization": contract.AUTHORIZATION_TEXT,
        }
        return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m spa_core.capital_shadow.run")
    # review round-3 item 7 (M2): the OLD default ("data", a path relative to CWD) ignored
    # SPA_DATA_DIR entirely. scripts/check_agent_before_deploy.sh sets SPA_DATA_DIR to a sandbox
    # for its trial run — with the old default, a gate trial run with no explicit --data-dir still
    # wrote straight into the PRODUCTION data/capital_shadow (measured: it did, at a real deploy,
    # 08:13). default=None (same pattern as spa_core/investment_cio/run.py) lets the resolution
    # happen at call time: an explicit --data-dir always wins; otherwise live_data_dir() honours
    # SPA_DATA_DIR first, else this code tree's own data/ (never another tree's).
    parser.add_argument("--data-dir", default=None, help="defaults to SPA_DATA_DIR, else this code tree's own data/ dir")
    parser.add_argument("--now", default=None)
    parser.add_argument("--scenario", default=None)
    rpc_group = parser.add_mutually_exclusive_group()
    rpc_group.add_argument("--live-rpc", action="store_true", default=False)
    rpc_group.add_argument("--no-rpc", action="store_true", default=False)
    args = parser.parse_args(argv)

    if args.data_dir:
        data_dir = Path(args.data_dir)
    else:
        # Final re-review (L-new): live_data_dir() falls back to the LIVE tree when SPA_DATA_DIR is
        # unset, so a run from any worktree appended to the production ledger. The default is now
        # SPA_DATA_DIR if set, else THIS code tree's own data/ — the launchd agent runs from the
        # production tree, so production still writes production; a worktree writes its own.
        from spa_core.utils.live_paths import DATA_DIR_ENV
        sandbox = os.environ.get(DATA_DIR_ENV)
        data_dir = Path(sandbox) if sandbox else Path(__file__).resolve().parents[2] / "data"

    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
    try:
        summary = run_cycle(data_dir, now, scenario=args.scenario, live_rpc=bool(args.live_rpc))
    except (ledger.LockBusy, RunLocked) as exc:
        print(f"capital_shadow: LOCKED: {exc}")
        return contract.EXIT_LOCKED
    except Exception as exc:  # unexpected — fail loudly, never silently
        print(f"capital_shadow: ERROR: {exc!r}")
        return contract.EXIT_FAIL

    print(f"capital_shadow: {summary['current_intents']} current intent(s), "
         f"{summary['scenario_intents']} scenario intent(s), "
         f"{len(summary['forward_reconciliations'])} forward reconciliation(s), "
         f"readiness={summary['readiness_states']} | {summary['authorization']}")
    return contract.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
