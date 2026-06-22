"""
MP-831 — Unit tests for DeFiTaxLotTracker.
stdlib unittest only; ≥ 65 tests.
Run: python3 -m unittest spa_core.tests.test_defi_tax_lot_tracker -v
"""

import json
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

from spa_core.analytics.defi_tax_lot_tracker import (
    analyze,
    save_log,
    load_log,
    MAX_ENTRIES,
    _parse_date,
    _process_disposal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_lot(lot_id="L1", acquired_date=None, cost_basis_usd=1000.0,
             quantity=1.0, current_price_usd=1200.0):
    if acquired_date is None:
        acquired_date = (date.today() - timedelta(days=400)).isoformat()
    return {
        "lot_id": lot_id,
        "acquired_date": acquired_date,
        "cost_basis_usd": cost_basis_usd,
        "quantity": quantity,
        "current_price_usd": current_price_usd,
    }


def make_position(protocol="Aave", lots=None, disposal=None):
    if lots is None:
        lots = [make_lot()]
    return {"protocol": protocol, "lots": lots, "disposal": disposal}


def make_disposal(quantity=0.5, proceeds_usd=700.0, method="FIFO"):
    return {"quantity": quantity, "proceeds_usd": proceeds_usd, "method": method}


def long_term_date():
    """Date > 365 days ago = long-term."""
    return (date.today() - timedelta(days=400)).isoformat()


def short_term_date():
    """Date < 365 days ago = short-term."""
    return (date.today() - timedelta(days=100)).isoformat()


# ---------------------------------------------------------------------------
# 1. _parse_date
# ---------------------------------------------------------------------------

class TestParseDate(unittest.TestCase):
    def test_parse_valid_date(self):
        d = _parse_date("2024-01-15")
        self.assertEqual(d, date(2024, 1, 15))

    def test_parse_recent_date(self):
        d = _parse_date("2026-06-01")
        self.assertEqual(d, date(2026, 6, 1))

    def test_parse_returns_date_object(self):
        d = _parse_date("2020-12-31")
        self.assertIsInstance(d, date)

    def test_parse_leap_year(self):
        d = _parse_date("2024-02-29")
        self.assertEqual(d.month, 2)
        self.assertEqual(d.day, 29)


# ---------------------------------------------------------------------------
# 2. Basic analyze() structure
# ---------------------------------------------------------------------------

class TestAnalyzeStructure(unittest.TestCase):
    def test_returns_dict(self):
        result = analyze([])
        self.assertIsInstance(result, dict)

    def test_has_positions_key(self):
        result = analyze([])
        self.assertIn("positions", result)

    def test_has_portfolio_summary_key(self):
        result = analyze([])
        self.assertIn("portfolio_summary", result)

    def test_has_timestamp(self):
        result = analyze([])
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)

    def test_timestamp_is_recent(self):
        before = time.time()
        result = analyze([])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_empty_positions(self):
        result = analyze([])
        self.assertEqual(result["positions"], [])

    def test_portfolio_summary_keys(self):
        result = analyze([])
        summary = result["portfolio_summary"]
        required = [
            "total_cost_basis_usd",
            "total_current_value_usd",
            "total_unrealized_gain_usd",
            "total_realized_gain_usd",
            "total_short_term_gain_usd",
            "total_long_term_gain_usd",
        ]
        for k in required:
            self.assertIn(k, summary)

    def test_empty_portfolio_summary_zeros(self):
        result = analyze([])
        s = result["portfolio_summary"]
        self.assertEqual(s["total_cost_basis_usd"], 0.0)
        self.assertEqual(s["total_current_value_usd"], 0.0)
        self.assertEqual(s["total_unrealized_gain_usd"], 0.0)
        self.assertEqual(s["total_realized_gain_usd"], 0.0)

    def test_position_result_keys(self):
        pos = make_position()
        result = analyze([pos])
        p = result["positions"][0]
        for k in ["protocol", "total_cost_basis_usd", "total_current_value_usd",
                  "unrealized_gain_usd", "unrealized_gain_pct", "lot_count", "disposal_result"]:
            self.assertIn(k, p)

    def test_protocol_pass_through(self):
        pos = make_position(protocol="Compound")
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["protocol"], "Compound")


# ---------------------------------------------------------------------------
# 3. Unrealized gain calculations
# ---------------------------------------------------------------------------

class TestUnrealizedGains(unittest.TestCase):
    def test_positive_unrealized_gain(self):
        # cost=1000, qty=1, price=1200 → gain=200
        lot = make_lot(cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1200.0)
        pos = make_position(lots=[lot])
        result = analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["total_cost_basis_usd"], 1000.0)
        self.assertAlmostEqual(p["total_current_value_usd"], 1200.0)
        self.assertAlmostEqual(p["unrealized_gain_usd"], 200.0)
        self.assertAlmostEqual(p["unrealized_gain_pct"], 20.0)

    def test_negative_unrealized_gain(self):
        lot = make_lot(cost_basis_usd=1000.0, quantity=1.0, current_price_usd=800.0)
        pos = make_position(lots=[lot])
        result = analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["unrealized_gain_usd"], -200.0)
        self.assertAlmostEqual(p["unrealized_gain_pct"], -20.0)

    def test_zero_unrealized_gain(self):
        lot = make_lot(cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1000.0)
        pos = make_position(lots=[lot])
        result = analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["unrealized_gain_usd"], 0.0)
        self.assertAlmostEqual(p["unrealized_gain_pct"], 0.0)

    def test_zero_cost_basis_pct_is_zero(self):
        lot = make_lot(cost_basis_usd=0.0, quantity=1.0, current_price_usd=100.0)
        pos = make_position(lots=[lot])
        result = analyze([pos])
        p = result["positions"][0]
        self.assertEqual(p["unrealized_gain_pct"], 0.0)

    def test_current_value_is_qty_times_price(self):
        lot = make_lot(cost_basis_usd=500.0, quantity=5.0, current_price_usd=150.0)
        pos = make_position(lots=[lot])
        result = analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["total_current_value_usd"], 750.0)

    def test_multiple_lots_sum_cost_basis(self):
        l1 = make_lot("L1", cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1100.0)
        l2 = make_lot("L2", cost_basis_usd=2000.0, quantity=2.0, current_price_usd=1100.0)
        pos = make_position(lots=[l1, l2])
        result = analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["total_cost_basis_usd"], 3000.0)
        self.assertAlmostEqual(p["total_current_value_usd"], 3300.0)

    def test_lot_count(self):
        lots = [make_lot(f"L{i}") for i in range(5)]
        pos = make_position(lots=lots)
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["lot_count"], 5)

    def test_empty_lots_zeros(self):
        pos = make_position(lots=[])
        result = analyze([pos])
        p = result["positions"][0]
        self.assertEqual(p["total_cost_basis_usd"], 0.0)
        self.assertEqual(p["total_current_value_usd"], 0.0)
        self.assertEqual(p["unrealized_gain_usd"], 0.0)
        self.assertEqual(p["lot_count"], 0)

    def test_no_disposal_result_none(self):
        pos = make_position(disposal=None)
        result = analyze([pos])
        self.assertIsNone(result["positions"][0]["disposal_result"])


# ---------------------------------------------------------------------------
# 4. FIFO disposal
# ---------------------------------------------------------------------------

class TestFIFODisposal(unittest.TestCase):
    def test_fifo_disposal_result_not_none(self):
        lot = make_lot("L1", acquired_date=long_term_date(), cost_basis_usd=1000.0,
                       quantity=2.0, current_price_usd=600.0)
        disposal = make_disposal(quantity=1.0, proceeds_usd=700.0, method="FIFO")
        pos = make_position(lots=[lot], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        self.assertIsNotNone(dr)

    def test_fifo_disposal_keys(self):
        lot = make_lot("L1", acquired_date=long_term_date(), cost_basis_usd=1000.0,
                       quantity=2.0, current_price_usd=600.0)
        disposal = make_disposal(quantity=1.0, proceeds_usd=700.0, method="FIFO")
        pos = make_position(lots=[lot], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        for k in ["method", "quantity_sold", "proceeds_usd", "cost_basis_sold_usd",
                  "realized_gain_usd", "short_term_gain_usd", "long_term_gain_usd", "lots_used"]:
            self.assertIn(k, dr)

    def test_fifo_method_label(self):
        lot = make_lot("L1", acquired_date=long_term_date(), cost_basis_usd=1000.0,
                       quantity=2.0, current_price_usd=600.0)
        disposal = make_disposal(quantity=1.0, proceeds_usd=700.0, method="FIFO")
        pos = make_position(lots=[lot], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        self.assertEqual(dr["method"], "FIFO")

    def test_fifo_uses_oldest_lot_first(self):
        # Lot1 is older, Lot2 is newer; FIFO should use Lot1 first
        older = make_lot("L1", acquired_date=long_term_date(),
                         cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1200.0)
        newer = make_lot("L2", acquired_date=short_term_date(),
                         cost_basis_usd=2000.0, quantity=1.0, current_price_usd=1200.0)
        disposal = make_disposal(quantity=1.0, proceeds_usd=1200.0, method="FIFO")
        pos = make_position(lots=[newer, older], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        # FIFO: uses L1 (older) first
        self.assertIn("L1", dr["lots_used"])
        self.assertNotIn("L2", dr["lots_used"])

    def test_fifo_single_lot_full_disposal(self):
        lot = make_lot("L1", acquired_date=long_term_date(),
                       cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1200.0)
        disposal = make_disposal(quantity=1.0, proceeds_usd=1200.0, method="FIFO")
        pos = make_position(lots=[lot], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        self.assertAlmostEqual(dr["quantity_sold"], 1.0)
        self.assertAlmostEqual(dr["proceeds_usd"], 1200.0)
        self.assertAlmostEqual(dr["cost_basis_sold_usd"], 1000.0)
        self.assertAlmostEqual(dr["realized_gain_usd"], 200.0)

    def test_fifo_partial_lot_disposal(self):
        # cost=1000 for 2 units; sell 1 unit for 600 → cost_basis_sold=500
        lot = make_lot("L1", acquired_date=long_term_date(),
                       cost_basis_usd=1000.0, quantity=2.0, current_price_usd=600.0)
        disposal = make_disposal(quantity=1.0, proceeds_usd=600.0, method="FIFO")
        pos = make_position(lots=[lot], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        self.assertAlmostEqual(dr["cost_basis_sold_usd"], 500.0)
        self.assertAlmostEqual(dr["realized_gain_usd"], 100.0)

    def test_fifo_long_term_gain_classification(self):
        # acquired 400 days ago → long-term (> 365)
        lot = make_lot("L1", acquired_date=long_term_date(),
                       cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1500.0)
        disposal = make_disposal(quantity=1.0, proceeds_usd=1500.0, method="FIFO")
        pos = make_position(lots=[lot], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        self.assertAlmostEqual(dr["long_term_gain_usd"], 500.0)
        self.assertAlmostEqual(dr["short_term_gain_usd"], 0.0)

    def test_fifo_short_term_gain_classification(self):
        # acquired 100 days ago → short-term (< 365)
        lot = make_lot("L1", acquired_date=short_term_date(),
                       cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1500.0)
        disposal = make_disposal(quantity=1.0, proceeds_usd=1500.0, method="FIFO")
        pos = make_position(lots=[lot], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        self.assertAlmostEqual(dr["short_term_gain_usd"], 500.0)
        self.assertAlmostEqual(dr["long_term_gain_usd"], 0.0)

    def test_fifo_multiple_lots_uses_oldest_first(self):
        old = make_lot("L1", acquired_date=(date.today() - timedelta(days=500)).isoformat(),
                       cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1200.0)
        mid = make_lot("L2", acquired_date=(date.today() - timedelta(days=300)).isoformat(),
                       cost_basis_usd=1500.0, quantity=1.0, current_price_usd=1200.0)
        new_ = make_lot("L3", acquired_date=(date.today() - timedelta(days=50)).isoformat(),
                        cost_basis_usd=1100.0, quantity=1.0, current_price_usd=1200.0)
        disposal = make_disposal(quantity=2.0, proceeds_usd=2400.0, method="FIFO")
        pos = make_position(lots=[new_, mid, old], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        self.assertIn("L1", dr["lots_used"])
        self.assertIn("L2", dr["lots_used"])
        self.assertNotIn("L3", dr["lots_used"])

    def test_fifo_lots_used_list(self):
        lot = make_lot("LOT-A", acquired_date=long_term_date(),
                       cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1200.0)
        disposal = make_disposal(quantity=1.0, proceeds_usd=1200.0, method="FIFO")
        pos = make_position(lots=[lot], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        self.assertEqual(dr["lots_used"], ["LOT-A"])

    def test_fifo_quantity_exceeds_available_caps(self):
        lot = make_lot("L1", acquired_date=long_term_date(),
                       cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1200.0)
        disposal = make_disposal(quantity=999.0, proceeds_usd=1200.0, method="FIFO")
        pos = make_position(lots=[lot], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        # Capped at available 1.0
        self.assertAlmostEqual(dr["quantity_sold"], 1.0)


# ---------------------------------------------------------------------------
# 5. LIFO disposal
# ---------------------------------------------------------------------------

class TestLIFODisposal(unittest.TestCase):
    def test_lifo_uses_newest_lot_first(self):
        older = make_lot("L1", acquired_date=long_term_date(),
                         cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1200.0)
        newer = make_lot("L2", acquired_date=short_term_date(),
                         cost_basis_usd=2000.0, quantity=1.0, current_price_usd=1200.0)
        disposal = make_disposal(quantity=1.0, proceeds_usd=1200.0, method="LIFO")
        pos = make_position(lots=[older, newer], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        # LIFO: uses L2 (newer) first
        self.assertIn("L2", dr["lots_used"])
        self.assertNotIn("L1", dr["lots_used"])

    def test_lifo_method_label(self):
        lot = make_lot("L1", acquired_date=long_term_date(),
                       cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1200.0)
        disposal = make_disposal(quantity=1.0, proceeds_usd=1200.0, method="LIFO")
        pos = make_position(lots=[lot], disposal=disposal)
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["disposal_result"]["method"], "LIFO")

    def test_lifo_short_term_from_new_lot(self):
        # LIFO picks up the new lot (short-term)
        newer = make_lot("L2", acquired_date=short_term_date(),
                         cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1500.0)
        older = make_lot("L1", acquired_date=long_term_date(),
                         cost_basis_usd=2000.0, quantity=1.0, current_price_usd=1500.0)
        disposal = make_disposal(quantity=1.0, proceeds_usd=1500.0, method="LIFO")
        pos = make_position(lots=[older, newer], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        self.assertAlmostEqual(dr["short_term_gain_usd"], 500.0, places=2)
        self.assertAlmostEqual(dr["long_term_gain_usd"], 0.0, places=2)

    def test_lifo_vs_fifo_different_cost_basis(self):
        older = make_lot("L1", acquired_date=(date.today() - timedelta(days=400)).isoformat(),
                         cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1200.0)
        newer = make_lot("L2", acquired_date=(date.today() - timedelta(days=50)).isoformat(),
                         cost_basis_usd=1100.0, quantity=1.0, current_price_usd=1200.0)
        disposal_fifo = make_disposal(quantity=1.0, proceeds_usd=1200.0, method="FIFO")
        disposal_lifo = make_disposal(quantity=1.0, proceeds_usd=1200.0, method="LIFO")
        pos_fifo = make_position(lots=[older, newer], disposal=disposal_fifo)
        pos_lifo = make_position(lots=[older, newer], disposal=disposal_lifo)
        fifo_dr = analyze([pos_fifo])["positions"][0]["disposal_result"]
        lifo_dr = analyze([pos_lifo])["positions"][0]["disposal_result"]
        # FIFO sells oldest (cost=1000), gain=200; LIFO sells newest (cost=1100), gain=100
        self.assertAlmostEqual(fifo_dr["realized_gain_usd"], 200.0, places=2)
        self.assertAlmostEqual(lifo_dr["realized_gain_usd"], 100.0, places=2)

    def test_lifo_quantity_exceeds_caps(self):
        lot = make_lot("L1", acquired_date=long_term_date(),
                       cost_basis_usd=1000.0, quantity=2.0, current_price_usd=600.0)
        disposal = make_disposal(quantity=999.0, proceeds_usd=600.0, method="LIFO")
        pos = make_position(lots=[lot], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        self.assertAlmostEqual(dr["quantity_sold"], 2.0)


# ---------------------------------------------------------------------------
# 6. Mixed short/long-term gains in single disposal
# ---------------------------------------------------------------------------

class TestMixedGains(unittest.TestCase):
    def test_two_lots_mixed_term(self):
        # Sell 2 lots: one long-term, one short-term
        old_lot = make_lot("L1", acquired_date=(date.today() - timedelta(days=400)).isoformat(),
                           cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1200.0)
        new_lot = make_lot("L2", acquired_date=(date.today() - timedelta(days=50)).isoformat(),
                           cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1200.0)
        disposal = make_disposal(quantity=2.0, proceeds_usd=2400.0, method="FIFO")
        pos = make_position(lots=[new_lot, old_lot], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        # Both sell for 200 gain each, but different term
        total = dr["short_term_gain_usd"] + dr["long_term_gain_usd"]
        self.assertAlmostEqual(total, dr["realized_gain_usd"], places=6)
        self.assertAlmostEqual(dr["realized_gain_usd"], 400.0, places=2)

    def test_realized_gain_equals_short_plus_long(self):
        old_lot = make_lot("L1", acquired_date=(date.today() - timedelta(days=400)).isoformat(),
                           cost_basis_usd=500.0, quantity=1.0, current_price_usd=700.0)
        new_lot = make_lot("L2", acquired_date=(date.today() - timedelta(days=100)).isoformat(),
                           cost_basis_usd=800.0, quantity=1.0, current_price_usd=700.0)
        disposal = make_disposal(quantity=2.0, proceeds_usd=1400.0, method="FIFO")
        pos = make_position(lots=[old_lot, new_lot], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        self.assertAlmostEqual(
            dr["realized_gain_usd"],
            dr["short_term_gain_usd"] + dr["long_term_gain_usd"],
            places=6
        )


# ---------------------------------------------------------------------------
# 7. Custom short_term_days config
# ---------------------------------------------------------------------------

class TestCustomShortTermDays(unittest.TestCase):
    def test_custom_threshold_30_days(self):
        # Acquired 50 days ago → long-term with threshold=30
        lot = make_lot("L1", acquired_date=(date.today() - timedelta(days=50)).isoformat(),
                       cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1500.0)
        disposal = make_disposal(quantity=1.0, proceeds_usd=1500.0, method="FIFO")
        pos = make_position(lots=[lot], disposal=disposal)
        result = analyze([pos], config={"short_term_days": 30})
        dr = result["positions"][0]["disposal_result"]
        # 50 days > 30 → long term
        self.assertAlmostEqual(dr["long_term_gain_usd"], 500.0, places=2)
        self.assertAlmostEqual(dr["short_term_gain_usd"], 0.0)

    def test_custom_threshold_large_makes_everything_short_term(self):
        # Acquired 400 days ago → short-term with threshold=1000
        lot = make_lot("L1", acquired_date=(date.today() - timedelta(days=400)).isoformat(),
                       cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1500.0)
        disposal = make_disposal(quantity=1.0, proceeds_usd=1500.0, method="FIFO")
        pos = make_position(lots=[lot], disposal=disposal)
        result = analyze([pos], config={"short_term_days": 1000})
        dr = result["positions"][0]["disposal_result"]
        self.assertAlmostEqual(dr["short_term_gain_usd"], 500.0, places=2)
        self.assertAlmostEqual(dr["long_term_gain_usd"], 0.0)

    def test_default_config_none(self):
        pos = make_position()
        result = analyze([pos], config=None)
        self.assertIn("positions", result)


# ---------------------------------------------------------------------------
# 8. Multiple positions
# ---------------------------------------------------------------------------

class TestMultiplePositions(unittest.TestCase):
    def test_two_positions_returned(self):
        p1 = make_position(protocol="Aave")
        p2 = make_position(protocol="Compound")
        result = analyze([p1, p2])
        self.assertEqual(len(result["positions"]), 2)

    def test_portfolio_sums_cost_basis(self):
        l1 = make_lot(cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1000.0)
        l2 = make_lot(cost_basis_usd=2000.0, quantity=1.0, current_price_usd=2000.0)
        p1 = make_position(protocol="A", lots=[l1])
        p2 = make_position(protocol="B", lots=[l2])
        result = analyze([p1, p2])
        self.assertAlmostEqual(result["portfolio_summary"]["total_cost_basis_usd"], 3000.0)

    def test_portfolio_sums_unrealized(self):
        l1 = make_lot(cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1100.0)
        l2 = make_lot(cost_basis_usd=2000.0, quantity=1.0, current_price_usd=2200.0)
        p1 = make_position(protocol="A", lots=[l1])
        p2 = make_position(protocol="B", lots=[l2])
        result = analyze([p1, p2])
        self.assertAlmostEqual(result["portfolio_summary"]["total_unrealized_gain_usd"], 300.0)

    def test_portfolio_sums_realized_gains(self):
        lot = make_lot("L1", acquired_date=long_term_date(),
                       cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1200.0)
        disp = make_disposal(quantity=1.0, proceeds_usd=1200.0, method="FIFO")
        p1 = make_position(protocol="A", lots=[lot], disposal=disp)
        p2 = make_position(protocol="B", lots=[lot], disposal=disp)
        result = analyze([p1, p2])
        self.assertAlmostEqual(result["portfolio_summary"]["total_realized_gain_usd"], 400.0, places=2)

    def test_protocol_names_preserved(self):
        p1 = make_position(protocol="Aave")
        p2 = make_position(protocol="Morpho")
        result = analyze([p1, p2])
        protocols = [p["protocol"] for p in result["positions"]]
        self.assertIn("Aave", protocols)
        self.assertIn("Morpho", protocols)


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_zero_qty_lots_skipped_in_disposal(self):
        zero_lot = make_lot("L0", acquired_date=long_term_date(),
                            cost_basis_usd=1000.0, quantity=0.0, current_price_usd=1200.0)
        good_lot = make_lot("L1", acquired_date=long_term_date(),
                            cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1200.0)
        disposal = make_disposal(quantity=1.0, proceeds_usd=1200.0, method="FIFO")
        pos = make_position(lots=[zero_lot, good_lot], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        self.assertNotIn("L0", dr["lots_used"])
        self.assertIn("L1", dr["lots_used"])

    def test_disposal_zero_quantity_returns_none(self):
        lot = make_lot("L1", acquired_date=long_term_date(),
                       cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1200.0)
        disposal = make_disposal(quantity=0.0, proceeds_usd=0.0, method="FIFO")
        pos = make_position(lots=[lot], disposal=disposal)
        result = analyze([pos])
        self.assertIsNone(result["positions"][0]["disposal_result"])

    def test_no_lots_empty_position(self):
        pos = make_position(lots=[])
        result = analyze([pos])
        p = result["positions"][0]
        self.assertEqual(p["total_cost_basis_usd"], 0.0)
        self.assertEqual(p["lot_count"], 0)

    def test_large_number_positions(self):
        positions = [make_position(protocol=f"Protocol-{i}") for i in range(50)]
        result = analyze(positions)
        self.assertEqual(len(result["positions"]), 50)

    def test_disposal_none_realized_zeros(self):
        pos = make_position(disposal=None)
        result = analyze([pos])
        s = result["portfolio_summary"]
        self.assertEqual(s["total_realized_gain_usd"], 0.0)
        self.assertEqual(s["total_short_term_gain_usd"], 0.0)
        self.assertEqual(s["total_long_term_gain_usd"], 0.0)

    def test_loss_on_disposal(self):
        lot = make_lot("L1", acquired_date=long_term_date(),
                       cost_basis_usd=1000.0, quantity=1.0, current_price_usd=800.0)
        disposal = make_disposal(quantity=1.0, proceeds_usd=800.0, method="FIFO")
        pos = make_position(lots=[lot], disposal=disposal)
        result = analyze([pos])
        dr = result["positions"][0]["disposal_result"]
        self.assertAlmostEqual(dr["realized_gain_usd"], -200.0, places=2)


# ---------------------------------------------------------------------------
# 10. _process_disposal directly
# ---------------------------------------------------------------------------

class TestProcessDisposalDirect(unittest.TestCase):
    def test_empty_lots_returns_zero_quantity_sold(self):
        # no lots → total_available=0 → qty_to_sell capped to 0
        disposal = {"quantity": 1.0, "proceeds_usd": 100.0, "method": "FIFO"}
        result = _process_disposal([], disposal, 365, date.today())
        # qty_to_sell capped to 0; returns dict with zero values
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["quantity_sold"], 0.0)
        self.assertAlmostEqual(result["realized_gain_usd"], 0.0)
        self.assertEqual(result["lots_used"], [])

    def test_single_lot_fifo_proceeds_equal_proceeds(self):
        lot = make_lot("L1", acquired_date=long_term_date(),
                       cost_basis_usd=500.0, quantity=1.0, current_price_usd=700.0)
        disposal = {"quantity": 1.0, "proceeds_usd": 700.0, "method": "FIFO"}
        result = _process_disposal([lot], disposal, 365, date.today())
        self.assertAlmostEqual(result["proceeds_usd"], 700.0)

    def test_fifo_spans_multiple_lots(self):
        lots = [
            make_lot("L1", acquired_date=(date.today() - timedelta(days=400)).isoformat(),
                     cost_basis_usd=100.0, quantity=1.0, current_price_usd=150.0),
            make_lot("L2", acquired_date=(date.today() - timedelta(days=300)).isoformat(),
                     cost_basis_usd=200.0, quantity=2.0, current_price_usd=150.0),
        ]
        disposal = {"quantity": 2.0, "proceeds_usd": 300.0, "method": "FIFO"}
        result = _process_disposal(lots, disposal, 365, date.today())
        self.assertIn("L1", result["lots_used"])
        self.assertIn("L2", result["lots_used"])


# ---------------------------------------------------------------------------
# 11. save_log / load_log
# ---------------------------------------------------------------------------

class TestSaveLoadLog(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "data" / "tax_lot_log.json"

    def test_save_creates_file(self):
        result = analyze([])
        save_log(result, self.data_file)
        self.assertTrue(self.data_file.exists())

    def test_save_creates_list(self):
        result = analyze([])
        save_log(result, self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertIsInstance(data, list)

    def test_save_appends_entry(self):
        result = analyze([])
        save_log(result, self.data_file)
        save_log(result, self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), 2)

    def test_ring_buffer_max_entries(self):
        result = analyze([])
        for _ in range(MAX_ENTRIES + 5):
            save_log(result, self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_load_log_empty_on_missing_file(self):
        missing = Path(self.tmp_dir) / "nonexistent.json"
        data = load_log(missing)
        self.assertEqual(data, [])

    def test_load_log_returns_list(self):
        result = analyze([])
        save_log(result, self.data_file)
        data = load_log(self.data_file)
        self.assertIsInstance(data, list)

    def test_atomic_write_no_leftover_tmp(self):
        result = analyze([])
        save_log(result, self.data_file)
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_load_log_corrupt_file_returns_empty(self):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.data_file.write_text("NOT_JSON")
        data = load_log(self.data_file)
        self.assertEqual(data, [])

    def test_saved_entry_has_timestamp(self):
        result = analyze([])
        save_log(result, self.data_file)
        data = load_log(self.data_file)
        self.assertIn("timestamp", data[0])

    def test_save_preserves_portfolio_summary(self):
        lot = make_lot(cost_basis_usd=5000.0, quantity=2.0, current_price_usd=3000.0)
        pos = make_position(lots=[lot])
        result = analyze([pos])
        save_log(result, self.data_file)
        loaded = load_log(self.data_file)
        self.assertIn("portfolio_summary", loaded[0])


# ---------------------------------------------------------------------------
# 12. Portfolio summary aggregation
# ---------------------------------------------------------------------------

class TestPortfolioSummaryAggregation(unittest.TestCase):
    def test_total_current_value_sum(self):
        l1 = make_lot(cost_basis_usd=1000.0, quantity=2.0, current_price_usd=600.0)
        l2 = make_lot(cost_basis_usd=500.0, quantity=1.0, current_price_usd=400.0)
        p1 = make_position(protocol="A", lots=[l1])
        p2 = make_position(protocol="B", lots=[l2])
        result = analyze([p1, p2])
        s = result["portfolio_summary"]
        self.assertAlmostEqual(s["total_current_value_usd"], 1200.0 + 400.0)

    def test_total_short_long_sum_equals_realized(self):
        lot1 = make_lot("L1", acquired_date=long_term_date(),
                        cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1200.0)
        lot2 = make_lot("L2", acquired_date=short_term_date(),
                        cost_basis_usd=1000.0, quantity=1.0, current_price_usd=1200.0)
        d1 = make_disposal(quantity=1.0, proceeds_usd=1200.0, method="FIFO")
        d2 = make_disposal(quantity=1.0, proceeds_usd=1200.0, method="FIFO")
        p1 = make_position(protocol="A", lots=[lot1], disposal=d1)
        p2 = make_position(protocol="B", lots=[lot2], disposal=d2)
        result = analyze([p1, p2])
        s = result["portfolio_summary"]
        self.assertAlmostEqual(
            s["total_realized_gain_usd"],
            s["total_short_term_gain_usd"] + s["total_long_term_gain_usd"],
            places=6
        )


if __name__ == "__main__":
    unittest.main()
