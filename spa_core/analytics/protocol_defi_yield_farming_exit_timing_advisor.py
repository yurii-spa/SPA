"""
MP-1079: ProtocolDeFiYieldFarmingExitTimingAdvisor
===================================================
Advisory-only analytics module.

Advises on the optimal timing to exit a DeFi yield farming position by evaluating
the trade-off between current APY quality, trend direction, exit costs, unrealized
P&L, and token price performance.

Per position it computes:
  net_exit_value_usd           float  (USD received after all exit costs)
  opportunity_cost_pct         float  (positive = staying costs you; alt APY − fwd APY)
  days_to_recover_exit_costs   float  (days of daily yield to break even on exit costs)
  exit_urgency_score           0–100  (higher = exit sooner)
  timing_label                 HOLD_STRONG / HOLD_MONITOR / NEUTRAL /
                               CONSIDER_EXIT / EXIT_NOW

Urgency components (all clamped before summing):
  1. APY decline from entry    0–30   (relative decline fraction × 30)
  2. Negative APY trend 7d    0–25   (|trend| × 2.5 when falling)
  3. Low current APY penalty  0–20   (max(0, (8−APY) × 2.5))
  4. Token price decline      0–15   (|change| × 0.2 when falling)
  5. Negative unrealized PnL  0–15   (|PnL| × 0.3 when negative)
  Lock discount               0–10   (lock_remaining_days × 0.1, capped at 10)

Label thresholds:
  < 20  → HOLD_STRONG
  < 40  → HOLD_MONITOR
  < 55  → NEUTRAL
  < 70  → CONSIDER_EXIT
  ≥ 70  → EXIT_NOW

Baseline best-alternative APY (for opportunity_cost_pct): 5.0%

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/yield_farming_exit_timing_log.json
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
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "yield_farming_exit_timing_log.json",
)
LOG_MAX_ENTRIES = 100

# Baseline "best alternative" APY (T1 lending rate) used for opportunity cost
BEST_ALTERNATIVE_APY_PCT = 5.0

# Sentinel returned when daily yield is zero or negative (can't recover)
MAX_DAYS_TO_RECOVER = 9999.0

# Exit urgency label thresholds
URGENCY_HOLD_STRONG = 20.0
URGENCY_HOLD_MONITOR = 40.0
URGENCY_NEUTRAL = 55.0
URGENCY_CONSIDER_EXIT = 70.0


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _validate_position(pos: dict) -> None:
    """Validate the position input dict."""
    if not isinstance(pos, dict):
        raise ValueError("position must be a dict")
    required = {
        "protocol_name", "entry_date_days_ago", "entry_apy_pct", "current_apy_pct",
        "apy_trend_7d_pct", "unrealized_pnl_pct", "exit_fee_pct",
        "lock_remaining_days", "token_price_change_since_entry_pct",
        "gas_cost_exit_usd", "position_usd",
    }
    missing = required - set(pos.keys())
    if missing:
        raise ValueError(f"Missing required position fields: {sorted(missing)}")

    if not isinstance(pos["protocol_name"], str) or not pos["protocol_name"]:
        raise ValueError("'protocol_name' must be a non-empty string")

    # Float/int numeric fields (not bool)
    float_fields = (
        "entry_date_days_ago", "entry_apy_pct", "current_apy_pct",
        "apy_trend_7d_pct", "unrealized_pnl_pct", "exit_fee_pct",
        "token_price_change_since_entry_pct", "gas_cost_exit_usd", "position_usd",
    )
    for field in float_fields:
        val = pos[field]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError(
                f"'{field}' must be a number (int or float), got {type(val).__name__}"
            )

    # lock_remaining_days must be a non-bool int
    lrd = pos["lock_remaining_days"]
    if isinstance(lrd, bool) or not isinstance(lrd, int):
        raise ValueError(
            f"'lock_remaining_days' must be an int, got {type(lrd).__name__}"
        )

    # Range checks
    if pos["entry_date_days_ago"] < 0:
        raise ValueError("'entry_date_days_ago' must be >= 0")
    if pos["entry_apy_pct"] < 0:
        raise ValueError("'entry_apy_pct' must be >= 0")
    if pos["current_apy_pct"] < 0:
        raise ValueError("'current_apy_pct' must be >= 0")
    if not (0.0 <= float(pos["exit_fee_pct"]) <= 100.0):
        raise ValueError("'exit_fee_pct' must be in [0, 100]")
    if pos["lock_remaining_days"] < 0:
        raise ValueError("'lock_remaining_days' must be >= 0")
    if pos["gas_cost_exit_usd"] < 0:
        raise ValueError("'gas_cost_exit_usd' must be >= 0")
    if pos["position_usd"] < 0:
        raise ValueError("'position_usd' must be >= 0")


# ---------------------------------------------------------------------------
# Core computations
# ---------------------------------------------------------------------------

def _net_exit_value_usd(
    position_usd: float,
    unrealized_pnl_pct: float,
    exit_fee_pct: float,
    gas_cost_exit_usd: float,
) -> float:
    """
    Net USD received after exiting the position.

    gross_exit = position_usd × (1 + unrealized_pnl_pct / 100)
    exit_fee   = gross_exit × exit_fee_pct / 100
    net        = gross_exit − exit_fee − gas_cost_exit_usd
    """
    gross_exit = position_usd * (1.0 + unrealized_pnl_pct / 100.0)
    fee_amount = gross_exit * exit_fee_pct / 100.0
    return round(gross_exit - fee_amount - gas_cost_exit_usd, 2)


def _opportunity_cost_pct(current_apy_pct: float, apy_trend_7d_pct: float) -> float:
    """
    Annualised opportunity cost of staying vs the best alternative (5% baseline).

    forward_apy = current_apy_pct + apy_trend_7d_pct
    opportunity_cost = BEST_ALTERNATIVE_APY − forward_apy

    Positive  → staying costs you (alt is better)
    Negative  → staying is better than the baseline alternative
    """
    forward_apy = current_apy_pct + apy_trend_7d_pct
    return round(BEST_ALTERNATIVE_APY_PCT - forward_apy, 4)


def _days_to_recover_exit_costs(
    position_usd: float,
    unrealized_pnl_pct: float,
    exit_fee_pct: float,
    gas_cost_exit_usd: float,
    current_apy_pct: float,
) -> float:
    """
    Number of days of yield income needed to cover exit costs.

    exit_costs  = gross_exit × exit_fee_pct / 100 + gas_cost_exit_usd
    daily_yield = position_usd × current_apy_pct / 100 / 365

    Returns MAX_DAYS_TO_RECOVER (9999) when daily_yield <= 0.
    """
    gross_exit = position_usd * (1.0 + unrealized_pnl_pct / 100.0)
    exit_costs = gross_exit * exit_fee_pct / 100.0 + gas_cost_exit_usd
    daily_yield = position_usd * current_apy_pct / 100.0 / 365.0
    if daily_yield <= 0:
        return MAX_DAYS_TO_RECOVER
    return round(min(exit_costs / daily_yield, MAX_DAYS_TO_RECOVER), 2)


def _exit_urgency_score(
    entry_apy_pct: float,
    current_apy_pct: float,
    apy_trend_7d_pct: float,
    unrealized_pnl_pct: float,
    token_price_change_since_entry_pct: float,
    lock_remaining_days: int,
) -> float:
    """
    Composite exit urgency score (0–100). Higher = exit sooner.

    Components:
    1. APY decline from entry (0–30)
       — fractional decline × 100 × 0.30, capped at 30
    2. Negative APY trend 7d (0–25)
       — |trend| × 2.5, only when apy_trend_7d_pct < 0
    3. Low current APY penalty (0–20)
       — max(0, (8 − current_apy_pct) × 2.5), capped at 20
    4. Token price decline (0–15)
       — |change| × 0.20, only when token_price_change < 0, capped at 15
    5. Negative unrealized PnL (0–15)
       — |pnl| × 0.30, only when unrealized_pnl_pct < 0, capped at 15
    Lock discount (0–10)
       — lock_remaining_days × 0.10, capped at 10

    Final score clamped to [0, 100].
    """
    # 1. APY decline from entry
    if entry_apy_pct > 0:
        decline_frac = max(0.0, entry_apy_pct - current_apy_pct) / entry_apy_pct
    else:
        decline_frac = 0.0
    apy_decline_score = min(decline_frac * 100.0 * 0.30, 30.0)

    # 2. Negative APY trend
    trend_score = min(abs(apy_trend_7d_pct) * 2.5, 25.0) if apy_trend_7d_pct < 0 else 0.0

    # 3. Low current APY quality
    apy_quality_score = min(max(0.0, (8.0 - current_apy_pct) * 2.5), 20.0)

    # 4. Token price decline
    token_score = (
        min(abs(token_price_change_since_entry_pct) * 0.20, 15.0)
        if token_price_change_since_entry_pct < 0
        else 0.0
    )

    # 5. Negative unrealized PnL
    pnl_score = (
        min(abs(unrealized_pnl_pct) * 0.30, 15.0)
        if unrealized_pnl_pct < 0
        else 0.0
    )

    # Lock discount
    lock_discount = min(lock_remaining_days * 0.10, 10.0)

    raw = (
        apy_decline_score + trend_score + apy_quality_score
        + token_score + pnl_score - lock_discount
    )
    return round(max(0.0, min(raw, 100.0)), 2)


def _timing_label(urgency: float) -> str:
    """Classify exit timing urgency into a human-readable label."""
    if urgency < URGENCY_HOLD_STRONG:
        return "HOLD_STRONG"
    if urgency < URGENCY_HOLD_MONITOR:
        return "HOLD_MONITOR"
    if urgency < URGENCY_NEUTRAL:
        return "NEUTRAL"
    if urgency < URGENCY_CONSIDER_EXIT:
        return "CONSIDER_EXIT"
    return "EXIT_NOW"


# ---------------------------------------------------------------------------
# Main advisor class
# ---------------------------------------------------------------------------

class ProtocolDeFiYieldFarmingExitTimingAdvisor:
    """
    Advisory module that recommends the optimal timing to exit a DeFi yield
    farming position. Read-only / no execution side-effects.
    """

    def analyze(self, position: dict, config: Optional[dict] = None) -> dict:
        """
        Parameters
        ----------
        position : dict
            Required keys:
                protocol_name                       str   (non-empty)
                entry_date_days_ago                 float (>= 0)
                entry_apy_pct                       float (>= 0)
                current_apy_pct                     float (>= 0)
                apy_trend_7d_pct                    float (positive=rising, negative=falling)
                unrealized_pnl_pct                  float (total PnL on position_usd)
                exit_fee_pct                        float (0–100)
                lock_remaining_days                 int   (>= 0; 0 = no lock)
                token_price_change_since_entry_pct  float
                gas_cost_exit_usd                   float (>= 0)
                position_usd                        float (>= 0; original principal)

        config : dict, optional
            Reserved for future overrides.

        Returns
        -------
        dict with keys:
            protocol_name                str
            net_exit_value_usd           float
            opportunity_cost_pct         float  (positive = staying costs you)
            days_to_recover_exit_costs   float  (9999 if daily_yield <= 0)
            exit_urgency_score           float  0–100
            timing_label                 str    HOLD_STRONG | HOLD_MONITOR |
                                                NEUTRAL | CONSIDER_EXIT | EXIT_NOW
            lock_remaining_days          int
            analyzed_at                  str    ISO-8601 UTC timestamp
        """
        if config is None:
            config = {}

        _validate_position(position)

        entry_apy = float(position["entry_apy_pct"])
        current_apy = float(position["current_apy_pct"])
        apy_trend = float(position["apy_trend_7d_pct"])
        unrealized_pnl = float(position["unrealized_pnl_pct"])
        exit_fee = float(position["exit_fee_pct"])
        lock_days = int(position["lock_remaining_days"])
        token_price_chg = float(position["token_price_change_since_entry_pct"])
        gas_cost = float(position["gas_cost_exit_usd"])
        pos_usd = float(position["position_usd"])

        net_value = _net_exit_value_usd(pos_usd, unrealized_pnl, exit_fee, gas_cost)
        opp_cost = _opportunity_cost_pct(current_apy, apy_trend)
        days_recover = _days_to_recover_exit_costs(
            pos_usd, unrealized_pnl, exit_fee, gas_cost, current_apy
        )
        urgency = _exit_urgency_score(
            entry_apy, current_apy, apy_trend, unrealized_pnl,
            token_price_chg, lock_days
        )
        label = _timing_label(urgency)

        output = {
            "protocol_name": position["protocol_name"],
            "net_exit_value_usd": net_value,
            "opportunity_cost_pct": opp_cost,
            "days_to_recover_exit_costs": days_recover,
            "exit_urgency_score": urgency,
            "timing_label": label,
            "lock_remaining_days": lock_days,
            "analyzed_at": _iso_now(),
        }

        _append_log(output)
        return output


# ---------------------------------------------------------------------------
# Ring-buffer log helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    t = time.gmtime()
    return (
        f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T"
        f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"
    )


def _atomic_write(path: str, data: object) -> None:
    """Write JSON atomically using tmp + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dir_ = os.path.dirname(path)
    atomic_save(data, str(path))
def _init_log(path: str) -> list:
    """Load existing ring-buffer log or return empty list."""
    if os.path.exists(path):
        try:
            with open(path, "r") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _append_log(result: dict, log_path: str = LOG_PATH) -> None:
    """Append a snapshot to the ring-buffer log (capped at LOG_MAX_ENTRIES)."""
    entries = _init_log(log_path)
    snapshot = {
        "ts": result.get("analyzed_at", _iso_now()),
        "protocol_name": result.get("protocol_name"),
        "net_exit_value_usd": result.get("net_exit_value_usd"),
        "exit_urgency_score": result.get("exit_urgency_score"),
        "timing_label": result.get("timing_label"),
        "days_to_recover_exit_costs": result.get("days_to_recover_exit_costs"),
    }
    entries.append(snapshot)
    if len(entries) > LOG_MAX_ENTRIES:
        entries = entries[-LOG_MAX_ENTRIES:]
    try:
        _atomic_write(log_path, entries)
    except OSError:
        pass  # advisory — never crash on log failure


# ---------------------------------------------------------------------------
# Module-level convenience alias
# ---------------------------------------------------------------------------

def analyze(position: dict, config: Optional[dict] = None) -> dict:
    """Module-level shorthand — delegates to ProtocolDeFiYieldFarmingExitTimingAdvisor."""
    return ProtocolDeFiYieldFarmingExitTimingAdvisor().analyze(position, config)
