"""
edge_cads_real.py — Idea #120 CADS-REAL: does #119's per-strategy drawdown stop survive the
REAL aggressive-lab panel?

#119 CADS was measured on the deterministic fixture only ([bt] [L0]) and said so. Its own
caveats named three things the fixture cannot answer: (a) real series have noise, so a 5 %
stop may fire on flutter, not on stress; (b) the first day of a stress window carries most of
the hit and a stop cannot avoid it; (c) no transaction cost was charged on stop / re-entry.
This file answers all three on the real 10-book panel (phase="backtest" block, the same
fail-CLOSED loader every real-panel entry since #16 uses) and splits the mechanism into its
two parts, which #119 measured only together:

  • the STOP   — leaving a wounded book (where does its slice go: cash / survivors);
  • the TARGET — sending the freed slice to the best rolling-Calmar survivor (#119's rule).

Arms (equal-weight book portfolio, daily-rebalanced, the convention of #108/#109):
  ew      — no stop (the baseline);
  cash    — stopped slice → RWA floor (RWA_DAILY, #108's conservative 3.4 %);
  spread  — stopped slice → spread equally over the active books;
  calmar  — stopped slice → the active book with the best rolling Calmar (#119 rule).

Causality (ADR-212 lesson, "the guard decided already knowing the day"): the stop / re-entry
decision on day t reads each book's standalone equity through t-1 only; the new weights earn
day t's return. Every change of the weight vector is charged ROUNDTRIP on half the L1 change
(a 1/n slice moved book→cash costs ROUNDTRIP × 1/n, identical to #109).

Out-of-sample discipline: ONE full causal run per cell; train = rows ≤ 2025-12-31, test = 2026
(the split the standing directive names). The cell is chosen on TRAIN Calmar only and its
TEST numbers are printed next to the EW test numbers — no cell is chosen by looking at test.

ADVISORY / OUTSIDE_RISKPOLICY / IS_ADVISORY=True. stdlib-only, no network, LLM FORBIDDEN.
Never imports spa_core.execution. Reads data/aggressive_lab read-only (SPA_PANEL_DIR).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import edge_real_panel_ensemble as RPE  # noqa: E402  phase-clean real-panel loader (fail-CLOSED)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
PANEL_DIR = Path(os.environ.get("SPA_PANEL_DIR") or (ROOT / "data" / "aggressive_lab"))

INITIAL = 100_000.0
ROUNDTRIP = 0.0096                 # 96 bp, canonical #10/#49
RWA_DAILY = 3.4 / 100.0 / 365.0    # #108's conservative floor
CALMAR_LOOKBACK = 60               # #119
TRAIN_END = "2025-12-31"           # standing directive: train 2024-2025 / test 2026

STOP_GRID: Tuple[float, ...] = (0.03, 0.05, 0.08, 0.10)
RE_GRID: Tuple[float, ...] = (0.01, 0.03)
MODES: Tuple[str, ...] = ("cash", "spread", "calmar")
HEADLINE_119 = ("calmar", 0.05, 0.03)   # #119's published cell, keyed (mode, stop, re)
CASH = "__cash__"


class Refusal(RuntimeError):
    """A precondition the measurement depends on is not met. Never downgraded to a warning."""


class Run(NamedTuple):
    dates: List[str]
    equity: List[float]          # equity[0] = INITIAL before dates[0]; equity[i+1] after dates[i]
    cost: float
    turnover: float
    stops: List[Tuple[str, str, float]]     # (date, book, dd at decision)
    reentries: List[Tuple[str, str, float]]
    avg_w: Dict[str, float]      # time-average weight per book (+ CASH) — feeds the tilt control


# ── metrics ──────────────────────────────────────────────────────────────────────────────────

def max_dd(curve: Sequence[float]) -> float:
    peak = -math.inf
    worst = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, 1.0 - v / peak)
    return worst


def apy(curve: Sequence[float], n_days: int) -> float:
    if n_days <= 0 or curve[0] <= 0 or curve[-1] <= 0:
        return 0.0
    return ((curve[-1] / curve[0]) ** (365.0 / n_days) - 1.0) * 100.0


def calmar(a_pct: float, dd: float) -> float:
    return a_pct / (dd * 100.0) if dd > 0 else float("inf") if a_pct > 0 else 0.0


def segment(run: Run, lo: Optional[str], hi: Optional[str]) -> Dict[str, float]:
    """Metrics of the slice of ONE causal run whose dates fall in [lo, hi]."""
    idx = [i for i, d in enumerate(run.dates) if (lo is None or d >= lo) and (hi is None or d <= hi)]
    if len(idx) < 30:
        raise Refusal(f"segment {lo}..{hi} has {len(idx)} days — refusing to print a metric on it")
    curve = [run.equity[idx[0]]] + [run.equity[i + 1] for i in idx]
    n = len(idx)
    a = apy(curve, n)
    dd = max_dd(curve)
    return {"apy_pct": a, "max_dd_pct": dd * 100.0, "calmar": calmar(a, dd), "days": float(n)}


def window_dd(run: Run, lo: str, hi: str) -> float:
    """Peak-to-trough inside a named crisis window, measured from the equity entering it."""
    idx = [i for i, d in enumerate(run.dates) if lo <= d <= hi]
    if not idx:
        return float("nan")
    curve = [run.equity[idx[0]]] + [run.equity[i + 1] for i in idx]
    return max_dd(curve) * 100.0


# ── rolling Calmar for the target choice (#119) ───────────────────────────────────────────────

def rolling_calmar(rets: Sequence[float]) -> float:
    """Calmar of the last CALMAR_LOOKBACK returns (already sliced by the caller). Causal: the
    caller passes returns strictly before the decision day."""
    if len(rets) < 5:
        return -math.inf
    eq = [1.0]
    for r in rets:
        eq.append(eq[-1] * (1.0 + r))
    a = (eq[-1] ** (365.0 / len(rets)) - 1.0) * 100.0
    dd = max_dd(eq)
    if dd <= 1e-12:
        return 1e6 + a          # never-negative window: ranks above any book that has had a loss
    return a / (dd * 100.0)


# ── the simulator ─────────────────────────────────────────────────────────────────────────────

def simulate(
    dates: Sequence[str],
    books: Sequence[str],
    rets: Dict[str, Dict[str, float]],
    stop: Optional[float],
    reentry: float,
    mode: str,
    roundtrip: float = ROUNDTRIP,
) -> Run:
    """stop=None ⇒ the EW baseline (no book is ever stopped)."""
    if mode not in MODES + ("ew",):
        raise Refusal(f"unknown mode {mode!r}")
    if stop is not None and not (0.0 < reentry < stop):
        raise Refusal(f"re-entry {reentry} must lie strictly inside (0, stop={stop})")
    n = len(books)
    s_eq = {b: 1.0 for b in books}      # standalone equity of each book, through t-1
    s_hwm = {b: 1.0 for b in books}
    hist: Dict[str, List[float]] = {b: [] for b in books}
    stopped: set = set()
    host: Dict[str, str] = {b: b for b in books}   # who carries book b's 1/n slice (calmar mode)
    w_prev: Dict[str, float] = {b: 1.0 / n for b in books}
    w_prev[CASH] = 0.0
    eq = INITIAL
    curve = [eq]
    cost = 0.0
    turnover = 0.0
    stops: List[Tuple[str, str, float]] = []
    reent: List[Tuple[str, str, float]] = []
    w_sum: Dict[str, float] = {k: 0.0 for k in list(books) + [CASH]}

    def best_active(exclude: set) -> Optional[str]:
        act = [b for b in books if b not in stopped and b not in exclude]
        if not act:
            return None
        return max(act, key=lambda b: (rolling_calmar(hist[b][-CALMAR_LOOKBACK:]), b))

    for d in dates:
        # 1) decide from information through t-1
        if stop is not None:
            for b in books:
                dd = 1.0 - s_eq[b] / s_hwm[b]
                if b not in stopped and dd >= stop:
                    stopped.add(b)
                    stops.append((d, b, dd))
                elif b in stopped and dd <= reentry:
                    stopped.discard(b)
                    reent.append((d, b, dd))
            # re-host every slice whose current host is not an active book
            for b in books:
                if b not in stopped:
                    host[b] = b
                elif host[b] == b or host[b] in stopped or host[b] == CASH:
                    tgt = best_active(set())
                    host[b] = tgt if tgt is not None else CASH
        # 2) weights
        w: Dict[str, float] = {b: 0.0 for b in books}
        w[CASH] = 0.0
        active = [b for b in books if b not in stopped]
        for b in books:
            if b not in stopped:
                w[b] += 1.0 / n
            elif not active or mode == "cash":
                w[CASH] += 1.0 / n
            elif mode == "spread":
                for a in active:
                    w[a] += 1.0 / n / len(active)
            else:  # calmar
                w[host[b] if host[b] != CASH else CASH] += 1.0 / n
        delta = 0.5 * sum(abs(w[k] - w_prev.get(k, 0.0)) for k in w)
        if delta > 1e-12:
            c = delta * roundtrip * eq
            eq -= c
            cost += c
            turnover += delta
        # 3) earn day t
        r_p = w[CASH] * RWA_DAILY + sum(w[b] * rets[b].get(d, 0.0) for b in books)
        eq *= 1.0 + r_p
        curve.append(eq)
        w_prev = w
        for k in w:
            w_sum[k] += w[k]
        # 4) observe day t for every book (stopped or not) — feeds tomorrow's decision
        for b in books:
            r = rets[b].get(d, 0.0)
            s_eq[b] *= 1.0 + r
            s_hwm[b] = max(s_hwm[b], s_eq[b])
            hist[b].append(r)
    nd = max(len(dates), 1)
    return Run(list(dates), curve, cost, turnover, stops, reent, {k: v / nd for k, v in w_sum.items()})


def static_mix(dates: Sequence[str], books: Sequence[str], rets: Dict[str, Dict[str, float]],
               weights: Dict[str, float]) -> Run:
    """Fixed weights, daily-rebalanced, NO cost — the matched-exposure control. If a CADS arm
    is no better than the static mix holding its own time-average weights, its edge is the
    TILT (which book it ended up in), not the stop (when it left)."""
    eq = INITIAL
    curve = [eq]
    for d in dates:
        r = weights.get(CASH, 0.0) * RWA_DAILY + sum(weights.get(b, 0.0) * rets[b].get(d, 0.0) for b in books)
        eq *= 1.0 + r
        curve.append(eq)
    return Run(list(dates), curve, 0.0, 0.0, [], [], dict(weights))


def load_real_panel(panel_dir: Path = PANEL_DIR) -> Tuple[List[str], List[str], Dict[str, Dict[str, float]]]:
    if not panel_dir.is_dir():
        raise Refusal(f"panel dir {panel_dir} absent — НЕ ИЗМЕРЕНО (set SPA_PANEL_DIR)")
    panel = RPE.load_panel(panel_dir)
    books = sorted(panel)
    common = sorted(set.intersection(*(set(panel[b]) for b in books)))
    if len(common) < 120:
        raise Refusal(f"only {len(common)} common days in {panel_dir}")
    return common, books, panel


EW_KEY = ("ew", 0.0, 0.0)


def run_all(dates, books, rets, roundtrip=ROUNDTRIP) -> Dict[Tuple[str, float, float], Run]:
    out = {EW_KEY: simulate(dates, books, rets, None, 0.0, "ew", roundtrip)}
    for mode in MODES:
        for s in STOP_GRID:
            for r in RE_GRID:
                if r < s:
                    out[(mode, s, r)] = simulate(dates, books, rets, s, r, mode, roundtrip)
    return out


def pick_on_train(runs: Dict[Tuple[str, float, float], Run]) -> Tuple[str, float, float]:
    cand = [(k, segment(v, None, TRAIN_END)["calmar"]) for k, v in runs.items() if k[0] != "ew"]
    return max(cand, key=lambda kv: (kv[1], str(kv[0])))[0]


def out_through(run: Run, start: str) -> List[str]:
    """Books that are stopped on `start` and never re-entered afterwards — replayed from the
    run's own event log in date order (a stop and a re-entry are never on the same day)."""
    events = sorted([(d, 1, b) for d, b, _ in run.stops] + [(d, 0, b) for d, b, _ in run.reentries])
    state: Dict[str, bool] = {}
    for d, is_stop, b in events:
        if d >= start:
            break
        state[b] = bool(is_stop)
    later_re = {b for d, b, _ in run.reentries if d >= start}
    return sorted(b for b, out in state.items() if out and b not in later_re)


LOO_DROP: Tuple[str, ...] = ("pendle_yt_susde", "pendle_pt_levered")


def book_segment(dates: Sequence[str], rets: Dict[str, Dict[str, float]], b: str,
                 lo: Optional[str], hi: Optional[str]) -> Dict[str, float]:
    eq = [INITIAL]
    for d in dates:
        eq.append(eq[-1] * (1.0 + rets[b].get(d, 0.0)))
    return segment(Run(list(dates), eq, 0.0, 0.0, [], [], {}), lo, hi)


def _fmt(m: Dict[str, float]) -> str:
    return f"{m['apy_pct']:7.2f}% {m['max_dd_pct']:6.2f}% {m['calmar']:7.3f}"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Idea #120 — CADS on the real aggressive-lab panel")
    ap.add_argument("--roundtrip", type=float, default=ROUNDTRIP)
    a = ap.parse_args(argv)
    try:
        dates, books, rets = load_real_panel()
    except (Refusal, RuntimeError, ValueError) as e:
        print(f"НЕ ИЗМЕРЕНО: {e}")
        return 2
    print(f"panel: {len(books)} books, {len(dates)} common days {dates[0]}…{dates[-1]}; "
          f"roundtrip {a.roundtrip * 1e4:.0f} bp; train ≤{TRAIN_END}, test >")
    print("books:", ", ".join(books))
    runs = run_all(dates, books, rets, a.roundtrip)
    years = len(dates) / 365.0
    print(f"\n{'arm':26s} {'FULL apy   mdd   calmar':>25s} | {'TRAIN apy   mdd  calmar':>25s} | "
          f"{'TEST apy   mdd  calmar':>25s} | cost bp/yr stops")
    for k, run in runs.items():
        name = "ew (no stop)" if k[0] == "ew" else f"{k[0]:6s} stop{k[1]*100:.0f}% re{k[2]*100:.0f}%"
        full = segment(run, None, None)
        tr = segment(run, None, TRAIN_END)
        te = segment(run, "2026-01-01", None)
        print(f"{name:26s} {_fmt(full)} | {_fmt(tr)} | {_fmt(te)} | "
              f"{run.cost / INITIAL / years * 1e4:7.1f} {len(run.stops):4d}")
    pick = pick_on_train(runs)
    pr, ew = runs[pick], runs[EW_KEY]
    print(f"\nchosen on TRAIN Calmar: {pick}")
    print(f"  TEST  chosen {_fmt(segment(pr, '2026-01-01', None))}   EW {_fmt(segment(ew, '2026-01-01', None))}")
    h = runs[HEADLINE_119]
    print(f"#119 headline cell {HEADLINE_119}: FULL {_fmt(segment(h, None, None))} vs EW {_fmt(segment(ew, None, None))}")
    print("\ncrisis-window DD (% from equity entering the window):")
    for name, lo, hi in RPE.CRISIS_WINDOWS:
        print(f"  {name:22s} EW {window_dd(ew, lo, hi):6.2f}  #119-cell {window_dd(h, lo, hi):6.2f}  "
              f"chosen {window_dd(pr, lo, hi):6.2f}")
    print("\n#119-cell stop events (date, book, dd at decision):")
    for d, b, dd in h.stops:
        print(f"  {d} {b:20s} {dd*100:6.2f}%")

    # control 1 — matched static tilt: the arm's own time-average weights, held fixed, free
    print("\ncontrol 1 · matched static tilt (same average weights, no stop, no cost):")
    for key in (HEADLINE_119, pick, ("spread", 0.05, 0.01), ("cash", 0.05, 0.01)):
        r = runs[key]
        st = static_mix(dates, books, rets, r.avg_w)
        top = max(books, key=lambda b: r.avg_w[b])
        print(f"  {str(key):26s} arm {_fmt(segment(r, None, None))}  tilt {_fmt(segment(st, None, None))}"
              f"  | top weight {top} {r.avg_w[top]*100:.1f}% (EW {100/len(books):.1f}%), cash {r.avg_w[CASH]*100:.1f}%")

    # control 2 — leave-one-out of the books the tilt lands on (#99 BLO discipline)
    for drop in (LOO_DROP[:1], LOO_DROP):
        bk = [b for b in books if b not in drop]
        print(f"\ncontrol 2 · leave out {', '.join(drop)}  (FULL | TRAIN | TEST):")
        for key in (EW_KEY, ("cash", 0.05, 0.01), ("spread", 0.05, 0.01), ("calmar", 0.05, 0.01)):
            r = simulate(dates, bk, rets, key[1] or None, key[2], key[0], a.roundtrip)
            print(f"  {str(key):24s} {_fmt(segment(r, None, None))} | {_fmt(segment(r, None, TRAIN_END))} | "
                  f"{_fmt(segment(r, '2026-01-01', None))}")

    # control 3 — what the TEST-period win is made of: independent books stopped-and-out in 2026
    still_out = out_through(pr, "2026-01-01")
    print(f"\ncontrol 3 · books held OUT through the test window by the chosen cell: {', '.join(still_out) or '—'}")
    for b in still_out:
        print(f"  {b:20s} standalone TEST {_fmt(book_segment(dates, rets, b, '2026-01-01', None))}")
    bk = [b for b in books if b not in still_out]
    ew_wo = simulate(dates, bk, rets, None, 0.0, "ew", a.roundtrip)
    print(f"  EW without them, TEST {_fmt(segment(ew_wo, '2026-01-01', None))}  — the test win is these books, "
          f"not a repeated stop skill")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
