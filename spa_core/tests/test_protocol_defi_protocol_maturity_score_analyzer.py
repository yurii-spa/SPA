"""
Tests for MP-1073 ProtocolDeFiProtocolMaturityScoreAnalyzer.
Run: python3 -m unittest spa_core.tests.test_protocol_defi_protocol_maturity_score_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.protocol_defi_protocol_maturity_score_analyzer import (
    ProtocolDeFiProtocolMaturityScoreAnalyzer,
    _validate_input,
    _audit_sub,
    _bug_bounty_sub,
    _incident_sub,
    _loss_ratio_sub,
    _security_score,
    _tvl_abs_sub,
    _tvl_retention_sub,
    _chain_sub,
    _users_sub,
    _adoption_score,
    _age_sub,
    _commits_sub,
    _dao_sub,
    _mcap_sub,
    _development_score,
    _composite_score,
    _maturity_label,
    _analyze_protocol,
    _atomic_write,
    _init_log,
    _append_log,
    _iso_now,
    LOG_MAX_ENTRIES,
    REQUIRED_FIELDS,
    analyze,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_proto(**kwargs):
    """Return a valid protocol dict, overriding any supplied kwargs."""
    base = {
        "protocol_name":          "TestProtocol",
        "launch_date_days_ago":   500,
        "tvl_usd":                50_000_000.0,
        "tvl_peak_usd":           60_000_000.0,
        "audit_count":            2,
        "bug_bounty_usd":         500_000.0,
        "num_security_incidents": 0,
        "total_loss_usd":         0.0,
        "chain_count":            3,
        "unique_users_30d":       5_000,
        "github_commits_90d":     40,
        "has_dao":                True,
        "token_market_cap_usd":   200_000_000.0,
    }
    base.update(kwargs)
    return base


def _battle_tested_proto():
    return _make_proto(
        protocol_name="AaveV3",
        launch_date_days_ago=1200,
        tvl_usd=5_000_000_000.0,
        tvl_peak_usd=6_000_000_000.0,
        audit_count=5,
        bug_bounty_usd=2_000_000.0,
        num_security_incidents=0,
        total_loss_usd=0.0,
        chain_count=8,
        unique_users_30d=500_000,
        github_commits_90d=150,
        has_dao=True,
        token_market_cap_usd=2_000_000_000.0,
    )


def _experimental_proto():
    return _make_proto(
        protocol_name="NewFi",
        launch_date_days_ago=20,
        tvl_usd=50_000.0,
        tvl_peak_usd=60_000.0,
        audit_count=0,
        bug_bounty_usd=0.0,
        num_security_incidents=3,
        total_loss_usd=30_000.0,
        chain_count=1,
        unique_users_30d=20,
        github_commits_90d=0,
        has_dao=False,
        token_market_cap_usd=0.0,
    )


# ===========================================================================
# 1. Validation — missing fields
# ===========================================================================

class TestValidationMissingFields(unittest.TestCase):

    def test_all_required_present_passes(self):
        _validate_input(_make_proto())

    def test_missing_protocol_name(self):
        p = _make_proto(); del p["protocol_name"]
        with self.assertRaises(ValueError): _validate_input(p)

    def test_missing_launch_date_days_ago(self):
        p = _make_proto(); del p["launch_date_days_ago"]
        with self.assertRaises(ValueError): _validate_input(p)

    def test_missing_tvl_usd(self):
        p = _make_proto(); del p["tvl_usd"]
        with self.assertRaises(ValueError): _validate_input(p)

    def test_missing_tvl_peak_usd(self):
        p = _make_proto(); del p["tvl_peak_usd"]
        with self.assertRaises(ValueError): _validate_input(p)

    def test_missing_audit_count(self):
        p = _make_proto(); del p["audit_count"]
        with self.assertRaises(ValueError): _validate_input(p)

    def test_missing_bug_bounty_usd(self):
        p = _make_proto(); del p["bug_bounty_usd"]
        with self.assertRaises(ValueError): _validate_input(p)

    def test_missing_num_security_incidents(self):
        p = _make_proto(); del p["num_security_incidents"]
        with self.assertRaises(ValueError): _validate_input(p)

    def test_missing_total_loss_usd(self):
        p = _make_proto(); del p["total_loss_usd"]
        with self.assertRaises(ValueError): _validate_input(p)

    def test_missing_chain_count(self):
        p = _make_proto(); del p["chain_count"]
        with self.assertRaises(ValueError): _validate_input(p)

    def test_missing_unique_users_30d(self):
        p = _make_proto(); del p["unique_users_30d"]
        with self.assertRaises(ValueError): _validate_input(p)

    def test_missing_github_commits_90d(self):
        p = _make_proto(); del p["github_commits_90d"]
        with self.assertRaises(ValueError): _validate_input(p)

    def test_missing_has_dao(self):
        p = _make_proto(); del p["has_dao"]
        with self.assertRaises(ValueError): _validate_input(p)

    def test_missing_token_market_cap_usd(self):
        p = _make_proto(); del p["token_market_cap_usd"]
        with self.assertRaises(ValueError): _validate_input(p)


# ===========================================================================
# 2. Validation — field values
# ===========================================================================

class TestValidationFieldValues(unittest.TestCase):

    def test_empty_protocol_name_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(protocol_name=""))

    def test_whitespace_protocol_name_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(protocol_name="   "))

    def test_negative_launch_date_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(launch_date_days_ago=-1))

    def test_zero_launch_date_valid(self):
        _validate_input(_make_proto(launch_date_days_ago=0))

    def test_negative_tvl_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(tvl_usd=-1.0))

    def test_zero_tvl_valid(self):
        _validate_input(_make_proto(tvl_usd=0.0))

    def test_negative_tvl_peak_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(tvl_peak_usd=-1.0))

    def test_negative_audit_count_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(audit_count=-1))

    def test_float_audit_count_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(audit_count=1.5))

    def test_bool_audit_count_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(audit_count=True))

    def test_zero_audit_count_valid(self):
        _validate_input(_make_proto(audit_count=0))

    def test_negative_bug_bounty_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(bug_bounty_usd=-1.0))

    def test_negative_incidents_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(num_security_incidents=-1))

    def test_float_incidents_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(num_security_incidents=0.5))

    def test_bool_incidents_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(num_security_incidents=False))

    def test_negative_total_loss_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(total_loss_usd=-100.0))

    def test_negative_chain_count_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(chain_count=-1))

    def test_float_chain_count_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(chain_count=2.0))

    def test_zero_chain_count_valid(self):
        _validate_input(_make_proto(chain_count=0))

    def test_negative_users_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(unique_users_30d=-1))

    def test_float_users_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(unique_users_30d=100.0))

    def test_negative_commits_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(github_commits_90d=-5))

    def test_has_dao_must_be_bool(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(has_dao=1))

    def test_has_dao_false_valid(self):
        _validate_input(_make_proto(has_dao=False))

    def test_negative_market_cap_raises(self):
        with self.assertRaises(ValueError): _validate_input(_make_proto(token_market_cap_usd=-1.0))

    def test_zero_market_cap_valid(self):
        _validate_input(_make_proto(token_market_cap_usd=0.0))


# ===========================================================================
# 3. Security sub-scores
# ===========================================================================

class TestAuditSub(unittest.TestCase):

    def test_zero_audits_returns_zero(self):
        self.assertEqual(_audit_sub(0), 0.0)

    def test_one_audit_returns_35(self):
        self.assertEqual(_audit_sub(1), 35.0)

    def test_two_audits_returns_60(self):
        self.assertEqual(_audit_sub(2), 60.0)

    def test_three_audits_returns_80(self):
        self.assertEqual(_audit_sub(3), 80.0)

    def test_four_audits_returns_100(self):
        self.assertEqual(_audit_sub(4), 100.0)

    def test_ten_audits_returns_100(self):
        self.assertEqual(_audit_sub(10), 100.0)

    def test_monotone_increase(self):
        scores = [_audit_sub(i) for i in range(5)]
        for i in range(len(scores) - 1):
            self.assertLessEqual(scores[i], scores[i + 1])


class TestBugBountySub(unittest.TestCase):

    def test_zero_returns_zero(self):
        self.assertEqual(_bug_bounty_sub(0), 0.0)

    def test_below_10k_returns_20(self):
        self.assertEqual(_bug_bounty_sub(5_000), 20.0)

    def test_exact_10k_returns_50(self):
        self.assertEqual(_bug_bounty_sub(10_000), 50.0)

    def test_below_100k_returns_50(self):
        self.assertEqual(_bug_bounty_sub(50_000), 50.0)

    def test_exact_100k_returns_75(self):
        self.assertEqual(_bug_bounty_sub(100_000), 75.0)

    def test_below_1m_returns_75(self):
        self.assertEqual(_bug_bounty_sub(500_000), 75.0)

    def test_exact_1m_returns_100(self):
        self.assertEqual(_bug_bounty_sub(1_000_000), 100.0)

    def test_above_1m_returns_100(self):
        self.assertEqual(_bug_bounty_sub(5_000_000), 100.0)


class TestIncidentSub(unittest.TestCase):

    def test_zero_incidents_returns_100(self):
        self.assertEqual(_incident_sub(0), 100.0)

    def test_one_incident_returns_65(self):
        self.assertEqual(_incident_sub(1), 65.0)

    def test_two_incidents_returns_35(self):
        self.assertEqual(_incident_sub(2), 35.0)

    def test_three_incidents_returns_zero(self):
        self.assertEqual(_incident_sub(3), 0.0)

    def test_ten_incidents_returns_zero(self):
        self.assertEqual(_incident_sub(10), 0.0)

    def test_monotone_decrease(self):
        prev = _incident_sub(0)
        for i in range(1, 5):
            curr = _incident_sub(i)
            self.assertLessEqual(curr, prev)
            prev = curr


class TestLossRatioSub(unittest.TestCase):

    def test_zero_loss_returns_100(self):
        self.assertEqual(_loss_ratio_sub(0.0, 1_000_000.0), 100.0)

    def test_below_1pct_returns_80(self):
        self.assertEqual(_loss_ratio_sub(5_000.0, 1_000_000.0), 80.0)

    def test_exact_1pct_returns_55(self):
        self.assertEqual(_loss_ratio_sub(10_000.0, 1_000_000.0), 55.0)

    def test_below_5pct_returns_55(self):
        self.assertEqual(_loss_ratio_sub(40_000.0, 1_000_000.0), 55.0)

    def test_exact_5pct_returns_25(self):
        self.assertEqual(_loss_ratio_sub(50_000.0, 1_000_000.0), 25.0)

    def test_below_20pct_returns_25(self):
        self.assertEqual(_loss_ratio_sub(100_000.0, 1_000_000.0), 25.0)

    def test_exact_20pct_returns_zero(self):
        self.assertEqual(_loss_ratio_sub(200_000.0, 1_000_000.0), 0.0)

    def test_zero_tvl_uses_floor(self):
        # total_loss=0 → 0% → 100
        result = _loss_ratio_sub(0.0, 0.0)
        self.assertEqual(result, 100.0)


# ===========================================================================
# 4. Adoption sub-scores
# ===========================================================================

class TestTvlAbsSub(unittest.TestCase):

    def test_below_1m(self):
        self.assertEqual(_tvl_abs_sub(500_000), 15.0)

    def test_exact_1m(self):
        self.assertEqual(_tvl_abs_sub(1_000_000), 40.0)

    def test_below_10m(self):
        self.assertEqual(_tvl_abs_sub(5_000_000), 40.0)

    def test_exact_10m(self):
        self.assertEqual(_tvl_abs_sub(10_000_000), 65.0)

    def test_below_100m(self):
        self.assertEqual(_tvl_abs_sub(50_000_000), 65.0)

    def test_exact_100m(self):
        self.assertEqual(_tvl_abs_sub(100_000_000), 85.0)

    def test_below_1b(self):
        self.assertEqual(_tvl_abs_sub(500_000_000), 85.0)

    def test_exact_1b(self):
        self.assertEqual(_tvl_abs_sub(1_000_000_000), 100.0)

    def test_above_1b(self):
        self.assertEqual(_tvl_abs_sub(5_000_000_000), 100.0)


class TestTvlRetentionSub(unittest.TestCase):

    def test_below_30pct_returns_zero(self):
        self.assertEqual(_tvl_retention_sub(200_000, 1_000_000), 0.0)

    def test_below_50pct_returns_25(self):
        self.assertEqual(_tvl_retention_sub(400_000, 1_000_000), 25.0)

    def test_below_70pct_returns_50(self):
        self.assertEqual(_tvl_retention_sub(600_000, 1_000_000), 50.0)

    def test_below_90pct_returns_75(self):
        self.assertEqual(_tvl_retention_sub(800_000, 1_000_000), 75.0)

    def test_above_90pct_returns_100(self):
        self.assertEqual(_tvl_retention_sub(950_000, 1_000_000), 100.0)

    def test_equal_to_peak_returns_100(self):
        self.assertEqual(_tvl_retention_sub(1_000_000, 1_000_000), 100.0)

    def test_zero_peak_returns_neutral(self):
        self.assertEqual(_tvl_retention_sub(1_000_000, 0), 50.0)


class TestChainSub(unittest.TestCase):

    def test_zero_chains_returns_20(self):
        self.assertEqual(_chain_sub(0), 20.0)

    def test_one_chain_returns_20(self):
        self.assertEqual(_chain_sub(1), 20.0)

    def test_two_chains_returns_50(self):
        self.assertEqual(_chain_sub(2), 50.0)

    def test_three_chains_returns_70(self):
        self.assertEqual(_chain_sub(3), 70.0)

    def test_four_chains_returns_70(self):
        self.assertEqual(_chain_sub(4), 70.0)

    def test_five_chains_returns_100(self):
        self.assertEqual(_chain_sub(5), 100.0)

    def test_ten_chains_returns_100(self):
        self.assertEqual(_chain_sub(10), 100.0)


class TestUsersSub(unittest.TestCase):

    def test_below_100_returns_10(self):
        self.assertEqual(_users_sub(50), 10.0)

    def test_zero_users_returns_10(self):
        self.assertEqual(_users_sub(0), 10.0)

    def test_exact_100_returns_35(self):
        self.assertEqual(_users_sub(100), 35.0)

    def test_below_1k_returns_35(self):
        self.assertEqual(_users_sub(500), 35.0)

    def test_exact_1k_returns_65(self):
        self.assertEqual(_users_sub(1_000), 65.0)

    def test_below_10k_returns_65(self):
        self.assertEqual(_users_sub(5_000), 65.0)

    def test_exact_10k_returns_85(self):
        self.assertEqual(_users_sub(10_000), 85.0)

    def test_exact_100k_returns_100(self):
        self.assertEqual(_users_sub(100_000), 100.0)


# ===========================================================================
# 5. Development sub-scores
# ===========================================================================

class TestAgeSub(unittest.TestCase):

    def test_below_90_days_returns_5(self):
        self.assertEqual(_age_sub(30), 5.0)

    def test_exact_90_days_returns_20(self):
        self.assertEqual(_age_sub(90), 20.0)

    def test_below_180_returns_20(self):
        self.assertEqual(_age_sub(150), 20.0)

    def test_exact_180_returns_45(self):
        self.assertEqual(_age_sub(180), 45.0)

    def test_below_365_returns_45(self):
        self.assertEqual(_age_sub(300), 45.0)

    def test_exact_365_returns_70(self):
        self.assertEqual(_age_sub(365), 70.0)

    def test_below_730_returns_70(self):
        self.assertEqual(_age_sub(500), 70.0)

    def test_exact_730_returns_85(self):
        self.assertEqual(_age_sub(730), 85.0)

    def test_below_1095_returns_85(self):
        self.assertEqual(_age_sub(900), 85.0)

    def test_exact_1095_returns_100(self):
        self.assertEqual(_age_sub(1095), 100.0)

    def test_very_old_returns_100(self):
        self.assertEqual(_age_sub(3000), 100.0)


class TestCommitsSub(unittest.TestCase):

    def test_zero_commits_returns_zero(self):
        self.assertEqual(_commits_sub(0), 0.0)

    def test_below_5_returns_20(self):
        self.assertEqual(_commits_sub(3), 20.0)

    def test_exact_5_returns_45(self):
        self.assertEqual(_commits_sub(5), 45.0)

    def test_below_20_returns_45(self):
        self.assertEqual(_commits_sub(10), 45.0)

    def test_exact_20_returns_70(self):
        self.assertEqual(_commits_sub(20), 70.0)

    def test_below_50_returns_70(self):
        self.assertEqual(_commits_sub(30), 70.0)

    def test_exact_50_returns_85(self):
        self.assertEqual(_commits_sub(50), 85.0)

    def test_below_100_returns_85(self):
        self.assertEqual(_commits_sub(75), 85.0)

    def test_exact_100_returns_100(self):
        self.assertEqual(_commits_sub(100), 100.0)

    def test_above_100_returns_100(self):
        self.assertEqual(_commits_sub(500), 100.0)


class TestDaoSub(unittest.TestCase):

    def test_has_dao_true_returns_100(self):
        self.assertEqual(_dao_sub(True), 100.0)

    def test_has_dao_false_returns_20(self):
        self.assertEqual(_dao_sub(False), 20.0)


class TestMcapSub(unittest.TestCase):

    def test_zero_returns_15(self):
        self.assertEqual(_mcap_sub(0), 15.0)

    def test_below_1m_returns_15(self):
        self.assertEqual(_mcap_sub(500_000), 15.0)

    def test_exact_1m_returns_35(self):
        self.assertEqual(_mcap_sub(1_000_000), 35.0)

    def test_below_10m_returns_35(self):
        self.assertEqual(_mcap_sub(5_000_000), 35.0)

    def test_exact_10m_returns_60(self):
        self.assertEqual(_mcap_sub(10_000_000), 60.0)

    def test_exact_100m_returns_85(self):
        self.assertEqual(_mcap_sub(100_000_000), 85.0)

    def test_exact_1b_returns_100(self):
        self.assertEqual(_mcap_sub(1_000_000_000), 100.0)


# ===========================================================================
# 6. Composite score and label
# ===========================================================================

class TestCompositeScore(unittest.TestCase):

    def test_all_hundred_returns_100(self):
        self.assertAlmostEqual(_composite_score(100.0, 100.0, 100.0), 100.0, places=2)

    def test_all_zero_returns_zero(self):
        self.assertAlmostEqual(_composite_score(0.0, 0.0, 0.0), 0.0, places=2)

    def test_weights_sum_to_correct_result(self):
        # 0.40*80 + 0.35*60 + 0.25*40 = 32 + 21 + 10 = 63
        result = _composite_score(80.0, 60.0, 40.0)
        self.assertAlmostEqual(result, 63.0, places=4)

    def test_result_bounded_0_to_100(self):
        result = _composite_score(100.0, 100.0, 100.0)
        self.assertGreaterEqual(result, 0.0)
        self.assertLessEqual(result, 100.0)


class TestMaturityLabel(unittest.TestCase):

    def test_below_20_experimental(self):
        self.assertEqual(_maturity_label(0.0), "EXPERIMENTAL")

    def test_19_99_experimental(self):
        self.assertEqual(_maturity_label(19.99), "EXPERIMENTAL")

    def test_exactly_20_early_stage(self):
        self.assertEqual(_maturity_label(20.0), "EARLY_STAGE")

    def test_30_early_stage(self):
        self.assertEqual(_maturity_label(30.0), "EARLY_STAGE")

    def test_39_99_early_stage(self):
        self.assertEqual(_maturity_label(39.99), "EARLY_STAGE")

    def test_exactly_40_established(self):
        self.assertEqual(_maturity_label(40.0), "ESTABLISHED")

    def test_50_established(self):
        self.assertEqual(_maturity_label(50.0), "ESTABLISHED")

    def test_59_99_established(self):
        self.assertEqual(_maturity_label(59.99), "ESTABLISHED")

    def test_exactly_60_mature(self):
        self.assertEqual(_maturity_label(60.0), "MATURE")

    def test_70_mature(self):
        self.assertEqual(_maturity_label(70.0), "MATURE")

    def test_79_99_mature(self):
        self.assertEqual(_maturity_label(79.99), "MATURE")

    def test_exactly_80_battle_tested(self):
        self.assertEqual(_maturity_label(80.0), "BATTLE_TESTED")

    def test_100_battle_tested(self):
        self.assertEqual(_maturity_label(100.0), "BATTLE_TESTED")


# ===========================================================================
# 7. Analyzer class — single protocol
# ===========================================================================

class TestAnalyzerSingleProtocol(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiProtocolMaturityScoreAnalyzer()

    def test_output_has_all_required_keys(self):
        result = self.analyzer.analyze(_make_proto())
        for key in ("security_score", "adoption_score", "development_score",
                    "maturity_composite_score", "maturity_label",
                    "protocol_name", "analyzed_at"):
            self.assertIn(key, result)

    def test_protocol_name_preserved(self):
        r = self.analyzer.analyze(_make_proto(protocol_name="Compound V3"))
        self.assertEqual(r["protocol_name"], "Compound V3")

    def test_battle_tested_scenario(self):
        r = self.analyzer.analyze(_battle_tested_proto())
        self.assertEqual(r["maturity_label"], "BATTLE_TESTED")

    def test_experimental_scenario(self):
        r = self.analyzer.analyze(_experimental_proto())
        self.assertEqual(r["maturity_label"], "EXPERIMENTAL")

    def test_security_score_in_range(self):
        r = self.analyzer.analyze(_make_proto())
        self.assertGreaterEqual(r["security_score"], 0.0)
        self.assertLessEqual(r["security_score"], 100.0)

    def test_adoption_score_in_range(self):
        r = self.analyzer.analyze(_make_proto())
        self.assertGreaterEqual(r["adoption_score"], 0.0)
        self.assertLessEqual(r["adoption_score"], 100.0)

    def test_development_score_in_range(self):
        r = self.analyzer.analyze(_make_proto())
        self.assertGreaterEqual(r["development_score"], 0.0)
        self.assertLessEqual(r["development_score"], 100.0)

    def test_composite_score_in_range(self):
        r = self.analyzer.analyze(_make_proto())
        self.assertGreaterEqual(r["maturity_composite_score"], 0.0)
        self.assertLessEqual(r["maturity_composite_score"], 100.0)

    def test_analyzed_at_is_string(self):
        r = self.analyzer.analyze(_make_proto())
        self.assertIsInstance(r["analyzed_at"], str)

    def test_analyzed_at_iso_format(self):
        r = self.analyzer.analyze(_make_proto())
        self.assertRegex(r["analyzed_at"], r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

    def test_more_audits_higher_security(self):
        r0 = self.analyzer.analyze(_make_proto(audit_count=0))
        r4 = self.analyzer.analyze(_make_proto(audit_count=4))
        self.assertGreater(r4["security_score"], r0["security_score"])

    def test_incidents_reduce_security(self):
        r0 = self.analyzer.analyze(_make_proto(num_security_incidents=0))
        r3 = self.analyzer.analyze(_make_proto(num_security_incidents=3))
        self.assertGreater(r0["security_score"], r3["security_score"])

    def test_larger_tvl_higher_adoption(self):
        r1 = self.analyzer.analyze(_make_proto(tvl_usd=100_000.0))
        r2 = self.analyzer.analyze(_make_proto(tvl_usd=10_000_000_000.0))
        self.assertGreater(r2["adoption_score"], r1["adoption_score"])

    def test_more_chains_higher_adoption(self):
        r1 = self.analyzer.analyze(_make_proto(chain_count=1))
        r2 = self.analyzer.analyze(_make_proto(chain_count=10))
        self.assertGreater(r2["adoption_score"], r1["adoption_score"])

    def test_older_protocol_higher_dev_score(self):
        r1 = self.analyzer.analyze(_make_proto(launch_date_days_ago=10))
        r2 = self.analyzer.analyze(_make_proto(launch_date_days_ago=2000))
        self.assertGreater(r2["development_score"], r1["development_score"])

    def test_dao_increases_dev_score(self):
        r_no_dao = self.analyzer.analyze(_make_proto(has_dao=False))
        r_dao    = self.analyzer.analyze(_make_proto(has_dao=True))
        self.assertGreater(r_dao["development_score"], r_no_dao["development_score"])

    def test_module_level_analyze_function(self):
        r = analyze(_make_proto())
        self.assertIn("maturity_label", r)

    def test_module_level_analyze_config_none(self):
        r = analyze(_make_proto(), config=None)
        self.assertIn("maturity_label", r)

    def test_label_in_valid_set(self):
        for label in ("EXPERIMENTAL", "EARLY_STAGE", "ESTABLISHED", "MATURE", "BATTLE_TESTED"):
            result = _maturity_label({"EXPERIMENTAL": 10, "EARLY_STAGE": 30,
                                      "ESTABLISHED": 50, "MATURE": 70,
                                      "BATTLE_TESTED": 90}[label])
            self.assertEqual(result, label)


# ===========================================================================
# 8. Batch analysis
# ===========================================================================

class TestAnalyzerBatch(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiProtocolMaturityScoreAnalyzer()

    def test_batch_empty_list_raises(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze_batch([])

    def test_batch_non_list_raises(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze_batch("not-a-list")

    def test_batch_single_protocol(self):
        result = self.analyzer.analyze_batch([_make_proto()])
        self.assertEqual(result["count"], 1)

    def test_batch_two_protocols(self):
        result = self.analyzer.analyze_batch([_battle_tested_proto(), _experimental_proto()])
        self.assertEqual(result["count"], 2)

    def test_batch_top_protocol_has_highest_composite(self):
        protos = [_experimental_proto(), _make_proto(), _battle_tested_proto()]
        result = self.analyzer.analyze_batch(protos)
        self.assertEqual(result["top_protocol"], "AaveV3")

    def test_batch_bottom_protocol_has_lowest_composite(self):
        protos = [_experimental_proto(), _make_proto(), _battle_tested_proto()]
        result = self.analyzer.analyze_batch(protos)
        self.assertEqual(result["bottom_protocol"], "NewFi")

    def test_batch_avg_composite_is_mean(self):
        p1 = _experimental_proto()
        p2 = _battle_tested_proto()
        result = self.analyzer.analyze_batch([p1, p2])
        r1 = _analyze_protocol(p1)
        r2 = _analyze_protocol(p2)
        expected = round(
            (r1["maturity_composite_score"] + r2["maturity_composite_score"]) / 2, 4
        )
        self.assertAlmostEqual(result["avg_composite_score"], expected, places=3)

    def test_batch_battle_tested_count(self):
        result = self.analyzer.analyze_batch([_battle_tested_proto(), _experimental_proto()])
        self.assertEqual(result["battle_tested_count"], 1)

    def test_batch_experimental_count(self):
        result = self.analyzer.analyze_batch([_battle_tested_proto(), _experimental_proto()])
        self.assertEqual(result["experimental_count"], 1)

    def test_batch_has_analyzed_at(self):
        result = self.analyzer.analyze_batch([_make_proto()])
        self.assertIn("analyzed_at", result)

    def test_batch_all_protocols_have_analyzed_at(self):
        result = self.analyzer.analyze_batch([_make_proto(), _experimental_proto()])
        for p in result["protocols"]:
            self.assertIn("analyzed_at", p)


# ===========================================================================
# 9. Log helpers
# ===========================================================================

class TestLogHelpers(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "maturity_log.json")

    def _write_log(self, entries):
        with open(self.log_path, "w") as fh:
            json.dump(entries, fh)

    def test_init_log_missing_file_returns_empty(self):
        result = _init_log(os.path.join(self.tmpdir, "nonexistent.json"))
        self.assertEqual(result, [])

    def test_init_log_valid_file(self):
        self._write_log([{"ts": "2026-01-01T00:00:00Z"}])
        result = _init_log(self.log_path)
        self.assertEqual(len(result), 1)

    def test_init_log_corrupted_file_returns_empty(self):
        with open(self.log_path, "w") as fh:
            fh.write("{{BROKEN JSON")
        result = _init_log(self.log_path)
        self.assertEqual(result, [])

    def test_init_log_dict_returns_empty(self):
        with open(self.log_path, "w") as fh:
            json.dump({"not": "list"}, fh)
        result = _init_log(self.log_path)
        self.assertEqual(result, [])

    def test_append_log_creates_file(self):
        r = _analyze_protocol(_make_proto())
        r["analyzed_at"] = _iso_now()
        _append_log(r, self.log_path)
        self.assertTrue(os.path.exists(self.log_path))

    def test_append_log_increments_count(self):
        r = _analyze_protocol(_make_proto())
        r["analyzed_at"] = _iso_now()
        _append_log(r, self.log_path)
        _append_log(r, self.log_path)
        entries = _init_log(self.log_path)
        self.assertEqual(len(entries), 2)

    def test_append_log_caps_at_max_entries(self):
        r = _analyze_protocol(_make_proto())
        r["analyzed_at"] = _iso_now()
        for _ in range(LOG_MAX_ENTRIES + 15):
            _append_log(r, self.log_path)
        entries = _init_log(self.log_path)
        self.assertLessEqual(len(entries), LOG_MAX_ENTRIES)

    def test_log_max_entries_is_100(self):
        self.assertEqual(LOG_MAX_ENTRIES, 100)

    def test_atomic_write_creates_file(self):
        path = os.path.join(self.tmpdir, "out.json")
        _atomic_write(path, [{"key": "value"}])
        self.assertTrue(os.path.exists(path))

    def test_atomic_write_valid_json(self):
        path = os.path.join(self.tmpdir, "out2.json")
        data = [{"a": 1}, {"b": 2}]
        _atomic_write(path, data)
        with open(path, "r") as fh:
            loaded = json.load(fh)
        self.assertEqual(loaded, data)

    def test_iso_now_format(self):
        self.assertRegex(_iso_now(), r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

    def test_iso_now_length(self):
        self.assertEqual(len(_iso_now()), 20)

    def test_required_fields_count(self):
        self.assertEqual(len(REQUIRED_FIELDS), 13)

    def test_required_fields_has_protocol_name(self):
        self.assertIn("protocol_name", REQUIRED_FIELDS)


# ===========================================================================
# 10. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiProtocolMaturityScoreAnalyzer()

    def test_tvl_exceeds_peak_retention_100(self):
        # TVL > peak → retention ratio > 1 → should still give 100
        r = self.analyzer.analyze(_make_proto(tvl_usd=200_000_000.0,
                                               tvl_peak_usd=100_000_000.0))
        self.assertIn("maturity_label", r)

    def test_zero_tvl_zero_loss_no_crash(self):
        r = self.analyzer.analyze(_make_proto(tvl_usd=0.0, total_loss_usd=0.0))
        self.assertIn("maturity_composite_score", r)

    def test_very_new_no_commits_no_dao_low_dev_score(self):
        r = _analyze_protocol(_make_proto(
            launch_date_days_ago=5,
            github_commits_90d=0,
            has_dao=False,
            token_market_cap_usd=0.0,
        ))
        # age=5→5; commits=0→0; dao=F→20; mcap=0→15 → 1.5+0+4+3=8.5
        self.assertAlmostEqual(r["development_score"], 8.5, places=2)

    def test_perfect_security_zero_loss_many_audits(self):
        r = _analyze_protocol(_make_proto(
            audit_count=10,
            bug_bounty_usd=5_000_000.0,
            num_security_incidents=0,
            total_loss_usd=0.0,
        ))
        self.assertAlmostEqual(r["security_score"], 100.0, places=2)

    def test_minimum_composite_near_zero(self):
        r = _analyze_protocol(_experimental_proto())
        self.assertLess(r["maturity_composite_score"], 20.0)

    def test_validate_raises_on_empty_dict(self):
        with self.assertRaises(ValueError):
            _validate_input({})

    def test_float_launch_date_valid(self):
        # float is allowed for launch_date_days_ago
        _validate_input(_make_proto(launch_date_days_ago=365.5))

    def test_maturity_label_from_full_analysis(self):
        r = self.analyzer.analyze(_battle_tested_proto())
        self.assertIn(r["maturity_label"],
                      {"EXPERIMENTAL", "EARLY_STAGE", "ESTABLISHED", "MATURE", "BATTLE_TESTED"})


if __name__ == "__main__":
    unittest.main()
