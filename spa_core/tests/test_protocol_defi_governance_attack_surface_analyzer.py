"""
Tests for MP-1125 ProtocolDeFiGovernanceAttackSurfaceAnalyzer.
Run: python3 -m unittest spa_core.tests.test_protocol_defi_governance_attack_surface_analyzer -v

Coverage targets (≥110 test methods):
  - compute_tokens_to_attack_pct      (various quorum values)
  - compute_attack_cost_usd           (formula, zero supply, zero price)
  - compute_attack_cost_to_tvl_ratio  (normal, zero tvl)
  - compute_concentration_risk_score  (all 5 tiers + boundary values)
  - compute_timelock_safety_score     (all 5 tiers + boundary values)
  - compute_low_timelock_penalty      (inverse of safety score)
  - compute_low_quorum_penalty        (all 4 tiers + boundaries)
  - compute_governance_attack_score   (formula, clamping)
  - governance_label                  (all 5 labels + boundaries)
  - ProtocolDeFiGovernanceAttackSurfaceAnalyzer.analyze() (keys, types, values)
  - analyze_and_log() / ring-buffer / atomic write
  - analyze_batch()
  - run() module function
  - Edge cases (zero supply, zero price, large values)
  - Scenario integration tests
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

from spa_core.analytics.protocol_defi_governance_attack_surface_analyzer import (
    ProtocolDeFiGovernanceAttackSurfaceAnalyzer,
    compute_tokens_to_attack_pct,
    compute_attack_cost_usd,
    compute_attack_cost_to_tvl_ratio,
    compute_concentration_risk_score,
    compute_timelock_safety_score,
    compute_low_timelock_penalty,
    compute_low_quorum_penalty,
    compute_governance_attack_score,
    governance_label,
    _atomic_write,
    _load_log,
    _append_log,
    _iso_now,
    _resolve_log_path,
    run,
    LOG_MAX_ENTRIES,
    TIMELOCK_MAX_SAFETY_SCORE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_analyzer(tmp_dir=None):
    return ProtocolDeFiGovernanceAttackSurfaceAnalyzer(data_dir=tmp_dir)


def _analyze(analyzer, **kwargs):
    defaults = dict(
        total_token_supply=1_000_000_000.0,
        top_10_holders_pct=30.0,
        quorum_threshold_pct=10.0,
        timelock_hours=48.0,
        vote_duration_hours=72.0,
        has_multisig_override=True,
        token_price_usd=2.50,
        protocol_tvl_usd=500_000_000.0,
        protocol_name="TestDAO",
    )
    defaults.update(kwargs)
    return analyzer.analyze(**defaults)


# ===========================================================================
# 1. compute_tokens_to_attack_pct
# ===========================================================================

class TestComputeTokensToAttackPct(unittest.TestCase):

    def test_standard_quorum_4(self):
        # 4.0 / 2 + 0.01 = 2.01
        self.assertAlmostEqual(compute_tokens_to_attack_pct(4.0), 2.01)

    def test_quorum_10(self):
        # 10.0 / 2 + 0.01 = 5.01
        self.assertAlmostEqual(compute_tokens_to_attack_pct(10.0), 5.01)

    def test_quorum_20(self):
        self.assertAlmostEqual(compute_tokens_to_attack_pct(20.0), 10.01)

    def test_quorum_zero(self):
        self.assertAlmostEqual(compute_tokens_to_attack_pct(0.0), 0.01)

    def test_quorum_100(self):
        self.assertAlmostEqual(compute_tokens_to_attack_pct(100.0), 50.01)

    def test_quorum_1(self):
        self.assertAlmostEqual(compute_tokens_to_attack_pct(1.0), 0.51)

    def test_always_greater_than_half_quorum(self):
        for q in [1.0, 4.0, 10.0, 20.0, 50.0]:
            tta = compute_tokens_to_attack_pct(q)
            self.assertGreater(tta, q / 2.0)

    def test_returns_float(self):
        self.assertIsInstance(compute_tokens_to_attack_pct(5.0), float)

    def test_positive_for_positive_quorum(self):
        self.assertGreater(compute_tokens_to_attack_pct(4.0), 0.0)


# ===========================================================================
# 2. compute_attack_cost_usd
# ===========================================================================

class TestComputeAttackCostUsd(unittest.TestCase):

    def test_basic_formula(self):
        # 10 / 100 * 1_000_000 * 1.0 = 100_000
        cost = compute_attack_cost_usd(10.0, 1_000_000.0, 1.0)
        self.assertAlmostEqual(cost, 100_000.0)

    def test_zero_supply(self):
        cost = compute_attack_cost_usd(5.0, 0.0, 2.0)
        self.assertAlmostEqual(cost, 0.0)

    def test_zero_price(self):
        cost = compute_attack_cost_usd(5.0, 1_000_000.0, 0.0)
        self.assertAlmostEqual(cost, 0.0)

    def test_zero_pct(self):
        cost = compute_attack_cost_usd(0.0, 1_000_000.0, 5.0)
        self.assertAlmostEqual(cost, 0.0)

    def test_large_supply_and_price(self):
        cost = compute_attack_cost_usd(2.01, 10_000_000_000.0, 10.0)
        expected = (2.01 / 100.0) * 10_000_000_000.0 * 10.0
        self.assertAlmostEqual(cost, expected, places=0)

    def test_returns_float(self):
        self.assertIsInstance(compute_attack_cost_usd(5.0, 1e8, 1.0), float)

    def test_scales_linearly_with_price(self):
        c1 = compute_attack_cost_usd(5.0, 1_000_000.0, 1.0)
        c2 = compute_attack_cost_usd(5.0, 1_000_000.0, 2.0)
        self.assertAlmostEqual(c2, c1 * 2.0)

    def test_scales_linearly_with_supply(self):
        c1 = compute_attack_cost_usd(5.0, 1_000_000.0, 1.0)
        c2 = compute_attack_cost_usd(5.0, 2_000_000.0, 1.0)
        self.assertAlmostEqual(c2, c1 * 2.0)


# ===========================================================================
# 3. compute_attack_cost_to_tvl_ratio
# ===========================================================================

class TestComputeAttackCostToTvlRatio(unittest.TestCase):

    def test_normal_ratio(self):
        r = compute_attack_cost_to_tvl_ratio(10_000_000.0, 100_000_000.0)
        self.assertAlmostEqual(r, 0.1)

    def test_cost_equals_tvl(self):
        r = compute_attack_cost_to_tvl_ratio(5_000_000.0, 5_000_000.0)
        self.assertAlmostEqual(r, 1.0)

    def test_zero_tvl_returns_zero(self):
        r = compute_attack_cost_to_tvl_ratio(1_000_000.0, 0.0)
        self.assertEqual(r, 0.0)

    def test_negative_tvl_returns_zero(self):
        r = compute_attack_cost_to_tvl_ratio(1_000_000.0, -1.0)
        self.assertEqual(r, 0.0)

    def test_zero_cost(self):
        r = compute_attack_cost_to_tvl_ratio(0.0, 100_000_000.0)
        self.assertAlmostEqual(r, 0.0)

    def test_ratio_greater_than_one_when_attack_costly(self):
        # attack costs more than TVL
        r = compute_attack_cost_to_tvl_ratio(200_000_000.0, 100_000_000.0)
        self.assertGreater(r, 1.0)

    def test_returns_float(self):
        self.assertIsInstance(compute_attack_cost_to_tvl_ratio(1e6, 1e7), float)


# ===========================================================================
# 4. compute_concentration_risk_score
# ===========================================================================

class TestComputeConcentrationRiskScore(unittest.TestCase):

    def test_above_66_gives_40(self):
        self.assertEqual(compute_concentration_risk_score(70.0), 40)

    def test_exactly_66_gives_30(self):
        # >66 → 40, exactly 66 → next tier
        self.assertEqual(compute_concentration_risk_score(66.0), 30)

    def test_just_above_66_gives_40(self):
        self.assertEqual(compute_concentration_risk_score(66.1), 40)

    def test_above_50_gives_30(self):
        self.assertEqual(compute_concentration_risk_score(60.0), 30)

    def test_exactly_50_gives_20(self):
        self.assertEqual(compute_concentration_risk_score(50.0), 20)

    def test_just_above_50_gives_30(self):
        self.assertEqual(compute_concentration_risk_score(50.1), 30)

    def test_above_33_gives_20(self):
        self.assertEqual(compute_concentration_risk_score(40.0), 20)

    def test_exactly_33_gives_10(self):
        self.assertEqual(compute_concentration_risk_score(33.0), 10)

    def test_just_above_33_gives_20(self):
        self.assertEqual(compute_concentration_risk_score(33.1), 20)

    def test_above_20_gives_10(self):
        self.assertEqual(compute_concentration_risk_score(25.0), 10)

    def test_exactly_20_gives_0(self):
        self.assertEqual(compute_concentration_risk_score(20.0), 0)

    def test_below_20_gives_0(self):
        self.assertEqual(compute_concentration_risk_score(10.0), 0)

    def test_zero_concentration_gives_0(self):
        self.assertEqual(compute_concentration_risk_score(0.0), 0)

    def test_100_percent_gives_40(self):
        self.assertEqual(compute_concentration_risk_score(100.0), 40)

    def test_returns_int(self):
        self.assertIsInstance(compute_concentration_risk_score(50.0), int)


# ===========================================================================
# 5. compute_timelock_safety_score
# ===========================================================================

class TestComputeTimelockSafetyScore(unittest.TestCase):

    def test_168_hours_gives_30(self):
        self.assertEqual(compute_timelock_safety_score(168.0), 30)

    def test_above_168_gives_30(self):
        self.assertEqual(compute_timelock_safety_score(200.0), 30)

    def test_just_below_168_gives_20(self):
        self.assertEqual(compute_timelock_safety_score(167.9), 20)

    def test_72_hours_gives_20(self):
        self.assertEqual(compute_timelock_safety_score(72.0), 20)

    def test_between_72_and_168_gives_20(self):
        self.assertEqual(compute_timelock_safety_score(100.0), 20)

    def test_just_below_72_gives_10(self):
        self.assertEqual(compute_timelock_safety_score(71.9), 10)

    def test_24_hours_gives_10(self):
        self.assertEqual(compute_timelock_safety_score(24.0), 10)

    def test_between_24_and_72_gives_10(self):
        self.assertEqual(compute_timelock_safety_score(48.0), 10)

    def test_just_below_24_gives_5(self):
        self.assertEqual(compute_timelock_safety_score(23.9), 5)

    def test_6_hours_gives_5(self):
        self.assertEqual(compute_timelock_safety_score(6.0), 5)

    def test_between_6_and_24_gives_5(self):
        self.assertEqual(compute_timelock_safety_score(12.0), 5)

    def test_below_6_gives_0(self):
        self.assertEqual(compute_timelock_safety_score(5.9), 0)

    def test_zero_gives_0(self):
        self.assertEqual(compute_timelock_safety_score(0.0), 0)

    def test_returns_int(self):
        self.assertIsInstance(compute_timelock_safety_score(48.0), int)

    def test_week_is_max_score(self):
        self.assertEqual(compute_timelock_safety_score(168.0), TIMELOCK_MAX_SAFETY_SCORE)


# ===========================================================================
# 6. compute_low_timelock_penalty
# ===========================================================================

class TestComputeLowTimelockPenalty(unittest.TestCase):

    def test_max_safety_gives_zero_penalty(self):
        self.assertEqual(compute_low_timelock_penalty(30), 0)

    def test_zero_safety_gives_max_penalty(self):
        self.assertEqual(compute_low_timelock_penalty(0), 30)

    def test_mid_safety_gives_mid_penalty(self):
        self.assertEqual(compute_low_timelock_penalty(15), 15)

    def test_safety_20_gives_penalty_10(self):
        self.assertEqual(compute_low_timelock_penalty(20), 10)

    def test_safety_10_gives_penalty_20(self):
        self.assertEqual(compute_low_timelock_penalty(10), 20)

    def test_penalty_plus_safety_equals_max(self):
        for s in [0, 5, 10, 20, 30]:
            self.assertEqual(compute_low_timelock_penalty(s) + s, TIMELOCK_MAX_SAFETY_SCORE)

    def test_returns_int(self):
        self.assertIsInstance(compute_low_timelock_penalty(10), int)


# ===========================================================================
# 7. compute_low_quorum_penalty
# ===========================================================================

class TestComputeLowQuorumPenalty(unittest.TestCase):

    def test_below_2_gives_30(self):
        self.assertEqual(compute_low_quorum_penalty(1.0), 30)

    def test_just_below_2_gives_30(self):
        self.assertEqual(compute_low_quorum_penalty(1.99), 30)

    def test_exactly_2_gives_20(self):
        # 2.0 is NOT < 2.0, so next tier: <5.0 → 20
        self.assertEqual(compute_low_quorum_penalty(2.0), 20)

    def test_between_2_and_5_gives_20(self):
        self.assertEqual(compute_low_quorum_penalty(3.0), 20)

    def test_just_below_5_gives_20(self):
        self.assertEqual(compute_low_quorum_penalty(4.99), 20)

    def test_exactly_5_gives_10(self):
        self.assertEqual(compute_low_quorum_penalty(5.0), 10)

    def test_between_5_and_15_gives_10(self):
        self.assertEqual(compute_low_quorum_penalty(10.0), 10)

    def test_just_below_15_gives_10(self):
        self.assertEqual(compute_low_quorum_penalty(14.99), 10)

    def test_exactly_15_gives_0(self):
        self.assertEqual(compute_low_quorum_penalty(15.0), 0)

    def test_above_15_gives_0(self):
        self.assertEqual(compute_low_quorum_penalty(25.0), 0)

    def test_zero_quorum_gives_30(self):
        self.assertEqual(compute_low_quorum_penalty(0.0), 30)

    def test_returns_int(self):
        self.assertIsInstance(compute_low_quorum_penalty(10.0), int)


# ===========================================================================
# 8. compute_governance_attack_score
# ===========================================================================

class TestComputeGovernanceAttackScore(unittest.TestCase):

    def test_zero_everything_gives_30(self):
        # 0 concentration + 30 timelock penalty (safety=0) + 30 quorum penalty (q<2)
        # quorum 0 → low_quorum_penalty=30
        s = compute_governance_attack_score(0, 0, 0.0)
        self.assertEqual(s, 60)

    def test_max_concentration_no_timelock_low_quorum(self):
        # 40 + 30 + 30 = 100
        s = compute_governance_attack_score(40, 0, 0.0)
        self.assertEqual(s, 100)

    def test_max_timelock_high_quorum(self):
        # 0 + (30-30) + 0 = 0
        s = compute_governance_attack_score(0, 30, 20.0)
        self.assertEqual(s, 0)

    def test_clamped_to_100(self):
        s = compute_governance_attack_score(100, 0, 0.0)
        self.assertLessEqual(s, 100)

    def test_clamped_to_0(self):
        s = compute_governance_attack_score(0, 30, 50.0)
        self.assertGreaterEqual(s, 0)

    def test_formula_basic(self):
        # concentration=20 (top=25%), timelock_safety=10 (24h), quorum=7% → penalty=10
        # 20 + (30-10) + 10 = 60
        conc = compute_concentration_risk_score(25.0)  # 10
        tls = compute_timelock_safety_score(24.0)       # 10
        s = compute_governance_attack_score(conc, tls, 7.0)
        self.assertEqual(s, 10 + 20 + 10)  # 40

    def test_returns_int(self):
        self.assertIsInstance(compute_governance_attack_score(20, 10, 5.0), int)

    def test_higher_concentration_increases_score(self):
        s_low = compute_governance_attack_score(0, 20, 10.0)
        s_high = compute_governance_attack_score(40, 20, 10.0)
        self.assertGreater(s_high, s_low)

    def test_longer_timelock_decreases_score(self):
        s_short = compute_governance_attack_score(20, 0, 10.0)
        s_long = compute_governance_attack_score(20, 30, 10.0)
        self.assertGreater(s_short, s_long)


# ===========================================================================
# 9. governance_label
# ===========================================================================

class TestGovernanceLabel(unittest.TestCase):

    def test_score_0_fortress(self):
        self.assertEqual(governance_label(0), "FORTRESS_GOVERNANCE")

    def test_score_15_fortress(self):
        self.assertEqual(governance_label(15), "FORTRESS_GOVERNANCE")

    def test_score_16_strong(self):
        self.assertEqual(governance_label(16), "STRONG_GOVERNANCE")

    def test_score_35_strong(self):
        self.assertEqual(governance_label(35), "STRONG_GOVERNANCE")

    def test_score_36_adequate(self):
        self.assertEqual(governance_label(36), "ADEQUATE_GOVERNANCE")

    def test_score_55_adequate(self):
        self.assertEqual(governance_label(55), "ADEQUATE_GOVERNANCE")

    def test_score_56_weak(self):
        self.assertEqual(governance_label(56), "WEAK_GOVERNANCE")

    def test_score_75_weak(self):
        self.assertEqual(governance_label(75), "WEAK_GOVERNANCE")

    def test_score_76_exploit_risk(self):
        self.assertEqual(governance_label(76), "GOVERNANCE_EXPLOIT_RISK")

    def test_score_100_exploit_risk(self):
        self.assertEqual(governance_label(100), "GOVERNANCE_EXPLOIT_RISK")

    def test_all_five_labels_reachable(self):
        expected = {
            "FORTRESS_GOVERNANCE",
            "STRONG_GOVERNANCE",
            "ADEQUATE_GOVERNANCE",
            "WEAK_GOVERNANCE",
            "GOVERNANCE_EXPLOIT_RISK",
        }
        actual = {governance_label(s) for s in [5, 25, 45, 65, 90]}
        self.assertEqual(actual, expected)

    def test_returns_string(self):
        self.assertIsInstance(governance_label(50), str)


# ===========================================================================
# 10. ProtocolDeFiGovernanceAttackSurfaceAnalyzer.analyze() — keys and types
# ===========================================================================

class TestAnalyzerKeys(unittest.TestCase):

    def setUp(self):
        self.analyzer = _default_analyzer()

    def _result(self):
        return _analyze(self.analyzer)

    def test_returns_dict(self):
        self.assertIsInstance(self._result(), dict)

    def test_key_tokens_to_attack_pct(self):
        self.assertIn("tokens_to_attack_pct", self._result())

    def test_key_attack_cost_usd(self):
        self.assertIn("attack_cost_usd", self._result())

    def test_key_attack_cost_to_tvl_ratio(self):
        self.assertIn("attack_cost_to_tvl_ratio", self._result())

    def test_key_concentration_risk_score(self):
        self.assertIn("concentration_risk_score", self._result())

    def test_key_timelock_safety_score(self):
        self.assertIn("timelock_safety_score", self._result())

    def test_key_governance_attack_score(self):
        self.assertIn("governance_attack_score", self._result())

    def test_key_governance_label(self):
        self.assertIn("governance_label", self._result())

    def test_key_protocol_name(self):
        self.assertIn("protocol_name", self._result())

    def test_key_schema_version(self):
        self.assertIn("schema_version", self._result())

    def test_key_module_tag(self):
        self.assertIn("module", self._result())

    def test_key_timestamp(self):
        self.assertIn("timestamp", self._result())

    def test_key_inputs(self):
        self.assertIn("inputs", self._result())

    def test_tokens_to_attack_pct_is_float(self):
        self.assertIsInstance(self._result()["tokens_to_attack_pct"], float)

    def test_attack_cost_usd_is_float(self):
        self.assertIsInstance(self._result()["attack_cost_usd"], float)

    def test_concentration_risk_score_is_int(self):
        self.assertIsInstance(self._result()["concentration_risk_score"], int)

    def test_timelock_safety_score_is_int(self):
        self.assertIsInstance(self._result()["timelock_safety_score"], int)

    def test_governance_attack_score_is_int(self):
        self.assertIsInstance(self._result()["governance_attack_score"], int)

    def test_governance_label_is_str(self):
        self.assertIsInstance(self._result()["governance_label"], str)


# ===========================================================================
# 11. ProtocolDeFiGovernanceAttackSurfaceAnalyzer.analyze() — values
# ===========================================================================

class TestAnalyzerValues(unittest.TestCase):

    def setUp(self):
        self.analyzer = _default_analyzer()

    def test_tokens_to_attack_pct_formula(self):
        r = _analyze(self.analyzer, quorum_threshold_pct=10.0)
        self.assertAlmostEqual(r["tokens_to_attack_pct"], 5.01)

    def test_attack_cost_usd_formula(self):
        r = _analyze(
            self.analyzer,
            total_token_supply=1_000_000.0,
            token_price_usd=1.0,
            quorum_threshold_pct=4.0,
        )
        tta = compute_tokens_to_attack_pct(4.0)  # 2.01
        expected = (tta / 100.0) * 1_000_000.0 * 1.0
        self.assertAlmostEqual(r["attack_cost_usd"], expected, places=2)

    def test_attack_cost_to_tvl_ratio(self):
        r = _analyze(
            self.analyzer,
            total_token_supply=1_000_000_000.0,
            token_price_usd=1.0,
            quorum_threshold_pct=4.0,
            protocol_tvl_usd=100_000_000.0,
        )
        self.assertAlmostEqual(
            r["attack_cost_to_tvl_ratio"],
            r["attack_cost_usd"] / 100_000_000.0,
            places=5,
        )

    def test_concentration_risk_score_70_pct(self):
        r = _analyze(self.analyzer, top_10_holders_pct=70.0)
        self.assertEqual(r["concentration_risk_score"], 40)

    def test_concentration_risk_score_25_pct(self):
        r = _analyze(self.analyzer, top_10_holders_pct=25.0)
        self.assertEqual(r["concentration_risk_score"], 10)

    def test_concentration_risk_score_15_pct(self):
        r = _analyze(self.analyzer, top_10_holders_pct=15.0)
        self.assertEqual(r["concentration_risk_score"], 0)

    def test_timelock_safety_score_168h(self):
        r = _analyze(self.analyzer, timelock_hours=168.0)
        self.assertEqual(r["timelock_safety_score"], 30)

    def test_timelock_safety_score_24h(self):
        r = _analyze(self.analyzer, timelock_hours=24.0)
        self.assertEqual(r["timelock_safety_score"], 10)

    def test_timelock_safety_score_0h(self):
        r = _analyze(self.analyzer, timelock_hours=0.0)
        self.assertEqual(r["timelock_safety_score"], 0)

    def test_governance_attack_score_range(self):
        r = _analyze(self.analyzer)
        self.assertGreaterEqual(r["governance_attack_score"], 0)
        self.assertLessEqual(r["governance_attack_score"], 100)

    def test_governance_label_matches_score(self):
        r = _analyze(self.analyzer)
        self.assertEqual(r["governance_label"], governance_label(r["governance_attack_score"]))

    def test_protocol_name_preserved(self):
        r = _analyze(self.analyzer, protocol_name="MyDAO")
        self.assertEqual(r["protocol_name"], "MyDAO")

    def test_inputs_stored(self):
        r = _analyze(self.analyzer, quorum_threshold_pct=8.0, timelock_hours=96.0)
        self.assertAlmostEqual(r["inputs"]["quorum_threshold_pct"], 8.0)
        self.assertAlmostEqual(r["inputs"]["timelock_hours"], 96.0)

    def test_high_concentration_high_attack_score(self):
        r = _analyze(
            self.analyzer,
            top_10_holders_pct=80.0,
            timelock_hours=0.0,
            quorum_threshold_pct=0.5,
        )
        self.assertGreaterEqual(r["governance_attack_score"], 75)

    def test_safe_protocol_low_attack_score(self):
        r = _analyze(
            self.analyzer,
            top_10_holders_pct=10.0,
            timelock_hours=336.0,
            quorum_threshold_pct=30.0,
        )
        self.assertLessEqual(r["governance_attack_score"], 35)

    def test_zero_tvl_ratio_is_zero(self):
        r = _analyze(self.analyzer, protocol_tvl_usd=0.0)
        self.assertEqual(r["attack_cost_to_tvl_ratio"], 0.0)

    def test_multisig_stored_in_inputs(self):
        r = _analyze(self.analyzer, has_multisig_override=True)
        self.assertTrue(r["inputs"]["has_multisig_override"])

    def test_vote_duration_stored_in_inputs(self):
        r = _analyze(self.analyzer, vote_duration_hours=120.0)
        self.assertAlmostEqual(r["inputs"]["vote_duration_hours"], 120.0)


# ===========================================================================
# 12. analyze_and_log + ring-buffer
# ===========================================================================

class TestAnalyzerLogAndRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = _default_analyzer(self.tmp)

    def _log_path(self):
        return _resolve_log_path(self.tmp)

    def _log_call(self, protocol_name="LogTest"):
        return self.analyzer.analyze_and_log(
            total_token_supply=1_000_000_000.0,
            top_10_holders_pct=30.0,
            quorum_threshold_pct=10.0,
            timelock_hours=48.0,
            vote_duration_hours=72.0,
            has_multisig_override=True,
            token_price_usd=2.5,
            protocol_tvl_usd=500_000_000.0,
            protocol_name=protocol_name,
        )

    def test_log_file_created(self):
        self._log_call()
        self.assertTrue(os.path.exists(self._log_path()))

    def test_log_is_list(self):
        self._log_call()
        entries = _load_log(self._log_path())
        self.assertIsInstance(entries, list)

    def test_log_appends_entries(self):
        for i in range(3):
            self._log_call(protocol_name=f"P{i}")
        entries = _load_log(self._log_path())
        self.assertEqual(len(entries), 3)

    def test_ring_buffer_cap(self):
        for i in range(LOG_MAX_ENTRIES + 15):
            self._log_call(protocol_name=f"P{i}")
        entries = _load_log(self._log_path())
        self.assertLessEqual(len(entries), LOG_MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        n = LOG_MAX_ENTRIES + 5
        for i in range(n):
            self._log_call(protocol_name=f"P{i}")
        entries = _load_log(self._log_path())
        self.assertEqual(entries[-1]["protocol_name"], f"P{n - 1}")

    def test_log_entry_has_governance_label(self):
        self._log_call()
        entries = _load_log(self._log_path())
        self.assertIn("governance_label", entries[-1])

    def test_analyze_and_log_returns_same_as_analyze(self):
        a = self.analyzer.analyze(
            total_token_supply=1e9, top_10_holders_pct=30.0,
            quorum_threshold_pct=10.0, timelock_hours=48.0,
            vote_duration_hours=72.0, has_multisig_override=True,
            token_price_usd=2.5, protocol_tvl_usd=5e8,
            protocol_name="Compare",
        )
        b = self._log_call(protocol_name="Compare")
        self.assertEqual(a["governance_attack_score"], b["governance_attack_score"])
        self.assertEqual(a["governance_label"], b["governance_label"])


# ===========================================================================
# 13. _atomic_write / _load_log / _append_log
# ===========================================================================

class TestAtomicWriteAndLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "test_gov_log.json")

    def test_atomic_write_creates_file(self):
        _atomic_write(self.log_path, [{"a": 1}])
        self.assertTrue(os.path.exists(self.log_path))

    def test_atomic_write_content_valid_json(self):
        data = [{"gov": "test"}]
        _atomic_write(self.log_path, data)
        with open(self.log_path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_load_log_missing_returns_empty(self):
        entries = _load_log("/no/such/file/log.json")
        self.assertEqual(entries, [])

    def test_load_log_corrupt_returns_empty(self):
        with open(self.log_path, "w") as f:
            f.write("{{{bad json")
        entries = _load_log(self.log_path)
        self.assertEqual(entries, [])

    def test_append_log_basic(self):
        _append_log(self.log_path, {"z": 99})
        entries = _load_log(self.log_path)
        self.assertEqual(entries[0]["z"], 99)

    def test_append_log_multiple(self):
        for i in range(7):
            _append_log(self.log_path, {"i": i})
        entries = _load_log(self.log_path)
        self.assertEqual(len(entries), 7)

    def test_append_log_ring_buffer_cap(self):
        for i in range(130):
            _append_log(self.log_path, {"i": i})
        entries = _load_log(self.log_path)
        self.assertLessEqual(len(entries), LOG_MAX_ENTRIES)

    def test_no_tmp_files_remain(self):
        _append_log(self.log_path, {"x": 1})
        tmp_files = [f for f in os.listdir(self.tmp) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])


# ===========================================================================
# 14. analyze_batch()
# ===========================================================================

class TestAnalyzerBatch(unittest.TestCase):

    def setUp(self):
        self.analyzer = _default_analyzer()

    def test_batch_empty_input(self):
        result = self.analyzer.analyze_batch([])
        self.assertEqual(result, [])

    def test_batch_returns_list(self):
        result = self.analyzer.analyze_batch([])
        self.assertIsInstance(result, list)

    def test_batch_single(self):
        result = self.analyzer.analyze_batch([{
            "total_token_supply": 1e9, "top_10_holders_pct": 30.0,
            "quorum_threshold_pct": 10.0, "timelock_hours": 48.0,
            "vote_duration_hours": 72.0, "has_multisig_override": True,
            "token_price_usd": 2.5, "protocol_tvl_usd": 5e8,
            "protocol_name": "SingleBatch",
        }])
        self.assertEqual(len(result), 1)

    def test_batch_multiple(self):
        protos = [
            {"protocol_name": "A"},
            {"protocol_name": "B"},
            {"protocol_name": "C"},
        ]
        result = self.analyzer.analyze_batch(protos)
        self.assertEqual(len(result), 3)

    def test_batch_names_preserved(self):
        protos = [{"protocol_name": "X"}, {"protocol_name": "Y"}]
        result = self.analyzer.analyze_batch(protos)
        names = [r["protocol_name"] for r in result]
        self.assertIn("X", names)
        self.assertIn("Y", names)

    def test_batch_different_scores(self):
        protos = [
            {
                "top_10_holders_pct": 10.0, "timelock_hours": 336.0,
                "quorum_threshold_pct": 25.0, "protocol_name": "Safe",
            },
            {
                "top_10_holders_pct": 80.0, "timelock_hours": 0.0,
                "quorum_threshold_pct": 0.5, "protocol_name": "Risky",
            },
        ]
        result = self.analyzer.analyze_batch(protos)
        safe = next(r for r in result if r["protocol_name"] == "Safe")
        risky = next(r for r in result if r["protocol_name"] == "Risky")
        self.assertLess(safe["governance_attack_score"], risky["governance_attack_score"])


# ===========================================================================
# 15. _iso_now
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
# 16. run() module function
# ===========================================================================

class TestRunFunction(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_run_returns_list(self):
        results = run(data_dir=self.tmp)
        self.assertIsInstance(results, list)

    def test_run_non_empty(self):
        results = run(data_dir=self.tmp)
        self.assertGreater(len(results), 0)

    def test_run_creates_log_file(self):
        run(data_dir=self.tmp)
        log_path = _resolve_log_path(self.tmp)
        self.assertTrue(os.path.exists(log_path))

    def test_run_all_have_governance_label(self):
        results = run(data_dir=self.tmp)
        for r in results:
            self.assertIn("governance_label", r)

    def test_run_all_have_protocol_name(self):
        results = run(data_dir=self.tmp)
        for r in results:
            self.assertNotEqual(r["protocol_name"], "")

    def test_run_scores_in_range(self):
        results = run(data_dir=self.tmp)
        for r in results:
            self.assertGreaterEqual(r["governance_attack_score"], 0)
            self.assertLessEqual(r["governance_attack_score"], 100)


# ===========================================================================
# 17. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.analyzer = _default_analyzer()

    def test_zero_token_supply(self):
        r = _analyze(self.analyzer, total_token_supply=0.0)
        self.assertAlmostEqual(r["attack_cost_usd"], 0.0)

    def test_zero_token_price(self):
        r = _analyze(self.analyzer, token_price_usd=0.0)
        self.assertAlmostEqual(r["attack_cost_usd"], 0.0)

    def test_very_large_supply(self):
        r = _analyze(self.analyzer, total_token_supply=1e18)
        self.assertGreater(r["attack_cost_usd"], 0.0)

    def test_100_pct_concentration(self):
        r = _analyze(self.analyzer, top_10_holders_pct=100.0)
        self.assertEqual(r["concentration_risk_score"], 40)

    def test_zero_concentration(self):
        r = _analyze(self.analyzer, top_10_holders_pct=0.0)
        self.assertEqual(r["concentration_risk_score"], 0)

    def test_very_long_timelock(self):
        r = _analyze(self.analyzer, timelock_hours=10_000.0)
        self.assertEqual(r["timelock_safety_score"], 30)

    def test_empty_protocol_name(self):
        r = _analyze(self.analyzer, protocol_name="")
        self.assertEqual(r["protocol_name"], "")

    def test_multiple_calls_independent(self):
        r1 = _analyze(self.analyzer, top_10_holders_pct=10.0, protocol_name="A")
        r2 = _analyze(self.analyzer, top_10_holders_pct=80.0, protocol_name="B")
        self.assertNotEqual(r1["concentration_risk_score"], r2["concentration_risk_score"])

    def test_governance_score_never_negative(self):
        r = _analyze(
            self.analyzer,
            top_10_holders_pct=0.0,
            timelock_hours=10_000.0,
            quorum_threshold_pct=100.0,
        )
        self.assertGreaterEqual(r["governance_attack_score"], 0)

    def test_governance_score_never_above_100(self):
        r = _analyze(
            self.analyzer,
            top_10_holders_pct=100.0,
            timelock_hours=0.0,
            quorum_threshold_pct=0.0,
        )
        self.assertLessEqual(r["governance_attack_score"], 100)

    def test_high_quorum_gives_zero_quorum_penalty(self):
        r = _analyze(self.analyzer, quorum_threshold_pct=50.0)
        # quorum >= 15 → penalty = 0
        # So governance_attack_score = conc + timelock_penalty + 0
        conc = r["concentration_risk_score"]
        tls = r["timelock_safety_score"]
        expected = max(0, min(100, conc + (30 - tls) + 0))
        self.assertEqual(r["governance_attack_score"], expected)


# ===========================================================================
# 18. Scenario integration tests
# ===========================================================================

class TestScenarios(unittest.TestCase):

    def setUp(self):
        self.analyzer = _default_analyzer()

    def test_fortress_governance_scenario(self):
        # Very decentralized, long timelock, high quorum
        r = self.analyzer.analyze(
            total_token_supply=2_000_000_000.0,
            top_10_holders_pct=12.0,
            quorum_threshold_pct=30.0,
            timelock_hours=336.0,
            vote_duration_hours=168.0,
            has_multisig_override=True,
            token_price_usd=10.0,
            protocol_tvl_usd=20_000_000_000.0,
            protocol_name="FortressDAO",
        )
        self.assertLessEqual(r["governance_attack_score"], 15)
        self.assertEqual(r["governance_label"], "FORTRESS_GOVERNANCE")

    def test_governance_exploit_risk_scenario(self):
        # Highly concentrated, no timelock, tiny quorum
        r = self.analyzer.analyze(
            total_token_supply=10_000_000.0,
            top_10_holders_pct=85.0,
            quorum_threshold_pct=0.5,
            timelock_hours=0.0,
            vote_duration_hours=6.0,
            has_multisig_override=False,
            token_price_usd=0.50,
            protocol_tvl_usd=5_000_000.0,
            protocol_name="ExploitDAO",
        )
        self.assertGreater(r["governance_attack_score"], 75)
        self.assertEqual(r["governance_label"], "GOVERNANCE_EXPLOIT_RISK")

    def test_compound_dao_scenario(self):
        r = self.analyzer.analyze(
            total_token_supply=10_000_000.0,
            top_10_holders_pct=40.0,
            quorum_threshold_pct=4.0,
            timelock_hours=48.0,
            vote_duration_hours=72.0,
            has_multisig_override=True,
            token_price_usd=60.0,
            protocol_tvl_usd=3_000_000_000.0,
            protocol_name="CompoundDAO",
        )
        self.assertIn(r["governance_label"], [
            "ADEQUATE_GOVERNANCE", "WEAK_GOVERNANCE", "STRONG_GOVERNANCE"
        ])

    def test_attack_cost_ratio_reflects_tvl(self):
        r = self.analyzer.analyze(
            total_token_supply=100_000_000.0,
            top_10_holders_pct=30.0,
            quorum_threshold_pct=4.0,
            timelock_hours=24.0,
            vote_duration_hours=48.0,
            has_multisig_override=False,
            token_price_usd=1.0,
            protocol_tvl_usd=1_000_000.0,
            protocol_name="RatioTest",
        )
        # attack_cost = (4/2+0.01)/100 * 100M * 1 = 2.01% of 100M = 2_010_000
        # ratio = 2_010_000 / 1_000_000 = 2.01
        self.assertAlmostEqual(r["attack_cost_to_tvl_ratio"], 2.01, places=4)

    def test_low_cost_ratio_high_risk_indicator(self):
        # cheap to attack relative to TVL → higher governance risk
        r_cheap = self.analyzer.analyze(
            total_token_supply=1_000_000.0,
            top_10_holders_pct=70.0,
            quorum_threshold_pct=1.0,
            timelock_hours=0.0,
            vote_duration_hours=12.0,
            has_multisig_override=False,
            token_price_usd=0.01,
            protocol_tvl_usd=100_000_000.0,
            protocol_name="CheapAttack",
        )
        self.assertLess(r_cheap["attack_cost_to_tvl_ratio"], 0.01)
        self.assertGreater(r_cheap["governance_attack_score"], 55)


if __name__ == "__main__":
    unittest.main(verbosity=2)
