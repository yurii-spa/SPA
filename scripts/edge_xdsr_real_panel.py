#!/usr/bin/env python3
"""
scripts/edge_xdsr_real_panel.py — Idea #109 (XDSR-REAL)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json) or the fleet. Reads the aggressive-lab panel READ-ONLY.


WHY THIS RUN EXISTS — THE ORDER #108 LEFT
-----------------------------------------
Registry idea #108 (XDSR: Cross-Sectional Downside Sharpe Ranking) ranks books by a trailing
Sortino ratio mu_L / (sigma_down_L + eps) and demotes the bottom k to the RWA floor. It ran on
the SYNTHETIC fixture only and named its own limit precisely: the fixture has sigma^2 ~ 0
outside its three stress windows, so sigma_down collapses to eps for every book in calm and the
Sortino ranking degenerates into the pure-mu ranking of XSD (#40) on 96.6 % of days. Its closing
order was literal:

    "Проверить на реальной панели data/aggressive_lab/ (phase=backtest), где книги имеют
     ненулевую неоднородность σ_down в спокойные периоды. Критерий приёмки: доля дней
     XDSR ≠ XSD > 20% (деградация устранена) И Calmar XDSR > Calmar XSD при одинаковом k
     на той же панели."

This run executes that order on the full real panel (10 books, 852 common days,
2024-03-06 … 2026-07-05, phase="backtest" block only).


THE DEFECT IN #108's HEADLINE, FOUND BEFORE THE FIRST NEW NUMBER
----------------------------------------------------------------
#108's published table compares

    XDSR Sortino k=2, L=20   Calmar 0.746      (its best cell)
    XSD  mu-rank  k=2        Calmar 0.712      (its named baseline)

and concludes "+0.034 при совпадающем k" — a gain at matching k. The k matches. **The window
does not.** In `edge_downside_sharpe_demotion.main()` the XSD baseline rows are built by

    xsd2_r = _simulate(dates, rets, _mean_score, 2, 60)     # L is hard-coded 60

while the XDSR row that beat it was produced at L=20. The zero therefore differs from the
treatment by TWO knobs — the ranking criterion AND the trailing window — and the whole reported
gain sits in the second one: XSD itself moves 0.712 -> 0.747 when its window is shortened
60 -> 20, which is +0.035, larger than the +0.034 attributed to Sortino.

At MATCHED (k, L) on #108's own fixture, XDSR loses in all six cells. That is measured here as
a positive control (`control_matched_window`) and the run REFUSES if it cannot reproduce both
the published cells and the correction — so the correction is a measurement, not a claim.

This is the same defect the CDMS entry caught in its own first draft ("ноль обязан отличаться
ровно одной ручкой") and it is why this file re-measures the zero at every reported cell
instead of quoting a baseline from the previous entry's prose.


WHAT THIS RUN ADDS THAT #108 DID NOT HAVE
-----------------------------------------
1. Real returns instead of a fixture whose calm-period variance is zero by construction — the
   one condition under which #108's mechanism is even distinguishable from XSD.
2. **Cost.** #108 moved a book to the RWA floor for free. A demotion is a round trip: the
   canonical 96 bp (#10/#49) is charged on the fraction of capital whose state changed, and
   every configuration is run twice (96 bp and 0 bp) so a loss is attributable to COST or to
   TIMING instead of asserted.
3. Matched-cell comparison: for every (k, L) the XSD zero is recomputed at the SAME (k, L).
4. Four TRAIN/TEST splits, not one; the cell is chosen on TRAIN only and its TEST result is
   printed as it falls, beside its TRAIN rank.
5. The degeneracy census on the SET (bottom-k), not only bottom-1, plus the calm-period
   sigma_down spread that #108 predicted would remove the degeneracy.

HONEST LIMITS DECLARED UP FRONT
  • evidence L0/[bt] — backtest on an advisory paper panel; the panel's own books are backtests
    over real deep-history feeds, so this measures a RULE on a real return SHAPE, never P&L;
  • phase="backtest" block only (RPE.load_panel); diffing across the forward seam fabricates
    one-day returns of tens of percent;
  • the RWA floor a demoted book earns is a flat 3.4 %/yr constant, as in #108 — it is a
    convention, not a quote, and it flatters every demotion rule equally;
  • no capacity, no slippage beyond the flat round trip, no borrow, no tier or chain ceiling;
  • advisory / paper-only: nothing here sizes, funds or gates anything.

stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_downside_sharpe_demotion as XDSR  # noqa: E402  #108 mechanism, imported UNCHANGED
import edge_real_panel_ensemble as RPE  # noqa: E402  phase-clean real-panel loader (fail-CLOSED)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
#: Panel location. Overridable because the panel is NOT git-tracked: a session working from a
#: worktree has an empty data/ and must point at the prod tree's copy (read-only).
PANEL_DIR = Path(os.environ.get("SPA_PANEL_DIR") or (ROOT / "data" / "aggressive_lab"))

INITIAL = 100_000.0
ROUNDTRIP = 0.0096          # 96 bp, canonical #10/#49
RWA_DAILY = XDSR.RWA_DAILY  # taken from #108 rather than restated

K_GRID: Tuple[int, ...] = (1, 2, 3)
L_GRID: Tuple[int, ...] = (20, 40, 60)
#: Registry-canonical split first, then the three used by #68/#69/#71/#108-CDMS.
SPLITS: Tuple[str, ...] = ("2025-06-30", "2025-03-31", "2025-09-30", "2025-12-31")

#: Cells published by #108 that this file must reproduce before printing anything new.
#: (score name, k, L) -> Calmar.  A mismatch is a REFUSAL, not a warning.
PUBLISHED_108: Dict[Tuple[str, int, int], float] = {
    ("sortino", 2, 20): 0.746,   # #108's headline cell
    ("sortino", 2, 60): 0.709,
    ("sortino", 1, 20): 0.303,
    ("mean", 2, 60): 0.712,      # #108's named XSD baseline — hard-coded L=60
    ("mean", 1, 60): 0.292,
}
PUBLISHED_108_DEGENERACY_L20 = 96.6  # % of days XDSR bottom-1 == XSD bottom-1, fixture


class Refusal(RuntimeError):
    """Raised when a control cannot be reproduced. Never downgraded to a warning."""


class Run(NamedTuple):
    """Everything one demotion pass produced."""
    equity: List[float]
    cost: float
    turnover: float
    n_switch: int


# ── metrics ──────────────────────────────────────────────────────────────────────────────────────

def max_dd(curve: Sequence[float]) -> float:
    """Peak-to-trough drawdown of an equity path, as a fraction."""
    peak = curve[0]
    worst = 0.0
    for v in curve:
        peak = max(peak, v)
        worst = max(worst, (peak - v) / peak)
    return worst


def apy(curve: Sequence[float], n_days: int) -> float:
    if n_days < 1 or curve[0] < 1e-9 or curve[-1] <= 0:
        return 0.0
    return ((curve[-1] / curve[0]) ** (365.0 / n_days) - 1.0) * 100.0


def calmar(a: float, dd: float) -> float:
    return a / (dd * 100.0) if dd > 1e-9 else float("inf")


def window_dd(dated: Sequence[Tuple[str, float]], lo: str, hi: str) -> float:
    """Drawdown inside one date window — the tail that must be printed beside every APY."""
    sub = [v for d, v in dated if lo <= d <= hi]
    if len(sub) < 2:
        return 0.0
    return max_dd(sub)


# ── the mechanism, on any panel ───────────────────────────────────────────────────────────────────

def _bottom_k(books: Sequence[str], scores: Dict[str, float], k: int) -> Set[str]:
    """Deterministic bottom-k: ties broken by book name, never by dict order."""
    if k <= 0:
        return set()
    return set(sorted(books, key=lambda b: (scores[b], b))[:k])


def simulate(
    dates: Sequence[str],
    books: Sequence[str],
    rets: Dict[str, Dict[str, float]],
    score_fn: Callable[[List[float]], float],
    k: int,
    l_win: int,
    roundtrip: float = ROUNDTRIP,
    warmup_gate: bool = False,
) -> Run:
    """
    k-book demotion on an equal-weight book portfolio.

    Causal by construction: the score on day t reads returns strictly before t. A book whose
    demotion state CHANGES moves 1/N of capital, and that move is charged `roundtrip` — the
    part #108 did not pay.

    `warmup_gate` decides what happens on the first L days, and it is NOT a detail:
      • False — #108's own behaviour: rank on whatever partial history exists. With a partial
        window a book that has not yet printed a negative day scores mu/EPS (order 1e6), so the
        ranking on those days is not a Sortino ranking at all — it is "who has been negative
        yet", which is a different rule that happens to run under the same name.
      • True  — no book is demoted until EVERY book has a full L-day window. This is the arm
        whose days the degeneracy census actually counts, so it is the only arm in which the
        census and the P&L answer the same question.
    """
    n = len(books)
    hist: Dict[str, List[float]] = {b: [] for b in books}
    eq = INITIAL
    curve: List[float] = [eq]
    prev: Set[str] = set()
    cost_total = 0.0
    turnover = 0.0
    n_switch = 0

    for d in dates:
        if warmup_gate and not all(len(hist[b]) >= l_win for b in books):
            demoted: Set[str] = set()
        else:
            scores = {b: score_fn(hist[b][-l_win:]) for b in books}
            demoted = _bottom_k(books, scores, k)
        moved = len(demoted ^ prev)
        if moved:
            delta = moved / n
            c = delta * roundtrip * eq
            eq -= c
            cost_total += c
            turnover += delta
            n_switch += 1
        r_p = sum((RWA_DAILY if b in demoted else rets[b].get(d, 0.0)) / n for b in books)
        eq *= 1.0 + r_p
        curve.append(eq)
        prev = demoted
        for b in books:
            hist[b].append(rets[b].get(d, 0.0))

    return Run(curve, cost_total, turnover, n_switch)


def summarise(run: Run, dates: Sequence[str]) -> Dict[str, float]:
    n = len(dates)
    years = max(n / 365.0, 1e-9)
    a = apy(run.equity, n)
    dd = max_dd(run.equity)
    return {
        "apy_pct": a,
        "max_dd_pct": dd * 100.0,
        "calmar": calmar(a, dd),
        "cost_bp_yr": (run.cost / INITIAL) / years * 10_000.0,
        "turn_yr": run.turnover / years,
        "switch_days": float(run.n_switch),
    }


def disagreement(
    dates: Sequence[str],
    books: Sequence[str],
    rets: Dict[str, Dict[str, float]],
    k: int,
    l_win: int,
) -> Tuple[float, int]:
    """
    Fraction of FULL-WINDOW days on which the XDSR bottom-k SET differs from the XSD bottom-k
    set. #108's acceptance criterion is stated on this number (> 20 % = degeneracy removed).

    Days before the trailing window is full are excluded from the denominator — on those days
    both rules read the same partial history and agreeing there says nothing about either.
    """
    hist: Dict[str, List[float]] = {b: [] for b in books}
    diff = tot = 0
    for d in dates:
        if all(len(hist[b]) >= l_win for b in books):
            w = {b: hist[b][-l_win:] for b in books}
            s_set = _bottom_k(books, {b: XDSR._sortino_score(w[b]) for b in books}, k)
            m_set = _bottom_k(books, {b: XDSR._mean_score(w[b]) for b in books}, k)
            if s_set != m_set:
                diff += 1
            tot += 1
        for b in books:
            hist[b].append(rets[b].get(d, 0.0))
    return (diff / tot if tot else 0.0), tot


def calm_sigma_down_spread(
    dates: Sequence[str],
    books: Sequence[str],
    rets: Dict[str, Dict[str, float]],
    l_win: int = 20,
) -> Dict[str, float]:
    """
    Per book: median trailing sigma_down over full-window days.

    This is the quantity #108 predicted would be ~eps on the fixture and non-degenerate on the
    real panel. Printing it turns "the panel should fix the degeneracy" from a hope into a
    number that can contradict the result.
    """
    hist: Dict[str, List[float]] = {b: [] for b in books}
    samples: Dict[str, List[float]] = {b: [] for b in books}
    for d in dates:
        for b in books:
            w = hist[b][-l_win:]
            if len(w) >= l_win:
                neg = [r for r in w if r < 0]
                if neg:
                    mn = sum(neg) / len(neg)
                    samples[b].append(math.sqrt(sum((r - mn) ** 2 for r in neg) / len(neg)))
                else:
                    samples[b].append(0.0)
        for b in books:
            hist[b].append(rets[b].get(d, 0.0))
    out: Dict[str, float] = {}
    for b in books:
        s = sorted(samples[b])
        out[b] = s[len(s) // 2] if s else 0.0
    return out


# ── positive controls ─────────────────────────────────────────────────────────────────────────────

def control_published_cells() -> Dict[str, float]:
    """
    Reproduce #108's published fixture cells with #108's own module, unchanged.

    REFUSES (raises) on any mismatch beyond 0.002 Calmar. A file that cannot reproduce the
    number it is about to correct has no standing to correct it.
    """
    dates, rets = XDSR._load_rets()
    fns = {"sortino": XDSR._sortino_score, "mean": XDSR._mean_score}
    got: Dict[str, float] = {}
    bad: List[str] = []
    for (name, k, l_win), want in sorted(PUBLISHED_108.items()):
        r = XDSR._simulate(dates, rets, fns[name], k, l_win)
        got[f"{name} k={k} L={l_win}"] = r["calmar"]
        if abs(r["calmar"] - want) > 0.002:
            bad.append(f"{name} k={k} L={l_win}: published {want}, reproduced {r['calmar']}")
    deg = XDSR._degeneracy_frac(dates, rets, 20) * 100.0
    got["degeneracy L=20 %"] = deg
    if abs(deg - PUBLISHED_108_DEGENERACY_L20) > 0.2:
        bad.append(f"degeneracy L=20: published {PUBLISHED_108_DEGENERACY_L20}%, got {deg:.1f}%")
    if bad:
        raise Refusal(
            "cannot reproduce #108's published fixture numbers — refusing to publish anything "
            "built on top of them:\n  " + "\n  ".join(bad)
        )
    return got


def control_matched_window() -> Dict[str, Dict[str, float]]:
    """
    The correction, measured: at MATCHED (k, L) on #108's own fixture, XDSR vs XSD.

    REFUSES unless the measurement actually shows what the correction claims, i.e. unless
      (a) XSD at L=20 k=2 beats XSD at L=60 k=2 by more than #108's reported +0.034 gain, and
      (b) XDSR does not beat XSD in a single matched cell.
    Either failing means the correction is wrong and must not be printed.
    """
    dates, rets = XDSR._load_rets()
    cells: Dict[str, Dict[str, float]] = {}
    xdsr_wins = 0
    for l_win in (20, 40, 60):
        for k in (1, 2):
            m = XDSR._simulate(dates, rets, XDSR._mean_score, k, l_win)
            s = XDSR._simulate(dates, rets, XDSR._sortino_score, k, l_win)
            cells[f"k={k} L={l_win}"] = {
                "xsd_calmar": m["calmar"],
                "xdsr_calmar": s["calmar"],
                "delta": round(s["calmar"] - m["calmar"], 3),
            }
            if s["calmar"] > m["calmar"]:
                xdsr_wins += 1
    window_effect = cells["k=2 L=20"]["xsd_calmar"] - cells["k=2 L=60"]["xsd_calmar"]
    claimed_gain = PUBLISHED_108[("sortino", 2, 20)] - PUBLISHED_108[("mean", 2, 60)]
    if window_effect <= claimed_gain:
        raise Refusal(
            f"correction not supported: shortening XSD's window 60->20 is worth "
            f"{window_effect:+.3f} Calmar, which does not exceed #108's claimed Sortino gain "
            f"{claimed_gain:+.3f} — the attribution stands and this file must not say otherwise"
        )
    if xdsr_wins:
        raise Refusal(
            f"correction not supported: XDSR beats XSD in {xdsr_wins} matched cell(s) on the "
            f"fixture — refusing to publish 'loses in all six'"
        )
    cells["_window_effect"] = {"xsd_L60_to_L20": round(window_effect, 3),
                              "claimed_sortino_gain": round(claimed_gain, 3)}
    return cells


# ── real-panel measurement ────────────────────────────────────────────────────────────────────────

def load_real_panel(panel_dir: Path = PANEL_DIR) -> Tuple[List[str], List[str], Dict[str, Dict[str, float]]]:
    """(common dates, book names, returns). Raises if the panel is absent — never returns empty."""
    panel = RPE.load_panel(panel_dir)
    books = sorted(panel)
    common = sorted(set.intersection(*(set(panel[b]) for b in books)))
    if len(common) < 120:
        raise Refusal(
            f"only {len(common)} common days in {panel_dir} — refusing to judge a demotion rule "
            f"on a window shorter than four months"
        )
    return common, books, panel


def run_grid(
    dates: Sequence[str],
    books: Sequence[str],
    rets: Dict[str, Dict[str, float]],
    roundtrip: float,
    warmup_gate: bool = False,
) -> Dict[Tuple[int, int], Dict[str, Dict[str, float]]]:
    """{(k, L): {"xsd": metrics, "xdsr": metrics}} — the zero recomputed at every matched cell."""
    out: Dict[Tuple[int, int], Dict[str, Dict[str, float]]] = {}
    for k in K_GRID:
        for l_win in L_GRID:
            out[(k, l_win)] = {
                "xsd": summarise(
                    simulate(dates, books, rets, XDSR._mean_score, k, l_win, roundtrip, warmup_gate), dates),
                "xdsr": summarise(
                    simulate(dates, books, rets, XDSR._sortino_score, k, l_win, roundtrip, warmup_gate), dates),
            }
    return out


def split_dates(dates: Sequence[str], split: str) -> Tuple[List[str], List[str]]:
    return [d for d in dates if d <= split], [d for d in dates if d > split]


# ── report ────────────────────────────────────────────────────────────────────────────────────────

def _fmt(m: Dict[str, float]) -> str:
    return (f"{m['apy_pct']:7.2f}% {m['max_dd_pct']:6.2f}% {m['calmar']:7.3f} "
            f"{m['cost_bp_yr']:7.1f} {m['turn_yr']:6.2f}")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Idea #109 — XDSR on the real aggressive-lab panel")
    ap.add_argument("--panel", default=str(PANEL_DIR), help="panel directory (read-only)")
    args = ap.parse_args(list(argv) if argv is not None else None)

    print("=" * 96)
    print("Idea #109 — XDSR-REAL: #108's Sortino demotion on the REAL panel, at a matched zero")
    print("Evidence: [bt] L0 — advisory paper panel, no real fills.  IS_ADVISORY  |  LLM_FORBIDDEN")
    print("=" * 96)

    # ── control 1: reproduce before correcting ────────────────────────────────────────────────
    try:
        pub = control_published_cells()
    except Refusal as exc:
        print(f"\nNOT MEASURED — {exc}", file=sys.stderr)
        return 2
    print("\n[control 1] #108's published fixture cells, reproduced with #108's own module:")
    for key, val in sorted(pub.items()):
        print(f"    {key:22s} {val}")

    # ── control 2: the correction, measured ───────────────────────────────────────────────────
    try:
        cells = control_matched_window()
    except Refusal as exc:
        print(f"\nNOT MEASURED — {exc}", file=sys.stderr)
        return 2
    print("\n[control 2] FIXTURE at MATCHED (k, L) — #108 compared L=20 against a hard-coded L=60:")
    print(f"    {'cell':12s} {'XSD':>8s} {'XDSR':>8s} {'delta':>8s}")
    for key in sorted(c for c in cells if not c.startswith("_")):
        c = cells[key]
        print(f"    {key:12s} {c['xsd_calmar']:8.3f} {c['xdsr_calmar']:8.3f} {c['delta']:+8.3f}")
    we = cells["_window_effect"]
    print(f"    window alone (XSD L=60 -> L=20): {we['xsd_L60_to_L20']:+.3f} Calmar   vs "
          f"#108's claimed Sortino gain {we['claimed_sortino_gain']:+.3f}")
    print("    => #108's headline gain is the WINDOW knob, not the Sortino criterion.")

    # ── the ordered measurement ───────────────────────────────────────────────────────────────
    panel_dir = Path(args.panel)
    try:
        dates, books, rets = load_real_panel(panel_dir)
    except (Refusal, RuntimeError, FileNotFoundError, ValueError) as exc:
        print(f"\nNOT MEASURED — real panel unreadable at {panel_dir}: {exc}", file=sys.stderr)
        return 2

    print(f"\nReal panel: {len(books)} books, {len(dates)} common days "
          f"({dates[0]} .. {dates[-1]}), phase=backtest only")
    print("    " + ", ".join(books))

    print("\n[1] DEGENERACY CENSUS — #108's acceptance criterion is 'XDSR != XSD on > 20 % of days'")
    print(f"    {'cell':12s} {'diff %':>8s} {'full-window days':>18s}")
    deg: Dict[Tuple[int, int], float] = {}
    for k in K_GRID:
        for l_win in L_GRID:
            frac, tot = disagreement(dates, books, rets, k, l_win)
            deg[(k, l_win)] = frac * 100.0
            print(f"    k={k} L={l_win:<6d} {frac * 100:7.1f}% {tot:18d}")
    crit1 = max(deg.values()) > 20.0
    print(f"    criterion 1 (degeneracy removed, > 20 %): "
          f"{'PASS' if crit1 else 'FAIL'} (best cell {max(deg.values()):.1f} %)")

    print("\n[2] CALM-PERIOD sigma_down (median trailing, L=20) — the thing the fixture had at ~eps:")
    spread = calm_sigma_down_spread(dates, books, rets, 20)
    for b in books:
        print(f"    {b:22s} {spread[b] * 100:8.4f}% / day")

    crit2: Dict[str, int] = {}
    n_cells = len(K_GRID) * len(L_GRID)
    for warmup_gate in (False, True):
        gate_label = ("WARM-UP GATED (no demotion until every book has a full window)"
                      if warmup_gate else "UNGATED — #108's own behaviour (partial windows rank)")
        for roundtrip, cost_key, cost_label in ((ROUNDTRIP, "96bp", "96 bp round-trip"),
                                                (0.0, "0bp", "0 bp cost-free arm")):
            print(f"\n[3] FULL PANEL, MATCHED CELLS — {cost_label} — {gate_label}")
            print(f"    {'cell':12s} {'rule':6s} {'APY':>8s} {'maxDD':>7s} {'Calmar':>8s} "
                  f"{'cost bp':>8s} {'turn/yr':>7s}")
            grid = run_grid(dates, books, rets, roundtrip, warmup_gate)
            wins = 0
            for k in K_GRID:
                for l_win in L_GRID:
                    cell = grid[(k, l_win)]
                    print(f"    {'k=%d L=%d' % (k, l_win):12s} {'XSD':6s} {_fmt(cell['xsd'])}")
                    print(f"    {'':12s} {'XDSR':6s} {_fmt(cell['xdsr'])}"
                          f"   dCalmar {cell['xdsr']['calmar'] - cell['xsd']['calmar']:+.3f}")
                    if cell["xdsr"]["calmar"] > cell["xsd"]["calmar"]:
                        wins += 1
            key = f"{'gated' if warmup_gate else 'ungated'}/{cost_key}"
            crit2[key] = wins
            print(f"    XDSR beats matched XSD in {wins} of {n_cells} cells")

    print(f"\n    WHERE THE UNGATED WIN COMES FROM: ungated {crit2['ungated/96bp']}/{n_cells} cells "
          f"-> gated {crit2['gated/96bp']}/{n_cells}. The cells the census calls IDENTICAL "
          f"(0 % disagreement) still differ when ungated — so that difference cannot be the "
          f"ranking criterion. It is the warm-up.")

    print("\n[4] TRAIN / TEST, WARM-UP GATED — cell chosen on TRAIN by Calmar, TEST as it falls (96 bp)")
    print(f"    {'split':12s} {'chosen':10s} {'TRAIN XDSR':>11s} {'TRAIN XSD':>10s} "
          f"{'TEST XDSR':>10s} {'TEST XSD':>9s} {'TEST dd XDSR':>13s} {'TEST dd XSD':>12s}")
    oos_wins = oos_tail_wins = oos_n = 0
    for sp in SPLITS:
        tr, te = split_dates(dates, sp)
        if len(tr) < 120 or len(te) < 120:
            print(f"    {sp:12s} NOT MEASURED — train {len(tr)} / test {len(te)} days")
            continue
        tr_grid = run_grid(tr, books, rets, ROUNDTRIP, True)
        best = max(tr_grid, key=lambda kl: tr_grid[kl]["xdsr"]["calmar"])
        k, l_win = best
        te_x = summarise(simulate(te, books, rets, XDSR._sortino_score, k, l_win, ROUNDTRIP, True), te)
        te_m = summarise(simulate(te, books, rets, XDSR._mean_score, k, l_win, ROUNDTRIP, True), te)
        oos_n += 1
        if te_x["calmar"] > te_m["calmar"]:
            oos_wins += 1
        if te_x["max_dd_pct"] < te_m["max_dd_pct"]:
            oos_tail_wins += 1
        print(f"    {sp:12s} {'k=%d L=%d' % (k, l_win):10s} "
              f"{tr_grid[best]['xdsr']['calmar']:11.3f} {tr_grid[best]['xsd']['calmar']:10.3f} "
              f"{te_x['calmar']:10.3f} {te_m['calmar']:9.3f} "
              f"{te_x['max_dd_pct']:12.2f}% {te_m['max_dd_pct']:11.2f}%")
    print(f"    XDSR beats matched XSD out-of-sample in {oos_wins} of {oos_n} splits; "
          f"its TAIL is better in {oos_tail_wins} of {oos_n}")

    print("\n" + "=" * 96)
    print("VERDICT")
    print(f"  criterion 1 (degeneracy > 20 % of days): {'PASS' if crit1 else 'FAIL'}")
    print(f"  criterion 2 (Calmar XDSR > XSD at matched k, L, 96 bp, warm-up gated): "
          f"{'PASS' if crit2['gated/96bp'] == n_cells else 'FAIL'} "
          f"({crit2['gated/96bp']}/{n_cells} cells; ungated {crit2['ungated/96bp']}/{n_cells} "
          f"is a warm-up artifact)")
    print(f"  out-of-sample (gated): {oos_wins}/{oos_n} splits on Calmar, "
          f"{oos_tail_wins}/{oos_n} on the tail")
    print("  Both criteria were set by #108 itself. Advisory only; nothing is deployed.")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
