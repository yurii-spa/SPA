"""
Tests for MP-916: DeFiProtocolAdoptionTracker
≥80 unittest tests covering all metrics, labels, flags, aggregates, ring-buffer.
"""

import json
import math
import os
import tempfile
import unittest

# Make sure imports work regardless of working directory
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_adoption_tracker import (
    DeFiProtocolAdoptionTracker,
    _safe_div,
    _growth_rate_pct,
    _adoption_velocity_score,
    _stickiness_score,
    _network_effect_score,
    _adoption_label,
    _compute_flags,
    _analyse_protocol,
    _build_aggregates,
    _atomic_log_append,
    LABEL_HYPERGROWTH,
    LABEL_GROWING,
    LABEL_STABLE,
    LABEL_DECLINING,
    LABEL_DYING,
    FLAG_USER_EXODUS,
    FLAG_TVL_SURGE,
    FLAG_LOW_RETENTION,
    FLAG_VIRAL_GROWTH,
    FLAG_MULTI_CHAIN_EXPANSION,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _proto(**kwargs):
    """Build a minimal valid protocol dict."""
    base = {
        "name": "TestProtocol",
        "unique_users_30d": 10_000,
        "unique_users_90d": 27_000,      # implies ~10k/mo
        "unique_users_all_time": 50_000,
        "transactions_30d": 100_000,
        "tvl_usd": 100_000_000,
        "tvl_30d_ago_usd": 90_000_000,
        "retention_rate_pct": 50.0,
        "new_users_30d": 3_000,
        "chain_count": 2,
        "integrations_count": 5,
    }
    base.update(kwargs)
    return base


# --------------------------------------------------------------------------- #
# Unit: _safe_div
# --------------------------------------------------------------------------- #

class TestSafeDiv(unittest.TestCase):
    def test_normal_division(self):
        self.assertAlmostEqual(_safe_div(10, 2), 5.0)

    def test_zero_denominator_default(self):
        self.assertEqual(_safe_div(5, 0), 0.0)

    def test_zero_denominator_custom_default(self):
        self.assertEqual(_safe_div(5, 0, -1.0), -1.0)

    def test_zero_numerator(self):
        self.assertEqual(_safe_div(0, 5), 0.0)

    def test_both_zero(self):
        self.assertEqual(_safe_div(0, 0), 0.0)

    def test_negative_numerator(self):
        self.assertAlmostEqual(_safe_div(-10, 2), -5.0)

    def test_fractional_result(self):
        self.assertAlmostEqual(_safe_div(1, 3), 1 / 3)


# --------------------------------------------------------------------------- #
# Unit: _growth_rate_pct
# --------------------------------------------------------------------------- #

class TestGrowthRatePct(unittest.TestCase):
    def test_positive_growth(self):
        result = _growth_rate_pct(110, 100)
        self.assertAlmostEqual(result, 10.0)

    def test_negative_growth(self):
        result = _growth_rate_pct(80, 100)
        self.assertAlmostEqual(result, -20.0)

    def test_zero_previous_positive_current(self):
        self.assertEqual(_growth_rate_pct(100, 0), 100.0)

    def test_zero_previous_zero_current(self):
        self.assertEqual(_growth_rate_pct(0, 0), 0.0)

    def test_doubled(self):
        self.assertAlmostEqual(_growth_rate_pct(200, 100), 100.0)

    def test_tripled(self):
        self.assertAlmostEqual(_growth_rate_pct(300, 100), 200.0)

    def test_decline_to_zero(self):
        self.assertAlmostEqual(_growth_rate_pct(0, 100), -100.0)

    def test_negative_previous(self):
        # Should use abs(previous)
        result = _growth_rate_pct(-80, -100)
        self.assertAlmostEqual(result, 20.0)


# --------------------------------------------------------------------------- #
# Unit: _adoption_velocity_score
# --------------------------------------------------------------------------- #

class TestAdoptionVelocityScore(unittest.TestCase):
    def test_all_max_inputs(self):
        score = _adoption_velocity_score(100.0, 100.0, 1.0)
        self.assertGreaterEqual(score, 90.0)
        self.assertLessEqual(score, 100.0)

    def test_all_zero(self):
        # user_growth=0 → ug=50, tvl=0 → tg=50, new_ratio=0 → nu=0
        score = _adoption_velocity_score(0.0, 0.0, 0.0)
        expected = 0.5 * 50 + 0.3 * 50 + 0.2 * 0
        self.assertAlmostEqual(score, expected, places=1)

    def test_result_in_range(self):
        for ug, tg, nu in [(-100, -100, 0), (200, 200, 2), (50, 30, 0.5)]:
            score = _adoption_velocity_score(ug, tg, nu)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_high_user_growth_dominates(self):
        score_high = _adoption_velocity_score(200.0, 0.0, 0.0)
        score_low = _adoption_velocity_score(-100.0, 0.0, 0.0)
        self.assertGreater(score_high, score_low)

    def test_returns_float(self):
        self.assertIsInstance(_adoption_velocity_score(10, 10, 0.5), float)


# --------------------------------------------------------------------------- #
# Unit: _stickiness_score
# --------------------------------------------------------------------------- #

class TestStickinessScore(unittest.TestCase):
    def test_fifty_pct(self):
        self.assertAlmostEqual(_stickiness_score(50.0), 50.0)

    def test_clamp_above_100(self):
        self.assertAlmostEqual(_stickiness_score(150.0), 100.0)

    def test_clamp_below_zero(self):
        self.assertAlmostEqual(_stickiness_score(-10.0), 0.0)

    def test_zero(self):
        self.assertAlmostEqual(_stickiness_score(0.0), 0.0)

    def test_hundred(self):
        self.assertAlmostEqual(_stickiness_score(100.0), 100.0)


# --------------------------------------------------------------------------- #
# Unit: _network_effect_score
# --------------------------------------------------------------------------- #

class TestNetworkEffectScore(unittest.TestCase):
    def test_zero_users(self):
        self.assertEqual(_network_effect_score(0, 5, 3), 0.0)

    def test_positive_score(self):
        score = _network_effect_score(1_000_000, 5, 5)
        self.assertGreater(score, 0.0)

    def test_clamp_max(self):
        score = _network_effect_score(1e15, 100, 100)
        self.assertLessEqual(score, 100.0)

    def test_clamp_min(self):
        score = _network_effect_score(1, 1, 1)
        self.assertGreaterEqual(score, 0.0)

    def test_more_integrations_higher_score(self):
        low = _network_effect_score(100_000, 1, 1)
        high = _network_effect_score(100_000, 10, 5)
        self.assertGreater(high, low)

    def test_returns_float(self):
        self.assertIsInstance(_network_effect_score(10_000, 3, 2), float)


# --------------------------------------------------------------------------- #
# Unit: _adoption_label
# --------------------------------------------------------------------------- #

class TestAdoptionLabel(unittest.TestCase):
    def test_hypergrowth(self):
        self.assertEqual(_adoption_label(150.0), LABEL_HYPERGROWTH)

    def test_exactly_100(self):
        # >100 is HYPERGROWTH; ==100 is not
        self.assertNotEqual(_adoption_label(100.0), LABEL_HYPERGROWTH)

    def test_growing(self):
        self.assertEqual(_adoption_label(50.0), LABEL_GROWING)

    def test_growing_lower_bound(self):
        self.assertEqual(_adoption_label(11.0), LABEL_GROWING)

    def test_stable_at_zero(self):
        self.assertEqual(_adoption_label(0.0), LABEL_STABLE)

    def test_stable_slightly_negative(self):
        self.assertEqual(_adoption_label(-4.0), LABEL_STABLE)

    def test_stable_boundary_negative5(self):
        self.assertEqual(_adoption_label(-5.0), LABEL_STABLE)

    def test_declining(self):
        self.assertEqual(_adoption_label(-15.0), LABEL_DECLINING)

    def test_declining_boundary(self):
        self.assertEqual(_adoption_label(-30.0), LABEL_DECLINING)

    def test_dying(self):
        self.assertEqual(_adoption_label(-50.0), LABEL_DYING)

    def test_dying_extreme(self):
        self.assertEqual(_adoption_label(-200.0), LABEL_DYING)


# --------------------------------------------------------------------------- #
# Unit: _compute_flags
# --------------------------------------------------------------------------- #

class TestComputeFlags(unittest.TestCase):
    def _flags(self, **kwargs):
        defaults = dict(
            user_growth_pct=0.0,
            tvl_growth_pct=0.0,
            retention_rate_pct=50.0,
            new_user_ratio=0.3,
            chain_count=1,
        )
        defaults.update(kwargs)
        return _compute_flags(**defaults)

    def test_no_flags_normal(self):
        flags = self._flags()
        self.assertEqual(flags, [])

    def test_user_exodus(self):
        flags = self._flags(user_growth_pct=-25.0)
        self.assertIn(FLAG_USER_EXODUS, flags)

    def test_no_user_exodus_boundary(self):
        flags = self._flags(user_growth_pct=-19.9)
        self.assertNotIn(FLAG_USER_EXODUS, flags)

    def test_tvl_surge(self):
        flags = self._flags(tvl_growth_pct=60.0)
        self.assertIn(FLAG_TVL_SURGE, flags)

    def test_no_tvl_surge(self):
        flags = self._flags(tvl_growth_pct=49.9)
        self.assertNotIn(FLAG_TVL_SURGE, flags)

    def test_low_retention(self):
        flags = self._flags(retention_rate_pct=10.0)
        self.assertIn(FLAG_LOW_RETENTION, flags)

    def test_no_low_retention(self):
        flags = self._flags(retention_rate_pct=20.0)
        self.assertNotIn(FLAG_LOW_RETENTION, flags)

    def test_viral_growth(self):
        flags = self._flags(new_user_ratio=0.85)
        self.assertIn(FLAG_VIRAL_GROWTH, flags)

    def test_no_viral_growth(self):
        flags = self._flags(new_user_ratio=0.79)
        self.assertNotIn(FLAG_VIRAL_GROWTH, flags)

    def test_multi_chain_expansion(self):
        flags = self._flags(chain_count=4)
        self.assertIn(FLAG_MULTI_CHAIN_EXPANSION, flags)

    def test_no_multi_chain_expansion(self):
        flags = self._flags(chain_count=3)
        self.assertNotIn(FLAG_MULTI_CHAIN_EXPANSION, flags)

    def test_multiple_flags_simultaneously(self):
        flags = self._flags(
            user_growth_pct=-25.0,
            tvl_growth_pct=60.0,
            retention_rate_pct=5.0,
            new_user_ratio=0.9,
            chain_count=5,
        )
        self.assertEqual(len(flags), 5)

    def test_flags_are_list(self):
        self.assertIsInstance(self._flags(), list)


# --------------------------------------------------------------------------- #
# Unit: _analyse_protocol
# --------------------------------------------------------------------------- #

class TestAnalyseProtocol(unittest.TestCase):
    def _result(self, **kwargs):
        return _analyse_protocol(_proto(**kwargs))

    def test_returns_dict(self):
        self.assertIsInstance(self._result(), dict)

    def test_has_required_keys(self):
        r = self._result()
        for key in ["name", "user_growth_rate_pct", "tvl_growth_rate_pct",
                    "adoption_velocity_score", "stickiness_score",
                    "network_effect_score", "adoption_label", "flags"]:
            self.assertIn(key, r)

    def test_name_preserved(self):
        r = _analyse_protocol(_proto(name="Aave"))
        self.assertEqual(r["name"], "Aave")

    def test_tvl_growth_positive(self):
        r = _analyse_protocol(_proto(tvl_usd=110, tvl_30d_ago_usd=100))
        self.assertAlmostEqual(r["tvl_growth_rate_pct"], 10.0)

    def test_tvl_growth_negative(self):
        r = _analyse_protocol(_proto(tvl_usd=80, tvl_30d_ago_usd=100))
        self.assertAlmostEqual(r["tvl_growth_rate_pct"], -20.0)

    def test_stickiness_passthrough(self):
        r = _analyse_protocol(_proto(retention_rate_pct=75.0))
        self.assertAlmostEqual(r["stickiness_score"], 75.0)

    def test_scores_in_range(self):
        r = self._result()
        self.assertGreaterEqual(r["adoption_velocity_score"], 0.0)
        self.assertLessEqual(r["adoption_velocity_score"], 100.0)
        self.assertGreaterEqual(r["stickiness_score"], 0.0)
        self.assertLessEqual(r["stickiness_score"], 100.0)
        self.assertGreaterEqual(r["network_effect_score"], 0.0)
        self.assertLessEqual(r["network_effect_score"], 100.0)

    def test_hypergrowth_label(self):
        # 30d users 3x the monthly average of 90d → very high growth
        r = _analyse_protocol(_proto(unique_users_30d=30_000, unique_users_90d=9_000))
        self.assertEqual(r["adoption_label"], LABEL_HYPERGROWTH)

    def test_dying_label(self):
        r = _analyse_protocol(_proto(unique_users_30d=1_000, unique_users_90d=90_000))
        self.assertEqual(r["adoption_label"], LABEL_DYING)

    def test_missing_optional_fields_defaults(self):
        # Minimal protocol dict
        r = _analyse_protocol({"name": "minimal"})
        self.assertEqual(r["name"], "minimal")
        self.assertIsInstance(r["flags"], list)

    def test_flags_list_type(self):
        r = self._result()
        self.assertIsInstance(r["flags"], list)

    def test_new_user_ratio_computed(self):
        r = _analyse_protocol(_proto(unique_users_30d=10_000, new_users_30d=5_000))
        self.assertAlmostEqual(r["new_user_ratio"], 0.5, places=2)

    def test_zero_tvl_ago_handled(self):
        r = _analyse_protocol(_proto(tvl_30d_ago_usd=0, tvl_usd=1_000_000))
        # Growth from 0 → should return 100.0
        self.assertAlmostEqual(r["tvl_growth_rate_pct"], 100.0)


# --------------------------------------------------------------------------- #
# Unit: _build_aggregates
# --------------------------------------------------------------------------- #

class TestBuildAggregates(unittest.TestCase):
    def _make_results(self, growths_and_retentions):
        results = []
        for i, (growth, retention) in enumerate(growths_and_retentions):
            r = _analyse_protocol(_proto(
                name=f"P{i}",
                unique_users_30d=max(1, int(10000 * (1 + growth / 100))),
                unique_users_90d=10000 * 3,
                retention_rate_pct=retention,
            ))
            results.append(r)
        return results

    def test_empty_returns_defaults(self):
        agg = _build_aggregates([])
        self.assertIsNone(agg["fastest_growing"])
        self.assertIsNone(agg["most_declining"])
        self.assertEqual(agg["total_ecosystem_users"], 0)

    def test_single_protocol(self):
        results = [_analyse_protocol(_proto(name="Solo"))]
        agg = _build_aggregates(results)
        self.assertEqual(agg["fastest_growing"], "Solo")
        self.assertEqual(agg["most_declining"], "Solo")

    def test_fastest_growing_identified(self):
        r1 = _analyse_protocol(_proto(name="Fast", unique_users_30d=100_000, unique_users_90d=9_000))
        r2 = _analyse_protocol(_proto(name="Slow", unique_users_30d=10_000, unique_users_90d=90_000))
        agg = _build_aggregates([r1, r2])
        self.assertEqual(agg["fastest_growing"], "Fast")

    def test_most_declining_identified(self):
        r1 = _analyse_protocol(_proto(name="Fast", unique_users_30d=100_000, unique_users_90d=9_000))
        r2 = _analyse_protocol(_proto(name="Slow", unique_users_30d=1_000, unique_users_90d=90_000))
        agg = _build_aggregates([r1, r2])
        self.assertEqual(agg["most_declining"], "Slow")

    def test_total_ecosystem_users(self):
        r1 = _analyse_protocol(_proto(name="A", unique_users_all_time=50_000))
        r2 = _analyse_protocol(_proto(name="B", unique_users_all_time=30_000))
        agg = _build_aggregates([r1, r2])
        self.assertEqual(agg["total_ecosystem_users"], 80_000)

    def test_average_retention(self):
        r1 = _analyse_protocol(_proto(retention_rate_pct=60.0))
        r2 = _analyse_protocol(_proto(retention_rate_pct=40.0))
        agg = _build_aggregates([r1, r2])
        self.assertAlmostEqual(agg["average_retention"], 50.0)

    def test_hypergrowth_count(self):
        r1 = _analyse_protocol(_proto(name="HG", unique_users_30d=100_000, unique_users_90d=1_000))
        r2 = _analyse_protocol(_proto(name="Normal", unique_users_30d=10_000, unique_users_90d=30_000))
        agg = _build_aggregates([r1, r2])
        self.assertEqual(agg["hypergrowth_count"], 1)

    def test_hypergrowth_count_zero(self):
        r1 = _analyse_protocol(_proto(unique_users_30d=10_000, unique_users_90d=30_000))
        agg = _build_aggregates([r1])
        self.assertEqual(agg["hypergrowth_count"], 0)


# --------------------------------------------------------------------------- #
# Unit: _atomic_log_append (ring-buffer)
# --------------------------------------------------------------------------- #

class TestAtomicLogAppend(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_log.json")

    def test_creates_file(self):
        _atomic_log_append({"x": 1}, self.log_path, cap=10)
        self.assertTrue(os.path.exists(self.log_path))

    def test_single_entry(self):
        _atomic_log_append({"x": 1}, self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["x"], 1)

    def test_multiple_entries(self):
        for i in range(5):
            _atomic_log_append({"i": i}, self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        for i in range(15):
            _atomic_log_append({"i": i}, self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 10)
        # Oldest entries should be dropped; last entry should be i=14
        self.assertEqual(data[-1]["i"], 14)

    def test_ring_buffer_keeps_newest(self):
        for i in range(12):
            _atomic_log_append({"i": i}, self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        # First entry should be i=2 (entries 0 and 1 were evicted)
        self.assertEqual(data[0]["i"], 2)

    def test_corrupted_file_resets(self):
        with open(self.log_path, "w") as f:
            f.write("NOT JSON")
        _atomic_log_append({"x": 99}, self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_no_tmp_file_left_behind(self):
        _atomic_log_append({"x": 1}, self.log_path, cap=10)
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))


# --------------------------------------------------------------------------- #
# Integration: DeFiProtocolAdoptionTracker.track()
# --------------------------------------------------------------------------- #

class TestDeFiProtocolAdoptionTrackerTrack(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "adoption_log.json")
        self.tracker = DeFiProtocolAdoptionTracker(log_path=self.log_path)

    def _make_protocols(self, n=3):
        return [_proto(name=f"Proto{i}") for i in range(n)]

    def test_returns_dict(self):
        result = self.tracker.track(self._make_protocols())
        self.assertIsInstance(result, dict)

    def test_has_protocols_key(self):
        result = self.tracker.track(self._make_protocols())
        self.assertIn("protocols", result)

    def test_has_aggregates_key(self):
        result = self.tracker.track(self._make_protocols())
        self.assertIn("aggregates", result)

    def test_has_timestamp_key(self):
        result = self.tracker.track(self._make_protocols())
        self.assertIn("timestamp", result)

    def test_protocols_count_matches_input(self):
        result = self.tracker.track(self._make_protocols(5))
        self.assertEqual(len(result["protocols"]), 5)

    def test_empty_protocols(self):
        result = self.tracker.track([])
        self.assertEqual(result["protocols"], [])
        self.assertIsNone(result["aggregates"]["fastest_growing"])

    def test_log_created_after_track(self):
        self.tracker.track(self._make_protocols())
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_entry_count(self):
        self.tracker.track(self._make_protocols())
        self.tracker.track(self._make_protocols())
        with open(self.log_path) as f:
            entries = json.load(f)
        self.assertEqual(len(entries), 2)

    def test_ring_buffer_cap_respected(self):
        for _ in range(105):
            self.tracker.track(self._make_protocols(1))
        with open(self.log_path) as f:
            entries = json.load(f)
        self.assertEqual(len(entries), 100)

    def test_config_none_allowed(self):
        result = self.tracker.track(self._make_protocols(), config=None)
        self.assertIn("protocols", result)

    def test_config_dict_allowed(self):
        result = self.tracker.track(self._make_protocols(), config={"foo": "bar"})
        self.assertIn("protocols", result)

    def test_timestamp_format(self):
        result = self.tracker.track(self._make_protocols())
        ts = result["timestamp"]
        self.assertTrue(ts.endswith("Z"))
        self.assertIn("T", ts)

    def test_per_protocol_label_present(self):
        result = self.tracker.track(self._make_protocols(1))
        self.assertIn("adoption_label", result["protocols"][0])

    def test_per_protocol_flags_list(self):
        result = self.tracker.track(self._make_protocols(1))
        self.assertIsInstance(result["protocols"][0]["flags"], list)

    def test_aggregates_fastest_growing(self):
        protos = [
            _proto(name="Rocket", unique_users_30d=500_000, unique_users_90d=10_000),
            _proto(name="Turtle", unique_users_30d=10_000, unique_users_90d=300_000),
        ]
        result = self.tracker.track(protos)
        self.assertEqual(result["aggregates"]["fastest_growing"], "Rocket")

    def test_aggregates_most_declining(self):
        protos = [
            _proto(name="Rocket", unique_users_30d=500_000, unique_users_90d=10_000),
            _proto(name="Turtle", unique_users_30d=1_000, unique_users_90d=300_000),
        ]
        result = self.tracker.track(protos)
        self.assertEqual(result["aggregates"]["most_declining"], "Turtle")

    def test_aggregates_total_ecosystem_users(self):
        protos = [
            _proto(name="A", unique_users_all_time=100_000),
            _proto(name="B", unique_users_all_time=200_000),
        ]
        result = self.tracker.track(protos)
        self.assertEqual(result["aggregates"]["total_ecosystem_users"], 300_000)

    def test_hypergrowth_protocol_detected(self):
        protos = [
            _proto(name="HG", unique_users_30d=200_000, unique_users_90d=10_000),
        ]
        result = self.tracker.track(protos)
        self.assertEqual(result["aggregates"]["hypergrowth_count"], 1)

    def test_user_exodus_flag_in_result(self):
        protos = [_proto(unique_users_30d=1_000, unique_users_90d=100_000)]
        result = self.tracker.track(protos)
        flags = result["protocols"][0]["flags"]
        self.assertIn(FLAG_USER_EXODUS, flags)

    def test_tvl_surge_flag(self):
        protos = [_proto(tvl_usd=200_000_000, tvl_30d_ago_usd=100_000_000)]
        result = self.tracker.track(protos)
        flags = result["protocols"][0]["flags"]
        self.assertIn(FLAG_TVL_SURGE, flags)

    def test_low_retention_flag(self):
        protos = [_proto(retention_rate_pct=10.0)]
        result = self.tracker.track(protos)
        flags = result["protocols"][0]["flags"]
        self.assertIn(FLAG_LOW_RETENTION, flags)

    def test_viral_growth_flag(self):
        protos = [_proto(new_users_30d=9_000, unique_users_30d=10_000)]
        result = self.tracker.track(protos)
        flags = result["protocols"][0]["flags"]
        self.assertIn(FLAG_VIRAL_GROWTH, flags)

    def test_multi_chain_flag(self):
        protos = [_proto(chain_count=5)]
        result = self.tracker.track(protos)
        flags = result["protocols"][0]["flags"]
        self.assertIn(FLAG_MULTI_CHAIN_EXPANSION, flags)

    def test_no_flags_normal_protocol(self):
        protos = [_proto(
            unique_users_30d=10_000,
            unique_users_90d=27_000,
            tvl_usd=100_000_000,
            tvl_30d_ago_usd=95_000_000,
            retention_rate_pct=50.0,
            new_users_30d=2_000,
            chain_count=2,
        )]
        result = self.tracker.track(protos)
        flags = result["protocols"][0]["flags"]
        self.assertEqual(flags, [])

    def test_large_protocol_set(self):
        protos = [_proto(name=f"P{i}") for i in range(50)]
        result = self.tracker.track(protos)
        self.assertEqual(len(result["protocols"]), 50)

    def test_protocol_with_zero_tvl_ago(self):
        protos = [_proto(tvl_30d_ago_usd=0, tvl_usd=1_000_000)]
        result = self.tracker.track(protos)
        self.assertAlmostEqual(result["protocols"][0]["tvl_growth_rate_pct"], 100.0)

    def test_velocity_score_range(self):
        for _ in range(10):
            protos = self._make_protocols(5)
            result = self.tracker.track(protos)
            for p in result["protocols"]:
                self.assertGreaterEqual(p["adoption_velocity_score"], 0.0)
                self.assertLessEqual(p["adoption_velocity_score"], 100.0)


if __name__ == "__main__":
    unittest.main()
