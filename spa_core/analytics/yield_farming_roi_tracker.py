"""
Yield Farming ROI Tracker — ADVISORY ONLY (MP-814).

Tracks total ROI of a yield farming position including initial gas cost, ongoing
gas for harvesting, impermanent loss, and token rewards.

Design constraints
------------------
* Pure stdlib — no external deps.
* Advisory only — never touches allocator / risk / execution.
* Atomic writes — tmp + os.replace on every JSON update.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* Ring-buffer JSON log capped at 100 entries.

CLI
---
    python3 -m spa_core.analytics.yield_farming_roi_tracker --check
    python3 -m spa_core.analytics.yield_farming_roi_tracker --run
    python3 -m spa_core.analytics.yield_farming_roi_tracker --run --data-dir /path/to/data
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Project root & paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_LOG_FILE = "farming_roi_log.json"
_LOG_CAP = 100

# ---------------------------------------------------------------------------
# Performance thresholds (actual_apy)
# ---------------------------------------------------------------------------

_PERF_EXCELLENT_APY = 20.0
_PERF_GOOD_APY = 10.0
_PERF_FAIR_APY = 5.0
_PERF_POOR_APY = 0.0

# Minimum actual_apy for continue_farming
_CONTINUE_MIN_APY = 5.0

# Minimum days guard to avoid division-by-zero
_MIN_DAYS = 0.001


# ---------------------------------------------------------------------------
# Core analyze function
# ---------------------------------------------------------------------------

def analyze(farm: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Analyze the ROI of a yield farming position.

    Parameters
    ----------
    farm : dict with farming position data
    config : optional {tax_rate_pct}

    Returns
    -------
    dict with full ROI analysis.
    """
    cfg = config or {}
    tax_rate_pct: float = float(cfg.get("tax_rate_pct", 0.0))

    # Extract farm fields
    protocol: str = str(farm.get("protocol", ""))
    pair: str = str(farm.get("pair", ""))
    initial_investment_usd: float = float(farm.get("initial_investment_usd", 0.0))
    entry_gas_usd: float = float(farm.get("entry_gas_usd", 0.0))
    days_elapsed: float = float(farm.get("days_elapsed", 0.0))
    base_apy: float = float(farm.get("base_apy", 0.0))
    reward_apy: float = float(farm.get("reward_apy", 0.0))
    current_value_usd: float = float(farm.get("current_value_usd", 0.0))
    harvested_rewards_usd: float = float(farm.get("harvested_rewards_usd", 0.0))
    harvest_gas_total_usd: float = float(farm.get("harvest_gas_total_usd", 0.0))
    pending_rewards_usd: float = float(farm.get("pending_rewards_usd", 0.0))

    # Guard against division by zero
    effective_days = max(days_elapsed, _MIN_DAYS)
    effective_investment = initial_investment_usd if initial_investment_usd != 0.0 else 1.0

    # -------------------------------------------------------------------
    # P&L calculations
    # -------------------------------------------------------------------

    unrealized_position_usd = current_value_usd - initial_investment_usd
    total_rewards_usd = harvested_rewards_usd + pending_rewards_usd
    gas_costs_usd = entry_gas_usd + harvest_gas_total_usd
    tax_cost_usd = total_rewards_usd * tax_rate_pct / 100.0
    net_pnl_usd = unrealized_position_usd + total_rewards_usd - gas_costs_usd - tax_cost_usd
    net_pnl_pct = net_pnl_usd / effective_investment * 100.0

    # -------------------------------------------------------------------
    # APY analysis
    # -------------------------------------------------------------------

    # Actual annualized APY
    actual_apy = (net_pnl_usd / effective_investment) * (365.0 / effective_days) * 100.0

    # Projected APY (as stated)
    projected_apy = base_apy + reward_apy

    # APY gap (positive means underperforming)
    apy_gap_pct = projected_apy - actual_apy

    # Impermanent loss: if current_value < initial_investment, the difference is IL
    il_estimated_usd = max(0.0, initial_investment_usd - current_value_usd)
    il_pct = (il_estimated_usd / effective_investment * 100.0) if il_estimated_usd > 0.0 else 0.0

    # -------------------------------------------------------------------
    # Performance rating
    # -------------------------------------------------------------------

    if actual_apy >= _PERF_EXCELLENT_APY:
        performance = "EXCELLENT"
    elif actual_apy >= _PERF_GOOD_APY:
        performance = "GOOD"
    elif actual_apy >= _PERF_FAIR_APY:
        performance = "FAIR"
    elif actual_apy >= _PERF_POOR_APY:
        performance = "POOR"
    else:
        performance = "LOSS"

    # -------------------------------------------------------------------
    # Continue farming decision
    # actual_apy > 5% AND net_pnl_usd >= -entry_gas_usd
    # -------------------------------------------------------------------

    continue_farming = (actual_apy > _CONTINUE_MIN_APY) and (net_pnl_usd >= -entry_gas_usd)

    return {
        "protocol": protocol,
        "pair": pair,
        "days_elapsed": days_elapsed,
        "pnl": {
            "unrealized_position_usd": round(unrealized_position_usd, 6),
            "harvested_rewards_usd": round(harvested_rewards_usd, 6),
            "pending_rewards_usd": round(pending_rewards_usd, 6),
            "total_rewards_usd": round(total_rewards_usd, 6),
            "gas_costs_usd": round(gas_costs_usd, 6),
            "tax_cost_usd": round(tax_cost_usd, 6),
            "net_pnl_usd": round(net_pnl_usd, 6),
            "net_pnl_pct": round(net_pnl_pct, 6),
        },
        "apy_analysis": {
            "actual_apy": round(actual_apy, 6),
            "projected_apy": round(projected_apy, 6),
            "apy_gap_pct": round(apy_gap_pct, 6),
            "il_estimated_usd": round(il_estimated_usd, 6),
            "il_pct": round(il_pct, 6),
        },
        "performance": performance,
        "continue_farming": continue_farming,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _append_to_log(log_path: Path, entry: Dict[str, Any]) -> None:
    """Append entry to ring-buffer log (capped at _LOG_CAP)."""
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        except (json.JSONDecodeError, OSError):
            log = []
    else:
        log = []

    log.append(entry)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]

    _atomic_write(log_path, log)


def _ensure_log_exists(data_dir: Path) -> None:
    """Initialize log file as empty list if it doesn't exist."""
    log_path = data_dir / _LOG_FILE
    if not log_path.exists():
        _atomic_write(log_path, [])


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _sample_farm() -> Dict[str, Any]:
    """Return a sample farm for CLI demonstration."""
    return {
        "protocol": "Uniswap V3",
        "pair": "ETH/USDC",
        "initial_investment_usd": 10000.0,
        "entry_gas_usd": 50.0,
        "days_elapsed": 30.0,
        "base_apy": 15.0,
        "reward_apy": 10.0,
        "current_value_usd": 9800.0,
        "harvested_rewards_usd": 150.0,
        "harvest_gas_total_usd": 30.0,
        "pending_rewards_usd": 50.0,
    }


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Yield Farming ROI Tracker (MP-814)")
    parser.add_argument("--check", action="store_true", help="Compute and print without writing")
    parser.add_argument("--run", action="store_true", help="Compute and write to log")
    parser.add_argument("--data-dir", default=str(_DEFAULT_DATA_DIR), help="Data directory")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    log_path = data_dir / _LOG_FILE

    farm = _sample_farm()
    result = analyze(farm)

    print(json.dumps(result, indent=2))

    if args.run:
        _ensure_log_exists(data_dir)
        _append_to_log(log_path, result)
        print(f"\n✅ Result appended to {log_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
