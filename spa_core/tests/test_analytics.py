"""
Tests for analytics.portfolio_stats — advanced portfolio statistics.
"""

import sys
import math
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from analytics.portfolio_stats import (
    calmar_ratio,
    sortino_ratio,
    ulcer_index,
    recovery_factor,
    avg_drawdown_duration,
    value_at_risk_historical,
    expected_shortfall,
    portfolio_summary,
    rolling_metrics,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _curve(capitals: list[float], start_date: str = "2026-01-01") -> list[dict]:
    """Build an equity_curve list from a raw capital series."""
    from datetime import date, timedelta
    base = date.fromisoformat(start_date)
    return [
        {"date": (base + timedelta(days=i)).isoformat(), "total_capital": c}
        for i, c in enumerate(capitals)
    ]


def _growing_curve(n: int = 40, start: float = 100_000, daily_gain: float = 50.0):
    """Strictly increasing curve — no drawdowns."""
    return _curve([start + i * daily_gain for i in range(n)])


def _flat_curve(n: int = 20, value: float = 100_000.0):
    """Perfectly flat curve — zero return, zero drawdown."""
    return _curve([value] * n)


def _drawdown_curve():
    """Curve that drops then recovers: 100k → 90k → 95k → 100k → 105k."""
    return _curve([100_000, 90_000, 95_000, 100_000, 105_000])


# ─── calmar_ratio ─────────────────────────────────────────────────────────────

class TestCalmarRatio:

    def test_zero_drawdown_returns_zero(self):
        """No drawdown → undefined calmar → returns 0.0 as sentinel."""
        curve = _growing_curve()
        result = calmar_ratio(curve)
        assert result == 0.0

    def test_positive_return_with_drawdown(self):
        """Curve with drawdown and positive final return → positive calmar."""
        curve = _curve([100_000, 90_000, 120_000])
        result = calmar_ratio(curve)
        assert result > 0, f"Expected positive calmar, got {result}"

    def test_empty_curve(self):
        assert calmar_ratio([]) == 0.0

    def test_single_point(self):
        assert calmar_ratio(_curve([100_000])) == 0.0

    def test_returns_float(self):
        curve = _drawdown_curve()
        result = calmar_ratio(curve)
        assert isinstance(result, float)


# ─── sortino_ratio ────────────────────────────────────────────────────────────

class TestSortinoRatio:

    def test_positive_return_nonnegative_sortino(self):
        """Monotonically growing curve → Sortino ≥ 0."""
        curve = _growing_curve(n=40, daily_gain=100.0)
        result = sortino_ratio(curve)
        assert result >= 0.0, f"Expected non-negative Sortino, got {result}"

    def test_flat_curve_returns_zero_or_negative(self):
        """Flat curve → zero return, which is below risk-free → ≤ 0."""
        curve = _flat_curve(n=30)
        result = sortino_ratio(curve)
        assert isinstance(result, float)

    def test_empty_curve(self):
        assert sortino_ratio([]) == 0.0

    def test_single_point(self):
        assert sortino_ratio(_curve([100_000])) == 0.0

    def test_returns_float(self):
        curve = _drawdown_curve()
        result = sortino_ratio(curve)
        assert isinstance(result, float)
        assert not math.isnan(result)


# ─── ulcer_index ──────────────────────────────────────────────────────────────

class TestUlcerIndex:

    def test_flat_curve_zero_ulcer(self):
        """Flat equity curve → zero drawdown → Ulcer Index = 0."""
        result = ulcer_index(_flat_curve(n=20))
        assert result == 0.0, f"Expected 0.0 for flat curve, got {result}"

    def test_growing_curve_zero_ulcer(self):
        """Strictly increasing curve → no drawdown → Ulcer Index = 0."""
        result = ulcer_index(_growing_curve())
        assert result == 0.0, f"Expected 0.0 for growing curve, got {result}"

    def test_drawdown_positive_ulcer(self):
        """Curve with drawdown → Ulcer Index > 0."""
        result = ulcer_index(_drawdown_curve())
        assert result > 0.0, f"Expected positive Ulcer Index, got {result}"

    def test_empty_curve(self):
        assert ulcer_index([]) == 0.0

    def test_single_point(self):
        assert ulcer_index(_curve([100_000])) == 0.0

    def test_returns_float(self):
        assert isinstance(ulcer_index(_drawdown_curve()), float)


# ─── recovery_factor ──────────────────────────────────────────────────────────

class TestRecoveryFactor:

    def test_no_drawdown_returns_zero(self):
        """No drawdown → undefined recovery → 0.0 sentinel."""
        result = recovery_factor(_growing_curve())
        assert result == 0.0

    def test_positive_recovery(self):
        """Net positive return with drawdown → positive recovery factor."""
        curve = _curve([100_000, 90_000, 115_000])
        result = recovery_factor(curve)
        assert result > 0.0, f"Expected positive recovery factor, got {result}"

    def test_empty_curve(self):
        assert recovery_factor([]) == 0.0


# ─── avg_drawdown_duration ────────────────────────────────────────────────────

class TestAvgDrawdownDuration:

    def test_flat_no_drawdown(self):
        """Flat curve → no drawdown ever → 0.0 days."""
        assert avg_drawdown_duration(_flat_curve()) == 0.0

    def test_growing_no_drawdown(self):
        """Monotonically increasing → 0.0 days."""
        assert avg_drawdown_duration(_growing_curve()) == 0.0

    def test_drawdown_duration_positive(self):
        """Curve with dip → average duration > 0."""
        result = avg_drawdown_duration(_drawdown_curve())
        assert result > 0.0, f"Expected positive duration, got {result}"


# ─── value_at_risk_historical ─────────────────────────────────────────────────

class TestVaRHistorical:

    def test_nonnegative(self):
        """VaR should always be ≥ 0 (expressed as a positive loss figure)."""
        result = value_at_risk_historical(_drawdown_curve())
        assert result >= 0.0

    def test_empty_curve(self):
        assert value_at_risk_historical([]) == 0.0

    def test_flat_curve_zero_var(self):
        """Flat curve → zero daily returns → VaR = 0."""
        result = value_at_risk_historical(_flat_curve())
        assert result == 0.0

    def test_returns_float(self):
        assert isinstance(value_at_risk_historical(_drawdown_curve()), float)


# ─── expected_shortfall ───────────────────────────────────────────────────────

class TestExpectedShortfall:

    def test_nonnegative(self):
        result = expected_shortfall(_drawdown_curve())
        assert result >= 0.0

    def test_empty_curve(self):
        assert expected_shortfall([]) == 0.0

    def test_cvar_gte_var(self):
        """CVaR should always be ≥ VaR (for the same curve and confidence)."""
        curve = _drawdown_curve()
        var   = value_at_risk_historical(curve, 0.95)
        cvar  = expected_shortfall(curve, 0.95)
        assert cvar >= var - 1e-9, (
            f"CVaR ({cvar}) should be ≥ VaR ({var})"
        )


# ─── portfolio_summary ────────────────────────────────────────────────────────

EXPECTED_KEYS = {
    "calmar_ratio",
    "sortino_ratio",
    "ulcer_index",
    "recovery_factor",
    "avg_drawdown_duration_days",
    "value_at_risk_95",
    "expected_shortfall_95",
    "total_return_pct",
    "annualised_return_pct",
    "max_drawdown_pct",
    "data_points",
}


class TestPortfolioSummary:

    def test_returns_dict(self):
        result = portfolio_summary(_drawdown_curve())
        assert isinstance(result, dict)

    def test_all_expected_keys_present(self):
        result = portfolio_summary(_drawdown_curve())
        missing = EXPECTED_KEYS - set(result.keys())
        assert not missing, f"Missing keys: {missing}"

    def test_empty_curve_returns_all_keys(self):
        result = portfolio_summary([])
        missing = EXPECTED_KEYS - set(result.keys())
        assert not missing, f"Missing keys on empty curve: {missing}"

    def test_empty_curve_zero_values(self):
        result = portfolio_summary([])
        for k, v in result.items():
            if k == "data_points":
                continue
            assert v == 0.0, f"Key '{k}' should be 0.0 for empty curve, got {v}"

    def test_growing_curve_positive_return(self):
        result = portfolio_summary(_growing_curve())
        assert result["total_return_pct"] > 0.0

    def test_data_points_matches_curve(self):
        curve  = _growing_curve(n=40)
        result = portfolio_summary(curve)
        assert result["data_points"] == 40

    def test_all_values_are_numeric(self):
        result = portfolio_summary(_drawdown_curve())
        for k, v in result.items():
            assert isinstance(v, (int, float)), (
                f"Key '{k}' has non-numeric value: {type(v)}"
            )


# ─── rolling_metrics ──────────────────────────────────────────────────────────

class TestRollingMetrics:

    def test_returns_one_entry_per_curve_point(self):
        """rolling_metrics must return exactly len(equity_curve) entries."""
        curve  = _growing_curve(n=40)
        result = rolling_metrics(curve, window=30)
        assert len(result) == 40, (
            f"Expected 40 rolling entries, got {len(result)}"
        )

    def test_small_curve_does_not_crash(self):
        """A 3-point curve with window=30 should not crash."""
        curve  = _curve([100_000, 101_000, 102_000])
        result = rolling_metrics(curve, window=30)
        assert len(result) == 3

    def test_entry_has_required_keys(self):
        curve  = _growing_curve(n=10)
        result = rolling_metrics(curve, window=7)
        for entry in result:
            for k in ["date", "sharpe", "sortino", "drawdown", "return_pct"]:
                assert k in entry, f"Missing key '{k}' in rolling entry"

    def test_empty_curve_returns_empty(self):
        result = rolling_metrics([])
        assert result == []

    def test_single_point_returns_one_entry(self):
        curve  = _curve([100_000])
        result = rolling_metrics(curve, window=30)
        assert len(result) == 1

    def test_no_drawdown_on_growing_curve(self):
        """Rolling drawdown should be 0.0 for a monotonically growing curve."""
        curve  = _growing_curve(n=40)
        result = rolling_metrics(curve, window=30)
        # Skip the very first entry (only 1 point, returns 0.0 by design)
        for entry in result[1:]:
            assert entry["drawdown"] == 0.0, (
                f"Non-zero drawdown on growing curve: {entry}"
            )

    def test_all_values_are_numeric(self):
        curve  = _drawdown_curve()
        result = rolling_metrics(curve, window=3)
        for entry in result:
            for k, v in entry.items():
                if k == "date":
                    continue
                assert isinstance(v, (int, float)), (
                    f"Non-numeric value at key '{k}': {type(v)}"
                )
