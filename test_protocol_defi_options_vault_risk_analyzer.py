"""
Tests for ProtocolDeFiOptionsVaultRiskAnalyzer (MP-1083).
Run: python3 -m unittest spa_core.tests.test_protocol_defi_options_vault_risk_analyzer
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_defi_options_vault_risk_analyzer import (
    ProtocolDeFiOptionsVaultRiskAnalyzer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_data(**overrides):
    """Return a well-formed options vault data dict with sensible defaults."""
    base = {
        "vault_name": "Ribbon ETH Covered Call",
        "strategy": "covered_call",
        "underlying_asset": "ETH",
        "strike_price_usd": 3_500.0,
        "current_price_usd": 3_000.0,
        "premium_apy_pct": 20.0,
        "expiry_days": 7.0,
        "implied_volatility_pct": 60.0,
        "delta": 0.3,
        "historical_win_rate_pct": 75.0,
        "max_loss_scenario_pct": 30.0,
    }
    base.update(overrides)
    return base


def _make_analyzer(tmp_dir=None):
    log_path = os.path.join(tmp_dir, "options_log.json") if tmp_dir else None
    return ProtocolDeFiOptionsVaultRiskAnalyzer(log_path=log_path)


# ===========================================================================
# 1. Output Structure
# ===========================================================================

class TestOutputStructure(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiOptionsVaultRiskAnalyzer()

    def test_returns_dict(self):
        self.assertIsInstance(self.a.analyze(_base_data()), dict)

    def test_all_required_keys_present(self):
        result = self.a.analyze(_base_data())
        required = {
            "vault_name", "strategy", "underlying_asset",
            "breakeven_price_usd", "annualized_premium_pct",
            "risk_reward_ratio", "tail_risk_score", "vault_label",
        }
        self.assertEqual(required, required & result.keys())

    def test_vault_name_passthrough(self):
        r = self.a.analyze(_base_data(vault_name="TestVault"))
        self.assertEqual(r["vault_name"], "TestVault")

    def test_strategy_passthrough(self):
        r = self.a.analyze(_base_data(strategy="covered_call"))
        self.assertEqual(r["strategy"], "covered_call")

    def test_underlying_asset_passthrough(self):
        r = self.a.analyze(_base_data(underlying_asset="BTC"))
        self.assertEqual(r["underlying_asset"], "BTC")

    def test_tail_risk_score_in_range(self):
        r = self.a.analyze(_base_data())
        self.assertGreaterEqual(r["tail_risk_score"], 0.0)
        self.assertLessEqual(r["tail_risk_score"], 100.0)

    def test_label_is_valid_string(self):
        valid = {
            "CONSERVATIVE_VAULT", "BALANCED_RISK", "ELEVATED_RISK",
            "HIGH_TAIL_RISK", "AVOID_VAULT",
        }
        r = self.a.analyze(_base_data())
        self.assertIn(r["vault_label"], valid)

    def test_numeric_outputs_are_floats(self):
        r = self.a.analyze(_base_data())
        for key in ("breakeven_price_usd", "annualized_premium_pct",
                    "risk_reward_ratio", "tail_risk_score"):
            self.assertIsInstance(r[key], float, msg=key)

    def test_breakeven_non_negative(self):
        self.assertGreaterEqual(self.a.analyze(_base_data())["breakeven_price_usd"], 0.0)

    def test_risk_reward_non_negative(self):
        self.assertGreaterEqual(self.a.analyze(_base_data())["risk_reward_ratio"], 0.0)


# ===========================================================================
# 2. Breakeven Price
# ===========================================================================

class TestBreakevenPrice(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiOptionsVaultRiskAnalyzer()

    def test_covered_call_basic(self):
        # period_premium = 20% * (7/365) * 3000 = 11.51
        # breakeven = 3000 - 11.51 = 2988.49
        r = self.a.analyze(_base_data(
            strategy="covered_call",
            current_price_usd=3_000.0,
            premium_apy_pct=20.0,
            expiry_days=7.0,
        ))
        expected_premium = 3_000.0 * (20.0 * (7.0 / 365.0) / 100.0)
        expected_be = 3_000.0 - expected_premium
        self.assertAlmostEqual(r["breakeven_price_usd"], expected_be, places=2)

    def test_covered_call_breakeven_below_current(self):
        r = self.a.analyze(_base_data(strategy="covered_call"))
        self.assertLess(r["breakeven_price_usd"], 3_000.0)

    def test_cash_secured_put_basic(self):
        # premium_abs = strike * period_premium%; breakeven = strike - premium_abs
        r = self.a.analyze(_base_data(
            strategy="cash_secured_put",
            strike_price_usd=3_000.0,
            current_price_usd=3_000.0,
            premium_apy_pct=20.0,
            expiry_days=7.0,
        ))
        premium_pct_period = 20.0 * (7.0 / 365.0) / 100.0
        expected_be = 3_000.0 - 3_000.0 * premium_pct_period
        self.assertAlmostEqual(r["breakeven_price_usd"], expected_be, places=2)

    def test_strangle_uses_lower_of_strike_current(self):
        # strike=3500, current=3000 → lower=3000
        r = self.a.analyze(_base_data(strategy="strangle", strike_price_usd=3_500, current_price_usd=3_000))
        self.assertLessEqual(r["breakeven_price_usd"], 3_000.0)

    def test_zero_current_price_zero_breakeven(self):
        r = self.a.analyze(_base_data(current_price_usd=0))
        self.assertEqual(r["breakeven_price_usd"], 0.0)

    def test_zero_expiry_no_premium(self):
        r = self.a.analyze(_base_data(expiry_days=0))
        # No time → no premium → breakeven = current
        self.assertAlmostEqual(r["breakeven_price_usd"], 3_000.0, places=1)

    def test_breakeven_non_negative(self):
        r = self.a.analyze(_base_data(premium_apy_pct=10_000.0, expiry_days=365))
        self.assertGreaterEqual(r["breakeven_price_usd"], 0.0)

    def test_higher_premium_lower_breakeven(self):
        r_low = self.a.analyze(_base_data(premium_apy_pct=5.0))
        r_high = self.a.analyze(_base_data(premium_apy_pct=40.0))
        self.assertGreater(r_low["breakeven_price_usd"], r_high["breakeven_price_usd"])

    def test_longer_expiry_lower_breakeven(self):
        r_short = self.a.analyze(_base_data(expiry_days=7))
        r_long = self.a.analyze(_base_data(expiry_days=30))
        self.assertGreater(r_short["breakeven_price_usd"], r_long["breakeven_price_usd"])

    def test_unknown_strategy_uses_strike(self):
        r = self.a.analyze(_base_data(strategy="butterfly", strike_price_usd=3_200, current_price_usd=3_000))
        # Generic path: breakeven = strike - premium_abs (based on current)
        self.assertLessEqual(r["breakeven_price_usd"], 3_200.0)


# ===========================================================================
# 3. Annualized Premium
# ===========================================================================

class TestAnnualizedPremium(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiOptionsVaultRiskAnalyzer()

    def test_premium_passthrough(self):
        r = self.a.analyze(_base_data(premium_apy_pct=25.0))
        self.assertAlmostEqual(r["annualized_premium_pct"], 25.0, places=4)

    def test_zero_premium(self):
        r = self.a.analyze(_base_data(premium_apy_pct=0.0))
        self.assertAlmostEqual(r["annualized_premium_pct"], 0.0, places=4)

    def test_high_premium(self):
        r = self.a.analyze(_base_data(premium_apy_pct=200.0))
        self.assertAlmostEqual(r["annualized_premium_pct"], 200.0, places=4)

    def test_fractional_premium(self):
        r = self.a.analyze(_base_data(premium_apy_pct=3.75))
        self.assertAlmostEqual(r["annualized_premium_pct"], 3.75, places=4)

    def test_premium_is_float(self):
        r = self.a.analyze(_base_data(premium_apy_pct=10))
        self.assertIsInstance(r["annualized_premium_pct"], float)

    def test_premium_string_numeric(self):
        r = self.a.analyze(_base_data(premium_apy_pct="15.5"))
        self.assertAlmostEqual(r["annualized_premium_pct"], 15.5, places=4)

    def test_typical_eth_call_vault(self):
        r = self.a.analyze(_base_data(premium_apy_pct=20.0))
        self.assertAlmostEqual(r["annualized_premium_pct"], 20.0, places=4)

    def test_very_small_premium(self):
        r = self.a.analyze(_base_data(premium_apy_pct=0.01))
        self.assertAlmostEqual(r["annualized_premium_pct"], 0.01, places=6)

    def test_large_premium(self):
        r = self.a.analyze(_base_data(premium_apy_pct=500.0))
        self.assertAlmostEqual(r["annualized_premium_pct"], 500.0, places=4)

    def test_premium_independent_of_expiry(self):
        r7 = self.a.analyze(_base_data(premium_apy_pct=20.0, expiry_days=7))
        r30 = self.a.analyze(_base_data(premium_apy_pct=20.0, expiry_days=30))
        self.assertAlmostEqual(r7["annualized_premium_pct"], r30["annualized_premium_pct"], places=4)


# ===========================================================================
# 4. Risk-Reward Ratio
# ===========================================================================

class TestRiskRewardRatio(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiOptionsVaultRiskAnalyzer()

    def test_basic_ratio(self):
        # period_premium = 20 * (7/365) = 0.3836%
        # max_loss = 30%; ratio = 0.3836/30 = 0.01279
        r = self.a.analyze(_base_data(premium_apy_pct=20.0, expiry_days=7, max_loss_scenario_pct=30.0))
        period_pct = 20.0 * (7.0 / 365.0)
        expected = period_pct / 30.0
        self.assertAlmostEqual(r["risk_reward_ratio"], min(10.0, expected), places=4)

    def test_zero_max_loss_high_ratio(self):
        r = self.a.analyze(_base_data(max_loss_scenario_pct=0.0, premium_apy_pct=20.0))
        self.assertGreater(r["risk_reward_ratio"], 0.0)

    def test_higher_premium_better_ratio(self):
        r_low = self.a.analyze(_base_data(premium_apy_pct=5.0, max_loss_scenario_pct=30.0))
        r_high = self.a.analyze(_base_data(premium_apy_pct=40.0, max_loss_scenario_pct=30.0))
        self.assertGreater(r_high["risk_reward_ratio"], r_low["risk_reward_ratio"])

    def test_higher_loss_worse_ratio(self):
        r_low = self.a.analyze(_base_data(max_loss_scenario_pct=10.0))
        r_high = self.a.analyze(_base_data(max_loss_scenario_pct=80.0))
        self.assertGreater(r_low["risk_reward_ratio"], r_high["risk_reward_ratio"])

    def test_ratio_capped_at_10(self):
        # Tiny loss, large premium → ratio capped at 10
        r = self.a.analyze(_base_data(premium_apy_pct=365.0, expiry_days=1, max_loss_scenario_pct=0.01))
        self.assertLessEqual(r["risk_reward_ratio"], 10.0)

    def test_ratio_non_negative(self):
        r = self.a.analyze(_base_data())
        self.assertGreaterEqual(r["risk_reward_ratio"], 0.0)

    def test_zero_premium_zero_ratio(self):
        r = self.a.analyze(_base_data(premium_apy_pct=0.0, max_loss_scenario_pct=30.0))
        self.assertAlmostEqual(r["risk_reward_ratio"], 0.0, places=4)

    def test_longer_expiry_higher_ratio_all_else_equal(self):
        r_short = self.a.analyze(_base_data(expiry_days=7, max_loss_scenario_pct=20.0))
        r_long = self.a.analyze(_base_data(expiry_days=30, max_loss_scenario_pct=20.0))
        self.assertGreater(r_long["risk_reward_ratio"], r_short["risk_reward_ratio"])

    def test_ratio_is_float(self):
        r = self.a.analyze(_base_data())
        self.assertIsInstance(r["risk_reward_ratio"], float)

    def test_ratio_100pct_max_loss(self):
        r = self.a.analyze(_base_data(max_loss_scenario_pct=100.0, premium_apy_pct=20.0, expiry_days=30))
        period_pct = 20.0 * (30.0 / 365.0)
        expected = period_pct / 100.0
        self.assertAlmostEqual(r["risk_reward_ratio"], min(10.0, expected), places=4)


# ===========================================================================
# 5. Tail Risk Score
# ===========================================================================

class TestTailRiskScore(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiOptionsVaultRiskAnalyzer()

    def test_high_iv_raises_score(self):
        r_low = self.a.analyze(_base_data(implied_volatility_pct=20.0))
        r_high = self.a.analyze(_base_data(implied_volatility_pct=120.0))
        self.assertGreater(r_high["tail_risk_score"], r_low["tail_risk_score"])

    def test_low_win_rate_raises_score(self):
        r_good = self.a.analyze(_base_data(historical_win_rate_pct=90.0))
        r_bad = self.a.analyze(_base_data(historical_win_rate_pct=30.0))
        self.assertGreater(r_bad["tail_risk_score"], r_good["tail_risk_score"])

    def test_high_max_loss_raises_score(self):
        r_low = self.a.analyze(_base_data(max_loss_scenario_pct=10.0))
        r_high = self.a.analyze(_base_data(max_loss_scenario_pct=80.0))
        self.assertGreater(r_high["tail_risk_score"], r_low["tail_risk_score"])

    def test_high_delta_raises_score(self):
        r_low = self.a.analyze(_base_data(delta=0.1))
        r_high = self.a.analyze(_base_data(delta=0.9))
        self.assertGreater(r_high["tail_risk_score"], r_low["tail_risk_score"])

    def test_strangle_higher_than_covered_call(self):
        r_cc = self.a.analyze(_base_data(strategy="covered_call"))
        r_st = self.a.analyze(_base_data(strategy="strangle"))
        self.assertGreater(r_st["tail_risk_score"], r_cc["tail_risk_score"])

    def test_negative_delta_same_magnitude_as_positive(self):
        r_pos = self.a.analyze(_base_data(delta=0.5))
        r_neg = self.a.analyze(_base_data(delta=-0.5))
        self.assertAlmostEqual(r_pos["tail_risk_score"], r_neg["tail_risk_score"], places=3)

    def test_score_bounded_zero_to_100(self):
        for iv, wrate, loss, delta in [
            (0, 100, 0, 0), (200, 0, 100, 1), (50, 75, 30, 0.3)
        ]:
            r = self.a.analyze(_base_data(
                implied_volatility_pct=iv, historical_win_rate_pct=wrate,
                max_loss_scenario_pct=loss, delta=delta
            ))
            self.assertGreaterEqual(r["tail_risk_score"], 0.0)
            self.assertLessEqual(r["tail_risk_score"], 100.0)

    def test_ideal_vault_low_risk(self):
        # Very low IV, high win rate, minimal loss, tiny delta
        r = self.a.analyze(_base_data(
            implied_volatility_pct=5.0, historical_win_rate_pct=95.0,
            max_loss_scenario_pct=3.0, delta=0.05, strategy="covered_call",
            premium_apy_pct=30.0
        ))
        self.assertLess(r["tail_risk_score"], 40.0)

    def test_worst_case_vault_high_risk(self):
        # High IV, low win rate, large max loss, high delta, strangle
        r = self.a.analyze(_base_data(
            implied_volatility_pct=150.0, historical_win_rate_pct=20.0,
            max_loss_scenario_pct=90.0, delta=0.9, strategy="strangle",
            premium_apy_pct=5.0
        ))
        self.assertGreater(r["tail_risk_score"], 60.0)

    def test_iron_condor_discount(self):
        # iron_condor has defined risk → score slightly lower than covered_call same params
        r_cc = self.a.analyze(_base_data(strategy="covered_call"))
        r_ic = self.a.analyze(_base_data(strategy="iron_condor"))
        self.assertGreaterEqual(r_cc["tail_risk_score"], r_ic["tail_risk_score"])

    def test_zero_iv_reduces_score(self):
        r_iv0 = self.a.analyze(_base_data(implied_volatility_pct=0.0))
        r_iv80 = self.a.analyze(_base_data(implied_volatility_pct=80.0))
        self.assertLess(r_iv0["tail_risk_score"], r_iv80["tail_risk_score"])

    def test_premium_cushion_reduces_score(self):
        r_low_prem = self.a.analyze(_base_data(premium_apy_pct=1.0))
        r_high_prem = self.a.analyze(_base_data(premium_apy_pct=60.0))
        self.assertGreaterEqual(r_low_prem["tail_risk_score"], r_high_prem["tail_risk_score"])

    def test_score_is_float(self):
        r = self.a.analyze(_base_data())
        self.assertIsInstance(r["tail_risk_score"], float)

    def test_naked_call_adds_risk(self):
        r_cc = self.a.analyze(_base_data(strategy="covered_call"))
        r_nc = self.a.analyze(_base_data(strategy="naked_call"))
        self.assertGreater(r_nc["tail_risk_score"], r_cc["tail_risk_score"])

    def test_win_rate_100_reduces_score_component(self):
        r = self.a.analyze(_base_data(historical_win_rate_pct=100.0))
        r_bad = self.a.analyze(_base_data(historical_win_rate_pct=0.0))
        self.assertLess(r["tail_risk_score"], r_bad["tail_risk_score"])


# ===========================================================================
# 6. Vault Labels
# ===========================================================================

class TestVaultLabels(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiOptionsVaultRiskAnalyzer()

    def _label_for_score(self, score):
        return ProtocolDeFiOptionsVaultRiskAnalyzer._assign_label(score)

    def test_score_0_conservative(self):
        self.assertEqual(self._label_for_score(0.0), "CONSERVATIVE_VAULT")

    def test_score_20_conservative(self):
        self.assertEqual(self._label_for_score(20.0), "CONSERVATIVE_VAULT")

    def test_score_21_balanced(self):
        self.assertEqual(self._label_for_score(21.0), "BALANCED_RISK")

    def test_score_40_balanced(self):
        self.assertEqual(self._label_for_score(40.0), "BALANCED_RISK")

    def test_score_41_elevated(self):
        self.assertEqual(self._label_for_score(41.0), "ELEVATED_RISK")

    def test_score_60_elevated(self):
        self.assertEqual(self._label_for_score(60.0), "ELEVATED_RISK")

    def test_score_61_high_tail_risk(self):
        self.assertEqual(self._label_for_score(61.0), "HIGH_TAIL_RISK")

    def test_score_80_high_tail_risk(self):
        self.assertEqual(self._label_for_score(80.0), "HIGH_TAIL_RISK")

    def test_score_81_avoid(self):
        self.assertEqual(self._label_for_score(81.0), "AVOID_VAULT")

    def test_score_100_avoid(self):
        self.assertEqual(self._label_for_score(100.0), "AVOID_VAULT")

    def test_all_valid_labels(self):
        valid = {
            "CONSERVATIVE_VAULT", "BALANCED_RISK", "ELEVATED_RISK",
            "HIGH_TAIL_RISK", "AVOID_VAULT",
        }
        for iv in [5, 30, 60, 90, 150]:
            for loss in [5, 30, 60, 90]:
                r = self.a.analyze(_base_data(
                    implied_volatility_pct=iv, max_loss_scenario_pct=loss
                ))
                self.assertIn(r["vault_label"], valid)

    def test_low_risk_params_conservative_or_balanced(self):
        r = self.a.analyze(_base_data(
            implied_volatility_pct=10, historical_win_rate_pct=90,
            max_loss_scenario_pct=5, delta=0.05,
            strategy="covered_call", premium_apy_pct=40.0
        ))
        self.assertIn(r["vault_label"], {"CONSERVATIVE_VAULT", "BALANCED_RISK"})

    def test_high_risk_params_avoid_or_high(self):
        r = self.a.analyze(_base_data(
            implied_volatility_pct=150, historical_win_rate_pct=10,
            max_loss_scenario_pct=90, delta=0.95,
            strategy="strangle", premium_apy_pct=5.0
        ))
        self.assertIn(r["vault_label"], {"AVOID_VAULT", "HIGH_TAIL_RISK"})

    def test_exact_boundary_20(self):
        self.assertEqual(self._label_for_score(20.0), "CONSERVATIVE_VAULT")

    def test_exact_boundary_40(self):
        self.assertEqual(self._label_for_score(40.0), "BALANCED_RISK")

    def test_exact_boundary_60(self):
        self.assertEqual(self._label_for_score(60.0), "ELEVATED_RISK")

    def test_exact_boundary_80(self):
        self.assertEqual(self._label_for_score(80.0), "HIGH_TAIL_RISK")


# ===========================================================================
# 7. Strategy-Specific Tests
# ===========================================================================

class TestStrategies(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiOptionsVaultRiskAnalyzer()

    def test_covered_call_breakeven_formula(self):
        r = self.a.analyze(_base_data(
            strategy="covered_call",
            current_price_usd=2_000, premium_apy_pct=36.5, expiry_days=10
        ))
        # period_pct = 36.5 * (10/365) = 1.0%
        # premium_abs = 2000 * 0.01 = 20
        # breakeven = 2000 - 20 = 1980
        self.assertAlmostEqual(r["breakeven_price_usd"], 1980.0, places=2)

    def test_cash_secured_put_breakeven_formula(self):
        r = self.a.analyze(_base_data(
            strategy="cash_secured_put",
            strike_price_usd=2_800, current_price_usd=3_000,
            premium_apy_pct=36.5, expiry_days=10
        ))
        # period_pct = 36.5 * (10/365) = 1.0%
        # premium_abs = 2800 * 0.01 = 28
        # breakeven = 2800 - 28 = 2772
        self.assertAlmostEqual(r["breakeven_price_usd"], 2772.0, places=2)

    def test_strangle_breakeven_lower_than_both_prices(self):
        r = self.a.analyze(_base_data(
            strategy="strangle",
            strike_price_usd=3_500, current_price_usd=3_000,
            premium_apy_pct=20.0, expiry_days=7
        ))
        self.assertLess(r["breakeven_price_usd"], 3_000.0)

    def test_strangle_higher_risk_than_covered_call(self):
        r_cc = self.a.analyze(_base_data(strategy="covered_call"))
        r_st = self.a.analyze(_base_data(strategy="strangle"))
        self.assertGreater(r_st["tail_risk_score"], r_cc["tail_risk_score"])

    def test_put_breakeven_uses_strike_not_current(self):
        r = self.a.analyze(_base_data(
            strategy="cash_secured_put",
            strike_price_usd=2_500, current_price_usd=3_000,
            premium_apy_pct=36.5, expiry_days=10
        ))
        # breakeven = 2500 - 2500*0.01 = 2475
        self.assertAlmostEqual(r["breakeven_price_usd"], 2475.0, places=2)

    def test_unknown_strategy_no_crash(self):
        r = self.a.analyze(_base_data(strategy="iron_fly"))
        self.assertIsInstance(r, dict)

    def test_strategy_lowercase(self):
        r = self.a.analyze(_base_data(strategy="COVERED_CALL"))
        self.assertEqual(r["strategy"], "covered_call")

    def test_naked_put_risk_higher_than_cash_secured_put(self):
        r_cs = self.a.analyze(_base_data(strategy="cash_secured_put"))
        r_np = self.a.analyze(_base_data(strategy="naked_put"))
        self.assertGreater(r_np["tail_risk_score"], r_cs["tail_risk_score"])

    def test_different_strategies_same_underlying_differ_risk(self):
        strategies = ["covered_call", "cash_secured_put", "strangle"]
        scores = [
            self.a.analyze(_base_data(strategy=s))["tail_risk_score"]
            for s in strategies
        ]
        # Strangle should have highest risk among the three
        self.assertEqual(max(scores), scores[2])

    def test_iron_condor_defined_risk(self):
        r = self.a.analyze(_base_data(strategy="iron_condor"))
        self.assertIsInstance(r["tail_risk_score"], float)


# ===========================================================================
# 8. Implied Volatility
# ===========================================================================

class TestImpliedVolatility(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiOptionsVaultRiskAnalyzer()

    def test_iv_zero_lower_risk(self):
        r = self.a.analyze(_base_data(implied_volatility_pct=0.0))
        r_high = self.a.analyze(_base_data(implied_volatility_pct=100.0))
        self.assertLess(r["tail_risk_score"], r_high["tail_risk_score"])

    def test_iv_100_adds_30pts_component(self):
        r_iv0 = self.a.analyze(_base_data(
            implied_volatility_pct=0.0, historical_win_rate_pct=50.0,
            max_loss_scenario_pct=0.0, delta=0.0, premium_apy_pct=0.0
        ))
        r_iv100 = self.a.analyze(_base_data(
            implied_volatility_pct=100.0, historical_win_rate_pct=50.0,
            max_loss_scenario_pct=0.0, delta=0.0, premium_apy_pct=0.0
        ))
        diff = r_iv100["tail_risk_score"] - r_iv0["tail_risk_score"]
        self.assertAlmostEqual(diff, 30.0, delta=2.0)

    def test_iv_capped_at_100_in_score(self):
        r_100 = self.a.analyze(_base_data(implied_volatility_pct=100.0))
        r_200 = self.a.analyze(_base_data(implied_volatility_pct=200.0))
        # Both capped at 100 in IV component
        self.assertAlmostEqual(r_100["tail_risk_score"], r_200["tail_risk_score"], places=3)

    def test_monotonic_iv_risk(self):
        scores = []
        for iv in [10, 30, 50, 70, 90]:
            r = self.a.analyze(_base_data(implied_volatility_pct=iv))
            scores.append(r["tail_risk_score"])
        for i in range(len(scores) - 1):
            self.assertLessEqual(scores[i], scores[i + 1])

    def test_typical_eth_iv_60pct(self):
        r = self.a.analyze(_base_data(implied_volatility_pct=60.0))
        self.assertGreater(r["tail_risk_score"], 0.0)
        self.assertLess(r["tail_risk_score"], 100.0)


# ===========================================================================
# 9. Delta Tests
# ===========================================================================

class TestDeltaTests(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiOptionsVaultRiskAnalyzer()

    def test_delta_zero_no_directional_risk(self):
        r = self.a.analyze(_base_data(delta=0.0))
        r_ref = self.a.analyze(_base_data(delta=0.5))
        self.assertLess(r["tail_risk_score"], r_ref["tail_risk_score"])

    def test_delta_one_max_directional_risk(self):
        r0 = self.a.analyze(_base_data(delta=0.0))
        r1 = self.a.analyze(_base_data(delta=1.0))
        diff = r1["tail_risk_score"] - r0["tail_risk_score"]
        self.assertAlmostEqual(diff, 15.0, delta=2.0)

    def test_negative_delta_same_as_positive(self):
        r_pos = self.a.analyze(_base_data(delta=0.4))
        r_neg = self.a.analyze(_base_data(delta=-0.4))
        self.assertAlmostEqual(r_pos["tail_risk_score"], r_neg["tail_risk_score"], places=3)

    def test_delta_above_1_capped(self):
        r_1 = self.a.analyze(_base_data(delta=1.0))
        r_2 = self.a.analyze(_base_data(delta=2.0))
        self.assertAlmostEqual(r_1["tail_risk_score"], r_2["tail_risk_score"], places=3)

    def test_put_delta_negative(self):
        r = self.a.analyze(_base_data(strategy="cash_secured_put", delta=-0.3))
        self.assertIsInstance(r["tail_risk_score"], float)


# ===========================================================================
# 10. Edge Cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiOptionsVaultRiskAnalyzer()

    def test_empty_dict_no_crash(self):
        r = self.a.analyze({})
        self.assertIsInstance(r, dict)

    def test_all_zeros(self):
        r = self.a.analyze({
            "vault_name": "", "strategy": "covered_call", "underlying_asset": "",
            "strike_price_usd": 0, "current_price_usd": 0, "premium_apy_pct": 0,
            "expiry_days": 0, "implied_volatility_pct": 0,
            "delta": 0, "historical_win_rate_pct": 0, "max_loss_scenario_pct": 0,
        })
        self.assertGreaterEqual(r["tail_risk_score"], 0.0)

    def test_string_numeric_values(self):
        r = self.a.analyze(_base_data(
            current_price_usd="3000", premium_apy_pct="20", expiry_days="7"
        ))
        self.assertIsInstance(r["breakeven_price_usd"], float)

    def test_very_high_premium_capped_breakeven(self):
        r = self.a.analyze(_base_data(premium_apy_pct=100_000.0, expiry_days=365))
        self.assertGreaterEqual(r["breakeven_price_usd"], 0.0)

    def test_expiry_negative_treated_as_zero(self):
        r = self.a.analyze(_base_data(expiry_days=-5))
        self.assertGreaterEqual(r["breakeven_price_usd"], 0.0)

    def test_analyze_does_not_mutate_input(self):
        data = _base_data()
        original = dict(data)
        self.a.analyze(data)
        self.assertEqual(data, original)

    def test_multiple_calls_independent(self):
        r1 = self.a.analyze(_base_data(premium_apy_pct=10.0))
        r2 = self.a.analyze(_base_data(premium_apy_pct=30.0))
        self.assertNotEqual(r1["annualized_premium_pct"], r2["annualized_premium_pct"])

    def test_missing_strategy_defaults_covered_call(self):
        data = dict(_base_data())
        del data["strategy"]
        r = self.a.analyze(data)
        self.assertEqual(r["strategy"], "covered_call")

    def test_win_rate_above_100_handled(self):
        r = self.a.analyze(_base_data(historical_win_rate_pct=110.0))
        self.assertGreaterEqual(r["tail_risk_score"], 0.0)

    def test_win_rate_below_0_handled(self):
        r = self.a.analyze(_base_data(historical_win_rate_pct=-10.0))
        self.assertLessEqual(r["tail_risk_score"], 100.0)


# ===========================================================================
# 11. Logging
# ===========================================================================

class TestLogging(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "options_log.json")
        self.a = ProtocolDeFiOptionsVaultRiskAnalyzer(log_path=self.log_path)

    def test_log_file_created(self):
        self.a.analyze_and_log(_base_data())
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.a.analyze_and_log(_base_data())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_vault_label(self):
        self.a.analyze_and_log(_base_data())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("vault_label", data[0])

    def test_log_entry_has_logged_at(self):
        self.a.analyze_and_log(_base_data())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("_logged_at", data[0])

    def test_multiple_entries_accumulate(self):
        for _ in range(5):
            self.a.analyze_and_log(_base_data())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap_100(self):
        for i in range(115):
            self.a.analyze_and_log(_base_data(premium_apy_pct=float(i + 1)))
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(115):
            self.a.analyze_and_log(_base_data(premium_apy_pct=float(i + 1)))
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertAlmostEqual(data[-1]["annualized_premium_pct"], 115.0, places=2)

    def test_atomic_no_tmp_leftover(self):
        self.a.analyze_and_log(_base_data())
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_analyze_and_log_returns_same_as_analyze(self):
        r1 = self.a.analyze(_base_data())
        r2 = self.a.analyze_and_log(_base_data())
        for key in r1:
            self.assertEqual(r1[key], r2[key])

    def test_corrupt_log_recovers(self):
        with open(self.log_path, "w") as f:
            f.write("{invalid json}")
        self.a.analyze_and_log(_base_data())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


# ===========================================================================
# 12. Real-world Scenarios
# ===========================================================================

class TestRealWorldScenarios(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiOptionsVaultRiskAnalyzer()

    def test_ribbon_eth_covered_call(self):
        r = self.a.analyze({
            "vault_name": "Ribbon ETH-C",
            "strategy": "covered_call",
            "underlying_asset": "ETH",
            "strike_price_usd": 3_500.0,
            "current_price_usd": 3_000.0,
            "premium_apy_pct": 20.0,
            "expiry_days": 7.0,
            "implied_volatility_pct": 65.0,
            "delta": 0.25,
            "historical_win_rate_pct": 78.0,
            "max_loss_scenario_pct": 35.0,
        })
        self.assertIn(r["vault_label"], {
            "CONSERVATIVE_VAULT", "BALANCED_RISK", "ELEVATED_RISK"
        })

    def test_stablecoin_cash_secured_put(self):
        r = self.a.analyze({
            "vault_name": "USDC Put Vault",
            "strategy": "cash_secured_put",
            "underlying_asset": "BTC",
            "strike_price_usd": 55_000.0,
            "current_price_usd": 60_000.0,
            "premium_apy_pct": 15.0,
            "expiry_days": 14.0,
            "implied_volatility_pct": 40.0,
            "delta": -0.2,
            "historical_win_rate_pct": 82.0,
            "max_loss_scenario_pct": 25.0,
        })
        self.assertIsInstance(r["breakeven_price_usd"], float)
        self.assertLessEqual(r["breakeven_price_usd"], 55_000.0)

    def test_default_log_path_attribute(self):
        a = ProtocolDeFiOptionsVaultRiskAnalyzer()
        self.assertEqual(a.log_path, "data/options_vault_risk_log.json")

    def test_custom_log_path_attribute(self):
        a = ProtocolDeFiOptionsVaultRiskAnalyzer(log_path="/tmp/opt_test.json")
        self.assertEqual(a.log_path, "/tmp/opt_test.json")

    def test_max_log_entries_is_100(self):
        self.assertEqual(ProtocolDeFiOptionsVaultRiskAnalyzer.MAX_LOG_ENTRIES, 100)

    def test_breakeven_always_below_strike_for_covered_call(self):
        for premium in [5, 10, 20, 40]:
            r = self.a.analyze(_base_data(
                strategy="covered_call", current_price_usd=3_000,
                strike_price_usd=3_500, premium_apy_pct=float(premium), expiry_days=30
            ))
            self.assertLessEqual(r["breakeven_price_usd"], 3_000.0)

    def test_annualized_premium_equals_input_apy(self):
        for apy in [5.0, 12.5, 20.0, 50.0]:
            r = self.a.analyze(_base_data(premium_apy_pct=apy))
            self.assertAlmostEqual(r["annualized_premium_pct"], apy, places=4)

    def test_tail_risk_score_increases_with_iv(self):
        prev = -1.0
        for iv in [0, 20, 40, 60, 80, 100]:
            r = self.a.analyze(_base_data(implied_volatility_pct=float(iv)))
            self.assertGreaterEqual(r["tail_risk_score"], prev)
            prev = r["tail_risk_score"]

    def test_strangle_with_low_win_rate_avoid(self):
        r = self.a.analyze(_base_data(
            strategy="strangle",
            implied_volatility_pct=100.0,
            historical_win_rate_pct=20.0,
            max_loss_scenario_pct=80.0,
            delta=0.5,
        ))
        self.assertIn(r["vault_label"], {"AVOID_VAULT", "HIGH_TAIL_RISK"})


if __name__ == "__main__":
    unittest.main()
