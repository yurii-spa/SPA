"""
MP-1002: DeFiProtocolSlippageImpactAnalyzer
Analyzes slippage impact on real yield from DeFi operations.
Pure stdlib, read-only analytics, atomic ring-buffer log.
"""

import json
import os
import time
from typing import Any, Dict, List


class DeFiProtocolSlippageImpactAnalyzer:
    """
    Analyzes the impact of slippage, spread, and MEV on DeFi trade profitability.
    """

    LOG_FILE = "data/slippage_impact_log.json"
    LOG_CAP = 100

    # Impact labels
    NEGLIGIBLE_IMPACT = "NEGLIGIBLE_IMPACT"
    LOW_IMPACT = "LOW_IMPACT"
    MODERATE_IMPACT = "MODERATE_IMPACT"
    HIGH_IMPACT = "HIGH_IMPACT"
    YIELD_DESTRUCTIVE = "YIELD_DESTRUCTIVE"

    # Flags
    FLAG_MEV_EXPOSURE = "MEV_EXPOSURE"
    FLAG_OVERSIZED_FOR_POOL = "OVERSIZED_FOR_POOL"
    FLAG_YIELD_NEGATIVE_NET = "YIELD_NEGATIVE_NET"
    FLAG_STABLE_POOL_EFFICIENT = "STABLE_POOL_EFFICIENT"
    FLAG_SLIPPAGE_EXCEEDS_ESTIMATE = "SLIPPAGE_EXCEEDS_ESTIMATE"
    FLAG_HIGH_SPREAD_MARKET = "HIGH_SPREAD_MARKET"

    def analyze(
        self,
        trades: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Analyzes slippage impact on trade profitability.

        Args:
            trades: List of trade dicts with slippage/cost fields.
            config: Configuration dict (optional overrides).

        Returns:
            dict with per-trade analysis and aggregates.
        """
        if not trades:
            return {
                "results": [],
                "aggregates": {
                    "lowest_impact": None,
                    "highest_impact": None,
                    "avg_efficiency_score": 0.0,
                    "yield_destructive_count": 0,
                    "negligible_count": 0,
                    "total_trades": 0,
                },
                "meta": {
                    "analyzer": "DeFiProtocolSlippageImpactAnalyzer",
                    "version": "1.0.0",
                },
            }

        results = []
        for trade in trades:
            result = self._analyze_trade(trade, config)
            results.append(result)

        aggregates = self._compute_aggregates(results)

        output = {
            "results": results,
            "aggregates": aggregates,
            "meta": {
                "analyzer": "DeFiProtocolSlippageImpactAnalyzer",
                "version": "1.0.0",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        }

        self._write_log(output)
        return output

    # ------------------------------------------------------------------
    # Per-trade analysis
    # ------------------------------------------------------------------

    def _analyze_trade(
        self, trade: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        name = trade.get("name", "unknown")
        protocol = trade.get("protocol", "unknown")
        pool_tvl_usd = float(trade.get("pool_tvl_usd", 0))
        trade_size_usd = float(trade.get("trade_size_usd", 0))
        pool_type = trade.get("pool_type", "v2_amm")
        bid_ask_spread_bps = float(trade.get("bid_ask_spread_bps", 0))
        actual_slippage_bps = float(trade.get("actual_slippage_bps", 0))
        mev_extracted_bps = float(trade.get("mev_extracted_bps", 0))
        position_hold_days = float(trade.get("position_hold_days", 1))
        expected_yield_pct_annual = float(trade.get("expected_yield_pct_annual", 0))

        # Size-to-liquidity ratio (%)
        if pool_tvl_usd > 0:
            size_to_liquidity_ratio = (trade_size_usd / pool_tvl_usd) * 100.0
        else:
            size_to_liquidity_ratio = 0.0

        # Expected price impact from pool dynamics (simple linear model)
        if "expected_price_impact_bps" in trade:
            expected_price_impact_bps = float(trade["expected_price_impact_bps"])
        else:
            expected_price_impact_bps = size_to_liquidity_ratio * 100.0  # 1% ratio ≈ 100 bps

        # Total cost (slippage + spread + mev)
        if "total_cost_bps" in trade:
            total_cost_bps = float(trade["total_cost_bps"])
        else:
            total_cost_bps = actual_slippage_bps + bid_ask_spread_bps + mev_extracted_bps

        # Dollar cost of slippage
        slippage_to_trade_ratio = (actual_slippage_bps / 10000.0) * trade_size_usd

        # Annual slippage drag (%)
        if position_hold_days > 0:
            annual_slippage_drag_pct = (
                (total_cost_bps / 10000.0) * (365.0 / position_hold_days) * 100.0
            )
        else:
            annual_slippage_drag_pct = 0.0

        # Yield net of costs
        yield_net_of_costs = expected_yield_pct_annual - annual_slippage_drag_pct

        # Efficiency score (0-100)
        if expected_yield_pct_annual > 0:
            efficiency_score = max(
                0.0,
                min(100.0, (yield_net_of_costs / expected_yield_pct_annual) * 100.0),
            )
        else:
            efficiency_score = 0.0

        # Impact label
        impact_label = self._compute_impact_label(
            total_cost_bps,
            size_to_liquidity_ratio,
            yield_net_of_costs,
            expected_yield_pct_annual,
            annual_slippage_drag_pct,
        )

        # Flags
        flags = self._compute_flags(
            mev_extracted_bps,
            size_to_liquidity_ratio,
            yield_net_of_costs,
            pool_type,
            total_cost_bps,
            actual_slippage_bps,
            expected_price_impact_bps,
            bid_ask_spread_bps,
        )

        return {
            "name": name,
            "protocol": protocol,
            "pool_type": pool_type,
            "trade_size_usd": trade_size_usd,
            "pool_tvl_usd": pool_tvl_usd,
            "size_to_liquidity_ratio": round(size_to_liquidity_ratio, 4),
            "bid_ask_spread_bps": bid_ask_spread_bps,
            "actual_slippage_bps": actual_slippage_bps,
            "expected_price_impact_bps": round(expected_price_impact_bps, 4),
            "mev_extracted_bps": mev_extracted_bps,
            "total_cost_bps": total_cost_bps,
            "slippage_to_trade_ratio": round(slippage_to_trade_ratio, 4),
            "annual_slippage_drag_pct": round(annual_slippage_drag_pct, 4),
            "expected_yield_pct_annual": expected_yield_pct_annual,
            "yield_net_of_costs": round(yield_net_of_costs, 4),
            "efficiency_score": round(efficiency_score, 2),
            "impact_label": impact_label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Label / flag helpers
    # ------------------------------------------------------------------

    def _compute_impact_label(
        self,
        total_cost_bps: float,
        size_to_liquidity_ratio: float,
        yield_net_of_costs: float,
        expected_yield_pct_annual: float,
        annual_slippage_drag_pct: float,
    ) -> str:
        # YIELD_DESTRUCTIVE: annual drag > yield (when yield >= 0)
        if (
            expected_yield_pct_annual >= 0
            and annual_slippage_drag_pct > expected_yield_pct_annual
        ):
            return self.YIELD_DESTRUCTIVE

        # HIGH_IMPACT: cost > 100 bps OR yield_net < 50% of gross
        if total_cost_bps > 100:
            return self.HIGH_IMPACT
        if (
            expected_yield_pct_annual > 0
            and yield_net_of_costs < 0.5 * expected_yield_pct_annual
        ):
            return self.HIGH_IMPACT

        # NEGLIGIBLE_IMPACT: cost < 10 bps AND size_ratio < 0.1%
        if total_cost_bps < 10 and size_to_liquidity_ratio < 0.1:
            return self.NEGLIGIBLE_IMPACT

        # LOW_IMPACT: cost < 30 bps AND size_ratio < 0.5%
        if total_cost_bps < 30 and size_to_liquidity_ratio < 0.5:
            return self.LOW_IMPACT

        return self.MODERATE_IMPACT

    def _compute_flags(
        self,
        mev_extracted_bps: float,
        size_to_liquidity_ratio: float,
        yield_net_of_costs: float,
        pool_type: str,
        total_cost_bps: float,
        actual_slippage_bps: float,
        expected_price_impact_bps: float,
        bid_ask_spread_bps: float,
    ) -> List[str]:
        flags: List[str] = []

        if mev_extracted_bps > 20:
            flags.append(self.FLAG_MEV_EXPOSURE)

        if size_to_liquidity_ratio > 2.0:
            flags.append(self.FLAG_OVERSIZED_FOR_POOL)

        if yield_net_of_costs < 0:
            flags.append(self.FLAG_YIELD_NEGATIVE_NET)

        if pool_type == "curve_stable" and total_cost_bps < 5:
            flags.append(self.FLAG_STABLE_POOL_EFFICIENT)

        if (
            expected_price_impact_bps > 0
            and actual_slippage_bps > expected_price_impact_bps * 1.5
        ):
            flags.append(self.FLAG_SLIPPAGE_EXCEEDS_ESTIMATE)

        if bid_ask_spread_bps > 50:
            flags.append(self.FLAG_HIGH_SPREAD_MARKET)

        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not results:
            return {
                "lowest_impact": None,
                "highest_impact": None,
                "avg_efficiency_score": 0.0,
                "yield_destructive_count": 0,
                "negligible_count": 0,
                "total_trades": 0,
            }

        sorted_by_eff = sorted(
            results, key=lambda r: r["efficiency_score"], reverse=True
        )
        lowest_impact = sorted_by_eff[0]["name"]
        highest_impact = sorted_by_eff[-1]["name"]

        avg_efficiency_score = sum(r["efficiency_score"] for r in results) / len(results)

        yield_destructive_count = sum(
            1 for r in results if r["impact_label"] == self.YIELD_DESTRUCTIVE
        )
        negligible_count = sum(
            1 for r in results if r["impact_label"] == self.NEGLIGIBLE_IMPACT
        )

        return {
            "lowest_impact": lowest_impact,
            "highest_impact": highest_impact,
            "avg_efficiency_score": round(avg_efficiency_score, 2),
            "yield_destructive_count": yield_destructive_count,
            "negligible_count": negligible_count,
            "total_trades": len(results),
        }

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def _write_log(self, output: Dict[str, Any]) -> None:
        """Atomic ring-buffer write to slippage_impact_log.json (cap 100)."""
        log_path = self.LOG_FILE
        dir_name = os.path.dirname(log_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        existing: List[Dict[str, Any]] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    existing = data
            except (json.JSONDecodeError, OSError):
                existing = []

        entry = {
            "timestamp": output["meta"].get("timestamp", ""),
            "total_trades": output["aggregates"]["total_trades"],
            "avg_efficiency_score": output["aggregates"]["avg_efficiency_score"],
            "yield_destructive_count": output["aggregates"]["yield_destructive_count"],
            "negligible_count": output["aggregates"]["negligible_count"],
        }
        existing.append(entry)

        if len(existing) > self.LOG_CAP:
            existing = existing[-self.LOG_CAP :]

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp_path, log_path)
