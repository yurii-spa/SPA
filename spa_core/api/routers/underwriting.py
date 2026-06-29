# LLM_FORBIDDEN
"""Underwriting router (Lane C, Layer-3 moat) — the FLAG-GATED public surface of the
hash-anchored UNDERWRITING REPORT.

C2.3 — two GET endpoints serve the report Lane C produces:
  • GET /api/underwriting/report  — the full underwriting_report.json (VERBATIM)
  • GET /api/underwriting/proof   — the report_proof.jsonl section chain + live verification

OWNER GATE (the whole point of Lane C's owner-gated publication): both endpoints are served ONLY
when ``SPA_UNDERWRITING_PUBLISH`` is ON. When the flag is OFF (the default) they return **404** — the
commercial underwriting surface is NOT public until the owner flips the flag. The report is still
ALWAYS written to ``data/`` (the proof chain grows + stays verifiable); the flag only governs PUBLIC
SURFACING.

POSTURE (WS2): GET-only, read-only, graceful, fail-CLOSED. The report is served VERBATIM (no
recompute — the honesty rule reaches the wire: the API never laundters a happier number than the file
on disk). The proof endpoint RUNS the same chain verification scripts/verify_spa.py uses, so the
server verdict matches the standalone verifier byte-for-byte. Defense-in-depth key redaction over the
public projection. NEVER a 500: a missing/corrupt file is an honest empty/absent condition.

stdlib + FastAPI. NO ``spa_core.execution`` import.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from spa_core.api._shared import data_dir, now, scrub_nonfinite
from spa_core.strategy_lab.underwriting import report as R

log = logging.getLogger("spa.api")

router = APIRouter(tags=["underwriting"])

# Same canonical-JSON reproducibility contract the rates-desk proof surfaces publish (A4): the
# response teaches its own verification so a consumer can re-derive every hash WITHOUT our code.
_SPEC_VERSION = "1.0"
_CANONICAL_JSON_RULE = "json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)"

# defense-in-depth: drop any key whose name suggests a secret from the public projection. The report
# is, by construction, risk/measurement data with no secrets — this is belt-and-suspenders so a
# future producer field can never leak onto the wire.
_REDACT_KEY_SUBSTRINGS = ("secret", "token", "key", "pat", "wallet", "address", "private")

# the public report/proof artifacts (relative to data_dir()).
_REPORT_REL = "underwriting/underwriting_report.json"
_PROOF_REL = "underwriting/report_proof.jsonl"


def _reproduce_block(files: list, note: str) -> dict:
    return {
        "spec_version": _SPEC_VERSION,
        "spec": "docs/UNDERWRITING_REPORT_SPEC.md",
        "canonical_json_rule": _CANONICAL_JSON_RULE,
        "hash": "sha256(canonical_json).hexdigest()",
        "public_files": files,
        "verify_with": "python3 verify_spa.py " + " ".join(files),
        "verifier": "scripts/verify_spa.py (zero-dependency, no spa_core import) — surface H",
        "note": note,
    }


def _redact_public(obj):
    """Recursively drop any dict key whose lowercased name contains a denylisted substring. PURE."""
    if isinstance(obj, dict):
        return {k: _redact_public(v) for k, v in obj.items()
                if not any(s in str(k).lower() for s in _REDACT_KEY_SUBSTRINGS)}
    if isinstance(obj, list):
        return [_redact_public(v) for v in obj]
    return obj


def _gate_or_404() -> None:
    """The OWNER GATE. When ``SPA_UNDERWRITING_PUBLISH`` is OFF (default) the public underwriting
    surface does not exist → 404. fail-CLOSED: the commercial report is owner-gated; an unflagged
    deployment must not leak it. The single source of truth for the flag is
    ``report.is_publish_enabled`` (the same gate that stamps ``published`` into the file)."""
    if not R.is_publish_enabled():
        raise HTTPException(status_code=404, detail={
            "error": "underwriting_surface_disabled",
            "note": ("the underwriting report is owner-gated; set SPA_UNDERWRITING_PUBLISH to a "
                     "truthy value to surface it. The report is still written to data/ and is "
                     "verifiable with scripts/verify_spa.py regardless of this flag."),
            "publish_flag_env": R.PUBLISH_FLAG_ENV,
        })


@router.get("/api/underwriting/report")
def get_underwriting_report():
    """The full hash-anchored UNDERWRITING REPORT, served VERBATIM — FLAG-GATED.

    404 unless ``SPA_UNDERWRITING_PUBLISH`` is ON. When ON, serves
    ``data/underwriting/underwriting_report.json`` VERBATIM (no recompute — the honesty rule reaches
    the wire). Read-only, graceful, fail-CLOSED: a missing/corrupt file (flag ON) yields an honest
    ``available: false`` payload, NEVER a 500. Redacted defense-in-depth."""
    _gate_or_404()
    raw = read_report_file()
    if not isinstance(raw, dict) or not raw:
        return {
            "generated_at": now(),
            "model": "underwriting_report",
            "available": False,
            "note": ("the underwriting report has not been generated yet (flag is ON but "
                     "data/underwriting/underwriting_report.json is absent/corrupt). Generate it: "
                     "python3 -m spa_core.strategy_lab.underwriting.report --build"),
            "reproduce": _reproduce_block(["underwriting_report.json", "report_proof.jsonl"],
                                          "Re-derive every section proof_hash + the chain head per "
                                          "docs/UNDERWRITING_REPORT_SPEC.md §4 (surface H)."),
        }
    # serve VERBATIM (scrub only non-finite so a corrupt file cannot crash the serializer).
    out = scrub_nonfinite(raw)
    if isinstance(out, dict):
        out.setdefault("reproduce", _reproduce_block(
            ["underwriting_report.json", "report_proof.jsonl"],
            "The published survives_at_aum_usd / floor_plus_bps_at_5M are copied VERBATIM from Lane "
            "B; re-derive every section proof_hash + chain head per UNDERWRITING_REPORT_SPEC.md §4."))
    return _redact_public(out)


@router.get("/api/underwriting/proof")
def get_underwriting_proof(last_n: int = Query(default=12, ge=1, le=200)):
    """The UNDERWRITING REPORT proof chain + LIVE verification — FLAG-GATED.

    404 unless ``SPA_UNDERWRITING_PUBLISH`` is ON. When ON, reads
    ``data/underwriting/report_proof.jsonl`` and RUNS the same section-chain verification surface H
    runs (per-section proof_hash + prev-linked entry_hash + refusal-consistency), so the server
    verdict matches scripts/verify_spa.py byte-for-byte. Read-only, graceful, fail-CLOSED: an
    absent/corrupt proof file yields ``verified:true`` over a length-0 chain (vacuously valid),
    NEVER a 500."""
    _gate_or_404()
    rows = read_proof_rows()
    result = R.verify_report_chain(rows)

    # cross-section refusal-consistency (the same property surface H enforces): a REFUSED market must
    # never appear as underwritten capacity. Computed only over the VERIFIED rows.
    refusal_consistent, smuggled = _refusal_consistency(rows)
    verified = bool(result["valid"]) and refusal_consistent

    last = []
    for sec in rows[-last_n:]:
        if not isinstance(sec, dict):
            continue
        last.append({
            "seq": sec.get("seq"),
            "section_id": sec.get("section_id"),
            "proof_hash": sec.get("proof_hash"),
            "entry_hash": sec.get("entry_hash"),
            "prev_hash": sec.get("prev_hash"),
        })

    payload = {
        "generated_at": now(),
        "model": "underwriting_report_proof_chain",
        "chain_length": result["length"],
        "head_hash": result["head_hash"],
        "verified": verified,
        "broken_at": result["broken_at"],
        "refusal_consistent": refusal_consistent,
        "smuggled_markets": smuggled,
        "n_sections": len(rows),
        "last_n_sections": last,
        "reproduce": _reproduce_block(
            ["report_proof.jsonl"],
            "Walk the section chain per UNDERWRITING_REPORT_SPEC.md §4-§4a: each section's proof_hash "
            "+ entry_hash recompute, prev-linked from genesis, AND no REFUSED market appears as "
            "underwritten capacity. The server verdict reproduces byte-for-byte under the verifier."),
    }
    return _redact_public(payload)


# ── verbatim file readers (graceful, fail-CLOSED — never raise into the handler) ──────────────────
def read_report_file() -> dict:
    """Read data/underwriting/underwriting_report.json VERBATIM. {} on missing/corrupt (graceful)."""
    path = data_dir() / _REPORT_REL
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (FileNotFoundError, OSError):
        return {}
    except json.JSONDecodeError as e:
        log.warning(f"underwriting report corrupt: {e}")
        return {}


def read_proof_rows() -> list:
    """Read data/underwriting/report_proof.jsonl as a list of section dicts. [] on missing/corrupt."""
    path = data_dir() / _PROOF_REL
    rows: list = []
    try:
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError:
                # a corrupt line is a real, honest tamper condition — push a non-dict so chain
                # verification fails CLOSED rather than silently skipping it.
                rows.append({"__corrupt__": True})
    except (FileNotFoundError, OSError):
        return []
    return rows


_REFUSE = "REFUSE"


def _refusal_consistency(rows: list):
    """Cross-section refusal-consistency over the proof rows (mirrors surface H): a market the
    ``refusals`` section marked REFUSE must NOT appear in ``capacity.capacity_markets``. Returns
    (consistent: bool, smuggled: list[str]). PURE."""
    refused: set = set()
    capacity_syms: set = set()
    for sec in rows:
        if not isinstance(sec, dict):
            continue
        sid = sec.get("section_id")
        if sid == "refusals":
            for v in (sec.get("verdicts") or []):
                if isinstance(v, dict) and v.get("verdict") == _REFUSE:
                    refused.add(v.get("symbol"))
        elif sid == "capacity":
            for m in (sec.get("capacity_markets") or []):
                if isinstance(m, dict):
                    capacity_syms.add(m.get("symbol") or m.get("market_id") or m.get("underlying"))
    smuggled = sorted(str(s) for s in (refused & capacity_syms) if s is not None)
    return (len(smuggled) == 0), smuggled


# ── full-chain download (VERBATIM bytes for clean-machine reproduction; flag-gated) ───────────────
@router.get("/api/underwriting/full-chain", response_class=PlainTextResponse)
def get_underwriting_full_chain():
    """Serve the COMPLETE report_proof.jsonl VERBATIM (uncapped) so a stranger can curl it onto a
    clean machine and re-derive the head with scripts/verify_spa.py — FLAG-GATED.

    404 unless ``SPA_UNDERWRITING_PUBLISH`` is ON. A KNOWN-but-absent file is also 404 (fail-CLOSED:
    no fabricated empty success). text/plain so the bytes are delivered unchanged."""
    _gate_or_404()
    path = data_dir() / _PROOF_REL
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        raise HTTPException(status_code=404, detail={
            "error": "proof_file_absent",
            "file": _PROOF_REL,
            "note": "fail-CLOSED: report_proof.jsonl does not exist yet; no fabricated body served.",
        })
    return PlainTextResponse(content=raw, media_type="text/plain; charset=utf-8")
