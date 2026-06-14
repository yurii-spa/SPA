"""
MP-1070: DeFiProtocolYieldSourceQualityRater
Rates DeFi protocol yield quality by decomposing yield sources into
sustainable (Tier-1) vs. speculative (Tier-2) categories and computing
a weighted quality score.

Pure stdlib, read-only analytics, atomic ring-buffer log (cap 100).
"""

import json
import os
import datetime

# --------------------------------------------------------------------------- #
# Log config
# --------------------------------------------------------------------------- #
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "yield_source_quality_log.json"
)
_LOG_CAP = 100

# --------------------------------------------------------------------------- #
# Source type tiers
# --------------------------------------------------------------------------- #
TIER_1_SOURCES = frozenset({
    "trading_fees",
    "lending_interest",
    "staking_rewards",
    "protocol_revenue_share",
})

TIER_2_SOURCES = frozenset({
    "token_emissions",
    "points_farming",
    "liquidity_incentives",
})

ALL_VALID_SOURCES = TIER_1_SOURCES | TIER_2_SOURCES

# --------------------------------------------------------------------------- #
# Quality weights per source type (0-100 scale)
# --------------------------------------------------------------------------- #
SOURCE_QUALITY_WEIGHTS: dict = {
    "trading_fees": 100,
    "lending_interest": 90,
    "staking_rewards": 85,
    "protocol_revenue_share": 80,
    "liquidity_incentives": 40,
    "token_emissions": 20,
    "points_farming": 10,
}

# --------------------------------------------------------------------------- #
# Quality labels
# --------------------------------------------------------------------------- #
LABEL_PREMIUM_YIELD = "PREMIUM_YIELD"
LABEL_HIGH_QUALITY = "HIGH_QUALITY"
LABEL_MIXED_QUALITY = "MIXED_QUALITY"
LABEL_SPECULATIVE = "SPECULATIVE"
LABEL_UNSUSTAINABLE = "UNSUSTAINABLE"


# --------------------------------------------------------------------------- #
# Pure helpers (importable for testing)
# --------------------------------------------------------------------------- #

def validate_source_type(source: str) -> bool:
    """Return True if source is a known/valid source type."""
    return source in ALL_VALID_SOURCES


def compute_totals(yield_sources: list) -> tuple:
    """
    Compute (total_apy_pct, sustainable_yield_pct, speculative_yield_pct)
    from a list of source dicts.
    sustainable = sum of Tier-1 source apy_pcts
    speculative = sum of Tier-2 source apy_pcts
    """
    total_apy = 0.0
    sustainable = 0.0
    speculative = 0.0
    for src in yield_sources:
        apy = float(src.get("apy_pct", 0.0))
        total_apy += apy
        source_type = src.get("source", "")
        if source_type in TIER_1_SOURCES:
            sustainable += apy
        elif source_type in TIER_2_SOURCES:
            speculative += apy
    return round(total_apy, 4), round(sustainable, 4), round(speculative, 4)


def compute_quality_score(yield_sources: list) -> float:
    """
    Compute quality score (0-100) as a pct_of_total-weighted average of source
    quality weights.  Unknown source types contribute weight=0.

    If all pct_of_total values are 0, falls back to uniform weighting by
    apy_pct share.  If no sources, returns 0.0.
    """
    if not yield_sources:
        return 0.0

    # Try pct_of_total weighting first
    total_pct = sum(float(s.get("pct_of_total", 0.0)) for s in yield_sources)
    if total_pct > 0:
        weighted_sum = sum(
            float(s.get("pct_of_total", 0.0)) * SOURCE_QUALITY_WEIGHTS.get(s.get("source", ""), 0)
            for s in yield_sources
        )
        score = weighted_sum / total_pct
    else:
        # Fall back: weight by apy_pct
        total_apy = sum(float(s.get("apy_pct", 0.0)) for s in yield_sources)
        if total_apy <= 0:
            # Equal weighting
            n = len(yield_sources)
            score = sum(
                SOURCE_QUALITY_WEIGHTS.get(s.get("source", ""), 0)
                for s in yield_sources
            ) / n if n > 0 else 0.0
        else:
            weighted_sum = sum(
                float(s.get("apy_pct", 0.0)) * SOURCE_QUALITY_WEIGHTS.get(s.get("source", ""), 0)
                for s in yield_sources
            )
            score = weighted_sum / total_apy

    return round(min(max(score, 0.0), 100.0), 2)


def quality_label(quality_score: float) -> str:
    """Map quality score (0-100) to a quality label."""
    if quality_score >= 85.0:
        return LABEL_PREMIUM_YIELD
    if quality_score >= 70.0:
        return LABEL_HIGH_QUALITY
    if quality_score >= 50.0:
        return LABEL_MIXED_QUALITY
    if quality_score >= 30.0:
        return LABEL_SPECULATIVE
    return LABEL_UNSUSTAINABLE


def _atomic_log_append(entry: dict, log_path: str, cap: int) -> None:
    """Append one entry to ring-buffer JSON log atomically (tmp + os.replace)."""
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as fh:
                records = json.load(fh)
            if not isinstance(records, list):
                records = []
        except (json.JSONDecodeError, OSError):
            records = []
    else:
        records = []

    records.append(entry)
    if len(records) > cap:
        records = records[-cap:]

    tmp = log_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(records, fh, indent=2)
    os.replace(tmp, log_path)


# --------------------------------------------------------------------------- #
# Main class
# --------------------------------------------------------------------------- #

class DeFiProtocolYieldSourceQualityRater:
    """
    Rates DeFi protocol yield quality by analyzing yield source composition.

    Input dict keys:
        protocol_name  (str)
        yield_sources  (list of dicts):
            source       (str) — one of the 7 valid source types
            apy_pct      (float) — APY contribution from this source
            pct_of_total (float) — percentage of total APY from this source

    Output keys:
        protocol_name       (str)
        total_apy_pct       (float)
        quality_score       (float, 0-100)
        sustainable_yield_pct  (float) — Tier-1 sources only
        speculative_yield_pct  (float) — Tier-2 sources only
        quality_label       (str) — PREMIUM_YIELD / HIGH_QUALITY / MIXED_QUALITY /
                                    SPECULATIVE / UNSUSTAINABLE
        timestamp           (str, ISO-8601 UTC)

    Usage::

        rater = DeFiProtocolYieldSourceQualityRater()
        result = rater.rate({
            "protocol_name": "Uniswap V3",
            "yield_sources": [
                {"source": "trading_fees", "apy_pct": 8.5, "pct_of_total": 100.0},
            ],
        })
    """

    def __init__(self, log_path: str | None = None, log_cap: int = _LOG_CAP):
        self._log_path = log_path or _LOG_PATH
        self._log_cap = log_cap

    def rate(self, protocol: dict) -> dict:
        """
        Rate a single protocol's yield source quality.

        Parameters
        ----------
        protocol : dict
            Must contain ``protocol_name`` (str) and ``yield_sources`` (list).

        Returns
        -------
        dict
            See class docstring for output keys.
        """
        protocol_name = str(protocol.get("protocol_name", "unknown"))
        yield_sources = list(protocol.get("yield_sources", []))

        total_apy_pct, sustainable_yield_pct, speculative_yield_pct = compute_totals(
            yield_sources
        )
        score = compute_quality_score(yield_sources)
        label = quality_label(score)

        timestamp = datetime.datetime.utcnow().isoformat() + "Z"

        result = {
            "protocol_name": protocol_name,
            "total_apy_pct": total_apy_pct,
            "quality_score": score,
            "sustainable_yield_pct": sustainable_yield_pct,
            "speculative_yield_pct": speculative_yield_pct,
            "quality_label": label,
            "timestamp": timestamp,
        }

        log_entry = {
            "timestamp": timestamp,
            "protocol_name": protocol_name,
            "total_apy_pct": total_apy_pct,
            "quality_score": score,
            "quality_label": label,
            "source_count": len(yield_sources),
        }
        _atomic_log_append(log_entry, self._log_path, self._log_cap)

        return result
