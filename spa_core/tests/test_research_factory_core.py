"""Core behavioural tests for the Research Factory (ADR-560, RM-EXPAND-01, Package A).

Time is INJECTED throughout: every judgement in this file is made against the single anchor
``NOW`` (or an offset derived from it), passed to the code under test as ``now=``. Nothing here
asks the wall clock anything.
# FROZEN-DATE-OK: injected-clock — the anchor NOW (and every NOW + timedelta(...) built from it)
# is passed as the `now=`/positional `now` argument to every lifecycle/admission/forward/registry
# call in this file; no assertion compares a literal date to the real clock.

RESEARCH / PAPER only — see spa_core/research_factory/contract.py.
"""
from __future__ import annotations

import ast
import importlib
import json
import multiprocessing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.research_factory import (
    admission, contract, counterparty, dedup, eligibility, forward, lifecycle, read, registry, run,
)
from spa_core.research_factory._common import ledger_for
from spa_core.utils.hash_ledger import DuplicateKey, LedgerError, RunLocked

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


def make_candidate(mechanism_id="STABLECOIN_SAVINGS", domain="CASH_TREASURY", instrument_id=None,
                   network="ethereum", counterparty_data=None, **overrides) -> dict:
    instrument_id = instrument_id or f"{network}:0x{'22' * 20}"
    exposure = contract.exposure_key(mechanism_id, instrument_id, network)
    cid = contract.candidate_id(exposure)
    c = {f: None for f in contract.CANDIDATE_FIELDS}
    c.update({
        "candidate_id": cid, "exposure_key": exposure, "exposure_key_version": contract.EXPOSURE_KEY_VERSION,
        "mechanism_id": mechanism_id, "asset_class": contract.MECHANISMS[mechanism_id]["asset_class"],
        "domain": domain, "network": contract.canonical_network(network), "venue_or_protocol": "test_scanner",
        "instrument": instrument_id, "instrument_id": instrument_id, "underlying_root": instrument_id,
        "economic_driver_key": f"DRIVER_{mechanism_id}", "yield_source": "savings_rate",
        "base_return": _cell(unit="fraction"), "fees": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "gas": _cell(contract.NOT_APPLICABLE, reason="n/a"), "funding": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "hedging_cost": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "liquidity": _cell(contract.MEASURED, 1_000_000.0), "time_to_exit": _cell(contract.MEASURED, 0.0),
        "capacity": _cell(contract.NOT_MEASURED, reason="not observed"),
        "duration": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "leverage": _cell(contract.NOT_APPLICABLE, reason="no leverage"),
        "liquidation_distance": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "source_refs": [{"source_root": "chain:1", "source_class": contract.PRIMARY_PROTOCOL, "value": 1.0}],
        "counterparty": counterparty_data if counterparty_data is not None else {
            "roles": {r: {"state": contract.CP_DOCUMENTED, "name": "Acme"} for r in
                     contract.MECHANISMS[mechanism_id]["required_roles"]},
            "dimensions": {},
        },
    })
    c.update(overrides)
    return c


def _admit_to_paper_active(data_dir: Path, candidate: dict, now: datetime = NOW) -> str:
    """Walks a valid candidate all the way to PAPER_ACTIVE via the real gated transitions."""
    cid = candidate["candidate_id"]
    registry.upsert(data_dir, candidate, now)
    for s in (contract.SCREENED, contract.RESEARCH_READY, contract.PAPER_CANDIDATE):
        lifecycle.transition(data_dir, cid, s, reason="setup", now=now)
    report = admission.evaluate(candidate, {"_existing_book_roots": []}, now)
    assert report["verdict"] == contract.GATE_PASS, report
    snap = admission.write_admission_snapshot(data_dir, candidate, report, now)
    admission_id = snap["payload"]["admission_id"]
    lifecycle.transition(data_dir, cid, contract.PAPER_ACTIVE, gate_ref=admission_id, reason="setup", now=now)
    return admission_id


# ── 1. missing return != 0 ──────────────────────────────────────────────────────────────────

def test_missing_return_is_never_zero(tmp_path):
    c = make_candidate(base_return=_cell(contract.NOT_MEASURED, reason="no feed"))
    assert c["base_return"]["value"] is None
    net = contract.net_expected_return(c)
    assert net["state"] == contract.NOT_MEASURED
    assert net["value"] is None  # never silently 0.0


# ── 2. missing counterparty != safe ─────────────────────────────────────────────────────────

def test_missing_counterparty_is_not_safe(tmp_path):
    c = make_candidate(mechanism_id="LENDING", domain="DEFI_STABLE_YIELD", counterparty_data={"roles": {}, "dimensions": {}})
    summary = counterparty.summarize(c)
    assert set(contract.MECHANISMS["LENDING"]["required_roles"]) <= set(summary["required_roles_missing"])
    gate = admission._counterparty_named(c)
    assert gate["verdict"] != contract.GATE_PASS


def test_unknown_counterparty_never_counts_as_safe_in_cio_credit_bar():
    c = make_candidate(mechanism_id="TOKENISED_TREASURY", domain="CASH_TREASURY",
                      counterparty_data={"roles": {r: {"state": contract.CP_DOCUMENTED} for r in
                                                      contract.MECHANISMS["TOKENISED_TREASURY"]["required_roles"]},
                                        "dimensions": {}})
    ok, reason = counterparty.credit_bar_passes(c)
    assert ok is False, reason


# ── 3. stale cannot become fresh ────────────────────────────────────────────────────────────

def test_stale_cannot_become_fresh_by_waiting_without_new_data(tmp_path):
    c = make_candidate(base_return=_cell(contract.MEASURED, 0.05, as_of=(NOW - timedelta(hours=40)).isoformat()))
    assert contract.is_fresh(c["base_return"], NOW) is False
    later = NOW + timedelta(days=5)
    assert contract.is_fresh(c["base_return"], later) is False  # ages further, never "becomes fresh"


# ── 4. advertised != realised ───────────────────────────────────────────────────────────────

def test_advertised_only_fails_not_advertised_only_gate():
    c = make_candidate(base_return=_cell(contract.DOCUMENTED, 0.20, source_class=contract.ISSUER_CLAIM))
    gate = admission._not_advertised_only(c)
    assert gate["verdict"] == contract.GATE_FAIL


def test_realised_return_without_independent_index_is_modelled_not_a_number(tmp_path):
    c = make_candidate()
    _admit_to_paper_active(tmp_path, c)
    kind, cell_ = forward.realised_return(tmp_path, c["candidate_id"])
    assert kind == contract.RETURN_MODELLED
    assert cell_["state"] == contract.NOT_MEASURED
    assert cell_["value"] is None


# ── 5. gross != net ──────────────────────────────────────────────────────────────────────────

def test_net_expected_return_subtracts_costs_gross_is_not_net():
    c = make_candidate(mechanism_id="LENDING", domain="DEFI_STABLE_YIELD",
                      fees=_cell(contract.MEASURED, 0.01), gas=_cell(contract.MEASURED, 0.002))
    net = contract.net_expected_return(c)
    assert net["value"] == pytest.approx(1.0 - 0.01 - 0.002)
    assert net["value"] != c["base_return"]["value"]


def test_incentive_return_never_added_to_net():
    c = make_candidate(incentive_return=_cell(contract.MEASURED, 5.0))
    net = contract.net_expected_return(c)
    assert net["value"] == pytest.approx(1.0)  # the 5.0 incentive never leaks in


# ── 6. economic dedup ────────────────────────────────────────────────────────────────────────

def test_economic_dedup_shared_exposure_key():
    # candidate_id is normally DERIVED from exposure_key, so two records sharing an exposure_key
    # share a candidate_id too (registry.upsert already collapses that case to one row). This
    # gate is the DEFENSIVE check for the case that should never happen but must still be
    # caught: two DIFFERENT candidate_ids somehow carrying the SAME exposure_key (e.g. data
    # corruption, an EXPOSURE_KEY_VERSION migration gone wrong) — never silently admitted.
    c1 = make_candidate()
    c2 = dict(c1)
    c2["candidate_id"] = "deliberately-different-id"
    verdict, reason = dedup.no_duplicate_exposure(c2, [c1], [])
    assert verdict == contract.GATE_FAIL, reason


def test_economic_dedup_shared_underlying_root_with_paper_state_candidate():
    c1 = make_candidate(instrument_id="ethereum:0x" + "aa" * 20)
    c1["admission_state"] = contract.PAPER_ACTIVE
    c2 = make_candidate(instrument_id="ethereum:0x" + "bb" * 20, underlying_root=c1["underlying_root"])
    verdict, reason = dedup.no_duplicate_exposure(c2, [c1], [])
    assert verdict == contract.GATE_FAIL, reason


def test_economic_dedup_against_live_book_roots():
    c = make_candidate()
    verdict, reason = dedup.no_duplicate_exposure(c, [], [c["underlying_root"]])
    assert verdict == contract.GATE_FAIL, reason


def test_shared_driver_key_is_a_correlation_group_not_a_block():
    c1 = make_candidate(instrument_id="ethereum:0x" + "cc" * 20, economic_driver_key="SKY_SSR")
    c2 = make_candidate(instrument_id="ethereum:0x" + "dd" * 20, economic_driver_key="SKY_SSR")
    groups = dedup.correlation_groups([c1, c2])
    assert groups["SKY_SSR"] == [c1["candidate_id"], c2["candidate_id"]]
    verdict, _ = dedup.no_duplicate_exposure(c2, [c1], [])
    assert verdict == contract.GATE_PASS  # a shared driver alone never blocks


def test_concurrent_discovery_dedup_real_multiprocessing(tmp_path):
    n = 6
    barrier = multiprocessing.Barrier(n)
    procs = [multiprocessing.Process(target=_concurrent_upsert_worker, args=(str(tmp_path), barrier))
            for _ in range(n)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=15)
        assert not p.is_alive()
    led = ledger_for(tmp_path)
    ids = registry.all_candidate_ids(led)
    assert len(ids) == 1
    v = led.verify()
    assert v["ok"], v


def _concurrent_upsert_worker(path_str: str, barrier) -> None:
    c = make_candidate()
    barrier.wait()
    registry.upsert(Path(path_str), c, NOW)


# ── 7. historical / backfill cannot create maturity ─────────────────────────────────────────

def test_backfill_observation_never_counts(tmp_path):
    c = make_candidate()
    _admit_to_paper_active(tmp_path, c)
    later = NOW + timedelta(hours=2)
    obs = {"period": "2026-10-04", "backfill": True,
          "observed_return": _cell(contract.MEASURED, 0.05, as_of=(NOW + timedelta(hours=1)).isoformat(),
                                   judge_now=later)}
    entry = forward.record(tmp_path, c["candidate_id"], obs, later)
    assert entry["payload"]["counted"] is False
    assert "backfill" in entry["payload"]["reason"]
    assert forward.forward_periods(tmp_path, c["candidate_id"]) == 0


def test_lookahead_period_before_admission_never_counts(tmp_path):
    c = make_candidate()
    admission_id = _admit_to_paper_active(tmp_path, c)
    admission_as_of = NOW
    obs = {"period": "2026-10-03",  # BEFORE admission
          "observed_return": _cell(contract.MEASURED, 0.05, as_of=(admission_as_of - timedelta(days=1)).isoformat(),
                                   judge_now=NOW)}
    entry = forward.record(tmp_path, c["candidate_id"], obs, NOW)
    assert entry["payload"]["counted"] is False
    assert forward.forward_periods(tmp_path, c["candidate_id"]) == 0


def test_re_admission_restarts_maturity_at_zero(tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    _admit_to_paper_active(tmp_path, c, NOW)
    t1 = NOW + timedelta(hours=2)
    obs1 = {"period": "2026-10-04",
           "observed_return": _cell(contract.MEASURED, 0.05, as_of=(NOW + timedelta(hours=1)).isoformat(),
                                    judge_now=t1)}
    forward.record(tmp_path, cid, obs1, t1)
    assert forward.forward_periods(tmp_path, cid) == 1

    # send it back to SCREENED and re-admit with a FRESH admission snapshot
    lifecycle.transition(tmp_path, cid, contract.REJECTED, reason="forced for test", now=t1)
    candidate2 = dict(c)
    candidate2["base_return"] = _cell(contract.MEASURED, 0.06, as_of=t1.isoformat(), judge_now=t1)
    registry.upsert(tmp_path, candidate2, t1)
    lifecycle.transition(tmp_path, cid, contract.SCREENED,
                        gate_ref={"prev_digest": "a", "new_digest": "b"}, reason="re-screen", now=t1)
    _admit_to_paper_active(tmp_path, candidate2, t1 + timedelta(hours=1))
    assert forward.forward_periods(tmp_path, cid) == 0


# ── 8. rejected candidate cannot become paper-active without a lifecycle transition ─────────

def test_rejected_candidate_requires_real_transitions_to_reach_paper_active(tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    registry.upsert(tmp_path, c, NOW)
    lifecycle.transition(tmp_path, cid, contract.SCREENED, reason="x", now=NOW)
    lifecycle.transition(tmp_path, cid, contract.REJECTED, reason="x", now=NOW)
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.transition(tmp_path, cid, contract.PAPER_ACTIVE, gate_ref="nonsense", reason="shortcut", now=NOW)
    assert lifecycle.current_state(tmp_path, cid) == contract.REJECTED


def test_paper_active_requires_a_real_pass_admission_snapshot(tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    registry.upsert(tmp_path, c, NOW)
    lifecycle.transition(tmp_path, cid, contract.SCREENED, reason="x", now=NOW)
    lifecycle.transition(tmp_path, cid, contract.RESEARCH_READY, reason="x", now=NOW)
    lifecycle.transition(tmp_path, cid, contract.PAPER_CANDIDATE, reason="x", now=NOW)
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.transition(tmp_path, cid, contract.PAPER_ACTIVE, gate_ref="made-up-id", reason="x", now=NOW)
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.transition(tmp_path, cid, contract.PAPER_ACTIVE, gate_ref=None, reason="x", now=NOW)


def test_paper_active_rejects_an_admission_id_for_a_different_candidate(tmp_path):
    c1 = make_candidate(instrument_id="ethereum:0x" + "ee" * 20)
    c2 = make_candidate(instrument_id="ethereum:0x" + "ff" * 20)
    admission_id_1 = _admit_to_paper_active(tmp_path, c1)
    registry.upsert(tmp_path, c2, NOW)
    lifecycle.transition(tmp_path, c2["candidate_id"], contract.SCREENED, reason="x", now=NOW)
    lifecycle.transition(tmp_path, c2["candidate_id"], contract.RESEARCH_READY, reason="x", now=NOW)
    lifecycle.transition(tmp_path, c2["candidate_id"], contract.PAPER_CANDIDATE, reason="x", now=NOW)
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.transition(tmp_path, c2["candidate_id"], contract.PAPER_ACTIVE, gate_ref=admission_id_1,
                            reason="borrow someone else's admission", now=NOW)


# MUTATION CHECK: with the admission-gate validator neutralised, the bypass above would SUCCEED —
# proving the test above is actually exercising the guard, not vacuously green.
def test_mutation_check_admission_gate_bypass_detectable(tmp_path, monkeypatch):
    c = make_candidate()
    cid = c["candidate_id"]
    registry.upsert(tmp_path, c, NOW)
    lifecycle.transition(tmp_path, cid, contract.SCREENED, reason="x", now=NOW)
    lifecycle.transition(tmp_path, cid, contract.RESEARCH_READY, reason="x", now=NOW)
    lifecycle.transition(tmp_path, cid, contract.PAPER_CANDIDATE, reason="x", now=NOW)
    monkeypatch.setattr(lifecycle, "_validate_admission_gate", lambda *a, **k: None)
    # with the guard neutralised, a bogus gate_ref now sails through — this is the RED state the
    # real (unpatched) guard prevents, confirming test_paper_active_requires_a_real_pass_admission
    # _snapshot above is a meaningful, guard-sensitive assertion.
    row = lifecycle.transition(tmp_path, cid, contract.PAPER_ACTIVE, gate_ref="made-up-id",
                              reason="bypass attempt", now=NOW)
    assert row["payload"]["to_state"] == contract.PAPER_ACTIVE  # the bypass succeeded under the mutation


# ── 9. paper cannot become CIO_ELIGIBLE without the evidence gate ──────────────────────────

def test_evidence_accumulating_cannot_jump_to_cio_eligible_without_gate(tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    _admit_to_paper_active(tmp_path, c)
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.transition(tmp_path, cid, contract.CIO_ELIGIBLE, gate_ref=None, reason="skip", now=NOW)
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.transition(tmp_path, cid, contract.CIO_ELIGIBLE,
                            gate_ref={"all_pass": True, "gates": {}}, reason="half-faked", now=NOW)


def test_cio_eligible_needs_every_gate_pass_not_just_most(tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    _admit_to_paper_active(tmp_path, c)
    lifecycle.transition(tmp_path, cid, contract.EVIDENCE_ACCUMULATING,
                        gate_ref=lifecycle.active_admission_id(tmp_path, cid), reason="setup", now=NOW)
    almost_all = {g: contract.GATE_PASS for g in contract.CIO_ELIGIBILITY_GATES}
    almost_all[next(iter(contract.CIO_ELIGIBILITY_GATES))] = contract.GATE_FAIL
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.transition(tmp_path, cid, contract.CIO_ELIGIBLE, gate_ref={"all_pass": True, "gates": almost_all},
                            reason="not quite all pass", now=NOW)


def test_eligibility_promotes_only_when_all_pass_demotes_on_any_failure(tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    _admit_to_paper_active(tmp_path, c)
    t1 = NOW + timedelta(hours=1)
    obs_period = NOW + timedelta(minutes=30)
    for i in range(contract.MIN_FORWARD_PERIODS_CIO):
        t_i = NOW + timedelta(hours=i + 1)
        obs = {"period": f"2026-10-{5 + i:02d}",
              "observed_return": _cell(contract.MEASURED, 0.05, as_of=t_i.isoformat(), judge_now=t_i)}
        forward.record(tmp_path, cid, obs, t_i)
        _process = lifecycle.current_state(tmp_path, cid)
        if _process == contract.PAPER_ACTIVE:
            lifecycle.transition(tmp_path, cid, contract.EVIDENCE_ACCUMULATING,
                                gate_ref=lifecycle.active_admission_id(tmp_path, cid), reason="x", now=t_i)
    assert forward.forward_periods(tmp_path, cid) >= contract.MIN_FORWARD_PERIODS_CIO
    final_now = NOW + timedelta(hours=contract.MIN_FORWARD_PERIODS_CIO + 1)
    report = eligibility.evaluate(tmp_path, registry.current_candidate(tmp_path, cid),
                                  {"_existing_book_roots": []}, final_now)
    # realised_vs_observed_consistent is UNKNOWN (no independent index) -> never all_pass
    assert report["gates"]["realised_vs_observed_consistent"]["verdict"] == contract.GATE_UNKNOWN
    assert report["all_pass"] is False


# MUTATION CHECK: force one CIO gate to always PASS and show a candidate that should NOT be
# eligible becomes eligible — proving eligibility.evaluate's all-gates-PASS aggregation matters.
def test_mutation_check_unknown_gate_forced_pass_wrongly_promotes(monkeypatch, tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    _admit_to_paper_active(tmp_path, c)
    lifecycle.transition(tmp_path, cid, contract.EVIDENCE_ACCUMULATING,
                        gate_ref=lifecycle.active_admission_id(tmp_path, cid), reason="x", now=NOW)
    monkeypatch.setattr(forward, "realised_return",
                       lambda *a, **k: (contract.RETURN_REALISED_PAPER, _cell(contract.MEASURED, 1.0, unit="fraction")))
    view = {"_existing_book_roots": []}
    report = eligibility.evaluate(tmp_path, registry.current_candidate(tmp_path, cid), view,
                                  NOW + timedelta(hours=1))
    # under the mutation, realised_vs_observed_consistent now reads PASS instead of UNKNOWN —
    # this is exactly the false-positive the real (unpatched) UNKNOWN-never-passes rule prevents
    assert report["gates"]["realised_vs_observed_consistent"]["verdict"] == contract.GATE_PASS


# ── 10. CIO view never lists OBSERVE_ONLY candidates as eligible ───────────────────────────

def test_cio_view_never_lists_observe_only_as_eligible(tmp_path):
    c = make_candidate(domain="TRADING_RESEARCH", mechanism_id="DIRECTIONAL_TREND",
                      instrument_id="engine:trading_research:btc-001", network="ethereum",
                      underlying_root="engine:trading_research:btc-001")
    registry.upsert(tmp_path, c, NOW)
    lifecycle.transition(tmp_path, c["candidate_id"], contract.OBSERVE_ONLY, reason="projected", now=NOW)
    run.run_once(tmp_path, NOW)  # writes status.json
    view = read.cio_view(tmp_path, NOW)
    assert c["candidate_id"] not in view["cio_eligible"]
    assert c["candidate_id"] in view["observe_only"]
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.transition(tmp_path, c["candidate_id"], contract.CIO_ELIGIBLE,
                            gate_ref={"all_pass": True, "gates": {g: contract.GATE_PASS for g in
                                                                  contract.CIO_ELIGIBILITY_GATES}},
                            reason="OBSERVE_ONLY may never move", now=NOW)


def test_cio_eligible_empty_when_read_model_stale(tmp_path):
    c = make_candidate()
    _admit_to_paper_active(tmp_path, c)
    run.run_once(tmp_path, NOW)
    much_later = NOW + timedelta(hours=contract.CIO_READ_MODEL_MAX_AGE_H + 1)
    view = read.cio_view(tmp_path, much_later)
    assert view["cio_eligible"] == []
    assert view["state"] == "STALE"


def test_cio_view_reflects_a_write_after_the_last_run_immediately(tmp_path):
    """N2: cio_view derives membership from the LEDGER, fresh, every call — never from a frozen
    status.json snapshot. A ledger write after the last run changes the LIVE head, but since
    membership is always re-derived (not read from a cache that could go stale), the view still
    reports OK (still within the 26h run-recency window) and immediately reflects the new
    candidate, rather than going spuriously STALE over a hash that no longer gates anything."""
    c = make_candidate()
    _admit_to_paper_active(tmp_path, c)
    run.run_once(tmp_path, NOW)
    c2 = make_candidate(instrument_id="ethereum:0x" + "99" * 20)
    _admit_to_paper_active(tmp_path, c2)
    view = read.cio_view(tmp_path, NOW)
    assert view["state"] == "OK"
    assert c2["candidate_id"] in view["paper_active"]


# ── 11. no live-execution import ─────────────────────────────────────────────────────────────

_PKG_DIR = Path(contract.__file__).resolve().parent

#: Package A's own files (this epic's scope — ADR-560 Appendix I). ``scanners/*``,
#: ``counterparty_registry.py`` and ``onchain.py`` are Package B's, built in parallel; this
#: package is explicitly instructed not to touch them, so an import-graph assertion about MY
#: code stays scoped to what I actually wrote. A SEPARATE, non-failing informational check below
#: still looks at the whole tree and reports what it finds, without gating on files I don't own.
_PACKAGE_A_FILES = ("__init__.py", "_common.py", "ledger.py", "registry.py", "lifecycle.py",
                   "admission.py", "forward.py", "eligibility.py", "counterparty.py", "dedup.py",
                   "read.py", "run.py", "failure_matrix.py")


def _imported_top_level_modules(py_file: Path) -> set:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_no_execution_import_anywhere_in_package_a():
    bad = []
    for name in _PACKAGE_A_FILES:
        py = _PKG_DIR / name
        if not py.exists():
            continue
        for mod in _imported_top_level_modules(py):
            if mod == "spa_core.execution" or mod.startswith("spa_core.execution."):
                bad.append((py.name, mod))
    assert not bad, f"research_factory (Package A) imports spa_core.execution: {bad}"


def test_package_a_imports_only_capital_shadow_rpc_never_another_module():
    bad = []
    for name in _PACKAGE_A_FILES:
        py = _PKG_DIR / name
        if not py.exists():
            continue
        for mod in _imported_top_level_modules(py):
            if mod.startswith("spa_core.capital_shadow") and mod not in (
                    "spa_core.capital_shadow", "spa_core.capital_shadow.rpc"):
                bad.append((py.name, mod))
    assert not bad, f"Package A imports a capital_shadow module other than rpc: {bad}"


def test_real_capital_is_always_zero():
    assert contract.REAL_CAPITAL_USD == 0
    assert contract.LIVE_AUTHORIZED is False


def test_status_json_always_reports_zero_real_capital(tmp_path):
    c = make_candidate()
    _admit_to_paper_active(tmp_path, c)
    status = run.run_once(tmp_path, NOW)
    assert status["real_capital_usd"] == 0
    assert status["live_authorized"] is False


# ── 12. source lineage replay: rebuild index from the ledger, compare ──────────────────────

def test_rebuilt_index_matches_ledger_truth(tmp_path):
    c1 = make_candidate(instrument_id="ethereum:0x" + "01" * 20)
    c2 = make_candidate(instrument_id="ethereum:0x" + "02" * 20)
    registry.upsert(tmp_path, c1, NOW)
    registry.upsert(tmp_path, c2, NOW)
    idx = registry.rebuild_index(tmp_path)
    assert set(idx["candidates"]) == {c1["candidate_id"], c2["candidate_id"]}
    assert idx["ledger_head_hash"] == ledger_for(tmp_path).head_hash()


# ── 13. ledger immutability ─────────────────────────────────────────────────────────────────

def test_candidate_snapshot_rows_are_never_rewritten_only_added(tmp_path):
    c = make_candidate()
    registry.upsert(tmp_path, c, NOW)
    n1 = len(ledger_for(tmp_path).read_all())
    c2 = dict(c)
    c2["base_return"] = _cell(contract.MEASURED, 0.08, as_of=(NOW + timedelta(hours=1)).isoformat(),
                             judge_now=NOW + timedelta(hours=1))
    registry.upsert(tmp_path, c2, NOW + timedelta(hours=1))
    n2 = len(ledger_for(tmp_path).read_all())
    assert n2 == n1 + 1  # a NEW row, the old one is still there untouched
    first_snapshot = registry.latest_snapshot(ledger_for(tmp_path), c["candidate_id"])
    assert first_snapshot["seq"] == n2  # the latest IS the new one; the old row is still seq 1
    all_rows = ledger_for(tmp_path).read_all()
    assert all_rows[0]["payload"]["candidate"]["base_return"]["value"] == 1.0


# ── 14. candidate idempotency ───────────────────────────────────────────────────────────────

def test_upserting_the_identical_candidate_twice_writes_nothing_new(tmp_path):
    c = make_candidate()
    e1 = registry.upsert(tmp_path, c, NOW)
    n1 = len(ledger_for(tmp_path).read_all())
    e2 = registry.upsert(tmp_path, dict(c), NOW + timedelta(hours=1))
    n2 = len(ledger_for(tmp_path).read_all())
    assert e1["seq"] == e2["seq"]
    assert n1 == n2


# ── 15. corrupted latest/index recoverable ──────────────────────────────────────────────────

def test_corrupted_index_json_is_rebuilt_not_trusted(tmp_path):
    c = make_candidate()
    registry.upsert(tmp_path, c, NOW)
    idx_path = ledger_for(tmp_path).root() / contract.INDEX
    idx_path.write_text("{not json at all")
    idx = registry.load_index(tmp_path)
    assert c["candidate_id"] in idx["candidates"]


def test_missing_index_json_is_rebuilt(tmp_path):
    c = make_candidate()
    registry.upsert(tmp_path, c, NOW)
    idx_path = ledger_for(tmp_path).root() / contract.INDEX
    if idx_path.exists():
        idx_path.unlink()
    idx = registry.load_index(tmp_path)
    assert c["candidate_id"] in idx["candidates"]


def test_stale_index_with_wrong_head_hash_is_not_trusted(tmp_path):
    c = make_candidate()
    registry.upsert(tmp_path, c, NOW)
    registry.rebuild_index(tmp_path)
    idx_path = ledger_for(tmp_path).root() / contract.INDEX
    stale = json.loads(idx_path.read_text())
    stale["ledger_head_hash"] = "0" * 64
    stale["candidates"] = {}  # pretend the stale file knows nothing
    idx_path.write_text(json.dumps(stale))
    idx = registry.load_index(tmp_path)
    assert c["candidate_id"] in idx["candidates"]  # rebuilt, not the empty stale content


# ── 16. every path into PAPER_STATES needs an admission row ────────────────────────────────

def _paths_into(target: str) -> list:
    return [frm for frm, tos in contract.TRANSITIONS.items() if target in tos]


@pytest.mark.parametrize("target", [contract.PAPER_ACTIVE, contract.EVIDENCE_ACCUMULATING])
def test_every_incoming_edge_to_a_gated_paper_state_is_enumerated_and_gated(target):
    froms = _paths_into(target)
    assert froms, f"{target} has no incoming edges at all — contract changed under us"
    assert contract.GATED_TARGETS.get(target) == "admission"


def test_cio_eligible_incoming_edges_are_all_gated():
    froms = _paths_into(contract.CIO_ELIGIBLE)
    assert froms
    assert contract.GATED_TARGETS.get(contract.CIO_ELIGIBLE) == "cio_eligibility"


@pytest.mark.parametrize("frm", [f for f in contract.TRANSITIONS if contract.PAPER_ACTIVE in
                                 contract.TRANSITIONS[f]])
def test_reaching_paper_active_from_every_possible_predecessor_needs_admission(tmp_path, frm):
    """For EVERY edge X -> PAPER_ACTIVE in the graph, actually drive a candidate to X and prove
    the edge refuses without gate_ref, and succeeds only with a real PASS admission row."""
    import hashlib
    addr = hashlib.sha256(frm.encode()).hexdigest()[:40]
    c = make_candidate(instrument_id=f"ethereum:0x{addr}")
    cid = c["candidate_id"]
    registry.upsert(tmp_path, c, NOW)

    # drive the candidate to `frm` via a legitimate path where possible
    path_from_discovered = {
        contract.PAPER_CANDIDATE: (contract.SCREENED, contract.RESEARCH_READY, contract.PAPER_CANDIDATE),
    }
    if frm == contract.PAPER_CANDIDATE:
        for s in path_from_discovered[contract.PAPER_CANDIDATE]:
            lifecycle.transition(tmp_path, cid, s, reason="setup", now=NOW)
    elif frm == contract.PAUSED_PAPER:
        for s in (contract.SCREENED, contract.RESEARCH_READY, contract.PAPER_CANDIDATE):
            lifecycle.transition(tmp_path, cid, s, reason="setup", now=NOW)
        admission_id = lifecycle.active_admission_id(tmp_path, cid)
        report = admission.evaluate(c, {"_existing_book_roots": []}, NOW)
        snap = admission.write_admission_snapshot(tmp_path, c, report, NOW)
        lifecycle.transition(tmp_path, cid, contract.PAPER_ACTIVE, gate_ref=snap["payload"]["admission_id"],
                            reason="setup", now=NOW)
        lifecycle.transition(tmp_path, cid, contract.PAUSED_PAPER, reason="pause", now=NOW)
    else:
        pytest.skip(f"{frm} -> PAPER_ACTIVE is not a path this harness drives (contract-graph edge only)")

    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.transition(tmp_path, cid, contract.PAPER_ACTIVE, gate_ref=None, reason="no gate", now=NOW)

    report = admission.evaluate(c, {"_existing_book_roots": []}, NOW)
    assert report["verdict"] == contract.GATE_PASS
    snap = admission.write_admission_snapshot(tmp_path, c, report, NOW)
    if frm == contract.PAUSED_PAPER:
        # PAUSED_PAPER resumes ONLY to its recorded paused_from (PAPER_ACTIVE here) — a resume
        # with a FRESH admission id for the same candidate is still gated correctly
        row = lifecycle.transition(tmp_path, cid, contract.PAPER_ACTIVE, gate_ref=snap["payload"]["admission_id"],
                                  reason="resume", now=NOW)
    else:
        row = lifecycle.transition(tmp_path, cid, contract.PAPER_ACTIVE, gate_ref=snap["payload"]["admission_id"],
                                  reason="admitted", now=NOW)
    assert row["payload"]["to_state"] == contract.PAPER_ACTIVE


def test_paused_paper_resumes_only_to_its_recorded_paused_from(tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    admission_id = _admit_to_paper_active(tmp_path, c)
    lifecycle.transition(tmp_path, cid, contract.EVIDENCE_ACCUMULATING, gate_ref=admission_id, reason="x", now=NOW)
    lifecycle.transition(tmp_path, cid, contract.PAUSED_PAPER, reason="pause", now=NOW)
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.transition(tmp_path, cid, contract.PAPER_ACTIVE, gate_ref=admission_id,
                            reason="wrong resume target", now=NOW)
    row = lifecycle.transition(tmp_path, cid, contract.EVIDENCE_ACCUMULATING, gate_ref=admission_id,
                              reason="correct resume", now=NOW)
    assert row["payload"]["to_state"] == contract.EVIDENCE_ACCUMULATING


# ── transition idempotency / no admission bypass more generally ────────────────────────────

def test_same_state_transition_call_is_a_no_op_not_a_duplicate_row(tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    registry.upsert(tmp_path, c, NOW)
    lifecycle.transition(tmp_path, cid, contract.SCREENED, reason="first", now=NOW)
    n1 = len(ledger_for(tmp_path).read_all())
    row = lifecycle.transition(tmp_path, cid, contract.SCREENED, reason="again", now=NOW)
    n2 = len(ledger_for(tmp_path).read_all())
    assert n1 == n2
    assert row["payload"]["to_state"] == contract.SCREENED


def test_rescreen_from_hold_requires_the_input_digest_to_have_changed(tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    registry.upsert(tmp_path, c, NOW)
    lifecycle.transition(tmp_path, cid, contract.SCREENED, reason="x", now=NOW)
    lifecycle.transition(tmp_path, cid, contract.DATA_INSUFFICIENT, reason="x", now=NOW)
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.transition(tmp_path, cid, contract.SCREENED,
                            gate_ref={"prev_digest": "same", "new_digest": "same"},
                            reason="shopping for a re-screen", now=NOW)
    row = lifecycle.transition(tmp_path, cid, contract.SCREENED,
                              gate_ref={"prev_digest": "old", "new_digest": "new"},
                              reason="input genuinely changed", now=NOW)
    assert row["payload"]["to_state"] == contract.SCREENED


# ── survivor bias: disappearance stays in the denominators ─────────────────────────────────

def test_disappeared_candidate_stays_in_denominators(tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    _admit_to_paper_active(tmp_path, c)
    ledger_for(tmp_path).append_idempotent("disappearance", ["disappearance", cid, "x"], {"candidate_id": cid}, "x")
    lifecycle.transition(tmp_path, cid, contract.DISAPPEARED, reason="vanished", now=NOW)
    status = read.latest(tmp_path)
    assert status["denominators"]["disappeared"] == 1
    assert any(c2["candidate_id"] == cid for c2 in status["candidates"])


# ── run.py tolerates an empty/missing scanners package ──────────────────────────────────────

def test_run_once_tolerates_no_scanners(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "_discover_scanners", lambda: [])
    status = run.run_once(tmp_path, NOW)
    assert status["schema"] == contract.SCHEMA_STATUS
    assert status["denominators"]["discovered"] == 0


def test_observe_only_is_reserved_for_trading_research_projections(tmp_path):
    """Contract fix (Package A report): DISCOVERED → OBSERVE_ONLY is now a contract edge, but only a
    TRADING_RESEARCH projection may take it — a DeFi candidate cannot park itself outside the gates."""
    from spa_core.research_factory import contract as c, lifecycle, registry
    from datetime import datetime, timezone
    now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    assert c.transition_allowed(c.DISCOVERED, c.OBSERVE_ONLY)
    assert c.TRANSITIONS[c.OBSERVE_ONLY] == set()
    for domain, ok in (("TRADING_RESEARCH", True), ("CASH_TREASURY", False)):
        d = tmp_path / domain
        cand = {f: None for f in c.CANDIDATE_FIELDS}
        key = c.exposure_key("DIRECTIONAL_TREND" if ok else "STABLECOIN_SAVINGS",
                             "engine:trading_research:x1" if ok else "llama:d8c4eff5-c8a9-46fc-a888-057c4c668e72",
                             "cex" if ok else "Ethereum")
        cand.update({"candidate_id": c.candidate_id(key), "exposure_key": key, "domain": domain})
        registry.upsert(d, cand, now)
        lifecycle.ensure_discovered(d, cand["candidate_id"], now)
        if ok:
            lifecycle.transition(d, cand["candidate_id"], c.OBSERVE_ONLY, reason="projection", now=now)
            assert lifecycle.current_state(d, cand["candidate_id"]) == c.OBSERVE_ONLY
        else:
            import pytest
            with pytest.raises(lifecycle.InvalidTransition):
                lifecycle.transition(d, cand["candidate_id"], c.OBSERVE_ONLY, reason="sneak", now=now)


def test_contract_net_return_values_a_funding_leg_and_refuses_unmeasured_costs():
    """Package B report: FUNDING_CAPTURE has no base leg (NOT_APPLICABLE), so the net formula could never
    value it. Now the funding IS the return — but any applicable unmeasured cost still blocks the result."""
    from spa_core.research_factory import contract as c
    f = c.cell(c.MEASURED, 0.05, unit="frac/yr", source_ref="market_data/funding.json",
               source_class=c.PRIMARY_VENUE, source_root="venue:median5", as_of="2026-10-04T09:00:00Z")
    na = lambda r: c.cell(c.NOT_APPLICABLE, reason=r)  # noqa: E731
    ok = c.net_expected_return({"base_return": na("funding leg"), "funding": f, "fees": na("x"),
                                "gas": na("x"), "hedging_cost": na("x")})
    assert ok["state"] == c.ESTIMATED_WITH_METHOD and ok["value"] == 0.05
    blocked = c.net_expected_return({"base_return": na("funding leg"), "funding": f, "fees": na("x"), "gas": na("x"),
                                     "hedging_cost": c.cell(c.NOT_MEASURED, reason="perp execution cost")})
    assert blocked["state"] == c.NOT_MEASURED and blocked["value"] is None
    emb = dict(f, embedded_in_return=True)
    assert c.net_expected_return({"base_return": na("x"), "funding": emb})["state"] == c.NOT_MEASURED


def test_contract_canonical_network_is_idempotent():
    from spa_core.research_factory import contract as c
    for alias in ("Ethereum", "OP Mainnet", "BNB Chain", "cex", "Hyperliquid L1"):
        once = c.canonical_network(alias)
        assert once is not None and c.canonical_network(once) == once
    assert c.canonical_network("not-a-chain") is None
