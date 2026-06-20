#!/usr/bin/env python3
"""
SPA Real-Data Backtest Runner
=============================

Runs the SPA strategy allocations against **real 365-day historical APY** pulled
from DeFiLlama (data/historical_apy/*.json), as opposed to the seeded synthetic
series used by scripts/run_backtest.py.

Each strategy is expressed as a static allocation across the five whitelisted
USDC venues. The daily portfolio return is the capital-weighted blend of each
venue's accrued daily yield:

    daily_return = Σ weight_i * (apy_i / 100) / 365

Capital compounds daily on a $100,000 starting balance for the full 365-day
window. Every strategy is scored with the SAME metric set (Sharpe / Sortino /
max-drawdown / CAGR / Calmar) so the leaderboard is apples-to-apples, and each
is compared against a "lazy HODL" benchmark of staying 100% in Aave forever.

NOTE ON RISK CAPS: the allocations below are **illustrative backtest weights**,
not live-tradeable targets. The aggressive sleeves deliberately overweight T2
(Morpho Blue) beyond the live RiskPolicy 20% T2 cap to show the upper bound of
chasing yield on this dataset. Live allocation is governed by
spa_core/allocator + RiskPolicy and is unaffected by this advisory script.

Pure stdlib, offline (reads local JSON only), atomic write, exit 0 on success.

Usage:
    python3 scripts/run_backtest_real.py
    python3 scripts/run_backtest_real.py --data-dir data/historical_apy
                                         --out data/backtest_results_real.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ── Make spa_core importable regardless of cwd ────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.backtesting.metrics import (  # reuse the canonical implementations
    sharpe_ratio,
    max_drawdown,
    total_return_pct,
    annualised_return_pct,
)

INITIAL_CAPITAL = 100_000.0
RISK_FREE = 0.04  # 4% annual, matches metrics.py default

# Protocol keys (== filenames in data/historical_apy without .json) and tier.
PROTOCOLS = {
    "aave_v3_usdc":     {"label": "Aave V3",      "tier": "T1"},
    "compound_v3_usdc": {"label": "Compound V3",  "tier": "T1"},
    "yearn_v3_usdc":    {"label": "Yearn V3",     "tier": "T2"},
    "sky_susds":        {"label": "Sky / sUSDS",  "tier": "T1"},
    "morpho_blue_usdc": {"label": "Morpho Blue",  "tier": "T2"},
}

# ── Strategy allocations (weights sum to 1.0 across the 5 venues) ──────────────
# Each maps the protocol key -> portfolio weight. Missing keys == 0% weight.
STRATEGIES = {
    "S0_baseline": {
        "name": "Baseline (Equal Weight)",
        "risk_tier": "T1/T2",
        "weights": {
            "aave_v3_usdc": 0.20, "compound_v3_usdc": 0.20,
            "yearn_v3_usdc": 0.20, "sky_susds": 0.20, "morpho_blue_usdc": 0.20,
        },
    },
    "S0_conservative": {
        "name": "S0 Conservative (low-vol T1)",
        "risk_tier": "T1",
        "weights": {
            "sky_susds": 0.50, "aave_v3_usdc": 0.30, "compound_v3_usdc": 0.20,
        },
    },
    "S1_conservative_lending": {
        "name": "Conservative Lending (T1 core)",
        "risk_tier": "T1",
        "weights": {
            "aave_v3_usdc": 0.40, "compound_v3_usdc": 0.40, "sky_susds": 0.20,
        },
    },
    "S2_balanced_yield": {
        "name": "Balanced Yield (T1+T2 blend)",
        "risk_tier": "T1/T2",
        "weights": {
            "morpho_blue_usdc": 0.30, "yearn_v3_usdc": 0.25,
            "compound_v3_usdc": 0.20, "aave_v3_usdc": 0.15, "sky_susds": 0.10,
        },
    },
    "S7_aggressive_yield": {
        "name": "Aggressive Yield (T2-heavy, illustrative)",
        "risk_tier": "T2",
        "weights": {
            "morpho_blue_usdc": 0.50, "yearn_v3_usdc": 0.25,
            "compound_v3_usdc": 0.15, "aave_v3_usdc": 0.10,
        },
    },
    "S12_base_layer": {
        "name": "S12 Base Layer (T1 anchor)",
        "risk_tier": "T1",
        "weights": {
            "aave_v3_usdc": 0.35, "compound_v3_usdc": 0.35, "sky_susds": 0.30,
        },
    },
}

# A representative "current live portfolio": dominant T1 anchor + yield sleeve,
# mirroring the structural ~T1-heavy mix the live allocator settles into.
CURRENT_PORTFOLIO = {
    "aave_v3_usdc": 0.40, "compound_v3_usdc": 0.25,
    "morpho_blue_usdc": 0.20, "yearn_v3_usdc": 0.10, "sky_susds": 0.05,
}

LAZY_BENCHMARK = {"aave_v3_usdc": 1.00}  # 100% Aave forever


# ─── Data loading & alignment ─────────────────────────────────────────────────

def load_series(data_dir: Path) -> dict[str, dict[str, float]]:
    """Load each protocol into {date_str: apy_pct}."""
    series: dict[str, dict[str, float]] = {}
    for key in PROTOCOLS:
        path = data_dir / f"{key}.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        series[key] = {r["date"]: float(r["apy"]) for r in rows}
    return series


def aligned_dates(series: dict[str, dict[str, float]]) -> list[str]:
    """Sorted list of dates present in EVERY protocol series (intersection)."""
    common: set[str] | None = None
    for per_date in series.values():
        s = set(per_date.keys())
        common = s if common is None else (common & s)
    return sorted(common or [])


# ─── Equity curve from an allocation ──────────────────────────────────────────

def equity_curve(weights: dict[str, float],
                 series: dict[str, dict[str, float]],
                 dates: list[str]) -> tuple[list[float], list[float]]:
    """
    Build the compounding equity curve and the list of daily returns for a static
    allocation. Rebalanced implicitly to target weights each day.

    Returns (curve, daily_returns) where curve has len(dates)+1 points.
    """
    capital = INITIAL_CAPITAL
    curve = [capital]
    daily_returns: list[float] = []
    for d in dates:
        day_ret = 0.0
        for key, w in weights.items():
            if w <= 0:
                continue
            apy_pct = series[key].get(d)
            if apy_pct is None:
                continue
            day_ret += w * (apy_pct / 100.0) / 365.0
        capital *= (1.0 + day_ret)
        curve.append(capital)
        daily_returns.append(day_ret)
    return curve, daily_returns


# ─── Metrics ──────────────────────────────────────────────────────────────────

def sortino_ratio(daily_returns: list[float], risk_free: float = RISK_FREE) -> float | None:
    """
    Annualised Sortino ratio (downside-deviation denominator).

    Returns None when there is no downside (downside deviation == 0) — common for
    pure stablecoin yield accrual where every daily return is positive.
    """
    if len(daily_returns) < 2:
        return 0.0
    daily_rf = risk_free / 365.0
    excess = [r - daily_rf for r in daily_returns]
    downside = [min(0.0, e) for e in excess]
    dd = math.sqrt(sum(x * x for x in downside) / len(downside))
    if dd == 0.0:
        return None  # no downside relative to risk-free → undefined (infinite)
    mean_excess = statistics.mean(excess)
    return round((mean_excess / dd) * math.sqrt(365), 4)


def compute_metrics(curve: list[float], daily_returns: list[float],
                    days: int) -> dict:
    initial, final = curve[0], curve[-1]
    total_frac = (final - initial) / initial if initial > 0 else 0.0
    mdd = max_drawdown(curve)
    cagr = annualised_return_pct(total_frac, days)
    # Calmar = CAGR / |maxDD|. Undefined when there is no drawdown.
    calmar = round(cagr / (mdd * 100), 4) if mdd > 0 else None
    return {
        "final_capital_usd": round(final, 2),
        "total_interest_usd": round(final - initial, 2),
        "total_return_pct": total_return_pct(initial, final),
        "cagr_pct": cagr,
        "annualised_return_pct": cagr,
        "sharpe_ratio": sharpe_ratio(daily_returns, risk_free_rate=RISK_FREE),
        "sortino_ratio": sortino_ratio(daily_returns),
        "max_drawdown_pct": round(mdd * 100, 4),
        "calmar_ratio": calmar,
        "backtest_days": days,
    }


# ─── Key analysis ─────────────────────────────────────────────────────────────

def rolling_window_analysis(weights: dict[str, float],
                            series: dict[str, dict[str, float]],
                            dates: list[str], window: int = 182) -> dict:
    """Find the best/worst contiguous `window`-day windows by total return."""
    if len(dates) <= window:
        return {"note": f"insufficient data for {window}-day windows"}
    best = None
    worst = None
    for start in range(0, len(dates) - window + 1):
        win_dates = dates[start:start + window]
        curve, _ = equity_curve(weights, series, win_dates)
        ret = (curve[-1] - curve[0]) / curve[0]
        rec = {
            "start_date": win_dates[0],
            "end_date": win_dates[-1],
            "window_days": window,
            "total_return_pct": round(ret * 100, 4),
            "annualised_return_pct": annualised_return_pct(ret, window),
        }
        if best is None or ret > best["_r"]:
            best = {**rec, "_r": ret}
        if worst is None or ret < worst["_r"]:
            worst = {**rec, "_r": ret}
    best.pop("_r", None)
    worst.pop("_r", None)
    return {"best": best, "worst": worst}


def protocol_volatility(series: dict[str, dict[str, float]],
                        dates: list[str]) -> dict:
    """Annualised volatility of each protocol's daily yield-return series + APY stats."""
    out = {}
    for key, meta in PROTOCOLS.items():
        apys = [series[key][d] for d in dates if d in series[key]]
        daily_rets = [a / 100.0 / 365.0 for a in apys]
        vol = statistics.stdev(daily_rets) * math.sqrt(365) if len(daily_rets) > 1 else 0.0
        out[key] = {
            "label": meta["label"],
            "tier": meta["tier"],
            "mean_apy_pct": round(statistics.mean(apys), 4) if apys else 0.0,
            "min_apy_pct": round(min(apys), 4) if apys else 0.0,
            "max_apy_pct": round(max(apys), 4) if apys else 0.0,
            "apy_stdev_pct": round(statistics.stdev(apys), 4) if len(apys) > 1 else 0.0,
            "annualised_return_vol_pct": round(vol * 100, 6),
        }
    return out


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
    ap = argparse.ArgumentParser(description="SPA real-data backtest runner")
    ap.add_argument("--data-dir", default=str(_REPO_ROOT / "data" / "historical_apy"))
    ap.add_argument("--out", default=str(_REPO_ROOT / "data" / "backtest_results_real.json"))
    ap.add_argument("--window", type=int, default=182, help="rolling-window size in days")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    series = load_series(data_dir)
    dates = aligned_dates(series)
    if len(dates) < 2:
        print("ERROR: insufficient aligned dates across protocols", file=sys.stderr)
        return 1
    days = len(dates)

    # ── Per-strategy backtest ─────────────────────────────────────────────────
    results: dict[str, dict] = {}
    for sid, cfg in STRATEGIES.items():
        curve, rets = equity_curve(cfg["weights"], series, dates)
        m = compute_metrics(curve, rets, days)
        m["strategy_name"] = cfg["name"]
        m["risk_tier"] = cfg["risk_tier"]
        m["weights"] = cfg["weights"]
        results[sid] = m

    # ── Lazy HODL benchmark (100% Aave) ───────────────────────────────────────
    bench_curve, bench_rets = equity_curve(LAZY_BENCHMARK, series, dates)
    benchmark = compute_metrics(bench_curve, bench_rets, days)
    benchmark["strategy_name"] = "Lazy HODL (100% Aave V3)"
    benchmark["risk_tier"] = "T1"
    benchmark["weights"] = LAZY_BENCHMARK

    # ── Current live portfolio over the trailing 12 months ────────────────────
    cur_curve, cur_rets = equity_curve(CURRENT_PORTFOLIO, series, dates)
    current = compute_metrics(cur_curve, cur_rets, days)
    current["strategy_name"] = "Current Live Portfolio (T1-anchored)"
    current["weights"] = CURRENT_PORTFOLIO
    current["period"] = {"from": dates[0], "to": dates[-1], "days": days}

    # ── Benchmark deltas (strategy vs lazy Aave) ──────────────────────────────
    bench_ret = benchmark["total_return_pct"]
    comparison = []
    for sid, r in results.items():
        comparison.append({
            "strategy": sid,
            "name": r["strategy_name"],
            "total_return_pct": r["total_return_pct"],
            "vs_lazy_aave_pct_pts": round(r["total_return_pct"] - bench_ret, 4),
            "excess_usd": round(r["final_capital_usd"] - benchmark["final_capital_usd"], 2),
            "beats_benchmark": r["total_return_pct"] > bench_ret,
        })
    comparison.sort(key=lambda x: x["total_return_pct"], reverse=True)

    # ── Leaderboard (incl. benchmark) ─────────────────────────────────────────
    leaderboard = sorted(
        [
            {
                "strategy": sid,
                "name": r["strategy_name"],
                "risk_tier": r["risk_tier"],
                "annualised_return_pct": r["annualised_return_pct"],
                "sharpe_ratio": r["sharpe_ratio"],
                "max_drawdown_pct": r["max_drawdown_pct"],
                "total_return_pct": r["total_return_pct"],
            }
            for sid, r in {**results, "BENCHMARK_lazy_aave": benchmark}.items()
        ],
        key=lambda x: x["annualised_return_pct"],
        reverse=True,
    )

    # ── Key analysis (windows on the balanced strategy + per-protocol vol) ─────
    key_analysis = {
        "rolling_window_days": args.window,
        "balanced_strategy_windows": rolling_window_analysis(
            STRATEGIES["S2_balanced_yield"]["weights"], series, dates, args.window),
        "lazy_aave_windows": rolling_window_analysis(
            LAZY_BENCHMARK, series, dates, args.window),
        "protocol_volatility": protocol_volatility(series, dates),
        "current_portfolio_trailing_12mo": current,
    }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": "defillama_historical_real",
        "data_dir": str(data_dir),
        "period": {"from": dates[0], "to": dates[-1], "days": days},
        "initial_capital_usd": INITIAL_CAPITAL,
        "risk_free_rate": RISK_FREE,
        "note": (
            "Allocation-weighted backtest on REAL 365-day DeFiLlama APY history. "
            "Stablecoin yield accrual is monotonic (no token price risk), so "
            "max-drawdown is ~0% and Sharpe/Calmar are structurally high or "
            "undefined — a property of the asset class, not an error. Sortino/"
            "Calmar are null when there is no downside/drawdown. Allocations are "
            "illustrative backtest weights; live weights are governed by "
            "spa_core/allocator + RiskPolicy (T2<=20%)."
        ),
        "strategies": results,
        "benchmark": benchmark,
        "benchmark_comparison": comparison,
        "leaderboard": leaderboard,
        "key_analysis": key_analysis,
    }

    out_path = Path(args.out)
    atomic_write_json(out_path, payload)

    # ── Console summary ───────────────────────────────────────────────────────
    print(f"\nSPA REAL backtest — {days}d ({dates[0]} → {dates[-1]}), "
          f"source=defillama_historical_real")
    print(f"{'strategy':<28}{'tier':<8}{'annRet%':>9}{'sharpe':>9}{'maxDD%':>9}{'totRet%':>9}")
    print("-" * 72)
    for row in leaderboard:
        print(f"{row['strategy']:<28}{row['risk_tier']:<8}"
              f"{row['annualised_return_pct']:>9.2f}{row['sharpe_ratio']:>9.2f}"
              f"{row['max_drawdown_pct']:>9.2f}{row['total_return_pct']:>9.2f}")

    print(f"\nLazy Aave HODL: {benchmark['total_return_pct']:.4f}% total "
          f"(${benchmark['final_capital_usd']:,.2f})")
    print("\nvs lazy Aave (pct points):")
    for c in comparison:
        flag = "✓" if c["beats_benchmark"] else "✗"
        print(f"  {flag} {c['strategy']:<26}{c['vs_lazy_aave_pct_pts']:>+8.4f} pp "
              f"(${c['excess_usd']:>+12,.2f})")

    bw = key_analysis["balanced_strategy_windows"]
    if "best" in bw:
        print(f"\nBest {args.window}d window (balanced):  "
              f"{bw['best']['start_date']} → {bw['best']['end_date']}  "
              f"{bw['best']['annualised_return_pct']:.2f}% annualised")
        print(f"Worst {args.window}d window (balanced): "
              f"{bw['worst']['start_date']} → {bw['worst']['end_date']}  "
              f"{bw['worst']['annualised_return_pct']:.2f}% annualised")

    print(f"\nCurrent portfolio trailing 12mo: "
          f"+${current['total_interest_usd']:,.2f} "
          f"({current['total_return_pct']:.4f}%, CAGR {current['cagr_pct']:.2f}%)")

    print("\nProtocol annualised return-volatility:")
    for key, v in key_analysis["protocol_volatility"].items():
        print(f"  {v['label']:<14}{v['tier']:<5} mean APY {v['mean_apy_pct']:>6.2f}%  "
              f"range [{v['min_apy_pct']:.2f}, {v['max_apy_pct']:.2f}]  "
              f"retVol {v['annualised_return_vol_pct']:.4f}%")

    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
