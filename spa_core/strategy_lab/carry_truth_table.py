"""
spa_core/strategy_lab/carry_truth_table.py — ROUND-2 WS-1.4: the CARRY TRUTH-TABLE.

THE QUESTION (replace narrative with a number)
══════════════════════════════════════════════
Every sleeve narrative ("FixedCarry harvests real carry", "rwa_sleeve banks the floor",
"eth_lst_neutral is hedged") needs to be replaced with ONE realized number per sleeve: how many
basis points of carry-ABOVE-the-RWA-floor each sleeve has ACTUALLY realized on its live forward
track — or INSUFFICIENT_DATA where the track is too short to say. Honestly. ZERO fabrication.

This module ranks EVERY captured/forward sleeve by realized carry-above-floor (bps/yr), reusing the
EXISTING attribution machinery (forward_analytics.captured_book_attribution → the floor-leg/carry-leg
split that reconciles to NAV) rather than reinventing it. The carry-above-floor (bps) is derived from
the realized carry-leg vs. the floor-leg over the elapsed track.

THE SLEEVES RANKED
══════════════════
  • rates_desk_fixed_carry  — the captured FixedCarry book (data/rates_desk/paper/*_series.json)
  • rwa_sleeve              — the realized RWA cash floor (banks the floor; carry-above ≈ 0 by design)
  • eth_lst_neutral         — the SAFE hedged-ETH sleeve (often INSUFFICIENT_DATA: offline / no track)
  • optimized_yield (realized A/B) — the WS-1.1 realized optimizer book vs the legacy book
  • plus every other *_series.json forward track present (engine_a/b/c, variant_n/d, …)

HONESTY / fail-CLOSED (the red-team the task bakes in)
══════════════════════════════════════════════════════
  • INSUFFICIENT_DATA is a FIRST-CLASS verdict, never masked as 0.0: a track that fails integrity,
    or is thinner than MIN_DAYS_FOR_BPS, or has < 2 points → status INSUFFICIENT_DATA with a null
    carry_above_floor_bps (NOT a fabricated 0.0). A sleeve sitting in cash with no realized carry is
    reported as carry_above_floor_bps≈0 ONLY when it genuinely has a real, dated track that earned it.
  • a backtest series can never enter the table — only the on-disk REALIZED forward *_series.json
    tracks are ingested (the same files the live paper services append to).
  • carry is the RESIDUAL of the NAV reconciliation (carry + floor == realized PnL exactly), so no
    leg can be inflated independently — a tampered/look-ahead series is REFUSED by the integrity gate
    inside captured_book_attribution before any number is computed.
  • deterministic: regenerates byte-identically from a fixed fixture (the smoke test pins this).

stdlib only, deterministic, fail-CLOSED, atomic. LLM FORBIDDEN. Advisory; reads forward series +
the live floor READ-ONLY; never moves capital, never touches the go-live track.

Run:  python3 -m spa_core.strategy_lab.carry_truth_table
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.utils.atomic import atomic_load, atomic_save
from spa_core.strategy_lab import metrics
from spa_core.strategy_lab import forward_analytics as fa

_REPO_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
DATA_DIR = _REPO_ROOT / "data"
OUT_FILE = DATA_DIR / "carry_truth_table.json"

# Below this many distinct forward days the carry-above-floor bps is a degenerate artifact (the
# annualization of a 1-2-day return swings wildly), so the verdict is INSUFFICIENT_DATA — honest at
# the current few-day track depth, by design.
MIN_DAYS_FOR_BPS = fa.MIN_POINTS_FOR_RATIO  # 7 (reuse the same depth bar as the risk-adjusted ratio)

VERDICT_INSUFFICIENT = "INSUFFICIENT_DATA"
VERDICT_ABOVE = "ABOVE_FLOOR"
VERDICT_AT_FLOOR = "AT_FLOOR"
VERDICT_BELOW = "BELOW_FLOOR"


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _discover_forward_series(root: Path) -> Dict[str, Any]:
    """Collect {sleeve_name: series_doc} for every REALIZED forward track on disk: the rates-desk
    FixedCarry book, the strategy_lab_paper sleeves, and the realized-A/B books. ONLY on-disk
    *_series.json forward tracks (never a backtest). Fail-safe (an unreadable file is skipped)."""
    out: Dict[str, Any] = {}
    for sub in ("rates_desk/paper", "strategy_lab_paper", "realized_ab"):
        d = root / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*_series.json")):
            doc = atomic_load(str(f), default=None)
            if doc is not None:
                out[f.name[:-len("_series.json")]] = doc
    return out


def _carry_row(name: str, series_doc: Any, *, floor_apy_pct: float) -> dict:
    """One truth-table row for ONE forward sleeve. Reuses forward_analytics.captured_book_attribution
    (the NAV-reconciling floor-leg/carry-leg split) — carry-above-floor (bps/yr) is the realized
    carry-leg annualized over the elapsed track. INSUFFICIENT_DATA where the track is too short."""
    attr = fa.captured_book_attribution(series_doc, floor_apy_pct=floor_apy_pct, name=name)
    row = {
        "sleeve": name,
        "verdict": VERDICT_INSUFFICIENT,
        "carry_above_floor_bps": None,    # NEVER a fabricated 0.0 — null when not measurable
        "realized_carry_usd": attr.get("carry_leg_usd"),
        "floor_leg_usd": attr.get("floor_leg_usd"),
        "realized_pnl_usd": attr.get("realized_pnl_usd"),
        "nav_usd": attr.get("nav_usd"),
        "initial_capital_usd": attr.get("initial_capital_usd"),
        "n_points": attr.get("n_points"),
        "elapsed_days": attr.get("elapsed_days"),
        "first_date": attr.get("first_date"),
        "last_date": attr.get("last_date"),
        "integrity_ok": attr.get("integrity_ok"),
        "integrity_reason": attr.get("integrity_reason"),
        "reconciles": attr.get("reconciles"),
        "thin": attr.get("thin"),
        "rwa_floor_pct": attr.get("rwa_floor_pct"),
        "reason": "",
    }

    # fail-CLOSED: a broken series / single-point track → INSUFFICIENT_DATA, no number.
    if not attr.get("integrity_ok") or not attr.get("reconciles"):
        row["reason"] = f"integrity/reconcile fail-closed ({attr.get('integrity_reason')})"
        return row
    n = attr.get("n_points") or 0
    elapsed = attr.get("elapsed_days") or 0
    initial = attr.get("initial_capital_usd")
    carry_usd = attr.get("carry_leg_usd")
    if n < 2 or not elapsed or initial in (None, 0) or carry_usd is None:
        row["reason"] = "no realized carry move yet (< 2 dated points / zero elapsed)"
        return row

    # realized carry-above-floor APY (bps): annualize the realized carry-leg return over the elapsed
    # window. carry_return_period = carry_usd / initial_capital; annualized simple → × 365/elapsed.
    carry_return_period = carry_usd / float(initial)
    carry_apy_pct = carry_return_period * (365.0 / float(elapsed)) * 100.0
    bps = round(carry_apy_pct * 100.0, 2)  # pp → bps
    row["carry_above_floor_bps"] = bps

    if n < MIN_DAYS_FOR_BPS:
        # the $ carry is honest, but the ANNUALIZED bps on a < MIN-day track is not yet trustworthy
        # → surface the number but mark the verdict INSUFFICIENT_DATA (depth-honest).
        row["verdict"] = VERDICT_INSUFFICIENT
        row["reason"] = (f"thin track ({n} pts < {MIN_DAYS_FOR_BPS}) — $ carry is honest but the "
                         "annualized bps is not yet a trustworthy verdict")
        return row

    # enough depth → a real verdict.
    if abs(bps) <= 1.0:           # within ~1bp of the floor → AT_FLOOR (banks the floor)
        row["verdict"] = VERDICT_AT_FLOOR
        row["reason"] = "realized carry ≈ floor — banks the floor, no above-floor edge"
    elif bps > 0:
        row["verdict"] = VERDICT_ABOVE
        row["reason"] = "realized carry above the RWA floor on the live forward track"
    else:
        row["verdict"] = VERDICT_BELOW
        row["reason"] = "realized carry BELOW the floor — underperforming tokenized T-bills"
    return row


def build_carry_truth_table(
    *,
    data_dir: Optional[Path] = None,
    floor_apy_pct: Optional[float] = None,
    series_by_name: Optional[Dict[str, Any]] = None,
    write: bool = True,
    now_iso: Optional[str] = None,
) -> dict:
    """Rank every realized forward sleeve by carry-above-floor (bps). Writes data/carry_truth_table.json
    atomically (unless write=False).

    ``series_by_name`` injects the forward tracks (tests/fixture). None → discover on disk.
    ``floor_apy_pct`` overrides the RWA floor (tests). None → live metrics.rwa_floor_apy_pct().
    """
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    floor = metrics.rwa_floor_apy_pct() if floor_apy_pct is None else float(floor_apy_pct)
    series = series_by_name if series_by_name is not None else _discover_forward_series(root)

    rows = [_carry_row(name, doc, floor_apy_pct=floor) for name, doc in sorted(series.items())]

    # rank: sleeves with a measurable bps first (descending), then INSUFFICIENT_DATA (alpha order).
    def _sort_key(r: dict):
        bps = r["carry_above_floor_bps"]
        measurable = bps is not None and r["verdict"] != VERDICT_INSUFFICIENT
        return (0 if measurable else 1, -(bps or 0.0) if measurable else 0.0, r["sleeve"])

    rows.sort(key=_sort_key)

    n_above = sum(1 for r in rows if r["verdict"] == VERDICT_ABOVE)
    n_at = sum(1 for r in rows if r["verdict"] == VERDICT_AT_FLOOR)
    n_below = sum(1 for r in rows if r["verdict"] == VERDICT_BELOW)
    n_insuff = sum(1 for r in rows if r["verdict"] == VERDICT_INSUFFICIENT)

    out = {
        "generated_at": now_iso if now_iso is not None else _utc_now_iso(),
        "model": "carry_truth_table",
        "llm_forbidden": True,
        "deterministic": True,
        "advisory": True,
        "rwa_floor_apy_pct": round(floor, 4),
        "min_days_for_bps": MIN_DAYS_FOR_BPS,
        "n_sleeves": len(rows),
        "n_above_floor": n_above,
        "n_at_floor": n_at,
        "n_below_floor": n_below,
        "n_insufficient_data": n_insuff,
        "rows": rows,
        "note": (
            "Realized carry-above-the-RWA-floor (bps/yr) per forward sleeve, ranked. Carry is the "
            "NAV-reconciling residual (carry + floor == realized PnL exactly), reused from "
            "forward_analytics.captured_book_attribution — no leg can be inflated independently. "
            "INSUFFICIENT_DATA is a first-class verdict (thin/broken track → null bps, never a "
            "fabricated 0.0). Advisory paper; the go-live track is byte-untouched."
        ),
    }
    if write:
        atomic_save(out, str(root / "carry_truth_table.json"))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    import json
    p = argparse.ArgumentParser(description="Carry truth-table (WS-1.4).")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    rep = build_carry_truth_table(write=not args.dry_run)
    print(f"Carry truth-table   RWA floor {rep['rwa_floor_apy_pct']}%/yr   "
          f"{rep['n_above_floor']} above / {rep['n_at_floor']} at / {rep['n_below_floor']} below / "
          f"{rep['n_insufficient_data']} insufficient")
    print(f"{'sleeve':32s} {'verdict':18s} {'carry_bps':>10s} {'carry$':>10s} {'pts':>4s}  reason")
    print("-" * 110)
    for r in rep["rows"]:
        bps = r["carry_above_floor_bps"]
        bps_s = f"{bps:10.2f}" if isinstance(bps, (int, float)) else f"{'—':>10s}"
        cu = r["realized_carry_usd"]
        cu_s = f"{cu:10.2f}" if isinstance(cu, (int, float)) else f"{'—':>10s}"
        print(f"{r['sleeve']:32s} {r['verdict']:18s} {bps_s} {cu_s} {str(r['n_points']):>4s}  "
              f"{r['reason'][:46]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
