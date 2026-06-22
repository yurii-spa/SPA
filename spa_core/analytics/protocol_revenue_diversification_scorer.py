"""
MP-908: ProtocolRevenueDiversificationScorer

Scores DeFi protocol revenue diversification using Herfindahl-Hirschman Index (HHI),
revenue stability, price independence, and multi-source trend analysis.

Advisory/read-only. Pure stdlib. Atomic writes (tmp + os.replace).
Ring-buffer capped at 100 entries in data/revenue_diversification_log.json.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/revenue_diversification_log.json")
MAX_ENTRIES = 100

# ─────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────

# HHI thresholds for revenue labels
HHI_SINGLE_SOURCE = 10_000      # only one source = 10000
HHI_CONCENTRATED = 5_000        # highly concentrated
HHI_MODERATE = 2_500
HHI_DIVERSIFIED = 1_500

# Diversification score mapping (0–100): inversely proportional to HHI
DIVERSIFICATION_MAX_HHI = 10_000.0

# Stability scoring weights
TREND_SCORES = {
    "growing": 100.0,
    "stable": 70.0,
    "declining": 20.0,
}

# Flags thresholds
TOKEN_PRICE_DEPENDENCY_THRESHOLD = 0.7
HIGH_HHI_THRESHOLD = 5_000
YOUNG_PROTOCOL_MONTHS = 6

# Revenue label mapping
REVENUE_LABEL_HIGHLY_DIVERSIFIED = "HIGHLY_DIVERSIFIED"
REVENUE_LABEL_DIVERSIFIED = "DIVERSIFIED"
REVENUE_LABEL_MODERATE = "MODERATE"
REVENUE_LABEL_CONCENTRATED = "CONCENTRATED"
REVENUE_LABEL_SINGLE_SOURCE = "SINGLE_SOURCE"

# Valid source types
VALID_SOURCE_TYPES = {"fees", "interest", "liquidations", "trading", "other"}


# ─────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────

def _compute_hhi(revenue_sources: list, total_revenue: float) -> float:
    """
    Compute Herfindahl-Hirschman Index for revenue sources.

    HHI = sum((share_i * 100)^2) where share_i = revenue_i / total_revenue.
    Range: 0 (perfect diversification) to 10000 (single source).
    """
    if not revenue_sources or total_revenue <= 0:
        return 10_000.0  # maximum concentration

    hhi = 0.0
    for source in revenue_sources:
        monthly_usd = float(source.get("monthly_usd", 0.0))
        if monthly_usd < 0:
            monthly_usd = 0.0
        share = monthly_usd / total_revenue
        hhi += (share * 100.0) ** 2

    return round(min(10_000.0, hhi), 2)


def _compute_diversification_score(hhi: float) -> float:
    """
    Map HHI to diversification score 0–100.
    0 HHI → 100 (fully diversified), 10000 HHI → 0 (single source).
    """
    score = (1.0 - hhi / DIVERSIFICATION_MAX_HHI) * 100.0
    return round(max(0.0, min(100.0, score)), 2)


def _compute_revenue_stability_score(
    revenue_sources: list,
    total_revenue: float,
) -> float:
    """
    Compute revenue stability score 0–100 based on revenue source trends.
    Weighted by each source's share of total revenue.
    """
    if not revenue_sources or total_revenue <= 0:
        return 0.0

    weighted_sum = 0.0
    weight_total = 0.0
    for source in revenue_sources:
        monthly_usd = float(source.get("monthly_usd", 0.0))
        if monthly_usd < 0:
            monthly_usd = 0.0
        trend = source.get("trend", "stable").lower()
        trend_score = TREND_SCORES.get(trend, TREND_SCORES["stable"])
        share = monthly_usd / total_revenue if total_revenue > 0 else 0.0
        weighted_sum += trend_score * share
        weight_total += share

    if weight_total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, weighted_sum / weight_total)), 2)


def _compute_price_independence_score(token_price_dependency: float) -> float:
    """
    Compute price independence score 0–100.
    token_price_dependency=0 → 100 (fully independent of price).
    token_price_dependency=1 → 0 (fully dependent on token price).
    """
    dependency = max(0.0, min(1.0, float(token_price_dependency)))
    return round((1.0 - dependency) * 100.0, 2)


def _get_primary_source(revenue_sources: list) -> dict | None:
    """Return the revenue source with the highest monthly_usd."""
    if not revenue_sources:
        return None
    return max(revenue_sources, key=lambda s: float(s.get("monthly_usd", 0.0)))


def _compute_revenue_label(hhi: float, source_count: int) -> str:
    """Determine revenue diversification label from HHI and source count."""
    if source_count <= 1 or hhi >= HHI_SINGLE_SOURCE:
        return REVENUE_LABEL_SINGLE_SOURCE
    elif hhi >= HHI_CONCENTRATED:
        return REVENUE_LABEL_CONCENTRATED
    elif hhi >= HHI_MODERATE:
        return REVENUE_LABEL_MODERATE
    elif hhi >= HHI_DIVERSIFIED:
        return REVENUE_LABEL_DIVERSIFIED
    else:
        return REVENUE_LABEL_HIGHLY_DIVERSIFIED


def _compute_flags(
    token_price_dependency: float,
    primary_source: dict | None,
    age_months: float,
    chain_count: int,
    hhi: float,
) -> list:
    """Compute flags for a protocol revenue analysis."""
    flags = []

    if token_price_dependency > TOKEN_PRICE_DEPENDENCY_THRESHOLD:
        flags.append("TOKEN_PRICE_DEPENDENT")

    if primary_source is not None:
        trend = primary_source.get("trend", "stable").lower()
        if trend == "declining":
            flags.append("DECLINING_PRIMARY")

    if age_months < YOUNG_PROTOCOL_MONTHS:
        flags.append("YOUNG_PROTOCOL")

    if chain_count <= 1:
        flags.append("SINGLE_CHAIN")

    if hhi > HIGH_HHI_THRESHOLD:
        flags.append("HIGH_HHI")

    return flags


def _effective_total_revenue(protocol: dict) -> float:
    """
    Get effective total monthly revenue. If total_monthly_revenue_usd not present,
    compute from revenue sources.
    """
    if "total_monthly_revenue_usd" in protocol:
        val = float(protocol["total_monthly_revenue_usd"])
        if val >= 0:
            return val

    sources = protocol.get("revenue_sources", [])
    return sum(max(0.0, float(s.get("monthly_usd", 0.0))) for s in sources)


def _score_protocol(protocol: dict, config: dict) -> dict:
    """Score a single protocol and return per-protocol result dict."""
    name = protocol.get("name", "unknown")
    revenue_sources = protocol.get("revenue_sources", [])
    total_monthly_revenue_usd = _effective_total_revenue(protocol)
    age_months = float(protocol.get("age_months", 0.0))
    chain_count = int(protocol.get("chain_count", 1))
    user_count = int(protocol.get("user_count", 0))
    token_price_dependency = float(protocol.get("token_price_dependency", 0.0))

    source_count = len(revenue_sources)

    hhi = _compute_hhi(revenue_sources, total_monthly_revenue_usd)
    diversification_score = _compute_diversification_score(hhi)
    revenue_stability_score = _compute_revenue_stability_score(revenue_sources, total_monthly_revenue_usd)
    price_independence_score = _compute_price_independence_score(token_price_dependency)

    label = _compute_revenue_label(hhi, source_count)
    primary_source = _get_primary_source(revenue_sources)
    flags = _compute_flags(
        token_price_dependency,
        primary_source,
        age_months,
        chain_count,
        hhi,
    )

    # Build source summary
    source_summary = []
    for src in revenue_sources:
        monthly_usd = float(src.get("monthly_usd", 0.0))
        share_pct = (monthly_usd / total_monthly_revenue_usd * 100.0) if total_monthly_revenue_usd > 0 else 0.0
        source_summary.append({
            "source_type": src.get("source_type", "other"),
            "monthly_usd": monthly_usd,
            "share_pct": round(share_pct, 2),
            "trend": src.get("trend", "stable"),
        })

    return {
        "name": name,
        "herfindahl_index": hhi,
        "diversification_score": diversification_score,
        "revenue_stability_score": revenue_stability_score,
        "price_independence_score": price_independence_score,
        "revenue_label": label,
        "flags": flags,
        "source_count": source_count,
        "total_monthly_revenue_usd": total_monthly_revenue_usd,
        "age_months": age_months,
        "chain_count": chain_count,
        "user_count": user_count,
        "primary_source_type": primary_source.get("source_type") if primary_source else None,
        "source_summary": source_summary,
    }


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

class ProtocolRevenueDiversificationScorer:
    """
    Scores DeFi protocol revenue diversification.

    Each protocol dict must contain:
        name: str
        revenue_sources: list[{source_type, monthly_usd, trend}]
        total_monthly_revenue_usd: float
        age_months: float
        chain_count: int
        user_count: int
        token_price_dependency: float  -- 0 (independent) to 1 (fully dependent)

    config dict may contain:
        data_file: str  (override default DATA_FILE path)
    """

    def score(self, protocols: list, config: dict | None = None) -> dict:
        """
        Score a list of protocols and return aggregated results.

        Returns:
            {
                "protocols": [per-protocol results],
                "aggregates": {
                    "most_diversified": str,
                    "least_diversified": str,
                    "average_hhi": float,
                    "average_diversification": float,
                    "highly_diversified_count": int,
                },
                "timestamp": float,
                "protocol_count": int,
            }
        """
        if config is None:
            config = {}

        if not protocols:
            result = {
                "protocols": [],
                "aggregates": {
                    "most_diversified": None,
                    "least_diversified": None,
                    "average_hhi": 0.0,
                    "average_diversification": 0.0,
                    "highly_diversified_count": 0,
                },
                "timestamp": time.time(),
                "protocol_count": 0,
            }
            self._write_log(result, config)
            return result

        protocol_results = [_score_protocol(p, config) for p in protocols]

        # Aggregates
        avg_hhi = sum(r["herfindahl_index"] for r in protocol_results) / len(protocol_results)
        avg_div = sum(r["diversification_score"] for r in protocol_results) / len(protocol_results)
        highly_div_count = sum(
            1 for r in protocol_results if r["revenue_label"] == REVENUE_LABEL_HIGHLY_DIVERSIFIED
        )

        most_diversified = min(protocol_results, key=lambda r: r["herfindahl_index"])
        least_diversified = max(protocol_results, key=lambda r: r["herfindahl_index"])

        result = {
            "protocols": protocol_results,
            "aggregates": {
                "most_diversified": most_diversified["name"],
                "least_diversified": least_diversified["name"],
                "average_hhi": round(avg_hhi, 2),
                "average_diversification": round(avg_div, 2),
                "highly_diversified_count": highly_div_count,
            },
            "timestamp": time.time(),
            "protocol_count": len(protocol_results),
        }

        self._write_log(result, config)
        return result

    @staticmethod
    def _write_log(result: dict, config: dict) -> None:
        """Append result to ring-buffer log (atomic write)."""
        data_file = Path(config.get("data_file", DATA_FILE))

        if data_file.exists():
            try:
                with open(data_file) as f:
                    log = json.load(f)
            except (json.JSONDecodeError, OSError):
                log = []
        else:
            log = []

        entry = {
            "ts": result["timestamp"],
            "protocol_count": result["protocol_count"],
            "aggregates": result["aggregates"],
        }
        log.append(entry)

        if len(log) > MAX_ENTRIES:
            log = log[-MAX_ENTRIES:]

        tmp = str(data_file) + ".tmp"
        data_file.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp, str(data_file))


# ─────────────────────────────────────────────────────────────────
# Expose internal helpers for unit testing
# ─────────────────────────────────────────────────────────────────

__all__ = [
    "ProtocolRevenueDiversificationScorer",
    "_compute_hhi",
    "_compute_diversification_score",
    "_compute_revenue_stability_score",
    "_compute_price_independence_score",
    "_compute_revenue_label",
    "_compute_flags",
    "_get_primary_source",
    "_score_protocol",
    "_effective_total_revenue",
]
