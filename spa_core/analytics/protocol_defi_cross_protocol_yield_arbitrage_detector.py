"""
MP-1041: ProtocolDeFiCrossProtocolYieldArbitrageDetector
=========================================================
Advisory-only analytics module.
Detects yield arbitrage opportunities between DeFi protocols for the same asset
by comparing supply APYs across chains and protocols, net of slippage, bridge
costs, and execution complexity.

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/cross_protocol_yield_arbitrage_log.json.
Atomic writes: tmp + os.replace.

Input per opportunity
---------------------
protocol        : str    e.g. "Aave V3 Ethereum"
supply_apy_pct  : float  annualized lending supply yield (%)
borrow_apy_pct  : float  annualized borrow cost if funding from this protocol (%)
asset           : str    e.g. "USDC"
chain           : str    e.g. "ethereum", "arbitrum"
slippage_bps    : float  expected execution slippage in basis points
bridge_cost_usd : float  one-time bridge cost in USD (0 for same-chain)

Config
------
min_spread_bps   : float  minimum net spread to flag as arbitrage (default 50)
position_size_usd: float  notional position size in USD (default 100_000)

Outputs
-------
best_opportunity          : dict  the protocol pair with the highest net arb APY
spread_bps                : float gross spread between best supply and worst (or borrow)
net_arb_apy_pct           : float spread after execution costs, annualized
execution_complexity_score: float 0-100 (higher = more complex / risky)
label                     : STRONG_ARBITRAGE / MARGINAL_ARBITRAGE / NO_ARBITRAGE /
                            NEGATIVE_CARRY / EXECUTION_RISK_TOO_HIGH

Labels
------
STRONG_ARBITRAGE      : net_arb_apy > 2% AND execution_complexity ≤ 50
MARGINAL_ARBITRAGE    : net_arb_apy > 0% AND net spread ≥ min_spread_bps
NO_ARBITRAGE          : spread < min_spread_bps or net_arb_apy ≤ 0
NEGATIVE_CARRY        : net_arb_apy < 0 (costs exceed spread)
EXECUTION_RISK_TOO_HIGH: execution_complexity > 80

CLI
---
python3 -m spa_core.analytics.protocol_defi_cross_protocol_yield_arbitrage_detector --check
python3 -m spa_core.analytics.protocol_defi_cross_protocol_yield_arbitrage_detector --run
python3 -m spa_core.analytics.protocol_defi_cross_protocol_yield_arbitrage_detector --run --data-dir PATH
"""

import argparse
import json
import os
import sys
import time
from typing import List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_DATA_DIR = os.path.join(_REPO_ROOT, "data")

LOG_FILENAME = "cross_protocol_yield_arbitrage_log.json"
LOG_MAX_ENTRIES = 100

DEFAULT_MIN_SPREAD_BPS = 50.0
DEFAULT_POSITION_SIZE_USD = 100_000.0

# Complexity scoring weights
COMPLEXITY_CROSS_CHAIN_PENALTY = 30.0    # per bridge hop
COMPLEXITY_SLIPPAGE_MULTIPLIER = 0.5     # bps → complexity points
COMPLEXITY_HIGH_SLIPPAGE_THRESHOLD = 50  # bps; above this adds extra risk
COMPLEXITY_HIGH_SLIPPAGE_EXTRA = 20.0
COMPLEXITY_BORROW_RISK_PENALTY = 15.0   # if funding via borrow (leveraged arb)
COMPLEXITY_MAX = 100.0

# Label thresholds
STRONG_ARB_APY_THRESHOLD = 2.0
EXECUTION_RISK_COMPLEXITY_THRESHOLD = 80.0
MIN_SPREAD_BPS_FALLBACK = DEFAULT_MIN_SPREAD_BPS

# BPS → PCT conversion
BPS_PER_PCT = 100.0


# ---------------------------------------------------------------------------
# Helper computations
# ---------------------------------------------------------------------------

def _bps_to_pct(bps: float) -> float:
    """Convert basis points to percentage. 100 bps = 1.0 pct."""
    return bps / BPS_PER_PCT


def _execution_cost_apy_pct(
    slippage_bps: float,
    bridge_cost_usd: float,
    position_size_usd: float,
) -> float:
    """
    Annualized execution cost as % of position.
    Slippage treated as recurring (each rotation), bridge cost as one-time/year.
    """
    if position_size_usd <= 0.0:
        return 0.0
    slippage_pct = _bps_to_pct(slippage_bps)
    bridge_pct = bridge_cost_usd / position_size_usd * 100.0
    return slippage_pct + bridge_pct


def _gross_spread_bps(high_apy_pct: float, low_apy_pct: float) -> float:
    """Gross APY spread between best and worst opportunity in basis points."""
    return (high_apy_pct - low_apy_pct) * BPS_PER_PCT


def _net_arb_apy(
    gross_spread_apy_pct: float,
    execution_cost_apy_pct: float,
) -> float:
    """Net arbitrage yield after deducting execution costs."""
    return gross_spread_apy_pct - execution_cost_apy_pct


def _compute_execution_complexity(
    opp_high: dict,
    opp_low: dict,
    position_size_usd: float,
) -> float:
    """
    0-100 execution complexity score.

    Components
    ----------
    +30  per cross-chain bridge required (different chains)
    +0.5 per slippage basis point of the destination side
    +20  if destination slippage > 50 bps (high market impact)
    +15  if the lower-APY leg is accessed via borrow (leveraged carry)
    """
    score = 0.0

    # Cross-chain bridge penalty
    if opp_high.get("chain", "") != opp_low.get("chain", ""):
        score += COMPLEXITY_CROSS_CHAIN_PENALTY

    # Slippage complexity of high-APY destination
    dest_slippage = float(opp_high.get("slippage_bps", 0.0))
    score += dest_slippage * COMPLEXITY_SLIPPAGE_MULTIPLIER
    if dest_slippage > COMPLEXITY_HIGH_SLIPPAGE_THRESHOLD:
        score += COMPLEXITY_HIGH_SLIPPAGE_EXTRA

    # Leveraged / borrow risk: if the HIGH-yield destination has an
    # active borrow position, execution involves leverage risk
    if float(opp_high.get("borrow_apy_pct", 0.0)) > 0.0:
        score += COMPLEXITY_BORROW_RISK_PENALTY

    return min(COMPLEXITY_MAX, max(0.0, score))


def _spread_bps_between(opp_high: dict, opp_low: dict) -> float:
    """Gross spread in BPS between the two best protocols."""
    return _gross_spread_bps(
        float(opp_high.get("supply_apy_pct", 0.0)),
        float(opp_low.get("supply_apy_pct", 0.0)),
    )


def _net_arb_apy_between(
    opp_high: dict,
    opp_low: dict,
    position_size_usd: float,
) -> float:
    """Net arbitrage APY % between the two protocols for a given position size."""
    gross_apy = float(opp_high.get("supply_apy_pct", 0.0)) - float(opp_low.get("supply_apy_pct", 0.0))
    # Cost to enter the high-APY side
    high_exec_cost = _execution_cost_apy_pct(
        float(opp_high.get("slippage_bps", 0.0)),
        float(opp_high.get("bridge_cost_usd", 0.0)),
        position_size_usd,
    )
    # Cost to exit / fund from the low-APY side
    low_exec_cost = _execution_cost_apy_pct(
        float(opp_low.get("slippage_bps", 0.0)),
        0.0,  # bridge cost already included in high side for cross-chain
        position_size_usd,
    )
    total_cost = high_exec_cost + low_exec_cost
    return gross_apy - total_cost


def _classify_label(
    net_arb_apy: float,
    spread_bps: float,
    execution_complexity: float,
    min_spread_bps: float,
) -> str:
    """
    Assign a classification label.

    Priority order:
    1. EXECUTION_RISK_TOO_HIGH   — complexity > 80
    2. NEGATIVE_CARRY            — net_arb_apy < 0
    3. NO_ARBITRAGE              — spread < min_spread_bps or net_arb_apy <= 0
    4. STRONG_ARBITRAGE          — net_arb_apy > 2% AND complexity <= 50
    5. MARGINAL_ARBITRAGE        — default when spread >= min_spread_bps
    """
    if execution_complexity > EXECUTION_RISK_COMPLEXITY_THRESHOLD:
        return "EXECUTION_RISK_TOO_HIGH"
    if net_arb_apy < 0.0:
        return "NEGATIVE_CARRY"
    if spread_bps < min_spread_bps or net_arb_apy <= 0.0:
        return "NO_ARBITRAGE"
    if net_arb_apy > STRONG_ARB_APY_THRESHOLD and execution_complexity <= 50.0:
        return "STRONG_ARBITRAGE"
    return "MARGINAL_ARBITRAGE"


def _build_opportunity_pair(
    opp_high: dict,
    opp_low: dict,
    position_size_usd: float,
    min_spread_bps: float,
) -> dict:
    """Build a fully annotated pair dict for an arbitrage opportunity."""
    spread = _spread_bps_between(opp_high, opp_low)
    net_apy = _net_arb_apy_between(opp_high, opp_low, position_size_usd)
    complexity = _compute_execution_complexity(opp_high, opp_low, position_size_usd)
    label = _classify_label(net_apy, spread, complexity, min_spread_bps)

    return {
        "high_protocol": opp_high.get("protocol", ""),
        "low_protocol": opp_low.get("protocol", ""),
        "asset": opp_high.get("asset", ""),
        "high_supply_apy_pct": round(float(opp_high.get("supply_apy_pct", 0.0)), 6),
        "low_supply_apy_pct": round(float(opp_low.get("supply_apy_pct", 0.0)), 6),
        "spread_bps": round(spread, 4),
        "net_arb_apy_pct": round(net_apy, 6),
        "execution_complexity_score": round(complexity, 4),
        "label": label,
    }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ProtocolDeFiCrossProtocolYieldArbitrageDetector:
    """
    Detects cross-protocol yield arbitrage opportunities for the same asset
    across multiple DeFi protocols and/or chains.

    Parameters
    ----------
    data_dir : str | None
        Directory for log output. Defaults to <repo_root>/data.
    """

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or _DEFAULT_DATA_DIR
        self.log_path = os.path.join(self.data_dir, LOG_FILENAME)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self,
        opportunities: List[dict],
        min_spread_bps: float = DEFAULT_MIN_SPREAD_BPS,
        position_size_usd: float = DEFAULT_POSITION_SIZE_USD,
        save: bool = False,
    ) -> dict:
        """
        Detect yield arbitrage opportunities among a list of protocol entries.

        Parameters
        ----------
        opportunities : list[dict]
            Each dict must contain:
                protocol        : str
                supply_apy_pct  : float
                borrow_apy_pct  : float
                asset           : str
                chain           : str
                slippage_bps    : float
                bridge_cost_usd : float
        min_spread_bps    : float  minimum net spread threshold (default 50)
        position_size_usd : float  notional position size in USD (default 100_000)
        save              : bool   atomically append result to log if True

        Returns
        -------
        dict with keys:
            opportunities_analyzed, best_opportunity, all_pairs,
            spread_bps, net_arb_apy_pct, execution_complexity_score,
            label, min_spread_bps, position_size_usd, timestamp
        """
        min_spread_bps = float(min_spread_bps)
        position_size_usd = float(position_size_usd)

        if len(opportunities) < 2:
            result = self._empty_result(min_spread_bps, position_size_usd)
            if save:
                self._append_log(result)
            return result

        # Sort by supply_apy descending
        sorted_opps = sorted(
            opportunities,
            key=lambda x: float(x.get("supply_apy_pct", 0.0)),
            reverse=True,
        )

        opp_high = sorted_opps[0]
        opp_low = sorted_opps[-1]

        # Build all adjacent pairs for informational output
        all_pairs = []
        for i in range(len(sorted_opps) - 1):
            pair = _build_opportunity_pair(
                sorted_opps[i], sorted_opps[i + 1], position_size_usd, min_spread_bps
            )
            all_pairs.append(pair)

        # Best opportunity = highest vs lowest (widest raw spread)
        best_pair = _build_opportunity_pair(
            opp_high, opp_low, position_size_usd, min_spread_bps
        )

        result = {
            "opportunities_analyzed": len(opportunities),
            "best_opportunity": best_pair,
            "all_pairs": all_pairs,
            "spread_bps": best_pair["spread_bps"],
            "net_arb_apy_pct": best_pair["net_arb_apy_pct"],
            "execution_complexity_score": best_pair["execution_complexity_score"],
            "label": best_pair["label"],
            "min_spread_bps": min_spread_bps,
            "position_size_usd": position_size_usd,
            "timestamp": time.time(),
        }

        if save:
            self._append_log(result)

        return result

    # ------------------------------------------------------------------
    # Log management
    # ------------------------------------------------------------------

    def _empty_result(self, min_spread_bps: float, position_size_usd: float) -> dict:
        return {
            "opportunities_analyzed": 0,
            "best_opportunity": None,
            "all_pairs": [],
            "spread_bps": 0.0,
            "net_arb_apy_pct": 0.0,
            "execution_complexity_score": 0.0,
            "label": "NO_ARBITRAGE",
            "min_spread_bps": min_spread_bps,
            "position_size_usd": position_size_usd,
            "timestamp": time.time(),
        }

    def _append_log(self, entry: dict) -> None:
        """Atomically append entry to ring-buffer log (capped at LOG_MAX_ENTRIES)."""
        os.makedirs(self.data_dir, exist_ok=True)
        existing = self._read_log()
        existing.append(entry)
        existing = existing[-LOG_MAX_ENTRIES:]
        self._atomic_write(existing)

    def _read_log(self) -> list:
        if not os.path.exists(self.log_path):
            return []
        try:
            with open(self.log_path, "r") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _atomic_write(self, data: list) -> None:
        os.makedirs(self.data_dir, exist_ok=True)
        atomic_save(data, str(self))
    def init_log(self) -> None:
        """Initialize log file as empty list if it does not exist."""
        if not os.path.exists(self.log_path):
            self._atomic_write([])


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------

def detect(
    opportunities: List[dict],
    min_spread_bps: float = DEFAULT_MIN_SPREAD_BPS,
    position_size_usd: float = DEFAULT_POSITION_SIZE_USD,
    data_dir: Optional[str] = None,
    save: bool = False,
) -> dict:
    """Module-level shortcut: create detector and call detect()."""
    detector = ProtocolDeFiCrossProtocolYieldArbitrageDetector(data_dir=data_dir)
    return detector.detect(
        opportunities=opportunities,
        min_spread_bps=min_spread_bps,
        position_size_usd=position_size_usd,
        save=save,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MP-1041 ProtocolDeFiCrossProtocolYieldArbitrageDetector"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compute and print results without writing to log",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compute, print, and atomically save to log",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override data directory (default: <repo_root>/data)",
    )
    return parser


def _demo_samples() -> List[dict]:
    return [
        {
            "protocol": "Aave V3 Ethereum",
            "supply_apy_pct": 3.5,
            "borrow_apy_pct": 5.2,
            "asset": "USDC",
            "chain": "ethereum",
            "slippage_bps": 5.0,
            "bridge_cost_usd": 0.0,
        },
        {
            "protocol": "Compound V3 Ethereum",
            "supply_apy_pct": 4.8,
            "borrow_apy_pct": 6.1,
            "asset": "USDC",
            "chain": "ethereum",
            "slippage_bps": 5.0,
            "bridge_cost_usd": 0.0,
        },
        {
            "protocol": "Morpho Steakhouse",
            "supply_apy_pct": 6.5,
            "borrow_apy_pct": 0.0,
            "asset": "USDC",
            "chain": "ethereum",
            "slippage_bps": 10.0,
            "bridge_cost_usd": 0.0,
        },
        {
            "protocol": "Aave V3 Arbitrum",
            "supply_apy_pct": 4.6,
            "borrow_apy_pct": 5.8,
            "asset": "USDC",
            "chain": "arbitrum",
            "slippage_bps": 5.0,
            "bridge_cost_usd": 2.5,
        },
    ]


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()

    if not args.check and not args.run:
        parser.print_help()
        sys.exit(0)

    save_flag = args.run
    samples = _demo_samples()

    result = detect(
        opportunities=samples,
        data_dir=args.data_dir,
        save=save_flag,
    )
    print(json.dumps(result, indent=2))
    sys.exit(0)
