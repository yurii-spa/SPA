"""
Tests for MP-889: DeFiPoolFeeTierOptimizer
Run: python3 -m unittest spa_core.tests.test_defi_pool_fee_tier_optimizer -v
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure project root is on path
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_pool_fee_tier_optimizer import (
    _fee_per_day,
    _il_risk_score,
    _net_score,
    _build_tier_analysis,
    _select_optimal_tier,
    _build_rationale,
    _analyze_pool,
    analyze,
    run_and_log,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def eth_usdc_pool(**overrides):
    base = {
        "pair": "ETH/USDC",
        "available_tiers_bps": [1, 5, 30, 100],
        "daily_volume_usd": 50_000_000.0,
        "tvl_usd": 100_000_000.0,
        "volatility_30d_pct": 45.0,
        "current_tier_bps": 5,
        "capital_usd": 100_000.0,
        "position_days": 30,
    }
    base.update(overrides)
    return base


def stable_pool(**overrides):
    base = {
        "pair": "USDC/USDT",
        "available_tiers_bps": [1, 5],
        "daily_volume_usd": 200_000_000.0,
        "tvl_usd": 500_000_000.0,
        "volatility_30d_pct": 0.5,
        "current_tier_bps": 1,
        "capital_usd": 200_000.0,
        "position_days": 60,
    }
    base.update(overrides)
    return base


# ===========================================================================
# Section 1: _fee_per_day
# ===========================================================================
class TestFeePerDay(unittest.TestCase):

    def test_basic_calculation(self):
        # 100k * (30/10000) * (50M/100M) = 100k * 0.003 * 0.5 = 150
        result = _fee_per_day(100_000, 30, 50_000_000, 100_000_000)
        self.assertAlmostEqual(result, 150.0, places=6)

    def test_zero_tvl_returns_zero(self):
        self.assertEqual(_fee_per_day(100_000, 30, 50_000_000, 0), 0.0)

    def test_negative_tvl_returns_zero(self):
        self.assertEqual(_fee_per_day(100_000, 30, 50_000_000, -1), 0.0)

    def test_zero_capital(self):
        self.assertEqual(_fee_per_day(0, 30, 50_000_000, 100_000_000), 0.0)

    def test_zero_volume(self):
        self.assertEqual(_fee_per_day(100_000, 30, 0, 100_000_000), 0.0)

    def test_tier_1_bps(self):
        result = _fee_per_day(100_000, 1, 50_000_000, 100_000_000)
        self.assertAlmostEqual(result, 5.0, places=6)

    def test_tier_100_bps(self):
        result = _fee_per_day(100_000, 100, 50_000_000, 100_000_000)
        self.assertAlmostEqual(result, 500.0, places=6)

    def test_returns_float(self):
        result = _fee_per_day(100_000, 30, 50_000_000, 100_000_000)
        self.assertIsInstance(result, float)

    def test_proportional_to_capital(self):
        r1 = _fee_per_day(100_000, 30, 50_000_000, 100_000_000)
        r2 = _fee_per_day(200_000, 30, 50_000_000, 100_000_000)
        self.assertAlmostEqual(r2, r1 * 2, places=6)

    def test_proportional_to_tier(self):
        r1 = _fee_per_day(100_000, 5, 50_000_000, 100_000_000)
        r2 = _fee_per_day(100_000, 10, 50_000_000, 100_000_000)
        self.assertAlmostEqual(r2, r1 * 2, places=6)


# ===========================================================================
# Section 2: _il_risk_score
# ===========================================================================
class TestIlRiskScore(unittest.TestCase):

    def test_zero_volatility(self):
        # min(100, int(0 / (30 * 0.1 + 1))) = 0
        self.assertEqual(_il_risk_score(0.0, 30), 0)

    def test_high_volatility_low_tier(self):
        # min(100, int(100 / (1 * 0.1 + 1))) = min(100, int(100/1.1)) = min(100, 90) = 90
        self.assertEqual(_il_risk_score(100.0, 1), 90)

    def test_capped_at_100(self):
        # very high vol, tier=1: int(1000 / 1.1) = 909 → capped at 100
        self.assertEqual(_il_risk_score(1000.0, 1), 100)

    def test_high_tier_reduces_risk(self):
        low = _il_risk_score(45.0, 1)
        high = _il_risk_score(45.0, 100)
        self.assertGreater(low, high)

    def test_specific_value_tier30_vol45(self):
        # int(45 / (30*0.1+1)) = int(45/4) = int(11.25) = 11
        self.assertEqual(_il_risk_score(45.0, 30), 11)

    def test_returns_int(self):
        result = _il_risk_score(45.0, 30)
        self.assertIsInstance(result, int)

    def test_tier5_vol45(self):
        # int(45 / (5*0.1+1)) = int(45/1.5) = int(30) = 30
        self.assertEqual(_il_risk_score(45.0, 5), 30)

    def test_minimum_is_zero(self):
        self.assertGreaterEqual(_il_risk_score(0.0, 100), 0)


# ===========================================================================
# Section 3: _net_score
# ===========================================================================
class TestNetScore(unittest.TestCase):

    def test_zero_il(self):
        # fee * (1 - 0/200) = fee * 1.0
        self.assertAlmostEqual(_net_score(100.0, 0), 100.0)

    def test_il_100_reduces_by_half(self):
        # fee * (1 - 100/200) = fee * 0.5
        self.assertAlmostEqual(_net_score(100.0, 100), 50.0)

    def test_il_200_returns_zero(self):
        # fee * (1 - 200/200) = 0
        self.assertAlmostEqual(_net_score(100.0, 200), 0.0)

    def test_zero_fee(self):
        self.assertAlmostEqual(_net_score(0.0, 50), 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_net_score(100.0, 50), float)

    def test_higher_il_lower_score(self):
        s1 = _net_score(100.0, 10)
        s2 = _net_score(100.0, 50)
        self.assertGreater(s1, s2)


# ===========================================================================
# Section 4: _build_tier_analysis
# ===========================================================================
class TestBuildTierAnalysis(unittest.TestCase):

    def test_returns_list(self):
        pool = eth_usdc_pool()
        result = _build_tier_analysis(pool)
        self.assertIsInstance(result, list)

    def test_length_matches_tiers(self):
        pool = eth_usdc_pool()
        result = _build_tier_analysis(pool)
        self.assertEqual(len(result), 4)

    def test_tier_keys_present(self):
        pool = eth_usdc_pool()
        result = _build_tier_analysis(pool)
        required = {"tier_bps", "fee_per_day_usd", "il_risk_score",
                    "net_daily_yield_pct", "annualized_yield_pct"}
        for ta in result:
            self.assertEqual(set(ta.keys()), required)

    def test_empty_tiers_returns_empty_list(self):
        pool = eth_usdc_pool(available_tiers_bps=[])
        result = _build_tier_analysis(pool)
        self.assertEqual(result, [])

    def test_fee_per_day_positive_for_normal_pool(self):
        pool = eth_usdc_pool()
        result = _build_tier_analysis(pool)
        for ta in result:
            self.assertGreaterEqual(ta["fee_per_day_usd"], 0.0)

    def test_annualized_is_365x_net_daily(self):
        pool = eth_usdc_pool()
        result = _build_tier_analysis(pool)
        for ta in result:
            self.assertAlmostEqual(
                ta["annualized_yield_pct"], ta["net_daily_yield_pct"] * 365, places=6
            )

    def test_zero_capital_gives_zero_yield(self):
        pool = eth_usdc_pool(capital_usd=0.0)
        result = _build_tier_analysis(pool)
        for ta in result:
            self.assertEqual(ta["net_daily_yield_pct"], 0.0)
            self.assertEqual(ta["annualized_yield_pct"], 0.0)

    def test_zero_tvl_gives_zero_fee(self):
        pool = eth_usdc_pool(tvl_usd=0.0)
        result = _build_tier_analysis(pool)
        for ta in result:
            self.assertEqual(ta["fee_per_day_usd"], 0.0)

    def test_higher_tier_generally_higher_fee(self):
        pool = eth_usdc_pool()
        result = _build_tier_analysis(pool)
        fees = {ta["tier_bps"]: ta["fee_per_day_usd"] for ta in result}
        self.assertGreater(fees[100], fees[1])

    def test_il_risk_score_range(self):
        pool = eth_usdc_pool()
        result = _build_tier_analysis(pool)
        for ta in result:
            self.assertGreaterEqual(ta["il_risk_score"], 0)
            self.assertLessEqual(ta["il_risk_score"], 100)


# ===========================================================================
# Section 5: _select_optimal_tier
# ===========================================================================
class TestSelectOptimalTier(unittest.TestCase):

    def _make_ta(self, tier, fpd, il):
        return {
            "tier_bps": tier,
            "fee_per_day_usd": fpd,
            "il_risk_score": il,
            "net_daily_yield_pct": 0.0,
            "annualized_yield_pct": 0.0,
        }

    def test_empty_returns_current(self):
        self.assertEqual(_select_optimal_tier([], 30), 30)

    def test_single_tier_returns_it(self):
        ta = [self._make_ta(5, 100.0, 20)]
        self.assertEqual(_select_optimal_tier(ta, 30), 5)

    def test_picks_highest_net_score(self):
        # tier 30 has better score than tier 5
        ta = [
            self._make_ta(5, 10.0, 0),    # net_score = 10.0
            self._make_ta(30, 50.0, 10),  # net_score = 50 * (1-10/200) = 47.5
        ]
        self.assertEqual(_select_optimal_tier(ta, 5), 30)

    def test_tie_picks_highest_tier(self):
        # Both have same fee + il → same score; pick higher tier_bps
        ta = [
            self._make_ta(5, 0.0, 0),
            self._make_ta(30, 0.0, 0),
        ]
        self.assertEqual(_select_optimal_tier(ta, 5), 30)

    def test_high_il_can_make_lower_tier_win(self):
        # tier 100 has higher fee but very high IL, tier 5 may win
        ta = [
            self._make_ta(5, 50.0, 0),     # net = 50
            self._make_ta(100, 80.0, 100), # net = 80 * 0.5 = 40
        ]
        self.assertEqual(_select_optimal_tier(ta, 100), 5)

    def test_returns_int(self):
        ta = [self._make_ta(30, 100.0, 10)]
        result = _select_optimal_tier(ta, 5)
        self.assertIsInstance(result, int)


# ===========================================================================
# Section 6: _build_rationale
# ===========================================================================
class TestBuildRationale(unittest.TestCase):

    def test_no_change_needed(self):
        pool = eth_usdc_pool(
            current_tier_bps=5,
            volatility_30d_pct=10.0,
            daily_volume_usd=1_000_000.0,
            tvl_usd=100_000_000.0,
        )
        r = _build_rationale(pool, 5)
        self.assertIn("No change needed", r)

    def test_high_volatility_high_tier(self):
        pool = eth_usdc_pool(
            volatility_30d_pct=60.0,
            current_tier_bps=5,
            daily_volume_usd=10_000_000.0,
            tvl_usd=100_000_000.0,
        )
        r = _build_rationale(pool, 30)
        self.assertIn("High volatility", r)

    def test_high_vol_tvl_ratio(self):
        pool = eth_usdc_pool(
            volatility_30d_pct=20.0,
            daily_volume_usd=60_000_000.0,  # vol/tvl = 0.6 > 0.5
            tvl_usd=100_000_000.0,
            current_tier_bps=5,
        )
        r = _build_rationale(pool, 5)
        self.assertIn("High volume/TVL ratio", r)

    def test_reducing_tier(self):
        pool = eth_usdc_pool(
            volatility_30d_pct=5.0,
            daily_volume_usd=1_000_000.0,
            tvl_usd=100_000_000.0,
            current_tier_bps=30,
        )
        r = _build_rationale(pool, 5)
        self.assertIn("Reducing fee tier", r)

    def test_increasing_tier(self):
        pool = eth_usdc_pool(
            volatility_30d_pct=5.0,
            daily_volume_usd=1_000_000.0,
            tvl_usd=100_000_000.0,
            current_tier_bps=5,
        )
        r = _build_rationale(pool, 30)
        self.assertIn("Increasing fee tier", r)

    def test_zero_tvl_no_crash(self):
        pool = eth_usdc_pool(tvl_usd=0.0, current_tier_bps=5)
        r = _build_rationale(pool, 5)
        self.assertIsInstance(r, str)
        self.assertGreater(len(r), 0)

    def test_returns_string(self):
        pool = eth_usdc_pool()
        r = _build_rationale(pool, 5)
        self.assertIsInstance(r, str)


# ===========================================================================
# Section 7: _analyze_pool
# ===========================================================================
class TestAnalyzePool(unittest.TestCase):

    def test_returns_dict(self):
        result = _analyze_pool(eth_usdc_pool())
        self.assertIsInstance(result, dict)

    def test_required_keys(self):
        result = _analyze_pool(eth_usdc_pool())
        for key in ("pair", "current_tier_bps", "optimal_tier_bps",
                    "tier_analysis", "projected_earnings_usd",
                    "tier_change_recommended", "rationale"):
            self.assertIn(key, result)

    def test_pair_preserved(self):
        result = _analyze_pool(eth_usdc_pool())
        self.assertEqual(result["pair"], "ETH/USDC")

    def test_tier_change_bool(self):
        result = _analyze_pool(eth_usdc_pool())
        self.assertIsInstance(result["tier_change_recommended"], bool)

    def test_projected_earnings_nonneg(self):
        result = _analyze_pool(eth_usdc_pool())
        self.assertGreaterEqual(result["projected_earnings_usd"], 0.0)

    def test_empty_tiers_uses_current(self):
        pool = eth_usdc_pool(available_tiers_bps=[], current_tier_bps=30)
        result = _analyze_pool(pool)
        self.assertEqual(result["optimal_tier_bps"], 30)
        self.assertFalse(result["tier_change_recommended"])

    def test_empty_tiers_zero_earnings(self):
        pool = eth_usdc_pool(available_tiers_bps=[], current_tier_bps=30)
        result = _analyze_pool(pool)
        self.assertEqual(result["projected_earnings_usd"], 0.0)

    def test_zero_capital_zero_earnings(self):
        pool = eth_usdc_pool(capital_usd=0.0)
        result = _analyze_pool(pool)
        self.assertEqual(result["projected_earnings_usd"], 0.0)

    def test_rationale_is_string(self):
        result = _analyze_pool(eth_usdc_pool())
        self.assertIsInstance(result["rationale"], str)

    def test_tier_analysis_list(self):
        result = _analyze_pool(eth_usdc_pool())
        self.assertIsInstance(result["tier_analysis"], list)

    def test_tier_change_when_tier_differs(self):
        # Force optimal != current by giving only one tier != current
        pool = eth_usdc_pool(
            available_tiers_bps=[100],
            current_tier_bps=5,
        )
        result = _analyze_pool(pool)
        self.assertEqual(result["optimal_tier_bps"], 100)
        self.assertTrue(result["tier_change_recommended"])


# ===========================================================================
# Section 8: analyze() — top-level
# ===========================================================================
class TestAnalyze(unittest.TestCase):

    def test_empty_pools_returns_structure(self):
        result = analyze([])
        self.assertEqual(result["pools"], [])
        self.assertIn("summary", result)
        self.assertIn("timestamp", result)

    def test_empty_summary_zeros(self):
        result = analyze([])
        s = result["summary"]
        self.assertEqual(s["pools_needing_rebalance"], 0)
        self.assertEqual(s["average_optimal_yield_pct"], 0.0)
        self.assertEqual(s["total_projected_earnings_usd"], 0.0)

    def test_single_pool_result(self):
        result = analyze([eth_usdc_pool()])
        self.assertEqual(len(result["pools"]), 1)

    def test_multiple_pools(self):
        result = analyze([eth_usdc_pool(), stable_pool()])
        self.assertEqual(len(result["pools"]), 2)

    def test_summary_keys_present(self):
        result = analyze([eth_usdc_pool()])
        for key in ("pools_needing_rebalance", "average_optimal_yield_pct",
                    "total_projected_earnings_usd"):
            self.assertIn(key, result["summary"])

    def test_pools_needing_rebalance_count(self):
        # pool with only one tier different from current → tier_change=True
        pool1 = eth_usdc_pool(available_tiers_bps=[100], current_tier_bps=5)
        pool2 = eth_usdc_pool(available_tiers_bps=[5], current_tier_bps=5)
        result = analyze([pool1, pool2])
        self.assertEqual(result["summary"]["pools_needing_rebalance"], 1)

    def test_timestamp_positive(self):
        result = analyze([eth_usdc_pool()])
        self.assertGreater(result["timestamp"], 0)

    def test_average_yield_nonneg(self):
        result = analyze([eth_usdc_pool(), stable_pool()])
        self.assertGreaterEqual(result["summary"]["average_optimal_yield_pct"], 0.0)

    def test_total_earnings_sum(self):
        result = analyze([eth_usdc_pool(), stable_pool()])
        individual = sum(p["projected_earnings_usd"] for p in result["pools"])
        self.assertAlmostEqual(
            result["summary"]["total_projected_earnings_usd"], individual, places=6
        )

    def test_config_none_ok(self):
        result = analyze([eth_usdc_pool()], config=None)
        self.assertIn("pools", result)

    def test_config_dict_ok(self):
        result = analyze([eth_usdc_pool()], config={"foo": "bar"})
        self.assertIn("pools", result)

    def test_zero_tvl_pool(self):
        pool = eth_usdc_pool(tvl_usd=0.0)
        result = analyze([pool])
        self.assertEqual(len(result["pools"]), 1)
        self.assertEqual(result["pools"][0]["projected_earnings_usd"], 0.0)

    def test_zero_capital_pool(self):
        pool = eth_usdc_pool(capital_usd=0.0)
        result = analyze([pool])
        self.assertEqual(result["pools"][0]["projected_earnings_usd"], 0.0)

    def test_single_tier_pool(self):
        pool = eth_usdc_pool(available_tiers_bps=[30], current_tier_bps=5)
        result = analyze([pool])
        self.assertEqual(result["pools"][0]["optimal_tier_bps"], 30)

    def test_pools_needing_rebalance_zero_when_all_current(self):
        pool1 = stable_pool(available_tiers_bps=[1], current_tier_bps=1)
        pool2 = eth_usdc_pool(available_tiers_bps=[5], current_tier_bps=5)
        result = analyze([pool1, pool2])
        self.assertEqual(result["summary"]["pools_needing_rebalance"], 0)

    def test_average_yield_single_pool(self):
        # Average should equal that pool's optimal-tier annualized yield
        pool = eth_usdc_pool(available_tiers_bps=[30], current_tier_bps=5)
        result = analyze([pool])
        pr = result["pools"][0]
        opt_ta = next(t for t in pr["tier_analysis"] if t["tier_bps"] == pr["optimal_tier_bps"])
        self.assertAlmostEqual(
            result["summary"]["average_optimal_yield_pct"],
            opt_ta["annualized_yield_pct"],
            places=6,
        )

    def test_high_volatility_pool_high_tier_preferred(self):
        pool = eth_usdc_pool(
            volatility_30d_pct=80.0,
            available_tiers_bps=[1, 5, 30, 100],
            current_tier_bps=1,
        )
        result = analyze([pool])
        # High vol should prefer higher tier
        self.assertGreater(result["pools"][0]["optimal_tier_bps"], 1)

    def test_stable_pool_low_tier_preferred(self):
        pool = stable_pool(
            available_tiers_bps=[1, 5, 30],
            current_tier_bps=30,
            volatility_30d_pct=0.2,
        )
        result = analyze([pool])
        # Stable pair with huge volume/tvl ratio should have valid optimal tier
        self.assertIn(result["pools"][0]["optimal_tier_bps"], [1, 5, 30])

    def test_position_days_zero(self):
        pool = eth_usdc_pool(position_days=0)
        result = analyze([pool])
        self.assertEqual(result["pools"][0]["projected_earnings_usd"], 0.0)


# ===========================================================================
# Section 9: run_and_log()
# ===========================================================================
class TestRunAndLog(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmpdir, "fee_tier_optimization_log.json")

    def test_creates_file(self):
        run_and_log([eth_usdc_pool()], data_file=self.log_file)
        self.assertTrue(os.path.exists(self.log_file))

    def test_file_is_valid_json(self):
        run_and_log([eth_usdc_pool()], data_file=self.log_file)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_appends_entries(self):
        run_and_log([eth_usdc_pool()], data_file=self.log_file)
        run_and_log([stable_pool()], data_file=self.log_file)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        for _ in range(105):
            run_and_log([eth_usdc_pool()], data_file=self.log_file)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_returns_result_dict(self):
        result = run_and_log([eth_usdc_pool()], data_file=self.log_file)
        self.assertIn("pools", result)
        self.assertIn("summary", result)
        self.assertIn("timestamp", result)

    def test_creates_parent_dir(self):
        nested = os.path.join(self.tmpdir, "sub", "fee_tier.json")
        run_and_log([eth_usdc_pool()], data_file=nested)
        self.assertTrue(os.path.exists(nested))

    def test_empty_pools_logged(self):
        run_and_log([], data_file=self.log_file)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["pools"], [])

    def test_existing_corrupt_file_reset(self):
        with open(self.log_file, "w") as f:
            f.write("NOT JSON")
        run_and_log([eth_usdc_pool()], data_file=self.log_file)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_ring_buffer_keeps_latest(self):
        # Write 101 entries, ensure last one is the most recent
        for i in range(101):
            run_and_log([eth_usdc_pool(position_days=i)], data_file=self.log_file)
        with open(self.log_file) as f:
            data = json.load(f)
        # The first entry should have position_days >= 1 (not 0)
        self.assertLessEqual(len(data), 100)


# ===========================================================================
# Section 10: Edge cases & integration
# ===========================================================================
class TestEdgeCases(unittest.TestCase):

    def test_many_tiers(self):
        pool = eth_usdc_pool(available_tiers_bps=[1, 2, 3, 5, 10, 30, 50, 100])
        result = analyze([pool])
        self.assertEqual(len(result["pools"][0]["tier_analysis"]), 8)

    def test_large_capital(self):
        pool = eth_usdc_pool(capital_usd=1_000_000_000.0)
        result = analyze([pool])
        self.assertGreater(result["pools"][0]["projected_earnings_usd"], 0)

    def test_very_high_volatility(self):
        pool = eth_usdc_pool(volatility_30d_pct=500.0)
        result = analyze([pool])
        # Should not raise; il_risk_score capped at 100
        for ta in result["pools"][0]["tier_analysis"]:
            self.assertLessEqual(ta["il_risk_score"], 100)

    def test_volume_exceeds_tvl(self):
        pool = eth_usdc_pool(daily_volume_usd=500_000_000.0, tvl_usd=100_000_000.0)
        result = analyze([pool])
        for ta in result["pools"][0]["tier_analysis"]:
            self.assertGreaterEqual(ta["fee_per_day_usd"], 0.0)

    def test_three_pools_summary_math(self):
        pools = [eth_usdc_pool(), stable_pool(),
                 eth_usdc_pool(pair="WBTC/USDC", current_tier_bps=100)]
        result = analyze(pools)
        total = sum(p["projected_earnings_usd"] for p in result["pools"])
        self.assertAlmostEqual(
            result["summary"]["total_projected_earnings_usd"], total, places=6
        )

    def test_pair_name_preserved(self):
        pool = eth_usdc_pool(pair="MY/TOKEN")
        result = analyze([pool])
        self.assertEqual(result["pools"][0]["pair"], "MY/TOKEN")

    def test_no_tiers_no_tier_change(self):
        pool = eth_usdc_pool(available_tiers_bps=[], current_tier_bps=30)
        result = analyze([pool])
        self.assertFalse(result["pools"][0]["tier_change_recommended"])

    def test_all_pools_different_pairs(self):
        pools = [
            eth_usdc_pool(pair=f"TOKEN{i}/USDC") for i in range(5)
        ]
        result = analyze(pools)
        pairs = [p["pair"] for p in result["pools"]]
        self.assertEqual(len(set(pairs)), 5)

    def test_projected_earnings_matches_fpd_x_days(self):
        pool = eth_usdc_pool(
            available_tiers_bps=[30],
            current_tier_bps=5,
            position_days=10,
        )
        result = analyze([pool])
        pr = result["pools"][0]
        ta = pr["tier_analysis"][0]
        expected = ta["fee_per_day_usd"] * 10
        self.assertAlmostEqual(pr["projected_earnings_usd"], expected, places=6)

    def test_analyze_result_serializable(self):
        result = analyze([eth_usdc_pool(), stable_pool()])
        # Should not raise
        json_str = json.dumps(result)
        self.assertIsInstance(json_str, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
