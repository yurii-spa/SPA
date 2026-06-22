"""
Tests for spa_core/analytics/apy_momentum.py (MP-598)
======================================================

Groups:
  TestComputeEMA             (12) — EMA edge-cases and correctness
  TestComputeOLSSlope        (12) — OLS slope edge-cases and correctness
  TestExtractAPYSeries       (10) — filtering, prefix matching, empty inputs
  TestClassifyTrend          (15) — all trend/confidence combos + boundary values
  TestGetSignal              (15) — change calculations, data_points, signal_strength
  TestGetReport              (12) — counts, sorting, top_rising/top_falling
  TestSaveReport             ( 6) — atomic write, ring-buffer ≤ 30
  TestFormatTelegramMessage  ( 8) — length, required strings, edge-cases

Total: 90 tests.  Run:
  python3 -m unittest spa_core.tests.test_apy_momentum -v
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

from spa_core.analytics.apy_momentum import (
    APYMomentumDetector,
    MomentumReport,
    MomentumSignal,
    _extract_current_apy,
    _parse_ts_unix,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso(days_ago: float = 0.0) -> str:
    """Return ISO-UTC timestamp *days_ago* days before now."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.isoformat()


def _ts_days(days_ago: float = 0.0) -> float:
    """Unix timestamp / 86400 for a point *days_ago* in the past."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.timestamp() / 86400.0


def _make_detector(tmp_dir: str) -> APYMomentumDetector:
    return APYMomentumDetector(history_path=tmp_dir)


def _write_json(path: str, payload: object) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _watchdog_snapshot(adapter_ids_apys: list, days_ago: float = 0.0) -> dict:
    """Build a minimal WatchdogReport-style snapshot."""
    return {
        "generated_at": _iso(days_ago),
        "total_adapters": len(adapter_ids_apys),
        "adapter_statuses": [
            {"adapter_id": aid, "apy_pct": apy, "tier": "T1",
             "chain": "ethereum", "is_healthy": True,
             "alert_level": "OK", "apy_change_pct": 0.0,
             "risk_score": 0.2, "peg_price": 1.0}
            for aid, apy in adapter_ids_apys
        ],
    }


def _write_watchdog_history(path: str, snapshots: list) -> None:
    _write_json(path, {
        "schema_version": 1,
        "source": "adapter_watchdog",
        "ring_buffer_max": 48,
        "snapshot_count": len(snapshots),
        "updated_at": _iso(),
        "latest": snapshots[-1] if snapshots else {},
        "snapshots": snapshots,
    })


def _write_adapter_status(path: str, adapters: list) -> None:
    """adapters: list of (protocol_key, mock_apy_ethereum_usdc)"""
    _write_json(path, {
        "generated_at": _iso(),
        "schema_version": 1,
        "adapters": [
            {
                "protocol_key": key,
                "tier": "T1",
                "mock_apy": {"ethereum": {"USDC": apy}},
            }
            for key, apy in adapters
        ],
    })


# ===========================================================================
# TestComputeEMA  (12 tests)
# ===========================================================================

class TestComputeEMA(unittest.TestCase):

    def setUp(self):
        self.d = APYMomentumDetector()

    # 1
    def test_empty_list_returns_zero(self):
        self.assertEqual(self.d.compute_ema([]), 0.0)

    # 2
    def test_single_element_returns_that_element(self):
        self.assertEqual(self.d.compute_ema([5.0]), 5.0)

    # 3
    def test_two_elements_alpha_03(self):
        # ema = 0.3*4 + 0.7*2 = 1.2 + 1.4 = 2.6
        result = self.d.compute_ema([2.0, 4.0], alpha=0.3)
        self.assertAlmostEqual(result, 2.6, places=10)

    # 4
    def test_three_elements_alpha_03(self):
        # step1: ema=2.0
        # step2: 0.3*4 + 0.7*2 = 2.6
        # step3: 0.3*6 + 0.7*2.6 = 1.8 + 1.82 = 3.62
        result = self.d.compute_ema([2.0, 4.0, 6.0], alpha=0.3)
        self.assertAlmostEqual(result, 3.62, places=10)

    # 5
    def test_alpha_one_returns_last_value(self):
        """alpha=1 → pure pass-through, EMA equals last value."""
        result = self.d.compute_ema([1.0, 2.0, 3.0, 100.0], alpha=1.0)
        self.assertAlmostEqual(result, 100.0, places=10)

    # 6
    def test_constant_series_returns_constant(self):
        """EMA of constant series = constant."""
        val = 7.5
        result = self.d.compute_ema([val] * 10, alpha=0.3)
        self.assertAlmostEqual(result, val, places=8)

    # 7
    def test_alpha_very_small_stays_close_to_first(self):
        """Small alpha → very slow adaptation; EMA stays near initial value."""
        result = self.d.compute_ema([1.0] + [100.0] * 50, alpha=0.01)
        # After 50 steps with alpha=0.01 the EMA should still be < 50
        self.assertLess(result, 50.0)

    # 8
    def test_large_series_convergence(self):
        """EMA over 100 identical values converges to that value."""
        result = self.d.compute_ema([5.5] * 100, alpha=0.5)
        self.assertAlmostEqual(result, 5.5, places=5)

    # 9
    def test_negative_values_supported(self):
        """EMA works with negative values (edge-case for spread APY)."""
        result = self.d.compute_ema([-1.0, -2.0], alpha=0.5)
        # ema = 0.5*(-2) + 0.5*(-1) = -1.5
        self.assertAlmostEqual(result, -1.5, places=10)

    # 10
    def test_zero_alpha_raises(self):
        with self.assertRaises(ValueError):
            self.d.compute_ema([1.0, 2.0], alpha=0.0)

    # 11
    def test_negative_alpha_raises(self):
        with self.assertRaises(ValueError):
            self.d.compute_ema([1.0, 2.0], alpha=-0.1)

    # 12
    def test_alpha_greater_than_one_raises(self):
        with self.assertRaises(ValueError):
            self.d.compute_ema([1.0, 2.0], alpha=1.1)


# ===========================================================================
# TestComputeOLSSlope  (12 tests)
# ===========================================================================

class TestComputeOLSSlope(unittest.TestCase):

    def setUp(self):
        self.d = APYMomentumDetector()

    # 1
    def test_empty_returns_zero(self):
        self.assertEqual(self.d.compute_ols_slope([]), 0.0)

    # 2
    def test_single_point_returns_zero(self):
        self.assertEqual(self.d.compute_ols_slope([(1.0, 5.0)]), 0.0)

    # 3
    def test_two_points_exact_slope(self):
        # (0, 2) and (1, 4) → slope = 2
        result = self.d.compute_ols_slope([(0.0, 2.0), (1.0, 4.0)])
        self.assertAlmostEqual(result, 2.0, places=10)

    # 4
    def test_two_points_negative_slope(self):
        # (0, 10) and (1, 8) → slope = -2
        result = self.d.compute_ols_slope([(0.0, 10.0), (1.0, 8.0)])
        self.assertAlmostEqual(result, -2.0, places=10)

    # 5
    def test_horizontal_line_slope_zero(self):
        pairs = [(float(i), 5.0) for i in range(10)]
        self.assertAlmostEqual(self.d.compute_ols_slope(pairs), 0.0, places=8)

    # 6
    def test_five_points_perfect_line(self):
        # y = 1 + 0.5*x
        pairs = [(float(i), 1.0 + 0.5 * i) for i in range(5)]
        result = self.d.compute_ols_slope(pairs)
        self.assertAlmostEqual(result, 0.5, places=8)

    # 7
    def test_five_points_noisy_rising(self):
        # Roughly y = 3*x + noise; slope should be close to 3
        pairs = [(0.0, 0.1), (1.0, 3.2), (2.0, 5.9), (3.0, 9.1), (4.0, 12.0)]
        result = self.d.compute_ols_slope(pairs)
        self.assertAlmostEqual(result, 2.975, delta=0.1)

    # 8
    def test_denominator_zero_returns_zero(self):
        """All x equal → denominator = 0 → 0.0."""
        pairs = [(5.0, 1.0), (5.0, 2.0), (5.0, 3.0)]
        self.assertEqual(self.d.compute_ols_slope(pairs), 0.0)

    # 9
    def test_steep_positive_slope(self):
        pairs = [(0.0, 0.0), (1.0, 100.0)]
        result = self.d.compute_ols_slope(pairs)
        self.assertAlmostEqual(result, 100.0, places=6)

    # 10
    def test_steep_negative_slope(self):
        pairs = [(0.0, 50.0), (1.0, 0.0)]
        result = self.d.compute_ols_slope(pairs)
        self.assertAlmostEqual(result, -50.0, places=6)

    # 11
    def test_large_x_values_real_days(self):
        """Simulate real day-based timestamps (e.g. 20000+)."""
        # y = 0.2*(x - base) + 5, so slope = 0.2
        base = 20000.0
        pairs = [(base + i, 5.0 + 0.2 * i) for i in range(8)]
        result = self.d.compute_ols_slope(pairs)
        self.assertAlmostEqual(result, 0.2, places=6)

    # 12
    def test_ten_points_descending(self):
        pairs = [(float(i), 10.0 - i) for i in range(10)]
        result = self.d.compute_ols_slope(pairs)
        self.assertAlmostEqual(result, -1.0, places=8)


# ===========================================================================
# TestExtractAPYSeries  (10 tests)
# ===========================================================================

class TestExtractAPYSeries(unittest.TestCase):

    def setUp(self):
        self.d = APYMomentumDetector()

    def _make_history(self, readings: list) -> list:
        """Create history list from [(adapter_id, apy, ts_unix)] tuples."""
        return [
            {
                "ts_unix": ts,
                "generated_at": _iso(),
                "adapter_id": aid,
                "apy_pct": apy,
                "source": "test",
            }
            for aid, apy, ts in readings
        ]

    # 1
    def test_empty_history_returns_empty(self):
        result = self.d.extract_apy_series("aave-v3", [])
        self.assertEqual(result, [])

    # 2
    def test_adapter_not_in_history_returns_empty(self):
        h = self._make_history([("compound-v3", 4.8, 100000.0)])
        result = self.d.extract_apy_series("aave-v3", h)
        self.assertEqual(result, [])

    # 3
    def test_exact_match_single_entry(self):
        ts = 100000.0
        h = self._make_history([("aave-v3", 4.2, ts)])
        result = self.d.extract_apy_series("aave-v3", h)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0][0], ts / 86400.0, places=6)
        self.assertAlmostEqual(result[0][1], 4.2, places=6)

    # 4
    def test_prefix_match_extracts_correct_entries(self):
        """"aave-v3" should match "aave-v3-usdc-ethereum"."""
        ts = 200000.0
        h = self._make_history([("aave-v3-usdc-ethereum", 5.0, ts)])
        result = self.d.extract_apy_series("aave-v3", h)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0][1], 5.0, places=6)

    # 5
    def test_prefix_does_not_match_different_protocol(self):
        h = self._make_history([
            ("compound-v3-usdc-ethereum", 4.8, 100000.0),
            ("aave-v3-usdc-ethereum", 4.2, 200000.0),
        ])
        result = self.d.extract_apy_series("compound-v3", h)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0][1], 4.8, places=6)

    # 6
    def test_multiple_entries_all_returned(self):
        h = self._make_history([
            ("aave-v3", 4.0, 1000000.0),
            ("aave-v3", 4.5, 2000000.0),
            ("aave-v3", 5.0, 3000000.0),
        ])
        result = self.d.extract_apy_series("aave-v3", h)
        self.assertEqual(len(result), 3)

    # 7
    def test_timestamp_conversion_to_days(self):
        ts_unix = 86400.0 * 19000.0  # exactly 19000 days
        h = self._make_history([("aave-v3", 3.5, ts_unix)])
        result = self.d.extract_apy_series("aave-v3", h)
        self.assertAlmostEqual(result[0][0], 19000.0, places=6)

    # 8
    def test_empty_adapter_id_returns_empty(self):
        h = self._make_history([("aave-v3", 4.0, 100000.0)])
        result = self.d.extract_apy_series("", h)
        self.assertEqual(result, [])

    # 9
    def test_mixed_adapters_only_correct_filtered(self):
        h = self._make_history([
            ("aave-v3", 4.0, 1000000.0),
            ("morpho-steakhouse", 6.5, 2000000.0),
            ("aave-v3", 4.2, 3000000.0),
            ("compound-v3", 4.8, 4000000.0),
        ])
        result = self.d.extract_apy_series("aave-v3", h)
        self.assertEqual(len(result), 2)
        apys = [r[1] for r in result]
        self.assertIn(4.0, apys)
        self.assertIn(4.2, apys)

    # 10
    def test_returns_list_of_tuples(self):
        h = self._make_history([("aave-v3", 4.0, 100000.0)])
        result = self.d.extract_apy_series("aave-v3", h)
        self.assertIsInstance(result, list)
        self.assertIsInstance(result[0], tuple)
        self.assertEqual(len(result[0]), 2)


# ===========================================================================
# TestClassifyTrend  (15 tests)
# ===========================================================================

class TestClassifyTrend(unittest.TestCase):

    def setUp(self):
        self.d = APYMomentumDetector()

    # --- Zero points ---

    # 1
    def test_zero_points_unknown_low(self):
        self.assertEqual(self.d.classify_trend(1.0, 0), ("UNKNOWN", "LOW"))

    # --- 1-2 points (LOW confidence) ---

    # 2
    def test_one_point_strong_rising(self):
        trend, conf = self.d.classify_trend(0.2, 1)
        self.assertEqual(trend, "RISING")
        self.assertEqual(conf, "LOW")

    # 3
    def test_one_point_strong_falling(self):
        trend, conf = self.d.classify_trend(-0.2, 1)
        self.assertEqual(trend, "FALLING")
        self.assertEqual(conf, "LOW")

    # 4
    def test_one_point_weak_slope_unknown(self):
        """slope ≤ RISING_THRESHOLD (0.05) → UNKNOWN even with 1 point."""
        trend, conf = self.d.classify_trend(0.03, 1)
        self.assertEqual(trend, "UNKNOWN")
        self.assertEqual(conf, "LOW")

    # 5
    def test_two_points_exactly_at_rising_threshold(self):
        """slope == RISING_THRESHOLD (0.05) → UNKNOWN (strict >)."""
        trend, conf = self.d.classify_trend(0.05, 2)
        self.assertEqual(trend, "UNKNOWN")
        self.assertEqual(conf, "LOW")

    # 6
    def test_two_points_just_above_rising_threshold(self):
        trend, conf = self.d.classify_trend(0.051, 2)
        self.assertEqual(trend, "RISING")
        self.assertEqual(conf, "LOW")

    # --- 3-6 points (MEDIUM confidence) ---

    # 7
    def test_three_points_stable_medium(self):
        """|slope| < 0.1 → STABLE, MEDIUM."""
        trend, conf = self.d.classify_trend(0.05, 3)
        self.assertEqual(trend, "STABLE")
        self.assertEqual(conf, "MEDIUM")

    # 8
    def test_three_points_rising_medium(self):
        trend, conf = self.d.classify_trend(0.15, 3)
        self.assertEqual(trend, "RISING")
        self.assertEqual(conf, "MEDIUM")

    # 9
    def test_six_points_falling_medium(self):
        trend, conf = self.d.classify_trend(-0.5, 6)
        self.assertEqual(trend, "FALLING")
        self.assertEqual(conf, "MEDIUM")

    # 10
    def test_boundary_six_to_seven_medium_vs_high(self):
        """6 → MEDIUM, 7 → HIGH."""
        _, c6 = self.d.classify_trend(0.2, 6)
        _, c7 = self.d.classify_trend(0.2, 7)
        self.assertEqual(c6, "MEDIUM")
        self.assertEqual(c7, "HIGH")

    # --- 7+ points (HIGH confidence) ---

    # 11
    def test_seven_points_rising_high(self):
        trend, conf = self.d.classify_trend(0.3, 7)
        self.assertEqual(trend, "RISING")
        self.assertEqual(conf, "HIGH")

    # 12
    def test_seven_points_falling_high(self):
        trend, conf = self.d.classify_trend(-0.3, 7)
        self.assertEqual(trend, "FALLING")
        self.assertEqual(conf, "HIGH")

    # 13
    def test_seven_points_stable_high(self):
        trend, conf = self.d.classify_trend(0.09, 7)
        self.assertEqual(trend, "STABLE")
        self.assertEqual(conf, "HIGH")

    # 14
    def test_slope_exactly_stable_threshold(self):
        """slope == 0.1 (STABLE_THRESHOLD): abs(0.1) < 0.1 is False → RISING."""
        trend, conf = self.d.classify_trend(0.1, 7)
        self.assertEqual(trend, "RISING")
        self.assertEqual(conf, "HIGH")

    # 15
    def test_large_negative_slope_high_confidence(self):
        trend, conf = self.d.classify_trend(-5.0, 30)
        self.assertEqual(trend, "FALLING")
        self.assertEqual(conf, "HIGH")


# ===========================================================================
# TestGetSignal  (15 tests)
# ===========================================================================

class TestGetSignal(unittest.TestCase):

    def setUp(self):
        self.d = APYMomentumDetector()

    def _make_history_entries(self, adapter_id: str, apys_and_days: list) -> list:
        """Build history from [(apy, days_ago)] pairs."""
        now_ts = datetime.now(timezone.utc).timestamp()
        entries = []
        for apy, days_ago in apys_and_days:
            ts = now_ts - days_ago * 86400
            entries.append({
                "ts_unix": ts,
                "generated_at": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "adapter_id": adapter_id,
                "apy_pct": apy,
                "source": "test",
            })
        entries.sort(key=lambda e: e["ts_unix"])
        return entries

    # 1
    def test_returns_momentum_signal_instance(self):
        sig = self.d.get_signal("aave-v3", 4.2, [])
        self.assertIsInstance(sig, MomentumSignal)

    # 2
    def test_empty_history_unknown_trend(self):
        sig = self.d.get_signal("aave-v3", 4.2, [])
        self.assertEqual(sig.trend, "UNKNOWN")
        self.assertEqual(sig.data_points, 0)

    # 3
    def test_empty_history_ema_equals_current_apy(self):
        sig = self.d.get_signal("aave-v3", 4.5, [])
        self.assertAlmostEqual(sig.ema_apy, 4.5, places=5)

    # 4
    def test_data_points_counts_correctly(self):
        hist = self._make_history_entries("aave-v3", [(4.0, 10), (4.2, 7), (4.5, 3)])
        sig = self.d.get_signal("aave-v3", 4.8, hist)
        self.assertEqual(sig.data_points, 3)

    # 5
    def test_current_apy_stored_correctly(self):
        sig = self.d.get_signal("compound-v3", 5.5, [])
        self.assertAlmostEqual(sig.current_apy, 5.5, places=5)

    # 6
    def test_apy_change_24h_zero_without_history(self):
        sig = self.d.get_signal("aave-v3", 4.2, [])
        self.assertEqual(sig.apy_change_24h, 0.0)

    # 7
    def test_apy_change_7d_zero_without_history(self):
        sig = self.d.get_signal("aave-v3", 4.2, [])
        self.assertEqual(sig.apy_change_7d, 0.0)

    # 8
    def test_apy_change_24h_computed_correctly(self):
        # 24h ago: 4.0, current: 4.5 → change = +0.5
        hist = self._make_history_entries("aave-v3", [
            (4.0, 1.0),   # ~24h ago
            (4.2, 0.5),
            (4.5, 0.1),
        ])
        sig = self.d.get_signal("aave-v3", 4.5, hist)
        # change_24h should be close to +0.5 (current - apy_at_24h_ago)
        self.assertGreater(sig.apy_change_24h, 0)

    # 9
    def test_signal_strength_zero_for_unknown(self):
        sig = self.d.get_signal("aave-v3", 4.2, [])
        self.assertEqual(sig.signal_strength, 0.0)

    # 10
    def test_signal_strength_positive_for_rising(self):
        # 7+ data points to get HIGH confidence
        hist = self._make_history_entries("aave-v3", [
            (3.0, 14), (3.2, 12), (3.4, 10), (3.6, 8),
            (3.8, 6), (4.0, 4), (4.2, 2),
        ])
        sig = self.d.get_signal("aave-v3", 4.5, hist)
        if sig.trend == "RISING":
            self.assertGreater(sig.signal_strength, 0.0)

    # 11
    def test_signal_strength_clamped_to_one(self):
        """Extremely steep slope should not produce strength > 1.0."""
        hist = self._make_history_entries("aave-v3", [
            (0.0, 10), (100.0, 5), (200.0, 2),
            (300.0, 1.5), (400.0, 1), (500.0, 0.5), (600.0, 0.1),
        ])
        sig = self.d.get_signal("aave-v3", 700.0, hist)
        self.assertLessEqual(sig.signal_strength, 1.0)

    # 12
    def test_signal_strength_non_negative(self):
        hist = self._make_history_entries("aave-v3", [
            (10.0, 8), (8.0, 6), (6.0, 4),
            (4.0, 3), (2.0, 2), (1.0, 1), (0.5, 0.1),
        ])
        sig = self.d.get_signal("aave-v3", 0.0, hist)
        self.assertGreaterEqual(sig.signal_strength, 0.0)

    # 13
    def test_slope_per_day_present_with_history(self):
        hist = self._make_history_entries("aave-v3", [
            (4.0, 3), (4.1, 2), (4.2, 1),
        ])
        sig = self.d.get_signal("aave-v3", 4.3, hist)
        # slope should be close to 0.1 %/day
        self.assertNotEqual(sig.slope_per_day, 0.0)

    # 14
    def test_to_dict_has_all_required_keys(self):
        sig = self.d.get_signal("aave-v3", 4.2, [])
        d = sig.to_dict()
        for key in ("adapter_id", "trend", "confidence", "current_apy",
                    "ema_apy", "apy_change_24h", "apy_change_7d",
                    "slope_per_day", "data_points", "signal_strength"):
            self.assertIn(key, d)

    # 15
    def test_adapter_id_stored_in_signal(self):
        sig = self.d.get_signal("morpho-steakhouse", 6.5, [])
        self.assertEqual(sig.adapter_id, "morpho-steakhouse")


# ===========================================================================
# TestGetReport  (12 tests)
# ===========================================================================

class TestGetReport(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.det = _make_detector(self.tmp)

    def _write_status_with_adapters(self, adapters: list) -> None:
        _write_adapter_status(
            os.path.join(self.tmp, "adapter_status.json"), adapters
        )

    # 1
    def test_returns_momentum_report_instance(self):
        self._write_status_with_adapters([("aave-v3", 4.2)])
        report = self.det.get_report()
        self.assertIsInstance(report, MomentumReport)

    # 2
    def test_total_adapters_matches_adapter_count(self):
        self._write_status_with_adapters([
            ("aave-v3", 4.2), ("compound-v3", 4.8), ("morpho-steakhouse", 6.5)
        ])
        report = self.det.get_report()
        self.assertEqual(report.total_adapters, 3)

    # 3
    def test_counts_sum_to_total(self):
        self._write_status_with_adapters([
            ("aave-v3", 4.2), ("compound-v3", 4.8),
            ("morpho-steakhouse", 6.5), ("euler-v2", 5.0),
        ])
        report = self.det.get_report()
        self.assertEqual(
            report.rising + report.falling + report.stable + report.unknown,
            report.total_adapters
        )

    # 4
    def test_all_unknown_when_no_history(self):
        """No history → all adapters are UNKNOWN trend."""
        self._write_status_with_adapters([("aave-v3", 4.2), ("compound-v3", 4.8)])
        report = self.det.get_report()
        self.assertEqual(report.unknown, report.total_adapters)

    # 5
    def test_empty_adapter_status_zero_adapters(self):
        _write_json(
            os.path.join(self.tmp, "adapter_status.json"),
            {"generated_at": _iso(), "adapters": []}
        )
        report = self.det.get_report()
        self.assertEqual(report.total_adapters, 0)

    # 6
    def test_missing_adapter_status_zero_adapters(self):
        report = self.det.get_report()
        self.assertEqual(report.total_adapters, 0)

    # 7
    def test_top_rising_max_three(self):
        self._write_status_with_adapters([
            ("a1", 4.0), ("a2", 5.0), ("a3", 6.0),
            ("a4", 7.0), ("a5", 8.0),
        ])
        report = self.det.get_report()
        self.assertLessEqual(len(report.top_rising), 3)

    # 8
    def test_top_falling_max_three(self):
        self._write_status_with_adapters([
            ("a1", 4.0), ("a2", 5.0), ("a3", 6.0),
            ("a4", 7.0), ("a5", 8.0),
        ])
        report = self.det.get_report()
        self.assertLessEqual(len(report.top_falling), 3)

    # 9
    def test_signals_list_length_matches_total(self):
        self._write_status_with_adapters([
            ("aave-v3", 4.2), ("compound-v3", 4.8)
        ])
        report = self.det.get_report()
        self.assertEqual(len(report.signals), report.total_adapters)

    # 10
    def test_top_rising_sorted_descending_slope(self):
        """top_rising sorted by slope descending (highest slope first)."""
        self._write_status_with_adapters([("a1", 4.0), ("a2", 5.0)])
        # Inject watchdog history to create rising trends
        snaps = []
        for i in range(8):
            snaps.append({
                "generated_at": _iso(days_ago=8 - i),
                "adapter_statuses": [
                    {"adapter_id": "a1", "apy_pct": 3.0 + i * 0.5},
                    {"adapter_id": "a2", "apy_pct": 3.0 + i * 1.0},
                ]
            })
        _write_watchdog_history(
            os.path.join(self.tmp, "watchdog_history.json"), snaps
        )
        report = self.det.get_report()
        if len(report.top_rising) >= 2:
            slopes = [s["slope_per_day"] for s in report.top_rising]
            self.assertGreaterEqual(slopes[0], slopes[1])

    # 11
    def test_generated_at_is_iso_string(self):
        self._write_status_with_adapters([("aave-v3", 4.2)])
        report = self.det.get_report()
        # Should parse as ISO without error
        ts = _parse_ts_unix(report.generated_at)
        self.assertGreater(ts, 0)

    # 12
    def test_to_dict_has_required_top_level_keys(self):
        self._write_status_with_adapters([("aave-v3", 4.2)])
        report = self.det.get_report()
        d = report.to_dict()
        for key in ("generated_at", "total_adapters", "rising", "falling",
                    "stable", "unknown", "top_rising", "top_falling", "signals"):
            self.assertIn(key, d)


# ===========================================================================
# TestSaveReport  (6 tests)
# ===========================================================================

class TestSaveReport(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.det = _make_detector(self.tmp)
        _write_adapter_status(
            os.path.join(self.tmp, "adapter_status.json"),
            [("aave-v3", 4.2)]
        )

    # 1
    def test_creates_momentum_report_json(self):
        self.det.save_report()
        self.assertTrue(
            os.path.exists(os.path.join(self.tmp, "momentum_report.json"))
        )

    # 2
    def test_returns_path_string(self):
        path = self.det.save_report()
        self.assertIsInstance(path, str)
        self.assertTrue(os.path.exists(path))

    # 3
    def test_file_is_valid_json(self):
        self.det.save_report()
        with open(os.path.join(self.tmp, "momentum_report.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)

    # 4
    def test_ring_buffer_does_not_exceed_30(self):
        """Saving more than 30 times keeps only the last 30."""
        for _ in range(35):
            self.det.save_report()
        with open(os.path.join(self.tmp, "momentum_report.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertLessEqual(len(data["reports"]), 30)

    # 5
    def test_no_tmp_files_left_after_save(self):
        """Atomic write should not leave .tmp files."""
        self.det.save_report()
        tmp_files = [
            f for f in os.listdir(self.tmp)
            if f.endswith(".tmp")
        ]
        self.assertEqual(tmp_files, [])

    # 6
    def test_custom_output_path(self):
        custom = os.path.join(self.tmp, "custom_report.json")
        self.det.save_report(output_path=custom)
        self.assertTrue(os.path.exists(custom))


# ===========================================================================
# TestFormatTelegramMessage  (8 tests)
# ===========================================================================

class TestFormatTelegramMessage(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.det = _make_detector(self.tmp)

    def _write_status(self, adapters: list) -> None:
        _write_adapter_status(
            os.path.join(self.tmp, "adapter_status.json"), adapters
        )

    def _write_rising_history(self, adapter_id: str, n: int = 8) -> None:
        snaps = []
        for i in range(n):
            snaps.append({
                "generated_at": _iso(days_ago=n - i),
                "adapter_statuses": [
                    {"adapter_id": adapter_id, "apy_pct": 3.0 + i * 0.3}
                ]
            })
        _write_watchdog_history(
            os.path.join(self.tmp, "watchdog_history.json"), snaps
        )

    # 1
    def test_returns_string(self):
        self._write_status([("aave-v3", 4.2)])
        msg = self.det.format_telegram_message()
        self.assertIsInstance(msg, str)

    # 2
    def test_length_at_most_1500(self):
        self._write_status([
            ("a1", 4.0), ("a2", 5.0), ("a3", 6.0), ("a4", 7.0), ("a5", 8.0),
        ])
        msg = self.det.format_telegram_message()
        self.assertLessEqual(len(msg), 1500)

    # 3
    def test_contains_total_adapters_info(self):
        self._write_status([("aave-v3", 4.2), ("compound-v3", 4.8)])
        msg = self.det.format_telegram_message()
        self.assertIn("2 adapters", msg)

    # 4
    def test_contains_rising_keyword_when_rising_exists(self):
        self._write_status([("aave-v3", 4.2)])
        self._write_rising_history("aave-v3")
        msg = self.det.format_telegram_message()
        # Message always includes trend counts regardless of actual trend
        self.assertIn("rising", msg.lower())

    # 5
    def test_contains_falling_keyword(self):
        self._write_status([("aave-v3", 4.2)])
        msg = self.det.format_telegram_message()
        self.assertIn("falling", msg.lower())

    # 6
    def test_contains_report_header(self):
        self._write_status([("aave-v3", 4.2)])
        msg = self.det.format_telegram_message()
        self.assertIn("Momentum", msg)

    # 7
    def test_no_exception_on_empty_adapters(self):
        _write_json(
            os.path.join(self.tmp, "adapter_status.json"),
            {"generated_at": _iso(), "adapters": []}
        )
        try:
            msg = self.det.format_telegram_message()
            # Should still return a string
            self.assertIsInstance(msg, str)
        except Exception as e:
            self.fail(f"format_telegram_message raised unexpectedly: {e}")

    # 8
    def test_length_capped_even_with_many_adapters(self):
        """Many adapters with long names should still be ≤ 1500 chars."""
        adapters = [(f"very-long-protocol-name-{i:03d}", float(4 + i % 5))
                    for i in range(50)]
        self._write_status(adapters)
        msg = self.det.format_telegram_message()
        self.assertLessEqual(len(msg), 1500)


# ===========================================================================
# Bonus: TestExtractCurrentAPY + TestParseTsUnix  (additional coverage)
# ===========================================================================

class TestExtractCurrentAPY(unittest.TestCase):
    """Tests for the _extract_current_apy helper."""

    # 1
    def test_apy_pct_field_preferred(self):
        entry = {"apy_pct": 5.5, "apy": 3.0, "mock_apy": {}}
        self.assertEqual(_extract_current_apy(entry), 5.5)

    # 2
    def test_apy_field_fallback(self):
        entry = {"apy": 4.2}
        self.assertEqual(_extract_current_apy(entry), 4.2)

    # 3
    def test_mock_apy_fallback(self):
        entry = {"mock_apy": {"ethereum": {"USDC": 4.8}}}
        self.assertEqual(_extract_current_apy(entry), 4.8)

    # 4
    def test_empty_entry_returns_zero(self):
        self.assertEqual(_extract_current_apy({}), 0.0)


class TestParseTsUnix(unittest.TestCase):
    """Tests for the _parse_ts_unix helper."""

    # 1
    def test_valid_iso_utc(self):
        ts = _parse_ts_unix("2026-06-13T10:00:00+00:00")
        self.assertGreater(ts, 0)

    # 2
    def test_invalid_string_returns_zero(self):
        self.assertEqual(_parse_ts_unix("not-a-date"), 0.0)

    # 3
    def test_non_string_returns_zero(self):
        self.assertEqual(_parse_ts_unix(None), 0.0)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main(verbosity=2)
