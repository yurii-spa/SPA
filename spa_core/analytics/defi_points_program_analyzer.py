"""
MP-879 DeFiPointsProgramAnalyzer
Advisory/read-only analytics for DeFi points / pre-airdrop program evaluation.

Estimates fair value of points accrual, compares programs by points-per-dollar
efficiency, and assesses airdrop probability.

Outputs: data/points_program_log.json (ring-buffer 100 entries, atomic write)
"""

import json
import os
import time
from spa_core.utils.atomic import atomic_save

_DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
_LOG_FILE = "points_program_log.json"
_RING_BUFFER_MAX = 100


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(programs: list, config: dict = None) -> dict:
    """
    Analyze DeFi points / pre-airdrop programs.

    Parameters
    ----------
    programs : list of dict with keys:
        protocol, points_per_usd_per_day, total_points_issued,
        expected_airdrop_token_supply_pct, token_fdv_estimate_usd,
        days_remaining, capital_usd, holding_days, program_status,
        qualification_difficulty
    config : dict (optional)
        risk_discount_pct : float  (default 70)

    Returns
    -------
    dict with keys: programs, best_program, active_count,
                    average_implied_apy_pct, timestamp
    """
    cfg = config or {}
    risk_discount_pct = float(cfg.get("risk_discount_pct", 70.0))

    if not programs:
        return {
            "programs": [],
            "best_program": None,
            "active_count": 0,
            "average_implied_apy_pct": 0.0,
            "timestamp": time.time(),
        }

    # First pass: per-program metrics (with internal _capital_usd key)
    computed = [_compute_program(p, risk_discount_pct) for p in programs]

    # Second pass: efficiency scores (relative ranking)
    max_apy = max(c["implied_apy_pct"] for c in computed)
    for c in computed:
        if len(computed) == 1:
            c["efficiency_score"] = 100 if c["implied_apy_pct"] > 0 else 0
        elif max_apy > 0:
            c["efficiency_score"] = int(min(100, c["implied_apy_pct"] / max_apy * 100))
        else:
            c["efficiency_score"] = 0

    # Third pass: recommendations (uses _capital_usd and efficiency_score)
    for c in computed:
        c["recommendation"] = _build_recommendation(c)

    # Strip internal key before returning
    for c in computed:
        c.pop("_capital_usd", None)

    # Aggregate
    active = [c for c in computed if c["program_status"] == "ACTIVE"]
    active_count = len(active)
    best_program = (
        max(active, key=lambda c: c["implied_apy_pct"])["protocol"] if active else None
    )
    average_implied_apy = sum(c["implied_apy_pct"] for c in computed) / len(computed)

    return {
        "programs": computed,
        "best_program": best_program,
        "active_count": active_count,
        "average_implied_apy_pct": average_implied_apy,
        "timestamp": time.time(),
    }


def analyze_and_log(
    programs: list,
    config: dict = None,
    data_dir: str = None,
) -> dict:
    """Run analyze() and append result to ring-buffer log file."""
    result = analyze(programs, config)
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

def _compute_program(p: dict, risk_discount_pct: float) -> dict:
    """Compute all per-program metrics, including internal _capital_usd."""
    protocol = str(p.get("protocol", ""))
    points_per_usd_per_day = float(p.get("points_per_usd_per_day", 0.0))
    total_points_issued = float(p.get("total_points_issued", 0.0))
    expected_airdrop_token_supply_pct = float(p.get("expected_airdrop_token_supply_pct", 0.0))
    token_fdv_estimate_usd = float(p.get("token_fdv_estimate_usd", 0.0))
    days_remaining = int(p.get("days_remaining", 0))
    capital_usd = float(p.get("capital_usd", 0.0))
    holding_days = int(p.get("holding_days", 0))
    program_status = str(p.get("program_status", "ANNOUNCED")).upper()
    qualification_difficulty = str(p.get("qualification_difficulty", "MODERATE")).upper()

    # your_points
    if capital_usd > 0 and holding_days > 0:
        your_points = capital_usd * points_per_usd_per_day * holding_days
    else:
        your_points = 0.0

    # your_share_pct
    if total_points_issued > 0:
        your_share_pct = your_points / total_points_issued * 100.0
    else:
        your_share_pct = 0.0

    # gross_airdrop_value
    gross_airdrop_value_usd = (
        your_share_pct / 100.0
        * (expected_airdrop_token_supply_pct / 100.0)
        * token_fdv_estimate_usd
    )

    # discounted_value
    discounted_airdrop_value_usd = gross_airdrop_value_usd * (1.0 - risk_discount_pct / 100.0)

    # implied_daily_yield & implied_apy
    if capital_usd > 0 and holding_days > 0:
        implied_daily_yield_pct = discounted_airdrop_value_usd / capital_usd / holding_days * 100.0
    else:
        implied_daily_yield_pct = 0.0
    implied_apy_pct = implied_daily_yield_pct * 365.0

    # airdrop_probability_label
    airdrop_probability_label = _airdrop_probability(
        program_status, qualification_difficulty, days_remaining
    )

    return {
        "protocol": protocol,
        "program_status": program_status,
        "your_points": your_points,
        "your_share_of_total_pct": your_share_pct,
        "gross_airdrop_value_usd": gross_airdrop_value_usd,
        "discounted_airdrop_value_usd": discounted_airdrop_value_usd,
        "implied_daily_yield_pct": implied_daily_yield_pct,
        "implied_apy_pct": implied_apy_pct,
        "airdrop_probability_label": airdrop_probability_label,
        "efficiency_score": 0,       # filled in second pass
        "recommendation": "",        # filled in third pass
        "_capital_usd": capital_usd, # internal, stripped before return
    }


def _airdrop_probability(
    program_status: str, qualification_difficulty: str, days_remaining: int
) -> str:
    """Determine airdrop probability label."""
    if program_status == "ACTIVE":
        if qualification_difficulty in ("EASY", "MODERATE") and days_remaining > 0:
            return "HIGH"
        else:
            return "MODERATE"
    elif program_status in ("ANNOUNCED", "ENDED"):
        return "LOW"
    else:
        # RUMORED or any unknown
        return "SPECULATIVE"


def _build_recommendation(c: dict) -> str:
    """Build human-readable recommendation string."""
    label = c["airdrop_probability_label"]
    implied_apy = c["implied_apy_pct"]
    capital = c.get("_capital_usd", 0.0)

    if label == "HIGH":
        if implied_apy >= 20:
            return (
                f"Deploy {capital:.0f} USD. "
                f"High probability + {implied_apy:.1f}% implied APY."
            )
        else:
            return (
                f"Moderate returns expected. "
                f"{implied_apy:.1f}% APY at current participation."
            )
    elif label == "MODERATE":
        return f"Possible airdrop but competitive. Risk-adjusted yield: {implied_apy:.1f}%."
    elif label == "LOW":
        return "Lower certainty. Speculative position only."
    else:  # SPECULATIVE
        return "Rumored only. No capital deployment recommended."


# ---------------------------------------------------------------------------
# Ring-buffer log (atomic writes)
# ---------------------------------------------------------------------------

def _atomic_write_json(obj, path: str, dir_path: str) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(path, str(obj))
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
