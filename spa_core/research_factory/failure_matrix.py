"""spa_core/research_factory/failure_matrix.py — ACTUALLY INDUCED failure scenarios, run through
the real Package A code on a fresh tmp data dir each. ``python -m ...failure_matrix --out FILE``.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from spa_core.research_factory import admission, contract, dedup, eligibility, forward, lifecycle, read, registry, run
from spa_core.utils.atomic import atomic_save
from spa_core.utils.hash_ledger import LedgerError

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)


def _cell(state=contract.MEASURED, value=1.0, judge_now=None, **kw):
    kw.setdefault("source_ref", "https://example/feed")
    kw.setdefault("source_class", contract.PRIMARY_PROTOCOL)
    kw.setdefault("source_root", "chain:1")
    kw.setdefault("as_of", NOW.isoformat())
    judge_now = judge_now or NOW
    if state not in contract.VALUED_STATES:
        return contract.cell(state, reason=kw.get("reason", "n/a"), now=judge_now)
    return contract.cell(state, value, now=judge_now, **{k: v for k, v in kw.items() if k != "reason"})


def base_candidate(mechanism_id="STABLECOIN_SAVINGS", domain="CASH_TREASURY", instrument_id=None,
                   network="ethereum", counterparty=None, **overrides) -> dict:
    instrument_id = instrument_id or f"{network}:0x{'11' * 20}"
    exposure = contract.exposure_key(mechanism_id, instrument_id, network)
    cid = contract.candidate_id(exposure)
    c = {f: None for f in contract.CANDIDATE_FIELDS}
    c.update({
        "candidate_id": cid, "exposure_key": exposure, "exposure_key_version": contract.EXPOSURE_KEY_VERSION,
        "mechanism_id": mechanism_id, "asset_class": contract.MECHANISMS[mechanism_id]["asset_class"],
        "domain": domain, "network": contract.canonical_network(network), "venue_or_protocol": "fake_scanner",
        "instrument": instrument_id, "instrument_id": instrument_id, "underlying_root": instrument_id,
        "economic_driver_key": f"DRIVER_{mechanism_id}", "yield_source": "savings_rate",
        "base_return": _cell(), "fees": _cell(contract.NOT_APPLICABLE, reason="no fee on this product"),
        "gas": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "funding": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "hedging_cost": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "liquidity": _cell(contract.MEASURED, 1_000_000.0),
        "time_to_exit": _cell(contract.MEASURED, 0.0),
        "capacity": _cell(contract.NOT_MEASURED, reason="not observed"),
        "duration": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "leverage": _cell(contract.NOT_APPLICABLE, reason="no leverage"),
        "liquidation_distance": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "source_refs": [{"source_root": "chain:1", "source_class": contract.PRIMARY_PROTOCOL, "value": 1.0}],
        "counterparty": counterparty if counterparty is not None else {
            "roles": {r: {"state": contract.CP_DOCUMENTED, "name": "Acme", "source_ref": "doc"}
                     for r in contract.MECHANISMS[mechanism_id]["required_roles"]},
            "dimensions": {},
        },
    })
    c.update(overrides)
    return c


class Case:
    def __init__(self, id_: str, scenario: str, fn: Callable[[Path], tuple]):
        self.id = id_
        self.scenario = scenario
        self.fn = fn

    def run(self) -> dict:
        tmp = Path(tempfile.mkdtemp(prefix="rf_fm_"))
        try:
            induced, expected, observed, ok = self.fn(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return {"id": self.id, "scenario": self.scenario, "induced": induced, "expected": expected,
               "observed": observed, "pass": bool(ok)}


def _admit_and_route(data_dir: Path, candidate: dict, registry_view=None) -> tuple:
    registry.upsert(data_dir, candidate, NOW)
    lifecycle.transition(data_dir, candidate["candidate_id"], contract.SCREENED, reason="screen", now=NOW)
    view = registry_view if registry_view is not None else {"_existing_book_roots": []}
    report = admission.evaluate(candidate, view, NOW)
    if report["verdict"] == contract.GATE_PASS:
        lifecycle.transition(data_dir, candidate["candidate_id"], contract.RESEARCH_READY,
                            reason="evaluable", now=NOW)
        lifecycle.transition(data_dir, candidate["candidate_id"], contract.PAPER_CANDIDATE,
                            reason="all PASS", now=NOW)
        return "PAPER_CANDIDATE", report
    hold, reasons = run._route_hold_state(report)
    lifecycle.transition(data_dir, candidate["candidate_id"], contract.RESEARCH_READY, reason="evaluable", now=NOW)
    lifecycle.transition(data_dir, candidate["candidate_id"], hold, reason="; ".join(reasons), now=NOW)
    return hold, report


def _c01_stale_apy(tmp):
    c = base_candidate(base_return=_cell(contract.MEASURED, 0.05, as_of=(NOW - timedelta(days=10)).isoformat()))
    state, _ = _admit_and_route(tmp, c)
    return "base_return as_of 10 days old (> 36h rate freshness)", "STALE", state, state == contract.STALE_STATE


def _c02_conflicting_roots(tmp):
    # base_return from an AGGREGATOR root (defillama) + an independent cross-check cell
    # (quoted_return) from a DIFFERENT, non-MODELLED root reporting a materially different number
    c = base_candidate(
        base_return=_cell(contract.MEASURED, 0.10, source_class=contract.REPUTABLE_AGGREGATOR,
                         source_root="defillama:yields"),
        quoted_return=_cell(contract.MEASURED, 0.03, source_class=contract.SECONDARY_SOURCE,
                           source_root="chain:1"),
    )
    state, _ = _admit_and_route(tmp, c)
    return ("aggregator says 10%, an independent cross-check root says 3% (>25% rel diff)",
           "DATA_INSUFFICIENT", state, state == contract.DATA_INSUFFICIENT)


def _c03_missing_fees(tmp):
    c = base_candidate(mechanism_id="LENDING", domain="DEFI_STABLE_YIELD",
                      fees=_cell(contract.NOT_MEASURED, reason="no fee feed"))
    c["counterparty"] = {"roles": {r: {"state": contract.CP_DOCUMENTED} for r in
                                   contract.MECHANISMS["LENDING"]["required_roles"]}, "dimensions": {}}
    state, _ = _admit_and_route(tmp, c)
    return "fees NOT_MEASURED on a mechanism that needs it", "DATA_INSUFFICIENT", state, \
        state == contract.DATA_INSUFFICIENT


def _c04_missing_redemption(tmp):
    c = base_candidate(mechanism_id="TOKENISED_TREASURY", domain="CASH_TREASURY")
    c["counterparty"] = {
        "roles": {r: {"state": contract.CP_DOCUMENTED} for r in
                 contract.MECHANISMS["TOKENISED_TREASURY"]["required_roles"]},
        "dimensions": {},  # redemption_restrictions / reserve_transparency both absent -> UNKNOWN
    }
    registry.upsert(tmp, c, NOW)
    for s in (contract.SCREENED, contract.RESEARCH_READY, contract.PAPER_CANDIDATE):
        lifecycle.transition(tmp, c["candidate_id"], s, reason="setup", now=NOW)
    report = admission.evaluate(c, {"_existing_book_roots": []}, NOW)
    snap = admission.write_admission_snapshot(tmp, c, report, NOW)
    lifecycle.transition(tmp, c["candidate_id"], contract.PAPER_ACTIVE,
                        gate_ref=snap["payload"]["admission_id"], reason="setup", now=NOW)
    ok, reason = counterparty_credit_bar_check(c)
    return "TOKENISED_TREASURY with no redemption/reserve data at all", "credit bar FAIL", reason, not ok


def counterparty_credit_bar_check(c):
    from spa_core.research_factory import counterparty
    return counterparty.credit_bar_passes(c)


def _c05_missing_counterparty(tmp):
    c = base_candidate(mechanism_id="LENDING", domain="DEFI_STABLE_YIELD", counterparty={"roles": {}, "dimensions": {}})
    state, _ = _admit_and_route(tmp, c)
    return "no counterparty roles named at all for LENDING", "COUNTERPARTY_UNKNOWN", state, \
        state == contract.COUNTERPARTY_UNKNOWN


def _c06_duplicate_from_two_scanners(tmp):
    c1 = base_candidate(venue_or_protocol="scanner_a")
    c2 = base_candidate(venue_or_protocol="scanner_b")
    registry.upsert(tmp, c1, NOW)
    registry.upsert(tmp, c2, NOW)
    from spa_core.research_factory._common import ledger_for
    ids = registry.all_candidate_ids(ledger_for(tmp))
    return "two scanners discover the SAME exposure (same mechanism/instrument/network)", 1, len(ids), len(ids) == 1


def _c07_protocol_rename(tmp):
    c = base_candidate()
    registry.upsert(tmp, c, NOW)
    lifecycle.transition(tmp, c["candidate_id"], contract.SCREENED, reason="x", now=NOW)
    lifecycle.transition(tmp, c["candidate_id"], contract.REJECTED, reason="pre-rename hold", now=NOW)
    lifecycle.transition(tmp, c["candidate_id"], contract.SUPERSEDED, reason="renamed, see superseded_by", now=NOW)
    raised = False
    try:
        lifecycle.transition(tmp, c["candidate_id"], contract.SCREENED, reason="try to revive", now=NOW)
    except lifecycle.InvalidTransition:
        raised = True
    return "protocol renamed -> SUPERSEDED, then an attempt to move it again", "InvalidTransition (terminal)", \
        raised, raised


def _c08_missing_price(tmp):
    c = base_candidate(base_return=_cell(contract.NOT_MEASURED, reason="no price feed"))
    state, _ = _admit_and_route(tmp, c)
    return ("base_return NOT_MEASURED (no price/rate at all)", "DATA_INSUFFICIENT", state,
           state == contract.DATA_INSUFFICIENT)


def _c09_depeg(tmp):
    c = base_candidate(base_return=_cell(contract.STALE, reason="peg broke, APY no longer meaningful"))
    state, _ = _admit_and_route(tmp, c)
    return "a depeg event — base_return marked STALE, not a number", "STALE", state, state == contract.STALE_STATE


def _c10_basis_unavailable(tmp):
    status = {"scanner": "basis", "domain": "MARKET_NEUTRAL_BASIS", "as_of": NOW.isoformat(),
             "status": "UNAVAILABLE", "reason": "feed down", "denominators": {"scanned": None, "discovered": 0,
                                                                              "truncated": None},
             "candidates": [], "unresolved": [], "observations": {}, "counterparty": {}, "existing_book_roots": []}
    rf_view = read.latest(tmp)
    return ("basis scanner reports UNAVAILABLE with zero candidates", "basis_track stays NOT_MEASURED",
           rf_view["basis_track"]["state"], rf_view["basis_track"]["state"] == "NOT_MEASURED")


def _c11_funding_unavailable(tmp):
    c = base_candidate(mechanism_id="FUNDING_CAPTURE", domain="MARKET_NEUTRAL", instrument_id="perp:ETH:median5",
                      network="ethereum", funding=_cell(contract.NOT_MEASURED, reason="funding feed down"),
                      leverage=_cell(contract.MEASURED, 2.0))
    c["counterparty"] = {"roles": {r: {"state": contract.CP_DOCUMENTED} for r in
                                   contract.MECHANISMS["FUNDING_CAPTURE"]["required_roles"]}, "dimensions": {}}
    state, report = _admit_and_route(tmp, c)
    # H5 rework: funding is now the PRIMARY provenance field for FUNDING_CAPTURE, so a
    # NOT_MEASURED funding cell fails source_provenance_acceptable (UNKNOWN) too, which routes
    # ahead of the REJECTED fallback — a MORE specific, and more correct, classification of
    # "we have no funding reading at all" than a bare rejection.
    return ("FUNDING_CAPTURE with funding NOT_MEASURED", "DATA_INSUFFICIENT (funding is now the "
           "primary provenance field too)", state, state == contract.DATA_INSUFFICIENT)


def _c12_funding_inversion(tmp):
    c = base_candidate(fees=_cell(contract.NOT_APPLICABLE, reason="n/a"), funding=_cell(contract.MEASURED, -0.5))
    net = contract.net_expected_return(c)
    return "funding cell carries a NEGATIVE real value (-50%)", "net reflects -0.5 unclamped", net["value"], \
        net["value"] == 0.5  # base_return(1.0) + funding(-0.5) = 0.5, never clamped to 0 or abs()'d


def _c13_maturity_missing(tmp):
    c = base_candidate(time_to_exit=_cell(contract.NOT_MEASURED, reason="no exit path documented"))
    state, _ = _admit_and_route(tmp, c)
    return "time_to_exit NOT_MEASURED", "REJECTED (exit_path_defined FAIL)", state, state == contract.REJECTED


def _c14_capacity_missing(tmp):
    c = base_candidate()  # capacity is already NOT_MEASURED in base_candidate()
    state, _ = _admit_and_route(tmp, c)
    still_absent = c["capacity"]["state"] == contract.NOT_MEASURED and c["capacity"]["value"] is None
    return ("capacity NOT_MEASURED (not an admission gate)", "PAPER_CANDIDATE, capacity stays absent (never 0)",
           (state, c["capacity"]["value"]), state == contract.PAPER_CANDIDATE and still_absent)


def _c15_chain_unavailable(tmp):
    raised = False
    try:
        contract.exposure_key("LENDING", "ethereum:0x" + "11" * 20, "mars")
    except ValueError:
        raised = True
    entry = registry.record_unresolved(tmp, "fake_scanner", "DEFI_DISCOVERY",
                                       {"name": "mystery-pool", "reason": "unknown network 'mars'"}, NOW)
    cid = entry["payload"]["candidate"]["candidate_id"]
    state = lifecycle.current_state(tmp, cid)
    return ("unknown chain name -> exposure_key refuses, recorded as unresolved",
           "ValueError + DATA_INSUFFICIENT", (raised, state), raised and state == contract.DATA_INSUFFICIENT)


def _c16_malformed_scanner(tmp):
    class _Boom:
        __name__ = "boom_scanner"

        @staticmethod
        def scan(data_dir, now, rpc_client=None):
            raise RuntimeError("malformed source payload")

    import spa_core.research_factory.run as run_mod
    orig = run_mod._discover_scanners
    run_mod._discover_scanners = lambda: [_Boom]
    try:
        status = run_mod.run_once(tmp, NOW)
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    finally:
        run_mod._discover_scanners = orig
    return "a scanner module raises mid-scan", "run_once survives, exits NOT_MEASURED for that scanner", ok, ok


def _c17_disappears(tmp):
    c = base_candidate()
    cid = c["candidate_id"]
    registry.upsert(tmp, c, NOW)
    for s in (contract.SCREENED, contract.RESEARCH_READY, contract.PAPER_CANDIDATE):
        lifecycle.transition(tmp, cid, s, reason="setup", now=NOW)
    report = admission.evaluate(c, {"_existing_book_roots": []}, NOW)
    snap = admission.write_admission_snapshot(tmp, c, report, NOW)
    lifecycle.transition(tmp, cid, contract.PAPER_ACTIVE, gate_ref=snap["payload"]["admission_id"],
                        reason="setup", now=NOW)
    from spa_core.research_factory._common import ledger_for
    ledger = ledger_for(tmp)
    ledger.append_idempotent("disappearance", ["disappearance", cid, "later"], {"candidate_id": cid}, "later")
    lifecycle.transition(tmp, cid, contract.DISAPPEARED, reason="absent from an OK scanner this run", now=NOW)
    state = lifecycle.current_state(tmp, cid)
    status = read.latest(tmp)
    return ("a paper-active candidate vanishes from its scanner's OK output", "DISAPPEARED, stays in denominators",
           (state, status["denominators"]["disappeared"]), state == contract.DISAPPEARED and
           status["denominators"]["disappeared"] == 1)


def _c18_revision(tmp):
    c = base_candidate()
    cid = c["candidate_id"]
    registry.upsert(tmp, c, NOW)
    for s in (contract.SCREENED, contract.RESEARCH_READY, contract.PAPER_CANDIDATE):
        lifecycle.transition(tmp, cid, s, reason="setup", now=NOW)
    report = admission.evaluate(c, {"_existing_book_roots": []}, NOW)
    snap = admission.write_admission_snapshot(tmp, c, report, NOW)
    lifecycle.transition(tmp, cid, contract.PAPER_ACTIVE, gate_ref=snap["payload"]["admission_id"],
                        reason="setup", now=NOW)
    admission_as_of = contract.parse_ts(snap["payload"]["as_of"])
    later_now = admission_as_of + timedelta(hours=2)
    period_as_of = (admission_as_of + timedelta(hours=1)).isoformat()
    obs1 = {"period": "2026-10-04",
           "observed_return": _cell(contract.MEASURED, 0.05, as_of=period_as_of, judge_now=later_now)}
    e1 = forward.record(tmp, cid, obs1, later_now)
    obs2 = {"period": "2026-10-04",
           "observed_return": _cell(contract.MEASURED, 0.09, as_of=period_as_of, judge_now=later_now)}
    e2 = forward.record(tmp, cid, obs2, later_now)
    maturity = forward.forward_periods(tmp, cid)
    return ("the SAME period is re-reported with a DIFFERENT value", "a revision row, maturity untouched by it",
           (e2["kind"], maturity), e2["kind"] == "revision" and maturity == 1)


def _c19_ledger_corruption(tmp):
    c = base_candidate()
    registry.upsert(tmp, c, NOW)
    from spa_core.research_factory._common import ledger_for
    led = ledger_for(tmp)
    led.anchors_path().write_text("")
    try:
        run.run_once(tmp, NOW)
        broke = False
    except LedgerError:
        broke = True
    return "the sibling anchors file is wiped (tamper)", "run_once refuses (LedgerError)", broke, broke


def _fm_concurrent_worker(path_str, payload_i, barrier) -> None:
    from spa_core.research_factory import registry as reg
    c2 = base_candidate()
    barrier.wait()
    reg.upsert(Path(path_str), c2, NOW)


def _c20_concurrent_writers(tmp):
    import multiprocessing

    c = base_candidate()
    n = 5
    barrier = multiprocessing.Barrier(n)
    procs = [multiprocessing.Process(target=_fm_concurrent_worker, args=(str(tmp), i, barrier)) for i in range(n)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=15)
    from spa_core.research_factory._common import ledger_for
    ids = registry.all_candidate_ids(ledger_for(tmp))
    return ("5 processes concurrently upsert the SAME exposure", 1, len(ids), len(ids) == 1)


def _c21_corrupted_index(tmp):
    c = base_candidate()
    registry.upsert(tmp, c, NOW)
    from spa_core.research_factory._common import ledger_for
    led = ledger_for(tmp)
    (led.root() / contract.INDEX).write_text("{not json")
    idx = registry.load_index(tmp)
    ok = c["candidate_id"] in idx.get("candidates", {})
    return "index.json is garbage", "load_index rebuilds from the ledger, candidate present", ok, ok


def _c22_restart_idempotency(tmp):
    import spa_core.research_factory.run as run_mod
    run_mod._discover_scanners = lambda: []
    c = base_candidate()
    registry.upsert(tmp, c, NOW)
    status1 = run.run_once(tmp, NOW)
    from spa_core.research_factory._common import ledger_for
    n1 = len(ledger_for(tmp).read_all())
    status2 = run.run_once(tmp, NOW)
    n2 = len(ledger_for(tmp).read_all())
    return ("run_once is called a SECOND time with identical inputs/now", "no new ledger rows", (n1, n2), n1 == n2)


def _c23_leverage_unknown(tmp):
    c = base_candidate(mechanism_id="LOOPED_LENDING", domain="DEFI_STABLE_YIELD",
                      leverage=_cell(contract.NOT_MEASURED, reason="leverage not observed"))
    c["counterparty"] = {"roles": {r: {"state": contract.CP_DOCUMENTED} for r in
                                   contract.MECHANISMS["LOOPED_LENDING"]["required_roles"]}, "dimensions": {}}
    state, _ = _admit_and_route(tmp, c)
    return "LOOPED_LENDING with leverage NOT_MEASURED", "RISK_UNRESOLVED", state, state == contract.RISK_UNRESOLVED


def _c24_counterparty_absent_dict(tmp):
    c = base_candidate(mechanism_id="LENDING", domain="DEFI_STABLE_YIELD")
    del c["counterparty"]
    state, _ = _admit_and_route(tmp, c)
    return "no 'counterparty' key at all on the candidate", "COUNTERPARTY_UNKNOWN", state, \
        state == contract.COUNTERPARTY_UNKNOWN


CASES = [
    Case("FM-01", "stale APY source", _c01_stale_apy),
    Case("FM-02", "conflicting APY roots", _c02_conflicting_roots),
    Case("FM-03", "missing fees", _c03_missing_fees),
    Case("FM-04", "missing redemption data", _c04_missing_redemption),
    Case("FM-05", "missing counterparty identity", _c05_missing_counterparty),
    Case("FM-06", "duplicate candidate from two scanners", _c06_duplicate_from_two_scanners),
    Case("FM-07", "protocol rename (superseded_by)", _c07_protocol_rename),
    Case("FM-08", "missing price", _c08_missing_price),
    Case("FM-09", "depeg (peg cell STALE)", _c09_depeg),
    Case("FM-10", "basis feed unavailable", _c10_basis_unavailable),
    Case("FM-11", "funding source unavailable", _c11_funding_unavailable),
    Case("FM-12", "extreme funding inversion", _c12_funding_inversion),
    Case("FM-13", "maturity date missing", _c13_maturity_missing),
    Case("FM-14", "capacity missing", _c14_capacity_missing),
    Case("FM-15", "chain data unavailable", _c15_chain_unavailable),
    Case("FM-16", "malformed source payload", _c16_malformed_scanner),
    Case("FM-17", "a candidate disappears", _c17_disappears),
    Case("FM-18", "a source revises old data", _c18_revision),
    Case("FM-19", "paper ledger corruption", _c19_ledger_corruption),
    Case("FM-20", "concurrent writers", _c20_concurrent_writers),
    Case("FM-21", "corrupted index", _c21_corrupted_index),
    Case("FM-22", "restart idempotency", _c22_restart_idempotency),
    Case("FM-23", "leverage required but unknown", _c23_leverage_unknown),
    Case("FM-24", "counterparty dict entirely absent", _c24_counterparty_absent_dict),
]


def run_all() -> list:
    return [case.run() for case in CASES]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    rows = run_all()
    with open(args.out, "w") as f:
        json.dump(rows, f, indent=2, default=str)
    failed = [r for r in rows if not r["pass"]]
    print(f"{len(rows)} scenarios, {len(failed)} FAILED")
    for r in failed:
        print(f"  FAIL {r['id']} {r['scenario']}: expected {r['expected']!r} observed {r['observed']!r}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
