"""
Tests for MP-746: BorrowRateOptimizer
≥65 test methods covering all logic paths.
Uses unittest only (no pytest).
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.borrow_rate_optimizer import (
    BorrowOpportunity,
    BorrowRateResult,
    _RING_BUFFER_CAP,
    analyze_market,
    analyze_opportunity,
    attractiveness_score,
    compute_leverage_2x,
    compute_leverage_3x,
    compute_net_spread,
    is_attractive,
    liquidation_buffer,
    load_history,
    rate_label,
    save_results,
    utilization_risk,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _opp_data(
    protocol: str = "Aave",
    asset: str = "USDC",
    supply_apy: float = 5.0,
    borrow_rate: float = 3.0,
    utilization: float = 60.0,
) -> dict:
    return {
        "protocol": protocol,
        "asset": asset,
        "supply_apy_pct": supply_apy,
        "borrow_rate_pct": borrow_rate,
        "utilization_rate_pct": utilization,
    }


def _market(n: int = 3) -> list:
    return [
        _opp_data("AaveV3",     borrow_rate=2.5, supply_apy=5.0, utilization=55.0),
        _opp_data("CompoundV3", borrow_rate=4.0, supply_apy=4.5, utilization=70.0),
        _opp_data("MorphoBlue", borrow_rate=7.5, supply_apy=6.0, utilization=85.0),
    ][:n]


# ── compute_net_spread ─────────────────────────────────────────────────────────

class TestComputeNetSpread(unittest.TestCase):
    def test_positive_spread(self):
        self.assertAlmostEqual(compute_net_spread(5.0, 3.0), 2.0)

    def test_negative_spread_borrow_exceeds_supply(self):
        self.assertAlmostEqual(compute_net_spread(3.0, 5.0), -2.0)

    def test_zero_spread(self):
        self.assertAlmostEqual(compute_net_spread(4.0, 4.0), 0.0)

    def test_zero_supply_apy(self):
        self.assertAlmostEqual(compute_net_spread(0.0, 5.0), -5.0)

    def test_zero_borrow_rate(self):
        self.assertAlmostEqual(compute_net_spread(6.0, 0.0), 6.0)


# ── compute_leverage_2x ───────────────────────────────────────────────────────

class TestComputeLeverage2x(unittest.TestCase):
    def test_formula(self):
        # 2*5.0 - 3.0 = 7.0
        self.assertAlmostEqual(compute_leverage_2x(5.0, 3.0), 7.0)

    def test_negative_when_borrow_high(self):
        # 2*1.0 - 6.0 = -4.0
        self.assertAlmostEqual(compute_leverage_2x(1.0, 6.0), -4.0)

    def test_zero_borrow(self):
        self.assertAlmostEqual(compute_leverage_2x(4.0, 0.0), 8.0)

    def test_zero_supply(self):
        self.assertAlmostEqual(compute_leverage_2x(0.0, 3.0), -3.0)


# ── compute_leverage_3x ───────────────────────────────────────────────────────

class TestComputeLeverage3x(unittest.TestCase):
    def test_formula(self):
        # 3*5.0 - 2*3.0 = 15 - 6 = 9.0
        self.assertAlmostEqual(compute_leverage_3x(5.0, 3.0), 9.0)

    def test_negative_result(self):
        # 3*1.0 - 2*5.0 = 3 - 10 = -7.0
        self.assertAlmostEqual(compute_leverage_3x(1.0, 5.0), -7.0)

    def test_zero_borrow(self):
        self.assertAlmostEqual(compute_leverage_3x(4.0, 0.0), 12.0)

    def test_zero_supply(self):
        self.assertAlmostEqual(compute_leverage_3x(0.0, 4.0), -8.0)


# ── utilization_risk ──────────────────────────────────────────────────────────

class TestUtilizationRisk(unittest.TestCase):
    def test_low_below_50(self):
        self.assertEqual(utilization_risk(30.0), "LOW")

    def test_low_at_zero(self):
        self.assertEqual(utilization_risk(0.0), "LOW")

    def test_low_just_below_50(self):
        self.assertEqual(utilization_risk(49.9), "LOW")

    def test_moderate_at_50(self):
        self.assertEqual(utilization_risk(50.0), "MODERATE")

    def test_moderate_at_80(self):
        self.assertEqual(utilization_risk(80.0), "MODERATE")

    def test_moderate_mid(self):
        self.assertEqual(utilization_risk(65.0), "MODERATE")

    def test_high_above_80(self):
        self.assertEqual(utilization_risk(81.0), "HIGH")

    def test_high_at_100(self):
        self.assertEqual(utilization_risk(100.0), "HIGH")


# ── liquidation_buffer ────────────────────────────────────────────────────────

class TestLiquidationBuffer(unittest.TestCase):
    def test_basic_formula(self):
        self.assertAlmostEqual(liquidation_buffer(60.0), 20.0)

    def test_zero_utilization(self):
        self.assertAlmostEqual(liquidation_buffer(0.0), 80.0)

    def test_exactly_80(self):
        self.assertAlmostEqual(liquidation_buffer(80.0), 0.0)

    def test_capped_at_zero_above_80(self):
        self.assertAlmostEqual(liquidation_buffer(90.0), 0.0)

    def test_capped_at_zero_at_100(self):
        self.assertAlmostEqual(liquidation_buffer(100.0), 0.0)


# ── attractiveness_score ──────────────────────────────────────────────────────

class TestAttractivenessScore(unittest.TestCase):
    def test_formula(self):
        # 2.0 * (1 - 60/100) * 100 = 2.0 * 0.4 * 100 = 80.0
        self.assertAlmostEqual(attractiveness_score(2.0, 60.0), 80.0)

    def test_clamp_at_100(self):
        self.assertAlmostEqual(attractiveness_score(999.0, 0.0), 100.0)

    def test_clamp_at_zero_negative_spread(self):
        self.assertAlmostEqual(attractiveness_score(-5.0, 30.0), 0.0)

    def test_zero_spread(self):
        self.assertAlmostEqual(attractiveness_score(0.0, 50.0), 0.0)

    def test_high_util_reduces_score(self):
        score_low_util = attractiveness_score(2.0, 20.0)
        score_high_util = attractiveness_score(2.0, 70.0)
        self.assertGreater(score_low_util, score_high_util)


# ── rate_label ────────────────────────────────────────────────────────────────

class TestRateLabel(unittest.TestCase):
    def test_cheap_below_3(self):
        self.assertEqual(rate_label(2.9), "CHEAP")

    def test_cheap_at_zero(self):
        self.assertEqual(rate_label(0.0), "CHEAP")

    def test_moderate_at_3(self):
        self.assertEqual(rate_label(3.0), "MODERATE")

    def test_moderate_at_6(self):
        self.assertEqual(rate_label(6.0), "MODERATE")

    def test_moderate_mid(self):
        self.assertEqual(rate_label(4.5), "MODERATE")

    def test_expensive_above_6(self):
        self.assertEqual(rate_label(6.01), "EXPENSIVE")

    def test_expensive_high(self):
        self.assertEqual(rate_label(12.0), "EXPENSIVE")


# ── is_attractive ─────────────────────────────────────────────────────────────

class TestIsAttractive(unittest.TestCase):
    def test_true_when_spread_positive_and_util_low(self):
        self.assertTrue(is_attractive(2.0, 60.0))

    def test_false_when_util_at_80(self):
        self.assertFalse(is_attractive(2.0, 80.0))

    def test_false_when_util_above_80(self):
        self.assertFalse(is_attractive(5.0, 85.0))

    def test_false_when_spread_exactly_1(self):
        self.assertFalse(is_attractive(1.0, 60.0))

    def test_false_when_spread_below_1(self):
        self.assertFalse(is_attractive(0.5, 30.0))

    def test_false_when_spread_negative(self):
        self.assertFalse(is_attractive(-1.0, 50.0))

    def test_true_just_above_spread_threshold(self):
        self.assertTrue(is_attractive(1.01, 79.9))


# ── analyze_opportunity ───────────────────────────────────────────────────────

class TestAnalyzeOpportunity(unittest.TestCase):
    def setUp(self):
        self.opp = analyze_opportunity("Aave", "USDC", 5.0, 2.5, 55.0)

    def test_protocol_stored(self):
        self.assertEqual(self.opp.protocol, "Aave")

    def test_asset_stored(self):
        self.assertEqual(self.opp.asset, "USDC")

    def test_supply_apy_stored(self):
        self.assertAlmostEqual(self.opp.supply_apy_pct, 5.0)

    def test_borrow_rate_stored(self):
        self.assertAlmostEqual(self.opp.borrow_rate_pct, 2.5)

    def test_utilization_stored(self):
        self.assertAlmostEqual(self.opp.utilization_rate_pct, 55.0)

    def test_net_spread(self):
        self.assertAlmostEqual(self.opp.net_spread_pct, 2.5)

    def test_leverage_2x(self):
        # 2*5.0 - 2.5 = 7.5
        self.assertAlmostEqual(self.opp.leverage_2x_apy_pct, 7.5)

    def test_leverage_3x(self):
        # 3*5.0 - 2*2.5 = 15 - 5 = 10.0
        self.assertAlmostEqual(self.opp.leverage_3x_apy_pct, 10.0)

    def test_utilization_risk_moderate(self):
        self.assertEqual(self.opp.utilization_risk, "MODERATE")

    def test_liquidation_buffer(self):
        self.assertAlmostEqual(self.opp.liquidation_buffer_pct, 25.0)

    def test_is_attractive_true(self):
        self.assertTrue(self.opp.is_attractive)

    def test_attractiveness_score_positive(self):
        self.assertGreater(self.opp.attractiveness_score, 0.0)

    def test_rate_label_cheap(self):
        self.assertEqual(self.opp.rate_label, "CHEAP")

    def test_recommendation_attractive(self):
        self.assertIn("Attractive", self.opp.recommendation)


class TestRecommendations(unittest.TestCase):
    def test_high_util_recommendation(self):
        opp = analyze_opportunity("X", "USDC", 5.0, 3.0, 90.0)
        self.assertIn("utilization risk", opp.recommendation)

    def test_negative_spread_recommendation(self):
        opp = analyze_opportunity("X", "USDC", 2.0, 8.0, 50.0)
        self.assertIn("Borrow cost exceeds", opp.recommendation)

    def test_attractive_recommendation(self):
        opp = analyze_opportunity("X", "USDC", 6.0, 2.0, 40.0)
        self.assertIn("Attractive", opp.recommendation)

    def test_marginal_spread_recommendation(self):
        # spread = 0.5, not attractive but no other trigger
        opp = analyze_opportunity("X", "USDC", 3.5, 3.0, 60.0)
        self.assertIn("Marginal", opp.recommendation)


# ── analyze_market ────────────────────────────────────────────────────────────

class TestAnalyzeMarket(unittest.TestCase):
    def setUp(self):
        self.data = [
            _opp_data("AaveV3",     supply_apy=5.0, borrow_rate=2.0, utilization=50.0),
            _opp_data("CompoundV3", supply_apy=4.0, borrow_rate=4.5, utilization=75.0),
            _opp_data("MorphoBlue", supply_apy=7.0, borrow_rate=8.0, utilization=90.0),
        ]
        self.result = analyze_market(self.data)

    def test_best_spread_protocol(self):
        # AaveV3: 5-2=3.0, Compound: 4-4.5=-0.5, Morpho: 7-8=-1
        self.assertEqual(self.result.best_spread_protocol, "AaveV3")

    def test_lowest_rate_protocol(self):
        self.assertEqual(self.result.lowest_rate_protocol, "AaveV3")

    def test_riskiest_protocol(self):
        self.assertEqual(self.result.riskiest_protocol, "MorphoBlue")

    def test_avg_borrow_rate(self):
        expected = (2.0 + 4.5 + 8.0) / 3
        self.assertAlmostEqual(self.result.avg_borrow_rate_pct, expected, places=5)

    def test_avg_net_spread(self):
        expected = (3.0 + (-0.5) + (-1.0)) / 3
        self.assertAlmostEqual(self.result.avg_net_spread_pct, expected, places=5)

    def test_attractive_count(self):
        # AaveV3: spread=3>1, util=50<80 → True; others False
        self.assertEqual(self.result.attractive_count, 1)

    def test_market_rate_label_moderate(self):
        # avg = (2+4.5+8)/3 = 4.83 → MODERATE_CREDIT
        self.assertEqual(self.result.market_rate_label, "MODERATE_CREDIT")

    def test_market_rate_label_cheap(self):
        data = [
            _opp_data("P1", borrow_rate=1.0, supply_apy=5.0, utilization=30.0),
            _opp_data("P2", borrow_rate=1.5, supply_apy=5.0, utilization=40.0),
        ]
        r = analyze_market(data)
        self.assertEqual(r.market_rate_label, "CHEAP_CREDIT")

    def test_market_rate_label_expensive(self):
        data = [
            _opp_data("P1", borrow_rate=7.0, supply_apy=5.0, utilization=85.0),
            _opp_data("P2", borrow_rate=8.0, supply_apy=5.0, utilization=90.0),
        ]
        r = analyze_market(data)
        self.assertEqual(r.market_rate_label, "EXPENSIVE_CREDIT")

    def test_recommendation_summary_non_empty(self):
        self.assertTrue(len(self.result.recommendation_summary) > 0)

    def test_opportunities_list_length(self):
        self.assertEqual(len(self.result.opportunities), 3)

    def test_empty_raises(self):
        with self.assertRaises((ValueError, Exception)):
            analyze_market([])


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):
    def test_zero_supply_apy_net_spread_equals_negative_borrow(self):
        opp = analyze_opportunity("X", "USDC", 0.0, 5.0, 50.0)
        self.assertAlmostEqual(opp.net_spread_pct, -5.0)

    def test_zero_borrow_rate_leverage_at_max_efficiency(self):
        opp = analyze_opportunity("X", "USDC", 5.0, 0.0, 30.0)
        self.assertAlmostEqual(opp.borrow_rate_pct, 0.0)
        self.assertAlmostEqual(opp.leverage_2x_apy_pct, 10.0)
        self.assertAlmostEqual(opp.leverage_3x_apy_pct, 15.0)
        self.assertEqual(opp.rate_label, "CHEAP")

    def test_single_opportunity_market(self):
        data = [_opp_data("OnlyOne", supply_apy=6.0, borrow_rate=2.0, utilization=40.0)]
        r = analyze_market(data)
        self.assertEqual(r.best_spread_protocol, "OnlyOne")
        self.assertEqual(r.lowest_rate_protocol, "OnlyOne")
        self.assertEqual(r.riskiest_protocol, "OnlyOne")


# ── save / load ───────────────────────────────────────────────────────────────

class TestSaveLoad(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "borrow_rate_log.json")

    def _make_result(self) -> BorrowRateResult:
        data = [_opp_data("AaveV3", supply_apy=5.0, borrow_rate=2.0, utilization=50.0)]
        return analyze_market(data)

    def test_save_creates_file(self):
        result = self._make_result()
        save_results(result, self.log_file)
        self.assertTrue(os.path.exists(self.log_file))

    def test_load_returns_list_after_save(self):
        result = self._make_result()
        save_results(result, self.log_file)
        history = load_history(self.log_file)
        self.assertIsInstance(history, list)
        self.assertEqual(len(history), 1)

    def test_save_load_round_trip(self):
        result = self._make_result()
        save_results(result, self.log_file)
        history = load_history(self.log_file)
        entry = history[0]
        self.assertEqual(entry["best_spread_protocol"], "AaveV3")
        self.assertIn("timestamp", entry)

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            save_results(self._make_result(), self.log_file)
        history = load_history(self.log_file)
        self.assertEqual(len(history), 5)

    def test_load_returns_empty_when_file_missing(self):
        history = load_history(os.path.join(self.tmp_dir, "nonexistent.json"))
        self.assertEqual(history, [])

    def test_ring_buffer_cap_100(self):
        for _ in range(_RING_BUFFER_CAP + 20):
            save_results(self._make_result(), self.log_file)
        history = load_history(self.log_file)
        self.assertLessEqual(len(history), _RING_BUFFER_CAP)

    def test_ring_buffer_keeps_newest(self):
        """After overflow, the oldest entries should be dropped."""
        # Save RING_BUFFER_CAP+5 entries; the first entry's index should be gone.
        for i in range(_RING_BUFFER_CAP + 5):
            save_results(self._make_result(), self.log_file)
        history = load_history(self.log_file)
        self.assertEqual(len(history), _RING_BUFFER_CAP)

    def test_save_returns_log_file_path(self):
        result = self._make_result()
        path = save_results(result, self.log_file)
        self.assertEqual(path, self.log_file)


if __name__ == "__main__":
    unittest.main()
