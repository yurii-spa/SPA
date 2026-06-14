"""
MP-995: ProtocolDeFiGasCostOptimizer
Analyzes and optimizes gas costs for DeFi operations.
Pure stdlib only. Advisory/read-only. Atomic writes.
Data log: data/gas_optimization_log.json (ring-buffer, max 100 entries)
"""

import json
import os
import time
from pathlib import Path

_LOG_CAP = 100
_DEFAULT_DATA_FILE = Path("data/gas_optimization_log.json")

# L2 chains (lower gas multiplier)
_L2_CHAINS = {"arbitrum", "base", "optimism", "polygon"}

# Efficiency label thresholds (gas_cost_bps)
_ULTRA_EFFICIENT_BPS = 5.0
_EFFICIENT_BPS = 20.0
_ACCEPTABLE_BPS = 50.0
_EXPENSIVE_BPS = 100.0

# Flag thresholds
_L2_MIGRATION_BPS = 50.0         # ethereum AND bps > 50 → recommend L2
_BATCH_SAVINGS_MIN = 50.0        # monthly savings > $50 → BATCH_OPPORTUNITY
_TIMING_SAVINGS_MIN = 30.0       # monthly savings > $30 → TIMING_OPPORTUNITY
_HARVEST_GAS_RATIO = 0.5         # gas_cost > 50% of tx_value → HARVEST_NOT_WORTH_IT
_HIGH_FREQ_COST_MIN = 500.0      # monthly > $500 → HIGH_FREQUENCY_COST
_COST_PROHIBITIVE_MONTHLY = 1000.0  # monthly > $1000 → COST_PROHIBITIVE

# Batch reduction factor
_BATCH_REDUCTION = 0.40


class ProtocolDeFiGasCostOptimizer:
    """
    Analyzes and optimizes gas costs for DeFi operations.

    Each operation dict must include:
        name (str), op_type (str: swap/borrow/repay/deposit/withdraw/harvest/rebalance/bridge),
        protocol (str), chain (str: ethereum/arbitrum/base/optimism/polygon),
        estimated_gas_units (int), current_gas_price_gwei (float),
        eth_price_usd (float), transaction_value_usd (float),
        frequency_per_month (float), can_batch (bool),
        can_delay (bool), typical_cheap_gas_gwei (float),
        congestion_factor (float: 1.0=normal, 2.0=congested)
    """

    def __init__(self, data_file: Path = _DEFAULT_DATA_FILE):
        self.data_file = Path(data_file)

    # ------------------------------------------------------------------
    # Core calculations
    # ------------------------------------------------------------------

    def _gas_cost_usd(self, op: dict) -> float:
        """gas_units * gas_price_gwei * eth_price_usd / 1e9."""
        units = op.get("estimated_gas_units", 0)
        price = op.get("current_gas_price_gwei", 0.0)
        eth_usd = op.get("eth_price_usd", 0.0)
        return round(units * price * eth_usd / 1_000_000_000.0, 6)

    def _gas_cost_bps(self, gas_cost: float, tx_value: float) -> float:
        """gas_cost / tx_value * 10000 basis points."""
        if tx_value <= 0.0:
            return 9999.0  # sentinel for zero-value transactions
        return round(gas_cost / tx_value * 10_000.0, 4)

    def _monthly_gas_cost_usd(self, gas_cost: float, frequency: float) -> float:
        """gas_cost_usd * frequency_per_month."""
        return round(gas_cost * max(0.0, frequency), 6)

    def _potential_savings_batch_usd(
        self, op: dict, gas_cost: float, frequency: float
    ) -> float:
        """40% reduction if can_batch, per month."""
        if not op.get("can_batch", False):
            return 0.0
        return round(gas_cost * _BATCH_REDUCTION * max(0.0, frequency), 6)

    def _potential_savings_timing_usd(
        self, op: dict, gas_cost: float, frequency: float
    ) -> float:
        """Savings from waiting for cheap gas window, per month."""
        if not op.get("can_delay", False):
            return 0.0
        current = op.get("current_gas_price_gwei", 0.0)
        typical = op.get("typical_cheap_gas_gwei", current)
        if current <= 0.0 or typical >= current:
            return 0.0
        savings_ratio = (current - typical) / current
        return round(gas_cost * savings_ratio * max(0.0, frequency), 6)

    def _total_potential_savings_pct(
        self, batch_savings: float, timing_savings: float, monthly_gas: float
    ) -> float:
        """Total potential savings as % of monthly gas cost."""
        total = batch_savings + timing_savings
        if monthly_gas <= 0.0:
            return 0.0
        return round(min(100.0, total / monthly_gas * 100.0), 4)

    def _cost_efficiency_score(self, bps: float) -> float:
        """
        0-100 score (higher = more efficient).
        Score = max(0, 100 - bps), clamped to [0, 100].
        """
        if bps >= 9000.0:  # sentinel for zero-value tx
            return 0.0
        return round(max(0.0, min(100.0, 100.0 - bps)), 2)

    def _efficiency_label(
        self, bps: float, chain: str, monthly_gas: float
    ) -> str:
        """Determine efficiency label."""
        # COST_PROHIBITIVE: bps >= 100 OR monthly > $1000
        if bps >= _EXPENSIVE_BPS or monthly_gas > _COST_PROHIBITIVE_MONTHLY:
            return "COST_PROHIBITIVE"
        # EXPENSIVE: bps in [50, 100)
        if bps >= _ACCEPTABLE_BPS:
            return "EXPENSIVE"
        # ACCEPTABLE: bps in [20, 50)
        if bps >= _EFFICIENT_BPS:
            return "ACCEPTABLE"
        # ULTRA_EFFICIENT: bps < 5 AND L2
        if bps < _ULTRA_EFFICIENT_BPS and chain.lower() in _L2_CHAINS:
            return "ULTRA_EFFICIENT"
        # EFFICIENT: bps < 20
        return "EFFICIENT"

    def _compute_flags(
        self,
        op: dict,
        bps: float,
        batch_savings: float,
        timing_savings: float,
        gas_cost: float,
        monthly_gas: float,
    ) -> list:
        flags = []

        chain = op.get("chain", "").lower()
        op_type = op.get("op_type", "").lower()

        # L2_MIGRATION_RECOMMENDED
        if chain == "ethereum" and bps > _L2_MIGRATION_BPS:
            flags.append("L2_MIGRATION_RECOMMENDED")

        # BATCH_OPPORTUNITY
        if op.get("can_batch", False) and batch_savings > _BATCH_SAVINGS_MIN:
            flags.append("BATCH_OPPORTUNITY")

        # TIMING_OPPORTUNITY
        if op.get("can_delay", False) and timing_savings > _TIMING_SAVINGS_MIN:
            flags.append("TIMING_OPPORTUNITY")

        # HARVEST_NOT_WORTH_IT
        if op_type == "harvest":
            tx_value = op.get("transaction_value_usd", 0.0)
            if tx_value > 0.0 and gas_cost > _HARVEST_GAS_RATIO * tx_value:
                flags.append("HARVEST_NOT_WORTH_IT")

        # HIGH_FREQUENCY_COST
        if monthly_gas > _HIGH_FREQ_COST_MIN:
            flags.append("HIGH_FREQUENCY_COST")

        return flags

    def _analyze_operation(self, op: dict) -> dict:
        name = op.get("name", "unknown")
        chain = op.get("chain", "ethereum").lower()

        gas_cost = self._gas_cost_usd(op)
        tx_value = op.get("transaction_value_usd", 0.0)
        frequency = op.get("frequency_per_month", 1.0)

        bps = self._gas_cost_bps(gas_cost, tx_value)
        monthly_gas = self._monthly_gas_cost_usd(gas_cost, frequency)
        batch_savings = self._potential_savings_batch_usd(op, gas_cost, frequency)
        timing_savings = self._potential_savings_timing_usd(op, gas_cost, frequency)
        savings_pct = self._total_potential_savings_pct(batch_savings, timing_savings, monthly_gas)
        efficiency_score = self._cost_efficiency_score(bps)
        label = self._efficiency_label(bps, chain, monthly_gas)
        flags = self._compute_flags(op, bps, batch_savings, timing_savings, gas_cost, monthly_gas)

        return {
            "name": name,
            "op_type": op.get("op_type", ""),
            "protocol": op.get("protocol", ""),
            "chain": chain,
            "gas_cost_usd": gas_cost,
            "gas_cost_bps": bps,
            "monthly_gas_cost_usd": monthly_gas,
            "potential_savings_batch_usd": batch_savings,
            "potential_savings_timing_usd": timing_savings,
            "total_potential_savings_pct": savings_pct,
            "cost_efficiency_score": efficiency_score,
            "efficiency_label": label,
            "flags": flags,
            # pass-through fields
            "estimated_gas_units": op.get("estimated_gas_units", 0),
            "current_gas_price_gwei": op.get("current_gas_price_gwei", 0.0),
            "eth_price_usd": op.get("eth_price_usd", 0.0),
            "transaction_value_usd": tx_value,
            "frequency_per_month": frequency,
            "can_batch": op.get("can_batch", False),
            "can_delay": op.get("can_delay", False),
            "typical_cheap_gas_gwei": op.get("typical_cheap_gas_gwei", 0.0),
            "congestion_factor": op.get("congestion_factor", 1.0),
        }

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "most_efficient": None,
                "most_expensive": None,
                "total_monthly_gas_usd": 0.0,
                "total_potential_savings_usd": 0.0,
                "cost_prohibitive_count": 0,
            }

        # Use efficiency_score for most_efficient (highest), gas_cost_bps for most_expensive
        most_efficient = max(results, key=lambda r: r["cost_efficiency_score"])
        most_expensive = max(results, key=lambda r: r["gas_cost_bps"])

        total_monthly = round(sum(r["monthly_gas_cost_usd"] for r in results), 6)
        total_savings = round(
            sum(
                r["potential_savings_batch_usd"] + r["potential_savings_timing_usd"]
                for r in results
            ),
            6,
        )
        prohibitive_count = sum(
            1 for r in results if r["efficiency_label"] == "COST_PROHIBITIVE"
        )

        return {
            "most_efficient": most_efficient["name"],
            "most_expensive": most_expensive["name"],
            "total_monthly_gas_usd": total_monthly,
            "total_potential_savings_usd": total_savings,
            "cost_prohibitive_count": prohibitive_count,
        }

    # ------------------------------------------------------------------
    # Atomic log write
    # ------------------------------------------------------------------

    def _append_log(self, entry: dict) -> None:
        """Ring-buffer append to data_file (max _LOG_CAP entries). Atomic write."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)

        if self.data_file.exists():
            try:
                with open(self.data_file, "r", encoding="utf-8") as fh:
                    log = json.load(fh)
                    if not isinstance(log, list):
                        log = []
            except (json.JSONDecodeError, OSError):
                log = []
        else:
            log = []

        log.append(entry)
        if len(log) > _LOG_CAP:
            log = log[-_LOG_CAP:]

        tmp = str(self.data_file) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp, str(self.data_file))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(self, operations: list, config: dict = None) -> dict:
        """
        Analyze and optimize gas costs across DeFi operations.

        Parameters
        ----------
        operations : list of dict
            See class docstring for required fields.
        config : dict, optional
            Reserved for future configuration options.

        Returns
        -------
        dict with keys: operations (list of analyzed results),
                        aggregates (dict), timestamp (float), config (dict).
        """
        if config is None:
            config = {}

        analyzed = [self._analyze_operation(op) for op in operations]
        aggregates = self._compute_aggregates(analyzed)

        result = {
            "operations": analyzed,
            "aggregates": aggregates,
            "timestamp": time.time(),
            "config": config,
        }

        # Persist log entry
        log_entry = {
            "timestamp": result["timestamp"],
            "operation_count": len(analyzed),
            "total_monthly_gas_usd": aggregates["total_monthly_gas_usd"],
            "total_potential_savings_usd": aggregates["total_potential_savings_usd"],
            "cost_prohibitive_count": aggregates["cost_prohibitive_count"],
            "most_expensive": aggregates["most_expensive"],
            "summary": [
                {
                    "name": r["name"],
                    "efficiency_label": r["efficiency_label"],
                    "gas_cost_bps": r["gas_cost_bps"],
                    "monthly_gas_cost_usd": r["monthly_gas_cost_usd"],
                    "cost_efficiency_score": r["cost_efficiency_score"],
                }
                for r in analyzed
            ],
        }
        self._append_log(log_entry)

        return result
