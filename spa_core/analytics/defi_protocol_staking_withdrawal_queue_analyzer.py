"""
MP-1102: DeFiProtocolStakingWithdrawalQueueAnalyzer
Analyzes Ethereum staking withdrawal queue depth and estimated wait time.
Long queues represent liquidity risk for unstaking positions.

Read-only/advisory — never modifies allocator/risk/execution.
Atomic writes to data/staking_withdrawal_queue_log.json (ring-buffer 100).
Pure stdlib only. No external dependencies.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

# ── constants ─────────────────────────────────────────────────────────────────
LOG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "staking_withdrawal_queue_log.json"
)
LOG_CAP = 100

ETH_PER_VALIDATOR: float = 32.0          # standard mainnet validator stake
SECONDS_PER_DAY: int = 86_400
DEFAULT_CHURN_LIMIT: int = 8             # validators exiting per epoch
DEFAULT_SECONDS_PER_EPOCH: int = 384     # mainnet value (~6.4 min)

# Label thresholds (days)
_LABEL_NO_QUEUE_MAX: float = 0.0
_LABEL_SHORT_WAIT_MAX: float = 2.0
_LABEL_MODERATE_WAIT_MAX: float = 7.0
_LABEL_LONG_WAIT_MAX: float = 30.0

# Decision thresholds
_SELL_LONG_WAIT_DAYS: float = 30.0
_SELL_HIGH_DISCOUNT_PCT: float = 2.0
_WAIT_SHORT_DAYS: float = 2.0
_WAIT_MODERATE_DAYS: float = 7.0
_WAIT_LOW_DISCOUNT_PCT: float = 0.5
_SELL_COMBO_DISCOUNT_PCT: float = 1.0

# Risk score normaliser (days at which score reaches ~100)
_RISK_NORMALISER_DAYS: float = 45.0
_RISK_DEPTH_BONUS_MAX: float = 10.0


# ── private helpers ───────────────────────────────────────────────────────────

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _epochs_per_day(seconds_per_epoch: int) -> float:
    """Return number of epochs per calendar day."""
    if seconds_per_epoch <= 0:
        raise ValueError(f"seconds_per_epoch must be > 0, got {seconds_per_epoch}")
    return SECONDS_PER_DAY / seconds_per_epoch


def _compute_estimated_wait_days(
    validators_in_exit_queue: int,
    churn_limit_per_epoch: int,
    seconds_per_epoch: int,
) -> float:
    """
    estimated_wait_days = (validators_in_exit_queue / churn_limit_per_epoch)
                          / epochs_per_day
    Returns 0.0 when queue is empty.
    """
    if validators_in_exit_queue <= 0:
        return 0.0
    if churn_limit_per_epoch <= 0:
        raise ValueError(
            f"churn_limit_per_epoch must be > 0, got {churn_limit_per_epoch}"
        )
    exit_epochs = validators_in_exit_queue / churn_limit_per_epoch
    epd = _epochs_per_day(seconds_per_epoch)
    return exit_epochs / epd


def _compute_queue_depth_ratio(
    validators_in_exit_queue: int,
    total_staked_eth: float,
) -> float:
    """
    Fraction of total validators currently in exit queue.
    total_validators_approx = total_staked_eth / ETH_PER_VALIDATOR
    Capped at 1.0.
    """
    if total_staked_eth <= 0:
        return 0.0
    total_validators = total_staked_eth / ETH_PER_VALIDATOR
    if validators_in_exit_queue <= 0:
        return 0.0
    return min(1.0, validators_in_exit_queue / total_validators)


def _withdrawal_label(wait_days: float) -> str:
    """Classify wait time into named category."""
    if wait_days <= _LABEL_NO_QUEUE_MAX:
        return "NO_QUEUE"
    if wait_days < _LABEL_SHORT_WAIT_MAX:
        return "SHORT_WAIT"
    if wait_days < _LABEL_MODERATE_WAIT_MAX:
        return "MODERATE_WAIT"
    if wait_days <= _LABEL_LONG_WAIT_MAX:
        return "LONG_WAIT"
    return "SEVERE_CONGESTION"


def _compute_withdrawal_risk_score(
    wait_days: float,
    queue_depth_ratio: float,
) -> int:
    """
    0–100 composite risk:
      base    = clamp(wait_days / RISK_NORMALISER_DAYS * 100, 0, 100)
      bonus   = clamp(queue_depth_ratio * RISK_DEPTH_BONUS_MAX, 0, RISK_DEPTH_BONUS_MAX)
      score   = min(100, int(base + bonus))
    """
    base = _clamp(wait_days / _RISK_NORMALISER_DAYS * 100.0)
    bonus = _clamp(
        queue_depth_ratio * _RISK_DEPTH_BONUS_MAX,
        0.0,
        _RISK_DEPTH_BONUS_MAX,
    )
    return min(100, int(base + bonus))


def _wait_vs_sell_decision(
    wait_days: float,
    lst_discount_pct: float,
) -> str:
    """
    Compare cost of waiting (liquidity lockup) vs cost of selling LST at discount.

    WAIT_FOR_WITHDRAWAL  — queue is short; saving the discount justifies waiting.
    SELL_ON_MARKET       — very long queue or discount too high relative to wait cost.
    BORDERLINE           — ambiguous trade-off; manual review recommended.
    """
    # Very short queue: always wait (save the discount)
    if wait_days <= _WAIT_SHORT_DAYS:
        return "WAIT_FOR_WITHDRAWAL"

    # Severely congested AND discount is significant → sell now
    if wait_days > _SELL_LONG_WAIT_DAYS and lst_discount_pct >= _SELL_COMBO_DISCOUNT_PCT:
        return "SELL_ON_MARKET"

    # Any queue with very high discount → sell now
    if lst_discount_pct >= _SELL_HIGH_DISCOUNT_PCT:
        return "SELL_ON_MARKET"

    # Severe congestion alone → sell
    if wait_days > _SELL_LONG_WAIT_DAYS:
        return "SELL_ON_MARKET"

    # Moderate wait and small discount → still worth waiting
    if wait_days <= _WAIT_MODERATE_DAYS and lst_discount_pct <= _WAIT_LOW_DISCOUNT_PCT:
        return "WAIT_FOR_WITHDRAWAL"

    return "BORDERLINE"


# ── I/O helpers ───────────────────────────────────────────────────────────────

def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp-file + os.replace."""
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_path or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _append_log(result: dict, log_path: str) -> None:
    """Append a summary entry; enforce ring-buffer cap."""
    existing: list = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if not isinstance(existing, list):
            existing = []
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    entry = {
        "ts": result.get("ts", datetime.now(timezone.utc).isoformat()),
        "protocol_name": result.get("protocol_name", ""),
        "estimated_wait_days": result.get("estimated_wait_days", 0.0),
        "withdrawal_label": result.get("withdrawal_label", ""),
        "withdrawal_risk_score": result.get("withdrawal_risk_score", 0),
        "wait_vs_sell_decision": result.get("wait_vs_sell_decision", ""),
        "my_position_usd": result.get("my_position_usd", 0.0),
    }
    existing.append(entry)
    if len(existing) > LOG_CAP:
        existing = existing[-LOG_CAP:]
    _atomic_write(log_path, existing)


# ── public class ──────────────────────────────────────────────────────────────

class DeFiProtocolStakingWithdrawalQueueAnalyzer:
    """
    Analyzes Ethereum staking withdrawal queue depth and estimated wait time.

    Input dict keys
    ---------------
    validators_in_exit_queue : int
        Number of validators currently queued for exit.
    churn_limit_per_epoch : int, optional
        Validators allowed to exit per epoch (default 8).
    seconds_per_epoch : int, optional
        Epoch duration in seconds (default 384, mainnet).
    total_staked_eth : float
        Total ETH staked network-wide (used to estimate total validator count).
    my_stake_eth : float
        Personal ETH position size.
    current_eth_price_usd : float
        Current ETH/USD spot price.
    lst_discount_pct : float
        Current LST secondary-market discount vs ETH (e.g. 0.1 for 0.1%).
    protocol_name : str
        Protocol identifier for logging.

    Returns
    -------
    dict with keys:
        protocol_name, ts,
        estimated_wait_days, my_position_usd, queue_depth_ratio,
        lst_discount_usd, wait_vs_sell_decision,
        withdrawal_risk_score, withdrawal_label
    """

    def analyze(self, data: dict, config: dict | None = None) -> dict:
        cfg = config or {}
        log_path = cfg.get("log_path", LOG_FILE)
        write_log = cfg.get("write_log", True)

        if not isinstance(data, dict):
            raise TypeError(f"data must be a dict, got {type(data).__name__}")

        # ── parse inputs ──────────────────────────────────────────────────────
        validators_in_exit_queue = int(data.get("validators_in_exit_queue", 0))
        churn_limit_per_epoch = int(
            data.get("churn_limit_per_epoch", DEFAULT_CHURN_LIMIT)
        )
        seconds_per_epoch = int(
            data.get("seconds_per_epoch", DEFAULT_SECONDS_PER_EPOCH)
        )
        total_staked_eth = float(data.get("total_staked_eth", 0.0))
        my_stake_eth = float(data.get("my_stake_eth", 0.0))
        current_eth_price_usd = float(data.get("current_eth_price_usd", 0.0))
        lst_discount_pct = float(data.get("lst_discount_pct", 0.0))
        protocol_name = str(data.get("protocol_name", "unknown"))

        # ── compute outputs ───────────────────────────────────────────────────
        wait_days = _compute_estimated_wait_days(
            validators_in_exit_queue, churn_limit_per_epoch, seconds_per_epoch
        )
        my_position_usd = round(my_stake_eth * current_eth_price_usd, 4)
        depth_ratio = round(
            _compute_queue_depth_ratio(validators_in_exit_queue, total_staked_eth), 6
        )
        lst_discount_usd = round(my_position_usd * lst_discount_pct / 100.0, 4)
        label = _withdrawal_label(wait_days)
        risk_score = _compute_withdrawal_risk_score(wait_days, depth_ratio)
        decision = _wait_vs_sell_decision(wait_days, lst_discount_pct)

        result = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "protocol_name": protocol_name,
            "estimated_wait_days": round(wait_days, 6),
            "my_position_usd": my_position_usd,
            "queue_depth_ratio": depth_ratio,
            "lst_discount_usd": lst_discount_usd,
            "wait_vs_sell_decision": decision,
            "withdrawal_risk_score": risk_score,
            "withdrawal_label": label,
        }

        if write_log:
            try:
                _append_log(result, log_path)
            except Exception:
                pass  # advisory — never raise on log failure

        return result
