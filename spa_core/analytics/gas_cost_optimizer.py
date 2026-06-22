"""
MP-661 GasCostOptimizer
=======================
Estimate gas costs for DeFi transactions and determine if execution is
economically viable given the expected yield gain.

Advisory / read-only analytics module.  Pure stdlib, no external deps.
Atomic writes (tmp + os.replace).  Ring-buffer cap: MAX_ENTRIES entries.
"""

from dataclasses import dataclass
from typing import List, Dict
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/gas_cost_log.json")
MAX_ENTRIES = 100

# Gas units for common DeFi operations
GAS_ESTIMATES: Dict[str, int] = {
    "ERC20_TRANSFER":    65_000,
    "AAVE_DEPOSIT":     200_000,
    "AAVE_WITHDRAW":    220_000,
    "COMPOUND_SUPPLY":  150_000,
    "CURVE_SWAP":       250_000,
    "UNISWAP_V3_SWAP":  180_000,
    "MORPHO_SUPPLY":    280_000,
    "PENDLE_SWAP":      350_000,
    "GENERIC_APPROVE":   46_000,
}

_DEFAULT_GAS_UNITS = 200_000


@dataclass
class GasEstimate:
    operation: str
    gas_units: int
    gas_price_gwei: float        # current gas price
    eth_price_usd: float         # ETH price in USD
    gas_cost_eth: float          # gas_units * gas_price_gwei * 1e-9
    gas_cost_usd: float          # gas_cost_eth * eth_price_usd
    capital_usd: float           # capital being deployed
    expected_yield_usd: float    # annualized yield from the operation
    gas_as_pct_of_capital: float # gas_cost / capital * 100
    gas_as_pct_of_yield: float   # gas_cost / expected_yield * 100
    break_even_days: float       # days until gas cost recovered from yield
    verdict: str                 # EFFICIENT / MARGINAL / EXPENSIVE / PROHIBITIVE


class GasCostOptimizer:
    """Estimate and persist gas-cost viability for DeFi operations."""

    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _gas_cost_eth(self, gas_units: int, gas_price_gwei: float) -> float:
        """Return gas cost in ETH: gas_units * gas_price_gwei * 1e-9."""
        return gas_units * gas_price_gwei * 1e-9

    def _verdict(self, gas_pct_of_yield: float) -> str:
        """Classify viability based on gas as % of annual yield."""
        if gas_pct_of_yield < 5:
            return "EFFICIENT"
        if gas_pct_of_yield < 20:
            return "MARGINAL"
        if gas_pct_of_yield < 50:
            return "EXPENSIVE"
        return "PROHIBITIVE"

    def _break_even_days(self, gas_cost_usd: float,
                          expected_yield_usd: float) -> float:
        """Days until gas cost recovered from yield.  inf when yield ≤ 0."""
        if expected_yield_usd <= 0:
            return float("inf")
        daily_yield = expected_yield_usd / 365
        return round(gas_cost_usd / daily_yield, 2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate(
        self,
        operation: str,
        gas_price_gwei: float,
        eth_price_usd: float,
        capital_usd: float,
        expected_apy: float,
    ) -> GasEstimate:
        """
        Estimate gas cost and viability for a single DeFi operation.

        Parameters
        ----------
        operation      : key from GAS_ESTIMATES (or any string for default)
        gas_price_gwei : current gas price in Gwei
        eth_price_usd  : current ETH price in USD
        capital_usd    : capital being deployed in USD
        expected_apy   : fractional APY, e.g. 0.05 for 5%
        """
        gas_units = GAS_ESTIMATES.get(operation, _DEFAULT_GAS_UNITS)
        gas_eth = self._gas_cost_eth(gas_units, gas_price_gwei)
        gas_usd = round(gas_eth * eth_price_usd, 4)
        expected_yield_usd = round(capital_usd * expected_apy, 4)

        if capital_usd > 0:
            gas_pct_capital = round(gas_usd / capital_usd * 100, 4)
        else:
            gas_pct_capital = 0.0

        if expected_yield_usd > 0:
            gas_pct_yield = round(gas_usd / expected_yield_usd * 100, 4)
        else:
            gas_pct_yield = 999.0

        be_days = self._break_even_days(gas_usd, expected_yield_usd)

        return GasEstimate(
            operation=operation,
            gas_units=gas_units,
            gas_price_gwei=round(gas_price_gwei, 2),
            eth_price_usd=round(eth_price_usd, 2),
            gas_cost_eth=round(gas_eth, 8),
            gas_cost_usd=gas_usd,
            capital_usd=round(capital_usd, 2),
            expected_yield_usd=expected_yield_usd,
            gas_as_pct_of_capital=gas_pct_capital,
            gas_as_pct_of_yield=gas_pct_yield,
            break_even_days=be_days,
            verdict=self._verdict(gas_pct_yield),
        )

    def estimate_batch(self, requests: List[dict]) -> List[GasEstimate]:
        """
        Estimate multiple operations at once.

        Each dict must contain the keyword arguments accepted by estimate():
        ``operation``, ``gas_price_gwei``, ``eth_price_usd``,
        ``capital_usd``, ``expected_apy``.
        """
        return [self.estimate(**r) for r in requests]

    def optimal_gas_price(
        self,
        max_gas_pct_of_yield: float,
        operation: str,
        eth_price_usd: float,
        capital_usd: float,
        expected_apy: float,
    ) -> float:
        """
        Return the maximum gas price (Gwei) at which the operation stays
        below ``max_gas_pct_of_yield`` % of the expected annual yield.

        Returns 0.0 when yield or ETH price is zero.
        """
        gas_units = GAS_ESTIMATES.get(operation, _DEFAULT_GAS_UNITS)
        expected_yield_usd = capital_usd * expected_apy
        if expected_yield_usd <= 0:
            return 0.0
        if eth_price_usd <= 0:
            return 0.0
        max_gas_usd = expected_yield_usd * (max_gas_pct_of_yield / 100)
        max_gas_eth = max_gas_usd / eth_price_usd
        # gas_cost_eth = gas_units * gas_price_gwei * 1e-9
        # → gas_price_gwei = gas_cost_eth / (gas_units * 1e-9)
        return round(max_gas_eth / (gas_units * 1e-9), 2)

    # ------------------------------------------------------------------
    # Persistence (ring-buffer, atomic write)
    # ------------------------------------------------------------------

    def save_estimates(self, estimates: List[GasEstimate]) -> None:
        """Append estimates to the ring-buffer log (MAX_ENTRIES cap)."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []

        for e in estimates:
            # Store float("inf") as -1 for JSON serialisability
            be_days = (
                -1
                if e.break_even_days == float("inf")
                else e.break_even_days
            )
            existing.append(
                {
                    "timestamp": time.time(),
                    "operation": e.operation,
                    "gas_cost_usd": e.gas_cost_usd,
                    "verdict": e.verdict,
                    "break_even_days": be_days,
                }
            )

        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Return persisted log, or [] if file is missing/corrupt."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []
