"""
spa_core/api/routers/riskwire.py — the RISKWIRE proof / "check us" surface (WS1.4).

RISKWIRE is measurement-as-a-product; its whole credibility is "don't trust us, check us". This router
serves the COMPLETE proof of every RISKWIRE deliverable VERBATIM (uncapped, raw bytes) so a third party
can re-derive every hash on a clean machine with the zero-dependency scripts/verify_riskwire.py — the
SAME pattern the DFB / underwriting / rates-desk proof surfaces publish.

  • GET /api/riskwire/proof        — a machine-readable index: for EACH artifact (measurements,
    day30_review) the wrapper metadata + head_hash + artifact_hash + a LIVE verify_artifact result +
    a FRESHNESS verdict (age_hours / stale / fresh_within_hours) + the reproduce block. The verdict is
    computed by the SAME proof code the standalone verifier mirrors, so the server never claims a
    verification it cannot reproduce.

TWO INDEPENDENT VERDICTS, never conflated: `verified` = the hash chain re-derives (integrity);
`stale` = the artifact is older than the SAME budget `d_riskwire.*` grades it with in
system_health_monitor (currency). A perfectly-verified snapshot can be weeks old — saying only
"verified" would let an outsider read an old measurement as today's risk, so the index also publishes
`any_stale`. fail-CLOSED both ways: missing/unparseable `generated_at` ⇒ stale:true.
  • GET /api/riskwire/proof/{artifact}  — the complete artifact (measurements | day30_review) served
    VERBATIM (the full row chain, uncapped) for offline re-derivation.

This surface is NOT flag-gated: verifiability of the proof chain is always available (the data files are
always written; only the PUBLIC report/oracle PRODUCT surfaces are owner-flag-gated — that gate lives in
the report/oracle routers, not here). Read-only. fail-CLOSED: a missing/corrupt artifact yields an
honest present:false / verified:false, never a fabricated pass. NO spa_core write, NO execution import.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException

from spa_core.api._shared import data_dir, scrub_nonfinite

log = logging.getLogger("spa.api")

router = APIRouter(tags=["riskwire"])

# artifact name → (relative path, verify-kind). "measurements" = row-chain + head + artifact_hash;
# "day30" = WS1.3's review_hash.
_ARTIFACTS = {
    "measurements": ("riskwire/measurements.json", "measurements"),
    "day30_review": ("riskwire/day30_review.json", "day30"),
}

_CANONICAL_JSON_RULE = "json.dumps(obj, sort_keys=True, separators=(',',':'), default=str)"

_DISCLAIMER = (
    "RISKWIRE proof surface — read-only. Every artifact is served VERBATIM so a third party can "
    "re-derive every row_hash + head_hash + artifact_hash with zero spa_core import. Advisory; moves "
    "no capital, never touches the go-live track. "
    "`verified` means the hash chain re-derives — it does NOT mean the artifact is CURRENT: read "
    "`generated_at` / `age_hours` / `stale` for that. A stale artifact is a faithfully-hashed "
    "snapshot of an OLD measurement, not today's risk."
)


def _fresh_within_hours(name: str) -> float:
    """Staleness budget (hours) for an artifact — the SAME constants the health monitor grades with.

    Imported, never re-declared: `d_riskwire.measurements.fresh` / `d_riskwire.day30.fresh` and this
    surface must call the same artifact stale at the same moment, or the public "check us" page and
    the internal health report would disagree about the same file.
    """
    from spa_core.monitoring.system_health_monitor import (
        RISKWIRE_DAY30_FRESH_D,
        RISKWIRE_MEASUREMENTS_FRESH_H,
    )

    return RISKWIRE_DAY30_FRESH_D * 24.0 if name == "day30_review" else RISKWIRE_MEASUREMENTS_FRESH_H


def _freshness(name: str, doc: dict) -> dict:
    """age_hours + stale for one artifact. fail-CLOSED: an absent/unparseable `generated_at` reads
    STALE (we cannot prove it is current, so we never claim it is)."""
    from spa_core.monitoring.system_health_monitor import _age_hours

    budget = _fresh_within_hours(name)
    age = _age_hours(doc.get("generated_at"))
    return {
        "age_hours": None if age is None else round(age, 1),
        "stale": True if age is None else bool(age > budget),
        "fresh_within_hours": budget,
    }


def _reproduce_block(files: list, note: str) -> dict:
    return {
        "spec_version": "1.0",
        "spec": "docs/PROOF_CHAIN_SPEC.md",
        "canonical_json_rule": _CANONICAL_JSON_RULE,
        "hash": "sha256(canonical_json).hexdigest()",
        "public_files": files,
        "verify_with": "python3 scripts/verify_riskwire.py " + " ".join(files),
        "verifier": "scripts/verify_riskwire.py (zero-dependency, no spa_core import)",
        "note": note,
    }


def _read_artifact(rel: str) -> dict | None:
    """Load a RISKWIRE artifact VERBATIM. None on missing/corrupt (fail-CLOSED — never fabricate)."""
    path = data_dir() / rel
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return doc if isinstance(doc, dict) else None


@router.get("/api/riskwire/proof")
def get_riskwire_proof():
    """The RISKWIRE proof INDEX — every artifact's anchor + a LIVE verification verdict.

    Runs spa_core.riskwire.proof.verify_artifact over each published artifact (the SAME recipe
    verify_riskwire.py reproduces), so the server's `verified` flag is the honest re-derivation, not a
    stored claim. Each artifact additionally carries `age_hours` / `stale` / `fresh_within_hours`
    (the health monitor's own budgets) so integrity is never mistaken for currency.
    fail-CLOSED: a missing artifact reads present:false / verified:false / stale:true."""
    from spa_core.riskwire import proof as rw_proof

    artifacts = {}
    all_verified = True
    any_stale = False
    for name, (rel, kind) in _ARTIFACTS.items():
        doc = _read_artifact(rel)
        if doc is None:
            artifacts[name] = {"present": False, "verified": False,
                               "age_hours": None, "stale": True,
                               "fresh_within_hours": _fresh_within_hours(name),
                               "note": f"{rel} missing/corrupt (fail-CLOSED)"}
            all_verified = False
            any_stale = True          # absent cannot be current — fail-CLOSED
            continue
        # each deliverable is verified with ITS OWN published scheme (measurements: row-chain +
        # head + artifact_hash; day30: WS1.3's review_hash).
        res = (rw_proof.verify_day30_review(doc) if kind == "day30"
               else rw_proof.verify_artifact(doc, kind))
        artifacts[name] = {
            "present": True,
            "verified": bool(res["valid"]),
            "schema": doc.get("schema"),
            "generated_at": doc.get("generated_at"),
            "as_of": doc.get("as_of"),
            "n_rows": res.get("n_rows"),
            "head_hash": res.get("head_hash"),
            "artifact_hash": res.get("artifact_hash"),
            "review_hash": res.get("review_hash"),
            "broken_at": res.get("broken_at"),
            "note": res.get("note"),
        }
        fresh = _freshness(name, doc)
        artifacts[name].update(fresh)
        all_verified = all_verified and bool(res["valid"])
        any_stale = any_stale or fresh["stale"]

    body = {
        "model": "riskwire_proof_index",
        "is_advisory": True,
        "all_verified": all_verified,
        "any_stale": any_stale,
        "artifacts": artifacts,
        "disclaimer": _DISCLAIMER,
        "reproduce": _reproduce_block(
            ["measurements.json", "day30_review.json"],
            "For each artifact: walk the row chain (row[0].prev_hash='0'*64; each prev_hash==prior "
            "row_hash; row_hash=sha256(canonical({body,prev_hash}))); require head_hash==last row_hash; "
            "require artifact_hash=sha256(canonical(wrapper minus artifact_hash)). Zero spa_core import."),
    }
    return scrub_nonfinite(body)


@router.get("/api/riskwire/proof/{artifact}")
def get_riskwire_artifact(artifact: str):
    """The COMPLETE artifact (measurements | day30_review) served VERBATIM (uncapped) for offline
    re-derivation. 404 on an unknown artifact name or a missing file (fail-CLOSED — never a stub)."""
    entry = _ARTIFACTS.get(artifact)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown riskwire artifact {artifact!r}")
    rel, _kind = entry
    doc = _read_artifact(rel)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"{rel} not published yet")
    # Served VERBATIM — the row chain uncapped, exactly as written, so the recompute matches to the byte.
    return scrub_nonfinite(doc)
