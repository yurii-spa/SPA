"""Tests for MP-693: PerformanceBenchmarkTracker (≥60 tests).

Run with:
    python3 -m unittest spa_core.tests.test_performance_benchmark_tracker -v

Pure stdlib unittest — no pytest, no numpy, no pandas.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repo root is on path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.performance_benchmark_tracker import (
    BENCHMARKS,
    MAX_ENTRIES,
    BenchmarkComparison,
    PerformanceBenchmarkTracker,
    PerformancePeriod,
    PerformanceTrackingReport,
    _atomic_write,
    _performance_tier,
    annualized_return,
    benchmark_period_return,
    outperformance_bps,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tracker(tmp_dir: str) -> PerformanceBenchmarkTracker:
    return PerformanceBenchmarkTracker(data_dir=tmp_dir)


def _period(label="2026-Q1", ret=2.0, days=90) -> PerformancePeriod:
    return PerformancePeriod(period_label=label, portfolio_return_pct=ret,
                             days_in_period=days)


# ---------------------------------------------------------------------------
# 1. annualized_return
# ---------------------------------------------------------------------------


class TestAnnualizedReturn(unittest.TestCase):

    def test_basic_annualization_90_days(self):
        # total=2%, 90 days → annualized
        result = annualized_return(2.0, 90)
        expected = ((1.02) ** (365 / 90) - 1) * 100
        self.assertAlmostEqual(result, expected, places=6)

    def test_365_days_same_as_input(self):
        # over 365 days, annualized ≈ total (compound: 1.05^1-1=5%)
        result = annualized_return(5.0, 365)
        self.assertAlmostEqual(result, 5.0, places=6)

    def test_zero_days_returns_input(self):
        self.assertAlmostEqual(annualized_return(5.0, 0), 5.0)

    def test_negative_days_returns_input(self):
        self.assertAlmostEqual(annualized_return(5.0, -1), 5.0)

    def test_zero_return_stays_zero(self):
        self.assertAlmostEqual(annualized_return(0.0, 90), 0.0, places=6)

    def test_formula_explicit(self):
        total = 3.0
        days = 180
        expected = ((1 + total / 100) ** (365 / days) - 1) * 100
        self.assertAlmostEqual(annualized_return(total, days), expected, places=8)

    def test_large_return_still_correct(self):
        result = annualized_return(50.0, 365)
        self.assertAlmostEqual(result, 50.0, places=5)

    def test_negative_return(self):
        result = annualized_return(-2.0, 90)
        expected = ((0.98) ** (365 / 90) - 1) * 100
        self.assertAlmostEqual(result, expected, places=5)

    def test_half_year_doubles_roughly(self):
        half = annualized_return(2.5, 182)
        full = annualized_return(5.0, 365)
        # annualized half-year ≈ same order as annual
        self.assertAlmostEqual(half, full, delta=0.5)


# ---------------------------------------------------------------------------
# 2. benchmark_period_return
# ---------------------------------------------------------------------------


class TestBenchmarkPeriodReturn(unittest.TestCase):

    def test_365_days_equals_annual(self):
        self.assertAlmostEqual(benchmark_period_return(5.0, 365), 5.0)

    def test_90_days_quarter(self):
        result = benchmark_period_return(4.0, 90)
        self.assertAlmostEqual(result, 4.0 * 90 / 365)

    def test_zero_days_returns_zero(self):
        self.assertAlmostEqual(benchmark_period_return(5.0, 0), 0.0)

    def test_negative_days_returns_zero(self):
        self.assertAlmostEqual(benchmark_period_return(5.0, -10), 0.0)

    def test_linear_scaling(self):
        r1 = benchmark_period_return(4.0, 30)
        r2 = benchmark_period_return(4.0, 60)
        self.assertAlmostEqual(r2, 2 * r1)

    def test_zero_annual_rate(self):
        self.assertAlmostEqual(benchmark_period_return(0.0, 90), 0.0)

    def test_eth_staking_90_days(self):
        result = benchmark_period_return(BENCHMARKS["ETH_STAKING"], 90)
        expected = 3.5 * 90 / 365
        self.assertAlmostEqual(result, expected)


# ---------------------------------------------------------------------------
# 3. outperformance_bps
# ---------------------------------------------------------------------------


class TestOutperformanceBps(unittest.TestCase):

    def test_basic_outperform(self):
        # portfolio 3%, benchmark 2% → 100bps
        self.assertAlmostEqual(outperformance_bps(3.0, 2.0), 100.0)

    def test_underperform(self):
        # portfolio 2%, benchmark 3% → -100bps
        self.assertAlmostEqual(outperformance_bps(2.0, 3.0), -100.0)

    def test_equal_zero(self):
        self.assertAlmostEqual(outperformance_bps(4.0, 4.0), 0.0)

    def test_formula_exact(self):
        p, b = 5.5, 4.2
        self.assertAlmostEqual(outperformance_bps(p, b), (p - b) * 100)

    def test_large_outperformance(self):
        self.assertAlmostEqual(outperformance_bps(10.0, 5.0), 500.0)

    def test_is_outperforming_positive_bps(self):
        bps = outperformance_bps(5.0, 3.0)
        self.assertGreater(bps, 0)

    def test_is_outperforming_negative_bps(self):
        bps = outperformance_bps(3.0, 5.0)
        self.assertLess(bps, 0)


# ---------------------------------------------------------------------------
# 4. _performance_tier
# ---------------------------------------------------------------------------


class TestPerformanceTier(unittest.TestCase):

    def test_elite_all_5(self):
        self.assertEqual(_performance_tier(5), "ELITE")

    def test_strong_4(self):
        self.assertEqual(_performance_tier(4), "STRONG")

    def test_adequate_3(self):
        self.assertEqual(_performance_tier(3), "ADEQUATE")

    def test_weak_2(self):
        self.assertEqual(_performance_tier(2), "WEAK")

    def test_underperforming_1(self):
        self.assertEqual(_performance_tier(1), "UNDERPERFORMING")

    def test_underperforming_0(self):
        self.assertEqual(_performance_tier(0), "UNDERPERFORMING")

    def test_elite_more_than_5(self):
        # robustness: >= 5 → ELITE
        self.assertEqual(_performance_tier(6), "ELITE")


# ---------------------------------------------------------------------------
# 5. track — single period
# ---------------------------------------------------------------------------


class TestTrackSinglePeriod(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _tracker(self.tmp)

    def test_total_return_equals_period_return(self):
        r = self.tracker.track("p1", [_period(ret=3.5, days=90)])
        self.assertAlmostEqual(r.total_return_pct, 3.5)

    def test_total_days_used_for_annualization(self):
        r = self.tracker.track("p1", [_period(ret=2.0, days=180)])
        expected = annualized_return(2.0, 180)
        self.assertAlmostEqual(r.annualized_return_pct, expected, places=5)

    def test_portfolio_id_preserved(self):
        r = self.tracker.track("my_port", [_period()])
        self.assertEqual(r.portfolio_id, "my_port")

    def test_comparisons_count_equals_benchmarks(self):
        r = self.tracker.track("p1", [_period()])
        self.assertEqual(len(r.comparisons), len(BENCHMARKS))

    def test_comparisons_sorted_descending(self):
        r = self.tracker.track("p1", [_period(ret=10.0, days=365)])
        bps_list = [c.outperformance_bps for c in r.comparisons]
        self.assertEqual(bps_list, sorted(bps_list, reverse=True))

    def test_rank_1_is_highest_outperformance(self):
        r = self.tracker.track("p1", [_period(ret=10.0, days=365)])
        rank1 = next(c for c in r.comparisons if c.rank == 1)
        max_bps = max(c.outperformance_bps for c in r.comparisons)
        self.assertAlmostEqual(rank1.outperformance_bps, max_bps)

    def test_best_relative_is_rank_1(self):
        r = self.tracker.track("p1", [_period(ret=10.0, days=365)])
        rank1 = next(c for c in r.comparisons if c.rank == 1)
        self.assertEqual(r.best_relative_benchmark, rank1.benchmark_name)

    def test_worst_relative_is_last(self):
        r = self.tracker.track("p1", [_period(ret=10.0, days=365)])
        worst = r.comparisons[-1]
        self.assertEqual(r.worst_relative_benchmark, worst.benchmark_name)

    def test_empty_periods_raises(self):
        with self.assertRaises(ValueError):
            self.tracker.track("p1", [])

    def test_beating_count_all_low_return(self):
        # Very low return → beats none
        r = self.tracker.track("p1", [_period(ret=-1.0, days=90)])
        self.assertEqual(r.beating_count, 0)

    def test_beating_count_all_high_return(self):
        # Very high return → beats all
        r = self.tracker.track("p1", [_period(ret=50.0, days=365)])
        self.assertEqual(r.beating_count, len(BENCHMARKS))

    def test_losing_count_complement(self):
        r = self.tracker.track("p1", [_period(ret=4.0, days=365)])
        self.assertEqual(r.beating_count + r.losing_count, len(BENCHMARKS))


# ---------------------------------------------------------------------------
# 6. track — multiple periods
# ---------------------------------------------------------------------------


class TestTrackMultiplePeriods(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _tracker(self.tmp)

    def test_total_return_sums_periods(self):
        periods = [_period("Q1", 2.0, 90), _period("Q2", 3.0, 91)]
        r = self.tracker.track("multi", periods)
        self.assertAlmostEqual(r.total_return_pct, 5.0)

    def test_total_days_sums_periods(self):
        periods = [_period("Q1", 2.0, 90), _period("Q2", 3.0, 91)]
        r = self.tracker.track("multi", periods)
        expected_ann = annualized_return(5.0, 181)
        self.assertAlmostEqual(r.annualized_return_pct, expected_ann, places=5)

    def test_three_periods(self):
        periods = [_period(f"P{i}", float(i), 90) for i in range(3)]
        r = self.tracker.track("3p", periods)
        self.assertAlmostEqual(r.total_return_pct, 3.0)  # 0+1+2

    def test_portfolio_return_pct_in_comparison_matches_total(self):
        periods = [_period("Q1", 2.0, 90), _period("Q2", 1.5, 90)]
        r = self.tracker.track("chk", periods)
        for comp in r.comparisons:
            self.assertAlmostEqual(comp.portfolio_return_pct, r.total_return_pct)

    def test_benchmark_period_return_formula(self):
        periods = [_period("Q1", 5.0, 90)]
        r = self.tracker.track("bpr", periods)
        # Find ETH_STAKING comparison
        eth = next(c for c in r.comparisons if c.benchmark_name == "ETH_STAKING")
        expected = benchmark_period_return(BENCHMARKS["ETH_STAKING"], 90)
        self.assertAlmostEqual(eth.benchmark_return_pct, expected)


# ---------------------------------------------------------------------------
# 7. BenchmarkComparison fields
# ---------------------------------------------------------------------------


class TestBenchmarkComparisonFields(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _tracker(self.tmp)

    def test_is_outperforming_true_when_positive_bps(self):
        r = self.tracker.track("p", [_period(ret=50.0, days=365)])
        for c in r.comparisons:
            if c.outperformance_bps > 0:
                self.assertTrue(c.is_outperforming)

    def test_is_outperforming_false_when_negative_bps(self):
        r = self.tracker.track("p", [_period(ret=-1.0, days=90)])
        for c in r.comparisons:
            self.assertFalse(c.is_outperforming)

    def test_outperformance_bps_formula(self):
        r = self.tracker.track("p", [_period(ret=5.0, days=365)])
        risk_free = next(c for c in r.comparisons if c.benchmark_name == "RISK_FREE")
        expected_bps = (5.0 - BENCHMARKS["RISK_FREE"]) * 100
        self.assertAlmostEqual(risk_free.outperformance_bps, expected_bps, delta=1e-3)

    def test_all_five_benchmarks_present(self):
        r = self.tracker.track("p", [_period()])
        names = {c.benchmark_name for c in r.comparisons}
        self.assertEqual(names, set(BENCHMARKS.keys()))

    def test_ranks_are_sequential(self):
        r = self.tracker.track("p", [_period()])
        ranks = sorted(c.rank for c in r.comparisons)
        self.assertEqual(ranks, list(range(1, len(BENCHMARKS) + 1)))


# ---------------------------------------------------------------------------
# 8. performance_tier integration
# ---------------------------------------------------------------------------


class TestPerformanceTierIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _tracker(self.tmp)

    def test_elite_when_beats_all(self):
        r = self.tracker.track("elite", [_period(ret=100.0, days=365)])
        self.assertEqual(r.performance_tier, "ELITE")

    def test_underperforming_when_beats_none(self):
        r = self.tracker.track("under", [_period(ret=-10.0, days=365)])
        self.assertEqual(r.performance_tier, "UNDERPERFORMING")

    def test_tier_values_valid(self):
        r = self.tracker.track("p", [_period(ret=5.0, days=365)])
        self.assertIn(r.performance_tier,
                      {"ELITE", "STRONG", "ADEQUATE", "WEAK", "UNDERPERFORMING"})


# ---------------------------------------------------------------------------
# 9. narrative
# ---------------------------------------------------------------------------


class TestNarrative(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _tracker(self.tmp)

    def test_narrative_contains_portfolio_id(self):
        r = self.tracker.track("MyFund", [_period()])
        self.assertIn("MyFund", r.narrative)

    def test_narrative_contains_total_return(self):
        r = self.tracker.track("p", [_period(ret=3.14, days=90)])
        self.assertIn("3.14", r.narrative)

    def test_narrative_contains_tier(self):
        r = self.tracker.track("p", [_period(ret=100.0, days=365)])
        self.assertIn(r.performance_tier, r.narrative)

    def test_narrative_contains_beating_count(self):
        r = self.tracker.track("p", [_period(ret=100.0, days=365)])
        self.assertIn(str(r.beating_count), r.narrative)

    def test_narrative_contains_best_benchmark(self):
        r = self.tracker.track("p", [_period(ret=5.0, days=365)])
        self.assertIn(r.best_relative_benchmark, r.narrative)

    def test_narrative_is_nonempty(self):
        r = self.tracker.track("p", [_period()])
        self.assertGreater(len(r.narrative), 10)


# ---------------------------------------------------------------------------
# 10. track_batch
# ---------------------------------------------------------------------------


class TestTrackBatch(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _tracker(self.tmp)

    def test_empty_batch_returns_empty_list(self):
        self.assertEqual(self.tracker.track_batch([]), [])

    def test_single_item_batch(self):
        result = self.tracker.track_batch([("p1", [_period()])])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].portfolio_id, "p1")

    def test_multiple_items_batch(self):
        items = [(f"p{i}", [_period(ret=float(i), days=90)]) for i in range(4)]
        result = self.tracker.track_batch(items)
        self.assertEqual(len(result), 4)

    def test_batch_ids_preserved(self):
        items = [("alpha", [_period()]), ("beta", [_period()])]
        result = self.tracker.track_batch(items)
        ids = [r.portfolio_id for r in result]
        self.assertIn("alpha", ids)
        self.assertIn("beta", ids)

    def test_batch_order_preserved(self):
        items = [("first", [_period(ret=1.0, days=90)]),
                 ("second", [_period(ret=2.0, days=90)])]
        result = self.tracker.track_batch(items)
        self.assertEqual(result[0].portfolio_id, "first")
        self.assertEqual(result[1].portfolio_id, "second")


# ---------------------------------------------------------------------------
# 11. save_results / load_history
# ---------------------------------------------------------------------------


class TestSaveLoadHistory(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _tracker(self.tmp)

    def test_load_missing_file_returns_empty(self):
        self.assertEqual(self.tracker.load_history(), [])

    def test_save_then_load_one_entry(self):
        r = self.tracker.track("p1", [_period()])
        self.tracker.save_results(r)
        history = self.tracker.load_history()
        self.assertEqual(len(history), 1)

    def test_saved_portfolio_id(self):
        r = self.tracker.track("saved_p", [_period()])
        self.tracker.save_results(r)
        history = self.tracker.load_history()
        self.assertEqual(history[0]["portfolio_id"], "saved_p")

    def test_multiple_saves(self):
        for i in range(5):
            r = self.tracker.track(f"p{i}", [_period()])
            self.tracker.save_results(r)
        self.assertEqual(len(self.tracker.load_history()), 5)

    def test_ring_buffer_capped(self):
        for i in range(MAX_ENTRIES + 10):
            r = self.tracker.track(f"p{i}", [_period()])
            self.tracker.save_results(r)
        self.assertEqual(len(self.tracker.load_history()), MAX_ENTRIES)

    def test_ring_buffer_keeps_newest(self):
        for i in range(MAX_ENTRIES + 5):
            r = self.tracker.track(f"p{i}", [_period()])
            self.tracker.save_results(r)
        history = self.tracker.load_history()
        self.assertEqual(history[0]["portfolio_id"], "p5")
        self.assertEqual(history[-1]["portfolio_id"], f"p{MAX_ENTRIES + 4}")

    def test_file_is_valid_json(self):
        r = self.tracker.track("json_test", [_period()])
        self.tracker.save_results(r)
        data_file = Path(self.tmp) / "benchmark_tracker_log.json"
        with open(data_file) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_atomic_write_creates_file(self):
        r = self.tracker.track("atomic", [_period()])
        self.tracker.save_results(r)
        data_file = Path(self.tmp) / "benchmark_tracker_log.json"
        self.assertTrue(data_file.exists())

    def test_load_corrupt_json_returns_empty(self):
        data_file = Path(self.tmp) / "benchmark_tracker_log.json"
        data_file.write_text("not-valid-json{{")
        self.assertEqual(self.tracker.load_history(), [])

    def test_load_non_list_returns_empty(self):
        data_file = Path(self.tmp) / "benchmark_tracker_log.json"
        data_file.write_text('{"key": "val"}')
        self.assertEqual(self.tracker.load_history(), [])

    def test_generated_at_present(self):
        r = self.tracker.track("ts", [_period()])
        self.tracker.save_results(r)
        history = self.tracker.load_history()
        self.assertIn("generated_at", history[0])

    def test_data_dir_created_if_missing(self):
        nested = Path(self.tmp) / "deep" / "sub"
        t = _tracker(str(nested))
        r = t.track("nd", [_period()])
        t.save_results(r)
        self.assertTrue(nested.exists())

    def test_two_trackers_independent(self):
        tmp1, tmp2 = tempfile.mkdtemp(), tempfile.mkdtemp()
        t1, t2 = _tracker(tmp1), _tracker(tmp2)
        r = t1.track("p1", [_period()])
        t1.save_results(r)
        self.assertEqual(len(t1.load_history()), 1)
        self.assertEqual(len(t2.load_history()), 0)


if __name__ == "__main__":
    unittest.main()
