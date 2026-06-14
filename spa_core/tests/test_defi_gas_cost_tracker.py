"""
Tests for MP-887 DeFiGasCostTracker
Run: python3 -m unittest spa_core.tests.test_defi_gas_cost_tracker -v
"""

import json
import math
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path setup so the module can be imported without installation
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_gas_cost_tracker import (
    analyze,
    log_result,
    _gas_cost_eth,
    _efficiency_label,
    INF_SENTINEL,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def make_tx(**overrides) -> dict:
    base = {
        "protocol":        "Aave V3",
        "chain":           "ethereum",
        "tx_type":         "deposit",
        "gas_used":        200_000,
        "gas_price_gwei":  20.0,
        "eth_price_usd":   3_000.0,
        "position_size_usd": 50_000.0,
        "yield_apy_pct":   5.0,
    }
    base.update(overrides)
    return base


def _breakeven(tx: dict) -> float:
    """Replicate break-even formula from module for expected-value assertions."""
    gc_eth = tx["gas_used"] * tx["gas_price_gwei"] / 1e9
    gc_usd = gc_eth * tx["eth_price_usd"]
    denom  = tx["position_size_usd"] * tx["yield_apy_pct"] / 100.0 / 365.0
    if denom > 0:
        return gc_usd / denom
    return INF_SENTINEL


# ===========================================================================
# 1. _gas_cost_eth unit tests
# ===========================================================================
class TestGasCostEth(unittest.TestCase):

    def test_basic(self):
        self.assertAlmostEqual(_gas_cost_eth(1_000_000, 1.0), 0.001)

    def test_zero_gas_used(self):
        self.assertEqual(_gas_cost_eth(0, 50.0), 0.0)

    def test_zero_gwei(self):
        self.assertEqual(_gas_cost_eth(200_000, 0.0), 0.0)

    def test_typical(self):
        # 200_000 gas * 20 gwei = 4_000_000 gwei = 0.004 ETH
        self.assertAlmostEqual(_gas_cost_eth(200_000, 20.0), 0.004)

    def test_arbitrum_low_gas(self):
        # L2 — 150_000 gas * 0.1 gwei = 15_000 gwei = 0.000015 ETH
        self.assertAlmostEqual(_gas_cost_eth(150_000, 0.1), 1.5e-5)


# ===========================================================================
# 2. _efficiency_label unit tests
# ===========================================================================
class TestEfficiencyLabel(unittest.TestCase):

    def test_efficient_boundary(self):
        self.assertEqual(_efficiency_label(7.0), "EFFICIENT")

    def test_efficient_below(self):
        self.assertEqual(_efficiency_label(1.0), "EFFICIENT")

    def test_acceptable_boundary(self):
        self.assertEqual(_efficiency_label(30.0), "ACCEPTABLE")

    def test_acceptable_mid(self):
        self.assertEqual(_efficiency_label(15.0), "ACCEPTABLE")

    def test_expensive_boundary(self):
        self.assertEqual(_efficiency_label(90.0), "EXPENSIVE")

    def test_expensive_mid(self):
        self.assertEqual(_efficiency_label(50.0), "EXPENSIVE")

    def test_prohibitive(self):
        self.assertEqual(_efficiency_label(91.0), "PROHIBITIVE")

    def test_prohibitive_sentinel(self):
        self.assertEqual(_efficiency_label(INF_SENTINEL), "PROHIBITIVE")

    def test_prohibitive_large(self):
        self.assertEqual(_efficiency_label(10_000.0), "PROHIBITIVE")


# ===========================================================================
# 3. Empty input
# ===========================================================================
class TestEmptyInput(unittest.TestCase):

    def setUp(self):
        self.result = analyze([])

    def test_transactions_empty(self):
        self.assertEqual(self.result["transactions"], [])

    def test_by_chain_empty(self):
        self.assertEqual(self.result["by_chain"], {})

    def test_by_protocol_empty(self):
        self.assertEqual(self.result["by_protocol"], {})

    def test_by_tx_type_empty(self):
        self.assertEqual(self.result["by_tx_type"], {})

    def test_total_gas_zero(self):
        self.assertEqual(self.result["total_gas_spent_usd"], 0.0)

    def test_avg_breakeven_zero(self):
        self.assertEqual(self.result["average_breakeven_days"], 0.0)

    def test_cheapest_chain_none(self):
        self.assertIsNone(self.result["cheapest_chain"])

    def test_most_expensive_chain_none(self):
        self.assertIsNone(self.result["most_expensive_chain"])

    def test_has_timestamp(self):
        self.assertIn("timestamp", self.result)
        self.assertIsInstance(self.result["timestamp"], float)


# ===========================================================================
# 4. Single transaction
# ===========================================================================
class TestSingleTransaction(unittest.TestCase):

    def setUp(self):
        self.tx = make_tx()
        self.result = analyze([self.tx])
        self.tx_out = self.result["transactions"][0]

    def test_tx_count(self):
        self.assertEqual(len(self.result["transactions"]), 1)

    def test_gas_cost_eth(self):
        expected = _gas_cost_eth(self.tx["gas_used"], self.tx["gas_price_gwei"])
        self.assertAlmostEqual(self.tx_out["gas_cost_eth"], expected)

    def test_gas_cost_usd(self):
        eth = _gas_cost_eth(self.tx["gas_used"], self.tx["gas_price_gwei"])
        self.assertAlmostEqual(self.tx_out["gas_cost_usd"], eth * self.tx["eth_price_usd"])

    def test_gas_pct_of_position(self):
        eth = _gas_cost_eth(self.tx["gas_used"], self.tx["gas_price_gwei"])
        usd = eth * self.tx["eth_price_usd"]
        expected = usd / self.tx["position_size_usd"] * 100.0
        self.assertAlmostEqual(self.tx_out["gas_pct_of_position"], expected)

    def test_annual_gas_drag_eq_gas_pct(self):
        self.assertAlmostEqual(
            self.tx_out["annual_gas_drag_pct"],
            self.tx_out["gas_pct_of_position"]
        )

    def test_breakeven_days_positive(self):
        self.assertGreater(self.tx_out["breakeven_days"], 0)

    def test_breakeven_formula(self):
        expected = _breakeven(self.tx)
        self.assertAlmostEqual(self.tx_out["breakeven_days"], expected, places=4)

    def test_protocol_field(self):
        self.assertEqual(self.tx_out["protocol"], "Aave V3")

    def test_chain_field(self):
        self.assertEqual(self.tx_out["chain"], "ethereum")

    def test_tx_type_field(self):
        self.assertEqual(self.tx_out["tx_type"], "deposit")

    def test_by_chain_populated(self):
        self.assertIn("ethereum", self.result["by_chain"])

    def test_by_chain_tx_count(self):
        self.assertEqual(self.result["by_chain"]["ethereum"]["tx_count"], 1)

    def test_by_protocol_populated(self):
        self.assertIn("Aave V3", self.result["by_protocol"])

    def test_by_tx_type_populated(self):
        self.assertIn("deposit", self.result["by_tx_type"])

    def test_cheapest_chain_equals_ethereum(self):
        self.assertEqual(self.result["cheapest_chain"], "ethereum")

    def test_most_expensive_chain_equals_ethereum(self):
        self.assertEqual(self.result["most_expensive_chain"], "ethereum")


# ===========================================================================
# 5. Zero position size
# ===========================================================================
class TestZeroPosition(unittest.TestCase):

    def setUp(self):
        self.tx = make_tx(position_size_usd=0.0)
        self.tx_out = analyze([self.tx])["transactions"][0]

    def test_gas_pct_zero(self):
        self.assertEqual(self.tx_out["gas_pct_of_position"], 0.0)

    def test_annual_drag_zero(self):
        self.assertEqual(self.tx_out["annual_gas_drag_pct"], 0.0)

    def test_breakeven_sentinel(self):
        self.assertEqual(self.tx_out["breakeven_days"], INF_SENTINEL)

    def test_efficiency_prohibitive(self):
        self.assertEqual(self.tx_out["efficiency_label"], "PROHIBITIVE")


# ===========================================================================
# 6. Zero APY, non-zero position
# ===========================================================================
class TestZeroAPY(unittest.TestCase):

    def setUp(self):
        self.tx = make_tx(yield_apy_pct=0.0, position_size_usd=10_000.0)
        self.tx_out = analyze([self.tx])["transactions"][0]

    def test_breakeven_sentinel(self):
        self.assertEqual(self.tx_out["breakeven_days"], INF_SENTINEL)

    def test_label_prohibitive(self):
        self.assertEqual(self.tx_out["efficiency_label"], "PROHIBITIVE")

    def test_gas_pct_nonzero(self):
        self.assertGreater(self.tx_out["gas_pct_of_position"], 0.0)


# ===========================================================================
# 7. Efficiency labels via breakeven thresholds
# ===========================================================================
class TestEfficiencyLabelIntegration(unittest.TestCase):

    def _tx_for_bd(self, bd_days: float) -> dict:
        """Craft a tx that produces approx bd_days break-even."""
        position   = 100_000.0
        yield_apy  = 10.0
        # daily yield = position * apy/100/365
        daily_yield = position * yield_apy / 100.0 / 365.0
        target_gas_usd = daily_yield * bd_days
        # Use eth_price=1 so gas_cost_usd = gas_cost_eth
        # gas_cost_eth = gas_used * gwei / 1e9
        # Choose gas_used=200_000, gwei to hit target
        gas_used = 200_000
        gwei = target_gas_usd * 1e9 / gas_used
        return make_tx(
            gas_used=gas_used,
            gas_price_gwei=gwei,
            eth_price_usd=1.0,
            position_size_usd=position,
            yield_apy_pct=yield_apy,
        )

    def test_efficient(self):
        tx = self._tx_for_bd(5.0)
        out = analyze([tx])["transactions"][0]
        self.assertEqual(out["efficiency_label"], "EFFICIENT")

    def test_acceptable(self):
        tx = self._tx_for_bd(20.0)
        out = analyze([tx])["transactions"][0]
        self.assertEqual(out["efficiency_label"], "ACCEPTABLE")

    def test_expensive(self):
        tx = self._tx_for_bd(60.0)
        out = analyze([tx])["transactions"][0]
        self.assertEqual(out["efficiency_label"], "EXPENSIVE")

    def test_prohibitive(self):
        tx = self._tx_for_bd(100.0)
        out = analyze([tx])["transactions"][0]
        self.assertEqual(out["efficiency_label"], "PROHIBITIVE")


# ===========================================================================
# 8. Flag HIGH_GAS
# ===========================================================================
class TestHighGasFlag(unittest.TestCase):

    def test_flag_set_when_expensive(self):
        # Create a tx with large break-even
        tx = make_tx(
            gas_used=2_000_000,
            gas_price_gwei=50.0,
            eth_price_usd=3_000.0,
            position_size_usd=1_000.0,
            yield_apy_pct=5.0,
        )
        out = analyze([tx], config={"min_breakeven_days": 30})
        self.assertEqual(out["transactions"][0]["flag"], "HIGH_GAS")

    def test_flag_none_when_cheap(self):
        # Very cheap tx relative to large position
        tx = make_tx(
            gas_used=1_000,
            gas_price_gwei=1.0,
            eth_price_usd=100.0,
            position_size_usd=1_000_000.0,
            yield_apy_pct=20.0,
        )
        out = analyze([tx], config={"min_breakeven_days": 30})
        self.assertIsNone(out["transactions"][0]["flag"])

    def test_custom_min_breakeven(self):
        # tx that's exactly on the edge with min=5
        tx = make_tx(
            gas_used=200_000,
            gas_price_gwei=20.0,
            eth_price_usd=3_000.0,
            position_size_usd=50_000.0,
            yield_apy_pct=5.0,
        )
        bd = _breakeven(tx)
        # With min=10000, nothing should be flagged
        out = analyze([tx], config={"min_breakeven_days": 10_000})
        self.assertIsNone(out["transactions"][0]["flag"])


# ===========================================================================
# 9. Multiple transactions / aggregations
# ===========================================================================
class TestMultipleTransactions(unittest.TestCase):

    def setUp(self):
        self.txs = [
            make_tx(protocol="Aave V3",    chain="ethereum", tx_type="deposit",
                    gas_used=200_000, gas_price_gwei=30.0, eth_price_usd=3_000.0,
                    position_size_usd=50_000.0, yield_apy_pct=4.0),
            make_tx(protocol="Compound V3", chain="arbitrum", tx_type="rebalance",
                    gas_used=150_000, gas_price_gwei=0.1,  eth_price_usd=3_000.0,
                    position_size_usd=30_000.0, yield_apy_pct=5.0),
            make_tx(protocol="Aave V3",    chain="ethereum", tx_type="withdraw",
                    gas_used=180_000, gas_price_gwei=25.0, eth_price_usd=3_000.0,
                    position_size_usd=50_000.0, yield_apy_pct=4.0),
        ]
        self.result = analyze(self.txs)

    def test_tx_count(self):
        self.assertEqual(len(self.result["transactions"]), 3)

    def test_total_gas_sum(self):
        expected = sum(
            _gas_cost_eth(t["gas_used"], t["gas_price_gwei"]) * t["eth_price_usd"]
            for t in self.txs
        )
        self.assertAlmostEqual(self.result["total_gas_spent_usd"], expected, places=6)

    def test_by_chain_keys(self):
        self.assertIn("ethereum", self.result["by_chain"])
        self.assertIn("arbitrum", self.result["by_chain"])

    def test_by_chain_ethereum_count(self):
        self.assertEqual(self.result["by_chain"]["ethereum"]["tx_count"], 2)

    def test_by_chain_arbitrum_count(self):
        self.assertEqual(self.result["by_chain"]["arbitrum"]["tx_count"], 1)

    def test_by_protocol_aave_count(self):
        self.assertEqual(self.result["by_protocol"]["Aave V3"]["tx_count"], 2)

    def test_by_protocol_compound_count(self):
        self.assertEqual(self.result["by_protocol"]["Compound V3"]["tx_count"], 1)

    def test_by_protocol_total_gas_aave(self):
        expected = sum(
            _gas_cost_eth(t["gas_used"], t["gas_price_gwei"]) * t["eth_price_usd"]
            for t in self.txs if t["protocol"] == "Aave V3"
        )
        self.assertAlmostEqual(
            self.result["by_protocol"]["Aave V3"]["total_gas_usd"], expected, places=6
        )

    def test_by_tx_type_keys(self):
        self.assertIn("deposit",   self.result["by_tx_type"])
        self.assertIn("rebalance", self.result["by_tx_type"])
        self.assertIn("withdraw",  self.result["by_tx_type"])

    def test_cheapest_chain_is_arbitrum(self):
        # arbitrum has much lower gas
        self.assertEqual(self.result["cheapest_chain"], "arbitrum")

    def test_most_expensive_chain_is_ethereum(self):
        self.assertEqual(self.result["most_expensive_chain"], "ethereum")


# ===========================================================================
# 10. average_breakeven_days (finite only)
# ===========================================================================
class TestAverageBreakeven(unittest.TestCase):

    def test_excludes_infinite(self):
        # One tx with real breakeven, one with zero position (sentinel)
        tx_finite   = make_tx(position_size_usd=50_000.0, yield_apy_pct=5.0)
        tx_infinite = make_tx(position_size_usd=0.0)
        result = analyze([tx_finite, tx_infinite])
        expected = _breakeven(tx_finite)
        self.assertAlmostEqual(result["average_breakeven_days"], expected, places=3)

    def test_all_infinite(self):
        tx1 = make_tx(position_size_usd=0.0)
        tx2 = make_tx(yield_apy_pct=0.0)
        result = analyze([tx1, tx2])
        self.assertEqual(result["average_breakeven_days"], 0.0)

    def test_multiple_finite(self):
        tx1 = make_tx(gas_used=100_000, gas_price_gwei=10.0, eth_price_usd=1.0,
                      position_size_usd=10_000.0, yield_apy_pct=10.0)
        tx2 = make_tx(gas_used=200_000, gas_price_gwei=10.0, eth_price_usd=1.0,
                      position_size_usd=10_000.0, yield_apy_pct=10.0)
        result = analyze([tx1, tx2])
        bd1 = _breakeven(tx1)
        bd2 = _breakeven(tx2)
        self.assertAlmostEqual(result["average_breakeven_days"], (bd1 + bd2) / 2.0, places=4)


# ===========================================================================
# 11. by_chain avg_breakeven_days (finite only per chain)
# ===========================================================================
class TestByChainBreakeven(unittest.TestCase):

    def test_per_chain_avg(self):
        tx1 = make_tx(chain="ethereum", position_size_usd=50_000.0, yield_apy_pct=5.0,
                      gas_used=200_000, gas_price_gwei=20.0, eth_price_usd=3_000.0)
        tx2 = make_tx(chain="ethereum", position_size_usd=0.0)  # infinite → excluded
        result = analyze([tx1, tx2])
        expected = _breakeven(tx1)
        self.assertAlmostEqual(
            result["by_chain"]["ethereum"]["avg_breakeven_days"], expected, places=4
        )

    def test_all_infinite_in_chain_returns_zero(self):
        tx = make_tx(chain="base", position_size_usd=0.0)
        result = analyze([tx])
        self.assertEqual(result["by_chain"]["base"]["avg_breakeven_days"], 0.0)


# ===========================================================================
# 12. Config overrides
# ===========================================================================
class TestConfigOverrides(unittest.TestCase):

    def test_default_config_used_when_none(self):
        tx = make_tx(gas_used=2_000_000, gas_price_gwei=50.0, eth_price_usd=3_000.0,
                     position_size_usd=1_000.0, yield_apy_pct=5.0)
        result = analyze([tx])
        # default min is 30 → should be flagged
        self.assertEqual(result["transactions"][0]["flag"], "HIGH_GAS")

    def test_strict_threshold_flags_more(self):
        tx = make_tx()
        result_strict = analyze([tx], config={"min_breakeven_days": 0})
        # breakeven > 0 → flagged
        self.assertEqual(result_strict["transactions"][0]["flag"], "HIGH_GAS")

    def test_lenient_threshold_flags_less(self):
        tx = make_tx()
        result_lenient = analyze([tx], config={"min_breakeven_days": 999_999})
        self.assertIsNone(result_lenient["transactions"][0]["flag"])


# ===========================================================================
# 13. Output keys completeness
# ===========================================================================
class TestOutputKeys(unittest.TestCase):

    def test_top_level_keys(self):
        result = analyze([make_tx()])
        expected_keys = {
            "transactions", "by_chain", "by_protocol", "by_tx_type",
            "total_gas_spent_usd", "average_breakeven_days",
            "cheapest_chain", "most_expensive_chain", "timestamp",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_tx_keys(self):
        tx_out = analyze([make_tx()])["transactions"][0]
        expected_keys = {
            "protocol", "chain", "tx_type",
            "gas_cost_eth", "gas_cost_usd", "gas_pct_of_position",
            "breakeven_days", "annual_gas_drag_pct",
            "efficiency_label", "flag",
        }
        self.assertEqual(set(tx_out.keys()), expected_keys)

    def test_by_chain_keys(self):
        chain = analyze([make_tx()])["by_chain"]["ethereum"]
        self.assertSetEqual(set(chain.keys()), {"avg_gas_usd", "tx_count", "avg_breakeven_days"})

    def test_by_protocol_keys(self):
        proto = analyze([make_tx()])["by_protocol"]["Aave V3"]
        self.assertSetEqual(set(proto.keys()), {"avg_gas_usd", "total_gas_usd", "tx_count"})

    def test_by_tx_type_keys(self):
        tx_type = analyze([make_tx()])["by_tx_type"]["deposit"]
        self.assertSetEqual(set(tx_type.keys()), {"avg_gas_usd", "tx_count"})


# ===========================================================================
# 14. log_result ring-buffer
# ===========================================================================
class TestLogResult(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.log_path = self.tmp.name
        # Start with empty log
        with open(self.log_path, "w") as f:
            json.dump([], f)

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.unlink(self.log_path)

    def test_single_entry(self):
        result = analyze([make_tx()])
        log_result(result, self.log_path)
        with open(self.log_path) as f:
            entries = json.load(f)
        self.assertEqual(len(entries), 1)

    def test_entry_keys(self):
        result = analyze([make_tx()])
        log_result(result, self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        expected = {"timestamp", "total_gas_spent_usd", "average_breakeven_days",
                    "tx_count", "cheapest_chain", "most_expensive_chain"}
        self.assertEqual(set(entry.keys()), expected)

    def test_ring_buffer_cap_100(self):
        for _ in range(110):
            log_result(analyze([make_tx()]), self.log_path)
        with open(self.log_path) as f:
            entries = json.load(f)
        self.assertLessEqual(len(entries), 100)

    def test_creates_missing_file(self):
        path = self.log_path + "_new.json"
        try:
            log_result(analyze([make_tx()]), path)
            self.assertTrue(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_invalid_json_recovers(self):
        with open(self.log_path, "w") as f:
            f.write("NOT JSON")
        log_result(analyze([make_tx()]), self.log_path)
        with open(self.log_path) as f:
            entries = json.load(f)
        self.assertEqual(len(entries), 1)

    def test_tx_count_in_entry(self):
        result = analyze([make_tx(), make_tx()])
        log_result(result, self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["tx_count"], 2)


# ===========================================================================
# 15. Edge cases — various chains and tx types
# ===========================================================================
class TestEdgeCases(unittest.TestCase):

    def test_all_five_chains(self):
        chains = ["ethereum", "arbitrum", "base", "optimism", "polygon"]
        txs = [make_tx(chain=c) for c in chains]
        result = analyze(txs)
        for c in chains:
            self.assertIn(c, result["by_chain"])

    def test_all_tx_types(self):
        types = ["deposit", "withdraw", "rebalance", "harvest", "claim"]
        txs = [make_tx(tx_type=t) for t in types]
        result = analyze(txs)
        for t in types:
            self.assertIn(t, result["by_tx_type"])

    def test_zero_gas_used(self):
        tx = make_tx(gas_used=0)
        out = analyze([tx])["transactions"][0]
        self.assertEqual(out["gas_cost_eth"], 0.0)
        self.assertEqual(out["gas_cost_usd"], 0.0)
        self.assertEqual(out["breakeven_days"], 0.0)

    def test_zero_eth_price(self):
        tx = make_tx(eth_price_usd=0.0)
        out = analyze([tx])["transactions"][0]
        self.assertEqual(out["gas_cost_usd"], 0.0)

    def test_sentinel_never_exceeds(self):
        tx = make_tx(position_size_usd=0.0)
        out = analyze([tx])["transactions"][0]
        self.assertLessEqual(out["breakeven_days"], INF_SENTINEL)

    def test_result_json_serialisable(self):
        txs = [make_tx(), make_tx(position_size_usd=0.0), make_tx(yield_apy_pct=0.0)]
        result = analyze(txs)
        # Should not raise
        serialised = json.dumps(result)
        self.assertIsInstance(serialised, str)

    def test_multiple_protocols_total_gas(self):
        txs = [
            make_tx(protocol="Aave V3",    gas_used=100_000, gas_price_gwei=10.0, eth_price_usd=1.0),
            make_tx(protocol="Compound V3", gas_used=200_000, gas_price_gwei=10.0, eth_price_usd=1.0),
        ]
        result = analyze(txs)
        expected_total = (100_000 * 10.0 / 1e9 + 200_000 * 10.0 / 1e9)
        self.assertAlmostEqual(result["total_gas_spent_usd"], expected_total, places=8)

    def test_by_protocol_avg_gas_single(self):
        tx = make_tx(gas_used=200_000, gas_price_gwei=20.0, eth_price_usd=3_000.0)
        result = analyze([tx])
        expected = 200_000 * 20.0 / 1e9 * 3_000.0
        self.assertAlmostEqual(result["by_protocol"]["Aave V3"]["avg_gas_usd"], expected, places=6)

    def test_float_sentinel_in_json(self):
        """INF_SENTINEL must be a normal float, not inf."""
        self.assertTrue(math.isfinite(INF_SENTINEL))


if __name__ == "__main__":
    unittest.main()
