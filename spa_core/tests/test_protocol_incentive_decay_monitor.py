"""
Tests for MP-821 ProtocolIncentiveDecayMonitor.
Run: python3 -m unittest spa_core.tests.test_protocol_incentive_decay_monitor -v
"""

import os
import sys
import tempfile
import time
import datetime
import unittest

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_incentive_decay_monitor import (
    analyze,
    log_result,
    _load_log,
    LOG_CAP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today():
    return datetime.date.today()


def _date_str(delta_days=0):
    return (_today() + datetime.timedelta(days=delta_days)).isoformat()


def _base_program(**overrides):
    prog = {
        "name": "Test Program",
        "start_date": _date_str(-30),
        "end_date": _date_str(60),
        "initial_apy": 20.0,
        "current_apy": 15.0,
        "token_budget_usd": 1_000_000.0,
        "spent_usd": 500_000.0,
        "daily_emission_usd": 5_000.0,
        "tvl_usd": 10_000_000.0,
    }
    prog.update(overrides)
    return prog


class TestReturnShape(unittest.TestCase):
    """Verify result keys and types are present."""

    def setUp(self):
        self.result = analyze("Aave V3", _base_program())

    def test_protocol_key(self):
        self.assertIn("protocol", self.result)

    def test_program_name_key(self):
        self.assertIn("program_name", self.result)

    def test_days_elapsed_key(self):
        self.assertIn("days_elapsed", self.result)

    def test_days_remaining_key(self):
        self.assertIn("days_remaining", self.result)

    def test_budget_remaining_key(self):
        self.assertIn("budget_remaining_usd", self.result)

    def test_budget_utilization_key(self):
        self.assertIn("budget_utilization_pct", self.result)

    def test_days_until_exhausted_key(self):
        self.assertIn("days_until_budget_exhausted", self.result)

    def test_apy_decay_pct_key(self):
        self.assertIn("apy_decay_pct", self.result)

    def test_effective_end_days_key(self):
        self.assertIn("effective_end_days", self.result)

    def test_projected_apy_30d_key(self):
        self.assertIn("projected_apy_30d", self.result)

    def test_status_key(self):
        self.assertIn("status", self.result)

    def test_exit_signal_key(self):
        self.assertIn("exit_signal", self.result)

    def test_risk_flags_key(self):
        self.assertIn("risk_flags", self.result)

    def test_recommendation_key(self):
        self.assertIn("recommendation", self.result)

    def test_timestamp_key(self):
        self.assertIn("timestamp", self.result)

    def test_protocol_value(self):
        self.assertEqual(self.result["protocol"], "Aave V3")

    def test_program_name_value(self):
        self.assertEqual(self.result["program_name"], "Test Program")

    def test_risk_flags_is_list(self):
        self.assertIsInstance(self.result["risk_flags"], list)

    def test_exit_signal_is_bool(self):
        self.assertIsInstance(self.result["exit_signal"], bool)

    def test_timestamp_is_float(self):
        self.assertIsInstance(self.result["timestamp"], float)


class TestDaysElapsed(unittest.TestCase):
    def test_30_days_ago(self):
        r = analyze("P", _base_program(start_date=_date_str(-30)))
        self.assertEqual(r["days_elapsed"], 30)

    def test_zero_days_when_today(self):
        r = analyze("P", _base_program(start_date=_date_str(0)))
        self.assertEqual(r["days_elapsed"], 0)

    def test_future_start_clamped_to_zero(self):
        r = analyze("P", _base_program(start_date=_date_str(10)))
        self.assertEqual(r["days_elapsed"], 0)

    def test_one_day_elapsed(self):
        r = analyze("P", _base_program(start_date=_date_str(-1)))
        self.assertEqual(r["days_elapsed"], 1)


class TestDaysRemaining(unittest.TestCase):
    def test_60_days_future_end(self):
        r = analyze("P", _base_program(end_date=_date_str(60)))
        self.assertEqual(r["days_remaining"], 60)

    def test_no_end_date_returns_none(self):
        r = analyze("P", _base_program(end_date=None))
        self.assertIsNone(r["days_remaining"])

    def test_past_end_negative(self):
        r = analyze("P", _base_program(end_date=_date_str(-5)))
        self.assertEqual(r["days_remaining"], -5)

    def test_end_today_is_zero(self):
        r = analyze("P", _base_program(end_date=_date_str(0)))
        self.assertEqual(r["days_remaining"], 0)


class TestBudgetMath(unittest.TestCase):
    def test_budget_remaining_correct(self):
        r = analyze("P", _base_program(token_budget_usd=1_000_000, spent_usd=600_000))
        self.assertAlmostEqual(r["budget_remaining_usd"], 400_000.0)

    def test_utilization_pct(self):
        r = analyze("P", _base_program(token_budget_usd=1_000_000, spent_usd=700_000))
        self.assertAlmostEqual(r["budget_utilization_pct"], 70.0, places=2)

    def test_fully_spent_remaining_zero(self):
        r = analyze("P", _base_program(token_budget_usd=100_000, spent_usd=100_000))
        self.assertEqual(r["budget_remaining_usd"], 0.0)

    def test_overspent_remaining_clamped_zero(self):
        r = analyze("P", _base_program(token_budget_usd=100_000, spent_usd=120_000))
        self.assertEqual(r["budget_remaining_usd"], 0.0)

    def test_zero_budget_utilization_is_zero(self):
        r = analyze("P", _base_program(token_budget_usd=0, spent_usd=0))
        self.assertAlmostEqual(r["budget_utilization_pct"], 0.0)

    def test_days_until_exhausted(self):
        r = analyze("P", _base_program(
            token_budget_usd=1_000_000, spent_usd=500_000,
            daily_emission_usd=10_000
        ))
        # 500_000 / 10_000 = 50
        self.assertAlmostEqual(r["days_until_budget_exhausted"], 50.0)

    def test_zero_emission_returns_none(self):
        r = analyze("P", _base_program(daily_emission_usd=0))
        self.assertIsNone(r["days_until_budget_exhausted"])


class TestAPYDecay(unittest.TestCase):
    def test_no_decay(self):
        r = analyze("P", _base_program(initial_apy=20.0, current_apy=20.0))
        self.assertAlmostEqual(r["apy_decay_pct"], 0.0)

    def test_50_pct_decay(self):
        r = analyze("P", _base_program(initial_apy=20.0, current_apy=10.0))
        self.assertAlmostEqual(r["apy_decay_pct"], 50.0)

    def test_zero_initial_no_divide(self):
        r = analyze("P", _base_program(initial_apy=0.0, current_apy=5.0))
        self.assertAlmostEqual(r["apy_decay_pct"], 0.0)

    def test_full_decay_100_pct(self):
        r = analyze("P", _base_program(initial_apy=20.0, current_apy=0.0))
        self.assertAlmostEqual(r["apy_decay_pct"], 100.0)

    def test_negative_decay_apy_increase(self):
        # current > initial → negative decay
        r = analyze("P", _base_program(initial_apy=10.0, current_apy=15.0))
        self.assertAlmostEqual(r["apy_decay_pct"], -50.0)


class TestStatus(unittest.TestCase):
    def test_exhausted_status(self):
        r = analyze("P", _base_program(token_budget_usd=100_000, spent_usd=100_000))
        self.assertEqual(r["status"], "EXHAUSTED")

    def test_critical_budget_exhausted_soon(self):
        r = analyze("P", _base_program(
            token_budget_usd=1_000_000,
            spent_usd=990_000,
            daily_emission_usd=2_000,   # 10_000 / 2_000 = 5 days → CRITICAL
        ))
        self.assertEqual(r["status"], "CRITICAL")

    def test_critical_end_date_soon(self):
        r = analyze("P", _base_program(
            end_date=_date_str(3),
            initial_apy=20.0,
            current_apy=19.0,  # low decay → won't hit DECAYING
        ))
        self.assertEqual(r["status"], "CRITICAL")

    def test_decaying_status(self):
        r = analyze("P", _base_program(
            initial_apy=20.0,
            current_apy=10.0,  # 50% decay > 30% threshold
            end_date=_date_str(60),
            token_budget_usd=1_000_000,
            spent_usd=100_000,
            daily_emission_usd=1_000,
        ))
        self.assertEqual(r["status"], "DECAYING")

    def test_active_status(self):
        r = analyze("P", _base_program(
            initial_apy=20.0,
            current_apy=18.0,  # 10% decay
            end_date=_date_str(60),
        ))
        self.assertEqual(r["status"], "ACTIVE")


class TestEffectiveEndDays(unittest.TestCase):
    def test_min_of_both(self):
        # budget: 500_000 / 5_000 = 100 days; end_date: 60 days → min = 60
        r = analyze("P", _base_program(
            token_budget_usd=1_000_000,
            spent_usd=500_000,
            daily_emission_usd=5_000,
            end_date=_date_str(60),
        ))
        self.assertAlmostEqual(r["effective_end_days"], 60.0)

    def test_budget_is_sooner(self):
        # budget: 10_000 / 5_000 = 2 days; end_date: 100 days → min = 2
        r = analyze("P", _base_program(
            token_budget_usd=1_010_000,
            spent_usd=1_000_000,
            daily_emission_usd=5_000,
            end_date=_date_str(100),
        ))
        self.assertAlmostEqual(r["effective_end_days"], 2.0)

    def test_no_end_date_uses_budget(self):
        r = analyze("P", _base_program(
            token_budget_usd=1_000_000,
            spent_usd=900_000,
            daily_emission_usd=5_000,
            end_date=None,
        ))
        # 100_000 / 5_000 = 20 days
        self.assertAlmostEqual(r["effective_end_days"], 20.0)

    def test_no_end_no_emission_returns_none(self):
        r = analyze("P", _base_program(
            end_date=None,
            daily_emission_usd=0,
        ))
        self.assertIsNone(r["effective_end_days"])


class TestProjectedAPY(unittest.TestCase):
    def test_zero_budget_gives_zero(self):
        r = analyze("P", _base_program(token_budget_usd=0, spent_usd=0))
        self.assertEqual(r["projected_apy_30d"], 0.0)

    def test_full_budget_exhausted_in_30d(self):
        # remaining=30_000, daily=1_000 → budget_in_30d=0 → projected=0
        r = analyze("P", _base_program(
            token_budget_usd=1_000_000,
            spent_usd=970_000,
            daily_emission_usd=1_000,
            current_apy=10.0,
        ))
        self.assertEqual(r["projected_apy_30d"], 0.0)

    def test_projected_apy_proportional(self):
        # remaining=100_000, 30*daily=30_000 → ratio=70_000/100_000=0.7 → projected=7.0
        r = analyze("P", _base_program(
            token_budget_usd=1_000_000,
            spent_usd=900_000,
            daily_emission_usd=1_000,
            current_apy=10.0,
        ))
        self.assertAlmostEqual(r["projected_apy_30d"], 7.0, places=4)

    def test_zero_daily_emission_full_apy(self):
        # no emission → budget_in_30d = budget_remaining - 0 → same as budget_remaining → ratio = 1
        r = analyze("P", _base_program(
            token_budget_usd=1_000_000,
            spent_usd=500_000,
            daily_emission_usd=0,
            current_apy=10.0,
        ))
        # budget_remaining=500_000, budget_in_30d=500_000 → projected=10.0
        self.assertAlmostEqual(r["projected_apy_30d"], 10.0, places=4)


class TestExitSignal(unittest.TestCase):
    def test_exit_signal_true_when_projected_below_threshold(self):
        # projected_apy_30d = 0 < 5.0 → exit_signal = True
        r = analyze("P", _base_program(
            token_budget_usd=100_000,
            spent_usd=99_000,
            daily_emission_usd=1_000,
            current_apy=5.0,
        ))
        self.assertTrue(r["exit_signal"])

    def test_exit_signal_false_when_projected_above_threshold(self):
        r = analyze("P", _base_program(
            token_budget_usd=1_000_000,
            spent_usd=100_000,
            daily_emission_usd=100,
            current_apy=20.0,
        ))
        self.assertFalse(r["exit_signal"])

    def test_custom_exit_threshold(self):
        r = analyze("P", _base_program(
            token_budget_usd=1_000_000,
            spent_usd=900_000,
            daily_emission_usd=1_000,
            current_apy=10.0,
        ), config={"exit_apy_threshold": 10.0})
        # projected = 7.0 < 10.0 → exit_signal = True
        self.assertTrue(r["exit_signal"])


class TestRiskFlags(unittest.TestCase):
    def test_flag_budget_over_80(self):
        r = analyze("P", _base_program(token_budget_usd=1_000_000, spent_usd=850_000))
        self.assertIn("Budget >80% consumed", r["risk_flags"])

    def test_no_flag_budget_under_80(self):
        r = analyze("P", _base_program(token_budget_usd=1_000_000, spent_usd=500_000))
        self.assertNotIn("Budget >80% consumed", r["risk_flags"])

    def test_flag_budget_exhausted_soon(self):
        r = analyze("P", _base_program(
            token_budget_usd=1_000_000,
            spent_usd=990_000,
            daily_emission_usd=2_000,   # 5 days < 14
        ), config={"decay_warning_days": 14})
        flags_text = " ".join(r["risk_flags"])
        self.assertIn("Budget exhausted in <14 days", flags_text)

    def test_flag_apy_decay_over_50(self):
        r = analyze("P", _base_program(initial_apy=20.0, current_apy=8.0))
        self.assertTrue(any("APY decayed" in f for f in r["risk_flags"]))

    def test_no_apy_decay_flag_under_50(self):
        r = analyze("P", _base_program(initial_apy=20.0, current_apy=15.0))
        self.assertFalse(any("APY decayed" in f for f in r["risk_flags"]))

    def test_flag_current_apy_below_threshold(self):
        r = analyze("P", _base_program(current_apy=3.0),
                    config={"exit_apy_threshold": 5.0})
        self.assertIn("Current APY below exit threshold", r["risk_flags"])

    def test_no_flag_current_apy_above_threshold(self):
        r = analyze("P", _base_program(current_apy=10.0),
                    config={"exit_apy_threshold": 5.0})
        self.assertNotIn("Current APY below exit threshold", r["risk_flags"])


class TestRecommendation(unittest.TestCase):
    def test_hold(self):
        # Good program, no issues
        r = analyze("P", _base_program(
            initial_apy=20.0, current_apy=19.0,
            token_budget_usd=1_000_000, spent_usd=100_000,
            daily_emission_usd=100,
            end_date=_date_str(180),
        ))
        self.assertEqual(r["recommendation"], "HOLD")

    def test_exit_now_when_exhausted(self):
        r = analyze("P", _base_program(
            token_budget_usd=100_000, spent_usd=100_000
        ))
        self.assertEqual(r["recommendation"], "EXIT_NOW")

    def test_prepare_exit_when_exit_signal(self):
        # projected=7.0 < threshold=8.0 but projected > threshold/2=4.0 → PREPARE_EXIT
        r = analyze("P", _base_program(
            token_budget_usd=1_000_000,
            spent_usd=900_000,
            daily_emission_usd=1_000,
            current_apy=10.0,
        ), config={"exit_apy_threshold": 8.0})
        self.assertEqual(r["recommendation"], "PREPARE_EXIT")

    def test_exit_now_when_exit_signal_very_low_projected(self):
        # projected = 0 < threshold/2 → EXIT_NOW
        r = analyze("P", _base_program(
            token_budget_usd=1_000_000,
            spent_usd=999_000,
            daily_emission_usd=10_000,
            current_apy=5.0,
        ), config={"exit_apy_threshold": 5.0})
        self.assertEqual(r["recommendation"], "EXIT_NOW")

    def test_monitor_when_decaying(self):
        r = analyze("P", _base_program(
            initial_apy=20.0,
            current_apy=10.0,   # 50% decay → DECAYING
            end_date=_date_str(90),
            token_budget_usd=1_000_000,
            spent_usd=100_000,
            daily_emission_usd=100,
        ), config={"exit_apy_threshold": 1.0})  # low threshold so no exit_signal
        self.assertIn(r["recommendation"], ("MONITOR", "HOLD"))

    def test_monitor_when_critical(self):
        r = analyze("P", _base_program(
            end_date=_date_str(3),
            initial_apy=20.0,
            current_apy=19.0,
        ), config={"exit_apy_threshold": 1.0})
        self.assertIn(r["recommendation"], ("MONITOR", "EXIT_NOW", "PREPARE_EXIT"))


class TestEdgeCases(unittest.TestCase):
    def test_no_config_uses_defaults(self):
        r = analyze("P", _base_program())
        self.assertIn("status", r)

    def test_empty_config_uses_defaults(self):
        r = analyze("P", _base_program(), config={})
        self.assertIn("status", r)

    def test_custom_decay_warning_days(self):
        r = analyze("P", _base_program(
            token_budget_usd=1_000_000,
            spent_usd=990_000,
            daily_emission_usd=2_000,
        ), config={"decay_warning_days": 3})  # 5 days > 3 → no flag
        flags_text = " ".join(r["risk_flags"])
        self.assertNotIn("Budget exhausted in <3 days", flags_text)

    def test_invalid_start_date_defaults_to_today(self):
        r = analyze("P", _base_program(start_date="not-a-date"))
        self.assertEqual(r["days_elapsed"], 0)

    def test_invalid_end_date_treated_as_none(self):
        r = analyze("P", _base_program(end_date="bad-date"))
        self.assertIsNone(r["days_remaining"])

    def test_zero_principal_no_crash(self):
        r = analyze("P", _base_program(tvl_usd=0))
        self.assertIn("status", r)

    def test_status_values_valid(self):
        r = analyze("P", _base_program())
        self.assertIn(r["status"], ("ACTIVE", "DECAYING", "CRITICAL", "EXHAUSTED"))

    def test_recommendation_values_valid(self):
        r = analyze("P", _base_program())
        self.assertIn(r["recommendation"], ("HOLD", "MONITOR", "PREPARE_EXIT", "EXIT_NOW"))

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze("P", _base_program())
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_very_large_budget(self):
        r = analyze("P", _base_program(
            token_budget_usd=1e12,
            spent_usd=1e9,
            daily_emission_usd=1_000,
        ))
        self.assertIsNotNone(r["days_until_budget_exhausted"])

    def test_very_small_daily_emission(self):
        r = analyze("P", _base_program(daily_emission_usd=0.01))
        self.assertIsNotNone(r["days_until_budget_exhausted"])


class TestLogging(unittest.TestCase):
    def setUp(self):
        # Use a temp file so we don't corrupt real data
        self._tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        )
        self._tmp.write("[]")
        self._tmp.close()
        self._orig_path = __import__(
            "spa_core.analytics.protocol_incentive_decay_monitor",
            fromlist=["LOG_PATH"]
        )
        import spa_core.analytics.protocol_incentive_decay_monitor as mod
        self._mod = mod
        self._orig = mod.LOG_PATH
        mod.LOG_PATH = self._tmp.name

    def tearDown(self):
        self._mod.LOG_PATH = self._orig
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_log_result_creates_entry(self):
        r = analyze("P", _base_program())
        log_result(r)
        entries = _load_log()
        self.assertEqual(len(entries), 1)

    def test_log_result_appends(self):
        r1 = analyze("P", _base_program())
        r2 = analyze("Q", _base_program())
        log_result(r1)
        log_result(r2)
        entries = _load_log()
        self.assertEqual(len(entries), 2)

    def test_ring_buffer_cap(self):
        import spa_core.analytics.protocol_incentive_decay_monitor as mod
        entries = [{"x": i} for i in range(150)]
        mod._save_log(entries)
        loaded = mod._load_log()
        self.assertEqual(len(loaded), LOG_CAP)

    def test_ring_buffer_keeps_latest(self):
        import spa_core.analytics.protocol_incentive_decay_monitor as mod
        entries = [{"x": i} for i in range(150)]
        mod._save_log(entries)
        loaded = mod._load_log()
        self.assertEqual(loaded[-1]["x"], 149)
        self.assertEqual(loaded[0]["x"], 50)

    def test_corrupt_log_returns_empty(self):
        with open(self._tmp.name, "w") as f:
            f.write("not-json{{{")
        entries = _load_log()
        self.assertEqual(entries, [])

    def test_missing_log_returns_empty(self):
        os.unlink(self._tmp.name)
        entries = _load_log()
        self.assertEqual(entries, [])

    def test_atomic_write_succeeds(self):
        import spa_core.analytics.protocol_incentive_decay_monitor as mod
        mod._save_log([{"test": True}])
        loaded = mod._load_log()
        self.assertEqual(loaded[0]["test"], True)


if __name__ == "__main__":
    unittest.main()
