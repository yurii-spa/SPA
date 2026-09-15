"""
scripts/edge_downside_sharpe_demotion.py

Idea #108 — XDSR: Cross-Sectional Downside Sharpe Ranking
==========================================================
ADVISORY — backtest only.  NO imports from spa_core/execution/.  stdlib-only.

Edge hypothesis
---------------
XSD (#40) demotes by mean return (trailing drift) alone — same demotion target in calm AND
in crisis.  XVD (#45) demotes by total volatility — ignores drift direction.  MRD (#41)
demotes by proportion of negative days — ignores magnitude.  DSP (#105) re-weights by
1/σ_down (ALLOCATION weights, not k-book DEMOTION).

XDSR ranks books by the trailing Sortino ratio: μ_L / (σ_down_L + ε)
where σ_down = std of the NEGATIVE daily returns in the trailing window only.

Key structural intuition:
  • Calm periods   → σ_down ≈ ε for all books → XDSR ≈ XSD (rank by μ alone)
  • Crisis windows → the book absorbing the largest downside hits accumulates high σ_down
    → its Sortino score falls further than any pure-μ signal can detect → XDSR demotes it
    even if that book has a higher long-run drift than the permanently-lowest-μ book that
    XSD would demote.

Concrete expectation on fixture:
  USDe unwind 2025-10: leverage_loop takes −28% (biggest of any book in any crisis).
    XSD still demotes variant_d (lowest μ=9%).
    XDSR: leverage_loop Sortino collapses → XDSR demotes leverage_loop instead → avoids the
    worst drawdown in the entire fixture.
  rsETH depeg 2026-04: lrt_carry takes −22%.
    XSD still demotes variant_d.
    XDSR: lrt_carry σ_down spikes → may switch to lrt_carry demotion.

These switch events are the measurable, testable claim.

Novelty vs registry:
  • XSD (#40)  — μ-rank only; blind to downside risk magnitude during crises
  • XVD (#45)  — σ-rank only; blind to drift direction
  • MRD (#41)  — downside-day count (frequency, not magnitude × direction combined)
  • DSP (#105) — 1/σ_down proportional ALLOCATION (not k-book demotion timing)
  XDSR: Sortino-ratio RANKING → k-book demotion; first registry entry to combine
  trailing μ AND trailing σ_down in the RANKING criterion for demotion timing.

Honest caveats:
  1. Fixture σ²≈0 in calm → σ_down≈ε → XDSR collapses to XSD outside crisis windows.
     Degeneracy fraction measured explicitly below.
  2. Only 3 crisis windows in the fixture — same structural limit as XVD, CDR, CDMS.
  3. Best hyper-params (L, k) selected on the same 699-day window = overfit risk.
  4. L1 evidence only: deterministic synthetic fixture, no real fills.
  5. Real panel validation needed before any deployment consideration.

Backtest: fixture corpus (deterministic, 2024-07-01 … 2026-05-31, three crisis windows).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Tuple

_repo = Path(__file__).resolve().parent.parent
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS
from spa_core.strategy_lab.aggressive_lab.fixtures import _SPEC, _build_backtest_series

# ── constants ────────────────────────────────────────────────────────────────────────────────────
RWA_DAILY = 3.4 / 100.0 / 365.0   # conservative floor
INITIAL = 100_000.0
BOOKS = ["susde_dn", "lrt_carry", "leverage_loop", "points_farm", "variant_d"]
EPS = 1e-8

# Grid
L_GRID = [20, 40, 60]   # trailing window (days)
K_GRID = [1, 2]          # books to demote per day


# ── data loading ─────────────────────────────────────────────────────────────────────────────────

def _load_rets() -> Tuple[List[str], Dict[str, Dict[str, float]]]:
    """Return (sorted common dates, {book: {date: daily_return}}) from backtest phase."""
    rets: Dict[str, Dict[str, float]] = {}
    for b in BOOKS:
        raw = _build_backtest_series(_SPEC[b])
        eq = {r["date"]: float(r["equity_usd"]) for r in raw if r["phase"] == "backtest"}
        ds = sorted(eq)
        rets[b] = {ds[i]: (eq[ds[i]] - eq[ds[i - 1]]) / eq[ds[i - 1]] for i in range(1, len(ds))}
    common = sorted(set.intersection(*(set(rets[b]) for b in BOOKS)))
    return common, rets


# ── scoring functions ─────────────────────────────────────────────────────────────────────────────

def _sortino_score(w: List[float]) -> float:
    """Trailing Sortino ratio: μ / (σ_down + ε). Lower score → demoted."""
    if not w:
        return 0.0
    mu = sum(w) / len(w)
    neg = [r for r in w if r < 0]
    if not neg:
        # no negative returns in window → effectively high Sortino; score = μ/ε (large)
        return mu / EPS
    mn = sum(neg) / len(neg)
    sd = math.sqrt(sum((r - mn) ** 2 for r in neg) / len(neg)) + EPS
    return mu / sd


def _mean_score(w: List[float]) -> float:
    """Pure mean return. Lower score → demoted (XSD control)."""
    return sum(w) / len(w) if w else 0.0


def _neg_vol_score(w: List[float]) -> float:
    """Negative total volatility. Lower score → highest vol → demoted (XVD control)."""
    if len(w) < 2:
        return 0.0
    mu = sum(w) / len(w)
    sd = math.sqrt(sum((r - mu) ** 2 for r in w) / len(w))
    return -sd


# ── simulation ─────────────────────────────────────────────────────────────────────────────────────

def _simulate(
    dates: List[str],
    rets: Dict[str, Dict[str, float]],
    score_fn,
    k: int,
    l_win: int,
) -> dict:
    """
    Simulate k-book demotion using score_fn to rank.
    Each book has equal 1/N weight; demoted books earn RWA_DAILY instead.
    Causal: score at day t uses returns history[t-L : t-1] only.
    """
    n = len(BOOKS)
    hist: Dict[str, List[float]] = {b: [] for b in BOOKS}
    eq = INITIAL
    curve: List[float] = [eq]
    dated: List[Tuple[str, float]] = []

    for d in dates:
        # scores from trailing window (causal — history not yet updated)
        scores = {b: score_fn(hist[b][-l_win:]) for b in BOOKS}
        demoted = set(sorted(BOOKS, key=lambda b: scores[b])[:k]) if k > 0 else set()

        # equal 1/N weight; demoted → RWA floor
        r_p = sum(
            (RWA_DAILY if b in demoted else rets[b].get(d, 0.0)) / n
            for b in BOOKS
        )
        eq *= (1.0 + r_p)
        curve.append(eq)
        dated.append((d, eq))

        # update history AFTER observing today's return
        for b in BOOKS:
            hist[b].append(rets[b].get(d, 0.0))

    nd = len(curve) - 1
    ap = _apy(curve, nd)
    md = _mdd(curve)
    return {
        "apy_pct": round(ap, 2),
        "max_dd_pct": round(md * 100.0, 2),
        "calmar": round(_calmar(ap, md), 3),
        "crisis": {
            ck: round(_crisis_dd(dated, ck) * 100.0, 2)
            for ck in ["eth_crash_2024_08", "usde_unwind_2025_10", "rseth_depeg_2026_04"]
        },
    }


# ── metrics ──────────────────────────────────────────────────────────────────────────────────────

def _mdd(curve: List[float]) -> float:
    hwm = mdd = 0.0
    hwm = curve[0]
    for v in curve:
        hwm = max(hwm, v)
        mdd = max(mdd, (hwm - v) / hwm)
    return mdd


def _apy(curve: List[float], n: int) -> float:
    if n < 1 or curve[0] < 1e-9:
        return 0.0
    return ((curve[-1] / curve[0]) ** (365.0 / n) - 1.0) * 100.0


def _calmar(apy: float, mdd: float) -> float:
    return apy / (mdd * 100.0) if mdd > 1e-9 else float("inf")


def _crisis_dd(dated: List[Tuple[str, float]], key: str) -> float:
    lo = hi = None
    for w in STRESS_WINDOWS:
        if w["key"] == key:
            lo, hi = str(w["date_from"]), str(w["date_to"])
            break
    if lo is None:
        return 0.0
    sub = [v for d, v in dated if lo <= d <= hi]
    if not sub:
        return 0.0
    peak = mdd = 0.0
    peak = sub[0]
    for v in sub:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak)
    return mdd


# ── analysis helpers ─────────────────────────────────────────────────────────────────────────────

def _degeneracy_frac(dates: List[str], rets: Dict[str, Dict[str, float]], l_win: int) -> float:
    """Fraction of days where XDSR bottom-1 == XSD bottom-1 (collapsed to same ranking)."""
    hist: Dict[str, List[float]] = {b: [] for b in BOOKS}
    match = tot = 0
    for d in dates:
        w = {b: hist[b][-l_win:] for b in BOOKS}
        if all(w[b] for b in BOOKS):
            xdsr_bot = sorted(BOOKS, key=lambda b: _sortino_score(w[b]))[0]
            xsd_bot = sorted(BOOKS, key=lambda b: _mean_score(w[b]))[0]
            if xdsr_bot == xsd_bot:
                match += 1
            tot += 1
        for b in BOOKS:
            hist[b].append(rets[b].get(d, 0.0))
    return match / tot if tot > 0 else 0.0


def _loo(
    dates: List[str],
    rets: Dict[str, Dict[str, float]],
    l_win: int,
    k: int,
) -> List[Tuple[str, float, float, float]]:
    """Leave-one-out: return [(skipped_book, calmar, apy, max_dd_pct), ...]."""
    results = []
    for skip in BOOKS:
        sub = [b for b in BOOKS if b != skip]
        hist: Dict[str, List[float]] = {b: [] for b in sub}
        n = len(sub)
        eq = INITIAL
        curve: List[float] = [eq]
        for d in dates:
            scores = {b: _sortino_score(hist[b][-l_win:]) for b in sub}
            k_eff = min(k, n - 1)
            demoted = set(sorted(sub, key=lambda b: scores[b])[:k_eff]) if k_eff > 0 else set()
            r_p = sum(
                (RWA_DAILY if b in demoted else rets[b].get(d, 0.0)) / n
                for b in sub
            )
            eq *= (1.0 + r_p)
            curve.append(eq)
            for b in sub:
                hist[b].append(rets[b].get(d, 0.0))
        nd = len(curve) - 1
        ap = _apy(curve, nd)
        md = _mdd(curve)
        results.append((skip, round(_calmar(ap, md), 3), round(ap, 2), round(md * 100.0, 2)))
    return results


# ── main ─────────────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 72)
    print("Idea #108 — XDSR: Cross-Sectional Downside Sharpe Ranking")
    print("Evidence: BACKTEST on deterministic fixture (L1 — no real fills)")
    print("Advisory: IS_ADVISORY=True  |  LLM_FORBIDDEN")
    print("=" * 72)

    dates, rets = _load_rets()
    print(f"\nFixture: {len(dates)} trading days | {len(BOOKS)} books: {', '.join(BOOKS)}")

    # ── baselines ─────────────────────────────────────────────────────────────────
    print("\n--- BASELINES (L=60) ---")
    ew_r = _simulate(dates, rets, _mean_score, 0, 60)
    xsd_r = _simulate(dates, rets, _mean_score, 1, 60)
    xvd_r = _simulate(dates, rets, _neg_vol_score, 1, 60)

    xsd2_r = _simulate(dates, rets, _mean_score, 2, 60)

    for label, r in [("EW  (k=0, no demotion)", ew_r),
                     ("XSD (μ-rank, k=1)", xsd_r),
                     ("XSD (μ-rank, k=2)", xsd2_r),
                     ("XVD (−σ-rank, k=1)", xvd_r)]:
        print(f"  {label:<24}  APY={r['apy_pct']:>6.2f}%  maxDD={r['max_dd_pct']:>5.2f}%  "
              f"Calmar={r['calmar']:>7.3f}  "
              f"eth={r['crisis']['eth_crash_2024_08']:>5.2f}%  "
              f"usde={r['crisis']['usde_unwind_2025_10']:>5.2f}%  "
              f"rseth={r['crisis']['rseth_depeg_2026_04']:>5.2f}%")

    # ── XDSR grid ─────────────────────────────────────────────────────────────────
    print("\n--- XDSR GRID (Sortino ranking, sorted by Calmar desc) ---")
    print(f"  {'L':>4}  {'k':>2}  {'APY%':>7}  {'maxDD%':>7}  {'Calmar':>8}  "
          f"{'eth':>7}  {'usde':>7}  {'rseth':>7}")
    print("  " + "-" * 62)

    all_xdsr = []
    for l_win in L_GRID:
        for k in K_GRID:
            r = _simulate(dates, rets, _sortino_score, k, l_win)
            r["L"] = l_win
            r["k"] = k
            all_xdsr.append(r)

    all_xdsr.sort(key=lambda r: -r["calmar"])
    for r in all_xdsr:
        print(f"  {r['L']:>4}  {r['k']:>2}  {r['apy_pct']:>7.2f}  {r['max_dd_pct']:>7.2f}  "
              f"{r['calmar']:>8.3f}  {r['crisis']['eth_crash_2024_08']:>7.2f}  "
              f"{r['crisis']['usde_unwind_2025_10']:>7.2f}  "
              f"{r['crisis']['rseth_depeg_2026_04']:>7.2f}")

    best = all_xdsr[0]
    best_l, best_k = best["L"], best["k"]
    print(f"\n  BEST XDSR: L={best_l} k={best_k}  "
          f"APY={best['apy_pct']}%  maxDD={best['max_dd_pct']}%  Calmar={best['calmar']}")

    # ── degeneracy analysis ───────────────────────────────────────────────────────
    print("\n--- DEGENERACY ANALYSIS ---")
    print("  (% days where XDSR bottom-1 == XSD bottom-1 → σ_down≈ε in calm)")
    for l_win in L_GRID:
        frac = _degeneracy_frac(dates, rets, l_win)
        print(f"  L={l_win}: {frac * 100:.1f}% degenerate (XDSR ≡ XSD ranking)")

    # ── train / test split ────────────────────────────────────────────────────────
    mid = len(dates) // 2
    train_d, test_d = dates[:mid], dates[mid:]
    print(f"\n--- TRAIN / TEST SPLIT (first {mid} / last {len(dates) - mid} days; mid={dates[mid]}) ---")

    tr_x = _simulate(train_d, rets, _sortino_score, best_k, best_l)
    te_x = _simulate(test_d, rets, _sortino_score, best_k, best_l)
    tr_s = _simulate(train_d, rets, _mean_score, best_k, best_l)
    te_s = _simulate(test_d, rets, _mean_score, best_k, best_l)

    print(f"  XDSR  TRAIN  APY={tr_x['apy_pct']:>6.2f}%  Calmar={tr_x['calmar']:>7.3f}")
    print(f"  XDSR  TEST   APY={te_x['apy_pct']:>6.2f}%  Calmar={te_x['calmar']:>7.3f}")
    print(f"  XSD   TRAIN  APY={tr_s['apy_pct']:>6.2f}%  Calmar={tr_s['calmar']:>7.3f}")
    print(f"  XSD   TEST   APY={te_s['apy_pct']:>6.2f}%  Calmar={te_s['calmar']:>7.3f}")
    print(f"  XDSR−XSD ΔCalmar  TRAIN={tr_x['calmar'] - tr_s['calmar']:+.3f}  "
          f"TEST={te_x['calmar'] - te_s['calmar']:+.3f}")

    # ── leave-one-out ─────────────────────────────────────────────────────────────
    print(f"\n--- LEAVE-ONE-OUT (L={best_l} k={best_k}) ---")
    loo = _loo(dates, rets, best_l, best_k)
    loo_pass = all(c > 0.0 for _, c, _, _ in loo)
    for skip, cal, ap, md in loo:
        tag = "+" if cal >= best["calmar"] else "-"
        print(f"  −{skip:<18}  Calmar={cal:>7.3f} [{tag}]  APY={ap:>6.2f}%  maxDD={md:>5.2f}%")
    print(f"  LOO verdict: {'PASS — all sub-portfolios positive Calmar' if loo_pass else 'FAIL — some Calmar ≤ 0'}")

    # ── honest caveats ────────────────────────────────────────────────────────────
    print("\n--- HONEST CAVEATS ---")
    print("  1. Fixture σ²≈0 in calm → σ_down≈ε → XDSR collapses to XSD outside crisis windows.")
    print("     Degeneracy fraction above shows how rarely they differ.")
    print("  2. Only 3 crisis windows in the 699-day fixture (same limit as XVD, CDR, CDMS).")
    print("  3. Best (L, k) selected on the SAME 699 days used for evaluation → overfit risk.")
    print("  4. L1 evidence only: synthetic fixture, no real fills, no real book-level costs.")
    print("  5. σ_down uses intra-window negative returns; calm σ_down is near-zero by construction.")
    print("  6. IS_ADVISORY=True / OUTSIDE_RISKPOLICY=True. Not deployed. Not in swarm.")

    # ── verdict ───────────────────────────────────────────────────────────────────
    print("\n--- VERDICT ---")
    beats_ew = best["calmar"] > ew_r["calmar"]
    beats_xsd = best["calmar"] > xsd_r["calmar"]
    beats_xvd = best["calmar"] > xvd_r["calmar"]
    oos_positive = te_x["apy_pct"] > 3.4

    print(f"  Best XDSR Calmar:  {best['calmar']}")
    print(f"  vs EW  {ew_r['calmar']:>7.3f}: {'✅ beats' if beats_ew else '❌ does not beat'}")
    print(f"  vs XSD {xsd_r['calmar']:>7.3f}: {'✅ beats' if beats_xsd else '❌ does not beat'}")
    print(f"  vs XVD {xvd_r['calmar']:>7.3f}: {'✅ beats' if beats_xvd else '❌ does not beat'}")
    print(f"  OOS APY {te_x['apy_pct']}% > 3.4% RWA floor: {'✅' if oos_positive else '❌'}")
    print(f"  LOO: {'✅ PASS' if loo_pass else '❌ FAIL'}")

    if beats_xsd and beats_xvd and oos_positive:
        verdict_str = "RISK_COMPENSATION"
        verdict_sym = "✅"
    elif beats_xsd or beats_xvd:
        verdict_str = "PARTIAL_IMPROVEMENT"
        verdict_sym = "⚠️"
    else:
        verdict_str = "DOES_NOT_BEAT_BASELINES"
        verdict_sym = "❌"

    print(f"\n  OVERALL: {verdict_sym} {verdict_str}")

    # ── JSON output ───────────────────────────────────────────────────────────────
    summary = {
        "idea": "XDSR — Cross-Sectional Downside Sharpe Ranking",
        "number": 108,
        "evidence": "BACKTEST fixture L1 (synthetic, no real fills)",
        "baselines": {"ew": ew_r, "xsd": xsd_r, "xvd": xvd_r},
        "best_xdsr": best,
        "train": tr_x,
        "test": te_x,
        "loo": [{"skip": s, "calmar": c, "apy_pct": a, "max_dd_pct": m} for s, c, a, m in loo],
        "beats_xsd": beats_xsd,
        "beats_xvd": beats_xvd,
        "loo_pass": loo_pass,
        "verdict": verdict_str,
    }
    out = Path(__file__).parent.parent / "data" / "edge_idea_108_xdsr.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2))
    print(f"\n  JSON → {out}")


if __name__ == "__main__":
    main()
