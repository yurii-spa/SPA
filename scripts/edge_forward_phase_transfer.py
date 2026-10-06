#!/usr/bin/env python3
"""#125 FPT + #126 ZRB — the forward block as an out-of-sample test, and the honest zero.

WHAT THE TWO SECTIONS ANSWER (both are standing ORDERS of the registry, not free invention)

  #125 FPT — Forward-Phase Transfer. Entry #124 ordered: "check whether the conclusion survives
    on the real sleeve, where level stationarity is NOT set by a generator". Entry #123 named the
    same limit about itself: its TRAIN->TEST transfer (spearman 0.874) "is explained by the
    persistence of the LEVELS of backtest books, and persistence of a backtest book's level may be
    a property of the generator rather than of the market". Every number of #122/#123/#124 was read
    off the `phase="backtest"` block. The series carry a SECOND block, `phase="forward"` (62 rows,
    2026-08-05..2026-10-05), produced by the live paper loop and not by the backtest generator.
    That block is the out-of-sample window those two entries said they did not have.

  #126 ZRB — Zero-Rebased accounting. Entry #123 ordered two things, both executed here:
    (1) re-measure at least one POSITIVE overlay of the registry against the honest zero of #122
        (EW over the live sleeve) rather than against EW-10, printing both deltas on one axis;
    (2) check whether the 76.8 % leak of the inverse-risk sizer survives when the dead legs are
        excluded EXPLICITLY, and reprint the #17 Calmar on the live sleeve.

THE DEFECT THIS FILE IS BUILT AROUND (and why `maxdd` may not be a float here)

  On the forward block seven of ten books have NOT ONE down day in 61 returns. For those books a
  drawdown of 0.000 % is true BY CONSTRUCTION: a monotone non-decreasing equity curve cannot draw
  down, so the zero is a property of the arithmetic, not an observation of the market. Reporting it
  as `maxdd = 0.0` would be exactly invariant #17 — "no observation" wearing the costume of
  "measured, and equal to zero" — and it would hand every such portfolio an INFINITE Calmar, which
  is how a 61-day accrual ledger gets published as a risk-adjusted optimum. So `drawdown_verdict`
  returns a THIRD outcome (`unmeasured_monotone`, maxdd None, calmar None, reason named) and the
  printer carries that word through to the page instead of a number.

  The same reason forbids gluing the two blocks: the forward block RESTARTS equity near $100k, so
  the seam is a +104.9 % / -83.5 % step that is an accounting discontinuity, not a return. The seam
  is MEASURED and printed (`seam_steps`) rather than asserted, so a reader can see the size of the
  thing the phase filter is protecting them from.

HONEST LIMITS, stated before any number is read
  * 61 returns. An annualised figure over 61 days is a PROJECTION of a window, not a measurement of
    a year; both are printed and the annualised one is labelled.
  * The window contains no stress event. It therefore cannot confirm a tail, only fail to find one.
  * Advisory only: IS_ADVISORY / OUTSIDE_RISKPOLICY. Nothing here moves capital, reads
    `data/equity_curve_daily.json`, or touches RiskPolicy v1.0.

Run:  python3 scripts/edge_forward_phase_transfer.py            # both sections
      python3 scripts/edge_forward_phase_transfer.py --json out.json
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
PANEL_DIR = ROOT / "data" / "aggressive_lab"
HARNESS = ROOT / "scripts" / "edge_real_panel_ensemble.py"

#: canonical round-trip toll (#10/#49). A STATIC subset pays it once, on day one.
ROUNDTRIP = 0.0096
#: per-name policy ceiling used across the project; equal weight over N names gives 1/N each.
POLICY_CAP = 0.20
#: a forward block shorter than this is refused rather than judged.
MIN_FORWARD_ROWS = 30
#: the backtest-era live sleeve MEASURED by #122. Re-measured here, never trusted as a constant.
ERA_SLEEVE_SOURCE = "#122 PLB, re-measured by forward_breadth() below"


def load_harness():
    """Import `scripts/edge_real_panel_ensemble.py` — the panel loader everything here reuses.

    Reused and NOT reimplemented on purpose: `perf`, `subset_perf`, `nleg_frontier`,
    `inverse_risk_weights`, `book_census`, `live_breadth`, `rank_spearman` are the instruments
    #122/#123 were measured with, and a second copy of them would make this entry's numbers
    incomparable with theirs by construction.
    """
    spec = importlib.util.spec_from_file_location("edge_real_panel_ensemble", HARNESS)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import the panel harness at {HARNESS}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ───────────────────────────── the forward block ─────────────────────────────
def forward_block(rows: Sequence[dict]) -> List[dict]:
    """Keep only the phase=="forward" rows, in date order — the mirror of `backtest_block`.

    The phase filter IS the protection against the seam. See `seam_steps` for its size.
    """
    keep = [r for r in rows if r.get("phase") == "forward"]
    keep.sort(key=lambda r: str(r.get("date") or r.get("as_of") or ""))
    return keep


def seam_steps(panel_dir: Path = PANEL_DIR) -> Dict[str, Optional[float]]:
    """Per book: the one-day "return" a phase-BLIND loader would read at the block boundary.

    This exists so the reason the two blocks are never diffed together is a printed number rather
    than a claim. A book missing either block gets None — never 0.0, which would read as "the
    blocks join smoothly" (inv. #17).
    """
    H = load_harness()
    out: Dict[str, Optional[float]] = {}
    for sub in sorted(panel_dir.glob("*/realized_series.jsonl")):
        rows = H._read_rows(sub)
        bt, fw = H.backtest_block(rows), forward_block(rows)
        if not bt or not fw:
            out[sub.parent.name] = None
            continue
        last, first = bt[-1].get("equity_usd"), fw[0].get("equity_usd")
        out[sub.parent.name] = None if not last or not first else float(first) / float(last) - 1.0
    return out


def load_forward_panel(panel_dir: Path = PANEL_DIR,
                       min_rows: int = MIN_FORWARD_ROWS) -> Dict[str, Dict[str, float]]:
    """{book: {date: daily_return}} over the phase=="forward" block of each book.

    Returns come from `equity_usd` (the authoritative marked equity) and are diffed only WITHIN
    the forward block. A book whose forward block is shorter than `min_rows` is dropped rather
    than padded; a panel with no usable book raises instead of returning {} (fail-CLOSED, so an
    empty panel can never be printed as a clean result).
    """
    H = load_harness()
    panel: Dict[str, Dict[str, float]] = {}
    for sub in sorted(panel_dir.glob("*/realized_series.jsonl")):
        dates, eq = H._equity_points(forward_block(H._read_rows(sub)))
        if len(dates) < min_rows:
            continue
        panel[sub.parent.name] = {dates[i]: eq[i] / eq[i - 1] - 1.0 for i in range(1, len(dates))}
    if not panel:
        raise RuntimeError(
            f"no book under {panel_dir} has a phase='forward' block of >= {min_rows} rows — "
            f"refusing to report a forward result that was never measured"
        )
    return panel


# ──────────────────── the third outcome: a drawdown that was never observed ────────────────────
def drawdown_verdict(returns: Sequence[float], *, eps: float = 1e-12) -> Dict[str, object]:
    """maxDD with its STATUS — `measured`, or `unmeasured_monotone` with maxdd/calmar = None.

    A series with no day below zero cannot draw down. Its 0.0 is therefore arithmetic, not
    observation, and handing it back as a float is how an accrual ledger acquires an infinite
    Calmar and gets published as a risk-adjusted optimum. Three outcomes stay distinguishable
    (inv. #17): measured · measured and equal to zero · not measured.

    A note on the branch below, corrected by a mutation control rather than by re-reading: the
    `else None` guard on the measured path is UNREACHABLE. `down_days >= 1` requires a return
    below -1e-12, and such a return always drops equity below the running peak by a representable
    amount, so a measured drawdown is always strictly positive in float64. An earlier version of
    this docstring advertised "measured and equal to zero" as a real third case; it is not one on
    this arithmetic. The guard stays as cheap defence and `test_a_series_with_a_down_day_...`
    pins the implication that makes it unreachable — so if it ever becomes reachable, that test
    says so instead of this comment quietly being wrong.
    """
    if not returns:
        return {"maxdd": None, "status": "unmeasured_empty", "down_days": None,
                "reason": "no returns at all — nothing was observed"}
    down = sum(1 for r in returns if r < -eps)
    H = load_harness()
    p = H.perf(returns)
    mdd = abs(p["maxdd"])
    if down == 0:
        return {
            "maxdd": None, "calmar": None, "status": "unmeasured_monotone",
            "down_days": 0, "apy": p["apy"], "vol": p["vol"],
            "reason": (f"{len(returns)} returns, not one below zero: a non-decreasing equity "
                       f"curve cannot draw down, so 0.0 here is arithmetic, not an observation"),
        }
    return {"maxdd": mdd, "calmar": (p["apy"] / mdd) if mdd > 0 else None,
            "status": "measured", "down_days": down,
            "apy": p["apy"], "vol": p["vol"], "reason": None}


def window_return(returns: Sequence[float]) -> float:
    """Compounded return over the window AS IT FELL — the primary figure for a 61-day block."""
    eq = 1.0
    for r in returns:
        eq *= 1.0 + r
    return eq - 1.0


def ew_series(books: Sequence[str], rets: Dict[str, Sequence[float]],
              lo: int, hi: int, *, roundtrip: float = 0.0) -> List[float]:
    """Equal-weight series over [lo, hi); `roundtrip` charged ONCE on day one (static subset)."""
    if not books:
        raise ValueError("empty book list — refusing to report a portfolio of nothing")
    k = list(books)
    series = [sum(rets[b][i] for b in k) / len(k) for i in range(lo, hi)]
    if roundtrip:
        series[0] -= roundtrip
    return series


def portfolio_verdict(books: Sequence[str], rets: Dict[str, Sequence[float]],
                      lo: int, hi: int, *, roundtrip: float = 0.0) -> Dict[str, object]:
    """Window return (WITH toll) + annualised projection + drawdown verdict (WITHOUT toll).

    THE DRAWDOWN IS JUDGED ON THE UNTOLLED SERIES, AND THAT IS NOT A CONVENIENCE.
    The canonical toll is charged once, on day one, as a -0.96 % first return. On a portfolio of
    monotone books that single entry is the ONLY day below zero, so a drawdown measured on the
    tolled series comes back `measured, 0.908 %` — a number which is my own fee read back to me as
    though the market had taken it. It would defeat the third outcome of `drawdown_verdict` with a
    down day this script itself manufactured. So: the RETURN is net of the toll (we really do pay
    it), and the DRAWDOWN question — "did the market ever take money away" — is asked of the
    series without it. Both are reported, and `maxdd_incl_toll` keeps the contaminated figure
    visible rather than dropping it.
    """
    series = ew_series(books, rets, lo, hi, roundtrip=roundtrip)
    clean = ew_series(books, rets, lo, hi, roundtrip=0.0)
    v = dict(drawdown_verdict(clean))
    tolled = drawdown_verdict(series)
    v["books"] = list(books)
    v["n_books"] = len(books)
    v["n_days"] = hi - lo
    v["window_return"] = window_return(series)
    v["window_return_ex_toll"] = window_return(clean)
    v["apy_projected"] = v.get("apy")
    v["maxdd_incl_toll"] = tolled.get("maxdd")
    v["toll_charged"] = roundtrip
    v["admissible_by_policy"] = (1.0 / len(books)) <= POLICY_CAP
    return v


# ───────────────────────────── §1 census: who moves, and when ─────────────────────────────
def monotone_census(panel: Dict[str, Dict[str, float]], *, eps: float = 1e-12) -> Dict[str, dict]:
    """Per book over the forward block: down / up / flat days, and whether maxDD is observable.

    This is the census the whole entry turns on. A book with `down_days = 0` is not a safe book;
    it is a book whose risk the window did not measure.
    """
    out: Dict[str, dict] = {}
    for book in sorted(panel):
        r = [panel[book][d] for d in sorted(panel[book])]
        down = sum(1 for x in r if x < -eps)
        up = sum(1 for x in r if x > eps)
        out[book] = {
            "returns": len(r), "down_days": down, "up_days": up,
            "flat_days": len(r) - down - up,
            "moves": down + up,
            "window_return": window_return(r),
            "maxdd_observable": down > 0,
            "worst_day": min(r) if r else None,
        }
    return out


def forward_breadth(census: Dict[str, dict], *, min_moves: int = 1) -> Tuple[List[str], List[str]]:
    """(live, frozen) over the forward block — liveness is a property of the days being judged."""
    live = [b for b, c in census.items() if c["moves"] >= min_moves]
    frozen = [b for b, c in census.items() if c["moves"] < min_moves]
    return sorted(live), sorted(frozen)


# ───────────── §2 composition chosen on the BACKTEST block, applied to the FORWARD block ─────────
def cross_phase_transfer(universe: Sequence[str], *, cap: float = 0.10,
                         panel_dir: Path = PANEL_DIR) -> Dict[str, object]:
    """Select the N-leg frontier on the BACKTEST block; apply each winner to the FORWARD block.

    Selection reads the backtest block ONLY — it cannot see the forward block, so this is a
    genuine out-of-sample application and not a re-fit. `universe` is an argument because the
    right universe is itself in question: #122 measured the live sleeve on the backtest era, and
    §1 above measures it again on the forward era, where it is NOT the same set.
    """
    H = load_harness()
    bt = H.load_panel(panel_dir)
    missing = [b for b in universe if b not in bt]
    if missing:
        raise RuntimeError(f"universe names absent from the backtest panel: {missing}")
    bt_axis = H.common_axis({b: bt[b] for b in universe})
    bt_rets = {b: [bt[b][d] for d in bt_axis] for b in universe}

    fw = load_forward_panel(panel_dir)
    fw_missing = [b for b in universe if b not in fw]
    if fw_missing:
        raise RuntimeError(f"universe names absent from the forward panel: {fw_missing}")
    fw_axis = sorted(set.intersection(*[set(fw[b]) for b in universe]))
    fw_rets = {b: [fw[b][d] for d in fw_axis] for b in universe}

    rows: List[dict] = []
    for n in range(1, len(universe) + 1):
        cand = []
        for sub in itertools.combinations(sorted(universe), n):
            tr = H.subset_perf(sub, bt_rets, 0, len(bt_axis), roundtrip=ROUNDTRIP)
            if tr["maxdd"] <= cap:
                cand.append((sub, tr))
        if not cand:
            rows.append({"n": n, "admitted": 0, "subset": None, "backtest": None, "forward": None,
                         "reason": f"no subset of size {n} has |backtest maxDD| <= {cap:.4f}"})
            continue
        best, best_tr = max(cand, key=lambda kv: kv[1]["apy"])
        fwd = portfolio_verdict(best, fw_rets, 0, len(fw_axis), roundtrip=ROUNDTRIP)
        all_fwd = {s: portfolio_verdict(s, fw_rets, 0, len(fw_axis), roundtrip=ROUNDTRIP)
                   for s, _ in cand}
        ordered = sorted((v["window_return"] for v in all_fwd.values()), reverse=True)
        rows.append({
            "n": n, "admitted": len(cand), "subset": list(best),
            "backtest": {"apy": best_tr["apy"], "maxdd": best_tr["maxdd"]},
            "forward": fwd,
            "forward_rank": ordered.index(fwd["window_return"]) + 1,
            "forward_median_window_return": statistics.median(ordered),
            "admissible_by_policy": (1.0 / n) <= POLICY_CAP,
            "reason": None,
        })
    return {"cap": cap, "universe": sorted(universe), "backtest_days": len(bt_axis),
            "forward_days": len(fw_axis), "rows": rows}


# ───────────────────── §3 (#126) the honest zero, and the sizer's leak ─────────────────────
def vol_regime_overlay(returns: Sequence[float], *, lookback: int = 20,
                       quantile: float = 0.70) -> List[bool]:
    """#1's flagship PRE-EMPTIVE de-risk: out while own trailing vol sits in its upper tail.

    Causal by construction — the window ends strictly BEFORE the day it judges, and the threshold
    is taken from the trailing window only, never from the whole series.
    """
    out: List[bool] = []
    for i in range(len(returns)):
        lo = max(0, i - lookback)
        win = list(returns[lo:i])
        if len(win) < 5:
            out.append(False)
            continue
        ref = sorted(abs(x) for x in win)
        thr = ref[min(len(ref) - 1, int(quantile * len(ref)))]
        out.append(abs(returns[i - 1]) > thr if i >= 1 else False)
    return out


def rebased_overlay_accounting(*, panel_dir: Path = PANEL_DIR,
                               lookback: int = 20, quantile: float = 0.70) -> Dict[str, object]:
    """ORDER #123 (1): one positive overlay, scored against BOTH zeros on one axis.

    The registry scored its overlays against EW-10. #122 measured that EW-10 parks 40 % of capital
    in books the lab had already killed, so a delta against it is partly a delta against cash. The
    acceptance criterion of the order is literally this: dCalmar vs EW-live printed beside dCalmar
    vs EW-10, both on the same axis.
    """
    H = load_harness()
    panel = H.load_panel(panel_dir)
    axis = H.common_axis(panel)
    books = sorted(panel)
    rets = {b: [panel[b][d] for d in axis] for b in books}

    census = H.book_census(panel_dir)
    lo, last_kill = H.post_kill_era(axis, census)
    live, frozen = H.live_breadth(axis, rets, books, lo=lo, hi=len(axis))

    def scored(sel: Sequence[str]) -> Dict[str, object]:
        base = ew_series(sel, rets, 0, len(axis), roundtrip=ROUNDTRIP)
        flags = vol_regime_overlay(base, lookback=lookback, quantile=quantile)
        over = H.apply_overlay(base, flags, safe_daily=0.0)
        pb, po = H.perf(base), H.perf(over)
        cb = pb["apy"] / abs(pb["maxdd"]) if pb["maxdd"] < 0 else None
        co = po["apy"] / abs(po["maxdd"]) if po["maxdd"] < 0 else None
        return {"books": list(sel), "n_books": len(sel),
                "base": {"apy": pb["apy"], "maxdd": abs(pb["maxdd"]), "calmar": cb},
                "overlay": {"apy": po["apy"], "maxdd": abs(po["maxdd"]), "calmar": co},
                "d_calmar": (co - cb) if (co is not None and cb is not None) else None,
                "derisk_duty": sum(1 for f in flags if f) / len(flags)}

    return {"axis_days": len(axis), "era_start_index": lo, "last_kill": last_kill,
            "live_sleeve": live, "frozen_sleeve": frozen,
            "overlay": {"kind": "pre-emptive trailing-vol de-risk (#1 flagship)",
                        "lookback": lookback, "quantile": quantile},
            "vs_ew10": scored(books), "vs_ew_live": scored(live)}


def sizer_leak(*, panel_dir: Path = PANEL_DIR, lookback: int = 30,
               kind: str = "sigma") -> Dict[str, object]:
    """ORDER #123 (2): does the inverse-risk sizer's leak into dead books survive exclusion?

    Measured twice on the same day and the same window: over the FULL book set (what #17 did) and
    over the live sleeve only. The second share is zero BY CONSTRUCTION, and the order asked for
    exactly that — so the number that matters is not the zero but what the exclusion does to the
    Calmar of the #17 row.
    """
    H = load_harness()
    panel = H.load_panel(panel_dir)
    axis = H.common_axis(panel)
    books = sorted(panel)
    rets = {b: [panel[b][d] for d in axis] for b in books}
    census = H.book_census(panel_dir)
    lo, _ = H.post_kill_era(axis, census)
    live, frozen = H.live_breadth(axis, rets, books, lo=lo, hi=len(axis))

    def run(sel: Sequence[str]) -> Dict[str, object]:
        series, leak = [], []
        wseries: Dict[str, List[float]] = {b: [] for b in sel}
        for i in range(lookback, len(axis)):
            w = H.inverse_risk_weights(rets, sel, end=i, lookback=lookback, kind=kind)
            series.append(sum(w[b] * rets[b][i] for b in sel))
            leak.append(sum(w[b] for b in sel if b in frozen))
            for b in sel:
                wseries[b].append(w[b])
        per_book = {b: statistics.mean(wseries[b]) for b in sel}
        top = max(per_book, key=lambda b: per_book[b])
        v = drawdown_verdict(series)
        # Calmar here is the #17 row, and on this panel it is DEGENERATE in both directions:
        # over all ten books maxDD lands at ~1e-7 (a 1/sigma sizer parks the capital in frozen
        # books, whose returns are exactly 0.0, so the series is a near-flat line) and the ratio
        # explodes to four digits; over the live sleeve maxDD is exactly 0.0 and the ratio is
        # undefined. #122 measured this degeneracy for subsets; it is the same defect here, so the
        # number is REFUSED with a named reason rather than printed as 0.000 or as 1283.
        return {"books": list(sel), "n_books": len(sel),
                "apy": v.get("apy"), "maxdd": v.get("maxdd"), "calmar": v.get("calmar"),
                "dd_status": v["status"], "dd_reason": v.get("reason"),
                "down_days": v.get("down_days"),
                "mean_weight_in_frozen": statistics.mean(leak),
                "max_weight_in_frozen": max(leak),
                # WHERE the weight goes once the frozen books are gone. This is the actual answer
                # to order 2: the share in dead books becomes zero BY CONSTRUCTION, but 1/sigma
                # maximises weight on whatever moved least, and on this panel "moved least" means
                # "was not measured", not "is safe". The pathology RELOCATES rather than clearing.
                "mean_weights": per_book,
                "top_name": top,
                "top_mean_weight": per_book[top],
                "top_name_down_days": sum(1 for x in rets[top] if x < -1e-12),
                "top_name_sigma": statistics.pstdev(rets[top]),
                "breaches_policy_cap": per_book[top] > POLICY_CAP}

    return {"lookback": lookback, "kind": kind, "frozen_sleeve": frozen,
            "all_books": run(books), "live_only": run(live)}


# ───────────────────────────────────── printing ─────────────────────────────────────
def _dd(v: Dict[str, object]) -> str:
    """maxDD for the page — the WORD when it was not observed, never a zero (inv. #17)."""
    if v.get("status") == "measured":
        return f"{float(v['maxdd']) * 100:6.3f}%"
    return "  NOT MEASURED"


def _num(x: Optional[float], width: int, *, sign: bool = False) -> str:
    """A float, or the WORD. `None` must never reach the page as 0.000 (inv. #17)."""
    if x is None:
        return "NOT MEASURED"
    return f"{x:+.3f}" if sign else f"{x:.3f}"


def run(panel_dir: Path = PANEL_DIR, *, verbose: bool = True) -> Dict[str, object]:
    H = load_harness()
    fw = load_forward_panel(panel_dir)
    census = monotone_census(fw)
    live, frozen = forward_breadth(census)
    seams = seam_steps(panel_dir)

    # the backtest-era sleeve, RE-MEASURED rather than copied from #122
    bt = H.load_panel(panel_dir)
    bt_axis = H.common_axis(bt)
    bt_books = sorted(bt)
    bt_rets = {b: [bt[b][d] for d in bt_axis] for b in bt_books}
    bt_lo, last_kill = H.post_kill_era(bt_axis, H.book_census(panel_dir))
    bt_live, bt_frozen = H.live_breadth(bt_axis, bt_rets, bt_books, lo=bt_lo, hi=len(bt_axis))

    fw_axis = sorted(set.intersection(*[set(fw[b]) for b in sorted(fw)]))
    fw_rets = {b: [fw[b][d] for d in fw_axis] for b in sorted(fw)}

    if verbose:
        print("=" * 100)
        print("#125 FPT — the FORWARD block as the out-of-sample window #123/#124 said they lacked")
        print("=" * 100)
        print(f"forward block: {len(fw_axis)} returns, {fw_axis[0]} .. {fw_axis[-1]}  "
              f"| backtest block: {len(bt_axis)} returns")
        print("\n§0 THE SEAM a phase-blind loader would read as one day's return "
              "(this is why the blocks are never diffed together):")
        for b, s in sorted(seams.items(), key=lambda kv: -abs(kv[1] or 0)):
            print(f"    {b:22s} {'NOT MEASURED' if s is None else f'{s * 100:+9.2f}%'}")

        print("\n§1 CENSUS of the forward block — who moves, and whose drawdown is OBSERVABLE:")
        print(f"    {'book':22s} {'ret':>9} {'down':>5} {'up':>4} {'flat':>5} {'worst day':>11}  maxDD")
        for b, c in sorted(census.items()):
            w = c["worst_day"]
            print(f"    {b:22s} {c['window_return'] * 100:+8.3f}% {c['down_days']:5d} "
                  f"{c['up_days']:4d} {c['flat_days']:5d} {w * 100:+10.4f}%  "
                  f"{'observable' if c['maxdd_observable'] else 'NOT MEASURED (monotone)'}")
        nobs = sum(1 for c in census.values() if not c["maxdd_observable"])
        print(f"\n    >>> {nobs} of {len(census)} books have NOT ONE down day in {len(fw_axis)} "
              f"returns: their 0.000% drawdown is arithmetic, not observation.")
        print(f"    forward-era live  ({len(live)}): {', '.join(live)}")
        print(f"    forward-era frozen({len(frozen)}): {', '.join(frozen) or '—'}")
        print(f"    backtest-era live ({len(bt_live)}): {', '.join(bt_live)}   [#122's sleeve, "
              f"re-measured; last kill {last_kill}]")
        moved = sorted(set(live) - set(bt_live))
        print(f"    >>> books FROZEN in the backtest era but MOVING in the forward era "
              f"({len(moved)}): {', '.join(moved) or '—'}")

        print(f"\n§2 BASELINES on the forward block (window return primary; annualised = PROJECTION "
              f"of {len(fw_axis)} days):")
        print(f"    {'portfolio':34s} {'window':>9} {'ann.(proj)':>11}  maxDD")
        for label, sel in [("EW-10 (registry zero)", bt_books),
                           ("EW-live6 (#122 honest zero, bt era)", bt_live),
                           ("EW-live (forward era)", live),
                           ("N=5 (#123 political optimum)", sorted(set(bt_live) - {"eth_directional"}))]:
            v = portfolio_verdict(sel, fw_rets, 0, len(fw_axis), roundtrip=ROUNDTRIP)
            ann = "NOT MEASURED" if v["apy_projected"] is None \
                else f"{v['apy_projected'] * 100:+9.2f}%"
            print(f"    {label:34s} {v['window_return'] * 100:+8.3f}% {ann:>10}  {_dd(v)}"
                  f"   (incl. day-one toll: "
                  f"{(v['maxdd_incl_toll'] or 0) * 100:.3f}%)")

    transfer = cross_phase_transfer(bt_live, cap=0.10, panel_dir=panel_dir)
    if verbose:
        print("\n§3 COMPOSITION CHOSEN ON THE BACKTEST BLOCK, APPLIED TO THE FORWARD BLOCK")
        print("    (selection = max backtest APY s.t. |backtest maxDD| <= 10 %; it never sees "
              "the forward block)")
        print(f"    {'N':>2} {'subset':52s} {'bt APY':>8} {'fwd win':>9} {'rank':>6}  maxDD")
        for r in transfer["rows"]:
            if r["admitted"] == 0:
                print(f"    {r['n']:2d} NOT MEASURED — {r['reason']}")
                continue
            names = ",".join(x[:11] for x in r["subset"])
            print(f"    {r['n']:2d} {names:52s} {r['backtest']['apy'] * 100:+7.2f}% "
                  f"{r['forward']['window_return'] * 100:+8.3f}% "
                  f"{r['forward_rank']:3d}/{r['admitted']:<2d}  {_dd(r['forward'])}"
                  f"{'' if r['admissible_by_policy'] else '   [> 20 %/name]'}")

    reb = rebased_overlay_accounting(panel_dir=panel_dir)
    leak = sizer_leak(panel_dir=panel_dir)
    if verbose:
        print("\n" + "=" * 100)
        print("#126 ZRB — the two standing ORDERS of #123, on the BACKTEST block (where marks exist)")
        print("=" * 100)
        print(f"\nORDER 1 — one positive overlay against BOTH zeros, same axis "
              f"({reb['axis_days']} days, overlay = {reb['overlay']['kind']}):")
        print(f"    {'zero':30s} {'base Calmar':>12} {'overlay Calmar':>15} {'dCalmar':>9} {'duty':>6}")
        for label, key in [("EW-10 (what the registry used)", "vs_ew10"),
                           ("EW-live (#122 honest zero)", "vs_ew_live")]:
            s = reb[key]
            cb, co, d = s["base"]["calmar"], s["overlay"]["calmar"], s["d_calmar"]
            print(f"    {label:30s} {_num(cb, 12):>12} {_num(co, 15):>15} "
                  f"{_num(d, 9, sign=True):>9} {s['derisk_duty'] * 100:5.1f}%")
            print(f"    {'':30s}   base {s['base']['apy'] * 100:+7.2f}%/"
                  f"{s['base']['maxdd'] * 100:5.2f}%   overlay "
                  f"{s['overlay']['apy'] * 100:+7.2f}%/{s['overlay']['maxdd'] * 100:5.2f}%")
        print("\nORDER 2 — inverse-risk sizer: does the leak into dead books survive exclusion?")
        print(f"    frozen books: {', '.join(leak['frozen_sleeve'])}")
        print(f"    {'universe':26s} {'APY':>8} {'maxDD':>7} {'Calmar':>8} {'mean w in frozen':>18}")
        for label, key in [("all 10 books (#17 row)", "all_books"), ("live sleeve only", "live_only")]:
            s = leak[key]
            mdd = "NOT MEASURED" if s["maxdd"] is None else f"{s['maxdd'] * 100:.4f}%"
            cal = "REFUSED (degenerate)" if s["calmar"] is None or abs(s["calmar"]) > 100 \
                else f"{s['calmar']:.3f}"
            print(f"    {label:26s} {s['apy'] * 100:+7.2f}% {mdd:>13} {cal:>22} "
                  f"{s['mean_weight_in_frozen'] * 100:7.1f}%")
            if s["dd_status"] != "measured" or s["calmar"] is None or abs(s["calmar"] or 0) > 100:
                print(f"    {'':26s}   why: {s['dd_reason'] or 'maxDD ~ 0 on a near-flat series '
                      '(the sizer parks capital in books whose returns are exactly 0.0)'}")
            print(f"    {'':26s}   heaviest name: {s['top_name']} at "
                  f"{s['top_mean_weight'] * 100:.2f}% mean weight "
                  f"(own sigma {s['top_name_sigma'] * 100:.5f}%, "
                  f"{s['top_name_down_days']} down days)"
                  f"{'  >>> BREACHES the 20 %/name cap' if s['breaches_policy_cap'] else ''}")
        print()

    return {"forward": {"axis": [fw_axis[0], fw_axis[-1]], "days": len(fw_axis),
                        "census": census, "live": live, "frozen": frozen,
                        "seam_steps": seams,
                        "monotone_books": [b for b, c in census.items()
                                           if not c["maxdd_observable"]]},
            "backtest_era": {"live": bt_live, "frozen": bt_frozen, "last_kill": last_kill,
                             "days": len(bt_axis)},
            "transfer": transfer, "rebased_overlay": reb, "sizer_leak": leak,
            "is_advisory": IS_ADVISORY, "outside_riskpolicy": OUTSIDE_RISKPOLICY}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    ap.add_argument("--panel-dir", default=str(PANEL_DIR))
    ap.add_argument("--json", help="write the full result to this path")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    res = run(Path(args.panel_dir), verbose=not args.quiet)
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
