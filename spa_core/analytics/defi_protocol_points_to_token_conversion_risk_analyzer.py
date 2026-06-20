"""
MP-1042  DeFiProtocolPointsToTokenConversionRiskAnalyzer
---------------------------------------------------------
Analyzes the risk when a DeFi protocol converts "points" earned by users into
actual tokens at TGE (Token Generation Event).

Points programs are used to bootstrap liquidity; but when TGE arrives the
token price is subject to dilution pressure from mercenary capital farming the
points.  This module quantifies that risk and returns an advisory verdict.

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (100 entries).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "points_token_conversion_risk_log.json",
)
_LOG_CAP = 100

LABEL_HIGH_VALUE_LOCKED = "HIGH_VALUE_LOCKED"
LABEL_REASONABLE_CONVERSION = "REASONABLE_CONVERSION"
LABEL_DILUTION_WARNING = "DILUTION_WARNING"
LABEL_FARM_AND_DUMP_RISK = "FARM_AND_DUMP_RISK"
LABEL_POINTS_WORTHLESS = "POINTS_WORTHLESS"

ALL_LABELS = (
    LABEL_HIGH_VALUE_LOCKED,
    LABEL_REASONABLE_CONVERSION,
    LABEL_DILUTION_WARNING,
    LABEL_FARM_AND_DUMP_RISK,
    LABEL_POINTS_WORTHLESS,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=100), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data: list = json.load(fh)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    atomic_save(data, str(abs_path))
# ---------------------------------------------------------------------------
# Sub-calculators
# ---------------------------------------------------------------------------

def _total_implied_value_usd(
    total_points_outstanding: float,
    implied_point_value_usd: float,
) -> float:
    """Total USD value promised to all point-holders."""
    return max(0.0, total_points_outstanding) * max(0.0, implied_point_value_usd)


def _implied_vs_tvl_ratio(
    total_implied_value_usd: float,
    current_tvl_usd: float,
) -> float:
    """Ratio of total implied payout to current TVL (proxy for over-commitment)."""
    if current_tvl_usd <= 0:
        return 10.0  # pathological: assume worst-case
    return total_implied_value_usd / current_tvl_usd


def _dilution_risk_score(
    total_points_outstanding: float,
    implied_point_value_usd: float,
    current_tvl_usd: float,
    points_farming_tvl_ratio: float,
    tge_date_days_away: float,
) -> float:
    """
    Dilution risk score 0-100 (higher = more risk).

    Components
    ----------
    c1 (45 %) – implied payout vs TVL: how over-committed are points promises?
                 ratio ≥ 4x → component saturates at 100.
    c2 (35 %) – farming TVL ratio: fraction of TVL that is mercenary capital.
    c3 (20 %) – TGE proximity: imminent TGE amplifies near-term dump risk.
                 0 days away → 100; ≥ 333 days away → 0.
    """
    implied = _total_implied_value_usd(total_points_outstanding, implied_point_value_usd)
    ratio = _implied_vs_tvl_ratio(implied, current_tvl_usd)
    c1 = min(100.0, ratio * 25.0)  # 4x → 100

    farming = max(0.0, min(1.0, points_farming_tvl_ratio))
    c2 = farming * 100.0

    tge_days = max(0.0, tge_date_days_away)
    c3 = max(0.0, 100.0 - tge_days * 0.30)

    score = c1 * 0.45 + c2 * 0.35 + c3 * 0.20
    return min(100.0, max(0.0, score))


def _lock_value_score(
    vesting_cliff_days: float,
    vesting_duration_days: float,
) -> float:
    """
    Lock value score 0-100 (higher = more tokens are locked = less dump pressure).

    cliff_score  (50 %) – 0 days cliff → 0; 180-day cliff → ~54; 365-day → ~100.
    dur_score    (50 %) – 0 days duration → 0; 1-year → 50; 2-years → ~100.
    """
    cliff = max(0.0, vesting_cliff_days)
    dur = max(0.0, vesting_duration_days)

    cliff_score = min(100.0, cliff * (100.0 / 365.0))
    dur_score = min(100.0, dur * (100.0 / 730.0))  # 2 years to saturate

    return (cliff_score * 0.50 + dur_score * 0.50)


def _expected_tge_dump_pct(
    points_farming_tvl_ratio: float,
    vesting_cliff_days: float,
    vesting_duration_days: float,
) -> float:
    """
    Expected % price impact at TGE from mercenary capital selling.
    Range: 0 – 95 %.

    Logic
    -----
    1. Mercenary fraction = points_farming_tvl_ratio (these holders are likely to sell).
    2. Vesting protection reduces immediate sell pressure:
       - With no cliff and no duration: 0 protection → full dump.
       - Cliff delays unlock; longer duration spreads unlock over time.
    """
    mercenary = max(0.0, min(1.0, points_farming_tvl_ratio))
    cliff = max(0.0, vesting_cliff_days)
    dur = max(0.0, vesting_duration_days)

    if cliff <= 0 and dur <= 0:
        # No vesting: 100 % available at TGE
        vesting_protection = 0.0
    elif cliff > 0:
        # Cliff delays the dump substantially
        cliff_prot = min(1.0, cliff / 365.0)
        dur_prot = min(1.0, dur / 730.0)
        vesting_protection = 0.60 * cliff_prot + 0.40 * dur_prot
    else:
        # Linear from TGE, no cliff: partial protection from spread-out unlock
        dur_prot = min(1.0, dur / 730.0)
        vesting_protection = 0.30 * dur_prot

    dump_pct = mercenary * 100.0 * (1.0 - vesting_protection)
    return min(95.0, max(0.0, dump_pct))


def _real_yield_after_tge_pct(
    total_points_outstanding: float,
    implied_point_value_usd: float,
    current_tvl_usd: float,
    expected_tge_dump_pct: float,
) -> float:
    """
    Estimated total yield % (vs TVL) after accounting for TGE token price dump.

    points_yield_pct = total_implied_value / current_tvl * 100
    real_yield       = points_yield_pct * (1 - dump_pct / 100)

    This is a total-return metric over the farming period (not annualised),
    because farming duration is not provided as an input.
    """
    if current_tvl_usd <= 0:
        return 0.0
    implied = _total_implied_value_usd(total_points_outstanding, implied_point_value_usd)
    points_yield_pct = implied / current_tvl_usd * 100.0
    real = points_yield_pct * (1.0 - max(0.0, min(100.0, expected_tge_dump_pct)) / 100.0)
    return max(0.0, real)


def _conversion_label(
    dilution_risk_score: float,
    lock_value_score: float,
    real_yield_after_tge_pct: float,
    implied_point_value_usd: float,
    points_farming_tvl_ratio: float,
    vesting_cliff_days: float,
) -> str:
    """
    Classify the protocol's points-to-token conversion profile.

    Priority (highest to lowest):
    1. POINTS_WORTHLESS   – implied value ≤ 0 or real yield ≤ 0
    2. FARM_AND_DUMP_RISK – dilution_risk_score ≥ 75 OR
                            (farming_ratio > 0.65 AND cliff < 30)
    3. DILUTION_WARNING   – dilution_risk_score ≥ 55
    4. HIGH_VALUE_LOCKED  – lock_value_score ≥ 65 AND dilution_risk_score < 40
    5. REASONABLE_CONVERSION – default
    """
    if implied_point_value_usd <= 0 or real_yield_after_tge_pct <= 0:
        return LABEL_POINTS_WORTHLESS

    if dilution_risk_score >= 75.0:
        return LABEL_FARM_AND_DUMP_RISK

    if points_farming_tvl_ratio > 0.65 and vesting_cliff_days < 30.0:
        return LABEL_FARM_AND_DUMP_RISK

    if dilution_risk_score >= 55.0:
        return LABEL_DILUTION_WARNING

    if lock_value_score >= 65.0 and dilution_risk_score < 40.0:
        return LABEL_HIGH_VALUE_LOCKED

    return LABEL_REASONABLE_CONVERSION


def _recommendations(
    label: str,
    dilution_risk_score: float,
    lock_value_score: float,
    expected_tge_dump_pct: float,
    real_yield_after_tge_pct: float,
    points_farming_tvl_ratio: float,
    vesting_cliff_days: float,
    vesting_duration_days: float,
) -> list:
    """Return advisory recommendation strings."""
    recs: list[str] = []

    if label == LABEL_POINTS_WORTHLESS:
        recs.append(
            "Implied point value is zero or real post-TGE yield is non-positive. "
            "Points carry no economic value under current assumptions."
        )
        return recs

    if label == LABEL_FARM_AND_DUMP_RISK:
        recs.append(
            f"High farm-and-dump risk: dilution score {dilution_risk_score:.0f}/100, "
            f"farming TVL ratio {points_farming_tvl_ratio:.0%}. "
            "Expect significant TVL outflow at TGE."
        )
        if vesting_cliff_days < 30:
            recs.append(
                f"Vesting cliff of {vesting_cliff_days:.0f} days provides minimal "
                "lock-up protection. Token unlock and immediate selling are likely."
            )
    elif label == LABEL_DILUTION_WARNING:
        recs.append(
            f"Dilution risk score {dilution_risk_score:.0f}/100. Implied points payout "
            "may suppress token price at TGE. Monitor TVL closely around TGE date."
        )
    elif label == LABEL_HIGH_VALUE_LOCKED:
        recs.append(
            f"Strong lock-up score {lock_value_score:.0f}/100 with "
            f"{vesting_cliff_days:.0f}-day cliff and {vesting_duration_days:.0f}-day "
            "total vesting. Selling pressure is well-contained."
        )
    else:  # REASONABLE_CONVERSION
        recs.append(
            "Conversion profile is balanced. Moderate dilution risk with adequate "
            "vesting protection."
        )

    if expected_tge_dump_pct > 30.0:
        recs.append(
            f"Expected TGE price impact ~{expected_tge_dump_pct:.0f}%. "
            "Size positions conservatively ahead of TGE."
        )

    if real_yield_after_tge_pct > 0:
        recs.append(
            f"Real post-TGE yield estimate: {real_yield_after_tge_pct:.1f}% "
            "(total return vs TVL, not annualised)."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(protocol: dict, config: dict | None = None) -> dict:
    """
    Analyse points-to-token conversion risk for a DeFi protocol.

    Parameters
    ----------
    protocol : dict
        Required keys:
        - protocol_name : str
        - total_points_outstanding : float  (total points across all users)
        - estimated_token_supply   : float  (total token supply, informational)
        - implied_point_value_usd  : float  (USD per point at current estimates)
        - tge_date_days_away       : float  (days until TGE; 0 = imminent)
        - vesting_cliff_days       : float  (days before any token unlock)
        - vesting_duration_days    : float  (total vesting period in days)
        - current_tvl_usd          : float  (current protocol TVL in USD)
        - points_farming_tvl_ratio : float  (0-1 fraction of TVL that is mercenary)
    config : dict, optional
        - log_path : str  (override default log path)

    Returns
    -------
    dict
        Full analysis result including all scores, metrics, label, recommendations.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)

    name = str(protocol.get("protocol_name", "UNKNOWN"))
    total_pts = float(protocol.get("total_points_outstanding", 0.0))
    est_supply = float(protocol.get("estimated_token_supply", 0.0))
    pt_value = float(protocol.get("implied_point_value_usd", 0.0))
    tge_days = float(protocol.get("tge_date_days_away", 0.0))
    cliff = float(protocol.get("vesting_cliff_days", 0.0))
    vest_dur = float(protocol.get("vesting_duration_days", 0.0))
    tvl = float(protocol.get("current_tvl_usd", 0.0))
    farming_ratio = float(protocol.get("points_farming_tvl_ratio", 0.0))

    implied_total = _total_implied_value_usd(total_pts, pt_value)
    vs_tvl = _implied_vs_tvl_ratio(implied_total, tvl)

    d_risk = _dilution_risk_score(total_pts, pt_value, tvl, farming_ratio, tge_days)
    l_score = _lock_value_score(cliff, vest_dur)
    dump_pct = _expected_tge_dump_pct(farming_ratio, cliff, vest_dur)
    real_yield = _real_yield_after_tge_pct(total_pts, pt_value, tvl, dump_pct)

    label = _conversion_label(
        d_risk, l_score, real_yield, pt_value, farming_ratio, cliff
    )
    recs = _recommendations(
        label, d_risk, l_score, dump_pct, real_yield, farming_ratio, cliff, vest_dur
    )

    result: dict[str, Any] = {
        "protocol_name": name,
        "total_points_outstanding": total_pts,
        "estimated_token_supply": est_supply,
        "implied_point_value_usd": pt_value,
        "tge_date_days_away": tge_days,
        "vesting_cliff_days": cliff,
        "vesting_duration_days": vest_dur,
        "current_tvl_usd": tvl,
        "points_farming_tvl_ratio": farming_ratio,
        # --- derived ---
        "total_implied_value_usd": implied_total,
        "implied_vs_tvl_ratio": vs_tvl,
        "dilution_risk_score": d_risk,
        "lock_value_score": l_score,
        "expected_tge_dump_pct": dump_pct,
        "real_yield_after_tge_pct": real_yield,
        "label": label,
        "recommendations": recs,
        "timestamp": time.time(),
    }

    try:
        _atomic_log(log_path, result)
    except Exception:
        pass  # advisory: never crash caller

    return result


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class DeFiProtocolPointsToTokenConversionRiskAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` function.

    >>> a = DeFiProtocolPointsToTokenConversionRiskAnalyzer()
    >>> r = a.analyze({"protocol_name": "TestProto", ...})
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def analyze(self, protocol: dict) -> dict:
        """Delegate to module-level ``analyze``."""
        return analyze(protocol, config=self._config)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo = {
        "protocol_name": "Hyperliquid",
        "total_points_outstanding": 5_000_000.0,
        "estimated_token_supply": 100_000_000.0,
        "implied_point_value_usd": 0.05,
        "tge_date_days_away": 60.0,
        "vesting_cliff_days": 0.0,
        "vesting_duration_days": 180.0,
        "current_tvl_usd": 500_000_000.0,
        "points_farming_tvl_ratio": 0.70,
    }

    import json as _json
    print(_json.dumps(analyze(_demo), indent=2, default=str))
    sys.exit(0)
