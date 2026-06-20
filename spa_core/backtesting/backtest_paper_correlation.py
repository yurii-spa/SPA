"""
spa_core/backtesting/backtest_paper_correlation.py

MP-1497 (v11.13) — Backtest vs paper trading correlation tracker.

Tracks Spearman rank correlation between backtest-predicted daily APY and
actual paper trading daily APY outcomes.

Key metric for GoLive readiness:
  Spearman correlation >= MIN_CORRELATION_FOR_GOLIVE (0.70) over >= 30 days.

Rules (stdlib-only, read-only domain):
  - No external dependencies
  - Atomic saves (via BaseAnalytics.save)
  - Does NOT modify allocator / risk / execution domains

Output path: data/backtest_paper_correlation.json

Usage:
    from spa_core.backtesting.backtest_paper_correlation import BacktestPaperCorrelation

    bpc = BacktestPaperCorrelation()
    bpc.add_day(predicted_apy=5.2, actual_apy=4.9, date="2026-06-10")
    # ...add more days...
    status = bpc.to_dict()
    print(status["spearman_correlation"])
    print(status["passes_threshold"])
"""

import datetime
from spa_core.base import BaseAnalytics


MIN_CORRELATION_FOR_GOLIVE: float = 0.70
MIN_DAYS_FOR_VALIDATION: int = 10   # require at least this many days before reporting corr
GOLIVE_DAYS_REQUIRED: int = 30      # days needed to satisfy the GoLive criterion


class BacktestPaperCorrelation(BaseAnalytics):
    """
    Tracks correlation between backtest predictions and paper trading actuals.

    Each call to add_day() records one day of predicted vs actual APY,
    then recalculates Spearman rank correlation over the full history.

    GoLive criterion (ADR-002 helper):
        spearman_correlation >= 0.70 over at least 30 days.
    """

    OUTPUT_PATH: str = "data/backtest_paper_correlation.json"

    def __init__(self, base_dir: str = "."):
        super().__init__(base_dir)
        self._data: dict = {
            "daily_comparisons": [],
            "days_tracked": 0,
            "spearman_correlation": None,
            "mean_absolute_error": None,
            "passes_threshold": False,
            "golive_ready": False,
            "min_correlation_threshold": MIN_CORRELATION_FOR_GOLIVE,
            "min_days_for_validation": MIN_DAYS_FOR_VALIDATION,
            "golive_days_required": GOLIVE_DAYS_REQUIRED,
        }

    # ── public API ────────────────────────────────────────────────────────────

    def add_day(
        self,
        predicted_apy: float,
        actual_apy: float,
        date: str = None,
    ) -> None:
        """
        Records one day of predicted vs actual APY comparison.

        Args:
            predicted_apy: Backtest-predicted annualised APY (%).
            actual_apy:    Actual paper-trading annualised APY (%).
            date:          ISO date string (defaults to today).
        """
        date_str = date or datetime.date.today().isoformat()
        self._data["daily_comparisons"].append({
            "date": date_str,
            "predicted": round(float(predicted_apy), 6),
            "actual": round(float(actual_apy), 6),
            "error": round(abs(float(predicted_apy) - float(actual_apy)), 6),
        })
        self._recalculate()
        self.save()

    def reset(self) -> None:
        """Clears all comparison history and resets metrics."""
        self._data["daily_comparisons"] = []
        self._data["days_tracked"] = 0
        self._data["spearman_correlation"] = None
        self._data["mean_absolute_error"] = None
        self._data["passes_threshold"] = False
        self._data["golive_ready"] = False
        self.save()

    def to_dict(self) -> dict:
        return self._data

    # ── internals ─────────────────────────────────────────────────────────────

    def _recalculate(self) -> None:
        """Recalculates all derived metrics from the comparison history."""
        comparisons = self._data["daily_comparisons"]
        n = len(comparisons)
        self._data["days_tracked"] = n

        if n < MIN_DAYS_FOR_VALIDATION:
            self._data["spearman_correlation"] = None
            self._data["mean_absolute_error"] = None
            self._data["passes_threshold"] = False
            self._data["golive_ready"] = False
            return

        predicted = [c["predicted"] for c in comparisons]
        actual = [c["actual"] for c in comparisons]

        corr = self._spearman(predicted, actual)
        mae = sum(c["error"] for c in comparisons) / n

        self._data["spearman_correlation"] = round(corr, 6)
        self._data["mean_absolute_error"] = round(mae, 6)
        self._data["passes_threshold"] = corr >= MIN_CORRELATION_FOR_GOLIVE
        self._data["golive_ready"] = (
            corr >= MIN_CORRELATION_FOR_GOLIVE and n >= GOLIVE_DAYS_REQUIRED
        )

    def _spearman(self, x: list, y: list) -> float:
        """
        Computes Spearman rank correlation coefficient.

        Pure-stdlib implementation using rank differences.
        Handles ties by averaging ranks.

        Args:
            x: First series (list of floats).
            y: Second series (list of floats).

        Returns:
            Spearman rho in [-1.0, 1.0], or 0.0 if n < 2.
        """
        n = len(x)
        if n < 2:
            return 0.0

        rank_x = self._rank(x)
        rank_y = self._rank(y)

        d_sq = sum((rank_x[i] - rank_y[i]) ** 2 for i in range(n))
        rho = 1.0 - (6.0 * d_sq) / (n * (n ** 2 - 1))
        return max(-1.0, min(1.0, rho))

    @staticmethod
    def _rank(values: list) -> list:
        """
        Assigns average ranks (handles ties).

        Args:
            values: List of numeric values.

        Returns:
            List of float ranks (1-based, with tie-averaging).
        """
        n = len(values)
        # Sort indices by value
        sorted_idx = sorted(range(n), key=lambda i: values[i])
        ranks = [0.0] * n

        i = 0
        while i < n:
            j = i
            # Find all tied values
            while j < n - 1 and values[sorted_idx[j]] == values[sorted_idx[j + 1]]:
                j += 1
            # Average rank for tied group (1-based)
            avg_rank = (i + 1 + j + 1) / 2.0
            for k in range(i, j + 1):
                ranks[sorted_idx[k]] = avg_rank
            i = j + 1

        return ranks
