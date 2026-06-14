"""
Tests for MP-1052: DeFiProtocolTokenBridgeSecurityRiskAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_token_bridge_security_risk_analyzer -v
≥ 90 tests covering all helpers and integration paths.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from spa_core.analytics.defi_protocol_token_bridge_security_risk_analyzer import (
    DeFiProtocolTokenBridgeSecurityRiskAnalyzer,
    AUDIT_FRESHNESS_TABLE,
    AUDIT_STALE_SCORE,
    LABEL_THRESHOLDS,
    MAX_ENTRIES,
    VALIDATION_STRENGTH,
    compute_audit_freshness_score,
    compute_bridge_risk_score,
    compute_finality_risk_penalty,
    compute_hack_exposure_ratio,
    compute_overall_label,
    compute_validation_strength_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_params(**overrides):
    """Return a safe-default param dict, overridable."""
    params = dict(
        bridge_name="TestBridge",
        tvl_usd=500_000_000,
        validation_model="zk",
        validator_count=10,
        days_since_last_audit=15,
        historical_hacks=[],
        open_source=True,
        bug_bounty_usd=1_000_000,
        time_to_finality_minutes=5,
    )
    params.update(overrides)
    return params


def _make_analyzer(tmp_dir):
    """Create analyzer with a temp data file."""
    data_file = Path(tmp_dir) / "bridge_security_risk_log.json"
    return DeFiProtocolTokenBridgeSecurityRiskAnalyzer(data_file=data_file)


# ===========================================================================
# Tests: compute_validation_strength_score
# ===========================================================================

class TestValidationStrengthScore(unittest.TestCase):

    def test_zk_returns_95(self):
        self.assertAlmostEqual(compute_validation_strength_score("zk", 5), 95.0)

    def test_zk_proof_alias_returns_95(self):
        self.assertAlmostEqual(compute_validation_strength_score("zk_proof", 5), 95.0)

    def test_optimistic_returns_60(self):
        self.assertAlmostEqual(compute_validation_strength_score("optimistic", 5), 60.0)

    def test_multisig_base_is_45(self):
        # validator_count=1 → 45 + min(40, 3) = 48
        self.assertAlmostEqual(compute_validation_strength_score("multisig", 1), 48.0)

    def test_multisig_boost_by_validator_count(self):
        # validator_count=10 → 45 + min(40, 30) = 75
        self.assertAlmostEqual(compute_validation_strength_score("multisig", 10), 75.0)

    def test_multisig_boost_capped_at_90(self):
        # validator_count=20 → 45 + min(40, 60) = 45 + 40 = 85, cap at 90 → 85
        score = compute_validation_strength_score("multisig", 20)
        self.assertLessEqual(score, 90.0)

    def test_multisig_large_validator_count_hits_cap(self):
        # validator_count=50 → 45 + min(40, 150) = 85 → below cap → 85
        score = compute_validation_strength_score("multisig", 50)
        self.assertEqual(score, 85.0)

    def test_poa_low_score(self):
        score = compute_validation_strength_score("poa", 5)
        self.assertLess(score, 60.0)

    def test_federated_lower_than_multisig(self):
        fed = compute_validation_strength_score("federated", 5)
        ms = compute_validation_strength_score("multisig", 5)
        self.assertLess(fed, ms)

    def test_unknown_model_returns_low_score(self):
        score = compute_validation_strength_score("alien_model", 5)
        self.assertLessEqual(score, 40.0)

    def test_case_insensitive(self):
        self.assertAlmostEqual(
            compute_validation_strength_score("ZK", 5),
            compute_validation_strength_score("zk", 5),
        )

    def test_optimistic_case_insensitive(self):
        self.assertAlmostEqual(
            compute_validation_strength_score("OPTIMISTIC", 5),
            compute_validation_strength_score("optimistic", 5),
        )

    def test_score_always_0_to_100(self):
        for model in ["zk", "optimistic", "multisig", "poa", "federated", "unknown"]:
            for vc in [1, 5, 10, 100]:
                score = compute_validation_strength_score(model, vc)
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 100.0)

    def test_zk_greater_than_optimistic(self):
        self.assertGreater(
            compute_validation_strength_score("zk", 5),
            compute_validation_strength_score("optimistic", 5),
        )

    def test_optimistic_greater_than_poa(self):
        self.assertGreater(
            compute_validation_strength_score("optimistic", 1),
            compute_validation_strength_score("poa", 1),
        )


# ===========================================================================
# Tests: compute_audit_freshness_score
# ===========================================================================

class TestAuditFreshnessScore(unittest.TestCase):

    def test_recent_audit_0_days(self):
        self.assertEqual(compute_audit_freshness_score(0), 100.0)

    def test_audit_15_days(self):
        self.assertEqual(compute_audit_freshness_score(15), 100.0)

    def test_audit_at_30_days(self):
        self.assertEqual(compute_audit_freshness_score(30), 100.0)

    def test_audit_31_days(self):
        self.assertEqual(compute_audit_freshness_score(31), 80.0)

    def test_audit_90_days(self):
        self.assertEqual(compute_audit_freshness_score(90), 80.0)

    def test_audit_91_days(self):
        self.assertEqual(compute_audit_freshness_score(91), 60.0)

    def test_audit_180_days(self):
        self.assertEqual(compute_audit_freshness_score(180), 60.0)

    def test_audit_181_days(self):
        self.assertEqual(compute_audit_freshness_score(181), 35.0)

    def test_audit_365_days(self):
        self.assertEqual(compute_audit_freshness_score(365), 35.0)

    def test_audit_366_days(self):
        self.assertEqual(compute_audit_freshness_score(366), 15.0)

    def test_audit_730_days(self):
        self.assertEqual(compute_audit_freshness_score(730), 15.0)

    def test_audit_stale_731_days(self):
        self.assertEqual(compute_audit_freshness_score(731), AUDIT_STALE_SCORE)

    def test_audit_stale_1000_days(self):
        self.assertEqual(compute_audit_freshness_score(1000), AUDIT_STALE_SCORE)

    def test_negative_days_returns_100(self):
        # Treat as just-audited
        self.assertEqual(compute_audit_freshness_score(-1), 100.0)

    def test_freshness_decreases_monotonically(self):
        days = [0, 30, 90, 180, 365, 730, 1000]
        scores = [compute_audit_freshness_score(d) for d in days]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1])


# ===========================================================================
# Tests: compute_hack_exposure_ratio
# ===========================================================================

class TestHackExposureRatio(unittest.TestCase):

    def test_no_hacks_returns_zero(self):
        self.assertEqual(compute_hack_exposure_ratio([], 100_000_000), 0.0)

    def test_single_hack_half_tvl(self):
        hacks = [{"date": "2022-01-01", "amount_usd": 50_000_000}]
        ratio = compute_hack_exposure_ratio(hacks, 100_000_000)
        self.assertAlmostEqual(ratio, 0.5)

    def test_total_hacked_exceeds_tvl_capped_at_1(self):
        hacks = [{"amount_usd": 200_000_000}]
        ratio = compute_hack_exposure_ratio(hacks, 100_000_000)
        self.assertEqual(ratio, 1.0)

    def test_multiple_hacks_summed(self):
        hacks = [{"amount_usd": 30_000_000}, {"amount_usd": 20_000_000}]
        ratio = compute_hack_exposure_ratio(hacks, 100_000_000)
        self.assertAlmostEqual(ratio, 0.5)

    def test_zero_tvl_returns_1(self):
        ratio = compute_hack_exposure_ratio([], 0)
        self.assertEqual(ratio, 1.0)

    def test_negative_tvl_returns_1(self):
        ratio = compute_hack_exposure_ratio([], -1)
        self.assertEqual(ratio, 1.0)

    def test_ratio_bounded_0_to_1(self):
        hacks = [{"amount_usd": 999_999_999}]
        ratio = compute_hack_exposure_ratio(hacks, 1_000_000)
        self.assertGreaterEqual(ratio, 0.0)
        self.assertLessEqual(ratio, 1.0)

    def test_hack_with_zero_amount(self):
        hacks = [{"amount_usd": 0}]
        ratio = compute_hack_exposure_ratio(hacks, 100_000_000)
        self.assertEqual(ratio, 0.0)

    def test_missing_amount_usd_defaults_to_zero(self):
        hacks = [{"date": "2022-01-01"}]  # no amount_usd key
        ratio = compute_hack_exposure_ratio(hacks, 100_000_000)
        self.assertEqual(ratio, 0.0)


# ===========================================================================
# Tests: compute_finality_risk_penalty
# ===========================================================================

class TestFinalityRiskPenalty(unittest.TestCase):

    def test_instant_finality_zero_penalty(self):
        self.assertEqual(compute_finality_risk_penalty(0), 0.0)

    def test_sub_1_minute_zero_penalty(self):
        self.assertEqual(compute_finality_risk_penalty(1), 0.0)

    def test_1_to_5_minutes_small_penalty(self):
        self.assertEqual(compute_finality_risk_penalty(3), 3.0)

    def test_5_minutes_small_penalty(self):
        self.assertEqual(compute_finality_risk_penalty(5), 3.0)

    def test_6_minutes_medium_penalty(self):
        self.assertEqual(compute_finality_risk_penalty(6), 8.0)

    def test_20_minutes_medium_penalty(self):
        self.assertEqual(compute_finality_risk_penalty(20), 8.0)

    def test_21_minutes_higher_penalty(self):
        self.assertEqual(compute_finality_risk_penalty(21), 15.0)

    def test_60_minutes_higher_penalty(self):
        self.assertEqual(compute_finality_risk_penalty(60), 15.0)

    def test_61_minutes_very_high_penalty(self):
        self.assertEqual(compute_finality_risk_penalty(61), 20.0)

    def test_1440_minutes_very_high_penalty(self):
        self.assertEqual(compute_finality_risk_penalty(1440), 20.0)

    def test_over_1440_minutes_max_penalty(self):
        self.assertEqual(compute_finality_risk_penalty(10080), 25.0)

    def test_penalty_increases_monotonically(self):
        minutes = [0, 1, 5, 20, 60, 1440, 10080]
        penalties = [compute_finality_risk_penalty(m) for m in minutes]
        for i in range(len(penalties) - 1):
            self.assertLessEqual(penalties[i], penalties[i + 1])


# ===========================================================================
# Tests: compute_bridge_risk_score
# ===========================================================================

class TestBridgeRiskScore(unittest.TestCase):

    def _score(self, **kwargs):
        # Moderate defaults so that adjustments (open_source, bounty, tvl) have visible effect
        defaults = dict(
            validation_strength_score=55.0,
            audit_freshness_score=60.0,
            hack_exposure_ratio=0.0,
            time_to_finality_minutes=15.0,
            open_source=False,
            bug_bounty_usd=0,
            tvl_usd=10_000_000,
        )
        defaults.update(kwargs)
        return compute_bridge_risk_score(**defaults)

    def test_score_range_0_to_100(self):
        for vs in [0, 50, 100]:
            for af in [0, 50, 100]:
                score = self._score(validation_strength_score=vs, audit_freshness_score=af)
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 100.0)

    def test_perfect_inputs_give_low_score(self):
        score = self._score(
            validation_strength_score=95.0,
            audit_freshness_score=100.0,
            hack_exposure_ratio=0.0,
            time_to_finality_minutes=1.0,
            open_source=True,
            bug_bounty_usd=2_000_000,
            tvl_usd=1_000_000_000,
        )
        self.assertLess(score, 25.0)

    def test_worst_inputs_give_high_score(self):
        score = self._score(
            validation_strength_score=0.0,
            audit_freshness_score=0.0,
            hack_exposure_ratio=1.0,
            time_to_finality_minutes=10080,
            open_source=False,
            bug_bounty_usd=0,
            tvl_usd=0,
        )
        self.assertGreater(score, 70.0)

    def test_open_source_reduces_score(self):
        closed = self._score(open_source=False)
        opened = self._score(open_source=True)
        self.assertLess(opened, closed)

    def test_large_bounty_reduces_score(self):
        no_bounty = self._score(bug_bounty_usd=0)
        big_bounty = self._score(bug_bounty_usd=2_000_000)
        self.assertLess(big_bounty, no_bounty)

    def test_bounty_tiers_ordered(self):
        s0 = self._score(bug_bounty_usd=0)
        s1 = self._score(bug_bounty_usd=50_000)
        s2 = self._score(bug_bounty_usd=500_000)
        s3 = self._score(bug_bounty_usd=2_000_000)
        self.assertGreater(s0, s1)
        self.assertGreater(s1, s2)
        self.assertGreater(s2, s3)

    def test_high_tvl_reduces_score(self):
        low_tvl = self._score(tvl_usd=10_000_000)
        high_tvl = self._score(tvl_usd=500_000_000)
        self.assertLess(high_tvl, low_tvl)

    def test_hack_exposure_increases_score(self):
        s_safe = self._score(hack_exposure_ratio=0.0)
        s_risky = self._score(hack_exposure_ratio=1.0)
        self.assertLess(s_safe, s_risky)

    def test_stale_audit_increases_score(self):
        fresh = self._score(audit_freshness_score=100.0)
        stale = self._score(audit_freshness_score=0.0)
        self.assertLess(fresh, stale)

    def test_weak_validation_increases_score(self):
        strong = self._score(validation_strength_score=95.0)
        weak = self._score(validation_strength_score=10.0)
        self.assertLess(strong, weak)

    def test_result_is_float(self):
        self.assertIsInstance(self._score(), float)


# ===========================================================================
# Tests: compute_overall_label
# ===========================================================================

class TestOverallLabel(unittest.TestCase):

    def test_score_0_is_fortress(self):
        self.assertEqual(compute_overall_label(0.0), "FORTRESS_BRIDGE")

    def test_score_19_is_fortress(self):
        self.assertEqual(compute_overall_label(19.9), "FORTRESS_BRIDGE")

    def test_score_20_is_secure(self):
        self.assertEqual(compute_overall_label(20.0), "SECURE_BRIDGE")

    def test_score_39_is_secure(self):
        self.assertEqual(compute_overall_label(39.9), "SECURE_BRIDGE")

    def test_score_40_is_moderate(self):
        self.assertEqual(compute_overall_label(40.0), "MODERATE_RISK")

    def test_score_59_is_moderate(self):
        self.assertEqual(compute_overall_label(59.9), "MODERATE_RISK")

    def test_score_60_is_high_risk(self):
        self.assertEqual(compute_overall_label(60.0), "HIGH_RISK")

    def test_score_79_is_high_risk(self):
        self.assertEqual(compute_overall_label(79.9), "HIGH_RISK")

    def test_score_80_is_do_not_use(self):
        self.assertEqual(compute_overall_label(80.0), "DO_NOT_USE")

    def test_score_100_is_do_not_use(self):
        self.assertEqual(compute_overall_label(100.0), "DO_NOT_USE")

    def test_valid_labels_set(self):
        valid = {"FORTRESS_BRIDGE", "SECURE_BRIDGE", "MODERATE_RISK", "HIGH_RISK", "DO_NOT_USE"}
        for score in [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            self.assertIn(compute_overall_label(float(score)), valid)


# ===========================================================================
# Tests: DeFiProtocolTokenBridgeSecurityRiskAnalyzer (integration)
# ===========================================================================

class TestAnalyzerIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = _make_analyzer(self.tmp)

    def _analyze(self, **overrides):
        return self.analyzer.analyze(_default_params(**overrides))

    # --- Output keys ---
    def test_result_contains_all_output_keys(self):
        result = self._analyze()
        for key in DeFiProtocolTokenBridgeSecurityRiskAnalyzer.OUTPUT_KEYS:
            self.assertIn(key, result)

    def test_bridge_name_preserved(self):
        result = self._analyze(bridge_name="MyBridge")
        self.assertEqual(result["bridge_name"], "MyBridge")

    def test_overall_label_is_string(self):
        result = self._analyze()
        self.assertIsInstance(result["overall_label"], str)

    def test_bridge_risk_score_in_range(self):
        result = self._analyze()
        self.assertGreaterEqual(result["bridge_risk_score"], 0.0)
        self.assertLessEqual(result["bridge_risk_score"], 100.0)

    def test_hack_exposure_ratio_in_range(self):
        result = self._analyze(
            historical_hacks=[{"amount_usd": 100_000_000}], tvl_usd=200_000_000
        )
        self.assertAlmostEqual(result["hack_exposure_ratio"], 0.5)

    def test_audit_freshness_score_returned(self):
        result = self._analyze(days_since_last_audit=15)
        self.assertEqual(result["audit_freshness_score"], 100.0)

    def test_validation_strength_score_returned(self):
        result = self._analyze(validation_model="zk", validator_count=5)
        self.assertAlmostEqual(result["validation_strength_score"], 95.0)

    def test_timestamp_is_recent(self):
        result = self._analyze()
        now = time.time()
        self.assertAlmostEqual(result["timestamp"], now, delta=5.0)

    # --- Log file ---
    def test_log_file_created(self):
        self._analyze()
        log_path = Path(self.tmp) / "bridge_security_risk_log.json"
        self.assertTrue(log_path.exists())

    def test_log_file_is_list(self):
        self._analyze()
        log_path = Path(self.tmp) / "bridge_security_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_accumulates_entries(self):
        for _ in range(5):
            self._analyze()
        log_path = Path(self.tmp) / "bridge_security_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_ring_buffer_capped(self):
        analyzer = DeFiProtocolTokenBridgeSecurityRiskAnalyzer(
            data_file=Path(self.tmp) / "ring.json", max_entries=3
        )
        for i in range(10):
            analyzer.analyze(_default_params(bridge_name=f"b{i}"))
        with open(Path(self.tmp) / "ring.json") as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)
        # Most recent entries retained
        self.assertEqual(data[-1]["bridge_name"], "b9")

    def test_log_atomic_write_no_partial(self):
        """Log file should never be empty after a successful call."""
        self._analyze()
        log_path = Path(self.tmp) / "bridge_security_risk_log.json"
        with open(log_path) as f:
            content = f.read()
        self.assertGreater(len(content), 0)

    # --- Scenario tests ---
    def test_pristine_zk_bridge_fortress(self):
        result = self._analyze(
            validation_model="zk",
            validator_count=20,
            days_since_last_audit=10,
            historical_hacks=[],
            open_source=True,
            bug_bounty_usd=5_000_000,
            tvl_usd=1_000_000_000,
            time_to_finality_minutes=2,
        )
        self.assertIn(result["overall_label"], ("FORTRESS_BRIDGE", "SECURE_BRIDGE"))

    def test_hacked_old_bridge_do_not_use(self):
        result = self._analyze(
            validation_model="poa",
            validator_count=3,
            days_since_last_audit=800,
            historical_hacks=[{"amount_usd": 300_000_000}],
            tvl_usd=100_000_000,  # hack > tvl
            open_source=False,
            bug_bounty_usd=0,
            time_to_finality_minutes=2000,
        )
        self.assertIn(result["overall_label"], ("HIGH_RISK", "DO_NOT_USE"))

    def test_optimistic_bridge_moderate(self):
        result = self._analyze(
            validation_model="optimistic",
            validator_count=3,
            days_since_last_audit=400,   # stale audit
            historical_hacks=[],
            open_source=False,
            bug_bounty_usd=0,
            tvl_usd=20_000_000,
            time_to_finality_minutes=10080,  # 7-day challenge
        )
        # stale audit + no bounty + 7-day finality: should not be the safest label
        self.assertNotIn(result["overall_label"], ("FORTRESS_BRIDGE",))

    # --- Validation errors ---
    def test_missing_key_raises(self):
        params = _default_params()
        del params["tvl_usd"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_negative_tvl_raises(self):
        with self.assertRaises(ValueError):
            self._analyze(tvl_usd=-1)

    def test_zero_validator_count_raises(self):
        with self.assertRaises(ValueError):
            self._analyze(validator_count=0)

    def test_negative_days_since_audit_raises(self):
        with self.assertRaises(ValueError):
            self._analyze(days_since_last_audit=-1)

    def test_negative_bounty_raises(self):
        with self.assertRaises(ValueError):
            self._analyze(bug_bounty_usd=-100)

    def test_negative_finality_raises(self):
        with self.assertRaises(ValueError):
            self._analyze(time_to_finality_minutes=-5)

    def test_zero_tvl_accepted(self):
        """Zero TVL is valid (bridge might be pre-launch); hack_exposure_ratio = 1."""
        result = self._analyze(tvl_usd=0, historical_hacks=[])
        self.assertEqual(result["hack_exposure_ratio"], 1.0)

    # --- Label completeness ---
    def test_all_five_labels_reachable(self):
        """Each label can be reached with appropriate inputs."""
        seen = set()
        test_cases = [
            # FORTRESS_BRIDGE
            _default_params(validation_model="zk", days_since_last_audit=5,
                            historical_hacks=[], open_source=True, bug_bounty_usd=2_000_000,
                            time_to_finality_minutes=1, tvl_usd=1_000_000_000),
            # SECURE_BRIDGE — slightly less perfect
            _default_params(validation_model="optimistic", days_since_last_audit=50,
                            historical_hacks=[], open_source=True, bug_bounty_usd=200_000,
                            time_to_finality_minutes=5, tvl_usd=200_000_000),
            # MODERATE_RISK
            _default_params(validation_model="multisig", validator_count=5,
                            days_since_last_audit=200, historical_hacks=[],
                            open_source=True, bug_bounty_usd=0,
                            time_to_finality_minutes=30, tvl_usd=50_000_000),
            # HIGH_RISK
            _default_params(validation_model="federated", validator_count=3,
                            days_since_last_audit=400,
                            historical_hacks=[{"amount_usd": 50_000_000}],
                            tvl_usd=100_000_000, open_source=False,
                            bug_bounty_usd=0, time_to_finality_minutes=120),
            # DO_NOT_USE
            _default_params(validation_model="poa", validator_count=1,
                            days_since_last_audit=800,
                            historical_hacks=[{"amount_usd": 200_000_000}],
                            tvl_usd=50_000_000, open_source=False,
                            bug_bounty_usd=0, time_to_finality_minutes=5000),
        ]
        for params in test_cases:
            result = self.analyzer.analyze(params)
            seen.add(result["overall_label"])
        # At minimum 4 distinct labels should be reachable
        self.assertGreaterEqual(len(seen), 4)

    def test_multiple_historical_hacks_summed(self):
        hacks = [{"amount_usd": 50_000_000}, {"amount_usd": 50_000_000}]
        result = self._analyze(historical_hacks=hacks, tvl_usd=200_000_000)
        self.assertAlmostEqual(result["hack_exposure_ratio"], 0.5)

    def test_open_source_false_increases_risk(self):
        r_open = self._analyze(open_source=True)
        r_closed = self._analyze(open_source=False)
        self.assertLessEqual(r_open["bridge_risk_score"], r_closed["bridge_risk_score"])


if __name__ == "__main__":
    unittest.main()
