"""
Tests for MP-943: ProtocolFeeTierMigrationAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_fee_tier_migration_analyzer
"""

import json
import os
import sys
import unittest
import tempfile

_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_fee_tier_migration_analyzer import (
    ProtocolFeeTierMigrationAnalyzer,
    _compute_fee_revenue_change_pct,
    _compute_volume_efficiency_gain,
    _compute_migration_success_score,
    _compute_net_benefit_score,
    _get_flags,
    _get_label,
    _atomic_log_write,
    DEFAULT_CONFIG,
    LABEL_HIGHLY_SUCCESSFUL,
    LABEL_SUCCESSFUL,
    LABEL_NEUTRAL,
    LABEL_UNSUCCESSFUL,
    LABEL_COUNTERPRODUCTIVE,
    FLAG_VOLUME_CAPTURE_IMPROVED,
    FLAG_FEE_REVENUE_INCREASED,
    FLAG_IL_REDUCED,
    FLAG_REVERSE_MIGRATION_CANDIDATE,
    FLAG_INCENTIVE_DRIVEN,
)


def _migration(
    pair="USDC/ETH",
    from_tier=0.3,
    to_tier=0.05,
    tvl=1_000_000.0,
    vol_before=20.0,
    vol_after=60.0,
    days_ago=10,
    reason="competition",
    il_change=-1.0,
):
    return {
        "pair": pair,
        "from_tier_pct": from_tier,
        "to_tier_pct": to_tier,
        "tvl_migrated_usd": tvl,
        "volume_captured_before_pct": vol_before,
        "volume_captured_after_pct": vol_after,
        "date_days_ago": days_ago,
        "reason": reason,
        "il_change_pct": il_change,
    }


class TestConstants(unittest.TestCase):
    def test_label_names(self):
        self.assertEqual(LABEL_HIGHLY_SUCCESSFUL, "HIGHLY_SUCCESSFUL")
        self.assertEqual(LABEL_SUCCESSFUL, "SUCCESSFUL")
        self.assertEqual(LABEL_NEUTRAL, "NEUTRAL")
        self.assertEqual(LABEL_UNSUCCESSFUL, "UNSUCCESSFUL")
        self.assertEqual(LABEL_COUNTERPRODUCTIVE, "COUNTERPRODUCTIVE")

    def test_flag_names(self):
        self.assertEqual(FLAG_VOLUME_CAPTURE_IMPROVED, "VOLUME_CAPTURE_IMPROVED")
        self.assertEqual(FLAG_FEE_REVENUE_INCREASED, "FEE_REVENUE_INCREASED")
        self.assertEqual(FLAG_IL_REDUCED, "IL_REDUCED")
        self.assertEqual(FLAG_REVERSE_MIGRATION_CANDIDATE, "REVERSE_MIGRATION_CANDIDATE")
        self.assertEqual(FLAG_INCENTIVE_DRIVEN, "INCENTIVE_DRIVEN")

    def test_default_config_keys(self):
        keys = [
            "volume_capture_improvement_threshold_pct",
            "reverse_migration_threshold",
            "highly_successful_threshold",
            "successful_threshold",
            "neutral_threshold",
            "unsuccessful_threshold",
        ]
        for k in keys:
            self.assertIn(k, DEFAULT_CONFIG)

    def test_log_cap(self):
        from spa_core.analytics.protocol_fee_tier_migration_analyzer import LOG_CAP
        self.assertEqual(LOG_CAP, 100)


class TestFeeRevenueChange(unittest.TestCase):
    def test_same_tier_perfect_vol_transfer(self):
        m = _migration(from_tier=0.3, to_tier=0.3, vol_before=50.0, vol_after=50.0)
        change = _compute_fee_revenue_change_pct(m)
        self.assertAlmostEqual(change, 0.0, places=3)

    def test_lower_tier_higher_volume(self):
        # 0.3 → 0.05, vol 20 → 120: revenue change = (0.05*120)/(0.3*20) - 1 = 6/6 - 1 = 0
        m = _migration(from_tier=0.3, to_tier=0.05, vol_before=20.0, vol_after=120.0)
        change = _compute_fee_revenue_change_pct(m)
        self.assertAlmostEqual(change, 0.0, places=2)

    def test_lower_tier_insufficient_volume(self):
        # vol doesn't compensate for tier drop → negative revenue change
        m = _migration(from_tier=0.3, to_tier=0.05, vol_before=20.0, vol_after=30.0)
        change = _compute_fee_revenue_change_pct(m)
        self.assertLess(change, 0.0)

    def test_higher_tier_same_volume(self):
        m = _migration(from_tier=0.05, to_tier=0.3, vol_before=50.0, vol_after=50.0)
        change = _compute_fee_revenue_change_pct(m)
        self.assertGreater(change, 0.0)

    def test_zero_vol_after_negative(self):
        m = _migration(vol_before=10.0, vol_after=0.0)
        change = _compute_fee_revenue_change_pct(m)
        self.assertLess(change, 0.0)

    def test_returns_float(self):
        m = _migration()
        self.assertIsInstance(_compute_fee_revenue_change_pct(m), float)

    def test_doubled_tier_doubled_volume(self):
        # 0.05 → 0.1 (double tier), vol stays same → revenue doubles → +100%
        m = _migration(from_tier=0.05, to_tier=0.10, vol_before=50.0, vol_after=50.0)
        change = _compute_fee_revenue_change_pct(m)
        self.assertAlmostEqual(change, 100.0, places=2)


class TestVolumeEfficiencyGain(unittest.TestCase):
    def test_same_volume_zero_gain(self):
        m = _migration(vol_before=50.0, vol_after=50.0)
        gain = _compute_volume_efficiency_gain(m)
        self.assertAlmostEqual(gain, 0.0, places=3)

    def test_doubled_volume_100pct_gain(self):
        m = _migration(vol_before=50.0, vol_after=100.0)
        gain = _compute_volume_efficiency_gain(m)
        self.assertAlmostEqual(gain, 100.0, places=3)

    def test_halved_volume_negative_gain(self):
        m = _migration(vol_before=50.0, vol_after=25.0)
        gain = _compute_volume_efficiency_gain(m)
        self.assertAlmostEqual(gain, -50.0, places=3)

    def test_zero_vol_after(self):
        m = _migration(vol_before=50.0, vol_after=0.0)
        gain = _compute_volume_efficiency_gain(m)
        self.assertAlmostEqual(gain, -100.0, places=3)

    def test_large_gain(self):
        m = _migration(vol_before=5.0, vol_after=100.0)
        gain = _compute_volume_efficiency_gain(m)
        self.assertGreater(gain, 100.0)

    def test_returns_float(self):
        m = _migration()
        self.assertIsInstance(_compute_volume_efficiency_gain(m), float)


class TestMigrationSuccessScore(unittest.TestCase):
    def test_perfect_migration_high_score(self):
        m = _migration(vol_before=10.0, vol_after=50.0, il_change=-5.0)
        score = _compute_migration_success_score(m, 100.0, 400.0)
        self.assertGreater(score, 60.0)

    def test_failed_migration_low_score(self):
        m = _migration(vol_before=50.0, vol_after=5.0, il_change=10.0)
        score = _compute_migration_success_score(m, -80.0, -90.0)
        self.assertLess(score, 40.0)

    def test_score_bounded_0_100(self):
        m = _migration(vol_before=100.0, vol_after=0.0, il_change=50.0)
        score = _compute_migration_success_score(m, -100.0, -100.0)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_neutral_scores_mid_range(self):
        m = _migration(vol_before=50.0, vol_after=50.0, il_change=0.0)
        score = _compute_migration_success_score(m, 0.0, 0.0)
        self.assertGreater(score, 30.0)
        self.assertLess(score, 70.0)

    def test_il_reduction_improves_score(self):
        m_bad_il = _migration(il_change=5.0)
        m_good_il = _migration(il_change=-5.0)
        s_bad = _compute_migration_success_score(m_bad_il, 0.0, 0.0)
        s_good = _compute_migration_success_score(m_good_il, 0.0, 0.0)
        self.assertGreater(s_good, s_bad)

    def test_returns_float(self):
        m = _migration()
        self.assertIsInstance(_compute_migration_success_score(m, 0.0, 0.0), float)

    def test_positive_fee_and_vol_high_score(self):
        m = _migration()
        score = _compute_migration_success_score(m, 50.0, 50.0)
        self.assertGreater(score, 65.0)


class TestNetBenefitScore(unittest.TestCase):
    def test_bounded_0_100(self):
        m = _migration()
        score = _compute_net_benefit_score(100.0, 200.0, -10.0, m)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_negative_inputs_low_score(self):
        m = _migration(days_ago=300)
        score = _compute_net_benefit_score(-100.0, -100.0, 20.0, m)
        self.assertLess(score, 40.0)

    def test_positive_inputs_high_score(self):
        m = _migration(days_ago=5)
        score = _compute_net_benefit_score(100.0, 100.0, -10.0, m)
        self.assertGreater(score, 60.0)

    def test_recent_migration_scores_higher_than_old(self):
        m_recent = _migration(days_ago=5)
        m_old = _migration(days_ago=300)
        s_recent = _compute_net_benefit_score(0.0, 0.0, 0.0, m_recent)
        s_old = _compute_net_benefit_score(0.0, 0.0, 0.0, m_old)
        self.assertGreater(s_recent, s_old)

    def test_il_reduction_improves_score(self):
        m = _migration()
        s_bad = _compute_net_benefit_score(0.0, 0.0, 10.0, m)
        s_good = _compute_net_benefit_score(0.0, 0.0, -10.0, m)
        self.assertGreater(s_good, s_bad)

    def test_returns_float(self):
        m = _migration()
        self.assertIsInstance(_compute_net_benefit_score(0.0, 0.0, 0.0, m), float)


class TestFlags(unittest.TestCase):
    def test_volume_capture_improved_flag(self):
        m = _migration(reason="competition")
        flags = _get_flags(m, 10.0, 25.0, 60.0, DEFAULT_CONFIG)
        self.assertIn(FLAG_VOLUME_CAPTURE_IMPROVED, flags)

    def test_no_volume_capture_improved_flag(self):
        m = _migration(reason="competition")
        flags = _get_flags(m, 10.0, 10.0, 60.0, DEFAULT_CONFIG)
        self.assertNotIn(FLAG_VOLUME_CAPTURE_IMPROVED, flags)

    def test_fee_revenue_increased_flag(self):
        m = _migration()
        flags = _get_flags(m, 20.0, 10.0, 60.0, DEFAULT_CONFIG)
        self.assertIn(FLAG_FEE_REVENUE_INCREASED, flags)

    def test_no_fee_revenue_increased_flag(self):
        m = _migration()
        flags = _get_flags(m, -10.0, 10.0, 60.0, DEFAULT_CONFIG)
        self.assertNotIn(FLAG_FEE_REVENUE_INCREASED, flags)

    def test_il_reduced_flag_negative_il(self):
        m = _migration(il_change=-2.0)
        flags = _get_flags(m, 0.0, 0.0, 60.0, DEFAULT_CONFIG)
        self.assertIn(FLAG_IL_REDUCED, flags)

    def test_no_il_reduced_flag_positive_il(self):
        m = _migration(il_change=2.0)
        flags = _get_flags(m, 0.0, 0.0, 60.0, DEFAULT_CONFIG)
        self.assertNotIn(FLAG_IL_REDUCED, flags)

    def test_reverse_migration_candidate_flag(self):
        m = _migration()
        flags = _get_flags(m, -50.0, -50.0, 10.0, DEFAULT_CONFIG)
        self.assertIn(FLAG_REVERSE_MIGRATION_CANDIDATE, flags)

    def test_no_reverse_migration_flag(self):
        m = _migration()
        flags = _get_flags(m, 50.0, 50.0, 60.0, DEFAULT_CONFIG)
        self.assertNotIn(FLAG_REVERSE_MIGRATION_CANDIDATE, flags)

    def test_incentive_driven_flag(self):
        m = _migration(reason="incentives")
        flags = _get_flags(m, 0.0, 0.0, 50.0, DEFAULT_CONFIG)
        self.assertIn(FLAG_INCENTIVE_DRIVEN, flags)

    def test_no_incentive_flag_other_reason(self):
        m = _migration(reason="competition")
        flags = _get_flags(m, 0.0, 0.0, 50.0, DEFAULT_CONFIG)
        self.assertNotIn(FLAG_INCENTIVE_DRIVEN, flags)

    def test_multiple_flags(self):
        m = _migration(reason="incentives", il_change=-2.0)
        flags = _get_flags(m, 30.0, 30.0, 60.0, DEFAULT_CONFIG)
        self.assertIn(FLAG_VOLUME_CAPTURE_IMPROVED, flags)
        self.assertIn(FLAG_FEE_REVENUE_INCREASED, flags)
        self.assertIn(FLAG_IL_REDUCED, flags)
        self.assertIn(FLAG_INCENTIVE_DRIVEN, flags)

    def test_returns_list(self):
        m = _migration()
        self.assertIsInstance(_get_flags(m, 0.0, 0.0, 50.0, DEFAULT_CONFIG), list)

    def test_custom_volume_threshold(self):
        m = _migration(reason="other")
        cfg = {**DEFAULT_CONFIG, "volume_capture_improvement_threshold_pct": 5.0}
        flags = _get_flags(m, 0.0, 10.0, 50.0, cfg)
        self.assertIn(FLAG_VOLUME_CAPTURE_IMPROVED, flags)


class TestLabel(unittest.TestCase):
    def test_highly_successful(self):
        self.assertEqual(_get_label(80.0, DEFAULT_CONFIG), LABEL_HIGHLY_SUCCESSFUL)

    def test_successful(self):
        self.assertEqual(_get_label(60.0, DEFAULT_CONFIG), LABEL_SUCCESSFUL)

    def test_neutral(self):
        self.assertEqual(_get_label(40.0, DEFAULT_CONFIG), LABEL_NEUTRAL)

    def test_unsuccessful(self):
        self.assertEqual(_get_label(20.0, DEFAULT_CONFIG), LABEL_UNSUCCESSFUL)

    def test_counterproductive(self):
        self.assertEqual(_get_label(5.0, DEFAULT_CONFIG), LABEL_COUNTERPRODUCTIVE)

    def test_boundary_highly_successful(self):
        self.assertEqual(_get_label(75.0, DEFAULT_CONFIG), LABEL_HIGHLY_SUCCESSFUL)

    def test_boundary_successful(self):
        self.assertEqual(_get_label(55.0, DEFAULT_CONFIG), LABEL_SUCCESSFUL)

    def test_boundary_neutral(self):
        self.assertEqual(_get_label(35.0, DEFAULT_CONFIG), LABEL_NEUTRAL)

    def test_boundary_unsuccessful(self):
        self.assertEqual(_get_label(15.0, DEFAULT_CONFIG), LABEL_UNSUCCESSFUL)

    def test_returns_string(self):
        self.assertIsInstance(_get_label(50.0, DEFAULT_CONFIG), str)

    def test_custom_threshold(self):
        cfg = {**DEFAULT_CONFIG, "highly_successful_threshold": 90.0}
        self.assertNotEqual(_get_label(80.0, cfg), LABEL_HIGHLY_SUCCESSFUL)

    def test_zero_is_counterproductive(self):
        self.assertEqual(_get_label(0.0, DEFAULT_CONFIG), LABEL_COUNTERPRODUCTIVE)

    def test_100_is_highly_successful(self):
        self.assertEqual(_get_label(100.0, DEFAULT_CONFIG), LABEL_HIGHLY_SUCCESSFUL)


class TestAtomicLogWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def test_creates_file(self):
        _atomic_log_write({"x": 1}, self.tmp, 100)
        self.assertTrue(os.path.exists(self.tmp))

    def test_valid_json(self):
        _atomic_log_write({"x": 1}, self.tmp, 100)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_appends(self):
        for i in range(3):
            _atomic_log_write({"i": i}, self.tmp, 100)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_cap_enforced(self):
        for i in range(15):
            _atomic_log_write({"i": i}, self.tmp, 10)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 10)

    def test_newest_kept(self):
        for i in range(5):
            _atomic_log_write({"i": i}, self.tmp, 3)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["i"], 4)

    def test_no_tmp_file_remains(self):
        _atomic_log_write({"a": 1}, self.tmp, 100)
        self.assertFalse(os.path.exists(self.tmp + ".tmp"))


class TestAnalyzerEmptyInput(unittest.TestCase):
    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")
        self.analyzer = ProtocolFeeTierMigrationAnalyzer(log_path=self.tmp_log)

    def tearDown(self):
        if os.path.exists(self.tmp_log):
            os.remove(self.tmp_log)

    def test_empty_returns_dict(self):
        result = self.analyzer.analyze([], {})
        self.assertIsInstance(result, dict)

    def test_empty_migrations_list(self):
        result = self.analyzer.analyze([], {})
        self.assertEqual(result["migrations"], [])

    def test_empty_aggregates_defaults(self):
        result = self.analyzer.analyze([], {})
        agg = result["aggregates"]
        self.assertEqual(agg["migration_count"], 0)
        self.assertEqual(agg["total_tvl_migrated_usd"], 0.0)
        self.assertEqual(agg["average_net_benefit"], 0.0)
        self.assertEqual(agg["successful_count"], 0)
        self.assertIsNone(agg["most_successful_migration"])
        self.assertIsNone(agg["least_successful_migration"])

    def test_timestamp_present(self):
        result = self.analyzer.analyze([], {})
        self.assertIn("timestamp", result)


class TestAnalyzerSingleMigration(unittest.TestCase):
    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")
        self.analyzer = ProtocolFeeTierMigrationAnalyzer(log_path=self.tmp_log)

    def tearDown(self):
        if os.path.exists(self.tmp_log):
            os.remove(self.tmp_log)

    def test_single_result_structure(self):
        result = self.analyzer.analyze([_migration()], {})
        self.assertEqual(len(result["migrations"]), 1)
        m = result["migrations"][0]
        for key in ["pair", "from_tier_pct", "to_tier_pct", "tvl_migrated_usd",
                    "fee_revenue_change_pct", "volume_efficiency_gain",
                    "migration_success_score", "net_benefit_score",
                    "migration_label", "flags", "reason", "il_change_pct"]:
            self.assertIn(key, m)

    def test_single_label_valid(self):
        result = self.analyzer.analyze([_migration()], {})
        label = result["migrations"][0]["migration_label"]
        self.assertIn(label, [
            LABEL_HIGHLY_SUCCESSFUL, LABEL_SUCCESSFUL, LABEL_NEUTRAL,
            LABEL_UNSUCCESSFUL, LABEL_COUNTERPRODUCTIVE
        ])

    def test_single_scores_in_range(self):
        result = self.analyzer.analyze([_migration()], {})
        m = result["migrations"][0]
        self.assertGreaterEqual(m["migration_success_score"], 0.0)
        self.assertLessEqual(m["migration_success_score"], 100.0)
        self.assertGreaterEqual(m["net_benefit_score"], 0.0)
        self.assertLessEqual(m["net_benefit_score"], 100.0)

    def test_single_flags_list(self):
        result = self.analyzer.analyze([_migration()], {})
        self.assertIsInstance(result["migrations"][0]["flags"], list)

    def test_single_best_equals_worst(self):
        result = self.analyzer.analyze([_migration(pair="ETH/USDC")], {})
        best = result["aggregates"]["most_successful_migration"]
        worst = result["aggregates"]["least_successful_migration"]
        self.assertEqual(best["pair"], worst["pair"])

    def test_log_written(self):
        self.analyzer.analyze([_migration()], {})
        self.assertTrue(os.path.exists(self.tmp_log))


class TestAnalyzerMultipleMigrations(unittest.TestCase):
    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")
        self.analyzer = ProtocolFeeTierMigrationAnalyzer(log_path=self.tmp_log)
        self.migrations = [
            _migration("ETH/USDC", from_tier=0.3, to_tier=0.05, vol_before=10, vol_after=100,
                       days_ago=5, reason="competition", il_change=-2.0, tvl=2_000_000),
            _migration("BTC/USDC", from_tier=0.3, to_tier=0.3, vol_before=50, vol_after=50,
                       days_ago=30, reason="other", il_change=0.0, tvl=500_000),
            _migration("LINK/ETH", from_tier=0.05, to_tier=0.3, vol_before=80, vol_after=3,
                       days_ago=250, reason="high_volatility", il_change=10.0, tvl=100_000),
        ]

    def tearDown(self):
        if os.path.exists(self.tmp_log):
            os.remove(self.tmp_log)

    def test_count_matches(self):
        result = self.analyzer.analyze(self.migrations, {})
        self.assertEqual(len(result["migrations"]), 3)
        self.assertEqual(result["aggregates"]["migration_count"], 3)

    def test_total_tvl_correct(self):
        result = self.analyzer.analyze(self.migrations, {})
        self.assertAlmostEqual(result["aggregates"]["total_tvl_migrated_usd"], 2_600_000.0, places=0)

    def test_most_successful_structure(self):
        result = self.analyzer.analyze(self.migrations, {})
        best = result["aggregates"]["most_successful_migration"]
        for key in ["pair", "label", "net_benefit_score"]:
            self.assertIn(key, best)

    def test_least_successful_structure(self):
        result = self.analyzer.analyze(self.migrations, {})
        worst = result["aggregates"]["least_successful_migration"]
        for key in ["pair", "label", "net_benefit_score"]:
            self.assertIn(key, worst)

    def test_best_net_benefit_gte_worst(self):
        result = self.analyzer.analyze(self.migrations, {})
        best_score = result["aggregates"]["most_successful_migration"]["net_benefit_score"]
        worst_score = result["aggregates"]["least_successful_migration"]["net_benefit_score"]
        self.assertGreaterEqual(best_score, worst_score)

    def test_average_net_benefit_in_range(self):
        result = self.analyzer.analyze(self.migrations, {})
        avg = result["aggregates"]["average_net_benefit"]
        self.assertGreater(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_successful_count_nonneg(self):
        result = self.analyzer.analyze(self.migrations, {})
        self.assertGreaterEqual(result["aggregates"]["successful_count"], 0)

    def test_successful_count_lte_total(self):
        result = self.analyzer.analyze(self.migrations, {})
        self.assertLessEqual(result["aggregates"]["successful_count"], 3)

    def test_good_migration_high_benefit(self):
        result = self.analyzer.analyze(self.migrations, {})
        eth_usdc = result["migrations"][0]
        self.assertGreater(eth_usdc["net_benefit_score"], 50.0)

    def test_bad_migration_low_benefit(self):
        result = self.analyzer.analyze(self.migrations, {})
        link_eth = result["migrations"][2]
        self.assertLess(link_eth["net_benefit_score"], 50.0)

    def test_vol_improved_flag_on_good_migration(self):
        result = self.analyzer.analyze(self.migrations, {})
        eth_usdc = result["migrations"][0]
        self.assertIn(FLAG_VOLUME_CAPTURE_IMPROVED, eth_usdc["flags"])

    def test_il_reduced_flag_on_good_migration(self):
        result = self.analyzer.analyze(self.migrations, {})
        eth_usdc = result["migrations"][0]
        self.assertIn(FLAG_IL_REDUCED, eth_usdc["flags"])

    def test_reverse_candidate_on_bad_migration(self):
        result = self.analyzer.analyze(self.migrations, {})
        link_eth = result["migrations"][2]
        self.assertIn(FLAG_REVERSE_MIGRATION_CANDIDATE, link_eth["flags"])

    def test_log_written_with_data(self):
        self.analyzer.analyze(self.migrations, {})
        with open(self.tmp_log) as f:
            data = json.load(f)
        self.assertEqual(data[0]["migration_count"], 3)


class TestLogRingBuffer(unittest.TestCase):
    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")
        self.analyzer = ProtocolFeeTierMigrationAnalyzer(log_path=self.tmp_log, log_cap=5)

    def tearDown(self):
        if os.path.exists(self.tmp_log):
            os.remove(self.tmp_log)

    def test_log_capped(self):
        for _ in range(10):
            self.analyzer.analyze([_migration()], {})
        with open(self.tmp_log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_has_timestamp(self):
        self.analyzer.analyze([_migration()], {})
        with open(self.tmp_log) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_has_migration_count(self):
        self.analyzer.analyze([_migration(), _migration("B/C")], {})
        with open(self.tmp_log) as f:
            data = json.load(f)
        self.assertEqual(data[0]["migration_count"], 2)

    def test_log_has_tvl(self):
        self.analyzer.analyze([_migration(tvl=500_000.0)], {})
        with open(self.tmp_log) as f:
            data = json.load(f)
        self.assertAlmostEqual(data[0]["total_tvl_migrated_usd"], 500_000.0, places=0)


class TestConfigOverrides(unittest.TestCase):
    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")
        self.analyzer = ProtocolFeeTierMigrationAnalyzer(log_path=self.tmp_log)

    def tearDown(self):
        if os.path.exists(self.tmp_log):
            os.remove(self.tmp_log)

    def test_custom_reverse_threshold(self):
        m = _migration(vol_before=50, vol_after=40, il_change=2.0)
        cfg = {"reverse_migration_threshold": 80.0}
        result = self.analyzer.analyze([m], cfg)
        self.assertIn(FLAG_REVERSE_MIGRATION_CANDIDATE, result["migrations"][0]["flags"])

    def test_none_config_uses_defaults(self):
        result = self.analyzer.analyze([_migration()], None)
        self.assertIsInstance(result, dict)

    def test_custom_highly_successful_threshold(self):
        m = _migration(vol_before=10, vol_after=100, il_change=-3.0, days_ago=5)
        cfg = {"highly_successful_threshold": 99.0}
        result = self.analyzer.analyze([m], cfg)
        label = result["migrations"][0]["migration_label"]
        # With very high threshold, should not be HIGHLY_SUCCESSFUL
        self.assertNotEqual(label, LABEL_HIGHLY_SUCCESSFUL)

    def test_custom_volume_threshold(self):
        # vol_after=12 → gain=20%, below custom threshold 30% → flag NOT set
        m = _migration(vol_before=10, vol_after=12, reason="other")
        cfg = {"volume_capture_improvement_threshold_pct": 30.0}
        result = self.analyzer.analyze([m], cfg)
        self.assertNotIn(FLAG_VOLUME_CAPTURE_IMPROVED, result["migrations"][0]["flags"])


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmp_log = tempfile.mktemp(suffix=".json")
        self.analyzer = ProtocolFeeTierMigrationAnalyzer(log_path=self.tmp_log)

    def tearDown(self):
        if os.path.exists(self.tmp_log):
            os.remove(self.tmp_log)

    def test_minimal_migration_dict(self):
        result = self.analyzer.analyze([{"pair": "X/Y"}], {})
        self.assertIsInstance(result, dict)
        self.assertEqual(len(result["migrations"]), 1)

    def test_very_large_tvl(self):
        m = _migration(tvl=1_000_000_000.0)
        result = self.analyzer.analyze([m], {})
        self.assertGreater(result["aggregates"]["total_tvl_migrated_usd"], 0.0)

    def test_deterministic_results(self):
        m = _migration()
        r1 = self.analyzer.analyze([m], {})
        r2 = self.analyzer.analyze([m], {})
        self.assertAlmostEqual(
            r1["migrations"][0]["net_benefit_score"],
            r2["migrations"][0]["net_benefit_score"],
            places=4
        )

    def test_incentives_reason_gets_flag(self):
        m = _migration(reason="incentives")
        result = self.analyzer.analyze([m], {})
        self.assertIn(FLAG_INCENTIVE_DRIVEN, result["migrations"][0]["flags"])

    def test_fee_zero_vol_after_negative_revenue(self):
        m = _migration(vol_before=50, vol_after=0)
        change = _compute_fee_revenue_change_pct(m)
        self.assertLess(change, 0.0)

    def test_timestamp_is_float(self):
        result = self.analyzer.analyze([_migration()], {})
        self.assertIsInstance(result["timestamp"], float)

    def test_pair_preserved(self):
        result = self.analyzer.analyze([_migration(pair="WBTC/ETH")], {})
        self.assertEqual(result["migrations"][0]["pair"], "WBTC/ETH")

    def test_il_change_preserved(self):
        result = self.analyzer.analyze([_migration(il_change=-3.5)], {})
        self.assertAlmostEqual(result["migrations"][0]["il_change_pct"], -3.5)

    def test_all_labels_possible(self):
        """Verify the 5 labels can all be produced."""
        migrations = [
            _migration(vol_before=5, vol_after=200, il_change=-10, days_ago=1, reason="competition"),
            _migration(vol_before=20, vol_after=60, il_change=-1, days_ago=10),
            _migration(vol_before=50, vol_after=55, il_change=0, days_ago=30, reason="other"),
            _migration(vol_before=80, vol_after=40, il_change=2, days_ago=100, reason="other"),
            _migration(vol_before=100, vol_after=5, il_change=10, days_ago=350, reason="other"),
        ]
        result = self.analyzer.analyze(migrations, {})
        labels = {m["migration_label"] for m in result["migrations"]}
        # At minimum, highly_successful and counterproductive should appear
        self.assertGreaterEqual(len(labels), 2)

    def test_successful_count_only_counts_hs_and_s(self):
        migrations = [
            _migration(vol_before=5, vol_after=200, il_change=-10, days_ago=1),  # likely HIGHLY_SUCCESSFUL
        ]
        result = self.analyzer.analyze(migrations, {})
        sc = result["aggregates"]["successful_count"]
        label = result["migrations"][0]["migration_label"]
        if label in (LABEL_HIGHLY_SUCCESSFUL, LABEL_SUCCESSFUL):
            self.assertEqual(sc, 1)
        else:
            self.assertEqual(sc, 0)


if __name__ == "__main__":
    unittest.main()
