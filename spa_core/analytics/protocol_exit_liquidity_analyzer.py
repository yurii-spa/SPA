"""
MP-872 ProtocolExitLiquidityAnalyzer
--------------------------------------
Analyzes how easily you can exit a DeFi position considering withdrawal queues,
exit fees, lock-up periods, and market depth.  Estimates realistic exit scenarios.

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
_DEFAULT_TARGET_EXIT_DAYS: int = 7
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "exit_liquidity_log.json"
)
_LOG_CAP = 100


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=100), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            data: list = json.load(f)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    atomic_save(data, str(abs_path))
def _compute_estimated_exit_days(
    lock_up_days_remaining: int,
    daily_withdrawal_limit_usd: float,
    withdrawal_queue_usd: float,
    position_usd: float,
) -> float:
    """Return estimated days until position can be fully exited."""
    if lock_up_days_remaining > 0:
        return float(lock_up_days_remaining)

    if daily_withdrawal_limit_usd > 0 and position_usd > daily_withdrawal_limit_usd:
        queue_days = withdrawal_queue_usd / daily_withdrawal_limit_usd
        position_days = position_usd / daily_withdrawal_limit_usd
        return queue_days + position_days

    if withdrawal_queue_usd > 0 and daily_withdrawal_limit_usd == 0:
        return 1.0

    return 0.0


def _market_depth_coverage(market_depth_at_1pct_usd: float, position_usd: float) -> float:
    if position_usd > 0:
        return market_depth_at_1pct_usd / position_usd * 100.0
    return 0.0


def _exit_liquidity_score(
    lock_up_days_remaining: int,
    estimated_exit_days: float,
    target_exit_days: int,
    market_depth_coverage_pct: float,
) -> int:
    """Return 0-100 exit liquidity score."""
    # Base score from lock / time constraints
    if lock_up_days_remaining > 180:
        base = 5
    elif lock_up_days_remaining > 90:
        base = 8
    elif lock_up_days_remaining > 30:
        base = 12
    elif lock_up_days_remaining > 0:
        # ≤ 30 days locked
        base = 20
    elif estimated_exit_days > target_exit_days:
        base = 30
    elif estimated_exit_days > 1:
        base = 55
    elif estimated_exit_days > 0:
        base = 70
    else:
        # immediate
        base = 80

    # Market depth bonus
    if market_depth_coverage_pct >= 200:
        bonus = 20
    elif market_depth_coverage_pct >= 100:
        bonus = 15
    elif market_depth_coverage_pct >= 50:
        bonus = 10
    elif market_depth_coverage_pct >= 20:
        bonus = 5
    else:
        bonus = 0

    return min(100, base + bonus)


def _exit_label(
    lock_up_days_remaining: int,
    estimated_exit_days: float,
    target_exit_days: int,
) -> str:
    if lock_up_days_remaining > 0:
        return "LOCKED"
    if estimated_exit_days > target_exit_days:
        return "SLOW"
    if estimated_exit_days > 1:
        return "MODERATE"
    if estimated_exit_days > 0:
        return "FAST"
    return "INSTANT"


def _bottleneck(
    lock_up_days_remaining: int,
    daily_withdrawal_limit_usd: float,
    position_usd: float,
    withdrawal_queue_usd: float,
    market_depth_coverage_pct: float,
) -> str | None:
    if lock_up_days_remaining > 0:
        return "LOCK_UP"
    if daily_withdrawal_limit_usd > 0 and position_usd > daily_withdrawal_limit_usd:
        return "DAILY_LIMIT"
    if withdrawal_queue_usd > 0:
        return "QUEUE"
    if market_depth_coverage_pct < 50:
        return "MARKET_DEPTH"
    return None


def _recommendation(
    label: str,
    lock_up_days_remaining: int,
    estimated_exit_days: float,
    target_exit_days: int,
    withdrawal_queue_usd: float,
    market_depth_coverage_pct: float,
) -> str:
    if label == "LOCKED":
        return f"Locked for {lock_up_days_remaining}d. Plan around lock expiry."
    if label == "SLOW":
        return (
            f"Exit takes {estimated_exit_days:.0f}d (>target {target_exit_days}d). "
            f"Reduce position or wait."
        )
    if label == "MODERATE":
        return f"1-{target_exit_days}d exit window. Queue: {withdrawal_queue_usd:.0f} USD ahead."
    if label == "FAST":
        return "Exit available quickly. Monitor queue size."
    # INSTANT
    return f"Immediate exit available. Depth covers {market_depth_coverage_pct:.0f}% of position."


def _analyze_position(pos: dict, target_exit_days: int) -> dict:
    protocol = pos.get("protocol", "UNKNOWN")
    position_usd = float(pos.get("position_usd", 0.0))
    withdrawal_queue_usd = float(pos.get("withdrawal_queue_usd", 0.0))
    daily_limit = float(pos.get("daily_withdrawal_limit_usd", 0.0))
    exit_fee_pct = float(pos.get("exit_fee_pct", 0.0))
    lock_up_days = int(pos.get("lock_up_days_remaining", 0))
    market_depth = float(pos.get("market_depth_at_1pct_usd", 0.0))

    exit_fee_usd = position_usd * exit_fee_pct / 100.0
    net_exit_value_usd = position_usd - exit_fee_usd

    estimated_exit_days = _compute_estimated_exit_days(
        lock_up_days, daily_limit, withdrawal_queue_usd, position_usd
    )
    can_exit_in_target = estimated_exit_days <= target_exit_days

    depth_coverage = _market_depth_coverage(market_depth, position_usd)

    score = _exit_liquidity_score(lock_up_days, estimated_exit_days, target_exit_days, depth_coverage)
    label = _exit_label(lock_up_days, estimated_exit_days, target_exit_days)
    neck = _bottleneck(lock_up_days, daily_limit, position_usd, withdrawal_queue_usd, depth_coverage)
    rec = _recommendation(
        label, lock_up_days, estimated_exit_days, target_exit_days,
        withdrawal_queue_usd, depth_coverage,
    )

    return {
        "protocol": protocol,
        "position_usd": position_usd,
        "exit_fee_usd": exit_fee_usd,
        "net_exit_value_usd": net_exit_value_usd,
        "estimated_exit_days": estimated_exit_days,
        "can_exit_in_target": can_exit_in_target,
        "exit_liquidity_score": score,
        "exit_label": label,
        "market_depth_coverage_pct": depth_coverage,
        "bottleneck": neck,
        "recommendation": rec,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(positions: list[dict], config: dict | None = None) -> dict:
    """
    Analyze exit liquidity across a list of DeFi positions.

    Parameters
    ----------
    positions : list[dict]
        Each entry must have keys:
        - protocol: str
        - position_usd: float
        - withdrawal_queue_usd: float
        - daily_withdrawal_limit_usd: float  (0 = unlimited)
        - exit_fee_pct: float
        - lock_up_days_remaining: int
        - market_depth_at_1pct_usd: float
        - token_type: str  (informational)
    config : dict, optional
        - target_exit_days: int  (default 7)

    Returns
    -------
    dict
        Full exit liquidity analysis result.
    """
    cfg = config or {}
    target_exit_days: int = int(cfg.get("target_exit_days", _DEFAULT_TARGET_EXIT_DAYS))

    analyzed: list[dict] = [_analyze_position(p, target_exit_days) for p in positions]

    # -----------------------------------------------------------------------
    # Portfolio-level aggregations
    # -----------------------------------------------------------------------
    total_position_usd = sum(a["position_usd"] for a in analyzed)

    instantly_exitable_usd = sum(
        a["position_usd"] for a in analyzed if a["exit_label"] == "INSTANT"
    )

    liquidity_ratio_pct = (
        instantly_exitable_usd / total_position_usd * 100.0
        if total_position_usd > 0
        else 0.0
    )

    # most_locked: protocol with highest estimated_exit_days
    # Prefer positions with lock_up_days_remaining > 0
    most_locked: str | None = None
    if analyzed:
        locked_only = [a for a in analyzed if a["estimated_exit_days"] > 0]
        if locked_only:
            most_locked = max(locked_only, key=lambda a: a["estimated_exit_days"])["protocol"]

    avg_score = (
        sum(a["exit_liquidity_score"] for a in analyzed) / len(analyzed)
        if analyzed
        else 0.0
    )

    ts = time.time()
    result: dict[str, Any] = {
        "positions": analyzed,
        "instantly_exitable_usd": instantly_exitable_usd,
        "total_position_usd": total_position_usd,
        "liquidity_ratio_pct": liquidity_ratio_pct,
        "most_locked": most_locked,
        "average_exit_liquidity_score": avg_score,
        "timestamp": ts,
    }

    try:
        _atomic_log(_LOG_PATH, result)
    except Exception:
        pass  # advisory: never crash caller

    return result


if __name__ == "__main__":
    import sys

    _demo = [
        {
            "protocol": "Aave V3",
            "position_usd": 50_000.0,
            "withdrawal_queue_usd": 0.0,
            "daily_withdrawal_limit_usd": 0.0,
            "exit_fee_pct": 0.0,
            "lock_up_days_remaining": 0,
            "market_depth_at_1pct_usd": 100_000.0,
            "token_type": "LIQUID",
        },
        {
            "protocol": "Maple Finance",
            "position_usd": 30_000.0,
            "withdrawal_queue_usd": 50_000.0,
            "daily_withdrawal_limit_usd": 10_000.0,
            "exit_fee_pct": 0.5,
            "lock_up_days_remaining": 0,
            "market_depth_at_1pct_usd": 20_000.0,
            "token_type": "WITHDRAWAL_QUEUE",
        },
        {
            "protocol": "Lido stETH (vesting)",
            "position_usd": 20_000.0,
            "withdrawal_queue_usd": 0.0,
            "daily_withdrawal_limit_usd": 0.0,
            "exit_fee_pct": 0.0,
            "lock_up_days_remaining": 45,
            "market_depth_at_1pct_usd": 500_000.0,
            "token_type": "LOCKED_LP",
        },
    ]

    r = analyze(_demo)
    print(json.dumps(r, indent=2, default=str))
    sys.exit(0)
