#!/usr/bin/env python3
"""
scripts/edge_carry_momentum_switch.py  —  Idea #113: CMRS

CMRS: Carry Momentum Regime Switch
===================================
Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True.
Never imports spa_core/execution/. stdlib-only. LLM FORBIDDEN.

Hypothesis
----------
Every reactive binary switch in the registry (#110 BISS, #111 BISS-REAL) uses a DIFFERENT
signal for ENTRY (some negative-return trigger) and EXIT (N_RECOVER=3 consecutive all-positive
days).  The cross-contamination between those two rules inflates switch counts (#111 found 1DAY
at 97.9 % narud on real panel, 5DAY at 55.2 %) and makes the regime signal non-symmetric.

CMRS replaces both with ONE signal: the sign of the rolling mean of EW portfolio returns over
the last L days (measured at end-of-day t-1, applied on day t).

  rolling_mean(t) = mean of ew_return[t-L..t-1]

  state(t):
      if rolling_mean(t) > threshold  →  INVEST  (full EW across books)
      else                            →  DEFEND  (RWA floor, defend_frac = 0.0)

Properties
----------
* Symmetric: the SAME signal decides both ENTRY and EXIT.  No N_RECOVER free parameter.
* Hysteresis: requires ~L/2 days of sustained negative returns before crossing, then
  ~L/2 days of sustained recovery before switching back.
* On fixture (σ²≈0 outside crisis): rolling_mean always positive in calm → zero false positives.
* On real panel: rolling mean of carry-dominated returns is positive most of the time; should
  give far fewer false positives than 1DAY (which triggers on any single negative day).
* Expected switch count: 2-4 per crisis window (enter + exit each crisis) → 6-12 total vs
  31+ for 1DAY on real panel.

Novelty vs registry
-------------------
* DDO (#9)    — drawdown from HWM, continuous sizing
* DACRS (#25) — time under HWM, continuous sizing
* CDMS (#107) — EWMA of drawdown memory, continuous sizer
* BISS (#110) — binary switch, 1DAY or 5DAY entry + 3-day exit (ASYMMETRIC)
* 5DAY in #110 uses N_RECOVER=3 all-positive exit (different from rolling-mean exit)
CMRS: first SYMMETRIC rolling-mean switch, same signal entry AND exit, no N_RECOVER.

Key structural difference from BISS 5DAY:
  BISS 5DAY entry: EW 5-day sum < 0
  BISS 5DAY exit:  3 consecutive days with all books positive (hard exit rule)
  CMRS entry:      rolling_mean(L) ≤ threshold
  CMRS exit:       rolling_mean(L) > threshold  (SAME signal, not a book-level rule)

Data: fixture corpus only (data/aggressive_lab/ not present in this cloud checkout).
Evidence level: [bt] [L0] — deterministic fixture, no real fills.

HONEST LIMITS
  * Fixture has σ²≈0 in calm → zero false positives, cannot test real false positive rate.
  * Best L window selected on the SAME data → overfit risk; TRAIN/TEST split printed.
  * Defend pays 96 bp round-trip on the fraction of capital that changes state.
  * No slippage, gas, capacity, borrow cost, or tiering.
  * IS_ADVISORY=True / OUTSIDE_RISKPOLICY=True; does not touch live track or RiskPolicy v1.0.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_repo = Path(__file__).resolve().parent.parent
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS
from spa_core.strategy_lab.aggressive_lab.fixtures import _SPEC, _build_backtest_series  # type: ignore[attr-defined]

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

# ── constants ────────────────────────────────────────────────────────────────────────────────────

RWA_DAILY  = 3.4 / 100.0 / 365.0   # RWA floor annualised → daily fraction
INITIAL    = 100_000.0
BOOKS      = ["susde_dn", "lrt_carry", "leverage_loop", "points_farm", "variant_d"]
N_BOOKS    = len(BOOKS)
ROUNDTRIP  = 0.0096                  # 96 bp canonical cost (#10/#49)
SPLIT      = "2025-06-30"            # registry-canonical train/test boundary

# Window lengths to test (days)
L_GRID: Tuple[int, ...] = (5, 10, 20, 30, 60)
# Momentum threshold (signal switches when rolling_mean crosses this value)
THRESHOLD  = 0.0   # symmetric around zero
# Defend allocation: fraction of risky exposure retained (0.0 = all RWA)
DEFEND_FRAC = 0.0


# ── data loading ─────────────────────────────────────────────────────────────────────────────────

def _load_daily_rets() -> Tuple[List[str], Dict[str, List[float]]]:
    """Load daily fractional returns for fixture books, backtest phase only."""
    rets: Dict[str, List[float]] = {}
    date_map: Dict[str, Dict[str, float]] = {}
    for book in BOOKS:
        spec = _SPEC[book]
        series = _build_backtest_series(spec)
        # series is a list of {"date": ..., "equity_usd": ..., "phase": ...}
        prev: Optional[float] = None
        day_rets: Dict[str, float] = {}
        for row in series:
            if row.get("phase") != "backtest":
                continue
            eq = float(row["equity_usd"])
            d  = str(row["date"])
            if prev is not None:
                day_rets[d] = eq / prev - 1.0
            prev = eq
        date_map[book] = day_rets
    common = sorted(set.intersection(*(set(date_map[b]) for b in BOOKS)))
    for b in BOOKS:
        rets[b] = [date_map[b][d] for d in common]
    return common, rets


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────

def _max_drawdown(curve: List[float]) -> float:
    hwm, mdd = max(curve[0], 1e-9), 0.0
    for v in curve:
        if v > hwm:
            hwm = v
        mdd = max(mdd, (hwm - v) / hwm)
    return mdd


def _calmar(apy_pct: float, mdd: float) -> float:
    return apy_pct / (mdd * 100.0) if mdd > 1e-9 else float("inf")


def _annualised(curve: List[float], n_days: int) -> float:
    if n_days < 1 or curve[0] < 1e-9:
        return 0.0
    return ((curve[-1] / curve[0]) ** (365.0 / n_days) - 1.0) * 100.0


def _crisis_dd(dated: List[Tuple[str, float]], window_key: str) -> float:
    lo, hi = "", ""
    for w in STRESS_WINDOWS:
        if w["key"] == window_key:
            lo, hi = str(w["date_from"]), str(w["date_to"])
            break
    sub = [v for d, v in dated if lo <= d <= hi]
    if not sub:
        return 0.0
    peak = sub[0]
    dd = 0.0
    for v in sub:
        if v > peak:
            peak = v
        dd = max(dd, (peak - v) / peak)
    return dd


# ── simulation ───────────────────────────────────────────────────────────────────────────────────

def _simulate_cmrs(
    dates: List[str],
    rets: Dict[str, List[float]],
    L: int,
    threshold: float = THRESHOLD,
    defend_frac: float = DEFEND_FRAC,
    roundtrip_bp_frac: float = ROUNDTRIP,
) -> dict:
    """
    Simulate CMRS on the fixture.

    Signal: rolling mean of EW portfolio returns over last L days (causal: using only t-1 data).
    State:  INVEST if rolling_mean > threshold, else DEFEND.
    Causality guaranteed: signal on day t uses ew_returns[t-L..t-1] (end-of-day t-1 close).

    Returns summary dict with APY, maxDD, Calmar, switches, narud_pct, crisis_dds.
    """
    n = len(dates)
    # Build EW daily return series (one scalar per day)
    ew_rets: List[float] = []
    for i in range(n):
        ew_rets.append(sum(rets[b][i] for b in BOOKS) / N_BOOKS)

    # Simulate
    eq             = INITIAL
    curve          = [eq]
    dated          = []
    n_switches     = 0
    n_defend_days  = 0
    in_defend      = False   # initial state: INVEST
    prev_risky_w   = 1.0     # fraction of portfolio in risky books at start of previous day

    for i in range(n):
        # Compute rolling mean using data UP TO AND INCLUDING day i-1 (causal)
        if i >= L:
            window_mean = sum(ew_rets[i - L : i]) / L
        else:
            # warm-up: not enough history → stay in INVEST (RWA floor would be penalizing
            # without information; this is conservative on the INVEST side, matching BISS #110)
            window_mean = 1.0  # any positive value → INVEST

        # Decide state for day i (decided by end of day i-1 → applied on day i)
        new_defend = window_mean <= threshold
        if new_defend != in_defend:
            n_switches += 1
        in_defend = new_defend

        if in_defend:
            n_defend_days += 1

        # Risky fraction in current state
        risky_w = defend_frac if in_defend else 1.0
        rwa_w   = 1.0 - risky_w

        # Transaction cost on weight change (proportional to |Δrisky_weight| × capital)
        delta_w = abs(risky_w - prev_risky_w)
        cost    = roundtrip_bp_frac * delta_w * eq

        # Portfolio return for day i
        risky_ret = sum(rets[b][i] for b in BOOKS) / N_BOOKS  # EW
        port_ret  = risky_w * risky_ret + rwa_w * RWA_DAILY

        eq = eq * (1.0 + port_ret) - cost
        curve.append(eq)
        dated.append((dates[i], eq))
        prev_risky_w = risky_w

    n_total   = n
    n_calm    = n_total - n_defend_days
    apy       = _annualised(curve, n_total)
    mdd       = _max_drawdown(curve)
    calmar    = _calmar(apy, mdd)

    crisis_dds = {}
    for w in STRESS_WINDOWS:
        crisis_dds[w["key"]] = _crisis_dd(dated, w["key"])

    return {
        "apy_pct":     apy,
        "max_dd_pct":  mdd * 100.0,
        "calmar":      calmar,
        "switches":    n_switches,
        "narud_pct":   100.0 * n_defend_days / n_total,
        "n_calm_days": n_calm,
        "n_total":     n_total,
        "crisis_dds":  crisis_dds,
        "curve":       curve,
        "dated":       dated,
    }


def _simulate_ew(
    dates: List[str],
    rets: Dict[str, List[float]],
) -> dict:
    """EW baseline — no switching."""
    eq    = INITIAL
    curve = [eq]
    dated = []
    n     = len(dates)
    for i in range(n):
        r = sum(rets[b][i] for b in BOOKS) / N_BOOKS
        eq *= (1.0 + r)
        curve.append(eq)
        dated.append((dates[i], eq))
    apy    = _annualised(curve, n)
    mdd    = _max_drawdown(curve)
    calmar = _calmar(apy, mdd)
    crisis_dds = {w["key"]: _crisis_dd(dated, w["key"]) for w in STRESS_WINDOWS}
    return {
        "apy_pct":    apy,
        "max_dd_pct": mdd * 100.0,
        "calmar":     calmar,
        "switches":   0,
        "narud_pct":  0.0,
        "crisis_dds": crisis_dds,
        "curve":      curve,
        "dated":      dated,
    }


def _simulate_1day(
    dates: List[str],
    rets: Dict[str, List[float]],
    n_recover: int = 3,
    defend_frac: float = DEFEND_FRAC,
    roundtrip_bp_frac: float = ROUNDTRIP,
) -> dict:
    """Replicate BISS 1DAY signal for direct comparison."""
    n = len(dates)
    eq            = INITIAL
    curve         = [eq]
    dated         = []
    n_switches    = 0
    n_defend_days = 0
    in_defend     = False
    consec_good   = 0
    prev_risky_w  = 1.0

    for i in range(n):
        # Entry: any book negative yesterday
        if i > 0:
            any_neg = any(rets[b][i - 1] < 0 for b in BOOKS)
        else:
            any_neg = False

        if not in_defend and any_neg:
            in_defend     = True
            consec_good   = 0
            n_switches   += 1
        elif in_defend:
            all_pos = all(rets[b][i - 1] >= 0 for b in BOOKS) if i > 0 else False
            if all_pos:
                consec_good += 1
            else:
                consec_good = 0
            if consec_good >= n_recover:
                in_defend     = False
                consec_good   = 0
                n_switches   += 1

        if in_defend:
            n_defend_days += 1

        risky_w = defend_frac if in_defend else 1.0
        rwa_w   = 1.0 - risky_w
        delta_w = abs(risky_w - prev_risky_w)
        cost    = roundtrip_bp_frac * delta_w * eq
        risky_ret = sum(rets[b][i] for b in BOOKS) / N_BOOKS
        port_ret  = risky_w * risky_ret + rwa_w * RWA_DAILY
        eq = eq * (1.0 + port_ret) - cost
        curve.append(eq)
        dated.append((dates[i], eq))
        prev_risky_w = risky_w

    apy    = _annualised(curve, n)
    mdd    = _max_drawdown(curve)
    calmar = _calmar(apy, mdd)
    crisis_dds = {w["key"]: _crisis_dd(dated, w["key"]) for w in STRESS_WINDOWS}
    return {
        "apy_pct":    apy,
        "max_dd_pct": mdd * 100.0,
        "calmar":     calmar,
        "switches":   n_switches,
        "narud_pct":  100.0 * n_defend_days / n,
        "crisis_dds": crisis_dds,
    }


# ── train/test split helper ───────────────────────────────────────────────────────────────────────

def _split(
    dates: List[str],
    rets: Dict[str, List[float]],
    split_date: str,
) -> Tuple[Tuple[List[str], Dict[str, List[float]]], Tuple[List[str], Dict[str, List[float]]]]:
    idx = next((i for i, d in enumerate(dates) if d > split_date), len(dates))
    train_dates = dates[:idx]
    test_dates  = dates[idx:]
    train_rets  = {b: rets[b][:idx]  for b in BOOKS}
    test_rets   = {b: rets[b][idx:]  for b in BOOKS}
    return (train_dates, train_rets), (test_dates, test_rets)


# ── switch count comparison at 0 bp (structural check) ───────────────────────────────────────────

def _count_switches_cmrs(
    dates: List[str],
    rets: Dict[str, List[float]],
    L: int,
    threshold: float = 0.0,
) -> Tuple[int, float]:
    """Return (n_switches, narud_pct) without cost (structural, 0-bp)."""
    r = _simulate_cmrs(dates, rets, L, threshold=threshold, roundtrip_bp_frac=0.0)
    return r["switches"], r["narud_pct"]


# ── main ─────────────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    dates, rets = _load_daily_rets()
    n = len(dates)

    print("=" * 78)
    print("CMRS — Carry Momentum Regime Switch  [bt][L0]  IS_ADVISORY=True")
    print(f"Fixture: {dates[0]} … {dates[-1]}  ({n} backtest days, {N_BOOKS} books, 96 bp)")
    print("=" * 78)

    # ── 1. EW baseline ──────────────────────────────────────────────────────────────────────────
    ew = _simulate_ew(dates, rets)
    print(f"\nBASELINE  EW (no switching):  "
          f"APY {ew['apy_pct']:+.2f}%  maxDD {ew['max_dd_pct']:.2f}%  Calmar {ew['calmar']:.3f}  "
          f"switches 0  narud 0.0%")
    for w in STRESS_WINDOWS:
        key = w["key"]
        print(f"  {key}: {ew['crisis_dds'][key]*100:.2f}%")

    # ── 2. 1DAY from BISS (direct comparison) ───────────────────────────────────────────────────
    one = _simulate_1day(dates, rets, roundtrip_bp_frac=ROUNDTRIP)
    print(f"\n1DAY (BISS #110, 96 bp):  "
          f"APY {one['apy_pct']:+.2f}%  maxDD {one['max_dd_pct']:.2f}%  Calmar {one['calmar']:.3f}  "
          f"switches {one['switches']}  narud {one['narud_pct']:.1f}%")
    for w in STRESS_WINDOWS:
        key = w["key"]
        print(f"  {key}: {one['crisis_dds'][key]*100:.2f}%")

    # ── 3. CMRS grid ────────────────────────────────────────────────────────────────────────────
    print(f"\n{'L':>4} {'APY%':>8} {'maxDD%':>8} {'Calmar':>8} {'switches':>9} {'narud%':>8}  "
          + "  ".join(w["key"][:8] for w in STRESS_WINDOWS))
    print("-" * 78)

    best_L, best_calmar, best_row = L_GRID[0], -999.0, None
    rows = {}
    for L in L_GRID:
        r = _simulate_cmrs(dates, rets, L, roundtrip_bp_frac=ROUNDTRIP)
        rows[L] = r
        line = (f"{L:>4}  {r['apy_pct']:>+7.2f}%  {r['max_dd_pct']:>6.2f}%  "
                f"{r['calmar']:>7.3f}  {r['switches']:>8}  {r['narud_pct']:>6.1f}%")
        for w in STRESS_WINDOWS:
            line += f"  {r['crisis_dds'][w['key']]*100:>6.2f}%"
        print(line)
        if r["calmar"] > best_calmar:
            best_calmar = r["calmar"]
            best_L = L
            best_row = r

    # ── 4. Structural check: switch counts at 0 bp ──────────────────────────────────────────────
    print(f"\n--- Switch count at 0 bp (structural, no cost) ---")
    for L in L_GRID:
        sw, nd = _count_switches_cmrs(dates, rets, L)
        print(f"  L={L:>2}: {sw:>3} switches  narud {nd:.1f}%")

    # ── 5. TRAIN/TEST split ──────────────────────────────────────────────────────────────────────
    (tr_d, tr_r), (te_d, te_r) = _split(dates, rets, SPLIT)
    print(f"\n--- TRAIN/TEST split at {SPLIT} ---")
    print(f"  Train: {tr_d[0]} .. {tr_d[-1]}  ({len(tr_d)} days)")
    print(f"  Test:  {te_d[0]} .. {te_d[-1]}  ({len(te_d)} days)")
    print(f"  (selecting best L on TRAIN, printing TEST as-is)")
    print()

    # Find best L on TRAIN
    best_train_L, best_train_calmar = L_GRID[0], -999.0
    train_results = {}
    for L in L_GRID:
        r = _simulate_cmrs(tr_d, tr_r, L, roundtrip_bp_frac=ROUNDTRIP)
        train_results[L] = r
        if r["calmar"] > best_train_calmar:
            best_train_calmar = r["calmar"]
            best_train_L = L

    print(f"  Best L on TRAIN: L={best_train_L}  (Calmar {best_train_calmar:.3f})")

    # EW train/test
    ew_tr = _simulate_ew(tr_d, tr_r)
    ew_te = _simulate_ew(te_d, te_r)
    print(f"\n  {'':>4} {'TRAIN Calmar':>14} {'TEST Calmar':>12}")
    print(f"  {'EW':>4} {ew_tr['calmar']:>14.3f} {ew_te['calmar']:>12.3f}")

    for L in L_GRID:
        tr = train_results[L]
        te = _simulate_cmrs(te_d, te_r, L, roundtrip_bp_frac=ROUNDTRIP)
        marker = " ← selected on train" if L == best_train_L else ""
        print(f"  L={L:<3} {tr['calmar']:>14.3f} {te['calmar']:>12.3f}{marker}")

    # ── 6. Summary ──────────────────────────────────────────────────────────────────────────────
    assert best_row is not None
    print(f"\n{'=' * 78}")
    print(f"SUMMARY [bt][L0]  (best L={best_L} on full period, 96 bp, DEFEND=ZERO)")
    print(f"  EW baseline:  APY {ew['apy_pct']:+.2f}%  maxDD {ew['max_dd_pct']:.2f}%  "
          f"Calmar {ew['calmar']:.3f}")
    print(f"  1DAY (BISS):  APY {one['apy_pct']:+.2f}%  maxDD {one['max_dd_pct']:.2f}%  "
          f"Calmar {one['calmar']:.3f}  switches {one['switches']}")
    print(f"  CMRS L={best_L}:   APY {best_row['apy_pct']:+.2f}%  maxDD {best_row['max_dd_pct']:.2f}%  "
          f"Calmar {best_row['calmar']:.3f}  switches {best_row['switches']}  "
          f"narud {best_row['narud_pct']:.1f}%")
    print()
    delta_vs_ew  = best_row["calmar"] - ew["calmar"]
    delta_vs_1d  = best_row["calmar"] - one["calmar"]
    print(f"  ΔCalmar vs EW:  {delta_vs_ew:+.3f}")
    print(f"  ΔCalmar vs 1DAY: {delta_vs_1d:+.3f}")
    print()
    print("HONEST CAVEATS:")
    print("  [bt][L0] deterministic fixture, σ²=0 in calm → zero false positives on fixture.")
    print("  Best L selected on full period → overfit risk; use TRAIN split for unbiased estimate.")
    print("  Fixture has structured front-loaded crisis losses; on real data distribution differs.")
    print("  96 bp round-trip: no slippage, gas, or capacity.")
    print("  IS_ADVISORY=True / OUTSIDE_RISKPOLICY=True. No live track touched.")
    print(f"{'=' * 78}")


if __name__ == "__main__":
    main()
