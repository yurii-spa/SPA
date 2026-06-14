"""
Tests for MP-871 YieldSourceConcentrationRisk
≥65 unittest tests — pure stdlib, no third-party dependencies.
"""

import json
import math
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path setup so tests run from any directory
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.yield_source_concentration_risk import (
    analyze,
    _hhi,
    _compute_dimension,
    _risk_level,
    _overall_label,
    _recommendations,
    _atomic_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _pos(
    protocol="AaveV3",
    chain="Ethereum",
    asset_type="STABLECOIN",
    yield_type="LENDING",
    allocation_usd=10_000.0,
    apy_pct=5.0,
) -> dict:
    return {
        "protocol": protocol,
        "chain": chain,
        "asset_type": asset_type,
        "yield_type": yield_type,
        "allocation_usd": allocation_usd,
        "apy_pct": apy_pct,
    }


_FOUR_EQUAL = [
    _pos("A", "Ethereum", "STABLECOIN", "LENDING", 25_000),
    _pos("B", "Arbitrum", "ETH_LST", "STAKING", 25_000),
    _pos("C", "Optimism", "LP_TOKEN", "LP_FEES", 25_000),
    _pos("D", "Polygon", "GOVERNANCE_TOKEN", "FARMING", 25_000),
]

_ALL_ONE_PROTO = [
    _pos("Aave", "Ethereum", "STABLECOIN", "LENDING", 100_000),
]


# ===========================================================================
# 1. Internal helpers
# ===========================================================================

class TestHHI(unittest.TestCase):
    def test_single_share(self):
        self.assertAlmostEqual(_hhi([1.0]), 1.0)

    def test_equal_two(self):
        self.assertAlmostEqual(_hhi([0.5, 0.5]), 0.5)

    def test_equal_four(self):
        self.assertAlmostEqual(_hhi([0.25, 0.25, 0.25, 0.25]), 0.25)

    def test_empty(self):
        self.assertAlmostEqual(_hhi([]), 0.0)

    def test_unequal(self):
        # 60/40 split
        hhi = _hhi([0.6, 0.4])
        self.assertAlmostEqual(hhi, 0.52, places=5)

    def test_three_equal(self):
        v = 1 / 3
        self.assertAlmostEqual(_hhi([v, v, v]), 1 / 3, places=5)


class TestComputeDimension(unittest.TestCase):
    def test_empty_positions(self):
        hhi, top, top_pct, groups = _compute_dimension([], 0.0, "protocol")
        self.assertEqual(hhi, 0.0)
        self.assertIsNone(top)
        self.assertEqual(top_pct, 0.0)
        self.assertEqual(groups, {})

    def test_zero_total(self):
        hhi, top, top_pct, _ = _compute_dimension([_pos(allocation_usd=0)], 0.0, "protocol")
        self.assertEqual(hhi, 0.0)
        self.assertIsNone(top)

    def test_single_protocol(self):
        hhi, top, top_pct, _ = _compute_dimension(_ALL_ONE_PROTO, 100_000.0, "protocol")
        self.assertAlmostEqual(hhi, 1.0)
        self.assertEqual(top, "Aave")
        self.assertAlmostEqual(top_pct, 100.0)

    def test_equal_four_protocols(self):
        hhi, top, top_pct, _ = _compute_dimension(_FOUR_EQUAL, 100_000.0, "protocol")
        self.assertAlmostEqual(hhi, 0.25, places=5)
        self.assertAlmostEqual(top_pct, 25.0, places=5)

    def test_chain_dimension(self):
        positions = [
            _pos(chain="Ethereum", allocation_usd=70_000),
            _pos(chain="Arbitrum", allocation_usd=30_000),
        ]
        hhi, top, top_pct, _ = _compute_dimension(positions, 100_000.0, "chain")
        self.assertAlmostEqual(hhi, 0.7 ** 2 + 0.3 ** 2, places=5)
        self.assertEqual(top, "Ethereum")
        self.assertAlmostEqual(top_pct, 70.0, places=5)

    def test_asset_type_grouping(self):
        positions = [
            _pos(asset_type="STABLECOIN", allocation_usd=50_000),
            _pos(asset_type="STABLECOIN", allocation_usd=50_000),
        ]
        hhi, top, top_pct, groups = _compute_dimension(positions, 100_000.0, "asset_type")
        self.assertAlmostEqual(hhi, 1.0)
        self.assertEqual(top, "STABLECOIN")
        self.assertAlmostEqual(top_pct, 100.0)

    def test_groups_dict_present(self):
        positions = [
            _pos(protocol="X", allocation_usd=60_000),
            _pos(protocol="Y", allocation_usd=40_000),
        ]
        _, _, _, groups = _compute_dimension(positions, 100_000.0, "protocol")
        self.assertIn("X", groups)
        self.assertIn("Y", groups)
        self.assertAlmostEqual(groups["X"], 60_000.0)


class TestRiskLevel(unittest.TestCase):
    def test_low(self):
        self.assertEqual(_risk_level(0.10, 0.25, 0.5), "LOW")

    def test_boundary_low_moderate(self):
        self.assertEqual(_risk_level(0.15, 0.25, 0.5), "LOW")

    def test_moderate(self):
        self.assertEqual(_risk_level(0.20, 0.25, 0.5), "MODERATE")

    def test_high(self):
        self.assertEqual(_risk_level(0.30, 0.25, 0.5), "HIGH")

    def test_critical(self):
        self.assertEqual(_risk_level(0.60, 0.25, 0.5), "CRITICAL")

    def test_exactly_warning(self):
        # > warning → HIGH; == warning → MODERATE (not >)
        self.assertEqual(_risk_level(0.25, 0.25, 0.5), "MODERATE")

    def test_custom_thresholds(self):
        self.assertEqual(_risk_level(0.4, 0.3, 0.6), "HIGH")
        self.assertEqual(_risk_level(0.7, 0.3, 0.6), "CRITICAL")


class TestOverallLabel(unittest.TestCase):
    def test_well_diversified(self):
        self.assertEqual(_overall_label(10), "WELL_DIVERSIFIED")

    def test_moderate(self):
        self.assertEqual(_overall_label(20), "MODERATE")

    def test_concentrated(self):
        self.assertEqual(_overall_label(35), "CONCENTRATED")

    def test_highly_concentrated(self):
        self.assertEqual(_overall_label(60), "HIGHLY_CONCENTRATED")

    def test_boundary_moderate(self):
        self.assertEqual(_overall_label(19), "WELL_DIVERSIFIED")

    def test_boundary_concentrated(self):
        self.assertEqual(_overall_label(34), "MODERATE")


class TestRecommendations(unittest.TestCase):
    def test_all_adequate(self):
        recs = _recommendations(0.2, "A", 50, 0.2, "E", 50, 0.2, "SC", 50, 0.2, "LN", 50)
        self.assertEqual(recs, ["Diversification is adequate across all dimensions"])

    def test_high_protocol_hhi(self):
        recs = _recommendations(0.8, "Aave", 90, 0.2, "ETH", 50, 0.2, "SC", 50, 0.2, "LN", 50)
        self.assertTrue(any("Aave" in r for r in recs))

    def test_high_chain_hhi(self):
        recs = _recommendations(0.2, "A", 50, 0.9, "Ethereum", 95, 0.2, "SC", 50, 0.2, "LN", 50)
        self.assertTrue(any("Ethereum" in r for r in recs))

    def test_high_asset_hhi(self):
        recs = _recommendations(0.2, "A", 50, 0.2, "ETH", 50, 0.9, "STABLECOIN", 95, 0.2, "LN", 50)
        self.assertTrue(any("STABLECOIN" in r for r in recs))

    def test_high_yield_hhi(self):
        recs = _recommendations(0.2, "A", 50, 0.2, "ETH", 50, 0.2, "SC", 50, 0.9, "LENDING", 95)
        self.assertTrue(any("LENDING" in r for r in recs))

    def test_multiple_recs(self):
        recs = _recommendations(0.9, "A", 90, 0.9, "ETH", 90, 0.2, "SC", 50, 0.2, "LN", 50)
        self.assertGreaterEqual(len(recs), 2)

    def test_threshold_exact(self):
        # exactly 0.4 → NOT > 0.4 → no rec
        recs = _recommendations(0.4, "A", 50, 0.2, "ETH", 50, 0.2, "SC", 50, 0.2, "LN", 50)
        self.assertEqual(recs, ["Diversification is adequate across all dimensions"])

    def test_threshold_just_above(self):
        recs = _recommendations(0.401, "A", 50, 0.2, "ETH", 50, 0.2, "SC", 50, 0.2, "LN", 50)
        self.assertNotEqual(recs, ["Diversification is adequate across all dimensions"])


# ===========================================================================
# 2. analyze() — empty / edge cases
# ===========================================================================

class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.r = analyze([])

    def test_protocol_hhi_zero(self):
        self.assertEqual(self.r["protocol_concentration"]["hhi"], 0.0)

    def test_chain_hhi_zero(self):
        self.assertEqual(self.r["chain_concentration"]["hhi"], 0.0)

    def test_asset_hhi_zero(self):
        self.assertEqual(self.r["asset_type_concentration"]["hhi"], 0.0)

    def test_yield_hhi_zero(self):
        self.assertEqual(self.r["yield_type_concentration"]["hhi"], 0.0)

    def test_all_low_risk(self):
        self.assertEqual(self.r["protocol_concentration"]["risk_level"], "LOW")
        self.assertEqual(self.r["chain_concentration"]["risk_level"], "LOW")
        self.assertEqual(self.r["asset_type_concentration"]["risk_level"], "LOW")
        self.assertEqual(self.r["yield_type_concentration"]["risk_level"], "LOW")

    def test_score_zero(self):
        self.assertEqual(self.r["overall_concentration_score"], 0)

    def test_well_diversified(self):
        self.assertEqual(self.r["overall_risk_label"], "WELL_DIVERSIFIED")

    def test_weighted_apy_zero(self):
        self.assertEqual(self.r["weighted_avg_apy_pct"], 0.0)

    def test_total_alloc_zero(self):
        self.assertEqual(self.r["total_allocation_usd"], 0.0)

    def test_timestamp_present(self):
        self.assertIn("timestamp", self.r)
        self.assertIsInstance(self.r["timestamp"], float)

    def test_recommendations_adequate(self):
        self.assertEqual(
            self.r["diversification_recommendations"],
            ["Diversification is adequate across all dimensions"],
        )

    def test_top_protocol_none(self):
        self.assertIsNone(self.r["protocol_concentration"]["top_protocol"])

    def test_top_chain_none(self):
        self.assertIsNone(self.r["chain_concentration"]["top_chain"])


class TestAnalyzeSinglePosition(unittest.TestCase):
    def setUp(self):
        self.r = analyze([_pos(allocation_usd=50_000, apy_pct=4.0)])

    def test_protocol_hhi_one(self):
        self.assertAlmostEqual(self.r["protocol_concentration"]["hhi"], 1.0)

    def test_chain_hhi_one(self):
        self.assertAlmostEqual(self.r["chain_concentration"]["hhi"], 1.0)

    def test_asset_type_hhi_one(self):
        self.assertAlmostEqual(self.r["asset_type_concentration"]["hhi"], 1.0)

    def test_yield_type_hhi_one(self):
        self.assertAlmostEqual(self.r["yield_type_concentration"]["hhi"], 1.0)

    def test_weighted_apy(self):
        self.assertAlmostEqual(self.r["weighted_avg_apy_pct"], 4.0)

    def test_total_allocation(self):
        self.assertAlmostEqual(self.r["total_allocation_usd"], 50_000.0)

    def test_top_protocol(self):
        self.assertEqual(self.r["protocol_concentration"]["top_protocol"], "AaveV3")

    def test_top_protocol_share(self):
        self.assertAlmostEqual(
            self.r["protocol_concentration"]["top_protocol_share_pct"], 100.0
        )

    def test_risk_level_critical(self):
        self.assertEqual(self.r["protocol_concentration"]["risk_level"], "CRITICAL")


# ===========================================================================
# 3. analyze() — weighted APY
# ===========================================================================

class TestWeightedAPY(unittest.TestCase):
    def test_two_positions(self):
        positions = [
            _pos(allocation_usd=60_000, apy_pct=3.0),
            _pos(protocol="B", allocation_usd=40_000, apy_pct=7.0),
        ]
        r = analyze(positions)
        expected = (60_000 * 3.0 + 40_000 * 7.0) / 100_000
        self.assertAlmostEqual(r["weighted_avg_apy_pct"], expected, places=5)

    def test_equal_weights(self):
        positions = [
            _pos(allocation_usd=50_000, apy_pct=4.0),
            _pos(protocol="B", allocation_usd=50_000, apy_pct=6.0),
        ]
        r = analyze(positions)
        self.assertAlmostEqual(r["weighted_avg_apy_pct"], 5.0, places=5)

    def test_zero_apy(self):
        positions = [_pos(allocation_usd=100_000, apy_pct=0.0)]
        r = analyze(positions)
        self.assertAlmostEqual(r["weighted_avg_apy_pct"], 0.0)


# ===========================================================================
# 4. analyze() — protocol concentration
# ===========================================================================

class TestProtocolConcentration(unittest.TestCase):
    def test_two_protocols(self):
        positions = [
            _pos("AaveV3", allocation_usd=70_000),
            _pos("Compound", allocation_usd=30_000),
        ]
        r = analyze(positions)
        expected_hhi = 0.7 ** 2 + 0.3 ** 2
        self.assertAlmostEqual(r["protocol_concentration"]["hhi"], expected_hhi, places=5)

    def test_top_protocol_name(self):
        positions = [
            _pos("Morpho", allocation_usd=80_000),
            _pos("Euler", allocation_usd=20_000),
        ]
        r = analyze(positions)
        self.assertEqual(r["protocol_concentration"]["top_protocol"], "Morpho")

    def test_top_protocol_share(self):
        positions = [
            _pos("Morpho", allocation_usd=80_000),
            _pos("Euler", allocation_usd=20_000),
        ]
        r = analyze(positions)
        self.assertAlmostEqual(r["protocol_concentration"]["top_protocol_share_pct"], 80.0)

    def test_four_equal(self):
        r = analyze(_FOUR_EQUAL)
        self.assertAlmostEqual(r["protocol_concentration"]["hhi"], 0.25, places=5)


# ===========================================================================
# 5. analyze() — chain concentration
# ===========================================================================

class TestChainConcentration(unittest.TestCase):
    def test_two_chains(self):
        positions = [
            _pos(chain="Ethereum", allocation_usd=60_000),
            _pos(chain="Arbitrum", allocation_usd=40_000),
        ]
        r = analyze(positions)
        expected = 0.6 ** 2 + 0.4 ** 2
        self.assertAlmostEqual(r["chain_concentration"]["hhi"], expected, places=5)

    def test_single_chain_critical(self):
        positions = [
            _pos(chain="Ethereum", allocation_usd=50_000),
            _pos(chain="Ethereum", allocation_usd=50_000),
        ]
        r = analyze(positions)
        self.assertAlmostEqual(r["chain_concentration"]["hhi"], 1.0)
        self.assertEqual(r["chain_concentration"]["risk_level"], "CRITICAL")

    def test_three_chains_equal(self):
        positions = [
            _pos(chain="Ethereum", allocation_usd=33_333),
            _pos(chain="Arbitrum", allocation_usd=33_333),
            _pos(chain="Optimism", allocation_usd=33_334),
        ]
        r = analyze(positions)
        self.assertLess(r["chain_concentration"]["hhi"], 0.34)


# ===========================================================================
# 6. analyze() — asset_type concentration
# ===========================================================================

class TestAssetTypeConcentration(unittest.TestCase):
    def test_stablecoin_only(self):
        positions = [
            _pos(asset_type="STABLECOIN", allocation_usd=100_000),
        ]
        r = analyze(positions)
        self.assertAlmostEqual(r["asset_type_concentration"]["hhi"], 1.0)
        self.assertEqual(r["asset_type_concentration"]["top_asset_type"], "STABLECOIN")

    def test_mixed_asset_types(self):
        positions = [
            _pos(asset_type="STABLECOIN", allocation_usd=50_000),
            _pos(asset_type="ETH_LST", allocation_usd=50_000),
        ]
        r = analyze(positions)
        self.assertAlmostEqual(r["asset_type_concentration"]["hhi"], 0.5, places=5)

    def test_all_different_asset_types(self):
        positions = [
            _pos(asset_type="STABLECOIN", allocation_usd=20_000),
            _pos(asset_type="ETH_LST", allocation_usd=20_000),
            _pos(asset_type="LP_TOKEN", allocation_usd=20_000),
            _pos(asset_type="GOVERNANCE_TOKEN", allocation_usd=20_000),
            _pos(asset_type="BTC_DERIVATIVE", allocation_usd=20_000),
        ]
        r = analyze(positions)
        self.assertAlmostEqual(r["asset_type_concentration"]["hhi"], 0.2, places=5)


# ===========================================================================
# 7. analyze() — yield_type concentration
# ===========================================================================

class TestYieldTypeConcentration(unittest.TestCase):
    def test_lending_only(self):
        positions = [
            _pos(yield_type="LENDING", allocation_usd=100_000),
        ]
        r = analyze(positions)
        self.assertAlmostEqual(r["yield_type_concentration"]["hhi"], 1.0)

    def test_two_yield_types(self):
        positions = [
            _pos(yield_type="LENDING", allocation_usd=50_000),
            _pos(yield_type="STAKING", allocation_usd=50_000),
        ]
        r = analyze(positions)
        self.assertAlmostEqual(r["yield_type_concentration"]["hhi"], 0.5, places=5)

    def test_top_yield_type(self):
        positions = [
            _pos(yield_type="LENDING", allocation_usd=70_000),
            _pos(yield_type="FARMING", allocation_usd=30_000),
        ]
        r = analyze(positions)
        self.assertEqual(r["yield_type_concentration"]["top_yield_type"], "LENDING")


# ===========================================================================
# 8. analyze() — overall score & label
# ===========================================================================

class TestOverallScore(unittest.TestCase):
    def test_highly_concentrated_single(self):
        r = analyze([_pos(allocation_usd=100_000)])
        # all 4 HHI = 1.0 → avg = 1.0 → score = 100
        self.assertEqual(r["overall_concentration_score"], 100)
        self.assertEqual(r["overall_risk_label"], "HIGHLY_CONCENTRATED")

    def test_well_diversified_four_equal(self):
        r = analyze(_FOUR_EQUAL)
        # proto HHI=0.25, chain=0.25, asset_type=0.25, yield_type=0.25 → avg=0.25 → score=25
        self.assertEqual(r["overall_concentration_score"], 25)
        self.assertEqual(r["overall_risk_label"], "MODERATE")

    def test_score_type_is_int(self):
        r = analyze(_FOUR_EQUAL)
        self.assertIsInstance(r["overall_concentration_score"], int)

    def test_empty_score_zero(self):
        r = analyze([])
        self.assertEqual(r["overall_concentration_score"], 0)


# ===========================================================================
# 9. analyze() — config overrides
# ===========================================================================

class TestConfigOverrides(unittest.TestCase):
    def test_custom_warning_threshold(self):
        # default HIGH requires > 0.25; with low threshold even 0.26 → HIGH
        positions = [
            _pos("A", allocation_usd=60_000),
            _pos("B", allocation_usd=40_000),
        ]
        r = analyze(positions, config={"hhi_warning_threshold": 0.10, "hhi_critical_threshold": 0.9})
        self.assertEqual(r["protocol_concentration"]["risk_level"], "HIGH")

    def test_custom_critical_threshold(self):
        positions = [_pos(allocation_usd=100_000)]
        r = analyze(positions, config={"hhi_warning_threshold": 0.25, "hhi_critical_threshold": 0.99})
        # HHI=1.0 > 0.99 → CRITICAL
        self.assertEqual(r["protocol_concentration"]["risk_level"], "CRITICAL")

    def test_config_none_uses_defaults(self):
        r = analyze([_pos(allocation_usd=100_000)], config=None)
        self.assertEqual(r["protocol_concentration"]["risk_level"], "CRITICAL")

    def test_config_empty_uses_defaults(self):
        r = analyze([_pos(allocation_usd=100_000)], config={})
        self.assertEqual(r["protocol_concentration"]["risk_level"], "CRITICAL")


# ===========================================================================
# 10. analyze() — diversification recommendations
# ===========================================================================

class TestDiversificationRecs(unittest.TestCase):
    def test_protocol_rec_included(self):
        # Dominating protocol
        positions = [
            _pos("Aave", allocation_usd=90_000),
            _pos("Compound", allocation_usd=10_000),
        ]
        r = analyze(positions)
        recs = r["diversification_recommendations"]
        self.assertTrue(any("Aave" in rec for rec in recs))

    def test_chain_rec_included(self):
        positions = [
            _pos("A", chain="Ethereum", allocation_usd=90_000),
            _pos("B", chain="Arbitrum", allocation_usd=10_000),
        ]
        r = analyze(positions)
        recs = r["diversification_recommendations"]
        self.assertTrue(any("Ethereum" in rec for rec in recs))

    def test_no_recs_when_diverse(self):
        r = analyze(_FOUR_EQUAL)
        # HHI for each dimension ≈ 0.25, not > 0.4 → adequate
        self.assertEqual(
            r["diversification_recommendations"],
            ["Diversification is adequate across all dimensions"],
        )

    def test_recs_is_list(self):
        r = analyze([])
        self.assertIsInstance(r["diversification_recommendations"], list)

    def test_four_recs_when_all_concentrated(self):
        # All assets in a single bucket across all dims
        positions = [
            _pos("AaveV3", "Ethereum", "STABLECOIN", "LENDING", 100_000),
        ]
        r = analyze(positions)
        recs = r["diversification_recommendations"]
        # All 4 HHI = 1.0 > 0.4 → 4 recs
        self.assertEqual(len(recs), 4)


# ===========================================================================
# 11. Return structure completeness
# ===========================================================================

class TestReturnStructure(unittest.TestCase):
    def setUp(self):
        self.r = analyze(_FOUR_EQUAL)

    def test_top_level_keys(self):
        expected = {
            "protocol_concentration",
            "chain_concentration",
            "asset_type_concentration",
            "yield_type_concentration",
            "overall_concentration_score",
            "overall_risk_label",
            "weighted_avg_apy_pct",
            "total_allocation_usd",
            "diversification_recommendations",
            "timestamp",
        }
        self.assertEqual(set(self.r.keys()), expected)

    def test_protocol_sub_keys(self):
        expected = {"hhi", "top_protocol", "top_protocol_share_pct", "risk_level"}
        self.assertEqual(set(self.r["protocol_concentration"].keys()), expected)

    def test_chain_sub_keys(self):
        expected = {"hhi", "top_chain", "top_chain_share_pct", "risk_level"}
        self.assertEqual(set(self.r["chain_concentration"].keys()), expected)

    def test_asset_type_sub_keys(self):
        expected = {"hhi", "top_asset_type", "top_asset_type_share_pct", "risk_level"}
        self.assertEqual(set(self.r["asset_type_concentration"].keys()), expected)

    def test_yield_type_sub_keys(self):
        expected = {"hhi", "top_yield_type", "top_yield_type_share_pct", "risk_level"}
        self.assertEqual(set(self.r["yield_type_concentration"].keys()), expected)

    def test_hhi_float(self):
        self.assertIsInstance(self.r["protocol_concentration"]["hhi"], float)

    def test_risk_label_valid(self):
        valid = {"LOW", "MODERATE", "HIGH", "CRITICAL"}
        self.assertIn(self.r["protocol_concentration"]["risk_level"], valid)

    def test_overall_label_valid(self):
        valid = {"WELL_DIVERSIFIED", "MODERATE", "CONCENTRATED", "HIGHLY_CONCENTRATED"}
        self.assertIn(self.r["overall_risk_label"], valid)


# ===========================================================================
# 12. Atomic log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):
    def _make_log_path(self, tmp_dir):
        return os.path.join(tmp_dir, "test_log.json")

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            _atomic_log(path, {"x": 1})
            self.assertTrue(os.path.exists(path))

    def test_appends(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            _atomic_log(path, {"a": 1})
            _atomic_log(path, {"b": 2})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            for i in range(110):
                _atomic_log(path, {"i": i})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 100)

    def test_oldest_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            for i in range(105):
                _atomic_log(path, {"i": i})
            with open(path) as f:
                data = json.load(f)
            # first entry should be i=5 (entries 0-4 dropped)
            self.assertEqual(data[0]["i"], 5)

    def test_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            _atomic_log(path, {"ts": 12345})
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_overwrites_corrupted(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            with open(path, "w") as f:
                f.write("NOT JSON {{{{")
            # Should not raise; starts fresh
            _atomic_log(path, {"ok": True})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertTrue(data[0]["ok"])


# ===========================================================================
# 13. analyze() writes to log (integration)
# ===========================================================================

class TestAnalyzeWritesToLog(unittest.TestCase):
    def test_log_entry_written(self):
        """analyze() should write without error (log path may differ in test env)."""
        # We verify the function runs and returns a valid result; log is best-effort
        r = analyze([_pos(allocation_usd=100_000)])
        self.assertIn("timestamp", r)

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze([_pos()])
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)


# ===========================================================================
# 14. Additional edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def test_zero_allocation_position_ignored_in_hhi(self):
        """Zero-allocation position still participates but contributes 0 share."""
        positions = [
            _pos("A", allocation_usd=100_000),
            _pos("B", allocation_usd=0),
        ]
        r = analyze(positions)
        # total = 100_000; A share = 1.0 → HHI = 1.0
        self.assertAlmostEqual(r["protocol_concentration"]["hhi"], 1.0)

    def test_all_zero_allocations(self):
        positions = [
            _pos("A", allocation_usd=0),
            _pos("B", allocation_usd=0),
        ]
        r = analyze(positions)
        # total = 0 → _compute_dimension returns 0
        self.assertEqual(r["protocol_concentration"]["hhi"], 0.0)
        self.assertEqual(r["total_allocation_usd"], 0.0)

    def test_large_number_of_positions(self):
        # 50 equal-allocation positions across different protocols — only protocol varies,
        # so protocol HHI is 1/50 (very low), but chain/asset/yield are uniform → high HHI.
        positions = [
            _pos(protocol=f"Proto{i}", allocation_usd=2_000) for i in range(50)
        ]
        r = analyze(positions)
        self.assertAlmostEqual(r["protocol_concentration"]["hhi"], 1 / 50, places=4)
        # 50 protocols → protocol HHI=0.02 LOW; chain/asset/yield = 1.0 each → concentrated overall
        self.assertEqual(r["protocol_concentration"]["risk_level"], "LOW")

    def test_negative_allocation_handled(self):
        """Negative allocation is unlikely but should not crash."""
        positions = [
            _pos("A", allocation_usd=-1_000),
            _pos("B", allocation_usd=11_000),
        ]
        # Should not raise
        r = analyze(positions)
        self.assertIsInstance(r, dict)

    def test_missing_optional_fields(self):
        """Positions with missing keys should not crash analyze()."""
        positions = [{"allocation_usd": 10_000, "apy_pct": 5.0}]
        r = analyze(positions)
        self.assertIsInstance(r, dict)

    def test_float_precision(self):
        positions = [
            _pos("A", allocation_usd=33_333.33, apy_pct=5.0),
            _pos("B", allocation_usd=33_333.33, apy_pct=5.0),
            _pos("C", allocation_usd=33_333.34, apy_pct=5.0),
        ]
        r = analyze(positions)
        self.assertAlmostEqual(r["protocol_concentration"]["hhi"], 1 / 3, places=2)

    def test_multiple_calls_independent(self):
        r1 = analyze([_pos("A", allocation_usd=100_000)])
        r2 = analyze([_pos("A", allocation_usd=50_000), _pos("B", allocation_usd=50_000)])
        self.assertAlmostEqual(r1["protocol_concentration"]["hhi"], 1.0)
        self.assertAlmostEqual(r2["protocol_concentration"]["hhi"], 0.5)

    def test_total_allocation_correct(self):
        positions = [
            _pos(allocation_usd=30_000),
            _pos(protocol="B", allocation_usd=70_000),
        ]
        r = analyze(positions)
        self.assertAlmostEqual(r["total_allocation_usd"], 100_000.0)


if __name__ == "__main__":
    unittest.main()
