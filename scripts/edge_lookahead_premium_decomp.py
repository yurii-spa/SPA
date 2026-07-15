#!/usr/bin/env python3
"""
scripts/edge_lookahead_premium_decomp.py — Idea #13: Look-Ahead Premium Decomposition

NOVEL EDGE IDEA #13 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry):

WHERE THIS BUILDS FROM
  Idea #9 found the crisis-lifecycle overlay's Calmar drops from an ORACLE 14.29 (regime
  switched on the KNOWN crisis dates, `STRESS_WINDOWS`) to a live-attainable CAUSAL 3.68
  (regime switched on trailing drawdown only) — a **look-ahead premium of ~10.61 Calmar**
  that a live controller cannot have. Idea #10 showed the causal edge survives real costs.

  The open engineering question #13 answers: **of that ~10.61 premium, how much comes from
  knowing the crisis START early (entry timing) vs knowing the crisis END early (exit
  timing)?** That tells RTMR WHERE to spend signal engineering — is the live gap mostly a
  slow crisis-ONSET detector problem, or a slow RECOVERY detector problem?

THE IDEA (decompose entry vs exit look-ahead)
  The overlay has two transitions:
    • ENTRY  (CRUISE → DEFEND): when do we de-risk?
    • EXIT   (DEFEND → CRUISE/HARVEST): when do we re-risk?

  Each can independently use ORACLE (STRESS_WINDOWS boundaries) or CAUSAL (trailing DD).
  Run all four combinations, holding weights + harvest identical so ONLY the information
  set on each transition changes:

    (oracle-entry, oracle-exit)  = knows both start and end   → full look-ahead
    (causal-entry, causal-exit)  = knows neither              → #9 live-attainable
    (oracle-entry, causal-exit)  = knows START only
    (causal-entry, oracle-exit)  = knows END only

  Decomposition (in Calmar):
    total premium       = Cal(oracle,oracle) − Cal(causal,causal)
    value of knowing START = Cal(oracle-entry, causal-exit) − Cal(causal, causal)
    value of knowing END   = Cal(causal-entry, oracle-exit) − Cal(causal, causal)
    interaction            = total − (value_START + value_END)

  If value_START ≫ value_END: the live gap is a crisis-ONSET detection problem → invest in
  a faster de-risk trigger (vol/peg/oracle sensors leading drawdown). If value_END ≫
  value_START: it's a RECOVERY detection problem → invest in a vol-stabilisation re-risk
  signal. Either way #13 turns "we lose 10.61" into an actionable direction.

HONEST CAVEATS
  (a) Weights (#3/#7/#8 sleeves), harvest window, and causal thresholds are held fixed at
      #9's best-honest values so the ONLY variable is oracle-vs-causal per transition.
  (b) rates-carry + RWA-floor are SMOOTH SYNTHETIC; the sUSDe leg carries the real crisis
      vol (same fixture as #7/#8/#9/#10 — apples-to-apples).
  (c) "oracle" here = perfect knowledge of the STRESS_WINDOW boundary (0-day lead / 0-day
      lag). Real look-ahead would be imperfect; this is the UPPER bound on each side's value.
  (d) EVIDENCE LEVEL: L0 (backtest/synthetic). NOT live results.

Does NOT touch spa_core/execution, live paper track, or RiskPolicy v1.0.
stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab.aggressive_lab import fixtures as fx, loader as ld  # noqa: E402
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS  # noqa: E402

RATES_APY_PCT = 4.6
RWA_APY_PCT = 3.31

WEIGHTS_CRUISE  = [0.25, 0.50, 0.25]  # #3
WEIGHTS_DEFEND  = [0.05, 0.25, 0.70]  # #7
WEIGHTS_HARVEST = [0.40, 0.45, 0.15]  # #8

# #9 best-honest causal thresholds (drawdown fractions) + harvest window
THETA_ENTER = 0.003
THETA_EXIT = 0.001
HARVEST_DAYS = 21


def _load_susde_returns() -> Dict[str, float]:
    tmp = Path(tempfile.mkdtemp(prefix="lpd_"))
    fx.materialize(tmp)
    strats = ld.load_all(data_dir=tmp)
    s = strats.get("susde_dn")
    if s is None or s.backtest.n_points < 60:
        raise RuntimeError("susde_dn fixture not available")
    eq: Dict[str, float] = {}
    for p in s.backtest.series:
        d, e = p.get("date"), p.get("equity_usd", p.get("equity"))
        if d and e is not None:
            eq[d] = float(e)
    dates = sorted(eq)
    return {dates[i]: eq[dates[i]] / eq[dates[i - 1]] - 1.0
            for i in range(1, len(dates)) if eq[dates[i - 1]]}


def _smooth(dates: List[str], apy_pct: float) -> Dict[str, float]:
    daily = apy_pct / 100.0 / 365.0
    return {d: daily for d in dates}


def _windows() -> List[Tuple[datetime.date, datetime.date]]:
    return [(datetime.date.fromisoformat(str(w["date_from"])),
             datetime.date.fromisoformat(str(w["date_to"]))) for w in STRESS_WINDOWS]


def _in_window(d: datetime.date, wins: List[Tuple[datetime.date, datetime.date]]) -> bool:
    return any(lo <= d <= hi for lo, hi in wins)


def _run(
    dates: List[str],
    r_s: Dict[str, float],
    r_r: Dict[str, float],
    r_w: Dict[str, float],
    entry_mode: str,   # "oracle" | "causal"
    exit_mode: str,    # "oracle" | "causal"
) -> Tuple[List[float], Dict[str, int]]:
    """
    Unified regime engine. ENTRY (cruise→defend) and EXIT (defend→cruise) each use oracle
    (STRESS_WINDOWS) or causal (trailing DD). Weights/harvest identical across modes so only
    the per-transition information set changes. Decisions use info through yesterday.
    """
    wins = _windows()
    eq = 100_000.0
    out = [eq]
    hwm = eq
    defending = False
    harvest_left = 0
    counts = {"CRUISE": 0, "DEFEND": 0, "HARVEST": 0}
    for ds in dates:
        d = datetime.date.fromisoformat(ds)
        dd = (eq - hwm) / hwm if hwm > 0 else 0.0
        if not defending:
            if entry_mode == "oracle":
                enter = _in_window(d, wins)
            else:
                enter = dd <= -THETA_ENTER
            if enter:
                defending = True
                harvest_left = 0
        else:
            if exit_mode == "oracle":
                leave = not _in_window(d, wins)
            else:
                leave = dd >= -THETA_EXIT
            if leave:
                defending = False
                harvest_left = HARVEST_DAYS
        if defending:
            w = WEIGHTS_DEFEND
            regime = "DEFEND"
        elif harvest_left > 0:
            w = WEIGHTS_HARVEST
            harvest_left -= 1
            regime = "HARVEST"
        else:
            w = WEIGHTS_CRUISE
            regime = "CRUISE"
        counts[regime] += 1
        r = w[0] * r_s.get(ds, 0.0) + w[1] * r_r.get(ds, 0.0) + w[2] * r_w.get(ds, 0.0)
        eq *= (1.0 + r)
        hwm = max(hwm, eq)
        out.append(eq)
    return out, counts


def _metrics(equity: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if len(equity) < 2:
        return None, None, None
    n_days = len(equity) - 1
    net_apy = (equity[-1] / equity[0]) ** (365.0 / n_days) - 1.0
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        dd = (e - peak) / peak
        if dd < max_dd:
            max_dd = dd
    max_dd_pct = abs(max_dd) * 100.0
    calmar = (net_apy * 100.0) / max_dd_pct if max_dd_pct > 0 else None
    return net_apy * 100.0, max_dd_pct, calmar


def _f(x: Optional[float], d: int = 2) -> str:
    return f"{x:.{d}f}" if isinstance(x, (int, float)) else "n/a"


def run_analysis() -> Dict[str, object]:
    r_s = _load_susde_returns()
    dates = sorted(r_s)
    r_r = _smooth(dates, RATES_APY_PCT)
    r_w = _smooth(dates, RWA_APY_PCT)

    cells: Dict[Tuple[str, str], Dict[str, object]] = {}
    for em in ("oracle", "causal"):
        for xm in ("oracle", "causal"):
            eq, cnt = _run(dates, r_s, r_r, r_w, em, xm)
            apy, dd, cal = _metrics(eq)
            cells[(em, xm)] = {"apy": apy, "dd": dd, "calmar": cal, "counts": cnt}

    cal = {k: v["calmar"] for k, v in cells.items()}
    oo = cal[("oracle", "oracle")]
    cc = cal[("causal", "causal")]
    oc = cal[("oracle", "causal")]   # know START only
    co = cal[("causal", "oracle")]   # know END only

    def _sub(a, b):
        return (a - b) if isinstance(a, float) and isinstance(b, float) else None

    total = _sub(oo, cc)
    val_start = _sub(oc, cc)
    val_end = _sub(co, cc)
    interaction = (_sub(total, (val_start + val_end))
                   if isinstance(total, float) and isinstance(val_start, float)
                   and isinstance(val_end, float) else None)

    return {
        "dates": dates,
        "cells": cells,
        "total_premium": total,
        "value_start": val_start,
        "value_end": val_end,
        "interaction": interaction,
    }


def main() -> None:
    print("=" * 74)
    print("IDEA #13: Look-Ahead Premium Decomposition (crisis START vs END knowledge)")
    print("Of the ~10.61 Calmar the oracle gains (idea #9), how much is entry vs exit timing?")
    print("All numbers: BACKTEST / SYNTHETIC. NOT live results.")
    print("=" * 74)

    res = run_analysis()
    cells = res["cells"]
    dates = res["dates"]
    print(f"\nBacktest window: {dates[0]} → {dates[-1]} ({len(dates)} days)")
    print("Weights/harvest/thresholds fixed at #9 values; ONLY oracle-vs-causal per transition changes.\n")

    print("── 2×2 GRID (Calmar) ───────────────────────────────────────────────────────")
    print(f"  {'':16} {'exit=ORACLE':>14} {'exit=CAUSAL':>14}")
    for em in ("oracle", "causal"):
        row = []
        for xm in ("oracle", "causal"):
            row.append(_f(cells[(em, xm)]["calmar"]))
        tag = "entry=ORACLE" if em == "oracle" else "entry=CAUSAL"
        print(f"  {tag:16} {row[0]:>14} {row[1]:>14}")
    print("  (oracle,oracle)=full look-ahead #7 · (causal,causal)=live #9)")

    print("\n── per-cell detail (APY / maxDD / Calmar / regime days) ────────────────────")
    label = {("oracle", "oracle"): "know BOTH (full oracle)",
             ("oracle", "causal"): "know START only",
             ("causal", "oracle"): "know END only",
             ("causal", "causal"): "know NEITHER (live #9)"}
    for k in (("oracle", "oracle"), ("oracle", "causal"), ("causal", "oracle"), ("causal", "causal")):
        c = cells[k]
        cn = c["counts"]
        print(f"  {label[k]:26} APY {_f(c['apy']):>6}%  DD {_f(c['dd']):>5}%  "
              f"Calmar {_f(c['calmar']):>6}  "
              f"{cn.get('CRUISE',0)}C/{cn.get('DEFEND',0)}D/{cn.get('HARVEST',0)}H")

    print("\n── DECOMPOSITION (Calmar attributable to each side's look-ahead) ───────────")
    total = res["total_premium"]
    vs = res["value_start"]
    ve = res["value_end"]
    inter = res["interaction"]
    print(f"  Total look-ahead premium (oracle − causal) : {_f(total)}")
    print(f"  Value of knowing crisis START (entry)       : {_f(vs)}")
    print(f"  Value of knowing crisis END   (exit)        : {_f(ve)}")
    print(f"  Interaction (non-additive remainder)        : {_f(inter)}")

    print("\n── VERDICT ─────────────────────────────────────────────────────────────────")
    if isinstance(vs, float) and isinstance(ve, float):
        if vs > ve * 1.5:
            verdict = "✅ ENTRY-dominated — the live gap is mostly a crisis-ONSET detection problem"
            note = ("Most of the lost premium comes from de-risking LATE. Invest in a faster causal "
                    "de-risk trigger (vol/peg/oracle sensors that LEAD drawdown) — RTMR already has these.")
        elif ve > vs * 1.5:
            verdict = "✅ EXIT-dominated — the live gap is mostly a RECOVERY detection problem"
            note = ("Most of the lost premium comes from re-risking LATE (or too early). Invest in a "
                    "vol-stabilisation re-risk signal to time the RECOVERY harvest, not the onset.")
        else:
            verdict = "⚖️ BALANCED — entry and exit look-ahead contribute comparably"
            note = ("Neither transition dominates; a live controller must improve BOTH onset and "
                    "recovery detection to close the gap. No single cheap win.")
        print(f"  Verdict: {verdict}")
        print(f"  {note}")
    else:
        print("  Verdict: inconclusive (a Calmar cell was undefined).")

    print("\n  HONEST CAVEATS:")
    print("  (a) 'oracle' = perfect STRESS_WINDOW boundary knowledge (0-lead/0-lag) → UPPER bound per side.")
    print("  (b) rates/RWA smooth synthetic; sUSDe leg carries real crisis vol (same fixture as #7–#10).")
    print("  (c) Thresholds/weights fixed at #9 values — isolates information set, not tuning.")
    print("  (d) EVIDENCE LEVEL: L0 (backtest/synthetic). NOT live results.")
    print("\n  NEXT STEP: point the dominant side's causal detector at RTMR's leading sensors")
    print("  (vol/peg/oracle for onset; vol-stabilisation for recovery). ADR before any capital move.")


if __name__ == "__main__":
    main()
