"""
Tests for MP-840 ProtocolMultiChainRiskAssessor
Run: python3 -m unittest spa_core.tests.test_protocol_multi_chain_risk_assessor -v
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_multi_chain_risk_assessor import (
    analyze,
    run_and_log,
    _bridge_risk_score,
    _maturity_component,
    _fragmentation_component,
    _concentration_component,
    _risk_label,
    _fragmentation_risk_label,
    _merge_config,
    LOG_MAX,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chain(
    chain_name="Ethereum",
    tvl_usd=10_000_000.0,
    bridge_type="NONE",
    bridge_audit_score=0,
    chain_maturity_years=5.0,
    is_evm_compatible=True,
    active_incidents=0,
):
    return {
        "chain_name": chain_name,
        "tvl_usd": tvl_usd,
        "bridge_type": bridge_type,
        "bridge_audit_score": bridge_audit_score,
        "chain_maturity_years": chain_maturity_years,
        "is_evm_compatible": is_evm_compatible,
        "active_incidents": active_incidents,
    }


def _deployment(protocol="TestProto", chains=None):
    if chains is None:
        chains = [_chain()]
    return {"protocol": protocol, "chains": chains}


# ---------------------------------------------------------------------------
# _bridge_risk_score
# ---------------------------------------------------------------------------

class TestBridgeRiskScore(unittest.TestCase):
    def test_none_bridge_is_zero(self):
        self.assertEqual(_bridge_risk_score("NONE", 0, 0), 0)

    def test_native_max_no_audit(self):
        # audit_score=0 → 10 - 0 = 10
        self.assertEqual(_bridge_risk_score("NATIVE", 0, 0), 10)

    def test_native_min_full_audit(self):
        # audit_score=100 → 10 - 5 = 5
        self.assertEqual(_bridge_risk_score("NATIVE", 100, 0), 5)

    def test_native_mid_audit(self):
        # audit_score=50 → 10 - 2.5 = 7.5 → int(7) = 7
        self.assertEqual(_bridge_risk_score("NATIVE", 50, 0), 7)

    def test_canonical_max_no_audit(self):
        # audit=0 → 25 - 0 = 25
        self.assertEqual(_bridge_risk_score("CANONICAL", 0, 0), 25)

    def test_canonical_min_full_audit(self):
        # audit=100 → 25 - 15 = 10
        self.assertEqual(_bridge_risk_score("CANONICAL", 100, 0), 10)

    def test_canonical_mid_audit(self):
        # audit=50 → 25 - 7.5 = 17.5 → int(17)
        self.assertEqual(_bridge_risk_score("CANONICAL", 50, 0), 17)

    def test_third_party_max_no_audit(self):
        # audit=0 → 70 - 0 = 70
        self.assertEqual(_bridge_risk_score("THIRD_PARTY", 0, 0), 70)

    def test_third_party_min_full_audit(self):
        # audit=100 → 70 - 40 = 30
        self.assertEqual(_bridge_risk_score("THIRD_PARTY", 100, 0), 30)

    def test_third_party_mid_audit(self):
        # audit=50 → 70 - 20 = 50
        self.assertEqual(_bridge_risk_score("THIRD_PARTY", 50, 0), 50)

    def test_incidents_add_10_each(self):
        # NONE base=0, 1 incident → +10
        self.assertEqual(_bridge_risk_score("NONE", 0, 1), 10)

    def test_incidents_capped_at_20(self):
        # NONE base=0, 5 incidents → +20 (capped)
        self.assertEqual(_bridge_risk_score("NONE", 0, 5), 20)

    def test_incidents_exactly_2_gives_20(self):
        self.assertEqual(_bridge_risk_score("NONE", 0, 2), 20)

    def test_clamped_at_100(self):
        # THIRD_PARTY no audit + many incidents
        self.assertEqual(_bridge_risk_score("THIRD_PARTY", 0, 10), 90)

    def test_not_below_zero(self):
        self.assertGreaterEqual(_bridge_risk_score("NONE", 100, 0), 0)


# ---------------------------------------------------------------------------
# _maturity_component
# ---------------------------------------------------------------------------

class TestMaturityComponent(unittest.TestCase):
    def test_mature_chain_4plus_years_gives_0(self):
        self.assertEqual(_maturity_component(4.0), 0.0)

    def test_exactly_4_years_gives_0(self):
        self.assertEqual(_maturity_component(4.0), 0.0)

    def test_3_years_gives_3(self):
        self.assertEqual(_maturity_component(3.0), 3.0)

    def test_exactly_2_years_gives_3(self):
        self.assertEqual(_maturity_component(2.0), 3.0)

    def test_1_point_5_years_gives_6(self):
        self.assertEqual(_maturity_component(1.5), 6.0)

    def test_exactly_1_year_gives_6(self):
        self.assertEqual(_maturity_component(1.0), 6.0)

    def test_below_1_year_gives_10(self):
        self.assertEqual(_maturity_component(0.5), 10.0)

    def test_zero_years_gives_10(self):
        self.assertEqual(_maturity_component(0.0), 10.0)

    def test_very_mature_gives_0(self):
        self.assertEqual(_maturity_component(10.0), 0.0)


# ---------------------------------------------------------------------------
# _fragmentation_component
# ---------------------------------------------------------------------------

class TestFragmentationComponent(unittest.TestCase):
    def test_single_chain_gives_0(self):
        self.assertEqual(_fragmentation_component(1), 0.0)

    def test_two_chains_gives_10(self):
        self.assertEqual(_fragmentation_component(2), 10.0)

    def test_three_chains_gives_20(self):
        self.assertEqual(_fragmentation_component(3), 20.0)

    def test_four_chains_gives_20(self):
        self.assertEqual(_fragmentation_component(4), 20.0)

    def test_five_chains_gives_30(self):
        self.assertEqual(_fragmentation_component(5), 30.0)

    def test_ten_chains_gives_30(self):
        self.assertEqual(_fragmentation_component(10), 30.0)


# ---------------------------------------------------------------------------
# _concentration_component
# ---------------------------------------------------------------------------

class TestConcentrationComponent(unittest.TestCase):
    def test_above_90_gives_5(self):
        self.assertEqual(_concentration_component(95), 5.0)

    def test_exactly_90_gives_5(self):
        self.assertEqual(_concentration_component(90), 5.0)

    def test_80_gives_8(self):
        self.assertEqual(_concentration_component(80), 8.0)

    def test_exactly_70_gives_8(self):
        self.assertEqual(_concentration_component(70), 8.0)

    def test_60_gives_12(self):
        self.assertEqual(_concentration_component(60), 12.0)

    def test_exactly_50_gives_12(self):
        self.assertEqual(_concentration_component(50), 12.0)

    def test_below_50_gives_20(self):
        self.assertEqual(_concentration_component(40), 20.0)

    def test_zero_gives_20(self):
        self.assertEqual(_concentration_component(0), 20.0)


# ---------------------------------------------------------------------------
# _risk_label
# ---------------------------------------------------------------------------

class TestRiskLabel(unittest.TestCase):
    def test_76_is_critical(self):
        self.assertEqual(_risk_label(76), "CRITICAL")

    def test_100_is_critical(self):
        self.assertEqual(_risk_label(100), "CRITICAL")

    def test_75_is_high(self):
        self.assertEqual(_risk_label(75), "HIGH")

    def test_51_is_high(self):
        self.assertEqual(_risk_label(51), "HIGH")

    def test_50_is_moderate(self):
        self.assertEqual(_risk_label(50), "MODERATE")

    def test_26_is_moderate(self):
        self.assertEqual(_risk_label(26), "MODERATE")

    def test_25_is_low(self):
        self.assertEqual(_risk_label(25), "LOW")

    def test_zero_is_low(self):
        self.assertEqual(_risk_label(0), "LOW")


# ---------------------------------------------------------------------------
# _fragmentation_risk_label
# ---------------------------------------------------------------------------

class TestFragmentationRiskLabel(unittest.TestCase):
    def test_single_chain_is_low(self):
        self.assertEqual(_fragmentation_risk_label(1), "LOW")

    def test_two_chains_is_moderate(self):
        self.assertEqual(_fragmentation_risk_label(2), "MODERATE")

    def test_three_chains_is_moderate(self):
        self.assertEqual(_fragmentation_risk_label(3), "MODERATE")

    def test_four_chains_is_high(self):
        self.assertEqual(_fragmentation_risk_label(4), "HIGH")

    def test_five_chains_is_high(self):
        self.assertEqual(_fragmentation_risk_label(5), "HIGH")


# ---------------------------------------------------------------------------
# _merge_config
# ---------------------------------------------------------------------------

class TestMergeConfig(unittest.TestCase):
    def test_default_max_bridge_risk(self):
        cfg = _merge_config(None)
        self.assertEqual(cfg["max_bridge_risk"], 60)

    def test_custom_max_bridge_risk(self):
        cfg = _merge_config({"max_bridge_risk": 40})
        self.assertEqual(cfg["max_bridge_risk"], 40)


# ---------------------------------------------------------------------------
# analyze() — empty
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.result = analyze([])

    def test_protocols_empty(self):
        self.assertEqual(self.result["protocols"], [])

    def test_riskiest_is_none(self):
        self.assertIsNone(self.result["riskiest_protocol"])

    def test_safest_is_none(self):
        self.assertIsNone(self.result["safest_protocol"])

    def test_average_risk_zero(self):
        self.assertEqual(self.result["average_risk_score"], 0.0)

    def test_timestamp_present(self):
        self.assertIn("timestamp", self.result)


# ---------------------------------------------------------------------------
# analyze() — single chain, NONE bridge (simplest case)
# ---------------------------------------------------------------------------

class TestAnalyzeSingleChainNone(unittest.TestCase):
    def setUp(self):
        d = _deployment(
            protocol="SimpleProto",
            chains=[_chain(chain_name="Ethereum", tvl_usd=10_000_000, bridge_type="NONE",
                           chain_maturity_years=8, is_evm_compatible=True, active_incidents=0)],
        )
        self.result = analyze([d])
        self.proto = self.result["protocols"][0]

    def test_chain_count_one(self):
        self.assertEqual(self.proto["chain_count"], 1)

    def test_total_tvl(self):
        self.assertAlmostEqual(self.proto["total_tvl_usd"], 10_000_000.0)

    def test_tvl_concentration_100(self):
        self.assertAlmostEqual(self.proto["tvl_concentration"], 100.0)

    def test_bridge_risk_zero(self):
        self.assertEqual(self.proto["bridge_risk_score"], 0)

    def test_fragmentation_risk_low(self):
        self.assertEqual(self.proto["fragmentation_risk"], "LOW")

    def test_risk_score_low(self):
        # bridge=0, frag=0 (1 chain), conc=5 (100%), maturity=0 (8yrs) → 5
        self.assertEqual(self.proto["multi_chain_risk_score"], 5)

    def test_risk_label(self):
        self.assertEqual(self.proto["risk_label"], "LOW")

    def test_no_recommendations(self):
        self.assertEqual(self.proto["recommendations"], [])

    def test_chain_details_length(self):
        self.assertEqual(len(self.proto["chain_details"]), 1)

    def test_chain_detail_no_flags(self):
        self.assertEqual(self.proto["chain_details"][0]["flags"], [])

    def test_chain_tvl_pct_100(self):
        self.assertAlmostEqual(self.proto["chain_details"][0]["tvl_pct"], 100.0)


# ---------------------------------------------------------------------------
# analyze() — high risk (THIRD_PARTY, many chains, incidents)
# ---------------------------------------------------------------------------

class TestAnalyzeHighRisk(unittest.TestCase):
    def setUp(self):
        chains = [
            _chain("Ethereum", 5_000_000, "THIRD_PARTY", 0, 0.5, True, 2),
            _chain("BSC", 1_000_000, "THIRD_PARTY", 0, 0.5, True, 1),
            _chain("Solana", 1_000_000, "THIRD_PARTY", 0, 0.5, False, 1),
            _chain("Avalanche", 500_000, "THIRD_PARTY", 0, 0.5, True, 0),
            _chain("Fantom", 500_000, "THIRD_PARTY", 0, 0.5, True, 0),
        ]
        d = _deployment(protocol="RiskyProto", chains=chains)
        self.result = analyze([d])
        self.proto = self.result["protocols"][0]

    def test_chain_count_five(self):
        self.assertEqual(self.proto["chain_count"], 5)

    def test_fragmentation_risk_high(self):
        self.assertEqual(self.proto["fragmentation_risk"], "HIGH")

    def test_risk_score_high(self):
        self.assertGreater(self.proto["multi_chain_risk_score"], 50)

    def test_recommendation_consolidate(self):
        recs = self.proto["recommendations"]
        self.assertTrue(any("consolidating" in r for r in recs))

    def test_recommendation_many_chains(self):
        recs = self.proto["recommendations"]
        self.assertTrue(any("operational complexity" in r for r in recs))


# ---------------------------------------------------------------------------
# Bridge flags
# ---------------------------------------------------------------------------

class TestBridgeFlags(unittest.TestCase):
    def test_high_bridge_risk_flag(self):
        chains = [
            _chain("Ethereum", 5_000_000, "THIRD_PARTY", 0, 5.0, True, 0),
        ]
        d = _deployment(chains=chains)
        r = analyze([d])
        flags = r["protocols"][0]["chain_details"][0]["flags"]
        self.assertTrue(any("Bridge risk" in f for f in flags))

    def test_incident_flag(self):
        chains = [_chain(active_incidents=2)]
        d = _deployment(chains=chains)
        r = analyze([d])
        flags = r["protocols"][0]["chain_details"][0]["flags"]
        self.assertTrue(any("incident" in f.lower() for f in flags))

    def test_non_evm_flag(self):
        chains = [_chain(is_evm_compatible=False, bridge_type="NONE")]
        d = _deployment(chains=chains)
        r = analyze([d])
        flags = r["protocols"][0]["chain_details"][0]["flags"]
        self.assertTrue(any("Non-EVM" in f for f in flags))

    def test_no_flags_on_safe_chain(self):
        chains = [_chain("Ethereum", 10_000_000, "NONE", 0, 8.0, True, 0)]
        d = _deployment(chains=chains)
        r = analyze([d])
        flags = r["protocols"][0]["chain_details"][0]["flags"]
        self.assertEqual(flags, [])


# ---------------------------------------------------------------------------
# TVL concentration calculation
# ---------------------------------------------------------------------------

class TestTvlConcentration(unittest.TestCase):
    def test_equal_split_two_chains(self):
        chains = [
            _chain("Chain1", tvl_usd=5_000_000),
            _chain("Chain2", tvl_usd=5_000_000),
        ]
        d = _deployment(chains=chains)
        r = analyze([d])
        self.assertAlmostEqual(r["protocols"][0]["tvl_concentration"], 50.0)

    def test_dominant_single_chain(self):
        chains = [
            _chain("Main", tvl_usd=9_000_000),
            _chain("Side", tvl_usd=1_000_000),
        ]
        d = _deployment(chains=chains)
        r = analyze([d])
        self.assertAlmostEqual(r["protocols"][0]["tvl_concentration"], 90.0)

    def test_total_tvl_sum(self):
        chains = [
            _chain("A", tvl_usd=3_000_000),
            _chain("B", tvl_usd=7_000_000),
        ]
        d = _deployment(chains=chains)
        r = analyze([d])
        self.assertAlmostEqual(r["protocols"][0]["total_tvl_usd"], 10_000_000.0)


# ---------------------------------------------------------------------------
# Multiple protocols — riskiest / safest
# ---------------------------------------------------------------------------

class TestMultipleProtocols(unittest.TestCase):
    def setUp(self):
        d_safe = _deployment(
            "SafeProto",
            [_chain("ETH", 10_000_000, "NONE", 0, 8.0, True, 0)],
        )
        d_risky = _deployment(
            "RiskyProto",
            [
                _chain("C1", 5_000_000, "THIRD_PARTY", 0, 0.5, True, 2),
                _chain("C2", 5_000_000, "THIRD_PARTY", 0, 0.5, True, 2),
                _chain("C3", 5_000_000, "THIRD_PARTY", 0, 0.5, True, 2),
                _chain("C4", 5_000_000, "THIRD_PARTY", 0, 0.5, True, 2),
                _chain("C5", 5_000_000, "THIRD_PARTY", 0, 0.5, True, 2),
            ],
        )
        self.result = analyze([d_safe, d_risky])

    def test_safest_is_safe(self):
        self.assertEqual(self.result["safest_protocol"], "SafeProto")

    def test_riskiest_is_risky(self):
        self.assertEqual(self.result["riskiest_protocol"], "RiskyProto")

    def test_average_risk_between_extremes(self):
        scores = [p["multi_chain_risk_score"] for p in self.result["protocols"]]
        self.assertAlmostEqual(
            self.result["average_risk_score"],
            sum(scores) / len(scores),
            places=1,
        )

    def test_protocol_count(self):
        self.assertEqual(len(self.result["protocols"]), 2)


# ---------------------------------------------------------------------------
# run_and_log — ring buffer
# ---------------------------------------------------------------------------

class TestRunAndLog(unittest.TestCase):
    def _temp_log(self):
        d = tempfile.mkdtemp()
        return os.path.join(d, "test_multi_chain_log.json")

    def test_creates_log_file(self):
        path = self._temp_log()
        run_and_log([], data_file=path)
        self.assertTrue(os.path.exists(path))

    def test_log_is_list(self):
        path = self._temp_log()
        run_and_log([], data_file=path)
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends(self):
        path = self._temp_log()
        d = _deployment()
        run_and_log([d], data_file=path)
        run_and_log([d], data_file=path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_max(self):
        path = self._temp_log()
        d = _deployment()
        for _ in range(LOG_MAX + 5):
            run_and_log([d], data_file=path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), LOG_MAX)

    def test_entry_has_timestamp(self):
        path = self._temp_log()
        run_and_log([], data_file=path)
        with open(path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])


# ---------------------------------------------------------------------------
# Custom max_bridge_risk config
# ---------------------------------------------------------------------------

class TestCustomBridgeRisk(unittest.TestCase):
    def test_lower_threshold_triggers_flag(self):
        chains = [_chain("ETH", 10_000_000, "CANONICAL", 50, 5.0, True, 0)]
        # Default bridge_risk for CANONICAL/50 audit = 25 - 7.5 = 17.5 → 17
        # With threshold=10, 17 > 10 → flag
        d = _deployment(chains=chains)
        r = analyze([d], config={"max_bridge_risk": 10})
        flags = r["protocols"][0]["chain_details"][0]["flags"]
        self.assertTrue(any("Bridge risk" in f for f in flags))

    def test_higher_threshold_no_flag(self):
        chains = [_chain("ETH", 10_000_000, "CANONICAL", 50, 5.0, True, 0)]
        # bridge_risk=17, threshold=80 → no flag
        d = _deployment(chains=chains)
        r = analyze([d], config={"max_bridge_risk": 80})
        flags = r["protocols"][0]["chain_details"][0]["flags"]
        self.assertFalse(any("Bridge risk" in f for f in flags))

    def test_bridge_recommendation_triggered(self):
        chains = [_chain("ETH", 10_000_000, "THIRD_PARTY", 0, 5.0, True, 0)]
        # THIRD_PARTY/audit=0 → bridge_risk=70; default threshold=60
        d = _deployment(chains=chains)
        r = analyze([d])
        recs = r["protocols"][0]["recommendations"]
        self.assertTrue(any("Bridge risk elevated" in rec for rec in recs))


# ---------------------------------------------------------------------------
# Score bounds
# ---------------------------------------------------------------------------

class TestScoreBounds(unittest.TestCase):
    def test_score_not_above_100(self):
        chains = [
            _chain(f"C{i}", 1_000_000, "THIRD_PARTY", 0, 0.1, False, 5)
            for i in range(7)
        ]
        d = _deployment(chains=chains)
        r = analyze([d])
        self.assertLessEqual(r["protocols"][0]["multi_chain_risk_score"], 100)

    def test_score_not_below_zero(self):
        chains = [_chain("ETH", 10_000_000, "NONE", 100, 10.0, True, 0)]
        d = _deployment(chains=chains)
        r = analyze([d])
        self.assertGreaterEqual(r["protocols"][0]["multi_chain_risk_score"], 0)


if __name__ == "__main__":
    unittest.main()
