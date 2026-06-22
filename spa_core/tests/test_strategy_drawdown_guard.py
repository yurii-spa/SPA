"""
Tests for MP-743: StrategyDrawdownGuard
Pure stdlib unittest only. ≥65 tests.
"""

import os
import tempfile
import unittest

from spa_core.analytics.strategy_drawdown_guard import (
    DrawdownSnapshot,
    alert_level,
    analyze_strategy,
    compute_drawdown,
    compute_max_drawdown,
    compute_recovery_needed,
    guard_portfolio,
    load_history,
    save_results,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _snap(name: str, value: float, ts: str) -> DrawdownSnapshot:
    return DrawdownSnapshot(strategy_name=name, portfolio_value_usd=value, timestamp_iso=ts)


def _snaps(values, name="S"):
    """Create snapshots from a list of values with sequential ISO timestamps."""
    return [
        _snap(name, v, f"2026-06-{str(i+1).zfill(2)}T00:00:00Z")
        for i, v in enumerate(values)
    ]


def _portfolio_data(strategies):
    """
    strategies: list of (name, values, warning, halt)
    """
    result = []
    for name, values, warn, halt in strategies:
        snaps = [
            {"portfolio_value_usd": v, "timestamp_iso": f"2026-06-{str(i+1).zfill(2)}T00:00:00Z"}
            for i, v in enumerate(values)
        ]
        result.append({
            "strategy_name": name,
            "snapshots": snaps,
            "warning_threshold_pct": warn,
            "halt_threshold_pct": halt,
        })
    return result


# ---------------------------------------------------------------------------
# compute_drawdown
# ---------------------------------------------------------------------------

class TestComputeDrawdown(unittest.TestCase):

    def test_basic_formula(self):
        # peak=100, current=80 → 20%
        self.assertAlmostEqual(compute_drawdown(80.0, 100.0), 20.0, places=6)

    def test_peak_zero_returns_zero(self):
        self.assertEqual(compute_drawdown(50.0, 0.0), 0.0)

    def test_no_drawdown_current_equals_peak(self):
        self.assertEqual(compute_drawdown(100.0, 100.0), 0.0)

    def test_no_drawdown_current_above_peak(self):
        # shouldn't happen in practice but must return 0
        self.assertEqual(compute_drawdown(110.0, 100.0), 0.0)

    def test_full_loss(self):
        self.assertAlmostEqual(compute_drawdown(0.0, 100.0), 100.0, places=6)

    def test_partial_drawdown(self):
        self.assertAlmostEqual(compute_drawdown(75.0, 100.0), 25.0, places=6)

    def test_small_drawdown(self):
        self.assertAlmostEqual(compute_drawdown(99.0, 100.0), 1.0, places=6)

    def test_large_values(self):
        self.assertAlmostEqual(
            compute_drawdown(900_000.0, 1_000_000.0), 10.0, places=6
        )


# ---------------------------------------------------------------------------
# compute_recovery_needed
# ---------------------------------------------------------------------------

class TestComputeRecoveryNeeded(unittest.TestCase):

    def test_basic_formula(self):
        # current=80, peak=100 → (100/80 - 1)*100 = 25%
        self.assertAlmostEqual(compute_recovery_needed(80.0, 100.0), 25.0, places=6)

    def test_current_zero_returns_zero(self):
        self.assertEqual(compute_recovery_needed(0.0, 100.0), 0.0)

    def test_no_recovery_needed_at_peak(self):
        self.assertAlmostEqual(compute_recovery_needed(100.0, 100.0), 0.0, places=8)

    def test_no_recovery_when_current_above_peak(self):
        self.assertAlmostEqual(compute_recovery_needed(110.0, 100.0), 0.0, places=8)

    def test_50pct_drawdown_needs_100pct_recovery(self):
        self.assertAlmostEqual(compute_recovery_needed(50.0, 100.0), 100.0, places=6)

    def test_10pct_drawdown(self):
        self.assertAlmostEqual(compute_recovery_needed(90.0, 100.0), 11.111111, places=4)


# ---------------------------------------------------------------------------
# alert_level
# ---------------------------------------------------------------------------

class TestAlertLevel(unittest.TestCase):

    def test_halt_at_or_above_halt_threshold(self):
        self.assertEqual(alert_level(20.0, 10.0, 20.0), "HALT")

    def test_halt_above_halt_threshold(self):
        self.assertEqual(alert_level(35.0, 10.0, 20.0), "HALT")

    def test_warning_at_warning_threshold(self):
        self.assertEqual(alert_level(10.0, 10.0, 20.0), "WARNING")

    def test_warning_between_thresholds(self):
        self.assertEqual(alert_level(15.0, 10.0, 20.0), "WARNING")

    def test_normal_below_warning_threshold(self):
        self.assertEqual(alert_level(5.0, 10.0, 20.0), "NORMAL")

    def test_normal_at_zero(self):
        self.assertEqual(alert_level(0.0, 10.0, 20.0), "NORMAL")

    def test_custom_thresholds(self):
        self.assertEqual(alert_level(8.0, 5.0, 15.0), "WARNING")
        self.assertEqual(alert_level(16.0, 5.0, 15.0), "HALT")
        self.assertEqual(alert_level(3.0, 5.0, 15.0), "NORMAL")


# ---------------------------------------------------------------------------
# compute_max_drawdown
# ---------------------------------------------------------------------------

class TestComputeMaxDrawdown(unittest.TestCase):

    def test_finds_maximum_historical_drawdown(self):
        snaps = _snaps([100, 90, 80, 85, 70], "S")
        # peak=100, min=70 → 30%
        md = compute_max_drawdown(snaps)
        self.assertAlmostEqual(md, 30.0, places=5)

    def test_no_drawdown_monotonic_increase(self):
        snaps = _snaps([100, 110, 120, 130], "S")
        self.assertAlmostEqual(compute_max_drawdown(snaps), 0.0, places=6)

    def test_single_snapshot_returns_zero(self):
        snaps = _snaps([100], "S")
        self.assertEqual(compute_max_drawdown(snaps), 0.0)

    def test_empty_snapshots_returns_zero(self):
        self.assertEqual(compute_max_drawdown([]), 0.0)

    def test_rolling_peak_resets(self):
        # 100 → 90 (dd=10%) then new peak 150 → falls to 120 (dd=20%)
        snaps = _snaps([100, 90, 150, 120], "S")
        md = compute_max_drawdown(snaps)
        self.assertAlmostEqual(md, 20.0, places=5)

    def test_all_equal_returns_zero(self):
        snaps = _snaps([100, 100, 100], "S")
        self.assertAlmostEqual(compute_max_drawdown(snaps), 0.0, places=6)

    def test_two_snapshots_drawdown(self):
        snaps = _snaps([100, 60], "S")
        self.assertAlmostEqual(compute_max_drawdown(snaps), 40.0, places=5)


# ---------------------------------------------------------------------------
# analyze_strategy
# ---------------------------------------------------------------------------

class TestAnalyzeStrategy(unittest.TestCase):

    def test_peak_is_max_value(self):
        state = analyze_strategy("S", _snaps([80, 100, 70, 85]))
        self.assertAlmostEqual(state.peak_value_usd, 100.0, places=5)

    def test_current_is_last_snapshot(self):
        state = analyze_strategy("S", _snaps([80, 100, 70, 85]))
        self.assertAlmostEqual(state.current_value_usd, 85.0, places=5)

    def test_drawdown_pct_formula(self):
        # peak=100, current=75 → 25%
        state = analyze_strategy("S", _snaps([100, 75]))
        self.assertAlmostEqual(state.drawdown_pct, 25.0, places=5)

    def test_drawdown_duration_consecutive_below_peak(self):
        # peak=100, then 90, 80, 85 — all below peak, duration=3
        state = analyze_strategy("S", _snaps([100, 90, 80, 85]))
        self.assertEqual(state.drawdown_duration_periods, 3)

    def test_drawdown_duration_zero_when_at_peak(self):
        state = analyze_strategy("S", _snaps([80, 90, 100]))
        self.assertEqual(state.drawdown_duration_periods, 0)

    def test_max_drawdown_pct_correct(self):
        # 100 → 60 → 80 → 50 → max_dd = 50% (100→50)
        state = analyze_strategy("S", _snaps([100, 60, 80, 50]))
        self.assertAlmostEqual(state.max_drawdown_pct, 50.0, places=4)

    def test_recommendation_halt(self):
        state = analyze_strategy(
            "S", _snaps([100, 75]),
            warning_threshold_pct=10.0,
            halt_threshold_pct=20.0,
        )
        self.assertIn("HALT", state.recommendation)
        self.assertIn("De-risk immediately", state.recommendation)

    def test_recommendation_warning(self):
        state = analyze_strategy(
            "S", _snaps([100, 88]),
            warning_threshold_pct=10.0,
            halt_threshold_pct=20.0,
        )
        self.assertIn("WARNING", state.recommendation)
        self.assertIn("Monitor closely", state.recommendation)

    def test_recommendation_normal(self):
        state = analyze_strategy(
            "S", _snaps([100, 98]),
            warning_threshold_pct=10.0,
            halt_threshold_pct=20.0,
        )
        self.assertIn("normal parameters", state.recommendation)

    def test_alert_level_halt_when_deep_drawdown(self):
        state = analyze_strategy(
            "S", _snaps([100, 70]),
            warning_threshold_pct=10.0,
            halt_threshold_pct=20.0,
        )
        self.assertEqual(state.alert_level, "HALT")

    def test_alert_level_warning(self):
        state = analyze_strategy(
            "S", _snaps([100, 88]),
            warning_threshold_pct=10.0,
            halt_threshold_pct=20.0,
        )
        self.assertEqual(state.alert_level, "WARNING")

    def test_alert_level_normal(self):
        state = analyze_strategy(
            "S", _snaps([100, 99]),
            warning_threshold_pct=10.0,
            halt_threshold_pct=20.0,
        )
        self.assertEqual(state.alert_level, "NORMAL")

    def test_is_in_drawdown_true(self):
        state = analyze_strategy("S", _snaps([100, 90]))
        self.assertTrue(state.is_in_drawdown)

    def test_is_in_drawdown_false_at_peak(self):
        state = analyze_strategy("S", _snaps([80, 90, 100]))
        self.assertFalse(state.is_in_drawdown)

    def test_recovery_needed_pct_correct(self):
        state = analyze_strategy("S", _snaps([100, 80]))
        # (100/80 - 1)*100 = 25
        self.assertAlmostEqual(state.recovery_needed_pct, 25.0, places=4)

    # Edge cases
    def test_single_snapshot_drawdown_zero(self):
        state = analyze_strategy("S", _snaps([100]))
        self.assertAlmostEqual(state.drawdown_pct, 0.0, places=6)

    def test_single_snapshot_duration_zero(self):
        state = analyze_strategy("S", _snaps([100]))
        self.assertEqual(state.drawdown_duration_periods, 0)

    def test_all_values_equal_no_drawdown(self):
        state = analyze_strategy("S", _snaps([100, 100, 100]))
        self.assertAlmostEqual(state.drawdown_pct, 0.0, places=6)
        self.assertEqual(state.drawdown_duration_periods, 0)

    def test_monotonically_declining(self):
        # all periods are below first peak → duration = len-1
        values = [100, 90, 80, 70, 60]
        state = analyze_strategy("S", _snaps(values))
        self.assertEqual(state.drawdown_duration_periods, len(values) - 1)

    def test_strategy_name_preserved(self):
        state = analyze_strategy("MyStrat", _snaps([100, 95]))
        self.assertEqual(state.strategy_name, "MyStrat")


# ---------------------------------------------------------------------------
# guard_portfolio
# ---------------------------------------------------------------------------

class TestGuardPortfolio(unittest.TestCase):

    def test_strategies_in_halt_correct(self):
        data = _portfolio_data([
            ("S_HALT", [100, 70], 10.0, 20.0),
            ("S_NORMAL", [100, 99], 10.0, 20.0),
        ])
        result = guard_portfolio(data)
        self.assertIn("S_HALT", result.strategies_in_halt)
        self.assertNotIn("S_NORMAL", result.strategies_in_halt)

    def test_strategies_in_warning_correct(self):
        data = _portfolio_data([
            ("S_WARN", [100, 88], 10.0, 20.0),
            ("S_NORMAL", [100, 99], 10.0, 20.0),
        ])
        result = guard_portfolio(data)
        self.assertIn("S_WARN", result.strategies_in_warning)
        self.assertNotIn("S_NORMAL", result.strategies_in_warning)

    def test_overall_halt_beats_warning(self):
        data = _portfolio_data([
            ("S_HALT", [100, 70], 10.0, 20.0),
            ("S_WARN", [100, 88], 10.0, 20.0),
        ])
        result = guard_portfolio(data)
        self.assertEqual(result.overall_alert_level, "HALT")

    def test_overall_warning_beats_normal(self):
        data = _portfolio_data([
            ("S_WARN", [100, 88], 10.0, 20.0),
            ("S_NORMAL", [100, 99], 10.0, 20.0),
        ])
        result = guard_portfolio(data)
        self.assertEqual(result.overall_alert_level, "WARNING")

    def test_overall_normal_when_all_normal(self):
        data = _portfolio_data([
            ("S1", [100, 99], 10.0, 20.0),
            ("S2", [100, 98], 10.0, 20.0),
        ])
        result = guard_portfolio(data)
        self.assertEqual(result.overall_alert_level, "NORMAL")

    def test_recommendation_summary_mentions_count(self):
        data = _portfolio_data([
            ("S_HALT", [100, 70], 10.0, 20.0),
        ])
        result = guard_portfolio(data)
        # summary should mention halt count
        self.assertGreater(len(result.recommendation_summary), 5)
        self.assertIn("1", result.recommendation_summary)

    def test_recommendation_normal_summary(self):
        data = _portfolio_data([
            ("S1", [100, 99], 10.0, 20.0),
            ("S2", [100, 98], 10.0, 20.0),
        ])
        result = guard_portfolio(data)
        self.assertIn("normal", result.recommendation_summary.lower())

    def test_strategies_list_length(self):
        data = _portfolio_data([
            ("A", [100, 99], 10.0, 20.0),
            ("B", [100, 70], 10.0, 20.0),
            ("C", [100, 85], 10.0, 20.0),
        ])
        result = guard_portfolio(data)
        self.assertEqual(len(result.strategies), 3)

    def test_halt_not_in_warning_list(self):
        data = _portfolio_data([
            ("S_HALT", [100, 70], 10.0, 20.0),
        ])
        result = guard_portfolio(data)
        self.assertNotIn("S_HALT", result.strategies_in_warning)

    def test_empty_strategies_returns_normal(self):
        result = guard_portfolio([])
        self.assertEqual(result.overall_alert_level, "NORMAL")

    def test_warning_recommendation_mentions_count(self):
        data = _portfolio_data([
            ("W1", [100, 88], 10.0, 20.0),
            ("W2", [100, 87], 10.0, 20.0),
        ])
        result = guard_portfolio(data)
        self.assertEqual(result.overall_alert_level, "WARNING")
        self.assertIn("2", result.recommendation_summary)

    def test_drawdown_usd_correct(self):
        state = analyze_strategy("S", _snaps([100_000, 80_000]))
        self.assertAlmostEqual(state.drawdown_usd, 20_000.0, places=2)


# ---------------------------------------------------------------------------
# Save / Load
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):

    def _make_result(self):
        data = _portfolio_data([("S", [100, 95], 10.0, 20.0)])
        return guard_portfolio(data)

    def test_save_creates_file(self):
        path = _tmp_log()
        result = self._make_result()
        save_results(result, path)
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_load_returns_list(self):
        path = _tmp_log()
        save_results(self._make_result(), path)
        history = load_history(path)
        self.assertIsInstance(history, list)
        os.unlink(path)

    def test_round_trip_entry_count(self):
        path = _tmp_log()
        for _ in range(3):
            save_results(self._make_result(), path)
        history = load_history(path)
        self.assertEqual(len(history), 3)
        os.unlink(path)

    def test_load_missing_returns_empty_list(self):
        history = load_history("/tmp/__nonexistent_sdg_test__.json")
        self.assertEqual(history, [])

    def test_ring_buffer_capped_at_100(self):
        path = _tmp_log()
        for _ in range(105):
            save_results(self._make_result(), path)
        history = load_history(path)
        self.assertEqual(len(history), 100)
        os.unlink(path)

    def test_saved_to_field_set_after_save(self):
        path = _tmp_log()
        result = self._make_result()
        save_results(result, path)
        self.assertEqual(result.saved_to, path)
        os.unlink(path)


if __name__ == "__main__":
    unittest.main()
