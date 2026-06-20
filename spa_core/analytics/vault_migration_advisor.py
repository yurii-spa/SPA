"""
MP-802: VaultMigrationAdvisor
Evaluates whether migrating from a current vault to a target vault is
worthwhile after accounting for gas costs, slippage, and break-even time.

Pure stdlib only. Advisory/read-only. Atomic JSON writes via tmp+os.replace.
Ring-buffer cap: 100 entries.
"""
from __future__ import annotations

import json
import math
import os
import time
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_DATA_DIR = os.path.join(_REPO_ROOT, "data")
_LOG_FILE = os.path.join(_DATA_DIR, "vault_migration_log.json")

_RING_BUFFER_CAP = 100

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_DEFAULT_MAX_BREAK_EVEN_DAYS = 90


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _round4(value: float) -> float:
    return round(value, 4)


def _round2(value: float) -> float:
    return round(value, 2)


def _atomic_write_json(path: str, data: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(data, str(path))
def _append_to_ring_buffer(path: str, entry: Any, cap: int = _RING_BUFFER_CAP) -> None:
    """Append entry to ring-buffer JSON file, keeping at most `cap` entries."""
    try:
        with open(path, "r") as f:
            existing: list = json.load(f)
        if not isinstance(existing, list):
            existing = []
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    existing.append(entry)
    if len(existing) > cap:
        existing = existing[-cap:]

    _atomic_write_json(path, existing)


def _daily_yield_usd(position_usd: float, apy_pct: float) -> float:
    """Daily yield in USD: position * apy_pct / 100 / 365."""
    return position_usd * apy_pct / 100.0 / 365.0


def _evaluate_candidate(
    current_vault: Dict[str, Any],
    candidate: Dict[str, Any],
    position_usd: float,
    max_break_even_days: int,
) -> Dict[str, Any]:
    """
    Evaluate a single candidate vault against the current vault.

    Returns dict with all output fields for this candidate.
    """
    current_apy: float = float(current_vault.get("apy", 0.0))
    exit_cost_usd: float = float(current_vault.get("exit_cost_usd", 0.0))

    cand_name: str = str(candidate.get("name", ""))
    cand_apy: float = float(candidate.get("apy", 0.0))
    entry_cost_usd: float = float(candidate.get("entry_cost_usd", 0.0))

    apy_delta: float = cand_apy - current_apy
    total_migration_cost_usd: float = exit_cost_usd + entry_cost_usd

    current_daily: float = _daily_yield_usd(position_usd, current_apy)
    candidate_daily: float = _daily_yield_usd(position_usd, cand_apy)
    daily_yield_gain_usd: float = candidate_daily - current_daily

    # break_even_days
    if daily_yield_gain_usd > 0:
        break_even_days: Optional[float] = total_migration_cost_usd / daily_yield_gain_usd
    else:
        break_even_days = None

    # Recommendation logic
    if apy_delta <= 0:
        recommendation = "HOLD"
        reason = "Lower APY than current"
    elif break_even_days is not None and break_even_days <= max_break_even_days:
        recommendation = "MIGRATE"
        reason = f"Break-even in {break_even_days:.0f} days"
    else:
        recommendation = "MONITOR"
        if break_even_days is not None:
            reason = f"Break-even too long ({break_even_days:.0f} days)"
        else:
            reason = "No daily yield gain despite positive APY delta"

    return {
        "name": cand_name,
        "apy": _round4(cand_apy),
        "apy_delta": _round4(apy_delta),
        "daily_yield_gain_usd": _round4(daily_yield_gain_usd),
        "total_migration_cost_usd": _round4(total_migration_cost_usd),
        "break_even_days": _round4(break_even_days) if break_even_days is not None else None,
        "recommendation": recommendation,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(
    current_vault: Dict[str, Any],
    candidate_vaults: List[Dict[str, Any]],
    position_usd: float,
    config: Optional[Dict[str, Any]] = None,
    *,
    save: bool = False,
    data_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Evaluate vault migration candidates.

    Parameters
    ----------
    current_vault : dict with name, apy, exit_cost_usd
    candidate_vaults : list of dicts with name, apy, entry_cost_usd
    position_usd : float — capital to migrate
    config : optional dict with max_break_even_days (default 90)
    save : if True, append result to ring-buffer log file
    data_dir : override directory for log file

    Returns
    -------
    dict with current_vault, current_daily_yield_usd, candidates,
          best_candidate, immediate_action, summary_reason, timestamp
    """
    cfg = config or {}
    max_break_even_days: int = int(cfg.get("max_break_even_days", _DEFAULT_MAX_BREAK_EVEN_DAYS))
    position_usd = float(position_usd)
    timestamp = time.time()

    current_name: str = str(current_vault.get("name", ""))
    current_apy: float = float(current_vault.get("apy", 0.0))
    current_daily_yield_usd: float = _daily_yield_usd(position_usd, current_apy)

    # Edge: empty candidates
    if not candidate_vaults:
        result: Dict[str, Any] = {
            "current_vault": current_name,
            "current_daily_yield_usd": _round4(current_daily_yield_usd),
            "candidates": [],
            "best_candidate": None,
            "immediate_action": "STAY",
            "summary_reason": "No candidate vaults to evaluate",
            "timestamp": timestamp,
        }
        if save:
            _log_path = os.path.join(data_dir or _DATA_DIR, "vault_migration_log.json")
            _append_to_ring_buffer(_log_path, result)
        return result

    evaluated: List[Dict[str, Any]] = []
    for cand in candidate_vaults:
        evaluated.append(
            _evaluate_candidate(current_vault, cand, position_usd, max_break_even_days)
        )

    # Determine immediate_action
    has_migrate = any(c["recommendation"] == "MIGRATE" for c in evaluated)
    has_monitor = any(c["recommendation"] == "MONITOR" for c in evaluated)

    if has_migrate:
        immediate_action = "MIGRATE_NOW"
    elif has_monitor:
        immediate_action = "WAIT"
    else:
        immediate_action = "STAY"

    # best_candidate: highest apy_delta among MIGRATE recommendations
    migrate_candidates = [c for c in evaluated if c["recommendation"] == "MIGRATE"]
    if migrate_candidates:
        best_cand_name: Optional[str] = max(
            migrate_candidates, key=lambda c: c["apy_delta"]
        )["name"]
    else:
        best_cand_name = None

    # summary_reason
    if immediate_action == "MIGRATE_NOW":
        best = next(c for c in evaluated if c["name"] == best_cand_name)
        summary_reason = (
            f"Migrate to {best_cand_name}: {best['reason']}, "
            f"+{best['apy_delta']:.2f}% APY"
        )
    elif immediate_action == "WAIT":
        summary_reason = "Candidate vaults exist but break-even periods are too long; monitor for fee reduction"
    else:
        summary_reason = "All candidates offer lower or equal APY; stay in current vault"

    result = {
        "current_vault": current_name,
        "current_daily_yield_usd": _round4(current_daily_yield_usd),
        "candidates": evaluated,
        "best_candidate": best_cand_name,
        "immediate_action": immediate_action,
        "summary_reason": summary_reason,
        "timestamp": timestamp,
    }

    if save:
        _log_path = os.path.join(data_dir or _DATA_DIR, "vault_migration_log.json")
        _append_to_ring_buffer(_log_path, result)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="MP-802 VaultMigrationAdvisor")
    parser.add_argument("--run", action="store_true", help="Compute and save to log")
    parser.add_argument("--check", action="store_true", help="Compute only, no save (default)")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    save_flag = args.run and not args.check

    # Sample data
    current = {
        "name": "Aave V3 USDC",
        "apy": 3.5,
        "exit_cost_usd": 12.0,
    }
    candidates = [
        {"name": "Morpho Steakhouse", "apy": 6.5, "entry_cost_usd": 8.0},
        {"name": "Compound V3", "apy": 4.8, "entry_cost_usd": 5.0},
        {"name": "Yearn V3", "apy": 3.0, "entry_cost_usd": 7.0},
    ]
    position = 50000.0

    result = analyze(current, candidates, position, save=save_flag, data_dir=args.data_dir)
    print(json.dumps(result, indent=2))
    if save_flag:
        print("\n[MP-802] Logged to vault_migration_log.json", file=sys.stderr)
    sys.exit(0)
