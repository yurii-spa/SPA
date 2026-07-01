"""
spa_core/riskwire/proof.py — the UNIFIED RISKWIRE proof-chain glue (WS1.4).

RISKWIRE defines NO NEW hashing scheme. It reuses the SAME per-row sha256-over-canonical-JSON chain
pattern DFB's `risk_overlay` uses (genesis "0"*64; each row's `prev_hash` = the previous row's
`row_hash`; `row_hash` = sha256 over the canonical body + prev_hash, the body being the published row
minus its own chain-linkage envelope). A third party reproduces every `row_hash` from the published
`measurements.json` with zero `spa_core` import — "don't trust us, check us".

WS1.4 — ONE proof surface over EVERY RISKWIRE deliverable
---------------------------------------------------------
The product line has more than one deliverable, each with its OWN published proof scheme (WS1.4 verifies
what each deliverable actually published; it never re-imposes a scheme on another workstream's output):

  • the WS1.2 unified per-subject MEASUREMENTS snapshot — a per-row proof CHAIN + a per-artifact anchor:
      1. PER-ROW proof — every measurement row carries prev_hash + row_hash, linked into ONE
         single-genesis chain. Binds BOTH the published INPUTS and OUTPUTS of each row: forge a
         `risk_class` / `native_verdict` / an exit cell → the recompute diverges at that exact row.
      2. PER-ARTIFACT proof — the wrapper carries an `artifact_hash` over its canonical body (the
         wrapper MINUS its own envelope) that BINDS the chain head (`head_hash`) plus the metadata
         (schema, as_of, counts). Tamper a count/schema, or splice/drop a row → head shifts →
         artifact_hash diverges. So the proof covers the artifact as a whole, not just row-by-row.

  • the WS1.3 DAY-30 REVIEW (spa_core.riskwire.day30_review) — a single per-artifact `review_hash` =
    sha256(canonical(review MINUS {review_hash, generated_at}; nested day30_artifact.generated_at
    also stripped)). WS1.4 VERIFIES this scheme byte-identically (it does NOT re-hash or fork the
    review — WS1.3 owns it); `verify_day30_review` reproduces day30_review.compute_review_hash without
    importing it, so the standalone verifier stays zero-dependency.

Both are reproduced, with zero spa_core import, by ONE verifier: scripts/verify_riskwire.py (a sibling
of verify_spa.py / verify_dfb_pool.py). This module holds only the chain/anchor plumbing + the
measurements builder; all measurement CONTENT is produced by the seeds (WS1.2 facade), and the day-30
CONTENT + review_hash are produced by WS1.3 — WS1.4 re-scores nothing.

stdlib-only, deterministic, fail-CLOSED, atomic (writes confined to data/riskwire/), PURE, LLM-FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.riskwire import RiskWireMeasurement

# The per-row proof-chain genesis (identical to DFB's DFB_GENESIS_PREV — one shared pattern).
RISKWIRE_GENESIS_PREV = "0" * 64

# The chain-linkage envelope keys stripped before hashing the signed body.
_ENVELOPE_KEYS = ("prev_hash", "row_hash")

# The per-artifact envelope keys — the wrapper's OWN chain-linkage, stripped before the artifact hash.
_ARTIFACT_ENVELOPE_KEYS = ("artifact_hash",)

# The one canonical-JSON rule (PROOF_CHAIN_SPEC §2), reproduced verbatim by the standalone verifier.
CANONICAL_JSON_RULE = "json.dumps(obj, sort_keys=True, separators=(',',':'), default=str)"

MEASUREMENTS_SCHEMA = "riskwire_measurements_v1"


def canonical_body(m: RiskWireMeasurement) -> dict:
    """The signed body = the full published row (to_dict) MINUS the chain-linkage envelope
    (prev_hash / row_hash). The SINGLE definition used by both the writer and the verifier, so a
    third party reproduces row_hash from the published row exactly."""
    return {k: v for k, v in m.to_dict().items() if k not in _ENVELOPE_KEYS}


def row_hash(body: dict, prev_hash: str) -> str:
    """sha256 over the canonical sorted-JSON of {body, prev_hash} — the per-row chain link.
    Reproducible by anyone from the published row (matches the DFB `_row_hash` recipe)."""
    blob = json.dumps({"body": body, "prev_hash": prev_hash}, sort_keys=True,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def finalize(m: RiskWireMeasurement) -> RiskWireMeasurement:
    """Stamp the row_hash over the measurement's OWN canonical body (computed from to_dict, so verify
    and write agree to the byte). Returns a new frozen measurement with row_hash set."""
    rh = row_hash(canonical_body(m), m.prev_hash)
    return dataclasses.replace(m, row_hash=rh)


def chain(measurements: List[RiskWireMeasurement]) -> List[RiskWireMeasurement]:
    """Link an ordered list into ONE contiguous single-genesis chain: each row's prev_hash = the
    previous row's row_hash; genesis '0'*64. Returns NEW finalized measurements. Deterministic."""
    out: List[RiskWireMeasurement] = []
    prev = RISKWIRE_GENESIS_PREV
    for m in measurements:
        linked = dataclasses.replace(m, prev_hash=prev, row_hash="")
        sealed = finalize(linked)
        out.append(sealed)
        prev = sealed.row_hash
    return out


def verify_chain(measurements: List[RiskWireMeasurement]) -> bool:
    """Verify the per-row proof chain: each row's prev_hash links the previous row's row_hash, and each
    row_hash recomputes from the published body. fail-CLOSED. (genesis '0'*64.)"""
    prev = RISKWIRE_GENESIS_PREV
    for m in measurements:
        if m.prev_hash != prev:
            return False
        if row_hash(canonical_body(m), m.prev_hash) != m.row_hash:
            return False
        prev = m.row_hash
    return True


def verify_rows(rows: List[dict]) -> dict:
    """Verify PUBLISHED rows (plain dicts, as written to measurements.json) as ONE chain — the standalone
    verifier surface. Walk in order: (1) prev_hash == previous row_hash (genesis '0'*64), (2) row_hash
    recomputes over the published body. Returns {valid, length, broken_at, head_hash}. fail-CLOSED."""
    prev = RISKWIRE_GENESIS_PREV
    head = None
    n = len(rows)
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if row.get("prev_hash") != prev:
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        body = {k: v for k, v in row.items() if k not in _ENVELOPE_KEYS}
        if row_hash(body, prev) != row.get("row_hash"):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        prev = row["row_hash"]
        head = row["row_hash"]
    return {"valid": True, "length": n, "broken_at": None, "head_hash": head}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# PER-ARTIFACT PROOF — binds the whole deliverable (wrapper metadata + chain head) into one anchor
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def artifact_hash(artifact_body: Dict[str, Any]) -> str:
    """The per-artifact anchor: sha256 over the canonical JSON of the artifact body (the published
    wrapper MINUS its own `artifact_hash` envelope). The body includes `head_hash` (the chain head) so
    this hash TRANSITIVELY binds every row, PLUS the wrapper metadata (schema, as_of, the counts). A
    third party reproduces it from the published artifact exactly. Deterministic / PURE."""
    body = {k: v for k, v in artifact_body.items() if k not in _ARTIFACT_ENVELOPE_KEYS}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def verify_artifact(artifact: Dict[str, Any], rows_key: str) -> dict:
    """Verify a WHOLE published RISKWIRE artifact (the wrapper dict with a `rows_key` row list) as one
    proof unit — the standalone-verifier surface.

    Three fail-CLOSED gates, in order:
      1. the row chain under `rows_key` re-derives (verify_rows) → gives the head_hash,
      2. the wrapper's published `head_hash` equals that re-derived chain head (the wrapper cannot claim
         a head its rows do not produce),
      3. the wrapper's published `artifact_hash` re-derives over the wrapper body (binds schema / as_of /
         counts / head_hash — a forged count or a spliced/dropped row shifts the head and breaks this).

    Returns {valid, n_rows, broken_at, head_hash, artifact_hash}. fail-CLOSED on any missing/typed-wrong
    field. An empty artifact (0 rows) is still checked (head None, artifact hash over the wrapper)."""
    if not isinstance(artifact, dict):
        return {"valid": False, "n_rows": 0, "broken_at": None,
                "head_hash": None, "artifact_hash": None, "note": "artifact is not a JSON object"}
    rows = artifact.get(rows_key)
    if not isinstance(rows, list):
        return {"valid": False, "n_rows": 0, "broken_at": None, "head_hash": None,
                "artifact_hash": None, "note": f"missing/invalid '{rows_key}' row list"}
    chain_res = verify_rows(rows)
    if not chain_res["valid"]:
        return {"valid": False, "n_rows": len(rows), "broken_at": chain_res["broken_at"],
                "head_hash": None, "artifact_hash": None,
                "note": f"row chain broke at index {chain_res['broken_at']}"}
    head = chain_res["head_hash"]
    claimed_head = artifact.get("head_hash")
    if claimed_head != head:
        return {"valid": False, "n_rows": len(rows), "broken_at": "head_hash", "head_hash": head,
                "artifact_hash": None,
                "note": f"wrapper head_hash {str(claimed_head)[:16]}… != re-derived chain head "
                        f"{str(head)[:16]}… (rows spliced/dropped/reordered)"}
    recomputed = artifact_hash(artifact)
    claimed_artifact = artifact.get("artifact_hash")
    if recomputed != claimed_artifact:
        return {"valid": False, "n_rows": len(rows), "broken_at": "artifact_hash", "head_hash": head,
                "artifact_hash": recomputed,
                "note": f"artifact_hash mismatch: recomputed {recomputed[:16]}… != published "
                        f"{str(claimed_artifact)[:16]}… (wrapper metadata/head altered after the fact)"}
    return {"valid": True, "n_rows": len(rows), "broken_at": None,
            "head_hash": head, "artifact_hash": recomputed, "note": "ok"}


def seal_artifact(body: Dict[str, Any], rows_key: str) -> Dict[str, Any]:
    """Given a wrapper body that ALREADY carries its chained rows under `rows_key`, stamp `head_hash`
    (the last row's row_hash, or None on an empty artifact) and `artifact_hash` (over the body incl. the
    head). Returns a NEW dict. Deterministic; the exact inverse of `verify_artifact`."""
    rows = body.get(rows_key) or []
    head = rows[-1]["row_hash"] if rows else None
    sealed = {**body, "head_hash": head}
    sealed["artifact_hash"] = artifact_hash(sealed)
    return sealed


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# DELIVERABLE BUILDERS — the two WS1.2 / WS1.3 artifacts, hash-anchored deterministically
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def build_measurements_artifact(measurements: List[RiskWireMeasurement], *,
                                generated_at: str, as_of: Optional[str]) -> Dict[str, Any]:
    """Build the unified MEASUREMENTS snapshot artifact (WS1.2 deliverable) — the wrapper an outsider
    downloads and verifies. Chains the measurements (single genesis), then seals the wrapper with
    head_hash + artifact_hash. `generated_at` is an explicit input (deterministic tests). Deterministic:
    same measurements + same generated_at → byte-identical artifact (incl. all hashes)."""
    chained = chain(measurements)
    rows = [m.to_dict() for m in chained]
    n_refused = sum(1 for r in rows if (r.get("refusal") or {}).get("verdict") == "REFUSE")
    n_flagged = sum(1 for r in rows if r.get("flagged"))
    n_unknown = sum(1 for r in rows if r.get("risk_class") == "UNKNOWN")
    body = {
        "generated_at": generated_at,
        "schema": MEASUREMENTS_SCHEMA,
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "no_fork": ("every verdict field copied from the seed that produced it (DFB / RWA Safety Board / "
                    "underwriting) — RISKWIRE re-implements no risk math"),
        "as_of": as_of,
        "n_measurements": len(rows),
        "n_refused": n_refused,
        "n_flagged": n_flagged,
        "n_unknown": n_unknown,
        "canonical_json_rule": CANONICAL_JSON_RULE,
        "verify_with": "python3 scripts/verify_riskwire.py data/riskwire/",
        "measurements": rows,
        "disclaimer": ("Each subject's risk_class / refusal / exit-liquidity is the SPA risk engine's "
                       "OWN deterministic verdict (imported via the seeds, not forked). Advisory — moves "
                       "no capital, never touches the go-live track."),
    }
    return seal_artifact(body, "measurements")


# ── WS1.3 DAY-30 REVIEW verification (reproduces day30_review.compute_review_hash — NO fork) ──────
# The exact non-content keys WS1.3 excludes from its review_hash (verbatim from
# spa_core.riskwire.day30_review._NON_CONTENT_KEYS — reproduced, never imported, so the standalone
# verifier can mirror this recipe with zero spa_core import).
DAY30_NON_CONTENT_KEYS = ("review_hash", "generated_at")


def compute_review_hash(review: Dict[str, Any]) -> str:
    """Reproduce WS1.3's day-30 review_hash byte-identically (spa_core.riskwire.day30_review.
    compute_review_hash): sha256 over canonical(review MINUS {review_hash, generated_at}), with the
    nested day30_artifact.generated_at ALSO stripped. PURE / deterministic. WS1.4 never re-hashes the
    review — it only re-derives WS1.3's own anchor to prove the published file was not altered."""
    content = {k: v for k, v in review.items() if k not in DAY30_NON_CONTENT_KEYS}
    art = content.get("day30_artifact")
    if isinstance(art, dict):
        content = dict(content)
        content["day30_artifact"] = {k: v for k, v in art.items() if k != "generated_at"}
    blob = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def verify_day30_review(review: Dict[str, Any]) -> dict:
    """Verify a published WS1.3 day-30 review artifact: re-derive its review_hash and compare to the
    stored one. Returns {valid, review_hash, broken_at, note}. fail-CLOSED: a non-dict, or a review
    missing review_hash, is invalid (never a silent pass)."""
    if not isinstance(review, dict):
        return {"valid": False, "review_hash": None, "broken_at": None,
                "note": "day30 review is not a JSON object"}
    stored = review.get("review_hash")
    if not isinstance(stored, str) or not stored:
        return {"valid": False, "review_hash": None, "broken_at": "review_hash",
                "note": "day30 review has no review_hash (fail-CLOSED)"}
    recomputed = compute_review_hash(review)
    if recomputed != stored:
        return {"valid": False, "review_hash": recomputed, "broken_at": "review_hash",
                "note": (f"review_hash mismatch: recomputed {recomputed[:16]}… != published "
                         f"{stored[:16]}… (a review cell was altered after the fact)")}
    return {"valid": True, "review_hash": recomputed, "broken_at": None, "note": "ok"}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# ATOMIC WRITE — data/riskwire/ only (same-dir tmp + os.replace via atomic_save)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _riskwire_dir(data_dir: Optional[Path]) -> Path:
    root = Path(data_dir) if data_dir is not None else (Path(__file__).resolve().parents[2] / "data")
    return root / "riskwire"


def write_measurements(measurements: List[RiskWireMeasurement], *, generated_at: str,
                       as_of: Optional[str], data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Build + atomically write data/riskwire/measurements.json (+ per-subject detail under subject/).
    Returns the artifact. Atomic (atomic_save = same-dir tmp + os.replace). READ-ONLY outside data/riskwire/."""
    from spa_core.utils.atomic import atomic_save
    artifact = build_measurements_artifact(measurements, generated_at=generated_at, as_of=as_of)
    rw = _riskwire_dir(data_dir)
    atomic_save(artifact, str(rw / "measurements.json"), indent=1)
    subj_dir = rw / "subject"
    for row in artifact["measurements"]:
        sid = row.get("subject_id")
        if isinstance(sid, str) and sid:
            safe = sid.replace("/", "_").replace("..", "_")
            atomic_save(row, str(subj_dir / f"{safe}.json"), indent=1)
    return artifact


# (The DAY-30 review is written by WS1.3 — spa_core.riskwire.day30_review.write_review. WS1.4 only
#  VERIFIES it via verify_day30_review; it never writes the review, to keep WS1.3's ownership clean.)


def verify_all(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Verify EVERY published RISKWIRE artifact under data/riskwire/ (the WS1.2 measurements snapshot +
    the WS1.3 day-30 review) in one pass — the in-process mirror of scripts/verify_riskwire.py. Each
    artifact is verified with ITS OWN published scheme (measurements: row-chain + head + artifact_hash;
    day30_review: WS1.3's review_hash). Returns {all_ok, artifacts:{name:res}}. A MISSING artifact is
    {present: False, valid: False} (fail-CLOSED — the caller, e.g. d_riskwire, decides its severity)."""
    rw = _riskwire_dir(data_dir)
    out: Dict[str, Any] = {"artifacts": {}}
    all_ok = True
    for name in ("measurements.json", "day30_review.json"):
        path = rw / name
        if not path.exists():
            out["artifacts"][name] = {"present": False, "valid": False, "note": "missing"}
            all_ok = False
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            out["artifacts"][name] = {"present": True, "valid": False, "note": f"unreadable: {e}"}
            all_ok = False
            continue
        if name == "day30_review.json":
            res = verify_day30_review(doc)
        else:
            res = verify_artifact(doc, "measurements")
        res["present"] = True
        out["artifacts"][name] = res
        all_ok = all_ok and res["valid"]
    out["all_ok"] = all_ok
    return out
