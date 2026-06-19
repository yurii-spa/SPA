"""
tests/test_run_pit_backtest.py

35 unit tests for spa_core/backtesting/run_pit_backtest.py
MP-1310 (v9.26)

Test strategy:
- PITBacktestRunner with short periods (30 days) for speed-sensitive tests.
- Each test uses isolated tempfile.mkdtemp() for file-system tests.
- Full-period tests (default 2022→2026) used sparingly to keep suite fast.
- Structural correctness, performance, PIT stats, report format all covered.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spa_core.backtesting.run_pit_backtest import PITBacktestRunner


# ── Shared short-period runner (30 days from a fixed recent date) ──────────────
_SHORT_START = "2024-06-01"
_SHORT_END   = "2024-06-30"   # 30 days


class TestPITBacktestRunnerInit(unittest.TestCase):
    """Group 1: Constructor and class attributes."""

    def test_01_runner_creates_without_error(self) -> None:
        """PITBacktestRunner() instantiates with no arguments."""
        runner = PITBacktestRunner()
        self.assertIsNotNone(runner)

    def test_02_runner_default_start(self) -> None:
        """Default start date is '2022-05-01'."""
        runner = PITBacktestRunner()
        self.assertEqual(runner._start, "2022-05-01")

    def test_03_runner_default_end(self) -> None:
        """Default end date is '2026-05-05'."""
        runner = PITBacktestRunner()
        self.assertEqual(runner._end, "2026-05-05")

    def test_04_runner_default_capital(self) -> None:
        """Default initial_capital is 100_000.0."""
        runner = PITBacktestRunner()
        self.assertEqual(runner._initial_capital, 100_000.0)

    def test_05_runner_custom_params(self) -> None:
        """Custom constructor args are stored correctly."""
        runner = PITBacktestRunner(
            start=_SHORT_START, end=_SHORT_END, initial_capital=50_000.0
        )
        self.assertEqual(runner._start, _SHORT_START)
        self.assertEqual(runner._end, _SHORT_END)
        self.assertEqual(runner._initial_capital, 50_000.0)

    def test_06_runner_no_results_initially(self) -> None:
        """_results is None before run() is called."""
        runner = PITBacktestRunner()
        self.assertIsNone(runner._results)


class TestPITBacktestRunnerRun(unittest.TestCase):
    """Group 2: run() return structure and values."""

    @classmethod
    def setUpClass(cls) -> None:
        """Run once for the group — short period keeps it fast."""
        cls.runner = PITBacktestRunner(
            start=_SHORT_START, end=_SHORT_END, initial_capital=100_000.0
        )
        cls.result = cls.runner.run()

    def test_07_run_returns_dict(self) -> None:
        """run() returns a dict."""
        self.assertIsInstance(self.result, dict)

    def test_08_run_has_period_key(self) -> None:
        """Result contains 'period' key."""
        self.assertIn("period", self.result)

    def test_09_run_has_metrics_key(self) -> None:
        """Result contains 'metrics' key."""
        self.assertIn("metrics", self.result)

    def test_10_run_has_pit_stats_key(self) -> None:
        """Result contains 'pit_stats' key."""
        self.assertIn("pit_stats", self.result)

    def test_11_run_has_cash_days_pct_key(self) -> None:
        """Result contains 'cash_days_pct' key."""
        self.assertIn("cash_days_pct", self.result)

    def test_12_run_has_vs_cpa_key(self) -> None:
        """Result contains 'vs_cpa' key."""
        self.assertIn("vs_cpa", self.result)

    def test_13_period_start_matches_constructor(self) -> None:
        """period.start matches the start arg passed to constructor."""
        self.assertEqual(self.result["period"]["start"], _SHORT_START)

    def test_14_period_end_matches_constructor(self) -> None:
        """period.end matches the end arg passed to constructor."""
        self.assertEqual(self.result["period"]["end"], _SHORT_END)

    def test_15_cash_days_pct_is_positive(self) -> None:
        """cash_days_pct > 0 (cash buffer always maintained)."""
        self.assertGreater(self.result["cash_days_pct"], 0.0)

    def test_16_cash_days_pct_is_float(self) -> None:
        """cash_days_pct is a float."""
        self.assertIsInstance(self.result["cash_days_pct"], float)

    def test_17_cash_days_pct_max_100(self) -> None:
        """cash_days_pct ≤ 100.0 (sanity bound)."""
        self.assertLessEqual(self.result["cash_days_pct"], 100.0)


class TestPITPITStats(unittest.TestCase):
    """Group 3: pit_stats structure."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = PITBacktestRunner(
            start=_SHORT_START, end=_SHORT_END
        )
        cls.result = cls.runner.run()
        cls.pit = cls.result["pit_stats"]

    def test_18_pit_stats_has_total_protocols(self) -> None:
        """pit_stats contains 'total_protocols' int."""
        self.assertIn("total_protocols", self.pit)
        self.assertIsInstance(self.pit["total_protocols"], int)

    def test_19_pit_stats_total_protocols_positive(self) -> None:
        """total_protocols > 0."""
        self.assertGreater(self.pit["total_protocols"], 0)

    def test_20_pit_stats_has_per_protocol(self) -> None:
        """pit_stats contains 'per_protocol' dict."""
        self.assertIn("per_protocol", self.pit)
        self.assertIsInstance(self.pit["per_protocol"], dict)

    def test_21_per_protocol_has_kept_dropped(self) -> None:
        """Each per_protocol entry has 'kept' and 'dropped' keys."""
        for proto, stats in self.pit["per_protocol"].items():
            self.assertIn("kept", stats, f"'kept' missing for {proto}")
            self.assertIn("dropped", stats, f"'dropped' missing for {proto}")

    def test_22_pit_stats_has_total_rows(self) -> None:
        """pit_stats contains 'total_rows' int."""
        self.assertIn("total_rows", self.pit)
        self.assertIsInstance(self.pit["total_rows"], int)

    def test_23_pit_stats_has_kept_rows(self) -> None:
        """pit_stats contains 'kept_rows' int."""
        self.assertIn("kept_rows", self.pit)

    def test_24_pit_stats_has_dropped_rows(self) -> None:
        """pit_stats contains 'dropped_rows' int."""
        self.assertIn("dropped_rows", self.pit)

    def test_25_pit_stats_row_sum_consistent(self) -> None:
        """kept_rows + dropped_rows == total_rows."""
        self.assertEqual(
            self.pit["kept_rows"] + self.pit["dropped_rows"],
            self.pit["total_rows"],
        )


class TestPITVsCPA(unittest.TestCase):
    """Group 4: vs_cpa structure and values."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = PITBacktestRunner(start=_SHORT_START, end=_SHORT_END)
        cls.result = cls.runner.run()
        cls.vs = cls.result["vs_cpa"]

    def test_26_vs_cpa_has_cpa_apy(self) -> None:
        """vs_cpa contains 'cpa_apy'."""
        self.assertIn("cpa_apy", self.vs)

    def test_27_vs_cpa_has_pit_apy(self) -> None:
        """vs_cpa contains 'pit_apy'."""
        self.assertIn("pit_apy", self.vs)

    def test_28_vs_cpa_has_delta(self) -> None:
        """vs_cpa contains 'delta'."""
        self.assertIn("delta", self.vs)

    def test_29_vs_cpa_cpa_apy_is_float(self) -> None:
        """cpa_apy is a float."""
        self.assertIsInstance(self.vs["cpa_apy"], float)

    def test_30_vs_cpa_cpa_apy_approx_zero(self) -> None:
        """cpa_apy ≈ 0.0 (from gates — no backtest_gate.json present → default 0.0)."""
        # |cpa_apy| < 1.0 — conservative cash-proxy baseline
        self.assertLess(abs(self.vs["cpa_apy"]), 1.0)

    def test_31_vs_cpa_delta_equals_pit_minus_cpa(self) -> None:
        """delta == round(pit_apy - cpa_apy, 2)."""
        expected = round(self.vs["pit_apy"] - self.vs["cpa_apy"], 2)
        self.assertAlmostEqual(self.vs["delta"], expected, places=2)


class TestPITMetrics(unittest.TestCase):
    """Group 5: metrics dict structure."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = PITBacktestRunner(start=_SHORT_START, end=_SHORT_END)
        cls.result = cls.runner.run()
        cls.m = cls.result["metrics"]

    def test_32_metrics_has_total_return_pct(self) -> None:
        """metrics contains 'total_return_pct'."""
        self.assertIn("total_return_pct", self.m)

    def test_33_metrics_has_apy(self) -> None:
        """metrics contains 'apy'."""
        self.assertIn("apy", self.m)

    def test_34_metrics_has_max_dd(self) -> None:
        """metrics contains 'max_dd'."""
        self.assertIn("max_dd", self.m)

    def test_35_metrics_has_sharpe(self) -> None:
        """metrics contains 'sharpe'."""
        self.assertIn("sharpe", self.m)


class TestPITSaveResults(unittest.TestCase):
    """Group 6: save_results() atomic write."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.runner = PITBacktestRunner(start=_SHORT_START, end=_SHORT_END)
        self.runner.run()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_36_save_results_creates_file(self) -> None:
        """save_results() creates the output file."""
        out = os.path.join(self.tmpdir, "pit_results.json")
        self.runner.save_results(path=out)
        self.assertTrue(os.path.exists(out))

    def test_37_save_results_valid_json(self) -> None:
        """Saved file is valid JSON."""
        out = os.path.join(self.tmpdir, "pit_results.json")
        self.runner.save_results(path=out)
        with open(out, encoding="utf-8") as fh:
            parsed = json.load(fh)
        self.assertIsInstance(parsed, dict)

    def test_38_save_results_custom_path(self) -> None:
        """Custom save path is respected."""
        out = os.path.join(self.tmpdir, "subdir", "custom.json")
        self.runner.save_results(path=out)
        self.assertTrue(os.path.exists(out))

    def test_39_save_results_before_run_raises(self) -> None:
        """save_results() before run() raises ValueError."""
        fresh = PITBacktestRunner(start=_SHORT_START, end=_SHORT_END)
        with self.assertRaises(ValueError):
            fresh.save_results(path=os.path.join(self.tmpdir, "x.json"))


class TestPITGenerateReport(unittest.TestCase):
    """Group 7: generate_report() content."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = PITBacktestRunner(start=_SHORT_START, end=_SHORT_END)
        cls.runner.run()
        cls.report = cls.runner.generate_report()

    def test_40_generate_report_returns_string(self) -> None:
        """generate_report() returns a str."""
        self.assertIsInstance(self.report, str)

    def test_41_generate_report_has_markdown_header(self) -> None:
        """Report contains a # markdown header."""
        self.assertIn("#", self.report)

    def test_42_generate_report_has_period(self) -> None:
        """Report mentions the backtest period dates."""
        self.assertIn(_SHORT_START, self.report)
        self.assertIn(_SHORT_END, self.report)

    def test_43_generate_report_has_metrics_section(self) -> None:
        """Report contains the Metrics section."""
        self.assertIn("Metric", self.report)

    def test_44_generate_report_before_run_raises(self) -> None:
        """generate_report() before run() raises ValueError."""
        fresh = PITBacktestRunner(start=_SHORT_START, end=_SHORT_END)
        with self.assertRaises(ValueError):
            fresh.generate_report()


class TestPITPerformance(unittest.TestCase):
    """Group 8: Performance — 30-day run < 5 seconds."""

    def test_45_short_period_runs_fast(self) -> None:
        """A 30-day backtest completes in under 5 seconds."""
        runner = PITBacktestRunner(
            start=_SHORT_START, end=_SHORT_END, initial_capital=100_000.0
        )
        t0 = time.time()
        runner.run()
        elapsed = time.time() - t0
        self.assertLess(elapsed, 5.0, f"30-day PIT backtest took {elapsed:.2f}s (limit 5s)")


class TestPITProtocolFilter(unittest.TestCase):
    """Group 9: run() with protocol filter."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = PITBacktestRunner(start=_SHORT_START, end=_SHORT_END)
        # Filter to a single T1 protocol eligible in June 2024
        cls.result = cls.runner.run(protocols=["aave_v3_usdc"])

    def test_46_run_with_protocol_filter_returns_dict(self) -> None:
        """run(protocols=[...]) returns a dict."""
        self.assertIsInstance(self.result, dict)

    def test_47_run_with_protocol_filter_has_all_keys(self) -> None:
        """Filtered run result has all required top-level keys."""
        for key in ("period", "metrics", "pit_stats", "cash_days_pct", "vs_cpa"):
            self.assertIn(key, self.result)

    def test_48_run_second_call_updates_results(self) -> None:
        """Second run() call updates _results with new data."""
        runner = PITBacktestRunner(start=_SHORT_START, end=_SHORT_END)
        r1 = runner.run(protocols=["aave_v3_usdc"])
        r2 = runner.run(protocols=["compound_v2_usdc"])
        # Both should be dicts; second call replaces first
        self.assertIsInstance(r1, dict)
        self.assertIsInstance(r2, dict)
        self.assertIs(runner._results, r2)

    def test_49_pit_dropped_rows_exist_for_newer_protocols(self) -> None:
        """Protocols launched after backtest start have dropped rows."""
        # Run from 2022-05-01 so newer protocols have pre-launch rows to drop
        runner = PITBacktestRunner(
            start="2022-05-01", end="2022-07-31"  # short, early — Morpho not launched
        )
        result = runner.run(protocols=["morpho_blue"])
        # morpho_blue launched 2023-11-07, so ALL rows should be dropped
        pit = result["pit_stats"]
        self.assertEqual(pit["kept_rows"], 0)
        self.assertGreater(pit["dropped_rows"], 0)

    def test_50_results_json_serializable(self) -> None:
        """run() results are JSON-serializable (no non-standard types)."""
        runner = PITBacktestRunner(start=_SHORT_START, end=_SHORT_END)
        result = runner.run()
        # Must not raise
        serialized = json.dumps(result)
        self.assertIsInstance(serialized, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
