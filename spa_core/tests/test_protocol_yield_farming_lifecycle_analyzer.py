"""
Tests for MP-987: ProtocolYieldFarmingLifecycleAnalyzer
Run with: python3 -m unittest spa_core.tests.test_protocol_yield_farming_lifecycle_analyzer
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_yield_farming_lifecycle_analyzer import (
    ProtocolYieldFarmingLifecycleAnalyzer,
    _analyze_farm,
    _classify_lifecycle,
    LABEL_LAUNCH_PHASE,
    LABEL_GROWTH_PHASE,
    LABEL_MATURITY,
    LABEL_DECLINE,
    LABEL_SUNSET,
    LABEL_ZOMBIE,
    FLAG_APY_CRASHED,
    FLAG_MERCENARY_CAPITAL,
    FLAG_EMISSIONS_ENDING_SOON,
    FLAG_HIGH_VALUE_EXTRACTION,
    FLAG_STICKY_FARMERS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_farm(
    protocol="Uniswap",
    pair="ETH/USDC",
    launch_date_days_ago=60,
    initial_apy_pct=40.0,
    current_apy_pct=20.0,
    peak_apy_pct=45.0,
    tvl_at_launch_usd=5_000_000,
    tvl_at_peak_usd=10_000_000,
    tvl_current_usd=7_000_000,
    emission_schedule_remaining_pct=50.0,
    unique_farmers_current=500,
    unique_farmers_at_peak=800,
    rewards_claimed_pct=30.0,
    is_deprecated=False,
):
    return {
        "protocol": protocol,
        "pair": pair,
        "launch_date_days_ago": launch_date_days_ago,
        "initial_apy_pct": initial_apy_pct,
        "current_apy_pct": current_apy_pct,
        "peak_apy_pct": peak_apy_pct,
        "tvl_at_launch_usd": tvl_at_launch_usd,
        "tvl_at_peak_usd": tvl_at_peak_usd,
        "tvl_current_usd": tvl_current_usd,
        "emission_schedule_remaining_pct": emission_schedule_remaining_pct,
        "unique_farmers_current": unique_farmers_current,
        "unique_farmers_at_peak": unique_farmers_at_peak,
        "rewards_claimed_pct": rewards_claimed_pct,
        "is_deprecated": is_deprecated,
    }


def _make_analyzer(tmp_dir):
    log_path = os.path.join(tmp_dir, "farming_lifecycle_log.json")
    return ProtocolYieldFarmingLifecycleAnalyzer(log_path=log_path), log_path


# ---------------------------------------------------------------------------
# 1. _analyze_farm basics
# ---------------------------------------------------------------------------

class TestAnalyzeFarmBasics(unittest.TestCase):

    def test_returns_required_keys(self):
        farm = _make_farm()
        r = _analyze_farm(farm)
        for key in ("protocol", "pair", "apy_decay_rate_pct", "tvl_retention_rate_pct",
                    "farmer_retention_rate_pct", "lifecycle_stage_days",
                    "value_extraction_ratio", "lifecycle_label", "flags"):
            self.assertIn(key, r)

    def test_protocol_and_pair_preserved(self):
        farm = _make_farm(protocol="Curve", pair="3pool")
        r = _analyze_farm(farm)
        self.assertEqual(r["protocol"], "Curve")
        self.assertEqual(r["pair"], "3pool")

    def test_apy_decay_rate_zero_when_current_equals_peak(self):
        farm = _make_farm(current_apy_pct=45.0, peak_apy_pct=45.0)
        r = _analyze_farm(farm)
        self.assertAlmostEqual(r["apy_decay_rate_pct"], 0.0, places=2)

    def test_apy_decay_rate_100_when_current_zero(self):
        farm = _make_farm(current_apy_pct=0.0, peak_apy_pct=40.0)
        r = _analyze_farm(farm)
        self.assertAlmostEqual(r["apy_decay_rate_pct"], 100.0, places=2)

    def test_apy_decay_rate_50_pct(self):
        farm = _make_farm(current_apy_pct=20.0, peak_apy_pct=40.0)
        r = _analyze_farm(farm)
        self.assertAlmostEqual(r["apy_decay_rate_pct"], 50.0, places=2)

    def test_tvl_retention_full(self):
        farm = _make_farm(tvl_current_usd=10_000_000, tvl_at_peak_usd=10_000_000)
        r = _analyze_farm(farm)
        self.assertAlmostEqual(r["tvl_retention_rate_pct"], 100.0, places=1)

    def test_tvl_retention_half(self):
        farm = _make_farm(tvl_current_usd=5_000_000, tvl_at_peak_usd=10_000_000)
        r = _analyze_farm(farm)
        self.assertAlmostEqual(r["tvl_retention_rate_pct"], 50.0, places=1)

    def test_tvl_retention_zero_peak(self):
        """When tvl_at_peak=0, retention defaults to 100%."""
        farm = _make_farm(tvl_at_peak_usd=0, tvl_current_usd=0)
        r = _analyze_farm(farm)
        self.assertAlmostEqual(r["tvl_retention_rate_pct"], 100.0, places=1)

    def test_farmer_retention_full(self):
        farm = _make_farm(unique_farmers_current=800, unique_farmers_at_peak=800)
        r = _analyze_farm(farm)
        self.assertAlmostEqual(r["farmer_retention_rate_pct"], 100.0, places=1)

    def test_farmer_retention_partial(self):
        farm = _make_farm(unique_farmers_current=400, unique_farmers_at_peak=800)
        r = _analyze_farm(farm)
        self.assertAlmostEqual(r["farmer_retention_rate_pct"], 50.0, places=1)

    def test_farmer_retention_zero_peak(self):
        """When unique_farmers_at_peak=0, retention defaults to 100%."""
        farm = _make_farm(unique_farmers_current=0, unique_farmers_at_peak=0)
        r = _analyze_farm(farm)
        self.assertAlmostEqual(r["farmer_retention_rate_pct"], 100.0, places=1)

    def test_lifecycle_stage_days_equals_launch_days_ago(self):
        farm = _make_farm(launch_date_days_ago=90)
        r = _analyze_farm(farm)
        self.assertEqual(r["lifecycle_stage_days"], 90)


# ---------------------------------------------------------------------------
# 2. Lifecycle labels
# ---------------------------------------------------------------------------

class TestLifecycleLabels(unittest.TestCase):

    def test_sunset_when_deprecated(self):
        farm = _make_farm(is_deprecated=True)
        r = _analyze_farm(farm)
        self.assertEqual(r["lifecycle_label"], LABEL_SUNSET)

    def test_zombie_low_apy_low_farmers(self):
        farm = _make_farm(
            current_apy_pct=0.5,
            unique_farmers_current=3,
            is_deprecated=False,
        )
        r = _analyze_farm(farm)
        self.assertEqual(r["lifecycle_label"], LABEL_ZOMBIE)

    def test_zombie_boundary_apy_exactly_2(self):
        """APY = 2.0 (not < 2.0) → not zombie purely on APY."""
        farm = _make_farm(
            current_apy_pct=2.0,
            unique_farmers_current=3,
            is_deprecated=False,
        )
        r = _analyze_farm(farm)
        # 2.0 is NOT < 2.0, so should not be zombie
        self.assertNotEqual(r["lifecycle_label"], LABEL_ZOMBIE)

    def test_zombie_boundary_farmers_exactly_10(self):
        """10 farmers (not < 10) → not zombie purely on farmer count."""
        farm = _make_farm(
            current_apy_pct=0.5,
            unique_farmers_current=10,
            is_deprecated=False,
        )
        r = _analyze_farm(farm)
        self.assertNotEqual(r["lifecycle_label"], LABEL_ZOMBIE)

    def test_launch_phase(self):
        farm = _make_farm(
            launch_date_days_ago=10,
            current_apy_pct=40.0,
            peak_apy_pct=44.0,  # current >= 0.8 * peak
        )
        r = _analyze_farm(farm)
        self.assertEqual(r["lifecycle_label"], LABEL_LAUNCH_PHASE)

    def test_launch_phase_not_triggered_if_old(self):
        """Farm > 30 days old should not be LAUNCH_PHASE even if APY near peak."""
        farm = _make_farm(
            launch_date_days_ago=45,
            current_apy_pct=40.0,
            peak_apy_pct=44.0,
        )
        r = _analyze_farm(farm)
        self.assertNotEqual(r["lifecycle_label"], LABEL_LAUNCH_PHASE)

    def test_growth_phase(self):
        farm = _make_farm(
            launch_date_days_ago=60,
            current_apy_pct=35.0,
            peak_apy_pct=40.0,
            tvl_current_usd=9_500_000,
            tvl_at_peak_usd=10_000_000,
            unique_farmers_current=820,
            unique_farmers_at_peak=900,
            emission_schedule_remaining_pct=60.0,
        )
        r = _analyze_farm(farm)
        self.assertEqual(r["lifecycle_label"], LABEL_GROWTH_PHASE)

    def test_decline_low_tvl_retention(self):
        farm = _make_farm(
            tvl_current_usd=2_000_000,
            tvl_at_peak_usd=10_000_000,  # 20% retention
            unique_farmers_current=600,
            unique_farmers_at_peak=800,
        )
        r = _analyze_farm(farm)
        self.assertEqual(r["lifecycle_label"], LABEL_DECLINE)

    def test_decline_low_farmer_retention(self):
        farm = _make_farm(
            tvl_current_usd=9_000_000,
            tvl_at_peak_usd=10_000_000,
            unique_farmers_current=150,
            unique_farmers_at_peak=800,  # 18.75% retention
        )
        r = _analyze_farm(farm)
        self.assertEqual(r["lifecycle_label"], LABEL_DECLINE)

    def test_maturity_label(self):
        """Mid-lifecycle, not declining severely → MATURITY."""
        farm = _make_farm(
            launch_date_days_ago=180,
            current_apy_pct=15.0,
            peak_apy_pct=40.0,
            tvl_current_usd=6_000_000,
            tvl_at_peak_usd=10_000_000,   # 60% retention
            unique_farmers_current=450,
            unique_farmers_at_peak=800,    # 56.25% retention
            emission_schedule_remaining_pct=30.0,
        )
        r = _analyze_farm(farm)
        self.assertEqual(r["lifecycle_label"], LABEL_MATURITY)

    def test_sunset_precedence_over_zombie(self):
        """is_deprecated=True → SUNSET even if would qualify as zombie."""
        farm = _make_farm(
            is_deprecated=True,
            current_apy_pct=0.5,
            unique_farmers_current=2,
        )
        r = _analyze_farm(farm)
        self.assertEqual(r["lifecycle_label"], LABEL_SUNSET)

    def test_all_labels_are_strings(self):
        for lbl in (LABEL_LAUNCH_PHASE, LABEL_GROWTH_PHASE, LABEL_MATURITY,
                    LABEL_DECLINE, LABEL_SUNSET, LABEL_ZOMBIE):
            self.assertIsInstance(lbl, str)
            self.assertTrue(lbl)


# ---------------------------------------------------------------------------
# 3. Flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):

    def test_apy_crashed_flag(self):
        farm = _make_farm(current_apy_pct=3.0, peak_apy_pct=50.0)  # < 10% of peak
        r = _analyze_farm(farm)
        self.assertIn(FLAG_APY_CRASHED, r["flags"])

    def test_no_apy_crashed_above_threshold(self):
        farm = _make_farm(current_apy_pct=6.0, peak_apy_pct=50.0)  # 12% of peak
        r = _analyze_farm(farm)
        self.assertNotIn(FLAG_APY_CRASHED, r["flags"])

    def test_apy_crashed_boundary_exactly_10_pct(self):
        """current == peak * 0.1 → NOT crashed (not < 0.1)."""
        farm = _make_farm(current_apy_pct=5.0, peak_apy_pct=50.0)
        r = _analyze_farm(farm)
        self.assertNotIn(FLAG_APY_CRASHED, r["flags"])

    def test_mercenary_capital_flag(self):
        farm = _make_farm(
            unique_farmers_current=100,
            unique_farmers_at_peak=800,   # 12.5% retention
            tvl_current_usd=1_500_000,
            tvl_at_peak_usd=10_000_000,   # 15% retention
        )
        r = _analyze_farm(farm)
        self.assertIn(FLAG_MERCENARY_CAPITAL, r["flags"])

    def test_no_mercenary_if_only_low_farmer_retention(self):
        """Both conditions must hold for MERCENARY_CAPITAL."""
        farm = _make_farm(
            unique_farmers_current=100,
            unique_farmers_at_peak=800,   # 12.5% — low
            tvl_current_usd=6_000_000,
            tvl_at_peak_usd=10_000_000,   # 60% — NOT low
        )
        r = _analyze_farm(farm)
        self.assertNotIn(FLAG_MERCENARY_CAPITAL, r["flags"])

    def test_no_mercenary_if_only_low_tvl_retention(self):
        farm = _make_farm(
            unique_farmers_current=500,
            unique_farmers_at_peak=800,   # 62.5% — NOT low
            tvl_current_usd=2_000_000,
            tvl_at_peak_usd=10_000_000,   # 20% — low
        )
        r = _analyze_farm(farm)
        self.assertNotIn(FLAG_MERCENARY_CAPITAL, r["flags"])

    def test_emissions_ending_soon_flag(self):
        farm = _make_farm(emission_schedule_remaining_pct=5.0)
        r = _analyze_farm(farm)
        self.assertIn(FLAG_EMISSIONS_ENDING_SOON, r["flags"])

    def test_no_emissions_ending_soon_above_threshold(self):
        farm = _make_farm(emission_schedule_remaining_pct=10.0)
        r = _analyze_farm(farm)
        self.assertNotIn(FLAG_EMISSIONS_ENDING_SOON, r["flags"])

    def test_emissions_ending_exactly_10_pct(self):
        """10% is not < 10, so flag should NOT be set."""
        farm = _make_farm(emission_schedule_remaining_pct=10.0)
        r = _analyze_farm(farm)
        self.assertNotIn(FLAG_EMISSIONS_ENDING_SOON, r["flags"])

    def test_high_value_extraction_flag(self):
        """rewards_claimed > 50% → HIGH_VALUE_EXTRACTION."""
        farm = _make_farm(rewards_claimed_pct=75.0, tvl_at_launch_usd=10_000_000)
        r = _analyze_farm(farm)
        self.assertIn(FLAG_HIGH_VALUE_EXTRACTION, r["flags"])

    def test_no_high_value_extraction_below_50(self):
        farm = _make_farm(rewards_claimed_pct=40.0, tvl_at_launch_usd=10_000_000)
        r = _analyze_farm(farm)
        self.assertNotIn(FLAG_HIGH_VALUE_EXTRACTION, r["flags"])

    def test_sticky_farmers_flag(self):
        farm = _make_farm(
            unique_farmers_current=750,
            unique_farmers_at_peak=1000,  # 75% retention > 70%
        )
        r = _analyze_farm(farm)
        self.assertIn(FLAG_STICKY_FARMERS, r["flags"])

    def test_no_sticky_farmers_below_threshold(self):
        farm = _make_farm(
            unique_farmers_current=600,
            unique_farmers_at_peak=1000,  # 60% retention < 70%
        )
        r = _analyze_farm(farm)
        self.assertNotIn(FLAG_STICKY_FARMERS, r["flags"])

    def test_sticky_farmers_boundary_exactly_70(self):
        """70% retention is NOT > 70, so flag should NOT be set."""
        farm = _make_farm(
            unique_farmers_current=700,
            unique_farmers_at_peak=1000,
        )
        r = _analyze_farm(farm)
        self.assertNotIn(FLAG_STICKY_FARMERS, r["flags"])

    def test_all_flags_possible_simultaneously(self):
        farm = _make_farm(
            current_apy_pct=1.0,
            peak_apy_pct=50.0,              # APY_CRASHED
            unique_farmers_current=100,
            unique_farmers_at_peak=800,     # MERCENARY_CAPITAL (also low TVL retention)
            tvl_current_usd=2_000_000,
            tvl_at_peak_usd=10_000_000,
            emission_schedule_remaining_pct=5.0,  # EMISSIONS_ENDING_SOON
            rewards_claimed_pct=80.0,        # HIGH_VALUE_EXTRACTION
        )
        r = _analyze_farm(farm)
        self.assertIn(FLAG_APY_CRASHED, r["flags"])
        self.assertIn(FLAG_MERCENARY_CAPITAL, r["flags"])
        self.assertIn(FLAG_EMISSIONS_ENDING_SOON, r["flags"])
        self.assertIn(FLAG_HIGH_VALUE_EXTRACTION, r["flags"])

    def test_no_flags_healthy_farm(self):
        farm = _make_farm(
            current_apy_pct=30.0,
            peak_apy_pct=40.0,
            unique_farmers_current=750,
            unique_farmers_at_peak=800,
            tvl_current_usd=9_500_000,
            tvl_at_peak_usd=10_000_000,
            emission_schedule_remaining_pct=60.0,
            rewards_claimed_pct=20.0,
        )
        r = _analyze_farm(farm)
        # No crash, no mercenary, no ending emissions, no high extraction
        self.assertNotIn(FLAG_APY_CRASHED, r["flags"])
        self.assertNotIn(FLAG_MERCENARY_CAPITAL, r["flags"])
        self.assertNotIn(FLAG_EMISSIONS_ENDING_SOON, r["flags"])
        self.assertNotIn(FLAG_HIGH_VALUE_EXTRACTION, r["flags"])


# ---------------------------------------------------------------------------
# 4. ProtocolYieldFarmingLifecycleAnalyzer.analyze()
# ---------------------------------------------------------------------------

class TestAnalyzerBasic(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer, self.log_path = _make_analyzer(self.tmp)

    def test_empty_farms_returns_valid_structure(self):
        result = self.analyzer.analyze([])
        self.assertIn("farms", result)
        self.assertIn("aggregates", result)
        self.assertIn("timestamp", result)
        self.assertEqual(result["farms"], [])

    def test_empty_farms_aggregates(self):
        result = self.analyzer.analyze([])
        agg = result["aggregates"]
        self.assertIsNone(agg["newest_farm"])
        self.assertIsNone(agg["oldest_farm"])
        self.assertEqual(agg["average_tvl_retention"], 0.0)
        self.assertEqual(agg["zombie_count"], 0)
        self.assertEqual(agg["sunset_count"], 0)
        self.assertEqual(agg["total_farms"], 0)

    def test_single_farm_analyzed(self):
        result = self.analyzer.analyze([_make_farm()])
        self.assertEqual(len(result["farms"]), 1)
        self.assertEqual(result["aggregates"]["total_farms"], 1)

    def test_multiple_farms_all_analyzed(self):
        farms = [_make_farm(protocol=f"P{i}") for i in range(4)]
        result = self.analyzer.analyze(farms)
        self.assertEqual(len(result["farms"]), 4)
        self.assertEqual(result["aggregates"]["total_farms"], 4)

    def test_newest_farm_is_minimum_days(self):
        farms = [
            _make_farm(protocol="New", launch_date_days_ago=5),
            _make_farm(protocol="Old", launch_date_days_ago=365),
        ]
        result = self.analyzer.analyze(farms)
        self.assertEqual(result["aggregates"]["newest_farm"]["protocol"], "New")

    def test_oldest_farm_is_maximum_days(self):
        farms = [
            _make_farm(protocol="New", launch_date_days_ago=5),
            _make_farm(protocol="Old", launch_date_days_ago=365),
        ]
        result = self.analyzer.analyze(farms)
        self.assertEqual(result["aggregates"]["oldest_farm"]["protocol"], "Old")

    def test_average_tvl_retention_correct(self):
        farms = [
            _make_farm(tvl_current_usd=10_000_000, tvl_at_peak_usd=10_000_000),  # 100%
            _make_farm(tvl_current_usd=5_000_000,  tvl_at_peak_usd=10_000_000),  # 50%
        ]
        result = self.analyzer.analyze(farms)
        self.assertAlmostEqual(result["aggregates"]["average_tvl_retention"], 75.0, places=1)

    def test_zombie_count(self):
        farms = [
            _make_farm(current_apy_pct=0.5, unique_farmers_current=3),
            _make_farm(current_apy_pct=20.0, unique_farmers_current=500),
        ]
        result = self.analyzer.analyze(farms)
        self.assertEqual(result["aggregates"]["zombie_count"], 1)

    def test_sunset_count(self):
        farms = [
            _make_farm(is_deprecated=True),
            _make_farm(is_deprecated=True),
            _make_farm(is_deprecated=False),
        ]
        result = self.analyzer.analyze(farms)
        self.assertEqual(result["aggregates"]["sunset_count"], 2)

    def test_timestamp_present(self):
        result = self.analyzer.analyze([_make_farm()])
        self.assertIn("T", result["timestamp"])

    def test_config_log_path_override(self):
        alt_log = os.path.join(self.tmp, "alt_farming.json")
        self.analyzer.analyze([_make_farm()], config={"log_path": alt_log})
        self.assertTrue(os.path.exists(alt_log))

    def test_none_config_uses_default(self):
        result = self.analyzer.analyze([_make_farm()], config=None)
        self.assertIn("aggregates", result)


# ---------------------------------------------------------------------------
# 5. Ring-buffer log
# ---------------------------------------------------------------------------

class TestFarmingLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer, self.log_path = _make_analyzer(self.tmp)

    def test_log_created_after_analyze(self):
        self.analyzer.analyze([_make_farm()])
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.analyzer.analyze([_make_farm()])
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_appends_entries(self):
        self.analyzer.analyze([_make_farm()])
        self.analyzer.analyze([_make_farm()])
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_log_capped_at_100(self):
        for _ in range(110):
            self.analyzer.analyze([_make_farm()])
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), 100)

    def test_log_entry_has_expected_keys(self):
        self.analyzer.analyze([_make_farm()])
        with open(self.log_path) as fh:
            data = json.load(fh)
        entry = data[0]
        for key in ("timestamp", "total_farms", "average_tvl_retention",
                    "zombie_count", "sunset_count"):
            self.assertIn(key, entry)

    def test_log_empty_analyze_still_logged(self):
        self.analyzer.analyze([])
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["total_farms"], 0)

    def test_log_valid_json_after_many_writes(self):
        for i in range(10):
            self.analyzer.analyze([_make_farm(protocol=f"P{i}")])
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_ring_drops_oldest(self):
        for i in range(101):
            self.analyzer.analyze([_make_farm()],
                                  config={"log_path": self.log_path})
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 100)


# ---------------------------------------------------------------------------
# 6. Aggregates edge cases
# ---------------------------------------------------------------------------

class TestFarmingAggregatesEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer, self.log_path = _make_analyzer(self.tmp)

    def test_newest_oldest_same_when_one_farm(self):
        result = self.analyzer.analyze([_make_farm(protocol="Solo")])
        agg = result["aggregates"]
        self.assertEqual(agg["newest_farm"]["protocol"], "Solo")
        self.assertEqual(agg["oldest_farm"]["protocol"], "Solo")

    def test_aggregates_keys_present(self):
        result = self.analyzer.analyze([_make_farm()])
        for k in ("newest_farm", "oldest_farm", "average_tvl_retention",
                  "zombie_count", "sunset_count", "total_farms"):
            self.assertIn(k, result["aggregates"])

    def test_all_zombies(self):
        farms = [
            _make_farm(current_apy_pct=0.5, unique_farmers_current=2)
            for _ in range(5)
        ]
        result = self.analyzer.analyze(farms)
        self.assertEqual(result["aggregates"]["zombie_count"], 5)

    def test_all_sunsets(self):
        farms = [_make_farm(is_deprecated=True) for _ in range(3)]
        result = self.analyzer.analyze(farms)
        self.assertEqual(result["aggregates"]["sunset_count"], 3)
        self.assertEqual(result["aggregates"]["zombie_count"], 0)

    def test_zero_tvl_retention_avg(self):
        farms = [
            _make_farm(tvl_current_usd=0, tvl_at_peak_usd=10_000_000)
        ]
        result = self.analyzer.analyze(farms)
        self.assertAlmostEqual(result["aggregates"]["average_tvl_retention"], 0.0, places=1)


# ---------------------------------------------------------------------------
# 7. Construction
# ---------------------------------------------------------------------------

class TestAnalyzerConstruction(unittest.TestCase):

    def test_default_construction(self):
        analyzer = ProtocolYieldFarmingLifecycleAnalyzer()
        self.assertIsNotNone(analyzer)

    def test_custom_log_path(self):
        analyzer = ProtocolYieldFarmingLifecycleAnalyzer(log_path="/tmp/custom_farm.json")
        self.assertIsNotNone(analyzer)

    def test_analyze_method_exists(self):
        analyzer = ProtocolYieldFarmingLifecycleAnalyzer()
        self.assertTrue(callable(analyzer.analyze))


# ---------------------------------------------------------------------------
# 8. Determinism
# ---------------------------------------------------------------------------

class TestFarmingDeterminism(unittest.TestCase):

    def test_same_input_same_output(self):
        tmp = tempfile.mkdtemp()
        analyzer = ProtocolYieldFarmingLifecycleAnalyzer(
            log_path=os.path.join(tmp, "log.json")
        )
        farms = [_make_farm(), _make_farm(protocol="Curve")]
        r1 = analyzer.analyze(farms)
        r2 = analyzer.analyze(farms)
        for f1, f2 in zip(r1["farms"], r2["farms"]):
            self.assertEqual(f1["lifecycle_label"], f2["lifecycle_label"])
            self.assertEqual(f1["apy_decay_rate_pct"], f2["apy_decay_rate_pct"])
            self.assertEqual(f1["flags"], f2["flags"])

    def test_analyze_farm_deterministic(self):
        farm = _make_farm(current_apy_pct=5.0, peak_apy_pct=50.0)
        r1 = _analyze_farm(farm)
        r2 = _analyze_farm(farm)
        self.assertEqual(r1["lifecycle_label"], r2["lifecycle_label"])
        self.assertEqual(r1["apy_decay_rate_pct"], r2["apy_decay_rate_pct"])


# ---------------------------------------------------------------------------
# 9. Miscellaneous
# ---------------------------------------------------------------------------

class TestFarmingMisc(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer, self.log_path = _make_analyzer(self.tmp)

    def test_analyze_returns_dict(self):
        result = self.analyzer.analyze([_make_farm()])
        self.assertIsInstance(result, dict)

    def test_farms_list_in_result(self):
        result = self.analyzer.analyze([_make_farm(), _make_farm()])
        self.assertIsInstance(result["farms"], list)

    def test_flags_is_list(self):
        r = _analyze_farm(_make_farm())
        self.assertIsInstance(r["flags"], list)

    def test_lifecycle_label_is_string(self):
        r = _analyze_farm(_make_farm())
        self.assertIsInstance(r["lifecycle_label"], str)
        self.assertTrue(r["lifecycle_label"])

    def test_apy_decay_capped_at_100(self):
        """Even with negative current APY, decay rate should not exceed 100."""
        farm = _make_farm(current_apy_pct=-10.0, peak_apy_pct=50.0)
        r = _analyze_farm(farm)
        self.assertLessEqual(r["apy_decay_rate_pct"], 100.0)

    def test_tvl_retention_capped_at_200(self):
        """If current > 2× peak, cap at 200%."""
        farm = _make_farm(tvl_current_usd=25_000_000, tvl_at_peak_usd=10_000_000)
        r = _analyze_farm(farm)
        self.assertLessEqual(r["tvl_retention_rate_pct"], 200.0)

    def test_farmer_retention_capped_at_200(self):
        farm = _make_farm(unique_farmers_current=2500, unique_farmers_at_peak=1000)
        r = _analyze_farm(farm)
        self.assertLessEqual(r["farmer_retention_rate_pct"], 200.0)

    def test_value_extraction_ratio_non_negative(self):
        farm = _make_farm(rewards_claimed_pct=0.0)
        r = _analyze_farm(farm)
        self.assertGreaterEqual(r["value_extraction_ratio"], 0.0)

    def test_emission_remaining_preserved(self):
        farm = _make_farm(emission_schedule_remaining_pct=33.3)
        r = _analyze_farm(farm)
        self.assertAlmostEqual(r["emission_schedule_remaining_pct"], 33.3, places=1)

    def test_is_deprecated_preserved(self):
        farm = _make_farm(is_deprecated=True)
        r = _analyze_farm(farm)
        self.assertTrue(r["is_deprecated"])

    def test_zero_emission_remaining_flag(self):
        farm = _make_farm(emission_schedule_remaining_pct=0.0)
        r = _analyze_farm(farm)
        self.assertIn(FLAG_EMISSIONS_ENDING_SOON, r["flags"])

    def test_large_number_of_farms(self):
        farms = [_make_farm(protocol=f"P{i}") for i in range(50)]
        result = self.analyzer.analyze(farms)
        self.assertEqual(len(result["farms"]), 50)
        self.assertEqual(result["aggregates"]["total_farms"], 50)

    def test_none_peak_apy_no_crash_flag(self):
        """Zero peak APY → decay undefined → no APY_CRASHED flag."""
        farm = _make_farm(current_apy_pct=0.0, peak_apy_pct=0.0)
        r = _analyze_farm(farm)
        self.assertNotIn(FLAG_APY_CRASHED, r["flags"])

    def test_analyze_with_none_config(self):
        result = self.analyzer.analyze([_make_farm()], config=None)
        self.assertIn("farms", result)


if __name__ == "__main__":
    unittest.main()
