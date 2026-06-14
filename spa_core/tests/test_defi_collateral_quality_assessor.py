"""
Tests for MP-920 DeFiCollateralQualityAssessor
Run with: python3 -m unittest spa_core.tests.test_defi_collateral_quality_assessor
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_collateral_quality_assessor import (
    assess,
    append_log,
    run,
    _liquidity_adequacy_score,
    _volatility_penalty,
    _oracle_trust_score,
    _composite_quality_score,
    _quality_label,
    _compute_flags,
    _assess_single,
    LOW_LIQUIDITY_THRESHOLD,
    HIGH_VOLATILITY_THRESHOLD,
    CENTRALIZATION_RISK_THRESHOLD,
    LOG_CAP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_collateral(
    token="WETH",
    protocol="Aave",
    ltv_pct=75.0,
    liquidation_bonus_pct=5.0,
    market_cap_usd=200_000_000.0,
    daily_volume_usd=10_000_000.0,
    price_30d_volatility_pct=30.0,
    correlation_to_eth=1.0,
    centralization_risk=0.1,
    depeg_incidents_count=0,
    oracle_type="chainlink",
):
    return {
        "token": token,
        "protocol": protocol,
        "ltv_pct": ltv_pct,
        "liquidation_bonus_pct": liquidation_bonus_pct,
        "market_cap_usd": market_cap_usd,
        "daily_volume_usd": daily_volume_usd,
        "price_30d_volatility_pct": price_30d_volatility_pct,
        "correlation_to_eth": correlation_to_eth,
        "centralization_risk": centralization_risk,
        "depeg_incidents_count": depeg_incidents_count,
        "oracle_type": oracle_type,
    }


# ===========================================================================
# 1. TestLiquidityAdequacyScore
# ===========================================================================

class TestLiquidityAdequacyScore(unittest.TestCase):

    def test_zero_mcap_returns_zero(self):
        self.assertEqual(_liquidity_adequacy_score(1_000_000, 0), 0.0)

    def test_negative_mcap_returns_zero(self):
        self.assertEqual(_liquidity_adequacy_score(1_000_000, -1), 0.0)

    def test_exact_two_percent_returns_100(self):
        # vol/mcap = 0.02 exactly -> score = 100
        self.assertAlmostEqual(_liquidity_adequacy_score(200_000, 10_000_000), 100.0, places=4)

    def test_above_threshold_capped_at_100(self):
        # vol/mcap = 0.10 -> would be 500, capped at 100
        self.assertAlmostEqual(_liquidity_adequacy_score(1_000_000, 10_000_000), 100.0, places=4)

    def test_one_percent_returns_50(self):
        # vol/mcap = 0.01 -> 0.01/0.02 * 100 = 50
        self.assertAlmostEqual(_liquidity_adequacy_score(100_000, 10_000_000), 50.0, places=4)

    def test_zero_volume_returns_zero(self):
        self.assertAlmostEqual(_liquidity_adequacy_score(0, 10_000_000), 0.0, places=4)

    def test_half_percent_returns_25(self):
        # vol/mcap = 0.005 -> 25
        self.assertAlmostEqual(_liquidity_adequacy_score(50_000, 10_000_000), 25.0, places=4)

    def test_output_never_negative(self):
        self.assertGreaterEqual(_liquidity_adequacy_score(0, 1_000_000), 0.0)

    def test_output_never_exceeds_100(self):
        self.assertLessEqual(_liquidity_adequacy_score(1e12, 1_000_000), 100.0)


# ===========================================================================
# 2. TestVolatilityPenalty
# ===========================================================================

class TestVolatilityPenalty(unittest.TestCase):

    def test_zero_volatility_zero_penalty(self):
        self.assertAlmostEqual(_volatility_penalty(0.0), 0.0, places=4)

    def test_100_pct_volatility_max_penalty(self):
        self.assertAlmostEqual(_volatility_penalty(100.0), 100.0, places=4)

    def test_60_pct_threshold(self):
        self.assertAlmostEqual(_volatility_penalty(60.0), 60.0, places=4)

    def test_above_100_capped(self):
        self.assertAlmostEqual(_volatility_penalty(200.0), 100.0, places=4)

    def test_negative_clamped_to_zero(self):
        self.assertAlmostEqual(_volatility_penalty(-10.0), 0.0, places=4)

    def test_partial_value_30(self):
        self.assertAlmostEqual(_volatility_penalty(30.0), 30.0, places=4)

    def test_partial_value_45(self):
        self.assertAlmostEqual(_volatility_penalty(45.0), 45.0, places=4)


# ===========================================================================
# 3. TestOracleTrustScore
# ===========================================================================

class TestOracleTrustScore(unittest.TestCase):

    def test_chainlink_score(self):
        self.assertAlmostEqual(_oracle_trust_score("chainlink"), 90.0, places=4)

    def test_uniswap_twap_score(self):
        self.assertAlmostEqual(_oracle_trust_score("uniswap_twap"), 70.0, places=4)

    def test_band_score(self):
        self.assertAlmostEqual(_oracle_trust_score("band"), 60.0, places=4)

    def test_custom_score(self):
        self.assertAlmostEqual(_oracle_trust_score("custom"), 20.0, places=4)

    def test_unknown_returns_default(self):
        self.assertAlmostEqual(_oracle_trust_score("pyth"), 10.0, places=4)

    def test_empty_string_returns_default(self):
        self.assertAlmostEqual(_oracle_trust_score(""), 10.0, places=4)

    def test_case_insensitive_chainlink(self):
        self.assertAlmostEqual(_oracle_trust_score("CHAINLINK"), 90.0, places=4)

    def test_case_insensitive_custom(self):
        self.assertAlmostEqual(_oracle_trust_score("CUSTOM"), 20.0, places=4)

    def test_none_like_empty_default(self):
        # oracle_type = None falls to default
        self.assertAlmostEqual(_oracle_trust_score(None), 10.0, places=4)


# ===========================================================================
# 4. TestCompositeQualityScore
# ===========================================================================

class TestCompositeQualityScore(unittest.TestCase):

    def test_perfect_inputs(self):
        # oracle=90, liq=100, vol_pen=0, cent=0, depeg=0
        # = 90*0.50 + 100*0.50 - 0 - 0 - 0 = 45 + 50 = 95
        score = _composite_quality_score(100, 0, 90, 0.0, 0)
        self.assertAlmostEqual(score, 95.0, places=4)

    def test_zero_inputs_return_zero(self):
        score = _composite_quality_score(0, 0, 0, 0.0, 0)
        self.assertAlmostEqual(score, 0.0, places=4)

    def test_clamped_to_zero_minimum(self):
        # high penalties
        score = _composite_quality_score(0, 100, 0, 1.0, 100)
        self.assertEqual(score, 0.0)

    def test_clamped_to_100_maximum(self):
        score = _composite_quality_score(100, 0, 100, 0.0, 0)
        self.assertLessEqual(score, 100.0)

    def test_depeg_penalty_capped_at_10(self):
        # 3 incidents: 3*5=15, capped at 10
        score_3 = _composite_quality_score(100, 0, 90, 0.0, 3)
        score_2 = _composite_quality_score(100, 0, 90, 0.0, 2)
        # 3 incidents only 10 penalty (same as 2 → 2*5=10)
        self.assertAlmostEqual(score_3, score_2, places=4)

    def test_centralization_penalty(self):
        score_low  = _composite_quality_score(100, 0, 90, 0.0, 0)
        score_high = _composite_quality_score(100, 0, 90, 1.0, 0)
        self.assertGreater(score_low, score_high)

    def test_volatility_penalty_effect(self):
        score_low  = _composite_quality_score(100, 0,   90, 0.0, 0)
        score_high = _composite_quality_score(100, 100, 90, 0.0, 0)
        self.assertGreater(score_low, score_high)

    def test_liq_score_contribution(self):
        score_low  = _composite_quality_score(0,   0, 90, 0.0, 0)
        score_high = _composite_quality_score(100, 0, 90, 0.0, 0)
        self.assertGreater(score_high, score_low)


# ===========================================================================
# 5. TestQualityLabel
# ===========================================================================

class TestQualityLabel(unittest.TestCase):

    def test_excellent_at_80(self):
        self.assertEqual(_quality_label(80.0), "EXCELLENT")

    def test_excellent_at_100(self):
        self.assertEqual(_quality_label(100.0), "EXCELLENT")

    def test_good_at_60(self):
        self.assertEqual(_quality_label(60.0), "GOOD")

    def test_good_at_79(self):
        self.assertEqual(_quality_label(79.9), "GOOD")

    def test_adequate_at_40(self):
        self.assertEqual(_quality_label(40.0), "ADEQUATE")

    def test_poor_at_20(self):
        self.assertEqual(_quality_label(20.0), "POOR")

    def test_unsuitable_at_19(self):
        self.assertEqual(_quality_label(19.9), "UNSUITABLE")

    def test_unsuitable_at_zero(self):
        self.assertEqual(_quality_label(0.0), "UNSUITABLE")


# ===========================================================================
# 6. TestComputeFlags
# ===========================================================================

class TestComputeFlags(unittest.TestCase):

    def test_no_flags_clean_collateral(self):
        flags = _compute_flags(
            daily_volume_usd=1_000_000,
            market_cap_usd=10_000_000,   # 10% ratio > 2%
            price_30d_volatility_pct=30.0,
            centralization_risk=0.2,
            oracle_type="chainlink",
            depeg_incidents_count=0,
        )
        self.assertEqual(flags, [])

    def test_high_volatility_flag(self):
        flags = _compute_flags(1_000_000, 10_000_000, 70.0, 0.2, "chainlink", 0)
        self.assertIn("HIGH_VOLATILITY", flags)

    def test_no_high_volatility_at_boundary(self):
        flags = _compute_flags(1_000_000, 10_000_000, 60.0, 0.2, "chainlink", 0)
        self.assertNotIn("HIGH_VOLATILITY", flags)

    def test_low_liquidity_flag(self):
        # vol/mcap = 0.001 < 0.02
        flags = _compute_flags(10_000, 10_000_000, 30.0, 0.2, "chainlink", 0)
        self.assertIn("LOW_LIQUIDITY", flags)

    def test_low_liquidity_zero_mcap(self):
        flags = _compute_flags(10_000, 0, 30.0, 0.2, "chainlink", 0)
        self.assertIn("LOW_LIQUIDITY", flags)

    def test_centralized_risk_flag(self):
        flags = _compute_flags(1_000_000, 10_000_000, 30.0, 0.8, "chainlink", 0)
        self.assertIn("CENTRALIZED_RISK", flags)

    def test_no_centralized_risk_at_boundary(self):
        flags = _compute_flags(1_000_000, 10_000_000, 30.0, 0.7, "chainlink", 0)
        self.assertNotIn("CENTRALIZED_RISK", flags)

    def test_custom_oracle_flag(self):
        flags = _compute_flags(1_000_000, 10_000_000, 30.0, 0.2, "custom", 0)
        self.assertIn("CUSTOM_ORACLE", flags)

    def test_chainlink_no_custom_oracle_flag(self):
        flags = _compute_flags(1_000_000, 10_000_000, 30.0, 0.2, "chainlink", 0)
        self.assertNotIn("CUSTOM_ORACLE", flags)

    def test_depeg_history_flag(self):
        flags = _compute_flags(1_000_000, 10_000_000, 30.0, 0.2, "chainlink", 1)
        self.assertIn("DEPEG_HISTORY", flags)

    def test_no_depeg_history_flag_at_zero(self):
        flags = _compute_flags(1_000_000, 10_000_000, 30.0, 0.2, "chainlink", 0)
        self.assertNotIn("DEPEG_HISTORY", flags)

    def test_multiple_flags_at_once(self):
        flags = _compute_flags(0, 0, 90.0, 0.9, "custom", 3)
        self.assertIn("HIGH_VOLATILITY", flags)
        self.assertIn("LOW_LIQUIDITY", flags)
        self.assertIn("CENTRALIZED_RISK", flags)
        self.assertIn("CUSTOM_ORACLE", flags)
        self.assertIn("DEPEG_HISTORY", flags)


# ===========================================================================
# 7. TestAssessSingle
# ===========================================================================

class TestAssessSingle(unittest.TestCase):

    def test_returns_expected_keys(self):
        result = _assess_single(_make_collateral(), {})
        for key in ("token", "protocol", "liquidity_adequacy_score",
                    "volatility_penalty", "oracle_trust_score",
                    "composite_quality_score", "quality_label", "flags"):
            self.assertIn(key, result)

    def test_token_and_protocol_preserved(self):
        c = _make_collateral(token="DAI", protocol="Compound")
        r = _assess_single(c, {})
        self.assertEqual(r["token"], "DAI")
        self.assertEqual(r["protocol"], "Compound")

    def test_ltv_pct_preserved(self):
        c = _make_collateral(ltv_pct=60.0)
        r = _assess_single(c, {})
        self.assertAlmostEqual(r["ltv_pct"], 60.0, places=4)

    def test_chainlink_oracle_scores_high(self):
        c = _make_collateral(oracle_type="chainlink")
        r = _assess_single(c, {})
        self.assertAlmostEqual(r["oracle_trust_score"], 90.0, places=4)

    def test_high_vol_flags_set(self):
        c = _make_collateral(price_30d_volatility_pct=90.0)
        r = _assess_single(c, {})
        self.assertIn("HIGH_VOLATILITY", r["flags"])

    def test_depeg_history_in_flags(self):
        c = _make_collateral(depeg_incidents_count=2)
        r = _assess_single(c, {})
        self.assertIn("DEPEG_HISTORY", r["flags"])

    def test_excellent_collateral(self):
        # Best possible collateral
        c = _make_collateral(
            market_cap_usd=1_000_000_000,
            daily_volume_usd=100_000_000,  # 10% ratio
            price_30d_volatility_pct=5.0,
            centralization_risk=0.0,
            depeg_incidents_count=0,
            oracle_type="chainlink",
        )
        r = _assess_single(c, {})
        self.assertEqual(r["quality_label"], "EXCELLENT")

    def test_unsuitable_collateral(self):
        # Worst possible
        c = _make_collateral(
            market_cap_usd=100_000,
            daily_volume_usd=100,          # low liquidity
            price_30d_volatility_pct=100.0,
            centralization_risk=1.0,
            depeg_incidents_count=10,
            oracle_type="custom",
        )
        r = _assess_single(c, {})
        self.assertEqual(r["quality_label"], "UNSUITABLE")

    def test_missing_fields_use_defaults(self):
        # Minimal dict
        r = _assess_single({}, {})
        self.assertEqual(r["token"], "UNKNOWN")
        self.assertEqual(r["oracle_type"], "custom")

    def test_depeg_count_preserved(self):
        c = _make_collateral(depeg_incidents_count=3)
        r = _assess_single(c, {})
        self.assertEqual(r["depeg_incidents_count"], 3)


# ===========================================================================
# 8. TestAssessMain
# ===========================================================================

class TestAssessMain(unittest.TestCase):

    def test_empty_list_returns_empty(self):
        result = assess([], {})
        self.assertEqual(result["assessments"], [])
        self.assertEqual(result["aggregate"]["total_count"], 0)
        self.assertIsNone(result["aggregate"]["best_collateral"])
        self.assertIsNone(result["aggregate"]["worst_collateral"])

    def test_single_collateral(self):
        result = assess([_make_collateral()], {})
        self.assertEqual(len(result["assessments"]), 1)
        self.assertEqual(result["aggregate"]["total_count"], 1)

    def test_best_and_worst_identified(self):
        good = _make_collateral(
            token="GOOD",
            market_cap_usd=1_000_000_000, daily_volume_usd=100_000_000,
            price_30d_volatility_pct=5.0, centralization_risk=0.0,
            depeg_incidents_count=0, oracle_type="chainlink",
        )
        bad = _make_collateral(
            token="BAD",
            market_cap_usd=100_000, daily_volume_usd=100,
            price_30d_volatility_pct=100.0, centralization_risk=1.0,
            depeg_incidents_count=5, oracle_type="custom",
        )
        result = assess([good, bad], {})
        self.assertEqual(result["aggregate"]["best_collateral"], "GOOD")
        self.assertEqual(result["aggregate"]["worst_collateral"], "BAD")

    def test_unsuitable_count(self):
        bad = _make_collateral(
            market_cap_usd=100_000, daily_volume_usd=100,
            price_30d_volatility_pct=100.0, centralization_risk=1.0,
            depeg_incidents_count=5, oracle_type="custom",
        )
        result = assess([bad, bad], {})
        self.assertEqual(result["aggregate"]["unsuitable_count"], 2)

    def test_excellent_count(self):
        good = _make_collateral(
            market_cap_usd=1_000_000_000, daily_volume_usd=100_000_000,
            price_30d_volatility_pct=5.0, centralization_risk=0.0,
            depeg_incidents_count=0, oracle_type="chainlink",
        )
        result = assess([good, good], {})
        self.assertEqual(result["aggregate"]["excellent_count"], 2)

    def test_average_quality_computed(self):
        c1 = _make_collateral(token="A")
        c2 = _make_collateral(token="B")
        result = assess([c1, c2], {})
        scores = [a["composite_quality_score"] for a in result["assessments"]]
        expected_avg = sum(scores) / len(scores)
        self.assertAlmostEqual(result["aggregate"]["average_quality"], expected_avg, places=3)

    def test_timestamp_present(self):
        result = assess([_make_collateral()], {})
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)

    def test_three_collaterals(self):
        collaterals = [
            _make_collateral(token="A"),
            _make_collateral(token="B"),
            _make_collateral(token="C"),
        ]
        result = assess(collaterals, {})
        self.assertEqual(len(result["assessments"]), 3)
        self.assertEqual(result["aggregate"]["total_count"], 3)

    def test_assessments_list_length_matches_input(self):
        collaterals = [_make_collateral() for _ in range(5)]
        result = assess(collaterals, {})
        self.assertEqual(len(result["assessments"]), 5)

    def test_empty_config_accepted(self):
        result = assess([_make_collateral()], {})
        self.assertIsNotNone(result)

    def test_unsuitable_count_is_zero_for_good_collateral(self):
        good = _make_collateral(
            market_cap_usd=1_000_000_000, daily_volume_usd=100_000_000,
            price_30d_volatility_pct=5.0, centralization_risk=0.0,
            depeg_incidents_count=0, oracle_type="chainlink",
        )
        result = assess([good], {})
        self.assertEqual(result["aggregate"]["unsuitable_count"], 0)

    def test_average_quality_empty_returns_zero(self):
        result = assess([], {})
        self.assertAlmostEqual(result["aggregate"]["average_quality"], 0.0, places=4)


# ===========================================================================
# 9. TestAppendLog
# ===========================================================================

class TestAppendLog(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test_collateral_log.json")

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
        # Latest should be i = LOG_CAP + 4
        self.assertEqual(data[-1]["i"], LOG_CAP + 4)

    def test_corrupted_file_resets_gracefully(self):
        with open(self.log_path, "w") as f:
            f.write("NOT JSON")
        append_log({"key": "new"}, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_creates_directory_if_missing(self):
        nested_path = os.path.join(self.tmpdir, "sub", "dir", "log.json")
        append_log({"x": 1}, nested_path)
        self.assertTrue(os.path.exists(nested_path))


# ===========================================================================
# 10. TestRun
# ===========================================================================

class TestRun(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "run_test_log.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_run_returns_dict(self):
        result = run([_make_collateral()], {}, self.log_path)
        self.assertIsInstance(result, dict)

    def test_run_writes_to_log(self):
        run([_make_collateral()], {}, self.log_path)
        self.assertTrue(os.path.exists(self.log_path))

    def test_run_empty_collaterals_writes_log(self):
        run([], {}, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_run_result_has_assessments(self):
        result = run([_make_collateral()], {}, self.log_path)
        self.assertIn("assessments", result)

    def test_run_accumulates_log_entries(self):
        for _ in range(3):
            run([_make_collateral()], {}, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)


# ===========================================================================
# 11. TestEdgeCases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_single_collateral_best_equals_worst(self):
        result = assess([_make_collateral(token="ONLY")], {})
        self.assertEqual(result["aggregate"]["best_collateral"], "ONLY")
        self.assertEqual(result["aggregate"]["worst_collateral"], "ONLY")

    def test_scores_are_rounded(self):
        r = _assess_single(_make_collateral(), {})
        # Check composite_quality_score has at most 4 decimal places
        s = str(r["composite_quality_score"])
        if "." in s:
            self.assertLessEqual(len(s.split(".")[1]), 4)

    def test_flags_is_list(self):
        r = _assess_single(_make_collateral(), {})
        self.assertIsInstance(r["flags"], list)

    def test_config_not_used_but_accepted(self):
        config = {"some_key": "some_val"}
        result = assess([_make_collateral()], config)
        self.assertIsNotNone(result)

    def test_mixed_oracle_types(self):
        collaterals = [
            _make_collateral(token="CL", oracle_type="chainlink"),
            _make_collateral(token="TW", oracle_type="uniswap_twap"),
            _make_collateral(token="BA", oracle_type="band"),
            _make_collateral(token="CU", oracle_type="custom"),
        ]
        result = assess(collaterals, {})
        self.assertEqual(len(result["assessments"]), 4)
        labels = {a["token"]: a["oracle_trust_score"] for a in result["assessments"]}
        self.assertAlmostEqual(labels["CL"], 90.0, places=4)
        self.assertAlmostEqual(labels["TW"], 70.0, places=4)
        self.assertAlmostEqual(labels["BA"], 60.0, places=4)
        self.assertAlmostEqual(labels["CU"], 20.0, places=4)

    def test_zero_depeg_no_depeg_flag(self):
        r = _assess_single(_make_collateral(depeg_incidents_count=0), {})
        self.assertNotIn("DEPEG_HISTORY", r["flags"])

    def test_positive_depeg_count_adds_flag(self):
        r = _assess_single(_make_collateral(depeg_incidents_count=1), {})
        self.assertIn("DEPEG_HISTORY", r["flags"])

    def test_correlation_to_eth_preserved(self):
        c = _make_collateral(correlation_to_eth=0.75)
        r = _assess_single(c, {})
        self.assertAlmostEqual(r["correlation_to_eth"], 0.75, places=4)

    def test_liquidation_bonus_preserved(self):
        c = _make_collateral(liquidation_bonus_pct=8.5)
        r = _assess_single(c, {})
        self.assertAlmostEqual(r["liquidation_bonus_pct"], 8.5, places=4)

    def test_all_quality_labels_reachable(self):
        """Verify all 5 quality label strings are reachable."""
        self.assertEqual(_quality_label(100), "EXCELLENT")
        self.assertEqual(_quality_label(70),  "GOOD")
        self.assertEqual(_quality_label(50),  "ADEQUATE")
        self.assertEqual(_quality_label(25),  "POOR")
        self.assertEqual(_quality_label(10),  "UNSUITABLE")


if __name__ == "__main__":
    unittest.main()
