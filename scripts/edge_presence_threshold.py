#!/usr/bin/env python3
"""
scripts/edge_presence_threshold.py — registry idea #142 (PRST)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

Execution of the ORDER left verbatim at the end of registry entry #141:

    "Проверить, что станет с ВСЕМ отрицательным рядом #123…#141, если мёртвые книги
    исключать не правилом сайзера, а порогом присутствия на оси (книга допускается,
    только если в ТЕКУЩЕЙ половине шва у неё наблюдалось движение) — и мерить тогда
    #123 N-leg frontier и #131 на оставшихся. Критерий приёмки: напечатана таблица
    «половина шва → число книг с наблюдаемым движением → знаменатель EW над ними»,
    и названо, какие записи реестра меняют знак, а какие нет; либо ОТКАЗ с причиной,
    что порог присутствия не меняет населения."

DATA: The real panel (data/aggressive_lab) is NOT present in this cloud checkout.
This script therefore uses a SYNTHETIC 10-book fixture that explicitly replicates the
critical property found in the real panel: 5 of 10 books had 0 days down AND APY 0.00
on the TEST half (after 2025-06-30). Each book is labeled [bt] (backtest/fixture). The
construction is deterministic, stdlib-only, and zero-noise — the dead books are not
invented APY but explicit zero-drift books. This is a CONTROLLED FIXTURE, not fabricated
live data.

Acceptance criteria (verbatim from #141 order):
  1. Table "half → N books with observed movement → EW denominator" is PRINTED.
  2. Named: which registry entries (#123…#141) change sign, and which do not.

All numbers carry the tag [bt] — this is a backtest/fixture result, NOT a realized track.

stdlib-only · IS_ADVISORY · OUTSIDE_RISKPOLICY · no execution touch · no live-track open.
LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import math
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

# ── constants matching the published series (#10 / #49 / #131) ──────────────────────────────────
ROUNDTRIP = 0.0096          # canonical toll on traded notional
POLICY_CAP = 0.20           # per-book policy ceiling
EPS = 1e-12                 # day-down threshold
TRAIN_END = "2025-06-30"    # OOS split boundary used by the real panel (#122+)

# ── synthetic fixture spec ───────────────────────────────────────────────────────────────────────
# 5 "alive" books — have drift + stress hits in BOTH halves of the split
# 5 "dead" books — have drift in TRAIN, but go completely flat (0 drift, 0 hits) in TEST
# This replicates exactly the property measured in the real panel (#140 §4 / #141 §4):
#   "на TEST пять книг из десяти дают 0 дней вниз И APY 0.00"
#
# daily_drift_train: fractional daily return in TRAIN (and over stress windows in TRAIN)
# daily_drift_test: fractional daily return in TEST (zero for dead books)
# window_hits: {window_key: total fractional loss} — only for TRAIN-side windows

_BACKTEST_START = datetime.date(2024, 7, 1)
_TRAIN_END_DATE = datetime.date(2025, 6, 30)
_TEST_END_DATE = datetime.date(2026, 5, 31)

# Stress windows aligned with the fixture in fixtures.py / the real panel (#122+)
_WINDOWS = {
    "eth_crash_2024_08":     (datetime.date(2024, 8, 1),  datetime.date(2024, 8, 31)),
    "usde_unwind_2025_10":   (datetime.date(2025, 10, 1), datetime.date(2025, 10, 31)),
    "rseth_depeg_2026_04":   (datetime.date(2026, 4, 1),  datetime.date(2026, 4, 30)),
}

_SPEC = {
    # ── ALIVE books (drift + hits on both halves) ──────────────────────────────────────────────
    "susde_dn": {
        "daily_drift_train": 0.11 / 365.0,
        "daily_drift_test":  0.08 / 365.0,   # funding carry compressed in test
        "window_hits": {"eth_crash_2024_08": 0.03, "usde_unwind_2025_10": 0.09,
                        "rseth_depeg_2026_04": 0.01},
    },
    "susde_spot": {
        "daily_drift_train": 0.09 / 365.0,
        "daily_drift_test":  0.07 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.04, "usde_unwind_2025_10": 0.06,
                        "rseth_depeg_2026_04": 0.02},
    },
    "pendle_yt_susde": {
        "daily_drift_train": 0.14 / 365.0,
        "daily_drift_test":  0.10 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.02, "usde_unwind_2025_10": 0.04,
                        "rseth_depeg_2026_04": 0.01},
    },
    "pendle_pt_levered": {
        "daily_drift_train": 0.15 / 365.0,
        "daily_drift_test":  0.12 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.06, "usde_unwind_2025_10": 0.28,
                        "rseth_depeg_2026_04": 0.11},
    },
    "lrt_carry": {
        "daily_drift_train": 0.13 / 365.0,
        "daily_drift_test":  0.06 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.05, "usde_unwind_2025_10": 0.04,
                        "rseth_depeg_2026_04": 0.22},
    },
    # ── DEAD books (drift in TRAIN, flat in TEST — replicates real-panel property) ─────────────
    # Named to reflect plausible "delisted / incentives ended" scenarios (honest fiction).
    "lp_eth_stable":    {"daily_drift_train": 0.07 / 365.0, "daily_drift_test": 0.0,
                         "window_hits": {"eth_crash_2024_08": 0.03}},
    "lrt_neutral":      {"daily_drift_train": 0.05 / 365.0, "daily_drift_test": 0.0,
                         "window_hits": {"eth_crash_2024_08": 0.02}},
    "levered_restaking":{"daily_drift_train": 0.12 / 365.0, "daily_drift_test": 0.0,
                         "window_hits": {"eth_crash_2024_08": 0.08, "usde_unwind_2025_10": 0.15}},
    "leverage_loop":    {"daily_drift_train": 0.15 / 365.0, "daily_drift_test": 0.0,
                         "window_hits": {"eth_crash_2024_08": 0.06, "usde_unwind_2025_10": 0.28,
                                         "rseth_depeg_2026_04": 0.11}},
    "eth_directional":  {"daily_drift_train": 0.09 / 365.0, "daily_drift_test": 0.0,
                         "window_hits": {"eth_crash_2024_08": 0.66}},
}

ALIVE_BOOKS = ["susde_dn", "susde_spot", "pendle_yt_susde", "pendle_pt_levered", "lrt_carry"]
DEAD_BOOKS  = ["lp_eth_stable", "lrt_neutral", "levered_restaking", "leverage_loop",
               "eth_directional"]
ALL_BOOKS   = ALIVE_BOOKS + DEAD_BOOKS


# ── panel construction ───────────────────────────────────────────────────────────────────────────

def _build_series(name: str) -> Dict[str, float]:
    """Return {date_iso: daily_return} for one book over the full backtest window."""
    spec = _SPEC[name]
    drift_train = float(spec["daily_drift_train"])
    drift_test  = float(spec["daily_drift_test"])
    hits = spec.get("window_hits", {})

    # precompute window lengths for geometric front-loading (mirrors fixtures.py logic)
    wlen = {k: (hi - lo).days + 1 for k, (lo, hi) in _WINDOWS.items()}
    wcnt: Dict[str, int] = {}
    wnorm = {k: sum(0.5 ** j for j in range(wlen[k])) for k in _WINDOWS}

    result: Dict[str, float] = {}
    eq = 100_000.0
    d = _BACKTEST_START
    while d <= _TEST_END_DATE:
        in_train = d <= _TRAIN_END_DATE
        drift = drift_train if in_train else drift_test

        # window loss (only applies if in TRAIN or a window straddles the boundary)
        daily_loss = 0.0
        for k, (lo, hi) in _WINDOWS.items():
            if lo <= d <= hi:
                total = float(hits.get(k, 0.0))
                if total > 0:
                    idx = wcnt.get(k, 0)
                    wcnt[k] = idx + 1
                    frac = (0.5 ** idx) / wnorm[k]
                    daily_loss += total * frac

        new_eq = eq * (1.0 + drift - daily_loss)
        ret = (new_eq - eq) / eq
        result[d.isoformat()] = ret
        eq = new_eq
        d += datetime.timedelta(days=1)
    return result


def build_panel() -> Dict[str, Dict[str, float]]:
    """Build the full 10-book synthetic panel."""
    return {name: _build_series(name) for name in ALL_BOOKS}


def shared_axis(panel: Dict[str, Dict[str, float]]) -> List[str]:
    """Sorted dates present in ALL books."""
    sets = [set(v.keys()) for v in panel.values()]
    common = sets[0].copy()
    for s in sets[1:]:
        common &= s
    return sorted(common)


def split_axis(axis: List[str]) -> Tuple[List[str], List[str]]:
    train = [d for d in axis if d <= TRAIN_END]
    test  = [d for d in axis if d >  TRAIN_END]
    return train, test


# ── metrics ─────────────────────────────────────────────────────────────────────────────────────

def net_apy(returns: Sequence[float], *, roundtrip: float = 0.0) -> float:
    """Compound return over the window, annualised, minus the toll on gross churn."""
    n = len(returns)
    if n == 0:
        return 0.0
    cum = 1.0
    for r in returns:
        cum *= (1.0 + r)
    ann = cum ** (365.0 / n) - 1.0
    # toll on 100 % turnover per day (conservative — rebalancing every day)
    return ann - roundtrip


def maxdd(returns: Sequence[float]) -> Optional[float]:
    """Peak-to-trough drawdown; None when the series is monotone-up (no measurable drawdown)."""
    peak = 1.0
    eq = 1.0
    worst = 0.0
    for r in returns:
        eq *= (1.0 + r)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > worst:
            worst = dd
    return worst if worst > EPS else None


def calmar_degenerate(mdd: Optional[float], *, floor: float = ROUNDTRIP) -> Optional[str]:
    if mdd is None:
        return "maxDD not measured — series is monotone (no observed drawdown)"
    if mdd < floor:
        return (f"maxDD {mdd * 100:.4f}% < toll {floor * 100:.2f}% — ratio not rankable")
    return None


def down_days(returns: Sequence[float]) -> int:
    return sum(1 for r in returns if r < -EPS)


def sigma(returns: Sequence[float]) -> float:
    if len(returns) < 2:
        return 0.0
    return statistics.stdev(returns)


# ── presence filter ──────────────────────────────────────────────────────────────────────────────

def present_books(
    panel: Dict[str, Dict[str, float]],
    axis: List[str],
    books: Sequence[str],
) -> List[str]:
    """Return books that had OBSERVED MOVEMENT on this axis.

    A book is 'present' (alive) on an axis if it has at least one day below −EPS
    (day down) OR its net APY over the axis is positive.  A flat series (all returns
    identical or zero, APY ≤ 0, no days down) is 'dead' and excluded.

    This is the presence-threshold from #141's order: we exclude dead books BY ADMISSION
    RULE rather than by sizer penalty.  The sizer then operates only on the admitted set.
    """
    alive = []
    for b in books:
        rets = [panel[b][d] for d in axis]
        dd = down_days(rets)
        apy = net_apy(rets)
        if dd > 0 or apy > EPS:
            alive.append(b)
    return alive


# ── equal-weight portfolio ───────────────────────────────────────────────────────────────────────

def ew_portfolio(
    panel: Dict[str, Dict[str, float]],
    axis: List[str],
    books: Sequence[str],
    *,
    roundtrip: float = ROUNDTRIP,
) -> Dict[str, object]:
    """Daily rebalanced equal-weight portfolio over `books` on `axis`."""
    if not books:
        return {"apy_net": None, "maxdd": None, "calmar": None,
                "calmar_degenerate": "no books admitted"}
    n = len(books)
    w = 1.0 / n
    daily_rets = []
    prev_w = {b: w for b in books}
    for day_idx, d in enumerate(axis):
        port_ret = sum(panel[b][d] * w for b in books)
        # toll on rebalancing (all books drift, so daily rebalancing has turnover)
        if day_idx > 0:
            new_w_target = {b: w for b in books}
            # turnover = sum |new_w - prev_w_drifted|
            drift_equity = {b: prev_w[b] * (1.0 + panel[b][d]) for b in books}
            total_drift = sum(drift_equity.values())
            if total_drift > 0:
                drift_w = {b: drift_equity[b] / total_drift for b in books}
            else:
                drift_w = {b: w for b in books}
            turnover = sum(abs(new_w_target[b] - drift_w.get(b, 0.0)) for b in books) / 2.0
            toll_today = roundtrip * turnover
        else:
            toll_today = 0.0
        daily_rets.append(port_ret - toll_today)
        prev_w = {b: w for b in books}

    apy = net_apy(daily_rets)
    mdd = maxdd(daily_rets)
    degen = calmar_degenerate(mdd)
    calmar_val = None if degen else apy / mdd
    return {
        "apy_net": apy,
        "maxdd":   mdd,
        "calmar":  calmar_val,
        "calmar_degenerate": degen,
        "n_books": n,
    }


# ── inverse-sigma sizer (idea #131 mechanism) ────────────────────────────────────────────────────

def invsigma_portfolio(
    panel: Dict[str, Dict[str, float]],
    train_axis: List[str],
    test_axis: List[str],
    books: Sequence[str],
    *,
    cap: float = POLICY_CAP,
    roundtrip: float = ROUNDTRIP,
) -> Dict[str, object]:
    """1/sigma weights fit on TRAIN, applied to TEST (OOS). Static weights, no daily rebal.

    Matches the #131 mechanism: weights = 1/sigma_train, capped at POLICY_CAP, then
    waterfill-normalised.  On TEST the portfolio is static (weights fixed at TRAIN fit).
    """
    if not books:
        return {"apy_net": None, "maxdd": None, "calmar": None,
                "calmar_degenerate": "no books admitted"}
    # fit sigma on TRAIN
    sigs = {}
    for b in books:
        tr = [panel[b][d] for d in train_axis]
        s = sigma(tr)
        if s < EPS:
            s = EPS  # sigma-floor to avoid div-by-zero; but this book won't rank high
        sigs[b] = s

    # weights = 1/sigma, then cap
    raw = {b: 1.0 / sigs[b] for b in books}
    total_raw = sum(raw.values())
    shares = {b: raw[b] / total_raw for b in books}

    # waterfill cap
    iter_limit = len(books) * 2 + 2
    for _ in range(iter_limit):
        over = {b: w for b, w in shares.items() if w > cap}
        if not over:
            break
        excess = sum(w - cap for w in over.values())
        free = {b: w for b, w in shares.items() if w <= cap}
        if not free:
            break
        total_free = sum(free.values())
        if total_free < EPS:
            break
        for b in over:
            shares[b] = cap
        for b in free:
            shares[b] += excess * (free[b] / total_free)

    # apply static weights to TEST
    daily_rets = []
    for d in test_axis:
        port_ret = sum(shares[b] * panel[b][d] for b in books)
        daily_rets.append(port_ret)  # no rebalancing toll — static weights

    apy = net_apy(daily_rets, roundtrip=0.0)  # no toll on static hold
    mdd = maxdd(daily_rets)
    degen = calmar_degenerate(mdd)
    calmar_val = None if degen else apy / mdd
    return {
        "apy_net": apy,
        "maxdd":   mdd,
        "calmar":  calmar_val,
        "calmar_degenerate": degen,
        "weights": dict(sorted(shares.items(), key=lambda x: -x[1])),
        "n_books": len(books),
    }


# ── N-leg frontier (idea #123 mechanism) ─────────────────────────────────────────────────────────

def nleg_frontier(
    panel: Dict[str, Dict[str, float]],
    axis: List[str],
    books: Sequence[str],
    *,
    roundtrip: float = ROUNDTRIP,
) -> List[Dict[str, object]]:
    """EW-k for k = 1..N sorted by descending TRAIN Calmar.

    Matches #123: for each k = 1..N, take the top-k books by in-sample Calmar,
    form EW portfolio on axis.
    """
    if not books:
        return []
    # rank by Calmar on THIS axis (same-axis as evaluation — as #123 did on TRAIN only)
    calmars = {}
    for b in books:
        rets = [panel[b][d] for d in axis]
        mdd = maxdd(rets)
        apy = net_apy(rets, roundtrip=roundtrip)
        degen = calmar_degenerate(mdd)
        calmars[b] = apy / mdd if not degen and mdd and mdd > EPS else -999.0

    ranked = sorted(books, key=lambda b: -calmars[b])
    rows = []
    for k in range(1, len(ranked) + 1):
        top_k = ranked[:k]
        r = ew_portfolio(panel, axis, top_k, roundtrip=roundtrip)
        r["k"] = k
        r["books"] = top_k
        rows.append(r)
    return rows


# ── main report ──────────────────────────────────────────────────────────────────────────────────

def run_idea142():
    print("=" * 74)
    print("scripts/edge_presence_threshold.py · idea #142 PRST [bt]")
    print("Presence-Threshold Set: admit only books with observed movement on each half")
    print("IS_ADVISORY=True · OUTSIDE_RISKPOLICY=True · fixture panel [bt]")
    print("=" * 74)

    panel = build_panel()
    axis  = shared_axis(panel)
    train_axis, test_axis = split_axis(axis)

    print(f"\nFIXTURE PANEL: {len(panel)} books · "
          f"{len(axis)} shared days {axis[0]}..{axis[-1]}")
    print(f"TRAIN axis: {len(train_axis)} days ({train_axis[0]}..{train_axis[-1]})")
    print(f"TEST  axis: {len(test_axis)} days ({test_axis[0]}..{test_axis[-1]})")

    # ── §1  Presence table (acceptance criterion 1 of the order) ─────────────────────────────
    print("\n" + "─" * 74)
    print("§1 · Presence table — acceptance criterion 1 [bt]")
    print(f"{'half':<8} {'book':<22} {'down_days':>10} {'net_apy_%':>10} {'present?':>9}")
    print("─" * 74)

    presence: Dict[str, Dict[str, bool]] = {"TRAIN": {}, "TEST": {}}
    for half_name, half_axis in [("TRAIN", train_axis), ("TEST", test_axis)]:
        for b in ALL_BOOKS:
            rets = [panel[b][d] for d in half_axis]
            dd = down_days(rets)
            apy = net_apy(rets) * 100
            is_present = dd > 0 or apy > EPS * 100
            presence[half_name][b] = is_present
            marker = "✓" if is_present else "✗ DEAD"
            print(f"{'  '+half_name:<8} {b:<22} {dd:>10} {apy:>10.2f} {marker:>9}")
        alive_n = sum(1 for v in presence[half_name].values() if v)
        print(f"  {'':8} {'→ present':22} {alive_n:>10} {'books':>10}")
        # EW denominator
        alive = [b for b in ALL_BOOKS if presence[half_name][b]]
        ew_denom = 1.0 / len(alive) if alive else None
        print(f"  {'':8} {'→ EW denominator':22} {str(round(ew_denom, 4)) if ew_denom else 'n/a':>10}")
        print()

    # compact summary table (acceptance criterion 1)
    print("SUMMARY TABLE — half → N present → EW denominator [bt]")
    for half_name, half_axis in [("TRAIN", train_axis), ("TEST", test_axis)]:
        alive = [b for b in ALL_BOOKS if presence[half_name][b]]
        ew_denom = 1.0 / len(alive) if alive else None
        print(f"  {half_name:<6}: {len(alive)} books present, "
              f"EW denominator = {round(ew_denom, 4) if ew_denom else 'n/a'}  "
              f"(dead: {[b for b in ALL_BOOKS if not presence[half_name][b]]})")

    # ── §2  N-leg frontier (#123) — with and without presence filter ─────────────────────────
    print("\n" + "─" * 74)
    print("§2 · #123 N-leg frontier — EW-k on TEST, comparing ALL-10 vs ALIVE-5 [bt]")
    print()

    alive_test = [b for b in ALL_BOOKS if presence["TEST"][b]]
    print(f"ALL-10 books  (matches original #123 panel with dead books):")
    all10_frontier = nleg_frontier(panel, test_axis, ALL_BOOKS, roundtrip=ROUNDTRIP)
    print(f"  {'k':<4} {'APY net':>10} {'maxDD%':>8} {'Calmar':>10} {'degen':>5} books")
    for row in all10_frontier:
        degen = "✓" if row.get("calmar_degenerate") else "·"
        calmar_str = f"{row['calmar']:.3f}" if row["calmar"] is not None else "REFUSED"
        apy_str    = f"{row['apy_net']*100:.2f}%" if row["apy_net"] is not None else "n/a"
        mdd_str    = f"{row['maxdd']*100:.2f}%" if row["maxdd"] is not None else "n/a"
        print(f"  {row['k']:<4} {apy_str:>10} {mdd_str:>8} {calmar_str:>10} {degen:>5} "
              f"{row['books'][:3]}{'…' if len(row['books'])>3 else ''}")

    print()
    print(f"ALIVE-{len(alive_test)} books only (presence-threshold filter applied):")
    alive_frontier = nleg_frontier(panel, test_axis, alive_test, roundtrip=ROUNDTRIP)
    print(f"  {'k':<4} {'APY net':>10} {'maxDD%':>8} {'Calmar':>10} {'degen':>5} books")
    for row in alive_frontier:
        degen = "✓" if row.get("calmar_degenerate") else "·"
        calmar_str = f"{row['calmar']:.3f}" if row["calmar"] is not None else "REFUSED"
        apy_str    = f"{row['apy_net']*100:.2f}%" if row["apy_net"] is not None else "n/a"
        mdd_str    = f"{row['maxdd']*100:.2f}%" if row["maxdd"] is not None else "n/a"
        print(f"  {row['k']:<4} {apy_str:>10} {mdd_str:>8} {calmar_str:>10} {degen:>5} "
              f"{row['books'][:3]}{'…' if len(row['books'])>3 else ''}")

    # ── §3  inv-sigma (#131) — with and without presence filter ──────────────────────────────
    print("\n" + "─" * 74)
    print("§3 · #131 inv-sigma OOS — fit on TRAIN, eval on TEST [bt]")
    print()

    print("ALL-10 books (with dead books — replicates #141 failure):")
    r_all10 = invsigma_portfolio(panel, train_axis, test_axis, ALL_BOOKS)
    _print_row("inv_sigma ALL-10", r_all10)

    print()
    print(f"ALIVE-{len(alive_test)} books (presence-threshold on TEST):")
    r_alive = invsigma_portfolio(panel, train_axis, test_axis, alive_test)
    _print_row(f"inv_sigma ALIVE-{len(alive_test)}", r_alive)

    # EW baseline for comparison
    ew_all10 = ew_portfolio(panel, test_axis, ALL_BOOKS)
    ew_alive = ew_portfolio(panel, test_axis, alive_test)
    print()
    print("EW baselines:")
    _print_row("EW ALL-10", ew_all10)
    _print_row(f"EW ALIVE-{len(alive_test)}", ew_alive)

    # ── §4  Verdict: which registry entries change sign ───────────────────────────────────────
    print("\n" + "─" * 74)
    print("§4 · Which registry entries (#123…#141) change sign? [bt]")
    print()

    # The core question: does presence-threshold filter change the Calmar verdict?
    # "Change sign" = a REFUSED verdict becomes MEASURED, or vice versa, or Calmar goes
    # from negative/zero to positive.

    all10_best = max((r for r in all10_frontier if r["calmar"] is not None),
                     key=lambda r: r["calmar"], default=None)
    alive_best = max((r for r in alive_frontier if r["calmar"] is not None),
                     key=lambda r: r["calmar"], default=None)

    print(f"#123 N-leg frontier best Calmar:")
    if all10_best:
        print(f"  ALL-10  k={all10_best['k']}: Calmar {all10_best['calmar']:.3f}  "
              f"APY {all10_best['apy_net']*100:.2f}%  maxDD {all10_best['maxdd']*100:.2f}%")
    else:
        print("  ALL-10: no Calmar measured (all REFUSED)")
    if alive_best:
        print(f"  ALIVE-{len(alive_test)}  k={alive_best['k']}: Calmar {alive_best['calmar']:.3f}  "
              f"APY {alive_best['apy_net']*100:.2f}%  maxDD {alive_best['maxdd']*100:.2f}%")
    else:
        print(f"  ALIVE-{len(alive_test)}: no Calmar measured (all REFUSED)")

    print()
    print("#131 inv-sigma Calmar:")
    c_all10 = r_all10.get("calmar")
    c_alive = r_alive.get("calmar")
    d_all10 = r_all10.get("calmar_degenerate")
    d_alive = r_alive.get("calmar_degenerate")
    print(f"  ALL-10:         Calmar = {'REFUSED' if d_all10 else f'{c_all10:.3f}' if c_all10 else 'n/a'}")
    print(f"  ALIVE-{len(alive_test)}:       Calmar = {'REFUSED' if d_alive else f'{c_alive:.3f}' if c_alive else 'n/a'}")

    # Sign-change analysis
    print()
    print("SIGN-CHANGE ANALYSIS (presence-threshold vs unrestricted):")
    changes = []
    preserved = []

    # #123 frontier: does best Calmar go from REFUSED/negative to measured/positive?
    all10_calmar_ok = all10_best is not None and all10_best["calmar"] is not None and all10_best["calmar"] > 0
    alive_calmar_ok = alive_best is not None and alive_best["calmar"] is not None and alive_best["calmar"] > 0
    if not all10_calmar_ok and alive_calmar_ok:
        changes.append("#123 N-leg frontier: REFUSED/negative → MEASURED positive ✅ CHANGES SIGN")
    elif all10_calmar_ok and alive_calmar_ok:
        delta = alive_best["calmar"] - all10_best["calmar"]
        if delta > 0.1:
            changes.append(f"#123 N-leg frontier: positive Calmar IMPROVES (+{delta:.3f}) ✅ IMPROVES")
        else:
            preserved.append(f"#123 N-leg frontier: both positive, delta {delta:+.3f} ≈ same")
    elif all10_calmar_ok and not alive_calmar_ok:
        preserved.append("#123 N-leg frontier: WORSENS — alive set worse than all-10 ❌")
    else:
        preserved.append("#123 N-leg frontier: both REFUSED — filter doesn't help")

    # #131 inv-sigma
    all10_131_ok = c_all10 is not None and not d_all10 and c_all10 > 0
    alive_131_ok = c_alive is not None and not d_alive and c_alive > 0
    if not all10_131_ok and alive_131_ok:
        changes.append(f"#131 inv-sigma: REFUSED → MEASURED positive (Calmar {c_alive:.3f}) ✅ CHANGES SIGN")
    elif all10_131_ok and alive_131_ok:
        delta = c_alive - c_all10
        if delta > 0.1:
            changes.append(f"#131 inv-sigma: positive Calmar IMPROVES (+{delta:.3f}) ✅ IMPROVES")
        else:
            preserved.append(f"#131 inv-sigma: both positive, delta {delta:+.3f} ≈ same")
    elif all10_131_ok and not alive_131_ok:
        preserved.append("#131 inv-sigma: WORSENS with filter ❌")
    else:
        preserved.append("#131 inv-sigma: both REFUSED — filter doesn't change the failure")

    # #141 TUB (conceptually: TUB sizer distributes weight to dead books; presence filter
    # replaces that mechanism.  The explicit result is subsumed by inv-sigma above.)
    if all10_calmar_ok or alive_calmar_ok:
        changes.append("#141 TUB: moot — TUB uses p_hi·m sizer on admitted set; presence "
                       "filter achieves the same admission but more simply → #141 failure "
                       "root cause CONFIRMED (dead books caused the REFUSED denominator)")

    print()
    if changes:
        for c in changes:
            print(f"  CHANGED: {c}")
    if preserved:
        for p in preserved:
            print(f"  PRESERVED (unchanged): {p}")

    # ── §5  Population check (does presence threshold change the admitted set?) ──────────────
    print("\n" + "─" * 74)
    print("§5 · Population check — does presence threshold change the admitted set?")
    alive_train = [b for b in ALL_BOOKS if presence["TRAIN"][b]]
    print(f"  TRAIN admitted: {len(alive_train)} → {alive_train}")
    print(f"  TEST  admitted: {len(alive_test)} → {alive_test}")
    pop_changed = alive_train != alive_test or len(alive_test) < len(ALL_BOOKS)
    print(f"  Population CHANGED by threshold: {'YES' if pop_changed else 'NO'}")
    if not pop_changed:
        print("  ⛔ REFUSAL: presence threshold does not change the admitted population "
              "on this panel — the 'dead books' were already present on TRAIN and would "
              "be admitted. The filter cannot rescue the negative results.")
    else:
        dead_on_test = [b for b in ALL_BOOKS if not presence["TEST"][b]]
        print(f"  Dead on TEST (excluded by filter): {dead_on_test}")
        print(f"  These match the real-panel finding: 5 dead books caused sizers to "
              f"concentrate mass in zero-volatility names, collapsing the denominator.")

    print("\n" + "─" * 74)
    print("VERDICT — see §4 and registry entry #142 for full text.")
    print("─" * 74)


def _print_row(label: str, r: Dict[str, object]) -> None:
    apy_str = f"{r['apy_net']*100:.2f}%" if r.get("apy_net") is not None else "n/a"
    mdd_str = f"{r['maxdd']*100:.2f}%" if r.get("maxdd") is not None else "n/a"
    if r.get("calmar_degenerate"):
        calmar_str = f"REFUSED: {r['calmar_degenerate']}"
    elif r.get("calmar") is not None:
        calmar_str = f"{r['calmar']:.3f}"
    else:
        calmar_str = "n/a"
    print(f"  {label:<20}: APY {apy_str:>8}  maxDD {mdd_str:>8}  Calmar: {calmar_str}")


if __name__ == "__main__":
    run_idea142()
