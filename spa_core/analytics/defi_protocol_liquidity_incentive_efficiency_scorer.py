"""
MP-1018: DeFiProtocolLiquidityIncentiveEfficiencyScorer
Evaluates liquidity mining program efficiency: cost per unit of liquidity,
fee coverage, retention, and ROI metrics.
"""

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# --- constants -----------------------------------------------------------

COST_PER_TVL_LOW_COST_THRESHOLD = 5.0      # cents: < $0.05 per $1 TVL
COST_PER_TVL_EFFICIENT_THRESHOLD = 10.0    # cents: < $0.10 per $1 TVL
COST_PER_TVL_EXPENSIVE_THRESHOLD = 50.0    # cents: > $0.50 per $1 TVL

FEE_COVERAGE_SELF_FUNDING_MIN = 1.2
FEE_COVERAGE_BURNING_TREASURY_MAX = 0.2
FEE_COVERAGE_FEE_POSITIVE_MIN = 1.0

RETENTION_HIGH = 60.0       # %
RETENTION_MERCENARY = 20.0  # % (below = mercenary)
RETENTION_SELF_FUNDING_MIN = 60.0

EMISSION_INFLATION_THRESHOLD = -20.0  # % price drop → dilution

LONG_DURATION_WEEKS = 26

TVL_MULT_NORM_CAP = 10.0   # cap for tvl_multiplier normalization

LOG_CAP = 100

# --- helpers -------------------------------------------------------------

def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0.0:
        return default
    return numerator / denominator


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _atomic_write(path: str, data: Any) -> None:
    """Atomically write JSON data to path using tmp + os.replace."""
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    atomic_save(data, str(path))
def _load_log(path: str) -> list:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


# --- core scorer ---------------------------------------------------------

class DeFiProtocolLiquidityIncentiveEfficiencyScorer:
    """
    Scores DeFi liquidity mining programs by their efficiency.

    Usage:
        scorer = DeFiProtocolLiquidityIncentiveEfficiencyScorer()
        result = scorer.score(programs, config)
    """

    def __init__(self, log_path: str = "data/liquidity_incentive_efficiency_log.json"):
        self.log_path = log_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, programs: list, config: dict) -> dict:
        """
        Score a list of liquidity incentive programs.

        Args:
            programs: list of program dicts (see module docstring for keys)
            config:   optional overrides; currently unused but reserved

        Returns:
            dict with 'programs' (list of scored entries) and 'aggregates'.
        """
        scored = []
        for prog in programs:
            scored.append(self._score_program(prog, config))

        aggregates = self._compute_aggregates(scored)

        result = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "programs": scored,
            "aggregates": aggregates,
        }

        self._append_log(result)
        return result

    # ------------------------------------------------------------------
    # Per-program scoring
    # ------------------------------------------------------------------

    def _score_program(self, prog: dict, config: dict) -> dict:
        name = prog.get("name", "unknown")
        protocol = prog.get("protocol", "unknown")

        weekly_cost = float(prog.get("weekly_incentive_cost_usd", 0.0))
        incremental_tvl = float(prog.get("incremental_tvl_usd", 0.0))
        weekly_fees = float(prog.get("weekly_fees_generated_usd", 0.0))
        duration = float(prog.get("program_duration_weeks", 1.0))
        token_change = float(prog.get("token_price_change_pct_since_start", 0.0))
        retention = float(prog.get("organic_user_retention_pct", 0.0))
        tvl_attracted = float(prog.get("tvl_attracted_usd", 0.0))
        tvl_before = float(prog.get("tvl_before_program_usd", 0.0))

        # Derived totals
        incentive_cost_total = weekly_cost * max(duration, 1.0)
        fees_total = weekly_fees * max(duration, 1.0)

        # --- primary metrics ---
        # cents per dollar of incremental TVL attracted
        cost_per_tvl_dollar = _safe_div(weekly_cost, incremental_tvl, default=float("inf")) * 100.0

        # fee coverage: how many dollars in fees per dollar of incentives
        fee_coverage_ratio = _safe_div(weekly_fees, weekly_cost, default=0.0)

        # incremental TVL per total dollar spent
        tvl_multiplier = _safe_div(incremental_tvl, incentive_cost_total, default=0.0)

        # emission dilution: normalized 0-1 (higher = more dilution)
        emission_dilution_impact = _clamp(-token_change / 100.0, 0.0, 1.0)

        # payback in weeks (total cost / weekly fees)
        payback_period_weeks = _safe_div(incentive_cost_total, weekly_fees, default=float("inf"))

        # ROI efficiency score (0-100)
        fee_cov_norm = _clamp(fee_coverage_ratio / 2.0, 0.0, 1.0)
        retention_norm = _clamp(retention / 100.0, 0.0, 1.0)
        tvl_mult_norm = _clamp(tvl_multiplier / TVL_MULT_NORM_CAP, 0.0, 1.0)
        roi_efficiency_score = (
            fee_cov_norm * 40.0
            + retention_norm * 30.0
            + tvl_mult_norm * 30.0
        )

        # --- flags ---
        flags = self._compute_flags(
            cost_per_tvl_dollar=cost_per_tvl_dollar,
            fee_coverage_ratio=fee_coverage_ratio,
            retention=retention,
            token_change=token_change,
            duration=duration,
        )

        # --- label ---
        label = self._compute_label(
            cost_per_tvl_dollar=cost_per_tvl_dollar,
            fee_coverage_ratio=fee_coverage_ratio,
            retention=retention,
        )

        return {
            "name": name,
            "protocol": protocol,
            # raw inputs (echoed for traceability)
            "weekly_incentive_cost_usd": weekly_cost,
            "incremental_tvl_usd": incremental_tvl,
            "weekly_fees_generated_usd": weekly_fees,
            "program_duration_weeks": duration,
            "organic_user_retention_pct": retention,
            "token_price_change_pct_since_start": token_change,
            "tvl_attracted_usd": tvl_attracted,
            "tvl_before_program_usd": tvl_before,
            "incentive_cost_total": incentive_cost_total,
            # computed metrics
            "cost_per_tvl_dollar": round(cost_per_tvl_dollar, 6),
            "fee_coverage_ratio": round(fee_coverage_ratio, 6),
            "tvl_multiplier": round(tvl_multiplier, 6),
            "roi_efficiency_score": round(roi_efficiency_score, 4),
            "emission_dilution_impact": round(emission_dilution_impact, 6),
            "payback_period_weeks": round(payback_period_weeks, 4) if payback_period_weeks != float("inf") else None,
            # classification
            "label": label,
            "flags": flags,
        }

    def _compute_flags(
        self,
        cost_per_tvl_dollar: float,
        fee_coverage_ratio: float,
        retention: float,
        token_change: float,
        duration: float,
    ) -> list:
        flags = []
        if fee_coverage_ratio > FEE_COVERAGE_FEE_POSITIVE_MIN:
            flags.append("FEE_POSITIVE")
        if retention < RETENTION_MERCENARY:
            flags.append("MERCENARY_CAPITAL")
        if cost_per_tvl_dollar != float("inf") and cost_per_tvl_dollar < COST_PER_TVL_LOW_COST_THRESHOLD:
            flags.append("LOW_COST_ACQUISITION")
        if token_change < EMISSION_INFLATION_THRESHOLD:
            flags.append("EMISSION_INFLATION")
        if retention > RETENTION_HIGH:
            flags.append("HIGH_RETENTION")
        if duration > LONG_DURATION_WEEKS:
            flags.append("LONG_DURATION_COMMITMENT")
        return flags

    def _compute_label(
        self,
        cost_per_tvl_dollar: float,
        fee_coverage_ratio: float,
        retention: float,
    ) -> str:
        # Priority order matters
        if (
            fee_coverage_ratio < FEE_COVERAGE_BURNING_TREASURY_MAX
            and retention < RETENTION_MERCENARY
        ):
            return "BURNING_TREASURY"
        if (
            fee_coverage_ratio > FEE_COVERAGE_SELF_FUNDING_MIN
            and retention > RETENTION_SELF_FUNDING_MIN
        ):
            return "SELF_FUNDING"
        if cost_per_tvl_dollar != float("inf") and cost_per_tvl_dollar < COST_PER_TVL_EFFICIENT_THRESHOLD:
            return "EFFICIENT"
        if cost_per_tvl_dollar == float("inf") or cost_per_tvl_dollar > COST_PER_TVL_EXPENSIVE_THRESHOLD:
            return "EXPENSIVE"
        return "MODERATE"

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, scored: list) -> dict:
        if not scored:
            return {
                "most_efficient": None,
                "least_efficient": None,
                "avg_roi_efficiency": 0.0,
                "self_funding_count": 0,
                "burning_treasury_count": 0,
                "total_programs": 0,
            }

        by_roi = sorted(scored, key=lambda p: p["roi_efficiency_score"], reverse=True)
        most_efficient = by_roi[0]["name"]
        least_efficient = by_roi[-1]["name"]

        avg_roi = sum(p["roi_efficiency_score"] for p in scored) / len(scored)
        self_funding_count = sum(1 for p in scored if p["label"] == "SELF_FUNDING")
        burning_count = sum(1 for p in scored if p["label"] == "BURNING_TREASURY")

        return {
            "most_efficient": most_efficient,
            "least_efficient": least_efficient,
            "avg_roi_efficiency": round(avg_roi, 4),
            "self_funding_count": self_funding_count,
            "burning_treasury_count": burning_count,
            "total_programs": len(scored),
        }

    # ------------------------------------------------------------------
    # Ring-buffer log
    # ------------------------------------------------------------------

    def _append_log(self, entry: dict) -> None:
        log = _load_log(self.log_path)
        log.append(entry)
        if len(log) > LOG_CAP:
            log = log[-LOG_CAP:]
        _atomic_write(self.log_path, log)
