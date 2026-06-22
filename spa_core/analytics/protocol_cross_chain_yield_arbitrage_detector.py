"""
MP-939: ProtocolCrossChainYieldArbitrageDetector
Detects arbitrage opportunities between yields on different chains.
Pure stdlib, read-only/advisory, atomic ring-buffer log.
"""
import json
import os
from datetime import datetime, timezone
from spa_core.utils.atomic import atomic_save

LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "cross_chain_arbitrage_log.json"
)
LOG_CAP = 100

_OPPORTUNITY_THRESHOLDS = [
    (5.0,  "EXCEPTIONAL"),
    (2.0,  "GOOD"),
    (0.5,  "MARGINAL"),
    (0.0,  "UNPROFITABLE"),
]

COMPLEXITY_LEVELS = ("simple", "medium", "complex")


class ProtocolCrossChainYieldArbitrageDetector:
    """Detect cross-chain yield arbitrage opportunities and score their attractiveness."""

    # ---------- public API ----------

    def detect(self, opportunities: list, config: dict) -> dict:
        """
        Parameters
        ----------
        opportunities : list[dict]
            Each entry describes a potential cross-chain yield move.
        config : dict
            Tuning parameters (see defaults).

        Returns
        -------
        dict with keys:
            opportunities, aggregates, timestamp, config_used
        """
        if not isinstance(opportunities, list):
            raise TypeError("opportunities must be a list")
        if not isinstance(config, dict):
            raise TypeError("config must be a dict")

        cfg = self._resolve_config(config)
        results = [self._score_opportunity(o, cfg) for o in opportunities]

        aggregates = self._compute_aggregates(results)
        output = {
            "opportunities": results,
            "aggregates": aggregates,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config_used": cfg,
        }
        self._append_log(output)
        return output

    # ---------- config ----------

    def _resolve_config(self, config: dict) -> dict:
        return {
            "high_bridge_risk_threshold": float(config.get("high_bridge_risk_threshold", 60.0)),
            "fast_execution_hours": float(config.get("fast_execution_hours", 1.0)),
            "large_position_usd": float(config.get("large_position_usd", 100_000.0)),
            "gas_heavy_pct_of_profit": float(config.get("gas_heavy_pct_of_profit", 1.0)),
            "short_breakeven_days": float(config.get("short_breakeven_days", 7.0)),
            "days_per_year": float(config.get("days_per_year", 365.0)),
        }

    # ---------- per-opportunity scoring ----------

    def _score_opportunity(self, o: dict, cfg: dict) -> dict:
        protocol = str(o.get("protocol", ""))
        asset = str(o.get("asset", ""))
        source_chain = str(o.get("source_chain", ""))
        source_apy = float(o.get("source_apy_pct", 0.0))
        dest_chain = str(o.get("dest_chain", ""))
        dest_apy = float(o.get("dest_apy_pct", 0.0))
        bridge_fee = float(o.get("bridge_fee_pct", 0.0))
        bridge_hours = float(o.get("bridge_time_hours", 0.0))
        gas_cost_usd = float(o.get("gas_cost_usd", 0.0))
        position_size = float(o.get("position_size_usd", 1.0))
        bridge_risk = float(o.get("bridge_risk_score", 0.0))
        complexity = str(o.get("execution_complexity", "simple"))

        # -- spreads --
        gross_spread_pct = dest_apy - source_apy
        net_spread_pct = gross_spread_pct - bridge_fee

        # -- annualised profit (on position, after net spread) --
        days = cfg["days_per_year"]
        annualized_profit_usd = (net_spread_pct / 100.0) * position_size

        # -- break-even days --
        if net_spread_pct > 0 and position_size > 0:
            daily_profit_usd = annualized_profit_usd / days
            break_even_days = gas_cost_usd / daily_profit_usd if daily_profit_usd > 0 else float("inf")
        else:
            break_even_days = float("inf")

        # -- risk-adjusted spread --
        risk_adjusted_spread = gross_spread_pct * (1.0 - bridge_risk / 100.0)

        # -- label --
        label = self._opportunity_label(net_spread_pct)

        # -- flags --
        flags = self._compute_flags(o, cfg, bridge_risk, bridge_hours, position_size,
                                    gas_cost_usd, annualized_profit_usd, break_even_days)

        return {
            "protocol": protocol,
            "asset": asset,
            "source_chain": source_chain,
            "source_apy_pct": source_apy,
            "dest_chain": dest_chain,
            "dest_apy_pct": dest_apy,
            "bridge_fee_pct": bridge_fee,
            "bridge_time_hours": bridge_hours,
            "gas_cost_usd": gas_cost_usd,
            "position_size_usd": position_size,
            "bridge_risk_score": bridge_risk,
            "execution_complexity": complexity,
            "gross_spread_pct": round(gross_spread_pct, 6),
            "net_spread_pct": round(net_spread_pct, 6),
            "break_even_days": round(break_even_days, 4) if break_even_days != float("inf") else None,
            "annualized_profit_usd": round(annualized_profit_usd, 4),
            "risk_adjusted_spread": round(risk_adjusted_spread, 6),
            "opportunity_label": label,
            "flags": flags,
        }

    # ---------- label ----------

    def _opportunity_label(self, net_spread_pct: float) -> str:
        if net_spread_pct < 0:
            return "NEGATIVE"
        for threshold, label in _OPPORTUNITY_THRESHOLDS:
            if net_spread_pct >= threshold:
                return label
        return "NEGATIVE"

    # ---------- flags ----------

    def _compute_flags(self, o: dict, cfg: dict, bridge_risk: float,
                       bridge_hours: float, position_size: float,
                       gas_cost_usd: float, annualized_profit_usd: float,
                       break_even_days: float) -> list:
        flags = []

        if bridge_risk > cfg["high_bridge_risk_threshold"]:
            flags.append("HIGH_BRIDGE_RISK")

        if bridge_hours < cfg["fast_execution_hours"]:
            flags.append("FAST_EXECUTION")

        if position_size > cfg["large_position_usd"]:
            flags.append("LARGE_POSITION")

        # GAS_HEAVY: gas cost > X% of annualised profit
        if annualized_profit_usd > 0:
            gas_pct = (gas_cost_usd / annualized_profit_usd) * 100.0
            if gas_pct > cfg["gas_heavy_pct_of_profit"]:
                flags.append("GAS_HEAVY")
        elif gas_cost_usd > 0:
            flags.append("GAS_HEAVY")

        if break_even_days is not None and break_even_days < cfg["short_breakeven_days"]:
            flags.append("SHORT_BREAKEVEN")

        return flags

    # ---------- aggregates ----------

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "best_opportunity": None,
                "worst_opportunity": None,
                "total_opportunities": 0,
                "profitable_count": 0,
                "average_net_spread": None,
            }

        profitable = [r for r in results if r["net_spread_pct"] > 0]
        sorted_by_net = sorted(results, key=lambda x: x["net_spread_pct"], reverse=True)

        avg_net = sum(r["net_spread_pct"] for r in results) / len(results)

        best = sorted_by_net[0]
        worst = sorted_by_net[-1]

        return {
            "best_opportunity": f"{best['protocol']} {best['source_chain']}→{best['dest_chain']}",
            "worst_opportunity": f"{worst['protocol']} {worst['source_chain']}→{worst['dest_chain']}",
            "total_opportunities": len(results),
            "profitable_count": len(profitable),
            "average_net_spread": round(avg_net, 6),
        }

    # ---------- ring-buffer log ----------

    def _append_log(self, entry: dict) -> None:
        log_entry = {
            "ts": entry["timestamp"],
            "total_opportunities": entry["aggregates"].get("total_opportunities", 0),
            "profitable_count": entry["aggregates"].get("profitable_count", 0),
            "best_opportunity": entry["aggregates"].get("best_opportunity"),
            "average_net_spread": entry["aggregates"].get("average_net_spread"),
        }
        try:
            log_path = LOG_PATH
            if os.path.exists(log_path):
                with open(log_path, "r") as f:
                    buf = json.load(f)
                if not isinstance(buf, list):
                    buf = []
            else:
                buf = []
            buf.append(log_entry)
            if len(buf) > LOG_CAP:
                buf = buf[-LOG_CAP:]
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            atomic_save(buf, str(log_path))
        except Exception:
            pass


# ---------- CLI ----------

if __name__ == "__main__":
    sample = [
        {
            "protocol": "Aave",
            "asset": "USDC",
            "source_chain": "Ethereum",
            "source_apy_pct": 3.5,
            "dest_chain": "Arbitrum",
            "dest_apy_pct": 8.2,
            "bridge_fee_pct": 0.05,
            "bridge_time_hours": 0.5,
            "gas_cost_usd": 25.0,
            "position_size_usd": 50_000.0,
            "bridge_risk_score": 25.0,
            "execution_complexity": "simple",
        },
    ]
    import json
    detector = ProtocolCrossChainYieldArbitrageDetector()
    result = detector.detect(sample, {})
    print(json.dumps(result, indent=2))
