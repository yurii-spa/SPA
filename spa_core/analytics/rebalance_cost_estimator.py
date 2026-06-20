"""
MP-779: RebalanceCostEstimator
==============================
Estimates total cost (gas + slippage) of a portfolio rebalancing operation.

Advisory / read-only — never modifies allocator, risk, or execution.
Atomic writes only (tmp + os.replace). Pure stdlib. Exit 0 always.

Data file: data/rebalance_cost_log.json  (ring-buffer, max 100 entries)

CLI:
    python3 -m spa_core.analytics.rebalance_cost_estimator --check
    python3 -m spa_core.analytics.rebalance_cost_estimator --run
    python3 -m spa_core.analytics.rebalance_cost_estimator --run --data-dir <dir>
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

from spa_core.utils.errors import SPAError

# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

DEFAULT_MIN_REBALANCE_THRESHOLD_PCT: float = 1.0   # ignore diffs ≤ 1%
DEFAULT_GAS_UNITS_PER_TRADE: int = 200_000         # gas units per trade
DEFAULT_ETH_PRICE_USD: float = 3_500.0             # fallback ETH price
LOG_FILENAME = "rebalance_cost_log.json"
LOG_MAX_ENTRIES = 100


# ---------------------------------------------------------------------------
# Core estimation function (stateless)
# ---------------------------------------------------------------------------

def estimate_rebalance_cost(
    current_allocations: Dict[str, float],
    target_allocations: Dict[str, float],
    portfolio_value_usd: float,
    gas_price_gwei: float,
    avg_slippage_bps: float,
    eth_price_usd: float = DEFAULT_ETH_PRICE_USD,
    min_rebalance_threshold_pct: float = DEFAULT_MIN_REBALANCE_THRESHOLD_PCT,
) -> Dict[str, Any]:
    """Estimate the total cost of rebalancing from current to target allocations.

    Parameters
    ----------
    current_allocations : {protocol: pct}  (pct as float, e.g. 30.0 = 30%)
    target_allocations  : {protocol: pct}
    portfolio_value_usd : total portfolio value in USD
    gas_price_gwei      : gas price in Gwei (e.g. 20)
    avg_slippage_bps    : average slippage in basis points (e.g. 5 = 0.05%)
    eth_price_usd       : ETH price used for gas cost conversion
    min_rebalance_threshold_pct : ignore moves smaller than this (%)

    Returns
    -------
    dict with:
        trades_needed           : list of {protocol, from_pct, to_pct,
                                           diff_pct, trade_value_usd}
        n_trades                : int
        gas_cost_usd            : float
        slippage_cost_usd       : float
        total_cost_usd          : float
        cost_as_pct_of_portfolio: float
        rebalance_worthwhile    : bool  (True if expected_yield_gain > total_cost,
                                         but that field is only set by
                                         is_rebalance_worthwhile(); here None)
        inputs_snapshot         : dict (all input params)
        timestamp_utc           : float
    """
    all_protocols = set(current_allocations) | set(target_allocations)

    trades: List[Dict[str, Any]] = []
    for protocol in sorted(all_protocols):
        from_pct = float(current_allocations.get(protocol, 0.0))
        to_pct = float(target_allocations.get(protocol, 0.0))
        diff_pct = to_pct - from_pct

        if abs(diff_pct) <= min_rebalance_threshold_pct:
            continue

        trade_value = abs(diff_pct) / 100.0 * portfolio_value_usd
        trades.append({
            "protocol": protocol,
            "from_pct": round(from_pct, 4),
            "to_pct": round(to_pct, 4),
            "diff_pct": round(diff_pct, 4),
            "trade_value_usd": round(trade_value, 2),
        })

    n_trades = len(trades)

    # Gas cost: gas_price_gwei * GAS_UNITS * n_trades / 1e9 * eth_price
    gas_cost = (
        gas_price_gwei
        * DEFAULT_GAS_UNITS_PER_TRADE
        * n_trades
        / 1_000_000_000.0
        * eth_price_usd
    )

    # Slippage cost: sum(trade_value * slippage_bps / 10_000)
    total_trade_value = sum(t["trade_value_usd"] for t in trades)
    slippage_cost = total_trade_value * avg_slippage_bps / 10_000.0

    total_cost = gas_cost + slippage_cost
    cost_pct = (total_cost / portfolio_value_usd * 100.0) if portfolio_value_usd > 0 else 0.0

    return {
        "trades_needed": trades,
        "n_trades": n_trades,
        "gas_cost_usd": round(gas_cost, 4),
        "slippage_cost_usd": round(slippage_cost, 4),
        "total_cost_usd": round(total_cost, 4),
        "cost_as_pct_of_portfolio": round(cost_pct, 6),
        "rebalance_worthwhile": None,  # set by is_rebalance_worthwhile()
        "inputs_snapshot": {
            "portfolio_value_usd": portfolio_value_usd,
            "gas_price_gwei": gas_price_gwei,
            "avg_slippage_bps": avg_slippage_bps,
            "eth_price_usd": eth_price_usd,
            "min_rebalance_threshold_pct": min_rebalance_threshold_pct,
        },
        "timestamp_utc": time.time(),
    }


# ---------------------------------------------------------------------------
# RebalanceCostEstimator class
# ---------------------------------------------------------------------------

class RebalanceCostEstimator:
    """Stateful wrapper around estimate_rebalance_cost with ring-buffer log.

    Usage
    -----
    est = RebalanceCostEstimator(data_dir="data")
    result = est.estimate({
        "current_allocations": {"Aave": 50.0, "Compound": 50.0},
        "target_allocations":  {"Aave": 30.0, "Compound": 40.0, "Morpho": 30.0},
        "portfolio_value_usd": 100_000,
        "gas_price_gwei": 20,
        "avg_slippage_bps": 5,
    })
    cost = est.get_total_cost()
    ok   = est.is_rebalance_worthwhile(expected_annual_gain_usd=500)
    est.save()
    """

    def __init__(self, data_dir: str = "data") -> None:
        self._data_dir = data_dir
        self._last_result: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate(self, rebalance_data: Dict[str, Any]) -> Dict[str, Any]:
        """Compute and cache rebalance cost estimate.

        rebalance_data keys:
            current_allocations         : {protocol: pct}
            target_allocations          : {protocol: pct}
            portfolio_value_usd         : float
            gas_price_gwei              : float
            avg_slippage_bps            : float
            eth_price_usd               : float (optional, default 3500)
            min_rebalance_threshold_pct : float (optional, default 1.0)
        """
        current = rebalance_data.get("current_allocations", {})
        target = rebalance_data.get("target_allocations", {})
        portfolio_value = float(rebalance_data.get("portfolio_value_usd", 0.0))
        gas_price = float(rebalance_data.get("gas_price_gwei", 0.0))
        slippage = float(rebalance_data.get("avg_slippage_bps", 0.0))
        eth_price = float(rebalance_data.get("eth_price_usd", DEFAULT_ETH_PRICE_USD))
        threshold = float(
            rebalance_data.get("min_rebalance_threshold_pct", DEFAULT_MIN_REBALANCE_THRESHOLD_PCT)
        )

        self._last_result = estimate_rebalance_cost(
            current_allocations=current,
            target_allocations=target,
            portfolio_value_usd=portfolio_value,
            gas_price_gwei=gas_price,
            avg_slippage_bps=slippage,
            eth_price_usd=eth_price,
            min_rebalance_threshold_pct=threshold,
        )
        return self._last_result

    def get_total_cost(self) -> float:
        """Return total_cost_usd from last estimate() call. Returns 0.0 if none."""
        if self._last_result is None:
            return 0.0
        return self._last_result.get("total_cost_usd", 0.0)

    def is_rebalance_worthwhile(self, expected_annual_gain_usd: float) -> bool:
        """Return True if expected_annual_gain_usd > total_cost_usd.

        Also updates last result's rebalance_worthwhile field in-place.
        """
        total_cost = self.get_total_cost()
        worthwhile = expected_annual_gain_usd > total_cost
        if self._last_result is not None:
            self._last_result["rebalance_worthwhile"] = worthwhile
            self._last_result["expected_annual_gain_usd"] = round(expected_annual_gain_usd, 4)
        return worthwhile

    def save(self) -> str:
        """Atomically append last result to ring-buffer log. Returns log path."""
        if self._last_result is None:
            raise SPAError("No estimate to save; call estimate() first.", code="NOT_INITIALIZED")

        log_path = os.path.join(self._data_dir, LOG_FILENAME)
        log = _load_log(log_path)
        log.append(self._last_result)
        if len(log) > LOG_MAX_ENTRIES:
            log = log[-LOG_MAX_ENTRIES:]
        _atomic_write(log_path, log)
        return log_path

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def estimate_and_save(self, rebalance_data: Dict[str, Any]) -> Dict[str, Any]:
        """estimate() + save() combined."""
        result = self.estimate(rebalance_data)
        self.save()
        return result

    @property
    def last_result(self) -> Optional[Dict[str, Any]]:
        """Return the last cached estimation result or None."""
        return self._last_result


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _load_log(path: str) -> List[Any]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _atomic_write(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _sample_rebalance_data() -> Dict[str, Any]:
    return {
        "current_allocations": {
            "Aave V3": 45.0,
            "Compound V3": 30.0,
            "Morpho": 20.0,
            "Cash": 5.0,
        },
        "target_allocations": {
            "Aave V3": 30.0,
            "Compound V3": 35.0,
            "Morpho": 30.0,
            "Cash": 5.0,
        },
        "portfolio_value_usd": 100_000.0,
        "gas_price_gwei": 20.0,
        "avg_slippage_bps": 5.0,
        "eth_price_usd": 3_500.0,
    }


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="MP-779 RebalanceCostEstimator")
    parser.add_argument("--check", action="store_true", default=False)
    parser.add_argument("--run", action="store_true", default=False)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args(argv)

    data = _sample_rebalance_data()
    est = RebalanceCostEstimator(data_dir=args.data_dir)
    result = est.estimate(data)

    print(f"[RebalanceCostEstimator] Portfolio: ${data['portfolio_value_usd']:,.0f}")
    print(f"  Trades needed  : {result['n_trades']}")
    for t in result["trades_needed"]:
        print(
            f"    {t['protocol']:20s}  {t['from_pct']:6.2f}% → {t['to_pct']:6.2f}%"
            f"  move=${t['trade_value_usd']:,.2f}"
        )
    print(f"  Gas cost       : ${result['gas_cost_usd']:,.4f}")
    print(f"  Slippage cost  : ${result['slippage_cost_usd']:,.4f}")
    print(f"  Total cost     : ${result['total_cost_usd']:,.4f}")
    print(f"  Cost as % port : {result['cost_as_pct_of_portfolio']:.4f}%")

    # Demo worthwhile check
    gain = 500.0
    worthwhile = est.is_rebalance_worthwhile(gain)
    print(f"  Worthwhile?    : {worthwhile} (expected gain ${gain:,.0f} vs cost ${result['total_cost_usd']:,.4f})")

    if args.run:
        log_path = est.save()
        print(f"\n[RebalanceCostEstimator] Log written → {log_path}")
    else:
        print("\n[RebalanceCostEstimator] (--check mode, no write)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
