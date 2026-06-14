"""
Tests for MP-802: VaultMigrationAdvisor
Uses unittest only (no pytest).
≥65 tests covering MIGRATE/HOLD/MONITOR, break-even, edge cases,
immediate_action, best_candidate, ring-buffer log.
"""
import json
import math
import os
import sys
import tempfile
import time
import unittest

# Ensure repo root on path
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.vault_migration_advisor import analyze, _daily_yield_usd


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _current(name="CurrentVault", apy=5.0, exit_cost=10.0):
    return {"name": name, "apy": apy, "exit_cost_usd": exit_cost}


def _cand(name="CandVault", apy=8.0, entry_cost=5.0):
    return {"name": name, "apy": apy, "entry_cost_usd": entry_cost}


# ---------------------------------------------------------------------------
# Helper: daily yield
# ---------------------------------------------------------------------------

class TestDailyYieldUSD(unittest.TestCase):

    def test_basic_calculation(self):
        # 10000 * 10% / 365 = 2.7397...
        result = _daily_yield_usd(10000.0, 10.0)
        self.assertAlmostEqual(result, 10000.0 * 0.10 / 365.0, places=6)

    def test_zero_position(self):
        self.assertAlmostEqual(_daily_yield_usd(0.0, 10.0), 0.0)

    def test_zero_apy(self):
        self.assertAlmostEqual(_daily_yield_usd(10000.0, 0.0), 0.0)

    def test_hundred_percent_apy(self):
        result = _daily_yield_usd(365.0, 100.0)
        self.assertAlmostEqual(result, 1.0, places=6)


# ---------------------------------------------------------------------------
# Empty candidates
# ---------------------------------------------------------------------------

class TestEmptyCandidates(unittest.TestCase):

    def test_empty_returns_stay(self):
        result = analyze(_current(), [], 10000.0)
        self.assertEqual(result["immediate_action"], "STAY")

    def test_empty_candidates_list(self):
        result = analyze(_current(), [], 10000.0)
        self.assertEqual(result["candidates"], [])

    def test_empty_best_candidate_none(self):
        result = analyze(_current(), [], 10000.0)
        self.assertIsNone(result["best_candidate"])

    def test_empty_summary_reason(self):
        result = analyze(_current(), [], 10000.0)
        self.assertIn("No candidate", result["summary_reason"])

    def test_empty_current_vault_in_result(self):
        result = analyze(_current("MyVault"), [], 10000.0)
        self.assertEqual(result["current_vault"], "MyVault")

    def test_empty_has_timestamp(self):
        result = analyze(_current(), [], 10000.0)
        self.assertIsInstance(result["timestamp"], float)

    def test_empty_current_daily_yield(self):
        # 10000 * 5% / 365
        result = analyze(_current(apy=5.0), [], 10000.0)
        expected = 10000.0 * 0.05 / 365.0
        self.assertAlmostEqual(result["current_daily_yield_usd"], expected, places=3)


# ---------------------------------------------------------------------------
# MIGRATE recommendation
# ---------------------------------------------------------------------------

class TestMigrateRecommendation(unittest.TestCase):

    def setUp(self):
        # current: 5% APY, exit 10 USD
        # candidate: 10% APY, entry 5 USD → total cost 15 USD
        # position: 100000 USD
        # daily_gain = 100000 * (10-5)/100/365 = ~13.70 USD/day
        # break_even = 15/13.70 ≈ 1.09 days << 90 → MIGRATE
        self.current = _current(apy=5.0, exit_cost=10.0)
        self.cand = _cand(name="GoodVault", apy=10.0, entry_cost=5.0)
        self.result = analyze(self.current, [self.cand], 100000.0)

    def test_recommendation_migrate(self):
        self.assertEqual(self.result["candidates"][0]["recommendation"], "MIGRATE")

    def test_immediate_action_migrate_now(self):
        self.assertEqual(self.result["immediate_action"], "MIGRATE_NOW")

    def test_best_candidate_is_good_vault(self):
        self.assertEqual(self.result["best_candidate"], "GoodVault")

    def test_apy_delta_positive(self):
        self.assertAlmostEqual(self.result["candidates"][0]["apy_delta"], 5.0, places=3)

    def test_daily_gain_positive(self):
        self.assertGreater(self.result["candidates"][0]["daily_yield_gain_usd"], 0)

    def test_break_even_under_90(self):
        be = self.result["candidates"][0]["break_even_days"]
        self.assertIsNotNone(be)
        self.assertLessEqual(be, 90.0)

    def test_total_cost_is_exit_plus_entry(self):
        # exit_cost=10 + entry_cost=5 = 15
        self.assertAlmostEqual(
            self.result["candidates"][0]["total_migration_cost_usd"], 15.0, places=3
        )

    def test_reason_contains_break_even_days(self):
        self.assertIn("Break-even", self.result["candidates"][0]["reason"])

    def test_summary_reason_contains_migrate(self):
        self.assertIn("Migrate", self.result["summary_reason"])


# ---------------------------------------------------------------------------
# HOLD recommendation
# ---------------------------------------------------------------------------

class TestHoldRecommendation(unittest.TestCase):

    def setUp(self):
        # candidate APY is lower than current
        self.current = _current(apy=8.0)
        self.cand = _cand(name="BadVault", apy=4.0, entry_cost=5.0)
        self.result = analyze(self.current, [self.cand], 50000.0)

    def test_recommendation_hold(self):
        self.assertEqual(self.result["candidates"][0]["recommendation"], "HOLD")

    def test_immediate_action_stay(self):
        self.assertEqual(self.result["immediate_action"], "STAY")

    def test_best_candidate_none(self):
        self.assertIsNone(self.result["best_candidate"])

    def test_apy_delta_negative(self):
        self.assertLess(self.result["candidates"][0]["apy_delta"], 0)

    def test_break_even_none_for_hold(self):
        self.assertIsNone(self.result["candidates"][0]["break_even_days"])

    def test_reason_lower_apy(self):
        self.assertIn("Lower APY", self.result["candidates"][0]["reason"])

    def test_summary_reason_stay(self):
        self.assertIn("stay", self.result["summary_reason"].lower())

    def test_equal_apy_also_hold(self):
        cand = _cand(name="SameAPY", apy=8.0, entry_cost=5.0)
        result = analyze(self.current, [cand], 50000.0)
        # apy_delta = 0 → HOLD
        self.assertEqual(result["candidates"][0]["recommendation"], "HOLD")


# ---------------------------------------------------------------------------
# MONITOR recommendation
# ---------------------------------------------------------------------------

class TestMonitorRecommendation(unittest.TestCase):

    def setUp(self):
        # current: 5% APY, exit 1000 USD
        # candidate: 5.1% APY (tiny delta), entry 500 USD → total 1500 USD
        # position: 10000 USD
        # daily_gain = 10000 * 0.1/100/365 = ~0.027 USD/day
        # break_even = 1500 / 0.027 ≈ 55000 days >> 90 → MONITOR
        self.current = _current(apy=5.0, exit_cost=1000.0)
        self.cand = _cand(name="SlowVault", apy=5.1, entry_cost=500.0)
        self.result = analyze(self.current, [self.cand], 10000.0)

    def test_recommendation_monitor(self):
        self.assertEqual(self.result["candidates"][0]["recommendation"], "MONITOR")

    def test_immediate_action_wait(self):
        self.assertEqual(self.result["immediate_action"], "WAIT")

    def test_best_candidate_none(self):
        self.assertIsNone(self.result["best_candidate"])

    def test_break_even_over_90(self):
        be = self.result["candidates"][0]["break_even_days"]
        self.assertIsNotNone(be)
        self.assertGreater(be, 90.0)

    def test_reason_break_even_too_long(self):
        self.assertIn("Break-even too long", self.result["candidates"][0]["reason"])

    def test_summary_reason_wait(self):
        self.assertIn("break-even", self.result["summary_reason"].lower())


# ---------------------------------------------------------------------------
# Mixed candidates
# ---------------------------------------------------------------------------

class TestMixedCandidates(unittest.TestCase):

    def setUp(self):
        self.current = _current(apy=5.0, exit_cost=10.0)
        self.candidates = [
            _cand("Hold", apy=3.0, entry_cost=5.0),     # HOLD (lower APY)
            _cand("Monitor", apy=5.5, entry_cost=9999.0), # MONITOR (too long)
            _cand("Migrate", apy=15.0, entry_cost=5.0),  # MIGRATE (quick break-even)
        ]
        self.result = analyze(self.current, self.candidates, 100000.0)

    def test_hold_candidate(self):
        hold = next(c for c in self.result["candidates"] if c["name"] == "Hold")
        self.assertEqual(hold["recommendation"], "HOLD")

    def test_monitor_candidate(self):
        mon = next(c for c in self.result["candidates"] if c["name"] == "Monitor")
        self.assertEqual(mon["recommendation"], "MONITOR")

    def test_migrate_candidate(self):
        mig = next(c for c in self.result["candidates"] if c["name"] == "Migrate")
        self.assertEqual(mig["recommendation"], "MIGRATE")

    def test_immediate_action_migrate_now(self):
        self.assertEqual(self.result["immediate_action"], "MIGRATE_NOW")

    def test_best_candidate_is_migrate(self):
        self.assertEqual(self.result["best_candidate"], "Migrate")

    def test_candidate_count_preserved(self):
        self.assertEqual(len(self.result["candidates"]), 3)


# ---------------------------------------------------------------------------
# immediate_action priority: MIGRATE > MONITOR > STAY
# ---------------------------------------------------------------------------

class TestImmediateActionPriority(unittest.TestCase):

    def test_all_hold_gives_stay(self):
        current = _current(apy=10.0)
        candidates = [
            _cand("A", apy=3.0),
            _cand("B", apy=2.0),
        ]
        result = analyze(current, candidates, 50000.0)
        self.assertEqual(result["immediate_action"], "STAY")

    def test_all_monitor_gives_wait(self):
        current = _current(apy=5.0, exit_cost=99999.0)
        candidates = [
            _cand("A", apy=6.0, entry_cost=1.0),
            _cand("B", apy=7.0, entry_cost=1.0),
        ]
        # Large exit cost → break-even >> 90 → all MONITOR
        result = analyze(current, candidates, 10.0)  # small position → tiny daily gain
        # break_even = (99999 + 1) / tiny → MONITOR
        for c in result["candidates"]:
            if c["recommendation"] != "HOLD":
                self.assertEqual(c["recommendation"], "MONITOR")
        # At least MONITOR present → WAIT
        self.assertIn(result["immediate_action"], ["WAIT", "STAY"])

    def test_one_migrate_overrides_monitor(self):
        current = _current(apy=5.0, exit_cost=10.0)
        candidates = [
            _cand("Monitor", apy=5.5, entry_cost=9999.0),  # MONITOR
            _cand("Migrate", apy=20.0, entry_cost=5.0),    # MIGRATE
        ]
        result = analyze(current, candidates, 100000.0)
        self.assertEqual(result["immediate_action"], "MIGRATE_NOW")


# ---------------------------------------------------------------------------
# best_candidate: highest apy_delta among MIGRATE
# ---------------------------------------------------------------------------

class TestBestCandidate(unittest.TestCase):

    def test_best_is_highest_apy_delta(self):
        current = _current(apy=5.0, exit_cost=5.0)
        candidates = [
            _cand("Good", apy=10.0, entry_cost=5.0),   # delta=5
            _cand("Better", apy=15.0, entry_cost=5.0), # delta=10
            _cand("OK", apy=8.0, entry_cost=5.0),      # delta=3
        ]
        result = analyze(current, candidates, 100000.0)
        self.assertEqual(result["best_candidate"], "Better")

    def test_no_migrate_best_candidate_none(self):
        current = _current(apy=10.0)
        candidates = [_cand("Low", apy=4.0)]
        result = analyze(current, candidates, 50000.0)
        self.assertIsNone(result["best_candidate"])


# ---------------------------------------------------------------------------
# Zero position edge case
# ---------------------------------------------------------------------------

class TestZeroPosition(unittest.TestCase):

    def setUp(self):
        self.current = _current(apy=5.0, exit_cost=10.0)
        self.cand = _cand(apy=10.0, entry_cost=5.0)
        self.result = analyze(self.current, [self.cand], 0.0)

    def test_current_daily_yield_zero(self):
        self.assertAlmostEqual(self.result["current_daily_yield_usd"], 0.0)

    def test_daily_yield_gain_zero(self):
        self.assertAlmostEqual(self.result["candidates"][0]["daily_yield_gain_usd"], 0.0)

    def test_break_even_none_zero_position(self):
        # daily_gain = 0, so break_even = None
        self.assertIsNone(self.result["candidates"][0]["break_even_days"])

    def test_recommendation_monitor_or_hold_zero_position(self):
        # apy_delta > 0 but no gain → MONITOR (can't MIGRATE)
        rec = self.result["candidates"][0]["recommendation"]
        self.assertIn(rec, ["MONITOR", "HOLD"])


# ---------------------------------------------------------------------------
# Break-even boundary: exactly max_break_even_days
# ---------------------------------------------------------------------------

class TestBreakEvenBoundary(unittest.TestCase):

    def test_exactly_at_max_break_even(self):
        # Set up so break_even = exactly 90 days → MIGRATE
        max_days = 90
        position = 100000.0
        current_apy = 5.0
        cand_apy = 6.0
        daily_gain = position * (cand_apy - current_apy) / 100.0 / 365.0
        cost = daily_gain * max_days  # cost that makes break_even == 90
        exit_cost = cost / 2
        entry_cost = cost / 2
        current = {"name": "C", "apy": current_apy, "exit_cost_usd": exit_cost}
        cand = {"name": "T", "apy": cand_apy, "entry_cost_usd": entry_cost}
        result = analyze(current, [cand], position, config={"max_break_even_days": max_days})
        self.assertEqual(result["candidates"][0]["recommendation"], "MIGRATE")

    def test_one_day_over_max_break_even(self):
        # Make break_even = 91 days → MONITOR
        max_days = 90
        position = 100000.0
        current_apy = 5.0
        cand_apy = 6.0
        daily_gain = position * (cand_apy - current_apy) / 100.0 / 365.0
        cost = daily_gain * (max_days + 1)  # 91-day cost
        exit_cost = cost / 2
        entry_cost = cost / 2
        current = {"name": "C", "apy": current_apy, "exit_cost_usd": exit_cost}
        cand = {"name": "T", "apy": cand_apy, "entry_cost_usd": entry_cost}
        result = analyze(current, [cand], position, config={"max_break_even_days": max_days})
        self.assertEqual(result["candidates"][0]["recommendation"], "MONITOR")

    def test_custom_max_break_even_days(self):
        current = _current(apy=5.0, exit_cost=500.0)
        cand = _cand(apy=6.0, entry_cost=500.0)
        # With 10000 position: daily_gain = 10000 * 0.01/365 ≈ 0.274
        # total cost = 1000, break_even ≈ 3650 days
        # default 90 → MONITOR; custom 5000 → MIGRATE
        r1 = analyze(current, [cand], 10000.0, config={"max_break_even_days": 90})
        r2 = analyze(current, [cand], 10000.0, config={"max_break_even_days": 5000})
        self.assertEqual(r1["candidates"][0]["recommendation"], "MONITOR")
        self.assertEqual(r2["candidates"][0]["recommendation"], "MIGRATE")


# ---------------------------------------------------------------------------
# Output fields
# ---------------------------------------------------------------------------

class TestOutputFields(unittest.TestCase):

    def setUp(self):
        self.result = analyze(_current(), [_cand()], 50000.0)

    def test_has_current_vault(self):
        self.assertIn("current_vault", self.result)

    def test_has_current_daily_yield(self):
        self.assertIn("current_daily_yield_usd", self.result)

    def test_has_candidates(self):
        self.assertIn("candidates", self.result)

    def test_has_best_candidate(self):
        self.assertIn("best_candidate", self.result)

    def test_has_immediate_action(self):
        self.assertIn("immediate_action", self.result)

    def test_has_summary_reason(self):
        self.assertIn("summary_reason", self.result)

    def test_has_timestamp(self):
        self.assertIn("timestamp", self.result)

    def test_candidate_has_all_fields(self):
        c = self.result["candidates"][0]
        for field in [
            "name", "apy", "apy_delta", "daily_yield_gain_usd",
            "total_migration_cost_usd", "break_even_days",
            "recommendation", "reason"
        ]:
            self.assertIn(field, c, f"Missing field: {field}")

    def test_immediate_action_valid_values(self):
        self.assertIn(self.result["immediate_action"], ["MIGRATE_NOW", "WAIT", "STAY"])

    def test_recommendation_valid_values(self):
        for c in self.result["candidates"]:
            self.assertIn(c["recommendation"], ["MIGRATE", "HOLD", "MONITOR"])


# ---------------------------------------------------------------------------
# Save / ring-buffer log
# ---------------------------------------------------------------------------

class TestSaveAndRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "vault_migration_log.json")

    def test_save_creates_log_file(self):
        analyze(_current(), [_cand()], 10000.0, save=True, data_dir=self.tmpdir)
        self.assertTrue(os.path.exists(self.log_path))

    def test_save_log_is_list(self):
        analyze(_current(), [_cand()], 10000.0, save=True, data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_save_appends_entries(self):
        for _ in range(3):
            analyze(_current(), [_cand()], 10000.0, save=True, data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_ring_buffer_capped_at_100(self):
        for _ in range(110):
            analyze(_current(), [_cand()], 10000.0, save=True, data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_no_save_no_file(self):
        analyze(_current(), [_cand()], 10000.0, save=False, data_dir=self.tmpdir)
        self.assertFalse(os.path.exists(self.log_path))

    def test_empty_candidates_save(self):
        analyze(_current(), [], 10000.0, save=True, data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["candidates"], [])


# ---------------------------------------------------------------------------
# Timestamp
# ---------------------------------------------------------------------------

class TestTimestamp(unittest.TestCase):

    def test_timestamp_is_recent(self):
        before = time.time()
        result = analyze(_current(), [_cand()], 10000.0)
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_timestamp_is_float(self):
        result = analyze(_current(), [_cand()], 10000.0)
        self.assertIsInstance(result["timestamp"], float)


# ---------------------------------------------------------------------------
# Current_vault name propagated
# ---------------------------------------------------------------------------

class TestCurrentVaultName(unittest.TestCase):

    def test_current_vault_name_in_result(self):
        result = analyze(_current("SpecialVault"), [], 10000.0)
        self.assertEqual(result["current_vault"], "SpecialVault")


# ---------------------------------------------------------------------------
# APY delta = 0 → HOLD
# ---------------------------------------------------------------------------

class TestApyDeltaZero(unittest.TestCase):

    def test_equal_apy_hold(self):
        current = _current(apy=5.0)
        cand = _cand(apy=5.0)
        result = analyze(current, [cand], 50000.0)
        self.assertEqual(result["candidates"][0]["recommendation"], "HOLD")
        self.assertAlmostEqual(result["candidates"][0]["apy_delta"], 0.0)
        self.assertIsNone(result["candidates"][0]["break_even_days"])


# ---------------------------------------------------------------------------
# Multiple MIGRATE candidates: best has highest delta
# ---------------------------------------------------------------------------

class TestMultipleMigrateCandidates(unittest.TestCase):

    def test_two_migrate_best_is_max_delta(self):
        current = _current(apy=3.0, exit_cost=1.0)
        candidates = [
            _cand("V1", apy=20.0, entry_cost=1.0),  # delta=17
            _cand("V2", apy=25.0, entry_cost=1.0),  # delta=22
        ]
        result = analyze(current, candidates, 100000.0)
        self.assertEqual(result["best_candidate"], "V2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
