"""
MP-876: YieldOpportunityScorer

Master scoring function that combines yield, risk, liquidity, and sustainability
into a single composite opportunity score for ranking DeFi yield opportunities.

Read-only analytics module — stdlib only, atomic writes, ring-buffer 100.

Default weights (sum = 1.0):
  yield          0.30
  safety         0.30   (inverted risk_score)
  liquidity      0.20
  sustainability 0.15
  battle_test    0.05

yield_score_raw = min(100, net_apy_pct * 2)   (50% APY → score 100)

composite_score = int(sum of components), capped at 100.

Grades:
  A+   >= 85
  A    >= 75
  B+   >= 65
  B    >= 55
  C    >= 40
  D    < 40

filtered_out: net_apy_pct < min_apy_pct  OR  tvl_usd < min_tvl_usd
rank: 1 = best; filtered items get rank=0.
"""

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

_DEFAULT_LOG_PATH = "data/yield_opportunity_log.json"
_MAX_LOG_ENTRIES = 100

_DEFAULT_WEIGHTS: Dict[str, float] = {
    "yield": 0.30,
    "safety": 0.30,
    "liquidity": 0.20,
    "sustainability": 0.15,
    "battle_test": 0.05,
}

_DEFAULT_MIN_APY: float = 0.0
_DEFAULT_MIN_TVL: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_config(config: Optional[dict]) -> Tuple[Dict[str, float], float, float]:
    """Return (weights, min_apy_pct, min_tvl_usd)."""
    if config is None:
        config = {}

    weights: Dict[str, float] = dict(_DEFAULT_WEIGHTS)
    if "weights" in config and isinstance(config["weights"], dict):
        weights.update(config["weights"])

    min_apy: float = float(config.get("min_apy_pct", _DEFAULT_MIN_APY))
    min_tvl: float = float(config.get("min_tvl_usd", _DEFAULT_MIN_TVL))

    return weights, min_apy, min_tvl


def _opportunity_grade(composite: int) -> str:
    if composite >= 85:
        return "A+"
    if composite >= 75:
        return "A"
    if composite >= 65:
        return "B+"
    if composite >= 55:
        return "B"
    if composite >= 40:
        return "C"
    return "D"


def _score_opportunity(opp: dict, weights: Dict[str, float]) -> Tuple[int, dict]:
    """
    Returns (composite_score, component_dict).
    """
    net_apy: float = float(opp.get("net_apy_pct", 0.0))
    risk: float = float(opp.get("risk_score", 0))
    liquidity: float = float(opp.get("liquidity_score", 0))
    sustainability: float = float(opp.get("sustainability_score", 0))
    battle_test: float = float(opp.get("battle_test_score", 0))

    # Yield score raw: capped at 100; 0 if apy <= 0
    if net_apy <= 0:
        yield_score_raw = 0.0
    else:
        yield_score_raw = min(100.0, net_apy * 2.0)

    yield_component = yield_score_raw * weights["yield"]
    safety_component = (100.0 - risk) * weights["safety"]
    liquidity_component = liquidity * weights["liquidity"]
    sustainability_component = sustainability * weights["sustainability"]
    battle_test_component = battle_test * weights["battle_test"]

    composite = int(
        yield_component
        + safety_component
        + liquidity_component
        + sustainability_component
        + battle_test_component
    )
    composite = min(100, composite)

    components = {
        "yield_component": yield_component,
        "safety_component": safety_component,
        "liquidity_component": liquidity_component,
        "sustainability_component": sustainability_component,
        "battle_test_component": battle_test_component,
    }
    return composite, components


# ---------------------------------------------------------------------------
# Main analyze function
# ---------------------------------------------------------------------------


def analyze(opportunities: List[dict],
            config: Optional[dict] = None,
            log_path: str = _DEFAULT_LOG_PATH) -> dict:
    """
    Score and rank DeFi yield opportunities.

    Parameters
    ----------
    opportunities : list of opportunity dicts (see module docstring).
    config        : optional weights / filter thresholds.
    log_path      : path to ring-buffer JSON log.

    Returns
    -------
    dict with keys described in module docstring.
    """
    ts = time.time()
    weights, min_apy, min_tvl = _parse_config(config)

    if not opportunities:
        result: dict = {
            "opportunities": [],
            "top_opportunity": None,
            "top_opportunities_by_chain": {},
            "filtered_count": 0,
            "ranking_summary": [],
            "average_composite_score": 0.0,
            "timestamp": ts,
        }
        _append_log(result, log_path)
        return result

    scored_opps: List[dict] = []

    for opp in opportunities:
        name: str = opp.get("name", "")
        protocol: str = opp.get("protocol", "")
        chain: str = opp.get("chain", "")
        net_apy: float = float(opp.get("net_apy_pct", 0.0))
        tvl: float = float(opp.get("tvl_usd", 0.0))
        min_cap: float = float(opp.get("min_capital_usd", 0.0))

        filtered_out: bool = (net_apy < min_apy) or (tvl < min_tvl)

        composite, components = _score_opportunity(opp, weights)
        grade = _opportunity_grade(composite)

        scored_opps.append({
            "name": name,
            "protocol": protocol,
            "chain": chain,
            "net_apy_pct": net_apy,
            "composite_score": composite,
            "opportunity_grade": grade,
            "yield_component": components["yield_component"],
            "safety_component": components["safety_component"],
            "liquidity_component": components["liquidity_component"],
            "sustainability_component": components["sustainability_component"],
            "battle_test_component": components["battle_test_component"],
            "rank": 0,  # placeholder; set below for non-filtered
            "filtered_out": filtered_out,
        })

    # Separate non-filtered and assign ranks
    non_filtered = [o for o in scored_opps if not o["filtered_out"]]
    filtered_count = sum(1 for o in scored_opps if o["filtered_out"])

    # Sort non-filtered by composite_score descending
    non_filtered_sorted = sorted(non_filtered,
                                 key=lambda x: x["composite_score"],
                                 reverse=True)
    for rank_idx, opp_s in enumerate(non_filtered_sorted, start=1):
        opp_s["rank"] = rank_idx

    # Push ranks back into scored_opps list (sync by name)
    rank_map: Dict[str, int] = {o["name"]: o["rank"] for o in non_filtered_sorted}
    for o in scored_opps:
        if not o["filtered_out"]:
            o["rank"] = rank_map.get(o["name"], 0)

    # Top opportunity
    top_opportunity: Optional[str] = None
    if non_filtered_sorted:
        top_opportunity = non_filtered_sorted[0]["name"]

    # Top by chain (non-filtered only)
    top_by_chain: Dict[str, str] = {}
    chain_best: Dict[str, dict] = {}
    for o in non_filtered:
        ch = o["chain"]
        if ch not in chain_best or o["composite_score"] > chain_best[ch]["composite_score"]:
            chain_best[ch] = o
    top_by_chain = {ch: o["name"] for ch, o in chain_best.items()}

    # Average composite (non-filtered)
    avg_composite: float = 0.0
    if non_filtered:
        avg_composite = sum(o["composite_score"] for o in non_filtered) / len(non_filtered)

    # Ranking summary: top 5 non-filtered
    ranking_summary: List[dict] = [
        {
            "rank": o["rank"],
            "name": o["name"],
            "composite_score": o["composite_score"],
            "net_apy_pct": o["net_apy_pct"],
            "grade": o["opportunity_grade"],
        }
        for o in non_filtered_sorted[:5]
    ]

    result = {
        "opportunities": scored_opps,
        "top_opportunity": top_opportunity,
        "top_opportunities_by_chain": top_by_chain,
        "filtered_count": filtered_count,
        "ranking_summary": ranking_summary,
        "average_composite_score": avg_composite,
        "timestamp": ts,
    }

    _append_log(result, log_path)
    return result


# ---------------------------------------------------------------------------
# Ring-buffer log helper
# ---------------------------------------------------------------------------


def _append_log(result: dict, log_path: str) -> None:
    """Append a summary entry to the ring-buffer log (capped at 100)."""
    try:
        if os.path.exists(log_path):
            with open(log_path, "r") as fh:
                entries: List[dict] = json.load(fh)
        else:
            entries = []
    except Exception:
        entries = []

    entry = {
        "timestamp": result.get("timestamp", time.time()),
        "opportunity_count": len(result.get("opportunities", [])),
        "filtered_count": result.get("filtered_count", 0),
        "top_opportunity": result.get("top_opportunity"),
        "average_composite_score": result.get("average_composite_score", 0.0),
    }
    entries.append(entry)
    if len(entries) > _MAX_LOG_ENTRIES:
        entries = entries[-_MAX_LOG_ENTRIES:]

    dir_path = os.path.dirname(log_path) or "."
    os.makedirs(dir_path, exist_ok=True)
    tmp = log_path + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump(entries, fh, indent=2)
        os.replace(tmp, log_path)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _DEMO = [
        {
            "name": "Aave-USDC-v3",
            "protocol": "Aave",
            "net_apy_pct": 3.5,
            "risk_score": 20,
            "liquidity_score": 95,
            "sustainability_score": 90,
            "battle_test_score": 95,
            "tvl_usd": 8_000_000_000.0,
            "min_capital_usd": 1.0,
            "chain": "ethereum",
        },
        {
            "name": "Morpho-Steakhouse",
            "protocol": "Morpho",
            "net_apy_pct": 6.5,
            "risk_score": 35,
            "liquidity_score": 80,
            "sustainability_score": 80,
            "battle_test_score": 75,
            "tvl_usd": 500_000_000.0,
            "min_capital_usd": 1.0,
            "chain": "ethereum",
        },
        {
            "name": "Delta-Neutral-sUSDe",
            "protocol": "Ethena",
            "net_apy_pct": 25.0,
            "risk_score": 60,
            "liquidity_score": 70,
            "sustainability_score": 55,
            "battle_test_score": 40,
            "tvl_usd": 3_000_000_000.0,
            "min_capital_usd": 1000.0,
            "chain": "ethereum",
        },
    ]

    out = analyze(_DEMO)
    print(json.dumps(out, indent=2))
    sys.exit(0)
