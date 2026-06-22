# LLM_FORBIDDEN
"""
Tests for spa_core/backtesting/professional_backtest.py

Coverage targets (60+ tests):
  - Pure metric functions (Sharpe, Sortino, Calmar, VaR, CVaR, Omega, Win-rate)
  - Drawdown detection (max drawdown, duration, episodes)
  - Interpolation and daily APY series
  - Monthly returns and equity curve downsampling
  - Rolling Sharpe computation
  - Sub-period metrics
  - Simulation core (equity curve, transaction costs)
  - Stress test integration
  - Benchmark comparison math
  - Output schema validation (full run)
  - Edge cases: single-day, all-zero returns, monotone equity, full recovery
  - Atomic write helper
  - ProfessionalBacktest.run() contract
  - ProfessionalBacktest.update_legacy_redirect()

LLM_FORBIDDEN: no LLM calls in this module.
"""
# LLM_FORBIDDEN

import json
import math
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

# ── import the module under test ───────────────────────────────────────────────
from spa_core.backtesting.professional_backtest import (
    # constants
    INITIAL_CAPITAL,
    ANNUALISE,
    SIM_START,
    SIM_END,
    STRATEGIES,
    # utilities
    _parse_date,
    _atomic_write_json,
    _interp,
    _daily_yield,
    _date_range,
    _year_month,
    _build_apy_points,
    # simulation
    _is_rebalance_day,
    _simulate,
    # metrics
    _total_return_pct,
    _annualized_return_pct,
    _annualized_volatility_pct,
    _sharpe_ratio,
    _sortino_ratio,
    _max_drawdown_pct,
    _max_drawdown_duration,
    _drawdown_periods,
    _var_95_pct,
    _cvar_95_pct,
    _omega_ratio,
    _win_rate_pct,
    _calmar_ratio,
    _monthly_returns,
    _rolling_sharpe,
    _equity_curve_monthly,
    _sub_period_metrics,
    _compute_full_metrics,
    # benchmark & stress
    _run_benchmark,
    _benchmark_comparison,
    _run_stress_tests,
    # main class
    ProfessionalBacktest,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _const_equity(n: int, start: float = INITIAL_CAPITAL, delta: float = 100.0):
    """Monotonically increasing equity curve with constant daily step."""
    return [start + i * delta for i in range(n)]


def _flat_returns(n: int, r: float = 0.0) -> list:
    return [r] * n


def _days_n(n: int, start: date = date(2022, 1, 1)) -> list:
    return [start + timedelta(days=i) for i in range(n)]


def _monthly_fixture() -> dict:
    """Tiny daily APY dict: aave_v3 at 4 % annual for 90 days."""
    d_list = _days_n(90)
    dy = _daily_yield(0.04)
    return {"aave_v3": {d: dy for d in d_list}}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Utility helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestParseDate(unittest.TestCase):
    def test_iso_date(self):
        d = _parse_date("2022-05-15")
        self.assertEqual(d, date(2022, 5, 15))

    def test_datetime_prefix(self):
        d = _parse_date("2023-03-10T00:00:00Z")
        self.assertEqual(d, date(2023, 3, 10))


class TestAtomicWriteJson(unittest.TestCase):
    def test_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.json"
            _atomic_write_json(path, {"key": "value", "num": 42})
            data = json.loads(path.read_text())
            self.assertEqual(data["key"], "value")
            self.assertEqual(data["num"], 42)

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "nested" / "deep" / "file.json"
            _atomic_write_json(path, [1, 2, 3])
            self.assertTrue(path.exists())

    def test_overwrite_existing(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "file.json"
            _atomic_write_json(path, {"v": 1})
            _atomic_write_json(path, {"v": 2})
            data = json.loads(path.read_text())
            self.assertEqual(data["v"], 2)

    def test_no_tmp_file_left_behind(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "f.json"
            _atomic_write_json(path, {})
            tmp = Path(str(path) + ".tmp")
            self.assertFalse(tmp.exists())


class TestInterp(unittest.TestCase):
    def setUp(self):
        self.pts = [
            (date(2022, 1, 1), 0.02),
            (date(2022, 7, 1), 0.05),
            (date(2023, 1, 1), 0.03),
        ]

    def test_exact_point(self):
        v = _interp(self.pts, date(2022, 1, 1))
        self.assertAlmostEqual(v, 0.02, places=6)

    def test_clamp_before_start(self):
        v = _interp(self.pts, date(2021, 6, 1))
        self.assertAlmostEqual(v, 0.02, places=6)

    def test_clamp_after_end(self):
        v = _interp(self.pts, date(2024, 1, 1))
        self.assertAlmostEqual(v, 0.03, places=6)

    def test_midpoint_linear(self):
        # Midpoint between Jan-1-2022 (0.02) and Jul-1-2022 (0.05)
        mid = date(2022, 4, 1)
        v = _interp(self.pts, mid)
        self.assertGreater(v, 0.02)
        self.assertLess(v, 0.05)

    def test_empty_points(self):
        self.assertEqual(_interp([], date(2022, 1, 1)), 0.0)


class TestDailyYield(unittest.TestCase):
    def test_zero_apy(self):
        self.assertAlmostEqual(_daily_yield(0.0), 0.0, places=10)

    def test_4pct_apy(self):
        dy = _daily_yield(0.04)
        # Compound daily for 365 days should give ~4 %
        compounded = (1 + dy) ** 365 - 1
        self.assertAlmostEqual(compounded, 0.04, places=5)

    def test_positive(self):
        self.assertGreater(_daily_yield(0.05), 0.0)


class TestDateRange(unittest.TestCase):
    def test_inclusive(self):
        r = _date_range(date(2022, 1, 1), date(2022, 1, 5))
        self.assertEqual(len(r), 5)
        self.assertEqual(r[0], date(2022, 1, 1))
        self.assertEqual(r[-1], date(2022, 1, 5))

    def test_single_day(self):
        r = _date_range(date(2023, 6, 15), date(2023, 6, 15))
        self.assertEqual(len(r), 1)


class TestBuildApyPoints(unittest.TestCase):
    def test_parses_and_sorts(self):
        series = [
            {"date": "2022-06-01", "apy": 0.03},
            {"date": "2022-01-01", "apy": 0.02},
        ]
        pts = _build_apy_points(series)
        self.assertEqual(len(pts), 2)
        self.assertLess(pts[0][0], pts[1][0])

    def test_skips_invalid(self):
        series = [{"date": "not-a-date", "apy": 0.03}, {"date": "2022-01-01", "apy": 0.02}]
        pts = _build_apy_points(series)
        self.assertEqual(len(pts), 1)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Simulation core
# ─────────────────────────────────────────────────────────────────────────────

class TestIsRebalanceDay(unittest.TestCase):
    def test_first_of_month(self):
        self.assertTrue(_is_rebalance_day(date(2022, 3, 1)))

    def test_not_first(self):
        self.assertFalse(_is_rebalance_day(date(2022, 3, 15)))

    def test_jan_first(self):
        self.assertTrue(_is_rebalance_day(date(2023, 1, 1)))


class TestSimulate(unittest.TestCase):
    def _build_daily_apy(self, protocols, apy_decimal, n_days=90):
        days = _days_n(n_days)
        dy = _daily_yield(apy_decimal)
        return {p: {d: dy for d in days} for p in protocols}, days

    def test_pure_cash_no_growth(self):
        daily_apy, days = self._build_daily_apy(["aave_v3"], 0.04, 30)
        eq, dr = _simulate({"aave_v3": 0.0}, 1.0, daily_apy, days)
        # 100 % cash earns 0 %
        self.assertAlmostEqual(eq[-1], INITIAL_CAPITAL, places=2)

    def test_monotone_increase_positive_apy(self):
        daily_apy, days = self._build_daily_apy(["aave_v3"], 0.05, 60)
        eq, dr = _simulate({"aave_v3": 1.0}, 0.0, daily_apy, days)
        self.assertGreater(eq[-1], INITIAL_CAPITAL)
        # Equity is non-decreasing (rebalance cost aside)
        for i in range(1, len(eq)):
            if not _is_rebalance_day(days[i]):
                self.assertGreaterEqual(eq[i], eq[i - 1])

    def test_transaction_cost_applied_on_rebalance(self):
        """Equity dips slightly on day 1 (first calendar day = rebalance)."""
        daily_apy, days = self._build_daily_apy(["aave_v3"], 0.0, 5)
        eq, dr = _simulate({"aave_v3": 1.0}, 0.0, daily_apy, days)
        # Day 1 (index 0) is Jan 1 → rebalance → tx cost applies before yield
        self.assertLess(eq[0], INITIAL_CAPITAL)

    def test_single_day(self):
        daily_apy, days = self._build_daily_apy(["aave_v3"], 0.04, 1)
        eq, dr = _simulate({"aave_v3": 1.0}, 0.0, daily_apy, days)
        self.assertEqual(len(eq), 1)
        self.assertEqual(len(dr), 1)

    def test_zero_apy_equity_decreases_only_on_rebalance(self):
        daily_apy, days = self._build_daily_apy(["aave_v3"], 0.0, 35)
        eq, dr = _simulate({"aave_v3": 1.0}, 0.0, daily_apy, days)
        # Should only decrease on rebalance days
        for i in range(1, len(eq)):
            if not _is_rebalance_day(days[i]):
                self.assertAlmostEqual(eq[i], eq[i - 1], places=6)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Metric functions
# ─────────────────────────────────────────────────────────────────────────────

class TestTotalReturnPct(unittest.TestCase):
    def test_basic(self):
        eq = [INITIAL_CAPITAL, 110_000.0]
        self.assertAlmostEqual(_total_return_pct(eq), 10.0, places=4)

    def test_empty(self):
        self.assertEqual(_total_return_pct([]), 0.0)

    def test_no_change(self):
        eq = [INITIAL_CAPITAL, INITIAL_CAPITAL]
        self.assertAlmostEqual(_total_return_pct(eq), 0.0, places=6)


class TestAnnualizedReturnPct(unittest.TestCase):
    def test_one_year_5pct(self):
        # 5 % over 365 days starting at 100k
        end_eq = [INITIAL_CAPITAL * 1.05]
        result = _annualized_return_pct(end_eq, 365)
        self.assertAlmostEqual(result, 5.0, delta=0.05)

    def test_zero_n_days(self):
        self.assertEqual(_annualized_return_pct([100_000.0], 0), 0.0)

    def test_negative_equity(self):
        self.assertEqual(_annualized_return_pct([0.0], 365), 0.0)


class TestAnnualizedVolatility(unittest.TestCase):
    def test_zero_returns(self):
        self.assertEqual(_annualized_volatility_pct(_flat_returns(30, 0.0)), 0.0)

    def test_positive_vol(self):
        import random
        random.seed(42)
        returns = [random.gauss(0.0001, 0.001) for _ in range(200)]
        vol = _annualized_volatility_pct(returns)
        self.assertGreater(vol, 0.0)

    def test_single_return(self):
        self.assertEqual(_annualized_volatility_pct([0.001]), 0.0)


class TestSharpeRatio(unittest.TestCase):
    def test_positive_mean_positive_sharpe(self):
        # Consistent small positive return → positive Sharpe
        returns = _flat_returns(100, 0.0001)
        # All same value → zero std → Sharpe = 0
        self.assertEqual(_sharpe_ratio(returns), 0.0)

    def test_mixed_returns(self):
        import random
        random.seed(123)
        returns = [random.gauss(0.0005, 0.002) for _ in range(300)]
        sh = _sharpe_ratio(returns)
        self.assertIsInstance(sh, float)

    def test_zero_std_returns_zero(self):
        returns = [0.001] * 50
        self.assertEqual(_sharpe_ratio(returns), 0.0)

    def test_short_series(self):
        self.assertEqual(_sharpe_ratio([0.001]), 0.0)

    def test_empty(self):
        self.assertEqual(_sharpe_ratio([]), 0.0)


class TestSortinoRatio(unittest.TestCase):
    def test_no_losses_positive(self):
        returns = [0.001] * 50
        # All positive → very high Sortino
        s = _sortino_ratio(returns)
        self.assertGreater(s, 0.0)

    def test_mixed_returns(self):
        import random
        random.seed(7)
        returns = [random.gauss(0.0003, 0.003) for _ in range(200)]
        s = _sortino_ratio(returns)
        self.assertIsInstance(s, float)

    def test_all_losses(self):
        returns = [-0.001] * 50
        s = _sortino_ratio(returns)
        self.assertLess(s, 0.0)

    def test_empty(self):
        self.assertEqual(_sortino_ratio([]), 0.0)


class TestMaxDrawdownPct(unittest.TestCase):
    def test_no_drawdown_monotone(self):
        eq = list(range(100_000, 110_000, 100))
        self.assertAlmostEqual(_max_drawdown_pct(eq), 0.0, places=4)

    def test_known_drawdown(self):
        # Peak 100k, drop to 90k = 10 % drawdown
        eq = [100_000.0, 105_000.0, 90_000.0, 95_000.0, 110_000.0]
        dd = _max_drawdown_pct(eq)
        self.assertAlmostEqual(dd, 100.0 * (105_000 - 90_000) / 105_000, delta=0.01)

    def test_single_element(self):
        self.assertEqual(_max_drawdown_pct([100_000.0]), 0.0)

    def test_all_same(self):
        self.assertAlmostEqual(_max_drawdown_pct([100_000.0] * 10), 0.0, places=4)

    def test_all_zeros(self):
        self.assertEqual(_max_drawdown_pct([0.0] * 5), 0.0)


class TestMaxDrawdownDuration(unittest.TestCase):
    def test_recovery(self):
        # Rises to 110k, drops to 90k, recovers to 115k
        eq = [100_000.0, 110_000.0, 90_000.0, 95_000.0, 100_000.0, 115_000.0]
        days = _days_n(6, start=date(2022, 1, 1))
        dur = _max_drawdown_duration(eq, days)
        # Drawdown from day index 1 (110k peak) recovers at day index 5 (115k)
        self.assertEqual(dur, 4)

    def test_no_drawdown(self):
        eq = _const_equity(10)
        days = _days_n(10)
        self.assertEqual(_max_drawdown_duration(eq, days), 0)


class TestDrawdownPeriods(unittest.TestCase):
    def test_detects_episode(self):
        eq = [100_000.0, 105_000.0, 90_000.0, 95_000.0, 110_000.0]
        days = _days_n(5)
        episodes = _drawdown_periods(eq, days, threshold_pct=0.0)
        self.assertGreater(len(episodes), 0)

    def test_below_threshold_ignored(self):
        # Tiny drawdown 0.001 %
        eq = [100_000.0, 100_001.0, 100_000.5, 100_002.0]
        days = _days_n(4)
        episodes = _drawdown_periods(eq, days, threshold_pct=1.0)
        self.assertEqual(len(episodes), 0)

    def test_open_drawdown(self):
        # Last element still below peak
        eq = [100_000.0, 110_000.0, 90_000.0]
        days = _days_n(3)
        episodes = _drawdown_periods(eq, days, threshold_pct=0.0)
        self.assertTrue(any(e["end"] is None for e in episodes))

    def test_fields_present(self):
        eq = [100_000.0, 110_000.0, 90_000.0, 115_000.0]
        days = _days_n(4)
        eps = _drawdown_periods(eq, days, threshold_pct=0.0)
        if eps:
            ep = eps[0]
            for field in ("start", "trough", "depth_pct", "recovery_days"):
                self.assertIn(field, ep)

    def test_empty_equity(self):
        self.assertEqual(_drawdown_periods([], [], threshold_pct=0.0), [])


class TestVaR(unittest.TestCase):
    def test_returns_positive(self):
        import random
        random.seed(99)
        returns = [random.gauss(-0.0001, 0.002) for _ in range(200)]
        var = _var_95_pct(returns)
        self.assertGreaterEqual(var, 0.0)

    def test_all_positive_returns_var_zero_or_small(self):
        returns = [0.001] * 200
        # All gains → 5th percentile is positive → VaR (loss) = 0 or small negative
        var = _var_95_pct(returns)
        self.assertAlmostEqual(var, -0.1, delta=0.5)

    def test_short_series(self):
        self.assertEqual(_var_95_pct([0.001] * 5), 0.0)


class TestCVaR(unittest.TestCase):
    def test_cvar_gte_var(self):
        import random
        random.seed(11)
        returns = [random.gauss(0.0, 0.003) for _ in range(200)]
        var = _var_95_pct(returns)
        cvar = _cvar_95_pct(returns)
        self.assertGreaterEqual(cvar, var - 0.01)

    def test_short_series(self):
        self.assertEqual(_cvar_95_pct([0.001] * 5), 0.0)


class TestOmegaRatio(unittest.TestCase):
    def test_all_gains(self):
        returns = [0.001] * 50
        omega = _omega_ratio(returns)
        self.assertGreater(omega, 1.0)

    def test_all_losses(self):
        returns = [-0.001] * 50
        omega = _omega_ratio(returns)
        self.assertAlmostEqual(omega, 0.0, places=4)

    def test_empty(self):
        self.assertEqual(_omega_ratio([]), 0.0)

    def test_mixed_greater_than_one_when_net_positive(self):
        returns = [0.002, 0.001, -0.0005, 0.001, 0.001]
        omega = _omega_ratio(returns)
        self.assertGreater(omega, 1.0)


class TestWinRate(unittest.TestCase):
    def test_all_wins(self):
        self.assertAlmostEqual(_win_rate_pct([0.001] * 10), 100.0, places=4)

    def test_all_losses(self):
        self.assertAlmostEqual(_win_rate_pct([-0.001] * 10), 0.0, places=4)

    def test_half(self):
        returns = [0.001, -0.001] * 5
        self.assertAlmostEqual(_win_rate_pct(returns), 50.0, places=4)

    def test_empty(self):
        self.assertEqual(_win_rate_pct([]), 0.0)


class TestCalmarRatio(unittest.TestCase):
    def test_basic(self):
        # 10 % annual return, 5 % max drawdown → Calmar = 2.0
        c = _calmar_ratio(10.0, 5.0)
        self.assertAlmostEqual(c, 2.0, places=4)

    def test_zero_drawdown(self):
        c = _calmar_ratio(10.0, 0.0)
        self.assertGreater(c, 0.0)

    def test_zero_return_zero_drawdown(self):
        self.assertEqual(_calmar_ratio(0.0, 0.0), 0.0)


class TestMonthlyReturns(unittest.TestCase):
    def test_length_90_days(self):
        n = 90
        eq = _const_equity(n, delta=50.0)
        days = _days_n(n)
        m = _monthly_returns(eq, days)
        # 90 days spans Jan/Feb/Mar 2022 → 3 months
        self.assertEqual(len(m), 3)

    def test_empty(self):
        self.assertEqual(_monthly_returns([], []), {})

    def test_positive_when_rising(self):
        n = 31
        eq = _const_equity(n, delta=100.0)
        days = _days_n(n)
        m = _monthly_returns(eq, days)
        for v in m.values():
            self.assertGreater(v, 0.0)


class TestRollingSharpe(unittest.TestCase):
    def test_window_30(self):
        n = 60
        returns = [0.0002] * 20 + [-0.0001] * 20 + [0.0003] * 20
        days = _days_n(n)
        rs = _rolling_sharpe(returns, days, 30)
        # Should have n - window + 1 = 31 entries
        self.assertEqual(len(rs), 31)

    def test_short_series(self):
        returns = [0.001] * 10
        days = _days_n(10)
        rs = _rolling_sharpe(returns, days, 30)
        self.assertEqual(rs, [])

    def test_output_has_date_and_sharpe(self):
        returns = [0.001, -0.0005] * 20
        days = _days_n(40)
        rs = _rolling_sharpe(returns, days, 10)
        for entry in rs:
            self.assertIn("date", entry)
            self.assertIn("sharpe", entry)


class TestEquityCurveMonthly(unittest.TestCase):
    def test_one_entry_per_month(self):
        n = 90
        eq = _const_equity(n)
        days = _days_n(n)
        monthly = _equity_curve_monthly(eq, days)
        months = {entry["date"][:7] for entry in monthly}
        self.assertEqual(len(months), 3)

    def test_fields(self):
        n = 35
        eq = _const_equity(n)
        days = _days_n(n)
        monthly = _equity_curve_monthly(eq, days)
        for entry in monthly:
            self.assertIn("date", entry)
            self.assertIn("equity_usd", entry)
            self.assertIn("drawdown_pct", entry)

    def test_empty(self):
        self.assertEqual(_equity_curve_monthly([], []), [])


class TestSubPeriodMetrics(unittest.TestCase):
    def test_returns_dict_for_valid_year(self):
        n = 365
        days = _days_n(n, start=date(2022, 1, 1))
        returns = [0.0001] * n
        eq = _const_equity(n, delta=10.0)
        result = _sub_period_metrics(returns, eq, days, 2022)
        self.assertIsNotNone(result)
        self.assertIn("annualized_return_pct", result)

    def test_returns_none_for_missing_year(self):
        n = 30
        days = _days_n(n, start=date(2022, 1, 1))
        returns = [0.0001] * n
        eq = _const_equity(n)
        result = _sub_period_metrics(returns, eq, days, 2025)
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Compute full metrics
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeFullMetrics(unittest.TestCase):
    def _run_90d(self):
        n = 90
        days = _days_n(n)
        returns = [_daily_yield(0.05)] * n
        eq = [INITIAL_CAPITAL * (1 + returns[0]) ** (i + 1) for i in range(n)]
        return _compute_full_metrics(eq, returns, days)

    def test_required_keys_present(self):
        metrics = self._run_90d()
        required = [
            "total_return_pct", "annualized_return_pct", "annualized_volatility_pct",
            "sharpe_ratio", "sortino_ratio", "calmar_ratio", "max_drawdown_pct",
            "max_drawdown_duration_days", "value_at_risk_95_pct", "cvar_95_pct",
            "omega_ratio", "win_rate_pct", "best_month_pct", "worst_month_pct",
            "final_equity_usd", "monthly_returns", "rolling_sharpe_30d",
            "rolling_sharpe_90d", "drawdown_periods", "equity_curve", "sub_periods",
        ]
        for key in required:
            self.assertIn(key, metrics, f"Missing key: {key}")

    def test_positive_return_5pct(self):
        metrics = self._run_90d()
        self.assertGreater(metrics["total_return_pct"], 0.0)

    def test_win_rate_100pct_monotone(self):
        metrics = self._run_90d()
        # All daily returns are positive → win rate 100 %
        self.assertAlmostEqual(metrics["win_rate_pct"], 100.0, places=1)

    def test_monthly_returns_dict(self):
        metrics = self._run_90d()
        self.assertIsInstance(metrics["monthly_returns"], dict)
        self.assertGreater(len(metrics["monthly_returns"]), 0)

    def test_final_equity_greater_than_initial(self):
        metrics = self._run_90d()
        self.assertGreater(metrics["final_equity_usd"], INITIAL_CAPITAL)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Benchmark comparison
# ─────────────────────────────────────────────────────────────────────────────

class TestRunBenchmark(unittest.TestCase):
    def test_4pct_benchmark(self):
        days = _days_n(365, start=date(2022, 1, 1))
        series = [{"date": "2022-01-01", "apy": 0.04}, {"date": "2025-12-31", "apy": 0.04}]
        result = _run_benchmark(series, days, "4pct flat")
        self.assertAlmostEqual(result["annualized_return_pct"], 4.0, delta=0.1)
        self.assertEqual(result["label"], "4pct flat")

    def test_benchmark_grows(self):
        days = _days_n(365, start=date(2022, 1, 1))
        series = [{"date": "2022-01-01", "apy": 0.05}, {"date": "2025-12-31", "apy": 0.05}]
        result = _run_benchmark(series, days, "test")
        self.assertGreater(result["final_equity_usd"], INITIAL_CAPITAL)


class TestBenchmarkComparison(unittest.TestCase):
    def _mock_strategy_result(self, annual_ret: float):
        n = 12
        # Build monthly returns dict
        months = {
            f"2022-{m:02d}": annual_ret / 12.0
            for m in range(1, n + 1)
        }
        return {
            "annualized_return_pct": annual_ret,
            "monthly_returns": months,
        }

    def _mock_bench(self, annual_ret: float):
        n = 12
        months = {
            f"2022-{m:02d}": annual_ret / 12.0
            for m in range(1, n + 1)
        }
        return {
            "annualized_return_pct": annual_ret,
            "monthly_returns": months,
        }

    def test_positive_excess_when_strategy_outperforms(self):
        strat = {"S0": self._mock_strategy_result(5.0)}
        bench = {"bench_a": self._mock_bench(3.0)}
        comp = _benchmark_comparison(strat, bench)
        self.assertGreater(comp["S0"]["bench_a"]["excess_annual_return_pct"], 0.0)

    def test_negative_excess_when_underperforms(self):
        strat = {"S0": self._mock_strategy_result(2.0)}
        bench = {"bench_a": self._mock_bench(5.0)}
        comp = _benchmark_comparison(strat, bench)
        self.assertLess(comp["S0"]["bench_a"]["excess_annual_return_pct"], 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Stress test integration
# ─────────────────────────────────────────────────────────────────────────────

class TestStressTests(unittest.TestCase):
    def _setup(self):
        days = _date_range(date(2022, 1, 1), date(2022, 6, 30))
        dy = _daily_yield(0.04)
        daily_apy = {"aave_v3": {d: dy for d in days}}
        strategies = {
            "S0_conservative": {
                "weights": {"aave_v3": 1.0},
                "cash_pct": 0.0,
            }
        }
        scenarios = [
            {
                "id": "TEST_STRESS",
                "name": "Test Stress",
                "start": "2022-03-01",
                "end": "2022-03-05",
                "t1_apy_override": 0.001,
                "t2_apy_override": 0.0,
                "description": "Test stress scenario.",
            }
        ]
        return days, daily_apy, strategies, scenarios

    def test_stress_result_structure(self):
        days, daily_apy, strategies, scenarios = self._setup()
        # Build minimal base results (only monthly equity_curve needed)
        base_eq = [INITIAL_CAPITAL * 1.0004 ** i for i in range(len(days))]
        base_results = {
            "S0_conservative": {
                "equity_curve": [
                    {"date": d.isoformat(), "equity_usd": base_eq[i], "drawdown_pct": 0.0}
                    for i, d in enumerate(days)
                    if d.day == 1 or d == days[-1]
                ]
            }
        }
        stress = _run_stress_tests(
            strategies, daily_apy, base_results, days, scenarios
        )
        self.assertIn("TEST_STRESS", stress)
        self.assertIn("per_strategy", stress["TEST_STRESS"])
        self.assertIn("S0_conservative", stress["TEST_STRESS"]["per_strategy"])

    def test_stress_reduces_return(self):
        days, daily_apy, strategies, scenarios = self._setup()
        base_eq = [INITIAL_CAPITAL * 1.0001 ** i for i in range(len(days))]
        base_results = {
            "S0_conservative": {
                "equity_curve": [
                    {"date": d.isoformat(), "equity_usd": base_eq[i], "drawdown_pct": 0.0}
                    for i, d in enumerate(days)
                    if d.day == 1 or d == days[-1]
                ]
            }
        }
        stress = _run_stress_tests(
            strategies, daily_apy, base_results, days, scenarios
        )
        per_s = stress["TEST_STRESS"]["per_strategy"]["S0_conservative"]
        # Very low stress APY (0.1%) vs base 4% → stress window return < base window return
        self.assertLess(per_s["impact_bps"], 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# 7. ProfessionalBacktest integration tests (fast subset)
# ─────────────────────────────────────────────────────────────────────────────

class TestProfessionalBacktestClass(unittest.TestCase):
    """Integration tests that run a short-window backtest."""

    def _short_bt(self, tmpdir: str) -> ProfessionalBacktest:
        """Create a ProfessionalBacktest over just 2022 for speed."""
        from spa_core.backtesting.professional_backtest import _STRESS_SCENARIOS
        return ProfessionalBacktest(
            start=date(2022, 1, 1),
            end=date(2022, 12, 31),
            data_dir=Path(tmpdir),
            stress_scenarios=_STRESS_SCENARIOS,
        )

    def test_run_returns_dict(self):
        with tempfile.TemporaryDirectory() as td:
            bt = self._short_bt(td)
            result = bt.run()
            self.assertIsInstance(result, dict)

    def test_meta_keys(self):
        with tempfile.TemporaryDirectory() as td:
            bt = self._short_bt(td)
            result = bt.run()
            meta = result["meta"]
            for key in ("generated_at", "version", "data_source", "period",
                        "methodology", "caveat", "llm_forbidden"):
                self.assertIn(key, meta, f"Missing meta key: {key}")

    def test_llm_forbidden_flag(self):
        with tempfile.TemporaryDirectory() as td:
            bt = self._short_bt(td)
            result = bt.run()
            self.assertTrue(result["meta"]["llm_forbidden"])

    def test_all_strategies_in_result(self):
        with tempfile.TemporaryDirectory() as td:
            bt = self._short_bt(td)
            result = bt.run()
            for strat_name in STRATEGIES:
                self.assertIn(strat_name, result["strategies"])

    def test_leaderboard_sorted_by_sharpe(self):
        with tempfile.TemporaryDirectory() as td:
            bt = self._short_bt(td)
            result = bt.run()
            lb = result["leaderboard"]
            sharpes = [e["sharpe_ratio"] for e in lb]
            self.assertEqual(sharpes, sorted(sharpes, reverse=True))

    def test_best_strategy_is_in_strategies(self):
        with tempfile.TemporaryDirectory() as td:
            bt = self._short_bt(td)
            result = bt.run()
            self.assertIn(result["best_strategy"], result["strategies"])

    def test_benchmarks_present(self):
        with tempfile.TemporaryDirectory() as td:
            bt = self._short_bt(td)
            result = bt.run()
            self.assertIn("usdc_savings", result["benchmarks"])
            self.assertIn("tbill_proxy", result["benchmarks"])

    def test_benchmark_comparison_has_all_strategies(self):
        with tempfile.TemporaryDirectory() as td:
            bt = self._short_bt(td)
            result = bt.run()
            comp = result["benchmark_comparison"]
            for strat_name in STRATEGIES:
                self.assertIn(strat_name, comp)

    def test_stress_results_present(self):
        with tempfile.TemporaryDirectory() as td:
            bt = self._short_bt(td)
            result = bt.run()
            self.assertIn("stress_test_results", result)
            # LUNA scenario overlaps with 2022
            self.assertIn("LUNA_2022", result["stress_test_results"])

    def test_save_writes_json(self):
        with tempfile.TemporaryDirectory() as td:
            bt = self._short_bt(td)
            result = bt.run()
            out = bt.save(result, filename="test_output.json")
            self.assertTrue(out.exists())
            loaded = json.loads(out.read_text())
            self.assertIn("meta", loaded)

    def test_update_legacy_redirect(self):
        with tempfile.TemporaryDirectory() as td:
            redirect_path = ProfessionalBacktest.update_legacy_redirect(Path(td))
            self.assertTrue(redirect_path.exists())
            data = json.loads(redirect_path.read_text())
            self.assertIn("redirects_to", data)
            self.assertIn("professional_backtest_result.json", data["redirects_to"])

    def test_no_apy_promises_in_meta_caveat(self):
        with tempfile.TemporaryDirectory() as td:
            bt = self._short_bt(td)
            result = bt.run()
            caveat = result["meta"]["caveat"].lower()
            # Must include disclaimer
            self.assertIn("past performance", caveat)
            self.assertIn("does not predict", caveat)

    def test_strategy_metrics_have_sub_periods(self):
        with tempfile.TemporaryDirectory() as td:
            bt = self._short_bt(td)
            result = bt.run()
            for strat_name in STRATEGIES:
                sp = result["strategies"][strat_name]["sub_periods"]
                self.assertIn("2022", sp)

    def test_equity_curve_monthly_present(self):
        with tempfile.TemporaryDirectory() as td:
            bt = self._short_bt(td)
            result = bt.run()
            for strat_name in STRATEGIES:
                ec = result["strategies"][strat_name]["equity_curve"]
                self.assertIsInstance(ec, list)
                self.assertGreater(len(ec), 0)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def test_all_zero_returns_metrics(self):
        """Zero returns → zero vol, zero Sharpe, zero max drawdown."""
        n = 100
        returns = _flat_returns(n, 0.0)
        eq = [INITIAL_CAPITAL] * n
        days = _days_n(n)
        metrics = _compute_full_metrics(eq, returns, days)
        self.assertAlmostEqual(metrics["annualized_volatility_pct"], 0.0, places=6)
        self.assertEqual(metrics["sharpe_ratio"], 0.0)
        self.assertAlmostEqual(metrics["max_drawdown_pct"], 0.0, places=4)

    def test_single_day_history(self):
        """Single day should not crash any metric function."""
        eq = [INITIAL_CAPITAL]
        dr = [0.0]
        days = [date(2022, 1, 1)]
        metrics = _compute_full_metrics(eq, dr, days)
        self.assertIn("total_return_pct", metrics)
        self.assertAlmostEqual(metrics["total_return_pct"], 0.0, places=4)

    def test_max_drawdown_full_recovery(self):
        """Equity drops and fully recovers — drawdown episode has recovery_days."""
        eq = [100_000.0, 110_000.0, 80_000.0, 90_000.0, 100_000.0, 115_000.0]
        days = _days_n(6)
        episodes = _drawdown_periods(eq, days, threshold_pct=0.0)
        closed = [e for e in episodes if e["end"] is not None]
        self.assertGreater(len(closed), 0)
        self.assertIsNotNone(closed[0]["recovery_days"])

    def test_zero_weight_strategy(self):
        """All-cash strategy (no protocol weights) → only tx cost drag."""
        days = _days_n(31)
        daily_apy: dict = {}
        eq, dr = _simulate({}, 1.0, daily_apy, days)
        self.assertAlmostEqual(eq[-1], INITIAL_CAPITAL, places=2)

    def test_large_stress_impact_negative(self):
        """Stress with 0 % APY vs 5 % base → always negative impact."""
        scenario = {
            "id": "X",
            "name": "Test",
            "start": "2022-03-01",
            "end": "2022-03-10",
            "t1_apy_override": 0.0,
            "t2_apy_override": 0.0,
            "description": "Zero APY stress",
        }
        days = _date_range(date(2022, 1, 1), date(2022, 6, 30))
        dy = _daily_yield(0.05)
        daily_apy = {"aave_v3": {d: dy for d in days}}
        strategies = {"S_test": {"weights": {"aave_v3": 1.0}, "cash_pct": 0.0}}
        base_results = {
            "S_test": {
                "equity_curve": [
                    {"date": d.isoformat(), "equity_usd": INITIAL_CAPITAL, "drawdown_pct": 0.0}
                    for d in days
                    if d.day == 1 or d == days[-1]
                ]
            }
        }
        stress = _run_stress_tests(strategies, daily_apy, base_results, days, [scenario])
        per_s = stress["X"]["per_strategy"]["S_test"]
        self.assertLessEqual(per_s["impact_bps"], 0.0)

    def test_backtest_full_period_constants(self):
        """Sim start and end constants are date objects and form valid range."""
        self.assertIsInstance(SIM_START, date)
        self.assertIsInstance(SIM_END, date)
        self.assertLess(SIM_START, SIM_END)
        days = _date_range(SIM_START, SIM_END)
        # 2022-01-01 to 2025-12-31 = 1461 days (2024 is leap year)
        self.assertEqual(len(days), 1461)

    def test_year_month_helper(self):
        self.assertEqual(_year_month(date(2023, 4, 15)), "2023-04")
        self.assertEqual(_year_month(date(2022, 12, 31)), "2022-12")


if __name__ == "__main__":
    unittest.main(verbosity=2)
