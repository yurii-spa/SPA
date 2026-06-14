"""
MP-777: GovernanceTokenValueTracker
=====================================
Tracks whether DeFi governance tokens provide genuine economic value or
represent net dilution to holders.

Formula reference
-----------------
market_cap_usd          = token_price_usd * circulating_supply
price_to_revenue        = market_cap_usd / protocol_revenue_usd_annual
token_inflation_pct     = emission_rate_tokens_per_day * 365 / circulating_supply * 100
holder_value_score      = 100 / (1 + inflation_fraction * price_to_revenue)
                          where inflation_fraction = token_inflation_pct / 100
inflation_adjusted_yield_pct
                        = (protocol_revenue_usd_annual / market_cap_usd * 100)
                          - token_inflation_pct

value_tier:
  UNDERVALUED    holder_value_score >= 70
  FAIR           holder_value_score >= 40
  OVERVALUED     holder_value_score >= 20
  INFLATIONARY   holder_value_score <  20

Storage
-------
Ring-buffer log capped at 100 entries.
Atomic write: tmp + os.replace().
Default data file: <project_root>/data/governance_token_log.json
"""

from __future__ import annotations

import json
import math
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

class GovernanceTokenValueTracker:
    """Analyse governance token economics and classify value vs dilution.

    Parameters
    ----------
    data_dir : str, optional
        Directory for the JSON log file.  Defaults to ``<project_root>/data``.
    log_filename : str, optional
        Override the log file name.  Defaults to ``governance_token_log.json``.
    """

    _MAX_LOG = 100

    # Tier thresholds on holder_value_score (0–100 scale)
    _TIER_UNDERVALUED = 70.0
    _TIER_FAIR = 40.0
    _TIER_OVERVALUED = 20.0
    # Below _TIER_OVERVALUED → INFLATIONARY

    def __init__(
        self,
        data_dir: Optional[str] = None,
        log_filename: str = "governance_token_log.json",
    ) -> None:
        self._data_dir = data_dir or _default_data_dir()
        self._log_file = os.path.join(self._data_dir, log_filename)
        self._log: List[Dict[str, Any]] = self._load_log()
        self._last_result: Optional[Dict[str, Any]] = None

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
    def compute_market_cap(token_price_usd: float, circulating_supply: float) -> float:
        """Market cap = price × supply."""
        return float(token_price_usd) * float(circulating_supply)

    @staticmethod
    def compute_price_to_revenue(
        market_cap_usd: float, protocol_revenue_usd_annual: float
    ) -> float:
        """P/R ratio = market_cap / annual_revenue.

        Returns ``float('inf')`` when revenue is zero.
        """
        if protocol_revenue_usd_annual == 0.0:
            return float("inf")
        return market_cap_usd / protocol_revenue_usd_annual

    @staticmethod
    def compute_token_inflation_pct(
        emission_rate_tokens_per_day: float, circulating_supply: float
    ) -> float:
        """Annual token inflation as a percentage of circulating supply.

        token_inflation_pct = emission_rate * 365 / supply * 100

        Returns 0.0 if supply is zero.
        """
        if circulating_supply == 0.0:
            return 0.0
        return emission_rate_tokens_per_day * 365.0 / circulating_supply * 100.0

    @staticmethod
    def compute_holder_value_score(
        token_inflation_pct: float, price_to_revenue: float
    ) -> float:
        """Score in [0, 100] measuring how much value accrues to holders.

        score = 100 / (1 + inflation_fraction * price_to_revenue)
        where inflation_fraction = token_inflation_pct / 100

        Edge cases:
        - Infinite P/R (zero revenue) → score = 0 (no fundamental backing)
        - Denominator ≤ 0 (impossible in practice, guard) → 100
        """
        if math.isinf(price_to_revenue):
            return 0.0
        inflation_fraction = token_inflation_pct / 100.0
        denom = 1.0 + inflation_fraction * price_to_revenue
        if denom <= 0.0:
            return 100.0
        score = 100.0 / denom
        return min(100.0, max(0.0, score))

    @classmethod
    def compute_value_tier(cls, holder_value_score: float) -> str:
        """Classify the token into a value tier based on the holder value score."""
        if holder_value_score >= cls._TIER_UNDERVALUED:
            return "UNDERVALUED"
        elif holder_value_score >= cls._TIER_FAIR:
            return "FAIR"
        elif holder_value_score >= cls._TIER_OVERVALUED:
            return "OVERVALUED"
        else:
            return "INFLATIONARY"

    @staticmethod
    def compute_inflation_adjusted_yield(
        protocol_revenue_usd_annual: float,
        market_cap_usd: float,
        token_inflation_pct: float,
    ) -> float:
        """Earnings yield net of token inflation.

        inflation_adjusted_yield_pct =
            (protocol_revenue / market_cap * 100) - token_inflation_pct

        Returns 0.0 if market_cap is zero.
        """
        if market_cap_usd == 0.0:
            return 0.0
        earnings_yield_pct = protocol_revenue_usd_annual / market_cap_usd * 100.0
        return earnings_yield_pct - token_inflation_pct

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def track(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyse a governance token and append the result to the log.

        Parameters
        ----------
        token_data : dict
            Required keys:
            - ``protocol``                      (str)
            - ``token_price_usd``               (float)
            - ``circulating_supply``            (float)
            - ``protocol_revenue_usd_annual``   (float)
            - ``emission_rate_tokens_per_day``  (float)
            - ``token_holders``                 (int)

        Returns
        -------
        dict
            Full analysis record including all computed fields.
        """
        timestamp = _utc_now()

        protocol = token_data.get("protocol", "unknown")
        price = float(token_data.get("token_price_usd", 0.0))
        supply = float(token_data.get("circulating_supply", 0.0))
        revenue = float(token_data.get("protocol_revenue_usd_annual", 0.0))
        emission_rate = float(token_data.get("emission_rate_tokens_per_day", 0.0))
        holders = int(token_data.get("token_holders", 0))

        market_cap = self.compute_market_cap(price, supply)
        pr_ratio = self.compute_price_to_revenue(market_cap, revenue)
        inflation_pct = self.compute_token_inflation_pct(emission_rate, supply)
        hvs = self.compute_holder_value_score(inflation_pct, pr_ratio)
        tier = self.compute_value_tier(hvs)
        iay = self.compute_inflation_adjusted_yield(revenue, market_cap, inflation_pct)

        result: Dict[str, Any] = {
            "protocol": protocol,
            "token_price_usd": price,
            "circulating_supply": supply,
            "protocol_revenue_usd_annual": revenue,
            "emission_rate_tokens_per_day": emission_rate,
            "token_holders": holders,
            "market_cap_usd": round(market_cap, 2),
            "price_to_revenue": None if math.isinf(pr_ratio) else round(pr_ratio, 4),
            "token_inflation_pct": round(inflation_pct, 6),
            "holder_value_score": round(hvs, 6),
            "value_tier": tier,
            "inflation_adjusted_yield_pct": round(iay, 6),
            "timestamp": timestamp,
        }

        self._last_result = result
        self._log.append(result)
        self._save_log()

        return result

    def get_value_tier(self) -> Optional[str]:
        """Return the value tier from the most recent ``track()`` call.

        Returns ``None`` if ``track()`` has not been called yet.
        """
        if self._last_result is None:
            return None
        return self._last_result.get("value_tier")

    def get_inflation_adjusted_yield(self) -> Optional[float]:
        """Return the inflation-adjusted yield from the most recent ``track()`` call.

        Returns ``None`` if ``track()`` has not been called yet.
        """
        if self._last_result is None:
            return None
        return self._last_result.get("inflation_adjusted_yield_pct")

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def log_length(self) -> int:
        """Number of track entries currently in the in-memory log."""
        return len(self._log)

    def last_result(self) -> Optional[Dict[str, Any]]:
        """Raw result dict from the most recent track() call."""
        return self._last_result
