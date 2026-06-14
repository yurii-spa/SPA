"""
MP-776: FundingRateArbitrageDetector
=====================================
Detects funding-rate arbitrage opportunities between perpetual-futures
funding payments and spot/lending market yields.

Formula reference
-----------------
annualized_funding_pct = perp_funding_rate_8h_bps / 10_000 * 3 * 365
spread_pct             = annualized_funding_pct - spot_apy_pct
net_arb_yield_pct      = spread_pct * (1 - 1 / collateral_ratio)   [leverage-adjusted]

opportunity_grade:
  EXCELLENT  net_arb_yield > 5 %
  GOOD       net_arb_yield > 2 %
  MARGINAL   net_arb_yield > 0 %
  NONE       net_arb_yield <= 0 %

Storage
-------
Ring-buffer log capped at 100 entries.
Atomic write: tmp + os.replace().
Default data file: <project_root>/data/funding_rate_arb_log.json
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _project_root() -> str:
    """Return absolute path to the project root (two levels above this file)."""
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )


def _default_data_dir() -> str:
    return os.path.join(_project_root(), "data")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class FundingRateArbitrageDetector:
    """Detect and rank perp/spot funding-rate arbitrage opportunities.

    Parameters
    ----------
    data_dir : str, optional
        Directory for the JSON log file.  Defaults to ``<project_root>/data``.
    log_filename : str, optional
        Override the log file name.  Defaults to ``funding_rate_arb_log.json``.
    """

    _MAX_LOG = 100
    _GRADE_THRESHOLDS = [
        ("EXCELLENT", 5.0),
        ("GOOD", 2.0),
        ("MARGINAL", 0.0),
    ]

    def __init__(
        self,
        data_dir: Optional[str] = None,
        log_filename: str = "funding_rate_arb_log.json",
    ) -> None:
        self._data_dir = data_dir or _default_data_dir()
        self._log_file = os.path.join(self._data_dir, log_filename)
        self._log: List[Dict[str, Any]] = self._load_log()
        self._last_results: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_log(self) -> List[Dict[str, Any]]:
        if os.path.exists(self._log_file):
            try:
                with open(self._log_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        return data
            except (json.JSONDecodeError, OSError):
                pass
        return []

    def _save_log(self) -> None:
        """Atomic write with ring-buffer cap."""
        os.makedirs(self._data_dir, exist_ok=True)
        entries = self._log[-self._MAX_LOG:]
        tmp = self._log_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2)
        os.replace(tmp, self._log_file)

    # ------------------------------------------------------------------
    # Static computation helpers (pure functions, easily unit-tested)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_annualized_funding(perp_funding_rate_8h_bps: float) -> float:
        """Convert 8-hour funding rate in bps to annualised percentage.

        annualized = bps / 10_000 * 3 * 365
        """
        return perp_funding_rate_8h_bps / 10_000.0 * 3.0 * 365.0

    @staticmethod
    def compute_spread(annualized_funding_pct: float, spot_apy_pct: float) -> float:
        """Gross spread between annualised funding and spot APY (both in %)."""
        return annualized_funding_pct - spot_apy_pct

    @staticmethod
    def compute_net_arb_yield(spread_pct: float, collateral_ratio: float) -> float:
        """Leverage-adjusted net arbitrage yield.

        net_arb_yield = spread * (1 - 1 / collateral_ratio)

        If collateral_ratio is zero or negative, returns 0.0 to avoid division
        by zero.
        """
        if collateral_ratio <= 0.0:
            return 0.0
        return spread_pct * (1.0 - 1.0 / collateral_ratio)

    @classmethod
    def grade_opportunity(cls, net_arb_yield_pct: float) -> str:
        """Map a net_arb_yield to a qualitative grade string."""
        for grade, threshold in cls._GRADE_THRESHOLDS:
            if net_arb_yield_pct > threshold:
                return grade
        return "NONE"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Analyse a list of markets and return per-market opportunity dicts.

        Parameters
        ----------
        markets : list of dict
            Each dict must contain:
            - ``protocol``                  (str)
            - ``perp_funding_rate_8h_bps``  (float) — 8-h funding rate, basis points
            - ``spot_apy_pct``              (float) — spot/lending APY, percent
            - ``collateral_ratio``          (float) — e.g. 1.5 for 150 % collateral

        Returns
        -------
        list of dict
            Per-market analysis records, each containing:
            annualized_funding_pct, spread_pct, net_arb_yield_pct,
            opportunity_grade, and all input fields plus timestamp.
        """
        timestamp = _utc_now()
        results: List[Dict[str, Any]] = []

        for market in markets:
            protocol = market.get("protocol", "unknown")
            bps = float(market.get("perp_funding_rate_8h_bps", 0.0))
            spot_apy = float(market.get("spot_apy_pct", 0.0))
            collateral_ratio = float(market.get("collateral_ratio", 1.0))

            ann_funding = self.compute_annualized_funding(bps)
            spread = self.compute_spread(ann_funding, spot_apy)
            net_arb = self.compute_net_arb_yield(spread, collateral_ratio)
            grade = self.grade_opportunity(net_arb)

            results.append({
                "protocol": protocol,
                "perp_funding_rate_8h_bps": bps,
                "spot_apy_pct": spot_apy,
                "collateral_ratio": collateral_ratio,
                "annualized_funding_pct": round(ann_funding, 6),
                "spread_pct": round(spread, 6),
                "net_arb_yield_pct": round(net_arb, 6),
                "opportunity_grade": grade,
                "timestamp": timestamp,
            })

        self._last_results = results

        log_entry: Dict[str, Any] = {
            "timestamp": timestamp,
            "markets_analyzed": len(markets),
            "results": results,
        }
        self._log.append(log_entry)
        self._save_log()

        return results

    def get_opportunities(self) -> List[Dict[str, Any]]:
        """Return only markets with a positive net arbitrage yield (grade != NONE).

        Based on the most recent ``detect()`` call.
        Results are sorted by net_arb_yield_pct descending.
        """
        positive = [
            r for r in self._last_results
            if r.get("opportunity_grade") != "NONE"
        ]
        return sorted(
            positive,
            key=lambda r: r.get("net_arb_yield_pct", 0.0),
            reverse=True,
        )

    def get_best_opportunity(self) -> Optional[Dict[str, Any]]:
        """Return the single highest-yield opportunity from the last detect().

        Returns ``None`` if there are no positive opportunities.
        """
        opps = self.get_opportunities()
        return opps[0] if opps else None

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def log_length(self) -> int:
        """Number of detect-run entries currently in the in-memory log."""
        return len(self._log)

    def last_results(self) -> List[Dict[str, Any]]:
        """Raw results from the most recent detect() call (all grades)."""
        return list(self._last_results)
