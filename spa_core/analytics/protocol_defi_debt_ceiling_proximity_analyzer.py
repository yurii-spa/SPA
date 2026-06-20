"""
MP-1091 — ProtocolDeFiDebtCeilingProximityAnalyzer

Monitors how close a lending market's total debt is to its debt ceiling
(supply cap / borrow cap).  Near-ceiling = can't open new positions,
forced exit risk.

Log file: data/debt_ceiling_proximity_log.json  (ring-buffer, cap=100)
Atomic writes: tmp + os.replace

Pure Python stdlib only.  No external dependencies.
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
    "debt_ceiling_proximity_log.json",
)
LOG_RING_CAP = 100

# Capacity label constants
LABEL_AMPLE_CAPACITY = "AMPLE_CAPACITY"
LABEL_FILLING_UP = "FILLING_UP"
LABEL_NEAR_CEILING = "NEAR_CEILING"
LABEL_AT_CEILING = "AT_CEILING"
LABEL_CEILING_BREACHED = "CEILING_BREACHED"


# ---------------------------------------------------------------------------
# Core analyzer
# ---------------------------------------------------------------------------


class ProtocolDeFiDebtCeilingProximityAnalyzer:
    """
    Monitors how close a lending market's debt is to its ceiling.

    Parameters
    ----------
    current_debt_usd : float
        Total protocol debt outstanding (USD).
    debt_ceiling_usd : float
        Protocol's maximum borrow cap (USD).
    current_supply_usd : float
        Total supplied collateral (USD).
    supply_cap_usd : float
        Maximum supply allowed (USD).
    my_position_usd : float
        User's current position size (0 if not positioned).
    daily_debt_growth_rate_pct : float
        Average daily growth rate of debt in percent (e.g. 0.5 = 0.5 %/day).
    protocol_name : str
        Human-readable protocol identifier.
    """

    def __init__(
        self,
        current_debt_usd: float,
        debt_ceiling_usd: float,
        current_supply_usd: float,
        supply_cap_usd: float,
        my_position_usd: float,
        daily_debt_growth_rate_pct: float,
        protocol_name: str,
    ) -> None:
        self.current_debt_usd = float(current_debt_usd)
        self.debt_ceiling_usd = float(debt_ceiling_usd)
        self.current_supply_usd = float(current_supply_usd)
        self.supply_cap_usd = float(supply_cap_usd)
        self.my_position_usd = float(my_position_usd)
        self.daily_debt_growth_rate_pct = float(daily_debt_growth_rate_pct)
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
            protocol_name, current_debt_usd, debt_ceiling_usd,
            current_supply_usd, supply_cap_usd, my_position_usd,
            daily_debt_growth_rate_pct,
            debt_utilization_pct, supply_utilization_pct,
            days_to_debt_ceiling, headroom_usd,
            capacity_risk_score, capacity_label,
            timestamp_utc
        """
        debt_utilization_pct = self._debt_utilization()
        supply_utilization_pct = self._supply_utilization()
        headroom_usd = self._headroom()
        days_to_debt_ceiling = self._days_to_ceiling(headroom_usd)
        max_utilization = max(debt_utilization_pct, supply_utilization_pct)
        capacity_risk_score = self._capacity_risk_score(max_utilization)
        capacity_label = self._capacity_label(max_utilization)

        result: Dict[str, Any] = {
            "protocol_name": self.protocol_name,
            "current_debt_usd": round(self.current_debt_usd, 2),
            "debt_ceiling_usd": round(self.debt_ceiling_usd, 2),
            "current_supply_usd": round(self.current_supply_usd, 2),
            "supply_cap_usd": round(self.supply_cap_usd, 2),
            "my_position_usd": round(self.my_position_usd, 2),
            "daily_debt_growth_rate_pct": round(self.daily_debt_growth_rate_pct, 6),
            "debt_utilization_pct": round(debt_utilization_pct, 4),
            "supply_utilization_pct": round(supply_utilization_pct, 4),
            "days_to_debt_ceiling": (
                round(days_to_debt_ceiling, 2)
                if math.isfinite(days_to_debt_ceiling)
                else None  # JSON-safe representation of infinity
            ),
            "headroom_usd": round(headroom_usd, 2),
            "capacity_risk_score": capacity_risk_score,
            "capacity_label": capacity_label,
            "timestamp_utc": int(time.time()),
        }
        return result

    def analyze_and_log(self, log_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Run analyze() and atomically append result to the ring-buffer log.

        Parameters
        ----------
        log_path : str, optional
            Override path for the log file.  Defaults to LOG_FILE.
        """
        result = self.analyze()
        _append_to_log(result, log_path or LOG_FILE)
        return result

    # ------------------------------------------------------------------
    # Computation helpers
    # ------------------------------------------------------------------

    def _debt_utilization(self) -> float:
        """Debt utilization = current_debt / debt_ceiling * 100."""
        if self.debt_ceiling_usd <= 0:
            return 100.0 if self.current_debt_usd > 0 else 0.0
        return (self.current_debt_usd / self.debt_ceiling_usd) * 100.0

    def _supply_utilization(self) -> float:
        """Supply utilization = current_supply / supply_cap * 100."""
        if self.supply_cap_usd <= 0:
            return 100.0 if self.current_supply_usd > 0 else 0.0
        return (self.current_supply_usd / self.supply_cap_usd) * 100.0

    def _headroom(self) -> float:
        """Headroom = debt_ceiling - current_debt  (can be negative)."""
        return self.debt_ceiling_usd - self.current_debt_usd

    def _days_to_ceiling(self, headroom_usd: float) -> float:
        """
        Days until debt reaches the ceiling at current daily growth rate.

        Formula:  days = headroom / (current_debt * daily_rate / 100)
        Returns math.inf if growth rate ≤ 0 or current_debt == 0.
        Returns 0.0 if ceiling already breached (headroom < 0).
        """
        if headroom_usd <= 0:
            return 0.0
        growth_rate = self.daily_debt_growth_rate_pct
        if growth_rate <= 0 or self.current_debt_usd <= 0:
            return math.inf
        daily_growth_usd = self.current_debt_usd * growth_rate / 100.0
        if daily_growth_usd <= 0:
            return math.inf
        return headroom_usd / daily_growth_usd

    def _capacity_risk_score(self, max_utilization: float) -> int:
        """
        Risk score 0–100.  100 = ceiling hit / breached.

        Linear mapping: utilization % → score.
        Clamped to [0, 100].
        """
        score = min(max_utilization, 100.0)
        return max(0, min(100, int(round(score))))

    def _capacity_label(self, max_utilization: float) -> str:
        """
        Classify capacity status by the highest of debt or supply utilization.

        Thresholds:
          < 50 %          → AMPLE_CAPACITY
          50 % – 75 %     → FILLING_UP
          75 % – 90 %     → NEAR_CEILING
          90 % – 100 %    → AT_CEILING
          ≥ 100 %         → CEILING_BREACHED
        """
        if max_utilization >= 100.0:
            return LABEL_CEILING_BREACHED
        if max_utilization >= 90.0:
            return LABEL_AT_CEILING
        if max_utilization >= 75.0:
            return LABEL_NEAR_CEILING
        if max_utilization >= 50.0:
            return LABEL_FILLING_UP
        return LABEL_AMPLE_CAPACITY


# ---------------------------------------------------------------------------
# Ring-buffer log helpers
# ---------------------------------------------------------------------------


def _append_to_log(entry: Dict[str, Any], log_path: str) -> None:
    """
    Atomically append *entry* to the ring-buffer JSON log at *log_path*.
    Caps the buffer at LOG_RING_CAP entries (oldest removed first).
    Uses tmp + os.replace for atomicity.
    """
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)

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

    if len(entries) > LOG_RING_CAP:
        entries = entries[-LOG_RING_CAP:]

    dir_name = os.path.dirname(os.path.abspath(log_path))
    atomic_save(entries, str(log_path))
# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _main() -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-1091 Debt Ceiling Proximity Analyzer"
    )
    parser.add_argument("--current-debt", type=float, required=True)
    parser.add_argument("--debt-ceiling", type=float, required=True)
    parser.add_argument("--current-supply", type=float, required=True)
    parser.add_argument("--supply-cap", type=float, required=True)
    parser.add_argument("--my-position", type=float, default=0.0)
    parser.add_argument("--daily-growth", type=float, default=0.0)
    parser.add_argument("--protocol", type=str, default="unknown")
    parser.add_argument("--log", action="store_true")
    args = parser.parse_args()

    analyzer = ProtocolDeFiDebtCeilingProximityAnalyzer(
        current_debt_usd=args.current_debt,
        debt_ceiling_usd=args.debt_ceiling,
        current_supply_usd=args.current_supply,
        supply_cap_usd=args.supply_cap,
        my_position_usd=args.my_position,
        daily_debt_growth_rate_pct=args.daily_growth,
        protocol_name=args.protocol,
    )

    if args.log:
        result = analyzer.analyze_and_log()
    else:
        result = analyzer.analyze()

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _main()
