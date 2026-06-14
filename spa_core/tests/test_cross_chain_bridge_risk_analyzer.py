"""
Tests for MP-671: CrossChainBridgeRiskAnalyzer
Run: python3 -m unittest spa_core.tests.test_cross_chain_bridge_risk_analyzer -v
≥ 60 tests covering all helpers and integration paths.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.cross_chain_bridge_risk_analyzer import (
    BridgeProfile,
    BridgeRiskReport,
    CrossChainBridgeRiskAnalyzer,
    _arch_risk,
    _custody_risk,
    _sc_risk,
    _composite_risk,
    _risk_level,
    _build_recommendations,
    _bridge_verdict,
    MAX_ENTRIES,
    KNOWN_HACKED_BRIDGES,
)


def _make_profile(**kwargs) -> BridgeProfile:
    """Build a safe-default bridge profile, overridable by kwargs."""
    defaults = dict(
        bridge_id="test-bridge",
        bridge_type="NATIVE",
        tvl_usd=100_000_000,
        transfer_amount_usd=10_000,
        audit_count=3,
        has_multisig=True,
        validator_count=9,
        has_bug_bounty=True,
        protocol_age_days=500,
        previously_hacked=False,
        hack_amount_usd=0,
    )
    defaults.update(kwargs)
    return BridgeProfile(**defaults)


class TestArchRisk(unittest.TestCase):
    """_arch_risk: base per bridge type + hack multiplier."""

    def test_lock_mint_base(self):
        self.assertAlmostEqual(_arch_risk("LOCK_MINT", False), 0.60)

    def test_liquidity_base(self):
        self.assertAlmostEqual(_arch_risk("LIQUIDITY", False), 0.30)

    def test_native_base(self):
        self.assertAlmostEqual(_arch_risk("NATIVE", False), 0.15)

    def test_zk_proof_base(self):
        self.assertAlmostEqual(_arch_risk("ZK_PROOF", False), 0.05)

    def test_lock_mint_lowest_is_zk(self):
        self.assertLess(_arch_risk("ZK_PROOF", False), _arch_risk("NATIVE", False))
        self.assertLess(_arch_risk("NATIVE", False), _arch_risk("LIQUIDITY", False))
        self.assertLess(_arch_risk("LIQUIDITY", False), _arch_risk("LOCK_MINT", False))

    def test_previously_hacked_multiplies_by_15(self):
        # LIQUIDITY: 0.30 * 1.5 = 0.45
        self.assertAlmostEqual(_arch_risk("LIQUIDITY", True), 0.45)

    def test_previously_hacked_lock_mint_capped_at_1(self):
        # LOCK_MINT: 0.60 * 1.5 = 0.90 (≤ 1.0)
        result = _arch_risk("LOCK_MINT", True)
        self.assertAlmostEqual(result, 0.90)

    def test_previously_hacked_zk_multiplied(self):
        # ZK_PROOF: 0.05 * 1.5 = 0.075
        self.assertAlmostEqual(_arch_risk("ZK_PROOF", True), 0.075)

    def test_previously_hacked_native_multiplied(self):
        # NATIVE: 0.15 * 1.5 = 0.225
        self.assertAlmostEqual(_arch_risk("NATIVE", True), 0.225)

    def test_result_capped_at_1(self):
        # Any bridge_type × 1.5, capped
        self.assertLessEqual(_arch_risk("LOCK_MINT", True), 1.0)

    def test_unknown_type_fallback(self):
        # Unknown type falls back to 0.60 (lock-mint default)
        self.assertAlmostEqual(_arch_risk("UNKNOWN", False), 0.60)


class TestCustodyRisk(unittest.TestCase):
    """_custody_risk clamped [0.02, 0.95]."""

    def test_one_validator_no_extras(self):
        # 1/(1+1)=0.5
        self.assertAlmostEqual(_custody_risk(1, False, False), 0.5)

    def test_one_validator_multisig_reduces_by_01(self):
        # 0.5 - 0.1 = 0.4
        self.assertAlmostEqual(_custody_risk(1, True, False), 0.4)

    def test_one_validator_bug_bounty_reduces_by_005(self):
        # 0.5 - 0.05 = 0.45
        self.assertAlmostEqual(_custody_risk(1, False, True), 0.45)

    def test_one_validator_both_reduces(self):
        # 0.5 - 0.1 - 0.05 = 0.35
        self.assertAlmostEqual(_custody_risk(1, True, True), 0.35)

    def test_more_validators_reduces_base(self):
        # 9 validators: 1/10 = 0.1
        self.assertAlmostEqual(_custody_risk(9, False, False), 0.1)

    def test_many_validators_near_floor(self):
        # 99 validators: 1/100 = 0.01 → clamped to 0.02
        self.assertAlmostEqual(_custody_risk(99, False, False), 0.02)

    def test_clamp_lower_bound(self):
        result = _custody_risk(1000, True, True)
        self.assertGreaterEqual(result, 0.02)

    def test_clamp_upper_bound(self):
        result = _custody_risk(0, False, False)
        self.assertLessEqual(result, 0.95)

    def test_zero_validator_capped(self):
        # 1/(0+1)=1.0 → clamped 0.95
        self.assertAlmostEqual(_custody_risk(0, False, False), 0.95)

    def test_result_in_range(self):
        for vc in [0, 1, 3, 9, 21, 100]:
            r = _custody_risk(vc, True, True)
            self.assertGreaterEqual(r, 0.02)
            self.assertLessEqual(r, 0.95)


class TestSCRisk(unittest.TestCase):
    """_sc_risk for bridge: 0.6 base, audit/age reductions, clamped [0.05, 0.90]."""

    def test_zero_audits_new_protocol(self):
        # 0.6 - 0 - 0 = 0.6
        self.assertAlmostEqual(_sc_risk(0, 100), 0.6)

    def test_one_audit_reduces_by_01(self):
        self.assertAlmostEqual(_sc_risk(1, 100), 0.5)

    def test_two_audits_reduces_by_02(self):
        self.assertAlmostEqual(_sc_risk(2, 100), 0.4)

    def test_three_audits_reduces_by_03(self):
        self.assertAlmostEqual(_sc_risk(3, 100), 0.3)

    def test_audit_count_capped_at_3(self):
        # 5 audits same as 3
        self.assertAlmostEqual(_sc_risk(5, 100), _sc_risk(3, 100))

    def test_old_protocol_reduces_by_01(self):
        young = _sc_risk(0, 100)
        old = _sc_risk(0, 500)
        self.assertAlmostEqual(old, young - 0.1)

    def test_three_audits_old_protocol(self):
        # 0.6 - 0.3 - 0.1 = 0.2
        self.assertAlmostEqual(_sc_risk(3, 500), 0.2)

    def test_clamp_lower_bound(self):
        result = _sc_risk(100, 10000)
        self.assertGreaterEqual(result, 0.05)

    def test_clamp_upper_bound(self):
        result = _sc_risk(0, 1)
        self.assertLessEqual(result, 0.90)

    def test_result_is_float(self):
        self.assertIsInstance(_sc_risk(2, 400), float)


class TestCompositeRisk(unittest.TestCase):
    """_composite_risk weighted formula: arch*0.40 + custody*0.35 + sc*0.25."""

    def test_all_ones(self):
        # 0.40 + 0.35 + 0.25 = 1.0
        self.assertAlmostEqual(_composite_risk(1.0, 1.0, 1.0), 1.0)

    def test_all_zeros(self):
        self.assertAlmostEqual(_composite_risk(0.0, 0.0, 0.0), 0.0)

    def test_arch_weight_040(self):
        self.assertAlmostEqual(_composite_risk(1.0, 0.0, 0.0), 0.40)

    def test_custody_weight_035(self):
        self.assertAlmostEqual(_composite_risk(0.0, 1.0, 0.0), 0.35)

    def test_sc_weight_025(self):
        self.assertAlmostEqual(_composite_risk(0.0, 0.0, 1.0), 0.25)

    def test_known_combination(self):
        # arch=0.15, custody=0.1, sc=0.2
        expected = 0.15 * 0.40 + 0.10 * 0.35 + 0.20 * 0.25
        self.assertAlmostEqual(_composite_risk(0.15, 0.10, 0.20), expected, places=10)


class TestRiskLevel(unittest.TestCase):
    """_risk_level thresholds SAFE/LOW/MEDIUM/HIGH/EXTREME."""

    def test_safe_below_015(self):
        self.assertEqual(_risk_level(0.0), "SAFE")
        self.assertEqual(_risk_level(0.14), "SAFE")

    def test_low_below_030(self):
        self.assertEqual(_risk_level(0.15), "LOW")
        self.assertEqual(_risk_level(0.29), "LOW")

    def test_medium_below_050(self):
        self.assertEqual(_risk_level(0.30), "MEDIUM")
        self.assertEqual(_risk_level(0.49), "MEDIUM")

    def test_high_below_070(self):
        self.assertEqual(_risk_level(0.50), "HIGH")
        self.assertEqual(_risk_level(0.69), "HIGH")

    def test_extreme_at_070_and_above(self):
        self.assertEqual(_risk_level(0.70), "EXTREME")
        self.assertEqual(_risk_level(1.0), "EXTREME")

    def test_boundary_015_is_low(self):
        self.assertEqual(_risk_level(0.15), "LOW")

    def test_boundary_030_is_medium(self):
        self.assertEqual(_risk_level(0.30), "MEDIUM")

    def test_boundary_050_is_high(self):
        self.assertEqual(_risk_level(0.50), "HIGH")

    def test_boundary_070_is_extreme(self):
        self.assertEqual(_risk_level(0.70), "EXTREME")


class TestBridgeVerdict(unittest.TestCase):
    """_bridge_verdict maps risk_level → verdict."""

    def test_safe_is_approve(self):
        self.assertEqual(_bridge_verdict("SAFE"), "APPROVE")

    def test_low_is_approve(self):
        self.assertEqual(_bridge_verdict("LOW"), "APPROVE")

    def test_medium_is_caution(self):
        self.assertEqual(_bridge_verdict("MEDIUM"), "CAUTION")

    def test_high_is_avoid(self):
        self.assertEqual(_bridge_verdict("HIGH"), "AVOID")

    def test_extreme_is_avoid(self):
        self.assertEqual(_bridge_verdict("EXTREME"), "AVOID")


class TestRecommendations(unittest.TestCase):
    """_build_recommendations flags."""

    def test_previously_hacked_adds_hack_warning(self):
        recs = _build_recommendations(0.3, 0.2, True, 10_000, 100_000_000, "MEDIUM")
        self.assertTrue(any("hacked" in r.lower() or "🚨" in r for r in recs))

    def test_not_hacked_no_hack_warning(self):
        recs = _build_recommendations(0.3, 0.2, False, 10_000, 100_000_000, "LOW")
        self.assertFalse(any("hacked" in r.lower() for r in recs))

    def test_large_transfer_adds_liquidity_warning(self):
        # 11% of TVL
        recs = _build_recommendations(0.3, 0.2, False, 11_000_000, 100_000_000, "MEDIUM")
        self.assertTrue(any("10%" in r or "TVL" in r for r in recs))

    def test_small_transfer_no_liquidity_warning(self):
        # 5% of TVL
        recs = _build_recommendations(0.3, 0.2, False, 5_000_000, 100_000_000, "MEDIUM")
        self.assertFalse(any("TVL" in r for r in recs))

    def test_high_arch_risk_adds_lock_mint_warning(self):
        recs = _build_recommendations(0.6, 0.2, False, 10_000, 100_000_000, "HIGH")
        self.assertTrue(any("lock-mint" in r.lower() or "Lock-mint" in r for r in recs))

    def test_low_arch_risk_no_lock_mint_warning(self):
        recs = _build_recommendations(0.3, 0.2, False, 10_000, 100_000_000, "LOW")
        self.assertFalse(any("lock-mint" in r.lower() or "Lock-mint" in r for r in recs))

    def test_high_custody_risk_adds_validator_warning(self):
        recs = _build_recommendations(0.3, 0.6, False, 10_000, 100_000_000, "MEDIUM")
        self.assertTrue(any("validator" in r.lower() for r in recs))

    def test_safe_level_adds_approval_message(self):
        recs = _build_recommendations(0.05, 0.05, False, 10_000, 100_000_000, "SAFE")
        self.assertTrue(any("✅" in r for r in recs))

    def test_low_level_adds_approval_message(self):
        recs = _build_recommendations(0.1, 0.1, False, 10_000, 100_000_000, "LOW")
        self.assertTrue(any("✅" in r for r in recs))

    def test_medium_level_no_approval_message(self):
        recs = _build_recommendations(0.3, 0.3, False, 10_000, 100_000_000, "MEDIUM")
        self.assertFalse(any("✅" in r for r in recs))


class TestAnalyzeIntegration(unittest.TestCase):
    """Integration tests for CrossChainBridgeRiskAnalyzer.analyze()."""

    def setUp(self):
        self.analyzer = CrossChainBridgeRiskAnalyzer()

    def test_zk_many_validators_many_audits_safe_or_low(self):
        profile = _make_profile(
            bridge_type="ZK_PROOF",
            audit_count=4,
            has_multisig=True,
            validator_count=21,
            has_bug_bounty=True,
            protocol_age_days=600,
            previously_hacked=False,
        )
        report = self.analyzer.analyze(profile)
        self.assertIn(report.risk_level, ("SAFE", "LOW"))

    def test_zk_many_validators_verdict_approve(self):
        profile = _make_profile(
            bridge_type="ZK_PROOF",
            audit_count=4,
            has_multisig=True,
            validator_count=21,
            has_bug_bounty=True,
            protocol_age_days=600,
            previously_hacked=False,
        )
        report = self.analyzer.analyze(profile)
        self.assertEqual(report.bridge_verdict, "APPROVE")

    def test_lock_mint_hacked_one_validator_high_or_extreme(self):
        # LOCK_MINT hacked: arch=0.90, custody~0.5, sc=0.6 → composite~0.685 → HIGH
        # (threshold for EXTREME is ≥0.70; this profile lands in HIGH)
        profile = _make_profile(
            bridge_type="LOCK_MINT",
            audit_count=0,
            has_multisig=False,
            validator_count=1,
            has_bug_bounty=False,
            protocol_age_days=90,
            previously_hacked=True,
            hack_amount_usd=100_000_000,
        )
        report = self.analyzer.analyze(profile)
        self.assertIn(report.risk_level, ("HIGH", "EXTREME"))

    def test_lock_mint_hacked_verdict_avoid(self):
        profile = _make_profile(
            bridge_type="LOCK_MINT",
            audit_count=0,
            has_multisig=False,
            validator_count=1,
            has_bug_bounty=False,
            protocol_age_days=90,
            previously_hacked=True,
        )
        report = self.analyzer.analyze(profile)
        self.assertEqual(report.bridge_verdict, "AVOID")

    def test_report_fields_populated(self):
        report = self.analyzer.analyze(_make_profile())
        self.assertIsInstance(report.bridge_id, str)
        self.assertIsInstance(report.architecture_risk, float)
        self.assertIsInstance(report.custody_risk, float)
        self.assertIsInstance(report.smart_contract_risk, float)
        self.assertIsInstance(report.composite_risk, float)
        self.assertIsInstance(report.risk_level, str)
        self.assertIsInstance(report.transfer_risk_usd, float)
        self.assertIsInstance(report.recommendations, list)
        self.assertIsInstance(report.bridge_verdict, str)

    def test_risk_level_valid_values(self):
        report = self.analyzer.analyze(_make_profile())
        self.assertIn(report.risk_level, ("SAFE", "LOW", "MEDIUM", "HIGH", "EXTREME"))

    def test_verdict_valid_values(self):
        report = self.analyzer.analyze(_make_profile())
        self.assertIn(report.bridge_verdict, ("APPROVE", "CAUTION", "AVOID"))

    def test_transfer_risk_usd_equals_amount_times_composite(self):
        profile = _make_profile(transfer_amount_usd=100_000)
        report = self.analyzer.analyze(profile)
        expected = 100_000 * report.composite_risk
        self.assertAlmostEqual(report.transfer_risk_usd, expected, places=4)

    def test_bridge_id_preserved(self):
        profile = _make_profile(bridge_id="unique-bridge-xyz")
        report = self.analyzer.analyze(profile)
        self.assertEqual(report.bridge_id, "unique-bridge-xyz")

    def test_bridge_type_preserved(self):
        profile = _make_profile(bridge_type="LIQUIDITY")
        report = self.analyzer.analyze(profile)
        self.assertEqual(report.bridge_type, "LIQUIDITY")

    def test_composite_in_range(self):
        report = self.analyzer.analyze(_make_profile())
        self.assertGreaterEqual(report.composite_risk, 0.0)
        self.assertLessEqual(report.composite_risk, 1.0)

    def test_large_transfer_triggers_liquidity_warning(self):
        profile = _make_profile(
            tvl_usd=100_000,
            transfer_amount_usd=20_000,  # 20% of TVL
        )
        report = self.analyzer.analyze(profile)
        self.assertTrue(any("TVL" in r for r in report.recommendations))

    def test_previously_hacked_arch_risk_multiplied(self):
        clean = self.analyzer.analyze(_make_profile(bridge_type="LIQUIDITY", previously_hacked=False))
        hacked = self.analyzer.analyze(_make_profile(bridge_type="LIQUIDITY", previously_hacked=True))
        self.assertGreater(hacked.architecture_risk, clean.architecture_risk)


class TestAnalyzeBatch(unittest.TestCase):
    """analyze_batch()."""

    def setUp(self):
        self.analyzer = CrossChainBridgeRiskAnalyzer()

    def test_empty_batch_returns_empty(self):
        self.assertEqual(self.analyzer.analyze_batch([]), [])

    def test_batch_length_matches_input(self):
        profiles = [_make_profile(bridge_id=f"bridge-{i}") for i in range(5)]
        reports = self.analyzer.analyze_batch(profiles)
        self.assertEqual(len(reports), 5)

    def test_batch_preserves_order(self):
        profiles = [_make_profile(bridge_id=f"bridge-{i}") for i in range(3)]
        reports = self.analyzer.analyze_batch(profiles)
        for i, r in enumerate(reports):
            self.assertEqual(r.bridge_id, f"bridge-{i}")


class TestPersistence(unittest.TestCase):
    """save_results / load_history atomic writes + ring-buffer."""

    def setUp(self):
        self.analyzer = CrossChainBridgeRiskAnalyzer()
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "test_bridge_risk.json"

    def _make_report(self, bridge_id="test-bridge") -> BridgeRiskReport:
        profile = _make_profile(bridge_id=bridge_id)
        return self.analyzer.analyze(profile)

    def test_save_creates_file(self):
        reports = [self._make_report()]
        self.analyzer.save_results(reports, self.data_file)
        self.assertTrue(self.data_file.exists())

    def test_save_writes_valid_json(self):
        reports = [self._make_report()]
        self.analyzer.save_results(reports, self.data_file)
        with open(self.data_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_save_entry_has_expected_keys(self):
        reports = [self._make_report()]
        self.analyzer.save_results(reports, self.data_file)
        with open(self.data_file) as f:
            data = json.load(f)
        entry = data[0]
        for key in ("ts", "bridge_id", "risk_level", "bridge_verdict", "composite_risk"):
            self.assertIn(key, entry)

    def test_save_appends_on_second_call(self):
        self.analyzer.save_results([self._make_report("b-1")], self.data_file)
        self.analyzer.save_results([self._make_report("b-2")], self.data_file)
        with open(self.data_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_max_entries(self):
        for i in range(MAX_ENTRIES + 10):
            self.analyzer.save_results([self._make_report(f"b-{i}")], self.data_file)
        with open(self.data_file) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        n = MAX_ENTRIES + 5
        for i in range(n):
            self.analyzer.save_results([self._make_report(f"b-{i}")], self.data_file)
        with open(self.data_file) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["bridge_id"], f"b-{n - 1}")

    def test_atomic_write_no_tmp_left(self):
        self.analyzer.save_results([self._make_report()], self.data_file)
        tmp = str(self.data_file) + ".tmp"
        self.assertFalse(os.path.exists(tmp))

    def test_load_history_missing_file_returns_empty(self):
        missing = Path(self.tmp_dir) / "does_not_exist.json"
        result = self.analyzer.load_history(missing)
        self.assertEqual(result, [])

    def test_load_history_after_save(self):
        reports = [self._make_report("load-test")]
        self.analyzer.save_results(reports, self.data_file)
        history = self.analyzer.load_history(self.data_file)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["bridge_id"], "load-test")

    def test_load_history_corrupt_returns_empty(self):
        with open(self.data_file, "w") as f:
            f.write("{{invalid json")
        result = self.analyzer.load_history(self.data_file)
        self.assertEqual(result, [])

    def test_save_batch_multiple_reports(self):
        reports = [self._make_report(f"b{i}") for i in range(5)]
        self.analyzer.save_results(reports, self.data_file)
        with open(self.data_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)


class TestKnownHackedBridges(unittest.TestCase):
    """Verify KNOWN_HACKED_BRIDGES constant is intact."""

    def test_ronin_in_dict(self):
        self.assertIn("ronin", KNOWN_HACKED_BRIDGES)

    def test_wormhole_in_dict(self):
        self.assertIn("wormhole", KNOWN_HACKED_BRIDGES)

    def test_ronin_amount(self):
        self.assertEqual(KNOWN_HACKED_BRIDGES["ronin"], 625_000_000)

    def test_wormhole_amount(self):
        self.assertEqual(KNOWN_HACKED_BRIDGES["wormhole"], 320_000_000)


if __name__ == "__main__":
    unittest.main()
