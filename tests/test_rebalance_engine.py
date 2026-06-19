"""tests/test_rebalance_engine.py — 35 tests for RebalanceEngine (MP-1372 v9.88)

Coverage:
  T01–T05  calculate_new_range() — result shape, values, bounds
  T06–T08  rebalance_cost_usd() — constant, value, type
  T09–T12  monthly_rebalance_cost() — multiples, zero, type
  T13–T24  check_position() — None cases, proposal fields, triggers
  T25–T27  breakeven_days() — positivity, type, magnitude
  T28–T31  RebalanceProposal fields — recommendation, il_reset, gas
  T32–T35  check_all() — list result, empty/non-empty cases
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.rs002_position_tracker import (
    LPPosition,
    RS002_SLOTS,
    RS002PositionTracker,
)
from spa_core.analytics.rebalance_engine import RebalanceEngine, RebalanceProposal


# ── helpers ───────────────────────────────────────────────────────────────────

def _tracker_with_btc(
    entry: float = 60_000.0, total_capital: float = 20_000.0
) -> RS002PositionTracker:
    tracker = RS002PositionTracker(total_capital=total_capital)
    tracker.open_position("btc_usd_conc_lp", entry, "2026-06-01")
    return tracker


def _drive_out_of_range(tracker: RS002PositionTracker, slot_id: str,
                         price: float, n_days: int) -> None:
    """Call update_price n_days times with an out-of-range price."""
    for i in range(n_days):
        tracker.update_price(slot_id, price, f"2026-06-{i+2:02d}")


# ── T01–T05: calculate_new_range() ───────────────────────────────────────────

class TestCalculateNewRange(unittest.TestCase):

    def setUp(self):
        self.engine = RebalanceEngine()

    # T01
    def test_T01_returns_tuple(self):
        result = self.engine.calculate_new_range(100.0, 0.30)
        self.assertIsInstance(result, tuple)

    # T02
    def test_T02_btc_30pct_range(self):
        lower, upper = self.engine.calculate_new_range(100.0, 0.30)
        self.assertAlmostEqual(lower, 70.0, places=8)
        self.assertAlmostEqual(upper, 130.0, places=8)

    # T03
    def test_T03_upper_greater_than_lower(self):
        lower, upper = self.engine.calculate_new_range(60_000.0, 0.30)
        self.assertGreater(upper, lower)

    # T04
    def test_T04_lower_equals_price_times_one_minus_pct(self):
        lower, _ = self.engine.calculate_new_range(80_000.0, 0.20)
        self.assertAlmostEqual(lower, 80_000.0 * 0.80, places=6)

    # T05
    def test_T05_upper_equals_price_times_one_plus_pct(self):
        _, upper = self.engine.calculate_new_range(80_000.0, 0.20)
        self.assertAlmostEqual(upper, 80_000.0 * 1.20, places=6)


# ── T06–T08: rebalance_cost_usd() ────────────────────────────────────────────

class TestRebalanceCost(unittest.TestCase):

    def setUp(self):
        self.engine = RebalanceEngine()

    # T06
    def test_T06_cost_equals_gas_eth_times_eth_price(self):
        expected = RebalanceEngine.GAS_ESTIMATE_ETH * RebalanceEngine.ETH_PRICE_USD
        self.assertAlmostEqual(self.engine.rebalance_cost_usd(), expected, places=6)

    # T07
    def test_T07_cost_is_17_5_usd(self):
        # 0.005 ETH * 3500 USD/ETH = 17.5
        self.assertAlmostEqual(self.engine.rebalance_cost_usd(), 17.5, places=6)

    # T08
    def test_T08_cost_returns_float(self):
        self.assertIsInstance(self.engine.rebalance_cost_usd(), float)


# ── T09–T12: monthly_rebalance_cost() ────────────────────────────────────────

class TestMonthlyRebalanceCost(unittest.TestCase):

    def setUp(self):
        self.engine = RebalanceEngine()

    # T09
    def test_T09_two_rebalances(self):
        self.assertAlmostEqual(
            self.engine.monthly_rebalance_cost(2),
            2 * self.engine.rebalance_cost_usd(),
            places=6,
        )

    # T10
    def test_T10_zero_rebalances(self):
        self.assertAlmostEqual(self.engine.monthly_rebalance_cost(0), 0.0, places=6)

    # T11
    def test_T11_one_rebalance(self):
        self.assertAlmostEqual(
            self.engine.monthly_rebalance_cost(1),
            self.engine.rebalance_cost_usd(),
            places=6,
        )

    # T12
    def test_T12_returns_float(self):
        self.assertIsInstance(self.engine.monthly_rebalance_cost(3), float)


# ── T13–T24: check_position() ────────────────────────────────────────────────

class TestCheckPosition(unittest.TestCase):

    def setUp(self):
        self.engine = RebalanceEngine()

    # T13
    def test_T13_returns_none_when_position_in_range_low_il(self):
        tracker = _tracker_with_btc(60_000.0)
        # No price update → in range, IL = 0
        pos = tracker.positions["btc_usd_conc_lp"]
        result = self.engine.check_position(pos)
        self.assertIsNone(result)

    # T14
    def test_T14_returns_none_for_trader_losses_slot(self):
        tracker = RS002PositionTracker(total_capital=20_000.0)
        tracker.open_position("trader_losses", 1.0, "2026-06-01")
        # Drive to out-of-range
        _drive_out_of_range(tracker, "trader_losses", 100.0, 5)
        pos = tracker.positions["trader_losses"]
        result = self.engine.check_position(pos)
        self.assertIsNone(result)

    # T15
    def test_T15_returns_proposal_when_consecutive_out_exceeds_3(self):
        tracker = _tracker_with_btc(60_000.0)
        _drive_out_of_range(tracker, "btc_usd_conc_lp", 90_000.0, 4)
        pos = tracker.positions["btc_usd_conc_lp"]
        result = self.engine.check_position(pos)
        self.assertIsInstance(result, RebalanceProposal)

    # T16
    def test_T16_trigger_is_out_of_range(self):
        tracker = _tracker_with_btc(60_000.0)
        _drive_out_of_range(tracker, "btc_usd_conc_lp", 90_000.0, 4)
        pos = tracker.positions["btc_usd_conc_lp"]
        proposal = self.engine.check_position(pos)
        self.assertEqual(proposal.trigger, "out_of_range")

    # T17
    def test_T17_returns_proposal_when_il_exceeds_threshold(self):
        # 1 update with extreme price → high IL but only 1 consecutive day out
        tracker = _tracker_with_btc(60_000.0)
        _drive_out_of_range(tracker, "btc_usd_conc_lp", 300_000.0, 1)
        pos = tracker.positions["btc_usd_conc_lp"]
        # consecutive_out = 1 (≤ 3) but IL should be > 10%
        self.assertLess(pos.current_il_pct, -10.0)
        result = self.engine.check_position(pos)
        self.assertIsInstance(result, RebalanceProposal)

    # T18
    def test_T18_trigger_is_il_threshold_when_only_il_exceeded(self):
        tracker = _tracker_with_btc(60_000.0)
        _drive_out_of_range(tracker, "btc_usd_conc_lp", 300_000.0, 1)
        pos = tracker.positions["btc_usd_conc_lp"]
        proposal = self.engine.check_position(pos)
        self.assertEqual(proposal.trigger, "il_threshold")

    # T19
    def test_T19_proposal_new_lower_less_than_new_upper(self):
        tracker = _tracker_with_btc(60_000.0)
        _drive_out_of_range(tracker, "btc_usd_conc_lp", 90_000.0, 4)
        pos = tracker.positions["btc_usd_conc_lp"]
        proposal = self.engine.check_position(pos)
        self.assertLess(proposal.new_lower, proposal.new_upper)

    # T20
    def test_T20_proposal_old_lower_matches_position_lower_tick(self):
        tracker = _tracker_with_btc(60_000.0)
        _drive_out_of_range(tracker, "btc_usd_conc_lp", 90_000.0, 4)
        pos = tracker.positions["btc_usd_conc_lp"]
        proposal = self.engine.check_position(pos)
        self.assertAlmostEqual(proposal.old_lower, pos.lower_tick, places=6)

    # T21
    def test_T21_proposal_old_upper_matches_position_upper_tick(self):
        tracker = _tracker_with_btc(60_000.0)
        _drive_out_of_range(tracker, "btc_usd_conc_lp", 90_000.0, 4)
        pos = tracker.positions["btc_usd_conc_lp"]
        proposal = self.engine.check_position(pos)
        self.assertAlmostEqual(proposal.old_upper, pos.upper_tick, places=6)

    # T22
    def test_T22_proposal_estimated_gas_equals_rebalance_cost(self):
        tracker = _tracker_with_btc(60_000.0)
        _drive_out_of_range(tracker, "btc_usd_conc_lp", 90_000.0, 4)
        pos = tracker.positions["btc_usd_conc_lp"]
        proposal = self.engine.check_position(pos)
        self.assertAlmostEqual(
            proposal.estimated_gas_usd,
            self.engine.rebalance_cost_usd(),
            places=6,
        )

    # T23
    def test_T23_expected_il_reset_is_zero(self):
        tracker = _tracker_with_btc(60_000.0)
        _drive_out_of_range(tracker, "btc_usd_conc_lp", 90_000.0, 4)
        pos = tracker.positions["btc_usd_conc_lp"]
        proposal = self.engine.check_position(pos)
        self.assertAlmostEqual(proposal.expected_il_reset, 0.0, places=8)

    # T24
    def test_T24_returns_none_when_in_range_and_il_within_threshold(self):
        # Price moves slightly within range → IL is small
        tracker = _tracker_with_btc(60_000.0)
        tracker.update_price("btc_usd_conc_lp", 62_000.0, "2026-06-02")
        pos = tracker.positions["btc_usd_conc_lp"]
        result = self.engine.check_position(pos)
        self.assertIsNone(result)


# ── T25–T27: breakeven_days() ────────────────────────────────────────────────

class TestBreakevenDays(unittest.TestCase):

    def setUp(self):
        self.engine = RebalanceEngine()
        self.tracker = _tracker_with_btc(60_000.0)
        _drive_out_of_range(self.tracker, "btc_usd_conc_lp", 90_000.0, 4)
        self.pos = self.tracker.positions["btc_usd_conc_lp"]
        self.proposal = self.engine.check_position(self.pos)

    # T25
    def test_T25_breakeven_days_greater_than_zero(self):
        result = self.engine.breakeven_days(self.pos, self.proposal)
        self.assertGreater(result, 0)

    # T26
    def test_T26_breakeven_days_returns_int(self):
        result = self.engine.breakeven_days(self.pos, self.proposal)
        self.assertIsInstance(result, int)

    # T27
    def test_T27_breakeven_days_btc_is_reasonable(self):
        # BTC slot: $12K capital, 42% gross APY → daily fee ≈ $13.7
        # Gas ≈ $17.5 → breakeven ≈ 2 days (definitely < 365)
        result = self.engine.breakeven_days(self.pos, self.proposal)
        self.assertLess(result, 365)


# ── T28–T31: RebalanceProposal fields ────────────────────────────────────────

class TestProposalFields(unittest.TestCase):

    VALID_RECOMMENDATIONS = {"REBALANCE", "WAIT", "CLOSE"}

    def setUp(self):
        self.engine = RebalanceEngine()
        self.tracker = _tracker_with_btc(60_000.0)
        _drive_out_of_range(self.tracker, "btc_usd_conc_lp", 90_000.0, 4)
        self.pos = self.tracker.positions["btc_usd_conc_lp"]
        self.proposal = self.engine.check_position(self.pos)

    # T28
    def test_T28_recommendation_is_valid_string(self):
        self.assertIn(self.proposal.recommendation, self.VALID_RECOMMENDATIONS)

    # T29
    def test_T29_recommendation_rebalance_for_btc_low_breakeven(self):
        # BTC: breakeven ≈ 2 days ≤ 30 → "REBALANCE"
        self.assertEqual(self.proposal.recommendation, "REBALANCE")

    # T30
    def test_T30_expected_il_reset_is_float(self):
        self.assertIsInstance(self.proposal.expected_il_reset, float)

    # T31
    def test_T31_expected_il_reset_value_is_zero(self):
        self.assertAlmostEqual(self.proposal.expected_il_reset, 0.0, places=8)


# ── T32–T35: check_all() ─────────────────────────────────────────────────────

class TestCheckAll(unittest.TestCase):

    def setUp(self):
        self.engine = RebalanceEngine()

    # T32
    def test_T32_check_all_returns_list(self):
        tracker = _tracker_with_btc()
        result = self.engine.check_all(tracker)
        self.assertIsInstance(result, list)

    # T33
    def test_T33_check_all_empty_when_all_in_range(self):
        tracker = _tracker_with_btc(60_000.0)
        # No price updates → all in range
        result = self.engine.check_all(tracker)
        self.assertEqual(result, [])

    # T34
    def test_T34_check_all_returns_proposals_for_out_of_range(self):
        tracker = _tracker_with_btc(60_000.0)
        _drive_out_of_range(tracker, "btc_usd_conc_lp", 90_000.0, 4)
        result = self.engine.check_all(tracker)
        self.assertGreater(len(result), 0)
        self.assertIsInstance(result[0], RebalanceProposal)

    # T35
    def test_T35_check_all_handles_empty_tracker(self):
        tracker = RS002PositionTracker(total_capital=20_000.0)
        # No positions opened
        result = self.engine.check_all(tracker)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
