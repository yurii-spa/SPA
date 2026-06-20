"""
MP-1121: ProtocolDeFiExitLiquidityDepthAnalyzer
================================================
Advisory-only, read-only analytics module.
Analyses how easily a position can be exited without significant slippage.
Large positions in low-liquidity pools have severe exit costs.
Computes estimated slippage and time-to-exit at different urgency levels.

Output file: data/exit_liquidity_depth_log.json (ring-buffer, cap 100)
Pure Python stdlib only.  Atomic writes (tmp + os.replace).
Python 3.9 compatible.
"""

import json
import math
import os
import time
from typing import Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Data file (relative to repo root: two levels up from spa_core/analytics/)
# ---------------------------------------------------------------------------
_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "exit_liquidity_depth_log.json",
)

RING_BUFFER_CAP = 100

# ---------------------------------------------------------------------------
# Liquidity label constants
# ---------------------------------------------------------------------------
LABEL_DEEP_LIQUIDITY = "DEEP_LIQUIDITY"
LABEL_GOOD_LIQUIDITY = "GOOD_LIQUIDITY"
LABEL_ADEQUATE_LIQUIDITY = "ADEQUATE_LIQUIDITY"
LABEL_THIN_LIQUIDITY = "THIN_LIQUIDITY"
LABEL_EXIT_TRAP = "EXIT_TRAP"

# Thresholds for position_to_tvl_pct
THRESHOLD_DEEP = 0.5       # < 0.5 % → DEEP_LIQUIDITY
THRESHOLD_GOOD = 2.0       # 0.5–2 % → GOOD_LIQUIDITY
THRESHOLD_ADEQUATE = 5.0   # 2–5 %   → ADEQUATE_LIQUIDITY
THRESHOLD_THIN = 15.0      # 5–15 %  → THIN_LIQUIDITY
                            # >= 15 % → EXIT_TRAP

# Slippage cap (%)
MAX_SLIPPAGE_PCT = 20.0

# Urgency → hours-per-chunk
URGENCY_FACTORS = {
    "immediate":    0.0,
    "within_hour":  0.1,
    "within_day":   1.0,
    "within_week": 24.0,
}
DEFAULT_URGENCY_FACTOR = 1.0   # used for unrecognised urgency strings

# Valid protocol types (informational; not used in calculations)
VALID_PROTOCOL_TYPES = frozenset({"amm", "lending", "vault", "staking"})


# ---------------------------------------------------------------------------
# Pure math helpers — fully testable at module level
# ---------------------------------------------------------------------------

def compute_position_to_tvl_pct(
    position_size_usd: float, pool_tvl_usd: float
) -> float:
    """position / tvl * 100.  Returns 0.0 if tvl <= 0."""
    if pool_tvl_usd <= 0.0:
        return 0.0
    return position_size_usd / pool_tvl_usd * 100.0


def compute_position_to_daily_volume_pct(
    position_size_usd: float, daily_volume_usd: float
) -> float:
    """position / daily_volume * 100.  Returns 0.0 if volume <= 0."""
    if daily_volume_usd <= 0.0:
        return 0.0
    return position_size_usd / daily_volume_usd * 100.0


def compute_estimated_slippage_pct(
    position_size_usd: float, pool_tvl_usd: float
) -> float:
    """
    sqrt(position / tvl) * 10, capped at MAX_SLIPPAGE_PCT.
    Returns 0.0 if tvl <= 0 or position <= 0.
    """
    if pool_tvl_usd <= 0.0 or position_size_usd <= 0.0:
        return 0.0
    ratio = position_size_usd / pool_tvl_usd
    slippage = math.sqrt(ratio) * 10.0
    return min(slippage, MAX_SLIPPAGE_PCT)


def compute_estimated_exit_cost_usd(
    position_size_usd: float, estimated_slippage_pct: float
) -> float:
    """position * slippage / 100."""
    return position_size_usd * estimated_slippage_pct / 100.0


def compute_recommended_exit_chunks(position_to_tvl_pct: float) -> int:
    """
    If position_to_tvl_pct > 2 %: ceil(position_to_tvl_pct / 2), minimum 1.
    Otherwise: 1.
    """
    if position_to_tvl_pct > 2.0:
        return max(1, math.ceil(position_to_tvl_pct / 2.0))
    return 1


def get_urgency_factor(exit_urgency: str) -> float:
    """Return hours-per-chunk for the given urgency string."""
    return URGENCY_FACTORS.get(exit_urgency, DEFAULT_URGENCY_FACTOR)


def compute_exit_time_hours(
    withdrawal_queue_hours: float,
    exit_chunks: int,
    urgency_factor: float,
) -> float:
    """
    withdrawal_queue + chunks * urgency_factor.
    Negative withdrawal_queue values are clamped to 0.
    """
    return max(0.0, withdrawal_queue_hours) + exit_chunks * urgency_factor


def get_liquidity_label(position_to_tvl_pct: float) -> str:
    """Return label based on position_to_tvl_pct (%)."""
    if position_to_tvl_pct < THRESHOLD_DEEP:
        return LABEL_DEEP_LIQUIDITY
    if position_to_tvl_pct < THRESHOLD_GOOD:
        return LABEL_GOOD_LIQUIDITY
    if position_to_tvl_pct < THRESHOLD_ADEQUATE:
        return LABEL_ADEQUATE_LIQUIDITY
    if position_to_tvl_pct < THRESHOLD_THIN:
        return LABEL_THIN_LIQUIDITY
    return LABEL_EXIT_TRAP


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolDeFiExitLiquidityDepthAnalyzer:
    """
    Analyses exit liquidity depth for DeFi protocol positions.
    Advisory / read-only.  Pure stdlib only.  Python 3.9 compatible.
    """

    def __init__(self, data_file: Optional[str] = None) -> None:
        self._data_file = data_file or _DEFAULT_DATA_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        position_size_usd: float,
        pool_tvl_usd: float,
        daily_volume_usd: float,
        exit_urgency: str,
        protocol_type: str,
        withdrawal_queue_hours: float,
        protocol_name: str = "unknown",
    ) -> dict:
        """
        Analyse exit liquidity depth for a single DeFi position.

        Parameters
        ----------
        position_size_usd : float
            Size of our position we want to exit (USD).
        pool_tvl_usd : float
            Total liquidity available in the pool (USD).
        daily_volume_usd : float
            24-hour trading volume (USD).
        exit_urgency : str
            One of: immediate / within_hour / within_day / within_week.
        protocol_type : str
            One of: amm / lending / vault / staking.
        withdrawal_queue_hours : float
            Hours to wait for withdrawal; 0 if instant.
        protocol_name : str
            Label for identification and logging.

        Returns
        -------
        dict with keys:
            protocol_name, protocol_type, exit_urgency,
            position_size_usd, pool_tvl_usd, daily_volume_usd,
            withdrawal_queue_hours, position_to_tvl_pct,
            position_to_daily_volume_pct, estimated_slippage_pct,
            estimated_exit_cost_usd, recommended_exit_chunks,
            exit_time_hours, liquidity_label, run_ts
        """
        position_size_usd = float(position_size_usd)
        pool_tvl_usd = float(pool_tvl_usd)
        daily_volume_usd = float(daily_volume_usd)
        exit_urgency = str(exit_urgency)
        protocol_type = str(protocol_type)
        withdrawal_queue_hours = float(withdrawal_queue_hours)

        tvl_pct = compute_position_to_tvl_pct(position_size_usd, pool_tvl_usd)
        vol_pct = compute_position_to_daily_volume_pct(position_size_usd, daily_volume_usd)
        slippage = compute_estimated_slippage_pct(position_size_usd, pool_tvl_usd)
        exit_cost = compute_estimated_exit_cost_usd(position_size_usd, slippage)
        chunks = compute_recommended_exit_chunks(tvl_pct)
        urgency_factor = get_urgency_factor(exit_urgency)
        exit_time = compute_exit_time_hours(withdrawal_queue_hours, chunks, urgency_factor)
        label = get_liquidity_label(tvl_pct)

        return {
            "protocol_name": protocol_name,
            "protocol_type": protocol_type,
            "exit_urgency": exit_urgency,
            "position_size_usd": position_size_usd,
            "pool_tvl_usd": pool_tvl_usd,
            "daily_volume_usd": daily_volume_usd,
            "withdrawal_queue_hours": withdrawal_queue_hours,
            "position_to_tvl_pct": round(tvl_pct, 6),
            "position_to_daily_volume_pct": round(vol_pct, 6),
            "estimated_slippage_pct": round(slippage, 6),
            "estimated_exit_cost_usd": round(exit_cost, 6),
            "recommended_exit_chunks": chunks,
            "exit_time_hours": round(exit_time, 6),
            "liquidity_label": label,
            "run_ts": time.time(),
        }

    def save_result(self, result: dict) -> None:
        """
        Atomically append *result* to the ring-buffer JSON log
        (capped at RING_BUFFER_CAP entries).  Uses tmp + os.replace.
        """
        data_dir = os.path.dirname(self._data_file)
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)

        existing: list = []
        if os.path.exists(self._data_file):
            try:
                with open(self._data_file, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []

        existing.append(result)
        existing = existing[-RING_BUFFER_CAP:]

        atomic_save(existing, str(self))
