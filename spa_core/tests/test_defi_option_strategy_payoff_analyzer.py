"""
Tests for MP-936: DeFiOptionStrategyPayoffAnalyzer
≥80 tests covering payoff computation, breakevens, flags, aggregates,
validation, log write, and edge cases.
Run: python3 -m unittest spa_core.tests.test_defi_option_strategy_payoff_analyzer
"""

import json
import math
import os
import tempfile
import unittest

from spa_core.analytics.defi_option_strategy_payoff_analyzer import (
    DeFiOptionStrategyPayoffAnalyzer,
    _leg_payoff_at_price,
    _strategy_payoff_at_price,
    _find_breakevens,
    _compute_net_premium,
    _probability_of_profit_v2,
    _risk_reward_ratio,
    _compute_flags,
    _validate_strategy,
    _analyze_single_strategy,
    _compute_aggregates,
    _atomic_write,
    _append_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _long_call(strike=100.0, premium=5.0, qty=1.0):
    return {"option_type": "call", "strike": strike,
            "premium_usd": premium, "quantity": qty, "direction": "long"}

def _short_call(strike=110.0, premium=3.0, qty=1.0):
    return {"option_type": "call", "strike": strike,
            "premium_usd": premium, "quantity": qty, "direction": "short"}

def _long_put(strike=100.0, premium=5.0, qty=1.0):
    return {"option_type": "put", "strike": strike,
            "premium_usd": premium, "quantity": qty, "direction": "long"}

def _short_put(strike=90.0, premium=3.0, qty=1.0):
    return {"option_type": "put", "strike": strike,
            "premium_usd": premium, "quantity": qty, "direction": "short"}


def _covered_call_strategy(underlying=100.0, expiry=30):
    return {
        "name": "MyCoveredCall",
        "strategy_type": "covered_call",
        "legs": [_short_call(strike=110.0, premium=3.0)],
        "underlying_price_usd": underlying,
        "expiry_days": expiry,
    }

def _protective_put_strategy(underlying=100.0, expiry=30):
    return {
        "name": "MyProtectivePut",
        "strategy_type": "protective_put",
        "legs": [_long_put(strike=95.0, premium=4.0)],
        "underlying_price_usd": underlying,
        "expiry_days": expiry,
    }

def _straddle_strategy(underlying=100.0, expiry=30):
    return {
        "name": "MyStraddle",
        "strategy_type": "straddle",
        "legs": [
            _long_call(strike=100.0, premium=5.0),
            _long_put(strike=100.0, premium=5.0),
        ],
        "underlying_price_usd": underlying,
        "expiry_days": expiry,
    }

def _strangle_strategy(underlying=100.0, expiry=30):
    return {
        "name": "MyStrangle",
        "strategy_type": "strangle",
        "legs": [
            _long_call(strike=110.0, premium=3.0),
            _long_put(strike=90.0, premium=3.0),
        ],
        "underlying_price_usd": underlying,
        "expiry_days": expiry,
    }

def _bull_spread_strategy(underlying=100.0, expiry=30):
    return {
        "name": "MyBullSpread",
        "strategy_type": "bull_spread",
        "legs": [
            _long_call(strike=100.0, premium=5.0),
            _short_call(strike=110.0, premium=2.0),
        ],
        "underlying_price_usd": underlying,
        "expiry_days": expiry,
    }

def _bear_spread_strategy(underlying=100.0, expiry=30):
    return {
        "name": "MyBearSpread",
        "strategy_type": "bear_spread",
        "legs": [
            _long_put(strike=100.0, premium=5.0),
            _short_put(strike=90.0, premium=2.0),
        ],
        "underlying_price_usd": underlying,
        "expiry_days": expiry,
    }

def _iron_condor_strategy(underlying=100.0, expiry=30):
    return {
        "name": "MyIronCondor",
        "strategy_type": "iron_condor",
        "legs": [
            {"option_type": "put", "strike": 80.0, "premium_usd": 1.0, "quantity": 1.0, "direction": "long"},
            {"option_type": "put", "strike": 90.0, "premium_usd": 2.0, "quantity": 1.0, "direction": "short"},
            {"option_type": "call", "strike": 110.0, "premium_usd": 2.0, "quantity": 1.0, "direction": "short"},
            {"option_type": "call", "strike": 120.0, "premium_usd": 1.0, "quantity": 1.0, "direction": "long"},
        ],
        "underlying_price_usd": underlying,
        "expiry_days": expiry,
    }


# ---------------------------------------------------------------------------
# Unit tests: _leg_payoff_at_price
# ---------------------------------------------------------------------------

class TestLegPayoff(unittest.TestCase):

    def test_long_call_in_the_money(self):
        leg = _long_call(strike=100, premium=5)
        # at 120: intrinsic = 20, pnl = 20 - 5 = 15
        self.assertAlmostEqual(_leg_payoff_at_price(leg, 120.0), 15.0, places=4)

    def test_long_call_out_of_money(self):
        leg = _long_call(strike=100, premium=5)
        # at 90: intrinsic = 0, pnl = -5
        self.assertAlmostEqual(_leg_payoff_at_price(leg, 90.0), -5.0, places=4)

    def test_long_call_at_the_money(self):
        leg = _long_call(strike=100, premium=5)
        # at 100: intrinsic = 0, pnl = -5
        self.assertAlmostEqual(_leg_payoff_at_price(leg, 100.0), -5.0, places=4)

    def test_short_call_in_the_money(self):
        leg = _short_call(strike=100, premium=5)
        # at 120: intrinsic = 20, pnl = 5 - 20 = -15
        self.assertAlmostEqual(_leg_payoff_at_price(leg, 120.0), -15.0, places=4)

    def test_short_call_out_of_money(self):
        leg = _short_call(strike=100, premium=5)
        # at 90: intrinsic = 0, pnl = 5
        self.assertAlmostEqual(_leg_payoff_at_price(leg, 90.0), 5.0, places=4)

    def test_long_put_in_the_money(self):
        leg = _long_put(strike=100, premium=5)
        # at 80: intrinsic = 20, pnl = 15
        self.assertAlmostEqual(_leg_payoff_at_price(leg, 80.0), 15.0, places=4)

    def test_long_put_out_of_money(self):
        leg = _long_put(strike=100, premium=5)
        # at 110: intrinsic = 0, pnl = -5
        self.assertAlmostEqual(_leg_payoff_at_price(leg, 110.0), -5.0, places=4)

    def test_short_put_in_the_money(self):
        leg = _short_put(strike=100, premium=5)
        # at 80: intrinsic = 20, pnl = 5 - 20 = -15
        self.assertAlmostEqual(_leg_payoff_at_price(leg, 80.0), -15.0, places=4)

    def test_short_put_out_of_money(self):
        leg = _short_put(strike=100, premium=5)
        # at 110: intrinsic = 0, pnl = 5
        self.assertAlmostEqual(_leg_payoff_at_price(leg, 110.0), 5.0, places=4)

    def test_quantity_multiplier(self):
        leg = _long_call(strike=100, premium=5, qty=3.0)
        # at 120: (20-5)*3 = 45
        self.assertAlmostEqual(_leg_payoff_at_price(leg, 120.0), 45.0, places=4)

    def test_long_call_breakeven(self):
        leg = _long_call(strike=100, premium=5)
        # breakeven at 105: intrinsic = 5, pnl = 0
        self.assertAlmostEqual(_leg_payoff_at_price(leg, 105.0), 0.0, places=4)

    def test_long_put_breakeven(self):
        leg = _long_put(strike=100, premium=5)
        # breakeven at 95: intrinsic = 5, pnl = 0
        self.assertAlmostEqual(_leg_payoff_at_price(leg, 95.0), 0.0, places=4)


# ---------------------------------------------------------------------------
# Unit tests: _strategy_payoff_at_price
# ---------------------------------------------------------------------------

class TestStrategyPayoff(unittest.TestCase):

    def test_straddle_payoff_far_up(self):
        legs = [_long_call(100, 5), _long_put(100, 5)]
        # at 130: call = 25, put = -5, total = 20
        pnl = _strategy_payoff_at_price(legs, 130.0)
        self.assertAlmostEqual(pnl, 20.0, places=4)

    def test_straddle_payoff_at_money(self):
        legs = [_long_call(100, 5), _long_put(100, 5)]
        # at 100: call = -5, put = -5, total = -10
        pnl = _strategy_payoff_at_price(legs, 100.0)
        self.assertAlmostEqual(pnl, -10.0, places=4)

    def test_straddle_payoff_far_down(self):
        legs = [_long_call(100, 5), _long_put(100, 5)]
        # at 70: call = -5, put = 25, total = 20
        pnl = _strategy_payoff_at_price(legs, 70.0)
        self.assertAlmostEqual(pnl, 20.0, places=4)

    def test_bull_spread_above_upper(self):
        legs = [_long_call(100, 5), _short_call(110, 2)]
        # at 120: long_call = 15, short_call = -8, total = 7
        pnl = _strategy_payoff_at_price(legs, 120.0)
        self.assertAlmostEqual(pnl, 7.0, places=4)

    def test_bull_spread_below_lower(self):
        legs = [_long_call(100, 5), _short_call(110, 2)]
        # at 90: long_call = -5, short_call = 2, total = -3
        pnl = _strategy_payoff_at_price(legs, 90.0)
        self.assertAlmostEqual(pnl, -3.0, places=4)

    def test_iron_condor_inside_wings(self):
        # at 100 (between short strikes 90 and 110)
        legs = _iron_condor_strategy()["legs"]
        pnl = _strategy_payoff_at_price(legs, 100.0)
        # credit: -1 + 2 + 2 - 1 = 2
        self.assertAlmostEqual(pnl, 2.0, places=4)


# ---------------------------------------------------------------------------
# Unit tests: _compute_net_premium
# ---------------------------------------------------------------------------

class TestNetPremium(unittest.TestCase):

    def test_long_call_net_debit(self):
        # pay 5 for call
        legs = [_long_call(100, 5)]
        self.assertAlmostEqual(_compute_net_premium(legs), 5.0, places=4)

    def test_short_call_net_credit(self):
        # receive 3 for short call
        legs = [_short_call(110, 3)]
        self.assertAlmostEqual(_compute_net_premium(legs), -3.0, places=4)

    def test_straddle_net_debit(self):
        legs = [_long_call(100, 5), _long_put(100, 5)]
        self.assertAlmostEqual(_compute_net_premium(legs), 10.0, places=4)

    def test_iron_condor_net_credit(self):
        # -1 + 2 + 2 - 1 = 2 credit
        legs = _iron_condor_strategy()["legs"]
        self.assertAlmostEqual(_compute_net_premium(legs), -2.0, places=4)

    def test_bull_spread_net_debit(self):
        # pay 5, receive 2 → 3 net debit
        legs = [_long_call(100, 5), _short_call(110, 2)]
        self.assertAlmostEqual(_compute_net_premium(legs), 3.0, places=4)

    def test_quantity_affects_net_premium(self):
        legs = [_long_call(100, 5, qty=2.0)]
        self.assertAlmostEqual(_compute_net_premium(legs), 10.0, places=4)


# ---------------------------------------------------------------------------
# Unit tests: _find_breakevens
# ---------------------------------------------------------------------------

class TestFindBreakevens(unittest.TestCase):

    def test_long_call_breakeven(self):
        legs = [_long_call(100, 5)]
        bes = _find_breakevens(legs, 100.0)
        self.assertEqual(len(bes), 1)
        self.assertAlmostEqual(bes[0], 105.0, delta=0.5)

    def test_long_put_breakeven(self):
        legs = [_long_put(100, 5)]
        bes = _find_breakevens(legs, 100.0)
        self.assertEqual(len(bes), 1)
        self.assertAlmostEqual(bes[0], 95.0, delta=0.5)

    def test_straddle_two_breakevens(self):
        legs = [_long_call(100, 5), _long_put(100, 5)]
        bes = _find_breakevens(legs, 100.0)
        self.assertEqual(len(bes), 2)
        self.assertAlmostEqual(bes[0], 90.0, delta=1.0)
        self.assertAlmostEqual(bes[1], 110.0, delta=1.0)

    def test_short_call_no_upside_breakeven(self):
        # pure short call: always profitable below strike+premium
        legs = [_short_call(100, 5)]
        bes = _find_breakevens(legs, 100.0)
        # One breakeven at 105
        self.assertGreaterEqual(len(bes), 1)

    def test_bull_spread_one_breakeven(self):
        # bull spread: breakeven between long strike and short strike
        legs = [_long_call(100, 5), _short_call(110, 2)]
        bes = _find_breakevens(legs, 100.0)
        # breakeven at 103 (net debit 3)
        self.assertGreaterEqual(len(bes), 1)
        self.assertAlmostEqual(bes[0], 103.0, delta=1.0)

    def test_iron_condor_two_breakevens(self):
        legs = _iron_condor_strategy()["legs"]
        bes = _find_breakevens(legs, 100.0)
        # Two breakevens: one on each side
        self.assertEqual(len(bes), 2)

    def test_sorted_breakevens(self):
        legs = [_long_call(100, 5), _long_put(100, 5)]
        bes = _find_breakevens(legs, 100.0)
        self.assertEqual(bes, sorted(bes))


# ---------------------------------------------------------------------------
# Unit tests: _risk_reward_ratio
# ---------------------------------------------------------------------------

class TestRiskRewardRatio(unittest.TestCase):

    def test_basic_ratio(self):
        # 10 profit / 5 loss = 2.0
        rr = _risk_reward_ratio(10.0, -5.0)
        self.assertAlmostEqual(rr, 2.0, places=4)

    def test_unlimited_profit_returns_none(self):
        self.assertIsNone(_risk_reward_ratio(None, -5.0))

    def test_zero_loss_returns_none(self):
        self.assertIsNone(_risk_reward_ratio(10.0, 0.0))

    def test_small_loss_ratio(self):
        rr = _risk_reward_ratio(100.0, -50.0)
        self.assertAlmostEqual(rr, 2.0, places=4)

    def test_loss_larger_than_profit(self):
        rr = _risk_reward_ratio(3.0, -10.0)
        self.assertAlmostEqual(rr, 0.3, places=4)


# ---------------------------------------------------------------------------
# Unit tests: _compute_flags
# ---------------------------------------------------------------------------

class TestComputeFlags(unittest.TestCase):

    def test_unlimited_profit_flag(self):
        legs = [_long_call(100, 5)]
        flags = _compute_flags(None, -5.0, 5.0, 30, legs)
        self.assertIn("UNLIMITED_PROFIT", flags)

    def test_near_expiry_flag(self):
        legs = [_long_call(100, 5)]
        flags = _compute_flags(10.0, -5.0, 5.0, 3, legs)
        self.assertIn("NEAR_EXPIRY", flags)

    def test_not_near_expiry(self):
        legs = [_long_call(100, 5)]
        flags = _compute_flags(10.0, -5.0, 5.0, 30, legs)
        self.assertNotIn("NEAR_EXPIRY", flags)

    def test_net_credit_flag(self):
        legs = [_short_call(100, 5)]
        flags = _compute_flags(5.0, -95.0, -5.0, 30, legs)
        self.assertIn("NET_CREDIT", flags)

    def test_complex_flag_more_than_2_legs(self):
        legs = _iron_condor_strategy()["legs"]
        flags = _compute_flags(2.0, -8.0, -2.0, 30, legs)
        self.assertIn("COMPLEX", flags)

    def test_no_complex_flag_2_legs(self):
        legs = [_long_call(100, 5), _short_call(110, 2)]
        flags = _compute_flags(7.0, -3.0, 3.0, 30, legs)
        self.assertNotIn("COMPLEX", flags)


# ---------------------------------------------------------------------------
# Unit tests: _validate_strategy
# ---------------------------------------------------------------------------

class TestValidateStrategy(unittest.TestCase):

    def test_valid_strategy(self):
        s = _covered_call_strategy()
        _validate_strategy(s)  # Should not raise

    def test_missing_name(self):
        s = _covered_call_strategy()
        del s["name"]
        with self.assertRaises(ValueError):
            _validate_strategy(s)

    def test_missing_strategy_type(self):
        s = _covered_call_strategy()
        del s["strategy_type"]
        with self.assertRaises(ValueError):
            _validate_strategy(s)

    def test_invalid_strategy_type(self):
        s = _covered_call_strategy()
        s["strategy_type"] = "butterfly"
        with self.assertRaises(ValueError):
            _validate_strategy(s)

    def test_empty_legs(self):
        s = _covered_call_strategy()
        s["legs"] = []
        with self.assertRaises(ValueError):
            _validate_strategy(s)

    def test_invalid_option_type(self):
        s = _covered_call_strategy()
        s["legs"][0]["option_type"] = "futures"
        with self.assertRaises(ValueError):
            _validate_strategy(s)

    def test_invalid_direction(self):
        s = _covered_call_strategy()
        s["legs"][0]["direction"] = "neutral"
        with self.assertRaises(ValueError):
            _validate_strategy(s)

    def test_negative_strike(self):
        s = _covered_call_strategy()
        s["legs"][0]["strike"] = -10.0
        with self.assertRaises(ValueError):
            _validate_strategy(s)

    def test_zero_underlying_price(self):
        s = _covered_call_strategy()
        s["underlying_price_usd"] = 0.0
        with self.assertRaises(ValueError):
            _validate_strategy(s)

    def test_negative_expiry(self):
        s = _covered_call_strategy()
        s["expiry_days"] = -1
        with self.assertRaises(ValueError):
            _validate_strategy(s)

    def test_missing_leg_field(self):
        s = _covered_call_strategy()
        del s["legs"][0]["strike"]
        with self.assertRaises(ValueError):
            _validate_strategy(s)


# ---------------------------------------------------------------------------
# Unit tests: _analyze_single_strategy
# ---------------------------------------------------------------------------

class TestAnalyzeSingleStrategy(unittest.TestCase):

    def _cfg(self):
        return {"write_log": False}

    def test_covered_call_label(self):
        result = _analyze_single_strategy(_covered_call_strategy(), self._cfg())
        self.assertEqual(result["label"], "INCOME")

    def test_protective_put_label(self):
        result = _analyze_single_strategy(_protective_put_strategy(), self._cfg())
        self.assertEqual(result["label"], "HEDGING")

    def test_straddle_label(self):
        result = _analyze_single_strategy(_straddle_strategy(), self._cfg())
        self.assertEqual(result["label"], "SPECULATIVE")

    def test_strangle_label(self):
        result = _analyze_single_strategy(_strangle_strategy(), self._cfg())
        self.assertEqual(result["label"], "SPECULATIVE")

    def test_bull_spread_label(self):
        result = _analyze_single_strategy(_bull_spread_strategy(), self._cfg())
        self.assertEqual(result["label"], "DIRECTIONAL")

    def test_bear_spread_label(self):
        result = _analyze_single_strategy(_bear_spread_strategy(), self._cfg())
        self.assertEqual(result["label"], "DIRECTIONAL")

    def test_iron_condor_label(self):
        result = _analyze_single_strategy(_iron_condor_strategy(), self._cfg())
        self.assertEqual(result["label"], "NEUTRAL")

    def test_result_has_required_keys(self):
        result = _analyze_single_strategy(_bull_spread_strategy(), self._cfg())
        required = {
            "name", "strategy_type", "label", "net_premium_usd",
            "max_profit_usd", "max_loss_usd", "breakeven_prices",
            "probability_of_profit_pct", "risk_reward_ratio", "flags",
            "expiry_days", "underlying_price_usd", "leg_count",
        }
        for k in required:
            self.assertIn(k, result, f"Missing key: {k}")

    def test_bull_spread_max_profit_bounded(self):
        result = _analyze_single_strategy(_bull_spread_strategy(), self._cfg())
        # Max profit should be bounded (not None)
        self.assertIsNotNone(result["max_profit_usd"])
        # Max profit ~ (110-100) - 3 = 7
        self.assertAlmostEqual(result["max_profit_usd"], 7.0, delta=1.0)

    def test_long_call_unlimited_profit(self):
        s = {
            "name": "LongCall",
            "strategy_type": "covered_call",
            "legs": [_long_call(100, 5)],
            "underlying_price_usd": 100.0,
            "expiry_days": 30,
        }
        result = _analyze_single_strategy(s, self._cfg())
        # Long call has unlimited upside
        self.assertIsNone(result["max_profit_usd"])
        self.assertIn("UNLIMITED_PROFIT", result["flags"])

    def test_iron_condor_net_credit(self):
        result = _analyze_single_strategy(_iron_condor_strategy(), self._cfg())
        # Iron condor: net credit of 2
        self.assertAlmostEqual(result["net_premium_usd"], -2.0, places=4)
        self.assertIn("NET_CREDIT", result["flags"])

    def test_near_expiry_flag(self):
        s = _straddle_strategy(expiry=5)
        result = _analyze_single_strategy(s, self._cfg())
        self.assertIn("NEAR_EXPIRY", result["flags"])

    def test_complex_flag_iron_condor(self):
        result = _analyze_single_strategy(_iron_condor_strategy(), self._cfg())
        self.assertIn("COMPLEX", result["flags"])

    def test_probability_of_profit_range(self):
        result = _analyze_single_strategy(_bull_spread_strategy(), self._cfg())
        pop = result["probability_of_profit_pct"]
        self.assertGreaterEqual(pop, 0.0)
        self.assertLessEqual(pop, 100.0)

    def test_breakeven_prices_list(self):
        result = _analyze_single_strategy(_bull_spread_strategy(), self._cfg())
        self.assertIsInstance(result["breakeven_prices"], list)

    def test_leg_count(self):
        result = _analyze_single_strategy(_iron_condor_strategy(), self._cfg())
        self.assertEqual(result["leg_count"], 4)

    def test_straddle_two_breakevens(self):
        result = _analyze_single_strategy(_straddle_strategy(), self._cfg())
        self.assertEqual(len(result["breakeven_prices"]), 2)


# ---------------------------------------------------------------------------
# Unit tests: _compute_aggregates
# ---------------------------------------------------------------------------

class TestComputeAggregates(unittest.TestCase):

    def _make_result(self, name, max_profit, max_loss, rr, prob, flags, net_premium):
        return {
            "name": name,
            "max_profit_usd": max_profit,
            "max_loss_usd": max_loss,
            "risk_reward_ratio": rr,
            "probability_of_profit_pct": prob,
            "flags": flags,
            "net_premium_usd": net_premium,
        }

    def test_empty_list(self):
        agg = _compute_aggregates([])
        self.assertEqual(agg["total_premium_deployed_usd"], 0.0)
        self.assertEqual(agg["net_credit_count"], 0)
        self.assertIsNone(agg["best_risk_reward"])

    def test_best_risk_reward(self):
        r1 = self._make_result("A", 10, -5, 2.0, 60.0, [], 5.0)
        r2 = self._make_result("B", 20, -5, 4.0, 70.0, [], 5.0)
        agg = _compute_aggregates([r1, r2])
        self.assertEqual(agg["best_risk_reward_name"], "B")
        self.assertAlmostEqual(agg["best_risk_reward"], 4.0, places=4)

    def test_highest_profit_potential(self):
        r1 = self._make_result("A", 10, -5, 2.0, 60.0, [], 5.0)
        r2 = self._make_result("B", 30, -10, 3.0, 50.0, [], 5.0)
        agg = _compute_aggregates([r1, r2])
        self.assertEqual(agg["highest_profit_name"], "B")
        self.assertAlmostEqual(agg["highest_profit_potential"], 30.0, places=4)

    def test_total_premium_deployed(self):
        r1 = self._make_result("A", 10, -5, 2.0, 60.0, [], 5.0)
        r2 = self._make_result("B", 10, -5, 2.0, 60.0, [], 3.0)
        agg = _compute_aggregates([r1, r2])
        self.assertAlmostEqual(agg["total_premium_deployed_usd"], 8.0, places=4)

    def test_net_credit_count(self):
        r1 = self._make_result("A", 10, -5, 2.0, 60.0, ["NET_CREDIT"], -2.0)
        r2 = self._make_result("B", 10, -5, 2.0, 60.0, [], 5.0)
        agg = _compute_aggregates([r1, r2])
        self.assertEqual(agg["net_credit_count"], 1)

    def test_average_probability_of_profit(self):
        r1 = self._make_result("A", 10, -5, 2.0, 60.0, [], 5.0)
        r2 = self._make_result("B", 10, -5, 2.0, 40.0, [], 5.0)
        agg = _compute_aggregates([r1, r2])
        self.assertAlmostEqual(agg["average_probability_of_profit"], 50.0, places=2)

    def test_none_rr_skipped_in_best(self):
        r1 = self._make_result("A", None, -5, None, 60.0, ["UNLIMITED_PROFIT"], 5.0)
        r2 = self._make_result("B", 10, -5, 2.0, 60.0, [], 5.0)
        agg = _compute_aggregates([r1, r2])
        self.assertEqual(agg["best_risk_reward_name"], "B")

    def test_credits_not_added_to_premium(self):
        # net credit (negative net_premium) should not add to premium deployed
        r1 = self._make_result("A", 3, -8, 0.375, 70.0, ["NET_CREDIT"], -2.0)
        agg = _compute_aggregates([r1])
        self.assertAlmostEqual(agg["total_premium_deployed_usd"], 0.0, places=4)


# ---------------------------------------------------------------------------
# Unit tests: atomic write and log
# ---------------------------------------------------------------------------

class TestAtomicWriteAndLog(unittest.TestCase):

    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.json")
            _atomic_write(path, {"a": 1})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["a"], 1)

    def test_atomic_write_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.json")
            _atomic_write(path, {"a": 1})
            _atomic_write(path, {"a": 2})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["a"], 2)

    def test_append_log_creates_list(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            _append_log({"x": 1}, path)
            with open(path) as f:
                log = json.load(f)
            self.assertIsInstance(log, list)
            self.assertEqual(len(log), 1)

    def test_append_log_accumulates(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            for i in range(5):
                _append_log({"i": i}, path)
            with open(path) as f:
                log = json.load(f)
            self.assertEqual(len(log), 5)

    def test_append_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            for i in range(15):
                _append_log({"i": i}, path, cap=10)
            with open(path) as f:
                log = json.load(f)
            self.assertLessEqual(len(log), 10)

    def test_append_log_preserves_latest(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            for i in range(15):
                _append_log({"i": i}, path, cap=10)
            with open(path) as f:
                log = json.load(f)
            last = log[-1]["result"]["i"]
            self.assertEqual(last, 14)

    def test_log_has_timestamp(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            _append_log({"x": 1}, path)
            with open(path) as f:
                log = json.load(f)
            self.assertIn("timestamp", log[0])

    def test_log_corrupt_file_reset(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            with open(path, "w") as f:
                f.write("INVALID JSON")
            _append_log({"x": 1}, path)
            with open(path) as f:
                log = json.load(f)
            self.assertEqual(len(log), 1)


# ---------------------------------------------------------------------------
# Integration tests: DeFiOptionStrategyPayoffAnalyzer.analyze
# ---------------------------------------------------------------------------

class TestAnalyzerIntegration(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "opt_log.json")
        self.analyzer = DeFiOptionStrategyPayoffAnalyzer(log_path=self.log_path)

    def _cfg(self, write=False):
        return {"write_log": write, "price_range_factor": 2.5}

    def test_analyze_all_strategy_types(self):
        strategies = [
            _covered_call_strategy(),
            _protective_put_strategy(),
            _straddle_strategy(),
            _strangle_strategy(),
            _bull_spread_strategy(),
            _bear_spread_strategy(),
            _iron_condor_strategy(),
        ]
        result = self.analyzer.analyze(strategies, self._cfg())
        self.assertEqual(result["total_analyzed"], 7)
        self.assertEqual(result["total_errors"], 0)

    def test_analyze_returns_correct_keys(self):
        result = self.analyzer.analyze([_bull_spread_strategy()], self._cfg())
        for k in ["timestamp", "module", "mp", "strategies", "aggregates",
                   "errors", "total_analyzed", "total_errors"]:
            self.assertIn(k, result)

    def test_analyze_module_name(self):
        result = self.analyzer.analyze([], self._cfg())
        self.assertEqual(result["module"], "DeFiOptionStrategyPayoffAnalyzer")

    def test_analyze_mp_tag(self):
        result = self.analyzer.analyze([], self._cfg())
        self.assertEqual(result["mp"], "MP-936")

    def test_analyze_empty_list(self):
        result = self.analyzer.analyze([], self._cfg())
        self.assertEqual(result["total_analyzed"], 0)
        self.assertEqual(result["total_errors"], 0)

    def test_analyze_invalid_strategy_goes_to_errors(self):
        s = {"name": "Bad", "strategy_type": "invalid_type",
             "legs": [], "underlying_price_usd": 100.0, "expiry_days": 30}
        result = self.analyzer.analyze([s], self._cfg())
        self.assertEqual(result["total_errors"], 1)
        self.assertEqual(result["total_analyzed"], 0)

    def test_analyze_mixed_valid_invalid(self):
        bad = {"name": "Bad", "strategy_type": "xyz", "legs": [],
               "underlying_price_usd": 100.0, "expiry_days": 30}
        result = self.analyzer.analyze([_bull_spread_strategy(), bad], self._cfg())
        self.assertEqual(result["total_analyzed"], 1)
        self.assertEqual(result["total_errors"], 1)

    def test_analyze_writes_log_when_enabled(self):
        self.analyzer.analyze([_bull_spread_strategy()], {"write_log": True})
        self.assertTrue(os.path.exists(self.log_path))

    def test_analyze_no_log_when_disabled(self):
        self.analyzer.analyze([_bull_spread_strategy()], self._cfg(write=False))
        self.assertFalse(os.path.exists(self.log_path))

    def test_analyze_log_structure(self):
        self.analyzer.analyze([_bull_spread_strategy()], {"write_log": True})
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertIsInstance(log, list)
        self.assertEqual(len(log), 1)
        entry = log[0]
        self.assertIn("timestamp", entry)
        self.assertIn("result", entry)

    def test_analyze_strategies_is_list_required(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze("not a list", self._cfg())

    def test_iron_condor_max_profit_bounded(self):
        result = self.analyzer.analyze([_iron_condor_strategy()], self._cfg())
        s = result["strategies"][0]
        self.assertIsNotNone(s["max_profit_usd"])
        self.assertGreater(s["max_profit_usd"], 0)

    def test_covered_call_income_label(self):
        result = self.analyzer.analyze([_covered_call_strategy()], self._cfg())
        s = result["strategies"][0]
        self.assertEqual(s["label"], "INCOME")

    def test_protective_put_hedging_label(self):
        result = self.analyzer.analyze([_protective_put_strategy()], self._cfg())
        s = result["strategies"][0]
        self.assertEqual(s["label"], "HEDGING")

    def test_aggregates_present(self):
        result = self.analyzer.analyze([_bull_spread_strategy()], self._cfg())
        agg = result["aggregates"]
        self.assertIn("best_risk_reward", agg)
        self.assertIn("total_premium_deployed_usd", agg)
        self.assertIn("average_probability_of_profit", agg)
        self.assertIn("net_credit_count", agg)

    def test_zero_expiry_strategy(self):
        s = _bull_spread_strategy(expiry=0)
        result = self.analyzer.analyze([s], self._cfg())
        self.assertEqual(result["total_analyzed"], 1)

    def test_high_underlying_price(self):
        s = _straddle_strategy(underlying=10000.0)
        result = self.analyzer.analyze([s], self._cfg())
        self.assertEqual(result["total_analyzed"], 1)

    def test_probability_between_0_and_100(self):
        result = self.analyzer.analyze([_iron_condor_strategy()], self._cfg())
        pop = result["strategies"][0]["probability_of_profit_pct"]
        self.assertGreaterEqual(pop, 0.0)
        self.assertLessEqual(pop, 100.0)

    def test_strangle_lower_cost_than_straddle(self):
        straddle_result = self.analyzer.analyze([_straddle_strategy()], self._cfg())
        strangle_result = self.analyzer.analyze([_strangle_strategy()], self._cfg())
        straddle_cost = straddle_result["strategies"][0]["net_premium_usd"]
        strangle_cost = strangle_result["strategies"][0]["net_premium_usd"]
        # Straddle costs 10, strangle costs 6
        self.assertGreater(straddle_cost, strangle_cost)

    def test_multiple_log_entries_accumulate(self):
        cfg = {"write_log": True}
        self.analyzer.analyze([_bull_spread_strategy()], cfg)
        self.analyzer.analyze([_bull_spread_strategy()], cfg)
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertEqual(len(log), 2)


if __name__ == "__main__":
    unittest.main()
