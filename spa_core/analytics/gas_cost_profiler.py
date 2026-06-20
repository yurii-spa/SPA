"""
MP-749: GasCostProfiler
Advisory/read-only analytics module.
Profiles transaction gas costs for DeFi operations and computes break-even
thresholds — how much yield a position needs to justify gas overhead of
entry, rebalancing, and exit. Supports ETH mainnet and L2 chains.

CLI:
    python3 -m spa_core.analytics.gas_cost_profiler --check
    python3 -m spa_core.analytics.gas_cost_profiler --run
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict
from typing import List
from spa_core.utils.atomic import atomic_save


# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
DEFAULT_DATA_FILE = os.path.join(_REPO_ROOT, "data", "gas_cost_log.json")
RING_BUFFER_CAP = 100

# L2 discount factors applied to effective gas price
CHAIN_DISCOUNT = {
    "MAINNET": 1.0,
    "ARBITRUM": 0.05,
    "BASE": 0.03,
    "OPTIMISM": 0.04,
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class GasEstimate:
    operation: str           # "DEPOSIT" | "WITHDRAW" | "REBALANCE" | "CLAIM_REWARDS"
    gas_units: int           # estimated gas units
    gas_price_gwei: float    # current gas price in gwei
    eth_price_usd: float     # ETH price in USD
    chain: str               # "MAINNET" | "ARBITRUM" | "BASE" | "OPTIMISM"

    # L2 discount
    chain_discount_factor: float  # MAINNET=1.0, ARBITRUM=0.05, BASE=0.03, OPTIMISM=0.04

    # Computed
    effective_gas_price_gwei: float   # gas_price_gwei * chain_discount_factor
    gas_cost_eth: float               # gas_units * effective_gas_price / 1e9
    gas_cost_usd: float               # gas_cost_eth * eth_price_usd


@dataclass
class PositionGasProfile:
    protocol: str
    position_size_usd: float
    annual_apy_pct: float

    # Gas costs for a full cycle
    deposit_gas: GasEstimate
    withdraw_gas: GasEstimate
    rebalance_gas: GasEstimate
    rebalance_count: int

    # Total annual gas cost
    total_gas_usd: float           # deposit + withdraw + rebalance * count
    annual_gas_drag_pct: float     # total_gas_usd / position_size_usd * 100

    # Net APY after gas
    net_apy_after_gas_pct: float   # annual_apy_pct - annual_gas_drag_pct

    # Break-even
    breakeven_position_usd: float  # total_gas_usd / (annual_apy_pct / 100)

    is_gas_efficient: bool         # drag < 1.0% AND net_apy > 0
    gas_efficiency_label: str      # "EFFICIENT" | "MARGINAL" | "EXPENSIVE"

    recommendation: str


@dataclass
class GasCostResult:
    profiles: List[PositionGasProfile]

    most_gas_efficient_protocol: str    # min annual_gas_drag_pct
    least_gas_efficient_protocol: str   # max annual_gas_drag_pct

    avg_gas_drag_pct: float
    avg_breakeven_usd: float

    efficient_count: int                # is_gas_efficient == True

    market_gas_label: str              # "GAS_FRIENDLY" | "MODERATE_GAS" | "GAS_HEAVY"

    recommendation_summary: str
    saved_to: str


# ---------------------------------------------------------------------------
# Core computation functions
# ---------------------------------------------------------------------------

def compute_gas_cost_usd(
    gas_units: int,
    gas_price_gwei: float,
    eth_price_usd: float,
    chain: str,
) -> float:
    """
    Compute gas cost in USD for given parameters.
    Applies chain discount factor to gas_price_gwei.
    Unknown chains default to discount 1.0 (MAINNET equivalent).
    """
    discount = CHAIN_DISCOUNT.get(chain, 1.0)
    effective_gwei = gas_price_gwei * discount
    cost_eth = gas_units * effective_gwei / 1e9
    return cost_eth * eth_price_usd


def build_estimate(
    operation: str,
    gas_units: int,
    gas_price_gwei: float,
    eth_price_usd: float,
    chain: str,
) -> GasEstimate:
    """Build a GasEstimate dataclass with all computed fields."""
    discount = CHAIN_DISCOUNT.get(chain, 1.0)
    effective_gwei = gas_price_gwei * discount
    cost_eth = gas_units * effective_gwei / 1e9
    cost_usd = cost_eth * eth_price_usd

    return GasEstimate(
        operation=operation,
        gas_units=gas_units,
        gas_price_gwei=gas_price_gwei,
        eth_price_usd=eth_price_usd,
        chain=chain,
        chain_discount_factor=discount,
        effective_gas_price_gwei=effective_gwei,
        gas_cost_eth=cost_eth,
        gas_cost_usd=cost_usd,
    )


def gas_efficiency_label(drag_pct: float) -> str:
    """Map gas drag percentage to efficiency label."""
    if drag_pct < 1.0:
        return "EFFICIENT"
    if drag_pct <= 3.0:
        return "MARGINAL"
    return "EXPENSIVE"


def compute_breakeven(total_gas_usd: float, annual_apy_pct: float) -> float:
    """
    Minimum position size where gas drag equals yield (net = 0).
    breakeven = total_gas_usd / (annual_apy_pct / 100)
    Returns inf if annual_apy_pct <= 0.
    """
    if annual_apy_pct <= 0:
        return float("inf")
    return total_gas_usd / (annual_apy_pct / 100.0)


def _make_gas_recommendation(label: str) -> str:
    if label == "EXPENSIVE":
        return "Gas costs exceed 3% of yield. Increase position size or reduce rebalancing."
    if label == "MARGINAL":
        return "Marginal gas efficiency. Consider larger position or L2."
    return "Gas efficient. Good economics for this position size."


def profile_position(
    protocol: str,
    position_size_usd: float,
    annual_apy_pct: float,
    deposit_gas_units: int,
    withdraw_gas_units: int,
    rebalance_gas_units: int,
    rebalance_count: int,
    gas_price_gwei: float,
    eth_price_usd: float,
    chain: str,
) -> PositionGasProfile:
    """Build a full PositionGasProfile from raw inputs."""
    deposit_gas = build_estimate("DEPOSIT", deposit_gas_units, gas_price_gwei, eth_price_usd, chain)
    withdraw_gas = build_estimate("WITHDRAW", withdraw_gas_units, gas_price_gwei, eth_price_usd, chain)
    rebalance_gas = build_estimate("REBALANCE", rebalance_gas_units, gas_price_gwei, eth_price_usd, chain)

    total_gas_usd = (
        deposit_gas.gas_cost_usd
        + withdraw_gas.gas_cost_usd
        + rebalance_gas.gas_cost_usd * rebalance_count
    )

    if position_size_usd > 0:
        drag_pct = total_gas_usd / position_size_usd * 100.0
    else:
        drag_pct = float("inf")

    net_apy = annual_apy_pct - drag_pct

    breakeven = compute_breakeven(total_gas_usd, annual_apy_pct)

    label = gas_efficiency_label(drag_pct)
    is_efficient = drag_pct < 1.0 and net_apy > 0
    rec = _make_gas_recommendation(label)

    return PositionGasProfile(
        protocol=protocol,
        position_size_usd=position_size_usd,
        annual_apy_pct=annual_apy_pct,
        deposit_gas=deposit_gas,
        withdraw_gas=withdraw_gas,
        rebalance_gas=rebalance_gas,
        rebalance_count=rebalance_count,
        total_gas_usd=total_gas_usd,
        annual_gas_drag_pct=drag_pct,
        net_apy_after_gas_pct=net_apy,
        breakeven_position_usd=breakeven,
        is_gas_efficient=is_efficient,
        gas_efficiency_label=label,
        recommendation=rec,
    )


def profile_market(
    positions_data: List[dict],
    data_file: str = DEFAULT_DATA_FILE,
) -> GasCostResult:
    """
    Build GasCostResult from a list of position dicts.
    Each dict must contain fields expected by profile_position.
    """
    profiles: List[PositionGasProfile] = []
    for d in positions_data:
        p = profile_position(
            protocol=d["protocol"],
            position_size_usd=d["position_size_usd"],
            annual_apy_pct=d["annual_apy_pct"],
            deposit_gas_units=d["deposit_gas_units"],
            withdraw_gas_units=d["withdraw_gas_units"],
            rebalance_gas_units=d["rebalance_gas_units"],
            rebalance_count=d["rebalance_count"],
            gas_price_gwei=d["gas_price_gwei"],
            eth_price_usd=d["eth_price_usd"],
            chain=d["chain"],
        )
        profiles.append(p)

    if profiles:
        most_efficient = min(profiles, key=lambda p: p.annual_gas_drag_pct).protocol
        least_efficient = max(profiles, key=lambda p: p.annual_gas_drag_pct).protocol
        avg_drag = sum(p.annual_gas_drag_pct for p in profiles) / len(profiles)
        finite_breakevens = [p.breakeven_position_usd for p in profiles
                              if p.breakeven_position_usd != float("inf")]
        avg_breakeven = sum(finite_breakevens) / len(finite_breakevens) if finite_breakevens else float("inf")
    else:
        most_efficient = ""
        least_efficient = ""
        avg_drag = 0.0
        avg_breakeven = 0.0

    efficient_count = sum(1 for p in profiles if p.is_gas_efficient)

    # Market gas label
    if avg_drag < 1.0:
        market_label = "GAS_FRIENDLY"
    elif avg_drag <= 3.0:
        market_label = "MODERATE_GAS"
    else:
        market_label = "GAS_HEAVY"

    # Summary
    if market_label == "GAS_HEAVY":
        rec_summary = "High gas costs across protocols. Prioritize L2 chains or increase position sizes."
    elif market_label == "MODERATE_GAS":
        rec_summary = "Moderate gas drag. Consider L2 migration or batching rebalances."
    else:
        rec_summary = "Gas-friendly conditions. Current position economics are favorable."

    return GasCostResult(
        profiles=profiles,
        most_gas_efficient_protocol=most_efficient,
        least_gas_efficient_protocol=least_efficient,
        avg_gas_drag_pct=avg_drag,
        avg_breakeven_usd=avg_breakeven,
        efficient_count=efficient_count,
        market_gas_label=market_label,
        recommendation_summary=rec_summary,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_history(data_file: str = DEFAULT_DATA_FILE) -> list:
    """Load history from JSON ring-buffer file."""
    if not os.path.exists(data_file):
        return []
    try:
        with open(data_file, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def _estimate_to_dict(e: GasEstimate) -> dict:
    return asdict(e)


def _profile_to_dict(p: PositionGasProfile) -> dict:
    return {
        "protocol": p.protocol,
        "position_size_usd": p.position_size_usd,
        "annual_apy_pct": p.annual_apy_pct,
        "deposit_gas": _estimate_to_dict(p.deposit_gas),
        "withdraw_gas": _estimate_to_dict(p.withdraw_gas),
        "rebalance_gas": _estimate_to_dict(p.rebalance_gas),
        "rebalance_count": p.rebalance_count,
        "total_gas_usd": p.total_gas_usd,
        "annual_gas_drag_pct": p.annual_gas_drag_pct,
        "net_apy_after_gas_pct": p.net_apy_after_gas_pct,
        "breakeven_position_usd": (
            p.breakeven_position_usd
            if p.breakeven_position_usd != float("inf")
            else None
        ),
        "is_gas_efficient": p.is_gas_efficient,
        "gas_efficiency_label": p.gas_efficiency_label,
        "recommendation": p.recommendation,
    }


def _result_to_dict(result: GasCostResult) -> dict:
    return {
        "profiles": [_profile_to_dict(p) for p in result.profiles],
        "most_gas_efficient_protocol": result.most_gas_efficient_protocol,
        "least_gas_efficient_protocol": result.least_gas_efficient_protocol,
        "avg_gas_drag_pct": result.avg_gas_drag_pct,
        "avg_breakeven_usd": (
            result.avg_breakeven_usd
            if result.avg_breakeven_usd != float("inf")
            else None
        ),
        "efficient_count": result.efficient_count,
        "market_gas_label": result.market_gas_label,
        "recommendation_summary": result.recommendation_summary,
        "saved_to": result.saved_to,
    }


def save_results(
    result: GasCostResult,
    data_file: str = DEFAULT_DATA_FILE,
) -> str:
    """Atomically append result to ring-buffer JSON file (cap 100)."""
    history = load_history(data_file)
    history.append(_result_to_dict(result))
    if len(history) > RING_BUFFER_CAP:
        history = history[-RING_BUFFER_CAP:]

    os.makedirs(os.path.dirname(data_file), exist_ok=True)
    atomic_save(history, str(data_file))
    result.saved_to = data_file
    return data_file


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_SAMPLE_POSITIONS = [
    {
        "protocol": "Aave V3 Mainnet",
        "position_size_usd": 50_000.0,
        "annual_apy_pct": 3.5,
        "deposit_gas_units": 150_000,
        "withdraw_gas_units": 120_000,
        "rebalance_gas_units": 200_000,
        "rebalance_count": 12,
        "gas_price_gwei": 30.0,
        "eth_price_usd": 3_500.0,
        "chain": "MAINNET",
    },
    {
        "protocol": "Aave V3 Arbitrum",
        "position_size_usd": 50_000.0,
        "annual_apy_pct": 4.6,
        "deposit_gas_units": 150_000,
        "withdraw_gas_units": 120_000,
        "rebalance_gas_units": 200_000,
        "rebalance_count": 12,
        "gas_price_gwei": 30.0,
        "eth_price_usd": 3_500.0,
        "chain": "ARBITRUM",
    },
    {
        "protocol": "Compound V3 Base",
        "position_size_usd": 30_000.0,
        "annual_apy_pct": 4.8,
        "deposit_gas_units": 130_000,
        "withdraw_gas_units": 110_000,
        "rebalance_gas_units": 180_000,
        "rebalance_count": 4,
        "gas_price_gwei": 30.0,
        "eth_price_usd": 3_500.0,
        "chain": "BASE",
    },
]


def main() -> None:
    mode = "--check"
    data_file = DEFAULT_DATA_FILE
    args = sys.argv[1:]
    if "--run" in args:
        mode = "--run"
    if "--data-dir" in args:
        idx = args.index("--data-dir")
        if idx + 1 < len(args):
            data_file = os.path.join(args[idx + 1], "gas_cost_log.json")

    result = profile_market(_SAMPLE_POSITIONS, data_file=data_file)

    print("=== MP-749 GasCostProfiler ===")
    print(f"Market gas label:      {result.market_gas_label}")
    print(f"Most efficient:        {result.most_gas_efficient_protocol}")
    print(f"Least efficient:       {result.least_gas_efficient_protocol}")
    print(f"Avg gas drag:          {result.avg_gas_drag_pct:.3f}%")
    print(f"Avg break-even size:   ${result.avg_breakeven_usd:,.0f}")
    print(f"Efficient positions:   {result.efficient_count}/{len(result.profiles)}")
    print(f"Summary: {result.recommendation_summary}")
    print()
    for p in result.profiles:
        print(
            f"  [{p.gas_efficiency_label:8s}] {p.protocol} "
            f"size=${p.position_size_usd:,.0f} "
            f"gas=${p.total_gas_usd:.2f} "
            f"drag={p.annual_gas_drag_pct:.3f}% "
            f"net_apy={p.net_apy_after_gas_pct:.2f}%"
        )
        print(f"           break-even: ${p.breakeven_position_usd:,.0f} | {p.recommendation}")

    if mode == "--run":
        save_results(result, data_file)
        print(f"\nSaved → {result.saved_to}")


if __name__ == "__main__":
    main()
