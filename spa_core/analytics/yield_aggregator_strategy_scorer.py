"""
MP-897 YieldAggregatorStrategyScorer
Advisory/read-only analytics module.
Scores yield aggregator strategies (Yearn, Convex, Beefy, Harvest) on
quality, efficiency, and risk.

Usage:
    from spa_core.analytics.yield_aggregator_strategy_scorer import analyze
    result = analyze(strategies, config)

Pure stdlib. No external dependencies.
"""

import json
import os
import time
import tempfile

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "aggregator_strategy_log.json"
)
_LOG_CAP = 100

_COMPOUND_SCORE = {
    "HOURLY": 100,
    "DAILY": 80,
    "WEEKLY": 50,
    "MANUAL": 10,
}

_MATURITY_LABEL = {
    "ESTABLISHED": 100,
    "MATURE": 70,
    "GROWING": 40,
    "NEW": 10,
}

_HARVEST_SCORE = {
    "FRESH": 100,
    "HEALTHY": 80,
    "STALE": 40,
    "ABANDONED": 0,
}

_DEFAULT_CONFIG = {
    "min_apy_improvement_pct": 2.0,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strategy_maturity(age_days: int) -> str:
    if age_days > 365:
        return "ESTABLISHED"
    if age_days > 180:
        return "MATURE"
    if age_days > 90:
        return "GROWING"
    return "NEW"


def _harvest_health(last_harvest_days_ago: int) -> str:
    if last_harvest_days_ago <= 1:
        return "FRESH"
    if last_harvest_days_ago <= 7:
        return "HEALTHY"
    if last_harvest_days_ago <= 30:
        return "STALE"
    return "ABANDONED"


def _aggregator_grade(quality_score: int) -> str:
    if quality_score >= 90:
        return "S"
    if quality_score >= 80:
        return "A"
    if quality_score >= 70:
        return "B"
    if quality_score >= 60:
        return "C"
    if quality_score >= 50:
        return "D"
    return "F"


def _build_recommendation(grade: str, net_apy: float, efficiency: float,
                           fee_drag: float, flags: list) -> str:
    if grade in ("S", "A"):
        return (
            f"Top-tier aggregator. {net_apy:.1f}% net APY, "
            f"{efficiency:.2f}x efficiency."
        )
    if grade == "B":
        return (
            f"Solid strategy. {net_apy:.1f}% net APY. "
            f"{len(flags)} minor concern(s)."
        )
    if grade == "C":
        return (
            f"Mediocre. Fee drag {fee_drag:.1f}% reduces value. "
            f"Consider alternatives."
        )
    # D or F
    flag_str = ", ".join(flags[:2]) if flags else "poor metrics"
    return f"Avoid. {flag_str}."


def _atomic_log(entry: dict, log_path: str = _LOG_PATH) -> None:
    """Append entry to ring-buffer JSON log (capped at _LOG_CAP). Atomic write."""
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                records = json.load(f)
            if not isinstance(records, list):
                records = []
        else:
            records = []
        records.append(entry)
        records = records[-_LOG_CAP:]
        dir_name = os.path.dirname(log_path)
        with tempfile.NamedTemporaryFile(
            "w", dir=dir_name, delete=False, encoding="utf-8", suffix=".tmp"
        ) as tf:
            json.dump(records, tf, indent=2)
            tmp_path = tf.name
        os.replace(tmp_path, log_path)
    except Exception:
        # Advisory module — never raise on log failure
        pass


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(strategies: list, config: dict = None) -> dict:
    """
    Score yield aggregator strategies on quality, efficiency, and risk.

    Parameters
    ----------
    strategies : list of dict
        Each dict must contain:
            name, aggregator, underlying_apy_pct, aggregated_apy_pct,
            management_fee_pct, performance_fee_pct, auto_compound_frequency,
            strategy_age_days, tvl_usd, strategy_count, last_harvest_days_ago
    config : dict, optional
        min_apy_improvement_pct (default 2.0)

    Returns
    -------
    dict with keys:
        strategies, best_strategy, most_efficient,
        average_net_apy_pct, timestamp
    """
    cfg = dict(_DEFAULT_CONFIG)
    if config:
        cfg.update(config)

    min_boost = float(cfg.get("min_apy_improvement_pct", 2.0))

    scored = []

    for s in strategies:
        name = s.get("name", "")
        aggregator = s.get("aggregator", "OTHER")
        underlying_apy = float(s.get("underlying_apy_pct", 0.0))
        aggregated_apy = float(s.get("aggregated_apy_pct", 0.0))
        mgmt_fee = float(s.get("management_fee_pct", 0.0))
        perf_fee = float(s.get("performance_fee_pct", 0.0))
        compound_freq = s.get("auto_compound_frequency", "MANUAL")
        age_days = int(s.get("strategy_age_days", 0))
        tvl = float(s.get("tvl_usd", 0.0))
        strat_count = int(s.get("strategy_count", 1))
        last_harvest = int(s.get("last_harvest_days_ago", 0))

        # ── Derived metrics ──────────────────────────────────────────────
        apy_boost = aggregated_apy - underlying_apy
        fee_drag = mgmt_fee + perf_fee * aggregated_apy / 100.0
        net_apy = aggregated_apy - fee_drag
        efficiency = net_apy / underlying_apy if underlying_apy > 0 else 1.0

        # ── Component scores ─────────────────────────────────────────────
        compound_score = _COMPOUND_SCORE.get(compound_freq, 10)
        maturity = _strategy_maturity(age_days)
        harvest = _harvest_health(last_harvest)
        maturity_score = _MATURITY_LABEL[maturity]
        harvest_score = _HARVEST_SCORE[harvest]
        diversity_score = min(100, strat_count * 20)

        # efficiency capped at 100 for quality score contribution
        eff_capped = min(100.0, efficiency * 20.0)

        quality_score = max(0, min(100, int(
            eff_capped * 0.20
            + compound_score * 0.30
            + diversity_score * 0.20
            + maturity_score * 0.10
            + harvest_score * 0.20
        )))

        grade = _aggregator_grade(quality_score)

        # ── Flags ────────────────────────────────────────────────────────
        flags: list = []
        if apy_boost < min_boost:
            flags.append("INSUFFICIENT_BOOST")
        if fee_drag > 3.0:
            flags.append("HIGH_FEES")
        if harvest in ("STALE", "ABANDONED"):
            flags.append("STALE_HARVEST")
        if tvl < 1_000_000:
            flags.append("LOW_TVL")
        if strat_count <= 1:
            flags.append("SINGLE_STRATEGY")

        recommendation = _build_recommendation(
            grade, net_apy, efficiency, fee_drag, flags
        )

        scored.append({
            "name": name,
            "aggregator": aggregator,
            "apy_boost_pct": round(apy_boost, 6),
            "fee_drag_pct": round(fee_drag, 6),
            "net_apy_pct": round(net_apy, 6),
            "efficiency_ratio": round(efficiency, 6),
            "compound_frequency_score": compound_score,
            "strategy_maturity": maturity,
            "harvest_health": harvest,
            "quality_score": quality_score,
            "aggregator_grade": grade,
            "flags": flags,
            "recommendation": recommendation,
        })

    # ── Summary ──────────────────────────────────────────────────────────
    best_strategy = None
    most_efficient = None
    avg_net_apy = 0.0

    if scored:
        best_strategy = max(scored, key=lambda x: x["net_apy_pct"])["name"]
        most_efficient = max(scored, key=lambda x: x["efficiency_ratio"])["name"]
        avg_net_apy = sum(x["net_apy_pct"] for x in scored) / len(scored)

    result = {
        "strategies": scored,
        "best_strategy": best_strategy,
        "most_efficient": most_efficient,
        "average_net_apy_pct": round(avg_net_apy, 6),
        "timestamp": time.time(),
    }

    _atomic_log({
        "timestamp": result["timestamp"],
        "strategy_count": len(scored),
        "best_strategy": best_strategy,
        "most_efficient": most_efficient,
        "average_net_apy_pct": result["average_net_apy_pct"],
    })

    return result
