#!/usr/bin/env python3
"""Edge R&D — registry idea #53 (CQR): Carry Quality Ratio.

DATA NOTE: The real 10-book panel used by #32–#52 lives in data/aggressive_lab/ which is
gitignored. This script uses the CODE-GENERATED fixture from
spa_core/strategy_lab/aggressive_lab/fixtures.py — deterministic, stdlib-only, no files needed.
The fixture provides 5 books with ~700 days of real-shaped history (2024-07..2026-05) covering
all three major DeFi crises: ETH-crash 2024-08, USDe-unwind 2025-10, rsETH-depeg 2026-04.

Numbers marked [bt] are BACKTEST on synthetic fixture data (evidence L0), NOT live realized.

WHERE THIS COMES FROM
  Forty entries (#1–#52) built and stress-tested one family of book-selection rules. The winning
  configuration is #40 XSD (ranks books by trailing mean return / drift; demotes bottom-k).
  The key unanswered question: what if the QUALITY of carry matters as much as its quantity?
  Two books with equal mean returns differ if one achieves that mean via smooth daily accrual and
  the other via fat-tailed crises. XSD cannot distinguish them. CQR can.

──────────────────────────────────────────────────────────────────────────────────────────────
IDEA #53 — CQR: Carry Quality Ratio   ("is the carry smooth or lumpy?")
──────────────────────────────────────────────────────────────────────────────────────────────

      score_CQR(b, t) = mean(r_b[t-L:t-1]) / max(std(r_b[t-L:t-1]), ε)

  A within-window Sharpe-like ratio (no risk-free subtraction — we're comparing RELATIVE
  carry quality across books, not absolute excess return). ε = 5e-5 daily (≈1.8% ann. vol floor).

  CQR hypothesis: a book with high, smooth carry ranks higher than one with equal or higher
  mean return but fat-tailed, crisis-volatile distribution. In a DeFi universe where crisis
  losses dominate daily std, this should systematically downrank leveraged / liquidation-prone
  books and uprank delta-neutral stablecoin strategies.

  DEMOTION RULE: identical to #40 XSD — bottom-k demoted, re-admitted after M quiet days.
  ALLOCATOR: equal-weight over non-demoted books; demoted books' capital recycled to survivors.
  COST MODEL: 96 bp round-trip per switch (same as #10/#49 family).

  STRUCTURAL LIMIT (same as #40): 100% capital deployed at all times. CQR cannot de-risk
  against common shocks — it can only rotate WHICH books receive the capital.

  CONTROLS (non-negotiable):
  1. TOP-K FLIP — demote the BEST-CQR books. Must lose to CQR worst-demote.
  2. XSD REFERENCE — same k, M, L; same panel; CQR must beat or tie.
  3. TRAIN/TEST SPLIT — generalisation check (≤2025-06-30 / >2025-06-30).
  4. LEAVE-ONE-OUT — concentration check.

  PREDICTED OUTCOMES (written before numbers):
  A. CQR > XSD by ΔCalmar > 0.5 on both halves → genuine quality signal.
  B. CQR > XSD train, drops test → overfit.
  C. CQR ≈ XSD → drift dominates; vol of drift adds nothing at L=60.
  D. CQR < XSD → quality ratio hurts (e.g. downranks high-carry books in calm periods
     when vol is temporarily low and the signal is noise).

HONESTY / SCOPE
  IS_ADVISORY = True · OUTSIDE_RISKPOLICY = True · LLM_FORBIDDEN · stdlib-only
  No execution code imported. No data/ writes. RiskPolicy v1.0 untouched. Capital does not move.
  Evidence L0 — backtest on synthetic fixture; numbers marked [bt], never presented as live.

Usage:
    python3 scripts/edge_carry_quality_ratio.py           # full run
    python3 scripts/edge_carry_quality_ratio.py --tt      # train/test only
    python3 scripts/edge_carry_quality_ratio.py --loo     # leave-one-out only
    python3 scripts/edge_carry_quality_ratio.py --audit   # score audit only
"""
# LLM_FORBIDDEN
# IS_ADVISORY = True
# OUTSIDE_RISKPOLICY = True
from __future__ import annotations

import argparse
import datetime
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# ─── make spa_core importable ────────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS

# ─── constants ───────────────────────────────────────────────────────────────────────────────────
LOOKBACK: int = 60          # same as #40 XSD — NOT re-tuned
VOL_FLOOR: float = 5e-5    # daily vol floor ≈ 1.83% ann; prevents div/0
COST_BP_RT: float = 96.0   # round-trip cost per book per switch, basis points (#10/#49)
TRAIN_END: str = "2025-06-30"
BP: float = 10_000.0


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# FIXTURE DATA (deterministic, real-shaped — no files, no network, no fabrication)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

# Per-book daily drift and crisis hits, mirroring spa_core/strategy_lab/aggressive_lab/fixtures.py.
# `thin_new` (no backtest) excluded. 5 books remain.
_SPEC: Dict[str, dict] = {
    "susde_dn": {
        "daily_drift": 11.0 / 100.0 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.03, "usde_unwind_2025_10": 0.09,
                        "rseth_depeg_2026_04": 0.01},
    },
    "lrt_carry": {
        "daily_drift": 13.0 / 100.0 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.05, "usde_unwind_2025_10": 0.04,
                        "rseth_depeg_2026_04": 0.22},
    },
    "leverage_loop": {
        "daily_drift": 15.0 / 100.0 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.06, "usde_unwind_2025_10": 0.28,
                        "rseth_depeg_2026_04": 0.11},
    },
    "points_farm": {
        "daily_drift": 14.0 / 100.0 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.01, "usde_unwind_2025_10": 0.02,
                        "rseth_depeg_2026_04": 0.015},
    },
    "variant_d": {
        "daily_drift": 9.0 / 100.0 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.18, "usde_unwind_2025_10": 0.10,
                        "rseth_depeg_2026_04": 0.20},
    },
}

_BT_START = datetime.date(2024, 7, 1)
_BT_END = datetime.date(2026, 5, 31)


def _window_key(d: datetime.date) -> Optional[str]:
    for w in STRESS_WINDOWS:
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        if lo <= d <= hi:
            return w["key"]
    return None


def _build_rets(spec: dict, axis: List[str]) -> List[float]:
    """Deterministic daily returns: drift + front-loaded crisis losses, mirroring fixtures.py."""
    drift = spec["daily_drift"]
    hits = spec["window_hits"]

    # count days per window to front-load
    win_days: Dict[str, List[int]] = {}
    for i, ds in enumerate(axis):
        k = _window_key(datetime.date.fromisoformat(ds))
        if k and k in hits:
            win_days.setdefault(k, []).append(i)

    # pre-compute per-day loss: front-loaded as geometric decay over window
    extra_loss: List[float] = [0.0] * len(axis)
    for wk, idxs in win_days.items():
        total = hits[wk]
        n = len(idxs)
        # geometric: day-0 gets 40% of total loss, remainder distributed evenly
        if n == 0:
            continue
        front = total * 0.4
        tail_each = (total - front) / max(n - 1, 1)
        extra_loss[idxs[0]] += front
        for idx in idxs[1:]:
            extra_loss[idx] += tail_each

    rets: List[float] = []
    for i in range(len(axis)):
        r = drift - extra_loss[i]
        rets.append(r)
    return rets


def build_panel() -> Tuple[List[str], Dict[str, List[float]]]:
    """Build the fixture panel: returns (axis of date-strings, {book: [daily_returns]})."""
    axis: List[str] = []
    d = _BT_START
    while d <= _BT_END:
        axis.append(d.isoformat())
        d += datetime.timedelta(days=1)
    rets = {b: _build_rets(spec, axis) for b, spec in _SPEC.items()}
    return axis, rets


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# STATISTICS UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

def trailing_mean(r: Sequence[float], L: int) -> List[Optional[float]]:
    """Mean over the previous L days (through t-1). None if fewer than L points exist."""
    out: List[Optional[float]] = []
    for i in range(len(r)):
        if i < L:
            out.append(None)
        else:
            w = r[i - L:i]
            out.append(sum(w) / len(w))
    return out


def trailing_std(r: Sequence[float], L: int) -> List[Optional[float]]:
    """Sample std over the previous L days (through t-1). None if fewer than L points exist."""
    out: List[Optional[float]] = []
    for i in range(len(r)):
        if i < L:
            out.append(None)
        else:
            w = r[i - L:i]
            mu = sum(w) / len(w)
            var = sum((x - mu) ** 2 for x in w) / (len(w) - 1)
            out.append(math.sqrt(var))
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# SCORING CRITERIA
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

Scores = Dict[str, List[Optional[float]]]


def xsd_scores(rets: Dict[str, List[float]], L: int = LOOKBACK) -> Scores:
    """#40 XSD criterion: trailing mean return (drift). None before L days warm-up."""
    return {b: trailing_mean(r, L) for b, r in rets.items()}


def cqr_scores(rets: Dict[str, List[float]], L: int = LOOKBACK,
               vfloor: float = VOL_FLOOR) -> Scores:
    """#53 CQR criterion: trailing mean / max(trailing std, vfloor). None before L days warm-up."""
    out: Scores = {}
    for b, r in rets.items():
        mu_s = trailing_mean(r, L)
        sd_s = trailing_std(r, L)
        scores_b: List[Optional[float]] = []
        for i in range(len(r)):
            if mu_s[i] is None or sd_s[i] is None:
                scores_b.append(None)
            else:
                vol = max(float(sd_s[i]), vfloor)   # type: ignore[arg-type]
                scores_b.append(float(mu_s[i]) / vol)  # type: ignore[arg-type]
        out[b] = scores_b
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# RANK DEMOTION STATE MACHINE (mirrors edge_cross_sectional_demotion.rank_demotion_flags)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

def rank_demotion_flags(scores: Scores, k: int, readmit_days: int = 1,
                        worst_first: bool = True) -> Dict[str, List[bool]]:
    """Demote bottom-k books by score each day; re-admit after readmit_days out of bottom-k.

    Fail-CLOSED: fewer than k+1 rankable books → nobody changes state.
    None scores → book not rankable (cannot be demoted that day).
    Ties broken by book name for reproducibility.
    """
    books = sorted(scores)
    if k < 1 or k >= len(books):
        raise ValueError(f"k={k} invalid for {len(books)} books")
    n = len(scores[books[0]])
    sign = 1.0 if worst_first else -1.0

    demoted = {b: False for b in books}
    good_run = {b: 0 for b in books}
    out: Dict[str, List[bool]] = {b: [] for b in books}

    for i in range(n):
        rankable = [b for b in books if scores[b][i] is not None]
        if len(rankable) <= k:
            for b in books:
                out[b].append(demoted[b])   # state frozen
            continue
        ordered = sorted(rankable, key=lambda b: (sign * float(scores[b][i]), b))  # type: ignore
        bottom = set(ordered[:k])
        for b in books:
            in_bottom = b in bottom
            good_run[b] = 0 if in_bottom else good_run[b] + 1
            if demoted[b]:
                if good_run[b] >= readmit_days:
                    demoted[b] = False
            elif in_bottom:
                demoted[b] = True
            out[b].append(demoted[b])
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# ALLOCATOR + METRICS
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

def alloc_recycle(books: List[str], flags: Dict[str, List[bool]], n: int) -> Dict[str, List[float]]:
    """Equal-weight among non-demoted books; demoted books get weight 0.
    Their capital is recycled proportionally to the non-demoted survivors.
    If ALL books are demoted: all get equal weight (fail-safe, should not happen with rank rule).
    """
    weights: Dict[str, List[float]] = {b: [] for b in books}
    for i in range(n):
        eligible = [b for b in books if not flags[b][i]]
        w = 1.0 / len(eligible) if eligible else 1.0 / len(books)
        for b in books:
            weights[b].append(w if b in eligible else 0.0)
    return weights


def portfolio_metrics(books: List[str], rets: Dict[str, List[float]],
                      weights: Dict[str, List[float]], n: int) -> Dict[str, float]:
    """APY, maxDD, Calmar, duty, switches/yr, netAPY after turnover cost."""
    pf: List[float] = [
        sum(weights[b][i] * rets[b][i] for b in books)
        for i in range(n)
    ]

    # equity path and perf
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in pf:
        eq *= 1.0 + r
        if eq > peak:
            peak = eq
        dd = eq / peak - 1.0
        if dd < mdd:
            mdd = dd

    apy = eq ** (365.0 / n) - 1.0 if (n > 0 and eq > 0) else -1.0
    calmar = apy / abs(mdd) if mdd < 0 else float("inf")

    # duty: fraction of (book, day) cells with weight ~0
    demoted_cells = sum(1 for b in books for i in range(n) if weights[b][i] < 0.01)
    duty = demoted_cells / (len(books) * n) if books and n > 0 else 0.0

    # switches: transitions from 0→1 or 1→0 per book, averaged across books
    def switches(ws: List[float]) -> int:
        return sum(1 for i in range(1, len(ws)) if (ws[i] < 0.01) != (ws[i-1] < 0.01))

    total_sw = sum(switches(weights[b]) for b in books)
    sw_yr = total_sw / len(books) * 365.0 / n if books else 0.0
    cost_bp_yr = sw_yr * COST_BP_RT
    net_apy = apy - cost_bp_yr / BP

    return {
        "apy": apy, "maxdd": mdd, "calmar": calmar,
        "duty": duty, "switches_yr": sw_yr, "net_apy": net_apy,
        "cost_bp_yr": cost_bp_yr,
    }


def raw_metrics(books: List[str], rets: Dict[str, List[float]], n: int) -> Dict[str, float]:
    """Equal-weight portfolio with no overlay."""
    w = {b: [1.0 / len(books)] * n for b in books}
    return portfolio_metrics(books, rets, w, n)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# PRINT HELPERS
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

def _hdr(title: str, n: int, axis: List[str], books: List[str], base: Dict[str, float]) -> None:
    print()
    print("=" * 110)
    print(f"{title}  ·  {n} days {axis[0]}..{axis[-1]}  ·  {len(books)} books [bt]")
    print("=" * 110)
    print(f"raw (no overlay) [bt]: APY {base['apy']*100:.2f}%  maxDD {base['maxdd']*100:.2f}%"
          f"  Calmar {base['calmar']:.2f}  netAPY {base['net_apy']*100:.2f}%")
    print(f"{'configuration':34s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>8s}"
          f" {'ΔAPY':>7s} {'ΔDD':>7s} {'ΔCalmar':>8s}"
          f" {'duty':>6s} {'sw/yr':>6s} {'netAPY':>8s}")


def _row(name: str, m: Dict[str, float], base: Dict[str, float]) -> None:
    print(f"{name:34s} {m['apy']*100:7.2f}% {m['maxdd']*100:7.2f}% {m['calmar']:8.2f}"
          f" {(m['apy']-base['apy'])*100:6.2f} {(m['maxdd']-base['maxdd'])*100:6.2f}"
          f" {m['calmar']-base['calmar']:8.2f}"
          f" {m['duty']*100:5.1f}% {m['switches_yr']:6.1f} {m['net_apy']*100:7.2f}%")


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# MAIN BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

def run_backtest(axis: List[str], rets: Dict[str, List[float]],
                 books: List[str], label: str = "FULL",
                 ks: Sequence[int] = (1, 2, 3),
                 ms: Sequence[int] = (1, 20),
                 quiet: bool = False) -> Dict[str, Dict[str, float]]:
    n = len(axis)
    base = raw_metrics(books, rets, n)
    _hdr(f"IDEA #53 CQR — [{label}]", n, axis, books, base)

    sc_cqr = cqr_scores(rets)
    sc_xsd = xsd_scores(rets)

    results: Dict[str, Dict[str, float]] = {}
    for k in ks:
        for m_days in ms:
            for crit, label_s, sc, flip in [
                ("CQR", f"CQR k={k} M={m_days}", sc_cqr, False),
                ("CQR-FLIP", f"  FLIP k={k} M={m_days}", sc_cqr, True),
                ("XSD", f"  XSD(#40) k={k} M={m_days}", sc_xsd, False),
            ]:
                if crit == "CQR-FLIP" and quiet:
                    continue
                fl = rank_demotion_flags(sc, k, m_days, worst_first=not flip)
                w = alloc_recycle(books, fl, n)
                m = portfolio_metrics(books, rets, w, n)
                results[label_s.strip()] = m
                _row(label_s, m, base)

    return results


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# TRAIN / TEST SPLIT
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

def train_test() -> None:
    full_axis, full_rets = build_panel()
    books = sorted(full_rets)

    print()
    print("=" * 110)
    print(f"IDEA #53 CQR — TRAIN (≤{TRAIN_END}) / TEST (>{TRAIN_END})")
    print("=" * 110)
    print(f"{'config':30s} {'trAPY':>8s} {'trCalmar':>8s} {'ΔtrCal':>8s}"
          f" {'teAPY':>8s} {'teCalmar':>8s} {'ΔteCal':>8s}")

    ks, ms = (1, 2), (1, 20)
    for k in ks:
        for m_days in ms:
            for crit, sc_fn, tag in [
                ("CQR", cqr_scores, f"CQR k={k} M={m_days}"),
                ("XSD", xsd_scores, f"  XSD k={k} M={m_days}"),
            ]:
                row_parts: List[Tuple[str, float, float, float]] = []
                for split_end, split_start in [(TRAIN_END, None), (None, TRAIN_END)]:
                    ax = [d for d in full_axis
                          if (split_end is None or d <= split_end) and
                          (split_start is None or d > split_start)]
                    r = {b: [full_rets[b][i] for i, d in enumerate(full_axis) if d in set(ax)]
                         for b in books}
                    n = len(ax)
                    base = raw_metrics(books, r, n)
                    sc = sc_fn(r)
                    fl = rank_demotion_flags(sc, k, m_days)
                    w = alloc_recycle(books, fl, n)
                    m = portfolio_metrics(books, r, w, n)
                    row_parts.append((ax[0], m["apy"], m["calmar"],
                                      m["calmar"] - base["calmar"]))
                (_, tr_apy, tr_cal, tr_dc), (_, te_apy, te_cal, te_dc) = row_parts[0], row_parts[1]
                print(f"{tag:30s} {tr_apy*100:7.2f}% {tr_cal:8.2f} {tr_dc:+8.2f}"
                      f" {te_apy*100:7.2f}% {te_cal:8.2f} {te_dc:+8.2f}")


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# LEAVE-ONE-OUT
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

def leave_one_out(k: int = 2, m_days: int = 20) -> None:
    full_axis, full_rets = build_panel()
    books = sorted(full_rets)
    n = len(full_axis)

    base_full = raw_metrics(books, full_rets, n)
    fl_cqr = rank_demotion_flags(cqr_scores(full_rets), k, m_days)
    m_cqr = portfolio_metrics(books, full_rets, alloc_recycle(books, fl_cqr, n), n)
    fl_xsd = rank_demotion_flags(xsd_scores(full_rets), k, m_days)
    m_xsd = portfolio_metrics(books, full_rets, alloc_recycle(books, fl_xsd, n), n)

    print()
    print("=" * 110)
    print(f"IDEA #53 CQR — LEAVE-ONE-OUT  k={k} M={m_days}  [bt]")
    print(f"Full: CQR Calmar={m_cqr['calmar']:.2f} netAPY={m_cqr['net_apy']*100:.2f}%"
          f"  |  XSD Calmar={m_xsd['calmar']:.2f} netAPY={m_xsd['net_apy']*100:.2f}%")
    print("=" * 110)
    print(f"{'dropped':22s} {'CQRCalmar':>10s} {'XSDCalmar':>10s}"
          f" {'ΔCQR-XSD':>10s} {'CQRnetAPY':>10s} {'XSDnetAPY':>10s}")

    for drop in books:
        sub = [b for b in books if b != drop]
        sub_rets = {b: full_rets[b] for b in sub}
        nb = len(sub_rets[sub[0]])
        base_s = raw_metrics(sub, sub_rets, nb)

        fl_c = rank_demotion_flags(cqr_scores(sub_rets), k, m_days)
        mc = portfolio_metrics(sub, sub_rets, alloc_recycle(sub, fl_c, nb), nb)
        fl_x = rank_demotion_flags(xsd_scores(sub_rets), k, m_days)
        mx = portfolio_metrics(sub, sub_rets, alloc_recycle(sub, fl_x, nb), nb)

        print(f"  drop {drop:16s} {mc['calmar']:>9.2f} {mx['calmar']:>9.2f}"
              f" {mc['calmar']-mx['calmar']:>+9.2f}"
              f" {mc['net_apy']*100:>9.2f}% {mx['net_apy']*100:>9.2f}%")


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# SCORE AUDIT — what IS CQR ranking?
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

def score_audit() -> None:
    """Average CQR vs XSD score per book. Sanity check: do crisis books rank lower under CQR?"""
    _, rets = build_panel()
    books = sorted(rets)
    sc_cqr = cqr_scores(rets)
    sc_xsd = xsd_scores(rets)

    def mean_valid(s: List[Optional[float]]) -> float:
        v = [x for x in s if x is not None]
        return sum(v) / len(v) if v else float("nan")

    book_cqr = {b: mean_valid(sc_cqr[b]) for b in books}
    book_xsd = {b: mean_valid(sc_xsd[b]) for b in books}

    cqr_ord = sorted(books, key=lambda b: book_cqr[b], reverse=True)
    xsd_ord = sorted(books, key=lambda b: book_xsd[b], reverse=True)

    print()
    print("=" * 110)
    print("SCORE AUDIT — mean score per book, CQR vs XSD ranking (higher = better candidate to KEEP)")
    print("=" * 110)
    print(f"{'book':24s} {'CQR score':>12s} {'XSD drift(bp/d)':>16s} {'CQR rank':>10s} {'XSD rank':>10s}")
    for b in sorted(books):
        cr = cqr_ord.index(b) + 1
        xr = xsd_ord.index(b) + 1
        note = ""
        if cr < xr:
            note = f"↑ CQR upgrades (was XSD#{xr})"
        elif cr > xr:
            note = f"↓ CQR demotes (was XSD#{xr})"
        print(f"  {b:22s} {book_cqr[b]:12.4f} {book_xsd[b]*BP:14.4f} bp/d"
              f"  CQR#{cr}   {note}")

    print()
    print("CQR order (best→worst):", " > ".join(cqr_ord))
    print("XSD order (best→worst):", " > ".join(xsd_ord))


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# CRISIS WINDOW BREAKDOWN
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

def crisis_breakdown(k: int = 2, m_days: int = 20) -> None:
    """CQR vs XSD performance inside each stress window vs calm periods."""
    full_axis, full_rets = build_panel()
    books = sorted(full_rets)
    n = len(full_axis)

    sc_cqr = cqr_scores(full_rets)
    sc_xsd = xsd_scores(full_rets)

    fl_cqr = rank_demotion_flags(sc_cqr, k, m_days)
    fl_xsd = rank_demotion_flags(sc_xsd, k, m_days)

    w_cqr = alloc_recycle(books, fl_cqr, n)
    w_xsd = alloc_recycle(books, fl_xsd, n)
    w_raw = {b: [1.0 / len(books)] * n for b in books}

    def pf_rets(w: Dict[str, List[float]]) -> List[float]:
        return [sum(w[b][i] * full_rets[b][i] for b in books) for i in range(n)]

    r_cqr = pf_rets(w_cqr)
    r_xsd = pf_rets(w_xsd)
    r_raw = pf_rets(w_raw)

    windows = {w["key"]: (w["date_from"], w["date_to"]) for w in STRESS_WINDOWS}

    def window_ret(rets: List[float], wkey: str) -> float:
        lo = windows[wkey][0]
        hi = windows[wkey][1]
        eq = 1.0
        for i, ds in enumerate(full_axis):
            if lo <= ds <= hi:
                eq *= 1.0 + rets[i]
        return eq - 1.0

    print()
    print("=" * 90)
    print(f"CRISIS WINDOW BREAKDOWN  k={k} M={m_days}  [bt]")
    print("=" * 90)
    print(f"{'window':30s} {'raw':>10s} {'XSD':>10s} {'CQR':>10s} {'ΔCQR-XSD':>12s}")
    for wkey in ("eth_crash_2024_08", "usde_unwind_2025_10", "rseth_depeg_2026_04"):
        lo, hi = windows[wkey]
        rr = window_ret(r_raw, wkey)
        rx = window_ret(r_xsd, wkey)
        rc = window_ret(r_cqr, wkey)
        print(f"  {wkey:28s} {rr*100:9.2f}% {rx*100:9.2f}% {rc*100:9.2f}% {(rc-rx)*100:+11.2f}%")

    # calm (not in any window)
    win_dates = set()
    for wkey, (lo, hi) in windows.items():
        for ds in full_axis:
            if lo <= ds <= hi:
                win_dates.add(ds)
    calm_idx = [i for i, ds in enumerate(full_axis) if ds not in win_dates]

    def calm_apy(rets: List[float]) -> float:
        eq = 1.0
        for i in calm_idx:
            eq *= 1.0 + rets[i]
        nd = len(calm_idx)
        return eq ** (365.0 / nd) - 1.0 if nd > 0 else 0.0

    rr_c = calm_apy(r_raw)
    rx_c = calm_apy(r_xsd)
    rc_c = calm_apy(r_cqr)
    print(f"  {'CALM (all other days)':28s} {rr_c*100:9.2f}% {rx_c*100:9.2f}%"
          f" {rc_c*100:9.2f}% {(rc_c-rx_c)*100:+11.2f}%")


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(description="Idea #53 CQR: Carry Quality Ratio backtest [bt]")
    ap.add_argument("--tt", action="store_true", help="train/test split only")
    ap.add_argument("--loo", action="store_true", help="leave-one-out only")
    ap.add_argument("--audit", action="store_true", help="score audit only")
    ap.add_argument("--crisis", action="store_true", help="crisis breakdown only")
    args = ap.parse_args()

    if args.tt:
        train_test()
        return
    if args.loo:
        leave_one_out()
        return
    if args.audit:
        score_audit()
        return
    if args.crisis:
        crisis_breakdown()
        return

    axis, rets = build_panel()
    books = sorted(rets)
    n = len(axis)

    run_backtest(axis, rets, books, label="FULL [bt]")
    score_audit()
    train_test()
    leave_one_out()
    crisis_breakdown()

    print()
    print("─" * 110)
    print("ALL NUMBERS MARKED [bt] = BACKTEST on synthetic fixture, evidence L0, NOT live realized.")
    print(f"IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  VOL_FLOOR={VOL_FLOOR}  LOOKBACK={LOOKBACK}d")
    print("─" * 110)


if __name__ == "__main__":
    main()
