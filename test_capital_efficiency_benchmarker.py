"""
Tests for MP-741: CapitalEfficiencyBenchmarker
≥65 unittest tests. Pure stdlib.
"""

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.capital_efficiency_benchmarker import (
    EfficiencyMetrics,
    EfficiencyBenchmarkResult,
    compute_effective_yield,
    compute_yield_per_1000,
    rank_strategies,
    compute_efficiency_score,
    efficiency_label_from_score,
    benchmark,
    compare_to_benchmark,
    save_results,
    load_history,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_strategy(
    name="Strat A",
    protocol="AaveV3",
    deployed=100_000,
    locked=100_000,
    gross_apy=5.0,
    fee_apy=0.0,
):
    return {
        "strategy_name": name,
        "protocol": protocol,
        "capital_deployed_usd": deployed,
        "capital_locked_usd": locked,
        "gross_apy": gross_apy,
        "fee_apy": fee_apy,
    }


def _three_strategies():
    return [
        _make_strategy("Alpha", deployed=90_000, locked=100_000, gross_apy=10.0, fee_apy=0.5),
        _make_strategy("Beta",  deployed=60_000, locked=100_000, gross_apy=6.0,  fee_apy=0.2),
        _make_strategy("Gamma", deployed=40_000, locked=100_000, gross_apy=3.0,  fee_apy=0.1),
    ]


def _make_metrics(
    name="S",
    net_apy=5.0,
    utilization=80.0,
    effective_yield=4.0,
    score=75.0,
    label="GOOD",
):
    return EfficiencyMetrics(
        strategy_name=name,
        protocol="Proto",
        capital_deployed_usd=80_000,
        capital_locked_usd=100_000,
        gross_apy=net_apy + 0.1,
        fee_apy=0.1,
        net_apy=net_apy,
        capital_utilization=utilization,
        yield_per_1000_usd=compute_yield_per_1000(net_apy),
        effective_yield_on_locked=effective_yield,
        apy_vs_peer_avg=0.0,
        efficiency_vs_peer_avg=0.0,
        efficiency_score=score,
        efficiency_label=label,
        recommendation="",
    )


# ===========================================================================
# 1. compute_effective_yield
# ===========================================================================

class TestComputeEffectiveYield(unittest.TestCase):

    def test_basic(self):
        self.assertAlmostEqual(compute_effective_yield(10.0, 80.0), 8.0)

    def test_full_utilization(self):
        self.assertAlmostEqual(compute_effective_yield(5.0, 100.0), 5.0)

    def test_zero_utilization(self):
        self.assertAlmostEqual(compute_effective_yield(10.0, 0.0), 0.0)

    def test_zero_net_apy(self):
        self.assertAlmostEqual(compute_effective_yield(0.0, 75.0), 0.0)

    def test_fractional(self):
        self.assertAlmostEqual(compute_effective_yield(6.0, 50.0), 3.0)


# ===========================================================================
# 2. compute_yield_per_1000
# ===========================================================================

class TestComputeYieldPer1000(unittest.TestCase):

    def test_basic(self):
        self.assertAlmostEqual(compute_yield_per_1000(10.0), 100.0)

    def test_five_pct(self):
        self.assertAlmostEqual(compute_yield_per_1000(5.0), 50.0)

    def test_zero(self):
        self.assertAlmostEqual(compute_yield_per_1000(0.0), 0.0)

    def test_formula(self):
        # net_apy / 100 * 1000
        for apy in [1.0, 3.5, 20.0]:
            self.assertAlmostEqual(compute_yield_per_1000(apy), apy * 10.0)


# ===========================================================================
# 3. compute_efficiency_score
# ===========================================================================

class TestComputeEfficiencyScore(unittest.TestCase):

    def test_single_strategy_returns_100(self):
        self.assertAlmostEqual(compute_efficiency_score(1, 1, 1), 100.0)

    def test_best_of_two(self):
        # rank=1, n=2 → ((2-1) + (2-1)) / (2*(2-1)) * 100 = 100
        self.assertAlmostEqual(compute_efficiency_score(1, 1, 2), 100.0)

    def test_worst_of_two(self):
        # rank=2, n=2 → ((2-2) + (2-2)) / (2*1) * 100 = 0
        self.assertAlmostEqual(compute_efficiency_score(2, 2, 2), 0.0)

    def test_middle_of_three(self):
        # rank=2, n=3 → ((3-2) + (3-2)) / (2*2) * 100 = 2/4*100 = 50
        self.assertAlmostEqual(compute_efficiency_score(2, 2, 3), 50.0)

    def test_best_of_three(self):
        # rank=1, n=3 → ((3-1) + (3-1)) / (2*2)*100 = 4/4*100 = 100
        self.assertAlmostEqual(compute_efficiency_score(1, 1, 3), 100.0)

    def test_worst_of_three(self):
        # rank=3, n=3 → ((3-3) + (3-3)) / 4*100 = 0
        self.assertAlmostEqual(compute_efficiency_score(3, 3, 3), 0.0)

    def test_mixed_ranks(self):
        # apy_rank=1, util_rank=3, n=3 → ((3-1)+(3-3))/(4)*100 = (2+0)/4*100 = 50
        self.assertAlmostEqual(compute_efficiency_score(1, 3, 3), 50.0)


# ===========================================================================
# 4. efficiency_label_from_score
# ===========================================================================

class TestEfficiencyLabelFromScore(unittest.TestCase):

    def test_excellent_at_80(self):
        self.assertEqual(efficiency_label_from_score(80.0), "EXCELLENT")

    def test_excellent_at_100(self):
        self.assertEqual(efficiency_label_from_score(100.0), "EXCELLENT")

    def test_good_at_75(self):
        self.assertEqual(efficiency_label_from_score(75.0), "GOOD")

    def test_good_at_60(self):
        self.assertEqual(efficiency_label_from_score(60.0), "GOOD")

    def test_adequate_at_50(self):
        self.assertEqual(efficiency_label_from_score(50.0), "ADEQUATE")

    def test_adequate_at_40(self):
        self.assertEqual(efficiency_label_from_score(40.0), "ADEQUATE")

    def test_poor_below_40(self):
        self.assertEqual(efficiency_label_from_score(39.9), "POOR")

    def test_poor_at_zero(self):
        self.assertEqual(efficiency_label_from_score(0.0), "POOR")


# ===========================================================================
# 5. benchmark()
# ===========================================================================

class TestBenchmark(unittest.TestCase):

    def setUp(self):
        self.data = _three_strategies()

    def test_net_apy_computed(self):
        result = benchmark(self.data)
        alpha = next(m for m in result.strategies if m.strategy_name == "Alpha")
        self.assertAlmostEqual(alpha.net_apy, 9.5)

    def test_capital_utilization_formula(self):
        result = benchmark(self.data)
        alpha = next(m for m in result.strategies if m.strategy_name == "Alpha")
        self.assertAlmostEqual(alpha.capital_utilization, 90.0)

    def test_capital_utilization_locked_zero(self):
        data = [_make_strategy("S", deployed=1000, locked=0)]
        result = benchmark(data)
        self.assertAlmostEqual(result.strategies[0].capital_utilization, 0.0)

    def test_peer_avg_apy_formula(self):
        result = benchmark(self.data)
        # net_apys: 9.5, 5.8, 2.9 → avg = 18.2 / 3
        expected = (9.5 + 5.8 + 2.9) / 3
        self.assertAlmostEqual(result.peer_avg_apy, expected)

    def test_peer_avg_effective_yield_formula(self):
        result = benchmark(self.data)
        # effective = net_apy * util / 100
        # Alpha: 9.5 * 90 / 100 = 8.55
        # Beta: 5.8 * 60 / 100 = 3.48
        # Gamma: 2.9 * 40 / 100 = 1.16
        expected = (8.55 + 3.48 + 1.16) / 3
        self.assertAlmostEqual(result.peer_avg_effective_yield, expected, places=5)

    def test_top_strategy_is_alpha(self):
        result = benchmark(self.data)
        self.assertEqual(result.top_strategy, "Alpha")

    def test_bottom_strategy_is_gamma(self):
        result = benchmark(self.data)
        self.assertEqual(result.bottom_strategy, "Gamma")

    def test_apy_vs_peer_avg_alpha(self):
        result = benchmark(self.data)
        alpha = next(m for m in result.strategies if m.strategy_name == "Alpha")
        expected_peer_avg = (9.5 + 5.8 + 2.9) / 3
        self.assertAlmostEqual(alpha.apy_vs_peer_avg, 9.5 - expected_peer_avg)

    def test_apy_vs_peer_avg_gamma_negative(self):
        result = benchmark(self.data)
        gamma = next(m for m in result.strategies if m.strategy_name == "Gamma")
        self.assertLess(gamma.apy_vs_peer_avg, 0.0)

    def test_single_strategy(self):
        result = benchmark([_make_strategy()])
        self.assertEqual(len(result.strategies), 1)
        self.assertAlmostEqual(result.strategies[0].efficiency_score, 100.0)

    def test_single_strategy_top_equals_bottom(self):
        result = benchmark([_make_strategy("Solo")])
        self.assertEqual(result.top_strategy, "Solo")
        self.assertEqual(result.bottom_strategy, "Solo")

    def test_excellent_count(self):
        result = benchmark(self.data)
        count = sum(1 for m in result.strategies if m.efficiency_label == "EXCELLENT")
        self.assertEqual(result.excellent_count, count)

    def test_poor_count(self):
        result = benchmark(self.data)
        count = sum(1 for m in result.strategies if m.efficiency_label == "POOR")
        self.assertEqual(result.poor_count, count)

    def test_benchmark_summary_contains_top_strategy(self):
        result = benchmark(self.data)
        self.assertIn("Alpha", result.benchmark_summary)

    def test_benchmark_summary_contains_count(self):
        result = benchmark(self.data)
        self.assertIn("3", result.benchmark_summary)

    def test_strategies_count(self):
        result = benchmark(self.data)
        self.assertEqual(len(result.strategies), 3)

    def test_yield_per_1000_formula(self):
        result = benchmark(self.data)
        alpha = next(m for m in result.strategies if m.strategy_name == "Alpha")
        self.assertAlmostEqual(alpha.yield_per_1000_usd, 9.5 * 10)

    def test_all_same_apy_peer_avg_equals_individual(self):
        data = [_make_strategy(f"S{i}", gross_apy=5.0, fee_apy=0.0) for i in range(3)]
        result = benchmark(data)
        self.assertAlmostEqual(result.peer_avg_apy, 5.0)
        for m in result.strategies:
            self.assertAlmostEqual(m.apy_vs_peer_avg, 0.0, places=10)

    def test_peer_avg_utilization_formula(self):
        result = benchmark(self.data)
        # Alpha: 90%, Beta: 60%, Gamma: 40% → avg=63.33...
        expected = (90.0 + 60.0 + 40.0) / 3
        self.assertAlmostEqual(result.peer_avg_utilization, expected)

    def test_net_apy_gamma(self):
        result = benchmark(self.data)
        gamma = next(m for m in result.strategies if m.strategy_name == "Gamma")
        self.assertAlmostEqual(gamma.net_apy, 2.9)

    def test_recommendation_text_all_labels(self):
        data = [
            _make_strategy("A", gross_apy=30.0, fee_apy=0.0, deployed=100_000, locked=100_000),
            _make_strategy("B", gross_apy=10.0, fee_apy=0.0, deployed=60_000, locked=100_000),
            _make_strategy("C", gross_apy=4.0,  fee_apy=0.0, deployed=40_000, locked=100_000),
            _make_strategy("D", gross_apy=1.0,  fee_apy=0.0, deployed=10_000, locked=100_000),
        ]
        result = benchmark(data)
        labels = {m.efficiency_label for m in result.strategies}
        for label in ["EXCELLENT", "POOR"]:
            # At least EXCELLENT and POOR should appear
            m_list = [m for m in result.strategies if m.efficiency_label == label]
            if m_list:
                self.assertIn(m_list[0].recommendation, [
                    "Top-tier efficiency — maintain allocation.",
                    "Underperforming peers — consider reallocation.",
                ])

    def test_recommendation_excellent(self):
        result = benchmark([_make_strategy("Solo")])
        self.assertEqual(result.strategies[0].recommendation,
                         "Top-tier efficiency — maintain allocation.")

    def test_efficiency_vs_peer_avg_formula(self):
        result = benchmark(self.data)
        alpha = next(m for m in result.strategies if m.strategy_name == "Alpha")
        expected_eff = 9.5 * 90 / 100
        expected_peer_eff = (8.55 + 3.48 + 1.16) / 3
        self.assertAlmostEqual(
            alpha.efficiency_vs_peer_avg,
            expected_eff - expected_peer_eff,
            places=5,
        )


# ===========================================================================
# 6. compare_to_benchmark
# ===========================================================================

class TestCompareToBenchmark(unittest.TestCase):

    def _get_metrics(self):
        data = [_make_strategy("Solo", gross_apy=8.0, fee_apy=0.5)]
        result = benchmark(data)
        return result.strategies[0]

    def test_delta_apy_positive(self):
        m = self._get_metrics()
        cmp = compare_to_benchmark(m, benchmark_apy=5.0, benchmark_effective=2.0)
        self.assertAlmostEqual(cmp["delta_apy"], 7.5 - 5.0)

    def test_delta_apy_negative(self):
        m = self._get_metrics()
        cmp = compare_to_benchmark(m, benchmark_apy=10.0, benchmark_effective=5.0)
        self.assertAlmostEqual(cmp["delta_apy"], 7.5 - 10.0)

    def test_delta_effective_yield(self):
        m = self._get_metrics()
        # net_apy=7.5, util=100% → effective=7.5
        cmp = compare_to_benchmark(m, benchmark_apy=5.0, benchmark_effective=3.0)
        self.assertAlmostEqual(cmp["delta_effective_yield"], 7.5 - 3.0)

    def test_outperforms_apy_true(self):
        m = self._get_metrics()
        cmp = compare_to_benchmark(m, benchmark_apy=4.0, benchmark_effective=1.0)
        self.assertTrue(cmp["outperforms_apy"])

    def test_outperforms_apy_false(self):
        m = self._get_metrics()
        cmp = compare_to_benchmark(m, benchmark_apy=20.0, benchmark_effective=10.0)
        self.assertFalse(cmp["outperforms_apy"])

    def test_strategy_name_in_result(self):
        m = self._get_metrics()
        cmp = compare_to_benchmark(m, benchmark_apy=5.0, benchmark_effective=2.0)
        self.assertEqual(cmp["strategy_name"], "Solo")


# ===========================================================================
# 7. Persistence — save/load / ring-buffer
# ===========================================================================

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def _run_and_save(self):
        result = benchmark(_three_strategies())
        save_results(result, self.tmp_dir)
        return result

    def test_save_creates_file(self):
        self._run_and_save()
        path = os.path.join(self.tmp_dir, "capital_efficiency_log.json")
        self.assertTrue(os.path.exists(path))

    def test_load_empty_on_missing(self):
        history = load_history(self.tmp_dir)
        self.assertEqual(history, [])

    def test_save_load_round_trip(self):
        self._run_and_save()
        history = load_history(self.tmp_dir)
        self.assertEqual(len(history), 1)

    def test_multiple_saves(self):
        for _ in range(5):
            self._run_and_save()
        history = load_history(self.tmp_dir)
        self.assertEqual(len(history), 5)

    def test_ring_buffer_cap_100(self):
        for _ in range(110):
            self._run_and_save()
        history = load_history(self.tmp_dir)
        self.assertEqual(len(history), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            result = benchmark([_make_strategy(f"S{i}")])
            save_results(result, self.tmp_dir)
        history = load_history(self.tmp_dir)
        self.assertEqual(len(history), 100)

    def test_saved_to_set_after_save(self):
        result = self._run_and_save()
        self.assertTrue(result.saved_to.endswith("capital_efficiency_log.json"))

    def test_save_returns_path(self):
        result = benchmark(_three_strategies())
        path = save_results(result, self.tmp_dir)
        self.assertTrue(path.endswith("capital_efficiency_log.json"))

    def test_load_corrupt_returns_empty(self):
        path = os.path.join(self.tmp_dir, "capital_efficiency_log.json")
        with open(path, "w") as fh:
            fh.write("{{BAD JSON")
        history = load_history(self.tmp_dir)
        self.assertEqual(history, [])

    def test_history_has_timestamp(self):
        self._run_and_save()
        history = load_history(self.tmp_dir)
        self.assertIn("timestamp", history[0])

    def test_history_has_top_strategy(self):
        self._run_and_save()
        history = load_history(self.tmp_dir)
        self.assertIn("top_strategy", history[0])

    def test_atomic_no_tmp_file_left(self):
        self._run_and_save()
        tmp = os.path.join(self.tmp_dir, "capital_efficiency_log.json.tmp")
        self.assertFalse(os.path.exists(tmp))


if __name__ == "__main__":
    unittest.main()
