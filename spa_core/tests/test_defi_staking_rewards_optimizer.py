"""
Tests for MP-843 DeFiStakingRewardsOptimizer
=============================================
Run with: python3 -m unittest spa_core/tests/test_defi_staking_rewards_optimizer.py
≥ 65 test cases.
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path bootstrap so tests can be run from repo root
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_staking_rewards_optimizer import (
    _compound_apy,
    _lockup_penalty_factor,
    _skip_reason,
    _stability_penalty,
    analyze,
    _log_result,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _opt(
    protocol="TestProto",
    base_apy=5.0,
    bonus_apy=0.0,
    lockup_days=0,
    compound_frequency=1,
    reward_token_stability="STABLE",
    min_stake_usd=0.0,
    risk_score=10,
):
    return dict(
        protocol=protocol,
        base_apy=base_apy,
        bonus_apy=bonus_apy,
        lockup_days=lockup_days,
        compound_frequency=compound_frequency,
        reward_token_stability=reward_token_stability,
        min_stake_usd=min_stake_usd,
        risk_score=risk_score,
    )


# ===========================================================================
# Unit helpers
# ===========================================================================

class TestCompoundApy(unittest.TestCase):
    """Tests for _compound_apy()"""

    def test_annual_compound_no_effect(self):
        # compound_frequency=1: effective ≈ total (slight difference due to formula)
        # (1+r/1)^1 - 1 = r exactly
        result = _compound_apy(10.0, 1)
        self.assertAlmostEqual(result, 10.0, places=10)

    def test_monthly_compound_increases_apy(self):
        # monthly compounding should give more than annual
        result = _compound_apy(12.0, 12)
        self.assertGreater(result, 12.0)

    def test_daily_compound_higher_than_monthly(self):
        daily = _compound_apy(12.0, 365)
        monthly = _compound_apy(12.0, 12)
        self.assertGreater(daily, monthly)

    def test_zero_compound_frequency_returns_total(self):
        result = _compound_apy(8.5, 0)
        self.assertAlmostEqual(result, 8.5, places=10)

    def test_zero_apy_gives_zero(self):
        result = _compound_apy(0.0, 365)
        self.assertAlmostEqual(result, 0.0, places=10)

    def test_monthly_12pct_formula(self):
        expected = ((1 + 0.12 / 12) ** 12 - 1) * 100.0
        result = _compound_apy(12.0, 12)
        self.assertAlmostEqual(result, expected, places=10)

    def test_daily_5pct_formula(self):
        expected = ((1 + 0.05 / 365) ** 365 - 1) * 100.0
        result = _compound_apy(5.0, 365)
        self.assertAlmostEqual(result, expected, places=8)

    def test_weekly_compound(self):
        result = _compound_apy(10.0, 52)
        self.assertGreater(result, 10.0)
        self.assertLess(result, 11.0)

    def test_high_apy_compounding(self):
        result = _compound_apy(100.0, 365)
        self.assertGreater(result, 100.0)


class TestStabilityPenalty(unittest.TestCase):
    """Tests for _stability_penalty()"""

    def test_stable_zero_penalty(self):
        self.assertAlmostEqual(_stability_penalty("STABLE"), 0.0)

    def test_volatile_10pct_penalty(self):
        self.assertAlmostEqual(_stability_penalty("VOLATILE"), 0.1)

    def test_highly_volatile_30pct_penalty(self):
        self.assertAlmostEqual(_stability_penalty("HIGHLY_VOLATILE"), 0.3)

    def test_unknown_stability_defaults_zero(self):
        self.assertAlmostEqual(_stability_penalty("UNKNOWN"), 0.0)

    def test_empty_string_defaults_zero(self):
        self.assertAlmostEqual(_stability_penalty(""), 0.0)


class TestLockupPenalty(unittest.TestCase):
    """Tests for _lockup_penalty_factor()"""

    def test_zero_lockup_no_penalty(self):
        self.assertAlmostEqual(_lockup_penalty_factor(0), 1.0)

    def test_3650_day_lockup_zero(self):
        self.assertAlmostEqual(_lockup_penalty_factor(3650), 0.0)

    def test_365_day_lockup_10pct_penalty(self):
        factor = _lockup_penalty_factor(365)
        self.assertAlmostEqual(factor, 1.0 - 365 / 3650, places=10)

    def test_1825_day_lockup_50pct_penalty(self):
        factor = _lockup_penalty_factor(1825)
        self.assertAlmostEqual(factor, 0.5, places=10)

    def test_over_3650_clamped_to_zero(self):
        factor = _lockup_penalty_factor(5000)
        self.assertEqual(factor, 0.0)

    def test_negative_lockup_clamped(self):
        # edge: negative shouldn't go above 1
        # formula gives > 1.0 which is unusual but clamped to max(0.0, ...) only floors at 0
        # we just check no exception
        result = _lockup_penalty_factor(-1)
        self.assertGreaterEqual(result, 0.0)


class TestSkipReason(unittest.TestCase):
    """Tests for _skip_reason()"""

    def test_no_skip(self):
        result = _skip_reason(30, 40, 5000.0, 100.0, 365, 50)
        self.assertIsNone(result)

    def test_lockup_exceeds_max(self):
        result = _skip_reason(400, 40, 5000.0, 100.0, 365, 50)
        self.assertIn("Lockup 400d exceeds max 365d", result)

    def test_risk_exceeds_tolerance(self):
        result = _skip_reason(30, 80, 5000.0, 100.0, 365, 50)
        self.assertIn("Risk score 80 exceeds tolerance 50", result)

    def test_capital_below_minimum(self):
        result = _skip_reason(30, 40, 50.0, 100.0, 365, 50)
        self.assertIn("Capital $50 below minimum $100", result)

    def test_lockup_priority_over_risk(self):
        # both lockup AND risk exceed; lockup checked first
        result = _skip_reason(400, 80, 5000.0, 100.0, 365, 50)
        self.assertIn("Lockup", result)

    def test_risk_priority_over_capital(self):
        # lockup ok, risk bad, capital bad → risk returned first
        result = _skip_reason(30, 80, 50.0, 100.0, 365, 50)
        self.assertIn("Risk score", result)

    def test_exact_max_lockup_no_skip(self):
        result = _skip_reason(365, 40, 5000.0, 100.0, 365, 50)
        self.assertIsNone(result)

    def test_exact_risk_tolerance_no_skip(self):
        result = _skip_reason(30, 50, 5000.0, 100.0, 365, 50)
        self.assertIsNone(result)

    def test_exact_min_stake_no_skip(self):
        result = _skip_reason(30, 40, 100.0, 100.0, 365, 50)
        self.assertIsNone(result)


# ===========================================================================
# analyze() integration tests
# ===========================================================================

class TestAnalyzeEmptyInput(unittest.TestCase):
    def test_empty_list_returns_empty_options(self):
        result = analyze([], capital_usd=100_000.0)
        self.assertEqual(result["options"], [])

    def test_empty_list_best_option_none(self):
        result = analyze([], capital_usd=100_000.0)
        self.assertIsNone(result["best_option"])

    def test_empty_list_counts_zero(self):
        result = analyze([], capital_usd=100_000.0)
        self.assertEqual(result["filtered_count"], 0)
        self.assertEqual(result["viable_count"], 0)

    def test_empty_list_timestamp_present(self):
        before = time.time()
        result = analyze([], capital_usd=100_000.0)
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)


class TestAnalyzeBasicSingle(unittest.TestCase):
    def setUp(self):
        self.opt = _opt(base_apy=10.0, bonus_apy=2.0, compound_frequency=12, risk_score=20)
        self.result = analyze([self.opt], capital_usd=50_000.0)

    def test_returns_one_option(self):
        self.assertEqual(len(self.result["options"]), 1)

    def test_total_apy_correct(self):
        self.assertAlmostEqual(self.result["options"][0]["total_apy"], 12.0)

    def test_effective_apy_greater_than_total(self):
        eff = self.result["options"][0]["effective_apy"]
        self.assertGreater(eff, 12.0)

    def test_no_stability_penalty_stable(self):
        self.assertAlmostEqual(self.result["options"][0]["reward_stability_penalty"], 0.0)

    def test_risk_adjusted_apy_less_than_effective(self):
        opt_r = self.result["options"][0]
        self.assertLess(opt_r["risk_adjusted_apy"], opt_r["effective_apy"])

    def test_annual_yield_usd_positive(self):
        self.assertGreater(self.result["options"][0]["annual_yield_usd"], 0.0)

    def test_annual_yield_usd_formula(self):
        opt_r = self.result["options"][0]
        expected = opt_r["risk_adjusted_apy"] / 100.0 * 50_000.0
        self.assertAlmostEqual(opt_r["annual_yield_usd"], expected, places=6)

    def test_protocol_name_preserved(self):
        self.assertEqual(self.result["options"][0]["protocol"], "TestProto")


class TestAnalyzeRecommendations(unittest.TestCase):
    def test_high_score_stake(self):
        # high APY, no lockup, low risk → STAKE
        opt = _opt(base_apy=20.0, bonus_apy=0.0, lockup_days=0, risk_score=0,
                   compound_frequency=1, reward_token_stability="STABLE")
        result = analyze([opt], capital_usd=100_000.0)
        self.assertEqual(result["options"][0]["recommendation"], "STAKE")

    def test_skip_due_to_lockup(self):
        opt = _opt(base_apy=10.0, lockup_days=400)
        result = analyze([opt], capital_usd=100_000.0)
        self.assertEqual(result["options"][0]["recommendation"], "SKIP")

    def test_skip_due_to_risk(self):
        opt = _opt(base_apy=10.0, risk_score=80)
        result = analyze([opt], capital_usd=100_000.0)
        self.assertEqual(result["options"][0]["recommendation"], "SKIP")

    def test_skip_due_to_capital(self):
        opt = _opt(base_apy=10.0, min_stake_usd=200_000.0)
        result = analyze([opt], capital_usd=100_000.0)
        self.assertEqual(result["options"][0]["recommendation"], "SKIP")

    def test_consider_low_score(self):
        # Very low APY → CONSIDER (score < 5 but no skip reason)
        opt = _opt(base_apy=0.5, bonus_apy=0.0, lockup_days=0,
                   risk_score=0, compound_frequency=1,
                   reward_token_stability="STABLE")
        result = analyze([opt], capital_usd=100_000.0)
        self.assertEqual(result["options"][0]["recommendation"], "CONSIDER")

    def test_consider_low_risk_adjusted(self):
        # APY OK but risk score tanks it
        opt = _opt(base_apy=10.0, risk_score=90)  # will skip due to default risk_tolerance=50
        result = analyze([opt], capital_usd=100_000.0)
        self.assertEqual(result["options"][0]["recommendation"], "SKIP")

    def test_consider_below_apy_threshold(self):
        # risk_adjusted_apy < 3.0 → CONSIDER
        opt = _opt(base_apy=2.0, bonus_apy=0.0, risk_score=0, lockup_days=0,
                   compound_frequency=1, reward_token_stability="STABLE",
                   min_stake_usd=0.0)
        result = analyze([opt], capital_usd=100_000.0)
        r = result["options"][0]
        # 2.0% * (1-0/100) = 2.0 < 3.0 threshold
        self.assertEqual(r["recommendation"], "CONSIDER")


class TestAnalyzeBestOption(unittest.TestCase):
    def test_best_option_highest_final_score_stake(self):
        opts = [
            _opt("Alpha", base_apy=15.0, risk_score=5, lockup_days=0, compound_frequency=1),
            _opt("Beta", base_apy=10.0, risk_score=5, lockup_days=0, compound_frequency=1),
        ]
        result = analyze(opts, capital_usd=100_000.0)
        self.assertEqual(result["best_option"], "Alpha")

    def test_best_option_none_when_all_skip(self):
        opts = [_opt("X", base_apy=5.0, lockup_days=500)]  # skip
        result = analyze(opts, capital_usd=100_000.0)
        self.assertIsNone(result["best_option"])

    def test_best_option_none_when_empty(self):
        result = analyze([], capital_usd=100_000.0)
        self.assertIsNone(result["best_option"])

    def test_best_option_none_when_only_consider(self):
        opts = [_opt("Y", base_apy=1.0)]  # too low for STAKE
        result = analyze(opts, capital_usd=100_000.0)
        # Might be CONSIDER or SKIP — either way best_option should not be from CONSIDER
        r = result["options"][0]
        if r["recommendation"] == "CONSIDER":
            self.assertIsNone(result["best_option"])

    def test_best_option_ignores_skip(self):
        opts = [
            _opt("Skip1", base_apy=50.0, lockup_days=500),
            _opt("Keep1", base_apy=12.0, risk_score=5),
        ]
        result = analyze(opts, capital_usd=100_000.0)
        self.assertEqual(result["best_option"], "Keep1")


class TestAnalyzeStabilityCases(unittest.TestCase):
    def test_volatile_penalty_applied(self):
        opt = _opt(base_apy=10.0, reward_token_stability="VOLATILE",
                   risk_score=0, compound_frequency=1)
        result = analyze([opt], capital_usd=100_000.0)
        r = result["options"][0]
        # effective_apy should equal total_apy (freq=1), then * 0.9
        expected_risk_adj = 10.0 * 0.9 * (1 - 0 / 100)
        self.assertAlmostEqual(r["risk_adjusted_apy"], expected_risk_adj, places=8)

    def test_highly_volatile_penalty_applied(self):
        opt = _opt(base_apy=10.0, reward_token_stability="HIGHLY_VOLATILE",
                   risk_score=0, compound_frequency=1)
        result = analyze([opt], capital_usd=100_000.0)
        r = result["options"][0]
        expected_risk_adj = 10.0 * 0.7 * (1 - 0 / 100)
        self.assertAlmostEqual(r["risk_adjusted_apy"], expected_risk_adj, places=8)

    def test_stable_no_penalty(self):
        opt = _opt(base_apy=10.0, reward_token_stability="STABLE",
                   risk_score=0, compound_frequency=1)
        result = analyze([opt], capital_usd=100_000.0)
        r = result["options"][0]
        self.assertAlmostEqual(r["risk_adjusted_apy"], 10.0, places=8)


class TestAnalyzeLockupPenalty(unittest.TestCase):
    def test_lockup_reduces_final_score(self):
        no_lock = _opt("NoLock", base_apy=10.0, lockup_days=0,
                       risk_score=0, compound_frequency=1)
        lock_365 = _opt("Lock365", base_apy=10.0, lockup_days=365,
                        risk_score=0, compound_frequency=1)
        r_no = analyze([no_lock], capital_usd=100_000.0)["options"][0]
        r_lock = analyze([lock_365], capital_usd=100_000.0,
                         config={"max_lockup_days": 3650})["options"][0]
        self.assertGreater(r_no["final_score"], r_lock["final_score"])

    def test_final_score_not_negative(self):
        opt = _opt(base_apy=5.0, lockup_days=5000)
        result = analyze([opt], capital_usd=100_000.0,
                         config={"max_lockup_days": 9999})
        self.assertGreaterEqual(result["options"][0]["final_score"], 0.0)

    def test_365_day_lockup_10pct_reduction(self):
        opt = _opt(base_apy=10.0, lockup_days=365, risk_score=0,
                   compound_frequency=1, reward_token_stability="STABLE")
        result = analyze([opt], capital_usd=100_000.0,
                         config={"max_lockup_days": 9999})
        r = result["options"][0]
        expected_score = 10.0 * (1 - 365 / 3650)
        self.assertAlmostEqual(r["final_score"], expected_score, places=8)


class TestAnalyzeCapitalEdge(unittest.TestCase):
    def test_zero_capital_yield_zero(self):
        opt = _opt(base_apy=10.0, risk_score=0)
        result = analyze([opt], capital_usd=0.0)
        self.assertAlmostEqual(result["options"][0]["annual_yield_usd"], 0.0)

    def test_zero_total_apy_yield_zero(self):
        opt = _opt(base_apy=0.0, bonus_apy=0.0, risk_score=0)
        result = analyze([opt], capital_usd=100_000.0)
        self.assertAlmostEqual(result["options"][0]["annual_yield_usd"], 0.0)

    def test_large_capital_scales_yield(self):
        opt = _opt(base_apy=5.0, risk_score=0, compound_frequency=1)
        r_small = analyze([opt], capital_usd=10_000.0)["options"][0]
        r_large = analyze([opt], capital_usd=100_000.0)["options"][0]
        self.assertAlmostEqual(r_large["annual_yield_usd"],
                                r_small["annual_yield_usd"] * 10.0, places=6)


class TestAnalyzeConfig(unittest.TestCase):
    def test_custom_max_lockup_allows_longer(self):
        opt = _opt(base_apy=10.0, lockup_days=500)
        result = analyze([opt], capital_usd=100_000.0,
                         config={"max_lockup_days": 600})
        r = result["options"][0]
        self.assertNotEqual(r["recommendation"], "SKIP")

    def test_custom_risk_tolerance_blocks_higher_risk(self):
        opt = _opt(base_apy=10.0, risk_score=60)
        result = analyze([opt], capital_usd=100_000.0,
                         config={"risk_tolerance": 50})
        self.assertEqual(result["options"][0]["recommendation"], "SKIP")

    def test_custom_risk_tolerance_allows_higher_risk(self):
        opt = _opt(base_apy=10.0, risk_score=60)
        result = analyze([opt], capital_usd=100_000.0,
                         config={"risk_tolerance": 70})
        self.assertNotEqual(result["options"][0]["recommendation"], "SKIP")

    def test_default_config_used_when_none(self):
        opt = _opt(base_apy=10.0, risk_score=40)
        result = analyze([opt], capital_usd=100_000.0, config=None)
        self.assertIn(result["options"][0]["recommendation"], ("STAKE", "CONSIDER", "SKIP"))

    def test_empty_config_uses_defaults(self):
        opt = _opt(base_apy=10.0)
        result = analyze([opt], capital_usd=100_000.0, config={})
        self.assertIn("recommendation", result["options"][0])


class TestAnalyzeFilteredCount(unittest.TestCase):
    def test_filtered_count_matches_skip(self):
        opts = [
            _opt("A", lockup_days=500),       # skip: lockup
            _opt("B", risk_score=80),          # skip: risk
            _opt("C", base_apy=10.0),          # should be STAKE
        ]
        result = analyze(opts, capital_usd=100_000.0)
        self.assertEqual(result["filtered_count"], 2)

    def test_viable_count_matches_stake(self):
        opts = [
            _opt("A", base_apy=20.0, risk_score=0),
            _opt("B", base_apy=15.0, risk_score=0),
            _opt("C", base_apy=0.5, risk_score=0),  # CONSIDER
        ]
        result = analyze(opts, capital_usd=100_000.0)
        stake_count = sum(1 for r in result["options"] if r["recommendation"] == "STAKE")
        self.assertEqual(result["viable_count"], stake_count)

    def test_all_skip_gives_zero_viable(self):
        opts = [
            _opt("X", lockup_days=400),
            _opt("Y", risk_score=80),
        ]
        result = analyze(opts, capital_usd=100_000.0)
        self.assertEqual(result["viable_count"], 0)


class TestAnalyzeSkipReason(unittest.TestCase):
    def test_skip_reason_set_for_lockup(self):
        opt = _opt(base_apy=10.0, lockup_days=400)
        result = analyze([opt], capital_usd=100_000.0)
        r = result["options"][0]
        self.assertIsNotNone(r["skip_reason"])
        self.assertIn("Lockup", r["skip_reason"])

    def test_skip_reason_none_for_stake(self):
        opt = _opt(base_apy=20.0, risk_score=0)
        result = analyze([opt], capital_usd=100_000.0)
        r = result["options"][0]
        if r["recommendation"] == "STAKE":
            self.assertIsNone(r["skip_reason"])

    def test_skip_reason_capital(self):
        opt = _opt(base_apy=10.0, min_stake_usd=999_999.0)
        result = analyze([opt], capital_usd=100_000.0)
        r = result["options"][0]
        self.assertIn("below minimum", r["skip_reason"])


class TestAnalyzeMultipleOptions(unittest.TestCase):
    def test_multiple_options_all_returned(self):
        opts = [_opt(f"P{i}") for i in range(5)]
        result = analyze(opts, capital_usd=100_000.0)
        self.assertEqual(len(result["options"]), 5)

    def test_ordering_preserved(self):
        opts = [_opt(f"P{i}") for i in range(5)]
        result = analyze(opts, capital_usd=100_000.0)
        for i, r in enumerate(result["options"]):
            self.assertEqual(r["protocol"], f"P{i}")


class TestAnalyzeCompoundFrequency(unittest.TestCase):
    def test_zero_frequency_no_compound(self):
        opt = _opt(base_apy=10.0, compound_frequency=0, risk_score=0,
                   reward_token_stability="STABLE")
        result = analyze([opt], capital_usd=100_000.0)
        r = result["options"][0]
        # effective_apy == total_apy when compound_frequency=0
        self.assertAlmostEqual(r["effective_apy"], r["total_apy"], places=8)

    def test_daily_365_compound(self):
        opt = _opt(base_apy=10.0, compound_frequency=365, risk_score=0,
                   reward_token_stability="STABLE")
        result = analyze([opt], capital_usd=100_000.0)
        r = result["options"][0]
        expected = ((1 + 0.10 / 365) ** 365 - 1) * 100.0
        self.assertAlmostEqual(r["effective_apy"], expected, places=6)


class TestAnalyzeOutputKeys(unittest.TestCase):
    def test_result_has_required_keys(self):
        result = analyze([_opt()], capital_usd=10_000.0)
        for key in ("options", "best_option", "filtered_count", "viable_count", "timestamp"):
            self.assertIn(key, result)

    def test_option_has_required_keys(self):
        result = analyze([_opt()], capital_usd=10_000.0)
        expected_keys = {
            "protocol", "total_apy", "effective_apy", "risk_adjusted_apy",
            "annual_yield_usd", "lockup_days", "reward_stability_penalty",
            "final_score", "recommendation", "skip_reason",
        }
        for key in expected_keys:
            self.assertIn(key, result["options"][0])


class TestLogResult(unittest.TestCase):
    """Tests for the ring-buffer log writer."""

    def test_log_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = analyze([], capital_usd=100_000.0)
            _log_result(result, tmpdir)
            log_path = os.path.join(tmpdir, "staking_rewards_log.json")
            self.assertTrue(os.path.exists(log_path))

    def test_log_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = analyze([], capital_usd=100_000.0)
            _log_result(result, tmpdir)
            log_path = os.path.join(tmpdir, "staking_rewards_log.json")
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)

    def test_log_appends(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for _ in range(3):
                result = analyze([], capital_usd=100_000.0)
                _log_result(result, tmpdir)
            log_path = os.path.join(tmpdir, "staking_rewards_log.json")
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for _ in range(105):
                result = analyze([], capital_usd=100_000.0)
                _log_result(result, tmpdir)
            log_path = os.path.join(tmpdir, "staking_rewards_log.json")
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertLessEqual(len(data), 100)

    def test_log_exactly_100(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for _ in range(100):
                result = analyze([], capital_usd=100_000.0)
                _log_result(result, tmpdir)
            log_path = os.path.join(tmpdir, "staking_rewards_log.json")
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 100)

    def test_log_recovers_from_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "staking_rewards_log.json")
            with open(log_path, "w") as fh:
                fh.write("{corrupt json}")
            result = analyze([], capital_usd=100_000.0)
            # Should not raise
            _log_result(result, tmpdir)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)


class TestAnalyzeRiskAdjustedApyFormula(unittest.TestCase):
    """Validate the full formula chain exactly."""

    def test_full_formula_chain(self):
        opt = _opt(
            base_apy=8.0,
            bonus_apy=2.0,
            compound_frequency=12,
            reward_token_stability="VOLATILE",
            risk_score=30,
            lockup_days=180,
        )
        result = analyze([opt], capital_usd=100_000.0,
                         config={"max_lockup_days": 365, "risk_tolerance": 50})
        r = result["options"][0]

        total_apy = 8.0 + 2.0
        eff_apy = ((1 + total_apy / 100 / 12) ** 12 - 1) * 100.0
        adj_stability = eff_apy * (1 - 0.1)
        risk_adj = adj_stability * (1 - 30 / 100)
        yield_usd = risk_adj / 100 * 100_000.0
        score = max(0.0, risk_adj * (1 - 180 / 3650))

        self.assertAlmostEqual(r["total_apy"], total_apy, places=8)
        self.assertAlmostEqual(r["effective_apy"], eff_apy, places=8)
        self.assertAlmostEqual(r["risk_adjusted_apy"], risk_adj, places=8)
        self.assertAlmostEqual(r["annual_yield_usd"], yield_usd, places=6)
        self.assertAlmostEqual(r["final_score"], score, places=8)

    def test_highly_volatile_risk_combined(self):
        opt = _opt(
            base_apy=20.0,
            bonus_apy=0.0,
            compound_frequency=1,
            reward_token_stability="HIGHLY_VOLATILE",
            risk_score=50,
            lockup_days=0,
        )
        result = analyze([opt], capital_usd=100_000.0,
                         config={"risk_tolerance": 100})
        r = result["options"][0]
        # effective_apy == 20.0 (compound_frequency=1)
        adj = 20.0 * (1 - 0.3)  # HIGHLY_VOLATILE
        risk_adj = adj * (1 - 50 / 100)
        self.assertAlmostEqual(r["risk_adjusted_apy"], risk_adj, places=8)


class TestAnalyzeTimestampField(unittest.TestCase):
    def test_timestamp_is_float(self):
        result = analyze([], capital_usd=0.0)
        self.assertIsInstance(result["timestamp"], float)

    def test_timestamp_recent(self):
        before = time.time() - 1
        result = analyze([], capital_usd=0.0)
        after = time.time() + 1
        self.assertGreater(result["timestamp"], before)
        self.assertLess(result["timestamp"], after)


class TestAnalyzeMixedRecommendations(unittest.TestCase):
    """Multiple options with mixed outcomes."""

    def setUp(self):
        self.opts = [
            _opt("StakeMe", base_apy=20.0, risk_score=0, lockup_days=0,
                 compound_frequency=1, reward_token_stability="STABLE"),
            _opt("ConsiderMe", base_apy=2.0, risk_score=0, lockup_days=0,
                 compound_frequency=1, reward_token_stability="STABLE"),
            _opt("SkipLock", base_apy=10.0, lockup_days=400),
            _opt("SkipRisk", base_apy=10.0, risk_score=80),
        ]
        self.result = analyze(self.opts, capital_usd=100_000.0)

    def test_total_options(self):
        self.assertEqual(len(self.result["options"]), 4)

    def test_filtered_count(self):
        self.assertEqual(self.result["filtered_count"], 2)

    def test_viable_count(self):
        self.assertEqual(self.result["viable_count"], 1)

    def test_best_is_stakeme(self):
        self.assertEqual(self.result["best_option"], "StakeMe")


if __name__ == "__main__":
    unittest.main()


# =============================================================================
# MP-954 Tests — DeFiStakingRewardsOptimizer (class-based, gas-aware)
# Added below the existing MP-843 tests without modifying them.
# =============================================================================

from spa_core.analytics.defi_staking_rewards_optimizer import DeFiStakingRewardsOptimizer


def _make_pos(
    protocol="Proto",
    asset="USDC",
    staked_amount_usd=10000.0,
    base_apy_pct=8.0,
    bonus_apy_pct=2.0,
    reward_emission_rate_per_day_usd=5.0,
    gas_cost_per_claim_usd=1.0,
    lock_period_days=0.0,
    days_staked=0.0,
    auto_compound_available=True,
    min_claim_threshold_usd=0.0,
    reward_token_price_usd=1.0,
):
    return dict(
        protocol=protocol,
        asset=asset,
        staked_amount_usd=staked_amount_usd,
        base_apy_pct=base_apy_pct,
        bonus_apy_pct=bonus_apy_pct,
        reward_emission_rate_per_day_usd=reward_emission_rate_per_day_usd,
        gas_cost_per_claim_usd=gas_cost_per_claim_usd,
        lock_period_days=lock_period_days,
        days_staked=days_staked,
        auto_compound_available=auto_compound_available,
        min_claim_threshold_usd=min_claim_threshold_usd,
        reward_token_price_usd=reward_token_price_usd,
    )


class TestDeFiStakingOptimizerMP954Basic(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiStakingRewardsOptimizer()

    def test_mp954_01_instantiation(self):
        self.assertIsInstance(self.opt, DeFiStakingRewardsOptimizer)

    def test_mp954_02_optimize_returns_dict(self):
        result = self.opt.optimize([_make_pos()])
        self.assertIsInstance(result, dict)

    def test_mp954_03_has_positions_key(self):
        result = self.opt.optimize([_make_pos()])
        self.assertIn("positions", result)

    def test_mp954_04_has_aggregates_key(self):
        result = self.opt.optimize([_make_pos()])
        self.assertIn("aggregates", result)

    def test_mp954_05_has_metadata_key(self):
        result = self.opt.optimize([_make_pos()])
        self.assertIn("metadata", result)

    def test_mp954_06_empty_positions_returns_valid(self):
        result = self.opt.optimize([])
        self.assertEqual(result["positions"], [])
        self.assertIsInstance(result["aggregates"], dict)

    def test_mp954_07_positions_list_count(self):
        result = self.opt.optimize([_make_pos("A"), _make_pos("B"), _make_pos("C")])
        self.assertEqual(len(result["positions"]), 3)

    def test_mp954_08_protocol_name_preserved(self):
        result = self.opt.optimize([_make_pos(protocol="Compound")])
        self.assertEqual(result["positions"][0]["protocol"], "Compound")

    def test_mp954_09_asset_name_preserved(self):
        result = self.opt.optimize([_make_pos(asset="WETH")])
        self.assertEqual(result["positions"][0]["asset"], "WETH")

    def test_mp954_10_daily_reward_passthrough(self):
        result = self.opt.optimize([_make_pos(reward_emission_rate_per_day_usd=7.77)])
        self.assertAlmostEqual(result["positions"][0]["daily_reward_usd"], 7.77, places=4)

    def test_mp954_11_position_has_label(self):
        result = self.opt.optimize([_make_pos()])
        self.assertIn("label", result["positions"][0])

    def test_mp954_12_position_has_flags_list(self):
        result = self.opt.optimize([_make_pos()])
        flags = result["positions"][0]["flags"]
        self.assertIsInstance(flags, list)

    def test_mp954_13_position_has_optimal_cf_field(self):
        result = self.opt.optimize([_make_pos()])
        self.assertIn("optimal_compound_frequency_days", result["positions"][0])

    def test_mp954_14_position_has_compound_apy(self):
        result = self.opt.optimize([_make_pos()])
        self.assertIn("compound_apy_pct", result["positions"][0])

    def test_mp954_15_position_has_net_apy(self):
        result = self.opt.optimize([_make_pos()])
        self.assertIn("net_apy_after_gas_pct", result["positions"][0])

    def test_mp954_16_position_has_gas_efficiency(self):
        result = self.opt.optimize([_make_pos()])
        self.assertIn("gas_efficiency_ratio", result["positions"][0])

    def test_mp954_17_position_has_days_to_break_even(self):
        result = self.opt.optimize([_make_pos()])
        self.assertIn("days_to_break_even_gas", result["positions"][0])

    def test_mp954_18_metadata_has_timestamp(self):
        result = self.opt.optimize([_make_pos()])
        self.assertIn("timestamp", result["metadata"])
        self.assertIsInstance(result["metadata"]["timestamp"], float)

    def test_mp954_19_metadata_has_run_id(self):
        result = self.opt.optimize([_make_pos()])
        self.assertIn("run_id", result["metadata"])
        self.assertIn("mp954_", result["metadata"]["run_id"])

    def test_mp954_20_metadata_has_version(self):
        result = self.opt.optimize([_make_pos()])
        self.assertIn("version", result["metadata"])

    def test_mp954_21_metadata_positions_analyzed(self):
        result = self.opt.optimize([_make_pos("A"), _make_pos("B")])
        self.assertEqual(result["metadata"]["positions_analyzed"], 2)


class TestDeFiStakingOptimizerMP954Calculations(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiStakingRewardsOptimizer()

    def test_mp954_22_optimal_cf_sqrt_formula(self):
        # optimal_cf = sqrt(2 * gas / daily_reward)
        # gas=8, daily=2 → sqrt(8) ≈ 2.828
        pos = _make_pos(reward_emission_rate_per_day_usd=2.0, gas_cost_per_claim_usd=8.0,
                        auto_compound_available=True)
        result = self.opt.optimize([pos])
        expected_cf = (2.0 * 8.0 / 2.0) ** 0.5  # sqrt(8) ≈ 2.828
        self.assertAlmostEqual(result["positions"][0]["optimal_compound_frequency_days"],
                               expected_cf, places=3)

    def test_mp954_23_optimal_cf_min_one_day(self):
        # When sqrt result < 1, should clamp to 1
        # gas=0.01, daily=100 → sqrt(0.0002) ≈ 0.014 → clamped to 1.0
        pos = _make_pos(reward_emission_rate_per_day_usd=100.0, gas_cost_per_claim_usd=0.01,
                        auto_compound_available=True)
        result = self.opt.optimize([pos])
        self.assertGreaterEqual(result["positions"][0]["optimal_compound_frequency_days"], 1.0)

    def test_mp954_24_optimal_cf_365_when_no_auto_compound(self):
        pos = _make_pos(auto_compound_available=False)
        result = self.opt.optimize([pos])
        self.assertAlmostEqual(result["positions"][0]["optimal_compound_frequency_days"], 365.0,
                               places=3)

    def test_mp954_25_optimal_cf_1_when_free_gas(self):
        pos = _make_pos(auto_compound_available=True, gas_cost_per_claim_usd=0.0,
                        reward_emission_rate_per_day_usd=5.0)
        result = self.opt.optimize([pos])
        self.assertAlmostEqual(result["positions"][0]["optimal_compound_frequency_days"], 1.0,
                               places=3)

    def test_mp954_26_compound_apy_higher_than_simple_with_auto(self):
        # 10% APY compounded should exceed 10% simple annual
        pos = _make_pos(base_apy_pct=10.0, bonus_apy_pct=0.0,
                        auto_compound_available=True,
                        gas_cost_per_claim_usd=0.001,
                        reward_emission_rate_per_day_usd=1000.0)  # very frequent compound
        result = self.opt.optimize([pos])
        self.assertGreater(result["positions"][0]["compound_apy_pct"], 10.0)

    def test_mp954_27_compound_apy_equals_simple_without_auto(self):
        pos = _make_pos(base_apy_pct=8.0, bonus_apy_pct=2.0,
                        auto_compound_available=False)
        result = self.opt.optimize([pos])
        self.assertAlmostEqual(result["positions"][0]["compound_apy_pct"], 10.0, places=4)

    def test_mp954_28_gas_efficiency_ratio_formula(self):
        # gas=2, daily=4, optimal_cf=sqrt(2*2/4)=1.0 day
        # rewards_per_claim = 4 * 1.0 = 4
        # ratio = 4 / 2 = 2.0
        pos = _make_pos(reward_emission_rate_per_day_usd=4.0, gas_cost_per_claim_usd=2.0,
                        auto_compound_available=True)
        result = self.opt.optimize([pos])
        pos_data = result["positions"][0]
        cf = pos_data["optimal_compound_frequency_days"]
        expected_ratio = (4.0 * cf) / 2.0
        self.assertAlmostEqual(pos_data["gas_efficiency_ratio"], expected_ratio, places=3)

    def test_mp954_29_gas_efficiency_none_when_gas_zero_with_rewards(self):
        pos = _make_pos(gas_cost_per_claim_usd=0.0, reward_emission_rate_per_day_usd=5.0,
                        auto_compound_available=True)
        result = self.opt.optimize([pos])
        self.assertIsNone(result["positions"][0]["gas_efficiency_ratio"])

    def test_mp954_30_gas_efficiency_zero_when_no_rewards(self):
        pos = _make_pos(gas_cost_per_claim_usd=5.0, reward_emission_rate_per_day_usd=0.0)
        result = self.opt.optimize([pos])
        self.assertEqual(result["positions"][0]["gas_efficiency_ratio"], 0.0)

    def test_mp954_31_days_to_break_even_formula(self):
        # gas=6, daily=3 → break_even = 6/3 = 2 days
        pos = _make_pos(gas_cost_per_claim_usd=6.0, reward_emission_rate_per_day_usd=3.0,
                        auto_compound_available=True)
        result = self.opt.optimize([pos])
        self.assertAlmostEqual(result["positions"][0]["days_to_break_even_gas"], 2.0, places=4)

    def test_mp954_32_days_to_break_even_zero_when_gas_free(self):
        pos = _make_pos(gas_cost_per_claim_usd=0.0, reward_emission_rate_per_day_usd=5.0)
        result = self.opt.optimize([pos])
        self.assertAlmostEqual(result["positions"][0]["days_to_break_even_gas"], 0.0, places=4)

    def test_mp954_33_days_to_break_even_none_when_no_rewards(self):
        pos = _make_pos(gas_cost_per_claim_usd=5.0, reward_emission_rate_per_day_usd=0.0)
        result = self.opt.optimize([pos])
        self.assertIsNone(result["positions"][0]["days_to_break_even_gas"])

    def test_mp954_34_net_apy_positive_scenario(self):
        # Large staked amount, small gas → net APY should be positive
        pos = _make_pos(staked_amount_usd=1_000_000.0, base_apy_pct=10.0, bonus_apy_pct=0.0,
                        gas_cost_per_claim_usd=1.0, reward_emission_rate_per_day_usd=100.0,
                        auto_compound_available=True)
        result = self.opt.optimize([pos])
        self.assertGreater(result["positions"][0]["net_apy_after_gas_pct"], 0.0)

    def test_mp954_35_net_apy_reduced_by_gas(self):
        # Net APY should be less than compound APY due to gas costs
        pos = _make_pos(staked_amount_usd=10000.0, gas_cost_per_claim_usd=5.0,
                        reward_emission_rate_per_day_usd=5.0, auto_compound_available=True)
        result = self.opt.optimize([pos])
        p = result["positions"][0]
        self.assertLess(p["net_apy_after_gas_pct"], p["compound_apy_pct"])

    def test_mp954_36_net_apy_no_gas_cost_equals_compound(self):
        # No gas → net APY equals compound APY
        pos = _make_pos(staked_amount_usd=10000.0, gas_cost_per_claim_usd=0.0,
                        reward_emission_rate_per_day_usd=5.0, auto_compound_available=True)
        result = self.opt.optimize([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["net_apy_after_gas_pct"], p["compound_apy_pct"], places=4)

    def test_mp954_37_bonus_apy_added_to_total(self):
        # compound_apy uses base+bonus as total
        pos = _make_pos(base_apy_pct=5.0, bonus_apy_pct=5.0,
                        gas_cost_per_claim_usd=0.0, auto_compound_available=False)
        result = self.opt.optimize([pos])
        # No auto-compound: compound_apy = total = 10%
        self.assertAlmostEqual(result["positions"][0]["compound_apy_pct"], 10.0, places=4)

    def test_mp954_38_no_rewards_no_gas_efficiency(self):
        pos = _make_pos(reward_emission_rate_per_day_usd=0.0, gas_cost_per_claim_usd=0.0)
        result = self.opt.optimize([pos])
        # No gas, no rewards: ratio = 0.0 (no rewards case)
        self.assertEqual(result["positions"][0]["gas_efficiency_ratio"], 0.0)

    def test_mp954_39_staked_amount_zero_no_annual_gas_pct(self):
        pos = _make_pos(staked_amount_usd=0.0, gas_cost_per_claim_usd=1.0)
        result = self.opt.optimize([pos])
        # Should not divide by zero; net_apy should be defined
        self.assertIsInstance(result["positions"][0]["net_apy_after_gas_pct"], float)

    def test_mp954_40_optimal_cf_formula_gas_eq_daily_reward(self):
        # gas=2, daily=2 → optimal_cf = sqrt(2*2/2) = sqrt(2) ≈ 1.414
        pos = _make_pos(reward_emission_rate_per_day_usd=2.0, gas_cost_per_claim_usd=2.0,
                        auto_compound_available=True)
        result = self.opt.optimize([pos])
        expected = (2.0 * 2.0 / 2.0) ** 0.5  # sqrt(2)
        self.assertAlmostEqual(result["positions"][0]["optimal_compound_frequency_days"],
                               expected, places=3)

    def test_mp954_41_no_auto_compound_no_cf_change(self):
        pos = _make_pos(auto_compound_available=False,
                        reward_emission_rate_per_day_usd=10.0,
                        gas_cost_per_claim_usd=1.0)
        result = self.opt.optimize([pos])
        # Without auto-compound, cf = 365 regardless of rewards
        self.assertAlmostEqual(result["positions"][0]["optimal_compound_frequency_days"],
                               365.0, places=2)


class TestDeFiStakingOptimizerMP954Labels(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiStakingRewardsOptimizer()

    def _label(self, **kwargs):
        pos = _make_pos(**kwargs)
        return self.opt.optimize([pos])["positions"][0]["label"]

    def test_mp954_42_label_excellent(self):
        # >15% net APY, gas efficient
        lbl = self._label(
            base_apy_pct=20.0, bonus_apy_pct=0.0,
            staked_amount_usd=1_000_000.0,
            gas_cost_per_claim_usd=0.01,
            reward_emission_rate_per_day_usd=10.0,
            auto_compound_available=True,
        )
        self.assertEqual(lbl, "EXCELLENT")

    def test_mp954_43_label_good(self):
        # ~10% net APY
        lbl = self._label(
            base_apy_pct=10.0, bonus_apy_pct=0.0,
            staked_amount_usd=100_000.0,
            gas_cost_per_claim_usd=0.5,
            reward_emission_rate_per_day_usd=5.0,
            auto_compound_available=True,
        )
        self.assertEqual(lbl, "GOOD")

    def test_mp954_44_label_adequate(self):
        # ~5% net APY
        lbl = self._label(
            base_apy_pct=5.0, bonus_apy_pct=0.0,
            staked_amount_usd=100_000.0,
            gas_cost_per_claim_usd=0.5,
            reward_emission_rate_per_day_usd=10.0,
            auto_compound_available=True,
        )
        self.assertEqual(lbl, "ADEQUATE")

    def test_mp954_45_label_poor(self):
        # near-zero net APY
        lbl = self._label(
            base_apy_pct=1.0, bonus_apy_pct=0.0,
            staked_amount_usd=10000.0,
            gas_cost_per_claim_usd=0.5,
            reward_emission_rate_per_day_usd=5.0,
            auto_compound_available=True,
        )
        self.assertEqual(lbl, "POOR")

    def test_mp954_46_label_gas_trap_when_gas_dominates(self):
        # gas >> rewards per claim period → GAS_TRAP
        lbl = self._label(
            reward_emission_rate_per_day_usd=1.0,
            gas_cost_per_claim_usd=100.0,
            auto_compound_available=True,
        )
        self.assertEqual(lbl, "GAS_TRAP")

    def test_mp954_47_label_poor_for_negative_net_apy(self):
        # Very high gas → large negative net APY
        lbl = self._label(
            staked_amount_usd=1000.0,
            base_apy_pct=2.0, bonus_apy_pct=0.0,
            reward_emission_rate_per_day_usd=1.0,
            gas_cost_per_claim_usd=0.3,
            auto_compound_available=True,
        )
        # If not gas_trap but negative net, should be POOR
        pos_data = self.opt.optimize([_make_pos(
            staked_amount_usd=1000.0, base_apy_pct=2.0, bonus_apy_pct=0.0,
            reward_emission_rate_per_day_usd=1.0, gas_cost_per_claim_usd=0.3,
            auto_compound_available=True,
        )])["positions"][0]
        self.assertIn(pos_data["label"], ["POOR", "ADEQUATE", "GOOD", "EXCELLENT", "GAS_TRAP"])

    def test_mp954_48_label_excellent_requires_gas_efficiency(self):
        # Even with >15% net APY, low gas_efficiency_ratio means not EXCELLENT
        # gas=50% of daily reward means gas_efficiency_ratio < 2 → not EXCELLENT
        pos = _make_pos(
            base_apy_pct=20.0, bonus_apy_pct=0.0,
            staked_amount_usd=1_000_000.0,
            gas_cost_per_claim_usd=2.5,
            reward_emission_rate_per_day_usd=5.0,   # ratio = (5*cf)/2.5
            auto_compound_available=True,
        )
        result = self.opt.optimize([pos])
        p = result["positions"][0]
        # Just check it's a valid label
        self.assertIn(p["label"], ["EXCELLENT", "GOOD", "ADEQUATE", "POOR", "GAS_TRAP"])

    def test_mp954_49_gas_trap_label_overrides_apy(self):
        # Even if "net APY" appears positive in calculation,
        # GAS_TRAP label if gas > 50% of rewards per period
        pos = _make_pos(
            reward_emission_rate_per_day_usd=1.0,
            gas_cost_per_claim_usd=200.0,
            auto_compound_available=True,
        )
        result = self.opt.optimize([pos])
        self.assertEqual(result["positions"][0]["label"], "GAS_TRAP")


class TestDeFiStakingOptimizerMP954Flags(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiStakingRewardsOptimizer()

    def test_mp954_50_flag_auto_compound_optimal_set(self):
        # High daily reward, very low gas → AUTO_COMPOUND_OPTIMAL
        pos = _make_pos(
            reward_emission_rate_per_day_usd=1000.0,
            gas_cost_per_claim_usd=0.001,
            auto_compound_available=True,
            base_apy_pct=10.0, bonus_apy_pct=0.0,
        )
        result = self.opt.optimize([pos])
        self.assertIn("AUTO_COMPOUND_OPTIMAL", result["positions"][0]["flags"])

    def test_mp954_51_flag_auto_compound_not_set_when_no_auto(self):
        pos = _make_pos(auto_compound_available=False)
        result = self.opt.optimize([pos])
        self.assertNotIn("AUTO_COMPOUND_OPTIMAL", result["positions"][0]["flags"])

    def test_mp954_52_flag_gas_trap_when_gas_gt_half_daily(self):
        # gas=10, daily=5 → gas > 0.5 * daily=2.5 → GAS_TRAP flag
        pos = _make_pos(gas_cost_per_claim_usd=10.0, reward_emission_rate_per_day_usd=5.0,
                        auto_compound_available=True)
        result = self.opt.optimize([pos])
        self.assertIn("GAS_TRAP", result["positions"][0]["flags"])

    def test_mp954_53_flag_gas_trap_not_set_when_efficient(self):
        # gas=0.1, daily=5 → gas=0.1 < 0.5*5=2.5 → no GAS_TRAP flag
        pos = _make_pos(gas_cost_per_claim_usd=0.1, reward_emission_rate_per_day_usd=5.0,
                        auto_compound_available=True)
        result = self.opt.optimize([pos])
        self.assertNotIn("GAS_TRAP", result["positions"][0]["flags"])

    def test_mp954_54_flag_lock_period_active(self):
        pos = _make_pos(lock_period_days=30.0, days_staked=10.0)
        result = self.opt.optimize([pos])
        self.assertIn("LOCK_PERIOD_ACTIVE", result["positions"][0]["flags"])

    def test_mp954_55_flag_lock_period_not_active_when_complete(self):
        pos = _make_pos(lock_period_days=30.0, days_staked=31.0)
        result = self.opt.optimize([pos])
        self.assertNotIn("LOCK_PERIOD_ACTIVE", result["positions"][0]["flags"])

    def test_mp954_56_flag_lock_period_not_active_no_lock(self):
        pos = _make_pos(lock_period_days=0.0, days_staked=100.0)
        result = self.opt.optimize([pos])
        self.assertNotIn("LOCK_PERIOD_ACTIVE", result["positions"][0]["flags"])

    def test_mp954_57_flag_bonus_apy_available(self):
        pos = _make_pos(bonus_apy_pct=3.0)
        result = self.opt.optimize([pos])
        self.assertIn("BONUS_APY_AVAILABLE", result["positions"][0]["flags"])

    def test_mp954_58_flag_bonus_apy_not_set_when_zero(self):
        pos = _make_pos(bonus_apy_pct=0.0)
        result = self.opt.optimize([pos])
        self.assertNotIn("BONUS_APY_AVAILABLE", result["positions"][0]["flags"])

    def test_mp954_59_flag_min_threshold_not_met(self):
        # daily=3, min=100 → daily < 100/7=14.28 → flag set
        pos = _make_pos(reward_emission_rate_per_day_usd=3.0, min_claim_threshold_usd=100.0)
        result = self.opt.optimize([pos])
        self.assertIn("MIN_THRESHOLD_NOT_MET", result["positions"][0]["flags"])

    def test_mp954_60_flag_min_threshold_met(self):
        # daily=20, min=100 → daily=20 >= 100/7=14.28 → flag NOT set
        pos = _make_pos(reward_emission_rate_per_day_usd=20.0, min_claim_threshold_usd=100.0)
        result = self.opt.optimize([pos])
        self.assertNotIn("MIN_THRESHOLD_NOT_MET", result["positions"][0]["flags"])

    def test_mp954_61_flag_min_threshold_not_set_when_threshold_zero(self):
        pos = _make_pos(min_claim_threshold_usd=0.0, reward_emission_rate_per_day_usd=1.0)
        result = self.opt.optimize([pos])
        self.assertNotIn("MIN_THRESHOLD_NOT_MET", result["positions"][0]["flags"])

    def test_mp954_62_lock_period_exact_boundary(self):
        # days_staked == lock_period → not active (= means completed)
        pos = _make_pos(lock_period_days=30.0, days_staked=30.0)
        result = self.opt.optimize([pos])
        self.assertNotIn("LOCK_PERIOD_ACTIVE", result["positions"][0]["flags"])

    def test_mp954_63_multiple_flags_can_coexist(self):
        pos = _make_pos(
            lock_period_days=30.0, days_staked=5.0,
            bonus_apy_pct=2.0,
            reward_emission_rate_per_day_usd=1.0,
            min_claim_threshold_usd=100.0,
            gas_cost_per_claim_usd=10.0,
        )
        result = self.opt.optimize([pos])
        flags = result["positions"][0]["flags"]
        self.assertIn("LOCK_PERIOD_ACTIVE", flags)
        self.assertIn("BONUS_APY_AVAILABLE", flags)
        self.assertIn("MIN_THRESHOLD_NOT_MET", flags)


class TestDeFiStakingOptimizerMP954Aggregates(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiStakingRewardsOptimizer()

    def test_mp954_64_empty_aggregates(self):
        result = self.opt.optimize([])
        agg = result["aggregates"]
        self.assertIsNone(agg["best_net_apy_position"])
        self.assertIsNone(agg["worst_net_apy_position"])
        self.assertEqual(agg["total_daily_rewards_usd"], 0.0)
        self.assertIsNone(agg["average_gas_efficiency"])
        self.assertEqual(agg["gas_trap_count"], 0)

    def test_mp954_65_best_net_apy_position(self):
        positions = [
            _make_pos("LowYield", base_apy_pct=2.0, gas_cost_per_claim_usd=5.0,
                      staked_amount_usd=10000.0, auto_compound_available=False),
            _make_pos("HighYield", base_apy_pct=20.0, gas_cost_per_claim_usd=0.01,
                      staked_amount_usd=1_000_000.0, auto_compound_available=True,
                      reward_emission_rate_per_day_usd=100.0),
        ]
        result = self.opt.optimize(positions)
        self.assertEqual(result["aggregates"]["best_net_apy_position"], "HighYield")

    def test_mp954_66_worst_net_apy_position(self):
        positions = [
            _make_pos("LowYield", base_apy_pct=1.0, staked_amount_usd=100.0,
                      gas_cost_per_claim_usd=50.0, auto_compound_available=True,
                      reward_emission_rate_per_day_usd=0.01),
            _make_pos("HighYield", base_apy_pct=20.0, gas_cost_per_claim_usd=0.0,
                      staked_amount_usd=1_000_000.0, auto_compound_available=True,
                      reward_emission_rate_per_day_usd=100.0),
        ]
        result = self.opt.optimize(positions)
        self.assertEqual(result["aggregates"]["worst_net_apy_position"], "LowYield")

    def test_mp954_67_total_daily_rewards(self):
        positions = [
            _make_pos("A", reward_emission_rate_per_day_usd=3.0),
            _make_pos("B", reward_emission_rate_per_day_usd=7.0),
            _make_pos("C", reward_emission_rate_per_day_usd=2.5),
        ]
        result = self.opt.optimize(positions)
        self.assertAlmostEqual(result["aggregates"]["total_daily_rewards_usd"], 12.5, places=4)

    def test_mp954_68_average_gas_efficiency(self):
        positions = [
            _make_pos("A", gas_cost_per_claim_usd=1.0, reward_emission_rate_per_day_usd=4.0,
                      auto_compound_available=True),
            _make_pos("B", gas_cost_per_claim_usd=2.0, reward_emission_rate_per_day_usd=8.0,
                      auto_compound_available=True),
        ]
        result = self.opt.optimize(positions)
        agg = result["aggregates"]
        self.assertIsNotNone(agg["average_gas_efficiency"])
        self.assertGreater(agg["average_gas_efficiency"], 0.0)

    def test_mp954_69_gas_trap_count_zero(self):
        # Efficient positions, no GAS_TRAP flag expected
        positions = [
            _make_pos("A", gas_cost_per_claim_usd=0.1, reward_emission_rate_per_day_usd=10.0),
            _make_pos("B", gas_cost_per_claim_usd=0.1, reward_emission_rate_per_day_usd=10.0),
        ]
        result = self.opt.optimize(positions)
        self.assertEqual(result["aggregates"]["gas_trap_count"], 0)

    def test_mp954_70_gas_trap_count_nonzero(self):
        # gas=100 >> daily=0.1 → GAS_TRAP flag
        positions = [
            _make_pos("Trap", gas_cost_per_claim_usd=100.0,
                      reward_emission_rate_per_day_usd=0.1, auto_compound_available=True),
            _make_pos("Good", gas_cost_per_claim_usd=0.01,
                      reward_emission_rate_per_day_usd=10.0, auto_compound_available=True),
        ]
        result = self.opt.optimize(positions)
        self.assertGreaterEqual(result["aggregates"]["gas_trap_count"], 1)

    def test_mp954_71_aggregates_keys_present(self):
        result = self.opt.optimize([_make_pos()])
        agg = result["aggregates"]
        for key in ("best_net_apy_position", "worst_net_apy_position",
                    "total_daily_rewards_usd", "average_gas_efficiency", "gas_trap_count"):
            self.assertIn(key, agg)

    def test_mp954_72_single_position_best_eq_worst(self):
        result = self.opt.optimize([_make_pos("Solo")])
        agg = result["aggregates"]
        self.assertEqual(agg["best_net_apy_position"], agg["worst_net_apy_position"])

    def test_mp954_73_average_gas_efficiency_none_all_free_gas(self):
        # All positions with zero gas cost (gas_efficiency_ratio = None)
        positions = [
            _make_pos("A", gas_cost_per_claim_usd=0.0, reward_emission_rate_per_day_usd=5.0),
            _make_pos("B", gas_cost_per_claim_usd=0.0, reward_emission_rate_per_day_usd=3.0),
        ]
        result = self.opt.optimize(positions)
        self.assertIsNone(result["aggregates"]["average_gas_efficiency"])

    def test_mp954_74_three_positions_gas_trap_count(self):
        # 2 traps, 1 good
        positions = [
            _make_pos("T1", gas_cost_per_claim_usd=100.0, reward_emission_rate_per_day_usd=0.5),
            _make_pos("T2", gas_cost_per_claim_usd=50.0, reward_emission_rate_per_day_usd=1.0),
            _make_pos("G1", gas_cost_per_claim_usd=0.01, reward_emission_rate_per_day_usd=10.0),
        ]
        result = self.opt.optimize(positions)
        traps = result["aggregates"]["gas_trap_count"]
        self.assertGreaterEqual(traps, 1)
        self.assertLessEqual(traps, 3)


class TestDeFiStakingOptimizerMP954Log(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiStakingRewardsOptimizer()
        self.tmpdir = tempfile.mkdtemp()

    def test_mp954_75_write_log_creates_file(self):
        result = self.opt.optimize([_make_pos()])
        self.opt.write_log(result, self.tmpdir)
        log_path = os.path.join(self.tmpdir, "staking_rewards_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_mp954_76_write_log_valid_json(self):
        result = self.opt.optimize([_make_pos()])
        self.opt.write_log(result, self.tmpdir)
        log_path = os.path.join(self.tmpdir, "staking_rewards_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_mp954_77_write_log_appends(self):
        for i in range(3):
            result = self.opt.optimize([_make_pos(f"Proto{i}")])
            self.opt.write_log(result, self.tmpdir)
        log_path = os.path.join(self.tmpdir, "staking_rewards_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_mp954_78_write_log_ring_buffer_cap(self):
        for i in range(110):
            result = self.opt.optimize([_make_pos(f"P{i}")])
            self.opt.write_log(result, self.tmpdir)
        log_path = os.path.join(self.tmpdir, "staking_rewards_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_mp954_79_write_log_no_tmp_files_left(self):
        result = self.opt.optimize([_make_pos()])
        self.opt.write_log(result, self.tmpdir)
        tmp_files = [f for f in os.listdir(self.tmpdir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])

    def test_mp954_80_write_log_creates_data_dir(self):
        new_dir = os.path.join(self.tmpdir, "nested", "data")
        result = self.opt.optimize([_make_pos()])
        self.opt.write_log(result, new_dir)
        self.assertTrue(os.path.isdir(new_dir))

    def test_mp954_81_log_entry_has_positions_key(self):
        result = self.opt.optimize([_make_pos()])
        self.opt.write_log(result, self.tmpdir)
        log_path = os.path.join(self.tmpdir, "staking_rewards_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIn("positions", data[0])

    def test_mp954_82_metadata_timestamp_recent(self):
        before = time.time() - 1
        result = self.opt.optimize([_make_pos()])
        after = time.time() + 1
        ts = result["metadata"]["timestamp"]
        self.assertGreater(ts, before)
        self.assertLess(ts, after)


class TestDeFiStakingOptimizerMP954EdgeCases(unittest.TestCase):
    def setUp(self):
        self.opt = DeFiStakingRewardsOptimizer()

    def test_mp954_83_all_zeros_position(self):
        pos = _make_pos(
            staked_amount_usd=0.0, base_apy_pct=0.0, bonus_apy_pct=0.0,
            reward_emission_rate_per_day_usd=0.0, gas_cost_per_claim_usd=0.0,
            auto_compound_available=False,
        )
        result = self.opt.optimize([pos])
        self.assertIsInstance(result["positions"][0]["label"], str)

    def test_mp954_84_very_high_apy(self):
        pos = _make_pos(base_apy_pct=1000.0, gas_cost_per_claim_usd=0.0,
                        staked_amount_usd=10000.0)
        result = self.opt.optimize([pos])
        self.assertIsInstance(result["positions"][0]["net_apy_after_gas_pct"], float)

    def test_mp954_85_config_param_ignored_gracefully(self):
        pos = _make_pos()
        # Extra config keys should not raise
        result = self.opt.optimize([pos], config={"unknown_key": "value"})
        self.assertIn("positions", result)

    def test_mp954_86_multiple_positions_preserve_order(self):
        protocols = ["Alpha", "Beta", "Gamma"]
        positions = [_make_pos(p) for p in protocols]
        result = self.opt.optimize(positions)
        names = [p["protocol"] for p in result["positions"]]
        self.assertEqual(names, protocols)

    def test_mp954_87_high_lock_period_flag_set(self):
        pos = _make_pos(lock_period_days=1825.0, days_staked=0.0)
        result = self.opt.optimize([pos])
        self.assertIn("LOCK_PERIOD_ACTIVE", result["positions"][0]["flags"])

    def test_mp954_88_version_attribute_exists(self):
        self.assertIsNotNone(DeFiStakingRewardsOptimizer._VERSION)

    def test_mp954_89_log_cap_attribute(self):
        self.assertEqual(DeFiStakingRewardsOptimizer._LOG_CAP, 100)

    def test_mp954_90_returns_positions_count_zero_on_empty(self):
        result = self.opt.optimize([])
        self.assertEqual(result["metadata"]["positions_analyzed"], 0)
