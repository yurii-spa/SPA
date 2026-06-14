"""Unit tests for spa_core.analytics.liquidity_runway_calculator (MP-826).

Pure stdlib unittest only — no pytest, no numpy, no external deps.
File I/O tests use tempfile so real data/ is never touched.

Run:
    python3 -m unittest spa_core.tests.test_liquidity_runway_calculator -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve project root so imports work from any cwd
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import spa_core.analytics.liquidity_runway_calculator as lrc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _metrics(treasury_usd=1_000_000, daily_emission_usd=1_000,
             current_tvl_usd=50_000_000, organic_tvl_pct=40.0,
             tvl_per_emission_usd=100.0, daily_protocol_revenue_usd=500):
    return {
        "treasury_usd": treasury_usd,
        "daily_emission_usd": daily_emission_usd,
        "current_tvl_usd": current_tvl_usd,
        "organic_tvl_pct": organic_tvl_pct,
        "tvl_per_emission_usd": tvl_per_emission_usd,
        "daily_protocol_revenue_usd": daily_protocol_revenue_usd,
    }


class _TempDataMixin:
    """Redirects DATA_FILE to a temp directory for each test."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_data_file = lrc.DATA_FILE
        lrc.DATA_FILE = Path(self._tmpdir) / "liquidity_runway_log.json"

    def tearDown(self):
        lrc.DATA_FILE = self._orig_data_file
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)


# ===========================================================================
# 1. Return-value shape
# ===========================================================================
class TestReturnShape(_TempDataMixin, unittest.TestCase):

    def _result(self):
        return lrc.analyze("TestProtocol", _metrics())

    def test_returns_dict(self):
        self.assertIsInstance(self._result(), dict)

    def test_has_protocol_key(self):
        self.assertIn("protocol", self._result())

    def test_has_runway_days_key(self):
        self.assertIn("runway_days", self._result())

    def test_has_is_self_sustaining_key(self):
        self.assertIn("is_self_sustaining", self._result())

    def test_has_net_daily_burn_usd_key(self):
        self.assertIn("net_daily_burn_usd", self._result())

    def test_has_tvl_at_risk_usd_key(self):
        self.assertIn("tvl_at_risk_usd", self._result())

    def test_has_incentivized_tvl_usd_key(self):
        self.assertIn("incentivized_tvl_usd", self._result())

    def test_has_projected_tvl_after_stop_usd_key(self):
        self.assertIn("projected_tvl_after_stop_usd", self._result())

    def test_has_tvl_drop_usd_key(self):
        self.assertIn("tvl_drop_usd", self._result())

    def test_has_emission_efficiency_key(self):
        self.assertIn("emission_efficiency", self._result())

    def test_has_revenue_coverage_pct_key(self):
        self.assertIn("revenue_coverage_pct", self._result())

    def test_has_sustainability_status_key(self):
        self.assertIn("sustainability_status", self._result())

    def test_has_risk_assessment_key(self):
        self.assertIn("risk_assessment", self._result())

    def test_has_timestamp_key(self):
        self.assertIn("timestamp", self._result())

    def test_timestamp_is_float(self):
        self.assertIsInstance(self._result()["timestamp"], float)

    def test_timestamp_is_recent(self):
        self.assertAlmostEqual(self._result()["timestamp"], time.time(), delta=5)

    def test_protocol_name_preserved(self):
        r = lrc.analyze("MyProtocol", _metrics())
        self.assertEqual(r["protocol"], "MyProtocol")


# ===========================================================================
# 2. Self-sustaining logic
# ===========================================================================
class TestSelfSustaining(_TempDataMixin, unittest.TestCase):

    def test_self_sustaining_when_revenue_gt_emission(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=500,
                                      daily_protocol_revenue_usd=1000))
        self.assertTrue(r["is_self_sustaining"])

    def test_self_sustaining_when_revenue_eq_emission(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=1000,
                                      daily_protocol_revenue_usd=1000))
        self.assertTrue(r["is_self_sustaining"])

    def test_not_self_sustaining_when_revenue_lt_emission(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=1000,
                                      daily_protocol_revenue_usd=500))
        self.assertFalse(r["is_self_sustaining"])

    def test_self_sustaining_when_emission_zero(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=0,
                                      daily_protocol_revenue_usd=0))
        self.assertTrue(r["is_self_sustaining"])

    def test_self_sustaining_runway_is_none(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=500,
                                      daily_protocol_revenue_usd=1000))
        self.assertIsNone(r["runway_days"])

    def test_self_sustaining_status(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=500,
                                      daily_protocol_revenue_usd=1000))
        self.assertEqual(r["sustainability_status"], "SELF_SUSTAINING")

    def test_self_sustaining_risk_assessment_string(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=500,
                                      daily_protocol_revenue_usd=1000))
        self.assertIn("self-sustaining", r["risk_assessment"].lower())


# ===========================================================================
# 3. Runway calculation
# ===========================================================================
class TestRunwayDays(_TempDataMixin, unittest.TestCase):

    def test_runway_formula(self):
        # treasury=1000, emission=1000, revenue=0 → burn=1000, runway=1
        r = lrc.analyze("P", _metrics(treasury_usd=1000,
                                       daily_emission_usd=1000,
                                       daily_protocol_revenue_usd=0))
        self.assertAlmostEqual(r["runway_days"], 1.0, places=6)

    def test_runway_with_partial_revenue(self):
        # treasury=1000, emission=1000, revenue=500 → burn=500, runway=2
        r = lrc.analyze("P", _metrics(treasury_usd=1000,
                                       daily_emission_usd=1000,
                                       daily_protocol_revenue_usd=500))
        self.assertAlmostEqual(r["runway_days"], 2.0, places=6)

    def test_runway_365_days(self):
        r = lrc.analyze("P", _metrics(treasury_usd=365_000,
                                       daily_emission_usd=1000,
                                       daily_protocol_revenue_usd=0))
        self.assertAlmostEqual(r["runway_days"], 365.0, places=4)

    def test_runway_days_is_float_when_not_self_sustaining(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=1000,
                                       daily_protocol_revenue_usd=0))
        self.assertIsInstance(r["runway_days"], float)

    def test_treasury_zero_gives_runway_zero(self):
        r = lrc.analyze("P", _metrics(treasury_usd=0,
                                       daily_emission_usd=1000,
                                       daily_protocol_revenue_usd=0))
        self.assertAlmostEqual(r["runway_days"], 0.0, places=6)

    def test_treasury_zero_gives_critical_status(self):
        r = lrc.analyze("P", _metrics(treasury_usd=0,
                                       daily_emission_usd=1000,
                                       daily_protocol_revenue_usd=0))
        self.assertEqual(r["sustainability_status"], "CRITICAL")

    def test_runway_large_treasury(self):
        r = lrc.analyze("P", _metrics(treasury_usd=1_000_000,
                                       daily_emission_usd=100,
                                       daily_protocol_revenue_usd=0))
        self.assertAlmostEqual(r["runway_days"], 10_000.0, places=2)


# ===========================================================================
# 4. Sustainability status
# ===========================================================================
class TestSustainabilityStatus(_TempDataMixin, unittest.TestCase):

    def _status(self, treasury, emission, revenue):
        r = lrc.analyze("P", _metrics(treasury_usd=treasury,
                                       daily_emission_usd=emission,
                                       daily_protocol_revenue_usd=revenue))
        return r["sustainability_status"]

    def test_healthy_status_at_365_days(self):
        # 365 burn → status HEALTHY
        self.assertEqual(self._status(365_000, 1000, 0), "HEALTHY")

    def test_healthy_status_above_365_days(self):
        self.assertEqual(self._status(500_000, 1000, 0), "HEALTHY")

    def test_moderate_status_at_180_days(self):
        self.assertEqual(self._status(180_000, 1000, 0), "MODERATE")

    def test_moderate_status_between_180_and_365(self):
        self.assertEqual(self._status(250_000, 1000, 0), "MODERATE")

    def test_stressed_status_at_90_days(self):
        self.assertEqual(self._status(90_000, 1000, 0), "STRESSED")

    def test_stressed_status_between_90_and_180(self):
        self.assertEqual(self._status(120_000, 1000, 0), "STRESSED")

    def test_critical_status_below_90_days(self):
        self.assertEqual(self._status(89_000, 1000, 0), "CRITICAL")

    def test_critical_status_zero_runway(self):
        self.assertEqual(self._status(0, 1000, 0), "CRITICAL")

    def test_self_sustaining_takes_priority_over_other_statuses(self):
        # Even with zero treasury, self-sustaining wins
        r = lrc.analyze("P", _metrics(treasury_usd=0,
                                       daily_emission_usd=500,
                                       daily_protocol_revenue_usd=500))
        self.assertEqual(r["sustainability_status"], "SELF_SUSTAINING")

    def test_exactly_364_days_is_moderate(self):
        self.assertEqual(self._status(364_000, 1000, 0), "MODERATE")

    def test_exactly_179_days_is_stressed(self):
        self.assertEqual(self._status(179_000, 1000, 0), "STRESSED")

    def test_exactly_89_days_is_critical(self):
        self.assertEqual(self._status(89_000, 1000, 0), "CRITICAL")


# ===========================================================================
# 5. Net daily burn
# ===========================================================================
class TestNetDailyBurn(_TempDataMixin, unittest.TestCase):

    def test_net_daily_burn_positive(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=1000,
                                       daily_protocol_revenue_usd=300))
        self.assertAlmostEqual(r["net_daily_burn_usd"], 700.0, places=4)

    def test_net_daily_burn_negative_when_self_sustaining(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=500,
                                       daily_protocol_revenue_usd=1000))
        self.assertLess(r["net_daily_burn_usd"], 0)

    def test_net_daily_burn_zero_when_equal(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=1000,
                                       daily_protocol_revenue_usd=1000))
        self.assertAlmostEqual(r["net_daily_burn_usd"], 0.0, places=4)

    def test_net_daily_burn_formula(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=800,
                                       daily_protocol_revenue_usd=200))
        self.assertAlmostEqual(r["net_daily_burn_usd"], 600.0, places=4)


# ===========================================================================
# 6. TVL at risk
# ===========================================================================
class TestTvlAtRisk(_TempDataMixin, unittest.TestCase):

    def test_tvl_at_risk_formula(self):
        # current_tvl=50M, organic=40% → at_risk = 50M * 0.60 = 30M
        r = lrc.analyze("P", _metrics(current_tvl_usd=50_000_000,
                                       organic_tvl_pct=40.0))
        self.assertAlmostEqual(r["tvl_at_risk_usd"], 30_000_000.0, places=2)

    def test_tvl_at_risk_zero_organic(self):
        # organic=0 → all TVL at risk
        r = lrc.analyze("P", _metrics(current_tvl_usd=10_000_000,
                                       organic_tvl_pct=0.0))
        self.assertAlmostEqual(r["tvl_at_risk_usd"], 10_000_000.0, places=2)

    def test_tvl_at_risk_full_organic(self):
        # organic=100% → nothing at risk
        r = lrc.analyze("P", _metrics(current_tvl_usd=10_000_000,
                                       organic_tvl_pct=100.0))
        self.assertAlmostEqual(r["tvl_at_risk_usd"], 0.0, places=2)

    def test_incentivized_tvl_equals_tvl_at_risk(self):
        r = lrc.analyze("P", _metrics(current_tvl_usd=20_000_000,
                                       organic_tvl_pct=30.0))
        self.assertAlmostEqual(r["incentivized_tvl_usd"],
                               r["tvl_at_risk_usd"], places=6)

    def test_tvl_at_risk_partial_organic(self):
        # current_tvl=100M, organic=75% → at_risk=25M
        r = lrc.analyze("P", _metrics(current_tvl_usd=100_000_000,
                                       organic_tvl_pct=75.0))
        self.assertAlmostEqual(r["tvl_at_risk_usd"], 25_000_000.0, places=2)


# ===========================================================================
# 7. Projected TVL after emission stop
# ===========================================================================
class TestProjectedTvl(_TempDataMixin, unittest.TestCase):

    def test_projected_tvl_default_60pct_drop(self):
        # current_tvl=100M, drop=60% → projected=40M
        r = lrc.analyze("P", _metrics(current_tvl_usd=100_000_000))
        self.assertAlmostEqual(r["projected_tvl_after_stop_usd"],
                               40_000_000.0, places=2)

    def test_tvl_drop_usd_default(self):
        r = lrc.analyze("P", _metrics(current_tvl_usd=100_000_000))
        self.assertAlmostEqual(r["tvl_drop_usd"], 60_000_000.0, places=2)

    def test_custom_tvl_drop_pct(self):
        # drop=80% → projected=20M
        r = lrc.analyze("P", _metrics(current_tvl_usd=100_000_000),
                        config={"tvl_drop_at_emission_stop_pct": 80.0})
        self.assertAlmostEqual(r["projected_tvl_after_stop_usd"],
                               20_000_000.0, places=2)

    def test_custom_tvl_drop_usd(self):
        r = lrc.analyze("P", _metrics(current_tvl_usd=100_000_000),
                        config={"tvl_drop_at_emission_stop_pct": 80.0})
        self.assertAlmostEqual(r["tvl_drop_usd"], 80_000_000.0, places=2)

    def test_zero_tvl_drop(self):
        r = lrc.analyze("P", _metrics(current_tvl_usd=50_000_000),
                        config={"tvl_drop_at_emission_stop_pct": 0.0})
        self.assertAlmostEqual(r["projected_tvl_after_stop_usd"],
                               50_000_000.0, places=2)
        self.assertAlmostEqual(r["tvl_drop_usd"], 0.0, places=2)

    def test_full_tvl_drop(self):
        r = lrc.analyze("P", _metrics(current_tvl_usd=50_000_000),
                        config={"tvl_drop_at_emission_stop_pct": 100.0})
        self.assertAlmostEqual(r["projected_tvl_after_stop_usd"], 0.0, places=2)
        self.assertAlmostEqual(r["tvl_drop_usd"], 50_000_000.0, places=2)

    def test_tvl_drop_plus_projected_equals_current(self):
        r = lrc.analyze("P", _metrics(current_tvl_usd=80_000_000),
                        config={"tvl_drop_at_emission_stop_pct": 45.0})
        total = r["tvl_drop_usd"] + r["projected_tvl_after_stop_usd"]
        self.assertAlmostEqual(total, 80_000_000.0, places=2)


# ===========================================================================
# 8. Revenue coverage and emission efficiency
# ===========================================================================
class TestRevenueCoverageAndEfficiency(_TempDataMixin, unittest.TestCase):

    def test_revenue_coverage_formula(self):
        # revenue=500, emission=1000 → 50%
        r = lrc.analyze("P", _metrics(daily_emission_usd=1000,
                                       daily_protocol_revenue_usd=500))
        self.assertAlmostEqual(r["revenue_coverage_pct"], 50.0, places=4)

    def test_revenue_coverage_full(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=1000,
                                       daily_protocol_revenue_usd=1000))
        self.assertAlmostEqual(r["revenue_coverage_pct"], 100.0, places=4)

    def test_revenue_coverage_over_100_when_self_sustaining(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=500,
                                       daily_protocol_revenue_usd=1000))
        self.assertGreater(r["revenue_coverage_pct"], 100.0)

    def test_revenue_coverage_zero_when_no_revenue(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=1000,
                                       daily_protocol_revenue_usd=0))
        self.assertAlmostEqual(r["revenue_coverage_pct"], 0.0, places=4)

    def test_revenue_coverage_zero_emission_uses_guard(self):
        # emission=0 → uses max(0, 0.01)=0.01 in denominator
        r = lrc.analyze("P", _metrics(daily_emission_usd=0,
                                       daily_protocol_revenue_usd=100))
        # revenue_coverage = 100 / 0.01 * 100 = 1_000_000
        self.assertAlmostEqual(r["revenue_coverage_pct"], 1_000_000.0, places=0)

    def test_emission_efficiency_is_tvl_per_emission(self):
        r = lrc.analyze("P", _metrics(tvl_per_emission_usd=250.0))
        self.assertAlmostEqual(r["emission_efficiency"], 250.0, places=6)

    def test_emission_efficiency_zero(self):
        r = lrc.analyze("P", _metrics(tvl_per_emission_usd=0.0))
        self.assertAlmostEqual(r["emission_efficiency"], 0.0, places=6)


# ===========================================================================
# 9. Risk assessment string
# ===========================================================================
class TestRiskAssessment(_TempDataMixin, unittest.TestCase):

    def test_risk_assessment_is_string(self):
        r = lrc.analyze("P", _metrics())
        self.assertIsInstance(r["risk_assessment"], str)

    def test_risk_assessment_self_sustaining(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=500,
                                       daily_protocol_revenue_usd=1000))
        self.assertEqual(r["risk_assessment"], "Protocol is self-sustaining")

    def test_risk_assessment_contains_runway_days(self):
        r = lrc.analyze("P", _metrics(treasury_usd=500_000,
                                       daily_emission_usd=1000,
                                       daily_protocol_revenue_usd=0))
        self.assertIn("500", r["risk_assessment"])

    def test_risk_assessment_contains_revenue_coverage(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=1000,
                                       daily_protocol_revenue_usd=500))
        self.assertIn("50%", r["risk_assessment"])

    def test_risk_assessment_contains_days_word(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=1000,
                                       daily_protocol_revenue_usd=0))
        self.assertIn("days", r["risk_assessment"])

    def test_risk_assessment_zero_revenue_shows_0pct(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=1000,
                                       daily_protocol_revenue_usd=0))
        self.assertIn("0%", r["risk_assessment"])


# ===========================================================================
# 10. Config handling
# ===========================================================================
class TestConfigHandling(_TempDataMixin, unittest.TestCase):

    def test_config_none_uses_default_tvl_drop(self):
        r = lrc.analyze("P", _metrics(current_tvl_usd=100_000_000), config=None)
        self.assertAlmostEqual(r["tvl_drop_usd"], 60_000_000.0, places=2)

    def test_config_empty_dict_uses_default_tvl_drop(self):
        r = lrc.analyze("P", _metrics(current_tvl_usd=100_000_000), config={})
        self.assertAlmostEqual(r["tvl_drop_usd"], 60_000_000.0, places=2)

    def test_custom_tvl_drop_overrides_default(self):
        r = lrc.analyze("P", _metrics(current_tvl_usd=100_000_000),
                        config={"tvl_drop_at_emission_stop_pct": 30.0})
        self.assertAlmostEqual(r["tvl_drop_usd"], 30_000_000.0, places=2)


# ===========================================================================
# 11. Ring-buffer / persistence
# ===========================================================================
class TestRingBuffer(_TempDataMixin, unittest.TestCase):

    def test_log_file_created_after_analyze(self):
        lrc.analyze("P", _metrics())
        self.assertTrue(lrc.DATA_FILE.exists())

    def test_log_file_is_valid_json(self):
        lrc.analyze("P", _metrics())
        with open(lrc.DATA_FILE) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends_one_entry(self):
        lrc.analyze("P", _metrics())
        with open(lrc.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_grows_with_multiple_calls(self):
        lrc.analyze("A", _metrics())
        lrc.analyze("B", _metrics())
        with open(lrc.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_caps_at_100(self):
        for i in range(105):
            lrc.analyze(f"P{i}", _metrics())
        with open(lrc.DATA_FILE) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_ring_buffer_keeps_latest_entries(self):
        for i in range(105):
            lrc.analyze(f"PROTO_{i}", _metrics())
        with open(lrc.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["protocol"], "PROTO_104")

    def test_atomic_write_no_tmp_left(self):
        lrc.analyze("P", _metrics())
        tmp = lrc.DATA_FILE.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_log_entry_contains_protocol(self):
        lrc.analyze("CurveFinance", _metrics())
        with open(lrc.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(data[0]["protocol"], "CurveFinance")

    def test_log_entry_contains_timestamp(self):
        lrc.analyze("P", _metrics())
        with open(lrc.DATA_FILE) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_data_dir_created_if_missing(self):
        import shutil
        shutil.rmtree(lrc.DATA_FILE.parent, ignore_errors=True)
        lrc.analyze("P", _metrics())
        self.assertTrue(lrc.DATA_FILE.exists())


# ===========================================================================
# 12. Module constants
# ===========================================================================
class TestConstants(_TempDataMixin, unittest.TestCase):

    def test_default_tvl_drop_pct_is_60(self):
        self.assertEqual(lrc.DEFAULT_TVL_DROP_PCT, 60.0)

    def test_max_entries_is_100(self):
        self.assertEqual(lrc.MAX_ENTRIES, 100)

    def test_data_file_path_contains_liquidity(self):
        self.assertIn("liquidity", str(lrc.DATA_FILE))


# ===========================================================================
# 13. Edge / boundary cases
# ===========================================================================
class TestEdgeCases(_TempDataMixin, unittest.TestCase):

    def test_zero_tvl_gives_zero_at_risk(self):
        r = lrc.analyze("P", _metrics(current_tvl_usd=0,
                                       organic_tvl_pct=50.0))
        self.assertAlmostEqual(r["tvl_at_risk_usd"], 0.0, places=4)

    def test_zero_tvl_gives_zero_projected(self):
        r = lrc.analyze("P", _metrics(current_tvl_usd=0))
        self.assertAlmostEqual(r["projected_tvl_after_stop_usd"], 0.0, places=4)

    def test_daily_emission_zero_is_self_sustaining(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=0,
                                       daily_protocol_revenue_usd=0))
        self.assertTrue(r["is_self_sustaining"])

    def test_daily_emission_zero_runway_is_none(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=0,
                                       daily_protocol_revenue_usd=0))
        self.assertIsNone(r["runway_days"])

    def test_high_organic_tvl_low_at_risk(self):
        r = lrc.analyze("P", _metrics(current_tvl_usd=100_000_000,
                                       organic_tvl_pct=95.0))
        self.assertAlmostEqual(r["tvl_at_risk_usd"], 5_000_000.0, places=2)

    def test_large_values_dont_crash(self):
        r = lrc.analyze("P", _metrics(treasury_usd=1e12,
                                       daily_emission_usd=1e9,
                                       current_tvl_usd=1e15))
        self.assertIsInstance(r, dict)

    def test_net_burn_negative_revenue_exceeds_emission(self):
        r = lrc.analyze("P", _metrics(daily_emission_usd=100,
                                       daily_protocol_revenue_usd=500))
        self.assertAlmostEqual(r["net_daily_burn_usd"], -400.0, places=4)

    def test_result_is_not_mutated_on_second_call(self):
        r1 = lrc.analyze("A", _metrics(treasury_usd=100_000))
        r2 = lrc.analyze("B", _metrics(treasury_usd=200_000))
        self.assertNotEqual(r1["protocol"], r2["protocol"])

    def test_zero_revenue_full_burn(self):
        r = lrc.analyze("P", _metrics(treasury_usd=30_000,
                                       daily_emission_usd=1000,
                                       daily_protocol_revenue_usd=0))
        self.assertAlmostEqual(r["runway_days"], 30.0, places=4)
        self.assertEqual(r["sustainability_status"], "CRITICAL")

    def test_organic_tvl_pct_50_halves_at_risk(self):
        r = lrc.analyze("P", _metrics(current_tvl_usd=40_000_000,
                                       organic_tvl_pct=50.0))
        self.assertAlmostEqual(r["tvl_at_risk_usd"], 20_000_000.0, places=2)


if __name__ == "__main__":
    unittest.main()
