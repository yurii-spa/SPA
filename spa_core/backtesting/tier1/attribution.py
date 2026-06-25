"""
spa_core/backtesting/tier1/attribution.py — return / factor ATTRIBUTION (Tier-1).

PARALLEL MODEL. Pure stdlib, deterministic, LLM-forbidden.

A strategy's blended yield is a single headline number, but it tells you nothing about WHERE
that yield comes from. Attribution decomposes the blended net APY of an allocation into the
contribution of each underlying protocol and each risk tier (T1/T2/T3/cash):

    contribution_i = weight_i * avg_apy_i      (avg over the real series window)
    total_apy      = sum_i contribution_i      (== blended APY, renormalised over covered)
    share_i        = contribution_i / total_apy

This answers: "Which protocol carries this strategy's yield? Is the return concentrated in one
T2 venue (a hidden risk), or spread across blue-chip T1?" — a transparency overlay that
complements oos (does the edge persist), correlation (is the package diversified) and
tail_risk (what principal risk underlies the yield).

Uses the REAL per-protocol DeFiLlama APY history (data/bee/defillama_apy_history.json) via the
oos helpers (load_protocol_series / _common_axis / _ffill_apy) and the tier map from
tail_risk.PROTOCOL_TIER. build_report() attributes each VALIDATED strategy from
data/tier1_verdict.json (allocations resolved from data/mass_tournament_results.json) and
writes data/tier1_attribution.json atomically.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.backtesting.tier1 import oos as oos_mod
from spa_core.backtesting.tier1.tail_risk import PROTOCOL_TIER
from spa_core.utils.atomic import atomic_save

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"
_RESULTS = _DATA / "mass_tournament_results.json"
_VERDICT = _DATA / "tier1_verdict.json"
_OUT = _DATA / "tier1_attribution.json"

ATTRIBUTION_VERSION = "v1.0"
# OOS window: last (1 - SPLIT) of the common axis, mirroring oos.SPLIT so the recent-window
# attribution lines up with the out-of-sample yield the verdict already reports.
OOS_SPLIT = oos_mod.SPLIT


def _load(p: Path, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _tier_of(protocol: str) -> str:
    if protocol == "cash":
        return "cash"
    return PROTOCOL_TIER.get(protocol, "T2")  # unregistered → conservative T2 default


def _avg_apy_pct(per_date: Dict[str, float], axis: List[str], lo: int, hi: int) -> Optional[float]:
    """Average APY (in PERCENT) over axis[lo:hi], using forward-fill; None if never started."""
    ff = oos_mod._ffill_apy(per_date, axis)
    vals = [ff[i] for i in range(lo, hi) if ff[i] is not None]
    if not vals:
        return None
    return (sum(vals) / len(vals)) * 100.0  # decimal → percent


def attribute(allocation: Dict[str, float],
              series_map: Optional[Dict[str, Dict[str, float]]] = None) -> dict:
    """Decompose an allocation's blended net APY into per-protocol and per-tier contributions.

    Returns a dict with:
      total_apy_pct  — blended APY over covered protocols (renormalised over covered weight)
      by_protocol    — [{protocol, weight, apy_pct, contribution_pct, share_pct, tier}]
      by_tier        — {T1: contribution_pct, T2: ..., T3: ..., cash: ...}
      top_contributor — protocol id with the largest contribution (or None)
      coverage, n_days, oos — diagnostics; oos holds the same decomposition on the recent window
    """
    if series_map is None:
        series_map = oos_mod.load_protocol_series()

    raw = {k: float(v) for k, v in (allocation or {}).items() if v}
    # protocols we have a real series for (cash carries no yield, contributes 0)
    covered_w = {k: w for k, w in raw.items() if k != "cash" and k in series_map}
    covered = sum(covered_w.values())
    if not covered_w or covered <= 0:
        return {
            "status": "insufficient_data",
            "total_apy_pct": 0.0,
            "by_protocol": [],
            "by_tier": {},
            "top_contributor": None,
            "coverage": round(covered, 4),
            "n_days": 0,
            "version": ATTRIBUTION_VERSION,
        }

    axis = oos_mod._common_axis(series_map, list(covered_w.keys()))
    n = len(axis)
    cut = int(n * OOS_SPLIT)

    def _decompose(lo: int, hi: int) -> dict:
        # renormalise weights over protocols that have data IN THIS window
        contribs: Dict[str, float] = {}
        apys: Dict[str, float] = {}
        avail_w: Dict[str, float] = {}
        for p, w in covered_w.items():
            a = _avg_apy_pct(series_map[p], axis, lo, hi)
            if a is None:
                continue
            apys[p] = a
            avail_w[p] = w
        wsum = sum(avail_w.values())
        if wsum <= 0:
            return {"total_apy_pct": 0.0, "by_protocol": [], "by_tier": {}, "top_contributor": None}
        for p, w in avail_w.items():
            contribs[p] = (w / wsum) * apys[p]  # renormalised weight * avg APY
        total = sum(contribs.values())

        by_protocol = []
        by_tier: Dict[str, float] = {}
        for p in sorted(contribs, key=lambda k: contribs[k], reverse=True):
            c = contribs[p]
            tier = _tier_of(p)
            share = (c / total * 100.0) if total else 0.0
            by_protocol.append({
                "protocol": p,
                "weight": round(avail_w[p] / wsum, 4),  # renormalised weight (sums to 1)
                "apy_pct": round(apys[p], 4),
                "contribution_pct": round(c, 4),
                "share_pct": round(share, 2),
                "tier": tier,
            })
            by_tier[tier] = round(by_tier.get(tier, 0.0) + c, 4)
        top = by_protocol[0]["protocol"] if by_protocol else None
        return {
            "total_apy_pct": round(total, 4),
            "by_protocol": by_protocol,
            "by_tier": by_tier,
            "top_contributor": top,
        }

    full = _decompose(0, n)
    oos = _decompose(cut, n) if (n - cut) > 0 else {
        "total_apy_pct": 0.0, "by_protocol": [], "by_tier": {}, "top_contributor": None}

    return {
        "status": "ok",
        "total_apy_pct": full["total_apy_pct"],
        "by_protocol": full["by_protocol"],
        "by_tier": full["by_tier"],
        "top_contributor": full["top_contributor"],
        "coverage": round(covered, 4),
        "n_days": n,
        "split_at_day": cut,
        "oos": {
            "total_apy_pct": oos["total_apy_pct"],
            "by_protocol": oos["by_protocol"],
            "by_tier": oos["by_tier"],
            "top_contributor": oos["top_contributor"],
        },
        "version": ATTRIBUTION_VERSION,
    }


def build_report(write: bool = True) -> dict:
    """Attribute every VALIDATED strategy in tier1_verdict.json and write tier1_attribution.json."""
    results = _load(_RESULTS, {})
    verdict = _load(_VERDICT, {})
    alloc_map = {e["id"]: (e.get("allocation") or {}) for e in results.get("leaderboard", [])}

    series_map = oos_mod.load_protocol_series()

    strategies: Dict[str, dict] = {}
    for e in verdict.get("leaderboard_tier1", []):
        if not e.get("validated"):
            continue
        sid = e.get("id")
        alloc = alloc_map.get(sid, {})
        attr = attribute(alloc, series_map)
        strategies[sid] = {
            "package": e.get("package"),
            "net_apy_pct": e.get("net_apy_pct"),
            "allocation": alloc,
            "attribution": attr,
        }

    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "tier1_attribution",
        "llm_forbidden": True,
        "version": ATTRIBUTION_VERSION,
        "method": "contribution_i = renorm_weight_i * avg_real_apy_i; share = contribution / total",
        "oos_split": OOS_SPLIT,
        "n_validated": len(strategies),
        "strategies": strategies,
    }
    if write:
        atomic_save(out, str(_OUT))
    return out


def _top_validated_with_series(series_map) -> Optional[tuple]:
    """(id, allocation) of the highest-net-APY validated strategy that has cached series, else None."""
    results = _load(_RESULTS, {})
    verdict = _load(_VERDICT, {})
    alloc_map = {e["id"]: (e.get("allocation") or {}) for e in results.get("leaderboard", [])}
    best = None
    best_apy = -1.0
    for e in verdict.get("leaderboard_tier1", []):
        if not e.get("validated"):
            continue
        sid = e.get("id")
        alloc = alloc_map.get(sid, {})
        if not any(p in series_map for p in alloc if p != "cash"):
            continue
        apy = e.get("net_apy_pct") or 0.0
        if apy > best_apy:
            best_apy = apy
            best = (sid, alloc)
    return best


if __name__ == "__main__":
    sm = oos_mod.load_protocol_series()
    pick = _top_validated_with_series(sm)
    if pick:
        sid, alloc = pick
        print(f"attribution for top validated strategy {sid}: {alloc}")
    else:
        sid = "demo (no validated strategy has cached series)"
        alloc = {"aave_v3": 0.5, "morpho_steakhouse": 0.3, "cash": 0.2}
        print(f"attribution for {sid}: {alloc}")
    print(json.dumps(attribute(alloc, sm), indent=2))
