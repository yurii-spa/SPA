"""
MP-965: ProtocolYieldCurveArbitrageDetector
Detects arbitrage opportunities between different yield instruments.
Pure stdlib, atomic writes, read-only advisory module.
"""

import json
import os
import time


class ProtocolYieldCurveArbitrageDetector:
    """
    Detects yield curve arbitrage opportunities across DeFi protocols.

    Metrics:
      gross_spread_pct      = long_apy_pct - short_cost_pct
      gas_drag_pct          = execution_gas_usd / max_position_usd * 100
      net_spread_pct        = gross_spread_pct - slippage_est_pct - gas_drag_pct
      annualized_return_pct = net_spread_pct * (365 / holding_period_days)
      capital_efficiency_ratio = annualized_return_pct * (max_position_usd / collateral_required_usd)
      risk_adjusted_return_pct = net_spread_pct * (100 - counterparty_risk_score) / 100
    """

    LOG_CAP = 100

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def detect(self, opportunities: list, config: dict = None) -> dict:
        """
        Detect arbitrage opportunities from a list of opportunity dicts.

        Each opportunity dict fields:
          name, long_asset, long_apy_pct, short_asset, short_cost_pct,
          strategy_type (cash_and_carry/basis_trade/rate_arbitrage/curve_flattener),
          collateral_required_usd, max_position_usd, execution_gas_usd,
          slippage_est_pct, holding_period_days,
          refinancing_risk (bool), counterparty_risk_score (0-100)

        Returns dict with 'opportunities' list + 'aggregates' + metadata.
        """
        if config is None:
            config = {}

        results = [self._analyze_opportunity(o, config) for o in opportunities]
        aggregates = self._compute_aggregates(results)

        output = {
            "opportunities": results,
            "aggregates": aggregates,
            "opportunity_count": len(results),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        if config.get("write_log", False):
            data_dir = config.get("data_dir", "data")
            self._write_log(output, data_dir)

        return output

    # ------------------------------------------------------------------ #
    # Per-opportunity analysis
    # ------------------------------------------------------------------ #

    def _analyze_opportunity(self, opp: dict, config: dict) -> dict:
        name = opp.get("name", "unknown")
        long_asset = opp.get("long_asset", "unknown")
        long_apy_pct = float(opp.get("long_apy_pct", 0.0))
        short_asset = opp.get("short_asset", "unknown")
        short_cost_pct = float(opp.get("short_cost_pct", 0.0))
        strategy_type = opp.get("strategy_type", "cash_and_carry")
        collateral_required_usd = float(opp.get("collateral_required_usd", 0.0))
        max_position_usd = float(opp.get("max_position_usd", 0.0))
        execution_gas_usd = float(opp.get("execution_gas_usd", 0.0))
        slippage_est_pct = float(opp.get("slippage_est_pct", 0.0))
        holding_period_days = float(opp.get("holding_period_days", 30.0))
        refinancing_risk = bool(opp.get("refinancing_risk", False))
        counterparty_risk_score = float(opp.get("counterparty_risk_score", 50.0))

        # ── Spread metrics ────────────────────────────────────────────────
        gross_spread_pct = long_apy_pct - short_cost_pct

        # Gas drag as % of position (one-time cost as %)
        if max_position_usd > 0:
            gas_drag_pct = (execution_gas_usd / max_position_usd) * 100.0
        else:
            gas_drag_pct = 0.0

        net_spread_pct = gross_spread_pct - slippage_est_pct - gas_drag_pct

        # Annualize: net_spread is over holding_period_days, scale to 365 days
        period = max(holding_period_days, 1.0)
        annualized_return_pct = net_spread_pct * (365.0 / period)

        # Capital efficiency: return on collateral deployed
        if collateral_required_usd > 0:
            capital_efficiency_ratio = annualized_return_pct * (
                max_position_usd / collateral_required_usd
            )
        else:
            capital_efficiency_ratio = 0.0

        # Risk-adjusted return
        risk_adjusted_return_pct = net_spread_pct * (100.0 - counterparty_risk_score) / 100.0

        # ── Label & flags ─────────────────────────────────────────────────
        arb_label = self._compute_label(annualized_return_pct, counterparty_risk_score)
        flags = self._compute_flags(
            capital_efficiency_ratio,
            refinancing_risk,
            counterparty_risk_score,
            gas_drag_pct,
            gross_spread_pct,
            holding_period_days,
        )

        return {
            "name": name,
            "long_asset": long_asset,
            "long_apy_pct": long_apy_pct,
            "short_asset": short_asset,
            "short_cost_pct": short_cost_pct,
            "strategy_type": strategy_type,
            "collateral_required_usd": collateral_required_usd,
            "max_position_usd": max_position_usd,
            "execution_gas_usd": execution_gas_usd,
            "slippage_est_pct": slippage_est_pct,
            "holding_period_days": holding_period_days,
            "refinancing_risk": refinancing_risk,
            "counterparty_risk_score": counterparty_risk_score,
            "gross_spread_pct": round(gross_spread_pct, 4),
            "gas_drag_pct": round(gas_drag_pct, 4),
            "net_spread_pct": round(net_spread_pct, 4),
            "annualized_return_pct": round(annualized_return_pct, 4),
            "capital_efficiency_ratio": round(capital_efficiency_ratio, 4),
            "risk_adjusted_return_pct": round(risk_adjusted_return_pct, 4),
            "arb_label": arb_label,
            "flags": flags,
        }

    # ------------------------------------------------------------------ #
    # Label
    # ------------------------------------------------------------------ #

    def _compute_label(self, annualized_return_pct: float, counterparty_risk_score: float) -> str:
        """
        EXCEPTIONAL: >5% net annualized AND counterparty_risk_score < 50
        ATTRACTIVE:  >2% annualized
        MARGINAL:    >0% annualized
        UNECONOMICAL: -1% to 0%
        NEGATIVE:    < -1%
        """
        if annualized_return_pct > 5.0 and counterparty_risk_score < 50.0:
            return "EXCEPTIONAL"
        if annualized_return_pct > 2.0:
            return "ATTRACTIVE"
        if annualized_return_pct > 0.0:
            return "MARGINAL"
        if annualized_return_pct >= -1.0:
            return "UNECONOMICAL"
        return "NEGATIVE"

    # ------------------------------------------------------------------ #
    # Flags
    # ------------------------------------------------------------------ #

    def _compute_flags(
        self,
        capital_efficiency_ratio: float,
        refinancing_risk: bool,
        counterparty_risk_score: float,
        gas_drag_pct: float,
        gross_spread_pct: float,
        holding_period_days: float,
    ) -> list:
        flags = []

        # HIGH_CAPITAL_EFFICIENCY: >20% return on collateral
        if capital_efficiency_ratio > 20.0:
            flags.append("HIGH_CAPITAL_EFFICIENCY")

        # REFINANCING_RISK: refinancing_risk == True
        if refinancing_risk:
            flags.append("REFINANCING_RISK")

        # LOW_COUNTERPARTY_RISK: score < 30
        if counterparty_risk_score < 30.0:
            flags.append("LOW_COUNTERPARTY_RISK")

        # GAS_HEAVY: gas drag > 10% of gross spread
        if gross_spread_pct > 0 and gas_drag_pct > gross_spread_pct * 0.10:
            flags.append("GAS_HEAVY")

        # CLOSING_SOON: holding period < 7 days
        if holding_period_days < 7.0:
            flags.append("CLOSING_SOON")

        return flags

    # ------------------------------------------------------------------ #
    # Aggregates
    # ------------------------------------------------------------------ #

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "best_opportunity": None,
                "worst_opportunity": None,
                "total_deployable_usd": 0.0,
                "average_net_spread": None,
                "exceptional_count": 0,
            }

        best = max(results, key=lambda r: r["annualized_return_pct"])
        worst = min(results, key=lambda r: r["annualized_return_pct"])

        # Total deployable = sum of max_position_usd for EXCEPTIONAL + ATTRACTIVE
        total_deployable_usd = sum(
            r["max_position_usd"]
            for r in results
            if r["arb_label"] in ("EXCEPTIONAL", "ATTRACTIVE")
        )

        avg_net_spread = sum(r["net_spread_pct"] for r in results) / len(results)
        exceptional_count = sum(1 for r in results if r["arb_label"] == "EXCEPTIONAL")

        return {
            "best_opportunity": {
                "name": best["name"],
                "annualized_return_pct": best["annualized_return_pct"],
                "arb_label": best["arb_label"],
            },
            "worst_opportunity": {
                "name": worst["name"],
                "annualized_return_pct": worst["annualized_return_pct"],
                "arb_label": worst["arb_label"],
            },
            "total_deployable_usd": round(total_deployable_usd, 2),
            "average_net_spread": round(avg_net_spread, 4),
            "exceptional_count": exceptional_count,
        }

    # ------------------------------------------------------------------ #
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------ #

    def _write_log(self, result: dict, data_dir: str = "data") -> None:
        os.makedirs(data_dir, exist_ok=True)
        log_path = os.path.join(data_dir, "yield_curve_arb_log.json")

        try:
            with open(log_path, "r") as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        agg = result.get("aggregates", {})
        entry = {
            "timestamp": result.get("timestamp", ""),
            "opportunity_count": result.get("opportunity_count", 0),
            "exceptional_count": agg.get("exceptional_count", 0),
            "average_net_spread": agg.get("average_net_spread"),
            "total_deployable_usd": agg.get("total_deployable_usd", 0.0),
        }
        log.append(entry)

        # Ring-buffer cap
        if len(log) > self.LOG_CAP:
            log = log[-self.LOG_CAP :]

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp_path, log_path)
