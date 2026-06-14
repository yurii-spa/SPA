"""
Tests for MP-1114 — DeFiProtocolYieldSourceDiversificationScorer
≥110 test cases using unittest (NOT pytest).
Run: python3 -m unittest spa_core.tests.test_defi_protocol_yield_source_diversification_scorer -v
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_yield_source_diversification_scorer import (
    VALID_YIELD_TYPES,
    DeFiProtocolYieldSourceDiversificationScorer,
    score_diversification,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _pos(protocol="Aave", chain="Ethereum", yield_type="lending", value=10000, apy=4.0):
    return {"protocol": protocol, "chain": chain, "yield_type": yield_type, "value_usd": value, "apy_pct": apy}


def _all_diff(n=4):
    """Return n positions each with distinct protocol/chain/yield_type."""
    protocols = ["Aave", "Compound", "Curve", "Lido", "Maker", "Yearn"]
    chains = ["Ethereum", "Arbitrum", "Polygon", "Optimism", "BSC", "Avalanche"]
    yield_types = list(VALID_YIELD_TYPES)
    return [
        _pos(
            protocol=protocols[i % len(protocols)],
            chain=chains[i % len(chains)],
            yield_type=yield_types[i % len(yield_types)],
            value=10000,
            apy=4.0 + i,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------
class TestBasicReturnStructure(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path="/tmp/test_div_log.json")
        self.positions = [_pos()]

    def test_returns_dict(self):
        r = self.scorer.score(self.positions, write_log=False)
        self.assertIsInstance(r, dict)

    def test_has_module_key(self):
        r = self.scorer.score(self.positions, write_log=False)
        self.assertEqual(r["module"], "MP-1114")

    def test_has_total_value_usd(self):
        r = self.scorer.score(self.positions, write_log=False)
        self.assertIn("total_value_usd", r)

    def test_has_protocol_hhi(self):
        r = self.scorer.score(self.positions, write_log=False)
        self.assertIn("protocol_hhi", r)

    def test_has_chain_hhi(self):
        r = self.scorer.score(self.positions, write_log=False)
        self.assertIn("chain_hhi", r)

    def test_has_yield_type_hhi(self):
        r = self.scorer.score(self.positions, write_log=False)
        self.assertIn("yield_type_hhi", r)

    def test_has_weighted_avg_apy(self):
        r = self.scorer.score(self.positions, write_log=False)
        self.assertIn("weighted_avg_apy_pct", r)

    def test_has_diversification_score(self):
        r = self.scorer.score(self.positions, write_log=False)
        self.assertIn("diversification_score", r)

    def test_has_largest_single_exposure_pct(self):
        r = self.scorer.score(self.positions, write_log=False)
        self.assertIn("largest_single_exposure_pct", r)

    def test_has_diversification_label(self):
        r = self.scorer.score(self.positions, write_log=False)
        self.assertIn("diversification_label", r)

    def test_has_position_count(self):
        r = self.scorer.score(self.positions, write_log=False)
        self.assertIn("position_count", r)

    def test_has_timestamp(self):
        r = self.scorer.score(self.positions, write_log=False)
        self.assertIn("timestamp", r)


class TestTotalValue(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path="/tmp/test_div_log.json")

    def test_single_position_total_value(self):
        r = self.scorer.score([_pos(value=50000)], write_log=False)
        self.assertAlmostEqual(r["total_value_usd"], 50000.0, places=2)

    def test_two_positions_sum(self):
        positions = [_pos(value=30000), _pos(protocol="Compound", value=70000)]
        r = self.scorer.score(positions, write_log=False)
        self.assertAlmostEqual(r["total_value_usd"], 100000.0, places=2)

    def test_many_positions_sum(self):
        positions = _all_diff(6)
        total = sum(p["value_usd"] for p in positions)
        r = self.scorer.score(positions, write_log=False)
        self.assertAlmostEqual(r["total_value_usd"], total, places=2)

    def test_fractional_values_sum(self):
        positions = [_pos(value=333.33), _pos(protocol="B", value=666.67)]
        r = self.scorer.score(positions, write_log=False)
        self.assertAlmostEqual(r["total_value_usd"], 1000.0, places=1)


class TestHHI(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path="/tmp/test_div_log.json")

    def test_single_protocol_hhi_is_10000(self):
        positions = [_pos(value=50000), _pos(value=50000)]
        r = self.scorer.score(positions, write_log=False)
        self.assertAlmostEqual(r["protocol_hhi"], 10000.0, places=2)

    def test_two_equal_protocols_hhi(self):
        positions = [_pos(value=50000), _pos(protocol="Compound", value=50000)]
        r = self.scorer.score(positions, write_log=False)
        # Each protocol 50% → HHI = 50^2 + 50^2 = 5000
        self.assertAlmostEqual(r["protocol_hhi"], 5000.0, places=2)

    def test_hhi_range_zero_to_ten_thousand(self):
        r = self.scorer.score(_all_diff(4), write_log=False)
        self.assertGreaterEqual(r["protocol_hhi"], 0)
        self.assertLessEqual(r["protocol_hhi"], 10001)

    def test_chain_hhi_single_chain(self):
        positions = [_pos(chain="Ethereum", value=50000), _pos(protocol="B", chain="Ethereum", value=50000)]
        r = self.scorer.score(positions, write_log=False)
        self.assertAlmostEqual(r["chain_hhi"], 10000.0, places=2)

    def test_chain_hhi_two_equal_chains(self):
        positions = [_pos(chain="Ethereum", value=50000), _pos(protocol="B", chain="Arbitrum", value=50000)]
        r = self.scorer.score(positions, write_log=False)
        self.assertAlmostEqual(r["chain_hhi"], 5000.0, places=2)

    def test_yield_type_hhi_single_type(self):
        positions = [_pos(yield_type="lending", value=50000), _pos(protocol="B", yield_type="lending", value=50000)]
        r = self.scorer.score(positions, write_log=False)
        self.assertAlmostEqual(r["yield_type_hhi"], 10000.0, places=2)

    def test_yield_type_hhi_two_equal_types(self):
        positions = [
            _pos(yield_type="lending", value=50000),
            _pos(protocol="B", yield_type="staking", value=50000),
        ]
        r = self.scorer.score(positions, write_log=False)
        self.assertAlmostEqual(r["yield_type_hhi"], 5000.0, places=2)

    def test_four_equal_protocols_hhi(self):
        positions = [
            _pos(protocol="A", value=25000),
            _pos(protocol="B", value=25000),
            _pos(protocol="C", value=25000),
            _pos(protocol="D", value=25000),
        ]
        r = self.scorer.score(positions, write_log=False)
        # Each 25% → 25^2 * 4 = 2500
        self.assertAlmostEqual(r["protocol_hhi"], 2500.0, places=2)

    def test_unequal_protocol_hhi_order(self):
        positions_equal = [_pos(protocol=f"P{i}", value=25000) for i in range(4)]
        positions_unequal = [
            _pos(protocol="A", value=70000),
            _pos(protocol="B", value=10000),
            _pos(protocol="C", value=10000),
            _pos(protocol="D", value=10000),
        ]
        r_eq = self.scorer.score(positions_equal, write_log=False)
        r_un = self.scorer.score(positions_unequal, write_log=False)
        self.assertGreater(r_un["protocol_hhi"], r_eq["protocol_hhi"])


class TestWeightedAvgAPY(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path="/tmp/test_div_log.json")

    def test_single_position_apy(self):
        r = self.scorer.score([_pos(apy=5.5)], write_log=False)
        self.assertAlmostEqual(r["weighted_avg_apy_pct"], 5.5, places=4)

    def test_two_equal_positions_avg_apy(self):
        positions = [_pos(protocol="A", value=50000, apy=4.0), _pos(protocol="B", value=50000, apy=8.0)]
        r = self.scorer.score(positions, write_log=False)
        self.assertAlmostEqual(r["weighted_avg_apy_pct"], 6.0, places=4)

    def test_weighted_apy_skews_toward_larger(self):
        positions = [_pos(protocol="A", value=90000, apy=2.0), _pos(protocol="B", value=10000, apy=20.0)]
        r = self.scorer.score(positions, write_log=False)
        self.assertLess(r["weighted_avg_apy_pct"], 10.0)
        self.assertGreater(r["weighted_avg_apy_pct"], 2.0)

    def test_zero_apy(self):
        r = self.scorer.score([_pos(apy=0.0)], write_log=False)
        self.assertAlmostEqual(r["weighted_avg_apy_pct"], 0.0, places=4)

    def test_negative_apy_allowed(self):
        r = self.scorer.score([_pos(apy=-1.5)], write_log=False)
        self.assertAlmostEqual(r["weighted_avg_apy_pct"], -1.5, places=4)


class TestLargestSingleExposure(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path="/tmp/test_div_log.json")

    def test_single_position_is_100_pct(self):
        r = self.scorer.score([_pos(value=10000)], write_log=False)
        self.assertAlmostEqual(r["largest_single_exposure_pct"], 100.0, places=4)

    def test_two_equal_positions_is_50_pct(self):
        positions = [_pos(protocol="A", value=50000), _pos(protocol="B", value=50000)]
        r = self.scorer.score(positions, write_log=False)
        self.assertAlmostEqual(r["largest_single_exposure_pct"], 50.0, places=4)

    def test_dominant_position(self):
        positions = [_pos(protocol="A", value=90000), _pos(protocol="B", value=10000)]
        r = self.scorer.score(positions, write_log=False)
        self.assertAlmostEqual(r["largest_single_exposure_pct"], 90.0, places=4)

    def test_largest_exposure_always_gte_0(self):
        r = self.scorer.score(_all_diff(5), write_log=False)
        self.assertGreaterEqual(r["largest_single_exposure_pct"], 0.0)

    def test_largest_exposure_always_lte_100(self):
        r = self.scorer.score([_pos(value=1000000)], write_log=False)
        self.assertLessEqual(r["largest_single_exposure_pct"], 100.0)


class TestDiversificationScore(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path="/tmp/test_div_log.json")

    def test_score_is_int(self):
        r = self.scorer.score(_all_diff(4), write_log=False)
        self.assertIsInstance(r["diversification_score"], int)

    def test_score_range_0_to_100(self):
        r = self.scorer.score([_pos(value=10000)], write_log=False)
        self.assertGreaterEqual(r["diversification_score"], 0)
        self.assertLessEqual(r["diversification_score"], 100)

    def test_well_diversified_has_high_score(self):
        positions = _all_diff(6)
        r = self.scorer.score(positions, write_log=False)
        self.assertGreater(r["diversification_score"], 50)

    def test_single_position_has_low_score(self):
        # One protocol, one chain, one yield type → max HHI
        r = self.scorer.score([_pos(value=100000)], write_log=False)
        self.assertLess(r["diversification_score"], 5)

    def test_more_protocols_higher_score(self):
        r2 = self.scorer.score(_all_diff(2), write_log=False)
        r6 = self.scorer.score(_all_diff(6), write_log=False)
        self.assertGreater(r6["diversification_score"], r2["diversification_score"])


class TestDiversificationLabel(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path="/tmp/test_div_log.json")

    def test_single_position_is_single_point_of_failure(self):
        r = self.scorer.score([_pos(value=100000)], write_log=False)
        self.assertEqual(r["diversification_label"], "SINGLE_POINT_OF_FAILURE")

    def test_label_is_string(self):
        r = self.scorer.score(_all_diff(4), write_log=False)
        self.assertIsInstance(r["diversification_label"], str)

    def test_valid_label_values(self):
        valid = {
            "WELL_DIVERSIFIED",
            "GOOD_DIVERSIFICATION",
            "MODERATE_CONCENTRATION",
            "CONCENTRATED",
            "SINGLE_POINT_OF_FAILURE",
        }
        r = self.scorer.score(_all_diff(4), write_log=False)
        self.assertIn(r["diversification_label"], valid)

    def test_two_equal_protocols_moderate_or_better(self):
        positions = [_pos(protocol="A", value=50000), _pos(protocol="B", value=50000)]
        r = self.scorer.score(positions, write_log=False)
        # HHI = 5000 → CONCENTRATED
        self.assertIn(
            r["diversification_label"],
            {"CONCENTRATED", "MODERATE_CONCENTRATION", "GOOD_DIVERSIFICATION", "WELL_DIVERSIFIED"},
        )

    def test_well_diversified_label_for_many_equal(self):
        positions = [_pos(protocol=f"P{i}", value=10000) for i in range(20)]
        r = self.scorer.score(positions, write_log=False)
        self.assertEqual(r["diversification_label"], "WELL_DIVERSIFIED")

    def test_label_good_diversification(self):
        # 6 equal protocols → HHI ≈ 1667 → GOOD_DIVERSIFICATION
        positions = [_pos(protocol=f"P{i}", value=10000) for i in range(6)]
        r = self.scorer.score(positions, write_log=False)
        self.assertEqual(r["diversification_label"], "GOOD_DIVERSIFICATION")

    def test_label_moderate_concentration(self):
        # 3 equal protocols → HHI ≈ 3333 → MODERATE_CONCENTRATION
        positions = [_pos(protocol=f"P{i}", value=10000) for i in range(3)]
        r = self.scorer.score(positions, write_log=False)
        self.assertEqual(r["diversification_label"], "MODERATE_CONCENTRATION")

    def test_label_concentrated(self):
        # 2 equal protocols → HHI = 5000 → CONCENTRATED
        positions = [_pos(protocol=f"P{i}", value=10000) for i in range(2)]
        r = self.scorer.score(positions, write_log=False)
        self.assertEqual(r["diversification_label"], "CONCENTRATED")


class TestEmptyAndEdgeCases(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path="/tmp/test_div_log.json")

    def test_empty_positions_returns_dict(self):
        r = self.scorer.score([], write_log=False)
        self.assertIsInstance(r, dict)

    def test_empty_positions_total_value_zero(self):
        r = self.scorer.score([], write_log=False)
        self.assertEqual(r["total_value_usd"], 0.0)

    def test_empty_positions_label_well_diversified(self):
        r = self.scorer.score([], write_log=False)
        self.assertEqual(r["diversification_label"], "WELL_DIVERSIFIED")

    def test_empty_positions_score_100(self):
        r = self.scorer.score([], write_log=False)
        self.assertEqual(r["diversification_score"], 100)

    def test_zero_value_positions(self):
        r = self.scorer.score([_pos(value=0)], write_log=False)
        self.assertEqual(r["total_value_usd"], 0.0)

    def test_protocol_name_stored(self):
        r = self.scorer.score([_pos()], protocol_name="TestFund", write_log=False)
        self.assertEqual(r["protocol_name"], "TestFund")

    def test_protocol_name_none_default_empty_string(self):
        r = self.scorer.score([_pos()], write_log=False)
        self.assertEqual(r["protocol_name"], "")

    def test_position_count_correct(self):
        r = self.scorer.score(_all_diff(5), write_log=False)
        self.assertEqual(r["position_count"], 5)

    def test_single_position_count(self):
        r = self.scorer.score([_pos()], write_log=False)
        self.assertEqual(r["position_count"], 1)

    def test_large_portfolio(self):
        positions = [_pos(protocol=f"P{i}", chain=f"C{i%4}", yield_type=list(VALID_YIELD_TYPES)[i%6], value=1000) for i in range(50)]
        r = self.scorer.score(positions, write_log=False)
        self.assertEqual(r["position_count"], 50)


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path="/tmp/test_div_log.json")

    def test_missing_protocol_raises(self):
        bad = {"chain": "Ethereum", "yield_type": "lending", "value_usd": 1000, "apy_pct": 4.0}
        with self.assertRaises((ValueError, KeyError)):
            self.scorer.score([bad], write_log=False)

    def test_missing_chain_raises(self):
        bad = {"protocol": "Aave", "yield_type": "lending", "value_usd": 1000, "apy_pct": 4.0}
        with self.assertRaises((ValueError, KeyError)):
            self.scorer.score([bad], write_log=False)

    def test_missing_yield_type_raises(self):
        bad = {"protocol": "Aave", "chain": "Ethereum", "value_usd": 1000, "apy_pct": 4.0}
        with self.assertRaises((ValueError, KeyError)):
            self.scorer.score([bad], write_log=False)

    def test_invalid_yield_type_raises(self):
        bad = _pos(yield_type="invalid_type")
        with self.assertRaises(ValueError):
            self.scorer.score([bad], write_log=False)

    def test_negative_value_raises(self):
        with self.assertRaises(ValueError):
            self.scorer.score([_pos(value=-100)], write_log=False)

    def test_all_valid_yield_types_accepted(self):
        for yt in VALID_YIELD_TYPES:
            r = self.scorer.score([_pos(yield_type=yt)], write_log=False)
            self.assertEqual(r["position_count"], 1)

    def test_uppercase_yield_type_accepted(self):
        pos = {"protocol": "Aave", "chain": "Ethereum", "yield_type": "LENDING", "value_usd": 1000, "apy_pct": 4.0}
        r = self.scorer.score([pos], write_log=False)
        self.assertEqual(r["position_count"], 1)

    def test_mixed_case_yield_type_accepted(self):
        pos = {"protocol": "Aave", "chain": "Ethereum", "yield_type": "Lending", "value_usd": 1000, "apy_pct": 4.0}
        r = self.scorer.score([pos], write_log=False)
        self.assertEqual(r["position_count"], 1)


class TestYieldTypes(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path="/tmp/test_div_log.json")

    def test_lending_yield_type(self):
        r = self.scorer.score([_pos(yield_type="lending")], write_log=False)
        self.assertIsNotNone(r)

    def test_amm_yield_type(self):
        r = self.scorer.score([_pos(yield_type="amm")], write_log=False)
        self.assertIsNotNone(r)

    def test_staking_yield_type(self):
        r = self.scorer.score([_pos(yield_type="staking")], write_log=False)
        self.assertIsNotNone(r)

    def test_farming_yield_type(self):
        r = self.scorer.score([_pos(yield_type="farming")], write_log=False)
        self.assertIsNotNone(r)

    def test_cdp_yield_type(self):
        r = self.scorer.score([_pos(yield_type="cdp")], write_log=False)
        self.assertIsNotNone(r)

    def test_restaking_yield_type(self):
        r = self.scorer.score([_pos(yield_type="restaking")], write_log=False)
        self.assertIsNotNone(r)

    def test_all_six_yield_types_equal_hhi(self):
        positions = [_pos(protocol=f"P{i}", yield_type=yt, value=10000) for i, yt in enumerate(VALID_YIELD_TYPES)]
        r = self.scorer.score(positions, write_log=False)
        # 6 equal groups → HHI ≈ 1667
        self.assertAlmostEqual(r["yield_type_hhi"], 10000 / 6, delta=10)


class TestLogging(unittest.TestCase):
    def test_log_file_created(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            log_path = f.name
        os.unlink(log_path)
        scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path=log_path)
        scorer.score([_pos()], write_log=True)
        self.assertTrue(os.path.exists(log_path))
        os.unlink(log_path)

    def test_log_contains_list(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            log_path = f.name
        os.unlink(log_path)
        scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path=log_path)
        scorer.score([_pos()], write_log=True)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        os.unlink(log_path)

    def test_log_accumulates_entries(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            log_path = f.name
        os.unlink(log_path)
        scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path=log_path)
        for _ in range(5):
            scorer.score([_pos()], write_log=True)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)
        os.unlink(log_path)

    def test_log_ring_buffer_caps_at_100(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            log_path = f.name
        os.unlink(log_path)
        scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path=log_path)
        for _ in range(110):
            scorer.score([_pos()], write_log=True)
        with open(log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)
        os.unlink(log_path)

    def test_log_entry_has_log_id(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            log_path = f.name
        os.unlink(log_path)
        scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path=log_path)
        scorer.score([_pos()], write_log=True)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIn("log_id", data[0])
        os.unlink(log_path)

    def test_log_entry_has_module_key(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            log_path = f.name
        os.unlink(log_path)
        scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path=log_path)
        scorer.score([_pos()], write_log=True)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["module"], "MP-1114")
        os.unlink(log_path)

    def test_no_log_when_write_false(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            log_path = f.name
        os.unlink(log_path)
        scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path=log_path)
        scorer.score([_pos()], write_log=False)
        self.assertFalse(os.path.exists(log_path))


class TestConvenienceFunction(unittest.TestCase):
    def test_returns_dict(self):
        r = score_diversification([_pos()])
        self.assertIsInstance(r, dict)

    def test_protocol_name_passed(self):
        r = score_diversification([_pos()], protocol_name="TestFund")
        self.assertEqual(r["protocol_name"], "TestFund")

    def test_no_log_by_default(self):
        tmp = "/tmp/conv_test_log.json"
        if os.path.exists(tmp):
            os.unlink(tmp)
        score_diversification([_pos()], log_path=tmp, write_log=False)
        self.assertFalse(os.path.exists(tmp))


class TestChainDiversification(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path="/tmp/test_div_log.json")

    def test_single_chain_hhi_is_10000(self):
        positions = [
            _pos(protocol="A", chain="Ethereum", value=30000),
            _pos(protocol="B", chain="Ethereum", value=70000),
        ]
        r = self.scorer.score(positions, write_log=False)
        self.assertAlmostEqual(r["chain_hhi"], 10000.0, places=2)

    def test_four_chains_equal_hhi(self):
        positions = [
            _pos(protocol=f"P{i}", chain=f"Chain{i}", value=25000)
            for i in range(4)
        ]
        r = self.scorer.score(positions, write_log=False)
        self.assertAlmostEqual(r["chain_hhi"], 2500.0, places=2)

    def test_chain_diversification_improves_score(self):
        single_chain = [
            _pos(protocol="A", chain="Ethereum", value=50000),
            _pos(protocol="B", chain="Ethereum", value=50000),
        ]
        multi_chain = [
            _pos(protocol="A", chain="Ethereum", value=50000),
            _pos(protocol="B", chain="Arbitrum", value=50000),
        ]
        r_single = self.scorer.score(single_chain, write_log=False)
        r_multi = self.scorer.score(multi_chain, write_log=False)
        self.assertGreater(r_multi["diversification_score"], r_single["diversification_score"])


class TestHHILabelBoundaries(unittest.TestCase):
    """Test HHI label transitions at specific boundary values."""

    def setUp(self):
        self.scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path="/tmp/test_div_log.json")

    def _positions_with_hhi(self, target_hhi: float):
        """Create 2-protocol positions targeting approximate HHI using concentration."""
        # HHI = s^2 + (100-s)^2 = 2s^2 - 200s + 10000
        # For target HHI: solve for s
        import math
        # Use 10 protocols equal → HHI = 1000
        if target_hhi < 1000:
            return [_pos(protocol=f"P{i}", value=10000) for i in range(10)]
        # 5 equal → HHI = 2000
        if target_hhi < 2000:
            return [_pos(protocol=f"P{i}", value=10000) for i in range(5)]
        # 3 equal → HHI ≈ 3333
        if target_hhi < 4000:
            return [_pos(protocol=f"P{i}", value=10000) for i in range(3)]
        # 2 equal → HHI = 5000
        if target_hhi < 7000:
            return [_pos(protocol=f"P{i}", value=10000) for i in range(2)]
        # 1 → HHI = 10000
        return [_pos(value=10000)]

    def test_11_equal_protocols_well_diversified(self):
        # 11 equal → HHI ≈ 909 < 1000 → WELL_DIVERSIFIED
        positions = [_pos(protocol=f"P{i}", value=10000) for i in range(11)]
        r = self.scorer.score(positions, write_log=False)
        self.assertEqual(r["diversification_label"], "WELL_DIVERSIFIED")

    def test_7_equal_protocols_good_diversification(self):
        # 7 equal → HHI ≈ 1429 → GOOD_DIVERSIFICATION
        positions = [_pos(protocol=f"P{i}", value=10000) for i in range(7)]
        r = self.scorer.score(positions, write_log=False)
        self.assertEqual(r["diversification_label"], "GOOD_DIVERSIFICATION")

    def test_3_equal_protocols_moderate_concentration(self):
        positions = [_pos(protocol=f"P{i}", value=10000) for i in range(3)]
        r = self.scorer.score(positions, write_log=False)
        self.assertEqual(r["diversification_label"], "MODERATE_CONCENTRATION")

    def test_2_equal_protocols_concentrated(self):
        positions = [_pos(protocol=f"P{i}", value=10000) for i in range(2)]
        r = self.scorer.score(positions, write_log=False)
        self.assertEqual(r["diversification_label"], "CONCENTRATED")

    def test_1_protocol_single_point_of_failure(self):
        r = self.scorer.score([_pos(value=100000)], write_log=False)
        self.assertEqual(r["diversification_label"], "SINGLE_POINT_OF_FAILURE")


class TestScoreMonotonicity(unittest.TestCase):
    """More diversification → higher score."""

    def setUp(self):
        self.scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path="/tmp/test_div_log.json")

    def test_score_increases_with_more_protocols(self):
        scores = []
        for n in [1, 2, 4, 8]:
            positions = [_pos(protocol=f"P{i}", value=10000) for i in range(n)]
            r = self.scorer.score(positions, write_log=False)
            scores.append(r["diversification_score"])
        self.assertTrue(all(scores[i] <= scores[i + 1] for i in range(len(scores) - 1)))

    def test_score_type_is_int(self):
        r = self.scorer.score(_all_diff(3), write_log=False)
        self.assertIsInstance(r["diversification_score"], int)

    def test_hhi_values_are_floats(self):
        r = self.scorer.score(_all_diff(3), write_log=False)
        self.assertIsInstance(r["protocol_hhi"], float)
        self.assertIsInstance(r["chain_hhi"], float)
        self.assertIsInstance(r["yield_type_hhi"], float)


class TestRealWorldPortfolios(unittest.TestCase):
    """Test with realistic portfolio scenarios."""

    def setUp(self):
        self.scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path="/tmp/test_div_log.json")

    def test_spa_sample_portfolio(self):
        positions = [
            _pos("Aave", "Ethereum", "lending", 40000, 3.5),
            _pos("Compound", "Ethereum", "lending", 30000, 4.8),
            _pos("Curve", "Ethereum", "amm", 20000, 6.0),
            _pos("Lido", "Ethereum", "staking", 10000, 4.0),
        ]
        r = self.scorer.score(positions, "SPA Portfolio", write_log=False)
        self.assertEqual(r["total_value_usd"], 100000.0)
        self.assertEqual(r["position_count"], 4)
        self.assertGreater(r["diversification_score"], 0)

    def test_single_protocol_full_exposure(self):
        r = self.scorer.score([_pos("Aave", "Ethereum", "lending", 100000, 3.5)], write_log=False)
        self.assertEqual(r["largest_single_exposure_pct"], 100.0)
        self.assertEqual(r["diversification_label"], "SINGLE_POINT_OF_FAILURE")

    def test_multi_chain_cross_protocol_portfolio(self):
        positions = [
            _pos("Aave", "Ethereum", "lending", 25000, 3.5),
            _pos("Aave", "Arbitrum", "lending", 25000, 4.5),
            _pos("Compound", "Ethereum", "lending", 25000, 4.8),
            _pos("GMX", "Arbitrum", "farming", 25000, 12.0),
        ]
        r = self.scorer.score(positions, write_log=False)
        self.assertAlmostEqual(r["total_value_usd"], 100000.0, places=2)
        self.assertEqual(r["position_count"], 4)
        # 3 protocols, 2 chains
        self.assertLess(r["chain_hhi"], 10000)

    def test_weighted_apy_realistic(self):
        positions = [
            _pos("Aave", "Ethereum", "lending", 50000, 3.5),
            _pos("Pendle", "Ethereum", "farming", 50000, 15.0),
        ]
        r = self.scorer.score(positions, write_log=False)
        self.assertAlmostEqual(r["weighted_avg_apy_pct"], 9.25, places=2)

    def test_restaking_and_lending_mix(self):
        positions = [
            _pos("EigenLayer", "Ethereum", "restaking", 30000, 8.0),
            _pos("Aave", "Ethereum", "lending", 70000, 3.5),
        ]
        r = self.scorer.score(positions, write_log=False)
        self.assertEqual(r["position_count"], 2)
        self.assertIn("yield_type_hhi", r)

    def test_cdp_farming_combo(self):
        positions = [
            _pos("Maker", "Ethereum", "cdp", 40000, 5.0),
            _pos("Convex", "Ethereum", "farming", 60000, 10.0),
        ]
        r = self.scorer.score(positions, write_log=False)
        # Two protocols → concentrated
        self.assertEqual(r["diversification_label"], "CONCENTRATED")


class TestStaticMethods(unittest.TestCase):
    """Test internal static methods directly."""

    def test_hhi_single_bucket(self):
        positions = [{"protocol": "A", "chain": "E", "yield_type": "lending", "value_usd": 100, "apy_pct": 5}]
        hhi = DeFiProtocolYieldSourceDiversificationScorer._hhi_by(positions, 100, "protocol")
        self.assertAlmostEqual(hhi, 10000.0, places=2)

    def test_hhi_two_equal_buckets(self):
        positions = [
            {"protocol": "A", "chain": "E", "yield_type": "lending", "value_usd": 50, "apy_pct": 5},
            {"protocol": "B", "chain": "E", "yield_type": "lending", "value_usd": 50, "apy_pct": 5},
        ]
        hhi = DeFiProtocolYieldSourceDiversificationScorer._hhi_by(positions, 100, "protocol")
        self.assertAlmostEqual(hhi, 5000.0, places=2)

    def test_weighted_avg_apy_correct(self):
        positions = [
            {"value_usd": 100, "apy_pct": 10.0},
            {"value_usd": 100, "apy_pct": 20.0},
        ]
        avg = DeFiProtocolYieldSourceDiversificationScorer._weighted_avg_apy(positions, 200)
        self.assertAlmostEqual(avg, 15.0, places=4)

    def test_largest_single_exposure_pct_correct(self):
        positions = [
            {"value_usd": 80},
            {"value_usd": 20},
        ]
        pct = DeFiProtocolYieldSourceDiversificationScorer._largest_single_exposure_pct(positions, 100)
        self.assertAlmostEqual(pct, 80.0, places=4)

    def test_diversification_score_monopoly(self):
        score = DeFiProtocolYieldSourceDiversificationScorer._diversification_score(10000, 10000, 10000)
        self.assertEqual(score, 0)

    def test_diversification_label_static(self):
        self.assertEqual(
            DeFiProtocolYieldSourceDiversificationScorer._diversification_label(500),
            "WELL_DIVERSIFIED",
        )
        self.assertEqual(
            DeFiProtocolYieldSourceDiversificationScorer._diversification_label(1500),
            "GOOD_DIVERSIFICATION",
        )
        self.assertEqual(
            DeFiProtocolYieldSourceDiversificationScorer._diversification_label(3000),
            "MODERATE_CONCENTRATION",
        )
        self.assertEqual(
            DeFiProtocolYieldSourceDiversificationScorer._diversification_label(5000),
            "CONCENTRATED",
        )
        self.assertEqual(
            DeFiProtocolYieldSourceDiversificationScorer._diversification_label(8000),
            "SINGLE_POINT_OF_FAILURE",
        )


class TestAdditionalCoverage(unittest.TestCase):
    """Extra tests to reach ≥110 per file."""

    def setUp(self):
        self.scorer = DeFiProtocolYieldSourceDiversificationScorer(log_path="/tmp/test_div_log.json")

    def test_20_equal_protocols_well_diversified(self):
        positions = [_pos(protocol=f"P{i}", value=10000) for i in range(20)]
        r = self.scorer.score(positions, write_log=False)
        self.assertEqual(r["diversification_label"], "WELL_DIVERSIFIED")

    def test_protocol_hhi_decreases_as_positions_increase(self):
        r4 = self.scorer.score([_pos(protocol=f"P{i}", value=10000) for i in range(4)], write_log=False)
        r8 = self.scorer.score([_pos(protocol=f"P{i}", value=10000) for i in range(8)], write_log=False)
        self.assertGreater(r4["protocol_hhi"], r8["protocol_hhi"])

    def test_chain_hhi_decreases_as_chains_increase(self):
        r2 = self.scorer.score([_pos(protocol=f"P{i}", chain=f"C{i%2}", value=10000) for i in range(4)], write_log=False)
        r4 = self.scorer.score([_pos(protocol=f"P{i}", chain=f"C{i}", value=10000) for i in range(4)], write_log=False)
        self.assertGreater(r2["chain_hhi"], r4["chain_hhi"])

    def test_apy_type_is_float(self):
        r = self.scorer.score([_pos(apy=5.5)], write_log=False)
        self.assertIsInstance(r["weighted_avg_apy_pct"], float)

    def test_hhi_nonnegative(self):
        positions = _all_diff(5)
        r = self.scorer.score(positions, write_log=False)
        self.assertGreaterEqual(r["protocol_hhi"], 0)
        self.assertGreaterEqual(r["chain_hhi"], 0)
        self.assertGreaterEqual(r["yield_type_hhi"], 0)

    def test_diversification_score_single_protocol_is_0(self):
        # Max HHI on all dimensions → score 0
        positions = [_pos(value=100000)]  # 1 protocol, 1 chain, 1 yield_type
        r = self.scorer.score(positions, write_log=False)
        self.assertEqual(r["diversification_score"], 0)

    def test_timestamp_is_float(self):
        r = self.scorer.score([_pos()], write_log=False)
        self.assertIsInstance(r["timestamp"], float)

    def test_total_value_is_float(self):
        r = self.scorer.score([_pos(value=50000)], write_log=False)
        self.assertIsInstance(r["total_value_usd"], float)

    def test_mixed_yield_types_hhi_less_than_single(self):
        single = [_pos(yield_type="lending", value=50000), _pos(protocol="B", yield_type="lending", value=50000)]
        mixed = [_pos(yield_type="lending", value=50000), _pos(protocol="B", yield_type="staking", value=50000)]
        r_single = self.scorer.score(single, write_log=False)
        r_mixed = self.scorer.score(mixed, write_log=False)
        self.assertGreater(r_single["yield_type_hhi"], r_mixed["yield_type_hhi"])

    def test_protocol_name_not_none_in_result(self):
        r = self.scorer.score([_pos()], protocol_name="MyFund", write_log=False)
        self.assertIsNotNone(r["protocol_name"])


if __name__ == "__main__":
    unittest.main()
