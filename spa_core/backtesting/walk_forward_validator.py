"""
spa_core/backtesting/walk_forward_validator.py

MP-1495 (v11.11) — Walk-forward validation engine for SPA strategies.

Splits a historical daily-returns series into rolling train/test windows
and validates out-of-sample performance.

Rules (stdlib-only, read-only domain):
  - Training window : TRAIN_DAYS = 180 days
  - Test window     : TEST_DAYS  = 30 days
  - Step            : TEST_DAYS (non-overlapping test windows)
  - Reports         : IS vs OOS Sharpe comparison + degradation ratio

Output path: data/walk_forward_{strategy_id}.json

Usage:
    from spa_core.backtesting.walk_forward_validator import WalkForwardValidator

    wfv = WalkForwardValidator("S0")
    result = wfv.run(returns_series)  # list[float] of daily returns
    print(result["degradation_ratio"])
"""

import statistics
from spa_core.base import BaseAnalytics


class WalkForwardValidator(BaseAnalytics):
    """
    Walk-forward validation for SPA strategies.

    Splits historical data into rolling train/test windows and validates
    out-of-sample performance by comparing Sharpe ratios.

    Attributes:
        TRAIN_DAYS: Length of in-sample training window (days).
        TEST_DAYS:  Length of out-of-sample test window (days).
    """

    TRAIN_DAYS: int = 180
    TEST_DAYS: int = 30

    def __init__(self, strategy_id: str, base_dir: str = "."):
        super().__init__(base_dir)
        self.strategy_id = strategy_id
        self.OUTPUT_PATH = f"data/walk_forward_{strategy_id}.json"
        self._data: dict = {
            "strategy": strategy_id,
            "train_days": self.TRAIN_DAYS,
            "test_days": self.TEST_DAYS,
            "n_windows": 0,
            "windows": [],
            "is_sharpe_avg": 0.0,
            "oos_sharpe_avg": 0.0,
            "degradation_ratio": 1.0,
            "verdict": "INSUFFICIENT_DATA",
        }

    # ── public API ────────────────────────────────────────────────────────────

    def run(self, returns_series: list) -> dict:
        """
        Runs walk-forward validation on a provided daily returns series.

        Args:
            returns_series: List of daily returns (floats), e.g. [0.0003, -0.0001, ...].

        Returns:
            Summary dict with IS/OOS performance comparison.
        """
        windows = self._create_windows(returns_series)
        results = []

        for i, (train, test) in enumerate(windows):
            is_sharpe = self._sharpe(train)
            oos_sharpe = self._sharpe(test)
            degradation = (
                oos_sharpe / is_sharpe if is_sharpe > 0 else 0.0
            )
            results.append({
                "window": i + 1,
                "train_days": len(train),
                "test_days": len(test),
                "is_sharpe": round(is_sharpe, 4),
                "oos_sharpe": round(oos_sharpe, 4),
                "degradation": round(degradation, 4),
            })

        self._data["n_windows"] = len(results)
        self._data["windows"] = results

        if results:
            is_avg = sum(r["is_sharpe"] for r in results) / len(results)
            oos_avg = sum(r["oos_sharpe"] for r in results) / len(results)
            self._data["is_sharpe_avg"] = round(is_avg, 4)
            self._data["oos_sharpe_avg"] = round(oos_avg, 4)
            self._data["degradation_ratio"] = (
                round(oos_avg / is_avg, 4) if is_avg > 0 else 0.0
            )
            self._data["verdict"] = self._verdict()
        else:
            self._data["verdict"] = "INSUFFICIENT_DATA"

        self.save()
        return self._data

    def to_dict(self) -> dict:
        return self._data

    # ── internals ─────────────────────────────────────────────────────────────

    def _create_windows(self, series: list) -> list:
        """
        Generates non-overlapping (train, test) window pairs.

        Each step advances by TEST_DAYS; training windows may overlap
        but test windows never do.
        """
        windows = []
        total = len(series)
        start = 0
        while start + self.TRAIN_DAYS + self.TEST_DAYS <= total:
            train = series[start: start + self.TRAIN_DAYS]
            test = series[
                start + self.TRAIN_DAYS: start + self.TRAIN_DAYS + self.TEST_DAYS
            ]
            windows.append((train, test))
            start += self.TEST_DAYS
        return windows

    def _sharpe(
        self,
        returns: list,
        risk_free_daily: float = 0.05 / 252,
    ) -> float:
        """
        Annualised Sharpe ratio from a daily returns list.

        Args:
            returns: Daily return floats.
            risk_free_daily: Daily risk-free rate (default = 5 % / 252).

        Returns:
            Annualised Sharpe ratio, or 0.0 if too few data points.
        """
        if len(returns) < 2:
            return 0.0
        avg = sum(returns) / len(returns) - risk_free_daily
        std = statistics.stdev(returns)
        if std <= 0:
            return 0.0
        return (avg / std) * (252 ** 0.5)

    def _verdict(self) -> str:
        """
        Human-readable verdict based on degradation_ratio and OOS Sharpe.

        Thresholds:
          STRONG   : degradation >= 0.70 and oos_sharpe_avg > 0
          MODERATE : degradation >= 0.40 and oos_sharpe_avg > 0
          WEAK     : oos_sharpe_avg > 0 but degradation < 0.40
          NEGATIVE : oos_sharpe_avg <= 0
        """
        dr = self._data["degradation_ratio"]
        oos = self._data["oos_sharpe_avg"]
        if oos <= 0:
            return "NEGATIVE_OOS"
        if dr >= 0.70:
            return "STRONG"
        if dr >= 0.40:
            return "MODERATE"
        return "WEAK"
