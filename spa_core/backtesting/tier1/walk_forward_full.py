"""
spa_core/backtesting/tier1/walk_forward_full.py — deepened Tier-1 validation.

PARALLEL MODEL. Pure stdlib, deterministic, LLM-forbidden, atomic writes. Does NOT edit
any existing module — it is a NEW layer on top of oos.py / evaluator.py.

Two questions the existing layer does not yet answer:

PART A — ROLLING WALK-FORWARD ON THE FULL EQUITY CURVE (not just average yield).
    oos.py compares average blended YIELD in one in-sample vs one out-of-sample split.
    That misses *path* effects: an allocation can have the same average APY yet a worse
    equity trajectory (drawdowns, regime breaks). Here we build the strategy's real daily
    COMPOUNDED EQUITY curve from per-protocol APY series (oos_mod.load_protocol_series),
    then run MULTIPLE consecutive train/test windows (default train 180d / test 60d, step
    60d). For each window we compute the test-period ANNUALIZED RETURN and MAX DRAWDOWN,
    and check whether the test return is (a) positive and (b) within a band of the train
    return. A strategy is `wf_robust` when >= 70% of windows hold — i.e. the edge is
    consistent across rolling regimes, not a single lucky split.

PART B — CAPACITY AT TARGET-AUM SCENARIOS.
    evaluator._capacity returns a single capacity number. Here we evaluate the discrete
    AUM scenarios that matter for the $100M external-AUM goal: {1M, 10M, 100M, 1B}. At each
    AUM, for every position we compute its size as a % of the pool TVL (from the bee cache)
    and flag whether it exceeds the 2% liquidity cap. We report, per scenario, whether the
    whole allocation `fits`, the `binding_protocol` (worst), and the `worst_utilization_pct`,
    plus the largest AUM that still fits everywhere (`max_safe_aum_usd`).

Output: data/tier1_walk_forward.json (atomic) for validated strategies + the live portfolio.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.backtesting.tier1 import oos as oos_mod
from spa_core.utils.atomic import atomic_save

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"
_VERDICT = _DATA / "tier1_verdict.json"
_RESULTS = _DATA / "mass_tournament_results.json"
_POSITIONS = _DATA / "current_positions.json"
_OUT = _DATA / "tier1_walk_forward.json"

# ---- Part A defaults -------------------------------------------------------
TRAIN_DAYS = 180
TEST_DAYS = 60
STEP_DAYS = 60
DAYS_PER_YEAR = 365
WF_CONSISTENCY_PASS = 0.70      # >= 70% of windows must hold → wf_robust
RETURN_BAND = 0.50             # test return within +/- 50% of train return = "in band"
MIN_TEST_RETURN_PCT = 0.0      # test annualized return must be strictly positive

# ---- Part B (capacity) -----------------------------------------------------
CAPACITY_MAX_POOL_PCT = 0.02   # 2% of pool TVL (mirrors evaluator.CAPACITY_MAX_POOL_PCT)
AUM_SCENARIOS = [
    ("1M", 1_000_000.0),
    ("10M", 10_000_000.0),
    ("100M", 100_000_000.0),
    ("1B", 1_000_000_000.0),
]


# ===========================================================================
# helpers
# ===========================================================================
def _normalize_allocation(allocation: Dict[str, float]) -> Dict[str, float]:
    """Accept either weight dicts (sum~1) or USD-amount dicts (positions). Return weights
    over non-cash protocols only, renormalized to sum to 1 over those protocols."""
    raw = {k: float(v) for k, v in (allocation or {}).items()
           if k != "cash" and v and float(v) > 0}
    tot = sum(raw.values())
    if tot <= 0:
        return {}
    return {k: v / tot for k, v in raw.items()}


def _blended_apy_curve(weights: Dict[str, float],
                       series_map: Dict[str, Dict[str, float]]) -> List[float]:
    """Per-day weighted-average APY (decimal) over the common date axis, renormalized over
    the protocols that have data on that day (same convention as oos.py)."""
    covered = {p: w for p, w in weights.items() if p in series_map}
    if not covered:
        return []
    axis = oos_mod._common_axis(series_map, list(covered.keys()))
    if not axis:
        return []
    ffilled = {p: oos_mod._ffill_apy(series_map[p], axis) for p in covered}
    out: List[float] = []
    for i in range(len(axis)):
        num, wsum = 0.0, 0.0
        for p, w in covered.items():
            a = ffilled[p][i]
            if a is not None:
                num += w * a
                wsum += w
        out.append((num / wsum) if wsum > 0 else 0.0)
    return out


def _equity_curve(apy_decimal_series: List[float]) -> List[float]:
    """Daily compounded equity (start = 1.0) from a per-day APY (annualized decimal) series.
    Daily factor = (1 + apy)^(1/365), so equity[i] reflects yield accrued through day i."""
    eq = [1.0]
    for apy in apy_decimal_series:
        daily = (1.0 + apy) ** (1.0 / DAYS_PER_YEAR)
        eq.append(eq[-1] * daily)
    return eq[1:]  # one equity point per day


def _annualized_return_pct(equity: List[float]) -> float:
    """Annualized return (%) of an equity sub-curve over its length in days."""
    n = len(equity)
    if n < 2 or equity[0] <= 0:
        return 0.0
    total = equity[-1] / equity[0]
    if total <= 0:
        return 0.0
    years = (n - 1) / DAYS_PER_YEAR
    if years <= 0:
        return 0.0
    return (total ** (1.0 / years) - 1.0) * 100.0


def _max_drawdown_pct(equity: List[float]) -> float:
    """Max drawdown (%) of an equity sub-curve, as a non-negative magnitude."""
    if not equity:
        return 0.0
    peak = equity[0]
    worst = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > worst:
                worst = dd
    return worst * 100.0


def _windows(n: int, train: int, test: int, step: int):
    """Yield (train_lo, train_hi, test_lo, test_hi) index slices [lo, hi).
    Test windows are consecutive and NON-OVERLAPPING when step >= test."""
    start = 0
    while start + train + test <= n:
        train_lo, train_hi = start, start + train
        test_lo, test_hi = train_hi, train_hi + test
        yield (train_lo, train_hi, test_lo, test_hi)
        start += step


# ===========================================================================
# PART A — rolling walk-forward on the equity curve
# ===========================================================================
def walk_forward(allocation: Dict[str, float],
                 train: int = TRAIN_DAYS,
                 test: int = TEST_DAYS,
                 step: int = STEP_DAYS,
                 series_map: Optional[Dict[str, Dict[str, float]]] = None) -> dict:
    """Rolling walk-forward on a strategy's compounded EQUITY curve, real per-protocol APY.

    For each consecutive train/test window: compute train- and test-period annualized
    return + max drawdown. A window "holds" when the test return is positive AND within
    RETURN_BAND of the train return. `wf_robust` when >= WF_CONSISTENCY_PASS of windows hold.
    """
    if series_map is None:
        series_map = oos_mod.load_protocol_series()
    weights = _normalize_allocation(allocation)
    covered = {p: w for p, w in weights.items() if p in series_map}
    coverage = round(sum(covered.values()), 4)  # weights already renormalized to 1
    if not covered:
        return {"status": "insufficient_data", "windows": [], "wf_robust": None,
                "consistency_pct": None, "n_windows": 0, "coverage": 0.0}

    apy_curve = _blended_apy_curve(weights, series_map)
    equity = _equity_curve(apy_curve)
    n = len(equity)
    if n < train + test:
        return {"status": "insufficient_history", "windows": [], "wf_robust": None,
                "consistency_pct": None, "n_windows": 0, "n_days": n,
                "needed_days": train + test, "coverage": coverage}

    windows = []
    holds = 0
    for (tr_lo, tr_hi, te_lo, te_hi) in _windows(n, train, test, step):
        train_eq = equity[tr_lo:tr_hi]
        test_eq = equity[te_lo:te_hi]
        tr_ret = _annualized_return_pct(train_eq)
        te_ret = _annualized_return_pct(test_eq)
        te_dd = _max_drawdown_pct(test_eq)
        # "in band": test return within +/- RETURN_BAND of train return.
        lo_band = tr_ret * (1.0 - RETURN_BAND)
        hi_band = tr_ret * (1.0 + RETURN_BAND)
        in_band = (lo_band <= te_ret <= hi_band) if tr_ret > 0 else (te_ret >= 0)
        positive = te_ret > MIN_TEST_RETURN_PCT
        held = bool(positive and in_band)
        if held:
            holds += 1
        windows.append({
            "train_idx": [tr_lo, tr_hi],
            "test_idx": [te_lo, te_hi],
            "train_return_pct": round(tr_ret, 4),
            "test_return_pct": round(te_ret, 4),
            "test_max_dd_pct": round(te_dd, 4),
            "in_band": bool(in_band),
            "positive": bool(positive),
            "holds": held,
        })

    n_windows = len(windows)
    consistency = (holds / n_windows) if n_windows else 0.0
    return {
        "status": "ok",
        "n_days": n,
        "train": train, "test": test, "step": step,
        "coverage": coverage,
        "windows": windows,
        "n_windows": n_windows,
        "consistency_pct": round(consistency * 100.0, 2),
        "wf_robust": bool(n_windows > 0 and consistency >= WF_CONSISTENCY_PASS),
    }


# ===========================================================================
# PART B — capacity at target-AUM scenarios
# ===========================================================================
def capacity_at_aum(allocation: Dict[str, float],
                    tvl_map: Optional[Dict[str, float]] = None) -> dict:
    """For each AUM in {1M,10M,100M,1B}: does every position stay <= 2% of its pool TVL?

    Per scenario: {aum_usd, fits, binding_protocol, worst_utilization_pct, positions}.
    Also: max_safe_aum_usd — the largest AUM where all positions fit (= min over protocols
    of tvl_i * CAP_PCT / weight_i), which is exact and consistent with the scenario flags.
    """
    if tvl_map is None:
        from spa_core.backtesting.tier1.evaluator import _load_tvl
        tvl_map = _load_tvl()
    weights = _normalize_allocation(allocation)
    covered = {p: w for p, w in weights.items() if tvl_map.get(p, 0) > 0}

    if not covered:
        return {"status": "insufficient_data",
                "scenarios": {k: {"aum_usd": a, "fits": None, "binding_protocol": None,
                                  "worst_utilization_pct": None} for k, a in AUM_SCENARIOS},
                "max_safe_aum_usd": None, "coverage": 0.0}

    coverage = round(sum(covered.values()), 4)
    # per-protocol max AUM before it exceeds the cap: tvl_i * CAP / weight_i
    per_protocol_max = {p: tvl_map[p] * CAPACITY_MAX_POOL_PCT / w for p, w in covered.items()}
    binding_global = min(per_protocol_max, key=per_protocol_max.get)
    max_safe_aum = per_protocol_max[binding_global]

    scenarios = {}
    for label, aum in AUM_SCENARIOS:
        positions = {}
        worst_util = 0.0
        worst_proto = None
        for p, w in covered.items():
            pos_usd = aum * w
            util = (pos_usd / tvl_map[p]) * 100.0  # % of pool TVL
            positions[p] = {"position_usd": round(pos_usd, 0),
                            "pool_tvl_usd": round(tvl_map[p], 0),
                            "utilization_pct": round(util, 4),
                            "fits": util <= CAPACITY_MAX_POOL_PCT * 100.0}
            if util > worst_util:
                worst_util = util
                worst_proto = p
        fits = worst_util <= CAPACITY_MAX_POOL_PCT * 100.0
        scenarios[label] = {
            "aum_usd": aum,
            "fits": bool(fits),
            "binding_protocol": worst_proto,
            "worst_utilization_pct": round(worst_util, 4),
            "positions": positions,
        }

    return {
        "status": "ok",
        "coverage": coverage,
        "cap_pct": CAPACITY_MAX_POOL_PCT * 100.0,
        "binding_protocol": binding_global,
        "max_safe_aum_usd": round(max_safe_aum, 0),
        "scenarios": scenarios,
    }


# ===========================================================================
# report builder
# ===========================================================================
def _live_allocation() -> Optional[Dict[str, float]]:
    """Live portfolio allocation from current_positions.json (USD amounts → weights)."""
    try:
        cp = json.loads(_POSITIONS.read_text())
    except Exception:
        return None
    pos = cp.get("positions")
    if isinstance(pos, dict) and pos:
        return {k: float(v) for k, v in pos.items()}
    return None


def _validated_strategies() -> Dict[str, Dict[str, float]]:
    """{id: allocation} for strategies marked validated in the Tier-1 verdict.
    Allocations come from mass_tournament_results.json (verdict stores no allocation)."""
    out: Dict[str, Dict[str, float]] = {}
    try:
        verdict = json.loads(_VERDICT.read_text())
    except Exception:
        verdict = {}
    try:
        results = json.loads(_RESULTS.read_text())
    except Exception:
        results = {}
    alloc_map = {e.get("id"): e.get("allocation", {}) for e in results.get("leaderboard", [])}
    for s in verdict.get("leaderboard_tier1", []):
        if s.get("validated") and s.get("id") in alloc_map:
            out[s["id"]] = alloc_map[s["id"]]
    return out


def build_report(write: bool = True) -> dict:
    """Walk-forward robustness + AUM capacity for validated strategies + the live portfolio."""
    series_map = oos_mod.load_protocol_series()
    from spa_core.backtesting.tier1.evaluator import _load_tvl
    tvl_map = _load_tvl()

    strategies = {}
    for sid, alloc in sorted(_validated_strategies().items()):
        strategies[sid] = {
            "allocation": _normalize_allocation(alloc),
            "walk_forward": walk_forward(alloc, series_map=series_map),
            "capacity": capacity_at_aum(alloc, tvl_map=tvl_map),
        }

    live_alloc = _live_allocation()
    live = None
    if live_alloc:
        live = {
            "allocation": _normalize_allocation(live_alloc),
            "walk_forward": walk_forward(live_alloc, series_map=series_map),
            "capacity": capacity_at_aum(live_alloc, tvl_map=tvl_map),
        }

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "tier1_walk_forward_full",
        "llm_forbidden": True,
        "method": {
            "part_a": (
                f"rolling walk-forward on compounded equity curve; train={TRAIN_DAYS}d "
                f"test={TEST_DAYS}d step={STEP_DAYS}d; window holds when test annualized "
                f"return > 0 AND within +/-{int(RETURN_BAND*100)}% of train return; "
                f"wf_robust when >= {int(WF_CONSISTENCY_PASS*100)}% of windows hold"
            ),
            "part_b": (
                f"capacity at AUM {{1M,10M,100M,1B}}; position must stay <= "
                f"{CAPACITY_MAX_POOL_PCT*100:.0f}% of pool TVL; max_safe_aum = min over "
                f"protocols of tvl*cap/weight"
            ),
        },
        "n_validated_strategies": len(strategies),
        "strategies": strategies,
        "live_portfolio": live,
    }
    if write:
        atomic_save(report, str(_OUT))
    return report


if __name__ == "__main__":
    sm = oos_mod.load_protocol_series()
    from spa_core.backtesting.tier1.evaluator import _load_tvl as _tvl
    tm = _tvl()
    live = _live_allocation() or {"aave_v3": 0.5, "compound_v3": 0.3, "cash": 0.2}
    label = "LIVE portfolio" if _live_allocation() else "DEMO allocation"
    print(f"=== {label}: {_normalize_allocation(live)}")

    wf = walk_forward(live, series_map=sm)
    print("\n--- PART A: walk-forward (full equity curve) ---")
    print(f"status={wf['status']} n_windows={wf['n_windows']} "
          f"consistency={wf.get('consistency_pct')}% wf_robust={wf.get('wf_robust')}")
    for w in wf.get("windows", []):
        print(f"  test {w['test_idx']}: train_ret={w['train_return_pct']}% "
              f"test_ret={w['test_return_pct']}% test_dd={w['test_max_dd_pct']}% "
              f"holds={w['holds']}")

    cap = capacity_at_aum(live, tvl_map=tm)
    print("\n--- PART B: capacity at target AUM ---")
    print(f"status={cap['status']} max_safe_aum_usd=${cap.get('max_safe_aum_usd')} "
          f"binding={cap.get('binding_protocol')}")
    for k, _a in AUM_SCENARIOS:
        s = cap.get("scenarios", {}).get(k, {})
        print(f"  {k:>5}: fits={s.get('fits')} worst_util={s.get('worst_utilization_pct')}% "
              f"binding={s.get('binding_protocol')}")

    print("\n--- build_report (data/tier1_walk_forward.json) ---")
    rep = build_report(write=True)
    print(f"validated strategies: {rep['n_validated_strategies']} | "
          f"live present: {rep['live_portfolio'] is not None}")
