"""
Tests for MP-890: ProtocolTVLConcentrationAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_tvl_concentration_analyzer -v
"""

import json
import math
import os
import sys
import tempfile
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_tvl_concentration_analyzer import (
    _tvl_pct,
    _concentration_label,
    _hhi,
    _concentration_risk,
    _build_by_chain,
    _build_by_asset_type,
    _top_by_tvl,
    _build_flags,
    analyze,
    run_and_log,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def demo_ecosystem(**overrides):
    base = {
        "protocols": [
            {"name": "Aave V3", "tvl_usd": 8_000_000_000.0,
             "chain": "Ethereum", "asset_type": "STABLECOIN"},
            {"name": "Compound V3", "tvl_usd": 3_000_000_000.0,
             "chain": "Ethereum", "asset_type": "STABLECOIN"},
            {"name": "Morpho", "tvl_usd": 2_000_000_000.0,
             "chain": "Ethereum", "asset_type": "ETH_LST"},
            {"name": "Yearn V3", "tvl_usd": 1_000_000_000.0,
             "chain": "Ethereum", "asset_type": "STABLECOIN"},
            {"name": "GMX", "tvl_usd": 500_000_000.0,
             "chain": "Arbitrum", "asset_type": "OTHER"},
        ],
        "total_ecosystem_tvl_usd": 14_500_000_000.0,
    }
    base.update(overrides)
    return base


def single_protocol_ecosystem(tvl=10_000_000.0, total=10_000_000.0, chain="Ethereum",
                               asset_type="STABLECOIN"):
    return {
        "protocols": [
            {"name": "OnlyProtocol", "tvl_usd": tvl,
             "chain": chain, "asset_type": asset_type},
        ],
        "total_ecosystem_tvl_usd": total,
    }


def empty_ecosystem():
    return {"protocols": [], "total_ecosystem_tvl_usd": 0.0}


# ===========================================================================
# Section 1: _tvl_pct
# ===========================================================================
class TestTvlPct(unittest.TestCase):

    def test_basic(self):
        self.assertAlmostEqual(_tvl_pct(50.0, 100.0), 50.0)

    def test_zero_total_returns_zero(self):
        self.assertEqual(_tvl_pct(100.0, 0.0), 0.0)

    def test_negative_total_returns_zero(self):
        self.assertEqual(_tvl_pct(100.0, -1.0), 0.0)

    def test_full_share(self):
        self.assertAlmostEqual(_tvl_pct(100.0, 100.0), 100.0)

    def test_fractional(self):
        self.assertAlmostEqual(_tvl_pct(1.0, 3.0), 100.0 / 3, places=5)

    def test_zero_tvl(self):
        self.assertEqual(_tvl_pct(0.0, 100.0), 0.0)


# ===========================================================================
# Section 2: _concentration_label
# ===========================================================================
class TestConcentrationLabel(unittest.TestCase):

    def test_dominant_above_20(self):
        self.assertEqual(_concentration_label(21.0), "DOMINANT")

    def test_significant_above_10(self):
        self.assertEqual(_concentration_label(11.0), "SIGNIFICANT")

    def test_moderate_above_5(self):
        self.assertEqual(_concentration_label(6.0), "MODERATE")

    def test_minor_at_5(self):
        self.assertEqual(_concentration_label(5.0), "MINOR")

    def test_minor_below_5(self):
        self.assertEqual(_concentration_label(1.0), "MINOR")

    def test_boundary_exactly_20(self):
        # > 20 is DOMINANT; ==20 should NOT be dominant
        self.assertNotEqual(_concentration_label(20.0), "DOMINANT")

    def test_boundary_exactly_10(self):
        self.assertNotEqual(_concentration_label(10.0), "SIGNIFICANT")

    def test_zero_pct_is_minor(self):
        self.assertEqual(_concentration_label(0.0), "MINOR")

    def test_100_pct_is_dominant(self):
        self.assertEqual(_concentration_label(100.0), "DOMINANT")


# ===========================================================================
# Section 3: _hhi
# ===========================================================================
class TestHhi(unittest.TestCase):

    def test_empty_list(self):
        self.assertEqual(_hhi([]), 0.0)

    def test_single_protocol_100pct(self):
        # (100/100)^2 * 10000 = 10000
        self.assertAlmostEqual(_hhi([100.0]), 10000.0, places=5)

    def test_two_equal_protocols(self):
        # 2 * (50/100)^2 * 10000 = 2 * 0.25 * 10000 = 5000
        self.assertAlmostEqual(_hhi([50.0, 50.0]), 5000.0, places=5)

    def test_four_equal_protocols(self):
        # 4 * (25/100)^2 * 10000 = 4 * 625 = 2500
        self.assertAlmostEqual(_hhi([25.0, 25.0, 25.0, 25.0]), 2500.0, places=5)

    def test_all_zero(self):
        self.assertAlmostEqual(_hhi([0.0, 0.0, 0.0]), 0.0, places=5)

    def test_monotone_higher_concentration_higher_hhi(self):
        hhi_equal = _hhi([50.0, 50.0])
        hhi_unequal = _hhi([80.0, 20.0])
        self.assertGreater(hhi_unequal, hhi_equal)

    def test_returns_float(self):
        self.assertIsInstance(_hhi([50.0, 50.0]), float)


# ===========================================================================
# Section 4: _concentration_risk
# ===========================================================================
class TestConcentrationRisk(unittest.TestCase):

    def test_low_below_1000(self):
        self.assertEqual(_concentration_risk(999.9), "LOW")

    def test_moderate_at_1000(self):
        self.assertEqual(_concentration_risk(1000.0), "MODERATE")

    def test_high_at_2500(self):
        self.assertEqual(_concentration_risk(2500.0), "HIGH")

    def test_critical_at_5000(self):
        self.assertEqual(_concentration_risk(5000.0), "CRITICAL")

    def test_critical_above_5000(self):
        self.assertEqual(_concentration_risk(9999.0), "CRITICAL")

    def test_moderate_range(self):
        self.assertEqual(_concentration_risk(1500.0), "MODERATE")

    def test_high_range(self):
        self.assertEqual(_concentration_risk(3000.0), "HIGH")

    def test_zero_is_low(self):
        self.assertEqual(_concentration_risk(0.0), "LOW")

    def test_single_protocol_is_critical(self):
        # single protocol → HHI = 10000 → CRITICAL
        self.assertEqual(_concentration_risk(10000.0), "CRITICAL")


# ===========================================================================
# Section 5: _build_by_chain
# ===========================================================================
class TestBuildByChain(unittest.TestCase):

    def test_returns_dict(self):
        result = _build_by_chain(demo_ecosystem()["protocols"], 14_500_000_000.0)
        self.assertIsInstance(result, dict)

    def test_chains_present(self):
        result = _build_by_chain(demo_ecosystem()["protocols"], 14_500_000_000.0)
        self.assertIn("Ethereum", result)
        self.assertIn("Arbitrum", result)

    def test_protocol_count(self):
        result = _build_by_chain(demo_ecosystem()["protocols"], 14_500_000_000.0)
        self.assertEqual(result["Ethereum"]["protocol_count"], 4)
        self.assertEqual(result["Arbitrum"]["protocol_count"], 1)

    def test_tvl_sum(self):
        result = _build_by_chain(demo_ecosystem()["protocols"], 14_500_000_000.0)
        eth_tvl = 8e9 + 3e9 + 2e9 + 1e9
        self.assertAlmostEqual(result["Ethereum"]["tvl_usd"], eth_tvl, places=0)

    def test_tvl_pct_computed(self):
        result = _build_by_chain(demo_ecosystem()["protocols"], 14_500_000_000.0)
        for chain in result:
            self.assertIn("tvl_pct", result[chain])

    def test_empty_protocols(self):
        result = _build_by_chain([], 100.0)
        self.assertEqual(result, {})

    def test_zero_total_pct_zero(self):
        result = _build_by_chain(demo_ecosystem()["protocols"], 0.0)
        for chain in result:
            self.assertEqual(result[chain]["tvl_pct"], 0.0)


# ===========================================================================
# Section 6: _build_by_asset_type
# ===========================================================================
class TestBuildByAssetType(unittest.TestCase):

    def test_returns_dict(self):
        result = _build_by_asset_type(demo_ecosystem()["protocols"], 14_500_000_000.0)
        self.assertIsInstance(result, dict)

    def test_asset_types_present(self):
        result = _build_by_asset_type(demo_ecosystem()["protocols"], 14_500_000_000.0)
        self.assertIn("STABLECOIN", result)
        self.assertIn("ETH_LST", result)
        self.assertIn("OTHER", result)

    def test_stablecoin_sum(self):
        result = _build_by_asset_type(demo_ecosystem()["protocols"], 14_500_000_000.0)
        expected = 8e9 + 3e9 + 1e9
        self.assertAlmostEqual(result["STABLECOIN"]["tvl_usd"], expected, places=0)

    def test_tvl_pct_computed(self):
        result = _build_by_asset_type(demo_ecosystem()["protocols"], 14_500_000_000.0)
        for at in result:
            self.assertIn("tvl_pct", result[at])

    def test_empty_protocols(self):
        result = _build_by_asset_type([], 100.0)
        self.assertEqual(result, {})


# ===========================================================================
# Section 7: _top_by_tvl
# ===========================================================================
class TestTopByTvl(unittest.TestCase):

    def test_returns_none_for_empty(self):
        self.assertIsNone(_top_by_tvl({}))

    def test_returns_max_key(self):
        mapping = {
            "A": {"tvl_usd": 100.0},
            "B": {"tvl_usd": 500.0},
            "C": {"tvl_usd": 50.0},
        }
        self.assertEqual(_top_by_tvl(mapping), "B")

    def test_single_entry(self):
        mapping = {"X": {"tvl_usd": 1000.0}}
        self.assertEqual(_top_by_tvl(mapping), "X")

    def test_returns_string(self):
        mapping = {"A": {"tvl_usd": 1.0}}
        self.assertIsInstance(_top_by_tvl(mapping), str)


# ===========================================================================
# Section 8: _build_flags
# ===========================================================================
class TestBuildFlags(unittest.TestCase):

    def _make_proto(self, pct):
        return {"tvl_pct": pct}

    def test_no_flags_balanced(self):
        protos = [self._make_proto(10.0), self._make_proto(10.0), self._make_proto(10.0)]
        by_chain = {"Eth": {"tvl_pct": 30.0}}
        by_at = {"STABLECOIN": {"tvl_pct": 30.0}}
        flags = _build_flags(protos, by_chain, by_at, 20.0)
        self.assertEqual(flags, [])

    def test_single_protocol_dominant_flag(self):
        protos = [self._make_proto(25.0)]
        by_chain = {"Eth": {"tvl_pct": 100.0}}
        by_at = {"STABLECOIN": {"tvl_pct": 100.0}}
        flags = _build_flags(protos, by_chain, by_at, 20.0)
        self.assertIn("SINGLE_PROTOCOL_DOMINANT", flags)

    def test_single_chain_dominant_flag(self):
        protos = [self._make_proto(5.0)]
        by_chain = {"Eth": {"tvl_pct": 60.0}}
        by_at = {"OTHER": {"tvl_pct": 5.0}}
        flags = _build_flags(protos, by_chain, by_at, 20.0)
        self.assertIn("SINGLE_CHAIN_DOMINANT", flags)

    def test_stablecoin_heavy_flag(self):
        protos = [self._make_proto(10.0)]
        by_chain = {"Eth": {"tvl_pct": 10.0}}
        by_at = {"STABLECOIN": {"tvl_pct": 65.0}}
        flags = _build_flags(protos, by_chain, by_at, 20.0)
        self.assertIn("STABLECOIN_HEAVY", flags)

    def test_all_flags_simultaneously(self):
        protos = [self._make_proto(25.0)]
        by_chain = {"Eth": {"tvl_pct": 55.0}}
        by_at = {"STABLECOIN": {"tvl_pct": 70.0}}
        flags = _build_flags(protos, by_chain, by_at, 20.0)
        self.assertIn("SINGLE_PROTOCOL_DOMINANT", flags)
        self.assertIn("SINGLE_CHAIN_DOMINANT", flags)
        self.assertIn("STABLECOIN_HEAVY", flags)

    def test_custom_warning_pct(self):
        protos = [self._make_proto(15.0)]
        by_chain = {"Eth": {"tvl_pct": 15.0}}
        by_at = {"OTHER": {"tvl_pct": 15.0}}
        # With warning=10, 15% triggers SINGLE_PROTOCOL_DOMINANT
        flags = _build_flags(protos, by_chain, by_at, 10.0)
        self.assertIn("SINGLE_PROTOCOL_DOMINANT", flags)


# ===========================================================================
# Section 9: analyze() — top-level
# ===========================================================================
class TestAnalyze(unittest.TestCase):

    def test_empty_protocols_returns_structure(self):
        result = analyze(empty_ecosystem())
        self.assertEqual(result["by_protocol"], [])
        self.assertEqual(result["by_chain"], {})
        self.assertEqual(result["by_asset_type"], {})
        self.assertEqual(result["hhi"], 0.0)
        self.assertEqual(result["concentration_risk"], "LOW")
        self.assertIsNone(result["top_protocol"])
        self.assertIsNone(result["top_chain"])
        self.assertIsNone(result["dominant_asset_type"])
        self.assertEqual(result["flags"], [])
        self.assertEqual(result["systemic_risk_score"], 0)

    def test_required_top_level_keys(self):
        result = analyze(demo_ecosystem())
        for key in ("by_protocol", "by_chain", "by_asset_type", "hhi",
                    "concentration_risk", "top_protocol", "top_chain",
                    "dominant_asset_type", "flags", "systemic_risk_score",
                    "timestamp"):
            self.assertIn(key, result)

    def test_by_protocol_list_length(self):
        result = analyze(demo_ecosystem())
        self.assertEqual(len(result["by_protocol"]), 5)

    def test_by_protocol_keys(self):
        result = analyze(demo_ecosystem())
        required = {"name", "tvl_usd", "tvl_pct", "chain",
                    "asset_type", "concentration_label"}
        for p in result["by_protocol"]:
            self.assertEqual(set(p.keys()), required)

    def test_top_protocol_is_aave(self):
        result = analyze(demo_ecosystem())
        self.assertEqual(result["top_protocol"], "Aave V3")

    def test_top_chain_is_ethereum(self):
        result = analyze(demo_ecosystem())
        self.assertEqual(result["top_chain"], "Ethereum")

    def test_dominant_asset_type_is_stablecoin(self):
        result = analyze(demo_ecosystem())
        self.assertEqual(result["dominant_asset_type"], "STABLECOIN")

    def test_hhi_positive_for_nonempty(self):
        result = analyze(demo_ecosystem())
        self.assertGreater(result["hhi"], 0.0)

    def test_single_protocol_hhi_is_10000(self):
        eco = single_protocol_ecosystem(10_000_000.0, 10_000_000.0)
        result = analyze(eco)
        self.assertAlmostEqual(result["hhi"], 10000.0, places=4)

    def test_single_protocol_concentration_critical(self):
        eco = single_protocol_ecosystem(10_000_000.0, 10_000_000.0)
        result = analyze(eco)
        self.assertEqual(result["concentration_risk"], "CRITICAL")

    def test_systemic_risk_score_range(self):
        result = analyze(demo_ecosystem())
        self.assertGreaterEqual(result["systemic_risk_score"], 0)
        self.assertLessEqual(result["systemic_risk_score"], 100)

    def test_systemic_risk_score_single_protocol(self):
        eco = single_protocol_ecosystem(10_000_000.0, 10_000_000.0)
        result = analyze(eco)
        self.assertEqual(result["systemic_risk_score"], 100)

    def test_systemic_risk_score_formula(self):
        result = analyze(demo_ecosystem())
        expected = min(100, int(result["hhi"] / 100))
        self.assertEqual(result["systemic_risk_score"], expected)

    def test_concentration_label_dominant_present(self):
        result = analyze(demo_ecosystem())
        labels = [p["concentration_label"] for p in result["by_protocol"]]
        self.assertIn("DOMINANT", labels)  # Aave 8B/14.5B ~55%

    def test_flag_single_protocol_dominant(self):
        # Aave ~55% > 20% → flag
        result = analyze(demo_ecosystem())
        self.assertIn("SINGLE_PROTOCOL_DOMINANT", result["flags"])

    def test_flag_single_chain_dominant(self):
        # Ethereum = 14B/14.5B ~96% > 50%
        result = analyze(demo_ecosystem())
        self.assertIn("SINGLE_CHAIN_DOMINANT", result["flags"])

    def test_no_stablecoin_heavy_flag_for_demo(self):
        # Stablecoins = 12B/14.5B ~82.7% → STABLECOIN_HEAVY should be present
        result = analyze(demo_ecosystem())
        # 12B / 14.5B * 100 = 82.7% > 60 → flag IS present
        self.assertIn("STABLECOIN_HEAVY", result["flags"])

    def test_no_flags_balanced_ecosystem(self):
        eco = {
            "protocols": [
                {"name": f"P{i}", "tvl_usd": 1_000_000.0,
                 "chain": f"Chain{i}", "asset_type": "OTHER"}
                for i in range(10)
            ],
            "total_ecosystem_tvl_usd": 10_000_000.0,
        }
        result = analyze(eco)
        # Each protocol is 10%, each chain 10%, no stablecoin → no flags
        self.assertNotIn("SINGLE_PROTOCOL_DOMINANT", result["flags"])
        self.assertNotIn("SINGLE_CHAIN_DOMINANT", result["flags"])
        self.assertNotIn("STABLECOIN_HEAVY", result["flags"])

    def test_zero_total_tvl_all_pct_zero(self):
        eco = {
            "protocols": [
                {"name": "P1", "tvl_usd": 1_000_000.0,
                 "chain": "Eth", "asset_type": "STABLECOIN"},
            ],
            "total_ecosystem_tvl_usd": 0.0,
        }
        result = analyze(eco)
        self.assertEqual(result["by_protocol"][0]["tvl_pct"], 0.0)
        self.assertAlmostEqual(result["hhi"], 0.0)

    def test_timestamp_positive(self):
        result = analyze(demo_ecosystem())
        self.assertGreater(result["timestamp"], 0)

    def test_config_custom_warning_pct(self):
        # Use a lower warning pct → more protocols flagged
        eco = {
            "protocols": [
                {"name": "P1", "tvl_usd": 15_000_000.0,
                 "chain": "Eth", "asset_type": "OTHER"},
                {"name": "P2", "tvl_usd": 85_000_000.0,
                 "chain": "Eth", "asset_type": "OTHER"},
            ],
            "total_ecosystem_tvl_usd": 100_000_000.0,
        }
        result = analyze(eco, config={"concentration_warning_pct": 10.0})
        # P1=15%>10 → SINGLE_PROTOCOL_DOMINANT flag
        self.assertIn("SINGLE_PROTOCOL_DOMINANT", result["flags"])

    def test_result_serializable(self):
        result = analyze(demo_ecosystem())
        json_str = json.dumps(result)
        self.assertIsInstance(json_str, str)

    def test_by_chain_structure(self):
        result = analyze(demo_ecosystem())
        for chain, data in result["by_chain"].items():
            self.assertIn("tvl_usd", data)
            self.assertIn("tvl_pct", data)
            self.assertIn("protocol_count", data)

    def test_by_asset_type_structure(self):
        result = analyze(demo_ecosystem())
        for at, data in result["by_asset_type"].items():
            self.assertIn("tvl_usd", data)
            self.assertIn("tvl_pct", data)

    def test_hhi_range_0_to_10000(self):
        result = analyze(demo_ecosystem())
        self.assertGreaterEqual(result["hhi"], 0.0)
        self.assertLessEqual(result["hhi"], 10000.0)

    def test_concentration_risk_valid_values(self):
        result = analyze(demo_ecosystem())
        self.assertIn(result["concentration_risk"],
                      ["LOW", "MODERATE", "HIGH", "CRITICAL"])

    def test_two_equal_protocols_hhi_5000(self):
        eco = {
            "protocols": [
                {"name": "A", "tvl_usd": 50_000_000.0,
                 "chain": "Eth", "asset_type": "STABLECOIN"},
                {"name": "B", "tvl_usd": 50_000_000.0,
                 "chain": "Arb", "asset_type": "OTHER"},
            ],
            "total_ecosystem_tvl_usd": 100_000_000.0,
        }
        result = analyze(eco)
        self.assertAlmostEqual(result["hhi"], 5000.0, places=4)
        # HHI = 5000 → >= 5000 → CRITICAL
        self.assertEqual(result["concentration_risk"], "CRITICAL")

    def test_stablecoin_heavy_flag_triggered(self):
        eco = {
            "protocols": [
                {"name": "Aave", "tvl_usd": 70_000_000.0,
                 "chain": "Eth", "asset_type": "STABLECOIN"},
                {"name": "Gmx", "tvl_usd": 30_000_000.0,
                 "chain": "Arb", "asset_type": "OTHER"},
            ],
            "total_ecosystem_tvl_usd": 100_000_000.0,
        }
        result = analyze(eco)
        self.assertIn("STABLECOIN_HEAVY", result["flags"])

    def test_config_none_uses_defaults(self):
        result = analyze(demo_ecosystem(), config=None)
        self.assertIn("flags", result)

    def test_concentration_label_minor_for_small(self):
        eco = {
            "protocols": [
                {"name": "Big", "tvl_usd": 95_000_000.0,
                 "chain": "Eth", "asset_type": "STABLECOIN"},
                {"name": "Small", "tvl_usd": 5_000_000.0,
                 "chain": "Eth", "asset_type": "OTHER"},
            ],
            "total_ecosystem_tvl_usd": 100_000_000.0,
        }
        result = analyze(eco)
        small = next(p for p in result["by_protocol"] if p["name"] == "Small")
        self.assertEqual(small["concentration_label"], "MINOR")

    def test_concentration_label_significant(self):
        eco = {
            "protocols": [
                {"name": "A", "tvl_usd": 12_000_000.0,
                 "chain": "Eth", "asset_type": "OTHER"},
                {"name": "B", "tvl_usd": 88_000_000.0,
                 "chain": "Eth", "asset_type": "OTHER"},
            ],
            "total_ecosystem_tvl_usd": 100_000_000.0,
        }
        result = analyze(eco)
        a = next(p for p in result["by_protocol"] if p["name"] == "A")
        self.assertEqual(a["concentration_label"], "SIGNIFICANT")

    def test_mixed_chains_top_chain(self):
        eco = {
            "protocols": [
                {"name": "A", "tvl_usd": 10_000_000.0, "chain": "Arb",
                 "asset_type": "OTHER"},
                {"name": "B", "tvl_usd": 90_000_000.0, "chain": "Eth",
                 "asset_type": "STABLECOIN"},
            ],
            "total_ecosystem_tvl_usd": 100_000_000.0,
        }
        result = analyze(eco)
        self.assertEqual(result["top_chain"], "Eth")


# ===========================================================================
# Section 10: run_and_log()
# ===========================================================================
class TestRunAndLog(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmpdir, "tvl_concentration_log.json")

    def test_creates_file(self):
        run_and_log(demo_ecosystem(), data_file=self.log_file)
        self.assertTrue(os.path.exists(self.log_file))

    def test_file_is_valid_json(self):
        run_and_log(demo_ecosystem(), data_file=self.log_file)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_appends_entries(self):
        run_and_log(demo_ecosystem(), data_file=self.log_file)
        run_and_log(empty_ecosystem(), data_file=self.log_file)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        for _ in range(105):
            run_and_log(demo_ecosystem(), data_file=self.log_file)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_returns_result_dict(self):
        result = run_and_log(demo_ecosystem(), data_file=self.log_file)
        self.assertIn("by_protocol", result)
        self.assertIn("hhi", result)
        self.assertIn("timestamp", result)

    def test_creates_parent_dir(self):
        nested = os.path.join(self.tmpdir, "sub", "tvl_log.json")
        run_and_log(demo_ecosystem(), data_file=nested)
        self.assertTrue(os.path.exists(nested))

    def test_empty_ecosystem_logged(self):
        run_and_log(empty_ecosystem(), data_file=self.log_file)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["by_protocol"], [])

    def test_existing_corrupt_file_reset(self):
        with open(self.log_file, "w") as f:
            f.write("INVALID JSON {{")
        run_and_log(demo_ecosystem(), data_file=self.log_file)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_ring_buffer_keeps_100(self):
        for _ in range(100):
            run_and_log(demo_ecosystem(), data_file=self.log_file)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
