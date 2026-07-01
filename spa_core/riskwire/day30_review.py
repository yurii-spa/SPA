#!/usr/bin/env python3
# LLM_FORBIDDEN
"""spa_core/riskwire/day30_review.py — the DAY-30 REVIEW PIPELINE (RISKWIRE WS1.3).

WHY THIS EXISTS
===============
As the healed evidenced go-live track approaches 30 continuous days (anchor
2026-06-22, target ~2026-07-21), the *fundable review artifact* — the document a
real reviewer/funder reads the moment the track lands — must be AUTO-produced,
verifiable, and honest, ready the instant the track hits 30. This module IS that
pipeline.

It is NOT a new measurement engine and NOT a duplicate of ``day30_artifact`` (the
hash-anchored readiness snapshot). It is the comprehensive REVIEW layer built ON
TOP of it — a deterministic COMPOSITION over the already-hardened pieces, each
cited so nothing is re-invented:

  * ``day30_artifact.build_artifact`` — the evidenced-track section, the golive
    gate, the validated-edge rollup, the equity-proof-chain anchor, the honest
    caveats and the readiness verdict. The review EMBEDS this artifact verbatim
    (never recomputes its numbers) and carries its ``proof_hash`` as the anchor
    of the underlying record.
  * ``track_evidence``               — the single source of truth for what
    "evidenced" means, and the CONTINUITY ASSERTION (a review can never be
    produced on a gapped / backfilled track — that is the whole point).
  * ``forward_analytics`` (via the artifact's edge section) — the honest
    edge-at-scale verdict (doesn't beat the floor via yield → chassis + a
    measurement moat; THIN/None below the credible-N, never fabricated).

THE THREE THINGS WS1.3 ADDS ON TOP OF THE ARTIFACT
==================================================
1. **The continuity assertion** (``assert_continuity``) — the evidenced dates
   must be (a) present, (b) evidenced-ONLY (no backfilled/reconstructed/future
   bar counted — inherited from ``track_evidence``), and (c) CONTINUOUS: no
   calendar gap between the anchor and the last evidenced day. A gap /
   discontinuity → ``continuous=False`` with the exact missing dates, and the
   review can NEVER read REVIEW_READY.
2. **The review-readiness state machine** (``review_state``) —
   TRACK_MATURING (N<30) → REVIEW_READY (N>=30 AND continuous AND the artifact
   verdict is READY_FOR_REVIEW). Any hole (short, gapped, held-by-gate,
   thin-metrics, unknown) → NOT ready, with an honest reason. Fail-CLOSED.
3. **The comprehensive review pack** (``build_review``) — the honest reset
   story, the realized risk-adjusted picture (THIN→None below credible-N), the
   honest fundability framing (floor + ~50–150 bps @ ~$5M target, NOT
   floor + 1000 bps; $10M = scale + trust + off-code), the refusal-record
   pointer, the proof surfaces, and the state-machine verdict. Hash-anchored
   with its OWN ``review_hash`` (over its content, excluding the wall clock).

VERIFIABILITY (the property the verification pins)
==================================================
For a FIXED track the review is byte-deterministic: ``build_review(...,
now_iso=<fixed>, today=<fixed>)`` reproduces the same document and the same
``review_hash``. The hash covers everything EXCEPT ``review_hash`` and
``generated_at``. Because the embedded artifact's ``proof_hash`` flows from the
equity-chain head over the EVIDENCED bars, ANY tampered / injected / re-dated bar
changes the artifact hash → changes ``review_hash``. A gapped track flips the
continuity assertion → the state machine refuses REVIEW_READY. There is nothing
to fabricate: below 30 evidenced continuous days the review reads TRACK_MATURING
with the honest "N days to go".

Scope / safety (RISKWIRE_CHARTER §3, verbatim)
==============================================
* stdlib only · deterministic (fixed inputs → fixed bytes) · fail-CLOSED · atomic
  write (``atomic_save`` / ``atomic_save_text``, confined to ``data/riskwire/`` +
  ``docs/``).
* READ-ONLY over the go-live track — it NEVER mutates ``equity_curve_daily.json``
  and moves no capital (advisory / measurement only). INERT re: cutover — it
  flips nothing, arms nothing.
* No LLM anywhere in the review path. No ``spa_core.execution`` import.

CLI::

    python3 -m spa_core.riskwire.day30_review            # print the review (read-only)
    python3 -m spa_core.riskwire.day30_review --write    # write data/riskwire/day30_review.json
                                                          #   + docs/DAY30_REVIEW.md (atomic)
    python3 -m spa_core.riskwire.day30_review --verify    # re-derive review_hash, report match
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.utils.atomic import atomic_load, atomic_save, atomic_save_text
from spa_core.paper_trading import track_evidence as te
from spa_core.audit import day30_artifact as d30

log_name = "spa.riskwire.day30_review"

_REPO_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
DATA_DIR = _REPO_ROOT / "data"
RISKWIRE_DIR = DATA_DIR / "riskwire"
DOCS_DIR = _REPO_ROOT / "docs"

REVIEW_JSON = RISKWIRE_DIR / "day30_review.json"
REVIEW_MD = DOCS_DIR / "DAY30_REVIEW.md"

# The day-30 target depth. MUST agree with day30_artifact.MIN_TRACK_DAYS.
MIN_TRACK_DAYS = d30.MIN_TRACK_DAYS  # 30

# Fixed schema/recipe version — bump on any change to the hash-covered fields.
REVIEW_VERSION = "day30-review-v1"

# ── review-readiness state machine states (deterministic) ─────────────────────────────────────────
STATE_TRACK_MATURING = "TRACK_MATURING"     # N < MIN evidenced days (the honest wait)
STATE_REVIEW_READY = "REVIEW_READY"         # N >= MIN AND continuous AND artifact READY_FOR_REVIEW
STATE_HELD_BY_GATE = "HELD_BY_GATE"         # N >= MIN + continuous but a non-time blocker / thin metrics
STATE_DISCONTINUOUS = "DISCONTINUOUS"       # a gap / backfilled discontinuity — review REFUSED
STATE_UNKNOWN = "UNKNOWN"                    # no usable track (fail-CLOSED)

# Fields excluded from the deterministic review hash.
_NON_CONTENT_KEYS = ("review_hash", "generated_at")

# The honest fundability framing — the load-bearing numbers a funder must see up front (fixed,
# not fabricated: these are the DISCIPLINE, the ceiling the review refuses to oversell past).
FUNDABILITY_FRAME = {
    "target_carry_above_floor_bps_low": 50,
    "target_carry_above_floor_bps_high": 150,
    "target_capacity_usd": 5_000_000,
    "not_a_claim_bps": 1000,   # what an honest review must NEVER claim (floor + 1000 bps ≈ fantasy)
    "ten_m_is": "scale across many gated books + trust (custody / audit / legal / relationships) — "
                "OFF-CODE, not more APY",
}


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _canonical(obj: Any) -> str:
    """Canonical JSON — the SAME recipe the equity/day30 proof chains use (PROOF_CHAIN_SPEC §2)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_review_hash(review: Dict[str, Any]) -> str:
    """SHA-256 over the canonical JSON of the review's CONTENT (excludes review_hash +
    generated_at). Deterministic fingerprint of the reviewed record + the state-machine verdict.

    The EMBEDDED ``day30_artifact`` carries its own wall-clock ``generated_at`` (from ``now_iso``);
    it is stripped here too so the review hash is stable across run instants (the artifact's OWN
    ``proof_hash`` — which already excludes its ``generated_at`` — is what anchors the record). The
    embedded artifact's ``proof_hash`` IS hash-covered, so any tampered/injected/re-dated bar still
    breaks the review hash.
    """
    content = {k: v for k, v in review.items() if k not in _NON_CONTENT_KEYS}
    art = content.get("day30_artifact")
    if isinstance(art, dict):
        content = dict(content)
        content["day30_artifact"] = {k: v for k, v in art.items() if k != "generated_at"}
    return hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()


# ──────────────────────────────────────────────────────────────────────────────
# THE CONTINUITY ASSERTION — a review can NEVER be produced on a gapped/backfilled track
# ──────────────────────────────────────────────────────────────────────────────
def assert_continuity(
    evidenced_dates: List[str],
    *,
    min_days: int = MIN_TRACK_DAYS,
) -> Dict[str, Any]:
    """Assert the evidenced series is CONTINUOUS + evidenced-only (the whole point of a review).

    ``evidenced_dates`` are already the evidenced-ONLY ISO dates from
    ``track_evidence.evidenced_dates`` (backfill / reconstructed / warmup /
    future-dated bars are excluded BY RULE upstream — so this function only needs
    to check calendar contiguity between the anchor and the last evidenced day).

    Returns a deterministic dict:
      {
        continuous:   bool     — True iff there is NO missing calendar day between anchor & last,
        n_evidenced:  int,
        anchor:       str|null,
        last:         str|null,
        span_days:    int      — inclusive calendar span (last - anchor + 1),
        missing_dates:[str,…]  — the exact calendar days inside the span with NO evidenced bar,
        n_missing:    int,
        reason:       str      — human-honest continuity reason.
      }

    Fail-CLOSED: an empty series → continuous=False (there is nothing to review).
    A single duplicate / out-of-order date cannot break it (the dates are a sorted
    set upstream). ANY gap → continuous=False + the exact missing dates surfaced.
    """
    dates = sorted(set(d for d in (evidenced_dates or []) if isinstance(d, str)))
    n = len(dates)
    if n == 0:
        return {"continuous": False, "n_evidenced": 0, "anchor": None, "last": None,
                "span_days": 0, "missing_dates": [], "n_missing": 0,
                "reason": "no evidenced days — nothing to review (fail-closed)"}

    try:
        anchor = datetime.date.fromisoformat(dates[0])
        last = datetime.date.fromisoformat(dates[-1])
    except ValueError:
        return {"continuous": False, "n_evidenced": n, "anchor": dates[0], "last": dates[-1],
                "span_days": 0, "missing_dates": [], "n_missing": 0,
                "reason": "un-parseable evidenced date — refusing to assert continuity (fail-closed)"}

    span_days = (last - anchor).days + 1
    present = set(dates)
    missing: List[str] = []
    cur = anchor
    while cur <= last:
        iso = cur.isoformat()
        if iso not in present:
            missing.append(iso)
        cur += datetime.timedelta(days=1)

    continuous = (len(missing) == 0) and (n == span_days)
    if continuous:
        reason = (f"continuous: {n} evidenced days from {dates[0]} to {dates[-1]} with no gap "
                  f"(every calendar day banked a real cycle)")
    else:
        reason = (f"DISCONTINUOUS: {len(missing)} calendar day(s) inside {dates[0]}..{dates[-1]} "
                  f"have no evidenced cycle — a review CANNOT be produced on a gapped track")
    return {
        "continuous": bool(continuous),
        "n_evidenced": n,
        "anchor": dates[0],
        "last": dates[-1],
        "span_days": span_days,
        "missing_dates": missing,
        "n_missing": len(missing),
        "reason": reason,
    }


# ──────────────────────────────────────────────────────────────────────────────
# THE REVIEW-READINESS STATE MACHINE — TRACK_MATURING → REVIEW_READY (fail-CLOSED)
# ──────────────────────────────────────────────────────────────────────────────
def review_state(
    artifact: Dict[str, Any],
    continuity: Dict[str, Any],
    *,
    min_days: int = MIN_TRACK_DAYS,
) -> Dict[str, Any]:
    """Assign the review-readiness state from the embedded artifact + the continuity assertion.

    Deterministic, fail-CLOSED (no LLM, no whim):

      * no usable track (artifact verdict UNKNOWN)          → UNKNOWN.
      * a discontinuity (continuity.continuous is False AND
        there IS a track)                                   → DISCONTINUOUS (review REFUSED — the
                                                              track must be healed before any review).
      * evidenced < min_days                                → TRACK_MATURING (honest "N days to go").
      * evidenced >= min_days AND continuous AND the
        artifact verdict is READY_FOR_REVIEW                → REVIEW_READY.
      * evidenced >= min_days AND continuous but the
        artifact is HELD_BY_GATE / metrics THIN             → HELD_BY_GATE (real work still pends).

    The review NEVER reads REVIEW_READY on a short, gapped, held, or thin record.
    """
    ev = artifact.get("evidenced") or {}
    n = int(ev.get("evidenced_days", 0) or 0)
    art_verdict = artifact.get("verdict")
    remaining = max(0, min_days - n)

    if art_verdict == d30.VERDICT_UNKNOWN or not ev.get("track_available", False):
        return {"state": STATE_UNKNOWN, "ready_for_review": False,
                "reason": "no usable evidenced track (equity_curve_daily.json missing/corrupt)",
                "remaining_days": min_days}

    # Discontinuity is the hard refusal — checked BEFORE maturity so a gapped 30-day track
    # (fabricated continuity) can never sneak to REVIEW_READY.
    if not continuity.get("continuous", False):
        return {"state": STATE_DISCONTINUOUS, "ready_for_review": False,
                "reason": ("track is DISCONTINUOUS — " + str(continuity.get("reason", "gap detected"))
                           + "; a day-30 review can never be produced on a gapped/backfilled track"),
                "remaining_days": remaining,
                "missing_dates": continuity.get("missing_dates", [])}

    if n < min_days:
        return {"state": STATE_TRACK_MATURING, "ready_for_review": False,
                "reason": (f"{n}/{min_days} evidenced continuous days — {remaining} more must accrue "
                           "before the day-30 review can flip REVIEW_READY (time-gated wait; nothing "
                           "to fix in code)"),
                "remaining_days": remaining}

    # Reached depth AND continuous. The artifact's own verdict decides READY vs HELD.
    if art_verdict == d30.VERDICT_READY_FOR_REVIEW:
        return {"state": STATE_REVIEW_READY, "ready_for_review": True,
                "reason": (f"{n}/{min_days} evidenced CONTINUOUS days, the 29-criteria gate passes, "
                           "and the realized risk-adjusted metrics are no longer THIN — ready for a "
                           "funder review"),
                "remaining_days": 0}

    # depth + continuous but the artifact held (non-time blocker or thin metrics)
    return {"state": STATE_HELD_BY_GATE, "ready_for_review": False,
            "reason": (f"{n}/{min_days} evidenced continuous days reached, but the readiness artifact "
                       f"is {art_verdict}: " + str(artifact.get("verdict_reason", ""))),
            "remaining_days": 0}


# ──────────────────────────────────────────────────────────────────────────────
# THE HONEST NARRATIVE SECTIONS (deterministic, evidence-aware)
# ──────────────────────────────────────────────────────────────────────────────
def _reset_story(ev: Dict[str, Any], continuity: Dict[str, Any]) -> Dict[str, Any]:
    """The honest reset story — WHY the count is what it is (the credibility, stated up front)."""
    n = int(ev.get("evidenced_days", 0) or 0)
    return {
        "anchor": ev.get("evidenced_anchor"),
        "last_evidenced": ev.get("evidenced_last"),
        "evidenced_days": n,
        "target_days": MIN_TRACK_DAYS,
        "continuous": bool(continuity.get("continuous", False)),
        "narrative": (
            "The track was HONESTLY RESET to evidenced-only on 2026-06-26: every bar before the "
            f"anchor ({ev.get('evidenced_anchor')}) — flat-rate backfill, reconstructed placeholders, "
            "pre-teardown warmup/seed bars — was flagged non-evidenced and EXCLUDED by rule. Only a "
            "day with a real daily_cycle log counts. So this review reports "
            f"{n}/{MIN_TRACK_DAYS} evidenced continuous days, not an inflated raw bar-count. A "
            "backfilled or future-dated day can never lift this number."
        ),
    }


def _edge_at_scale_verdict(edge: Dict[str, Any]) -> Dict[str, Any]:
    """The honest edge-at-scale verdict — does NOT beat the floor via yield → chassis + moat."""
    beats = edge.get("n_beats_floor")
    floor = edge.get("rwa_floor_apy_pct")
    survives = edge.get("carry_book_survives_all_stress")
    return {
        "available": bool(edge.get("available")),
        "n_tracks": edge.get("n_tracks"),
        "n_beats_floor": beats,
        "rwa_floor_apy_pct": floor,
        "carry_book_survives_all_stress": survives,
        "verdict": (
            "The edge is NOT raw yield. On the realized forward record the desk does not "
            "demonstrably clear the RWA floor by a fundable margin via APY alone — a neutral book is "
            "a DIVERSIFIER, not an alpha. The honest edge is the CHASSIS + the MEASUREMENT MOAT: a "
            "deterministic, LLM-free, fail-closed refusal engine that harvests real mispriced carry "
            "and REFUSES tail-comp yield, with a public, hash-anchored refusal record. That is what "
            "scales without a capacity ceiling; APY does not."
        ),
    }


def _fundability_frame(ev: Dict[str, Any]) -> Dict[str, Any]:
    """The honest fundability framing — the DISCIPLINE (floor + 50–150 bps @ ~$5M, NOT +1000 bps)."""
    f = dict(FUNDABILITY_FRAME)
    f["framing"] = (
        f"Honest fundability target: RWA floor + ~{f['target_carry_above_floor_bps_low']}–"
        f"{f['target_carry_above_floor_bps_high']} bps at ~${f['target_capacity_usd']:,} of gated "
        f"capacity — NOT floor + {f['not_a_claim_bps']} bps (that would be a fantasy this review "
        f"refuses to print). The $10M valuation is {f['ten_m_is']}. A single rates book does not "
        "clear $10M; the moat is scale across many gated books plus off-code trust."
    )
    return f


def _refusal_and_proof_surfaces(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """Pointers to the refusal record + the proof surfaces a reviewer can independently verify."""
    chain = artifact.get("equity_chain") or {}
    return {
        "refusal_record": {
            "description": "the public, hash-chained refusal log — every toxic book the desk refused "
                           "on the live track is a data point that IS the product's credibility",
            "api": "/api/refusal · /api/rates-desk/decisions (entries + refusals + proof_hash)",
            "data": "data/refusal_status.json · data/rates_desk/",
        },
        "proof_surfaces": {
            "equity_chain_head": chain.get("head_hash"),
            "equity_chain_rows": chain.get("evidenced_rows"),
            "day30_artifact_proof_hash": artifact.get("proof_hash"),
            "verify_cmd": chain.get("verify_cmd") or "python3 verify_spa.py data/rates_desk/",
            "note": "don't trust us, check us — every number above re-derives from the evidenced "
                    "equity chain; a tampered bar breaks the head and the artifact proof_hash.",
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# THE REVIEW BUILDER
# ──────────────────────────────────────────────────────────────────────────────
def build_review(
    equity_path: Optional[Path] = None,
    golive_path: Optional[Path] = None,
    forward_analytics_path: Optional[Path] = None,
    *,
    now_iso: Optional[str] = None,
    today: Optional[datetime.date] = None,
    risk_free_rate: float = 0.0,
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build the full day-30 review pack (does NOT write — caller decides).

    Deterministic for fixed inputs: pass ``now_iso`` (the only wall-clock field) AND ``today``
    (the future-date guard reference) to make the whole document — and its ``review_hash`` —
    byte-stable. The pipeline:

      1. builds the day30 readiness artifact (embedded verbatim — never recomputed);
      2. asserts CONTINUITY over the artifact's evidenced dates (a gap → the review REFUSES ready);
      3. runs the review-readiness state machine (TRACK_MATURING → REVIEW_READY);
      4. composes the honest narrative sections + anchors the pack with ``review_hash``.

    Fail-CLOSED throughout: a missing source degrades to UNKNOWN/unavailable, never a fabricated
    pass. On the CURRENT 9/30 track it reads TRACK_MATURING with the honest "21 days to go".
    """
    root = Path(data_dir) if data_dir is not None else DATA_DIR

    # 1. embed the readiness artifact verbatim (its own deterministic hash flows through).
    artifact = d30.build_artifact(
        equity_path, golive_path, forward_analytics_path,
        now_iso=now_iso, today=today, risk_free_rate=risk_free_rate, data_dir=data_dir,
    )
    ev = artifact.get("evidenced") or {}
    edge = artifact.get("validated_edge") or {}

    # 2. the continuity assertion over the artifact's EVIDENCED dates (evidenced-only upstream).
    continuity = assert_continuity(ev.get("evidenced_dates") or [])

    # 3. the review-readiness state machine.
    state = review_state(artifact, continuity)

    # 4. the honest narrative sections.
    reset = _reset_story(ev, continuity)
    edge_verdict = _edge_at_scale_verdict(edge)
    fundability = _fundability_frame(ev)
    surfaces = _refusal_and_proof_surfaces(artifact)

    n = int(ev.get("evidenced_days", 0) or 0)
    review_readiness_pct = round(min(100.0, 100.0 * n / MIN_TRACK_DAYS), 2)

    review: Dict[str, Any] = {
        "schema": REVIEW_VERSION,
        "model": "day30_review",
        "llm_forbidden": True,
        "deterministic": True,
        "inert_re_cutover": True,   # this review flips nothing / arms nothing (advisory)
        "generated_at": now_iso if now_iso is not None else _utc_now_iso(),
        "min_track_days": MIN_TRACK_DAYS,
        "review_readiness_pct": review_readiness_pct,
        "state": state["state"],
        "ready_for_review": bool(state.get("ready_for_review", False)),
        "state_reason": state["reason"],
        "remaining_days": state.get("remaining_days"),
        "continuity": continuity,
        "reset_story": reset,
        "realized_risk_metrics": ev.get("risk_metrics"),        # THIN→None below credible-N (verbatim)
        "realized_total_return_pct": ev.get("realized_total_return_pct"),
        "realized_max_drawdown_pct": ev.get("realized_max_drawdown_pct"),
        "edge_at_scale": edge_verdict,
        "fundability_frame": fundability,
        "refusal_and_proof": surfaces,
        "honest_caveats": artifact.get("honest_caveats"),        # reuse the artifact's caveats verbatim
        "day30_artifact": artifact,                              # embedded verbatim (its proof_hash anchors)
        "note": (
            "Auto-generated DAY-30 REVIEW pack (RISKWIRE WS1.3). The comprehensive review a real "
            "reviewer/funder reads the moment the evidenced track reaches 30 continuous days. Every "
            "number is sourced live from the evidenced go-live track + the hardened analytics; a "
            "backfilled / reconstructed / future-dated / gapped day can NEVER produce a REVIEW_READY "
            "verdict (the continuity assertion refuses it). The review_hash anchors the pack's content "
            "(everything except review_hash + generated_at); re-running the pipeline over the same "
            "track reproduces it, and any tampered bar breaks it. INERT re: cutover — flips nothing. "
            "Paper/advisory — not investment advice."
        ),
    }
    review["review_hash"] = compute_review_hash(review)
    return review


def render_markdown(review: Dict[str, Any]) -> str:
    """Render the review as a human-readable docs/DAY30_REVIEW.md (deterministic).

    Every figure is sourced from the review dict or printed as an honest UNAVAILABLE — no
    fabricated numbers. Kept plain-markdown so it renders on the site and in a terminal alike.
    """
    def _fmt(v: Any, suffix: str = "") -> str:
        if v is None:
            return "_UNAVAILABLE_"
        return f"{v}{suffix}"

    ev = (review.get("day30_artifact") or {}).get("evidenced") or {}
    cont = review.get("continuity") or {}
    reset = review.get("reset_story") or {}
    edge = review.get("edge_at_scale") or {}
    fund = review.get("fundability_frame") or {}
    risk = review.get("realized_risk_metrics") or {}
    surfaces = review.get("refusal_and_proof") or {}
    proof = surfaces.get("proof_surfaces") or {}

    n = ev.get("evidenced_days")
    lines: List[str] = []
    lines.append("# Day-30 Review — SPA go-live track")
    lines.append("")
    lines.append("> **AUTO-GENERATED · deterministic · hash-anchored · read-only · advisory · "
                 "INERT re: cutover.** The comprehensive review a reviewer/funder reads the moment "
                 "the evidenced track reaches 30 continuous days. Paper/advisory — not investment "
                 "advice.")
    lines.append("")
    lines.append(f"**State:** `{review.get('state')}` — {review.get('state_reason')}")
    lines.append("")
    lines.append(f"**Review readiness:** {_fmt(review.get('review_readiness_pct'), '%')} "
                 f"({_fmt(n)}/{review.get('min_track_days')} evidenced continuous days · "
                 f"{_fmt(review.get('remaining_days'))} to go)")
    lines.append("")
    lines.append(f"**Review hash:** `{review.get('review_hash')}`")
    lines.append("")

    # 1. the honest reset story
    lines.append("## 1. The honest reset story")
    lines.append("")
    lines.append(reset.get("narrative", "_UNAVAILABLE_"))
    lines.append("")
    lines.append(f"- Anchor: `{_fmt(reset.get('anchor'))}` · last evidenced: "
                 f"`{_fmt(reset.get('last_evidenced'))}`")
    lines.append(f"- Continuous: **{reset.get('continuous')}** "
                 f"(span {_fmt(cont.get('span_days'))} days, {_fmt(cont.get('n_missing'))} missing)")
    if cont.get("missing_dates"):
        lines.append(f"- ⚠️ Missing (un-evidenced) calendar days: `{cont.get('missing_dates')}` — "
                     "a review CANNOT be produced on a gapped track.")
    lines.append("")

    # 2. realized risk-adjusted metrics
    lines.append("## 2. Realized risk-adjusted metrics (evidenced-only)")
    lines.append("")
    status = risk.get("status")
    if status == "OK":
        lines.append(f"- Sharpe: **{_fmt(risk.get('sharpe'))}** · Sortino: "
                     f"**{_fmt(risk.get('sortino'))}** (n={_fmt(risk.get('n_returns'))} evidenced "
                     "daily returns)")
    else:
        lines.append(f"- Sharpe/Sortino: **THIN → None** (only {_fmt(risk.get('n_returns'))} of "
                     f"{_fmt(risk.get('min_returns'))} evidenced daily returns) — a small-sample "
                     "ratio is degenerate, so it is REFUSED, never fabricated.")
    lines.append(f"- Realized total return: {_fmt(review.get('realized_total_return_pct'), '%')} · "
                 f"realized max drawdown: {_fmt(review.get('realized_max_drawdown_pct'), '%')}")
    lines.append("")

    # 3. the edge-at-scale honest verdict
    lines.append("## 3. Edge at scale — the honest verdict")
    lines.append("")
    lines.append(edge.get("verdict", "_UNAVAILABLE_"))
    lines.append("")
    lines.append(f"- RWA floor: {_fmt(edge.get('rwa_floor_apy_pct'), '%')} · beats-floor tracks: "
                 f"{_fmt(edge.get('n_beats_floor'))}/{_fmt(edge.get('n_tracks'))} · carry book "
                 f"survives all stress: **{_fmt(edge.get('carry_book_survives_all_stress'))}**")
    lines.append("")

    # 4. honest fundability framing
    lines.append("## 4. Honest fundability framing")
    lines.append("")
    lines.append(fund.get("framing", "_UNAVAILABLE_"))
    lines.append("")

    # 5. refusal record + proof surfaces
    lines.append("## 5. Refusal record + proof surfaces (don't trust us, check us)")
    lines.append("")
    rr = surfaces.get("refusal_record") or {}
    lines.append(f"- Refusal record: {rr.get('description', '_UNAVAILABLE_')}")
    lines.append(f"  - API: `{rr.get('api')}` · data: `{rr.get('data')}`")
    lines.append(f"- Equity-chain head: `{_fmt(proof.get('equity_chain_head'))}` "
                 f"({_fmt(proof.get('equity_chain_rows'))} evidenced rows)")
    lines.append(f"- Day-30 artifact proof_hash: `{_fmt(proof.get('day30_artifact_proof_hash'))}`")
    lines.append(f"- Verify: `{proof.get('verify_cmd')}`")
    lines.append("")

    # 6. honest caveats
    lines.append("## 6. Honest caveats")
    lines.append("")
    for c in (review.get("honest_caveats") or []):
        lines.append(f"- {c}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"_{review.get('note')}_")
    lines.append("")
    return "\n".join(lines)


def write_review(
    equity_path: Optional[Path] = None,
    golive_path: Optional[Path] = None,
    forward_analytics_path: Optional[Path] = None,
    out_json: Optional[Path] = None,
    out_md: Optional[Path] = None,
    *,
    now_iso: Optional[str] = None,
    today: Optional[datetime.date] = None,
    risk_free_rate: float = 0.0,
    data_dir: Optional[Path] = None,
    write_md: bool = True,
) -> Dict[str, Any]:
    """Build + atomically write data/riskwire/day30_review.json (+ docs/DAY30_REVIEW.md).

    LIVE-GUARDED: the JSON lands under the SAME data dir it read (so a sandbox run writes to its
    own tmp dir, never the canonical data/riskwire/day30_review.json). The human-readable
    docs/DAY30_REVIEW.md is a CANONICAL artifact — it is written ONLY on a canonical run (data_dir
    is None or the live DATA_DIR). A sandbox run (explicit tmp data_dir) skips the .md unless an
    explicit ``out_md`` is given, so a QA run can never overwrite the canonical doc.
    """
    review = build_review(
        equity_path, golive_path, forward_analytics_path,
        now_iso=now_iso, today=today, risk_free_rate=risk_free_rate, data_dir=data_dir,
    )
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    rw_dir = root / "riskwire"
    rw_dir.mkdir(parents=True, exist_ok=True)
    out_j = Path(out_json) if out_json is not None else (rw_dir / REVIEW_JSON.name)
    atomic_save(review, str(out_j))

    # docs/DAY30_REVIEW.md — canonical only (never from a sandbox-redirected run).
    is_canonical = (data_dir is None) or (root.resolve() == DATA_DIR.resolve())
    if write_md and (is_canonical or out_md is not None):
        md_path = Path(out_md) if out_md is not None else REVIEW_MD
        md_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_save_text(render_markdown(review), str(md_path))
    return review


def verify_review(review: Dict[str, Any]) -> Dict[str, Any]:
    """Re-derive ``review_hash`` from a review's content and report whether it matches.

    Fail-CLOSED: a non-dict / missing hash is invalid. Also surfaces the embedded artifact's own
    self-consistency so a reviewer verifies the WHOLE chain (review + artifact) in one call.
    """
    if not isinstance(review, dict) or "review_hash" not in review:
        return {"valid": False, "stored_hash": None, "recomputed_hash": None,
                "artifact_valid": None}
    stored = review.get("review_hash")
    recomputed = compute_review_hash(review)
    art = review.get("day30_artifact")
    art_res = d30.verify_artifact(art) if isinstance(art, dict) else {"valid": None}
    return {"valid": bool(stored == recomputed and art_res.get("valid") is not False),
            "stored_hash": stored, "recomputed_hash": recomputed,
            "review_hash_match": bool(stored == recomputed),
            "artifact_valid": art_res.get("valid")}


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m spa_core.riskwire.day30_review",
        description="Auto, verifiable, hash-anchored DAY-30 REVIEW pipeline (RISKWIRE WS1.3).",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true",
                      help="atomically write data/riskwire/day30_review.json + docs/DAY30_REVIEW.md")
    mode.add_argument("--verify", action="store_true",
                      help="re-derive the review_hash of data/riskwire/day30_review.json, report match")
    args = ap.parse_args(argv)

    if args.verify:
        stored = atomic_load(str(REVIEW_JSON), default=None)
        if not isinstance(stored, dict):
            print("day30_review: no review on disk to verify")
            return 1
        res = verify_review(stored)
        print(json.dumps(res, indent=2))
        return 0 if res["valid"] else 2

    if args.write:
        review = write_review()
        print(f"day30_review: wrote {REVIEW_JSON} + {REVIEW_MD} "
              f"(state={review['state']}, readiness={review['review_readiness_pct']}%, "
              f"review_hash={review['review_hash'][:16]}…)")
        return 0

    review = build_review()
    print(json.dumps(review, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
