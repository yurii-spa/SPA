"""
MP-882 YieldBearingStablecoinComparator
Advisory/read-only analytics module.
Compares yield-bearing stablecoins across yield, safety, liquidity, and peg stability.

Data: data/yield_stablecoin_log.json (ring-buffer 100, atomic writes)
Pure stdlib only. LLM FORBIDDEN.
"""

import json
import os
import time
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_MIN_TVL_USD = 50_000_000.0
_DEFAULT_MAX_PEG_DEVIATION_PCT = 0.5
_LOG_FILE = "data/yield_stablecoin_log.json"
_RING_BUFFER_MAX = 100

_REDEMPTION_SCORES = {
    "INSTANT": 100,
    "QUEUED": 70,
    "TIMELOCKED": 40,
    "AMM_ONLY": 20,
}

_RISK_LABELS = [
    (80, "VERY_LOW_RISK"),
    (65, "LOW_RISK"),
    (50, "MODERATE_RISK"),
    (35, "HIGH_RISK"),
    (0,  "VERY_HIGH_RISK"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    """Clamp and convert to int."""
    return int(max(lo, min(hi, value)))


def _peg_stability_score(peg_deviation_30d_max_pct: float) -> int:
    """0-100: 100 - min(100, int(peg_deviation_30d_max_pct * 200))"""
    penalty = min(100, int(peg_deviation_30d_max_pct * 200))
    return 100 - penalty


def _liquidity_score(liquidity_depth_usd: float, tvl_usd: float) -> int:
    """0-100: min(100, int(liquidity_depth_usd / tvl_usd * 100)) if tvl>0 else 0"""
    if tvl_usd <= 0:
        return 0
    return _clamp(liquidity_depth_usd / tvl_usd * 100)


def _safety_score(collateral_ratio_pct: float) -> int:
    """0-100: min(100, max(0, int((collateral_ratio_pct - 100) * 2 + 50)))"""
    raw = (collateral_ratio_pct - 100.0) * 2 + 50.0
    return _clamp(raw)


def _redemption_score(redemption_mechanism: str) -> int:
    return _REDEMPTION_SCORES.get(redemption_mechanism.upper(), 0)


def _apy_norm(current_apy_pct: float) -> int:
    return _clamp(current_apy_pct * 10)


def _composite_score(
    apy_norm: int,
    peg_stability: int,
    safety: int,
    redemption: int,
    liquidity: int,
) -> int:
    raw = (
        apy_norm * 0.25
        + peg_stability * 0.30
        + safety * 0.25
        + redemption * 0.10
        + liquidity * 0.10
    )
    return _clamp(raw)


def _risk_label(composite: int) -> str:
    for threshold, label in _RISK_LABELS:
        if composite >= threshold:
            return label
    return "VERY_HIGH_RISK"


def _flags(
    tvl_usd: float,
    peg_deviation_30d_max_pct: float,
    collateral_ratio_pct: float,
    days_since_peg_incident: int,
    min_tvl_usd: float,
    max_peg_deviation_pct: float,
) -> list:
    result = []
    if tvl_usd < min_tvl_usd:
        result.append("LOW_TVL")
    if peg_deviation_30d_max_pct > max_peg_deviation_pct:
        result.append("PEG_INSTABILITY")
    if collateral_ratio_pct < 100:
        result.append("UNDERCOLLATERALIZED")
    if days_since_peg_incident < 90:
        result.append("RECENT_INCIDENT")
    return result


def _recommendation(
    risk_label: str,
    current_apy_pct: float,
    flag_list: list,
) -> str:
    if risk_label == "VERY_LOW_RISK":
        if current_apy_pct >= 5.0:
            return f"Excellent choice. {current_apy_pct:.1f}% APY with top safety profile."
        return "Safe but modest yield. Consider for capital preservation."
    if risk_label == "LOW_RISK":
        return f"Good risk-adjusted yield. {current_apy_pct:.1f}% APY, minor caveats."
    if risk_label == "MODERATE_RISK":
        flags_str = ", ".join(flag_list) if flag_list else "none"
        return f"Acceptable yield-risk tradeoff. Review flags: {flags_str}."
    # HIGH_RISK or VERY_HIGH_RISK
    flags_str = ", ".join(flag_list) if flag_list else "low composite score"
    return f"High risk. Avoid for large allocations. Flags: {flags_str}."


# ---------------------------------------------------------------------------
# Atomic log write
# ---------------------------------------------------------------------------

def _append_log(entry: dict, log_path: str = _LOG_FILE) -> None:
    """Append entry to ring-buffer JSON log (max 100 entries), atomic write."""
    try:
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        else:
            data = []
    except Exception:
        data = []

    data.append(entry)
    if len(data) > _RING_BUFFER_MAX:
        data = data[-_RING_BUFFER_MAX:]

    dir_name = os.path.dirname(log_path) or "."
    os.makedirs(dir_name, exist_ok=True)
    atomic_save(data, str(log_path))
# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(stablecoins: list, config: dict = None) -> dict:
    """
    Compare yield-bearing stablecoins across yield, safety, liquidity, and peg stability.

    Parameters
    ----------
    stablecoins : list of dict
        Each dict must contain:
            symbol, underlying, current_apy_pct, tvl_usd,
            peg_deviation_30d_max_pct, yield_source, redemption_mechanism,
            collateral_ratio_pct, days_since_peg_incident, liquidity_depth_usd
    config : dict, optional
        min_tvl_usd (default 50_000_000)
        max_peg_deviation_pct (default 0.5)

    Returns
    -------
    dict with keys: stablecoins, best_yield, safest, average_apy_pct, timestamp
    """
    if config is None:
        config = {}
    min_tvl_usd = float(config.get("min_tvl_usd", _DEFAULT_MIN_TVL_USD))
    max_peg_deviation_pct = float(config.get("max_peg_deviation_pct", _DEFAULT_MAX_PEG_DEVIATION_PCT))

    scored: list[dict] = []

    for s in stablecoins:
        symbol = str(s.get("symbol", ""))
        underlying = str(s.get("underlying", ""))
        current_apy_pct = float(s.get("current_apy_pct", 0.0))
        tvl_usd = float(s.get("tvl_usd", 0.0))
        peg_deviation_30d_max_pct = float(s.get("peg_deviation_30d_max_pct", 0.0))
        yield_source = str(s.get("yield_source", ""))
        redemption_mechanism = str(s.get("redemption_mechanism", ""))
        collateral_ratio_pct = float(s.get("collateral_ratio_pct", 100.0))
        days_since_peg_incident = int(s.get("days_since_peg_incident", 9999))
        liquidity_depth_usd = float(s.get("liquidity_depth_usd", 0.0))

        # Sub-scores
        peg_stab = _peg_stability_score(peg_deviation_30d_max_pct)
        liq_score = _liquidity_score(liquidity_depth_usd, tvl_usd)
        safe_score = _safety_score(collateral_ratio_pct)
        red_score = _redemption_score(redemption_mechanism)
        apy_n = _apy_norm(current_apy_pct)

        comp = _composite_score(apy_n, peg_stab, safe_score, red_score, liq_score)
        risk = _risk_label(comp)

        flag_list = _flags(
            tvl_usd,
            peg_deviation_30d_max_pct,
            collateral_ratio_pct,
            days_since_peg_incident,
            min_tvl_usd,
            max_peg_deviation_pct,
        )

        rec = _recommendation(risk, current_apy_pct, flag_list)

        scored.append({
            "symbol": symbol,
            "yield_source": yield_source,
            "current_apy_pct": current_apy_pct,
            "peg_stability_score": peg_stab,
            "liquidity_score": liq_score,
            "safety_score": safe_score,
            "redemption_score": red_score,
            "composite_score": comp,
            "risk_label": risk,
            "flags": flag_list,
            "recommendation": rec,
        })

    # Aggregates
    best_yield: str | None = None
    safest: str | None = None
    if scored:
        best_yield = max(scored, key=lambda x: x["current_apy_pct"])["symbol"]
        safest = max(scored, key=lambda x: x["composite_score"])["symbol"]

    avg_apy = (
        sum(x["current_apy_pct"] for x in scored) / len(scored)
        if scored else 0.0
    )

    result = {
        "stablecoins": scored,
        "best_yield": best_yield,
        "safest": safest,
        "average_apy_pct": avg_apy,
        "timestamp": time.time(),
    }

    # Log atomically
    try:
        _append_log({
            "timestamp": result["timestamp"],
            "stablecoin_count": len(scored),
            "best_yield": best_yield,
            "safest": safest,
            "average_apy_pct": avg_apy,
        })
    except Exception:
        pass

    return result
