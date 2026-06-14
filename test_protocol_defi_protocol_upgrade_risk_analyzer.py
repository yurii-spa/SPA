"""
MP-1039 ProtocolDeFiProtocolUpgradeRiskAnalyzer — unit tests (≥90)
Run: python3 -m unittest spa_core.tests.test_protocol_defi_protocol_upgrade_risk_analyzer -v
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_defi_protocol_upgrade_risk_analyzer import (
    analyze,
    log_result,
    ProtocolDeFiProtocolUpgradeRiskAnalyzer,
    _mechanism_risk,
    _timelock_risk,
    _governance_risk,
    _audit_risk,
    _frequency_risk,
    _recency_risk,
    _upgrade_risk_score,
    _governance_quality_score,
    _surprise_upgrade_risk,
    _label,
    _THRESHOLD_BATTLE_TESTED,
    _THRESHOLD_WELL_GOVERNED,
    _THRESHOLD_MODERATE_RISK,
    _THRESHOLD_HIGH_RISK,
    _LOG_RING_SIZE,
    _W_MECHANISM,
    _W_TIMELOCK,
    _W_GOVERNANCE,
    _W_AUDIT,
    _W_FREQUENCY,
    _W_RECENCY,
)


# ===========================================================================
# _mechanism_risk
# ===========================================================================

class TestMechanismRisk(unittest.TestCase):
    def test_immutable_lowest(self):
        self.assertEqual(_mechanism_risk("immutable"), 0.0)

    def test_proxy_higher_than_immutable(self):
        self.assertGreater(_mechanism_risk("proxy"), _mechanism_risk("immutable"))

    def test_multisig_higher_than_timelock(self):
        self.assertGreater(_mechanism_risk("multisig"), _mechanism_risk("timelock"))

    def test_proxy_higher_than_multisig(self):
        self.assertGreater(_mechanism_risk("proxy"), _mechanism_risk("multisig"))

    def test_dao_between_timelock_and_multisig(self):
        self.assertGreater(_mechanism_risk("dao"), _mechanism_risk("timelock"))
        self.assertLess(_mechanism_risk("dao"), _mechanism_risk("multisig"))

    def test_case_insensitive_immutable(self):
        self.assertEqual(_mechanism_risk("IMMUTABLE"), _mechanism_risk("immutable"))

    def test_case_insensitive_proxy(self):
        self.assertEqual(_mechanism_risk("PROXY"), _mechanism_risk("proxy"))

    def test_unknown_mechanism_positive(self):
        self.assertGreater(_mechanism_risk("unknown_xyz"), 0.0)

    def test_all_known_mechanisms_non_negative(self):
        for m in ("proxy", "immutable", "timelock", "multisig", "dao"):
            self.assertGreaterEqual(_mechanism_risk(m), 0.0)

    def test_all_known_mechanisms_at_most_100(self):
        for m in ("proxy", "immutable", "timelock", "multisig", "dao"):
            self.assertLessEqual(_mechanism_risk(m), 100.0)


# ===========================================================================
# _timelock_risk
# ===========================================================================

class TestTimelockRisk(unittest.TestCase):
    def test_immutable_always_zero(self):
        for hours in (0.0, 24.0, 168.0, 0.0):
            self.assertEqual(_timelock_risk("immutable", hours), 0.0)

    def test_no_timelock_max_risk(self):
        self.assertEqual(_timelock_risk("proxy", 0.0), 100.0)

    def test_long_timelock_low_risk(self):
        self.assertLessEqual(_timelock_risk("proxy", 168.0), 15.0)

    def test_monotone_decreasing_with_hours(self):
        risks = [_timelock_risk("proxy", h) for h in (0.0, 12.0, 48.0, 72.0, 168.0)]
        self.assertEqual(risks, sorted(risks, reverse=True))

    def test_positive_hours_under_24_risky(self):
        self.assertGreater(_timelock_risk("proxy", 12.0), 50.0)

    def test_48h_moderate_risk(self):
        r = _timelock_risk("proxy", 48.0)
        self.assertGreater(r, 0.0)
        self.assertLess(r, 50.0)

    def test_72h_lower_than_48h(self):
        self.assertLessEqual(_timelock_risk("proxy", 72.0), _timelock_risk("proxy", 48.0))

    def test_168h_lower_than_72h(self):
        self.assertLessEqual(_timelock_risk("proxy", 168.0), _timelock_risk("proxy", 72.0))

    def test_multisig_no_timelock_high_risk(self):
        self.assertEqual(_timelock_risk("multisig", 0.0), 100.0)

    def test_all_non_negative(self):
        for m in ("proxy", "timelock", "multisig", "dao"):
            for h in (0.0, 24.0, 48.0, 168.0):
                self.assertGreaterEqual(_timelock_risk(m, h), 0.0)


# ===========================================================================
# _governance_risk
# ===========================================================================

class TestGovernanceRisk(unittest.TestCase):
    def test_immutable_zero(self):
        self.assertEqual(_governance_risk("immutable", 50.0), 0.0)

    def test_high_participation_lower_risk(self):
        self.assertLess(
            _governance_risk("dao", 40.0),
            _governance_risk("dao", 5.0),
        )

    def test_low_participation_high_risk(self):
        self.assertGreater(_governance_risk("proxy", 0.0), 50.0)

    def test_proxy_higher_than_dao_same_participation(self):
        self.assertGreater(
            _governance_risk("proxy", 20.0),
            _governance_risk("dao", 20.0),
        )

    def test_bounds_non_negative(self):
        for m in ("proxy", "dao", "timelock", "multisig"):
            for p in (0.0, 10.0, 40.0, 100.0):
                self.assertGreaterEqual(_governance_risk(m, p), 0.0)

    def test_bounds_at_most_100(self):
        for m in ("proxy", "dao", "timelock", "multisig"):
            for p in (0.0, 10.0, 40.0, 100.0):
                self.assertLessEqual(_governance_risk(m, p), 100.0)

    def test_dao_40pct_participation_lower_risk(self):
        self.assertLess(_governance_risk("dao", 40.0), _governance_risk("dao", 5.0))

    def test_multisig_riskier_than_dao_same_participation(self):
        self.assertGreater(
            _governance_risk("multisig", 20.0),
            _governance_risk("dao", 20.0),
        )


# ===========================================================================
# _audit_risk
# ===========================================================================

class TestAuditRisk(unittest.TestCase):
    def test_full_coverage_low_risk(self):
        self.assertLessEqual(_audit_risk(100.0), 10.0)

    def test_zero_coverage_high_risk(self):
        self.assertGreaterEqual(_audit_risk(0.0), 80.0)

    def test_monotone_decreasing(self):
        risks = [_audit_risk(c) for c in (0.0, 25.0, 50.0, 75.0, 90.0, 100.0)]
        self.assertEqual(risks, sorted(risks, reverse=True))

    def test_90pct_coverage_low_risk(self):
        self.assertLessEqual(_audit_risk(90.0), 10.0)

    def test_50pct_coverage_moderate(self):
        r = _audit_risk(50.0)
        self.assertGreater(r, 20.0)
        self.assertLess(r, 80.0)

    def test_non_negative(self):
        for c in (0.0, 25.0, 50.0, 75.0, 100.0):
            self.assertGreaterEqual(_audit_risk(c), 0.0)

    def test_at_most_100(self):
        for c in (0.0, 25.0, 50.0, 75.0, 100.0):
            self.assertLessEqual(_audit_risk(c), 100.0)


# ===========================================================================
# _frequency_risk
# ===========================================================================

class TestFrequencyRisk(unittest.TestCase):
    def test_immutable_zero(self):
        self.assertEqual(_frequency_risk("immutable", 10.0), 0.0)

    def test_zero_frequency_low_but_non_zero(self):
        r = _frequency_risk("proxy", 0.0)
        self.assertGreater(r, 0.0)
        self.assertLessEqual(r, 30.0)

    def test_high_frequency_high_risk(self):
        self.assertGreater(_frequency_risk("proxy", 10.0), 80.0)

    def test_monotone_increasing_with_frequency(self):
        risks = [_frequency_risk("proxy", f) for f in (0.0, 1.0, 2.0, 4.0, 8.0)]
        self.assertEqual(risks, sorted(risks))

    def test_multisig_high_freq_high_risk(self):
        self.assertGreater(_frequency_risk("multisig", 8.0), 80.0)

    def test_non_negative(self):
        for m in ("proxy", "multisig", "dao", "timelock"):
            for f in (0.0, 1.0, 5.0):
                self.assertGreaterEqual(_frequency_risk(m, f), 0.0)

    def test_at_most_100(self):
        for f in (0.0, 1.0, 5.0, 100.0):
            self.assertLessEqual(_frequency_risk("proxy", f), 100.0)


# ===========================================================================
# _recency_risk
# ===========================================================================

class TestRecencyRisk(unittest.TestCase):
    def test_immutable_zero(self):
        self.assertEqual(_recency_risk("immutable", 1.0), 0.0)

    def test_never_upgraded_low_moderate(self):
        r = _recency_risk("proxy", -1.0)
        self.assertGreater(r, 0.0)
        self.assertLessEqual(r, 30.0)

    def test_very_recent_high_risk(self):
        self.assertGreaterEqual(_recency_risk("proxy", 1.0), 80.0)

    def test_old_upgrade_low_risk(self):
        self.assertLessEqual(_recency_risk("proxy", 365.0), 10.0)

    def test_monotone_decreasing_with_days(self):
        risks = [_recency_risk("proxy", d) for d in (1.0, 15.0, 60.0, 180.0, 400.0)]
        self.assertEqual(risks, sorted(risks, reverse=True))

    def test_non_negative(self):
        for d in (-1.0, 0.0, 7.0, 30.0, 365.0):
            self.assertGreaterEqual(_recency_risk("proxy", d), 0.0)

    def test_at_most_100(self):
        for d in (0.0, 1.0, 365.0):
            self.assertLessEqual(_recency_risk("proxy", d), 100.0)

    def test_immutable_any_days_zero(self):
        for d in (0.0, 1.0, 100.0, -1.0):
            self.assertEqual(_recency_risk("immutable", d), 0.0)


# ===========================================================================
# _upgrade_risk_score
# ===========================================================================

class TestUpgradeRiskScore(unittest.TestCase):
    def _call(self, mechanism="proxy", tl=0.0, gov=0.0, days=-1.0, audit=0.0, freq=0.0):
        return _upgrade_risk_score(mechanism, tl, gov, days, audit, freq)

    def test_immutable_very_low(self):
        self.assertLessEqual(self._call("immutable", 0.0, 0.0, -1.0, 100.0, 0.0), 20.0)

    def test_worst_case_proxy_very_high(self):
        # proxy, no timelock, no governance, just upgraded, no audit, frequent
        r = self._call("proxy", 0.0, 0.0, 1.0, 0.0, 10.0)
        self.assertGreater(r, 70.0)

    def test_proxy_with_long_timelock_lower(self):
        r_short = self._call("proxy", 0.0, 50.0, 180.0, 80.0, 1.0)
        r_long  = self._call("proxy", 168.0, 50.0, 180.0, 80.0, 1.0)
        self.assertLess(r_long, r_short)

    def test_better_audit_lowers_risk(self):
        r_low  = self._call("proxy", 48.0, 20.0, 90.0, 10.0, 1.0)
        r_high = self._call("proxy", 48.0, 20.0, 90.0, 90.0, 1.0)
        self.assertLess(r_high, r_low)

    def test_higher_participation_lowers_risk(self):
        r_low  = self._call("dao", 48.0, 2.0,  90.0, 80.0, 1.0)
        r_high = self._call("dao", 48.0, 50.0, 90.0, 80.0, 1.0)
        self.assertLess(r_high, r_low)

    def test_bounds_0_to_100(self):
        for mechanism in ("proxy", "immutable", "timelock", "multisig", "dao"):
            r = self._call(mechanism, 48.0, 20.0, 90.0, 80.0, 1.0)
            self.assertGreaterEqual(r, 0.0)
            self.assertLessEqual(r, 100.0)

    def test_weights_sum_to_one(self):
        total = _W_MECHANISM + _W_TIMELOCK + _W_GOVERNANCE + _W_AUDIT + _W_FREQUENCY + _W_RECENCY
        self.assertAlmostEqual(total, 1.0, places=10)

    def test_returns_float(self):
        self.assertIsInstance(self._call(), float)

    def test_immutable_full_audit_very_low(self):
        r = _upgrade_risk_score("immutable", 0.0, 0.0, -1.0, 100.0, 0.0)
        self.assertLessEqual(r, 5.0)


# ===========================================================================
# _governance_quality_score
# ===========================================================================

class TestGovernanceQualityScore(unittest.TestCase):
    def test_immutable_high(self):
        self.assertGreaterEqual(_governance_quality_score("immutable", 0.0), 85.0)

    def test_proxy_low(self):
        self.assertLessEqual(_governance_quality_score("proxy", 0.0), 35.0)

    def test_dao_high_participation_good(self):
        self.assertGreaterEqual(_governance_quality_score("dao", 50.0), 70.0)

    def test_multisig_lower_than_dao(self):
        self.assertLess(
            _governance_quality_score("multisig", 20.0),
            _governance_quality_score("dao", 20.0),
        )

    def test_high_participation_better_than_low(self):
        self.assertGreater(
            _governance_quality_score("dao", 40.0),
            _governance_quality_score("dao", 5.0),
        )

    def test_bounds_0_to_100(self):
        for m in ("proxy", "immutable", "timelock", "multisig", "dao"):
            for p in (0.0, 20.0, 50.0):
                r = _governance_quality_score(m, p)
                self.assertGreaterEqual(r, 0.0)
                self.assertLessEqual(r, 100.0)

    def test_returns_float(self):
        self.assertIsInstance(_governance_quality_score("dao", 20.0), float)

    def test_immutable_same_regardless_of_participation(self):
        r1 = _governance_quality_score("immutable", 0.0)
        r2 = _governance_quality_score("immutable", 50.0)
        self.assertEqual(r1, r2)


# ===========================================================================
# _surprise_upgrade_risk
# ===========================================================================

class TestSurpriseUpgradeRisk(unittest.TestCase):
    def test_immutable_zero(self):
        self.assertEqual(_surprise_upgrade_risk("immutable", 0.0, 5.0), 0.0)

    def test_proxy_no_timelock_high_risk(self):
        self.assertGreater(_surprise_upgrade_risk("proxy", 0.0, 0.0), 60.0)

    def test_long_timelock_reduces_risk(self):
        r_none = _surprise_upgrade_risk("proxy", 0.0, 1.0)
        r_long = _surprise_upgrade_risk("proxy", 168.0, 1.0)
        self.assertLess(r_long, r_none)

    def test_high_frequency_increases_risk(self):
        r_low  = _surprise_upgrade_risk("proxy", 0.0, 1.0)
        r_high = _surprise_upgrade_risk("proxy", 0.0, 10.0)
        self.assertGreater(r_high, r_low)

    def test_dao_lower_than_proxy(self):
        self.assertLess(
            _surprise_upgrade_risk("dao", 0.0, 1.0),
            _surprise_upgrade_risk("proxy", 0.0, 1.0),
        )

    def test_bounds_0_to_100(self):
        for m in ("proxy", "immutable", "timelock", "multisig", "dao"):
            r = _surprise_upgrade_risk(m, 48.0, 2.0)
            self.assertGreaterEqual(r, 0.0)
            self.assertLessEqual(r, 100.0)

    def test_returns_float(self):
        self.assertIsInstance(_surprise_upgrade_risk("proxy", 0.0, 1.0), float)

    def test_multisig_higher_than_dao(self):
        self.assertGreater(
            _surprise_upgrade_risk("multisig", 0.0, 1.0),
            _surprise_upgrade_risk("dao", 0.0, 1.0),
        )

    def test_timelock_48h_lower_than_no_timelock(self):
        self.assertLess(
            _surprise_upgrade_risk("proxy", 48.0, 1.0),
            _surprise_upgrade_risk("proxy", 0.0, 1.0),
        )


# ===========================================================================
# _label
# ===========================================================================

class TestLabel(unittest.TestCase):
    def test_battle_tested_at_zero(self):
        self.assertEqual(_label(0.0), "BATTLE_TESTED")

    def test_battle_tested_at_threshold(self):
        self.assertEqual(_label(_THRESHOLD_BATTLE_TESTED), "BATTLE_TESTED")

    def test_well_governed_above_battle_tested(self):
        self.assertEqual(_label(_THRESHOLD_BATTLE_TESTED + 0.01), "WELL_GOVERNED")

    def test_well_governed_at_threshold(self):
        self.assertEqual(_label(_THRESHOLD_WELL_GOVERNED), "WELL_GOVERNED")

    def test_moderate_risk_above_well_governed(self):
        self.assertEqual(_label(_THRESHOLD_WELL_GOVERNED + 0.01), "MODERATE_RISK")

    def test_moderate_risk_mid(self):
        self.assertEqual(_label(50.0), "MODERATE_RISK")

    def test_high_upgrade_risk_above_moderate(self):
        self.assertEqual(_label(_THRESHOLD_MODERATE_RISK + 0.01), "HIGH_UPGRADE_RISK")

    def test_high_upgrade_risk_at_threshold(self):
        self.assertEqual(_label(_THRESHOLD_HIGH_RISK), "HIGH_UPGRADE_RISK")

    def test_unilateral_control_above_high(self):
        self.assertEqual(_label(_THRESHOLD_HIGH_RISK + 0.01), "UNILATERAL_CONTROL")

    def test_unilateral_control_at_100(self):
        self.assertEqual(_label(100.0), "UNILATERAL_CONTROL")

    def test_all_five_labels_distinct(self):
        labels = {
            _label(10.0),
            _label(30.0),
            _label(50.0),
            _label(70.0),
            _label(90.0),
        }
        self.assertEqual(len(labels), 5)


# ===========================================================================
# analyze()
# ===========================================================================

class TestAnalyze(unittest.TestCase):
    def _immutable(self, **kw):
        defaults = dict(
            upgrade_mechanism="immutable",
            timelock_hours=0.0,
            governance_participation_pct=0.0,
            last_upgrade_days_ago=-1.0,
            audit_coverage_pct=100.0,
            upgrade_frequency_per_year=0.0,
        )
        defaults.update(kw)
        return analyze(**defaults)

    def _worst_proxy(self):
        return analyze(
            upgrade_mechanism="proxy",
            timelock_hours=0.0,
            governance_participation_pct=0.0,
            last_upgrade_days_ago=1.0,
            audit_coverage_pct=0.0,
            upgrade_frequency_per_year=12.0,
        )

    def test_returns_dict(self):
        self.assertIsInstance(analyze("immutable"), dict)

    def test_immutable_battle_tested(self):
        r = self._immutable()
        self.assertEqual(r["label"], "BATTLE_TESTED")

    def test_worst_proxy_very_high_risk(self):
        r = self._worst_proxy()
        self.assertGreater(r["upgrade_risk_score"], 70.0)

    def test_immutable_surprise_risk_zero(self):
        r = self._immutable()
        self.assertEqual(r["surprise_upgrade_risk"], 0.0)

    def test_all_required_keys_present(self):
        r = analyze("timelock", timelock_hours=48.0, governance_participation_pct=20.0,
                    last_upgrade_days_ago=90.0, audit_coverage_pct=80.0,
                    upgrade_frequency_per_year=1.0)
        for key in (
            "upgrade_mechanism", "timelock_hours", "governance_participation_pct",
            "last_upgrade_days_ago", "audit_coverage_pct", "upgrade_frequency_per_year",
            "mechanism_risk", "timelock_risk", "governance_risk", "audit_risk",
            "frequency_risk", "recency_risk",
            "upgrade_risk_score", "governance_quality_score", "surprise_upgrade_risk",
            "label", "timestamp",
        ):
            self.assertIn(key, r)

    def test_mechanism_normalised_to_lowercase(self):
        r = analyze("PROXY")
        self.assertEqual(r["upgrade_mechanism"], "proxy")

    def test_risk_score_between_0_and_100(self):
        r = analyze("proxy", timelock_hours=48.0, governance_participation_pct=20.0,
                    last_upgrade_days_ago=90.0, audit_coverage_pct=80.0,
                    upgrade_frequency_per_year=1.0)
        self.assertGreaterEqual(r["upgrade_risk_score"], 0.0)
        self.assertLessEqual(r["upgrade_risk_score"], 100.0)

    def test_governance_quality_between_0_and_100(self):
        r = analyze("dao", governance_participation_pct=30.0)
        self.assertGreaterEqual(r["governance_quality_score"], 0.0)
        self.assertLessEqual(r["governance_quality_score"], 100.0)

    def test_surprise_upgrade_risk_between_0_and_100(self):
        r = analyze("proxy", timelock_hours=0.0, upgrade_frequency_per_year=5.0)
        self.assertGreaterEqual(r["surprise_upgrade_risk"], 0.0)
        self.assertLessEqual(r["surprise_upgrade_risk"], 100.0)

    def test_timestamp_is_float(self):
        self.assertIsInstance(analyze("immutable")["timestamp"], float)

    def test_timestamp_positive(self):
        self.assertGreater(analyze("immutable")["timestamp"], 0.0)

    def test_inputs_stored_in_result(self):
        r = analyze("timelock", timelock_hours=72.0, governance_participation_pct=25.0,
                    last_upgrade_days_ago=60.0, audit_coverage_pct=85.0,
                    upgrade_frequency_per_year=2.0)
        self.assertEqual(r["upgrade_mechanism"], "timelock")
        self.assertAlmostEqual(r["timelock_hours"], 72.0)
        self.assertAlmostEqual(r["governance_participation_pct"], 25.0)

    def test_dao_better_gov_quality_than_proxy(self):
        r_dao   = analyze("dao",   governance_participation_pct=30.0)
        r_proxy = analyze("proxy", governance_participation_pct=30.0)
        self.assertGreater(r_dao["governance_quality_score"], r_proxy["governance_quality_score"])

    def test_proxy_higher_risk_than_dao(self):
        r_dao   = analyze("dao",   timelock_hours=48.0, audit_coverage_pct=80.0)
        r_proxy = analyze("proxy", timelock_hours=48.0, audit_coverage_pct=80.0)
        self.assertGreater(r_proxy["upgrade_risk_score"], r_dao["upgrade_risk_score"])

    def test_longer_timelock_lowers_risk(self):
        r_short = analyze("proxy", timelock_hours=0.0, audit_coverage_pct=80.0)
        r_long  = analyze("proxy", timelock_hours=168.0, audit_coverage_pct=80.0)
        self.assertLess(r_long["upgrade_risk_score"], r_short["upgrade_risk_score"])

    def test_higher_audit_lowers_risk(self):
        r_low  = analyze("proxy", timelock_hours=48.0, audit_coverage_pct=10.0)
        r_high = analyze("proxy", timelock_hours=48.0, audit_coverage_pct=90.0)
        self.assertLess(r_high["upgrade_risk_score"], r_low["upgrade_risk_score"])

    def test_label_type_is_str(self):
        self.assertIsInstance(analyze("dao")["label"], str)

    def test_component_risks_non_negative(self):
        r = self._worst_proxy()
        for key in ("mechanism_risk", "timelock_risk", "governance_risk",
                    "audit_risk", "frequency_risk", "recency_risk"):
            self.assertGreaterEqual(r[key], 0.0, msg=key)

    def test_component_risks_at_most_100(self):
        r = self._worst_proxy()
        for key in ("mechanism_risk", "timelock_risk", "governance_risk",
                    "audit_risk", "frequency_risk", "recency_risk"):
            self.assertLessEqual(r[key], 100.0, msg=key)

    def test_all_mechanisms_return_valid_label(self):
        valid = {"BATTLE_TESTED", "WELL_GOVERNED", "MODERATE_RISK", "HIGH_UPGRADE_RISK", "UNILATERAL_CONTROL"}
        for m in ("proxy", "immutable", "timelock", "multisig", "dao"):
            r = analyze(m, audit_coverage_pct=80.0)
            self.assertIn(r["label"], valid)

    def test_result_json_serialisable(self):
        r = analyze("timelock", timelock_hours=48.0, governance_participation_pct=20.0,
                    last_upgrade_days_ago=90.0, audit_coverage_pct=80.0,
                    upgrade_frequency_per_year=1.0)
        try:
            json.dumps(r)
        except TypeError as e:
            self.fail(f"Result not JSON serializable: {e}")


# ===========================================================================
# ProtocolDeFiProtocolUpgradeRiskAnalyzer class
# ===========================================================================

class TestAnalyzerClass(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolDeFiProtocolUpgradeRiskAnalyzer()

    def test_instantiation(self):
        self.assertIsInstance(self.analyzer, ProtocolDeFiProtocolUpgradeRiskAnalyzer)

    def test_analyze_returns_dict(self):
        r = self.analyzer.analyze("immutable")
        self.assertIsInstance(r, dict)

    def test_analyze_immutable_battle_tested(self):
        r = self.analyzer.analyze("immutable", audit_coverage_pct=100.0)
        self.assertEqual(r["label"], "BATTLE_TESTED")

    def test_analyze_proxy_higher_risk_than_immutable(self):
        r_im = self.analyzer.analyze("immutable", audit_coverage_pct=100.0)
        r_pr = self.analyzer.analyze("proxy", audit_coverage_pct=100.0)
        self.assertGreater(r_pr["upgrade_risk_score"], r_im["upgrade_risk_score"])

    def test_analyze_matches_module_level_analyze(self):
        r1 = self.analyzer.analyze("timelock", timelock_hours=48.0,
                                   governance_participation_pct=20.0)
        r2 = analyze("timelock", timelock_hours=48.0, governance_participation_pct=20.0)
        self.assertEqual(r1["upgrade_risk_score"], r2["upgrade_risk_score"])
        self.assertEqual(r1["label"], r2["label"])

    def test_analyze_all_mechanisms(self):
        for m in ("proxy", "immutable", "timelock", "multisig", "dao"):
            r = self.analyzer.analyze(m)
            self.assertIn("upgrade_risk_score", r)

    def test_analyze_case_insensitive(self):
        r = self.analyzer.analyze("PROXY")
        self.assertEqual(r["upgrade_mechanism"], "proxy")

    def test_analyze_surprise_risk_zero_immutable(self):
        r = self.analyzer.analyze("immutable")
        self.assertEqual(r["surprise_upgrade_risk"], 0.0)

    def test_multiple_calls_independent(self):
        r1 = self.analyzer.analyze("proxy")
        r2 = self.analyzer.analyze("immutable")
        self.assertNotEqual(r1["upgrade_risk_score"], r2["upgrade_risk_score"])


# ===========================================================================
# log_result()
# ===========================================================================

class TestLogResult(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp()

    def _log_path(self):
        return os.path.join(self._dir, "protocol_upgrade_risk_log.json")

    def _run_and_log(self, mechanism="timelock", **kw):
        r = analyze(mechanism, **kw)
        log_result(r, data_dir=self._dir)
        return r

    def test_creates_file(self):
        self._run_and_log()
        self.assertTrue(os.path.isfile(self._log_path()))

    def test_file_is_valid_json(self):
        self._run_and_log()
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_one_entry_after_one_call(self):
        self._run_and_log()
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_accumulates_entries(self):
        for _ in range(5):
            self._run_and_log()
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_capped(self):
        for _ in range(_LOG_RING_SIZE + 15):
            self._run_and_log()
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertEqual(len(data), _LOG_RING_SIZE)

    def test_entry_has_required_keys(self):
        self._run_and_log()
        with open(self._log_path()) as f:
            entry = json.load(f)[0]
        for key in (
            "timestamp", "upgrade_mechanism", "timelock_hours",
            "upgrade_risk_score", "governance_quality_score",
            "surprise_upgrade_risk", "label",
        ):
            self.assertIn(key, entry)

    def test_label_is_string(self):
        self._run_and_log()
        with open(self._log_path()) as f:
            entry = json.load(f)[0]
        self.assertIsInstance(entry["label"], str)

    def test_corrupt_file_overwritten(self):
        with open(self._log_path(), "w") as f:
            f.write("{{BAD JSON}")
        self._run_and_log()
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_creates_nested_data_dir(self):
        subdir = os.path.join(self._dir, "nested", "logs")
        r = analyze("immutable")
        log_result(r, data_dir=subdir)
        self.assertTrue(os.path.isdir(subdir))

    def test_entry_mechanism_correct(self):
        self._run_and_log("proxy")
        with open(self._log_path()) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["upgrade_mechanism"], "proxy")


if __name__ == "__main__":
    unittest.main()
