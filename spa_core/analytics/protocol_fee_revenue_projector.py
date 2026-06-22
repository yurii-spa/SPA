"""
MP-880 ProtocolFeeRevenueProjector
Advisory/read-only analytics for projecting DeFi protocol fee revenue.

Projects protocol fee revenue 3–12 months forward based on TVL trends,
user growth, fee rates, and market cycle assumptions.

Outputs: data/fee_revenue_projection_log.json (ring-buffer 100 entries, atomic write)
"""

import json
import os
import time
from spa_core.utils.atomic import atomic_save

_DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
_LOG_FILE = "fee_revenue_projection_log.json"
_RING_BUFFER_MAX = 100

# Cycle multipliers
_CYCLE_MULTIPLIERS = {
    "BEAR": None,        # filled from config (default 0.5)
    "ACCUMULATION": 0.8,
    "BULL": None,        # filled from config (default 1.5)
    "PEAK": 1.2,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Project protocol fee revenue 3–12 months forward.

    Parameters
    ----------
    protocols : list of dict with keys:
        name, current_monthly_fee_usd, tvl_usd, tvl_growth_rate_30d_pct,
        fee_rate_bps, user_growth_rate_30d_pct, market_cycle_position
    config : dict (optional)
        projection_months : int    (default 6, not used in per-protocol logic but stored)
        bear_multiplier : float    (default 0.5)
        bull_multiplier : float    (default 1.5)

    Returns
    -------
    dict with keys: protocols, highest_revenue_protocol, fastest_growing,
                    total_projected_annual_usd, average_revenue_cagr_pct, timestamp
    """
    cfg = config or {}
    bear_mult = float(cfg.get("bear_multiplier", 0.5))
    bull_mult = float(cfg.get("bull_multiplier", 1.5))

    if not protocols:
        return {
            "protocols": [],
            "highest_revenue_protocol": None,
            "fastest_growing": None,
            "total_projected_annual_usd": 0.0,
            "average_revenue_cagr_pct": 0.0,
            "timestamp": time.time(),
        }

    computed = [_compute_protocol(p, bear_mult, bull_mult) for p in protocols]

    # Aggregates
    highest = max(computed, key=lambda c: c["projected_annual_fee_usd"])
    fastest = max(computed, key=lambda c: c["revenue_cagr_pct"])

    total_annual = sum(c["projected_annual_fee_usd"] for c in computed)
    avg_cagr = sum(c["revenue_cagr_pct"] for c in computed) / len(computed)

    return {
        "protocols": computed,
        "highest_revenue_protocol": highest["name"],
        "fastest_growing": fastest["name"],
        "total_projected_annual_usd": total_annual,
        "average_revenue_cagr_pct": avg_cagr,
        "timestamp": time.time(),
    }


def analyze_and_log(
    protocols: list,
    config: dict = None,
    data_dir: str = None,
) -> dict:
    """Run analyze() and append result to ring-buffer log file."""
    result = analyze(protocols, config)
    _append_log(result, data_dir or _DEFAULT_DATA_DIR)
    return result


def init_log(data_dir: str = None) -> None:
    """Initialize log file as empty list if it doesn't exist."""
    d = data_dir or _DEFAULT_DATA_DIR
    os.makedirs(d, exist_ok=True)
    log_path = os.path.join(d, _LOG_FILE)
    if not os.path.exists(log_path):
        _atomic_write_json([], log_path, d)


# ---------------------------------------------------------------------------
# Internal computation
# ---------------------------------------------------------------------------

def _cycle_multiplier(market_cycle: str, bear_mult: float, bull_mult: float) -> float:
    """Return cycle-adjusted multiplier for the given market cycle position."""
    mc = market_cycle.upper()
    if mc == "BEAR":
        return bear_mult
    elif mc == "ACCUMULATION":
        return 0.8
    elif mc == "BULL":
        return bull_mult
    elif mc == "PEAK":
        return 1.2
    else:
        return 1.0  # unknown → neutral


def _combined_monthly_growth(tvl_growth_pct: float, user_growth_pct: float) -> float:
    """Multiplicative combination of TVL and user monthly growth rates."""
    return (1.0 + tvl_growth_pct / 100.0) * (1.0 + user_growth_pct / 100.0) - 1.0


def _monthly_fee(
    current_fee: float,
    combined_growth: float,
    cycle_mult: float,
    month: int,
) -> float:
    """Fee at month m = current * (1 + combined_growth)^m * cycle_mult."""
    return current_fee * ((1.0 + combined_growth) ** month) * cycle_mult


def _growth_trajectory(combined_growth: float) -> str:
    """Classify growth trajectory."""
    if abs(combined_growth) > 0.15:
        return "VOLATILE"
    elif combined_growth > 0.05:
        return "ACCELERATING"
    elif combined_growth >= -0.02:
        return "STEADY"
    else:
        return "DECLINING"


def _sustainability_outlook(cagr_pct: float, market_cycle: str) -> str:
    """Classify sustainability outlook from CAGR and cycle position."""
    mc = market_cycle.upper()
    if cagr_pct >= 50 and mc in ("BULL", "ACCUMULATION"):
        return "STRONG"
    elif cagr_pct >= 20:
        return "POSITIVE"
    elif cagr_pct >= -10:
        return "NEUTRAL"
    elif cagr_pct >= -30:
        return "CONCERNING"
    else:
        return "AT_RISK"


def _projection_confidence(trajectory: str, market_cycle: str) -> str:
    """Classify projection confidence."""
    mc = market_cycle.upper()
    if trajectory == "STEADY" and mc in ("ACCUMULATION", "BULL"):
        return "HIGH"
    elif trajectory == "VOLATILE" or mc == "BEAR":
        return "LOW"
    else:
        return "MEDIUM"


def _compute_protocol(p: dict, bear_mult: float, bull_mult: float) -> dict:
    """Compute all metrics for a single protocol."""
    name = str(p.get("name", ""))
    current_fee = float(p.get("current_monthly_fee_usd", 0.0))
    tvl_usd = float(p.get("tvl_usd", 0.0))
    tvl_growth_pct = float(p.get("tvl_growth_rate_30d_pct", 0.0))
    fee_rate_bps = float(p.get("fee_rate_bps", 0.0))
    user_growth_pct = float(p.get("user_growth_rate_30d_pct", 0.0))
    market_cycle = str(p.get("market_cycle_position", "ACCUMULATION")).upper()

    cycle_mult = _cycle_multiplier(market_cycle, bear_mult, bull_mult)
    combined_growth = _combined_monthly_growth(tvl_growth_pct, user_growth_pct)
    trajectory = _growth_trajectory(combined_growth)

    # Monthly projections (months 1–12)
    if current_fee == 0.0:
        monthly_fees = [0.0] * 12
    else:
        monthly_fees = [
            _monthly_fee(current_fee, combined_growth, cycle_mult, m)
            for m in range(1, 13)
        ]

    fee_3m = monthly_fees[2]   # index 2 = month 3
    fee_6m = monthly_fees[5]   # index 5 = month 6
    fee_12m = monthly_fees[11] # index 11 = month 12
    annual_fee = sum(monthly_fees)

    # CAGR (simple: projected_12m / current - 1) * 100
    if current_fee > 0:
        cagr_pct = (fee_12m / current_fee - 1.0) * 100.0
    else:
        cagr_pct = 0.0

    outlook = _sustainability_outlook(cagr_pct, market_cycle)
    confidence = _projection_confidence(trajectory, market_cycle)

    return {
        "name": name,
        "current_monthly_fee_usd": current_fee,
        "projected_monthly_fee_3m_usd": fee_3m,
        "projected_monthly_fee_6m_usd": fee_6m,
        "projected_monthly_fee_12m_usd": fee_12m,
        "projected_annual_fee_usd": annual_fee,
        "growth_trajectory": trajectory,
        "cycle_adjusted_multiplier": cycle_mult,
        "revenue_cagr_pct": cagr_pct,
        "sustainability_outlook": outlook,
        "projection_confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Ring-buffer log (atomic writes)
# ---------------------------------------------------------------------------

def _atomic_write_json(obj, path: str, dir_path: str) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _append_log(entry: dict, data_dir: str) -> None:
    """Atomically append entry to ring-buffer log (max 100 entries)."""
    os.makedirs(data_dir, exist_ok=True)
    log_path = os.path.join(data_dir, _LOG_FILE)

    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        except (json.JSONDecodeError, OSError):
            log = []
    else:
        log = []

    log.append(entry)
    if len(log) > _RING_BUFFER_MAX:
        log = log[-_RING_BUFFER_MAX:]

    _atomic_write_json(log, log_path, data_dir)
