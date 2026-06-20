"""
MP-1090 — DeFiProtocolAutoCompoundingFrequencyAnalyzer

Analyzes the effect of compounding frequency on effective APY.
Compares nominal APY vs effective APY for different compounding intervals,
accounting for gas cost drag.

Log file: data/auto_compounding_frequency_log.json  (ring-buffer, cap=100)
Atomic writes: tmp + os.replace

Pure Python stdlib only. No external dependencies.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any, Dict, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "auto_compounding_frequency_log.json",
)
LOG_RING_CAP = 100

# Compounding label constants
LABEL_OPTIMAL_FREQUENCY = "OPTIMAL_FREQUENCY"
LABEL_GOOD_FREQUENCY = "GOOD_FREQUENCY"
LABEL_OVER_COMPOUNDING = "OVER_COMPOUNDING"
LABEL_UNDER_COMPOUNDING = "UNDER_COMPOUNDING"
LABEL_GAS_DESTROYS_YIELD = "GAS_DESTROYS_YIELD"


# ---------------------------------------------------------------------------
# Core analyzer
# ---------------------------------------------------------------------------


class DeFiProtocolAutoCompoundingFrequencyAnalyzer:
    """
    Analyzes the effect of compounding frequency on effective APY,
    accounting for gas cost drag.

    Parameters
    ----------
    nominal_apy_pct : float
        Advertised nominal APY in percent (e.g. 5.0 = 5 %).
    compounds_per_year : int
        How many times compounding occurs per year
        (365=daily, 8760=hourly, 52=weekly, 12=monthly, 1=annual).
    gas_cost_usd_per_compound : float
        Gas cost in USD for each compound transaction.
    position_size_usd : float
        User's position size in USD.
    protocol_name : str
        Human-readable protocol identifier.
    """

    def __init__(
        self,
        nominal_apy_pct: float,
        compounds_per_year: int,
        gas_cost_usd_per_compound: float,
        position_size_usd: float,
        protocol_name: str,
    ) -> None:
        self.nominal_apy_pct = float(nominal_apy_pct)
        self.compounds_per_year = int(compounds_per_year)
        self.gas_cost_usd_per_compound = float(gas_cost_usd_per_compound)
        self.position_size_usd = float(position_size_usd)
        self.protocol_name = str(protocol_name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self) -> Dict[str, Any]:
        """
        Run the full analysis and return a result dictionary.

        Returns
        -------
        dict with keys:
            protocol_name, nominal_apy_pct, compounds_per_year,
            gas_cost_usd_per_compound, position_size_usd,
            effective_apy_pct, apy_boost_pct,
            annual_gas_cost_usd, annual_gas_drag_pct,
            net_effective_apy_pct, compounding_score, compounding_label,
            timestamp_utc
        """
        effective_apy_pct = self._effective_apy()
        apy_boost_pct = effective_apy_pct - self.nominal_apy_pct
        annual_gas_cost_usd = self._annual_gas_cost()
        annual_gas_drag_pct = self._gas_drag_pct(annual_gas_cost_usd)
        net_effective_apy_pct = effective_apy_pct - annual_gas_drag_pct
        compounding_score = self._compounding_score(
            effective_apy_pct, apy_boost_pct, annual_gas_drag_pct, net_effective_apy_pct
        )
        compounding_label = self._compounding_label(
            effective_apy_pct, apy_boost_pct, annual_gas_drag_pct, net_effective_apy_pct
        )

        result: Dict[str, Any] = {
            "protocol_name": self.protocol_name,
            "nominal_apy_pct": round(self.nominal_apy_pct, 6),
            "compounds_per_year": self.compounds_per_year,
            "gas_cost_usd_per_compound": round(self.gas_cost_usd_per_compound, 6),
            "position_size_usd": round(self.position_size_usd, 2),
            "effective_apy_pct": round(effective_apy_pct, 6),
            "apy_boost_pct": round(apy_boost_pct, 6),
            "annual_gas_cost_usd": round(annual_gas_cost_usd, 4),
            "annual_gas_drag_pct": round(annual_gas_drag_pct, 6),
            "net_effective_apy_pct": round(net_effective_apy_pct, 6),
            "compounding_score": compounding_score,
            "compounding_label": compounding_label,
            "timestamp_utc": int(time.time()),
        }
        return result

    def analyze_and_log(self, log_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Run analyze() and atomically append result to the ring-buffer log.

        Parameters
        ----------
        log_path : str, optional
            Override path for the log file. Defaults to LOG_FILE.
        """
        result = self.analyze()
        _append_to_log(result, log_path or LOG_FILE)
        return result

    # ------------------------------------------------------------------
    # Computation helpers
    # ------------------------------------------------------------------

    def _effective_apy(self) -> float:
        """
        Effective APY = (1 + r/n)^n - 1, expressed as percent.

        r = nominal_apy_pct / 100, n = compounds_per_year
        """
        n = self.compounds_per_year
        if n <= 0:
            return self.nominal_apy_pct
        r = self.nominal_apy_pct / 100.0
        effective = (1.0 + r / n) ** n - 1.0
        return effective * 100.0

    def _annual_gas_cost(self) -> float:
        """Total gas spent per year in USD."""
        return self.gas_cost_usd_per_compound * self.compounds_per_year

    def _gas_drag_pct(self, annual_gas_cost_usd: float) -> float:
        """Gas drag expressed as percent of position size."""
        if self.position_size_usd <= 0:
            return 0.0
        return (annual_gas_cost_usd / self.position_size_usd) * 100.0

    def _compounding_score(
        self,
        effective_apy_pct: float,
        apy_boost_pct: float,
        annual_gas_drag_pct: float,
        net_effective_apy_pct: float,
    ) -> int:
        """
        Score 0–100 representing how favourable the compounding setup is.

        Scoring logic:
        - Start at 100
        - Penalise if gas drag is large relative to APY boost
        - Penalise if compounding frequency is very low (compounds < 12)
        - Penalise if net APY is negative
        - Penalise proportionally when gas exceeds boost
        """
        score = 100

        # Penalise if the compounding frequency is very low
        if self.compounds_per_year < 12:
            # Under-compounding penalty: up to 40 points
            # at compounds=1 (annual) → -40; at compounds=12 → -0
            penalty = int(40 * (1 - self.compounds_per_year / 12))
            score -= min(penalty, 40)

        # Penalise based on gas drag ratio relative to effective APY
        if effective_apy_pct > 0:
            drag_ratio = annual_gas_drag_pct / effective_apy_pct
            # drag_ratio 0 → no penalty; drag_ratio ≥ 1 → -60 points
            gas_penalty = int(min(drag_ratio, 1.0) * 60)
            score -= gas_penalty
        elif annual_gas_drag_pct > 0:
            score -= 60

        # Hard floor: if net APY is negative, clamp to 0
        if net_effective_apy_pct < 0:
            score = 0

        return max(0, min(100, score))

    def _compounding_label(
        self,
        effective_apy_pct: float,
        apy_boost_pct: float,
        annual_gas_drag_pct: float,
        net_effective_apy_pct: float,
    ) -> str:
        """
        Classify the compounding setup.

        Priority order (first match wins):
        1. GAS_DESTROYS_YIELD  — net_effective_apy ≤ nominal * 0.5
        2. OVER_COMPOUNDING    — annual_gas_drag > apy_boost AND compounds > 52
        3. UNDER_COMPOUNDING   — compounds < 12
        4. OPTIMAL_FREQUENCY   — net_effective ≥ effective * 0.95 AND apy_boost > 0
        5. GOOD_FREQUENCY      — net_effective ≥ effective * 0.85
        6. OVER_COMPOUNDING    — fallback for excessive frequency with gas drag
        """
        # 1. Gas destroys yield
        if net_effective_apy_pct <= self.nominal_apy_pct * 0.5:
            return LABEL_GAS_DESTROYS_YIELD

        # 2. Over-compounding: gas cost exceeds compounding benefit
        if (annual_gas_drag_pct > apy_boost_pct) and (self.compounds_per_year > 52):
            return LABEL_OVER_COMPOUNDING

        # 3. Under-compounding
        if self.compounds_per_year < 12:
            return LABEL_UNDER_COMPOUNDING

        # 4. Optimal
        if effective_apy_pct > 0 and apy_boost_pct > 0:
            if net_effective_apy_pct >= effective_apy_pct * 0.95:
                return LABEL_OPTIMAL_FREQUENCY

        # 5. Good
        if effective_apy_pct > 0:
            if net_effective_apy_pct >= effective_apy_pct * 0.85:
                return LABEL_GOOD_FREQUENCY

        # 6. Default: over-compounding (gas erodes most of the gain)
        return LABEL_OVER_COMPOUNDING


# ---------------------------------------------------------------------------
# Ring-buffer log helpers
# ---------------------------------------------------------------------------


def _append_to_log(entry: Dict[str, Any], log_path: str) -> None:
    """
    Atomically append *entry* to the ring-buffer JSON log at *log_path*.
    Caps the buffer at LOG_RING_CAP entries (oldest removed first).
    Uses tmp + os.replace for atomicity.
    """
    # Ensure the parent directory exists
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)

    # Read existing log
    entries: list = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                entries = json.load(fh)
            if not isinstance(entries, list):
                entries = []
        except (json.JSONDecodeError, OSError):
            entries = []

    entries.append(entry)

    # Trim to cap
    if len(entries) > LOG_RING_CAP:
        entries = entries[-LOG_RING_CAP:]

    # Atomic write
    dir_name = os.path.dirname(os.path.abspath(log_path))
    atomic_save(entries, str(log_path))
# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _main() -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-1090 Auto-Compounding Frequency Analyzer"
    )
    parser.add_argument("--nominal-apy", type=float, required=True,
                        help="Nominal APY in percent")
    parser.add_argument("--compounds", type=int, required=True,
                        help="Compounding frequency per year")
    parser.add_argument("--gas-cost", type=float, default=0.0,
                        help="Gas cost per compound in USD")
    parser.add_argument("--position-size", type=float, default=10000.0,
                        help="Position size in USD")
    parser.add_argument("--protocol", type=str, default="unknown",
                        help="Protocol name")
    parser.add_argument("--log", action="store_true",
                        help="Write result to log file")
    args = parser.parse_args()

    analyzer = DeFiProtocolAutoCompoundingFrequencyAnalyzer(
        nominal_apy_pct=args.nominal_apy,
        compounds_per_year=args.compounds,
        gas_cost_usd_per_compound=args.gas_cost,
        position_size_usd=args.position_size,
        protocol_name=args.protocol,
    )

    if args.log:
        result = analyzer.analyze_and_log()
    else:
        result = analyzer.analyze()

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _main()
