"""
MP-821 ProtocolIncentiveDecayMonitor
=====================================
Monitors DeFi liquidity mining / incentive programs to detect APY decay curves
and predict exit timing before rewards dry up.

Advisory / read-only. Pure stdlib. Atomic writes. Ring-buffer log (cap=100).
"""

import json
import os
import time
import datetime
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_EXIT_APY_THRESHOLD = 5.0    # %
DEFAULT_DECAY_WARNING_DAYS = 14

LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "incentive_decay_log.json"
)
LOG_PATH = os.path.normpath(LOG_PATH)
LOG_CAP = 100


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(protocol: str, incentive_program: dict, config: dict = None) -> dict:
    """
    Analyse a DeFi incentive / liquidity-mining program and return an exit signal.

    Parameters
    ----------
    protocol : str
        Human-readable protocol name (e.g. "Aave V3").
    incentive_program : dict
        {
            "name": str,
            "start_date": str,          # "YYYY-MM-DD"
            "end_date": str | None,     # None = ongoing
            "initial_apy": float,
            "current_apy": float,
            "token_budget_usd": float,  # total token budget
            "spent_usd": float,         # already distributed
            "daily_emission_usd": float,
            "tvl_usd": float
        }
    config : dict, optional
        {
            "exit_apy_threshold": float,   # default 5.0
            "decay_warning_days": int      # default 14
        }

    Returns
    -------
    dict  — see module docstring / spec.
    """
    cfg = config or {}
    exit_threshold = float(cfg.get("exit_apy_threshold", DEFAULT_EXIT_APY_THRESHOLD))
    decay_warning_days = int(cfg.get("decay_warning_days", DEFAULT_DECAY_WARNING_DAYS))

    # ---- parse dates ---------------------------------------------------
    today = datetime.date.today()

    start_date_str = incentive_program.get("start_date", "")
    try:
        start_date = datetime.date.fromisoformat(start_date_str)
    except (ValueError, TypeError):
        start_date = today

    end_date_str = incentive_program.get("end_date")
    end_date = None
    if end_date_str:
        try:
            end_date = datetime.date.fromisoformat(end_date_str)
        except (ValueError, TypeError):
            end_date = None

    # ---- elapsed / remaining -------------------------------------------
    raw_elapsed = (today - start_date).days
    days_elapsed = max(0, raw_elapsed)

    days_remaining: "int | None"
    if end_date is not None:
        days_remaining = (end_date - today).days
    else:
        days_remaining = None

    # ---- budget math ---------------------------------------------------
    token_budget = float(incentive_program.get("token_budget_usd", 0.0))
    spent = float(incentive_program.get("spent_usd", 0.0))
    daily_emission = float(incentive_program.get("daily_emission_usd", 0.0))

    budget_remaining = max(0.0, token_budget - spent)

    if token_budget > 0:
        budget_utilization_pct = (spent / token_budget) * 100.0
    else:
        budget_utilization_pct = 0.0

    if daily_emission > 0:
        days_until_budget_exhausted: "float | None" = budget_remaining / daily_emission
    else:
        days_until_budget_exhausted = None

    # ---- APY metrics ---------------------------------------------------
    initial_apy = float(incentive_program.get("initial_apy", 0.0))
    current_apy = float(incentive_program.get("current_apy", 0.0))

    if initial_apy > 0:
        apy_decay_pct = ((initial_apy - current_apy) / initial_apy) * 100.0
    else:
        apy_decay_pct = 0.0

    # ---- effective_end_days --------------------------------------------
    effective_end_days: "float | None"
    if days_remaining is not None and days_until_budget_exhausted is not None:
        effective_end_days = min(float(days_remaining), days_until_budget_exhausted)
    elif days_remaining is not None:
        effective_end_days = float(days_remaining)
    elif days_until_budget_exhausted is not None:
        effective_end_days = days_until_budget_exhausted
    else:
        effective_end_days = None

    # ---- projected_apy_30d ---------------------------------------------
    if budget_remaining > 0:
        budget_in_30d = budget_remaining - 30.0 * daily_emission
        if budget_in_30d <= 0:
            projected_apy_30d = 0.0
        else:
            projected_apy_30d = current_apy * (budget_in_30d / budget_remaining)
    else:
        projected_apy_30d = 0.0

    # ---- status --------------------------------------------------------
    if budget_remaining <= 0:
        status = "EXHAUSTED"
    elif (
        (days_until_budget_exhausted is not None and days_until_budget_exhausted < 7)
        or (days_remaining is not None and days_remaining < 7)
    ):
        status = "CRITICAL"
    elif apy_decay_pct > 30:
        status = "DECAYING"
    else:
        status = "ACTIVE"

    # ---- exit_signal ---------------------------------------------------
    exit_signal = projected_apy_30d < exit_threshold

    # ---- risk_flags ----------------------------------------------------
    risk_flags = []
    if budget_utilization_pct > 80:
        risk_flags.append("Budget >80% consumed")
    if (
        days_until_budget_exhausted is not None
        and days_until_budget_exhausted < decay_warning_days
    ):
        risk_flags.append(
            f"Budget exhausted in <{decay_warning_days} days"
        )
    if apy_decay_pct > 50:
        risk_flags.append(f"APY decayed {apy_decay_pct:.0f}% from initial")
    if current_apy < exit_threshold:
        risk_flags.append("Current APY below exit threshold")

    # ---- recommendation ------------------------------------------------
    if status == "EXHAUSTED" or (
        exit_signal and projected_apy_30d < exit_threshold / 2.0
    ):
        recommendation = "EXIT_NOW"
    elif exit_signal:
        recommendation = "PREPARE_EXIT"
    elif status in ("DECAYING", "CRITICAL"):
        recommendation = "MONITOR"
    else:
        recommendation = "HOLD"

    result = {
        "protocol": protocol,
        "program_name": incentive_program.get("name", ""),
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "budget_remaining_usd": budget_remaining,
        "budget_utilization_pct": round(budget_utilization_pct, 4),
        "days_until_budget_exhausted": days_until_budget_exhausted,
        "apy_decay_pct": round(apy_decay_pct, 4),
        "effective_end_days": effective_end_days,
        "projected_apy_30d": round(projected_apy_30d, 6),
        "status": status,
        "exit_signal": exit_signal,
        "risk_flags": risk_flags,
        "recommendation": recommendation,
        "timestamp": time.time(),
    }
    return result


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _ensure_log_dir():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)


def _load_log() -> list:
    if not os.path.exists(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_log(entries: list):
    _ensure_log_dir()
    # ring-buffer cap
    if len(entries) > LOG_CAP:
        entries = entries[-LOG_CAP:]
    atomic_save(entries, str(LOG_PATH))
def log_result(result: dict):
    """Append *result* to the ring-buffer log at data/incentive_decay_log.json."""
    entries = _load_log()
    entries.append(result)
    _save_log(entries)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_demo():
    program = {
        "name": "AAVE Liquidity Mining Season 2",
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "initial_apy": 20.0,
        "current_apy": 12.0,
        "token_budget_usd": 1_000_000.0,
        "spent_usd": 850_000.0,
        "daily_emission_usd": 2_000.0,
        "tvl_usd": 50_000_000.0,
    }
    result = analyze("Aave V3", program)
    print(json.dumps(result, indent=2))
    log_result(result)
    print(f"\nLogged to {LOG_PATH}")


if __name__ == "__main__":
    _cli_demo()
