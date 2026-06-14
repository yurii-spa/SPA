"""
Tests for MP-816 EmissionScheduleForecaster.
Run: python3 -m unittest spa_core.tests.test_emission_schedule_forecaster -v
"""

import json
import math
import os
import sys
import tempfile
import time
import unittest

# Ensure project root is importable
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.emission_schedule_forecaster import (
    forecast,
    forecast_and_log,
    log_result,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _p(emission=6.0, base=3.0, decay=0.10, periods=12, label="month"):
    return {
        "current_emission_apy": emission,
        "base_apy": base,
        "decay_rate_per_period": decay,
        "periods": periods,
        "period_label": label,
    }


# ---------------------------------------------------------------------------
# 1. Return-structure tests
# ---------------------------------------------------------------------------
class TestReturnStructure(unittest.TestCase):

    def setUp(self):
        self.result = forecast("TestProto", _p())

    def test_has_protocol(self):
        self.assertIn("protocol", self.result)

    def test_has_period_label(self):
        self.assertIn("period_label", self.result)

    def test_has_periods(self):
        self.assertIn("periods", self.result)

    def test_has_current_emission_apy(self):
        self.assertIn("current_emission_apy", self.result)

    def test_has_base_apy(self):
        self.assertIn("base_apy", self.result)

    def test_has_current_total_apy(self):
        self.assertIn("current_total_apy", self.result)

    def test_has_decay_rate_per_period(self):
        self.assertIn("decay_rate_per_period", self.result)

    def test_has_decay_rate_clamped(self):
        self.assertIn("decay_rate_clamped", self.result)

    def test_has_schedule(self):
        self.assertIn("schedule", self.result)

    def test_has_half_life_periods(self):
        self.assertIn("half_life_periods", self.result)

    def test_has_terminal_emission_apy(self):
        self.assertIn("terminal_emission_apy", self.result)

    def test_has_terminal_total_apy(self):
        self.assertIn("terminal_total_apy", self.result)

    def test_has_total_apy_decline_pct(self):
        self.assertIn("total_apy_decline_pct", self.result)

    def test_has_current_emission_share_pct(self):
        self.assertIn("current_emission_share_pct", self.result)

    def test_has_sustainability(self):
        self.assertIn("sustainability", self.result)

    def test_has_risk_flags(self):
        self.assertIn("risk_flags", self.result)

    def test_has_recommendation(self):
        self.assertIn("recommendation", self.result)

    def test_has_timestamp(self):
        self.assertIn("timestamp", self.result)

    def test_protocol_matches(self):
        self.assertEqual(self.result["protocol"], "TestProto")

    def test_schedule_is_list(self):
        self.assertIsInstance(self.result["schedule"], list)

    def test_risk_flags_is_list(self):
        self.assertIsInstance(self.result["risk_flags"], list)

    def test_recommendation_is_string(self):
        self.assertIsInstance(self.result["recommendation"], str)

    def test_periods_is_int(self):
        self.assertIsInstance(self.result["periods"], int)

    def test_schedule_entry_has_period(self):
        self.assertIn("period", self.result["schedule"][0])

    def test_schedule_entry_has_emission_apy(self):
        self.assertIn("emission_apy", self.result["schedule"][0])

    def test_schedule_entry_has_total_apy(self):
        self.assertIn("total_apy", self.result["schedule"][0])


# ---------------------------------------------------------------------------
# 2. Schedule / decay math tests
# ---------------------------------------------------------------------------
class TestScheduleMath(unittest.TestCase):

    def test_schedule_length_matches_periods(self):
        r = forecast("P", _p(periods=12))
        self.assertEqual(len(r["schedule"]), 12)

    def test_schedule_length_custom_periods(self):
        r = forecast("P", _p(periods=5))
        self.assertEqual(len(r["schedule"]), 5)

    def test_schedule_periods_start_at_one(self):
        r = forecast("P", _p(periods=4))
        self.assertEqual(r["schedule"][0]["period"], 1)

    def test_schedule_periods_sequential(self):
        r = forecast("P", _p(periods=4))
        periods = [e["period"] for e in r["schedule"]]
        self.assertEqual(periods, [1, 2, 3, 4])

    def test_first_period_emission_decayed_once(self):
        r = forecast("P", _p(emission=10.0, base=0.0, decay=0.10, periods=3))
        self.assertAlmostEqual(r["schedule"][0]["emission_apy"], 10.0 * 0.9)

    def test_second_period_emission_decayed_twice(self):
        r = forecast("P", _p(emission=10.0, base=0.0, decay=0.10, periods=3))
        self.assertAlmostEqual(r["schedule"][1]["emission_apy"], 10.0 * 0.9 * 0.9)

    def test_total_apy_is_base_plus_emission(self):
        r = forecast("P", _p(emission=10.0, base=2.0, decay=0.10, periods=3))
        e = r["schedule"][0]
        self.assertAlmostEqual(e["total_apy"], 2.0 + e["emission_apy"])

    def test_emission_monotonically_decreasing(self):
        r = forecast("P", _p(emission=10.0, base=1.0, decay=0.10, periods=8))
        ems = [e["emission_apy"] for e in r["schedule"]]
        for a, b in zip(ems, ems[1:]):
            self.assertGreater(a, b)

    def test_terminal_emission_matches_last_entry(self):
        r = forecast("P", _p(periods=6))
        self.assertAlmostEqual(r["terminal_emission_apy"], r["schedule"][-1]["emission_apy"])

    def test_terminal_total_matches_last_entry(self):
        r = forecast("P", _p(periods=6))
        self.assertAlmostEqual(r["terminal_total_apy"], r["schedule"][-1]["total_apy"])

    def test_current_total_apy_sum(self):
        r = forecast("P", _p(emission=6.0, base=3.0))
        self.assertAlmostEqual(r["current_total_apy"], 9.0)

    def test_emission_share_pct(self):
        r = forecast("P", _p(emission=6.0, base=3.0))
        self.assertAlmostEqual(r["current_emission_share_pct"], 66.66666666, places=4)

    def test_no_decay_emission_constant(self):
        r = forecast("P", _p(emission=5.0, base=2.0, decay=0.0, periods=4))
        for e in r["schedule"]:
            self.assertAlmostEqual(e["emission_apy"], 5.0)

    def test_no_decay_zero_decline(self):
        r = forecast("P", _p(emission=5.0, base=2.0, decay=0.0, periods=4))
        self.assertAlmostEqual(r["total_apy_decline_pct"], 0.0)

    def test_decline_pct_default_example(self):
        r = forecast("P", _p(emission=6.0, base=3.0, decay=0.10, periods=12))
        self.assertAlmostEqual(r["total_apy_decline_pct"], 47.838, places=2)

    def test_decline_pct_full_decay_no_base(self):
        # base=0, eventually emission->0 → decline approaches 100%
        r = forecast("P", _p(emission=10.0, base=0.0, decay=0.5, periods=20))
        self.assertGreater(r["total_apy_decline_pct"], 99.0)

    def test_zero_emission_zero_decline(self):
        r = forecast("P", _p(emission=0.0, base=5.0, decay=0.10, periods=6))
        self.assertAlmostEqual(r["total_apy_decline_pct"], 0.0)

    def test_raw_decay_rate_preserved(self):
        r = forecast("P", _p(decay=0.123))
        self.assertAlmostEqual(r["decay_rate_per_period"], 0.123)


# ---------------------------------------------------------------------------
# 3. Half-life tests
# ---------------------------------------------------------------------------
class TestHalfLife(unittest.TestCase):

    def test_half_life_for_10pct_decay(self):
        r = forecast("P", _p(decay=0.10))
        self.assertAlmostEqual(r["half_life_periods"], math.log(0.5) / math.log(0.9))

    def test_half_life_none_when_no_decay(self):
        r = forecast("P", _p(decay=0.0))
        self.assertIsNone(r["half_life_periods"])

    def test_half_life_none_when_decay_clamped_to_zero(self):
        r = forecast("P", _p(decay=-0.5))
        self.assertIsNone(r["half_life_periods"])

    def test_half_life_positive(self):
        r = forecast("P", _p(decay=0.20))
        self.assertGreater(r["half_life_periods"], 0.0)

    def test_half_life_smaller_for_faster_decay(self):
        slow = forecast("P", _p(decay=0.05))
        fast = forecast("P", _p(decay=0.30))
        self.assertLess(fast["half_life_periods"], slow["half_life_periods"])

    def test_half_life_50pct_decay_is_one(self):
        r = forecast("P", _p(decay=0.5))
        self.assertAlmostEqual(r["half_life_periods"], 1.0)


# ---------------------------------------------------------------------------
# 4. Decay-rate clamping tests
# ---------------------------------------------------------------------------
class TestDecayClamping(unittest.TestCase):

    def test_negative_decay_clamped_to_zero(self):
        r = forecast("P", _p(decay=-0.2))
        self.assertEqual(r["decay_rate_clamped"], 0.0)

    def test_decay_above_one_clamped(self):
        r = forecast("P", _p(decay=1.5))
        self.assertLess(r["decay_rate_clamped"], 1.0)

    def test_decay_exactly_one_clamped(self):
        r = forecast("P", _p(decay=1.0))
        self.assertLess(r["decay_rate_clamped"], 1.0)

    def test_decay_within_range_unchanged(self):
        r = forecast("P", _p(decay=0.25))
        self.assertAlmostEqual(r["decay_rate_clamped"], 0.25)

    def test_clamped_decay_keeps_emission_nonneg(self):
        r = forecast("P", _p(emission=10.0, base=1.0, decay=2.0, periods=5))
        for e in r["schedule"]:
            self.assertGreaterEqual(e["emission_apy"], 0.0)

    def test_negative_decay_constant_emission(self):
        r = forecast("P", _p(emission=8.0, base=1.0, decay=-0.5, periods=4))
        for e in r["schedule"]:
            self.assertAlmostEqual(e["emission_apy"], 8.0)


# ---------------------------------------------------------------------------
# 5. Sustainability classification tests
# ---------------------------------------------------------------------------
class TestSustainabilityClassification(unittest.TestCase):

    def test_stable_low_emission_share(self):
        # base=9, emission=1 → share 10% < 20% → STABLE
        r = forecast("P", _p(emission=1.0, base=9.0, decay=0.10, periods=12))
        self.assertEqual(r["sustainability"], "STABLE")

    def test_stable_zero_decay(self):
        # high share but no decay → STABLE
        r = forecast("P", _p(emission=8.0, base=2.0, decay=0.0, periods=12))
        self.assertEqual(r["sustainability"], "STABLE")

    def test_gradual_decay(self):
        # share 66%, decay 0.03 → decline ~20% < 30% → GRADUAL_DECAY
        r = forecast("P", _p(emission=6.0, base=3.0, decay=0.03, periods=12))
        self.assertEqual(r["sustainability"], "GRADUAL_DECAY")

    def test_fast_decay(self):
        # default example: decline ~47.8% → FAST_DECAY
        r = forecast("P", _p(emission=6.0, base=3.0, decay=0.10, periods=12))
        self.assertEqual(r["sustainability"], "FAST_DECAY")

    def test_cliff(self):
        # decay 0.3, base 1, emission 9 → decline ~88% → CLIFF
        r = forecast("P", _p(emission=9.0, base=1.0, decay=0.3, periods=12))
        self.assertEqual(r["sustainability"], "CLIFF")

    def test_stable_share_exactly_below_threshold(self):
        # share 19.9% < 20 → STABLE
        r = forecast("P", _p(emission=1.99, base=8.01, decay=0.5, periods=12))
        self.assertEqual(r["sustainability"], "STABLE")

    def test_negative_decay_is_stable(self):
        r = forecast("P", _p(emission=8.0, base=2.0, decay=-0.3, periods=12))
        self.assertEqual(r["sustainability"], "STABLE")

    def test_gradual_to_fast_boundary(self):
        # decay 0.04 → decline ~25.8% → GRADUAL (just under 30)
        r = forecast("P", _p(emission=6.0, base=3.0, decay=0.04, periods=12))
        self.assertEqual(r["sustainability"], "GRADUAL_DECAY")

    def test_fast_to_cliff_boundary(self):
        # decay 0.2 base3 emis6 → decline ~62% → CLIFF (>60)
        r = forecast("P", _p(emission=6.0, base=3.0, decay=0.2, periods=12))
        self.assertEqual(r["sustainability"], "CLIFF")

    def test_custom_stable_threshold(self):
        # share 30%, normally not STABLE; with threshold 40 → STABLE
        r = forecast("P", _p(emission=3.0, base=7.0, decay=0.5, periods=12),
                     config={"stable_emission_share": 40.0})
        self.assertEqual(r["sustainability"], "STABLE")


# ---------------------------------------------------------------------------
# 6. Risk flags tests
# ---------------------------------------------------------------------------
class TestRiskFlags(unittest.TestCase):

    def test_high_emission_dependency_flag(self):
        # share 80% > 70%
        r = forecast("P", _p(emission=8.0, base=2.0, decay=0.10, periods=12))
        self.assertIn("Yield highly emission-dependent", r["risk_flags"])

    def test_no_high_dependency_flag_when_below_70(self):
        # share 66% < 70%
        r = forecast("P", _p(emission=6.0, base=3.0, decay=0.10, periods=12))
        self.assertNotIn("Yield highly emission-dependent", r["risk_flags"])

    def test_rapid_decay_flag(self):
        r = forecast("P", _p(emission=5.0, base=5.0, decay=0.40, periods=12))
        self.assertIn("Rapid emission decay expected", r["risk_flags"])

    def test_no_rapid_decay_flag_at_low_rate(self):
        r = forecast("P", _p(emission=5.0, base=5.0, decay=0.10, periods=12))
        self.assertNotIn("Rapid emission decay expected", r["risk_flags"])

    def test_no_real_yield_floor_flag(self):
        r = forecast("P", _p(emission=6.0, base=0.0, decay=0.10, periods=12))
        self.assertIn("No real yield floor", r["risk_flags"])

    def test_no_floor_flag_negative_base(self):
        r = forecast("P", _p(emission=6.0, base=-1.0, decay=0.10, periods=12))
        self.assertIn("No real yield floor", r["risk_flags"])

    def test_no_floor_flag_absent_when_base_positive(self):
        r = forecast("P", _p(emission=6.0, base=3.0, decay=0.10, periods=12))
        self.assertNotIn("No real yield floor", r["risk_flags"])

    def test_no_flags_for_clean_forecast(self):
        # share low, slow decay, positive base
        r = forecast("P", _p(emission=2.0, base=8.0, decay=0.05, periods=12))
        self.assertEqual(r["risk_flags"], [])

    def test_multiple_flags_coexist(self):
        # high share + rapid decay + no base
        r = forecast("P", _p(emission=10.0, base=0.0, decay=0.5, periods=12))
        self.assertGreaterEqual(len(r["risk_flags"]), 3)

    def test_risk_flags_strings(self):
        r = forecast("P", _p(emission=8.0, base=2.0, decay=0.4, periods=12))
        for f in r["risk_flags"]:
            self.assertIsInstance(f, str)


# ---------------------------------------------------------------------------
# 7. Recommendation tests
# ---------------------------------------------------------------------------
class TestRecommendation(unittest.TestCase):

    def test_recommendation_stable(self):
        r = forecast("P", _p(emission=1.0, base=9.0, decay=0.10, periods=12))
        self.assertIn("durable", r["recommendation"].lower())

    def test_recommendation_gradual(self):
        r = forecast("P", _p(emission=6.0, base=3.0, decay=0.03, periods=12))
        self.assertIn("monitor", r["recommendation"].lower())

    def test_recommendation_fast(self):
        r = forecast("P", _p(emission=6.0, base=3.0, decay=0.10, periods=12))
        self.assertIn("rotation", r["recommendation"].lower())

    def test_recommendation_cliff(self):
        r = forecast("P", _p(emission=9.0, base=1.0, decay=0.3, periods=12))
        self.assertIn("avoid", r["recommendation"].lower())

    def test_recommendation_nonempty(self):
        r = forecast("P", _p())
        self.assertGreater(len(r["recommendation"]), 0)

    def test_recommendation_is_string(self):
        r = forecast("P", _p())
        self.assertIsInstance(r["recommendation"], str)


# ---------------------------------------------------------------------------
# 8. Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases(unittest.TestCase):

    def test_zero_total_apy(self):
        r = forecast("P", _p(emission=0.0, base=0.0, decay=0.10, periods=6))
        self.assertEqual(r["current_emission_share_pct"], 0.0)
        self.assertEqual(r["total_apy_decline_pct"], 0.0)

    def test_zero_periods_empty_schedule(self):
        r = forecast("P", _p(periods=0))
        self.assertEqual(r["schedule"], [])

    def test_zero_periods_terminal_equals_current(self):
        r = forecast("P", _p(emission=6.0, base=3.0, periods=0))
        self.assertAlmostEqual(r["terminal_total_apy"], 9.0)

    def test_negative_periods_clamped_to_zero(self):
        r = forecast("P", _p(periods=-5))
        self.assertEqual(r["periods"], 0)
        self.assertEqual(r["schedule"], [])

    def test_missing_periods_uses_default(self):
        r = forecast("P", {"current_emission_apy": 6.0, "base_apy": 3.0,
                            "decay_rate_per_period": 0.1})
        self.assertEqual(r["periods"], 12)

    def test_missing_period_label_default(self):
        r = forecast("P", {"current_emission_apy": 6.0, "base_apy": 3.0,
                            "decay_rate_per_period": 0.1, "periods": 4})
        self.assertEqual(r["period_label"], "period")

    def test_period_label_preserved(self):
        r = forecast("P", _p(label="epoch"))
        self.assertEqual(r["period_label"], "epoch")

    def test_empty_params_defaults(self):
        r = forecast("P", {})
        self.assertEqual(r["current_emission_apy"], 0.0)
        self.assertEqual(r["base_apy"], 0.0)

    def test_large_values(self):
        r = forecast("P", _p(emission=1e6, base=5e5, decay=0.10, periods=12))
        self.assertGreater(r["current_total_apy"], 0)

    def test_small_values(self):
        r = forecast("P", _p(emission=0.001, base=0.002, decay=0.10, periods=6))
        self.assertEqual(len(r["schedule"]), 6)

    def test_config_none_uses_defaults(self):
        r1 = forecast("P", _p(), config=None)
        r2 = forecast("P", _p(), config={})
        self.assertEqual(r1["sustainability"], r2["sustainability"])

    def test_extra_config_keys_ignored(self):
        r = forecast("P", _p(), config={"unknown_key": 999})
        self.assertIn("sustainability", r)

    def test_timestamp_is_recent(self):
        before = time.time()
        r = forecast("P", _p())
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_protocol_name_preserved(self):
        r = forecast("Radiant V2", _p())
        self.assertEqual(r["protocol"], "Radiant V2")

    def test_single_period(self):
        r = forecast("P", _p(emission=10.0, base=0.0, decay=0.1, periods=1))
        self.assertEqual(len(r["schedule"]), 1)
        self.assertAlmostEqual(r["schedule"][0]["emission_apy"], 9.0)

    def test_negative_emission_input(self):
        r = forecast("P", _p(emission=-5.0, base=10.0, decay=0.1, periods=4))
        self.assertIn("sustainability", r)

    def test_decline_pct_never_nan(self):
        r = forecast("P", _p(emission=0.0, base=0.0, decay=0.1, periods=4))
        self.assertFalse(math.isnan(r["total_apy_decline_pct"]))


# ---------------------------------------------------------------------------
# 9. Config override tests
# ---------------------------------------------------------------------------
class TestConfigOverrides(unittest.TestCase):

    def test_custom_default_periods(self):
        r = forecast("P", {"current_emission_apy": 6.0, "base_apy": 3.0,
                           "decay_rate_per_period": 0.1},
                     config={"default_periods": 6})
        self.assertEqual(r["periods"], 6)

    def test_custom_gradual_decline_max(self):
        # default example decline 47.8%; with gradual_max=60 → GRADUAL
        r = forecast("P", _p(emission=6.0, base=3.0, decay=0.10, periods=12),
                     config={"gradual_decline_max": 60.0, "fast_decline_max": 90.0})
        self.assertEqual(r["sustainability"], "GRADUAL_DECAY")

    def test_custom_fast_decline_max(self):
        # decline 47.8%; with fast_max=40 → CLIFF
        r = forecast("P", _p(emission=6.0, base=3.0, decay=0.10, periods=12),
                     config={"fast_decline_max": 40.0})
        self.assertEqual(r["sustainability"], "CLIFF")

    def test_config_float_types(self):
        r = forecast("P", _p(), config={"stable_emission_share": 20, "gradual_decline_max": 30})
        self.assertIn("sustainability", r)


# ---------------------------------------------------------------------------
# 10. Log / IO tests
# ---------------------------------------------------------------------------
class TestLogging(unittest.TestCase):

    def test_log_result_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_log.json")
            r = forecast("P", _p())
            log_result(r, log_path=path)
            self.assertTrue(os.path.exists(path))

    def test_log_result_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_log.json")
            r = forecast("P", _p())
            log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_log_result_appends(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_log.json")
            for i in range(3):
                r = forecast(f"P{i}", _p())
                log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)

    def test_log_ring_buffer_capped_at_100(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_log.json")
            for i in range(120):
                r = forecast(f"P{i}", _p())
                log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 100)

    def test_log_keeps_most_recent_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_log.json")
            for i in range(110):
                r = forecast(f"PROTO_{i}", _p())
                log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data[-1]["protocol"], "PROTO_109")
            self.assertEqual(data[0]["protocol"], "PROTO_10")

    def test_forecast_and_log_returns_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "log.json")
            r = forecast_and_log("P", _p(), log_path=path)
            self.assertIn("protocol", r)

    def test_forecast_and_log_writes_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "log.json")
            forecast_and_log("P", _p(), log_path=path)
            self.assertTrue(os.path.exists(path))

    def test_log_handles_corrupt_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "log.json")
            with open(path, "w") as f:
                f.write("not valid json {{{")
            r = forecast("P", _p())
            log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)

    def test_log_creates_missing_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "nested", "deep", "log.json")
            r = forecast("P", _p())
            log_result(r, log_path=path)
            self.assertTrue(os.path.exists(path))

    def test_log_no_stray_tmp_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "log.json")
            r = forecast("P", _p())
            log_result(r, log_path=path)
            tmps = [f for f in os.listdir(tmpdir) if f.endswith(".tmp")]
            self.assertEqual(tmps, [])

    def test_log_roundtrip_preserves_schedule(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "log.json")
            r = forecast("P", _p(periods=5))
            log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data[0]["schedule"]), 5)


if __name__ == "__main__":
    unittest.main()
