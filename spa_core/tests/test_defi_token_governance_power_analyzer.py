"""
Tests for MP-885 DeFiTokenGovernancePowerAnalyzer
==================================================
Run: python3 -m unittest spa_core.tests.test_defi_token_governance_power_analyzer -v
"""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Ensure project root is importable
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from spa_core.analytics.defi_token_governance_power_analyzer import (
    analyze,
    save_result,
    _compute_hhi_score,
    _compute_decentralization_score,
    _compute_participation_score,
    _compute_activity_score,
    _compute_governance_quality,
    _compute_token_model_bonus,
    _compute_composite_score,
    _compute_flags,
    _build_recommendation,
    _atomic_write_json,
    _load_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proto(
    name="TestProto",
    top10_holder_pct=30.0,
    team_treasury_pct=10.0,
    circulating_supply_pct=80.0,
    active_voters_30d=500,
    total_token_holders=50000,
    proposals_last_90d=5,
    avg_voter_turnout_pct=15.0,
    token_type="GOVERNANCE_ONLY",
):
    return {
        "name": name,
        "top10_holder_pct": top10_holder_pct,
        "team_treasury_pct": team_treasury_pct,
        "circulating_supply_pct": circulating_supply_pct,
        "active_voters_30d": active_voters_30d,
        "total_token_holders": total_token_holders,
        "proposals_last_90d": proposals_last_90d,
        "avg_voter_turnout_pct": avg_voter_turnout_pct,
        "token_type": token_type,
    }


# ===========================================================================
# 1. HHI Score Tests
# ===========================================================================
class TestHHIScore(unittest.TestCase):

    def test_perfect_distribution(self):
        # top10 = 10% → (10/10)^2 * 10 = 10 → int(10) = 10
        self.assertEqual(_compute_hhi_score(10.0), 10)

    def test_perfect_distribution_boundary(self):
        # Checks actual formula: int((10/10)^2 * 10) = int(10) = 10
        result = _compute_hhi_score(10.0)
        self.assertIsInstance(result, int)

    def test_zero_percent(self):
        # (0/10)^2 * 10 = 0
        self.assertEqual(_compute_hhi_score(0.0), 0)

    def test_fifty_percent(self):
        # (50/10)^2 * 10 = 25 * 10 = 250 → clamped to 100
        self.assertEqual(_compute_hhi_score(50.0), 100)

    def test_hundred_percent(self):
        # max concentration → clamped to 100
        self.assertEqual(_compute_hhi_score(100.0), 100)

    def test_twenty_percent(self):
        # (20/10)^2 * 10 = 4 * 10 = 40
        self.assertEqual(_compute_hhi_score(20.0), 40)

    def test_thirty_percent(self):
        # (30/10)^2 * 10 = 9 * 10 = 90
        self.assertEqual(_compute_hhi_score(30.0), 90)

    def test_forty_percent(self):
        # (40/10)^2 * 10 = 16 * 10 = 160 → clamped to 100
        self.assertEqual(_compute_hhi_score(40.0), 100)

    def test_returns_int(self):
        result = _compute_hhi_score(25.0)
        self.assertIsInstance(result, int)

    def test_clamped_at_100(self):
        self.assertLessEqual(_compute_hhi_score(100.0), 100)

    def test_non_negative(self):
        self.assertGreaterEqual(_compute_hhi_score(0.0), 0)

    def test_fifteen_percent(self):
        # (15/10)^2 * 10 = 2.25 * 10 = 22.5 → int = 22
        self.assertEqual(_compute_hhi_score(15.0), 22)


# ===========================================================================
# 2. Decentralization Score Tests
# ===========================================================================
class TestDecentralizationScore(unittest.TestCase):

    def test_low_hhi_low_team(self):
        # hhi=10, team=5% → penalty=int(5*0.8)=4 → 100-10-4=86
        result = _compute_decentralization_score(10, 5.0)
        self.assertEqual(result, 86)

    def test_high_hhi_zeroes_score(self):
        # hhi=90, team=20 → penalty=min(40,16)=16 → 100-90-16=-6 → max(0,...)=0
        result = _compute_decentralization_score(90, 20.0)
        self.assertEqual(result, 0)

    def test_penalty_capped_at_40(self):
        # team=60% → min(40, int(60*0.8))=min(40,48)=40
        result = _compute_decentralization_score(0, 60.0)
        self.assertEqual(result, 60)  # 100-0-40=60

    def test_zero_hhi_zero_team(self):
        result = _compute_decentralization_score(0, 0.0)
        self.assertEqual(result, 100)

    def test_minimum_zero(self):
        result = _compute_decentralization_score(100, 60.0)
        self.assertEqual(result, 0)

    def test_returns_int(self):
        result = _compute_decentralization_score(30, 10.0)
        self.assertIsInstance(result, int)

    def test_team_penalty_calculation(self):
        # team=25% → penalty=int(25*0.8)=20 → 100-30-20=50
        result = _compute_decentralization_score(30, 25.0)
        self.assertEqual(result, 50)

    def test_non_negative(self):
        for hhi in [0, 50, 100]:
            for team in [0, 30, 60]:
                self.assertGreaterEqual(_compute_decentralization_score(hhi, team), 0)


# ===========================================================================
# 3. Participation Score Tests
# ===========================================================================
class TestParticipationScore(unittest.TestCase):

    def test_zero_turnout(self):
        self.assertEqual(_compute_participation_score(0.0), 0)

    def test_twenty_percent_turnout(self):
        # min(100, int(20 * 5)) = 100
        self.assertEqual(_compute_participation_score(20.0), 100)

    def test_ten_percent_turnout(self):
        # int(10 * 5) = 50
        self.assertEqual(_compute_participation_score(10.0), 50)

    def test_five_percent_turnout(self):
        # int(5 * 5) = 25
        self.assertEqual(_compute_participation_score(5.0), 25)

    def test_over_twenty_percent_clamped(self):
        self.assertEqual(_compute_participation_score(30.0), 100)

    def test_returns_int(self):
        self.assertIsInstance(_compute_participation_score(10.0), int)

    def test_non_negative(self):
        self.assertGreaterEqual(_compute_participation_score(0.0), 0)


# ===========================================================================
# 4. Activity Score Tests
# ===========================================================================
class TestActivityScore(unittest.TestCase):

    def test_zero_proposals(self):
        self.assertEqual(_compute_activity_score(0), 0)

    def test_one_proposal(self):
        self.assertEqual(_compute_activity_score(1), 10)

    def test_ten_proposals(self):
        self.assertEqual(_compute_activity_score(10), 100)

    def test_over_ten_clamped(self):
        self.assertEqual(_compute_activity_score(15), 100)

    def test_five_proposals(self):
        self.assertEqual(_compute_activity_score(5), 50)

    def test_returns_int(self):
        self.assertIsInstance(_compute_activity_score(3), int)


# ===========================================================================
# 5. Governance Quality Tests
# ===========================================================================
class TestGovernanceQuality(unittest.TestCase):

    def test_excellent(self):
        result = _compute_governance_quality(70, 50)
        self.assertEqual(result, "EXCELLENT")

    def test_excellent_high_scores(self):
        result = _compute_governance_quality(90, 80)
        self.assertEqual(result, "EXCELLENT")

    def test_good(self):
        result = _compute_governance_quality(50, 30)
        self.assertEqual(result, "GOOD")

    def test_good_boundary(self):
        result = _compute_governance_quality(60, 40)
        self.assertEqual(result, "GOOD")

    def test_moderate(self):
        result = _compute_governance_quality(30, 10)
        self.assertEqual(result, "MODERATE")

    def test_moderate_boundary(self):
        result = _compute_governance_quality(30, 29)
        self.assertEqual(result, "MODERATE")

    def test_weak(self):
        result = _compute_governance_quality(15, 5)
        self.assertEqual(result, "WEAK")

    def test_plutocratic(self):
        result = _compute_governance_quality(14, 0)
        self.assertEqual(result, "PLUTOCRATIC")

    def test_plutocratic_zero_zero(self):
        result = _compute_governance_quality(0, 0)
        self.assertEqual(result, "PLUTOCRATIC")

    def test_dec70_but_participation_below_50_not_excellent(self):
        # dec=70, participation=49 → not EXCELLENT; check GOOD (50<=70, 30<=49)
        result = _compute_governance_quality(70, 49)
        self.assertEqual(result, "GOOD")


# ===========================================================================
# 6. Token Model Bonus Tests
# ===========================================================================
class TestTokenModelBonus(unittest.TestCase):

    def test_vote_escrowed(self):
        self.assertEqual(_compute_token_model_bonus("VOTE_ESCROWED"), 15)

    def test_delegated(self):
        self.assertEqual(_compute_token_model_bonus("DELEGATED"), 10)

    def test_dual_utility(self):
        self.assertEqual(_compute_token_model_bonus("DUAL_UTILITY"), 5)

    def test_governance_only(self):
        self.assertEqual(_compute_token_model_bonus("GOVERNANCE_ONLY"), 0)

    def test_unknown_type(self):
        self.assertEqual(_compute_token_model_bonus("UNKNOWN"), 0)

    def test_empty_string(self):
        self.assertEqual(_compute_token_model_bonus(""), 0)


# ===========================================================================
# 7. Composite Score Tests
# ===========================================================================
class TestCompositeScore(unittest.TestCase):

    def test_all_zero(self):
        self.assertEqual(_compute_composite_score(0, 0, 0, 0), 0)

    def test_all_100(self):
        # int(100*0.4 + 100*0.3 + 100*0.2 + 100*0.1) = int(100) = 100
        self.assertEqual(_compute_composite_score(100, 100, 100, 100), 100)

    def test_weights_correct(self):
        # dec=100, others=0 → 40; dec=0,part=100,others=0 → 30
        self.assertEqual(_compute_composite_score(100, 0, 0, 0), 40)
        self.assertEqual(_compute_composite_score(0, 100, 0, 0), 30)
        self.assertEqual(_compute_composite_score(0, 0, 100, 0), 20)
        self.assertEqual(_compute_composite_score(0, 0, 0, 100), 10)

    def test_clamped_max(self):
        result = _compute_composite_score(200, 200, 200, 200)
        self.assertLessEqual(result, 100)

    def test_clamped_min(self):
        result = _compute_composite_score(-50, -50, -50, -50)
        self.assertGreaterEqual(result, 0)

    def test_returns_int(self):
        self.assertIsInstance(_compute_composite_score(50, 50, 50, 10), int)


# ===========================================================================
# 8. Flags Tests
# ===========================================================================
class TestFlags(unittest.TestCase):

    def test_no_flags(self):
        flags = _compute_flags(40.0, 20.0, 10.0, 5)
        self.assertEqual(flags, [])

    def test_whale_dominated(self):
        flags = _compute_flags(51.0, 20.0, 10.0, 5)
        self.assertIn("WHALE_DOMINATED", flags)

    def test_whale_dominated_boundary_exact_50(self):
        # >50 triggers flag; exact 50 does not
        flags = _compute_flags(50.0, 0.0, 10.0, 5)
        self.assertNotIn("WHALE_DOMINATED", flags)

    def test_team_heavy(self):
        flags = _compute_flags(40.0, 31.0, 10.0, 5)
        self.assertIn("TEAM_HEAVY", flags)

    def test_team_heavy_boundary(self):
        flags = _compute_flags(40.0, 30.0, 10.0, 5)
        self.assertNotIn("TEAM_HEAVY", flags)

    def test_low_participation(self):
        flags = _compute_flags(40.0, 20.0, 4.9, 5)
        self.assertIn("LOW_PARTICIPATION", flags)

    def test_low_participation_boundary(self):
        flags = _compute_flags(40.0, 20.0, 5.0, 5)
        self.assertNotIn("LOW_PARTICIPATION", flags)

    def test_inactive(self):
        flags = _compute_flags(40.0, 20.0, 10.0, 2)
        self.assertIn("INACTIVE", flags)

    def test_inactive_boundary(self):
        flags = _compute_flags(40.0, 20.0, 10.0, 3)
        self.assertNotIn("INACTIVE", flags)

    def test_all_flags(self):
        flags = _compute_flags(55.0, 35.0, 2.0, 1)
        self.assertEqual(
            set(flags),
            {"WHALE_DOMINATED", "TEAM_HEAVY", "LOW_PARTICIPATION", "INACTIVE"},
        )

    def test_returns_list(self):
        self.assertIsInstance(_compute_flags(30.0, 10.0, 10.0, 5), list)


# ===========================================================================
# 9. Recommendation Tests
# ===========================================================================
class TestRecommendation(unittest.TestCase):

    def test_excellent_contains_active_voters(self):
        rec = _build_recommendation("EXCELLENT", 1200, 15.0, 8, 30.0, [])
        self.assertIn("1200", rec)
        self.assertIn("15.0", rec)

    def test_excellent_contains_strong(self):
        rec = _build_recommendation("EXCELLENT", 500, 10.0, 4, 30.0, [])
        self.assertIn("Strong", rec)

    def test_good_contains_proposals(self):
        rec = _build_recommendation("GOOD", 500, 10.0, 8, 30.0, [])
        self.assertIn("8", rec)
        self.assertIn("Solid", rec)

    def test_moderate_contains_concerns(self):
        rec = _build_recommendation("MODERATE", 200, 3.0, 5, 30.0, ["WHALE_DOMINATED"])
        self.assertIn("1 concern", rec)

    def test_moderate_shows_first_two_flags(self):
        rec = _build_recommendation(
            "MODERATE", 200, 3.0, 5, 30.0,
            ["WHALE_DOMINATED", "TEAM_HEAVY", "INACTIVE"]
        )
        self.assertIn("WHALE_DOMINATED", rec)

    def test_moderate_no_flags_shows_low_engagement(self):
        rec = _build_recommendation("MODERATE", 200, 3.0, 5, 30.0, [])
        self.assertIn("low engagement", rec)

    def test_weak_contains_top10_pct(self):
        rec = _build_recommendation("WEAK", 100, 2.0, 1, 70.0, [])
        self.assertIn("70%", rec)

    def test_plutocratic_contains_top10_pct(self):
        rec = _build_recommendation("PLUTOCRATIC", 10, 1.0, 0, 90.0, [])
        self.assertIn("90%", rec)
        self.assertIn("risk", rec)

    def test_returns_string(self):
        self.assertIsInstance(
            _build_recommendation("MODERATE", 100, 5.0, 4, 40.0, []), str
        )


# ===========================================================================
# 10. analyze() integration tests
# ===========================================================================
class TestAnalyze(unittest.TestCase):

    def test_empty_input(self):
        result = analyze([])
        self.assertEqual(result["protocols"], [])
        self.assertIsNone(result["most_decentralized"])
        self.assertEqual(result["average_composite_score"], 0.0)
        self.assertIn("timestamp", result)

    def test_single_protocol_keys(self):
        proto = _make_proto()
        result = analyze([proto])
        p = result["protocols"][0]
        for key in [
            "name", "hhi_score", "decentralization_score", "participation_score",
            "activity_score", "governance_quality", "token_model_bonus",
            "composite_score", "flags", "recommendation",
        ]:
            self.assertIn(key, p)

    def test_single_protocol_most_decentralized(self):
        proto = _make_proto(name="Alpha")
        result = analyze([proto])
        self.assertEqual(result["most_decentralized"], "Alpha")

    def test_multiple_protocols_most_decentralized(self):
        p1 = _make_proto(name="Aave", top10_holder_pct=10.0, team_treasury_pct=5.0)
        p2 = _make_proto(name="Compound", top10_holder_pct=80.0, team_treasury_pct=40.0)
        result = analyze([p1, p2])
        self.assertEqual(result["most_decentralized"], "Aave")

    def test_average_composite_score_single(self):
        proto = _make_proto(top10_holder_pct=20.0, team_treasury_pct=10.0,
                            avg_voter_turnout_pct=10.0, proposals_last_90d=5)
        result = analyze([proto])
        self.assertEqual(
            result["average_composite_score"],
            result["protocols"][0]["composite_score"]
        )

    def test_average_composite_score_two(self):
        p1 = _make_proto(name="A")
        p2 = _make_proto(name="B")
        result = analyze([p1, p2])
        expected = (
            result["protocols"][0]["composite_score"]
            + result["protocols"][1]["composite_score"]
        ) / 2
        self.assertAlmostEqual(result["average_composite_score"], expected, places=5)

    def test_timestamp_is_recent(self):
        before = time.time()
        result = analyze([])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after + 1)

    def test_none_config_accepted(self):
        result = analyze([_make_proto()], config=None)
        self.assertIn("protocols", result)

    def test_dict_config_accepted(self):
        result = analyze([_make_proto()], config={"any": "key"})
        self.assertIn("protocols", result)

    def test_whale_flag_set(self):
        proto = _make_proto(top10_holder_pct=60.0)
        result = analyze([proto])
        self.assertIn("WHALE_DOMINATED", result["protocols"][0]["flags"])

    def test_no_whale_flag(self):
        proto = _make_proto(top10_holder_pct=30.0)
        result = analyze([proto])
        self.assertNotIn("WHALE_DOMINATED", result["protocols"][0]["flags"])

    def test_team_heavy_flag(self):
        proto = _make_proto(team_treasury_pct=40.0)
        result = analyze([proto])
        self.assertIn("TEAM_HEAVY", result["protocols"][0]["flags"])

    def test_low_participation_flag(self):
        proto = _make_proto(avg_voter_turnout_pct=2.0)
        result = analyze([proto])
        self.assertIn("LOW_PARTICIPATION", result["protocols"][0]["flags"])

    def test_inactive_flag(self):
        proto = _make_proto(proposals_last_90d=1)
        result = analyze([proto])
        self.assertIn("INACTIVE", result["protocols"][0]["flags"])

    def test_hhi_score_formula(self):
        proto = _make_proto(top10_holder_pct=20.0)
        result = analyze([proto])
        # (20/10)^2 * 10 = 40
        self.assertEqual(result["protocols"][0]["hhi_score"], 40)

    def test_excellent_quality(self):
        # Need dec>=70 and participation>=50
        # dec: hhi_score low, team low; participation: turnout 20%→part=100
        proto = _make_proto(
            top10_holder_pct=10.0,  # hhi=10
            team_treasury_pct=5.0,  # penalty=4 → dec=86
            avg_voter_turnout_pct=20.0,  # part=100
            proposals_last_90d=5,
        )
        result = analyze([proto])
        self.assertEqual(result["protocols"][0]["governance_quality"], "EXCELLENT")

    def test_plutocratic_quality(self):
        proto = _make_proto(
            top10_holder_pct=100.0,  # hhi=100
            team_treasury_pct=50.0,  # penalty=40 → dec=0
            avg_voter_turnout_pct=1.0,  # part=5
        )
        result = analyze([proto])
        self.assertEqual(result["protocols"][0]["governance_quality"], "PLUTOCRATIC")

    def test_vote_escrowed_bonus(self):
        proto = _make_proto(token_type="VOTE_ESCROWED")
        result = analyze([proto])
        self.assertEqual(result["protocols"][0]["token_model_bonus"], 15)

    def test_delegated_bonus(self):
        proto = _make_proto(token_type="DELEGATED")
        result = analyze([proto])
        self.assertEqual(result["protocols"][0]["token_model_bonus"], 10)

    def test_composite_score_range(self):
        proto = _make_proto()
        result = analyze([proto])
        score = result["protocols"][0]["composite_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_multiple_protocols_all_returned(self):
        protos = [_make_proto(name=f"P{i}") for i in range(5)]
        result = analyze(protos)
        self.assertEqual(len(result["protocols"]), 5)

    def test_protocol_name_preserved(self):
        proto = _make_proto(name="MyProtocol")
        result = analyze([proto])
        self.assertEqual(result["protocols"][0]["name"], "MyProtocol")

    def test_recommendation_is_string(self):
        result = analyze([_make_proto()])
        self.assertIsInstance(result["protocols"][0]["recommendation"], str)

    def test_recommendation_not_empty(self):
        result = analyze([_make_proto()])
        self.assertTrue(len(result["protocols"][0]["recommendation"]) > 0)


# ===========================================================================
# 11. Persistence tests
# ===========================================================================
class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = Path(self.tmp_dir) / "governance_power_log.json"

    def test_save_creates_file(self):
        result = analyze([_make_proto()])
        save_result(result, self.log_path)
        self.assertTrue(self.log_path.exists())

    def test_save_creates_list(self):
        result = analyze([_make_proto()])
        save_result(result, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_save_multiple_entries(self):
        for i in range(5):
            result = analyze([_make_proto(name=f"P{i}")])
            save_result(result, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_caps_at_100(self):
        for i in range(110):
            result = analyze([_make_proto(name=f"P{i}")])
            save_result(result, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_load_missing_file_returns_empty(self):
        missing = Path(self.tmp_dir) / "nonexistent.json"
        data = _load_log(missing)
        self.assertEqual(data, [])

    def test_atomic_write_json(self):
        path = Path(self.tmp_dir) / "test_atomic.json"
        payload = {"key": "value", "num": 42}
        _atomic_write_json(path, payload)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["key"], "value")
        self.assertEqual(data["num"], 42)

    def test_load_corrupt_file_returns_empty(self):
        corrupt = Path(self.tmp_dir) / "corrupt.json"
        corrupt.write_text("{not valid json", encoding="utf-8")
        data = _load_log(corrupt)
        self.assertEqual(data, [])

    def test_load_non_list_returns_empty(self):
        path = Path(self.tmp_dir) / "not_list.json"
        with open(path, "w") as f:
            json.dump({"key": "val"}, f)
        data = _load_log(path)
        self.assertEqual(data, [])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)


# ===========================================================================
# 12. Edge case / boundary tests
# ===========================================================================
class TestEdgeCases(unittest.TestCase):

    def test_empty_protocols_returns_empty_list(self):
        result = analyze([])
        self.assertEqual(result["protocols"], [])

    def test_empty_protocols_most_decentralized_none(self):
        result = analyze([])
        self.assertIsNone(result["most_decentralized"])

    def test_empty_protocols_avg_zero(self):
        result = analyze([])
        self.assertEqual(result["average_composite_score"], 0.0)

    def test_top10_exactly_100_hhi_100(self):
        self.assertEqual(_compute_hhi_score(100.0), 100)

    def test_top10_exactly_10_hhi_10(self):
        self.assertEqual(_compute_hhi_score(10.0), 10)

    def test_proposals_exactly_3_no_inactive_flag(self):
        flags = _compute_flags(30.0, 10.0, 10.0, 3)
        self.assertNotIn("INACTIVE", flags)

    def test_proposals_exactly_2_inactive_flag(self):
        flags = _compute_flags(30.0, 10.0, 10.0, 2)
        self.assertIn("INACTIVE", flags)

    def test_missing_fields_use_defaults(self):
        # Protocol with minimal fields
        proto = {"name": "Minimal"}
        result = analyze([proto])
        self.assertEqual(len(result["protocols"]), 1)
        p = result["protocols"][0]
        self.assertEqual(p["name"], "Minimal")
        # hhi_score: top10=0 → 0
        self.assertEqual(p["hhi_score"], 0)

    def test_protocol_with_float_active_voters(self):
        # active_voters_30d converted to int
        proto = _make_proto(active_voters_30d=1000)
        result = analyze([proto])
        self.assertIsNotNone(result)

    def test_large_number_of_protocols(self):
        protos = [_make_proto(name=f"P{i}") for i in range(50)]
        result = analyze(protos)
        self.assertEqual(len(result["protocols"]), 50)

    def test_turnout_exactly_5_not_low_participation(self):
        flags = _compute_flags(30.0, 10.0, 5.0, 5)
        self.assertNotIn("LOW_PARTICIPATION", flags)

    def test_turnout_4_99_low_participation(self):
        flags = _compute_flags(30.0, 10.0, 4.99, 5)
        self.assertIn("LOW_PARTICIPATION", flags)

    def test_all_zeros_protocol(self):
        proto = {
            "name": "ZeroProto",
            "top10_holder_pct": 0.0,
            "team_treasury_pct": 0.0,
            "circulating_supply_pct": 0.0,
            "active_voters_30d": 0,
            "total_token_holders": 0,
            "proposals_last_90d": 0,
            "avg_voter_turnout_pct": 0.0,
            "token_type": "GOVERNANCE_ONLY",
        }
        result = analyze([proto])
        p = result["protocols"][0]
        self.assertEqual(p["hhi_score"], 0)
        self.assertEqual(p["token_model_bonus"], 0)
        # all proposals=0 → INACTIVE flag; turnout=0 → LOW_PARTICIPATION
        self.assertIn("INACTIVE", p["flags"])
        self.assertIn("LOW_PARTICIPATION", p["flags"])


if __name__ == "__main__":
    unittest.main()
