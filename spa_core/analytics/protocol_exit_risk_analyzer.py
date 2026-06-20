"""
MP-810 ProtocolExitRiskAnalyzer
Analyzes the risks and costs of exiting a DeFi position — withdrawal queues,
slippage, lock periods, and penalty fees — and provides optimal exit strategy.

Advisory/read-only module. Pure stdlib. Atomic writes via tmp + os.replace.
Data: data/protocol_exit_risk_log.json (ring-buffer 100)
"""

import json
import os
import time
from spa_core.utils.atomic import atomic_save

_DEFAULT_CONFIG = {
    "acceptable_slippage_pct": 1.0,
}

_LOG_RING_SIZE = 100
_DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "protocol_exit_risk_log.json"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_slippage_usd(position_usd: float, slippage_1pct_depth_usd: float) -> float:
    """
    Estimated slippage cost.
    If position > depth: 2% on the excess; otherwise 0.
    """
    if position_usd > slippage_1pct_depth_usd:
        return (position_usd - slippage_1pct_depth_usd) * 0.02
    return 0.0


def _compute_days_to_exit(position_usd: float, daily_withdrawal_usd: float) -> float:
    """Days needed to fully exit at daily withdrawal volume. Minimum 1 day."""
    if daily_withdrawal_usd <= 0:
        return float("inf")
    raw = position_usd / daily_withdrawal_usd
    return max(1.0, raw)


def _compute_liquidity_risk(days_to_exit: float, position_as_pct_of_pool: float) -> str:
    """
    Classify liquidity risk.
    Evaluation is ordered: CRITICAL > HIGH > MEDIUM > LOW.
    """
    if days_to_exit > 30 or position_as_pct_of_pool > 20:
        return "CRITICAL"
    if days_to_exit > 7 or position_as_pct_of_pool > 10:
        return "HIGH"
    if days_to_exit > 3 or position_as_pct_of_pool > 5:
        return "MEDIUM"
    return "LOW"


def _compute_exit_strategy(
    is_locked: bool,
    early_exit_penalty_usd: float,
    withdrawal_fee_usd: float,
    gas_cost_usd: float,
    liquidity_risk: str,
    exit_cost_pct: float,
) -> str:
    """
    Determine exit strategy.
    Priority:
      1. WAIT_UNLOCK  — locked AND penalty > fee+gas
      2. PARTIAL_EXIT — HIGH/CRITICAL liquidity AND not locked
      3. EXIT_NOW     — not locked AND cost < 3% AND LOW/MEDIUM liquidity
      4. HOLD         — otherwise
    """
    if is_locked and early_exit_penalty_usd > (withdrawal_fee_usd + gas_cost_usd):
        return "WAIT_UNLOCK"
    if liquidity_risk in ("HIGH", "CRITICAL") and not is_locked:
        return "PARTIAL_EXIT"
    if not is_locked and exit_cost_pct < 3.0 and liquidity_risk in ("LOW", "MEDIUM"):
        return "EXIT_NOW"
    return "HOLD"


def _compute_recommended_exit_size(
    exit_strategy: str,
    position_usd: float,
    slippage_1pct_depth_usd: float,
) -> float:
    """How much to exit now."""
    if exit_strategy == "EXIT_NOW":
        return position_usd
    if exit_strategy == "PARTIAL_EXIT":
        return min(slippage_1pct_depth_usd, position_usd * 0.5)
    # HOLD / WAIT_UNLOCK
    return 0.0


def _build_reason(
    exit_strategy: str,
    is_locked: bool,
    lock_remaining_days: int,
    exit_cost_pct: float,
    liquidity_risk: str,
    early_exit_penalty_usd: float,
    withdrawal_fee_usd: float,
    gas_cost_usd: float,
    days_to_exit: float,
) -> str:
    """Human-readable explanation for the recommended strategy."""
    if exit_strategy == "WAIT_UNLOCK":
        return (
            f"Position is locked for {lock_remaining_days} more day(s). "
            f"Early exit penalty (${early_exit_penalty_usd:.2f}) exceeds "
            f"withdrawal fee + gas (${withdrawal_fee_usd + gas_cost_usd:.2f}). "
            "Wait for lock expiry to avoid unnecessary costs."
        )
    if exit_strategy == "PARTIAL_EXIT":
        return (
            f"Liquidity risk is {liquidity_risk} — estimated {days_to_exit:.1f} day(s) to fully exit. "
            "Recommend partial exit within 1% slippage depth to reduce position size gradually."
        )
    if exit_strategy == "EXIT_NOW":
        return (
            f"Position is unlocked. Total exit cost is {exit_cost_pct:.2f}% of position "
            f"(below 3% threshold). Liquidity risk is {liquidity_risk}. "
            "Favorable conditions to exit now."
        )
    # HOLD
    if is_locked:
        return (
            f"Position is locked for {lock_remaining_days} more day(s). "
            f"Penalty (${early_exit_penalty_usd:.2f}) is not significantly higher than "
            "other costs, but exiting early is still inadvisable. Hold until unlock."
        )
    return (
        f"Exit cost is {exit_cost_pct:.2f}% or liquidity risk ({liquidity_risk}) is elevated. "
        "Hold position and reassess when conditions improve."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(position: dict, market: dict, config: dict = None) -> dict:
    """
    Analyze risks and costs of exiting a DeFi position.

    Parameters
    ----------
    position : dict
        {
            "protocol": str,
            "position_usd": float,
            "lock_remaining_days": int,
            "early_exit_penalty_pct": float,
            "token": str
        }
    market : dict
        {
            "pool_tvl_usd": float,
            "daily_withdrawal_usd": float,
            "slippage_1pct_depth_usd": float,
            "withdrawal_fee_pct": float,
            "gas_cost_usd": float
        }
    config : dict, optional
        {
            "acceptable_slippage_pct": float   # default 1.0 (unused in logic, kept for extensibility)
        }

    Returns
    -------
    dict  (see module docstring)
    """
    cfg = {**_DEFAULT_CONFIG, **(config or {})}  # noqa — stored for future use

    # --- Position fields ---
    protocol = str(position.get("protocol", ""))
    position_usd = float(position.get("position_usd", 0.0))
    lock_remaining_days = int(position.get("lock_remaining_days", 0))
    early_exit_penalty_pct = float(position.get("early_exit_penalty_pct", 0.0))

    # --- Market fields ---
    pool_tvl_usd = float(market.get("pool_tvl_usd", 0.0))
    daily_withdrawal_usd = float(market.get("daily_withdrawal_usd", 0.0))
    slippage_1pct_depth_usd = float(market.get("slippage_1pct_depth_usd", 0.0))
    withdrawal_fee_pct = float(market.get("withdrawal_fee_pct", 0.0))
    gas_cost_usd = float(market.get("gas_cost_usd", 0.0))

    # --- Derived booleans ---
    is_locked = lock_remaining_days > 0

    # --- Cost computations ---
    early_exit_penalty_usd = (position_usd * early_exit_penalty_pct / 100.0) if is_locked else 0.0
    withdrawal_fee_usd = position_usd * withdrawal_fee_pct / 100.0
    estimated_slippage_usd = _compute_slippage_usd(position_usd, slippage_1pct_depth_usd)
    total_exit_cost_usd = (
        early_exit_penalty_usd + withdrawal_fee_usd + estimated_slippage_usd + gas_cost_usd
    )
    exit_cost_pct = (total_exit_cost_usd / position_usd * 100.0) if position_usd > 0 else 0.0

    # --- Liquidity computations ---
    days_to_exit = _compute_days_to_exit(position_usd, daily_withdrawal_usd)
    can_exit_without_slippage = position_usd <= slippage_1pct_depth_usd
    position_as_pct_of_pool = (position_usd / pool_tvl_usd * 100.0) if pool_tvl_usd > 0 else 0.0
    liquidity_risk = _compute_liquidity_risk(days_to_exit, position_as_pct_of_pool)

    # --- Strategy ---
    exit_strategy = _compute_exit_strategy(
        is_locked, early_exit_penalty_usd, withdrawal_fee_usd,
        gas_cost_usd, liquidity_risk, exit_cost_pct,
    )
    recommended_exit_size_usd = _compute_recommended_exit_size(
        exit_strategy, position_usd, slippage_1pct_depth_usd
    )
    reason = _build_reason(
        exit_strategy, is_locked, lock_remaining_days, exit_cost_pct,
        liquidity_risk, early_exit_penalty_usd, withdrawal_fee_usd,
        gas_cost_usd, days_to_exit,
    )

    return {
        "protocol": protocol,
        "position_usd": position_usd,
        "is_locked": is_locked,
        "lock_remaining_days": lock_remaining_days,
        "costs": {
            "early_exit_penalty_usd": early_exit_penalty_usd,
            "withdrawal_fee_usd": withdrawal_fee_usd,
            "estimated_slippage_usd": estimated_slippage_usd,
            "gas_cost_usd": gas_cost_usd,
            "total_exit_cost_usd": total_exit_cost_usd,
            "exit_cost_pct": exit_cost_pct,
        },
        "liquidity": {
            "days_to_exit": days_to_exit,
            "can_exit_without_slippage": can_exit_without_slippage,
            "position_as_pct_of_pool": position_as_pct_of_pool,
            "liquidity_risk": liquidity_risk,
        },
        "exit_strategy": exit_strategy,
        "recommended_exit_size_usd": recommended_exit_size_usd,
        "reason": reason,
        "timestamp": time.time(),
    }


def log_result(result: dict, log_path: str = None) -> None:
    """Append result to ring-buffer JSON log (max 100 entries). Atomic write."""
    if log_path is None:
        log_path = _DEFAULT_LOG_PATH

    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                log = json.load(f)
        except (json.JSONDecodeError, OSError):
            log = []
    else:
        log = []

    log.append(result)

    if len(log) > _LOG_RING_SIZE:
        log = log[-_LOG_RING_SIZE:]

    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    atomic_save(log, str(log_path))
def analyze_and_log(position: dict, market: dict, config: dict = None, log_path: str = None) -> dict:
    """analyze() + log_result(). Returns the result dict."""
    result = analyze(position, market, config)
    log_result(result, log_path)
    return result


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json as _json
    import sys

    _pos = {
        "protocol": "Aave V3",
        "position_usd": 50000.0,
        "lock_remaining_days": 0,
        "early_exit_penalty_pct": 0.0,
        "token": "USDC",
    }
    _mkt = {
        "pool_tvl_usd": 1_000_000.0,
        "daily_withdrawal_usd": 20_000.0,
        "slippage_1pct_depth_usd": 100_000.0,
        "withdrawal_fee_pct": 0.1,
        "gas_cost_usd": 25.0,
    }
    result = analyze(_pos, _mkt)
    _json.dump(result, sys.stdout, indent=2)
    print()
