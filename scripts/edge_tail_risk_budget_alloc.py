# LLM_FORBIDDEN
"""
scripts/edge_tail_risk_budget_alloc.py — Idea #42: TRB-Alloc

Tail-Risk-Budget Allocation for the Aggressive Tier.

Hypothesis: Among fixed-weight allocations over the 5 aggressive-tier fixture strategies,
weighting INVERSELY proportional to each strategy's worst observed crisis drawdown
(max over stress windows) achieves better risk-adjusted returns than equal-weight or
APY-tilt, because it equalises each strategy's contribution to the portfolio's worst day.

This is a STATIC (no timing, no switching) idea — directly informed by the finding from
#32-#41 that slow/static allocation consistently outperforms de-risking overlays on the
fixture.

Methods compared:
  EW   — equal weight (20% each of 5 strategies)
  APY  — weight proportional to headline APY
  TRB  — weight inversely proportional to max(crisis_hit over stress windows)

Variants (of TRB):
  TRB-max   — inverse of max single-window drawdown
  TRB-sum   — inverse of sum of all window drawdowns
  TRB-worst — inverse of single worst net-pnl day across all windows (geometric front-load)

IS_ADVISORY=True  OUTSIDE_RISKPOLICY  LLM_FORBIDDEN
stdlib-only, deterministic, NO randomness, NO network, NO LLM.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.strategy_lab.aggressive_lab import STRESS_WINDOWS
from spa_core.strategy_lab.aggressive_lab import fixtures as fx

# ── strategy roster (excluding thin_new — no backtest) ──────────────────────
STRATEGIES = ["susde_dn", "lrt_carry", "leverage_loop", "points_farm", "variant_d"]

_SPEC = {
    "susde_dn":      {"headline_apy_pct": 11.0, "daily_drift": 11.0/100.0/365.0,
                      "window_hits": {"eth_crash_2024_08": 0.03, "usde_unwind_2025_10": 0.09, "rseth_depeg_2026_04": 0.01}},
    "lrt_carry":     {"headline_apy_pct": 13.0, "daily_drift": 13.0/100.0/365.0,
                      "window_hits": {"eth_crash_2024_08": 0.05, "usde_unwind_2025_10": 0.04, "rseth_depeg_2026_04": 0.22}},
    "leverage_loop": {"headline_apy_pct": 15.0, "daily_drift": 15.0/100.0/365.0,
                      "window_hits": {"eth_crash_2024_08": 0.06, "usde_unwind_2025_10": 0.28, "rseth_depeg_2026_04": 0.11}},
    "points_farm":   {"headline_apy_pct": 14.0, "daily_drift": 14.0/100.0/365.0,
                      "window_hits": {"eth_crash_2024_08": 0.01, "usde_unwind_2025_10": 0.02, "rseth_depeg_2026_04": 0.015}},
    "variant_d":     {"headline_apy_pct": 9.0,  "daily_drift": 9.0/100.0/365.0,
                      "window_hits": {"eth_crash_2024_08": 0.18, "usde_unwind_2025_10": 0.10, "rseth_depeg_2026_04": 0.20}},
}

_BACKTEST_START = datetime.date(2024, 7, 1)
_BACKTEST_END   = datetime.date(2026, 5, 31)
_INITIAL        = 100_000.0
_COST_BPS       = 10   # round-trip cost on initial allocation (applied once at start)
TRANSACTION_COST_ANNUAL_BPS = 2  # minimal rebalancing cost: annual drift correction ~1bp/month each


# ── weight schemes ────────────────────────────────────────────────────────────

def _weights_equal() -> Dict[str, float]:
    n = len(STRATEGIES)
    return {s: 1.0 / n for s in STRATEGIES}


def _weights_apy() -> Dict[str, float]:
    apy = {s: _SPEC[s]["headline_apy_pct"] for s in STRATEGIES}
    total = sum(apy.values())
    return {s: apy[s] / total for s in STRATEGIES}


def _weights_trb_max() -> Dict[str, float]:
    """Inverse of maximum single-window drawdown."""
    max_hit = {s: max(_SPEC[s]["window_hits"].values()) for s in STRATEGIES}
    inv = {s: 1.0 / max_hit[s] for s in STRATEGIES}
    total = sum(inv.values())
    return {s: inv[s] / total for s in STRATEGIES}


def _weights_trb_sum() -> Dict[str, float]:
    """Inverse of sum of all window drawdowns."""
    sum_hit = {s: sum(_SPEC[s]["window_hits"].values()) for s in STRATEGIES}
    inv = {s: 1.0 / sum_hit[s] for s in STRATEGIES}
    total = sum(inv.values())
    return {s: inv[s] / total for s in STRATEGIES}


def _weights_trb_worst_day() -> Dict[str, float]:
    """Inverse of single worst daily loss (geometric front-load, day-0 of worst window)."""
    worst = {}
    window_lengths: Dict[str, int] = {}
    for w in STRESS_WINDOWS:
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        window_lengths[str(w["key"])] = (hi - lo).days + 1

    for s in STRATEGIES:
        wh = _SPEC[s]["window_hits"]
        best = 0.0
        for key, total in wh.items():
            if total <= 0:
                continue
            n = window_lengths[key]
            norm = sum(0.5 ** j for j in range(n))
            day0_frac = (0.5 ** 0) / norm if norm > 0 else 0.0
            day0_loss = total * day0_frac
            if day0_loss > best:
                best = day0_loss
        worst[s] = best if best > 0 else 1e-6

    inv = {s: 1.0 / worst[s] for s in STRATEGIES}
    total = sum(inv.values())
    return {s: inv[s] / total for s in STRATEGIES}


# ── portfolio equity simulation ───────────────────────────────────────────────

def _window_for(d: datetime.date):
    for w in STRESS_WINDOWS:
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        if lo <= d <= hi:
            return w
    return None


def _simulate(weights: Dict[str, float]) -> Tuple[List[float], float]:
    """
    Returns (equity_curve, total_transaction_cost_fraction).
    Equity curve is list of daily portfolio values starting at _INITIAL.
    Static weights: no rebalancing. Each strategy runs independently,
    portfolio value = sum(w_i * individual_equity_i).
    """
    # Pre-compute window lengths
    window_lengths: Dict[str, int] = {}
    for w in STRESS_WINDOWS:
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        window_lengths[str(w["key"])] = (hi - lo).days + 1

    # Individual equity curves
    eq: Dict[str, float] = {s: _INITIAL * weights[s] for s in STRATEGIES}
    window_day_counters: Dict[str, Dict[str, int]] = {s: {} for s in STRATEGIES}

    portfolio_curve: List[float] = []

    d = _BACKTEST_START
    while d <= _BACKTEST_END:
        w_obj = _window_for(d)
        for s in STRATEGIES:
            spec = _SPEC[s]
            drift = spec["daily_drift"]
            daily_loss = 0.0
            if w_obj is not None:
                key = str(w_obj["key"])
                total = float(spec["window_hits"].get(key, 0.0))
                if total > 0:
                    n = window_lengths[key]
                    idx = window_day_counters[s].get(key, 0)
                    window_day_counters[s][key] = idx + 1
                    norm = sum(0.5 ** j for j in range(n))
                    frac = (0.5 ** idx) / norm if norm > 0 else 0.0
                    daily_loss = total * frac
            eq[s] = eq[s] * (1.0 + drift - daily_loss)
        portfolio_curve.append(sum(eq[s] for s in STRATEGIES))
        d += datetime.timedelta(days=1)

    # One-time cost: initial allocation setup + annual drift correction
    days = (_BACKTEST_END - _BACKTEST_START).days + 1
    years = days / 365.0
    # 10bps entry + 2bps/yr ongoing minimal rebalancing
    total_cost_frac = (_COST_BPS / 10_000.0) + (TRANSACTION_COST_ANNUAL_BPS / 10_000.0 * years)
    return portfolio_curve, total_cost_frac


def _metrics(equity_curve: List[float], cost_frac: float, label: str) -> dict:
    n = len(equity_curve)
    years = n / 365.0
    final = equity_curve[-1]
    gross_return = (final - _INITIAL) / _INITIAL
    net_return = gross_return - cost_frac
    net_apy = ((1 + net_return) ** (1 / years) - 1) * 100

    # max drawdown
    peak = _INITIAL
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd

    calmar = net_apy / (max_dd * 100) if max_dd > 0 else float("inf")
    gross_apy = ((1 + gross_return) ** (1 / years) - 1) * 100

    return {
        "label": label,
        "gross_apy_pct": round(gross_apy, 2),
        "net_apy_pct": round(net_apy, 2),
        "max_dd_pct": round(max_dd * 100, 2),
        "calmar": round(calmar, 3),
        "cost_bps": round(cost_frac * 10_000, 1),
        "days": n,
        "years": round(years, 2),
    }


def _per_crisis_breakdown(weights: Dict[str, float]) -> Dict[str, float]:
    """Max single-day crisis loss fraction at portfolio level per window."""
    window_lengths: Dict[str, int] = {}
    for w in STRESS_WINDOWS:
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        window_lengths[str(w["key"])] = (hi - lo).days + 1

    result = {}
    for w in STRESS_WINDOWS:
        key = str(w["key"])
        # Day-0 loss fraction at portfolio level
        n = window_lengths[key]
        norm = sum(0.5 ** j for j in range(n))
        day0_frac = (0.5 ** 0) / norm if norm > 0 else 0.0

        portfolio_day0_loss = 0.0
        for s in STRATEGIES:
            total = _SPEC[s]["window_hits"].get(key, 0.0)
            if total > 0:
                portfolio_day0_loss += weights[s] * total * day0_frac

        # Total portfolio crisis loss (sum over window)
        portfolio_total_loss = sum(
            weights[s] * _SPEC[s]["window_hits"].get(key, 0.0)
            for s in STRATEGIES
        )
        result[key] = {
            "day0_loss_pct": round(portfolio_day0_loss * 100, 3),
            "total_window_loss_pct": round(portfolio_total_loss * 100, 3),
        }
    return result


def _tail_budget_analysis(weights: Dict[str, float]) -> Dict[str, dict]:
    """How much each strategy contributes to portfolio tail risk."""
    max_hit = {s: max(_SPEC[s]["window_hits"].values()) for s in STRATEGIES}
    result = {}
    for s in STRATEGIES:
        result[s] = {
            "weight_pct": round(weights[s] * 100, 2),
            "max_crisis_hit_pct": round(max_hit[s] * 100, 1),
            "tail_risk_contribution_pct": round(weights[s] * max_hit[s] * 100, 3),
        }
    return result


# ── main ──────────────────────────────────────────────────────────────────────

def run_all() -> dict:
    schemes = {
        "EW":           _weights_equal(),
        "APY":          _weights_apy(),
        "TRB-max":      _weights_trb_max(),
        "TRB-sum":      _weights_trb_sum(),
        "TRB-worst-day": _weights_trb_worst_day(),
    }

    results = {}
    crisis_breakdowns = {}
    tail_budgets = {}

    for label, weights in schemes.items():
        curve, cost = _simulate(weights)
        results[label] = _metrics(curve, cost, label)
        crisis_breakdowns[label] = _per_crisis_breakdown(weights)
        tail_budgets[label] = _tail_budget_analysis(weights)

    return {
        "metrics": results,
        "crisis_breakdowns": crisis_breakdowns,
        "tail_budgets": tail_budgets,
        "strategies": STRATEGIES,
        "spec_summary": {s: {
            "headline_apy_pct": _SPEC[s]["headline_apy_pct"],
            "max_crisis_hit_pct": round(max(_SPEC[s]["window_hits"].values()) * 100, 1),
            "sum_crisis_hit_pct": round(sum(_SPEC[s]["window_hits"].values()) * 100, 1),
        } for s in STRATEGIES},
        "meta": {
            "idea": "#42 TRB-Alloc",
            "evidence_level": "L0",
            "is_advisory": True,
            "outside_riskpolicy": True,
            "backtest_period": f"{_BACKTEST_START} .. {_BACKTEST_END}",
            "cost_bps_entry": _COST_BPS,
            "cost_bps_annual_ongoing": TRANSACTION_COST_ANNUAL_BPS,
        }
    }


def _print_results(out: dict) -> None:
    print("\n" + "="*70)
    print("IDEA #42: TRB-Alloc — Tail-Risk-Budget Allocation")
    print(f"Backtest {out['meta']['backtest_period']}  |  IS_ADVISORY=True  |  L0")
    print("="*70)

    print("\n── Strategy Spec Summary ──")
    print(f"{'Strategy':<16} {'APY%':>6} {'MaxHit%':>8} {'SumHit%':>8}")
    for s, spec in out["spec_summary"].items():
        print(f"{s:<16} {spec['headline_apy_pct']:>6.1f} {spec['max_crisis_hit_pct']:>8.1f} {spec['sum_crisis_hit_pct']:>8.1f}")

    print("\n── Portfolio Metrics (backtest, L0) ──")
    print(f"{'Scheme':<16} {'GrossAPY%':>10} {'NetAPY%':>9} {'MaxDD%':>8} {'Calmar':>8} {'CostBps':>8}")
    for label, m in out["metrics"].items():
        print(f"{label:<16} {m['gross_apy_pct']:>10.2f} {m['net_apy_pct']:>9.2f} {m['max_dd_pct']:>8.2f} {m['calmar']:>8.3f} {m['cost_bps']:>8.1f}")

    print("\n── Weights per Scheme ──")
    schemes = list(out["metrics"].keys())
    print(f"{'Strategy':<16} " + " ".join(f"{s:>12}" for s in schemes))
    for s in STRATEGIES:
        row = f"{s:<16} "
        for scheme_label in schemes:
            w_pct = out["tail_budgets"][scheme_label][s]["weight_pct"]
            row += f"{w_pct:>12.1f}"
        print(row)

    print("\n── Tail-Risk Contributions (weight × max_crisis_hit) ──")
    print("Best scheme = most equal contribution across strategies")
    print(f"{'Strategy':<16} " + " ".join(f"{s:>12}" for s in schemes))
    for s in STRATEGIES:
        row = f"{s:<16} "
        for scheme_label in schemes:
            trc = out["tail_budgets"][scheme_label][s]["tail_risk_contribution_pct"]
            row += f"{trc:>12.3f}"
        print(row)

    print("\n── Per-Crisis Breakdown: Total Window Loss % (portfolio) ──")
    crisis_keys = [str(w["key"]) for w in STRESS_WINDOWS]
    print(f"{'Crisis':<26} " + " ".join(f"{s:>12}" for s in schemes))
    for key in crisis_keys:
        row = f"{key:<26} "
        for scheme_label in schemes:
            loss = out["crisis_breakdowns"][scheme_label][key]["total_window_loss_pct"]
            row += f"{loss:>12.2f}"
        print(row)

    print("\n── Summary ──")
    best_calmar = max(out["metrics"].items(), key=lambda kv: kv[1]["calmar"])
    best_net_apy = max(out["metrics"].items(), key=lambda kv: kv[1]["net_apy_pct"])
    best_min_dd = min(out["metrics"].items(), key=lambda kv: kv[1]["max_dd_pct"])

    print(f"Best Calmar:  {best_calmar[0]} → {best_calmar[1]['calmar']:.3f}")
    print(f"Best NetAPY:  {best_net_apy[0]} → {best_net_apy[1]['net_apy_pct']:.2f}%")
    print(f"Min MaxDD:    {best_min_dd[0]} → {best_min_dd[1]['max_dd_pct']:.2f}%")

    rwa_floor = 3.4
    print(f"\nAll schemes vs RWA floor {rwa_floor}%:")
    for label, m in out["metrics"].items():
        delta = m["net_apy_pct"] - rwa_floor
        sign = "+" if delta >= 0 else ""
        print(f"  {label:<16} netAPY={m['net_apy_pct']:.2f}%  vs floor: {sign}{delta:.2f}%  Calmar={m['calmar']:.3f}")

    print("\n[IS_ADVISORY=True | OUTSIDE_RISKPOLICY | L0 backtest | LLM_FORBIDDEN]")
    print("="*70)


if __name__ == "__main__":
    out = run_all()
    _print_results(out)
    # write JSON output for registry
    out_path = ROOT / "scripts" / "edge_42_trb_alloc_results.json"
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nResults written to {out_path}")
