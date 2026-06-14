"""
MP-1011 ProtocolDeFiYieldSourceSustainabilityRanker
Advisory/read-only. Pure stdlib. No external dependencies.

Ranks DeFi yield sources by sustainability and quality, evaluating
real yield vs emission-dependent yield, revenue coverage, and durability.

Data log: data/yield_sustainability_rank_log.json (ring-buffer 100, atomic write)
"""

import json
import math
import os
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "data",
    "yield_sustainability_rank_log.json",
)
_LOG_CAP = 100

# Competitive advantage weights for sustainability scoring
_ADVANTAGE_WEIGHTS = {
    "none": 0.0,
    "efficiency": 0.4,
    "network_effect": 0.7,
    "monopoly": 1.0,
}

# Valid yield types
_VALID_YIELD_TYPES = {
    "trading_fees",
    "lending_interest",
    "staking_rewards",
    "liquidity_mining",
    "points_farming",
    "real_world_yield",
    "protocol_revenue_share",
    "restaking",
}

# ---------------------------------------------------------------------------
# Labels & Flags
# ---------------------------------------------------------------------------

LABEL_FORTRESS_YIELD = "FORTRESS_YIELD"            # real_yield>8%, sustainability>80, coverage>2
LABEL_SUSTAINABLE = "SUSTAINABLE"                  # sustainability>65
LABEL_TRANSITIONAL = "TRANSITIONAL"                # improving but emission>40%
LABEL_EMISSION_DEPENDENT = "EMISSION_DEPENDENT"    # emission>60%
LABEL_UNSUSTAINABLE = "UNSUSTAINABLE"              # coverage<0.5 AND emission>70%
LABEL_POINTS_SPECULATION = "POINTS_SPECULATION"    # yield_type=points_farming

FLAG_REAL_YIELD_DOMINANT = "REAL_YIELD_DOMINANT"   # emission<20%
FLAG_EMISSION_HEAVY = "EMISSION_HEAVY"             # emission>60%
FLAG_REVENUE_SURPLUS = "REVENUE_SURPLUS"           # coverage>2
FLAG_AIRDROP_BOOSTED = "AIRDROP_BOOSTED"           # yield_type=points_farming
FLAG_COMPETITIVE_MOAT = "COMPETITIVE_MOAT"         # advantage != none
FLAG_YIELD_DECLINING = "YIELD_DECLINING"           # current_apy < 90d_avg * 0.8


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _apy_stability_score(apy_std: float, current_apy: float, avg_90d: float) -> float:
    """
    0-100 score: low std + current close to 90d average = stable.
    """
    # Coefficient of variation (normalized volatility)
    if avg_90d > 0:
        cv = apy_std / avg_90d
    else:
        cv = apy_std / max(current_apy, 0.01)

    if cv <= 0.05:
        std_score = 95.0
    elif cv <= 0.10:
        std_score = 80.0
    elif cv <= 0.20:
        std_score = 60.0
    elif cv <= 0.40:
        std_score = 40.0
    elif cv <= 0.70:
        std_score = 20.0
    else:
        std_score = 5.0

    # Proximity to 90d average
    if avg_90d > 0:
        deviation = abs(current_apy - avg_90d) / avg_90d
    else:
        deviation = 0.0

    if deviation <= 0.05:
        prox_score = 100.0
    elif deviation <= 0.10:
        prox_score = 80.0
    elif deviation <= 0.20:
        prox_score = 60.0
    elif deviation <= 0.40:
        prox_score = 35.0
    else:
        prox_score = 15.0

    return round(_clamp(std_score * 0.60 + prox_score * 0.40, 0.0, 100.0), 2)


def _sustainability_score(
    real_yield_pct: float,
    revenue_coverage_ratio: float,
    competitive_advantage: str,
    sustainability_horizon_months: float,
    emission_component_pct: float,
) -> float:
    """
    0-100 composite sustainability score.
    Weights: real_yield 0.4, revenue_coverage 0.3, competitive_advantage 0.2, horizon 0.1
    """
    # Real yield component (0-100): scale by real yield magnitude
    if real_yield_pct >= 15.0:
        ry_score = 100.0
    elif real_yield_pct >= 10.0:
        ry_score = 85.0
    elif real_yield_pct >= 7.0:
        ry_score = 70.0
    elif real_yield_pct >= 4.0:
        ry_score = 55.0
    elif real_yield_pct >= 2.0:
        ry_score = 40.0
    elif real_yield_pct >= 0.5:
        ry_score = 25.0
    else:
        ry_score = 5.0

    # Revenue coverage component (0-100)
    if revenue_coverage_ratio >= 3.0:
        rc_score = 100.0
    elif revenue_coverage_ratio >= 2.0:
        rc_score = 85.0
    elif revenue_coverage_ratio >= 1.5:
        rc_score = 70.0
    elif revenue_coverage_ratio >= 1.0:
        rc_score = 55.0
    elif revenue_coverage_ratio >= 0.7:
        rc_score = 35.0
    elif revenue_coverage_ratio >= 0.3:
        rc_score = 15.0
    else:
        rc_score = 5.0

    # Competitive advantage component (0-100)
    adv_raw = _ADVANTAGE_WEIGHTS.get(competitive_advantage, 0.0)
    adv_score = adv_raw * 100.0

    # Horizon component (0-100): scale up to 36 months
    if sustainability_horizon_months >= 36:
        hz_score = 100.0
    elif sustainability_horizon_months >= 24:
        hz_score = 80.0
    elif sustainability_horizon_months >= 18:
        hz_score = 65.0
    elif sustainability_horizon_months >= 12:
        hz_score = 50.0
    elif sustainability_horizon_months >= 6:
        hz_score = 30.0
    elif sustainability_horizon_months >= 3:
        hz_score = 15.0
    else:
        hz_score = 5.0

    composite = (
        ry_score * 0.40
        + rc_score * 0.30
        + adv_score * 0.20
        + hz_score * 0.10
    )

    # Penalty for heavy emission dependency
    if emission_component_pct > 80.0:
        composite *= 0.60
    elif emission_component_pct > 60.0:
        composite *= 0.75

    return round(_clamp(composite, 0.0, 100.0), 2)


def _classify_source(
    real_yield_pct: float,
    sustainability_sc: float,
    revenue_coverage_ratio: float,
    emission_component_pct: float,
    yield_type: str,
) -> str:
    """Assign sustainability label."""
    if yield_type == "points_farming":
        return LABEL_POINTS_SPECULATION
    if (
        real_yield_pct > 8.0
        and sustainability_sc > 80.0
        and revenue_coverage_ratio > 2.0
    ):
        return LABEL_FORTRESS_YIELD
    if revenue_coverage_ratio < 0.5 and emission_component_pct > 70.0:
        return LABEL_UNSUSTAINABLE
    if emission_component_pct > 60.0:
        return LABEL_EMISSION_DEPENDENT
    if emission_component_pct > 40.0:
        return LABEL_TRANSITIONAL
    if sustainability_sc > 65.0:
        return LABEL_SUSTAINABLE
    return LABEL_TRANSITIONAL


def _compute_flags(
    emission_component_pct: float,
    revenue_coverage_ratio: float,
    yield_type: str,
    competitive_advantage: str,
    current_apy: float,
    avg_90d_apy: float,
) -> list:
    flags = []
    if emission_component_pct < 20.0:
        flags.append(FLAG_REAL_YIELD_DOMINANT)
    if emission_component_pct > 60.0:
        flags.append(FLAG_EMISSION_HEAVY)
    if revenue_coverage_ratio > 2.0:
        flags.append(FLAG_REVENUE_SURPLUS)
    if yield_type == "points_farming":
        flags.append(FLAG_AIRDROP_BOOSTED)
    if competitive_advantage not in ("none", ""):
        flags.append(FLAG_COMPETITIVE_MOAT)
    if avg_90d_apy > 0 and current_apy < avg_90d_apy * 0.80:
        flags.append(FLAG_YIELD_DECLINING)
    return flags


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class ProtocolDeFiYieldSourceSustainabilityRanker:
    """
    Ranks DeFi yield sources by sustainability.

    Each source dict:
        name                        str
        protocol                    str
        yield_type                  str  — see _VALID_YIELD_TYPES
        current_apy_pct             float
        apy_90d_avg_pct             float
        apy_90d_std_pct             float   — volatility
        token_emission_component_pct float  — % APY from token emissions
        has_real_revenue_backing    bool
        revenue_coverage_ratio      float   — protocol_revenue / emission_cost (>1 sustainable)
        competitive_advantage       str     — "none"/"efficiency"/"network_effect"/"monopoly"
        sustainability_horizon_months float — expected support duration
    """

    def rank(self, yield_sources: list, config: dict) -> dict:
        if not isinstance(yield_sources, list) or not yield_sources:
            return {
                "status": "no_data",
                "sources": [],
                "ranking": [],
                "aggregates": {},
                "timestamp": time.time(),
            }

        results = []
        for src in yield_sources:
            result = self._analyze_source(src, config)
            results.append(result)

        # Sort by sustainability_score descending
        ranking = sorted(results, key=lambda r: r["sustainability_score"], reverse=True)
        ranked_list = [
            {"rank": i + 1, "name": r["name"], "sustainability_score": r["sustainability_score"]}
            for i, r in enumerate(ranking)
        ]

        aggregates = self._aggregate(results, ranking)

        output = {
            "status": "ok",
            "sources": results,
            "ranking": ranked_list,
            "aggregates": aggregates,
            "timestamp": time.time(),
        }

        self._append_log(output)
        return output

    # ------------------------------------------------------------------
    def _analyze_source(self, src: dict, config: dict) -> dict:
        name = str(src.get("name", "unknown"))
        protocol = str(src.get("protocol", "unknown"))
        yield_type = str(src.get("yield_type", "trading_fees")).lower()

        current_apy = float(src.get("current_apy_pct", 0.0))
        avg_90d = float(src.get("apy_90d_avg_pct", current_apy))
        std_90d = float(src.get("apy_90d_std_pct", 0.0))
        emission_pct = float(src.get("token_emission_component_pct", 0.0))
        has_real_revenue = bool(src.get("has_real_revenue_backing", False))
        rev_coverage = float(src.get("revenue_coverage_ratio", 0.0))
        competitive_adv = str(src.get("competitive_advantage", "none")).lower()
        horizon_months = float(src.get("sustainability_horizon_months", 6.0))

        # Derived metrics
        real_yield_pct = round(current_apy * (1.0 - emission_pct / 100.0), 4)

        apy_stability_sc = _apy_stability_score(std_90d, current_apy, avg_90d)

        sustainability_sc = _sustainability_score(
            real_yield_pct,
            rev_coverage,
            competitive_adv,
            horizon_months,
            emission_pct,
        )

        risk_adjusted_yield = round(real_yield_pct * sustainability_sc / 100.0, 4)

        emission_dependency_risk = (
            "HIGH" if emission_pct > 60.0 else ("MEDIUM" if emission_pct > 30.0 else "LOW")
        )

        label = _classify_source(
            real_yield_pct,
            sustainability_sc,
            rev_coverage,
            emission_pct,
            yield_type,
        )

        flags = _compute_flags(
            emission_pct,
            rev_coverage,
            yield_type,
            competitive_adv,
            current_apy,
            avg_90d,
        )

        return {
            "name": name,
            "protocol": protocol,
            "yield_type": yield_type,
            "current_apy_pct": current_apy,
            "apy_90d_avg_pct": avg_90d,
            "apy_90d_std_pct": std_90d,
            "token_emission_component_pct": emission_pct,
            "has_real_revenue_backing": has_real_revenue,
            "revenue_coverage_ratio": rev_coverage,
            "competitive_advantage": competitive_adv,
            "sustainability_horizon_months": horizon_months,
            # Computed
            "real_yield_pct": real_yield_pct,
            "apy_stability_score": apy_stability_sc,
            "sustainability_score": sustainability_sc,
            "risk_adjusted_yield": risk_adjusted_yield,
            "emission_dependency_risk": emission_dependency_risk,
            # Classification
            "label": label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    def _aggregate(self, results: list, ranking: list) -> dict:
        if not results:
            return {}

        real_yields = [r["real_yield_pct"] for r in results]
        sustainability_scores = [r["sustainability_score"] for r in results]

        avg_real_yield = round(sum(real_yields) / len(real_yields), 4)
        avg_sustainability = round(
            sum(sustainability_scores) / len(sustainability_scores), 2
        )

        fortress_count = sum(1 for r in results if r["label"] == LABEL_FORTRESS_YIELD)
        unsustainable_count = sum(1 for r in results if r["label"] == LABEL_UNSUSTAINABLE)
        emission_dependent_count = sum(
            1 for r in results if r["label"] == LABEL_EMISSION_DEPENDENT
        )
        points_speculation_count = sum(
            1 for r in results if r["label"] == LABEL_POINTS_SPECULATION
        )
        real_yield_dominant_count = sum(
            1 for r in results if FLAG_REAL_YIELD_DOMINANT in r["flags"]
        )

        highest = results[next(
            i for i, r in enumerate(results) if r["sustainability_score"] == max(sustainability_scores)
        )]
        lowest = results[next(
            i for i, r in enumerate(results) if r["sustainability_score"] == min(sustainability_scores)
        )]

        return {
            "source_count": len(results),
            "highest_ranked": {
                "name": highest["name"],
                "sustainability_score": highest["sustainability_score"],
                "label": highest["label"],
            },
            "lowest_ranked": {
                "name": lowest["name"],
                "sustainability_score": lowest["sustainability_score"],
                "label": lowest["label"],
            },
            "avg_real_yield_pct": avg_real_yield,
            "avg_sustainability_score": avg_sustainability,
            "fortress_count": fortress_count,
            "unsustainable_count": unsustainable_count,
            "emission_dependent_count": emission_dependent_count,
            "points_speculation_count": points_speculation_count,
            "real_yield_dominant_count": real_yield_dominant_count,
        }

    # ------------------------------------------------------------------
    def _append_log(self, output: dict) -> None:
        """Append compressed record to ring-buffer log (atomic write)."""
        log_path = os.path.abspath(_LOG_PATH)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        record = {
            "ts": output["timestamp"],
            "source_count": len(output.get("sources", [])),
            "aggregates": output.get("aggregates", {}),
        }

        try:
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    log = json.load(f)
                if not isinstance(log, list):
                    log = []
            else:
                log = []
        except (json.JSONDecodeError, OSError):
            log = []

        log.append(record)
        if len(log) > _LOG_CAP:
            log = log[-_LOG_CAP:]

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp_path, log_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="DeFi Yield Source Sustainability Ranker")
    parser.add_argument("--check", action="store_true", help="Run with sample data (no write)")
    parser.add_argument("--run", action="store_true", help="Run and write log")
    args = parser.parse_args()

    sample_sources = [
        {
            "name": "Aave-V3-USDC-Lending",
            "protocol": "Aave V3",
            "yield_type": "lending_interest",
            "current_apy_pct": 3.5,
            "apy_90d_avg_pct": 3.8,
            "apy_90d_std_pct": 0.3,
            "token_emission_component_pct": 5.0,
            "has_real_revenue_backing": True,
            "revenue_coverage_ratio": 2.5,
            "competitive_advantage": "network_effect",
            "sustainability_horizon_months": 36,
        },
        {
            "name": "XYZ-Liquidity-Mining",
            "protocol": "XYZSwap",
            "yield_type": "liquidity_mining",
            "current_apy_pct": 45.0,
            "apy_90d_avg_pct": 80.0,
            "apy_90d_std_pct": 20.0,
            "token_emission_component_pct": 85.0,
            "has_real_revenue_backing": False,
            "revenue_coverage_ratio": 0.2,
            "competitive_advantage": "none",
            "sustainability_horizon_months": 3,
        },
        {
            "name": "Morpho-Steakhouse-USDC",
            "protocol": "Morpho",
            "yield_type": "lending_interest",
            "current_apy_pct": 6.5,
            "apy_90d_avg_pct": 6.2,
            "apy_90d_std_pct": 0.5,
            "token_emission_component_pct": 10.0,
            "has_real_revenue_backing": True,
            "revenue_coverage_ratio": 1.8,
            "competitive_advantage": "efficiency",
            "sustainability_horizon_months": 24,
        },
    ]

    ranker = ProtocolDeFiYieldSourceSustainabilityRanker()
    result = ranker.rank(sample_sources, {})
    print(json.dumps(result, indent=2))
