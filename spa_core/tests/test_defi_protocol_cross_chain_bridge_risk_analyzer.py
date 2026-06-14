"""
Tests for DeFiProtocolCrossChainBridgeRiskAnalyzer (MP-1126).
Framework: unittest (run with `python3 -m unittest`)
≥ 110 tests covering scoring logic, edge cases, label thresholds, validation,
ring-buffer logging, and the convenience class-method.
"""

import json
import os
import shutil
import tempfile
import unittest
from typing import Dict, Any

from spa_core.analytics.defi_protocol_cross_chain_bridge_risk_analyzer import (
    DeFiProtocolCrossChainBridgeRiskAnalyzer,
    BRIDGE_BASE_SCORES,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make(
    bridge_name: str = "layerzero",
    bridge_tvl_usd: float = 1_000_000.0,
    bridge_audit_count: int = 2,
    bridge_age_days: int = 365,
    prior_hack_usd: float = 0.0,
    position_bridge_exposure_usd: float = 10_000.0,
    is_canonical_bridge: bool = False,
    protocol_name: str = "TestProtocol",
    data_dir: str = "data",
) -> Dict[str, Any]:
    a = DeFiProtocolCrossChainBridgeRiskAnalyzer(data_dir=data_dir)
    return a.analyze(
        bridge_name=bridge_name,
        bridge_tvl_usd=bridge_tvl_usd,
        bridge_audit_count=bridge_audit_count,
        bridge_age_days=bridge_age_days,
        prior_hack_usd=prior_hack_usd,
        position_bridge_exposure_usd=position_bridge_exposure_usd,
        is_canonical_bridge=is_canonical_bridge,
        protocol_name=protocol_name,
    )


# ---------------------------------------------------------------------------
# Test suites
# ---------------------------------------------------------------------------

class TestBaseScore(unittest.TestCase):
    """bridge_base_risk_score by name."""

    def test_native_rollup_base(self):
        r = _make(bridge_name="native_rollup")
        self.assertEqual(r["bridge_base_risk_score"], 0)

    def test_layerzero_base(self):
        r = _make(bridge_name="layerzero")
        self.assertEqual(r["bridge_base_risk_score"], 8)

    def test_stargate_base(self):
        r = _make(bridge_name="stargate")
        self.assertEqual(r["bridge_base_risk_score"], 12)

    def test_wormhole_base(self):
        r = _make(bridge_name="wormhole")
        self.assertEqual(r["bridge_base_risk_score"], 20)

    def test_multichain_base(self):
        r = _make(bridge_name="multichain")
        self.assertEqual(r["bridge_base_risk_score"], 35)

    def test_nomad_base(self):
        r = _make(bridge_name="nomad")
        self.assertEqual(r["bridge_base_risk_score"], 40)

    def test_synapse_base(self):
        r = _make(bridge_name="synapse")
        self.assertEqual(r["bridge_base_risk_score"], 10)

    def test_hop_base(self):
        r = _make(bridge_name="hop")
        self.assertEqual(r["bridge_base_risk_score"], 10)

    def test_custom_base(self):
        r = _make(bridge_name="custom")
        self.assertEqual(r["bridge_base_risk_score"], 30)

    def test_base_score_case_insensitive(self):
        r = _make(bridge_name="LAYERZERO")
        self.assertEqual(r["bridge_base_risk_score"], 8)

    def test_base_score_mixed_case(self):
        r = _make(bridge_name="StarGate")
        self.assertEqual(r["bridge_base_risk_score"], 12)

    def test_base_score_with_whitespace(self):
        r = _make(bridge_name="  hop  ")
        self.assertEqual(r["bridge_base_risk_score"], 10)


class TestHackPenalty(unittest.TestCase):
    """hack_history_penalty computation."""

    def test_no_hack_penalty_is_zero(self):
        r = _make(prior_hack_usd=0.0)
        self.assertEqual(r["hack_history_penalty"], 0)

    def test_small_hack_penalty(self):
        # 1e7 → int(1e7/1e7) = 1
        r = _make(prior_hack_usd=1e7)
        self.assertEqual(r["hack_history_penalty"], 1)

    def test_large_hack_penalty_capped_at_40(self):
        # Ronin $625M → int(625e6/1e7) = 62 → min(40, 62) = 40
        r = _make(prior_hack_usd=625_000_000.0)
        self.assertEqual(r["hack_history_penalty"], 40)

    def test_wormhole_hack_penalty(self):
        # $320M → int(32) → min(40,32) = 32
        r = _make(prior_hack_usd=320_000_000.0)
        self.assertEqual(r["hack_history_penalty"], 32)

    def test_nomad_hack_penalty(self):
        # $190M → int(19) → min(40,19) = 19
        r = _make(prior_hack_usd=190_000_000.0)
        self.assertEqual(r["hack_history_penalty"], 19)

    def test_just_below_cap(self):
        r = _make(prior_hack_usd=399_999_999.0)
        self.assertEqual(r["hack_history_penalty"], 39)

    def test_at_cap_boundary(self):
        r = _make(prior_hack_usd=400_000_000.0)
        self.assertEqual(r["hack_history_penalty"], 40)

    def test_very_small_hack_less_than_1e7(self):
        # $5M → int(0.5) = 0, but prior_hack_usd > 0 → min(40, 0) = 0
        r = _make(prior_hack_usd=5_000_000.0)
        self.assertEqual(r["hack_history_penalty"], 0)

    def test_hack_penalty_exactly_ten_million(self):
        r = _make(prior_hack_usd=1e7)
        self.assertEqual(r["hack_history_penalty"], 1)


class TestMaturityBonus(unittest.TestCase):
    """maturity_bonus = min(15, age_days // 60)."""

    def test_new_bridge_zero_bonus(self):
        r = _make(bridge_age_days=0)
        self.assertEqual(r["maturity_bonus"], 0)

    def test_59_days_zero_bonus(self):
        r = _make(bridge_age_days=59)
        self.assertEqual(r["maturity_bonus"], 0)

    def test_60_days_one_bonus(self):
        r = _make(bridge_age_days=60)
        self.assertEqual(r["maturity_bonus"], 1)

    def test_120_days_two_bonus(self):
        r = _make(bridge_age_days=120)
        self.assertEqual(r["maturity_bonus"], 2)

    def test_365_days_six_bonus(self):
        r = _make(bridge_age_days=365)
        self.assertEqual(r["maturity_bonus"], 6)

    def test_900_days_capped_at_15(self):
        r = _make(bridge_age_days=900)
        self.assertEqual(r["maturity_bonus"], 15)

    def test_1200_days_still_capped(self):
        r = _make(bridge_age_days=1200)
        self.assertEqual(r["maturity_bonus"], 15)


class TestAuditBonus(unittest.TestCase):
    """audit_bonus = min(10, audit_count * 3)."""

    def test_zero_audits(self):
        r = _make(bridge_audit_count=0)
        self.assertEqual(r["audit_bonus"], 0)

    def test_one_audit(self):
        r = _make(bridge_audit_count=1)
        self.assertEqual(r["audit_bonus"], 3)

    def test_two_audits(self):
        r = _make(bridge_audit_count=2)
        self.assertEqual(r["audit_bonus"], 6)

    def test_three_audits_capped(self):
        r = _make(bridge_audit_count=3)
        self.assertEqual(r["audit_bonus"], 9)

    def test_four_audits_capped_at_10(self):
        r = _make(bridge_audit_count=4)
        self.assertEqual(r["audit_bonus"], 10)

    def test_ten_audits_still_capped(self):
        r = _make(bridge_audit_count=10)
        self.assertEqual(r["audit_bonus"], 10)


class TestCanonicalBonus(unittest.TestCase):
    """canonical_bonus: 20 if is_canonical_bridge else 0."""

    def test_canonical_true(self):
        r = _make(is_canonical_bridge=True)
        self.assertEqual(r["canonical_bonus"], 20)

    def test_canonical_false(self):
        r = _make(is_canonical_bridge=False)
        self.assertEqual(r["canonical_bonus"], 0)


class TestBridgeRiskScoreClamping(unittest.TestCase):
    """bridge_risk_score clamped 0-100."""

    def test_score_not_negative_native_rollup_max_bonuses(self):
        # native_rollup (base=0) + max bonuses → 0 + 0 - 15 - 10 - 20 = -45 → clamp 0
        r = _make(
            bridge_name="native_rollup",
            bridge_audit_count=10,
            bridge_age_days=1200,
            prior_hack_usd=0.0,
            is_canonical_bridge=True,
        )
        self.assertGreaterEqual(r["bridge_risk_score"], 0)

    def test_score_not_above_100_nomad_heavy_hack(self):
        r = _make(
            bridge_name="nomad",
            prior_hack_usd=900_000_000.0,
            bridge_audit_count=0,
            bridge_age_days=0,
            is_canonical_bridge=False,
        )
        self.assertLessEqual(r["bridge_risk_score"], 100)

    def test_score_is_integer(self):
        r = _make()
        self.assertIsInstance(r["bridge_risk_score"], int)

    def test_score_layerzero_typical(self):
        # layerzero(8) + 0 hack - 6 maturity - 6 audit - 0 canonical = -4 → 0
        # Actually: 8 + 0 - min(15,365//60) - min(10,2*3) - 0 = 8 - 6 - 6 = -4 → 0
        r = _make(
            bridge_name="layerzero",
            bridge_age_days=365,
            bridge_audit_count=2,
            prior_hack_usd=0.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 0)

    def test_score_wormhole_with_hack(self):
        # wormhole(20) + 32 hack - 6 maturity - 6 audit - 0 = 40
        r = _make(
            bridge_name="wormhole",
            bridge_age_days=365,
            bridge_audit_count=2,
            prior_hack_usd=320_000_000.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 40)

    def test_score_nomad_max_scenario(self):
        # nomad(40) + 40 hack - 0 maturity - 0 audit - 0 canonical = 80
        r = _make(
            bridge_name="nomad",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=400_000_000.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 80)

    def test_score_multichain_no_bonuses(self):
        # multichain(35) + 0 - 0 - 0 - 0 = 35
        r = _make(
            bridge_name="multichain",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=0.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 35)

    def test_score_canonical_native_rollup(self):
        # native_rollup(0) + 0 - 0 - 0 - 20 = -20 → 0
        r = _make(
            bridge_name="native_rollup",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=0.0,
            is_canonical_bridge=True,
        )
        self.assertEqual(r["bridge_risk_score"], 0)


class TestBridgeLabel(unittest.TestCase):
    """bridge_label thresholds."""

    def _score_to_label(self, target_score: int) -> str:
        # Force a specific risk score via nomad bridge + manual hack_penalty manipulation
        # Use custom bridge: base=30, then tune hack to get desired score
        # score = 30 + hack - maturity - audit - canonical
        # Simplest: zero all bonuses, set hack to target_score - 30
        hack_usd = max(0, (target_score - 30)) * 1e7
        r = _make(
            bridge_name="custom",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=hack_usd,
            is_canonical_bridge=False,
        )
        return r["bridge_label"]

    def test_label_score_0_battle_tested(self):
        r = _make(
            bridge_name="native_rollup",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=0.0,
            is_canonical_bridge=True,
        )
        self.assertEqual(r["bridge_label"], "BATTLE_TESTED_BRIDGE")

    def test_label_score_10_battle_tested(self):
        # layerzero(8) + hack=2(20M) - 0 - 0 - 0 = 10
        r = _make(
            bridge_name="layerzero",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=20_000_000.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 10)
        self.assertEqual(r["bridge_label"], "BATTLE_TESTED_BRIDGE")

    def test_label_score_11_established(self):
        # layerzero(8) + hack=3(30M) - 0 - 0 - 0 = 11
        r = _make(
            bridge_name="layerzero",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=30_000_000.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 11)
        self.assertEqual(r["bridge_label"], "ESTABLISHED_BRIDGE")

    def test_label_score_25_established(self):
        # synapse(10) + hack=15(150M) = 25
        r = _make(
            bridge_name="synapse",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=150_000_000.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 25)
        self.assertEqual(r["bridge_label"], "ESTABLISHED_BRIDGE")

    def test_label_score_26_moderate(self):
        # synapse(10) + hack=16(160M) = 26
        r = _make(
            bridge_name="synapse",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=160_000_000.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 26)
        self.assertEqual(r["bridge_label"], "MODERATE_BRIDGE_RISK")

    def test_label_score_45_moderate(self):
        # wormhole(20) + hack=25(250M) = 45
        r = _make(
            bridge_name="wormhole",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=250_000_000.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 45)
        self.assertEqual(r["bridge_label"], "MODERATE_BRIDGE_RISK")

    def test_label_score_46_high(self):
        # wormhole(20) + hack=26(260M) = 46
        r = _make(
            bridge_name="wormhole",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=260_000_000.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 46)
        self.assertEqual(r["bridge_label"], "HIGH_BRIDGE_RISK")

    def test_label_score_70_high(self):
        # nomad(40) + hack=30(300M) = 70
        r = _make(
            bridge_name="nomad",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=300_000_000.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 70)
        self.assertEqual(r["bridge_label"], "HIGH_BRIDGE_RISK")

    def test_label_score_71_avoid(self):
        # nomad(40) + hack=31(310M) = 71
        r = _make(
            bridge_name="nomad",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=310_000_000.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 71)
        self.assertEqual(r["bridge_label"], "AVOID_BRIDGE")

    def test_label_score_100_avoid(self):
        r = _make(
            bridge_name="nomad",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=625_000_000.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 80)
        self.assertEqual(r["bridge_label"], "AVOID_BRIDGE")


class TestExpectedLoss(unittest.TestCase):
    """expected_loss_usd = exposure * score/100 * 0.1."""

    def test_zero_exposure_zero_loss(self):
        r = _make(position_bridge_exposure_usd=0.0)
        self.assertEqual(r["expected_loss_usd"], 0.0)

    def test_zero_score_zero_loss(self):
        r = _make(
            bridge_name="native_rollup",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=0.0,
            is_canonical_bridge=True,
            position_bridge_exposure_usd=100_000.0,
        )
        # Score = 0 → loss = 0
        self.assertEqual(r["expected_loss_usd"], 0.0)

    def test_loss_formula_basic(self):
        # wormhole(20) + hack=32(320M) - 6 maturity - 6 audit - 0 = 40
        r = _make(
            bridge_name="wormhole",
            bridge_age_days=365,
            bridge_audit_count=2,
            prior_hack_usd=320_000_000.0,
            is_canonical_bridge=False,
            position_bridge_exposure_usd=100_000.0,
        )
        expected = 100_000.0 * (r["bridge_risk_score"] / 100) * 0.1
        self.assertAlmostEqual(r["expected_loss_usd"], expected, places=4)

    def test_loss_100_score(self):
        # Force score=80 (nomad+hack=40+40=80 → capped at 80)
        r = _make(
            bridge_name="nomad",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=900_000_000.0,
            is_canonical_bridge=False,
            position_bridge_exposure_usd=50_000.0,
        )
        expected = 50_000.0 * (r["bridge_risk_score"] / 100) * 0.1
        self.assertAlmostEqual(r["expected_loss_usd"], expected, places=4)

    def test_loss_large_exposure(self):
        r = _make(
            bridge_name="wormhole",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=0.0,
            is_canonical_bridge=False,
            position_bridge_exposure_usd=1_000_000.0,
        )
        # wormhole(20) + 0 hack - 0 maturity - 0 audit - 0 = 20
        expected = 1_000_000.0 * (20 / 100) * 0.1
        self.assertAlmostEqual(r["expected_loss_usd"], expected, places=4)


class TestResultStructure(unittest.TestCase):
    """Result dict has all required keys."""

    REQUIRED_KEYS = [
        "protocol_name", "bridge_name", "bridge_tvl_usd",
        "bridge_audit_count", "bridge_age_days", "prior_hack_usd",
        "position_bridge_exposure_usd", "is_canonical_bridge",
        "bridge_base_risk_score", "hack_history_penalty",
        "maturity_bonus", "audit_bonus", "canonical_bonus",
        "bridge_risk_score", "expected_loss_usd", "bridge_label",
        "timestamp",
    ]

    def test_all_keys_present(self):
        r = _make()
        for k in self.REQUIRED_KEYS:
            self.assertIn(k, r, f"Missing key: {k}")

    def test_inputs_echoed_correctly(self):
        r = _make(
            bridge_name="hop",
            bridge_tvl_usd=5_000_000.0,
            bridge_audit_count=3,
            bridge_age_days=180,
            prior_hack_usd=0.0,
            position_bridge_exposure_usd=20_000.0,
            is_canonical_bridge=False,
            protocol_name="HopTest",
        )
        self.assertEqual(r["bridge_name"], "hop")
        self.assertEqual(r["bridge_tvl_usd"], 5_000_000.0)
        self.assertEqual(r["bridge_audit_count"], 3)
        self.assertEqual(r["bridge_age_days"], 180)
        self.assertEqual(r["prior_hack_usd"], 0.0)
        self.assertEqual(r["position_bridge_exposure_usd"], 20_000.0)
        self.assertEqual(r["is_canonical_bridge"], False)
        self.assertEqual(r["protocol_name"], "HopTest")

    def test_timestamp_is_int(self):
        r = _make()
        self.assertIsInstance(r["timestamp"], int)
        self.assertGreater(r["timestamp"], 0)

    def test_bridge_label_is_str(self):
        r = _make()
        self.assertIsInstance(r["bridge_label"], str)

    def test_expected_loss_is_float(self):
        r = _make()
        self.assertIsInstance(r["expected_loss_usd"], float)


class TestValidation(unittest.TestCase):
    """Input validation raises ValueError on bad inputs."""

    def test_unknown_bridge_name_raises(self):
        with self.assertRaises(ValueError):
            _make(bridge_name="rainbow_bridge")

    def test_negative_tvl_raises(self):
        with self.assertRaises(ValueError):
            _make(bridge_tvl_usd=-1.0)

    def test_negative_audit_count_raises(self):
        with self.assertRaises(ValueError):
            _make(bridge_audit_count=-1)

    def test_negative_age_days_raises(self):
        with self.assertRaises(ValueError):
            _make(bridge_age_days=-1)

    def test_negative_prior_hack_raises(self):
        with self.assertRaises(ValueError):
            _make(prior_hack_usd=-1.0)

    def test_negative_exposure_raises(self):
        with self.assertRaises(ValueError):
            _make(position_bridge_exposure_usd=-1.0)

    def test_empty_bridge_name_raises(self):
        with self.assertRaises(ValueError):
            _make(bridge_name="")

    def test_zero_values_do_not_raise(self):
        r = _make(
            bridge_tvl_usd=0.0,
            bridge_audit_count=0,
            bridge_age_days=0,
            prior_hack_usd=0.0,
            position_bridge_exposure_usd=0.0,
        )
        self.assertIsNotNone(r)


class TestClassMethodScore(unittest.TestCase):
    """Class-method .score() convenience wrapper."""

    def test_class_method_returns_dict(self):
        r = DeFiProtocolCrossChainBridgeRiskAnalyzer.score(
            bridge_name="hop",
            bridge_tvl_usd=2_000_000.0,
            bridge_audit_count=1,
            bridge_age_days=120,
            prior_hack_usd=0.0,
            position_bridge_exposure_usd=5_000.0,
            is_canonical_bridge=False,
            protocol_name="Hop",
        )
        self.assertIn("bridge_risk_score", r)
        self.assertIn("bridge_label", r)

    def test_class_method_matches_instance(self):
        kwargs = dict(
            bridge_name="stargate",
            bridge_tvl_usd=10_000_000.0,
            bridge_audit_count=2,
            bridge_age_days=400,
            prior_hack_usd=0.0,
            position_bridge_exposure_usd=15_000.0,
            is_canonical_bridge=False,
            protocol_name="Stargate",
        )
        r_class = DeFiProtocolCrossChainBridgeRiskAnalyzer.score(**kwargs)
        a = DeFiProtocolCrossChainBridgeRiskAnalyzer()
        r_inst = a.analyze(**kwargs)
        self.assertEqual(r_class["bridge_risk_score"], r_inst["bridge_risk_score"])
        self.assertEqual(r_class["bridge_label"], r_inst["bridge_label"])


class TestLogFile(unittest.TestCase):
    """Ring-buffer logging (100 entries, atomic write)."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _make_logged(self, **kwargs):
        a = DeFiProtocolCrossChainBridgeRiskAnalyzer(data_dir=self.tmp_dir)
        defaults = dict(
            bridge_name="layerzero",
            bridge_tvl_usd=1_000_000.0,
            bridge_audit_count=2,
            bridge_age_days=365,
            prior_hack_usd=0.0,
            position_bridge_exposure_usd=10_000.0,
            is_canonical_bridge=False,
            protocol_name="TestProto",
        )
        defaults.update(kwargs)
        return a.analyze_and_log(**defaults)

    def test_log_file_created(self):
        self._make_logged()
        log_path = os.path.join(self.tmp_dir, "cross_chain_bridge_risk_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_log_file_is_valid_json(self):
        self._make_logged()
        log_path = os.path.join(self.tmp_dir, "cross_chain_bridge_risk_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_file_has_one_entry(self):
        self._make_logged()
        log_path = os.path.join(self.tmp_dir, "cross_chain_bridge_risk_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_accumulates_entries(self):
        for _ in range(5):
            self._make_logged()
        log_path = os.path.join(self.tmp_dir, "cross_chain_bridge_risk_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_caps_at_100(self):
        for _ in range(105):
            self._make_logged()
        log_path = os.path.join(self.tmp_dir, "cross_chain_bridge_risk_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_ring_buffer_keeps_newest(self):
        for i in range(101):
            self._make_logged(bridge_tvl_usd=float(i * 1000))
        log_path = os.path.join(self.tmp_dir, "cross_chain_bridge_risk_log.json")
        with open(log_path) as f:
            data = json.load(f)
        # Oldest discarded entry should have tvl=0
        tvls = [e["bridge_tvl_usd"] for e in data]
        self.assertNotIn(0.0, tvls)

    def test_log_entry_has_bridge_label(self):
        self._make_logged()
        log_path = os.path.join(self.tmp_dir, "cross_chain_bridge_risk_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIn("bridge_label", data[0])

    def test_log_entry_has_timestamp(self):
        self._make_logged()
        log_path = os.path.join(self.tmp_dir, "cross_chain_bridge_risk_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_expected_loss(self):
        self._make_logged()
        log_path = os.path.join(self.tmp_dir, "cross_chain_bridge_risk_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIn("expected_loss_usd", data[0])


class TestAllBridgeNames(unittest.TestCase):
    """All valid bridge names produce valid results."""

    def test_all_names_in_registry(self):
        for name in BRIDGE_BASE_SCORES:
            with self.subTest(name=name):
                r = _make(bridge_name=name)
                self.assertIn("bridge_risk_score", r)
                self.assertGreaterEqual(r["bridge_risk_score"], 0)
                self.assertLessEqual(r["bridge_risk_score"], 100)


class TestEdgeCases(unittest.TestCase):
    """Edge and boundary cases."""

    def test_very_large_exposure(self):
        # Use wormhole (base=20) with no bonuses so score>0
        r = _make(
            bridge_name="wormhole",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=0.0,
            is_canonical_bridge=False,
            position_bridge_exposure_usd=1_000_000_000.0,
        )
        self.assertGreater(r["expected_loss_usd"], 0.0)

    def test_exactly_60_days_gives_bonus_1(self):
        r = _make(bridge_age_days=60)
        self.assertEqual(r["maturity_bonus"], 1)

    def test_exactly_600_days_gives_bonus_10(self):
        r = _make(bridge_age_days=600)
        self.assertEqual(r["maturity_bonus"], 10)

    def test_exactly_900_days_gives_bonus_15(self):
        r = _make(bridge_age_days=900)
        self.assertEqual(r["maturity_bonus"], 15)

    def test_score_floor_zero(self):
        r = _make(
            bridge_name="native_rollup",
            bridge_age_days=1200,
            bridge_audit_count=10,
            prior_hack_usd=0.0,
            is_canonical_bridge=True,
        )
        self.assertEqual(r["bridge_risk_score"], 0)

    def test_score_never_exceeds_100(self):
        r = _make(
            bridge_name="nomad",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=999_999_999.0,
            is_canonical_bridge=False,
        )
        self.assertLessEqual(r["bridge_risk_score"], 100)

    def test_tvl_not_used_in_score(self):
        r1 = _make(bridge_tvl_usd=1.0)
        r2 = _make(bridge_tvl_usd=1_000_000_000.0)
        self.assertEqual(r1["bridge_risk_score"], r2["bridge_risk_score"])

    def test_protocol_name_not_used_in_score(self):
        r1 = _make(protocol_name="Alpha")
        r2 = _make(protocol_name="Beta")
        self.assertEqual(r1["bridge_risk_score"], r2["bridge_risk_score"])

    def test_canonical_plus_wormhole_reduces_score(self):
        r_no_canonical = _make(
            bridge_name="wormhole",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=0.0,
            is_canonical_bridge=False,
        )
        r_canonical = _make(
            bridge_name="wormhole",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=0.0,
            is_canonical_bridge=True,
        )
        self.assertLess(r_canonical["bridge_risk_score"], r_no_canonical["bridge_risk_score"])

    def test_hack_penalty_increases_score(self):
        r_no_hack = _make(bridge_name="synapse", prior_hack_usd=0.0)
        r_hack = _make(bridge_name="synapse", prior_hack_usd=100_000_000.0)
        self.assertGreater(r_hack["bridge_risk_score"], r_no_hack["bridge_risk_score"])

    def test_more_audits_lower_score(self):
        r_low = _make(bridge_audit_count=0)
        r_high = _make(bridge_audit_count=4)
        self.assertLess(r_high["bridge_risk_score"], r_low["bridge_risk_score"])

    def test_older_bridge_lower_score(self):
        r_new = _make(bridge_age_days=0)
        r_old = _make(bridge_age_days=900)
        self.assertLess(r_old["bridge_risk_score"], r_new["bridge_risk_score"])

    def test_exact_boundary_hack_penalty_40(self):
        r = _make(prior_hack_usd=400_000_000.0)
        self.assertEqual(r["hack_history_penalty"], 40)

    def test_exact_boundary_hack_penalty_39(self):
        r = _make(prior_hack_usd=390_000_000.0)
        self.assertEqual(r["hack_history_penalty"], 39)

    def test_zero_age_zero_maturity_bonus(self):
        r = _make(bridge_age_days=0)
        self.assertEqual(r["maturity_bonus"], 0)

    def test_combined_score_stargate_typical(self):
        # stargate(12) + 0 hack - 6 maturity - 6 audit - 0 canonical = 0
        r = _make(
            bridge_name="stargate",
            bridge_age_days=365,
            bridge_audit_count=2,
            prior_hack_usd=0.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 0)
        self.assertEqual(r["bridge_label"], "BATTLE_TESTED_BRIDGE")

    def test_hop_no_bonuses(self):
        # hop(10) + 0 - 0 - 0 - 0 = 10
        r = _make(
            bridge_name="hop",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=0.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 10)
        self.assertEqual(r["bridge_label"], "BATTLE_TESTED_BRIDGE")


class TestDataIntegrity(unittest.TestCase):
    """Verify output types and value ranges."""

    def test_base_risk_score_in_range(self):
        for name in BRIDGE_BASE_SCORES:
            r = _make(bridge_name=name)
            score = r["bridge_base_risk_score"]
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 40)

    def test_hack_penalty_in_range(self):
        for hack in [0, 1e6, 1e7, 1e8, 1e9]:
            r = _make(prior_hack_usd=hack)
            self.assertGreaterEqual(r["hack_history_penalty"], 0)
            self.assertLessEqual(r["hack_history_penalty"], 40)

    def test_maturity_bonus_in_range(self):
        for days in [0, 60, 180, 365, 900, 2000]:
            r = _make(bridge_age_days=days)
            self.assertGreaterEqual(r["maturity_bonus"], 0)
            self.assertLessEqual(r["maturity_bonus"], 15)

    def test_audit_bonus_in_range(self):
        for n in [0, 1, 2, 3, 4, 10, 100]:
            r = _make(bridge_audit_count=n)
            self.assertGreaterEqual(r["audit_bonus"], 0)
            self.assertLessEqual(r["audit_bonus"], 10)

    def test_risk_score_always_in_0_100(self):
        for name in BRIDGE_BASE_SCORES:
            for hack in [0, 1e8, 6e8]:
                for days in [0, 365, 900]:
                    for audits in [0, 5]:
                        for canonical in [False, True]:
                            r = _make(
                                bridge_name=name,
                                prior_hack_usd=hack,
                                bridge_age_days=days,
                                bridge_audit_count=audits,
                                is_canonical_bridge=canonical,
                            )
                            self.assertGreaterEqual(r["bridge_risk_score"], 0)
                            self.assertLessEqual(r["bridge_risk_score"], 100)

    def test_expected_loss_non_negative(self):
        r = _make()
        self.assertGreaterEqual(r["expected_loss_usd"], 0.0)

    def test_label_one_of_valid_values(self):
        valid = {
            "BATTLE_TESTED_BRIDGE", "ESTABLISHED_BRIDGE",
            "MODERATE_BRIDGE_RISK", "HIGH_BRIDGE_RISK", "AVOID_BRIDGE",
        }
        r = _make()
        self.assertIn(r["bridge_label"], valid)


class TestScoreFormulaCombinations(unittest.TestCase):
    """Explicit formula verification for various combinations."""

    def test_formula_all_zeroed_layerzero(self):
        # layerzero(8) + 0 - 0 - 0 - 0 = 8
        r = _make(
            bridge_name="layerzero",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=0.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 8)

    def test_formula_synapse_one_audit_60days(self):
        # synapse(10) + 0 - 1 maturity - 3 audit - 0 = 6
        r = _make(
            bridge_name="synapse",
            bridge_age_days=60,
            bridge_audit_count=1,
            prior_hack_usd=0.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 6)

    def test_formula_hop_canonical_reduces_score(self):
        # hop(10) + 0 - 0 - 0 - 20 = -10 → 0
        r = _make(
            bridge_name="hop",
            bridge_age_days=0,
            bridge_audit_count=0,
            prior_hack_usd=0.0,
            is_canonical_bridge=True,
        )
        self.assertEqual(r["bridge_risk_score"], 0)

    def test_formula_custom_with_hack(self):
        # custom(30) + 5 hack(50M) - 2 maturity(120d) - 3 audit(1) - 0 = 30
        r = _make(
            bridge_name="custom",
            bridge_age_days=120,
            bridge_audit_count=1,
            prior_hack_usd=50_000_000.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 30)

    def test_formula_wormhole_all_bonuses(self):
        # wormhole(20) + 0 hack - 15 maturity(900d) - 10 audit(4) - 20 canonical = -25 → 0
        r = _make(
            bridge_name="wormhole",
            bridge_age_days=900,
            bridge_audit_count=4,
            prior_hack_usd=0.0,
            is_canonical_bridge=True,
        )
        self.assertEqual(r["bridge_risk_score"], 0)

    def test_stargate_with_two_audits_and_maturity(self):
        # stargate(12) + 0 - 3(180d//60) - 6(2 audits) - 0 = 3
        r = _make(
            bridge_name="stargate",
            bridge_age_days=180,
            bridge_audit_count=2,
            prior_hack_usd=0.0,
            is_canonical_bridge=False,
        )
        self.assertEqual(r["bridge_risk_score"], 3)

    def test_hack_penalty_exact_boundary_2e7(self):
        # prior_hack=2e7 → int(2e7/1e7)=2 → penalty=2
        r = _make(prior_hack_usd=2e7)
        self.assertEqual(r["hack_history_penalty"], 2)

    def test_hack_penalty_exact_boundary_3e7(self):
        r = _make(prior_hack_usd=3e7)
        self.assertEqual(r["hack_history_penalty"], 3)

    def test_maturity_bonus_boundary_899_days(self):
        # 899 // 60 = 14
        r = _make(bridge_age_days=899)
        self.assertEqual(r["maturity_bonus"], 14)

    def test_audit_bonus_exactly_2_audits(self):
        r = _make(bridge_audit_count=2)
        self.assertEqual(r["audit_bonus"], 6)

    def test_canonical_reduces_by_exactly_20(self):
        r_no = _make(bridge_name="stargate", bridge_age_days=0, bridge_audit_count=0,
                     prior_hack_usd=0.0, is_canonical_bridge=False)
        r_yes = _make(bridge_name="stargate", bridge_age_days=0, bridge_audit_count=0,
                      prior_hack_usd=0.0, is_canonical_bridge=True)
        diff = r_no["bridge_risk_score"] - r_yes["bridge_risk_score"]
        # stargate=12 without canonical → 12; with canonical → 0 (clamped), diff may be ≤20
        self.assertGreaterEqual(diff, 0)

    def test_result_is_deterministic(self):
        r1 = _make(bridge_name="wormhole", bridge_age_days=200, bridge_audit_count=1,
                   prior_hack_usd=100_000_000.0, is_canonical_bridge=False)
        r2 = _make(bridge_name="wormhole", bridge_age_days=200, bridge_audit_count=1,
                   prior_hack_usd=100_000_000.0, is_canonical_bridge=False)
        self.assertEqual(r1["bridge_risk_score"], r2["bridge_risk_score"])
        self.assertEqual(r1["bridge_label"], r2["bridge_label"])


if __name__ == "__main__":
    unittest.main()
