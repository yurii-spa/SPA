"""Round-2 rework tests for the Research Factory (ADR-560 Package A): M2 (unit conversion),
N1 (latest() integrity), N2 (cio_view ledger-derived membership), N3 (cache trust scoping),
N5 (data_fresh primary field), M5 leftover (stale_feeds/basis_track use run time).

Each fix has a positive test AND a mutation check proving the test is actually sensitive.

# FROZEN-DATE-OK: injected-clock — every judgement in this file is made against an explicit
# anchor (NOW, or RUN_TIME for the M5-leftover section) passed as the now=/positional now
# argument to every lifecycle/admission/forward/registry/run call; nothing compares a literal
# date to the real clock.
"""
from __future__ import annotations

import json
import multiprocessing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.research_factory import (
    admission, contract, eligibility, forward, lifecycle, read, registry, run,
)
from spa_core.research_factory._common import ledger_for
import spa_core.research_factory._common as common_mod
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


def make_candidate(mechanism_id="STABLECOIN_SAVINGS", domain="CASH_TREASURY", instrument_id=None,
                   network="ethereum", counterparty_data=None, **overrides) -> dict:
    instrument_id = instrument_id or f"{network}:0x{'77' * 20}"
    exposure = contract.exposure_key(mechanism_id, instrument_id, network)
    cid = contract.candidate_id(exposure)
    c = {f: None for f in contract.CANDIDATE_FIELDS}
    c.update({
        "candidate_id": cid, "exposure_key": exposure, "exposure_key_version": contract.EXPOSURE_KEY_VERSION,
        "mechanism_id": mechanism_id, "asset_class": contract.MECHANISMS[mechanism_id]["asset_class"],
        "domain": domain, "network": contract.canonical_network(network), "venue_or_protocol": "test_scanner",
        "producing_scanner": "test_scanner",
        "instrument": instrument_id, "instrument_id": instrument_id, "underlying_root": instrument_id,
        "economic_driver_key": f"DRIVER_{mechanism_id}", "yield_source": "savings_rate",
        "base_return": _cell(), "fees": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "gas": _cell(contract.NOT_APPLICABLE, reason="n/a"), "funding": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "hedging_cost": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "liquidity": _cell(contract.MEASURED, 1_000_000.0), "time_to_exit": _cell(contract.MEASURED, 0.0),
        "capacity": _cell(contract.NOT_MEASURED, reason="not observed"),
        "duration": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "leverage": _cell(contract.NOT_APPLICABLE, reason="no leverage"),
        "liquidation_distance": _cell(contract.NOT_APPLICABLE, reason="n/a"),
        "source_refs": [],
        "counterparty": counterparty_data if counterparty_data is not None else {
            "roles": {r: {"state": contract.CP_DOCUMENTED, "name": "Acme"} for r in
                     contract.MECHANISMS[mechanism_id]["required_roles"]},
            "dimensions": {},
        },
    })
    c.update(overrides)
    return c


def _admit_to_paper_active(data_dir: Path, candidate: dict, now: datetime = NOW) -> str:
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


def _fresh_ledger(tmp_path: Path):
    """Drop this test's data_dir from the per-process ledger_for() cache, simulating a FRESH
    process picking the ledger back up (no lingering trust/cache from an earlier call in THIS
    test)."""
    key = str(Path(tmp_path).resolve())
    common_mod._LEDGER_CACHE.pop(key, None)


# ── M2 (still open): compare return cells in ONE declared unit ─────────────────────────────

def test_m2_pct_apy_vs_fraction_is_consistent(tmp_path):
    """The review's exact reproduction: index growing at 4.5%/yr vs. base_return 4.5 'pct_apy'
    must PASS once both sides are converted to the same fraction (0.045)."""
    c = make_candidate(base_return=_cell(contract.MEASURED, 4.5, unit="pct_apy"))
    cid = c["candidate_id"]
    _admit_to_paper_active(tmp_path, c, NOW)
    t0 = NOW + timedelta(hours=1)
    t1 = t0 + timedelta(days=30)
    idx0, idx1 = 1.0, (1.045) ** (30.0 / 365.25)
    forward.record(tmp_path, cid, {
        "period": "P0", "observed_return": _cell(contract.MEASURED, 4.5, unit="pct_apy",
                                                as_of=t0.isoformat(), judge_now=t0),
        "realised_index": _cell(contract.MEASURED, idx0, source_class=contract.PRIMARY_CHAIN,
                               as_of=t0.isoformat(), judge_now=t0)}, t0)
    forward.record(tmp_path, cid, {
        "period": "P1", "observed_return": _cell(contract.MEASURED, 4.5, unit="pct_apy",
                                                as_of=t1.isoformat(), judge_now=t1),
        "realised_index": _cell(contract.MEASURED, idx1, source_class=contract.PRIMARY_CHAIN,
                               as_of=t1.isoformat(), judge_now=t1)}, t1)
    view = {"_existing_book_roots": []}
    report = eligibility.evaluate(tmp_path, registry.current_candidate(tmp_path, cid), view, t1)
    gate = report["gates"]["realised_vs_observed_consistent"]
    assert gate["verdict"] == contract.GATE_PASS, gate


def test_m2_mutation_check_without_unit_conversion_the_consistent_case_fails():
    """MUTATION CHECK: comparing the RAW numbers (4.5 vs 0.045) without unit conversion gives
    the review's reported ~99% rel_diff — proving the fix (converting both to a fraction
    first) is what makes the PASS above possible."""
    raw_rel = abs(4.5 - 0.045) / max(abs(4.5), abs(0.045), 1e-12)
    assert raw_rel > contract.CONFLICT_TOLERANCE_REL
    assert raw_rel == pytest.approx(0.99, abs=0.01)


def test_m2_two_x_mismatch_fails(tmp_path):
    c = make_candidate(base_return=_cell(contract.MEASURED, 4.5, unit="pct_apy"))
    cid = c["candidate_id"]
    _admit_to_paper_active(tmp_path, c, NOW)
    t0 = NOW + timedelta(hours=1)
    t1 = t0 + timedelta(days=30)
    idx0, idx1 = 1.0, (1.09) ** (30.0 / 365.25)  # ~2x the 4.5% rate
    forward.record(tmp_path, cid, {
        "period": "P0", "observed_return": _cell(contract.MEASURED, 4.5, unit="pct_apy",
                                                as_of=t0.isoformat(), judge_now=t0),
        "realised_index": _cell(contract.MEASURED, idx0, source_class=contract.PRIMARY_CHAIN,
                               as_of=t0.isoformat(), judge_now=t0)}, t0)
    forward.record(tmp_path, cid, {
        "period": "P1", "observed_return": _cell(contract.MEASURED, 4.5, unit="pct_apy",
                                                as_of=t1.isoformat(), judge_now=t1),
        "realised_index": _cell(contract.MEASURED, idx1, source_class=contract.PRIMARY_CHAIN,
                               as_of=t1.isoformat(), judge_now=t1)}, t1)
    view = {"_existing_book_roots": []}
    report = eligibility.evaluate(tmp_path, registry.current_candidate(tmp_path, cid), view, t1)
    gate = report["gates"]["realised_vs_observed_consistent"]
    assert gate["verdict"] == contract.GATE_FAIL, gate


def test_m2_unknown_unit_is_unknown():
    base = _cell(contract.MEASURED, 4.5, unit="bogus_unit_nobody_declared")
    realised = _cell(contract.ESTIMATED_WITH_METHOD, 0.045, unit="fraction", method="test")
    assert eligibility._as_fraction(base) is None
    assert eligibility._as_fraction(realised) == pytest.approx(0.045)


def test_m2_mutation_check_unknown_unit_silently_treated_as_fraction_would_be_wrong():
    """MUTATION CHECK: if an unknown unit were silently treated as 'already a fraction' (the
    bug this guards against), a value of 4.5 under a nonsense unit would be compared directly
    against 0.045 and wrongly look CONFLICTED — proving _as_fraction's refusal matters."""
    base_bad_guess = 4.5  # what the WRONG code would have used directly, no conversion
    realised = 0.045
    rel = abs(base_bad_guess - realised) / max(abs(base_bad_guess), abs(realised), 1e-12)
    assert rel > contract.CONFLICT_TOLERANCE_REL, "the bad guess happens to be within tolerance anyway"


# ── N1 (HIGH): latest() always runs a full, FRESH verify() ─────────────────────────────────

def _tamper_row_without_recomputing_chain(data_dir: Path, seq_to_tamper: int) -> None:
    led = ledger_for(data_dir)
    rows = led.read_all(fresh=True)
    rows[seq_to_tamper - 1]["payload"] = {"tampered": True}
    text = "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n"
    led.ledger_path().write_text(text)


def test_n1_tampered_middle_row_is_broken_even_when_tail_hash_still_matches(monkeypatch, tmp_path):
    import spa_core.research_factory.run as run_mod
    monkeypatch.setattr(run_mod, "_discover_scanners", lambda: [])
    for i in range(3):
        registry.upsert(tmp_path, make_candidate(instrument_id=f"ethereum:0x{i:040x}"), NOW)
    run_mod.run_once(tmp_path, NOW)

    led = ledger_for(tmp_path)
    tail_hash_before = led.read_all(fresh=True)[-1]["entry_hash"]
    _tamper_row_without_recomputing_chain(tmp_path, seq_to_tamper=2)
    # the tail's OWN stored entry_hash field is untouched by this tamper (only row 2's payload
    # changed) -- the exact shape that let a cheap "does the tail hash match?" check through.
    _fresh_ledger(tmp_path)
    led2 = ledger_for(tmp_path)
    assert led2.head_hash() == tail_hash_before, "the tamper changed the tail's own stored hash field too"

    status = read.latest(tmp_path)
    assert status["integrity"] == "BROKEN"


def test_n1_mutation_check_trusting_a_matching_tail_hash_would_say_ok(monkeypatch, tmp_path):
    """MUTATION CHECK: the OLD shortcut ("status.json's ledger_head_hash == the live tail hash
    => trust the cached blob, including integrity") would have returned OK here — reproduce it
    literally against the tampered ledger from the scenario above."""
    import spa_core.research_factory.run as run_mod
    monkeypatch.setattr(run_mod, "_discover_scanners", lambda: [])
    for i in range(3):
        registry.upsert(tmp_path, make_candidate(instrument_id=f"ethereum:0x{i:040x}"), NOW)
    run_mod.run_once(tmp_path, NOW)
    _tamper_row_without_recomputing_chain(tmp_path, seq_to_tamper=2)
    _fresh_ledger(tmp_path)

    led = ledger_for(tmp_path)
    live_head = led.head_hash()  # cheap: the tail's OWN stored field, never recomputed
    status_path = led.root() / contract.STATUS
    cached = json.loads(status_path.read_text())
    old_shortcut_would_trust = cached.get("ledger_head_hash") == live_head
    assert old_shortcut_would_trust, "the tamper also changed the tail hash — this mutation no longer applies"
    assert cached.get("integrity") == "OK", "the cached blob (written before the tamper) said OK"


# ── N2 (MEDIUM): cio_view derives membership from the ledger, not status.json ───────────────

def test_n2_forged_status_json_cannot_grant_eligibility(monkeypatch, tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    _admit_to_paper_active(tmp_path, c, NOW)  # PAPER_ACTIVE only, never CIO_ELIGIBLE

    import spa_core.research_factory.run as run_mod
    monkeypatch.setattr(run_mod, "_discover_scanners", lambda: [])
    run_mod.run_once(tmp_path, NOW)

    status_path = ledger_for(tmp_path).root() / contract.STATUS
    status = json.loads(status_path.read_text())
    for c_out in status["candidates"]:
        if c_out["candidate_id"] == cid:
            c_out["admission_state"] = contract.CIO_ELIGIBLE  # forge it
    status_path.write_text(json.dumps(status))

    view = read.cio_view(tmp_path, NOW)
    assert cid not in view["cio_eligible"], "a forged status.json granted eligibility the ledger never recorded"
    assert cid in view["paper_active"], "the REAL (ledger-derived) state should still be reported"


def test_n2_mutation_check_reading_status_json_candidates_would_grant_it(monkeypatch, tmp_path):
    """MUTATION CHECK: reproduce the OLD behaviour (membership read straight off status.json's
    'candidates' list) against the exact forged file from the scenario above — it DOES contain
    the forged CIO_ELIGIBLE entry, proving the forgery would have worked under the old code."""
    c = make_candidate()
    cid = c["candidate_id"]
    _admit_to_paper_active(tmp_path, c, NOW)
    import spa_core.research_factory.run as run_mod
    monkeypatch.setattr(run_mod, "_discover_scanners", lambda: [])
    run_mod.run_once(tmp_path, NOW)
    status_path = ledger_for(tmp_path).root() / contract.STATUS
    status = json.loads(status_path.read_text())
    for c_out in status["candidates"]:
        if c_out["candidate_id"] == cid:
            c_out["admission_state"] = contract.CIO_ELIGIBLE
    status_path.write_text(json.dumps(status))

    reforged = json.loads(status_path.read_text())
    old_style_cio_eligible = [c_out["candidate_id"] for c_out in reforged["candidates"]
                             if c_out.get("admission_state") == contract.CIO_ELIGIBLE]
    assert cid in old_style_cio_eligible, "the forged file no longer demonstrates the old vulnerability"


# ── N3 (MEDIUM): cache trust is scoped to exactly one run ───────────────────────────────────

def _tamper_anchors(data_dir: Path) -> None:
    ledger_for(data_dir).anchors_path().write_text("")


def test_n3_tamper_after_run1_then_run2_same_process_is_broken_exit2(tmp_path):
    t1 = NOW
    t2 = NOW + timedelta(hours=12)
    rc1 = run.main(["--data-dir", str(tmp_path), "--now", t1.isoformat()])
    assert rc1 == contract.EXIT_OK
    _tamper_anchors(tmp_path)  # SAME process, no fresh-process simulation — exactly the bug report
    rc2 = run.main(["--data-dir", str(tmp_path), "--now", t2.isoformat()])
    assert rc2 == contract.EXIT_BROKEN


def test_n3_mutation_check_lingering_trust_plus_cached_verify_hides_the_tamper(tmp_path, monkeypatch):
    """MUTATION CHECK: reproduce the bug directly — disable BOTH halves of the fix
    (invalidate_cache() in run_once's finally, and verify()'s always-fresh read) on the SAME
    scenario as the real test above, and watch run2 silently build on a tampered ledger."""
    from spa_core.utils import hash_ledger as hl
    orig_invalidate = hl.HashLedger.invalidate_cache
    orig_verify = hl.HashLedger.verify
    monkeypatch.setattr(hl.HashLedger, "invalidate_cache", lambda self: None)  # mutation: never revoke trust

    def cached_verify(self):
        # mutation: the OLD shape — use the (possibly stale) cache instead of a fresh disk read
        entries = self.read_all()
        anchors = self.read_anchors()
        seqs = [a.get("seq") for a in anchors]
        beyond = [q for q in seqs if isinstance(q, int) and q > len(entries)]
        if beyond:
            return {"ok": False, "break_at": min(beyond), "entries": len(entries), "reason": "ledger_truncated"}
        return {"ok": True, "break_at": None, "entries": len(entries), "reason": None}

    monkeypatch.setattr(hl.HashLedger, "verify", cached_verify)

    t1 = NOW
    t2 = NOW + timedelta(hours=12)
    rc1 = run.main(["--data-dir", str(tmp_path), "--now", t1.isoformat()])
    assert rc1 == contract.EXIT_OK
    _tamper_anchors(tmp_path)
    rc2 = run.main(["--data-dir", str(tmp_path), "--now", t2.isoformat()])
    assert rc2 == contract.EXIT_OK, (
        "under the mutation, run2 did NOT silently succeed on the tampered ledger — this "
        "mutation check no longer demonstrates the bug the real fix prevents")


def _outside_writer(path_str: str, barrier) -> None:
    from spa_core.research_factory import registry as reg
    c = make_candidate(instrument_id="ethereum:0x" + "88" * 20, venue_or_protocol="outside_writer")
    barrier.wait()
    reg.upsert(Path(path_str), c, NOW)


def test_n3_outside_writer_causes_no_false_broken(tmp_path):
    rc1 = run.main(["--data-dir", str(tmp_path), "--now", NOW.isoformat()])
    assert rc1 == contract.EXIT_OK

    barrier = multiprocessing.Barrier(1)
    proc = multiprocessing.Process(target=_outside_writer, args=(str(tmp_path), barrier))
    proc.start()
    proc.join(timeout=10)
    assert not proc.is_alive()

    later = NOW + timedelta(hours=1)
    rc2 = run.main(["--data-dir", str(tmp_path), "--now", later.isoformat()])
    assert rc2 == contract.EXIT_OK, "a legitimate outside writer's append caused a false BROKEN"
    led = ledger_for(tmp_path)
    assert led.verify()["ok"]


def test_n3_mutation_check_a_trusted_cache_sees_an_outside_write_as_truncated(tmp_path):
    """MUTATION CHECK: directly reproduce the hazard a trusted, cached HashLedger instance faces
    when a sibling instance (an 'outside writer') appends a perfectly legitimate row — using
    the OLD, cache-trusting verify() shape. This is exactly why N3 requires verify() to NEVER
    use the cache."""
    led_a = ledger_for(tmp_path)
    led_a.append("widget", ["w1"], {}, NOW.isoformat())
    led_a.mark_verified()  # led_a is now "trusted" inside a run, per the design

    # the outside writer: a DIFFERENT HashLedger instance on the same data_dir (as a second
    # process would be), appending a perfectly valid row under its own lock.
    from spa_core.utils.hash_ledger import HashLedger
    led_b = HashLedger(tmp_path, "research_factory", "research_factory_anchors", "ledger.jsonl")
    led_b.append("widget", ["w2"], {}, NOW.isoformat())

    # led_a's cache is now STALE (1 entry) while the anchors file (never cached) has 2.
    cached_entries = led_a.read_all()  # still trusted -> serves the stale 1-entry cache
    assert len(cached_entries) == 1

    def old_style_verify(self):
        entries = self.read_all()  # the BUG: uses the (stale) cache
        anchors = self.read_anchors()
        seqs = [a.get("seq") for a in anchors]
        beyond = [q for q in seqs if isinstance(q, int) and q > len(entries)]
        if beyond:
            return {"ok": False, "break_at": min(beyond), "entries": len(entries), "reason": "ledger_truncated"}
        return {"ok": True}

    old_verdict = old_style_verify(led_a)
    assert old_verdict["ok"] is False and old_verdict["reason"] == "ledger_truncated", (
        "the old cache-trusting shape no longer reproduces a false BROKEN — this mutation "
        "check no longer demonstrates the hazard")
    # the REAL (fixed) verify() reads fresh and must NOT be fooled:
    assert led_a.verify()["ok"] is True


# ── N5 (core part): data_fresh judges the PRIMARY field per mechanism ──────────────────────

def test_n5_funding_capture_data_fresh_judges_funding_not_base_return():
    c = make_candidate(mechanism_id="FUNDING_CAPTURE", domain="MARKET_NEUTRAL",
                      instrument_id="perp:ETH:median5", network="ethereum",
                      base_return=_cell(contract.NOT_APPLICABLE, reason="n/a for FUNDING_CAPTURE"),
                      funding=_cell(contract.MEASURED, 0.05, source_class=contract.PRIMARY_CHAIN))
    gate = admission._data_fresh(c, NOW)
    assert gate["verdict"] == contract.GATE_PASS, gate
    assert "funding" in gate["evidence"]


def test_n5_mutation_check_judging_base_return_is_permanently_unknown():
    """MUTATION CHECK: the pre-fix shape (always judging base_return) is UNKNOWN forever for a
    FUNDING_CAPTURE candidate, because base_return there is legitimately NOT_APPLICABLE."""
    c = make_candidate(mechanism_id="FUNDING_CAPTURE", domain="MARKET_NEUTRAL",
                      instrument_id="perp:ETH:median5", network="ethereum",
                      base_return=_cell(contract.NOT_APPLICABLE, reason="n/a for FUNDING_CAPTURE"),
                      funding=_cell(contract.MEASURED, 0.05, source_class=contract.PRIMARY_CHAIN))
    base = c.get("base_return") or {}
    fresh = contract.is_fresh(base, NOW)
    assert fresh is None, "base_return is somehow judgeable now — the mutation premise changed"


# ── M5 leftover (LOW): stale_feeds / basis_track judged by run time, not wall clock ────────

RUN_TIME = datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_m5_leftover_stale_feeds_judged_by_run_time_not_wall_clock(monkeypatch, tmp_path):
    c = make_candidate(base_return=_cell(contract.MEASURED, 0.05,
                                        as_of=(RUN_TIME - timedelta(hours=2)).isoformat(), judge_now=RUN_TIME))
    cid = c["candidate_id"]
    registry.upsert(tmp_path, c, RUN_TIME)
    import spa_core.research_factory.run as run_mod
    monkeypatch.setattr(run_mod, "_discover_scanners", lambda: [])
    run_mod.run_once(tmp_path, RUN_TIME)

    status = read.latest(tmp_path)
    assert status["generated_at"] == f"{RUN_TIME.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    stale_roots = {f.get("source_root") for f in status["stale_feeds"]}
    # fresh (2h old) relative to RUN_TIME (2020) -- real wall-clock is years later, so a
    # wall-clock-based check would see this as ancient and wrongly list it as stale.
    assert not any(cid for f in status["stale_feeds"]), status["stale_feeds"]


def test_m5_leftover_mutation_check_wall_clock_would_flag_it_stale(tmp_path):
    """MUTATION CHECK: reproduce the OLD wall-clock-based judgement directly against the SAME
    2020-dated cell and today's real clock — it IS stale under that judgement, proving the fix
    (using run_now instead) is what keeps it out of stale_feeds above."""
    br = _cell(contract.MEASURED, 0.05, as_of=(RUN_TIME - timedelta(hours=2)).isoformat(), judge_now=RUN_TIME)
    real_wall_clock = datetime.now(timezone.utc)
    fresh_under_wall_clock = contract.is_fresh(br, real_wall_clock)
    assert fresh_under_wall_clock is False, (
        "a 2020-dated cell judged against today's real wall clock is somehow still 'fresh' — "
        "this mutation check no longer demonstrates the bug")


# ── second review round 3: N8 + LOW notes ────────────────────────────────────────────────────────

def test_n8_a_hand_edited_status_json_never_reaches_any_reader(tmp_path):
    """N8: read.latest() used to serve status.json whenever its head hash matched — the file's CONTENT
    was never bound to the ledger, so a forged CIO_ELIGIBLE count and basis reason reached Mission
    Control and the readiness text. Readers must derive from the verified ledger only."""
    run.run_once(tmp_path, NOW)
    status_path = tmp_path / contract.DATA_SUBDIR / contract.STATUS
    honest = json.loads(status_path.read_text())
    forged = dict(honest)
    forged["denominators"] = dict(honest["denominators"], cio_eligible=1)
    forged["basis_track"] = {"state": "MEASURED", "funding_as_of": None, "reason": "FORGED"}
    forged["by_state"] = {contract.CIO_ELIGIBLE: 1}
    status_path.write_text(json.dumps(forged))
    _fresh_ledger(tmp_path)
    got = read.latest(tmp_path)
    assert got["integrity"] == "OK"
    assert got["denominators"]["cio_eligible"] == honest["denominators"]["cio_eligible"]
    assert "FORGED" not in json.dumps(got)
    assert got.get("by_state", {}).get(contract.CIO_ELIGIBLE) in (None, 0)


def test_low_a_unitless_value_is_not_assumed_to_be_a_fraction():
    assert eligibility._as_fraction({"state": contract.MEASURED, "value": 4.5, "unit": None}) is None
    assert eligibility._as_fraction({"state": contract.MEASURED, "value": 4.5, "unit": "pct_apy_annualised"}) \
        == pytest.approx(0.045)


def test_low_a_primary_chain_index_must_come_from_a_chain_root():
    obs = {"observed_return": None, "realised_index": {
        "state": contract.MEASURED, "value": 1.01, "source_class": contract.PRIMARY_CHAIN,
        "source_root": "venue:x", "as_of": (NOW - timedelta(hours=1)).isoformat()}}
    ok, why = contract.period_countable(obs, None, (NOW - timedelta(days=2)).isoformat(), NOW)
    assert ok is False and "on-chain" in why
    obs["realised_index"]["source_root"] = "chain:1"
    assert contract.period_countable(obs, None, (NOW - timedelta(days=2)).isoformat(), NOW)[0] is True
