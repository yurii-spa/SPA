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
    python3 verify_spa.py data/rates_desk/                # a directory: auto-discovers the files
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


def _classify_file(p: Path, found: dict) -> None:
    """Sort ONE file into the surface buckets by its filename. The tournament ranking chain and the
    rates-desk decision chain are BOTH named decision_log.jsonl — they are told apart by their parent
    dir (a tournament/ parent → tournament bucket). Sleeve proofs (*_series_proof.jsonl) are a LIST
    (many files)."""
    name = p.name
    parent = p.parent.name
    if name.endswith("_series_proof.jsonl"):
        if p not in found["sleeve_proofs"]:
            found["sleeve_proofs"].append(p)
    elif name == "nav_proof.jsonl" or name.endswith("nav_proof.jsonl"):
        if found["nav_proof"] is None:
            found["nav_proof"] = p
    elif name == "decision_log.jsonl" or name.endswith("decision_log.jsonl"):
        # tournament/decision_log.jsonl vs rates-desk decision_log.jsonl — disambiguate by parent dir
        if parent == "tournament":
            if found["tournament"] is None:
                found["tournament"] = p
        elif found["decision_log"] is None:
            found["decision_log"] = p
        elif found["tournament"] is None:
            found["tournament"] = p
    elif name == "equity_track.jsonl" or name.endswith("equity_track.jsonl"):
        if found["equity_track"] is None:
            found["equity_track"] = p
    elif name == "anchors.jsonl" or name.endswith("anchors.jsonl"):
        if found["anchors"] is None:
            found["anchors"] = p
    elif name == "exit_nav.json" or name.endswith("exit_nav.json"):
        if found["exit_nav"] is None:
            found["exit_nav"] = p


def _resolve_inputs(args_paths: List[str]) -> dict:
    """Map the CLI paths to EVERY anchored surface. A directory is walked RECURSIVELY (rglob) so a
    single ``verify_spa.py data/`` auto-discovers all surfaces wherever they live (rates_desk/,
    tournament/, rwa_backstop/, rates_desk/paper/). Explicit files are matched by name. ``sleeve_proofs``
    is a LIST (one chain per sleeve); every other surface is a single file."""
    found: dict = {
        "decision_log": None, "exit_nav": None, "anchors": None, "equity_track": None,
        "tournament": None, "nav_proof": None, "sleeve_proofs": [],
    }
    # The filenames the recursive walk picks up (so we don't scan unrelated JSON).
    _DISCOVER = ("decision_log.jsonl", "exit_nav.json", "anchors.jsonl", "equity_track.jsonl",
                 "nav_proof.jsonl")
    for raw in args_paths:
        p = Path(raw)
        if p.is_dir():
            seen: set = set()
            for fname in _DISCOVER:
                for fp in sorted(p.rglob(fname)):
                    if fp.is_file() and fp not in seen:
                        seen.add(fp)
                        _classify_file(fp, found)
            for fp in sorted(p.rglob("*_series_proof.jsonl")):
                if fp.is_file():
                    _classify_file(fp, found)
        else:
            _classify_file(p, found)
            # an explicit non-canonical .jsonl/.json falls back to the rates-desk default buckets.
            name = p.name
            if (name.endswith(".jsonl") and not any(
                    name.endswith(s) for s in ("decision_log.jsonl", "anchors.jsonl",
                                               "equity_track.jsonl", "nav_proof.jsonl",
                                               "_series_proof.jsonl"))):
                if found["decision_log"] is None:
                    found["decision_log"] = p
            elif name.endswith(".json") and not name.endswith("exit_nav.json"):
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
        "errors": [],
        "ok": False,
    }

    def _has_any(v) -> bool:
        return bool(v) if not isinstance(v, list) else len(v) > 0

    if not any(_has_any(v) for v in inputs.values()):
        report["errors"].append(
            "no recognizable public files supplied (decision_log.jsonl / exit_nav.json / "
            "anchors.jsonl / equity_track.jsonl / tournament/decision_log.jsonl / "
            "rwa_backstop/nav_proof.jsonl / *_series_proof.jsonl)")
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
