"""
Tests for MP-1117 ProtocolDeFiEpochRewardTimingAnalyzer.
Run: python3 -m unittest spa_core.tests.test_protocol_defi_epoch_reward_timing_analyzer -v
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_defi_epoch_reward_timing_analyzer import (
    analyze,
    log_result,
    _timing_label,
    _entry_timing_score,
    _atomic_write,
    _LOG_CAP,
    _HOURS_PER_YEAR,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_kwargs(**overrides) -> dict:
    """Return baseline kwargs for analyze(); override as needed."""
    base = dict(
        epoch_duration_hours=168,       # weekly
        hours_elapsed_in_epoch=0.0,     # start of epoch
        reward_per_epoch_usd=10_000.0,
        total_staked_usd=5_000_000.0,
        my_stake_usd=100_000.0,
        entry_cost_usd=15.0,
        exit_cost_usd=12.0,
        protocol_name="TestProtocol",
    )
    base.update(overrides)
    return base


def _expected_progress(elapsed, duration):
    return elapsed / max(1.0, float(duration)) * 100.0


def _expected_share(my_stake, total_staked):
    pool = total_staked + my_stake
    if pool <= 0:
        return 0.0
    return my_stake / pool * 100.0


def _expected_reward(my_stake, total_staked, reward_per_epoch):
    share = _expected_share(my_stake, total_staked)
    return share / 100.0 * reward_per_epoch


def _expected_apy(my_stake, total_staked, reward_per_epoch, duration_hours):
    if my_stake <= 0:
        return 0.0
    epochs_per_year = _HOURS_PER_YEAR / max(1.0, float(duration_hours))
    reward = _expected_reward(my_stake, total_staked, reward_per_epoch)
    return reward * epochs_per_year / my_stake * 100.0


# ===========================================================================
# 1.  _timing_label  (12 tests)
# ===========================================================================
class TestTimingLabel(unittest.TestCase):

    def test_zero_pct_perfect_entry(self):
        self.assertEqual(_timing_label(0.0), "PERFECT_ENTRY")

    def test_five_pct_perfect_entry(self):
        self.assertEqual(_timing_label(5.0), "PERFECT_ENTRY")

    def test_ten_pct_perfect_entry(self):
        self.assertEqual(_timing_label(10.0), "PERFECT_ENTRY")

    def test_just_above_10_good_entry(self):
        self.assertEqual(_timing_label(10.1), "GOOD_ENTRY")

    def test_twenty_pct_good_entry(self):
        self.assertEqual(_timing_label(20.0), "GOOD_ENTRY")

    def test_thirty_pct_good_entry(self):
        self.assertEqual(_timing_label(30.0), "GOOD_ENTRY")

    def test_just_above_30_neutral(self):
        self.assertEqual(_timing_label(30.1), "NEUTRAL_TIMING")

    def test_fifty_pct_neutral(self):
        self.assertEqual(_timing_label(50.0), "NEUTRAL_TIMING")

    def test_sixty_pct_neutral(self):
        self.assertEqual(_timing_label(60.0), "NEUTRAL_TIMING")

    def test_sixty_one_pct_late(self):
        self.assertEqual(_timing_label(61.0), "LATE_ENTRY")

    def test_seventy_five_pct_late(self):
        self.assertEqual(_timing_label(75.0), "LATE_ENTRY")

    def test_eighty_five_pct_late(self):
        self.assertEqual(_timing_label(85.0), "LATE_ENTRY")

    def test_eighty_six_pct_almost_done(self):
        self.assertEqual(_timing_label(86.0), "EPOCH_ALMOST_DONE")

    def test_100_pct_almost_done(self):
        self.assertEqual(_timing_label(100.0), "EPOCH_ALMOST_DONE")

    def test_all_five_labels_exist(self):
        labels = {
            _timing_label(0.0),
            _timing_label(20.0),
            _timing_label(45.0),
            _timing_label(70.0),
            _timing_label(95.0),
        }
        self.assertEqual(len(labels), 5)


# ===========================================================================
# 2.  _entry_timing_score  (10 tests)
# ===========================================================================
class TestEntryTimingScore(unittest.TestCase):

    def test_zero_pct_gives_100(self):
        self.assertEqual(_entry_timing_score(0.0), 100)

    def test_fifty_pct_gives_50(self):
        self.assertEqual(_entry_timing_score(50.0), 50)

    def test_100_pct_gives_0(self):
        self.assertEqual(_entry_timing_score(100.0), 0)

    def test_10_pct_gives_90(self):
        self.assertEqual(_entry_timing_score(10.0), 90)

    def test_85_pct_gives_15(self):
        self.assertEqual(_entry_timing_score(85.0), 15)

    def test_never_below_zero(self):
        self.assertEqual(_entry_timing_score(200.0), 0)

    def test_returns_int(self):
        self.assertIsInstance(_entry_timing_score(33.3), int)

    def test_monotone_decreasing(self):
        scores = [_entry_timing_score(p) for p in (0, 10, 30, 60, 85, 100)]
        for a, b in zip(scores, scores[1:]):
            self.assertGreaterEqual(a, b)

    def test_25_pct_gives_75(self):
        self.assertEqual(_entry_timing_score(25.0), 75)

    def test_99_pct_gives_1(self):
        self.assertEqual(_entry_timing_score(99.0), 1)


# ===========================================================================
# 3.  _atomic_write helper  (5 tests)
# ===========================================================================
class TestAtomicWrite(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _path(self, name="log.json"):
        return os.path.join(self.tmpdir, name)

    def test_creates_file(self):
        path = self._path()
        _atomic_write(path, [{"epoch": 1}])
        self.assertTrue(os.path.exists(path))

    def test_content_correct(self):
        path = self._path()
        data = [{"a": 1}, {"b": 2}]
        _atomic_write(path, data)
        with open(path) as f:
            self.assertEqual(json.load(f), data)

    def test_overwrites_existing(self):
        path = self._path()
        _atomic_write(path, [1, 2, 3])
        _atomic_write(path, [99])
        with open(path) as f:
            self.assertEqual(json.load(f), [99])

    def test_no_tmp_file_left(self):
        path = self._path()
        _atomic_write(path, {"k": "v"})
        self.assertFalse(os.path.exists(path + ".tmp"))

    def test_nested_dir_created(self):
        path = os.path.join(self.tmpdir, "sub", "deep", "log.json")
        _atomic_write(path, [])
        self.assertTrue(os.path.exists(path))


# ===========================================================================
# 4.  analyze() — epoch progress / time  (10 tests)
# ===========================================================================
class TestAnalyzeEpochProgress(unittest.TestCase):

    def test_epoch_progress_zero(self):
        r = analyze(**_base_kwargs(hours_elapsed_in_epoch=0.0))
        self.assertAlmostEqual(r["epoch_progress_pct"], 0.0, places=6)

    def test_epoch_progress_halfway(self):
        r = analyze(**_base_kwargs(hours_elapsed_in_epoch=84.0))
        self.assertAlmostEqual(r["epoch_progress_pct"], 50.0, places=6)

    def test_epoch_progress_100(self):
        r = analyze(**_base_kwargs(hours_elapsed_in_epoch=168.0))
        self.assertAlmostEqual(r["epoch_progress_pct"], 100.0, places=6)

    def test_hours_remaining_at_start(self):
        r = analyze(**_base_kwargs(hours_elapsed_in_epoch=0.0,
                                   epoch_duration_hours=168))
        self.assertAlmostEqual(r["hours_remaining_in_epoch"], 168.0, places=6)

    def test_hours_remaining_halfway(self):
        r = analyze(**_base_kwargs(hours_elapsed_in_epoch=84.0,
                                   epoch_duration_hours=168))
        self.assertAlmostEqual(r["hours_remaining_in_epoch"], 84.0, places=6)

    def test_hours_remaining_at_end(self):
        r = analyze(**_base_kwargs(hours_elapsed_in_epoch=168.0,
                                   epoch_duration_hours=168))
        self.assertAlmostEqual(r["hours_remaining_in_epoch"], 0.0, places=6)

    def test_elapsed_clamped_above_duration(self):
        r = analyze(**_base_kwargs(hours_elapsed_in_epoch=999.0,
                                   epoch_duration_hours=168))
        self.assertAlmostEqual(r["epoch_progress_pct"], 100.0, places=6)
        self.assertAlmostEqual(r["hours_remaining_in_epoch"], 0.0, places=6)

    def test_elapsed_clamped_below_zero(self):
        r = analyze(**_base_kwargs(hours_elapsed_in_epoch=-10.0))
        self.assertAlmostEqual(r["epoch_progress_pct"], 0.0, places=6)

    def test_daily_epoch(self):
        r = analyze(**_base_kwargs(epoch_duration_hours=24,
                                   hours_elapsed_in_epoch=6.0))
        self.assertAlmostEqual(r["epoch_progress_pct"], 25.0, places=6)

    def test_monthly_epoch(self):
        r = analyze(**_base_kwargs(epoch_duration_hours=720,
                                   hours_elapsed_in_epoch=360.0))
        self.assertAlmostEqual(r["epoch_progress_pct"], 50.0, places=6)


# ===========================================================================
# 5.  analyze() — share and reward calculations  (12 tests)
# ===========================================================================
class TestAnalyzeShareAndReward(unittest.TestCase):

    def test_my_share_formula(self):
        r = analyze(**_base_kwargs(my_stake_usd=100_000.0,
                                   total_staked_usd=5_000_000.0))
        expected = 100_000.0 / (5_000_000.0 + 100_000.0) * 100.0
        self.assertAlmostEqual(r["my_share_pct"], expected, places=6)

    def test_my_share_equals_100_when_only_staker(self):
        r = analyze(**_base_kwargs(my_stake_usd=100_000.0,
                                   total_staked_usd=0.0))
        self.assertAlmostEqual(r["my_share_pct"], 100.0, places=6)

    def test_my_share_zero_when_no_stake(self):
        r = analyze(**_base_kwargs(my_stake_usd=0.0,
                                   total_staked_usd=1_000_000.0))
        self.assertAlmostEqual(r["my_share_pct"], 0.0, places=6)

    def test_my_share_zero_when_both_zero(self):
        r = analyze(**_base_kwargs(my_stake_usd=0.0, total_staked_usd=0.0))
        self.assertAlmostEqual(r["my_share_pct"], 0.0, places=6)

    def test_expected_reward_formula(self):
        r = analyze(**_base_kwargs(my_stake_usd=100_000.0,
                                   total_staked_usd=5_000_000.0,
                                   reward_per_epoch_usd=10_000.0))
        expected = _expected_reward(100_000.0, 5_000_000.0, 10_000.0)
        self.assertAlmostEqual(r["expected_epoch_reward_usd"], expected, places=6)

    def test_expected_reward_zero_when_no_stake(self):
        r = analyze(**_base_kwargs(my_stake_usd=0.0,
                                   reward_per_epoch_usd=10_000.0))
        self.assertAlmostEqual(r["expected_epoch_reward_usd"], 0.0, places=6)

    def test_expected_reward_equals_full_when_sole_staker(self):
        r = analyze(**_base_kwargs(my_stake_usd=100_000.0,
                                   total_staked_usd=0.0,
                                   reward_per_epoch_usd=500.0))
        self.assertAlmostEqual(r["expected_epoch_reward_usd"], 500.0, places=4)

    def test_apy_formula(self):
        r = analyze(**_base_kwargs())
        expected = _expected_apy(100_000.0, 5_000_000.0, 10_000.0, 168)
        self.assertAlmostEqual(r["annualized_reward_apy_pct"], expected, places=4)

    def test_apy_zero_when_no_stake(self):
        r = analyze(**_base_kwargs(my_stake_usd=0.0))
        self.assertAlmostEqual(r["annualized_reward_apy_pct"], 0.0, places=6)

    def test_apy_increases_with_reward_per_epoch(self):
        r_low = analyze(**_base_kwargs(reward_per_epoch_usd=1_000.0))
        r_high = analyze(**_base_kwargs(reward_per_epoch_usd=100_000.0))
        self.assertGreater(r_high["annualized_reward_apy_pct"],
                           r_low["annualized_reward_apy_pct"])

    def test_apy_decreases_with_more_total_stake(self):
        r_small = analyze(**_base_kwargs(total_staked_usd=100_000.0))
        r_large = analyze(**_base_kwargs(total_staked_usd=100_000_000.0))
        self.assertGreater(r_small["annualized_reward_apy_pct"],
                           r_large["annualized_reward_apy_pct"])

    def test_apy_increases_with_shorter_epoch(self):
        r_weekly = analyze(**_base_kwargs(epoch_duration_hours=168))
        r_daily = analyze(**_base_kwargs(epoch_duration_hours=24))
        self.assertGreater(r_daily["annualized_reward_apy_pct"],
                           r_weekly["annualized_reward_apy_pct"])


# ===========================================================================
# 6.  analyze() — timing label and score  (10 tests)
# ===========================================================================
class TestAnalyzeTimingLabelAndScore(unittest.TestCase):

    def _progress(self, elapsed, duration=168):
        return analyze(**_base_kwargs(hours_elapsed_in_epoch=elapsed,
                                     epoch_duration_hours=duration))

    def test_perfect_entry_at_start(self):
        r = self._progress(0.0)
        self.assertEqual(r["timing_label"], "PERFECT_ENTRY")

    def test_perfect_entry_score_is_100(self):
        r = self._progress(0.0)
        self.assertEqual(r["entry_timing_score"], 100)

    def test_good_entry(self):
        # 20% of 168 = 33.6 hours
        r = self._progress(33.6)
        self.assertEqual(r["timing_label"], "GOOD_ENTRY")

    def test_neutral_timing(self):
        # 45% of 168 = 75.6 hours
        r = self._progress(75.6)
        self.assertEqual(r["timing_label"], "NEUTRAL_TIMING")

    def test_late_entry(self):
        # 70% of 168 = 117.6 hours
        r = self._progress(117.6)
        self.assertEqual(r["timing_label"], "LATE_ENTRY")

    def test_epoch_almost_done(self):
        # 90% of 168 = 151.2 hours
        r = self._progress(151.2)
        self.assertEqual(r["timing_label"], "EPOCH_ALMOST_DONE")

    def test_score_at_end_is_zero(self):
        r = self._progress(168.0)
        self.assertEqual(r["entry_timing_score"], 0)

    def test_score_monotone_with_progress(self):
        progresses = [0.0, 16.8, 42.0, 84.0, 126.0, 168.0]
        scores = [self._progress(p)["entry_timing_score"] for p in progresses]
        for a, b in zip(scores, scores[1:]):
            self.assertGreaterEqual(a, b)

    def test_timing_label_consistent_with_score(self):
        r = self._progress(0.0)
        self.assertEqual(r["timing_label"], "PERFECT_ENTRY")
        self.assertGreaterEqual(r["entry_timing_score"], 90)

    def test_timing_score_is_int(self):
        r = self._progress(50.0)
        self.assertIsInstance(r["entry_timing_score"], int)


# ===========================================================================
# 7.  analyze() — costs and net reward  (8 tests)
# ===========================================================================
class TestAnalyzeCosts(unittest.TestCase):

    def test_total_cost_formula(self):
        r = analyze(**_base_kwargs(entry_cost_usd=15.0, exit_cost_usd=12.0))
        self.assertAlmostEqual(r["total_cost_usd"], 27.0, places=6)

    def test_net_reward_formula(self):
        r = analyze(**_base_kwargs(entry_cost_usd=15.0, exit_cost_usd=12.0))
        self.assertAlmostEqual(r["net_reward_usd"],
                               r["expected_epoch_reward_usd"] - 27.0, places=6)

    def test_zero_costs(self):
        r = analyze(**_base_kwargs(entry_cost_usd=0.0, exit_cost_usd=0.0))
        self.assertAlmostEqual(r["total_cost_usd"], 0.0, places=6)
        self.assertAlmostEqual(r["net_reward_usd"],
                               r["expected_epoch_reward_usd"], places=6)

    def test_high_costs_negative_net(self):
        r = analyze(**_base_kwargs(
            my_stake_usd=100.0,
            total_staked_usd=100_000_000.0,
            reward_per_epoch_usd=10_000.0,
            entry_cost_usd=500.0,
            exit_cost_usd=500.0,
        ))
        self.assertLess(r["net_reward_usd"], 0.0)

    def test_total_cost_zero_entry(self):
        r = analyze(**_base_kwargs(entry_cost_usd=0.0, exit_cost_usd=10.0))
        self.assertAlmostEqual(r["total_cost_usd"], 10.0, places=6)

    def test_total_cost_zero_exit(self):
        r = analyze(**_base_kwargs(entry_cost_usd=20.0, exit_cost_usd=0.0))
        self.assertAlmostEqual(r["total_cost_usd"], 20.0, places=6)

    def test_net_reward_positive_when_reward_exceeds_costs(self):
        r = analyze(**_base_kwargs(
            my_stake_usd=1_000_000.0,
            total_staked_usd=1_000_000.0,
            reward_per_epoch_usd=10_000.0,
            entry_cost_usd=5.0,
            exit_cost_usd=5.0,
        ))
        self.assertGreater(r["net_reward_usd"], 0.0)

    def test_epochs_per_year_weekly(self):
        r = analyze(**_base_kwargs(epoch_duration_hours=168))
        expected = _HOURS_PER_YEAR / 168.0
        self.assertAlmostEqual(r["epochs_per_year"], expected, places=4)


# ===========================================================================
# 8.  analyze() — return structure  (10 tests)
# ===========================================================================
class TestAnalyzeStructure(unittest.TestCase):

    def _r(self):
        return analyze(**_base_kwargs())

    def test_all_required_keys(self):
        r = self._r()
        required = {
            "protocol_name", "epoch_duration_hours", "hours_elapsed_in_epoch",
            "epoch_progress_pct", "hours_remaining_in_epoch", "my_share_pct",
            "expected_epoch_reward_usd", "annualized_reward_apy_pct",
            "entry_timing_score", "timing_label", "total_cost_usd",
            "net_reward_usd", "epochs_per_year", "timestamp",
        }
        self.assertTrue(required.issubset(r.keys()))

    def test_protocol_name_stored(self):
        r = analyze(**_base_kwargs(protocol_name="Aave V3"))
        self.assertEqual(r["protocol_name"], "Aave V3")

    def test_epoch_duration_stored(self):
        r = analyze(**_base_kwargs(epoch_duration_hours=24))
        self.assertEqual(r["epoch_duration_hours"], 24)

    def test_timing_label_is_string(self):
        self.assertIsInstance(self._r()["timing_label"], str)

    def test_entry_timing_score_is_int(self):
        self.assertIsInstance(self._r()["entry_timing_score"], int)

    def test_apy_is_float(self):
        self.assertIsInstance(self._r()["annualized_reward_apy_pct"], float)

    def test_timestamp_in_range(self):
        before = time.time()
        r = self._r()
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_timing_label_valid_value(self):
        valid = {"PERFECT_ENTRY", "GOOD_ENTRY", "NEUTRAL_TIMING",
                 "LATE_ENTRY", "EPOCH_ALMOST_DONE"}
        r = self._r()
        self.assertIn(r["timing_label"], valid)

    def test_share_pct_between_0_and_100(self):
        r = self._r()
        self.assertGreaterEqual(r["my_share_pct"], 0.0)
        self.assertLessEqual(r["my_share_pct"], 100.0)

    def test_progress_pct_between_0_and_100(self):
        for elapsed in (0, 84, 168):
            r = analyze(**_base_kwargs(hours_elapsed_in_epoch=elapsed))
            self.assertGreaterEqual(r["epoch_progress_pct"], 0.0)
            self.assertLessEqual(r["epoch_progress_pct"], 100.0)


# ===========================================================================
# 9.  analyze() — epoch duration edge cases  (8 tests)
# ===========================================================================
class TestAnalyzeEpochDurations(unittest.TestCase):

    def test_daily_epoch_24h(self):
        r = analyze(**_base_kwargs(epoch_duration_hours=24,
                                   hours_elapsed_in_epoch=6.0))
        self.assertAlmostEqual(r["epoch_progress_pct"], 25.0, places=6)

    def test_weekly_epoch_168h(self):
        r = analyze(**_base_kwargs(epoch_duration_hours=168,
                                   hours_elapsed_in_epoch=84.0))
        self.assertAlmostEqual(r["epoch_progress_pct"], 50.0, places=6)

    def test_biweekly_epoch_336h(self):
        r = analyze(**_base_kwargs(epoch_duration_hours=336,
                                   hours_elapsed_in_epoch=168.0))
        self.assertAlmostEqual(r["epoch_progress_pct"], 50.0, places=6)

    def test_monthly_epoch_720h(self):
        r = analyze(**_base_kwargs(epoch_duration_hours=720,
                                   hours_elapsed_in_epoch=180.0))
        self.assertAlmostEqual(r["epoch_progress_pct"], 25.0, places=6)

    def test_epoch_min_1_hour(self):
        # epoch_duration_hours=0 should be clamped to 1
        r = analyze(**_base_kwargs(epoch_duration_hours=0,
                                   hours_elapsed_in_epoch=0.0))
        self.assertGreater(r["epochs_per_year"], 0.0)

    def test_epochs_per_year_daily(self):
        r = analyze(**_base_kwargs(epoch_duration_hours=24))
        expected = _HOURS_PER_YEAR / 24.0
        self.assertAlmostEqual(r["epochs_per_year"], expected, places=4)

    def test_epochs_per_year_weekly(self):
        r = analyze(**_base_kwargs(epoch_duration_hours=168))
        expected = _HOURS_PER_YEAR / 168.0
        self.assertAlmostEqual(r["epochs_per_year"], expected, places=4)

    def test_apy_higher_for_shorter_epoch(self):
        r_daily = analyze(**_base_kwargs(epoch_duration_hours=24))
        r_weekly = analyze(**_base_kwargs(epoch_duration_hours=168))
        # Daily compounding → more epochs → higher APY (same reward per epoch)
        self.assertGreater(r_daily["annualized_reward_apy_pct"],
                           r_weekly["annualized_reward_apy_pct"])


# ===========================================================================
# 10. log_result() — ring-buffer and atomic write  (20 tests)
# ===========================================================================
class TestLogResult(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test_epoch_log.json")

    def _sample_result(self, **overrides) -> dict:
        r = analyze(**_base_kwargs())
        r.update(overrides)
        return r

    def test_creates_new_log_file(self):
        log_result(self._sample_result(), self.log_path)
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        log_result(self._sample_result(), self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_first_entry_count(self):
        log_result(self._sample_result(), self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_appends_second_entry(self):
        log_result(self._sample_result(), self.log_path)
        log_result(self._sample_result(), self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_entry_has_required_keys(self):
        log_result(self._sample_result(), self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        for key in ("timestamp", "protocol_name", "epoch_duration_hours",
                    "epoch_progress_pct", "timing_label", "entry_timing_score",
                    "my_share_pct", "expected_epoch_reward_usd",
                    "annualized_reward_apy_pct", "net_reward_usd"):
            self.assertIn(key, entry)

    def test_timing_label_stored_correctly(self):
        r = self._sample_result()
        log_result(r, self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["timing_label"], r["timing_label"])

    def test_protocol_name_stored(self):
        r = self._sample_result()
        r["protocol_name"] = "Aave V3"
        log_result(r, self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["protocol_name"], "Aave V3")

    def test_ring_buffer_capped_at_100(self):
        for i in range(105):
            log_result(self._sample_result(), self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), _LOG_CAP)

    def test_ring_buffer_keeps_last_entries(self):
        for i in range(105):
            r = self._sample_result()
            r["epoch_progress_pct"] = float(i)
            log_result(r, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        # Last entry should be from i=104
        self.assertEqual(data[-1]["epoch_progress_pct"], 104.0)

    def test_ring_buffer_exactly_100(self):
        for i in range(100):
            log_result(self._sample_result(), self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_handles_missing_file(self):
        missing = os.path.join(self.tmpdir, "missing.json")
        log_result(self._sample_result(), missing)
        with open(missing) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_handles_corrupt_json(self):
        with open(self.log_path, "w") as f:
            f.write("NOT JSON {{{")
        log_result(self._sample_result(), self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_handles_non_list_json(self):
        with open(self.log_path, "w") as f:
            json.dump({"not": "a list"}, f)
        log_result(self._sample_result(), self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_no_tmp_file_after_write(self):
        log_result(self._sample_result(), self.log_path)
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_timestamp_stored(self):
        r = self._sample_result()
        log_result(r, self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertIn("timestamp", entry)
        self.assertIsInstance(entry["timestamp"], float)

    def test_nested_log_dir_created(self):
        nested = os.path.join(self.tmpdir, "sub", "dir", "log.json")
        log_result(self._sample_result(), nested)
        self.assertTrue(os.path.exists(nested))

    def test_apy_in_entry(self):
        r = self._sample_result()
        log_result(r, self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertAlmostEqual(entry["annualized_reward_apy_pct"],
                               r["annualized_reward_apy_pct"], places=4)

    def test_net_reward_in_entry(self):
        r = self._sample_result()
        log_result(r, self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertAlmostEqual(entry["net_reward_usd"],
                               r["net_reward_usd"], places=6)

    def test_score_in_entry(self):
        r = self._sample_result()
        log_result(r, self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["entry_timing_score"], r["entry_timing_score"])

    def test_multiple_entries_ordered(self):
        for i in range(5):
            r = self._sample_result()
            r["epoch_progress_pct"] = float(i * 20)
            log_result(r, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        progress_values = [e["epoch_progress_pct"] for e in data]
        self.assertEqual(progress_values, [0.0, 20.0, 40.0, 60.0, 80.0])


# ===========================================================================
# 11. Constants checks  (5 tests)
# ===========================================================================
class TestModuleConstants(unittest.TestCase):

    def test_log_cap_is_100(self):
        self.assertEqual(_LOG_CAP, 100)

    def test_hours_per_year(self):
        self.assertAlmostEqual(_HOURS_PER_YEAR, 8760.0, places=1)

    def test_hours_per_year_equals_365_times_24(self):
        self.assertAlmostEqual(_HOURS_PER_YEAR, 365.0 * 24.0, places=8)

    def test_weekly_epochs_per_year(self):
        # 52 weeks per year
        self.assertAlmostEqual(_HOURS_PER_YEAR / 168.0, 52.142857, places=3)

    def test_daily_epochs_per_year(self):
        self.assertAlmostEqual(_HOURS_PER_YEAR / 24.0, 365.0, places=4)


# ===========================================================================
# 12. End-to-end scenario tests  (12 tests)
# ===========================================================================
class TestE2EScenarios(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "e2e_epoch.json")

    def test_early_entry_best_score(self):
        r_early = analyze(**_base_kwargs(hours_elapsed_in_epoch=0.0))
        r_late = analyze(**_base_kwargs(hours_elapsed_in_epoch=160.0))
        self.assertGreater(r_early["entry_timing_score"],
                           r_late["entry_timing_score"])

    def test_early_entry_label(self):
        r = analyze(**_base_kwargs(hours_elapsed_in_epoch=5.0))
        self.assertEqual(r["timing_label"], "PERFECT_ENTRY")

    def test_late_epoch_entry_label(self):
        r = analyze(**_base_kwargs(hours_elapsed_in_epoch=155.0,
                                   epoch_duration_hours=168))
        self.assertEqual(r["timing_label"], "EPOCH_ALMOST_DONE")

    def test_small_stake_in_large_pool(self):
        r = analyze(**_base_kwargs(my_stake_usd=1_000.0,
                                   total_staked_usd=100_000_000.0))
        self.assertLess(r["my_share_pct"], 0.01)
        self.assertGreater(r["my_share_pct"], 0.0)

    def test_large_stake_dominates_pool(self):
        r = analyze(**_base_kwargs(my_stake_usd=10_000_000.0,
                                   total_staked_usd=1_000_000.0))
        self.assertGreater(r["my_share_pct"], 90.0)

    def test_log_and_reload(self):
        r = analyze(**_base_kwargs())
        log_result(r, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["timing_label"], r["timing_label"])

    def test_arbitrage_opportunity_high_net_reward(self):
        # Large stake, early entry, high reward, low costs → positive net
        r = analyze(**_base_kwargs(
            hours_elapsed_in_epoch=0.0,
            reward_per_epoch_usd=1_000_000.0,
            my_stake_usd=10_000_000.0,
            total_staked_usd=10_000_000.0,
            entry_cost_usd=50.0,
            exit_cost_usd=50.0,
        ))
        self.assertGreater(r["net_reward_usd"], 10_000.0)
        self.assertEqual(r["timing_label"], "PERFECT_ENTRY")

    def test_epoch_almost_done_low_score(self):
        r = analyze(**_base_kwargs(hours_elapsed_in_epoch=160.0,
                                   epoch_duration_hours=168))
        self.assertEqual(r["timing_label"], "EPOCH_ALMOST_DONE")
        self.assertLess(r["entry_timing_score"], 10)

    def test_neutral_timing_mid_epoch(self):
        r = analyze(**_base_kwargs(hours_elapsed_in_epoch=70.0,
                                   epoch_duration_hours=168))
        self.assertEqual(r["timing_label"], "NEUTRAL_TIMING")

    def test_zero_reward_zero_apy(self):
        r = analyze(**_base_kwargs(reward_per_epoch_usd=0.0))
        self.assertAlmostEqual(r["annualized_reward_apy_pct"], 0.0, places=6)
        self.assertAlmostEqual(r["expected_epoch_reward_usd"], 0.0, places=6)

    def test_log_round_trip_multiple_protocols(self):
        protocols = ["Aave V3", "Compound V3", "Morpho", "Yearn V3", "Euler V2"]
        for p in protocols:
            r = analyze(**_base_kwargs(protocol_name=p))
            log_result(r, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)
        stored_names = [e["protocol_name"] for e in data]
        self.assertEqual(stored_names, protocols)

    def test_epoch_duration_1_hour_extreme(self):
        r = analyze(**_base_kwargs(epoch_duration_hours=1,
                                   hours_elapsed_in_epoch=0.0))
        self.assertAlmostEqual(r["epoch_progress_pct"], 0.0, places=6)
        self.assertAlmostEqual(r["epochs_per_year"], _HOURS_PER_YEAR, places=4)


if __name__ == "__main__":
    unittest.main()
