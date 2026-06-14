"""
MP-1053: ProtocolDeFiGasOptimizationYieldImpactAnalyzer
Quantify how gas costs erode DeFi yield and surface optimization levers.

Gas drag is the silent killer of yield for small positions: $5 of gas on a
$500 position harvested 52x/year consumes 52% of gross yield. This module
makes that impact explicit and recommends corrective action.

Advisory / read-only. Pure stdlib. Atomic writes (os.replace).
Ring-buffer log capped at 100 entries in data/gas_optimization_yield_impact_log.json.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/gas_optimization_yield_impact_log.json")
MAX_ENTRIES = 100

# Recommendation thresholds (gas_drag_ratio = gas_drag_pct / gross_apy_pct)
RECOMMENDATION_THRESHOLDS = [
    (0.05, "GAS_NEGLIGIBLE"),    # drag < 5 % of gross yield
    (0.20, "GAS_MANAGEABLE"),    # drag 5–20 % of gross yield
    (0.50, "GAS_SIGNIFICANT"),   # drag 20–50 % of gross yield
    (1.00, "GAS_DOMINANT"),      # drag 50–100 % of gross yield
]
RECOMMENDATION_NEGATIVE = "POSITION_TOO_SMALL"  # drag > gross yield (net APY < 0)

# Known chain gas efficiency factors (relative to Ethereum mainnet = 1.0)
# Informational — not used in core math but stored in output
CHAIN_GAS_EFFICIENCY: Dict[str, float] = {
    "ethereum": 1.0,
    "arbitrum": 0.05,   # ~20x cheaper
    "base": 0.04,
    "optimism": 0.06,
    "polygon": 0.02,
    "bsc": 0.03,
    "avalanche": 0.08,
    "zksync": 0.03,
    "scroll": 0.04,
}

# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def compute_annual_gas_cost_usd(
    estimated_gas_usd_per_tx: float,
    txs_per_year: float,
    protocol_gas_rebate_pct: float,
) -> float:
    """
    Return effective annual gas cost in USD after rebate.

    effective_gas_usd_per_tx = estimated_gas_usd_per_tx * (1 - rebate / 100)
    annual_cost = effective_gas_usd_per_tx * txs_per_year
    """
    rebate_factor = 1.0 - min(1.0, max(0.0, protocol_gas_rebate_pct / 100.0))
    effective_per_tx = estimated_gas_usd_per_tx * rebate_factor
    return effective_per_tx * txs_per_year


def compute_gas_drag_pct(annual_gas_cost_usd: float, position_usd: float) -> float:
    """
    Return gas cost as a percentage of position value per year.

    gas_drag_pct = (annual_gas_cost_usd / position_usd) * 100
    Returns 0.0 if position_usd <= 0 (degenerate case).
    """
    if position_usd <= 0:
        return 0.0
    return (annual_gas_cost_usd / position_usd) * 100.0


def compute_net_apy_pct(gross_apy_pct: float, gas_drag_pct: float) -> float:
    """Return net APY after subtracting gas drag (can be negative)."""
    return gross_apy_pct - gas_drag_pct


def compute_break_even_position_usd(
    annual_gas_cost_usd: float, gross_apy_pct: float
) -> float:
    """
    Minimum position size (USD) for the strategy to break even (net APY = 0).

    break_even = annual_gas_cost_usd * 100 / gross_apy_pct

    Returns float('inf') if gross_apy_pct <= 0 (no yield → never breaks even).
    Returns 0.0 if annual_gas_cost_usd <= 0.
    """
    if annual_gas_cost_usd <= 0:
        return 0.0
    if gross_apy_pct <= 0:
        return float("inf")
    return annual_gas_cost_usd * 100.0 / gross_apy_pct


def compute_gas_efficiency_score(
    gas_drag_pct: float, gross_apy_pct: float
) -> float:
    """
    Score 0–100 indicating how efficiently gas is used.

    100 = gas is completely negligible relative to yield.
    0   = gas consumes all yield (or position too small / no yield).

    score = max(0, (1 - gas_drag_pct / gross_apy_pct) * 100)
    Capped at [0, 100].
    """
    if gross_apy_pct <= 0:
        return 0.0
    ratio = gas_drag_pct / gross_apy_pct
    return round(max(0.0, min(100.0, (1.0 - ratio) * 100.0)), 4)


def compute_recommendation(
    gas_drag_pct: float, gross_apy_pct: float
) -> str:
    """
    Return recommendation label based on gas drag as a fraction of gross yield.

    POSITION_TOO_SMALL  net_apy < 0     (drag > yield)
    GAS_DOMINANT        50–100 % drag
    GAS_SIGNIFICANT     20–50 %
    GAS_MANAGEABLE      5–20 %
    GAS_NEGLIGIBLE      < 5 %
    """
    if gross_apy_pct <= 0:
        return RECOMMENDATION_NEGATIVE
    ratio = gas_drag_pct / gross_apy_pct
    if ratio >= 1.0:
        return RECOMMENDATION_NEGATIVE
    for threshold, label in RECOMMENDATION_THRESHOLDS:
        if ratio < threshold:
            return label
    return RECOMMENDATION_NEGATIVE


def chain_gas_efficiency_factor(chain: str) -> float:
    """Return the chain's gas cost factor relative to Ethereum mainnet (1.0)."""
    return CHAIN_GAS_EFFICIENCY.get(chain.lower().strip(), 1.0)


# ---------------------------------------------------------------------------
# Main analyser class
# ---------------------------------------------------------------------------


class ProtocolDeFiGasOptimizationYieldImpactAnalyzer:
    """
    Quantify gas cost impact on DeFi yield and surface optimization levers.

    Usage
    -----
    analyzer = ProtocolDeFiGasOptimizationYieldImpactAnalyzer()
    result = analyzer.analyze({
        "position_usd": 10_000,
        "gross_apy_pct": 5.0,
        "estimated_gas_usd_per_tx": 15.0,
        "txs_per_year": 24,
        "chain": "ethereum",
        "compound_frequency_per_year": 12,
        "gas_price_gwei": 30.0,
        "protocol_gas_rebate_pct": 0.0,
    })
    """

    OUTPUT_KEYS = (
        "position_usd",
        "gross_apy_pct",
        "net_apy_pct",
        "gas_drag_pct",
        "break_even_position_usd",
        "gas_efficiency_score",
        "recommendation",
        "annual_gas_cost_usd",
        "chain",
        "chain_gas_efficiency_factor",
        "timestamp",
    )

    def __init__(
        self, data_file: Path | None = None, max_entries: int = MAX_ENTRIES
    ) -> None:
        self._data_file = data_file if data_file is not None else DATA_FILE
        self._max_entries = max_entries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyse gas impact on yield and return a result dict.

        Parameters
        ----------
        params : dict with keys:
            position_usd                float  > 0
            gross_apy_pct               float  ≥ 0
            estimated_gas_usd_per_tx    float  ≥ 0
            txs_per_year                float  ≥ 0
            chain                       str    e.g. "ethereum", "base", "arbitrum"
            compound_frequency_per_year float  ≥ 0  (stored, informational)
            gas_price_gwei              float  ≥ 0  (stored, informational)
            protocol_gas_rebate_pct     float  0–100

        Returns
        -------
        dict with OUTPUT_KEYS
        """
        self._validate(params)

        position_usd = float(params["position_usd"])
        gross_apy_pct = float(params["gross_apy_pct"])
        estimated_gas_usd_per_tx = float(params["estimated_gas_usd_per_tx"])
        txs_per_year = float(params["txs_per_year"])
        chain = str(params["chain"])
        protocol_gas_rebate_pct = float(params["protocol_gas_rebate_pct"])

        # Core calculations
        annual_gas_cost_usd = compute_annual_gas_cost_usd(
            estimated_gas_usd_per_tx, txs_per_year, protocol_gas_rebate_pct
        )
        gas_drag_pct = compute_gas_drag_pct(annual_gas_cost_usd, position_usd)
        net_apy_pct = compute_net_apy_pct(gross_apy_pct, gas_drag_pct)
        break_even = compute_break_even_position_usd(annual_gas_cost_usd, gross_apy_pct)
        efficiency_score = compute_gas_efficiency_score(gas_drag_pct, gross_apy_pct)
        recommendation = compute_recommendation(gas_drag_pct, gross_apy_pct)
        cef = chain_gas_efficiency_factor(chain)

        # Serialise break_even (inf → string for JSON compatibility)
        break_even_serialized: Any = break_even if break_even != float("inf") else None

        result: Dict[str, Any] = {
            "position_usd": position_usd,
            "gross_apy_pct": gross_apy_pct,
            "net_apy_pct": round(net_apy_pct, 6),
            "gas_drag_pct": round(gas_drag_pct, 6),
            "break_even_position_usd": (
                round(break_even, 4) if break_even_serialized is not None else None
            ),
            "gas_efficiency_score": efficiency_score,
            "recommendation": recommendation,
            "annual_gas_cost_usd": round(annual_gas_cost_usd, 4),
            "chain": chain,
            "chain_gas_efficiency_factor": cef,
            "timestamp": time.time(),
        }

        self._append_log(result)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(params: Dict[str, Any]) -> None:
        required = {
            "position_usd", "gross_apy_pct", "estimated_gas_usd_per_tx",
            "txs_per_year", "chain", "compound_frequency_per_year",
            "gas_price_gwei", "protocol_gas_rebate_pct",
        }
        missing = required - set(params.keys())
        if missing:
            raise ValueError(f"Missing required params: {sorted(missing)}")
        if float(params["position_usd"]) < 0:
            raise ValueError("position_usd must be >= 0")
        if float(params["gross_apy_pct"]) < 0:
            raise ValueError("gross_apy_pct must be >= 0")
        if float(params["estimated_gas_usd_per_tx"]) < 0:
            raise ValueError("estimated_gas_usd_per_tx must be >= 0")
        if float(params["txs_per_year"]) < 0:
            raise ValueError("txs_per_year must be >= 0")
        rebate = float(params["protocol_gas_rebate_pct"])
        if rebate < 0 or rebate > 100:
            raise ValueError("protocol_gas_rebate_pct must be 0–100")
        if float(params["gas_price_gwei"]) < 0:
            raise ValueError("gas_price_gwei must be >= 0")
        if float(params["compound_frequency_per_year"]) < 0:
            raise ValueError("compound_frequency_per_year must be >= 0")

    def _append_log(self, entry: Dict[str, Any]) -> None:
        """Append entry to ring-buffer JSON log (max MAX_ENTRIES). Atomic write."""
        self._data_file.parent.mkdir(parents=True, exist_ok=True)

        existing: List[Dict[str, Any]] = []
        if self._data_file.exists():
            try:
                with open(self._data_file, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []

        existing.append(entry)
        if len(existing) > self._max_entries:
            existing = existing[-self._max_entries:]

        tmp = self._data_file.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2)
        os.replace(tmp, self._data_file)
