"""
Tests for MP-794 BridgeRiskAssessor.
Run: python3 -m pytest spa_core/tests/test_bridge_risk_assessor.py -v
"""

import json
import os
import tempfile
import time
import unittest

from spa_core.analytics.bridge_risk_assessor import (
    BridgeRiskAssessor,
    BRIDGE_TIER_TRUSTED,
    BRIDGE_TIER_ESTABLISHED,
    BRIDGE_TIER_CAUTION,
    BRIDGE_TIER_AVOID,
    BRIDGE_TYPE_NATIVE,
    BRIDGE_TYPE_LIQUIDITY,
    BRIDGE_TYPE_LOCK_MINT,
    _compute_incident_penalty,
    _compute_audit_score,
    _compute_usage_score,
    _get_bridge_tier,
    _RECENT_WINDOW_SECONDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now():
    return time.time()


def _recent_ts(offset_seconds=0):
    """Timestamp that is within the recent window."""
    return _now() - 60 - offset_seconds  # 60 s ago, well within 1 year


def _old_ts():
    """Timestamp older than _RECENT_WINDOW_SECONDS."""
    return _now() - _RECENT_WINDOW_SECONDS - 86400  # 1 year + 1 day ago


def _perfect_bridge(bridge_name="Stargate"):
    """Best possible bridge: NATIVE, 3 audits, recent, $100 M volume, no incidents."""
    return {
        "bridge_name": bridge_name,
        "total_value_bridged_usd": 500_000_000.0,
        "incident_history": [],
        "audit_count": 3,
        "days_since_last_audit": 30.0,
        "bridge_type": BRIDGE_TYPE_NATIVE,
        "daily_volume_usd": 100_000_000.0,  # $100 M
    }


def _terrible_bridge(bridge_name="SketchBridge"):
    """Worst possible bridge: LOCK_MINT, 0 audits, huge losses, low volume."""
    return {
        "bridge_name": bridge_name,
        "total_value_bridged_usd": 10_000_000.0,
        "incident_history": [
            {"date_ts": _recent_ts(), "loss_usd": 4_000_000.0, "type": "hack"},
        ],
        "audit_count": 0,
        "days_since_last_audit": 9999.0,
        "bridge_type": BRIDGE_TYPE_LOCK_MINT,
        "daily_volume_usd": 1_000.0,
    }


def _make_assessor(max_entries=100):
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    return BridgeRiskAssessor(log_path=tmp.name, max_entries=max_entries), tmp.name


def _cleanup(path):
    for f in [path, path + ".tmp"]:
        try:
            os.unlink(f)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Group 1: Initialization
# ---------------------------------------------------------------------------

class TestInit(unittest.TestCase):

    def test_default_log_path(self):
        a = BridgeRiskAssessor()
        self.assertEqual(a.log_path, "data/bridge_risk_log.json")

    def test_default_max_entries(self):
        a = BridgeRiskAssessor()
        self.assertEqual(a.max_entries, 100)

    def test_custom_log_path(self):
        a = BridgeRiskAssessor(log_path="/tmp/br.json")
        self.assertEqual(a.log_path, "/tmp/br.json")

    def test_custom_max_entries(self):
        a = BridgeRiskAssessor(max_entries=25)
        self.assertEqual(a.max_entries, 25)

    def test_last_result_initially_none(self):
        a = BridgeRiskAssessor()
        self.assertIsNone(a._last_result)


# ---------------------------------------------------------------------------
# Group 2: _compute_incident_penalty
# ---------------------------------------------------------------------------

class TestIncidentPenalty(unittest.TestCase):

    def test_no_incidents_penalty_zero(self):
        self.assertEqual(_compute_incident_penalty([], tvb=1_000_000), 0.0)

    def test_empty_list_penalty_zero(self):
        self.assertEqual(_compute_incident_penalty([], tvb=0), 0.0)

    def test_small_loss_small_penalty(self):
        # loss=10000 on TVB=1000000 → ratio=0.01 → penalty=1.0
        incidents = [{"date_ts": _old_ts(), "loss_usd": 10_000}]
        penalty = _compute_incident_penalty(incidents, tvb=1_000_000)
        self.assertAlmostEqual(penalty, 1.0, places=4)

    def test_large_loss_capped_at_40(self):
        # loss=800000 on TVB=100000 → ratio=8 → penalty would be 800, capped at 40
        incidents = [{"date_ts": _old_ts(), "loss_usd": 800_000}]
        penalty = _compute_incident_penalty(incidents, tvb=100_000)
        self.assertEqual(penalty, 40.0)

    def test_recent_incident_weighted_2x(self):
        ts_recent = _recent_ts()
        ts_old = _old_ts()
        # Old incident: loss=5000 on TVB=100000 → ratio=0.05 → penalty=5
        # Recent incident: loss=5000 → 5000*2=10000 → ratio=0.1 → penalty=10
        old_incident = [{"date_ts": ts_old, "loss_usd": 5_000}]
        recent_incident = [{"date_ts": ts_recent, "loss_usd": 5_000}]
        p_old = _compute_incident_penalty(old_incident, tvb=100_000)
        p_recent = _compute_incident_penalty(recent_incident, tvb=100_000)
        self.assertAlmostEqual(p_recent, 2 * p_old, places=4)

    def test_old_incident_not_doubled(self):
        ts_old = _old_ts()
        incidents = [{"date_ts": ts_old, "loss_usd": 10_000}]
        # 10000 / 1000000 * 100 = 1.0
        penalty = _compute_incident_penalty(incidents, tvb=1_000_000)
        self.assertAlmostEqual(penalty, 1.0, places=4)

    def test_mixed_recent_and_old(self):
        ts_recent = _recent_ts()
        ts_old = _old_ts()
        incidents = [
            {"date_ts": ts_recent, "loss_usd": 5_000},   # weighted 2x → 10000
            {"date_ts": ts_old, "loss_usd": 5_000},       # weighted 1x → 5000
        ]
        # weighted_loss = 15000 on TVB=1_000_000 → ratio=0.015 → penalty=1.5
        penalty = _compute_incident_penalty(incidents, tvb=1_000_000)
        self.assertAlmostEqual(penalty, 1.5, places=4)

    def test_zero_tvb_with_incidents_max_penalty(self):
        incidents = [{"date_ts": _recent_ts(), "loss_usd": 1_000}]
        penalty = _compute_incident_penalty(incidents, tvb=0.0)
        self.assertEqual(penalty, 40.0)

    def test_zero_tvb_no_incidents_zero_penalty(self):
        penalty = _compute_incident_penalty([], tvb=0.0)
        self.assertEqual(penalty, 0.0)

    def test_40pct_loss_ratio_gives_40_penalty(self):
        # loss=400000 on TVB=1000000 → ratio=0.4 → penalty=40
        incidents = [{"date_ts": _old_ts(), "loss_usd": 400_000}]
        penalty = _compute_incident_penalty(incidents, tvb=1_000_000)
        self.assertAlmostEqual(penalty, 40.0, places=4)

    def test_penalty_capped_at_40(self):
        incidents = [{"date_ts": _old_ts(), "loss_usd": 999_999_999}]
        penalty = _compute_incident_penalty(incidents, tvb=1_000)
        self.assertEqual(penalty, 40.0)

    def test_multiple_recent_incidents_accumulate(self):
        ts = _recent_ts()
        incidents = [
            {"date_ts": ts, "loss_usd": 10_000},
            {"date_ts": ts, "loss_usd": 10_000},
        ]
        # weighted_loss = 40000 on TVB=1_000_000 → ratio=0.04 → penalty=4
        penalty = _compute_incident_penalty(incidents, tvb=1_000_000)
        self.assertAlmostEqual(penalty, 4.0, places=4)

    def test_zero_loss_incident_no_penalty(self):
        incidents = [{"date_ts": _recent_ts(), "loss_usd": 0.0}]
        penalty = _compute_incident_penalty(incidents, tvb=1_000_000)
        self.assertAlmostEqual(penalty, 0.0, places=6)

    def test_penalty_nonnegative(self):
        for tvb in [0, 1000, 1_000_000]:
            penalty = _compute_incident_penalty([], tvb=tvb)
            self.assertGreaterEqual(penalty, 0.0)


# ---------------------------------------------------------------------------
# Group 3: _compute_audit_score
# ---------------------------------------------------------------------------

class TestAuditScore(unittest.TestCase):

    def test_zero_audits_score_zero(self):
        self.assertEqual(_compute_audit_score(0, 0), 0.0)

    def test_one_audit_score_10(self):
        self.assertAlmostEqual(_compute_audit_score(1, 0), 10.0, places=4)

    def test_two_audits_score_20(self):
        self.assertAlmostEqual(_compute_audit_score(2, 0), 20.0, places=4)

    def test_three_audits_score_30(self):
        self.assertAlmostEqual(_compute_audit_score(3, 0), 30.0, places=4)

    def test_four_audits_capped_at_30(self):
        self.assertAlmostEqual(_compute_audit_score(4, 0), 30.0, places=4)

    def test_ten_audits_capped_at_30(self):
        self.assertAlmostEqual(_compute_audit_score(10, 0), 30.0, places=4)

    def test_stale_penalty_over_180_days(self):
        # 2 audits = 20 base, stale → 20 - 10 = 10
        self.assertAlmostEqual(_compute_audit_score(2, 181.0), 10.0, places=4)

    def test_stale_penalty_boundary_exactly_180(self):
        # 180.0 is NOT > 180, so no penalty
        self.assertAlmostEqual(_compute_audit_score(2, 180.0), 20.0, places=4)

    def test_stale_penalty_just_over_180(self):
        self.assertAlmostEqual(_compute_audit_score(2, 180.001), 10.0, places=4)

    def test_no_stale_penalty_under_180(self):
        self.assertAlmostEqual(_compute_audit_score(3, 90.0), 30.0, places=4)

    def test_stale_penalty_zero_audits_stays_zero(self):
        self.assertAlmostEqual(_compute_audit_score(0, 365), 0.0, places=4)

    def test_stale_penalty_one_audit_over_180(self):
        # 1 audit = 10 base, stale → 10 - 10 = 0
        self.assertAlmostEqual(_compute_audit_score(1, 200), 0.0, places=4)

    def test_stale_does_not_go_negative(self):
        score = _compute_audit_score(0, 9999)
        self.assertGreaterEqual(score, 0.0)


# ---------------------------------------------------------------------------
# Group 4: _compute_usage_score
# ---------------------------------------------------------------------------

class TestUsageScore(unittest.TestCase):

    def test_zero_volume_score_zero(self):
        self.assertAlmostEqual(_compute_usage_score(0), 0.0, places=4)

    def test_negative_volume_score_zero(self):
        self.assertAlmostEqual(_compute_usage_score(-1000), 0.0, places=4)

    def test_100M_volume_score_20(self):
        # log10(1e8) / 8 * 20 = 20
        self.assertAlmostEqual(_compute_usage_score(100_000_000), 20.0, places=4)

    def test_very_high_volume_capped_at_20(self):
        self.assertAlmostEqual(_compute_usage_score(10_000_000_000), 20.0, places=4)

    def test_1M_volume_score_15(self):
        # log10(1e6)=6, (6/8)*20=15
        self.assertAlmostEqual(_compute_usage_score(1_000_000), 15.0, places=4)

    def test_10K_volume_score_10(self):
        # log10(10000)=4, (4/8)*20=10
        self.assertAlmostEqual(_compute_usage_score(10_000), 10.0, places=4)

    def test_100_volume_score_5(self):
        # log10(100)=2, (2/8)*20=5
        self.assertAlmostEqual(_compute_usage_score(100), 5.0, places=4)

    def test_score_nonnegative(self):
        for v in [0, 1, 100, 1_000, 1_000_000]:
            self.assertGreaterEqual(_compute_usage_score(v), 0.0)

    def test_score_monotonically_increasing(self):
        volumes = [1_000, 10_000, 100_000, 1_000_000, 10_000_000]
        scores = [_compute_usage_score(v) for v in volumes]
        for i in range(len(scores) - 1):
            self.assertLess(scores[i], scores[i + 1])


# ---------------------------------------------------------------------------
# Group 5: _get_bridge_tier
# ---------------------------------------------------------------------------

class TestGetBridgeTier(unittest.TestCase):

    def test_trusted_at_75(self):
        self.assertEqual(_get_bridge_tier(75.0), BRIDGE_TIER_TRUSTED)

    def test_trusted_at_100(self):
        self.assertEqual(_get_bridge_tier(100.0), BRIDGE_TIER_TRUSTED)

    def test_established_at_74(self):
        self.assertEqual(_get_bridge_tier(74.9), BRIDGE_TIER_ESTABLISHED)

    def test_established_at_50(self):
        self.assertEqual(_get_bridge_tier(50.0), BRIDGE_TIER_ESTABLISHED)

    def test_caution_at_49(self):
        self.assertEqual(_get_bridge_tier(49.9), BRIDGE_TIER_CAUTION)

    def test_caution_at_25(self):
        self.assertEqual(_get_bridge_tier(25.0), BRIDGE_TIER_CAUTION)

    def test_avoid_at_24(self):
        self.assertEqual(_get_bridge_tier(24.9), BRIDGE_TIER_AVOID)

    def test_avoid_at_0(self):
        self.assertEqual(_get_bridge_tier(0.0), BRIDGE_TIER_AVOID)


# ---------------------------------------------------------------------------
# Group 6: type scores
# ---------------------------------------------------------------------------

class TestTypeScore(unittest.TestCase):

    def setUp(self):
        self.a, self.path = _make_assessor()

    def tearDown(self):
        _cleanup(self.path)

    def test_native_type_score_10(self):
        bd = _perfect_bridge()
        bd["bridge_type"] = BRIDGE_TYPE_NATIVE
        result = self.a.assess(bd)
        self.assertEqual(result["type_score"], 10)

    def test_liquidity_type_score_7(self):
        bd = _perfect_bridge()
        bd["bridge_type"] = BRIDGE_TYPE_LIQUIDITY
        result = self.a.assess(bd)
        self.assertEqual(result["type_score"], 7)

    def test_lock_mint_type_score_4(self):
        bd = _perfect_bridge()
        bd["bridge_type"] = BRIDGE_TYPE_LOCK_MINT
        result = self.a.assess(bd)
        self.assertEqual(result["type_score"], 4)

    def test_unknown_type_defaults_to_lock_mint_score(self):
        bd = _perfect_bridge()
        bd["bridge_type"] = "UNKNOWN_TYPE"
        result = self.a.assess(bd)
        self.assertEqual(result["type_score"], 4)


# ---------------------------------------------------------------------------
# Group 7: Total score & tier via assess()
# ---------------------------------------------------------------------------

class TestTotalScoreAndTier(unittest.TestCase):

    def setUp(self):
        self.a, self.path = _make_assessor()

    def tearDown(self):
        _cleanup(self.path)

    def test_perfect_bridge_is_trusted(self):
        result = self.a.assess(_perfect_bridge())
        self.assertEqual(result["bridge_tier"], BRIDGE_TIER_TRUSTED)

    def test_terrible_bridge_is_avoid_or_caution(self):
        result = self.a.assess(_terrible_bridge())
        self.assertIn(result["bridge_tier"], [BRIDGE_TIER_AVOID, BRIDGE_TIER_CAUTION])

    def test_score_capped_at_100(self):
        result = self.a.assess(_perfect_bridge())
        self.assertLessEqual(result["total_bridge_score"], 100.0)

    def test_score_min_0(self):
        result = self.a.assess(_terrible_bridge())
        self.assertGreaterEqual(result["total_bridge_score"], 0.0)

    def test_score_between_0_and_100(self):
        for bd in [_perfect_bridge(), _terrible_bridge()]:
            result = self.a.assess(bd)
            self.assertGreaterEqual(result["total_bridge_score"], 0.0)
            self.assertLessEqual(result["total_bridge_score"], 100.0)

    def test_established_bridge(self):
        bd = {
            "bridge_name": "MediumBridge",
            "total_value_bridged_usd": 100_000_000.0,
            "incident_history": [],
            "audit_count": 1,
            "days_since_last_audit": 90.0,
            "bridge_type": BRIDGE_TYPE_LIQUIDITY,
            "daily_volume_usd": 1_000_000.0,
        }
        result = self.a.assess(bd)
        # incident_component=40, audit=10, usage=15, type=7 → 72 → TRUSTED
        self.assertGreaterEqual(result["total_bridge_score"], 50.0)

    def test_total_score_components_sum_correctly(self):
        bd = _perfect_bridge()
        result = self.a.assess(bd)
        expected = (
            result["incident_component"]
            + result["audit_score"]
            + result["usage_score"]
            + result["type_score"]
        )
        self.assertAlmostEqual(
            result["total_bridge_score"],
            min(100.0, max(0.0, expected)),
            places=4,
        )

    def test_no_incidents_incident_component_is_40(self):
        bd = _perfect_bridge()
        bd["incident_history"] = []
        result = self.a.assess(bd)
        self.assertAlmostEqual(result["incident_component"], 40.0, places=4)

    def test_max_incident_penalty_incident_component_zero(self):
        bd = _perfect_bridge()
        # force penalty = 40 by huge recent loss
        bd["incident_history"] = [
            {"date_ts": _recent_ts(), "loss_usd": 999_999_999}
        ]
        result = self.a.assess(bd)
        self.assertAlmostEqual(result["incident_component"], 0.0, places=4)

    def test_native_beats_lock_mint_same_otherwise(self):
        base = {
            "total_value_bridged_usd": 50_000_000.0,
            "incident_history": [],
            "audit_count": 2,
            "days_since_last_audit": 60.0,
            "daily_volume_usd": 1_000_000.0,
        }
        native = dict(base, bridge_name="Native", bridge_type=BRIDGE_TYPE_NATIVE)
        lock = dict(base, bridge_name="Lock", bridge_type=BRIDGE_TYPE_LOCK_MINT)
        r_native = self.a.assess(native)
        r_lock = self.a.assess(lock)
        self.assertGreater(r_native["total_bridge_score"], r_lock["total_bridge_score"])

    def test_more_audits_better_score_same_otherwise(self):
        base = {
            "bridge_name": "TestBridge",
            "total_value_bridged_usd": 50_000_000.0,
            "incident_history": [],
            "days_since_last_audit": 60.0,
            "bridge_type": BRIDGE_TYPE_LIQUIDITY,
            "daily_volume_usd": 1_000_000.0,
        }
        r0 = self.a.assess(dict(base, audit_count=0))
        r3 = self.a.assess(dict(base, audit_count=3))
        self.assertGreater(r3["total_bridge_score"], r0["total_bridge_score"])


# ---------------------------------------------------------------------------
# Group 8: assess() method structure
# ---------------------------------------------------------------------------

class TestAssessMethod(unittest.TestCase):

    def setUp(self):
        self.a, self.path = _make_assessor()

    def tearDown(self):
        _cleanup(self.path)

    def test_assess_returns_dict(self):
        result = self.a.assess(_perfect_bridge())
        self.assertIsInstance(result, dict)

    def test_assess_bridge_name_in_result(self):
        result = self.a.assess(_perfect_bridge("MyBridge"))
        self.assertEqual(result["bridge_name"], "MyBridge")

    def test_assess_timestamp_present(self):
        result = self.a.assess(_perfect_bridge())
        self.assertIn("timestamp", result)
        self.assertAlmostEqual(result["timestamp"], time.time(), delta=5)

    def test_assess_incident_count_in_result(self):
        bd = _perfect_bridge()
        bd["incident_history"] = [
            {"date_ts": _recent_ts(), "loss_usd": 1000},
            {"date_ts": _old_ts(), "loss_usd": 2000},
        ]
        result = self.a.assess(bd)
        self.assertEqual(result["incident_count"], 2)

    def test_assess_zero_incidents_count(self):
        result = self.a.assess(_perfect_bridge())
        self.assertEqual(result["incident_count"], 0)

    def test_assess_bridge_type_preserved(self):
        result = self.a.assess(_perfect_bridge())
        self.assertEqual(result["bridge_type"], BRIDGE_TYPE_NATIVE)

    def test_assess_stores_last_result(self):
        self.assertIsNone(self.a._last_result)
        self.a.assess(_perfect_bridge())
        self.assertIsNotNone(self.a._last_result)

    def test_assess_all_score_keys_present(self):
        result = self.a.assess(_perfect_bridge())
        for key in [
            "incident_penalty", "incident_component", "audit_score",
            "usage_score", "type_score", "total_bridge_score", "bridge_tier",
        ]:
            self.assertIn(key, result)

    def test_assess_daily_volume_in_result(self):
        result = self.a.assess(_perfect_bridge())
        self.assertIn("daily_volume_usd", result)

    def test_assess_default_bridge_name_unknown(self):
        result = self.a.assess({})
        self.assertEqual(result["bridge_name"], "unknown")

    def test_assess_default_type_lock_mint(self):
        result = self.a.assess({"bridge_name": "X", "total_value_bridged_usd": 1e6})
        self.assertEqual(result["bridge_type"], BRIDGE_TYPE_LOCK_MINT)


# ---------------------------------------------------------------------------
# Group 9: get_bridge_tier() and get_risk_summary()
# ---------------------------------------------------------------------------

class TestGetTierAndSummary(unittest.TestCase):

    def setUp(self):
        self.a, self.path = _make_assessor()

    def tearDown(self):
        _cleanup(self.path)

    def test_get_bridge_tier_before_assess_is_none(self):
        self.assertIsNone(self.a.get_bridge_tier())

    def test_get_bridge_tier_after_assess_trusted(self):
        self.a.assess(_perfect_bridge())
        self.assertEqual(self.a.get_bridge_tier(), BRIDGE_TIER_TRUSTED)

    def test_get_bridge_tier_after_assess_avoid(self):
        self.a.assess(_terrible_bridge())
        tier = self.a.get_bridge_tier()
        self.assertIn(tier, [BRIDGE_TIER_AVOID, BRIDGE_TIER_CAUTION])

    def test_get_bridge_tier_updates_after_second_assess(self):
        self.a.assess(_perfect_bridge())
        self.a.assess(_terrible_bridge())
        tier = self.a.get_bridge_tier()
        self.assertNotEqual(tier, BRIDGE_TIER_TRUSTED)

    def test_get_risk_summary_before_assess_empty(self):
        self.assertEqual(self.a.get_risk_summary(), {})

    def test_get_risk_summary_after_assess_has_keys(self):
        self.a.assess(_perfect_bridge("MyStar"))
        summary = self.a.get_risk_summary()
        for key in [
            "bridge_name", "total_bridge_score", "bridge_tier",
            "incident_penalty", "audit_score", "usage_score", "type_score",
            "incident_count",
        ]:
            self.assertIn(key, summary)

    def test_get_risk_summary_bridge_name(self):
        self.a.assess(_perfect_bridge("StarBridge"))
        summary = self.a.get_risk_summary()
        self.assertEqual(summary["bridge_name"], "StarBridge")

    def test_get_risk_summary_tier_matches_assess(self):
        result = self.a.assess(_perfect_bridge())
        summary = self.a.get_risk_summary()
        self.assertEqual(summary["bridge_tier"], result["bridge_tier"])

    def test_get_risk_summary_score_matches_assess(self):
        result = self.a.assess(_perfect_bridge())
        summary = self.a.get_risk_summary()
        self.assertAlmostEqual(
            summary["total_bridge_score"], result["total_bridge_score"], places=4
        )


# ---------------------------------------------------------------------------
# Group 10: Ring buffer & persistence
# ---------------------------------------------------------------------------

class TestRingBuffer(unittest.TestCase):

    def test_log_file_created_after_assess(self):
        a, path = _make_assessor()
        os.unlink(path)
        try:
            a.assess(_perfect_bridge())
            self.assertTrue(os.path.exists(path))
        finally:
            _cleanup(path)

    def test_log_is_list(self):
        a, path = _make_assessor()
        try:
            a.assess(_perfect_bridge())
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
        finally:
            _cleanup(path)

    def test_log_grows_on_multiple_assess(self):
        a, path = _make_assessor()
        try:
            a.assess(_perfect_bridge())
            a.assess(_terrible_bridge())
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)
        finally:
            _cleanup(path)

    def test_log_capped_at_max_entries(self):
        a, path = _make_assessor(max_entries=3)
        try:
            for i in range(6):
                bd = _perfect_bridge(f"Bridge{i}")
                a.assess(bd)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)
        finally:
            _cleanup(path)

    def test_log_contains_bridge_name(self):
        a, path = _make_assessor()
        try:
            a.assess(_perfect_bridge("Alpha"))
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data[0]["bridge_name"], "Alpha")
        finally:
            _cleanup(path)

    def test_log_keeps_newest_on_cap(self):
        a, path = _make_assessor(max_entries=2)
        try:
            for name in ["A", "B", "C", "D"]:
                a.assess(_perfect_bridge(name))
            with open(path) as f:
                data = json.load(f)
            names = [d["bridge_name"] for d in data]
            self.assertIn("C", names)
            self.assertIn("D", names)
            self.assertNotIn("A", names)
        finally:
            _cleanup(path)

    def test_directory_created_automatically(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "deep", "nested", "br.json")
            a = BridgeRiskAssessor(log_path=log_path)
            a.assess(_perfect_bridge())
            self.assertTrue(os.path.exists(log_path))

    def test_log_valid_json_after_write(self):
        a, path = _make_assessor()
        try:
            a.assess(_perfect_bridge())
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
        finally:
            _cleanup(path)


if __name__ == "__main__":
    unittest.main()
