"""
Tests for MP-1079 ProtocolDeFiYieldFarmingExitTimingAdvisor.
Run: python3 -m unittest spa_core.tests.test_protocol_defi_yield_farming_exit_timing_advisor -v
"""

import json
import os
import sys
import tempfile
import unittest

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.protocol_defi_yield_farming_exit_timing_advisor import (
    ProtocolDeFiYieldFarmingExitTimingAdvisor,
    _validate_position,
    _net_exit_value_usd,
    _opportunity_cost_pct,
    _days_to_recover_exit_costs,
    _exit_urgency_score,
    _timing_label,
    _iso_now,
    _atomic_write,
    _init_log,
    _append_log,
    analyze,
    BEST_ALTERNATIVE_APY_PCT,
    MAX_DAYS_TO_RECOVER,
    URGENCY_HOLD_STRONG,
    URGENCY_HOLD_MONITOR,
    URGENCY_NEUTRAL,
    URGENCY_CONSIDER_EXIT,
    LOG_MAX_ENTRIES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _pos(
    protocol_name="Aave",
    entry_date_days_ago=30,
    entry_apy_pct=10.0,
    current_apy_pct=10.0,
    apy_trend_7d_pct=0.0,
    unrealized_pnl_pct=5.0,
    exit_fee_pct=0.1,
    lock_remaining_days=0,
    token_price_change_since_entry_pct=0.0,
    gas_cost_exit_usd=20.0,
    position_usd=10000.0,
):
    return {
        "protocol_name": protocol_name,
        "entry_date_days_ago": entry_date_days_ago,
        "entry_apy_pct": entry_apy_pct,
        "current_apy_pct": current_apy_pct,
        "apy_trend_7d_pct": apy_trend_7d_pct,
        "unrealized_pnl_pct": unrealized_pnl_pct,
        "exit_fee_pct": exit_fee_pct,
        "lock_remaining_days": lock_remaining_days,
        "token_price_change_since_entry_pct": token_price_change_since_entry_pct,
        "gas_cost_exit_usd": gas_cost_exit_usd,
        "position_usd": position_usd,
    }


def _hold_strong_pos():
    """Position that should produce HOLD_STRONG label."""
    return _pos(
        entry_apy_pct=10.0, current_apy_pct=10.0, apy_trend_7d_pct=2.0,
        unrealized_pnl_pct=15.0, token_price_change_since_entry_pct=20.0,
        lock_remaining_days=0,
    )


def _exit_now_pos():
    """Position that should produce EXIT_NOW label."""
    return _pos(
        entry_apy_pct=20.0, current_apy_pct=1.0, apy_trend_7d_pct=-10.0,
        unrealized_pnl_pct=-20.0, token_price_change_since_entry_pct=-50.0,
        lock_remaining_days=0, position_usd=10000.0,
    )


def _fake_log_result():
    return {
        "protocol_name": "TestProto",
        "net_exit_value_usd": 9900.0,
        "exit_urgency_score": 15.0,
        "timing_label": "HOLD_STRONG",
        "days_to_recover_exit_costs": 10.0,
        "analyzed_at": _iso_now(),
    }


# ---------------------------------------------------------------------------
# TestValidatePosition
# ---------------------------------------------------------------------------

class TestValidatePosition(unittest.TestCase):

    def test_valid_position_passes(self):
        _validate_position(_pos())  # must not raise

    def test_missing_protocol_name_raises(self):
        p = _pos(); del p["protocol_name"]
        with self.assertRaises(ValueError):
            _validate_position(p)

    def test_missing_entry_date_days_ago_raises(self):
        p = _pos(); del p["entry_date_days_ago"]
        with self.assertRaises(ValueError):
            _validate_position(p)

    def test_missing_entry_apy_pct_raises(self):
        p = _pos(); del p["entry_apy_pct"]
        with self.assertRaises(ValueError):
            _validate_position(p)

    def test_missing_current_apy_pct_raises(self):
        p = _pos(); del p["current_apy_pct"]
        with self.assertRaises(ValueError):
            _validate_position(p)

    def test_missing_apy_trend_7d_pct_raises(self):
        p = _pos(); del p["apy_trend_7d_pct"]
        with self.assertRaises(ValueError):
            _validate_position(p)

    def test_missing_unrealized_pnl_pct_raises(self):
        p = _pos(); del p["unrealized_pnl_pct"]
        with self.assertRaises(ValueError):
            _validate_position(p)

    def test_missing_exit_fee_pct_raises(self):
        p = _pos(); del p["exit_fee_pct"]
        with self.assertRaises(ValueError):
            _validate_position(p)

    def test_missing_lock_remaining_days_raises(self):
        p = _pos(); del p["lock_remaining_days"]
        with self.assertRaises(ValueError):
            _validate_position(p)

    def test_missing_token_price_change_raises(self):
        p = _pos(); del p["token_price_change_since_entry_pct"]
        with self.assertRaises(ValueError):
            _validate_position(p)

    def test_missing_gas_cost_exit_usd_raises(self):
        p = _pos(); del p["gas_cost_exit_usd"]
        with self.assertRaises(ValueError):
            _validate_position(p)

    def test_missing_position_usd_raises(self):
        p = _pos(); del p["position_usd"]
        with self.assertRaises(ValueError):
            _validate_position(p)

    def test_empty_protocol_name_raises(self):
        with self.assertRaises(ValueError):
            _validate_position(_pos(protocol_name=""))

    def test_bool_entry_apy_raises(self):
        p = _pos(); p["entry_apy_pct"] = True
        with self.assertRaises(ValueError):
            _validate_position(p)

    def test_string_current_apy_raises(self):
        p = _pos(); p["current_apy_pct"] = "5.0"
        with self.assertRaises(ValueError):
            _validate_position(p)

    def test_float_lock_remaining_raises(self):
        p = _pos(); p["lock_remaining_days"] = 30.5
        with self.assertRaises(ValueError):
            _validate_position(p)

    def test_bool_lock_remaining_raises(self):
        p = _pos(); p["lock_remaining_days"] = True
        with self.assertRaises(ValueError):
            _validate_position(p)

    def test_negative_entry_date_raises(self):
        with self.assertRaises(ValueError):
            _validate_position(_pos(entry_date_days_ago=-1))

    def test_negative_entry_apy_raises(self):
        with self.assertRaises(ValueError):
            _validate_position(_pos(entry_apy_pct=-0.01))

    def test_negative_current_apy_raises(self):
        with self.assertRaises(ValueError):
            _validate_position(_pos(current_apy_pct=-1.0))

    def test_exit_fee_over_100_raises(self):
        with self.assertRaises(ValueError):
            _validate_position(_pos(exit_fee_pct=101.0))

    def test_negative_exit_fee_raises(self):
        with self.assertRaises(ValueError):
            _validate_position(_pos(exit_fee_pct=-0.01))

    def test_negative_lock_remaining_raises(self):
        with self.assertRaises(ValueError):
            _validate_position(_pos(lock_remaining_days=-1))

    def test_negative_gas_cost_raises(self):
        with self.assertRaises(ValueError):
            _validate_position(_pos(gas_cost_exit_usd=-1.0))

    def test_negative_position_usd_raises(self):
        with self.assertRaises(ValueError):
            _validate_position(_pos(position_usd=-1.0))

    def test_position_not_dict_raises(self):
        with self.assertRaises(ValueError):
            _validate_position("not_a_dict")

    def test_zero_position_usd_passes(self):
        _validate_position(_pos(position_usd=0.0))

    def test_zero_lock_remaining_passes(self):
        _validate_position(_pos(lock_remaining_days=0))

    def test_zero_exit_fee_passes(self):
        _validate_position(_pos(exit_fee_pct=0.0))

    def test_negative_apy_trend_passes(self):
        _validate_position(_pos(apy_trend_7d_pct=-5.0))

    def test_negative_unrealized_pnl_passes(self):
        _validate_position(_pos(unrealized_pnl_pct=-10.0))


# ---------------------------------------------------------------------------
# TestNetExitValue
# ---------------------------------------------------------------------------

class TestNetExitValue(unittest.TestCase):

    def test_no_fees_no_gas_no_pnl(self):
        net = _net_exit_value_usd(10000.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(net, 10000.0)

    def test_exit_fee_only(self):
        # fee = 10000 * 1% = 100 → net = 9900
        net = _net_exit_value_usd(10000.0, 0.0, 1.0, 0.0)
        self.assertAlmostEqual(net, 9900.0)

    def test_gas_cost_only(self):
        net = _net_exit_value_usd(10000.0, 0.0, 0.0, 50.0)
        self.assertAlmostEqual(net, 9950.0)

    def test_positive_pnl_increases_gross(self):
        # gross = 10000 * 1.1 = 11000
        net = _net_exit_value_usd(10000.0, 10.0, 0.0, 0.0)
        self.assertAlmostEqual(net, 11000.0)

    def test_negative_pnl_decreases_gross(self):
        # gross = 10000 * 0.8 = 8000
        net = _net_exit_value_usd(10000.0, -20.0, 0.0, 0.0)
        self.assertAlmostEqual(net, 8000.0)

    def test_fee_applied_on_gross_not_principal(self):
        # gross = 10000 * 1.1 = 11000; fee = 11000 * 0.01 = 110 → 10890
        net = _net_exit_value_usd(10000.0, 10.0, 1.0, 0.0)
        self.assertAlmostEqual(net, 10890.0)

    def test_combined_fee_and_gas(self):
        # gross = 8000; fee = 8000 * 0.005 = 40; net = 8000 - 40 - 50 = 7910
        net = _net_exit_value_usd(10000.0, -20.0, 0.5, 50.0)
        self.assertAlmostEqual(net, 7910.0)

    def test_zero_position_usd(self):
        net = _net_exit_value_usd(0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(net, 0.0)

    def test_large_gas_cost_can_make_negative(self):
        net = _net_exit_value_usd(100.0, 0.0, 0.0, 200.0)
        self.assertLess(net, 0.0)

    def test_100_pct_fee_leaves_only_gas_deducted(self):
        # fee=100% → all gross eaten → net = 0 - gas
        net = _net_exit_value_usd(10000.0, 0.0, 100.0, 50.0)
        self.assertAlmostEqual(net, -50.0)


# ---------------------------------------------------------------------------
# TestOpportunityCost
# ---------------------------------------------------------------------------

class TestOpportunityCost(unittest.TestCase):

    def test_current_equals_best_alt_zero_cost(self):
        opp = _opportunity_cost_pct(BEST_ALTERNATIVE_APY_PCT, 0.0)
        self.assertAlmostEqual(opp, 0.0, places=4)

    def test_current_below_alt_positive_cost(self):
        opp = _opportunity_cost_pct(3.0, 0.0)
        self.assertAlmostEqual(opp, 2.0, places=4)

    def test_current_above_alt_negative_cost(self):
        opp = _opportunity_cost_pct(8.0, 0.0)
        self.assertAlmostEqual(opp, -3.0, places=4)

    def test_rising_trend_reduces_cost(self):
        no_trend = _opportunity_cost_pct(3.0, 0.0)
        rising = _opportunity_cost_pct(3.0, 2.0)
        self.assertGreater(no_trend, rising)

    def test_falling_trend_increases_cost(self):
        no_trend = _opportunity_cost_pct(8.0, 0.0)
        falling = _opportunity_cost_pct(8.0, -3.0)
        self.assertGreater(falling, no_trend)

    def test_forward_apy_below_zero_large_positive_cost(self):
        opp = _opportunity_cost_pct(1.0, -10.0)
        # forward = -9, opp = 5 - (-9) = 14
        self.assertAlmostEqual(opp, 14.0, places=4)

    def test_result_is_float(self):
        self.assertIsInstance(_opportunity_cost_pct(5.0, 0.0), float)

    def test_both_trend_and_apy_combine(self):
        # current=4, trend=-2 → forward=2, opp=5-2=3
        opp = _opportunity_cost_pct(4.0, -2.0)
        self.assertAlmostEqual(opp, 3.0, places=4)


# ---------------------------------------------------------------------------
# TestDaysToRecover
# ---------------------------------------------------------------------------

class TestDaysToRecover(unittest.TestCase):

    def test_zero_apy_returns_sentinel(self):
        d = _days_to_recover_exit_costs(10000.0, 0.0, 1.0, 100.0, 0.0)
        self.assertEqual(d, MAX_DAYS_TO_RECOVER)

    def test_zero_exit_costs_returns_zero(self):
        d = _days_to_recover_exit_costs(10000.0, 0.0, 0.0, 0.0, 10.0)
        self.assertAlmostEqual(d, 0.0, places=2)

    def test_normal_scenario(self):
        # position=10000, pnl=0, fee=1%, gas=100, apy=10
        # gross=10000; fee=100; exit_costs=200; daily_yield=10000*10/100/365=2.7397
        # days = 200/2.7397 ≈ 73.0
        d = _days_to_recover_exit_costs(10000.0, 0.0, 1.0, 100.0, 10.0)
        self.assertAlmostEqual(d, 200.0 / (10000.0 * 10.0 / 100.0 / 365.0), places=0)

    def test_higher_apy_fewer_days(self):
        low = _days_to_recover_exit_costs(10000.0, 0.0, 0.5, 50.0, 5.0)
        high = _days_to_recover_exit_costs(10000.0, 0.0, 0.5, 50.0, 20.0)
        self.assertGreater(low, high)

    def test_higher_fee_more_days(self):
        low = _days_to_recover_exit_costs(10000.0, 0.0, 0.1, 0.0, 10.0)
        high = _days_to_recover_exit_costs(10000.0, 0.0, 1.0, 0.0, 10.0)
        self.assertGreater(high, low)

    def test_capped_at_max(self):
        # Extremely high exit costs with tiny APY
        d = _days_to_recover_exit_costs(100.0, 0.0, 100.0, 9999.0, 0.001)
        self.assertLessEqual(d, MAX_DAYS_TO_RECOVER)

    def test_negative_pnl_affects_exit_costs(self):
        # gross = 10000 * 0.8 = 8000; fee = 8000 * 0.01 = 80; gas = 0 → exit_costs = 80
        # daily = 10000 * 10/100/365 = 2.7397; days = 80/2.7397 ≈ 29.2
        d = _days_to_recover_exit_costs(10000.0, -20.0, 1.0, 0.0, 10.0)
        expected = 80.0 / (10000.0 * 10.0 / 100.0 / 365.0)
        self.assertAlmostEqual(d, expected, places=0)

    def test_large_position_fewer_days(self):
        small = _days_to_recover_exit_costs(1000.0, 0.0, 1.0, 0.0, 10.0)
        large = _days_to_recover_exit_costs(100000.0, 0.0, 1.0, 0.0, 10.0)
        # Same fee pct → same days (fee pct × position / daily_yield = fee pct / (apy/100/365))
        self.assertAlmostEqual(small, large, places=0)

    def test_zero_position_usd_returns_sentinel(self):
        d = _days_to_recover_exit_costs(0.0, 0.0, 1.0, 100.0, 10.0)
        self.assertEqual(d, MAX_DAYS_TO_RECOVER)

    def test_result_always_non_negative(self):
        d = _days_to_recover_exit_costs(10000.0, 50.0, 0.5, 50.0, 8.0)
        self.assertGreaterEqual(d, 0.0)


# ---------------------------------------------------------------------------
# TestExitUrgencyScore
# ---------------------------------------------------------------------------

class TestExitUrgencyScore(unittest.TestCase):

    def _urgency(self, entry_apy=10.0, current_apy=10.0, trend=0.0,
                 pnl=5.0, token=0.0, lock=0):
        return _exit_urgency_score(entry_apy, current_apy, trend, pnl, token, lock)

    def test_hold_strong_perfect_position(self):
        score = self._urgency(10.0, 10.0, 2.0, 15.0, 20.0, 0)
        self.assertLess(score, URGENCY_HOLD_STRONG)

    def test_zero_when_all_zero_signals(self):
        # Same entry/current, no trend, no pnl, no token change, but APY < 8% adds quality penalty
        score = self._urgency(0.0, 0.0, 0.0, 0.0, 0.0, 0)
        # apy_quality = max(0, (8-0)*2.5) = 20.0 → NEUTRAL area
        self.assertGreater(score, 0.0)

    def test_apy_decline_increases_urgency(self):
        no_decline = self._urgency(10.0, 10.0)
        with_decline = self._urgency(10.0, 5.0)
        self.assertGreater(with_decline, no_decline)

    def test_apy_decline_from_0_entry_no_division_by_zero(self):
        # entry_apy=0 → decline_frac=0 (guard against div by zero)
        score = self._urgency(entry_apy=0.0, current_apy=0.0)
        self.assertGreaterEqual(score, 0.0)

    def test_negative_trend_increases_urgency(self):
        no_trend = self._urgency(current_apy=10.0, trend=0.0)
        falling = self._urgency(current_apy=10.0, trend=-5.0)
        self.assertGreater(falling, no_trend)

    def test_positive_trend_no_effect(self):
        no_trend = self._urgency(current_apy=10.0, trend=0.0)
        rising = self._urgency(current_apy=10.0, trend=5.0)
        self.assertEqual(no_trend, rising)  # positive trend adds no urgency

    def test_low_apy_adds_quality_penalty(self):
        low = self._urgency(current_apy=1.0)
        high = self._urgency(current_apy=10.0)
        self.assertGreater(low, high)

    def test_apy_above_8_no_quality_penalty(self):
        # When entry_apy == current_apy (no decline) and current_apy >= 8%,
        # quality penalty = max(0, (8 - apy) * 2.5) = 0, so both are equal
        at_8 = _exit_urgency_score(8.0, 8.0, 0.0, 5.0, 0.0, 0)
        above_8 = _exit_urgency_score(10.0, 10.0, 0.0, 5.0, 0.0, 0)
        self.assertAlmostEqual(at_8, above_8, places=1)

    def test_token_decline_increases_urgency(self):
        no_change = self._urgency(token=0.0)
        declining = self._urgency(token=-30.0)
        self.assertGreater(declining, no_change)

    def test_token_increase_no_effect(self):
        no_change = self._urgency(token=0.0)
        rising = self._urgency(token=50.0)
        self.assertEqual(no_change, rising)

    def test_negative_pnl_increases_urgency(self):
        positive = self._urgency(pnl=10.0)
        negative = self._urgency(pnl=-10.0)
        self.assertGreater(negative, positive)

    def test_lock_reduces_urgency(self):
        # Use a scenario with meaningful base urgency so the 10-point discount matters
        no_lock = self._urgency(entry_apy=15.0, current_apy=4.0, lock=0)
        locked = self._urgency(entry_apy=15.0, current_apy=4.0, lock=100)
        self.assertGreater(no_lock, locked)

    def test_lock_discount_capped_at_10(self):
        # Lock of 100 days = min(100 * 0.1, 10) = 10; 200 days also = 10
        lock_100 = self._urgency(entry_apy=5.0, current_apy=2.0, lock=100)
        lock_200 = self._urgency(entry_apy=5.0, current_apy=2.0, lock=200)
        self.assertAlmostEqual(lock_100, lock_200, places=2)

    def test_result_bounded_0_100(self):
        # Worst case
        score = _exit_urgency_score(100.0, 0.0, -20.0, -50.0, -100.0, 0)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_hold_monitor_scenario(self):
        # entry=8, current=5, trend=-2, pnl=5, token=-5, lock=0 → ~24.75
        score = self._urgency(entry_apy=8.0, current_apy=5.0, trend=-2.0, pnl=5.0, token=-5.0, lock=0)
        self.assertGreaterEqual(score, URGENCY_HOLD_STRONG)
        self.assertLess(score, URGENCY_HOLD_MONITOR)

    def test_neutral_scenario(self):
        # entry=15, current=4, trend=-3, pnl=2, token=-10, lock=0 → 41.5
        score = self._urgency(entry_apy=15.0, current_apy=4.0, trend=-3.0, pnl=2.0, token=-10.0, lock=0)
        self.assertGreaterEqual(score, URGENCY_HOLD_MONITOR)
        self.assertLess(score, URGENCY_NEUTRAL)

    def test_consider_exit_scenario(self):
        # entry=20, current=2, trend=-4, pnl=-5, token=-20, lock=0 → 57.5
        score = self._urgency(entry_apy=20.0, current_apy=2.0, trend=-4.0, pnl=-5.0, token=-20.0, lock=0)
        self.assertGreaterEqual(score, URGENCY_NEUTRAL)
        self.assertLess(score, URGENCY_CONSIDER_EXIT)

    def test_exit_now_scenario(self):
        # entry=20, current=1, trend=-10, pnl=-20, token=-50, lock=0 → 87
        score = self._urgency(entry_apy=20.0, current_apy=1.0, trend=-10.0, pnl=-20.0, token=-50.0, lock=0)
        self.assertGreaterEqual(score, URGENCY_CONSIDER_EXIT)


# ---------------------------------------------------------------------------
# TestTimingLabel
# ---------------------------------------------------------------------------

class TestTimingLabel(unittest.TestCase):

    def test_zero_is_hold_strong(self):
        self.assertEqual(_timing_label(0.0), "HOLD_STRONG")

    def test_just_below_hold_strong_threshold(self):
        self.assertEqual(_timing_label(URGENCY_HOLD_STRONG - 0.01), "HOLD_STRONG")

    def test_at_hold_monitor_threshold(self):
        self.assertEqual(_timing_label(URGENCY_HOLD_STRONG), "HOLD_MONITOR")

    def test_midrange_hold_monitor(self):
        self.assertEqual(_timing_label(30.0), "HOLD_MONITOR")

    def test_just_below_neutral_threshold(self):
        self.assertEqual(_timing_label(URGENCY_HOLD_MONITOR - 0.01), "HOLD_MONITOR")

    def test_at_neutral_threshold(self):
        self.assertEqual(_timing_label(URGENCY_HOLD_MONITOR), "NEUTRAL")

    def test_midrange_neutral(self):
        self.assertEqual(_timing_label(47.0), "NEUTRAL")

    def test_just_below_consider_exit_threshold(self):
        self.assertEqual(_timing_label(URGENCY_NEUTRAL - 0.01), "NEUTRAL")

    def test_at_consider_exit_threshold(self):
        self.assertEqual(_timing_label(URGENCY_NEUTRAL), "CONSIDER_EXIT")

    def test_midrange_consider_exit(self):
        self.assertEqual(_timing_label(62.0), "CONSIDER_EXIT")

    def test_just_below_exit_now_threshold(self):
        self.assertEqual(_timing_label(URGENCY_CONSIDER_EXIT - 0.01), "CONSIDER_EXIT")

    def test_at_exit_now_threshold(self):
        self.assertEqual(_timing_label(URGENCY_CONSIDER_EXIT), "EXIT_NOW")

    def test_max_urgency_is_exit_now(self):
        self.assertEqual(_timing_label(100.0), "EXIT_NOW")

    def test_all_five_labels_reachable(self):
        labels = {
            _timing_label(0.0),
            _timing_label(25.0),
            _timing_label(47.0),
            _timing_label(62.0),
            _timing_label(80.0),
        }
        self.assertEqual(labels, {"HOLD_STRONG", "HOLD_MONITOR", "NEUTRAL", "CONSIDER_EXIT", "EXIT_NOW"})


# ---------------------------------------------------------------------------
# TestAnalyze  (integration)
# ---------------------------------------------------------------------------

class TestAnalyze(unittest.TestCase):

    def _run(self, position):
        return ProtocolDeFiYieldFarmingExitTimingAdvisor().analyze(position)

    def test_returns_required_keys(self):
        r = self._run(_pos())
        for k in ("protocol_name", "net_exit_value_usd", "opportunity_cost_pct",
                  "days_to_recover_exit_costs", "exit_urgency_score",
                  "timing_label", "lock_remaining_days", "analyzed_at"):
            self.assertIn(k, r)

    def test_protocol_name_in_result(self):
        r = self._run(_pos(protocol_name="Compound"))
        self.assertEqual(r["protocol_name"], "Compound")

    def test_analyzed_at_format(self):
        r = self._run(_pos())
        self.assertRegex(r["analyzed_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_hold_strong_label_end_to_end(self):
        r = self._run(_hold_strong_pos())
        self.assertEqual(r["timing_label"], "HOLD_STRONG")

    def test_exit_now_label_end_to_end(self):
        r = self._run(_exit_now_pos())
        self.assertEqual(r["timing_label"], "EXIT_NOW")

    def test_urgency_bounded_0_100(self):
        r = self._run(_exit_now_pos())
        self.assertGreaterEqual(r["exit_urgency_score"], 0.0)
        self.assertLessEqual(r["exit_urgency_score"], 100.0)

    def test_net_exit_value_correct(self):
        # position=10000, pnl=10%, fee=0%, gas=0 → gross=11000, net=11000
        r = self._run(_pos(position_usd=10000.0, unrealized_pnl_pct=10.0,
                           exit_fee_pct=0.0, gas_cost_exit_usd=0.0))
        self.assertAlmostEqual(r["net_exit_value_usd"], 11000.0)

    def test_lock_days_preserved_in_result(self):
        r = self._run(_pos(lock_remaining_days=14))
        self.assertEqual(r["lock_remaining_days"], 14)

    def test_config_none_accepted(self):
        r = ProtocolDeFiYieldFarmingExitTimingAdvisor().analyze(_pos(), None)
        self.assertIn("timing_label", r)

    def test_config_empty_dict_accepted(self):
        r = ProtocolDeFiYieldFarmingExitTimingAdvisor().analyze(_pos(), {})
        self.assertIn("timing_label", r)

    def test_module_level_analyze_alias(self):
        r = analyze(_pos())
        self.assertIn("timing_label", r)

    def test_invalid_position_raises(self):
        with self.assertRaises(ValueError):
            self._run({})

    def test_opportunity_cost_positive_when_low_apy(self):
        # current=2%, trend=0% → forward=2%, opp_cost=5-2=3%
        r = self._run(_pos(current_apy_pct=2.0, apy_trend_7d_pct=0.0))
        self.assertGreater(r["opportunity_cost_pct"], 0.0)

    def test_opportunity_cost_negative_when_high_apy(self):
        # current=10%, trend=0% → opp_cost=5-10=-5%
        r = self._run(_pos(current_apy_pct=10.0, apy_trend_7d_pct=0.0))
        self.assertLess(r["opportunity_cost_pct"], 0.0)

    def test_days_recover_zero_apy_returns_max(self):
        r = self._run(_pos(current_apy_pct=0.0))
        self.assertEqual(r["days_to_recover_exit_costs"], MAX_DAYS_TO_RECOVER)

    def test_timing_label_is_valid_string(self):
        valid = {"HOLD_STRONG", "HOLD_MONITOR", "NEUTRAL", "CONSIDER_EXIT", "EXIT_NOW"}
        r = self._run(_pos())
        self.assertIn(r["timing_label"], valid)


# ---------------------------------------------------------------------------
# TestLogHelpers
# ---------------------------------------------------------------------------

class TestLogHelpers(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._log_path = os.path.join(self._tmpdir, "test_exit_log.json")

    def test_iso_now_returns_string(self):
        self.assertIsInstance(_iso_now(), str)

    def test_iso_now_format(self):
        self.assertRegex(_iso_now(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_atomic_write_creates_file(self):
        _atomic_write(self._log_path, [{"a": 1}])
        self.assertTrue(os.path.exists(self._log_path))

    def test_atomic_write_content_correct(self):
        data = [{"x": 10}, {"y": 20}]
        _atomic_write(self._log_path, data)
        with open(self._log_path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_atomic_write_overwrites_existing(self):
        _atomic_write(self._log_path, [1])
        _atomic_write(self._log_path, [2, 3])
        with open(self._log_path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, [2, 3])

    def test_init_log_empty_if_not_exists(self):
        result = _init_log(os.path.join(self._tmpdir, "none.json"))
        self.assertEqual(result, [])

    def test_init_log_loads_existing(self):
        _atomic_write(self._log_path, [{"ts": "t"}])
        result = _init_log(self._log_path)
        self.assertEqual(len(result), 1)

    def test_init_log_returns_empty_on_corrupt_json(self):
        with open(self._log_path, "w") as f:
            f.write("{{{invalid")
        result = _init_log(self._log_path)
        self.assertEqual(result, [])

    def test_append_log_creates_entry(self):
        _append_log(_fake_log_result(), log_path=self._log_path)
        entries = _init_log(self._log_path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["protocol_name"], "TestProto")

    def test_append_log_ring_buffer_capped(self):
        fake = _fake_log_result()
        for _ in range(LOG_MAX_ENTRIES + 15):
            _append_log(fake, log_path=self._log_path)
        entries = _init_log(self._log_path)
        self.assertEqual(len(entries), LOG_MAX_ENTRIES)

    def test_append_log_keeps_latest_entries(self):
        for i in range(LOG_MAX_ENTRIES + 5):
            result = dict(_fake_log_result(), protocol_name=f"P{i}")
            _append_log(result, log_path=self._log_path)
        entries = _init_log(self._log_path)
        self.assertEqual(entries[-1]["protocol_name"], f"P{LOG_MAX_ENTRIES + 4}")

    def test_append_log_bad_path_no_crash(self):
        blocker = os.path.join(self._tmpdir, "blocker.txt")
        with open(blocker, "w") as f:
            f.write("x")
        bad_path = os.path.join(blocker, "nested", "log.json")
        _append_log(_fake_log_result(), log_path=bad_path)  # must not raise

    def test_append_log_stores_urgency(self):
        fake = dict(_fake_log_result(), exit_urgency_score=77.5)
        _append_log(fake, log_path=self._log_path)
        entries = _init_log(self._log_path)
        self.assertEqual(entries[0]["exit_urgency_score"], 77.5)


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def _run(self, position):
        return ProtocolDeFiYieldFarmingExitTimingAdvisor().analyze(position)

    def test_zero_position_usd(self):
        # No position, no fees, no gas → net = 0, days = MAX sentinel
        r = self._run(_pos(position_usd=0.0, exit_fee_pct=0.0, gas_cost_exit_usd=0.0))
        self.assertAlmostEqual(r["net_exit_value_usd"], 0.0)
        self.assertEqual(r["days_to_recover_exit_costs"], MAX_DAYS_TO_RECOVER)

    def test_locked_position_lower_urgency(self):
        unlocked = self._run(_pos(lock_remaining_days=0))
        locked = self._run(_pos(lock_remaining_days=100))
        self.assertGreaterEqual(
            unlocked["exit_urgency_score"],
            locked["exit_urgency_score"],
        )

    def test_analysis_does_not_modify_input(self):
        import copy
        p = _pos()
        original = copy.deepcopy(p)
        self._run(p)
        self.assertEqual(p, original)

    def test_entry_apy_zero_no_crash(self):
        r = self._run(_pos(entry_apy_pct=0.0, current_apy_pct=0.0))
        self.assertIn("timing_label", r)

    def test_max_exit_fee_100_pct(self):
        r = self._run(_pos(exit_fee_pct=100.0, gas_cost_exit_usd=0.0))
        # Net = 0 (all eaten by fee)
        self.assertAlmostEqual(r["net_exit_value_usd"], 0.0)

    def test_very_long_position_age_no_crash(self):
        r = self._run(_pos(entry_date_days_ago=3650.0))
        self.assertIn("timing_label", r)

    def test_extreme_negative_token_price_bounded(self):
        r = self._run(_pos(token_price_change_since_entry_pct=-1000.0))
        self.assertLessEqual(r["exit_urgency_score"], 100.0)

    def test_extreme_positive_trend_no_urgency_added(self):
        pos_trend = self._run(_pos(apy_trend_7d_pct=100.0, current_apy_pct=10.0))
        no_trend = self._run(_pos(apy_trend_7d_pct=0.0, current_apy_pct=10.0))
        # Rising trend does not add urgency
        self.assertLessEqual(pos_trend["exit_urgency_score"], no_trend["exit_urgency_score"] + 0.01)

    def test_hold_strong_all_good_signals(self):
        r = self._run(_hold_strong_pos())
        self.assertLess(r["exit_urgency_score"], URGENCY_HOLD_STRONG)


if __name__ == "__main__":
    unittest.main()
