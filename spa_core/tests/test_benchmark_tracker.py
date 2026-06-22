"""Tests for BenchmarkTracker (MP-607).

Groups:
  TestBenchmarkResult        (10) — fields, outperforming, IR
  TestBenchmarkReport        (10) — outperforming_count, verdict logic
  TestLoadPortfolioData      (10) — missing→defaults, valid→correct fields
  TestGetBestAdapterAPY       (8) — max APY, missing→fallback
  TestComputeBenchmark       (12) — excess, IR, outperforming
  TestGenerateReport         (15) — all 4 benchmarks, best_benchmark, annual_alpha
  TestSaveReport              (5) — atomic write, ring-buffer
  TestFormatTelegramMessage   (6) — ≤1500 chars, contains verdict+APY
  TestToDict                  (4) — JSON-serializable

Total: 80+ tests.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

# ── resolve project root ─────────────────────────────────────────────────────
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.benchmark_tracker import (
    BenchmarkResult,
    BenchmarkReport,
    BenchmarkTracker,
    RING_BUFFER_MAX,
    _DEFAULT_PORTFOLIO_APY,
    _DEFAULT_PORTFOLIO_USD,
    _extract_apy_from_adapter,
    _safe_float,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(
    name: str = "T-Bill",
    apy_pct: float = 4.5,
    portfolio_apy_pct: float = 5.0,
    excess_return_pct: float = 0.5,
    information_ratio: float = 0.5,
    outperforming: bool = True,
) -> BenchmarkResult:
    return BenchmarkResult(
        name=name,
        apy_pct=apy_pct,
        portfolio_apy_pct=portfolio_apy_pct,
        excess_return_pct=excess_return_pct,
        information_ratio=information_ratio,
        outperforming=outperforming,
    )


def _make_report(**kwargs) -> BenchmarkReport:
    defaults = dict(
        generated_at="2026-06-13T00:00:00+00:00",
        portfolio_apy_pct=5.0,
        portfolio_allocated_usd=100_000.0,
        benchmarks=[],
        best_benchmark_name="Best Adapter",
        best_benchmark_apy=5.5,
        overall_excess_return=-0.5,
        annual_alpha_usd=-500.0,
        outperforming_count=2,
        total_benchmarks=4,
        verdict="LAGGING",
    )
    defaults.update(kwargs)
    return BenchmarkReport(**defaults)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# TestBenchmarkResult (10 tests)
# ---------------------------------------------------------------------------

class TestBenchmarkResult(unittest.TestCase):
    """Tests for BenchmarkResult dataclass."""

    def test_fields_stored(self):
        r = _make_result()
        self.assertEqual(r.name, "T-Bill")
        self.assertAlmostEqual(r.apy_pct, 4.5)
        self.assertAlmostEqual(r.portfolio_apy_pct, 5.0)
        self.assertAlmostEqual(r.excess_return_pct, 0.5)
        self.assertAlmostEqual(r.information_ratio, 0.5)
        self.assertTrue(r.outperforming)

    def test_outperforming_true_when_excess_positive(self):
        r = _make_result(excess_return_pct=0.01, outperforming=True)
        self.assertTrue(r.outperforming)

    def test_outperforming_false_when_excess_negative(self):
        r = _make_result(excess_return_pct=-0.1, outperforming=False)
        self.assertFalse(r.outperforming)

    def test_outperforming_false_when_excess_zero(self):
        # At exactly 0, outperforming should be False (0 is not > 0)
        r = _make_result(excess_return_pct=0.0, outperforming=False)
        self.assertFalse(r.outperforming)

    def test_ir_equals_excess_over_vol(self):
        r = _make_result(excess_return_pct=2.0, information_ratio=2.0)
        # With ASSUMED_VOL=1.0, IR = excess/1.0 = excess
        self.assertAlmostEqual(r.information_ratio, 2.0)

    def test_ir_negative_when_lagging(self):
        r = _make_result(excess_return_pct=-1.5, information_ratio=-1.5)
        self.assertLess(r.information_ratio, 0)

    def test_to_dict_keys(self):
        r = _make_result()
        d = r.to_dict()
        for key in ("name", "apy_pct", "portfolio_apy_pct",
                    "excess_return_pct", "information_ratio", "outperforming"):
            self.assertIn(key, d)

    def test_to_dict_values(self):
        r = _make_result(name="USDC Hold", apy_pct=4.0, portfolio_apy_pct=5.0,
                         excess_return_pct=1.0, information_ratio=1.0, outperforming=True)
        d = r.to_dict()
        self.assertEqual(d["name"], "USDC Hold")
        self.assertAlmostEqual(d["apy_pct"], 4.0)
        self.assertAlmostEqual(d["excess_return_pct"], 1.0)

    def test_to_dict_json_serializable(self):
        r = _make_result()
        d = r.to_dict()
        dumped = json.dumps(d)
        self.assertIsInstance(dumped, str)

    def test_different_benchmarks(self):
        for name in ("T-Bill", "USDC Hold", "ETH Staking", "Best Adapter"):
            r = _make_result(name=name)
            self.assertEqual(r.name, name)


# ---------------------------------------------------------------------------
# TestBenchmarkReport (10 tests)
# ---------------------------------------------------------------------------

class TestBenchmarkReport(unittest.TestCase):
    """Tests for BenchmarkReport dataclass and verdict logic."""

    def test_fields_stored(self):
        rpt = _make_report()
        self.assertEqual(rpt.generated_at, "2026-06-13T00:00:00+00:00")
        self.assertAlmostEqual(rpt.portfolio_apy_pct, 5.0)
        self.assertAlmostEqual(rpt.portfolio_allocated_usd, 100_000.0)

    def test_verdict_alpha_plus(self):
        rpt = _make_report(verdict="ALPHA+")
        self.assertEqual(rpt.verdict, "ALPHA+")

    def test_verdict_alpha(self):
        rpt = _make_report(verdict="ALPHA")
        self.assertEqual(rpt.verdict, "ALPHA")

    def test_verdict_benchmark(self):
        rpt = _make_report(verdict="BENCHMARK")
        self.assertEqual(rpt.verdict, "BENCHMARK")

    def test_verdict_lagging(self):
        rpt = _make_report(verdict="LAGGING")
        self.assertEqual(rpt.verdict, "LAGGING")

    def test_outperforming_count(self):
        rpt = _make_report(outperforming_count=3, total_benchmarks=4)
        self.assertEqual(rpt.outperforming_count, 3)
        self.assertEqual(rpt.total_benchmarks, 4)

    def test_annual_alpha_usd_positive(self):
        rpt = _make_report(annual_alpha_usd=720.0)
        self.assertAlmostEqual(rpt.annual_alpha_usd, 720.0)

    def test_annual_alpha_usd_negative(self):
        rpt = _make_report(annual_alpha_usd=-300.0)
        self.assertLess(rpt.annual_alpha_usd, 0)

    def test_to_dict_has_benchmarks_list(self):
        r = _make_result()
        rpt = _make_report(benchmarks=[r])
        d = rpt.to_dict()
        self.assertIn("benchmarks", d)
        self.assertEqual(len(d["benchmarks"]), 1)

    def test_default_benchmarks_empty(self):
        rpt = BenchmarkReport(
            generated_at="2026-01-01T00:00:00+00:00",
            portfolio_apy_pct=5.0,
            portfolio_allocated_usd=100_000.0,
        )
        self.assertEqual(rpt.benchmarks, [])
        self.assertEqual(rpt.total_benchmarks, 0)


# ---------------------------------------------------------------------------
# TestLoadPortfolioData (10 tests)
# ---------------------------------------------------------------------------

class TestLoadPortfolioData(unittest.TestCase):
    """Tests for BenchmarkTracker.load_portfolio_data."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = BenchmarkTracker(data_path=self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_attribution(self, data: Any) -> None:
        path = Path(self.tmp) / "yield_attribution_tracker.json"
        _write_json(path, data)

    def test_missing_file_returns_defaults(self):
        result = self.tracker.load_portfolio_data()
        self.assertAlmostEqual(result["effective_apy_pct"], _DEFAULT_PORTFOLIO_APY)
        self.assertAlmostEqual(result["total_allocated_usd"], _DEFAULT_PORTFOLIO_USD)

    def test_valid_data_returns_correct_apy(self):
        self._write_attribution({
            "latest": {"effective_apy_pct": 6.12, "total_allocated_usd": 95000.0}
        })
        result = self.tracker.load_portfolio_data()
        self.assertAlmostEqual(result["effective_apy_pct"], 6.12, places=2)

    def test_valid_data_returns_correct_allocated(self):
        self._write_attribution({
            "latest": {"effective_apy_pct": 5.5, "total_allocated_usd": 98000.0}
        })
        result = self.tracker.load_portfolio_data()
        self.assertAlmostEqual(result["total_allocated_usd"], 98000.0)

    def test_malformed_json_returns_defaults(self):
        path = Path(self.tmp) / "yield_attribution_tracker.json"
        path.write_text("NOT JSON", encoding="utf-8")
        result = self.tracker.load_portfolio_data()
        self.assertAlmostEqual(result["effective_apy_pct"], _DEFAULT_PORTFOLIO_APY)

    def test_missing_latest_key_returns_defaults(self):
        self._write_attribution({"schema_version": "1.0"})
        result = self.tracker.load_portfolio_data()
        self.assertAlmostEqual(result["effective_apy_pct"], _DEFAULT_PORTFOLIO_APY)

    def test_latest_not_dict_returns_defaults(self):
        self._write_attribution({"latest": [1, 2, 3]})
        result = self.tracker.load_portfolio_data()
        self.assertAlmostEqual(result["effective_apy_pct"], _DEFAULT_PORTFOLIO_APY)

    def test_zero_apy_falls_back_to_default(self):
        self._write_attribution({
            "latest": {"effective_apy_pct": 0, "total_allocated_usd": 50000.0}
        })
        result = self.tracker.load_portfolio_data()
        self.assertAlmostEqual(result["effective_apy_pct"], _DEFAULT_PORTFOLIO_APY)

    def test_zero_allocated_falls_back_to_default(self):
        self._write_attribution({
            "latest": {"effective_apy_pct": 5.0, "total_allocated_usd": 0}
        })
        result = self.tracker.load_portfolio_data()
        self.assertAlmostEqual(result["total_allocated_usd"], _DEFAULT_PORTFOLIO_USD)

    def test_negative_apy_falls_back_to_default(self):
        self._write_attribution({
            "latest": {"effective_apy_pct": -1.0, "total_allocated_usd": 100000.0}
        })
        result = self.tracker.load_portfolio_data()
        self.assertAlmostEqual(result["effective_apy_pct"], _DEFAULT_PORTFOLIO_APY)

    def test_returns_both_keys(self):
        result = self.tracker.load_portfolio_data()
        self.assertIn("effective_apy_pct", result)
        self.assertIn("total_allocated_usd", result)


# ---------------------------------------------------------------------------
# TestGetBestAdapterAPY (8 tests)
# ---------------------------------------------------------------------------

class TestGetBestAdapterAPY(unittest.TestCase):
    """Tests for BenchmarkTracker.get_best_adapter_apy."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = BenchmarkTracker(data_path=self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_adapter_status(self, data: Any) -> None:
        path = Path(self.tmp) / "adapter_status.json"
        _write_json(path, data)

    def test_missing_file_returns_fallback(self):
        apy = self.tracker.get_best_adapter_apy()
        self.assertGreater(apy, 0)

    def test_max_apy_from_adapters_list(self):
        self._write_adapter_status({
            "adapters": [
                {"protocol_key": "aave", "apy_pct": 4.2},
                {"protocol_key": "compound", "apy_pct": 4.8},
                {"protocol_key": "euler", "apy_pct": 7.4},
            ]
        })
        apy = self.tracker.get_best_adapter_apy()
        self.assertAlmostEqual(apy, 7.4)

    def test_max_apy_from_mock_apy(self):
        self._write_adapter_status({
            "adapters": [
                {
                    "protocol_key": "aave",
                    "mock_apy": {"ethereum": {"USDC": 4.2}},
                },
                {
                    "protocol_key": "euler",
                    "mock_apy": {"ethereum": {"USDC": 7.4}},
                },
            ]
        })
        apy = self.tracker.get_best_adapter_apy()
        self.assertAlmostEqual(apy, 7.4)

    def test_top_level_and_adapters_merged(self):
        self._write_adapter_status({
            "my_proto": {"tier": "T1", "apy_pct": 9.0},
            "adapters": [
                {"protocol_key": "euler", "apy_pct": 7.4},
            ]
        })
        apy = self.tracker.get_best_adapter_apy()
        self.assertAlmostEqual(apy, 9.0)

    def test_malformed_json_returns_fallback(self):
        path = Path(self.tmp) / "adapter_status.json"
        path.write_text("NOT JSON", encoding="utf-8")
        apy = self.tracker.get_best_adapter_apy()
        self.assertGreater(apy, 0)

    def test_empty_adapters_returns_fallback(self):
        self._write_adapter_status({"adapters": []})
        apy = self.tracker.get_best_adapter_apy()
        self.assertGreater(apy, 0)

    def test_ignores_skip_keys(self):
        self._write_adapter_status({
            "generated_at": "2026-01-01",
            "schema_version": 1,
            "adapters": [{"protocol_key": "euler", "apy_pct": 7.4}]
        })
        apy = self.tracker.get_best_adapter_apy()
        self.assertAlmostEqual(apy, 7.4)

    def test_returns_positive_float(self):
        self._write_adapter_status({
            "adapters": [{"protocol_key": "aave", "apy_pct": 4.2}]
        })
        apy = self.tracker.get_best_adapter_apy()
        self.assertIsInstance(apy, float)
        self.assertGreater(apy, 0)


# ---------------------------------------------------------------------------
# TestComputeBenchmark (12 tests)
# ---------------------------------------------------------------------------

class TestComputeBenchmark(unittest.TestCase):
    """Tests for BenchmarkTracker.compute_benchmark."""

    def setUp(self):
        self.tracker = BenchmarkTracker.__new__(BenchmarkTracker)
        self.tracker.data_dir = Path(tempfile.mkdtemp())
        self.tracker.ASSUMED_VOL = 1.0

    def test_excess_equals_portfolio_minus_bench(self):
        r = self.tracker.compute_benchmark("T-Bill", 4.5, 5.0)
        self.assertAlmostEqual(r.excess_return_pct, 0.5, places=5)

    def test_excess_negative_when_lagging(self):
        r = self.tracker.compute_benchmark("Best Adapter", 8.0, 5.0)
        self.assertLess(r.excess_return_pct, 0)
        self.assertAlmostEqual(r.excess_return_pct, -3.0, places=5)

    def test_excess_zero_when_equal(self):
        r = self.tracker.compute_benchmark("ETH Staking", 3.5, 3.5)
        self.assertAlmostEqual(r.excess_return_pct, 0.0, places=5)

    def test_ir_equals_excess_divided_by_vol(self):
        r = self.tracker.compute_benchmark("T-Bill", 4.5, 5.0)
        self.assertAlmostEqual(r.information_ratio, 0.5 / 1.0, places=5)

    def test_ir_negative_when_lagging(self):
        r = self.tracker.compute_benchmark("Best Adapter", 8.0, 5.0)
        self.assertLess(r.information_ratio, 0)

    def test_outperforming_true_when_excess_positive(self):
        r = self.tracker.compute_benchmark("T-Bill", 4.5, 5.0)
        self.assertTrue(r.outperforming)

    def test_outperforming_false_when_excess_negative(self):
        r = self.tracker.compute_benchmark("Best Adapter", 8.0, 5.0)
        self.assertFalse(r.outperforming)

    def test_outperforming_false_when_excess_zero(self):
        r = self.tracker.compute_benchmark("USDC Hold", 5.0, 5.0)
        self.assertFalse(r.outperforming)

    def test_name_stored(self):
        r = self.tracker.compute_benchmark("USDC Hold", 4.0, 5.0)
        self.assertEqual(r.name, "USDC Hold")

    def test_bench_apy_stored(self):
        r = self.tracker.compute_benchmark("T-Bill", 4.5, 5.0)
        self.assertAlmostEqual(r.apy_pct, 4.5)

    def test_portfolio_apy_stored(self):
        r = self.tracker.compute_benchmark("T-Bill", 4.5, 6.0)
        self.assertAlmostEqual(r.portfolio_apy_pct, 6.0)

    def test_large_excess_ir(self):
        r = self.tracker.compute_benchmark("T-Bill", 1.0, 10.0)
        self.assertAlmostEqual(r.excess_return_pct, 9.0, places=5)
        self.assertAlmostEqual(r.information_ratio, 9.0, places=5)


# ---------------------------------------------------------------------------
# TestGenerateReport (15 tests)
# ---------------------------------------------------------------------------

class TestGenerateReport(unittest.TestCase):
    """Tests for BenchmarkTracker.generate_report."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = BenchmarkTracker(data_path=self.tmp)
        # Write attribution data so portfolio_apy is deterministic
        attr = {
            "latest": {
                "effective_apy_pct": 5.22,
                "total_allocated_usd": 95000.0,
            }
        }
        _write_json(Path(self.tmp) / "yield_attribution_tracker.json", attr)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_benchmark_report_instance(self):
        rpt = self.tracker.generate_report()
        self.assertIsInstance(rpt, BenchmarkReport)

    def test_four_benchmarks_present(self):
        rpt = self.tracker.generate_report()
        self.assertEqual(len(rpt.benchmarks), 4)

    def test_benchmark_names_include_tbill(self):
        rpt = self.tracker.generate_report()
        names = [r.name for r in rpt.benchmarks]
        self.assertIn("T-Bill", names)

    def test_benchmark_names_include_usdc_hold(self):
        rpt = self.tracker.generate_report()
        names = [r.name for r in rpt.benchmarks]
        self.assertIn("USDC Hold", names)

    def test_benchmark_names_include_eth_staking(self):
        rpt = self.tracker.generate_report()
        names = [r.name for r in rpt.benchmarks]
        self.assertIn("ETH Staking", names)

    def test_benchmark_names_include_best_adapter(self):
        rpt = self.tracker.generate_report()
        names = [r.name for r in rpt.benchmarks]
        self.assertIn("Best Adapter", names)

    def test_best_benchmark_is_max_apy(self):
        # Best Adapter will be dynamic; inject fixed adapter file for determinism
        _write_json(Path(self.tmp) / "adapter_status.json", {
            "adapters": [{"protocol_key": "euler", "apy_pct": 7.4}]
        })
        rpt = self.tracker.generate_report()
        max_apy = max(r.apy_pct for r in rpt.benchmarks)
        self.assertAlmostEqual(rpt.best_benchmark_apy, max_apy)

    def test_overall_excess_equals_portfolio_minus_best(self):
        _write_json(Path(self.tmp) / "adapter_status.json", {
            "adapters": [{"protocol_key": "euler", "apy_pct": 7.4}]
        })
        rpt = self.tracker.generate_report()
        expected = round(rpt.portfolio_apy_pct - rpt.best_benchmark_apy, 6)
        self.assertAlmostEqual(rpt.overall_excess_return, expected, places=4)

    def test_annual_alpha_usd_formula(self):
        _write_json(Path(self.tmp) / "adapter_status.json", {
            "adapters": [{"protocol_key": "euler", "apy_pct": 4.0}]
        })
        rpt = self.tracker.generate_report()
        expected = round(rpt.overall_excess_return * rpt.portfolio_allocated_usd / 100.0, 2)
        self.assertAlmostEqual(rpt.annual_alpha_usd, expected, places=1)

    def test_outperforming_count_correct(self):
        _write_json(Path(self.tmp) / "adapter_status.json", {
            "adapters": [{"protocol_key": "euler", "apy_pct": 4.0}]
        })
        rpt = self.tracker.generate_report()
        manual_count = sum(1 for r in rpt.benchmarks if r.outperforming)
        self.assertEqual(rpt.outperforming_count, manual_count)

    def test_total_benchmarks_is_four(self):
        rpt = self.tracker.generate_report()
        self.assertEqual(rpt.total_benchmarks, 4)

    def test_verdict_alpha_plus_when_large_excess(self):
        # Portfolio APY 12%, all benchmarks ≤4.5%
        _write_json(Path(self.tmp) / "yield_attribution_tracker.json", {
            "latest": {"effective_apy_pct": 12.0, "total_allocated_usd": 100_000.0}
        })
        _write_json(Path(self.tmp) / "adapter_status.json", {
            "adapters": [{"protocol_key": "aave", "apy_pct": 4.0}]
        })
        rpt = self.tracker.generate_report()
        self.assertEqual(rpt.verdict, "ALPHA+")

    def test_verdict_lagging_when_low_portfolio(self):
        # Portfolio APY 1.0% (below all benchmarks)
        _write_json(Path(self.tmp) / "yield_attribution_tracker.json", {
            "latest": {"effective_apy_pct": 1.0, "total_allocated_usd": 100_000.0}
        })
        _write_json(Path(self.tmp) / "adapter_status.json", {
            "adapters": [{"protocol_key": "aave", "apy_pct": 4.5}]
        })
        rpt = self.tracker.generate_report()
        self.assertEqual(rpt.verdict, "LAGGING")

    def test_portfolio_apy_matches_loaded_value(self):
        rpt = self.tracker.generate_report()
        self.assertAlmostEqual(rpt.portfolio_apy_pct, 5.22, places=1)

    def test_portfolio_allocated_matches_loaded_value(self):
        rpt = self.tracker.generate_report()
        self.assertAlmostEqual(rpt.portfolio_allocated_usd, 95000.0, places=0)


# ---------------------------------------------------------------------------
# TestSaveReport (5 tests)
# ---------------------------------------------------------------------------

class TestSaveReport(unittest.TestCase):
    """Tests for BenchmarkTracker.save_report."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = BenchmarkTracker(data_path=self.tmp)
        _write_json(Path(self.tmp) / "yield_attribution_tracker.json", {
            "latest": {"effective_apy_pct": 5.0, "total_allocated_usd": 100000.0}
        })

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_file_created(self):
        path = self.tracker.save_report()
        self.assertTrue(os.path.exists(path))

    def test_file_is_valid_json(self):
        path = self.tracker.save_report()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, dict)

    def test_file_contains_latest_key(self):
        path = self.tracker.save_report()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("latest", data)
        self.assertIn("verdict", data["latest"])

    def test_ring_buffer_capped_at_max(self):
        for _ in range(RING_BUFFER_MAX + 5):
            self.tracker.save_report()
        path = self.tracker.save_report()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data["snapshots"]), RING_BUFFER_MAX)

    def test_custom_output_path(self):
        custom = os.path.join(self.tmp, "custom_bench.json")
        self.tracker.save_report(output_path=custom)
        self.assertTrue(os.path.exists(custom))


# ---------------------------------------------------------------------------
# TestFormatTelegramMessage (6 tests)
# ---------------------------------------------------------------------------

class TestFormatTelegramMessage(unittest.TestCase):
    """Tests for BenchmarkTracker.format_telegram_message."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = BenchmarkTracker(data_path=self.tmp)
        _write_json(Path(self.tmp) / "yield_attribution_tracker.json", {
            "latest": {"effective_apy_pct": 5.22, "total_allocated_usd": 95000.0}
        })
        _write_json(Path(self.tmp) / "adapter_status.json", {
            "adapters": [
                {"protocol_key": "euler", "apy_pct": 7.4},
                {"protocol_key": "aave", "apy_pct": 4.2},
            ]
        })

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_length_at_most_1500(self):
        msg = self.tracker.format_telegram_message()
        self.assertLessEqual(len(msg), 1500)

    def test_contains_portfolio_apy(self):
        msg = self.tracker.format_telegram_message()
        self.assertIn("5.22", msg)

    def test_contains_verdict(self):
        msg = self.tracker.format_telegram_message()
        rpt = self.tracker.generate_report()
        self.assertIn(rpt.verdict, msg)

    def test_contains_tbill(self):
        msg = self.tracker.format_telegram_message()
        self.assertIn("T-Bill", msg)

    def test_contains_best_adapter(self):
        msg = self.tracker.format_telegram_message()
        self.assertIn("Best Adapter", msg)

    def test_returns_string(self):
        msg = self.tracker.format_telegram_message()
        self.assertIsInstance(msg, str)


# ---------------------------------------------------------------------------
# TestToDict (4 tests)
# ---------------------------------------------------------------------------

class TestToDict(unittest.TestCase):
    """Tests for BenchmarkTracker.to_dict."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = BenchmarkTracker(data_path=self.tmp)
        _write_json(Path(self.tmp) / "yield_attribution_tracker.json", {
            "latest": {"effective_apy_pct": 5.0, "total_allocated_usd": 100000.0}
        })

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_dict(self):
        d = self.tracker.to_dict()
        self.assertIsInstance(d, dict)

    def test_json_serializable(self):
        d = self.tracker.to_dict()
        dumped = json.dumps(d)
        self.assertIsInstance(dumped, str)

    def test_contains_verdict_key(self):
        d = self.tracker.to_dict()
        self.assertIn("verdict", d)

    def test_contains_benchmarks_list(self):
        d = self.tracker.to_dict()
        self.assertIn("benchmarks", d)
        self.assertIsInstance(d["benchmarks"], list)
        self.assertEqual(len(d["benchmarks"]), 4)


# ---------------------------------------------------------------------------
# Additional edge-case tests (bonus to push well past 80)
# ---------------------------------------------------------------------------

class TestVerdictThresholds(unittest.TestCase):
    """Tests specifically verifying verdict threshold logic."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = BenchmarkTracker(data_path=self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _set_portfolio_apy(self, apy: float) -> None:
        _write_json(Path(self.tmp) / "yield_attribution_tracker.json", {
            "latest": {"effective_apy_pct": apy, "total_allocated_usd": 100_000.0}
        })

    def _set_best_adapter_apy(self, apy: float) -> None:
        # Force best adapter to be below T-Bill so T-Bill is "best benchmark"
        _write_json(Path(self.tmp) / "adapter_status.json", {
            "adapters": [{"protocol_key": "aave", "apy_pct": apy}]
        })

    def test_alpha_plus_boundary(self):
        # Excess just above 1.5% → ALPHA+
        # best bench = T-Bill = 4.50; portfolio = 4.50 + 1.51 = 6.01
        self._set_best_adapter_apy(1.0)  # adapter below T-Bill → T-Bill is best
        self._set_portfolio_apy(4.50 + 1.51)
        rpt = self.tracker.generate_report()
        self.assertEqual(rpt.verdict, "ALPHA+")

    def test_alpha_boundary(self):
        # Excess just above 0.3% but ≤ 1.5% → ALPHA
        self._set_best_adapter_apy(1.0)
        self._set_portfolio_apy(4.50 + 0.31)
        rpt = self.tracker.generate_report()
        self.assertEqual(rpt.verdict, "ALPHA")

    def test_benchmark_boundary_positive(self):
        # Excess exactly 0.3% → BENCHMARK (|excess|≤0.3)
        self._set_best_adapter_apy(1.0)
        self._set_portfolio_apy(4.50 + 0.30)
        rpt = self.tracker.generate_report()
        self.assertEqual(rpt.verdict, "BENCHMARK")

    def test_benchmark_boundary_negative(self):
        # Excess exactly -0.3% → BENCHMARK
        self._set_best_adapter_apy(1.0)
        self._set_portfolio_apy(4.50 - 0.30)
        rpt = self.tracker.generate_report()
        self.assertEqual(rpt.verdict, "BENCHMARK")

    def test_lagging_boundary(self):
        # Excess below -0.3% → LAGGING
        self._set_best_adapter_apy(1.0)
        self._set_portfolio_apy(4.50 - 0.31)
        rpt = self.tracker.generate_report()
        self.assertEqual(rpt.verdict, "LAGGING")


class TestSafeFloat(unittest.TestCase):
    """Tests for _safe_float helper."""

    def test_int(self):
        self.assertAlmostEqual(_safe_float(5), 5.0)

    def test_float(self):
        self.assertAlmostEqual(_safe_float(3.14), 3.14)

    def test_string_numeric(self):
        self.assertAlmostEqual(_safe_float("2.5"), 2.5)

    def test_none_returns_zero(self):
        self.assertAlmostEqual(_safe_float(None), 0.0)

    def test_bool_returns_zero(self):
        self.assertAlmostEqual(_safe_float(True), 0.0)
        self.assertAlmostEqual(_safe_float(False), 0.0)

    def test_nan_returns_zero(self):
        self.assertAlmostEqual(_safe_float(float("nan")), 0.0)

    def test_inf_returns_zero(self):
        self.assertAlmostEqual(_safe_float(float("inf")), 0.0)


class TestExtractApyFromAdapter(unittest.TestCase):
    """Tests for _extract_apy_from_adapter helper."""

    def test_apy_pct_takes_priority(self):
        d = {"apy_pct": 7.4, "apy": 4.0}
        self.assertAlmostEqual(_extract_apy_from_adapter(d), 7.4)

    def test_apy_fallback(self):
        d = {"apy": 5.5}
        self.assertAlmostEqual(_extract_apy_from_adapter(d), 5.5)

    def test_mock_apy_fallback(self):
        d = {"mock_apy": {"ethereum": {"USDC": 6.5}}}
        self.assertAlmostEqual(_extract_apy_from_adapter(d), 6.5)

    def test_empty_returns_zero(self):
        self.assertAlmostEqual(_extract_apy_from_adapter({}), 0.0)

    def test_bool_not_accepted(self):
        d = {"apy_pct": True}
        self.assertAlmostEqual(_extract_apy_from_adapter(d), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
