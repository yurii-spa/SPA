"""spa_core/tests/test_research_remediation_paper.py — post-implementation review remediation
(2026-10-04), five independent findings against the Research Factory's forward/lifecycle/replay/
http_client surface:

* N1 (HIGH)   — forward.py: a PAUSED_PAPER candidate must stop maturing (forward.py, forward.record).
* M6 (MEDIUM) — run.py: PAUSED_PAPER counts as a held exposure for dedup; a same-run ADMIT is seen
  by later candidates in the same Sherlock loop (run._sherlock_review_all).
* M3 (MEDIUM) — decision.py: replay() distinguishes "same verdict on new code" (REPLAY_CODE_CHANGED)
  from "verdict flipped on new code" (REPLAY_VERDICT_DRIFT).
* H1 LOWs     — http_client.py: a redirect's allow-list re-check is port-aware, and a relative
  Location header is resolved against the current URL before that check.
* N2 (LOW)    — run.py: a PAUSED_PAPER resume names the NEW ADMIT decision that triggered it,
  structurally (a ``resume_evidence`` ledger row), not only in free-text ``reason``.

Time is INJECTED throughout: every judgement here is made against the single anchor ``NOW`` (or
an offset derived from it), passed to the code under test as ``now=``. Nothing here asks the
wall clock anything.
# FROZEN-DATE-OK: injected-clock — the anchor NOW (and every NOW + timedelta(...) built from it)
# is passed as the `now=`/positional `now` argument to every lifecycle/forward/decision/http_client
# call in this file; no assertion compares a literal date to the real clock.

RESEARCH / PAPER only — real capital $0; nothing here moves money, signs or orders.

# LLM_FORBIDDEN
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import pytest

from spa_core.research_factory import admission_v2, bundle as bundle_mod, contract, \
    decision as decision_mod, evidence_contract as ec, forward, http_client, lifecycle, paper, registry
from spa_core.research_factory import run as run_mod
from spa_core.research_factory._common import ledger_for
from spa_core.tests import _research_evidence_v2_fixtures as v2fx

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)


# ── shared fixtures (same shape as test_research_evidence_core.py / test_research_factory_core.py) ─

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
                   network="ethereum", **overrides) -> dict:
    instrument_id = instrument_id or f"{network}:0x{'99' * 20}"
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
        "counterparty": {
            "roles": {r: {"state": contract.CP_DOCUMENTED, "name": "Acme"} for r in
                     contract.MECHANISMS[mechanism_id]["required_roles"]},
            "dimensions": {},
        },
    })
    c.update(overrides)
    return c


def _walk_to_paper_candidate(data_dir: Path, candidate: dict, now: datetime = NOW) -> None:
    cid = candidate["candidate_id"]
    registry.upsert(data_dir, candidate, now)
    for state in (contract.SCREENED, contract.RESEARCH_READY, contract.PAPER_CANDIDATE):
        lifecycle.transition(data_dir, cid, state, reason="setup", now=now)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# FIX 1 — N1 (HIGH): a PAUSED_PAPER candidate stops maturing
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_n1_paused_period_not_counted_resume_counts_again(tmp_path):
    """Positive control (the exact scenario named by the fix): admit, record COUNTED periods,
    pause, record N advancing periods (still fresh, still primary, still time-advancing — the
    ONLY thing that changed is the lifecycle state) — forward_periods must NOT move. Resume,
    record one more — forward_periods must advance by exactly 1."""
    c = make_candidate()
    cid = c["candidate_id"]
    admission_id = v2fx.admit_to_paper_active_v2(tmp_path, c, NOW)

    t1 = NOW + timedelta(hours=1)
    forward.record(tmp_path, cid, {
        "period": "p1", "backfill": False, "realised_index": None,
        "observed_return": _cell(contract.MEASURED, 0.05, as_of=t1.isoformat(), judge_now=t1)}, t1)
    t2 = NOW + timedelta(hours=2)
    forward.record(tmp_path, cid, {
        "period": "p2", "backfill": False, "realised_index": None,
        "observed_return": _cell(contract.MEASURED, 0.05, as_of=t2.isoformat(), judge_now=t2)}, t2)
    assert forward.forward_periods(tmp_path, cid) == 2

    lifecycle.transition(tmp_path, cid, contract.PAUSED_PAPER, reason="pause for test", now=t2)
    assert lifecycle.current_state(tmp_path, cid) == contract.PAUSED_PAPER

    last_t = t2
    for i in range(3, 6):  # N=3 advancing periods recorded WHILE paused
        t = NOW + timedelta(hours=i)
        entry = forward.record(tmp_path, cid, {
            "period": f"p{i}", "backfill": False, "realised_index": None,
            "observed_return": _cell(contract.MEASURED, 0.05, as_of=t.isoformat(), judge_now=t)}, t)
        assert entry["payload"]["counted"] is False
        assert entry["payload"]["reason"] == "paused: tracking only, not counted toward maturity"
        last_t = t
    assert forward.forward_periods(tmp_path, cid) == 2, "a paused period must never count toward maturity"

    # resume from PAUSED_PAPER back to its recorded paused_from (PAPER_ACTIVE here), same admission
    lifecycle.transition(tmp_path, cid, contract.PAPER_ACTIVE, gate_ref=admission_id,
                        reason="resume for test", now=last_t)
    assert lifecycle.current_state(tmp_path, cid) == contract.PAPER_ACTIVE

    t6 = NOW + timedelta(hours=6)
    forward.record(tmp_path, cid, {
        "period": "p6", "backfill": False, "realised_index": None,
        "observed_return": _cell(contract.MEASURED, 0.05, as_of=t6.isoformat(), judge_now=t6)}, t6)
    assert forward.forward_periods(tmp_path, cid) == 3, "a period recorded after resume must count again"


def test_mutation_check_n1_without_pause_guard_period_counts(tmp_path, monkeypatch):
    """MUTATION CHECK: forcing forward.py's OWN ``lifecycle.current_state`` lookup to always
    report PAPER_ACTIVE — exactly what the pre-fix code effectively did, since it never looked at
    lifecycle state at all — makes a period recorded during a REAL PAUSED_PAPER pause count
    anyway, proving the positive test above exercises a real guard, not a tautology."""
    c = make_candidate()
    cid = c["candidate_id"]
    v2fx.admit_to_paper_active_v2(tmp_path, c, NOW)

    t1 = NOW + timedelta(hours=1)
    forward.record(tmp_path, cid, {
        "period": "p1", "backfill": False, "realised_index": None,
        "observed_return": _cell(contract.MEASURED, 0.05, as_of=t1.isoformat(), judge_now=t1)}, t1)
    assert forward.forward_periods(tmp_path, cid) == 1

    lifecycle.transition(tmp_path, cid, contract.PAUSED_PAPER, reason="pause for test", now=t1)
    monkeypatch.setattr(forward.lifecycle, "current_state", lambda *a, **k: contract.PAPER_ACTIVE)

    t2 = NOW + timedelta(hours=2)
    forward.record(tmp_path, cid, {
        "period": "p2", "backfill": False, "realised_index": None,
        "observed_return": _cell(contract.MEASURED, 0.05, as_of=t2.isoformat(), judge_now=t2)}, t2)
    assert forward.forward_periods(tmp_path, cid) == 2, (
        "the old bug, reproduced: a period recorded while REALLY paused counted toward maturity "
        "because nothing ever asked the lifecycle state")


# ══════════════════════════════════════════════════════════════════════════════════════════════
# FIX 2 — M6 (MEDIUM): PAUSED_PAPER is a held exposure; a same-run ADMIT is seen mid-loop
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_m6a_paused_candidate_counts_as_held_exposure_for_dedup(tmp_path):
    """(a) a PAUSED_PAPER fund is STILL held on paper — a second copy of it, discovered later,
    must be caught by duplicate_exposure_clear exactly like an ADMITTED copy would be."""
    cand_a = make_candidate(mechanism_id="TOKENISED_TREASURY", domain="CASH_TREASURY",
                            instrument_id="ethereum:0x" + "33" * 20, underlying_root="fund:paused-fund")
    cid_a = cand_a["candidate_id"]
    v2fx.admit_to_paper_active_v2(tmp_path, cand_a, NOW)
    lifecycle.transition(tmp_path, cid_a, contract.PAUSED_PAPER, reason="pause for test", now=NOW)
    assert lifecycle.current_state(tmp_path, cid_a) == contract.PAUSED_PAPER

    cand_b = make_candidate(mechanism_id="TOKENISED_TREASURY", domain="CASH_TREASURY",
                            instrument_id="arbitrum:0x" + "44" * 20, underlying_root="fund:paused-fund")
    cid_b = cand_b["candidate_id"]
    registry.upsert(tmp_path, cand_b, NOW)
    for s in (contract.SCREENED, contract.RESEARCH_READY):
        lifecycle.transition(tmp_path, cid_b, s, reason="setup", now=NOW)

    all_candidates = {cid_a: cand_a, cid_b: cand_b}
    run_mod._sherlock_review_all(tmp_path, all_candidates, [], v2fx.DEFAULT_REGISTRY, [], {}, NOW)

    outcome = decision_mod.latest_decision(tmp_path, cid_b)
    assert outcome is not None
    assert outcome["decision"] != ec.ADMIT_TO_PAPER
    assert "duplicate_exposure_clear" in outcome["failed_gates"], outcome
    assert lifecycle.current_state(tmp_path, cid_b) != contract.PAPER_ACTIVE


def test_mutation_check_m6a_old_paper_states_only_misses_a_paused_duplicate(tmp_path):
    """MUTATION CHECK: rebuilding the SAME map the OLD way — membership in ``contract.
    PAPER_STATES`` alone, excluding PAUSED_PAPER — against the identical paused candidate above
    never sees its root at all, proving the fix (and the test above) is load-bearing."""
    cand_a = make_candidate(mechanism_id="TOKENISED_TREASURY", instrument_id="ethereum:0x" + "77" * 20,
                            underlying_root="fund:paused-fund-2")
    cid_a = cand_a["candidate_id"]
    v2fx.admit_to_paper_active_v2(tmp_path, cand_a, NOW)
    lifecycle.transition(tmp_path, cid_a, contract.PAUSED_PAPER, reason="pause for test", now=NOW)

    old_roots = {}
    for other_cid, other_candidate in {cid_a: cand_a}.items():
        other_state = lifecycle.current_state(tmp_path, other_cid)
        if other_state in contract.PAPER_STATES:  # the OLD, narrower membership test (pre-fix)
            root = other_candidate.get("underlying_root")
            if root:
                old_roots[root] = other_cid
    assert old_roots == {}, "the old bug, reproduced: a paused fund's root was invisible to dedup"


def test_m6b_a_candidate_admitted_mid_loop_is_seen_by_a_later_candidate_same_loop(tmp_path, monkeypatch):
    """(b) candidate A gets ADMITTED (reaches PAPER_ACTIVE) DURING this very Sherlock loop — a
    later candidate B in the SAME loop, sharing A's underlying_root, must see A as held exposure.
    The pre-loop snapshot (built once, before any candidate is reviewed) cannot know this by
    construction; only an update made DURING the loop can."""
    cand_a = make_candidate(mechanism_id="TOKENISED_TREASURY", instrument_id="ethereum:0x" + "55" * 20,
                            underlying_root="fund:same-run-fund")
    cid_a = cand_a["candidate_id"]
    cand_b = make_candidate(mechanism_id="TOKENISED_TREASURY", instrument_id="arbitrum:0x" + "66" * 20,
                            underlying_root="fund:same-run-fund")
    cid_b = cand_b["candidate_id"]
    # neither candidate has been touched yet — the pre-loop snapshot sees NEITHER as held
    # (admit_to_paper_active_v2 below does cand_a's ENTIRE walk itself, from a clean DISCOVERED).
    assert lifecycle.current_state(tmp_path, cid_a) is None
    assert lifecycle.current_state(tmp_path, cid_b) is None

    captured: dict = {}

    def fake_review(data_dir, cid, candidate, existing_book_roots, other_families, origins, facts_all,
                    v2_overrides, now, *, other_admitted_underlying_roots=None):
        if cid == cid_a:
            # simulate: A gets a real Sherlock ADMIT_TO_PAPER decision DURING this run's loop.
            v2fx.admit_to_paper_active_v2(data_dir, candidate, now)
            return
        captured["families"] = dict(other_families or {})
        captured["roots"] = dict(other_admitted_underlying_roots or {})

    monkeypatch.setattr(run_mod, "_sherlock_review_candidate", fake_review)

    all_candidates = {cid_a: cand_a, cid_b: cand_b}
    run_mod._sherlock_review_all(tmp_path, all_candidates, [], v2fx.DEFAULT_REGISTRY, [], {}, NOW)

    assert lifecycle.current_state(tmp_path, cid_a) == contract.PAPER_ACTIVE  # sanity: A really got admitted
    assert captured["roots"].get("fund:same-run-fund") == cid_a, (
        "B's review never saw A as a held exposure, even though A was admitted earlier in the SAME loop")


# ══════════════════════════════════════════════════════════════════════════════════════════════
# FIX 3 — M3 (MEDIUM): replay() distinguishes CODE_CHANGED from VERDICT_DRIFT
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _decision_only(tmp_path: Path, c: dict, now: datetime) -> dict:
    """Builds a real all-STRONG bundle + a real Sherlock ADMIT_TO_PAPER decision for ``c`` —
    WITHOUT touching the lifecycle at all (unlike ``v2fx.admit_to_paper_active_v2``). For a
    candidate that has ALREADY been walked/admitted/paused elsewhere in a test — re-walking it
    from SCREENED would refuse (it is no longer DISCOVERED)."""
    profile = v2fx.all_strong_profile(c["mechanism_id"])
    v2_evidence = v2fx.all_strong_v2_evidence(now)
    b = bundle_mod.build_bundle(c, profile=profile, v2_evidence=v2_evidence, facts=[],
                               paper_mode=ec.PAPER_MODE_HOLDABLE, registry=v2fx.DEFAULT_REGISTRY, now=now)
    bundle_mod.write_bundle(tmp_path, b, now)
    outcome = decision_mod.decide_and_record(tmp_path, b, c, extra={}, now=now)
    assert outcome["decision"] == ec.ADMIT_TO_PAPER
    return outcome


def _admitted_decision(tmp_path: Path, c: dict, now: datetime) -> dict:
    _walk_to_paper_candidate(tmp_path, c, now)
    return _decision_only(tmp_path, c, now)


def test_m3_replay_code_changed_when_verdict_is_unchanged(tmp_path, monkeypatch):
    """A code change that does not move the verdict (decision/failed_gates/unknowns/paper_mode/
    evidence_ceiling all stay the same) is REPLAY_CODE_CHANGED, with no 'diff' key — the SAME
    verdict, just not byte-identical because code_identity (and the decision_id digest that folds
    it in) differ on every code change by construction."""
    c = make_candidate()
    stored = _admitted_decision(tmp_path, c, NOW)

    monkeypatch.setattr(decision_mod, "code_identity", lambda: "a-different-code-identity")
    result = decision_mod.replay(tmp_path, stored["decision_id"])
    assert result["outcome"] == decision_mod.REPLAY_CODE_CHANGED
    assert result["decision"]["decision"] == stored["decision"]
    assert "diff" not in result


def test_m3_replay_verdict_drift_when_code_changed_and_the_verdict_flips(tmp_path, monkeypatch):
    """A code change that ALSO flips a gate's verdict is REPLAY_VERDICT_DRIFT, never the old
    (undifferentiated) REPLAY_CODE_CHANGED — and carries a field-level diff naming what moved."""
    c = make_candidate()
    stored = _admitted_decision(tmp_path, c, NOW)

    monkeypatch.setattr(decision_mod, "code_identity", lambda: "a-different-code-identity")
    monkeypatch.setitem(admission_v2._EVALUATORS, "identity_verified",
                        lambda bundle, candidate, extra, now: {"verdict": contract.GATE_FAIL,
                                                               "evidence": "mutated for test"})
    result = decision_mod.replay(tmp_path, stored["decision_id"])
    assert result["outcome"] == decision_mod.REPLAY_VERDICT_DRIFT
    assert result["decision"]["decision"] != stored["decision"]
    assert result["diff"], "a real verdict flip must carry a non-empty field-level diff"
    assert any(f in result["diff"] for f in ("decision", "failed_gates", "unknowns"))


def test_mutation_check_m3_old_replay_mislabelled_drift_as_code_changed(tmp_path, monkeypatch):
    """MUTATION CHECK: the pre-M3 ``replay()`` had exactly two branches — byte-identical MATCH,
    or (under a changed code_identity) CODE_CHANGED, full stop. Reproduced here with the SAME
    mutation as the VERDICT_DRIFT test above: the verdict genuinely flips, yet the old two-branch
    rule would have called it CODE_CHANGED — the very ambiguity M3 exists to remove."""
    c = make_candidate()
    stored = _admitted_decision(tmp_path, c, NOW)

    monkeypatch.setattr(decision_mod, "code_identity", lambda: "a-different-code-identity")
    monkeypatch.setitem(admission_v2._EVALUATORS, "identity_verified",
                        lambda bundle, candidate, extra, now: {"verdict": contract.GATE_FAIL,
                                                               "evidence": "mutated for test"})
    companion = decision_mod._find_companion(tmp_path, stored["candidate_id"], stored["decision_id"])
    bundle = bundle_mod.find_bundle(tmp_path, stored["candidate_id"], stored["bundle_digest"])
    fresh_report = admission_v2.evaluate(bundle, companion["candidate_snapshot"],
                                         companion.get("extra_snapshot") or {}, NOW)
    recomputed = decision_mod.decide(bundle, fresh_report, [], NOW)
    assert recomputed["decision"] != stored["decision"]  # the verdict really did flip

    old_outcome = "MATCH" if recomputed == stored else (
        "CODE_CHANGED" if decision_mod.code_identity() != stored.get("code_identity") else "RAISE")
    assert old_outcome == "CODE_CHANGED", "the old bug, reproduced: a real verdict flip hid under 'code changed'"


# ══════════════════════════════════════════════════════════════════════════════════════════════
# FIX 4 — H1 LOWs: http_client redirect allow-list is port-aware and resolves relative Location
# ══════════════════════════════════════════════════════════════════════════════════════════════

class _FakeResponse:
    def __init__(self, status: int, body: bytes = b"{}", headers: Optional[dict] = None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    def read(self, n: int) -> bytes:
        return self._body[:n]


def test_h1_low_redirect_to_same_host_different_port_is_refused():
    calls = {"n": 0}

    def transport(req, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResponse(302, headers={"Location": "https://api.binance.com:8443/api/v3/ticker"})
        return _FakeResponse(200, b"{}")  # never reached

    with pytest.raises(http_client.HttpRefused, match="allow-listed host"):
        http_client.fetch("https://api.binance.com/api/v3/ticker", now=NOW, transport=transport)


def test_h1_low_redirect_to_same_host_same_implicit_port_still_allowed():
    """Positive control for (a): both hops at the (unspecified, default) https port — 443 ==
    443 — must still be ALLOWED; the fix is port-AWARE, not port-paranoid."""
    calls = {"n": 0}

    def transport(req, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResponse(302, headers={"Location": "https://api.binance.com/api/v3/ticker"})
        return _FakeResponse(200, b"{}")

    status, _raw, _at = http_client.fetch("https://api.binance.com/api/v3/ticker", now=NOW, transport=transport)
    assert status == 200
    assert calls["n"] == 2


def test_mutation_check_h1_low_hostname_only_comparison_cannot_see_the_port():
    """MUTATION CHECK: the OLD redirect check compared ``urlsplit(...).hostname`` alone — and
    .hostname strips the port entirely, by design. Reproducing exactly that comparison on the
    SAME same-host-different-port redirect from the test above shows it would have matched (the
    old bug): host-only comparison is blind to the thing this fix adds."""
    old_host = urlsplit("https://api.binance.com/api/v3/ticker").hostname
    new_host = urlsplit("https://api.binance.com:8443/api/v3/ticker").hostname
    assert new_host == old_host, "the old bug, reproduced: hostname-only comparison cannot see the port at all"


def test_h1_low_relative_redirect_location_is_resolved_against_the_current_url():
    """(b) a relative Location (no scheme, no host — just a path, the common same-host-redirect
    shape) must be resolved against the CURRENT url before the allow-list re-check, not treated
    as leaving the host (scheme '') or skipped."""
    calls = {"n": 0}

    def transport(req, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResponse(302, headers={"Location": "/api/v3/avgPrice"})
        return _FakeResponse(200, b'{"ok": true}')

    status, raw, _at = http_client.fetch("https://api.binance.com/api/v3/ticker", now=NOW, transport=transport)
    assert status == 200
    assert calls["n"] == 2
    import json as _json
    assert _json.loads(raw) == {"ok": True}


def test_h1_low_relative_redirect_leaving_the_allow_list_path_is_still_refused():
    """The resolved, absolute URL still goes through the FULL allow-list check — a relative
    redirect to a disallowed path on the SAME host is refused exactly like an absolute one."""
    calls = {"n": 0}

    def transport(req, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResponse(302, headers={"Location": "/sapi/v1/account"})
        return _FakeResponse(200, b"{}")  # never reached

    with pytest.raises(http_client.HttpRefused):
        http_client.fetch("https://api.binance.com/api/v3/ticker", now=NOW, transport=transport)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# FIX 5 — N2 (LOW): resuming from PAUSED_PAPER names the NEW ADMIT decision structurally
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_n2_resume_paused_records_a_resume_evidence_row(tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    admission_id = v2fx.admit_to_paper_active_v2(tmp_path, c, NOW)

    # a real OPEN paper position under the pre-pause admission (_resume_paused refuses without one)
    decision_payload = decision_mod.latest_decision(tmp_path, cid)
    bundle = bundle_mod.latest_bundle(tmp_path, cid)
    snap = decision_mod.find_admission_snapshot_v2(tmp_path, cid, admission_id)
    paper.open_position(tmp_path, decision_payload, snap, bundle, NOW)

    lifecycle.transition(tmp_path, cid, contract.PAUSED_PAPER, reason="pause for test", now=NOW)

    # a NEW ADMIT_TO_PAPER decision — the one that triggers the resume (what run._admit_walk hands
    # _resume_paused as `outcome`); built fresh so its decision_id/bundle_digest differ from above.
    t_resume = NOW + timedelta(hours=1)
    new_outcome = _decision_only(tmp_path, c, t_resume)
    assert new_outcome["decision_id"] != decision_payload["decision_id"]

    run_mod._resume_paused(tmp_path, cid, new_outcome, t_resume)
    assert lifecycle.current_state(tmp_path, cid) == contract.PAPER_ACTIVE, "resume must succeed in this setup"

    rows = [e for e in ledger_for(tmp_path).read_all()
           if e["kind"] == "resume_evidence" and e["payload"].get("candidate_id") == cid]
    assert len(rows) == 1, "exactly one resume_evidence row for this resume"
    payload = rows[0]["payload"]
    assert payload["admission_id"] == admission_id
    assert payload["decision_id"] == new_outcome["decision_id"]
    assert payload["bundle_digest"] == new_outcome["bundle_digest"]


def test_n2_resume_paused_writes_no_row_when_the_resume_itself_is_refused(tmp_path):
    """MUTATION-ADJACENT negative control: when the resume is refused (no OPEN position here —
    _resume_paused was never given one), no resume_evidence row is written at all — the new row
    is additive evidence for a SUCCESSFUL resume, never a record of a refused one (that is what
    the existing run_warning row is for)."""
    c = make_candidate()
    cid = c["candidate_id"]
    v2fx.admit_to_paper_active_v2(tmp_path, c, NOW)
    lifecycle.transition(tmp_path, cid, contract.PAUSED_PAPER, reason="pause for test", now=NOW)

    t_resume = NOW + timedelta(hours=1)
    new_outcome = _decision_only(tmp_path, c, t_resume)
    run_mod._resume_paused(tmp_path, cid, new_outcome, t_resume)

    assert lifecycle.current_state(tmp_path, cid) == contract.PAUSED_PAPER, "no OPEN position — resume refused"
    rows = [e for e in ledger_for(tmp_path).read_all()
           if e["kind"] == "resume_evidence" and e["payload"].get("candidate_id") == cid]
    assert rows == []


# ══════════════════════════════════════════════════════════════════════════════════════════════
# N3 (second re-review, MEDIUM): paused rows are tracking — never a "miss" for the STALE rule
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _pause_then_resume_with_a_quiet_first_day(tmp_path):
    c = make_candidate()
    cid = c["candidate_id"]
    admission_id = v2fx.admit_to_paper_active_v2(tmp_path, c, NOW)
    t1 = NOW + timedelta(hours=1)
    forward.record(tmp_path, cid, {"period": "p1", "backfill": False, "realised_index": None,
                                   "observed_return": _cell(contract.MEASURED, 0.05, as_of=t1.isoformat(),
                                                            judge_now=t1)}, t1)
    lifecycle.transition(tmp_path, cid, contract.PAUSED_PAPER, reason="pause for test", now=t1)
    for i in (2, 3):
        t = NOW + timedelta(hours=i)
        forward.record(tmp_path, cid, {"period": f"p{i}", "backfill": False, "realised_index": None,
                                       "observed_return": _cell(contract.MEASURED, 0.05, as_of=t.isoformat(),
                                                                judge_now=t)}, t)
    t3 = NOW + timedelta(hours=3)
    lifecycle.transition(tmp_path, cid, contract.PAPER_ACTIVE, gate_ref=admission_id, reason="resume", now=t3)
    # first observation after resume: the upstream did NOT advance (a weekend for a business-day NAV)
    t4 = NOW + timedelta(hours=4)
    entry = forward.record(tmp_path, cid, {"period": "p4", "backfill": False, "realised_index": None,
                                           "observed_return": _cell(contract.MEASURED, 0.05, as_of=t1.isoformat(),
                                                                    judge_now=t4)}, t4)
    assert entry["payload"]["counted"] is False, "premise: the post-resume reading must be honestly uncounted"
    return cid


def test_n3_resume_then_one_quiet_day_is_not_stale(tmp_path):
    """Red without the fix: tail [paused, paused, not-advanced] = 3 not-counted ⇒ STALE on the
    first quiet day after a resume — the pause, meant as tracking only, became a staleness verdict."""
    cid = _pause_then_resume_with_a_quiet_first_day(tmp_path)
    assert lifecycle.current_state(tmp_path, cid) == contract.PAPER_ACTIVE


def test_mutation_check_n3_counting_paused_rows_as_misses_goes_stale(tmp_path, monkeypatch):
    """MUTATION CHECK: the pre-fix stale rule (every not-counted row is a miss, paused or not)
    sends the same scenario to STALE — the test above is pinned to the fix, not to the scene."""
    def _old_maybe_mark_stale(data_dir, candidate_id, now):
        rows = forward._observation_rows(ledger_for(data_dir), candidate_id)
        tail = rows[-contract.STALE_PERIODS_TO_STALE_STATE:]
        if len(tail) == contract.STALE_PERIODS_TO_STALE_STATE and \
                all(not (r.get("payload") or {}).get("counted") for r in tail) and \
                lifecycle.current_state(data_dir, candidate_id) in contract.PAPER_STATES:
            lifecycle.transition(data_dir, candidate_id, contract.STALE_STATE, reason="old rule", now=now)

    monkeypatch.setattr(forward, "_maybe_mark_stale", _old_maybe_mark_stale)
    cid = _pause_then_resume_with_a_quiet_first_day(tmp_path)
    assert lifecycle.current_state(tmp_path, cid) == contract.STALE_STATE
