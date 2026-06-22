"""
MP-980: DeFiCrossProtocolYieldOptimizer
Optimizes capital allocation across DeFi yield protocols for maximum risk-adjusted APY.
Stdlib only. Atomic ring-buffer log (cap 100).
"""

import json
import os
import time


class DeFiCrossProtocolYieldOptimizer:
    """
    Analyzes DeFi yield opportunities and computes optimized capital allocation.

    Input per opportunity:
      protocol, asset, apy_pct, min_deposit_usd, max_deposit_usd,
      gas_entry_usd, gas_exit_usd, lock_period_days, withdrawal_notice_hours,
      risk_score (0-100), correlation_with_others {protocol: coeff},
      capacity_remaining_usd

    Computed per opportunity:
      annualized_gas_drag_pct, net_apy_pct, risk_adjusted_net_apy,
      min_viable_capital_usd, efficient_allocation_pct, label, flags

    Labels:
      MUST_ALLOCATE  risk_adj > 15%
      RECOMMENDED    risk_adj 8-15%
      CONSIDER       risk_adj 3-8%
      LOW_PRIORITY   risk_adj 1-3%
      SKIP           risk_adj < 1% or GAS_TRAP

    Flags:
      GAS_TRAP              annualized_gas_drag > 50% of apy
      CAPITAL_EFFICIENT     min_viable_capital < 1000
      HIGH_CAPACITY         capacity_remaining > 1 000 000
      LOW_LOCK              lock_period_days < 7
      DIVERSIFICATION_BENEFIT  avg |correlation| < 0.3
    """

    LOG_PATH = "data/cross_protocol_optimizer_log.json"
    LOG_CAP = 100

    # ------------------------------------------------------------------ public

    def optimize(self, opportunities: list, config: dict) -> dict:
        """
        Analyse opportunities and return ranked allocation recommendations.

        config keys (all optional):
          total_capital_usd    default 100 000
          position_hold_days   default 365
          log_path             override log file path
        """
        if not opportunities:
            return self._empty_result(config)

        total_capital = float(config.get("total_capital_usd", 100_000.0))
        hold_days = max(int(config.get("position_hold_days", 365)), 1)

        analyzed = [
            self._analyze(opp, total_capital, hold_days)
            for opp in opportunities
        ]

        self._normalize_weights(analyzed)
        aggregates = self._compute_aggregates(analyzed)

        result = {
            "opportunities": analyzed,
            "top_opportunity": aggregates["top_opportunity"],
            "top_opportunity_risk_adj_apy": aggregates["top_opportunity_risk_adj_apy"],
            "worst_opportunity": aggregates["worst_opportunity"],
            "worst_opportunity_risk_adj_apy": aggregates["worst_opportunity_risk_adj_apy"],
            "recommended_allocation_summary": aggregates["recommended_allocation_summary"],
            "total_available_capacity_usd": aggregates["total_available_capacity_usd"],
            "must_allocate_count": aggregates["must_allocate_count"],
            "config_used": {
                "total_capital_usd": total_capital,
                "position_hold_days": hold_days,
            },
        }

        log_path = config.get("log_path", self.LOG_PATH)
        self._append_log(result, log_path)
        return result

    # ----------------------------------------------------------------- private

    def _analyze(self, opp: dict, total_capital: float, hold_days: int) -> dict:
        protocol = str(opp.get("protocol", "unknown"))
        asset = str(opp.get("asset", "unknown"))
        apy_pct = float(opp.get("apy_pct", 0.0))
        min_dep = float(opp.get("min_deposit_usd", 0.0))
        max_dep = float(opp.get("max_deposit_usd", total_capital))
        gas_in = float(opp.get("gas_entry_usd", 0.0))
        gas_out = float(opp.get("gas_exit_usd", 0.0))
        lock_days = float(opp.get("lock_period_days", 0.0))
        withdrawal_notice = float(opp.get("withdrawal_notice_hours", 0.0))
        risk_score = float(opp.get("risk_score", 50.0))
        correlations = opp.get("correlation_with_others", {}) or {}
        capacity = float(opp.get("capacity_remaining_usd", 1_000_000.0))

        # Representative position size for gas-drag calculation
        ref_position = max(min_dep, min(total_capital * 0.1, max_dep, capacity))
        if ref_position <= 0:
            ref_position = max(total_capital * 0.1, 1.0)

        total_gas = gas_in + gas_out

        # Annualized gas drag (%): round-trip gas amortized over hold_days, scaled to 1 year
        annualized_gas_drag_pct = (total_gas / ref_position * 100.0) * (365.0 / hold_days)

        net_apy_pct = apy_pct - annualized_gas_drag_pct

        risk_factor = (100.0 - max(0.0, min(100.0, risk_score))) / 100.0
        risk_adjusted_net_apy = net_apy_pct * risk_factor

        # Min viable capital: position size where annualized gas drag < 1% of APY
        # (total_gas / pos) * (365/hold_days) * 100 = 0.01 * apy_pct
        # → pos = total_gas * (365/hold_days) * 100 / (0.01 * apy_pct)
        if apy_pct > 0 and total_gas > 0:
            min_viable_capital = (total_gas * (365.0 / hold_days) * 100.0) / (0.01 * apy_pct)
        elif total_gas == 0:
            min_viable_capital = 0.0
        else:
            min_viable_capital = None  # zero APY, gas cost exists → no viable size

        # Inverse-risk weight (for MVO-simplified normalization)
        inv_risk = 1.0 / max(risk_score, 0.01)

        # Flags
        flags = []

        is_gas_trap = (apy_pct > 0 and annualized_gas_drag_pct > 0.5 * apy_pct) or (
            apy_pct == 0 and total_gas > 0
        )
        if is_gas_trap:
            flags.append("GAS_TRAP")

        if min_viable_capital is not None and min_viable_capital < 1000.0:
            flags.append("CAPITAL_EFFICIENT")

        if capacity > 1_000_000.0:
            flags.append("HIGH_CAPACITY")

        if lock_days < 7.0:
            flags.append("LOW_LOCK")

        if correlations:
            avg_corr = sum(abs(float(v)) for v in correlations.values()) / len(correlations)
        else:
            avg_corr = 0.0  # no data → assume uncorrelated
        if avg_corr < 0.3:
            flags.append("DIVERSIFICATION_BENEFIT")

        # Label
        if is_gas_trap or risk_adjusted_net_apy < 1.0:
            label = "SKIP"
        elif risk_adjusted_net_apy >= 15.0:
            label = "MUST_ALLOCATE"
        elif risk_adjusted_net_apy >= 8.0:
            label = "RECOMMENDED"
        elif risk_adjusted_net_apy >= 3.0:
            label = "CONSIDER"
        else:
            label = "LOW_PRIORITY"

        return {
            "protocol": protocol,
            "asset": asset,
            "apy_pct": apy_pct,
            "risk_score": risk_score,
            "lock_period_days": lock_days,
            "withdrawal_notice_hours": withdrawal_notice,
            "capacity_remaining_usd": capacity,
            "annualized_gas_drag_pct": round(annualized_gas_drag_pct, 6),
            "net_apy_pct": round(net_apy_pct, 6),
            "risk_adjusted_net_apy": round(risk_adjusted_net_apy, 6),
            "min_viable_capital_usd": round(min_viable_capital, 4) if min_viable_capital is not None else None,
            "efficient_allocation_pct": None,  # filled after normalization
            "label": label,
            "flags": flags,
            "_inv_risk": inv_risk,  # internal; removed after normalization
        }

    def _normalize_weights(self, analyzed: list) -> None:
        """Compute efficient_allocation_pct via inverse-risk MVO."""
        total_w = sum(a["_inv_risk"] for a in analyzed)
        n = len(analyzed)
        for a in analyzed:
            pct = (a["_inv_risk"] / total_w * 100.0) if total_w > 0 else (100.0 / n)
            a["efficient_allocation_pct"] = round(pct, 4)
            del a["_inv_risk"]

    def _compute_aggregates(self, analyzed: list) -> dict:
        by_radj = sorted(analyzed, key=lambda x: x["risk_adjusted_net_apy"], reverse=True)
        top = by_radj[0]
        worst = by_radj[-1]

        rec_labels = {"MUST_ALLOCATE", "RECOMMENDED"}
        rec_summary = [
            (a["protocol"], a["efficient_allocation_pct"])
            for a in by_radj
            if a["label"] in rec_labels
        ]

        total_capacity = sum(a["capacity_remaining_usd"] for a in analyzed)
        must_count = sum(1 for a in analyzed if a["label"] == "MUST_ALLOCATE")

        return {
            "top_opportunity": top["protocol"],
            "top_opportunity_risk_adj_apy": top["risk_adjusted_net_apy"],
            "worst_opportunity": worst["protocol"],
            "worst_opportunity_risk_adj_apy": worst["risk_adjusted_net_apy"],
            "recommended_allocation_summary": rec_summary,
            "total_available_capacity_usd": total_capacity,
            "must_allocate_count": must_count,
        }

    def _empty_result(self, config: dict) -> dict:
        return {
            "opportunities": [],
            "top_opportunity": None,
            "top_opportunity_risk_adj_apy": None,
            "worst_opportunity": None,
            "worst_opportunity_risk_adj_apy": None,
            "recommended_allocation_summary": [],
            "total_available_capacity_usd": 0.0,
            "must_allocate_count": 0,
            "config_used": dict(config),
        }

    def _append_log(self, result: dict, log_path: str) -> None:
        dir_ = os.path.dirname(log_path)
        if dir_:
            os.makedirs(dir_, exist_ok=True)

        try:
            with open(log_path, "r") as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        except Exception:
            log = []

        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "opportunity_count": len(result.get("opportunities", [])),
            "must_allocate_count": result.get("must_allocate_count", 0),
            "top_opportunity": result.get("top_opportunity"),
            "total_capacity_usd": result.get("total_available_capacity_usd"),
        }
        log.append(entry)
        log = log[-self.LOG_CAP:]

        tmp = log_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp, log_path)
