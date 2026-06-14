"""
MP-899 DeFiPositionPnLTracker
Advisory/read-only analytics module.
Tracks comprehensive P&L for DeFi positions: realized/unrealized IL, fee income,
reward token value, gas drag, and benchmark-relative alpha.

Data log: data/position_pnl_log.json (ring-buffer, max 100 entries)
Pure stdlib. No external dependencies.
"""

import json
import os
import time
import tempfile


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_CAP = 100

_DEFAULT_CONFIG = {
    "benchmark_apy_pct": 5.0,
}

# Performance label thresholds (applied in order)
_PERF_ORDER = [
    "LOSS",         # net_pnl_usd < 0
    "EXCEPTIONAL",  # alpha_pct > 10
    "OUTPERFORM",   # alpha_pct > 0
    "UNDERPERFORM", # alpha_pct <= -5
    "BENCHMARK",    # else (alpha in range -5..0)
]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _safe_div(numerator: float, denominator: float) -> float:
    """Return numerator / denominator; 0.0 when denominator is 0."""
    if denominator == 0.0:
        return 0.0
    return numerator / denominator


def _safe_mean(values: list) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _performance_label(net_pnl_usd: float, alpha_pct: float) -> str:
    if net_pnl_usd < 0:
        return "LOSS"
    if alpha_pct > 10:
        return "EXCEPTIONAL"
    if alpha_pct > 0:
        return "OUTPERFORM"
    if alpha_pct <= -5:
        return "UNDERPERFORM"
    return "BENCHMARK"


def _status(net_pnl_usd: float, entry_value_usd: float) -> str:
    threshold = entry_value_usd * 0.01  # 1 %
    if net_pnl_usd > threshold:
        return "PROFITABLE"
    if net_pnl_usd < -threshold:
        return "LOSING"
    return "BREAKEVEN"


def _build_flags(
    il_drag_pct: float,
    gas_costs_usd: float,
    entry_value_usd: float,
    alpha_pct: float,
    days_held: int,
) -> list:
    flags = []
    if il_drag_pct > 5:
        flags.append("HIGH_IL")
    if entry_value_usd > 0 and gas_costs_usd > entry_value_usd * 0.02:
        flags.append("GAS_HEAVY")
    if alpha_pct < 0:
        flags.append("BELOW_BENCHMARK")
    if days_held < 7:
        flags.append("SHORT_HOLD")
    return flags


def _recommendation(
    performance_label: str,
    net_pnl_pct: float,
    alpha_pct: float,
    flags: list,
) -> str:
    if performance_label == "EXCEPTIONAL":
        return (
            f"Excellent. {net_pnl_pct:.1f}% total return, {alpha_pct:.1f}% alpha. "
            "Hold or increase."
        )
    if performance_label == "OUTPERFORM":
        return f"Beating benchmark by {alpha_pct:.1f}%. Continue monitoring."
    if performance_label == "BENCHMARK":
        return (
            f"In-line with benchmark ({alpha_pct:+.1f}% alpha). "
            "Review IL drag if applicable."
        )
    if performance_label == "UNDERPERFORM":
        return (
            f"Underperforming. {alpha_pct:.1f}% below benchmark. Consider exit."
        )
    # LOSS
    if flags:
        reason = ", ".join(flags[:2])
    else:
        reason = "review strategy"
    return f"Position in loss ({net_pnl_pct:.1f}%). Assess: {reason}."


def _analyse_position(pos: dict, benchmark_apy_pct: float) -> dict:
    protocol          = pos.get("protocol", "")
    position_type     = pos.get("position_type", "")
    entry_value_usd   = float(pos.get("entry_value_usd", 0.0))
    current_value_usd = float(pos.get("current_value_usd", 0.0))
    fees_earned_usd   = float(pos.get("fees_earned_usd", 0.0))
    rewards_earned_usd = float(pos.get("rewards_earned_usd", 0.0))
    il_loss_usd       = float(pos.get("il_loss_usd", 0.0))
    gas_costs_usd     = float(pos.get("gas_costs_usd", 0.0))
    days_held         = int(pos.get("days_held", 0))

    # Core PnL
    gross_pnl_usd = (
        current_value_usd - entry_value_usd + fees_earned_usd + rewards_earned_usd
    )
    net_pnl_usd = gross_pnl_usd - il_loss_usd - gas_costs_usd

    # Percentages (guard against zero entry)
    net_pnl_pct         = _safe_div(net_pnl_usd, entry_value_usd) * 100
    fee_yield_pct       = _safe_div(fees_earned_usd, entry_value_usd) * 100
    reward_yield_pct    = _safe_div(rewards_earned_usd, entry_value_usd) * 100
    il_drag_pct         = _safe_div(il_loss_usd, entry_value_usd) * 100

    # Annualised return
    if days_held > 0:
        annualized_return_pct = net_pnl_pct / days_held * 365
    else:
        annualized_return_pct = 0.0

    alpha_pct = annualized_return_pct - benchmark_apy_pct

    perf_label = _performance_label(net_pnl_usd, alpha_pct)
    status     = _status(net_pnl_usd, entry_value_usd)
    flags      = _build_flags(il_drag_pct, gas_costs_usd, entry_value_usd,
                               alpha_pct, days_held)
    recommendation = _recommendation(perf_label, net_pnl_pct, alpha_pct, flags)

    return {
        "protocol":              protocol,
        "position_type":         position_type,
        "entry_value_usd":       entry_value_usd,
        "current_value_usd":     current_value_usd,
        "gross_pnl_usd":         gross_pnl_usd,
        "net_pnl_usd":           net_pnl_usd,
        "net_pnl_pct":           net_pnl_pct,
        "annualized_return_pct": annualized_return_pct,
        "fee_yield_pct":         fee_yield_pct,
        "reward_yield_pct":      reward_yield_pct,
        "il_drag_pct":           il_drag_pct,
        "alpha_pct":             alpha_pct,
        "performance_label":     perf_label,
        "status":                status,
        "flags":                 flags,
        "recommendation":        recommendation,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(positions: list, config: dict = None) -> dict:
    """
    Analyse P&L for a list of DeFi positions.

    Parameters
    ----------
    positions : list[dict]
        Each dict has keys: protocol, position_type, entry_value_usd,
        current_value_usd, fees_earned_usd, rewards_earned_usd, il_loss_usd,
        gas_costs_usd, days_held.
    config : dict, optional
        Accepts ``benchmark_apy_pct`` (default 5.0).

    Returns
    -------
    dict
        Full analysis with per-position metrics and aggregates.
    """
    cfg = {**_DEFAULT_CONFIG, **(config or {})}
    benchmark_apy_pct = float(cfg.get("benchmark_apy_pct", 5.0))

    if not positions:
        return {
            "positions":            [],
            "total_net_pnl_usd":    0.0,
            "total_fees_earned_usd": 0.0,
            "total_il_loss_usd":    0.0,
            "best_performer":       None,
            "worst_performer":      None,
            "average_alpha_pct":    0.0,
            "timestamp":            time.time(),
        }

    analysed = [_analyse_position(p, benchmark_apy_pct) for p in positions]

    total_net_pnl_usd     = sum(p["net_pnl_usd"] for p in analysed)
    total_fees_earned_usd = sum(p["fee_yield_pct"] * p["entry_value_usd"] / 100
                                for p in analysed)
    total_il_loss_usd     = sum(p["il_drag_pct"] * p["entry_value_usd"] / 100
                                for p in analysed)

    annuals = [p["annualized_return_pct"] for p in analysed]
    best_idx  = annuals.index(max(annuals))
    worst_idx = annuals.index(min(annuals))

    average_alpha_pct = _safe_mean([p["alpha_pct"] for p in analysed])

    return {
        "positions":            analysed,
        "total_net_pnl_usd":    total_net_pnl_usd,
        "total_fees_earned_usd": total_fees_earned_usd,
        "total_il_loss_usd":    total_il_loss_usd,
        "best_performer":       analysed[best_idx]["protocol"],
        "worst_performer":      analysed[worst_idx]["protocol"],
        "average_alpha_pct":    average_alpha_pct,
        "timestamp":            time.time(),
    }


def log_result(result: dict, data_dir: str = None) -> None:
    """
    Append an analysis result to the ring-buffer log.

    Parameters
    ----------
    result : dict
        Return value of ``analyze()``.
    data_dir : str, optional
        Directory for the log file.  Defaults to the ``data/`` directory
        next to the repository root.
    """
    if data_dir is None:
        _here = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(_here, "..", "..", "data")

    log_path = os.path.join(data_dir, "position_pnl_log.json")

    # Read existing log
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            log = json.load(fh)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(result)
    # Enforce ring-buffer cap
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]

    # Atomic write
    os.makedirs(data_dir, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=data_dir, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp_path, log_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-899 DeFiPositionPnLTracker")
    parser.add_argument("--check", action="store_true",
                        help="Compute and print without writing (default)")
    parser.add_argument("--run", action="store_true",
                        help="Compute and write to data/position_pnl_log.json")
    parser.add_argument("--data-dir", default=None,
                        help="Override data directory")
    args = parser.parse_args()

    # Demo positions
    _DEMO = [
        {
            "protocol": "Aave V3",
            "position_type": "LENDING",
            "entry_value_usd": 50_000.0,
            "current_value_usd": 50_000.0,
            "fees_earned_usd": 1_200.0,
            "rewards_earned_usd": 0.0,
            "il_loss_usd": 0.0,
            "gas_costs_usd": 30.0,
            "days_held": 90,
        },
        {
            "protocol": "Uniswap V3",
            "position_type": "LP",
            "entry_value_usd": 30_000.0,
            "current_value_usd": 28_500.0,
            "fees_earned_usd": 900.0,
            "rewards_earned_usd": 200.0,
            "il_loss_usd": 1_800.0,
            "gas_costs_usd": 120.0,
            "days_held": 60,
        },
    ]

    result = analyze(_DEMO)
    print(json.dumps(result, indent=2))

    if args.run:
        log_result(result, data_dir=args.data_dir)
        print("[MP-899] Result written to position_pnl_log.json")
