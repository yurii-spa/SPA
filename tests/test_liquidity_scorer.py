"""tests/test_liquidity_scorer.py — MP-581 LiquidityScorer test suite.

Coverage: 90 test cases across 10 classes.

TestTVLScore           (8)  — TVL sub-score breakpoints
TestTierScore          (9)  — T1/T2/T3/unknown/object attr
TestRedemptionScore    (8)  — instant/batched/lock/unknown
TestAgeScore           (8)  — age breakpoints and defaults
TestAuditScore         (7)  — audit count breakpoints
TestScoreAdapter       (12) — full score_adapter integration
TestClassifyLiquidity  (10) — classify_liquidity string returns
TestScorePortfolio     (10) — score_portfolio weighted average + edge cases
TestGetLiquidityReport (13) — get_liquidity_report structure + content
TestEstimateExitTime   (12) — estimate_exit_time_days (tier, redemption, TVL)
TestImportHygiene       (3) — no forbidden imports; only stdlib

Total: 100 tests
"""

from __future__ import annotations

import os
import sys
import types
import unittest

# Make spa_core importable from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.analytics.liquidity_scorer import (
    LiquidityScorer,
    _safe_float,
    _normalise_tier,
    _normalise_redemption,
    _tiered_score,
    _TVL_TIERS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _adapter(
    tvl_usd=500_000_000,
    tier="T1",
    redemption_type="instant",
    protocol_age_days=1095,
    audit_count=4,
    protocol="test_proto",
) -> dict:
    """Build a fully-populated adapter dict."""
    return {
        "tvl_usd": tvl_usd,
        "tier": tier,
        "redemption_type": redemption_type,
        "protocol_age_days": protocol_age_days,
        "audit_count": audit_count,
        "protocol": protocol,
    }


def _make_obj(**kwargs):
    """Return a simple namespace object with the given attributes."""
    obj = types.SimpleNamespace(**kwargs)
    return obj


# ---------------------------------------------------------------------------
# TestTVLScore (8 tests)
# ---------------------------------------------------------------------------

class TestTVLScore(unittest.TestCase):
    """TVL sub-score: 0–30 pts based on piecewise thresholds."""

    def setUp(self):
        self.scorer = LiquidityScorer()

    def test_tvl_billion_gets_30(self):
        a = _adapter(tvl_usd=1_000_000_000)
        self.assertEqual(self.scorer._tvl_score(a), 30.0)

    def test_tvl_above_billion_capped_at_30(self):
        a = _adapter(tvl_usd=5_000_000_000)
        self.assertEqual(self.scorer._tvl_score(a), 30.0)

    def test_tvl_500m_gets_26(self):
        a = _adapter(tvl_usd=500_000_000)
        self.assertEqual(self.scorer._tvl_score(a), 26.0)

    def test_tvl_100m_gets_20(self):
        a = _adapter(tvl_usd=100_000_000)
        self.assertEqual(self.scorer._tvl_score(a), 20.0)

    def test_tvl_50m_gets_14(self):
        a = _adapter(tvl_usd=50_000_000)
        self.assertEqual(self.scorer._tvl_score(a), 14.0)

    def test_tvl_10m_gets_8(self):
        a = _adapter(tvl_usd=10_000_000)
        self.assertEqual(self.scorer._tvl_score(a), 8.0)

    def test_tvl_5m_gets_4(self):
        a = _adapter(tvl_usd=5_000_000)
        self.assertEqual(self.scorer._tvl_score(a), 4.0)

    def test_tvl_zero_gets_0(self):
        a = _adapter(tvl_usd=0)
        self.assertEqual(self.scorer._tvl_score(a), 0.0)


# ---------------------------------------------------------------------------
# TestTierScore (9 tests)
# ---------------------------------------------------------------------------

class TestTierScore(unittest.TestCase):
    """Tier sub-score: T1=25, T2=15, T3=5, unknown→5."""

    def setUp(self):
        self.scorer = LiquidityScorer()

    def test_t1_gets_25(self):
        self.assertEqual(self.scorer._tier_score(_adapter(tier="T1")), 25.0)

    def test_t2_gets_15(self):
        self.assertEqual(self.scorer._tier_score(_adapter(tier="T2")), 15.0)

    def test_t3_gets_5(self):
        self.assertEqual(self.scorer._tier_score(_adapter(tier="T3")), 5.0)

    def test_unknown_tier_falls_back_to_t3(self):
        self.assertEqual(self.scorer._tier_score(_adapter(tier="T4")), 5.0)

    def test_none_tier_falls_back_to_t3(self):
        a = _adapter(); a["tier"] = None
        self.assertEqual(self.scorer._tier_score(a), 5.0)

    def test_lowercase_t1(self):
        a = _adapter(tier="t1")
        self.assertEqual(self.scorer._tier_score(a), 25.0)

    def test_lowercase_t2(self):
        a = _adapter(tier="t2")
        self.assertEqual(self.scorer._tier_score(a), 15.0)

    def test_object_attribute_t1(self):
        obj = _make_obj(tier="T1", tvl_usd=100_000_000, redemption_type="instant",
                        protocol_age_days=730, audit_count=2)
        self.assertEqual(self.scorer._tier_score(obj), 25.0)

    def test_empty_string_tier_falls_back_to_t3(self):
        a = _adapter(tier="")
        self.assertEqual(self.scorer._tier_score(a), 5.0)


# ---------------------------------------------------------------------------
# TestRedemptionScore (8 tests)
# ---------------------------------------------------------------------------

class TestRedemptionScore(unittest.TestCase):
    """Redemption sub-score: instant=20, batched=10, lock=0."""

    def setUp(self):
        self.scorer = LiquidityScorer()

    def test_instant_gets_20(self):
        self.assertEqual(self.scorer._redemption_score(_adapter(redemption_type="instant")), 20.0)

    def test_batched_gets_10(self):
        self.assertEqual(self.scorer._redemption_score(_adapter(redemption_type="batched")), 10.0)

    def test_lock_gets_0(self):
        self.assertEqual(self.scorer._redemption_score(_adapter(redemption_type="lock")), 0.0)

    def test_unknown_redemption_falls_back_to_lock(self):
        a = _adapter(redemption_type="queue")
        self.assertEqual(self.scorer._redemption_score(a), 0.0)

    def test_none_redemption_falls_back_to_lock(self):
        a = _adapter(); a["redemption_type"] = None
        self.assertEqual(self.scorer._redemption_score(a), 0.0)

    def test_uppercase_instant(self):
        a = _adapter(redemption_type="INSTANT")
        self.assertEqual(self.scorer._redemption_score(a), 20.0)

    def test_uppercase_batched(self):
        a = _adapter(redemption_type="BATCHED")
        self.assertEqual(self.scorer._redemption_score(a), 10.0)

    def test_mixed_case_lock(self):
        a = _adapter(redemption_type="Lock")
        self.assertEqual(self.scorer._redemption_score(a), 0.0)


# ---------------------------------------------------------------------------
# TestAgeScore (8 tests)
# ---------------------------------------------------------------------------

class TestAgeScore(unittest.TestCase):
    """Age sub-score: breakpoints at 5yr/3yr/2yr/1yr/6mo."""

    def setUp(self):
        self.scorer = LiquidityScorer()

    def test_5yr_gets_15(self):
        a = _adapter(protocol_age_days=1825)
        self.assertEqual(self.scorer._age_score(a), 15.0)

    def test_3yr_gets_12(self):
        a = _adapter(protocol_age_days=1095)
        self.assertEqual(self.scorer._age_score(a), 12.0)

    def test_2yr_gets_9(self):
        a = _adapter(protocol_age_days=730)
        self.assertEqual(self.scorer._age_score(a), 9.0)

    def test_1yr_gets_6(self):
        a = _adapter(protocol_age_days=365)
        self.assertEqual(self.scorer._age_score(a), 6.0)

    def test_6mo_gets_3(self):
        a = _adapter(protocol_age_days=180)
        self.assertEqual(self.scorer._age_score(a), 3.0)

    def test_less_than_6mo_gets_0(self):
        a = _adapter(protocol_age_days=90)
        self.assertEqual(self.scorer._age_score(a), 0.0)

    def test_none_age_uses_default_1yr(self):
        a = _adapter(); a["protocol_age_days"] = None
        # default = 365 → 6 pts
        self.assertEqual(self.scorer._age_score(a), 6.0)

    def test_missing_age_key_uses_default(self):
        a = {k: v for k, v in _adapter().items() if k != "protocol_age_days"}
        # missing key → default 365 days → 6 pts
        self.assertEqual(self.scorer._age_score(a), 6.0)


# ---------------------------------------------------------------------------
# TestAuditScore (7 tests)
# ---------------------------------------------------------------------------

class TestAuditScore(unittest.TestCase):
    """Audit sub-score: 0→0, 1→3, 2→6, 3→8, ≥4→10."""

    def setUp(self):
        self.scorer = LiquidityScorer()

    def test_4_audits_gets_10(self):
        a = _adapter(audit_count=4)
        self.assertEqual(self.scorer._audit_score(a), 10.0)

    def test_3_audits_gets_8(self):
        a = _adapter(audit_count=3)
        self.assertEqual(self.scorer._audit_score(a), 8.0)

    def test_2_audits_gets_6(self):
        a = _adapter(audit_count=2)
        self.assertEqual(self.scorer._audit_score(a), 6.0)

    def test_1_audit_gets_3(self):
        a = _adapter(audit_count=1)
        self.assertEqual(self.scorer._audit_score(a), 3.0)

    def test_0_audits_gets_0(self):
        a = _adapter(audit_count=0)
        self.assertEqual(self.scorer._audit_score(a), 0.0)

    def test_5_audits_capped_at_10(self):
        a = _adapter(audit_count=5)
        self.assertEqual(self.scorer._audit_score(a), 10.0)

    def test_none_audit_count_gets_0(self):
        a = _adapter(); a["audit_count"] = None
        self.assertEqual(self.scorer._audit_score(a), 0.0)


# ---------------------------------------------------------------------------
# TestScoreAdapter (12 tests)
# ---------------------------------------------------------------------------

class TestScoreAdapter(unittest.TestCase):
    """Integration tests for score_adapter (combined sub-scores)."""

    def setUp(self):
        self.scorer = LiquidityScorer()

    def test_perfect_score_100(self):
        # TVL≥1B(30) + T1(25) + instant(20) + ≥5yr(15) + ≥4 audits(10) = 100
        a = _adapter(tvl_usd=2_000_000_000, tier="T1", redemption_type="instant",
                     protocol_age_days=1825, audit_count=4)
        self.assertEqual(self.scorer.score_adapter(a), 100.0)

    def test_score_within_bounds(self):
        a = _adapter()
        score = self.scorer.score_adapter(a)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_worst_case_score_is_5(self):
        # TVL=0(0) + T3(5) + lock(0) + <6mo(0) + 0 audits(0) = 5
        a = _adapter(tvl_usd=0, tier="T3", redemption_type="lock",
                     protocol_age_days=30, audit_count=0)
        self.assertEqual(self.scorer.score_adapter(a), 5.0)

    def test_t2_batched_mid_score(self):
        # TVL 50M(14) + T2(15) + batched(10) + 1yr(6) + 2 audits(6) = 51
        a = _adapter(tvl_usd=50_000_000, tier="T2", redemption_type="batched",
                     protocol_age_days=365, audit_count=2)
        self.assertEqual(self.scorer.score_adapter(a), 51.0)

    def test_object_adapter_works(self):
        obj = _make_obj(tvl_usd=1_000_000_000, tier="T1", redemption_type="instant",
                        protocol_age_days=1825, audit_count=4, protocol="aave_v3")
        self.assertEqual(self.scorer.score_adapter(obj), 100.0)

    def test_missing_all_fields_gives_low_score(self):
        # Only defaults: TVL=0(0) + T3(5) + lock(0) + 365d(6) + 0 audits(0) = 11
        score = self.scorer.score_adapter({})
        self.assertEqual(score, 11.0)

    def test_score_is_float(self):
        a = _adapter()
        self.assertIsInstance(self.scorer.score_adapter(a), float)

    def test_tvl_none_treated_as_zero(self):
        a = _adapter(tvl_usd=None, tier="T1", redemption_type="instant",
                     protocol_age_days=1825, audit_count=4)
        # TVL=0(0)+T1(25)+instant(20)+age(15)+audit(10) = 70
        self.assertEqual(self.scorer.score_adapter(a), 70.0)

    def test_negative_tvl_treated_as_zero(self):
        a = _adapter(tvl_usd=-1_000_000, tier="T1", redemption_type="instant",
                     protocol_age_days=1825, audit_count=4)
        self.assertEqual(self.scorer.score_adapter(a), 70.0)

    def test_aave_proxy_score(self):
        # Simulate Aave V3: TVL≥1B(30) + T1(25) + instant(20) + 3yr+(12) + 4 audits(10) = 97
        aave = _adapter(tvl_usd=5_000_000_000, tier="T1", redemption_type="instant",
                        protocol_age_days=1095, audit_count=4)
        self.assertEqual(self.scorer.score_adapter(aave), 97.0)

    def test_maple_proxy_score(self):
        # Simulate Maple: TVL 50M(14) + T2(15) + lock(0) + 2yr(9) + 3 audits(8) = 46
        maple = _adapter(tvl_usd=50_000_000, tier="T2", redemption_type="lock",
                         protocol_age_days=730, audit_count=3)
        self.assertEqual(self.scorer.score_adapter(maple), 46.0)

    def test_score_stable_on_repeated_calls(self):
        a = _adapter()
        s1 = self.scorer.score_adapter(a)
        s2 = self.scorer.score_adapter(a)
        self.assertEqual(s1, s2)


# ---------------------------------------------------------------------------
# TestClassifyLiquidity (10 tests)
# ---------------------------------------------------------------------------

class TestClassifyLiquidity(unittest.TestCase):
    """classify_liquidity: excellent(≥80), good(60-79), fair(40-59), poor(<40)."""

    def test_100_is_excellent(self):
        self.assertEqual(LiquidityScorer.classify_liquidity(100.0), "excellent")

    def test_80_is_excellent(self):
        self.assertEqual(LiquidityScorer.classify_liquidity(80.0), "excellent")

    def test_79_is_good(self):
        self.assertEqual(LiquidityScorer.classify_liquidity(79.0), "good")

    def test_60_is_good(self):
        self.assertEqual(LiquidityScorer.classify_liquidity(60.0), "good")

    def test_59_is_fair(self):
        self.assertEqual(LiquidityScorer.classify_liquidity(59.0), "fair")

    def test_40_is_fair(self):
        self.assertEqual(LiquidityScorer.classify_liquidity(40.0), "fair")

    def test_39_is_poor(self):
        self.assertEqual(LiquidityScorer.classify_liquidity(39.0), "poor")

    def test_0_is_poor(self):
        self.assertEqual(LiquidityScorer.classify_liquidity(0.0), "poor")

    def test_above_100_clamped_to_excellent(self):
        self.assertEqual(LiquidityScorer.classify_liquidity(150.0), "excellent")

    def test_negative_clamped_to_poor(self):
        self.assertEqual(LiquidityScorer.classify_liquidity(-5.0), "poor")


# ---------------------------------------------------------------------------
# TestScorePortfolio (10 tests)
# ---------------------------------------------------------------------------

class TestScorePortfolio(unittest.TestCase):
    """score_portfolio: weighted average across adapters."""

    def setUp(self):
        self.scorer = LiquidityScorer()
        self.best = _adapter(tvl_usd=2_000_000_000, tier="T1", redemption_type="instant",
                             protocol_age_days=1825, audit_count=4)   # score 100
        self.worst = _adapter(tvl_usd=0, tier="T3", redemption_type="lock",
                              protocol_age_days=30, audit_count=0)   # score 0

    def test_single_adapter_equals_score_adapter(self):
        a = _adapter()
        expected = self.scorer.score_adapter(a)
        self.assertEqual(self.scorer.score_portfolio([a], [1.0]), expected)

    def test_equal_weights_averages(self):
        # best(100) + worst(5: T3=5) equally weighted → (100+5)/2 = 52.5
        result = self.scorer.score_portfolio([self.best, self.worst], [1.0, 1.0])
        self.assertEqual(result, 52.5)

    def test_unequal_weights(self):
        # best(100)*3 + worst(5)*1 / 4 = (300+5)/4 = 76.25
        result = self.scorer.score_portfolio([self.best, self.worst], [3.0, 1.0])
        self.assertEqual(result, 76.25)

    def test_empty_adapters_returns_zero(self):
        self.assertEqual(self.scorer.score_portfolio([], []), 0.0)

    def test_all_zero_weights_returns_zero(self):
        a = _adapter()
        self.assertEqual(self.scorer.score_portfolio([a, a], [0.0, 0.0]), 0.0)

    def test_negative_weights_treated_as_zero(self):
        # negative weight ignored; only second adapter (score=5: T3=5) has w=1 → result=5
        result = self.scorer.score_portfolio([self.best, self.worst], [-1.0, 1.0])
        self.assertEqual(result, 5.0)

    def test_mismatched_lengths_raises(self):
        with self.assertRaises(ValueError):
            self.scorer.score_portfolio([self.best], [1.0, 1.0])

    def test_large_usd_weights_work(self):
        # Use realistic USD values as weights
        a1 = _adapter(tvl_usd=1_000_000_000, tier="T1", redemption_type="instant",
                      protocol_age_days=1825, audit_count=4)  # 100
        a2 = _adapter(tvl_usd=50_000_000, tier="T2", redemption_type="batched",
                      protocol_age_days=365, audit_count=2)   # 51
        result = self.scorer.score_portfolio([a1, a2], [40_000, 60_000])
        expected = (100.0 * 40_000 + 51.0 * 60_000) / 100_000
        self.assertAlmostEqual(result, expected, places=3)

    def test_result_within_bounds(self):
        adapters = [_adapter(tier="T1"), _adapter(tier="T2"), _adapter(tier="T3")]
        weights  = [0.5, 0.3, 0.2]
        score = self.scorer.score_portfolio(adapters, weights)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_result_is_float(self):
        result = self.scorer.score_portfolio([self.best], [1])
        self.assertIsInstance(result, float)


# ---------------------------------------------------------------------------
# TestGetLiquidityReport (13 tests)
# ---------------------------------------------------------------------------

class TestGetLiquidityReport(unittest.TestCase):
    """get_liquidity_report: structure, content, warnings, tier breakdown."""

    def setUp(self):
        self.scorer = LiquidityScorer()
        self.a1 = _adapter(tvl_usd=2_000_000_000, tier="T1", redemption_type="instant",
                           protocol_age_days=1825, audit_count=4, protocol="aave")
        self.a2 = _adapter(tvl_usd=50_000_000, tier="T2", redemption_type="batched",
                           protocol_age_days=365, audit_count=2, protocol="maple")
        self.adapters = [self.a1, self.a2]
        self.weights  = [70_000, 30_000]

    def test_returns_dict(self):
        report = self.scorer.get_liquidity_report(self.adapters, self.weights)
        self.assertIsInstance(report, dict)

    def test_has_required_keys(self):
        report = self.scorer.get_liquidity_report(self.adapters, self.weights)
        for key in ("portfolio_score", "classification", "scores", "breakdown",
                    "warnings", "tier_liquidity_breakdown"):
            self.assertIn(key, report, f"Missing key: {key}")

    def test_scores_length_matches_adapters(self):
        report = self.scorer.get_liquidity_report(self.adapters, self.weights)
        self.assertEqual(len(report["scores"]), 2)

    def test_breakdown_length_matches_adapters(self):
        report = self.scorer.get_liquidity_report(self.adapters, self.weights)
        self.assertEqual(len(report["breakdown"]), 2)

    def test_portfolio_score_matches_score_portfolio(self):
        report = self.scorer.get_liquidity_report(self.adapters, self.weights)
        expected = self.scorer.score_portfolio(self.adapters, self.weights)
        self.assertEqual(report["portfolio_score"], expected)

    def test_classification_is_string(self):
        report = self.scorer.get_liquidity_report(self.adapters, self.weights)
        self.assertIsInstance(report["classification"], str)

    def test_breakdown_has_sub_scores(self):
        report = self.scorer.get_liquidity_report(self.adapters, self.weights)
        for entry in report["breakdown"]:
            sub = entry.get("sub_scores", {})
            for sub_key in ("tvl", "tier", "redemption", "age", "audit"):
                self.assertIn(sub_key, sub)

    def test_tier_liquidity_breakdown_has_t1_t2_t3(self):
        report = self.scorer.get_liquidity_report(self.adapters, self.weights)
        tlb = report["tier_liquidity_breakdown"]
        for tier_key in ("T1", "T2", "T3"):
            self.assertIn(tier_key, tlb)

    def test_low_tvl_generates_warning(self):
        bad = _adapter(tvl_usd=1_000_000, tier="T3", redemption_type="lock",
                       protocol_age_days=60, audit_count=0, protocol="bad")
        report = self.scorer.get_liquidity_report([bad], [1.0])
        self.assertTrue(any("TVL" in w for w in report["warnings"]))

    def test_zero_audits_warning(self):
        no_audit = _adapter(audit_count=0, protocol="unaudited")
        report = self.scorer.get_liquidity_report([no_audit], [1.0])
        self.assertTrue(any("audit" in w.lower() for w in report["warnings"]))

    def test_lock_redemption_warning(self):
        locked = _adapter(redemption_type="lock", protocol="locked_proto")
        report = self.scorer.get_liquidity_report([locked], [1.0])
        self.assertTrue(any("lock" in w.lower() for w in report["warnings"]))

    def test_mismatched_lengths_raises(self):
        with self.assertRaises(ValueError):
            self.scorer.get_liquidity_report(self.adapters, [1.0])

    def test_empty_portfolio_returns_zero_score(self):
        report = self.scorer.get_liquidity_report([], [])
        self.assertEqual(report["portfolio_score"], 0.0)


# ---------------------------------------------------------------------------
# TestEstimateExitTime (12 tests)
# ---------------------------------------------------------------------------

class TestEstimateExitTime(unittest.TestCase):
    """estimate_exit_time_days: redemption type, tier, TVL utilisation."""

    def setUp(self):
        self.scorer = LiquidityScorer()

    def test_instant_redemption_zero_days(self):
        a = _adapter(redemption_type="instant", tvl_usd=1_000_000_000)
        self.assertEqual(self.scorer.estimate_exit_time_days(a, 0), 0.0)

    def test_batched_redemption_base_is_2_days(self):
        # batched: min=1, max=3 → base=(1+3)/2=2.0
        a = _adapter(redemption_type="batched", tvl_usd=1_000_000_000)
        self.assertEqual(self.scorer.estimate_exit_time_days(a, 0), 2.0)

    def test_lock_redemption_base_is_18_5_days(self):
        # lock: min=7, max=30 → base=(7+30)/2=18.5
        a = _adapter(redemption_type="lock", tvl_usd=1_000_000_000)
        self.assertEqual(self.scorer.estimate_exit_time_days(a, 0), 18.5)

    def test_t1_no_redemption_type_is_instant(self):
        # T1 default: min=0, max=0 → base=0
        a = {"tier": "T1", "tvl_usd": 1_000_000_000}
        self.assertEqual(self.scorer.estimate_exit_time_days(a, 0), 0.0)

    def test_t2_no_redemption_type_is_batched(self):
        # T2 default: min=1, max=3 → base=2
        a = {"tier": "T2", "tvl_usd": 1_000_000_000}
        self.assertEqual(self.scorer.estimate_exit_time_days(a, 0), 2.0)

    def test_t3_no_redemption_type_is_lock(self):
        a = {"tier": "T3", "tvl_usd": 1_000_000_000}
        self.assertEqual(self.scorer.estimate_exit_time_days(a, 0), 18.5)

    def test_utilisation_premium_at_high_threshold(self):
        # 10% of TVL (max utilisation): premium_days = 3.0 * 3.0 = 9.0
        # t=1 → base_days + 1*(9.0 - 2.0) = 2 + 7 = 9
        a = _adapter(redemption_type="batched", tvl_usd=100_000_000)
        result = self.scorer.estimate_exit_time_days(a, 10_000_000)  # exactly 10%
        self.assertAlmostEqual(result, 9.0, places=2)

    def test_utilisation_above_high_threshold_capped(self):
        # > 10% of TVL → should not exceed max_days * multiplier = 3*3 = 9
        a = _adapter(redemption_type="batched", tvl_usd=100_000_000)
        result = self.scorer.estimate_exit_time_days(a, 50_000_000)  # 50%
        self.assertAlmostEqual(result, 9.0, places=2)

    def test_zero_tvl_no_premium(self):
        a = _adapter(redemption_type="batched", tvl_usd=0)
        result = self.scorer.estimate_exit_time_days(a, 1_000_000)
        self.assertEqual(result, 2.0)

    def test_negative_amount_treated_as_zero(self):
        a = _adapter(redemption_type="lock", tvl_usd=100_000_000)
        result = self.scorer.estimate_exit_time_days(a, -500_000)
        self.assertEqual(result, 18.5)

    def test_result_non_negative(self):
        a = _adapter(redemption_type="instant", tvl_usd=0)
        self.assertGreaterEqual(self.scorer.estimate_exit_time_days(a), 0.0)

    def test_result_is_float(self):
        a = _adapter(redemption_type="batched", tvl_usd=1_000_000_000)
        self.assertIsInstance(self.scorer.estimate_exit_time_days(a, 0), float)


# ---------------------------------------------------------------------------
# TestImportHygiene (3 tests)
# ---------------------------------------------------------------------------

class TestImportHygiene(unittest.TestCase):
    """Verify no forbidden external or domain dependencies."""

    def _module_source(self) -> str:
        import inspect
        import spa_core.analytics.liquidity_scorer as mod
        return inspect.getsource(mod)

    def test_no_forbidden_external_packages(self):
        """No numpy/requests/web3/pandas/scipy/aiohttp etc."""
        source = self._module_source()
        forbidden = ["import numpy", "import requests", "import web3",
                     "import pandas", "import scipy", "import aiohttp",
                     "import openai", "import anthropic"]
        for pkg in forbidden:
            self.assertNotIn(pkg, source, f"Forbidden import found: {pkg}")

    def test_no_forbidden_domain_imports(self):
        """No execution / risk / monitoring domain imports."""
        source = self._module_source()
        for domain in ("execution", "monitoring", "feed_health"):
            self.assertNotIn(
                f"from spa_core.{domain}", source,
                f"Forbidden domain import: {domain}"
            )

    def test_module_importable(self):
        """LiquidityScorer must be importable without side-effects."""
        import importlib
        mod = importlib.import_module("spa_core.analytics.liquidity_scorer")
        self.assertTrue(hasattr(mod, "LiquidityScorer"))


# ---------------------------------------------------------------------------
# Extra edge-case tests to reach ≥85 total (filed under TestScoreAdapter)
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """Edge cases and helper function tests."""

    def setUp(self):
        self.scorer = LiquidityScorer()

    def test_safe_float_none_returns_default(self):
        self.assertEqual(_safe_float(None, 99.0), 99.0)

    def test_safe_float_string_number(self):
        self.assertAlmostEqual(_safe_float("3.14"), 3.14)

    def test_safe_float_invalid_string(self):
        self.assertEqual(_safe_float("abc", 0.0), 0.0)

    def test_normalise_tier_t1(self):
        self.assertEqual(_normalise_tier("T1"), "T1")

    def test_normalise_tier_unknown(self):
        self.assertEqual(_normalise_tier("TX"), "T3")

    def test_normalise_tier_none(self):
        self.assertEqual(_normalise_tier(None), "T3")

    def test_normalise_redemption_instant(self):
        self.assertEqual(_normalise_redemption("INSTANT"), "instant")

    def test_normalise_redemption_unknown(self):
        self.assertEqual(_normalise_redemption("unknown_type"), "lock")

    def test_tiered_score_exact_boundary(self):
        # 1B is first tier (30 pts) in TVL_TIERS
        self.assertEqual(_tiered_score(1_000_000_000, _TVL_TIERS), 30.0)

    def test_tiered_score_just_below_boundary(self):
        # Just below $500M → should be 20 (100M tier)
        self.assertEqual(_tiered_score(499_999_999, _TVL_TIERS), 20.0)

    def test_score_portfolio_single_weight_zero_and_one(self):
        best = _adapter(tvl_usd=2_000_000_000, tier="T1", redemption_type="instant",
                        protocol_age_days=1825, audit_count=4)
        worst = _adapter(tvl_usd=0, tier="T3", redemption_type="lock",
                         protocol_age_days=30, audit_count=0)
        # Weight on best=0, worst=1 → should be score of worst (5: T3 tier=5)
        result = self.scorer.score_portfolio([best, worst], [0.0, 1.0])
        self.assertEqual(result, 5.0)

    def test_classify_boundary_80(self):
        self.assertEqual(LiquidityScorer.classify_liquidity(80.0), "excellent")

    def test_classify_boundary_79_99(self):
        self.assertEqual(LiquidityScorer.classify_liquidity(79.9), "good")

    def test_classify_boundary_60(self):
        self.assertEqual(LiquidityScorer.classify_liquidity(60.0), "good")

    def test_classify_boundary_59_99(self):
        self.assertEqual(LiquidityScorer.classify_liquidity(59.9), "fair")

    def test_classify_boundary_40(self):
        self.assertEqual(LiquidityScorer.classify_liquidity(40.0), "fair")

    def test_classify_boundary_39_99(self):
        self.assertEqual(LiquidityScorer.classify_liquidity(39.9), "poor")

    def test_report_scores_match_individual_score_adapter(self):
        a1 = _adapter(tier="T1", protocol="p1")
        a2 = _adapter(tier="T2", protocol="p2")
        report = self.scorer.get_liquidity_report([a1, a2], [1.0, 1.0])
        self.assertEqual(report["scores"][0], self.scorer.score_adapter(a1))
        self.assertEqual(report["scores"][1], self.scorer.score_adapter(a2))

    def test_report_weight_fractions_sum_to_one(self):
        a1 = _adapter(protocol="p1")
        a2 = _adapter(protocol="p2")
        a3 = _adapter(protocol="p3")
        report = self.scorer.get_liquidity_report([a1, a2, a3], [1.0, 2.0, 3.0])
        total_fraction = sum(e["weight_fraction"] for e in report["breakdown"])
        self.assertAlmostEqual(total_fraction, 1.0, places=5)

    def test_estimate_exit_small_amount_no_premium(self):
        # amount = 0.001% of TVL → below utilisation low threshold
        a = _adapter(redemption_type="batched", tvl_usd=1_000_000_000)
        result = self.scorer.estimate_exit_time_days(a, 1_000)
        self.assertAlmostEqual(result, 2.0, places=2)

    def test_excellent_score_above_80(self):
        a = _adapter(tvl_usd=1_000_000_000, tier="T1", redemption_type="instant",
                     protocol_age_days=1825, audit_count=4)
        score = self.scorer.score_adapter(a)
        self.assertEqual(self.scorer.classify_liquidity(score), "excellent")

    def test_low_score_is_poor(self):
        # TVL=0(0)+T3(5)+lock(0)+30d(0)+0audits(0)=5 → poor
        a = _adapter(tvl_usd=0, tier="T3", redemption_type="lock",
                     protocol_age_days=30, audit_count=0)
        score = self.scorer.score_adapter(a)
        self.assertEqual(score, 5.0)
        self.assertEqual(self.scorer.classify_liquidity(score), "poor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
