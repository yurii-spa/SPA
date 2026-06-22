"""
Tests for MP-898 ProtocolEconomicAttackSimulator.
Run: python3 -m unittest spa_core.tests.test_protocol_economic_attack_simulator -v
"""

import time
import unittest

from spa_core.analytics.protocol_economic_attack_simulator import (
    analyze,
    _governance_attack_cost,
    _flash_loan_feasibility,
    _oracle_vulnerability,
    _timelock_protection,
    _economic_security_score,
    _attack_surface_label,
    _build_recommendation,
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def _make_protocol(**overrides):
    base = {
        "name": "TestProtocol",
        "tvl_usd": 50_000_000.0,
        "governance_token_price_usd": 10.0,
        "circulating_supply": 1_000_000.0,
        "majority_threshold_pct": 50.0,
        "flash_loan_fee_pct": 0.09,
        "oracle_manipulation_cost_usd": 500_000.0,
        "time_lock_hours": 72,
        "has_flash_loan_guard": True,
        "avg_block_governance_votes": 500,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _governance_attack_cost
# ---------------------------------------------------------------------------

class TestGovernanceAttackCost(unittest.TestCase):
    def test_basic(self):
        cost = _governance_attack_cost(50.0, 1_000_000.0, 10.0)
        self.assertAlmostEqual(cost, 5_000_000.0)

    def test_66_pct_threshold(self):
        cost = _governance_attack_cost(66.0, 1_000_000.0, 1.0)
        self.assertAlmostEqual(cost, 660_000.0)

    def test_zero_price(self):
        cost = _governance_attack_cost(50.0, 1_000_000.0, 0.0)
        self.assertAlmostEqual(cost, 0.0)

    def test_zero_supply(self):
        cost = _governance_attack_cost(50.0, 0.0, 10.0)
        self.assertAlmostEqual(cost, 0.0)

    def test_100_pct_threshold(self):
        cost = _governance_attack_cost(100.0, 1_000_000.0, 5.0)
        self.assertAlmostEqual(cost, 5_000_000.0)


# ---------------------------------------------------------------------------
# _flash_loan_feasibility
# ---------------------------------------------------------------------------

class TestFlashLoanFeasibility(unittest.TestCase):
    def test_trivial(self):
        self.assertEqual(_flash_loan_feasibility(0), "TRIVIAL")

    def test_trivial_just_below(self):
        self.assertEqual(_flash_loan_feasibility(99_999), "TRIVIAL")

    def test_feasible_at_100k(self):
        self.assertEqual(_flash_loan_feasibility(100_000), "FEASIBLE")

    def test_feasible_999k(self):
        self.assertEqual(_flash_loan_feasibility(999_999), "FEASIBLE")

    def test_expensive_1m(self):
        self.assertEqual(_flash_loan_feasibility(1_000_000), "EXPENSIVE")

    def test_expensive_9_9m(self):
        self.assertEqual(_flash_loan_feasibility(9_999_999), "EXPENSIVE")

    def test_impractical_10m(self):
        self.assertEqual(_flash_loan_feasibility(10_000_000), "IMPRACTICAL")

    def test_impractical_large(self):
        self.assertEqual(_flash_loan_feasibility(100_000_000), "IMPRACTICAL")


# ---------------------------------------------------------------------------
# _oracle_vulnerability
# ---------------------------------------------------------------------------

class TestOracleVulnerability(unittest.TestCase):
    def test_critical_zero(self):
        self.assertEqual(_oracle_vulnerability(0), "CRITICAL")

    def test_critical_just_below_100k(self):
        self.assertEqual(_oracle_vulnerability(99_999), "CRITICAL")

    def test_high_100k(self):
        self.assertEqual(_oracle_vulnerability(100_000), "HIGH")

    def test_high_999k(self):
        self.assertEqual(_oracle_vulnerability(999_999), "HIGH")

    def test_moderate_1m(self):
        self.assertEqual(_oracle_vulnerability(1_000_000), "MODERATE")

    def test_moderate_9_9m(self):
        self.assertEqual(_oracle_vulnerability(9_999_999), "MODERATE")

    def test_low_10m(self):
        self.assertEqual(_oracle_vulnerability(10_000_000), "LOW")

    def test_low_large(self):
        self.assertEqual(_oracle_vulnerability(100_000_000), "LOW")


# ---------------------------------------------------------------------------
# _timelock_protection
# ---------------------------------------------------------------------------

class TestTimelockProtection(unittest.TestCase):
    def test_none_zero(self):
        self.assertEqual(_timelock_protection(0), "NONE")

    def test_weak_1(self):
        self.assertEqual(_timelock_protection(1), "WEAK")

    def test_weak_23(self):
        self.assertEqual(_timelock_protection(23), "WEAK")

    def test_moderate_24(self):
        self.assertEqual(_timelock_protection(24), "MODERATE")

    def test_moderate_71(self):
        self.assertEqual(_timelock_protection(71), "MODERATE")

    def test_strong_72(self):
        self.assertEqual(_timelock_protection(72), "STRONG")

    def test_strong_167(self):
        self.assertEqual(_timelock_protection(167), "STRONG")

    def test_very_strong_168(self):
        self.assertEqual(_timelock_protection(168), "VERY_STRONG")

    def test_very_strong_336(self):
        self.assertEqual(_timelock_protection(336), "VERY_STRONG")


# ---------------------------------------------------------------------------
# _attack_surface_label
# ---------------------------------------------------------------------------

class TestAttackSurfaceLabel(unittest.TestCase):
    def test_minimal_80(self):
        self.assertEqual(_attack_surface_label(80), "MINIMAL")

    def test_minimal_100(self):
        self.assertEqual(_attack_surface_label(100), "MINIMAL")

    def test_low_65(self):
        self.assertEqual(_attack_surface_label(65), "LOW")

    def test_low_79(self):
        self.assertEqual(_attack_surface_label(79), "LOW")

    def test_moderate_50(self):
        self.assertEqual(_attack_surface_label(50), "MODERATE")

    def test_moderate_64(self):
        self.assertEqual(_attack_surface_label(64), "MODERATE")

    def test_high_35(self):
        self.assertEqual(_attack_surface_label(35), "HIGH")

    def test_high_49(self):
        self.assertEqual(_attack_surface_label(49), "HIGH")

    def test_critical_34(self):
        self.assertEqual(_attack_surface_label(34), "CRITICAL")

    def test_critical_0(self):
        self.assertEqual(_attack_surface_label(0), "CRITICAL")


# ---------------------------------------------------------------------------
# _economic_security_score
# ---------------------------------------------------------------------------

class TestEconomicSecurityScore(unittest.TestCase):
    def test_max_score(self):
        # IMPRACTICAL(40)+LOW(25)+VERY_STRONG(20)+guard(10)+votes(5)=100
        score = _economic_security_score("IMPRACTICAL", "LOW", "VERY_STRONG", True, 500)
        self.assertEqual(score, 100)

    def test_min_score(self):
        # TRIVIAL(0)+CRITICAL(0)+NONE(0)+no_guard(0)+votes=0
        score = _economic_security_score("TRIVIAL", "CRITICAL", "NONE", False, 0)
        self.assertEqual(score, 0)

    def test_flash_guard_adds_10(self):
        base = _economic_security_score("TRIVIAL", "CRITICAL", "NONE", False, 0)
        with_guard = _economic_security_score("TRIVIAL", "CRITICAL", "NONE", True, 0)
        self.assertEqual(with_guard - base, 10)

    def test_block_vote_score_capped_5(self):
        score_big = _economic_security_score("TRIVIAL", "CRITICAL", "NONE", False, 10_000)
        score_small = _economic_security_score("TRIVIAL", "CRITICAL", "NONE", False, 0)
        self.assertEqual(score_big - score_small, 5)

    def test_block_vote_score_100_gives_1(self):
        score = _economic_security_score("TRIVIAL", "CRITICAL", "NONE", False, 100)
        self.assertEqual(score, 1)

    def test_block_vote_score_499_gives_4(self):
        score = _economic_security_score("TRIVIAL", "CRITICAL", "NONE", False, 499)
        self.assertEqual(score, 4)

    def test_expensive_governance(self):
        score = _economic_security_score("EXPENSIVE", "LOW", "STRONG", True, 0)
        # 30+25+15+10+0=80
        self.assertEqual(score, 80)

    def test_feasible_governance(self):
        score = _economic_security_score("FEASIBLE", "MODERATE", "MODERATE", False, 0)
        # 15+18+10+0+0=43
        self.assertEqual(score, 43)

    def test_clamped_at_100(self):
        score = _economic_security_score("IMPRACTICAL", "LOW", "VERY_STRONG", True, 10_000)
        self.assertLessEqual(score, 100)

    def test_clamped_at_0(self):
        score = _economic_security_score("TRIVIAL", "CRITICAL", "NONE", False, 0)
        self.assertGreaterEqual(score, 0)


# ---------------------------------------------------------------------------
# _build_recommendation
# ---------------------------------------------------------------------------

class TestBuildRecommendation(unittest.TestCase):
    def test_minimal(self):
        rec = _build_recommendation("MINIMAL", 5_000_000, [])
        self.assertIn("Well-secured", rec)
        self.assertIn("5,000,000", rec)

    def test_low(self):
        rec = _build_recommendation("LOW", 2_000_000, [])
        self.assertIn("Well-secured", rec)

    def test_moderate_with_flags(self):
        rec = _build_recommendation("MODERATE", 500_000, ["FLASH_LOAN_VULNERABLE", "NO_TIMELOCK"])
        self.assertIn("Moderate", rec)
        self.assertIn("FLASH_LOAN_VULNERABLE", rec)

    def test_moderate_no_flags(self):
        rec = _build_recommendation("MODERATE", 500_000, [])
        self.assertIn("review config", rec)

    def test_high(self):
        rec = _build_recommendation("HIGH", 10_000, ["A", "B", "C"])
        self.assertIn("High attack surface", rec)
        self.assertIn("3 vulnerabilities", rec)

    def test_critical_with_flags(self):
        rec = _build_recommendation("CRITICAL", 0, ["FLASH_LOAN_VULNERABLE", "NO_TIMELOCK"])
        self.assertIn("Critical security risk", rec)
        self.assertIn("FLASH_LOAN_VULNERABLE", rec)

    def test_critical_no_flags(self):
        rec = _build_recommendation("CRITICAL", 0, [])
        self.assertIn("very low scores", rec)


# ---------------------------------------------------------------------------
# analyze() — empty input
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):
    def test_empty_protocols(self):
        result = analyze([])
        self.assertEqual(result["protocols"], [])
        self.assertIsNone(result["most_secure"])
        self.assertIsNone(result["most_vulnerable"])
        self.assertEqual(result["average_security_score"], 0.0)
        self.assertEqual(result["critical_count"], 0)
        self.assertIn("timestamp", result)

    def test_empty_timestamp_present(self):
        before = time.time()
        result = analyze([])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)


# ---------------------------------------------------------------------------
# analyze() — single protocol
# ---------------------------------------------------------------------------

class TestAnalyzeSingle(unittest.TestCase):
    def setUp(self):
        self.p = _make_protocol()
        self.result = analyze([self.p])
        self.proto = self.result["protocols"][0]

    def test_returns_one_protocol(self):
        self.assertEqual(len(self.result["protocols"]), 1)

    def test_name_preserved(self):
        self.assertEqual(self.proto["name"], "TestProtocol")

    def test_governance_attack_cost(self):
        # 50% * 1M * $10 = $5M
        self.assertAlmostEqual(self.proto["governance_attack_cost_usd"], 5_000_000.0)

    def test_flash_loan_attack_feasibility(self):
        # 50% * 1,000,000 supply * $10 = $5M → EXPENSIVE (< $10M)
        self.assertEqual(self.proto["flash_loan_attack_feasibility"], "EXPENSIVE")

    def test_flash_loan_blocked(self):
        self.assertTrue(self.proto["flash_loan_blocked"])

    def test_oracle_attack_cost_10pct(self):
        # 500k * 10 = 5M
        self.assertAlmostEqual(self.proto["oracle_attack_cost_10pct_usd"], 5_000_000.0)

    def test_oracle_vulnerability(self):
        self.assertEqual(self.proto["oracle_vulnerability"], "MODERATE")

    def test_timelock_protection(self):
        self.assertEqual(self.proto["timelock_protection"], "STRONG")

    def test_security_score_range(self):
        self.assertGreaterEqual(self.proto["economic_security_score"], 0)
        self.assertLessEqual(self.proto["economic_security_score"], 100)

    def test_attack_surface_label_is_valid(self):
        self.assertIn(self.proto["attack_surface_label"],
                      ["MINIMAL", "LOW", "MODERATE", "HIGH", "CRITICAL"])

    def test_flags_is_list(self):
        self.assertIsInstance(self.proto["flags"], list)

    def test_recommendation_is_string(self):
        self.assertIsInstance(self.proto["recommendation"], str)

    def test_most_secure(self):
        self.assertEqual(self.result["most_secure"], "TestProtocol")

    def test_most_vulnerable(self):
        self.assertEqual(self.result["most_vulnerable"], "TestProtocol")

    def test_average_score_matches_single(self):
        self.assertAlmostEqual(
            self.result["average_security_score"],
            self.proto["economic_security_score"],
        )


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):
    def test_flash_loan_vulnerable_no_guard(self):
        p = _make_protocol(has_flash_loan_guard=False)
        r = analyze([p])
        self.assertIn("FLASH_LOAN_VULNERABLE", r["protocols"][0]["flags"])

    def test_no_flash_loan_vulnerable_with_guard(self):
        p = _make_protocol(has_flash_loan_guard=True)
        r = analyze([p])
        self.assertNotIn("FLASH_LOAN_VULNERABLE", r["protocols"][0]["flags"])

    def test_cheap_governance_trivial(self):
        # cost = 50% * 100 * 0.01 = 0.5 → TRIVIAL
        p = _make_protocol(
            majority_threshold_pct=50.0,
            circulating_supply=100.0,
            governance_token_price_usd=0.01,
        )
        r = analyze([p])
        self.assertIn("CHEAP_GOVERNANCE_ATTACK", r["protocols"][0]["flags"])

    def test_cheap_governance_feasible(self):
        # cost = 50% * 1_000_000 * 1.0 = 500_000 → FEASIBLE
        p = _make_protocol(
            majority_threshold_pct=50.0,
            circulating_supply=1_000_000.0,
            governance_token_price_usd=1.0,
        )
        r = analyze([p])
        self.assertIn("CHEAP_GOVERNANCE_ATTACK", r["protocols"][0]["flags"])

    def test_no_cheap_governance_expensive(self):
        # cost = 50% * 1_000_000 * 20.0 = 10_000_000 → IMPRACTICAL
        p = _make_protocol(
            majority_threshold_pct=50.0,
            circulating_supply=1_000_000.0,
            governance_token_price_usd=20.0,
        )
        r = analyze([p])
        self.assertNotIn("CHEAP_GOVERNANCE_ATTACK", r["protocols"][0]["flags"])

    def test_oracle_vulnerable_critical(self):
        p = _make_protocol(oracle_manipulation_cost_usd=5_000)  # 10pct=50k < 100k
        r = analyze([p])
        self.assertIn("ORACLE_VULNERABLE", r["protocols"][0]["flags"])

    def test_oracle_vulnerable_high(self):
        p = _make_protocol(oracle_manipulation_cost_usd=50_000)  # 10pct=500k < 1M
        r = analyze([p])
        self.assertIn("ORACLE_VULNERABLE", r["protocols"][0]["flags"])

    def test_no_oracle_vulnerable_moderate(self):
        p = _make_protocol(oracle_manipulation_cost_usd=200_000)  # 10pct=2M
        r = analyze([p])
        self.assertNotIn("ORACLE_VULNERABLE", r["protocols"][0]["flags"])

    def test_no_timelock(self):
        p = _make_protocol(time_lock_hours=0)
        r = analyze([p])
        self.assertIn("NO_TIMELOCK", r["protocols"][0]["flags"])

    def test_no_no_timelock_when_set(self):
        p = _make_protocol(time_lock_hours=48)
        r = analyze([p])
        self.assertNotIn("NO_TIMELOCK", r["protocols"][0]["flags"])

    def test_no_flags_secure_protocol(self):
        p = _make_protocol(
            has_flash_loan_guard=True,
            majority_threshold_pct=50.0,
            circulating_supply=1_000_000.0,
            governance_token_price_usd=20.0,  # cost=10M → IMPRACTICAL
            oracle_manipulation_cost_usd=1_500_000.0,  # 10pct=15M → LOW
            time_lock_hours=200,
        )
        r = analyze([p])
        self.assertEqual(r["protocols"][0]["flags"], [])


# ---------------------------------------------------------------------------
# Multi-protocol selection
# ---------------------------------------------------------------------------

class TestMultiProtocol(unittest.TestCase):
    def setUp(self):
        # Secure: IMPRACTICAL + LOW oracle + VERY_STRONG timelock
        self.secure = _make_protocol(
            name="Secure",
            majority_threshold_pct=50.0,
            circulating_supply=10_000_000.0,
            governance_token_price_usd=20.0,   # cost=100M → IMPRACTICAL
            oracle_manipulation_cost_usd=1_500_000.0,  # 10pct=15M → LOW
            time_lock_hours=200,
            has_flash_loan_guard=True,
            avg_block_governance_votes=1000,
        )
        # Vulnerable: TRIVIAL + CRITICAL oracle + NONE timelock
        self.vuln = _make_protocol(
            name="Vulnerable",
            majority_threshold_pct=50.0,
            circulating_supply=1000.0,
            governance_token_price_usd=0.01,   # cost=5 → TRIVIAL
            oracle_manipulation_cost_usd=1_000.0,  # 10pct=10k → CRITICAL
            time_lock_hours=0,
            has_flash_loan_guard=False,
            avg_block_governance_votes=0,
        )
        self.result = analyze([self.secure, self.vuln])

    def test_most_secure_is_secure(self):
        self.assertEqual(self.result["most_secure"], "Secure")

    def test_most_vulnerable_is_vulnerable(self):
        self.assertEqual(self.result["most_vulnerable"], "Vulnerable")

    def test_critical_count(self):
        vuln_proto = next(p for p in self.result["protocols"] if p["name"] == "Vulnerable")
        # The vulnerable one should be CRITICAL
        self.assertEqual(vuln_proto["attack_surface_label"], "CRITICAL")
        self.assertGreaterEqual(self.result["critical_count"], 1)

    def test_all_protocols_returned(self):
        self.assertEqual(len(self.result["protocols"]), 2)

    def test_average_score_is_between(self):
        scores = [p["economic_security_score"] for p in self.result["protocols"]]
        avg = sum(scores) / len(scores)
        self.assertAlmostEqual(self.result["average_security_score"], avg, places=4)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_zero_price_governance_cost_zero(self):
        p = _make_protocol(governance_token_price_usd=0.0)
        r = analyze([p])
        self.assertAlmostEqual(r["protocols"][0]["governance_attack_cost_usd"], 0.0)
        self.assertEqual(r["protocols"][0]["flash_loan_attack_feasibility"], "TRIVIAL")

    def test_zero_supply_governance_cost_zero(self):
        p = _make_protocol(circulating_supply=0.0)
        r = analyze([p])
        self.assertAlmostEqual(r["protocols"][0]["governance_attack_cost_usd"], 0.0)

    def test_zero_oracle_cost_critical(self):
        p = _make_protocol(oracle_manipulation_cost_usd=0.0)
        r = analyze([p])
        self.assertEqual(r["protocols"][0]["oracle_vulnerability"], "CRITICAL")

    def test_very_high_block_votes_capped(self):
        p = _make_protocol(avg_block_governance_votes=1_000_000)
        r = analyze([p])
        self.assertLessEqual(r["protocols"][0]["economic_security_score"], 100)

    def test_very_high_timelock(self):
        p = _make_protocol(time_lock_hours=10_000)
        r = analyze([p])
        self.assertEqual(r["protocols"][0]["timelock_protection"], "VERY_STRONG")

    def test_critical_count_zero_when_no_critical(self):
        p = _make_protocol(
            majority_threshold_pct=50.0,
            circulating_supply=10_000_000.0,
            governance_token_price_usd=50.0,  # cost=250M → IMPRACTICAL
            oracle_manipulation_cost_usd=5_000_000.0,  # 10pct=50M → LOW
            time_lock_hours=200,
            has_flash_loan_guard=True,
            avg_block_governance_votes=1000,
        )
        r = analyze([p])
        self.assertEqual(r["critical_count"], 0)

    def test_three_protocols_average(self):
        p1 = _make_protocol(name="A")
        p2 = _make_protocol(name="B")
        p3 = _make_protocol(name="C")
        r = analyze([p1, p2, p3])
        self.assertEqual(len(r["protocols"]), 3)
        scores = [p["economic_security_score"] for p in r["protocols"]]
        self.assertAlmostEqual(r["average_security_score"], sum(scores) / 3, places=4)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class TestLogging(unittest.TestCase):
    def test_logging_does_not_raise(self):
        result = analyze([_make_protocol()])
        self.assertIn("timestamp", result)

    def test_multiple_calls_no_raise(self):
        for _ in range(3):
            analyze([_make_protocol()])


if __name__ == "__main__":
    unittest.main()
