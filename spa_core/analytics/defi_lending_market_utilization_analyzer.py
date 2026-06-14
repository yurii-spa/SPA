"""
MP-964: DeFiLendingMarketUtilizationAnalyzer
Analyzes utilization rates of DeFi lending markets and their impact on APY.
Uses kink/jump-rate interest rate model (Compound-style).
Pure stdlib, atomic writes, read-only advisory module.
"""

import json
import os
import time
from typing import Any


class DeFiLendingMarketUtilizationAnalyzer:
    """
    Analyzes utilization rate of DeFi lending markets and its impact on APY.

    Kink model (jump-rate):
      borrow_apy = base + (u/kink)*slope1             if u <= kink
      borrow_apy = base + slope1 + ((u-kink)/(100-kink))*slope2  if u > kink
      supply_apy = borrow_apy * (u/100) * (1 - reserve_factor/100)
    """

    LOG_CAP = 100

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def analyze(self, markets: list, config: dict = None) -> dict:
        """
        Analyze a list of lending markets.

        Each market dict fields:
          protocol, asset,
          total_supply_usd, total_borrow_usd,
          base_rate_pct, slope1_pct, slope2_pct,
          kink_utilization_pct, reserve_factor_pct,
          current_supply_apy_pct, current_borrow_apy_pct,
          liquidation_threshold_pct, close_factor_pct

        Returns dict with 'markets' list + 'aggregates' + metadata.
        """
        if config is None:
            config = {}

        results = [self._analyze_market(m, config) for m in markets]
        aggregates = self._compute_aggregates(results)

        output = {
            "markets": results,
            "aggregates": aggregates,
            "market_count": len(results),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        if config.get("write_log", False):
            data_dir = config.get("data_dir", "data")
            self._write_log(output, data_dir)

        return output

    # ------------------------------------------------------------------ #
    # Per-market analysis
    # ------------------------------------------------------------------ #

    def _analyze_market(self, market: dict, config: dict) -> dict:
        protocol = market.get("protocol", "unknown")
        asset = market.get("asset", "unknown")
        total_supply_usd = float(market.get("total_supply_usd", 0.0))
        total_borrow_usd = float(market.get("total_borrow_usd", 0.0))
        base_rate_pct = float(market.get("base_rate_pct", 0.0))
        slope1_pct = float(market.get("slope1_pct", 4.0))
        slope2_pct = float(market.get("slope2_pct", 60.0))
        kink_utilization_pct = float(market.get("kink_utilization_pct", 80.0))
        reserve_factor_pct = float(market.get("reserve_factor_pct", 10.0))
        liquidation_threshold_pct = float(market.get("liquidation_threshold_pct", 80.0))
        close_factor_pct = float(market.get("close_factor_pct", 50.0))
        current_supply_apy_pct = float(market.get("current_supply_apy_pct", 0.0))
        current_borrow_apy_pct = float(market.get("current_borrow_apy_pct", 0.0))

        # ── Utilization rate ──────────────────────────────────────────────
        if total_supply_usd > 0:
            utilization_rate_pct = (total_borrow_usd / total_supply_usd) * 100.0
        else:
            utilization_rate_pct = 0.0

        # ── Model APYs ────────────────────────────────────────────────────
        borrow_apy_from_model_pct = self._compute_borrow_apy(
            utilization_rate_pct, base_rate_pct, slope1_pct, slope2_pct, kink_utilization_pct
        )

        util_fraction = min(utilization_rate_pct, 100.0) / 100.0
        reserve_fraction = reserve_factor_pct / 100.0
        supply_apy_from_model_pct = (
            borrow_apy_from_model_pct * util_fraction * (1.0 - reserve_fraction)
        )

        # ── Derived metrics ───────────────────────────────────────────────
        spread_pct = borrow_apy_from_model_pct - supply_apy_from_model_pct
        distance_to_kink_pct = kink_utilization_pct - utilization_rate_pct
        distance_to_full_pct = 100.0 - utilization_rate_pct

        # ── Label & flags ─────────────────────────────────────────────────
        utilization_label = self._compute_label(utilization_rate_pct, kink_utilization_pct)
        flags = self._compute_flags(utilization_rate_pct, kink_utilization_pct, spread_pct)

        return {
            "protocol": protocol,
            "asset": asset,
            "total_supply_usd": total_supply_usd,
            "total_borrow_usd": total_borrow_usd,
            "utilization_rate_pct": round(utilization_rate_pct, 4),
            "borrow_apy_from_model_pct": round(borrow_apy_from_model_pct, 4),
            "supply_apy_from_model_pct": round(supply_apy_from_model_pct, 4),
            "spread_pct": round(spread_pct, 4),
            "distance_to_kink_pct": round(distance_to_kink_pct, 4),
            "distance_to_full_pct": round(distance_to_full_pct, 4),
            "utilization_label": utilization_label,
            "flags": flags,
            "kink_utilization_pct": kink_utilization_pct,
            "reserve_factor_pct": reserve_factor_pct,
            "liquidation_threshold_pct": liquidation_threshold_pct,
            "close_factor_pct": close_factor_pct,
            "current_supply_apy_pct": current_supply_apy_pct,
            "current_borrow_apy_pct": current_borrow_apy_pct,
        }

    # ------------------------------------------------------------------ #
    # Interest rate model
    # ------------------------------------------------------------------ #

    def _compute_borrow_apy(
        self,
        util: float,
        base_rate: float,
        slope1: float,
        slope2: float,
        kink: float,
    ) -> float:
        """Kink (jump-rate) interest rate model."""
        if util <= kink:
            if kink > 0:
                return base_rate + (util / kink) * slope1
            return base_rate
        else:
            excess = util - kink
            remaining = 100.0 - kink
            if remaining > 0:
                return base_rate + slope1 + (excess / remaining) * slope2
            return base_rate + slope1 + slope2

    # ------------------------------------------------------------------ #
    # Label
    # ------------------------------------------------------------------ #

    def _compute_label(self, util: float, kink: float) -> str:
        """
        Priority order (highest to lowest):
          OVERUTILIZED > SATURATED > OPTIMAL > HIGH > EMPTY > LOW
        OPTIMAL = within kink ± 10 pp (only when util ≤ 90 and > 0)
        """
        if util > 100.0:
            return "OVERUTILIZED"
        if util > 90.0:
            return "SATURATED"
        if abs(util - kink) <= 10.0:
            return "OPTIMAL"
        if util > kink + 10.0:
            return "HIGH"
        if util < 10.0:
            return "EMPTY"
        return "LOW"

    # ------------------------------------------------------------------ #
    # Flags
    # ------------------------------------------------------------------ #

    def _compute_flags(self, util: float, kink: float, spread: float) -> list:
        flags = []
        # AT_KINK: within 5 pp of kink
        if abs(util - kink) <= 5.0:
            flags.append("AT_KINK")
        # RATE_SPIKE_IMMINENT: util > 95% of kink value
        if kink > 0 and util > kink * 0.95:
            flags.append("RATE_SPIKE_IMMINENT")
        # SUPPLY_INCENTIVE_NEEDED: util > 80%
        if util > 80.0:
            flags.append("SUPPLY_INCENTIVE_NEEDED")
        # LIQUIDATION_RISK_HIGH: util > 90%
        if util > 90.0:
            flags.append("LIQUIDATION_RISK_HIGH")
        # HEALTHY_SPREAD: borrow-supply spread between 2% and 8%
        if 2.0 <= spread <= 8.0:
            flags.append("HEALTHY_SPREAD")
        return flags

    # ------------------------------------------------------------------ #
    # Aggregates
    # ------------------------------------------------------------------ #

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "highest_utilization": None,
                "lowest_utilization": None,
                "average_utilization": None,
                "saturated_count": 0,
                "optimal_count": 0,
            }

        highest = max(results, key=lambda r: r["utilization_rate_pct"])
        lowest = min(results, key=lambda r: r["utilization_rate_pct"])
        avg = sum(r["utilization_rate_pct"] for r in results) / len(results)

        saturated_count = sum(
            1 for r in results if r["utilization_label"] in ("SATURATED", "OVERUTILIZED")
        )
        optimal_count = sum(
            1 for r in results if r["utilization_label"] == "OPTIMAL"
        )

        return {
            "highest_utilization": {
                "protocol": highest["protocol"],
                "asset": highest["asset"],
                "utilization_rate_pct": highest["utilization_rate_pct"],
            },
            "lowest_utilization": {
                "protocol": lowest["protocol"],
                "asset": lowest["asset"],
                "utilization_rate_pct": lowest["utilization_rate_pct"],
            },
            "average_utilization": round(avg, 4),
            "saturated_count": saturated_count,
            "optimal_count": optimal_count,
        }

    # ------------------------------------------------------------------ #
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------ #

    def _write_log(self, result: dict, data_dir: str = "data") -> None:
        os.makedirs(data_dir, exist_ok=True)
        log_path = os.path.join(data_dir, "lending_utilization_log.json")

        try:
            with open(log_path, "r") as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        entry = {
            "timestamp": result.get("timestamp", ""),
            "market_count": result.get("market_count", 0),
            "average_utilization": result.get("aggregates", {}).get("average_utilization"),
            "saturated_count": result.get("aggregates", {}).get("saturated_count", 0),
            "optimal_count": result.get("aggregates", {}).get("optimal_count", 0),
        }
        log.append(entry)

        # Ring-buffer cap
        if len(log) > self.LOG_CAP:
            log = log[-self.LOG_CAP :]

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp_path, log_path)
