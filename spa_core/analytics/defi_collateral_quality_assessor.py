"""
MP-920 DeFiCollateralQualityAssessor
====================================
Advisory-only, read-only analytics module.
Assesses the quality of collateral in DeFi lending protocols.

Input per collateral:
  token, protocol, ltv_pct, liquidation_bonus_pct, market_cap_usd,
  daily_volume_usd, price_30d_volatility_pct, correlation_to_eth (0-1),
  centralization_risk (0-1), depeg_incidents_count, oracle_type
  (chainlink/uniswap_twap/band/custom)

Computes per collateral:
  - liquidity_adequacy_score (0-100): vol/mcap ratio vs 2% threshold
  - volatility_penalty       (0-100): higher annualized vol -> higher penalty
  - oracle_trust_score       (0-100): based on oracle type
  - composite_quality_score  (0-100): weighted combination
  - quality_label: EXCELLENT / GOOD / ADEQUATE / POOR / UNSUITABLE
  - flags: HIGH_VOLATILITY, LOW_LIQUIDITY, CENTRALIZED_RISK,
           CUSTOM_ORACLE, DEPEG_HISTORY

Aggregates:
  best_collateral, worst_collateral, average_quality,
  unsuitable_count, excellent_count, total_count

Output file: data/collateral_quality_log.json (ring-buffer, cap 100)
Pure Python stdlib only. Atomic writes (tmp + os.replace).
"""

import json
import os
import time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_CAP = 100
DEFAULT_LOG_PATH = "data/collateral_quality_log.json"

ORACLE_TRUST_SCORES: dict = {
    "chainlink":    90.0,
    "uniswap_twap": 70.0,
    "band":         60.0,
    "custom":       20.0,
}
ORACLE_TRUST_DEFAULT = 10.0

LOW_LIQUIDITY_THRESHOLD = 0.02        # vol/mcap ratio threshold (2 %)
HIGH_VOLATILITY_THRESHOLD = 60.0      # annualized % threshold
CENTRALIZATION_RISK_THRESHOLD = 0.7   # 0-1 scale

QUALITY_THRESHOLDS = [
    (80.0, "EXCELLENT"),
    (60.0, "GOOD"),
    (40.0, "ADEQUATE"),
    (20.0, "POOR"),
]


# ---------------------------------------------------------------------------
# Core helper functions
# ---------------------------------------------------------------------------

def _liquidity_adequacy_score(daily_volume_usd: float, market_cap_usd: float) -> float:
    """
    Score 0-100 based on daily volume / market cap ratio.
    At ratio >= 2 % (LOW_LIQUIDITY_THRESHOLD) -> score = 100.
    score = min(100, ratio / 0.02 * 100)
    """
    if market_cap_usd <= 0:
        return 0.0
    ratio = daily_volume_usd / market_cap_usd
    return max(0.0, min(100.0, ratio / LOW_LIQUIDITY_THRESHOLD * 100.0))


def _volatility_penalty(price_30d_volatility_pct: float) -> float:
    """
    Penalty 0-100.  penalty = min(100, volatility_pct).
    Higher annualized volatility -> higher penalty.
    """
    return max(0.0, min(100.0, price_30d_volatility_pct))


def _oracle_trust_score(oracle_type: str) -> float:
    """Trust score 0-100 based on oracle type string."""
    key = (oracle_type or "").strip().lower()
    return ORACLE_TRUST_SCORES.get(key, ORACLE_TRUST_DEFAULT)


def _composite_quality_score(
    liquidity_score: float,
    volatility_pen: float,
    oracle_score: float,
    centralization_risk: float,
    depeg_incidents: int,
) -> float:
    """
    Composite quality score 0-100:
      = oracle_score * 0.50
        + liquidity_score * 0.50
        - volatility_pen * 0.15
        - centralization_risk * 100 * 0.10
        - min(depeg_incidents * 5, 10)
    Clamped to [0, 100].
    With perfect chainlink oracle (90) + full liquidity (100) + zero vol/risk:
    score = 45 + 50 = 95 -> EXCELLENT.
    """
    raw = (
        oracle_score * 0.50
        + liquidity_score * 0.50
        - volatility_pen * 0.15
        - centralization_risk * 100.0 * 0.10
        - min(float(depeg_incidents) * 5.0, 10.0)
    )
    return max(0.0, min(100.0, raw))


def _quality_label(composite_score: float) -> str:
    """Map composite score to quality label."""
    for threshold, label in QUALITY_THRESHOLDS:
        if composite_score >= threshold:
            return label
    return "UNSUITABLE"


def _compute_flags(
    daily_volume_usd: float,
    market_cap_usd: float,
    price_30d_volatility_pct: float,
    centralization_risk: float,
    oracle_type: str,
    depeg_incidents_count: int,
) -> list:
    """Return list of applicable flag strings."""
    flags = []
    if price_30d_volatility_pct > HIGH_VOLATILITY_THRESHOLD:
        flags.append("HIGH_VOLATILITY")
    if market_cap_usd > 0 and (daily_volume_usd / market_cap_usd) < LOW_LIQUIDITY_THRESHOLD:
        flags.append("LOW_LIQUIDITY")
    elif market_cap_usd <= 0:
        # zero market cap means we cannot assess liquidity – flag as LOW_LIQUIDITY
        flags.append("LOW_LIQUIDITY")
    if centralization_risk > CENTRALIZATION_RISK_THRESHOLD:
        flags.append("CENTRALIZED_RISK")
    if (oracle_type or "").strip().lower() == "custom":
        flags.append("CUSTOM_ORACLE")
    if depeg_incidents_count > 0:
        flags.append("DEPEG_HISTORY")
    return flags


# ---------------------------------------------------------------------------
# Per-collateral assessment
# ---------------------------------------------------------------------------

def _assess_single(collateral: dict, config: dict) -> dict:
    """Assess a single collateral dict.  Returns enriched result dict."""
    token                   = str(collateral.get("token",                  "UNKNOWN"))
    protocol                = str(collateral.get("protocol",               "UNKNOWN"))
    ltv_pct                 = float(collateral.get("ltv_pct",              0.0))
    liquidation_bonus_pct   = float(collateral.get("liquidation_bonus_pct", 0.0))
    market_cap_usd          = float(collateral.get("market_cap_usd",       0.0))
    daily_volume_usd        = float(collateral.get("daily_volume_usd",     0.0))
    price_30d_volatility_pct = float(collateral.get("price_30d_volatility_pct", 0.0))
    correlation_to_eth      = float(collateral.get("correlation_to_eth",   0.0))
    centralization_risk     = float(collateral.get("centralization_risk",  0.0))
    depeg_incidents_count   = int(collateral.get("depeg_incidents_count",  0))
    oracle_type             = str(collateral.get("oracle_type",            "custom"))

    liq_score   = _liquidity_adequacy_score(daily_volume_usd, market_cap_usd)
    vol_pen     = _volatility_penalty(price_30d_volatility_pct)
    oracle_sc   = _oracle_trust_score(oracle_type)
    comp_score  = _composite_quality_score(
        liq_score, vol_pen, oracle_sc, centralization_risk, depeg_incidents_count
    )
    label = _quality_label(comp_score)
    flags = _compute_flags(
        daily_volume_usd, market_cap_usd, price_30d_volatility_pct,
        centralization_risk, oracle_type, depeg_incidents_count,
    )

    return {
        "token":                       token,
        "protocol":                    protocol,
        "ltv_pct":                     ltv_pct,
        "liquidation_bonus_pct":       liquidation_bonus_pct,
        "market_cap_usd":              market_cap_usd,
        "daily_volume_usd":            daily_volume_usd,
        "price_30d_volatility_pct":    price_30d_volatility_pct,
        "correlation_to_eth":          correlation_to_eth,
        "centralization_risk":         centralization_risk,
        "depeg_incidents_count":       depeg_incidents_count,
        "oracle_type":                 oracle_type,
        "liquidity_adequacy_score":    round(liq_score, 4),
        "volatility_penalty":          round(vol_pen, 4),
        "oracle_trust_score":          round(oracle_sc, 4),
        "composite_quality_score":     round(comp_score, 4),
        "quality_label":               label,
        "flags":                       flags,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assess(collaterals: list, config: dict) -> dict:
    """
    Assess quality of a list of collateral dicts.

    Returns:
        dict with keys:
            assessments  – list of per-collateral result dicts
            aggregate    – summary stats
            timestamp    – Unix time of assessment
    """
    if not collaterals:
        return {
            "assessments": [],
            "aggregate": {
                "best_collateral":  None,
                "worst_collateral": None,
                "average_quality":  0.0,
                "unsuitable_count": 0,
                "excellent_count":  0,
                "total_count":      0,
            },
            "timestamp": time.time(),
        }

    assessments = [_assess_single(c, config) for c in collaterals]
    scores = [a["composite_quality_score"] for a in assessments]

    best_idx  = scores.index(max(scores))
    worst_idx = scores.index(min(scores))

    unsuitable_count = sum(1 for a in assessments if a["quality_label"] == "UNSUITABLE")
    excellent_count  = sum(1 for a in assessments if a["quality_label"] == "EXCELLENT")
    average_quality  = sum(scores) / len(scores)

    return {
        "assessments": assessments,
        "aggregate": {
            "best_collateral":  assessments[best_idx]["token"],
            "worst_collateral": assessments[worst_idx]["token"],
            "average_quality":  round(average_quality, 4),
            "unsuitable_count": unsuitable_count,
            "excellent_count":  excellent_count,
            "total_count":      len(assessments),
        },
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Ring-buffer log persistence
# ---------------------------------------------------------------------------

def append_log(result: dict, log_path: str = DEFAULT_LOG_PATH) -> None:
    """Append *result* to ring-buffer JSON log (cap LOG_CAP). Atomic write."""
    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    existing: list = []
    if os.path.exists(log_path):
        try:
            with open(log_path) as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(result)
    existing = existing[-LOG_CAP:]

    tmp = log_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(existing, fh, indent=2)
    os.replace(tmp, log_path)


def run(collaterals: list, config: dict, log_path: str = DEFAULT_LOG_PATH) -> dict:
    """Assess collaterals and persist result to log. Returns assessment result."""
    result = assess(collaterals, config)
    append_log(result, log_path)
    return result
