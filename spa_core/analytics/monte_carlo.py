"""
spa_core/analytics/monte_carlo.py

MP-1496 (v11.12) — Monte Carlo simulation for strategy robustness testing.

Generates N synthetic return paths using Gaussian random walks and tests
the distribution of final portfolio values.

Rules (stdlib-only, read-only domain):
  - Uses only Python stdlib: random, statistics
  - N_SIMULATIONS default = 1000
  - Seed support for reproducibility in tests

Output path: data/monte_carlo_{strategy_id}.json

Usage:
    from spa_core.analytics.monte_carlo import MonteCarloSimulator

    mc = MonteCarloSimulator()
    result = mc.simulate(
        strategy_id="S0",
        mean_daily_return=0.0004,
        std_daily_return=0.008,
        n_days=252,
    )
    print(result["p50"], result["prob_profitable"])
"""

import random
import statistics
from spa_core.base import BaseAnalytics


class MonteCarloSimulator(BaseAnalytics):
    """
    Monte Carlo robustness tester for SPA strategies.

    Generates N synthetic daily return paths from a Gaussian distribution
    and reports percentile outcomes (P5 / P25 / P50 / P75 / P95) plus
    probabilities of profit and significant drawdown.

    Attributes:
        N_SIMULATIONS: Default number of simulation paths.
    """

    N_SIMULATIONS: int = 1000
    OUTPUT_PATH: str = "data/monte_carlo_results.json"

    def __init__(self, base_dir: str = "."):
        super().__init__(base_dir)
        self._data: dict = {
            "simulations_run": 0,
            "results": {},
        }

    # ── public API ────────────────────────────────────────────────────────────

    def simulate(
        self,
        strategy_id: str,
        mean_daily_return: float,
        std_daily_return: float,
        n_days: int = 252,
        n_sims: int = None,
        seed: int = None,
    ) -> dict:
        """
        Runs N Monte Carlo simulations for a strategy.

        Each simulation compounds daily Gaussian random returns for n_days
        and records the terminal portfolio value (starting from 1.0).

        Args:
            strategy_id:        Identifier for the strategy.
            mean_daily_return:  Mean of the daily return distribution.
            std_daily_return:   Std-dev of the daily return distribution.
            n_days:             Simulation horizon in trading days (default=252).
            n_sims:             Number of paths (default = N_SIMULATIONS = 1000).
            seed:               RNG seed for reproducibility (optional).

        Returns:
            dict with percentile results and risk metrics.
        """
        n = n_sims if n_sims is not None else self.N_SIMULATIONS
        rng = random.Random(seed)

        final_values = []
        for _ in range(n):
            portfolio_value = 1.0
            for _ in range(n_days):
                daily_return = rng.gauss(mean_daily_return, std_daily_return)
                portfolio_value *= (1.0 + daily_return)
            final_values.append(portfolio_value)

        final_values.sort()

        result = self._build_result(
            strategy_id, n, n_days, mean_daily_return, std_daily_return, final_values
        )

        self._data["results"][strategy_id] = result
        self._data["simulations_run"] += n

        # Update output path to include strategy_id in file name
        strategy_safe = strategy_id.replace("/", "_").replace(" ", "_")
        self.OUTPUT_PATH = f"data/monte_carlo_{strategy_safe}.json"
        self.save()
        return result

    def to_dict(self) -> dict:
        return self._data

    # ── internals ─────────────────────────────────────────────────────────────

    def _build_result(
        self,
        strategy_id: str,
        n: int,
        n_days: int,
        mean: float,
        std: float,
        sorted_values: list,
    ) -> dict:
        """Builds the summary dict from sorted terminal values."""

        def _pct(pct: float) -> float:
            idx = max(0, min(len(sorted_values) - 1, int(n * pct)))
            return round(sorted_values[idx], 6)

        mean_val = sum(sorted_values) / n
        std_val = statistics.stdev(sorted_values) if n > 1 else 0.0
        prob_profitable = sum(1 for v in sorted_values if v > 1.0) / n
        prob_drawdown_20 = sum(1 for v in sorted_values if v < 0.80) / n
        prob_drawdown_50 = sum(1 for v in sorted_values if v < 0.50) / n
        cagr = (mean_val ** (252.0 / n_days) - 1.0) if n_days > 0 else 0.0

        return {
            "strategy": strategy_id,
            "simulations": n,
            "n_days": n_days,
            "input_mean_daily": round(mean, 8),
            "input_std_daily": round(std, 8),
            "p5": _pct(0.05),
            "p25": _pct(0.25),
            "p50": _pct(0.50),
            "p75": _pct(0.75),
            "p95": _pct(0.95),
            "mean": round(mean_val, 6),
            "std": round(std_val, 6),
            "prob_profitable": round(prob_profitable, 4),
            "prob_drawdown_20pct": round(prob_drawdown_20, 4),
            "prob_drawdown_50pct": round(prob_drawdown_50, 4),
            "cagr_estimate": round(cagr, 4),
            "verdict": self._verdict(prob_profitable, prob_drawdown_20),
        }

    @staticmethod
    def _verdict(prob_profitable: float, prob_drawdown_20: float) -> str:
        """
        Simple go/no-go verdict.

        ROBUST   : prob_profitable >= 0.70 and prob_drawdown_20 < 0.10
        MODERATE : prob_profitable >= 0.55
        RISKY    : prob_profitable < 0.55 or prob_drawdown_20 >= 0.30
        """
        if prob_profitable >= 0.70 and prob_drawdown_20 < 0.10:
            return "ROBUST"
        if prob_profitable >= 0.55:
            return "MODERATE"
        return "RISKY"
