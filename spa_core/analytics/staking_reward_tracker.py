"""
MP-786 StakingRewardTracker
Tracks staking rewards accumulation and effective yield across
compounding frequencies (DAILY/WEEKLY/MONTHLY/NONE), lock periods,
and early-exit penalty scenarios.

Ring-buffer log (cap 100), atomic writes, stdlib only.
"""

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_COMPOUND_FREQ: Dict[str, int] = {
    "DAILY": 365,
    "WEEKLY": 52,
    "MONTHLY": 12,
    "NONE": 1,
}

_LOG_CAP = 100

_DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)

_LOG_FILE = "staking_reward_log.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp-file + os.replace."""
    dir_ = os.path.dirname(path) or "."
    atomic_save(data, str(path))
def _load_log(path: str) -> List[Dict]:
    """Load ring-buffer log from disk, return empty list if missing/corrupt."""
    try:
        with open(path) as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _append_log(path: str, entry: Dict, cap: int = _LOG_CAP) -> None:
    """Append entry to ring-buffer log, trim to cap, atomic write."""
    log = _load_log(path)
    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]
    _atomic_write(path, log)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _effective_apy(reward_rate_daily_pct: float, compound_frequency: str) -> float:
    """
    Compute effective APY using compound interest formula:
        effective_apy = (1 + daily_rate/freq)^freq - 1

    daily_rate is converted to annual: daily_pct/100 * 365 = annual_rate.
    Then:  freq_rate = annual_rate / freq
           effective_apy = (1 + freq_rate)^freq - 1
    """
    freq = _COMPOUND_FREQ.get(compound_frequency.upper(), 1)
    # Convert daily pct to annual decimal
    annual_rate = (reward_rate_daily_pct / 100.0) * 365.0
    if freq == 1:
        # No intra-year compounding — simple annual rate
        return annual_rate
    freq_rate = annual_rate / freq
    return (1.0 + freq_rate) ** freq - 1.0


def _lock_attractiveness(
    effective_apy: float,
    early_exit_penalty_pct: float,
    lock_period_days: int,
) -> float:
    """
    Score 0-100.
    - APY component  (0-50): 50 pts at ≥30 % APY
    - Penalty component (0-30): 30 pts for 0% penalty, 0 pts for ≥100%
    - Lock component (0-20): 20 pts for 0 days, 0 pts for ≥365 days
    """
    apy_score = min(effective_apy / 0.30, 1.0) * 50.0
    penalty_score = max(0.0, 1.0 - early_exit_penalty_pct / 100.0) * 30.0
    lock_score = max(0.0, 1.0 - lock_period_days / 365.0) * 20.0
    raw = apy_score + penalty_score + lock_score
    return round(min(max(raw, 0.0), 100.0), 4)


# ---------------------------------------------------------------------------
# StakingRewardTracker
# ---------------------------------------------------------------------------

class StakingRewardTracker:
    """
    Tracks staking rewards, compounding, exit costs, and attractiveness.

    Usage
    -----
    tracker = StakingRewardTracker()
    result  = tracker.track(staking_data, holding_days=30)
    print(tracker.get_effective_apy())
    print(tracker.get_exit_analysis())
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        self._data_dir = data_dir or _DEFAULT_DATA_DIR
        self._log_path = os.path.join(self._data_dir, _LOG_FILE)
        self._last_result: Optional[Dict] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def track(self, staking_data: Dict, holding_days: int = 30) -> Dict:
        """
        Compute all staking metrics for the given staking_data dict.

        Required keys
        -------------
        protocol                  : str
        staked_amount_usd         : float  (USD principal)
        reward_rate_daily_pct     : float  (daily reward %)
        compound_frequency        : str    DAILY|WEEKLY|MONTHLY|NONE
        lock_period_days          : int
        early_exit_penalty_pct    : float  (% of staked amount)

        Returns the result dict and appends to the ring-buffer log.
        """
        self._validate(staking_data)

        protocol = staking_data["protocol"]
        staked = float(staking_data["staked_amount_usd"])
        daily_pct = float(staking_data["reward_rate_daily_pct"])
        cf = staking_data.get("compound_frequency", "DAILY").upper()
        lock_days = int(staking_data.get("lock_period_days", 0))
        penalty_pct = float(staking_data.get("early_exit_penalty_pct", 0.0))

        eff_apy = _effective_apy(daily_pct, cf)

        # total_rewards over holding_days period
        total_rewards = staked * eff_apy / 365.0 * holding_days

        # Exit cost: only applies if still within lock period
        within_lock = holding_days < lock_days
        exit_cost_usd = staked * penalty_pct / 100.0 if within_lock else 0.0

        # net APY after exit cost expressed as a return rate
        # exit_cost / staked → fractional penalty; annualised relative to holding days
        if holding_days > 0 and within_lock:
            exit_penalty_annualised = (exit_cost_usd / staked) * (365.0 / holding_days)
        else:
            exit_penalty_annualised = 0.0

        net_apy = eff_apy - exit_penalty_annualised

        attractiveness = _lock_attractiveness(eff_apy, penalty_pct, lock_days)

        result = {
            "protocol": protocol,
            "staked_amount_usd": staked,
            "reward_rate_daily_pct": daily_pct,
            "compound_frequency": cf,
            "lock_period_days": lock_days,
            "early_exit_penalty_pct": penalty_pct,
            "holding_days": holding_days,
            # computed
            "effective_apy": round(eff_apy, 6),
            "effective_apy_pct": round(eff_apy * 100.0, 4),
            "total_rewards_30d": round(staked * eff_apy / 365.0 * 30.0, 4),
            "total_rewards_holding": round(total_rewards, 4),
            "within_lock_period": within_lock,
            "exit_cost_usd": round(exit_cost_usd, 4),
            "net_apy_after_exit_cost": round(net_apy, 6),
            "net_apy_after_exit_cost_pct": round(net_apy * 100.0, 4),
            "lock_attractiveness_score": attractiveness,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

        self._last_result = result
        _append_log(self._log_path, result)
        return result

    def get_effective_apy(self) -> Optional[Dict]:
        """
        Return the APY summary from the most recent track() call.
        Returns None if track() has not been called.
        """
        if self._last_result is None:
            return None
        r = self._last_result
        return {
            "protocol": r["protocol"],
            "compound_frequency": r["compound_frequency"],
            "reward_rate_daily_pct": r["reward_rate_daily_pct"],
            "effective_apy": r["effective_apy"],
            "effective_apy_pct": r["effective_apy_pct"],
        }

    def get_exit_analysis(self) -> Optional[Dict]:
        """
        Return the exit-cost analysis from the most recent track() call.
        Returns None if track() has not been called.
        """
        if self._last_result is None:
            return None
        r = self._last_result
        return {
            "protocol": r["protocol"],
            "staked_amount_usd": r["staked_amount_usd"],
            "holding_days": r["holding_days"],
            "lock_period_days": r["lock_period_days"],
            "within_lock_period": r["within_lock_period"],
            "early_exit_penalty_pct": r["early_exit_penalty_pct"],
            "exit_cost_usd": r["exit_cost_usd"],
            "effective_apy_pct": r["effective_apy_pct"],
            "net_apy_after_exit_cost_pct": r["net_apy_after_exit_cost_pct"],
            "lock_attractiveness_score": r["lock_attractiveness_score"],
        }

    def get_log(self) -> List[Dict]:
        """Return the full ring-buffer log from disk."""
        return _load_log(self._log_path)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(data: Dict) -> None:
        required = [
            "protocol",
            "staked_amount_usd",
            "reward_rate_daily_pct",
            "compound_frequency",
            "lock_period_days",
            "early_exit_penalty_pct",
        ]
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"Missing required keys: {missing}")

        cf = str(data.get("compound_frequency", "")).upper()
        if cf not in _COMPOUND_FREQ:
            raise ValueError(
                f"compound_frequency must be one of {list(_COMPOUND_FREQ.keys())}, got '{cf}'"
            )

        staked = float(data["staked_amount_usd"])
        if staked <= 0:
            raise ValueError("staked_amount_usd must be > 0")

        daily = float(data["reward_rate_daily_pct"])
        if daily < 0:
            raise ValueError("reward_rate_daily_pct must be >= 0")

        penalty = float(data["early_exit_penalty_pct"])
        if not (0.0 <= penalty <= 100.0):
            raise ValueError("early_exit_penalty_pct must be in [0, 100]")

        lock = int(data["lock_period_days"])
        if lock < 0:
            raise ValueError("lock_period_days must be >= 0")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    sample = {
        "protocol": "Lido",
        "staked_amount_usd": 50000.0,
        "reward_rate_daily_pct": 0.01096,   # ~4% APY simple
        "compound_frequency": "DAILY",
        "lock_period_days": 90,
        "early_exit_penalty_pct": 2.0,
    }

    tracker = StakingRewardTracker()
    result = tracker.track(sample, holding_days=30)

    print("=== StakingRewardTracker ===")
    for k, v in result.items():
        print(f"  {k}: {v}")

    print("\n=== Effective APY ===")
    print(tracker.get_effective_apy())

    print("\n=== Exit Analysis ===")
    print(tracker.get_exit_analysis())
