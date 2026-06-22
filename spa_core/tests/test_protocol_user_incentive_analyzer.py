"""
Tests for MP-921 ProtocolUserIncentiveAnalyzer
Run with: python3 -m unittest spa_core.tests.test_protocol_user_incentive_analyzer
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_user_incentive_analyzer import (
    analyze,
    append_log,
    run,
    _cost_per_user_usd,
    _cost_per_tvl_usd,
    _roi_score,
    _efficiency_score,
    _mercenary_capital_risk,
    _efficiency_label,
    _compute_flags,
    _analyze_single,
    MERCENARY_CAPITAL_RETENTION_THRESHOLD,
    LOG_CAP,
    ROI_FULL_MULTIPLE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_program(
    protocol="TestProtocol",
    program_type="liquidity_mining",
    monthly_cost_usd=100_000.0,
    monthly_new_users=200,
    monthly_tvl_added_usd=1_000_000.0,
    retention_after_program_pct=40.0,
    duration_months=3,
    token_price_change_during_pct=0.0,
):
    return {
        "protocol": protocol,
        "program_type": program_type,
        "monthly_cost_usd": monthly_cost_usd,
        "monthly_new_users": monthly_new_users,
        "monthly_tvl_added_usd": monthly_tvl_added_usd,
        "retention_after_program_pct": retention_after_program_pct,
        "duration_months": duration_months,
        "token_price_change_during_pct": token_price_change_during_pct,
    }


# ===========================================================================
# 1. TestCostPerUser
# ===========================================================================

class TestCostPerUser(unittest.TestCase):

    def test_basic_calculation(self):
        # 100_000 / 200 = 500
        self.assertAlmostEqual(_cost_per_user_usd(100_000, 200), 500.0, places=4)

    def test_zero_users_returns_inf(self):
        result = _cost_per_user_usd(100_000, 0)
        self.assertEqual(result, float("inf"))

    def test_zero_users_zero_cost_returns_zero(self):
        result = _cost_per_user_usd(0, 0)
        self.assertEqual(result, 0.0)

    def test_zero_cost_any_users(self):
        self.assertAlmostEqual(_cost_per_user_usd(0, 100), 0.0, places=4)

    def test_one_user(self):
        self.assertAlmostEqual(_cost_per_user_usd(999, 1), 999.0, places=4)

    def test_large_numbers(self):
        self.assertAlmostEqual(_cost_per_user_usd(1_000_000, 1000), 1000.0, places=4)

    def test_fractional_result(self):
        self.assertAlmostEqual(_cost_per_user_usd(333, 100), 3.33, places=4)


# ===========================================================================
# 2. TestCostPerTvl
# ===========================================================================

class TestCostPerTvl(unittest.TestCase):

    def test_basic_calculation(self):
        # 100_000 / 1_000_000 = 0.1
        self.assertAlmostEqual(_cost_per_tvl_usd(100_000, 1_000_000), 0.1, places=6)

    def test_zero_tvl_returns_inf(self):
        result = _cost_per_tvl_usd(100_000, 0)
        self.assertEqual(result, float("inf"))

    def test_zero_tvl_zero_cost_returns_zero(self):
        result = _cost_per_tvl_usd(0, 0)
        self.assertEqual(result, 0.0)

    def test_zero_cost_any_tvl(self):
        self.assertAlmostEqual(_cost_per_tvl_usd(0, 1_000_000), 0.0, places=6)

    def test_equal_cost_and_tvl(self):
        self.assertAlmostEqual(_cost_per_tvl_usd(1000, 1000), 1.0, places=6)

    def test_large_tvl(self):
        self.assertAlmostEqual(_cost_per_tvl_usd(50_000, 10_000_000), 0.005, places=6)

    def test_cost_exceeds_tvl(self):
        result = _cost_per_tvl_usd(1_000_000, 100_000)
        self.assertAlmostEqual(result, 10.0, places=4)


# ===========================================================================
# 3. TestRoiScore
# ===========================================================================

class TestRoiScore(unittest.TestCase):

    def test_zero_cost_positive_tvl_returns_100(self):
        self.assertAlmostEqual(_roi_score(1_000_000, 0), 100.0, places=4)

    def test_zero_cost_zero_tvl_returns_zero(self):
        self.assertAlmostEqual(_roi_score(0, 0), 0.0, places=4)

    def test_10x_ratio_returns_100(self):
        # ratio = 10 -> 100/10*100 = 100
        self.assertAlmostEqual(_roi_score(1_000_000, 100_000), 100.0, places=4)

    def test_1x_ratio_returns_10(self):
        self.assertAlmostEqual(_roi_score(100_000, 100_000), 10.0, places=4)

    def test_5x_ratio_returns_50(self):
        self.assertAlmostEqual(_roi_score(500_000, 100_000), 50.0, places=4)

    def test_above_10x_capped_at_100(self):
        self.assertAlmostEqual(_roi_score(10_000_000, 100_000), 100.0, places=4)

    def test_zero_tvl_positive_cost_returns_zero(self):
        self.assertAlmostEqual(_roi_score(0, 100_000), 0.0, places=4)

    def test_output_never_negative(self):
        self.assertGreaterEqual(_roi_score(0, 1_000_000), 0.0)

    def test_output_never_exceeds_100(self):
        self.assertLessEqual(_roi_score(1e12, 1), 100.0)


# ===========================================================================
# 4. TestEfficiencyScore
# ===========================================================================

class TestEfficiencyScore(unittest.TestCase):

    def test_zero_roi_zero_retention_returns_zero(self):
        self.assertAlmostEqual(_efficiency_score(0, 0), 0.0, places=4)

    def test_100_roi_100_retention_returns_100(self):
        self.assertAlmostEqual(_efficiency_score(100, 100), 100.0, places=4)

    def test_50_roi_50_retention(self):
        # 50*0.6 + 50*0.4 = 30 + 20 = 50
        self.assertAlmostEqual(_efficiency_score(50, 50), 50.0, places=4)

    def test_roi_weighted_60_pct(self):
        # 100*0.6 + 0*0.4 = 60
        self.assertAlmostEqual(_efficiency_score(100, 0), 60.0, places=4)

    def test_retention_weighted_40_pct(self):
        # 0*0.6 + 100*0.4 = 40
        self.assertAlmostEqual(_efficiency_score(0, 100), 40.0, places=4)

    def test_clamped_to_100(self):
        self.assertAlmostEqual(_efficiency_score(200, 200), 100.0, places=4)

    def test_clamped_to_zero(self):
        self.assertAlmostEqual(_efficiency_score(-100, -100), 0.0, places=4)


# ===========================================================================
# 5. TestMercenaryCapitalRisk
# ===========================================================================

class TestMercenaryCapitalRisk(unittest.TestCase):

    def test_zero_retention_max_risk(self):
        self.assertAlmostEqual(_mercenary_capital_risk(0.0), 100.0, places=4)

    def test_100_retention_zero_risk(self):
        self.assertAlmostEqual(_mercenary_capital_risk(100.0), 0.0, places=4)

    def test_50_retention_50_risk(self):
        self.assertAlmostEqual(_mercenary_capital_risk(50.0), 50.0, places=4)

    def test_20_pct_retention(self):
        self.assertAlmostEqual(_mercenary_capital_risk(20.0), 80.0, places=4)

    def test_clamped_to_0_for_high_retention(self):
        self.assertAlmostEqual(_mercenary_capital_risk(150.0), 0.0, places=4)

    def test_clamped_to_100_for_negative_retention(self):
        self.assertAlmostEqual(_mercenary_capital_risk(-10.0), 100.0, places=4)


# ===========================================================================
# 6. TestEfficiencyLabel
# ===========================================================================

class TestEfficiencyLabel(unittest.TestCase):

    def test_excellent_at_80(self):
        self.assertEqual(_efficiency_label(80.0), "EXCELLENT")

    def test_excellent_at_100(self):
        self.assertEqual(_efficiency_label(100.0), "EXCELLENT")

    def test_good_at_60(self):
        self.assertEqual(_efficiency_label(60.0), "GOOD")

    def test_good_at_79(self):
        self.assertEqual(_efficiency_label(79.9), "GOOD")

    def test_fair_at_40(self):
        self.assertEqual(_efficiency_label(40.0), "FAIR")

    def test_poor_at_20(self):
        self.assertEqual(_efficiency_label(20.0), "POOR")

    def test_wasteful_at_19(self):
        self.assertEqual(_efficiency_label(19.9), "WASTEFUL")

    def test_wasteful_at_zero(self):
        self.assertEqual(_efficiency_label(0.0), "WASTEFUL")


# ===========================================================================
# 7. TestComputeFlagsIncentive
# ===========================================================================

class TestComputeFlagsIncentive(unittest.TestCase):

    def test_no_flags_clean_program(self):
        flags = _compute_flags(
            retention_after_program_pct=50.0,
            cost_per_user=500.0,
            monthly_tvl_added_usd=1_000_000.0,
            monthly_new_users=200,
            token_price_change_during_pct=0.0,
        )
        # 50% retention > 20% -> no MERCENARY_CAPITAL
        # 500 < 1000 -> no HIGH_COST_PER_USER
        # tvl_per_user=5000 < 10000 -> no TVL_FARMING
        # 0% > -30% -> no TOKEN_DUMP
        # 50% < 60% -> no EFFECTIVE_RETENTION
        self.assertEqual(flags, [])

    def test_mercenary_capital_below_threshold(self):
        flags = _compute_flags(
            retention_after_program_pct=10.0,
            cost_per_user=500.0,
            monthly_tvl_added_usd=1_000_000.0,
            monthly_new_users=200,
            token_price_change_during_pct=0.0,
        )
        self.assertIn("MERCENARY_CAPITAL", flags)

    def test_mercenary_capital_exactly_at_threshold_no_flag(self):
        flags = _compute_flags(
            retention_after_program_pct=MERCENARY_CAPITAL_RETENTION_THRESHOLD,
            cost_per_user=500.0,
            monthly_tvl_added_usd=1_000_000.0,
            monthly_new_users=200,
            token_price_change_during_pct=0.0,
        )
        self.assertNotIn("MERCENARY_CAPITAL", flags)

    def test_high_cost_per_user_flag(self):
        flags = _compute_flags(
            retention_after_program_pct=50.0,
            cost_per_user=1500.0,
            monthly_tvl_added_usd=1_000_000.0,
            monthly_new_users=200,
            token_price_change_during_pct=0.0,
        )
        self.assertIn("HIGH_COST_PER_USER", flags)

    def test_no_high_cost_below_threshold(self):
        flags = _compute_flags(
            retention_after_program_pct=50.0,
            cost_per_user=999.0,
            monthly_tvl_added_usd=1_000_000.0,
            monthly_new_users=200,
            token_price_change_during_pct=0.0,
        )
        self.assertNotIn("HIGH_COST_PER_USER", flags)

    def test_infinite_cpu_is_high_cost(self):
        flags = _compute_flags(
            retention_after_program_pct=50.0,
            cost_per_user=float("inf"),
            monthly_tvl_added_usd=1_000_000.0,
            monthly_new_users=0,
            token_price_change_during_pct=0.0,
        )
        self.assertIn("HIGH_COST_PER_USER", flags)

    def test_tvl_farming_flag(self):
        # tvl_per_user = 5_000_000/2 = 2_500_000 > 10_000 AND users=2 < 100
        flags = _compute_flags(
            retention_after_program_pct=50.0,
            cost_per_user=500.0,
            monthly_tvl_added_usd=5_000_000.0,
            monthly_new_users=2,
            token_price_change_during_pct=0.0,
        )
        self.assertIn("TVL_FARMING", flags)

    def test_no_tvl_farming_enough_users(self):
        # tvl_per_user = 5_000_000/200 = 25_000 > 10_000 but users=200 >= 100
        flags = _compute_flags(
            retention_after_program_pct=50.0,
            cost_per_user=500.0,
            monthly_tvl_added_usd=5_000_000.0,
            monthly_new_users=200,
            token_price_change_during_pct=0.0,
        )
        self.assertNotIn("TVL_FARMING", flags)

    def test_token_dump_flag(self):
        flags = _compute_flags(
            retention_after_program_pct=50.0,
            cost_per_user=500.0,
            monthly_tvl_added_usd=1_000_000.0,
            monthly_new_users=200,
            token_price_change_during_pct=-50.0,
        )
        self.assertIn("TOKEN_DUMP", flags)

    def test_no_token_dump_at_threshold(self):
        flags = _compute_flags(
            retention_after_program_pct=50.0,
            cost_per_user=500.0,
            monthly_tvl_added_usd=1_000_000.0,
            monthly_new_users=200,
            token_price_change_during_pct=-30.0,  # exactly at threshold
        )
        self.assertNotIn("TOKEN_DUMP", flags)

    def test_effective_retention_flag(self):
        flags = _compute_flags(
            retention_after_program_pct=80.0,
            cost_per_user=500.0,
            monthly_tvl_added_usd=1_000_000.0,
            monthly_new_users=200,
            token_price_change_during_pct=0.0,
        )
        self.assertIn("EFFECTIVE_RETENTION", flags)

    def test_no_effective_retention_at_threshold(self):
        flags = _compute_flags(
            retention_after_program_pct=60.0,
            cost_per_user=500.0,
            monthly_tvl_added_usd=1_000_000.0,
            monthly_new_users=200,
            token_price_change_during_pct=0.0,
        )
        self.assertNotIn("EFFECTIVE_RETENTION", flags)

    def test_all_flags_at_once(self):
        flags = _compute_flags(
            retention_after_program_pct=5.0,       # MERCENARY_CAPITAL
            cost_per_user=2000.0,                   # HIGH_COST_PER_USER
            monthly_tvl_added_usd=10_000_000.0,    # TVL_FARMING (high tvl, few users)
            monthly_new_users=1,
            token_price_change_during_pct=-50.0,    # TOKEN_DUMP
        )
        self.assertIn("MERCENARY_CAPITAL", flags)
        self.assertIn("HIGH_COST_PER_USER", flags)
        self.assertIn("TVL_FARMING", flags)
        self.assertIn("TOKEN_DUMP", flags)
        self.assertNotIn("EFFECTIVE_RETENTION", flags)  # 5% < 60%


# ===========================================================================
# 8. TestAnalyzeSingle
# ===========================================================================

class TestAnalyzeSingle(unittest.TestCase):

    def test_returns_expected_keys(self):
        result = _analyze_single(_make_program(), {})
        for key in ("protocol", "program_type", "cost_per_user_usd", "cost_per_tvl_usd",
                    "roi_score", "efficiency_score", "mercenary_capital_risk",
                    "efficiency_label", "flags"):
            self.assertIn(key, result)

    def test_protocol_preserved(self):
        r = _analyze_single(_make_program(protocol="Uniswap"), {})
        self.assertEqual(r["protocol"], "Uniswap")

    def test_program_type_preserved(self):
        r = _analyze_single(_make_program(program_type="airdrop"), {})
        self.assertEqual(r["program_type"], "airdrop")

    def test_cost_per_user_computed(self):
        r = _analyze_single(_make_program(monthly_cost_usd=100_000, monthly_new_users=200), {})
        self.assertAlmostEqual(r["cost_per_user_usd"], 500.0, places=4)

    def test_mercenary_capital_risk_computed(self):
        r = _analyze_single(_make_program(retention_after_program_pct=30.0), {})
        self.assertAlmostEqual(r["mercenary_capital_risk"], 70.0, places=4)

    def test_excellent_program(self):
        # high TVL, low cost, high retention
        p = _make_program(
            monthly_cost_usd=10_000,
            monthly_new_users=500,
            monthly_tvl_added_usd=5_000_000,   # 500x cost -> roi=100
            retention_after_program_pct=90.0,   # high retention
        )
        r = _analyze_single(p, {})
        self.assertEqual(r["efficiency_label"], "EXCELLENT")

    def test_wasteful_program(self):
        # Zero tvl, high cost, zero retention
        p = _make_program(
            monthly_cost_usd=100_000,
            monthly_new_users=0,
            monthly_tvl_added_usd=0,
            retention_after_program_pct=0.0,
        )
        r = _analyze_single(p, {})
        self.assertEqual(r["efficiency_label"], "WASTEFUL")

    def test_missing_fields_use_defaults(self):
        r = _analyze_single({}, {})
        self.assertEqual(r["protocol"], "UNKNOWN")
        self.assertEqual(r["program_type"], "unknown")

    def test_duration_months_preserved(self):
        r = _analyze_single(_make_program(duration_months=6), {})
        self.assertEqual(r["duration_months"], 6)

    def test_token_price_change_preserved(self):
        r = _analyze_single(_make_program(token_price_change_during_pct=-20.0), {})
        self.assertAlmostEqual(r["token_price_change_during_pct"], -20.0, places=4)

    def test_flags_is_list(self):
        r = _analyze_single(_make_program(), {})
        self.assertIsInstance(r["flags"], list)


# ===========================================================================
# 9. TestAnalyzeMain
# ===========================================================================

class TestAnalyzeMain(unittest.TestCase):

    def test_empty_list_returns_empty(self):
        result = analyze([], {})
        self.assertEqual(result["analyses"], [])
        self.assertEqual(result["aggregate"]["total_count"], 0)
        self.assertIsNone(result["aggregate"]["most_efficient"])
        self.assertIsNone(result["aggregate"]["least_efficient"])

    def test_single_program(self):
        result = analyze([_make_program()], {})
        self.assertEqual(len(result["analyses"]), 1)
        self.assertEqual(result["aggregate"]["total_count"], 1)

    def test_most_and_least_efficient_identified(self):
        good = _make_program(
            protocol="GREAT",
            monthly_cost_usd=10_000,
            monthly_tvl_added_usd=5_000_000,
            retention_after_program_pct=90.0,
        )
        bad = _make_program(
            protocol="TERRIBLE",
            monthly_cost_usd=1_000_000,
            monthly_tvl_added_usd=0,
            retention_after_program_pct=0.0,
        )
        result = analyze([good, bad], {})
        self.assertEqual(result["aggregate"]["most_efficient"], "GREAT")
        self.assertEqual(result["aggregate"]["least_efficient"], "TERRIBLE")

    def test_total_monthly_cost(self):
        p1 = _make_program(monthly_cost_usd=50_000)
        p2 = _make_program(monthly_cost_usd=75_000)
        result = analyze([p1, p2], {})
        self.assertAlmostEqual(result["aggregate"]["total_monthly_cost_usd"], 125_000.0, places=2)

    def test_average_retention(self):
        p1 = _make_program(retention_after_program_pct=40.0)
        p2 = _make_program(retention_after_program_pct=60.0)
        result = analyze([p1, p2], {})
        self.assertAlmostEqual(result["aggregate"]["average_retention"], 50.0, places=4)

    def test_excellent_count(self):
        good = _make_program(
            monthly_cost_usd=10_000,
            monthly_tvl_added_usd=5_000_000,
            retention_after_program_pct=90.0,
        )
        result = analyze([good, good], {})
        self.assertEqual(result["aggregate"]["excellent_count"], 2)

    def test_timestamp_present(self):
        result = analyze([_make_program()], {})
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)

    def test_three_programs(self):
        programs = [_make_program(protocol=f"P{i}") for i in range(3)]
        result = analyze(programs, {})
        self.assertEqual(len(result["analyses"]), 3)
        self.assertEqual(result["aggregate"]["total_count"], 3)

    def test_analyses_length_matches_input(self):
        programs = [_make_program() for _ in range(7)]
        result = analyze(programs, {})
        self.assertEqual(len(result["analyses"]), 7)

    def test_empty_config_accepted(self):
        result = analyze([_make_program()], {})
        self.assertIsNotNone(result)

    def test_average_retention_empty_returns_zero(self):
        result = analyze([], {})
        self.assertAlmostEqual(result["aggregate"]["average_retention"], 0.0, places=4)

    def test_total_cost_empty_returns_zero(self):
        result = analyze([], {})
        self.assertAlmostEqual(result["aggregate"]["total_monthly_cost_usd"], 0.0, places=2)

    def test_excellent_count_zero_for_bad_programs(self):
        bad = _make_program(
            monthly_cost_usd=1_000_000,
            monthly_tvl_added_usd=0,
            retention_after_program_pct=0.0,
        )
        result = analyze([bad], {})
        self.assertEqual(result["aggregate"]["excellent_count"], 0)


# ===========================================================================
# 10. TestAppendLogIncentive
# ===========================================================================

class TestAppendLogIncentive(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test_incentive_log.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_file_if_not_exists(self):
        append_log({"key": "val"}, self.log_path)
        self.assertTrue(os.path.exists(self.log_path))

    def test_file_is_valid_json_list(self):
        append_log({"key": "val"}, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_single_append(self):
        append_log({"x": 1}, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["x"], 1)

    def test_multiple_appends(self):
        for i in range(5):
            append_log({"i": i}, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        for i in range(LOG_CAP + 10):
            append_log({"i": i}, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), LOG_CAP)

    def test_ring_buffer_keeps_latest(self):
        for i in range(LOG_CAP + 5):
            append_log({"i": i}, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["i"], LOG_CAP + 4)

    def test_corrupted_file_resets_gracefully(self):
        with open(self.log_path, "w") as f:
            f.write("CORRUPTED")
        append_log({"key": "new"}, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_creates_directory_if_missing(self):
        nested_path = os.path.join(self.tmpdir, "a", "b", "log.json")
        append_log({"x": 1}, nested_path)
        self.assertTrue(os.path.exists(nested_path))

    def test_non_list_file_resets(self):
        with open(self.log_path, "w") as f:
            json.dump({"not": "a list"}, f)
        append_log({"key": "new"}, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


# ===========================================================================
# 11. TestRunIncentive
# ===========================================================================

class TestRunIncentive(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "run_incentive_log.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_run_returns_dict(self):
        result = run([_make_program()], {}, self.log_path)
        self.assertIsInstance(result, dict)

    def test_run_writes_to_log(self):
        run([_make_program()], {}, self.log_path)
        self.assertTrue(os.path.exists(self.log_path))

    def test_run_empty_programs_writes_log(self):
        run([], {}, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_run_result_has_analyses(self):
        result = run([_make_program()], {}, self.log_path)
        self.assertIn("analyses", result)

    def test_run_accumulates_log_entries(self):
        for _ in range(3):
            run([_make_program()], {}, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)


# ===========================================================================
# 12. TestEdgeCasesIncentive
# ===========================================================================

class TestEdgeCasesIncentive(unittest.TestCase):

    def test_single_program_best_equals_worst(self):
        result = analyze([_make_program(protocol="ONLY")], {})
        self.assertEqual(result["aggregate"]["most_efficient"], "ONLY")
        self.assertEqual(result["aggregate"]["least_efficient"], "ONLY")

    def test_all_program_types(self):
        programs = [
            _make_program(protocol=pt, program_type=pt)
            for pt in ["liquidity_mining", "referral", "points", "airdrop", "staking_rewards"]
        ]
        result = analyze(programs, {})
        self.assertEqual(len(result["analyses"]), 5)

    def test_scores_are_rounded(self):
        r = _analyze_single(_make_program(), {})
        s = str(r["roi_score"])
        if "." in s:
            self.assertLessEqual(len(s.split(".")[1]), 4)

    def test_all_efficiency_labels_reachable(self):
        self.assertEqual(_efficiency_label(100), "EXCELLENT")
        self.assertEqual(_efficiency_label(70),  "GOOD")
        self.assertEqual(_efficiency_label(50),  "FAIR")
        self.assertEqual(_efficiency_label(25),  "POOR")
        self.assertEqual(_efficiency_label(10),  "WASTEFUL")

    def test_zero_users_program(self):
        p = _make_program(monthly_new_users=0, monthly_cost_usd=50_000)
        r = _analyze_single(p, {})
        # cost_per_user should be None (inf -> None)
        self.assertIsNone(r["cost_per_user_usd"])

    def test_zero_tvl_program(self):
        p = _make_program(monthly_tvl_added_usd=0, monthly_cost_usd=50_000)
        r = _analyze_single(p, {})
        self.assertIsNone(r["cost_per_tvl_usd"])

    def test_high_retention_effective_flag(self):
        p = _make_program(retention_after_program_pct=70.0)
        r = _analyze_single(p, {})
        self.assertIn("EFFECTIVE_RETENTION", r["flags"])

    def test_low_retention_mercenary_flag(self):
        p = _make_program(retention_after_program_pct=10.0)
        r = _analyze_single(p, {})
        self.assertIn("MERCENARY_CAPITAL", r["flags"])

    def test_token_dump_flag_via_analyze_single(self):
        p = _make_program(token_price_change_during_pct=-40.0)
        r = _analyze_single(p, {})
        self.assertIn("TOKEN_DUMP", r["flags"])

    def test_roi_full_multiple_constant_used(self):
        # roi at exactly ROI_FULL_MULTIPLE * cost should be 100
        cost = 100_000.0
        tvl  = ROI_FULL_MULTIPLE * cost
        self.assertAlmostEqual(_roi_score(tvl, cost), 100.0, places=4)

    def test_config_not_used_but_accepted(self):
        config = {"irrelevant": True}
        result = analyze([_make_program()], config)
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
