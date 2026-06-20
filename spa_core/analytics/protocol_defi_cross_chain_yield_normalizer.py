"""
MP-1023: ProtocolDeFiCrossChainYieldNormalizer
Нормализует доходности DeFi стратегий с разных чейнов с учётом bridging costs и risks.
Только stdlib Python, atomic writes, read-only домен.
"""

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# Default data directory (relative to repo root)
_DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")

# Chain risk scores (defaults) — L1=10, established_L2=20, newer_L2=40, sidechain=60
_CHAIN_DEFAULT_RISK: dict = {
    "ethereum": 10,
    "arbitrum": 20,
    "optimism": 20,
    "base": 20,
    "polygon": 40,
    "avalanche": 40,
    "bsc": 60,
}


def _atomic_write(path: str, data: Any) -> None:
    """Atomic write: tmp file + os.replace."""
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    atomic_save(data, str(path))
def _load_ring_buffer(path: str, cap: int) -> list:
    """Load existing ring-buffer log or return empty list."""
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data[-cap:]
        return []
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return []


class ProtocolDeFiCrossChainYieldNormalizer:
    """
    Normalizes DeFi yield opportunities across chains, accounting for
    bridging costs, gas friction, and chain-specific risks.

    normalize(opportunities, config) -> dict with normalized opportunities
    and cross-chain comparison aggregates.
    """

    LOG_FILE = "cross_chain_yield_normalized_log.json"
    LOG_CAP = 100

    def __init__(self, data_dir: str | None = None):
        self.data_dir = data_dir or _DEFAULT_DATA_DIR

    # ------------------------------------------------------------------
    # Computation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _total_bridge_cost(opp: dict) -> float:
        """bridge_cost_usd_one_way + bridge_cost_usd_return"""
        bridge_in = float(opp.get("bridge_cost_usd_one_way", 0))
        bridge_out = float(opp.get("bridge_cost_usd_return", 0))
        return bridge_in + bridge_out

    @staticmethod
    def _bridge_cost_annualized_pct(opp: dict, total_bridge: float) -> float:
        """
        (total_bridge / position_size) × 12 (monthly rebalance cadence → ×12/year)
        We assume bridge costs are a one-time round-trip per year for simplicity.
        """
        position_size = float(opp.get("position_size_usd", 1))
        if position_size <= 0:
            return 0.0
        return (total_bridge / position_size) * 100.0

    @staticmethod
    def _monthly_gas_cost(opp: dict) -> float:
        """gas_cost_per_interaction_usd × interactions_per_month"""
        gas = float(opp.get("gas_cost_per_interaction_usd", 0))
        interactions = float(opp.get("interactions_per_month", 1))
        return gas * interactions

    @staticmethod
    def _total_friction_pct(bridge_annualized: float, monthly_gas_usd: float,
                            position_size: float) -> float:
        """
        bridge_cost_annualized_pct + gas_annualized_pct
        gas_annualized_pct = monthly_gas × 12 / position_size × 100
        """
        if position_size <= 0:
            return 0.0
        gas_annual_pct = (monthly_gas_usd * 12.0 / position_size) * 100.0
        return bridge_annualized + gas_annual_pct

    @staticmethod
    def _chain_risk_adjusted_apy(opp: dict) -> float:
        """
        nominal_apy × (100 - chain_risk_score) / 100
        Uses opp['chain_risk_score'] if provided, else default from _CHAIN_DEFAULT_RISK.
        """
        nominal = float(opp.get("nominal_apy_pct", 0))
        chain = opp.get("chain", "ethereum").lower()
        chain_risk = float(opp.get("chain_risk_score",
                                   _CHAIN_DEFAULT_RISK.get(chain, 40)))
        return nominal * (100.0 - chain_risk) / 100.0

    @staticmethod
    def _net_normalized_apy(chain_adjusted: float, total_friction: float) -> float:
        """chain_risk_adjusted_apy - total_friction_pct"""
        return chain_adjusted - total_friction

    @staticmethod
    def _position_viability_score(opp: dict, net_apy: float,
                                  monthly_gas: float) -> float:
        """
        0-100:
        net_apy>0 (×40) + position>min_viable (×40) + bridge_time<24h (×20)
        """
        score = 0.0
        if net_apy > 0:
            score += 40.0
        position_size = float(opp.get("position_size_usd", 0))
        min_viable = float(opp.get("min_viable_position_usd", 0))
        if position_size >= min_viable:
            score += 40.0
        bridge_time = float(opp.get("bridge_time_hours", 999))
        if bridge_time < 24.0:
            score += 20.0
        return min(score, 100.0)

    def _normalized_label(self, opp: dict, net_apy: float,
                          total_friction: float, viability: float,
                          nominal_apy: float) -> str:
        """
        SUPERIOR_OPPORTUNITY / ATTRACTIVE / MARGINAL /
        FRICTION_DOMINATED / UNVIABLE
        """
        position_size = float(opp.get("position_size_usd", 0))
        min_viable = float(opp.get("min_viable_position_usd", 0))
        viable_position = position_size >= min_viable

        if net_apy < 0 or not viable_position:
            return "UNVIABLE"
        if nominal_apy > 0 and total_friction > nominal_apy * 0.5:
            return "FRICTION_DOMINATED"
        if net_apy > 10 and viable_position:
            return "SUPERIOR_OPPORTUNITY"
        if net_apy > 5:
            return "ATTRACTIVE"
        if net_apy > 2:
            return "MARGINAL"
        return "UNVIABLE"

    def _compute_flags(self, opp: dict, monthly_gas: float,
                       total_bridge: float, net_apy: float) -> list:
        """Compute applicable flags."""
        flags = []
        chain = opp.get("chain", "ethereum").lower()
        chain_risk = float(opp.get("chain_risk_score",
                                   _CHAIN_DEFAULT_RISK.get(chain, 40)))
        position_size = float(opp.get("position_size_usd", 0))
        min_viable = float(opp.get("min_viable_position_usd", 0))
        bridge_time = float(opp.get("bridge_time_hours", 999))

        # friction for L2_NATIVE_ADVANTAGE
        nominal = float(opp.get("nominal_apy_pct", 0))
        if position_size > 0:
            gas_annual_pct = (monthly_gas * 12.0 / position_size) * 100.0
            bridge_ann = (total_bridge / position_size) * 100.0
            total_f = gas_annual_pct + bridge_ann
        else:
            total_f = 999.0

        if chain != "ethereum" and total_f < 1.0:
            flags.append("L2_NATIVE_ADVANTAGE")
        if total_bridge > 100.0:
            flags.append("BRIDGE_HEAVY")
        if monthly_gas > 200.0:
            flags.append("GAS_INTENSIVE")
        if position_size < min_viable:
            flags.append("POSITION_TOO_SMALL")
        if chain_risk > 50:
            flags.append("HIGH_CHAIN_RISK")
        if chain == "ethereum" and monthly_gas > 50.0:
            flags.append("ETHEREUM_MAINNET_COST")
        return flags

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def normalize(self, opportunities: list, config: dict | None = None) -> dict:
        """
        Normalize yield opportunities across chains.

        Args:
            opportunities: list of opportunity dicts
            config: optional config dict (data_dir, etc.)

        Returns:
            dict with normalized_opportunities, aggregates, chain_comparison, metadata
        """
        if config is None:
            config = {}

        data_dir = config.get("data_dir", self.data_dir)
        log_path = os.path.join(data_dir, self.LOG_FILE)

        normalized = []
        for opp in opportunities:
            total_bridge = self._total_bridge_cost(opp)
            position_size = float(opp.get("position_size_usd", 1))
            bridge_ann = self._bridge_cost_annualized_pct(opp, total_bridge)
            monthly_gas = self._monthly_gas_cost(opp)
            total_friction = self._total_friction_pct(bridge_ann, monthly_gas,
                                                      position_size)
            chain_adj_apy = self._chain_risk_adjusted_apy(opp)
            net_apy = self._net_normalized_apy(chain_adj_apy, total_friction)
            viability = self._position_viability_score(opp, net_apy, monthly_gas)
            nominal_apy = float(opp.get("nominal_apy_pct", 0))
            label = self._normalized_label(opp, net_apy, total_friction,
                                           viability, nominal_apy)
            flags = self._compute_flags(opp, monthly_gas, total_bridge, net_apy)

            chain = opp.get("chain", "unknown").lower()
            chain_risk = float(opp.get("chain_risk_score",
                                       _CHAIN_DEFAULT_RISK.get(chain, 40)))

            normalized.append({
                "name": opp.get("name", ""),
                "protocol": opp.get("protocol", ""),
                "chain": chain,
                "nominal_apy_pct": round(nominal_apy, 4),
                "chain_risk_score": round(chain_risk, 2),
                "total_bridge_cost_usd": round(total_bridge, 4),
                "bridge_cost_annualized_pct": round(bridge_ann, 4),
                "monthly_gas_cost_usd": round(monthly_gas, 4),
                "total_friction_pct": round(total_friction, 4),
                "chain_risk_adjusted_apy": round(chain_adj_apy, 4),
                "net_normalized_apy": round(net_apy, 4),
                "position_viability_score": round(viability, 2),
                "normalized_label": label,
                "flags": flags,
            })

        # Aggregates
        if normalized:
            net_apys = [n["net_normalized_apy"] for n in normalized]
            avg_net = sum(net_apys) / len(net_apys)
            best = max(normalized, key=lambda n: n["net_normalized_apy"])
            worst = min(normalized, key=lambda n: n["net_normalized_apy"])
            superior = [n["name"] for n in normalized
                        if n["normalized_label"] == "SUPERIOR_OPPORTUNITY"]
            unviable = [n["name"] for n in normalized
                        if n["normalized_label"] == "UNVIABLE"]

            # Chain comparison: avg net_apy per chain
            chain_sums: dict = {}
            chain_counts: dict = {}
            for n in normalized:
                ch = n["chain"]
                chain_sums[ch] = chain_sums.get(ch, 0.0) + n["net_normalized_apy"]
                chain_counts[ch] = chain_counts.get(ch, 0) + 1
            chain_comparison = {
                ch: round(chain_sums[ch] / chain_counts[ch], 4)
                for ch in chain_sums
            }
        else:
            avg_net = 0.0
            best = {}
            worst = {}
            superior = []
            unviable = []
            chain_comparison = {}

        aggregates = {
            "best_normalized": best.get("name", "") if best else "",
            "worst_normalized": worst.get("name", "") if worst else "",
            "avg_net_apy": round(avg_net, 4),
            "superior_count": len(superior),
            "unviable_count": len(unviable),
            "superior_opportunities": superior,
            "unviable_opportunities": unviable,
            "chain_comparison": chain_comparison,
        }

        result = {
            "normalized_opportunities": normalized,
            "aggregates": aggregates,
            "metadata": {
                "module": "ProtocolDeFiCrossChainYieldNormalizer",
                "mp": "MP-1023",
                "opportunity_count": len(opportunities),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        }

        # Ring-buffer log (cap 100), atomic write
        log_entry = {
            "timestamp": result["metadata"]["timestamp"],
            "opportunity_count": len(opportunities),
            "avg_net_apy": aggregates["avg_net_apy"],
            "superior_count": aggregates["superior_count"],
            "unviable_count": aggregates["unviable_count"],
        }
        buf = _load_ring_buffer(log_path, self.LOG_CAP)
        buf.append(log_entry)
        buf = buf[-self.LOG_CAP:]
        _atomic_write(log_path, buf)

        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    demo_opps = [
        {
            "name": "Aave USDC Ethereum",
            "protocol": "Aave V3",
            "chain": "ethereum",
            "nominal_apy_pct": 3.5,
            "tvl_usd": 500_000_000,
            "bridge_cost_usd_one_way": 0,
            "bridge_cost_usd_return": 0,
            "bridge_time_hours": 0,
            "chain_risk_score": 10,
            "gas_cost_per_interaction_usd": 30,
            "interactions_per_month": 4,
            "position_size_usd": 50_000,
            "min_viable_position_usd": 10_000,
        },
        {
            "name": "Aave USDC Arbitrum",
            "protocol": "Aave V3",
            "chain": "arbitrum",
            "nominal_apy_pct": 4.6,
            "tvl_usd": 100_000_000,
            "bridge_cost_usd_one_way": 5,
            "bridge_cost_usd_return": 5,
            "bridge_time_hours": 7 * 24,  # 7 days (L2 withdrawal delay)
            "chain_risk_score": 20,
            "gas_cost_per_interaction_usd": 0.5,
            "interactions_per_month": 4,
            "position_size_usd": 50_000,
            "min_viable_position_usd": 5_000,
        },
    ]

    normalizer = ProtocolDeFiCrossChainYieldNormalizer()
    result = normalizer.normalize(demo_opps, {})
    print(json.dumps(result, indent=2))
