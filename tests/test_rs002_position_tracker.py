"""tests/test_rs002_position_tracker.py — 40 tests for RS002PositionTracker (MP-1371 v9.87)

Coverage:
  T01–T15  open_position() — construction, range bounds, capital, validation
  T16–T25  update_price() — in-range / out-of-range counters, fees, IL
  T26–T31  current_il() — zero at entry, negative outside range, trader_losses
  T32–T34  net_apy() — type, value at entry, all slots
  T35–T38  portfolio_summary() — keys, types, capital value
  T39–T40  needs_rebalance() + save()
"""
from __future__ import annotations

import os
import sys
import tempfile
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


# ── helpers ───────────────────────────────────────────────────────────────────

def _tracker() -> RS002PositionTracker:
    return RS002PositionTracker(total_capital=20_000.0)


def _open_btc(tracker: RS002PositionTracker, entry: float = 60_000.0) -> LPPosition:
    return tracker.open_position("btc_usd_conc_lp", entry, "2026-06-01")


# ── T01–T15: open_position() ──────────────────────────────────────────────────

class TestOpenPosition(unittest.TestCase):

    def setUp(self):
        self.tracker = _tracker()

    # T01
    def test_T01_open_position_returns_lp_position(self):
        pos = _open_btc(self.tracker)
        self.assertIsInstance(pos, LPPosition)

    # T02
    def test_T02_upper_tick_greater_than_lower_tick(self):
        pos = _open_btc(self.tracker)
        self.assertGreater(pos.upper_tick, pos.lower_tick)

    # T03
    def test_T03_lower_tick_calculation_btc(self):
        pos = _open_btc(self.tracker, 60_000.0)
        expected = 60_000.0 * (1.0 - 0.30)
        self.assertAlmostEqual(pos.lower_tick, expected, places=6)

    # T04
    def test_T04_upper_tick_calculation_btc(self):
        pos = _open_btc(self.tracker, 60_000.0)
        expected = 60_000.0 * (1.0 + 0.30)
        self.assertAlmostEqual(pos.upper_tick, expected, places=6)

    # T05
    def test_T05_capital_usd_equals_weight_times_total(self):
        pos = _open_btc(self.tracker)
        expected = 20_000.0 * RS002_SLOTS["btc_usd_conc_lp"]["weight"]
        self.assertAlmostEqual(pos.capital_usd, expected, places=6)

    # T06
    def test_T06_entry_date_stored(self):
        pos = _open_btc(self.tracker)
        self.assertEqual(pos.entry_date, "2026-06-01")

    # T07
    def test_T07_current_price_equals_entry_price_after_open(self):
        pos = _open_btc(self.tracker, 60_000.0)
        self.assertAlmostEqual(pos.current_price, 60_000.0, places=6)

    # T08
    def test_T08_days_in_range_zero_after_open(self):
        pos = _open_btc(self.tracker)
        self.assertEqual(pos.days_in_range, 0)

    # T09
    def test_T09_days_out_of_range_zero_after_open(self):
        pos = _open_btc(self.tracker)
        self.assertEqual(pos.days_out_of_range, 0)

    # T10
    def test_T10_accumulated_fees_zero_after_open(self):
        pos = _open_btc(self.tracker)
        self.assertAlmostEqual(pos.accumulated_fees_usd, 0.0, places=10)

    # T11
    def test_T11_current_il_pct_zero_after_open(self):
        pos = _open_btc(self.tracker)
        self.assertAlmostEqual(pos.current_il_pct, 0.0, places=10)

    # T12
    def test_T12_can_open_all_four_slots(self):
        entries = {
            "btc_usd_conc_lp": 60_000.0,
            "rwa_lp": 1.0,
            "trader_losses": 1.0,
            "stablecoin_floor": 1.0,
        }
        for slot_id, entry in entries.items():
            pos = self.tracker.open_position(slot_id, entry, "2026-06-01")
            self.assertIsInstance(pos, LPPosition, msg=f"slot={slot_id}")

    # T13
    def test_T13_unknown_slot_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.tracker.open_position("unknown_slot", 60_000.0, "2026-06-01")

    # T14
    def test_T14_rwa_lp_range_bounds(self):
        pos = self.tracker.open_position("rwa_lp", 1.0, "2026-06-01")
        self.assertAlmostEqual(pos.lower_tick, 1.0 * (1 - 0.05), places=8)
        self.assertAlmostEqual(pos.upper_tick, 1.0 * (1 + 0.05), places=8)

    # T15
    def test_T15_stablecoin_floor_range_bounds(self):
        pos = self.tracker.open_position("stablecoin_floor", 1.0, "2026-06-01")
        self.assertAlmostEqual(pos.lower_tick, 1.0 * (1 - 0.002), places=8)
        self.assertAlmostEqual(pos.upper_tick, 1.0 * (1 + 0.002), places=8)


# ── T16–T25: update_price() ───────────────────────────────────────────────────

class TestUpdatePrice(unittest.TestCase):

    def setUp(self):
        self.tracker = _tracker()
        _open_btc(self.tracker, 60_000.0)
        # btc range: [42000, 78000]

    # T16
    def test_T16_in_range_increments_days_in_range(self):
        self.tracker.update_price("btc_usd_conc_lp", 60_000.0, "2026-06-02")
        pos = self.tracker.positions["btc_usd_conc_lp"]
        self.assertEqual(pos.days_in_range, 1)

    # T17
    def test_T17_in_range_multiple_correct_count(self):
        for i in range(5):
            self.tracker.update_price("btc_usd_conc_lp", 60_000.0, f"2026-06-0{i+2}")
        pos = self.tracker.positions["btc_usd_conc_lp"]
        self.assertEqual(pos.days_in_range, 5)

    # T18
    def test_T18_out_of_range_increments_days_out(self):
        self.tracker.update_price("btc_usd_conc_lp", 90_000.0, "2026-06-02")  # > 78000
        pos = self.tracker.positions["btc_usd_conc_lp"]
        self.assertEqual(pos.days_out_of_range, 1)

    # T19
    def test_T19_out_of_range_multiple_correct_count(self):
        for i in range(3):
            self.tracker.update_price("btc_usd_conc_lp", 90_000.0, f"2026-06-0{i+2}")
        pos = self.tracker.positions["btc_usd_conc_lp"]
        self.assertEqual(pos.days_out_of_range, 3)

    # T20
    def test_T20_in_range_fees_accumulate(self):
        self.tracker.update_price("btc_usd_conc_lp", 60_000.0, "2026-06-02")
        pos = self.tracker.positions["btc_usd_conc_lp"]
        self.assertGreater(pos.accumulated_fees_usd, 0.0)

    # T21
    def test_T21_out_of_range_fees_do_not_accumulate(self):
        self.tracker.update_price("btc_usd_conc_lp", 90_000.0, "2026-06-02")
        pos = self.tracker.positions["btc_usd_conc_lp"]
        self.assertAlmostEqual(pos.accumulated_fees_usd, 0.0, places=10)

    # T22
    def test_T22_consecutive_out_days_increments(self):
        for i in range(3):
            self.tracker.update_price("btc_usd_conc_lp", 90_000.0, f"2026-06-0{i+2}")
        pos = self.tracker.positions["btc_usd_conc_lp"]
        self.assertEqual(pos.consecutive_out_days, 3)

    # T23
    def test_T23_consecutive_out_days_resets_on_return_in_range(self):
        for i in range(3):
            self.tracker.update_price("btc_usd_conc_lp", 90_000.0, f"2026-06-0{i+2}")
        # Back in range
        self.tracker.update_price("btc_usd_conc_lp", 60_000.0, "2026-06-05")
        pos = self.tracker.positions["btc_usd_conc_lp"]
        self.assertEqual(pos.consecutive_out_days, 0)

    # T24
    def test_T24_current_price_updated(self):
        self.tracker.update_price("btc_usd_conc_lp", 65_000.0, "2026-06-02")
        pos = self.tracker.positions["btc_usd_conc_lp"]
        self.assertAlmostEqual(pos.current_price, 65_000.0, places=6)

    # T25
    def test_T25_current_il_pct_updated_after_price_move(self):
        self.tracker.update_price("btc_usd_conc_lp", 70_000.0, "2026-06-02")
        pos = self.tracker.positions["btc_usd_conc_lp"]
        # Should be a float (possibly 0 or small negative inside range)
        self.assertIsInstance(pos.current_il_pct, float)


# ── T26–T31: current_il() ─────────────────────────────────────────────────────

class TestCurrentIL(unittest.TestCase):

    def setUp(self):
        self.tracker = _tracker()

    # T26
    def test_T26_current_il_zero_at_entry_price(self):
        _open_btc(self.tracker, 60_000.0)
        il = self.tracker.current_il("btc_usd_conc_lp")
        self.assertAlmostEqual(il, 0.0, places=8)

    # T27
    def test_T27_current_il_negative_when_price_above_upper_range(self):
        _open_btc(self.tracker, 60_000.0)
        self.tracker.update_price("btc_usd_conc_lp", 200_000.0, "2026-06-02")
        il = self.tracker.current_il("btc_usd_conc_lp")
        self.assertLess(il, 0.0)

    # T28
    def test_T28_current_il_negative_when_price_below_lower_range(self):
        _open_btc(self.tracker, 60_000.0)
        self.tracker.update_price("btc_usd_conc_lp", 10_000.0, "2026-06-02")
        il = self.tracker.current_il("btc_usd_conc_lp")
        self.assertLess(il, 0.0)

    # T29
    def test_T29_current_il_zero_for_trader_losses(self):
        self.tracker.open_position("trader_losses", 1.0, "2026-06-01")
        il = self.tracker.current_il("trader_losses")
        self.assertAlmostEqual(il, 0.0, places=10)

    # T30
    def test_T30_current_il_within_valid_range(self):
        _open_btc(self.tracker, 60_000.0)
        self.tracker.update_price("btc_usd_conc_lp", 500_000.0, "2026-06-02")
        il = self.tracker.current_il("btc_usd_conc_lp")
        self.assertGreaterEqual(il, -100.0)
        self.assertLessEqual(il, 0.0)

    # T31
    def test_T31_current_il_returns_float(self):
        _open_btc(self.tracker)
        il = self.tracker.current_il("btc_usd_conc_lp")
        self.assertIsInstance(il, float)


# ── T32–T34: net_apy() ────────────────────────────────────────────────────────

class TestNetAPY(unittest.TestCase):

    def setUp(self):
        self.tracker = _tracker()

    # T32
    def test_T32_net_apy_returns_float(self):
        _open_btc(self.tracker)
        result = self.tracker.net_apy("btc_usd_conc_lp")
        self.assertIsInstance(result, float)

    # T33
    def test_T33_net_apy_at_entry_equals_gross_fee_apy(self):
        _open_btc(self.tracker, 60_000.0)
        # At entry: price == entry_price → IL = 0; days = 0 → il_drag = 0
        net = self.tracker.net_apy("btc_usd_conc_lp")
        gross = RS002_SLOTS["btc_usd_conc_lp"]["gross_fee_apy"]
        self.assertAlmostEqual(net, gross, places=6)

    # T34
    def test_T34_net_apy_all_slots_return_float(self):
        entries = {"btc_usd_conc_lp": 60_000.0, "rwa_lp": 1.0,
                   "trader_losses": 1.0, "stablecoin_floor": 1.0}
        for slot_id, entry in entries.items():
            self.tracker.open_position(slot_id, entry, "2026-06-01")
            result = self.tracker.net_apy(slot_id)
            self.assertIsInstance(result, float, msg=f"slot={slot_id}")


# ── T35–T38: portfolio_summary() ─────────────────────────────────────────────

class TestPortfolioSummary(unittest.TestCase):

    def setUp(self):
        self.tracker = _tracker()
        _open_btc(self.tracker)
        self.tracker.open_position("rwa_lp", 1.0, "2026-06-01")
        self.tracker.open_position("trader_losses", 1.0, "2026-06-01")
        self.tracker.open_position("stablecoin_floor", 1.0, "2026-06-01")

    # T35
    def test_T35_portfolio_summary_has_blended_net_apy(self):
        summary = self.tracker.portfolio_summary()
        self.assertIn("blended_net_apy", summary)

    # T36
    def test_T36_portfolio_summary_has_total_capital(self):
        summary = self.tracker.portfolio_summary()
        self.assertIn("total_capital", summary)

    # T37
    def test_T37_portfolio_summary_has_total_fees_usd(self):
        summary = self.tracker.portfolio_summary()
        self.assertIn("total_fees_usd", summary)

    # T38
    def test_T38_blended_net_apy_is_float(self):
        summary = self.tracker.portfolio_summary()
        self.assertIsInstance(summary["blended_net_apy"], float)


# ── T39–T40: needs_rebalance() + save() ──────────────────────────────────────

class TestNeedsRebalanceAndSave(unittest.TestCase):

    def setUp(self):
        self.tracker = _tracker()
        _open_btc(self.tracker, 60_000.0)
        # btc range: lower=42000, upper=78000

    # T39
    def test_T39_needs_rebalance_false_initially(self):
        self.assertFalse(self.tracker.needs_rebalance("btc_usd_conc_lp"))

    # T40
    def test_T40_needs_rebalance_true_after_4_consecutive_out_and_save_creates_file(self):
        # needs_rebalance after 4 days
        for i in range(4):
            self.tracker.update_price("btc_usd_conc_lp", 90_000.0, f"2026-06-0{i+2}")
        self.assertTrue(self.tracker.needs_rebalance("btc_usd_conc_lp"))

        # save() creates file
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker2 = RS002PositionTracker(
                tracker_path=os.path.join(tmpdir, "rs002", "positions.json"),
                total_capital=20_000.0,
            )
            _open_btc(tracker2)
            tracker2.save()
            self.assertTrue(os.path.exists(tracker2.tracker_path))


if __name__ == "__main__":
    unittest.main()
