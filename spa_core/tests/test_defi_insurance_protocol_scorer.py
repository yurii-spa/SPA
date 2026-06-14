"""
Tests for MP-881 DeFiInsuranceProtocolScorer
Run: python3 -m unittest spa_core.tests.test_defi_insurance_protocol_scorer -v
"""
import json
import os
import tempfile
import time
import unittest

from spa_core.analytics.defi_insurance_protocol_scorer import (
    analyze,
    _coverage_ratio,
    _claims_payment_rate,
    _capital_efficiency_score,
    _cover_breadth_score,
    _maturity_normalized,
    _premium_competitiveness,
    _maturity_label,
    _grade,
    _flags,
    _recommendation,
    _clamp,
    _append_log,
    _RING_BUFFER_MAX,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_protocol(**kwargs):
    base = {
        "name": "TestProtocol",
        "total_coverage_usd": 5_000_000.0,
        "total_capital_usd": 2_000_000.0,
        "claims_paid_usd": 100_000.0,
        "claims_rejected_usd": 10_000.0,
        "active_cover_policies": 200,
        "annual_premium_rate_bps": 80.0,
        "days_since_launch": 400,
        "cover_types": ["smart_contract", "depeg"],
        "capital_utilization_pct": 250.0,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Unit tests – _clamp
# ---------------------------------------------------------------------------

class TestClamp(unittest.TestCase):
    def test_clamp_below_zero(self):
        self.assertEqual(_clamp(-10), 0)

    def test_clamp_above_100(self):
        self.assertEqual(_clamp(150), 100)

    def test_clamp_at_zero(self):
        self.assertEqual(_clamp(0), 0)

    def test_clamp_at_100(self):
        self.assertEqual(_clamp(100), 100)

    def test_clamp_midrange(self):
        self.assertEqual(_clamp(55.9), 55)

    def test_clamp_returns_int(self):
        self.assertIsInstance(_clamp(42.5), int)


# ---------------------------------------------------------------------------
# Unit tests – _coverage_ratio
# ---------------------------------------------------------------------------

class TestCoverageRatio(unittest.TestCase):
    def test_basic_ratio(self):
        self.assertAlmostEqual(_coverage_ratio(5_000_000, 2_000_000), 2.5)

    def test_zero_capital(self):
        self.assertEqual(_coverage_ratio(5_000_000, 0), 0.0)

    def test_negative_capital(self):
        self.assertEqual(_coverage_ratio(1_000, -1), 0.0)

    def test_zero_coverage(self):
        self.assertEqual(_coverage_ratio(0, 1_000_000), 0.0)

    def test_equal(self):
        self.assertAlmostEqual(_coverage_ratio(1_000_000, 1_000_000), 1.0)


# ---------------------------------------------------------------------------
# Unit tests – _claims_payment_rate
# ---------------------------------------------------------------------------

class TestClaimsPaymentRate(unittest.TestCase):
    def test_both_zero_benefit_of_doubt(self):
        self.assertEqual(_claims_payment_rate(0, 0), 100.0)

    def test_all_paid(self):
        self.assertAlmostEqual(_claims_payment_rate(100_000, 0), 100.0)

    def test_all_rejected(self):
        self.assertAlmostEqual(_claims_payment_rate(0, 100_000), 0.0)

    def test_partial(self):
        self.assertAlmostEqual(_claims_payment_rate(90_000, 10_000), 90.0)

    def test_equal(self):
        self.assertAlmostEqual(_claims_payment_rate(50_000, 50_000), 50.0)


# ---------------------------------------------------------------------------
# Unit tests – _capital_efficiency_score
# ---------------------------------------------------------------------------

class TestCapitalEfficiencyScore(unittest.TestCase):
    def test_ratio_2_5(self):
        # coverage_ratio=2.5 → min(100, int(2.5*10)) = 25
        self.assertEqual(_capital_efficiency_score(2.5), 25)

    def test_ratio_10_capped(self):
        # coverage_ratio=10 → min(100, 100) = 100
        self.assertEqual(_capital_efficiency_score(10.0), 100)

    def test_ratio_15_capped(self):
        # coverage_ratio=15 → min(100, 150) = 100
        self.assertEqual(_capital_efficiency_score(15.0), 100)

    def test_ratio_0(self):
        self.assertEqual(_capital_efficiency_score(0.0), 0)

    def test_ratio_5(self):
        self.assertEqual(_capital_efficiency_score(5.0), 50)


# ---------------------------------------------------------------------------
# Unit tests – _cover_breadth_score
# ---------------------------------------------------------------------------

class TestCoverBreadthScore(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_cover_breadth_score([]), 0)

    def test_one(self):
        # 1/4*100 = 25
        self.assertEqual(_cover_breadth_score(["smart_contract"]), 25)

    def test_two(self):
        self.assertEqual(_cover_breadth_score(["a", "b"]), 50)

    def test_four_equals_100(self):
        self.assertEqual(_cover_breadth_score(["a", "b", "c", "d"]), 100)

    def test_five_capped(self):
        self.assertEqual(_cover_breadth_score(["a", "b", "c", "d", "e"]), 100)


# ---------------------------------------------------------------------------
# Unit tests – _maturity_normalized
# ---------------------------------------------------------------------------

class TestMaturityNormalized(unittest.TestCase):
    def test_zero_days(self):
        self.assertEqual(_maturity_normalized(0), 0)

    def test_730_days(self):
        self.assertEqual(_maturity_normalized(730), 100)

    def test_365_days(self):
        self.assertEqual(_maturity_normalized(365), 50)

    def test_over_730_capped(self):
        self.assertEqual(_maturity_normalized(1500), 100)

    def test_partial(self):
        # int(200/730*100) = int(27.39) = 27
        self.assertEqual(_maturity_normalized(200), 27)


# ---------------------------------------------------------------------------
# Unit tests – _premium_competitiveness
# ---------------------------------------------------------------------------

class TestPremiumCompetitiveness(unittest.TestCase):
    def test_cheap(self):
        self.assertEqual(_premium_competitiveness(0), "CHEAP")

    def test_cheap_boundary(self):
        self.assertEqual(_premium_competitiveness(49), "CHEAP")

    def test_competitive(self):
        self.assertEqual(_premium_competitiveness(50), "COMPETITIVE")

    def test_competitive_boundary(self):
        self.assertEqual(_premium_competitiveness(149), "COMPETITIVE")

    def test_expensive(self):
        self.assertEqual(_premium_competitiveness(150), "EXPENSIVE")

    def test_expensive_boundary(self):
        self.assertEqual(_premium_competitiveness(299), "EXPENSIVE")

    def test_very_expensive(self):
        self.assertEqual(_premium_competitiveness(300), "VERY_EXPENSIVE")

    def test_very_expensive_high(self):
        self.assertEqual(_premium_competitiveness(1000), "VERY_EXPENSIVE")


# ---------------------------------------------------------------------------
# Unit tests – _maturity_label
# ---------------------------------------------------------------------------

class TestMaturityLabel(unittest.TestCase):
    def test_new(self):
        self.assertEqual(_maturity_label(0), "NEW")

    def test_new_boundary(self):
        self.assertEqual(_maturity_label(179), "NEW")

    def test_growing(self):
        self.assertEqual(_maturity_label(180), "GROWING")

    def test_growing_boundary(self):
        self.assertEqual(_maturity_label(364), "GROWING")

    def test_mature(self):
        self.assertEqual(_maturity_label(365), "MATURE")

    def test_mature_boundary(self):
        self.assertEqual(_maturity_label(729), "MATURE")

    def test_established(self):
        self.assertEqual(_maturity_label(730), "ESTABLISHED")

    def test_established_large(self):
        self.assertEqual(_maturity_label(2000), "ESTABLISHED")


# ---------------------------------------------------------------------------
# Unit tests – _grade
# ---------------------------------------------------------------------------

class TestGrade(unittest.TestCase):
    def test_S(self):
        self.assertEqual(_grade(90), "S")

    def test_S_100(self):
        self.assertEqual(_grade(100), "S")

    def test_A(self):
        self.assertEqual(_grade(80), "A")

    def test_A_boundary(self):
        self.assertEqual(_grade(89), "A")

    def test_B(self):
        self.assertEqual(_grade(70), "B")

    def test_B_boundary(self):
        self.assertEqual(_grade(79), "B")

    def test_C(self):
        self.assertEqual(_grade(60), "C")

    def test_D(self):
        self.assertEqual(_grade(50), "D")

    def test_F(self):
        self.assertEqual(_grade(49), "F")

    def test_F_zero(self):
        self.assertEqual(_grade(0), "F")


# ---------------------------------------------------------------------------
# Unit tests – _flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):
    def test_no_flags(self):
        result = _flags(5_000_000, 100_000, 10_000, 250, 1_000_000)
        self.assertEqual(result, [])

    def test_undercapitalized(self):
        result = _flags(500_000, 0, 0, 0, 1_000_000)
        self.assertIn("UNDERCAPITALIZED", result)

    def test_high_rejection_rate(self):
        result = _flags(5_000_000, 10_000, 100_000, 0, 1_000_000)
        self.assertIn("HIGH_REJECTION_RATE", result)

    def test_high_rejection_equal_not_flagged(self):
        # rejected == paid, not rejected > paid
        result = _flags(5_000_000, 50_000, 50_000, 0, 1_000_000)
        self.assertNotIn("HIGH_REJECTION_RATE", result)

    def test_no_claims_no_high_rejection(self):
        result = _flags(5_000_000, 0, 0, 0, 1_000_000)
        self.assertNotIn("HIGH_REJECTION_RATE", result)

    def test_overleveraged(self):
        result = _flags(5_000_000, 0, 0, 600, 1_000_000)
        self.assertIn("OVERLEVERAGED", result)

    def test_overleveraged_boundary_not_flagged(self):
        result = _flags(5_000_000, 0, 0, 500, 1_000_000)
        self.assertNotIn("OVERLEVERAGED", result)

    def test_all_flags(self):
        result = _flags(500_000, 10_000, 100_000, 600, 1_000_000)
        self.assertIn("UNDERCAPITALIZED", result)
        self.assertIn("HIGH_REJECTION_RATE", result)
        self.assertIn("OVERLEVERAGED", result)


# ---------------------------------------------------------------------------
# Unit tests – _recommendation
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):
    def test_grade_S(self):
        rec = _recommendation("S", 95.0, 75, 92, [])
        self.assertIn("Reliable protocol", rec)
        self.assertIn("95%", rec)

    def test_grade_A(self):
        rec = _recommendation("A", 88.0, 50, 82, [])
        self.assertIn("Reliable protocol", rec)

    def test_grade_B(self):
        rec = _recommendation("B", 75.0, 50, 72, [])
        self.assertIn("Solid option", rec)
        self.assertIn("72", rec)

    def test_grade_C_no_flags(self):
        rec = _recommendation("C", 60.0, 25, 62, [])
        self.assertIn("Acceptable", rec)
        self.assertIn("0 flags", rec)

    def test_grade_C_with_flags(self):
        rec = _recommendation("C", 60.0, 25, 62, ["UNDERCAPITALIZED"])
        self.assertIn("1 flags", rec)

    def test_grade_D(self):
        rec = _recommendation("D", 40.0, 0, 45, ["HIGH_REJECTION_RATE"])
        self.assertIn("Avoid", rec)
        self.assertIn("HIGH_REJECTION_RATE", rec)

    def test_grade_F_no_flags(self):
        rec = _recommendation("F", 30.0, 0, 20, [])
        self.assertIn("low overall score", rec)

    def test_grade_F_with_flags(self):
        rec = _recommendation("F", 30.0, 0, 20, ["OVERLEVERAGED", "UNDERCAPITALIZED"])
        self.assertIn("OVERLEVERAGED", rec)


# ---------------------------------------------------------------------------
# Integration tests – analyze()
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):
    def test_empty_input(self):
        result = analyze([])
        self.assertEqual(result["protocols"], [])
        self.assertIsNone(result["best_protocol"])
        self.assertEqual(result["average_claims_payment_rate_pct"], 0.0)
        self.assertIn("timestamp", result)

    def test_timestamp_type(self):
        result = analyze([])
        self.assertIsInstance(result["timestamp"], float)


class TestAnalyzeSingleProtocol(unittest.TestCase):
    def setUp(self):
        self.protocol = _make_protocol(
            name="Nexus",
            total_coverage_usd=10_000_000,
            total_capital_usd=2_000_000,
            claims_paid_usd=200_000,
            claims_rejected_usd=20_000,
            annual_premium_rate_bps=80,
            days_since_launch=500,
            cover_types=["smart_contract", "depeg"],
            capital_utilization_pct=250,
        )
        self.result = analyze([self.protocol])

    def test_single_protocol_returned(self):
        self.assertEqual(len(self.result["protocols"]), 1)

    def test_name_preserved(self):
        self.assertEqual(self.result["protocols"][0]["name"], "Nexus")

    def test_best_protocol(self):
        self.assertEqual(self.result["best_protocol"], "Nexus")

    def test_coverage_ratio(self):
        # 10M / 2M = 5.0
        self.assertAlmostEqual(self.result["protocols"][0]["coverage_ratio"], 5.0)

    def test_claims_payment_rate(self):
        # 200k / 220k * 100 ≈ 90.9%
        rate = self.result["protocols"][0]["claims_payment_rate_pct"]
        self.assertAlmostEqual(rate, 200_000 / 220_000 * 100, places=4)

    def test_capital_efficiency_score(self):
        # coverage_ratio=5 → 50
        self.assertEqual(self.result["protocols"][0]["capital_efficiency_score"], 50)

    def test_cover_breadth_score(self):
        # 2 types → 50
        self.assertEqual(self.result["protocols"][0]["cover_breadth_score"], 50)

    def test_premium_competitiveness(self):
        self.assertEqual(self.result["protocols"][0]["premium_competitiveness"], "COMPETITIVE")

    def test_maturity_label(self):
        self.assertEqual(self.result["protocols"][0]["maturity_label"], "MATURE")

    def test_overall_score_range(self):
        score = self.result["protocols"][0]["overall_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_grade_is_valid(self):
        self.assertIn(self.result["protocols"][0]["grade"], ["S", "A", "B", "C", "D", "F"])

    def test_flags_is_list(self):
        self.assertIsInstance(self.result["protocols"][0]["flags"], list)

    def test_recommendation_is_str(self):
        self.assertIsInstance(self.result["protocols"][0]["recommendation"], str)

    def test_average_equals_single_rate(self):
        p = self.result["protocols"][0]
        self.assertAlmostEqual(
            self.result["average_claims_payment_rate_pct"],
            p["claims_payment_rate_pct"],
        )


class TestAnalyzeMultipleProtocols(unittest.TestCase):
    def setUp(self):
        self.protocols = [
            _make_protocol(name="Alpha", total_capital_usd=5_000_000, claims_paid_usd=500_000, claims_rejected_usd=0, days_since_launch=800),
            _make_protocol(name="Beta", total_capital_usd=500_000, claims_paid_usd=0, claims_rejected_usd=200_000, days_since_launch=100),
        ]
        self.result = analyze(self.protocols)

    def test_two_protocols(self):
        self.assertEqual(len(self.result["protocols"]), 2)

    def test_best_protocol_is_alpha(self):
        # Alpha has 100% claims rate, Beta has 0%
        self.assertEqual(self.result["best_protocol"], "Alpha")

    def test_average_claims_rate(self):
        rates = [p["claims_payment_rate_pct"] for p in self.result["protocols"]]
        expected = sum(rates) / 2
        self.assertAlmostEqual(self.result["average_claims_payment_rate_pct"], expected)


class TestAnalyzeEdgeCases(unittest.TestCase):
    def test_zero_capital(self):
        p = _make_protocol(total_capital_usd=0)
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["coverage_ratio"], 0.0)
        self.assertEqual(result["protocols"][0]["capital_efficiency_score"], 0)

    def test_empty_cover_types(self):
        p = _make_protocol(cover_types=[])
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["cover_breadth_score"], 0)

    def test_zero_days(self):
        p = _make_protocol(days_since_launch=0)
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["maturity_label"], "NEW")

    def test_no_claims_ever(self):
        p = _make_protocol(claims_paid_usd=0, claims_rejected_usd=0)
        result = analyze([p])
        self.assertAlmostEqual(result["protocols"][0]["claims_payment_rate_pct"], 100.0)

    def test_undercapitalized_flag(self):
        p = _make_protocol(total_capital_usd=500_000)
        result = analyze([p])
        self.assertIn("UNDERCAPITALIZED", result["protocols"][0]["flags"])

    def test_custom_min_capital(self):
        p = _make_protocol(total_capital_usd=500_000)
        result = analyze([p], config={"min_capital_usd": 300_000})
        self.assertNotIn("UNDERCAPITALIZED", result["protocols"][0]["flags"])

    def test_overleveraged_flag(self):
        p = _make_protocol(capital_utilization_pct=600)
        result = analyze([p])
        self.assertIn("OVERLEVERAGED", result["protocols"][0]["flags"])

    def test_high_rejection_rate_flag(self):
        p = _make_protocol(claims_paid_usd=10_000, claims_rejected_usd=100_000)
        result = analyze([p])
        self.assertIn("HIGH_REJECTION_RATE", result["protocols"][0]["flags"])

    def test_very_cheap_premium(self):
        p = _make_protocol(annual_premium_rate_bps=10)
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["premium_competitiveness"], "CHEAP")

    def test_very_expensive_premium(self):
        p = _make_protocol(annual_premium_rate_bps=500)
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["premium_competitiveness"], "VERY_EXPENSIVE")

    def test_established_maturity(self):
        p = _make_protocol(days_since_launch=1000)
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["maturity_label"], "ESTABLISHED")

    def test_new_maturity(self):
        p = _make_protocol(days_since_launch=30)
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["maturity_label"], "NEW")

    def test_score_clamped_0(self):
        p = _make_protocol(claims_paid_usd=0, claims_rejected_usd=1_000_000, cover_types=[], days_since_launch=0, total_capital_usd=500_000, total_coverage_usd=0)
        result = analyze([p])
        self.assertGreaterEqual(result["protocols"][0]["overall_score"], 0)

    def test_score_clamped_100(self):
        p = _make_protocol(
            claims_paid_usd=1_000_000, claims_rejected_usd=0,
            cover_types=["a", "b", "c", "d", "e"],
            days_since_launch=2000,
            total_coverage_usd=50_000_000,
            total_capital_usd=1_000_000,
        )
        result = analyze([p])
        self.assertLessEqual(result["protocols"][0]["overall_score"], 100)

    def test_result_has_all_keys(self):
        result = analyze([_make_protocol()])
        self.assertIn("protocols", result)
        self.assertIn("best_protocol", result)
        self.assertIn("average_claims_payment_rate_pct", result)
        self.assertIn("timestamp", result)

    def test_protocol_has_all_keys(self):
        result = analyze([_make_protocol()])
        p = result["protocols"][0]
        for key in [
            "name", "coverage_ratio", "claims_payment_rate_pct",
            "capital_efficiency_score", "premium_competitiveness",
            "cover_breadth_score", "maturity_label", "overall_score",
            "grade", "flags", "recommendation",
        ]:
            self.assertIn(key, p)

    def test_best_protocol_is_name_str(self):
        result = analyze([_make_protocol(name="X")])
        self.assertEqual(result["best_protocol"], "X")

    def test_multiple_best_is_highest_score(self):
        p1 = _make_protocol(name="P1", claims_paid_usd=1_000, claims_rejected_usd=999_000, days_since_launch=10, cover_types=[])
        p2 = _make_protocol(name="P2", claims_paid_usd=999_000, claims_rejected_usd=1_000, days_since_launch=800, cover_types=["a","b","c","d"], total_coverage_usd=50_000_000, total_capital_usd=5_000_000)
        result = analyze([p1, p2])
        self.assertEqual(result["best_protocol"], "P2")


# ---------------------------------------------------------------------------
# Log tests
# ---------------------------------------------------------------------------

class TestAppendLog(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._log_path = os.path.join(self._tmpdir, "test_log.json")

    def test_creates_log(self):
        _append_log({"x": 1}, self._log_path)
        self.assertTrue(os.path.exists(self._log_path))

    def test_content_is_list(self):
        _append_log({"x": 1}, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_single_entry(self):
        _append_log({"x": 1}, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["x"], 1)

    def test_multiple_entries(self):
        for i in range(5):
            _append_log({"i": i}, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        for i in range(_RING_BUFFER_MAX + 20):
            _append_log({"i": i}, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), _RING_BUFFER_MAX)

    def test_ring_buffer_keeps_latest(self):
        for i in range(_RING_BUFFER_MAX + 5):
            _append_log({"i": i}, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        # Last entry should be i = RING_BUFFER_MAX + 4
        self.assertEqual(data[-1]["i"], _RING_BUFFER_MAX + 4)

    def test_analyze_appends_log(self):
        """analyze() writes to log file without error."""
        # Just ensure no exception raised; log path in sandbox may not exist
        result = analyze([_make_protocol()])
        self.assertIn("timestamp", result)


# ---------------------------------------------------------------------------
# Scoring formula validation
# ---------------------------------------------------------------------------

class TestScoringFormula(unittest.TestCase):
    def test_full_score_breakdown(self):
        """Manually verify formula for known inputs."""
        # claims_payment_rate=100, cap_eff=50, breadth=50, maturity_norm=68
        # maturity_norm = int(500/730*100) = int(68.49) = 68
        # overall = int(100*0.4 + 50*0.3 + 50*0.2 + 68*0.1)
        #         = int(40 + 15 + 10 + 6.8) = int(71.8) = 71
        p = _make_protocol(
            claims_paid_usd=100_000,
            claims_rejected_usd=0,
            total_coverage_usd=10_000_000,
            total_capital_usd=2_000_000,  # coverage_ratio=5 → eff=50
            cover_types=["a", "b"],       # breadth=50
            days_since_launch=500,        # maturity_norm=68
        )
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["overall_score"], 71)
        self.assertEqual(result["protocols"][0]["grade"], "B")

    def test_zero_score_produces_F(self):
        p = _make_protocol(
            claims_paid_usd=0, claims_rejected_usd=1_000_000,
            total_coverage_usd=0, total_capital_usd=1_000_000,
            cover_types=[], days_since_launch=0,
        )
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["grade"], "F")

    def test_S_grade_scenario(self):
        p = _make_protocol(
            claims_paid_usd=1_000_000, claims_rejected_usd=0,
            total_coverage_usd=100_000_000, total_capital_usd=1_000_000,
            cover_types=["a", "b", "c", "d"],
            days_since_launch=730,
            capital_utilization_pct=100,
        )
        result = analyze([p])
        score = result["protocols"][0]["overall_score"]
        self.assertGreaterEqual(score, 90)
        self.assertEqual(result["protocols"][0]["grade"], "S")


if __name__ == "__main__":
    unittest.main()
