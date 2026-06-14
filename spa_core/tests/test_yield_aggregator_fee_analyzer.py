"""
Tests for MP-858: YieldAggregatorFeeAnalyzer
>=65 tests covering all fee drag calculations, competitiveness tiers,
efficiency scoring, edge cases, aggregates, and log append.
Uses unittest only (pure stdlib).
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.yield_aggregator_fee_analyzer import (
    analyze,
    _management_drag,
    _performance_drag,
    _withdrawal_drag,
    _fee_competitiveness,
    _fee_efficiency_score,
    _autocompound_label,
    _append_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _agg(
    name="TestVault",
    gross_apy_pct=10.0,
    management_fee_pct=1.0,
    performance_fee_pct=10.0,
    withdrawal_fee_pct=0.1,
    holding_period_days=365,
    autocompound=True,
):
    return {
        "name": name,
        "gross_apy_pct": gross_apy_pct,
        "management_fee_pct": management_fee_pct,
        "performance_fee_pct": performance_fee_pct,
        "withdrawal_fee_pct": withdrawal_fee_pct,
        "holding_period_days": holding_period_days,
        "autocompound": autocompound,
    }


# ---------------------------------------------------------------------------
# _management_drag
# ---------------------------------------------------------------------------

class TestManagementDrag(unittest.TestCase):

    def test_direct_passthrough(self):
        self.assertAlmostEqual(_management_drag(2.0), 2.0)

    def test_zero(self):
        self.assertAlmostEqual(_management_drag(0.0), 0.0)

    def test_fractional(self):
        self.assertAlmostEqual(_management_drag(0.5), 0.5)

    def test_large(self):
        self.assertAlmostEqual(_management_drag(5.0), 5.0)


# ---------------------------------------------------------------------------
# _performance_drag
# ---------------------------------------------------------------------------

class TestPerformanceDrag(unittest.TestCase):

    def test_20pct_fee_on_10pct_apy(self):
        # 20/100 * 10 = 2.0
        self.assertAlmostEqual(_performance_drag(20.0, 10.0), 2.0)

    def test_zero_fee(self):
        self.assertAlmostEqual(_performance_drag(0.0, 10.0), 0.0)

    def test_zero_gross(self):
        self.assertAlmostEqual(_performance_drag(20.0, 0.0), 0.0)

    def test_100pct_fee(self):
        self.assertAlmostEqual(_performance_drag(100.0, 8.0), 8.0)

    def test_fractional(self):
        self.assertAlmostEqual(_performance_drag(4.5, 6.5), 4.5 / 100 * 6.5)


# ---------------------------------------------------------------------------
# _withdrawal_drag
# ---------------------------------------------------------------------------

class TestWithdrawalDrag(unittest.TestCase):

    def test_annualised_365(self):
        # 0.1 / 365 * 365 = 0.1
        self.assertAlmostEqual(_withdrawal_drag(0.1, 365), 0.1)

    def test_annualised_180(self):
        # 0.5 / 180 * 365
        expected = 0.5 / 180 * 365
        self.assertAlmostEqual(_withdrawal_drag(0.5, 180), expected)

    def test_zero_holding_returns_0(self):
        self.assertAlmostEqual(_withdrawal_drag(1.0, 0), 0.0)

    def test_zero_fee_returns_0(self):
        self.assertAlmostEqual(_withdrawal_drag(0.0, 365), 0.0)

    def test_short_holding_larger_drag(self):
        # 30 days holding amplifies annualised drag
        drag_short = _withdrawal_drag(1.0, 30)
        drag_long = _withdrawal_drag(1.0, 365)
        self.assertGreater(drag_short, drag_long)

    def test_90_days_holding(self):
        expected = 0.2 / 90 * 365
        self.assertAlmostEqual(_withdrawal_drag(0.2, 90), expected)


# ---------------------------------------------------------------------------
# _fee_competitiveness
# ---------------------------------------------------------------------------

class TestFeeCompetitiveness(unittest.TestCase):

    def test_excellent_low_drag(self):
        # drag <= 0.5 and gross > 0
        self.assertEqual(_fee_competitiveness(0.0, 10.0), "EXCELLENT")
        self.assertEqual(_fee_competitiveness(0.5, 10.0), "EXCELLENT")

    def test_just_over_05_gross_high(self):
        # drag=0.51, gross=10 -> ratio=5.1% -> GOOD
        self.assertEqual(_fee_competitiveness(0.51, 10.0), "GOOD")

    def test_good_up_to_15pct(self):
        # drag=1.5, gross=10 -> ratio=15% -> GOOD
        self.assertEqual(_fee_competitiveness(1.5, 10.0), "GOOD")

    def test_fair_15_to_30pct(self):
        # drag=2.0, gross=10 -> ratio=20% -> FAIR
        self.assertEqual(_fee_competitiveness(2.0, 10.0), "FAIR")
        # drag=3.0, gross=10 -> ratio=30% -> FAIR
        self.assertEqual(_fee_competitiveness(3.0, 10.0), "FAIR")

    def test_expensive_30_to_50pct(self):
        # drag=4.0, gross=10 -> ratio=40% -> EXPENSIVE
        self.assertEqual(_fee_competitiveness(4.0, 10.0), "EXPENSIVE")
        # drag=5.0, gross=10 -> ratio=50% -> EXPENSIVE
        self.assertEqual(_fee_competitiveness(5.0, 10.0), "EXPENSIVE")

    def test_avoid_over_50pct(self):
        # drag=6.0, gross=10 -> ratio=60% -> AVOID
        self.assertEqual(_fee_competitiveness(6.0, 10.0), "AVOID")

    def test_zero_gross_zero_drag_excellent(self):
        self.assertEqual(_fee_competitiveness(0.0, 0.0), "EXCELLENT")

    def test_zero_gross_nonzero_drag_avoid(self):
        self.assertEqual(_fee_competitiveness(1.0, 0.0), "AVOID")
        self.assertEqual(_fee_competitiveness(0.1, 0.0), "AVOID")

    def test_boundary_15pct_ratio(self):
        # ratio exactly 15% -> GOOD
        self.assertEqual(_fee_competitiveness(1.5, 10.0), "GOOD")

    def test_boundary_30pct_ratio(self):
        # ratio exactly 30% -> FAIR
        self.assertEqual(_fee_competitiveness(3.0, 10.0), "FAIR")

    def test_boundary_50pct_ratio(self):
        # ratio exactly 50% -> EXPENSIVE
        self.assertEqual(_fee_competitiveness(5.0, 10.0), "EXPENSIVE")

    def test_ratio_just_over_15(self):
        # drag=1.501, gross=10 -> ratio=15.01% -> FAIR
        self.assertEqual(_fee_competitiveness(1.501, 10.0), "FAIR")


# ---------------------------------------------------------------------------
# _fee_efficiency_score
# ---------------------------------------------------------------------------

class TestFeeEfficiencyScore(unittest.TestCase):

    def test_full_retention(self):
        # net=gross -> score=100
        self.assertEqual(_fee_efficiency_score(10.0, 10.0, 0.0), 100)

    def test_half_retention(self):
        # net=5, gross=10 -> 50%
        self.assertEqual(_fee_efficiency_score(5.0, 10.0, 5.0), 50)

    def test_zero_gross_zero_drag(self):
        self.assertEqual(_fee_efficiency_score(0.0, 0.0, 0.0), 100)

    def test_zero_gross_nonzero_drag(self):
        self.assertEqual(_fee_efficiency_score(0.0, 0.0, 1.0), 0)

    def test_negative_net_clamps_to_0(self):
        # net=-2, gross=10 -> retention=-20% clamped to 0
        self.assertEqual(_fee_efficiency_score(-2.0, 10.0, 12.0), 0)

    def test_high_retention_caps_at_100(self):
        # net=10, gross=10 -> exactly 100
        self.assertEqual(_fee_efficiency_score(10.0, 10.0, 0.0), 100)

    def test_80pct_retention(self):
        self.assertEqual(_fee_efficiency_score(8.0, 10.0, 2.0), 80)

    def test_fractional_truncated(self):
        # net=9.9, gross=10 -> 99% -> score=99 (int truncation)
        self.assertEqual(_fee_efficiency_score(9.9, 10.0, 0.1), 99)


# ---------------------------------------------------------------------------
# _autocompound_label
# ---------------------------------------------------------------------------

class TestAutocompoundLabel(unittest.TestCase):

    def test_true(self):
        self.assertEqual(
            _autocompound_label(True), "Auto-compounds (higher effective yield)"
        )

    def test_false(self):
        self.assertEqual(
            _autocompound_label(False), "Manual compounding required"
        )


# ---------------------------------------------------------------------------
# analyze() -- empty input
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):

    def test_empty_list_returns_nones(self):
        res = analyze([])
        self.assertIsNone(res["best_net_yield"])
        self.assertIsNone(res["most_fee_efficient"])
        self.assertEqual(res["aggregators"], [])

    def test_empty_market_summary_zeros(self):
        res = analyze([])
        ms = res["market_summary"]
        self.assertEqual(ms["avg_gross_apy_pct"], 0.0)
        self.assertEqual(ms["avg_net_apy_pct"], 0.0)
        self.assertEqual(ms["avg_fee_drag_pct"], 0.0)
        self.assertEqual(ms["avg_fee_drag_of_gross_pct"], 0.0)

    def test_timestamp_present(self):
        res = analyze([])
        self.assertIn("timestamp", res)
        self.assertIsInstance(res["timestamp"], float)


# ---------------------------------------------------------------------------
# analyze() -- single aggregator
# ---------------------------------------------------------------------------

class TestAnalyzeSingle(unittest.TestCase):

    def test_net_apy_computed(self):
        # gross=10, mgmt=1, perf=20% of 10=2, wd=0.1/365*365=0.1 -> drag=3.1, net=6.9
        a = _agg(gross_apy_pct=10.0, management_fee_pct=1.0, performance_fee_pct=20.0,
                 withdrawal_fee_pct=0.1, holding_period_days=365)
        res = analyze([a])
        entry = res["aggregators"][0]
        self.assertAlmostEqual(entry["management_drag_pct"], 1.0)
        self.assertAlmostEqual(entry["performance_drag_pct"], 2.0)
        self.assertAlmostEqual(entry["withdrawal_drag_pct"], 0.1)
        self.assertAlmostEqual(entry["fee_drag_pct"], 3.1)
        self.assertAlmostEqual(entry["net_apy_pct"], 6.9)

    def test_vs_benchmark_positive(self):
        # net=6.9, benchmark=5.0 -> vs_benchmark=1.9
        a = _agg(gross_apy_pct=10.0, management_fee_pct=1.0, performance_fee_pct=20.0,
                 withdrawal_fee_pct=0.1, holding_period_days=365)
        res = analyze([a])
        self.assertAlmostEqual(res["aggregators"][0]["vs_benchmark_pct"], 1.9)

    def test_vs_benchmark_custom(self):
        a = _agg(gross_apy_pct=10.0, management_fee_pct=0.0, performance_fee_pct=0.0,
                 withdrawal_fee_pct=0.0, holding_period_days=365)
        res = analyze([a], config={"benchmark_apy_pct": 8.0})
        self.assertAlmostEqual(res["aggregators"][0]["vs_benchmark_pct"], 2.0)

    def test_best_net_yield_single(self):
        res = analyze([_agg(name="Only")])
        self.assertEqual(res["best_net_yield"], "Only")

    def test_most_fee_efficient_single(self):
        res = analyze([_agg(name="Only")])
        self.assertEqual(res["most_fee_efficient"], "Only")

    def test_autocompound_true_label(self):
        res = analyze([_agg(autocompound=True)])
        self.assertIn("Auto-compounds", res["aggregators"][0]["autocompound_label"])

    def test_autocompound_false_label(self):
        res = analyze([_agg(autocompound=False)])
        self.assertIn("Manual compounding", res["aggregators"][0]["autocompound_label"])

    def test_name_preserved(self):
        res = analyze([_agg(name="Yearn")])
        self.assertEqual(res["aggregators"][0]["name"], "Yearn")

    def test_gross_preserved(self):
        res = analyze([_agg(gross_apy_pct=12.5)])
        self.assertAlmostEqual(res["aggregators"][0]["gross_apy_pct"], 12.5)

    def test_holding_0_wd_drag_zero(self):
        a = _agg(withdrawal_fee_pct=1.0, holding_period_days=0)
        res = analyze([a])
        self.assertAlmostEqual(res["aggregators"][0]["withdrawal_drag_pct"], 0.0)

    def test_output_keys_complete(self):
        res = analyze([_agg()])
        entry = res["aggregators"][0]
        for key in ("name", "gross_apy_pct", "net_apy_pct", "fee_drag_pct",
                    "management_drag_pct", "performance_drag_pct", "withdrawal_drag_pct",
                    "fee_competitiveness", "vs_benchmark_pct",
                    "fee_efficiency_score", "autocompound_label"):
            self.assertIn(key, entry)

    def test_zero_fees_excellent(self):
        a = _agg(management_fee_pct=0.0, performance_fee_pct=0.0, withdrawal_fee_pct=0.0)
        res = analyze([a])
        self.assertEqual(res["aggregators"][0]["fee_competitiveness"], "EXCELLENT")

    def test_market_summary_single(self):
        a = _agg(gross_apy_pct=10.0, management_fee_pct=1.0,
                 performance_fee_pct=0.0, withdrawal_fee_pct=0.0,
                 holding_period_days=365)
        res = analyze([a])
        ms = res["market_summary"]
        self.assertAlmostEqual(ms["avg_gross_apy_pct"], 10.0)
        self.assertAlmostEqual(ms["avg_net_apy_pct"], 9.0)
        self.assertAlmostEqual(ms["avg_fee_drag_pct"], 1.0)
        self.assertAlmostEqual(ms["avg_fee_drag_of_gross_pct"], 10.0)

    def test_negative_net_apy_possible(self):
        a = _agg(gross_apy_pct=1.0, management_fee_pct=3.0, performance_fee_pct=0.0,
                 withdrawal_fee_pct=0.0, holding_period_days=365)
        res = analyze([a])
        self.assertLess(res["aggregators"][0]["net_apy_pct"], 0)


# ---------------------------------------------------------------------------
# analyze() -- multiple aggregators
# ---------------------------------------------------------------------------

class TestAnalyzeMultiple(unittest.TestCase):

    def _no_fee(self, name="Clean", gross=10.0):
        return _agg(name=name, gross_apy_pct=gross,
                    management_fee_pct=0.0, performance_fee_pct=0.0,
                    withdrawal_fee_pct=0.0, holding_period_days=365)

    def _high_fee(self, name="Expensive", gross=10.0):
        return _agg(name=name, gross_apy_pct=gross,
                    management_fee_pct=3.0, performance_fee_pct=30.0,
                    withdrawal_fee_pct=1.0, holding_period_days=90)

    def test_best_net_yield_identified(self):
        res = analyze([self._no_fee("A", 10), self._no_fee("B", 8)])
        self.assertEqual(res["best_net_yield"], "A")

    def test_most_fee_efficient_identified(self):
        res = analyze([self._no_fee("Clean"), self._high_fee("Pricey")])
        self.assertEqual(res["most_fee_efficient"], "Clean")

    def test_market_summary_avg_gross(self):
        res = analyze([self._no_fee("A", 10), self._no_fee("B", 6)])
        self.assertAlmostEqual(res["market_summary"]["avg_gross_apy_pct"], 8.0)

    def test_market_summary_avg_net(self):
        res = analyze([self._no_fee("A", 10), self._no_fee("B", 6)])
        self.assertAlmostEqual(res["market_summary"]["avg_net_apy_pct"], 8.0)

    def test_market_summary_avg_drag_zero_fees(self):
        res = analyze([self._no_fee("A"), self._no_fee("B")])
        self.assertAlmostEqual(res["market_summary"]["avg_fee_drag_pct"], 0.0)

    def test_market_summary_avg_drag_of_gross_zero(self):
        res = analyze([self._no_fee("A"), self._no_fee("B")])
        self.assertAlmostEqual(res["market_summary"]["avg_fee_drag_of_gross_pct"], 0.0)

    def test_three_aggregators_count(self):
        res = analyze([self._no_fee("A"), self._no_fee("B"), self._high_fee("C")])
        self.assertEqual(len(res["aggregators"]), 3)

    def test_market_summary_drag_of_gross_nonzero(self):
        a1 = _agg(gross_apy_pct=10.0, management_fee_pct=1.0,
                  performance_fee_pct=0.0, withdrawal_fee_pct=0.0, holding_period_days=365)
        a2 = _agg(gross_apy_pct=10.0, management_fee_pct=1.0,
                  performance_fee_pct=0.0, withdrawal_fee_pct=0.0, holding_period_days=365)
        res = analyze([a1, a2])
        # avg_drag=1.0, avg_gross=10.0 -> avg_drag_of_gross=10%
        self.assertAlmostEqual(res["market_summary"]["avg_fee_drag_of_gross_pct"], 10.0)


# ---------------------------------------------------------------------------
# Fee competitiveness integration
# ---------------------------------------------------------------------------

class TestCompetitivenessIntegration(unittest.TestCase):

    def test_avoid_high_fees(self):
        # gross=2, mgmt=3 -> drag=3, ratio=150% -> AVOID
        a = _agg(gross_apy_pct=2.0, management_fee_pct=3.0,
                 performance_fee_pct=0.0, withdrawal_fee_pct=0.0, holding_period_days=365)
        res = analyze([a])
        self.assertEqual(res["aggregators"][0]["fee_competitiveness"], "AVOID")

    def test_excellent_minimal_fees(self):
        a = _agg(gross_apy_pct=10.0, management_fee_pct=0.2,
                 performance_fee_pct=0.0, withdrawal_fee_pct=0.0, holding_period_days=365)
        res = analyze([a])
        self.assertEqual(res["aggregators"][0]["fee_competitiveness"], "EXCELLENT")

    def test_good_competitive_fees(self):
        # drag=0.8, gross=10 -> 8% -> GOOD
        a = _agg(gross_apy_pct=10.0, management_fee_pct=0.8,
                 performance_fee_pct=0.0, withdrawal_fee_pct=0.0, holding_period_days=365)
        res = analyze([a])
        self.assertEqual(res["aggregators"][0]["fee_competitiveness"], "GOOD")

    def test_expensive_high_fee_ratio(self):
        # drag=4, gross=10 -> 40% -> EXPENSIVE
        a = _agg(gross_apy_pct=10.0, management_fee_pct=4.0,
                 performance_fee_pct=0.0, withdrawal_fee_pct=0.0, holding_period_days=365)
        res = analyze([a])
        self.assertEqual(res["aggregators"][0]["fee_competitiveness"], "EXPENSIVE")

    def test_zero_gross_zero_fee_excellent(self):
        a = _agg(gross_apy_pct=0.0, management_fee_pct=0.0,
                 performance_fee_pct=0.0, withdrawal_fee_pct=0.0, holding_period_days=365)
        res = analyze([a])
        self.assertEqual(res["aggregators"][0]["fee_competitiveness"], "EXCELLENT")

    def test_zero_gross_with_fee_avoid(self):
        a = _agg(gross_apy_pct=0.0, management_fee_pct=1.0,
                 performance_fee_pct=0.0, withdrawal_fee_pct=0.0, holding_period_days=365)
        res = analyze([a])
        self.assertEqual(res["aggregators"][0]["fee_competitiveness"], "AVOID")


# ---------------------------------------------------------------------------
# Config override
# ---------------------------------------------------------------------------

class TestConfigOverride(unittest.TestCase):

    def test_custom_benchmark_changes_vs_benchmark(self):
        a = _agg(gross_apy_pct=5.0, management_fee_pct=0.0, performance_fee_pct=0.0,
                 withdrawal_fee_pct=0.0, holding_period_days=365)
        res_default = analyze([a])
        res_custom = analyze([a], config={"benchmark_apy_pct": 3.0})
        self.assertAlmostEqual(res_default["aggregators"][0]["vs_benchmark_pct"], 0.0)
        self.assertAlmostEqual(res_custom["aggregators"][0]["vs_benchmark_pct"], 2.0)

    def test_config_none_uses_defaults(self):
        a = _agg()
        res = analyze([a], config=None)
        self.assertIn("aggregators", res)

    def test_config_empty_dict_uses_defaults(self):
        a = _agg()
        res = analyze([a], config={})
        self.assertIn("aggregators", res)


# ---------------------------------------------------------------------------
# _append_log
# ---------------------------------------------------------------------------

class TestAppendLog858(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "yield_aggregator_fee_log.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_creates_file_if_missing(self):
        result = analyze([_agg()])
        _append_log(result, self.log_file)
        self.assertTrue(os.path.exists(self.log_file))

    def test_appends_entry(self):
        _append_log(analyze([_agg()]), self.log_file)
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(len(log), 1)

    def test_appends_multiple(self):
        for _ in range(5):
            _append_log(analyze([_agg()]), self.log_file)
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(len(log), 5)

    def test_ring_buffer_cap_100(self):
        for _ in range(110):
            _append_log(analyze([_agg()]), self.log_file)
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(len(log), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(5):
            res = analyze([_agg(name=f"Vault{i}")])
            res["_seq"] = i
            _append_log(res, self.log_file)
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(log[-1]["_seq"], 4)

    def test_corrupt_file_recovered(self):
        with open(self.log_file, "w") as f:
            f.write("NOT JSON{{{{")
        _append_log(analyze([_agg()]), self.log_file)
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(len(log), 1)

    def test_non_list_recovered(self):
        with open(self.log_file, "w") as f:
            json.dump({"bad": "structure"}, f)
        _append_log(analyze([_agg()]), self.log_file)
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(len(log), 1)

    def test_atomic_write_valid_json(self):
        _append_log(analyze([_agg()]), self.log_file)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


# ---------------------------------------------------------------------------
# Fee efficiency score integration
# ---------------------------------------------------------------------------

class TestFeeEfficiencyIntegration(unittest.TestCase):

    def test_zero_fee_full_efficiency(self):
        a = _agg(management_fee_pct=0.0, performance_fee_pct=0.0, withdrawal_fee_pct=0.0)
        res = analyze([a])
        self.assertEqual(res["aggregators"][0]["fee_efficiency_score"], 100)

    def test_high_fee_low_efficiency(self):
        # gross=10, drag=8 -> net=2 -> retention=20%
        a = _agg(gross_apy_pct=10.0, management_fee_pct=6.0,
                 performance_fee_pct=20.0, withdrawal_fee_pct=0.0, holding_period_days=365)
        res = analyze([a])
        # perf drag = 20/100 * 10 = 2; total drag = 6+2=8; net=2; score=20
        self.assertEqual(res["aggregators"][0]["fee_efficiency_score"], 20)

    def test_negative_net_zero_efficiency(self):
        a = _agg(gross_apy_pct=1.0, management_fee_pct=5.0,
                 performance_fee_pct=0.0, withdrawal_fee_pct=0.0, holding_period_days=365)
        res = analyze([a])
        self.assertEqual(res["aggregators"][0]["fee_efficiency_score"], 0)


if __name__ == "__main__":
    unittest.main()
