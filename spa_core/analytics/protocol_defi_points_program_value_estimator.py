"""
MP-1101: ProtocolDeFiPointsProgramValueEstimator
=================================================
Advisory-only analytics module.

Estimates the real dollar value of DeFi protocol points programs. Points are
pre-token incentives whose value depends on total supply dilution, airdrop %
to depositors, and TGE price assumptions.

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/points_program_value_log.json.
Atomic writes: tmp + os.replace.
"""

import json
import os
import time
from typing import Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_FILENAME = "points_program_value_log.json"
LOG_MAX_ENTRIES = 100

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_DEFAULT_DATA_DIR = os.path.join(_REPO_ROOT, "data")


# ---------------------------------------------------------------------------
# Internal computation helpers
# ---------------------------------------------------------------------------

def _compute_total_points_at_tge(
    points_earned_per_day: float,
    days_until_tge: int,
) -> float:
    """Total points user will have accumulated by TGE date."""
    if days_until_tge <= 0:
        return 0.0
    return points_earned_per_day * float(days_until_tge)


def _compute_user_points_share_pct(
    total_points_at_tge: float,
    total_protocol_points_issued: float,
) -> float:
    """
    User's share of total protocol points as a percentage.
    Returns 0.0 if total_protocol_points_issued is zero or negative.
    """
    if total_protocol_points_issued <= 0:
        return 0.0
    return total_points_at_tge / total_protocol_points_issued * 100.0


def _compute_tokens_received(
    user_points_share_pct: float,
    airdrop_allocation_pct: float,
    total_token_supply: float,
) -> float:
    """
    Tokens allocated to the user.
    = (user_share / 100) × (airdrop_alloc / 100) × total_supply
    """
    if total_token_supply <= 0:
        return 0.0
    return (user_points_share_pct / 100.0) * (airdrop_allocation_pct / 100.0) * total_token_supply


def _compute_scenario_value(tokens_received: float, tge_price_usd: float) -> float:
    """Dollar value = tokens × price."""
    if tokens_received <= 0 or tge_price_usd <= 0:
        return 0.0
    return tokens_received * tge_price_usd


def _compute_implied_apy(
    base_value_usd: float,
    position_size_usd: float,
    days_until_tge: int,
) -> float:
    """
    Implied APY from airdrop, annualized from holding period.
    = (base_value / position_size) × (365 / days_until_tge) × 100
    Returns 0.0 if position_size or days_until_tge is zero/negative.
    """
    if position_size_usd <= 0 or days_until_tge <= 0:
        return 0.0
    return (base_value_usd / position_size_usd) * (365.0 / float(days_until_tge)) * 100.0


def _classify_points(implied_apy_pct: float) -> str:
    """
    Classify the airdrop value by implied APY.

    > 100%  → EXCEPTIONAL_AIRDROP
    30-100% → GOOD_AIRDROP
    10-30%  → MODEST_AIRDROP
    2-10%   → MINIMAL_VALUE
    < 2%    → DILUTED_OUT
    """
    if implied_apy_pct > 100.0:
        return "EXCEPTIONAL_AIRDROP"
    elif implied_apy_pct >= 30.0:
        return "GOOD_AIRDROP"
    elif implied_apy_pct >= 10.0:
        return "MODEST_AIRDROP"
    elif implied_apy_pct >= 2.0:
        return "MINIMAL_VALUE"
    else:
        return "DILUTED_OUT"


# ---------------------------------------------------------------------------
# Atomic I/O helpers
# ---------------------------------------------------------------------------

def _atomic_write_json(data, path: str, data_dir: str) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(path, str(data))
def _read_log(log_path: str) -> list:
    """Read existing log or return empty list."""
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _append_log(entry: dict, data_dir: str) -> None:
    """Append entry to ring-buffer log (max LOG_MAX_ENTRIES). Atomic write."""
    log_path = os.path.join(data_dir, LOG_FILENAME)
    entries = _read_log(log_path)
    entries.append(entry)
    if len(entries) > LOG_MAX_ENTRIES:
        entries = entries[-LOG_MAX_ENTRIES:]
    _atomic_write_json(entries, log_path, data_dir)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def estimate(
    points_earned_per_day: float,
    days_until_tge: int,
    total_protocol_points_issued: float,
    airdrop_allocation_pct: float,
    total_token_supply: float,
    conservative_tge_price_usd: float,
    base_tge_price_usd: float,
    bull_tge_price_usd: float,
    position_size_usd: float,
    protocol_name: str,
) -> dict:
    """
    Estimate the dollar value of a DeFi protocol points program.

    Parameters
    ----------
    points_earned_per_day : float
        User's daily point accrual rate for their current position.
    days_until_tge : int
        Estimated days remaining until the Token Generation Event.
    total_protocol_points_issued : float
        Total points outstanding across all protocol participants.
    airdrop_allocation_pct : float
        Percentage of total token supply allocated to points holders (%).
    total_token_supply : float
        Total token supply at launch (e.g. 1,000,000,000).
    conservative_tge_price_usd : float
        Bear-case token price at TGE (USD).
    base_tge_price_usd : float
        Base/expected token price at TGE (USD).
    bull_tge_price_usd : float
        Bull-case token price at TGE (USD).
    position_size_usd : float
        User's current position size in USD (used to compute implied APY).
    protocol_name : str
        Protocol identifier (e.g. "Eigenlayer").

    Returns
    -------
    dict with keys:
        protocol_name, points_earned_per_day, days_until_tge,
        total_protocol_points_issued, airdrop_allocation_pct,
        total_token_supply, conservative_tge_price_usd, base_tge_price_usd,
        bull_tge_price_usd, position_size_usd,
        total_points_at_tge, user_points_share_pct, tokens_received,
        conservative_value_usd, base_value_usd, bull_value_usd,
        implied_apy_pct, points_label, timestamp
    """
    total_points_at_tge = _compute_total_points_at_tge(points_earned_per_day, days_until_tge)
    user_points_share_pct = _compute_user_points_share_pct(
        total_points_at_tge, total_protocol_points_issued
    )
    tokens_received = _compute_tokens_received(
        user_points_share_pct, airdrop_allocation_pct, total_token_supply
    )
    conservative_value_usd = _compute_scenario_value(tokens_received, conservative_tge_price_usd)
    base_value_usd = _compute_scenario_value(tokens_received, base_tge_price_usd)
    bull_value_usd = _compute_scenario_value(tokens_received, bull_tge_price_usd)
    implied_apy_pct = _compute_implied_apy(base_value_usd, position_size_usd, days_until_tge)
    points_label = _classify_points(implied_apy_pct)

    return {
        "protocol_name": protocol_name,
        "points_earned_per_day": points_earned_per_day,
        "days_until_tge": days_until_tge,
        "total_protocol_points_issued": total_protocol_points_issued,
        "airdrop_allocation_pct": airdrop_allocation_pct,
        "total_token_supply": total_token_supply,
        "conservative_tge_price_usd": conservative_tge_price_usd,
        "base_tge_price_usd": base_tge_price_usd,
        "bull_tge_price_usd": bull_tge_price_usd,
        "position_size_usd": position_size_usd,
        "total_points_at_tge": total_points_at_tge,
        "user_points_share_pct": user_points_share_pct,
        "tokens_received": tokens_received,
        "conservative_value_usd": conservative_value_usd,
        "base_value_usd": base_value_usd,
        "bull_value_usd": bull_value_usd,
        "implied_apy_pct": implied_apy_pct,
        "points_label": points_label,
        "timestamp": time.time(),
    }


def estimate_and_log(
    points_earned_per_day: float,
    days_until_tge: int,
    total_protocol_points_issued: float,
    airdrop_allocation_pct: float,
    total_token_supply: float,
    conservative_tge_price_usd: float,
    base_tge_price_usd: float,
    bull_tge_price_usd: float,
    position_size_usd: float,
    protocol_name: str,
    data_dir: Optional[str] = None,
) -> dict:
    """Run estimate() and append result to ring-buffer log."""
    result = estimate(
        points_earned_per_day=points_earned_per_day,
        days_until_tge=days_until_tge,
        total_protocol_points_issued=total_protocol_points_issued,
        airdrop_allocation_pct=airdrop_allocation_pct,
        total_token_supply=total_token_supply,
        conservative_tge_price_usd=conservative_tge_price_usd,
        base_tge_price_usd=base_tge_price_usd,
        bull_tge_price_usd=bull_tge_price_usd,
        position_size_usd=position_size_usd,
        protocol_name=protocol_name,
    )
    _append_log(result, data_dir or _DEFAULT_DATA_DIR)
    return result


def init_log(data_dir: Optional[str] = None) -> None:
    """Initialize log file as empty list if it does not exist."""
    d = data_dir or _DEFAULT_DATA_DIR
    os.makedirs(d, exist_ok=True)
    log_path = os.path.join(d, LOG_FILENAME)
    if not os.path.exists(log_path):
        _atomic_write_json([], log_path, d)


# ---------------------------------------------------------------------------
# Main class (wraps module-level functions)
# ---------------------------------------------------------------------------

class ProtocolDeFiPointsProgramValueEstimator:
    """
    Estimates the real dollar value of DeFi protocol points programs.

    Points are pre-token incentives; their dollar value depends on the user's
    share of total issued points, the fraction of token supply reserved for
    the airdrop, and the token price at TGE. Three price scenarios
    (conservative / base / bull) bracket the expected range of outcomes.

    Usage
    -----
    >>> est = ProtocolDeFiPointsProgramValueEstimator()
    >>> result = est.estimate(
    ...     points_earned_per_day=1000,
    ...     days_until_tge=180,
    ...     total_protocol_points_issued=1_000_000_000,
    ...     airdrop_allocation_pct=10.0,
    ...     total_token_supply=1_000_000_000,
    ...     conservative_tge_price_usd=0.05,
    ...     base_tge_price_usd=0.15,
    ...     bull_tge_price_usd=0.50,
    ...     position_size_usd=50_000,
    ...     protocol_name="Eigenlayer",
    ... )
    """

    def __init__(self, data_dir: Optional[str] = None):
        self._data_dir = data_dir or _DEFAULT_DATA_DIR

    def estimate(
        self,
        points_earned_per_day: float,
        days_until_tge: int,
        total_protocol_points_issued: float,
        airdrop_allocation_pct: float,
        total_token_supply: float,
        conservative_tge_price_usd: float,
        base_tge_price_usd: float,
        bull_tge_price_usd: float,
        position_size_usd: float,
        protocol_name: str,
    ) -> dict:
        """Estimate points program value. Does not write to disk."""
        return estimate(
            points_earned_per_day=points_earned_per_day,
            days_until_tge=days_until_tge,
            total_protocol_points_issued=total_protocol_points_issued,
            airdrop_allocation_pct=airdrop_allocation_pct,
            total_token_supply=total_token_supply,
            conservative_tge_price_usd=conservative_tge_price_usd,
            base_tge_price_usd=base_tge_price_usd,
            bull_tge_price_usd=bull_tge_price_usd,
            position_size_usd=position_size_usd,
            protocol_name=protocol_name,
        )

    def estimate_and_log(
        self,
        points_earned_per_day: float,
        days_until_tge: int,
        total_protocol_points_issued: float,
        airdrop_allocation_pct: float,
        total_token_supply: float,
        conservative_tge_price_usd: float,
        base_tge_price_usd: float,
        bull_tge_price_usd: float,
        position_size_usd: float,
        protocol_name: str,
    ) -> dict:
        """Estimate and append to ring-buffer log."""
        return estimate_and_log(
            points_earned_per_day=points_earned_per_day,
            days_until_tge=days_until_tge,
            total_protocol_points_issued=total_protocol_points_issued,
            airdrop_allocation_pct=airdrop_allocation_pct,
            total_token_supply=total_token_supply,
            conservative_tge_price_usd=conservative_tge_price_usd,
            base_tge_price_usd=base_tge_price_usd,
            bull_tge_price_usd=bull_tge_price_usd,
            position_size_usd=position_size_usd,
            protocol_name=protocol_name,
            data_dir=self._data_dir,
        )

    def init_log(self) -> None:
        """Initialize log file if it does not exist."""
        init_log(self._data_dir)

    @property
    def log_path(self) -> str:
        return os.path.join(self._data_dir, LOG_FILENAME)
