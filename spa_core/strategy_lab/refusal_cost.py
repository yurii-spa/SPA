"""
spa_core/strategy_lab/refusal_cost.py — ROUND-2 WS-1.5: "why in cash" refusal-cost attribution.

THE QUESTION (is the conservatism leaving fundable money on the table, or defensible?)
══════════════════════════════════════════════════════════════════════════════════════
The rates-desk refusal-first gate (rate_policy.py) sits in cash whenever every scanned candidate is
refused (tail_veto / economics / size_floor / …). The desk's THESIS is that the refused yield is
tail-compensation — risk premium you'd pay back, not carry. But that thesis has a COST: every day the
gate refuses a candidate that quoted a positive net edge, it FORGOES that edge. This module quantifies
that tradeoff so the owner can SEE it as a number, not a narrative:

  • a per-day FORGONE-EDGE ledger: on each refused-into-cash day, the best refused candidate's net
    edge (bps) is the nominal yield the desk walked away from that day,
  • an aggregate "cost of caution" (bps/yr the gate forgoes by sitting in cash), and
  • the HONEST framing both ways:
      – cost-of-caution (the bps the gate left on the table IF the refused edge were real carry), AND
      – the gate's thesis (that the refused edge is tail-comp, refused for a STRUCTURAL reason — so the
        "cost" is the INSURANCE PREMIUM against the 2025-10 USDe-leverage-unwind pattern, not lost alpha).
    We report BOTH numbers and let the realized track (carry_truth_table) adjudicate which is true.

READ-ONLY analysis of the rate_policy scan diagnostics already persisted in the FixedCarry forward
series (each day's ``scan_diag``: refused_by_reason + best_net_edge_bps). It RE-DERIVES, never re-runs
the gate (no clock, no IO into the gate).

HONESTY / fail-CLOSED
═════════════════════
  • a day with NO scan_diag, or a non-finite edge, contributes NOTHING (never a fabricated forgone
    edge). A day where the gate APPROVED (entered) has zero forgone edge by definition.
  • forgone edge is the STRUCTURAL-refusal forgone yield ONLY where the refusal was a tail/structural
    veto — a size_floor refusal forgoes nothing fundable (the book was simply too small to trade at
    the desk's size discipline), so it is tallied separately and NOT counted as cost-of-caution
    (counting it would INFLATE the apparent cost — the red-team trap of dressing a size limit as
    forgone alpha).
  • thin track → the aggregate annualized bps is flagged thin (honest at the current few-day depth).

stdlib only, deterministic, fail-CLOSED, atomic. LLM FORBIDDEN. Advisory; reads the forward series
READ-ONLY; never moves capital, never touches the go-live track.

Run:  python3 -m spa_core.strategy_lab.refusal_cost
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.utils.atomic import atomic_load, atomic_save

_REPO_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
DATA_DIR = _REPO_ROOT / "data"
FIXED_CARRY_SERIES = DATA_DIR / "rates_desk" / "paper" / "rates_desk_fixed_carry_series.json"
OUT_FILE = DATA_DIR / "refusal_cost.json"

# Below this many forward days the annualized cost-of-caution is a degenerate artifact.
MIN_DAYS_FOR_AGG = 7

# Refusal reasons that forgo genuinely-fundable yield (a STRUCTURAL/economic veto: the desk could have
# taken the carry but chose not to because it judged the yield to be tail-comp). A size_floor refusal
# forgoes nothing fundable (the book was sub-min-size), so it is tracked but NOT counted as cost.
STRUCTURAL_REFUSAL_REASONS = ("tail_veto", "economics", "underlying_depeg", "stable_depeg",
                              "oracle_stale", "funding_flip")
NON_COST_REFUSAL_REASONS = ("size_floor",)

_EPS = 1e-12


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _day_forgone(point: dict) -> Optional[dict]:
    """Per-day forgone-edge record from one FixedCarry series point's scan_diag. None when the day
    carries no usable scan diagnostic (fail-CLOSED: never a fabricated forgone edge)."""
    sd = point.get("scan_diag")
    if not isinstance(sd, dict):
        return None
    by_reason = sd.get("refused_by_reason") or {}
    if not isinstance(by_reason, dict):
        by_reason = {}
    approvals = sd.get("approvals")
    best_bps = sd.get("best_net_edge_bps")
    # the day's refusals split into structural (cost-bearing) vs non-cost (size_floor).
    structural_refusals = sum(int(by_reason.get(r, 0) or 0) for r in STRUCTURAL_REFUSAL_REASONS)
    noncost_refusals = sum(int(by_reason.get(r, 0) or 0) for r in NON_COST_REFUSAL_REASONS)
    # forgone edge counts ONLY when the desk REFUSED a candidate for a STRUCTURAL reason that day AND
    # there was a positive best edge it walked away from. A size_floor-only day forgoes nothing fundable.
    forgone_bps = 0.0
    if structural_refusals > 0 and _finite(best_bps) and float(best_bps) > 0:
        forgone_bps = float(best_bps)
    return {
        "date": point.get("date"),
        "approvals": int(approvals) if isinstance(approvals, int) else None,
        "structural_refusals": structural_refusals,
        "noncost_refusals": noncost_refusals,
        "best_net_edge_bps": float(best_bps) if _finite(best_bps) else None,
        "forgone_edge_bps_if_real": round(forgone_bps, 4),
        "refused_by_reason": dict(by_reason),
    }


def build_refusal_cost(
    *,
    data_dir: Optional[Path] = None,
    series_doc: Optional[Any] = None,
    write: bool = True,
    now_iso: Optional[str] = None,
) -> dict:
    """Quantify the refusal-vs-yield tradeoff from the FixedCarry forward series' per-day scan
    diagnostics. Writes data/refusal_cost.json atomically (unless write=False).

    ``series_doc`` injects the FixedCarry series (tests/fixture). None → read on disk.
    """
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    if series_doc is None:
        series_doc = atomic_load(str(root / "rates_desk" / "paper" /
                                     "rates_desk_fixed_carry_series.json"), default=None)

    base = {
        "generated_at": now_iso if now_iso is not None else _utc_now_iso(),
        "model": "refusal_cost",
        "llm_forbidden": True,
        "deterministic": True,
        "advisory": True,
        "basis": (
            "Refusal-cost attribution: per-day forgone edge (bps) the refusal-first gate walked away "
            "from by sitting in cash, from the FixedCarry forward series' scan_diag (read-only "
            "re-derivation, never a gate re-run). Cost-of-caution counts ONLY structural/economic "
            "refusals (a size_floor refusal forgoes nothing fundable). Reported BOTH ways: the cost "
            "IF the refused edge were real carry, AND the gate's thesis that it is tail-comp insurance."
        ),
    }

    series = series_doc.get("series") if isinstance(series_doc, dict) else None
    if not isinstance(series, list) or not series:
        return {**base, "status": "unavailable", "reason": "no_forward_series",
                "n_days": 0, "ledger": [], "cost_of_caution_bps_per_yr_if_real": None,
                "thin": True}

    ledger: List[dict] = []
    sum_forgone = 0.0
    n_refused_days = 0
    n_entered_days = 0
    n_sizefloor_only_days = 0
    for pt in series:
        if not isinstance(pt, dict):
            continue
        rec = _day_forgone(pt)
        if rec is None:
            continue
        ledger.append(rec)
        if rec["forgone_edge_bps_if_real"] > 0:
            sum_forgone += rec["forgone_edge_bps_if_real"]
            n_refused_days += 1
        elif rec["approvals"]:
            n_entered_days += 1
        elif rec["noncost_refusals"] > 0 and rec["structural_refusals"] == 0:
            n_sizefloor_only_days += 1

    n_days = len(ledger)
    if n_days == 0:
        return {**base, "status": "unavailable", "reason": "no_scan_diagnostics",
                "n_days": 0, "ledger": [], "cost_of_caution_bps_per_yr_if_real": None,
                "thin": True}

    # mean DAILY forgone edge (bps) across the ledger. The "net_edge_bps" is already an annualized
    # rate the candidate quoted (a fixed-rate carry quote), so the mean of the forgone rates IS the
    # annualized cost-of-caution (bps/yr) — the rate of yield the gate declined, not a per-day flow.
    mean_forgone_bps = round(sum_forgone / n_days, 4)
    thin = n_days < MIN_DAYS_FOR_AGG

    out = {
        **base,
        "status": "ok",
        "n_days": n_days,
        "min_days_for_agg": MIN_DAYS_FOR_AGG,
        "n_days_refused_into_cash": n_refused_days,
        "n_days_entered": n_entered_days,
        "n_days_sizefloor_only": n_sizefloor_only_days,
        "cost_of_caution_bps_per_yr_if_real": mean_forgone_bps,
        "thin": thin,
        "interpretation": {
            "cost_of_caution_bps_if_refused_edge_were_real": mean_forgone_bps,
            "gate_thesis": (
                "The refused edge is tail-compensation (the 2025-10 USDe-leverage-unwind / ezETH "
                "pattern), NOT carry — so this 'cost' is the INSURANCE PREMIUM the desk pays to avoid "
                "the blow-up, not forgone alpha. The realized carry_truth_table adjudicates: if the "
                "few approved books realize carry ABOVE the floor, the refusals were defensible; if "
                "even the approved books underperform the floor, the conservatism is the right call."
            ),
            "defensible": (
                "DEFENSIBLE while the realized carry track is thin/at-or-below floor — the gate is "
                "not yet demonstrably leaving real money on the table." if thin else
                "see carry_truth_table realized verdict for adjudication"
            ),
        },
        "ledger": ledger,
        "note": (
            "A size_floor refusal forgoes nothing fundable (sub-min-size book) and is EXCLUDED from "
            "cost-of-caution (counting it would inflate the apparent cost). Advisory; read-only."
        ),
    }
    if write:
        atomic_save(out, str(root / "refusal_cost.json"))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    import json
    p = argparse.ArgumentParser(description="Refusal-cost attribution (WS-1.5).")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    rep = build_refusal_cost(write=not args.dry_run)
    if rep.get("status") != "ok":
        print(json.dumps(rep, indent=2, default=str))
        return 0
    print(f"Refusal-cost   days={rep['n_days']} (refused-into-cash={rep['n_days_refused_into_cash']}, "
          f"entered={rep['n_days_entered']}, sizefloor-only={rep['n_days_sizefloor_only']})")
    print(f"cost-of-caution = {rep['cost_of_caution_bps_per_yr_if_real']} bps/yr "
          f"IF the refused edge were real carry  (thin={rep['thin']})")
    print(f"{'date':12s} {'forgone_bps':>12s} {'struct_ref':>10s} {'best_edge_bps':>14s}")
    print("-" * 54)
    for r in rep["ledger"]:
        be = r["best_net_edge_bps"]
        be_s = f"{be:14.2f}" if isinstance(be, (int, float)) else f"{'—':>14s}"
        print(f"{str(r['date']):12s} {r['forgone_edge_bps_if_real']:>12.2f} "
              f"{r['structural_refusals']:>10d} {be_s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
