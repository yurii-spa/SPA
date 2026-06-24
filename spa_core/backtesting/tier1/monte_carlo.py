"""
spa_core/backtesting/tier1/monte_carlo.py — Tier-1 Monte-Carlo / bootstrap CIs.

PARALLEL MODEL (does not modify RiskPolicy v1.0, the cycle, or any canonical module).
Pure stdlib (math, random with FIXED seed, json), deterministic, LLM-forbidden.

A single point estimate of APY / max-drawdown is not a risk statement — it hides the
uncertainty that comes from a finite, autocorrelated yield history. This module builds a
strategy's real daily blended-yield series (same allocation-weighting as oos.py, on the
real DeFiLlama per-protocol APY cache) and answers:

    "Given the observed daily-yield path, what is the *distribution* of plausible
     annualized return and worst-case drawdown, accounting for the fact that yield is
     autocorrelated (regimes persist)?"

Method: STATIONARY BLOCK BOOTSTRAP. Plain i.i.d. bootstrap would shuffle days and destroy
the autocorrelation structure of yield (high-yield regimes cluster). The stationary block
bootstrap (Politis & Romano, 1994) resamples *blocks* of consecutive days — each block
preserves local autocorrelation, and chaining random blocks builds N synthetic paths of
the same length. For each path we compute the annualized return and the max drawdown of the
compounded equity curve; the p5 / p50 / p95 percentiles across paths are the confidence
intervals. A FIXED seed (random.Random(42)) makes every run bit-for-bit reproducible.

Output: data/tier1_monte_carlo.json (atomic) with per-validated-strategy CIs, read from
data/tier1_verdict.json (validated set) + data/mass_tournament_results.json (allocations).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
import random
import tempfile
import datetime
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.backtesting.tier1 import oos as oos_mod

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"
_VERDICT = _DATA / "tier1_verdict.json"
_RESULTS = _DATA / "mass_tournament_results.json"
_OUT = _DATA / "tier1_monte_carlo.json"

DAYS_PER_YEAR = 365          # stablecoin yield accrues daily
DEFAULT_N_PATHS = 2000
DEFAULT_BLOCK = 20           # mean block length (days) for the stationary bootstrap
MIN_DAYS = 30                # need at least this many real daily-yield observations
SEED = 42                    # FIXED — deterministic by contract


# ---------------------------------------------------------------------------
# Real daily blended-yield series for a strategy (same weighting as oos.py)
# ---------------------------------------------------------------------------
def daily_yield_series(allocation: Dict[str, float],
                       series_map: Optional[Dict[str, Dict[str, float]]] = None
                       ) -> Dict[str, object]:
    """Build the strategy's daily blended yield (decimal/day) from the real per-protocol
    APY cache. Weighted average of forward-filled APYs over the common date axis, renormalised
    over the protocols available each day (identical approach to oos.py), then /365 for the
    daily yield. Returns {status, coverage, n_days, yields:[...]} ."""
    if series_map is None:
        series_map = oos_mod.load_protocol_series()
    weights = {k: float(v) for k, v in (allocation or {}).items()
               if k != "cash" and v and k in series_map}
    covered = sum(weights.values())
    if not weights or covered <= 0:
        return {"status": "insufficient_data", "coverage": round(covered, 4),
                "n_days": 0, "yields": []}

    axis = oos_mod._common_axis(series_map, list(weights.keys()))
    if len(axis) < MIN_DAYS:
        return {"status": "insufficient_history", "coverage": round(covered, 4),
                "n_days": len(axis), "yields": []}

    ffilled = {p: oos_mod._ffill_apy(series_map[p], axis) for p in weights}
    yields: List[float] = []
    for i in range(len(axis)):
        num, wsum = 0.0, 0.0
        for p, w in weights.items():
            a = ffilled[p][i]
            if a is not None:
                num += w * a
                wsum += w
        if wsum > 0:
            blended_apy = num / wsum               # decimal APY for the day
            yields.append(blended_apy / DAYS_PER_YEAR)  # daily yield (decimal)
    if len(yields) < MIN_DAYS:
        return {"status": "insufficient_history", "coverage": round(covered, 4),
                "n_days": len(yields), "yields": []}
    return {"status": "ok", "coverage": round(covered, 4),
            "n_days": len(yields), "yields": yields}


# ---------------------------------------------------------------------------
# Stationary block bootstrap
# ---------------------------------------------------------------------------
def _stationary_block_path(yields: List[float], block: int, rng: random.Random) -> List[float]:
    """One synthetic path of len(yields), built by chaining blocks of consecutive days.
    Block length is geometric (mean ~block) and the series wraps around (circular) so every
    starting index is admissible — this is the stationary block bootstrap of Politis & Romano."""
    n = len(yields)
    p = 1.0 / max(block, 1)        # geometric parameter → expected block length = block
    out: List[float] = []
    while len(out) < n:
        start = rng.randrange(n)
        i = start
        # geometric block: continue with prob (1-p)
        while True:
            out.append(yields[i % n])
            if len(out) >= n:
                break
            if rng.random() < p:    # stop this block
                break
            i += 1
    return out[:n]


def _annualized_return_and_maxdd(daily_yields: List[float]) -> Dict[str, float]:
    """Compound the daily yields into an equity curve, then derive annualized return (CAGR)
    and the worst peak-to-trough drawdown (as a positive percent)."""
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for y in daily_yields:
        equity *= (1.0 + y)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    n = len(daily_yields)
    # CAGR from total compounded growth over n days
    cagr = (equity ** (DAYS_PER_YEAR / n) - 1.0) if n > 0 and equity > 0 else 0.0
    return {"apy_pct": cagr * 100.0, "maxdd_pct": max_dd * 100.0}


def _percentile(sorted_vals: List[float], q: float) -> float:
    """Linear-interpolation percentile (q in [0,1]) over an already-sorted list."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def mc_strategy(allocation: Dict[str, float], n_paths: int = DEFAULT_N_PATHS,
                block: int = DEFAULT_BLOCK,
                series_map: Optional[Dict[str, Dict[str, float]]] = None) -> dict:
    """Monte-Carlo (stationary block bootstrap) confidence intervals for a strategy's
    annualized return and worst drawdown, from its real daily blended-yield series.

    Returns {status, apy_p5/p50/p95, maxdd_p5/p50/p95, n_paths, n_days, coverage, block}.
    apy_* in percent; maxdd_* the worst peak-to-trough drawdown in percent (positive).
    Deterministic: uses random.Random(SEED). Handles insufficient data via the status field."""
    ser = daily_yield_series(allocation, series_map)
    if ser["status"] != "ok":
        return {"status": ser["status"], "coverage": ser["coverage"],
                "n_days": ser["n_days"], "n_paths": 0,
                "apy_p5": None, "apy_p50": None, "apy_p95": None,
                "maxdd_p5": None, "maxdd_p50": None, "maxdd_p95": None}

    yields = ser["yields"]
    rng = random.Random(SEED)        # FIXED seed → deterministic
    apys: List[float] = []
    dds: List[float] = []
    for _ in range(n_paths):
        path = _stationary_block_path(yields, block, rng)
        m = _annualized_return_and_maxdd(path)
        apys.append(m["apy_pct"])
        dds.append(m["maxdd_pct"])
    apys.sort()
    dds.sort()
    return {
        "status": "ok",
        "n_paths": n_paths,
        "n_days": ser["n_days"],
        "coverage": ser["coverage"],
        "block": block,
        "apy_p5": round(_percentile(apys, 0.05), 4),
        "apy_p50": round(_percentile(apys, 0.50), 4),
        "apy_p95": round(_percentile(apys, 0.95), 4),
        "maxdd_p5": round(_percentile(dds, 0.05), 4),
        "maxdd_p50": round(_percentile(dds, 0.50), 4),
        "maxdd_p95": round(_percentile(dds, 0.95), 4),
    }


# ---------------------------------------------------------------------------
# Report over the validated strategies
# ---------------------------------------------------------------------------
def _validated_allocations() -> List[Dict[str, object]]:
    """Validated strategies from tier1_verdict.json paired with their allocations from
    mass_tournament_results.json. Falls back to no strategies if files are absent."""
    try:
        verdict = json.loads(_VERDICT.read_text())
    except Exception:
        return []
    try:
        results = json.loads(_RESULTS.read_text())
        allocs = {e.get("id"): (e.get("allocation") or {})
                  for e in (results.get("leaderboard") or [])}
    except Exception:
        allocs = {}
    out = []
    for x in (verdict.get("leaderboard_tier1") or []):
        if x.get("validated"):
            sid = x.get("id")
            out.append({"id": sid, "allocation": allocs.get(sid, {}),
                        "net_apy_pct": x.get("net_apy_pct")})
    return out


def build_report(write: bool = True, n_paths: int = DEFAULT_N_PATHS,
                 block: int = DEFAULT_BLOCK) -> dict:
    """Compute MC confidence intervals for each validated strategy and (atomically) write
    data/tier1_monte_carlo.json. Deterministic and read-only w.r.t. all canonical state."""
    series_map = oos_mod.load_protocol_series()
    strategies = _validated_allocations()
    rows = []
    for s in strategies:
        mc = mc_strategy(s["allocation"], n_paths=n_paths, block=block, series_map=series_map)
        rows.append({
            "id": s["id"],
            "allocation": s["allocation"],
            "point_net_apy_pct": s.get("net_apy_pct"),
            "mc": mc,
        })
    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "tier1_monte_carlo",
        "method": "stationary_block_bootstrap",
        "llm_forbidden": True,
        "seed": SEED,
        "n_paths": n_paths,
        "block_days": block,
        "min_days": MIN_DAYS,
        "validated_count": len(strategies),
        "computed_count": sum(1 for r in rows if r["mc"]["status"] == "ok"),
        "note": (
            "Stationary block bootstrap (seed=42) of each strategy's real daily blended-yield "
            "series → distribution of annualized return + worst drawdown. p5/p50/p95 are "
            "confidence intervals. Strategies whose protocols lack a real APY series report "
            "status=insufficient_data (e.g. spark_susds is not in the DeFiLlama cache). "
            "Parallel analytical layer — does not affect RiskPolicy or the cycle."
        ),
        "strategies": rows,
    }
    if write:
        _DATA.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_DATA, prefix=".tier1_mc_")
        with os.fdopen(fd, "w") as f:
            json.dump(report, f, indent=2)
        os.replace(tmp, _OUT)
    return report


if __name__ == "__main__":
    rep = build_report(write=True)
    print("Tier-1 Monte-Carlo (stationary block bootstrap, seed=%d)" % rep["seed"])
    print("  validated=%d computed=%d paths=%d block=%dd"
          % (rep["validated_count"], rep["computed_count"], rep["n_paths"], rep["block_days"]))
    if not rep["strategies"]:
        print("  (no validated strategies in tier1_verdict.json)")
    for r in rep["strategies"]:
        mc = r["mc"]
        if mc["status"] == "ok":
            print("  %-26s APY p5/p50/p95 = %.2f / %.2f / %.2f %%  |  maxDD p5/p50/p95 = %.2f / %.2f / %.2f %%  (n_days=%d)"
                  % (r["id"], mc["apy_p5"], mc["apy_p50"], mc["apy_p95"],
                     mc["maxdd_p5"], mc["maxdd_p50"], mc["maxdd_p95"], mc["n_days"]))
        else:
            print("  %-26s %s (coverage=%.2f, n_days=%d)"
                  % (r["id"], mc["status"], mc.get("coverage", 0.0), mc.get("n_days", 0)))
    # Demo on a covered allocation so __main__ always shows real CIs.
    demo = {"aave_v3": 0.5, "compound_v3": 0.3, "cash": 0.2}
    dmc = mc_strategy(demo, n_paths=500)
    print("  [demo aave/compound] APY p5/p50/p95 = %.2f / %.2f / %.2f %%  maxDD p50 = %.2f %%"
          % (dmc["apy_p5"], dmc["apy_p50"], dmc["apy_p95"], dmc["maxdd_p50"]))
