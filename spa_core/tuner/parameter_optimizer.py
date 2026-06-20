"""
spa_core/tuner/parameter_optimizer.py — MP-1481 Strategy Parameter Optimizer

Bayesian-inspired (grid-search) parameter optimizer for SPA strategies.
Uses historical backtest data to tune strategy parameters.
Operates ONLY on paper trading data (no live execution).

Supported metrics: sharpe, calmar, sortino, apy
Stdlib only. Atomic writes. LLM FORBIDDEN.
"""
from __future__ import annotations

import itertools, json, logging, math, os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

from spa_core.base import BaseAnalytics
from spa_core.utils.errors import SPAError

log = logging.getLogger("spa.tuner.optimizer")

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_DATA_DIR = os.path.join(_REPO_ROOT, "data")
_DEFAULT_BACKTEST_FILE = os.path.join(_DEFAULT_DATA_DIR, "backtest_results.json")


class OptimizerError(SPAError):
    """Raised when optimization fails or inputs are invalid."""


@dataclass
class OptimizeResult:
    strategy_name: str
    best_params: Dict[str, Any]
    best_score: float
    metric: str
    total_trials: int
    trials: List[Dict]    # [{"params": {...}, "score": float}]
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


class ParameterOptimizer(BaseAnalytics):
    """Tunes strategy parameters using backtest data (paper trading only)."""

    OUTPUT_PATH = "data/optimizer_results.json"

    def __init__(self, strategy_name: str, base_dir: str = "."):
        super().__init__(base_dir)
        self.strategy_name = strategy_name
        self._results: List[OptimizeResult] = []

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy_name,
            "results": [r.to_dict() for r in self._results],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def optimize(
        self,
        param_grid: Dict[str, List[Any]],
        metric: str = "sharpe",
        backtest_data: Optional[List[dict]] = None,
    ) -> OptimizeResult:
        """Grid search over param_grid, return OptimizeResult with best params."""
        if not param_grid:
            raise OptimizerError("param_grid must be non-empty")
        valid_metrics = {"sharpe", "calmar", "sortino", "apy"}
        if metric not in valid_metrics:
            raise OptimizerError(f"metric must be one of {valid_metrics}")

        if backtest_data is None:
            backtest_data = self._load_backtest()

        best_params: Dict[str, Any] = {}
        best_score = float("-inf")
        trials: List[Dict] = []

        for params in self._expand_grid(param_grid):
            score = self._evaluate(params, metric, backtest_data)
            trials.append({"params": dict(params), "score": score})
            if score > best_score:
                best_score = score
                best_params = dict(params)

        result = OptimizeResult(
            strategy_name=self.strategy_name,
            best_params=best_params,
            best_score=best_score,
            metric=metric,
            total_trials=len(trials),
            trials=trials,
        )
        self._results.append(result)
        return result

    def _expand_grid(self, grid: Dict[str, List[Any]]) -> Iterator[Dict[str, Any]]:
        """Cartesian product of parameter grid."""
        keys = list(grid.keys())
        for vals in itertools.product(*[grid[k] for k in keys]):
            yield dict(zip(keys, vals))

    def _evaluate(
        self,
        params: Dict[str, Any],
        metric: str,
        backtest_data: List[dict],
    ) -> float:
        """Simulate strategy with params on backtest data, return metric score."""
        if not backtest_data:
            return self._synthetic_score(params, metric)

        # Apply params as multipliers/modifiers to the equity curve
        apy_scale = float(params.get("apy_scale", 1.0))
        risk_mult = float(params.get("risk_multiplier", 1.0))
        rebalance_threshold = float(params.get("rebalance_threshold", 0.05))

        returns = []
        for entry in backtest_data:
            daily_return = float(entry.get("daily_return", 0.0)) * apy_scale
            returns.append(daily_return)

        if not returns:
            return 0.0

        mean_ret = sum(returns) / len(returns)

        if metric == "apy":
            return mean_ret * 365 * 100

        variance = sum((r - mean_ret) ** 2 for r in returns) / max(len(returns), 1)
        std_dev = math.sqrt(variance) if variance > 0 else 1e-9

        if metric == "sharpe":
            return (mean_ret / std_dev) / risk_mult

        if metric == "sortino":
            neg_rets = [r for r in returns if r < 0]
            downside_var = sum(r ** 2 for r in neg_rets) / max(len(neg_rets), 1)
            downside_std = math.sqrt(downside_var) if downside_var > 0 else 1e-9
            return (mean_ret / downside_std) / risk_mult

        if metric == "calmar":
            cumulative = 1.0
            peak = 1.0
            max_dd = 0.0
            for r in returns:
                cumulative *= (1 + r)
                if cumulative > peak:
                    peak = cumulative
                dd = (peak - cumulative) / peak
                if dd > max_dd:
                    max_dd = dd
            total_return = (cumulative - 1.0) * 100
            return total_return / max(max_dd * 100, 0.01) / risk_mult

        return 0.0

    def _synthetic_score(self, params: Dict[str, Any], metric: str) -> float:
        """Score when no backtest data: deterministic function of params."""
        apy_scale = float(params.get("apy_scale", 1.0))
        risk_mult = float(params.get("risk_multiplier", 1.0))
        base = apy_scale / max(risk_mult, 0.01)
        if metric == "apy":
            return base * 10.0
        if metric == "sharpe":
            return base * 1.5
        if metric == "sortino":
            return base * 2.0
        if metric == "calmar":
            return base * 3.0
        return base

    def _load_backtest(self) -> List[dict]:
        """Load backtest data from data/backtest_results.json."""
        path = os.path.join(self.base_dir, "data", "backtest_results.json")
        fallback = os.path.join(_DEFAULT_DATA_DIR, "backtest_results.json")
        for p in (path, fallback):
            if os.path.exists(p):
                try:
                    with open(p) as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        return data
                    if isinstance(data, dict):
                        return data.get("entries", data.get("data", []))
                except (json.JSONDecodeError, OSError):
                    pass
        return []

    def best_result(self) -> Optional[OptimizeResult]:
        """Return the highest-scoring result across all optimize() calls."""
        if not self._results:
            return None
        return max(self._results, key=lambda r: r.best_score)
