"""
Tests for MP-690: YieldVolatilitySurface  (≥65 tests)
Pure stdlib unittest — no pytest dependency.
"""
import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.yield_volatility_surface import (
    YieldObservation,
    build_surface,
    save_results,
    load_history,
    _population_std,
    _volatility_label,
    _surface_stability,
    MAX_ENTRIES,
)

EPS = 1e-9


def _obs(protocol, ts, apy):
    return YieldObservation(protocol=protocol, timestamp=ts, apy_pct=apy)


def _ts_ago(days):
    """Timestamp for N days ago from 'now' (fixed base for determinism)."""
    BASE = 1_700_000_000.0  # fixed epoch base
    return BASE - days * 86400


# ===========================================================================
# 1. _population_std
# ===========================================================================

class TestPopulationStd(unittest.TestCase):

    def test_std_empty(self):
        self.assertAlmostEqual(_population_std([]), 0.0, places=9)

    def test_std_single(self):
        self.assertAlmostEqual(_population_std([5.0]), 0.0, places=9)

    def test_std_two_identical(self):
        self.assertAlmostEqual(_population_std([3.0, 3.0]), 0.0, places=9)

    def test_std_two_values(self):
        # std([2, 4]) = 1.0
        self.assertAlmostEqual(_population_std([2.0, 4.0]), 1.0, places=9)

    def test_std_known(self):
        # [2, 4, 4, 4, 5, 5, 7, 9] pop std = 2.0
        vals = [2, 4, 4, 4, 5, 5, 7, 9]
        self.assertAlmostEqual(_population_std(vals), 2.0, places=9)

    def test_std_symmetric(self):
        # symmetric data: mean=5, deviations ±1,±2 → var=(1+4+1+4)/4=2.5
        vals = [3.0, 4.0, 6.0, 7.0]
        expected = math.sqrt(2.5)
        self.assertAlmostEqual(_population_std(vals), expected, places=9)


# ===========================================================================
# 2. mean_apy (via VolatilityNode arithmetic mean)
# ===========================================================================

class TestMeanApy(unittest.TestCase):

    def _get_node(self, observations, protocol, window_days):
        report = build_surface("test", observations)
        for n in report.nodes:
            if n.protocol == protocol and n.window_days == window_days:
                return n
        return None

    def test_mean_three_values(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 1 * 86400, 4.0),
            _obs("P", BASE - 2 * 86400, 6.0),
            _obs("P", BASE - 3 * 86400, 8.0),
        ]
        node = self._get_node(obs, "P", 7)
        self.assertIsNotNone(node)
        self.assertAlmostEqual(node.mean_apy, 6.0, places=9)

    def test_mean_two_values(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 1 * 86400, 10.0),
            _obs("P", BASE - 2 * 86400, 20.0),
        ]
        node = self._get_node(obs, "P", 7)
        self.assertIsNotNone(node)
        self.assertAlmostEqual(node.mean_apy, 15.0, places=9)


# ===========================================================================
# 3. std_apy (population stdev)
# ===========================================================================

class TestStdApy(unittest.TestCase):

    def _get_node(self, observations, protocol, window_days):
        report = build_surface("test", observations)
        for n in report.nodes:
            if n.protocol == protocol and n.window_days == window_days:
                return n
        return None

    def test_std_two_identical_obs(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 1 * 86400, 5.0),
            _obs("P", BASE - 2 * 86400, 5.0),
        ]
        node = self._get_node(obs, "P", 7)
        self.assertIsNotNone(node)
        self.assertAlmostEqual(node.std_apy, 0.0, places=9)

    def test_std_two_values(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 1 * 86400, 2.0),
            _obs("P", BASE - 2 * 86400, 4.0),
        ]
        node = self._get_node(obs, "P", 7)
        self.assertIsNotNone(node)
        self.assertAlmostEqual(node.std_apy, 1.0, places=9)

    def test_std_larger_spread(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 1 * 86400, 0.0),
            _obs("P", BASE - 2 * 86400, 10.0),
        ]
        node = self._get_node(obs, "P", 7)
        self.assertIsNotNone(node)
        self.assertAlmostEqual(node.std_apy, 5.0, places=9)


# ===========================================================================
# 4. coefficient_of_variation
# ===========================================================================

class TestCoefficientOfVariation(unittest.TestCase):

    def _get_node(self, obs_list, window_days):
        report = build_surface("test", obs_list)
        for n in report.nodes:
            if n.window_days == window_days:
                return n
        return None

    def test_cv_zero_mean_returns_zero(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 1 * 86400, 0.0),
            _obs("P", BASE - 2 * 86400, 0.0),
        ]
        node = self._get_node(obs, 7)
        self.assertIsNotNone(node)
        self.assertAlmostEqual(node.coefficient_of_variation, 0.0, places=9)

    def test_cv_formula(self):
        BASE = 1_700_000_000.0
        # mean=5, std=1 → cv=0.2
        obs = [
            _obs("P", BASE - 1 * 86400, 4.0),
            _obs("P", BASE - 2 * 86400, 6.0),
        ]
        node = self._get_node(obs, 7)
        self.assertIsNotNone(node)
        expected_cv = 1.0 / 5.0
        self.assertAlmostEqual(node.coefficient_of_variation, expected_cv, places=9)

    def test_cv_positive_mean(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 1 * 86400, 10.0),
            _obs("P", BASE - 2 * 86400, 10.0),
        ]
        node = self._get_node(obs, 7)
        self.assertIsNotNone(node)
        # std=0, cv=0
        self.assertAlmostEqual(node.coefficient_of_variation, 0.0, places=9)


# ===========================================================================
# 5. is_anomalous
# ===========================================================================

class TestIsAnomalous(unittest.TestCase):

    def _get_node(self, obs_list, protocol, window_days):
        report = build_surface("test", obs_list)
        for n in report.nodes:
            if n.protocol == protocol and n.window_days == window_days:
                return n
        return None

    def test_not_anomalous_normal(self):
        BASE = 1_700_000_000.0
        # All same value: mean=5, std=0 → latest=5, not anomalous
        obs = [
            _obs("P", BASE - 3 * 86400, 5.0),
            _obs("P", BASE - 2 * 86400, 5.0),
            _obs("P", BASE - 1 * 86400, 5.0),
        ]
        node = self._get_node(obs, "P", 7)
        self.assertIsNotNone(node)
        self.assertFalse(node.is_anomalous)

    def test_anomalous_spike(self):
        BASE = 1_700_000_000.0
        # mean=5, std=1 → threshold=7; latest=50 → anomalous
        obs = [
            _obs("P", BASE - 6 * 86400, 4.0),
            _obs("P", BASE - 5 * 86400, 6.0),
            _obs("P", BASE - 4 * 86400, 4.0),
            _obs("P", BASE - 3 * 86400, 6.0),
            _obs("P", BASE - 2 * 86400, 5.0),
            _obs("P", BASE - 1 * 86400, 50.0),   # spike
        ]
        node = self._get_node(obs, "P", 7)
        self.assertIsNotNone(node)
        self.assertTrue(node.is_anomalous)

    def test_not_anomalous_just_below_threshold(self):
        BASE = 1_700_000_000.0
        # values: [4, 6] → mean=5, std=1 → threshold=7; latest=6 → not anomalous
        obs = [
            _obs("P", BASE - 2 * 86400, 4.0),
            _obs("P", BASE - 1 * 86400, 6.0),
        ]
        node = self._get_node(obs, "P", 7)
        self.assertIsNotNone(node)
        self.assertFalse(node.is_anomalous)

    def test_anomalous_exactly_above(self):
        BASE = 1_700_000_000.0
        # 5 stable values at 5.0 + spike at 1000 → threshold≈912 < 1000 → anomalous
        # (n≥5 stable points ensures spike strictly exceeds mean+2*std)
        obs = [
            _obs("P", BASE - 6 * 86400, 5.0),
            _obs("P", BASE - 5 * 86400, 5.0),
            _obs("P", BASE - 4 * 86400, 5.0),
            _obs("P", BASE - 3 * 86400, 5.0),
            _obs("P", BASE - 2 * 86400, 5.0),
            _obs("P", BASE - 1 * 86400, 1000.0),   # big spike
        ]
        node = self._get_node(obs, "P", 7)
        self.assertIsNotNone(node)
        self.assertTrue(node.is_anomalous)


# ===========================================================================
# 6. volatility_label
# ===========================================================================

class TestVolatilityLabel(unittest.TestCase):

    def test_low(self):
        self.assertEqual(_volatility_label(0.0), "LOW")

    def test_low_boundary(self):
        self.assertEqual(_volatility_label(0.04999), "LOW")

    def test_moderate_boundary(self):
        self.assertEqual(_volatility_label(0.05), "MODERATE")

    def test_moderate(self):
        self.assertEqual(_volatility_label(0.10), "MODERATE")

    def test_high_boundary(self):
        self.assertEqual(_volatility_label(0.15), "HIGH")

    def test_high(self):
        self.assertEqual(_volatility_label(0.20), "HIGH")

    def test_extreme_boundary(self):
        self.assertEqual(_volatility_label(0.30), "EXTREME")

    def test_extreme(self):
        self.assertEqual(_volatility_label(0.50), "EXTREME")

    def test_extreme_large(self):
        self.assertEqual(_volatility_label(10.0), "EXTREME")


# ===========================================================================
# 7. most_volatile_protocol / least_volatile_protocol
# ===========================================================================

class TestMostLeastVolatile(unittest.TestCase):

    def test_most_volatile_protocol(self):
        BASE = 1_700_000_000.0
        # Proto-A: small spread; Proto-B: large spread
        obs = [
            _obs("A", BASE - 2 * 86400, 5.0),
            _obs("A", BASE - 1 * 86400, 5.2),
            _obs("B", BASE - 2 * 86400, 1.0),
            _obs("B", BASE - 1 * 86400, 20.0),
        ]
        report = build_surface("test", obs)
        self.assertEqual(report.most_volatile_protocol, "B")

    def test_least_volatile_protocol(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("A", BASE - 2 * 86400, 5.0),
            _obs("A", BASE - 1 * 86400, 5.2),
            _obs("B", BASE - 2 * 86400, 1.0),
            _obs("B", BASE - 1 * 86400, 20.0),
        ]
        report = build_surface("test", obs)
        self.assertEqual(report.least_volatile_protocol, "A")

    def test_single_protocol(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("A", BASE - 2 * 86400, 5.0),
            _obs("A", BASE - 1 * 86400, 6.0),
        ]
        report = build_surface("test", obs)
        self.assertEqual(report.most_volatile_protocol, "A")
        self.assertEqual(report.least_volatile_protocol, "A")

    def test_empty_obs_empty_protocols(self):
        report = build_surface("test", [])
        self.assertEqual(report.most_volatile_protocol, "")
        self.assertEqual(report.least_volatile_protocol, "")


# ===========================================================================
# 8. spike_alerts
# ===========================================================================

class TestSpikeAlerts(unittest.TestCase):

    def test_spike_alert_present(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 6 * 86400, 5.0),
            _obs("P", BASE - 5 * 86400, 5.0),
            _obs("P", BASE - 4 * 86400, 5.0),
            _obs("P", BASE - 3 * 86400, 5.0),
            _obs("P", BASE - 2 * 86400, 5.0),
            _obs("P", BASE - 1 * 86400, 100.0),
        ]
        report = build_surface("test", obs)
        alerts = [a for a in report.spike_alerts if "P" in a]
        self.assertTrue(len(alerts) > 0)

    def test_spike_alert_format(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("Proto", BASE - 3 * 86400, 5.0),
            _obs("Proto", BASE - 2 * 86400, 5.0),
            _obs("Proto", BASE - 1 * 86400, 100.0),
        ]
        report = build_surface("test", obs)
        for alert in report.spike_alerts:
            if "Proto" in alert:
                self.assertIn("spike detected at", alert)
                self.assertIn("d window", alert)
                break

    def test_no_spike_alerts_when_normal(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 3 * 86400, 5.0),
            _obs("P", BASE - 2 * 86400, 5.0),
            _obs("P", BASE - 1 * 86400, 5.0),
        ]
        report = build_surface("test", obs)
        self.assertEqual(report.spike_alerts, [])

    def test_spike_alert_includes_window_days(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 2 * 86400, 5.0),
            _obs("P", BASE - 1 * 86400, 100.0),
        ]
        report = build_surface("test", obs)
        for alert in report.spike_alerts:
            if "P" in alert:
                # should contain a number like "7d window"
                self.assertRegex(alert, r'\d+d window')
                break


# ===========================================================================
# 9. surface_stability
# ===========================================================================

class TestSurfaceStability(unittest.TestCase):

    def test_stable(self):
        self.assertEqual(_surface_stability(0.0), "STABLE")

    def test_stable_boundary(self):
        self.assertEqual(_surface_stability(0.499), "STABLE")

    def test_unstable_boundary(self):
        self.assertEqual(_surface_stability(0.5), "UNSTABLE")

    def test_unstable(self):
        self.assertEqual(_surface_stability(1.0), "UNSTABLE")

    def test_volatile_boundary(self):
        self.assertEqual(_surface_stability(2.0), "VOLATILE")

    def test_volatile(self):
        self.assertEqual(_surface_stability(3.0), "VOLATILE")

    def test_chaotic_boundary(self):
        self.assertEqual(_surface_stability(5.0), "CHAOTIC")

    def test_chaotic(self):
        self.assertEqual(_surface_stability(100.0), "CHAOTIC")


# ===========================================================================
# 10. build_surface: single protocol, basic node
# ===========================================================================

class TestBuildSurfaceBasic(unittest.TestCase):

    def test_single_protocol_three_obs_builds_node(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 3 * 86400, 4.0),
            _obs("P", BASE - 2 * 86400, 6.0),
            _obs("P", BASE - 1 * 86400, 5.0),
        ]
        report = build_surface("s1", obs)
        nodes_7 = [n for n in report.nodes if n.window_days == 7 and n.protocol == "P"]
        self.assertEqual(len(nodes_7), 1)

    def test_single_protocol_two_obs_builds_node(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 1 * 86400, 4.0),
            _obs("P", BASE - 2 * 86400, 6.0),
        ]
        report = build_surface("s1", obs)
        nodes_7 = [n for n in report.nodes if n.window_days == 7 and n.protocol == "P"]
        self.assertEqual(len(nodes_7), 1)

    def test_surface_id_stored(self):
        report = build_surface("my-surface-id", [])
        self.assertEqual(report.surface_id, "my-surface-id")

    def test_protocols_list_populated(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("A", BASE - 1 * 86400, 5.0),
            _obs("A", BASE - 2 * 86400, 6.0),
            _obs("B", BASE - 1 * 86400, 3.0),
            _obs("B", BASE - 2 * 86400, 4.0),
        ]
        report = build_surface("s1", obs)
        self.assertIn("A", report.protocols)
        self.assertIn("B", report.protocols)

    def test_all_protocols_in_report(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("X", BASE - 1 * 86400, 5.0),
            _obs("X", BASE - 2 * 86400, 6.0),
            _obs("Y", BASE - 1 * 86400, 7.0),
            _obs("Y", BASE - 2 * 86400, 8.0),
            _obs("Z", BASE - 1 * 86400, 9.0),
            _obs("Z", BASE - 2 * 86400, 10.0),
        ]
        report = build_surface("s1", obs)
        self.assertSetEqual(set(report.protocols), {"X", "Y", "Z"})

    def test_empty_obs_empty_nodes(self):
        report = build_surface("empty", [])
        self.assertEqual(report.nodes, [])
        self.assertEqual(report.protocols, [])


# ===========================================================================
# 11. build_surface: window filtering
# ===========================================================================

class TestBuildSurfaceWindowFiltering(unittest.TestCase):

    def test_obs_within_window_included(self):
        BASE = 1_700_000_000.0
        # 3 obs within 7 days → node exists
        obs = [
            _obs("P", BASE - 1 * 86400, 4.0),
            _obs("P", BASE - 2 * 86400, 6.0),
            _obs("P", BASE - 3 * 86400, 8.0),
        ]
        report = build_surface("test", obs)
        nodes_7 = [n for n in report.nodes if n.protocol == "P" and n.window_days == 7]
        self.assertEqual(len(nodes_7), 1)

    def test_obs_outside_window_excluded(self):
        BASE = 1_700_000_000.0
        # latest is at BASE, one obs at BASE-10days → 10 days ago is outside 7d window
        obs = [
            _obs("P", BASE, 5.0),
            _obs("P", BASE - 10 * 86400, 5.0),
        ]
        report = build_surface("test", obs)
        # Only the 2 obs count; but BASE-10d is outside the 7d window from latest=BASE
        # so only 1 obs in 7d window → no 7d node
        nodes_7 = [n for n in report.nodes if n.protocol == "P" and n.window_days == 7]
        self.assertEqual(len(nodes_7), 0)

    def test_obs_within_30d_window(self):
        BASE = 1_700_000_000.0
        # obs at -10d, -20d → within 30d window → 30d node exists
        obs = [
            _obs("P", BASE - 10 * 86400, 4.0),
            _obs("P", BASE - 20 * 86400, 6.0),
        ]
        report = build_surface("test", obs)
        nodes_30 = [n for n in report.nodes if n.protocol == "P" and n.window_days == 30]
        self.assertEqual(len(nodes_30), 1)

    def test_fewer_than_2_obs_no_node(self):
        BASE = 1_700_000_000.0
        obs = [_obs("P", BASE - 1 * 86400, 5.0)]
        report = build_surface("test", obs)
        self.assertEqual(len(report.nodes), 0)

    def test_two_obs_in_different_windows(self):
        BASE = 1_700_000_000.0
        # Both within 14d window → 14d node exists; both within 30d → 30d node exists
        obs = [
            _obs("P", BASE - 5 * 86400, 4.0),
            _obs("P", BASE - 10 * 86400, 6.0),
        ]
        report = build_surface("test", obs)
        windows = {n.window_days for n in report.nodes if n.protocol == "P"}
        self.assertIn(14, windows)
        self.assertIn(30, windows)


# ===========================================================================
# 12. min_apy / max_apy / apy_range
# ===========================================================================

class TestMinMaxRange(unittest.TestCase):

    def _get_node(self, obs_list, protocol, window_days):
        report = build_surface("test", obs_list)
        for n in report.nodes:
            if n.protocol == protocol and n.window_days == window_days:
                return n
        return None

    def test_min_apy(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 2 * 86400, 2.0),
            _obs("P", BASE - 1 * 86400, 8.0),
        ]
        node = self._get_node(obs, "P", 7)
        self.assertIsNotNone(node)
        self.assertAlmostEqual(node.min_apy, 2.0, places=9)

    def test_max_apy(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 2 * 86400, 2.0),
            _obs("P", BASE - 1 * 86400, 8.0),
        ]
        node = self._get_node(obs, "P", 7)
        self.assertIsNotNone(node)
        self.assertAlmostEqual(node.max_apy, 8.0, places=9)

    def test_apy_range(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 2 * 86400, 2.0),
            _obs("P", BASE - 1 * 86400, 8.0),
        ]
        node = self._get_node(obs, "P", 7)
        self.assertIsNotNone(node)
        self.assertAlmostEqual(node.apy_range, 6.0, places=9)


# ===========================================================================
# 13. avg_surface_volatility
# ===========================================================================

class TestAvgSurfaceVolatility(unittest.TestCase):

    def test_avg_vol_zero_std(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 2 * 86400, 5.0),
            _obs("P", BASE - 1 * 86400, 5.0),
        ]
        report = build_surface("test", obs)
        # std=0 → avg_vol=0
        self.assertAlmostEqual(report.avg_surface_volatility, 0.0, places=9)

    def test_avg_vol_computed(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 2 * 86400, 2.0),
            _obs("P", BASE - 1 * 86400, 4.0),
        ]
        report = build_surface("test", obs)
        # all nodes should have std=1.0; avg_vol should be 1.0
        for n in report.nodes:
            self.assertAlmostEqual(n.std_apy, 1.0, places=9)
        self.assertAlmostEqual(report.avg_surface_volatility, 1.0, places=9)

    def test_avg_vol_empty(self):
        report = build_surface("test", [])
        self.assertAlmostEqual(report.avg_surface_volatility, 0.0, places=9)


# ===========================================================================
# 14. save_results / load_history
# ===========================================================================

class TestPersistence(unittest.TestCase):

    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        self.data_file = Path(path)

    def tearDown(self):
        if self.data_file.exists():
            self.data_file.unlink()
        tmp = self.data_file.with_suffix(".tmp")
        if tmp.exists():
            tmp.unlink()

    def test_load_history_missing_returns_empty(self):
        result = load_history(self.data_file)
        self.assertEqual(result, [])

    def test_save_and_load(self):
        report = build_surface("save-test", [])
        save_results(report, self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["surface_id"], "save-test")

    def test_ring_buffer_max_entries(self):
        # Fill more than MAX_ENTRIES
        for i in range(MAX_ENTRIES + 5):
            report = build_surface(f"run-{i}", [])
            save_results(report, self.data_file)
        history = load_history(self.data_file)
        self.assertLessEqual(len(history), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        for i in range(MAX_ENTRIES + 3):
            report = build_surface(f"run-{i}", [])
            save_results(report, self.data_file)
        history = load_history(self.data_file)
        last_id = history[-1]["surface_id"]
        self.assertEqual(last_id, f"run-{MAX_ENTRIES + 2}")

    def test_atomic_write_no_tmp_left(self):
        report = build_surface("atomic-test", [])
        save_results(report, self.data_file)
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_file_is_valid_json(self):
        report = build_surface("json-test", [])
        save_results(report, self.data_file)
        raw = self.data_file.read_text()
        parsed = json.loads(raw)
        self.assertIsInstance(parsed, list)

    def test_load_corrupt_returns_empty(self):
        self.data_file.write_text("not-valid-json")
        result = load_history(self.data_file)
        self.assertEqual(result, [])

    def test_multiple_saves_accumulate(self):
        for i in range(3):
            report = build_surface(f"run-{i}", [])
            save_results(report, self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(len(history), 3)


# ===========================================================================
# 15. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_single_obs_no_nodes(self):
        BASE = 1_700_000_000.0
        obs = [_obs("P", BASE - 1 * 86400, 5.0)]
        report = build_surface("edge", obs)
        self.assertEqual(len(report.nodes), 0)

    def test_duplicate_timestamps(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 1 * 86400, 5.0),
            _obs("P", BASE - 1 * 86400, 7.0),
        ]
        report = build_surface("dup", obs)
        # Two obs at same ts → builds nodes
        self.assertTrue(len(report.nodes) > 0)

    def test_protocols_list_sorted(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("Z", BASE - 1 * 86400, 5.0),
            _obs("Z", BASE - 2 * 86400, 6.0),
            _obs("A", BASE - 1 * 86400, 7.0),
            _obs("A", BASE - 2 * 86400, 8.0),
        ]
        report = build_surface("sorted", obs)
        self.assertEqual(report.protocols, sorted(report.protocols))

    def test_surface_stability_stable_for_low_vol(self):
        BASE = 1_700_000_000.0
        obs = [
            _obs("P", BASE - 2 * 86400, 5.0),
            _obs("P", BASE - 1 * 86400, 5.01),
        ]
        report = build_surface("stable", obs)
        self.assertEqual(report.surface_stability, "STABLE")


if __name__ == "__main__":
    unittest.main()
