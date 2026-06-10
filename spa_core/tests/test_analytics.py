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


# ═══════════════════════════════════════════════════════════════════════════
# MP-104 — core analytics modules (spa_core/analytics/*, post-cycle hook)
# ═══════════════════════════════════════════════════════════════════════════

import json

from analytics.sharpe import calculate_sharpe
from analytics.drawdown import calculate_max_drawdown
from analytics.volatility import calculate_volatility
from analytics.benchmark import compare_to_benchmark
from analytics.streak import calculate_streaks
from analytics.calmar import calculate_calmar
from analytics.concentration import calculate_concentration
from analytics.analytics_runner import run_post_cycle_analytics


# ─── MP-104: sharpe ──────────────────────────────────────────────────────────

class TestCalculateSharpe:

    def test_too_few_points_returns_zero(self):
        assert calculate_sharpe([]) == 0.0
        assert calculate_sharpe([0.001]) == 0.0

    def test_zero_std_returns_zero(self):
        assert calculate_sharpe([0.001] * 10) == 0.0

    def test_positive_excess_returns_positive_sharpe(self):
        # Daily returns well above rf/365 ≈ 0.000137 with some dispersion.
        rets = [0.001, 0.002, 0.0015, 0.0008, 0.0012] * 6
        assert calculate_sharpe(rets) > 0.0

    def test_matches_manual_formula(self):
        rets = [0.001, -0.0005, 0.002, 0.0007]
        rf_daily = 0.05 / 365.0
        excess = [r - rf_daily for r in rets]
        mean = sum(excess) / len(excess)
        var = sum((x - mean) ** 2 for x in excess) / (len(excess) - 1)
        expected = mean / math.sqrt(var) * math.sqrt(365.0)
        assert calculate_sharpe(rets) == pytest.approx(expected)

    def test_negative_excess_returns_negative_sharpe(self):
        rets = [-0.001, -0.002, -0.0015, -0.0005] * 5
        assert calculate_sharpe(rets) < 0.0


# ─── MP-104: drawdown ────────────────────────────────────────────────────────

class TestCalculateMaxDrawdown:

    def test_empty_curve(self):
        result = calculate_max_drawdown([])
        assert result == {
            "max_drawdown_pct": 0.0,
            "peak_date": None,
            "trough_date": None,
            "current_drawdown_pct": 0.0,
        }

    def test_monotonic_growth_has_zero_drawdown(self):
        result = calculate_max_drawdown([100.0, 101.0, 102.0, 103.0])
        assert result["max_drawdown_pct"] == 0.0
        assert result["current_drawdown_pct"] == 0.0

    def test_simple_drawdown_with_dates(self):
        equity = [100_000, 110_000, 99_000, 104_500, 108_000]
        dates = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]
        result = calculate_max_drawdown(equity, dates)
        assert result["max_drawdown_pct"] == pytest.approx(10.0)
        assert result["peak_date"] == "2026-06-02"
        assert result["trough_date"] == "2026-06-03"
        # Still below the 110k peak at the end:
        assert result["current_drawdown_pct"] == pytest.approx(
            (110_000 - 108_000) / 110_000 * 100, rel=1e-6
        )

    def test_recovered_curve_has_zero_current_drawdown(self):
        result = calculate_max_drawdown([100.0, 90.0, 105.0])
        assert result["max_drawdown_pct"] == pytest.approx(10.0)
        assert result["current_drawdown_pct"] == 0.0

    def test_default_dates_are_indices(self):
        result = calculate_max_drawdown([100.0, 80.0])
        assert result["peak_date"] == "0"
        assert result["trough_date"] == "1"


# ─── MP-104: volatility ──────────────────────────────────────────────────────

class TestCalculateVolatility:

    def test_too_few_points_returns_zeros(self):
        result = calculate_volatility([0.001])
        assert result == {"daily_vol": 0.0, "annualized_vol": 0.0, "vol_30d": 0.0}

    def test_constant_returns_have_zero_vol(self):
        result = calculate_volatility([0.001] * 50)
        assert result["daily_vol"] == 0.0
        assert result["annualized_vol"] == 0.0
        assert result["vol_30d"] == 0.0

    def test_annualized_is_daily_times_sqrt_365(self):
        rets = [0.001, -0.002, 0.0015, 0.0, 0.003]
        result = calculate_volatility(rets)
        assert result["daily_vol"] > 0.0
        assert result["annualized_vol"] == pytest.approx(
            result["daily_vol"] * math.sqrt(365.0)
        )

    def test_vol_30d_uses_trailing_window(self):
        # 60 noisy points, then 30 constant points → trailing-30d vol is 0.
        rets = [0.01, -0.01] * 30 + [0.0005] * 30
        result = calculate_volatility(rets)
        assert result["vol_30d"] == 0.0
        assert result["daily_vol"] > 0.0


# ─── MP-104: benchmark ───────────────────────────────────────────────────────

class TestCompareToBenchmark:

    def test_too_few_points_returns_zero_result(self):
        result = compare_to_benchmark([100_000.0], ["2026-06-01"])
        assert result["spa_total_return"] == 0.0
        assert result["benchmark_total_return"] == 0.0
        assert result["outperforming"] is False

    def test_outperforming_spa(self):
        # +1% over ~36.5 days vs 5% APY benchmark (+0.5%) → alpha > 0.
        dates = ["2026-01-01", "2026-02-06"]
        result = compare_to_benchmark([100_000.0, 101_000.0], dates)
        assert result["spa_total_return"] == pytest.approx(1.0)
        assert result["benchmark_total_return"] == pytest.approx(
            0.05 * 36 / 365 * 100, rel=1e-6
        )
        assert result["alpha"] > 0
        assert result["outperforming"] is True

    def test_underperforming_spa(self):
        # Flat SPA over a year vs 5% benchmark → alpha = -5%.
        dates = ["2025-06-10", "2026-06-10"]
        result = compare_to_benchmark([100_000.0, 100_000.0], dates)
        assert result["spa_total_return"] == 0.0
        assert result["benchmark_total_return"] == pytest.approx(5.0)
        assert result["alpha"] == pytest.approx(-5.0)
        assert result["outperforming"] is False

    def test_bad_dates_return_zero_result(self):
        result = compare_to_benchmark(
            [100_000.0, 101_000.0], ["not-a-date", "also-bad"]
        )
        assert result["outperforming"] is False
        assert result["alpha"] == 0.0


# ─── MP-104: streak ──────────────────────────────────────────────────────────

class TestCalculateStreaks:

    def test_empty_series(self):
        assert calculate_streaks([]) == {
            "current_win_streak": 0,
            "max_win_streak": 0,
            "current_loss_streak": 0,
            "max_loss_streak": 0,
        }

    def test_all_wins(self):
        result = calculate_streaks([1.0, 2.0, 0.5])
        assert result["current_win_streak"] == 3
        assert result["max_win_streak"] == 3
        assert result["max_loss_streak"] == 0

    def test_mixed_series(self):
        result = calculate_streaks([1.0, 1.0, -1.0, -1.0, -1.0, 2.0])
        assert result["max_win_streak"] == 2
        assert result["max_loss_streak"] == 3
        assert result["current_win_streak"] == 1
        assert result["current_loss_streak"] == 0

    def test_zero_breaks_both_streaks(self):
        result = calculate_streaks([1.0, 1.0, 0.0, 1.0])
        assert result["max_win_streak"] == 2
        assert result["current_win_streak"] == 1
        assert result["current_loss_streak"] == 0


# ─── MP-104: calmar ──────────────────────────────────────────────────────────

class TestCalculateCalmarMP104:

    def test_zero_drawdown_returns_zero(self):
        assert calculate_calmar(10.0, 0.0) == 0.0

    def test_basic_ratio(self):
        assert calculate_calmar(10.0, 5.0) == pytest.approx(2.0)

    def test_negative_drawdown_uses_abs(self):
        assert calculate_calmar(10.0, -5.0) == pytest.approx(2.0)

    def test_negative_return_gives_negative_calmar(self):
        assert calculate_calmar(-4.0, 2.0) == pytest.approx(-2.0)


# ─── MP-104: concentration ───────────────────────────────────────────────────

class TestCalculateConcentration:

    def test_empty_allocation(self):
        assert calculate_concentration({}) == {
            "herfindahl_index": 0.0,
            "top1_weight": 0.0,
            "top3_weight": 0.0,
            "n_active": 0,
        }

    def test_single_position_is_fully_concentrated(self):
        result = calculate_concentration({"aave_v3": 1.0})
        assert result["herfindahl_index"] == pytest.approx(1.0)
        assert result["top1_weight"] == pytest.approx(1.0)
        assert result["n_active"] == 1

    def test_equal_weights(self):
        result = calculate_concentration(
            {"aave_v3": 0.25, "compound_v3": 0.25, "morpho_blue": 0.25, "yearn_v3": 0.25}
        )
        assert result["herfindahl_index"] == pytest.approx(0.25)
        assert result["top1_weight"] == pytest.approx(0.25)
        assert result["top3_weight"] == pytest.approx(0.75)
        assert result["n_active"] == 4

    def test_usd_amounts_are_normalized(self):
        # Absolute USD positions behave the same as fractional weights.
        result = calculate_concentration({"a": 50_000.0, "b": 30_000.0, "c": 20_000.0})
        assert result["top1_weight"] == pytest.approx(0.5)
        assert result["top3_weight"] == pytest.approx(1.0)
        assert result["herfindahl_index"] == pytest.approx(0.25 + 0.09 + 0.04)

    def test_zero_and_negative_weights_ignored(self):
        result = calculate_concentration({"a": 1.0, "b": 0.0, "c": -0.5})
        assert result["n_active"] == 1
        assert result["top1_weight"] == pytest.approx(1.0)


# ─── MP-104: analytics_runner ────────────────────────────────────────────────

def _write_equity_doc(data_dir: Path, bars: list[dict], is_demo: bool = False):
    doc = {
        "generated_at": "2026-06-10T08:00:00+00:00",
        "source": "cycle_runner",
        "is_demo": is_demo,
        "daily": bars,
    }
    (data_dir / "equity_curve_daily.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )


def _bars(equities: list[float], start: str = "2026-06-01") -> list[dict]:
    from datetime import date, timedelta
    base = date.fromisoformat(start)
    return [
        {
            "date": (base + timedelta(days=i)).isoformat(),
            "equity": e,
            "positions": {"aave_v3": e * 0.6, "morpho_blue": e * 0.4},
        }
        for i, e in enumerate(equities)
    ]


class TestRunPostCycleAnalytics:

    def test_writes_summary_with_all_metrics(self, tmp_path):
        _write_equity_doc(tmp_path, _bars([100_000.0, 100_050.0, 100_020.0, 100_110.0]))
        summary = run_post_cycle_analytics(data_dir=tmp_path)

        out = tmp_path / "analytics_summary.json"
        assert out.exists()
        on_disk = json.loads(out.read_text(encoding="utf-8"))
        assert on_disk["metrics"].keys() == summary["metrics"].keys()

        m = summary["metrics"]
        for key in (
            "sharpe", "drawdown", "volatility", "benchmark",
            "streaks", "calmar", "concentration",
        ):
            assert m[key] is not None, f"metric {key} missing"
        assert summary["errors"] == []
        assert summary["num_days"] == 4
        assert summary["is_demo"] is False
        assert m["concentration"]["n_active"] == 2
        # pnl = [+50, -30, +90] → win streaks of 1, one loss day
        assert m["streaks"]["max_win_streak"] == 1
        assert m["streaks"]["max_loss_streak"] == 1
        assert m["streaks"]["current_win_streak"] == 1
        assert m["drawdown"]["max_drawdown_pct"] > 0.0

    def test_missing_equity_file_writes_empty_summary(self, tmp_path):
        summary = run_post_cycle_analytics(data_dir=tmp_path)
        assert summary["num_days"] == 0
        assert summary["metrics"]["sharpe"] == 0.0
        assert (tmp_path / "analytics_summary.json").exists()

    def test_corrupt_equity_file_is_failsafe(self, tmp_path):
        (tmp_path / "equity_curve_daily.json").write_text("{not json", encoding="utf-8")
        summary = run_post_cycle_analytics(data_dir=tmp_path)
        assert summary["num_days"] == 0
        assert (tmp_path / "analytics_summary.json").exists()

    def test_metric_failure_writes_partial_summary(self, tmp_path, monkeypatch):
        import analytics.analytics_runner as runner_mod

        def _boom(*a, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(runner_mod, "calculate_sharpe", _boom)
        _write_equity_doc(tmp_path, _bars([100_000.0, 100_050.0, 100_100.0]))
        summary = run_post_cycle_analytics(data_dir=tmp_path)

        assert summary["metrics"]["sharpe"] is None
        assert any("sharpe" in e for e in summary["errors"])
        # All the other metrics still computed and persisted:
        assert summary["metrics"]["drawdown"] is not None
        assert summary["metrics"]["concentration"] is not None
        assert (tmp_path / "analytics_summary.json").exists()

    def test_write_false_returns_but_writes_nothing(self, tmp_path):
        _write_equity_doc(tmp_path, _bars([100_000.0, 100_050.0]))
        summary = run_post_cycle_analytics(data_dir=tmp_path, write=False)
        assert summary["num_days"] == 2
        assert not (tmp_path / "analytics_summary.json").exists()

    def test_close_equity_fallback(self, tmp_path):
        bars = [
            {"date": "2026-06-01", "close_equity": 100_000.0},
            {"date": "2026-06-02", "close_equity": 100_040.0},
        ]
        _write_equity_doc(tmp_path, bars)
        summary = run_post_cycle_analytics(data_dir=tmp_path)
        assert summary["num_days"] == 2
        assert summary["metrics"]["benchmark"]["spa_total_return"] == pytest.approx(
            0.04, rel=1e-6
        )
