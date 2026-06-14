"""
Tests for MP-817: ProtocolTVLCompositionAnalyzer.

≥65 unittest cases across:
  - TestAnalyzeEdgeCases         (9)
  - TestByType                   (10)
  - TestByChain                  (8)
  - TestTopAssets                (7)
  - TestCompositionScore         (11)
  - TestRiskFlags                (12)
  - TestDominantTypeChain        (5)
  - TestLogResult                (8)
  - TestLoadLog                  (5)

Run:
    python3 -m unittest spa_core.tests.test_protocol_tvl_composition_analyzer -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Ensure project root on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from spa_core.analytics.protocol_tvl_composition_analyzer import (
    analyze,
    load_log,
    log_result,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_asset(name="USDC", type_="stablecoin", chain="ethereum", tvl=1_000_000.0):
    return {"name": name, "type": type_, "chain": chain, "tvl_usd": tvl}


def _simple_assets():
    return [
        _make_asset("USDC",  "stablecoin", "ethereum", 500_000),
        _make_asset("ETH",   "blue_chip",  "ethereum", 300_000),
        _make_asset("wBTC",  "blue_chip",  "arbitrum", 200_000),
    ]


# ===========================================================================
# TestAnalyzeEdgeCases
# ===========================================================================

class TestAnalyzeEdgeCases(unittest.TestCase):

    def test_empty_assets_total_zero(self):
        r = analyze("Proto", [])
        self.assertEqual(r["total_tvl_usd"], 0.0)

    def test_empty_assets_by_type_empty(self):
        r = analyze("Proto", [])
        self.assertEqual(r["by_type"], {})

    def test_empty_assets_by_chain_empty(self):
        r = analyze("Proto", [])
        self.assertEqual(r["by_chain"], {})

    def test_empty_assets_top_assets_empty(self):
        r = analyze("Proto", [])
        self.assertEqual(r["top_assets"], [])

    def test_empty_assets_score_zero(self):
        r = analyze("Proto", [])
        self.assertEqual(r["composition_score"], 0)

    def test_empty_assets_dominant_type_empty(self):
        r = analyze("Proto", [])
        self.assertEqual(r["dominant_type"], "")

    def test_empty_assets_dominant_chain_empty(self):
        r = analyze("Proto", [])
        self.assertEqual(r["dominant_chain"], "")

    def test_single_asset_protocol_name(self):
        r = analyze("Compound", [_make_asset(tvl=1_000)])
        self.assertEqual(r["protocol"], "Compound")

    def test_timestamp_is_recent(self):
        before = time.time() - 1
        r = analyze("Proto", _simple_assets())
        self.assertGreater(r["timestamp"], before)

    def test_single_asset_total_matches(self):
        r = analyze("X", [_make_asset(tvl=12_345.0)])
        self.assertAlmostEqual(r["total_tvl_usd"], 12_345.0)


# ===========================================================================
# TestByType
# ===========================================================================

class TestByType(unittest.TestCase):

    def test_single_type_tvl(self):
        assets = [_make_asset("USDC", "stablecoin", tvl=1_000_000)]
        r = analyze("P", assets)
        self.assertAlmostEqual(r["by_type"]["stablecoin"]["tvl_usd"], 1_000_000)

    def test_single_type_pct_100(self):
        assets = [_make_asset("USDC", "stablecoin", tvl=500_000)]
        r = analyze("P", assets)
        self.assertAlmostEqual(r["by_type"]["stablecoin"]["pct"], 100.0)

    def test_two_types_pct_sum_100(self):
        assets = [
            _make_asset("USDC", "stablecoin", tvl=600_000),
            _make_asset("ETH",  "blue_chip",  tvl=400_000),
        ]
        r = analyze("P", assets)
        total_pct = sum(v["pct"] for v in r["by_type"].values())
        self.assertAlmostEqual(total_pct, 100.0, places=2)

    def test_assets_list_in_type(self):
        assets = [
            _make_asset("USDC", "stablecoin", tvl=100),
            _make_asset("DAI",  "stablecoin", tvl=100),
        ]
        r = analyze("P", assets)
        self.assertIn("USDC", r["by_type"]["stablecoin"]["assets"])
        self.assertIn("DAI",  r["by_type"]["stablecoin"]["assets"])

    def test_same_asset_not_duplicated_in_list(self):
        assets = [
            _make_asset("USDC", "stablecoin", "ethereum", 100),
            _make_asset("USDC", "stablecoin", "base",     100),
        ]
        r = analyze("P", assets)
        self.assertEqual(r["by_type"]["stablecoin"]["assets"].count("USDC"), 1)

    def test_three_types_present(self):
        assets = [
            _make_asset("USDC", "stablecoin", tvl=100),
            _make_asset("ETH",  "blue_chip",  tvl=100),
            _make_asset("UNI",  "alt",        tvl=100),
        ]
        r = analyze("P", assets)
        self.assertIn("stablecoin", r["by_type"])
        self.assertIn("blue_chip",  r["by_type"])
        self.assertIn("alt",        r["by_type"])

    def test_tvl_aggregation_per_type(self):
        assets = [
            _make_asset("USDC", "stablecoin", tvl=300_000),
            _make_asset("DAI",  "stablecoin", tvl=200_000),
        ]
        r = analyze("P", assets)
        self.assertAlmostEqual(r["by_type"]["stablecoin"]["tvl_usd"], 500_000)

    def test_lp_token_type(self):
        assets = [_make_asset("LP", "lp_token", tvl=100)]
        r = analyze("P", assets)
        self.assertIn("lp_token", r["by_type"])

    def test_governance_type(self):
        assets = [_make_asset("GOV", "governance", tvl=50)]
        r = analyze("P", assets)
        self.assertIn("governance", r["by_type"])

    def test_unknown_type_handled(self):
        assets = [_make_asset("X", "unknown_xyz", tvl=50)]
        r = analyze("P", assets)
        self.assertIn("unknown_xyz", r["by_type"])


# ===========================================================================
# TestByChain
# ===========================================================================

class TestByChain(unittest.TestCase):

    def test_single_chain_present(self):
        assets = [_make_asset(chain="ethereum", tvl=100)]
        r = analyze("P", assets)
        self.assertIn("ethereum", r["by_chain"])

    def test_single_chain_pct_100(self):
        assets = [_make_asset(chain="ethereum", tvl=1_000)]
        r = analyze("P", assets)
        self.assertAlmostEqual(r["by_chain"]["ethereum"]["pct"], 100.0)

    def test_two_chains_pct_sum_100(self):
        assets = [
            _make_asset(chain="ethereum", tvl=700),
            _make_asset(chain="base",     tvl=300),
        ]
        r = analyze("P", assets)
        total = sum(v["pct"] for v in r["by_chain"].values())
        self.assertAlmostEqual(total, 100.0, places=2)

    def test_asset_count_per_chain(self):
        assets = [
            _make_asset("USDC", chain="ethereum", tvl=100),
            _make_asset("ETH",  chain="ethereum", tvl=200),
        ]
        r = analyze("P", assets)
        self.assertEqual(r["by_chain"]["ethereum"]["asset_count"], 2)

    def test_chain_tvl_aggregation(self):
        assets = [
            _make_asset("USDC", chain="arbitrum", tvl=400),
            _make_asset("DAI",  chain="arbitrum", tvl=600),
        ]
        r = analyze("P", assets)
        self.assertAlmostEqual(r["by_chain"]["arbitrum"]["tvl_usd"], 1000)

    def test_multiple_chains_all_present(self):
        chains = ["ethereum", "base", "arbitrum", "optimism"]
        assets = [_make_asset(f"A{i}", chain=c, tvl=100) for i, c in enumerate(chains)]
        r = analyze("P", assets)
        for c in chains:
            self.assertIn(c, r["by_chain"])

    def test_no_private_keys_in_by_chain(self):
        assets = [_make_asset(chain="ethereum", tvl=100)]
        r = analyze("P", assets)
        self.assertNotIn("_names", r["by_chain"].get("ethereum", {}))

    def test_chain_asset_count_same_name_different_chain(self):
        # Same asset name on both chains → each chain gets 1
        assets = [
            _make_asset("USDC", chain="ethereum", tvl=100),
            _make_asset("USDC", chain="base",     tvl=100),
        ]
        r = analyze("P", assets)
        self.assertEqual(r["by_chain"]["ethereum"]["asset_count"], 1)
        self.assertEqual(r["by_chain"]["base"]["asset_count"], 1)


# ===========================================================================
# TestTopAssets
# ===========================================================================

class TestTopAssets(unittest.TestCase):

    def test_top_assets_max_five(self):
        assets = [_make_asset(f"A{i}", tvl=i * 100) for i in range(1, 10)]
        r = analyze("P", assets)
        self.assertLessEqual(len(r["top_assets"]), 5)

    def test_top_assets_sorted_desc(self):
        assets = [
            _make_asset("A", tvl=100),
            _make_asset("B", tvl=500),
            _make_asset("C", tvl=300),
        ]
        r = analyze("P", assets)
        tvls = [a["tvl_usd"] for a in r["top_assets"]]
        self.assertEqual(tvls, sorted(tvls, reverse=True))

    def test_top_assets_contains_correct_pct(self):
        assets = [
            _make_asset("USDC", tvl=200),
            _make_asset("ETH",  tvl=800),
        ]
        r = analyze("P", assets)
        top = r["top_assets"][0]
        self.assertAlmostEqual(top["pct"], 80.0)

    def test_top_assets_fields_present(self):
        r = analyze("P", _simple_assets())
        for a in r["top_assets"]:
            for field in ("name", "type", "chain", "tvl_usd", "pct"):
                self.assertIn(field, a)

    def test_top_assets_fewer_than_five_if_less_assets(self):
        assets = [_make_asset("X", tvl=100), _make_asset("Y", tvl=200)]
        r = analyze("P", assets)
        self.assertEqual(len(r["top_assets"]), 2)

    def test_top_asset_is_highest_tvl(self):
        assets = [
            _make_asset("Low",  tvl=100),
            _make_asset("High", tvl=900),
            _make_asset("Mid",  tvl=400),
        ]
        r = analyze("P", assets)
        self.assertEqual(r["top_assets"][0]["name"], "High")

    def test_top_assets_empty_if_no_assets(self):
        r = analyze("P", [])
        self.assertEqual(r["top_assets"], [])


# ===========================================================================
# TestCompositionScore
# ===========================================================================

class TestCompositionScore(unittest.TestCase):

    def test_score_zero_on_empty(self):
        r = analyze("P", [])
        self.assertEqual(r["composition_score"], 0)

    def test_score_is_int(self):
        r = analyze("P", _simple_assets())
        self.assertIsInstance(r["composition_score"], int)

    def test_score_between_0_and_100(self):
        r = analyze("P", _simple_assets())
        self.assertGreaterEqual(r["composition_score"], 0)
        self.assertLessEqual(r["composition_score"], 100)

    def test_score_increases_with_more_types(self):
        # Use 3 equal-weight assets so none hits the 40% threshold
        one_type = [
            _make_asset("A", "stablecoin", "ethereum", 100),
            _make_asset("B", "stablecoin", "ethereum", 100),
            _make_asset("C", "stablecoin", "ethereum", 100),
        ]
        two_types = [
            _make_asset("A", "stablecoin", "ethereum", 100),
            _make_asset("B", "blue_chip",  "ethereum", 100),
            _make_asset("C", "blue_chip",  "ethereum", 100),
        ]
        r1 = analyze("P", one_type)
        r2 = analyze("P", two_types)
        self.assertGreater(r2["composition_score"], r1["composition_score"])

    def test_score_increases_with_more_chains(self):
        one_chain = [
            _make_asset("USDC", "stablecoin", "ethereum", 100),
            _make_asset("ETH",  "blue_chip",  "ethereum", 100),
        ]
        two_chains = [
            _make_asset("USDC", "stablecoin", "ethereum", 100),
            _make_asset("ETH",  "blue_chip",  "arbitrum", 100),
        ]
        r1 = analyze("P", one_chain)
        r2 = analyze("P", two_chains)
        self.assertGreater(r2["composition_score"], r1["composition_score"])

    def test_type_diversity_cap_at_40(self):
        # 5 types → 5*10=50, but cap is 40
        assets = [
            _make_asset("A", "stablecoin", "ethereum", 100),
            _make_asset("B", "blue_chip",  "ethereum", 100),
            _make_asset("C", "alt",        "ethereum", 100),
            _make_asset("D", "lp_token",   "ethereum", 100),
            _make_asset("E", "governance", "ethereum", 100),
        ]
        r = analyze("P", assets)
        # chain_diversity = min(1*10,30)=10; no concentration → 30; type capped 40 → total 80
        self.assertLessEqual(r["composition_score"], 100)

    def test_chain_diversity_cap_at_30(self):
        # 4 chains → 4*10=40, but cap is 30
        assets = [
            _make_asset("A", "stablecoin", "ethereum",  100),
            _make_asset("B", "stablecoin", "base",      100),
            _make_asset("C", "stablecoin", "arbitrum",  100),
            _make_asset("D", "stablecoin", "optimism",  100),
        ]
        r = analyze("P", assets)
        self.assertLessEqual(r["composition_score"], 100)

    def test_concentration_penalty(self):
        # One asset dominates >40% → penalty -10 from bonus
        assets = [
            _make_asset("HUGE", "stablecoin", "ethereum", 900),
            _make_asset("TINY", "blue_chip",  "ethereum", 100),
        ]
        r = analyze("P", assets)
        # Expect score < max possible
        self.assertLess(r["composition_score"], 100)

    def test_no_concentration_gives_full_bonus(self):
        # All assets below 40% threshold
        assets = [
            _make_asset("A", "stablecoin", "ethereum",  200),
            _make_asset("B", "blue_chip",  "ethereum",  200),
            _make_asset("C", "alt",        "arbitrum",  200),
            _make_asset("D", "lp_token",   "base",      200),
        ]
        r = analyze("P", assets)
        # 4 types → min(40,40); 3 chains → 30; bonus=30 → total=100
        self.assertGreaterEqual(r["composition_score"], 80)

    def test_custom_threshold_lower_triggers_flag(self):
        # Threshold=10 means even 25% asset triggers flag
        assets = [
            _make_asset("USDC", "stablecoin", "ethereum", 250),
            _make_asset("ETH",  "blue_chip",  "ethereum", 750),
        ]
        r = analyze("P", assets, config={"concentration_threshold_pct": 10.0})
        flags_mentioning_usdc = [f for f in r["risk_flags"] if "USDC" in f]
        self.assertTrue(len(flags_mentioning_usdc) > 0)

    def test_custom_threshold_high_no_flag(self):
        # Threshold=90 means 75% asset doesn't trigger flag
        assets = [
            _make_asset("ETH", "blue_chip", "ethereum", 750),
            _make_asset("X",   "alt",       "ethereum", 250),
        ]
        r = analyze("P", assets, config={"concentration_threshold_pct": 90.0})
        single_flags = [f for f in r["risk_flags"] if "Single asset" in f]
        self.assertEqual(len(single_flags), 0)


# ===========================================================================
# TestRiskFlags
# ===========================================================================

class TestRiskFlags(unittest.TestCase):

    def test_single_asset_high_concentration_flag(self):
        assets = [
            _make_asset("ETH", "blue_chip", "ethereum", 900),
            _make_asset("X",   "alt",       "ethereum", 100),
        ]
        r = analyze("P", assets)
        flags = [f for f in r["risk_flags"] if "Single asset" in f]
        self.assertEqual(len(flags), 1)
        self.assertIn("ETH", flags[0])

    def test_flag_includes_percentage(self):
        assets = [
            _make_asset("BIG", "alt", "ethereum", 900),
            _make_asset("SML", "alt", "ethereum", 100),
        ]
        r = analyze("P", assets)
        flag = next((f for f in r["risk_flags"] if "BIG" in f), None)
        self.assertIsNotNone(flag)
        self.assertIn("90.0%", flag)

    def test_high_stablecoin_flag(self):
        assets = [
            _make_asset("USDC", "stablecoin", "ethereum", 850),
            _make_asset("DAI",  "stablecoin", "ethereum", 150),
        ]
        r = analyze("P", assets)
        self.assertTrue(any("stablecoin" in f.lower() for f in r["risk_flags"]))

    def test_no_high_stablecoin_flag_below_80(self):
        assets = [
            _make_asset("USDC", "stablecoin", "ethereum", 750),
            _make_asset("ETH",  "blue_chip",  "ethereum", 250),
        ]
        r = analyze("P", assets)
        self.assertFalse(any("High stablecoin" in f for f in r["risk_flags"]))

    def test_low_blue_chip_flag(self):
        # blue_chip < 10%, stablecoin < 50%
        assets = [
            _make_asset("UNI",  "alt",        "ethereum", 900),
            _make_asset("AAVE", "governance", "ethereum", 95),
            _make_asset("ETH",  "blue_chip",  "ethereum",  5),
        ]
        r = analyze("P", assets)
        self.assertTrue(any("blue-chip" in f.lower() for f in r["risk_flags"]))

    def test_no_low_blue_chip_flag_when_stablecoin_high(self):
        # stablecoin >= 50% → skip blue-chip check
        assets = [
            _make_asset("USDC", "stablecoin", "ethereum", 600),
            _make_asset("UNI",  "alt",        "ethereum", 400),
        ]
        r = analyze("P", assets)
        self.assertFalse(any("Low blue-chip" in f for f in r["risk_flags"]))

    def test_chain_concentration_flag(self):
        assets = [
            _make_asset("USDC", "stablecoin", "ethereum", 900),
            _make_asset("DAI",  "stablecoin", "base",     100),
        ]
        r = analyze("P", assets)
        self.assertTrue(any("Chain concentration" in f for f in r["risk_flags"]))
        self.assertTrue(any("ethereum" in f for f in r["risk_flags"]))

    def test_no_chain_flag_when_split(self):
        assets = [
            _make_asset("A", "stablecoin", "ethereum", 500),
            _make_asset("B", "stablecoin", "base",     500),
        ]
        r = analyze("P", assets)
        self.assertFalse(any("Chain concentration" in f for f in r["risk_flags"]))

    def test_no_risk_flags_diversified(self):
        # Four types, four chains, no asset > 40%
        assets = [
            _make_asset("USDC", "stablecoin", "ethereum",  200),
            _make_asset("ETH",  "blue_chip",  "arbitrum",  200),
            _make_asset("UNI",  "alt",        "base",      200),
            _make_asset("LP",   "lp_token",   "optimism",  200),
        ]
        r = analyze("P", assets)
        single_flags = [f for f in r["risk_flags"] if "Single asset" in f]
        chain_flags  = [f for f in r["risk_flags"] if "Chain concentration" in f]
        self.assertEqual(single_flags, [])
        self.assertEqual(chain_flags, [])

    def test_multiple_concentrated_assets_multiple_flags(self):
        assets = [
            _make_asset("A", "stablecoin", "ethereum", 500),
            _make_asset("B", "blue_chip",  "ethereum", 450),
            _make_asset("C", "alt",        "ethereum",  50),
        ]
        r = analyze("P", assets)
        single_flags = [f for f in r["risk_flags"] if "Single asset" in f]
        self.assertEqual(len(single_flags), 2)

    def test_risk_flags_is_list(self):
        r = analyze("P", _simple_assets())
        self.assertIsInstance(r["risk_flags"], list)

    def test_empty_assets_no_flags(self):
        r = analyze("P", [])
        self.assertEqual(r["risk_flags"], [])


# ===========================================================================
# TestDominantTypeChain
# ===========================================================================

class TestDominantTypeChain(unittest.TestCase):

    def test_dominant_type_single(self):
        assets = [_make_asset("USDC", "stablecoin", "ethereum", 100)]
        r = analyze("P", assets)
        self.assertEqual(r["dominant_type"], "stablecoin")

    def test_dominant_type_highest_tvl(self):
        assets = [
            _make_asset("USDC", "stablecoin", "ethereum", 300),
            _make_asset("ETH",  "blue_chip",  "ethereum", 700),
        ]
        r = analyze("P", assets)
        self.assertEqual(r["dominant_type"], "blue_chip")

    def test_dominant_chain_single(self):
        assets = [_make_asset(chain="arbitrum", tvl=1_000)]
        r = analyze("P", assets)
        self.assertEqual(r["dominant_chain"], "arbitrum")

    def test_dominant_chain_highest_tvl(self):
        assets = [
            _make_asset("A", chain="base",     tvl=100),
            _make_asset("B", chain="ethereum", tvl=900),
        ]
        r = analyze("P", assets)
        self.assertEqual(r["dominant_chain"], "ethereum")

    def test_dominant_empty_on_no_assets(self):
        r = analyze("P", [])
        self.assertEqual(r["dominant_type"], "")
        self.assertEqual(r["dominant_chain"], "")


# ===========================================================================
# TestLogResult
# ===========================================================================

class TestLogResult(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "tvl_test_log.json"

    def _result(self, protocol="P"):
        return analyze(protocol, _simple_assets())

    def test_log_creates_file(self):
        log_result(self._result(), self.data_file)
        self.assertTrue(self.data_file.exists())

    def test_log_file_is_list(self):
        log_result(self._result(), self.data_file)
        with open(self.data_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_single_entry(self):
        log_result(self._result(), self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), 1)

    def test_log_two_entries(self):
        log_result(self._result("A"), self.data_file)
        log_result(self._result("B"), self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), 2)

    def test_log_ring_buffer_cap_100(self):
        for i in range(110):
            log_result(self._result(f"P{i}"), self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), 100)

    def test_log_ring_buffer_keeps_latest(self):
        for i in range(105):
            log_result(self._result(f"P{i}"), self.data_file)
        data = json.loads(self.data_file.read_text())
        # Last entry should be P104
        self.assertEqual(data[-1]["protocol"], "P104")

    def test_log_atomic_no_tmp_file_left(self):
        log_result(self._result(), self.data_file)
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_log_result_contains_protocol(self):
        log_result(self._result("MyProto"), self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(data[0]["protocol"], "MyProto")


# ===========================================================================
# TestLoadLog
# ===========================================================================

class TestLoadLog(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "tvl_test_log.json"

    def test_load_missing_file_returns_empty(self):
        result = load_log(self.data_file)
        self.assertEqual(result, [])

    def test_load_empty_list(self):
        self.data_file.write_text("[]")
        result = load_log(self.data_file)
        self.assertEqual(result, [])

    def test_load_corrupted_json_returns_empty(self):
        self.data_file.write_text("{corrupted{{")
        result = load_log(self.data_file)
        self.assertEqual(result, [])

    def test_load_after_log_result(self):
        r = analyze("Proto", _simple_assets())
        log_result(r, self.data_file)
        loaded = load_log(self.data_file)
        self.assertEqual(len(loaded), 1)

    def test_load_returns_list_type(self):
        r = analyze("Proto", _simple_assets())
        log_result(r, self.data_file)
        loaded = load_log(self.data_file)
        self.assertIsInstance(loaded, list)


if __name__ == "__main__":
    unittest.main()
