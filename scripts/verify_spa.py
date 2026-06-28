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
      the portfolio section, recomputed from each row's published INPUTS *and* OUTPUTS *and* prev_hash
      (a forged output or a reordered/dropped row diverges the recompute / breaks the prev_hash chain).
  (C) anchors.jsonl      — the head-checkpoint anchors (append-only, monotonic seq). Each in-window
      anchor's head_hash is re-derived from the public chain (the head at length K == rows[K-1].
      entry_hash), so a FABRICATED in-window historical anchor is REJECTED; anchors whose prefix has
      been evicted (or which claim more rows than the public chain) are reported as UNCHECKABLE from
      public files (cross-eviction proof needs the producer ledger — PROOF_CHAIN_SPEC §6a). No over-claim.

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

# exit-nav §6: the per-row proof_hash now covers INPUTS + OUTPUTS + prev_hash (tamper-evidence fix).
# A forged user-facing output (net_proceeds_usd / haircut_pct / flagged / …) breaks the recompute;
# the prev_hash links each schedule into a verifiable chain (genesis '0'*64) so a reordered/dropped
# row is caught too.
EXIT_NAV_ROW_INPUT_KEYS = (
    "ticket_usd", "gross_usd", "depth_usd", "as_of", "model", "model_params", "data_source",
)
EXIT_NAV_ROW_OUTPUT_KEYS = (
    "net_proceeds_usd", "haircut_pct", "price_impact_frac", "flagged", "flag_reason",
    "time_to_exit_days",
)
EXIT_NAV_GENESIS_PREV = "0" * 64


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


def exit_nav_proof_hash(proof_obj: dict) -> str:
    """PROOF_CHAIN_SPEC §6 — SHA-256 over the canonical JSON of {inputs, outputs, prev_hash}.

    The hashed object covers the published INPUTS (ticket/gross/depth/as_of/model/params/source), the
    published OUTPUTS (net_proceeds_usd/haircut_pct/price_impact_frac/flagged/flag_reason/
    time_to_exit_days), and the row's prev_hash (linking it into the per-schedule chain). So forging
    any user-facing number, or reordering/dropping a row, diverges the recompute. The spec recipe uses
    ``default=str``; published values are JSON-native, so it is byte-identical either way."""
    blob = json.dumps(proof_obj, sort_keys=True, separators=(",", ":"), default=str)
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
def _proof_obj_from(row: dict) -> Tuple[Optional[dict], Optional[str]]:
    """Reconstruct the §6 hashed object {inputs, outputs, prev_hash} from a published schedule row.
    Returns (proof_obj, error_or_None). fail-CLOSED: any required field absent → error (the published
    row claims a proof_hash, so all its hashed inputs AND outputs AND prev_hash must be present)."""
    missing_in = [k for k in EXIT_NAV_ROW_INPUT_KEYS if k not in row]
    missing_out = [k for k in EXIT_NAV_ROW_OUTPUT_KEYS if k not in row]
    if "prev_hash" not in row:
        missing_in = missing_in + ["prev_hash"]
    if missing_in or missing_out:
        return None, f"missing field(s): {','.join(missing_in + missing_out)}"
    return {
        "inputs": {k: row[k] for k in EXIT_NAV_ROW_INPUT_KEYS},
        "outputs": {k: row[k] for k in EXIT_NAV_ROW_OUTPUT_KEYS},
        "prev_hash": row["prev_hash"],
    }, None


def _iter_schedules(exit_nav: dict):
    """Yield (section_label, [rows]) for EVERY schedule that carries proof_hash rows: the live
    `schedule`, the `illustrative.schedule`, and each `portfolio.markets[*].schedule`. Yielding whole
    schedules (not flat rows) lets the verifier check the per-schedule prev_hash chain (each schedule
    is its own chain, genesis '0'*64)."""
    if not isinstance(exit_nav, dict):
        return
    live = exit_nav.get("schedule")
    if isinstance(live, list):
        yield ("live", live)
    illus = exit_nav.get("illustrative")
    if isinstance(illus, dict) and isinstance(illus.get("schedule"), list):
        yield ("illustrative", illus["schedule"])
    portfolio = exit_nav.get("portfolio")
    if isinstance(portfolio, dict):
        for mi, mkt in enumerate(portfolio.get("markets") or []):
            if not isinstance(mkt, dict):
                continue
            mid = mkt.get("market_id", mi)
            sched = mkt.get("schedule")
            if isinstance(sched, list):
                yield (f"portfolio[{mid}]", sched)


def _iter_schedule_rows(exit_nav: dict):
    """Yield (label, row) for EVERY schedule row that carries a proof_hash (compat helper for callers
    that want flat rows; the chain check lives in verify_exit_nav over whole schedules)."""
    for section, rows in _iter_schedules(exit_nav):
        for i, r in enumerate(rows):
            if isinstance(r, dict) and "proof_hash" in r:
                yield (f"{section}[{i}]", r)


def verify_exit_nav(exit_nav: dict) -> dict:
    """Recompute every published exit-NAV proof_hash (§6) AND verify each schedule's prev_hash chain.
    Returns {valid, n_rows, n_verified, first_bad}. fail-CLOSED: any row missing inputs/outputs,
    mismatching its stored proof_hash, OR a broken prev_hash linkage → valid=False with first_bad set
    to the precise section label. The chain check makes a reordered/dropped/inserted row detectable:
    each schedule is its own chain (genesis '0'*64); row i's prev_hash must equal row i-1's proof_hash."""
    n_rows = 0
    n_ok = 0
    first_bad: Optional[str] = None
    for section, rows in _iter_schedules(exit_nav):
        expected_prev = EXIT_NAV_GENESIS_PREV
        for i, row in enumerate(rows):
            if not (isinstance(row, dict) and "proof_hash" in row):
                continue
            label = f"{section}[{i}]"
            n_rows += 1
            # (1) prev_hash chain linkage (genesis '0'*64; else previous row's proof_hash)
            if row.get("prev_hash") != expected_prev:
                first_bad = first_bad or f"{label}: prev_hash chain broken"
                expected_prev = row.get("proof_hash")  # advance so later labels stay meaningful
                continue
            # (2) recompute proof_hash over inputs + outputs + prev_hash
            proof_obj, err = _proof_obj_from(row)
            if err is not None:
                first_bad = first_bad or f"{label}: {err}"
                expected_prev = row.get("proof_hash")
                continue
            recomputed = exit_nav_proof_hash(proof_obj)
            if recomputed == row.get("proof_hash"):
                n_ok += 1
            else:
                first_bad = first_bad or f"{label}: proof_hash mismatch"
            expected_prev = row.get("proof_hash")
    valid = (first_bad is None)
    return {"valid": valid, "n_rows": n_rows, "n_verified": n_ok, "first_bad": first_bad}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (C) cross-eviction anchors — verified against the producer head they checkpoint
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def verify_anchors(anchors: List[dict], decision_head: Optional[str],
                   decision_length: Optional[int],
                   decision_rows: Optional[List[dict]] = None) -> dict:
    """Verify the append-only anchor ledger (anchors.jsonl) — PROOF_CHAIN_SPEC §6a.

    Each anchor = {ts, seq, head_hash, chain_length}. `head_hash` is the PUBLIC decision mirror's
    §5 head (its LAST row's entry_hash) at the checkpointed `chain_length`. Because the mirror is a
    single-genesis, re-based chain, the head at ANY in-window length K equals `rows[K-1].entry_hash` —
    so a historical anchor whose checkpointed rows are STILL in the published window IS independently
    checkable (this is the honesty fix: a fabricated historical anchor no longer silently passes).

    Checks:
      1. append-only monotonic seq: anchor.seq runs 0..N contiguous (strictly increasing).
      2. monotonic chain_length: never checkpoints a SHORTER chain than an earlier anchor.
      3. head consistency, as far as the PUBLIC files allow:
         (a) clen == decision_length  → head MUST == decision_head (the current window head);
         (b) clen <  decision_length and the checkpointed prefix is still in-window (i.e. row
             [clen-1] is present in decision_rows) → head MUST == decision_rows[clen-1].entry_hash
             (historical in-window anchor — NOW verified, not skipped);
         (c) the prefix has been EVICTED (clen-1 no longer in the window, e.g. genesis moved past it),
             or no decision file was supplied → the anchor's head CANNOT be re-derived from the public
             files alone. We mark it UNCHECKABLE rather than silently pass. Cross-eviction proof of
             such an anchor requires the authoritative append-only producer ledger (see §6a) — the
             public ring-buffer alone cannot deliver it, and we do not claim it can.

    fail-CLOSED. Returns {valid, length, broken_at, latest_matches_head, n_historical_verified,
    n_uncheckable}. Empty is vacuously valid. NOTE: an `uncheckable` historical anchor does NOT fail
    the ledger (we cannot prove it wrong from public files), but it is COUNTED + reported so the claim
    stays honest — `n_uncheckable > 0` means some anchors rest on the producer ledger, not these files."""
    n = len(anchors)
    if n == 0:
        return {"valid": True, "length": 0, "broken_at": None, "latest_matches_head": None,
                "n_historical_verified": 0, "n_uncheckable": 0}
    # entry_hash by chain_length: the re-based mirror's head at length K is row[K-1].entry_hash.
    head_at_length = {}
    if decision_rows:
        for i, r in enumerate(decision_rows):
            if isinstance(r, dict) and isinstance(r.get("entry_hash"), str):
                head_at_length[i + 1] = r["entry_hash"]
    in_window_min_length = (min(head_at_length) if head_at_length else None)
    prev_seq = -1
    prev_len = -1
    latest_matches_head: Optional[bool] = None
    n_hist_ok = 0
    n_uncheckable = 0
    for idx, a in enumerate(anchors):
        if not isinstance(a, dict):
            return _anchor_fail(n, idx)
        seq = a.get("seq")
        clen = a.get("chain_length")
        head = a.get("head_hash")
        if not isinstance(seq, int) or seq != idx:
            return _anchor_fail(n, idx)
        if seq <= prev_seq:  # strictly monotonic (defensive; seq==idx already implies it)
            return _anchor_fail(n, idx)
        if not isinstance(clen, int) or clen < prev_len:
            return _anchor_fail(n, idx)
        if not isinstance(head, str) or len(head) != 64:
            return _anchor_fail(n, idx)
        # (3a) current-window head.
        if decision_head is not None and decision_length is not None and clen == decision_length:
            if head != decision_head:
                return {"valid": False, "length": n, "broken_at": idx, "latest_matches_head": False,
                        "n_historical_verified": n_hist_ok, "n_uncheckable": n_uncheckable}
            latest_matches_head = True
        # (3b) historical anchor whose checkpointed prefix is STILL in-window → re-derivable + checked.
        elif clen in head_at_length:
            if head != head_at_length[clen]:
                # a FABRICATED historical anchor: claims a head the public chain does not reproduce.
                return {"valid": False, "length": n, "broken_at": idx, "latest_matches_head": None,
                        "n_historical_verified": n_hist_ok, "n_uncheckable": n_uncheckable}
            n_hist_ok += 1
        # (3c) anchor longer than the current chain, or prefix evicted, or no decision file supplied.
        else:
            if (decision_length is not None and clen > decision_length):
                # an anchor claiming MORE rows than the published chain has → unreproducible forward
                # claim. Not fabricated-detectable as wrong-head, but it cannot be checked → uncheckable.
                n_uncheckable += 1
            elif (in_window_min_length is not None and clen < in_window_min_length):
                # the checkpointed prefix has been evicted from the window → uncheckable from public
                # files (needs the producer ledger). Honest: counted, not silently passed.
                n_uncheckable += 1
            else:
                n_uncheckable += 1
        prev_seq = seq
        prev_len = clen
    return {"valid": True, "length": n, "broken_at": None, "latest_matches_head": latest_matches_head,
            "n_historical_verified": n_hist_ok, "n_uncheckable": n_uncheckable}


def _anchor_fail(n: int, idx: int) -> dict:
    return {"valid": False, "length": n, "broken_at": idx, "latest_matches_head": None,
            "n_historical_verified": 0, "n_uncheckable": 0}


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
    decision_rows: Optional[List[dict]] = None

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
                decision_rows = rows  # carried so historical in-window anchors are checkable (§6a)
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
            res = verify_anchors(anchors, decision_head, decision_length, decision_rows)
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
        print(f"    historical     : verified_in_window={an.get('n_historical_verified')}  "
              f"uncheckable_from_public_files={an.get('n_uncheckable')}  "
              f"(uncheckable anchors require the producer ledger — see PROOF_CHAIN_SPEC §6a)")

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
