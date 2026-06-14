"""
MP-914: DeFiLendingHealthMonitor
Monitors health of DeFi lending markets.
Pure stdlib only. Advisory/read-only. Atomic writes.
"""

import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/lending_health_log.json")
MAX_ENTRIES = 100


class DeFiLendingHealthMonitor:
    """
    Monitors health of DeFi lending markets.
    Each market dict must have:
        protocol, asset, total_supplied_usd, total_borrowed_usd,
        utilization_rate_pct, supply_apy_pct, borrow_apy_pct,
        liquidation_threshold_pct, bad_debt_usd, reserve_factor_pct,
        oracle_price_usd
    """

    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = Path(data_file)

    # ------------------------------------------------------------------
    # Internal calculations
    # ------------------------------------------------------------------

    def _compute_net_spread_pct(self, market: dict) -> float:
        return round(
            market.get("borrow_apy_pct", 0.0) - market.get("supply_apy_pct", 0.0),
            4,
        )

    def _compute_bad_debt_ratio_pct(self, market: dict) -> float:
        total_supplied = market.get("total_supplied_usd", 0.0)
        bad_debt = market.get("bad_debt_usd", 0.0)
        if total_supplied <= 0:
            return 0.0
        return round(bad_debt / total_supplied * 100.0, 4)

    def _compute_health_index(self, market: dict) -> float:
        """Health index 0-100 (higher = healthier)."""
        util = market.get("utilization_rate_pct", 0.0)
        total_supplied = market.get("total_supplied_usd", 0.0)
        bad_debt = market.get("bad_debt_usd", 0.0)
        supply_apy = market.get("supply_apy_pct", 0.0)
        borrow_apy = market.get("borrow_apy_pct", 0.0)
        reserve_factor = market.get("reserve_factor_pct", 0.0)

        # Utilization: 0% → 100, 100% → 0
        util_score = max(0.0, min(100.0, (1.0 - util / 100.0) * 100.0))

        # Bad debt: 0 ratio → 100, 1%+ ratio → 0
        bad_debt_ratio = bad_debt / max(total_supplied, 1.0)
        bad_debt_score = max(0.0, min(100.0, (1.0 - bad_debt_ratio * 100.0) * 100.0))

        # Spread: positive spread → healthy; capped at 5% spread = full score
        spread = borrow_apy - supply_apy
        # spread 5% → 100, spread 0 → 50, spread -5% → 0
        spread_score = max(0.0, min(100.0, spread * 10.0 + 50.0))

        # Reserve factor: 20%+ → 100, 0% → 0
        reserve_score = max(0.0, min(100.0, reserve_factor * 5.0))

        health_index = (
            util_score * 0.40
            + bad_debt_score * 0.30
            + spread_score * 0.20
            + reserve_score * 0.10
        )
        return round(max(0.0, min(100.0, health_index)), 2)

    def _get_health_label(self, health_index: float) -> str:
        if health_index >= 80:
            return "EXCELLENT"
        elif health_index >= 60:
            return "HEALTHY"
        elif health_index >= 40:
            return "FAIR"
        elif health_index >= 20:
            return "STRESSED"
        else:
            return "CRITICAL"

    def _compute_flags(self, market: dict) -> list:
        flags = []
        util = market.get("utilization_rate_pct", 0.0)
        bad_debt = market.get("bad_debt_usd", 0.0)
        supply_apy = market.get("supply_apy_pct", 0.0)
        borrow_apy = market.get("borrow_apy_pct", 0.0)
        reserve_factor = market.get("reserve_factor_pct", 0.0)

        if util > 85:
            flags.append("HIGH_UTILIZATION")
        if bad_debt > 0:
            flags.append("BAD_DEBT_PRESENT")
        if supply_apy > borrow_apy:
            flags.append("INVERTED_SPREAD")
        if util > 95:
            flags.append("NEAR_MAX_UTIL")
        if reserve_factor < 5:
            flags.append("LOW_RESERVES")
        return flags

    def _analyze_market(self, market: dict) -> dict:
        net_spread_pct = self._compute_net_spread_pct(market)
        bad_debt_ratio_pct = self._compute_bad_debt_ratio_pct(market)
        health_index = self._compute_health_index(market)
        health_label = self._get_health_label(health_index)
        flags = self._compute_flags(market)

        return {
            "protocol": market.get("protocol", ""),
            "asset": market.get("asset", ""),
            "total_supplied_usd": market.get("total_supplied_usd", 0.0),
            "total_borrowed_usd": market.get("total_borrowed_usd", 0.0),
            "utilization_rate_pct": market.get("utilization_rate_pct", 0.0),
            "supply_apy_pct": market.get("supply_apy_pct", 0.0),
            "borrow_apy_pct": market.get("borrow_apy_pct", 0.0),
            "liquidation_threshold_pct": market.get("liquidation_threshold_pct", 0.0),
            "bad_debt_usd": market.get("bad_debt_usd", 0.0),
            "reserve_factor_pct": market.get("reserve_factor_pct", 0.0),
            "oracle_price_usd": market.get("oracle_price_usd", 0.0),
            "net_spread_pct": net_spread_pct,
            "bad_debt_ratio_pct": bad_debt_ratio_pct,
            "health_index": health_index,
            "health_label": health_label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def monitor(self, markets: list, config: dict) -> dict:
        """
        Monitor lending markets and return health analysis.

        Returns dict with:
            timestamp, market_count, markets (list of analyzed),
            aggregates: { healthiest_market, most_stressed,
                          total_bad_debt_usd, average_utilization,
                          critical_count }
        """
        if not markets:
            return {
                "timestamp": time.time(),
                "market_count": 0,
                "markets": [],
                "aggregates": {
                    "healthiest_market": None,
                    "most_stressed": None,
                    "total_bad_debt_usd": 0.0,
                    "average_utilization": 0.0,
                    "critical_count": 0,
                },
            }

        analyzed = [self._analyze_market(m) for m in markets]

        sorted_by_health = sorted(analyzed, key=lambda x: x["health_index"], reverse=True)
        healthiest = (
            sorted_by_health[0]["protocol"] + "/" + sorted_by_health[0]["asset"]
        )
        most_stressed = (
            sorted_by_health[-1]["protocol"] + "/" + sorted_by_health[-1]["asset"]
        )

        total_bad_debt = sum(m["bad_debt_usd"] for m in analyzed)
        avg_util = sum(m["utilization_rate_pct"] for m in analyzed) / len(analyzed)
        critical_count = sum(1 for m in analyzed if m["health_label"] == "CRITICAL")

        result = {
            "timestamp": time.time(),
            "market_count": len(analyzed),
            "markets": analyzed,
            "aggregates": {
                "healthiest_market": healthiest,
                "most_stressed": most_stressed,
                "total_bad_debt_usd": round(total_bad_debt, 2),
                "average_utilization": round(avg_util, 2),
                "critical_count": critical_count,
            },
        }

        self._append_log(result)
        return result

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def _append_log(self, result: dict) -> None:
        log_entry = {
            "timestamp": result["timestamp"],
            "market_count": result["market_count"],
            "aggregates": result["aggregates"],
        }
        try:
            if self.data_file.exists():
                with open(self.data_file) as f:
                    log = json.load(f)
            else:
                log = []
        except (json.JSONDecodeError, OSError):
            log = []

        log.append(log_entry)
        if len(log) > MAX_ENTRIES:
            log = log[-MAX_ENTRIES:]

        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(self.data_file) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp, str(self.data_file))
