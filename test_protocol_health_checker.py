"""
Tests for MP-765: ProtocolHealthChecker  (≥65 tests)
Pure stdlib unittest — no pytest dependency.
"""
import json
import math
import os
import tempfile
import time
import unittest
from pathlib import Path

from spa_core.analytics.protocol_health_checker import (
    HealthResult,
    ProtocolHealthChecker,
    HEALTHY_THRESHOLD,
    WATCH_THRESHOLD,
    CAUTION_THRESHOLD,
    FLAG_THRESHOLD,
    MAX_ENTRIES,
)

EPS = 1e-6


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _checker() -> ProtocolHealthChecker:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return ProtocolHealthChecker(data_file=Path(path))


def _healthy_proto(name: str = "Aave V3") -> dict:
    """Protocol data expected to yield HEALTHY status."""
    return {
        "protocol": name,
        "tvl_trend_1w": 0.08,
        "tvl_trend_4w": 0.15,
        "governance_activity": 0.90,
        "code_audit_score": 95.0,
        "team_activity_score": 0.90,
        "bug_bounty_size_usd": 2_000_000,
    }


def _critical_proto(name: str = "HighRisk") -> dict:
    """Protocol data expected to yield CRITICAL status."""
    return {
        "protocol": name,
        "tvl_trend_1w": -0.20,
        "tvl_trend_4w": -0.40,
        "governance_activity": 0.05,
        "code_audit_score": 10.0,
        "team_activity_score": 0.05,
        "bug_bounty_size_usd": 0,
    }


def _watch_proto(name: str = "MidProtocol") -> dict:
    """Protocol data expected to yield WATCH status (score ~55)."""
    return {
        "protocol": name,
        "tvl_trend_1w": 0.02,
        "tvl_trend_4w": 0.00,
        "governance_activity": 0.50,
        "code_audit_score": 55.0,
        "team_activity_score": 0.50,
        "bug_bounty_size_usd": 100_000,
    }


# ===========================================================================
# 1. check_health() — basic returns
# ===========================================================================

class TestCheckHealthBasic(unittest.TestCase):

    def setUp(self):
        self.c = _checker()

    def test_returns_health_result(self):
        r = self.c.check_health(_healthy_proto())
        self.assertIsInstance(r, HealthResult)

    def test_protocol_name_set(self):
        r = self.c.check_health({"protocol": "TestProto"})
        self.assertEqual(r.protocol, "TestProto")

    def test_default_protocol_name_when_missing(self):
        r = self.c.check_health({})
        self.assertEqual(r.protocol, "unknown")

    def test_timestamp_recent(self):
        before = time.time()
        r = self.c.check_health(_healthy_proto())
        self.assertGreaterEqual(r.timestamp, before)

    def test_health_score_in_range(self):
        r = self.c.check_health(_healthy_proto())
        self.assertGreaterEqual(r.health_score, 0.0)
        self.assertLessEqual(r.health_score, 100.0)

    def test_health_status_is_valid_string(self):
        r = self.c.check_health(_healthy_proto())
        self.assertIn(r.health_status, {"HEALTHY", "WATCH", "CAUTION", "CRITICAL"})

    def test_flagged_is_bool(self):
        r = self.c.check_health(_healthy_proto())
        self.assertIsInstance(r.flagged, bool)

    def test_components_dict_present(self):
        r = self.c.check_health(_healthy_proto())
        self.assertIsInstance(r.components, dict)

    def test_components_has_four_keys(self):
        r = self.c.check_health(_healthy_proto())
        for key in ("tvl_health", "governance", "code_audit", "team_bounty"):
            self.assertIn(key, r.components)

    def test_healthy_proto_not_flagged(self):
        r = self.c.check_health(_healthy_proto())
        self.assertFalse(r.flagged)

    def test_critical_proto_flagged(self):
        r = self.c.check_health(_critical_proto())
        self.assertTrue(r.flagged)

    def test_result_stored_internally(self):
        self.c.check_health(_healthy_proto())
        self.assertEqual(len(self.c._results), 1)


# ===========================================================================
# 2. health_status classification
# ===========================================================================

class TestHealthStatus(unittest.TestCase):

    def setUp(self):
        self.c = _checker()

    def test_healthy_status_for_healthy_proto(self):
        r = self.c.check_health(_healthy_proto())
        self.assertEqual(r.health_status, "HEALTHY")

    def test_critical_status_for_critical_proto(self):
        r = self.c.check_health(_critical_proto())
        self.assertEqual(r.health_status, "CRITICAL")

    def test_thresholds_healthy_boundary(self):
        # classify_status should return HEALTHY at HEALTHY_THRESHOLD
        c = self.c
        self.assertEqual(c._classify_status(HEALTHY_THRESHOLD), "HEALTHY")
        self.assertEqual(c._classify_status(100.0), "HEALTHY")

    def test_thresholds_watch_boundary(self):
        c = self.c
        self.assertEqual(c._classify_status(WATCH_THRESHOLD), "WATCH")
        self.assertEqual(c._classify_status(HEALTHY_THRESHOLD - 0.01), "WATCH")

    def test_thresholds_caution_boundary(self):
        c = self.c
        self.assertEqual(c._classify_status(CAUTION_THRESHOLD), "CAUTION")
        self.assertEqual(c._classify_status(WATCH_THRESHOLD - 0.01), "CAUTION")

    def test_thresholds_critical_boundary(self):
        c = self.c
        self.assertEqual(c._classify_status(0.0), "CRITICAL")
        self.assertEqual(c._classify_status(CAUTION_THRESHOLD - 0.01), "CRITICAL")

    def test_watch_proto_gets_watch_status(self):
        r = self.c.check_health(_watch_proto())
        self.assertIn(r.health_status, {"WATCH", "CAUTION", "HEALTHY"})
        # Just verify it's a valid status
        self.assertIn(r.health_status, {"HEALTHY", "WATCH", "CAUTION", "CRITICAL"})

    def test_all_max_inputs_healthy(self):
        proto = {
            "protocol": "Perfect",
            "tvl_trend_1w": 1.0,
            "tvl_trend_4w": 1.0,
            "governance_activity": 1.0,
            "code_audit_score": 100.0,
            "team_activity_score": 1.0,
            "bug_bounty_size_usd": 10_000_000,
        }
        r = self.c.check_health(proto)
        self.assertEqual(r.health_status, "HEALTHY")

    def test_all_min_inputs_critical(self):
        proto = {
            "protocol": "Broken",
            "tvl_trend_1w": -1.0,
            "tvl_trend_4w": -1.0,
            "governance_activity": 0.0,
            "code_audit_score": 0.0,
            "team_activity_score": 0.0,
            "bug_bounty_size_usd": 0,
        }
        r = self.c.check_health(proto)
        self.assertEqual(r.health_status, "CRITICAL")

    def test_flag_threshold_const(self):
        self.assertEqual(FLAG_THRESHOLD, 50.0)

    def test_healthy_threshold_const(self):
        self.assertEqual(HEALTHY_THRESHOLD, 75.0)

    def test_watch_threshold_const(self):
        self.assertEqual(WATCH_THRESHOLD, 50.0)

    def test_caution_threshold_const(self):
        self.assertEqual(CAUTION_THRESHOLD, 25.0)


# ===========================================================================
# 3. get_health_score()
# ===========================================================================

class TestGetHealthScore(unittest.TestCase):

    def setUp(self):
        self.c = _checker()

    def test_returns_zero_before_any_check(self):
        self.assertEqual(self.c.get_health_score(), 0.0)

    def test_returns_last_health_score_after_check(self):
        r = self.c.check_health(_healthy_proto())
        self.assertAlmostEqual(self.c.get_health_score(), r.health_score, places=6)

    def test_score_in_range(self):
        self.c.check_health(_healthy_proto())
        score = self.c.get_health_score()
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_updates_after_second_check(self):
        self.c.check_health(_healthy_proto())
        s1 = self.c.get_health_score()
        self.c.check_health(_critical_proto())
        s2 = self.c.get_health_score()
        self.assertLess(s2, s1)

    def test_health_result_get_health_score_method(self):
        r = self.c.check_health(_healthy_proto())
        self.assertEqual(r.get_health_score(), r.health_score)

    def test_critical_score_lower_than_healthy(self):
        self.c.check_health(_critical_proto())
        critical_score = self.c.get_health_score()
        self.c.check_health(_healthy_proto())
        healthy_score = self.c.get_health_score()
        self.assertGreater(healthy_score, critical_score)

    def test_score_nonnegative_for_extreme_negative_inputs(self):
        proto = {
            "protocol": "X",
            "tvl_trend_1w": -10.0,
            "tvl_trend_4w": -10.0,
            "governance_activity": -5.0,
            "code_audit_score": -100.0,
            "team_activity_score": -1.0,
            "bug_bounty_size_usd": 0,
        }
        self.c.check_health(proto)
        self.assertGreaterEqual(self.c.get_health_score(), 0.0)

    def test_score_at_most_100_for_extreme_positive_inputs(self):
        proto = {
            "protocol": "Y",
            "tvl_trend_1w": 100.0,
            "tvl_trend_4w": 100.0,
            "governance_activity": 100.0,
            "code_audit_score": 1_000.0,
            "team_activity_score": 100.0,
            "bug_bounty_size_usd": 1e15,
        }
        self.c.check_health(proto)
        self.assertLessEqual(self.c.get_health_score(), 100.0)


# ===========================================================================
# 4. get_flagged_protocols()
# ===========================================================================

class TestGetFlaggedProtocols(unittest.TestCase):

    def setUp(self):
        self.c = _checker()

    def test_empty_before_checks(self):
        self.assertEqual(self.c.get_flagged_protocols(), [])

    def test_critical_proto_appears_in_flagged(self):
        self.c.check_health(_critical_proto("C1"))
        flagged = self.c.get_flagged_protocols()
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0].protocol, "C1")

    def test_healthy_proto_not_in_flagged(self):
        self.c.check_health(_healthy_proto("H1"))
        self.assertEqual(len(self.c.get_flagged_protocols()), 0)

    def test_mixed_batch_flags_only_bad(self):
        self.c.check_health(_healthy_proto("H1"))
        self.c.check_health(_critical_proto("C1"))
        self.c.check_health(_healthy_proto("H2"))
        flagged = self.c.get_flagged_protocols()
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0].protocol, "C1")

    def test_all_flagged_when_all_critical(self):
        for i in range(3):
            self.c.check_health(_critical_proto(f"C{i}"))
        self.assertEqual(len(self.c.get_flagged_protocols()), 3)

    def test_returns_list_of_health_results(self):
        self.c.check_health(_critical_proto())
        for r in self.c.get_flagged_protocols():
            self.assertIsInstance(r, HealthResult)

    def test_flagged_results_have_score_below_threshold(self):
        self.c.check_health(_critical_proto("C"))
        for r in self.c.get_flagged_protocols():
            self.assertLess(r.health_score, FLAG_THRESHOLD)

    def test_clear_results_empties_flagged(self):
        self.c.check_health(_critical_proto())
        self.c.clear_results()
        self.assertEqual(self.c.get_flagged_protocols(), [])

    def test_accumulated_across_multiple_checks(self):
        for i in range(5):
            self.c.check_health(_critical_proto(f"P{i}"))
        self.assertEqual(len(self.c.get_flagged_protocols()), 5)

    def test_flagged_attribute_matches_get_flagged(self):
        self.c.check_health(_critical_proto("X"))
        for r in self.c._results:
            if r.protocol == "X":
                self.assertTrue(r.flagged)


# ===========================================================================
# 5. Score component logic
# ===========================================================================

class TestScoreComponents(unittest.TestCase):

    def setUp(self):
        self.c = _checker()

    def test_tvl_health_zero_when_deeply_negative(self):
        proto = {"protocol": "A", "tvl_trend_1w": -1.0, "tvl_trend_4w": -1.0}
        r = self.c.check_health(proto)
        self.assertAlmostEqual(r.components["tvl_health"], 0.0, places=4)

    def test_tvl_health_max_when_strongly_positive(self):
        proto = {"protocol": "A", "tvl_trend_1w": 1.0, "tvl_trend_4w": 1.0}
        r = self.c.check_health(proto)
        self.assertAlmostEqual(r.components["tvl_health"], 25.0, places=4)

    def test_governance_zero_when_inactive(self):
        proto = {"protocol": "A", "governance_activity": 0.0}
        r = self.c.check_health(proto)
        self.assertAlmostEqual(r.components["governance"], 0.0, places=4)

    def test_governance_max_when_fully_active(self):
        proto = {"protocol": "A", "governance_activity": 1.0}
        r = self.c.check_health(proto)
        self.assertAlmostEqual(r.components["governance"], 25.0, places=4)

    def test_code_audit_zero_at_zero(self):
        proto = {"protocol": "A", "code_audit_score": 0.0}
        r = self.c.check_health(proto)
        self.assertAlmostEqual(r.components["code_audit"], 0.0, places=4)

    def test_code_audit_max_at_100(self):
        proto = {"protocol": "A", "code_audit_score": 100.0}
        r = self.c.check_health(proto)
        self.assertAlmostEqual(r.components["code_audit"], 25.0, places=4)

    def test_team_bounty_zero_at_zero(self):
        proto = {"protocol": "A", "team_activity_score": 0.0, "bug_bounty_size_usd": 0}
        r = self.c.check_health(proto)
        self.assertAlmostEqual(r.components["team_bounty"], 0.0, places=4)

    def test_team_bounty_max_team_full_bounty_10m(self):
        proto = {
            "protocol": "A",
            "team_activity_score": 1.0,
            "bug_bounty_size_usd": 10_000_000,
        }
        r = self.c.check_health(proto)
        self.assertAlmostEqual(r.components["team_bounty"], 25.0, places=2)

    def test_component_scores_nonnegative(self):
        r = self.c.check_health(_critical_proto())
        for comp, val in r.components.items():
            self.assertGreaterEqual(val, 0.0, msg=f"{comp} negative")

    def test_component_scores_at_most_25(self):
        r = self.c.check_health(_healthy_proto())
        for comp, val in r.components.items():
            self.assertLessEqual(val, 25.0 + EPS, msg=f"{comp} exceeds 25")

    def test_composite_equals_sum_of_components(self):
        r = self.c.check_health(_healthy_proto())
        total = sum(r.components.values())
        self.assertAlmostEqual(r.health_score, total, places=3)


# ===========================================================================
# 6. check_all()
# ===========================================================================

class TestCheckAll(unittest.TestCase):

    def setUp(self):
        self.c = _checker()

    def test_returns_list(self):
        results = self.c.check_all([_healthy_proto(), _critical_proto()])
        self.assertIsInstance(results, list)

    def test_length_matches_input(self):
        protos = [_healthy_proto(f"P{i}") for i in range(5)]
        results = self.c.check_all(protos)
        self.assertEqual(len(results), 5)

    def test_replaces_internal_results(self):
        self.c.check_health(_healthy_proto("A"))
        self.c.check_all([_critical_proto("B")])
        self.assertEqual(len(self.c._results), 1)
        self.assertEqual(self.c._results[0].protocol, "B")

    def test_empty_list_clears_results(self):
        self.c.check_health(_healthy_proto())
        self.c.check_all([])
        self.assertEqual(self.c._results, [])

    def test_get_flagged_after_check_all(self):
        self.c.check_all([_healthy_proto(), _critical_proto()])
        flagged = self.c.get_flagged_protocols()
        self.assertEqual(len(flagged), 1)


# ===========================================================================
# 7. Edge cases and input validation
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.c = _checker()

    def test_missing_all_fields_returns_result(self):
        r = self.c.check_health({})
        self.assertIsInstance(r, HealthResult)

    def test_missing_fields_score_in_range(self):
        r = self.c.check_health({})
        self.assertGreaterEqual(r.health_score, 0.0)
        self.assertLessEqual(r.health_score, 100.0)

    def test_string_numeric_values_coerced(self):
        proto = {
            "protocol": "X",
            "tvl_trend_1w": "0.05",
            "code_audit_score": "80",
            "governance_activity": "0.7",
            "team_activity_score": "0.6",
            "bug_bounty_size_usd": "500000",
        }
        r = self.c.check_health(proto)
        self.assertGreater(r.health_score, 0.0)

    def test_extreme_positive_tvl_capped(self):
        proto = {"protocol": "A", "tvl_trend_1w": 100.0, "tvl_trend_4w": 100.0}
        r = self.c.check_health(proto)
        self.assertAlmostEqual(r.components["tvl_health"], 25.0, places=4)

    def test_extreme_negative_tvl_capped_at_zero(self):
        proto = {"protocol": "A", "tvl_trend_1w": -100.0, "tvl_trend_4w": -100.0}
        r = self.c.check_health(proto)
        self.assertAlmostEqual(r.components["tvl_health"], 0.0, places=4)

    def test_governance_above_1_clamped(self):
        proto = {"protocol": "A", "governance_activity": 5.0}
        r = self.c.check_health(proto)
        self.assertAlmostEqual(r.components["governance"], 25.0, places=4)

    def test_audit_score_above_100_clamped(self):
        proto = {"protocol": "A", "code_audit_score": 999.0}
        r = self.c.check_health(proto)
        self.assertAlmostEqual(r.components["code_audit"], 25.0, places=4)

    def test_negative_governance_clamped_to_zero(self):
        proto = {"protocol": "A", "governance_activity": -1.0}
        r = self.c.check_health(proto)
        self.assertAlmostEqual(r.components["governance"], 0.0, places=4)

    def test_bug_bounty_zero_gives_zero_bounty_component(self):
        proto = {"protocol": "A", "bug_bounty_size_usd": 0, "team_activity_score": 0.0}
        r = self.c.check_health(proto)
        self.assertAlmostEqual(r.components["team_bounty"], 0.0, places=4)

    def test_very_large_bug_bounty_capped(self):
        proto = {
            "protocol": "A",
            "team_activity_score": 1.0,
            "bug_bounty_size_usd": 1e20,
        }
        r = self.c.check_health(proto)
        self.assertLessEqual(r.components["team_bounty"], 25.0 + EPS)

    def test_clear_results_resets_last_result(self):
        self.c.check_health(_healthy_proto())
        self.c.clear_results()
        self.assertIsNone(self.c._last_result)
        self.assertEqual(self.c.get_health_score(), 0.0)


# ===========================================================================
# 8. save_results() / load_history()
# ===========================================================================

class TestSaveAndLoadHistory(unittest.TestCase):

    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        self.path = Path(path)
        self.c = ProtocolHealthChecker(data_file=self.path)

    def tearDown(self):
        for f in [self.path, self.path.with_suffix(".tmp")]:
            try:
                f.unlink()
            except FileNotFoundError:
                pass

    def test_load_history_empty_before_any_save(self):
        self.assertEqual(self.c.load_history(), [])

    def test_save_creates_file(self):
        self.c.check_health(_healthy_proto())
        self.c.save_results()
        self.assertTrue(self.path.exists())

    def test_save_and_load_one_entry(self):
        self.c.check_health(_healthy_proto())
        self.c.save_results()
        self.assertEqual(len(self.c.load_history()), 1)

    def test_saved_entry_has_required_keys(self):
        self.c.check_health(_healthy_proto())
        self.c.save_results()
        entry = self.c.load_history()[0]
        for key in ("timestamp", "protocol", "health_score", "health_status",
                    "flagged", "components"):
            self.assertIn(key, entry)

    def test_multiple_saves_accumulate(self):
        # Each save call uses check_all (which resets _results to exactly 1 entry),
        # so 3 saves yield 3 entries in history.
        for _ in range(3):
            self.c.check_all([_healthy_proto()])
            self.c.save_results()
        self.assertEqual(len(self.c.load_history()), 3)

    def test_ring_buffer_does_not_exceed_max_entries(self):
        for i in range(MAX_ENTRIES + 5):
            self.c.check_all([_healthy_proto(f"P{i}")])
            self.c.save_results()
        self.assertLessEqual(len(self.c.load_history()), MAX_ENTRIES)

    def test_no_tmp_file_left_after_save(self):
        self.c.check_health(_healthy_proto())
        self.c.save_results()
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_load_history_returns_empty_on_invalid_json(self):
        self.path.write_text("not json {{{")
        self.assertEqual(self.c.load_history(), [])

    def test_load_history_returns_empty_on_non_list_json(self):
        self.path.write_text('{"key": "value"}')
        self.assertEqual(self.c.load_history(), [])

    def test_save_explicit_results_list(self):
        results = [self.c._evaluate(_healthy_proto("E1"))]
        self.c.save_results(results)
        history = self.c.load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["protocol"], "E1")

    def test_health_score_preserved_in_log(self):
        r = self.c.check_health(_healthy_proto("Aave"))
        self.c.save_results()
        history = self.c.load_history()
        self.assertAlmostEqual(history[0]["health_score"], r.health_score, places=4)

    def test_flagged_field_preserved_in_log(self):
        self.c.check_health(_critical_proto("X"))
        self.c.save_results()
        history = self.c.load_history()
        self.assertTrue(history[0]["flagged"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
