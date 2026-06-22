"""
MP-786 — unit tests for StakingRewardTracker.
≥65 tests, unittest only, stdlib only.
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure project root is on path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from spa_core.analytics.staking_reward_tracker import (
    StakingRewardTracker,
    _effective_apy,
    _lock_attractiveness,
    _COMPOUND_FREQ,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_data(**kwargs):
    base = {
        "protocol": "TestProto",
        "staked_amount_usd": 10_000.0,
        "reward_rate_daily_pct": 0.05,
        "compound_frequency": "DAILY",
        "lock_period_days": 30,
        "early_exit_penalty_pct": 2.0,
    }
    base.update(kwargs)
    return base


def _tracker(tmp_dir):
    return StakingRewardTracker(data_dir=tmp_dir)


# ---------------------------------------------------------------------------
# 1. _effective_apy — NONE (simple interest)
# ---------------------------------------------------------------------------

class TestEffectiveApyNone(unittest.TestCase):

    def test_none_simple_rate_basic(self):
        # NONE → simple annual rate = daily_pct/100 * 365
        result = _effective_apy(0.1, "NONE")
        self.assertAlmostEqual(result, 0.365, places=6)

    def test_none_zero_rate(self):
        result = _effective_apy(0.0, "NONE")
        self.assertAlmostEqual(result, 0.0, places=10)

    def test_none_large_rate(self):
        result = _effective_apy(1.0, "NONE")
        self.assertAlmostEqual(result, 3.65, places=6)

    def test_none_case_insensitive(self):
        result = _effective_apy(0.1, "none")
        self.assertAlmostEqual(result, 0.365, places=6)


# ---------------------------------------------------------------------------
# 2. _effective_apy — DAILY compounding
# ---------------------------------------------------------------------------

class TestEffectiveApyDaily(unittest.TestCase):

    def test_daily_greater_than_none(self):
        daily = _effective_apy(0.1, "DAILY")
        none_ = _effective_apy(0.1, "NONE")
        self.assertGreater(daily, none_)

    def test_daily_compounding_formula(self):
        # daily_pct=0.1 → annual_rate=0.365, freq=365
        # (1 + 0.365/365)^365 - 1
        daily_pct = 0.1
        annual = daily_pct / 100.0 * 365
        expected = (1 + annual / 365) ** 365 - 1
        self.assertAlmostEqual(_effective_apy(daily_pct, "DAILY"), expected, places=10)

    def test_daily_zero_rate(self):
        self.assertAlmostEqual(_effective_apy(0.0, "DAILY"), 0.0, places=10)

    def test_daily_case_upper(self):
        r1 = _effective_apy(0.05, "DAILY")
        r2 = _effective_apy(0.05, "daily")
        self.assertAlmostEqual(r1, r2, places=10)


# ---------------------------------------------------------------------------
# 3. _effective_apy — WEEKLY compounding
# ---------------------------------------------------------------------------

class TestEffectiveApyWeekly(unittest.TestCase):

    def test_weekly_formula(self):
        pct = 0.1
        annual = pct / 100.0 * 365
        expected = (1 + annual / 52) ** 52 - 1
        self.assertAlmostEqual(_effective_apy(pct, "WEEKLY"), expected, places=10)

    def test_weekly_between_none_and_daily(self):
        pct = 0.1
        none_ = _effective_apy(pct, "NONE")
        weekly = _effective_apy(pct, "WEEKLY")
        daily = _effective_apy(pct, "DAILY")
        self.assertGreater(weekly, none_)
        self.assertLess(weekly, daily)

    def test_weekly_zero(self):
        self.assertAlmostEqual(_effective_apy(0.0, "WEEKLY"), 0.0, places=10)


# ---------------------------------------------------------------------------
# 4. _effective_apy — MONTHLY compounding
# ---------------------------------------------------------------------------

class TestEffectiveApyMonthly(unittest.TestCase):

    def test_monthly_formula(self):
        pct = 0.1
        annual = pct / 100.0 * 365
        expected = (1 + annual / 12) ** 12 - 1
        self.assertAlmostEqual(_effective_apy(pct, "MONTHLY"), expected, places=10)

    def test_monthly_ordering(self):
        pct = 0.1
        none_  = _effective_apy(pct, "NONE")
        monthly = _effective_apy(pct, "MONTHLY")
        weekly  = _effective_apy(pct, "WEEKLY")
        daily   = _effective_apy(pct, "DAILY")
        self.assertLess(none_, monthly)
        self.assertLess(monthly, weekly)
        self.assertLess(weekly, daily)

    def test_monthly_zero(self):
        self.assertAlmostEqual(_effective_apy(0.0, "MONTHLY"), 0.0, places=10)


# ---------------------------------------------------------------------------
# 5. _lock_attractiveness
# ---------------------------------------------------------------------------

class TestLockAttractiveness(unittest.TestCase):

    def test_range_always_0_to_100(self):
        score = _lock_attractiveness(0.5, 0.0, 0)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_perfect_score_conditions(self):
        # Very high APY (>=30%), zero penalty, zero lock
        score = _lock_attractiveness(0.50, 0.0, 0)
        self.assertAlmostEqual(score, 100.0, places=2)

    def test_worst_score_zero_apy_full_penalty_long_lock(self):
        score = _lock_attractiveness(0.0, 100.0, 999)
        self.assertAlmostEqual(score, 0.0, places=4)

    def test_higher_apy_better_score(self):
        low  = _lock_attractiveness(0.05, 5.0, 60)
        high = _lock_attractiveness(0.25, 5.0, 60)
        self.assertGreater(high, low)

    def test_lower_penalty_better_score(self):
        s_high_pen = _lock_attractiveness(0.10, 50.0, 30)
        s_low_pen  = _lock_attractiveness(0.10,  0.0, 30)
        self.assertGreater(s_low_pen, s_high_pen)

    def test_shorter_lock_better_score(self):
        s_long  = _lock_attractiveness(0.10, 2.0, 300)
        s_short = _lock_attractiveness(0.10, 2.0, 10)
        self.assertGreater(s_short, s_long)

    def test_zero_apy_still_bounded(self):
        score = _lock_attractiveness(0.0, 0.0, 0)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_exact_30pct_apy_gives_50_apy_pts(self):
        # With 0% penalty, 0 lock → max = 50 (APY) + 30 (penalty) + 20 (lock) = 100
        score = _lock_attractiveness(0.30, 0.0, 0)
        self.assertAlmostEqual(score, 100.0, places=2)

    def test_half_apy_half_max(self):
        # APY=0.15 (50% of 30%) → apy_pts = 25, penalty=0 → 30, lock=0 → 20  total=75
        score = _lock_attractiveness(0.15, 0.0, 0)
        self.assertAlmostEqual(score, 75.0, places=2)


# ---------------------------------------------------------------------------
# 6. track() — return structure
# ---------------------------------------------------------------------------

class TestTrackStructure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _tracker(self.tmp)
        self.data = _make_data()

    def test_returns_dict(self):
        result = self.tracker.track(self.data)
        self.assertIsInstance(result, dict)

    def test_has_all_required_keys(self):
        result = self.tracker.track(self.data)
        for key in [
            "protocol", "effective_apy", "effective_apy_pct",
            "total_rewards_30d", "total_rewards_holding",
            "exit_cost_usd", "net_apy_after_exit_cost",
            "net_apy_after_exit_cost_pct", "lock_attractiveness_score",
            "within_lock_period", "computed_at",
        ]:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_protocol_preserved(self):
        result = self.tracker.track(self.data)
        self.assertEqual(result["protocol"], "TestProto")

    def test_staked_amount_preserved(self):
        result = self.tracker.track(self.data)
        self.assertAlmostEqual(result["staked_amount_usd"], 10_000.0)

    def test_computed_at_is_iso_string(self):
        result = self.tracker.track(self.data)
        ts = result["computed_at"]
        self.assertIsInstance(ts, str)
        self.assertIn("T", ts)

    def test_effective_apy_positive(self):
        result = self.tracker.track(self.data)
        self.assertGreater(result["effective_apy"], 0)

    def test_effective_apy_pct_equals_100x_apy(self):
        result = self.tracker.track(self.data)
        self.assertAlmostEqual(
            result["effective_apy_pct"],
            result["effective_apy"] * 100,
            places=3,
        )


# ---------------------------------------------------------------------------
# 7. track() — total_rewards_30d
# ---------------------------------------------------------------------------

class TestTotalRewards30d(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _tracker(self.tmp)

    def test_30d_rewards_formula(self):
        data = _make_data(staked_amount_usd=10_000, reward_rate_daily_pct=0.1,
                          compound_frequency="NONE")
        result = self.tracker.track(data, holding_days=30)
        eff_apy = _effective_apy(0.1, "NONE")
        expected = 10_000 * eff_apy / 365 * 30
        self.assertAlmostEqual(result["total_rewards_30d"], expected, places=2)

    def test_holding_days_effect(self):
        # total_rewards_30d is always a fixed 30-day window, so identical across calls
        # total_rewards_holding varies with holding_days
        data = _make_data(lock_period_days=200)
        r30 = self.tracker.track(data, holding_days=30)
        r90 = self.tracker.track(data, holding_days=90)
        # fixed 30d window is identical
        self.assertAlmostEqual(r30["total_rewards_30d"], r90["total_rewards_30d"], places=6)
        # holding reward grows with holding_days
        self.assertLess(r30["total_rewards_holding"], r90["total_rewards_holding"])

    def test_larger_staked_more_rewards(self):
        r1 = self.tracker.track(_make_data(staked_amount_usd=1_000), holding_days=30)
        r2 = self.tracker.track(_make_data(staked_amount_usd=100_000), holding_days=30)
        self.assertLess(r1["total_rewards_30d"], r2["total_rewards_30d"])

    def test_higher_rate_more_rewards(self):
        r1 = self.tracker.track(_make_data(reward_rate_daily_pct=0.01), holding_days=30)
        r2 = self.tracker.track(_make_data(reward_rate_daily_pct=0.10), holding_days=30)
        self.assertLess(r1["total_rewards_30d"], r2["total_rewards_30d"])


# ---------------------------------------------------------------------------
# 8. track() — exit cost logic
# ---------------------------------------------------------------------------

class TestExitCost(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _tracker(self.tmp)

    def test_exit_cost_within_lock(self):
        # holding_days=20 < lock_period_days=90 → cost applies
        data = _make_data(staked_amount_usd=10_000, early_exit_penalty_pct=5.0,
                          lock_period_days=90)
        result = self.tracker.track(data, holding_days=20)
        self.assertTrue(result["within_lock_period"])
        self.assertAlmostEqual(result["exit_cost_usd"], 500.0, places=4)

    def test_exit_cost_after_lock(self):
        # holding_days=100 >= lock_period_days=90 → no cost
        data = _make_data(staked_amount_usd=10_000, early_exit_penalty_pct=5.0,
                          lock_period_days=90)
        result = self.tracker.track(data, holding_days=100)
        self.assertFalse(result["within_lock_period"])
        self.assertAlmostEqual(result["exit_cost_usd"], 0.0, places=4)

    def test_exit_cost_exactly_at_lock_boundary(self):
        # holding_days == lock_period_days → not within lock
        data = _make_data(staked_amount_usd=10_000, early_exit_penalty_pct=5.0,
                          lock_period_days=30)
        result = self.tracker.track(data, holding_days=30)
        self.assertFalse(result["within_lock_period"])
        self.assertAlmostEqual(result["exit_cost_usd"], 0.0, places=4)

    def test_zero_penalty(self):
        data = _make_data(early_exit_penalty_pct=0.0, lock_period_days=365)
        result = self.tracker.track(data, holding_days=10)
        self.assertAlmostEqual(result["exit_cost_usd"], 0.0, places=4)

    def test_zero_lock_period_no_exit_cost(self):
        # lock_period_days=0 → holding_days >= 0 → not within lock
        data = _make_data(early_exit_penalty_pct=10.0, lock_period_days=0)
        result = self.tracker.track(data, holding_days=0)
        self.assertFalse(result["within_lock_period"])
        self.assertAlmostEqual(result["exit_cost_usd"], 0.0, places=4)

    def test_net_apy_lower_when_within_lock(self):
        data = _make_data(staked_amount_usd=10_000, early_exit_penalty_pct=50.0,
                          lock_period_days=365)
        result = self.tracker.track(data, holding_days=10)
        self.assertLess(result["net_apy_after_exit_cost"], result["effective_apy"])

    def test_net_apy_equals_effective_apy_outside_lock(self):
        data = _make_data(staked_amount_usd=10_000, early_exit_penalty_pct=50.0,
                          lock_period_days=30)
        result = self.tracker.track(data, holding_days=60)
        self.assertAlmostEqual(
            result["net_apy_after_exit_cost"],
            result["effective_apy"],
            places=6,
        )

    def test_net_apy_pct_equals_100x_net(self):
        data = _make_data(lock_period_days=90)
        result = self.tracker.track(data, holding_days=30)
        self.assertAlmostEqual(
            result["net_apy_after_exit_cost_pct"],
            result["net_apy_after_exit_cost"] * 100,
            places=3,
        )


# ---------------------------------------------------------------------------
# 9. get_effective_apy() and get_exit_analysis()
# ---------------------------------------------------------------------------

class TestGetters(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _tracker(self.tmp)

    def test_get_effective_apy_none_before_track(self):
        self.assertIsNone(self.tracker.get_effective_apy())

    def test_get_exit_analysis_none_before_track(self):
        self.assertIsNone(self.tracker.get_exit_analysis())

    def test_get_effective_apy_keys(self):
        self.tracker.track(_make_data())
        apy = self.tracker.get_effective_apy()
        for k in ("protocol", "compound_frequency", "reward_rate_daily_pct",
                   "effective_apy", "effective_apy_pct"):
            self.assertIn(k, apy)

    def test_get_exit_analysis_keys(self):
        self.tracker.track(_make_data())
        ea = self.tracker.get_exit_analysis()
        for k in ("protocol", "staked_amount_usd", "holding_days", "lock_period_days",
                   "within_lock_period", "early_exit_penalty_pct", "exit_cost_usd",
                   "effective_apy_pct", "net_apy_after_exit_cost_pct",
                   "lock_attractiveness_score"):
            self.assertIn(k, ea)

    def test_get_effective_apy_reflects_latest_track(self):
        self.tracker.track(_make_data(reward_rate_daily_pct=0.01))
        first = self.tracker.get_effective_apy()["effective_apy"]
        self.tracker.track(_make_data(reward_rate_daily_pct=0.10))
        second = self.tracker.get_effective_apy()["effective_apy"]
        self.assertLess(first, second)

    def test_get_exit_analysis_within_lock_flag(self):
        self.tracker.track(_make_data(lock_period_days=90), holding_days=10)
        ea = self.tracker.get_exit_analysis()
        self.assertTrue(ea["within_lock_period"])

    def test_get_exit_analysis_outside_lock_flag(self):
        self.tracker.track(_make_data(lock_period_days=10), holding_days=60)
        ea = self.tracker.get_exit_analysis()
        self.assertFalse(ea["within_lock_period"])


# ---------------------------------------------------------------------------
# 10. Validation errors
# ---------------------------------------------------------------------------

class TestValidation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _tracker(self.tmp)

    def test_missing_protocol(self):
        data = _make_data()
        del data["protocol"]
        with self.assertRaises(ValueError):
            self.tracker.track(data)

    def test_missing_staked_amount(self):
        data = _make_data()
        del data["staked_amount_usd"]
        with self.assertRaises(ValueError):
            self.tracker.track(data)

    def test_missing_reward_rate(self):
        data = _make_data()
        del data["reward_rate_daily_pct"]
        with self.assertRaises(ValueError):
            self.tracker.track(data)

    def test_missing_compound_frequency(self):
        data = _make_data()
        del data["compound_frequency"]
        with self.assertRaises(ValueError):
            self.tracker.track(data)

    def test_missing_lock_period(self):
        data = _make_data()
        del data["lock_period_days"]
        with self.assertRaises(ValueError):
            self.tracker.track(data)

    def test_missing_penalty(self):
        data = _make_data()
        del data["early_exit_penalty_pct"]
        with self.assertRaises(ValueError):
            self.tracker.track(data)

    def test_invalid_compound_frequency(self):
        with self.assertRaises(ValueError):
            self.tracker.track(_make_data(compound_frequency="QUARTERLY"))

    def test_zero_staked_amount_raises(self):
        with self.assertRaises(ValueError):
            self.tracker.track(_make_data(staked_amount_usd=0))

    def test_negative_staked_raises(self):
        with self.assertRaises(ValueError):
            self.tracker.track(_make_data(staked_amount_usd=-100))

    def test_negative_rate_raises(self):
        with self.assertRaises(ValueError):
            self.tracker.track(_make_data(reward_rate_daily_pct=-0.01))

    def test_penalty_above_100_raises(self):
        with self.assertRaises(ValueError):
            self.tracker.track(_make_data(early_exit_penalty_pct=101))

    def test_negative_penalty_raises(self):
        with self.assertRaises(ValueError):
            self.tracker.track(_make_data(early_exit_penalty_pct=-1))

    def test_negative_lock_raises(self):
        with self.assertRaises(ValueError):
            self.tracker.track(_make_data(lock_period_days=-1))

    def test_valid_zero_rate_no_error(self):
        result = self.tracker.track(_make_data(reward_rate_daily_pct=0.0))
        self.assertAlmostEqual(result["effective_apy"], 0.0)

    def test_valid_zero_penalty_no_error(self):
        result = self.tracker.track(_make_data(early_exit_penalty_pct=0.0))
        self.assertIsNotNone(result)

    def test_valid_zero_lock_no_error(self):
        result = self.tracker.track(_make_data(lock_period_days=0))
        self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# 11. Ring-buffer log behaviour
# ---------------------------------------------------------------------------

class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _tracker(self.tmp)

    def test_log_file_created_on_track(self):
        self.tracker.track(_make_data())
        log_path = os.path.join(self.tmp, "staking_reward_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_log_is_valid_json_list(self):
        self.tracker.track(_make_data())
        log_path = os.path.join(self.tmp, "staking_reward_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_grows_with_each_track(self):
        self.tracker.track(_make_data())
        self.tracker.track(_make_data())
        log = self.tracker.get_log()
        self.assertEqual(len(log), 2)

    def test_ring_buffer_cap_at_100(self):
        for i in range(110):
            self.tracker.track(_make_data(protocol=f"Proto{i}"))
        log = self.tracker.get_log()
        self.assertEqual(len(log), 100)

    def test_ring_buffer_keeps_most_recent(self):
        for i in range(105):
            self.tracker.track(_make_data(protocol=f"Proto{i}"))
        log = self.tracker.get_log()
        # Last entry should be the 105th (Proto104)
        self.assertEqual(log[-1]["protocol"], "Proto104")

    def test_get_log_returns_list(self):
        log = self.tracker.get_log()
        self.assertIsInstance(log, list)

    def test_get_log_empty_initially(self):
        log = self.tracker.get_log()
        self.assertEqual(log, [])


# ---------------------------------------------------------------------------
# 12. Compounding frequency values
# ---------------------------------------------------------------------------

class TestCompoundFreqValues(unittest.TestCase):

    def test_daily_freq_is_365(self):
        self.assertEqual(_COMPOUND_FREQ["DAILY"], 365)

    def test_weekly_freq_is_52(self):
        self.assertEqual(_COMPOUND_FREQ["WEEKLY"], 52)

    def test_monthly_freq_is_12(self):
        self.assertEqual(_COMPOUND_FREQ["MONTHLY"], 12)

    def test_none_freq_is_1(self):
        self.assertEqual(_COMPOUND_FREQ["NONE"], 1)


# ---------------------------------------------------------------------------
# 13. Additional numeric precision / edge cases
# ---------------------------------------------------------------------------

class TestNumericEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = _tracker(self.tmp)

    def test_very_small_rate(self):
        data = _make_data(reward_rate_daily_pct=0.001, compound_frequency="DAILY")
        result = self.tracker.track(data)
        self.assertGreater(result["effective_apy"], 0)

    def test_high_staked_amount(self):
        data = _make_data(staked_amount_usd=100_000_000)
        result = self.tracker.track(data)
        self.assertGreater(result["total_rewards_30d"], 0)

    def test_100_pct_penalty_within_lock(self):
        data = _make_data(staked_amount_usd=10_000, early_exit_penalty_pct=100.0,
                          lock_period_days=365)
        result = self.tracker.track(data, holding_days=1)
        self.assertAlmostEqual(result["exit_cost_usd"], 10_000.0, places=2)

    def test_lock_attractiveness_score_in_range(self):
        for pct in [0.0, 0.01, 0.10, 0.30, 0.50]:
            for pen in [0, 10, 50, 100]:
                for lock in [0, 30, 180, 365]:
                    score = _lock_attractiveness(pct, float(pen), lock)
                    self.assertGreaterEqual(score, 0.0)
                    self.assertLessEqual(score, 100.0)

    def test_effective_apy_all_frequencies_positive_rate(self):
        for freq in ["DAILY", "WEEKLY", "MONTHLY", "NONE"]:
            apy = _effective_apy(0.05, freq)
            self.assertGreater(apy, 0.0)

    def test_effective_apy_increases_with_frequency(self):
        pct = 0.1
        apys = {f: _effective_apy(pct, f) for f in ["NONE", "MONTHLY", "WEEKLY", "DAILY"]}
        self.assertLessEqual(apys["NONE"], apys["MONTHLY"])
        self.assertLessEqual(apys["MONTHLY"], apys["WEEKLY"])
        self.assertLessEqual(apys["WEEKLY"], apys["DAILY"])

    def test_track_returns_holding_days_in_result(self):
        data = _make_data(lock_period_days=200)
        result = self.tracker.track(data, holding_days=45)
        self.assertEqual(result["holding_days"], 45)

    def test_multiple_protocols_tracked(self):
        for proto in ["Lido", "Rocket Pool", "Frax"]:
            self.tracker.track(_make_data(protocol=proto))
        log = self.tracker.get_log()
        protos = [e["protocol"] for e in log]
        self.assertIn("Lido", protos)
        self.assertIn("Rocket Pool", protos)
        self.assertIn("Frax", protos)

    def test_all_compound_modes_accepted(self):
        for freq in ["DAILY", "WEEKLY", "MONTHLY", "NONE"]:
            data = _make_data(compound_frequency=freq)
            result = self.tracker.track(data)
            self.assertEqual(result["compound_frequency"], freq.upper())


if __name__ == "__main__":
    unittest.main(verbosity=2)
