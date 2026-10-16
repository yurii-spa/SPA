#!/usr/bin/env python3
"""
scripts/edge_rkaw_running_calmar_weighting.py

Idea #138 — RKAW: Running-Calmar Allocation Weighting
======================================================
ADVISORY — backtest only. NO imports from spa_core/execution/. stdlib-only.
IS_ADVISORY=True / OUTSIDE_RISKPOLICY=True

Edge hypothesis
---------------
Every prior timing/sizing idea (#1–#137) either:
  (A) sizes ONE fixed strategy (susde_dn) in/out  — KODS #15, DDO #9, etc.
  (B) weights strategies by static cross-sectional metrics at one snapshot.

RKAW asks: can we improve risk-adjusted returns by CONTINUOUSLY rebalancing between
multiple strategies in proportion to each strategy's RUNNING CAUSAL Calmar ratio?

Running-Calmar for strategy i at time t:
  run_apy_i(t)   = annualised cumulative return from backtest day 1 through t
  max_dd_i(t)    = maximum peak-to-trough drawdown from day 1 through t
  run_calmar_i(t) = run_apy_i(t) / max( max_dd_i(t), EPSILON )

Daily portfolio weight:
  raw_i(t)  = max( run_calmar_i(t), 0.0 )   [negative Calmar = near-zero weight]
  w_i(t)    = raw_i(t) / sum_j(raw_j(t))    [normalise]
  w_i(t)    = max( w_i(t), FLOOR_WEIGHT )   [floor prevents total exclusion]
  w_i(t)   /= sum( w )                       [renorm after floor]

Decision point: weights are set on day t-1 data and applied to day t returns (causal).

Novelty vs registry
-------------------
• DDO (#9), KODS (#15), CMRS (#113) — TIMING of ONE strategy (susde_dn)
• XSD (#40), XVD (#45), XDSR (#108) — cross-sectional RANK snapshots, not running Calmar
• MSD-KODS (#130) — fixed composition with KODS timing on the composite
• RKAW — continuous multi-strategy REWEIGHTING by running Calmar (carry per unit of
  realised tail); no external RWA floor; no timing signal

Honest caveats
--------------
(a) Pre-crisis phase: no drawdown has occurred → Calmar = APY / epsilon.
    Weights tilt toward HIGHEST-APY strategy (leverage_loop at 15%), NOT most
    risk-efficient. This look-ahead is ABSENT: early tilt is determined by fixture drift,
    not by oracle knowledge of future crises.
(b) Front-loaded losses in fixture are IMMEDIATE: running Calmar updates on day 1 of
    each crisis window. Therefore RKAW de-risks the day AFTER the first hit (1-day lag).
(c) Daily turnover is high (continuous reweighting). Transaction costs estimated via
    a conservative round-trip cost of COST_BPS per daily weight change ≥ REBALANCE_TOL.
    Sensitivity sweep: 0 / 20 / 50 / 96 bps.
(d) Fixture uses CONSTANT drift (no incentive decay, no carry compression). On real
    data, running-Calmar may lag behind APY deterioration. Clearly labelled [bt].
(e) Strategies compared: fixture roster minus thin_new (no backtest) = 5 strategies.
(f) IS_ADVISORY=True / OUTSIDE_RISKPOLICY=True. Live track NOT touched. RiskPolicy
    v1.0 NOT modified. spa_core/execution NOT imported.
(g) Evidence level: [bt] L0 (deterministic fixture, no real fills).

Metrics reported
----------------
Full axis:  APY (bt) / maxDD (bt) / Calmar (bt) — net of transaction costs
Train/Test split (2025-06-30): same metrics each half + OOS transfer check
Crisis decomposition: portfolio loss in each stress window
Turnover stats: daily switches, total cost burden

Comparison benchmarks (all on same fixture, same axis):
  A. equal-weight (1/5 each of 5 strategies)
  B. RKAW (this idea)
  C. RKAW-KODS: RKAW weights + KODS timing on the composite (best-of-both)
  D. RWA floor (pure safe carry, the floor)

Advisory only. stdlib-only, deterministic, LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple, Optional

_repo = Path(__file__).resolve().parent.parent
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

from spa_core.strategy_lab.aggressive_lab.fixtures import (  # type: ignore[attr-defined]
    _SPEC, _BACKTEST_START, _BACKTEST_END, _build_backtest_series, STRESS_WINDOWS,
)

# ── constants ────────────────────────────────────────────────────────────────────────────────────
RWA_APY_PCT = 3.4           # conservative floor for reference
STRATEGIES = ["susde_dn", "lrt_carry", "leverage_loop", "points_farm", "variant_d"]
N = len(STRATEGIES)
EPSILON = 1e-6              # floor on max_drawdown to avoid division by zero
FLOOR_WEIGHT = 0.02         # minimum weight per strategy (prevents zero exclusion)
REBALANCE_TOL = 0.005       # only log a "rebalance event" if any weight changes > 0.5pp
COST_BPS_SWEEP = [0, 20, 50, 96]   # round-trip cost per switched unit of weight
TRAIN_END = "2025-06-30"           # consistent with registry seam

# KODS constants (re-use KODS idea #15 logic for variant C)
KODS_LOOKBACK = 10          # days in rolling window for Kelly sizing
KODS_MAX_RISKY = 1.0        # max allocation to composite risky sleeve


# ── fixture loading ──────────────────────────────────────────────────────────────────────────────

def _load_returns() -> Dict[str, List[Tuple[str, float]]]:
    """Returns dict: strategy_id -> [(date, daily_return), ...] sorted ascending."""
    out: Dict[str, List[Tuple[str, float]]] = {}
    for sid in STRATEGIES:
        raw = _build_backtest_series(_SPEC[sid])
        eq = {r["date"]: float(r["equity_usd"]) for r in raw if r.get("phase") == "backtest"}
        dates = sorted(eq)
        returns = []
        for i in range(1, len(dates)):
            d_prev, d_curr = dates[i - 1], dates[i]
            returns.append((d_curr, eq[d_curr] / eq[d_prev] - 1.0))
        out[sid] = returns
    return out


# ── Calmar helper ────────────────────────────────────────────────────────────────────────────────

def _running_calmar(equity_path: List[float], n_days: int) -> float:
    """Annualised return / max drawdown for the first n_days of the equity path."""
    if n_days < 2:
        return 0.0
    path = equity_path[:n_days]
    total_return = path[-1] / path[0] - 1.0
    ann_return = total_return * 365.0 / (n_days - 1)
    # max drawdown
    peak = path[0]
    max_dd = 0.0
    for eq in path:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_dd:
            max_dd = dd
    return ann_return / max(max_dd, EPSILON)


def _compute_metrics(
    portfolio_returns: List[Tuple[str, float]]
) -> Tuple[float, float, Optional[float]]:
    """Return (annualised_apy, max_drawdown, calmar). Calmar = None if maxDD = 0."""
    if not portfolio_returns:
        return 0.0, 0.0, None
    n = len(portfolio_returns)
    cumulative = 1.0
    peak = 1.0
    max_dd = 0.0
    for _, r in portfolio_returns:
        cumulative *= (1.0 + r)
        if cumulative > peak:
            peak = cumulative
        dd = (peak - cumulative) / peak
        if dd > max_dd:
            max_dd = dd
    ann_return = (cumulative ** (365.0 / n) - 1.0) * 100.0
    max_dd_pct = max_dd * 100.0
    if max_dd < 1e-9:
        return ann_return, max_dd_pct, None  # unmeasured (invar #17)
    return ann_return, max_dd_pct, ann_return / max_dd_pct


# ── core backtest engine ──────────────────────────────────────────────────────────────────────────

def _compute_rkaw_weights(
    all_returns: Dict[str, List[Tuple[str, float]]],
) -> List[Dict[str, float]]:
    """Return the daily RKAW weight dict for each day in the date axis (causal, no lookahead)."""
    date_axis = [d for d, _ in all_returns[STRATEGIES[0]]]
    equity: Dict[str, List[float]] = {sid: [1.0] for sid in STRATEGIES}
    for sid in STRATEGIES:
        ret_map = dict(all_returns[sid])
        for d in date_axis:
            prev = equity[sid][-1]
            equity[sid].append(prev * (1.0 + ret_map.get(d, 0.0)))

    result: List[Dict[str, float]] = []
    for i in range(len(date_axis)):
        t = i + 1
        raw_calmar: Dict[str, float] = {}
        for sid in STRATEGIES:
            rc = _running_calmar(equity[sid], t)
            raw_calmar[sid] = max(rc, 0.0)
        total_rc = sum(raw_calmar.values())
        if total_rc < EPSILON:
            weights = {sid: 1.0 / N for sid in STRATEGIES}
        else:
            weights = {sid: raw_calmar[sid] / total_rc for sid in STRATEGIES}
            for sid in STRATEGIES:
                weights[sid] = max(weights[sid], FLOOR_WEIGHT)
            total_w = sum(weights.values())
            weights = {sid: weights[sid] / total_w for sid in STRATEGIES}
        result.append(weights)
    return result

def run_rkaw(
    all_returns: Dict[str, List[Tuple[str, float]]],
    cost_bps: float = 0.0,
) -> List[Tuple[str, float]]:
    """
    RKAW: running-Calmar allocation weighting.

    Returns portfolio daily returns [(date, return), ...] for the full axis.
    """
    # Align all strategies to the common date axis
    date_axis = [d for d, _ in all_returns[STRATEGIES[0]]]
    # Build equity paths: start at 1.0
    equity: Dict[str, List[float]] = {sid: [1.0] for sid in STRATEGIES}
    for sid in STRATEGIES:
        ret_map = dict(all_returns[sid])
        for d in date_axis:
            prev = equity[sid][-1]
            equity[sid].append(prev * (1.0 + ret_map.get(d, 0.0)))

    # Previous weights (starts equal)
    prev_weights = {sid: 1.0 / N for sid in STRATEGIES}
    portfolio_returns: List[Tuple[str, float]] = []

    for i, d in enumerate(date_axis):
        # Weights for today were set using data through day i (equity index i+1 includes today)
        # We use equity[sid][i] (before today's return) to set today's weights
        t = i + 1  # number of equity points available (0..t-1)

        # Compute running Calmar for each strategy from equity[:t]
        raw_calmar: Dict[str, float] = {}
        for sid in STRATEGIES:
            rc = _running_calmar(equity[sid], t)
            raw_calmar[sid] = max(rc, 0.0)

        total_rc = sum(raw_calmar.values())
        if total_rc < EPSILON:
            # No meaningful Calmar yet → equal weights
            weights = {sid: 1.0 / N for sid in STRATEGIES}
        else:
            # Proportional weights
            weights = {sid: raw_calmar[sid] / total_rc for sid in STRATEGIES}
            # Apply floor
            for sid in STRATEGIES:
                weights[sid] = max(weights[sid], FLOOR_WEIGHT)
            # Renorm
            total_w = sum(weights.values())
            weights = {sid: weights[sid] / total_w for sid in STRATEGIES}

        # Transaction cost: proportional to weight change
        turnover = sum(abs(weights[sid] - prev_weights[sid]) for sid in STRATEGIES) / 2.0
        cost_today = turnover * cost_bps / 10000.0

        # Portfolio return = weighted sum of today's returns minus cost
        ret_map = {sid: dict(all_returns[sid]).get(d, 0.0) for sid in STRATEGIES}
        port_ret = sum(weights[sid] * ret_map[sid] for sid in STRATEGIES) - cost_today
        portfolio_returns.append((d, port_ret))

        prev_weights = weights
        # Update equity paths with today's return
        # (already done in the equity dict above — we appended next step's equity)

    return portfolio_returns


def run_equal_weight(
    all_returns: Dict[str, List[Tuple[str, float]]],
    cost_bps: float = 0.0,
) -> List[Tuple[str, float]]:
    """Equal-weight baseline: 1/N allocation, no rebalancing."""
    date_axis = [d for d, _ in all_returns[STRATEGIES[0]]]
    portfolio_returns: List[Tuple[str, float]] = []
    for d in date_axis:
        port_ret = sum(
            (1.0 / N) * dict(all_returns[sid]).get(d, 0.0)
            for sid in STRATEGIES
        )
        portfolio_returns.append((d, port_ret - 0.0))  # no rebalancing cost
    return portfolio_returns


def run_rkaw_kods(
    all_returns: Dict[str, List[Tuple[str, float]]],
    cost_bps: float = 0.0,
) -> List[Tuple[str, float]]:
    """
    RKAW-KODS: RKAW composition + KODS timing on the composite.

    Kelly fraction f*(t) = E[r] / Var[r] over a lookback window.
    When f*(t) < 1.0, de-risk to RWA floor for the difference.
    """
    date_axis = [d for d, _ in all_returns[STRATEGIES[0]]]
    equity: Dict[str, List[float]] = {sid: [1.0] for sid in STRATEGIES}
    for sid in STRATEGIES:
        ret_map = dict(all_returns[sid])
        for d in date_axis:
            prev = equity[sid][-1]
            equity[sid].append(prev * (1.0 + ret_map.get(d, 0.0)))

    daily_rwa = RWA_APY_PCT / 100.0 / 365.0
    prev_weights: Dict[str, float] = {sid: 1.0 / N for sid in STRATEGIES}
    composite_returns_history: List[float] = []
    portfolio_returns: List[Tuple[str, float]] = []

    for i, d in enumerate(date_axis):
        t = i + 1
        # RKAW weights
        raw_calmar: Dict[str, float] = {}
        for sid in STRATEGIES:
            rc = _running_calmar(equity[sid], t)
            raw_calmar[sid] = max(rc, 0.0)
        total_rc = sum(raw_calmar.values())
        if total_rc < EPSILON:
            weights = {sid: 1.0 / N for sid in STRATEGIES}
        else:
            weights = {sid: raw_calmar[sid] / total_rc for sid in STRATEGIES}
            for sid in STRATEGIES:
                weights[sid] = max(weights[sid], FLOOR_WEIGHT)
            total_w = sum(weights.values())
            weights = {sid: weights[sid] / total_w for sid in STRATEGIES}

        # KODS: Kelly fraction on composite
        if len(composite_returns_history) >= KODS_LOOKBACK:
            window = composite_returns_history[-KODS_LOOKBACK:]
            mu = sum(window) / len(window)
            var = sum((r - mu) ** 2 for r in window) / len(window)
            kelly_f = mu / var if var > 1e-12 else KODS_MAX_RISKY
            kelly_f = max(0.0, min(KODS_MAX_RISKY, kelly_f))
        else:
            kelly_f = KODS_MAX_RISKY  # full allocation before enough history

        # Today's composite return (before sizing)
        ret_map = {sid: dict(all_returns[sid]).get(d, 0.0) for sid in STRATEGIES}
        composite_today = sum(weights[sid] * ret_map[sid] for sid in STRATEGIES)
        composite_returns_history.append(composite_today)

        # Transaction cost
        turnover = sum(abs(weights[sid] - prev_weights[sid]) for sid in STRATEGIES) / 2.0
        cost_today = turnover * cost_bps / 10000.0

        # Portfolio: kelly_f in composite, (1 - kelly_f) in RWA floor
        port_ret = kelly_f * composite_today + (1.0 - kelly_f) * daily_rwa - cost_today
        portfolio_returns.append((d, port_ret))
        prev_weights = weights

    return portfolio_returns


def _crisis_loss(
    portfolio_returns: List[Tuple[str, float]],
) -> Dict[str, float]:
    """Compute cumulative portfolio loss in each named stress window."""
    losses = {}
    for w in STRESS_WINDOWS:
        lo = w["date_from"]
        hi = w["date_to"]
        cum = 1.0
        for d, r in portfolio_returns:
            if lo <= d <= hi:
                cum *= (1.0 + r)
        losses[str(w["key"])] = (1.0 - cum) * 100.0
    return losses


def _split(
    portfolio_returns: List[Tuple[str, float]], seam: str
) -> Tuple[List[Tuple[str, float]], List[Tuple[str, float]]]:
    train = [(d, r) for d, r in portfolio_returns if d <= seam]
    test = [(d, r) for d, r in portfolio_returns if d > seam]
    return train, test


# ── turnover stats ────────────────────────────────────────────────────────────────────────────────

def _turnover_stats(
    all_returns: Dict[str, List[Tuple[str, float]]],
) -> Dict[str, float]:
    """Compute average daily turnover and number of rebalance events."""
    date_axis = [d for d, _ in all_returns[STRATEGIES[0]]]
    equity: Dict[str, List[float]] = {sid: [1.0] for sid in STRATEGIES}
    for sid in STRATEGIES:
        ret_map = dict(all_returns[sid])
        for d in date_axis:
            prev = equity[sid][-1]
            equity[sid].append(prev * (1.0 + ret_map.get(d, 0.0)))

    prev_weights = {sid: 1.0 / N for sid in STRATEGIES}
    turnovers = []
    rebalance_events = 0

    for i, d in enumerate(date_axis):
        t = i + 1
        raw_calmar: Dict[str, float] = {}
        for sid in STRATEGIES:
            rc = _running_calmar(equity[sid], t)
            raw_calmar[sid] = max(rc, 0.0)
        total_rc = sum(raw_calmar.values())
        if total_rc < EPSILON:
            weights = {sid: 1.0 / N for sid in STRATEGIES}
        else:
            weights = {sid: raw_calmar[sid] / total_rc for sid in STRATEGIES}
            for sid in STRATEGIES:
                weights[sid] = max(weights[sid], FLOOR_WEIGHT)
            total_w = sum(weights.values())
            weights = {sid: weights[sid] / total_w for sid in STRATEGIES}

        turnover = sum(abs(weights[sid] - prev_weights[sid]) for sid in STRATEGIES) / 2.0
        turnovers.append(turnover)
        if turnover > REBALANCE_TOL:
            rebalance_events += 1
        prev_weights = weights

    avg_turnover = sum(turnovers) / len(turnovers) if turnovers else 0.0
    return {
        "avg_daily_turnover_pct": avg_turnover * 100.0,
        "rebalance_events": rebalance_events,
        "total_axis_days": len(date_axis),
        "annual_turnover_pct": avg_turnover * 365.0 * 100.0,
    }


# ── main ──────────────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    all_returns = _load_returns()
    n_days = len(all_returns[STRATEGIES[0]])
    date_axis = [d for d, _ in all_returns[STRATEGIES[0]]]
    print(f"=== RKAW #138: Running-Calmar Allocation Weighting ===")
    print(f"    Axis: {date_axis[0]} … {date_axis[-1]}  ({n_days} days)")
    print(f"    Strategies: {STRATEGIES}")
    print(f"    Train/Test seam: {TRAIN_END}")
    print()

    # ── per-strategy standalone metrics ─────────────────────────────────────────────────
    print("=== Individual strategy metrics (equal-weight reference, full axis) ===")
    print(f"  {'Strategy':<18} {'APY%':>8} {'maxDD%':>8} {'Calmar':>8}  Note")
    for sid in STRATEGIES:
        rets = all_returns[sid]
        apy, mdd, cal = _compute_metrics(rets)
        cal_str = f"{cal:.3f}" if cal is not None else "ОТКАЗАН"
        note = _SPEC[sid].get("note", "")[:50]
        print(f"  {sid:<18} {apy:>8.2f} {mdd:>8.3f} {cal_str:>8}  {note}")
    print()

    # ── RKAW turnover analysis ────────────────────────────────────────────────────────────
    tstats = _turnover_stats(all_returns)
    print("=== RKAW Turnover Statistics ===")
    print(f"  Avg daily turnover: {tstats['avg_daily_turnover_pct']:.4f}%")
    print(f"  Annual turnover:    {tstats['annual_turnover_pct']:.2f}%")
    print(f"  Rebalance events (Δw>{REBALANCE_TOL*100:.1f}pp): {tstats['rebalance_events']}"
          f" / {tstats['total_axis_days']} days")
    print()

    # ── full-axis comparison ──────────────────────────────────────────────────────────────
    print("=== Full-axis comparison (net of transaction costs) ===")
    print(f"  {'Method':<22} {'cost_bps':>8} {'APY%':>8} {'maxDD%':>8} {'Calmar':>8}")

    # Equal weight (no cost)
    ew = run_equal_weight(all_returns, cost_bps=0)
    apy, mdd, cal = _compute_metrics(ew)
    cal_str = f"{cal:.3f}" if cal is not None else "ОТКАЗАН"
    print(f"  {'EqualWeight':<22} {'0':>8} {apy:>8.2f} {mdd:>8.3f} {cal_str:>8}  ← baseline")

    # RKAW at each cost level
    for cost in COST_BPS_SWEEP:
        rkaw = run_rkaw(all_returns, cost_bps=cost)
        apy, mdd, cal = _compute_metrics(rkaw)
        cal_str = f"{cal:.3f}" if cal is not None else "ОТКАЗАН"
        marker = "  ← canonical 96bps" if cost == 96 else ""
        print(f"  {'RKAW':<22} {cost:>8} {apy:>8.2f} {mdd:>8.3f} {cal_str:>8}{marker}")

    # RKAW-KODS at 0 and 96 bps
    for cost in [0, 96]:
        rkods = run_rkaw_kods(all_returns, cost_bps=cost)
        apy, mdd, cal = _compute_metrics(rkods)
        cal_str = f"{cal:.3f}" if cal is not None else "ОТКАЗАН"
        marker = "" if cost == 0 else "  ← canonical 96bps"
        print(f"  {'RKAW-KODS':<22} {cost:>8} {apy:>8.2f} {mdd:>8.3f} {cal_str:>8}{marker}")

    # RWA floor reference
    rwa_daily = RWA_APY_PCT / 100.0 / 365.0
    rwa_rets = [(d, rwa_daily) for d, _ in all_returns[STRATEGIES[0]]]
    apy, mdd, cal = _compute_metrics(rwa_rets)
    cal_str = f"{cal:.3f}" if cal is not None else "ОТКАЗАН"
    print(f"  {'RWA floor':<22} {'0':>8} {apy:>8.2f} {mdd:>8.3f} {cal_str:>8}  ← safe floor")
    print()

    # ── train / test split ────────────────────────────────────────────────────────────────
    print(f"=== Train/Test split (seam: {TRAIN_END}) ===")
    print(f"  {'Method':<22} {'period':>12} {'APY%':>8} {'maxDD%':>8} {'Calmar':>8}")
    for label, series in [
        ("EqualWeight", run_equal_weight(all_returns, cost_bps=0)),
        ("RKAW_0bps", run_rkaw(all_returns, cost_bps=0)),
        ("RKAW_96bps", run_rkaw(all_returns, cost_bps=96)),
        ("RKAW-KODS_0bps", run_rkaw_kods(all_returns, cost_bps=0)),
    ]:
        tr, te = _split(series, TRAIN_END)
        for period_label, portion in [("TRAIN", tr), ("TEST", te)]:
            apy, mdd, cal = _compute_metrics(portion)
            cal_str = f"{cal:.3f}" if cal is not None else "ОТКАЗАН"
            print(f"  {label:<22} {period_label:>12} {apy:>8.2f} {mdd:>8.3f} {cal_str:>8}")
    print()

    # ── crisis decomposition ──────────────────────────────────────────────────────────────
    print("=== Crisis decomposition (portfolio loss % in each window) ===")
    window_labels = [str(w["key"]) for w in STRESS_WINDOWS]
    print(f"  {'Method':<22} " + "  ".join(f"{k:<22}" for k in window_labels))
    for label, series in [
        ("EqualWeight", run_equal_weight(all_returns, cost_bps=0)),
        ("RKAW_0bps",   run_rkaw(all_returns, cost_bps=0)),
        ("RKAW_96bps",  run_rkaw(all_returns, cost_bps=96)),
        ("RKAW-KODS_0bps", run_rkaw_kods(all_returns, cost_bps=0)),
    ]:
        losses = _crisis_loss(series)
        row = "  ".join(f"{losses[k]:>6.2f}%{'':<15}" for k in window_labels)
        print(f"  {label:<22} {row}")
    print()

    # ── RKAW weight trajectory at key dates ──────────────────────────────────────────────
    print("=== RKAW weight snapshot at key dates ===")
    date_axis_full = [d for d, _ in all_returns[STRATEGIES[0]]]
    equity_snap: Dict[str, List[float]] = {sid: [1.0] for sid in STRATEGIES}
    for sid in STRATEGIES:
        ret_map = dict(all_returns[sid])
        for d in date_axis_full:
            prev = equity_snap[sid][-1]
            equity_snap[sid].append(prev * (1.0 + ret_map.get(d, 0.0)))

    snapshot_dates = [
        "2024-07-31",   # pre-crisis
        "2024-08-31",   # after eth_crash
        "2025-01-31",   # midpoint calm
        "2025-10-31",   # after usde_unwind
        "2026-04-30",   # after rseth_depeg
        "2026-05-31",   # end of axis
    ]
    hdr = f"  {'Date':<14} " + " ".join(f"{s:<14}" for s in STRATEGIES)
    print(hdr)
    for snap_d in snapshot_dates:
        if snap_d not in date_axis_full:
            continue
        t = date_axis_full.index(snap_d) + 1
        raw_calmar: Dict[str, float] = {}
        for sid in STRATEGIES:
            rc = _running_calmar(equity_snap[sid], t)
            raw_calmar[sid] = max(rc, 0.0)
        total_rc = sum(raw_calmar.values())
        if total_rc < EPSILON:
            weights = {sid: 1.0 / N for sid in STRATEGIES}
        else:
            weights = {sid: raw_calmar[sid] / total_rc for sid in STRATEGIES}
            for sid in STRATEGIES:
                weights[sid] = max(weights[sid], FLOOR_WEIGHT)
            total_w = sum(weights.values())
            weights = {sid: weights[sid] / total_w for sid in STRATEGIES}
        row = " ".join(f"{weights[sid]*100:>5.1f}%{'':<8}" for sid in STRATEGIES)
        print(f"  {snap_d:<14} {row}")
    print()

    # ── sensitivity: points_farm APY haircut ─────────────────────────────────────────────
    print("=== Sensitivity: 50% APY haircut on points_farm (caveat a) ===")
    import copy
    spec_haircut = {k: copy.deepcopy(v) for k, v in _SPEC.items()}
    spec_haircut["points_farm"]["daily_drift"] /= 2.0  # 14% → 7%
    haircut_returns = dict(all_returns)
    # rebuild points_farm with haircut
    raw_hc = _build_backtest_series(spec_haircut["points_farm"])
    eq_hc = {r["date"]: float(r["equity_usd"]) for r in raw_hc if r.get("phase") == "backtest"}
    dates_hc = sorted(eq_hc)
    haircut_returns["points_farm"] = [
        (dates_hc[i], eq_hc[dates_hc[i]] / eq_hc[dates_hc[i - 1]] - 1.0)
        for i in range(1, len(dates_hc))
    ]
    print(f"  {'Method':<22} {'cost_bps':>8} {'APY%':>8} {'maxDD%':>8} {'Calmar':>8}")
    for cost in [0, 96]:
        rkaw_hc = run_rkaw(haircut_returns, cost_bps=cost)
        apy, mdd, cal = _compute_metrics(rkaw_hc)
        cal_str = f"{cal:.3f}" if cal is not None else "ОТКАЗАН"
        print(f"  {'RKAW_haircut':<22} {cost:>8} {apy:>8.2f} {mdd:>8.3f} {cal_str:>8}")

    ew_hc = run_equal_weight(haircut_returns, cost_bps=0)
    apy, mdd, cal = _compute_metrics(ew_hc)
    cal_str = f"{cal:.3f}" if cal is not None else "ОТКАЗАН"
    print(f"  {'EW_haircut':<22} {'0':>8} {apy:>8.2f} {mdd:>8.3f} {cal_str:>8}")
    print()

    # ── summary verdict ───────────────────────────────────────────────────────────────────
    rkaw_0 = run_rkaw(all_returns, cost_bps=0)
    rkaw_96 = run_rkaw(all_returns, cost_bps=96)
    ew = run_equal_weight(all_returns, cost_bps=0)
    apy_ew, mdd_ew, cal_ew = _compute_metrics(ew)
    apy_0, mdd_0, cal_0 = _compute_metrics(rkaw_0)
    apy_96, mdd_96, cal_96 = _compute_metrics(rkaw_96)

    ew_cal_s = f"{cal_ew:.3f}" if cal_ew is not None else "ОТКАЗАН"
    cal_0_s = f"{cal_0:.3f}" if cal_0 is not None else "ОТКАЗАН"
    cal_96_s = f"{cal_96:.3f}" if cal_96 is not None else "ОТКАЗАН"

    print("=== Summary Verdict ===")
    print(f"  EqualWeight:      APY {apy_ew:.2f}%  maxDD {mdd_ew:.3f}%  Calmar {ew_cal_s}")
    print(f"  RKAW (0bps):      APY {apy_0:.2f}%  maxDD {mdd_0:.3f}%  Calmar {cal_0_s}")
    print(f"  RKAW (96bps):     APY {apy_96:.2f}%  maxDD {mdd_96:.3f}%  Calmar {cal_96_s}")

    if cal_0 is not None and cal_ew is not None:
        delta_calmar = cal_0 - cal_ew
        verdict = "✅ УЛУЧШЕНИЕ" if delta_calmar > 0.1 else "⚠️ МАРГИНАЛЬНОЕ / ❌ НЕТ УЛУЧШЕНИЯ"
        print(f"  ΔCalmar (RKAW_0 vs EW): {delta_calmar:+.3f}  → {verdict}")
    else:
        print("  ΔCalmar: ОТКАЗАН (один знаменатель не измерим)")

    print()
    print("  [bt] L0 — deterministic fixture backtest. IS_ADVISORY=True. NOT live results.")
    print("  Evidence level: BACKTEST on synthetic fixture (Garchive-shaped deterministic data).")


if __name__ == "__main__":
    main()
