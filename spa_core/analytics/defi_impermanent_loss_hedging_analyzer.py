"""
MP-946: DeFiImpermanentLossHedgingAnalyzer
Analyzes impermanent loss hedging strategies for AMM LP positions.
Pure stdlib, read-only analytics, atomic writes.
"""

import json
import os
import time
from typing import Optional

# ── Constants ────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "il_hedging_log.json"
)
LOG_CAP = 100

# Hedge labels
LABEL_EFFECTIVE_HEDGE = "EFFECTIVE_HEDGE"
LABEL_PARTIAL_HEDGE = "PARTIAL_HEDGE"
LABEL_EXPENSIVE_HEDGE = "EXPENSIVE_HEDGE"
LABEL_UNNECESSARY = "UNNECESSARY"
LABEL_NO_HEDGE_AVAILABLE = "NO_HEDGE_AVAILABLE"

# Flags
FLAG_HIGH_IL = "HIGH_IL"
FLAG_CORRELATED_PAIR = "CORRELATED_PAIR"
FLAG_HEDGE_PROFITABLE = "HEDGE_PROFITABLE"
FLAG_COST_EXCEEDS_IL = "COST_EXCEEDS_IL"
FLAG_LOW_CORR_HIGH_RISK = "LOW_CORRELATION_HIGH_RISK"

# Recommendations
REC_HEDGE = "hedge"
REC_PARTIAL = "partial"
REC_SKIP = "skip"

DEFAULT_CONFIG = {
    "high_il_threshold_pct": 5.0,          # il_pct > this → HIGH_IL
    "correlated_pair_threshold": 0.7,       # correlation > this → CORRELATED_PAIR
    "low_correlation_threshold": 0.3,       # correlation < this → low corr
    "large_position_usd": 50000.0,          # lp_value > this → large position
    "effective_hedge_efficiency_min": 70.0, # efficiency >= this → EFFECTIVE
    "partial_hedge_efficiency_min": 40.0,   # efficiency >= this → PARTIAL
    "effective_hedge_coverage_min": 60.0,   # coverage >= this → EFFECTIVE
    "partial_hedge_coverage_min": 30.0,     # coverage >= this → PARTIAL
    "unnecessary_il_max_pct": 2.0,          # il_pct <= this → UNNECESSARY
    "profitable_hedge_value_threshold": 0.0,# hedge_value > this → HEDGE_PROFITABLE
    "partial_hedge_value_min": -10.0,       # hedge_value > this AND coverage > 50 → partial
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _has_real_hedge(available_hedges: list) -> bool:
    """Returns True if at least one non-'none' hedge is available."""
    for h in available_hedges:
        if str(h).lower() not in ("none", ""):
            return True
    return False


def _compute_hedge_efficiency_score(
    hedge_coverage_pct: float, hedge_cost_annual_pct: float
) -> float:
    """
    Efficiency score 0-100.
    Score = coverage - cost, clamped to [0, 100].
    High coverage with low cost → high efficiency.
    """
    raw = hedge_coverage_pct - hedge_cost_annual_pct
    return round(_clamp(raw, 0.0, 100.0), 4)


def _compute_net_hedged_apy(
    apy_with_hedge_pct: float, hedge_cost_annual_pct: float
) -> float:
    """Net APY after paying for the hedge."""
    return round(apy_with_hedge_pct - hedge_cost_annual_pct, 6)


def _compute_hedge_value_pct(
    net_hedged_apy: float, apy_without_hedge_pct: float
) -> float:
    """
    Relative value of hedging vs. not hedging.
    = (net_hedged_apy / apy_without_hedge) - 1
    Returns 0.0 if apy_without_hedge is zero.
    """
    if abs(apy_without_hedge_pct) < 1e-9:
        return 0.0
    return round(net_hedged_apy / apy_without_hedge_pct - 1.0, 6)


def _determine_recommendation(
    hedge_value_pct: float,
    hedge_coverage_pct: float,
    config: dict,
) -> str:
    """hedge / partial / skip."""
    profitable_threshold = float(
        config.get("profitable_hedge_value_threshold", 0.0)
    )
    partial_min = float(config.get("partial_hedge_value_min", -10.0))

    if hedge_value_pct > profitable_threshold:
        return REC_HEDGE
    if hedge_value_pct > partial_min and hedge_coverage_pct > 50.0:
        return REC_PARTIAL
    return REC_SKIP


def _determine_label(
    position: dict,
    hedge_efficiency_score: float,
    config: dict,
) -> str:
    """
    EFFECTIVE_HEDGE / PARTIAL_HEDGE / EXPENSIVE_HEDGE / UNNECESSARY / NO_HEDGE_AVAILABLE
    """
    available_hedges = position.get("available_hedges", [])
    il_pct = float(position.get("il_pct", 0.0))
    hedge_cost_annual_pct = float(position.get("hedge_cost_annual_pct", 0.0))
    hedge_coverage_pct = float(position.get("hedge_coverage_pct", 0.0))

    unnecessary_max = float(config.get("unnecessary_il_max_pct", 2.0))
    eff_min = float(config.get("effective_hedge_efficiency_min", 70.0))
    eff_cov_min = float(config.get("effective_hedge_coverage_min", 60.0))
    partial_min = float(config.get("partial_hedge_efficiency_min", 40.0))
    partial_cov_min = float(config.get("partial_hedge_coverage_min", 30.0))

    if not _has_real_hedge(available_hedges):
        return LABEL_NO_HEDGE_AVAILABLE

    if il_pct <= unnecessary_max:
        return LABEL_UNNECESSARY

    if hedge_cost_annual_pct > il_pct and il_pct > 0:
        return LABEL_EXPENSIVE_HEDGE

    if (
        hedge_efficiency_score >= eff_min
        and hedge_coverage_pct >= eff_cov_min
    ):
        return LABEL_EFFECTIVE_HEDGE

    if (
        hedge_efficiency_score >= partial_min
        and hedge_coverage_pct >= partial_cov_min
    ):
        return LABEL_PARTIAL_HEDGE

    return LABEL_EXPENSIVE_HEDGE


def _compute_flags(position: dict, hedge_value_pct: float, config: dict) -> list:
    """Compute all applicable flags for this position."""
    flags = []
    il_pct = float(position.get("il_pct", 0.0))
    correlation_ab = float(position.get("correlation_ab", 0.5))
    lp_value_usd = float(position.get("lp_value_usd", 0.0))
    hedge_cost_annual_pct = float(position.get("hedge_cost_annual_pct", 0.0))

    high_il_thresh = float(config.get("high_il_threshold_pct", 5.0))
    corr_thresh = float(config.get("correlated_pair_threshold", 0.7))
    low_corr_thresh = float(config.get("low_correlation_threshold", 0.3))
    large_pos_usd = float(config.get("large_position_usd", 50000.0))
    profitable_thresh = float(config.get("profitable_hedge_value_threshold", 0.0))

    if il_pct > high_il_thresh:
        flags.append(FLAG_HIGH_IL)

    if correlation_ab > corr_thresh:
        flags.append(FLAG_CORRELATED_PAIR)

    if hedge_value_pct > profitable_thresh:
        flags.append(FLAG_HEDGE_PROFITABLE)

    if hedge_cost_annual_pct > il_pct and il_pct > 0:
        flags.append(FLAG_COST_EXCEEDS_IL)

    if correlation_ab < low_corr_thresh and lp_value_usd > large_pos_usd:
        flags.append(FLAG_LOW_CORR_HIGH_RISK)

    return flags


def _analyze_position(position: dict, config: dict) -> dict:
    """Compute all per-position analytics."""
    pair = position.get("pair", "UNKNOWN/UNKNOWN")
    token_a = position.get("token_a", "")
    token_b = position.get("token_b", "")
    lp_value_usd = float(position.get("lp_value_usd", 0.0))
    il_pct = float(position.get("il_pct", 0.0))
    correlation_ab = float(position.get("correlation_ab", 0.5))
    available_hedges = position.get("available_hedges", [])
    hedge_cost_annual_pct = float(position.get("hedge_cost_annual_pct", 0.0))
    hedge_coverage_pct = float(position.get("hedge_coverage_pct", 0.0))
    apy_with_hedge_pct = float(position.get("apy_with_hedge_pct", 0.0))
    apy_without_hedge_pct = float(position.get("apy_without_hedge_pct", 0.0))

    hedge_efficiency_score = _compute_hedge_efficiency_score(
        hedge_coverage_pct, hedge_cost_annual_pct
    )
    net_hedged_apy = _compute_net_hedged_apy(apy_with_hedge_pct, hedge_cost_annual_pct)
    hedge_value_pct = _compute_hedge_value_pct(net_hedged_apy, apy_without_hedge_pct)
    recommendation = _determine_recommendation(hedge_value_pct, hedge_coverage_pct, config)
    label = _determine_label(position, hedge_efficiency_score, config)
    flags = _compute_flags(position, hedge_value_pct, config)

    il_exposure_usd = round(lp_value_usd * il_pct / 100.0, 4)

    return {
        "pair": pair,
        "token_a": token_a,
        "token_b": token_b,
        "lp_value_usd": lp_value_usd,
        "il_pct": il_pct,
        "correlation_ab": correlation_ab,
        "available_hedges": list(available_hedges),
        "hedge_cost_annual_pct": hedge_cost_annual_pct,
        "hedge_coverage_pct": hedge_coverage_pct,
        "apy_with_hedge_pct": apy_with_hedge_pct,
        "apy_without_hedge_pct": apy_without_hedge_pct,
        # Computed
        "hedge_efficiency_score": hedge_efficiency_score,
        "net_hedged_apy": net_hedged_apy,
        "hedge_value_pct": hedge_value_pct,
        "recommendation": recommendation,
        "hedge_label": label,
        "flags": flags,
        "il_exposure_usd": il_exposure_usd,
    }


def _compute_aggregates(results: list, config: dict) -> dict:
    """Compute portfolio-level aggregates."""
    if not results:
        return {
            "best_hedge_opportunity": None,
            "least_effective_hedge": None,
            "total_il_exposure_usd": 0.0,
            "average_hedge_efficiency": 0.0,
            "effective_hedge_count": 0,
        }

    scores = [r["hedge_efficiency_score"] for r in results]
    best_idx = scores.index(max(scores))
    worst_idx = scores.index(min(scores))

    total_il_usd = round(sum(r["il_exposure_usd"] for r in results), 4)
    avg_eff = round(sum(scores) / len(scores), 4)
    eff_count = sum(1 for r in results if r["hedge_label"] == LABEL_EFFECTIVE_HEDGE)

    return {
        "best_hedge_opportunity": results[best_idx]["pair"],
        "least_effective_hedge": results[worst_idx]["pair"],
        "total_il_exposure_usd": total_il_usd,
        "average_hedge_efficiency": avg_eff,
        "effective_hedge_count": eff_count,
    }


def _write_log(entry: dict) -> None:
    """Append entry to ring-buffer log (atomic write, cap LOG_CAP)."""
    log_path = os.path.normpath(LOG_PATH)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    existing: list = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    existing = data
        except Exception:
            existing = []

    existing.append(entry)
    if len(existing) > LOG_CAP:
        existing = existing[-LOG_CAP:]

    tmp_path = log_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    os.replace(tmp_path, log_path)


class DeFiImpermanentLossHedgingAnalyzer:
    """
    Analyzes IL hedging strategies for AMM LP positions.
    All methods are pure functions; no external state is modified
    except the ring-buffer log on disk.
    """

    def analyze(self, positions: list, config: Optional[dict] = None) -> dict:
        """
        Main entry point.

        Args:
            positions: list of position dicts
            config: optional config overrides

        Returns:
            dict with 'positions' (per-position analytics) and 'aggregates'.
        """
        cfg = {**DEFAULT_CONFIG, **(config or {})}

        analyzed = []
        for pos in positions:
            result = _analyze_position(pos, cfg)
            analyzed.append(result)

        aggregates = _compute_aggregates(analyzed, cfg)

        output = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "position_count": len(analyzed),
            "positions": analyzed,
            "aggregates": aggregates,
        }

        log_entry = {
            "timestamp": output["timestamp"],
            "position_count": len(analyzed),
            "total_il_exposure_usd": aggregates["total_il_exposure_usd"],
            "average_hedge_efficiency": aggregates["average_hedge_efficiency"],
            "effective_hedge_count": aggregates["effective_hedge_count"],
        }
        try:
            _write_log(log_entry)
        except Exception:
            pass  # analytics never raises

        return output
