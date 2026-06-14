"""
Tests for MP-780: CrossChainYieldComparator
≥65 unittest tests covering net_apy computation, chain ranking, arbitrage score,
edge cases, validation, atomic write, and ring buffer.
"""

import json
import math
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path bootstrap — allow running from repo root or directly
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.cross_chain_yield_comparator import (
    CrossChainYieldComparator,
    _compute_net_apy,
    _compute_chain_premium,
    _compute_arbitrage_score,
    _best_chain_per_category,
    _validate_opportunity,
    _atomic_write_json,
    _load_log,
    _append_log,
    DAYS_PER_YEAR,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _opp(chain="ethereum", protocol="aave_v3", apy=4.0,
         bridge_cost_usd=0.0, bridge_time_hours=0.0,
         chain_gas_cost_daily_usd=1.0):
    return {
        "chain": chain,
        "protocol": protocol,
        "apy": apy,
        "bridge_cost_usd": bridge_cost_usd,
        "bridge_time_hours": bridge_time_hours,
        "chain_gas_cost_daily_usd": chain_gas_cost_daily_usd,
    }


class TempDirMixin(unittest.TestCase):
    """Provides a fresh temp directory for each test that needs file I/O."""
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)


# ===========================================================================
# 1. _compute_net_apy
# ===========================================================================

class TestComputeNetApy(unittest.TestCase):

    def test_zero_costs_returns_apy(self):
        opp = _opp(apy=5.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0)
        self.assertAlmostEqual(_compute_net_apy(opp, 100_000), 5.0, places=6)

    def test_bridge_cost_reduces_net_apy(self):
        # bridge_cost_usd=1000, gas=0, capital=100_000 → cost_pct = 1000/100000*100=1.0
        opp = _opp(apy=5.0, bridge_cost_usd=1000.0, chain_gas_cost_daily_usd=0.0)
        result = _compute_net_apy(opp, 100_000)
        self.assertAlmostEqual(result, 4.0, places=6)

    def test_gas_cost_reduces_net_apy(self):
        # gas=1/day → annual=365 → cost_pct = 365/100000*100=0.365
        opp = _opp(apy=5.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=1.0)
        result = _compute_net_apy(opp, 100_000)
        expected = 5.0 - (1.0 * 365 / 100_000 * 100)
        self.assertAlmostEqual(result, expected, places=6)

    def test_both_costs_combined(self):
        opp = _opp(apy=6.0, bridge_cost_usd=500.0, chain_gas_cost_daily_usd=2.0)
        result = _compute_net_apy(opp, 100_000)
        annual_cost = 500.0 + 2.0 * DAYS_PER_YEAR
        expected = 6.0 - (annual_cost / 100_000 * 100)
        self.assertAlmostEqual(result, expected, places=6)

    def test_smaller_capital_amplifies_cost(self):
        opp = _opp(apy=5.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=1.0)
        net_large = _compute_net_apy(opp, 1_000_000)
        net_small = _compute_net_apy(opp, 10_000)
        self.assertGreater(net_large, net_small)

    def test_negative_net_apy_possible(self):
        # Very high costs vs small capital → negative
        opp = _opp(apy=2.0, bridge_cost_usd=10_000.0, chain_gas_cost_daily_usd=50.0)
        result = _compute_net_apy(opp, 1_000)
        self.assertLess(result, 0)

    def test_raises_on_zero_capital(self):
        opp = _opp(apy=5.0)
        with self.assertRaises(ValueError):
            _compute_net_apy(opp, 0)

    def test_raises_on_negative_capital(self):
        opp = _opp(apy=5.0)
        with self.assertRaises(ValueError):
            _compute_net_apy(opp, -1)

    def test_exact_arithmetic_large_capital(self):
        opp = _opp(apy=10.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0)
        self.assertAlmostEqual(_compute_net_apy(opp, 1_000_000), 10.0, places=6)


# ===========================================================================
# 2. _compute_chain_premium
# ===========================================================================

class TestComputeChainPremium(unittest.TestCase):

    def test_zero_baseline(self):
        self.assertAlmostEqual(_compute_chain_premium(5.0, 0.0), 5.0, places=6)

    def test_eth_baseline_converted_from_fraction(self):
        # baseline 0.04 = 4% → premium = 5.0 - 4.0 = 1.0
        self.assertAlmostEqual(_compute_chain_premium(5.0, 0.04), 1.0, places=6)

    def test_negative_premium(self):
        self.assertLess(_compute_chain_premium(2.0, 0.05), 0)

    def test_zero_net_apy_with_zero_baseline(self):
        self.assertAlmostEqual(_compute_chain_premium(0.0, 0.0), 0.0, places=6)

    def test_large_baseline(self):
        premium = _compute_chain_premium(3.0, 0.10)
        self.assertAlmostEqual(premium, -7.0, places=6)


# ===========================================================================
# 3. _compute_arbitrage_score
# ===========================================================================

class TestComputeArbitrageScore(unittest.TestCase):

    def test_empty_list_returns_zero(self):
        self.assertEqual(_compute_arbitrage_score([]), 0.0)

    def test_single_opportunity_returns_zero(self):
        opps = [{"net_apy": 5.0}]
        self.assertEqual(_compute_arbitrage_score(opps), 0.0)

    def test_no_spread_returns_zero(self):
        opps = [{"net_apy": 5.0}, {"net_apy": 5.0}]
        self.assertAlmostEqual(_compute_arbitrage_score(opps), 0.0, places=2)

    def test_spread_of_1_gives_score_10(self):
        opps = [{"net_apy": 5.0}, {"net_apy": 4.0}]
        self.assertAlmostEqual(_compute_arbitrage_score(opps), 10.0, places=2)

    def test_score_capped_at_100(self):
        opps = [{"net_apy": 200.0}, {"net_apy": 0.0}]
        self.assertEqual(_compute_arbitrage_score(opps), 100.0)

    def test_score_non_negative(self):
        opps = [{"net_apy": 3.0}, {"net_apy": 2.0}]
        self.assertGreaterEqual(_compute_arbitrage_score(opps), 0.0)

    def test_three_opportunities(self):
        opps = [{"net_apy": 8.0}, {"net_apy": 5.0}, {"net_apy": 3.0}]
        score = _compute_arbitrage_score(opps)
        # spread = 8 - 3 = 5 → score = 50
        self.assertAlmostEqual(score, 50.0, places=2)


# ===========================================================================
# 4. _validate_opportunity
# ===========================================================================

class TestValidateOpportunity(unittest.TestCase):

    def test_valid_opportunity_passes(self):
        _validate_opportunity(_opp())  # should not raise

    def test_missing_chain_raises(self):
        opp = _opp()
        del opp["chain"]
        with self.assertRaises(ValueError):
            _validate_opportunity(opp)

    def test_missing_protocol_raises(self):
        opp = _opp()
        del opp["protocol"]
        with self.assertRaises(ValueError):
            _validate_opportunity(opp)

    def test_missing_apy_raises(self):
        opp = _opp()
        del opp["apy"]
        with self.assertRaises(ValueError):
            _validate_opportunity(opp)

    def test_missing_bridge_cost_raises(self):
        opp = _opp()
        del opp["bridge_cost_usd"]
        with self.assertRaises(ValueError):
            _validate_opportunity(opp)

    def test_missing_bridge_time_raises(self):
        opp = _opp()
        del opp["bridge_time_hours"]
        with self.assertRaises(ValueError):
            _validate_opportunity(opp)

    def test_missing_gas_cost_raises(self):
        opp = _opp()
        del opp["chain_gas_cost_daily_usd"]
        with self.assertRaises(ValueError):
            _validate_opportunity(opp)

    def test_negative_apy_raises(self):
        opp = _opp(apy=-1.0)
        with self.assertRaises(ValueError):
            _validate_opportunity(opp)

    def test_negative_bridge_cost_raises(self):
        opp = _opp(bridge_cost_usd=-5.0)
        with self.assertRaises(ValueError):
            _validate_opportunity(opp)

    def test_negative_bridge_time_raises(self):
        opp = {**_opp(), "bridge_time_hours": -1.0}
        with self.assertRaises(ValueError):
            _validate_opportunity(opp)

    def test_negative_gas_raises(self):
        opp = _opp(chain_gas_cost_daily_usd=-1.0)
        with self.assertRaises(ValueError):
            _validate_opportunity(opp)

    def test_zero_apy_valid(self):
        opp = _opp(apy=0.0)
        _validate_opportunity(opp)  # should not raise

    def test_zero_bridge_cost_valid(self):
        opp = _opp(bridge_cost_usd=0.0)
        _validate_opportunity(opp)  # should not raise


# ===========================================================================
# 5. _best_chain_per_category
# ===========================================================================

class TestBestChainPerCategory(unittest.TestCase):

    def test_single_protocol_returns_its_chain(self):
        opps = [{"protocol": "aave", "chain": "ethereum", "net_apy": 4.0}]
        result = _best_chain_per_category(opps)
        self.assertEqual(result, {"aave": "ethereum"})

    def test_two_protocols_different_chains(self):
        opps = [
            {"protocol": "aave", "chain": "ethereum", "net_apy": 4.0},
            {"protocol": "compound", "chain": "base", "net_apy": 5.0},
        ]
        result = _best_chain_per_category(opps)
        self.assertEqual(result["aave"], "ethereum")
        self.assertEqual(result["compound"], "base")

    def test_same_protocol_on_multiple_chains_picks_highest_net_apy(self):
        opps = [
            {"protocol": "aave", "chain": "ethereum", "net_apy": 3.0},
            {"protocol": "aave", "chain": "arbitrum", "net_apy": 5.5},
            {"protocol": "aave", "chain": "base", "net_apy": 4.0},
        ]
        result = _best_chain_per_category(opps)
        self.assertEqual(result["aave"], "arbitrum")

    def test_empty_list_returns_empty_dict(self):
        self.assertEqual(_best_chain_per_category([]), {})


# ===========================================================================
# 6. CrossChainYieldComparator.compare()
# ===========================================================================

class TestComparatorCompare(unittest.TestCase):

    def setUp(self):
        self.cmp = CrossChainYieldComparator()

    def test_empty_opportunities(self):
        result = self.cmp.compare([], capital_usd=100_000)
        self.assertEqual(result["ranked_opportunities"], [])
        self.assertEqual(result["cross_chain_arbitrage_score"], 0.0)
        self.assertIsNone(result["recommended_chain"])
        self.assertEqual(result["opportunity_count"], 0)

    def test_single_opportunity_ranked(self):
        opps = [_opp(chain="ethereum", apy=5.0,
                     bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0)]
        result = self.cmp.compare(opps, capital_usd=100_000)
        self.assertEqual(len(result["ranked_opportunities"]), 1)
        self.assertAlmostEqual(
            result["ranked_opportunities"][0]["net_apy"], 5.0, places=4
        )

    def test_ranked_by_net_apy_descending(self):
        opps = [
            _opp(chain="A", apy=3.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
            _opp(chain="B", apy=6.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
            _opp(chain="C", apy=4.5, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
        ]
        result = self.cmp.compare(opps, capital_usd=100_000)
        ranks = [o["net_apy"] for o in result["ranked_opportunities"]]
        self.assertEqual(ranks, sorted(ranks, reverse=True))

    def test_recommended_chain_is_top_net_apy(self):
        opps = [
            _opp(chain="ethereum", apy=3.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
            _opp(chain="arbitrum", apy=7.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
        ]
        result = self.cmp.compare(opps, capital_usd=100_000)
        self.assertEqual(result["recommended_chain"], "arbitrum")

    def test_eth_baseline_apy_stored_as_pct(self):
        result = self.cmp.compare([], capital_usd=100_000, eth_baseline_apy=0.04)
        self.assertAlmostEqual(result["eth_baseline_apy_pct"], 4.0, places=4)

    def test_chain_premium_vs_eth_in_output(self):
        opps = [_opp(chain="A", apy=6.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0)]
        result = self.cmp.compare(opps, capital_usd=100_000, eth_baseline_apy=0.04)
        opp = result["ranked_opportunities"][0]
        # net_apy=6.0, baseline=4.0 → premium=2.0
        self.assertAlmostEqual(opp["chain_premium_vs_eth"], 2.0, places=4)

    def test_annual_cost_usd_field_present(self):
        opps = [_opp(bridge_cost_usd=100.0, chain_gas_cost_daily_usd=1.0)]
        result = self.cmp.compare(opps, capital_usd=100_000)
        opp = result["ranked_opportunities"][0]
        expected_cost = 100.0 + 1.0 * DAYS_PER_YEAR
        self.assertAlmostEqual(opp["annual_cost_usd"], expected_cost, places=2)

    def test_capital_usd_in_result(self):
        result = self.cmp.compare([], capital_usd=50_000)
        self.assertEqual(result["capital_usd"], 50_000)

    def test_raises_on_zero_capital(self):
        with self.assertRaises(ValueError):
            self.cmp.compare([_opp()], capital_usd=0)

    def test_raises_on_negative_capital(self):
        with self.assertRaises(ValueError):
            self.cmp.compare([_opp()], capital_usd=-100)

    def test_invalid_opportunity_raises_in_compare(self):
        bad = _opp()
        del bad["chain"]
        with self.assertRaises(ValueError):
            self.cmp.compare([bad], capital_usd=100_000)

    def test_opportunity_count_field(self):
        opps = [_opp() for _ in range(5)]
        result = self.cmp.compare(opps, capital_usd=100_000)
        self.assertEqual(result["opportunity_count"], 5)

    def test_timestamp_utc_is_recent(self):
        result = self.cmp.compare([], capital_usd=100_000)
        now = time.time()
        self.assertLess(abs(result["timestamp_utc"] - now), 5)

    def test_best_chain_per_protocol_populated(self):
        opps = [
            _opp(chain="ethereum", protocol="aave", apy=4.0,
                 bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
            _opp(chain="arbitrum", protocol="aave", apy=5.5,
                 bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
        ]
        result = self.cmp.compare(opps, capital_usd=100_000)
        self.assertEqual(result["best_chain_per_protocol"]["aave"], "arbitrum")

    def test_multiple_protocols_in_best_chain(self):
        opps = [
            _opp(chain="A", protocol="p1", apy=3.0,
                 bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
            _opp(chain="B", protocol="p2", apy=6.0,
                 bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
        ]
        result = self.cmp.compare(opps, capital_usd=100_000)
        bcp = result["best_chain_per_protocol"]
        self.assertIn("p1", bcp)
        self.assertIn("p2", bcp)


# ===========================================================================
# 7. CrossChainYieldComparator.get_best_opportunity()
# ===========================================================================

class TestGetBestOpportunity(unittest.TestCase):

    def test_returns_none_before_compare(self):
        cmp = CrossChainYieldComparator()
        self.assertIsNone(cmp.get_best_opportunity())

    def test_returns_none_after_empty_compare(self):
        cmp = CrossChainYieldComparator()
        cmp.compare([], capital_usd=100_000)
        self.assertIsNone(cmp.get_best_opportunity())

    def test_returns_top_ranked(self):
        cmp = CrossChainYieldComparator()
        opps = [
            _opp(chain="low", apy=2.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
            _opp(chain="high", apy=8.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
        ]
        cmp.compare(opps, capital_usd=100_000)
        best = cmp.get_best_opportunity()
        self.assertIsNotNone(best)
        self.assertEqual(best["chain"], "high")

    def test_best_has_net_apy_field(self):
        cmp = CrossChainYieldComparator()
        cmp.compare([_opp(apy=5.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0)],
                    capital_usd=100_000)
        best = cmp.get_best_opportunity()
        self.assertIn("net_apy", best)

    def test_best_updates_after_second_compare(self):
        cmp = CrossChainYieldComparator()
        opps1 = [_opp(chain="A", apy=3.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0)]
        opps2 = [_opp(chain="B", apy=9.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0)]
        cmp.compare(opps1, capital_usd=100_000)
        cmp.compare(opps2, capital_usd=100_000)
        self.assertEqual(cmp.get_best_opportunity()["chain"], "B")


# ===========================================================================
# 8. CrossChainYieldComparator.get_chain_ranking()
# ===========================================================================

class TestGetChainRanking(unittest.TestCase):

    def test_returns_empty_before_compare(self):
        cmp = CrossChainYieldComparator()
        self.assertEqual(cmp.get_chain_ranking(), [])

    def test_returns_empty_after_empty_compare(self):
        cmp = CrossChainYieldComparator()
        cmp.compare([], capital_usd=100_000)
        self.assertEqual(cmp.get_chain_ranking(), [])

    def test_single_chain_ranking(self):
        cmp = CrossChainYieldComparator()
        cmp.compare(
            [_opp(chain="ethereum", apy=5.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0)],
            capital_usd=100_000
        )
        ranking = cmp.get_chain_ranking()
        self.assertEqual(len(ranking), 1)
        self.assertEqual(ranking[0]["chain"], "ethereum")

    def test_ranking_sorted_by_avg_net_apy(self):
        cmp = CrossChainYieldComparator()
        opps = [
            _opp(chain="low_chain", apy=2.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
            _opp(chain="high_chain", apy=8.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
        ]
        cmp.compare(opps, capital_usd=100_000)
        ranking = cmp.get_chain_ranking()
        self.assertEqual(ranking[0]["chain"], "high_chain")

    def test_ranking_entry_fields(self):
        cmp = CrossChainYieldComparator()
        cmp.compare(
            [_opp(chain="eth", apy=5.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0)],
            capital_usd=100_000
        )
        entry = cmp.get_chain_ranking()[0]
        for field in ("chain", "avg_net_apy", "max_net_apy", "min_net_apy", "opportunity_count"):
            self.assertIn(field, entry)

    def test_multiple_opps_same_chain_aggregated(self):
        cmp = CrossChainYieldComparator()
        opps = [
            _opp(chain="eth", apy=4.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
            _opp(chain="eth", apy=6.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
        ]
        cmp.compare(opps, capital_usd=100_000)
        ranking = cmp.get_chain_ranking()
        self.assertEqual(len(ranking), 1)
        self.assertEqual(ranking[0]["opportunity_count"], 2)
        self.assertAlmostEqual(ranking[0]["avg_net_apy"], 5.0, places=4)

    def test_two_chains_separate_entries(self):
        cmp = CrossChainYieldComparator()
        opps = [
            _opp(chain="A", apy=3.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
            _opp(chain="B", apy=7.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
        ]
        cmp.compare(opps, capital_usd=100_000)
        ranking = cmp.get_chain_ranking()
        chains = [r["chain"] for r in ranking]
        self.assertIn("A", chains)
        self.assertIn("B", chains)


# ===========================================================================
# 9. Atomic write / ring buffer / log I/O
# ===========================================================================

class TestAtomicWriteAndLog(TempDirMixin):

    def test_atomic_write_creates_file(self):
        path = os.path.join(self._tmpdir, "test.json")
        _atomic_write_json(path, [1, 2, 3])
        self.assertTrue(os.path.exists(path))

    def test_atomic_write_content_correct(self):
        path = os.path.join(self._tmpdir, "test.json")
        data = {"a": 1, "b": [1, 2]}
        _atomic_write_json(path, data)
        with open(path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_atomic_write_creates_directories(self):
        path = os.path.join(self._tmpdir, "sub1", "sub2", "file.json")
        _atomic_write_json(path, {"x": 1})
        self.assertTrue(os.path.exists(path))

    def test_load_log_empty_if_no_file(self):
        path = os.path.join(self._tmpdir, "nonexistent.json")
        self.assertEqual(_load_log(path), [])

    def test_load_log_returns_list(self):
        path = os.path.join(self._tmpdir, "log.json")
        _atomic_write_json(path, [{"a": 1}])
        result = _load_log(path)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)

    def test_load_log_empty_list_on_corrupt_json(self):
        path = os.path.join(self._tmpdir, "corrupt.json")
        with open(path, "w") as f:
            f.write("NOT_JSON{{{")
        self.assertEqual(_load_log(path), [])

    def test_append_log_basic(self):
        path = os.path.join(self._tmpdir, "log.json")
        _append_log(path, {"entry": 1}, cap=10)
        result = _load_log(path)
        self.assertEqual(len(result), 1)

    def test_append_log_ring_buffer_cap(self):
        path = os.path.join(self._tmpdir, "log.json")
        for i in range(15):
            _append_log(path, {"i": i}, cap=10)
        result = _load_log(path)
        self.assertEqual(len(result), 10)

    def test_append_log_keeps_latest(self):
        path = os.path.join(self._tmpdir, "log.json")
        for i in range(12):
            _append_log(path, {"i": i}, cap=10)
        result = _load_log(path)
        self.assertEqual(result[0]["i"], 2)
        self.assertEqual(result[-1]["i"], 11)

    def test_write_log_flag_creates_log_file(self):
        cmp = CrossChainYieldComparator(data_dir=self._tmpdir)
        cmp.compare([], capital_usd=100_000, write_log=True)
        log_path = os.path.join(self._tmpdir, "cross_chain_yield_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_write_log_entry_has_expected_keys(self):
        cmp = CrossChainYieldComparator(data_dir=self._tmpdir)
        cmp.compare(
            [_opp(apy=5.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0)],
            capital_usd=100_000,
            write_log=True,
        )
        log_path = os.path.join(self._tmpdir, "cross_chain_yield_log.json")
        with open(log_path) as f:
            log = json.load(f)
        entry = log[0]
        for key in (
            "timestamp_utc", "capital_usd", "eth_baseline_apy_pct",
            "recommended_chain", "cross_chain_arbitrage_score", "opportunity_count",
        ):
            self.assertIn(key, entry)

    def test_ring_buffer_capped_at_100_by_default(self):
        cmp = CrossChainYieldComparator(data_dir=self._tmpdir)
        for _ in range(105):
            cmp.compare([], capital_usd=100_000, write_log=True)
        log_path = os.path.join(self._tmpdir, "cross_chain_yield_log.json")
        with open(log_path) as f:
            log = json.load(f)
        self.assertLessEqual(len(log), 100)

    def test_write_log_false_does_not_create_file(self):
        cmp = CrossChainYieldComparator(data_dir=self._tmpdir)
        cmp.compare([], capital_usd=100_000, write_log=False)
        log_path = os.path.join(self._tmpdir, "cross_chain_yield_log.json")
        self.assertFalse(os.path.exists(log_path))


# ===========================================================================
# 10. Integration / edge-case scenarios
# ===========================================================================

class TestIntegrationScenarios(unittest.TestCase):

    def setUp(self):
        self.cmp = CrossChainYieldComparator()

    def test_arbitrum_beats_ethereum_after_bridge(self):
        opps = [
            _opp(chain="ethereum", apy=4.5,
                 bridge_cost_usd=0.0, chain_gas_cost_daily_usd=2.0),
            _opp(chain="arbitrum", apy=6.0,
                 bridge_cost_usd=20.0, chain_gas_cost_daily_usd=0.05),
        ]
        result = self.cmp.compare(opps, capital_usd=100_000)
        self.assertEqual(result["recommended_chain"], "arbitrum")

    def test_high_gas_can_flip_ranking(self):
        # Ethereum has higher gross APY but much higher gas
        opps = [
            _opp(chain="ethereum", apy=8.0,
                 bridge_cost_usd=0.0, chain_gas_cost_daily_usd=10.0),
            _opp(chain="optimism", apy=5.0,
                 bridge_cost_usd=5.0, chain_gas_cost_daily_usd=0.01),
        ]
        result = self.cmp.compare(opps, capital_usd=10_000)
        # eth annual gas = 10*365 = 3650 → cost_pct = 3650/10000*100 = 36.5 → net = 8-36.5 = -28.5
        # optimism: (5+0.01*365)/10000*100 = (5+3.65)/10000*100 = 0.0865 → net = 5-0.0865 = 4.9135
        self.assertEqual(result["recommended_chain"], "optimism")

    def test_arbitrage_score_increases_with_spread(self):
        opps_small = [
            _opp(chain="A", apy=5.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
            _opp(chain="B", apy=5.5, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
        ]
        opps_large = [
            _opp(chain="A", apy=3.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
            _opp(chain="B", apy=10.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
        ]
        r_small = self.cmp.compare(opps_small, capital_usd=100_000)
        r_large = self.cmp.compare(opps_large, capital_usd=100_000)
        self.assertLess(
            r_small["cross_chain_arbitrage_score"],
            r_large["cross_chain_arbitrage_score"]
        )

    def test_zero_apy_opportunity_accepted(self):
        opp = _opp(apy=0.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0)
        result = self.cmp.compare([opp], capital_usd=100_000)
        self.assertEqual(len(result["ranked_opportunities"]), 1)
        self.assertAlmostEqual(result["ranked_opportunities"][0]["net_apy"], 0.0, places=4)

    def test_many_opportunities_correct_count(self):
        opps = [_opp(chain=f"chain_{i}", apy=float(i),
                     bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0)
                for i in range(20)]
        result = self.cmp.compare(opps, capital_usd=100_000)
        self.assertEqual(result["opportunity_count"], 20)

    def test_original_opp_dict_not_mutated(self):
        opp = _opp(apy=5.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0)
        original_keys = set(opp.keys())
        self.cmp.compare([opp], capital_usd=100_000)
        self.assertEqual(set(opp.keys()), original_keys)

    def test_chain_ranking_after_multi_opp_compare(self):
        opps = [
            _opp(chain="eth", apy=4.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
            _opp(chain="eth", apy=5.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
            _opp(chain="arb", apy=6.0, bridge_cost_usd=0.0, chain_gas_cost_daily_usd=0.0),
        ]
        self.cmp.compare(opps, capital_usd=100_000)
        ranking = self.cmp.get_chain_ranking()
        # arb avg=6.0, eth avg=4.5 → arb first
        self.assertEqual(ranking[0]["chain"], "arb")

    def test_net_apy_precision(self):
        opp = _opp(apy=7.777777, bridge_cost_usd=100.0, chain_gas_cost_daily_usd=0.123456)
        result = self.cmp.compare([opp], capital_usd=100_000)
        net = result["ranked_opportunities"][0]["net_apy"]
        self.assertIsInstance(net, float)
        # Should be a finite number
        self.assertTrue(math.isfinite(net))


if __name__ == "__main__":
    unittest.main(verbosity=2)
