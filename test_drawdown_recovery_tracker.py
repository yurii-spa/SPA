"""
MP-647 — DrawdownRecoveryTracker unit tests.
Run: python3 -m unittest spa_core.tests.test_drawdown_recovery_tracker -v
Pure stdlib / unittest only. No pytest.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.drawdown_recovery_tracker import (
    DrawdownEpisode,
    DrawdownRecoveryTracker,
    MAX_ENTRIES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _tracker(tmp_dir: str) -> DrawdownRecoveryTracker:
    return DrawdownRecoveryTracker(data_file=Path(tmp_dir) / "drl.json")


def _make_episode(**kwargs) -> DrawdownEpisode:
    defaults = dict(
        strategy_id="S0",
        peak_apy=0.10,
        trough_apy=0.08,
        drawdown_pct=0.20,
        start_day=0,
        trough_day=2,
        recovery_day=None,
        days_to_trough=2,
        days_to_recover=None,
        status="RECOVERING",
        severity="MODERATE",
    )
    defaults.update(kwargs)
    return DrawdownEpisode(**defaults)


# ===========================================================================
# 1. _severity
# ===========================================================================
class TestSeverity(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownRecoveryTracker()

    # --- MINOR bucket ---
    def test_severity_zero_is_minor(self):
        self.assertEqual(self.t._severity(0.0), "MINOR")

    def test_severity_very_small_is_minor(self):
        self.assertEqual(self.t._severity(0.001), "MINOR")

    def test_severity_below_boundary_is_minor(self):
        self.assertEqual(self.t._severity(0.0499), "MINOR")

    # --- boundary at 0.05 ---
    def test_severity_exactly_005_is_moderate(self):
        self.assertEqual(self.t._severity(0.05), "MODERATE")

    # --- MODERATE bucket ---
    def test_severity_moderate_mid(self):
        self.assertEqual(self.t._severity(0.10), "MODERATE")

    def test_severity_just_below_015_is_moderate(self):
        self.assertEqual(self.t._severity(0.1499), "MODERATE")

    # --- boundary at 0.15 ---
    def test_severity_exactly_015_is_severe(self):
        self.assertEqual(self.t._severity(0.15), "SEVERE")

    # --- SEVERE bucket ---
    def test_severity_large_is_severe(self):
        self.assertEqual(self.t._severity(0.50), "SEVERE")

    def test_severity_one_hundred_pct_is_severe(self):
        self.assertEqual(self.t._severity(1.0), "SEVERE")

    def test_severity_returns_string(self):
        self.assertIsInstance(self.t._severity(0.07), str)


# ===========================================================================
# 2. detect_episodes — edge cases
# ===========================================================================
class TestDetectEpisodesEdge(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownRecoveryTracker()

    def test_empty_series_returns_empty(self):
        self.assertEqual(self.t.detect_episodes("S0", []), [])

    def test_single_value_returns_empty(self):
        self.assertEqual(self.t.detect_episodes("S0", [0.05]), [])

    def test_two_equal_values_returns_empty(self):
        self.assertEqual(self.t.detect_episodes("S0", [0.05, 0.05]), [])

    def test_flat_series_returns_empty(self):
        self.assertEqual(self.t.detect_episodes("S0", [0.05] * 10), [])

    def test_monotonic_up_returns_empty(self):
        series = [0.01 * i for i in range(1, 11)]
        self.assertEqual(self.t.detect_episodes("S0", series), [])

    def test_two_values_downward_open_drawdown(self):
        eps = self.t.detect_episodes("S0", [0.10, 0.08])
        self.assertEqual(len(eps), 1)
        self.assertIsNone(eps[0].recovery_day)

    def test_strategy_id_propagated(self):
        eps = self.t.detect_episodes("S7", [0.10, 0.08])
        self.assertEqual(eps[0].strategy_id, "S7")


# ===========================================================================
# 3. detect_episodes — V-shape (single recovered episode)
# ===========================================================================
class TestDetectEpisodesVShape(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownRecoveryTracker()
        # [0.10, 0.08, 0.06, 0.11]
        # peak=0.10 at idx 0, trough=0.06 at idx 2, recovery at idx 3
        self.series = [0.10, 0.08, 0.06, 0.11]
        self.eps = self.t.detect_episodes("S1", self.series)

    def test_one_episode(self):
        self.assertEqual(len(self.eps), 1)

    def test_status_recovered(self):
        self.assertEqual(self.eps[0].status, "RECOVERED")

    def test_peak_apy(self):
        self.assertAlmostEqual(self.eps[0].peak_apy, 0.10, places=6)

    def test_trough_apy(self):
        self.assertAlmostEqual(self.eps[0].trough_apy, 0.06, places=6)

    def test_drawdown_pct(self):
        # (0.10 - 0.06) / 0.10 = 0.40
        self.assertAlmostEqual(self.eps[0].drawdown_pct, 0.40, places=6)

    def test_start_day(self):
        self.assertEqual(self.eps[0].start_day, 0)

    def test_trough_day(self):
        self.assertEqual(self.eps[0].trough_day, 2)

    def test_recovery_day(self):
        self.assertEqual(self.eps[0].recovery_day, 3)

    def test_days_to_trough(self):
        self.assertEqual(self.eps[0].days_to_trough, 2)

    def test_days_to_recover(self):
        self.assertEqual(self.eps[0].days_to_recover, 1)

    def test_severity_severe(self):
        # 40% drawdown → SEVERE
        self.assertEqual(self.eps[0].severity, "SEVERE")


# ===========================================================================
# 4. detect_episodes — open drawdown at end
# ===========================================================================
class TestDetectEpisodesOpenDrawdown(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownRecoveryTracker()

    def test_open_minor_status_recovering(self):
        # drawdown_pct = (0.10 - 0.098) / 0.10 = 0.02 → MINOR → RECOVERING
        eps = self.t.detect_episodes("S0", [0.10, 0.098])
        self.assertEqual(len(eps), 1)
        self.assertEqual(eps[0].status, "RECOVERING")
        self.assertIsNone(eps[0].recovery_day)

    def test_open_deep_status_deep(self):
        # drawdown_pct = (0.10 - 0.08) / 0.10 = 0.20 → > 15% → DEEP
        eps = self.t.detect_episodes("S0", [0.10, 0.08])
        self.assertEqual(eps[0].status, "DEEP")

    def test_open_moderate_status_recovering(self):
        # 10% drawdown → MODERATE → still RECOVERING (not DEEP)
        eps = self.t.detect_episodes("S0", [0.10, 0.09])
        self.assertEqual(eps[0].status, "RECOVERING")

    def test_open_drawdown_days_to_recover_none(self):
        eps = self.t.detect_episodes("S0", [0.10, 0.08])
        self.assertIsNone(eps[0].days_to_recover)


# ===========================================================================
# 5. drawdown_pct calculation correctness
# ===========================================================================
class TestDrawdownPctCalc(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownRecoveryTracker()

    def test_50pct_drawdown(self):
        eps = self.t.detect_episodes("S0", [0.10, 0.05, 0.11])
        self.assertAlmostEqual(eps[0].drawdown_pct, 0.50, places=6)

    def test_10pct_drawdown(self):
        eps = self.t.detect_episodes("S0", [0.10, 0.09, 0.11])
        self.assertAlmostEqual(eps[0].drawdown_pct, 0.10, places=6)

    def test_1pct_drawdown(self):
        eps = self.t.detect_episodes("S0", [0.10, 0.099, 0.11])
        self.assertAlmostEqual(eps[0].drawdown_pct, 0.01, places=6)

    def test_peak_zero_no_division_by_zero(self):
        # peak=0 → drawdown_pct should be 0.0 (guarded)
        eps = self.t.detect_episodes("S0", [0.0, -0.01])
        self.assertEqual(eps[0].drawdown_pct, 0.0)

    def test_peak_zero_trough_negative_open(self):
        eps = self.t.detect_episodes("S0", [0.0, -0.05])
        self.assertIsNotNone(eps)  # should not crash


# ===========================================================================
# 6. days_to_trough / days_to_recover
# ===========================================================================
class TestDayCounters(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownRecoveryTracker()

    def test_days_to_trough_immediate(self):
        # peak at 0, trough at 1
        eps = self.t.detect_episodes("S0", [0.10, 0.05, 0.11])
        self.assertEqual(eps[0].days_to_trough, 1)

    def test_days_to_trough_delayed(self):
        # peak at 0, keeps falling: 0.10 0.09 0.08 0.07, then 0.11
        eps = self.t.detect_episodes("S0", [0.10, 0.09, 0.08, 0.07, 0.11])
        self.assertEqual(eps[0].days_to_trough, 3)

    def test_days_to_recover_one(self):
        eps = self.t.detect_episodes("S0", [0.10, 0.05, 0.11])
        self.assertEqual(eps[0].days_to_recover, 1)

    def test_days_to_recover_three(self):
        # trough at idx 1, then slow climb: 0.09, 0.10.5... we need a new high
        # [0.10, 0.05, 0.06, 0.07, 0.11] — trough idx=1, recovery idx=4
        eps = self.t.detect_episodes("S0", [0.10, 0.05, 0.06, 0.07, 0.11])
        self.assertEqual(eps[0].days_to_recover, 3)


# ===========================================================================
# 7. Multiple episodes in one series
# ===========================================================================
class TestMultipleEpisodes(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownRecoveryTracker()

    def _two_episode_series(self):
        # Episode 1: peak 0.10 → trough 0.07 → recover 0.12
        # Episode 2: peak 0.12 → trough 0.09 (open)
        return [0.10, 0.07, 0.12, 0.09]

    def test_two_episodes_detected(self):
        eps = self.t.detect_episodes("S0", self._two_episode_series())
        self.assertEqual(len(eps), 2)

    def test_first_episode_recovered(self):
        eps = self.t.detect_episodes("S0", self._two_episode_series())
        self.assertEqual(eps[0].status, "RECOVERED")

    def test_second_episode_open(self):
        eps = self.t.detect_episodes("S0", self._two_episode_series())
        self.assertIsNone(eps[1].recovery_day)

    def test_three_episodes(self):
        # [0.10, 0.06, 0.12, 0.08, 0.14, 0.09]
        # ep1: peak=0.10 trough=0.06 recover=0.12
        # ep2: peak=0.12 trough=0.08 recover=0.14
        # ep3: peak=0.14 trough=0.09 open
        series = [0.10, 0.06, 0.12, 0.08, 0.14, 0.09]
        eps = self.t.detect_episodes("S0", series)
        self.assertEqual(len(eps), 3)

    def test_episode_peak_values_correct(self):
        eps = self.t.detect_episodes("S0", self._two_episode_series())
        self.assertAlmostEqual(eps[0].peak_apy, 0.10, places=6)
        self.assertAlmostEqual(eps[1].peak_apy, 0.12, places=6)


# ===========================================================================
# 8. avg_recovery_days
# ===========================================================================
class TestAvgRecoveryDays(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownRecoveryTracker()

    def test_no_episodes_returns_none(self):
        self.assertIsNone(self.t.avg_recovery_days([]))

    def test_all_open_returns_none(self):
        ep = _make_episode(days_to_recover=None)
        self.assertIsNone(self.t.avg_recovery_days([ep]))

    def test_single_recovered_episode(self):
        ep = _make_episode(days_to_recover=5)
        self.assertAlmostEqual(self.t.avg_recovery_days([ep]), 5.0, places=6)

    def test_two_recovered_mean(self):
        ep1 = _make_episode(days_to_recover=4)
        ep2 = _make_episode(days_to_recover=6)
        self.assertAlmostEqual(self.t.avg_recovery_days([ep1, ep2]), 5.0, places=6)

    def test_mix_open_and_recovered(self):
        ep1 = _make_episode(days_to_recover=10)
        ep2 = _make_episode(days_to_recover=None)
        self.assertAlmostEqual(self.t.avg_recovery_days([ep1, ep2]), 10.0, places=6)

    def test_three_episodes_mean(self):
        eps = [_make_episode(days_to_recover=d) for d in [2, 4, 6]]
        self.assertAlmostEqual(self.t.avg_recovery_days(eps), 4.0, places=6)


# ===========================================================================
# 9. worst_episode
# ===========================================================================
class TestWorstEpisode(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownRecoveryTracker()

    def test_empty_returns_none(self):
        self.assertIsNone(self.t.worst_episode([]))

    def test_single_episode_returned(self):
        ep = _make_episode(drawdown_pct=0.20)
        self.assertIs(self.t.worst_episode([ep]), ep)

    def test_max_drawdown_selected(self):
        ep1 = _make_episode(drawdown_pct=0.10)
        ep2 = _make_episode(drawdown_pct=0.40)
        ep3 = _make_episode(drawdown_pct=0.25)
        worst = self.t.worst_episode([ep1, ep2, ep3])
        self.assertAlmostEqual(worst.drawdown_pct, 0.40, places=6)

    def test_worst_is_last_if_tie(self):
        # max() returns the first maximum found in Python — both equal
        ep1 = _make_episode(drawdown_pct=0.30)
        ep2 = _make_episode(drawdown_pct=0.30)
        worst = self.t.worst_episode([ep1, ep2])
        self.assertAlmostEqual(worst.drawdown_pct, 0.30, places=6)


# ===========================================================================
# 10. save_episodes / load_history / ring-buffer
# ===========================================================================
class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.t = _tracker(self.tmp)

    def test_load_history_missing_file_returns_empty(self):
        self.assertEqual(self.t.load_history(), [])

    def test_save_then_load_round_trip(self):
        ep = _make_episode(strategy_id="S2", drawdown_pct=0.10)
        self.t.save_episodes([ep])
        history = self.t.load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["strategy_id"], "S2")
        self.assertAlmostEqual(history[0]["drawdown_pct"], 0.10, places=6)

    def test_save_multiple_episodes(self):
        eps = [_make_episode(drawdown_pct=i * 0.01) for i in range(5)]
        self.t.save_episodes(eps)
        history = self.t.load_history()
        self.assertEqual(len(history), 5)

    def test_atomic_write_no_tmp_left_over(self):
        ep = _make_episode()
        self.t.save_episodes([ep])
        tmp_path = self.t.data_file.with_suffix(".tmp")
        self.assertFalse(tmp_path.exists())

    def test_ring_buffer_truncation(self):
        # Save MAX_ENTRIES + 10 episodes across two calls
        eps_first = [_make_episode(drawdown_pct=0.01 * i) for i in range(MAX_ENTRIES)]
        self.t.save_episodes(eps_first)
        eps_extra = [_make_episode(drawdown_pct=0.99 + i * 0.001) for i in range(10)]
        self.t.save_episodes(eps_extra)
        history = self.t.load_history()
        self.assertEqual(len(history), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        # First batch: 95 entries with drawdown_pct = 0.01
        eps_old = [_make_episode(drawdown_pct=0.01) for _ in range(95)]
        self.t.save_episodes(eps_old)
        # Second batch: 10 entries with drawdown_pct = 0.99
        eps_new = [_make_episode(drawdown_pct=0.99) for _ in range(10)]
        self.t.save_episodes(eps_new)
        history = self.t.load_history()
        # Total = 105 → ring-buffer keeps last 100
        self.assertEqual(len(history), 100)
        # The newest 10 entries should be at the end
        self.assertAlmostEqual(history[-1]["drawdown_pct"], 0.99, places=6)

    def test_save_persists_all_fields(self):
        ep = DrawdownEpisode(
            strategy_id="S9",
            peak_apy=0.27,
            trough_apy=0.20,
            drawdown_pct=round((0.27 - 0.20) / 0.27, 6),
            start_day=5,
            trough_day=8,
            recovery_day=12,
            days_to_trough=3,
            days_to_recover=4,
            status="RECOVERED",
            severity="MODERATE",
        )
        self.t.save_episodes([ep])
        h = self.t.load_history()[0]
        self.assertEqual(h["strategy_id"], "S9")
        self.assertAlmostEqual(h["peak_apy"], 0.27, places=6)
        self.assertAlmostEqual(h["trough_apy"], 0.20, places=6)
        self.assertEqual(h["start_day"], 5)
        self.assertEqual(h["trough_day"], 8)
        self.assertEqual(h["recovery_day"], 12)
        self.assertEqual(h["days_to_trough"], 3)
        self.assertEqual(h["days_to_recover"], 4)
        self.assertEqual(h["status"], "RECOVERED")
        self.assertEqual(h["severity"], "MODERATE")

    def test_load_history_corrupt_file_returns_empty(self):
        self.t.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.t.data_file.write_text("NOT JSON {{{")
        self.assertEqual(self.t.load_history(), [])

    def test_append_to_existing_history(self):
        ep1 = _make_episode(drawdown_pct=0.10)
        self.t.save_episodes([ep1])
        ep2 = _make_episode(drawdown_pct=0.20)
        self.t.save_episodes([ep2])
        history = self.t.load_history()
        self.assertEqual(len(history), 2)


# ===========================================================================
# 11. severity labels in detected episodes
# ===========================================================================
class TestSeverityInEpisodes(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownRecoveryTracker()

    def test_minor_episode(self):
        # 2% drawdown → MINOR
        eps = self.t.detect_episodes("S0", [0.10, 0.098, 0.11])
        self.assertEqual(eps[0].severity, "MINOR")

    def test_moderate_episode(self):
        # 10% drawdown → MODERATE
        eps = self.t.detect_episodes("S0", [0.10, 0.09, 0.11])
        self.assertEqual(eps[0].severity, "MODERATE")

    def test_severe_episode(self):
        # 40% drawdown → SEVERE
        eps = self.t.detect_episodes("S0", [0.10, 0.06, 0.11])
        self.assertEqual(eps[0].severity, "SEVERE")


# ===========================================================================
# 12. DEEP status correctness
# ===========================================================================
class TestDeepStatus(unittest.TestCase):
    def setUp(self):
        self.t = DrawdownRecoveryTracker()

    def test_deep_when_over_15pct_open(self):
        # 20% drawdown, open → DEEP
        eps = self.t.detect_episodes("S0", [0.10, 0.08])
        self.assertEqual(eps[0].status, "DEEP")

    def test_recovering_when_exactly_15pct_open(self):
        # exactly 15% → NOT > 0.15, so RECOVERING
        eps = self.t.detect_episodes("S0", [0.100, 0.085])
        # drawdown_pct = 0.15 exactly; 0.15 > 0.15 is False → RECOVERING
        self.assertEqual(eps[0].status, "RECOVERING")

    def test_recovered_ignores_depth(self):
        # Even deep drawdown that recovers gets RECOVERED status
        eps = self.t.detect_episodes("S0", [0.10, 0.05, 0.11])
        self.assertEqual(eps[0].status, "RECOVERED")


if __name__ == "__main__":
    unittest.main()
