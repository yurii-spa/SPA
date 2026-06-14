"""
Tests for MP-875: DeFiProtocolDependencyMapper
Run: python3 -m unittest spa_core.tests.test_defi_protocol_dependency_mapper -v
"""

import json
import os
import tempfile
import time
import unittest

from spa_core.analytics.defi_protocol_dependency_mapper import (
    _admin_risk_score,
    _bridge_risk_score,
    _build_shared_dependencies,
    _contagion_level,
    _dependency_chain_score,
    _oracle_risk_score,
    _single_points_of_failure,
    analyze,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _p(**kwargs):
    """Build a minimal protocol dict with safe defaults."""
    defaults = {
        "name": "TestProtocol",
        "oracle_dependency": None,
        "underlying_protocols": [],
        "bridge_dependency": None,
        "stablecoin_dependency": "USDC",
        "tvl_usd": 100_000_000.0,
        "is_upgradeable": False,
        "multisig_signers": 0,
        "dependency_count": 0,
    }
    defaults.update(kwargs)
    return defaults


# ============================================================
# 1. _dependency_chain_score
# ============================================================

class TestDependencyChainScore(unittest.TestCase):

    def test_zero_deps(self):
        self.assertEqual(_dependency_chain_score(0), 0)

    def test_one_dep(self):
        self.assertEqual(_dependency_chain_score(1), 5)

    def test_two_deps(self):
        self.assertEqual(_dependency_chain_score(2), 10)

    def test_three_deps(self):
        self.assertEqual(_dependency_chain_score(3), 15)

    def test_four_deps(self):
        self.assertEqual(_dependency_chain_score(4), 15)

    def test_five_deps(self):
        self.assertEqual(_dependency_chain_score(5), 20)

    def test_six_deps(self):
        self.assertEqual(_dependency_chain_score(6), 20)

    def test_seven_deps(self):
        self.assertEqual(_dependency_chain_score(7), 25)

    def test_eight_deps(self):
        self.assertEqual(_dependency_chain_score(8), 25)

    def test_ten_deps(self):
        self.assertEqual(_dependency_chain_score(10), 30)

    def test_large_deps(self):
        self.assertEqual(_dependency_chain_score(100), 30)

    def test_nine_deps(self):
        self.assertEqual(_dependency_chain_score(9), 25)


# ============================================================
# 2. _oracle_risk_score
# ============================================================

class TestOracleRiskScore(unittest.TestCase):

    def test_no_oracle(self):
        self.assertEqual(_oracle_risk_score(None, []), 5)

    def test_chainlink(self):
        self.assertEqual(_oracle_risk_score("Chainlink", []), 8)

    def test_twap_uniswap(self):
        self.assertEqual(_oracle_risk_score("Uniswap-TWAP", []), 12)

    def test_twap_lowercase(self):
        # Case: "twap" in lower -> 12
        self.assertEqual(_oracle_risk_score("SomeTWAP-Oracle", []), 12)

    def test_pyth(self):
        self.assertEqual(_oracle_risk_score("Pyth", []), 10)

    def test_unknown_oracle(self):
        self.assertEqual(_oracle_risk_score("OscillatorOracle", []), 20)

    def test_chainlink_self_referential(self):
        # oracle is "Chainlink", underlying contains "Chainlink" → 8+5=13
        self.assertEqual(_oracle_risk_score("Chainlink", ["Chainlink"]), 13)

    def test_twap_self_referential(self):
        # twap=12, self-ref → 17
        self.assertEqual(_oracle_risk_score("Uniswap-TWAP", ["Uniswap-TWAP"]), 17)

    def test_pyth_self_referential(self):
        self.assertEqual(_oracle_risk_score("Pyth", ["Pyth"]), 15)

    def test_unknown_oracle_cap(self):
        # unknown=20, self-ref→25 (cap)
        self.assertEqual(_oracle_risk_score("ObscureX", ["ObscureX"]), 25)

    def test_no_oracle_no_self_ref_underlying(self):
        # None → 5, no self-ref bonus
        self.assertEqual(_oracle_risk_score(None, ["Aave"]), 5)

    def test_chainlink_not_in_underlying(self):
        # "Chainlink" not in underlying list → no +5
        self.assertEqual(_oracle_risk_score("Chainlink", ["Aave", "Uniswap"]), 8)

    def test_oracle_case_insensitive_self_ref(self):
        # oracle "uniswap-twap" vs underlying "uniswap-twap" — same lowercase
        score = _oracle_risk_score("uniswap-twap", ["uniswap-twap"])
        self.assertEqual(score, 17)  # 12 + 5

    def test_cap_at_25(self):
        score = _oracle_risk_score("Unknown", ["Unknown"])
        self.assertLessEqual(score, 25)


# ============================================================
# 3. _admin_risk_score
# ============================================================

class TestAdminRiskScore(unittest.TestCase):

    def test_not_upgradeable(self):
        self.assertEqual(_admin_risk_score(False, 0), 5)

    def test_not_upgradeable_with_multisig(self):
        self.assertEqual(_admin_risk_score(False, 7), 5)

    def test_upgradeable_7_signers(self):
        self.assertEqual(_admin_risk_score(True, 7), 8)

    def test_upgradeable_10_signers(self):
        self.assertEqual(_admin_risk_score(True, 10), 8)

    def test_upgradeable_5_signers(self):
        self.assertEqual(_admin_risk_score(True, 5), 12)

    def test_upgradeable_6_signers(self):
        self.assertEqual(_admin_risk_score(True, 6), 12)

    def test_upgradeable_3_signers(self):
        self.assertEqual(_admin_risk_score(True, 3), 16)

    def test_upgradeable_4_signers(self):
        self.assertEqual(_admin_risk_score(True, 4), 16)

    def test_upgradeable_2_signers(self):
        self.assertEqual(_admin_risk_score(True, 2), 20)

    def test_upgradeable_1_signer(self):
        self.assertEqual(_admin_risk_score(True, 1), 23)

    def test_upgradeable_0_signers(self):
        self.assertEqual(_admin_risk_score(True, 0), 25)


# ============================================================
# 4. _bridge_risk_score
# ============================================================

class TestBridgeRiskScore(unittest.TestCase):

    def test_no_bridge(self):
        self.assertEqual(_bridge_risk_score(None, 0), 0)

    def test_no_bridge_high_tvl(self):
        self.assertEqual(_bridge_risk_score(None, 50_000_000), 0)

    def test_native_bridge_low_tvl(self):
        # "native" → base=5; tvl=1M ≤ 10M → no +5 extra
        self.assertEqual(_bridge_risk_score("NativeBridge", 1_000_000), 5)

    def test_native_bridge_high_tvl(self):
        # "native" → 5 + 5 = 10  (tvl=50M > 10M)
        self.assertEqual(_bridge_risk_score("NativeBridge", 50_000_000), 10)

    def test_native_case_insensitive(self):
        self.assertEqual(_bridge_risk_score("NATIVE-L1", 50_000_000), 10)

    def test_official_bridge_low_tvl(self):
        # official → base=8; tvl=1M ≤ 10M → no +5 extra
        self.assertEqual(_bridge_risk_score("OfficialBridge", 1_000_000), 8)

    def test_official_bridge_high_tvl(self):
        # official → 8 + 5 = 13  (tvl=50M > 10M)
        self.assertEqual(_bridge_risk_score("OfficialBridge", 50_000_000), 13)

    def test_official_case_insensitive(self):
        self.assertEqual(_bridge_risk_score("OFFICIAL-XYZ", 50_000_000), 13)

    def test_third_party_bridge_low_tvl(self):
        # third-party: base=15; tvl=1M ≤ 10M → no +5
        self.assertEqual(_bridge_risk_score("Wormhole", 1_000_000), 15)

    def test_third_party_bridge_high_tvl(self):
        # 15 + 5 = 20 (cap); tvl=50M > 10M
        self.assertEqual(_bridge_risk_score("Wormhole", 50_000_000), 20)

    def test_cap_at_20(self):
        score = _bridge_risk_score("SomeRiskyBridge", 100_000_000)
        self.assertLessEqual(score, 20)


# ============================================================
# 5. _contagion_level
# ============================================================

class TestContagionLevel(unittest.TestCase):

    def test_low_boundary(self):
        self.assertEqual(_contagion_level(0), "LOW")

    def test_low_29(self):
        self.assertEqual(_contagion_level(29), "LOW")

    def test_moderate_30(self):
        self.assertEqual(_contagion_level(30), "MODERATE")

    def test_moderate_49(self):
        self.assertEqual(_contagion_level(49), "MODERATE")

    def test_high_50(self):
        self.assertEqual(_contagion_level(50), "HIGH")

    def test_high_69(self):
        self.assertEqual(_contagion_level(69), "HIGH")

    def test_critical_70(self):
        self.assertEqual(_contagion_level(70), "CRITICAL")

    def test_critical_100(self):
        self.assertEqual(_contagion_level(100), "CRITICAL")


# ============================================================
# 6. _single_points_of_failure
# ============================================================

class TestSinglePointsOfFailure(unittest.TestCase):

    def test_no_spofs(self):
        spofs = _single_points_of_failure(
            bridge_dependency=None, bridge_score=0,
            multisig_signers=5, is_upgradeable=True,
            oracle_dependency="Chainlink", oracle_score=8,
            underlying_protocols=["Aave"],
        )
        self.assertEqual(spofs, [])

    def test_bridge_spof(self):
        spofs = _single_points_of_failure(
            bridge_dependency="Wormhole", bridge_score=20,
            multisig_signers=5, is_upgradeable=True,
            oracle_dependency=None, oracle_score=5,
            underlying_protocols=[],
        )
        self.assertIn("Bridge: Wormhole", spofs)

    def test_bridge_score_14_no_spof(self):
        spofs = _single_points_of_failure(
            bridge_dependency="SafeBridge", bridge_score=14,
            multisig_signers=5, is_upgradeable=True,
            oracle_dependency=None, oracle_score=5,
            underlying_protocols=[],
        )
        self.assertNotIn("Bridge: SafeBridge", spofs)

    def test_single_admin_key_spof(self):
        spofs = _single_points_of_failure(
            bridge_dependency=None, bridge_score=0,
            multisig_signers=1, is_upgradeable=True,
            oracle_dependency=None, oracle_score=5,
            underlying_protocols=[],
        )
        self.assertIn("Single admin key (upgrade risk)", spofs)

    def test_single_admin_key_not_upgradeable(self):
        spofs = _single_points_of_failure(
            bridge_dependency=None, bridge_score=0,
            multisig_signers=0, is_upgradeable=False,
            oracle_dependency=None, oracle_score=5,
            underlying_protocols=[],
        )
        self.assertNotIn("Single admin key (upgrade risk)", spofs)

    def test_oracle_spof(self):
        spofs = _single_points_of_failure(
            bridge_dependency=None, bridge_score=0,
            multisig_signers=5, is_upgradeable=True,
            oracle_dependency="ObscureX", oracle_score=20,
            underlying_protocols=[],
        )
        self.assertIn("Oracle: ObscureX", spofs)

    def test_oracle_score_17_no_spof(self):
        spofs = _single_points_of_failure(
            bridge_dependency=None, bridge_score=0,
            multisig_signers=5, is_upgradeable=True,
            oracle_dependency="Pyth", oracle_score=17,
            underlying_protocols=[],
        )
        self.assertNotIn("Oracle: Pyth", spofs)

    def test_many_underlying_spof(self):
        spofs = _single_points_of_failure(
            bridge_dependency=None, bridge_score=0,
            multisig_signers=5, is_upgradeable=True,
            oracle_dependency=None, oracle_score=5,
            underlying_protocols=["A", "B", "C", "D", "E"],
        )
        self.assertIn("5 underlying protocol dependencies", spofs)

    def test_four_underlying_no_spof(self):
        spofs = _single_points_of_failure(
            bridge_dependency=None, bridge_score=0,
            multisig_signers=5, is_upgradeable=True,
            oracle_dependency=None, oracle_score=5,
            underlying_protocols=["A", "B", "C", "D"],
        )
        self.assertNotIn("4 underlying protocol dependencies", spofs)

    def test_multisig_zero_upgradeable(self):
        spofs = _single_points_of_failure(
            bridge_dependency=None, bridge_score=0,
            multisig_signers=0, is_upgradeable=True,
            oracle_dependency=None, oracle_score=5,
            underlying_protocols=[],
        )
        self.assertIn("Single admin key (upgrade risk)", spofs)

    def test_all_spofs(self):
        spofs = _single_points_of_failure(
            bridge_dependency="Wormhole", bridge_score=20,
            multisig_signers=0, is_upgradeable=True,
            oracle_dependency="WeirdOracle", oracle_score=25,
            underlying_protocols=["A", "B", "C", "D", "E", "F"],
        )
        self.assertEqual(len(spofs), 4)


# ============================================================
# 7. _build_shared_dependencies
# ============================================================

class TestBuildSharedDependencies(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(_build_shared_dependencies([]), {})

    def test_single_protocol(self):
        protocols = [_p(name="A", oracle_dependency="Chainlink",
                        underlying_protocols=["Uniswap"])]
        self.assertEqual(_build_shared_dependencies(protocols), {})

    def test_shared_oracle(self):
        protocols = [
            _p(name="A", oracle_dependency="Chainlink"),
            _p(name="B", oracle_dependency="Chainlink"),
        ]
        result = _build_shared_dependencies(protocols)
        self.assertIn("Chainlink", result)
        self.assertIn("A", result["Chainlink"])
        self.assertIn("B", result["Chainlink"])

    def test_shared_bridge(self):
        protocols = [
            _p(name="A", bridge_dependency="Wormhole"),
            _p(name="B", bridge_dependency="Wormhole"),
        ]
        result = _build_shared_dependencies(protocols)
        self.assertIn("Wormhole", result)

    def test_shared_underlying(self):
        protocols = [
            _p(name="A", underlying_protocols=["Aave"]),
            _p(name="B", underlying_protocols=["Aave"]),
        ]
        result = _build_shared_dependencies(protocols)
        self.assertIn("Aave", result)

    def test_not_shared(self):
        protocols = [
            _p(name="A", oracle_dependency="Chainlink"),
            _p(name="B", oracle_dependency="Pyth"),
        ]
        result = _build_shared_dependencies(protocols)
        self.assertNotIn("Chainlink", result)
        self.assertNotIn("Pyth", result)

    def test_multiple_shared(self):
        protocols = [
            _p(name="A", oracle_dependency="Chainlink", underlying_protocols=["Uniswap"]),
            _p(name="B", oracle_dependency="Chainlink", underlying_protocols=["Uniswap"]),
        ]
        result = _build_shared_dependencies(protocols)
        self.assertIn("Chainlink", result)
        self.assertIn("Uniswap", result)

    def test_deduplication_same_protocol(self):
        # Protocol A lists same underlying twice — should not appear twice in list
        protocols = [
            _p(name="A", underlying_protocols=["Uniswap", "Uniswap"]),
            _p(name="B", underlying_protocols=["Uniswap"]),
        ]
        result = _build_shared_dependencies(protocols)
        self.assertIn("Uniswap", result)
        # A should appear only once
        self.assertEqual(result["Uniswap"].count("A"), 1)


# ============================================================
# 8. analyze() — core behavior
# ============================================================

class TestAnalyzeEmpty(unittest.TestCase):

    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        for f in [self.tmp_log, self.tmp_log + ".tmp"]:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass

    def test_empty_protocols(self):
        result = analyze([], log_path=self.tmp_log)
        self.assertEqual(result["protocols"], [])
        self.assertIsNone(result["highest_contagion_risk"])
        self.assertIsNone(result["lowest_contagion_risk"])
        self.assertEqual(result["shared_dependencies"], {})
        self.assertEqual(result["average_contagion_score"], 0.0)
        self.assertIn("timestamp", result)


class TestAnalyzeSingle(unittest.TestCase):

    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        for f in [self.tmp_log, self.tmp_log + ".tmp"]:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass

    def test_single_immutable_protocol(self):
        p = _p(name="SimpleProtocol", oracle_dependency="Chainlink",
               dependency_count=2)
        result = analyze([p], log_path=self.tmp_log)
        self.assertEqual(len(result["protocols"]), 1)
        self.assertEqual(result["highest_contagion_risk"], "SimpleProtocol")
        self.assertEqual(result["lowest_contagion_risk"], "SimpleProtocol")
        scored = result["protocols"][0]
        # chain=10, oracle=8, admin=5(not upgradeable), bridge=0 → 23 → LOW
        self.assertEqual(scored["contagion_risk_level"], "LOW")
        self.assertEqual(scored["contagion_risk_score"], 23)

    def test_single_high_risk_protocol(self):
        p = _p(name="DangerProtocol",
               oracle_dependency="ObscureOracle",
               bridge_dependency="WeirdBridge",
               is_upgradeable=True,
               multisig_signers=0,
               dependency_count=10,
               tvl_usd=50_000_000)
        result = analyze([p], log_path=self.tmp_log)
        scored = result["protocols"][0]
        # chain=30, oracle=20, admin=25, bridge=min(20,20)=20 → min(100,95)=95
        self.assertEqual(scored["contagion_risk_score"], 95)
        self.assertEqual(scored["contagion_risk_level"], "CRITICAL")

    def test_summary_format(self):
        p = _p(name="Aave", dependency_count=2)
        result = analyze([p], log_path=self.tmp_log)
        summary = result["protocols"][0]["summary"]
        self.assertIn("Aave", summary)
        self.assertIn("contagion risk", summary)
        self.assertIn("deps", summary)
        self.assertIn("SPOFs", summary)


class TestAnalyzeMultiple(unittest.TestCase):

    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")
        self.protocols = [
            _p(name="Low", oracle_dependency=None, dependency_count=0,
               is_upgradeable=False),
            _p(name="High", oracle_dependency="ObscureX", is_upgradeable=True,
               multisig_signers=0, dependency_count=10, tvl_usd=50_000_000,
               bridge_dependency="ThirdPartyBridge"),
            _p(name="Mid", oracle_dependency="Chainlink", is_upgradeable=True,
               multisig_signers=5, dependency_count=3),
        ]

    def tearDown(self):
        for f in [self.tmp_log, self.tmp_log + ".tmp"]:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass

    def test_highest_contagion(self):
        result = analyze(self.protocols, log_path=self.tmp_log)
        self.assertEqual(result["highest_contagion_risk"], "High")

    def test_lowest_contagion(self):
        result = analyze(self.protocols, log_path=self.tmp_log)
        self.assertEqual(result["lowest_contagion_risk"], "Low")

    def test_average_score(self):
        result = analyze(self.protocols, log_path=self.tmp_log)
        scores = [p["contagion_risk_score"] for p in result["protocols"]]
        expected_avg = sum(scores) / len(scores)
        self.assertAlmostEqual(result["average_contagion_score"], expected_avg, places=5)

    def test_protocol_count(self):
        result = analyze(self.protocols, log_path=self.tmp_log)
        self.assertEqual(len(result["protocols"]), 3)

    def test_shared_deps_chainlink(self):
        protocols = [
            _p(name="A", oracle_dependency="Chainlink"),
            _p(name="B", oracle_dependency="Chainlink"),
            _p(name="C", oracle_dependency="Pyth"),
        ]
        result = analyze(protocols, log_path=self.tmp_log)
        self.assertIn("Chainlink", result["shared_dependencies"])
        self.assertNotIn("Pyth", result["shared_dependencies"])

    def test_score_capped_at_100(self):
        protocols = [
            _p(name="X", oracle_dependency="Strange",
               is_upgradeable=True, multisig_signers=0,
               dependency_count=15, bridge_dependency="FlyByNight",
               tvl_usd=50_000_000),
        ]
        result = analyze(protocols, log_path=self.tmp_log)
        self.assertLessEqual(result["protocols"][0]["contagion_risk_score"], 100)

    def test_timestamp_present(self):
        result = analyze(self.protocols, log_path=self.tmp_log)
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)

    def test_spofs_field_present(self):
        result = analyze(self.protocols, log_path=self.tmp_log)
        for p in result["protocols"]:
            self.assertIn("single_points_of_failure", p)
            self.assertIsInstance(p["single_points_of_failure"], list)

    def test_all_score_fields_present(self):
        result = analyze(self.protocols, log_path=self.tmp_log)
        for p in result["protocols"]:
            for field in ["dependency_chain_score", "oracle_risk_score",
                          "admin_risk_score", "bridge_risk_score",
                          "contagion_risk_score", "contagion_risk_level",
                          "total_dependencies", "summary"]:
                self.assertIn(field, p, f"Missing field: {field}")


# ============================================================
# 9. Log ring-buffer tests
# ============================================================

class TestLogRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        for f in [self.tmp_log, self.tmp_log + ".tmp"]:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass

    def test_log_created(self):
        analyze([_p(name="A")], log_path=self.tmp_log)
        self.assertTrue(os.path.exists(self.tmp_log))

    def test_log_is_valid_json(self):
        analyze([_p(name="A")], log_path=self.tmp_log)
        with open(self.tmp_log) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends(self):
        analyze([_p(name="A")], log_path=self.tmp_log)
        analyze([_p(name="B")], log_path=self.tmp_log)
        with open(self.tmp_log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_ring_buffer_cap(self):
        for i in range(110):
            analyze([_p(name=f"P{i}")], log_path=self.tmp_log)
        with open(self.tmp_log) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_entry_fields(self):
        analyze([_p(name="A")], log_path=self.tmp_log)
        with open(self.tmp_log) as f:
            data = json.load(f)
        entry = data[0]
        self.assertIn("timestamp", entry)
        self.assertIn("protocol_count", entry)
        self.assertIn("average_contagion_score", entry)

    def test_log_empty_result(self):
        analyze([], log_path=self.tmp_log)
        with open(self.tmp_log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["protocol_count"], 0)


# ============================================================
# 10. Edge cases & integration
# ============================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        for f in [self.tmp_log, self.tmp_log + ".tmp"]:
            try:
                os.remove(f)
            except FileNotFoundError:
                pass

    def test_no_oracle_not_upgradeable_no_bridge_no_deps(self):
        p = _p(name="Minimal", dependency_count=0, is_upgradeable=False)
        result = analyze([p], log_path=self.tmp_log)
        scored = result["protocols"][0]
        # chain=0, oracle=5, admin=5, bridge=0 → 10 → LOW
        self.assertEqual(scored["contagion_risk_score"], 10)
        self.assertEqual(scored["contagion_risk_level"], "LOW")

    def test_critical_risk_protocol(self):
        p = _p(name="Danger",
               oracle_dependency="WeirdOracle",
               underlying_protocols=["WeirdOracle"],  # self-referential
               bridge_dependency="FlyByNightBridge",
               is_upgradeable=True,
               multisig_signers=0,
               dependency_count=10,
               tvl_usd=100_000_000)
        result = analyze([p], log_path=self.tmp_log)
        scored = result["protocols"][0]
        self.assertEqual(scored["contagion_risk_level"], "CRITICAL")

    def test_native_bridge_low_tvl_score(self):
        p = _p(name="NativeUser",
               bridge_dependency="NativeBridge",
               tvl_usd=5_000_000,
               is_upgradeable=False,
               dependency_count=0)
        result = analyze([p], log_path=self.tmp_log)
        scored = result["protocols"][0]
        # bridge: native(5) + tvl<=10M? tvl=5M ≤ 10M → no +5 → bridge=5? wait no:
        # bridge_risk_score adds +5 if tvl > 10_000_000. 5M is NOT > 10M, so base=5, no extra
        # Actually: "native" → base=5; tvl=5M is NOT > 10M → bridge=5
        # Wait, re-reading spec: "+5 if bridge is the only cross-chain connection AND tvl > 10M"
        # 5M < 10M → no extra → bridge_score=5
        # chain=0, oracle=5, admin=5, bridge=5 → total=15 → LOW
        self.assertEqual(scored["bridge_risk_score"], 5)

    def test_official_bridge_high_tvl_score(self):
        p = _p(name="OfficialUser",
               bridge_dependency="OfficialBridge",
               tvl_usd=50_000_000,
               is_upgradeable=False,
               dependency_count=0)
        result = analyze([p], log_path=self.tmp_log)
        scored = result["protocols"][0]
        # official → 8 + 5 = 13 (tvl=50M > 10M)
        self.assertEqual(scored["bridge_risk_score"], 13)

    def test_total_dependencies_field(self):
        p = _p(name="P", dependency_count=7)
        result = analyze([p], log_path=self.tmp_log)
        self.assertEqual(result["protocols"][0]["total_dependencies"], 7)

    def test_config_none_works(self):
        # config=None should not crash
        result = analyze([_p(name="A")], config=None, log_path=self.tmp_log)
        self.assertEqual(len(result["protocols"]), 1)

    def test_config_dict_works(self):
        result = analyze([_p(name="A")], config={}, log_path=self.tmp_log)
        self.assertEqual(len(result["protocols"]), 1)

    def test_shared_deps_empty_when_single(self):
        result = analyze([_p(name="Solo", oracle_dependency="Chainlink",
                             bridge_dependency="Wormhole")],
                         log_path=self.tmp_log)
        self.assertEqual(result["shared_dependencies"], {})

    def test_three_protocols_shared_oracle(self):
        protocols = [
            _p(name="X", oracle_dependency="Chainlink"),
            _p(name="Y", oracle_dependency="Chainlink"),
            _p(name="Z", oracle_dependency="Chainlink"),
        ]
        result = analyze(protocols, log_path=self.tmp_log)
        self.assertEqual(len(result["shared_dependencies"]["Chainlink"]), 3)

    def test_spofs_empty_list_when_none(self):
        p = _p(name="Safe",
               oracle_dependency="Chainlink",
               bridge_dependency=None,
               is_upgradeable=True,
               multisig_signers=7,
               dependency_count=1,
               underlying_protocols=["Aave"])
        result = analyze([p], log_path=self.tmp_log)
        self.assertEqual(result["protocols"][0]["single_points_of_failure"], [])

    def test_bridge_risk_score_capped(self):
        # Force a scenario that would exceed 20 without cap
        score = _bridge_risk_score("FlyByNight", 100_000_000_000)
        self.assertLessEqual(score, 20)

    def test_all_four_sub_scores_summed(self):
        p = _p(name="P",
               oracle_dependency="Chainlink",
               is_upgradeable=True,
               multisig_signers=5,
               dependency_count=3,
               bridge_dependency=None)
        result = analyze([p], log_path=self.tmp_log)
        scored = result["protocols"][0]
        expected = min(100,
                       scored["dependency_chain_score"] +
                       scored["oracle_risk_score"] +
                       scored["admin_risk_score"] +
                       scored["bridge_risk_score"])
        self.assertEqual(scored["contagion_risk_score"], expected)

    def test_moderate_level(self):
        # Force score around 35 → MODERATE
        p = _p(name="M",
               oracle_dependency="Chainlink",  # 8
               is_upgradeable=True,
               multisig_signers=5,            # 12
               dependency_count=2,            # 10
               bridge_dependency=None)        # 0  → total=30 → MODERATE
        result = analyze([p], log_path=self.tmp_log)
        self.assertEqual(result["protocols"][0]["contagion_risk_level"], "MODERATE")

    def test_high_level(self):
        p = _p(name="H",
               oracle_dependency="Chainlink",  # 8
               is_upgradeable=True,
               multisig_signers=2,            # 20
               dependency_count=5,            # 20
               bridge_dependency=None)        # 0  → total=53 (5+8+20+20... wait)
        # chain=20, oracle=8, admin=20, bridge=0 → 48? Let me recalc:
        # dep=5 → chain=20
        # oracle=Chainlink → 8
        # upgradeable, signers=2 → 20
        # bridge=None → 0
        # total = 48 → still < 50, MODERATE
        # Let me try dep=7 → chain=25: 25+8+20+0=53 → HIGH
        p2 = _p(name="H2",
                oracle_dependency="Chainlink",
                is_upgradeable=True,
                multisig_signers=2,
                dependency_count=7,
                bridge_dependency=None)
        result = analyze([p2], log_path=self.tmp_log)
        self.assertEqual(result["protocols"][0]["contagion_risk_level"], "HIGH")


if __name__ == "__main__":
    unittest.main()
