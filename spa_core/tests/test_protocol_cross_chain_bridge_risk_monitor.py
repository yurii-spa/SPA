"""
Tests for MP-989: ProtocolCrossChainBridgeRiskMonitor
Run: python3 -m unittest spa_core.tests.test_protocol_cross_chain_bridge_risk_monitor
"""
import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_cross_chain_bridge_risk_monitor import (
    ProtocolCrossChainBridgeRiskMonitor,
    _compute_centralization_score,
    _compute_composite_risk_score,
    _compute_coverage_ratio,
    _compute_flags,
    _compute_incident_risk_score,
    _compute_risk_label,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _bridge(
    name="BridgeX",
    bridge_type="lock_mint",
    total_tvl_bridged_usd=500_000_000.0,
    top_asset_concentration_pct=50.0,
    validator_count=15,
    validator_threshold_pct=66.0,
    audit_count=3,
    incidents_count_all_time=0,
    amount_lost_all_time_usd=0.0,
    days_since_last_incident=9999,
    canonical_bridge=False,
    insurance_coverage_usd=0.0,
):
    return dict(
        name=name,
        bridge_type=bridge_type,
        total_tvl_bridged_usd=total_tvl_bridged_usd,
        top_asset_concentration_pct=top_asset_concentration_pct,
        validator_count=validator_count,
        validator_threshold_pct=validator_threshold_pct,
        audit_count=audit_count,
        incidents_count_all_time=incidents_count_all_time,
        amount_lost_all_time_usd=amount_lost_all_time_usd,
        days_since_last_incident=days_since_last_incident,
        canonical_bridge=canonical_bridge,
        insurance_coverage_usd=insurance_coverage_usd,
    )


# ── helper function tests ─────────────────────────────────────────────────────

class TestCentralizationScore(unittest.TestCase):

    def test_zk_proof_lowest_base(self):
        score = _compute_centralization_score("zk_proof", 100, 66.0)
        lock_mint = _compute_centralization_score("lock_mint", 100, 66.0)
        self.assertLess(score, lock_mint)

    def test_lock_mint_highest_base(self):
        zk = _compute_centralization_score("zk_proof", 10, 66.0)
        lm = _compute_centralization_score("lock_mint", 10, 66.0)
        self.assertGreater(lm, zk)

    def test_canonical_lower_than_lock_mint(self):
        c = _compute_centralization_score("canonical", 10, 66.0)
        lm = _compute_centralization_score("lock_mint", 10, 66.0)
        self.assertLess(c, lm)

    def test_more_validators_lower_score(self):
        few = _compute_centralization_score("lock_mint", 3, 66.0)
        many = _compute_centralization_score("lock_mint", 50, 66.0)
        self.assertGreater(few, many)

    def test_higher_threshold_higher_score(self):
        low = _compute_centralization_score("lock_mint", 10, 33.0)
        high = _compute_centralization_score("lock_mint", 10, 90.0)
        self.assertGreater(high, low)

    def test_capped_at_100(self):
        score = _compute_centralization_score("lock_mint", 1, 100.0)
        self.assertLessEqual(score, 100.0)

    def test_minimum_is_non_negative(self):
        score = _compute_centralization_score("zk_proof", 10000, 0.0)
        self.assertGreaterEqual(score, 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_compute_centralization_score("lock_mint", 10, 66.0), float)

    def test_zero_validators(self):
        # When validator_count=0, no validator-based penalties apply
        score_0 = _compute_centralization_score("lock_mint", 0, 66.0)
        self.assertGreaterEqual(score_0, 0.0)
        self.assertLessEqual(score_0, 100.0)

    def test_optimistic_between_canonical_and_lock_mint(self):
        c = _compute_centralization_score("canonical", 10, 50.0)
        o = _compute_centralization_score("optimistic", 10, 50.0)
        lm = _compute_centralization_score("lock_mint", 10, 50.0)
        self.assertGreater(o, c)
        self.assertLess(o, lm)


class TestIncidentRiskScore(unittest.TestCase):

    def test_zero_incidents_returns_zero(self):
        self.assertEqual(_compute_incident_risk_score(0, 0, 0.0, 1_000_000.0), 0.0)

    def test_recent_incident_high_score(self):
        score = _compute_incident_risk_score(1, 30, 1_000_000.0, 10_000_000.0)
        self.assertGreater(score, 20.0)

    def test_old_incident_lower_score(self):
        recent = _compute_incident_risk_score(1, 30, 0.0, 1_000_000.0)
        old = _compute_incident_risk_score(1, 800, 0.0, 1_000_000.0)
        self.assertGreater(recent, old)

    def test_more_incidents_higher_frequency(self):
        one = _compute_incident_risk_score(1, 9999, 0.0, 1_000_000.0)
        four = _compute_incident_risk_score(4, 9999, 0.0, 1_000_000.0)
        self.assertGreater(four, one)

    def test_large_loss_raises_score(self):
        no_loss = _compute_incident_risk_score(1, 9999, 0.0, 1_000_000.0)
        big_loss = _compute_incident_risk_score(1, 9999, 5_000_000.0, 1_000_000.0)
        self.assertGreater(big_loss, no_loss)

    def test_capped_at_100(self):
        score = _compute_incident_risk_score(100, 1, 1e12, 1_000_000.0)
        self.assertLessEqual(score, 100.0)

    def test_returns_float(self):
        self.assertIsInstance(_compute_incident_risk_score(1, 100, 0.0, 1e6), float)

    def test_frequency_capped_at_40(self):
        # 10 incidents → frequency would be 100 but capped at 40
        score_10 = _compute_incident_risk_score(10, 9999, 0.0, 1e6)
        score_20 = _compute_incident_risk_score(20, 9999, 0.0, 1e6)
        # Both are frequency-capped; should be equal (ignoring other terms)
        self.assertAlmostEqual(score_10, score_20, delta=1.0)

    def test_non_negative(self):
        self.assertGreaterEqual(_compute_incident_risk_score(0, 9999, 0.0, 1e6), 0.0)

    def test_180_day_boundary(self):
        at_180 = _compute_incident_risk_score(1, 180, 0.0, 1e6)
        just_before = _compute_incident_risk_score(1, 179, 0.0, 1e6)
        self.assertGreater(just_before, at_180)


class TestCoverageRatio(unittest.TestCase):

    def test_zero_tvl_returns_zero(self):
        self.assertEqual(_compute_coverage_ratio(1_000_000.0, 0.0), 0.0)

    def test_correct_ratio(self):
        ratio = _compute_coverage_ratio(50_000_000.0, 1_000_000_000.0)
        self.assertAlmostEqual(ratio, 5.0, places=2)

    def test_over_100_pct_possible(self):
        ratio = _compute_coverage_ratio(200_000_000.0, 100_000_000.0)
        self.assertGreater(ratio, 100.0)

    def test_returns_float(self):
        self.assertIsInstance(_compute_coverage_ratio(1e6, 1e7), float)

    def test_zero_insurance_zero_ratio(self):
        self.assertEqual(_compute_coverage_ratio(0.0, 1_000_000.0), 0.0)


class TestCompositeRiskScore(unittest.TestCase):

    def test_high_centralization_high_score(self):
        score = _compute_composite_risk_score(90.0, 0.0, 0.0)
        self.assertGreater(score, 30.0)

    def test_high_incident_risk_high_score(self):
        score = _compute_composite_risk_score(0.0, 90.0, 0.0)
        self.assertGreater(score, 30.0)

    def test_full_coverage_reduces_score(self):
        no_cov = _compute_composite_risk_score(50.0, 50.0, 0.0)
        with_cov = _compute_composite_risk_score(50.0, 50.0, 100.0)
        self.assertLess(with_cov, no_cov)

    def test_capped_at_100(self):
        score = _compute_composite_risk_score(100.0, 100.0, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_non_negative(self):
        score = _compute_composite_risk_score(0.0, 0.0, 100.0)
        self.assertGreaterEqual(score, 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_compute_composite_risk_score(50.0, 50.0, 10.0), float)


class TestRiskLabel(unittest.TestCase):

    def test_fortress_zk_no_incidents_audited(self):
        label = _compute_risk_label(
            bridge_type="zk_proof", incidents_count=0, days_since_last_incident=9999,
            audit_count=3, composite_risk_score=10.0, validator_count=100,
        )
        self.assertEqual(label, "FORTRESS")

    def test_critical_lock_mint_few_validators(self):
        label = _compute_risk_label(
            bridge_type="lock_mint", incidents_count=0, days_since_last_incident=9999,
            audit_count=2, composite_risk_score=50.0, validator_count=3,
        )
        self.assertEqual(label, "CRITICAL")

    def test_critical_recent_hack(self):
        label = _compute_risk_label(
            bridge_type="lock_mint", incidents_count=1, days_since_last_incident=30,
            audit_count=2, composite_risk_score=50.0, validator_count=20,
        )
        self.assertEqual(label, "CRITICAL")

    def test_low_risk_clean_score(self):
        label = _compute_risk_label(
            bridge_type="canonical", incidents_count=0, days_since_last_incident=9999,
            audit_count=1, composite_risk_score=10.0, validator_count=100,
        )
        self.assertEqual(label, "LOW_RISK")

    def test_moderate_risk(self):
        label = _compute_risk_label(
            bridge_type="liquidity_network", incidents_count=1, days_since_last_incident=200,
            audit_count=1, composite_risk_score=30.0, validator_count=20,
        )
        self.assertEqual(label, "MODERATE_RISK")

    def test_high_risk(self):
        label = _compute_risk_label(
            bridge_type="optimistic", incidents_count=2, days_since_last_incident=300,
            audit_count=1, composite_risk_score=55.0, validator_count=15,
        )
        self.assertEqual(label, "HIGH_RISK")

    def test_fortress_requires_zk(self):
        label = _compute_risk_label(
            bridge_type="canonical", incidents_count=0, days_since_last_incident=9999,
            audit_count=5, composite_risk_score=5.0, validator_count=100,
        )
        self.assertNotEqual(label, "FORTRESS")

    def test_fortress_requires_no_incidents(self):
        label = _compute_risk_label(
            bridge_type="zk_proof", incidents_count=1, days_since_last_incident=9999,
            audit_count=3, composite_risk_score=5.0, validator_count=100,
        )
        self.assertNotEqual(label, "FORTRESS")

    def test_fortress_requires_audits(self):
        label = _compute_risk_label(
            bridge_type="zk_proof", incidents_count=0, days_since_last_incident=9999,
            audit_count=0, composite_risk_score=5.0, validator_count=100,
        )
        self.assertNotEqual(label, "FORTRESS")

    def test_critical_threshold_90_days(self):
        # Exactly 89 days → CRITICAL
        label = _compute_risk_label(
            bridge_type="optimistic", incidents_count=1, days_since_last_incident=89,
            audit_count=2, composite_risk_score=20.0, validator_count=20,
        )
        self.assertEqual(label, "CRITICAL")

    def test_not_critical_at_90_days(self):
        # Exactly 90 days → NOT CRITICAL (< 90 required)
        label = _compute_risk_label(
            bridge_type="optimistic", incidents_count=1, days_since_last_incident=90,
            audit_count=2, composite_risk_score=20.0, validator_count=20,
        )
        self.assertNotEqual(label, "CRITICAL")

    def test_label_is_string(self):
        label = _compute_risk_label(
            "lock_mint", 0, 9999, 2, 50.0, 10
        )
        self.assertIsInstance(label, str)


class TestFlags(unittest.TestCase):

    def test_no_flags_safe_bridge(self):
        flags = _compute_flags(
            bridge_type="zk_proof", validator_count=50, incidents_count=0,
            days_since_last_incident=9999, coverage_ratio=20.0,
            top_asset_concentration_pct=30.0, canonical_bridge=False,
        )
        self.assertEqual(flags, [])

    def test_multisig_risk_flag(self):
        # lock_mint AND validators < 7
        flags = _compute_flags(
            bridge_type="lock_mint", validator_count=5, incidents_count=0,
            days_since_last_incident=9999, coverage_ratio=20.0,
            top_asset_concentration_pct=30.0, canonical_bridge=False,
        )
        self.assertIn("MULTISIG_RISK", flags)

    def test_multisig_risk_not_triggered_7_validators(self):
        flags = _compute_flags(
            bridge_type="lock_mint", validator_count=7, incidents_count=0,
            days_since_last_incident=9999, coverage_ratio=20.0,
            top_asset_concentration_pct=30.0, canonical_bridge=False,
        )
        self.assertNotIn("MULTISIG_RISK", flags)

    def test_multisig_risk_not_triggered_non_lock_mint(self):
        flags = _compute_flags(
            bridge_type="zk_proof", validator_count=3, incidents_count=0,
            days_since_last_incident=9999, coverage_ratio=20.0,
            top_asset_concentration_pct=30.0, canonical_bridge=False,
        )
        self.assertNotIn("MULTISIG_RISK", flags)

    def test_recent_incident_flag(self):
        flags = _compute_flags(
            bridge_type="zk_proof", validator_count=50, incidents_count=1,
            days_since_last_incident=100, coverage_ratio=20.0,
            top_asset_concentration_pct=30.0, canonical_bridge=False,
        )
        self.assertIn("RECENT_INCIDENT", flags)

    def test_recent_incident_not_triggered_no_incidents(self):
        flags = _compute_flags(
            bridge_type="zk_proof", validator_count=50, incidents_count=0,
            days_since_last_incident=10, coverage_ratio=20.0,
            top_asset_concentration_pct=30.0, canonical_bridge=False,
        )
        self.assertNotIn("RECENT_INCIDENT", flags)

    def test_recent_incident_not_triggered_after_180_days(self):
        flags = _compute_flags(
            bridge_type="zk_proof", validator_count=50, incidents_count=1,
            days_since_last_incident=181, coverage_ratio=20.0,
            top_asset_concentration_pct=30.0, canonical_bridge=False,
        )
        self.assertNotIn("RECENT_INCIDENT", flags)

    def test_uninsured_flag(self):
        flags = _compute_flags(
            bridge_type="zk_proof", validator_count=50, incidents_count=0,
            days_since_last_incident=9999, coverage_ratio=3.0,
            top_asset_concentration_pct=30.0, canonical_bridge=False,
        )
        self.assertIn("UNINSURED", flags)

    def test_uninsured_not_triggered_at_5_pct(self):
        # Exactly 5.0 → NOT triggered (< 5 required)
        flags = _compute_flags(
            bridge_type="zk_proof", validator_count=50, incidents_count=0,
            days_since_last_incident=9999, coverage_ratio=5.0,
            top_asset_concentration_pct=30.0, canonical_bridge=False,
        )
        self.assertNotIn("UNINSURED", flags)

    def test_asset_concentrated_flag(self):
        flags = _compute_flags(
            bridge_type="zk_proof", validator_count=50, incidents_count=0,
            days_since_last_incident=9999, coverage_ratio=20.0,
            top_asset_concentration_pct=75.0, canonical_bridge=False,
        )
        self.assertIn("ASSET_CONCENTRATED", flags)

    def test_asset_concentrated_not_triggered_below_60(self):
        flags = _compute_flags(
            bridge_type="zk_proof", validator_count=50, incidents_count=0,
            days_since_last_incident=9999, coverage_ratio=20.0,
            top_asset_concentration_pct=60.0, canonical_bridge=False,
        )
        self.assertNotIn("ASSET_CONCENTRATED", flags)

    def test_canonical_safe_flag(self):
        flags = _compute_flags(
            bridge_type="zk_proof", validator_count=50, incidents_count=0,
            days_since_last_incident=9999, coverage_ratio=20.0,
            top_asset_concentration_pct=30.0, canonical_bridge=True,
        )
        self.assertIn("CANONICAL_SAFE", flags)

    def test_canonical_safe_not_triggered_non_zk(self):
        flags = _compute_flags(
            bridge_type="canonical", validator_count=50, incidents_count=0,
            days_since_last_incident=9999, coverage_ratio=20.0,
            top_asset_concentration_pct=30.0, canonical_bridge=True,
        )
        self.assertNotIn("CANONICAL_SAFE", flags)

    def test_canonical_safe_not_triggered_zk_not_canonical(self):
        flags = _compute_flags(
            bridge_type="zk_proof", validator_count=50, incidents_count=0,
            days_since_last_incident=9999, coverage_ratio=20.0,
            top_asset_concentration_pct=30.0, canonical_bridge=False,
        )
        self.assertNotIn("CANONICAL_SAFE", flags)

    def test_multiple_flags_simultaneously(self):
        flags = _compute_flags(
            bridge_type="lock_mint", validator_count=5, incidents_count=2,
            days_since_last_incident=30, coverage_ratio=1.0,
            top_asset_concentration_pct=80.0, canonical_bridge=False,
        )
        self.assertIn("MULTISIG_RISK", flags)
        self.assertIn("RECENT_INCIDENT", flags)
        self.assertIn("UNINSURED", flags)
        self.assertIn("ASSET_CONCENTRATED", flags)

    def test_flags_is_list(self):
        flags = _compute_flags(
            "lock_mint", 10, 0, 9999, 10.0, 30.0, False
        )
        self.assertIsInstance(flags, list)


class TestMonitorBasic(unittest.TestCase):
    """monitor() basic structure and content."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "bridge_log.json")
        self.monitor = ProtocolCrossChainBridgeRiskMonitor(log_path=self.log_path)

    def test_empty_bridges_returns_empty(self):
        result = self.monitor.monitor([], {})
        self.assertEqual(result["bridges"], [])
        self.assertEqual(result["bridge_count"], 0)

    def test_single_bridge_returns_one_entry(self):
        result = self.monitor.monitor([_bridge()], {})
        self.assertEqual(len(result["bridges"]), 1)

    def test_output_has_timestamp(self):
        result = self.monitor.monitor([], {})
        self.assertIn("timestamp", result)

    def test_output_has_bridge_count(self):
        result = self.monitor.monitor([_bridge(), _bridge(name="B2")], {})
        self.assertEqual(result["bridge_count"], 2)

    def test_output_has_aggregates(self):
        result = self.monitor.monitor([_bridge()], {})
        self.assertIn("aggregates", result)

    def test_bridge_entry_has_all_scored_fields(self):
        result = self.monitor.monitor([_bridge()], {})
        b = result["bridges"][0]
        for field in [
            "centralization_score", "incident_risk_score",
            "coverage_ratio", "composite_risk_score", "risk_label", "flags",
        ]:
            self.assertIn(field, b, f"Missing field: {field}")

    def test_name_propagated(self):
        result = self.monitor.monitor([_bridge(name="MyBridge")], {})
        self.assertEqual(result["bridges"][0]["name"], "MyBridge")

    def test_bridge_type_propagated(self):
        result = self.monitor.monitor([_bridge(bridge_type="zk_proof")], {})
        self.assertEqual(result["bridges"][0]["bridge_type"], "zk_proof")

    def test_centralization_score_range(self):
        result = self.monitor.monitor([_bridge()], {})
        score = result["bridges"][0]["centralization_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_composite_score_range(self):
        result = self.monitor.monitor([_bridge()], {})
        score = result["bridges"][0]["composite_risk_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_risk_label_valid(self):
        result = self.monitor.monitor([_bridge()], {})
        label = result["bridges"][0]["risk_label"]
        self.assertIn(label, {"FORTRESS", "LOW_RISK", "MODERATE_RISK", "HIGH_RISK", "CRITICAL"})

    def test_coverage_ratio_zero_no_insurance(self):
        result = self.monitor.monitor([_bridge(insurance_coverage_usd=0.0)], {})
        self.assertEqual(result["bridges"][0]["coverage_ratio"], 0.0)

    def test_coverage_ratio_calculated(self):
        result = self.monitor.monitor(
            [_bridge(insurance_coverage_usd=50_000_000.0, total_tvl_bridged_usd=1_000_000_000.0)], {}
        )
        self.assertAlmostEqual(result["bridges"][0]["coverage_ratio"], 5.0, places=2)

    def test_flags_is_list(self):
        result = self.monitor.monitor([_bridge()], {})
        self.assertIsInstance(result["bridges"][0]["flags"], list)

    def test_missing_fields_use_defaults(self):
        result = self.monitor.monitor([{"name": "MinBridge"}], {})
        self.assertEqual(len(result["bridges"]), 1)

    def test_multiple_bridges(self):
        bridges = [_bridge(name=f"B{i}") for i in range(5)]
        result = self.monitor.monitor(bridges, {})
        self.assertEqual(result["bridge_count"], 5)
        self.assertEqual(len(result["bridges"]), 5)


class TestRiskLabelIntegration(unittest.TestCase):
    """End-to-end risk label assignment via monitor()."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.monitor = ProtocolCrossChainBridgeRiskMonitor(
            log_path=os.path.join(self.tmp, "log.json")
        )

    def test_fortress_label(self):
        b = _bridge(
            bridge_type="zk_proof", incidents_count_all_time=0, audit_count=3,
            canonical_bridge=True, validator_count=100,
        )
        result = self.monitor.monitor([b], {})
        self.assertEqual(result["bridges"][0]["risk_label"], "FORTRESS")

    def test_critical_label_few_validators(self):
        b = _bridge(
            bridge_type="lock_mint", validator_count=3,
            incidents_count_all_time=0,
        )
        result = self.monitor.monitor([b], {})
        self.assertEqual(result["bridges"][0]["risk_label"], "CRITICAL")

    def test_critical_label_recent_hack(self):
        b = _bridge(
            bridge_type="zk_proof", incidents_count_all_time=1,
            days_since_last_incident=30, validator_count=100, audit_count=5,
        )
        result = self.monitor.monitor([b], {})
        self.assertEqual(result["bridges"][0]["risk_label"], "CRITICAL")

    def test_low_risk_label(self):
        b = _bridge(
            bridge_type="canonical", incidents_count_all_time=0,
            validator_count=100, audit_count=2,
            insurance_coverage_usd=100_000_000.0,  # high coverage
        )
        result = self.monitor.monitor([b], {})
        self.assertIn(result["bridges"][0]["risk_label"], {"LOW_RISK", "FORTRESS"})


class TestAggregates(unittest.TestCase):
    """Aggregates block correctness."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.monitor = ProtocolCrossChainBridgeRiskMonitor(
            log_path=os.path.join(self.tmp, "log.json")
        )

    def test_empty_aggregates(self):
        result = self.monitor.monitor([], {})
        agg = result["aggregates"]
        self.assertIsNone(agg["safest_bridge"])
        self.assertIsNone(agg["riskiest_bridge"])
        self.assertEqual(agg["total_tvl_at_risk_usd"], 0.0)
        self.assertEqual(agg["critical_count"], 0)
        self.assertEqual(agg["fortress_count"], 0)

    def test_safest_bridge_lowest_composite(self):
        b1 = _bridge(name="SafeBridge", bridge_type="zk_proof",
                     incidents_count_all_time=0, validator_count=100, audit_count=5,
                     insurance_coverage_usd=500_000_000.0)
        b2 = _bridge(name="RiskyBridge", bridge_type="lock_mint",
                     validator_count=3, incidents_count_all_time=2,
                     days_since_last_incident=30)
        result = self.monitor.monitor([b1, b2], {})
        self.assertEqual(result["aggregates"]["safest_bridge"], "SafeBridge")

    def test_riskiest_bridge_highest_composite(self):
        b1 = _bridge(name="SafeBridge", bridge_type="zk_proof",
                     incidents_count_all_time=0, validator_count=100, audit_count=5,
                     insurance_coverage_usd=500_000_000.0)
        b2 = _bridge(name="RiskyBridge", bridge_type="lock_mint",
                     validator_count=3, incidents_count_all_time=2,
                     days_since_last_incident=30)
        result = self.monitor.monitor([b1, b2], {})
        self.assertEqual(result["aggregates"]["riskiest_bridge"], "RiskyBridge")

    def test_total_tvl_at_risk_includes_high_and_critical(self):
        b_critical = _bridge(
            name="Critical", bridge_type="lock_mint", validator_count=3,
            total_tvl_bridged_usd=100_000_000.0,
        )
        b_safe = _bridge(
            name="Safe", bridge_type="zk_proof", incidents_count_all_time=0,
            audit_count=3, total_tvl_bridged_usd=50_000_000.0,
            validator_count=100,
        )
        result = self.monitor.monitor([b_critical, b_safe], {})
        agg = result["aggregates"]
        # Only critical bridges count toward TVL at risk
        self.assertGreaterEqual(agg["total_tvl_at_risk_usd"], 100_000_000.0)

    def test_critical_count(self):
        b1 = _bridge(name="C1", bridge_type="lock_mint", validator_count=2)
        b2 = _bridge(name="C2", bridge_type="lock_mint", validator_count=1)
        b3 = _bridge(name="Safe", bridge_type="zk_proof", incidents_count_all_time=0,
                     audit_count=3, validator_count=100)
        result = self.monitor.monitor([b1, b2, b3], {})
        self.assertEqual(result["aggregates"]["critical_count"], 2)

    def test_fortress_count(self):
        b1 = _bridge(name="F1", bridge_type="zk_proof", incidents_count_all_time=0,
                     audit_count=3, validator_count=100)
        b2 = _bridge(name="F2", bridge_type="zk_proof", incidents_count_all_time=0,
                     audit_count=2, validator_count=50)
        b3 = _bridge(name="R1", bridge_type="lock_mint", validator_count=5)
        result = self.monitor.monitor([b1, b2, b3], {})
        self.assertGreaterEqual(result["aggregates"]["fortress_count"], 2)

    def test_single_bridge_same_safest_riskiest(self):
        result = self.monitor.monitor([_bridge(name="OnlyBridge")], {})
        agg = result["aggregates"]
        self.assertEqual(agg["safest_bridge"], "OnlyBridge")
        self.assertEqual(agg["riskiest_bridge"], "OnlyBridge")

    def test_total_tvl_zero_when_all_safe(self):
        b = _bridge(name="Safe", bridge_type="zk_proof", incidents_count_all_time=0,
                    audit_count=3, validator_count=100)
        result = self.monitor.monitor([b], {})
        # Fortress has 0 TVL at risk
        self.assertEqual(result["aggregates"]["total_tvl_at_risk_usd"], 0.0)


class TestPersistAndLog(unittest.TestCase):
    """Ring-buffer log persistence."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "bridge_risk_log.json")
        self.monitor = ProtocolCrossChainBridgeRiskMonitor(log_path=self.log_path)

    def test_no_log_without_persist(self):
        self.monitor.monitor([_bridge()], {"persist": False})
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_file_created_with_persist(self):
        self.monitor.monitor([_bridge()], {"persist": True})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.monitor.monitor([_bridge()], {"persist": True})
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertIsInstance(log, list)

    def test_log_grows(self):
        for _ in range(3):
            self.monitor.monitor([_bridge()], {"persist": True})
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertEqual(len(log), 3)

    def test_log_entry_has_timestamp(self):
        self.monitor.monitor([_bridge()], {"persist": True})
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertIn("timestamp", log[0])

    def test_log_ring_buffer_cap(self):
        for _ in range(110):
            self.monitor.monitor([_bridge()], {"persist": True})
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertLessEqual(len(log), 100)

    def test_log_keeps_latest_entries(self):
        for i in range(105):
            self.monitor.monitor([_bridge(name=f"B{i}")], {"persist": True})
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertEqual(log[-1]["bridges"][0]["name"], "B104")

    def test_atomic_write_no_tmp_remains(self):
        self.monitor.monitor([_bridge()], {"persist": True})
        tmp_files = [f for f in os.listdir(self.tmp) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])

    def test_persist_default_false(self):
        self.monitor.monitor([_bridge()], {})
        self.assertFalse(os.path.exists(self.log_path))


class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.monitor = ProtocolCrossChainBridgeRiskMonitor(
            log_path=os.path.join(self.tmp, "log.json")
        )

    def test_zero_tvl_no_crash(self):
        b = _bridge(total_tvl_bridged_usd=0.0)
        result = self.monitor.monitor([b], {})
        self.assertEqual(len(result["bridges"]), 1)

    def test_very_large_tvl(self):
        b = _bridge(total_tvl_bridged_usd=1e15)
        result = self.monitor.monitor([b], {})
        self.assertIn("composite_risk_score", result["bridges"][0])

    def test_unknown_bridge_type_defaults(self):
        b = _bridge(bridge_type="unknown_type")
        result = self.monitor.monitor([b], {})
        self.assertIn("centralization_score", result["bridges"][0])

    def test_result_is_dict(self):
        result = self.monitor.monitor([_bridge()], {})
        self.assertIsInstance(result, dict)

    def test_many_bridges(self):
        bridges = [_bridge(name=f"B{i}", bridge_type="zk_proof",
                           validator_count=50, incidents_count_all_time=0, audit_count=3)
                   for i in range(20)]
        result = self.monitor.monitor(bridges, {})
        self.assertEqual(result["bridge_count"], 20)

    def test_days_since_incident_defaults_to_high(self):
        b = {"name": "MinBridge"}  # no days_since_last_incident field
        result = self.monitor.monitor([b], {})
        # Should not raise RECENT_INCIDENT since default is 9999
        self.assertNotIn("RECENT_INCIDENT", result["bridges"][0]["flags"])


if __name__ == "__main__":
    unittest.main()
