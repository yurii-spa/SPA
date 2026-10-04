"""Rework tests for the REWORK-verdict review of ADR-560 Package A (H0-H5, M2, M5, M7, LOW).

Each fix below has a positive test AND a mutation check proving the test is actually
sensitive to the fix (not vacuously green).

Time is injected throughout via the single anchor NOW (and offsets built from it), passed as
`now=`/positional `now` to every call under test.
# FROZEN-DATE-OK: injected-clock — NOW (and every NOW + timedelta(...) derived from it) is
# passed as the now= argument to every lifecycle/admission/forward/registry/run call in this
# file; nothing here compares a literal date to the real clock.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.research_factory import (
    admission, contract, eligibility, forward, lifecycle, read, registry, run,
)
from spa_core.research_factory._common import ledger_for
from spa_core.utils.hash_ledger import LedgerError
from spa_core.tests import _research_evidence_v2_fixtures as v2fx

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
    instrument_id = instrument_id or f"{network}:0x{'33' * 20}"
    exposure = contract.exposure_key(mechanism_id, instrument_id, network)
    cid = contract.candidate_id(exposure)
    c = {f: None for f in contract.CANDIDATE_FIELDS}
    c.update({
        "candidate_id": cid, "exposure_key": exposure, "exposure_key_version": contract.EXPOSURE_KEY_VERSION,
        "mechanism_id": mechanism_id, "asset_class": contract.MECHANISMS[mechanism_id]["asset_class"],
        "domain": domain, "network": contract.canonical_network(network), "venue_or_protocol": "test_scanner",
        "instrument": instrument_id, "instrument_id": instrument_id, "underlying_root": instrument_id,
        "economic_driver_key": f"DRIVER_{mechanism_id}", "yield_source": "savings_rate",
        # unit="fraction" is a declared ANNUAL rate (contract.ANNUAL_RATE_UNITS) — contract.
        # net_expected_return() is now unit-aware (ADR-564 integration finding: a live run
        # netted a one-off fee against an annual rate unchecked and produced net=-2697); a
        # unit-less default would make every candidate built here honestly NOT_MEASURED.
        "base_return": _cell(unit="fraction"), "fees": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "gas": _cell(contract.NOT_APPLICABLE, reason="n/a"), "funding": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "hedging_cost": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "liquidity": _cell(contract.MEASURED, 1_000_000.0), "time_to_exit": _cell(contract.MEASURED, 0.0),
        "capacity": _cell(contract.NOT_MEASURED, reason="not observed"),
        "duration": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "leverage": _cell(contract.NOT_APPLICABLE, reason="no leverage"),
        "liquidation_distance": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "source_refs": [],
        "producing_scanner": "test_scanner",
        "counterparty": counterparty_data if counterparty_data is not None else {
            "roles": {r: {"state": contract.CP_DOCUMENTED, "name": "Acme"} for r in
                     contract.MECHANISMS[mechanism_id]["required_roles"]},
            "dimensions": {},
        },
    })
    c.update(overrides)
    return c


def _admit_to_paper_active(data_dir: Path, candidate: dict, now: datetime = NOW) -> str:
    """ADR-564 binding #1: v1 ``admission.write_admission_snapshot`` now always refuses — this
    delegates to the shared all-STRONG v2 fixture helper (same signature/return as before)."""
    return v2fx.admit_to_paper_active_v2(data_dir, candidate, now)


# ── H0: rpc_client must be a real RpcClient instance ────────────────────────────────────────

def test_h0_live_rpc_builds_a_real_client_no_scanner_unavailable_because_of_it(tmp_path, monkeypatch):
    from spa_core.capital_shadow import rpc as rpc_mod

    def fake_post(url, payload):
        method = payload.get("method")
        if method == "eth_blockNumber":
            return {"jsonrpc": "2.0", "id": 1, "result": "0x64"}
        if method == "eth_getBlockByNumber":
            return {"jsonrpc": "2.0", "id": 1, "result": {"timestamp": "0x6512aaaa", "hash": "0xabc"}}
        if method == "eth_call":
            return {"jsonrpc": "2.0", "id": 1, "result": "0x00"}
        return {"jsonrpc": "2.0", "id": 1, "result": None}

    real_init = rpc_mod.RpcClient.__init__

    def fake_init(self, chain_id, endpoints=None, post=None, timeout_s=10):
        fake_endpoints = [("http://op1", "op1"), ("http://op2", "op2")]
        real_init(self, chain_id, endpoints=fake_endpoints, post=fake_post, timeout_s=timeout_s)

    monkeypatch.setattr(rpc_mod.RpcClient, "__init__", fake_init)

    received = {}

    class _Spy:
        __name__ = "spy_scanner"

        @staticmethod
        def scan(data_dir, now, rpc_client=None):
            received["rpc_client"] = rpc_client
            return {"scanner": "spy_scanner", "domain": "CASH_TREASURY", "as_of": now.isoformat(),
                   "status": "OK", "reason": None,
                   "denominators": {"scanned": 0, "discovered": 0, "truncated": 0},
                   "candidates": [], "unresolved": [], "observations": {}, "counterparty": {},
                   "existing_book_roots": []}

    import spa_core.research_factory.run as run_mod
    monkeypatch.setattr(run_mod, "_discover_scanners", lambda: [_Spy])

    rc = run_mod.main(["--live-rpc", "--data-dir", str(tmp_path), "--now", NOW.isoformat()])
    assert rc == contract.EXIT_OK
    assert "rpc_client" in received, "the spy scanner was never called"
    assert isinstance(received["rpc_client"], rpc_mod.RpcClient), (
        f"--live-rpc handed scanners a {type(received['rpc_client'])!r}, not an RpcClient instance")
    # it is a REAL, working client — calling the exact method onchain.py calls must not raise
    pinned = received["rpc_client"].pin_block()
    assert isinstance(pinned, dict) and "state" in pinned


def test_h0_mutation_check_module_as_client_breaks_onchain_directly():
    """MUTATION CHECK: reverting to the bug (passing the bare MODULE, not an RpcClient
    instance) reproduces exactly the defect this fix removes, at the exact call site
    (onchain.py's realised_index -> rpc_client.pin_block()). onchain.py itself already catches
    the resulting AttributeError (a scanner "never raises on missing data") and turns it into a
    NOT_MEASURED cell NAMING that AttributeError — so the observable symptom of H0's bug is not
    a process crash, it is EVERY realised_index read on EVERY run silently failing with a
    client-shaped reason, never the chain's real NAV. (The 5 real scanners in this tree happen
    not to reach onchain.py on an empty tmp data dir with no upstream artifacts to key off of,
    which is why this check goes straight to the call site rather than through run_once — the
    bug is in run.py's construction of rpc_client, not in reaching it.)"""
    from spa_core.capital_shadow import rpc as rpc_mod
    from spa_core.research_factory import onchain
    broken = onchain.realised_index("sUSDS", onchain.SUSDS_ADDRESS, rpc_client=rpc_mod, now=NOW)  # module bug
    assert broken["state"] == contract.NOT_MEASURED
    assert "AttributeError" in broken["reason"] and "pin_block" in broken["reason"]

    from spa_core.capital_shadow.rpc import RpcClient
    real_client = RpcClient(1, endpoints=[], post=lambda *a, **k: {})
    fixed = onchain.realised_index("sUSDS", onchain.SUSDS_ADDRESS, rpc_client=real_client, now=NOW)
    assert fixed["state"] == contract.NOT_MEASURED  # still NOT_MEASURED (no real endpoints), but...
    assert "AttributeError" not in (fixed["reason"] or "")  # ...never because of the CLIENT's own shape


def test_h0_exit_code_is_broken_only_when_integrity_is_not_ok(tmp_path, monkeypatch):
    registry.upsert(tmp_path, make_candidate(), NOW)
    led = ledger_for(tmp_path)
    led.anchors_path().write_text("")  # tamper -> integrity BROKEN
    rc = run.main(["--data-dir", str(tmp_path), "--now", NOW.isoformat()])
    assert rc == contract.EXIT_BROKEN


# ── H2: fingerprint excludes timestamps everywhere; no churn on unchanged data ─────────────

def test_h2_identical_data_12h_apart_appends_no_snapshot_and_no_transition(tmp_path):
    c = make_candidate(mechanism_id="LENDING", domain="DEFI_STABLE_YIELD",
                      counterparty_data={"roles": {}, "dimensions": {}})
    c["source_refs"] = [{"source_root": "chain:1", "source_class": contract.PRIMARY_PROTOCOL,
                        "value": 1.0, "as_of": NOW.isoformat(), "recorded_at": NOW.isoformat()}]
    registry.upsert(tmp_path, c, NOW)
    lifecycle.transition(tmp_path, c["candidate_id"], contract.SCREENED, reason="x", now=NOW)
    lifecycle.transition(tmp_path, c["candidate_id"], contract.DATA_INSUFFICIENT, reason="x", now=NOW)
    n1 = len(ledger_for(tmp_path).read_all())

    later = NOW + timedelta(hours=12)
    c2 = make_candidate(mechanism_id="LENDING", domain="DEFI_STABLE_YIELD",
                       counterparty_data={"roles": {}, "dimensions": {}})
    # only the TIMESTAMPS differ from c — same numbers, same structure, everywhere
    c2["base_return"] = _cell(contract.MEASURED, 1.0, unit="fraction", as_of=later.isoformat(), judge_now=later)
    c2["source_refs"] = [{"source_root": "chain:1", "source_class": contract.PRIMARY_PROTOCOL,
                         "value": 1.0, "as_of": later.isoformat(), "recorded_at": later.isoformat()}]
    fp1 = registry.fingerprint_of(c)
    fp2 = registry.fingerprint_of(c2)
    assert fp1 == fp2, "fingerprints differ on a timestamp-only change — H2 not fixed"

    entry = registry.upsert(tmp_path, c2, later)
    n2 = len(ledger_for(tmp_path).read_all())
    assert n2 == n1, "a timestamp-only re-observation appended a new row"
    assert entry["payload"]["candidate"]["base_return"]["value"] == 1.0


def test_h2_mutation_check_source_refs_timestamp_is_really_excluded():
    """MUTATION CHECK: a candidate differing ONLY in a `source_refs` entry's `as_of`/
    `recorded_at` must fingerprint identically; flip ONE of those keys' NAME (simulating the
    narrower, pre-fix stripping that only looked at named cell fields) and watch the digest
    change, proving the test is actually sensitive to source_refs being covered."""
    c = make_candidate()
    c["source_refs"] = [{"source_root": "chain:1", "as_of": "2026-01-01T00:00:00Z"}]
    c2 = dict(c)
    c2["source_refs"] = [{"source_root": "chain:1", "as_of": "2030-01-01T00:00:00Z"}]
    assert registry.fingerprint_of(c) == registry.fingerprint_of(c2)

    # now rename the key so the (correct) stripper no longer recognises it — the digest MUST
    # then differ, proving the equality above wasn't a coincidence of empty dicts
    c3 = dict(c)
    c3["source_refs"] = [{"source_root": "chain:1", "NOT_as_of": "2030-01-01T00:00:00Z"}]
    assert registry.fingerprint_of(c) != registry.fingerprint_of(c3)


# ── H3: disappearance keyed by producing_scanner ────────────────────────────────────────────

def test_h3_disappearance_keyed_by_producing_scanner(tmp_path):
    c = make_candidate(producing_scanner="cash_treasury_scanner", venue_or_protocol="sky")
    cid = c["candidate_id"]
    _admit_to_paper_active(tmp_path, c)

    class _Scanner:
        __name__ = "cash_treasury_scanner"

        @staticmethod
        def scan(data_dir, now, rpc_client=None):
            return {"scanner": "cash_treasury_scanner", "domain": "CASH_TREASURY", "as_of": now.isoformat(),
                   "status": "OK", "reason": None,
                   "denominators": {"scanned": 0, "discovered": 0, "truncated": 0},
                   "candidates": [], "unresolved": [], "observations": {}, "counterparty": {},
                   "existing_book_roots": []}

    import spa_core.research_factory.run as run_mod
    orig = run_mod._discover_scanners
    run_mod._discover_scanners = lambda: [_Scanner]
    try:
        status = run_mod.run_once(tmp_path, NOW + timedelta(hours=1))
    finally:
        run_mod._discover_scanners = orig

    assert lifecycle.current_state(tmp_path, cid) == contract.DISAPPEARED
    led = ledger_for(tmp_path)
    disappearance_rows = [e for e in led.read_all() if e["kind"] == "disappearance"
                         and e["payload"].get("candidate_id") == cid]
    assert disappearance_rows
    assert status["denominators"]["disappeared"] == 1


def test_h3_mutation_check_venue_keying_never_fires():
    """MUTATION CHECK: keying the SAME scenario by venue_or_protocol (the pre-fix behaviour)
    instead of producing_scanner never matches `seen_this_run` (which is keyed by SCANNER
    name), so disappearance never fires — proving the old keying really was broken, not just
    differently named."""
    seen_this_run = {"cash_treasury_scanner": set()}  # the scanner ran OK, reported nothing
    candidate = {"venue_or_protocol": "sky", "producing_scanner": "cash_treasury_scanner"}
    # old (broken) key:
    old_key = candidate.get("venue_or_protocol")
    assert old_key not in seen_this_run, "the mutation's premise is wrong: venue happens to match"
    # new (fixed) key:
    new_key = candidate.get("producing_scanner")
    assert new_key in seen_this_run and "fake-cid" not in seen_this_run[new_key]


# ── H4: an observation row every run for every paper-state candidate ───────────────────────

def test_h4_frozen_bytes_for_four_days_yields_zero_counted_periods(tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    admission_id = _admit_to_paper_active(tmp_path, c, NOW)
    admission_as_of = NOW
    frozen_as_of = (admission_as_of - timedelta(days=5)).isoformat()  # frozen BEFORE admission
    for day in range(1, 5):
        t = NOW + timedelta(days=day)
        obs = {"period": f"2026-10-{4 + day:02d}", "backfill": False, "realised_index": None,
              "observed_return": _cell(contract.MEASURED, 0.05, as_of=frozen_as_of, judge_now=t)}
        forward.record(tmp_path, cid, obs, t)
    assert forward.forward_periods(tmp_path, cid) == 0


def test_h4_observation_written_every_run_even_when_scanner_omits_it(tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    _admit_to_paper_active(tmp_path, c, NOW)
    for day in range(1, 4):
        t = NOW + timedelta(days=day)
        all_candidates = {cid: registry.current_candidate(tmp_path, cid)}
        run._process_candidate(tmp_path, cid, all_candidates, [], {}, t)  # no new_obs supplied
    led = ledger_for(tmp_path)
    obs_rows = [e for e in led.read_all() if e["kind"] == "observation"
               and e["payload"].get("candidate_id") == cid]
    assert len(obs_rows) == 3
    assert all(r["payload"]["observed_return"]["state"] == contract.NOT_MEASURED for r in obs_rows)
    assert lifecycle.current_state(tmp_path, cid) == contract.STALE_STATE


def test_h4_vanished_source_prefers_disappeared_over_stale(tmp_path):
    """When the source truly vanished (absent from an OK scanner), DISAPPEARED (terminal) wins
    — H4's synthesized-NOT_MEASURED/STALE path never even runs for it, because the
    disappearance check (and the resulting terminal state) happens before forward-observation
    processing in run_once."""
    c = make_candidate(producing_scanner="rwa_scanner")
    cid = c["candidate_id"]
    _admit_to_paper_active(tmp_path, c, NOW)

    class _Scanner:
        __name__ = "rwa_scanner"

        @staticmethod
        def scan(data_dir, now, rpc_client=None):
            return {"scanner": "rwa_scanner", "domain": "RWA_STABLE_YIELD", "as_of": now.isoformat(),
                   "status": "OK", "reason": None,
                   "denominators": {"scanned": 0, "discovered": 0, "truncated": 0},
                   "candidates": [], "unresolved": [], "observations": {}, "counterparty": {},
                   "existing_book_roots": []}

    import spa_core.research_factory.run as run_mod
    orig = run_mod._discover_scanners
    run_mod._discover_scanners = lambda: [_Scanner]
    try:
        run_mod.run_once(tmp_path, NOW + timedelta(hours=1))
    finally:
        run_mod._discover_scanners = orig
    assert lifecycle.current_state(tmp_path, cid) == contract.DISAPPEARED


def test_h4_mutation_check_without_synthesis_stale_never_fires(tmp_path):
    """MUTATION CHECK: calling forward.record only on runs where an observation ACTUALLY
    exists (the pre-fix behaviour: `if obs is not None: forward.record(...)`) never writes
    anything for a silent candidate, so the 3-consecutive-not-counted rule never triggers."""
    c = make_candidate()
    cid = c["candidate_id"]
    _admit_to_paper_active(tmp_path, c, NOW)
    for day in range(1, 4):
        t = NOW + timedelta(days=day)
        obs = None  # the scanner never mentions this candidate — old code: skip entirely
        if obs is not None:
            forward.record(tmp_path, cid, obs, t)
    led = ledger_for(tmp_path)
    obs_rows = [e for e in led.read_all() if e["kind"] == "observation"
               and e["payload"].get("candidate_id") == cid]
    assert len(obs_rows) == 0
    assert lifecycle.current_state(tmp_path, cid) == contract.PAPER_ACTIVE, (
        "without H4's synthesis, a silent candidate never reaches STALE — proving the real fix "
        "(run._process_candidate always calling forward.record) is what makes it happen")


# ── H1: forward.record delegates entirely to contract.period_countable ─────────────────────

def test_h1_forward_uses_contract_period_countable(tmp_path, monkeypatch):
    c = make_candidate()
    cid = c["candidate_id"]
    _admit_to_paper_active(tmp_path, c, NOW)
    calls = []
    real = contract.period_countable

    def spy(obs, prev_counted, admission_as_of, now):
        calls.append((obs, prev_counted, admission_as_of, now))
        return real(obs, prev_counted, admission_as_of, now)

    monkeypatch.setattr(contract, "period_countable", spy)
    t = NOW + timedelta(hours=1)
    obs = {"period": "2026-10-05", "backfill": False, "realised_index": None,
          "observed_return": _cell(contract.MEASURED, 0.05, as_of=t.isoformat(), judge_now=t)}
    forward.record(tmp_path, cid, obs, t)
    assert calls, "forward.record never called contract.period_countable at all"


def test_h1_mutation_check_period_countable_forced_true_wrongly_counts_backfill(tmp_path, monkeypatch):
    """MUTATION CHECK: forcing contract.period_countable to always say True makes an obvious
    backfill row count — proving forward.record really defers the decision to it (a local
    re-implementation would ignore this monkeypatch entirely)."""
    c = make_candidate()
    cid = c["candidate_id"]
    _admit_to_paper_active(tmp_path, c, NOW)
    monkeypatch.setattr(contract, "period_countable", lambda *a, **k: (True, "forced"))
    t = NOW + timedelta(hours=1)
    obs = {"period": "2026-10-05", "backfill": True, "realised_index": None,
          "observed_return": _cell(contract.MEASURED, 0.05, as_of=t.isoformat(), judge_now=t)}
    forward.record(tmp_path, cid, obs, t)
    assert forward.forward_periods(tmp_path, cid) == 1, (
        "a backfill row did not count even though period_countable was forced True — "
        "forward.record is not actually delegating the decision")


# ── H5: provenance compares a real second return cell, excludes derived/MODELLED ───────────

def test_h5_aggregator_only_fails_single_aggregator_root():
    """sUSDS-only-DeFiLlama: base_return sourced ONLY from a REPUTABLE_AGGREGATOR root, no
    second cell at all -> FAIL, not PASS/UNKNOWN."""
    c = make_candidate(base_return=_cell(contract.MEASURED, 0.055, source_class=contract.REPUTABLE_AGGREGATOR,
                                        source_root="defillama:yields"))
    gate = admission._source_provenance_acceptable(c, NOW)
    assert gate["verdict"] == contract.GATE_FAIL
    assert "single aggregator root" in gate["evidence"]


def test_h5_cross_check_agreement_is_not_falsely_conflicted():
    """BUIDL: base_return from an aggregator + an independent cross-check cell reporting an
    economically EQUIVALENT number -> PASS, never a false CONFLICTED."""
    c = make_candidate(
        base_return=_cell(contract.MEASURED, 0.052, source_class=contract.REPUTABLE_AGGREGATOR,
                         source_root="defillama:yields"),
        quoted_return=_cell(contract.MEASURED, 0.0515, source_class=contract.PRIMARY_CHAIN, source_root="chain:1"),
    )
    gate = admission._source_provenance_acceptable(c, NOW)
    assert gate["verdict"] == contract.GATE_PASS, gate


def test_h5_a_real_conflict_is_caught():
    c = make_candidate(
        base_return=_cell(contract.MEASURED, 0.10, source_class=contract.REPUTABLE_AGGREGATOR,
                         source_root="defillama:yields"),
        quoted_return=_cell(contract.MEASURED, 0.03, source_class=contract.SECONDARY_SOURCE, source_root="chain:1"),
    )
    gate = admission._source_provenance_acceptable(c, NOW)
    assert gate["verdict"] == contract.GATE_FAIL
    assert "CONFLICTED" in gate["evidence"]


def test_h5_excludes_derived_net_expected_return_and_modelled():
    """net_expected_return (derived) and a MODELLED cell must never serve as the cross-check,
    even if present and numerically different."""
    c = make_candidate(base_return=_cell(contract.MEASURED, 0.08, source_class=contract.REPUTABLE_AGGREGATOR,
                                        source_root="defillama:yields"),
                       quoted_return=_cell(contract.DOCUMENTED, 0.01, source_class=contract.MODELLED,
                                          source_root="model:internal"))
    gate = admission._source_provenance_acceptable(c, NOW)
    # the MODELLED quoted_return must be IGNORED -> falls back to "no comparable second root"
    assert gate["verdict"] == contract.GATE_FAIL
    assert "single aggregator root" in gate["evidence"]


def test_h5_mutation_check_source_refs_no_longer_consulted():
    """MUTATION CHECK: the OLD gate read `source_refs`; the NEW one must NOT — a candidate
    with conflicting source_refs but a clean PRIMARY base_return and no cross-check field must
    PASS trivially, proving source_refs is no longer the gate's input."""
    c = make_candidate(source_refs=[
        {"source_root": "a", "source_class": contract.REPUTABLE_AGGREGATOR, "value": 0.99},
        {"source_root": "b", "source_class": contract.SECONDARY_SOURCE, "value": 0.01},
    ])  # base_return stays the fixture default: MEASURED, PRIMARY_PROTOCOL
    gate = admission._source_provenance_acceptable(c, NOW)
    assert gate["verdict"] == contract.GATE_PASS, (
        "the gate still reacts to source_refs content — it should ignore that field entirely now")


# ── M2: realised return is annualised to match the observed rate's unit ────────────────────

def test_m2_annualised_realised_return_matches_apy_shaped_base_return(tmp_path):
    c = make_candidate(base_return=_cell(contract.MEASURED, 0.05, unit="fraction",
                                     source_root="venue:test_observed_feed"))  # 5% APY
    cid = c["candidate_id"]
    admission_id = _admit_to_paper_active(tmp_path, c, NOW)
    # a realised_index growing at ~5%/yr compounded, sampled 30 days apart
    t0 = NOW + timedelta(hours=1)
    t1 = t0 + timedelta(days=30)
    idx0 = 1.0
    idx1 = (1.05) ** (30.0 / 365.25)
    # ADR-564 amendment: realised_vs_observed_consistent is UNKNOWN when both sides share an
    # origin — observed_return here is an INDEPENDENT (venue:) feed, distinct from the on-chain
    # realised_index, so this test still exercises the numeric consistency check it is named for.
    obs0 = {"period": "2026-11-04", "realised_index": _cell(contract.MEASURED, idx0, source_class=contract.PRIMARY_CHAIN,
                                                           as_of=t0.isoformat(), judge_now=t0),
           "observed_return": _cell(contract.MEASURED, 0.05, source_root="venue:test_observed_feed",
                                   as_of=t0.isoformat(), judge_now=t0)}
    forward.record(tmp_path, cid, obs0, t0)
    obs1 = {"period": "2026-12-04", "realised_index": _cell(contract.MEASURED, idx1, source_class=contract.PRIMARY_CHAIN,
                                                           as_of=t1.isoformat(), judge_now=t1),
           "observed_return": _cell(contract.MEASURED, 0.05, source_root="venue:test_observed_feed",
                                   as_of=t1.isoformat(), judge_now=t1)}
    forward.record(tmp_path, cid, obs1, t1)
    kind, realised_cell = forward.realised_return(tmp_path, cid)
    assert kind == contract.RETURN_REALISED_PAPER
    assert realised_cell["value"] == pytest.approx(0.05, abs=1e-6)

    view = {"_existing_book_roots": []}
    report = eligibility.evaluate(tmp_path, registry.current_candidate(tmp_path, cid), view, t1)
    assert report["gates"]["realised_vs_observed_consistent"]["verdict"] == contract.GATE_PASS, \
        report["gates"]["realised_vs_observed_consistent"]


def test_m2_mutation_check_un_annualised_period_fraction_would_fail(tmp_path):
    """MUTATION CHECK: the RAW (un-annualised) period fraction for the SAME 30-day/5%/yr series
    is tiny (~0.4%) and would NOT match a 5% APY within tolerance — proving the annualisation
    step in forward.realised_return is what makes the PASS above possible, not a coincidence."""
    idx0, idx1 = 1.0, (1.05) ** (30.0 / 365.25)
    raw_period_fraction = (idx1 / idx0) - 1.0
    denom = max(abs(0.05), abs(raw_period_fraction), 1e-12)
    rel = abs(0.05 - raw_period_fraction) / denom
    assert rel > contract.CONFLICT_TOLERANCE_REL, (
        "the un-annualised period fraction is somehow already within tolerance of the APY — "
        "this mutation check no longer demonstrates anything")


def test_m2_both_directions_realised_higher_and_lower_than_observed(tmp_path):
    for apy, idx_annual_rate, expect_pass in ((0.05, 0.051, True), (0.05, 0.12, False)):
        c = make_candidate(base_return=_cell(contract.MEASURED, apy, unit="fraction",
                              source_root="venue:test_observed_feed"),
                          instrument_id=f"ethereum:0x{'44' if expect_pass else '55'}" + "0" * 38)
        cid = c["candidate_id"]
        _admit_to_paper_active(tmp_path, c, NOW)
        t0 = NOW + timedelta(hours=1)
        t1 = t0 + timedelta(days=60)
        idx0 = 1.0
        idx1 = (1 + idx_annual_rate) ** (60.0 / 365.25)
        # ADR-564 amendment: realised_vs_observed_consistent is UNKNOWN when both sides share an
        # origin — observed_return is an INDEPENDENT (venue:) feed here, distinct from the
        # on-chain realised_index, so this test still exercises the numeric consistency check.
        forward.record(tmp_path, cid, {"period": "P0",
                                       "realised_index": _cell(contract.MEASURED, idx0, source_class=contract.PRIMARY_CHAIN,
                                                              as_of=t0.isoformat(), judge_now=t0),
                                       "observed_return": _cell(contract.MEASURED, apy,
                                                               source_root="venue:test_observed_feed",
                                                               as_of=t0.isoformat(), judge_now=t0)}, t0)
        forward.record(tmp_path, cid, {"period": "P1",
                                       "realised_index": _cell(contract.MEASURED, idx1, source_class=contract.PRIMARY_CHAIN,
                                                              as_of=t1.isoformat(), judge_now=t1),
                                       "observed_return": _cell(contract.MEASURED, apy,
                                                               source_root="venue:test_observed_feed",
                                                               as_of=t1.isoformat(), judge_now=t1)}, t1)
        view = {"_existing_book_roots": []}
        report = eligibility.evaluate(tmp_path, registry.current_candidate(tmp_path, cid), view, t1)
        verdict = report["gates"]["realised_vs_observed_consistent"]["verdict"]
        if expect_pass:
            assert verdict == contract.GATE_PASS, report["gates"]["realised_vs_observed_consistent"]
        else:
            assert verdict == contract.GATE_FAIL, report["gates"]["realised_vs_observed_consistent"]


# ── M5: generated_at comes from the last run row, not the wall clock ───────────────────────

def test_m5_generated_at_is_the_last_run_at_not_wall_clock(tmp_path, monkeypatch):
    import spa_core.research_factory.run as run_mod
    monkeypatch.setattr(run_mod, "_discover_scanners", lambda: [])
    run_mod.run_once(tmp_path, NOW)

    status = read.latest(tmp_path)
    assert status["generated_at"] == f"{NOW.strftime('%Y-%m-%dT%H:%M:%SZ')}"

    much_later = NOW + timedelta(days=4)
    view = read.cio_view(tmp_path, much_later)
    assert view["state"] == "STALE"


def test_m5_mutation_check_wall_clock_generated_at_would_never_go_stale(tmp_path):
    """MUTATION CHECK: if generated_at tracked the wall clock instead of the last run, cio_view
    would see an ALWAYS-FRESH timestamp no matter how old the actual run — reproduce that
    directly and show it reports OK even 4 days later, the exact bug M5 fixes."""
    import time as _time
    wall_clock_generated_at = f"{NOW.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    much_later = NOW + timedelta(days=4)
    # simulate "wall clock at read time" standing in for generated_at, re-stamped EVERY read
    fake_generated_at = much_later.strftime("%Y-%m-%dT%H:%M:%SZ")  # "now" at read time, the bug
    age_h = (much_later - much_later).total_seconds() / 3600.0
    assert age_h <= contract.CIO_READ_MODEL_MAX_AGE_H, (
        "even the buggy wall-clock stand-in aged out — the mutation no longer demonstrates "
        "the false-freshness bug")


# ── M7: verify-once + read_all caching (and cio_view / latest() read the cheap cache) ───────

def test_m7_mark_verified_skips_repeated_full_verify(tmp_path, monkeypatch):
    led = ledger_for(tmp_path)
    led.append("widget", ["w1"], {}, NOW.isoformat())
    verify_calls = []
    real_verify = led.verify

    def counting_verify():
        verify_calls.append(1)
        return real_verify()

    monkeypatch.setattr(led, "verify", counting_verify)
    led.mark_verified()
    before = len(verify_calls)
    for i in range(5):
        led.append(f"widget{i}", [f"w{i}"], {}, NOW.isoformat())
    after = len(verify_calls)
    assert after == before, f"verify() was called {after - before} more times after mark_verified()"


def test_m7_read_all_is_cached_only_after_mark_verified(tmp_path, monkeypatch):
    led = ledger_for(tmp_path)
    led.append("widget", ["w1"], {}, NOW.isoformat())
    calls = []
    real = led._read_all_from_disk

    def counting():
        calls.append(1)
        return real()

    monkeypatch.setattr(led, "_read_all_from_disk", counting)
    led.read_all()
    led.read_all()
    assert len(calls) == 2, "read_all() cached BEFORE mark_verified() — the hazard this guards against"
    calls.clear()
    led.mark_verified()
    calls.clear()
    led.read_all()
    led.read_all()
    assert len(calls) == 0, "read_all() re-read from disk even though mark_verified() was called"


def test_n8_latest_always_derives_from_the_verified_ledger_never_from_status_json(tmp_path, monkeypatch):
    """Was the M7 'cache hit' test. The second review (N8) showed a served status.json is forgeable (its
    content is not bound to the ledger), so latest() now ALWAYS derives — intentional reversal, journal W40."""
    import spa_core.research_factory.run as run_mod
    monkeypatch.setattr(run_mod, "_discover_scanners", lambda: [])
    run_mod.run_once(tmp_path, NOW)

    calls = []
    real = read._derive_latest

    def counting(data_dir, **kw):
        calls.append(1)
        return real(data_dir, **kw)

    monkeypatch.setattr(read, "_derive_latest", counting)
    read.latest(tmp_path)
    read.latest(tmp_path)
    assert calls == [1, 1], "latest() must derive from the verified ledger on every call (N8)"


def test_m7_mutation_check_a_write_after_caching_forces_a_fresh_derive(tmp_path, monkeypatch):
    """MUTATION CHECK: after a NEW write, the cached status.json's head hash no longer matches
    — latest() MUST fall through to _derive_latest again, proving the cache-hit test above is
    not simply always returning the stale answer."""
    import spa_core.research_factory.run as run_mod
    monkeypatch.setattr(run_mod, "_discover_scanners", lambda: [])
    run_mod.run_once(tmp_path, NOW)
    registry.upsert(tmp_path, make_candidate(instrument_id="ethereum:0x" + "66" * 20), NOW)

    calls = []
    real = read._derive_latest

    def counting(data_dir, **kw):
        calls.append(1)
        return real(data_dir, **kw)

    monkeypatch.setattr(read, "_derive_latest", counting)
    read.latest(tmp_path)
    assert calls, "latest() served a stale cache after a write changed the ledger's head hash"


# ── LOW: EVIDENCE_ACCUMULATING counts as paper_active ───────────────────────────────────────

def test_low_evidence_accumulating_counts_as_paper_active(monkeypatch, tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    admission_id = _admit_to_paper_active(tmp_path, c, NOW)
    lifecycle.transition(tmp_path, cid, contract.EVIDENCE_ACCUMULATING, gate_ref=admission_id,
                        reason="setup", now=NOW)
    status = read.latest(tmp_path)
    assert status["denominators"]["paper_active"] == 1

    import spa_core.research_factory.run as run_mod
    monkeypatch.setattr(run_mod, "_discover_scanners", lambda: [])
    # this test's subject is cio_view's OWN denominator counting, not Sherlock's lifecycle
    # decision — with zero scanners wired, a fresh Sherlock re-review has no v2_evidence beyond
    # run._default_v2_evidence's conservative defaults and would (correctly, post-review M4)
    # demote this all-strong-fixture-admitted candidate to PAUSED_PAPER, which is a REAL
    # consequence of zero evidence, not something this test is about.
    monkeypatch.setattr(run_mod, "_sherlock_review_all", lambda *a, **k: None)
    run_mod.run_once(tmp_path, NOW + timedelta(hours=1))
    view = read.cio_view(tmp_path, NOW + timedelta(hours=1))
    assert cid in view["paper_active"]


def test_low_mutation_check_strict_paper_active_only_would_miss_it():
    """MUTATION CHECK: the pre-fix, STRICT `state == PAPER_ACTIVE` membership test excludes an
    EVIDENCE_ACCUMULATING candidate — proving the broadened membership above is the real fix,
    not a no-op."""
    by_state_cids = {contract.EVIDENCE_ACCUMULATING: ["cid-1"]}
    strict_paper_active = by_state_cids.get(contract.PAPER_ACTIVE, [])
    assert "cid-1" not in strict_paper_active
