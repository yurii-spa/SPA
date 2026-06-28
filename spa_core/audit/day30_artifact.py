#!/usr/bin/env python3
# LLM_FORBIDDEN
"""spa_core/audit/day30_artifact.py — the AUTO, VERIFIABLE, HASH-ANCHORED day-30
readiness artifact (Workstream 5.1, "Cutover-Bulletproof").

WHY THIS EXISTS
===============
The go-live track approaches 30 evidenced days (anchor 2026-06-22, target ~2026-07-21).
At day 30 a funder/reviewer needs ONE artifact that says — provably, from the live track,
with nothing fabricated along the way — "the record is N/30 evidenced, here is the realized
risk-adjusted picture, here is the validated edge, here are the honest caveats, here is the
go-live verdict." This module IS that artifact, produced AUTOMATICALLY from the current
evidenced track and HASH-ANCHORED so a reviewer can re-derive the exact same proof.

It is NOT a new measurement engine — it is a deterministic COMPOSITION of the existing,
already-hardened pieces (each cited so the artifact never re-invents a number):

  * ``track_evidence``       — the single source of truth for what "evidenced" means
                               (evidenced_dates / count_evidenced / evidenced_risk_metrics).
                               Backfill / reconstructed / warmup / FUTURE-dated bars can NEVER
                               count: the day-count is exactly the honest go-live count.
  * ``equity_proof_chain``   — the tamper-evident single-genesis hash chain over the EVIDENCED
                               equity bars (data/rates_desk/equity_track.jsonl). Its head hash
                               is the cryptographic fingerprint of the entire evidenced record.
  * ``forward_analytics``    — the live risk-adjusted scorecard on the accruing forward sleeves
                               (THIN/UNKNOWN below the credible-N, never a fabricated Sharpe).
  * ``golive_status.json``   — the 29-criteria gate result (passed/total, time-gated blockers).
  * ``hash_chain``           — canonical-JSON SHA-256 (the SAME recipe the rest of the proof
                               chain uses) to anchor the artifact itself with a ``proof_hash``.

VERIFIABILITY (the property the verification pins)
==================================================
For a FIXED track the artifact is byte-deterministic: ``build_artifact(..., now_iso=<fixed>)``
produces an identical document, and ``proof_hash`` is the SHA-256 over the artifact's content
fields (everything EXCEPT ``proof_hash`` and the wall-clock ``generated_at``). Re-running the
generator over the same equity file yields the same ``proof_hash``; mutating ANY evidenced bar
(forge an equity number, insert a backfilled day, back-date / future-date a bar, reorder, drop)
changes the evidenced series → changes the equity-chain head → changes ``proof_hash``. The
artifact therefore cannot be silently edited, and an inflated readiness is impossible because
the day-count flows straight from ``track_evidence`` (a backfilled bar is excluded BY RULE).

HONEST AT 7/30 TODAY, BY DESIGN
================================
Dry-run against the CURRENT track today (7 evidenced days) yields verdict NOT_READY with the
two time-gated blockers and THIN risk-adjusted metrics — there is nothing to fabricate. Only
once the evidenced count reaches MIN_TRACK_DAYS (30) AND the risk metrics leave THIN does the
verdict become READY_FOR_REVIEW. The artifact never claims more than the track evidences.

Scope / safety
==============
* Stdlib only. Deterministic (fixed inputs → fixed bytes). Fail-CLOSED. Atomic write.
* Read-only over data/equity_curve_daily.json + the scorecard/golive artifacts; it NEVER
  mutates the live track and moves no capital (advisory / measurement only).
* No LLM anywhere in the readiness path.

CLI::

    python3 -m spa_core.audit.day30_artifact            # print to stdout (read-only)
    python3 -m spa_core.audit.day30_artifact --write    # write data/day30_artifact.json (atomic)
    python3 -m spa_core.audit.day30_artifact --verify    # re-derive proof_hash, report match
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.utils.atomic import atomic_load, atomic_save
from spa_core.paper_trading import track_evidence as te
from spa_core.audit import equity_proof_chain as epc

log_name = "spa.audit.day30_artifact"

_REPO_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
DATA_DIR = _REPO_ROOT / "data"
EQUITY_FILE = DATA_DIR / "equity_curve_daily.json"
GOLIVE_FILE = DATA_DIR / "golive_status.json"
FORWARD_ANALYTICS_FILE = DATA_DIR / "forward_analytics.json"
ARTIFACT_FILE = DATA_DIR / "day30_artifact.json"

# The day-30 target depth. MUST agree with golive_checker.MIN_TRACK_DAYS / track_evidence.
MIN_TRACK_DAYS = 30

# Fixed schema/recipe version — bump on any change to the hash-covered fields so a reviewer
# can pin which recipe a stored proof_hash was produced under.
ARTIFACT_VERSION = "day30-v1"

# Verdict vocabulary (deterministic; assigned purely from the evidenced count + the gate).
VERDICT_NOT_READY = "NOT_READY"            # < MIN_TRACK_DAYS evidenced days (time-gated wait)
VERDICT_READY_FOR_REVIEW = "READY_FOR_REVIEW"  # >= MIN_TRACK_DAYS evidenced AND gate passes
VERDICT_HELD_GATE = "HELD_BY_GATE"         # >= MIN_TRACK_DAYS evidenced but a non-time blocker
VERDICT_UNKNOWN = "UNKNOWN"                 # no usable track (fail-CLOSED)

# Fields that are NOT part of the deterministic content (excluded from the proof hash).
_NON_CONTENT_KEYS = ("proof_hash", "generated_at")


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _canonical(obj: Any) -> str:
    """Canonical JSON — the SAME recipe equity_proof_chain / hash_chain use (PROOF_CHAIN_SPEC §2)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_proof_hash(artifact: Dict[str, Any]) -> str:
    """SHA-256 over the canonical JSON of the artifact's CONTENT fields.

    Excludes ``proof_hash`` (self-reference) and ``generated_at`` (the only wall-clock field) so
    the hash is a stable fingerprint of the evidenced record + verdict, not of the run instant.
    Deterministic: identical content → identical hash, across processes and Python runs.
    """
    content = {k: v for k, v in artifact.items() if k not in _NON_CONTENT_KEYS}
    return hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()


# ──────────────────────────────────────────────────────────────────────────────
# evidenced-track section (reuses track_evidence — the single source of truth)
# ──────────────────────────────────────────────────────────────────────────────
def _load_daily(equity_path: Path) -> Optional[List[dict]]:
    """Read the daily bar list from an equity_curve_daily.json, or None (fail-CLOSED)."""
    try:
        doc = atomic_load(str(equity_path), default=None)
    except Exception:  # noqa: BLE001 — a corrupt file is an UNKNOWN track, never a crash
        doc = None
    if not isinstance(doc, dict):
        return None
    daily = doc.get("daily")
    return daily if isinstance(daily, list) else None


def evidenced_section(
    daily: Optional[List[dict]],
    *,
    today: Optional[datetime.date] = None,
    risk_free_rate: float = 0.0,
) -> Dict[str, Any]:
    """The honest evidenced-track block: count, anchor, dates, realized return/DD, risk metrics.

    Every number flows through ``track_evidence`` so a backfilled/reconstructed/future-dated bar
    can never inflate it. ``today`` (defaults to live UTC) pins the future-date guard so a stray
    future bar cannot over-count. Risk metrics are THIN (None) until MIN evidenced returns accrue.
    """
    if daily is None:
        return {
            "evidenced_days": 0,
            "min_track_days": MIN_TRACK_DAYS,
            "remaining_days": MIN_TRACK_DAYS,
            "evidenced_anchor": None,
            "evidenced_dates": [],
            "realized_total_return_pct": None,
            "realized_max_drawdown_pct": None,
            "risk_metrics": {"status": "UNKNOWN", "sharpe": None, "sortino": None,
                             "n_returns": 0, "min_returns": te.MIN_EVIDENCED_RETURNS_FOR_SHARPE},
            "track_available": False,
        }

    today = today if today is not None else datetime.datetime.now(datetime.timezone.utc).date()
    dates = te.evidenced_dates(daily, today=today)
    n = len(dates)
    risk = te.evidenced_risk_metrics(daily, risk_free_rate=risk_free_rate)
    return {
        "evidenced_days": n,
        "min_track_days": MIN_TRACK_DAYS,
        "remaining_days": max(0, MIN_TRACK_DAYS - n),
        "evidenced_anchor": dates[0] if dates else None,
        "evidenced_last": dates[-1] if dates else None,
        "evidenced_dates": dates,
        "realized_total_return_pct": te.real_total_return_pct(daily),
        "realized_max_drawdown_pct": te.real_max_drawdown_pct(daily),
        "risk_metrics": risk,           # {sharpe, sortino, n_returns, min_returns, status}
        "track_available": True,
    }


# ──────────────────────────────────────────────────────────────────────────────
# go-live gate section (read VERBATIM from golive_status.json — never recomputed here)
# ──────────────────────────────────────────────────────────────────────────────
def golive_section(golive: Optional[dict]) -> Dict[str, Any]:
    """Summarize the 29-criteria gate from golive_status.json (read-only).

    Fail-CLOSED: a missing/unusable gate file → available=False, ready=None (never a fabricated
    pass). Splits blockers into the two known time-gated ones vs any OTHER (non-time) blocker so
    the verdict can distinguish "just wait for days" from "something must be fixed".
    """
    if not isinstance(golive, dict):
        return {"available": False, "ready": None, "passed": None, "total": None,
                "blockers": [], "time_gated_blockers": [], "other_blockers": []}
    blockers = golive.get("blockers") or []
    blockers = [str(b) for b in blockers if b is not None]
    # The two known TIME-GATED blockers are pure day-count waits (nothing to fix in code).
    time_gated = [b for b in blockers
                  if ("gap_monitor_30d" in b) or ("min_track_days_30" in b)]
    other = [b for b in blockers if b not in time_gated]
    return {
        "available": True,
        "ready": bool(golive.get("ready")),
        "passed": golive.get("passed"),
        "total": golive.get("total"),
        "real_track_days": golive.get("real_track_days"),
        "target_date": golive.get("target_date"),
        "evidenced_anchor": golive.get("evidenced_anchor"),
        "blockers": blockers,
        "time_gated_blockers": time_gated,
        "other_blockers": other,
    }


# ──────────────────────────────────────────────────────────────────────────────
# forward-analytics section (the validated edge — read VERBATIM, fail-CLOSED)
# ──────────────────────────────────────────────────────────────────────────────
def edge_section(fa: Optional[dict]) -> Dict[str, Any]:
    """The validated-edge block from the forward_analytics scorecard (read-only).

    The forward analytics module already labels each track THIN/UNKNOWN/BEATS_FLOOR honestly; we
    surface the rollup + the carry-book stress survival, never a re-derived number. Missing
    scorecard → available=False (no fabricated edge)."""
    if not isinstance(fa, dict) or not fa.get("tracks"):
        return {"available": False, "n_tracks": None, "n_beats_floor": None,
                "n_thin_track": None, "n_unknown": None, "n_dsr_active": None,
                "rwa_floor_apy_pct": None, "carry_book_survives_all_stress": None}
    overlay = fa.get("carry_book_stress_overlay")
    survives = overlay.get("survives_all") if isinstance(overlay, dict) else None
    # Per-track honest one-line verdicts (name + verdict + realized return) — no recompute.
    tracks = []
    for t in (fa.get("tracks") or []):
        if not isinstance(t, dict):
            continue
        tracks.append({
            "name": t.get("name"),
            "n_points": t.get("n_points"),
            "verdict": t.get("verdict"),
            "ann_return_pct": t.get("ann_return_pct"),
            "excess_vs_floor_pct": t.get("excess_vs_floor_pct"),
            "sharpe": t.get("sharpe"),
        })
    return {
        "available": True,
        "n_tracks": fa.get("n_tracks"),
        "n_beats_floor": fa.get("n_beats_floor"),
        "n_thin_track": fa.get("n_thin_track"),
        "n_unknown": fa.get("n_unknown"),
        "n_dsr_active": fa.get("n_dsr_active"),
        "rwa_floor_apy_pct": fa.get("rwa_floor_apy_pct"),
        "carry_book_survives_all_stress": survives,
        "tracks": tracks,
    }


# ──────────────────────────────────────────────────────────────────────────────
# honest caveats — deterministic, evidence-aware (NEVER hidden)
# ──────────────────────────────────────────────────────────────────────────────
def honest_caveats(ev: Dict[str, Any], edge: Dict[str, Any]) -> List[str]:
    """A deterministic list of the load-bearing honest caveats, tailored to the current depth.

    These are the credibility — a funder trusts the day-30 number precisely because the artifact
    states, up front, exactly what it does and does not prove."""
    caveats: List[str] = [
        "Paper/advisory track on a virtual $100k base — $0 real capital is deployed.",
        "Every number is sourced live from the evidenced record; a missing source reads UNKNOWN, "
        "never a fabricated value.",
        "The evidenced day-count excludes backfill / reconstructed / future-dated bars BY RULE "
        "(track_evidence) — a padded day can never inflate readiness.",
    ]
    n = ev.get("evidenced_days", 0)
    risk = ev.get("risk_metrics") or {}
    if n < MIN_TRACK_DAYS:
        caveats.append(
            f"The track is THIN: {n}/{MIN_TRACK_DAYS} evidenced days — "
            f"{max(0, MIN_TRACK_DAYS - n)} more must accrue before the day-30 verdict can read "
            "READY_FOR_REVIEW. Nothing here is fixable in code; it is a time-gated wait."
        )
    if (risk.get("status") != "OK"):
        caveats.append(
            "Risk-adjusted ratios (Sharpe/Sortino) read THIN/UNKNOWN until "
            f"{risk.get('min_returns', te.MIN_EVIDENCED_RETURNS_FOR_SHARPE)} evidenced daily "
            "returns accrue — a small-sample or locked-volatility ratio is a degenerate artifact, "
            "so it is refused rather than fabricated."
        )
    caveats.append(
        "The carry edge is capacity-bound (a single rates book does NOT clear $10M); the moat is "
        "scale across many gated books plus the trust earned by a transparent refusal engine — "
        "off-code (custody / audit / legal / relationships) gates the business, not more APY."
    )
    return caveats


# ──────────────────────────────────────────────────────────────────────────────
# verdict — deterministic from the evidenced count + the gate + the risk status
# ──────────────────────────────────────────────────────────────────────────────
def compute_verdict(ev: Dict[str, Any], gate: Dict[str, Any]) -> Dict[str, Any]:
    """Assign the day-30 readiness verdict — purely deterministic, fail-CLOSED.

    Rules (no LLM, no whim):
      * no usable track            → UNKNOWN.
      * evidenced < MIN_TRACK_DAYS → NOT_READY (the time-gated wait; honest at 7/30 today).
      * evidenced >= MIN_TRACK_DAYS:
          - gate ready AND risk metrics OK            → READY_FOR_REVIEW.
          - a NON-time-gated blocker remains, OR the
            risk metrics are still THIN/UNKNOWN       → HELD_BY_GATE (something real still pends).
    The verdict NEVER claims READY on a thin record or an un-passed gate.
    """
    if not ev.get("track_available"):
        return {"verdict": VERDICT_UNKNOWN,
                "reason": "no usable evidenced track (equity_curve_daily.json missing/corrupt)"}

    n = int(ev.get("evidenced_days", 0))
    if n < MIN_TRACK_DAYS:
        rem = max(0, MIN_TRACK_DAYS - n)
        return {"verdict": VERDICT_NOT_READY,
                "reason": (f"{n}/{MIN_TRACK_DAYS} evidenced days — {rem} more needed (time-gated "
                           "wait; nothing to fix in code)")}

    # Reached the depth. The gate + the risk status decide READY vs HELD.
    risk_ok = (ev.get("risk_metrics") or {}).get("status") == "OK"
    other_blockers = gate.get("other_blockers") or []
    gate_ready = bool(gate.get("ready"))

    if gate_ready and risk_ok and not other_blockers:
        return {"verdict": VERDICT_READY_FOR_REVIEW,
                "reason": (f"{n}/{MIN_TRACK_DAYS} evidenced days, the 29-criteria gate passes, and "
                           "the realized risk-adjusted metrics are no longer THIN")}

    held = []
    if other_blockers:
        held.append(f"non-time-gated blocker(s): {other_blockers}")
    if not risk_ok:
        held.append("risk-adjusted metrics still THIN/UNKNOWN")
    if not gate_ready and not other_blockers:
        held.append("gate not ready (time-gated criteria still settling)")
    return {"verdict": VERDICT_HELD_GATE,
            "reason": f"{n}/{MIN_TRACK_DAYS} evidenced days reached, but: " + "; ".join(held)}


# ──────────────────────────────────────────────────────────────────────────────
# the artifact builder
# ──────────────────────────────────────────────────────────────────────────────
def build_artifact(
    equity_path: Optional[Path] = None,
    golive_path: Optional[Path] = None,
    forward_analytics_path: Optional[Path] = None,
    *,
    now_iso: Optional[str] = None,
    today: Optional[datetime.date] = None,
    risk_free_rate: float = 0.0,
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build the full day-30 readiness artifact (does NOT write — caller decides).

    Deterministic for fixed inputs: pass ``now_iso`` (the only wall-clock field) AND ``today``
    (the future-date guard reference) to make the whole document — and its ``proof_hash`` —
    byte-stable. The equity hash-chain head over the EVIDENCED bars is embedded as the
    cryptographic anchor of the underlying record.

    Fail-CLOSED throughout: any missing source degrades to UNKNOWN/unavailable, never a
    fabricated pass. The verdict is honest at 7/30 today (NOT_READY).
    """
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    eq_path = Path(equity_path) if equity_path is not None else (root / EQUITY_FILE.name)
    gl_path = Path(golive_path) if golive_path is not None else (root / GOLIVE_FILE.name)
    fa_path = (Path(forward_analytics_path) if forward_analytics_path is not None
               else (root / FORWARD_ANALYTICS_FILE.name))

    daily = _load_daily(eq_path)
    golive = atomic_load(str(gl_path), default=None)
    fa = atomic_load(str(fa_path), default=None)

    ev = evidenced_section(daily, today=today, risk_free_rate=risk_free_rate)
    gate = golive_section(golive if isinstance(golive, dict) else None)
    edge = edge_section(fa if isinstance(fa, dict) else None)
    verdict = compute_verdict(ev, gate)
    caveats = honest_caveats(ev, edge)

    # ── the cryptographic anchor: the equity-chain head over the EVIDENCED bars ──────────────
    # Re-derive (read-only) the single-genesis hash chain over exactly the evidenced equity
    # bars. The head hash is the fingerprint of the entire honest record; if any bar is forged /
    # inserted / reordered / re-dated the head changes → the artifact's proof_hash changes.
    try:
        chain_rows, chain_head = epc.build_chain(eq_path)
    except Exception:  # noqa: BLE001 — fail-CLOSED: no anchor rather than a crash
        chain_rows, chain_head = [], None
    equity_chain = {
        "model": "equity_proof_chain",
        "evidenced_rows": len(chain_rows),
        "head_hash": chain_head,
        "genesis_prev": epc.GENESIS_PREV,
        "recipe": "sha256(canonical({seq,date,kind,payload,prev_hash})) — see equity_proof_chain",
        "verify_cmd": "python3 verify_spa.py data/rates_desk/",
    }

    # readiness_pct — honest progress toward the day-30 bar (evidenced/30, capped at 100).
    readiness_pct = round(min(100.0, 100.0 * ev["evidenced_days"] / MIN_TRACK_DAYS), 2)

    artifact: Dict[str, Any] = {
        "schema": ARTIFACT_VERSION,
        "model": "day30_artifact",
        "llm_forbidden": True,
        "deterministic": True,
        "generated_at": now_iso if now_iso is not None else _utc_now_iso(),
        "min_track_days": MIN_TRACK_DAYS,
        "readiness_pct": readiness_pct,
        "verdict": verdict["verdict"],
        "verdict_reason": verdict["reason"],
        "evidenced": ev,
        "equity_chain": equity_chain,
        "golive_gate": gate,
        "validated_edge": edge,
        "honest_caveats": caveats,
        "note": (
            "Auto-generated day-30 readiness artifact. Every number is sourced live from the "
            "evidenced go-live track + the hardened analytics; a backfilled / reconstructed / "
            "future-dated bar can NEVER count toward the evidenced day-count. The proof_hash "
            "anchors the artifact's content (everything except proof_hash + generated_at); "
            "re-running the generator over the same track reproduces it, and any tampered bar "
            "breaks it. Paper/advisory — not investment advice."
        ),
    }
    artifact["proof_hash"] = compute_proof_hash(artifact)
    return artifact


def write_artifact(
    equity_path: Optional[Path] = None,
    golive_path: Optional[Path] = None,
    forward_analytics_path: Optional[Path] = None,
    out_path: Optional[Path] = None,
    *,
    now_iso: Optional[str] = None,
    today: Optional[datetime.date] = None,
    risk_free_rate: float = 0.0,
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build + atomically write the day-30 artifact. Returns the artifact dict.

    Writes under the SAME data dir it read (so a sandbox/test run lands in its own tmp dir, never
    the live data/day30_artifact.json)."""
    art = build_artifact(
        equity_path, golive_path, forward_analytics_path,
        now_iso=now_iso, today=today, risk_free_rate=risk_free_rate, data_dir=data_dir,
    )
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    out = Path(out_path) if out_path is not None else (root / ARTIFACT_FILE.name)
    atomic_save(art, str(out))
    return art


def verify_artifact(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """Re-derive ``proof_hash`` from an artifact's content and report whether it matches.

    A reviewer (or a watchdog) runs this to confirm a stored artifact was not edited after the
    fact. Returns {valid, stored_hash, recomputed_hash}. Fail-CLOSED: a non-dict / missing hash
    is invalid."""
    if not isinstance(artifact, dict) or "proof_hash" not in artifact:
        return {"valid": False, "stored_hash": None, "recomputed_hash": None}
    stored = artifact.get("proof_hash")
    recomputed = compute_proof_hash(artifact)
    return {"valid": bool(stored == recomputed),
            "stored_hash": stored, "recomputed_hash": recomputed}


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m spa_core.audit.day30_artifact",
        description="Auto, verifiable, hash-anchored day-30 go-live readiness artifact.",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true",
                      help="atomically write data/day30_artifact.json")
    mode.add_argument("--verify", action="store_true",
                      help="re-derive the proof_hash of data/day30_artifact.json and report match")
    args = ap.parse_args(argv)

    if args.verify:
        stored = atomic_load(str(ARTIFACT_FILE), default=None)
        if not isinstance(stored, dict):
            print("day30_artifact: no artifact on disk to verify")
            return 1
        res = verify_artifact(stored)
        print(json.dumps(res, indent=2))
        return 0 if res["valid"] else 2

    if args.write:
        art = write_artifact()
        print(f"day30_artifact: wrote {ARTIFACT_FILE} "
              f"(verdict={art['verdict']}, readiness={art['readiness_pct']}%, "
              f"proof_hash={art['proof_hash'][:16]}…)")
        return 0

    art = build_artifact()
    print(json.dumps(art, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
