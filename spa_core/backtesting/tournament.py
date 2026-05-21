"""
Strategy Tournament — runs multiple strategies on the same historical data
and picks a winner based on risk-adjusted performance.
Used to decide which strategy goes live on 2026-07-15.

Usage:
    from backtesting.tournament import StrategyTournament
    from backtesting.data_loader import generate_synthetic_history

    hist = generate_synthetic_history(days=90)
    result = StrategyTournament().run(hist)
    print(result.winner, result.confidence)
    print(result.recommendation)
"""

from __future__ import annotations

import sys
import logging
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

log = logging.getLogger(__name__)


# ─── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class TournamentResult:
    """
    Full result from StrategyTournament.run().

    Attributes:
        winner: Strategy name with the highest composite score.
        scores: Composite score (0–1) per strategy name.
        metrics: Full BacktestResult.metrics dict per strategy name.
        recommendation: Human-readable winner explanation.
        confidence: 'HIGH' if winner leads by >20%, 'MEDIUM' 10–20%, 'LOW' <10%.
    """
    winner: str
    scores: dict[str, float]
    metrics: dict[str, dict]
    recommendation: str
    confidence: str


# ─── Tournament ────────────────────────────────────────────────────────────────

# Strategy name → RiskConfig overrides applied before running the backtest.
# v1_passive: default conservative config.
# v2_aggressive: higher concentration limits, lower APY floor → more allocation.
_STRATEGY_CONFIGS: dict[str, dict] = {
    "v1_passive": {},           # use RiskConfig defaults
    "v2_aggressive": {          # looser limits to match live paper-v2 behaviour
        "max_single_protocol": 0.45,
        "min_apy_for_new_position": 2.0,
        "max_total_t2_allocation": 0.50,
    },
}

# Scoring weights (must sum to 1.0)
_WEIGHTS = {
    "sharpe_ratio":      0.40,
    "total_return_pct":  0.30,
    "max_drawdown_pct":  0.20,   # inverted — lower drawdown = better
    "win_rate":          0.10,
}


class StrategyTournament:
    """
    Runs multiple strategies on the SAME historical dataset and scores each
    using a weighted composite of Sharpe, return, drawdown, and win-rate.

    Scoring steps:
    1. Run BacktestEngine for each strategy.
    2. Extract the four scored metrics.
    3. Normalise each metric 0–1 across strategies (min–max scaling).
       For max_drawdown_pct the score is inverted (lower DD → higher score).
    4. Apply weights → composite score.
    5. Pick winner, compute confidence, and write recommendation.
    """

    def __init__(self, strategies: list[str] = None):
        self.strategies = strategies or ["v1_passive", "v2_aggressive"]

    def run(
        self,
        historical_data: list[dict],
        capital: float = 100_000,
    ) -> TournamentResult:
        """
        Run the tournament.

        Args:
            historical_data: list of dicts in BacktestEngine format.
            capital: Starting capital for each strategy (default $100,000).

        Returns:
            TournamentResult with winner, scores, metrics, recommendation, confidence.
        """
        from backtesting.engine import BacktestEngine
        from risk.policy import RiskConfig

        raw_metrics: dict[str, dict] = {}

        # ── Run each strategy ──────────────────────────────────────────────────
        for name in self.strategies:
            try:
                overrides = _STRATEGY_CONFIGS.get(name, {})
                config = RiskConfig(**overrides) if overrides else RiskConfig()
                engine = BacktestEngine(config=config)
                result = engine.run(historical_data, initial_capital=capital,
                                    policy_version=name)
                raw_metrics[name] = result.metrics
                log.info(
                    f"Tournament [{name}]: return={result.metrics['total_return_pct']:.4f}% "
                    f"sharpe={result.metrics['sharpe_ratio']:.4f} "
                    f"dd={result.metrics['max_drawdown_pct']:.4f}% "
                    f"win={result.metrics['win_rate']:.4f}"
                )
            except Exception as exc:
                log.error(f"Tournament: strategy '{name}' failed — {exc!r}")
                raw_metrics[name] = _zero_metrics()

        if not raw_metrics:
            return _fallback_result(self.strategies)

        # ── Extract the four scored metrics ────────────────────────────────────
        sharpes  = {n: m.get("sharpe_ratio", 0.0)      for n, m in raw_metrics.items()}
        returns  = {n: m.get("total_return_pct", 0.0)  for n, m in raw_metrics.items()}
        drawdowns= {n: m.get("max_drawdown_pct", 0.0)  for n, m in raw_metrics.items()}
        winrates = {n: m.get("win_rate", 0.0)           for n, m in raw_metrics.items()}

        # ── Normalise 0–1 (min–max) ────────────────────────────────────────────
        # For max_drawdown: lower is better → invert after normalising.
        norm_sharpe   = _normalise(sharpes,   invert=False)
        norm_return   = _normalise(returns,   invert=False)
        norm_drawdown = _normalise(drawdowns, invert=True)   # lower DD → higher score
        norm_winrate  = _normalise(winrates,  invert=False)

        # ── Composite score ────────────────────────────────────────────────────
        scores: dict[str, float] = {}
        for name in self.strategies:
            scores[name] = round(
                norm_sharpe[name]   * _WEIGHTS["sharpe_ratio"]
                + norm_return[name]   * _WEIGHTS["total_return_pct"]
                + norm_drawdown[name] * _WEIGHTS["max_drawdown_pct"]
                + norm_winrate[name]  * _WEIGHTS["win_rate"],
                6,
            )

        # ── Winner & confidence ────────────────────────────────────────────────
        winner = max(scores, key=lambda n: scores[n])
        sorted_scores = sorted(scores.values(), reverse=True)
        best  = sorted_scores[0]
        worst = sorted_scores[-1] if len(sorted_scores) > 1 else 0.0
        gap   = best - worst  # 0–1 range

        if gap > 0.20:
            confidence = "HIGH"
        elif gap > 0.10:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        # ── Human-readable recommendation ──────────────────────────────────────
        recommendation = _build_recommendation(
            winner, scores, sharpes, returns, drawdowns, winrates, raw_metrics
        )

        return TournamentResult(
            winner=winner,
            scores=scores,
            metrics=raw_metrics,
            recommendation=recommendation,
            confidence=confidence,
        )


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _normalise(values: dict[str, float], invert: bool = False) -> dict[str, float]:
    """Min-max normalise a dict of values to [0, 1]. Inverts if requested."""
    if not values:
        return {}
    lo = min(values.values())
    hi = max(values.values())
    span = hi - lo
    if span == 0:
        # All equal — give everyone 0.5 (neutral)
        return {n: 0.5 for n in values}
    result = {}
    for name, val in values.items():
        norm = (val - lo) / span
        result[name] = round(1.0 - norm if invert else norm, 6)
    return result


def _build_recommendation(
    winner: str,
    scores: dict[str, float],
    sharpes: dict[str, float],
    returns: dict[str, float],
    drawdowns: dict[str, float],
    winrates: dict[str, float],
    raw_metrics: dict[str, dict],
) -> str:
    """
    Build a human-readable recommendation sentence describing why the winner won.

    Example:
        "v1_passive recommended: superior Sharpe (24.76 vs 18.20) compensates
         for lower return (1.38% vs 1.89%)"
    """
    losers = [n for n in scores if n != winner]
    if not losers:
        return f"{winner} recommended: sole strategy evaluated."

    loser = losers[0]  # first / primary competitor

    winner_sharpe  = sharpes.get(winner, 0.0)
    loser_sharpe   = sharpes.get(loser, 0.0)
    winner_return  = returns.get(winner, 0.0)
    loser_return   = returns.get(loser, 0.0)
    winner_dd      = drawdowns.get(winner, 0.0)
    loser_dd       = drawdowns.get(loser, 0.0)
    winner_wr      = winrates.get(winner, 0.0)
    loser_wr       = winrates.get(loser, 0.0)

    # Find winner's strengths and weaknesses
    strengths = []
    weaknesses = []

    if winner_sharpe >= loser_sharpe:
        strengths.append(f"superior Sharpe ({winner_sharpe:.2f} vs {loser_sharpe:.2f})")
    else:
        weaknesses.append(f"lower Sharpe ({winner_sharpe:.2f} vs {loser_sharpe:.2f})")

    if winner_return >= loser_return:
        strengths.append(f"higher return ({winner_return:.2f}% vs {loser_return:.2f}%)")
    else:
        weaknesses.append(f"lower return ({winner_return:.2f}% vs {loser_return:.2f}%)")

    if winner_dd <= loser_dd:
        strengths.append(f"lower drawdown ({winner_dd:.2f}% vs {loser_dd:.2f}%)")
    else:
        weaknesses.append(f"higher drawdown ({winner_dd:.2f}% vs {loser_dd:.2f}%)")

    if winner_wr >= loser_wr:
        strengths.append(f"win rate {winner_wr*100:.0f}% vs {loser_wr*100:.0f}%")

    parts = []
    if strengths:
        parts.append("; ".join(strengths[:2]))
    if weaknesses:
        verb = "compensates for" if strengths else "despite"
        parts.append(f"{verb} {weaknesses[0]}")

    detail = " — ".join(parts) if parts else "highest composite score"
    return f"{winner} recommended: {detail}"


def _zero_metrics() -> dict:
    return {
        "sharpe_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "total_return_pct": 0.0,
        "annualised_return_pct": 0.0,
        "win_rate": 0.0,
        "total_trades": 0,
        "avg_position_size_usd": 0.0,
        "initial_capital_usd": 0.0,
        "final_capital_usd": 0.0,
        "total_interest_usd": 0.0,
        "backtest_days": 0,
    }


def _fallback_result(strategies: list[str]) -> TournamentResult:
    """Return a safe fallback result when no strategies could run."""
    name = strategies[0] if strategies else "unknown"
    scores = {s: 0.0 for s in strategies}
    metrics = {s: _zero_metrics() for s in strategies}
    return TournamentResult(
        winner=name,
        scores=scores,
        metrics=metrics,
        recommendation=f"{name} recommended: no data available for comparison.",
        confidence="LOW",
    )
