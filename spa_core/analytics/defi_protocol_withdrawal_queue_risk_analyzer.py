"""
MP-1136: DeFiProtocolWithdrawalQueueRiskAnalyzer
=================================================
Advisory-only analytics module.

Analyzes withdrawal queue risk — how long it takes to exit a position and what
happens to yield/value during the wait. Critical for Lido (unbonding), Pendle
(maturity), and lending protocols under stress.

Inputs:
  withdrawal_type               str: instant / queued / unbonding / maturity_locked
  queue_wait_hours              float (0 if instant; minimum stated wait in hours)
  queue_size_usd                float (total USD value waiting ahead in the queue)
  daily_exit_capacity_usd       float (how much USD exits the protocol per day)
  position_size_usd             float (our position we want to exit)
  annual_yield_during_wait_pct  float (APY % earned on the position while waiting)
  price_impact_risk_pct         float (expected % change in underlying asset price
                                        during the wait — e.g. slippage, depegging)
  protocol_name                 str

Outputs:
  estimated_wait_hours          float | None — max(queue_wait_hours,
                                                    queue_size_usd / daily_exit_capacity_usd * 24);
                                                None when the queue is infinite (capacity=0
                                                and queue_size_usd > 0)
  estimated_wait_days           float | None
  yield_earned_during_wait_usd  float — position * annual_yield/100 * wait_days/365;
                                         0.0 when wait is infinite
  price_impact_usd              float — position * price_impact_risk/100
  net_exit_value_usd            float — position + yield - price_impact
  queue_risk_score              int 0-100 (piecewise linear, see SCORE_BREAKPOINTS)
  queue_label                   str: INSTANT_EXIT / FAST_EXIT / MANAGEABLE_QUEUE /
                                      LONG_QUEUE / EXIT_ILLIQUID

Label thresholds (estimated_wait_hours):
  == 0          → INSTANT_EXIT
  (0, 2]        → FAST_EXIT
  (2, 24]       → MANAGEABLE_QUEUE
  (24, 168]     → LONG_QUEUE
  > 168 / inf   → EXIT_ILLIQUID

Risk-score piecewise breakpoints (hours → score):
  0 → 0, 2 → 20, 24 → 50, 168 → 80, 336 → 100, >336 → 100

Log file: data/withdrawal_queue_risk_log.json  (ring-buffer 100 entries)
Atomic writes: tmp + os.replace.
Pure stdlib only.  Read-only / advisory.  Python 3.9 compatible.
"""

import json
import os
import time
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_PATH: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "withdrawal_queue_risk_log.json",
)
LOG_MAX_ENTRIES: int = 100

HOURS_PER_DAY: float = 24.0
DAYS_PER_YEAR: float = 365.0

# Label boundary hours
LABEL_INSTANT_MAX: float = 0.0     # == 0  → INSTANT_EXIT
LABEL_FAST_MAX: float = 2.0        # <= 2  → FAST_EXIT
LABEL_MANAGEABLE_MAX: float = 24.0 # <= 24 → MANAGEABLE_QUEUE
LABEL_LONG_MAX: float = 168.0      # <= 168→ LONG_QUEUE
                                   # > 168 → EXIT_ILLIQUID

# Valid withdrawal types
VALID_WITHDRAWAL_TYPES: frozenset = frozenset(
    {"instant", "queued", "unbonding", "maturity_locked"}
)

# Piecewise linear breakpoints: (hours, score)
SCORE_BREAKPOINTS: List[tuple] = [
    (0.0, 0),
    (2.0, 20),
    (24.0, 50),
    (168.0, 80),
    (336.0, 100),
]


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _validate_inputs(
    withdrawal_type: str,
    queue_wait_hours: float,
    queue_size_usd: float,
    daily_exit_capacity_usd: float,
    position_size_usd: float,
    annual_yield_during_wait_pct: float,
    price_impact_risk_pct: float,
    protocol_name: str,
) -> None:
    if withdrawal_type not in VALID_WITHDRAWAL_TYPES:
        raise ValueError(
            f"withdrawal_type must be one of {sorted(VALID_WITHDRAWAL_TYPES)}, "
            f"got '{withdrawal_type}'"
        )
    if queue_wait_hours < 0:
        raise ValueError(
            f"queue_wait_hours must be >= 0, got {queue_wait_hours}"
        )
    if queue_size_usd < 0:
        raise ValueError(
            f"queue_size_usd must be >= 0, got {queue_size_usd}"
        )
    if daily_exit_capacity_usd < 0:
        raise ValueError(
            f"daily_exit_capacity_usd must be >= 0, got {daily_exit_capacity_usd}"
        )
    if position_size_usd <= 0:
        raise ValueError(
            f"position_size_usd must be > 0, got {position_size_usd}"
        )
    if annual_yield_during_wait_pct < 0:
        raise ValueError(
            f"annual_yield_during_wait_pct must be >= 0, "
            f"got {annual_yield_during_wait_pct}"
        )
    if price_impact_risk_pct < 0:
        raise ValueError(
            f"price_impact_risk_pct must be >= 0, got {price_impact_risk_pct}"
        )
    if not isinstance(protocol_name, str) or not protocol_name.strip():
        raise ValueError("protocol_name must be a non-empty string")


# ---------------------------------------------------------------------------
# Core computations
# ---------------------------------------------------------------------------

def _compute_estimated_wait_hours(
    queue_wait_hours: float,
    queue_size_usd: float,
    daily_exit_capacity_usd: float,
) -> float:
    """
    estimated_wait_hours = max(queue_wait_hours,
                               queue_size_usd / daily_exit_capacity_usd * 24)

    Special cases:
      daily_exit_capacity_usd == 0 and queue_size_usd >  0 → inf (queue never drains)
      daily_exit_capacity_usd == 0 and queue_size_usd == 0 → queue_wait_hours
    """
    if daily_exit_capacity_usd <= 0.0:
        if queue_size_usd > 0.0:
            return float("inf")
        return float(queue_wait_hours)
    queue_based_hours = queue_size_usd / daily_exit_capacity_usd * HOURS_PER_DAY
    return max(float(queue_wait_hours), queue_based_hours)


def _compute_queue_risk_score(estimated_wait_hours: float) -> int:
    """
    Piecewise linear score 0-100 based on estimated wait hours.
    Uses SCORE_BREAKPOINTS.  inf → 100.
    """
    if estimated_wait_hours != estimated_wait_hours:  # NaN guard
        return 100
    if estimated_wait_hours == float("inf"):
        return 100
    if estimated_wait_hours <= 0.0:
        return 0
    # Past the last breakpoint
    if estimated_wait_hours >= SCORE_BREAKPOINTS[-1][0]:
        return SCORE_BREAKPOINTS[-1][1]
    for i in range(len(SCORE_BREAKPOINTS) - 1):
        x0, y0 = SCORE_BREAKPOINTS[i]
        x1, y1 = SCORE_BREAKPOINTS[i + 1]
        if x0 <= estimated_wait_hours <= x1:
            if x1 == x0:
                return int(y1)
            frac = (estimated_wait_hours - x0) / (x1 - x0)
            return int(y0 + frac * (y1 - y0))
    return 100  # fallback


def _compute_queue_label(estimated_wait_hours: float) -> str:
    """Classify wait hours into an exit-liquidity label."""
    if estimated_wait_hours == float("inf"):
        return "EXIT_ILLIQUID"
    if estimated_wait_hours <= LABEL_INSTANT_MAX:
        return "INSTANT_EXIT"
    if estimated_wait_hours <= LABEL_FAST_MAX:
        return "FAST_EXIT"
    if estimated_wait_hours <= LABEL_MANAGEABLE_MAX:
        return "MANAGEABLE_QUEUE"
    if estimated_wait_hours <= LABEL_LONG_MAX:
        return "LONG_QUEUE"
    return "EXIT_ILLIQUID"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: Any) -> None:
    """Write *data* as JSON to *path* atomically (tmp + os.replace)."""
    dir_ = os.path.dirname(path)
    if dir_:
        os.makedirs(dir_, exist_ok=True)
    atomic_save(data, str(path))
def _load_log(path: str) -> List[Dict[str, Any]]:
    """Load log entries from *path*, returning [] on missing/corrupt file."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError):
        pass
    return []


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class DeFiProtocolWithdrawalQueueRiskAnalyzer:
    """
    Analyzes withdrawal queue risk for a DeFi protocol position.

    Advisory only — never modifies allocator, risk, or execution domains.
    """

    def __init__(self, log_path: Optional[str] = None) -> None:
        self._log_path: str = log_path if log_path is not None else LOG_PATH

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def analyze(
        self,
        withdrawal_type: str,
        queue_wait_hours: float,
        queue_size_usd: float,
        daily_exit_capacity_usd: float,
        position_size_usd: float,
        annual_yield_during_wait_pct: float,
        price_impact_risk_pct: float,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """
        Analyze withdrawal queue risk for one position.

        Returns a dict with all computed fields. Raises ValueError on invalid input.
        Estimated wait hours/days are returned as None when the queue is infinite.
        """
        _validate_inputs(
            withdrawal_type,
            queue_wait_hours,
            queue_size_usd,
            daily_exit_capacity_usd,
            position_size_usd,
            annual_yield_during_wait_pct,
            price_impact_risk_pct,
            protocol_name,
        )

        raw_wait_hours = _compute_estimated_wait_hours(
            queue_wait_hours, queue_size_usd, daily_exit_capacity_usd
        )
        is_infinite = raw_wait_hours == float("inf")
        estimated_wait_hours: Optional[float] = None if is_infinite else raw_wait_hours
        estimated_wait_days: Optional[float] = (
            None if is_infinite else raw_wait_hours / HOURS_PER_DAY
        )

        # Yield during wait: 0 when wait is infinite (can't compute)
        if is_infinite or estimated_wait_days is None:
            yield_earned_during_wait_usd = 0.0
        else:
            yield_earned_during_wait_usd = (
                position_size_usd
                * (annual_yield_during_wait_pct / 100.0)
                * (estimated_wait_days / DAYS_PER_YEAR)
            )

        price_impact_usd = position_size_usd * (price_impact_risk_pct / 100.0)
        net_exit_value_usd = (
            position_size_usd + yield_earned_during_wait_usd - price_impact_usd
        )

        queue_risk_score = _compute_queue_risk_score(raw_wait_hours)
        queue_label = _compute_queue_label(raw_wait_hours)

        return {
            "protocol_name": protocol_name,
            "withdrawal_type": withdrawal_type,
            "queue_wait_hours": queue_wait_hours,
            "queue_size_usd": queue_size_usd,
            "daily_exit_capacity_usd": daily_exit_capacity_usd,
            "position_size_usd": position_size_usd,
            "annual_yield_during_wait_pct": annual_yield_during_wait_pct,
            "price_impact_risk_pct": price_impact_risk_pct,
            "estimated_wait_hours": estimated_wait_hours,
            "estimated_wait_days": estimated_wait_days,
            "yield_earned_during_wait_usd": yield_earned_during_wait_usd,
            "price_impact_usd": price_impact_usd,
            "net_exit_value_usd": net_exit_value_usd,
            "queue_risk_score": queue_risk_score,
            "queue_label": queue_label,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def analyze_and_log(
        self,
        withdrawal_type: str,
        queue_wait_hours: float,
        queue_size_usd: float,
        daily_exit_capacity_usd: float,
        position_size_usd: float,
        annual_yield_during_wait_pct: float,
        price_impact_risk_pct: float,
        protocol_name: str,
    ) -> Dict[str, Any]:
        """
        Analyze and append the result to the ring-buffer log
        (capped at LOG_MAX_ENTRIES via atomic write).
        """
        result = self.analyze(
            withdrawal_type,
            queue_wait_hours,
            queue_size_usd,
            daily_exit_capacity_usd,
            position_size_usd,
            annual_yield_during_wait_pct,
            price_impact_risk_pct,
            protocol_name,
        )
        entries = _load_log(self._log_path)
        entries.append(result)
        if len(entries) > LOG_MAX_ENTRIES:
            entries = entries[-LOG_MAX_ENTRIES:]
        _atomic_write(self._log_path, entries)
        return result

    def get_log(self) -> List[Dict[str, Any]]:
        """Return current log entries (empty list if log does not exist)."""
        return _load_log(self._log_path)
