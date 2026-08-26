#!/usr/bin/env python3
"""
scripts/edge_mhfc_backtest.py — Idea #79 MHFC: Multi-Horizon Forecast Combination

Advisory-only backtest on code-generated fixture.
IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  Evidence=L0

HYPOTHESIS
----------
Different lookback horizons carry different information at different times.
During stress events the 5d signal responds first; during calm the 60d signal
is more stable (lower noise).  MHFC tracks, for each horizon h, how well the
lagged h-day signal predicted the NEXT day's return over the past M=30 days,
then weights horizons proportionally to their recent predictive accuracy
(max(0, acc_h) / sum).  Books whose combined MHFC signal is positive are
held at equal weight; books with a clearly negative combined signal are
excluded.

DISTINCTNESS FROM PRIOR IDEAS
------------------------------
• #24 VTST   — uses SLOPE between TWO vol estimates, not per-horizon accuracy weights
• #27 ALK    — asymmetric μ vs σ² lookbacks; no accuracy-adaptive weighting
• #32 ECDR   — single lookback with dwell hysteresis; no multi-horizon combination
• #41 MRD    — uses "return during bad portfolio days" as a static score, not forecast accuracy

LOOK-AHEAD GUARD (all checks explicit)
- Signal at index i: uses rets[i-h : i]  (data through day i-1, never includes i)
- Accuracy at index i: correlation of signal(j) → actual(j+1) for j in [i-M-1, i-2]
  so the latest actual used is rets[i-1]  ✓
- Portfolio weight at index i applied to return rets[i]  ✓

HONESTY CONSTRAINTS
- Only code-generated fixture (no real-panel data; constant drift between stress windows
  means Pearson corr is undefined in calm periods → fallback to equal-weight for those days)
- All numbers labeled [bt]; no forward paper without real-panel validation
- Turnover costs deducted (96 bps round-trip per unit turnover)
"""
# LLM_FORBIDDEN
from __future__ import annotations
import datetime
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── constants ────────────────────────────────────────────────────────────────────
IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True
EVIDENCE_LEVEL = "L0"   # code-generated fixture

HORIZONS = [5, 20, 60]  # lookback windows for multi-horizon signal
ACC_WINDOW = 30          # days to evaluate predictive accuracy
WARMUP = max(HORIZONS) + ACC_WINDOW + 2   # conservative burn-in
COST_BPS = 96            # round-trip cost per unit turnover

STRESS_WINDOWS = [
    {"key": "eth_crash_2024_08",  "date_from": "2024-08-01", "date_to": "2024-08-31"},
    {"key": "usde_unwind_2025_10","date_from": "2025-10-01", "date_to": "2025-10-31"},
    {"key": "rseth_depeg_2026_04","date_from": "2026-04-01", "date_to": "2026-04-30"},
]

SPLIT_DATE = "2025-06-30"  # train/test boundary; chosen BEFORE seeing numbers


# ── data loading ─────────────────────────────────────────────────────────────────
def _load_fixture() -> Dict[str, List[dict]]:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from spa_core.strategy_lab.aggressive_lab.fixtures import (
        strategy_jsonl, roster as _roster,
    )
    books: Dict[str, List[dict]] = {}
    for sid in _roster():
        lines = [
            json.loads(ln)
            for ln in strategy_jsonl(sid).strip().split("\n")
            if ln.strip()
        ]
        bt = [ln for ln in lines if ln.get("phase") == "backtest"]
        if not bt:
            continue  # thin_new: no backtest phase
        books[sid] = bt
    return books


def _daily_returns(
    series: List[dict],
) -> Tuple[List[datetime.date], List[float]]:
    dates, rets = [], []
    for i in range(1, len(series)):
        d = datetime.date.fromisoformat(series[i]["date"])
        prev = float(series[i - 1]["equity_usd"])
        curr = float(series[i]["equity_usd"])
        if prev <= 0:
            continue
        r = (curr - prev) / prev
        if abs(r) > 0.50:
            raise ValueError(
                f"Suspicious return {r:.3f} on {d} — phase-glue contamination?"
            )
        dates.append(d)
        rets.append(r)
    return dates, rets


# ── statistical helpers ───────────────────────────────────────────────────────────
def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 5 or len(ys) != n:
        return None
    mx, my = _mean(xs), _mean(ys)
    cov = sum((xs[k] - mx) * (ys[k] - my) for k in range(n))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    denom = math.sqrt(vx * vy)
    if denom < 1e-12:
        return None  # zero-variance (constant drift in calm fixture periods)
    return cov / denom


# ── signal computation (no look-ahead) ───────────────────────────────────────────
def _signal_at(rets: List[float], i: int, h: int) -> Optional[float]:
    """h-day rolling mean ending at i-1 (no look-ahead)."""
    if i < h:
        return None
    window = rets[i - h : i]
    if len(window) < h:
        return None
    return _mean(window)


def _accuracy_at(rets: List[float], i: int, h: int, M: int) -> Optional[float]:
    """
    Pearson corr of signal(j) → actual(j+1) for j in [i-M-1, i-2].
    Latest actual return used: rets[i-1].  No look-ahead into day i.
    """
    if i < h + M + 2:
        return None
    sigs, acts = [], []
    for j in range(i - M - 1, i - 1):  # j in [i-M-1, i-2]
        s = _signal_at(rets, j, h)
        if s is None:
            continue
        if j + 1 >= len(rets):
            continue
        sigs.append(s)
        acts.append(rets[j + 1])
    return _pearson(sigs, acts)


def _mhfc_signal(rets: List[float], i: int) -> Optional[float]:
    """
    Combined MHFC signal for one book at index i.
    Weights each horizon by max(0, accuracy), normalised.
    Returns None if warmup not satisfied.
    Falls back to slow (60d) signal when all accuracies are undefined.
    Falls back to equal-horizon mix when total positive weight is zero.
    """
    if i < WARMUP:
        return None
    raw_sigs, accs = [], []
    for h in HORIZONS:
        s = _signal_at(rets, i, h)
        a = _accuracy_at(rets, i, h, ACC_WINDOW)
        raw_sigs.append(s)
        accs.append(a)

    # If ALL accuracies undefined (constant-drift calm period in fixture),
    # fall back to slow signal (most stable)
    if all(a is None for a in accs):
        return raw_sigs[-1]  # 60d signal (or None if still warming up)

    total_pos = sum(max(0.0, a) for a in accs if a is not None)
    if total_pos < 1e-12:
        # All accuracies defined but none positive: equal-weight the signals
        valid = [s for s in raw_sigs if s is not None]
        return _mean(valid) if valid else None

    combined = 0.0
    for s, a in zip(raw_sigs, accs):
        if s is None or a is None:
            continue
        combined += s * max(0.0, a)
    return combined / total_pos


# ── portfolio construction ────────────────────────────────────────────────────────
def _weights(
    book_rets: Dict[str, List[float]],
    i: int,
    mode: str,
    h_single: int = 20,
) -> Dict[str, float]:
    """
    Returns weights (sum = 1.0) for day i.
    mode: 'eq' | 'mhfc' | 'h5' | 'h20' | 'h60'
    Rule: include books with positive signal at equal weight.
    Books with None/uncertain signal are INCLUDED (fail-open for capital deployment).
    Books with clearly negative signal are EXCLUDED.
    If all excluded: revert to equal weight.
    """
    book_ids = sorted(book_rets.keys())
    n = len(book_ids)

    if mode == "eq":
        return {b: 1.0 / n for b in book_ids}

    signals: Dict[str, Optional[float]] = {}
    if mode == "mhfc":
        for b in book_ids:
            signals[b] = _mhfc_signal(book_rets[b], i)
    else:
        h = int(mode[1:])
        for b in book_ids:
            signals[b] = _signal_at(book_rets[b], i, h)

    # Include: signal > 0 or signal is None (uncertain → include)
    included = [b for b in book_ids if signals[b] is None or signals[b] > 0]
    if not included:
        included = book_ids  # all negative → equal weight all
    w = 1.0 / len(included)
    return {b: (w if b in included else 0.0) for b in book_ids}


# ── backtest engine ───────────────────────────────────────────────────────────────
def _run(
    book_rets: Dict[str, List[float]],
    dates: List[datetime.date],
    mode: str,
) -> Tuple[List[float], List[float]]:
    """Returns (net_rets, turnovers)."""
    book_ids = sorted(book_rets.keys())
    net_rets, turnovers = [], []
    prev_w: Dict[str, float] = {}

    for i in range(1, len(dates)):
        w = _weights(book_rets, i, mode)
        port_r = sum(w.get(b, 0.0) * book_rets[b][i] for b in book_ids)
        to = (
            sum(abs(w.get(b, 0.0) - prev_w.get(b, 0.0)) for b in book_ids)
            if prev_w
            else 0.0
        )
        net_r = port_r - to * COST_BPS / 10_000.0
        net_rets.append(net_r)
        turnovers.append(to)
        prev_w = w

    return net_rets, turnovers


# ── metrics ──────────────────────────────────────────────────────────────────────
def _apy(rets: List[float]) -> float:
    if not rets:
        return 0.0
    compound = 1.0
    for r in rets:
        compound *= 1.0 + r
    years = len(rets) / 365.0
    if years <= 0 or compound <= 0:
        return 0.0
    return compound ** (1.0 / years) - 1.0


def _mdd(rets: List[float]) -> float:
    peak = eq = 1.0
    worst = 0.0
    for r in rets:
        eq *= 1.0 + r
        peak = max(peak, eq)
        worst = min(worst, (eq - peak) / peak)
    return worst


def _calmar(rets: List[float]) -> float:
    a = _apy(rets)
    d = _mdd(rets)
    return a / abs(d) if abs(d) > 1e-9 else float("inf")


def _stress_ret(
    rets: List[float], dates: List[datetime.date], key: str
) -> float:
    for sw in STRESS_WINDOWS:
        if sw["key"] == key:
            lo = datetime.date.fromisoformat(sw["date_from"])
            hi = datetime.date.fromisoformat(sw["date_to"])
            c = 1.0
            for r, d in zip(rets, dates):
                if lo <= d <= hi:
                    c *= 1.0 + r
            return c - 1.0
    return 0.0


def _split(
    rets: List[float], dates: List[datetime.date], cut: str
) -> Tuple[List[float], List[float]]:
    cd = datetime.date.fromisoformat(cut)
    tr = [r for r, d in zip(rets, dates) if d <= cd]
    te = [r for r, d in zip(rets, dates) if d > cd]
    return tr, te


# ── horizon-weight diagnostics ────────────────────────────────────────────────────
def _horizon_weights_over_time(
    book_rets: Dict[str, List[float]],
    dates: List[datetime.date],
) -> Dict[int, List[float]]:
    """Return mean adaptive weight for each horizon per post-warmup day."""
    b0 = sorted(book_rets.keys())[0]  # representative book
    rets = book_rets[b0]
    hw: Dict[int, List[float]] = {h: [] for h in HORIZONS}
    for i in range(1, len(dates)):
        if i < WARMUP:
            continue
        accs = {h: _accuracy_at(rets, i, h, ACC_WINDOW) for h in HORIZONS}
        if all(a is None for a in accs.values()):
            # undefined: equal weight
            for h in HORIZONS:
                hw[h].append(1.0 / len(HORIZONS))
            continue
        total_pos = sum(max(0.0, a) for a in accs.values() if a is not None)
        for h in HORIZONS:
            a = accs[h]
            if total_pos < 1e-12 or a is None:
                hw[h].append(1.0 / len(HORIZONS))
            else:
                hw[h].append(max(0.0, a) / total_pos)
    return hw


# ── main ─────────────────────────────────────────────────────────────────────────
def run_idea79() -> None:
    print("=" * 72)
    print("Idea #79 MHFC: Multi-Horizon Forecast Combination  [bt]")
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  Evidence=L0")
    print(f"Horizons H={HORIZONS}d  AccWindow M={ACC_WINDOW}d  Warmup={WARMUP}d")
    print("=" * 72)

    raw_books = _load_fixture()
    print(f"\nLoaded {len(raw_books)} books (backtest phase only):")

    # Compute returns per book
    by_date: Dict[str, Dict[datetime.date, float]] = {}
    for sid, series in raw_books.items():
        dts, rets = _daily_returns(series)
        by_date[sid] = dict(zip(dts, rets))
        print(f"  {sid:<20} {len(rets)} days")

    # Align to common dates
    common_dates = sorted(
        set.intersection(*[set(d.keys()) for d in by_date.values()])
    )
    print(f"\nAligned: {common_dates[0]} … {common_dates[-1]}  ({len(common_dates)} days)")

    book_rets: Dict[str, List[float]] = {
        sid: [by_date[sid][d] for d in common_dates]
        for sid in sorted(by_date.keys())
    }
    # dates for returns (offset by 1)
    ret_dates = common_dates[1:]

    # Run all strategies
    modes = [
        ("eq",  "Equal-weight baseline"),
        ("h5",  "Single h=5d"),
        ("h20", "Single h=20d"),
        ("h60", "Single h=60d"),
        ("mhfc","MHFC adaptive"),
    ]
    results: Dict[str, Tuple[List[float], List[float]]] = {}
    for m, _ in modes:
        nr, to = _run(book_rets, common_dates, m)
        results[m] = (nr, to)

    eq_cal = _calmar(results["eq"][0])

    # ── main table ────────────────────────────────────────────────────────────────
    print("\n" + "─" * 72)
    print(f"{'STRATEGY':<28} {'APY':>7} {'maxDD':>8} {'Calmar':>8} {'ΔCalmar':>9} {'TO/yr':>7}")
    print("─" * 72)
    for m, label in modes:
        nr, to = results[m]
        a = _apy(nr)
        d = _mdd(nr)
        c = _calmar(nr)
        to_yr = sum(to) / (len(nr) / 365.0) if nr else 0.0
        dc = c - eq_cal
        flag = "  ← baseline" if m == "eq" else ""
        print(
            f"  {label:<26} {a*100:>6.2f}% {d*100:>7.2f}% {c:>8.2f} {dc:>+9.2f} {to_yr:>7.2f}{flag}"
        )

    # ── stress windows ────────────────────────────────────────────────────────────
    print("\n" + "─" * 72)
    print(f"{'STRESS WINDOW':<30} {'EQ ret':>9} {'MHFC ret':>10} {'Δ':>9}")
    print("─" * 72)
    for sw in STRESS_WINDOWS:
        eq_sw = _stress_ret(results["eq"][0], ret_dates, sw["key"])
        mh_sw = _stress_ret(results["mhfc"][0], ret_dates, sw["key"])
        delta = mh_sw - eq_sw
        print(
            f"  {sw['key']:<28} {eq_sw*100:>8.2f}% {mh_sw*100:>9.2f}% {delta*100:>+8.2f}%"
        )

    # ── OOS validation ────────────────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print(f"TRAIN / TEST (split: {SPLIT_DATE})")
    print(f"{'STRATEGY':<28} {'trΔCalmar':>11} {'teΔCalmar':>11}")
    print("─" * 72)
    eq_tr, eq_te = _split(results["eq"][0], ret_dates, SPLIT_DATE)
    eq_tr_cal = _calmar(eq_tr)
    eq_te_cal = _calmar(eq_te)
    for m, label in modes[1:]:
        tr, te = _split(results[m][0], ret_dates, SPLIT_DATE)
        dc_tr = _calmar(tr) - eq_tr_cal
        dc_te = _calmar(te) - eq_te_cal
        print(f"  {label:<26} {dc_tr:>+11.2f} {dc_te:>+11.2f}")

    # ── horizon weight diagnostics ────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("ADAPTIVE HORIZON WEIGHTS (post-warmup mean weight)")
    hw = _horizon_weights_over_time(book_rets, common_dates)
    n_post = len(next(iter(hw.values())))
    undefined_days = sum(
        1
        for k in range(n_post)
        if all(hw[h][k] == 1.0 / len(HORIZONS) for h in HORIZONS)
    )
    for h in HORIZONS:
        ws = hw[h]
        mean_w = _mean(ws) if ws else 0.0
        print(f"  h={h:2d}d: mean weight = {mean_w:.3f}")
    print(f"  (Days with undefined accuracy → equal-horizon fallback: {undefined_days}/{n_post})")

    # ── look-ahead verification ───────────────────────────────────────────────────
    print(f"\n{'─'*72}")
    print("LOOK-AHEAD VERIFICATION")
    print("  Signal at i uses rets[i-h : i]        ← excludes day i  ✓")
    print("  Accuracy at i uses actuals rets[j+1], j <= i-2  ← max j+1 = i-1  ✓")
    print("  Portfolio weight at i applied to rets[i]         ✓")

    # ── summary ───────────────────────────────────────────────────────────────────
    mhfc_nr, mhfc_to = results["mhfc"]
    mhfc_a = _apy(mhfc_nr)
    mhfc_d = _mdd(mhfc_nr)
    mhfc_c = _calmar(mhfc_nr)
    mhfc_dc = mhfc_c - eq_cal
    mhfc_to_yr = sum(mhfc_to) / (len(mhfc_nr) / 365.0) if mhfc_nr else 0.0

    eq_a = _apy(results["eq"][0])
    eq_d = _mdd(results["eq"][0])

    print(f"\n{'═'*72}")
    print("SUMMARY  [bt]  fixture only — fixture has constant drift in calm periods")
    print(f"  Equal-weight:  APY={eq_a*100:.2f}%  maxDD={eq_d*100:.2f}%  Calmar={eq_cal:.2f}")
    print(f"  MHFC #79:      APY={mhfc_a*100:.2f}%  maxDD={mhfc_d*100:.2f}%  Calmar={mhfc_c:.2f}")
    print(f"  ΔCalmar:       {mhfc_dc:+.2f}  |  Turnover/year: {mhfc_to_yr:.2f}")
    print()
    print("  IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  evidence L0 [bt]")
    print("  Real-panel validation required before any forward proposal.")
    print("═" * 72)


if __name__ == "__main__":
    run_idea79()
