"""
spa_core/backtesting/tournament_runner_v2.py — MP-1512 Tournament Runner v2

Tournament Runner v2 — ranks all strategies by Sharpe ratio.
=============================================================
Runs daily evaluation on all tournament strategies (S0–S21+).
Outputs a ranked leaderboard with promotion/demotion recommendations.

Features vs v1:
  - Sharpe-ranked leaderboard (annualised, 252-day convention)
  - Promotion pipeline: Sharpe ≥ 1.5 + days ≥ 7 → promotions_pending
  - Demotion pipeline: Sharpe < 0.5 for 5+ days → demotions_pending
  - Calmar ratio computed alongside Sharpe
  - Atomic JSON save via BaseAnalytics.save()
  - All metrics: sharpe, calmar, max_drawdown, annualized_return,
                 volatility, avg_daily_return, days, win_rate

Constraints:
  - Extends BaseAnalytics (spa_core/base.py) — atomic save, stdlib only
  - LLM FORBIDDEN in this module
  - No external dependencies
  - Advisory / read-only — never modifies allocator, risk, or execution

ADR: ADR-023 (promotion/demotion policy)
Date: 2026-06-20 (MP-1512, Sprint v11.28)
"""
from __future__ import annotations

import datetime
import statistics
from typing import Dict, List, Optional

from spa_core.base import BaseAnalytics


# ─── Constants ────────────────────────────────────────────────────────────────

OUTPUT_PATH = "data/tournament_runner_v2.json"

# Promotion thresholds (ADR-023)
PROMOTION_SHARPE_MIN: float = 1.5     # Sharpe ≥ 1.5 to qualify for promotion
PROMOTION_DAYS_MIN: int = 7           # Must have at least 7 days of returns

# Demotion thresholds
DEMOTION_SHARPE_FLOOR: float = 0.5   # Sharpe < 0.5 counts as a "bad" evaluation
DEMOTION_CONSECUTIVE: int = 5        # 5 consecutive bad days → demote

# Annualisation factor (daily → annual)
ANNUALISE_FACTOR: float = 252.0 ** 0.5


# ─── TournamentRunnerV2 ───────────────────────────────────────────────────────

class TournamentRunnerV2(BaseAnalytics):
    """
    Tournament Runner v2 — manages strategy tournament and promotion pipeline.

    Usage:
        runner = TournamentRunnerV2(base_dir=".")
        result = runner.run_evaluation(strategy_returns)
        # result["leaderboard"] → sorted list of strategy metrics

    Args for run_evaluation:
        strategy_returns: dict mapping strategy_id → list[float] of daily returns
                          e.g. {"S7": [0.0003, 0.0004, ...], "S11": [...]}

    The in_production flag can be passed per-strategy via in_production_set:
        runner.run_evaluation(returns, in_production_set={"S7", "S11"})
    """

    OUTPUT_PATH = OUTPUT_PATH

    PROMOTION_SHARPE_MIN = PROMOTION_SHARPE_MIN
    PROMOTION_DAYS_MIN = PROMOTION_DAYS_MIN
    DEMOTION_SHARPE_FLOOR = DEMOTION_SHARPE_FLOOR
    DEMOTION_CONSECUTIVE = DEMOTION_CONSECUTIVE

    def __init__(self, base_dir: str = ".") -> None:
        super().__init__(base_dir)
        self._data: dict = {
            "leaderboard": [],
            "promotions_pending": [],
            "demotions_pending": [],
            "last_run": None,
            "runner_version": "v2",
        }
        # Consecutive bad-day counters per strategy: {strategy_id → int}
        self._bad_day_streak: Dict[str, int] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def run_evaluation(
        self,
        strategy_returns: Dict[str, List[float]],
        in_production_set: Optional[set] = None,
        save: bool = True,
    ) -> dict:
        """
        Evaluates all strategies and updates leaderboard.

        Args:
            strategy_returns:  {strategy_id: [daily_return, ...]}  (fraction per day)
            in_production_set: set of strategy IDs already in production (skip promotion)
            save:              If True, atomically save to OUTPUT_PATH.

        Returns:
            Full result dict with: leaderboard, promotions_pending, demotions_pending,
            last_run, runner_version, strategy_count.
        """
        in_production_set = in_production_set or set()
        results: List[dict] = []

        for strategy_id, returns in strategy_returns.items():
            if returns is None:
                continue
            metrics = self._calculate_metrics(strategy_id, list(returns))
            metrics["in_production"] = strategy_id in in_production_set
            results.append(metrics)

        # Sort leaderboard by Sharpe ratio descending (ties: by annualised return)
        self._data["leaderboard"] = sorted(
            results,
            key=lambda x: (x.get("sharpe", 0.0), x.get("annualized_return", 0.0)),
            reverse=True,
        )

        # Promotion candidates: Sharpe ≥ threshold, days ≥ threshold, not already in production
        self._data["promotions_pending"] = [
            r for r in results
            if r.get("days", 0) >= PROMOTION_DAYS_MIN
            and r.get("sharpe", 0.0) >= PROMOTION_SHARPE_MIN
            and not r.get("in_production", False)
        ]

        # Demotion candidates: update consecutive bad-day counter
        demotion_candidates: List[dict] = []
        for r in results:
            sid = r["strategy_id"]
            is_bad = r.get("sharpe", 1.0) < DEMOTION_SHARPE_FLOOR
            if is_bad:
                self._bad_day_streak[sid] = self._bad_day_streak.get(sid, 0) + 1
            else:
                self._bad_day_streak[sid] = 0

            if self._bad_day_streak.get(sid, 0) >= DEMOTION_CONSECUTIVE and r.get("in_production", False):
                r_copy = dict(r)
                r_copy["consecutive_bad_days"] = self._bad_day_streak[sid]
                demotion_candidates.append(r_copy)

        self._data["demotions_pending"] = demotion_candidates
        self._data["last_run"] = datetime.datetime.utcnow().isoformat() + "Z"
        self._data["strategy_count"] = len(results)

        if save:
            self.save(self._data)

        return dict(self._data)

    def leaderboard(self) -> List[dict]:
        """Returns current ranked leaderboard (most recent evaluation)."""
        return list(self._data.get("leaderboard", []))

    def promotions_pending(self) -> List[dict]:
        """Returns strategies pending promotion after last evaluation."""
        return list(self._data.get("promotions_pending", []))

    def demotions_pending(self) -> List[dict]:
        """Returns strategies pending demotion after last evaluation."""
        return list(self._data.get("demotions_pending", []))

    def reset_streak(self, strategy_id: str) -> None:
        """Resets the consecutive bad-day counter for a strategy (e.g., after demotion)."""
        self._bad_day_streak[strategy_id] = 0

    def to_dict(self) -> dict:
        """Returns current runner state as JSON-serialisable dict."""
        return dict(self._data)

    def analyze(self, strategy_returns: Optional[Dict[str, List[float]]] = None,
                *args, **kwargs) -> dict:
        """BaseAnalytics contract — evaluates strategies and returns the result dict."""
        return self.run_evaluation(strategy_returns or {}, *args, **kwargs)

    # ── Metrics computation ───────────────────────────────────────────────────

    def _calculate_metrics(self, strategy_id: str, returns: List[float]) -> dict:
        """
        Computes full metric set for one strategy.

        Metrics returned:
          strategy_id, days, avg_daily_return, volatility,
          sharpe, annualized_return, max_drawdown, calmar, win_rate.

        Args:
            strategy_id: Identifier string.
            returns:     List of daily returns (fractions).

        Returns:
            Metrics dict (all float fields ≥ 0 except max_drawdown which is ≤ 0).
        """
        days = len(returns)
        base: dict = {
            "strategy_id": strategy_id,
            "days": days,
            "avg_daily_return": 0.0,
            "volatility": 0.0,
            "sharpe": 0.0,
            "annualized_return": 0.0,
            "max_drawdown": 0.0,
            "calmar": 0.0,
            "win_rate": 0.0,
        }

        if days == 0:
            return base

        avg = sum(returns) / days
        base["avg_daily_return"] = round(avg, 8)
        base["annualized_return"] = round(avg * ANNUALISE_FACTOR * ANNUALISE_FACTOR, 6)  # avg * 252

        # Win rate: fraction of days with positive return
        wins = sum(1 for r in returns if r > 0)
        base["win_rate"] = round(wins / days, 4) if days > 0 else 0.0

        if days < 2:
            return base

        std = statistics.stdev(returns)
        base["volatility"] = round(std, 8)

        # Annualised Sharpe (risk-free rate = 0, SPA paper-trading convention)
        if std > 0:
            sharpe = (avg / std) * ANNUALISE_FACTOR
            base["sharpe"] = round(sharpe, 4)

        # Max drawdown
        max_dd = self._max_drawdown(returns)
        base["max_drawdown"] = round(max_dd, 6)

        # Calmar = annualized_return / |max_drawdown|
        if max_dd < 0:
            calmar = base["annualized_return"] / abs(max_dd)
            base["calmar"] = round(calmar, 4)
        elif max_dd == 0 and base["annualized_return"] > 0:
            base["calmar"] = float("inf")  # No drawdown — perfect

        return base

    @staticmethod
    def _max_drawdown(returns: List[float]) -> float:
        """
        Computes maximum drawdown from a list of daily returns.

        Uses NAV simulation starting at 1.0.

        Args:
            returns: Daily returns list (fractions).

        Returns:
            Max drawdown as a negative fraction (e.g. -0.05 = -5%).
            Returns 0.0 if returns is empty or no drawdown occurred.
        """
        if not returns:
            return 0.0

        nav = 1.0
        peak = 1.0
        max_dd = 0.0

        for r in returns:
            nav *= (1.0 + r)
            if nav > peak:
                peak = nav
            dd = (peak - nav) / peak
            if dd > max_dd:
                max_dd = dd

        return -max_dd  # return as negative fraction

    # ── Ranking helpers ───────────────────────────────────────────────────────

    def rank_by(self, metric: str, ascending: bool = False) -> List[dict]:
        """
        Returns leaderboard re-ranked by any numeric metric field.

        Args:
            metric:    Key to sort by (e.g. "sharpe", "annualized_return").
            ascending: True for lowest-first (e.g. "max_drawdown").

        Returns:
            Sorted copy of the leaderboard list.
        """
        lb = self.leaderboard()
        return sorted(lb, key=lambda x: x.get(metric, 0.0), reverse=not ascending)

    def top_n(self, n: int = 5, metric: str = "sharpe") -> List[dict]:
        """
        Returns top-N strategies by a given metric.

        Args:
            n:      Number of top entries to return.
            metric: Metric to rank by (default: "sharpe").

        Returns:
            List of up to n strategy metric dicts.
        """
        ranked = self.rank_by(metric, ascending=False)
        return ranked[:n]

    def get_strategy_metrics(self, strategy_id: str) -> Optional[dict]:
        """
        Returns metrics dict for a specific strategy from current leaderboard.

        Args:
            strategy_id: Strategy identifier.

        Returns:
            Metrics dict or None if not found.
        """
        for entry in self._data.get("leaderboard", []):
            if entry.get("strategy_id") == strategy_id:
                return dict(entry)
        return None
