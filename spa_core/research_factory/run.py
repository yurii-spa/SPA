"""spa_core/research_factory/run.py — orchestrator: scanners -> registry -> lifecycle -> admission
-> forward -> eligibility -> status.json.

``python -m spa_core.research_factory.run [--data-dir D] [--now ISO] [--live-rpc]``

Default data dir: ``$SPA_DATA_DIR`` if set, else THIS code tree's own ``data/`` — never another
tree (``Path(__file__).resolve().parents[2] / "data"``).

Scanner modules live in ``spa_core.research_factory.scanners`` (Package B, built in parallel) and
are discovered DYNAMICALLY — an empty or missing ``scanners`` package is tolerated (status
NOT_MEASURED for the run, never a crash). Every scanner is called as
``scan(data_dir, now, rpc_client=None)`` unless ``--live-rpc`` is given.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spa_core.research_factory import admission, contract, dedup, eligibility, forward, lifecycle, read, registry
from spa_core.research_factory._common import iso, ledger_for
from spa_core.utils.atomic import atomic_save
from spa_core.utils.hash_ledger import DuplicateKey, LedgerError, RunLocked

#: (gate, verdicts-that-route-here, hold state) — first match in this order wins. A gate judged
#: UNKNOWN for lack of ANY data (e.g. no as_of to judge freshness from at all, as opposed to a
#: judged-stale FAIL) is a DATA_INSUFFICIENT case, never STALE — STALE means "we know it, and it
#: aged out", not "we never had anything to date".
_FAIL, _UNKNOWN = contract.GATE_FAIL, contract.GATE_UNKNOWN
_GATE_ROUTE = [
    ("counterparty_named", (_FAIL, _UNKNOWN), contract.COUNTERPARTY_UNKNOWN),
    ("no_duplicate_exposure", (_FAIL, _UNKNOWN), contract.DUPLICATE_EXPOSURE),
    ("data_fresh", (_FAIL,), contract.STALE_STATE),
    ("data_fresh", (_UNKNOWN,), contract.DATA_INSUFFICIENT),
    ("source_provenance_acceptable", (_FAIL, _UNKNOWN), contract.DATA_INSUFFICIENT),
    ("fees_measurable", (_FAIL, _UNKNOWN), contract.DATA_INSUFFICIENT),
    ("liquidity_measurable", (_FAIL, _UNKNOWN), contract.DATA_INSUFFICIENT),
    ("no_conflicted_inputs", (_FAIL, _UNKNOWN), contract.DATA_INSUFFICIENT),
    ("leverage_known", (_FAIL, _UNKNOWN), contract.RISK_UNRESOLVED),
]


def _default_data_dir() -> Path:
    import os
    env = os.environ.get("SPA_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data"


def _discover_scanners():
    try:
        pkg = importlib.import_module("spa_core.research_factory.scanners")
    except ModuleNotFoundError:
        return []
    mods = []
    for info in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
        try:
            mod = importlib.import_module(info.name)
        except Exception:  # noqa: BLE001 — a broken scanner module must not crash the run
            continue
        if hasattr(mod, "scan"):
            mods.append(mod)
    return mods


def _route_hold_state(report: dict) -> tuple[str, list]:
    gates = report["gates"]
    # every non-PASS gate is reported (the routing gate first) — a reader must see ALL the reasons a
    # candidate is held, not only the one that happened to route it
    failed = [f"{g}: {v['evidence']}" for g, v in gates.items() if v["verdict"] != contract.GATE_PASS]
    for gate_name, verdicts, hold_state in _GATE_ROUTE:
        if gates[gate_name]["verdict"] in verdicts:
            first = f"{gate_name}: {gates[gate_name]['evidence']}"
            return hold_state, [first] + [f for f in failed if f != first]
    return contract.REJECTED, failed or ["admission report not PASS"]


def _registry_view_for(data_dir: Path, exclude_id: str, all_candidates: dict, existing_book_roots: list) -> dict:
    view = {cid: {**c, "admission_state": lifecycle.current_state(data_dir, cid)}
           for cid, c in all_candidates.items() if cid != exclude_id}
    view["_existing_book_roots"] = existing_book_roots
    return view


def _process_candidate(data_dir: Path, cid: str, all_candidates: dict, existing_book_roots: list,
                       new_obs: dict, now: datetime) -> None:
    candidate = all_candidates.get(cid)
    if candidate is None:
        return
    state = lifecycle.current_state(data_dir, cid)
    if state == contract.DISCOVERED:
        if candidate.get("mechanism_id") in contract.MECHANISMS and candidate.get("exposure_key"):
            lifecycle.transition(data_dir, cid, contract.SCREENED,
                                reason="identity resolved, mechanism known", now=now)
            state = contract.SCREENED
        else:
            lifecycle.transition(data_dir, cid, contract.DATA_INSUFFICIENT,
                                reason="mechanism/identity not resolved", now=now)
            return

    if state == contract.SCREENED:
        lifecycle.transition(data_dir, cid, contract.RESEARCH_READY, reason="admission evaluable", now=now)
        state = contract.RESEARCH_READY

    if state == contract.RESEARCH_READY:
        view = _registry_view_for(data_dir, cid, all_candidates, existing_book_roots)
        report = admission.evaluate(candidate, view, now)
        if report["verdict"] == contract.GATE_PASS:
            lifecycle.transition(data_dir, cid, contract.PAPER_CANDIDATE, reason="all admission gates PASS",
                                now=now)
            state = contract.PAPER_CANDIDATE
        else:
            hold, reasons = _route_hold_state(report)
            lifecycle.transition(data_dir, cid, hold, reason="; ".join(reasons), now=now)
            return

    if state == contract.PAPER_CANDIDATE:
        view = _registry_view_for(data_dir, cid, all_candidates, existing_book_roots)
        report = admission.evaluate(candidate, view, now)
        if report["verdict"] != contract.GATE_PASS:
            hold, reasons = _route_hold_state(report)
            lifecycle.transition(data_dir, cid, hold, reason="; ".join(reasons), now=now)
            return
        snap = admission.write_admission_snapshot(data_dir, candidate, report, now)
        admission_id = (snap.get("payload") or {}).get("admission_id")
        lifecycle.transition(data_dir, cid, contract.PAPER_ACTIVE, gate_ref=admission_id,
                            reason="admission snapshot PASS", now=now)
        state = contract.PAPER_ACTIVE

    if state in (contract.PAPER_ACTIVE, contract.EVIDENCE_ACCUMULATING, contract.CIO_ELIGIBLE):
        # H4: an observation row is written EVERY run for EVERY paper-state candidate — a
        # NOT_MEASURED cell when no scanner supplied one this run, rather than silently writing
        # nothing at all. A silent gap could never trip the 3-consecutive-not-counted -> STALE
        # rule (forward._maybe_mark_stale); a feed that goes quiet would then look no different
        # from one with no activity to report, forever.
        obs = new_obs.get(cid)
        if obs is None:
            obs = {"period": now.strftime("%Y-%m-%d"), "backfill": False, "realised_index": None,
                  "observed_return": contract.cell(contract.NOT_MEASURED,
                                                    reason="no observation from any scanner this run")}
        forward.record(data_dir, cid, obs, now)
        state = lifecycle.current_state(data_dir, cid)  # forward.record may have moved it to STALE

    if state == contract.PAPER_ACTIVE and forward.forward_periods(data_dir, cid) >= 1:
        admission_id = lifecycle.active_admission_id(data_dir, cid)
        lifecycle.transition(data_dir, cid, contract.EVIDENCE_ACCUMULATING, gate_ref=admission_id,
                            reason="first counted forward period recorded", now=now)
        state = contract.EVIDENCE_ACCUMULATING

    if state in (contract.EVIDENCE_ACCUMULATING, contract.CIO_ELIGIBLE):
        view = _registry_view_for(data_dir, cid, all_candidates, existing_book_roots)
        eligibility.recheck_and_apply(data_dir, candidate, view, now)


def _reschreen_if_changed(data_dir: Path, cid: str, state: str, prior_fp: Optional[str], new_fp: str,
                          now: datetime) -> None:
    if state in contract.HOLD_STATES and state not in (contract.SUPERSEDED, contract.DISAPPEARED,
                                                       contract.OBSERVE_ONLY) and prior_fp is not None \
            and prior_fp != new_fp:
        lifecycle.transition(data_dir, cid, contract.SCREENED,
                            gate_ref={"prev_digest": prior_fp, "new_digest": new_fp},
                            reason="failed gate's input changed — re-screening", now=now)


def run_once(data_dir: Path, now: datetime, *, rpc_client=None) -> dict:
    ledger = ledger_for(data_dir)
    with ledger.run_lock():
      try:
        verdict = ledger.verify()
        if not verdict["ok"]:
            raise LedgerError(f"ledger BROKEN (reason={verdict.get('reason')}); refusing to run")
        # M7: one full chain+anchor walk for the WHOLE run, not one per append. The anchors are
        # still extended on every write below, so a LATER, independent verify() still catches a
        # torn/tampered history — only the redundant re-walk inside an already-verified run is
        # skipped.
        ledger.mark_verified()

        scanners = _discover_scanners()
        scan_results = []
        scanner_errors = []  # H0: logged into the run row, never silently swallowed
        for mod in scanners:
            try:
                scan_results.append(mod.scan(data_dir, now, rpc_client=rpc_client))
            except Exception as exc:  # noqa: BLE001 — one broken scanner must not sink the run
                name = getattr(mod, "__name__", "?")
                detail = f"{type(exc).__name__}: {exc}"
                scanner_errors.append({"scanner": name, "error": detail})
                scan_results.append({"scanner": name, "domain": None,
                                     "as_of": iso(now), "status": "UNAVAILABLE", "reason": detail,
                                     "denominators": {"scanned": None, "discovered": 0, "truncated": None},
                                     "candidates": [], "unresolved": [], "observations": {}, "counterparty": {},
                                     "existing_book_roots": []})

        existing_book_roots: list = []
        new_obs: dict = {}
        seen_this_run: dict = {}  # scanner_name -> {candidate_id, ...}
        discovered_ids_by_domain: dict = {}
        total_scanned = total_truncated = 0
        any_scanned = any_truncated = False

        for res in scan_results:
            denom = res.get("denominators") or {}
            if denom.get("scanned") is not None:
                total_scanned += denom["scanned"]
                any_scanned = True
            if denom.get("truncated") is not None:
                total_truncated += denom["truncated"]
                any_truncated = True
            existing_book_roots.extend(res.get("existing_book_roots") or [])

            scanner_name = res.get("scanner")
            ids_this_scanner = set()
            for cand in res.get("candidates") or []:
                full = {f: cand.get(f) for f in contract.CANDIDATE_FIELDS}
                # H3: the field disappearance is keyed by is the PRODUCING SCANNER, never
                # `venue_or_protocol` (a protocol name, not a scanner name — comparing it
                # against `seen_this_run` (keyed by scanner) silently never matched, so
                # disappearance never fired). Not part of contract.CANDIDATE_FIELDS (frozen); an
                # extra key on the dict, set here at ingestion as instructed.
                full["producing_scanner"] = scanner_name
                cp_map = res.get("counterparty")
                cp = cp_map.get(full["candidate_id"]) if isinstance(cp_map, dict) else None
                if cp is not None:
                    full["counterparty"] = cp
                if res.get("domain") == "TRADING_RESEARCH":
                    full["admission_state"] = contract.OBSERVE_ONLY
                prior = registry.latest_snapshot(ledger, full["candidate_id"])
                prior_fp = (prior.get("payload") or {}).get("fingerprint") if prior else None
                registry.upsert(data_dir, full, now)
                ids_this_scanner.add(full["candidate_id"])
                discovered_ids_by_domain.setdefault(res.get("domain"), set()).add(full["candidate_id"])
                new_fp = registry.fingerprint_of(full)
                state_now = lifecycle.current_state(data_dir, full["candidate_id"])
                _reschreen_if_changed(data_dir, full["candidate_id"], state_now, prior_fp, new_fp, now)

                if res.get("domain") == "TRADING_RESEARCH":
                    lifecycle.transition(data_dir, full["candidate_id"], contract.OBSERVE_ONLY,
                                        reason="projected read-only from trading_research", now=now)

            for u in res.get("unresolved") or []:
                registry.record_unresolved(data_dir, scanner_name, res.get("domain"), u, now)

            for cid, obs in (res.get("observations") or {}).items():
                new_obs[cid] = obs

            if res.get("status") == "OK":
                seen_this_run[scanner_name] = ids_this_scanner

        all_candidates = {cid: (registry.current_candidate(data_dir, cid) or {})
                          for cid in registry.all_candidate_ids(ledger)}

        # disappearance: a paper-state candidate missing from its OWN PRODUCING SCANNER's output
        # this run, for a run where THAT scanner's status was OK (H3) — never UNAVAILABLE.
        for cid, candidate in all_candidates.items():
            state = lifecycle.current_state(data_dir, cid)
            if state not in contract.PAPER_STATES:
                continue
            producing_scanner = candidate.get("producing_scanner")
            if producing_scanner in seen_this_run and cid not in seen_this_run[producing_scanner]:
                ledger.append_idempotent("disappearance", ["disappearance", cid, iso(now)],
                                        {"candidate_id": cid, "last_state": state,
                                         "producing_scanner": producing_scanner}, iso(now))
                lifecycle.transition(data_dir, cid, contract.DISAPPEARED,
                                    reason="absent from an OK scanner's output this run", now=now)

        for cid in list(all_candidates):
            _process_candidate(data_dir, cid, all_candidates, existing_book_roots, new_obs, now)

        run_payload = {
            "generated_at": iso(now),
            "denominators": {"scanned": total_scanned if any_scanned else None,
                            "discovered": sum(len(v) for v in discovered_ids_by_domain.values()),
                            "truncated": total_truncated if any_truncated else None},
            "scanners": [r.get("scanner") for r in scan_results],
            "scanner_errors": scanner_errors,  # H0: logged, never silently dropped
        }
        ledger.append_idempotent("run", ["run", iso(now)], run_payload, iso(now))

        status = read.latest(data_dir)
        atomic_save(status, str(ledger.root() / contract.STATUS))
        registry.rebuild_index(data_dir)
        return status
      finally:
        # N3: trust (and the read_all() cache it permits) is scoped to EXACTLY this run — revoke
        # it the instant the run ends (success OR failure), still under the run lock, so no
        # later call in THIS process (e.g. a second run_once after an outside tamper) can ever
        # be served a stale cache. "The cache may serve reads only inside a run, under the run
        # lock" (N3) -- this is the other half of that sentence.
        ledger.invalidate_cache()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--now", default=None)
    parser.add_argument("--live-rpc", action="store_true")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else _default_data_dir()
    now = contract.parse_ts(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        print(f"unparseable --now {args.now!r}", file=sys.stderr)
        return 2

    rpc_client = None
    if args.live_rpc:
        # H0: this must be an instance, never the bare MODULE — onchain.py calls
        # rpc_client.pin_block()/.quorum()/.request()/.endpoints, none of which exist on the
        # module object itself (`capital_shadow.rpc` has no top-level `pin_block`). Passing the
        # module silently turned every call into an AttributeError, which run_once's per-scanner
        # try/except then swallowed as a (wrongly) UNAVAILABLE scanner — every single day, for
        # every scanner that touches the chain.
        from spa_core.capital_shadow.rpc import RpcClient
        rpc_client = RpcClient(1)  # chain_id 1 = Ethereum mainnet (the only chain onchain.py reads)

    try:
        status = run_once(data_dir, now, rpc_client=rpc_client)
    except RunLocked as exc:
        print(str(exc), file=sys.stderr)
        return contract.EXIT_LOCKED
    except LedgerError as exc:
        print(str(exc), file=sys.stderr)
        return contract.EXIT_BROKEN

    # H0: exit 0 ONLY when the ledger's own integrity is OK — a scanner crash never blocks a
    # clean exit (it is recorded, not fatal), but a BROKEN ledger must never report success even
    # if run_once somehow returned a status dict for it.
    if status.get("integrity") != "OK":
        print(f"research_factory run: integrity={status.get('integrity')!r}, refusing a clean exit",
             file=sys.stderr)
        return contract.EXIT_BROKEN

    print(f"research_factory run ok: {status['denominators']}")
    return contract.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
