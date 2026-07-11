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

It AUTO-DISCOVERS and verifies EVERY anchored surface under the supplied path (recursively when a
directory is given), each with its own zero-dependency recipe, and reports a COMBINED manifest with
ONE exit code. The surfaces:
  (A) rates-desk decision chain   — decision_log.jsonl
  (B) rates-desk exit-NAV proofs  — exit_nav.json
  (C) rates-desk anchors          — anchors.jsonl
  (D) evidenced equity track      — equity_track.jsonl
  (E) tournament ranking chain    — tournament/decision_log.jsonl  (WORKSTREAM 2 proof-breadth)
  (F) RWA-backstop NAV proof      — rwa_backstop/nav_proof.jsonl   (WORKSTREAM 2 proof-breadth)
  (G) sleeve forward-series proofs — rates_desk/paper/*_series_proof.jsonl (WORKSTREAM 2, many files)
  (H) underwriting report chain   — underwriting/report_proof.jsonl (LANE C moat: the hash-anchored,
      publicly-verifiable underwriting artifact; per-section proof_hash + chained + refusal-consistency)

(E)/(F)/(G) learn from the two flaws the rates-desk red-team caught: each proof covers the published
OUTPUTS (rank/strategy/net_return/sharpe · tvl_weighted_nav/liq_nav_gap · equity/apy/book-counts),
NOT just the inputs, AND chains the rows (per-row prev_hash) — so forging a published value or
reordering/dropping a row is caught, never silently passed (FAIL#2); and they are regenerated together
with their producer so they never rot (F1).

It verifies these independent published proofs:
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

  (D) equity_track.jsonl is the EVIDENCED equity / go-live track, hash-chained the same way as (A):
      each row covers one evidenced equity bar (open/close equity, daily yield, apy, source) and the
      chain is single-genesis + contiguous seq + prev-linkage. A forged equity number, or a
      reordered/dropped/inserted/back-dated day, DIVERGES the recompute and is reported as a precise
      broken_at. This is what makes the track-record page's "verify this track yourself" claim
      literally true: the equity track is now independently re-derivable, not just the decisions.

USAGE
    python3 verify_spa.py data/                           # WHOLE data dir: covers ALL 7 surfaces
    python3 verify_spa.py data/rates_desk/                # a subtree: auto-discovers what is there
    python3 verify_spa.py decision_log.jsonl exit_nav.json anchors.jsonl   # explicit files
    python3 verify_spa.py --expect-head <hex> data/       # also assert the published chain head
    python3 verify_spa.py --expect-surfaces A,D,E,F,G data/   # FAIL CLOSED if a surface is absent
    python3 verify_spa.py --json data/                    # machine-readable verdict to stdout

NOTE: the WHOLE-DIR form ``verify_spa.py data/`` is the documented reviewer command — it covers
ALL seven surfaces (rates-desk A/B/C/D plus tournament E, RWA-NAV F, sleeve G). Running the
narrower ``data/rates_desk/`` form only ever sees A–D and SILENTLY never checks E/F/G; use
``--expect-surfaces`` (or the whole-dir form) to fail closed when a surface you require is absent.

COVERAGE ENFORCEMENT (FAIL#5): a PRODUCER present without its matching verified PROOF is a FAIL,
never a silent pass — e.g. a ``data/rates_desk/paper/<sleeve>_series.json`` with no matching
``<sleeve>_series_proof.jsonl``, or a truncated/empty proof for a present producer.

EXIT CODES
    0  all supplied proofs reproduce exactly (and any --expect-head / --expect-surfaces satisfied)
    1  any mismatch, malformed row, missing required field, unreadable required file, a present
       producer with a missing/empty proof, or a required surface absent
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal, InvalidOperation
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

# equity-track §8 (F2): the EVIDENCED equity / go-live track, hash-chained like the decision log.
# Each row's entry_hash = sha256(canonical({seq, date, kind, payload, prev_hash})) with kind fixed
# and payload = the row minus the four envelope keys. Single-genesis '0'*64, contiguous seq.
EQUITY_TRACK_EVENT_TYPE = "equity_track_bar"
EQUITY_TRACK_GENESIS_PREV = "0" * 64
EQUITY_TRACK_ENVELOPE_KEYS = ("seq", "date", "prev_hash", "entry_hash")

# ── WORKSTREAM 2 proof-breadth surfaces (the SAME canonical-JSON + SHA-256 rule; output-covering) ──

# (E) tournament ranking chain — each daily ranking row covers rank/strategy/net_return/sharpe and is
# chained (single-genesis, contiguous seq). entry_hash = sha256(canonical({seq, ts, kind, payload,
# prev_hash})) with kind fixed, payload = the row minus the four envelope keys. Forging a published
# rank/strategy/sharpe/net_return, or reordering a ranking, DIVERGES the recompute.
TOURNAMENT_EVENT_TYPE = "tournament_ranking_row"
TOURNAMENT_GENESIS_PREV = "0" * 64
TOURNAMENT_ENVELOPE_KEYS = ("seq", "ts", "prev_hash", "entry_hash")

# (F) RWA-backstop NAV proof — exit-NAV §6 pattern over each forward point: per-row proof_hash over
# {inputs, outputs, prev_hash}, chained (genesis '0'*64). Forging tvl_weighted_nav / liq_nav_gap_pct,
# or reordering/dropping a forward point, DIVERGES the recompute / breaks the chain.
NAV_PROOF_GENESIS_PREV = "0" * 64
NAV_PROOF_INPUT_KEYS = ("date", "ts", "n_assets", "onchain_4626_count", "off_chain_estimate_count")
NAV_PROOF_OUTPUT_KEYS = ("tvl_weighted_nav", "liq_nav_gap_pct")

# (G) sleeve forward-series proofs — each sleeve series chained like the equity track. entry_hash =
# sha256(canonical({seq, date, kind, payload, prev_hash})) with kind fixed, payload = the row minus
# the four envelope keys. Forging a forward equity/apy/book-count, or reordering/back-dating a day,
# DIVERGES the recompute. MANY such files (one per sleeve) are auto-discovered + verified.
SLEEVE_EVENT_TYPE = "sleeve_forward_point"
SLEEVE_GENESIS_PREV = "0" * 64
SLEEVE_ENVELOPE_KEYS = ("seq", "date", "prev_hash", "entry_hash")

# (H) underwriting report (LANE C — the productized, hash-anchored, publicly-verifiable underwriting
# artifact, the moat sold as risk infrastructure). data/underwriting/report_proof.jsonl is the
# section chain: one row per report SECTION (meta/refusals/depth/realized/capacity), single-genesis,
# contiguous seq, prev-linked. EACH section carries TWO anchors verified here:
#   • its own ``proof_hash``  = sha256(canonical(section_body − {proof_hash, seq, prev_hash, entry_hash}))
#   • its chain ``entry_hash`` = sha256(canonical({seq, section_id, event_type, payload, prev_hash}))
#     where payload = the section MINUS {seq, prev_hash, entry_hash} (it still carries its proof_hash),
#     and event_type = the fixed UNDERWRITING_EVENT_TYPE.
# Forging a published section value (e.g. laundering survives_at_aum_usd in the realized section, or
# claiming a REFUSED market as underwritten capacity), or reordering/dropping a section, DIVERGES the
# recompute. NO spa_core import — the recipe is inlined per docs/UNDERWRITING_REPORT_SPEC.md.
UNDERWRITING_EVENT_TYPE = "underwriting_report_section"
UNDERWRITING_GENESIS_PREV = "0" * 64
UNDERWRITING_ENVELOPE_KEYS = ("seq", "prev_hash", "entry_hash")


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


def recompute_equity_entry_hash(row: dict) -> str:
    """equity-track §8 — SHA-256 over canonical({seq, date, kind, payload, prev_hash}) where
    payload = the row minus the four envelope keys and kind = the fixed EQUITY_TRACK_EVENT_TYPE.
    Mirrors recompute_entry_hash; the equity track is just a second single-genesis chain."""
    payload = {k: v for k, v in row.items() if k not in EQUITY_TRACK_ENVELOPE_KEYS}
    canonical = _canonical({
        "seq": row.get("seq"),
        "date": row.get("date"),
        "kind": EQUITY_TRACK_EVENT_TYPE,
        "payload": payload,
        "prev_hash": row.get("prev_hash"),
    })
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def recompute_tournament_entry_hash(row: dict) -> str:
    """(E) tournament — SHA-256 over canonical({seq, ts, kind, payload, prev_hash}) where payload =
    the row minus the four envelope keys and kind = TOURNAMENT_EVENT_TYPE. The payload carries the
    OUTPUTS (rank/strategy/sharpe/net_return), so forging any of them diverges the recompute."""
    payload = {k: v for k, v in row.items() if k not in TOURNAMENT_ENVELOPE_KEYS}
    canonical = _canonical({
        "seq": row.get("seq"),
        "ts": row.get("ts"),
        "kind": TOURNAMENT_EVENT_TYPE,
        "payload": payload,
        "prev_hash": row.get("prev_hash"),
    })
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def recompute_sleeve_entry_hash(row: dict) -> str:
    """(G) sleeve — SHA-256 over canonical({seq, date, kind, payload, prev_hash}) where payload =
    the row minus the four envelope keys and kind = SLEEVE_EVENT_TYPE. The payload carries the
    forward OUTPUTS (equity/apy/book-counts), so forging any of them diverges the recompute."""
    payload = {k: v for k, v in row.items() if k not in SLEEVE_ENVELOPE_KEYS}
    canonical = _canonical({
        "seq": row.get("seq"),
        "date": row.get("date"),
        "kind": SLEEVE_EVENT_TYPE,
        "payload": payload,
        "prev_hash": row.get("prev_hash"),
    })
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def recompute_underwriting_section_proof_hash(section: dict) -> str:
    """(H) underwriting — the per-section proof_hash: SHA-256 over canonical(section_body) where the
    body is the section MINUS {proof_hash, seq, prev_hash, entry_hash}. Independent of chain position;
    a reviewer recomputes it from the published section content alone."""
    body = {k: v for k, v in section.items()
            if k not in ("proof_hash", "seq", "prev_hash", "entry_hash")}
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def recompute_underwriting_entry_hash(section: dict) -> str:
    """(H) underwriting — the chain entry_hash: SHA-256 over canonical({seq, section_id, event_type,
    payload, prev_hash}) where payload = the section minus the three envelope keys (it still carries
    its own proof_hash, so the chain binds the section proof) and event_type = the fixed constant."""
    payload = {k: v for k, v in section.items() if k not in UNDERWRITING_ENVELOPE_KEYS}
    canonical = _canonical({
        "seq": section.get("seq"),
        "section_id": section.get("section_id"),
        "event_type": UNDERWRITING_EVENT_TYPE,
        "payload": payload,
        "prev_hash": section.get("prev_hash"),
    })
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def nav_proof_hash(row: dict) -> str:
    """(F) RWA-backstop NAV — SHA-256 over the canonical JSON of {inputs, outputs, prev_hash}
    reconstructed from a published forward-point row (exit-NAV §6 recipe; default=str). Covering the
    OUTPUTS (tvl_weighted_nav / liq_nav_gap_pct) makes a forged NAV number detectable; the prev_hash
    chains the points so a reordered/dropped/inserted forward point is caught."""
    proof_obj = {
        "inputs": {k: row.get(k) for k in NAV_PROOF_INPUT_KEYS},
        "outputs": {k: row.get(k) for k in NAV_PROOF_OUTPUT_KEYS},
        "prev_hash": row.get("prev_hash"),
    }
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
# (A-replay) DECISION REPLAY — re-DERIVE each verdict from its OWN published numbers  [Q2-2]
# ══════════════════════════════════════════════════════════════════════════════════════════════════
_REPLAY_TOL = Decimal("1e-9")


def _dec(x) -> Optional[Decimal]:
    """Parse a published Decimal-string/number → Decimal, or None if unparseable."""
    if x is None:
        return None
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError):
        return None


def verify_decision_replay(rows: List[dict]) -> dict:
    """RE-DERIVE each published verdict from its OWN published inputs — not a re-hash (that only proves
    the row wasn't edited), but an independent check that the STORED verdict actually FOLLOWS from the
    numbers the desk published alongside it. Trusts neither the stored ``fair_yield`` nor ``approved``.

    Per row, fail-CLOSED on the first violation:
      • D1 fair-value identity     — decomposition.fair_yield == baseline − total_haircut (±1e-9). A
        tampered fair_yield that no longer equals baseline minus the published haircuts is caught here.
      • D2 haircut non-negativity  — every published structural haircut ≥ 0 (a negative haircut would be
        a fabricated "credit" inflating fair value); total_haircut ≥ 0.
      • D3 approve→edge coherence  — approved==True ⇒ net_edge > 0 (REFUSAL-FIRST never enters a book
        whose own published net edge is ≤ 0). A flipped ``approved`` on a non-positive-edge book is caught.
      • D4 refuse→reason coherence — approved==False ⇒ a non-empty ``reason`` (every refusal is explained).

    Returns {checked, passed, failed, first_bad, invariants:{d1,d2,d3,d4 counts}}. Empty ⇒ vacuously ok.
    HONEST SCOPE: this replays the published DECOMPOSITION→verdict coherence. Re-deriving the haircuts
    THEMSELVES from raw Pendle history + pinned calibration (fuller moat proof) is the next increment."""
    checked = passed = 0
    inv = {"d1_identity": 0, "d2_nonneg": 0, "d3_approve_edge": 0, "d4_refuse_reason": 0}
    first_bad: Optional[dict] = None

    def _fail(idx, code, msg):
        nonlocal first_bad
        if first_bad is None:
            first_bad = {"row": idx, "check": code, "detail": msg}

    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            _fail(idx, "shape", "row is not an object")
            continue
        checked += 1
        ok = True

        decomp = row.get("decomposition")
        if isinstance(decomp, dict):
            base = _dec(decomp.get("baseline"))
            total = _dec(decomp.get("total_haircut"))
            fair = _dec(decomp.get("fair_yield"))
            # D1 — fair-value identity
            if base is not None and total is not None and fair is not None:
                if abs((base - total) - fair) <= _REPLAY_TOL:
                    inv["d1_identity"] += 1
                else:
                    ok = False
                    _fail(idx, "D1_identity",
                          f"fair_yield {fair} != baseline {base} − total_haircut {total}")
            # D2 — every haircut component (and the total) non-negative
            hc_keys = [k for k in decomp if k.endswith("_haircut")]
            neg = [k for k in hc_keys if (_dec(decomp.get(k)) or Decimal(0)) < 0]
            if not neg:
                inv["d2_nonneg"] += 1
            else:
                ok = False
                _fail(idx, "D2_nonneg", f"negative haircut(s): {neg}")

        # D3 — approved ⇒ net_edge > 0  (refusal-first never enters non-positive edge)
        approved = bool(row.get("approved"))
        ne = _dec(row.get("net_edge"))
        if approved:
            if ne is not None and ne > 0:
                inv["d3_approve_edge"] += 1
            else:
                ok = False
                _fail(idx, "D3_approve_edge",
                      f"approved but net_edge={row.get('net_edge')} is not > 0")
        else:
            # D4 — every refusal carries a reason
            if str(row.get("reason") or "").strip():
                inv["d4_refuse_reason"] += 1
            else:
                ok = False
                _fail(idx, "D4_refuse_reason", "refused with empty reason")

        if ok:
            passed += 1

    return {"checked": checked, "passed": passed, "failed": checked - passed,
            "first_bad": first_bad, "invariants": inv}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (offline) SNAPSHOT INTEGRITY — a funder replays a FROZEN checksummed dataset with no live API  [Q2-10]
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def verify_snapshot_manifest(snapshot_dir: Path) -> dict:
    """OFFLINE reproducibility: assert every file pinned in SNAPSHOT_MANIFEST.json is present and
    BYTE-IDENTICAL to its recorded sha256 + byte-count. A funder who cloned the frozen DD snapshot
    proves the dataset is EXACTLY what was published — no live API, no trust in us. fail-CLOSED on any
    missing / resized / tampered file. Also surfaces the manifest's pinned expected_decision_head +
    expected_surfaces so ``--offline`` can auto-apply them (the funder needn't copy them by hand).

    Returns {manifest_present, checked, matched, mismatched, first_bad, expected_decision_head,
    expected_surfaces}. A manifest that is absent/malformed is reported (manifest_present False) and
    fails CLOSED at the call site."""
    out = {"manifest_present": False, "checked": 0, "matched": 0, "mismatched": 0,
           "first_bad": None, "expected_decision_head": None, "expected_surfaces": None}
    mpath = snapshot_dir / "SNAPSHOT_MANIFEST.json"
    if not mpath.exists():
        out["first_bad"] = {"file": "SNAPSHOT_MANIFEST.json", "reason": "manifest absent"}
        return out
    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — malformed manifest → fail-CLOSED
        out["first_bad"] = {"file": "SNAPSHOT_MANIFEST.json", "reason": f"parse error: {exc}"}
        return out
    out["manifest_present"] = True
    out["expected_decision_head"] = manifest.get("expected_decision_head")
    out["expected_surfaces"] = manifest.get("expected_surfaces")
    for f in manifest.get("files", []):
        if f.get("absent") or not f.get("sha256"):
            continue  # source was absent at freeze time (recorded, not a pinned file)
        out["checked"] += 1
        fp = snapshot_dir / f.get("arcname", "")
        if not fp.exists():
            out["mismatched"] += 1
            if out["first_bad"] is None:
                out["first_bad"] = {"file": f.get("arcname"), "reason": "pinned file missing"}
            continue
        raw = fp.read_bytes()
        got = hashlib.sha256(raw).hexdigest()
        if got == f["sha256"] and len(raw) == f.get("bytes", len(raw)):
            out["matched"] += 1
        else:
            out["mismatched"] += 1
            if out["first_bad"] is None:
                out["first_bad"] = {"file": f.get("arcname"), "reason": "sha256/size mismatch",
                                    "pinned": f["sha256"], "got": got}
    return out


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (D) equity track — the EVIDENCED equity / go-live track, hash-chained like (A)  [F2]
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def verify_equity_track(rows: List[dict]) -> dict:
    """Walk evidenced equity rows in seq order; at each row require (1) seq == idx, (2) prev_hash ==
    previous entry_hash (genesis '0'*64), (3) recompute_equity_entry_hash(row) == entry_hash.
    fail-CLOSED on any malformed row. Returns {valid, length, broken_at, head_hash, n_days,
    first_date, last_date}. Empty is vacuously valid (no evidenced days yet → honest empty chain)."""
    expected_prev = EQUITY_TRACK_GENESIS_PREV
    head_hash: Optional[str] = None
    first_date: Optional[str] = None
    last_date: Optional[str] = None
    n = len(rows)

    def _fail(idx: int) -> dict:
        return {"valid": False, "length": n, "broken_at": idx, "head_hash": None,
                "n_days": 0, "first_date": None, "last_date": None}

    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return _fail(idx)
        if row.get("seq") != idx:
            return _fail(idx)
        if row.get("prev_hash") != expected_prev:
            return _fail(idx)
        try:
            recomputed = recompute_equity_entry_hash(row)
        except Exception:  # noqa: BLE001 — malformed row → fail-CLOSED
            return _fail(idx)
        if recomputed != row.get("entry_hash"):
            return _fail(idx)
        if first_date is None:
            first_date = row.get("date")
        last_date = row.get("date")
        expected_prev = row["entry_hash"]
        head_hash = row["entry_hash"]
    return {"valid": True, "length": n, "broken_at": None, "head_hash": head_hash,
            "n_days": n, "first_date": first_date, "last_date": last_date}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (E) tournament ranking chain — output-covering, chained (WORKSTREAM 2 proof-breadth)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def verify_tournament_chain(rows: List[dict]) -> dict:
    """Walk ranking rows in seq order; at each row require (1) seq == idx, (2) prev_hash == previous
    entry_hash (genesis '0'*64), (3) recompute_tournament_entry_hash(row) == entry_hash. fail-CLOSED
    on any malformed row. Returns {valid, length, broken_at, head_hash}. Empty is vacuously valid.
    A forged published rank/strategy/sharpe/net_return, or a reordered ranking, → precise broken_at."""
    expected_prev = TOURNAMENT_GENESIS_PREV
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
            recomputed = recompute_tournament_entry_hash(row)
        except Exception:  # noqa: BLE001 — malformed row → fail-CLOSED
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if recomputed != row.get("entry_hash"):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        expected_prev = row["entry_hash"]
        head_hash = row["entry_hash"]
    return {"valid": True, "length": n, "broken_at": None, "head_hash": head_hash}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (F) RWA-backstop NAV forward-record proof — exit-NAV §6 pattern, chained (WORKSTREAM 2)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def verify_nav_proof(rows: List[dict]) -> dict:
    """Walk forward-point rows; at each require (1) prev_hash == previous proof_hash (genesis
    '0'*64), (2) nav_proof_hash(row) == proof_hash (recomputed from inputs+outputs+prev_hash).
    fail-CLOSED on any malformed row. Returns {valid, length, broken_at, head_hash}. Empty is
    vacuously valid. A forged tvl_weighted_nav/liq_nav_gap, or a reordered/dropped point, → broken_at."""
    expected_prev = NAV_PROOF_GENESIS_PREV
    head_hash: Optional[str] = None
    n = len(rows)
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if row.get("prev_hash") != expected_prev:
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        try:
            recomputed = nav_proof_hash(row)
        except Exception:  # noqa: BLE001 — malformed row → fail-CLOSED
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if recomputed != row.get("proof_hash"):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        expected_prev = row["proof_hash"]
        head_hash = row["proof_hash"]
    return {"valid": True, "length": n, "broken_at": None, "head_hash": head_hash}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (G) sleeve forward-series proof — chained like the equity track (WORKSTREAM 2; MANY files)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def verify_sleeve_chain(rows: List[dict]) -> dict:
    """Walk forward-point rows in seq order; at each require (1) seq == idx, (2) prev_hash ==
    previous entry_hash (genesis '0'*64), (3) recompute_sleeve_entry_hash(row) == entry_hash.
    fail-CLOSED. Returns {valid, length, broken_at, head_hash}. Empty is vacuously valid. A forged
    forward equity/apy/book-count, or a reordered/back-dated day, → precise broken_at."""
    expected_prev = SLEEVE_GENESIS_PREV
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
            recomputed = recompute_sleeve_entry_hash(row)
        except Exception:  # noqa: BLE001 — malformed row → fail-CLOSED
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        if recomputed != row.get("entry_hash"):
            return {"valid": False, "length": n, "broken_at": idx, "head_hash": None}
        expected_prev = row["entry_hash"]
        head_hash = row["entry_hash"]
    return {"valid": True, "length": n, "broken_at": None, "head_hash": head_hash}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# (H) underwriting report section chain — LANE C moat (per-section proof_hash + chained entry_hash)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# refusal-consistency: the verdict the refusal section published as REFUSE for a market must NEVER
# appear as an underwritten-capacity market. A reviewer checks this from the public sections alone.
_UNDERWRITING_REFUSE = "REFUSE"


def verify_underwriting_chain(rows: List[dict]) -> dict:
    """Walk underwriting report SECTIONS in seq order; at each require (1) seq == idx, (2) prev_hash ==
    previous entry_hash (genesis '0'*64), (3) the per-section proof_hash recomputes over the body,
    (4) the chain entry_hash recomputes. THEN enforce the cross-section REFUSAL-CONSISTENCY property:
    a market the ``refusals`` section marked REFUSE must NOT appear in the ``capacity`` section's
    ``capacity_markets`` (a refused market cannot be sold as underwritten capacity). fail-CLOSED on
    any malformed section or a broken property. Returns {valid, length, broken_at, head_hash,
    published, refusal_consistent}. Empty is vacuously valid.

    A forged published section value (e.g. a laundered survives_at_aum_usd, a section reorder/drop, or
    a REFUSED market smuggled into capacity) → precise broken_at / refusal_consistent=False."""
    expected_prev = UNDERWRITING_GENESIS_PREV
    head_hash: Optional[str] = None
    n = len(rows)
    refused: set = set()
    capacity_syms: set = set()
    published: Optional[bool] = None

    def _fail(idx: int) -> dict:
        return {"valid": False, "length": n, "broken_at": idx, "head_hash": None,
                "published": published, "refusal_consistent": None}

    for idx, sec in enumerate(rows):
        if not isinstance(sec, dict):
            return _fail(idx)
        if sec.get("seq") != idx:
            return _fail(idx)
        if sec.get("prev_hash") != expected_prev:
            return _fail(idx)
        if recompute_underwriting_section_proof_hash(sec) != sec.get("proof_hash"):
            return _fail(idx)
        try:
            recomputed = recompute_underwriting_entry_hash(sec)
        except Exception:  # noqa: BLE001 — malformed section → fail-CLOSED
            return _fail(idx)
        if recomputed != sec.get("entry_hash"):
            return _fail(idx)
        # gather the cross-section refusal-consistency facts from the verified (untampered) sections.
        sid = sec.get("section_id")
        if sid == "meta":
            published = sec.get("published")
        elif sid == "refusals":
            for v in (sec.get("verdicts") or []):
                if isinstance(v, dict) and v.get("verdict") == _UNDERWRITING_REFUSE:
                    refused.add(v.get("symbol"))
        elif sid == "capacity":
            for m in (sec.get("capacity_markets") or []):
                if isinstance(m, dict):
                    capacity_syms.add(m.get("symbol") or m.get("market_id") or m.get("underlying"))
        expected_prev = sec["entry_hash"]
        head_hash = sec["entry_hash"]

    # REFUSAL-CONSISTENCY (red-team #3): no REFUSED market may be sold as underwritten capacity.
    smuggled = sorted(str(s) for s in (refused & capacity_syms) if s is not None)
    refusal_consistent = (len(smuggled) == 0)
    if not refusal_consistent:
        return {"valid": False, "length": n, "broken_at": None, "head_hash": head_hash,
                "published": published, "refusal_consistent": False, "smuggled_markets": smuggled}
    return {"valid": True, "length": n, "broken_at": None, "head_hash": head_hash,
            "published": published, "refusal_consistent": True}


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


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# FUNDABILITY reproduction (--check-fundability) — recompute every realized carry-above-floor bps from
#     the RAW series and assert it equals the PUBLISHED carry_truth_table.json (WORKSTREAM 6
#     "Prove the Edge"). NOTE: this is an opt-in reproduction check, NOT a lettered proof-chain surface
#     (the lettered surfaces are A–H); it is gated behind --check-fundability.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# This is the WS6 "don't trust us, check us" surface for the FUNDABILITY sheet: a reviewer must be
# able to reproduce EVERY realized fundability number from the raw forward series alone, with no
# spa_core. We re-derive each sleeve's carry-above-floor (bps/yr) directly from its raw
# *_series.json equity path — using the floor-leg/carry-leg residual split inlined verbatim from
# spa_core.strategy_lab.forward_analytics.captured_book_attribution + carry_truth_table — and assert
# it matches the published carry_truth_table.json to the published precision.
#
# TAMPER-EVIDENCE (the red-team): if someone forges a published bps in carry_truth_table.json (e.g.
# flips a below-floor sleeve to "+50 bps beats floor"), the recompute from the RAW series DIVERGES
# and this check FAILS with the precise sleeve. And — the INSUFFICIENT_DATA-hidden-behind-0.0 path —
# a published `null` bps recomputed to a real number, OR a real bps published as null, is a MISMATCH.
# A null published bps is honest ONLY when the raw series genuinely has < 2 dated points / zero
# elapsed (no realized carry move to measure); we re-derive that condition from the raw series too.

# the carry-bps precision the producer publishes (carry_truth_table rounds pp→bps to 2 dp).
_FUNDABILITY_BPS_DP = 2
# the producer's depth bar for a NUMERIC bps (carry_truth_table: < 2 dated points / zero elapsed →
# null bps). We reproduce the SAME null-vs-number decision from the raw series, never the published flag.
_FUNDABILITY_MIN_POINTS = 2


def _raw_series_points(doc) -> Optional[List[dict]]:
    """Coerce a raw *_series.json doc to its list of forward points (or None if unusable). Accepts
    {"series":[...]} or a bare list (mirrors track_integrity._coerce_series, inlined)."""
    if isinstance(doc, dict):
        s = doc.get("series")
        return s if isinstance(s, list) else None
    if isinstance(doc, list):
        return doc
    return None


def _recompute_carry_bps(points: List[dict], floor_apy_pct: float) -> Tuple[Optional[float], str]:
    """Re-derive carry-above-floor (bps/yr) from a raw forward equity path — the EXACT recipe the
    producer uses (captured_book_attribution floor-leg/carry-leg residual split + carry_truth_table
    annualization), inlined with zero spa_core import. Returns (bps_or_None, reason).

    fail-CLOSED: a non-numeric/non-finite equity, a < 2-point / zero-elapsed track, or a zero initial
    capital → (None, reason) — the honest INSUFFICIENT_DATA condition (null bps), re-derived from the
    RAW series, NEVER read from the published flag. carry is the residual (carry+floor==realized PnL),
    so no leg can be inflated independently."""
    eq: List[float] = []
    for p in points:
        if not isinstance(p, dict):
            return None, "malformed point"
        v = p.get("equity_usd")
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return None, "non-numeric equity_usd"
        fv = float(v)
        if fv != fv or fv in (float("inf"), float("-inf")):  # NaN/inf without importing math
            return None, "non-finite equity_usd"
        eq.append(fv)
    if len(eq) < _FUNDABILITY_MIN_POINTS:
        return None, "< 2 dated points (no realized carry move)"
    initial = eq[0]
    if initial == 0:
        return None, "zero initial capital"
    nav = eq[-1]
    realized_pnl = nav - initial
    floor_daily = (float(floor_apy_pct) / 100.0) / 365.0
    floor_leg = 0.0
    elapsed = 0
    import datetime as _dt
    for i in range(1, len(eq)):
        d_prev = points[i - 1].get("date")
        d_cur = points[i].get("date")
        step = 1
        try:
            if d_prev and d_cur:
                step = max(1, (_dt.date.fromisoformat(str(d_cur))
                               - _dt.date.fromisoformat(str(d_prev))).days)
        except ValueError:
            step = 1
        floor_leg += eq[i - 1] * floor_daily * step
        elapsed += step
    if not elapsed:
        return None, "zero elapsed days"
    # carry is the residual; the producer (captured_book_attribution) ROUNDS carry_leg_usd to 4 dp
    # before carry_truth_table annualizes it — we round identically so the bps reproduces exactly
    # (this is honest rounding parity, not a fudge: the published bps is derived from the 4-dp carry).
    carry_usd = round(realized_pnl - floor_leg, 4)
    carry_return_period = carry_usd / float(initial)
    carry_apy_pct = carry_return_period * (365.0 / float(elapsed)) * 100.0
    bps = round(carry_apy_pct * 100.0, _FUNDABILITY_BPS_DP)
    return bps, "ok"


def verify_fundability(data_dir: Path) -> dict:
    """Reproduce every realized carry-above-floor bps in the published carry_truth_table.json from the
    RAW *_series.json forward tracks, and assert they match. Returns a verdict dict.

    fail-CLOSED: a missing published table, a published sleeve with no discoverable raw series, OR any
    recomputed bps that diverges from the published value (including a null-vs-number disagreement) →
    valid=False with the precise mismatches. This is the tamper-evidence: a forged fundability number
    cannot survive recomputation from the raw series."""
    table_path = data_dir / "carry_truth_table.json"
    doc, err = _read_json(table_path)
    if err is not None or not isinstance(doc, dict):
        return {"valid": False, "available": False,
                "error": f"carry_truth_table.json: {err or 'not an object'}",
                "n_checked": 0, "n_matched": 0, "mismatches": []}
    # prefer the FULL-PRECISION floor (rwa_floor_apy_pct_full) so the bps reproduces BYTE-EXACTLY;
    # fall back to the 4-dp display floor (older artifacts) where the full-precision field is absent.
    floor = doc.get("rwa_floor_apy_pct_full")
    if not isinstance(floor, (int, float)) or isinstance(floor, bool):
        floor = doc.get("rwa_floor_apy_pct")
    rows = doc.get("rows")
    if not isinstance(floor, (int, float)) or isinstance(floor, bool) or not isinstance(rows, list):
        return {"valid": False, "available": True,
                "error": "carry_truth_table.json missing rwa_floor_apy_pct/rows",
                "n_checked": 0, "n_matched": 0, "mismatches": []}

    # discover the raw series by sleeve name — the SAME dirs carry_truth_table reads from.
    raw_by_name: dict = {}
    for sub in ("rates_desk/paper", "strategy_lab_paper", "realized_ab"):
        d = data_dir / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*_series.json")):
            name = f.name[: -len("_series.json")]
            sdoc, serr = _read_json(f)
            if serr is None:
                raw_by_name[name] = sdoc

    mismatches: List[dict] = []
    n_checked = 0
    n_matched = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("sleeve")
        published = row.get("carry_above_floor_bps")
        n_checked += 1
        raw = raw_by_name.get(name)
        if raw is None:
            mismatches.append({"sleeve": name, "reason": "published row has NO raw series to reproduce from"})
            continue
        pts = _raw_series_points(raw)
        if pts is None:
            mismatches.append({"sleeve": name, "reason": "raw series unusable (no point list)"})
            continue
        recomputed, reason = _recompute_carry_bps(pts, float(floor))
        # null-vs-number tamper check: published null must reproduce as null; a number as that number.
        if published is None:
            if recomputed is not None:
                mismatches.append({"sleeve": name, "published": None, "recomputed": recomputed,
                                   "reason": "published null but raw series yields a real bps "
                                             "(INSUFFICIENT_DATA masked)"})
            else:
                n_matched += 1
            continue
        if recomputed is None:
            mismatches.append({"sleeve": name, "published": published, "recomputed": None,
                               "reason": f"published a bps but raw series is unmeasurable ({reason})"})
            continue
        # numeric compare at the published precision (both rounded to the same dp → exact equality).
        if round(float(published), _FUNDABILITY_BPS_DP) != recomputed:
            mismatches.append({"sleeve": name, "published": published, "recomputed": recomputed,
                               "reason": "bps mismatch — published value not reproducible from raw series"})
        else:
            n_matched += 1
    return {
        "valid": len(mismatches) == 0 and n_checked > 0,
        "available": True,
        "rwa_floor_apy_pct": floor,
        "n_checked": n_checked,
        "n_matched": n_matched,
        "mismatches": mismatches,
    }


# ── content-based classification (FAIL#8) ──────────────────────────────────────────────────────────
# A file is classified as WHAT IT ACTUALLY IS — by the shape of its first data row — not by its
# filename or parent dir. So a stray/misnamed ``decision_log.jsonl`` (e.g. a sleeve proof dropped at a
# tournament path, or vice-versa) can NEVER displace the real surface: it classifies to its true
# bucket from its content. Filename/parent-dir are only a LAST-RESORT hint for an empty file (no rows
# to read), where content cannot speak.

def _sniff_jsonl_kind(p: Path) -> Optional[str]:
    """Read the FIRST non-empty JSON row and return a surface key inferred from its CONTENT, or None
    if the file is empty/unreadable/unrecognized. Recognizes:
      'tournament'  — kind == TOURNAMENT_EVENT_TYPE                       (E)
      'nav_proof'   — has proof_hash + tvl_weighted_nav/liq_nav_gap_pct   (F)
      'sleeve'      — has entry_hash + sleeve_id (+ equity/apy/book cols)  (G)
      'equity_track'— has entry_hash + date + (open/close)_equity-ish     (D)
      'decision_log'— has entry_hash + a decision body (kind/underlying)   (A)
      'anchors'     — has head_hash + chain_length (no entry/proof body)   (C)
    Content beats filename: the row carries the surface's signature fields regardless of where it
    lives or what it is named."""
    try:
        with p.open("r", encoding="utf-8") as fh:
            row = None
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                row = json.loads(ln)
                break
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(row, dict):
        return None
    keys = set(row.keys())
    # (H) underwriting report section — entry_hash chain carrying a section_id + its own proof_hash,
    # whose chain kind constant is the underwriting event type. Recognized BEFORE the generic
    # entry_hash buckets so a section row never mis-classifies as a decision/sleeve chain.
    if (row.get("kind") == UNDERWRITING_EVENT_TYPE
            or ("entry_hash" in keys and "section_id" in keys and "proof_hash" in keys)):
        return "underwriting"
    # (C) anchors — head-checkpoint envelope, no per-row entry/proof body.
    if {"head_hash", "chain_length"} <= keys and "entry_hash" not in keys and "proof_hash" not in keys:
        return "anchors"
    # (F) RWA-NAV proof — exit-NAV §6 proof_hash row carrying the NAV outputs.
    if "proof_hash" in keys and ("tvl_weighted_nav" in keys or "liq_nav_gap_pct" in keys):
        return "nav_proof"
    # (E) tournament ranking — fixed kind constant in the row body.
    if row.get("kind") == TOURNAMENT_EVENT_TYPE or "rank" in keys and "strategy_id" in keys and "entry_hash" in keys:
        return "tournament"
    # (G) sleeve forward series — entry_hash chain carrying a sleeve_id.
    if "entry_hash" in keys and "sleeve_id" in keys:
        return "sleeve"
    # (D) equity track — entry_hash chain carrying an evidenced equity bar (date + equity field).
    if "entry_hash" in keys and "date" in keys and (
            "open_equity" in keys or "close_equity" in keys or "equity" in keys
            or "daily_yield" in keys or "apy" in keys):
        return "equity_track"
    # (A) rates-desk decision chain — entry_hash chain carrying a decision body.
    if "entry_hash" in keys and ("underlying" in keys or "shape" in keys
                                 or "approved" in keys or row.get("kind") in ("ENTRY", "REFUSAL")):
        return "decision_log"
    # generic entry_hash chain with no stronger signal → treat as the rates-desk decision chain.
    if "entry_hash" in keys:
        return "decision_log"
    return None


def _classify_by_name(p: Path) -> Optional[str]:
    """Last-resort filename hint (ONLY used when content cannot speak — an empty file). Mirrors the
    surface-key vocabulary of _sniff_jsonl_kind."""
    name = p.name
    parent = p.parent.name
    if name.endswith("_series_proof.jsonl"):
        return "sleeve"
    if name.endswith("nav_proof.jsonl"):
        return "nav_proof"
    if name.endswith("decision_log.jsonl"):
        return "tournament" if parent == "tournament" else "decision_log"
    if name.endswith("equity_track.jsonl"):
        return "equity_track"
    if name.endswith("anchors.jsonl"):
        return "anchors"
    if name.endswith("report_proof.jsonl"):
        return "underwriting"
    return None


def _place(kind: Optional[str], p: Path, found: dict) -> None:
    """Place a file at the resolved surface key. ``sleeve`` is a LIST (many files); others are single
    (first wins — a real surface already bound is not displaced by a later/stray file)."""
    if kind is None:
        return
    if kind == "sleeve":
        if p not in found["sleeve_proofs"]:
            found["sleeve_proofs"].append(p)
        return
    bucket = {"tournament": "tournament", "nav_proof": "nav_proof", "decision_log": "decision_log",
              "equity_track": "equity_track", "anchors": "anchors", "exit_nav": "exit_nav",
              "underwriting": "underwriting"}.get(kind)
    if bucket and found.get(bucket) is None:
        found[bucket] = p


def _classify_file(p: Path, found: dict) -> None:
    """Sort ONE file into the surface buckets by its CONTENT (FAIL#8). exit_nav.json is the lone JSON
    document (not JSONL) and is identified by its .json shape; every JSONL surface is told apart by the
    signature fields of its first row, NEVER by filename/parent-dir. A stray/misnamed file therefore
    classifies as what it ACTUALLY is and cannot displace a real surface. Filename is a fallback ONLY
    for an empty file that has no row to read."""
    name = p.name
    # exit_nav is a single JSON object (a schedule document), not a JSONL chain.
    if name.endswith(".json") and not name.endswith(".jsonl"):
        # content sniff: an exit-NAV doc has a `schedule`/`illustrative`/`portfolio` section.
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            doc = None
        if isinstance(doc, dict) and ("schedule" in doc or "illustrative" in doc
                                      or "portfolio" in doc):
            if found["exit_nav"] is None:
                found["exit_nav"] = p
        elif name.endswith("exit_nav.json") and found["exit_nav"] is None:
            found["exit_nav"] = p
        return
    # JSONL surfaces — classify by content, falling back to filename only for an empty file.
    kind = _sniff_jsonl_kind(p)
    if kind is None:
        kind = _classify_by_name(p)
    _place(kind, p, found)


def _is_sleeve_producer_dir(d: Path) -> bool:
    """True if a directory is the sleeve-proof surface's canonical producer location — a
    ``rates_desk/paper/`` dir (the only place ``sleeve_proof.write_all`` reads/writes). Used to scope
    FAIL#5 coverage so unrelated ``*_series.json`` families (strategy_lab_paper/) are not required to
    carry a sleeve proof."""
    return d.name == "paper" and d.parent.name == "rates_desk"


def _resolve_data_dir(args_paths: List[str]) -> Optional[Path]:
    """Resolve the data dir that holds carry_truth_table.json (for --check-fundability). A supplied
    directory containing it (or whose ``data/`` subdir does) wins; a supplied file → its parent chain
    is searched. Returns the dir holding carry_truth_table.json, or None if none is found."""
    candidates: List[Path] = []
    for raw in args_paths:
        p = Path(raw)
        base = p if p.is_dir() else p.parent
        candidates.append(base)
        candidates.append(base / "data")
        # walk up a few levels so ``verify_spa.py data/rates_desk/`` still finds data/.
        for anc in list(base.parents)[:4]:
            candidates.append(anc)
            candidates.append(anc / "data")
    seen: set = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        if (c / "carry_truth_table.json").is_file():
            return c
    return None


# Frozen point-in-time copies that live UNDER data/ but are NOT the live surface: the offline
# DD snapshot (data/dd_snapshot/, a checksummed daily freeze replayed explicitly via --offline)
# and DB/backup dirs. A recursive discovery must NOT adopt their (stale) decision_log/proofs as
# the canonical live chain — e.g. data/dd_snapshot/decision_log.jsonl sorts BEFORE
# data/rates_desk/decision_log.jsonl and would hand surface [A] a stale head, breaking
# --expect-head. Excluded only when they are a SUBDIR of the walked root; an explicit
# --offline target (root == the snapshot dir) has nothing matching between root and file, so it
# is still discovered.
_DISCOVERY_EXCLUDE_DIRS = frozenset({"dd_snapshot", "backups", "backup"})


def _under_frozen_copy(fp: Path, root: Path) -> bool:
    try:
        inter = fp.relative_to(root).parts[:-1]  # intermediate dirs only (drop the filename)
    except ValueError:
        return False
    return any(part in _DISCOVERY_EXCLUDE_DIRS or part.endswith(".orphaned") for part in inter)


def _resolve_inputs(args_paths: List[str]) -> dict:
    """Map the CLI paths to EVERY anchored surface AND every producer that MUST have a proof. A
    directory is walked RECURSIVELY (rglob) so a single ``verify_spa.py data/`` auto-discovers all
    surfaces wherever they live (rates_desk/, tournament/, rwa_backstop/, rates_desk/paper/). Files
    are classified by CONTENT (FAIL#8). ``sleeve_proofs`` is a LIST (one chain per sleeve); every
    other surface is a single file. ``sleeve_producers`` is the LIST of ``*_series.json`` producers we
    discovered — used to REQUIRE a matching proof (FAIL#5 coverage enforcement)."""
    found: dict = {
        "decision_log": None, "exit_nav": None, "anchors": None, "equity_track": None,
        "tournament": None, "nav_proof": None, "sleeve_proofs": [], "underwriting": None,
        # producers that MUST carry a proof (FAIL#5). Recorded for coverage enforcement in run().
        "sleeve_producers": [],
    }
    # The CANONICAL surface filenames a directory walk picks up. We discover by name (so we don't
    # adopt unrelated entry_hash chains elsewhere under data/) but CLASSIFY each by CONTENT (FAIL#8),
    # so a stray/misnamed file sitting at one of these names still lands in its TRUE bucket and cannot
    # displace the real surface. Sleeve proofs (*_series_proof.jsonl) are MANY files.
    _DISCOVER = ("decision_log.jsonl", "exit_nav.json", "anchors.jsonl", "equity_track.jsonl",
                 "nav_proof.jsonl", "report_proof.jsonl")
    for raw in args_paths:
        p = Path(raw)
        if p.is_dir():
            seen: set = set()
            for fname in _DISCOVER:
                for fp in sorted(p.rglob(fname)):
                    if fp.is_file() and fp not in seen and not _under_frozen_copy(fp, p):
                        seen.add(fp)
                        _classify_file(fp, found)
            for fp in sorted(p.rglob("*_series_proof.jsonl")):
                if fp.is_file() and fp not in seen and not _under_frozen_copy(fp, p):
                    seen.add(fp)
                    _classify_file(fp, found)
            # sleeve PRODUCERS that REQUIRE a matching proof (FAIL#5 coverage). Scoped to the
            # sleeve-proof surface's CANONICAL producer location — a ``rates_desk/paper/`` directory.
            # The requirement holds even if the proof was DELETED (an empty proof_dirs set must still
            # require coverage — that is precisely the silent-pass we fail closed on). Other
            # *_series.json families (e.g. strategy_lab_paper/, a different surface) are NOT in a
            # rates_desk/paper/ dir, so they are correctly excluded — no false coverage failure.
            for fp in sorted(p.rglob("*_series.json")):
                if (fp.is_file() and _is_sleeve_producer_dir(fp.parent)
                        and not _under_frozen_copy(fp, p)
                        and fp not in found["sleeve_producers"]):
                    found["sleeve_producers"].append(fp)
        else:
            _classify_file(p, found)
            name = p.name
            # an explicit forward-series producer → record it for coverage enforcement.
            if name.endswith("_series.json") and p not in found["sleeve_producers"]:
                found["sleeve_producers"].append(p)
            # an explicit non-canonical .jsonl that content-sniff could not place → default to the
            # rates-desk decision chain bucket (back-compat with the explicit-file usage).
            elif (name.endswith(".jsonl")
                  and _sniff_jsonl_kind(p) is None and _classify_by_name(p) is None
                  and found["decision_log"] is None):
                found["decision_log"] = p
            elif (name.endswith(".json") and not name.endswith(".jsonl")
                  and found["exit_nav"] is None and not name.endswith("_series.json")):
                found["exit_nav"] = p
    return found


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════════════════════════
# Surface-letter vocabulary for --expect-surfaces (FAIL#5). A reviewer asserts which surfaces MUST
# be present, and a missing one FAILS CLOSED (a renamed/hidden surface can no longer silently pass).
_SURFACE_LETTERS = {
    "A": "decision_log", "B": "exit_nav", "C": "anchors", "D": "equity_track",
    "E": "tournament", "F": "nav_proof", "G": "sleeve_proofs", "H": "underwriting",
}


def _sleeve_proof_for(producer: Path) -> Path:
    """The proof path a forward-series producer MUST have: ``<x>_series.json`` → ``<x>_series_proof.jsonl``
    co-located beside it."""
    stem = producer.name
    if stem.endswith("_series.json"):
        proof_name = stem[: -len(".json")] + "_proof.jsonl"
    else:  # defensive — any *.json producer maps to *_proof.jsonl
        proof_name = stem[: -len(".json")] + "_proof.jsonl"
    return producer.with_name(proof_name)


def _enforce_coverage(inputs: dict, report: dict) -> None:
    """FAIL#5 — a PRODUCER present without its matching, NON-EMPTY proof is a FAIL, never a silent
    pass. For every discovered ``*_series.json`` sleeve producer, REQUIRE a matching
    ``*_series_proof.jsonl`` that was discovered AND verifies non-empty. A truncated (0-row) proof for
    a present producer also fails (an empty proof must not certify a populated producer)."""
    sleeve_proof_paths = {Path(s["file"]) for s in (report.get("sleeves") or {}).get("per_sleeve", [])}
    # map proof path → its verified row count (0 = empty/truncated)
    proof_len = {Path(s["file"]): (s.get("length") or 0)
                 for s in (report.get("sleeves") or {}).get("per_sleeve", [])}
    for producer in inputs.get("sleeve_producers", []):
        # does the producer carry any forward points? (an empty producer needs no proof)
        try:
            doc = json.loads(producer.read_text(encoding="utf-8"))
            series = doc.get("series") if isinstance(doc, dict) else None
            n_points = len(series) if isinstance(series, list) else 0
        except (OSError, json.JSONDecodeError):
            n_points = 0
        if n_points == 0:
            continue
        expected = _sleeve_proof_for(producer)
        if expected not in sleeve_proof_paths:
            report["errors"].append(
                f"coverage: producer {producer.name} has {n_points} forward point(s) but NO matching "
                f"proof {expected.name} (missing/hidden proof → fail-CLOSED, not silent pass)")
        elif proof_len.get(expected, 0) == 0:
            report["errors"].append(
                f"coverage: producer {producer.name} has {n_points} forward point(s) but its proof "
                f"{expected.name} is EMPTY/truncated (0 verified rows → fail-CLOSED)")


def run(paths: List[str], expect_head: Optional[str] = None,
        expect_surfaces: Optional[List[str]] = None,
        check_fundability: bool = False, replay: bool = False) -> dict:
    """Run all available verifications over the resolved inputs. Returns a verdict dict. A proof is
    only checked if its file is present; at least ONE file must be present (else nothing to verify).

    Coverage (FAIL#5): a present producer (a ``*_series.json``) without its matching, non-empty proof
    FAILS. ``expect_surfaces`` (letters A–G) asserts those surfaces are present, failing closed when
    one is absent — so a renamed/hidden surface can no longer slip through as a silent exit 0.

    ``check_fundability`` (WS6): additionally reproduce every realized carry-above-floor bps in the
    published carry_truth_table.json from the RAW *_series.json tracks and assert they match — the
    "don't trust us, check us" surface for the FUNDABILITY sheet. A forged fundability number, or an
    INSUFFICIENT_DATA masked as a real bps, FAILS CLOSED."""
    inputs = _resolve_inputs(paths)

    def _file_repr(v):
        if isinstance(v, list):
            return [str(x) for x in v]
        return str(v) if v else None

    report: dict = {
        "spec_version": SPEC_VERSION,
        "canonical_json_rule": CANONICAL_JSON_RULE,
        "files": {k: _file_repr(v) for k, v in inputs.items()},
        "decision_chain": None,
        "exit_nav": None,
        "anchors": None,
        "equity_track": None,
        "tournament": None,
        "nav_proof": None,
        "sleeves": None,
        "underwriting": None,
        "fundability": None,
        "errors": [],
        "ok": False,
    }

    def _has_any(v) -> bool:
        return bool(v) if not isinstance(v, list) else len(v) > 0

    # (H) WS6 FUNDABILITY reproduction runs FIRST and independently of the proof-chain surfaces, so
    # ``--check-fundability`` works even when pointed at a dir with only the realized artifacts.
    if check_fundability:
        fdir = _resolve_data_dir(paths)
        if fdir is None:
            report["fundability"] = {"valid": False, "available": False,
                                     "error": "could not resolve a data dir from the supplied paths",
                                     "n_checked": 0, "n_matched": 0, "mismatches": []}
            report["errors"].append("fundability: could not resolve a data dir to reproduce from")
        else:
            res = verify_fundability(fdir)
            report["fundability"] = res
            if not res.get("valid"):
                if not res.get("available"):
                    report["errors"].append(f"fundability: {res.get('error')}")
                else:
                    for m in res.get("mismatches", []):
                        report["errors"].append(
                            f"fundability: sleeve {m.get('sleeve')} — {m.get('reason')}")
                    if not res.get("mismatches"):
                        report["errors"].append(
                            f"fundability: {res.get('error') or 'no checkable rows'}")

    if not any(_has_any(v) for v in inputs.values()):
        # the proof-chain surfaces are absent. If --check-fundability was requested AND succeeded,
        # that is still a valid run (the fundability reproduction is itself a complete check); else fail.
        if not check_fundability:
            report["errors"].append(
                "no recognizable public files supplied (decision_log.jsonl / exit_nav.json / "
                "anchors.jsonl / equity_track.jsonl / tournament/decision_log.jsonl / "
                "rwa_backstop/nav_proof.jsonl / *_series_proof.jsonl / underwriting/report_proof.jsonl)")
        report["ok"] = (len(report["errors"]) == 0)
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
            # (A-replay Q2-2) re-derive each verdict from its own published numbers, fail-CLOSED
            if replay:
                rep = verify_decision_replay(rows)
                report["decision_replay"] = rep
                if rep["failed"]:
                    fb = rep.get("first_bad") or {}
                    report["errors"].append(
                        f"decision_replay: {rep['failed']}/{rep['checked']} verdict(s) do not follow "
                        f"from their published inputs (first: row {fb.get('row')} {fb.get('check')})")

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

    # (D) equity track — the EVIDENCED equity / go-live track hash chain (F2)
    if inputs["equity_track"]:
        rows, err = _read_jsonl(inputs["equity_track"])
        if err is not None:
            report["errors"].append(f"equity_track: {err}")
            report["equity_track"] = {"valid": False, "broken_at": None, "head_hash": None,
                                      "length": None, "n_days": None}
        else:
            res = verify_equity_track(rows)
            report["equity_track"] = res
            if not res["valid"]:
                report["errors"].append(
                    f"equity_track: chain broken at row {res['broken_at']}")

    # (E) tournament ranking chain — output-covering + chained (WORKSTREAM 2)
    if inputs["tournament"]:
        rows, err = _read_jsonl(inputs["tournament"])
        if err is not None:
            report["errors"].append(f"tournament: {err}")
            report["tournament"] = {"valid": False, "broken_at": None, "head_hash": None,
                                    "length": None}
        else:
            res = verify_tournament_chain(rows)
            report["tournament"] = res
            if not res["valid"]:
                report["errors"].append(f"tournament: chain broken at row {res['broken_at']}")

    # (F) RWA-backstop NAV forward-record proof — exit-NAV §6 pattern, chained (WORKSTREAM 2)
    if inputs["nav_proof"]:
        rows, err = _read_jsonl(inputs["nav_proof"])
        if err is not None:
            report["errors"].append(f"nav_proof: {err}")
            report["nav_proof"] = {"valid": False, "broken_at": None, "head_hash": None,
                                   "length": None}
        else:
            res = verify_nav_proof(rows)
            report["nav_proof"] = res
            if not res["valid"]:
                report["errors"].append(f"nav_proof: chain broken at row {res['broken_at']}")

    # (G) sleeve forward-series proofs — MANY files, each its own chain (WORKSTREAM 2)
    if inputs["sleeve_proofs"]:
        per_sleeve: List[dict] = []
        all_valid = True
        for sp in inputs["sleeve_proofs"]:
            rows, err = _read_jsonl(sp)
            if err is not None:
                report["errors"].append(f"sleeve {sp.name}: {err}")
                per_sleeve.append({"file": str(sp), "valid": False, "broken_at": None,
                                   "head_hash": None, "length": None})
                all_valid = False
                continue
            res = verify_sleeve_chain(rows)
            res = {"file": str(sp), **res}
            per_sleeve.append(res)
            if not res["valid"]:
                report["errors"].append(f"sleeve {sp.name}: chain broken at row {res['broken_at']}")
                all_valid = False
        report["sleeves"] = {"valid": all_valid, "n_sleeves": len(per_sleeve),
                             "per_sleeve": per_sleeve}

    # (H) underwriting report section chain — LANE C moat (per-section proof_hash + chained + the
    # cross-section refusal-consistency property: a REFUSED market may not be underwritten capacity).
    if inputs["underwriting"]:
        rows, err = _read_jsonl(inputs["underwriting"])
        if err is not None:
            report["errors"].append(f"underwriting: {err}")
            report["underwriting"] = {"valid": False, "broken_at": None, "head_hash": None,
                                      "length": None, "refusal_consistent": None}
        else:
            res = verify_underwriting_chain(rows)
            report["underwriting"] = res
            if not res["valid"]:
                if res.get("refusal_consistent") is False:
                    report["errors"].append(
                        "underwriting: REFUSAL-CONSISTENCY broken — REFUSED market(s) "
                        f"{res.get('smuggled_markets')} appear as underwritten capacity")
                else:
                    report["errors"].append(
                        f"underwriting: chain broken at section {res['broken_at']}")

    # FAIL#5 — coverage enforcement: a present producer must carry a verified, non-empty proof.
    _enforce_coverage(inputs, report)

    # FAIL#6 — honest advisory labeling of degenerate / placeholder anchored numbers. The proof
    # proves "we PUBLISHED X", not "X is real" — surface that caveat where it applies (NOT a failure,
    # but a loud advisory flag in the verdict so gravitas is never mistaken for substance).
    report["advisories"] = _collect_advisories(inputs)

    # --expect-head assertion (the published head a reviewer was told to expect)
    if expect_head is not None:
        if decision_head != expect_head:
            report["errors"].append(
                f"head mismatch: expected {expect_head}, reproduced {decision_head}")
        report["expected_head"] = expect_head

    # --expect-surfaces assertion (FAIL#5): named surfaces MUST be present, else fail-CLOSED.
    if expect_surfaces:
        present = {
            "A": bool(inputs["decision_log"]), "B": bool(inputs["exit_nav"]),
            "C": bool(inputs["anchors"]), "D": bool(inputs["equity_track"]),
            "E": bool(inputs["tournament"]), "F": bool(inputs["nav_proof"]),
            "G": bool(inputs["sleeve_proofs"]), "H": bool(inputs["underwriting"]),
        }
        report["expected_surfaces"] = list(expect_surfaces)
        for letter in expect_surfaces:
            key = _SURFACE_LETTERS.get(letter)
            if key is None:
                report["errors"].append(f"--expect-surfaces: unknown surface letter {letter!r} "
                                        f"(valid: {','.join(sorted(_SURFACE_LETTERS))})")
            elif not present.get(letter):
                report["errors"].append(
                    f"--expect-surfaces: required surface [{letter}] ({key}) is ABSENT — fail-CLOSED "
                    "(a missing/renamed/hidden surface must not pass silently)")

    report["ok"] = (len(report["errors"]) == 0)
    return report


# ── FAIL#6 advisory labeling — degenerate Sharpe / placeholder par-NAV are flagged, not hidden ──────
SHARPE_SANE_CEILING = 10.0   # |Sharpe| above this is locked-vol / mock degenerate, not a real RAR.


def _collect_advisories(inputs: dict) -> List[dict]:
    """Scan the tournament + RWA-NAV surfaces for anchored numbers that are degenerate or placeholder,
    and emit honest advisory labels. The hash proves these values were PUBLISHED; it does NOT prove
    they are real. We surface that explicitly so a reviewer never mistakes an anchored placeholder for
    a measured result. Returns a list of {surface, level, label, detail}. fail-soft (never raises)."""
    out: List[dict] = []

    # (E) tournament — any |Sharpe| above the sane ceiling is degenerate / locked-vol, NOT a real RAR.
    if inputs.get("tournament"):
        rows, err = _read_jsonl(inputs["tournament"])
        if err is None and rows:
            worst = None
            n_deg = 0
            for r in rows:
                if not isinstance(r, dict):
                    continue
                s = r.get("sharpe")
                if isinstance(s, (int, float)) and not isinstance(s, bool) and abs(s) > SHARPE_SANE_CEILING:
                    n_deg += 1
                    if worst is None or abs(s) > abs(worst):
                        worst = s
            if n_deg:
                out.append({
                    "surface": "tournament",
                    "level": "ADVISORY / MOCK-DATA",
                    "label": "degenerate Sharpe (locked-vol, NOT a real risk-adjusted return)",
                    "detail": f"{n_deg} ranking row(s) carry |Sharpe| > {SHARPE_SANE_CEILING:g} "
                              f"(worst {worst:.2f}). These are mock/locked-vol artifacts. The chain "
                              "proves the ranking was PUBLISHED, not that the Sharpe is investable.",
                })

    # (F) RWA-NAV — any forward point with onchain_4626_count == 0 is a MARKETING PAR estimate, not a
    # measured liquidation NAV; the liq_nav_gap_pct=100 sentinel means "no on-chain NAV measured".
    if inputs.get("nav_proof"):
        rows, err = _read_jsonl(inputs["nav_proof"])
        if err is None and rows:
            n_par = sum(1 for r in rows if isinstance(r, dict)
                        and _int_or_none(r.get("onchain_4626_count")) == 0)
            if n_par:
                out.append({
                    "surface": "nav_proof",
                    "level": "MEASUREMENT-ONLY / MARKETING-PAR",
                    "label": "par-NAV estimate (NOT a measured liquidation NAV)",
                    "detail": f"{n_par} forward point(s) have onchain_4626_count == 0 → "
                              "tvl_weighted_nav is the $1.00 MARKETING par, and liq_nav_gap_pct=100 is "
                              "a sentinel (no on-chain ERC-4626 NAV measured). Advisory/measurement-only: "
                              "the chain proves the point was PUBLISHED, not that par equals executable NAV.",
                })
    return out


def _int_or_none(v):
    try:
        if isinstance(v, bool):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _print_human(report: dict) -> None:
    print("=" * 78)
    print("SPA STANDALONE PROOF VERIFIER  (zero-dependency · no spa_core · per PROOF_CHAIN_SPEC)")
    print("=" * 78)
    print(f"spec_version       : {report['spec_version']}")
    print(f"canonical_json_rule: {report['canonical_json_rule']}")
    for k, v in report["files"].items():
        if isinstance(v, list):
            disp = (", ".join(v) if v else "(not supplied)")
        else:
            disp = (v or "(not supplied)")
        print(f"  {k:14s}: {disp}")
    print("-" * 78)

    dc = report["decision_chain"]
    if dc is not None:
        print(f"[A] decision chain : valid={dc.get('valid')}  length={dc.get('length')}  "
              f"broken_at={dc.get('broken_at')}")
        print(f"    head_hash      : {dc.get('head_hash')}")

    rp = report.get("decision_replay")
    if rp is not None:
        iv = rp.get("invariants", {})
        print(f"[A-replay] verdict re-derivation: {rp.get('passed')}/{rp.get('checked')} verdicts follow "
              f"from their own published inputs  (failed={rp.get('failed')})")
        print(f"    invariants     : identity={iv.get('d1_identity')}  nonneg-haircut={iv.get('d2_nonneg')}  "
              f"approved→edge>0={iv.get('d3_approve_edge')}  refused→reason={iv.get('d4_refuse_reason')}")
        if rp.get("first_bad"):
            print(f"    first_bad      : {rp['first_bad']}")

    si = report.get("snapshot_integrity")
    if si is not None:
        print(f"[offline] snapshot integrity: {si.get('matched')}/{si.get('checked')} pinned files "
              f"byte-identical to SNAPSHOT_MANIFEST.json  (mismatched={si.get('mismatched')}, "
              f"manifest_present={si.get('manifest_present')})")
        if si.get("expected_decision_head"):
            print(f"    pinned head    : {si['expected_decision_head']}  surfaces={si.get('expected_surfaces')}")
        if si.get("first_bad"):
            print(f"    first_bad      : {si['first_bad']}")

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

    et = report["equity_track"]
    if et is not None:
        print(f"[D] equity track   : valid={et.get('valid')}  evidenced_days={et.get('n_days')}  "
              f"broken_at={et.get('broken_at')}  "
              f"window={et.get('first_date')}..{et.get('last_date')}")
        print(f"    head_hash      : {et.get('head_hash')}")

    tn = report["tournament"]
    if tn is not None:
        print(f"[E] tournament     : valid={tn.get('valid')}  rows={tn.get('length')}  "
              f"broken_at={tn.get('broken_at')}")
        print(f"    head_hash      : {tn.get('head_hash')}")

    nv = report["nav_proof"]
    if nv is not None:
        print(f"[F] rwa nav proof  : valid={nv.get('valid')}  forward_points={nv.get('length')}  "
              f"broken_at={nv.get('broken_at')}")
        print(f"    head_hash      : {nv.get('head_hash')}")

    sl = report["sleeves"]
    if sl is not None:
        print(f"[G] sleeve proofs  : valid={sl.get('valid')}  n_sleeves={sl.get('n_sleeves')}")
        for s in sl.get("per_sleeve", []):
            print(f"    {Path(s['file']).name:42s}: valid={s.get('valid')}  "
                  f"rows={s.get('length')}  broken_at={s.get('broken_at')}  head={s.get('head_hash')}")

    uw = report["underwriting"]
    if uw is not None:
        print(f"[H] underwriting   : valid={uw.get('valid')}  sections={uw.get('length')}  "
              f"broken_at={uw.get('broken_at')}  refusal_consistent={uw.get('refusal_consistent')}  "
              f"published={uw.get('published')}")
        print(f"    head_hash      : {uw.get('head_hash')}")
        if uw.get("smuggled_markets"):
            print(f"    ✗ refused markets smuggled into capacity: {uw['smuggled_markets']}")

    fd = report.get("fundability")
    if fd is not None:
        print("-" * 78)
        print(f"[fundability]      : valid={fd.get('valid')}  reproduced="
              f"{fd.get('n_matched')}/{fd.get('n_checked')} sleeve carry-bps from RAW series"
              + (f"  floor={fd.get('rwa_floor_apy_pct')}%" if fd.get("rwa_floor_apy_pct") is not None else ""))
        if fd.get("error"):
            print(f"    error          : {fd['error']}")
        for m in fd.get("mismatches", []):
            print(f"    ✗ {m.get('sleeve')}: published={m.get('published')} "
                  f"recomputed={m.get('recomputed')} — {m.get('reason')}")

    if "expected_head" in report:
        ok = report["decision_chain"] and report["decision_chain"].get("head_hash") == report["expected_head"]
        print(f"[--expect-head]    : {'MATCH' if ok else 'MISMATCH'}  ({report['expected_head']})")

    if "expected_surfaces" in report:
        print(f"[--expect-surfaces]: required {','.join(report['expected_surfaces'])}")

    adv = report.get("advisories") or []
    if adv:
        print("-" * 78)
        print("ADVISORIES (the proof proves we PUBLISHED these — NOT that they are real):")
        for a in adv:
            print(f"  ⚠ [{a['surface']}] {a['level']}: {a['label']}")
            print(f"      {a['detail']}")

    print("-" * 78)
    if report["errors"]:
        print("ERRORS:")
        for e in report["errors"]:
            print(f"  ✗ {e}")
    print(f"VERDICT: {'OK — everything reproduces' if report['ok'] else 'FAILED'}")
    print("=" * 78)



def check_ots_anchors(paths):
    """Surface [I] — EXTERNAL timestamp anchoring (OpenTimestamps/Bitcoin), additive & NON-FATAL.

    Zero-dep here: this verifier confirms only the LINKAGE it can (each stamp's `<head>.head` digest
    file re-creates EXACTLY its head_hash) and emits the precise ``ots verify`` command a skeptic runs
    with their OWN opentimestamps client to confirm the Bitcoin proof. OTS proofs begin at the adoption
    date; earlier history is not Bitcoin-anchored (honest scope). Absence is fine (not an error)."""
    found = None
    for p in paths:
        base = Path(p)
        base = base if base.is_dir() else base.parent
        cur = base
        for _ in range(7):
            c = cur / "proofs" / "ots" / "ots_anchors.jsonl"
            if c.exists():
                found = c; break
            if (cur / "ots_anchors.jsonl").exists():
                found = cur / "ots_anchors.jsonl"; break
            cur = cur.parent
        if found:
            break
    if not found:
        return {"present": False}
    entries = []
    for line in found.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    stamps = [e for e in entries if e.get("event") == "ots_stamp"]
    otsdir = found.parent
    ok = checked = 0
    cmds = []
    for e in stamps:
        hh = e.get("head_hash") or ""
        checked += 1
        df = otsdir / f"{hh}.head"
        if df.exists() and df.read_text().strip() == hh:
            ok += 1
        of = otsdir / f"{hh}.head.ots"
        if of.exists():
            cmds.append(f"ots verify {of}")
    confirmed = sum(1 for e in entries
                    if e.get("event") == "ots_upgrade" and e.get("status") == "confirmed")
    return {"present": True, "ledger": str(found), "stamps": len(stamps),
            "linkage_ok": ok, "linkage_checked": checked, "confirmed": confirmed,
            "verify_cmds": cmds[:5]}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Standalone, zero-dependency verifier for SPA's public proof artifacts.")
    ap.add_argument("paths", nargs="+",
                    help="a directory (auto-discovers the 3 files) or explicit file paths")
    ap.add_argument("--expect-head", default=None,
                    help="assert the reproduced DECISION-CHAIN head_hash (surface A) equals this hex "
                         "digest. NOTE: this is the chain HEAD, NOT the verifier script's own SHA-256.")
    ap.add_argument("--expect-surfaces", default=None,
                    help="comma-separated surface letters (A=decision_log B=exit_nav C=anchors "
                         "D=equity_track E=tournament F=nav_proof G=sleeve H=underwriting) that MUST "
                         "be present; a missing one fails CLOSED (so a renamed/hidden surface can't "
                         "pass silently)")
    ap.add_argument("--json", action="store_true", help="emit the machine-readable verdict as JSON")
    ap.add_argument("--check-fundability", action="store_true",
                    help="ALSO reproduce every realized carry-above-floor bps in carry_truth_table.json "
                         "from the RAW *_series.json tracks and assert they match (the WS6 FUNDABILITY "
                         "'don't trust us, check us' surface). A forged fundability number, or an "
                         "INSUFFICIENT_DATA masked as a real bps, fails CLOSED.")
    ap.add_argument("--replay", action="store_true",
                    help="ALSO re-DERIVE each rates-desk verdict from its OWN published numbers (not a "
                         "re-hash): fair_yield==baseline−total_haircut, non-negative haircuts, approved⇒"
                         "net_edge>0 (refusal-first), refused⇒reason. A stored verdict that does not "
                         "follow from its published inputs fails CLOSED (the measurement-moat replay proof).")
    ap.add_argument("--offline", action="store_true",
                    help="OFFLINE self-contained mode for a FROZEN DD snapshot dir: read its "
                         "SNAPSHOT_MANIFEST.json, assert every pinned file is byte-identical to its "
                         "recorded sha256+size, and AUTO-APPLY the manifest's expected head/surfaces. "
                         "A cloned snapshot reproduces with NO live API and NO trust in us; any "
                         "missing/tampered file fails CLOSED.")
    args = ap.parse_args(argv)

    expect_surfaces = None
    if args.expect_surfaces:
        expect_surfaces = [s.strip().upper() for s in args.expect_surfaces.split(",") if s.strip()]

    # (Q2-10) --offline: verify the frozen snapshot's pinned checksums + inherit its expected head/surfaces
    integ = None
    if args.offline:
        snap = Path(args.paths[0])
        snap_dir = snap if snap.is_dir() else snap.parent
        integ = verify_snapshot_manifest(snap_dir)
        if args.expect_head is None and integ.get("expected_decision_head"):
            args.expect_head = integ["expected_decision_head"]
        if expect_surfaces is None and integ.get("expected_surfaces"):
            expect_surfaces = [str(s).strip().upper() for s in integ["expected_surfaces"]]

    report = run(args.paths, expect_head=args.expect_head, expect_surfaces=expect_surfaces,
                 check_fundability=args.check_fundability, replay=args.replay)

    if integ is not None:
        report["snapshot_integrity"] = integ
        if (not integ["manifest_present"]) or integ["mismatched"] > 0 or integ["checked"] == 0:
            fb = integ.get("first_bad") or {}
            report["errors"].append(
                f"snapshot_integrity: {integ['mismatched']}/{integ['checked']} pinned file(s) do not "
                f"match the manifest (first: {fb.get('file')} — {fb.get('reason')})"
                if integ["manifest_present"] else
                f"snapshot_integrity: no usable SNAPSHOT_MANIFEST.json ({fb.get('reason')})")
            report["ok"] = (len(report["errors"]) == 0)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
        _ots = check_ots_anchors(args.paths)
        if _ots.get("present"):
            print("-" * 78)
            print(f"[I] external timestamp anchoring (OpenTimestamps/Bitcoin): stamps={_ots['stamps']}  "
                  f"digest-linkage_ok={_ots['linkage_ok']}/{_ots['linkage_checked']}  "
                  f"bitcoin_confirmed={_ots['confirmed']}")
            print("    Linkage (digest re-creates the chain head) is checked zero-dep HERE; the BITCOIN")
            print("    proof you check with YOUR OWN client (don't trust us) — install opentimestamps-client:")
            for _c in _ots["verify_cmds"]:
                print(f"      {_c}")
            print("    Honest scope: OTS proofs start at the adoption date; earlier history isn't Bitcoin-anchored.")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
