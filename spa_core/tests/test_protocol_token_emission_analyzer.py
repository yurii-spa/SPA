"""
Tests for MP-852 ProtocolTokenEmissionAnalyzer
================================================
Run with: python3 -m unittest spa_core/tests/test_protocol_token_emission_analyzer.py
≥65 tests covering all branches, edge cases, sustainability labels, flags.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_token_emission_analyzer import (
    analyze,
    _analyze_protocol,
    _load_log,
    _save_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _proto(
    name="TestProto",
    token_symbol="TKN",
    current_supply=1_000_000.0,
    max_supply=10_000_000.0,
    emissions_per_day=1_000.0,
    token_price_usd=1.0,
    revenue_daily_usd=2_000.0,
    unlock_schedule=None,
):
    return {
        "name": name,
        "token_symbol": token_symbol,
        "current_supply": current_supply,
        "max_supply": max_supply,
        "emissions_per_day": emissions_per_day,
        "token_price_usd": token_price_usd,
        "protocol_revenue_daily_usd": revenue_daily_usd,
        "emission_unlock_schedule": unlock_schedule or [],
    }


# ---------------------------------------------------------------------------
# 1. Daily inflation %
# ---------------------------------------------------------------------------

class TestDailyInflation(unittest.TestCase):

    def test_basic_daily_inflation(self):
        p = _proto(current_supply=1_000_000.0, emissions_per_day=1_000.0)
        r = _analyze_protocol(p, 5.0)
        self.assertAlmostEqual(r["daily_inflation_pct"], 0.1, places=6)

    def test_zero_supply_inflation_is_zero(self):
        p = _proto(current_supply=0.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["daily_inflation_pct"], 0.0)

    def test_zero_emissions_inflation_is_zero(self):
        p = _proto(emissions_per_day=0.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["daily_inflation_pct"], 0.0)

    def test_annualized_is_daily_times_365(self):
        p = _proto(current_supply=1_000_000.0, emissions_per_day=500.0)
        r = _analyze_protocol(p, 5.0)
        self.assertAlmostEqual(r["annualized_inflation_pct"], r["daily_inflation_pct"] * 365, places=4)

    def test_high_emission_inflation(self):
        # 10% daily → 3650% annual (HYPERINFLATIONARY)
        p = _proto(current_supply=1_000_000.0, emissions_per_day=100_000.0)
        r = _analyze_protocol(p, 5.0)
        self.assertGreater(r["annualized_inflation_pct"], 100.0)

    def test_small_emission_inflation(self):
        p = _proto(current_supply=100_000_000.0, emissions_per_day=100.0)
        r = _analyze_protocol(p, 5.0)
        self.assertLess(r["annualized_inflation_pct"], 5.0)


# ---------------------------------------------------------------------------
# 2. Emission value USD
# ---------------------------------------------------------------------------

class TestEmissionValueUsd(unittest.TestCase):

    def test_emission_value_basic(self):
        p = _proto(emissions_per_day=1_000.0, token_price_usd=2.0)
        r = _analyze_protocol(p, 5.0)
        self.assertAlmostEqual(r["emission_value_usd_daily"], 2_000.0, places=4)

    def test_emission_value_zero_emissions(self):
        p = _proto(emissions_per_day=0.0, token_price_usd=10.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["emission_value_usd_daily"], 0.0)

    def test_emission_value_zero_price(self):
        p = _proto(emissions_per_day=1_000.0, token_price_usd=0.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["emission_value_usd_daily"], 0.0)


# ---------------------------------------------------------------------------
# 3. Revenue coverage ratio
# ---------------------------------------------------------------------------

class TestRevenueCoverage(unittest.TestCase):

    def test_coverage_above_one(self):
        p = _proto(emissions_per_day=1_000.0, token_price_usd=1.0, revenue_daily_usd=2_000.0)
        r = _analyze_protocol(p, 5.0)
        self.assertAlmostEqual(r["revenue_coverage_ratio"], 2.0, places=4)

    def test_coverage_below_one(self):
        p = _proto(emissions_per_day=1_000.0, token_price_usd=1.0, revenue_daily_usd=500.0)
        r = _analyze_protocol(p, 5.0)
        self.assertAlmostEqual(r["revenue_coverage_ratio"], 0.5, places=4)

    def test_coverage_zero_emissions_returns_999(self):
        p = _proto(emissions_per_day=0.0, revenue_daily_usd=5000.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["revenue_coverage_ratio"], 999.0)

    def test_coverage_zero_revenue(self):
        p = _proto(emissions_per_day=1_000.0, token_price_usd=1.0, revenue_daily_usd=0.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["revenue_coverage_ratio"], 0.0)


# ---------------------------------------------------------------------------
# 4. Supply remaining %
# ---------------------------------------------------------------------------

class TestSupplyRemaining(unittest.TestCase):

    def test_supply_remaining_basic(self):
        p = _proto(current_supply=1_000_000.0, max_supply=10_000_000.0)
        r = _analyze_protocol(p, 5.0)
        self.assertAlmostEqual(r["supply_remaining_pct"], 90.0, places=4)

    def test_supply_remaining_none_when_unlimited(self):
        p = _proto(max_supply=0.0)
        r = _analyze_protocol(p, 5.0)
        self.assertIsNone(r["supply_remaining_pct"])

    def test_supply_remaining_zero_when_fully_diluted(self):
        p = _proto(current_supply=10_000_000.0, max_supply=10_000_000.0)
        r = _analyze_protocol(p, 5.0)
        self.assertAlmostEqual(r["supply_remaining_pct"], 0.0, places=4)

    def test_supply_remaining_over_diluted_clipped(self):
        # current > max → remaining = 0%
        p = _proto(current_supply=11_000_000.0, max_supply=10_000_000.0)
        r = _analyze_protocol(p, 5.0)
        self.assertAlmostEqual(r["supply_remaining_pct"], 0.0, places=4)

    def test_supply_remaining_50_pct(self):
        p = _proto(current_supply=5_000_000.0, max_supply=10_000_000.0)
        r = _analyze_protocol(p, 5.0)
        self.assertAlmostEqual(r["supply_remaining_pct"], 50.0, places=4)


# ---------------------------------------------------------------------------
# 5. Days to fully diluted
# ---------------------------------------------------------------------------

class TestDaysToFullyDiluted(unittest.TestCase):

    def test_days_basic(self):
        p = _proto(current_supply=1_000_000.0, max_supply=10_000_000.0, emissions_per_day=1_000.0)
        r = _analyze_protocol(p, 5.0)
        # (10M - 1M) / 1000 = 9000 days
        self.assertAlmostEqual(r["days_to_fully_diluted"], 9_000.0, places=2)

    def test_days_none_when_unlimited(self):
        p = _proto(max_supply=0.0)
        r = _analyze_protocol(p, 5.0)
        self.assertIsNone(r["days_to_fully_diluted"])

    def test_days_none_when_zero_emissions(self):
        p = _proto(emissions_per_day=0.0)
        r = _analyze_protocol(p, 5.0)
        self.assertIsNone(r["days_to_fully_diluted"])

    def test_days_zero_when_already_diluted(self):
        p = _proto(current_supply=10_000_000.0, max_supply=10_000_000.0, emissions_per_day=100.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["days_to_fully_diluted"], 0.0)

    def test_days_zero_when_over_diluted(self):
        p = _proto(current_supply=11_000_000.0, max_supply=10_000_000.0, emissions_per_day=100.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["days_to_fully_diluted"], 0.0)


# ---------------------------------------------------------------------------
# 6. Next major unlock
# ---------------------------------------------------------------------------

class TestNextMajorUnlock(unittest.TestCase):

    def test_none_when_no_schedule(self):
        p = _proto(unlock_schedule=[])
        r = _analyze_protocol(p, 5.0)
        self.assertIsNone(r["next_major_unlock"])

    def test_picks_smallest_positive_days(self):
        schedule = [
            {"days_until": 90, "tokens_unlocking": 100_000},
            {"days_until": 15, "tokens_unlocking": 50_000},
            {"days_until": 30, "tokens_unlocking": 200_000},
        ]
        p = _proto(unlock_schedule=schedule)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["next_major_unlock"]["days_until"], 15)

    def test_skips_past_unlocks(self):
        schedule = [
            {"days_until": -5, "tokens_unlocking": 500_000},
            {"days_until": 0, "tokens_unlocking": 100_000},
            {"days_until": 60, "tokens_unlocking": 200_000},
        ]
        p = _proto(unlock_schedule=schedule)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["next_major_unlock"]["days_until"], 60)

    def test_none_when_all_past(self):
        schedule = [
            {"days_until": -10, "tokens_unlocking": 100_000},
            {"days_until": -5, "tokens_unlocking": 50_000},
        ]
        p = _proto(unlock_schedule=schedule)
        r = _analyze_protocol(p, 5.0)
        self.assertIsNone(r["next_major_unlock"])

    def test_single_upcoming_unlock(self):
        schedule = [{"days_until": 45, "tokens_unlocking": 1_000_000}]
        p = _proto(unlock_schedule=schedule)
        r = _analyze_protocol(p, 5.0)
        self.assertIsNotNone(r["next_major_unlock"])
        self.assertEqual(r["next_major_unlock"]["tokens_unlocking"], 1_000_000)


# ---------------------------------------------------------------------------
# 7. Inflation pressure
# ---------------------------------------------------------------------------

class TestInflationPressure(unittest.TestCase):

    def test_low_inflation(self):
        # annualized < 5%
        p = _proto(current_supply=100_000_000.0, emissions_per_day=100.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["inflation_pressure"], "LOW")

    def test_moderate_inflation(self):
        # annualized between 5% and 20%
        # daily = x/100M → annualized = x*365/100M*100 ≥ 5% → x ≥ 13699
        # annualized < 20% → x < 54795
        p = _proto(current_supply=1_000_000.0, emissions_per_day=200.0)
        r = _analyze_protocol(p, 5.0)
        ann = r["annualized_inflation_pct"]
        self.assertGreaterEqual(ann, 5.0)
        self.assertLess(ann, 20.0)
        self.assertEqual(r["inflation_pressure"], "MODERATE")

    def test_high_inflation(self):
        # annualized between 20% and 100%
        # 600/1M*100*365 = 21.9% → HIGH
        p = _proto(current_supply=1_000_000.0, emissions_per_day=600.0)
        r = _analyze_protocol(p, 5.0)
        ann = r["annualized_inflation_pct"]
        self.assertGreaterEqual(ann, 20.0)
        self.assertLess(ann, 100.0)
        self.assertEqual(r["inflation_pressure"], "HIGH")

    def test_hyperinflationary(self):
        # annualized >= 100%
        p = _proto(current_supply=1_000_000.0, emissions_per_day=3_000.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["inflation_pressure"], "HYPERINFLATIONARY")

    def test_zero_emission_is_low(self):
        p = _proto(emissions_per_day=0.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["inflation_pressure"], "LOW")

    def test_custom_alert_pct(self):
        # With alert=10, something with 7% ann should be MODERATE (not LOW)
        p = _proto(current_supply=1_000_000.0, emissions_per_day=200.0)
        r_default = _analyze_protocol(p, 5.0)
        r_high_alert = _analyze_protocol(p, 10.0)
        # annualized = 200/1M*365*100 = 7.3%
        # With alert=5: MODERATE; with alert=10: LOW
        self.assertEqual(r_default["inflation_pressure"], "MODERATE")
        self.assertEqual(r_high_alert["inflation_pressure"], "LOW")


# ---------------------------------------------------------------------------
# 8. Sustainability
# ---------------------------------------------------------------------------

class TestSustainability(unittest.TestCase):

    def test_deflationary_zero_emissions(self):
        p = _proto(emissions_per_day=0.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["sustainability"], "DEFLATIONARY")

    def test_revenue_backed(self):
        # revenue >= emission_value
        p = _proto(emissions_per_day=1_000.0, token_price_usd=1.0, revenue_daily_usd=2_000.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["sustainability"], "REVENUE_BACKED")

    def test_revenue_backed_exactly_one(self):
        p = _proto(emissions_per_day=1_000.0, token_price_usd=1.0, revenue_daily_usd=1_000.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["sustainability"], "REVENUE_BACKED")

    def test_partially_backed(self):
        # 0.5 <= ratio < 1.0
        p = _proto(emissions_per_day=1_000.0, token_price_usd=1.0, revenue_daily_usd=600.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["sustainability"], "PARTIALLY_BACKED")

    def test_partially_backed_exactly_0_5(self):
        p = _proto(emissions_per_day=1_000.0, token_price_usd=1.0, revenue_daily_usd=500.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["sustainability"], "PARTIALLY_BACKED")

    def test_unsustainable(self):
        # ratio < 0.5
        p = _proto(emissions_per_day=1_000.0, token_price_usd=1.0, revenue_daily_usd=100.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["sustainability"], "UNSUSTAINABLE")

    def test_zero_revenue_unsustainable(self):
        p = _proto(emissions_per_day=1_000.0, token_price_usd=1.0, revenue_daily_usd=0.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["sustainability"], "UNSUSTAINABLE")

    def test_negative_emissions_treated_as_zero(self):
        p = _proto(emissions_per_day=-100.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["sustainability"], "DEFLATIONARY")


# ---------------------------------------------------------------------------
# 9. Flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):

    def test_flag_high_inflation(self):
        p = _proto(current_supply=1_000_000.0, emissions_per_day=200.0)
        r = _analyze_protocol(p, 5.0)
        matching = [f for f in r["flags"] if "Annual inflation" in f]
        self.assertEqual(len(matching), 1)

    def test_flag_revenue_not_cover(self):
        p = _proto(emissions_per_day=1_000.0, token_price_usd=1.0, revenue_daily_usd=100.0)
        r = _analyze_protocol(p, 5.0)
        self.assertIn("Revenue does not cover emissions", r["flags"])

    def test_flag_major_unlock_approaching(self):
        schedule = [{"days_until": 10, "tokens_unlocking": 1_000_000}]
        p = _proto(unlock_schedule=schedule)
        r = _analyze_protocol(p, 5.0)
        self.assertIn("Major unlock event approaching", r["flags"])

    def test_no_flag_unlock_far_future(self):
        schedule = [{"days_until": 90, "tokens_unlocking": 1_000_000}]
        p = _proto(unlock_schedule=schedule)
        r = _analyze_protocol(p, 5.0)
        self.assertNotIn("Major unlock event approaching", r["flags"])

    def test_flag_unlimited_supply(self):
        p = _proto(max_supply=0.0, emissions_per_day=1_000.0)
        r = _analyze_protocol(p, 5.0)
        self.assertIn("Unlimited supply — no hard cap", r["flags"])

    def test_no_flag_unlimited_supply_when_zero_emissions(self):
        p = _proto(max_supply=0.0, emissions_per_day=0.0)
        r = _analyze_protocol(p, 5.0)
        self.assertNotIn("Unlimited supply — no hard cap", r["flags"])

    def test_flag_near_fully_diluted(self):
        # supply_remaining < 10%: current = 9.5M, max = 10M → 5% remaining
        p = _proto(current_supply=9_500_000.0, max_supply=10_000_000.0, emissions_per_day=100.0)
        r = _analyze_protocol(p, 5.0)
        self.assertIn("Near fully diluted", r["flags"])

    def test_no_flag_near_diluted_when_unlimited(self):
        p = _proto(max_supply=0.0, emissions_per_day=100.0)
        r = _analyze_protocol(p, 5.0)
        self.assertNotIn("Near fully diluted", r["flags"])

    def test_flag_no_protocol_revenue(self):
        p = _proto(emissions_per_day=100.0, revenue_daily_usd=0.0)
        r = _analyze_protocol(p, 5.0)
        self.assertIn("No protocol revenue", r["flags"])

    def test_no_flag_revenue_when_zero_emissions(self):
        p = _proto(emissions_per_day=0.0, revenue_daily_usd=0.0)
        r = _analyze_protocol(p, 5.0)
        self.assertNotIn("No protocol revenue", r["flags"])

    def test_flags_is_list(self):
        p = _proto()
        r = _analyze_protocol(p, 5.0)
        self.assertIsInstance(r["flags"], list)

    def test_no_flags_when_healthy(self):
        # Zero inflation, 50% supply remaining, no unlock → no flags
        p = _proto(emissions_per_day=0.0, revenue_daily_usd=10_000.0,
                   current_supply=5_000_000.0, max_supply=10_000_000.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["flags"], [])

    def test_unlock_exactly_30_days(self):
        schedule = [{"days_until": 30, "tokens_unlocking": 500_000}]
        p = _proto(unlock_schedule=schedule)
        r = _analyze_protocol(p, 5.0)
        self.assertIn("Major unlock event approaching", r["flags"])


# ---------------------------------------------------------------------------
# 10. analyze() aggregate fields
# ---------------------------------------------------------------------------

class TestAnalyzeAggregate(unittest.TestCase):

    def setUp(self):
        self.protocols = [
            _proto("Alpha", current_supply=1_000_000.0, emissions_per_day=200.0,
                   token_price_usd=1.0, revenue_daily_usd=2_000.0),
            _proto("Beta", current_supply=10_000_000.0, emissions_per_day=100_000.0,
                   token_price_usd=0.01, revenue_daily_usd=50.0),
        ]

    def test_returns_dict(self):
        result = analyze(self.protocols, save_log=False)
        self.assertIsInstance(result, dict)

    def test_protocols_list_length(self):
        result = analyze(self.protocols, save_log=False)
        self.assertEqual(len(result["protocols"]), 2)

    def test_most_inflationary(self):
        result = analyze(self.protocols, save_log=False)
        # Beta has 100K/10M = 1% daily = 365% annualized
        # Alpha has 200/1M = 0.02% daily = 7.3% annualized
        self.assertEqual(result["most_inflationary"], "Beta")

    def test_most_sustainable(self):
        result = analyze(self.protocols, save_log=False)
        # Alpha: emission_value=200, revenue=2000 → ratio=10 (REVENUE_BACKED)
        # Beta: emission_value=100K*0.01=1000, revenue=50 → ratio=0.05 (UNSUSTAINABLE)
        self.assertEqual(result["most_sustainable"], "Alpha")

    def test_average_inflation(self):
        result = analyze(self.protocols, save_log=False)
        alpha_ann = result["protocols"][0]["annualized_inflation_pct"]
        beta_ann = result["protocols"][1]["annualized_inflation_pct"]
        expected = (alpha_ann + beta_ann) / 2
        self.assertAlmostEqual(result["average_inflation_pct"], expected, places=2)

    def test_timestamp_present(self):
        result = analyze(self.protocols, save_log=False)
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)

    def test_empty_protocols(self):
        result = analyze([], save_log=False)
        self.assertEqual(result["protocols"], [])
        self.assertIsNone(result["most_inflationary"])
        self.assertIsNone(result["most_sustainable"])
        self.assertEqual(result["average_inflation_pct"], 0.0)

    def test_output_keys(self):
        result = analyze([_proto()], save_log=False)
        expected = {"protocols", "most_inflationary", "most_sustainable",
                    "average_inflation_pct", "timestamp"}
        self.assertEqual(set(result.keys()), expected)

    def test_single_protocol(self):
        result = analyze([_proto("Solo")], save_log=False)
        self.assertEqual(result["most_inflationary"], "Solo")
        self.assertEqual(result["most_sustainable"], "Solo")

    def test_protocol_output_keys(self):
        result = analyze([_proto()], save_log=False)
        expected = {
            "name", "token_symbol", "daily_inflation_pct", "annualized_inflation_pct",
            "emission_value_usd_daily", "revenue_coverage_ratio", "supply_remaining_pct",
            "days_to_fully_diluted", "next_major_unlock", "inflation_pressure",
            "sustainability", "flags",
        }
        self.assertEqual(set(result["protocols"][0].keys()), expected)


# ---------------------------------------------------------------------------
# 11. Log persistence
# ---------------------------------------------------------------------------

class TestLogPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "token_emission_log.json")

    def _run(self, save=True):
        return analyze([_proto()], data_dir=self.tmp_dir, save_log=save)

    def test_log_created_on_save(self):
        self._run(save=True)
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_not_created_when_no_save(self):
        self._run(save=False)
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self._run()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends(self):
        self._run()
        self._run()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_ring_buffer_100(self):
        for _ in range(110):
            self._run()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_entry_has_timestamp(self):
        self._run()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_load_log_missing_file(self):
        result = _load_log("/nonexistent/path/log.json")
        self.assertEqual(result, [])

    def test_save_and_reload(self):
        self._run()
        loaded = _load_log(self.log_path)
        self.assertEqual(len(loaded), 1)
        self.assertIn("protocols", loaded[0])

    def test_atomic_write(self):
        entries = [{"test": "value"}]
        _save_log(self.log_path, entries)
        self.assertTrue(os.path.exists(self.log_path))
        loaded = _load_log(self.log_path)
        self.assertEqual(loaded[0]["test"], "value")

    def test_log_cap_exactly_100(self):
        for _ in range(100):
            self._run()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)


# ---------------------------------------------------------------------------
# 12. Config override
# ---------------------------------------------------------------------------

class TestConfigOverride(unittest.TestCase):

    def test_custom_inflation_alert(self):
        # annualized = 7.3%; with alert=5 → MODERATE; with alert=10 → LOW
        p = _proto(current_supply=1_000_000.0, emissions_per_day=200.0)
        r1 = analyze([p], config={"inflation_alert_pct": 5.0}, save_log=False)
        r2 = analyze([p], config={"inflation_alert_pct": 10.0}, save_log=False)
        self.assertEqual(r1["protocols"][0]["inflation_pressure"], "MODERATE")
        self.assertEqual(r2["protocols"][0]["inflation_pressure"], "LOW")

    def test_default_config_none(self):
        p = _proto()
        r1 = analyze([p], config=None, save_log=False)
        r2 = analyze([p], config={}, save_log=False)
        self.assertEqual(
            r1["protocols"][0]["inflation_pressure"],
            r2["protocols"][0]["inflation_pressure"],
        )


# ---------------------------------------------------------------------------
# 13. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_name_preserved(self):
        p = _proto(name="UniqueProtocolName")
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["name"], "UniqueProtocolName")

    def test_token_symbol_preserved(self):
        p = _proto(token_symbol="XYZ")
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["token_symbol"], "XYZ")

    def test_negative_emissions_treated_as_zero(self):
        p = _proto(emissions_per_day=-500.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["daily_inflation_pct"], 0.0)
        self.assertEqual(r["emission_value_usd_daily"], 0.0)
        self.assertEqual(r["sustainability"], "DEFLATIONARY")

    def test_multiple_most_inflationary_is_highest(self):
        p1 = _proto("Low", current_supply=1_000_000.0, emissions_per_day=100.0)
        p2 = _proto("High", current_supply=1_000_000.0, emissions_per_day=10_000.0)
        result = analyze([p1, p2], save_log=False)
        self.assertEqual(result["most_inflationary"], "High")

    def test_most_sustainable_prefers_revenue_backed(self):
        # p1: PARTIALLY_BACKED with high ratio; p2: REVENUE_BACKED with lower ratio
        p1 = _proto("PB", emissions_per_day=1_000.0, token_price_usd=1.0, revenue_daily_usd=600.0)
        p2 = _proto("RB", emissions_per_day=1_000.0, token_price_usd=1.0, revenue_daily_usd=1_100.0)
        result = analyze([p1, p2], save_log=False)
        # p2 is REVENUE_BACKED, so it wins
        self.assertEqual(result["most_sustainable"], "RB")

    def test_most_sustainable_among_deflationary(self):
        # Two deflationary: both have ratio=999; pick first (or highest ratio)
        p1 = _proto("D1", emissions_per_day=0.0)
        p2 = _proto("D2", emissions_per_day=0.0)
        result = analyze([p1, p2], save_log=False)
        # Both have ratio=999; either could be most_sustainable
        self.assertIn(result["most_sustainable"], ["D1", "D2"])

    def test_missing_fields_no_crash(self):
        p = {"name": "Minimal"}
        r = _analyze_protocol(p, 5.0)
        self.assertIsInstance(r, dict)

    def test_inflation_pressure_valid_values(self):
        valid = {"LOW", "MODERATE", "HIGH", "HYPERINFLATIONARY"}
        for emissions in [0, 50, 200, 400, 5000]:
            p = _proto(current_supply=1_000_000.0, emissions_per_day=float(emissions))
            r = _analyze_protocol(p, 5.0)
            self.assertIn(r["inflation_pressure"], valid)

    def test_sustainability_valid_values(self):
        valid = {"DEFLATIONARY", "REVENUE_BACKED", "PARTIALLY_BACKED", "UNSUSTAINABLE"}
        for (emi, rev) in [(0, 0), (1000, 2000), (1000, 600), (1000, 100)]:
            p = _proto(emissions_per_day=float(emi), revenue_daily_usd=float(rev),
                       token_price_usd=1.0)
            r = _analyze_protocol(p, 5.0)
            self.assertIn(r["sustainability"], valid)

    def test_average_inflation_single_protocol(self):
        p = _proto(current_supply=1_000_000.0, emissions_per_day=200.0)
        result = analyze([p], save_log=False)
        self.assertAlmostEqual(
            result["average_inflation_pct"],
            result["protocols"][0]["annualized_inflation_pct"],
            places=4,
        )

    def test_supply_remaining_clipped_to_zero(self):
        # current > max → clipped to 0
        p = _proto(current_supply=15_000_000.0, max_supply=10_000_000.0)
        r = _analyze_protocol(p, 5.0)
        self.assertEqual(r["supply_remaining_pct"], 0.0)

    def test_near_fully_diluted_flag_threshold(self):
        # 9.5% remaining → just below 10% → flag
        p = _proto(current_supply=9_050_000.0, max_supply=10_000_000.0, emissions_per_day=100.0)
        r = _analyze_protocol(p, 5.0)
        self.assertIn("Near fully diluted", r["flags"])

    def test_not_near_fully_diluted_above_threshold(self):
        # 15% remaining → above 10% → no flag
        p = _proto(current_supply=8_500_000.0, max_supply=10_000_000.0, emissions_per_day=100.0)
        r = _analyze_protocol(p, 5.0)
        self.assertNotIn("Near fully diluted", r["flags"])


if __name__ == "__main__":
    unittest.main()
