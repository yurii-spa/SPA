"""
MP-940: DeFi Yield Optimizer Allocation Scorer
Evaluates optimality of capital allocation across yield optimizer positions.

Standalone module — stdlib only, no external dependencies.
Atomic writes: tmp file + os.replace().
"""
import json
import os
import tempfile
from typing import Any, Dict, List, Optional


class DeFiYieldOptimizerAllocationScorer:
    """
    Scores optimality of capital allocations in yield optimizer protocols.

    Input fields per allocation (dict):
        protocol (str)                     – protocol name
        strategy_name (str)                – strategy identifier
        allocated_usd (float)              – capital allocated (USD)
        current_apy_pct (float)            – current APY in percent
        risk_score (float, 0-100)          – risk score (0=safest, 100=riskiest)
        gas_cost_annual_usd (float)        – estimated annual gas cost (USD)
        rebalance_frequency_days (float)   – days between rebalances
        opportunity_cost_pct (float)       – best available APY in same risk tier
        correlation_to_portfolio (float, 0-1) – correlation with rest of portfolio

    Computed per allocation:
        efficiency_ratio           current_apy / opportunity_cost_pct
        risk_adjusted_apy          current_apy * (1 - risk_score / 200)
        net_apy_after_gas          current_apy - (gas_cost_annual_usd / allocated_usd * 100)
        diversification_contribution 1 - correlation_to_portfolio

    Allocation label:
        OPTIMAL / GOOD / SUBOPTIMAL / INEFFICIENT / MISALLOCATED

    Flags:
        OPPORTUNITY_LOSS      efficiency_ratio < 0.8
        HIGH_GAS_DRAG         gas_cost_annual_usd > 0.5% of allocated_usd
        OVERCORRELATED        correlation_to_portfolio > 0.8 with another allocation
        RISK_MISMATCH         high risk_score (>70) but low current_apy_pct (<5%)
        OPTIMAL_ALLOCATION    all metrics in top quartile

    Aggregates:
        best_allocation, worst_allocation, portfolio_weighted_apy,
        total_opportunity_cost_usd, optimal_count

    config keys:
        log_path (str)   – path for ring-buffer JSON log
        persist (bool)   – if True, append result to log
    """

    LOG_CAP = 100
    DEFAULT_LOG_PATH = "data/yield_optimizer_allocation_log.json"

    # Thresholds
    EFFICIENCY_OPPORTUNITY_LOSS = 0.80
    GAS_DRAG_THRESHOLD_PCT = 0.005        # 0.5% of allocation
    OVERCORRELATION_THRESHOLD = 0.80
    RISK_MISMATCH_RISK_SCORE = 70.0
    RISK_MISMATCH_APY_THRESHOLD = 5.0

    # Label score thresholds (composite_score, higher = better)
    _LABEL_THRESHOLDS = [
        (80.0, "OPTIMAL"),
        (60.0, "GOOD"),
        (40.0, "SUBOPTIMAL"),
        (20.0, "INEFFICIENT"),
    ]

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def score(
        self,
        allocations: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Score capital allocations for yield optimizer efficiency.

        :param allocations: list of allocation dicts (see class docstring)
        :param config:      configuration dict (log_path, persist)
        :return:            dict with per-allocation scores and aggregates
        """
        log_path = config.get("log_path", self.DEFAULT_LOG_PATH)
        persist  = config.get("persist", False)

        if not allocations:
            result = self._empty_result()
            if persist:
                self._append_log(log_path, result)
            return result

        # First pass: compute derived metrics
        scored = [self._score_single(a) for a in allocations]

        # Second pass: detect OVERCORRELATED flag (cross-allocation)
        scored = self._apply_overcorrelation_flag(scored)

        # Aggregates
        aggregates = self._compute_aggregates(scored, allocations)

        result = {
            "allocations": scored,
            "aggregates": aggregates,
            "status": "ok",
        }

        if persist:
            self._append_log(log_path, result)

        return result

    # ------------------------------------------------------------------ #
    # Private — single allocation scoring                                  #
    # ------------------------------------------------------------------ #

    def _score_single(self, a: Dict[str, Any]) -> Dict[str, Any]:
        protocol     = str(a.get("protocol", "unknown"))
        strategy     = str(a.get("strategy_name", "unknown"))
        allocated    = float(a.get("allocated_usd", 0.0))
        current_apy  = float(a.get("current_apy_pct", 0.0))
        risk_score   = float(a.get("risk_score", 0.0))
        gas_annual   = float(a.get("gas_cost_annual_usd", 0.0))
        opp_cost     = float(a.get("opportunity_cost_pct", current_apy))
        correlation  = float(a.get("correlation_to_portfolio", 0.0))

        # Clamp inputs
        risk_score  = max(0.0, min(100.0, risk_score))
        correlation = max(0.0, min(1.0, correlation))

        # --- Derived metrics ---
        # Efficiency ratio: how well current APY compares to best available
        if opp_cost > 0:
            efficiency_ratio = current_apy / opp_cost
        else:
            efficiency_ratio = 1.0 if current_apy >= 0 else 0.0

        # Risk-adjusted APY
        risk_adjusted_apy = current_apy * (1.0 - risk_score / 200.0)

        # Net APY after gas drag
        if allocated > 0:
            gas_drag_pct = (gas_annual / allocated) * 100.0
        else:
            gas_drag_pct = 0.0
        net_apy_after_gas = current_apy - gas_drag_pct

        # Diversification contribution
        diversification_contribution = 1.0 - correlation

        # --- Composite score (0-100, higher = better) ---
        composite_score = self._compute_composite_score(
            efficiency_ratio=efficiency_ratio,
            risk_adjusted_apy=risk_adjusted_apy,
            net_apy_after_gas=net_apy_after_gas,
            diversification_contribution=diversification_contribution,
            opp_cost=opp_cost,
        )

        # --- Label ---
        label = self._get_label(composite_score)

        # --- Flags (partial — OVERCORRELATED added in second pass) ---
        flags = self._compute_flags(
            efficiency_ratio=efficiency_ratio,
            gas_annual=gas_annual,
            allocated=allocated,
            risk_score=risk_score,
            current_apy=current_apy,
            composite_score=composite_score,
        )

        return {
            "protocol":                      protocol,
            "strategy_name":                 strategy,
            "allocated_usd":                 allocated,
            "current_apy_pct":               current_apy,
            "risk_score":                    risk_score,
            "gas_cost_annual_usd":           gas_annual,
            "rebalance_frequency_days":      float(a.get("rebalance_frequency_days", 0.0)),
            "opportunity_cost_pct":          opp_cost,
            "correlation_to_portfolio":      correlation,
            # Derived
            "efficiency_ratio":              round(efficiency_ratio, 4),
            "risk_adjusted_apy":             round(risk_adjusted_apy, 4),
            "net_apy_after_gas":             round(net_apy_after_gas, 4),
            "diversification_contribution":  round(diversification_contribution, 4),
            "composite_score":               round(composite_score, 2),
            "label":                         label,
            "flags":                         flags,
        }

    def _compute_composite_score(
        self,
        efficiency_ratio: float,
        risk_adjusted_apy: float,
        net_apy_after_gas: float,
        diversification_contribution: float,
        opp_cost: float,
    ) -> float:
        """
        Composite score 0-100 (higher = better allocation).

        Components:
          - efficiency_score (40%): how close efficiency_ratio is to 1.0+
          - net_yield_score  (35%): net_apy_after_gas relative to opp_cost
          - diversification  (25%): diversification_contribution * 100
        """
        # Efficiency component: cap at 1.2 (120% of opportunity cost = max)
        eff_capped = min(efficiency_ratio, 1.2)
        efficiency_score = (eff_capped / 1.2) * 100.0
        efficiency_score = max(0.0, efficiency_score)

        # Net yield component: relative to opportunity cost
        if opp_cost > 0:
            net_yield_ratio = net_apy_after_gas / opp_cost
        else:
            net_yield_ratio = 1.0 if net_apy_after_gas >= 0 else 0.0
        net_yield_ratio = max(0.0, min(1.2, net_yield_ratio))
        net_yield_score = (net_yield_ratio / 1.2) * 100.0

        # Diversification component
        diversification_score = diversification_contribution * 100.0

        composite = (
            efficiency_score       * 0.40 +
            net_yield_score        * 0.35 +
            diversification_score  * 0.25
        )
        return max(0.0, min(100.0, composite))

    def _get_label(self, composite_score: float) -> str:
        for threshold, label in self._LABEL_THRESHOLDS:
            if composite_score >= threshold:
                return label
        return "MISALLOCATED"

    def _compute_flags(
        self,
        efficiency_ratio: float,
        gas_annual: float,
        allocated: float,
        risk_score: float,
        current_apy: float,
        composite_score: float,
    ) -> List[str]:
        flags = []

        if efficiency_ratio < self.EFFICIENCY_OPPORTUNITY_LOSS:
            flags.append("OPPORTUNITY_LOSS")

        if allocated > 0 and gas_annual > (allocated * self.GAS_DRAG_THRESHOLD_PCT):
            flags.append("HIGH_GAS_DRAG")

        if risk_score > self.RISK_MISMATCH_RISK_SCORE and current_apy < self.RISK_MISMATCH_APY_THRESHOLD:
            flags.append("RISK_MISMATCH")

        # OPTIMAL_ALLOCATION: composite >= 80 (OPTIMAL label) + no negative flags
        if composite_score >= 80.0:
            # Will add OPTIMAL_ALLOCATION only if no negative flags
            if not flags:
                flags.append("OPTIMAL_ALLOCATION")

        return flags

    def _apply_overcorrelation_flag(
        self, scored: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Add OVERCORRELATED flag if correlation_to_portfolio > threshold.
        Each allocation's correlation represents its correlation with the
        overall portfolio; high values indicate redundancy.
        """
        for item in scored:
            if item["correlation_to_portfolio"] > self.OVERCORRELATION_THRESHOLD:
                if "OVERCORRELATED" not in item["flags"]:
                    item["flags"].append("OVERCORRELATED")
        return scored

    # ------------------------------------------------------------------ #
    # Private — aggregates                                                 #
    # ------------------------------------------------------------------ #

    def _compute_aggregates(
        self,
        scored: List[Dict[str, Any]],
        original: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        scores = [s["composite_score"] for s in scored]
        best_idx  = scores.index(max(scores))
        worst_idx = scores.index(min(scores))

        # Portfolio weighted APY (weighted by allocated_usd)
        total_allocated = sum(s["allocated_usd"] for s in scored)
        if total_allocated > 0:
            weighted_apy = sum(
                s["current_apy_pct"] * s["allocated_usd"]
                for s in scored
            ) / total_allocated
        else:
            weighted_apy = 0.0

        # Total opportunity cost: what is foregone vs best available
        total_opp_cost_usd = sum(
            max(0.0, s["opportunity_cost_pct"] - s["current_apy_pct"])
            * s["allocated_usd"] / 100.0
            for s in scored
        )

        optimal_count = sum(1 for s in scored if s["label"] == "OPTIMAL")

        return {
            "best_allocation":            scored[best_idx]["protocol"],
            "worst_allocation":           scored[worst_idx]["protocol"],
            "portfolio_weighted_apy":     round(weighted_apy, 4),
            "total_opportunity_cost_usd": round(total_opp_cost_usd, 2),
            "optimal_count":              optimal_count,
            "total_allocations":          len(scored),
        }

    # ------------------------------------------------------------------ #
    # Private — empty result                                               #
    # ------------------------------------------------------------------ #

    def _empty_result(self) -> Dict[str, Any]:
        return {
            "allocations": [],
            "aggregates": {
                "best_allocation":            None,
                "worst_allocation":           None,
                "portfolio_weighted_apy":     0.0,
                "total_opportunity_cost_usd": 0.0,
                "optimal_count":              0,
                "total_allocations":          0,
            },
            "status": "ok",
        }

    # ------------------------------------------------------------------ #
    # Private — log persistence                                            #
    # ------------------------------------------------------------------ #

    def _append_log(self, log_path: str, entry: Dict) -> None:
        """Append entry to ring-buffer log (cap=LOG_CAP), atomic write."""
        try:
            if os.path.exists(log_path):
                with open(log_path, "r") as fh:
                    data = json.load(fh)
                if not isinstance(data, list):
                    data = []
            else:
                data = []

            data.append(entry)
            if len(data) > self.LOG_CAP:
                data = data[-self.LOG_CAP:]

            dir_name = os.path.dirname(os.path.abspath(log_path))
            os.makedirs(dir_name, exist_ok=True)

            fd, tmp_path = tempfile.mkstemp(
                dir=dir_name, prefix=".yield_optimizer_alloc_tmp_"
            )
            try:
                with os.fdopen(fd, "w") as fh:
                    json.dump(data, fh, indent=2)
                os.replace(tmp_path, log_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception:
            pass  # analytics must never crash the system
