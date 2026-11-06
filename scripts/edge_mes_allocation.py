"""
scripts/edge_mes_allocation.py

Idea #156 — MES: Marginal Expected Shortfall Allocation
==========================================================
Novel yield/risk edge: allocate weights based on each book's Marginal Expected Shortfall
(MES) — its conditional return when the EQUAL-WEIGHT reference portfolio is in its worst
ES_PCT% of days over a rolling WINDOW.

HOW IT DIFFERS from existing entries:
  • MRD (#41)  — marginal VARIANCE contribution (symmetric second moment, not tail-focused)
  • DSP (#105) — each book's OWN downside semi-deviation (not portfolio-conditional)
  • TDC (#106) — COUNTS tail coincidences as a demotion flag (not a continuous reweighting)
  • MES HERE   — E[r_i | r_portfolio ≤ VaR(ES_PCT)] over rolling WINDOW
                 i.e. each book's expected return conditioned on the PORTFOLIO being in its
                 worst p% of daily outcomes. Books that are most negative in joint tail
                 get systematically down-weighted.

The reference portfolio is equal-weight (not the MES-weighted one) to avoid the fixed-
point problem inherent in portfolio-conditional signals. This is the standard academic
approach (see Acharya et al. 2010 / Brownlees & Engle 2017 for the concept).

Backtest: fixture only (spa_core/strategy_lab/aggressive_lab/fixtures.py).
Period: 2024-07-01..2026-05-31 (~700 days). OOS split: 2025-06-01.
No external data. No randomness. Deterministic. stdlib-only.

Evidence level: **backtest (bt)** — NOT realized.
IS_ADVISORY=True. LLM_FORBIDDEN.
"""
# LLM_FORBIDDEN
# IS_ADVISORY=True
from __future__ import annotations

import sys
import os
import datetime

# allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spa_core.strategy_lab.aggressive_lab.fixtures import _SPEC, _build_backtest_series

# ── constants ───────────────────────────────────────────────────────────────
RWA_APY = 0.0331          # ~3.31%/yr floor reference
RATES_APY = 0.046         # 4.6%/yr rates carry reference
ES_PCT = 0.10             # worst 10% of portfolio days define the conditional tail
WINDOW = 60               # rolling window for MES estimation (days)
REBAL_FREQ = 5            # rebalance every 5 trading days
MIN_WEIGHT = 0.05         # floor: each book gets at least 5%
OOS_DATE = datetime.date(2025, 6, 1)   # consistent with #11/#15/#19/#20/#21/#22

BOOKS = ["susde_dn", "lrt_carry", "leverage_loop", "points_farm", "variant_d"]

CRISIS_WINDOWS = {
    "eth_crash_2024_08":  ("2024-08-01", "2024-08-31"),
    "usde_unwind_2025_10": ("2025-10-01", "2025-10-31"),
    "rseth_depeg_2026_04": ("2026-04-01", "2026-04-30"),
}


# ── data loading ─────────────────────────────────────────────────────────────

def _load_returns() -> dict[str, list[tuple[datetime.date, float]]]:
    """Daily fractional returns per book from the synthetic fixture."""
    result: dict[str, list[tuple[datetime.date, float]]] = {}
    for book in BOOKS:
        series = _build_backtest_series(_SPEC[book])
        dates_eq = [(datetime.date.fromisoformat(p["date"]), p["equity_usd"])
                    for p in series if p["phase"] == "backtest"]
        # daily return = (eq_t / eq_{t-1}) - 1
        rets: list[tuple[datetime.date, float]] = []
        for i in range(1, len(dates_eq)):
            d, eq = dates_eq[i]
            _, eq_prev = dates_eq[i - 1]
            rets.append((d, eq / eq_prev - 1.0))
        result[book] = rets
    return result


def _align_dates(book_rets: dict[str, list[tuple[datetime.date, float]]]) \
        -> tuple[list[datetime.date], dict[str, list[float]]]:
    """Find common dates across all books and return aligned arrays."""
    # all books share same fixture dates
    dates = [d for d, _ in book_rets[BOOKS[0]]]
    aligned: dict[str, list[float]] = {}
    for book in BOOKS:
        date_map = {d: r for d, r in book_rets[book]}
        aligned[book] = [date_map[d] for d in dates]
    return dates, aligned


# ── MES weight computation ────────────────────────────────────────────────────

def _compute_mes_weights(
    book_rets_window: dict[str, list[float]],
    n_tail: int,
) -> dict[str, float]:
    """
    Given the last WINDOW returns for each book, compute MES-based weights.

    MES_i = mean(r_i[j] for j in tail_idx)
    where tail_idx = indices where equal-weight portfolio return is in its worst n_tail values.

    Weight proportional to: softmax(-MES_i * T)  with temperature T=1
    but floored at MIN_WEIGHT for stability.
    """
    n = len(book_rets_window[BOOKS[0]])
    if n < max(10, n_tail + 2):
        # not enough history: fall back to equal weight
        w = 1.0 / len(BOOKS)
        return {b: w for b in BOOKS}

    # equal-weight reference portfolio return each day
    n_books = len(BOOKS)
    eq_ret = [
        sum(book_rets_window[b][i] for b in BOOKS) / n_books
        for i in range(n)
    ]

    # find tail indices (worst n_tail days by equal-weight portfolio return)
    indexed = sorted(enumerate(eq_ret), key=lambda x: x[1])
    tail_idx = {idx for idx, _ in indexed[:n_tail]}

    if not tail_idx:
        w = 1.0 / n_books
        return {b: w for b in BOOKS}

    # compute MES for each book
    mes: dict[str, float] = {}
    for b in BOOKS:
        tail_rets = [book_rets_window[b][i] for i in sorted(tail_idx)]
        mes[b] = sum(tail_rets) / len(tail_rets) if tail_rets else 0.0

    # score = -MES  (less negative in tail → higher score)
    # shift so min score = 0, then add epsilon
    scores = {b: -mes[b] for b in BOOKS}
    min_score = min(scores.values())
    scores = {b: scores[b] - min_score + 1e-6 for b in BOOKS}

    # floor at MIN_WEIGHT; distribute remainder by score
    n_b = len(BOOKS)
    total_floor = MIN_WEIGHT * n_b
    rem = max(0.0, 1.0 - total_floor)
    total_score = sum(scores.values())
    weights: dict[str, float] = {}
    for b in BOOKS:
        weights[b] = MIN_WEIGHT + rem * (scores[b] / total_score)

    # re-normalize (should already sum to 1, but guard float rounding)
    total_w = sum(weights.values())
    return {b: weights[b] / total_w for b in BOOKS}


# ── backtest engine ────────────────────────────────────────────────────────────

def run_backtest(
    dates: list[datetime.date],
    aligned: dict[str, list[float]],
    es_pct: float = ES_PCT,
    window: int = WINDOW,
    rebal_freq: int = REBAL_FREQ,
    label: str = "MES",
) -> dict:
    """Full backtest returning daily equity and summary statistics."""
    n_tail = max(2, round(window * es_pct))

    equity: list[float] = [1.0]
    eq = 1.0
    # start with equal weights
    weights: dict[str, float] = {b: 1.0 / len(BOOKS) for b in BOOKS}

    for i in range(len(dates)):
        # rebalance check
        if i > 0 and i % rebal_freq == 0 and i >= window:
            win_start = i - window
            window_rets = {b: aligned[b][win_start:i] for b in BOOKS}
            weights = _compute_mes_weights(window_rets, n_tail)

        # daily portfolio return under current weights
        if i > 0:
            daily_r = sum(weights[b] * aligned[b][i] for b in BOOKS)
            eq *= (1.0 + daily_r)
        equity.append(eq)

    # compute stats
    daily_rets = [equity[i + 1] / equity[i] - 1.0 for i in range(len(equity) - 1)]
    n_days = len(daily_rets)
    total_return = equity[-1] - 1.0
    apy = (equity[-1] ** (365.0 / n_days)) - 1.0 if n_days > 0 else 0.0

    # max drawdown
    peak = 1.0
    max_dd = 0.0
    for eq_val in equity:
        if eq_val > peak:
            peak = eq_val
        dd = (peak - eq_val) / peak
        if dd > max_dd:
            max_dd = dd

    calmar = apy / max_dd if max_dd > 1e-9 else float("inf")

    # OOS stats
    oos_start_idx = next((i for i, d in enumerate(dates) if d >= OOS_DATE), None)
    oos_apy = oos_max_dd = oos_calmar = None
    if oos_start_idx is not None and oos_start_idx < len(dates) - 1:
        oos_eq = equity[oos_start_idx + 1:]  # equity at close of each OOS day
        oos_anchor = equity[oos_start_idx]
        oos_eq_norm = [v / oos_anchor for v in oos_eq]
        n_oos = len(oos_eq)
        oos_apy_v = (oos_eq_norm[-1] ** (365.0 / n_oos)) - 1.0 if n_oos > 0 else 0.0
        oos_peak = 1.0
        oos_mdd = 0.0
        for v in oos_eq_norm:
            if v > oos_peak:
                oos_peak = v
            dd = (oos_peak - v) / oos_peak
            if dd > oos_mdd:
                oos_mdd = dd
        oos_apy = oos_apy_v
        oos_max_dd = oos_mdd
        oos_calmar = oos_apy / oos_mdd if oos_mdd > 1e-9 else float("inf")

    # crisis window stats
    crisis_stats = {}
    for cname, (cstart_s, cend_s) in CRISIS_WINDOWS.items():
        cstart = datetime.date.fromisoformat(cstart_s)
        cend = datetime.date.fromisoformat(cend_s)
        c_indices = [i for i, d in enumerate(dates) if cstart <= d <= cend]
        if c_indices:
            start_eq = equity[c_indices[0]]
            end_eq = equity[c_indices[-1] + 1]
            crisis_ret = end_eq / start_eq - 1.0
            # max drawdown within window
            w_peak = start_eq
            w_mdd = 0.0
            for ci in c_indices:
                v = equity[ci + 1]
                if v > w_peak:
                    w_peak = v
                dd = (w_peak - v) / w_peak
                if dd > w_mdd:
                    w_mdd = dd
            crisis_stats[cname] = {"ret": crisis_ret, "max_dd": w_mdd}

    return {
        "label": label,
        "n_days": n_days,
        "total_return": total_return,
        "apy": apy,
        "max_dd": max_dd,
        "calmar": calmar,
        "oos_apy": oos_apy,
        "oos_max_dd": oos_max_dd,
        "oos_calmar": oos_calmar,
        "crisis": crisis_stats,
    }


# ── benchmarks ─────────────────────────────────────────────────────────────────

def run_equal_weight(
    dates: list[datetime.date],
    aligned: dict[str, list[float]],
) -> dict:
    """Equal-weight benchmark across all 5 books."""
    n_books = len(BOOKS)
    eq = 1.0
    equity = [1.0]
    for i in range(len(dates)):
        daily_r = sum(aligned[b][i] for b in BOOKS) / n_books
        eq *= (1.0 + daily_r)
        equity.append(eq)

    daily_rets = [equity[i + 1] / equity[i] - 1.0 for i in range(len(equity) - 1)]
    n_days = len(daily_rets)
    total_return = equity[-1] - 1.0
    apy = (equity[-1] ** (365.0 / n_days)) - 1.0 if n_days > 0 else 0.0

    peak = 1.0
    max_dd = 0.0
    for eq_val in equity:
        if eq_val > peak:
            peak = eq_val
        dd = (peak - eq_val) / peak
        if dd > max_dd:
            max_dd = dd

    calmar = apy / max_dd if max_dd > 1e-9 else float("inf")

    oos_start_idx = next((i for i, d in enumerate(dates) if d >= OOS_DATE), None)
    oos_apy = oos_max_dd = oos_calmar = None
    if oos_start_idx is not None and oos_start_idx < len(dates) - 1:
        oos_eq = equity[oos_start_idx + 1:]
        oos_anchor = equity[oos_start_idx]
        oos_eq_norm = [v / oos_anchor for v in oos_eq]
        n_oos = len(oos_eq)
        oos_apy_v = (oos_eq_norm[-1] ** (365.0 / n_oos)) - 1.0 if n_oos > 0 else 0.0
        oos_peak = 1.0
        oos_mdd = 0.0
        for v in oos_eq_norm:
            if v > oos_peak:
                oos_peak = v
            dd = (oos_peak - v) / oos_peak
            if dd > oos_mdd:
                oos_mdd = dd
        oos_apy = oos_apy_v
        oos_max_dd = oos_mdd
        oos_calmar = oos_apy / oos_mdd if oos_mdd > 1e-9 else float("inf")

    crisis_stats = {}
    for cname, (cstart_s, cend_s) in CRISIS_WINDOWS.items():
        cstart = datetime.date.fromisoformat(cstart_s)
        cend = datetime.date.fromisoformat(cend_s)
        c_indices = [i for i, d in enumerate(dates) if cstart <= d <= cend]
        if c_indices:
            start_eq = equity[c_indices[0]]
            end_eq = equity[c_indices[-1] + 1]
            crisis_ret = end_eq / start_eq - 1.0
            w_peak = start_eq
            w_mdd = 0.0
            for ci in c_indices:
                v = equity[ci + 1]
                if v > w_peak:
                    w_peak = v
                dd = (w_peak - v) / w_peak
                if dd > w_mdd:
                    w_mdd = dd
            crisis_stats[cname] = {"ret": crisis_ret, "max_dd": w_mdd}

    return {
        "label": "EW (equal-weight)",
        "n_days": n_days,
        "total_return": total_return,
        "apy": apy,
        "max_dd": max_dd,
        "calmar": calmar,
        "oos_apy": oos_apy,
        "oos_max_dd": oos_max_dd,
        "oos_calmar": oos_calmar,
        "crisis": crisis_stats,
    }


# ── parameter sensitivity sweep ────────────────────────────────────────────────

def param_sweep(
    dates: list[datetime.date],
    aligned: dict[str, list[float]],
) -> list[dict]:
    """Sweep ES_PCT and WINDOW to find robustness."""
    results = []
    for es_pct in [0.05, 0.10, 0.15, 0.20]:
        for window in [30, 60, 90]:
            r = run_backtest(dates, aligned, es_pct=es_pct, window=window,
                             label=f"MES es={es_pct:.0%} w={window}")
            results.append(r)
    return results


# ── final weight snapshot ──────────────────────────────────────────────────────

def final_weights(
    dates: list[datetime.date],
    aligned: dict[str, list[float]],
) -> dict[str, float]:
    """Weights that would be used if today were the last day in the fixture."""
    n = len(dates)
    win_start = max(0, n - WINDOW)
    window_rets = {b: aligned[b][win_start:n] for b in BOOKS}
    n_tail = max(2, round(WINDOW * ES_PCT))
    return _compute_mes_weights(window_rets, n_tail)


# ── print helpers ─────────────────────────────────────────────────────────────

def _fmt(r: dict) -> str:
    oos_c = f"{r['oos_calmar']:.2f}" if r["oos_calmar"] is not None else "n/a"
    oos_a = f"{r['oos_apy']:.1%}" if r["oos_apy"] is not None else "n/a"
    return (f"  {r['label']:<40}"
            f"  APY(bt)={r['apy']:+.1%}  maxDD={r['max_dd']:.1%}"
            f"  Calmar={r['calmar']:.2f}"
            f"  OOS-APY={oos_a}  OOS-Calmar={oos_c}")


def main() -> None:
    print("=" * 72)
    print("MES: Marginal Expected Shortfall Allocation — Backtest")
    print("Evidence level: BACKTEST (bt). NOT realized. IS_ADVISORY=True.")
    print("=" * 72)
    print()

    book_rets = _load_returns()
    dates, aligned = _align_dates(book_rets)

    print(f"Fixture: {dates[0].isoformat()} .. {dates[-1].isoformat()}"
          f"  ({len(dates)} trading days)")
    print(f"Books: {', '.join(BOOKS)}")
    print(f"OOS split: {OOS_DATE.isoformat()}")
    print()

    # run equal-weight benchmark
    ew = run_equal_weight(dates, aligned)
    print("BENCHMARKS:")
    print(_fmt(ew))
    print(f"  {'RWA floor':<40}  APY(ref)={RWA_APY:+.1%}  (threshold)")
    print(f"  {'Rates carry':<40}  APY(ref)={RATES_APY:+.1%}  (threshold)")
    print()

    # run primary MES strategy
    mes_main = run_backtest(dates, aligned,
                            es_pct=ES_PCT, window=WINDOW,
                            label=f"MES (es={ES_PCT:.0%}, w={WINDOW}d, rf={REBAL_FREQ}d)")
    print("PRIMARY (MES):")
    print(_fmt(mes_main))
    print()

    # crisis breakdown
    print("CRISIS BREAKDOWN (primary MES vs equal-weight):")
    for cname in CRISIS_WINDOWS:
        m = mes_main["crisis"].get(cname, {})
        e = ew["crisis"].get(cname, {})
        m_ret = m.get("ret", float("nan"))
        e_ret = e.get("ret", float("nan"))
        m_mdd = m.get("max_dd", float("nan"))
        e_mdd = e.get("max_dd", float("nan"))
        print(f"  {cname}:")
        print(f"    EW  ret={e_ret:+.1%}  maxDD={e_mdd:.1%}")
        print(f"    MES ret={m_ret:+.1%}  maxDD={m_mdd:.1%}  "
              f"delta_ret={m_ret - e_ret:+.1%}")
    print()

    # parameter sweep
    print("PARAMETER SWEEP (ES_PCT × WINDOW):")
    print(f"  {'label':<45}  Calmar  OOS-Calmar")
    sweep = param_sweep(dates, aligned)
    for r in sorted(sweep, key=lambda x: x["calmar"], reverse=True):
        oos_c = f"{r['oos_calmar']:.2f}" if r["oos_calmar"] is not None else "n/a"
        print(f"  {r['label']:<45}  {r['calmar']:.2f}    {oos_c}")
    print()

    # final weights
    fw = final_weights(dates, aligned)
    print("FINAL WEIGHTS (as of fixture end):")
    for b, w in sorted(fw.items(), key=lambda x: -x[1]):
        print(f"  {b:<20}  {w:.1%}")
    print()

    # honest summary
    print("=" * 72)
    print("HONEST ASSESSMENT:")
    calmar_vs_ew = mes_main["calmar"] - ew["calmar"]
    print(f"  MES Calmar vs EW: {mes_main['calmar']:.2f} vs {ew['calmar']:.2f}"
          f"  (delta {calmar_vs_ew:+.2f})")
    print(f"  MES APY vs RWA floor: {mes_main['apy']:.1%} vs {RWA_APY:.1%}"
          f"  (spread {mes_main['apy'] - RWA_APY:+.1%})")
    if mes_main["oos_calmar"] is not None:
        print(f"  OOS Calmar: {mes_main['oos_calmar']:.2f}"
              f"  OOS APY: {mes_main['oos_apy']:.1%}")
    print()
    best_sweep = max(sweep, key=lambda x: x["calmar"])
    print(f"  Best sweep config: {best_sweep['label']}")
    best_oos = f"{best_sweep['oos_calmar']:.2f}" if best_sweep["oos_calmar"] is not None else "n/a"
    print(f"    Calmar={best_sweep['calmar']:.2f}  OOS-Calmar={best_oos}")
    print()
    print("CAVEATS:")
    print("  1. Fixture front-loads 50%+ of each crisis loss on day 1 — causal methods")
    print("     cannot avoid this hit; MES reacts AFTER the initial shock.")
    print("  2. Rolling window (60d) with 10% tail = 6 conditioning days → high variance")
    print("     in MES estimates. Real data needs longer window or higher ES_PCT.")
    print("  3. Points-farm book (incentive_decay) is structurally protected here because")
    print("     it has low crisis returns, but its real-world risk (incentive disappearance)")
    print("     is NOT captured in portfolio tail days — a known fixture blind spot.")
    print("  4. No transaction costs, borrow costs, or liquidity constraints modelled.")
    print("  5. All numbers are BACKTEST (bt) on a synthetic fixture. NOT realized returns.")


if __name__ == "__main__":
    main()
