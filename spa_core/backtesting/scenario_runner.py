"""
SPA Backtesting — Scenario Runner (v0.9)
========================================

Runs complete backtests for named strategies and returns standardised results.
Supports side-by-side comparison of v1_passive vs v2_aggressive.

Strategy configs mirror the live paper-trading definitions:
  v1_passive   — conservative RiskConfig defaults (max 35% concentration, APY ≥ 3%)
  v2_aggressive — looser limits (45% concentration, APY ≥ 2%, higher T2 allocation)

Usage:
    from backtesting.scenario_runner import run_scenario, compare_scenarios

    result = run_scenario("v1_passive", initial_capital=100_000, days=90, seed=42)
    comparison = compare_scenarios(days=30)
"""

from __future__ import annotations

import math
import sys
import statistics
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtesting.engine import BacktestEngine
from backtesting.data_loader import generate_synthetic_history
from backtesting.metrics import (
    sharpe_ratio,
    max_drawdown,
    win_rate,
    total_return_pct,
    annualised_return_pct,
)
from risk.policy import RiskConfig


# ── Strategy configurations ───────────────────────────────────────────────────

_STRATEGY_CONFIGS: dict[str, dict] = {
    "v1_passive": {
        # Conservative defaults — same as RiskConfig()
        "max_single_protocol": 0.35,
        "min_apy_for_new_position": 3.0,
        "max_total_t2_allocation": 0.30,
    },
    "v2_aggressive": {
        # Looser limits — more allocation, higher T2 exposure
        "max_single_protocol": 0.45,
        "min_apy_for_new_position": 2.0,
        "max_total_t2_allocation": 0.50,
    },
}

_VALID_STRATEGIES = set(_STRATEGY_CONFIGS.keys())


# ── Calmar and Sortino helpers ────────────────────────────────────────────────

def _calmar_ratio(annualized_return_pct: float, max_dd_pct: float) -> float:
    """Calmar = annualised return / max drawdown (both in %)."""
    if max_dd_pct <= 0:
        return 0.0
    return round(annualized_return_pct / max_dd_pct, 4)


def _sortino_ratio(
    daily_returns: list[float],
    risk_free_rate: float = 0.04,
) -> float:
    """
    Annualised Sortino ratio: mean excess return / downside deviation.

    Downside deviation uses only negative-excess days.
    """
    if len(daily_returns) < 2:
        return 0.0

    daily_rf = risk_free_rate / 365.0
    excess = [r - daily_rf for r in daily_returns]
    mean_excess = statistics.mean(excess)

    downside = [e for e in excess if e < 0]
    if not downside:
        return 0.0  # no losing days → could be infinite, return 0 as sentinel

    downside_sq = sum(d ** 2 for d in downside) / len(downside)
    downside_dev = math.sqrt(downside_sq)

    if downside_dev == 0:
        return 0.0

    return round((mean_excess / downside_dev) * math.sqrt(365), 4)


# ── run_scenario ──────────────────────────────────────────────────────────────

def run_scenario(
    strategy: str,
    initial_capital: float = 100_000.0,
    days: int = 90,
    seed: int = 42,
) -> dict:
    """
    Run a complete backtest for a named strategy.

    Args:
        strategy: Strategy name — 'v1_passive' or 'v2_aggressive'.
        initial_capital: Starting capital in USD (default $100,000).
        days: Number of days to simulate (default 90).
        seed: Random seed for synthetic data reproducibility (default 42).

    Returns:
        Standardised result dict:
            {
                strategy, total_return, sharpe, max_drawdown, win_rate,
                calmar, sortino, equity_curve: list[dict],
                initial_capital, final_capital, days,
                annualized_return, total_trades, avg_position_size_usd,
            }

    Raises:
        ValueError: if strategy is not one of the valid strategy names.
    """
    if strategy not in _VALID_STRATEGIES:
        raise ValueError(
            f"Unknown strategy '{strategy}'. "
            f"Valid options: {sorted(_VALID_STRATEGIES)}"
        )

    # Build RiskConfig for this strategy
    cfg_overrides = _STRATEGY_CONFIGS[strategy]
    config = _build_risk_config(cfg_overrides)

    # Generate synthetic historical data
    hist = generate_synthetic_history(days=days, seed=seed)

    # Run backtest
    engine = BacktestEngine(config=config)
    result = engine.run(
        hist,
        initial_capital=initial_capital,
        policy_version=f"{strategy}-v0.9",
    )

    # Extract equity curve as a compact list
    equity_curve = [
        {
            "day": i,
            "date": snap["date"],
            "portfolio_value": snap["total_capital"],
            "pnl_pct": snap["pnl_pct"],
            "open_positions": snap.get("open_positions", 0),
        }
        for i, snap in enumerate(result.equity_curve)
    ]

    # Compute daily returns for Sortino
    capitals = [snap["total_capital"] for snap in result.equity_curve]
    daily_returns = [
        (capitals[i] - capitals[i - 1]) / capitals[i - 1]
        if capitals[i - 1] > 0 else 0.0
        for i in range(1, len(capitals))
    ]

    m = result.metrics
    ann_ret = m.get("annualised_return_pct", 0.0)
    max_dd = m.get("max_drawdown_pct", 0.0)

    return {
        "strategy": strategy,
        "total_return": m.get("total_return_pct", 0.0),
        "sharpe": m.get("sharpe_ratio", 0.0),
        "max_drawdown": max_dd,
        "win_rate": m.get("win_rate", 0.0),
        "calmar": _calmar_ratio(ann_ret, max_dd),
        "sortino": _sortino_ratio(daily_returns),
        "annualized_return": ann_ret,
        "equity_curve": equity_curve,
        "initial_capital": round(initial_capital, 2),
        "final_capital": m.get("final_capital_usd", initial_capital),
        "days": days,
        "total_trades": m.get("total_trades", 0),
        "avg_position_size_usd": m.get("avg_position_size_usd", 0.0),
    }


# ── compare_scenarios ─────────────────────────────────────────────────────────

def compare_scenarios(
    days: int = 90,
    initial_capital: float = 100_000.0,
    seed: int = 42,
) -> dict:
    """
    Run both strategies on the same synthetic data and return a side-by-side comparison.

    Both strategies use the same random seed → identical market conditions,
    so any performance difference is purely due to strategy parameters.

    Args:
        days: Number of backtest days (default 90).
        initial_capital: Starting capital for each strategy (default $100,000).
        seed: Shared random seed for reproducibility (default 42).

    Returns:
        Dict with keys:
            {
                days, seed, initial_capital,
                v1_passive: {strategy result dict},
                v2_aggressive: {strategy result dict},
                winner: str,
                winner_metric: str,   # which metric determined the winner
                delta: dict,          # v2 - v1 for each key metric
            }
    """
    v1 = run_scenario("v1_passive", initial_capital=initial_capital, days=days, seed=seed)
    v2 = run_scenario("v2_aggressive", initial_capital=initial_capital, days=days, seed=seed)

    # Determine winner by Sharpe-ratio (risk-adjusted performance)
    if v1["sharpe"] >= v2["sharpe"]:
        winner = "v1_passive"
        winner_metric = "sharpe_ratio"
    else:
        winner = "v2_aggressive"
        winner_metric = "sharpe_ratio"

    delta = {
        "total_return": round(v2["total_return"] - v1["total_return"], 4),
        "sharpe": round(v2["sharpe"] - v1["sharpe"], 4),
        "max_drawdown": round(v2["max_drawdown"] - v1["max_drawdown"], 4),
        "win_rate": round(v2["win_rate"] - v1["win_rate"], 4),
        "calmar": round(v2["calmar"] - v1["calmar"], 4),
        "sortino": round(v2["sortino"] - v1["sortino"], 4),
        "annualized_return": round(v2["annualized_return"] - v1["annualized_return"], 4),
    }

    return {
        "days": days,
        "seed": seed,
        "initial_capital": initial_capital,
        "v1_passive": v1,
        "v2_aggressive": v2,
        "winner": winner,
        "winner_metric": winner_metric,
        "delta": delta,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_risk_config(overrides: dict) -> RiskConfig:
    """
    Build a RiskConfig applying only the specified overrides.

    We construct the defaults first, then overwrite with any provided values.
    This ensures unspecified fields keep their RiskConfig defaults.
    """
    cfg = RiskConfig()
    for attr, value in overrides.items():
        if hasattr(cfg, attr):
            setattr(cfg, attr, value)
    return cfg
