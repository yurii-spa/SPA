"""
Tests for MP-757: RewardTokenTracker
Uses unittest only. 65+ test cases.
"""

import os
import tempfile
import unittest

from spa_core.analytics.reward_token_tracker import (
    compute_vesting_discount,
    compute_volatility_discount,
    load_history,
    reward_quality_label,
    save_results,
    token_label,
    track_portfolio,
    track_token,
)


class TestComputeVestingDiscount(unittest.TestCase):
    def test_basic(self):
        # 6 months * 2% = 12%
        self.assertAlmostEqual(compute_vesting_discount(6), 12.0)

    def test_zero_months(self):
        self.assertAlmostEqual(compute_vesting_discount(0), 0.0)

    def test_capped_at_50(self):
        # 30 months * 2% = 60% → capped at 50%
        self.assertAlmostEqual(compute_vesting_discount(30), 50.0)

    def test_exactly_at_cap(self):
        # 25 months * 2% = 50%
        self.assertAlmostEqual(compute_vesting_discount(25), 50.0)

    def test_one_month(self):
        self.assertAlmostEqual(compute_vesting_discount(1), 2.0)

    def test_twelve_months(self):
        self.assertAlmostEqual(compute_vesting_discount(12), 24.0)

    def test_large_months_capped(self):
        self.assertAlmostEqual(compute_vesting_discount(100), 50.0)


class TestComputeVolatilityDiscount(unittest.TestCase):
    def test_basic(self):
        # 80% vol * 0.3 = 24%
        self.assertAlmostEqual(compute_volatility_discount(80.0), 24.0)

    def test_zero_volatility(self):
        self.assertAlmostEqual(compute_volatility_discount(0.0), 0.0)

    def test_capped_at_50(self):
        # 200% vol * 0.3 = 60% → capped at 50%
        self.assertAlmostEqual(compute_volatility_discount(200.0), 50.0)

    def test_exactly_at_cap(self):
        # 50/0.3 = 166.67% vol
        vol = 50.0 / 0.3
        self.assertAlmostEqual(compute_volatility_discount(vol), 50.0)

    def test_low_volatility(self):
        self.assertAlmostEqual(compute_volatility_discount(10.0), 3.0)

    def test_fifty_percent_vol(self):
        self.assertAlmostEqual(compute_volatility_discount(50.0), 15.0)


class TestAnnualRewardUsd(unittest.TestCase):
    def test_basic(self):
        t = track_token("TKN", "Proto", 1000, 5.0, 0, 0.0, 100000)
        self.assertAlmostEqual(t.annual_reward_usd, 5000.0)

    def test_zero_tokens(self):
        t = track_token("TKN", "Proto", 0, 10.0, 0, 0.0, 100000)
        self.assertAlmostEqual(t.annual_reward_usd, 0.0)

    def test_zero_price(self):
        t = track_token("TKN", "Proto", 1000, 0.0, 0, 0.0, 100000)
        self.assertAlmostEqual(t.annual_reward_usd, 0.0)


class TestVestingDiscountField(unittest.TestCase):
    def test_six_months(self):
        t = track_token("TKN", "Proto", 1000, 5.0, 6, 0.0, 100000)
        self.assertAlmostEqual(t.vesting_discount_pct, 12.0)

    def test_zero_months(self):
        t = track_token("TKN", "Proto", 1000, 5.0, 0, 0.0, 100000)
        self.assertAlmostEqual(t.vesting_discount_pct, 0.0)


class TestNetRewardUsd(unittest.TestCase):
    def test_no_vesting(self):
        t = track_token("TKN", "Proto", 1000, 5.0, 0, 0.0, 100000)
        self.assertAlmostEqual(t.net_reward_usd, 5000.0)

    def test_six_months_vesting(self):
        # annual = 5000, vesting_disc = 12% → net = 5000 * 0.88 = 4400
        t = track_token("TKN", "Proto", 1000, 5.0, 6, 0.0, 100000)
        self.assertAlmostEqual(t.net_reward_usd, 5000.0 * 0.88)

    def test_max_vesting_half_net(self):
        # 25+ months → 50% discount → net = annual * 0.5
        t = track_token("TKN", "Proto", 1000, 5.0, 25, 0.0, 100000)
        self.assertAlmostEqual(t.net_reward_usd, 5000.0 * 0.50)


class TestVolatilityDiscountField(unittest.TestCase):
    def test_eighty_pct_vol(self):
        t = track_token("TKN", "Proto", 1000, 5.0, 0, 80.0, 100000)
        self.assertAlmostEqual(t.volatility_discount_pct, 24.0)

    def test_zero_vol(self):
        t = track_token("TKN", "Proto", 1000, 5.0, 0, 0.0, 100000)
        self.assertAlmostEqual(t.volatility_discount_pct, 0.0)


class TestRiskAdjustedRewardUsd(unittest.TestCase):
    def test_no_discounts(self):
        t = track_token("TKN", "Proto", 1000, 5.0, 0, 0.0, 100000)
        self.assertAlmostEqual(t.risk_adjusted_reward_usd, 5000.0)

    def test_vol_discount_only(self):
        # annual=5000, no vesting, 80% vol → vol_disc=24% → risk_adj=5000*0.76=3800
        t = track_token("TKN", "Proto", 1000, 5.0, 0, 80.0, 100000)
        self.assertAlmostEqual(t.risk_adjusted_reward_usd, 5000.0 * 0.76)

    def test_both_discounts(self):
        # annual=5000, 6mo vesting (12%), 80%vol (24%)
        # net = 5000 * 0.88 = 4400; risk_adj = 4400 * 0.76 = 3344
        t = track_token("TKN", "Proto", 1000, 5.0, 6, 80.0, 100000)
        self.assertAlmostEqual(t.risk_adjusted_reward_usd, 5000.0 * 0.88 * 0.76)

    def test_max_both_discounts(self):
        # 25mo vesting (50%) + 200% vol (50%) → net=annual*0.5 → risk_adj=net*0.5=annual*0.25
        t = track_token("TKN", "Proto", 1000, 5.0, 25, 200.0, 100000)
        self.assertAlmostEqual(t.risk_adjusted_reward_usd, 5000.0 * 0.25)


class TestRiskAdjustedApyContribution(unittest.TestCase):
    def test_basic(self):
        # risk_adj=5000, position=100000 → 5%
        t = track_token("TKN", "Proto", 1000, 5.0, 0, 0.0, 100000)
        self.assertAlmostEqual(t.risk_adjusted_apy_contribution_pct, 5.0)

    def test_zero_position_size(self):
        t = track_token("TKN", "Proto", 1000, 5.0, 0, 0.0, 0)
        self.assertAlmostEqual(t.risk_adjusted_apy_contribution_pct, 0.0)

    def test_small_position(self):
        # risk_adj=5000, position=50000 → 10%
        t = track_token("TKN", "Proto", 1000, 5.0, 0, 0.0, 50000)
        self.assertAlmostEqual(t.risk_adjusted_apy_contribution_pct, 10.0)


class TestTokenLabel(unittest.TestCase):
    def test_high_value(self):
        self.assertEqual(token_label(2.0), "HIGH_VALUE")

    def test_high_value_above(self):
        self.assertEqual(token_label(5.0), "HIGH_VALUE")

    def test_moderate_value_lower(self):
        self.assertEqual(token_label(0.5), "MODERATE_VALUE")

    def test_moderate_value_upper(self):
        self.assertEqual(token_label(1.99), "MODERATE_VALUE")

    def test_low_value(self):
        self.assertEqual(token_label(0.4), "LOW_VALUE")

    def test_low_value_zero(self):
        self.assertEqual(token_label(0.0), "LOW_VALUE")


class TestIsHighValue(unittest.TestCase):
    def test_high_value_true(self):
        t = track_token("TKN", "Proto", 1000, 5.0, 0, 0.0, 100000)
        # 5% → HIGH_VALUE
        self.assertTrue(t.is_high_value)

    def test_low_value_not_high(self):
        # Very small reward relative to position → LOW_VALUE
        t = track_token("TKN", "Proto", 1, 0.01, 0, 0.0, 1000000)
        self.assertFalse(t.is_high_value)


class TestRecommendations(unittest.TestCase):
    def test_high_value_recommendation(self):
        # 5% → HIGH_VALUE
        t = track_token("TKN", "Proto", 1000, 5.0, 0, 0.0, 100000)
        self.assertIn("High-value", t.recommendation)
        self.assertIn("reinvesting", t.recommendation)

    def test_moderate_value_recommendation(self):
        # 1000 tokens * $1 / $100,000 position = 1% → MODERATE_VALUE (no discounts)
        t = track_token("TKN", "Proto", 1000, 1.0, 0, 0.0, 100000)
        self.assertIn("Moderate", t.recommendation)
        self.assertIn("token price", t.recommendation)

    def test_low_value_recommendation(self):
        # near-zero → LOW_VALUE
        t = track_token("TKN", "Proto", 1, 0.01, 0, 0.0, 1000000)
        self.assertIn("Low reward", t.recommendation)
        self.assertIn("emission rate", t.recommendation)


class TestRewardQualityLabel(unittest.TestCase):
    def test_high_quality(self):
        self.assertEqual(reward_quality_label(75, 100), "HIGH_QUALITY")

    def test_high_quality_exactly_70(self):
        self.assertEqual(reward_quality_label(70, 100), "HIGH_QUALITY")

    def test_medium_quality(self):
        self.assertEqual(reward_quality_label(55, 100), "MEDIUM_QUALITY")

    def test_medium_quality_exactly_40(self):
        self.assertEqual(reward_quality_label(40, 100), "MEDIUM_QUALITY")

    def test_low_quality(self):
        self.assertEqual(reward_quality_label(30, 100), "LOW_QUALITY")

    def test_zero_gross_defaults_to_high(self):
        self.assertEqual(reward_quality_label(0, 0), "HIGH_QUALITY")

    def test_medium_quality_between(self):
        self.assertEqual(reward_quality_label(50, 100), "MEDIUM_QUALITY")


class TestTrackPortfolioAggregation(unittest.TestCase):
    def _two_tokens(self):
        return [
            {
                "token_symbol": "AAVE",
                "protocol": "Aave",
                "tokens_earned_per_year": 500,
                "token_price_usd": 10.0,
                "vesting_months": 0,
                "token_volatility_pct": 80.0,
                "position_size_usd": 100000,
            },
            {
                "token_symbol": "COMP",
                "protocol": "Compound",
                "tokens_earned_per_year": 200,
                "token_price_usd": 50.0,
                "vesting_months": 3,
                "token_volatility_pct": 60.0,
                "position_size_usd": 50000,
            },
        ]

    def test_total_annual_reward_usd(self):
        result = track_portfolio(self._two_tokens())
        # AAVE: 500*10=5000; COMP: 200*50=10000
        self.assertAlmostEqual(result.total_annual_reward_usd, 15000.0)

    def test_total_risk_adjusted_usd(self):
        result = track_portfolio(self._two_tokens())
        # AAVE: 5000*0.76 = 3800; COMP: 10000*0.94*0.82 = 7708
        aave_ra = 5000.0 * (1 - 0.0) * (1 - 24.0 / 100.0)  # no vesting
        comp_ra = 10000.0 * (1 - 6.0 / 100.0) * (1 - 18.0 / 100.0)  # 3mo=6%, 60*0.3=18%
        self.assertAlmostEqual(result.total_risk_adjusted_usd, aave_ra + comp_ra, places=2)

    def test_top_reward_token(self):
        result = track_portfolio(self._two_tokens())
        # COMP has higher risk-adjusted; verify it's a string
        self.assertIsInstance(result.top_reward_token, str)
        self.assertIn(result.top_reward_token, ["AAVE", "COMP"])

    def test_high_value_tokens_list(self):
        result = track_portfolio(self._two_tokens())
        self.assertIsInstance(result.high_value_tokens, list)

    def test_total_risk_adjusted_apy_pct(self):
        result = track_portfolio(self._two_tokens())
        self.assertGreater(result.total_risk_adjusted_apy_pct, 0.0)

    def test_reward_quality_label_valid(self):
        result = track_portfolio(self._two_tokens())
        self.assertIn(result.reward_quality_label, ("HIGH_QUALITY", "MEDIUM_QUALITY", "LOW_QUALITY"))

    def test_recommendation_summary_non_empty(self):
        result = track_portfolio(self._two_tokens())
        self.assertIsInstance(result.recommendation_summary, str)
        self.assertGreater(len(result.recommendation_summary), 0)

    def test_empty_portfolio(self):
        result = track_portfolio([])
        self.assertAlmostEqual(result.total_annual_reward_usd, 0.0)
        self.assertAlmostEqual(result.total_risk_adjusted_usd, 0.0)
        self.assertEqual(result.top_reward_token, "")
        self.assertEqual(result.high_value_tokens, [])
        self.assertAlmostEqual(result.total_risk_adjusted_apy_pct, 0.0)

    def test_top_reward_token_is_max_risk_adjusted(self):
        data = [
            {
                "token_symbol": "AAA",
                "protocol": "P1",
                "tokens_earned_per_year": 10000,
                "token_price_usd": 1.0,
                "vesting_months": 0,
                "token_volatility_pct": 0.0,
                "position_size_usd": 100000,
            },
            {
                "token_symbol": "BBB",
                "protocol": "P2",
                "tokens_earned_per_year": 1,
                "token_price_usd": 1.0,
                "vesting_months": 0,
                "token_volatility_pct": 0.0,
                "position_size_usd": 100000,
            },
        ]
        result = track_portfolio(data)
        self.assertEqual(result.top_reward_token, "AAA")

    def test_high_value_tokens_correct(self):
        data = [
            {
                "token_symbol": "HIGH",
                "protocol": "P",
                "tokens_earned_per_year": 10000,
                "token_price_usd": 1.0,
                "vesting_months": 0,
                "token_volatility_pct": 0.0,
                "position_size_usd": 100000,   # 10% contribution → HIGH_VALUE
            },
            {
                "token_symbol": "LOW",
                "protocol": "P",
                "tokens_earned_per_year": 1,
                "token_price_usd": 0.01,
                "vesting_months": 0,
                "token_volatility_pct": 0.0,
                "position_size_usd": 100000,   # negligible → LOW_VALUE
            },
        ]
        result = track_portfolio(data)
        self.assertIn("HIGH", result.high_value_tokens)
        self.assertNotIn("LOW", result.high_value_tokens)


class TestSaveLoadRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "reward_test_log.json")

    def _make_result(self):
        data = [
            {
                "token_symbol": "AAVE",
                "protocol": "Aave",
                "tokens_earned_per_year": 500,
                "token_price_usd": 10.0,
                "vesting_months": 0,
                "token_volatility_pct": 80.0,
                "position_size_usd": 100000,
            }
        ]
        return track_portfolio(data)

    def test_save_creates_file(self):
        result = self._make_result()
        save_results(result, self.log_file)
        self.assertTrue(os.path.exists(self.log_file))

    def test_save_updates_saved_to(self):
        result = self._make_result()
        save_results(result, self.log_file)
        self.assertEqual(result.saved_to, self.log_file)

    def test_load_returns_list(self):
        result = self._make_result()
        save_results(result, self.log_file)
        history = load_history(self.log_file)
        self.assertIsInstance(history, list)
        self.assertEqual(len(history), 1)

    def test_load_nonexistent_returns_empty(self):
        history = load_history(os.path.join(self.tmp_dir, "nonexistent.json"))
        self.assertEqual(history, [])

    def test_multiple_saves_accumulate(self):
        for _ in range(3):
            save_results(self._make_result(), self.log_file)
        history = load_history(self.log_file)
        self.assertEqual(len(history), 3)

    def test_ring_buffer_cap_100(self):
        for _ in range(105):
            save_results(self._make_result(), self.log_file)
        history = load_history(self.log_file)
        self.assertEqual(len(history), 100)

    def test_round_trip_data_integrity(self):
        result = self._make_result()
        save_results(result, self.log_file)
        history = load_history(self.log_file)
        self.assertEqual(history[0]["reward_quality_label"], result.reward_quality_label)
        self.assertAlmostEqual(
            history[0]["total_annual_reward_usd"],
            result.total_annual_reward_usd,
        )


class TestEdgeCases(unittest.TestCase):
    def test_zero_tokens_zero_rewards(self):
        t = track_token("TKN", "P", 0, 0.0, 0, 0.0, 100000)
        self.assertAlmostEqual(t.annual_reward_usd, 0.0)
        self.assertAlmostEqual(t.net_reward_usd, 0.0)
        self.assertAlmostEqual(t.risk_adjusted_reward_usd, 0.0)
        self.assertAlmostEqual(t.risk_adjusted_apy_contribution_pct, 0.0)

    def test_fully_vested_and_high_vol_significant_haircut(self):
        # 25mo vesting → 50% disc; 200% vol → 50% disc
        # gross = 10000, net = 5000, risk_adj = 2500
        t = track_token("TKN", "P", 2000, 5.0, 25, 200.0, 100000)
        self.assertAlmostEqual(t.annual_reward_usd, 10000.0)
        self.assertAlmostEqual(t.vesting_discount_pct, 50.0)
        self.assertAlmostEqual(t.volatility_discount_pct, 50.0)
        self.assertAlmostEqual(t.risk_adjusted_reward_usd, 2500.0)
        # 2500/100000*100 = 2.5% → HIGH_VALUE
        self.assertAlmostEqual(t.risk_adjusted_apy_contribution_pct, 2.5)
        self.assertEqual(t.token_label, "HIGH_VALUE")

    def test_token_symbol_stored(self):
        t = track_token("MORPHO", "Morpho", 100, 2.0, 0, 0.0, 50000)
        self.assertEqual(t.token_symbol, "MORPHO")
        self.assertEqual(t.protocol, "Morpho")

    def test_empty_portfolio_no_crash(self):
        result = track_portfolio([])
        self.assertEqual(result.recommendation_summary, "No reward tokens tracked.")


if __name__ == "__main__":
    unittest.main()
