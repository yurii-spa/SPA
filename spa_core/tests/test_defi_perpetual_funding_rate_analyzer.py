"""
Tests for MP-932 DeFiPerpetualFundingRateAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_perpetual_funding_rate_analyzer -v
"""

import json
import os
import sys
import unittest
import tempfile

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_perpetual_funding_rate_analyzer import (
    DeFiPerpetualFundingRateAnalyzer,
    _annualize_funding_rate,
    _atomic_log,
    _carry_trade_opportunity,
    _clamp,
    _compute_flags,
    _funding_cost_score,
    _funding_label,
    _market_skew_score,
    _analyze_market,
)

NO_LOG = {"write_log": False}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _market(
    protocol="GMX",
    pair="ETH-USD",
    current_funding_rate_8h_pct=0.01,
    avg_funding_rate_30d_pct=0.008,
    open_interest_usd=50_000_000.0,
    long_short_ratio=1.5,
    funding_rate_volatility_pct=0.02,
    predicted_next_rate_pct=0.012,
    insurance_fund_usd=5_000_000.0,
    liquidations_24h_usd=500_000.0,
) -> dict:
    return {
        "protocol": protocol,
        "pair": pair,
        "current_funding_rate_8h_pct": current_funding_rate_8h_pct,
        "avg_funding_rate_30d_pct": avg_funding_rate_30d_pct,
        "open_interest_usd": open_interest_usd,
        "long_short_ratio": long_short_ratio,
        "funding_rate_volatility_pct": funding_rate_volatility_pct,
        "predicted_next_rate_pct": predicted_next_rate_pct,
        "insurance_fund_usd": insurance_fund_usd,
        "liquidations_24h_usd": liquidations_24h_usd,
    }


# ===========================================================================
# 1. _clamp
# ===========================================================================
class TestClamp(unittest.TestCase):
    def test_below_lo(self):
        self.assertEqual(_clamp(-10.0), 0.0)

    def test_above_hi(self):
        self.assertEqual(_clamp(110.0), 100.0)

    def test_within_range(self):
        self.assertEqual(_clamp(50.0), 50.0)

    def test_at_lo_boundary(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_at_hi_boundary(self):
        self.assertEqual(_clamp(100.0), 100.0)

    def test_custom_bounds(self):
        self.assertEqual(_clamp(5.0, lo=10.0, hi=20.0), 10.0)

    def test_custom_bounds_hi(self):
        self.assertEqual(_clamp(25.0, lo=10.0, hi=20.0), 20.0)

    def test_custom_within(self):
        self.assertEqual(_clamp(15.0, lo=10.0, hi=20.0), 15.0)


# ===========================================================================
# 2. _annualize_funding_rate
# ===========================================================================
class TestAnnualizeFundingRate(unittest.TestCase):
    def test_zero_rate(self):
        self.assertAlmostEqual(_annualize_funding_rate(0.0), 0.0)

    def test_positive_rate(self):
        # 0.01% * 3 * 365 = 10.95%
        self.assertAlmostEqual(_annualize_funding_rate(0.01), 10.95)

    def test_negative_rate(self):
        self.assertAlmostEqual(_annualize_funding_rate(-0.01), -10.95)

    def test_large_rate(self):
        # 0.1% * 3 * 365 = 109.5%
        self.assertAlmostEqual(_annualize_funding_rate(0.1), 109.5)

    def test_small_rate(self):
        self.assertAlmostEqual(_annualize_funding_rate(0.001), 1.095)

    def test_periods_days(self):
        # verify formula: rate * 3 * 365
        rate = 0.05
        expected = rate * 3 * 365
        self.assertAlmostEqual(_annualize_funding_rate(rate), expected)

    def test_half_percent(self):
        self.assertAlmostEqual(_annualize_funding_rate(0.5), 0.5 * 3 * 365)


# ===========================================================================
# 3. _funding_cost_score
# ===========================================================================
class TestFundingCostScore(unittest.TestCase):
    def test_zero_annualized(self):
        self.assertAlmostEqual(_funding_cost_score(0.0), 50.0)

    def test_positive_annualized(self):
        # 100% → 50 + 50 = 100
        self.assertAlmostEqual(_funding_cost_score(100.0), 100.0)

    def test_negative_annualized(self):
        # -100% → 50 - 50 = 0
        self.assertAlmostEqual(_funding_cost_score(-100.0), 0.0)

    def test_clamp_hi(self):
        self.assertAlmostEqual(_funding_cost_score(1000.0), 100.0)

    def test_clamp_lo(self):
        self.assertAlmostEqual(_funding_cost_score(-1000.0), 0.0)

    def test_moderate_positive(self):
        # 50% → 50 + 25 = 75
        self.assertAlmostEqual(_funding_cost_score(50.0), 75.0)

    def test_moderate_negative(self):
        # -50% → 50 - 25 = 25
        self.assertAlmostEqual(_funding_cost_score(-50.0), 25.0)

    def test_returns_float(self):
        result = _funding_cost_score(20.0)
        self.assertIsInstance(result, float)


# ===========================================================================
# 4. _market_skew_score
# ===========================================================================
class TestMarketSkewScore(unittest.TestCase):
    def test_neutral_ratio(self):
        # ratio=1 → log2(1)=0 → 50 + 25*0 = 50
        self.assertAlmostEqual(_market_skew_score(1.0), 50.0)

    def test_heavily_long(self):
        # ratio=2 → log2(2)=1 → 50 + 25 = 75
        self.assertAlmostEqual(_market_skew_score(2.0), 75.0)

    def test_heavily_short(self):
        # ratio=0.5 → log2(0.5)=-1 → 50 - 25 = 25
        self.assertAlmostEqual(_market_skew_score(0.5), 25.0)

    def test_zero_ratio_returns_zero(self):
        self.assertEqual(_market_skew_score(0.0), 0.0)

    def test_negative_ratio_returns_zero(self):
        self.assertEqual(_market_skew_score(-1.0), 0.0)

    def test_clamp_hi(self):
        # Very large ratio should clamp to 100
        self.assertAlmostEqual(_market_skew_score(1e9), 100.0)

    def test_clamp_lo(self):
        # Very small positive ratio → clamped to 0
        self.assertAlmostEqual(_market_skew_score(1e-9), 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_market_skew_score(1.5), float)


# ===========================================================================
# 5. _funding_label
# ===========================================================================
class TestFundingLabel(unittest.TestCase):
    def test_heavily_long(self):
        self.assertEqual(_funding_label(2.0), "HEAVILY_LONG")

    def test_heavily_long_above(self):
        self.assertEqual(_funding_label(5.0), "HEAVILY_LONG")

    def test_long_biased(self):
        self.assertEqual(_funding_label(1.5), "LONG_BIASED")

    def test_neutral_balanced(self):
        self.assertEqual(_funding_label(1.0), "NEUTRAL")

    def test_neutral_slight_long(self):
        # 1.1 is between SHORT_BIASED (0.8) and LONG_BIASED (1.25) → NEUTRAL
        self.assertEqual(_funding_label(1.1), "NEUTRAL")

    def test_short_biased(self):
        self.assertEqual(_funding_label(0.7), "SHORT_BIASED")

    def test_heavily_short(self):
        self.assertEqual(_funding_label(0.5), "HEAVILY_SHORT")

    def test_heavily_short_below(self):
        self.assertEqual(_funding_label(0.1), "HEAVILY_SHORT")

    def test_exact_boundaries_long(self):
        # Exactly LONG_BIASED_RATIO=1.25 → LONG_BIASED
        self.assertEqual(_funding_label(1.25), "LONG_BIASED")

    def test_exact_boundaries_heavily_long(self):
        # Exactly HEAVILY_LONG_RATIO=2.0 → HEAVILY_LONG
        self.assertEqual(_funding_label(2.0), "HEAVILY_LONG")

    def test_returns_str(self):
        self.assertIsInstance(_funding_label(1.0), str)


# ===========================================================================
# 6. _carry_trade_opportunity
# ===========================================================================
class TestCarryTradeOpportunity(unittest.TestCase):
    def test_positive_carry(self):
        # 20% funding, 4% staking → 16% premium
        self.assertAlmostEqual(_carry_trade_opportunity(20.0, 4.0), 16.0)

    def test_negative_carry(self):
        # 2% funding, 4% staking → -2% premium
        self.assertAlmostEqual(_carry_trade_opportunity(2.0, 4.0), -2.0)

    def test_zero_carry(self):
        self.assertAlmostEqual(_carry_trade_opportunity(4.0, 4.0), 0.0)

    def test_zero_staking(self):
        self.assertAlmostEqual(_carry_trade_opportunity(10.0, 0.0), 10.0)

    def test_negative_funding(self):
        # -5% funding, 4% staking → -9%
        self.assertAlmostEqual(_carry_trade_opportunity(-5.0, 4.0), -9.0)


# ===========================================================================
# 7. _compute_flags
# ===========================================================================
class TestComputeFlags(unittest.TestCase):
    def _base_market(self):
        return {
            "current_funding_rate_8h_pct": 0.01,
            "open_interest_usd": 10_000_000.0,
            "liquidations_24h_usd": 100_000.0,
            "insurance_fund_usd": 1_000_000.0,
            "funding_rate_volatility_pct": 0.02,
        }

    def test_no_flags_nominal(self):
        m = self._base_market()
        flags = _compute_flags(m, 10.0, 2.0)
        self.assertEqual(flags, [])

    def test_extreme_funding_flag_positive(self):
        m = self._base_market()
        m["current_funding_rate_8h_pct"] = 0.15
        flags = _compute_flags(m, 164.25, 160.0)
        self.assertIn("EXTREME_FUNDING", flags)

    def test_extreme_funding_flag_negative(self):
        m = self._base_market()
        m["current_funding_rate_8h_pct"] = -0.15
        flags = _compute_flags(m, -164.25, -170.0)
        self.assertIn("EXTREME_FUNDING", flags)

    def test_carry_opportunity_flag(self):
        m = self._base_market()
        # carry_premium > 5% → CARRY_OPPORTUNITY
        flags = _compute_flags(m, 10.0, 10.0)
        self.assertIn("CARRY_OPPORTUNITY", flags)

    def test_no_carry_flag_below_threshold(self):
        m = self._base_market()
        flags = _compute_flags(m, 10.0, 3.0)
        self.assertNotIn("CARRY_OPPORTUNITY", flags)

    def test_high_liquidation_risk(self):
        m = self._base_market()
        # liq = 6% of OI → flag
        m["liquidations_24h_usd"] = 600_000.0
        flags = _compute_flags(m, 10.0, 3.0)
        self.assertIn("HIGH_LIQUIDATION_RISK", flags)

    def test_no_high_liq_zero_oi(self):
        m = self._base_market()
        m["open_interest_usd"] = 0.0
        flags = _compute_flags(m, 10.0, 3.0)
        self.assertNotIn("HIGH_LIQUIDATION_RISK", flags)

    def test_low_insurance_flag(self):
        m = self._base_market()
        # insurance = 0.5% OI → flag
        m["insurance_fund_usd"] = 50_000.0
        flags = _compute_flags(m, 10.0, 3.0)
        self.assertIn("LOW_INSURANCE", flags)

    def test_no_low_insurance_zero_oi(self):
        m = self._base_market()
        m["open_interest_usd"] = 0.0
        flags = _compute_flags(m, 10.0, 3.0)
        self.assertNotIn("LOW_INSURANCE", flags)

    def test_volatile_funding_flag(self):
        m = self._base_market()
        m["funding_rate_volatility_pct"] = 0.06
        flags = _compute_flags(m, 10.0, 3.0)
        self.assertIn("VOLATILE_FUNDING", flags)

    def test_all_flags_simultaneously(self):
        m = {
            "current_funding_rate_8h_pct": 0.2,
            "open_interest_usd": 10_000_000.0,
            "liquidations_24h_usd": 1_000_000.0,   # 10% → HIGH_LIQ
            "insurance_fund_usd": 50_000.0,          # 0.5% → LOW_INS
            "funding_rate_volatility_pct": 0.1,      # > 0.05 → VOLATILE
        }
        flags = _compute_flags(m, 219.0, 215.0)     # annualized huge → EXTREME, CARRY
        for expected in [
            "EXTREME_FUNDING", "CARRY_OPPORTUNITY",
            "HIGH_LIQUIDATION_RISK", "LOW_INSURANCE", "VOLATILE_FUNDING",
        ]:
            self.assertIn(expected, flags)

    def test_returns_list(self):
        m = self._base_market()
        result = _compute_flags(m, 10.0, 3.0)
        self.assertIsInstance(result, list)


# ===========================================================================
# 8. _analyze_market
# ===========================================================================
class TestAnalyzeMarket(unittest.TestCase):
    def test_passthrough_fields(self):
        m = _market(protocol="dYdX", pair="BTC-USD")
        result = _analyze_market(m, {})
        self.assertEqual(result["protocol"], "dYdX")
        self.assertEqual(result["pair"], "BTC-USD")

    def test_annualized_computed(self):
        m = _market(current_funding_rate_8h_pct=0.01)
        result = _analyze_market(m, {})
        self.assertAlmostEqual(result["annualized_funding_pct"], 10.95)

    def test_funding_cost_score_range(self):
        m = _market()
        result = _analyze_market(m, {})
        self.assertGreaterEqual(result["funding_cost_score"], 0.0)
        self.assertLessEqual(result["funding_cost_score"], 100.0)

    def test_market_skew_score_range(self):
        m = _market()
        result = _analyze_market(m, {})
        self.assertGreaterEqual(result["market_skew_score"], 0.0)
        self.assertLessEqual(result["market_skew_score"], 100.0)

    def test_flags_is_list(self):
        m = _market()
        result = _analyze_market(m, {})
        self.assertIsInstance(result["flags"], list)

    def test_funding_label_present(self):
        m = _market()
        result = _analyze_market(m, {})
        valid_labels = {
            "HEAVILY_LONG", "LONG_BIASED", "NEUTRAL",
            "SHORT_BIASED", "HEAVILY_SHORT",
        }
        self.assertIn(result["funding_label"], valid_labels)

    def test_carry_opportunity_uses_config_staking(self):
        m = _market(current_funding_rate_8h_pct=0.01)
        config = {"spot_staking_apy_pct": 5.0}
        result = _analyze_market(m, config)
        expected_carry = 10.95 - 5.0
        self.assertAlmostEqual(result["carry_trade_opportunity_pct"], expected_carry, places=3)

    def test_all_keys_present(self):
        m = _market()
        result = _analyze_market(m, {})
        for k in [
            "protocol", "pair", "current_funding_rate_8h_pct",
            "avg_funding_rate_30d_pct", "open_interest_usd",
            "long_short_ratio", "funding_rate_volatility_pct",
            "predicted_next_rate_pct", "insurance_fund_usd",
            "liquidations_24h_usd", "annualized_funding_pct",
            "funding_cost_score", "market_skew_score",
            "carry_trade_opportunity_pct", "funding_label", "flags",
        ]:
            self.assertIn(k, result, msg=f"Missing key: {k}")


# ===========================================================================
# 9. _atomic_log
# ===========================================================================
class TestAtomicLog(unittest.TestCase):
    def _make_log_path(self, tmp_dir):
        return os.path.join(tmp_dir, "test_perp_log.json")

    def test_creates_log_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            _atomic_log({"a": 1}, path)
            self.assertTrue(os.path.exists(path))

    def test_log_contains_entry(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            _atomic_log({"key": "val"}, path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["key"], "val")

    def test_ring_buffer_capped(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            for i in range(105):
                _atomic_log({"i": i}, path, max_entries=100)
            with open(path) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), 100)

    def test_ring_buffer_keeps_latest(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            for i in range(105):
                _atomic_log({"i": i}, path, max_entries=100)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data[-1]["i"], 104)

    def test_append_multiple_entries(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            _atomic_log({"n": 1}, path)
            _atomic_log({"n": 2}, path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)


# ===========================================================================
# 10. DeFiPerpetualFundingRateAnalyzer — instantiation & structure
# ===========================================================================
class TestAnalyzerInstantiation(unittest.TestCase):
    def test_instantiation(self):
        a = DeFiPerpetualFundingRateAnalyzer()
        self.assertIsNotNone(a)

    def test_has_analyze_method(self):
        a = DeFiPerpetualFundingRateAnalyzer()
        self.assertTrue(callable(getattr(a, "analyze", None)))


# ===========================================================================
# 11. DeFiPerpetualFundingRateAnalyzer.analyze — empty / no markets
# ===========================================================================
class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.a = DeFiPerpetualFundingRateAnalyzer()

    def test_empty_markets_returns_ok(self):
        r = self.a.analyze([], NO_LOG)
        self.assertEqual(r["status"], "ok")

    def test_empty_markets_count_zero(self):
        r = self.a.analyze([], NO_LOG)
        self.assertEqual(r["markets_analyzed"], 0)

    def test_empty_markets_list(self):
        r = self.a.analyze([], NO_LOG)
        self.assertEqual(r["markets"], [])

    def test_empty_aggregates(self):
        r = self.a.analyze([], NO_LOG)
        agg = r["aggregates"]
        self.assertIsNone(agg["highest_funding_market"])
        self.assertIsNone(agg["lowest_funding_market"])
        self.assertEqual(agg["total_open_interest_usd"], 0.0)
        self.assertEqual(agg["average_annualized_funding"], 0.0)
        self.assertEqual(agg["carry_opportunity_count"], 0)

    def test_empty_has_timestamp(self):
        r = self.a.analyze([], NO_LOG)
        self.assertIn("timestamp", r)

    def test_empty_config_used_key(self):
        r = self.a.analyze([], NO_LOG)
        self.assertIn("config_used", r)


# ===========================================================================
# 12. DeFiPerpetualFundingRateAnalyzer.analyze — single market
# ===========================================================================
class TestAnalyzeSingle(unittest.TestCase):
    def setUp(self):
        self.a = DeFiPerpetualFundingRateAnalyzer()

    def test_single_market_count(self):
        r = self.a.analyze([_market()], NO_LOG)
        self.assertEqual(r["markets_analyzed"], 1)

    def test_single_market_list_length(self):
        r = self.a.analyze([_market()], NO_LOG)
        self.assertEqual(len(r["markets"]), 1)

    def test_single_highest_equals_lowest(self):
        r = self.a.analyze([_market(protocol="GMX", pair="ETH-USD")], NO_LOG)
        agg = r["aggregates"]
        self.assertEqual(agg["highest_funding_market"], agg["lowest_funding_market"])

    def test_single_total_oi(self):
        r = self.a.analyze([_market(open_interest_usd=12_000_000.0)], NO_LOG)
        self.assertAlmostEqual(r["aggregates"]["total_open_interest_usd"], 12_000_000.0)

    def test_single_avg_annualized(self):
        r = self.a.analyze([_market(current_funding_rate_8h_pct=0.01)], NO_LOG)
        self.assertAlmostEqual(
            r["aggregates"]["average_annualized_funding"], 10.95, places=3
        )


# ===========================================================================
# 13. DeFiPerpetualFundingRateAnalyzer.analyze — multiple markets
# ===========================================================================
class TestAnalyzeMultiple(unittest.TestCase):
    def setUp(self):
        self.a = DeFiPerpetualFundingRateAnalyzer()
        self.markets = [
            _market(protocol="GMX",    pair="ETH-USD", current_funding_rate_8h_pct=0.02,
                    open_interest_usd=10_000_000.0),
            _market(protocol="dYdX",   pair="BTC-USD", current_funding_rate_8h_pct=0.01,
                    open_interest_usd=20_000_000.0),
            _market(protocol="Vertex", pair="SOL-USD", current_funding_rate_8h_pct=-0.005,
                    open_interest_usd=5_000_000.0),
        ]

    def test_count(self):
        r = self.a.analyze(self.markets, NO_LOG)
        self.assertEqual(r["markets_analyzed"], 3)

    def test_total_oi(self):
        r = self.a.analyze(self.markets, NO_LOG)
        self.assertAlmostEqual(
            r["aggregates"]["total_open_interest_usd"], 35_000_000.0
        )

    def test_highest_funding_market(self):
        r = self.a.analyze(self.markets, NO_LOG)
        # 0.02% * 3 * 365 = 21.9% → GMX:ETH-USD
        self.assertEqual(
            r["aggregates"]["highest_funding_market"], "GMX:ETH-USD"
        )

    def test_lowest_funding_market(self):
        r = self.a.analyze(self.markets, NO_LOG)
        # -0.005% * 3 * 365 = -5.475% → Vertex:SOL-USD
        self.assertEqual(
            r["aggregates"]["lowest_funding_market"], "Vertex:SOL-USD"
        )

    def test_avg_annualized(self):
        r = self.a.analyze(self.markets, NO_LOG)
        ann_gmx = 0.02 * 3 * 365
        ann_dydx = 0.01 * 3 * 365
        ann_vtx = -0.005 * 3 * 365
        expected = (ann_gmx + ann_dydx + ann_vtx) / 3
        self.assertAlmostEqual(
            r["aggregates"]["average_annualized_funding"], expected, places=3
        )

    def test_markets_list_length(self):
        r = self.a.analyze(self.markets, NO_LOG)
        self.assertEqual(len(r["markets"]), 3)

    def test_status_ok(self):
        r = self.a.analyze(self.markets, NO_LOG)
        self.assertEqual(r["status"], "ok")


# ===========================================================================
# 14. Carry opportunity count
# ===========================================================================
class TestCarryOpportunityCount(unittest.TestCase):
    def setUp(self):
        self.a = DeFiPerpetualFundingRateAnalyzer()

    def test_zero_carry_when_funding_low(self):
        # 0.001% * 3 * 365 = 1.095%, staking = 4% → carry = -2.9% → no flag
        m = _market(current_funding_rate_8h_pct=0.001)
        r = self.a.analyze([m], {"write_log": False, "spot_staking_apy_pct": 4.0})
        self.assertEqual(r["aggregates"]["carry_opportunity_count"], 0)

    def test_carry_opportunity_detected(self):
        # 0.1% * 3 * 365 = 109.5%, staking = 4% → carry = 105.5% > 5% → flag
        m = _market(current_funding_rate_8h_pct=0.1)
        r = self.a.analyze([m], {"write_log": False, "spot_staking_apy_pct": 4.0})
        self.assertEqual(r["aggregates"]["carry_opportunity_count"], 1)

    def test_multiple_carry_opportunities(self):
        markets = [
            _market(current_funding_rate_8h_pct=0.1, protocol="A", pair="X"),
            _market(current_funding_rate_8h_pct=0.05, protocol="B", pair="Y"),
            _market(current_funding_rate_8h_pct=0.001, protocol="C", pair="Z"),
        ]
        r = self.a.analyze(markets, {"write_log": False, "spot_staking_apy_pct": 4.0})
        self.assertEqual(r["aggregates"]["carry_opportunity_count"], 2)


# ===========================================================================
# 15. Config propagation
# ===========================================================================
class TestConfigPropagation(unittest.TestCase):
    def setUp(self):
        self.a = DeFiPerpetualFundingRateAnalyzer()

    def test_custom_staking_apy_reflected(self):
        r = self.a.analyze([], {"write_log": False, "spot_staking_apy_pct": 6.0})
        self.assertAlmostEqual(r["config_used"]["spot_staking_apy_pct"], 6.0)

    def test_default_staking_apy(self):
        r = self.a.analyze([], NO_LOG)
        self.assertAlmostEqual(r["config_used"]["spot_staking_apy_pct"], 4.0)

    def test_no_log_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            self.a.analyze([], {"write_log": False, "log_path": path})
            self.assertFalse(os.path.exists(path))

    def test_write_log_true_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            self.a.analyze([], {"write_log": True, "log_path": path})
            self.assertTrue(os.path.exists(path))


# ===========================================================================
# 16. Per-market field validation
# ===========================================================================
class TestPerMarketFields(unittest.TestCase):
    def setUp(self):
        self.a = DeFiPerpetualFundingRateAnalyzer()

    def test_annualized_funding_in_market(self):
        r = self.a.analyze([_market(current_funding_rate_8h_pct=0.02)], NO_LOG)
        self.assertIn("annualized_funding_pct", r["markets"][0])

    def test_funding_cost_score_in_market(self):
        r = self.a.analyze([_market()], NO_LOG)
        self.assertIn("funding_cost_score", r["markets"][0])

    def test_market_skew_score_in_market(self):
        r = self.a.analyze([_market()], NO_LOG)
        self.assertIn("market_skew_score", r["markets"][0])

    def test_flags_in_market(self):
        r = self.a.analyze([_market()], NO_LOG)
        self.assertIsInstance(r["markets"][0]["flags"], list)

    def test_funding_label_in_market(self):
        r = self.a.analyze([_market()], NO_LOG)
        self.assertIn("funding_label", r["markets"][0])


# ===========================================================================
# 17. Flag appearance in full analyze output
# ===========================================================================
class TestFlagsInAnalyze(unittest.TestCase):
    def setUp(self):
        self.a = DeFiPerpetualFundingRateAnalyzer()

    def test_extreme_funding_flag_in_output(self):
        m = _market(current_funding_rate_8h_pct=0.2)
        r = self.a.analyze([m], NO_LOG)
        self.assertIn("EXTREME_FUNDING", r["markets"][0]["flags"])

    def test_volatile_funding_flag(self):
        m = _market(funding_rate_volatility_pct=0.1)
        r = self.a.analyze([m], NO_LOG)
        self.assertIn("VOLATILE_FUNDING", r["markets"][0]["flags"])

    def test_low_insurance_flag(self):
        m = _market(open_interest_usd=10_000_000.0, insurance_fund_usd=50_000.0)
        r = self.a.analyze([m], NO_LOG)
        self.assertIn("LOW_INSURANCE", r["markets"][0]["flags"])

    def test_high_liquidation_risk_flag(self):
        m = _market(open_interest_usd=10_000_000.0, liquidations_24h_usd=600_000.0)
        r = self.a.analyze([m], NO_LOG)
        self.assertIn("HIGH_LIQUIDATION_RISK", r["markets"][0]["flags"])


# ===========================================================================
# 18. Edge cases
# ===========================================================================
class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.a = DeFiPerpetualFundingRateAnalyzer()

    def test_none_config_defaults(self):
        r = self.a.analyze([], None)
        self.assertEqual(r["status"], "ok")

    def test_negative_funding_rate(self):
        m = _market(current_funding_rate_8h_pct=-0.05)
        r = self.a.analyze([m], NO_LOG)
        self.assertLess(r["markets"][0]["annualized_funding_pct"], 0)

    def test_zero_oi_no_crash(self):
        m = _market(open_interest_usd=0.0, liquidations_24h_usd=0.0)
        r = self.a.analyze([m], NO_LOG)
        self.assertEqual(r["status"], "ok")

    def test_equal_oi_in_two_markets_for_total(self):
        markets = [
            _market(protocol="A", pair="X", open_interest_usd=1_000.0),
            _market(protocol="B", pair="Y", open_interest_usd=1_000.0),
        ]
        r = self.a.analyze(markets, NO_LOG)
        self.assertAlmostEqual(r["aggregates"]["total_open_interest_usd"], 2_000.0)

    def test_timestamp_format(self):
        r = self.a.analyze([], NO_LOG)
        ts = r["timestamp"]
        self.assertRegex(ts, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


if __name__ == "__main__":
    unittest.main()
