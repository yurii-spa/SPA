"""Unit tests for spa_core.analytics.protocol_maturity_scorer (MP-804).

Pure stdlib unittest only — no pytest, no numpy, no external deps.
File I/O tests use tempfile so real data/ is never touched.

Run:
    python3 -m unittest spa_core.tests.test_protocol_maturity_scorer -v
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

import spa_core.analytics.protocol_maturity_scorer as pms
from spa_core.analytics.protocol_maturity_scorer import (
    MAX_ENTRIES,
    _age_score,
    _audit_score,
    _build_key_risks,
    _build_key_strengths,
    _incident_score,
    _maturity_tier,
    _team_score,
    _activity_score,
    analyze,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _metrics(
    age_days: int = 400,
    audit_count: int = 3,
    last_audit_days_ago: int = 60,
    incident_count: int = 0,
    total_loss_usd: float = 0.0,
    tvl_usd: float = 100_000_000,
    team_doxxed: bool = True,
    has_bug_bounty: bool = True,
    governance_token: bool = True,
    on_chain_tx_30d: int = 10_000,
) -> dict:
    return {
        "age_days": age_days,
        "audit_count": audit_count,
        "last_audit_days_ago": last_audit_days_ago,
        "incident_count": incident_count,
        "total_loss_usd": total_loss_usd,
        "tvl_usd": tvl_usd,
        "team_doxxed": team_doxxed,
        "has_bug_bounty": has_bug_bounty,
        "governance_token": governance_token,
        "on_chain_tx_30d": on_chain_tx_30d,
    }


# ---------------------------------------------------------------------------
# 1. _age_score  (pure function, 0–25)
# ---------------------------------------------------------------------------

class TestAgeScore(unittest.TestCase):

    def test_age_0_returns_5(self):
        self.assertEqual(_age_score(0), 5)

    def test_age_89_returns_5(self):
        self.assertEqual(_age_score(89), 5)

    def test_age_90_returns_10(self):
        self.assertEqual(_age_score(90), 10)

    def test_age_179_returns_10(self):
        self.assertEqual(_age_score(179), 10)

    def test_age_180_returns_15(self):
        self.assertEqual(_age_score(180), 15)

    def test_age_364_returns_15(self):
        self.assertEqual(_age_score(364), 15)

    def test_age_365_returns_20(self):
        self.assertEqual(_age_score(365), 20)

    def test_age_729_returns_20(self):
        self.assertEqual(_age_score(729), 20)

    def test_age_730_returns_25(self):
        self.assertEqual(_age_score(730), 25)

    def test_age_1000_returns_25(self):
        self.assertEqual(_age_score(1000), 25)

    def test_age_score_is_int(self):
        self.assertIsInstance(_age_score(500), int)


# ---------------------------------------------------------------------------
# 2. _audit_score  (pure function, 0–25)
# ---------------------------------------------------------------------------

class TestAuditScore(unittest.TestCase):

    def test_no_audits_recent(self):
        """0 audits, 0 days ago → 0."""
        self.assertEqual(_audit_score(0, 0), 0)

    def test_three_audits_recent(self):
        """3 audits, 60 days ago → 3*5 - (60//180)*5 = 15 - 0 = 15."""
        self.assertEqual(_audit_score(3, 60), 15)

    def test_five_audits_recent(self):
        """5 audits, 0 days → 25."""
        self.assertEqual(_audit_score(5, 0), 25)

    def test_six_audits_capped_at_25(self):
        """6 audits, 0 days → 30 → capped 25."""
        self.assertEqual(_audit_score(6, 0), 25)

    def test_penalty_for_staleness(self):
        """5 audits, 360 days → 25 - (360//180)*5 = 25-10 = 15."""
        self.assertEqual(_audit_score(5, 360), 15)

    def test_heavy_penalty_floors_at_zero(self):
        """1 audit, 540 days → 5 - (540//180)*5 = 5-15 = -10 → 0."""
        self.assertEqual(_audit_score(1, 540), 0)

    def test_exact_180_days_penalty(self):
        """180//180 = 1; 3 audits, 180 days → 15 - 5 = 10."""
        self.assertEqual(_audit_score(3, 180), 10)

    def test_179_days_no_penalty(self):
        """179//180 = 0; penalty = 0."""
        self.assertEqual(_audit_score(3, 179), 15)

    def test_audit_score_is_int(self):
        self.assertIsInstance(_audit_score(3, 60), int)

    def test_never_negative(self):
        self.assertGreaterEqual(_audit_score(0, 99999), 0)


# ---------------------------------------------------------------------------
# 3. _incident_score  (pure function, 0–25)
# ---------------------------------------------------------------------------

class TestIncidentScore(unittest.TestCase):

    def test_zero_incidents_no_loss(self):
        self.assertEqual(_incident_score(0, 0.0, 1_000_000), 25)

    def test_one_incident_no_material_loss(self):
        """25 - 8 = 17."""
        self.assertEqual(_incident_score(1, 0.0, 1_000_000), 17)

    def test_two_incidents_no_material_loss(self):
        """25 - 16 = 9."""
        self.assertEqual(_incident_score(2, 0.0, 1_000_000), 9)

    def test_three_incidents_no_material_loss(self):
        """25 - 24 = 1."""
        self.assertEqual(_incident_score(3, 0.0, 1_000_000), 1)

    def test_four_incidents_floors_at_zero(self):
        """25 - 32 = -7 → 0."""
        self.assertEqual(_incident_score(4, 0.0, 1_000_000), 0)

    def test_material_loss_extra_penalty(self):
        """1 incident + loss > 10% TVL: 25 - 8 - 10 = 7."""
        self.assertEqual(_incident_score(1, 200_000, 1_000_000), 7)

    def test_material_loss_threshold_exact(self):
        """loss = tvl*0.1 exactly — NOT material (not strictly greater)."""
        self.assertEqual(_incident_score(0, 100_000, 1_000_000), 25)

    def test_material_loss_just_above_threshold(self):
        """loss = tvl*0.1 + 1 — material penalty applies."""
        self.assertEqual(_incident_score(0, 100_001, 1_000_000), 15)

    def test_combined_penalty_floors_at_zero(self):
        """4 incidents + material loss: 25 - 32 - 10 = -17 → 0."""
        self.assertEqual(_incident_score(4, 200_000, 1_000_000), 0)

    def test_no_tvl_no_material_loss(self):
        """TVL=0 and loss=0 → 0 > 0*0.1 = 0 is False → no material penalty."""
        self.assertEqual(_incident_score(0, 0.0, 0.0), 25)

    def test_incident_score_is_int(self):
        self.assertIsInstance(_incident_score(1, 0, 1_000_000), int)


# ---------------------------------------------------------------------------
# 4. _team_score  (pure function, 0–15)
# ---------------------------------------------------------------------------

class TestTeamScore(unittest.TestCase):

    def test_all_false(self):
        self.assertEqual(_team_score(False, False, False), 0)

    def test_doxxed_only(self):
        self.assertEqual(_team_score(True, False, False), 5)

    def test_bug_bounty_only(self):
        self.assertEqual(_team_score(False, True, False), 5)

    def test_governance_only(self):
        self.assertEqual(_team_score(False, False, True), 5)

    def test_doxxed_and_bug_bounty(self):
        self.assertEqual(_team_score(True, True, False), 10)

    def test_doxxed_and_governance(self):
        self.assertEqual(_team_score(True, False, True), 10)

    def test_all_true(self):
        self.assertEqual(_team_score(True, True, True), 15)

    def test_team_score_is_int(self):
        self.assertIsInstance(_team_score(True, True, True), int)


# ---------------------------------------------------------------------------
# 5. _activity_score  (pure function, 0–10)
# ---------------------------------------------------------------------------

class TestActivityScore(unittest.TestCase):

    def test_zero_transactions(self):
        """log10(1) / log10(100001) * 10 = 0."""
        self.assertEqual(_activity_score(0), 0)

    def test_100k_transactions_capped_at_10(self):
        """log10(100001)/log10(100001)*10 = 10."""
        self.assertEqual(_activity_score(100_000), 10)

    def test_above_100k_still_10(self):
        self.assertEqual(_activity_score(1_000_000), 10)

    def test_activity_score_is_int(self):
        self.assertIsInstance(_activity_score(5000), int)

    def test_monotonically_increases(self):
        """More txs → same or higher score."""
        self.assertGreaterEqual(_activity_score(10_000), _activity_score(1_000))
        self.assertGreaterEqual(_activity_score(50_000), _activity_score(10_000))

    def test_bounded_0_to_10(self):
        for txs in [0, 100, 1_000, 10_000, 100_000, 999_999]:
            s = _activity_score(txs)
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(s, 10)


# ---------------------------------------------------------------------------
# 6. _maturity_tier
# ---------------------------------------------------------------------------

class TestMaturityTier(unittest.TestCase):

    def test_zero_is_experimental(self):
        self.assertEqual(_maturity_tier(0), "EXPERIMENTAL")

    def test_29_is_experimental(self):
        self.assertEqual(_maturity_tier(29), "EXPERIMENTAL")

    def test_30_is_emerging(self):
        self.assertEqual(_maturity_tier(30), "EMERGING")

    def test_54_is_emerging(self):
        self.assertEqual(_maturity_tier(54), "EMERGING")

    def test_55_is_established(self):
        self.assertEqual(_maturity_tier(55), "ESTABLISHED")

    def test_79_is_established(self):
        self.assertEqual(_maturity_tier(79), "ESTABLISHED")

    def test_80_is_battle_tested(self):
        self.assertEqual(_maturity_tier(80), "BATTLE_TESTED")

    def test_100_is_battle_tested(self):
        self.assertEqual(_maturity_tier(100), "BATTLE_TESTED")

    def test_four_possible_tiers_only(self):
        for score in range(0, 101):
            tier = _maturity_tier(score)
            self.assertIn(tier, {"EXPERIMENTAL", "EMERGING", "ESTABLISHED", "BATTLE_TESTED"})


# ---------------------------------------------------------------------------
# 7. total_score computation
# ---------------------------------------------------------------------------

class TestTotalScore(unittest.TestCase):

    def test_total_is_sum_of_components(self):
        result = analyze("Proto", _metrics())
        comps = result["components"]
        expected = sum(comps.values())
        self.assertEqual(result["total_score"], expected)

    def test_total_score_minimum_is_zero(self):
        m = _metrics(age_days=0, audit_count=0, last_audit_days_ago=9999,
                     incident_count=10, team_doxxed=False, has_bug_bounty=False,
                     governance_token=False, on_chain_tx_30d=0)
        result = analyze("Worst", m)
        self.assertGreaterEqual(result["total_score"], 0)

    def test_total_score_is_int(self):
        result = analyze("Proto", _metrics())
        self.assertIsInstance(result["total_score"], int)

    def test_high_quality_protocol_score(self):
        """A battle-tested protocol should score ≥ 80."""
        m = _metrics(age_days=900, audit_count=5, last_audit_days_ago=30,
                     incident_count=0, team_doxxed=True, has_bug_bounty=True,
                     governance_token=True, on_chain_tx_30d=100_000)
        result = analyze("BattleTested", m)
        self.assertGreaterEqual(result["total_score"], 80)

    def test_bad_history_protocol_is_experimental(self):
        """A young protocol with 4+ incidents (incident_score=0) should be EXPERIMENTAL."""
        m = _metrics(age_days=10, audit_count=0, last_audit_days_ago=0,
                     incident_count=4, team_doxxed=False, has_bug_bounty=False,
                     governance_token=False, on_chain_tx_30d=0)
        result = analyze("BadProto", m)
        # age=5, audit=0, incident=0, team=0, activity=0 → total=5 → EXPERIMENTAL
        self.assertLess(result["total_score"], 30)
        self.assertEqual(result["maturity_tier"], "EXPERIMENTAL")


# ---------------------------------------------------------------------------
# 8. max_recommended_allocation_pct
# ---------------------------------------------------------------------------

class TestAllocationCap(unittest.TestCase):

    def test_experimental_alloc_5(self):
        m = _metrics(age_days=10, audit_count=0, last_audit_days_ago=0,
                     team_doxxed=False, has_bug_bounty=False,
                     governance_token=False, on_chain_tx_30d=0)
        result = analyze("Exp", m)
        if result["maturity_tier"] == "EXPERIMENTAL":
            self.assertEqual(result["max_recommended_allocation_pct"], 5.0)

    def test_battle_tested_alloc_50(self):
        m = _metrics(age_days=900, audit_count=5, last_audit_days_ago=30,
                     incident_count=0, team_doxxed=True, has_bug_bounty=True,
                     governance_token=True, on_chain_tx_30d=100_000)
        result = analyze("BT", m)
        if result["maturity_tier"] == "BATTLE_TESTED":
            self.assertEqual(result["max_recommended_allocation_pct"], 50.0)

    def test_emerging_alloc_15(self):
        """Score 30–54 should give 15% cap."""
        result = analyze("Proto", _metrics())
        if result["maturity_tier"] == "EMERGING":
            self.assertEqual(result["max_recommended_allocation_pct"], 15.0)

    def test_established_alloc_30(self):
        """Score 55–79 should give 30% cap."""
        result = analyze("Proto", _metrics())
        if result["maturity_tier"] == "ESTABLISHED":
            self.assertEqual(result["max_recommended_allocation_pct"], 30.0)

    def test_alloc_is_float(self):
        result = analyze("Proto", _metrics())
        self.assertIsInstance(result["max_recommended_allocation_pct"], float)

    def test_alloc_matches_tier(self):
        expected_map = {
            "EXPERIMENTAL": 5.0,
            "EMERGING": 15.0,
            "ESTABLISHED": 30.0,
            "BATTLE_TESTED": 50.0,
        }
        result = analyze("Proto", _metrics())
        tier = result["maturity_tier"]
        self.assertEqual(result["max_recommended_allocation_pct"], expected_map[tier])


# ---------------------------------------------------------------------------
# 9. key_risks
# ---------------------------------------------------------------------------

class TestKeyRisks(unittest.TestCase):

    def test_no_audit_flag(self):
        m = _metrics(audit_count=0, last_audit_days_ago=10)
        risks = _build_key_risks(m)
        self.assertIn("No security audit", risks)

    def test_last_audit_over_365_flag(self):
        m = _metrics(audit_count=1, last_audit_days_ago=400)
        risks = _build_key_risks(m)
        self.assertIn("No audit in past year", risks)

    def test_last_audit_under_365_no_flag(self):
        m = _metrics(audit_count=1, last_audit_days_ago=300)
        risks = _build_key_risks(m)
        self.assertNotIn("No audit in past year", risks)

    def test_incident_count_flag(self):
        m = _metrics(incident_count=2)
        risks = _build_key_risks(m)
        self.assertIn("2 security incident(s) on record", risks)

    def test_incident_count_1_flag(self):
        m = _metrics(incident_count=1)
        risks = _build_key_risks(m)
        self.assertIn("1 security incident(s) on record", risks)

    def test_no_incidents_no_flag(self):
        m = _metrics(incident_count=0)
        risks = _build_key_risks(m)
        self.assertNotIn("1 security incident(s) on record", risks)

    def test_material_loss_flag(self):
        m = _metrics(total_loss_usd=200_000, tvl_usd=1_000_000)
        risks = _build_key_risks(m)
        self.assertIn("Material losses relative to TVL", risks)

    def test_no_material_loss_no_flag(self):
        m = _metrics(total_loss_usd=50_000, tvl_usd=1_000_000)
        risks = _build_key_risks(m)
        self.assertNotIn("Material losses relative to TVL", risks)

    def test_young_protocol_flag(self):
        m = _metrics(age_days=30)
        risks = _build_key_risks(m)
        self.assertIn("Protocol less than 90 days old", risks)

    def test_old_protocol_no_young_flag(self):
        m = _metrics(age_days=365)
        risks = _build_key_risks(m)
        self.assertNotIn("Protocol less than 90 days old", risks)

    def test_anonymous_team_flag(self):
        m = _metrics(team_doxxed=False)
        risks = _build_key_risks(m)
        self.assertIn("Anonymous team", risks)

    def test_known_team_no_anonymous_flag(self):
        m = _metrics(team_doxxed=True)
        risks = _build_key_risks(m)
        self.assertNotIn("Anonymous team", risks)

    def test_clean_protocol_no_risks(self):
        m = _metrics(audit_count=3, last_audit_days_ago=30, incident_count=0,
                     total_loss_usd=0, tvl_usd=1_000_000, age_days=400,
                     team_doxxed=True)
        risks = _build_key_risks(m)
        self.assertEqual(risks, [])

    def test_risks_is_list(self):
        risks = _build_key_risks(_metrics())
        self.assertIsInstance(risks, list)


# ---------------------------------------------------------------------------
# 10. key_strengths
# ---------------------------------------------------------------------------

class TestKeyStrengths(unittest.TestCase):

    def test_age_730_flag(self):
        m = _metrics(age_days=730)
        strengths = _build_key_strengths(m)
        self.assertIn("730+ days live", strengths)

    def test_age_729_no_flag(self):
        m = _metrics(age_days=729)
        strengths = _build_key_strengths(m)
        self.assertNotIn("730+ days live", strengths)

    def test_audit_count_3_flag(self):
        m = _metrics(audit_count=3)
        strengths = _build_key_strengths(m)
        self.assertIn("3 security audits completed", strengths)

    def test_audit_count_5_flag(self):
        m = _metrics(audit_count=5)
        strengths = _build_key_strengths(m)
        self.assertIn("5 security audits completed", strengths)

    def test_audit_count_2_no_flag(self):
        m = _metrics(audit_count=2)
        strengths = _build_key_strengths(m)
        self.assertNotIn("2 security audits completed", strengths)

    def test_no_incidents_flag(self):
        m = _metrics(incident_count=0)
        strengths = _build_key_strengths(m)
        self.assertIn("No security incidents", strengths)

    def test_incidents_no_clean_flag(self):
        m = _metrics(incident_count=1)
        strengths = _build_key_strengths(m)
        self.assertNotIn("No security incidents", strengths)

    def test_bug_bounty_flag(self):
        m = _metrics(has_bug_bounty=True)
        strengths = _build_key_strengths(m)
        self.assertIn("Bug bounty program active", strengths)

    def test_no_bug_bounty_no_flag(self):
        m = _metrics(has_bug_bounty=False)
        strengths = _build_key_strengths(m)
        self.assertNotIn("Bug bounty program active", strengths)

    def test_team_doxxed_flag(self):
        m = _metrics(team_doxxed=True)
        strengths = _build_key_strengths(m)
        self.assertIn("Team identity verified", strengths)

    def test_anonymous_team_no_flag(self):
        m = _metrics(team_doxxed=False)
        strengths = _build_key_strengths(m)
        self.assertNotIn("Team identity verified", strengths)

    def test_no_strengths_for_weak_protocol(self):
        m = _metrics(age_days=50, audit_count=1, incident_count=1,
                     has_bug_bounty=False, team_doxxed=False)
        strengths = _build_key_strengths(m)
        self.assertNotIn("730+ days live", strengths)
        self.assertNotIn("No security incidents", strengths)

    def test_strengths_is_list(self):
        strengths = _build_key_strengths(_metrics())
        self.assertIsInstance(strengths, list)


# ---------------------------------------------------------------------------
# 11. Result structure / analyze() API
# ---------------------------------------------------------------------------

class TestAnalyzeAPI(unittest.TestCase):

    def test_required_keys_present(self):
        result = analyze("Aave", _metrics())
        for key in ("protocol", "components", "total_score", "maturity_tier",
                    "max_recommended_allocation_pct", "key_risks",
                    "key_strengths", "timestamp"):
            self.assertIn(key, result)

    def test_protocol_name_preserved(self):
        result = analyze("MyProto", _metrics())
        self.assertEqual(result["protocol"], "MyProto")

    def test_components_dict_has_five_keys(self):
        result = analyze("P", _metrics())
        self.assertEqual(len(result["components"]), 5)

    def test_components_dict_keys(self):
        result = analyze("P", _metrics())
        comps = result["components"]
        for k in ("age_score", "audit_score", "incident_score",
                  "team_score", "activity_score"):
            self.assertIn(k, comps)

    def test_timestamp_is_float(self):
        result = analyze("P", _metrics())
        self.assertIsInstance(result["timestamp"], float)

    def test_timestamp_is_recent(self):
        before = time.time()
        result = analyze("P", _metrics())
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_maturity_tier_string(self):
        result = analyze("P", _metrics())
        self.assertIsInstance(result["maturity_tier"], str)

    def test_key_risks_is_list(self):
        result = analyze("P", _metrics())
        self.assertIsInstance(result["key_risks"], list)

    def test_key_strengths_is_list(self):
        result = analyze("P", _metrics())
        self.assertIsInstance(result["key_strengths"], list)

    def test_missing_metrics_fields_use_defaults(self):
        """analyze() must not crash on minimal metrics dict."""
        result = analyze("Bare", {})
        self.assertIn("total_score", result)
        self.assertGreaterEqual(result["total_score"], 0)

    def test_components_age_score_correct(self):
        m = _metrics(age_days=730)
        result = analyze("P", m)
        self.assertEqual(result["components"]["age_score"], 25)

    def test_components_team_score_correct(self):
        m = _metrics(team_doxxed=True, has_bug_bounty=True, governance_token=False)
        result = analyze("P", m)
        self.assertEqual(result["components"]["team_score"], 10)


# ---------------------------------------------------------------------------
# 12. Persistence / ring-buffer
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_data_file = pms.DATA_FILE
        pms.DATA_FILE = Path(self._tmpdir) / "data" / "protocol_maturity_log.json"

    def tearDown(self):
        pms.DATA_FILE = self._orig_data_file

    def test_log_file_created(self):
        analyze("Proto", _metrics())
        self.assertTrue(pms.DATA_FILE.exists())

    def test_log_file_is_list(self):
        analyze("Proto", _metrics())
        data = json.loads(pms.DATA_FILE.read_text())
        self.assertIsInstance(data, list)

    def test_log_appends_entries(self):
        analyze("P1", _metrics())
        analyze("P2", _metrics())
        data = json.loads(pms.DATA_FILE.read_text())
        self.assertEqual(len(data), 2)

    def test_ring_buffer_capped_at_100(self):
        for i in range(MAX_ENTRIES + 5):
            analyze(f"P{i}", _metrics())
        data = json.loads(pms.DATA_FILE.read_text())
        self.assertLessEqual(len(data), MAX_ENTRIES)

    def test_ring_buffer_keeps_most_recent(self):
        for i in range(MAX_ENTRIES + 2):
            analyze(f"P{i}", _metrics())
        data = json.loads(pms.DATA_FILE.read_text())
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_no_tmp_file_left_behind(self):
        analyze("P", _metrics())
        tmp = pms.DATA_FILE.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_corrupt_log_recovers(self):
        pms.DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        pms.DATA_FILE.write_text("INVALID JSON!!!!", encoding="utf-8")
        analyze("P", _metrics())  # should not raise
        data = json.loads(pms.DATA_FILE.read_text())
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_persistence_never_raises_on_bad_path(self):
        pms.DATA_FILE = Path("/root/no_permission/deep/maturity.json")
        try:
            result = analyze("P", _metrics())
            self.assertIn("total_score", result)
        finally:
            pms.DATA_FILE = Path(self._tmpdir) / "data" / "protocol_maturity_log.json"


# ---------------------------------------------------------------------------
# 13. Constants
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):

    def test_max_entries_is_100(self):
        self.assertEqual(MAX_ENTRIES, 100)

    def test_four_tier_strings_defined(self):
        for score, expected in [(0, "EXPERIMENTAL"), (30, "EMERGING"),
                                 (55, "ESTABLISHED"), (80, "BATTLE_TESTED")]:
            self.assertEqual(_maturity_tier(score), expected)


if __name__ == "__main__":
    unittest.main()
