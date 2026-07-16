"""
tests/test_capm_decomposition_coverage.py

MP-1468 (v10.84) — Coverage tests for spa_core/paper_trading/capm_decomposition.py
(851 lines, previously untested in tests/).

15 tests on pure mathematical functions: period_returns, flat_daily_return,
covariance, ols_capm, _compound.

stdlib-only, no external dependencies.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spa_core.analytics_lab.capm_decomposition import (
    period_returns,
    flat_daily_return,
    covariance,
    ols_capm,
    _compound,
)


# ─── period_returns ───────────────────────────────────────────────────────────


def test_01_period_returns_basic():
    """Hand example: 100→110→99 yields [0.10, -0.10]."""
    series = [("d0", 100.0), ("d1", 110.0), ("d2", 99.0)]
    result = period_returns(series)
    assert len(result) == 2
    assert abs(result[0] - 0.10) < 1e-9
    assert abs(result[1] - (99 / 110 - 1)) < 1e-9


def test_02_period_returns_empty():
    """Empty input → empty list, no error."""
    assert period_returns([]) == []


def test_03_period_returns_single():
    """Single bar → empty list (need at least 2)."""
    assert period_returns([("d0", 100.0)]) == []


def test_04_period_returns_skip_non_positive():
    """Non-positive or zero equity is skipped (no inf/nan emitted)."""
    series = [("d0", 100.0), ("d1", 0.0), ("d2", 110.0)]
    result = period_returns(series)
    for r in result:
        assert math.isfinite(r)


def test_05_period_returns_all_same():
    """Constant series → all returns are 0.0."""
    series = [("d" + str(i), 100.0) for i in range(5)]
    result = period_returns(series)
    assert len(result) == 4
    assert all(r == 0.0 for r in result)


# ─── flat_daily_return ────────────────────────────────────────────────────────


def test_06_flat_daily_return_4pct():
    """4% annual → ~1.0746e-4 daily."""
    r = flat_daily_return(4.0)
    expected = (1.04) ** (1 / 365) - 1
    assert abs(r - expected) < 1e-12


def test_07_flat_daily_return_zero_annual():
    """0% annual → 0.0 daily."""
    assert flat_daily_return(0.0) == 0.0


def test_08_flat_daily_return_zero_periods():
    """periods_per_year=0 → returns 0.0 (guard)."""
    assert flat_daily_return(4.0, periods_per_year=0) == 0.0


def test_09_flat_daily_return_positive():
    """Any positive annual rate yields a positive daily return."""
    r = flat_daily_return(10.0)
    assert r > 0.0


# ─── covariance ───────────────────────────────────────────────────────────────


def test_10_covariance_perfect_positive():
    """Identical series (corr=1) → cov = var."""
    xs = [1.0, 2.0, 3.0]
    mean = sum(xs) / len(xs)
    cov = covariance(xs, xs, mean, mean)
    # Population variance
    var = sum((x - mean) ** 2 for x in xs) / len(xs)
    assert abs(cov - var) < 1e-12


def test_11_covariance_empty():
    """Empty input → 0.0, no error."""
    assert covariance([], [], 0.0, 0.0) == 0.0


def test_12_covariance_orthogonal():
    """Orthogonal sequences have near-zero covariance."""
    xs = [1.0, -1.0, 1.0, -1.0]
    ys = [1.0, 1.0, -1.0, -1.0]
    mx, my = 0.0, 0.0
    cov = covariance(xs, ys, mx, my)
    assert abs(cov) < 1e-12


# ─── ols_capm ─────────────────────────────────────────────────────────────────


def test_13_ols_capm_returns_dict():
    """Valid inputs → dict with beta, alpha_daily, correlation, residuals."""
    rp = [0.02, -0.01, 0.03, 0.00, 0.01]
    rm = [0.01, -0.02, 0.02, 0.01, -0.01]
    result = ols_capm(rp, rm, rf_daily=0.0)
    assert result is not None
    assert "beta" in result
    assert "alpha_daily" in result
    assert "correlation" in result
    assert len(result["residuals"]) == len(rp)


def test_14_ols_capm_flat_benchmark():
    """Flat benchmark (zero variance) → returns None (beta undefined)."""
    rp = [0.01, 0.02, 0.03]
    rm = [0.00, 0.00, 0.00]  # all same → zero variance
    assert ols_capm(rp, rm, rf_daily=0.0) is None


def test_15_ols_capm_correlation_in_range():
    """Correlation must be in [-1, 1]."""
    rp = [0.01, 0.02, -0.01, 0.00, 0.03]
    rm = [0.01, 0.015, -0.005, 0.002, 0.025]
    result = ols_capm(rp, rm, rf_daily=0.0)
    assert result is not None
    assert -1.0 <= result["correlation"] <= 1.0
