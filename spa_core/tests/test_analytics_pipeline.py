#!/usr/bin/env python3
"""
test_analytics_pipeline.py — Unit tests for AnalyticsPipeline (MP-663).

≥ 40 tests covering:
  - instantiation
  - _load_positions / _load_apy_history with missing / malformed files
  - run() output shape and correctness
  - ring-buffer capping
  - atomic write (tmp + os.replace)
  - per-module isolation (one failure doesn't stop others)
  - portfolio summary totals
  - report key presence

Run:
    python3 -m unittest spa_core.tests.test_analytics_pipeline -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Make repo root importable regardless of cwd
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.analytics_pipeline import (
    AnalyticsPipeline,
    MAX_REPORT_HISTORY,
    _load_positions,
    _load_apy_history,
    _load_status,
    _load_adapter_status,
    _to_dict,
    _build_adapter_liquidities,
    _build_protocol_inputs,
    _build_allocation_slots,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_data_dir() -> Path:
    """Create a temporary directory and return its Path."""
    tmp = tempfile.mkdtemp(prefix="spa_test_pipeline_")
    return Path(tmp)


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj), encoding="utf-8")


_SAMPLE_POSITIONS_DICT = {
    "generated_at": "2026-06-13T06:00:00+00:00",
    "is_demo": False,
    "capital_usd": 100_000.0,
    "positions": {
        "aave_v3": 40_000.0,
        "compound_v3": 35_000.0,
        "yearn_v3": 20_000.0,
    },
}

_SAMPLE_EQUITY_CURVE = {
    "daily": [
        {"date": "2026-06-10", "apy_today": 3.80, "equity_usd": 100_010.0},
        {"date": "2026-06-11", "apy_today": 3.90, "equity_usd": 100_020.0},
        {"date": "2026-06-12", "apy_today": 3.95, "equity_usd": 100_030.0},
        {"date": "2026-06-13", "apy_today": 4.00, "equity_usd": 100_040.0},
    ]
}

_SAMPLE_STATUS = {
    "is_demo": False,
    "current_equity": 100_040.0,
    "apy_today_pct": 4.00,
    "days_running": 4,
}

_REQUIRED_REPORT_KEYS = {
    "timestamp", "run_at", "elapsed_sec",
    "portfolio_summary", "modules_run", "modules_failed", "results",
}

_REQUIRED_SUMMARY_KEYS = {
    "total_capital_usd", "current_apy", "current_apy_pct",
    "positions_count", "positions",
}

_REQUIRED_RESULT_KEYS = {
    "volatility_regime", "liquidity_stress", "collateral_health",
    "protocol_risk_scores", "apy_momentum", "yield_benchmarks",
    "drawdown_episodes", "apy_forecast", "rebalance_trigger",
    "slippage_estimates", "gas_cost_estimate", "chain_fee_comparison",
}


# ===========================================================================
# 1. Instantiation
# ===========================================================================

class TestInstantiation(unittest.TestCase):

    def test_default_instantiation(self):
        """AnalyticsPipeline() should construct without error."""
        pipeline = AnalyticsPipeline()
        self.assertIsInstance(pipeline, AnalyticsPipeline)

    def test_custom_data_dir(self):
        """Custom data_dir is stored correctly."""
        dd = _tmp_data_dir()
        pipeline = AnalyticsPipeline(data_dir=dd)
        self.assertEqual(pipeline.data_dir, dd)

    def test_custom_report_file(self):
        """Custom report_file is stored correctly."""
        dd = _tmp_data_dir()
        rf = dd / "custom_report.json"
        pipeline = AnalyticsPipeline(data_dir=dd, report_file=rf)
        self.assertEqual(pipeline.report_file, rf)

    def test_default_report_file_is_in_data_dir(self):
        """Default report file lives inside data_dir."""
        dd = _tmp_data_dir()
        pipeline = AnalyticsPipeline(data_dir=dd)
        self.assertEqual(pipeline.report_file.parent, dd)


# ===========================================================================
# 2. Data loaders — missing files
# ===========================================================================

class TestLoadersWithMissingFiles(unittest.TestCase):

    def setUp(self):
        self.dd = _tmp_data_dir()

    def test_load_positions_missing_file_returns_empty(self):
        result = _load_positions(self.dd)
        self.assertEqual(result, {})

    def test_load_apy_history_missing_file_returns_empty(self):
        result = _load_apy_history(self.dd)
        self.assertEqual(result, [])

    def test_load_status_missing_file_returns_empty_dict(self):
        result = _load_status(self.dd)
        self.assertEqual(result, {})

    def test_load_adapter_status_missing_file_returns_empty_dict(self):
        result = _load_adapter_status(self.dd)
        self.assertEqual(result, {})

    def test_pipeline_load_positions_missing(self):
        pipeline = AnalyticsPipeline(data_dir=self.dd)
        self.assertEqual(pipeline._load_positions(), {})

    def test_pipeline_load_apy_history_missing(self):
        pipeline = AnalyticsPipeline(data_dir=self.dd)
        self.assertEqual(pipeline._load_apy_history(), [])


# ===========================================================================
# 3. Data loaders — correct parsing
# ===========================================================================

class TestLoadersWithFiles(unittest.TestCase):

    def setUp(self):
        self.dd = _tmp_data_dir()

    def test_load_positions_nested_dict(self):
        _write_json(self.dd / "current_positions.json", _SAMPLE_POSITIONS_DICT)
        result = _load_positions(self.dd)
        self.assertIn("aave_v3", result)
        self.assertAlmostEqual(result["aave_v3"], 40_000.0)
        self.assertAlmostEqual(result["compound_v3"], 35_000.0)

    def test_load_positions_flat_dict(self):
        flat = {"aave_v3": 50_000.0, "compound_v3": 50_000.0}
        _write_json(self.dd / "current_positions.json", flat)
        result = _load_positions(self.dd)
        self.assertAlmostEqual(result["aave_v3"], 50_000.0)

    def test_load_positions_list_shape(self):
        lst = [
            {"adapter_id": "aave_v3", "capital_usd": 60_000.0},
            {"adapter_id": "euler_v2", "capital_usd": 40_000.0},
        ]
        _write_json(self.dd / "current_positions.json", lst)
        result = _load_positions(self.dd)
        self.assertAlmostEqual(result["aave_v3"], 60_000.0)
        self.assertAlmostEqual(result["euler_v2"], 40_000.0)

    def test_load_apy_history_correct_values(self):
        _write_json(self.dd / "equity_curve_daily.json", _SAMPLE_EQUITY_CURVE)
        result = _load_apy_history(self.dd)
        self.assertEqual(len(result), 4)
        # 3.80% → 0.0380
        self.assertAlmostEqual(result[0], 0.0380, places=5)
        self.assertAlmostEqual(result[-1], 0.0400, places=5)

    def test_load_apy_history_list_shape(self):
        lst = [{"apy_today": 5.0}, {"apy_today": 6.0}]
        _write_json(self.dd / "equity_curve_daily.json", {"daily": lst})
        result = _load_apy_history(self.dd)
        self.assertAlmostEqual(result[0], 0.05, places=5)


# ===========================================================================
# 4. run() — all data files missing
# ===========================================================================

class TestRunWithNoData(unittest.TestCase):

    def setUp(self):
        self.dd = _tmp_data_dir()
        self.pipeline = AnalyticsPipeline(data_dir=self.dd)

    def test_run_completes_without_exception(self):
        """run() must not raise even when all data files are missing."""
        report = self.pipeline.run()
        self.assertIsNotNone(report)

    def test_run_returns_dict(self):
        report = self.pipeline.run()
        self.assertIsInstance(report, dict)

    def test_run_has_required_keys(self):
        report = self.pipeline.run()
        for key in _REQUIRED_REPORT_KEYS:
            self.assertIn(key, report, f"Missing key: {key}")

    def test_run_modules_run_is_nonnegative_int(self):
        report = self.pipeline.run()
        self.assertIsInstance(report["modules_run"], int)
        self.assertGreaterEqual(report["modules_run"], 0)

    def test_run_modules_failed_is_int(self):
        report = self.pipeline.run()
        self.assertIsInstance(report["modules_failed"], int)

    def test_run_modules_run_at_least_one(self):
        report = self.pipeline.run()
        self.assertGreaterEqual(report["modules_run"], 1)

    def test_run_timestamp_is_float(self):
        report = self.pipeline.run()
        self.assertIsInstance(report["timestamp"], float)

    def test_run_timestamp_is_recent(self):
        before = time.time()
        report = self.pipeline.run()
        after = time.time()
        self.assertGreaterEqual(report["timestamp"], before)
        self.assertLessEqual(report["timestamp"], after)

    def test_run_has_results_key(self):
        report = self.pipeline.run()
        self.assertIn("results", report)
        self.assertIsInstance(report["results"], dict)

    def test_run_results_has_all_expected_keys(self):
        report = self.pipeline.run()
        results = report["results"]
        for key in _REQUIRED_RESULT_KEYS:
            self.assertIn(key, results, f"Missing results key: {key}")

    def test_run_portfolio_summary_has_required_keys(self):
        report = self.pipeline.run()
        summary = report["portfolio_summary"]
        for key in _REQUIRED_SUMMARY_KEYS:
            self.assertIn(key, summary, f"Missing summary key: {key}")

    def test_run_elapsed_sec_nonnegative(self):
        report = self.pipeline.run()
        self.assertGreaterEqual(report["elapsed_sec"], 0)

    def test_report_written_to_disk(self):
        self.pipeline.run()
        self.assertTrue(self.pipeline.report_file.exists(),
                        "Report file should be created")

    def test_report_on_disk_is_valid_json(self):
        self.pipeline.run()
        content = self.pipeline.report_file.read_text(encoding="utf-8")
        data = json.loads(content)
        self.assertIsInstance(data, list)

    def test_report_on_disk_has_one_entry_after_first_run(self):
        self.pipeline.run()
        data = json.loads(self.pipeline.report_file.read_text())
        self.assertEqual(len(data), 1)


# ===========================================================================
# 5. run() — with real sample data
# ===========================================================================

class TestRunWithSampleData(unittest.TestCase):

    def setUp(self):
        self.dd = _tmp_data_dir()
        _write_json(self.dd / "current_positions.json", _SAMPLE_POSITIONS_DICT)
        _write_json(self.dd / "equity_curve_daily.json", _SAMPLE_EQUITY_CURVE)
        _write_json(self.dd / "paper_trading_status.json", _SAMPLE_STATUS)
        self.pipeline = AnalyticsPipeline(data_dir=self.dd)

    def test_run_with_data_completes(self):
        report = self.pipeline.run()
        self.assertIsNotNone(report)

    def test_portfolio_summary_capital_matches(self):
        report = self.pipeline.run()
        # current_equity from status
        self.assertAlmostEqual(
            report["portfolio_summary"]["total_capital_usd"], 100_040.0, places=1
        )

    def test_portfolio_summary_positions_count(self):
        report = self.pipeline.run()
        self.assertEqual(report["portfolio_summary"]["positions_count"], 3)

    def test_portfolio_summary_apy_reasonable(self):
        report = self.pipeline.run()
        apy = report["portfolio_summary"]["current_apy"]
        self.assertGreater(apy, 0)
        self.assertLess(apy, 1.0)  # fractional, not percent

    def test_modules_run_reasonable(self):
        report = self.pipeline.run()
        # At minimum the chain_fee and gas modules should always succeed
        self.assertGreaterEqual(report["modules_run"], 3)

    def test_modules_failed_is_integer(self):
        report = self.pipeline.run()
        self.assertIsInstance(report["modules_failed"], int)


# ===========================================================================
# 6. Ring-buffer and persistence
# ===========================================================================

class TestRingBuffer(unittest.TestCase):

    def setUp(self):
        self.dd = _tmp_data_dir()
        self.pipeline = AnalyticsPipeline(data_dir=self.dd)

    def test_ring_buffer_grows_with_runs(self):
        self.pipeline.run()
        self.pipeline.run()
        data = json.loads(self.pipeline.report_file.read_text())
        self.assertEqual(len(data), 2)

    def test_ring_buffer_capped_at_max(self):
        """After MAX_REPORT_HISTORY + 5 runs, file has exactly MAX_REPORT_HISTORY entries."""
        for _ in range(MAX_REPORT_HISTORY + 5):
            self.pipeline.run()
        data = json.loads(self.pipeline.report_file.read_text())
        self.assertEqual(len(data), MAX_REPORT_HISTORY)

    def test_ring_buffer_keeps_latest(self):
        """The most recently appended report should be last in the list."""
        self.pipeline.run()
        before = time.time()
        self.pipeline.run()
        data = json.loads(self.pipeline.report_file.read_text())
        last_ts = data[-1]["timestamp"]
        self.assertGreaterEqual(last_ts, before)

    def test_atomic_write_no_tmp_file_leftover(self):
        """After a successful write, no .tmp file should remain."""
        self.pipeline.run()
        tmp = self.pipeline.report_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists(), ".tmp file should be cleaned up")

    def test_existing_non_list_json_is_recovered(self):
        """If the existing report file contains a non-list, it is replaced cleanly."""
        self.pipeline.report_file.write_text('{"bad": "json"}', encoding="utf-8")
        self.pipeline.run()
        data = json.loads(self.pipeline.report_file.read_text())
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)


# ===========================================================================
# 7. Per-module isolation
# ===========================================================================

class TestModuleIsolation(unittest.TestCase):

    def setUp(self):
        self.dd = _tmp_data_dir()
        self.pipeline = AnalyticsPipeline(data_dir=self.dd)

    def test_one_module_failure_doesnt_prevent_others(self):
        """If one module raises, modules_run should still be > 0."""
        original = self.pipeline._run_volatility_regime

        def _failing_regime(apy_history):
            raise RuntimeError("simulated failure")

        self.pipeline._run_volatility_regime = _failing_regime
        report = self.pipeline.run()
        # Other modules should still have run
        self.assertGreater(report["modules_run"], 0)
        self.assertGreaterEqual(report["modules_failed"], 1)

    def test_failed_module_tracked_in_count(self):
        """A module that raises increments modules_failed."""
        def _failing(*_a, **_kw):
            raise RuntimeError("boom")

        self.pipeline._run_chain_fees = _failing
        report = self.pipeline.run()
        self.assertGreaterEqual(report["modules_failed"], 1)

    def test_run_module_returns_error_dict_on_failure(self):
        """_run_module captures errors into a dict with 'error' key."""
        def _boom():
            raise ValueError("test error")

        result = self.pipeline._run_module("test", _boom)
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)
        self.assertIn("test error", result["error"])


# ===========================================================================
# 8. _build_report structure
# ===========================================================================

class TestBuildReport(unittest.TestCase):

    def setUp(self):
        self.dd = _tmp_data_dir()
        self.pipeline = AnalyticsPipeline(data_dir=self.dd)

    def test_build_report_structure(self):
        report = self.pipeline._build_report(
            positions={"aave_v3": 50_000.0},
            total_capital=50_000.0,
            portfolio_apy=0.05,
            results={"volatility_regime": {"regime": "NORMAL"}},
            elapsed_sec=0.5,
        )
        self.assertIn("timestamp", report)
        self.assertIn("portfolio_summary", report)
        self.assertIn("modules_run", report)
        self.assertIn("modules_failed", report)
        self.assertIn("results", report)

    def test_build_report_portfolio_values(self):
        report = self.pipeline._build_report(
            positions={"aave_v3": 40_000.0, "compound_v3": 60_000.0},
            total_capital=100_000.0,
            portfolio_apy=0.045,
            results={},
            elapsed_sec=1.2,
        )
        summary = report["portfolio_summary"]
        self.assertAlmostEqual(summary["total_capital_usd"], 100_000.0)
        self.assertAlmostEqual(summary["current_apy_pct"], 4.5, places=4)
        self.assertEqual(summary["positions_count"], 2)

    def test_build_report_elapsed_stored(self):
        report = self.pipeline._build_report(
            positions={}, total_capital=0.0, portfolio_apy=0.0,
            results={}, elapsed_sec=3.14,
        )
        self.assertAlmostEqual(report["elapsed_sec"], 3.14, places=5)


# ===========================================================================
# 9. _to_dict helper
# ===========================================================================

class TestToDict(unittest.TestCase):

    def test_primitive_passthrough(self):
        self.assertEqual(_to_dict(42), 42)
        self.assertEqual(_to_dict("hello"), "hello")
        self.assertEqual(_to_dict(3.14), 3.14)
        self.assertEqual(_to_dict(True), True)
        self.assertIsNone(_to_dict(None))

    def test_list_passthrough(self):
        self.assertEqual(_to_dict([1, 2, 3]), [1, 2, 3])

    def test_dict_passthrough(self):
        d = {"a": 1, "b": "x"}
        self.assertEqual(_to_dict(d), d)

    def test_dataclass_converted(self):
        from dataclasses import dataclass

        @dataclass
        class Dummy:
            x: int
            y: str

        result = _to_dict(Dummy(x=7, y="hello"))
        self.assertIsInstance(result, dict)
        self.assertEqual(result["x"], 7)
        self.assertEqual(result["y"], "hello")


# ===========================================================================
# 10. Input-builder helpers
# ===========================================================================

class TestInputBuilders(unittest.TestCase):

    def test_build_adapter_liquidities_known_adapter(self):
        positions = {"aave_v3": 50_000.0, "yearn_v3": 30_000.0}
        adapters = _build_adapter_liquidities(positions)
        self.assertEqual(len(adapters), 2)
        ids = {a.adapter_id for a in adapters}
        self.assertIn("aave_v3", ids)

    def test_build_adapter_liquidities_t1_lock_zero(self):
        adapters = _build_adapter_liquidities({"aave_v3": 10_000.0})
        self.assertEqual(adapters[0].lock_days, 0)
        self.assertEqual(adapters[0].tier, "T1")

    def test_build_adapter_liquidities_unknown_defaults_t2(self):
        adapters = _build_adapter_liquidities({"unknown_proto": 5_000.0})
        self.assertEqual(adapters[0].tier, "T2")

    def test_build_protocol_inputs_returns_list(self):
        positions = {"aave_v3": 40_000.0, "compound_v3": 60_000.0}
        protocols = _build_protocol_inputs(positions)
        self.assertEqual(len(protocols), 2)

    def test_build_allocation_slots_equal_weight_target(self):
        positions = {"aave_v3": 60_000.0, "euler_v2": 40_000.0}
        slots = _build_allocation_slots(positions, 100_000.0)
        self.assertEqual(len(slots), 2)
        # Equal target = 0.5 each
        for slot in slots:
            self.assertAlmostEqual(slot.target_pct, 0.5, places=5)

    def test_build_allocation_slots_empty_positions(self):
        slots = _build_allocation_slots({}, 0.0)
        self.assertEqual(slots, [])


# ===========================================================================
# 11. Chain fee / gas modules run without positions
# ===========================================================================

class TestIndependentModules(unittest.TestCase):
    """Gas and chain fee modules don't depend on position data."""

    def setUp(self):
        self.dd = _tmp_data_dir()
        self.pipeline = AnalyticsPipeline(data_dir=self.dd)

    def test_chain_fee_result_is_dict(self):
        result = self.pipeline._run_chain_fees()
        self.assertIsInstance(result, dict)

    def test_chain_fee_no_error_key(self):
        result = self.pipeline._run_chain_fees()
        # Should succeed; no 'error' key expected
        self.assertNotIn("error", result)

    def test_gas_cost_result_is_dict(self):
        result = self.pipeline._run_gas_cost(100_000.0, 0.04)
        self.assertIsInstance(result, dict)

    def test_gas_cost_no_error_key(self):
        result = self.pipeline._run_gas_cost(100_000.0, 0.04)
        self.assertNotIn("error", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
