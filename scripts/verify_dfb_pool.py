#!/usr/bin/env python3
"""
verify_dfb_pool.py — the STANDALONE, ZERO-DEPENDENCY per-pool "don't trust us, check us" verifier.

A sibling of scripts/verify_spa.py, applied PER POOL to the DFB ("DeFi Board") risk overlay. A
skeptic downloads ONLY:
  • this single file, and
  • DFB's public JSON artifacts — any of:
        data/dfb/pools.json            (the wrapped screener list: {..., "pools": [ <row>, ... ]})
        data/dfb/pool/<pool_id>.json   (one pool's detail row)
        data/dfb/history/<pool_id>.jsonl (the pool's proof-chained history; one JSON row per line)

drops them on a CLEAN machine with NO `spa_core` on sys.path, runs:

    python3 verify_dfb_pool.py <files-or-dir-or-pool_id>

and independently RE-DERIVES every published per-row proof:
  • row_hash  — sha256 over the canonical-JSON of the row body (the row MINUS the chain-linkage
                envelope prev_hash/row_hash) + its prev_hash. This binds BOTH the published INPUTS
                (apy/tvl/...) AND the published OUTPUTS (risk_class / refusal / exit_liquidity /
                structural_haircut / engine_proof_hash). Forge ANY cell → the recompute diverges.
  • the chain — for pools.json (and history JSONL), every row's prev_hash must equal the previous
                row's row_hash (genesis "0"*64), so a reordered / dropped / inserted / back-fitted
                row is caught, never silently passed.

If a single byte of any published pool row were altered after the fact, the recompute diverges and
this tool reports the precise broken_at (the pool_id + field-level mismatch). It imports NOTHING from
SPA — it follows ONLY the public recipe (canonical-JSON + SHA-256), reproduced inline below, the SAME
recipe spa_core/dfb/risk_overlay.py::_row_hash uses. So the desk's number and your recompute agree to
the byte, with zero shared code.

stdlib-only · deterministic · fail-CLOSED · NO `spa_core` import · NO network.
EXIT CODES
    0  every supplied pool row reproduces byte-for-byte (and every chain links)
    1  ANY mismatch / broken link / malformed row / missing-required / unreadable required input
    2  usage error (no input found)
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# ── PUBLISHED INVARIANTS (verbatim from spa_core/dfb/risk_overlay.py; NEVER imported from code) ──
GENESIS_PREV = "0" * 64                         # the per-row proof-chain genesis prev_hash
ENVELOPE_KEYS = ("prev_hash", "row_hash")       # the chain-linkage envelope, excluded from the body
CANONICAL_JSON_RULE = 'json.dumps({"body": body, "prev_hash": prev_hash}, sort_keys=True, separators=(",",":"), default=str)'

# Cells the API/file may add when SERVING a row (router._read_*/setdefault) that are NOT part of the
# signed body. A file on disk does not carry them, but if someone verifies a SAVED API response we
# strip them so the body matches what was hashed. (The producer never hashes these.)
_SERVE_ONLY_KEYS = ("is_advisory", "disclaimer", "reproduce")


# ── the canonical recipe (the ONLY hashing code; mirrors risk_overlay._row_hash to the byte) ──
def _canonical_body(row: dict) -> dict:
    """The signed body = the published row MINUS the chain-linkage envelope (prev_hash/row_hash) and
    MINUS any serve-only envelope a router may have added. The single definition the producer signs."""
    return {
        k: v for k, v in row.items()
        if k not in ENVELOPE_KEYS and k not in _SERVE_ONLY_KEYS
    }


def _row_hash(row: dict, prev_hash: str) -> str:
    """Re-derive a row's row_hash with NO spa_core import — byte-identical to risk_overlay._row_hash:
       sha256( json.dumps({"body": <body>, "prev_hash": prev_hash},
                          sort_keys=True, separators=(",",":"), default=str) )."""
    blob = json.dumps({"body": _canonical_body(row), "prev_hash": prev_hash},
                      sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ── per-row check ──
def _check_row(row: dict, expected_prev: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Verify ONE row. Returns (ok, problem). fail-CLOSED on any missing/typed-wrong field.

    Checks, in order:
      1. it is a dict with a string row_hash + prev_hash (the envelope is present),
      2. if expected_prev is given, prev_hash links it (chain continuity),
      3. the recomputed row_hash equals the published row_hash (no cell back-fitted)."""
    if not isinstance(row, dict):
        return False, "row is not a JSON object"
    rh = row.get("row_hash")
    ph = row.get("prev_hash")
    if not isinstance(rh, str) or not rh:
        return False, "missing/invalid row_hash"
    if not isinstance(ph, str) or not ph:
        return False, "missing/invalid prev_hash"
    if expected_prev is not None and ph != expected_prev:
        return False, (f"chain break: prev_hash {ph[:12]}… does not link previous row_hash "
                       f"{expected_prev[:12]}…")
    recomputed = _row_hash(row, ph)
    if recomputed != rh:
        return False, (f"row_hash mismatch: recomputed {recomputed[:16]}… != published {rh[:16]}… "
                       f"(a published cell was altered after the fact)")
    return True, None


# ── input shapes ──
def _rows_from_obj(obj) -> Tuple[List[dict], str, bool]:
    """Extract the list of overlay rows from a loaded JSON object. Returns (rows, kind, is_chain).

      • a wrapped pools.json  {"pools": [ ... ]}  → the list, chained
      • a bare list           [ ... ]             → the list, chained
      • a single detail row   { "pool_id": ..., "row_hash": ... } → one-element list, NOT a chain
        (a standalone detail file is genesis-anchored on its own; its prev_hash is whatever the
        producer wrote — we still recompute its row_hash, we just do not require it to link a prior
        row we were not given)."""
    if isinstance(obj, dict) and isinstance(obj.get("pools"), list):
        return [r for r in obj["pools"] if isinstance(r, dict)], "pools.json", True
    if isinstance(obj, list):
        return [r for r in obj if isinstance(r, dict)], "pool list", True
    if isinstance(obj, dict) and "row_hash" in obj:
        return [obj], "pool detail", False
    return [], "unrecognized", False


def _verify_rows(rows: List[dict], is_chain: bool, source: str, results: list) -> bool:
    """Verify a list of rows. If is_chain, enforce prev_hash linkage genesis '0'*64 → each
    row_hash. Otherwise verify each row independently. Appends a per-row result; returns all-ok."""
    if not rows:
        results.append({"source": source, "ok": False, "broken_at": None,
                        "note": "no verifiable pool rows found (fail-CLOSED)"})
        return False
    all_ok = True
    prev = GENESIS_PREV if is_chain else None
    for i, row in enumerate(rows):
        pid = row.get("pool_id", f"<row {i}>")
        ok, problem = _check_row(row, prev)
        if not ok:
            all_ok = False
            results.append({"source": source, "ok": False, "broken_at": pid, "index": i,
                            "note": problem})
            # On a chain, a break invalidates everything downstream — stop (precise broken_at).
            if is_chain:
                break
            # On independent rows, keep going to report every bad row.
            continue
        prev = row["row_hash"] if is_chain else None
    if all_ok:
        results.append({"source": source, "ok": True, "broken_at": None,
                        "n_rows": len(rows),
                        "head_hash": rows[-1].get("row_hash") if is_chain else None,
                        "note": f"all {len(rows)} pool row(s) reproduce byte-for-byte"})
    return all_ok


# ── jsonl (history) ──
def _verify_jsonl(path: Path, results: list) -> bool:
    """Verify a per-pool history JSONL as ONE chain (one JSON row per line, prev_hash→row_hash)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        results.append({"source": str(path), "ok": False, "broken_at": None,
                        "note": f"unreadable: {e}"})
        return False
    rows: List[dict] = []
    for ln_no, ln in enumerate(text.splitlines(), 1):
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError as e:
            results.append({"source": str(path), "ok": False, "broken_at": f"line {ln_no}",
                            "note": f"malformed JSON line (fail-CLOSED): {e}"})
            return False
        if not isinstance(obj, dict):
            results.append({"source": str(path), "ok": False, "broken_at": f"line {ln_no}",
                            "note": "history line is not a JSON object"})
            return False
        rows.append(obj)
    return _verify_rows(rows, is_chain=True, source=str(path), results=results)


# ── discovery ──
def _discover(target: str) -> List[Path]:
    """Resolve the CLI target into concrete files. Accepts:
       • a file path (.json / .jsonl),
       • a directory (recursively finds dfb pools.json + pool/*.json + history/*.jsonl),
       • a bare pool_id (resolved under ./data/dfb/pool/<id>.json then ./data/dfb/history/<id>.jsonl).
    fail-CLOSED: an unresolvable target yields []."""
    p = Path(target)
    if p.is_file():
        return [p]
    if p.is_dir():
        found: List[Path] = []
        # the canonical DFB layout (also works when given the repo root or data/ or data/dfb/)
        for rel in ("dfb/pools.json", "pools.json"):
            cand = p / rel
            if cand.is_file():
                found.append(cand)
        for sub in ("dfb/pool", "pool"):
            d = p / sub
            if d.is_dir():
                found.extend(sorted(d.glob("*.json")))
        for sub in ("dfb/history", "history"):
            d = p / sub
            if d.is_dir():
                found.extend(sorted(d.glob("*.jsonl")))
        # de-dup preserving order
        seen, uniq = set(), []
        for f in found:
            rp = f.resolve()
            if rp not in seen:
                seen.add(rp)
                uniq.append(f)
        return uniq
    # bare pool_id → look under ./data/dfb/
    for rel in (f"data/dfb/pool/{target}.json", f"data/dfb/history/{target}.jsonl"):
        cand = Path(rel)
        if cand.is_file():
            return [cand]
    return []


def _verify_path(path: Path, results: list) -> bool:
    """Dispatch ONE file by extension. .jsonl → chain-of-lines; .json → object/list of rows."""
    if path.suffix == ".jsonl":
        return _verify_jsonl(path, results)
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        results.append({"source": str(path), "ok": False, "broken_at": None,
                        "note": f"unreadable/malformed JSON (fail-CLOSED): {e}"})
        return False
    rows, kind, is_chain = _rows_from_obj(obj)
    return _verify_rows(rows, is_chain, f"{path} ({kind})", results)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="verify_dfb_pool.py",
        description="Zero-dependency per-pool DFB proof verifier (no spa_core import).")
    ap.add_argument("targets", nargs="+",
                    help="pool detail json / pools.json / history jsonl / a directory / a pool_id")
    ap.add_argument("--json", action="store_true", help="machine-readable verdict to stdout")
    args = ap.parse_args(argv)

    files: List[Path] = []
    for t in args.targets:
        files.extend(_discover(t))
    # de-dup preserving order
    seen, uniq = set(), []
    for f in files:
        rp = f.resolve()
        if rp not in seen:
            seen.add(rp)
            uniq.append(f)
    files = uniq

    if not files:
        msg = {"ok": False, "error": "no_input",
               "note": "no DFB pool artifacts found at the supplied target(s) (fail-CLOSED)"}
        print(json.dumps(msg, indent=2) if args.json else
              "ERROR: no DFB pool artifacts found (fail-CLOSED). "
              "Give a pools.json / pool/<id>.json / history/<id>.jsonl / a dir / a pool_id.")
        return 2

    results: list = []
    all_ok = True
    for f in files:
        all_ok = _verify_path(f, results) and all_ok

    verdict = {
        "verifier": "verify_dfb_pool.py",
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
        print("DFB per-pool proof verification (zero-dependency, no spa_core import)\n")
        for r in results:
            tag = "PASS" if r["ok"] else "FAIL"
            line = f"  [{tag}] {r['source']}"
            if r["ok"]:
                extra = []
                if r.get("n_rows") is not None:
                    extra.append(f"{r['n_rows']} row(s)")
                if r.get("head_hash"):
                    extra.append(f"head {r['head_hash'][:16]}…")
                if extra:
                    line += "  (" + ", ".join(extra) + ")"
            else:
                if r.get("broken_at") is not None:
                    line += f"  broken_at={r['broken_at']}"
                line += f"\n         → {r.get('note')}"
            print(line)
        print()
        print("RESULT:", "OK — every pool row reproduces byte-for-byte." if all_ok
              else "FAIL — at least one row did not reproduce (see broken_at above).")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
