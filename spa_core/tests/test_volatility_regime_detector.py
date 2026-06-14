"""
MP-648 — VolatilityRegimeDetector unit tests.
Run: python3 -m unittest spa_core.tests.test_volatility_regime_detector -v
Pure stdlib / unittest only. No pytest.
"""

import json
import math
import os
import tempfile
import time
import unittest
from pathlib import Path

from spa_core.analytics.volatility_regime_detector import (
    VolatilityRegimeDetector,
    RegimeSnapshot,
    MAX_ENTRIES,
    REGIMES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _detector(tmp_dir: str) -> VolatilityRegimeDetector:
    return VolatilityRegimeDetector(data_file=Path(tmp_dir) / "vrl.json")


def _make_history_entry(regime: str, regime_changed: bool = False) -> dict:
    return {"regime": regime, "regime_changed": regime_changed}


# Precise stdev of two values (a, b): sqrt(((a-m)^2 + (b-m)^2) / 1)
def _two_val_stdev(a: float, b: float) -> float:
    mean = (a + b) / 2
    return math.sqrt(((a - mean) ** 2 + (b - mean) ** 2) / 1)


# ===========================================================================
# 1. _stdev
# ===========================================================================
class TestStdev(unittest.TestCase):
    def setUp(self):
        self.d = VolatilityRegimeDetector()

    def test_empty_returns_zero(self):
        self.assertAlmostEqual(self.d._stdev([]), 0.0, places=6)

    def test_single_value_returns_zero(self):
        self.assertAlmostEqual(self.d._stdev([0.05]), 0.0, places=6)

    def test_two_identical_values_returns_zero(self):
        self.assertAlmostEqual(self.d._stdev([0.05, 0.05]), 0.0, places=6)

    def test_two_known_values(self):
        # stdev([0.0, 0.1]) = sqrt(((−0.05)^2 + (0.05)^2)/1) = sqrt(0.005) ≈ 0.070711
        expected = _two_val_stdev(0.0, 0.1)
        self.assertAlmostEqual(self.d._stdev([0.0, 0.1]), expected, places=6)

    def test_constant_series_returns_zero(self):
        self.assertAlmostEqual(self.d._stdev([0.05] * 14), 0.0, places=6)

    def test_known_three_value_stdev(self):
        # [1, 2, 3] → mean=2, stdev=1.0
        self.assertAlmostEqual(self.d._stdev([1.0, 2.0, 3.0]), 1.0, places=6)

    def test_returns_float(self):
        self.assertIsInstance(self.d._stdev([0.01, 0.02]), float)

    def test_large_values_no_overflow(self):
        vals = [1000.0 * i for i in range(1, 15)]
        result = self.d._stdev(vals)
        self.assertGreater(result, 0.0)


# ===========================================================================
# 2. _classify_regime
# ===========================================================================
class TestClassifyRegime(unittest.TestCase):
    def setUp(self):
        self.d = VolatilityRegimeDetector()

    # CALM
    def test_zero_vol_is_calm(self):
        self.assertEqual(self.d._classify_regime(0.0), "CALM")

    def test_below_normal_threshold_is_calm(self):
        self.assertEqual(self.d._classify_regime(0.009), "CALM")

    # NORMAL boundary
    def test_exactly_normal_threshold_is_normal(self):
        self.assertEqual(self.d._classify_regime(0.010), "NORMAL")

    def test_normal_mid(self):
        self.assertEqual(self.d._classify_regime(0.015), "NORMAL")

    def test_just_below_stressed_threshold_is_normal(self):
        self.assertEqual(self.d._classify_regime(0.0249), "NORMAL")

    # STRESSED boundary
    def test_exactly_stressed_threshold_is_stressed(self):
        self.assertEqual(self.d._classify_regime(0.025), "STRESSED")

    def test_stressed_mid(self):
        self.assertEqual(self.d._classify_regime(0.030), "STRESSED")

    def test_just_below_crisis_threshold_is_stressed(self):
        self.assertEqual(self.d._classify_regime(0.0399), "STRESSED")

    # CRISIS boundary
    def test_exactly_crisis_threshold_is_crisis(self):
        self.assertEqual(self.d._classify_regime(0.040), "CRISIS")

    def test_above_crisis_threshold_is_crisis(self):
        self.assertEqual(self.d._classify_regime(0.10), "CRISIS")

    def test_returns_string(self):
        self.assertIsInstance(self.d._classify_regime(0.02), str)


# ===========================================================================
# 3. _advisory
# ===========================================================================
class TestAdvisory(unittest.TestCase):
    def setUp(self):
        self.d = VolatilityRegimeDetector()

    def test_crisis_advisory_nonempty(self):
        self.assertTrue(len(self.d._advisory("CRISIS")) > 0)

    def test_stressed_advisory_nonempty(self):
        self.assertTrue(len(self.d._advisory("STRESSED")) > 0)

    def test_normal_advisory_nonempty(self):
        self.assertTrue(len(self.d._advisory("NORMAL")) > 0)

    def test_calm_advisory_nonempty(self):
        self.assertTrue(len(self.d._advisory("CALM")) > 0)

    def test_all_advisories_are_distinct(self):
        texts = {self.d._advisory(r) for r in ("CRISIS", "STRESSED", "NORMAL", "CALM")}
        self.assertEqual(len(texts), 4)

    def test_advisory_returns_string(self):
        self.assertIsInstance(self.d._advisory("NORMAL"), str)


# ===========================================================================
# 4. _days_in_regime
# ===========================================================================
class TestDaysInRegime(unittest.TestCase):
    def setUp(self):
        self.d = VolatilityRegimeDetector()

    def test_empty_history_returns_one(self):
        self.assertEqual(self.d._days_in_regime([], "CALM"), 1)

    def test_single_matching_entry(self):
        history = [_make_history_entry("CALM")]
        self.assertEqual(self.d._days_in_regime(history, "CALM"), 2)

    def test_three_consecutive_matching(self):
        history = [_make_history_entry("NORMAL")] * 3
        self.assertEqual(self.d._days_in_regime(history, "NORMAL"), 4)

    def test_break_on_mismatch(self):
        history = [
            _make_history_entry("CALM"),
            _make_history_entry("NORMAL"),
            _make_history_entry("NORMAL"),
        ]
        # last two match "NORMAL" → count=2 + 1 today = 3
        self.assertEqual(self.d._days_in_regime(history, "NORMAL"), 3)

    def test_no_match_at_tail_returns_one(self):
        history = [_make_history_entry("CRISIS"), _make_history_entry("CALM")]
        # latest = "CALM" != "NORMAL" → count=0, return 1
        self.assertEqual(self.d._days_in_regime(history, "NORMAL"), 1)

    def test_all_different_returns_one(self):
        history = [
            _make_history_entry("CRISIS"),
            _make_history_entry("STRESSED"),
            _make_history_entry("NORMAL"),
        ]
        self.assertEqual(self.d._days_in_regime(history, "CALM"), 1)


# ===========================================================================
# 5. detect — basic behaviour
# ===========================================================================
class TestDetect(unittest.TestCase):
    def setUp(self):
        self.d = VolatilityRegimeDetector()

    def test_less_than_two_readings_is_calm(self):
        snap = self.d.detect("S0", [0.05])
        self.assertEqual(snap.regime, "CALM")

    def test_one_reading_vol_zero(self):
        snap = self.d.detect("S0", [0.05])
        self.assertAlmostEqual(snap.current_vol, 0.0, places=6)

    def test_14_identical_readings_is_calm(self):
        snap = self.d.detect("S0", [0.05] * 14)
        self.assertEqual(snap.regime, "CALM")
        self.assertAlmostEqual(snap.current_vol, 0.0, places=6)

    def test_high_variance_series_is_crisis(self):
        # Alternating 0.0 and 0.20 → vol ≈ 0.1414 >> 0.04
        series = [0.0, 0.20] * 7
        snap = self.d.detect("S0", series)
        self.assertEqual(snap.regime, "CRISIS")

    def test_strategy_id_propagated(self):
        snap = self.d.detect("S9", [0.05] * 5)
        self.assertEqual(snap.strategy_id, "S9")

    def test_timestamp_is_recent(self):
        before = time.time()
        snap = self.d.detect("S0", [0.05] * 5)
        after = time.time()
        self.assertGreaterEqual(snap.timestamp, before)
        self.assertLessEqual(snap.timestamp, after)

    def test_snapshot_has_regime_label(self):
        snap = self.d.detect("S0", [0.05] * 5)
        self.assertIn(snap.regime_label, [v["label"] for v in REGIMES.values()])

    def test_snapshot_has_advisory(self):
        snap = self.d.detect("S0", [0.05] * 5)
        self.assertTrue(len(snap.advisory) > 0)

    def test_uses_last_14_values_of_long_series(self):
        # First 100 values are high-variance; last 14 are flat → CALM
        noisy = [0.0 if i % 2 == 0 else 0.5 for i in range(100)]
        flat  = [0.05] * 14
        snap = self.d.detect("S0", noisy + flat)
        self.assertEqual(snap.regime, "CALM")

    def test_vol_rounded_to_6_places(self):
        snap = self.d.detect("S0", [0.01, 0.02, 0.03])
        # Just verify it's stored as a float with at most 6 decimal places
        self.assertEqual(round(snap.current_vol, 6), snap.current_vol)


# ===========================================================================
# 6. detect — regime_changed and prev_regime
# ===========================================================================
class TestRegimeChanged(unittest.TestCase):
    def setUp(self):
        self.d = VolatilityRegimeDetector()

    def test_no_history_regime_changed_false(self):
        snap = self.d.detect("S0", [0.05] * 5, history=[])
        self.assertFalse(snap.regime_changed)

    def test_no_history_prev_regime_none(self):
        snap = self.d.detect("S0", [0.05] * 5, history=[])
        self.assertIsNone(snap.prev_regime)

    def test_same_regime_not_changed(self):
        history = [_make_history_entry("CALM")]
        snap = self.d.detect("S0", [0.05] * 5, history=history)
        # series vol ≈ 0 → CALM; prev CALM → no change
        self.assertFalse(snap.regime_changed)

    def test_different_regime_changed_true(self):
        history = [_make_history_entry("CRISIS")]
        snap = self.d.detect("S0", [0.05] * 5, history=history)
        # vol ≈ 0 → CALM; prev CRISIS → changed
        self.assertTrue(snap.regime_changed)

    def test_prev_regime_from_last_history_entry(self):
        history = [
            _make_history_entry("STRESSED"),
            _make_history_entry("NORMAL"),
        ]
        snap = self.d.detect("S0", [0.05] * 5, history=history)
        self.assertEqual(snap.prev_regime, "NORMAL")

    def test_history_none_treated_as_empty(self):
        snap = self.d.detect("S0", [0.05] * 5, history=None)
        self.assertFalse(snap.regime_changed)
        self.assertIsNone(snap.prev_regime)


# ===========================================================================
# 7. detect — days_in_regime
# ===========================================================================
class TestDaysInRegimeDetect(unittest.TestCase):
    def setUp(self):
        self.d = VolatilityRegimeDetector()

    def test_no_history_days_in_regime_is_one(self):
        snap = self.d.detect("S0", [0.05] * 5)
        self.assertEqual(snap.days_in_regime, 1)

    def test_two_prior_same_regime(self):
        history = [_make_history_entry("CALM")] * 2
        snap = self.d.detect("S0", [0.05] * 5, history=history)
        self.assertEqual(snap.days_in_regime, 3)


# ===========================================================================
# 8. save_snapshot / load_history / ring-buffer
# ===========================================================================
class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = _detector(self.tmp)

    def _snap(self, regime: str = "CALM") -> RegimeSnapshot:
        series = [0.05] * 5 if regime == "CALM" else [0.0, 0.5] * 7
        return self.d.detect("S0", series)

    def test_load_missing_file_returns_empty(self):
        self.assertEqual(self.d.load_history(), [])

    def test_save_then_load_round_trip(self):
        snap = self._snap()
        self.d.save_snapshot(snap)
        h = self.d.load_history()
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["strategy_id"], "S0")

    def test_atomic_write_no_tmp_left_over(self):
        snap = self._snap()
        self.d.save_snapshot(snap)
        tmp_path = self.d.data_file.with_suffix(".tmp")
        self.assertFalse(tmp_path.exists())

    def test_ring_buffer_truncation(self):
        for _ in range(MAX_ENTRIES + 10):
            self.d.save_snapshot(self._snap())
        h = self.d.load_history()
        self.assertEqual(len(h), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        # Fill 95 CALM entries
        for _ in range(95):
            self.d.save_snapshot(self._snap("CALM"))
        # Add 10 CRISIS entries
        for _ in range(10):
            self.d.save_snapshot(self._snap("CRISIS"))
        h = self.d.load_history()
        self.assertEqual(len(h), MAX_ENTRIES)
        self.assertEqual(h[-1]["regime"], "CRISIS")

    def test_persisted_fields_present(self):
        snap = self._snap()
        self.d.save_snapshot(snap)
        h = self.d.load_history()[0]
        for field in ("timestamp", "strategy_id", "current_vol", "regime",
                      "regime_label", "days_in_regime", "regime_changed", "prev_regime"):
            self.assertIn(field, h)

    def test_load_corrupt_file_returns_empty(self):
        self.d.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.d.data_file.write_text("GARBAGE {{")
        self.assertEqual(self.d.load_history(), [])

    def test_append_accumulates(self):
        self.d.save_snapshot(self._snap())
        self.d.save_snapshot(self._snap())
        h = self.d.load_history()
        self.assertEqual(len(h), 2)


# ===========================================================================
# 9. get_regime_transitions
# ===========================================================================
class TestRegimeTransitions(unittest.TestCase):
    def setUp(self):
        self.d = VolatilityRegimeDetector()

    def test_empty_history_returns_empty(self):
        self.assertEqual(self.d.get_regime_transitions([]), [])

    def test_no_transitions(self):
        history = [_make_history_entry("CALM", regime_changed=False)] * 5
        self.assertEqual(self.d.get_regime_transitions(history), [])

    def test_single_transition(self):
        history = [
            _make_history_entry("CALM", False),
            _make_history_entry("NORMAL", True),
            _make_history_entry("NORMAL", False),
        ]
        transitions = self.d.get_regime_transitions(history)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["regime"], "NORMAL")

    def test_multiple_transitions(self):
        history = [
            _make_history_entry("CALM", False),
            _make_history_entry("NORMAL", True),
            _make_history_entry("STRESSED", True),
        ]
        self.assertEqual(len(self.d.get_regime_transitions(history)), 2)

    def test_all_transitions(self):
        history = [_make_history_entry("CALM", True)] * 4
        self.assertEqual(len(self.d.get_regime_transitions(history)), 4)


# ===========================================================================
# 10. Full 30-day scenario: calm → volatile
# ===========================================================================
class TestFullScenario(unittest.TestCase):
    def setUp(self):
        self.d = VolatilityRegimeDetector()

    def test_30_day_calm_then_volatile(self):
        """
        Days 1-20: flat APY (CALM).
        Days 21-30: wildly oscillating APY (CRISIS).
        Verify regime_changed fires when volatility spikes.
        """
        calm_series = [0.05] * 20
        volatile_chunk = [0.0 if i % 2 == 0 else 0.20 for i in range(10)]
        full_series = calm_series + volatile_chunk

        history: list = []
        snaps = []
        for i in range(len(full_series)):
            snap = self.d.detect("S_full", full_series[: i + 1], history=history)
            history.append(
                {
                    "regime": snap.regime,
                    "regime_changed": snap.regime_changed,
                }
            )
            snaps.append(snap)

        # First 20 days should be CALM (single-value → stdev=0)
        for s in snaps[:20]:
            self.assertEqual(s.regime, "CALM")

        # After enough volatile data enters the 14-day window, regime must be CRISIS
        late_snaps = snaps[28:]
        self.assertTrue(
            any(s.regime == "CRISIS" for s in late_snaps),
            "Expected CRISIS regime in last 2 snaps",
        )

        # At least one transition must have been recorded
        transitions = [s for s in snaps if s.regime_changed]
        self.assertGreater(len(transitions), 0, "Expected at least one regime change")

    def test_days_in_regime_increases_monotonically_in_calm_streak(self):
        history: list = []
        snaps = []
        for i in range(10):
            snap = self.d.detect("S0", [0.05] * (i + 1), history=history)
            history.append({"regime": snap.regime, "regime_changed": snap.regime_changed})
            snaps.append(snap)
        # days_in_regime should increase by 1 each day
        for i, s in enumerate(snaps):
            self.assertEqual(s.days_in_regime, i + 1)


if __name__ == "__main__":
    unittest.main()
