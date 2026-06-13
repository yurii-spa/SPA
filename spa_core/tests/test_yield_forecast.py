"""
Unit tests for spa_core.analytics.yield_forecast (MP-615).

Coverage targets
----------------
TestAdapterForecast       (8)  — dataclass fields, advisory_note always present
TestPortfolioForecast     (8)  — disclaimer, portfolio_trend, low_data_warning
TestOlsSlope             (20)  — edge cases, ideal series, degenerate inputs
TestClamp                 (6)  — boundary and in-range values
TestClassifyTrend         (6)  — RISING / FALLING / STABLE, boundary ±0.01
TestClassifyConfidence    (6)  — HIGH / MEDIUM / LOW thresholds
TestForecastAdapter      (15)  — clamp applied, slope=0, rising trend, etc.
TestGenerateForecast     (15)  — empty data, multiple adapters, majority trend
TestSaveForecast          (4)  — atomic write, ring-buffer ≤ 48
TestFormatTelegramMessage (8)  — ≤ 1500 chars, required strings

Total: 96 tests
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from spa_core.analytics.yield_forecast import (
    AdapterForecast,
    PortfolioForecast,
    YieldForecastEngine,
    _ADVISORY_NOTE,
    _DISCLAIMER,
    _RING_BUFFER_MAX,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(data_dir: str = None) -> YieldForecastEngine:
    """Create engine pointing at a given data directory (or a temp dir)."""
    if data_dir is None:
        data_dir = tempfile.mkdtemp()
    return YieldForecastEngine(data_path=data_dir)


def _make_adapter_forecast(**kwargs) -> AdapterForecast:
    defaults = dict(
        adapter_key="test_adapter",
        current_apy_pct=5.0,
        data_points=10,
        slope_pct_per_day=0.05,
        forecast_1d=5.05,
        forecast_7d=5.35,
        forecast_30d=6.5,
        trend="RISING",
        confidence="HIGH",
        advisory_note=_ADVISORY_NOTE,
    )
    defaults.update(kwargs)
    return AdapterForecast(**defaults)


def _make_portfolio_forecast(**kwargs) -> PortfolioForecast:
    from datetime import datetime, timezone
    defaults = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        adapters=[],
        portfolio_current_apy=5.0,
        portfolio_forecast_1d=5.1,
        portfolio_forecast_7d=5.5,
        portfolio_forecast_30d=6.5,
        portfolio_trend="RISING",
        high_confidence_count=2,
        low_data_warning=False,
        disclaimer=_DISCLAIMER,
    )
    defaults.update(kwargs)
    return PortfolioForecast(**defaults)


def _write_watchdog_history(data_dir: str, snapshots: list) -> None:
    """Write a minimal watchdog_history.json with the given snapshots."""
    path = Path(data_dir) / "watchdog_history.json"
    payload = {
        "schema_version": 1,
        "source": "adapter_watchdog",
        "ring_buffer_max": 48,
        "snapshot_count": len(snapshots),
        "updated_at": "2026-06-13T08:00:00+00:00",
        "latest": snapshots[-1] if snapshots else {},
        "snapshots": snapshots,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _make_snapshot(adapters_apy: dict) -> dict:
    """
    Build a minimal WatchdogReport snapshot dict.
    adapters_apy: {adapter_key: apy_pct}
    """
    return {
        "generated_at": "2026-06-13T08:00:00+00:00",
        "adapter_statuses": [
            {"adapter_key": k, "apy_pct": v}
            for k, v in adapters_apy.items()
        ],
    }


# ===========================================================================
# 1. TestAdapterForecast (8 tests)
# ===========================================================================

class TestAdapterForecast(unittest.TestCase):
    """Verify AdapterForecast dataclass structure and field invariants."""

    def test_adapter_key_stored(self):
        af = _make_adapter_forecast(adapter_key="aave_v3")
        self.assertEqual(af.adapter_key, "aave_v3")

    def test_current_apy_stored(self):
        af = _make_adapter_forecast(current_apy_pct=7.5)
        self.assertEqual(af.current_apy_pct, 7.5)

    def test_data_points_stored(self):
        af = _make_adapter_forecast(data_points=12)
        self.assertEqual(af.data_points, 12)

    def test_slope_stored(self):
        af = _make_adapter_forecast(slope_pct_per_day=0.123)
        self.assertAlmostEqual(af.slope_pct_per_day, 0.123)

    def test_forecasts_stored(self):
        af = _make_adapter_forecast(forecast_1d=5.1, forecast_7d=5.7, forecast_30d=7.0)
        self.assertAlmostEqual(af.forecast_1d, 5.1)
        self.assertAlmostEqual(af.forecast_7d, 5.7)
        self.assertAlmostEqual(af.forecast_30d, 7.0)

    def test_advisory_note_always_present(self):
        af = _make_adapter_forecast()
        self.assertIsNotNone(af.advisory_note)
        self.assertTrue(len(af.advisory_note) > 0)

    def test_advisory_note_default_value(self):
        af = _make_adapter_forecast()
        self.assertEqual(af.advisory_note, _ADVISORY_NOTE)

    def test_trend_and_confidence_fields(self):
        af = _make_adapter_forecast(trend="FALLING", confidence="MEDIUM")
        self.assertEqual(af.trend, "FALLING")
        self.assertEqual(af.confidence, "MEDIUM")


# ===========================================================================
# 2. TestPortfolioForecast (8 tests)
# ===========================================================================

class TestPortfolioForecast(unittest.TestCase):
    """Verify PortfolioForecast dataclass structure and invariants."""

    def test_disclaimer_always_present(self):
        pf = _make_portfolio_forecast()
        self.assertIsNotNone(pf.disclaimer)
        self.assertTrue(len(pf.disclaimer) > 0)

    def test_disclaimer_default_value(self):
        pf = _make_portfolio_forecast()
        self.assertIn("ADVISORY ONLY", pf.disclaimer)

    def test_portfolio_trend_stored(self):
        pf = _make_portfolio_forecast(portfolio_trend="FALLING")
        self.assertEqual(pf.portfolio_trend, "FALLING")

    def test_low_data_warning_false_by_default_kwarg(self):
        pf = _make_portfolio_forecast(low_data_warning=False)
        self.assertFalse(pf.low_data_warning)

    def test_low_data_warning_can_be_true(self):
        pf = _make_portfolio_forecast(low_data_warning=True)
        self.assertTrue(pf.low_data_warning)

    def test_high_confidence_count_stored(self):
        pf = _make_portfolio_forecast(high_confidence_count=5)
        self.assertEqual(pf.high_confidence_count, 5)

    def test_adapters_list_default_empty(self):
        from datetime import datetime, timezone
        pf = PortfolioForecast(generated_at=datetime.now(timezone.utc).isoformat())
        self.assertEqual(pf.adapters, [])

    def test_portfolio_current_apy_stored(self):
        pf = _make_portfolio_forecast(portfolio_current_apy=8.25)
        self.assertAlmostEqual(pf.portfolio_current_apy, 8.25)


# ===========================================================================
# 3. TestOlsSlope (20 tests)
# ===========================================================================

class TestOlsSlope(unittest.TestCase):
    """Test YieldForecastEngine.ols_slope."""

    def setUp(self):
        self.engine = _make_engine()

    def test_empty_list_returns_zero(self):
        self.assertEqual(self.engine.ols_slope([]), 0.0)

    def test_single_element_returns_zero(self):
        self.assertEqual(self.engine.ols_slope([5.0]), 0.0)

    def test_ideal_rising_two_points(self):
        # y = 0, 1 → slope = 1.0
        result = self.engine.ols_slope([0.0, 1.0])
        self.assertAlmostEqual(result, 1.0)

    def test_ideal_falling_two_points(self):
        # y = 1, 0 → slope = -1.0
        result = self.engine.ols_slope([1.0, 0.0])
        self.assertAlmostEqual(result, -1.0)

    def test_flat_series_slope_zero(self):
        result = self.engine.ols_slope([5.0, 5.0, 5.0, 5.0, 5.0])
        self.assertAlmostEqual(result, 0.0, places=10)

    def test_perfect_linear_rise(self):
        # y = [0, 1, 2, 3, 4] → slope = 1.0
        result = self.engine.ols_slope([0.0, 1.0, 2.0, 3.0, 4.0])
        self.assertAlmostEqual(result, 1.0, places=10)

    def test_perfect_linear_fall(self):
        # y = [4, 3, 2, 1, 0] → slope = -1.0
        result = self.engine.ols_slope([4.0, 3.0, 2.0, 1.0, 0.0])
        self.assertAlmostEqual(result, -1.0, places=10)

    def test_slope_with_step_2(self):
        # y = [0, 2, 4, 6] → slope = 2.0
        result = self.engine.ols_slope([0.0, 2.0, 4.0, 6.0])
        self.assertAlmostEqual(result, 2.0, places=10)

    def test_slope_positive_sign(self):
        result = self.engine.ols_slope([3.0, 3.5, 4.0, 4.5])
        self.assertGreater(result, 0.0)

    def test_slope_negative_sign(self):
        result = self.engine.ols_slope([4.5, 4.0, 3.5, 3.0])
        self.assertLess(result, 0.0)

    def test_slope_large_series(self):
        # y = [i * 0.1 for i in range(30)] → slope = 0.1
        values = [i * 0.1 for i in range(30)]
        result = self.engine.ols_slope(values)
        self.assertAlmostEqual(result, 0.1, places=6)

    def test_two_identical_points_returns_zero(self):
        # denominator = 2*0.5*0.5 - 1*1 = 0 when all x^2 identical? No:
        # n=2, sum_x=0+1=1, sum_x2=0+1=1, denom=2*1-1*1=1 ≠ 0
        # but if y1==y2: slope=0
        result = self.engine.ols_slope([5.0, 5.0])
        self.assertAlmostEqual(result, 0.0)

    def test_denominator_zero_returns_zero(self):
        # Force denom=0 by mocking: can't happen naturally with integer x-indices
        # But we can test with n<2 to confirm 0.0
        self.assertEqual(self.engine.ols_slope([42.0]), 0.0)

    def test_fractional_slope(self):
        # y = [0, 0.5, 1.0] → slope = 0.5
        result = self.engine.ols_slope([0.0, 0.5, 1.0])
        self.assertAlmostEqual(result, 0.5, places=10)

    def test_negative_values_allowed(self):
        # y = [-1, 0, 1] → slope = 1.0
        result = self.engine.ols_slope([-1.0, 0.0, 1.0])
        self.assertAlmostEqual(result, 1.0, places=10)

    def test_slope_near_zero_for_noisy_flat(self):
        # Small perturbations around 5.0 — slope should be tiny
        values = [5.0, 5.01, 4.99, 5.02, 4.98, 5.01, 4.99]
        result = self.engine.ols_slope(values)
        self.assertLess(abs(result), 0.02)

    def test_return_type_is_float(self):
        result = self.engine.ols_slope([1.0, 2.0, 3.0])
        self.assertIsInstance(result, float)

    def test_n_equals_2_nontrivial(self):
        # y = [3.0, 7.0], x=[0,1] → slope = (3)/(1) = 4.0
        result = self.engine.ols_slope([3.0, 7.0])
        self.assertAlmostEqual(result, 4.0)

    def test_slope_symmetric_antisymmetry(self):
        # slope([a,b,c]) == -slope([c,b,a]) only for symmetric x
        vals = [1.0, 3.0, 5.0]
        s1 = self.engine.ols_slope(vals)
        s2 = self.engine.ols_slope(list(reversed(vals)))
        self.assertAlmostEqual(s1, -s2, places=10)

    def test_longer_series_dominates_outlier(self):
        # 9 stable points + 1 jump at the end
        values = [5.0] * 9 + [5.1]
        result = self.engine.ols_slope(values)
        # slope should be small positive
        self.assertGreater(result, 0)
        self.assertLess(result, 0.1)


# ===========================================================================
# 4. TestClamp (6 tests)
# ===========================================================================

class TestClamp(unittest.TestCase):
    """Test YieldForecastEngine.clamp."""

    def setUp(self):
        self.engine = _make_engine()

    def test_above_max_clamped_to_max(self):
        self.assertAlmostEqual(self.engine.clamp(30.0), 25.0)

    def test_well_above_max_clamped_to_max(self):
        self.assertAlmostEqual(self.engine.clamp(100.0), 25.0)

    def test_below_min_clamped_to_min(self):
        self.assertAlmostEqual(self.engine.clamp(-5.0), 0.0)

    def test_at_min_boundary(self):
        self.assertAlmostEqual(self.engine.clamp(0.0), 0.0)

    def test_at_max_boundary(self):
        self.assertAlmostEqual(self.engine.clamp(25.0), 25.0)

    def test_in_range_unchanged(self):
        self.assertAlmostEqual(self.engine.clamp(10.0), 10.0)


# ===========================================================================
# 5. TestClassifyTrend (6 tests)
# ===========================================================================

class TestClassifyTrend(unittest.TestCase):
    """Test YieldForecastEngine.classify_trend."""

    def setUp(self):
        self.engine = _make_engine()

    def test_large_positive_slope_rising(self):
        self.assertEqual(self.engine.classify_trend(0.5), "RISING")

    def test_large_negative_slope_falling(self):
        self.assertEqual(self.engine.classify_trend(-0.5), "FALLING")

    def test_zero_slope_stable(self):
        self.assertEqual(self.engine.classify_trend(0.0), "STABLE")

    def test_just_below_threshold_stable_positive(self):
        self.assertEqual(self.engine.classify_trend(0.009), "STABLE")

    def test_just_below_threshold_stable_negative(self):
        self.assertEqual(self.engine.classify_trend(-0.009), "STABLE")

    def test_exactly_at_threshold_rising(self):
        # |slope| == 0.01 is NOT < 0.01, so it should be RISING
        self.assertEqual(self.engine.classify_trend(0.01), "RISING")


# ===========================================================================
# 6. TestClassifyConfidence (6 tests)
# ===========================================================================

class TestClassifyConfidence(unittest.TestCase):
    """Test YieldForecastEngine.classify_confidence."""

    def setUp(self):
        self.engine = _make_engine()

    def test_ten_points_high(self):
        self.assertEqual(self.engine.classify_confidence(10), "HIGH")

    def test_twenty_points_high(self):
        self.assertEqual(self.engine.classify_confidence(20), "HIGH")

    def test_five_points_medium(self):
        self.assertEqual(self.engine.classify_confidence(5), "MEDIUM")

    def test_nine_points_medium(self):
        self.assertEqual(self.engine.classify_confidence(9), "MEDIUM")

    def test_four_points_low(self):
        self.assertEqual(self.engine.classify_confidence(4), "LOW")

    def test_zero_points_low(self):
        self.assertEqual(self.engine.classify_confidence(0), "LOW")


# ===========================================================================
# 7. TestForecastAdapter (15 tests)
# ===========================================================================

class TestForecastAdapter(unittest.TestCase):
    """Test YieldForecastEngine.forecast_adapter."""

    def setUp(self):
        self.engine = _make_engine()

    def test_returns_adapter_forecast_instance(self):
        af = self.engine.forecast_adapter("aave", [5.0, 5.1, 5.2])
        self.assertIsInstance(af, AdapterForecast)

    def test_adapter_key_preserved(self):
        af = self.engine.forecast_adapter("morpho_blue", [5.0])
        self.assertEqual(af.adapter_key, "morpho_blue")

    def test_data_points_count(self):
        af = self.engine.forecast_adapter("x", [1.0, 2.0, 3.0])
        self.assertEqual(af.data_points, 3)

    def test_current_apy_is_last_value(self):
        af = self.engine.forecast_adapter("x", [1.0, 2.0, 7.5])
        self.assertAlmostEqual(af.current_apy_pct, 7.5, places=4)

    def test_zero_slope_all_forecasts_equal_current(self):
        af = self.engine.forecast_adapter("x", [5.0, 5.0, 5.0, 5.0, 5.0])
        self.assertAlmostEqual(af.forecast_1d, 5.0, places=4)
        self.assertAlmostEqual(af.forecast_7d, 5.0, places=4)
        self.assertAlmostEqual(af.forecast_30d, 5.0, places=4)

    def test_rising_trend_forecasts_increase(self):
        # Perfect rising series
        af = self.engine.forecast_adapter("x", [1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertGreater(af.forecast_7d, af.current_apy_pct)
        self.assertGreater(af.forecast_30d, af.forecast_7d)

    def test_clamp_applied_high_apy(self):
        # Current 24.9, slope=0.5 → 30d would be 24.9+15=39.9 > 25.0
        af = self.engine.forecast_adapter("x", [24.4, 24.6, 24.8, 24.9])
        self.assertLessEqual(af.forecast_30d, 25.0)

    def test_clamp_applied_negative_forecast(self):
        # Falling fast: current=0.1, big negative slope
        af = self.engine.forecast_adapter("x", [5.0, 4.0, 3.0, 2.0, 1.0, 0.1])
        self.assertGreaterEqual(af.forecast_30d, 0.0)

    def test_advisory_note_always_present(self):
        af = self.engine.forecast_adapter("x", [5.0, 5.0])
        self.assertEqual(af.advisory_note, _ADVISORY_NOTE)

    def test_confidence_high_for_10_points(self):
        af = self.engine.forecast_adapter("x", [5.0] * 10)
        self.assertEqual(af.confidence, "HIGH")

    def test_confidence_medium_for_7_points(self):
        af = self.engine.forecast_adapter("x", [5.0] * 7)
        self.assertEqual(af.confidence, "MEDIUM")

    def test_confidence_low_for_3_points(self):
        af = self.engine.forecast_adapter("x", [5.0] * 3)
        self.assertEqual(af.confidence, "LOW")

    def test_trend_rising_for_positive_slope(self):
        af = self.engine.forecast_adapter("x", [1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(af.trend, "RISING")

    def test_trend_falling_for_negative_slope(self):
        af = self.engine.forecast_adapter("x", [5.0, 4.0, 3.0, 2.0, 1.0])
        self.assertEqual(af.trend, "FALLING")

    def test_single_point_zero_slope_stable(self):
        af = self.engine.forecast_adapter("x", [5.0])
        self.assertAlmostEqual(af.slope_pct_per_day, 0.0)
        self.assertEqual(af.trend, "STABLE")


# ===========================================================================
# 8. TestGenerateForecast (15 tests)
# ===========================================================================

class TestGenerateForecast(unittest.TestCase):
    """Test YieldForecastEngine.generate_forecast."""

    def _engine_with_history(self, snapshots: list) -> YieldForecastEngine:
        data_dir = tempfile.mkdtemp()
        _write_watchdog_history(data_dir, snapshots)
        return _make_engine(data_dir)

    def test_empty_history_returns_portfolio_forecast(self):
        engine = _make_engine()  # no watchdog_history.json
        pf = engine.generate_forecast()
        self.assertIsInstance(pf, PortfolioForecast)

    def test_empty_history_empty_adapters(self):
        engine = _make_engine()
        pf = engine.generate_forecast()
        self.assertEqual(pf.adapters, [])

    def test_empty_history_low_data_warning_true(self):
        engine = _make_engine()
        pf = engine.generate_forecast()
        self.assertTrue(pf.low_data_warning)

    def test_empty_history_portfolio_apy_zero(self):
        engine = _make_engine()
        pf = engine.generate_forecast()
        self.assertAlmostEqual(pf.portfolio_current_apy, 0.0)

    def test_single_adapter_single_snapshot(self):
        snaps = [_make_snapshot({"aave_v3": 5.0})]
        engine = self._engine_with_history(snaps)
        pf = engine.generate_forecast()
        self.assertEqual(len(pf.adapters), 1)
        self.assertEqual(pf.adapters[0].adapter_key, "aave_v3")

    def test_portfolio_apy_equals_adapter_apy_single(self):
        snaps = [_make_snapshot({"aave_v3": 6.5})]
        engine = self._engine_with_history(snaps)
        pf = engine.generate_forecast()
        self.assertAlmostEqual(pf.portfolio_current_apy, 6.5, places=4)

    def test_multiple_adapters_portfolio_is_average(self):
        snaps = [_make_snapshot({"a": 4.0, "b": 6.0})]
        engine = self._engine_with_history(snaps)
        pf = engine.generate_forecast()
        self.assertAlmostEqual(pf.portfolio_current_apy, 5.0, places=4)

    def test_adapters_sorted_by_key(self):
        snaps = [_make_snapshot({"z_adapter": 3.0, "a_adapter": 5.0, "m_adapter": 4.0})]
        engine = self._engine_with_history(snaps)
        pf = engine.generate_forecast()
        keys = [a.adapter_key for a in pf.adapters]
        self.assertEqual(keys, sorted(keys))

    def test_majority_vote_trend_rising(self):
        # 3 adapters all with rising slope → RISING
        snaps = []
        for i in range(5):
            snaps.append(_make_snapshot({
                "a": 1.0 + i * 0.1,
                "b": 2.0 + i * 0.2,
                "c": 3.0 + i * 0.3,
            }))
        engine = self._engine_with_history(snaps)
        pf = engine.generate_forecast()
        self.assertEqual(pf.portfolio_trend, "RISING")

    def test_majority_vote_trend_falling(self):
        # 2 falling, 1 rising → FALLING
        snaps = []
        for i in range(5):
            snaps.append(_make_snapshot({
                "a": 5.0 - i * 0.2,
                "b": 4.0 - i * 0.1,
                "c": 1.0 + i * 0.1,
            }))
        engine = self._engine_with_history(snaps)
        pf = engine.generate_forecast()
        self.assertEqual(pf.portfolio_trend, "FALLING")

    def test_high_confidence_count_correct(self):
        # 2 adapters with 10 points each → high_confidence_count=2
        snaps = []
        for i in range(10):
            snaps.append(_make_snapshot({"a": 5.0, "b": 4.0}))
        engine = self._engine_with_history(snaps)
        pf = engine.generate_forecast()
        self.assertEqual(pf.high_confidence_count, 2)

    def test_low_data_warning_false_when_enough_data(self):
        snaps = []
        for i in range(5):
            snaps.append(_make_snapshot({"aave": 5.0}))
        engine = self._engine_with_history(snaps)
        pf = engine.generate_forecast()
        self.assertFalse(pf.low_data_warning)

    def test_disclaimer_always_present(self):
        engine = _make_engine()
        pf = engine.generate_forecast()
        self.assertEqual(pf.disclaimer, _DISCLAIMER)

    def test_generated_at_is_iso_string(self):
        engine = _make_engine()
        pf = engine.generate_forecast()
        # Should parse without error
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(pf.generated_at.replace("Z", "+00:00"))
        except ValueError:
            self.fail("generated_at is not a valid ISO timestamp")

    def test_missing_watchdog_file_graceful(self):
        data_dir = tempfile.mkdtemp()
        engine = _make_engine(data_dir)
        # No watchdog_history.json — should not raise
        try:
            pf = engine.generate_forecast()
        except Exception as exc:
            self.fail(f"generate_forecast raised unexpectedly: {exc}")


# ===========================================================================
# 9. TestSaveForecast (4 tests)
# ===========================================================================

class TestSaveForecast(unittest.TestCase):
    """Test YieldForecastEngine.save_forecast."""

    def _fresh_engine(self):
        data_dir = tempfile.mkdtemp()
        return _make_engine(data_dir), data_dir

    def test_save_creates_file(self):
        engine, data_dir = self._fresh_engine()
        path = engine.save_forecast()
        self.assertTrue(Path(path).exists())

    def test_saved_file_is_valid_json(self):
        engine, data_dir = self._fresh_engine()
        path = engine.save_forecast()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)

    def test_ring_buffer_does_not_exceed_48(self):
        engine, data_dir = self._fresh_engine()
        # Save 50 times
        for _ in range(50):
            engine._cached_forecast = None
            engine.save_forecast()
        with open(engine._output_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertLessEqual(len(data["history"]), _RING_BUFFER_MAX)

    def test_atomic_write_no_partial_file(self):
        """Verify tmp file is cleaned up after write (no .tmp files remain)."""
        engine, data_dir = self._fresh_engine()
        engine.save_forecast()
        tmp_files = list(Path(data_dir).glob("*.tmp"))
        self.assertEqual(len(tmp_files), 0)


# ===========================================================================
# 10. TestFormatTelegramMessage (8 tests)
# ===========================================================================

class TestFormatTelegramMessage(unittest.TestCase):
    """Test YieldForecastEngine.format_telegram_message."""

    def setUp(self):
        self.engine = _make_engine()

    def _forecast_with_adapters(self) -> PortfolioForecast:
        from datetime import datetime, timezone
        adapters = [
            _make_adapter_forecast(
                adapter_key="aave_v3",
                current_apy_pct=5.0,
                slope_pct_per_day=0.05,
                forecast_1d=5.05,
                forecast_7d=5.35,
                forecast_30d=6.5,
                trend="RISING",
                confidence="HIGH",
            ),
            _make_adapter_forecast(
                adapter_key="compound_v3",
                current_apy_pct=4.8,
                slope_pct_per_day=-0.02,
                forecast_1d=4.78,
                forecast_7d=4.66,
                forecast_30d=4.2,
                trend="FALLING",
                confidence="MEDIUM",
            ),
        ]
        return _make_portfolio_forecast(
            adapters=adapters,
            portfolio_current_apy=4.9,
            portfolio_forecast_1d=4.915,
            portfolio_forecast_7d=5.005,
            portfolio_forecast_30d=5.35,
            portfolio_trend="RISING",
            high_confidence_count=1,
            low_data_warning=False,
        )

    def test_returns_string(self):
        msg = self.engine.format_telegram_message(_make_portfolio_forecast())
        self.assertIsInstance(msg, str)

    def test_length_at_most_1500_chars(self):
        forecast = self._forecast_with_adapters()
        msg = self.engine.format_telegram_message(forecast)
        self.assertLessEqual(len(msg), 1500)

    def test_length_at_most_1500_chars_empty(self):
        msg = self.engine.format_telegram_message(_make_portfolio_forecast(adapters=[]))
        self.assertLessEqual(len(msg), 1500)

    def test_contains_advisory(self):
        msg = self.engine.format_telegram_message(self._forecast_with_adapters())
        self.assertIn("Advisory", msg)

    def test_contains_not_financial_advice(self):
        msg = self.engine.format_telegram_message(self._forecast_with_adapters())
        self.assertIn("Not financial advice", msg)

    def test_contains_forecast_header(self):
        msg = self.engine.format_telegram_message(self._forecast_with_adapters())
        self.assertIn("Yield Forecast", msg)

    def test_contains_portfolio_numbers(self):
        forecast = self._forecast_with_adapters()
        msg = self.engine.format_telegram_message(forecast)
        # Portfolio current apy should appear
        self.assertIn("4.90", msg)

    def test_empty_adapters_no_crash(self):
        """Message must be generated even when no adapters are available."""
        pf = _make_portfolio_forecast(adapters=[], low_data_warning=True)
        try:
            msg = self.engine.format_telegram_message(pf)
        except Exception as exc:
            self.fail(f"format_telegram_message raised unexpectedly: {exc}")
        self.assertIsInstance(msg, str)
        self.assertLessEqual(len(msg), 1500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
