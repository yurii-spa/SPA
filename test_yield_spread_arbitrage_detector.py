"""
Tests for MP-841 YieldSpreadArbitrageDetector
(spa_core/analytics/yield_spread_arbitrage_detector.py)

Pure stdlib unittest — do NOT use pytest or any external deps.
Run: python3 -m unittest spa_core.tests.test_yield_spread_arbitrage_detector -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.analytics.yield_spread_arbitrage_detector import (  # noqa: E402
    analyze,
    run,
    _viability,
    _risk_note,
    _safe_float,
    _load_log,
    _save_log,
    _RING_BUFFER_MAX,
    _DEFAULT_MIN_SPREAD_PCT,
    _DEFAULT_MIN_NET_PROFIT_USD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lend(protocol, asset, apy, liquidity=1_000_000, min_pos=1_000, gas=15.0):
    return {
        "protocol": protocol, "asset": asset, "side": "LEND",
        "apy": apy, "available_liquidity_usd": liquidity,
        "min_position_usd": min_pos, "gas_cost_usd": gas,
    }


def _borrow(protocol, asset, apy, liquidity=1_000_000, min_pos=1_000, gas=15.0):
    return {
        "protocol": protocol, "asset": asset, "side": "BORROW",
        "apy": apy, "available_liquidity_usd": liquidity,
        "min_position_usd": min_pos, "gas_cost_usd": gas,
    }


def _simple_pair(lend_apy=5.0, borrow_apy=3.0, liquidity=500_000,
                 gas=10.0, min_pos=1_000):
    """Return a single LEND+BORROW pair on USDC across two protocols."""
    return [
        _lend("ProtocolA", "USDC", lend_apy, liquidity, min_pos, gas),
        _borrow("ProtocolB", "USDC", borrow_apy, liquidity, min_pos, gas),
    ]


# ===========================================================================
# 1. Constants / defaults
# ===========================================================================

class TestConstants(unittest.TestCase):

    def test_ring_buffer_max(self):
        self.assertEqual(_RING_BUFFER_MAX, 100)

    def test_default_min_spread(self):
        self.assertAlmostEqual(_DEFAULT_MIN_SPREAD_PCT, 0.5)

    def test_default_min_net_profit(self):
        self.assertAlmostEqual(_DEFAULT_MIN_NET_PROFIT_USD, 10.0)


# ===========================================================================
# 2. _safe_float
# ===========================================================================

class TestSafeFloat(unittest.TestCase):

    def test_int(self):
        self.assertEqual(_safe_float(5), 5.0)

    def test_float(self):
        self.assertAlmostEqual(_safe_float(3.14), 3.14)

    def test_string_number(self):
        self.assertAlmostEqual(_safe_float("2.5"), 2.5)

    def test_none_default(self):
        self.assertEqual(_safe_float(None), 0.0)

    def test_none_custom_default(self):
        self.assertEqual(_safe_float(None, 99.0), 99.0)

    def test_bad_string(self):
        self.assertEqual(_safe_float("abc"), 0.0)

    def test_zero(self):
        self.assertEqual(_safe_float(0), 0.0)

    def test_negative(self):
        self.assertAlmostEqual(_safe_float(-1.5), -1.5)


# ===========================================================================
# 3. _viability
# ===========================================================================

class TestViability(unittest.TestCase):

    def test_excellent(self):
        # net_spread >= 2.0 and profit >= min
        v = _viability(net_spread_pct=2.5, net_annual_profit_usd=100.0,
                       min_net_profit_usd=10.0)
        self.assertEqual(v, "EXCELLENT")

    def test_good(self):
        v = _viability(1.5, 50.0, 10.0)
        self.assertEqual(v, "GOOD")

    def test_marginal(self):
        v = _viability(0.5, 20.0, 10.0)
        self.assertEqual(v, "MARGINAL")

    def test_marginal_zero_spread(self):
        v = _viability(0.0, 10.0, 10.0)
        self.assertEqual(v, "MARGINAL")

    def test_unviable_profit_below_min(self):
        v = _viability(5.0, 9.0, 10.0)
        self.assertEqual(v, "UNVIABLE")

    def test_unviable_negative_profit(self):
        v = _viability(-1.0, -50.0, 10.0)
        self.assertEqual(v, "UNVIABLE")

    def test_exactly_at_excellent_threshold(self):
        v = _viability(2.0, 100.0, 10.0)
        self.assertEqual(v, "EXCELLENT")

    def test_exactly_at_good_threshold(self):
        v = _viability(1.0, 100.0, 10.0)
        self.assertEqual(v, "GOOD")

    def test_profit_exactly_at_min(self):
        # profit == min_net_profit → not UNVIABLE
        v = _viability(1.5, 10.0, 10.0)
        self.assertNotEqual(v, "UNVIABLE")


# ===========================================================================
# 4. _risk_note
# ===========================================================================

class TestRiskNote(unittest.TestCase):

    def test_excellent_note(self):
        note = _risk_note("EXCELLENT", "USDC", 3.0)
        self.assertIn("Strong arbitrage", note)
        self.assertIn("USDC", note)
        self.assertIn("3.00%", note)

    def test_good_note(self):
        note = _risk_note("GOOD", "ETH", 1.5)
        self.assertIn("Good spread", note)
        self.assertIn("ETH", note)

    def test_marginal_note(self):
        note = _risk_note("MARGINAL", "DAI", 0.6)
        self.assertIn("Thin margin", note)
        self.assertIn("DAI", note)

    def test_unviable_note(self):
        note = _risk_note("UNVIABLE", "USDC", 0.5)
        self.assertIn("Gas costs eat spread", note)
        self.assertIn("USDC", note)


# ===========================================================================
# 5. analyze() — empty / edge inputs
# ===========================================================================

class TestAnalyzeEmpty(unittest.TestCase):

    def test_empty_markets(self):
        result = analyze([])
        self.assertEqual(result["opportunities"], [])
        self.assertIsNone(result["best_opportunity"])
        self.assertEqual(result["total_opportunities"], 0)
        self.assertEqual(result["viable_count"], 0)
        self.assertEqual(result["assets_analyzed"], [])
        self.assertIn("timestamp", result)

    def test_none_markets(self):
        result = analyze(None)
        self.assertEqual(result["opportunities"], [])

    def test_only_lend_no_borrow(self):
        markets = [_lend("A", "USDC", 5.0)]
        result = analyze(markets)
        self.assertEqual(result["opportunities"], [])
        self.assertEqual(result["assets_analyzed"], ["USDC"])

    def test_only_borrow_no_lend(self):
        markets = [_borrow("A", "USDC", 3.0)]
        result = analyze(markets)
        self.assertEqual(result["opportunities"], [])

    def test_same_protocol_skipped(self):
        markets = [
            _lend("SameProtocol", "USDC", 5.0),
            _borrow("SameProtocol", "USDC", 3.0),
        ]
        result = analyze(markets)
        self.assertEqual(result["opportunities"], [])

    def test_lend_apy_not_greater_than_borrow_apy(self):
        # lend 3% < borrow 5% → no opportunity
        markets = _simple_pair(lend_apy=3.0, borrow_apy=5.0)
        result = analyze(markets)
        self.assertEqual(result["opportunities"], [])

    def test_equal_apy_skipped(self):
        markets = _simple_pair(lend_apy=4.0, borrow_apy=4.0)
        result = analyze(markets)
        self.assertEqual(result["opportunities"], [])

    def test_spread_below_min_threshold_skipped(self):
        # gross spread 0.3 < default min 0.5
        markets = _simple_pair(lend_apy=3.3, borrow_apy=3.0)
        result = analyze(markets)
        self.assertEqual(result["opportunities"], [])


# ===========================================================================
# 6. analyze() — opportunity detection
# ===========================================================================

class TestAnalyzeOpportunities(unittest.TestCase):

    def test_single_pair_detected(self):
        markets = _simple_pair(lend_apy=6.0, borrow_apy=3.0)
        result = analyze(markets)
        self.assertEqual(result["total_opportunities"], 1)
        opp = result["opportunities"][0]
        self.assertEqual(opp["asset"], "USDC")
        self.assertEqual(opp["lend_protocol"], "ProtocolA")
        self.assertEqual(opp["borrow_protocol"], "ProtocolB")

    def test_gross_spread_computed(self):
        markets = _simple_pair(lend_apy=7.0, borrow_apy=2.0)
        opp = analyze(markets)["opportunities"][0]
        self.assertAlmostEqual(opp["gross_spread_pct"], 5.0, places=6)

    def test_max_position_is_min_of_liquidity(self):
        markets = [
            _lend("A", "USDC", 6.0, liquidity=300_000),
            _borrow("B", "USDC", 3.0, liquidity=500_000),
        ]
        opp = analyze(markets)["opportunities"][0]
        self.assertAlmostEqual(opp["max_position_usd"], 300_000.0)

    def test_gas_total(self):
        markets = [
            _lend("A", "USDC", 6.0, gas=20.0),
            _borrow("B", "USDC", 3.0, gas=15.0),
        ]
        opp = analyze(markets)["opportunities"][0]
        self.assertAlmostEqual(opp["gas_total_usd"], 35.0)

    def test_net_spread_pct(self):
        liquidity = 1_000_000.0
        gas_lend = 10.0
        gas_borrow = 10.0
        gas_total = gas_lend + gas_borrow
        lend_apy = 6.0
        borrow_apy = 3.0
        gross = lend_apy - borrow_apy  # 3.0
        gas_drag = (gas_total / liquidity) * 100.0
        expected_net = gross - gas_drag
        markets = [
            _lend("A", "USDC", lend_apy, liquidity, 1000, gas_lend),
            _borrow("B", "USDC", borrow_apy, liquidity, 1000, gas_borrow),
        ]
        opp = analyze(markets)["opportunities"][0]
        self.assertAlmostEqual(opp["net_spread_pct"], expected_net, places=6)

    def test_estimated_annual_profit(self):
        liq = 500_000.0
        lend_apy = 5.0
        borrow_apy = 2.0
        gas = 10.0
        gross = 3.0
        gas_drag = (gas * 2 / liq) * 100
        net_spread = gross - gas_drag
        expected = (net_spread / 100.0) * liq
        markets = [
            _lend("A", "USDC", lend_apy, liq, 1000, gas),
            _borrow("B", "USDC", borrow_apy, liq, 1000, gas),
        ]
        opp = analyze(markets)["opportunities"][0]
        self.assertAlmostEqual(opp["estimated_annual_profit_usd"], expected, places=4)

    def test_net_annual_profit_subtracts_gas(self):
        markets = _simple_pair(lend_apy=6.0, borrow_apy=3.0, gas=10.0,
                               liquidity=1_000_000)
        opp = analyze(markets)["opportunities"][0]
        expected = opp["estimated_annual_profit_usd"] - opp["gas_total_usd"]
        self.assertAlmostEqual(opp["net_annual_profit_usd"], expected, places=6)

    def test_viability_excellent(self):
        # Large liquidity → gas drag negligible; spread=10%
        markets = [
            _lend("A", "USDC", 12.0, liquidity=10_000_000, gas=5.0),
            _borrow("B", "USDC", 2.0, liquidity=10_000_000, gas=5.0),
        ]
        opp = analyze(markets)["opportunities"][0]
        self.assertEqual(opp["viability"], "EXCELLENT")

    def test_viability_good(self):
        # net_spread between 1.0 and 2.0
        markets = [
            _lend("A", "USDC", 4.5, liquidity=1_000_000, gas=0.0),
            _borrow("B", "USDC", 3.0, liquidity=1_000_000, gas=0.0),
        ]
        opp = analyze(markets)["opportunities"][0]
        # gross=1.5, gas_drag=0 → net_spread=1.5 → GOOD
        self.assertEqual(opp["viability"], "GOOD")

    def test_viability_marginal(self):
        # net_spread between 0 and 1.0 and profit >= min
        markets = [
            _lend("A", "USDC", 3.6, liquidity=1_000_000, gas=0.0),
            _borrow("B", "USDC", 3.0, liquidity=1_000_000, gas=0.0),
        ]
        opp = analyze(markets)["opportunities"][0]
        # gross=0.6, net=0.6, profit=6000 → MARGINAL
        self.assertEqual(opp["viability"], "MARGINAL")

    def test_viability_unviable_low_profit(self):
        # Very high gas relative to position
        markets = [
            _lend("A", "USDC", 6.0, liquidity=100.0, min_pos=50, gas=50.0),
            _borrow("B", "USDC", 3.0, liquidity=100.0, min_pos=50, gas=50.0),
        ]
        opp = analyze(markets)["opportunities"][0]
        self.assertEqual(opp["viability"], "UNVIABLE")

    def test_best_opportunity_is_most_profitable_viable(self):
        markets = [
            # pair 1: high profit
            _lend("A", "USDC", 10.0, liquidity=5_000_000, gas=10.0),
            _borrow("B", "USDC", 2.0, liquidity=5_000_000, gas=10.0),
            # pair 2: lower profit
            _lend("C", "USDC", 4.0, liquidity=100_000, gas=5.0),
            _borrow("D", "USDC", 3.0, liquidity=100_000, gas=5.0),
        ]
        result = analyze(markets)
        best = result["best_opportunity"]
        self.assertIsNotNone(best)
        self.assertEqual(best["lend_protocol"], "A")

    def test_best_opportunity_none_if_all_unviable(self):
        markets = [
            _lend("A", "USDC", 6.0, liquidity=10.0, min_pos=5, gas=100.0),
            _borrow("B", "USDC", 3.0, liquidity=10.0, min_pos=5, gas=100.0),
        ]
        result = analyze(markets)
        self.assertIsNone(result["best_opportunity"])

    def test_sorted_by_net_profit_descending(self):
        markets = [
            # smaller
            _lend("A", "USDC", 5.0, liquidity=100_000, gas=0.0),
            _borrow("B", "USDC", 3.0, liquidity=100_000, gas=0.0),
            # larger (different asset so no cross-pairing)
            _lend("C", "ETH", 5.0, liquidity=1_000_000, gas=0.0),
            _borrow("D", "ETH", 3.0, liquidity=1_000_000, gas=0.0),
        ]
        result = analyze(markets)
        profits = [o["net_annual_profit_usd"] for o in result["opportunities"]]
        self.assertEqual(profits, sorted(profits, reverse=True))

    def test_assets_analyzed_sorted(self):
        markets = [
            _lend("A", "ETH", 5.0),
            _lend("A", "USDC", 6.0),
        ]
        result = analyze(markets)
        self.assertEqual(result["assets_analyzed"], ["ETH", "USDC"])

    def test_viable_count(self):
        markets = [
            # viable
            _lend("A", "USDC", 10.0, liquidity=5_000_000, gas=5.0),
            _borrow("B", "USDC", 2.0, liquidity=5_000_000, gas=5.0),
            # unviable — gas eats everything
            _lend("C", "USDC", 6.0, liquidity=20.0, min_pos=10, gas=100.0),
            _borrow("D", "USDC", 3.0, liquidity=20.0, min_pos=10, gas=100.0),
        ]
        result = analyze(markets)
        self.assertEqual(result["viable_count"], 1)

    def test_multiple_assets(self):
        markets = [
            _lend("A", "USDC", 6.0),
            _borrow("B", "USDC", 3.0),
            _lend("A", "DAI", 5.5),
            _borrow("B", "DAI", 2.5),
        ]
        result = analyze(markets)
        assets = {o["asset"] for o in result["opportunities"]}
        self.assertIn("USDC", assets)
        self.assertIn("DAI", assets)

    def test_min_position_check_fails(self):
        # max_position=100, min_pos_A=200 → skip
        markets = [
            _lend("A", "USDC", 6.0, liquidity=100.0, min_pos=200.0),
            _borrow("B", "USDC", 3.0, liquidity=100.0, min_pos=1.0),
        ]
        result = analyze(markets)
        self.assertEqual(result["total_opportunities"], 0)

    def test_min_position_check_borrow_fails(self):
        markets = [
            _lend("A", "USDC", 6.0, liquidity=100.0, min_pos=1.0),
            _borrow("B", "USDC", 3.0, liquidity=100.0, min_pos=200.0),
        ]
        result = analyze(markets)
        self.assertEqual(result["total_opportunities"], 0)

    def test_timestamp_is_recent(self):
        result = analyze([])
        self.assertAlmostEqual(result["timestamp"], time.time(), delta=5.0)

    def test_multiple_pairs_same_asset(self):
        markets = [
            _lend("A", "USDC", 8.0, liquidity=500_000),
            _lend("B", "USDC", 6.0, liquidity=500_000),
            _borrow("C", "USDC", 3.0, liquidity=500_000),
            _borrow("D", "USDC", 2.0, liquidity=500_000),
        ]
        result = analyze(markets)
        # A vs C, A vs D, B vs C, B vs D = 4 pairs
        self.assertEqual(result["total_opportunities"], 4)

    def test_spread_exactly_at_min_threshold(self):
        # spread == 0.5 = min → included
        markets = _simple_pair(lend_apy=3.5, borrow_apy=3.0)
        result = analyze(markets)
        self.assertEqual(result["total_opportunities"], 1)

    def test_spread_just_below_min_threshold(self):
        # spread = 0.499 < 0.5 → excluded
        markets = _simple_pair(lend_apy=3.499, borrow_apy=3.0)
        result = analyze(markets)
        self.assertEqual(result["total_opportunities"], 0)

    def test_custom_min_spread_config(self):
        # default spread=0.5 with custom config min_spread=1.0 → excluded
        markets = _simple_pair(lend_apy=3.5, borrow_apy=3.0)
        result = analyze(markets, config={"min_spread_pct": 1.0})
        self.assertEqual(result["total_opportunities"], 0)

    def test_custom_min_net_profit_config(self):
        # make a borderline opportunity
        markets = [
            _lend("A", "USDC", 5.0, liquidity=200_000, gas=0.0),
            _borrow("B", "USDC", 3.0, liquidity=200_000, gas=0.0),
        ]
        # net profit = 2%/100 * 200_000 - 0 = 4000 → viable at min=10
        r1 = analyze(markets, config={"min_net_profit_usd": 10.0})
        self.assertNotEqual(r1["viable_count"], 0)
        # raise min to 10M → unviable
        r2 = analyze(markets, config={"min_net_profit_usd": 10_000_000.0})
        self.assertEqual(r2["viable_count"], 0)

    def test_empty_protocol_string_ok(self):
        # Should not crash; protocol="" is valid (just empty string)
        markets = [
            {"protocol": "", "asset": "USDC", "side": "LEND",
             "apy": 5.0, "available_liquidity_usd": 500_000,
             "min_position_usd": 0, "gas_cost_usd": 0},
            {"protocol": "B", "asset": "USDC", "side": "BORROW",
             "apy": 3.0, "available_liquidity_usd": 500_000,
             "min_position_usd": 0, "gas_cost_usd": 0},
        ]
        result = analyze(markets)
        self.assertEqual(result["total_opportunities"], 1)

    def test_market_without_asset_key(self):
        # Market missing 'asset' → skipped
        markets = [
            {"protocol": "A", "side": "LEND", "apy": 5.0,
             "available_liquidity_usd": 500_000, "min_position_usd": 0,
             "gas_cost_usd": 0},
            _borrow("B", "USDC", 3.0),
        ]
        result = analyze(markets)
        self.assertEqual(result["total_opportunities"], 0)

    def test_missing_numeric_fields_default_to_zero(self):
        markets = [
            {"protocol": "A", "asset": "USDC", "side": "LEND",
             "apy": 5.0},
            _borrow("B", "USDC", 3.0),
        ]
        # Should not crash
        result = analyze(markets)
        self.assertIsInstance(result, dict)

    def test_zero_max_position_gas_drag_sentinel(self):
        # both liquidities = 0, but min_pos = 0 too
        markets = [
            {"protocol": "A", "asset": "USDC", "side": "LEND", "apy": 5.0,
             "available_liquidity_usd": 0, "min_position_usd": 0,
             "gas_cost_usd": 10.0},
            {"protocol": "B", "asset": "USDC", "side": "BORROW", "apy": 3.0,
             "available_liquidity_usd": 0, "min_position_usd": 0,
             "gas_cost_usd": 10.0},
        ]
        result = analyze(markets)
        # max_position=0 → gas_drag=999.0 → net_spread hugely negative → UNVIABLE
        if result["opportunities"]:
            self.assertEqual(result["opportunities"][0]["viability"], "UNVIABLE")

    def test_risk_note_in_opportunity(self):
        markets = _simple_pair(lend_apy=10.0, borrow_apy=2.0,
                               liquidity=5_000_000, gas=5.0)
        opp = analyze(markets)["opportunities"][0]
        self.assertIsInstance(opp["risk_note"], str)
        self.assertTrue(len(opp["risk_note"]) > 0)

    def test_lend_apy_borrow_apy_in_opportunity(self):
        markets = _simple_pair(lend_apy=7.5, borrow_apy=2.5)
        opp = analyze(markets)["opportunities"][0]
        self.assertAlmostEqual(opp["lend_apy"], 7.5)
        self.assertAlmostEqual(opp["borrow_apy"], 2.5)

    def test_cross_asset_no_pair(self):
        # USDC lend vs ETH borrow → different assets → no pair
        markets = [
            _lend("A", "USDC", 5.0),
            _borrow("B", "ETH", 3.0),
        ]
        result = analyze(markets)
        self.assertEqual(result["total_opportunities"], 0)


# ===========================================================================
# 7. _load_log / _save_log
# ===========================================================================

class TestLogPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.log_path = self.tmp_dir / "yield_spread_arb_log.json"

    def test_load_nonexistent(self):
        result = _load_log(self.log_path)
        self.assertEqual(result, [])

    def test_save_and_load_roundtrip(self):
        data = [{"foo": 1}, {"bar": 2}]
        _save_log(self.log_path, data)
        loaded = _load_log(self.log_path)
        self.assertEqual(loaded, data)

    def test_ring_buffer_cap(self):
        data = [{"i": i} for i in range(150)]
        _save_log(self.log_path, data)
        loaded = _load_log(self.log_path)
        self.assertEqual(len(loaded), _RING_BUFFER_MAX)
        # Should keep the most recent entries
        self.assertEqual(loaded[-1]["i"], 149)

    def test_atomic_write_file_valid_json(self):
        _save_log(self.log_path, [{"test": True}])
        with open(self.log_path) as f:
            parsed = json.load(f)
        self.assertEqual(parsed, [{"test": True}])

    def test_load_corrupt_file_returns_empty(self):
        self.log_path.write_text("not valid json")
        result = _load_log(self.log_path)
        self.assertEqual(result, [])

    def test_load_non_list_json_returns_empty(self):
        self.log_path.write_text('{"not": "a list"}')
        result = _load_log(self.log_path)
        self.assertEqual(result, [])

    def test_save_preserves_exactly_100(self):
        data = [{"i": i} for i in range(100)]
        _save_log(self.log_path, data)
        loaded = _load_log(self.log_path)
        self.assertEqual(len(loaded), 100)


# ===========================================================================
# 8. run() — persistence integration
# ===========================================================================

class TestRun(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def test_run_creates_log(self):
        markets = _simple_pair(lend_apy=6.0, borrow_apy=3.0)
        run(markets, data_dir=self.tmp_dir)
        log_path = Path(self.tmp_dir) / "yield_spread_arb_log.json"
        self.assertTrue(log_path.exists())

    def test_run_returns_analysis_dict(self):
        markets = _simple_pair(lend_apy=6.0, borrow_apy=3.0)
        result = run(markets, data_dir=self.tmp_dir)
        self.assertIn("opportunities", result)
        self.assertIn("timestamp", result)

    def test_run_accumulates_log_entries(self):
        markets = _simple_pair(lend_apy=5.0, borrow_apy=3.0)
        run(markets, data_dir=self.tmp_dir)
        run(markets, data_dir=self.tmp_dir)
        log_path = Path(self.tmp_dir) / "yield_spread_arb_log.json"
        with open(log_path) as f:
            log = json.load(f)
        self.assertEqual(len(log), 2)

    def test_run_ring_buffer_capped(self):
        markets = _simple_pair(lend_apy=5.0, borrow_apy=3.0)
        for _ in range(110):
            run(markets, data_dir=self.tmp_dir)
        log_path = Path(self.tmp_dir) / "yield_spread_arb_log.json"
        with open(log_path) as f:
            log = json.load(f)
        self.assertLessEqual(len(log), _RING_BUFFER_MAX)

    def test_run_with_empty_markets(self):
        result = run([], data_dir=self.tmp_dir)
        self.assertEqual(result["total_opportunities"], 0)


# ===========================================================================
# 9. Result structure completeness
# ===========================================================================

class TestResultStructure(unittest.TestCase):

    def test_all_required_top_level_keys(self):
        result = analyze([])
        required = {
            "opportunities", "best_opportunity", "total_opportunities",
            "viable_count", "assets_analyzed", "timestamp",
        }
        self.assertTrue(required.issubset(set(result.keys())))

    def test_opportunity_has_all_required_fields(self):
        markets = _simple_pair(lend_apy=6.0, borrow_apy=3.0,
                               liquidity=1_000_000, gas=10.0)
        result = analyze(markets)
        opp = result["opportunities"][0]
        required = {
            "asset", "lend_protocol", "borrow_protocol",
            "lend_apy", "borrow_apy", "gross_spread_pct",
            "net_spread_pct", "max_position_usd",
            "estimated_annual_profit_usd", "gas_total_usd",
            "net_annual_profit_usd", "viability", "risk_note",
        }
        self.assertTrue(required.issubset(set(opp.keys())))

    def test_assets_analyzed_is_list(self):
        result = analyze([])
        self.assertIsInstance(result["assets_analyzed"], list)

    def test_opportunities_is_list(self):
        result = analyze([])
        self.assertIsInstance(result["opportunities"], list)

    def test_total_opportunities_matches_list_length(self):
        markets = [
            _lend("A", "USDC", 6.0), _borrow("B", "USDC", 3.0),
            _lend("A", "ETH", 5.0), _borrow("B", "ETH", 2.0),
        ]
        result = analyze(markets)
        self.assertEqual(result["total_opportunities"],
                         len(result["opportunities"]))

    def test_viable_count_never_exceeds_total(self):
        markets = _simple_pair(lend_apy=6.0, borrow_apy=3.0)
        result = analyze(markets)
        self.assertLessEqual(result["viable_count"],
                             result["total_opportunities"])


# ===========================================================================
# 10. Risk notes match viability
# ===========================================================================

class TestRiskNoteConsistency(unittest.TestCase):

    def _get_opp_with_viability(self, viab: str) -> dict:
        """Return an opportunity dict with the given viability."""
        if viab == "EXCELLENT":
            markets = [
                _lend("A", "USDC", 15.0, liquidity=10_000_000, gas=1.0),
                _borrow("B", "USDC", 2.0, liquidity=10_000_000, gas=1.0),
            ]
        elif viab == "GOOD":
            markets = [
                _lend("A", "USDC", 4.5, liquidity=1_000_000, gas=0.0),
                _borrow("B", "USDC", 3.0, liquidity=1_000_000, gas=0.0),
            ]
        elif viab == "MARGINAL":
            markets = [
                _lend("A", "USDC", 3.6, liquidity=1_000_000, gas=0.0),
                _borrow("B", "USDC", 3.0, liquidity=1_000_000, gas=0.0),
            ]
        else:  # UNVIABLE
            markets = [
                _lend("A", "USDC", 6.0, liquidity=10.0, min_pos=0, gas=200.0),
                _borrow("B", "USDC", 3.0, liquidity=10.0, min_pos=0, gas=200.0),
            ]
        result = analyze(markets)
        return result["opportunities"][0] if result["opportunities"] else {}

    def test_excellent_risk_note_content(self):
        opp = self._get_opp_with_viability("EXCELLENT")
        if opp:
            self.assertIn("Strong arbitrage", opp["risk_note"])

    def test_good_risk_note_content(self):
        opp = self._get_opp_with_viability("GOOD")
        if opp:
            self.assertIn("Good spread", opp["risk_note"])

    def test_marginal_risk_note_content(self):
        opp = self._get_opp_with_viability("MARGINAL")
        if opp:
            self.assertIn("Thin margin", opp["risk_note"])

    def test_unviable_risk_note_content(self):
        opp = self._get_opp_with_viability("UNVIABLE")
        if opp:
            self.assertIn("Gas costs eat spread", opp["risk_note"])


# ===========================================================================
# 11. Additional edge-case tests
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_three_protocols_all_pairs(self):
        # 2 lenders × 2 borrowers, all different protocols = 4 pairs
        markets = [
            _lend("L1", "USDC", 8.0, liquidity=500_000),
            _lend("L2", "USDC", 6.0, liquidity=500_000),
            _borrow("B1", "USDC", 2.0, liquidity=500_000),
            _borrow("B2", "USDC", 3.0, liquidity=500_000),
        ]
        result = analyze(markets)
        self.assertEqual(result["total_opportunities"], 4)

    def test_lend_and_borrow_same_protocol_skipped(self):
        # L1 vs B1 OK; but L1 vs B1-same-proto should be skipped
        markets = [
            _lend("Same", "USDC", 8.0, liquidity=500_000),
            _borrow("Same", "USDC", 2.0, liquidity=500_000),
            _borrow("Other", "USDC", 3.0, liquidity=500_000),
        ]
        result = analyze(markets)
        # Only "Same" lend vs "Other" borrow should appear
        self.assertEqual(result["total_opportunities"], 1)
        self.assertEqual(result["opportunities"][0]["borrow_protocol"], "Other")

    def test_very_high_gas_cost_unviable(self):
        markets = [
            _lend("A", "USDC", 99.0, liquidity=1_000.0, min_pos=0, gas=500.0),
            _borrow("B", "USDC", 0.0, liquidity=1_000.0, min_pos=0, gas=500.0),
        ]
        result = analyze(markets)
        if result["opportunities"]:
            self.assertEqual(result["opportunities"][0]["viability"], "UNVIABLE")

    def test_float_apy_precision(self):
        markets = [
            _lend("A", "USDC", 4.123456789, liquidity=1_000_000),
            _borrow("B", "USDC", 2.987654321, liquidity=1_000_000),
        ]
        result = analyze(markets)
        self.assertEqual(result["total_opportunities"], 1)
        opp = result["opportunities"][0]
        expected_gross = 4.123456789 - 2.987654321
        self.assertAlmostEqual(opp["gross_spread_pct"], expected_gross, places=5)

    def test_markets_with_unknown_side(self):
        # Side not LEND or BORROW → ignored
        markets = [
            {"protocol": "A", "asset": "USDC", "side": "HOLD",
             "apy": 5.0, "available_liquidity_usd": 500_000,
             "min_position_usd": 0, "gas_cost_usd": 0},
            _borrow("B", "USDC", 3.0),
        ]
        result = analyze(markets)
        self.assertEqual(result["total_opportunities"], 0)

    def test_asset_with_no_viable_borrow(self):
        # USDC has lend but no borrow → 0 opportunities for USDC
        markets = [
            _lend("A", "USDC", 5.0),
            _lend("B", "USDC", 6.0),
        ]
        result = analyze(markets)
        usdc_opps = [o for o in result["opportunities"] if o["asset"] == "USDC"]
        self.assertEqual(len(usdc_opps), 0)

    def test_total_opportunities_is_int(self):
        result = analyze([])
        self.assertIsInstance(result["total_opportunities"], int)

    def test_viable_count_is_int(self):
        result = analyze([])
        self.assertIsInstance(result["viable_count"], int)

    def test_timestamp_is_float(self):
        result = analyze([])
        self.assertIsInstance(result["timestamp"], float)


if __name__ == "__main__":
    unittest.main(verbosity=2)
