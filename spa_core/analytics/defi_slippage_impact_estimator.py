#!/usr/bin/env python3
"""DeFi Slippage Impact Estimator (SPA-V672 / MP-868) — read-only / advisory.

Estimates slippage impact for DeFi trades based on pool liquidity, trade size,
and AMM mechanics. Models both spot slippage and price impact for entry/exit
across CONSTANT_PRODUCT, STABLE_SWAP, and CONCENTRATED pool types.

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic).
* Ring-buffer history capped at 100 entries in data/slippage_impact_log.json.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Price Impact Model
------------------
  effective_liquidity = pool_liquidity_usd * concentration_factor
    (if concentration_factor == 0: use pool_liquidity_usd directly)

  CONSTANT_PRODUCT:
    price_impact_pct = trade_size / (effective_liquidity + trade_size) * 100

  STABLE_SWAP:
    price_impact_pct = trade_size / (effective_liquidity + trade_size) * 100 * 0.1

  CONCENTRATED:
    price_impact_pct = trade_size / (effective_liquidity + trade_size) * 100
    (effective_liquidity already adjusted by concentration_factor)

  If price_impact_observed_pct is not None, that value overrides the computed one.

  total_cost_pct = estimated_price_impact_pct + pool_fee_pct
  net_received_pct = max(0.0, 100.0 - total_cost_pct)

Slippage Labels (by total_cost_pct)
-------------------------------------
  MINIMAL:    <= 0.1
  ACCEPTABLE: <= 0.5
  NOTABLE:    <= 1.0
  HIGH:       <= 3.0
  SEVERE:     > 3.0

CLI
---
  python3 -m spa_core.analytics.defi_slippage_impact_estimator --check
  python3 -m spa_core.analytics.defi_slippage_impact_estimator --run
  python3 -m spa_core.analytics.defi_slippage_impact_estimator --run --data-dir PATH
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_LOG_FILE = "data/slippage_impact_log.json"
_RING_BUFFER_CAP = 100
_DEFAULT_ACCEPTABLE_SLIPPAGE_PCT = 0.5

_POOL_TYPES = {"CONSTANT_PRODUCT", "STABLE_SWAP", "CONCENTRATED"}


# ---------------------------------------------------------------------------
# Core impact calculation helpers
# ---------------------------------------------------------------------------

def _effective_liquidity(pool_liquidity_usd: float, concentration_factor: float) -> float:
    """Compute effective liquidity considering concentration factor.

    If concentration_factor == 0 (or negative), fall back to pool_liquidity_usd directly.
    """
    if concentration_factor > 0:
        return pool_liquidity_usd * concentration_factor
    return pool_liquidity_usd


def _compute_price_impact_pct(
    trade_size_usd: float,
    effective_liq: float,
    pool_type: str,
) -> float:
    """Compute estimated price impact percentage using AMM model.

    For all types:
      base_impact = trade_size / (effective_liq + trade_size) * 100

    STABLE_SWAP multiplies by 0.1 (stable pools have ~10x less slippage).
    """
    if effective_liq <= 0:
        # No liquidity → maximum impact: treat as if effective_liq = 0
        # trade / (0 + trade) * 100 = 100%
        base = 100.0
    else:
        denominator = effective_liq + trade_size_usd
        base = (trade_size_usd / denominator) * 100.0

    if pool_type == "STABLE_SWAP":
        return base * 0.1
    # CONSTANT_PRODUCT and CONCENTRATED both use the base formula
    return base


def _slippage_label(total_cost_pct: float) -> str:
    """Map total_cost_pct to a slippage label."""
    if total_cost_pct <= 0.1:
        return "MINIMAL"
    elif total_cost_pct <= 0.5:
        return "ACCEPTABLE"
    elif total_cost_pct <= 1.0:
        return "NOTABLE"
    elif total_cost_pct <= 3.0:
        return "HIGH"
    else:
        return "SEVERE"


def _recommendation(label: str, total_cost_pct: float, token_pair: str) -> str:
    """Build recommendation string for a trade result."""
    if label == "MINIMAL":
        return f"Excellent execution. {total_cost_pct:.3f}% total cost on {token_pair}."
    elif label == "ACCEPTABLE":
        return f"Acceptable slippage ({total_cost_pct:.2f}%). Proceed with trade."
    elif label == "NOTABLE":
        return (
            f"Notable slippage ({total_cost_pct:.2f}%). "
            f"Consider splitting trade or better timing."
        )
    elif label == "HIGH":
        return f"High impact ({total_cost_pct:.2f}%). Split trade or use limit orders."
    else:  # SEVERE
        return f"SEVERE slippage ({total_cost_pct:.2f}%). Trade size too large for this pool."


# ---------------------------------------------------------------------------
# Main analyze function
# ---------------------------------------------------------------------------

def analyze(
    trades: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Estimate slippage impact for a list of DeFi trades.

    Parameters
    ----------
    trades:
        List of trade dicts with pool/size/type information.
    config:
        Optional config dict. Supports:
          "acceptable_slippage_pct": float  (default 0.5)

    Returns
    -------
    dict with per-trade impact estimates and aggregate metrics.
    """
    cfg = config or {}
    acceptable_slippage = float(
        cfg.get("acceptable_slippage_pct", _DEFAULT_ACCEPTABLE_SLIPPAGE_PCT)
    )

    if not trades:
        return {
            "trades": [],
            "worst_slippage_trade": None,
            "best_execution_trade": None,
            "trades_above_threshold": 0,
            "average_total_cost_pct": 0.0,
            "timestamp": time.time(),
        }

    results = []

    for t in trades:
        protocol = str(t.get("protocol", "unknown"))
        token_pair = str(t.get("token_pair", "UNKNOWN/UNKNOWN"))
        pool_liquidity = float(t.get("pool_liquidity_usd", 0.0))
        trade_size = float(t.get("trade_size_usd", 0.0))
        pool_fee = float(t.get("pool_fee_pct", 0.0))
        pool_type = str(t.get("pool_type", "CONSTANT_PRODUCT"))
        concentration = float(t.get("concentration_factor", 1.0))
        observed_impact = t.get("price_impact_observed_pct")

        # Effective liquidity
        eff_liq = _effective_liquidity(pool_liquidity, concentration)

        # Trade size ratio
        trade_size_ratio = trade_size / eff_liq if eff_liq > 0 else 1.0

        # Price impact
        if observed_impact is not None:
            estimated_impact = float(observed_impact)
        else:
            estimated_impact = _compute_price_impact_pct(trade_size, eff_liq, pool_type)

        # Derived metrics
        total_cost = estimated_impact + pool_fee
        net_received = max(0.0, 100.0 - total_cost)
        label = _slippage_label(total_cost)
        above_threshold = total_cost > acceptable_slippage
        rec = _recommendation(label, total_cost, token_pair)

        results.append(
            {
                "protocol": protocol,
                "token_pair": token_pair,
                "trade_size_usd": trade_size,
                "pool_liquidity_usd": pool_liquidity,
                "estimated_price_impact_pct": round(estimated_impact, 6),
                "total_cost_pct": round(total_cost, 6),
                "net_received_pct": round(net_received, 6),
                "slippage_label": label,
                "is_above_threshold": above_threshold,
                "effective_liquidity_usd": round(eff_liq, 4),
                "trade_size_ratio": round(trade_size_ratio, 8),
                "recommendation": rec,
            }
        )

    # Aggregate
    costs = [r["total_cost_pct"] for r in results]
    avg_cost = sum(costs) / len(costs) if costs else 0.0

    worst = max(results, key=lambda r: r["total_cost_pct"])
    best = min(results, key=lambda r: r["total_cost_pct"])

    trades_above = sum(1 for r in results if r["is_above_threshold"])

    return {
        "trades": results,
        "worst_slippage_trade": f"{worst['protocol']} {worst['token_pair']}",
        "best_execution_trade": f"{best['protocol']} {best['token_pair']}",
        "trades_above_threshold": trades_above,
        "average_total_cost_pct": round(avg_cost, 6),
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Log persistence (ring-buffer)
# ---------------------------------------------------------------------------

def _load_log(log_path: Path) -> List[Dict[str, Any]]:
    """Load existing ring-buffer log or return empty list."""
    if not log_path.exists():
        return []
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_log(log_path: Path, entries: List[Dict[str, Any]]) -> None:
    """Atomically save ring-buffer log (capped at _RING_BUFFER_CAP)."""
    entries = entries[-_RING_BUFFER_CAP:]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(entries, str(log_path))
def run(
    trades: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
    data_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Analyze and persist result to ring-buffer log."""
    result = analyze(trades, config)
    base = Path(data_dir) if data_dir else Path(".")
    log_path = base / _DEFAULT_LOG_FILE
    entries = _load_log(log_path)
    entries.append(result)
    _save_log(log_path, entries)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_sample_trades() -> List[Dict[str, Any]]:
    """Return sample trade data for CLI demonstration."""
    return [
        {
            "protocol": "Uniswap-V3",
            "token_pair": "USDC/ETH",
            "pool_liquidity_usd": 50_000_000,
            "trade_size_usd": 100_000,
            "pool_fee_pct": 0.3,
            "pool_type": "CONCENTRATED",
            "concentration_factor": 0.4,
            "price_impact_observed_pct": None,
        },
        {
            "protocol": "Curve",
            "token_pair": "USDC/USDT",
            "pool_liquidity_usd": 200_000_000,
            "trade_size_usd": 500_000,
            "pool_fee_pct": 0.04,
            "pool_type": "STABLE_SWAP",
            "concentration_factor": 1.0,
            "price_impact_observed_pct": None,
        },
        {
            "protocol": "Uniswap-V2",
            "token_pair": "DAI/WETH",
            "pool_liquidity_usd": 5_000_000,
            "trade_size_usd": 200_000,
            "pool_fee_pct": 0.3,
            "pool_type": "CONSTANT_PRODUCT",
            "concentration_factor": 1.0,
            "price_impact_observed_pct": None,
        },
    ]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="DeFi Slippage Impact Estimator (MP-868)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compute and print result without saving to disk (default)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compute and atomically save result to data/slippage_impact_log.json",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override base directory for data files",
    )
    args = parser.parse_args(argv)

    trades = _build_sample_trades()

    if args.run:
        result = run(trades, data_dir=args.data_dir)
        print(json.dumps(result, indent=2))
    else:
        result = analyze(trades)
        print(json.dumps(result, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
