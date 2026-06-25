"""
spa_core/backtesting/tier1/benchmark.py — benchmark-relative performance metrics.

PARALLEL MODEL. Pure stdlib (math, statistics), deterministic, no network, LLM-forbidden.
Does NOT modify RiskPolicy v1.0, the cycle, or any canonical module — new file only.

Institutional reporting needs EXCESS return vs a benchmark, not just absolute yield.
A 5% APY strategy is unimpressive if a US T-bill pays 5% and holding 100% Aave pays 5.2%.
This module measures a strategy allocation against two deterministic benchmarks:

  1. RISK-FREE  — RISK_FREE_APY_PCT = 5.0 (US T-bill proxy), a flat constant series.
  2. AAVE-HOLD  — holding 100% aave_v3, using its REAL DeFiLlama series from the bee cache
     (via tier1.oos), aligned on the same date axis as the strategy.

Reusing the oos helpers (load_protocol_series, _common_axis, _ffill_apy) keeps the data
path identical to the OOS validator: same real per-protocol APY series, same forward-fill,
same blended-APY construction.

Metrics produced (all annualized / percent where noted):
  • strategy_apy / aave_apy   — mean blended daily-yield * 365 (percent).
  • excess_vs_rf_pct          — strategy_apy - RISK_FREE_APY_PCT.
  • excess_vs_aave_pct        — strategy_apy - aave_apy.
  • tracking_error_pct        — stdev of daily (strategy - aave) excess yield, annualized
                                (* sqrt(365)) and expressed in percent.
  • information_ratio         — excess_vs_aave / tracking_error (annualized, consistent units).
  • pct_days_outperform       — % of common-axis days strategy daily yield >= aave daily yield.

References: Grinold & Kahn, "Active Portfolio Management" (Information Ratio = active return /
tracking error). All formulas reimplemented in stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import pstdev
from typing import Dict, List, Optional

from spa_core.backtesting.tier1 import oos as oos_mod
from spa_core.utils.atomic import atomic_save

_ROOT = Path(__file__).resolve().parents[3]
_VERDICT = _ROOT / "data" / "tier1_verdict.json"
_TOURNAMENT = _ROOT / "data" / "mass_tournament_results.json"
_OUT = _ROOT / "data" / "tier1_benchmark.json"

RISK_FREE_APY_PCT = 5.0          # US 3-month T-bill proxy (deterministic constant)
AAVE_BENCHMARK_PROTOCOL = "aave_v3"  # on-chain benchmark = holding 100% aave_v3
DAYS_PER_YEAR = 365              # stablecoin yield accrues daily
MIN_OVERLAP_DAYS = 20           # need enough overlapping days to judge tracking error


# ---------------------------------------------------------------------------
# Daily-yield series construction (mirrors oos blended-APY logic)
# ---------------------------------------------------------------------------
def _blended_daily_yield_series(
    weights: Dict[str, float],
    series_map: Dict[str, Dict[str, float]],
    axis: List[str],
) -> List[Optional[float]]:
    """Per-day blended daily yield (= weighted-avg APY decimal / 365) along `axis`.

    Weights are renormalised each day over the protocols whose series has started
    (forward-filled, same as oos_check). Returns None for days with no data yet."""
    ffilled = {p: oos_mod._ffill_apy(series_map[p], axis) for p in weights}
    out: List[Optional[float]] = []
    for i in range(len(axis)):
        num, wsum = 0.0, 0.0
        for p, w in weights.items():
            a = ffilled[p][i]
            if a is not None:
                num += w * a
                wsum += w
        if wsum > 0:
            out.append((num / wsum) / DAYS_PER_YEAR)  # decimal APY → daily yield
        else:
            out.append(None)
    return out


def _strategy_weights(allocation: Dict[str, float],
                      series_map: Dict[str, Dict[str, float]]) -> Dict[str, float]:
    """Allocation protocols (excl. cash) for which we have a real series."""
    return {k: float(v) for k, v in (allocation or {}).items()
            if k != "cash" and v and k in series_map}


def _insufficient(reason: str, **extra) -> dict:
    base = {
        "status": reason,
        "strategy_apy": None,
        "rf_apy": RISK_FREE_APY_PCT,
        "aave_apy": None,
        "excess_vs_rf_pct": None,
        "excess_vs_aave_pct": None,
        "tracking_error_pct": None,
        "information_ratio": None,
        "pct_days_outperform": None,
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Public: benchmark-relative metrics for a single allocation
# ---------------------------------------------------------------------------
def benchmark_relative(allocation: Dict[str, float],
                       series_map: Optional[Dict[str, Dict[str, float]]] = None) -> dict:
    """Benchmark-relative performance of a strategy allocation on real data.

    Returns a dict with strategy_apy, rf_apy, aave_apy, excess_vs_rf_pct,
    excess_vs_aave_pct, tracking_error_pct, information_ratio, pct_days_outperform.
    Handles missing data / no aave benchmark / too-short overlap gracefully."""
    if series_map is None:
        series_map = oos_mod.load_protocol_series()

    weights = _strategy_weights(allocation, series_map)
    covered = sum(weights.values())
    if not weights or covered <= 0:
        return _insufficient("insufficient_data", coverage=round(covered, 4))

    if AAVE_BENCHMARK_PROTOCOL not in series_map:
        return _insufficient("no_aave_benchmark", coverage=round(covered, 4))

    # Common date axis = union of the strategy's protocols AND the aave benchmark,
    # so both series live on the SAME axis (oos helper, sorted union of dates).
    axis = oos_mod._common_axis(
        series_map, list(weights.keys()) + [AAVE_BENCHMARK_PROTOCOL])

    strat_series = _blended_daily_yield_series(weights, series_map, axis)
    aave_series = _blended_daily_yield_series(
        {AAVE_BENCHMARK_PROTOCOL: 1.0}, series_map, axis)

    # Pair only days where BOTH benchmarks have data.
    pairs = [(s, a) for s, a in zip(strat_series, aave_series)
             if s is not None and a is not None]
    if len(pairs) < MIN_OVERLAP_DAYS:
        return _insufficient("insufficient_history",
                             coverage=round(covered, 4),
                             n_days=len(pairs))

    strat_daily = [s for s, _ in pairs]
    aave_daily = [a for _, a in pairs]
    excess_daily = [s - a for s, a in pairs]

    n = len(pairs)
    strat_apy = (sum(strat_daily) / n) * DAYS_PER_YEAR * 100.0
    aave_apy = (sum(aave_daily) / n) * DAYS_PER_YEAR * 100.0

    excess_vs_rf = strat_apy - RISK_FREE_APY_PCT
    excess_vs_aave = strat_apy - aave_apy

    # Tracking error = stdev of daily excess vs aave, annualized → percent.
    daily_te = pstdev(excess_daily) if n >= 2 else 0.0
    tracking_error = daily_te * math.sqrt(DAYS_PER_YEAR) * 100.0

    # Information Ratio = annualized excess vs aave / annualized tracking error.
    if tracking_error > 1e-12:
        info_ratio = excess_vs_aave / tracking_error
    else:
        # Zero active risk: IR is degenerate. 0 if no excess, else signed infinity.
        info_ratio = 0.0 if abs(excess_vs_aave) < 1e-9 else math.copysign(float("inf"), excess_vs_aave)

    outperform_days = sum(1 for s, a in pairs if s >= a)
    pct_outperform = (outperform_days / n) * 100.0

    return {
        "status": "ok",
        "strategy_apy": round(strat_apy, 4),
        "rf_apy": RISK_FREE_APY_PCT,
        "aave_apy": round(aave_apy, 4),
        "excess_vs_rf_pct": round(excess_vs_rf, 4),
        "excess_vs_aave_pct": round(excess_vs_aave, 4),
        "tracking_error_pct": round(tracking_error, 4),
        "information_ratio": (round(info_ratio, 4)
                              if math.isfinite(info_ratio) else info_ratio),
        "pct_days_outperform": round(pct_outperform, 2),
        "coverage": round(covered, 4),
        "n_days": n,
    }


# ---------------------------------------------------------------------------
# Report build (validated strategies → data/tier1_benchmark.json, atomic)
# ---------------------------------------------------------------------------
def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _allocation_map() -> Dict[str, Dict[str, float]]:
    """{strategy_id: allocation} from the mass tournament leaderboard."""
    data = _load_json(_TOURNAMENT)
    out: Dict[str, Dict[str, float]] = {}
    for entry in (data.get("leaderboard") or []):
        sid = entry.get("id")
        alloc = entry.get("allocation")
        if sid and isinstance(alloc, dict):
            out[sid] = {k: float(v) for k, v in alloc.items()}
    return out


def _validated_ids() -> List[str]:
    """Strategy ids marked validated in data/tier1_verdict.json (fallback: leaderboard)."""
    verdict = _load_json(_VERDICT)
    ids = [row.get("id") for row in (verdict.get("leaderboard_tier1") or [])
           if row.get("validated") and row.get("id")]
    return ids


def _atomic_write(path: Path, payload: dict) -> None:
    atomic_save(payload, str(path))


def build_report(write: bool = True) -> dict:
    """Benchmark-relative report for each validated strategy → data/tier1_benchmark.json."""
    series_map = oos_mod.load_protocol_series()
    allocs = _allocation_map()
    validated = _validated_ids()

    # Fall back to the whole leaderboard if the verdict marks nothing validated.
    targets = [sid for sid in validated if sid in allocs]
    used_fallback = False
    if not targets:
        targets = list(allocs.keys())
        used_fallback = True

    results = []
    for sid in targets:
        rel = benchmark_relative(allocs[sid], series_map)
        rel["id"] = sid
        rel["allocation"] = allocs[sid]
        results.append(rel)

    # Stable order: best excess-vs-aave first (None last), then id.
    def _key(r):
        e = r.get("excess_vs_aave_pct")
        return (0, -e) if isinstance(e, (int, float)) else (1, 0)
    results.sort(key=lambda r: (_key(r), r["id"]))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "tier1_parallel",
        "llm_forbidden": True,
        "risk_free_apy_pct": RISK_FREE_APY_PCT,
        "aave_benchmark_protocol": AAVE_BENCHMARK_PROTOCOL,
        "min_overlap_days": MIN_OVERLAP_DAYS,
        "validated_source": "tier1_verdict" if not used_fallback else "leaderboard_fallback",
        "n_strategies": len(results),
        "results": results,
    }
    if write:
        _atomic_write(_OUT, payload)
    return payload


if __name__ == "__main__":
    sm = oos_mod.load_protocol_series()
    # Real/demo allocation (protocols present in the bee cache).
    demo = {"aave_v3": 0.5, "compound_v3": 0.3, "cash": 0.2}
    print("=== benchmark_relative(demo) ===")
    print(json.dumps(benchmark_relative(demo, sm), indent=2))

    print("\n=== holding 100% aave_v3 (excess_vs_aave ~ 0) ===")
    print(json.dumps(benchmark_relative({"aave_v3": 1.0}, sm), indent=2))

    rep = build_report(write=True)
    print("\n=== build_report wrote %d strategies → %s ===" % (rep["n_strategies"], _OUT))
