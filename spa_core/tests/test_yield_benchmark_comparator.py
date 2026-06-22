"""
MP-832 — Unit tests for YieldBenchmarkComparator.
stdlib unittest only; ≥ 65 tests.
Run: python3 -m unittest spa_core.tests.test_yield_benchmark_comparator -v
"""

import json
import tempfile
import time
import unittest
from pathlib import Path

from spa_core.analytics.yield_benchmark_comparator import (
    analyze,
    save_log,
    load_log,
    _compute_verdict,
    MAX_ENTRIES,
    VERDICT_EXCELLENT,
    VERDICT_GOOD,
    VERDICT_FAIR,
    VERDICT_POOR,
    VERDICT_AVOID,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_BENCHMARKS = {
    "risk_free_rate": 4.5,
    "eth_staking_apy": 3.8,
    "btc_holding_apy": 0.0,
}


def make_strategy(name="Aave", apy=6.0, risk_score=30, liquidity="HIGH"):
    return {"name": name, "apy": apy, "risk_score": risk_score, "liquidity": liquidity}


# ---------------------------------------------------------------------------
# 1. _compute_verdict
# ---------------------------------------------------------------------------

class TestComputeVerdict(unittest.TestCase):
    def test_avoid_zero_apy(self):
        v = _compute_verdict(0.0, 10, 0.0, 4.5)
        self.assertEqual(v, VERDICT_AVOID)

    def test_avoid_negative_apy(self):
        v = _compute_verdict(-1.0, 10, -0.7, 4.5)
        self.assertEqual(v, VERDICT_AVOID)

    def test_avoid_risk_score_90(self):
        v = _compute_verdict(10.0, 90, 1.0, 4.5)
        self.assertEqual(v, VERDICT_AVOID)

    def test_avoid_risk_score_100(self):
        v = _compute_verdict(10.0, 100, 0.0, 4.5)
        self.assertEqual(v, VERDICT_AVOID)

    def test_excellent_standard(self):
        # rfr=4.5, rfr*2=9.0; risk_adj=10.0 >= 9.0 AND risk_score=30 < 50
        v = _compute_verdict(12.0, 30, 10.0, 4.5)
        self.assertEqual(v, VERDICT_EXCELLENT)

    def test_excellent_at_rfr_zero_with_positive_adj(self):
        # rfr=0, rfr*2=0; risk_adj=4.0 >= 0 AND risk_score=20 < 50 → EXCELLENT
        v = _compute_verdict(5.0, 20, 4.0, 0.0)
        self.assertEqual(v, VERDICT_EXCELLENT)

    def test_excellent_boundary_risk_score_49(self):
        v = _compute_verdict(12.0, 49, 10.0, 4.5)
        self.assertEqual(v, VERDICT_EXCELLENT)

    def test_not_excellent_risk_score_50(self):
        # risk_score=50, not < 50 → not EXCELLENT
        # risk_adj=10 > rfr=4.5 AND risk_score=50 < 70 → GOOD
        v = _compute_verdict(12.0, 50, 10.0, 4.5)
        self.assertEqual(v, VERDICT_GOOD)

    def test_good_standard(self):
        # risk_adj=5.0 > rfr=4.5 AND risk_score=60 < 70
        v = _compute_verdict(8.0, 60, 5.0, 4.5)
        self.assertEqual(v, VERDICT_GOOD)

    def test_good_boundary_risk_score_69(self):
        v = _compute_verdict(8.0, 69, 5.0, 4.5)
        self.assertEqual(v, VERDICT_GOOD)

    def test_not_good_risk_score_70(self):
        # risk_score=70 not < 70; apy=8 > rfr=4.5; risk_adj=2.4 <= rfr=4.5 → FAIR
        v = _compute_verdict(8.0, 70, 2.4, 4.5)
        self.assertEqual(v, VERDICT_FAIR)

    def test_fair_standard(self):
        # apy=5.0 > rfr=4.5 AND risk_adj=2.0 <= rfr=4.5
        v = _compute_verdict(5.0, 60, 2.0, 4.5)
        self.assertEqual(v, VERDICT_FAIR)

    def test_poor_standard(self):
        # apy=3.0 <= rfr=4.5 AND apy > 0
        v = _compute_verdict(3.0, 30, 2.1, 4.5)
        self.assertEqual(v, VERDICT_POOR)

    def test_poor_apy_equals_rfr(self):
        v = _compute_verdict(4.5, 30, 3.0, 4.5)
        self.assertEqual(v, VERDICT_POOR)

    def test_avoid_risk_score_89_can_be_fair(self):
        # risk_score=89 < 90 → not AVOID
        # risk_adj = 20*(1-89/100) = 2.2 not >= rfr*2=9; not EXCELLENT
        # risk_score=89 not < 70 → not GOOD
        # apy=20 > rfr=4.5; risk_adj=2.2 <= rfr=4.5 → FAIR
        v = _compute_verdict(20.0, 89, 2.2, 4.5)
        self.assertEqual(v, VERDICT_FAIR)


# ---------------------------------------------------------------------------
# 2. analyze() basic structure
# ---------------------------------------------------------------------------

class TestAnalyzeStructure(unittest.TestCase):
    def test_returns_dict(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        self.assertIsInstance(result, dict)

    def test_has_strategies_key(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        self.assertIn("strategies", result)

    def test_has_best_risk_adjusted(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        self.assertIn("best_risk_adjusted", result)

    def test_has_best_raw_yield(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        self.assertIn("best_raw_yield", result)

    def test_has_benchmark_summary(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        self.assertIn("benchmark_summary", result)

    def test_has_timestamp(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        self.assertIn("timestamp", result)

    def test_timestamp_is_recent(self):
        before = time.time()
        result = analyze([], DEFAULT_BENCHMARKS)
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_empty_strategies_list(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        self.assertEqual(result["strategies"], [])

    def test_empty_best_risk_adjusted_none(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        self.assertIsNone(result["best_risk_adjusted"])

    def test_empty_best_raw_yield_none(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        self.assertIsNone(result["best_raw_yield"])

    def test_benchmark_summary_keys(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        bs = result["benchmark_summary"]
        for k in ["risk_free_rate", "eth_staking_apy", "btc_holding_apy",
                  "strategies_beating_rfr", "strategies_beating_eth"]:
            self.assertIn(k, bs)

    def test_strategy_result_keys(self):
        strat = make_strategy()
        result = analyze([strat], DEFAULT_BENCHMARKS)
        s = result["strategies"][0]
        for k in ["name", "apy", "risk_score", "risk_adjusted_apy", "excess_over_rfr",
                  "excess_over_eth_staking", "risk_premium", "verdict",
                  "better_than_rfr", "better_than_eth", "liquidity_tier"]:
            self.assertIn(k, s)


# ---------------------------------------------------------------------------
# 3. risk_adjusted_apy computation
# ---------------------------------------------------------------------------

class TestRiskAdjustedAPY(unittest.TestCase):
    def test_zero_risk_score(self):
        strat = make_strategy(apy=10.0, risk_score=0)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertAlmostEqual(result["strategies"][0]["risk_adjusted_apy"], 10.0)

    def test_100_risk_score_zero_adj(self):
        strat = make_strategy(apy=10.0, risk_score=100)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertAlmostEqual(result["strategies"][0]["risk_adjusted_apy"], 0.0)

    def test_50_risk_score_halves_apy(self):
        strat = make_strategy(apy=10.0, risk_score=50)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertAlmostEqual(result["strategies"][0]["risk_adjusted_apy"], 5.0)

    def test_risk_adjusted_formula(self):
        strat = make_strategy(apy=8.0, risk_score=25)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        # 8.0 * (1 - 25/100) = 6.0
        self.assertAlmostEqual(result["strategies"][0]["risk_adjusted_apy"], 6.0)


# ---------------------------------------------------------------------------
# 4. excess_over_rfr and excess_over_eth_staking
# ---------------------------------------------------------------------------

class TestExcessReturns(unittest.TestCase):
    def test_excess_over_rfr_positive(self):
        strat = make_strategy(apy=7.0)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertAlmostEqual(result["strategies"][0]["excess_over_rfr"], 2.5)

    def test_excess_over_rfr_negative(self):
        strat = make_strategy(apy=3.0)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertAlmostEqual(result["strategies"][0]["excess_over_rfr"], -1.5)

    def test_excess_over_eth_staking(self):
        strat = make_strategy(apy=6.0)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertAlmostEqual(result["strategies"][0]["excess_over_eth_staking"], 2.2)

    def test_risk_premium_formula(self):
        strat = make_strategy(apy=10.0, risk_score=25)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        # risk_adj = 10*(1-0.25) = 7.5; risk_premium = 7.5 - 4.5 = 3.0
        self.assertAlmostEqual(result["strategies"][0]["risk_premium"], 3.0)


# ---------------------------------------------------------------------------
# 5. better_than_rfr / better_than_eth
# ---------------------------------------------------------------------------

class TestBetterThan(unittest.TestCase):
    def test_better_than_rfr_true(self):
        strat = make_strategy(apy=5.0)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertTrue(result["strategies"][0]["better_than_rfr"])

    def test_better_than_rfr_false(self):
        strat = make_strategy(apy=3.0)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertFalse(result["strategies"][0]["better_than_rfr"])

    def test_better_than_rfr_equal_is_false(self):
        strat = make_strategy(apy=4.5)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertFalse(result["strategies"][0]["better_than_rfr"])

    def test_better_than_eth_true(self):
        strat = make_strategy(apy=5.0)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertTrue(result["strategies"][0]["better_than_eth"])

    def test_better_than_eth_false(self):
        strat = make_strategy(apy=2.0)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertFalse(result["strategies"][0]["better_than_eth"])

    def test_better_than_eth_equal_is_false(self):
        strat = make_strategy(apy=3.8)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertFalse(result["strategies"][0]["better_than_eth"])


# ---------------------------------------------------------------------------
# 6. Verdict assignments via analyze()
# ---------------------------------------------------------------------------

class TestVerdictViaAnalyze(unittest.TestCase):
    def test_avoid_zero_apy(self):
        strat = make_strategy(apy=0.0, risk_score=10)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertEqual(result["strategies"][0]["verdict"], VERDICT_AVOID)

    def test_avoid_high_risk(self):
        strat = make_strategy(apy=20.0, risk_score=90)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertEqual(result["strategies"][0]["verdict"], VERDICT_AVOID)

    def test_excellent_high_yield_low_risk(self):
        # apy=12, risk=20 → risk_adj=9.6 >= rfr*2=9.0 AND risk_score=20 < 50 → EXCELLENT
        strat = make_strategy(apy=12.0, risk_score=20)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertEqual(result["strategies"][0]["verdict"], VERDICT_EXCELLENT)

    def test_good_verdict_explicitly(self):
        # apy=10, risk=50 → risk_adj=5.0 > rfr=4.5; 5.0 < rfr*2=9.0 → not EXCELLENT
        # risk_score=50 < 70 → GOOD
        strat = make_strategy(apy=10.0, risk_score=50)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertEqual(result["strategies"][0]["verdict"], VERDICT_GOOD)

    def test_fair_verdict(self):
        # apy=5.0 > rfr=4.5; risk_adj = 5*(1-70/100)=1.5 <= rfr=4.5 → FAIR
        strat = make_strategy(apy=5.0, risk_score=70)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertEqual(result["strategies"][0]["verdict"], VERDICT_FAIR)

    def test_poor_verdict(self):
        strat = make_strategy(apy=3.0, risk_score=10)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertEqual(result["strategies"][0]["verdict"], VERDICT_POOR)

    def test_avoid_negative_apy(self):
        strat = make_strategy(apy=-2.0, risk_score=10)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertEqual(result["strategies"][0]["verdict"], VERDICT_AVOID)

    def test_fair_high_risk_high_apy(self):
        # apy=8, risk=60 → risk_adj=3.2; 3.2 not > rfr=4.5 → not GOOD
        # apy=8 > rfr=4.5; risk_adj=3.2 <= rfr=4.5 → FAIR
        strat = make_strategy(apy=8.0, risk_score=60)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertEqual(result["strategies"][0]["verdict"], VERDICT_FAIR)


# ---------------------------------------------------------------------------
# 7. benchmark_summary counts
# ---------------------------------------------------------------------------

class TestBenchmarkSummaryCounts(unittest.TestCase):
    def test_empty_strategies_zero_counts(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        bs = result["benchmark_summary"]
        self.assertEqual(bs["strategies_beating_rfr"], 0)
        self.assertEqual(bs["strategies_beating_eth"], 0)

    def test_one_beating_rfr(self):
        strat = make_strategy(apy=5.0)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertEqual(result["benchmark_summary"]["strategies_beating_rfr"], 1)

    def test_none_beating_rfr(self):
        strat = make_strategy(apy=3.0)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertEqual(result["benchmark_summary"]["strategies_beating_rfr"], 0)

    def test_two_beating_eth_one_not(self):
        s1 = make_strategy("A", apy=5.0)
        s2 = make_strategy("B", apy=4.0)
        s3 = make_strategy("C", apy=3.0)
        result = analyze([s1, s2, s3], DEFAULT_BENCHMARKS)
        self.assertEqual(result["benchmark_summary"]["strategies_beating_eth"], 2)

    def test_benchmark_summary_passes_through_values(self):
        bench = {"risk_free_rate": 5.0, "eth_staking_apy": 4.0, "btc_holding_apy": 1.0}
        result = analyze([], bench)
        bs = result["benchmark_summary"]
        self.assertAlmostEqual(bs["risk_free_rate"], 5.0)
        self.assertAlmostEqual(bs["eth_staking_apy"], 4.0)
        self.assertAlmostEqual(bs["btc_holding_apy"], 1.0)


# ---------------------------------------------------------------------------
# 8. best_risk_adjusted and best_raw_yield
# ---------------------------------------------------------------------------

class TestBestSelectors(unittest.TestCase):
    def test_best_raw_yield_single(self):
        strat = make_strategy(name="Alpha", apy=8.0)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertEqual(result["best_raw_yield"], "Alpha")

    def test_best_raw_yield_multiple(self):
        s1 = make_strategy("A", apy=6.0)
        s2 = make_strategy("B", apy=10.0)
        s3 = make_strategy("C", apy=4.0)
        result = analyze([s1, s2, s3], DEFAULT_BENCHMARKS)
        self.assertEqual(result["best_raw_yield"], "B")

    def test_best_risk_adjusted_single(self):
        strat = make_strategy(name="Beta", apy=8.0, risk_score=10)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertEqual(result["best_risk_adjusted"], "Beta")

    def test_best_risk_adjusted_picks_lower_risk(self):
        # A: apy=12, risk=80 → risk_adj=2.4
        # B: apy=8, risk=10 → risk_adj=7.2
        s1 = make_strategy("A", apy=12.0, risk_score=80)
        s2 = make_strategy("B", apy=8.0, risk_score=10)
        result = analyze([s1, s2], DEFAULT_BENCHMARKS)
        self.assertEqual(result["best_risk_adjusted"], "B")

    def test_best_raw_yield_different_from_best_risk_adjusted(self):
        s1 = make_strategy("HighRaw", apy=20.0, risk_score=80)
        s2 = make_strategy("LowRisk", apy=8.0, risk_score=5)
        result = analyze([s1, s2], DEFAULT_BENCHMARKS)
        self.assertEqual(result["best_raw_yield"], "HighRaw")
        self.assertEqual(result["best_risk_adjusted"], "LowRisk")

    def test_empty_strategies_best_none(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        self.assertIsNone(result["best_risk_adjusted"])
        self.assertIsNone(result["best_raw_yield"])


# ---------------------------------------------------------------------------
# 9. liquidity tier pass-through
# ---------------------------------------------------------------------------

class TestLiquidityTier(unittest.TestCase):
    def test_high_liquidity_passthrough(self):
        strat = make_strategy(liquidity="HIGH")
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertEqual(result["strategies"][0]["liquidity_tier"], "HIGH")

    def test_medium_liquidity_passthrough(self):
        strat = make_strategy(liquidity="MEDIUM")
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertEqual(result["strategies"][0]["liquidity_tier"], "MEDIUM")

    def test_low_liquidity_passthrough(self):
        strat = make_strategy(liquidity="LOW")
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertEqual(result["strategies"][0]["liquidity_tier"], "LOW")


# ---------------------------------------------------------------------------
# 10. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_risk_score_100_all_avoid(self):
        s = make_strategy(apy=20.0, risk_score=100)
        result = analyze([s], DEFAULT_BENCHMARKS)
        self.assertEqual(result["strategies"][0]["verdict"], VERDICT_AVOID)
        self.assertAlmostEqual(result["strategies"][0]["risk_adjusted_apy"], 0.0)

    def test_risk_score_clamped_above_100(self):
        s = {"name": "X", "apy": 10.0, "risk_score": 150, "liquidity": "HIGH"}
        result = analyze([s], DEFAULT_BENCHMARKS)
        self.assertEqual(result["strategies"][0]["risk_score"], 100)

    def test_risk_score_clamped_below_0(self):
        s = {"name": "X", "apy": 10.0, "risk_score": -10, "liquidity": "HIGH"}
        result = analyze([s], DEFAULT_BENCHMARKS)
        self.assertEqual(result["strategies"][0]["risk_score"], 0)

    def test_rfr_zero_no_divide_error(self):
        bench = {"risk_free_rate": 0.0, "eth_staking_apy": 0.0, "btc_holding_apy": 0.0}
        strat = make_strategy(apy=5.0, risk_score=20)
        result = analyze([strat], bench)
        s = result["strategies"][0]
        # risk_adj = 5*(1-0.2) = 4.0; rfr*2=0; 4.0>=0 AND risk_score=20<50 → EXCELLENT
        self.assertEqual(s["verdict"], VERDICT_EXCELLENT)

    def test_many_strategies_correct_count(self):
        strategies = [make_strategy(f"S{i}", apy=float(i + 1), risk_score=20) for i in range(20)]
        result = analyze(strategies, DEFAULT_BENCHMARKS)
        self.assertEqual(len(result["strategies"]), 20)

    def test_name_passthrough(self):
        strat = make_strategy(name="Morpho Steakhouse")
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertEqual(result["strategies"][0]["name"], "Morpho Steakhouse")

    def test_config_none_no_error(self):
        strat = make_strategy()
        result = analyze([strat], DEFAULT_BENCHMARKS, config=None)
        self.assertIn("strategies", result)

    def test_config_with_label(self):
        strat = make_strategy()
        result = analyze([strat], DEFAULT_BENCHMARKS, config={"risk_free_label": "Fed Funds"})
        self.assertIn("strategies", result)

    def test_apy_passthrough(self):
        strat = make_strategy(apy=7.77)
        result = analyze([strat], DEFAULT_BENCHMARKS)
        self.assertAlmostEqual(result["strategies"][0]["apy"], 7.77)


# ---------------------------------------------------------------------------
# 11. save_log / load_log
# ---------------------------------------------------------------------------

class TestSaveLoadLog(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "data" / "yield_benchmark_log.json"

    def test_save_creates_file(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        save_log(result, self.data_file)
        self.assertTrue(self.data_file.exists())

    def test_saved_data_is_list(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        save_log(result, self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertIsInstance(data, list)

    def test_save_appends_entries(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        save_log(result, self.data_file)
        save_log(result, self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), 2)

    def test_ring_buffer_max_entries(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        for _ in range(MAX_ENTRIES + 10):
            save_log(result, self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_load_missing_returns_empty(self):
        missing = Path(self.tmp_dir) / "nonexistent.json"
        data = load_log(missing)
        self.assertEqual(data, [])

    def test_load_returns_list(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        save_log(result, self.data_file)
        data = load_log(self.data_file)
        self.assertIsInstance(data, list)

    def test_no_leftover_tmp_file(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        save_log(result, self.data_file)
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_corrupt_file_returns_empty(self):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.data_file.write_text("INVALID_JSON{{")
        data = load_log(self.data_file)
        self.assertEqual(data, [])

    def test_saved_entry_has_timestamp(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        save_log(result, self.data_file)
        data = load_log(self.data_file)
        self.assertIn("timestamp", data[0])

    def test_saved_entry_has_benchmark_summary(self):
        result = analyze([], DEFAULT_BENCHMARKS)
        save_log(result, self.data_file)
        data = load_log(self.data_file)
        self.assertIn("benchmark_summary", data[0])


# ---------------------------------------------------------------------------
# 12. Multiple strategies integration
# ---------------------------------------------------------------------------

class TestMultipleStrategies(unittest.TestCase):
    def test_three_strategies_returned(self):
        s1 = make_strategy("A", apy=10.0, risk_score=20)
        s2 = make_strategy("B", apy=5.0, risk_score=40)
        s3 = make_strategy("C", apy=3.0, risk_score=10)
        result = analyze([s1, s2, s3], DEFAULT_BENCHMARKS)
        self.assertEqual(len(result["strategies"]), 3)

    def test_beating_rfr_count_correct(self):
        s1 = make_strategy("A", apy=10.0, risk_score=20)
        s2 = make_strategy("B", apy=5.0, risk_score=40)
        s3 = make_strategy("C", apy=3.0, risk_score=10)
        result = analyze([s1, s2, s3], DEFAULT_BENCHMARKS)
        self.assertEqual(result["benchmark_summary"]["strategies_beating_rfr"], 2)

    def test_beating_eth_count_correct(self):
        s1 = make_strategy("A", apy=10.0, risk_score=20)
        s2 = make_strategy("B", apy=5.0, risk_score=40)
        s3 = make_strategy("C", apy=3.0, risk_score=10)
        result = analyze([s1, s2, s3], DEFAULT_BENCHMARKS)
        self.assertEqual(result["benchmark_summary"]["strategies_beating_eth"], 2)

    def test_verdicts_all_assigned(self):
        strategies = [make_strategy(f"S{i}", apy=float(i + 1), risk_score=20) for i in range(5)]
        result = analyze(strategies, DEFAULT_BENCHMARKS)
        valid_verdicts = {VERDICT_EXCELLENT, VERDICT_GOOD, VERDICT_FAIR, VERDICT_POOR, VERDICT_AVOID}
        for s in result["strategies"]:
            self.assertIn(s["verdict"], valid_verdicts)

    def test_order_preserved(self):
        s1 = make_strategy("Alpha")
        s2 = make_strategy("Beta")
        s3 = make_strategy("Gamma")
        result = analyze([s1, s2, s3], DEFAULT_BENCHMARKS)
        names = [s["name"] for s in result["strategies"]]
        self.assertEqual(names, ["Alpha", "Beta", "Gamma"])

    def test_all_risk_100_all_avoid(self):
        strategies = [make_strategy(f"S{i}", apy=10.0, risk_score=100) for i in range(5)]
        result = analyze(strategies, DEFAULT_BENCHMARKS)
        for s in result["strategies"]:
            self.assertEqual(s["verdict"], VERDICT_AVOID)

    def test_portfolio_with_mixed_verdicts(self):
        s_excellent = make_strategy("E", apy=15.0, risk_score=10)
        s_avoid = make_strategy("AV", apy=0.0, risk_score=95)
        s_poor = make_strategy("P", apy=2.0, risk_score=5)
        result = analyze([s_excellent, s_avoid, s_poor], DEFAULT_BENCHMARKS)
        verdicts = [s["verdict"] for s in result["strategies"]]
        self.assertIn(VERDICT_EXCELLENT, verdicts)
        self.assertIn(VERDICT_AVOID, verdicts)
        self.assertIn(VERDICT_POOR, verdicts)


if __name__ == "__main__":
    unittest.main()
