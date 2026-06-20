#!/usr/bin/env python3
"""
SPA Backtest Runner — end-to-end driver
=======================================

First real end-to-end run of the SPA backtest infrastructure (engine/metrics/
data_loader built but never executed). Runs the whitelisted strategies on
historical APY data and writes a single comparable results file.

Strategies have three different (legacy) interfaces; this harness adapts each:
  * native  ``strategy.backtest(history, initial_capital) -> dict``   (S1, S2, S3)
  * S0       ``BaselineStrategy.run_day(apy_map) -> avg_apy_pct``      (equal weight)
  * S7       ``S7PendleYTAggressive.simulate_day(value, day, apy_map, scenario)``

All strategies are reduced to a daily equity curve, then scored with the SAME
metrics module (spa_core.backtesting.metrics) so Sharpe / max-drawdown /
total-return / annualised-return are computed identically across strategies.

Data:
  * Lending universe (S0/S1/S2/S3): spa_core.backtesting.data_loader, which
    pulls real DeFiLlama history when available and otherwise falls back to a
    seeded, mean-reverting synthetic series (3–8% stablecoin-lending regime).
  * Pendle YT universe (S7): a seeded synthetic YT/PT/Morpho/Compound series
    generated here (YT is speculative, ~14% mean with high variance).

Pure stdlib, offline-safe, atomic write, exit 0 on success.

Usage:
    python3 scripts/run_backtest.py [--days 90] [--seed 42]
                                    [--source synthetic|defillama]
                                    [--out data/backtest_results.json]
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ── Make spa_core importable regardless of cwd ────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.backtesting.data_loader import (
    generate_synthetic_history,
    load_from_defillama_api,
)
from spa_core.backtesting.metrics import (
    sharpe_ratio,
    max_drawdown,
    total_return_pct,
    annualised_return_pct,
)

log = logging.getLogger("spa.run_backtest")

INITIAL_CAPITAL = 100_000.0


# ─── Shared metrics helper ────────────────────────────────────────────────────

def metrics_from_curve(curve_values: list[float], days: int) -> dict:
    """Compute the standard metric set from a daily equity curve (list of USD values)."""
    if len(curve_values) < 2:
        return {
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "total_return_pct": 0.0,
            "annualised_return_pct": 0.0,
            "final_capital_usd": round(curve_values[0] if curve_values else INITIAL_CAPITAL, 2),
            "total_interest_usd": 0.0,
            "backtest_days": days,
        }

    daily_returns = [
        (curve_values[i] - curve_values[i - 1]) / curve_values[i - 1]
        if curve_values[i - 1] > 0 else 0.0
        for i in range(1, len(curve_values))
    ]
    initial = curve_values[0]
    final = curve_values[-1]
    total_frac = (final - initial) / initial if initial > 0 else 0.0

    return {
        "sharpe_ratio": sharpe_ratio(daily_returns, risk_free_rate=0.04),
        "max_drawdown_pct": round(max_drawdown(curve_values) * 100, 4),
        "total_return_pct": total_return_pct(initial, final),
        "annualised_return_pct": annualised_return_pct(total_frac, days),
        "final_capital_usd": round(final, 2),
        "total_interest_usd": round(final - initial, 2),
        "backtest_days": days,
    }


# ─── Per-day apy maps from a standard history ─────────────────────────────────

def history_by_day(history: list[dict]) -> list[tuple[str, dict]]:
    """Group a standard history into [(date_str, {protocol_key: apy}), ...] sorted by date."""
    days: dict[str, dict] = {}
    for row in history:
        ts = row["timestamp"][:10]
        days.setdefault(ts, {})[row["protocol_key"]] = float(row["apy"])
    return sorted(days.items(), key=lambda kv: kv[0])


# ─── Strategy drivers ─────────────────────────────────────────────────────────

def run_native(strategy, history: list[dict], initial_capital: float) -> dict:
    """Run a strategy that implements the conformant backtest() interface."""
    raw = strategy.backtest(history, initial_capital=initial_capital)
    m = dict(raw.get("metrics", {}))
    # Normalise to the standard key set (native metrics already match).
    return {
        "sharpe_ratio": m.get("sharpe_ratio", 0.0),
        "max_drawdown_pct": m.get("max_drawdown_pct", 0.0),
        "total_return_pct": m.get("total_return_pct", 0.0),
        "annualised_return_pct": m.get("annualised_return_pct", 0.0),
        "final_capital_usd": m.get("final_capital_usd", initial_capital),
        "total_interest_usd": m.get("total_interest_usd", 0.0),
        "backtest_days": m.get("backtest_days", 0),
        "total_trades": m.get("total_trades", 0),
        "win_rate": m.get("win_rate", 0.0),
        "_driver": "native_backtest",
    }


def run_baseline_s0(strategy, history: list[dict], initial_capital: float) -> dict:
    """
    Drive S0 BaselineStrategy day-by-day via run_day(apy_map).

    Each day the strategy reports its equal-weighted portfolio APY; we accrue
    one day of interest (apy/100/365) onto the running capital.
    """
    capital = initial_capital
    curve = [capital]
    per_day = history_by_day(history)
    for _date, apy_map in per_day:
        apy_pct = float(strategy.run_day(apy_map))
        capital += capital * (apy_pct / 100.0) / 365.0
        curve.append(capital)
    m = metrics_from_curve(curve, len(per_day))
    m["_driver"] = "run_day"
    m["total_trades"] = len(per_day)  # daily rebalance
    m["win_rate"] = 1.0 if m["total_return_pct"] >= 0 else 0.0
    return m


def run_s7(strategy, yt_history: list[dict], initial_capital: float,
           scenario: str = "base") -> dict:
    """
    Drive S7 day-by-day via simulate_day(value, day_num, apy_map, scenario).

    yt_history is the Pendle YT universe (pendle_yt/pendle_pt/morpho_steakhouse/
    compound_v3). simulate_day returns portfolio_value_after; we chain it.
    """
    capital = initial_capital
    curve = [capital]
    per_day = history_by_day(yt_history)
    for i, (_date, apy_map) in enumerate(per_day, start=1):
        res = strategy.simulate_day(capital, i, apy_map=apy_map, scenario=scenario)
        capital = res["portfolio_value_after"]
        curve.append(capital)
    m = metrics_from_curve(curve, len(per_day))
    m["_driver"] = f"simulate_day[{scenario}]"
    m["total_trades"] = len(per_day)
    m["win_rate"] = 1.0 if m["total_return_pct"] >= 0 else 0.0
    return m


# ─── Pendle YT synthetic universe (for S7) ────────────────────────────────────

def _ou_normal(rng: random.Random) -> float:
    """Box-Muller standard normal from a seeded RNG."""
    while True:
        u1 = rng.random()
        u2 = rng.random()
        if u1 > 0:
            return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def generate_yt_history(days: int = 90, seed: int = 42,
                        end_date: date | None = None) -> list[dict]:
    """
    Seeded synthetic history for the S7 Pendle YT universe.

    Mean-reverting (OU) APY series per protocol. YT is the speculative leg —
    high mean and high volatility (8–40% band); PT/Morpho/Compound are calm.
    Returns the standard history format so it flows through history_by_day().
    """
    rng = random.Random(seed)
    if end_date is None:
        end_date = date.today()
    start = end_date - timedelta(days=days - 1)

    # (key, tier, mean_apy, sigma, floor, ceil)
    universe = [
        ("pendle_yt",         "T3", 14.0, 3.0, 4.0, 40.0),
        ("pendle_pt",         "T3",  8.5, 0.35, 6.0, 12.0),
        ("morpho_steakhouse", "T1",  6.5, 0.45, 4.0, 10.0),
        ("compound_v3",       "T1",  4.8, 0.30, 2.5, 7.0),
    ]
    theta = 0.15
    state = {u[0]: u[2] for u in universe}
    meta = {u[0]: u for u in universe}

    records: list[dict] = []
    cur = start
    for _ in range(days):
        ds = cur.isoformat()
        for key, (_k, tier, mu, sigma, lo, hi) in meta.items():
            apy = state[key]
            apy = apy + theta * (mu - apy) + sigma * _ou_normal(rng)
            apy = max(lo, min(hi, apy))
            state[key] = apy
            records.append({
                "timestamp": ds,
                "protocol_key": key,
                "apy": round(apy, 4),
                "tvl_usd": 50_000_000.0,
                "tier": tier,
            })
        cur += timedelta(days=1)
    return sorted(records, key=lambda r: (r["timestamp"], r["protocol_key"]))


# ─── Atomic write ─────────────────────────────────────────────────────────────

def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="SPA end-to-end backtest runner")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--source", choices=["synthetic", "defillama"], default="synthetic")
    ap.add_argument("--out", default=str(_REPO_ROOT / "data" / "backtest_results.json"))
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )
    # Silence the noisy RiskPolicy stdout-style logger during native backtests.
    if not args.verbose:
        logging.getLogger().setLevel(logging.ERROR)

    # ── Build the lending-universe history (S0/S1/S2/S3) ──────────────────────
    if args.source == "defillama":
        lending_history = load_from_defillama_api(days=args.days)
        data_source = getattr(load_from_defillama_api, "last_source", "synthetic")
    else:
        lending_history = generate_synthetic_history(days=args.days, seed=args.seed)
        data_source = "synthetic"

    yt_history = generate_yt_history(days=args.days, seed=args.seed)

    # ── Import strategies lazily (registry side-effects are heavy) ─────────────
    from spa_core.strategies.baseline import BaselineStrategy
    from spa_core.strategies.s1_conservative_lending import ConservativeLendingStrategy
    from spa_core.strategies.s2_lp_stable import LPStableStrategy
    from spa_core.strategies.s3_yield_loop import YieldLoopStrategy
    from spa_core.strategies.s7_pendle_yt_aggressive import S7PendleYTAggressive

    results: dict[str, dict] = {}

    # S0 — Baseline equal weight (run_day driver)
    try:
        results["S0_baseline"] = run_baseline_s0(
            BaselineStrategy(), lending_history, INITIAL_CAPITAL)
        results["S0_baseline"]["strategy_name"] = "Baseline (Equal Weight)"
        results["S0_baseline"]["risk_tier"] = "T1"
        results["S0_baseline"]["universe"] = "lending"
    except Exception as exc:  # pragma: no cover
        results["S0_baseline"] = {"error": repr(exc)}

    # S1 — Conservative lending (native backtest)
    try:
        results["S1_conservative_lending"] = run_native(
            ConservativeLendingStrategy(), lending_history, INITIAL_CAPITAL)
        results["S1_conservative_lending"]["strategy_name"] = "Conservative Lending"
        results["S1_conservative_lending"]["risk_tier"] = "T1"
        results["S1_conservative_lending"]["universe"] = "lending"
    except Exception as exc:
        results["S1_conservative_lending"] = {"error": repr(exc)}

    # S2 — LP stablecoin pairs (native backtest)
    try:
        results["S2_lp_stable"] = run_native(
            LPStableStrategy(), lending_history, INITIAL_CAPITAL)
        results["S2_lp_stable"]["strategy_name"] = "LP Stablecoin Pairs"
        results["S2_lp_stable"]["risk_tier"] = "T2"
        results["S2_lp_stable"]["universe"] = "lending"
    except Exception as exc:
        results["S2_lp_stable"] = {"error": repr(exc)}

    # S3 — Yield loop (native backtest)
    try:
        results["S3_yield_loop"] = run_native(
            YieldLoopStrategy(), lending_history, INITIAL_CAPITAL)
        results["S3_yield_loop"]["strategy_name"] = "Yield Loop"
        results["S3_yield_loop"]["risk_tier"] = "T3"
        results["S3_yield_loop"]["universe"] = "lending"
    except Exception as exc:
        results["S3_yield_loop"] = {"error": repr(exc)}

    # S7 — Pendle YT+PT aggressive (simulate_day driver). Report base scenario as
    # the headline; keep bull/bear as auxiliary scenario stats for transparency.
    try:
        s7 = S7PendleYTAggressive()
        base = run_s7(s7, yt_history, INITIAL_CAPITAL, scenario="base")
        bull = run_s7(S7PendleYTAggressive(), yt_history, INITIAL_CAPITAL, scenario="bull")
        bear = run_s7(S7PendleYTAggressive(), yt_history, INITIAL_CAPITAL, scenario="bear")
        base["strategy_name"] = "Pendle YT+PT Aggressive"
        base["risk_tier"] = "T3"
        base["universe"] = "pendle_yt"
        base["scenarios"] = {
            "base": {k: base[k] for k in (
                "annualised_return_pct", "sharpe_ratio", "max_drawdown_pct")},
            "bull": {k: bull[k] for k in (
                "annualised_return_pct", "sharpe_ratio", "max_drawdown_pct")},
            "bear": {k: bear[k] for k in (
                "annualised_return_pct", "sharpe_ratio", "max_drawdown_pct")},
        }
        results["S7_pendle_yt_aggressive"] = base
    except Exception as exc:
        results["S7_pendle_yt_aggressive"] = {"error": repr(exc)}

    # ── Leaderboard by annualised return (skip errored) ───────────────────────
    leaderboard = sorted(
        [
            {
                "strategy": sid,
                "name": r.get("strategy_name", sid),
                "risk_tier": r.get("risk_tier", "?"),
                "annualised_return_pct": r.get("annualised_return_pct", 0.0),
                "sharpe_ratio": r.get("sharpe_ratio", 0.0),
                "max_drawdown_pct": r.get("max_drawdown_pct", 0.0),
                "total_return_pct": r.get("total_return_pct", 0.0),
            }
            for sid, r in results.items() if "error" not in r
        ],
        key=lambda x: x["annualised_return_pct"],
        reverse=True,
    )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": data_source,
        "period_days": args.days,
        "seed": args.seed,
        "initial_capital_usd": INITIAL_CAPITAL,
        "note": (
            "Stablecoin yield-accrual strategies (S0–S3) have near-zero price "
            "volatility, so max drawdown ~0% and Sharpe is structurally high — "
            "this is a property of monotonic yield accrual, not an error. S7's "
            "speculative Pendle-YT leg carries real variance (see scenarios)."
        ),
        "strategies": results,
        "leaderboard": leaderboard,
    }

    out_path = Path(args.out)
    atomic_write_json(out_path, payload)

    # ── Console summary ───────────────────────────────────────────────────────
    print(f"\nSPA backtest — {args.days}d, source={data_source}, seed={args.seed}")
    print(f"{'strategy':<28}{'tier':<6}{'annRet%':>9}{'sharpe':>9}{'maxDD%':>9}{'totRet%':>9}")
    print("-" * 70)
    for row in leaderboard:
        print(f"{row['strategy']:<28}{row['risk_tier']:<6}"
              f"{row['annualised_return_pct']:>9.2f}{row['sharpe_ratio']:>9.2f}"
              f"{row['max_drawdown_pct']:>9.2f}{row['total_return_pct']:>9.2f}")
    errored = [s for s, r in results.items() if "error" in r]
    if errored:
        print(f"\nERRORED: {errored}")
        for s in errored:
            print(f"  {s}: {results[s]['error']}")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
