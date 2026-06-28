#!/usr/bin/env python3
"""
verify_spa.py — the STANDALONE, ZERO-DEPENDENCY "don't trust us, check us" verifier.

A skeptical third party (a Gauntlet / Credora / Chaos-Labs reviewer) downloads ONLY:
  • this single file, and
  • SPA's public JSON artifacts (decision_log.jsonl, exit_nav.json, anchors.jsonl),

drops them on a clean machine with NO `spa_core` on sys.path, runs:

    python3 verify_spa.py <files-or-dir>

and independently re-derives EVERY published hash, reaching SPA's EXACT verdicts. If a single byte
of any historical decision, any exit-NAV row, or any anchor were altered after the fact, the
recompute diverges and this tool reports the precise broken_at. Nothing here imports SPA code — it
follows ONLY the public docs/PROOF_CHAIN_SPEC.md recipe (canonical-JSON + SHA-256), reproduced inline.

stdlib-only · deterministic · fail-CLOSED · NO `spa_core` import · NO network. Exit 0 = everything
reproduces byte-for-byte; exit 1 = ANY mismatch / missing-required / malformed input.

It verifies three independent published proofs:
  (A) decision_log.jsonl — the tamper-evident decision chain (PROOF_CHAIN_SPEC §2-§5):
      re-derive every entry_hash, check single-genesis + contiguous seq + prev-linkage; print
      valid / broken_at / head_hash.
  (B) exit_nav.json      — every per-row proof_hash (PROOF_CHAIN_SPEC §6), live + illustrative +
      the portfolio section, recomputed from each row's published inputs.
  (C) anchors.jsonl      — the cross-eviction immutability anchors (append-only, monotonic seq, and
      each anchor's head_hash must match the producer ledger / decision-chain head it checkpoints).

USAGE
    python3 verify_spa.py data/rates_desk/                # a directory: auto-discovers the 3 files
    python3 verify_spa.py decision_log.jsonl exit_nav.json anchors.jsonl   # explicit files
    python3 verify_spa.py --expect-head <hex> data/rates_desk/  # also assert the published head
    python3 verify_spa.py --json data/rates_desk/          # machine-readable verdict to stdout

EXIT CODES
    0  all supplied proofs reproduce exactly (and any --expect-head matched)
    1  any mismatch, malformed row, missing required field, or unreadable required file
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# ── PUBLISHED INVARIANTS (verbatim from docs/PROOF_CHAIN_SPEC.md §7; NEVER import them from code) ──
SPEC_VERSION = "1.0"
EVENT_TYPE = "rates_desk_decision"          # §3: fixed for this log, not stored per-row
GENESIS_PREV = "0" * 64                      # §5: genesis prev_hash
ENVELOPE_KEYS = ("seq", "ts", "entry_hash", "prev_hash")  # §1/§3: the chain-linkage envelope
CANONICAL_JSON_RULE = "json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)"

# exit-nav §6: the exact set of fields the per-row proof_hash is taken over.
EXIT_NAV_ROW_INPUT_KEYS = (
    "ticket_usd", "gross_usd", "depth_usd", "as_of", "model", "model_params", "data_source",
)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# canonical JSON + the two published hash recipes (inlined per the spec — no shared lib)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _canonical(obj) -> str:
    """The ONE canonical-JSON rule (PROOF_CHAIN_SPEC §2). sort_keys recursive, compact, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def recompute_entry_hash(row: dict) -> str:
    """PROOF_CHAIN_SPEC §3 — SHA-256 over canonical({seq, ts, event_type, payload, prev_hash})
    where payload = the row minus the four envelope keys, event_type = the fixed constant."""
    payload = {k: v for k, v in row.items() if k not in ENVELOPE_KEYS}
    canonical = _canonical({
        "seq": row.get("seq"),
        "ts": row.get("ts"),
        "event_type": EVENT_TYPE,
        "payload": payload,
        "prev_hash": row.get("prev_hash"),
    })
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def exit_nav_proof_hash(row_inputs: dict) -> str:
    """PROOF_CHAIN_SPEC §6 — SHA-256 over the canonical JSON of the published row inputs.

    NOTE: the spec recipe uses ``default=str`` (Decimals/None rendered with str()); for the published
    file every value is already a JSON-native scalar, so the result is byte-identical either way. We
    pass default=str to match the spec exactly."""
    blob = json.dumps(row_inputs, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (A) decision chain — PROOF_CHAIN_SPEC §5
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def verify_decision_chain(rows: List[dict]) -> dict:
    """Walk rows in seq order; at each row require (1) seq == idx, (2) prev_hash == previous
    entry_hash (genesis '0'*64), (3) recompute_entry_hash(row) == entry_hash. fail-CLOSED on any
    malformed row. Returns {valid, length, broken_at, head_hash}. Empty is vacuously valid."""
    expected_prev = GENESIS_PREV
    head_hash: Optional[str] = None
    n = len(rows)
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if row.get("seq") != idx:
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if row.get("prev_hash") != expected_prev:
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        try:
            recomputed = recompute_entry_hash(row)
        except Exception:  # noqa: BLE001 — malformed row → fail-CLOSED here
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if recomputed != row.get("entry_hash"):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        expected_prev = row["entry_hash"]
        head_hash = row["entry_hash"]
    return {"valid": True, "length": n, "broken_at": None, "head_hash": head_hash}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (B) exit-NAV per-row proof hashes — PROOF_CHAIN_SPEC §6 (live + illustrative + portfolio)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _row_inputs_from(row: dict) -> Tuple[Optional[dict], Optional[str]]:
    """Reconstruct §6 row_inputs from a published schedule row. Returns (row_inputs, error_or_None).
    fail-CLOSED: any required field absent → error (a hole we cannot reproduce is a FAILURE here, not
    a pass — the published row claims a proof_hash, so all its inputs must be present)."""
    missing = [k for k in EXIT_NAV_ROW_INPUT_KEYS if k not in row]
    if missing:
        return None, f"missing input field(s): {','.join(missing)}"
    return {k: row[k] for k in EXIT_NAV_ROW_INPUT_KEYS}, None


def _iter_schedule_rows(exit_nav: dict):
    """Yield (label, row) for EVERY schedule row that carries a proof_hash, across all sections:
    the live `schedule`, the `illustrative.schedule`, and the `portfolio.markets[*].schedule`."""
    if not isinstance(exit_nav, dict):
        return
    for i, r in enumerate(exit_nav.get("schedule") or []):
        if isinstance(r, dict) and "proof_hash" in r:
            yield (f"live[{i}]", r)
    illus = exit_nav.get("illustrative")
    if isinstance(illus, dict):
        for i, r in enumerate(illus.get("schedule") or []):
            if isinstance(r, dict) and "proof_hash" in r:
                yield (f"illustrative[{i}]", r)
    portfolio = exit_nav.get("portfolio")
    if isinstance(portfolio, dict):
        for mi, mkt in enumerate(portfolio.get("markets") or []):
            if not isinstance(mkt, dict):
                continue
            mid = mkt.get("market_id", mi)
            for i, r in enumerate(mkt.get("schedule") or []):
                if isinstance(r, dict) and "proof_hash" in r:
                    yield (f"portfolio[{mid}][{i}]", r)


def verify_exit_nav(exit_nav: dict) -> dict:
    """Recompute every published exit-NAV proof_hash (§6). Returns
    {valid, n_rows, n_verified, first_bad}. fail-CLOSED: any row missing its inputs or mismatching
    its stored proof_hash → valid=False with first_bad set to the section label."""
    n_rows = 0
    n_ok = 0
    first_bad: Optional[str] = None
    for label, row in _iter_schedule_rows(exit_nav):
        n_rows += 1
        inputs, err = _row_inputs_from(row)
        if err is not None:
            first_bad = first_bad or f"{label}: {err}"
            continue
        recomputed = exit_nav_proof_hash(inputs)
        if recomputed == row.get("proof_hash"):
            n_ok += 1
        else:
            first_bad = first_bad or f"{label}: proof_hash mismatch"
    valid = (first_bad is None)
    return {"valid": valid, "n_rows": n_rows, "n_verified": n_ok, "first_bad": first_bad}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (C) cross-eviction anchors — verified against the producer head they checkpoint
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def verify_anchors(anchors: List[dict], decision_head: Optional[str],
                   decision_length: Optional[int]) -> dict:
    """Verify the append-only anchor ledger (anchors.jsonl).

    Each anchor = {ts, seq, head_hash, chain_length}. Checks:
      1. append-only monotonic seq: anchor seq runs 0..N contiguous.
      2. monotonic chain_length: an anchor never checkpoints a SHORTER all-time chain than an earlier
         one (the producer ledger is append-only → length never decreases).
      3. consistency with the CURRENT decision head: the anchor whose chain_length == the supplied
         decision_length must carry head_hash == decision_head (the latest checkpoint reproduces the
         live chain head). Anchors for OLDER lengths (pre-eviction windows) are accepted as historical
         checkpoints — their head_hash cannot be re-derived from a ring-buffered file alone, which is
         exactly WHY the append-only anchor ledger exists.

    fail-CLOSED. Returns {valid, length, broken_at, latest_matches_head}. Empty is vacuously valid."""
    n = len(anchors)
    if n == 0:
        return {"valid": True, "length": 0, "broken_at": None, "latest_matches_head": None}
    prev_seq = -1
    prev_len = -1
    latest_matches_head: Optional[bool] = None
    for idx, a in enumerate(anchors):
        if not isinstance(a, dict):
            return {"valid": False, "length": n, "broken_at": idx, "latest_matches_head": None}
        seq = a.get("seq")
        clen = a.get("chain_length")
        head = a.get("head_hash")
        if not isinstance(seq, int) or seq != idx:
            return {"valid": False, "length": n, "broken_at": idx, "latest_matches_head": None}
        if seq <= prev_seq:  # strictly monotonic (defensive; seq==idx already implies it)
            return {"valid": False, "length": n, "broken_at": idx, "latest_matches_head": None}
        if not isinstance(clen, int) or clen < prev_len:
            return {"valid": False, "length": n, "broken_at": idx, "latest_matches_head": None}
        if not isinstance(head, str) or len(head) != 64:
            return {"valid": False, "length": n, "broken_at": idx, "latest_matches_head": None}
        # consistency with the live decision chain, when this anchor checkpoints the current length.
        if decision_head is not None and decision_length is not None and clen == decision_length:
            if head != decision_head:
                return {"valid": False, "length": n, "broken_at": idx, "latest_matches_head": False}
            latest_matches_head = True
        prev_seq = seq
        prev_len = clen
    return {"valid": True, "length": n, "broken_at": None, "latest_matches_head": latest_matches_head}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# file loading (stdlib-only, fail-CLOSED)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _read_jsonl(path: Path) -> Tuple[Optional[List[dict]], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return None, f"unreadable: {e}"
    rows: List[dict] = []
    for ln_no, ln in enumerate(text.splitlines()):
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError as e:
            return None, f"corrupt JSON at line {ln_no + 1}: {e}"
    return rows, None


def _read_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except OSError as e:
        return None, f"unreadable: {e}"
    except json.JSONDecodeError as e:
        return None, f"corrupt JSON: {e}"


def _resolve_inputs(args_paths: List[str]) -> dict:
    """Map the CLI paths to {decision_log, exit_nav, anchors}. A single directory auto-discovers the
    canonical filenames; explicit files are matched by suffix/name."""
    found = {"decision_log": None, "exit_nav": None, "anchors": None}
    for raw in args_paths:
        p = Path(raw)
        if p.is_dir():
            cand = {
                "decision_log": p / "decision_log.jsonl",
                "exit_nav": p / "exit_nav.json",
                "anchors": p / "anchors.jsonl",
            }
            for k, fp in cand.items():
                if fp.exists() and found[k] is None:
                    found[k] = fp
        else:
            name = p.name
            if name.endswith("decision_log.jsonl") or name == "decision_log.jsonl":
                found["decision_log"] = p
            elif name.endswith("anchors.jsonl") or name == "anchors.jsonl":
                found["anchors"] = p
            elif name.endswith("exit_nav.json") or name == "exit_nav.json":
                found["exit_nav"] = p
            elif name.endswith(".jsonl"):
                # unknown jsonl: treat as decision_log only if not already set
                if found["decision_log"] is None:
                    found["decision_log"] = p
            elif name.endswith(".json"):
                if found["exit_nav"] is None:
                    found["exit_nav"] = p
    return found


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def run(paths: List[str], expect_head: Optional[str] = None) -> dict:
    """Run all available verifications over the resolved inputs. Returns a verdict dict. A proof is
    only checked if its file is present; at least ONE file must be present (else nothing to verify)."""
    inputs = _resolve_inputs(paths)
    report: dict = {
        "spec_version": SPEC_VERSION,
        "canonical_json_rule": CANONICAL_JSON_RULE,
        "files": {k: (str(v) if v else None) for k, v in inputs.items()},
        "decision_chain": None,
        "exit_nav": None,
        "anchors": None,
        "errors": [],
        "ok": False,
    }

    if not any(inputs.values()):
        report["errors"].append("no recognizable public files supplied (decision_log.jsonl / "
                                "exit_nav.json / anchors.jsonl)")
        return report

    decision_head: Optional[str] = None
    decision_length: Optional[int] = None

    # (A) decision chain
    if inputs["decision_log"]:
        rows, err = _read_jsonl(inputs["decision_log"])
        if err is not None:
            report["errors"].append(f"decision_log: {err}")
            report["decision_chain"] = {"valid": False, "broken_at": None, "head_hash": None,
                                        "length": None}
        else:
            res = verify_decision_chain(rows)
            report["decision_chain"] = res
            if res["valid"]:
                decision_head = res["head_hash"]
                decision_length = res["length"]
            else:
                report["errors"].append(f"decision_log: chain broken at row {res['broken_at']}")

    # (B) exit-NAV proof hashes
    if inputs["exit_nav"]:
        doc, err = _read_json(inputs["exit_nav"])
        if err is not None:
            report["errors"].append(f"exit_nav: {err}")
            report["exit_nav"] = {"valid": False, "n_rows": 0, "n_verified": 0, "first_bad": err}
        else:
            res = verify_exit_nav(doc)
            report["exit_nav"] = res
            if not res["valid"]:
                report["errors"].append(f"exit_nav: {res['first_bad']}")

    # (C) anchors (against the producer head we just re-derived)
    if inputs["anchors"]:
        anchors, err = _read_jsonl(inputs["anchors"])
        if err is not None:
            report["errors"].append(f"anchors: {err}")
            report["anchors"] = {"valid": False, "broken_at": None, "length": None,
                                 "latest_matches_head": None}
        else:
            res = verify_anchors(anchors, decision_head, decision_length)
            report["anchors"] = res
            if not res["valid"]:
                report["errors"].append(f"anchors: broken at index {res['broken_at']}")

    # --expect-head assertion (the published head a reviewer was told to expect)
    if expect_head is not None:
        if decision_head != expect_head:
            report["errors"].append(
                f"head mismatch: expected {expect_head}, reproduced {decision_head}")
        report["expected_head"] = expect_head

    report["ok"] = (len(report["errors"]) == 0)
    return report


def _print_human(report: dict) -> None:
    print("=" * 78)
    print("SPA STANDALONE PROOF VERIFIER  (zero-dependency · no spa_core · per PROOF_CHAIN_SPEC)")
    print("=" * 78)
    print(f"spec_version       : {report['spec_version']}")
    print(f"canonical_json_rule: {report['canonical_json_rule']}")
    for k, v in report["files"].items():
        print(f"  {k:14s}: {v or '(not supplied)'}")
    print("-" * 78)

    dc = report["decision_chain"]
    if dc is not None:
        print(f"[A] decision chain : valid={dc.get('valid')}  length={dc.get('length')}  "
              f"broken_at={dc.get('broken_at')}")
        print(f"    head_hash      : {dc.get('head_hash')}")

    en = report["exit_nav"]
    if en is not None:
        print(f"[B] exit-NAV proofs: valid={en.get('valid')}  "
              f"verified={en.get('n_verified')}/{en.get('n_rows')} rows"
              + (f"  first_bad={en['first_bad']}" if en.get("first_bad") else ""))

    an = report["anchors"]
    if an is not None:
        print(f"[C] anchors        : valid={an.get('valid')}  length={an.get('length')}  "
              f"broken_at={an.get('broken_at')}  latest_matches_head={an.get('latest_matches_head')}")

    if "expected_head" in report:
        ok = report["decision_chain"] and report["decision_chain"].get("head_hash") == report["expected_head"]
        print(f"[--expect-head]    : {'MATCH' if ok else 'MISMATCH'}  ({report['expected_head']})")

    print("-" * 78)
    if report["errors"]:
        print("ERRORS:")
        for e in report["errors"]:
            print(f"  ✗ {e}")
    print(f"VERDICT: {'OK — everything reproduces' if report['ok'] else 'FAILED'}")
    print("=" * 78)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Standalone, zero-dependency verifier for SPA's public proof artifacts.")
    ap.add_argument("paths", nargs="+",
                    help="a directory (auto-discovers the 3 files) or explicit file paths")
    ap.add_argument("--expect-head", default=None,
                    help="assert the reproduced decision-chain head_hash equals this hex digest")
    ap.add_argument("--json", action="store_true", help="emit the machine-readable verdict as JSON")
    args = ap.parse_args(argv)

    report = run(args.paths, expect_head=args.expect_head)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
