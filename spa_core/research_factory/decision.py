"""spa_core/research_factory/decision.py — Sherlock's deterministic decision (ADR-564 review #7/#15).

``decide()`` is a pure function: precedence REJECT > HOLD > STALE > NEEDS_MORE_EVIDENCE > ADMIT_TO_PAPER
(``evidence_contract.DECISION_PRECEDENCE``), exactly the fields of ``DECISION_FIELDS``.
``decide_and_record`` is the persistence wrapper ``run.py`` calls: it evaluates the 20 v2 gates,
decides, and writes BOTH the decision row (kind ``admission_decision``) and a companion row (kind
``admission_v2_report``) carrying the exact admission_v2 report + the prior-bundle digests used —
without that companion, a later :func:`replay` could not reproduce the decision byte-identically,
because the 20-gate report depends on ``extra`` (book/exposure state at decision time) that is not
itself part of the stored bundle or decision.

Sherlock (``head_of_research``) decides research admission; it never moves money, signs, or orders
(``decided_by_role="head_of_research"``, ``authority_over_capital="NONE"``, both frozen fields on
every decision).

# LLM_FORBIDDEN
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from spa_core.research_factory import admission_v2
from spa_core.research_factory import bundle as bundle_mod
from spa_core.research_factory import contract as c1
from spa_core.research_factory import evidence_contract as ec
from spa_core.research_factory._common import code_identity, iso as _iso, ledger_for
from spa_core.utils.hash_ledger import DuplicateKey


class ReplayError(Exception):
    """A decision/companion/bundle row needed for replay cannot be found."""


class ReplayMismatch(Exception):
    """Replay recomputed a DIFFERENT decision than the one stored — the stored decision is not
    reproducible from its own recorded inputs (a code/contract change, or a corrupted row)."""


_CRITICAL_DIMENSIONS = ("RETURN", "COST", "COUNTERPARTY", "PRIMARY_IDENTITY")


def _required_next_evidence(decision: str, bundle: dict, failed_gates: list, unknown_gates: list) -> list:
    if decision == ec.ADMIT_TO_PAPER:
        return []
    if decision == ec.REJECT:
        return ["REJECT is terminal for THIS evidence — a materially different candidate/mechanism "
               "or a corrected on-chain identity would be needed, not more evidence of the same claim"]
    out = [f"{gate}: evidence for {', '.join(ec.GATE_INPUTS.get(gate, ())) or 'this gate'} "
          f"is missing or insufficient" for gate in sorted(set(failed_gates) | set(unknown_gates))]
    if decision == ec.HOLD:
        out.append("resolve the CONFLICTED critical input(s) with an independent, agreeing origin")
    if decision == ec.DECISION_STALE:
        out.append("a fresh reading on the stale dimension(s), advancing past the frozen-value limit")
    return out


def decide(bundle: dict, report: dict, prior_bundles: list, now: datetime) -> dict:
    """``(bundle, report, prior_bundles, now) -> ResearchAdmissionDecision`` — a pure function;
    the same four inputs always produce the same output (``replay`` depends on exactly this)."""
    mechanism_id = bundle.get("mechanism_id")
    gates = report.get("gates") or {}
    grades = bundle.get("grades") or {}
    conflicts = set(bundle.get("conflicts") or [])
    stale = set(bundle.get("stale_evidence") or [])
    unknown_dims = set(bundle.get("unknowns") or [])

    # net_expected_return lives on return_evidence (this package's own admission concern) —
    # paper_accounting_evidence is E2's frozen shape and carries no such key.
    net = (bundle.get("return_evidence") or {}).get("net_expected_return") or {}
    net_nonpositive = net.get("state") in (c1.MEASURED, c1.ESTIMATED_WITH_METHOD) \
        and isinstance(net.get("value"), (int, float)) and net["value"] <= 0
    identity_mismatch = grades.get("PRIMARY_IDENTITY") == ec.CONFLICTED

    failed_gates = sorted(g for g, v in gates.items() if v.get("verdict") == ec.FAIL)
    unknown_gates = sorted(g for g, v in gates.items() if v.get("verdict") == ec.GATE_UNKNOWN)

    decision = None
    rationale: list = []

    if mechanism_id not in c1.MECHANISMS:
        decision = ec.REJECT
        rationale.append(f"mechanism {mechanism_id!r} is not in contract.MECHANISMS")
    elif identity_mismatch:
        decision = ec.REJECT
        rationale.append("on-chain identity CONTRADICTS the claimed instrument (PRIMARY_IDENTITY CONFLICTED)")
    elif net_nonpositive:
        decision = ec.REJECT
        rationale.append(f"net_expected_return is {net.get('state')} and <= 0 (value={net.get('value')})")

    if decision is None and (conflicts & set(_CRITICAL_DIMENSIONS)):
        decision = ec.HOLD
        rationale.append(f"critical input(s) CONFLICTED: {sorted(conflicts & set(_CRITICAL_DIMENSIONS))}")

    if decision is None and stale:
        was_adequate = any((pb.get("grades") or {}).get(dim) in (ec.ADEQUATE, ec.STRONG)
                          for pb in prior_bundles for dim in stale)
        if was_adequate:
            decision = ec.DECISION_STALE
            rationale.append(f"dimension(s) STALE after a prior >= ADEQUATE reading: {sorted(stale)}")

    if decision is None and (failed_gates or unknown_gates):
        decision = ec.NEEDS_MORE_EVIDENCE
        rationale.append(f"gate(s) not PASS/NOT_APPLICABLE: failed={failed_gates} unknown={unknown_gates}")

    if decision is None:
        decision = ec.ADMIT_TO_PAPER
        rationale.append("every ADMISSION_V2_GATES gate PASS or NOT_APPLICABLE")

    required_next = _required_next_evidence(decision, bundle, failed_gates, unknown_gates)
    now_str = _iso(now)
    decision_id = c1.digest({
        "candidate_id": bundle.get("candidate_id"), "bundle_digest": bundle.get("evidence_digest"),
        "decision": decision, "policy_version": ec.POLICY_VERSION, "code_identity": code_identity(),
        "now": now_str,
    })[:24]

    payload = {
        "schema_version": ec.SCHEMA_DECISION, "decision_id": decision_id,
        "candidate_id": bundle.get("candidate_id"), "generated_at": now_str,
        "evidence_cutoff": bundle.get("evidence_cutoff"), "decision": decision,
        "failed_gates": failed_gates, "unknowns": sorted(unknown_dims | set(unknown_gates)),
        "conflicts": sorted(conflicts), "rationale": rationale,
        "evidence_refs": bundle.get("source_roots") or [], "required_next_evidence": required_next,
        "policy_version": ec.POLICY_VERSION, "source_snapshot_digest": bundle.get("evidence_digest"),
        "bundle_digest": bundle.get("evidence_digest"), "code_identity": code_identity(), "now": now_str,
        "input_digests": {"bundle": bundle.get("evidence_digest"), "report": c1.digest(report)},
        "paper_mode": bundle.get("paper_mode"), "evidence_ceiling": bundle.get("evidence_ceiling"),
        "issuer_asserted_roles": bundle.get("issuer_asserted_roles") or [],
        "circularity_concerns": bundle.get("circularity_concerns") or [],
        "decided_by_role": ec.ROLE_ID, "authority_over_capital": ec.AUTHORITY_OVER_CAPITAL,
    }
    assert set(payload) == set(ec.DECISION_FIELDS)
    return payload


# ── persistence ───────────────────────────────────────────────────────────────────────────────
def write_decision(data_dir: Path, payload: dict) -> dict:
    ledger = ledger_for(data_dir)
    key = ["admission_decision", payload["candidate_id"], payload["decision_id"]]
    try:
        return ledger.append("admission_decision", key, payload, payload["generated_at"])
    except DuplicateKey as dup:
        return dup.existing


def find_decision(data_dir: Path, decision_id: str) -> Optional[dict]:
    ledger = ledger_for(data_dir)
    for e in ledger.read_all():
        if e.get("kind") == "admission_decision" and (e.get("payload") or {}).get("decision_id") == decision_id:
            return e.get("payload")
    return None


def latest_decision(data_dir: Path, candidate_id: str) -> Optional[dict]:
    ledger = ledger_for(data_dir)
    best = None
    for e in ledger.read_all():
        if e.get("kind") == "admission_decision" and (e.get("payload") or {}).get("candidate_id") == candidate_id:
            if best is None or e["seq"] > best["seq"]:
                best = e
    return best.get("payload") if best else None


def _write_companion(data_dir: Path, companion: dict) -> dict:
    ledger = ledger_for(data_dir)
    key = ["admission_v2_report", companion["candidate_id"], companion["decision_id"]]
    try:
        return ledger.append("admission_v2_report", key, companion, companion["now"])
    except DuplicateKey as dup:
        return dup.existing


def _find_companion(data_dir: Path, candidate_id: str, decision_id: str) -> Optional[dict]:
    ledger = ledger_for(data_dir)
    for e in ledger.read_all():
        if e.get("kind") == "admission_v2_report":
            p = e.get("payload") or {}
            if p.get("candidate_id") == candidate_id and p.get("decision_id") == decision_id:
                return p
    return None


def decide_and_record(data_dir: Path, bundle: dict, candidate: dict, extra: Optional[dict],
                      now: datetime) -> dict:
    """Evaluates the 20 v2 gates, decides, and persists the decision + the companion row replay
    needs. ``bundle`` must already be written (:func:`bundle.write_bundle`) by the caller.

    Post-implementation review M3 (2026-10-04): the companion now carries the ACTUAL
    ``candidate``/``extra`` snapshots used (not just their digests alone — a digest with nothing
    to re-hash from is an integrity check with no input) PLUS their digests, so
    :func:`replay` can recompute ``admission_v2.evaluate()`` itself from the SAME inputs, not
    merely re-run ``decide()`` over an already-computed report (which only tests ``decide()``'s
    own determinism, never the 20 gates' own reproducibility)."""
    extra = extra or {}
    report = admission_v2.evaluate(bundle, candidate, extra, now)
    prior_bundles = [b for b in bundle_mod.all_bundles(data_dir, bundle["candidate_id"])
                    if b.get("evidence_digest") != bundle.get("evidence_digest")]
    payload = decide(bundle, report, prior_bundles, now)
    row = write_decision(data_dir, payload)
    final_payload = row.get("payload") or payload
    companion = {
        "candidate_id": final_payload["candidate_id"], "decision_id": final_payload["decision_id"],
        "bundle_digest": bundle.get("evidence_digest"), "report": report,
        "prior_bundle_digests": sorted({b.get("evidence_digest") for b in prior_bundles}),
        "now": final_payload["now"],
        "candidate_snapshot": candidate, "candidate_digest": c1.digest(candidate),
        "extra_snapshot": extra, "extra_digest": c1.digest(extra),
    }
    _write_companion(data_dir, companion)
    return final_payload


def write_admission_snapshot_v2(data_dir: Path, decision_payload: dict, bundle: dict, now: datetime) -> dict:
    """The ``paper-admission/2`` snapshot — the ONLY thing ``lifecycle.py`` accepts as ``gate_ref``
    into PAPER_ACTIVE/EVIDENCE_ACCUMULATING (ADR-564 binding #1). Only call this once
    ``decision_payload["decision"] == evidence_contract.ADMIT_TO_PAPER``."""
    if decision_payload.get("decision") != ec.ADMIT_TO_PAPER:
        raise ValueError("write_admission_snapshot_v2 called on a non-ADMIT_TO_PAPER decision")
    ledger = ledger_for(data_dir)
    at = _iso(now)
    admission_id = c1.digest({
        "candidate_id": decision_payload["candidate_id"], "decision_id": decision_payload["decision_id"],
        "bundle_digest": bundle["evidence_digest"],
    })[:24]
    payload = {
        "schema": ec.SCHEMA_ADMISSION_V2, "admission_id": admission_id,
        "candidate_id": decision_payload["candidate_id"], "decision_id": decision_payload["decision_id"],
        "bundle_digest": bundle["evidence_digest"], "policy_version": ec.POLICY_VERSION,
        "paper_mode": bundle.get("paper_mode"), "evidence_ceiling": bundle.get("evidence_ceiling"),
        "as_of": at, "recorded_at": at, "code_identity": code_identity(),
    }
    assert set(payload) == set(ec.ADMISSION_V2_FIELDS)
    key = ["paper_admission_v2", payload["candidate_id"], admission_id]
    try:
        return ledger.append("paper_admission_v2", key, payload, at)
    except DuplicateKey as dup:
        return dup.existing


def find_admission_snapshot_v2(data_dir: Path, candidate_id: str, admission_id: str) -> Optional[dict]:
    ledger = ledger_for(data_dir)
    for e in ledger.read_all():
        if e.get("kind") == "paper_admission_v2":
            p = e.get("payload") or {}
            if p.get("candidate_id") == candidate_id and p.get("admission_id") == admission_id:
                return p
    return None


#: replay() outcomes — MATCH is the only one meaning "reproduced exactly"; CODE_CHANGED names a
#: real, EXPECTED cause of divergence (the code evolved since recording, but the VERDICT —
#: decision/failed_gates/unknowns/paper_mode/evidence_ceiling — is still the same one — not a
#: bug); VERDICT_DRIFT (M3, post-implementation review, 2026-10-04) names the OTHER case a code
#: change can cause: the verdict itself actually flipped, distinguishable from CODE_CHANGED only
#: by comparing those named fields, never by full-payload equality (``decision_id``/
#: ``code_identity`` differ on EVERY code change regardless of the verdict, by construction —
#: see ``decide()``'s own ``decision_id`` digest, which folds in ``code_identity()``). Only a
#: divergence with an UNCHANGED code_identity is a genuine mismatch and still raises.
REPLAY_MATCH, REPLAY_CODE_CHANGED, REPLAY_VERDICT_DRIFT = "MATCH", "CODE_CHANGED", "VERDICT_DRIFT"

#: the fields that define "the same verdict" for replay()'s CODE_CHANGED/VERDICT_DRIFT split —
#: everything else (rationale wording, decision_id, generated_at, code_identity, ...) is either
#: volatile by construction or free-text that can legitimately reword without the verdict moving.
_VERDICT_FIELDS = ("decision", "failed_gates", "unknowns", "paper_mode", "evidence_ceiling")


def replay(data_dir: Path, decision_id: str) -> dict:
    """Recomputes ``admission_v2.evaluate()`` AND ``decide()`` from the companion's stored
    ``candidate_snapshot``/``extra_snapshot`` and the stored bundle/prior-bundles/``now`` (review
    #15 + post-implementation review M3, 2026-10-04 — recomputing the 20-GATE REPORT itself,
    not just re-running ``decide()`` over an already-computed report, is what actually tests
    whether admission_v2.py is reproducible). Raises :class:`ReplayError` when a needed row is
    missing. Returns ``{"outcome", "decision", ...}``:

    * ``REPLAY_MATCH`` — recomputed decision is byte-identical to the stored one.
    * ``REPLAY_CODE_CHANGED`` — the payload is NOT byte-identical and ``code_identity()`` differs
      from the one recorded at decision time, but the VERDICT (``_VERDICT_FIELDS`` — decision,
      failed_gates, unknowns, paper_mode, evidence_ceiling) is still the SAME: the code changed
      since (every code change moves ``decision_id``/``code_identity``, by construction — see
      ``decide()``), but it changed nothing this candidate's admission actually turned on. Named,
      expected, never raised.
    * ``REPLAY_VERDICT_DRIFT`` (M3, post-implementation review 2026-10-04) — the payload is not
      byte-identical, ``code_identity()`` differs, AND the verdict itself is DIFFERENT: the code
      change actually flipped this candidate's admission outcome. Before this outcome existed,
      ANY code change made ``REPLAY_CODE_CHANGED`` fire regardless of whether the verdict moved —
      "same verdict on new code" and "verdict flipped on new code" were the same, unexaminable
      bucket. ``"diff"`` carries ``{field: {"stored", "recomputed"}}`` for every ``_VERDICT_FIELDS``
      entry that actually changed. Named, never raised — a reader decides whether that drift is
      acceptable; replay's job is only to NAME it, not to judge it.

    A divergence where ``code_identity()`` is UNCHANGED is always a genuine reproducibility
    failure (``decide()``/``admission_v2.evaluate()`` are pure — same code, same inputs, same
    output) and still raises :class:`ReplayMismatch` — never silently accepted as a match or a
    drift."""
    stored = find_decision(data_dir, decision_id)
    if stored is None:
        raise ReplayError(f"no admission_decision {decision_id!r} on this ledger")
    companion = _find_companion(data_dir, stored["candidate_id"], decision_id)
    if companion is None:
        raise ReplayError(f"no admission_v2_report companion for decision {decision_id!r} — cannot replay")
    bundle = bundle_mod.find_bundle(data_dir, stored["candidate_id"], stored["bundle_digest"])
    if bundle is None:
        raise ReplayError(f"bundle {stored['bundle_digest']!r} for decision {decision_id!r} not found")
    prior_bundles = []
    for digest in companion.get("prior_bundle_digests") or []:
        prior = bundle_mod.find_bundle(data_dir, stored["candidate_id"], digest)
        if prior is None:
            raise ReplayError(f"prior bundle {digest!r} referenced by decision {decision_id!r} not found")
        prior_bundles.append(prior)
    now = c1.parse_ts(stored["now"])
    if now is None:
        raise ReplayError(f"decision {decision_id!r} has an unparseable 'now' ({stored.get('now')!r})")
    candidate_snapshot = companion.get("candidate_snapshot")
    if candidate_snapshot is None:
        raise ReplayError(f"decision {decision_id!r}'s companion carries no candidate_snapshot — "
                          f"cannot recompute admission_v2.evaluate() (pre-M3 companion row?)")
    extra_snapshot = companion.get("extra_snapshot") or {}

    fresh_report = admission_v2.evaluate(bundle, candidate_snapshot, extra_snapshot, now)
    recomputed = decide(bundle, fresh_report, prior_bundles, now)
    if recomputed == stored:
        return {"outcome": REPLAY_MATCH, "decision": recomputed}

    current_identity = code_identity()
    stored_identity = stored.get("code_identity")
    if current_identity == stored_identity:
        raise ReplayMismatch(f"replay of {decision_id!r} does not reproduce the stored decision byte-for-byte, "
                             f"and code_identity is UNCHANGED ({current_identity!r}) — a genuine divergence")

    # M3: code_identity (and therefore decision_id, which folds it in) differs on EVERY code
    # change — that alone never tells us whether the VERDICT moved. Compare only the fields that
    # define "the same verdict" (_VERDICT_FIELDS) to split CODE_CHANGED from VERDICT_DRIFT.
    diff = {f: {"stored": stored.get(f), "recomputed": recomputed.get(f)} for f in _VERDICT_FIELDS
           if stored.get(f) != recomputed.get(f)}
    if not diff:
        return {"outcome": REPLAY_CODE_CHANGED, "decision": recomputed, "stored": stored,
               "current_code_identity": current_identity, "stored_code_identity": stored_identity}
    return {"outcome": REPLAY_VERDICT_DRIFT, "decision": recomputed, "stored": stored,
           "current_code_identity": current_identity, "stored_code_identity": stored_identity, "diff": diff}
