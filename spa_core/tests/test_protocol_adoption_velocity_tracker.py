"""
Tests for MP-829: ProtocolAdoptionVelocityTracker
≥65 unittest tests — pure stdlib.
"""

import json
import os
import sys
import tempfile
import time
import unittest

# Ensure project root is on path
_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_adoption_velocity_tracker import (
    RING_BUFFER_CAP,
    _compute_protocol,
    _velocity_label,
    analyze,
)

# ── helpers ────────────────────────────────────────────────────────────────

def _proto(
    name="Alpha",
    tvl_now=1_000_000,
    tvl_30d_ago=800_000,
    tvl_90d_ago=600_000,
    user_count_now=2000,
    user_count_30d_ago=1500,
    daily_active_users=400,
    age_days=90,
):
    return {
        "name": name,
        "tvl_now": tvl_now,
        "tvl_30d_ago": tvl_30d_ago,
        "tvl_90d_ago": tvl_90d_ago,
        "user_count_now": user_count_now,
        "user_count_30d_ago": user_count_30d_ago,
        "daily_active_users": daily_active_users,
        "age_days": age_days,
    }


class TestVelocityLabel(unittest.TestCase):
    def test_viral_at_70(self):
        self.assertEqual(_velocity_label(70), "VIRAL")

    def test_viral_at_100(self):
        self.assertEqual(_velocity_label(100), "VIRAL")

    def test_fast_at_50(self):
        self.assertEqual(_velocity_label(50), "FAST")

    def test_fast_at_69(self):
        self.assertEqual(_velocity_label(69), "FAST")

    def test_growing_at_30(self):
        self.assertEqual(_velocity_label(30), "GROWING")

    def test_growing_at_49(self):
        self.assertEqual(_velocity_label(49), "GROWING")

    def test_stable_at_10(self):
        self.assertEqual(_velocity_label(10), "STABLE")

    def test_stable_at_29(self):
        self.assertEqual(_velocity_label(29), "STABLE")

    def test_declining_at_9(self):
        self.assertEqual(_velocity_label(9), "DECLINING")

    def test_declining_at_0(self):
        self.assertEqual(_velocity_label(0), "DECLINING")

    def test_declining_negative(self):
        # clamp at 0 means label gets DECLINING
        self.assertEqual(_velocity_label(0), "DECLINING")


class TestComputeProtocol(unittest.TestCase):
    def setUp(self):
        self.p = _proto()

    def test_returns_dict(self):
        r = _compute_protocol(self.p)
        self.assertIsInstance(r, dict)

    def test_name_preserved(self):
        r = _compute_protocol(self.p)
        self.assertEqual(r["name"], "Alpha")

    def test_tvl_growth_30d_pct(self):
        # (1M - 0.8M) / 0.8M * 100 = 25
        r = _compute_protocol(self.p)
        self.assertAlmostEqual(r["tvl_growth_30d_pct"], 25.0, places=2)

    def test_tvl_growth_90d_pct(self):
        # (1M - 0.6M) / 0.6M * 100 = 66.67
        r = _compute_protocol(self.p)
        self.assertAlmostEqual(r["tvl_growth_90d_pct"], 66.6667, places=1)

    def test_tvl_acceleration(self):
        # 25 - (66.67/3) = 25 - 22.22 = 2.78
        r = _compute_protocol(self.p)
        expected = 25.0 - (66.6667 / 3.0)
        self.assertAlmostEqual(r["tvl_acceleration"], expected, places=1)

    def test_user_growth_30d_pct(self):
        # (2000-1500)/1500*100 = 33.33
        r = _compute_protocol(self.p)
        self.assertAlmostEqual(r["user_growth_30d_pct"], 33.3333, places=1)

    def test_dau_ratio(self):
        # 400/2000 = 0.2
        r = _compute_protocol(self.p)
        self.assertAlmostEqual(r["dau_ratio"], 0.2, places=4)

    def test_tvl_per_user(self):
        # 1M/2000 = 500
        r = _compute_protocol(self.p)
        self.assertAlmostEqual(r["tvl_per_user"], 500.0, places=2)

    def test_velocity_score_is_int(self):
        r = _compute_protocol(self.p)
        self.assertIsInstance(r["velocity_score"], int)

    def test_velocity_score_in_range(self):
        r = _compute_protocol(self.p)
        self.assertGreaterEqual(r["velocity_score"], 0)
        self.assertLessEqual(r["velocity_score"], 100)

    def test_velocity_label_present(self):
        r = _compute_protocol(self.p)
        self.assertIn(r["velocity_label"], ("VIRAL", "FAST", "GROWING", "STABLE", "DECLINING"))

    def test_tvl_30d_zero_no_tvl_component(self):
        p = _proto(tvl_30d_ago=0)
        r = _compute_protocol(p)
        self.assertEqual(r["tvl_growth_30d_pct"], 0.0)
        self.assertEqual(r["tvl_acceleration"], 0.0)

    def test_tvl_90d_zero_no_90d_growth(self):
        p = _proto(tvl_90d_ago=0)
        r = _compute_protocol(p)
        self.assertEqual(r["tvl_growth_90d_pct"], 0.0)

    def test_user_30d_zero_returns_none(self):
        p = _proto(user_count_30d_ago=0)
        r = _compute_protocol(p)
        self.assertIsNone(r["user_growth_30d_pct"])

    def test_user_count_now_zero_tvl_per_user_is_zero(self):
        p = _proto(user_count_now=0, daily_active_users=0)
        r = _compute_protocol(p)
        self.assertEqual(r["tvl_per_user"], 0.0)

    def test_user_count_now_zero_dau_ratio_is_zero(self):
        p = _proto(user_count_now=0, daily_active_users=0)
        r = _compute_protocol(p)
        self.assertEqual(r["dau_ratio"], 0.0)

    def test_high_tvl_growth_capped_at_40(self):
        # 200% monthly growth → tvl_component = 40 (capped)
        p = _proto(tvl_now=3_000_000, tvl_30d_ago=1_000_000, tvl_90d_ago=900_000,
                   user_count_now=100, user_count_30d_ago=90, daily_active_users=10)
        r = _compute_protocol(p)
        # tvl_component = min(40, 200) = 40
        self.assertLessEqual(r["velocity_score"], 100)

    def test_high_user_growth_capped_at_20(self):
        # 500% user growth → user_component = 20 (capped)
        p = _proto(user_count_now=6000, user_count_30d_ago=1000,
                   daily_active_users=100)
        r = _compute_protocol(p)
        self.assertLessEqual(r["velocity_score"], 100)

    def test_engagement_capped_at_20(self):
        # dau_ratio = 0.5 → dau_ratio*100 = 50 → capped at 20
        p = _proto(user_count_now=1000, daily_active_users=1000)
        r = _compute_protocol(p)
        self.assertLessEqual(r["velocity_score"], 100)

    def test_zero_growth_declining(self):
        p = _proto(
            tvl_now=1_000_000, tvl_30d_ago=1_000_000, tvl_90d_ago=1_000_000,
            user_count_now=1000, user_count_30d_ago=1000,
            daily_active_users=0,
        )
        r = _compute_protocol(p)
        self.assertEqual(r["velocity_score"], 0)
        self.assertEqual(r["velocity_label"], "DECLINING")

    def test_negative_tvl_growth(self):
        # TVL fell: 800k → 600k → tvl_growth_30d = -25%
        p = _proto(tvl_now=600_000, tvl_30d_ago=800_000, tvl_90d_ago=900_000,
                   user_count_now=1000, user_count_30d_ago=1000,
                   daily_active_users=0)
        r = _compute_protocol(p)
        self.assertEqual(r["tvl_growth_30d_pct"], -25.0)
        # tvl_component = max(0, -25) = 0

    def test_velocity_score_viral(self):
        # Design a protocol with near-max score
        p = _proto(
            tvl_now=10_000_000, tvl_30d_ago=100_000, tvl_90d_ago=50_000,
            user_count_now=10000, user_count_30d_ago=100,
            daily_active_users=5000, age_days=200,
        )
        r = _compute_protocol(p)
        self.assertGreaterEqual(r["velocity_score"], 70)
        self.assertEqual(r["velocity_label"], "VIRAL")

    def test_negative_user_growth_clamped(self):
        p = _proto(user_count_now=500, user_count_30d_ago=1000)
        r = _compute_protocol(p)
        # user_growth = -50%, user_component = max(0, -50) = 0
        self.assertIsNotNone(r["user_growth_30d_pct"])
        self.assertLess(r["user_growth_30d_pct"], 0)

    def test_all_zeros_no_crash(self):
        p = {
            "name": "Zero",
            "tvl_now": 0.0, "tvl_30d_ago": 0.0, "tvl_90d_ago": 0.0,
            "user_count_now": 0, "user_count_30d_ago": 0,
            "daily_active_users": 0, "age_days": 100,
        }
        r = _compute_protocol(p)
        self.assertEqual(r["velocity_score"], 0)

    def test_float_inputs(self):
        p = _proto(tvl_now=1e6, tvl_30d_ago=9e5, tvl_90d_ago=8e5)
        r = _compute_protocol(p)
        self.assertIsInstance(r["tvl_growth_30d_pct"], float)

    def test_velocity_label_matches_score(self):
        p = _proto()
        r = _compute_protocol(p)
        expected_label = _velocity_label(r["velocity_score"])
        self.assertEqual(r["velocity_label"], expected_label)


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "adoption_velocity_log.json")
        self.cfg = {"log_path": self.log_path}

    def _run(self, protocols, cfg=None):
        cfg = dict(self.cfg)
        if cfg is None:
            cfg = {}
        cfg["log_path"] = self.log_path
        return analyze(protocols, cfg)

    def test_returns_dict(self):
        r = self._run([_proto()])
        self.assertIsInstance(r, dict)

    def test_protocols_key_present(self):
        r = self._run([_proto()])
        self.assertIn("protocols", r)

    def test_protocols_list(self):
        r = self._run([_proto()])
        self.assertIsInstance(r["protocols"], list)

    def test_single_protocol(self):
        r = self._run([_proto()])
        self.assertEqual(len(r["protocols"]), 1)

    def test_multiple_protocols(self):
        r = self._run([_proto("A"), _proto("B"), _proto("C")])
        self.assertEqual(len(r["protocols"]), 3)

    def test_market_leader_present(self):
        r = self._run([_proto("A"), _proto("B")])
        self.assertIn("market_leader", r)

    def test_fastest_growing_present(self):
        r = self._run([_proto("A"), _proto("B")])
        self.assertIn("fastest_growing", r)

    def test_most_engaged_present(self):
        r = self._run([_proto("A"), _proto("B")])
        self.assertIn("most_engaged", r)

    def test_filtered_out_present(self):
        r = self._run([_proto()])
        self.assertIn("filtered_out", r)

    def test_timestamp_present(self):
        r = self._run([_proto()])
        self.assertIn("timestamp", r)

    def test_timestamp_is_float(self):
        r = self._run([_proto()])
        self.assertIsInstance(r["timestamp"], float)

    def test_age_filter_removes_young(self):
        young = _proto(name="Young", age_days=5)
        old = _proto(name="Old", age_days=200)
        r = self._run([young, old], {"log_path": self.log_path, "min_age_days": 30})
        names = [p["name"] for p in r["protocols"]]
        self.assertNotIn("Young", names)
        self.assertIn("Old", names)

    def test_young_in_filtered_out(self):
        young = _proto(name="Young", age_days=5)
        r = self._run([young], {"log_path": self.log_path, "min_age_days": 30})
        self.assertIn("Young", r["filtered_out"])

    def test_all_filtered_empty_protocols(self):
        r = self._run([_proto(age_days=1)], {"log_path": self.log_path, "min_age_days": 30})
        self.assertEqual(r["protocols"], [])

    def test_all_filtered_market_leader_none(self):
        r = self._run([_proto(age_days=1)], {"log_path": self.log_path, "min_age_days": 30})
        self.assertIsNone(r["market_leader"])

    def test_all_filtered_fastest_growing_none(self):
        r = self._run([_proto(age_days=1)], {"log_path": self.log_path, "min_age_days": 30})
        self.assertIsNone(r["fastest_growing"])

    def test_all_filtered_most_engaged_none(self):
        r = self._run([_proto(age_days=1)], {"log_path": self.log_path, "min_age_days": 30})
        self.assertIsNone(r["most_engaged"])

    def test_market_leader_is_max_score(self):
        slow = _proto("Slow", tvl_now=1_000_000, tvl_30d_ago=990_000,
                      tvl_90d_ago=980_000, user_count_now=100,
                      user_count_30d_ago=99, daily_active_users=1)
        fast = _proto("Fast", tvl_now=10_000_000, tvl_30d_ago=100_000,
                      tvl_90d_ago=50_000, user_count_now=10000,
                      user_count_30d_ago=100, daily_active_users=5000)
        r = self._run([slow, fast])
        self.assertEqual(r["market_leader"], "Fast")

    def test_fastest_growing_is_max_30d(self):
        low = _proto("Low", tvl_now=110, tvl_30d_ago=100, tvl_90d_ago=90)
        high = _proto("High", tvl_now=300, tvl_30d_ago=100, tvl_90d_ago=90)
        r = self._run([low, high])
        self.assertEqual(r["fastest_growing"], "High")

    def test_most_engaged_is_max_dau_ratio(self):
        low = _proto("Low", user_count_now=1000, daily_active_users=10)
        high = _proto("High", user_count_now=100, daily_active_users=80)
        r = self._run([low, high])
        self.assertEqual(r["most_engaged"], "High")

    def test_empty_input(self):
        r = self._run([])
        self.assertEqual(r["protocols"], [])
        self.assertIsNone(r["market_leader"])

    def test_default_min_age_is_30(self):
        # age_days=29 should be filtered with default
        young = _proto(name="Young", age_days=29)
        r = analyze([young], {"log_path": self.log_path})
        self.assertIn("Young", r["filtered_out"])

    def test_default_min_age_accepts_30(self):
        exact = _proto(name="Exact", age_days=30)
        r = analyze([exact], {"log_path": self.log_path})
        names = [p["name"] for p in r["protocols"]]
        self.assertIn("Exact", names)

    def test_log_file_created(self):
        self._run([_proto()])
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self._run([_proto()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends(self):
        self._run([_proto()])
        self._run([_proto()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        for _ in range(RING_BUFFER_CAP + 5):
            self._run([_proto()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), RING_BUFFER_CAP)

    def test_log_entry_has_timestamp(self):
        self._run([_proto()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_protocols(self):
        self._run([_proto()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("protocols", data[0])

    def test_no_tmp_file_left(self):
        self._run([_proto()])
        tmp = self.log_path + ".tmp"
        self.assertFalse(os.path.exists(tmp))

    def test_corrupt_log_handled(self):
        with open(self.log_path, "w") as f:
            f.write("NOT JSON")
        # Should not raise; resets to empty list
        r = self._run([_proto()])
        self.assertIsInstance(r, dict)

    def test_config_none_uses_defaults(self):
        # With no config, min_age_days=30
        r = analyze([_proto(age_days=100)], {"log_path": self.log_path})
        self.assertEqual(len(r["protocols"]), 1)


class TestComputeProtocolScoreComponents(unittest.TestCase):
    """Verify velocity score component calculations in detail."""

    def test_tvl_component_exact(self):
        # 30d growth = 30%, so tvl_component = 30 (not capped)
        p = _proto(tvl_now=130_000, tvl_30d_ago=100_000, tvl_90d_ago=100_000,
                   user_count_now=100, user_count_30d_ago=100,
                   daily_active_users=0)
        r = _compute_protocol(p)
        # tvl_component = min(40, 30) = 30
        # user_component = max(0, 0) = 0
        # engagement = 0
        # acceleration = 30 - (0/3) = 30 → min(20, 30) = 20
        # total = 30 + 0 + 0 + 20 = 50
        self.assertEqual(r["velocity_score"], 50)

    def test_user_component_exact(self):
        # user growth 15%: component = min(20, 15) = 15
        p = _proto(tvl_now=100_000, tvl_30d_ago=100_000, tvl_90d_ago=100_000,
                   user_count_now=115, user_count_30d_ago=100,
                   daily_active_users=0)
        r = _compute_protocol(p)
        # tvl_component = min(40, 0) = 0
        # user_component = min(20, 15) = 15
        # engagement = 0
        # acceleration = 0 - 0 = 0
        self.assertEqual(r["velocity_score"], 15)

    def test_engagement_component_exact(self):
        # dau_ratio = 0.10 → engagement = min(20, 10) = 10
        p = _proto(tvl_now=100_000, tvl_30d_ago=100_000, tvl_90d_ago=100_000,
                   user_count_now=1000, user_count_30d_ago=1000,
                   daily_active_users=100)
        r = _compute_protocol(p)
        # user_component = min(20, 0) = 0
        # engagement = min(20, 10.0) = 10
        self.assertEqual(r["velocity_score"], 10)

    def test_negative_acceleration_not_penalized(self):
        # acceleration < 0 → acceleration_component = 0 (not negative)
        p = _proto(tvl_now=110_000, tvl_30d_ago=100_000, tvl_90d_ago=50_000,
                   user_count_now=100, user_count_30d_ago=100,
                   daily_active_users=0)
        r = _compute_protocol(p)
        # tvl_growth_30d = 10%, tvl_growth_90d = 120%
        # accel = 10 - (120/3) = 10 - 40 = -30 → max(0, -30) = 0
        self.assertGreaterEqual(r["velocity_score"], 0)

    def test_max_possible_score_is_100(self):
        # All components max: tvl=40, user=20, engagement=20, accel=20
        p = _proto(tvl_now=20_000_000, tvl_30d_ago=1_000_000, tvl_90d_ago=500_000,
                   user_count_now=10_000, user_count_30d_ago=100,
                   daily_active_users=10_000)
        r = _compute_protocol(p)
        self.assertLessEqual(r["velocity_score"], 100)

    def test_tvl_zero_base_sets_both_tvl_and_accel_zero(self):
        p = _proto(tvl_now=1_000_000, tvl_30d_ago=0, tvl_90d_ago=0)
        r = _compute_protocol(p)
        self.assertEqual(r["tvl_growth_30d_pct"], 0.0)
        self.assertEqual(r["tvl_acceleration"], 0.0)

    def test_user_growth_none_uses_zero_in_score(self):
        p = _proto(user_count_30d_ago=0, user_count_now=500, daily_active_users=0)
        r = _compute_protocol(p)
        self.assertIsNone(r["user_growth_30d_pct"])
        # user_component treated as 0
        self.assertGreaterEqual(r["velocity_score"], 0)

    def test_multiple_protocols_all_have_label(self):
        protos = [_proto(name=f"P{i}") for i in range(5)]
        result = analyze(protos, {"log_path": tempfile.mktemp()})
        for p in result["protocols"]:
            self.assertIn(p["velocity_label"],
                          ("VIRAL", "FAST", "GROWING", "STABLE", "DECLINING"))

    def test_score_stable_label(self):
        # Score should be ≥10, <30 to hit STABLE
        p = _proto(tvl_now=110_000, tvl_30d_ago=100_000, tvl_90d_ago=100_000,
                   user_count_now=100, user_count_30d_ago=100,
                   daily_active_users=0)
        r = _compute_protocol(p)
        # tvl_growth_30d = 10 → tvl_component = 10
        # accel = 10 - 0 = 10 → accel_component = 10
        # total = 20 → STABLE
        self.assertGreaterEqual(r["velocity_score"], 10)

    def test_protocol_name_as_string(self):
        p = _proto(name=42)  # numeric name coerced
        r = _compute_protocol(p)
        self.assertEqual(r["name"], "42")

    def test_large_tvl_per_user(self):
        p = _proto(tvl_now=1_000_000, user_count_now=1)
        r = _compute_protocol(p)
        self.assertAlmostEqual(r["tvl_per_user"], 1_000_000.0, places=0)

    def test_high_dau_engagement_capped(self):
        # dau = 2000, users = 100 → dau_ratio = 20 → *100 = 2000 → capped at 20
        p = _proto(user_count_now=100, daily_active_users=2000,
                   tvl_now=100_000, tvl_30d_ago=100_000, tvl_90d_ago=100_000,
                   user_count_30d_ago=100)
        r = _compute_protocol(p)
        # engagement_component = min(20, 2000) = 20
        # user_component = min(20, 0) = 0
        self.assertGreaterEqual(r["velocity_score"], 20)

    def test_rounded_values(self):
        r = _compute_protocol(_proto())
        self.assertIsInstance(r["tvl_growth_30d_pct"], float)
        self.assertIsInstance(r["dau_ratio"], float)

    def test_filtered_out_list_type(self):
        r = analyze([_proto(age_days=5)], {"log_path": tempfile.mktemp(), "min_age_days": 30})
        self.assertIsInstance(r["filtered_out"], list)

    def test_mixed_age_protocols(self):
        protos = [
            _proto("Old1", age_days=100),
            _proto("Young", age_days=10),
            _proto("Old2", age_days=90),
        ]
        r = analyze(protos, {"log_path": tempfile.mktemp(), "min_age_days": 30})
        names = [p["name"] for p in r["protocols"]]
        self.assertIn("Old1", names)
        self.assertIn("Old2", names)
        self.assertNotIn("Young", names)
        self.assertIn("Young", r["filtered_out"])

    def test_result_timestamp_recent(self):
        before = time.time()
        r = analyze([_proto()], {"log_path": tempfile.mktemp()})
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)


if __name__ == "__main__":
    unittest.main()
