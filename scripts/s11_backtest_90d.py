#!/usr/bin/env python3
"""S11 90-day Monte Carlo backtest simulation using historical APY ranges.

Model: two-component daily return
  1. Yield drift: weight * clamp(gauss(apy_mean, apy_std), min, max) / 365 / 100
  2. Market risk:  weight * gauss(0, market_vol_daily)
     Captures DeFi price volatility / liquidity risk / smart-contract risk.
     T3-SPEC (Pendle YT) carries the highest market vol.

Stdlib only. No numpy / pandas.
"""
import json
import random
import os
import tempfile
import math
from spa_core.utils import clock

# ---------------------------------------------------------------------------
# S11 allocation config
# market_vol_daily: annualised-equivalent daily volatility of mark-to-market
#   moves (not the APY uncertainty). T3-SPEC ≈ 2% / day ≈ 32% annual vol.
# ---------------------------------------------------------------------------
ALLOCATION = {
    "pendle_yt": {
        "weight": 0.45, "apy_mean": 28.4, "apy_std": 8.0,
        "min": 15.0, "max": 45.0,
        "market_vol_daily": 0.0190,   # T3-SPEC: ~30% annual vol / sqrt(252)
    },
    "morpho_steakhouse": {
        "weight": 0.30, "apy_mean": 6.5, "apy_std": 1.5,
        "min": 4.0, "max": 10.0,
        "market_vol_daily": 0.0030,   # T1 stablecoin lending: ~5% annual vol
    },
    "euler_v2": {
        "weight": 0.15, "apy_mean": 2.78, "apy_std": 0.8,
        "min": 1.5, "max": 5.0,
        "market_vol_daily": 0.0050,   # T2: ~8% annual vol
    },
    "maple": {
        "weight": 0.10, "apy_mean": 4.74, "apy_std": 1.0,
        "min": 3.0, "max": 7.0,
        "market_vol_daily": 0.0040,   # T2: ~6% annual vol
    },
}

CAPITAL      = 100_000.0
DAYS         = 90
N_SIMULATIONS = 1000
RANDOM_SEED  = 42


def _percentile(values: list, p: float) -> float:
    """Compute p-th percentile of a list (linear interpolation)."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p / 100.0
    lo = int(k)
    hi = lo + 1
    if hi >= len(s):
        return s[-1]
    return s[lo] * (1.0 - (k - lo)) + s[hi] * (k - lo)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _run_single_simulation(rng: random.Random) -> dict:
    """Simulate one 90-day equity path; return per-simulation metrics."""
    equity      = CAPITAL
    peak        = CAPITAL
    max_dd      = 0.0
    daily_rets  = []

    for _ in range(DAYS):
        day_ret = 0.0
        for cfg in ALLOCATION.values():
            # --- yield drift component ---
            annual_apy = rng.gauss(cfg["apy_mean"], cfg["apy_std"])
            annual_apy = _clamp(annual_apy, cfg["min"], cfg["max"])
            drift = cfg["weight"] * annual_apy / 365.0 / 100.0

            # --- market risk / mark-to-market component ---
            shock = cfg["weight"] * rng.gauss(0.0, cfg["market_vol_daily"])

            day_ret += drift + shock

        daily_rets.append(day_ret)
        equity *= 1.0 + day_ret

        if equity > peak:
            peak = equity
        dd = (equity - peak) / peak
        if dd < max_dd:
            max_dd = dd

    # Annualised APY from equity curve (geometric)
    total_return = (equity - CAPITAL) / CAPITAL
    ann_apy = ((1.0 + total_return) ** (365.0 / DAYS) - 1.0) * 100.0

    # Sharpe ratio (daily mean / daily std × √365, risk-free = 0)
    n = len(daily_rets)
    mean_r = sum(daily_rets) / n
    var_r  = sum((r - mean_r) ** 2 for r in daily_rets) / (n - 1) if n > 1 else 1e-18
    std_r  = math.sqrt(var_r) if var_r > 0 else 1e-9
    sharpe = (mean_r / std_r) * math.sqrt(365.0)

    return {
        "final_equity":    equity,
        "annualised_apy":  ann_apy,
        "sharpe":          sharpe,
        "max_drawdown_pct": max_dd * 100.0,   # stored negative (e.g. -5.0 = -5%)
    }


def run_backtest(n_simulations: int = N_SIMULATIONS,
                 seed: int = RANDOM_SEED) -> dict:
    """Run Monte Carlo backtest; return aggregated statistics dict."""
    rng = random.Random(seed)

    apys      = []
    sharpes   = []
    drawdowns = []

    for _ in range(n_simulations):
        sim = _run_single_simulation(rng)
        apys.append(sim["annualised_apy"])
        sharpes.append(sim["sharpe"])
        drawdowns.append(sim["max_drawdown_pct"])

    # ---- APY percentiles ----
    p5_apy   = _percentile(apys, 5)
    p25_apy  = _percentile(apys, 25)
    p50_apy  = _percentile(apys, 50)
    p75_apy  = _percentile(apys, 75)
    p95_apy  = _percentile(apys, 95)
    mean_apy = sum(apys) / n_simulations

    # ---- Sharpe percentiles ----
    p5_sh   = _percentile(sharpes, 5)
    p50_sh  = _percentile(sharpes, 50)
    p95_sh  = _percentile(sharpes, 95)
    mean_sh = sum(sharpes) / n_simulations

    # ---- Drawdown percentiles ----
    # Stored as negative magnitudes.  We compute percentiles of abs magnitude so
    # p5 = mildest (only 5% of sims this mild), p95 = most severe (5% worse).
    abs_dd = [abs(d) for d in drawdowns]
    p5_dd  = -_percentile(abs_dd, 5)    # e.g. -0.8% (mild end)
    p50_dd = -_percentile(abs_dd, 50)
    p95_dd = -_percentile(abs_dd, 95)   # e.g. -7.2% (severe end)

    # ---- Probabilities ----
    p_apy_10  = sum(1 for a in apys if a > 10.0)  / n_simulations * 100.0
    p_apy_15  = sum(1 for a in apys if a > 15.0)  / n_simulations * 100.0
    p_sh_ge_1 = sum(1 for s in sharpes if s >= 1.0) / n_simulations * 100.0

    return {
        "meta": {
            "strategy":        "S11 Hybrid Yield Maximizer",
            "version":         "v1.0",
            "simulation_date": clock.utcnow().isoformat() + "Z",
            "n_simulations":   n_simulations,
            "days":            DAYS,
            "capital":         CAPITAL,
            "seed":            seed,
            "allocation":      {k: v["weight"] for k, v in ALLOCATION.items()},
        },
        "apy_pct": {
            "p5":   round(p5_apy,  2),
            "p25":  round(p25_apy, 2),
            "p50":  round(p50_apy, 2),
            "p75":  round(p75_apy, 2),
            "p95":  round(p95_apy, 2),
            "mean": round(mean_apy, 2),
        },
        "sharpe": {
            "p5":   round(p5_sh,  3),
            "p50":  round(p50_sh, 3),
            "p95":  round(p95_sh, 3),
            "mean": round(mean_sh, 3),
        },
        "max_drawdown_pct": {
            "p5":  round(p5_dd,  2),   # least severe (near 0)
            "p50": round(p50_dd, 2),
            "p95": round(p95_dd, 2),   # most severe (most negative)
        },
        "probabilities": {
            "p_apy_gt_10_pct":   round(p_apy_10,  1),
            "p_apy_gt_15_pct":   round(p_apy_15,  1),
            "p_sharpe_ge_1_pct": round(p_sh_ge_1, 1),
        },
        "adr023_assessment": {
            "sharpe_threshold":          1.0,
            "pct_simulations_passing":   round(p_sh_ge_1, 1),
            "verdict": "CONDITIONAL" if p_sh_ge_1 >= 40.0 else "WEAK",
            "note": (
                "ADR-023 requires 30-day live paper trading + Sharpe>=1.0. "
                "Backtest only; live validation required before promotion."
            ),
        },
    }


def save_result_atomic(result: dict, data_dir: str) -> str:
    """Atomically write result to data/s11_backtest_90d.json (tmp + os.replace)."""
    os.makedirs(data_dir, exist_ok=True)
    target  = os.path.join(data_dir, "s11_backtest_90d.json")
    payload = json.dumps(result, indent=2)
    fd, tmp_path = tempfile.mkstemp(dir=data_dir, prefix=".s11_backtest_tmp_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(payload)
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return target


def print_report(r: dict) -> None:
    apy  = r["apy_pct"]
    sh   = r["sharpe"]
    dd   = r["max_drawdown_pct"]
    pr   = r["probabilities"]
    n    = r["meta"]["n_simulations"]

    print(f"\n=== S11 90-Day Backtest ({n} simulations) ===")
    print(f"Median APY:       {apy['p50']:.1f}%  (p5: {apy['p5']:.1f}%, p95: {apy['p95']:.1f}%)")
    print(f"Median Sharpe:    {sh['p50']:.2f}  (p5: {sh['p5']:.2f}, p95: {sh['p95']:.2f})")
    print(f"Max Drawdown p50: {dd['p50']:.1f}%  (p5: {dd['p5']:.1f}%, p95: {dd['p95']:.1f}%)")
    print(f"P(APY>10%):       {pr['p_apy_gt_10_pct']:.0f}%")
    print(f"P(APY>15%):       {pr['p_apy_gt_15_pct']:.0f}%")
    print(f"ADR-023 Sharpe>=1.0: {pr['p_sharpe_ge_1_pct']:.0f}% simulations pass")


def main() -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root  = os.path.dirname(script_dir)
    data_dir   = os.path.join(repo_root, "data")

    result     = run_backtest()
    saved_path = save_result_atomic(result, data_dir)
    print_report(result)
    print(f"\nSaved → {saved_path}")


if __name__ == "__main__":
    main()
