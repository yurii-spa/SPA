#!/usr/bin/env python3
"""
scripts/edge_ctac_tail_persistence.py — Idea #127 (CTAC)

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the live paper track, or the fleet.

CROSS-TAIL ADVERSARIAL CALIBRATION (CTAC)
==========================================
Hypothesis: a book's tail loss in crisis N is a causal, forward-looking predictor of its tail
loss in crisis N+1, because the UNDERLYING RISK SHAPE (funding_flip / depeg / liquidation /
incentive_decay) is PERSISTENT across crisis types.

If the hypothesis holds, an allocation that re-sizes INVERSELY to observed crisis losses
(CTAC) should outperform equal-weight on subsequent crises — at no cost to calm-period carry,
since the highest-σ books are already capped.

Why this is new compared to the registry
-----------------------------------------
Previous entries (#16–#17, #40, #108, etc.) size by rolling trailing statistics (σ, σ_down,
mu, Sortino) computed on the FULL history window. CTAC instead uses EPISODIC information:
"what actually happened in the most recent identifiable crisis event?" The difference matters
because: (a) crisis tails are front-loaded in the fixture (so a trailing-30-day window sees
the tail WHILE it happens, not BEFORE); (b) the crisis event is identifiable by an EXOGENOUS
signal (breadth across books, or the RTMR onset signal), not just own-book trailing vol.

Three causal portfolios:
  ew            — equal weight at all times (baseline)
  ctac_1        — after crisis 1 ends, re-size inversely to crisis-1 losses; fixed until crisis 2
  ctac_cumul    — after each crisis, re-size inversely to CUMULATIVE observed losses
  ctac_hindsight— hindsight upper bound: sizes from day 1 using ALL three crises (look-ahead!)
  anti_ctac     — deliberate anti-CTAC: overweight books that SUFFERED MOST in the prior crisis

Three diagnostic questions:
  Q1. Does CTAC beat equal-weight on portfolio maxDD? (tail protection)
  Q2. Does CTAC pay a carry toll? (does overweighting "quieter" books reduce APY?)
  Q3. Is the gain driven by crisis avoidance, or by calm-period carry differences?

Honest caveats declared up front:
  • evidence: [bt] L0 — synthetic deterministic fixture, NOT a real-feed result
  • fixture crises are exact hits (no noise) — real crises have lead-in, not front-load
  • CTAC weights update ONCE per crisis, not daily (no transaction costs for the update)
  • the RWA floor (3.4%/yr) is NOT used here — de-risking to cash during crises is left for
    a future entry; here we size portfolios but never exit entirely
  • hindsight portfolio is clearly labeled as LOOK-AHEAD and never presented as achievable
  • thin_new excluded (no backtest data)
  • IS_ADVISORY=True; RiskPolicy v1.0 not touched; no live track, no fleet

stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab.aggressive_lab.fixtures import (  # noqa: E402
    roster,
    strategy_jsonl,
    strategy_meta,
)
from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS  # noqa: E402

# ── constants ─────────────────────────────────────────────────────────────────────────────────
EPSILON = 1e-9           # avoids division by zero in inverted weights
ROUND_TRIP_BPS = 96e-4   # 96 bps for one re-sizing event (canonical #10/#49)
RWA_FLOOR_APY = 0.034    # 3.4 %/yr — used only in the final verdict comparison

# ── load fixture returns for the backtest phase only ─────────────────────────────────────────

def _load_returns() -> Tuple[List[str], Dict[str, List[float]], Dict[str, str]]:
    """
    Returns (dates, rets, book_shapes) for the backtest phase only.
    dates is a sorted list of ISO date strings.
    rets[book][t] is the day-t fractional return (equity[t]/equity[t-1] - 1).
    Drops thin_new (no_backtest=True) and variant_d edge-case (directional ETH-beta, not carry).
    """
    # Include only carry/yield books (exclude variant_d as it is flagged RiskClass B / ETH-beta)
    # and exclude thin_new (no backtest).
    EXCLUDE = {"thin_new", "variant_d"}

    raw: Dict[str, List[Tuple[str, float]]] = {}
    shapes: Dict[str, str] = {}
    for book_id in roster():
        if book_id in EXCLUDE:
            continue
        meta = strategy_meta(book_id)
        shapes[book_id] = meta.get("risk_shape", "unknown")
        series_raw = []
        for line in strategy_jsonl(book_id).strip().split("\n"):
            row = json.loads(line)
            if row.get("phase", "forward") == "backtest":
                series_raw.append((row["date"], float(row["equity_usd"])))
        series_raw.sort(key=lambda x: x[0])
        raw[book_id] = series_raw

    # Build a common date axis (intersection)
    date_sets = [set(d for d, _ in v) for v in raw.values()]
    common_dates = sorted(date_sets[0].intersection(*date_sets[1:]))

    rets: Dict[str, List[float]] = {b: [] for b in raw}
    for book_id, series in raw.items():
        by_date = {d: e for d, e in series}
        eq = [by_date[d] for d in common_dates]
        rets[book_id] = [eq[t] / eq[t - 1] - 1.0 for t in range(1, len(eq))]

    return common_dates[1:], rets, shapes


def _crisis_phase(date: str, windows: list) -> Optional[str]:
    """Return the crisis key if date falls within a stress window, else None."""
    for w in windows:
        if w["date_from"] <= date <= w["date_to"]:
            return w["key"]
    return None


# ── observe per-book realized loss in a crisis window ────────────────────────────────────────

def _observe_crisis_loss(
    dates: List[str], rets: Dict[str, List[float]], window_key: str
) -> Dict[str, float]:
    """
    Measure the realized peak-to-trough loss for each book WITHIN the named crisis window.
    Returns {book_id: fractional_loss} — a positive number means a loss.
    Uses a simple peak-to-trough on the cumulative return WITHIN the window.
    """
    books = list(rets.keys())
    # find the indices for the window
    window = next(w for w in STRESS_WINDOWS if w["key"] == window_key)
    wstart, wend = window["date_from"], window["date_to"]

    losses: Dict[str, float] = {}
    for book in books:
        cum = 1.0
        peak = 1.0
        worst = 0.0
        in_window = False
        for i, d in enumerate(dates):
            if d >= wstart:
                in_window = True
            if d > wend:
                break
            if in_window:
                cum *= 1.0 + rets[book][i]
                if cum > peak:
                    peak = cum
                dd = (peak - cum) / peak
                if dd > worst:
                    worst = dd
        losses[book] = worst
    return losses


# ── build CTAC weights from observed cumulative losses ────────────────────────────────────────

def _ctac_weights(cumulative_losses: Dict[str, float]) -> Dict[str, float]:
    """
    Build CTAC weights: inversely proportional to observed cumulative loss.
    Books with zero observed loss get a weight based on EPSILON (tiny, as if loss=epsilon).
    Normalized to sum to 1.
    """
    books = list(cumulative_losses.keys())
    inv = {b: 1.0 / max(cumulative_losses[b], EPSILON) for b in books}
    total = sum(inv.values())
    return {b: inv[b] / total for b in books}


def _ew_weights(books: list) -> Dict[str, float]:
    n = len(books)
    return {b: 1.0 / n for b in books}


def _anti_ctac_weights(cumulative_losses: Dict[str, float]) -> Dict[str, float]:
    """
    Anti-CTAC: overweight the books that SUFFERED MOST (momentum into bad performers).
    Weights proportional to observed losses (not inverse).
    """
    books = list(cumulative_losses.keys())
    total_loss = sum(max(cumulative_losses[b], EPSILON) for b in books)
    return {b: max(cumulative_losses[b], EPSILON) / total_loss for b in books}


# ── simulate a portfolio ──────────────────────────────────────────────────────────────────────

def _simulate_portfolio(
    dates: List[str],
    rets: Dict[str, List[float]],
    weight_schedule: Dict[str, Dict[str, float]],
) -> List[float]:
    """
    Simulate a portfolio where weights may change at certain dates.

    weight_schedule: {date_str: {book: weight}}
    On each date, if that date is in the schedule, apply the new weights
    (charging a round-trip rebalancing cost of ROUND_TRIP_BPS on the fraction that moved).

    Returns a list of daily fractional returns for the portfolio.
    """
    books = list(rets.keys())
    n = len(dates)

    # Start with equal weight
    cur_weights = _ew_weights(books)
    port_rets: List[float] = []

    for t, d in enumerate(dates):
        # Check if we're updating weights today
        if d in weight_schedule:
            new_w = weight_schedule[d]
            # Compute turnover (fraction of portfolio that needs to move)
            turnover = sum(abs(new_w.get(b, 0.0) - cur_weights.get(b, 0.0)) for b in books) / 2.0
            transaction_cost = turnover * ROUND_TRIP_BPS
            cur_weights = new_w

        # Compute daily return with current weights
        r = sum(cur_weights.get(b, 0.0) * rets[b][t] for b in books)
        # Apply transaction cost on the day of rebalancing
        if d in weight_schedule:
            r -= transaction_cost

        port_rets.append(r)

    return port_rets


# ── performance metrics ───────────────────────────────────────────────────────────────────────

def _metrics(rets: List[float], label: str = "") -> dict:
    """Compute APY, maxDD, Calmar from a list of daily fractional returns."""
    if not rets:
        return {"label": label, "apy": None, "max_dd": None, "calmar": None,
                "down_days": None, "n": 0}

    n = len(rets)
    years = n / 365.25

    # Cumulative equity
    equity = [1.0]
    for r in rets:
        equity.append(equity[-1] * (1.0 + r))

    total_return = equity[-1] - 1.0
    apy = (equity[-1] ** (1.0 / years) - 1.0) * 100.0  # percent

    # Max drawdown
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak
        if dd > max_dd:
            max_dd = dd
    max_dd_pct = max_dd * 100.0

    # Calmar
    calmar: Optional[float]
    if max_dd > 1e-9:
        calmar = (apy / 100.0) / max_dd
    else:
        calmar = None  # vyroen — not measured (no down days on this window)

    down_days = sum(1 for r in rets if r < -1e-12)

    return {
        "label": label,
        "apy_pct": round(apy, 3),
        "max_dd_pct": round(max_dd_pct, 4),
        "calmar": round(calmar, 3) if calmar is not None else "REFUSED(vyroen)",
        "down_days": down_days,
        "n_days": n,
    }


def _phase_rets(rets: List[float], dates: List[str], d_from: str, d_to: str) -> List[float]:
    """Slice returns for dates in [d_from, d_to]."""
    result = []
    for i, d in enumerate(dates):
        if d_from <= d <= d_to:
            result.append(rets[i])
    return result


# ── main ──────────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 72)
    print("CTAC — Cross-Tail Adversarial Calibration  [bt] L0  IS_ADVISORY=True")
    print("Idea #127 (CTAC — Cross-Tail Adversarial Calibration)")
    print("=" * 72)
    print()

    dates, rets, shapes = _load_returns()
    books = sorted(rets.keys())

    print(f"Books in scope: {books}")
    print(f"Risk shapes:    {', '.join(f'{b}={shapes[b]}' for b in books)}")
    print(f"Date range:     {dates[0]} … {dates[-1]}  ({len(dates)} days)")
    print()

    # ── Step 1: Observe per-crisis tail losses ──────────────────────────────
    crisis_keys = [w["key"] for w in STRESS_WINDOWS]
    print("§1  OBSERVED TAIL LOSSES per crisis window")
    print("-" * 60)

    per_crisis_losses: Dict[str, Dict[str, float]] = {}
    for ck in crisis_keys:
        losses = _observe_crisis_loss(dates, rets, ck)
        per_crisis_losses[ck] = losses
        w = next(w for w in STRESS_WINDOWS if w["key"] == ck)
        print(f"  {ck} ({w['date_from']} .. {w['date_to']}):")
        for b in books:
            print(f"    {b:20s}  {losses[b]*100:.2f}%")
    print()

    # ── Step 2: CTAC weight schedule ────────────────────────────────────────
    # Weights change the day AFTER the crisis window closes (causal)
    crisis_end_dates = {w["key"]: w["date_to"] for w in STRESS_WINDOWS}

    # cumulative losses: sum up as each crisis is observed
    cumulative_losses: Dict[str, float] = {b: 0.0 for b in books}

    # ctac_1: after crisis 1 (eth_crash_2024_08)
    ck1 = "eth_crash_2024_08"
    cum1 = {b: per_crisis_losses[ck1][b] for b in books}
    ctac1_weights = _ctac_weights(cum1)

    # ctac_cumul after crisis 2
    cum2 = {b: per_crisis_losses[ck1][b] + per_crisis_losses["usde_unwind_2025_10"][b]
            for b in books}
    ctac2_weights = _ctac_weights(cum2)

    # ctac_cumul after crisis 3 (same as hindsight but delayed)
    cum3 = {b: sum(per_crisis_losses[ck][b] for ck in crisis_keys) for b in books}
    ctac3_weights = _ctac_weights(cum3)

    # hindsight: same as ctac3 but applied from day 1
    hindsight_weights = ctac3_weights

    # anti_ctac: after crisis 1, overweight the worst performers
    anti1_weights = _anti_ctac_weights(cum1)

    print("§2  CTAC WEIGHT SCHEDULES")
    print("-" * 60)
    print("  After crisis 1 (causal):")
    for b in books:
        print(f"    {b:20s}  {ctac1_weights[b]*100:.1f}%")
    print("  After crisis 2 (causal cumul):")
    for b in books:
        print(f"    {b:20s}  {ctac2_weights[b]*100:.1f}%")
    print("  Hindsight (all crises, look-ahead!):")
    for b in books:
        print(f"    {b:20s}  {hindsight_weights[b]*100:.1f}%")
    print("  Anti-CTAC after crisis 1 (overweight bad performers):")
    for b in books:
        print(f"    {b:20s}  {anti1_weights[b]*100:.1f}%")
    print()

    # The day AFTER a crisis window closes, we update weights
    # We use the next available date in our date list
    def _next_date(end_date: str) -> Optional[str]:
        for d in dates:
            if d > end_date:
                return d
        return None

    d_after_c1 = _next_date(crisis_end_dates[ck1])
    d_after_c2 = _next_date(crisis_end_dates["usde_unwind_2025_10"])
    d_after_c3 = _next_date(crisis_end_dates["rseth_depeg_2026_04"])

    # ── Step 3: Build weight schedules ──────────────────────────────────────
    ew = {b: 1.0 / len(books) for b in books}

    sched_ew: Dict[str, Dict[str, float]] = {}  # no changes = stays EW

    sched_ctac1: Dict[str, Dict[str, float]] = {}
    if d_after_c1:
        sched_ctac1[d_after_c1] = ctac1_weights

    sched_ctac_cumul: Dict[str, Dict[str, float]] = {}
    if d_after_c1:
        sched_ctac_cumul[d_after_c1] = ctac1_weights
    if d_after_c2:
        sched_ctac_cumul[d_after_c2] = ctac2_weights

    sched_hindsight: Dict[str, Dict[str, float]] = {dates[0]: hindsight_weights}

    sched_anti: Dict[str, Dict[str, float]] = {}
    if d_after_c1:
        sched_anti[d_after_c1] = anti1_weights

    # ── Step 4: Simulate ─────────────────────────────────────────────────────
    port_ew = _simulate_portfolio(dates, rets, sched_ew)
    port_ctac1 = _simulate_portfolio(dates, rets, sched_ctac1)
    port_ctac_cumul = _simulate_portfolio(dates, rets, sched_ctac_cumul)
    port_hindsight = _simulate_portfolio(dates, rets, sched_hindsight)
    port_anti = _simulate_portfolio(dates, rets, sched_anti)

    # ── Step 5: Full-period metrics ──────────────────────────────────────────
    print("§3  FULL-PERIOD PERFORMANCE  [bt] = backtest result, NOT realized")
    print("-" * 72)
    portfolios = [
        ("eq_weight [bt]", port_ew),
        ("ctac_1    [bt]", port_ctac1),
        ("ctac_cumul[bt]", port_ctac_cumul),
        ("hindsight [bt!LOOK-AHEAD]", port_hindsight),
        ("anti_ctac [bt]", port_anti),
    ]
    header = f"{'Portfolio':30s} {'APY%':>8s} {'maxDD%':>8s} {'Calmar':>10s} {'downdays':>9s}"
    print(header)
    print("-" * 72)
    for label, pr in portfolios:
        m = _metrics(pr, label)
        cal = m["calmar"]
        cal_str = f"{cal:.3f}" if isinstance(cal, float) else str(cal)
        print(f"{label:30s} {m['apy_pct']:>8.2f} {m['max_dd_pct']:>8.3f} {cal_str:>10s} {m['down_days']:>9d}")
    print()

    # ── Step 6: Per-phase breakdown ──────────────────────────────────────────
    phases = [
        ("before_c1",        dates[0],             crisis_end_dates["eth_crash_2024_08"]),
        ("during_c1",         STRESS_WINDOWS[0]["date_from"], STRESS_WINDOWS[0]["date_to"]),
        ("between_c1_c2",    crisis_end_dates["eth_crash_2024_08"], STRESS_WINDOWS[1]["date_from"]),
        ("during_c2",         STRESS_WINDOWS[1]["date_from"], STRESS_WINDOWS[1]["date_to"]),
        ("between_c2_c3",    crisis_end_dates["usde_unwind_2025_10"], STRESS_WINDOWS[2]["date_from"]),
        ("during_c3",         STRESS_WINDOWS[2]["date_from"], STRESS_WINDOWS[2]["date_to"]),
        ("after_c3",          crisis_end_dates["rseth_depeg_2026_04"], dates[-1]),
    ]

    print("§4  PER-PHASE BREAKDOWN (APY %, maxDD %)")
    print("-" * 80)
    phase_header = f"{'Phase':22s} {'n':>4s}  " + "  ".join(
        f"{name[:10]:>12s}" for name, _ in portfolios
    )
    print(phase_header)
    print("-" * 80)
    for pname, pfrom, pto in phases:
        row_parts = [f"{pname:22s}"]
        ph_ew = _phase_rets(port_ew, dates, pfrom, pto)
        n = len(ph_ew)
        row_parts.append(f"{n:>4d}  ")
        for _, pr in portfolios:
            ph = _phase_rets(pr, dates, pfrom, pto)
            if not ph:
                row_parts.append(f"{'N/A':>12s}")
                continue
            m = _metrics(ph)
            row_parts.append(f"{m['apy_pct']:>5.1f}%/{m['max_dd_pct']:>4.1f}%")
        print("  ".join(row_parts))
    print()

    # ── Step 7: Q1/Q2/Q3 answers ─────────────────────────────────────────────
    print("§5  HYPOTHESIS ANSWERS")
    print("-" * 72)

    m_ew = _metrics(port_ew)
    m_c1 = _metrics(port_ctac1)
    m_cc = _metrics(port_ctac_cumul)
    m_hi = _metrics(port_hindsight)
    m_an = _metrics(port_anti)

    def _calmar_val(m):
        c = m["calmar"]
        return c if isinstance(c, float) else 0.0

    print("Q1 — Does CTAC reduce maxDD vs equal-weight?")
    print(f"     EW maxDD={m_ew['max_dd_pct']:.3f}%  CTAC-1 maxDD={m_c1['max_dd_pct']:.3f}%"
          f"  CTAC-cumul maxDD={m_cc['max_dd_pct']:.3f}%")
    ans1 = m_c1["max_dd_pct"] < m_ew["max_dd_pct"]
    print(f"     → {'YES ✅' if ans1 else 'NO ❌'}: CTAC-1 {'smaller' if ans1 else 'larger'} maxDD")
    print()

    print("Q2 — Does CTAC pay a carry toll (lower APY)?")
    print(f"     EW APY={m_ew['apy_pct']:.2f}%  CTAC-1 APY={m_c1['apy_pct']:.2f}%")
    ans2 = m_c1["apy_pct"] < m_ew["apy_pct"]
    print(f"     → {'YES (toll paid)' if ans2 else 'NO (free or positive) ✅'}")
    print()

    print("Q3 — Is the Calmar (risk-adj return) improved?")
    c_ew = _calmar_val(m_ew)
    c_c1 = _calmar_val(m_c1)
    print(f"     EW Calmar={c_ew:.3f}  CTAC-1 Calmar={c_c1:.3f}")
    ans3 = c_c1 > c_ew
    print(f"     → {'YES ✅' if ans3 else 'NO ❌'}: CTAC-1 is {'better' if ans3 else 'worse'}")
    print()

    print("Q4 — Does the anti-CTAC (overweight bad performers) lose?")
    c_an = _calmar_val(m_an)
    print(f"     Anti-CTAC Calmar={c_an:.3f} vs CTAC-1 Calmar={c_c1:.3f}")
    ans4 = c_an < c_c1
    print(f"     → {'YES ✅ (directionality confirmed)' if ans4 else 'NO ❌ (directionality not confirmed)'}")
    print()

    # ── Step 8: Honest verdict ────────────────────────────────────────────────
    print("§6  HONEST VERDICT  [bt]")
    print("-" * 72)

    positive_result = ans1 and ans3

    if positive_result:
        print("✅ POSITIVE [bt] — CTAC improves risk-adjusted returns on the fixture.")
    else:
        print("❌ NEGATIVE/NEUTRAL [bt] — CTAC does not clearly improve on equal-weight.")

    print()
    print("CAVEATS (read before forwarding this number):")
    print("  1. [bt] L0 — synthetic deterministic fixture, stress windows are EXACT hits.")
    print("     Real crises have stochastic lead-in; CTAC may see partial information, not full.")
    print("  2. The fixture has only 3 crisis windows. CTAC has 2 'causal' update steps.")
    print("     A 3-window train→test split is structurally weak (insufficient OOS).")
    print("  3. On the fixture, high-CTAC-weight books coincide with high-APY books")
    print("     (points_farm, susde_dn). Real panels may not have this correlation.")
    print("  4. Transaction cost is only charged at rebalancing events (2 times for ctac_1).")
    print("     Daily churn is zero — an unrealistic assumption for a real implementation.")
    print("  5. IS_ADVISORY=True. RiskPolicy v1.0 UNTOUCHED. No live track modified.")
    print()
    print(f"Next step (if positive): re-test on the REAL panel (data/aggressive_lab/)")
    print(f"  using phase='backtest' block — the same structure, but with real calendar noise.")
    print(f"  Tool: scripts/edge_real_panel_ensemble.py as template (RPE.load_panel pattern).")
    print()

    # Return result dict for registry entry generation
    return {
        "verdict": "POSITIVE" if positive_result else "NEGATIVE",
        "ew_apy": m_ew["apy_pct"],
        "ew_maxdd": m_ew["max_dd_pct"],
        "ew_calmar": _calmar_val(m_ew),
        "ctac1_apy": m_c1["apy_pct"],
        "ctac1_maxdd": m_c1["max_dd_pct"],
        "ctac1_calmar": _calmar_val(m_c1),
        "ctac_cumul_calmar": _calmar_val(m_cc),
        "hindsight_calmar": _calmar_val(m_hi),
        "anti_calmar": _calmar_val(m_an),
    }


if __name__ == "__main__":
    result = main()
    sys.exit(0)
