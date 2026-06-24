"""
spa_core/backtesting/tier1/cost_model.py — net-of-cost adjustment (Tier-1).

PARALLEL MODEL. Pure stdlib, deterministic, LLM-forbidden. Gross backtest APY ignores
the frictions a real fund pays; aggressive strategies that rebalance often can lose most
of their "edge" to costs. This converts gross APY → net APY deterministically.

Frictions modelled:
  • Gas — each rebalance enters/exits positions; cost scales with #positions and chain.
  • Swap slippage — bps on the notional turned over per rebalance.
  • Bridge — flat bps when a strategy spans multiple chains.

Conventions: all APY/return figures are PERCENT (e.g. 5.0 == 5%). Costs are expressed as
an annual percentage drag on capital and subtracted from gross APY.
"""
# LLM_FORBIDDEN
from __future__ import annotations

# Blended gas per position entry/exit (USD). L2-weighted; Ethereum mainnet is the dear one.
GAS_USD_PER_POSITION_CHANGE = {
    "ethereum": 12.0, "mainnet": 12.0,
    "arbitrum": 0.25, "optimism": 0.25, "base": 0.15, "polygon": 0.05,
    "blended": 1.5,  # default for multi-chain / unknown
}
SLIPPAGE_BPS_STABLE = 8.0      # stablecoin swap slippage, basis points of turnover
BRIDGE_BPS = 5.0               # flat bps drag when multi-chain
REBALANCES_PER_YEAR_DEFAULT = 12  # monthly cadence assumption for a paper sleeve


def net_of_cost_apy(
    gross_apy_pct: float,
    capital_usd: float,
    n_positions: int = 1,
    rebalances_per_year: int = REBALANCES_PER_YEAR_DEFAULT,
    annual_turnover: float = 1.0,
    chain: str = "blended",
    multichain: bool = False,
) -> dict:
    """Return {net_apy_pct, gross_apy_pct, gas_drag_pct, slippage_drag_pct, bridge_drag_pct, total_cost_pct}."""
    capital_usd = max(float(capital_usd), 1.0)
    gas_unit = GAS_USD_PER_POSITION_CHANGE.get(str(chain).lower(), GAS_USD_PER_POSITION_CHANGE["blended"])

    # Gas: each rebalance touches up to n_positions; annualized as % of capital.
    gas_usd_year = rebalances_per_year * max(n_positions, 1) * gas_unit
    gas_drag_pct = 100.0 * gas_usd_year / capital_usd

    # Slippage: bps on the notional turned over across the year.
    slippage_drag_pct = annual_turnover * (SLIPPAGE_BPS_STABLE / 10_000.0) * 100.0

    bridge_drag_pct = (BRIDGE_BPS / 10_000.0) * 100.0 * rebalances_per_year if multichain else 0.0

    total = gas_drag_pct + slippage_drag_pct + bridge_drag_pct
    return {
        "gross_apy_pct": round(gross_apy_pct, 4),
        "net_apy_pct": round(gross_apy_pct - total, 4),
        "gas_drag_pct": round(gas_drag_pct, 4),
        "slippage_drag_pct": round(slippage_drag_pct, 4),
        "bridge_drag_pct": round(bridge_drag_pct, 4),
        "total_cost_pct": round(total, 4),
    }


if __name__ == "__main__":
    import json
    # Aggressive: $20k, 8 positions, weekly rebalance, 4x turnover, multichain.
    print(json.dumps(net_of_cost_apy(14.0, 20_000, n_positions=8, rebalances_per_year=52,
                                     annual_turnover=4.0, multichain=True), indent=2))
    # Conservative: $100k, 4 positions, monthly, 1x turnover, single chain.
    print(json.dumps(net_of_cost_apy(4.8, 100_000, n_positions=4, rebalances_per_year=12,
                                     annual_turnover=1.0), indent=2))
