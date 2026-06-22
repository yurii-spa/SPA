"""
DeFi Portfolio Rebalancer — ADVISORY ONLY (MP-813).

Analyzes current vs target portfolio allocation and recommends rebalancing moves,
accounting for gas costs and minimum trade sizes.

Design constraints
------------------
* Pure stdlib — no external deps.
* Advisory only — never touches allocator / risk / execution.
* Atomic writes — tmp + os.replace on every JSON update.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* Ring-buffer JSON log capped at 100 entries.

CLI
---
    python3 -m spa_core.analytics.defi_portfolio_rebalancer --check
    python3 -m spa_core.analytics.defi_portfolio_rebalancer --run
    python3 -m spa_core.analytics.defi_portfolio_rebalancer --run --data-dir /path/to/data
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Project root & paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_LOG_FILE = "rebalance_recommendations_log.json"
_LOG_CAP = 100

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_MIN_TRADE_USD = 100.0
_DEFAULT_GAS_COST_PER_MOVE_USD = 15.0
_DEFAULT_DRIFT_THRESHOLD_PCT = 5.0


# ---------------------------------------------------------------------------
# Core analyze function
# ---------------------------------------------------------------------------

def analyze(
    positions: List[Dict[str, Any]],
    targets: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Analyze current vs target portfolio allocation and recommend rebalancing moves.

    Parameters
    ----------
    positions : list of {protocol, value_usd, apy}
    targets   : list of {protocol, target_pct}
    config    : optional {min_trade_usd, gas_cost_per_move_usd, drift_threshold_pct}

    Returns
    -------
    dict with rebalancing analysis and recommendations.
    """
    cfg = config or {}
    min_trade_usd: float = float(cfg.get("min_trade_usd", _DEFAULT_MIN_TRADE_USD))
    gas_cost_per_move: float = float(cfg.get("gas_cost_per_move_usd", _DEFAULT_GAS_COST_PER_MOVE_USD))
    drift_threshold: float = float(cfg.get("drift_threshold_pct", _DEFAULT_DRIFT_THRESHOLD_PCT))

    # Build lookup: protocol -> {value_usd, apy}
    pos_lookup: Dict[str, Dict[str, float]] = {}
    for p in positions:
        proto = str(p.get("protocol", ""))
        if proto:
            pos_lookup[proto] = {
                "value_usd": float(p.get("value_usd", 0.0)),
                "apy": float(p.get("apy", 0.0)),
            }

    # Total portfolio value
    total_portfolio_usd: float = sum(v["value_usd"] for v in pos_lookup.values())

    # Build target lookup: protocol -> target_pct
    tgt_lookup: Dict[str, float] = {}
    for t in targets:
        proto = str(t.get("protocol", ""))
        if proto:
            tgt_lookup[proto] = float(t.get("target_pct", 0.0))

    # Determine all protocols that appear in targets (and possibly not in positions)
    all_target_protocols = list(tgt_lookup.keys())

    # Build positions analysis
    positions_analysis: List[Dict[str, Any]] = []
    for proto in all_target_protocols:
        current_usd = pos_lookup.get(proto, {}).get("value_usd", 0.0)
        current_pct = (current_usd / total_portfolio_usd * 100.0) if total_portfolio_usd > 0 else 0.0
        target_pct = tgt_lookup.get(proto, 0.0)
        drift_pct = current_pct - target_pct
        needs_rebalance = abs(drift_pct) > drift_threshold

        positions_analysis.append({
            "protocol": proto,
            "current_usd": round(current_usd, 6),
            "current_pct": round(current_pct, 6),
            "target_pct": round(target_pct, 6),
            "drift_pct": round(drift_pct, 6),
            "needs_rebalance": needs_rebalance,
        })

    # Build moves for protocols that need rebalancing
    moves: List[Dict[str, Any]] = []

    if total_portfolio_usd > 0:
        for pa in positions_analysis:
            if not pa["needs_rebalance"]:
                continue

            proto = pa["protocol"]
            drift_pct = pa["drift_pct"]
            usd_change = abs(drift_pct / 100.0 * total_portfolio_usd)

            action = "REDUCE" if drift_pct > 0 else "INCREASE"
            target_usd = tgt_lookup.get(proto, 0.0) / 100.0 * total_portfolio_usd
            current_apy = pos_lookup.get(proto, {}).get("apy", 0.0)

            # net_benefit_usd calculation:
            # INCREASE: annual gain = usd_change * target_apy / 100
            # REDUCE: opportunity cost = usd_change * current_apy / 100 (negative benefit)
            if action == "INCREASE":
                net_benefit_usd = usd_change * current_apy / 100.0 - gas_cost_per_move
            else:
                # Reducing: we lose yield on the amount we move away
                net_benefit_usd = -(usd_change * current_apy / 100.0) - gas_cost_per_move

            worthwhile = (net_benefit_usd > 0) and (usd_change >= min_trade_usd)

            moves.append({
                "protocol": proto,
                "action": action,
                "usd_change": round(usd_change, 6),
                "new_target_usd": round(target_usd, 6),
                "gas_cost_usd": round(gas_cost_per_move, 6),
                "net_benefit_usd": round(net_benefit_usd, 6),
                "worthwhile": worthwhile,
            })

    # Sort moves by abs(usd_change) descending
    moves.sort(key=lambda m: m["usd_change"], reverse=True)

    # Rebalance needed: any position needs rebalance
    rebalance_needed = any(pa["needs_rebalance"] for pa in positions_analysis)

    # Total gas for worthwhile moves
    worthwhile_moves = [m for m in moves if m["worthwhile"]]
    all_moves_with_drift = [m for m in moves]  # moves only for positions needing rebalance

    estimated_total_gas_usd = sum(m["gas_cost_usd"] for m in worthwhile_moves)
    estimated_annual_yield_gain_usd = sum(
        m["net_benefit_usd"] + m["gas_cost_usd"]  # gain before gas
        for m in worthwhile_moves
        if m["action"] == "INCREASE"
    )

    # Recommendation logic
    if not rebalance_needed or not moves:
        recommendation = "HOLD"
    elif worthwhile_moves and len(worthwhile_moves) == len(all_moves_with_drift):
        recommendation = "REBALANCE"
    elif worthwhile_moves:
        recommendation = "PARTIAL"
    else:
        recommendation = "HOLD"

    return {
        "total_portfolio_usd": round(total_portfolio_usd, 6),
        "positions": positions_analysis,
        "moves": moves,
        "rebalance_needed": rebalance_needed,
        "estimated_total_gas_usd": round(estimated_total_gas_usd, 6),
        "estimated_annual_yield_gain_usd": round(estimated_annual_yield_gain_usd, 6),
        "recommendation": recommendation,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(data, str(path))
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

def _sample_positions() -> List[Dict[str, Any]]:
    """Return sample positions for CLI demonstration."""
    return [
        {"protocol": "Aave V3", "value_usd": 40000.0, "apy": 3.5},
        {"protocol": "Compound V3", "value_usd": 30000.0, "apy": 4.8},
        {"protocol": "Morpho Steakhouse", "value_usd": 20000.0, "apy": 6.5},
        {"protocol": "Yearn V3", "value_usd": 10000.0, "apy": 5.2},
    ]


def _sample_targets() -> List[Dict[str, Any]]:
    """Return sample targets for CLI demonstration."""
    return [
        {"protocol": "Aave V3", "target_pct": 30.0},
        {"protocol": "Compound V3", "target_pct": 35.0},
        {"protocol": "Morpho Steakhouse", "target_pct": 25.0},
        {"protocol": "Yearn V3", "target_pct": 10.0},
    ]


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="DeFi Portfolio Rebalancer (MP-813)")
    parser.add_argument("--check", action="store_true", help="Compute and print without writing")
    parser.add_argument("--run", action="store_true", help="Compute and write to log")
    parser.add_argument("--data-dir", default=str(_DEFAULT_DATA_DIR), help="Data directory")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    log_path = data_dir / _LOG_FILE

    positions = _sample_positions()
    targets = _sample_targets()

    result = analyze(positions, targets)

    print(json.dumps(result, indent=2))

    if args.run:
        _ensure_log_exists(data_dir)
        _append_to_log(log_path, result)
        print(f"\n✅ Result appended to {log_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
