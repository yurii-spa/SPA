"""
Tests for MP-1124 DeFiProtocolOracleManipulationRiskScorer.
Run: python3 -m unittest spa_core.tests.test_defi_protocol_oracle_manipulation_risk_scorer -v

Coverage targets (≥110 test methods):
  - compute_oracle_source_score   (all types + unknown + casing)
  - compute_manipulation_cost_ratio (normal, zero flash loan, equal, large)
  - compute_tvl_at_risk_ratio     (single-source vs multi, zero liquidity)
  - compute_circuit_breaker_bonus (True / False)
  - compute_multi_source_bonus    (0,1,2,3,4,5,10 sources; clamping)
  - compute_manipulation_risk_score (formula, clamping)
  - risk_label                    (all 5 bands + boundaries)
  - DeFiProtocolOracleManipulationRiskScorer.score() (keys, types, values)
  - score_and_log() / ring-buffer / atomic write
  - score_batch()
  - run() module function
  - Edge cases (negative inputs, zero TVL, very large numbers)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.defi_protocol_oracle_manipulation_risk_scorer import (
    DeFiProtocolOracleManipulationRiskScorer,
    compute_oracle_source_score,
    compute_manipulation_cost_ratio,
    compute_tvl_at_risk_ratio,
    compute_circuit_breaker_bonus,
    compute_multi_source_bonus,
    compute_manipulation_risk_score,
    risk_label,
    _atomic_write,
    _load_log,
    _append_log,
    _iso_now,
    _resolve_log_path,
    run,
    ORACLE_SOURCE_SCORES,
    LOG_MAX_ENTRIES,
    CIRCUIT_BREAKER_BONUS,
    MULTI_SOURCE_BONUS_PER_EXTRA,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_scorer(tmp_dir=None):
    return DeFiProtocolOracleManipulationRiskScorer(data_dir=tmp_dir)


def _score(scorer, **kwargs):
    defaults = dict(
        oracle_type="chainlink",
        twap_period_minutes=0,
        oracle_pool_liquidity_usd=0.0,
        protocol_tvl_usd=50_000_000.0,
        max_flash_loan_available_usd=500_000_000.0,
        num_oracle_sources=5,
        has_circuit_breaker=True,
        protocol_name="TestProtocol",
    )
    defaults.update(kwargs)
    return scorer.score(**defaults)


# ===========================================================================
# 1. compute_oracle_source_score
# ===========================================================================

class TestComputeOracleSourceScore(unittest.TestCase):

    def test_chainlink_score(self):
        self.assertEqual(compute_oracle_source_score("chainlink"), 40)

    def test_pyth_score(self):
        self.assertEqual(compute_oracle_source_score("pyth"), 35)

    def test_twap_curve_score(self):
        self.assertEqual(compute_oracle_source_score("twap_curve"), 25)

    def test_twap_uniswap_score(self):
        self.assertEqual(compute_oracle_source_score("twap_uniswap"), 20)

    def test_band_score(self):
        self.assertEqual(compute_oracle_source_score("band"), 20)

    def test_single_dex_score(self):
        self.assertEqual(compute_oracle_source_score("single_dex"), 5)

    def test_custom_score(self):
        self.assertEqual(compute_oracle_source_score("custom"), 0)

    def test_unknown_type_returns_zero(self):
        self.assertEqual(compute_oracle_source_score("nonexistent_oracle"), 0)

    def test_empty_string_returns_zero(self):
        self.assertEqual(compute_oracle_source_score(""), 0)

    def test_chainlink_is_highest(self):
        self.assertGreater(
            compute_oracle_source_score("chainlink"),
            compute_oracle_source_score("pyth"),
        )

    def test_custom_is_lowest(self):
        self.assertEqual(compute_oracle_source_score("custom"), 0)
        for ot in ORACLE_SOURCE_SCORES:
            if ot != "custom":
                self.assertGreaterEqual(compute_oracle_source_score(ot), 0)

    def test_single_dex_lower_than_twap_uniswap(self):
        self.assertLess(
            compute_oracle_source_score("single_dex"),
            compute_oracle_source_score("twap_uniswap"),
        )

    def test_twap_curve_higher_than_twap_uniswap(self):
        self.assertGreater(
            compute_oracle_source_score("twap_curve"),
            compute_oracle_source_score("twap_uniswap"),
        )

    def test_pyth_lower_than_chainlink(self):
        self.assertLess(
            compute_oracle_source_score("pyth"),
            compute_oracle_source_score("chainlink"),
        )

    def test_all_scores_in_range(self):
        for ot, score in ORACLE_SOURCE_SCORES.items():
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 40)

    def test_scores_are_integers(self):
        for ot in ORACLE_SOURCE_SCORES:
            self.assertIsInstance(compute_oracle_source_score(ot), int)

    def test_uppercase_not_found(self):
        # uppercase will return 0 (not in dict without .lower() case normalization)
        # Our impl does .lower() so it should still find it
        self.assertEqual(compute_oracle_source_score("CHAINLINK"), 40)

    def test_mixed_case(self):
        self.assertEqual(compute_oracle_source_score("Pyth"), 35)


# ===========================================================================
# 2. compute_manipulation_cost_ratio
# ===========================================================================

class TestComputeManipulationCostRatio(unittest.TestCase):

    def test_normal_ratio(self):
        # 1M liquidity / 10M flash loan = 0.1
        r = compute_manipulation_cost_ratio(1_000_000.0, 10_000_000.0)
        self.assertAlmostEqual(r, 0.1)

    def test_liquidity_larger_than_flash_loan(self):
        # safer: ratio > 1
        r = compute_manipulation_cost_ratio(10_000_000.0, 1_000_000.0)
        self.assertAlmostEqual(r, 10.0)

    def test_equal_liquidity_and_flash_loan(self):
        r = compute_manipulation_cost_ratio(5_000_000.0, 5_000_000.0)
        self.assertAlmostEqual(r, 1.0)

    def test_zero_flash_loan_returns_zero(self):
        r = compute_manipulation_cost_ratio(1_000_000.0, 0.0)
        self.assertEqual(r, 0.0)

    def test_zero_liquidity(self):
        r = compute_manipulation_cost_ratio(0.0, 1_000_000.0)
        self.assertAlmostEqual(r, 0.0)

    def test_both_zero_returns_zero(self):
        r = compute_manipulation_cost_ratio(0.0, 0.0)
        self.assertEqual(r, 0.0)

    def test_large_flash_loan(self):
        r = compute_manipulation_cost_ratio(1_000_000.0, 1_000_000_000.0)
        self.assertAlmostEqual(r, 0.001)

    def test_negative_flash_loan_returns_zero(self):
        # negative flash loan → treat as 0
        r = compute_manipulation_cost_ratio(1_000_000.0, -500_000.0)
        self.assertEqual(r, 0.0)

    def test_returns_float(self):
        r = compute_manipulation_cost_ratio(1_000_000.0, 5_000_000.0)
        self.assertIsInstance(r, float)


# ===========================================================================
# 3. compute_tvl_at_risk_ratio
# ===========================================================================

class TestComputeTvlAtRiskRatio(unittest.TestCase):

    def test_single_source_normal(self):
        # 50M TVL / 2M liquidity = 25.0
        r = compute_tvl_at_risk_ratio(50_000_000.0, 2_000_000.0, 1)
        self.assertAlmostEqual(r, 25.0)

    def test_multi_source_returns_zero(self):
        r = compute_tvl_at_risk_ratio(50_000_000.0, 2_000_000.0, 2)
        self.assertEqual(r, 0.0)

    def test_five_sources_returns_zero(self):
        r = compute_tvl_at_risk_ratio(50_000_000.0, 2_000_000.0, 5)
        self.assertEqual(r, 0.0)

    def test_single_source_zero_liquidity_returns_zero(self):
        r = compute_tvl_at_risk_ratio(50_000_000.0, 0.0, 1)
        self.assertEqual(r, 0.0)

    def test_single_source_equal_tvl_and_liquidity(self):
        r = compute_tvl_at_risk_ratio(10_000_000.0, 10_000_000.0, 1)
        self.assertAlmostEqual(r, 1.0)

    def test_single_source_zero_tvl(self):
        r = compute_tvl_at_risk_ratio(0.0, 5_000_000.0, 1)
        self.assertAlmostEqual(r, 0.0)

    def test_zero_sources_treated_as_single(self):
        # 0 sources — not really meaningful, but num_oracle_sources == 1 condition
        # num=0 ≠ 1, so should return 0
        r = compute_tvl_at_risk_ratio(50_000_000.0, 2_000_000.0, 0)
        self.assertEqual(r, 0.0)

    def test_returns_float(self):
        r = compute_tvl_at_risk_ratio(1_000.0, 100.0, 1)
        self.assertIsInstance(r, float)


# ===========================================================================
# 4. compute_circuit_breaker_bonus
# ===========================================================================

class TestComputeCircuitBreakerBonus(unittest.TestCase):

    def test_true_gives_bonus(self):
        self.assertEqual(compute_circuit_breaker_bonus(True), CIRCUIT_BREAKER_BONUS)

    def test_false_gives_zero(self):
        self.assertEqual(compute_circuit_breaker_bonus(False), 0)

    def test_bonus_is_15(self):
        self.assertEqual(compute_circuit_breaker_bonus(True), 15)

    def test_return_type_int(self):
        self.assertIsInstance(compute_circuit_breaker_bonus(True), int)
        self.assertIsInstance(compute_circuit_breaker_bonus(False), int)


# ===========================================================================
# 5. compute_multi_source_bonus
# ===========================================================================

class TestComputeMultiSourceBonus(unittest.TestCase):

    def test_one_source_zero_bonus(self):
        self.assertEqual(compute_multi_source_bonus(1), 0)

    def test_two_sources_one_extra(self):
        self.assertEqual(compute_multi_source_bonus(2), 1 * MULTI_SOURCE_BONUS_PER_EXTRA)

    def test_three_sources_two_extras(self):
        self.assertEqual(compute_multi_source_bonus(3), 2 * MULTI_SOURCE_BONUS_PER_EXTRA)

    def test_four_sources_max_extras(self):
        self.assertEqual(compute_multi_source_bonus(4), 3 * MULTI_SOURCE_BONUS_PER_EXTRA)

    def test_five_sources_still_max(self):
        self.assertEqual(compute_multi_source_bonus(5), 3 * MULTI_SOURCE_BONUS_PER_EXTRA)

    def test_ten_sources_still_max(self):
        self.assertEqual(compute_multi_source_bonus(10), 3 * MULTI_SOURCE_BONUS_PER_EXTRA)

    def test_max_bonus_is_15(self):
        self.assertEqual(compute_multi_source_bonus(100), 15)

    def test_zero_sources_returns_zero(self):
        # max(0-1, 0) = 0
        self.assertEqual(compute_multi_source_bonus(0), 0)

    def test_negative_sources_returns_zero(self):
        self.assertEqual(compute_multi_source_bonus(-5), 0)

    def test_returns_int(self):
        self.assertIsInstance(compute_multi_source_bonus(3), int)


# ===========================================================================
# 6. compute_manipulation_risk_score
# ===========================================================================

class TestComputeManipulationRiskScore(unittest.TestCase):

    def test_basic_formula(self):
        # 100 - 40 - 15 - 15 = 30
        s = compute_manipulation_risk_score(40, 15, 15)
        self.assertEqual(s, 30)

    def test_zero_all_bonuses_and_source_score(self):
        # 100 - 0 - 0 - 0 = 100
        self.assertEqual(compute_manipulation_risk_score(0, 0, 0), 100)

    def test_max_all_safeguards(self):
        # 100 - 40 - 15 - 15 = 30
        self.assertEqual(compute_manipulation_risk_score(40, 15, 15), 30)

    def test_clamped_above_100(self):
        # Should not exceed 100
        self.assertEqual(compute_manipulation_risk_score(-10, 0, 0), 100)

    def test_clamped_below_zero(self):
        # 100 - 100 - 100 - 100 = -200 → 0
        self.assertEqual(compute_manipulation_risk_score(100, 100, 100), 0)

    def test_chainlink_full_safeguards(self):
        # chainlink(40) + cb(15) + msb(15) = 70 → 100-70=30
        s = compute_manipulation_risk_score(40, 15, 15)
        self.assertEqual(s, 30)

    def test_custom_no_safeguards(self):
        # custom(0) + no cb(0) + single source(0) = 0 → 100
        s = compute_manipulation_risk_score(0, 0, 0)
        self.assertEqual(s, 100)

    def test_single_dex_no_safeguards(self):
        # single_dex(5) + 0 + 0 → 95
        self.assertEqual(compute_manipulation_risk_score(5, 0, 0), 95)

    def test_return_type_int(self):
        self.assertIsInstance(compute_manipulation_risk_score(20, 5, 10), int)

    def test_symmetric_bonuses(self):
        # 40 + 15 + 10 = 65, → 35
        self.assertEqual(compute_manipulation_risk_score(40, 15, 10), 35)


# ===========================================================================
# 7. risk_label
# ===========================================================================

class TestRiskLabel(unittest.TestCase):

    def test_score_0_is_negligible(self):
        self.assertEqual(risk_label(0), "NEGLIGIBLE_ORACLE_RISK")

    def test_score_10_is_negligible(self):
        self.assertEqual(risk_label(10), "NEGLIGIBLE_ORACLE_RISK")

    def test_score_11_is_low(self):
        self.assertEqual(risk_label(11), "LOW_ORACLE_RISK")

    def test_score_30_is_low(self):
        self.assertEqual(risk_label(30), "LOW_ORACLE_RISK")

    def test_score_31_is_moderate(self):
        self.assertEqual(risk_label(31), "MODERATE_ORACLE_RISK")

    def test_score_55_is_moderate(self):
        self.assertEqual(risk_label(55), "MODERATE_ORACLE_RISK")

    def test_score_56_is_high(self):
        self.assertEqual(risk_label(56), "HIGH_ORACLE_RISK")

    def test_score_75_is_high(self):
        self.assertEqual(risk_label(75), "HIGH_ORACLE_RISK")

    def test_score_76_is_critical(self):
        self.assertEqual(risk_label(76), "CRITICAL_ORACLE_RISK")

    def test_score_100_is_critical(self):
        self.assertEqual(risk_label(100), "CRITICAL_ORACLE_RISK")

    def test_all_five_labels_exist(self):
        expected = {
            "NEGLIGIBLE_ORACLE_RISK",
            "LOW_ORACLE_RISK",
            "MODERATE_ORACLE_RISK",
            "HIGH_ORACLE_RISK",
            "CRITICAL_ORACLE_RISK",
        }
        actual = {risk_label(s) for s in [5, 20, 45, 65, 90]}
        self.assertEqual(actual, expected)

    def test_returns_string(self):
        self.assertIsInstance(risk_label(50), str)


# ===========================================================================
# 8. DeFiProtocolOracleManipulationRiskScorer.score() — keys and types
# ===========================================================================

class TestScorerScoreKeys(unittest.TestCase):

    def setUp(self):
        self.scorer = _default_scorer()

    def _safe_result(self):
        return _score(self.scorer)

    def test_returns_dict(self):
        self.assertIsInstance(self._safe_result(), dict)

    def test_key_oracle_source_score(self):
        self.assertIn("oracle_source_score", self._safe_result())

    def test_key_manipulation_cost_ratio(self):
        self.assertIn("manipulation_cost_ratio", self._safe_result())

    def test_key_tvl_at_risk_ratio(self):
        self.assertIn("tvl_at_risk_ratio", self._safe_result())

    def test_key_circuit_breaker_bonus(self):
        self.assertIn("circuit_breaker_bonus", self._safe_result())

    def test_key_multi_source_bonus(self):
        self.assertIn("multi_source_bonus", self._safe_result())

    def test_key_manipulation_risk_score(self):
        self.assertIn("manipulation_risk_score", self._safe_result())

    def test_key_risk_label(self):
        self.assertIn("risk_label", self._safe_result())

    def test_key_protocol_name(self):
        self.assertIn("protocol_name", self._safe_result())

    def test_oracle_source_score_is_int(self):
        r = self._safe_result()
        self.assertIsInstance(r["oracle_source_score"], int)

    def test_manipulation_risk_score_is_int(self):
        r = self._safe_result()
        self.assertIsInstance(r["manipulation_risk_score"], int)

    def test_risk_label_is_str(self):
        r = self._safe_result()
        self.assertIsInstance(r["risk_label"], str)

    def test_manipulation_cost_ratio_is_float(self):
        r = self._safe_result()
        self.assertIsInstance(r["manipulation_cost_ratio"], float)

    def test_tvl_at_risk_ratio_is_float(self):
        r = self._safe_result()
        self.assertIsInstance(r["tvl_at_risk_ratio"], float)

    def test_schema_version_key(self):
        self.assertIn("schema_version", self._safe_result())

    def test_module_tag_key(self):
        self.assertIn("module", self._safe_result())

    def test_timestamp_key(self):
        self.assertIn("timestamp", self._safe_result())

    def test_inputs_key(self):
        self.assertIn("inputs", self._safe_result())


# ===========================================================================
# 9. DeFiProtocolOracleManipulationRiskScorer.score() — values
# ===========================================================================

class TestScorerScoreValues(unittest.TestCase):

    def setUp(self):
        self.scorer = _default_scorer()

    def test_chainlink_oracle_source_score(self):
        r = _score(self.scorer, oracle_type="chainlink")
        self.assertEqual(r["oracle_source_score"], 40)

    def test_single_dex_oracle_source_score(self):
        r = _score(self.scorer, oracle_type="single_dex")
        self.assertEqual(r["oracle_source_score"], 5)

    def test_custom_oracle_source_score(self):
        r = _score(self.scorer, oracle_type="custom")
        self.assertEqual(r["oracle_source_score"], 0)

    def test_circuit_breaker_bonus_when_true(self):
        r = _score(self.scorer, has_circuit_breaker=True)
        self.assertEqual(r["circuit_breaker_bonus"], 15)

    def test_circuit_breaker_bonus_when_false(self):
        r = _score(self.scorer, has_circuit_breaker=False)
        self.assertEqual(r["circuit_breaker_bonus"], 0)

    def test_multi_source_bonus_four_sources(self):
        r = _score(self.scorer, num_oracle_sources=4)
        self.assertEqual(r["multi_source_bonus"], 15)

    def test_multi_source_bonus_one_source(self):
        r = _score(self.scorer, num_oracle_sources=1)
        self.assertEqual(r["multi_source_bonus"], 0)

    def test_tvl_at_risk_ratio_single_source(self):
        r = _score(
            self.scorer,
            num_oracle_sources=1,
            protocol_tvl_usd=10_000_000.0,
            oracle_pool_liquidity_usd=2_000_000.0,
        )
        self.assertAlmostEqual(r["tvl_at_risk_ratio"], 5.0)

    def test_tvl_at_risk_ratio_multi_source_zero(self):
        r = _score(self.scorer, num_oracle_sources=3)
        self.assertEqual(r["tvl_at_risk_ratio"], 0.0)

    def test_manipulation_risk_score_chainlink_all_safeguards(self):
        # chainlink(40) + cb(15) + msb max(15) = 70 → 30
        r = _score(
            self.scorer,
            oracle_type="chainlink",
            has_circuit_breaker=True,
            num_oracle_sources=4,
        )
        self.assertEqual(r["manipulation_risk_score"], 30)

    def test_manipulation_risk_score_custom_no_safeguards(self):
        # custom(0) + no cb(0) + single source(0) = 0 → 100
        r = _score(
            self.scorer,
            oracle_type="custom",
            has_circuit_breaker=False,
            num_oracle_sources=1,
        )
        self.assertEqual(r["manipulation_risk_score"], 100)

    def test_risk_score_clamped_to_0(self):
        r = _score(
            self.scorer,
            oracle_type="chainlink",
            has_circuit_breaker=True,
            num_oracle_sources=100,
        )
        self.assertGreaterEqual(r["manipulation_risk_score"], 0)

    def test_risk_score_clamped_to_100(self):
        r = _score(
            self.scorer,
            oracle_type="custom",
            has_circuit_breaker=False,
            num_oracle_sources=1,
        )
        self.assertLessEqual(r["manipulation_risk_score"], 100)

    def test_protocol_name_preserved(self):
        r = _score(self.scorer, protocol_name="MyProtocol")
        self.assertEqual(r["protocol_name"], "MyProtocol")

    def test_pyth_risk_score(self):
        # pyth(35) + no cb(0) + 1 source(0) → 65
        r = _score(
            self.scorer,
            oracle_type="pyth",
            has_circuit_breaker=False,
            num_oracle_sources=1,
        )
        self.assertEqual(r["manipulation_risk_score"], 65)

    def test_twap_uniswap_with_cb_and_two_sources(self):
        # twap_uniswap(20) + cb(15) + 1 extra source(5) → 100-40=60
        r = _score(
            self.scorer,
            oracle_type="twap_uniswap",
            has_circuit_breaker=True,
            num_oracle_sources=2,
        )
        self.assertEqual(r["manipulation_risk_score"], 60)

    def test_band_oracle_source_score(self):
        r = _score(self.scorer, oracle_type="band")
        self.assertEqual(r["oracle_source_score"], 20)

    def test_twap_curve_oracle_source_score(self):
        r = _score(self.scorer, oracle_type="twap_curve")
        self.assertEqual(r["oracle_source_score"], 25)

    def test_inputs_stored_in_result(self):
        r = _score(self.scorer, oracle_type="pyth", twap_period_minutes=10)
        self.assertEqual(r["inputs"]["oracle_type"], "pyth")
        self.assertEqual(r["inputs"]["twap_period_minutes"], 10)

    def test_risk_label_matches_score(self):
        r = _score(
            self.scorer,
            oracle_type="custom",
            has_circuit_breaker=False,
            num_oracle_sources=1,
        )
        self.assertEqual(r["risk_label"], risk_label(r["manipulation_risk_score"]))


# ===========================================================================
# 10. score_and_log + ring-buffer
# ===========================================================================

class TestScorerLogAndRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _default_scorer(self.tmp)

    def _log_path(self):
        return _resolve_log_path(self.tmp)

    def test_log_file_created(self):
        self.scorer.score_and_log(
            oracle_type="chainlink", twap_period_minutes=0,
            oracle_pool_liquidity_usd=0.0, protocol_tvl_usd=1e7,
            max_flash_loan_available_usd=5e8, num_oracle_sources=5,
            has_circuit_breaker=True, protocol_name="LogTest",
        )
        self.assertTrue(os.path.exists(self._log_path()))

    def test_log_is_list(self):
        self.scorer.score_and_log(
            oracle_type="chainlink", twap_period_minutes=0,
            oracle_pool_liquidity_usd=0.0, protocol_tvl_usd=1e7,
            max_flash_loan_available_usd=5e8, num_oracle_sources=5,
            has_circuit_breaker=True, protocol_name="LogTest",
        )
        entries = _load_log(self._log_path())
        self.assertIsInstance(entries, list)

    def test_log_appends(self):
        for i in range(3):
            self.scorer.score_and_log(
                oracle_type="chainlink", twap_period_minutes=0,
                oracle_pool_liquidity_usd=0.0, protocol_tvl_usd=1e7,
                max_flash_loan_available_usd=5e8, num_oracle_sources=5,
                has_circuit_breaker=True, protocol_name=f"Proto{i}",
            )
        entries = _load_log(self._log_path())
        self.assertEqual(len(entries), 3)

    def test_ring_buffer_cap(self):
        for i in range(LOG_MAX_ENTRIES + 10):
            self.scorer.score_and_log(
                oracle_type="custom", twap_period_minutes=0,
                oracle_pool_liquidity_usd=0.0, protocol_tvl_usd=1e6,
                max_flash_loan_available_usd=1e8, num_oracle_sources=1,
                has_circuit_breaker=False, protocol_name=f"P{i}",
            )
        entries = _load_log(self._log_path())
        self.assertLessEqual(len(entries), LOG_MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        for i in range(LOG_MAX_ENTRIES + 5):
            self.scorer.score_and_log(
                oracle_type="custom", twap_period_minutes=0,
                oracle_pool_liquidity_usd=0.0, protocol_tvl_usd=1e6,
                max_flash_loan_available_usd=1e8, num_oracle_sources=1,
                has_circuit_breaker=False, protocol_name=f"P{i}",
            )
        entries = _load_log(self._log_path())
        # Last entry should be the last scored protocol
        self.assertEqual(entries[-1]["protocol_name"], f"P{LOG_MAX_ENTRIES + 4}")

    def test_log_entry_has_risk_label(self):
        self.scorer.score_and_log(
            oracle_type="single_dex", twap_period_minutes=0,
            oracle_pool_liquidity_usd=0.0, protocol_tvl_usd=1e6,
            max_flash_loan_available_usd=1e8, num_oracle_sources=1,
            has_circuit_breaker=False, protocol_name="RiskyP",
        )
        entries = _load_log(self._log_path())
        self.assertIn("risk_label", entries[-1])

    def test_score_and_log_returns_same_as_score(self):
        r1 = self.scorer.score(
            oracle_type="chainlink", twap_period_minutes=0,
            oracle_pool_liquidity_usd=0.0, protocol_tvl_usd=1e7,
            max_flash_loan_available_usd=5e8, num_oracle_sources=5,
            has_circuit_breaker=True, protocol_name="Compare",
        )
        r2 = self.scorer.score_and_log(
            oracle_type="chainlink", twap_period_minutes=0,
            oracle_pool_liquidity_usd=0.0, protocol_tvl_usd=1e7,
            max_flash_loan_available_usd=5e8, num_oracle_sources=5,
            has_circuit_breaker=True, protocol_name="Compare",
        )
        # Same keys and risk scores (timestamps may differ slightly)
        self.assertEqual(r1["manipulation_risk_score"], r2["manipulation_risk_score"])
        self.assertEqual(r1["risk_label"], r2["risk_label"])


# ===========================================================================
# 11. _atomic_write / _load_log / _append_log
# ===========================================================================

class TestAtomicWriteAndLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "test_log.json")

    def test_atomic_write_creates_file(self):
        _atomic_write(self.log_path, [{"key": "value"}])
        self.assertTrue(os.path.exists(self.log_path))

    def test_atomic_write_content_valid_json(self):
        data = [{"a": 1}, {"b": 2}]
        _atomic_write(self.log_path, data)
        with open(self.log_path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_load_log_missing_file_returns_empty(self):
        entries = _load_log("/nonexistent/path/log.json")
        self.assertEqual(entries, [])

    def test_load_log_corrupt_file_returns_empty(self):
        with open(self.log_path, "w") as f:
            f.write("not json{{")
        entries = _load_log(self.log_path)
        self.assertEqual(entries, [])

    def test_append_log_basic(self):
        _append_log(self.log_path, {"x": 1})
        entries = _load_log(self.log_path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["x"], 1)

    def test_append_log_multiple(self):
        for i in range(5):
            _append_log(self.log_path, {"idx": i})
        entries = _load_log(self.log_path)
        self.assertEqual(len(entries), 5)

    def test_append_log_ring_buffer_cap(self):
        for i in range(120):
            _append_log(self.log_path, {"idx": i})
        entries = _load_log(self.log_path)
        self.assertLessEqual(len(entries), LOG_MAX_ENTRIES)

    def test_append_log_no_tmp_files_left(self):
        _append_log(self.log_path, {"x": 1})
        tmp_files = [f for f in os.listdir(self.tmp) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])


# ===========================================================================
# 12. score_batch()
# ===========================================================================

class TestScorerBatch(unittest.TestCase):

    def setUp(self):
        self.scorer = _default_scorer()

    def test_batch_returns_list(self):
        result = self.scorer.score_batch([])
        self.assertIsInstance(result, list)

    def test_batch_empty_input(self):
        result = self.scorer.score_batch([])
        self.assertEqual(result, [])

    def test_batch_single_protocol(self):
        result = self.scorer.score_batch([{
            "oracle_type": "chainlink", "twap_period_minutes": 0,
            "oracle_pool_liquidity_usd": 0.0, "protocol_tvl_usd": 1e7,
            "max_flash_loan_available_usd": 5e8, "num_oracle_sources": 5,
            "has_circuit_breaker": True, "protocol_name": "BatchP",
        }])
        self.assertEqual(len(result), 1)

    def test_batch_multiple_protocols(self):
        protos = [
            {"oracle_type": "chainlink", "protocol_name": "P1"},
            {"oracle_type": "custom", "protocol_name": "P2"},
            {"oracle_type": "single_dex", "protocol_name": "P3"},
        ]
        result = self.scorer.score_batch(protos)
        self.assertEqual(len(result), 3)

    def test_batch_names_preserved(self):
        protos = [
            {"oracle_type": "chainlink", "protocol_name": "Alpha"},
            {"oracle_type": "pyth", "protocol_name": "Beta"},
        ]
        result = self.scorer.score_batch(protos)
        names = [r["protocol_name"] for r in result]
        self.assertIn("Alpha", names)
        self.assertIn("Beta", names)

    def test_batch_different_scores(self):
        protos = [
            {"oracle_type": "chainlink", "has_circuit_breaker": True,
             "num_oracle_sources": 4, "protocol_name": "Safe"},
            {"oracle_type": "custom", "has_circuit_breaker": False,
             "num_oracle_sources": 1, "protocol_name": "Risky"},
        ]
        result = self.scorer.score_batch(protos)
        safe = next(r for r in result if r["protocol_name"] == "Safe")
        risky = next(r for r in result if r["protocol_name"] == "Risky")
        self.assertLess(safe["manipulation_risk_score"], risky["manipulation_risk_score"])


# ===========================================================================
# 13. _iso_now
# ===========================================================================

class TestIsoNow(unittest.TestCase):

    def test_format(self):
        s = _iso_now()
        self.assertRegex(s, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_returns_string(self):
        self.assertIsInstance(_iso_now(), str)

    def test_length(self):
        self.assertEqual(len(_iso_now()), 20)


# ===========================================================================
# 14. run() module function
# ===========================================================================

class TestRunFunction(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_run_returns_list(self):
        results = run(data_dir=self.tmp)
        self.assertIsInstance(results, list)

    def test_run_returns_non_empty(self):
        results = run(data_dir=self.tmp)
        self.assertGreater(len(results), 0)

    def test_run_creates_log_file(self):
        run(data_dir=self.tmp)
        log_path = _resolve_log_path(self.tmp)
        self.assertTrue(os.path.exists(log_path))

    def test_run_all_results_have_risk_label(self):
        results = run(data_dir=self.tmp)
        for r in results:
            self.assertIn("risk_label", r)

    def test_run_all_results_have_protocol_name(self):
        results = run(data_dir=self.tmp)
        for r in results:
            self.assertIn("protocol_name", r)
            self.assertNotEqual(r["protocol_name"], "")

    def test_run_scores_in_range(self):
        results = run(data_dir=self.tmp)
        for r in results:
            self.assertGreaterEqual(r["manipulation_risk_score"], 0)
            self.assertLessEqual(r["manipulation_risk_score"], 100)


# ===========================================================================
# 15. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.scorer = _default_scorer()

    def test_very_large_tvl(self):
        r = _score(self.scorer, protocol_tvl_usd=1e15)
        self.assertIn("manipulation_risk_score", r)

    def test_very_small_liquidity(self):
        r = _score(
            self.scorer,
            oracle_pool_liquidity_usd=0.01,
            num_oracle_sources=1,
            protocol_tvl_usd=1_000_000.0,
        )
        self.assertGreater(r["tvl_at_risk_ratio"], 0)

    def test_empty_protocol_name(self):
        r = _score(self.scorer, protocol_name="")
        self.assertEqual(r["protocol_name"], "")

    def test_zero_num_sources(self):
        r = _score(self.scorer, num_oracle_sources=0)
        self.assertEqual(r["multi_source_bonus"], 0)

    def test_large_num_sources_capped(self):
        r = _score(self.scorer, num_oracle_sources=1000)
        self.assertEqual(r["multi_source_bonus"], 15)

    def test_zero_flash_loan(self):
        r = _score(self.scorer, max_flash_loan_available_usd=0.0)
        self.assertEqual(r["manipulation_cost_ratio"], 0.0)

    def test_twap_period_stored_in_inputs(self):
        r = _score(self.scorer, twap_period_minutes=30)
        self.assertEqual(r["inputs"]["twap_period_minutes"], 30)

    def test_manipulation_risk_score_never_negative(self):
        for oracle_type in ORACLE_SOURCE_SCORES:
            r = _score(
                self.scorer,
                oracle_type=oracle_type,
                has_circuit_breaker=True,
                num_oracle_sources=10,
            )
            self.assertGreaterEqual(r["manipulation_risk_score"], 0)

    def test_manipulation_risk_score_never_above_100(self):
        r = _score(
            self.scorer,
            oracle_type="custom",
            has_circuit_breaker=False,
            num_oracle_sources=0,
        )
        self.assertLessEqual(r["manipulation_risk_score"], 100)

    def test_multiple_calls_independent(self):
        r1 = _score(self.scorer, oracle_type="chainlink", protocol_name="A")
        r2 = _score(self.scorer, oracle_type="custom", protocol_name="B")
        self.assertNotEqual(r1["oracle_source_score"], r2["oracle_source_score"])
        self.assertNotEqual(r1["protocol_name"], r2["protocol_name"])

    def test_has_circuit_breaker_false_lower_score(self):
        r_cb = _score(self.scorer, has_circuit_breaker=True)
        r_no_cb = _score(self.scorer, has_circuit_breaker=False)
        self.assertGreater(r_no_cb["manipulation_risk_score"], r_cb["manipulation_risk_score"])

    def test_more_oracle_sources_lower_risk(self):
        r1 = _score(self.scorer, num_oracle_sources=1)
        r4 = _score(self.scorer, num_oracle_sources=4)
        self.assertGreater(r1["manipulation_risk_score"], r4["manipulation_risk_score"])


# ===========================================================================
# 16. Scenario integration tests
# ===========================================================================

class TestScenarios(unittest.TestCase):

    def setUp(self):
        self.scorer = _default_scorer()

    def test_aave_scenario_low_risk(self):
        # Aave: chainlink, multisource, circuit breaker
        r = self.scorer.score(
            oracle_type="chainlink",
            twap_period_minutes=0,
            oracle_pool_liquidity_usd=0.0,
            protocol_tvl_usd=5_000_000_000.0,
            max_flash_loan_available_usd=2_000_000_000.0,
            num_oracle_sources=10,
            has_circuit_breaker=True,
            protocol_name="Aave V3",
        )
        self.assertLessEqual(r["manipulation_risk_score"], 55)

    def test_risky_single_dex_scenario(self):
        r = self.scorer.score(
            oracle_type="single_dex",
            twap_period_minutes=0,
            oracle_pool_liquidity_usd=100_000.0,
            protocol_tvl_usd=20_000_000.0,
            max_flash_loan_available_usd=100_000_000.0,
            num_oracle_sources=1,
            has_circuit_breaker=False,
            protocol_name="RiskyDex",
        )
        self.assertGreaterEqual(r["manipulation_risk_score"], 75)

    def test_critical_custom_oracle(self):
        r = self.scorer.score(
            oracle_type="custom",
            twap_period_minutes=5,
            oracle_pool_liquidity_usd=50_000.0,
            protocol_tvl_usd=10_000_000.0,
            max_flash_loan_available_usd=300_000_000.0,
            num_oracle_sources=1,
            has_circuit_breaker=False,
            protocol_name="CustomRisk",
        )
        self.assertEqual(r["risk_label"], "CRITICAL_ORACLE_RISK")

    def test_pyth_with_cb_moderate_risk(self):
        r = self.scorer.score(
            oracle_type="pyth",
            twap_period_minutes=0,
            oracle_pool_liquidity_usd=0.0,
            protocol_tvl_usd=500_000_000.0,
            max_flash_loan_available_usd=1_000_000_000.0,
            num_oracle_sources=3,
            has_circuit_breaker=True,
            protocol_name="PythProto",
        )
        # pyth(35) + cb(15) + 2 extras(10) → 100-60=40 → MODERATE
        self.assertEqual(r["manipulation_risk_score"], 40)
        self.assertEqual(r["risk_label"], "MODERATE_ORACLE_RISK")

    def test_band_no_cb_single_source(self):
        r = self.scorer.score(
            oracle_type="band",
            twap_period_minutes=0,
            oracle_pool_liquidity_usd=0.0,
            protocol_tvl_usd=100_000_000.0,
            max_flash_loan_available_usd=500_000_000.0,
            num_oracle_sources=1,
            has_circuit_breaker=False,
            protocol_name="BandProto",
        )
        # band(20) + 0 + 0 → 80 → CRITICAL
        self.assertEqual(r["manipulation_risk_score"], 80)
        self.assertEqual(r["risk_label"], "CRITICAL_ORACLE_RISK")


if __name__ == "__main__":
    unittest.main(verbosity=2)
