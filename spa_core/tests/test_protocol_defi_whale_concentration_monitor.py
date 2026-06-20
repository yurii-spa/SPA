"""
Tests for MP-999: ProtocolDeFiWhaleConcentrationMonitor
Run: python3 -m unittest spa_core.tests.test_protocol_defi_whale_concentration_monitor
"""

import json
import os
import unittest
import tempfile

from spa_core.analytics.protocol_defi_whale_concentration_monitor import (
    ProtocolDeFiWhaleConcentrationMonitor,
    _clamp,
    _safe_div,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_protocol(
    name="TestProtocol",
    top10_tvl_pct=40.0,
    top1_tvl_pct=8.0,
    whale_threshold_usd=1_000_000,
    whale_count=25,
    total_users=5000,
    whale_holding_days=90.0,
    retail_holding_days=30.0,
    whale_inflow=500_000,
    whale_outflow=300_000,
    governance_top10_pct=50.0,
    pol_pct=10.0,
):
    return {
        "name": name,
        "top10_wallet_tvl_pct": top10_tvl_pct,
        "top1_wallet_tvl_pct": top1_tvl_pct,
        "whale_threshold_usd": whale_threshold_usd,
        "whale_count": whale_count,
        "total_users": total_users,
        "whale_avg_holding_days": whale_holding_days,
        "retail_avg_holding_days": retail_holding_days,
        "whale_inflow_7d_usd": whale_inflow,
        "whale_outflow_7d_usd": whale_outflow,
        "governance_token_top10_pct": governance_top10_pct,
        "protocol_owned_liquidity_pct": pol_pct,
    }


class TestHelpers(unittest.TestCase):
    """T001-T010: Helper functions."""

    def test_t001_clamp_lo(self):
        self.assertEqual(_clamp(-10), 0.0)

    def test_t002_clamp_hi(self):
        self.assertEqual(_clamp(150), 100.0)

    def test_t003_clamp_mid(self):
        self.assertEqual(_clamp(55), 55.0)

    def test_t004_clamp_zero(self):
        self.assertEqual(_clamp(0), 0.0)

    def test_t005_clamp_hundred(self):
        self.assertEqual(_clamp(100), 100.0)

    def test_t006_safe_div_normal(self):
        self.assertAlmostEqual(_safe_div(9, 3), 3.0)

    def test_t007_safe_div_zero_denom(self):
        self.assertEqual(_safe_div(5, 0), 0.0)

    def test_t008_safe_div_custom_default(self):
        self.assertEqual(_safe_div(5, 0, 42.0), 42.0)

    def test_t009_safe_div_zero_numerator(self):
        self.assertEqual(_safe_div(0, 10), 0.0)

    def test_t010_safe_div_both_zero(self):
        self.assertEqual(_safe_div(0, 0), 0.0)


class TestReturnStructure(unittest.TestCase):
    """T011-T025: Return structure validation."""

    def setUp(self):
        self.m = ProtocolDeFiWhaleConcentrationMonitor()
        self.cfg = {"skip_log": True}

    def test_t011_returns_dict(self):
        r = self.m.monitor([make_protocol()], self.cfg)
        self.assertIsInstance(r, dict)

    def test_t012_has_protocols_key(self):
        r = self.m.monitor([make_protocol()], self.cfg)
        self.assertIn("protocols", r)

    def test_t013_has_aggregates_key(self):
        r = self.m.monitor([make_protocol()], self.cfg)
        self.assertIn("aggregates", r)

    def test_t014_has_timestamp(self):
        r = self.m.monitor([make_protocol()], self.cfg)
        self.assertIn("timestamp", r)

    def test_t015_has_version(self):
        r = self.m.monitor([make_protocol()], self.cfg)
        self.assertIn("version", r)

    def test_t016_module_is_mp999(self):
        r = self.m.monitor([make_protocol()], self.cfg)
        self.assertEqual(r["module"], "MP-999")

    def test_t017_protocols_is_list(self):
        r = self.m.monitor([make_protocol()], self.cfg)
        self.assertIsInstance(r["protocols"], list)

    def test_t018_protocols_count_matches_input(self):
        r = self.m.monitor([make_protocol(), make_protocol(name="P2")], self.cfg)
        self.assertEqual(len(r["protocols"]), 2)

    def test_t019_aggregates_is_dict(self):
        r = self.m.monitor([make_protocol()], self.cfg)
        self.assertIsInstance(r["aggregates"], dict)

    def test_t020_empty_protocols(self):
        r = self.m.monitor([], self.cfg)
        self.assertEqual(len(r["protocols"]), 0)

    def test_t021_empty_aggregates_total(self):
        r = self.m.monitor([], self.cfg)
        self.assertEqual(r["aggregates"]["total_protocols"], 0)

    def test_t022_single_protocol_total(self):
        r = self.m.monitor([make_protocol()], self.cfg)
        self.assertEqual(r["aggregates"]["total_protocols"], 1)

    def test_t023_timestamp_is_string(self):
        r = self.m.monitor([make_protocol()], self.cfg)
        self.assertIsInstance(r["timestamp"], str)

    def test_t024_timestamp_ends_with_z(self):
        r = self.m.monitor([make_protocol()], self.cfg)
        self.assertTrue(r["timestamp"].endswith("Z"))

    def test_t025_version_is_string(self):
        r = self.m.monitor([make_protocol()], self.cfg)
        self.assertIsInstance(r["version"], str)


class TestPerProtocolFields(unittest.TestCase):
    """T026-T042: Per-protocol fields."""

    def setUp(self):
        self.m = ProtocolDeFiWhaleConcentrationMonitor()
        self.cfg = {"skip_log": True}
        self.p = make_protocol()
        self.r = self.m.monitor([self.p], self.cfg)["protocols"][0]

    def test_t026_name_preserved(self):
        self.assertEqual(self.r["name"], "TestProtocol")

    def test_t027_top10_tvl_pct_preserved(self):
        self.assertEqual(self.r["top10_wallet_tvl_pct"], 40.0)

    def test_t028_top1_tvl_pct_preserved(self):
        self.assertEqual(self.r["top1_wallet_tvl_pct"], 8.0)

    def test_t029_whale_dominance_score_present(self):
        self.assertIn("whale_dominance_score", self.r)

    def test_t030_whale_dominance_score_in_range(self):
        s = self.r["whale_dominance_score"]
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)

    def test_t031_retail_health_score_present(self):
        self.assertIn("retail_health_score", self.r)

    def test_t032_retail_health_score_in_range(self):
        s = self.r["retail_health_score"]
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)

    def test_t033_net_whale_flow_usd_present(self):
        self.assertIn("net_whale_flow_usd", self.r)

    def test_t034_net_whale_flow_usd_value(self):
        # inflow=500k, outflow=300k → net=200k
        self.assertAlmostEqual(self.r["net_whale_flow_usd"], 200_000, places=0)

    def test_t035_whale_exit_risk_score_present(self):
        self.assertIn("whale_exit_risk_score", self.r)

    def test_t036_whale_exit_risk_score_in_range(self):
        s = self.r["whale_exit_risk_score"]
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)

    def test_t037_decentralization_score_present(self):
        self.assertIn("decentralization_score", self.r)

    def test_t038_decentralization_score_in_range(self):
        s = self.r["decentralization_score"]
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)

    def test_t039_concentration_label_present(self):
        self.assertIn("concentration_label", self.r)

    def test_t040_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_t041_pol_pct_preserved(self):
        self.assertEqual(self.r["protocol_owned_liquidity_pct"], 10.0)

    def test_t042_governance_top10_pct_preserved(self):
        self.assertEqual(self.r["governance_token_top10_pct"], 50.0)


class TestWhaleMetrics(unittest.TestCase):
    """T043-T052: Core metric calculations."""

    def setUp(self):
        self.m = ProtocolDeFiWhaleConcentrationMonitor()
        self.cfg = {"skip_log": True}

    def test_t043_whale_dominance_formula(self):
        # top10=60, top1=20, governance=70 → 60*0.4 + 20*0.3 + 70*0.3 = 24+6+21=51
        p = make_protocol(top10_tvl_pct=60, top1_tvl_pct=20, governance_top10_pct=70)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertAlmostEqual(r["whale_dominance_score"], 51.0, places=1)

    def test_t044_whale_dominance_capped_at_100(self):
        p = make_protocol(top10_tvl_pct=100, top1_tvl_pct=100, governance_top10_pct=100)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertLessEqual(r["whale_dominance_score"], 100)

    def test_t045_net_whale_flow_positive(self):
        p = make_protocol(whale_inflow=2_000_000, whale_outflow=500_000)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertAlmostEqual(r["net_whale_flow_usd"], 1_500_000, places=0)

    def test_t046_net_whale_flow_negative(self):
        p = make_protocol(whale_inflow=200_000, whale_outflow=3_000_000)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertAlmostEqual(r["net_whale_flow_usd"], -2_800_000, places=0)

    def test_t047_net_whale_flow_zero(self):
        p = make_protocol(whale_inflow=1_000_000, whale_outflow=1_000_000)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertAlmostEqual(r["net_whale_flow_usd"], 0.0, places=0)

    def test_t048_decentralization_high_when_distributed(self):
        p = make_protocol(top10_tvl_pct=10, top1_tvl_pct=2, governance_top10_pct=20, pol_pct=5)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertGreater(r["decentralization_score"], 70)

    def test_t049_decentralization_low_when_concentrated(self):
        p = make_protocol(top10_tvl_pct=90, top1_tvl_pct=40, governance_top10_pct=90)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertLess(r["decentralization_score"], 30)

    def test_t050_exit_risk_high_when_outflow_dominant(self):
        p = make_protocol(whale_inflow=100_000, whale_outflow=5_000_000,
                          top10_tvl_pct=80, governance_top10_pct=80)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertGreater(r["whale_exit_risk_score"], 30)

    def test_t051_exit_risk_low_when_inflow_dominant(self):
        p = make_protocol(whale_inflow=10_000_000, whale_outflow=100_000,
                          top10_tvl_pct=20, governance_top10_pct=20)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertLess(r["whale_exit_risk_score"], 50)

    def test_t052_zero_flow_exit_risk(self):
        p = make_protocol(whale_inflow=0, whale_outflow=0)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertGreaterEqual(r["whale_exit_risk_score"], 0)


class TestConcentrationLabels(unittest.TestCase):
    """T053-T064: Concentration label assignment."""

    def setUp(self):
        self.m = ProtocolDeFiWhaleConcentrationMonitor()
        self.cfg = {"skip_log": True}

    def _label_for(self, top10=40, top1=8, pol=10, governance=50):
        p = make_protocol(top10_tvl_pct=top10, top1_tvl_pct=top1,
                          pol_pct=pol, governance_top10_pct=governance)
        return self.m.monitor([p], self.cfg)["protocols"][0]["concentration_label"]

    def test_t053_protocol_dominated_label(self):
        self.assertEqual(self._label_for(pol=55), "PROTOCOL_DOMINATED")

    def test_t054_protocol_dominated_boundary(self):
        # POL=50 is NOT > 50
        self.assertNotEqual(self._label_for(pol=50), "PROTOCOL_DOMINATED")

    def test_t055_single_whale_risk_label(self):
        self.assertEqual(self._label_for(top1=25), "SINGLE_WHALE_RISK")

    def test_t056_single_whale_risk_boundary(self):
        # top1=20 is NOT > 20
        self.assertNotEqual(self._label_for(top1=20, pol=10), "SINGLE_WHALE_RISK")

    def test_t057_whale_heavy_label(self):
        self.assertEqual(self._label_for(top10=70, top1=15, pol=10), "WHALE_HEAVY")

    def test_t058_whale_heavy_boundary(self):
        # top10=60 is NOT > 60; top1=10 < 20; pol=10 < 50
        result = self._label_for(top10=60, top1=10, pol=10)
        # Should be AVERAGE or MODERATE based on decentralization
        self.assertNotEqual(result, "WHALE_HEAVY")

    def test_t059_well_distributed_label(self):
        # top10<30, decentralization>70 → need low dominance
        p = make_protocol(top10_tvl_pct=20, top1_tvl_pct=4, governance_top10_pct=20, pol_pct=5)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertEqual(r["concentration_label"], "WELL_DISTRIBUTED")

    def test_t060_moderate_concentration_default(self):
        # top10=40 (not <30), not whale-heavy, not single-whale, not POL-dominated
        result = self._label_for(top10=40, top1=10, pol=10)
        self.assertEqual(result, "MODERATE_CONCENTRATION")

    def test_t061_pol_priority_over_whale_heavy(self):
        # POL > 50 takes priority
        result = self._label_for(top10=80, top1=30, pol=60)
        self.assertEqual(result, "PROTOCOL_DOMINATED")

    def test_t062_single_whale_priority_over_whale_heavy(self):
        # top1>20 checked before top10>60
        result = self._label_for(top10=70, top1=25, pol=10)
        self.assertEqual(result, "SINGLE_WHALE_RISK")

    def test_t063_well_distributed_requires_both_conditions(self):
        # top10=20 but low decentralization → MODERATE
        p = make_protocol(top10_tvl_pct=20, top1_tvl_pct=10, governance_top10_pct=90, pol_pct=5)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        # With governance=90 → high dominance → low decentralization → not WELL_DISTRIBUTED
        self.assertNotEqual(r["concentration_label"], "WELL_DISTRIBUTED")

    def test_t064_all_five_labels_valid(self):
        valid_labels = {
            "WELL_DISTRIBUTED", "MODERATE_CONCENTRATION", "WHALE_HEAVY",
            "SINGLE_WHALE_RISK", "PROTOCOL_DOMINATED"
        }
        for p in [
            make_protocol(top10_tvl_pct=15, top1_tvl_pct=3, governance_top10_pct=20, pol_pct=5),
            make_protocol(top10_tvl_pct=40, top1_tvl_pct=10, pol_pct=10),
            make_protocol(top10_tvl_pct=70, top1_tvl_pct=15, pol_pct=10),
            make_protocol(top10_tvl_pct=30, top1_tvl_pct=25, pol_pct=10),
            make_protocol(pol_pct=60),
        ]:
            r = self.m.monitor([p], self.cfg)["protocols"][0]
            self.assertIn(r["concentration_label"], valid_labels)


class TestFlags(unittest.TestCase):
    """T065-T083: Flag detection."""

    def setUp(self):
        self.m = ProtocolDeFiWhaleConcentrationMonitor()
        self.cfg = {"skip_log": True}

    def test_t065_whale_exit_signal_flag(self):
        # net_flow < -1M AND outflow > inflow*2
        p = make_protocol(whale_inflow=100_000, whale_outflow=5_000_000)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertIn("WHALE_EXIT_SIGNAL", r["flags"])

    def test_t066_no_whale_exit_when_inflow_higher(self):
        p = make_protocol(whale_inflow=3_000_000, whale_outflow=500_000)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertNotIn("WHALE_EXIT_SIGNAL", r["flags"])

    def test_t067_no_whale_exit_small_outflow(self):
        # outflow>inflow*2 but net_flow > -1M
        p = make_protocol(whale_inflow=100_000, whale_outflow=300_000)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertNotIn("WHALE_EXIT_SIGNAL", r["flags"])

    def test_t068_governance_capture_risk_flag(self):
        p = make_protocol(governance_top10_pct=65)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertIn("GOVERNANCE_CAPTURE_RISK", r["flags"])

    def test_t069_no_governance_capture_at_60(self):
        # 60 is NOT > 60
        p = make_protocol(governance_top10_pct=60)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertNotIn("GOVERNANCE_CAPTURE_RISK", r["flags"])

    def test_t070_single_whale_dominant_flag(self):
        p = make_protocol(top1_tvl_pct=16)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertIn("SINGLE_WHALE_DOMINANT", r["flags"])

    def test_t071_no_single_whale_dominant_at_15(self):
        # 15 is NOT > 15
        p = make_protocol(top1_tvl_pct=15)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertNotIn("SINGLE_WHALE_DOMINANT", r["flags"])

    def test_t072_retail_exodus_flag(self):
        # retail_holding < whale_holding*0.5 AND whale_dominance > 50
        p = make_protocol(
            whale_holding_days=100, retail_holding_days=10,
            top10_tvl_pct=80, governance_top10_pct=80
        )
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertIn("RETAIL_EXODUS", r["flags"])

    def test_t073_no_retail_exodus_when_retail_holds_long(self):
        p = make_protocol(whale_holding_days=30, retail_holding_days=60)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertNotIn("RETAIL_EXODUS", r["flags"])

    def test_t074_high_pol_flag(self):
        p = make_protocol(pol_pct=35)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertIn("HIGH_POL", r["flags"])

    def test_t075_no_high_pol_at_30(self):
        # 30 is NOT > 30
        p = make_protocol(pol_pct=30)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertNotIn("HIGH_POL", r["flags"])

    def test_t076_healthy_distribution_flag(self):
        p = make_protocol(top10_tvl_pct=20)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertIn("HEALTHY_DISTRIBUTION", r["flags"])

    def test_t077_no_healthy_distribution_at_25(self):
        # 25 is NOT < 25
        p = make_protocol(top10_tvl_pct=25)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertNotIn("HEALTHY_DISTRIBUTION", r["flags"])

    def test_t078_multiple_flags_possible(self):
        p = make_protocol(
            top10_tvl_pct=20, top1_tvl_pct=16, governance_top10_pct=70,
            whale_inflow=100_000, whale_outflow=5_000_000
        )
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        # Should have SINGLE_WHALE_DOMINANT, GOVERNANCE_CAPTURE_RISK, WHALE_EXIT_SIGNAL, HEALTHY_DISTRIBUTION
        self.assertIn("SINGLE_WHALE_DOMINANT", r["flags"])
        self.assertIn("GOVERNANCE_CAPTURE_RISK", r["flags"])
        self.assertIn("WHALE_EXIT_SIGNAL", r["flags"])

    def test_t079_no_flags_moderate_protocol(self):
        # "Normal" protocol with moderate values — should have no alarming flags
        p = make_protocol(
            top10_tvl_pct=35, top1_tvl_pct=7, governance_top10_pct=50,
            whale_inflow=500_000, whale_outflow=300_000,
            whale_holding_days=60, retail_holding_days=40, pol_pct=5
        )
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertNotIn("WHALE_EXIT_SIGNAL", r["flags"])
        self.assertNotIn("GOVERNANCE_CAPTURE_RISK", r["flags"])
        self.assertNotIn("SINGLE_WHALE_DOMINANT", r["flags"])

    def test_t080_high_pol_and_whale_exit_combo(self):
        p = make_protocol(pol_pct=40, whale_inflow=0, whale_outflow=5_000_000)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertIn("HIGH_POL", r["flags"])
        self.assertIn("WHALE_EXIT_SIGNAL", r["flags"])

    def test_t081_whale_exit_requires_both_conditions(self):
        # net_flow < -1M but outflow NOT > inflow*2
        p = make_protocol(whale_inflow=4_000_000, whale_outflow=5_500_000)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        # net = -1.5M < -1M; but outflow=5.5M NOT > 4M*2=8M
        self.assertNotIn("WHALE_EXIT_SIGNAL", r["flags"])

    def test_t082_governance_capture_at_61(self):
        p = make_protocol(governance_top10_pct=61)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertIn("GOVERNANCE_CAPTURE_RISK", r["flags"])

    def test_t083_retail_exodus_dominance_threshold(self):
        # retail < whale*0.5 but dominance <= 50 → no RETAIL_EXODUS
        p = make_protocol(
            whale_holding_days=100, retail_holding_days=10,
            top10_tvl_pct=20, governance_top10_pct=10  # low dominance
        )
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        # Dominance = 20*0.4 + 10*0.3 + 10*0.3 = 8+3+3=14 < 50 → no RETAIL_EXODUS
        self.assertNotIn("RETAIL_EXODUS", r["flags"])


class TestAggregates(unittest.TestCase):
    """T084-T095: Aggregate statistics."""

    def setUp(self):
        self.m = ProtocolDeFiWhaleConcentrationMonitor()
        self.cfg = {"skip_log": True}

    def test_t084_empty_aggregates(self):
        r = self.m.monitor([], self.cfg)["aggregates"]
        self.assertIsNone(r["most_distributed"])
        self.assertIsNone(r["most_concentrated"])
        self.assertEqual(r["avg_decentralization"], 0.0)
        self.assertEqual(r["single_whale_risk_count"], 0)
        self.assertEqual(r["well_distributed_count"], 0)
        self.assertEqual(r["total_protocols"], 0)

    def test_t085_single_protocol_is_both_most_and_least(self):
        r = self.m.monitor([make_protocol(name="Solo")], self.cfg)["aggregates"]
        self.assertEqual(r["most_distributed"], "Solo")
        self.assertEqual(r["most_concentrated"], "Solo")

    def test_t086_most_distributed_identified(self):
        p1 = make_protocol(name="Open", top10_tvl_pct=10, top1_tvl_pct=2, governance_top10_pct=15)
        p2 = make_protocol(name="Closed", top10_tvl_pct=90, top1_tvl_pct=40, governance_top10_pct=90)
        r = self.m.monitor([p1, p2], self.cfg)["aggregates"]
        self.assertEqual(r["most_distributed"], "Open")

    def test_t087_most_concentrated_identified(self):
        p1 = make_protocol(name="Open", top10_tvl_pct=10, top1_tvl_pct=2, governance_top10_pct=15)
        p2 = make_protocol(name="Closed", top10_tvl_pct=90, top1_tvl_pct=40, governance_top10_pct=90)
        r = self.m.monitor([p1, p2], self.cfg)["aggregates"]
        self.assertEqual(r["most_concentrated"], "Closed")

    def test_t088_avg_decentralization(self):
        p1 = make_protocol(name="A")
        p2 = make_protocol(name="B")
        r = self.m.monitor([p1, p2], self.cfg)
        scores = [pr["decentralization_score"] for pr in r["protocols"]]
        expected = round(sum(scores) / 2, 2)
        self.assertAlmostEqual(r["aggregates"]["avg_decentralization"], expected, places=1)

    def test_t089_single_whale_risk_count(self):
        p1 = make_protocol(name="Whale", top1_tvl_pct=25)  # SINGLE_WHALE_RISK
        p2 = make_protocol(name="Normal")
        r = self.m.monitor([p1, p2], self.cfg)["aggregates"]
        self.assertGreaterEqual(r["single_whale_risk_count"], 1)

    def test_t090_well_distributed_count(self):
        p = make_protocol(name="Open", top10_tvl_pct=15, top1_tvl_pct=3, governance_top10_pct=20, pol_pct=5)
        r = self.m.monitor([p], self.cfg)["aggregates"]
        self.assertGreaterEqual(r["well_distributed_count"], 1)

    def test_t091_total_protocols_count(self):
        protocols = [make_protocol(name=f"P{i}") for i in range(7)]
        r = self.m.monitor(protocols, self.cfg)["aggregates"]
        self.assertEqual(r["total_protocols"], 7)

    def test_t092_single_whale_count_zero_when_none(self):
        p = make_protocol(top1_tvl_pct=5)
        r = self.m.monitor([p], self.cfg)["aggregates"]
        self.assertEqual(r["single_whale_risk_count"], 0)

    def test_t093_well_distributed_count_zero_when_concentrated(self):
        p = make_protocol(top10_tvl_pct=80)
        r = self.m.monitor([p], self.cfg)["aggregates"]
        self.assertEqual(r["well_distributed_count"], 0)

    def test_t094_agg_keys_present(self):
        r = self.m.monitor([make_protocol()], self.cfg)["aggregates"]
        for key in ["most_distributed", "most_concentrated", "avg_decentralization",
                    "single_whale_risk_count", "well_distributed_count", "total_protocols"]:
            self.assertIn(key, r)

    def test_t095_avg_decentralization_in_range(self):
        protocols = [make_protocol(name=f"P{i}") for i in range(5)]
        r = self.m.monitor(protocols, self.cfg)["aggregates"]
        self.assertGreaterEqual(r["avg_decentralization"], 0)
        self.assertLessEqual(r["avg_decentralization"], 100)


class TestRingBufferLog(unittest.TestCase):
    """T096-T106: Ring-buffer log and atomic write."""

    def _make_cfg(self, tmpdir, cap=100):
        return {"data_dir": tmpdir, "log_cap": cap}

    def test_t096_creates_log_file(self):
        with tempfile.TemporaryDirectory() as d:
            m = ProtocolDeFiWhaleConcentrationMonitor()
            m.monitor([make_protocol()], self._make_cfg(d))
            self.assertTrue(os.path.exists(os.path.join(d, "whale_concentration_log.json")))

    def test_t097_log_is_list(self):
        with tempfile.TemporaryDirectory() as d:
            m = ProtocolDeFiWhaleConcentrationMonitor()
            m.monitor([make_protocol()], self._make_cfg(d))
            with open(os.path.join(d, "whale_concentration_log.json")) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_t098_log_entry_has_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            m = ProtocolDeFiWhaleConcentrationMonitor()
            m.monitor([make_protocol()], self._make_cfg(d))
            with open(os.path.join(d, "whale_concentration_log.json")) as f:
                data = json.load(f)
            self.assertIn("timestamp", data[0])

    def test_t099_log_entry_has_avg_decentralization(self):
        with tempfile.TemporaryDirectory() as d:
            m = ProtocolDeFiWhaleConcentrationMonitor()
            m.monitor([make_protocol()], self._make_cfg(d))
            with open(os.path.join(d, "whale_concentration_log.json")) as f:
                data = json.load(f)
            self.assertIn("avg_decentralization", data[0])

    def test_t100_log_accumulates_entries(self):
        with tempfile.TemporaryDirectory() as d:
            m = ProtocolDeFiWhaleConcentrationMonitor()
            cfg = self._make_cfg(d)
            for _ in range(4):
                m.monitor([make_protocol()], cfg)
            with open(os.path.join(d, "whale_concentration_log.json")) as f:
                data = json.load(f)
            self.assertEqual(len(data), 4)

    def test_t101_ring_buffer_cap_enforced(self):
        with tempfile.TemporaryDirectory() as d:
            m = ProtocolDeFiWhaleConcentrationMonitor()
            cfg = self._make_cfg(d, cap=3)
            for _ in range(7):
                m.monitor([make_protocol()], cfg)
            with open(os.path.join(d, "whale_concentration_log.json")) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)

    def test_t102_skip_log_no_file(self):
        with tempfile.TemporaryDirectory() as d:
            m = ProtocolDeFiWhaleConcentrationMonitor()
            m.monitor([make_protocol()], {"data_dir": d, "skip_log": True})
            self.assertFalse(os.path.exists(os.path.join(d, "whale_concentration_log.json")))

    def test_t103_no_tmp_file_left(self):
        with tempfile.TemporaryDirectory() as d:
            m = ProtocolDeFiWhaleConcentrationMonitor()
            m.monitor([make_protocol()], self._make_cfg(d))
            self.assertFalse(
                os.path.exists(os.path.join(d, "whale_concentration_log.json.tmp"))
            )

    def test_t104_log_entry_total_protocols(self):
        with tempfile.TemporaryDirectory() as d:
            m = ProtocolDeFiWhaleConcentrationMonitor()
            m.monitor([make_protocol(), make_protocol(name="P2")], self._make_cfg(d))
            with open(os.path.join(d, "whale_concentration_log.json")) as f:
                data = json.load(f)
            self.assertEqual(data[0]["total_protocols"], 2)

    def test_t105_log_entry_whale_risk_count(self):
        with tempfile.TemporaryDirectory() as d:
            m = ProtocolDeFiWhaleConcentrationMonitor()
            p = make_protocol(top1_tvl_pct=25)  # SINGLE_WHALE_RISK
            m.monitor([p], self._make_cfg(d))
            with open(os.path.join(d, "whale_concentration_log.json")) as f:
                data = json.load(f)
            self.assertIn("single_whale_risk_count", data[0])

    def test_t106_corrupt_log_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "whale_concentration_log.json")
            with open(log_path, "w") as f:
                f.write("NOT VALID JSON {{{{")
            m = ProtocolDeFiWhaleConcentrationMonitor()
            # Should not raise; starts fresh
            m.monitor([make_protocol()], self._make_cfg(d))
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)


class TestEdgeCases(unittest.TestCase):
    """T107-T115: Edge cases and robustness."""

    def setUp(self):
        self.m = ProtocolDeFiWhaleConcentrationMonitor()
        self.cfg = {"skip_log": True}

    def test_t107_missing_name_defaults(self):
        p = {"top10_wallet_tvl_pct": 40}
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertEqual(r["name"], "unknown")

    def test_t108_all_zero_protocol(self):
        p = make_protocol(top10_tvl_pct=0, top1_tvl_pct=0,
                          whale_inflow=0, whale_outflow=0, governance_top10_pct=0)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertEqual(r["whale_dominance_score"], 0.0)
        self.assertEqual(r["net_whale_flow_usd"], 0.0)

    def test_t109_all_100_pct_concentrations(self):
        p = make_protocol(top10_tvl_pct=100, top1_tvl_pct=100,
                          governance_top10_pct=100, pol_pct=100)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertLessEqual(r["whale_dominance_score"], 100)
        self.assertLessEqual(r["decentralization_score"], 100)

    def test_t110_scores_never_negative(self):
        p = make_protocol(top10_tvl_pct=100, governance_top10_pct=100)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertGreaterEqual(r["retail_health_score"], 0)
        self.assertGreaterEqual(r["decentralization_score"], 0)

    def test_t111_scores_never_above_100(self):
        p = make_protocol(top10_tvl_pct=0, governance_top10_pct=0)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertLessEqual(r["retail_health_score"], 100)
        self.assertLessEqual(r["decentralization_score"], 100)

    def test_t112_float_inputs(self):
        p = make_protocol(top10_tvl_pct=33.33, top1_tvl_pct=6.66)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertIsNotNone(r["whale_dominance_score"])

    def test_t113_large_whale_flows(self):
        p = make_protocol(whale_inflow=1e9, whale_outflow=2e9)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertAlmostEqual(r["net_whale_flow_usd"], -1e9, delta=1)

    def test_t114_many_protocols(self):
        protocols = [make_protocol(name=f"P{i}") for i in range(20)]
        r = self.m.monitor(protocols, self.cfg)
        self.assertEqual(len(r["protocols"]), 20)
        self.assertEqual(r["aggregates"]["total_protocols"], 20)

    def test_t115_whale_count_preserved(self):
        p = make_protocol(whale_count=42)
        r = self.m.monitor([p], self.cfg)["protocols"][0]
        self.assertEqual(r["whale_count"], 42)


if __name__ == "__main__":
    unittest.main()
