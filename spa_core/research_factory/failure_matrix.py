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

from spa_core.research_factory import admission, contract, decision, dedup, eligibility, forward, lifecycle, read, \
    registry, run
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
        # unit="fraction" declares this an ANNUAL rate (contract.ANNUAL_RATE_UNITS) — contract.
        # net_expected_return() is now unit-aware (ADR-564 integration finding, a live run netted
        # a one-off fee against an annual rate unchecked and produced net=-2697); a unit-less
        # fixture would make every candidate built here honestly NOT_MEASURED instead.
        "base_return": _cell(unit="fraction"), "fees": _cell(contract.NOT_APPLICABLE, reason="no fee on this product"),
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


def _v2_baseline_overrides() -> dict:
    """A v2_evidence baseline that clears every dimension EXCEPT the ones this module's
    ``base_candidate()``/v1 cells themselves speak to (RETURN/COST/COUNTERPARTY/LIQUIDITY/
    PRIMARY_IDENTITY for a perp) — so each scenario's OWN induced v1-cell defect is the thing
    that fails, not an unrelated gap this legacy fixture never set up (``identity_verified`` is
    FIRST in ``evidence_contract.ADMISSION_V2_GATES`` and would otherwise mask every other
    scenario behind a single generic "no on-chain identity" finding). Deliberately excludes:
      * "cost_components" — ``run._default_v2_evidence`` already derives it from the candidate's
        OWN fees/gas/hedging_cost cells, which IS several scenarios' induced defect (FM-03);
      * every "return_*" key — ``run._default_v2_evidence`` derives ``return_last_change_at``
        from the candidate's OWN base_return/funding ``as_of`` (when no forward rows exist yet,
        true for every fresh candidate here), which IS the induced defect for FM-01/09/11 (a
        fixed "now" here would silently make every staleness scenario look fresh)."""
    from spa_core.tests import _research_evidence_v2_fixtures as v2fx
    baseline = v2fx.all_strong_v2_evidence(NOW)
    # re-review H5 residual: "return_primary_origin" is KEPT (the fixture's registered issuer origin) — it
    # carries no time, so it cannot mask a staleness scenario, and a `chain:` source_root no longer counts
    # as an independent group for a rate claim; dropping it would fail every scenario on independence
    # instead of on the defect it induces.
    for key in ("cost_components", "return_family", "return_last_change_at", "return_cross_checks"):
        baseline.pop(key, None)
    return baseline


def _admit_and_route(data_dir: Path, candidate: dict, registry_view=None) -> tuple:
    """ADR-564 binding #1 (Round 5 live-validation finding, 2026-10-04): v1's
    ``admission.evaluate()`` is DISPLAY-ONLY now and ``run._route_hold_state`` no longer
    exists — the lifecycle follows Sherlock's decision alone (``run._sherlock_review_candidate``),
    exactly as ``run.run_once`` drives it (``run._process_candidate`` walks a fresh candidate to
    RESEARCH_READY and STOPS there; Sherlock's own admit walk takes the RESEARCH_READY ->
    PAPER_CANDIDATE step). This helper mirrors that real path for a synthetic v1-shaped
    candidate, so each scenario below exercises the SAME routing production code does."""
    cid = candidate["candidate_id"]
    registry.upsert(data_dir, candidate, NOW)
    lifecycle.transition(data_dir, cid, contract.SCREENED, reason="screen", now=NOW)
    lifecycle.transition(data_dir, cid, contract.RESEARCH_READY, reason="evaluable", now=NOW)
    existing_book_roots = (registry_view or {}).get("_existing_book_roots") or []
    v2_overrides = {cid: _v2_baseline_overrides()}
    # post-implementation review H5/H6 (2026-10-04): evidence_contract.origin_group now fails
    # CLOSED on an unregistered origin (no "own group" for an unknown name) — the candidate's
    # default source_root ("chain:1") needs a real registry entry or source_independence_sufficient
    # honestly fails for every scenario here, masking each one's OWN induced defect.
    from spa_core.tests._research_evidence_v2_fixtures import DEFAULT_REGISTRY
    run._sherlock_review_candidate(data_dir, cid, candidate, existing_book_roots, {}, DEFAULT_REGISTRY, [],
                                   v2_overrides, NOW)
    state = lifecycle.current_state(data_dir, cid)
    outcome = decision.latest_decision(data_dir, cid)
    return state, outcome


def _c01_stale_apy(tmp):
    # unit="fraction" (ANNUAL rate, contract.ANNUAL_RATE_UNITS) — omitting it here would make
    # net_expected_return() (unit-aware, ADR-564) itself NOT_MEASURED, failing net_return_computable
    # BEFORE data_fresh ever gets evaluated (admission_v2's gates run in ADMISSION_V2_GATES order,
    # and net_return_computable is #4, data_fresh is #6) — masking the STALE scenario entirely.
    c = base_candidate(base_return=_cell(contract.MEASURED, 0.05, unit="fraction",
                                        as_of=(NOW - timedelta(days=10)).isoformat()))
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
    # name/source_ref present (unlike a bare {"state": ...}) so migrate_role_from_v1 can
    # actually promote this role past CP_UNKNOWN — otherwise COUNTERPARTY itself grades UNKNOWN
    # and masks the fees-specific defect this scenario is actually about.
    c["counterparty"] = {"roles": {r: {"state": contract.CP_DOCUMENTED, "name": "Acme", "source_ref": "doc"}
                                   for r in contract.MECHANISMS["LENDING"]["required_roles"]}, "dimensions": {}}
    state, _ = _admit_and_route(tmp, c)
    return "fees NOT_MEASURED on a mechanism that needs it", "DATA_INSUFFICIENT", state, \
        state == contract.DATA_INSUFFICIENT



def _v2_snapshot_row(data_dir, admission_id):
    """The real paper-admission/2 ledger row for ``admission_id`` (as_of etc. exactly as written)."""
    from spa_core.research_factory._common import ledger_for
    for e in ledger_for(data_dir).read_all():
        p = e.get("payload")
        if isinstance(p, dict) and p.get("admission_id") == admission_id and e.get("kind") == "paper_admission_v2":
            return e
    raise LookupError(f"no paper_admission_v2 row for {admission_id}")

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
    # ADR-564 binding #1: the v1 snapshot is refused; admission goes through a real Sherlock
    # ADMIT decision over an all-STRONG bundle (this scenario tests something other than grading)
    from spa_core.tests._research_evidence_v2_fixtures import v2_admission_id_for
    snap = _v2_snapshot_row(tmp, v2_admission_id_for(tmp, c, NOW))
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
    # Round 5 (ADR-564 binding #1) re-verification, 2026-10-04: with base_return NOT_MEASURED,
    # grade_return returns UNKNOWN (never STALE — STALE means "went old", this is "never had
    # one") and _data_fresh (GATE_INPUTS RETURN, FORWARD_SERIES) reads UNKNOWN -> GATE_UNKNOWN.
    # "data_fresh" IS in run._GATE_DIM_HOLD (-> STALE_STATE) while "return_source_verified"/
    # "net_return_computable" (the gates actually failing FOR THE RIGHT REASON) are not, so
    # data_fresh — earlier in evidence_contract.ADMISSION_V2_GATES order — wins the routing.
    # Re-targeting GATE_DIM_HOLD's data_fresh/UNKNOWN-vs-STALE distinction is a separate,
    # un-asked-for change; this scenario's VERIFIED real outcome is STALE_STATE, not DATA_INSUFFICIENT.
    # RM-EVIDENCE-01 live-run fix: freshness now routes by VERDICT — data_fresh UNKNOWN ("never had one") is
    # DATA_INSUFFICIENT, only a judged-too-old source (FAIL) is STALE. The quirk described above is gone, so
    # this scenario's expectation follows the comment's own reasoning (intentional change, journal W40).
    return ("base_return NOT_MEASURED (no price/rate at all)", "DATA_INSUFFICIENT (never had a price — "
           "not STALE)", state, state == contract.DATA_INSUFFICIENT)


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
    c["counterparty"] = {"roles": {r: {"state": contract.CP_DOCUMENTED, "name": "Acme", "source_ref": "doc"}
                                   for r in contract.MECHANISMS["FUNDING_CAPTURE"]["required_roles"]},
                        "dimensions": {}}
    state, report = _admit_and_route(tmp, c)
    # Round 5 (ADR-564 binding #1) re-verification, 2026-10-04: same root cause as FM-08's own
    # comment — funding NOT_MEASURED makes grade_return UNKNOWN (never measured, not stale), so
    # _data_fresh reads GATE_UNKNOWN and (being earlier in ADMISSION_V2_GATES order AND the only
    # one of the relevant failing gates present in run._GATE_DIM_HOLD) routes to STALE_STATE.
    # RM-EVIDENCE-01 live-run fix (see FM-08): UNKNOWN freshness ⇒ DATA_INSUFFICIENT (intentional, journal W40)
    return ("FUNDING_CAPTURE with funding NOT_MEASURED", "DATA_INSUFFICIENT (funding never measured — not STALE)",
           state, state == contract.DATA_INSUFFICIENT)


def _c12_funding_inversion(tmp):
    c = base_candidate(fees=_cell(contract.NOT_APPLICABLE, reason="n/a"),
                      funding=_cell(contract.MEASURED, -0.5, unit="fraction"))
    net = contract.net_expected_return(c)
    return "funding cell carries a NEGATIVE real value (-50%)", "net reflects -0.5 unclamped", net["value"], \
        net["value"] == 0.5  # base_return(1.0) + funding(-0.5) = 0.5, never clamped to 0 or abs()'d


def _c13_maturity_missing(tmp):
    c = base_candidate(time_to_exit=_cell(contract.NOT_MEASURED, reason="no exit path documented"))
    state, _ = _admit_and_route(tmp, c)
    # Round 5 (ADR-564 binding #1) re-verification, 2026-10-04: admission_v2._exit_path_defined
    # (GATE_INPUTS LIQUIDITY, REDEMPTION, paper_mode) replaced v1's OWN same-named gate and never
    # reads the v1 candidate's time_to_exit cell at all — v1's admission.evaluate() is display-only
    # now (binding #1) and its own exit_path_defined verdict never reaches the lifecycle. With
    # LIQUIDITY/REDEMPTION both otherwise clear, this candidate legitimately clears every gate and
    # reaches PAPER_ACTIVE — exactly the "ADMIT now takes effect" fix this round made (Issue #1).
    return ("time_to_exit NOT_MEASURED (a v1-only field v2's exit_path_defined never reads)",
           "PAPER_ACTIVE (LIQUIDITY/REDEMPTION are what v2 actually gates on)", state,
           state == contract.PAPER_ACTIVE)


def _c14_capacity_missing(tmp):
    c = base_candidate()  # capacity is already NOT_MEASURED in base_candidate()
    state, _ = _admit_and_route(tmp, c)
    still_absent = c["capacity"]["state"] == contract.NOT_MEASURED and c["capacity"]["value"] is None
    # Round 5 (ADR-564 binding #1) re-verification, 2026-10-04: capacity was never gated, v1 OR
    # v2 — the only thing that changed is that ADMIT now actually takes effect (Issue #1 of this
    # round), so a fully-clear candidate reaches PAPER_ACTIVE instead of stopping at
    # PAPER_CANDIDATE. capacity staying honestly absent (never defaulted to 0) is still the point.
    return ("capacity NOT_MEASURED (not an admission gate)", "PAPER_ACTIVE, capacity stays absent (never 0)",
           (state, c["capacity"]["value"]), state == contract.PAPER_ACTIVE and still_absent)


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
    # ADR-564 binding #1: the v1 snapshot is refused; admission goes through a real Sherlock
    # ADMIT decision over an all-STRONG bundle (this scenario tests something other than grading)
    from spa_core.tests._research_evidence_v2_fixtures import v2_admission_id_for
    snap = _v2_snapshot_row(tmp, v2_admission_id_for(tmp, c, NOW))
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
    # ADR-564 binding #1: the v1 snapshot is refused; admission goes through a real Sherlock
    # ADMIT decision over an all-STRONG bundle (this scenario tests something other than grading)
    from spa_core.tests._research_evidence_v2_fixtures import v2_admission_id_for
    snap = _v2_snapshot_row(tmp, v2_admission_id_for(tmp, c, NOW))
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
    c["counterparty"] = {"roles": {r: {"state": contract.CP_DOCUMENTED, "name": "Acme", "source_ref": "doc"}
                                   for r in contract.MECHANISMS["LOOPED_LENDING"]["required_roles"]},
                        "dimensions": {}}
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
