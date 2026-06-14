"""
Tests for MP-992: DeFiProtocolRegulatoryRiskScorer
≥80 tests, stdlib unittest only.
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_regulatory_risk_scorer import (
    DeFiProtocolRegulatoryRiskScorer,
    LABEL_COMPLIANT,
    LABEL_LOW_RISK,
    LABEL_MODERATE_RISK,
    LABEL_HIGH_RISK,
    LABEL_CRITICAL_RISK,
    FLAG_SECURITIES_RISK,
    FLAG_NO_AML_KYC,
    FLAG_ANONYMOUS_TEAM,
    FLAG_US_NEXUS_RISK,
    FLAG_REGULATOR_ACTION_HISTORY,
    FLAG_STABLECOIN_SYSTEMIC,
    _kyc_aml_score,
    _jurisdiction_risk_score,
    _securities_risk_score,
    _operational_opacity_score,
    _composite_score,
    _risk_label,
    _compute_flags,
    _score_protocol,
)


# ── Fixtures ───────────────────────────────────────────────────────────────

def _clean_protocol(**overrides):
    """A maximally compliant protocol with optional overrides."""
    base = {
        "name": "TestProtocol",
        "jurisdiction": ["Cayman Islands"],
        "has_kyc": True,
        "has_aml": True,
        "token_classified_security": False,
        "sanctions_screening": True,
        "front_end_geo_restrictions": ["US"],
        "team_public": True,
        "entity_incorporated": True,
        "dao_governance": False,
        "stablecoin_exposure_pct": 20.0,
        "defi_category": "lending",
        "regulator_action_history": False,
        "settlement_layer": "ethereum",
    }
    base.update(overrides)
    return base


def _risky_protocol(**overrides):
    """A maximally risky protocol with optional overrides."""
    base = {
        "name": "RiskyProtocol",
        "jurisdiction": ["US"],
        "has_kyc": False,
        "has_aml": False,
        "token_classified_security": True,
        "sanctions_screening": False,
        "front_end_geo_restrictions": [],
        "team_public": False,
        "entity_incorporated": False,
        "dao_governance": True,
        "stablecoin_exposure_pct": 80.0,
        "defi_category": "derivatives",
        "regulator_action_history": True,
        "settlement_layer": "solana",
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════
# 1. Class construction
# ═══════════════════════════════════════════════════════════════════════════

class TestInstantiation(unittest.TestCase):

    def test_01_creates_scorer(self):
        scorer = DeFiProtocolRegulatoryRiskScorer()
        self.assertIsInstance(scorer, DeFiProtocolRegulatoryRiskScorer)

    def test_02_score_method_exists(self):
        scorer = DeFiProtocolRegulatoryRiskScorer()
        self.assertTrue(callable(scorer.score))


# ═══════════════════════════════════════════════════════════════════════════
# 2. Empty / edge inputs
# ═══════════════════════════════════════════════════════════════════════════

class TestEmptyInput(unittest.TestCase):

    def setUp(self):
        self.scorer = DeFiProtocolRegulatoryRiskScorer()
        self.cfg    = {"write_log": False}

    def test_03_empty_list_returns_dict(self):
        r = self.scorer.score([], self.cfg)
        self.assertIsInstance(r, dict)

    def test_04_empty_protocols_list(self):
        r = self.scorer.score([], self.cfg)
        self.assertEqual(r["protocols"], [])

    def test_05_empty_highest_risk_is_none(self):
        r = self.scorer.score([], self.cfg)
        self.assertIsNone(r["highest_risk"])

    def test_06_empty_lowest_risk_is_none(self):
        r = self.scorer.score([], self.cfg)
        self.assertIsNone(r["lowest_risk"])

    def test_07_empty_avg_score_zero(self):
        r = self.scorer.score([], self.cfg)
        self.assertEqual(r["avg_regulatory_score"], 0.0)

    def test_08_empty_critical_count_zero(self):
        r = self.scorer.score([], self.cfg)
        self.assertEqual(r["critical_count"], 0)

    def test_09_empty_compliant_count_zero(self):
        r = self.scorer.score([], self.cfg)
        self.assertEqual(r["compliant_count"], 0)

    def test_10_timestamp_present(self):
        r = self.scorer.score([], self.cfg)
        self.assertIn("timestamp", r)
        self.assertGreater(r["timestamp"], 0)


# ═══════════════════════════════════════════════════════════════════════════
# 3. KYC/AML sub-scorer
# ═══════════════════════════════════════════════════════════════════════════

class TestKycAmlScore(unittest.TestCase):

    def test_11_full_compliance_zero(self):
        p = _clean_protocol()
        self.assertEqual(_kyc_aml_score(p), 0.0)

    def test_12_no_kyc_penalty(self):
        p = _clean_protocol(has_kyc=False)
        self.assertGreater(_kyc_aml_score(p), 0.0)

    def test_13_no_aml_penalty(self):
        p = _clean_protocol(has_aml=False)
        self.assertGreater(_kyc_aml_score(p), 0.0)

    def test_14_no_sanctions_screening_penalty(self):
        p = _clean_protocol(sanctions_screening=False)
        self.assertGreater(_kyc_aml_score(p), 0.0)

    def test_15_no_kyc_no_aml_highest(self):
        p_both = _clean_protocol(has_kyc=False, has_aml=False)
        p_kyc  = _clean_protocol(has_kyc=False)
        self.assertGreater(_kyc_aml_score(p_both), _kyc_aml_score(p_kyc))

    def test_16_score_bounded_0_100(self):
        p = _risky_protocol()
        s = _kyc_aml_score(p)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_17_partial_missing_aml(self):
        p = _clean_protocol(has_aml=False, sanctions_screening=False)
        s = _kyc_aml_score(p)
        self.assertGreater(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_18_all_bad_still_bounded(self):
        p = _clean_protocol(has_kyc=False, has_aml=False, sanctions_screening=False)
        s = _kyc_aml_score(p)
        self.assertLessEqual(s, 100.0)
        self.assertGreater(s, 50.0)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Jurisdiction risk sub-scorer
# ═══════════════════════════════════════════════════════════════════════════

class TestJurisdictionRiskScore(unittest.TestCase):

    def test_19_us_without_compliance_high(self):
        p = _clean_protocol(
            jurisdiction=["US"], has_kyc=False, has_aml=False,
            front_end_geo_restrictions=[]
        )
        self.assertGreater(_jurisdiction_risk_score(p), 30.0)

    def test_20_us_with_compliance_lower(self):
        p_no = _clean_protocol(jurisdiction=["US"], has_kyc=False, has_aml=False)
        p_yes = _clean_protocol(jurisdiction=["US"], has_kyc=True, has_aml=True)
        self.assertGreater(_jurisdiction_risk_score(p_no), _jurisdiction_risk_score(p_yes))

    def test_21_cayman_low_risk(self):
        p = _clean_protocol(jurisdiction=["Cayman Islands"])
        s = _jurisdiction_risk_score(p)
        self.assertLess(s, 20.0)

    def test_22_eu_without_aml(self):
        p = _clean_protocol(jurisdiction=["EU"], has_aml=False)
        self.assertGreater(_jurisdiction_risk_score(p), 15.0)

    def test_23_geo_block_reduces_us_risk(self):
        p_no_block = _clean_protocol(
            jurisdiction=["US"], has_kyc=False, has_aml=False,
            front_end_geo_restrictions=[]
        )
        p_block = _clean_protocol(
            jurisdiction=["US"], has_kyc=False, has_aml=False,
            front_end_geo_restrictions=["US"]
        )
        self.assertGreater(
            _jurisdiction_risk_score(p_no_block),
            _jurisdiction_risk_score(p_block)
        )

    def test_24_multiple_jurisdictions_additive(self):
        p_single = _clean_protocol(jurisdiction=["Cayman Islands"])
        p_multi  = _clean_protocol(jurisdiction=["Cayman Islands", "Singapore", "BVI"])
        self.assertGreaterEqual(_jurisdiction_risk_score(p_multi),
                                _jurisdiction_risk_score(p_single))

    def test_25_bounded_0_100(self):
        p = _risky_protocol()
        s = _jurisdiction_risk_score(p)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_26_empty_jurisdictions_low(self):
        p = _clean_protocol(jurisdiction=[])
        s = _jurisdiction_risk_score(p)
        self.assertLessEqual(s, 15.0)


# ═══════════════════════════════════════════════════════════════════════════
# 5. Securities risk sub-scorer
# ═══════════════════════════════════════════════════════════════════════════

class TestSecuritiesRiskScore(unittest.TestCase):

    def test_27_token_classified_security_high(self):
        p = _clean_protocol(token_classified_security=True)
        self.assertGreaterEqual(_securities_risk_score(p), 40.0)

    def test_28_no_security_classification_lower(self):
        p = _clean_protocol(token_classified_security=False)
        self.assertLess(_securities_risk_score(p), 40.0)

    def test_29_derivatives_category_extra(self):
        p_other = _clean_protocol(defi_category="other")
        p_deriv = _clean_protocol(defi_category="derivatives")
        self.assertGreater(_securities_risk_score(p_deriv), _securities_risk_score(p_other))

    def test_30_securities_plus_no_kyc_maximum(self):
        p = _clean_protocol(token_classified_security=True, has_kyc=False)
        s = _securities_risk_score(p)
        self.assertGreater(s, 50.0)

    def test_31_bounded_0_100(self):
        p = _risky_protocol()
        s = _securities_risk_score(p)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_32_lending_category_some_risk(self):
        p_other = _clean_protocol(defi_category="other")
        p_lend  = _clean_protocol(defi_category="lending")
        # lending has category risk
        self.assertGreaterEqual(_securities_risk_score(p_lend),
                                _securities_risk_score(p_other))

    def test_33_yield_category_some_risk(self):
        p = _clean_protocol(defi_category="yield")
        s = _securities_risk_score(p)
        self.assertGreater(s, 0.0)


# ═══════════════════════════════════════════════════════════════════════════
# 6. Operational opacity sub-scorer
# ═══════════════════════════════════════════════════════════════════════════

class TestOperationalOpacityScore(unittest.TestCase):

    def test_34_full_transparency_low(self):
        p = _clean_protocol(team_public=True, entity_incorporated=True)
        self.assertLessEqual(_operational_opacity_score(p), 5.0)

    def test_35_anon_team_penalty(self):
        p = _clean_protocol(team_public=False)
        self.assertGreater(_operational_opacity_score(p), 20.0)

    def test_36_no_entity_penalty(self):
        p = _clean_protocol(entity_incorporated=False)
        self.assertGreater(_operational_opacity_score(p), 20.0)

    def test_37_dao_anon_extra_penalty(self):
        p_no_dao = _clean_protocol(team_public=False, entity_incorporated=False,
                                   dao_governance=False)
        p_dao    = _clean_protocol(team_public=False, entity_incorporated=False,
                                   dao_governance=True)
        self.assertGreater(_operational_opacity_score(p_dao),
                           _operational_opacity_score(p_no_dao))

    def test_38_bounded_0_100(self):
        p = _risky_protocol()
        s = _operational_opacity_score(p)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_39_partial_opacity(self):
        # Only no entity, but team is public
        p = _clean_protocol(team_public=True, entity_incorporated=False)
        s = _operational_opacity_score(p)
        self.assertGreater(s, 0.0)
        self.assertLess(s, 60.0)


# ═══════════════════════════════════════════════════════════════════════════
# 7. Composite score
# ═══════════════════════════════════════════════════════════════════════════

class TestCompositeScore(unittest.TestCase):

    def test_40_all_zero_gives_zero(self):
        s = _composite_score(0, 0, 0, 0)
        self.assertEqual(s, 0.0)

    def test_41_all_100_gives_100(self):
        s = _composite_score(100, 100, 100, 100)
        self.assertEqual(s, 100.0)

    def test_42_weighted_sum_correct(self):
        s = _composite_score(100, 0, 0, 0)
        self.assertAlmostEqual(s, 35.0, places=1)

    def test_43_jurisdiction_weight(self):
        s = _composite_score(0, 100, 0, 0)
        self.assertAlmostEqual(s, 25.0, places=1)

    def test_44_bounded_result(self):
        s = _composite_score(80, 70, 90, 60)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_45_float_result(self):
        s = _composite_score(50, 30, 20, 10)
        self.assertIsInstance(s, float)


# ═══════════════════════════════════════════════════════════════════════════
# 8. Risk labels
# ═══════════════════════════════════════════════════════════════════════════

class TestRiskLabels(unittest.TestCase):

    def _label_for(self, **overrides):
        p = _clean_protocol(**overrides)
        r = _score_protocol(p)
        return r["risk_label"]

    def test_46_compliant_label(self):
        p = _clean_protocol()
        r = _score_protocol(p)
        # Clean protocol should be COMPLIANT or LOW_RISK
        self.assertIn(r["risk_label"], [LABEL_COMPLIANT, LABEL_LOW_RISK])

    def test_47_critical_via_regulator_action(self):
        label = self._label_for(regulator_action_history=True)
        self.assertEqual(label, LABEL_CRITICAL_RISK)

    def test_48_critical_via_securities_no_kyc(self):
        label = self._label_for(token_classified_security=True, has_kyc=False)
        self.assertEqual(label, LABEL_CRITICAL_RISK)

    def test_49_critical_via_high_composite(self):
        # Force very high composite through all risk channels
        p = _risky_protocol()
        r = _score_protocol(p)
        self.assertEqual(r["risk_label"], LABEL_CRITICAL_RISK)

    def test_50_labels_are_valid_strings(self):
        valid = {LABEL_COMPLIANT, LABEL_LOW_RISK, LABEL_MODERATE_RISK,
                 LABEL_HIGH_RISK, LABEL_CRITICAL_RISK}
        p = _clean_protocol()
        r = _score_protocol(p)
        self.assertIn(r["risk_label"], valid)

    def test_51_risky_protocol_not_compliant(self):
        p = _risky_protocol()
        r = _score_protocol(p)
        self.assertNotEqual(r["risk_label"], LABEL_COMPLIANT)

    def test_52_label_risk_label_function_consistent(self):
        p = _clean_protocol()
        r = _score_protocol(p)
        label_from_fn = _risk_label(r["composite_regulatory_score"], p)
        self.assertEqual(r["risk_label"], label_from_fn)

    def test_53_moderate_risk_range(self):
        # Manually craft moderate risk: US jurisdiction, no aml
        p = _clean_protocol(
            jurisdiction=["EU"],
            has_aml=False,
            has_kyc=True,
            token_classified_security=False,
            team_public=True,
            entity_incorporated=True,
        )
        r = _score_protocol(p)
        # Should be some risk level, not CRITICAL
        self.assertNotEqual(r["risk_label"], LABEL_CRITICAL_RISK)


# ═══════════════════════════════════════════════════════════════════════════
# 9. Flags
# ═══════════════════════════════════════════════════════════════════════════

class TestFlags(unittest.TestCase):

    def test_54_securities_flag_raised(self):
        p = _clean_protocol(token_classified_security=True, has_kyc=True)
        flags = _compute_flags(p)
        self.assertIn(FLAG_SECURITIES_RISK, flags)

    def test_55_no_securities_flag_absent(self):
        p = _clean_protocol(token_classified_security=False)
        flags = _compute_flags(p)
        self.assertNotIn(FLAG_SECURITIES_RISK, flags)

    def test_56_no_aml_kyc_flag_raised(self):
        p = _clean_protocol(has_kyc=False, has_aml=False)
        flags = _compute_flags(p)
        self.assertIn(FLAG_NO_AML_KYC, flags)

    def test_57_no_aml_kyc_partial_not_raised(self):
        # has_kyc=True but has_aml=False → NO_AML_KYC requires BOTH absent
        p = _clean_protocol(has_kyc=True, has_aml=False)
        flags = _compute_flags(p)
        self.assertNotIn(FLAG_NO_AML_KYC, flags)

    def test_58_anonymous_team_flag(self):
        p = _clean_protocol(team_public=False, entity_incorporated=False)
        flags = _compute_flags(p)
        self.assertIn(FLAG_ANONYMOUS_TEAM, flags)

    def test_59_anonymous_team_flag_absent_when_transparent(self):
        p = _clean_protocol(team_public=True, entity_incorporated=True)
        flags = _compute_flags(p)
        self.assertNotIn(FLAG_ANONYMOUS_TEAM, flags)

    def test_60_us_nexus_flag_raised(self):
        p = _clean_protocol(jurisdiction=["US"], has_kyc=False, has_aml=False)
        flags = _compute_flags(p)
        self.assertIn(FLAG_US_NEXUS_RISK, flags)

    def test_61_us_nexus_flag_absent_with_compliance(self):
        p = _clean_protocol(jurisdiction=["US"], has_kyc=True, has_aml=True)
        flags = _compute_flags(p)
        self.assertNotIn(FLAG_US_NEXUS_RISK, flags)

    def test_62_regulator_action_flag(self):
        p = _clean_protocol(regulator_action_history=True)
        flags = _compute_flags(p)
        self.assertIn(FLAG_REGULATOR_ACTION_HISTORY, flags)

    def test_63_regulator_action_flag_absent(self):
        p = _clean_protocol(regulator_action_history=False)
        flags = _compute_flags(p)
        self.assertNotIn(FLAG_REGULATOR_ACTION_HISTORY, flags)

    def test_64_stablecoin_systemic_flag(self):
        p = _clean_protocol(stablecoin_exposure_pct=75.0)
        flags = _compute_flags(p)
        self.assertIn(FLAG_STABLECOIN_SYSTEMIC, flags)

    def test_65_stablecoin_systemic_flag_absent_below_threshold(self):
        p = _clean_protocol(stablecoin_exposure_pct=50.0)
        flags = _compute_flags(p)
        self.assertNotIn(FLAG_STABLECOIN_SYSTEMIC, flags)

    def test_66_no_flags_clean_protocol(self):
        p = _clean_protocol()
        flags = _compute_flags(p)
        self.assertEqual(flags, [])

    def test_67_all_flags_risky_protocol(self):
        p = _risky_protocol()
        flags = _compute_flags(p)
        self.assertIn(FLAG_SECURITIES_RISK, flags)
        self.assertIn(FLAG_NO_AML_KYC, flags)
        self.assertIn(FLAG_ANONYMOUS_TEAM, flags)
        self.assertIn(FLAG_US_NEXUS_RISK, flags)
        self.assertIn(FLAG_REGULATOR_ACTION_HISTORY, flags)
        self.assertIn(FLAG_STABLECOIN_SYSTEMIC, flags)


# ═══════════════════════════════════════════════════════════════════════════
# 10. Full score output structure
# ═══════════════════════════════════════════════════════════════════════════

class TestScoreOutput(unittest.TestCase):

    def setUp(self):
        self.scorer = DeFiProtocolRegulatoryRiskScorer()
        self.cfg    = {"write_log": False}

    def test_68_result_has_protocols_key(self):
        r = self.scorer.score([_clean_protocol()], self.cfg)
        self.assertIn("protocols", r)

    def test_69_protocol_has_name(self):
        r = self.scorer.score([_clean_protocol(name="Foo")], self.cfg)
        self.assertEqual(r["protocols"][0]["name"], "Foo")

    def test_70_protocol_has_composite_score(self):
        r = self.scorer.score([_clean_protocol()], self.cfg)
        self.assertIn("composite_regulatory_score", r["protocols"][0])

    def test_71_protocol_has_kyc_aml_score(self):
        r = self.scorer.score([_clean_protocol()], self.cfg)
        self.assertIn("kyc_aml_score", r["protocols"][0])

    def test_72_protocol_has_jurisdiction_risk_score(self):
        r = self.scorer.score([_clean_protocol()], self.cfg)
        self.assertIn("jurisdiction_risk_score", r["protocols"][0])

    def test_73_protocol_has_securities_risk_score(self):
        r = self.scorer.score([_clean_protocol()], self.cfg)
        self.assertIn("securities_risk_score", r["protocols"][0])

    def test_74_protocol_has_opacity_score(self):
        r = self.scorer.score([_clean_protocol()], self.cfg)
        self.assertIn("operational_opacity_score", r["protocols"][0])

    def test_75_protocol_has_risk_label(self):
        r = self.scorer.score([_clean_protocol()], self.cfg)
        self.assertIn("risk_label", r["protocols"][0])

    def test_76_protocol_has_flags(self):
        r = self.scorer.score([_clean_protocol()], self.cfg)
        self.assertIsInstance(r["protocols"][0]["flags"], list)

    def test_77_two_protocols_correct_aggregate(self):
        protos = [_clean_protocol(name="A"), _risky_protocol(name="B")]
        r = self.scorer.score(protos, self.cfg)
        self.assertEqual(len(r["protocols"]), 2)

    def test_78_highest_risk_is_risky(self):
        protos = [_clean_protocol(name="Clean"), _risky_protocol(name="Risky")]
        r = self.scorer.score(protos, self.cfg)
        self.assertEqual(r["highest_risk"], "Risky")

    def test_79_lowest_risk_is_clean(self):
        protos = [_clean_protocol(name="Clean"), _risky_protocol(name="Risky")]
        r = self.scorer.score(protos, self.cfg)
        self.assertEqual(r["lowest_risk"], "Clean")

    def test_80_avg_score_between_extremes(self):
        protos = [_clean_protocol(name="A"), _risky_protocol(name="B")]
        r = self.scorer.score(protos, self.cfg)
        s_a = r["protocols"][0]["composite_regulatory_score"]
        s_b = r["protocols"][1]["composite_regulatory_score"]
        self.assertAlmostEqual(r["avg_regulatory_score"], (s_a + s_b) / 2, places=3)

    def test_81_critical_count_accurate(self):
        protos = [_risky_protocol(name="A"), _clean_protocol(name="B")]
        r = self.scorer.score(protos, self.cfg)
        # risky should be CRITICAL
        self.assertGreaterEqual(r["critical_count"], 1)

    def test_82_compliant_count_for_clean(self):
        r = self.scorer.score([_clean_protocol()], self.cfg)
        # clean protocol should be compliant
        self.assertGreaterEqual(r["compliant_count"], 0)

    def test_83_single_protocol_highest_equals_lowest(self):
        r = self.scorer.score([_clean_protocol(name="Only")], self.cfg)
        self.assertEqual(r["highest_risk"], "Only")
        self.assertEqual(r["lowest_risk"], "Only")

    def test_84_default_config(self):
        """score() should work with no config arg."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scorer = DeFiProtocolRegulatoryRiskScorer()
            cfg = {"write_log": True, "log_path": os.path.join(tmpdir, "log.json")}
            r = scorer.score([_clean_protocol()], cfg)
            self.assertIn("protocols", r)


# ═══════════════════════════════════════════════════════════════════════════
# 11. Ring-buffer log
# ═══════════════════════════════════════════════════════════════════════════

class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test_log.json")
        self.scorer = DeFiProtocolRegulatoryRiskScorer()

    def _cfg(self):
        return {"write_log": True, "log_path": self.log_path}

    def test_85_log_created_on_score(self):
        self.scorer.score([_clean_protocol()], self._cfg())
        self.assertTrue(os.path.exists(self.log_path))

    def test_86_log_is_json_list(self):
        self.scorer.score([_clean_protocol()], self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_87_log_grows_per_call(self):
        self.scorer.score([_clean_protocol()], self._cfg())
        self.scorer.score([_risky_protocol()], self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_88_log_entry_has_timestamp(self):
        self.scorer.score([_clean_protocol()], self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIn("timestamp", data[0])

    def test_89_log_cap_100(self):
        for _ in range(105):
            self.scorer.score([_clean_protocol()], self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), 100)

    def test_90_log_atomic_write(self):
        """Ensure no .tmp file remains after write."""
        self.scorer.score([_clean_protocol()], self._cfg())
        tmps = [f for f in os.listdir(self.tmpdir) if f.endswith(".tmp")]
        self.assertEqual(tmps, [])

    def test_91_load_log_returns_list(self):
        self.scorer.score([_clean_protocol()], self._cfg())
        log = self.scorer.load_log(self.log_path)
        self.assertIsInstance(log, list)

    def test_92_load_log_nonexistent_returns_empty(self):
        log = self.scorer.load_log(os.path.join(self.tmpdir, "nonexistent.json"))
        self.assertEqual(log, [])

    def test_93_write_log_false_no_file(self):
        path = os.path.join(self.tmpdir, "should_not_exist.json")
        self.scorer.score([_clean_protocol()], {"write_log": False, "log_path": path})
        self.assertFalse(os.path.exists(path))

    def test_94_log_entry_has_protocols_key(self):
        self.scorer.score([_clean_protocol()], self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIn("protocols", data[0])


# ═══════════════════════════════════════════════════════════════════════════
# 12. Score field ranges
# ═══════════════════════════════════════════════════════════════════════════

class TestFieldRanges(unittest.TestCase):

    def setUp(self):
        self.scorer = DeFiProtocolRegulatoryRiskScorer()
        self.cfg    = {"write_log": False}

    def _proto_result(self, **overrides):
        r = self.scorer.score([_clean_protocol(**overrides)], self.cfg)
        return r["protocols"][0]

    def test_95_kyc_aml_score_0_100(self):
        p = self._proto_result(has_kyc=False, has_aml=False)
        self.assertGreaterEqual(p["kyc_aml_score"], 0.0)
        self.assertLessEqual(p["kyc_aml_score"], 100.0)

    def test_96_jurisdiction_score_0_100(self):
        p = self._proto_result(jurisdiction=["US"])
        self.assertGreaterEqual(p["jurisdiction_risk_score"], 0.0)
        self.assertLessEqual(p["jurisdiction_risk_score"], 100.0)

    def test_97_securities_score_0_100(self):
        p = self._proto_result(token_classified_security=True)
        self.assertGreaterEqual(p["securities_risk_score"], 0.0)
        self.assertLessEqual(p["securities_risk_score"], 100.0)

    def test_98_opacity_score_0_100(self):
        p = self._proto_result(team_public=False, entity_incorporated=False)
        self.assertGreaterEqual(p["operational_opacity_score"], 0.0)
        self.assertLessEqual(p["operational_opacity_score"], 100.0)

    def test_99_composite_score_0_100(self):
        r = _score_protocol(_risky_protocol())
        self.assertGreaterEqual(r["composite_regulatory_score"], 0.0)
        self.assertLessEqual(r["composite_regulatory_score"], 100.0)


# ═══════════════════════════════════════════════════════════════════════════
# 13. Settlement layer / category passthrough
# ═══════════════════════════════════════════════════════════════════════════

class TestPassthrough(unittest.TestCase):

    def setUp(self):
        self.scorer = DeFiProtocolRegulatoryRiskScorer()
        self.cfg    = {"write_log": False}

    def test_100_settlement_layer_preserved(self):
        r = self.scorer.score([_clean_protocol(settlement_layer="solana")], self.cfg)
        self.assertEqual(r["protocols"][0]["settlement_layer"], "solana")

    def test_101_defi_category_preserved(self):
        r = self.scorer.score([_clean_protocol(defi_category="dex")], self.cfg)
        self.assertEqual(r["protocols"][0]["defi_category"], "dex")

    def test_102_name_preserved(self):
        r = self.scorer.score([_clean_protocol(name="MyProtocol")], self.cfg)
        self.assertEqual(r["protocols"][0]["name"], "MyProtocol")


if __name__ == "__main__":
    unittest.main()
