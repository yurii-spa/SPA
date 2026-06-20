"""
MP-955: ProtocolCrossChainFeeComparator
========================================
Compares transaction costs across different blockchains (L1/L2) for common
DeFi operations: transfers, swaps, LP operations, bridging.

Advisory-only. Pure stdlib. No external dependencies.
Ring-buffer log → data/cross_chain_fee_log.json (cap 100, atomic write).

CLI:
    python3 -m spa_core.analytics.protocol_cross_chain_fee_comparator --check
    python3 -m spa_core.analytics.protocol_cross_chain_fee_comparator --run [--data-dir DIR]
"""

from __future__ import annotations

import json
import os
import sys
import time
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_CAP = 100
_VERSION = "mp955-1.0"

# Fee label thresholds (full DeFi cycle cost in USD)
_ULTRA_CHEAP_THRESHOLD = 0.10
_CHEAP_THRESHOLD = 1.00
_MODERATE_THRESHOLD = 10.00
_EXPENSIVE_THRESHOLD = 50.00

# Flag thresholds
_HIGH_THROUGHPUT_TPS = 1000.0
_FAST_FINALITY_SECONDS = 5.0
_BRIDGE_EXPENSIVE_USD = 10.0
_L2_DISCOUNT_CYCLE_THRESHOLD = 1.0


# ---------------------------------------------------------------------------
# ProtocolCrossChainFeeComparator
# ---------------------------------------------------------------------------

class ProtocolCrossChainFeeComparator:
    """
    MP-955: Compares operation costs across chains for DeFi participants.

    Per-chain outputs:
        simple_transfer_usd, token_swap_usd, lp_deposit_usd,
        lp_withdrawal_usd, bridge_out_usd, full_defi_cycle_usd,
        cost_efficiency_score (0-100), fee_label, flags

    Aggregates:
        cheapest_chain, most_expensive_chain, cheapest_for_small_txs,
        recommended_for_defi, average_cycle_cost_usd
    """

    _LOG_CAP = _LOG_CAP
    _VERSION = _VERSION

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compare(self, chains: list, config: dict = None) -> dict:
        """
        Compare transaction costs across the provided chain specifications.

        Parameters
        ----------
        chains : list[dict]
            Each dict: name, avg_gas_price_gwei, eth_price_usd,
            simple_transfer_gas, token_swap_gas, lp_deposit_gas,
            lp_withdrawal_gas, bridge_gas_out, native_token_price_usd,
            tps_capacity, avg_finality_seconds, is_l2 (bool),
            l1_data_posting_cost_per_tx_usd (for L2)
        config : dict, optional
            Reserved for future overrides.

        Returns
        -------
        dict with keys: chains, aggregates, metadata
        """
        cfg = config or {}
        chain_results = [self._analyze_chain(chain, cfg) for chain in chains]
        self._compute_efficiency_scores(chain_results)
        aggregates = self._compute_aggregates(chain_results)
        ts = time.time()
        return {
            "chains": chain_results,
            "aggregates": aggregates,
            "metadata": {
                "timestamp": ts,
                "version": self._VERSION,
                "chains_analyzed": len(chain_results),
                "run_id": f"mp955_{int(ts)}",
            },
        }

    def write_log(self, result: dict, data_dir: str) -> None:
        """Append result to ring-buffer log (atomic write, cap 100)."""
        log_path = os.path.join(data_dir, "cross_chain_fee_log.json")
        os.makedirs(data_dir, exist_ok=True)

        entries: list = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as fh:
                    entries = json.load(fh)
                if not isinstance(entries, list):
                    entries = []
            except (json.JSONDecodeError, OSError):
                entries = []

        entries.append(result)
        if len(entries) > self._LOG_CAP:
            entries = entries[-self._LOG_CAP:]

        dir_name = os.path.dirname(log_path) or "."
        atomic_save(entries, str(log_path))
    # ------------------------------------------------------------------
    # Internal: per-chain analysis
    # ------------------------------------------------------------------

    def _analyze_chain(self, chain: dict, cfg: dict) -> dict:
        name = chain.get("name", "")
        avg_gas_price_gwei = float(chain.get("avg_gas_price_gwei", 0.0))
        eth_price_usd = float(chain.get("eth_price_usd", 0.0))
        # native_token_price_usd falls back to eth_price_usd if not set
        native_token_price_usd = float(
            chain.get("native_token_price_usd", eth_price_usd)
        )
        simple_transfer_gas = float(chain.get("simple_transfer_gas", 21000))
        token_swap_gas = float(chain.get("token_swap_gas", 150000))
        lp_deposit_gas = float(chain.get("lp_deposit_gas", 200000))
        lp_withdrawal_gas = float(chain.get("lp_withdrawal_gas", 180000))
        bridge_gas_out = float(chain.get("bridge_gas_out", 100000))
        tps_capacity = float(chain.get("tps_capacity", 0.0))
        avg_finality_seconds = float(chain.get("avg_finality_seconds", 0.0))
        is_l2 = bool(chain.get("is_l2", False))
        l1_data_posting_cost_per_tx_usd = float(
            chain.get("l1_data_posting_cost_per_tx_usd", 0.0)
        )

        def gas_usd(gas_units: float) -> float:
            """Convert gas units to USD using gwei price and native token price."""
            return gas_units * avg_gas_price_gwei * 1e-9 * native_token_price_usd

        # Base execution costs
        simple_transfer_usd = gas_usd(simple_transfer_gas)
        token_swap_usd = gas_usd(token_swap_gas)
        lp_deposit_usd = gas_usd(lp_deposit_gas)
        lp_withdrawal_usd = gas_usd(lp_withdrawal_gas)
        bridge_out_usd = gas_usd(bridge_gas_out)

        # For L2: add L1 data posting cost to each operation
        l1_data = l1_data_posting_cost_per_tx_usd if is_l2 else 0.0
        if l1_data > 0:
            simple_transfer_usd += l1_data
            token_swap_usd += l1_data
            lp_deposit_usd += l1_data
            lp_withdrawal_usd += l1_data
            bridge_out_usd += l1_data

        # Full DeFi cycle: transfer + swap + lp_deposit + lp_withdrawal
        full_defi_cycle_usd = (
            simple_transfer_usd
            + token_swap_usd
            + lp_deposit_usd
            + lp_withdrawal_usd
        )

        # Fee label
        fee_label = self._compute_fee_label(full_defi_cycle_usd)

        # Flags
        flags: list = []

        if is_l2 and full_defi_cycle_usd < _L2_DISCOUNT_CYCLE_THRESHOLD:
            flags.append("L2_DISCOUNT")

        if tps_capacity > _HIGH_THROUGHPUT_TPS:
            flags.append("HIGH_THROUGHPUT")

        if avg_finality_seconds < _FAST_FINALITY_SECONDS:
            flags.append("FAST_FINALITY")

        # L1_DATA_COST_DOMINANT: L1 data > 50% of cycle cost (4 ops in cycle)
        if is_l2 and l1_data > 0 and full_defi_cycle_usd > 0:
            total_l1_in_cycle = 4.0 * l1_data
            if total_l1_in_cycle > 0.5 * full_defi_cycle_usd:
                flags.append("L1_DATA_COST_DOMINANT")

        if bridge_out_usd > _BRIDGE_EXPENSIVE_USD:
            flags.append("BRIDGE_EXPENSIVE")

        return {
            "name": name,
            "is_l2": is_l2,
            "avg_finality_seconds": avg_finality_seconds,
            "tps_capacity": tps_capacity,
            "simple_transfer_usd": round(simple_transfer_usd, 8),
            "token_swap_usd": round(token_swap_usd, 8),
            "lp_deposit_usd": round(lp_deposit_usd, 8),
            "lp_withdrawal_usd": round(lp_withdrawal_usd, 8),
            "bridge_out_usd": round(bridge_out_usd, 8),
            "full_defi_cycle_usd": round(full_defi_cycle_usd, 8),
            "cost_efficiency_score": None,   # filled by _compute_efficiency_scores
            "fee_label": fee_label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Internal: efficiency scores (normalised across all chains)
    # ------------------------------------------------------------------

    def _compute_efficiency_scores(self, results: list) -> None:
        """Fill cost_efficiency_score (0–100) for each chain in-place."""
        if not results:
            return
        max_cost = max(r["full_defi_cycle_usd"] for r in results)
        min_cost = min(r["full_defi_cycle_usd"] for r in results)
        spread = max_cost - min_cost
        for r in results:
            if spread == 0:
                r["cost_efficiency_score"] = 100.0
            else:
                score = 100.0 * (max_cost - r["full_defi_cycle_usd"]) / spread
                r["cost_efficiency_score"] = round(score, 2)

    # ------------------------------------------------------------------
    # Internal: label
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_fee_label(cycle_usd: float) -> str:
        if cycle_usd < _ULTRA_CHEAP_THRESHOLD:
            return "ULTRA_CHEAP"
        if cycle_usd < _CHEAP_THRESHOLD:
            return "CHEAP"
        if cycle_usd < _MODERATE_THRESHOLD:
            return "MODERATE"
        if cycle_usd < _EXPENSIVE_THRESHOLD:
            return "EXPENSIVE"
        return "PROHIBITIVE"

    # ------------------------------------------------------------------
    # Internal: aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "cheapest_chain": None,
                "most_expensive_chain": None,
                "cheapest_for_small_txs": None,
                "recommended_for_defi": None,
                "average_cycle_cost_usd": None,
            }

        cheapest = min(results, key=lambda r: r["full_defi_cycle_usd"])
        most_expensive = max(results, key=lambda r: r["full_defi_cycle_usd"])
        cheapest_for_small = min(results, key=lambda r: r["simple_transfer_usd"])

        # recommended_for_defi: best cycle cost + finality bonus
        def _defi_score(r: dict) -> float:
            cost_score = r["cost_efficiency_score"] or 0.0
            # Finality bonus: <5s gets full bonus, drops off toward 60s
            finality = r["avg_finality_seconds"]
            finality_bonus = max(0.0, 20.0 - finality)
            return cost_score + finality_bonus

        recommended = max(results, key=_defi_score)

        avg_cycle = sum(r["full_defi_cycle_usd"] for r in results) / len(results)

        return {
            "cheapest_chain": cheapest["name"],
            "most_expensive_chain": most_expensive["name"],
            "cheapest_for_small_txs": cheapest_for_small["name"],
            "recommended_for_defi": recommended["name"],
            "average_cycle_cost_usd": round(avg_cycle, 8),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_demo_chains() -> list:
    return [
        {
            "name": "Ethereum",
            "avg_gas_price_gwei": 30.0,
            "native_token_price_usd": 3500.0,
            "simple_transfer_gas": 21000,
            "token_swap_gas": 150000,
            "lp_deposit_gas": 200000,
            "lp_withdrawal_gas": 180000,
            "bridge_gas_out": 100000,
            "tps_capacity": 15,
            "avg_finality_seconds": 780,
            "is_l2": False,
            "l1_data_posting_cost_per_tx_usd": 0.0,
        },
        {
            "name": "Arbitrum One",
            "avg_gas_price_gwei": 0.1,
            "native_token_price_usd": 3500.0,
            "simple_transfer_gas": 21000,
            "token_swap_gas": 300000,
            "lp_deposit_gas": 400000,
            "lp_withdrawal_gas": 360000,
            "bridge_gas_out": 200000,
            "tps_capacity": 4000,
            "avg_finality_seconds": 1,
            "is_l2": True,
            "l1_data_posting_cost_per_tx_usd": 0.005,
        },
        {
            "name": "Polygon PoS",
            "avg_gas_price_gwei": 50.0,
            "native_token_price_usd": 0.7,
            "simple_transfer_gas": 21000,
            "token_swap_gas": 150000,
            "lp_deposit_gas": 200000,
            "lp_withdrawal_gas": 180000,
            "bridge_gas_out": 100000,
            "tps_capacity": 7000,
            "avg_finality_seconds": 2,
            "is_l2": False,
            "l1_data_posting_cost_per_tx_usd": 0.0,
        },
    ]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-955 ProtocolCrossChainFeeComparator"
    )
    parser.add_argument("--run", action="store_true", help="Compute and write log")
    parser.add_argument(
        "--check", action="store_true", help="Compute and print (no write)"
    )
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
    data_dir = args.data_dir or os.path.join(repo_root, "data")

    comparator = ProtocolCrossChainFeeComparator()
    result = comparator.compare(_default_demo_chains())

    print(json.dumps(result, indent=2))

    if args.run:
        comparator.write_log(result, data_dir)
        log_path = os.path.join(data_dir, "cross_chain_fee_log.json")
        print(f"\n[MP-955] Log written → {log_path}")


if __name__ == "__main__":
    main()
