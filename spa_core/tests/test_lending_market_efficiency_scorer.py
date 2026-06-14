"""
Tests for MP-818: LendingMarketEfficiencyScorer.

≥65 unittest cases across:
  - TestAnalyzeEdgeCases         (8)
  - TestMarketFields             (10)
  - TestSpreadScore              (9)
  - TestUtilizationScore         (8)
  - TestSizeScore                (7)
  - TestGrade                    (8)
  - TestRankings                 (8)
  - TestMarketSummary            (7)
  - TestLogResult                (7)
  - TestLoadLog                  (5)

Run:
    python3 -m unittest spa_core.tests.test_lending_market_efficiency_scorer -v
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from spa_core.analytics.lending_market_efficiency_scorer import (
    _grade,
    _size_score,
    analyze,
    load_log,
    log_result,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _market(
    protocol="Aave",
    asset="USDC",
    supply_rate=3.0,
    borrow_rate=5.0,
    utilization_rate=0.80,
    total_supply_usd=500_000_000.0,
    total_borrow_usd=400_000_000.0,
):
    return {
        "protocol": protocol,
        "asset": asset,
        "supply_rate": supply_rate,
        "borrow_rate": borrow_rate,
        "utilization_rate": utilization_rate,
        "total_supply_usd": total_supply_usd,
        "total_borrow_usd": total_borrow_usd,
    }


def _simple_markets():
    return [
        _market("Aave",     "USDC", 3.5, 5.2, 0.82, 500_000_000, 410_000_000),
        _market("Compound", "USDC", 4.0, 6.5, 0.75, 200_000_000, 150_000_000),
    ]


# ===========================================================================
# TestAnalyzeEdgeCases
# ===========================================================================

class TestAnalyzeEdgeCases(unittest.TestCase):

    def test_empty_markets_returns_empty_list(self):
        r = analyze([])
        self.assertEqual(r["markets"], [])

    def test_empty_markets_rankings_empty(self):
        r = analyze([])
        for v in r["rankings"].values():
            self.assertEqual(v, "")

    def test_empty_markets_summary_zeros(self):
        r = analyze([])
        s = r["market_summary"]
        self.assertEqual(s["avg_spread_pct"], 0.0)
        self.assertEqual(s["avg_utilization_rate"], 0.0)
        self.assertEqual(s["avg_efficiency_score"], 0.0)
        self.assertEqual(s["total_supply_usd"], 0.0)

    def test_result_has_markets_key(self):
        r = analyze(_simple_markets())
        self.assertIn("markets", r)

    def test_result_has_rankings_key(self):
        r = analyze(_simple_markets())
        self.assertIn("rankings", r)

    def test_result_has_market_summary_key(self):
        r = analyze(_simple_markets())
        self.assertIn("market_summary", r)

    def test_result_has_timestamp(self):
        before = time.time() - 1
        r = analyze(_simple_markets())
        self.assertGreater(r["timestamp"], before)

    def test_single_market_one_entry(self):
        r = analyze([_market()])
        self.assertEqual(len(r["markets"]), 1)


# ===========================================================================
# TestMarketFields
# ===========================================================================

class TestMarketFields(unittest.TestCase):

    def setUp(self):
        self.r = analyze([_market("Aave", "USDC", 3.0, 5.0, 0.8, 100_000_000, 80_000_000)])
        self.m = self.r["markets"][0]

    def test_protocol_preserved(self):
        self.assertEqual(self.m["protocol"], "Aave")

    def test_asset_preserved(self):
        self.assertEqual(self.m["asset"], "USDC")

    def test_supply_rate_preserved(self):
        self.assertAlmostEqual(self.m["supply_rate"], 3.0)

    def test_borrow_rate_preserved(self):
        self.assertAlmostEqual(self.m["borrow_rate"], 5.0)

    def test_spread_pct_computed(self):
        self.assertAlmostEqual(self.m["spread_pct"], 2.0)

    def test_utilization_rate_preserved(self):
        self.assertAlmostEqual(self.m["utilization_rate"], 0.8)

    def test_utilization_gap_computed(self):
        # optimal=0.8, util=0.8 → gap=0
        self.assertAlmostEqual(self.m["utilization_gap"], 0.0)

    def test_capital_efficiency_computed(self):
        # util=0.8, supply=3.0, borrow=5.0 → 0.8*(3/5)=0.48
        self.assertAlmostEqual(self.m["capital_efficiency"], 0.48, places=5)

    def test_efficiency_score_is_int(self):
        self.assertIsInstance(self.m["efficiency_score"], int)

    def test_grade_present(self):
        self.assertIn(self.m["grade"], ("A", "B", "C", "D", "F"))


# ===========================================================================
# TestSpreadScore
# ===========================================================================

class TestSpreadScore(unittest.TestCase):

    def test_zero_spread_gives_max_spread_score(self):
        # spread=0, optimal util, big supply → only size/util vary
        m = _market(supply_rate=5.0, borrow_rate=5.0, utilization_rate=0.8,
                    total_supply_usd=1_000_000_000)
        r = analyze([m])
        scored = r["markets"][0]
        # spread_score = 40*(1-0/20)=40; util_score=40; size ~20 → ~100
        self.assertGreaterEqual(scored["efficiency_score"], 95)

    def test_large_spread_reduces_score(self):
        m_tight = _market(supply_rate=4.0, borrow_rate=4.5, utilization_rate=0.8,
                          total_supply_usd=1_000_000)
        m_wide  = _market(supply_rate=1.0, borrow_rate=15.0, utilization_rate=0.8,
                          total_supply_usd=1_000_000)
        r1 = analyze([m_tight])
        r2 = analyze([m_wide])
        self.assertGreater(r1["markets"][0]["efficiency_score"],
                           r2["markets"][0]["efficiency_score"])

    def test_spread_20_gives_zero_spread_score(self):
        # spread = 20% → spread_score = 40*(1-20/20)=0
        m = _market(supply_rate=0.0, borrow_rate=20.0, utilization_rate=0.8,
                    total_supply_usd=1_000_000_000)
        r = analyze([m])
        # Should still get utilization_score + size_score, but no spread_score
        scored = r["markets"][0]
        # util=0.8=optimal → util_score=40; size=big → ~20; spread=0 → total≈60
        self.assertLessEqual(scored["efficiency_score"], 65)

    def test_negative_spread_pct_field(self):
        # supply > borrow (unusual)
        m = _market(supply_rate=6.0, borrow_rate=4.0)
        r = analyze([m])
        self.assertLess(r["markets"][0]["spread_pct"], 0)

    def test_spread_score_never_negative_in_total(self):
        m = _market(supply_rate=0.0, borrow_rate=50.0)
        r = analyze([m])
        self.assertGreaterEqual(r["markets"][0]["efficiency_score"], 0)

    def test_spread_exact_10_gives_half_spread_score(self):
        # spread_score = 40*(1-10/20)=20
        m = _market(supply_rate=0.0, borrow_rate=10.0, utilization_rate=0.8,
                    total_supply_usd=0)
        r = analyze([m])
        scored = r["markets"][0]
        # spread=20; util=40; size=0 → total=60
        self.assertAlmostEqual(scored["efficiency_score"], 60)

    def test_spread_pct_is_borrow_minus_supply(self):
        m = _market(supply_rate=3.5, borrow_rate=7.5)
        r = analyze([m])
        self.assertAlmostEqual(r["markets"][0]["spread_pct"], 4.0)

    def test_two_markets_different_spread(self):
        m1 = _market("A", "X", supply_rate=3.0, borrow_rate=4.0)
        m2 = _market("B", "X", supply_rate=1.0, borrow_rate=10.0)
        r = analyze([m1, m2])
        self.assertGreater(r["markets"][0]["efficiency_score"],
                           r["markets"][1]["efficiency_score"])

    def test_spread_pct_zero_zero_rates(self):
        m = _market(supply_rate=0.0, borrow_rate=0.0)
        r = analyze([m])
        self.assertAlmostEqual(r["markets"][0]["spread_pct"], 0.0)


# ===========================================================================
# TestUtilizationScore
# ===========================================================================

class TestUtilizationScore(unittest.TestCase):

    def test_optimal_util_max_utilization_score(self):
        m = _market(utilization_rate=0.80, total_supply_usd=0,
                    supply_rate=0.0, borrow_rate=0.0)
        r = analyze([m], config={"optimal_utilization": 0.80})
        # util_score = 40*(1-0/0.5)=40; spread_score=40; size=0 → 80
        self.assertAlmostEqual(r["markets"][0]["efficiency_score"], 80)

    def test_util_50pct_below_optimal_reduces_score(self):
        m_at_opt = _market(utilization_rate=0.80, total_supply_usd=0,
                           supply_rate=0.0, borrow_rate=0.0)
        m_off    = _market(utilization_rate=0.30, total_supply_usd=0,
                           supply_rate=0.0, borrow_rate=0.0)
        r1 = analyze([m_at_opt])
        r2 = analyze([m_off])
        self.assertGreater(r1["markets"][0]["efficiency_score"],
                           r2["markets"][0]["efficiency_score"])

    def test_utilization_gap_is_abs_distance(self):
        m = _market(utilization_rate=0.70)
        r = analyze([m], config={"optimal_utilization": 0.80})
        self.assertAlmostEqual(r["markets"][0]["utilization_gap"], 0.10, places=5)

    def test_custom_optimal_utilization_used(self):
        m = _market(utilization_rate=0.60)
        r_def = analyze([m])                                  # default optimal=0.80
        r_cus = analyze([m], config={"optimal_utilization": 0.60})  # optimal=0.60
        # Gap with default=0.20, gap with custom=0.0 → custom should score higher
        self.assertGreater(r_cus["markets"][0]["efficiency_score"],
                           r_def["markets"][0]["efficiency_score"])

    def test_utilization_over_1_handled(self):
        m = _market(utilization_rate=1.10)
        r = analyze([m])
        scored = r["markets"][0]
        self.assertGreaterEqual(scored["efficiency_score"], 0)
        self.assertLessEqual(scored["efficiency_score"], 100)

    def test_zero_utilization_low_score(self):
        m = _market(utilization_rate=0.0, total_supply_usd=0,
                    supply_rate=0.0, borrow_rate=0.0)
        r = analyze([m])
        # util_gap=0.8, util_score=40*(1-0.8/0.5)=40*(1-1.6)=max(0,...)=0
        # spread_score=40; size=0 → total=40
        self.assertAlmostEqual(r["markets"][0]["efficiency_score"], 40)

    def test_capital_efficiency_uses_borrow_floor(self):
        # borrow_rate=0 → should use floor 0.01
        m = _market(supply_rate=3.0, borrow_rate=0.0, utilization_rate=0.5)
        r = analyze([m])
        ce = r["markets"][0]["capital_efficiency"]
        expected = 0.5 * (3.0 / 0.01)
        self.assertAlmostEqual(ce, expected, places=5)

    def test_utilization_gap_symmetric(self):
        m1 = _market(utilization_rate=0.60)  # gap=0.20
        m2 = _market(utilization_rate=1.00)  # gap=0.20
        r1 = analyze([m1])
        r2 = analyze([m2])
        self.assertAlmostEqual(
            r1["markets"][0]["utilization_gap"],
            r2["markets"][0]["utilization_gap"],
            places=5,
        )


# ===========================================================================
# TestSizeScore
# ===========================================================================

class TestSizeScore(unittest.TestCase):

    def test_zero_supply_score_zero(self):
        self.assertAlmostEqual(_size_score(0), 0.0)

    def test_billion_supply_max_score(self):
        self.assertAlmostEqual(_size_score(1_000_000_000), 20.0, places=3)

    def test_negative_supply_score_zero(self):
        self.assertAlmostEqual(_size_score(-1), 0.0)

    def test_larger_supply_higher_score(self):
        self.assertGreater(_size_score(100_000_000), _size_score(1_000_000))

    def test_size_score_capped_at_20(self):
        self.assertLessEqual(_size_score(1e12), 20.0)

    def test_size_score_small_supply(self):
        # $1 supply → should be well below 20
        self.assertLess(_size_score(1.0), 5.0)

    def test_size_score_in_efficiency(self):
        big   = _market(total_supply_usd=1_000_000_000, supply_rate=0.0,
                        borrow_rate=0.0, utilization_rate=0.8)
        small = _market(total_supply_usd=1_000, supply_rate=0.0,
                        borrow_rate=0.0, utilization_rate=0.8)
        r1 = analyze([big])
        r2 = analyze([small])
        self.assertGreater(r1["markets"][0]["efficiency_score"],
                           r2["markets"][0]["efficiency_score"])


# ===========================================================================
# TestGrade
# ===========================================================================

class TestGrade(unittest.TestCase):

    def test_grade_A_at_80(self):
        self.assertEqual(_grade(80), "A")

    def test_grade_A_at_100(self):
        self.assertEqual(_grade(100), "A")

    def test_grade_B_at_65(self):
        self.assertEqual(_grade(65), "B")

    def test_grade_B_at_79(self):
        self.assertEqual(_grade(79), "B")

    def test_grade_C_at_50(self):
        self.assertEqual(_grade(50), "C")

    def test_grade_C_at_64(self):
        self.assertEqual(_grade(64), "C")

    def test_grade_D_at_35(self):
        self.assertEqual(_grade(35), "D")

    def test_grade_F_at_34(self):
        self.assertEqual(_grade(34), "F")

    def test_grade_F_at_0(self):
        self.assertEqual(_grade(0), "F")

    def test_grade_D_at_49(self):
        self.assertEqual(_grade(49), "D")


# ===========================================================================
# TestRankings
# ===========================================================================

class TestRankings(unittest.TestCase):

    def test_rankings_keys_present(self):
        r = analyze(_simple_markets())
        self.assertIn("tightest_spread", r["rankings"])
        self.assertIn("highest_utilization", r["rankings"])
        self.assertIn("most_efficient", r["rankings"])

    def test_tightest_spread_format(self):
        m1 = _market("Aave",     "USDC", supply_rate=3.0, borrow_rate=3.5)  # spread=0.5
        m2 = _market("Compound", "USDC", supply_rate=2.0, borrow_rate=5.0)  # spread=3.0
        r = analyze([m1, m2])
        self.assertEqual(r["rankings"]["tightest_spread"], "Aave:USDC")

    def test_highest_utilization_format(self):
        m1 = _market("A", "X", utilization_rate=0.70)
        m2 = _market("B", "Y", utilization_rate=0.95)
        r = analyze([m1, m2])
        self.assertEqual(r["rankings"]["highest_utilization"], "B:Y")

    def test_most_efficient_format(self):
        # m1 has tighter spread and more supply → should win
        m1 = _market("Best",  "U", supply_rate=4.0, borrow_rate=4.1, utilization_rate=0.80,
                     total_supply_usd=1_000_000_000)
        m2 = _market("Worse", "U", supply_rate=1.0, borrow_rate=15.0, utilization_rate=0.30,
                     total_supply_usd=1_000)
        r = analyze([m1, m2])
        self.assertEqual(r["rankings"]["most_efficient"], "Best:U")

    def test_single_market_all_rankings_same(self):
        r = analyze([_market("Solo", "X")])
        self.assertEqual(r["rankings"]["tightest_spread"], "Solo:X")
        self.assertEqual(r["rankings"]["highest_utilization"], "Solo:X")
        self.assertEqual(r["rankings"]["most_efficient"], "Solo:X")

    def test_empty_rankings_all_empty_string(self):
        r = analyze([])
        for k, v in r["rankings"].items():
            self.assertEqual(v, "")

    def test_ranking_key_format_colon(self):
        r = analyze([_market("MyProto", "ETH")])
        self.assertIn(":", r["rankings"]["tightest_spread"])

    def test_most_efficient_correlates_with_score(self):
        markets = _simple_markets()
        r = analyze(markets)
        best_key = r["rankings"]["most_efficient"]
        max_score = max(m["efficiency_score"] for m in r["markets"])
        winner = next(m for m in r["markets"]
                      if f"{m['protocol']}:{m['asset']}" == best_key)
        self.assertEqual(winner["efficiency_score"], max_score)


# ===========================================================================
# TestMarketSummary
# ===========================================================================

class TestMarketSummary(unittest.TestCase):

    def test_summary_keys_present(self):
        r = analyze(_simple_markets())
        s = r["market_summary"]
        for k in ("avg_spread_pct", "avg_utilization_rate", "avg_efficiency_score",
                  "total_supply_usd", "total_borrow_usd"):
            self.assertIn(k, s)

    def test_avg_spread_correct(self):
        m1 = _market("A", "X", supply_rate=2.0, borrow_rate=4.0)  # spread=2
        m2 = _market("B", "Y", supply_rate=3.0, borrow_rate=7.0)  # spread=4
        r = analyze([m1, m2])
        self.assertAlmostEqual(r["market_summary"]["avg_spread_pct"], 3.0)

    def test_avg_utilization_correct(self):
        m1 = _market("A", "X", utilization_rate=0.60)
        m2 = _market("B", "Y", utilization_rate=0.80)
        r = analyze([m1, m2])
        self.assertAlmostEqual(r["market_summary"]["avg_utilization_rate"], 0.70)

    def test_total_supply_aggregated(self):
        m1 = _market("A", "X", total_supply_usd=100_000)
        m2 = _market("B", "Y", total_supply_usd=200_000)
        r = analyze([m1, m2])
        self.assertAlmostEqual(r["market_summary"]["total_supply_usd"], 300_000)

    def test_total_borrow_aggregated(self):
        m1 = _market("A", "X", total_borrow_usd=50_000)
        m2 = _market("B", "Y", total_borrow_usd=75_000)
        r = analyze([m1, m2])
        self.assertAlmostEqual(r["market_summary"]["total_borrow_usd"], 125_000)

    def test_avg_efficiency_score_correct(self):
        m1 = _market("A", "X", supply_rate=0.0, borrow_rate=0.0,
                     utilization_rate=0.8, total_supply_usd=0)
        r = analyze([m1])
        # score = 40+40+0 = 80
        self.assertAlmostEqual(r["market_summary"]["avg_efficiency_score"], 80.0, places=0)

    def test_single_market_summary(self):
        m = _market("S", "T", total_supply_usd=1_000_000, total_borrow_usd=800_000)
        r = analyze([m])
        self.assertAlmostEqual(r["market_summary"]["total_supply_usd"], 1_000_000)
        self.assertAlmostEqual(r["market_summary"]["total_borrow_usd"], 800_000)


# ===========================================================================
# TestLogResult
# ===========================================================================

class TestLogResult(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "lending_test_log.json"

    def test_log_creates_file(self):
        log_result(analyze(_simple_markets()), self.data_file)
        self.assertTrue(self.data_file.exists())

    def test_log_is_list(self):
        log_result(analyze(_simple_markets()), self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertIsInstance(data, list)

    def test_log_single_entry(self):
        log_result(analyze(_simple_markets()), self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), 1)

    def test_log_two_entries(self):
        log_result(analyze(_simple_markets()), self.data_file)
        log_result(analyze(_simple_markets()), self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap_100(self):
        for _ in range(110):
            log_result(analyze(_simple_markets()), self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            r = analyze([_market(f"P{i}", "X")])
            log_result(r, self.data_file)
        data = json.loads(self.data_file.read_text())
        # Last entry should contain protocol P104
        last_markets = data[-1]["markets"]
        self.assertEqual(last_markets[0]["protocol"], "P104")

    def test_no_tmp_file_left_after_write(self):
        log_result(analyze(_simple_markets()), self.data_file)
        self.assertFalse(self.data_file.with_suffix(".tmp").exists())


# ===========================================================================
# TestLoadLog
# ===========================================================================

class TestLoadLog(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "lending_test_log.json"

    def test_load_missing_returns_empty(self):
        self.assertEqual(load_log(self.data_file), [])

    def test_load_empty_list(self):
        self.data_file.write_text("[]")
        self.assertEqual(load_log(self.data_file), [])

    def test_load_corrupt_returns_empty(self):
        self.data_file.write_text("{bad json{{")
        self.assertEqual(load_log(self.data_file), [])

    def test_load_after_log(self):
        log_result(analyze(_simple_markets()), self.data_file)
        loaded = load_log(self.data_file)
        self.assertEqual(len(loaded), 1)

    def test_load_returns_list(self):
        log_result(analyze(_simple_markets()), self.data_file)
        loaded = load_log(self.data_file)
        self.assertIsInstance(loaded, list)


if __name__ == "__main__":
    unittest.main()
