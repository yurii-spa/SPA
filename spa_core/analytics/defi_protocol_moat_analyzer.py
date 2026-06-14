"""
MP-944 DeFiProtocolMoatAnalyzer
================================
Advisory-only analytics module. Pure stdlib. No external dependencies.

Analyzes competitive advantages (economic moats) of DeFi protocols:
scoring switching costs, network effects, brand recognition, protocol-owned
liquidity, and longevity to derive moat strength, competitive durability,
market position, and flag key competitive signals.

Data log: data/protocol_moat_log.json (ring-buffer 100 entries, atomic write)

Usage:
    from spa_core.analytics.defi_protocol_moat_analyzer import DeFiProtocolMoatAnalyzer
    result = DeFiProtocolMoatAnalyzer().analyze(protocols, config)
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_PATH_DEFAULT = "data/protocol_moat_log.json"
LOG_CAP = 100

# Moat strength score weights
WEIGHT_SWITCHING_COST = 0.30
WEIGHT_NETWORK_EFFECT = 0.30
WEIGHT_BRAND = 0.20
WEIGHT_POL = 0.10
WEIGHT_LONGEVITY = 0.10

# Longevity: years_operating * 10, capped at 100 (10 yrs = max)
LONGEVITY_YEARS_CAP = 10.0
LONGEVITY_PER_YEAR = 10.0

# Competitive durability thresholds
WIDE_MOAT_THRESHOLD = 65.0
NARROW_MOAT_THRESHOLD = 35.0

# Market position thresholds (market_share_pct)
DOMINANT_SHARE = 40.0
STRONG_SHARE = 25.0
COMPETITIVE_SHARE = 10.0
NICHE_SHARE = 5.0

# Flag thresholds
FLAG_DOMINANT_SHARE = 40.0
FLAG_HIGH_SWITCHING_COST = 70.0
FLAG_STRONG_NETWORK_EFFECT = 70.0
FLAG_POL = 50.0
FLAG_WIDELY_FORKED = 10  # clone_count > 10

# LOSING_MOAT: high clones + weak market share
LOSING_MOAT_CLONE_THRESHOLD = 10
LOSING_MOAT_SHARE_THRESHOLD = 20.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp a value to [lo, hi]."""
    return max(lo, min(hi, float(value)))


def _compute_moat_strength(protocol: dict) -> float:
    """
    Weighted moat strength score 0-100:
      switching_cost 30% + network_effect 30% + brand 20% + pol 10% + longevity 10%
    """
    switching = _clamp(float(protocol.get("switching_cost_score", 0)))
    network = _clamp(float(protocol.get("network_effect_score", 0)))
    brand = _clamp(float(protocol.get("brand_recognition_score", 0)))
    pol_pct = _clamp(float(protocol.get("protocol_owned_liquidity_pct", 0)))
    years = float(protocol.get("years_operating", 0))
    longevity = _clamp(min(years * LONGEVITY_PER_YEAR, LONGEVITY_YEARS_CAP * LONGEVITY_PER_YEAR))

    return (
        switching * WEIGHT_SWITCHING_COST
        + network * WEIGHT_NETWORK_EFFECT
        + brand * WEIGHT_BRAND
        + pol_pct * WEIGHT_POL
        + longevity * WEIGHT_LONGEVITY
    )


def _competitive_durability(score: float) -> str:
    """WIDE / NARROW / NONE based on moat_strength_score."""
    if score >= WIDE_MOAT_THRESHOLD:
        return "WIDE"
    elif score >= NARROW_MOAT_THRESHOLD:
        return "NARROW"
    else:
        return "NONE"


def _market_position(market_share_pct: float) -> str:
    """DOMINANT / STRONG / COMPETITIVE / NICHE / VULNERABLE."""
    if market_share_pct > DOMINANT_SHARE:
        return "DOMINANT"
    elif market_share_pct >= STRONG_SHARE:
        return "STRONG"
    elif market_share_pct >= COMPETITIVE_SHARE:
        return "COMPETITIVE"
    elif market_share_pct >= NICHE_SHARE:
        return "NICHE"
    else:
        return "VULNERABLE"


def _moat_label(score: float, clone_count: int, market_share_pct: float) -> str:
    """
    LOSING_MOAT: high clone_count + weak market share (being eaten by forks).
    WIDE_MOAT: score >= 65.
    NARROW_MOAT: 35 <= score < 65.
    NO_MOAT: score < 35.
    """
    if clone_count > LOSING_MOAT_CLONE_THRESHOLD and market_share_pct < LOSING_MOAT_SHARE_THRESHOLD:
        return "LOSING_MOAT"
    if score >= WIDE_MOAT_THRESHOLD:
        return "WIDE_MOAT"
    elif score >= NARROW_MOAT_THRESHOLD:
        return "NARROW_MOAT"
    else:
        return "NO_MOAT"


def _compute_flags(protocol: dict) -> List[str]:
    """Compute list of flag strings for a protocol."""
    flags: List[str] = []
    if float(protocol.get("market_share_pct", 0)) > FLAG_DOMINANT_SHARE:
        flags.append("DOMINANT_MARKET_SHARE")
    if float(protocol.get("switching_cost_score", 0)) > FLAG_HIGH_SWITCHING_COST:
        flags.append("HIGH_SWITCHING_COST")
    if float(protocol.get("network_effect_score", 0)) > FLAG_STRONG_NETWORK_EFFECT:
        flags.append("STRONG_NETWORK_EFFECT")
    if float(protocol.get("protocol_owned_liquidity_pct", 0)) > FLAG_POL:
        flags.append("PROTOCOL_OWNED_LIQUIDITY")
    if int(protocol.get("clone_count", 0)) > FLAG_WIDELY_FORKED:
        flags.append("WIDELY_FORKED")
    return flags


def _analyze_single(protocol: dict) -> dict:
    """Analyze one protocol dict and return enriched result dict."""
    name = str(protocol.get("name", "unknown"))
    category = str(protocol.get("category", "unknown"))
    tvl_usd = float(protocol.get("tvl_usd", 0))
    market_share_pct = float(protocol.get("market_share_pct", 0))
    switching_cost_score = _clamp(float(protocol.get("switching_cost_score", 0)))
    network_effect_score = _clamp(float(protocol.get("network_effect_score", 0)))
    brand_recognition_score = _clamp(float(protocol.get("brand_recognition_score", 0)))
    pol_pct = _clamp(float(protocol.get("protocol_owned_liquidity_pct", 0)))
    integrations_count = int(protocol.get("integrations_count", 0))
    years_operating = float(protocol.get("years_operating", 0))
    clone_count = int(protocol.get("clone_count", 0))

    strength = _compute_moat_strength(protocol)
    durability = _competitive_durability(strength)
    position = _market_position(market_share_pct)
    label = _moat_label(strength, clone_count, market_share_pct)
    flags = _compute_flags(protocol)

    return {
        "name": name,
        "category": category,
        "tvl_usd": tvl_usd,
        "market_share_pct": market_share_pct,
        "switching_cost_score": switching_cost_score,
        "network_effect_score": network_effect_score,
        "brand_recognition_score": brand_recognition_score,
        "protocol_owned_liquidity_pct": pol_pct,
        "integrations_count": integrations_count,
        "years_operating": years_operating,
        "clone_count": clone_count,
        "moat_strength_score": round(strength, 4),
        "competitive_durability": durability,
        "market_position": position,
        "moat_label": label,
        "flags": flags,
    }


def _atomic_write(path: str, data: dict) -> None:
    """Write JSON atomically via tmp-file + os.replace."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def _append_log(result: dict, log_path: str) -> None:
    """Append a summary entry to the ring-buffer log (cap=100). Non-fatal."""
    try:
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as fh:
                log = json.load(fh)
        else:
            log = {"entries": []}

        entry = {
            "timestamp": result["timestamp"],
            "protocol_count": result["protocol_count"],
            "average_moat_strength": result["aggregates"]["average_moat_strength"],
            "wide_moat_count": result["aggregates"]["wide_moat_count"],
            "no_moat_count": result["aggregates"]["no_moat_count"],
            "widest_moat": result["aggregates"]["widest_moat"],
        }
        entries = log.get("entries", [])
        entries.append(entry)
        if len(entries) > LOG_CAP:
            entries = entries[-LOG_CAP:]
        log["entries"] = entries
        log["last_updated"] = result["timestamp"]

        _atomic_write(log_path, log)
    except Exception:
        pass  # Logging failures are non-fatal


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiProtocolMoatAnalyzer:
    """
    Analyzes economic moats of DeFi protocols.

    Args:
        data_dir: Optional directory for log files (overrides default).
    """

    def __init__(self, data_dir: Optional[str] = None):
        self._data_dir = data_dir

    def _log_path(self) -> str:
        if self._data_dir:
            return os.path.join(self._data_dir, "protocol_moat_log.json")
        return LOG_PATH_DEFAULT

    def analyze(self, protocols: List[Dict[str, Any]], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Analyze competitive moats for a list of DeFi protocols.

        Each protocol dict may contain:
            name, category, tvl_usd, market_share_pct,
            switching_cost_score (0-100), network_effect_score (0-100),
            brand_recognition_score (0-100), protocol_owned_liquidity_pct,
            integrations_count, years_operating, clone_count

        Returns:
            dict with keys:
                timestamp, protocol_count, protocols (list of enriched dicts),
                aggregates (widest_moat, narrowest_moat, average_moat_strength,
                            wide_moat_count, no_moat_count)
        """
        if config is None:
            config = {}

        timestamp = datetime.now(timezone.utc).isoformat()

        if not protocols:
            result = {
                "timestamp": timestamp,
                "protocol_count": 0,
                "protocols": [],
                "aggregates": {
                    "widest_moat": None,
                    "narrowest_moat": None,
                    "average_moat_strength": 0.0,
                    "wide_moat_count": 0,
                    "no_moat_count": 0,
                },
            }
            _append_log(result, self._log_path())
            return result

        analyzed = [_analyze_single(p) for p in protocols]

        scores = [a["moat_strength_score"] for a in analyzed]
        avg_strength = sum(scores) / len(scores)
        widest = max(analyzed, key=lambda x: x["moat_strength_score"])
        narrowest = min(analyzed, key=lambda x: x["moat_strength_score"])
        wide_count = sum(1 for a in analyzed if a["moat_label"] == "WIDE_MOAT")
        no_count = sum(1 for a in analyzed if a["moat_label"] in ("NO_MOAT", "LOSING_MOAT"))

        result = {
            "timestamp": timestamp,
            "protocol_count": len(analyzed),
            "protocols": analyzed,
            "aggregates": {
                "widest_moat": widest["name"],
                "narrowest_moat": narrowest["name"],
                "average_moat_strength": round(avg_strength, 4),
                "wide_moat_count": wide_count,
                "no_moat_count": no_count,
            },
        }

        _append_log(result, self._log_path())
        return result
