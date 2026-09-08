"""
scripts/edge_carry_compression_coordinator.py — Idea #104: CCC

Carry-Compression Coordinator
«De-risk a BOOK when its realized carry falls below its own promised headline;
recycle freed capital to non-compressed books»

IS_ADVISORY=True. OUTSIDE_RISKPOLICY=True.
Does NOT touch spa_core/execution, live paper track, or RiskPolicy v1.0.
stdlib-only, deterministic. LLM FORBIDDEN.
Evidence level: L0 [bt] (synthetic stress-fixture, NOT realised).

Hypothesis:
    Each fixture book has a promised daily drift (headline_apy_pct / 365).  When a
    book's rolling realized return over `lookback` days falls below `threshold ×
    headline_apy`, its carry is «compressed»: it is either in a stress event or
    structurally degrading.  CCC de-risks compressed books and redistributes their
    capital to non-compressed books.

    Structural differences vs prior ideas:
    • DDO (#9): portfolio-level trailing drawdown → de-risk the WHOLE BLEND
    • Guardian (#1): portfolio-level vol spike → de-risk the WHOLE BLEND
    • KODS (#15): Kelly-optimal sizing from per-book mean/variance
    • CCC (#104): per-BOOK carry-ratio signal → SELECTIVE de-risk + rotation

    Key testable prediction: because CCC acts per-book rather than portfolio-level,
    it should selectively avoid the worst-hit book in each crisis while KEEPING
    weight in books that are still delivering their carry.

    ETH crash 2024-08: variant_d loses 18%, others 1-6% → CCC exits variant_d, holds rest
    USDe unwind 2025-10: leverage_loop -28%, susde_dn -9%, but points_farm -2% → CCC exits
                         leverage_loop first, holds points_farm
    rsETH depeg 2026-04: lrt_carry -22%, variant_d -20%, but points_farm -1.5% → CCC exits
                         lrt_carry/variant_d, holds rest

    Baseline: equal-weight 5 books (no filter)

Variants:
    CCC-HARD: binary — carry_ratio < threshold → weight=0; equal weight among active
    CCC-SOFT: continuous — weight ∝ max(0, carry_ratio); fallback EW if all compressed
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import sys
from pathlib import Path
from typing import Dict, List, Tuple

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.strategy_lab.aggressive_lab.fixtures import (  # noqa: E402
    _build_backtest_series,
    _SPEC,
)
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS  # noqa: E402

BOOKS = ["susde_dn", "lrt_carry", "leverage_loop", "points_farm", "variant_d"]
INITIAL = 100_000.0
TRAIN_END = datetime.date(2025, 6, 30)


def _build_returns(book: str) -> List[Tuple[datetime.date, float]]:
    """Daily (date, return) from fixture backtest series."""
    spec = _SPEC[book]
    series = _build_backtest_series(spec)
    result: List[Tuple[datetime.date, float]] = []
    prev_eq = INITIAL
    for row in series:
        d = datetime.date.fromisoformat(row["date"])
        eq = float(row["equity_usd"])
        ret = (eq - prev_eq) / prev_eq
        result.append((d, ret))
        prev_eq = eq
    return result


def _metrics(curve: List[float]) -> dict:
    n = len(curve)
    if n < 2:
        return {"apy_pct": 0.0, "max_dd_pct": 0.0, "calmar": 0.0}
    apy = (curve[-1] / curve[0]) ** (365.0 / n) - 1.0
    hwm = curve[0]
    max_dd = 0.0
    for v in curve:
        if v > hwm:
            hwm = v
        dd = (hwm - v) / hwm
        if dd > max_dd:
            max_dd = dd
    calmar = apy / max_dd if max_dd > 1e-9 else float("inf")
    return {
        "apy_pct": round(apy * 100, 2),
        "max_dd_pct": round(max_dd * 100, 2),
        "calmar": round(calmar, 2),
    }


def _crisis_dd(curve: List[float], dates: List[datetime.date]) -> Dict[str, float]:
    """
    Per-crisis peak-to-trough drawdown.
    curve has n+1 elements (curve[0]=initial; curve[t+1]=equity after day t).
    dates has n elements.
    """
    out = {}
    for w in STRESS_WINDOWS:
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        idxs = [t for t, d in enumerate(dates) if lo <= d <= hi]
        if not idxs:
            continue
        # equity at the START of crisis (end of prior day)
        start_eq = curve[idxs[0]]
        # lowest equity DURING crisis (end of each crisis day)
        min_eq = min(curve[t + 1] for t in idxs)
        if start_eq > 1e-9:
            out[str(w["key"])] = round((start_eq - min_eq) / start_eq * 100, 2)
    return out


def run_equal_weight(
    all_rets: Dict[str, List[Tuple[datetime.date, float]]],
) -> Tuple[List[float], List[datetime.date]]:
    """Equal-weight 5 books, daily rebalanced. Returns (curve, dates)."""
    dates = [d for d, _ in all_rets[BOOKS[0]]]
    n = len(dates)
    w = 1.0 / len(BOOKS)
    eq = INITIAL
    curve = [eq]
    for t in range(n):
        daily = sum(w * all_rets[b][t][1] for b in BOOKS)
        eq = eq * (1.0 + daily)
        curve.append(eq)
    return curve, dates


def run_ccc(
    all_rets: Dict[str, List[Tuple[datetime.date, float]]],
    lookback: int,
    threshold: float,
    mode: str = "HARD",
) -> Tuple[List[float], List[datetime.date]]:
    """
    CCC: Carry-Compression Coordinator (causal — uses returns t-lookback..t-1 for day t).

    carry_ratio(b, t) = annualized_realized_apy(b, t-lookback..t-1) / headline_apy(b)

    HARD: compressed if carry_ratio < threshold → weight=0; equal among active books
          if ALL compressed → fallback equal weight (fail-safe, no data-loss)
    SOFT: weight ∝ max(0, carry_ratio); normalised; fallback EW if total=0

    Warm-up (t < lookback): carry_ratio=1.0 for all books (delivering headline),
    which is conservative (equal weight, no speculation on thin history).
    """
    headlines = {b: _SPEC[b]["daily_drift"] for b in BOOKS}
    dates = [d for d, _ in all_rets[BOOKS[0]]]
    n = len(dates)
    rets = {b: [r for _, r in all_rets[b]] for b in BOOKS}

    eq = INITIAL
    curve = [eq]

    for t in range(n):
        # causal carry_ratio: use returns from (t-lookback) to (t-1)
        carry_ratios: Dict[str, float] = {}
        for b in BOOKS:
            if t < lookback:
                carry_ratios[b] = 1.0  # warm-up: assume on-target
            else:
                window = rets[b][t - lookback : t]
                cumret = 1.0
                for r in window:
                    cumret *= 1.0 + r
                ann_ret = cumret ** (365.0 / lookback) - 1.0
                h = headlines[b]
                carry_ratios[b] = ann_ret / h if h > 1e-9 else 1.0

        if mode == "HARD":
            active = [b for b in BOOKS if carry_ratios[b] >= threshold]
            if not active:
                active = BOOKS[:]  # fail-safe: equal weight all
            w: Dict[str, float] = {
                b: (1.0 / len(active) if b in active else 0.0) for b in BOOKS
            }
        elif mode == "SOFT":
            scores = {b: max(0.0, carry_ratios[b]) for b in BOOKS}
            total = sum(scores.values())
            if total < 1e-9:
                w = {b: 1.0 / len(BOOKS) for b in BOOKS}  # fail-safe
            else:
                w = {b: scores[b] / total for b in BOOKS}
        else:
            raise ValueError(f"Unknown mode: {mode!r}")

        daily = sum(w[b] * rets[b][t] for b in BOOKS)
        eq = eq * (1.0 + daily)
        curve.append(eq)

    return curve, dates


def _sweep(
    all_rets: Dict[str, List[Tuple[datetime.date, float]]],
) -> Tuple[int, float, float]:
    """Sweep lookback × threshold in HARD mode; return (best_lb, best_thr, best_calmar)."""
    best_calmar = -999.0
    best_params = (10, 0.0)
    for lb in [5, 10, 20]:
        for thr in [-0.5, 0.0, 0.3, 0.5]:
            c, _ = run_ccc(all_rets, lb, thr, mode="HARD")
            m = _metrics(c)
            if m["calmar"] > best_calmar:
                best_calmar = m["calmar"]
                best_params = (lb, thr)
    return best_params[0], best_params[1], best_calmar


def main() -> None:  # noqa: C901
    print("=" * 72)
    print("CCC — Carry-Compression Coordinator  [bt] [L0 evidence]  Idea #104")
    print("IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  LLM_FORBIDDEN")
    print("=" * 72)

    all_rets = {b: _build_returns(b) for b in BOOKS}
    dates = [d for d, _ in all_rets[BOOKS[0]]]
    n_days = len(dates)
    date_start = dates[0].isoformat()
    date_end = dates[-1].isoformat()

    print(f"\nFixture: {date_start}..{date_end} ({n_days} days)")
    print(f"Books:   {', '.join(BOOKS)}")
    print(f"TRAIN/TEST split: {TRAIN_END.isoformat()}")

    # ── Baseline: equal-weight ─────────────────────────────────────────────
    bl_curve, bl_dates = run_equal_weight(all_rets)
    bl_m = _metrics(bl_curve)
    bl_crisis = _crisis_dd(bl_curve, bl_dates)

    print(f"\n── BASELINE (equal-weight 5 books) ──────────────────────────────")
    print(f"  APY [bt]:    {bl_m['apy_pct']:.2f}%")
    print(f"  Max DD [bt]: {bl_m['max_dd_pct']:.2f}%")
    print(f"  Calmar [bt]: {bl_m['calmar']:.2f}")
    for wk in sorted(bl_crisis):
        print(f"  Crisis {wk}: −{bl_crisis[wk]:.2f}%")

    # ── Parameter sweep (full IS) ──────────────────────────────────────────
    print(f"\n── SWEEP CCC-HARD (full IS {date_start}..{date_end}) ─────────────")
    print(f"  {'lb':>4} {'thr':>6} {'APY%':>7} {'MaxDD%':>8} {'Calmar':>8}")
    for lb in [5, 10, 20]:
        for thr in [-0.5, 0.0, 0.3, 0.5]:
            c, _ = run_ccc(all_rets, lb, thr, mode="HARD")
            m = _metrics(c)
            print(f"  {lb:>4} {thr:>6.1f} {m['apy_pct']:>7.2f} {m['max_dd_pct']:>8.2f} {m['calmar']:>8.2f}")

    best_lb, best_thr, best_cal_is = _sweep(all_rets)
    print(f"\n  → Best IS: lb={best_lb}, thr={best_thr:.1f}, Calmar={best_cal_is:.2f}")

    # ── Best CCC-HARD full period ──────────────────────────────────────────
    hd_curve, hd_dates = run_ccc(all_rets, best_lb, best_thr, mode="HARD")
    hd_m = _metrics(hd_curve)
    hd_crisis = _crisis_dd(hd_curve, hd_dates)

    print(f"\n── CCC-HARD (lb={best_lb}, thr={best_thr:.1f}) — full IS ──────────────")
    print(f"  APY [bt]:    {hd_m['apy_pct']:.2f}%")
    print(f"  Max DD [bt]: {hd_m['max_dd_pct']:.2f}%")
    print(f"  Calmar [bt]: {hd_m['calmar']:.2f}")
    for wk in sorted(hd_crisis):
        baseline_dd = bl_crisis.get(wk, 0.0)
        saved = baseline_dd - hd_crisis[wk]
        print(f"  Crisis {wk}: −{hd_crisis[wk]:.2f}%  (baseline −{baseline_dd:.2f}%; saved {saved:+.2f}pp)")

    # ── CCC-SOFT full period (same lb/thr for apples-to-apples) ───────────
    sf_curve, _ = run_ccc(all_rets, best_lb, best_thr, mode="SOFT")
    sf_m = _metrics(sf_curve)
    sf_crisis = _crisis_dd(sf_curve, hd_dates)

    print(f"\n── CCC-SOFT (lb={best_lb}, thr={best_thr:.1f}) — full IS ──────────────")
    print(f"  APY [bt]:    {sf_m['apy_pct']:.2f}%")
    print(f"  Max DD [bt]: {sf_m['max_dd_pct']:.2f}%")
    print(f"  Calmar [bt]: {sf_m['calmar']:.2f}")
    for wk in sorted(sf_crisis):
        print(f"  Crisis {wk}: −{sf_crisis[wk]:.2f}%")

    # ── OOS split ──────────────────────────────────────────────────────────
    # params fitted on TRAIN half; applied to TEST half (genuine causal warmup included)
    train_idx = next(i for i, d in enumerate(dates) if d > TRAIN_END)
    oos_dates = dates[train_idx:]

    # Run with params found by IS sweep on TRAIN data only
    tr_rets = {b: v[:train_idx] for b, v in all_rets.items()}
    tr_best_lb, tr_best_thr, _ = _sweep(tr_rets)
    print(
        f"\n── OOS SETUP ─────────────────────────────────────────────────────"
    )
    print(f"  Train: {date_start}..{TRAIN_END.isoformat()} ({train_idx} days)")
    print(f"  Test:  {oos_dates[0].isoformat()}..{date_end} ({len(oos_dates)} days)")
    print(
        f"  Params from TRAIN sweep: lb={tr_best_lb}, thr={tr_best_thr:.1f}"
        " (may differ from full-IS best)"
    )

    # Apply train-params to full dataset; slice test portion of curve
    oos_ccc_full, _ = run_ccc(all_rets, tr_best_lb, tr_best_thr, mode="HARD")
    oos_ccc_curve = oos_ccc_full[train_idx:]   # equity curve for test period only

    oos_bl_full, _ = run_equal_weight(all_rets)
    oos_bl_curve = oos_bl_full[train_idx:]

    oos_ccc_m = _metrics(oos_ccc_curve)
    oos_bl_m = _metrics(oos_bl_curve)
    oos_delta = oos_ccc_m["calmar"] - oos_bl_m["calmar"]

    print(f"\n── OUT-OF-SAMPLE RESULTS ─────────────────────────────────────────")
    print(
        f"  EW baseline OOS:  APY={oos_bl_m['apy_pct']:.2f}%"
        f"  MaxDD={oos_bl_m['max_dd_pct']:.2f}%"
        f"  Calmar={oos_bl_m['calmar']:.2f}"
    )
    print(
        f"  CCC-HARD  OOS:    APY={oos_ccc_m['apy_pct']:.2f}%"
        f"  MaxDD={oos_ccc_m['max_dd_pct']:.2f}%"
        f"  Calmar={oos_ccc_m['calmar']:.2f}"
    )
    oos_label = "✅ HOLDS" if oos_delta > 0 else "❌ DOES NOT HOLD"
    print(f"  ΔCalmar OOS = {oos_delta:+.2f}  → {oos_label}")

    # ── Summary table ──────────────────────────────────────────────────────
    print(f"\n── SUMMARY TABLE [bt] ────────────────────────────────────────────")
    fmt = "  {:<28} {:>7} {:>8} {:>8}"
    print(fmt.format("Strategy", "APY%", "MaxDD%", "Calmar"))
    print(fmt.format("-" * 28, "-" * 7, "-" * 8, "-" * 8))
    print(fmt.format("EW baseline (5 books)", f"{bl_m['apy_pct']:.2f}", f"{bl_m['max_dd_pct']:.2f}", f"{bl_m['calmar']:.2f}"))
    print(fmt.format(f"CCC-HARD IS (lb={best_lb},thr={best_thr:.1f})", f"{hd_m['apy_pct']:.2f}", f"{hd_m['max_dd_pct']:.2f}", f"{hd_m['calmar']:.2f}"))
    print(fmt.format(f"CCC-SOFT IS (lb={best_lb},thr={best_thr:.1f})", f"{sf_m['apy_pct']:.2f}", f"{sf_m['max_dd_pct']:.2f}", f"{sf_m['calmar']:.2f}"))
    print(fmt.format("CCC-HARD OOS", f"{oos_ccc_m['apy_pct']:.2f}", f"{oos_ccc_m['max_dd_pct']:.2f}", f"{oos_ccc_m['calmar']:.2f}"))
    print(fmt.format("EW baseline OOS", f"{oos_bl_m['apy_pct']:.2f}", f"{oos_bl_m['max_dd_pct']:.2f}", f"{oos_bl_m['calmar']:.2f}"))

    # ── Verdict ────────────────────────────────────────────────────────────
    is_positive = hd_m["calmar"] > bl_m["calmar"] * 1.05
    oos_positive = oos_delta > 0
    if is_positive and oos_positive:
        verdict = "✅ ПОЗИТИВНО: IS улучшает Calmar и OOS держится"
    elif is_positive and not oos_positive:
        verdict = "⚠️ ЧАСТИЧНО: IS положительный, OOS не держится (calm period?)"
    elif not is_positive and oos_positive:
        verdict = "⚠️ ИНВЕРСИЯ: IS слабый, OOS держится — проверить"
    else:
        verdict = "❌ НЕ УЛУЧШАЕТ: IS и OOS ниже baseline"

    print(f"\n── VERDICT ───────────────────────────────────────────────────────")
    print(f"  {verdict}")
    print(f"  IS:  baseline Calmar={bl_m['calmar']:.2f} → CCC-HARD={hd_m['calmar']:.2f}")
    print(f"  OOS: ΔCalmar = {oos_delta:+.2f}")
    print()
    print("Все числа — [bt] [L0], синтетический стресс-фикстур, НЕ реализованные данные.")
    print("IS_ADVISORY=True. Не трогает spa_core/execution, RiskPolicy v1.0, live-трек.")
    print(
        "Carry-ratio относится к FIXTURE-headlines: промисед drift, "
        "а не реальный индекс доходности."
    )


if __name__ == "__main__":
    main()
