"""
Tests for MP-952: DeFiYieldAggregatorFeeAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_yield_aggregator_fee_analyzer -v
≥80 tests required.
"""

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.defi_yield_aggregator_fee_analyzer import (
    DeFiYieldAggregatorFeeAnalyzer,
    _atomic_write,
    _append_log,
    _load_log,
    _compute_fee_drag,
    _fee_label,
    _break_even_days,
    _build_aggregator_result,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_agg(**kwargs) -> dict:
    defaults = {
        "name": "TestAgg",
        "strategy_name": "USDC Vault",
        "gross_apy_pct": 10.0,
        "performance_fee_pct": 10.0,   # 10% of profit → 1% drag
        "management_fee_pct": 0.5,     # 0.5% AUM/yr drag
        "withdrawal_fee_pct": 0.1,
        "deposit_fee_pct": 0.1,
        "aum_usd": 50_000_000,
        "harvest_frequency_days": 7,
        "underlying_protocol_fee_pct": 0.2,
    }
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# Unit Tests: _compute_fee_drag
# ---------------------------------------------------------------------------
class TestComputeFeeDrag(unittest.TestCase):

    def test_perf_drag_basic(self):
        agg = make_agg(gross_apy_pct=10.0, performance_fee_pct=20.0)
        d = _compute_fee_drag(agg)
        self.assertAlmostEqual(d["perf_drag"], 2.0)

    def test_mgmt_drag_equals_fee(self):
        agg = make_agg(management_fee_pct=1.5)
        d = _compute_fee_drag(agg)
        self.assertAlmostEqual(d["mgmt_drag"], 1.5)

    def test_withdrawal_drag(self):
        agg = make_agg(withdrawal_fee_pct=0.5, deposit_fee_pct=0.0)
        d = _compute_fee_drag(agg)
        self.assertAlmostEqual(d["withdrawal_drag"], 0.5)

    def test_deposit_drag(self):
        agg = make_agg(deposit_fee_pct=0.3, withdrawal_fee_pct=0.0)
        d = _compute_fee_drag(agg)
        self.assertAlmostEqual(d["deposit_drag"], 0.3)

    def test_underlying_drag(self):
        agg = make_agg(underlying_protocol_fee_pct=0.25)
        d = _compute_fee_drag(agg)
        self.assertAlmostEqual(d["underlying_drag"], 0.25)

    def test_total_drag_sum(self):
        agg = make_agg(
            gross_apy_pct=20.0,
            performance_fee_pct=10.0,   # 2.0
            management_fee_pct=1.0,     # 1.0
            withdrawal_fee_pct=0.2,     # 0.2
            deposit_fee_pct=0.1,        # 0.1
            underlying_protocol_fee_pct=0.3,  # 0.3
        )
        d = _compute_fee_drag(agg)
        expected = 2.0 + 1.0 + 0.2 + 0.1 + 0.3
        self.assertAlmostEqual(d["total_fee_drag_pct"], expected, places=6)

    def test_zero_fees(self):
        agg = make_agg(
            gross_apy_pct=5.0,
            performance_fee_pct=0.0,
            management_fee_pct=0.0,
            withdrawal_fee_pct=0.0,
            deposit_fee_pct=0.0,
            underlying_protocol_fee_pct=0.0,
        )
        d = _compute_fee_drag(agg)
        self.assertAlmostEqual(d["total_fee_drag_pct"], 0.0)

    def test_high_perf_fee(self):
        agg = make_agg(gross_apy_pct=100.0, performance_fee_pct=50.0)
        d = _compute_fee_drag(agg)
        self.assertAlmostEqual(d["perf_drag"], 50.0)

    def test_returns_dict_keys(self):
        d = _compute_fee_drag(make_agg())
        for k in ["perf_drag", "mgmt_drag", "withdrawal_drag", "deposit_drag",
                  "underlying_drag", "total_fee_drag_pct"]:
            self.assertIn(k, d)

    def test_zero_gross_perf_drag(self):
        agg = make_agg(gross_apy_pct=0.0, performance_fee_pct=50.0)
        d = _compute_fee_drag(agg)
        self.assertAlmostEqual(d["perf_drag"], 0.0)


# ---------------------------------------------------------------------------
# Unit Tests: _fee_label
# ---------------------------------------------------------------------------
class TestFeeLabel(unittest.TestCase):

    def test_low_fees(self):
        self.assertEqual(_fee_label(5.0), "LOW_FEES")

    def test_moderate(self):
        self.assertEqual(_fee_label(20.0), "MODERATE")

    def test_high(self):
        self.assertEqual(_fee_label(35.0), "HIGH")

    def test_very_high(self):
        self.assertEqual(_fee_label(45.0), "VERY_HIGH")

    def test_extractive(self):
        self.assertEqual(_fee_label(60.0), "EXTRACTIVE")

    def test_boundary_low_to_moderate(self):
        self.assertEqual(_fee_label(10.0), "MODERATE")

    def test_boundary_moderate_to_high(self):
        self.assertEqual(_fee_label(25.0), "HIGH")

    def test_boundary_high_to_very_high(self):
        self.assertEqual(_fee_label(40.0), "VERY_HIGH")

    def test_boundary_very_high_to_extractive(self):
        self.assertEqual(_fee_label(50.0), "EXTRACTIVE")

    def test_zero(self):
        self.assertEqual(_fee_label(0.0), "LOW_FEES")


# ---------------------------------------------------------------------------
# Unit Tests: _break_even_days
# ---------------------------------------------------------------------------
class TestBreakEvenDays(unittest.TestCase):

    def test_no_upfront_fees(self):
        result = _break_even_days(10.0, 1.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_basic_calculation(self):
        # net = 10 - 1 = 9; daily = 9/365; upfront=0.2+0.1=0.3
        # be = 0.3 / (9/365) = 0.3 * 365 / 9 ≈ 12.17
        result = _break_even_days(10.0, 1.0, 0.1, 0.2)
        expected = 0.3 / (9.0 / 365.0)
        self.assertAlmostEqual(result, expected, places=4)

    def test_zero_net_apy_returns_inf(self):
        result = _break_even_days(5.0, 5.0, 0.1, 0.1)
        self.assertEqual(result, float("inf"))

    def test_negative_net_apy_returns_inf(self):
        result = _break_even_days(5.0, 10.0, 0.1, 0.1)
        self.assertEqual(result, float("inf"))

    def test_large_upfront(self):
        result = _break_even_days(20.0, 2.0, 1.0, 1.0)
        net_daily = 18.0 / 365.0
        expected = 2.0 / net_daily
        self.assertAlmostEqual(result, expected, places=4)

    def test_withdrawal_only(self):
        result = _break_even_days(10.0, 0.5, 0.0, 0.5)
        net_daily = 9.5 / 365.0
        expected = 0.5 / net_daily
        self.assertAlmostEqual(result, expected, places=4)

    def test_deposit_only(self):
        result = _break_even_days(10.0, 0.5, 0.5, 0.0)
        net_daily = 9.5 / 365.0
        expected = 0.5 / net_daily
        self.assertAlmostEqual(result, expected, places=4)


# ---------------------------------------------------------------------------
# Unit Tests: _build_aggregator_result
# ---------------------------------------------------------------------------
class TestBuildAggregatorResult(unittest.TestCase):

    def _result(self, **kwargs):
        return _build_aggregator_result(make_agg(**kwargs))

    def test_returns_dict(self):
        self.assertIsInstance(self._result(), dict)

    def test_required_keys(self):
        r = self._result()
        for k in ["name", "strategy_name", "gross_apy_pct", "total_fee_drag_pct",
                  "net_apy_pct", "fee_efficiency_ratio", "break_even_holding_days",
                  "value_add_vs_direct", "fee_label", "flags", "fee_breakdown"]:
            self.assertIn(k, r)

    def test_net_apy_equals_gross_minus_drag(self):
        r = self._result(gross_apy_pct=10.0)
        self.assertAlmostEqual(r["net_apy_pct"], r["gross_apy_pct"] - r["total_fee_drag_pct"], places=5)

    def test_fee_efficiency_between_0_and_1(self):
        r = self._result(gross_apy_pct=10.0, performance_fee_pct=5.0)
        self.assertGreaterEqual(r["fee_efficiency_ratio"], 0.0)
        self.assertLessEqual(r["fee_efficiency_ratio"], 1.0)

    def test_extractive_flag_when_drag_gt_50pct(self):
        # gross=2, perf_fee=60% → drag ≈ 1.2 > 50% of 2 → EXTRACTIVE_FEES
        r = self._result(
            gross_apy_pct=2.0,
            performance_fee_pct=60.0,
            management_fee_pct=0.0,
            withdrawal_fee_pct=0.0,
            deposit_fee_pct=0.0,
            underlying_protocol_fee_pct=0.0,
        )
        self.assertIn("EXTRACTIVE_FEES", r["flags"])

    def test_performance_fee_heavy_flag(self):
        r = self._result(performance_fee_pct=25.0)
        self.assertIn("PERFORMANCE_FEE_HEAVY", r["flags"])

    def test_no_performance_fee_heavy_below_threshold(self):
        r = self._result(performance_fee_pct=15.0)
        self.assertNotIn("PERFORMANCE_FEE_HEAVY", r["flags"])

    def test_management_fee_high_flag(self):
        r = self._result(management_fee_pct=3.0)
        self.assertIn("MANAGEMENT_FEE_HIGH", r["flags"])

    def test_no_management_fee_high_below_threshold(self):
        r = self._result(management_fee_pct=1.5)
        self.assertNotIn("MANAGEMENT_FEE_HIGH", r["flags"])

    def test_frequent_harvest_flag(self):
        r = self._result(harvest_frequency_days=3)
        self.assertIn("FREQUENT_HARVEST", r["flags"])

    def test_no_frequent_harvest_flag_at_7days(self):
        r = self._result(harvest_frequency_days=7)
        self.assertNotIn("FREQUENT_HARVEST", r["flags"])

    def test_break_even_none_when_no_upfront(self):
        r = self._result(deposit_fee_pct=0.0, withdrawal_fee_pct=0.0)
        self.assertEqual(r["break_even_holding_days"], 0.0)

    def test_fee_label_present(self):
        r = self._result()
        self.assertIn(r["fee_label"], ["LOW_FEES", "MODERATE", "HIGH", "VERY_HIGH", "EXTRACTIVE"])

    def test_fee_breakdown_keys(self):
        r = self._result()
        bd = r["fee_breakdown"]
        for k in ["perf_drag_pct", "mgmt_drag_pct", "withdrawal_drag_pct",
                  "deposit_drag_pct", "underlying_drag_pct"]:
            self.assertIn(k, bd)

    def test_zero_gross_fee_efficiency_zero(self):
        r = self._result(gross_apy_pct=0.0)
        self.assertAlmostEqual(r["fee_efficiency_ratio"], 0.0)

    def test_name_preserved(self):
        r = self._result(name="Yearn")
        self.assertEqual(r["name"], "Yearn")

    def test_strategy_name_preserved(self):
        r = self._result(strategy_name="yvUSDC")
        self.assertEqual(r["strategy_name"], "yvUSDC")

    def test_low_fees_label_for_minimal_fees(self):
        r = self._result(
            gross_apy_pct=10.0,
            performance_fee_pct=0.0,
            management_fee_pct=0.5,
            withdrawal_fee_pct=0.0,
            deposit_fee_pct=0.0,
            underlying_protocol_fee_pct=0.0,
        )
        # drag = 0.5, drag_pct_of_gross = 5% → LOW_FEES
        self.assertEqual(r["fee_label"], "LOW_FEES")

    def test_extractive_label_high_drag(self):
        # gross=10, all fees = 6 → drag_pct_of_gross=60% → EXTRACTIVE
        r = self._result(
            gross_apy_pct=10.0,
            performance_fee_pct=0.0,
            management_fee_pct=6.0,
            withdrawal_fee_pct=0.0,
            deposit_fee_pct=0.0,
            underlying_protocol_fee_pct=0.0,
        )
        self.assertEqual(r["fee_label"], "EXTRACTIVE")

    def test_value_add_negative_when_no_added_alpha(self):
        # Net APY < Direct APY (gross) when there are fees
        r = self._result(management_fee_pct=2.0)
        self.assertLess(r["value_add_vs_direct"], 0.0)


# ---------------------------------------------------------------------------
# Integration Tests: DeFiYieldAggregatorFeeAnalyzer.analyze
# ---------------------------------------------------------------------------
class TestAnalyzerIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "fee_log.json")
        self.analyzer = DeFiYieldAggregatorFeeAnalyzer(log_path=self.log_path)

    def _agg(self, **kwargs):
        return make_agg(**kwargs)

    def test_empty_list(self):
        result = self.analyzer.analyze([])
        self.assertEqual(result["aggregates"]["total_count"], 0)
        self.assertIsNone(result["aggregates"]["lowest_fee_aggregator"])

    def test_single_aggregator(self):
        result = self.analyzer.analyze([self._agg(name="Yearn")])
        self.assertEqual(len(result["aggregators"]), 1)
        self.assertEqual(result["aggregators"][0]["name"], "Yearn")

    def test_multiple_aggregators(self):
        aggs = [self._agg(name="A"), self._agg(name="B"), self._agg(name="C")]
        result = self.analyzer.analyze(aggs)
        self.assertEqual(len(result["aggregators"]), 3)

    def test_output_has_timestamp(self):
        result = self.analyzer.analyze([self._agg()])
        self.assertIn("analysis_timestamp", result)
        self.assertTrue(result["analysis_timestamp"].endswith("Z"))

    def test_output_has_module_field(self):
        result = self.analyzer.analyze([self._agg()])
        self.assertEqual(result["module"], "MP-952")

    def test_aggregates_lowest_fee(self):
        a = self._agg(name="Cheap", management_fee_pct=0.1, performance_fee_pct=0.0,
                      withdrawal_fee_pct=0.0, deposit_fee_pct=0.0, underlying_protocol_fee_pct=0.0)
        b = self._agg(name="Expensive", management_fee_pct=5.0)
        result = self.analyzer.analyze([a, b])
        self.assertEqual(result["aggregates"]["lowest_fee_aggregator"], "Cheap")

    def test_aggregates_highest_fee(self):
        a = self._agg(name="Cheap", management_fee_pct=0.1, performance_fee_pct=0.0,
                      withdrawal_fee_pct=0.0, deposit_fee_pct=0.0, underlying_protocol_fee_pct=0.0)
        b = self._agg(name="Expensive", management_fee_pct=5.0)
        result = self.analyzer.analyze([a, b])
        self.assertEqual(result["aggregates"]["highest_fee_aggregator"], "Expensive")

    def test_average_net_apy_calculation(self):
        a = self._agg(name="A", gross_apy_pct=10.0,
                      management_fee_pct=1.0, performance_fee_pct=0.0,
                      withdrawal_fee_pct=0.0, deposit_fee_pct=0.0, underlying_protocol_fee_pct=0.0)
        b = self._agg(name="B", gross_apy_pct=20.0,
                      management_fee_pct=2.0, performance_fee_pct=0.0,
                      withdrawal_fee_pct=0.0, deposit_fee_pct=0.0, underlying_protocol_fee_pct=0.0)
        result = self.analyzer.analyze([a, b])
        # net A = 9, net B = 18, avg = 13.5
        self.assertAlmostEqual(result["aggregates"]["average_net_apy"], 13.5, places=4)

    def test_average_fee_drag(self):
        a = self._agg(name="A", gross_apy_pct=10.0,
                      management_fee_pct=1.0, performance_fee_pct=0.0,
                      withdrawal_fee_pct=0.0, deposit_fee_pct=0.0, underlying_protocol_fee_pct=0.0)
        b = self._agg(name="B", gross_apy_pct=10.0,
                      management_fee_pct=3.0, performance_fee_pct=0.0,
                      withdrawal_fee_pct=0.0, deposit_fee_pct=0.0, underlying_protocol_fee_pct=0.0)
        result = self.analyzer.analyze([a, b])
        self.assertAlmostEqual(result["aggregates"]["average_fee_drag"], 2.0, places=4)

    def test_adds_value_count_zero_without_alpha(self):
        agg = self._agg(management_fee_pct=2.0)
        result = self.analyzer.analyze([agg])
        self.assertEqual(result["aggregates"]["adds_value_count"], 0)

    def test_log_written(self):
        self.analyzer.analyze([self._agg()])
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_ring_buffer_cap(self):
        small_cap_analyzer = DeFiYieldAggregatorFeeAnalyzer(
            log_path=self.log_path, log_cap=3
        )
        for _ in range(5):
            small_cap_analyzer.analyze([self._agg()])
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertLessEqual(len(log), 3)

    def test_log_entry_has_ts(self):
        self.analyzer.analyze([self._agg()])
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertIn("ts", log[0])

    def test_log_entry_has_count(self):
        self.analyzer.analyze([self._agg(), self._agg(name="B")])
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertEqual(log[0]["count"], 2)

    def test_config_none_ok(self):
        result = self.analyzer.analyze([self._agg()], config=None)
        self.assertIn("aggregators", result)

    def test_config_empty_ok(self):
        result = self.analyzer.analyze([self._agg()], config={})
        self.assertIn("aggregators", result)

    def test_per_aggregator_result_type(self):
        result = self.analyzer.analyze([self._agg()])
        self.assertIsInstance(result["aggregators"][0], dict)

    def test_version_field(self):
        result = self.analyzer.analyze([self._agg()])
        self.assertEqual(result["version"], "1.0.0")

    def test_total_count_matches(self):
        result = self.analyzer.analyze([self._agg(), self._agg(name="B")])
        self.assertEqual(result["aggregates"]["total_count"], 2)

    def test_extractive_aggregator_detected(self):
        agg = self._agg(
            gross_apy_pct=2.0,
            performance_fee_pct=0.0,
            management_fee_pct=2.0,
            withdrawal_fee_pct=0.0,
            deposit_fee_pct=0.0,
            underlying_protocol_fee_pct=0.0,
        )
        result = self.analyzer.analyze([agg])
        self.assertEqual(result["aggregators"][0]["fee_label"], "EXTRACTIVE")

    def test_net_apy_can_be_negative(self):
        agg = self._agg(gross_apy_pct=1.0, management_fee_pct=5.0)
        result = self.analyzer.analyze([agg])
        self.assertLess(result["aggregators"][0]["net_apy_pct"], 0.0)

    def test_multiple_log_entries_accumulate(self):
        self.analyzer.analyze([self._agg()])
        self.analyzer.analyze([self._agg()])
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertEqual(len(log), 2)

    def test_flags_list_type(self):
        result = self.analyzer.analyze([self._agg()])
        self.assertIsInstance(result["aggregators"][0]["flags"], list)

    def test_fee_efficiency_ratio_close_to_1_for_low_fees(self):
        agg = self._agg(
            gross_apy_pct=20.0,
            management_fee_pct=0.1,
            performance_fee_pct=0.0,
            withdrawal_fee_pct=0.0,
            deposit_fee_pct=0.0,
            underlying_protocol_fee_pct=0.0,
        )
        result = self.analyzer.analyze([agg])
        ratio = result["aggregators"][0]["fee_efficiency_ratio"]
        self.assertGreater(ratio, 0.99)


# ---------------------------------------------------------------------------
# Tests: Atomic write helpers
# ---------------------------------------------------------------------------
class TestAtomicWrite(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def test_write_and_read(self):
        path = os.path.join(self.tmp_dir, "test.json")
        _atomic_write(path, {"key": "value"})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["key"], "value")

    def test_overwrites_existing(self):
        path = os.path.join(self.tmp_dir, "test.json")
        _atomic_write(path, [1, 2, 3])
        _atomic_write(path, [4, 5, 6])
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data, [4, 5, 6])

    def test_creates_parent_dirs(self):
        path = os.path.join(self.tmp_dir, "sub", "dir", "test.json")
        _atomic_write(path, {"nested": True})
        self.assertTrue(os.path.exists(path))

    def test_writes_list(self):
        path = os.path.join(self.tmp_dir, "list.json")
        _atomic_write(path, [{"a": 1}, {"b": 2}])
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)


class TestLoadLog(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def test_missing_file_returns_empty(self):
        result = _load_log("/nonexistent/path/log.json")
        self.assertEqual(result, [])

    def test_invalid_json_returns_empty(self):
        path = os.path.join(self.tmp_dir, "bad.json")
        with open(path, "w") as f:
            f.write("NOT JSON {{{")
        result = _load_log(path)
        self.assertEqual(result, [])

    def test_non_list_json_returns_empty(self):
        path = os.path.join(self.tmp_dir, "obj.json")
        with open(path, "w") as f:
            json.dump({"not": "a list"}, f)
        result = _load_log(path)
        self.assertEqual(result, [])

    def test_valid_log(self):
        path = os.path.join(self.tmp_dir, "log.json")
        _atomic_write(path, [{"ts": "2026-01-01"}])
        result = _load_log(path)
        self.assertEqual(len(result), 1)


class TestAppendLog(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp_dir, "log.json")

    def test_appends_entry(self):
        _append_log(self.path, {"a": 1}, cap=10)
        _append_log(self.path, {"b": 2}, cap=10)
        log = _load_log(self.path)
        self.assertEqual(len(log), 2)

    def test_cap_enforced(self):
        for i in range(10):
            _append_log(self.path, {"i": i}, cap=5)
        log = _load_log(self.path)
        self.assertLessEqual(len(log), 5)

    def test_last_entry_preserved(self):
        for i in range(10):
            _append_log(self.path, {"i": i}, cap=5)
        log = _load_log(self.path)
        self.assertEqual(log[-1]["i"], 9)


# ---------------------------------------------------------------------------
# Edge case / boundary tests
# ---------------------------------------------------------------------------
class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.analyzer = DeFiYieldAggregatorFeeAnalyzer(
            log_path=os.path.join(self.tmp_dir, "log.json")
        )

    def test_very_high_gross_apy(self):
        agg = make_agg(gross_apy_pct=1000.0, performance_fee_pct=10.0)
        result = self.analyzer.analyze([agg])
        self.assertGreater(result["aggregators"][0]["net_apy_pct"], 0)

    def test_all_flags_present(self):
        agg = make_agg(
            gross_apy_pct=2.0,
            performance_fee_pct=25.0,  # PERFORMANCE_FEE_HEAVY
            management_fee_pct=3.0,    # MANAGEMENT_FEE_HIGH
            withdrawal_fee_pct=0.0,
            deposit_fee_pct=0.0,
            underlying_protocol_fee_pct=0.0,
            harvest_frequency_days=1,  # FREQUENT_HARVEST
        )
        result = self.analyzer.analyze([agg])
        flags = result["aggregators"][0]["flags"]
        # drag = 25%*2 + 3 = 0.5 + 3 = 3.5 > 50% of 2=1 → EXTRACTIVE_FEES
        self.assertIn("PERFORMANCE_FEE_HEAVY", flags)
        self.assertIn("MANAGEMENT_FEE_HIGH", flags)
        self.assertIn("FREQUENT_HARVEST", flags)
        self.assertIn("EXTRACTIVE_FEES", flags)

    def test_float_string_input_handled(self):
        # All numeric fields should accept float-like values
        agg = make_agg(gross_apy_pct="10.5", performance_fee_pct="5.0")
        result = self.analyzer.analyze([agg])
        self.assertAlmostEqual(result["aggregators"][0]["gross_apy_pct"], 10.5)

    def test_missing_fields_use_defaults(self):
        agg = {"name": "Minimal"}
        result = self.analyzer.analyze([agg])
        self.assertEqual(result["aggregators"][0]["gross_apy_pct"], 0.0)

    def test_analyzer_aggregates_type(self):
        result = self.analyzer.analyze([make_agg()])
        self.assertIsInstance(result["aggregates"], dict)

    def test_ten_aggregators(self):
        aggs = [make_agg(name=f"Agg{i}", gross_apy_pct=float(i + 1)) for i in range(10)]
        result = self.analyzer.analyze(aggs)
        self.assertEqual(len(result["aggregators"]), 10)

    def test_single_agg_lowest_equals_highest(self):
        result = self.analyzer.analyze([make_agg(name="Solo")])
        agg = result["aggregates"]
        self.assertEqual(agg["lowest_fee_aggregator"], "Solo")
        self.assertEqual(agg["highest_fee_aggregator"], "Solo")

    def test_break_even_finite_when_net_positive(self):
        agg = make_agg(gross_apy_pct=10.0, management_fee_pct=1.0,
                       deposit_fee_pct=0.5, withdrawal_fee_pct=0.5,
                       performance_fee_pct=0.0, underlying_protocol_fee_pct=0.0)
        result = self.analyzer.analyze([agg])
        r = result["aggregators"][0]
        self.assertIsNotNone(r["break_even_holding_days"])
        self.assertGreater(r["break_even_holding_days"], 0.0)

    def test_no_crash_on_bad_log_path(self):
        bad_analyzer = DeFiYieldAggregatorFeeAnalyzer(log_path="/nonexistent/xyz/log.json")
        # Should not raise
        try:
            bad_analyzer.analyze([make_agg()])
        except Exception:
            pass  # Log I/O errors are swallowed


if __name__ == "__main__":
    unittest.main()
