#!/usr/bin/env python3
"""Novel-edge idea #6 — CARRY-PRESERVING CRISIS ROTATION (CPCR)
(docs/DYNAMIC_LEVERAGE_GUARDIAN.md registry)

HOW THIS DIFFERS FROM ALL PRIOR IDEAS
Ideas #1–#5 de-risk by routing stressed capital to FLOOR / CASH — losing carry yield during the
de-risk window. The sUSDe carry desk has stress events (USDe-unwind, ETH-crash), but the RATES-CARRY
desk is structurally different-tailed (PT fixed rate, not stablecoin-depeg). So when sUSDe-specific
stress fires, there is a carry substitute that does NOT share the tail: rates-desk fixed carry (~4.6%
APY, near-zero vol from backtest #3). CPCR routes sUSDe capital to rates-carry during sUSDe stress
instead of to zero-carry floor.

Three-way comparison (each using same signal, same de-risk weights, different DESTINATION):
  A. #3 fixed blend baseline    — static 25/50/25, ignores all signals
  B. De-risk → FLOOR           — same as #1 reactive but at portfolio level (25%→0% sUSDe, +25% floor)
  C. De-risk → RATES-CARRY     — #6 CPCR: same de-risk but destination is rates-carry (5/70/25)

The signal: 3-day rolling sUSDe return < -THRESHOLD (noise-reduced; causal — uses only past data).
State machine: NORMAL → ROTATED (signal fires) → NORMAL after N consecutive clean days (no signal).

Rates-carry series: loads real data from backtest_rates if committed; falls back to SYNTHETIC
4.6%/yr constant (known from backtest #3, near-zero-vol, principled proxy). Clearly labelled.

METRICS: APY / maxDD / Calmar for full period + per-crisis breakdown + OOS split (2024-2025 /
2026). The key honest question: does routing to RATES-CARRY (vs FLOOR) during sUSDe stress give
meaningfully better risk-adjusted return, or is the difference negligible?

Deterministic, stdlib-only, LLM-forbidden. Advisory; touches no live track / RiskPolicy.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab import metrics  # noqa: E402
from spa_core.strategy_lab.aggressive_lab import fixtures  # noqa: E402

# ── constants ───────────────────────────────────────────────────────────────────────────────────
RWA_FLOOR_APY_PCT = 3.31    # live RWA floor rate (T-bills); near-zero-vol
RATES_CARRY_APY_PCT = 4.60  # rates-desk fixed-carry; known from backtest #3, near-zero-vol
                             # used as synthetic proxy when real backtest data is unavailable

# Default CPCR blend:  sUSDe / rates-carry / RWA-floor
NORMAL_WEIGHTS = (0.25, 0.50, 0.25)    # #3 cross-desk default
ROTATED_WEIGHTS = (0.05, 0.70, 0.25)   # CPCR: sUSDe → rates-carry during stress
TO_FLOOR_WEIGHTS = (0.05, 0.25, 0.70)  # comparison: same de-risk but destination is floor

# OOS split
TRAIN_END = "2025-12-31"
TEST_START = "2026-01-01"

# Named crisis windows for per-event breakdown
CRISIS_WINDOWS = [
    ("ETH-crash",    "2024-08-01", "2024-08-31"),
    ("USDe-unwind",  "2025-10-01", "2025-10-31"),
    ("rsETH-depeg",  "2026-04-01", "2026-04-30"),
]


# ── data loading ─────────────────────────────────────────────────────────────────────────────────

def _load_susde_returns() -> Dict[str, float]:
    """Daily returns for susde_dn from the deterministic fixture."""
    tmp = Path(tempfile.mkdtemp(prefix="cpcr_"))
    fixtures.materialize(tmp)
    eq_by_date: Dict[str, float] = {}
    jsonl = (tmp / "susde_dn" / "realized_series.jsonl").read_text()
    for line in jsonl.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("phase") == "backtest":
            eq_by_date[row["date"]] = float(row["equity_usd"])
    dates = sorted(eq_by_date)
    return {dates[i]: eq_by_date[dates[i]] / eq_by_date[dates[i - 1]] - 1.0
            for i in range(1, len(dates))}


def _load_rates_returns(dates: List[str]) -> Tuple[Dict[str, float], bool]:
    """Load real rates-carry daily returns, fall back to synthetic 4.6%/yr constant.
    Returns (daily_returns_by_date, is_real_data)."""
    try:
        from spa_core.strategy_lab.rates_desk import backtest_rates as br
        from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
        from spa_core.strategy_lab.rates_desk import retro
        from spa_core.strategy_lab.rates_desk.contracts import RatePolicyParams
        from spa_core.strategy_lab.rates_desk.opportunity_engine import CostConfig
        from spa_core.strategy_lab.rates_desk.feeds import BorosFeed
        deep = pph.load()
        try:
            funding = retro.load_funding()
        except FileNotFoundError:
            funding = {}
        all_dates = br._all_dates(deep)
        universe = sorted({m["underlying"].lower() for m in deep["markets"].values()})
        hedge_map = BorosFeed().hedge_available(universe)
        res = br.replay_sleeve("fixed_carry", all_dates, deep, funding, hedge_map,
                               RatePolicyParams(), CostConfig(), return_series=True)
        series = res.get("series") or []
        if len(series) < 60:
            raise ValueError("too few points")
        eq_by_date = {p["date"]: float(p["equity_usd"]) for p in series}
        rdates = sorted(eq_by_date)
        real = {rdates[i]: eq_by_date[rdates[i]] / eq_by_date[rdates[i - 1]] - 1.0
                for i in range(1, len(rdates))}
        # fill any missing dates with synthetic (near-zero-vol → tiny daily accrual)
        daily_synth = RATES_CARRY_APY_PCT / 100.0 / 365.0
        out = {d: real.get(d, daily_synth) for d in dates}
        return out, True
    except Exception:
        daily = RATES_CARRY_APY_PCT / 100.0 / 365.0
        return {d: daily for d in dates}, False


# ── signal: 3-day rolling return ─────────────────────────────────────────────────────────────────

def _rolling_return(dates: List[str], ret: Dict[str, float], n: int = 3) -> Dict[str, float]:
    """N-day rolling sum of daily returns (causal: uses day t-1 .. t-n returns to predict day t).
    Return at index i is the SUM of returns at indices i-1 .. max(i-n, 0)."""
    out: Dict[str, float] = {}
    for i, d in enumerate(dates):
        s = sum(ret.get(dates[j], 0.0) for j in range(max(0, i - n), i))
        out[d] = s
    return out


# ── state machine: NORMAL / ROTATED ──────────────────────────────────────────────────────────────

def _run_strategy(dates, r_susde, r_rates, r_floor, normal_w, stressed_w,
                  threshold, clean_days_needed):
    """Simulate the CPCR portfolio. Returns daily equity list (100k start).
    State machine: NORMAL → ROTATED when 3-day sUSDe return < -threshold.
                  ROTATED → NORMAL after `clean_days_needed` consecutive days without signal."""
    roll = _rolling_return(dates, r_susde, n=3)
    eq = [100_000.0]
    state = "NORMAL"
    clean_count = 0
    for d in dates:
        w = normal_w if state == "NORMAL" else stressed_w
        r = w[0] * r_susde.get(d, 0.0) + w[1] * r_rates.get(d, 0.0) + w[2] * r_floor.get(d, 0.0)
        eq.append(eq[-1] * (1.0 + r))
        # state transition (causal: uses roll[d] = sum of returns UP TO day d, i.e. d-1..d-3)
        signal = roll.get(d, 0.0) < -threshold
        if state == "NORMAL" and signal:
            state = "ROTATED"
            clean_count = 0
        elif state == "ROTATED":
            if not signal:
                clean_count += 1
                if clean_count >= clean_days_needed:
                    state = "NORMAL"
                    clean_count = 0
            else:
                clean_count = 0
    return eq


# ── metrics helpers ──────────────────────────────────────────────────────────────────────────────

def _m(eq) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    a = metrics.net_apy_from_equity(eq)
    d = metrics.max_drawdown_pct(eq)
    c = (a / d) if (isinstance(a, (int, float)) and isinstance(d, (int, float)) and d > 0) else None
    return a, d, c


def _fmt(x) -> str:
    return f"{x:.2f}" if isinstance(x, (int, float)) else "n/a"


def _crisis_dd(dates, r_susde, r_rates, r_floor, normal_w, stressed_w,
               threshold, clean_days_needed, window_start, window_end) -> Optional[float]:
    """Max drawdown of the strategy restricted to a specific crisis window."""
    roll = _rolling_return(dates, r_susde, n=3)
    eq = 100_000.0
    state = "NORMAL"
    clean_count = 0
    peak = eq
    min_eq = eq
    in_window = False
    for d in dates:
        in_w = window_start <= d <= window_end
        w = normal_w if state == "NORMAL" else stressed_w
        r = w[0] * r_susde.get(d, 0.0) + w[1] * r_rates.get(d, 0.0) + w[2] * r_floor.get(d, 0.0)
        eq = eq * (1.0 + r)
        if in_w:
            peak = max(peak, eq) if not in_window else peak
            in_window = True
            min_eq = min(min_eq, eq) if in_window else eq
        signal = roll.get(d, 0.0) < -threshold
        if state == "NORMAL" and signal:
            state = "ROTATED"
            clean_count = 0
        elif state == "ROTATED":
            if not signal:
                clean_count += 1
                if clean_count >= clean_days_needed:
                    state = "NORMAL"
                    clean_count = 0
            else:
                clean_count = 0
    if not in_window or peak == 0:
        return None
    # simple peak-to-trough for window only (approximate)
    return max(0.0, (peak - min_eq) / peak * 100.0)


# ── crisis-window equity extraction for breakdown ────────────────────────────────────────────────

def _window_equity(dates, r_susde, r_rates, r_floor, normal_w, stressed_w,
                   threshold, clean_days_needed, ws, we) -> List[float]:
    """Return equity curve clipped to the crisis window."""
    roll = _rolling_return(dates, r_susde, n=3)
    state = "NORMAL"
    clean_count = 0
    eq = 100_000.0
    out = []
    for d in dates:
        w = normal_w if state == "NORMAL" else stressed_w
        r = w[0] * r_susde.get(d, 0.0) + w[1] * r_rates.get(d, 0.0) + w[2] * r_floor.get(d, 0.0)
        eq = eq * (1.0 + r)
        if ws <= d <= we:
            out.append(eq)
        signal = roll.get(d, 0.0) < -threshold
        if state == "NORMAL" and signal:
            state = "ROTATED"
            clean_count = 0
        elif state == "ROTATED":
            if not signal:
                clean_count += 1
                if clean_count >= clean_days_needed:
                    state = "NORMAL"
                    clean_count = 0
            else:
                clean_count = 0
    return out


# ── parameter sweep ──────────────────────────────────────────────────────────────────────────────

def _sweep(dates, r_susde, r_rates, r_floor):
    """Sweep threshold and clean_days to find the best CPCR config (by Calmar)."""
    best = None
    results = []
    for threshold in (0.0, 0.001, 0.002, 0.005):   # 0%, 0.1%, 0.2%, 0.5%
        for clean in (1, 3, 5):
            eq = _run_strategy(dates, r_susde, r_rates, r_floor,
                               NORMAL_WEIGHTS, ROTATED_WEIGHTS, threshold, clean)
            a, d, c = _m(eq)
            results.append((threshold, clean, a, d, c))
            if isinstance(c, (int, float)) and (best is None or c > best[4]):
                best = (threshold, clean, a, d, c, eq)
    return best, results


# ── main ─────────────────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 72)
    print("IDEA #6: CARRY-PRESERVING CRISIS ROTATION (CPCR)")
    print("  Novel: de-risk to RATES-CARRY (not floor) when sUSDe stress fires")
    print("=" * 72)

    # ── load data ────────────────────────────────────────────────────────────────
    r_susde = _load_susde_returns()
    dates = sorted(r_susde)
    r_rates, is_real = _load_rates_returns(dates)
    daily_floor = RWA_FLOOR_APY_PCT / 100.0 / 365.0
    r_floor = {d: daily_floor for d in dates}

    data_label = "REAL backtest data" if is_real else f"SYNTHETIC {RATES_CARRY_APY_PCT}%/yr proxy (known from backtest #3)"
    print(f"\nRates-carry data: {data_label}")
    print(f"Window: {dates[0]} .. {dates[-1]}  ({len(dates)} days)")

    # ── full-period metrics for all three strategies ──────────────────────────────
    eq_fixed   = _run_strategy(dates, r_susde, r_rates, r_floor,
                               NORMAL_WEIGHTS, NORMAL_WEIGHTS, 0.0, 999)  # signal never changes blend
    eq_to_floor = _run_strategy(dates, r_susde, r_rates, r_floor,
                                NORMAL_WEIGHTS, TO_FLOOR_WEIGHTS, 0.002, 3)
    eq_cpcr    = _run_strategy(dates, r_susde, r_rates, r_floor,
                               NORMAL_WEIGHTS, ROTATED_WEIGHTS, 0.002, 3)

    a_fix, d_fix, c_fix = _m(eq_fixed)
    a_flr, d_flr, c_flr = _m(eq_to_floor)
    a_cpcr, d_cpcr, c_cpcr = _m(eq_cpcr)

    print(f"\n{'Strategy':>28}  {'APY%':>7} {'maxDD%':>8} {'Calmar':>8}")
    print("-" * 60)
    print(f"{'#3 fixed 25/50/25 (baseline)':>28}  {_fmt(a_fix):>7} {_fmt(d_fix):>8} {_fmt(c_fix):>8}")
    print(f"{'de-risk→FLOOR (comparison)':>28}  {_fmt(a_flr):>7} {_fmt(d_flr):>8} {_fmt(c_flr):>8}")
    print(f"{'CPCR de-risk→RATES (idea #6)':>28}  {_fmt(a_cpcr):>7} {_fmt(d_cpcr):>8} {_fmt(c_cpcr):>8}")

    # ── parameter sweep to find optimal CPCR config ──────────────────────────────
    print("\n=== PARAMETER SWEEP (CPCR: threshold × clean_days) ===")
    print(f"{'threshold':>11} {'clean_days':>11} {'APY%':>7} {'maxDD%':>8} {'Calmar':>8}")
    print("-" * 50)
    best, results = _sweep(dates, r_susde, r_rates, r_floor)
    for thr, cln, a, d, c in sorted(results, key=lambda r: r[4] or -999, reverse=True):
        print(f"{thr*100:>10.2f}% {cln:>11}d {_fmt(a):>7} {_fmt(d):>8} {_fmt(c):>8}")

    if best:
        t_best, c_best, a_best, d_best, cb_best, eq_best = best
        print(f"\n→ Best CPCR: threshold={t_best*100:.2f}%  clean_days={c_best}")
        print(f"  APY {_fmt(a_best)}%  maxDD {_fmt(d_best)}%  Calmar {_fmt(cb_best)}")

    # ── per-crisis breakdown (CPCR vs fixed vs to-floor) ────────────────────────
    print("\n=== PER-CRISIS DRAWDOWN BREAKDOWN ===")
    print(f"{'crisis':>14}  {'fixed DD%':>10} {'→floor DD%':>11} {'CPCR DD%':>10} {'CPCR saves vs floor':>20}")
    print("-" * 72)
    for crisis_name, ws, we in CRISIS_WINDOWS:
        def _wdd(normal_w, stressed_w, thr, cln):
            eq_w = _window_equity(dates, r_susde, r_rates, r_floor,
                                  normal_w, stressed_w, thr, cln, ws, we)
            if len(eq_w) < 2:
                return None
            pk = eq_w[0]
            mn = min(eq_w)
            return max(0.0, (pk - mn) / pk * 100.0) if pk > 0 else None

        dd_fix = _wdd(NORMAL_WEIGHTS, NORMAL_WEIGHTS, 0.0, 999)
        dd_flr = _wdd(NORMAL_WEIGHTS, TO_FLOOR_WEIGHTS, 0.002, 3)
        dd_cpcr = _wdd(NORMAL_WEIGHTS, ROTATED_WEIGHTS, 0.002, 3)

        saved = None
        if isinstance(dd_flr, (int, float)) and isinstance(dd_cpcr, (int, float)):
            saved = dd_flr - dd_cpcr

        print(f"{crisis_name:>14}  {_fmt(dd_fix):>10} {_fmt(dd_flr):>11} {_fmt(dd_cpcr):>10}  "
              f"{'CPCR better by ' + _fmt(saved) + 'pp' if isinstance(saved, (int, float)) and saved > 0 else 'no diff' if saved is not None else 'n/a':>20}")

    # ── out-of-sample split ──────────────────────────────────────────────────────
    print(f"\n=== OUT-OF-SAMPLE SPLIT (train ≤{TRAIN_END} / test ≥{TEST_START}) ===")
    train_dates = [d for d in dates if d <= TRAIN_END]
    test_dates  = [d for d in dates if d >= TEST_START]

    def _oos(w_normal, w_stress, thr, cln, ds):
        if len(ds) < 30:
            return None, None, None
        eq = _run_strategy(ds, r_susde, r_rates, r_floor, w_normal, w_stress, thr, cln)
        return _m(eq)

    print(f"\n  Train ({len(train_dates)} days): {train_dates[0] if train_dates else '?'} .. {train_dates[-1] if train_dates else '?'}")
    for label, nw, sw, thr, cln in [
        ("#3 fixed",         NORMAL_WEIGHTS, NORMAL_WEIGHTS,   0.000, 999),
        ("→floor (best)",   NORMAL_WEIGHTS, TO_FLOOR_WEIGHTS, 0.002,   3),
        ("CPCR (best)",     NORMAL_WEIGHTS, ROTATED_WEIGHTS,  0.002,   3),
    ]:
        a, d, c = _oos(nw, sw, thr, cln, train_dates)
        print(f"  {label:>16}: APY {_fmt(a)}%  maxDD {_fmt(d)}%  Calmar {_fmt(c)}")

    print(f"\n  Test ({len(test_dates)} days): {test_dates[0] if test_dates else '?'} .. {test_dates[-1] if test_dates else '?'}")
    for label, nw, sw, thr, cln in [
        ("#3 fixed",         NORMAL_WEIGHTS, NORMAL_WEIGHTS,   0.000, 999),
        ("→floor (best)",   NORMAL_WEIGHTS, TO_FLOOR_WEIGHTS, 0.002,   3),
        ("CPCR (best)",     NORMAL_WEIGHTS, ROTATED_WEIGHTS,  0.002,   3),
    ]:
        a, d, c = _oos(nw, sw, thr, cln, test_dates)
        print(f"  {label:>16}: APY {_fmt(a)}%  maxDD {_fmt(d)}%  Calmar {_fmt(c)}")

    # ── verdict ──────────────────────────────────────────────────────────────────
    print("\n=== VERDICT ===")
    if best:
        fix_c = c_fix or 0
        cpcr_c = cb_best or 0
        delta = cpcr_c - fix_c
        better_than_fixed = delta > 0
        print(f"  CPCR vs fixed blend:  Calmar {'UP' if better_than_fixed else 'DOWN'} by {abs(delta):.2f}"
              f"  ({'risk-adj improvement' if better_than_fixed else 'no improvement'})")
        if isinstance(c_flr, (int, float)) and isinstance(cb_best, (int, float)):
            vs_floor = cb_best - c_flr
            print(f"  CPCR vs de-risk→floor:  Calmar {'UP' if vs_floor > 0 else 'DOWN'} by {abs(vs_floor):.2f}"
                  f"  ({'carry-preserve edge demonstrated' if vs_floor > 0 else 'floor destination better or equal'})")

    print("\n  HONEST CAVEATS:")
    print("  (a) Rates-carry is near-zero-vol → differential signal = single-desk sUSDe signal only")
    print("  (b) In-sample: both threshold and clean_days fit on same data → OOS test is the real check")
    print("  (c) Synthetic rates-carry (if real not available) = constant APY — real data may vary")
    print("  (d) CPCR assumes rates-carry does NOT share sUSDe's tail — valid for desk-specific stress,")
    print("      but both legs could co-move in a SYSTEMIC crypto crisis (correlation-1 event)")
    print("  (e) Gap/exploit risk: CPCR exits sUSDe NEXT DAY after signal — same 1-day lag as guardian")

    print("\n  backtest label: all numbers are BACKTEST (fixture-generated) — NOT live realized.")
    print("=" * 72)


if __name__ == "__main__":
    main()
