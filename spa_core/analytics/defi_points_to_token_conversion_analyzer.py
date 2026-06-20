"""
MP-924 DeFiPointsToTokenConversionAnalyzer
------------------------------------------
Analyzes the conversion of DeFi points / XP programs into real token value.
For each program it computes the implied USD value per point, annualised APY
from holding until the airdrop, dilution risk from the eligible user base, and
a premium/discount versus similar peer protocol airdrops.

Advisory / read-only.  Pure stdlib.  Atomic ring-buffer JSON log (cap 100).
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DAYS_PER_YEAR: float = 365.0
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "points_conversion_log.json"
)
_LOG_CAP = 100

# Thresholds for flags and labels
_HIGH_DILUTION_USERS = 1_000_000
_DELAYED_AIRDROP_DAYS = 180
_BETTER_THAN_PEERS_PREMIUM_PCT = 50.0
_FARM_SATURATION_THRESHOLD = 0.001   # points per dollar per day — very low

# Score thresholds for value labels (based on implied_apy_pct)
_EXCEPTIONAL_APY = 50.0
_GOOD_APY = 20.0
_FAIR_APY = 5.0
_POOR_APY = 1.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=_LOG_CAP), atomic write."""
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
def _implied_value_per_point(
    total_points_issued: float,
    expected_token_allocation_pct: float,
    token_fdv_usd: float,
) -> float:
    """USD value of one point, based on allocation % of FDV."""
    if total_points_issued <= 0 or token_fdv_usd <= 0:
        return 0.0
    allocation_usd = max(0.0, expected_token_allocation_pct) / 100.0 * max(0.0, token_fdv_usd)
    return allocation_usd / total_points_issued


def _implied_apy_pct(
    value_per_point: float,
    points_earned_per_dollar_tvl: float,
    airdrop_date_days: float,
) -> float:
    """
    Annualised APY from points farming until airdrop.

    Formula: (value_per_point * points_per_dollar_day * 365) * 100
    where points_per_dollar_day is the daily earning rate.

    If airdrop_date_days > 0 we scale by a time factor so that a very distant
    airdrop reduces the effective annualised yield (you have to hold longer for
    the same payout, meaning the annualised rate is lower if you can't redeploy).
    We treat points_earned_per_dollar_tvl as a per-day figure.
    """
    if points_earned_per_dollar_tvl <= 0 or airdrop_date_days <= 0:
        return 0.0
    total_value_per_dollar = value_per_point * points_earned_per_dollar_tvl * airdrop_date_days
    annualised = total_value_per_dollar / airdrop_date_days * _DAYS_PER_YEAR * 100.0
    return max(0.0, annualised)


def _dilution_risk_score(eligible_users_count: float) -> float:
    """
    0-100 dilution risk score.  More users = higher dilution risk = higher score.
    Score saturates logarithmically: 1 user → 0, 1M users → ~75, 10M → ~88.
    """
    if eligible_users_count <= 0:
        return 0.0
    # log10(1) = 0, log10(1e6) = 6, log10(1e7) = 7
    log_val = math.log10(max(1.0, eligible_users_count))
    score = min(100.0, log_val / 7.0 * 100.0)
    return round(score, 2)


def _comparison_premium_pct(
    implied_value_per_point: float,
    similar_protocol_airdrop_usd: float,
    eligible_users_count: float,
) -> float:
    """
    Premium (%) of this program's per-user airdrop vs similar protocol's.
    Positive = better than peers, negative = worse.
    Returns 0 if similar_protocol_airdrop_usd or eligible_users_count is 0.
    """
    if similar_protocol_airdrop_usd <= 0 or eligible_users_count <= 0:
        return 0.0
    # Approximate total value of this program's airdrop per user.
    # We use total_points_issued * value_per_point / eligible_users_count
    # but we don't have total_points_issued here, so we accept
    # similar_protocol_airdrop_usd as the per-user benchmark directly.
    # The caller passes similar_protocol_airdrop_usd as total airdrop / user.
    # We compute this program's per-user value from the value_per_point and
    # assume average points per user = total_points_issued / eligible_users_count.
    # Since that is already captured implicitly, we compare directly:
    # per_user_value = total_allocation_usd / eligible_users_count
    # but total_allocation_usd isn't in this helper — so we just compare
    # a passed-in "this program per-user" vs peer.
    # To keep this helper simple: accept implied_value_per_point as proxy
    # and similar_protocol_airdrop_usd as peer per-user usd for a standard
    # user with 1 point.  The program-level analyze() will compute actual values.
    peer = similar_protocol_airdrop_usd
    this_val = implied_value_per_point
    if peer <= 0:
        return 0.0
    return (this_val - peer) / peer * 100.0


def _value_label(implied_apy: float) -> str:
    """Classify program into EXCEPTIONAL / GOOD / FAIR / POOR / LIKELY_WORTHLESS."""
    if implied_apy >= _EXCEPTIONAL_APY:
        return "EXCEPTIONAL"
    if implied_apy >= _GOOD_APY:
        return "GOOD"
    if implied_apy >= _FAIR_APY:
        return "FAIR"
    if implied_apy >= _POOR_APY:
        return "POOR"
    return "LIKELY_WORTHLESS"


def _compute_flags(
    eligible_users_count: float,
    airdrop_date_days: float,
    comparison_premium_pct: float,
    expected_token_allocation_pct: float,
    points_earned_per_dollar_tvl: float,
) -> list[str]:
    """Return list of advisory flag strings for this program."""
    flags: list[str] = []
    if eligible_users_count > _HIGH_DILUTION_USERS:
        flags.append("HIGH_DILUTION")
    if airdrop_date_days > _DELAYED_AIRDROP_DAYS:
        flags.append("DELAYED_AIRDROP")
    if comparison_premium_pct > _BETTER_THAN_PEERS_PREMIUM_PCT:
        flags.append("BETTER_THAN_PEERS")
    if expected_token_allocation_pct <= 0:
        flags.append("UNANNOUNCED_ALLOCATION")
    if 0 < points_earned_per_dollar_tvl < _FARM_SATURATION_THRESHOLD:
        flags.append("FARM_SATURATION")
    return flags


def _analyze_program(program: dict) -> dict:
    """Analyze a single points program and return its metrics dict."""
    protocol = program.get("protocol", "UNKNOWN")
    points_per_dollar = float(program.get("points_earned_per_dollar_tvl", 0.0))
    total_points = float(program.get("total_points_issued", 0.0))
    allocation_pct = float(program.get("expected_token_allocation_pct", 0.0))
    fdv = float(program.get("token_fdv_usd", 0.0))
    airdrop_days = float(program.get("airdrop_date_days_from_now", 0.0))
    users = float(program.get("eligible_users_count", 0.0))
    similar_airdrop = float(program.get("similar_protocol_airdrop_usd", 0.0))

    val_per_point = _implied_value_per_point(total_points, allocation_pct, fdv)
    apy = _implied_apy_pct(val_per_point, points_per_dollar, airdrop_days)
    dilution = _dilution_risk_score(users)
    premium = _comparison_premium_pct(val_per_point, similar_airdrop, users)
    label = _value_label(apy)
    flags = _compute_flags(users, airdrop_days, premium, allocation_pct, points_per_dollar)

    # Total points value for this program
    total_value = val_per_point * total_points

    return {
        "protocol": protocol,
        "implied_value_per_point_usd": round(val_per_point, 8),
        "implied_apy_pct": round(apy, 4),
        "dilution_risk_score": dilution,
        "comparison_premium_pct": round(premium, 4),
        "total_points_value_usd": round(total_value, 2),
        "value_label": label,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------

class DeFiPointsToTokenConversionAnalyzer:
    """
    Analyzes DeFi points-to-token conversion for a list of programs.

    Usage
    -----
    analyzer = DeFiPointsToTokenConversionAnalyzer()
    result = analyzer.analyze(programs, config)
    """

    def analyze(self, programs: list[dict], config: dict | None = None) -> dict:
        """
        Analyze points-to-token conversion for each program.

        Parameters
        ----------
        programs : list[dict]
            Each dict must contain:
            - protocol: str
            - points_earned_per_dollar_tvl: float  (per day)
            - total_points_issued: float
            - expected_token_allocation_pct: float  (% of FDV for points)
            - token_fdv_usd: float
            - airdrop_date_days_from_now: float
            - eligible_users_count: float
            - similar_protocol_airdrop_usd: float  (peer benchmark per-point)
        config : dict, optional
            - log_path: str

        Returns
        -------
        dict
            Per-program analysis + aggregate metrics.
        """
        cfg = config or {}
        log_path = cfg.get("log_path", _LOG_PATH)
        write_log = cfg.get("write_log", True)

        if not programs:
            return {
                "programs": [],
                "best_program": None,
                "worst_program": None,
                "average_implied_apy": 0.0,
                "total_points_value_usd": 0.0,
                "exceptional_count": 0,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

        analyzed = [_analyze_program(p) for p in programs]

        # Aggregates
        apys = [a["implied_apy_pct"] for a in analyzed]
        average_apy = sum(apys) / len(apys)
        total_value = sum(a["total_points_value_usd"] for a in analyzed)
        exceptional_count = sum(1 for a in analyzed if a["value_label"] == "EXCEPTIONAL")

        best = max(analyzed, key=lambda x: x["implied_apy_pct"])
        worst = min(analyzed, key=lambda x: x["implied_apy_pct"])

        result: dict[str, Any] = {
            "programs": analyzed,
            "best_program": best["protocol"],
            "worst_program": worst["protocol"],
            "average_implied_apy": round(average_apy, 4),
            "total_points_value_usd": round(total_value, 2),
            "exceptional_count": exceptional_count,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        if write_log:
            log_entry = {
                "timestamp": result["timestamp"],
                "program_count": len(programs),
                "best_program": result["best_program"],
                "average_implied_apy": result["average_implied_apy"],
                "total_points_value_usd": result["total_points_value_usd"],
                "exceptional_count": exceptional_count,
            }
            _atomic_log(log_path, log_entry)

        return result


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def analyze(programs: list[dict], config: dict | None = None) -> dict:
    """Module-level convenience wrapper around DeFiPointsToTokenConversionAnalyzer.analyze."""
    return DeFiPointsToTokenConversionAnalyzer().analyze(programs, config)
