"""test_performance_report.py — unit tests for performance_report.py.

Covers: total_return, APY annualisation, max_drawdown, Sharpe/Sortino/Calmar
        (None when insufficient data), atomic write, CLI flags.
All tests are pure stdlib / no external dependencies.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# Ensure project root is on path so imports work from any working directory
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.paper_trading.performance_report import (
    compute_calmar,
    compute_max_drawdown,
    compute_report,
    compute_sharpe,
    compute_sortino,
    load_benchmark_apy,
    persist_report,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_equity_json(daily: list[dict]) -> dict:
    """Build minimal equity_curve_daily.json structure."""
    return {"daily": daily}


def _make_daily(dates: list[str], equities: list[float]) -> list[dict]:
    """Build list of daily entries from dates/equities."""
    entries = []
    for i, (d, eq) in enumerate(zip(dates, equities)):
        prev = equities[i - 1] if i > 0 else eq
        dr = (eq - prev) / prev * 100.0 if prev > 0 else 0.0
        entries.append({
            "date": d,
            "open_equity": float(equities[i - 1] if i > 0 else eq),
            "close_equity": float(eq),
            "equity": float(eq),
            "daily_return_pct": round(dr, 6),
            "cumulative_return_pct": round((eq - equities[0]) / equities[0] * 100.0, 6),
            "drawdown_pct": 0.0,
        })
    return entries


def _make_data_dir_with_equity(daily: list[dict], adapter_apy: float | None = 4.2):
    """Create a temp dir with equity_curve_daily.json (and optionally adapter_status.json)."""
    tmp = tempfile.mkdtemp()
    equity = _make_equity_json(daily)
    with open(os.path.join(tmp, "equity_curve_daily.json"), "w") as fh:
        json.dump(equity, fh)
    if adapter_apy is not None:
        adapter = {
            "adapters": [{
                "protocol_key": "aave-v3",
                "mock_apy": {"ethereum": {"USDC": adapter_apy}},
            }]
        }
        with open(os.path.join(tmp, "adapter_status.json"), "w") as fh:
            json.dump(adapter, fh)
    return tmp


def _make_returns(n: int, daily_pct: float = 0.01) -> list[float]:
    """Make list of n identical daily returns."""
    return [daily_pct] * n


# ─── Total Return ─────────────────────────────────────────────────────────────

class TestTotalReturn(unittest.TestCase):

    def test_total_return_zero_gain(self):
        """If equity doesn't change, total_return_pct == 0."""
        daily = _make_daily(["2026-06-10", "2026-06-11"], [100000.0, 100000.0])
        tmp = _make_data_dir_with_equity(daily)
        report = compute_report(tmp)
        self.assertEqual(report["total_return_pct"], 0.0)

    def test_total_return_positive(self):
        """Positive gain yields positive total_return_pct."""
        daily = _make_daily(["2026-06-10", "2026-06-11"], [100000.0, 101000.0])
        tmp = _make_data_dir_with_equity(daily)
        report = compute_report(tmp)
        self.assertAlmostEqual(report["total_return_pct"], 1.0, places=4)

    def test_total_return_negative(self):
        """Loss yields negative total_return_pct."""
        daily = _make_daily(["2026-06-10", "2026-06-11"], [100000.0, 99000.0])
        tmp = _make_data_dir_with_equity(daily)
        report = compute_report(tmp)
        self.assertAlmostEqual(report["total_return_pct"], -1.0, places=4)

    def test_total_return_formula(self):
        """total_return_pct matches (last - first) / first * 100 formula."""
        first, last = 80000.0, 84000.0
        daily = _make_daily(["2026-06-10", "2026-06-11"], [first, last])
        tmp = _make_data_dir_with_equity(daily)
        report = compute_report(tmp)
        expected = (last - first) / first * 100.0
        self.assertAlmostEqual(report["total_return_pct"], round(expected, 6), places=5)


# ─── Annualised APY ───────────────────────────────────────────────────────────

class TestAnnualisedAPY(unittest.TestCase):

    def test_apy_exact_year_equals_total_return(self):
        """365-day track: annualised APY ≈ total_return_pct."""
        import datetime as _dt
        start = _dt.date(2025, 6, 10)
        dates = [(start + _dt.timedelta(days=i)).isoformat() for i in range(365)]
        # Constant 3% annual → ≈ 3/365 % daily compounded
        daily_r = 3.0 / 365.0
        equities = [100000.0]
        for _ in range(364):
            equities.append(equities[-1] * (1 + daily_r / 100.0))
        daily = _make_daily(dates, equities)
        tmp = _make_data_dir_with_equity(daily, adapter_apy=None)
        report = compute_report(tmp)
        # Total return over a year annualised should stay ≈ total_return
        self.assertAlmostEqual(report["annualized_apy_pct"], report["total_return_pct"], places=1)

    def test_apy_two_day_track(self):
        """2-day track: APY = ((1 + r/100)^(365/2) - 1) * 100."""
        daily = _make_daily(["2026-06-10", "2026-06-11"], [100000.0, 100017.3])
        tmp = _make_data_dir_with_equity(daily)
        report = compute_report(tmp)
        r = (100017.3 - 100000.0) / 100000.0
        expected = ((1 + r) ** (365.0 / 2.0) - 1.0) * 100.0
        self.assertAlmostEqual(report["annualized_apy_pct"], round(expected, 4), places=3)

    def test_apy_single_day(self):
        """1-day track: APY = ((1 + r)^365 - 1) * 100."""
        daily = _make_daily(["2026-06-10"], [100000.0])
        # Force single entry — open_equity == close_equity → return 0
        tmp = _make_data_dir_with_equity(daily, adapter_apy=None)
        report = compute_report(tmp)
        # Single day, no gain → 0 annualised
        self.assertEqual(report["annualized_apy_pct"], 0.0)


# ─── Max Drawdown ─────────────────────────────────────────────────────────────

class TestMaxDrawdown(unittest.TestCase):

    def test_max_drawdown_no_drawdown(self):
        """Monotonically increasing equity → drawdown = 0."""
        equities = [100000.0 + i * 10 for i in range(10)]
        dates = [f"2026-06-{10 + i:02d}" for i in range(10)]
        daily = _make_daily(dates, equities)
        tmp = _make_data_dir_with_equity(daily, adapter_apy=None)
        report = compute_report(tmp)
        self.assertEqual(report["max_drawdown_pct"], 0.0)

    def test_max_drawdown_simple(self):
        """Peak 100K → trough 95K → max DD = 5%."""
        daily_raw = [
            {"date": "2026-06-10", "close_equity": 100000.0, "equity": 100000.0},
            {"date": "2026-06-11", "close_equity": 102000.0, "equity": 102000.0},
            {"date": "2026-06-12", "close_equity": 95000.0,  "equity": 95000.0},
            {"date": "2026-06-13", "close_equity": 96000.0,  "equity": 96000.0},
        ]
        result = compute_max_drawdown(daily_raw)
        # Peak = 102K, trough = 95K → (102K-95K)/102K * 100 ≈ 6.86%
        self.assertAlmostEqual(result, (102000 - 95000) / 102000 * 100, places=4)

    def test_max_drawdown_multiple_peaks(self):
        """Finds global maximum across multiple peaks and troughs."""
        daily_raw = [
            {"close_equity": 100000.0},
            {"close_equity": 105000.0},
            {"close_equity": 98000.0},   # dd1 ≈ 6.67%
            {"close_equity": 110000.0},
            {"close_equity": 90000.0},   # dd2 ≈ 18.18%
            {"close_equity": 95000.0},
        ]
        result = compute_max_drawdown(daily_raw)
        self.assertAlmostEqual(result, (110000 - 90000) / 110000 * 100, places=4)

    def test_max_drawdown_empty(self):
        """Empty daily list → drawdown = 0."""
        self.assertEqual(compute_max_drawdown([]), 0.0)

    def test_max_drawdown_function_direct(self):
        """compute_max_drawdown returns float."""
        daily = [{"close_equity": 100.0}, {"close_equity": 80.0}]
        result = compute_max_drawdown(daily)
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 20.0, places=4)


# ─── Sharpe Ratio ────────────────────────────────────────────────────────────

class TestSharpe(unittest.TestCase):

    def test_sharpe_none_below_30(self):
        """compute_sharpe returns None for n < 30."""
        returns = _make_returns(29, 0.01)
        self.assertIsNone(compute_sharpe(returns))

    def test_sharpe_computed_at_30(self):
        """compute_sharpe returns float for n == 30."""
        returns = _make_returns(30, 0.01)
        result = compute_sharpe(returns)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, float)

    def test_sharpe_none_zero_std(self):
        """compute_sharpe returns None when std == 0 (all-zero returns)."""
        # All returns exactly 0.0: mean=0, std=0 → undefined Sharpe → None
        returns = [0.0] * 30
        result = compute_sharpe(returns, min_obs=0)
        self.assertIsNone(result)

    def test_sharpe_positive_returns(self):
        """Positive mean returns → positive Sharpe."""
        import random
        rng = random.Random(42)
        returns = [rng.gauss(0.01, 0.005) for _ in range(50)]
        result = compute_sharpe(returns, min_obs=30)
        # Should be positive since mean ≈ 0.01
        self.assertGreater(result, 0.0)

    def test_sharpe_report_none_below_30_obs(self):
        """Full report: sharpe_ratio=None + sharpe_need_days=30 when n<30."""
        daily = _make_daily(
            [f"2026-06-{i+10:02d}" for i in range(5)],
            [100000.0 + i * 10 for i in range(5)],
        )
        tmp = _make_data_dir_with_equity(daily, adapter_apy=None)
        report = compute_report(tmp)
        self.assertIsNone(report["sharpe_ratio"])
        self.assertEqual(report["sharpe_need_days"], 30)


# ─── Sortino Ratio ───────────────────────────────────────────────────────────

class TestSortino(unittest.TestCase):

    def test_sortino_none_below_30(self):
        """compute_sortino returns None for n < 30."""
        returns = _make_returns(20, 0.01)
        self.assertIsNone(compute_sortino(returns))

    def test_sortino_none_no_downside_returns(self):
        """Sortino returns None when there are no negative returns."""
        returns = [0.01] * 30  # all positive
        self.assertIsNone(compute_sortino(returns, min_obs=0))

    def test_sortino_with_mixed_returns(self):
        """Sortino is computed when mixed returns provided and n >= 30."""
        returns = [0.01 if i % 3 != 0 else -0.005 for i in range(60)]
        result = compute_sortino(returns, min_obs=30)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, float)

    def test_sortino_report_none_below_30_obs(self):
        """Full report: sortino_ratio=None + sortino_need_days=30 when n<30."""
        daily = _make_daily(["2026-06-10", "2026-06-11"], [100000.0, 100010.0])
        tmp = _make_data_dir_with_equity(daily, adapter_apy=None)
        report = compute_report(tmp)
        self.assertIsNone(report["sortino_ratio"])
        self.assertEqual(report["sortino_need_days"], 30)


# ─── Calmar Ratio ────────────────────────────────────────────────────────────

class TestCalmar(unittest.TestCase):

    def test_calmar_none_below_365(self):
        """Full report: calmar_ratio=None + calmar_need_days=365 when n<365."""
        daily = _make_daily(["2026-06-10", "2026-06-11"], [100000.0, 100010.0])
        tmp = _make_data_dir_with_equity(daily, adapter_apy=None)
        report = compute_report(tmp)
        self.assertIsNone(report["calmar_ratio"])
        self.assertEqual(report["calmar_need_days"], 365)

    def test_calmar_none_zero_drawdown(self):
        """compute_calmar returns None when drawdown is 0."""
        self.assertIsNone(compute_calmar(5.0, 0.0))

    def test_calmar_formula(self):
        """compute_calmar = apy / drawdown."""
        result = compute_calmar(6.0, 2.0)
        self.assertAlmostEqual(result, 3.0, places=6)


# ─── Benchmark / Alpha ────────────────────────────────────────────────────────

class TestBenchmark(unittest.TestCase):

    def test_benchmark_loaded(self):
        """load_benchmark_apy reads Aave V3 USDC mock APY."""
        tmp = tempfile.mkdtemp()
        adapter = {
            "adapters": [{
                "protocol_key": "aave-v3",
                "mock_apy": {"ethereum": {"USDC": 4.2}},
            }]
        }
        with open(os.path.join(tmp, "adapter_status.json"), "w") as fh:
            json.dump(adapter, fh)
        result = load_benchmark_apy(tmp)
        self.assertAlmostEqual(result, 4.2, places=5)

    def test_benchmark_missing_file(self):
        """load_benchmark_apy returns None if file not found."""
        tmp = tempfile.mkdtemp()
        result = load_benchmark_apy(tmp)
        self.assertIsNone(result)

    def test_alpha_positive_when_above_benchmark(self):
        """alpha > 0 when annualised APY > benchmark."""
        daily = _make_daily(
            [f"2026-06-{10 + i:02d}" for i in range(5)],
            [100000.0 + i * 100 for i in range(5)],  # fast growth
        )
        # Write with very low benchmark so annualised beats it easily
        tmp = _make_data_dir_with_equity(daily, adapter_apy=0.1)
        report = compute_report(tmp)
        self.assertIsNotNone(report["alpha_vs_benchmark_pct"])
        self.assertGreater(report["alpha_vs_benchmark_pct"], 0.0)

    def test_alpha_none_without_benchmark(self):
        """alpha_vs_benchmark_pct is None when adapter_status.json missing."""
        daily = _make_daily(["2026-06-10", "2026-06-11"], [100000.0, 100010.0])
        tmp = _make_data_dir_with_equity(daily, adapter_apy=None)
        report = compute_report(tmp)
        self.assertIsNone(report["alpha_vs_benchmark_pct"])


# ─── Schema / N Observations ─────────────────────────────────────────────────

class TestSchema(unittest.TestCase):

    def test_required_keys_present(self):
        """Report contains all required keys."""
        daily = _make_daily(["2026-06-10", "2026-06-11"], [100000.0, 100010.0])
        tmp = _make_data_dir_with_equity(daily)
        report = compute_report(tmp)
        required = {
            "available", "generated_at", "track_start", "track_end",
            "track_days", "total_return_pct", "annualized_apy_pct",
            "max_drawdown_pct", "sharpe_ratio", "sharpe_need_days",
            "sortino_ratio", "sortino_need_days", "calmar_ratio",
            "calmar_need_days", "benchmark_apy_pct", "alpha_vs_benchmark_pct",
            "n_observations",
        }
        self.assertTrue(required.issubset(report.keys()), f"Missing: {required - report.keys()}")

    def test_n_observations(self):
        """n_observations == number of daily entries."""
        daily = _make_daily(
            [f"2026-06-{10 + i:02d}" for i in range(7)],
            [100000.0 + i * 5 for i in range(7)],
        )
        tmp = _make_data_dir_with_equity(daily, adapter_apy=None)
        report = compute_report(tmp)
        self.assertEqual(report["n_observations"], 7)

    def test_track_days_calculation(self):
        """track_days == (last_date - first_date).days + 1."""
        daily = _make_daily(
            ["2026-06-10", "2026-06-12", "2026-06-15"],  # gaps don't matter
            [100000.0, 100010.0, 100020.0],
        )
        tmp = _make_data_dir_with_equity(daily, adapter_apy=None)
        report = compute_report(tmp)
        # June 10 → June 15: 5 days diff + 1 = 6
        self.assertEqual(report["track_days"], 6)

    def test_available_false_on_empty_daily(self):
        """available=False returned when daily list is empty."""
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "equity_curve_daily.json"), "w") as fh:
            json.dump({"daily": []}, fh)
        report = compute_report(tmp)
        self.assertFalse(report["available"])

    def test_available_false_missing_file(self):
        """available=False returned when equity curve file not found."""
        tmp = tempfile.mkdtemp()
        report = compute_report(tmp)
        self.assertFalse(report["available"])


# ─── Atomic Write ────────────────────────────────────────────────────────────

class TestAtomicWrite(unittest.TestCase):

    def test_atomic_write_creates_file(self):
        """persist_report writes tear_sheet.json."""
        tmp = tempfile.mkdtemp()
        report = {"available": True, "test": 1}
        path = persist_report(report, tmp)
        self.assertTrue(os.path.exists(path))
        with open(path) as fh:
            loaded = json.load(fh)
        self.assertEqual(loaded["test"], 1)

    def test_atomic_write_no_tmp_leftover(self):
        """No .tmp files left after successful write."""
        tmp = tempfile.mkdtemp()
        persist_report({"available": True}, tmp)
        leftover = [f for f in os.listdir(tmp) if f.endswith(".tmp")]
        self.assertEqual(leftover, [])

    def test_atomic_write_overwrites_old(self):
        """Second write overwrites first."""
        tmp = tempfile.mkdtemp()
        persist_report({"available": True, "v": 1}, tmp)
        persist_report({"available": True, "v": 2}, tmp)
        out = os.path.join(tmp, "tear_sheet.json")
        with open(out) as fh:
            loaded = json.load(fh)
        self.assertEqual(loaded["v"], 2)


# ─── CLI ─────────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):

    def _run_main(self, args: list[str]) -> int:
        """Run main() with patched sys.argv; catch SystemExit and return code."""
        from spa_core.paper_trading import performance_report as pr
        with patch.object(sys, "argv", ["performance_report"] + args):
            try:
                pr.main()
                return 0
            except SystemExit as exc:
                return exc.code if exc.code is not None else 0

    def test_cli_check_exits_0(self):
        """--check exits 0."""
        daily = _make_daily(["2026-06-10", "2026-06-11"], [100000.0, 100010.0])
        tmp = _make_data_dir_with_equity(daily)
        code = self._run_main(["--check", "--data-dir", tmp])
        self.assertEqual(code, 0)

    def test_cli_check_no_file_written(self):
        """--check does not write tear_sheet.json."""
        daily = _make_daily(["2026-06-10", "2026-06-11"], [100000.0, 100010.0])
        tmp = _make_data_dir_with_equity(daily)
        self._run_main(["--check", "--data-dir", tmp])
        self.assertFalse(os.path.exists(os.path.join(tmp, "tear_sheet.json")))

    def test_cli_run_writes_file(self):
        """--run writes tear_sheet.json."""
        daily = _make_daily(["2026-06-10", "2026-06-11"], [100000.0, 100010.0])
        tmp = _make_data_dir_with_equity(daily)
        self._run_main(["--run", "--data-dir", tmp])
        self.assertTrue(os.path.exists(os.path.join(tmp, "tear_sheet.json")))

    def test_cli_run_exits_0(self):
        """--run exits 0."""
        daily = _make_daily(["2026-06-10", "2026-06-11"], [100000.0, 100010.0])
        tmp = _make_data_dir_with_equity(daily)
        code = self._run_main(["--run", "--data-dir", tmp])
        self.assertEqual(code, 0)

    def test_cli_run_valid_json(self):
        """--run writes valid JSON that loads correctly."""
        daily = _make_daily(["2026-06-10", "2026-06-11"], [100000.0, 100010.0])
        tmp = _make_data_dir_with_equity(daily)
        self._run_main(["--run", "--data-dir", tmp])
        out = os.path.join(tmp, "tear_sheet.json")
        with open(out) as fh:
            loaded = json.load(fh)
        self.assertIn("available", loaded)
        self.assertTrue(loaded["available"])


if __name__ == "__main__":
    unittest.main()
