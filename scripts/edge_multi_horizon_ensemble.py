#!/usr/bin/env python3
"""Edge R&D — registry idea #64 (MHE): Multi-Horizon Ensemble Scoring.

DATA NOTE: Uses the CODE-GENERATED fixture from
spa_core/strategy_lab/aggressive_lab/fixtures.py — deterministic, stdlib-only, no files needed.
Fixture: 5 books, ~700 days (2024-07..2026-05), all three DeFi crises.

Numbers marked [bt] = BACKTEST on synthetic fixture (evidence L0), NOT live realized.

═══════════════════════════════════════════════════════════════════════════════════════════════
IDEA #64 — MHE: Multi-Horizon Ensemble Scoring   ("is the answer in the weighting of horizons?")
═══════════════════════════════════════════════════════════════════════════════════════════════

BACKGROUND
  Every cross-sectional criterion tested since #35 uses a SINGLE trailing window (L=60 days
  by convention). Entries #40–#55 vary the scoring metric, demotion logic, timing, and cash
  allocation — but never ask: "what if we blend signals at different timescales simultaneously?"

  The missing dimension:
    • L=20 (fast): reactive, catches crises early, noisy, re-admits quickly
    • L=60 (standard, baseline): the #40 XSD reference
    • L=180 (slow): stable, insensitive to short-term noise, slow to re-admit

  A simple CONVEX COMBINATION scores each book as:
        score_MHE(b, t) = α·mean_L20(b,t) + β·mean_L60(b,t) + γ·mean_L180(b,t)
  where α+β+γ=1. The rest of the allocation machine (rank demotion → equal-weight recycling,
  96 bp cost model) is unchanged — same code path as #40 XSD.

HYPOTHESES (written before numbers):
  H1. Equal weighting (α=β=γ=1/3) distributes exposure across timescales and dampens
      single-window sensitivity — may give more stable Calmar OOS.
  H2. Fast-heavy (α=0.50, β=0.35, γ=0.15) exits crises faster, improving maxDD;
      at the cost of more whipsawing → higher turnover.
  H3. Slow-heavy (α=0.15, β=0.35, γ=0.50) delays re-entry after crisis — lower Calmar
      during recovery, but fewer false positives.
  H4. Any single horizon (L=20 or L=180) is likely inferior to L=60 on the fixture due
      to the synthetic structure (constant drift outside windows).

CONTROLS:
  • XSD(L=60) — the existing #40 baseline; MHE must beat it to be an edge.
  • XSD(L=20) and XSD(L=180) — single-horizon references; MHE must beat all three.
  • TOP-K FLIP — demote BEST books; ensemble must lose to normal demotion.
  • TRAIN/TEST SPLIT (≤2025-06-30 / >2025-06-30).
  • LEAVE-ONE-OUT — check for single-book dependence.

HONESTY / SCOPE
  IS_ADVISORY = True · OUTSIDE_RISKPOLICY = True · LLM_FORBIDDEN · stdlib-only
  No execution code imported. No data/ writes. RiskPolicy v1.0 untouched.
  Capital does not move. Evidence L0.

Usage:
    python3 scripts/edge_multi_horizon_ensemble.py           # full run
    python3 scripts/edge_multi_horizon_ensemble.py --tt      # train/test only
    python3 scripts/edge_multi_horizon_ensemble.py --loo     # leave-one-out only
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

sys.path.insert(0, str(Path(__file__).parent.parent))
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS

# ─── constants ────────────────────────────────────────────────────────────────
L_FAST: int = 20
L_MID: int = 60      # same as #40 XSD
L_SLOW: int = 180
COST_BP_RT: float = 96.0   # round-trip cost per switch, basis points (#10/#49)
TRAIN_END: str = "2025-06-30"
BP: float = 10_000.0

# Ensemble weight sets to test: (α_fast, β_mid, γ_slow)
_MHE_CONFIGS: Dict[str, Tuple[float, float, float]] = {
    "MHE-equal": (1/3, 1/3, 1/3),
    "MHE-fast":  (0.50, 0.35, 0.15),
    "MHE-slow":  (0.15, 0.35, 0.50),
    "MHE-nofast": (0.00, 0.60, 0.40),
    "MHE-noslow": (0.40, 0.60, 0.00),
}

# ─── fixture spec (mirrors edge_carry_quality_ratio.py) ──────────────────────
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

# ─── panel builder ───────────────────────────────────────────────────────────

def _window_key(d: datetime.date) -> Optional[str]:
    for w in STRESS_WINDOWS:
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        if lo <= d <= hi:
            return w["key"]
    return None


def _build_rets(spec: dict, axis: List[str]) -> List[float]:
    drift = spec["daily_drift"]
    hits = spec["window_hits"]
    win_days: Dict[str, List[int]] = {}
    for i, ds in enumerate(axis):
        k = _window_key(datetime.date.fromisoformat(ds))
        if k and k in hits:
            win_days.setdefault(k, []).append(i)
    extra_loss: List[float] = [0.0] * len(axis)
    for wk, idxs in win_days.items():
        total = hits[wk]
        n = len(idxs)
        if n == 0:
            continue
        front = total * 0.4
        tail_each = (total - front) / max(n - 1, 1)
        extra_loss[idxs[0]] += front
        for idx in idxs[1:]:
            extra_loss[idx] += tail_each
    return [spec["daily_drift"] - extra_loss[i] for i in range(len(axis))]


def build_panel() -> Tuple[List[str], Dict[str, List[float]]]:
    axis: List[str] = []
    d = _BT_START
    while d <= _BT_END:
        axis.append(d.isoformat())
        d += datetime.timedelta(days=1)
    rets = {b: _build_rets(spec, axis) for b, spec in _SPEC.items()}
    return axis, rets


# ─── scoring ─────────────────────────────────────────────────────────────────

Scores = Dict[str, List[Optional[float]]]


def trailing_mean(r: Sequence[float], L: int) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for i in range(len(r)):
        if i < L:
            out.append(None)
        else:
            w = r[i - L:i]
            out.append(sum(w) / len(w))
    return out


def xsd_scores(rets: Dict[str, List[float]], L: int = L_MID) -> Scores:
    return {b: trailing_mean(r, L) for b, r in rets.items()}


def mhe_scores(
    rets: Dict[str, List[float]],
    alpha: float, beta: float, gamma: float,
) -> Scores:
    """Multi-Horizon Ensemble: α·mean_L20 + β·mean_L60 + γ·mean_L180.

    None if ANY of the required windows has insufficient data (fail-CLOSED: we refuse to score
    rather than using a partial signal — consistent with reestry invariant #2).
    L_SLOW=180 defines the warm-up period; a book must have 180 days of history before being
    ranked. This is STRICTER than XSD(L=60) — acknowledged tradeoff: later ranking starts,
    less data lost to warm-up effects.
    """
    out: Scores = {}
    for b, r in rets.items():
        m20 = trailing_mean(r, L_FAST)
        m60 = trailing_mean(r, L_MID)
        m180 = trailing_mean(r, L_SLOW)
        scores_b: List[Optional[float]] = []
        for i in range(len(r)):
            if m20[i] is None or m60[i] is None or m180[i] is None:
                scores_b.append(None)
            else:
                scores_b.append(
                    alpha * float(m20[i])
                    + beta * float(m60[i])
                    + gamma * float(m180[i])
                )
        out[b] = scores_b
    return out


# ─── rank demotion state machine ────────────────────────────────────────────

def rank_demotion_flags(
    scores: Scores, k: int, readmit_days: int = 1, worst_first: bool = True
) -> Dict[str, List[bool]]:
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
                out[b].append(demoted[b])
            continue
        ordered = sorted(rankable, key=lambda b: (sign * float(scores[b][i]), b))  # type: ignore[arg-type]
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


# ─── allocator + metrics ─────────────────────────────────────────────────────

def alloc_recycle(
    books: List[str], flags: Dict[str, List[bool]], n: int
) -> Dict[str, List[float]]:
    weights: Dict[str, List[float]] = {b: [] for b in books}
    for i in range(n):
        eligible = [b for b in books if not flags[b][i]]
        w = 1.0 / len(eligible) if eligible else 1.0 / len(books)
        for b in books:
            weights[b].append(w if b in eligible else 0.0)
    return weights


def portfolio_metrics(
    books: List[str], rets: Dict[str, List[float]],
    weights: Dict[str, List[float]], n: int
) -> Dict[str, float]:
    pf = [sum(weights[b][i] * rets[b][i] for b in books) for i in range(n)]
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
    demoted_cells = sum(1 for b in books for i in range(n) if weights[b][i] < 0.01)
    duty = demoted_cells / (len(books) * n) if books and n > 0 else 0.0
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
    w = {b: [1.0 / len(books)] * n for b in books}
    return portfolio_metrics(books, rets, w, n)


# ─── print helpers ───────────────────────────────────────────────────────────

def _hdr(title: str, n: int, axis: List[str], books: List[str], base: Dict[str, float]) -> None:
    print()
    print("=" * 115)
    print(f"{title}  ·  {n} days {axis[0]}..{axis[-1]}  ·  {len(books)} books [bt]")
    print("=" * 115)
    print(f"raw (equal-weight, no overlay) [bt]: APY {base['apy']*100:.2f}%  "
          f"maxDD {base['maxdd']*100:.2f}%  Calmar {base['calmar']:.2f}  "
          f"netAPY {base['net_apy']*100:.2f}%")
    print(f"{'configuration':38s} {'APY':>8s} {'maxDD':>8s} {'Calmar':>8s}"
          f" {'ΔAPY':>7s} {'ΔDD':>7s} {'ΔCalmar':>8s}"
          f" {'duty':>6s} {'sw/yr':>6s} {'netAPY':>8s}")


def _row(name: str, m: Dict[str, float], base: Dict[str, float]) -> None:
    print(f"{name:38s} {m['apy']*100:7.2f}% {m['maxdd']*100:7.2f}% {m['calmar']:8.2f}"
          f" {(m['apy']-base['apy'])*100:6.2f} {(m['maxdd']-base['maxdd'])*100:6.2f}"
          f" {m['calmar']-base['calmar']:8.2f}"
          f" {m['duty']*100:5.1f}% {m['switches_yr']:6.1f} {m['net_apy']*100:7.2f}%")


# ─── backtest runner ─────────────────────────────────────────────────────────

def run_backtest(
    axis: List[str], rets: Dict[str, List[float]], books: List[str],
    label: str = "FULL",
    ks: Sequence[int] = (1, 2),
    ms: Sequence[int] = (1, 20),
) -> Dict[str, Dict[str, float]]:
    n = len(axis)
    base = raw_metrics(books, rets, n)
    _hdr(f"IDEA #64 MHE — [{label}]", n, axis, books, base)

    # pre-compute all score sets (single + ensemble)
    sc_xsd20 = xsd_scores(rets, L=L_FAST)
    sc_xsd60 = xsd_scores(rets, L=L_MID)
    sc_xsd180 = xsd_scores(rets, L=L_SLOW)
    sc_mhe = {tag: mhe_scores(rets, a, b, g)
              for tag, (a, b, g) in _MHE_CONFIGS.items()}
    sc_flip60 = sc_xsd60  # flip reference uses same scores, different sorting

    results: Dict[str, Dict[str, float]] = {}

    for k in ks:
        for m_days in ms:
            print(f"\n  ─── k={k}  M={m_days} ───")

            # Single-horizon references
            for tag, sc in [
                (f"XSD(L=20)  k={k} M={m_days}", sc_xsd20),
                (f"XSD(L=60)  k={k} M={m_days}", sc_xsd60),
                (f"XSD(L=180) k={k} M={m_days}", sc_xsd180),
            ]:
                fl = rank_demotion_flags(sc, k, m_days)
                w = alloc_recycle(books, fl, n)
                m = portfolio_metrics(books, rets, w, n)
                results[tag] = m
                _row(tag, m, base)

            # MHE ensemble configurations
            for cfg_name, sc_m in sc_mhe.items():
                a_v, b_v, g_v = _MHE_CONFIGS[cfg_name]
                tag = f"{cfg_name}({a_v:.2f},{b_v:.2f},{g_v:.2f}) k={k} M={m_days}"
                fl = rank_demotion_flags(sc_m, k, m_days)
                w = alloc_recycle(books, fl, n)
                m = portfolio_metrics(books, rets, w, n)
                results[tag] = m
                _row(tag, m, base)

            # Flip control for XSD(L=60)
            tag_flip = f"  FLIP XSD(L=60)   k={k} M={m_days}"
            fl = rank_demotion_flags(sc_flip60, k, m_days, worst_first=False)
            w = alloc_recycle(books, fl, n)
            m = portfolio_metrics(books, rets, w, n)
            results[tag_flip] = m
            _row(tag_flip, m, base)

    return results


# ─── train/test split ────────────────────────────────────────────────────────

def train_test() -> None:
    full_axis, full_rets = build_panel()
    books = sorted(full_rets)

    print()
    print("=" * 115)
    print(f"IDEA #64 MHE — TRAIN (≤{TRAIN_END}) / TEST (>{TRAIN_END})")
    print("=" * 115)
    print(f"{'config':42s} {'trAPY':>8s} {'trCalmar':>8s} {'ΔtrCal':>8s}"
          f" {'teAPY':>8s} {'teCalmar':>8s} {'ΔteCal':>8s}")

    ks, ms = (1, 2), (1, 20)

    def _get_sc(full_rets: Dict[str, List[float]], kind: str) -> Scores:
        if kind == "XSD60":
            return xsd_scores(full_rets, L=L_MID)
        if kind == "XSD20":
            return xsd_scores(full_rets, L=L_FAST)
        if kind == "XSD180":
            return xsd_scores(full_rets, L=L_SLOW)
        a, b, g = _MHE_CONFIGS[kind]
        return mhe_scores(full_rets, a, b, g)

    configs = ["XSD20", "XSD60", "XSD180"] + list(_MHE_CONFIGS.keys())

    for k in ks:
        for m_days in ms:
            for kind in configs:
                full_sc = _get_sc(full_rets, kind)
                row_parts: List[Tuple[str, float, float, float]] = []
                for split_end, split_start in [(TRAIN_END, None), (None, TRAIN_END)]:
                    idx = [
                        i for i, d in enumerate(full_axis)
                        if (split_end is None or d <= split_end)
                        and (split_start is None or d > split_start)
                    ]
                    if not idx:
                        continue
                    ax_sl = [full_axis[i] for i in idx]
                    r_sl = {b: [full_rets[b][i] for i in idx] for b in books}
                    sc_sl = {b: [full_sc[b][i] for i in idx] for b in books}
                    n_sl = len(ax_sl)
                    base_sl = raw_metrics(books, r_sl, n_sl)
                    fl = rank_demotion_flags(sc_sl, k, m_days)
                    w = alloc_recycle(books, fl, n_sl)
                    m = portfolio_metrics(books, r_sl, w, n_sl)
                    row_parts.append((
                        ax_sl[0], m["apy"], m["calmar"],
                        m["calmar"] - base_sl["calmar"]
                    ))
                if len(row_parts) == 2:
                    name = f"{kind} k={k} M={m_days}"
                    (_d1, tr_apy, tr_cal, tr_dcal), (_d2, te_apy, te_cal, te_dcal) = row_parts
                    print(f"{name:42s} {tr_apy*100:7.2f}% {tr_cal:8.2f} {tr_dcal:+8.2f}"
                          f" {te_apy*100:7.2f}% {te_cal:8.2f} {te_dcal:+8.2f}")


# ─── leave-one-out ───────────────────────────────────────────────────────────

def leave_one_out() -> None:
    full_axis, full_rets = build_panel()
    books = sorted(full_rets)

    print()
    print("=" * 115)
    print("IDEA #64 MHE — LEAVE-ONE-OUT  (k=2, M=20)")
    print("=" * 115)

    k, m_days = 2, 20

    comparisons = {
        "XSD(L=60)": xsd_scores(full_rets, L=L_MID),
        "MHE-equal": mhe_scores(full_rets, 1/3, 1/3, 1/3),
        "MHE-fast":  mhe_scores(full_rets, 0.50, 0.35, 0.15),
    }

    header = f"{'dropped':16s}"
    for cfg_name in comparisons:
        header += f" {'Δ'+cfg_name+' Calmar':>18s}"
    print(header)

    for dropped in books:
        sub_books = [b for b in books if b != dropped]
        line = f"{dropped:16s}"
        for cfg_name, full_sc in comparisons.items():
            n = len(full_axis)
            r_sub = {b: full_rets[b] for b in sub_books}
            sc_sub = {b: full_sc[b] for b in sub_books}
            base_sub = raw_metrics(sub_books, r_sub, n)
            fl = rank_demotion_flags(sc_sub, k, m_days)
            w = alloc_recycle(sub_books, fl, n)
            m = portfolio_metrics(sub_books, r_sub, w, n)
            line += f" {m['calmar']-base_sub['calmar']:+18.2f}"
        print(line)


# ─── crisis window performance ───────────────────────────────────────────────

def crisis_windows() -> None:
    full_axis, full_rets = build_panel()
    books = sorted(full_rets)

    windows = [
        ("eth_crash_2024_08",   "2024-07-01", "2024-09-30"),
        ("usde_unwind_2025_10", "2025-09-01", "2025-11-30"),
        ("rseth_depeg_2026_04", "2026-03-01", "2026-05-31"),
    ]

    sc_xsd60 = xsd_scores(full_rets, L=L_MID)
    sc_mhe_eq = mhe_scores(full_rets, 1/3, 1/3, 1/3)
    sc_mhe_fast = mhe_scores(full_rets, 0.50, 0.35, 0.15)

    print()
    print("=" * 115)
    print("IDEA #64 MHE — CRISIS WINDOWS (k=2, M=20;  APY / maxDD / Calmar, [bt])")
    print("=" * 115)

    k, m_days = 2, 20
    comps = [("XSD(L=60)", sc_xsd60), ("MHE-equal", sc_mhe_eq), ("MHE-fast", sc_mhe_fast)]

    hdr = f"{'window':28s} {'metric':12s}"
    for n, _ in comps:
        hdr += f" {n:>16s}"
    print(hdr)

    for w_key, w_start, w_end in windows:
        idx = [i for i, d in enumerate(full_axis) if w_start <= d <= w_end]
        if not idx:
            continue
        ax_w = [full_axis[i] for i in idx]
        r_w = {b: [full_rets[b][i] for i in idx] for b in books}
        n_w = len(ax_w)

        for row_metric in ("APY", "maxDD", "Calmar"):
            line = f"{w_key if row_metric=='APY' else '':28s} {row_metric:12s}"
            for cfg_name, full_sc in comps:
                sc_w = {b: [full_sc[b][i] for i in idx] for b in books}
                base_w = raw_metrics(books, r_w, n_w)
                fl = rank_demotion_flags(sc_w, k, m_days)
                wts = alloc_recycle(books, fl, n_w)
                m = portfolio_metrics(books, r_w, wts, n_w)
                if row_metric == "APY":
                    line += f" {m['apy']*100:15.2f}%"
                elif row_metric == "maxDD":
                    line += f" {m['maxdd']*100:15.2f}%"
                else:
                    line += f" {m['calmar']:16.2f}"
            print(line)


# ─── entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Edge R&D idea #64: Multi-Horizon Ensemble")
    parser.add_argument("--tt", action="store_true", help="Train/test split only")
    parser.add_argument("--loo", action="store_true", help="Leave-one-out only")
    parser.add_argument("--crisis", action="store_true", help="Crisis windows only")
    args = parser.parse_args()

    full_axis, full_rets = build_panel()
    books = sorted(full_rets)

    print()
    print("EDGE R&D — IDEA #64  MHE: Multi-Horizon Ensemble Scoring")
    print("IS_ADVISORY=True  |  OUTSIDE_RISKPOLICY=True  |  LLM_FORBIDDEN  |  Evidence: L0 [bt]")
    print(f"Fixture: {len(books)} books  {len(full_axis)} days  {full_axis[0]}..{full_axis[-1]}")
    print(f"Horizons: L_fast={L_FAST}  L_mid={L_MID}  L_slow={L_SLOW}")
    print(f"Cost model: {COST_BP_RT} bp round-trip per switch  (from #10/#49)")
    print(f"Note: MHE requires L_slow={L_SLOW} days of warm-up — stricter than XSD(L=60).")

    if args.tt:
        train_test()
        return
    if args.loo:
        leave_one_out()
        return
    if args.crisis:
        crisis_windows()
        return

    # full run
    run_backtest(full_axis, full_rets, books, label="FULL")
    train_test()
    leave_one_out()
    crisis_windows()


if __name__ == "__main__":
    main()
