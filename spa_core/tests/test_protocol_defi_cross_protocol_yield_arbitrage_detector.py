"""
Tests for MP-1041 ProtocolDeFiCrossProtocolYieldArbitrageDetector.
Run: python3 -m unittest spa_core.tests.test_protocol_defi_cross_protocol_yield_arbitrage_detector -v
"""

import json
import os
import sys
import tempfile
import time
import unittest

# Ensure repo root on path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_defi_cross_protocol_yield_arbitrage_detector import (
    ProtocolDeFiCrossProtocolYieldArbitrageDetector,
    detect,
    _bps_to_pct,
    _execution_cost_apy_pct,
    _gross_spread_bps,
    _net_arb_apy,
    _compute_execution_complexity,
    _classify_label,
    LOG_FILENAME,
    LOG_MAX_ENTRIES,
    DEFAULT_MIN_SPREAD_BPS,
    DEFAULT_POSITION_SIZE_USD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_detector(tmp_dir=None):
    return ProtocolDeFiCrossProtocolYieldArbitrageDetector(data_dir=tmp_dir)


def _opp(
    protocol="Aave V3",
    supply_apy=5.0,
    borrow_apy=6.0,
    asset="USDC",
    chain="ethereum",
    slippage_bps=5.0,
    bridge_cost_usd=0.0,
):
    return {
        "protocol": protocol,
        "supply_apy_pct": supply_apy,
        "borrow_apy_pct": borrow_apy,
        "asset": asset,
        "chain": chain,
        "slippage_bps": slippage_bps,
        "bridge_cost_usd": bridge_cost_usd,
    }


def _two_opps(spread_pct=1.5):
    return [
        _opp("ProtocolHigh", supply_apy=5.0 + spread_pct),
        _opp("ProtocolLow", supply_apy=5.0),
    ]


# ===========================================================================
# Unit tests — _bps_to_pct
# ===========================================================================

class TestBpsToPCT(unittest.TestCase):

    def test_100_bps_is_1_pct(self):
        self.assertAlmostEqual(_bps_to_pct(100.0), 1.0)

    def test_50_bps_is_half_pct(self):
        self.assertAlmostEqual(_bps_to_pct(50.0), 0.5)

    def test_zero(self):
        self.assertAlmostEqual(_bps_to_pct(0.0), 0.0)

    def test_1_bps(self):
        self.assertAlmostEqual(_bps_to_pct(1.0), 0.01)

    def test_10000_bps(self):
        self.assertAlmostEqual(_bps_to_pct(10000.0), 100.0)


# ===========================================================================
# Unit tests — _execution_cost_apy_pct
# ===========================================================================

class TestExecutionCostApyPct(unittest.TestCase):

    def test_zero_cost(self):
        self.assertAlmostEqual(_execution_cost_apy_pct(0.0, 0.0, 100_000), 0.0)

    def test_slippage_only(self):
        # 10 bps slippage = 0.1%
        self.assertAlmostEqual(_execution_cost_apy_pct(10.0, 0.0, 100_000), 0.1)

    def test_bridge_only(self):
        # $2.5 on $100k = 0.0025%
        self.assertAlmostEqual(_execution_cost_apy_pct(0.0, 2.5, 100_000), 0.0025)

    def test_both_costs(self):
        slip = _bps_to_pct(5.0)
        bridge = 10.0 / 100_000 * 100.0
        expected = slip + bridge
        result = _execution_cost_apy_pct(5.0, 10.0, 100_000)
        self.assertAlmostEqual(result, expected)

    def test_zero_position_size(self):
        self.assertAlmostEqual(_execution_cost_apy_pct(10.0, 5.0, 0.0), 0.0)

    def test_negative_position_size(self):
        self.assertAlmostEqual(_execution_cost_apy_pct(10.0, 5.0, -100.0), 0.0)

    def test_large_bridge_cost(self):
        # $1000 bridge on $10k position = 10%
        self.assertAlmostEqual(_execution_cost_apy_pct(0.0, 1000.0, 10_000), 10.0)


# ===========================================================================
# Unit tests — _gross_spread_bps
# ===========================================================================

class TestGrossSpreadBps(unittest.TestCase):

    def test_positive_spread(self):
        self.assertAlmostEqual(_gross_spread_bps(5.0, 3.0), 200.0)

    def test_zero_spread(self):
        self.assertAlmostEqual(_gross_spread_bps(4.0, 4.0), 0.0)

    def test_negative_spread(self):
        self.assertAlmostEqual(_gross_spread_bps(3.0, 5.0), -200.0)

    def test_fractional(self):
        self.assertAlmostEqual(_gross_spread_bps(4.5, 4.0), 50.0)

    def test_bps_conversion(self):
        # 1% spread = 100 bps
        self.assertAlmostEqual(_gross_spread_bps(6.0, 5.0), 100.0)


# ===========================================================================
# Unit tests — _net_arb_apy
# ===========================================================================

class TestNetArbApy(unittest.TestCase):

    def test_no_cost(self):
        self.assertAlmostEqual(_net_arb_apy(2.0, 0.0), 2.0)

    def test_cost_reduces_return(self):
        self.assertAlmostEqual(_net_arb_apy(2.0, 0.5), 1.5)

    def test_cost_exceeds_spread_negative(self):
        self.assertAlmostEqual(_net_arb_apy(0.5, 1.0), -0.5)

    def test_zero_spread_zero_cost(self):
        self.assertAlmostEqual(_net_arb_apy(0.0, 0.0), 0.0)

    def test_large_spread(self):
        self.assertAlmostEqual(_net_arb_apy(10.0, 0.5), 9.5)


# ===========================================================================
# Unit tests — _compute_execution_complexity
# ===========================================================================

class TestComputeExecutionComplexity(unittest.TestCase):

    def _complexity(self, high_chain="ethereum", low_chain="ethereum",
                    high_slippage=5.0, high_borrow=0.0):
        opp_high = _opp(chain=high_chain, slippage_bps=high_slippage, borrow_apy=high_borrow)
        opp_low = _opp(chain=low_chain)
        return _compute_execution_complexity(opp_high, opp_low, 100_000)

    def test_same_chain_low_slippage_low_complexity(self):
        c = self._complexity(high_chain="ethereum", low_chain="ethereum", high_slippage=5.0)
        self.assertLess(c, 30.0)

    def test_cross_chain_adds_complexity(self):
        c_same = self._complexity("ethereum", "ethereum", 5.0)
        c_cross = self._complexity("ethereum", "arbitrum", 5.0)
        self.assertGreater(c_cross, c_same)

    def test_cross_chain_penalty_is_30(self):
        c_same = self._complexity("ethereum", "ethereum", 0.0)
        c_cross = self._complexity("ethereum", "arbitrum", 0.0)
        self.assertAlmostEqual(c_cross - c_same, 30.0, places=4)

    def test_high_slippage_adds_complexity(self):
        c_low = self._complexity(high_slippage=5.0)
        c_high = self._complexity(high_slippage=100.0)
        self.assertGreater(c_high, c_low)

    def test_borrow_leg_adds_complexity(self):
        # borrow check is on opp_high (the destination leg)
        # so we must also set opp_low borrow to 0 to isolate the signal
        opp_hi_no_borrow = _opp(chain="ethereum", slippage_bps=5.0, borrow_apy=0.0)
        opp_hi_borrow = _opp(chain="ethereum", slippage_bps=5.0, borrow_apy=5.0)
        opp_lo = _opp(chain="ethereum", borrow_apy=0.0)
        c_no_borrow = _compute_execution_complexity(opp_hi_no_borrow, opp_lo, 100_000)
        c_borrow = _compute_execution_complexity(opp_hi_borrow, opp_lo, 100_000)
        self.assertGreater(c_borrow, c_no_borrow)

    def test_capped_at_100(self):
        opp_high = _opp(chain="arbitrum", slippage_bps=1000.0, borrow_apy=10.0)
        opp_low = _opp(chain="ethereum")
        c = _compute_execution_complexity(opp_high, opp_low, 100_000)
        self.assertLessEqual(c, 100.0)

    def test_minimum_is_zero(self):
        opp_high = _opp(chain="ethereum", slippage_bps=0.0, borrow_apy=0.0)
        opp_low = _opp(chain="ethereum")
        c = _compute_execution_complexity(opp_high, opp_low, 100_000)
        self.assertGreaterEqual(c, 0.0)


# ===========================================================================
# Unit tests — _classify_label
# ===========================================================================

class TestClassifyLabel(unittest.TestCase):

    def test_execution_risk_too_high_wins(self):
        label = _classify_label(
            net_arb_apy=5.0,
            spread_bps=300.0,
            execution_complexity=85.0,
            min_spread_bps=50.0,
        )
        self.assertEqual(label, "EXECUTION_RISK_TOO_HIGH")

    def test_negative_carry(self):
        label = _classify_label(
            net_arb_apy=-0.5,
            spread_bps=100.0,
            execution_complexity=30.0,
            min_spread_bps=50.0,
        )
        self.assertEqual(label, "NEGATIVE_CARRY")

    def test_no_arbitrage_spread_too_small(self):
        label = _classify_label(
            net_arb_apy=0.3,
            spread_bps=20.0,
            execution_complexity=30.0,
            min_spread_bps=50.0,
        )
        self.assertEqual(label, "NO_ARBITRAGE")

    def test_strong_arbitrage(self):
        label = _classify_label(
            net_arb_apy=3.0,
            spread_bps=300.0,
            execution_complexity=30.0,
            min_spread_bps=50.0,
        )
        self.assertEqual(label, "STRONG_ARBITRAGE")

    def test_marginal_arbitrage(self):
        label = _classify_label(
            net_arb_apy=1.0,
            spread_bps=100.0,
            execution_complexity=30.0,
            min_spread_bps=50.0,
        )
        self.assertEqual(label, "MARGINAL_ARBITRAGE")

    def test_strong_arb_requires_low_complexity(self):
        # net_arb > 2% but complexity > 50 → MARGINAL (not STRONG)
        label = _classify_label(
            net_arb_apy=3.0,
            spread_bps=300.0,
            execution_complexity=60.0,
            min_spread_bps=50.0,
        )
        self.assertEqual(label, "MARGINAL_ARBITRAGE")

    def test_zero_net_arb_no_arbitrage(self):
        label = _classify_label(
            net_arb_apy=0.0,
            spread_bps=100.0,
            execution_complexity=20.0,
            min_spread_bps=50.0,
        )
        self.assertEqual(label, "NO_ARBITRAGE")

    def test_valid_label_set(self):
        valid = {
            "STRONG_ARBITRAGE", "MARGINAL_ARBITRAGE", "NO_ARBITRAGE",
            "NEGATIVE_CARRY", "EXECUTION_RISK_TOO_HIGH"
        }
        for net, spread, complexity, min_s in [
            (3.0, 300.0, 20.0, 50.0),
            (1.0, 100.0, 40.0, 50.0),
            (0.1, 20.0, 10.0, 50.0),
            (-1.0, 100.0, 20.0, 50.0),
            (5.0, 500.0, 90.0, 50.0),
        ]:
            label = _classify_label(net, spread, complexity, min_s)
            self.assertIn(label, valid, f"Unexpected label: {label!r}")


# ===========================================================================
# Integration tests — ProtocolDeFiCrossProtocolYieldArbitrageDetector.detect()
# ===========================================================================

class TestDetectorDetect(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.detector = _make_detector(self.tmp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_returns_dict(self):
        result = self.detector.detect(_two_opps())
        self.assertIsInstance(result, dict)

    def test_required_keys(self):
        result = self.detector.detect(_two_opps())
        for key in [
            "opportunities_analyzed", "best_opportunity", "all_pairs",
            "spread_bps", "net_arb_apy_pct", "execution_complexity_score",
            "label", "min_spread_bps", "position_size_usd", "timestamp",
        ]:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_empty_list_returns_no_arbitrage(self):
        result = self.detector.detect([])
        self.assertEqual(result["label"], "NO_ARBITRAGE")
        self.assertIsNone(result["best_opportunity"])

    def test_single_opportunity_returns_no_arbitrage(self):
        result = self.detector.detect([_opp()])
        self.assertEqual(result["label"], "NO_ARBITRAGE")

    def test_two_opps_analyzed_count(self):
        result = self.detector.detect(_two_opps())
        self.assertEqual(result["opportunities_analyzed"], 2)

    def test_spread_bps_positive_for_different_apys(self):
        result = self.detector.detect(_two_opps(spread_pct=1.5))
        self.assertGreater(result["spread_bps"], 0.0)

    def test_spread_bps_calculation(self):
        opps = [_opp("A", supply_apy=6.0), _opp("B", supply_apy=4.0)]
        result = self.detector.detect(opps, min_spread_bps=50)
        # 2% spread = 200 bps
        self.assertAlmostEqual(result["spread_bps"], 200.0, places=3)

    def test_best_opportunity_is_dict(self):
        result = self.detector.detect(_two_opps())
        self.assertIsInstance(result["best_opportunity"], dict)

    def test_best_opportunity_keys(self):
        result = self.detector.detect(_two_opps())
        best = result["best_opportunity"]
        for key in ["high_protocol", "low_protocol", "asset", "spread_bps",
                    "net_arb_apy_pct", "execution_complexity_score", "label"]:
            self.assertIn(key, best, f"Missing key in best_opportunity: {key}")

    def test_timestamp_is_recent(self):
        before = time.time()
        result = self.detector.detect(_two_opps())
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_label_is_valid(self):
        valid = {
            "STRONG_ARBITRAGE", "MARGINAL_ARBITRAGE", "NO_ARBITRAGE",
            "NEGATIVE_CARRY", "EXECUTION_RISK_TOO_HIGH"
        }
        result = self.detector.detect(_two_opps())
        self.assertIn(result["label"], valid)

    def test_no_save_no_log(self):
        self.detector.detect(_two_opps(), save=False)
        log_path = os.path.join(self.tmp_dir, LOG_FILENAME)
        self.assertFalse(os.path.exists(log_path))

    def test_save_creates_log(self):
        self.detector.detect(_two_opps(), save=True)
        log_path = os.path.join(self.tmp_dir, LOG_FILENAME)
        self.assertTrue(os.path.exists(log_path))

    def test_save_log_has_entry(self):
        self.detector.detect(_two_opps(), save=True)
        log_path = os.path.join(self.tmp_dir, LOG_FILENAME)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            self.detector.detect(_two_opps(), save=True)
        log_path = os.path.join(self.tmp_dir, LOG_FILENAME)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_capped(self):
        for _ in range(LOG_MAX_ENTRIES + 10):
            self.detector.detect(_two_opps(), save=True)
        log_path = os.path.join(self.tmp_dir, LOG_FILENAME)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), LOG_MAX_ENTRIES)

    def test_min_spread_bps_respected(self):
        # 50 bps gross spread, 1 bps slippage each side → net clearly positive
        # but min_spread=200 bps → NO_ARBITRAGE
        opps = [
            _opp("A", supply_apy=5.5, slippage_bps=1.0, borrow_apy=0.0, chain="ethereum"),
            _opp("B", supply_apy=5.0, slippage_bps=1.0, borrow_apy=0.0, chain="ethereum"),
        ]
        result = self.detector.detect(opps, min_spread_bps=200.0)
        self.assertEqual(result["label"], "NO_ARBITRAGE")

    def test_min_spread_bps_stored_in_result(self):
        result = self.detector.detect(_two_opps(), min_spread_bps=75.0)
        self.assertAlmostEqual(result["min_spread_bps"], 75.0)

    def test_position_size_stored_in_result(self):
        result = self.detector.detect(_two_opps(), position_size_usd=50_000.0)
        self.assertAlmostEqual(result["position_size_usd"], 50_000.0)

    def test_sorts_by_highest_apy(self):
        opps = [
            _opp("Low", supply_apy=3.0),
            _opp("High", supply_apy=7.0),
            _opp("Mid", supply_apy=5.0),
        ]
        result = self.detector.detect(opps)
        self.assertEqual(result["best_opportunity"]["high_protocol"], "High")
        self.assertEqual(result["best_opportunity"]["low_protocol"], "Low")

    def test_all_pairs_length(self):
        opps = [_opp(f"P{i}", supply_apy=float(i)) for i in range(4)]
        result = self.detector.detect(opps)
        # 4 opportunities → 3 adjacent pairs
        self.assertEqual(len(result["all_pairs"]), 3)

    def test_cross_chain_detected_higher_complexity(self):
        opps = [
            _opp("AaveEth", supply_apy=6.0, chain="ethereum", slippage_bps=5.0),
            _opp("AaveArb", supply_apy=4.0, chain="arbitrum", bridge_cost_usd=2.5),
        ]
        result = self.detector.detect(opps)
        self.assertGreater(result["execution_complexity_score"], 0.0)

    def test_strong_arbitrage_label_large_spread_low_complexity(self):
        opps = [
            _opp("HighYield", supply_apy=9.0, slippage_bps=2.0, chain="ethereum"),
            _opp("LowYield", supply_apy=4.0, slippage_bps=2.0, chain="ethereum"),
        ]
        result = self.detector.detect(opps, min_spread_bps=50.0)
        self.assertEqual(result["label"], "STRONG_ARBITRAGE")

    def test_negative_carry_when_costs_exceed_spread(self):
        # Same chain, 60 bps slippage each side, 10 bps gross spread.
        # Complexity: 60*0.5=30, >50 slippage extra=+20, no borrow, no cross-chain → 50 < 80
        # Cost: 2 * 0.6% = 1.2%, gross spread = 0.1% → net = -1.1% → NEGATIVE_CARRY
        opps = [
            _opp("A", supply_apy=5.1, slippage_bps=60.0, borrow_apy=0.0,
                 chain="ethereum", bridge_cost_usd=0.0),
            _opp("B", supply_apy=5.0, slippage_bps=60.0, borrow_apy=0.0,
                 chain="ethereum", bridge_cost_usd=0.0),
        ]
        result = self.detector.detect(opps, min_spread_bps=50.0)
        self.assertEqual(result["label"], "NEGATIVE_CARRY")

    def test_default_min_spread_used(self):
        result = self.detector.detect(_two_opps())
        self.assertAlmostEqual(result["min_spread_bps"], DEFAULT_MIN_SPREAD_BPS)

    def test_default_position_size_used(self):
        result = self.detector.detect(_two_opps())
        self.assertAlmostEqual(result["position_size_usd"], DEFAULT_POSITION_SIZE_USD)


# ===========================================================================
# Module-level detect() function
# ===========================================================================

class TestModuleLevelDetect(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_returns_dict(self):
        result = detect(_two_opps(), data_dir=self.tmp_dir)
        self.assertIsInstance(result, dict)

    def test_has_label(self):
        result = detect(_two_opps(), data_dir=self.tmp_dir)
        self.assertIn("label", result)

    def test_save_creates_log(self):
        detect(_two_opps(), data_dir=self.tmp_dir, save=True)
        log_path = os.path.join(self.tmp_dir, LOG_FILENAME)
        self.assertTrue(os.path.exists(log_path))

    def test_no_save_no_log(self):
        detect(_two_opps(), data_dir=self.tmp_dir, save=False)
        log_path = os.path.join(self.tmp_dir, LOG_FILENAME)
        self.assertFalse(os.path.exists(log_path))

    def test_empty_input_no_arbitrage(self):
        result = detect([], data_dir=self.tmp_dir)
        self.assertEqual(result["label"], "NO_ARBITRAGE")


# ===========================================================================
# Log management tests
# ===========================================================================

class TestLogManagement(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.detector = _make_detector(self.tmp_dir)
        self.log_path = os.path.join(self.tmp_dir, LOG_FILENAME)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_init_log_creates_file(self):
        self.assertFalse(os.path.exists(self.log_path))
        self.detector.init_log()
        self.assertTrue(os.path.exists(self.log_path))

    def test_init_log_is_empty_list(self):
        self.detector.init_log()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data, [])

    def test_init_log_idempotent(self):
        self.detector.init_log()
        self.detector.detect(_two_opps(), save=True)
        self.detector.init_log()  # should NOT overwrite
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_read_log_missing_returns_empty(self):
        result = self.detector._read_log()
        self.assertEqual(result, [])

    def test_read_log_corrupt_returns_empty(self):
        with open(self.log_path, "w") as f:
            f.write("{{not valid json")
        result = self.detector._read_log()
        self.assertEqual(result, [])

    def test_read_log_non_list_returns_empty(self):
        with open(self.log_path, "w") as f:
            json.dump({"key": "value"}, f)
        result = self.detector._read_log()
        self.assertEqual(result, [])

    def test_atomic_write_valid_json(self):
        data = [{"x": 1}, {"y": 2}]
        self.detector._atomic_write(data)
        with open(self.log_path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_ring_buffer_keeps_latest(self):
        for i in range(LOG_MAX_ENTRIES + 5):
            opps = [_opp(f"P{i}_A", supply_apy=6.0), _opp(f"P{i}_B", supply_apy=4.0)]
            self.detector.detect(opps, save=True)
        data = self.detector._read_log()
        self.assertEqual(len(data), LOG_MAX_ENTRIES)


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.detector = _make_detector(self.tmp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_identical_apys_zero_spread(self):
        opps = [_opp("A", supply_apy=5.0), _opp("B", supply_apy=5.0)]
        result = self.detector.detect(opps)
        self.assertAlmostEqual(result["spread_bps"], 0.0, places=3)

    def test_many_protocols(self):
        opps = [_opp(f"P{i}", supply_apy=float(i)) for i in range(10)]
        result = self.detector.detect(opps)
        self.assertEqual(result["opportunities_analyzed"], 10)
        self.assertEqual(len(result["all_pairs"]), 9)

    def test_net_arb_apy_can_be_negative(self):
        # Very small spread + high slippage
        opps = [
            _opp("A", supply_apy=5.01, slippage_bps=500.0),
            _opp("B", supply_apy=5.00, slippage_bps=500.0),
        ]
        result = self.detector.detect(opps, position_size_usd=100_000)
        self.assertLess(result["net_arb_apy_pct"], 0.0)

    def test_all_same_chain_no_bridge_penalty(self):
        opps = [
            _opp("A", supply_apy=7.0, chain="ethereum"),
            _opp("B", supply_apy=4.0, chain="ethereum"),
        ]
        result = self.detector.detect(opps)
        # No cross-chain penalty, should not be EXECUTION_RISK_TOO_HIGH
        self.assertNotEqual(result["label"], "EXECUTION_RISK_TOO_HIGH")

    def test_empty_opportunities_returns_zero_count(self):
        result = self.detector.detect([])
        self.assertEqual(result["opportunities_analyzed"], 0)

    def test_result_complexity_in_range(self):
        result = self.detector.detect(_two_opps())
        self.assertGreaterEqual(result["execution_complexity_score"], 0.0)
        self.assertLessEqual(result["execution_complexity_score"], 100.0)


if __name__ == "__main__":
    unittest.main()
