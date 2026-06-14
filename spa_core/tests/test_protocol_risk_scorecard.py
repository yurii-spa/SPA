"""
Tests for MP-751: ProtocolRiskScorecard
Uses unittest only. ≥65 tests.
"""

import json
import os
import sys
import tempfile
import unittest

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.protocol_risk_scorecard import (
    WEIGHTS,
    ProtocolRiskScore,
    RiskDimension,
    ScorecardResult,
    _portfolio_risk_label,
    _recommendation,
    compute_composite,
    load_history,
    risk_label,
    save_results,
    score_portfolio,
    score_protocol,
    top_risk_factors,
)


# ---------------------------------------------------------------------------
# WEIGHTS
# ---------------------------------------------------------------------------

class TestWeights(unittest.TestCase):

    def test_weights_sum_to_1(self):
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0, places=9)

    def test_weights_has_7_dimensions(self):
        self.assertEqual(len(WEIGHTS), 7)

    def test_smart_contract_weight(self):
        self.assertAlmostEqual(WEIGHTS["smart_contract"], 0.25, places=9)

    def test_liquidity_weight(self):
        self.assertAlmostEqual(WEIGHTS["liquidity"], 0.20, places=9)

    def test_governance_weight(self):
        self.assertAlmostEqual(WEIGHTS["governance"], 0.15, places=9)

    def test_oracle_weight(self):
        self.assertAlmostEqual(WEIGHTS["oracle"], 0.15, places=9)

    def test_counterparty_weight(self):
        self.assertAlmostEqual(WEIGHTS["counterparty"], 0.10, places=9)

    def test_market_weight(self):
        self.assertAlmostEqual(WEIGHTS["market"], 0.10, places=9)

    def test_regulatory_weight(self):
        self.assertAlmostEqual(WEIGHTS["regulatory"], 0.05, places=9)


# ---------------------------------------------------------------------------
# compute_composite
# ---------------------------------------------------------------------------

class TestComputeComposite(unittest.TestCase):

    def test_all_zeros_returns_zero(self):
        scores = {d: 0.0 for d in WEIGHTS}
        self.assertAlmostEqual(compute_composite(scores), 0.0, places=9)

    def test_all_100_returns_100(self):
        scores = {d: 100.0 for d in WEIGHTS}
        self.assertAlmostEqual(compute_composite(scores), 100.0, places=9)

    def test_formula_manual(self):
        scores = {
            "smart_contract": 40,
            "liquidity":      30,
            "governance":     50,
            "oracle":         20,
            "counterparty":   60,
            "market":         10,
            "regulatory":     80,
        }
        expected = (40 * 0.25 + 30 * 0.20 + 50 * 0.15 +
                    20 * 0.15 + 60 * 0.10 + 10 * 0.10 + 80 * 0.05)
        self.assertAlmostEqual(compute_composite(scores), expected, places=6)

    def test_partial_dimensions_uses_zero_for_missing(self):
        scores = {"smart_contract": 100}
        result = compute_composite(scores)
        self.assertAlmostEqual(result, 100 * 0.25, places=6)

    def test_result_in_range(self):
        scores = {d: 50.0 for d in WEIGHTS}
        result = compute_composite(scores)
        self.assertGreaterEqual(result, 0)
        self.assertLessEqual(result, 100)


# ---------------------------------------------------------------------------
# risk_label
# ---------------------------------------------------------------------------

class TestRiskLabel(unittest.TestCase):

    def test_score_0_low_risk(self):
        self.assertEqual(risk_label(0.0), "LOW_RISK")

    def test_score_24_low_risk(self):
        self.assertEqual(risk_label(24.9), "LOW_RISK")

    def test_score_25_moderate_risk(self):
        self.assertEqual(risk_label(25.0), "MODERATE_RISK")

    def test_score_49_moderate_risk(self):
        self.assertEqual(risk_label(49.9), "MODERATE_RISK")

    def test_score_50_moderate_risk(self):
        self.assertEqual(risk_label(50.0), "MODERATE_RISK")

    def test_score_50_1_high_risk(self):
        self.assertEqual(risk_label(50.1), "HIGH_RISK")

    def test_score_74_high_risk(self):
        self.assertEqual(risk_label(74.9), "HIGH_RISK")

    def test_score_75_critical_risk(self):
        self.assertEqual(risk_label(75.0), "CRITICAL_RISK")

    def test_score_100_critical_risk(self):
        self.assertEqual(risk_label(100.0), "CRITICAL_RISK")

    def test_four_distinct_labels(self):
        labels = {risk_label(s) for s in (0, 30, 60, 80)}
        self.assertEqual(len(labels), 4)


# ---------------------------------------------------------------------------
# top_risk_factors
# ---------------------------------------------------------------------------

class TestTopRiskFactors(unittest.TestCase):

    def test_returns_two_factors(self):
        scores = {d: float(i * 10) for i, d in enumerate(WEIGHTS)}
        result = top_risk_factors(scores, n=2)
        self.assertEqual(len(result), 2)

    def test_returns_highest_scored_dimensions(self):
        scores = {d: 0.0 for d in WEIGHTS}
        scores["governance"] = 90.0
        scores["market"] = 80.0
        result = top_risk_factors(scores, n=2)
        self.assertIn("governance", result)
        self.assertIn("market", result)

    def test_deterministic_ordering_same_scores(self):
        """With equal scores, result is alphabetically consistent."""
        scores = {d: 50.0 for d in WEIGHTS}
        r1 = top_risk_factors(scores, n=2)
        r2 = top_risk_factors(scores, n=2)
        self.assertEqual(r1, r2)

    def test_top_1_returns_single(self):
        scores = {d: float(i) for i, d in enumerate(WEIGHTS)}
        result = top_risk_factors(scores, n=1)
        self.assertEqual(len(result), 1)

    def test_highest_score_is_first(self):
        scores = {d: 0.0 for d in WEIGHTS}
        scores["regulatory"] = 100.0
        result = top_risk_factors(scores, n=1)
        self.assertEqual(result[0], "regulatory")


# ---------------------------------------------------------------------------
# score_protocol (ProtocolRiskScore)
# ---------------------------------------------------------------------------

class TestScoreProtocol(unittest.TestCase):

    def _low_risk_score(self):
        return score_protocol("Aave", "Ethereum",
                               smart_contract=10, liquidity=5, governance=10,
                               oracle=10, counterparty=5, market=10, regulatory=5)

    def _high_risk_score(self):
        # composite = 85*0.25+80*0.20+80*0.15+80*0.15+80*0.10+80*0.10+80*0.05 = 81.25 → CRITICAL
        return score_protocol("NewProto", "BSC",
                               smart_contract=85, liquidity=80, governance=80,
                               oracle=80, counterparty=80, market=80, regulatory=80)

    def test_dimensions_list_has_7_entries(self):
        ps = self._low_risk_score()
        self.assertEqual(len(ps.dimensions), 7)

    def test_each_dimension_weighted_score(self):
        ps = self._low_risk_score()
        for d in ps.dimensions:
            self.assertAlmostEqual(d.weighted_score, d.score * d.weight, places=9)

    def test_composite_risk_score_matches_formula(self):
        ps = self._low_risk_score()
        scores = {
            "smart_contract": ps.smart_contract_risk,
            "liquidity":      ps.liquidity_risk,
            "governance":     ps.governance_risk,
            "oracle":         ps.oracle_risk,
            "counterparty":   ps.counterparty_risk,
            "market":         ps.market_risk,
            "regulatory":     ps.regulatory_risk,
        }
        expected = compute_composite(scores)
        self.assertAlmostEqual(ps.composite_risk_score, expected, places=6)

    def test_risk_label_low_risk(self):
        ps = self._low_risk_score()
        self.assertEqual(ps.risk_label, "LOW_RISK")

    def test_risk_label_critical_risk(self):
        ps = self._high_risk_score()
        self.assertEqual(ps.risk_label, "CRITICAL_RISK")

    def test_is_investment_grade_true_when_score_le_50(self):
        ps = self._low_risk_score()
        self.assertTrue(ps.is_investment_grade)

    def test_is_investment_grade_false_when_score_gt_50(self):
        ps = self._high_risk_score()
        self.assertFalse(ps.is_investment_grade)

    def test_is_investment_grade_at_exactly_50(self):
        # We need to find inputs that produce exactly 50.0
        # Use all dims at 50: composite = 50
        ps = score_protocol("Mid", "ETH",
                             smart_contract=50, liquidity=50, governance=50,
                             oracle=50, counterparty=50, market=50, regulatory=50)
        self.assertTrue(ps.is_investment_grade)  # 50 <= 50

    def test_top_risk_factors_has_2_items(self):
        ps = self._low_risk_score()
        self.assertEqual(len(ps.top_risk_factors), 2)

    def test_recommendation_low_risk(self):
        ps = self._low_risk_score()
        self.assertIn("conservative", ps.recommendation.lower())

    def test_recommendation_critical_risk(self):
        ps = self._high_risk_score()
        self.assertIn("critical", ps.recommendation.lower())

    def test_recommendation_high_risk(self):
        ps = score_protocol("H", "ETH",
                             smart_contract=65, liquidity=60, governance=65,
                             oracle=60, counterparty=55, market=60, regulatory=65)
        self.assertEqual(ps.risk_label, "HIGH_RISK")
        self.assertIn("high risk", ps.recommendation.lower())

    def test_recommendation_moderate_risk(self):
        ps = score_protocol("M", "ETH",
                             smart_contract=30, liquidity=30, governance=30,
                             oracle=30, counterparty=30, market=30, regulatory=30)
        self.assertEqual(ps.risk_label, "MODERATE_RISK")
        self.assertIn("acceptable", ps.recommendation.lower())

    def test_dimension_names_present(self):
        ps = self._low_risk_score()
        dim_names = {d.name for d in ps.dimensions}
        self.assertEqual(dim_names, set(WEIGHTS.keys()))


# ---------------------------------------------------------------------------
# score_portfolio / ScorecardResult
# ---------------------------------------------------------------------------

class TestScorePortfolio(unittest.TestCase):

    def _protocols(self):
        return [
            {
                "protocol": "Aave", "chain": "ETH",
                "smart_contract": 10, "liquidity": 10, "governance": 15,
                "oracle": 10, "counterparty": 5, "market": 10, "regulatory": 10,
            },
            {
                "protocol": "Risky", "chain": "BSC",
                "smart_contract": 85, "liquidity": 75, "governance": 80,
                "oracle": 80, "counterparty": 70, "market": 75, "regulatory": 90,
            },
            {
                "protocol": "Mid", "chain": "Poly",
                "smart_contract": 40, "liquidity": 35, "governance": 40,
                "oracle": 35, "counterparty": 30, "market": 35, "regulatory": 40,
            },
        ]

    def test_safest_protocol_is_min_composite(self):
        result = score_portfolio(self._protocols())
        self.assertEqual(result.safest_protocol, "Aave")

    def test_riskiest_protocol_is_max_composite(self):
        result = score_portfolio(self._protocols())
        self.assertEqual(result.riskiest_protocol, "Risky")

    def test_investment_grade_count(self):
        result = score_portfolio(self._protocols())
        expected = sum(1 for p in result.protocols if p.is_investment_grade)
        self.assertEqual(result.investment_grade_count, expected)

    def test_avg_risk_score_formula(self):
        result = score_portfolio(self._protocols())
        expected = sum(p.composite_risk_score for p in result.protocols) / len(result.protocols)
        self.assertAlmostEqual(result.avg_risk_score, expected, places=6)

    def test_low_risk_count(self):
        result = score_portfolio(self._protocols())
        expected = sum(1 for p in result.protocols if p.risk_label == "LOW_RISK")
        self.assertEqual(result.low_risk_count, expected)

    def test_moderate_risk_count(self):
        result = score_portfolio(self._protocols())
        expected = sum(1 for p in result.protocols if p.risk_label == "MODERATE_RISK")
        self.assertEqual(result.moderate_risk_count, expected)

    def test_high_risk_count(self):
        result = score_portfolio(self._protocols())
        expected = sum(1 for p in result.protocols if p.risk_label == "HIGH_RISK")
        self.assertEqual(result.high_risk_count, expected)

    def test_critical_risk_count(self):
        result = score_portfolio(self._protocols())
        expected = sum(1 for p in result.protocols if p.risk_label == "CRITICAL_RISK")
        self.assertEqual(result.critical_risk_count, expected)

    def test_portfolio_risk_label_conservative(self):
        protos = [
            {"protocol": "A", "chain": "ETH",
             "smart_contract": 5, "liquidity": 5, "governance": 5,
             "oracle": 5, "counterparty": 5, "market": 5, "regulatory": 5},
        ]
        result = score_portfolio(protos)
        self.assertEqual(result.portfolio_risk_label, "CONSERVATIVE")

    def test_portfolio_risk_label_speculative(self):
        protos = [
            {"protocol": "B", "chain": "ETH",
             "smart_contract": 90, "liquidity": 90, "governance": 90,
             "oracle": 90, "counterparty": 90, "market": 90, "regulatory": 90},
        ]
        result = score_portfolio(protos)
        self.assertEqual(result.portfolio_risk_label, "SPECULATIVE")

    def test_portfolio_risk_label_balanced(self):
        protos = [
            {"protocol": "C", "chain": "ETH",
             "smart_contract": 35, "liquidity": 35, "governance": 35,
             "oracle": 35, "counterparty": 35, "market": 35, "regulatory": 35},
        ]
        result = score_portfolio(protos)
        self.assertEqual(result.portfolio_risk_label, "BALANCED")

    def test_portfolio_risk_label_aggressive(self):
        protos = [
            {"protocol": "D", "chain": "ETH",
             "smart_contract": 60, "liquidity": 60, "governance": 60,
             "oracle": 60, "counterparty": 60, "market": 60, "regulatory": 60},
        ]
        result = score_portfolio(protos)
        self.assertEqual(result.portfolio_risk_label, "AGGRESSIVE")

    def test_empty_portfolio_returns_result(self):
        result = score_portfolio([])
        self.assertIsInstance(result, ScorecardResult)
        self.assertEqual(result.protocols, [])

    def test_single_protocol_safest_and_riskiest_same(self):
        protos = [
            {"protocol": "Solo", "chain": "ETH",
             "smart_contract": 50, "liquidity": 50, "governance": 50,
             "oracle": 50, "counterparty": 50, "market": 50, "regulatory": 50},
        ]
        result = score_portfolio(protos)
        self.assertEqual(result.safest_protocol, "Solo")
        self.assertEqual(result.riskiest_protocol, "Solo")

    def test_all_same_score_same_label(self):
        protos = [
            {"protocol": f"P{i}", "chain": "ETH",
             "smart_contract": 20, "liquidity": 20, "governance": 20,
             "oracle": 20, "counterparty": 20, "market": 20, "regulatory": 20}
            for i in range(3)
        ]
        result = score_portfolio(protos)
        labels = {p.risk_label for p in result.protocols}
        self.assertEqual(len(labels), 1)

    def test_recommendation_summary_string(self):
        result = score_portfolio(self._protocols())
        self.assertIsInstance(result.recommendation_summary, str)
        self.assertGreater(len(result.recommendation_summary), 0)

    def test_protocols_list_length_matches_input(self):
        result = score_portfolio(self._protocols())
        self.assertEqual(len(result.protocols), 3)


# ---------------------------------------------------------------------------
# _portfolio_risk_label helper
# ---------------------------------------------------------------------------

class TestPortfolioRiskLabel(unittest.TestCase):

    def test_below_25_conservative(self):
        self.assertEqual(_portfolio_risk_label(0), "CONSERVATIVE")
        self.assertEqual(_portfolio_risk_label(24.9), "CONSERVATIVE")

    def test_25_to_50_balanced(self):
        self.assertEqual(_portfolio_risk_label(25), "BALANCED")
        self.assertEqual(_portfolio_risk_label(49.9), "BALANCED")

    def test_50_to_75_aggressive(self):
        self.assertEqual(_portfolio_risk_label(50), "AGGRESSIVE")
        self.assertEqual(_portfolio_risk_label(74.9), "AGGRESSIVE")

    def test_75_plus_speculative(self):
        self.assertEqual(_portfolio_risk_label(75), "SPECULATIVE")
        self.assertEqual(_portfolio_risk_label(100), "SPECULATIVE")


# ---------------------------------------------------------------------------
# recommendation helper
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):

    def test_critical_risk_recommendation(self):
        rec = _recommendation("CRITICAL_RISK")
        self.assertIn("critical", rec.lower())

    def test_high_risk_recommendation(self):
        rec = _recommendation("HIGH_RISK")
        self.assertIn("high risk", rec.lower())

    def test_moderate_risk_recommendation(self):
        rec = _recommendation("MODERATE_RISK")
        self.assertIn("acceptable", rec.lower())

    def test_low_risk_recommendation(self):
        rec = _recommendation("LOW_RISK")
        self.assertIn("conservative", rec.lower())

    def test_all_four_distinct(self):
        recs = {_recommendation(l) for l in
                ("LOW_RISK", "MODERATE_RISK", "HIGH_RISK", "CRITICAL_RISK")}
        self.assertEqual(len(recs), 4)


# ---------------------------------------------------------------------------
# save / load / ring-buffer
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):

    def _tmp_path(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        return path

    def _sample_protocols(self):
        return [
            {"protocol": "TestProto", "chain": "ETH",
             "smart_contract": 20, "liquidity": 15, "governance": 25,
             "oracle": 20, "counterparty": 10, "market": 15, "regulatory": 10},
        ]

    def test_save_creates_file(self):
        path = self._tmp_path()
        result = score_portfolio(self._sample_protocols())
        save_results(result, path)
        self.assertTrue(os.path.exists(path))

    def test_load_returns_list(self):
        path = self._tmp_path()
        result = score_portfolio(self._sample_protocols())
        save_results(result, path)
        history = load_history(path)
        self.assertIsInstance(history, list)

    def test_save_load_round_trip(self):
        path = self._tmp_path()
        result = score_portfolio(self._sample_protocols())
        save_results(result, path)
        history = load_history(path)
        self.assertEqual(len(history), 1)

    def test_load_nonexistent_returns_empty_list(self):
        history = load_history("/tmp/nonexistent_risk_scorecard_xyz_test.json")
        self.assertEqual(history, [])

    def test_ring_buffer_cap_100(self):
        path = self._tmp_path()
        result = score_portfolio(self._sample_protocols())
        for _ in range(105):
            save_results(result, path)
        history = load_history(path)
        self.assertLessEqual(len(history), 100)

    def test_saved_entry_has_timestamp(self):
        path = self._tmp_path()
        result = score_portfolio(self._sample_protocols())
        save_results(result, path)
        history = load_history(path)
        self.assertIn("timestamp", history[0])

    def test_saved_entry_has_protocols_list(self):
        path = self._tmp_path()
        result = score_portfolio(self._sample_protocols())
        save_results(result, path)
        history = load_history(path)
        self.assertIn("protocols", history[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
