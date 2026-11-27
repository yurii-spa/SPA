#!/usr/bin/env python3
"""
scripts/edge_dcps_real_panel.py — registry idea #168 DCPS (Dynamic-Target Cross-book Peril
Suspension), the ORDER left verbatim by #167, measured on the REAL panel.

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

WHAT #167 LEFT.  CPS fires on BREADTH (>= K books with a negative W-day trailing return) and
suspends ONE fixed book (leverage_loop).  On the L0 fixture it helped in one crisis window of
three, because each window had a DIFFERENT dominant loser.  The order:

    "DCPS: on each stress day suspend not a pre-fixed book but the book with the LARGEST
     cumulative loss over the same W-day window (argmin of W-day cumulative return).
     Acceptance: DCPS must improve maxDD in ALL THREE windows without worsening Calmar on
     TEST.  Second path: measure the false-positive rate outside the stress windows."

WHAT THIS INSTRUMENT CHANGES RELATIVE TO #167 (each one declared before the run):
  1. PANEL — the REAL ten-book panel `data/aggressive_lab/*/realized_series.jsonl`
     (phase="backtest" block only, loader `edge_real_panel_ensemble.load_panel`), not the
     fixture.  #167 could not read it (cloud container); this Mac can.  Real noise answers the
     order's "second path" directly — no synthetic seed is needed.
  2. SELECTION ON TRAIN — #167 reported the best of 24 cells BY TEST CALMAR, which is
     in-sample selection on the test set.  Here the cell is chosen on TRAIN (<= 2025-06-30)
     and only then read on TEST; the share of all cells that beat the baseline on TEST is
     printed beside it, so a lucky cell cannot pass for a mechanism.
  3. TARGET PLACEBO — DCPS differs from CPS only in WHICH book is cut.  The control that
     decides whether target choice carries information: the SAME stress days, the SAME F,
     a uniformly random live book as target (2000 seeded draws).  DCPS inside that
     distribution ⇒ the result is de-grossing timing, not target selection.
  4. FIXED-TARGET CPS on the real panel — the target is the book with the largest TRAIN
     drawdown (the real analogue of "the highest-tail book"), fixed ex ante.

PORTFOLIO.  Equal weight over the ten books, rebalanced daily (identical to
`subset_perf`).  Suspension cuts the target's weight by F; mode "redistribute" (as #167)
spreads it over the other books, mode "cash" holds it at 0 %.  Cost: 96 bp × base_weight × F
per state change of a book's suspension (on and off are each a change; a target switch is two).

THIRD OUTCOME.  A crisis window absent from the axis is reported "НЕ ИЗМЕРЕНО", never as a
zero drawdown.  Frozen books (zero return on the whole slice) are named: a book that never
moves cannot be a loser, so the breadth signal is computed on the live population only, and
that population is printed.

stdlib-only, deterministic, read-only (nothing written to disk), LLM FORBIDDEN.  The go-live
track is never opened; RiskPolicy v1.0, the kill-switch rungs and the 20 %/name ceiling are
untouched (equal weight over 10 books = 10 %/name).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edge_real_panel_ensemble as rpe  # noqa: E402

IS_ADVISORY: bool = True
OUTSIDE_RISKPOLICY: bool = True

TOLL = rpe.PLB_ROUNDTRIP          # 96 bp round trip, inherited
SPLIT = rpe.TRAIN_END             # 2025-06-30
WINDOWS = rpe.CRISIS_WINDOWS
GRID_W = (1, 3, 7, 14)
GRID_K = (2, 3, 4)
GRID_F = (0.5, 1.0)
MODES = ("redistribute", "cash")
PLACEBO_DRAWS = 2000
SEED = 168


def trailing_cum(r: Sequence[float], i: int, w: int) -> Optional[float]:
    """Sum of returns on days [i-w, i) — strictly before day i.  None if not enough history."""
    if i - w < 0:
        return None
    return sum(r[i - w:i])


def stress_and_target(rets: Dict[str, List[float]], live: Sequence[str], w: int, k: int,
                      n: int) -> Tuple[List[bool], List[Optional[str]]]:
    """Per day: is breadth >= k (causal), and the DCPS target (argmin of W-day trailing sum)."""
    stress: List[bool] = []
    target: List[Optional[str]] = []
    for i in range(n):
        cums = {b: trailing_cum(rets[b], i, w) for b in live}
        if any(v is None for v in cums.values()):
            stress.append(False)
            target.append(None)
            continue
        neg = [b for b, v in cums.items() if v < 0]
        if len(neg) >= k:
            stress.append(True)
            target.append(min(neg, key=lambda b: (cums[b], b)))
        else:
            stress.append(False)
            target.append(None)
    return stress, target


def run_portfolio(rets: Dict[str, List[float]], books: Sequence[str],
                  targets: Sequence[Optional[str]], f: float, mode: str) -> Tuple[List[float], int]:
    """Daily-rebalanced EW portfolio with per-day suspension of `targets[i]` by fraction f."""
    n = len(next(iter(rets.values())))
    base = 1.0 / len(books)
    out: List[float] = []
    changes = 0
    prev: Optional[str] = None
    for i in range(n):
        t = targets[i]
        w = {b: base for b in books}
        if t is not None:
            cut = base * f
            w[t] -= cut
            if mode == "redistribute":
                others = [b for b in books if b != t]
                for b in others:
                    w[b] += cut / len(others)
        r = sum(w[b] * rets[b][i] for b in books)
        n_chg = (prev is not None) + (t is not None) if t != prev else 0
        changes += n_chg
        r -= n_chg * TOLL * base * f
        out.append(r)
        prev = t
    return out, changes


def seg(series: Sequence[float], axis: Sequence[str], lo: Optional[str], hi: Optional[str],
        lo_excl: bool = False) -> List[float]:
    return [x for x, d in zip(series, axis)
            if (lo is None or (d > lo if lo_excl else d >= lo)) and (hi is None or d <= hi)]


def window_dd(series: Sequence[float], axis: Sequence[str]) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    for name, lo, hi in WINDOWS:
        s = seg(series, axis, lo, hi)
        out[name] = None if len(s) < 3 else abs(rpe.perf(s)["maxdd"])
    return out


def metrics(series: Sequence[float], axis: Sequence[str]) -> Dict[str, Dict[str, float]]:
    tr = seg(series, axis, None, SPLIT)
    te = seg(series, axis, SPLIT, None, lo_excl=True)
    out = {}
    for name, s in (("FULL", list(series)), ("TRAIN", tr), ("TEST", te)):
        p = rpe.perf(s)
        out[name] = {"apy": p["apy"], "maxdd": abs(p["maxdd"]),
                     "calmar": p["calmar"] if p["maxdd"] < 0 else float("inf"), "days": len(s)}
    return out


def fp_share(stress: Sequence[bool], axis: Sequence[str]) -> Tuple[int, int, int]:
    """(stress days outside every crisis window, stress days inside, days outside)."""
    def inside(d: str) -> bool:
        return any(lo <= d <= hi for _, lo, hi in WINDOWS)
    out_s = sum(1 for s, d in zip(stress, axis) if s and not inside(d))
    in_s = sum(1 for s, d in zip(stress, axis) if s and inside(d))
    out_days = sum(1 for d in axis if not inside(d))
    return out_s, in_s, out_days


def analyse(panel_dir: Path) -> Tuple[Dict, Dict[str, List[float]], List[str], List[str], List[str]]:
    axis, rets, books = rpe.plb_load(panel_dir)
    n = len(axis)
    live, frozen = rpe.live_breadth(axis, rets, books)
    te_lo = sum(1 for d in axis if d <= SPLIT)
    live_te, frozen_te = rpe.live_breadth(axis, rets, books, lo=te_lo)
    train_rets = {b: seg(rets[b], axis, None, SPLIT) for b in books}
    fixed_target = max(books, key=lambda b: (abs(rpe.perf(train_rets[b])["maxdd"]), b))

    base_series, _ = run_portfolio(rets, books, [None] * n, 0.0, "cash")
    res = {"axis": (axis[0], axis[-1], n), "books": books, "live_full": live,
           "frozen_full": frozen, "live_test": live_te, "frozen_test": frozen_te,
           "fixed_target": fixed_target,
           "baseline": {"m": metrics(base_series, axis), "win": window_dd(base_series, axis)},
           "cells": []}

    for w in GRID_W:
        for k in GRID_K:
            stress, dtarget = stress_and_target(rets, live, w, k, n)
            fp = fp_share(stress, axis)
            for f in GRID_F:
                for mode in MODES:
                    d_ser, d_chg = run_portfolio(rets, books, dtarget, f, mode)
                    c_tg = [fixed_target if s else None for s in stress]
                    c_ser, c_chg = run_portfolio(rets, books, c_tg, f, mode)
                    res["cells"].append({
                        "W": w, "K": k, "F": f, "mode": mode, "fp": fp,
                        "dcps": {"m": metrics(d_ser, axis), "win": window_dd(d_ser, axis),
                                 "changes": d_chg},
                        "cps": {"m": metrics(c_ser, axis), "win": window_dd(c_ser, axis),
                                "changes": c_chg},
                        "_stress": stress})
    return res, rets, books, axis, live


def placebo(rets, books, axis, live, stress, f, mode, draws=PLACEBO_DRAWS):
    rng = random.Random(SEED)
    te_cal, tr_cal = [], []
    n = len(axis)
    for _ in range(draws):
        tg: List[Optional[str]] = []
        cur: Optional[str] = None
        for i in range(n):
            if stress[i]:
                if cur is None:
                    cur = rng.choice(list(live))
                tg.append(cur)
            else:
                cur = None
                tg.append(None)
        s, _ = run_portfolio(rets, books, tg, f, mode)
        m = metrics(s, axis)
        te_cal.append(m["TEST"]["calmar"])
        tr_cal.append(m["TRAIN"]["calmar"])
    return tr_cal, te_cal


def pctile(x: float, dist: Sequence[float]) -> float:
    return 100.0 * sum(1 for v in dist if v < x) / len(dist)


def _fmt_m(m: Dict[str, float]) -> str:
    cal = "∞" if m["calmar"] == float("inf") else f"{m['calmar']:.2f}"
    return f"APY {m['apy']*100:+.2f}% · maxDD {m['maxdd']*100:.2f}% · Calmar {cal} · {m['days']} д"


def _fmt_w(win: Dict[str, Optional[float]]) -> str:
    return " · ".join(f"{k} {'НЕ ИЗМЕРЕНО' if v is None else f'{v*100:.2f}%'}" for k, v in win.items())


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--panel-dir", type=Path, default=rpe.PANEL_DIR)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        res, rets, books, axis, live = analyse(a.panel_dir)
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2

    base = res["baseline"]
    b_te = base["m"]["TEST"]["calmar"]
    cells = res["cells"]

    def beats_all_windows(c, key):
        return all(c[key]["win"][wn] is not None and base["win"][wn] is not None
                   and c[key]["win"][wn] < base["win"][wn] for wn, _, _ in WINDOWS)

    def train_cal(c, key):
        return c[key]["m"]["TRAIN"]["calmar"]

    best_d = max(cells, key=lambda c: (train_cal(c, "dcps"), -c["W"], -c["K"]))
    best_c = max(cells, key=lambda c: (train_cal(c, "cps"), -c["W"], -c["K"]))
    tr_cal, te_cal = placebo(rets, books, axis, live, best_d["_stress"], best_d["F"], best_d["mode"])

    summary = {
        "axis": res["axis"], "live_full": res["live_full"], "frozen_full": res["frozen_full"],
        "live_test": res["live_test"], "frozen_test": res["frozen_test"],
        "fixed_target": res["fixed_target"], "baseline": base,
        "dcps_cells_beat_base_test": sum(1 for c in cells if c["dcps"]["m"]["TEST"]["calmar"] > b_te),
        "cps_cells_beat_base_test": sum(1 for c in cells if c["cps"]["m"]["TEST"]["calmar"] > b_te),
        "dcps_cells_all_windows": sum(1 for c in cells if beats_all_windows(c, "dcps")),
        "dcps_cells_all_windows_and_test": sum(
            1 for c in cells if beats_all_windows(c, "dcps")
            and c["dcps"]["m"]["TEST"]["calmar"] >= b_te),
        "n_cells": len(cells),
        "best_dcps_by_train": {k: best_d[k] for k in ("W", "K", "F", "mode", "fp", "dcps", "cps")},
        "best_cps_by_train": {k: best_c[k] for k in ("W", "K", "F", "mode", "fp", "cps")},
        "placebo": {"draws": PLACEBO_DRAWS,
                    "dcps_test_calmar_pctile": pctile(best_d["dcps"]["m"]["TEST"]["calmar"], te_cal),
                    "dcps_train_calmar_pctile": pctile(best_d["dcps"]["m"]["TRAIN"]["calmar"], tr_cal),
                    "placebo_test_calmar_median": sorted(te_cal)[len(te_cal) // 2]},
    }
    if a.json:
        print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
        return 0

    print(f"#168 DCPS — реальная панель {res['axis'][0]} … {res['axis'][1]} ({res['axis'][2]} д)")
    print(f"  живых книг (весь ряд): {len(res['live_full'])}  · замороженных: {res['frozen_full']}")
    print(f"  живых на TEST: {res['live_test']}  · замороженных на TEST: {res['frozen_test']}")
    print(f"  цель фикс-CPS (наиб. TRAIN maxDD): {res['fixed_target']}")
    for p in ("FULL", "TRAIN", "TEST"):
        print(f"  BASE {p:5}: {_fmt_m(base['m'][p])}")
    print(f"  BASE окна: {_fmt_w(base['win'])}")
    for label, c, key in (("DCPS*", best_d, "dcps"), ("CPS* ", best_c, "cps")):
        print(f"  {label} выбран по TRAIN: W={c['W']} K={c['K']} F={c['F']} mode={c['mode']}"
              f"  · стресс-дней вне окон/внутри/всего вне: {c['fp']}")
        for p in ("FULL", "TRAIN", "TEST"):
            print(f"    {p:5}: {_fmt_m(c[key]['m'][p])}")
        print(f"    окна: {_fmt_w(c[key]['win'])}")
    print(f"  ячеек, бьющих BASE по TEST Calmar: DCPS {summary['dcps_cells_beat_base_test']}/"
          f"{len(cells)} · CPS {summary['cps_cells_beat_base_test']}/{len(cells)}")
    print(f"  ячеек DCPS, улучшивших ВСЕ три окна: {summary['dcps_cells_all_windows']}/{len(cells)};"
          f" из них без ухудшения TEST Calmar: {summary['dcps_cells_all_windows_and_test']}")
    pl = summary["placebo"]
    print(f"  плацебо цели ({PLACEBO_DRAWS}): DCPS* TEST Calmar на {pl['dcps_test_calmar_pctile']:.1f}"
          f" перцентиле (медиана плацебо {pl['placebo_test_calmar_median']:.2f}); TRAIN —"
          f" {pl['dcps_train_calmar_pctile']:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
