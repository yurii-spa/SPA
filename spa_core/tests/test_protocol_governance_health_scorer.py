"""
Tests for MP-836 ProtocolGovernanceHealthScorer.
Run: python3 -m unittest spa_core.tests.test_protocol_governance_health_scorer -v
"""

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.protocol_governance_health_scorer import (
    _participation_score,
    _activity_score,
    _decentralization_score,
    _safety_score,
    _circulation_score,
    _grade,
    _governance_label,
    _centralization_risk,
    _compute_flags,
    _compute_strengths,
    analyze,
    log_result,
    _atomic_write,
    _init_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proto(name="TestProto",
           voter_participation_pct=10.0,
           proposals_last_90d=5,
           top10_holder_pct=40.0,
           has_timelock=True,
           timelock_hours=48,
           multisig_required=True,
           community_forum_active=True,
           governance_token_circulating_pct=60.0):
    return {
        "name": name,
        "voter_participation_pct": voter_participation_pct,
        "proposals_last_90d": proposals_last_90d,
        "top10_holder_pct": top10_holder_pct,
        "has_timelock": has_timelock,
        "timelock_hours": timelock_hours,
        "multisig_required": multisig_required,
        "community_forum_active": community_forum_active,
        "governance_token_circulating_pct": governance_token_circulating_pct,
    }


def _minimal_proto(name="Min"):
    """Protocol that will score very low."""
    return _proto(
        name=name,
        voter_participation_pct=0.5,
        proposals_last_90d=0,
        top10_holder_pct=95.0,
        has_timelock=False,
        timelock_hours=0,
        multisig_required=False,
        community_forum_active=False,
        governance_token_circulating_pct=5.0,
    )


def _max_proto(name="Max"):
    """Protocol that will score near maximum."""
    return _proto(
        name=name,
        voter_participation_pct=25.0,
        proposals_last_90d=12,
        top10_holder_pct=20.0,
        has_timelock=True,
        timelock_hours=72,
        multisig_required=True,
        community_forum_active=True,
        governance_token_circulating_pct=80.0,
    )


# ---------------------------------------------------------------------------
# Tests for sub-component scorers
# ---------------------------------------------------------------------------

class TestParticipationScore(unittest.TestCase):
    """10 tests for _participation_score."""

    def test_above_20_returns_25(self):
        self.assertEqual(_participation_score(25.0), 25)

    def test_exactly_20_returns_25(self):
        self.assertEqual(_participation_score(20.0), 25)

    def test_above_10_returns_20(self):
        self.assertEqual(_participation_score(15.0), 20)

    def test_exactly_10_returns_20(self):
        self.assertEqual(_participation_score(10.0), 20)

    def test_above_5_returns_15(self):
        self.assertEqual(_participation_score(7.0), 15)

    def test_exactly_5_returns_15(self):
        self.assertEqual(_participation_score(5.0), 15)

    def test_above_2_returns_8(self):
        self.assertEqual(_participation_score(3.0), 8)

    def test_exactly_2_returns_8(self):
        self.assertEqual(_participation_score(2.0), 8)

    def test_below_2_returns_2(self):
        self.assertEqual(_participation_score(0.5), 2)

    def test_zero_returns_2(self):
        self.assertEqual(_participation_score(0.0), 2)


class TestActivityScore(unittest.TestCase):
    """8 tests for _activity_score."""

    def test_10_or_more_returns_20(self):
        self.assertEqual(_activity_score(10), 20)
        self.assertEqual(_activity_score(15), 20)

    def test_5_to_9_returns_15(self):
        self.assertEqual(_activity_score(5), 15)
        self.assertEqual(_activity_score(9), 15)

    def test_2_to_4_returns_10(self):
        self.assertEqual(_activity_score(2), 10)
        self.assertEqual(_activity_score(4), 10)

    def test_1_returns_5(self):
        self.assertEqual(_activity_score(1), 5)

    def test_0_returns_0(self):
        self.assertEqual(_activity_score(0), 0)


class TestDecentralizationScore(unittest.TestCase):
    """8 tests for _decentralization_score."""

    def test_30_or_less_returns_25(self):
        self.assertEqual(_decentralization_score(20.0), 25)
        self.assertEqual(_decentralization_score(30.0), 25)

    def test_31_to_50_returns_18(self):
        self.assertEqual(_decentralization_score(45.0), 18)
        self.assertEqual(_decentralization_score(50.0), 18)

    def test_51_to_70_returns_10(self):
        self.assertEqual(_decentralization_score(60.0), 10)
        self.assertEqual(_decentralization_score(70.0), 10)

    def test_71_to_85_returns_5(self):
        self.assertEqual(_decentralization_score(75.0), 5)
        self.assertEqual(_decentralization_score(85.0), 5)

    def test_above_85_returns_0(self):
        self.assertEqual(_decentralization_score(90.0), 0)


class TestSafetyScore(unittest.TestCase):
    """10 tests for _safety_score."""

    def test_48h_timelock_gives_8(self):
        score = _safety_score(48, False, False)
        self.assertEqual(score, 8)

    def test_72h_timelock_gives_8(self):
        score = _safety_score(72, False, False)
        self.assertEqual(score, 8)

    def test_24h_timelock_gives_5(self):
        score = _safety_score(24, False, False)
        self.assertEqual(score, 5)

    def test_1h_timelock_gives_2(self):
        score = _safety_score(1, False, False)
        self.assertEqual(score, 2)

    def test_no_timelock_gives_0(self):
        score = _safety_score(0, False, False)
        self.assertEqual(score, 0)

    def test_multisig_adds_7(self):
        score_no_ms = _safety_score(0, False, False)
        score_ms = _safety_score(0, True, False)
        self.assertEqual(score_ms - score_no_ms, 7)

    def test_forum_adds_5(self):
        score_no_forum = _safety_score(0, False, False)
        score_forum = _safety_score(0, False, True)
        self.assertEqual(score_forum - score_no_forum, 5)

    def test_all_safety_features_max_20(self):
        score = _safety_score(48, True, True)
        self.assertEqual(score, 20)

    def test_max_total_all_features(self):
        score = _safety_score(72, True, True)
        self.assertEqual(score, 20)

    def test_no_safety_features_zero(self):
        self.assertEqual(_safety_score(0, False, False), 0)


class TestCirculationScore(unittest.TestCase):
    """7 tests for _circulation_score."""

    def test_70_or_above_returns_10(self):
        self.assertEqual(_circulation_score(70.0), 10)
        self.assertEqual(_circulation_score(90.0), 10)

    def test_50_to_69_returns_7(self):
        self.assertEqual(_circulation_score(50.0), 7)
        self.assertEqual(_circulation_score(69.9), 7)

    def test_30_to_49_returns_4(self):
        self.assertEqual(_circulation_score(30.0), 4)
        self.assertEqual(_circulation_score(49.9), 4)

    def test_below_30_returns_1(self):
        self.assertEqual(_circulation_score(10.0), 1)
        self.assertEqual(_circulation_score(0.0), 1)


class TestGradeAndLabel(unittest.TestCase):
    """12 tests for _grade, _governance_label, _centralization_risk."""

    def test_grade_A_at_80(self):
        self.assertEqual(_grade(80), "A")

    def test_grade_A_at_100(self):
        self.assertEqual(_grade(100), "A")

    def test_grade_B_at_60(self):
        self.assertEqual(_grade(60), "B")

    def test_grade_B_at_79(self):
        self.assertEqual(_grade(79), "B")

    def test_grade_C_at_40(self):
        self.assertEqual(_grade(40), "C")

    def test_grade_D_at_20(self):
        self.assertEqual(_grade(20), "D")

    def test_grade_F_at_0(self):
        self.assertEqual(_grade(0), "F")

    def test_label_excellent(self):
        self.assertEqual(_governance_label(80), "EXCELLENT")

    def test_label_critical(self):
        self.assertEqual(_governance_label(19), "CRITICAL")

    def test_centralization_low(self):
        self.assertEqual(_centralization_risk(25.0), "LOW")

    def test_centralization_extreme(self):
        self.assertEqual(_centralization_risk(75.0), "EXTREME")

    def test_centralization_medium_at_50(self):
        self.assertEqual(_centralization_risk(50.0), "MEDIUM")


class TestFlagsAndStrengths(unittest.TestCase):
    """10 tests for _compute_flags and _compute_strengths."""

    def _p(self, **kwargs):
        base = {
            "voter_participation_pct": 10.0,
            "proposals_last_90d": 5,
            "top10_holder_pct": 40.0,
            "has_timelock": True,
            "timelock_hours": 48,
            "multisig_required": True,
            "community_forum_active": True,
            "governance_token_circulating_pct": 60.0,
        }
        base.update(kwargs)
        return base

    def test_low_participation_flag(self):
        p = self._p(voter_participation_pct=2.0)
        flags = _compute_flags(p, min_participation=5.0)
        self.assertTrue(any("participation" in f.lower() for f in flags))

    def test_no_activity_flag(self):
        p = self._p(proposals_last_90d=0)
        flags = _compute_flags(p, min_participation=5.0)
        self.assertIn("No governance activity in 90 days", flags)

    def test_majority_holder_flag(self):
        p = self._p(top10_holder_pct=60.0)
        flags = _compute_flags(p, min_participation=5.0)
        self.assertTrue(any("majority" in f.lower() for f in flags))

    def test_no_timelock_flag(self):
        p = self._p(has_timelock=False, timelock_hours=0)
        flags = _compute_flags(p, min_participation=5.0)
        self.assertIn("No timelock on governance", flags)

    def test_no_multisig_flag(self):
        p = self._p(multisig_required=False)
        flags = _compute_flags(p, min_participation=5.0)
        self.assertIn("No multisig protection", flags)

    def test_low_circulation_flag(self):
        p = self._p(governance_token_circulating_pct=20.0)
        flags = _compute_flags(p, min_participation=5.0)
        self.assertIn("Token supply not widely distributed", flags)

    def test_strong_participation_strength(self):
        p = self._p(voter_participation_pct=20.0)
        strengths = _compute_strengths(p)
        self.assertIn("Strong voter participation", strengths)

    def test_active_community_strength(self):
        p = self._p(proposals_last_90d=6)
        strengths = _compute_strengths(p)
        self.assertIn("Active governance community", strengths)

    def test_decentralized_strength(self):
        p = self._p(top10_holder_pct=35.0)
        strengths = _compute_strengths(p)
        self.assertIn("Decentralized token distribution", strengths)

    def test_multisig_strength(self):
        p = self._p(multisig_required=True)
        strengths = _compute_strengths(p)
        self.assertIn("Multisig security", strengths)


class TestAnalyze(unittest.TestCase):
    """25 tests for the main analyze() function."""

    def test_returns_dict(self):
        result = analyze([_proto()])
        self.assertIsInstance(result, dict)

    def test_required_keys_present(self):
        result = analyze([_proto()])
        for k in ("protocols", "best_governed", "worst_governed",
                  "average_score", "critical_count", "timestamp"):
            self.assertIn(k, result)

    def test_protocol_result_keys(self):
        result = analyze([_proto()])
        p = result["protocols"][0]
        for k in ("name", "governance_score", "grade", "governance_label",
                  "centralization_risk", "flags", "strengths"):
            self.assertIn(k, p)

    def test_empty_protocols(self):
        result = analyze([])
        self.assertEqual(result["protocols"], [])
        self.assertIsNone(result["best_governed"])
        self.assertIsNone(result["worst_governed"])
        self.assertEqual(result["average_score"], 0.0)
        self.assertEqual(result["critical_count"], 0)

    def test_single_protocol_best_worst_same(self):
        result = analyze([_proto("Solo")])
        self.assertEqual(result["best_governed"], "Solo")
        self.assertEqual(result["worst_governed"], "Solo")

    def test_score_between_0_and_100(self):
        for p in [_proto(), _minimal_proto(), _max_proto()]:
            result = analyze([p])
            score = result["protocols"][0]["governance_score"]
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_max_proto_high_score(self):
        result = analyze([_max_proto()])
        score = result["protocols"][0]["governance_score"]
        self.assertGreaterEqual(score, 80)

    def test_minimal_proto_low_score(self):
        result = analyze([_minimal_proto()])
        score = result["protocols"][0]["governance_score"]
        self.assertLessEqual(score, 20)

    def test_minimal_proto_critical_label(self):
        result = analyze([_minimal_proto()])
        label = result["protocols"][0]["governance_label"]
        self.assertEqual(label, "CRITICAL")

    def test_max_proto_excellent_label(self):
        result = analyze([_max_proto()])
        label = result["protocols"][0]["governance_label"]
        self.assertEqual(label, "EXCELLENT")

    def test_critical_count_correct(self):
        result = analyze([_max_proto("Good"), _minimal_proto("Bad")])
        self.assertEqual(result["critical_count"], 1)

    def test_best_governed_is_highest_score(self):
        p_good = _max_proto("Good")
        p_bad = _minimal_proto("Bad")
        result = analyze([p_good, p_bad])
        self.assertEqual(result["best_governed"], "Good")

    def test_worst_governed_is_lowest_score(self):
        p_good = _max_proto("Good")
        p_bad = _minimal_proto("Bad")
        result = analyze([p_good, p_bad])
        self.assertEqual(result["worst_governed"], "Bad")

    def test_average_score_correct(self):
        p1 = _proto("A", voter_participation_pct=25.0, proposals_last_90d=12,
                    top10_holder_pct=20.0, timelock_hours=72,
                    multisig_required=True, community_forum_active=True,
                    governance_token_circulating_pct=80.0)
        p2 = _minimal_proto("B")
        result = analyze([p1, p2])
        scores = [x["governance_score"] for x in result["protocols"]]
        expected_avg = sum(scores) / len(scores)
        self.assertAlmostEqual(result["average_score"], round(expected_avg, 4), places=3)

    def test_timestamp_is_float(self):
        result = analyze([_proto()])
        self.assertIsInstance(result["timestamp"], float)

    def test_grade_in_valid_set(self):
        for p in [_proto(), _minimal_proto(), _max_proto()]:
            result = analyze([p])
            grade = result["protocols"][0]["grade"]
            self.assertIn(grade, {"A", "B", "C", "D", "F"})

    def test_governance_label_in_valid_set(self):
        for p in [_proto(), _minimal_proto(), _max_proto()]:
            result = analyze([p])
            label = result["protocols"][0]["governance_label"]
            self.assertIn(label, {"EXCELLENT", "GOOD", "ADEQUATE", "WEAK", "CRITICAL"})

    def test_centralization_risk_in_valid_set(self):
        for p in [_proto(), _minimal_proto(), _max_proto()]:
            result = analyze([p])
            risk = result["protocols"][0]["centralization_risk"]
            self.assertIn(risk, {"LOW", "MEDIUM", "HIGH", "EXTREME"})

    def test_flags_is_list(self):
        result = analyze([_minimal_proto()])
        self.assertIsInstance(result["protocols"][0]["flags"], list)

    def test_strengths_is_list(self):
        result = analyze([_max_proto()])
        self.assertIsInstance(result["protocols"][0]["strengths"], list)

    def test_custom_min_participation(self):
        # With high threshold, moderate participation should be flagged
        p = _proto(voter_participation_pct=8.0)
        result = analyze([p], config={"min_participation": 15.0})
        flags = result["protocols"][0]["flags"]
        self.assertTrue(any("participation" in f.lower() for f in flags))

    def test_three_protocols_ranking(self):
        p1 = _max_proto("Best")
        p2 = _proto("Mid")
        p3 = _minimal_proto("Worst")
        result = analyze([p1, p2, p3])
        self.assertEqual(len(result["protocols"]), 3)
        self.assertEqual(result["best_governed"], "Best")
        self.assertEqual(result["worst_governed"], "Worst")

    def test_no_timelock_flag_via_has_timelock_false(self):
        p = _proto(has_timelock=False, timelock_hours=24)
        result = analyze([p])
        flags = result["protocols"][0]["flags"]
        # has_timelock=False should trigger the flag regardless of timelock_hours
        self.assertIn("No timelock on governance", flags)

    def test_score_does_not_exceed_100(self):
        # Even with all maxed-out values, capped at 100
        p = _max_proto()
        result = analyze([p])
        self.assertLessEqual(result["protocols"][0]["governance_score"], 100)

    def test_multiple_protocols_returns_all(self):
        protocols = [_proto(name=f"P{i}") for i in range(5)]
        result = analyze(protocols)
        self.assertEqual(len(result["protocols"]), 5)


class TestLogResult(unittest.TestCase):
    """10 tests for log_result and atomic write helpers."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()
        self._log_path = os.path.join(self._tmp_dir, "gov_test_log.json")

    def test_log_creates_file(self):
        result = analyze([_proto()])
        log_result(result, self._log_path)
        self.assertTrue(os.path.exists(self._log_path))

    def test_log_is_list(self):
        log_result(analyze([_proto()]), self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends(self):
        for _ in range(4):
            log_result(analyze([_proto()]), self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 4)

    def test_log_caps_at_100(self):
        for i in range(110):
            log_result({"i": i, "timestamp": float(i)}, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_log_keeps_newest(self):
        for i in range(105):
            log_result({"i": i, "timestamp": float(i)}, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["i"], 5)
        self.assertEqual(data[-1]["i"], 104)

    def test_init_log_creates_empty_list(self):
        path = os.path.join(self._tmp_dir, "new.json")
        _init_log(path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data, [])

    def test_init_log_no_overwrite(self):
        path = os.path.join(self._tmp_dir, "existing.json")
        _atomic_write(path, [{"x": 1}])
        _init_log(path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_atomic_write_valid_json(self):
        path = os.path.join(self._tmp_dir, "atomic.json")
        _atomic_write(path, {"gov": "test", "v": 42})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["gov"], "test")

    def test_log_result_stores_protocols_key(self):
        result = analyze([_proto("Logged")])
        log_result(result, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertIn("protocols", data[0])

    def test_corrupt_log_handled_gracefully(self):
        path = os.path.join(self._tmp_dir, "corrupt.json")
        with open(path, "w") as f:
            f.write("{{NOT JSON}}")
        log_result({"x": 1}, path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
