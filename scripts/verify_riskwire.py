#!/usr/bin/env python3
"""
verify_riskwire.py — the STANDALONE, ZERO-DEPENDENCY "don't trust us, check us" verifier for the
WHOLE RISKWIRE measurement product line (sibling of scripts/verify_spa.py + verify_dfb_pool.py).

RISKWIRE is measurement-as-a-product: its entire credibility is that a skeptic can re-derive every
published number on a CLEAN machine with NO `spa_core` on sys.path. A fund's risk desk downloads ONLY:
  • this single file, and
  • RISKWIRE's published artifacts under data/riskwire/:
        data/riskwire/measurements.json     (the unified per-subject snapshot — WS1.2 deliverable)
        data/riskwire/day30_review.json     (the day-30 review pack        — WS1.3 deliverable)
        data/riskwire/subject/<id>.json     (optional per-subject detail rows)

drops them on a clean machine and runs:

    python3 verify_riskwire.py data/riskwire/          # a directory (auto-discovers every artifact)
    python3 verify_riskwire.py data/riskwire/measurements.json data/riskwire/day30_review.json
    python3 verify_riskwire.py --json data/riskwire/   # machine-readable verdict

It independently RE-DERIVES each artifact's OWN published proof, byte-for-byte, importing NOTHING from
SPA — it follows ONLY the public recipe (canonical-JSON + SHA-256), reproduced inline below, the SAME
recipe spa_core/riskwire/proof.py uses. Each deliverable is verified with the scheme it published:

  A) the MEASUREMENTS snapshot — a per-row proof CHAIN + a per-artifact anchor:
     • PER-ROW: every measurement row carries prev_hash + row_hash; the rows form ONE single-genesis
       chain (row[0].prev_hash == "0"*64; each prev_hash == the previous row's row_hash). row_hash ==
       sha256(canonical({"body": <row minus envelope>, "prev_hash": <prev_hash>})). Binds BOTH the
       published INPUTS and OUTPUTS — forge a `risk_class` / `native_verdict` / an exit cell → the
       recompute diverges at that exact row (broken_at).
     • PER-ARTIFACT: the wrapper carries `head_hash` (must equal the last row's row_hash — a spliced /
       dropped / reordered row is caught) and `artifact_hash` == sha256 over the canonical wrapper body
       (the wrapper MINUS `artifact_hash`, which INCLUDES head_hash + every count/schema/as_of field).
       Forge a count, the schema, or the head → artifact_hash diverges.

  B) the DAY-30 REVIEW — WS1.3's single `review_hash` == sha256(canonical(review MINUS
     {review_hash, generated_at}); the nested day30_artifact.generated_at is ALSO stripped). Forge any
     review cell (a verdict, a realized number, the embedded day30_artifact proof_hash) → the recompute
     diverges. (WS1.3 owns writing the review; this verifier only re-derives its published hash.)

So the proof covers the OUTPUTS, not merely the inputs, AND each artifact as a whole — with zero shared
code between the desk and your recompute.

stdlib-only · deterministic · fail-CLOSED · NO `spa_core` import · NO network.
EXIT CODES
    0  every supplied RISKWIRE artifact reproduces byte-for-byte (rows chain + head + artifact hash)
    1  ANY mismatch / broken link / broken artifact hash / malformed row / unreadable required input
    2  usage error (no RISKWIRE artifact found)
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# ── PUBLISHED INVARIANTS (verbatim from spa_core/riskwire/proof.py; NEVER imported from code) ──
GENESIS_PREV = "0" * 64                                 # the per-row proof-chain genesis prev_hash
ROW_ENVELOPE_KEYS = ("prev_hash", "row_hash")           # per-row chain-linkage envelope
ARTIFACT_ENVELOPE_KEYS = ("artifact_hash",)             # per-artifact envelope (measurements)
DAY30_NON_CONTENT_KEYS = ("review_hash", "generated_at")  # excluded from WS1.3's review_hash
CANONICAL_JSON_RULE = "json.dumps(obj, sort_keys=True, separators=(',',':'), default=str)"

# Each RISKWIRE artifact = (filename, kind). kind routes the verify recipe:
#   "measurements" → row-chain + head + artifact_hash;  "day30" → WS1.3's review_hash.
_ARTIFACTS = (("measurements.json", "measurements"), ("day30_review.json", "day30"))


# ── the canonical recipe (the ONLY hashing code; mirrors proof.py to the byte) ──
def _row_body(row: dict) -> dict:
    """The signed row body = the published row MINUS its per-row chain-linkage envelope."""
    return {k: v for k, v in row.items() if k not in ROW_ENVELOPE_KEYS}


def _row_hash(row: dict, prev_hash: str) -> str:
    """Re-derive a row's row_hash with NO spa_core import — byte-identical to proof.row_hash:
       sha256( json.dumps({"body": <body>, "prev_hash": prev_hash},
                          sort_keys=True, separators=(",",":"), default=str) )."""
    blob = json.dumps({"body": _row_body(row), "prev_hash": prev_hash},
                      sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _artifact_hash(artifact: dict) -> str:
    """Re-derive the per-artifact hash — byte-identical to proof.artifact_hash:
       sha256( json.dumps(<wrapper MINUS artifact_hash>, sort_keys, compact, default=str) )."""
    body = {k: v for k, v in artifact.items() if k not in ARTIFACT_ENVELOPE_KEYS}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _review_hash(review: dict) -> str:
    """Re-derive WS1.3's day-30 review_hash — byte-identical to
    spa_core.riskwire.day30_review.compute_review_hash:
       sha256( json.dumps(<review MINUS {review_hash, generated_at}; nested day30_artifact.generated_at
               also stripped>, sort_keys, compact, ensure_ascii=False) )."""
    content = {k: v for k, v in review.items() if k not in DAY30_NON_CONTENT_KEYS}
    art = content.get("day30_artifact")
    if isinstance(art, dict):
        content = dict(content)
        content["day30_artifact"] = {k: v for k, v in art.items() if k != "generated_at"}
    blob = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ── per-row chain check ──
def _verify_chain(rows: List[dict]) -> Tuple[bool, Optional[object], Optional[str], Optional[str]]:
    """Walk the rows as ONE single-genesis chain. Returns (ok, broken_at, head_hash, note).
    fail-CLOSED on any missing/typed-wrong envelope field or any mismatch."""
    prev = GENESIS_PREV
    head = None
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return False, idx, None, "row is not a JSON object"
        rh = row.get("row_hash")
        ph = row.get("prev_hash")
        if not isinstance(rh, str) or not rh:
            return False, idx, None, "missing/invalid row_hash"
        if not isinstance(ph, str) or not ph:
            return False, idx, None, "missing/invalid prev_hash"
        if ph != prev:
            return False, idx, None, (f"chain break: prev_hash {ph[:12]}… does not link previous "
                                      f"row_hash {prev[:12]}…")
        recomputed = _row_hash(row, ph)
        if recomputed != rh:
            return False, idx, None, (f"row_hash mismatch: recomputed {recomputed[:16]}… != published "
                                      f"{rh[:16]}… (a published cell was altered after the fact)")
        prev = rh
        head = rh
    return True, None, head, None


# ── per-artifact check (rows chain → head binds → artifact hash binds) ──
def _verify_artifact(artifact: dict, rows_key: str, source: str, results: list) -> bool:
    if not isinstance(artifact, dict):
        results.append({"source": source, "ok": False, "broken_at": None,
                        "note": "artifact is not a JSON object"})
        return False
    rows = artifact.get(rows_key)
    if not isinstance(rows, list):
        results.append({"source": source, "ok": False, "broken_at": None,
                        "note": f"missing/invalid '{rows_key}' row list (fail-CLOSED)"})
        return False
    ok, broken_at, head, note = _verify_chain(rows)
    if not ok:
        results.append({"source": source, "ok": False, "broken_at": broken_at, "note": note})
        return False
    claimed_head = artifact.get("head_hash")
    if claimed_head != head:
        results.append({"source": source, "ok": False, "broken_at": "head_hash",
                        "note": (f"wrapper head_hash {str(claimed_head)[:16]}… != re-derived chain head "
                                 f"{str(head)[:16]}… (rows spliced/dropped/reordered)")})
        return False
    recomputed = _artifact_hash(artifact)
    claimed = artifact.get("artifact_hash")
    if recomputed != claimed:
        results.append({"source": source, "ok": False, "broken_at": "artifact_hash",
                        "note": (f"artifact_hash mismatch: recomputed {recomputed[:16]}… != published "
                                 f"{str(claimed)[:16]}… (wrapper metadata/head altered after the fact)")})
        return False
    results.append({"source": source, "ok": True, "broken_at": None, "n_rows": len(rows),
                    "head_hash": head, "artifact_hash": recomputed,
                    "note": f"all {len(rows)} row(s) + artifact reproduce byte-for-byte"})
    return True


# ── the WS1.3 day-30 review (single review_hash over the review content) ──
def _verify_day30(review: dict, source: str, results: list) -> bool:
    if not isinstance(review, dict):
        results.append({"source": source, "ok": False, "broken_at": None,
                        "note": "day30 review is not a JSON object"})
        return False
    stored = review.get("review_hash")
    if not isinstance(stored, str) or not stored:
        results.append({"source": source, "ok": False, "broken_at": "review_hash",
                        "note": "day30 review has no review_hash (fail-CLOSED)"})
        return False
    recomputed = _review_hash(review)
    if recomputed != stored:
        results.append({"source": source, "ok": False, "broken_at": "review_hash",
                        "note": (f"review_hash mismatch: recomputed {recomputed[:16]}… != published "
                                 f"{stored[:16]}… (a review cell was altered after the fact)")})
        return False
    results.append({"source": source, "ok": True, "broken_at": None, "review_hash": recomputed,
                    "note": "day-30 review_hash reproduces byte-for-byte"})
    return True


# ── a standalone per-subject detail file (one measurement row, genesis-anchored on its own) ──
def _verify_detail_row(row: dict, source: str, results: list) -> bool:
    """A data/riskwire/subject/<id>.json is one measurement row. We recompute its row_hash over its own
    published prev_hash (we do NOT require it to link a prior row we were not given). fail-CLOSED.

    Content-sniff first: a directly-passed file that is actually a full artifact (has `measurements` or
    `review_hash`) is routed to the right verifier so the broken_at message is precise even when the
    file was renamed (discovery only recognizes the canonical filenames)."""
    if not isinstance(row, dict):
        results.append({"source": source, "ok": False, "broken_at": None,
                        "note": "detail row is not a JSON object"})
        return False
    if isinstance(row.get("measurements"), list) and "head_hash" in row:
        return _verify_artifact(row, "measurements", source, results)
    if "review_hash" in row and "row_hash" not in row:
        return _verify_day30(row, source, results)
    rh = row.get("row_hash")
    ph = row.get("prev_hash")
    if not isinstance(rh, str) or not rh or not isinstance(ph, str) or not ph:
        results.append({"source": source, "ok": False, "broken_at": None,
                        "note": "missing/invalid row_hash/prev_hash"})
        return False
    recomputed = _row_hash(row, ph)
    if recomputed != rh:
        results.append({"source": source, "ok": False, "broken_at": row.get("subject_id"),
                        "note": (f"row_hash mismatch: recomputed {recomputed[:16]}… != published "
                                 f"{rh[:16]}… (a published cell was altered)")})
        return False
    results.append({"source": source, "ok": True, "broken_at": None,
                    "note": "detail row reproduces byte-for-byte"})
    return True


# ── discovery ──
def _discover(target: str) -> List[Tuple[Path, str]]:
    """Resolve a CLI target into concrete (file, kind) pairs. kind ∈ {measurements, sections, detail}.
    Accepts a file path, or a directory (auto-finds measurements.json + day30_review.json + subject/*).
    fail-CLOSED: an unresolvable target yields []."""
    p = Path(target)
    if p.is_file():
        name = p.name
        for fname, key in _ARTIFACTS:
            if name == fname:
                return [(p, key)]
        # any other json we were handed directly: treat as a per-subject detail row.
        return [(p, "detail")]
    if p.is_dir():
        found: List[Tuple[Path, str]] = []
        for sub in (".", "riskwire"):
            base = p if sub == "." else p / sub
            for fname, key in _ARTIFACTS:
                cand = base / fname
                if cand.is_file():
                    found.append((cand, key))
            subj = base / "subject"
            if subj.is_dir():
                for f in sorted(subj.glob("*.json")):
                    found.append((f, "detail"))
        # de-dup preserving order
        seen, uniq = set(), []
        for f, k in found:
            rp = f.resolve()
            if rp not in seen:
                seen.add(rp)
                uniq.append((f, k))
        return uniq
    return []


def _verify_path(path: Path, kind: str, results: list) -> bool:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        results.append({"source": str(path), "ok": False, "broken_at": None,
                        "note": f"unreadable/malformed JSON (fail-CLOSED): {e}"})
        return False
    if kind == "detail":
        return _verify_detail_row(obj, str(path), results)
    if kind == "day30":
        return _verify_day30(obj, str(path), results)
    return _verify_artifact(obj, kind, str(path), results)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="verify_riskwire.py",
        description="Zero-dependency RISKWIRE proof verifier (no spa_core import).")
    ap.add_argument("targets", nargs="+",
                    help="a data/riskwire/ directory, or measurements.json / day30_review.json / "
                         "subject/<id>.json file(s)")
    ap.add_argument("--json", action="store_true", help="machine-readable verdict to stdout")
    args = ap.parse_args(argv)

    files: List[Tuple[Path, str]] = []
    for t in args.targets:
        files.extend(_discover(t))
    # de-dup preserving order
    seen, uniq = set(), []
    for f, k in files:
        rp = f.resolve()
        if rp not in seen:
            seen.add(rp)
            uniq.append((f, k))
    files = uniq

    if not files:
        msg = {"ok": False, "error": "no_input",
               "note": "no RISKWIRE artifacts found at the supplied target(s) (fail-CLOSED)"}
        print(json.dumps(msg, indent=2) if args.json else
              "ERROR: no RISKWIRE artifacts found (fail-CLOSED). Give a data/riskwire/ dir or "
              "measurements.json / day30_review.json / subject/<id>.json.")
        return 2

    results: list = []
    all_ok = True
    for f, k in files:
        all_ok = _verify_path(f, k, results) and all_ok

    verdict = {
        "verifier": "verify_riskwire.py",
        "zero_dependency": True,
        "no_spa_core_import": True,
        "canonical_json_rule": CANONICAL_JSON_RULE,
        "n_sources": len(results),
        "all_ok": all_ok,
        "results": results,
    }
    if args.json:
        print(json.dumps(verdict, indent=2, default=str))
    else:
        print("RISKWIRE proof verification (zero-dependency, no spa_core import)\n")
        for r in results:
            tag = "PASS" if r["ok"] else "FAIL"
            line = f"  [{tag}] {r['source']}"
            if r["ok"]:
                extra = []
                if r.get("n_rows") is not None:
                    extra.append(f"{r['n_rows']} row(s)")
                if r.get("head_hash"):
                    extra.append(f"head {r['head_hash'][:16]}…")
                if r.get("artifact_hash"):
                    extra.append(f"artifact {r['artifact_hash'][:16]}…")
                if r.get("review_hash"):
                    extra.append(f"review {r['review_hash'][:16]}…")
                if extra:
                    line += "  (" + ", ".join(extra) + ")"
            else:
                if r.get("broken_at") is not None:
                    line += f"  broken_at={r['broken_at']}"
                line += f"\n         → {r.get('note')}"
            print(line)
        print()
        print("RESULT:", "OK — every RISKWIRE artifact reproduces byte-for-byte." if all_ok
              else "FAIL — at least one artifact did not reproduce (see broken_at above).")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
