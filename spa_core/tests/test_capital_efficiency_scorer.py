"""Unit tests for spa_core.analytics.capital_efficiency_scorer (MP-681).

Pure stdlib unittest only — no pytest, no numpy, no external deps.
File I/O tests use tempfile so real data/ is never touched.

Run:
    python3 -m unittest spa_core.tests.test_capital_efficiency_scorer -v
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.capital_efficiency_scorer import (
    MAX_ENTRIES,
    CapitalEfficiencyScorer,
    EfficiencyReport,
    PortfolioEfficiencyReport,
    PositionEfficiency,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_position(
    position_id: str = "pos-1",
    protocol: str = "Aave",
    capital_deployed_usd: float = 100_000.0,
    annual_yield_usd: float = 5_000.0,
    annual_yield_pct: float = 5.0,
    risk_score: float = 0.2,
    gas_cost_annual_usd: float = 200.0,
    opportunity_cost_pct: float = 4.25,
) -> PositionEfficiency:
    return PositionEfficiency(
        position_id=position_id,
        protocol=protocol,
        capital_deployed_usd=capital_deployed_usd,
        annual_yield_usd=annual_yield_usd,
        annual_yield_pct=annual_yield_pct,
        risk_score=risk_score,
        gas_cost_annual_usd=gas_cost_annual_usd,
        opportunity_cost_pct=opportunity_cost_pct,
    )


def _make_good_position(pid: str = "good") -> PositionEfficiency:
    """Position that clearly beats risk-free rate with low risk."""
    return _make_position(
        position_id=pid,
        capital_deployed_usd=100_000.0,
        annual_yield_usd=12_000.0,  # 12%
        annual_yield_pct=12.0,
        risk_score=0.1,
        gas_cost_annual_usd=100.0,
        opportunity_cost_pct=4.25,
    )


def _make_poor_position(pid: str = "poor") -> PositionEfficiency:
    """Position barely above risk-free, high gas."""
    return _make_position(
        position_id=pid,
        capital_deployed_usd=100_000.0,
        annual_yield_usd=4_500.0,  # 4.5%
        annual_yield_pct=4.5,
        risk_score=0.6,
        gas_cost_annual_usd=1_000.0,
        opportunity_cost_pct=4.25,
    )


def _scorer_with_tmp() -> tuple[CapitalEfficiencyScorer, Path]:
    tmpdir = Path(tempfile.mkdtemp())
    data_file = tmpdir / "data" / "capital_efficiency_log.json"
    scorer = CapitalEfficiencyScorer(data_file=data_file)
    return scorer, data_file


# ---------------------------------------------------------------------------
# 1. _net_yield_usd
# ---------------------------------------------------------------------------

class TestNetYieldUsd(unittest.TestCase):
    def setUp(self):
        self.s = CapitalEfficiencyScorer()

    def test_basic_net_yield(self):
        pos = _make_position(annual_yield_usd=5000.0, gas_cost_annual_usd=200.0)
        self.assertAlmostEqual(self.s._net_yield_usd(pos), 4800.0)

    def test_never_negative(self):
        pos = _make_position(annual_yield_usd=100.0, gas_cost_annual_usd=500.0)
        self.assertEqual(self.s._net_yield_usd(pos), 0.0)

    def test_zero_gas(self):
        pos = _make_position(annual_yield_usd=3000.0, gas_cost_annual_usd=0.0)
        self.assertAlmostEqual(self.s._net_yield_usd(pos), 3000.0)

    def test_zero_yield(self):
        pos = _make_position(annual_yield_usd=0.0, gas_cost_annual_usd=100.0)
        self.assertAlmostEqual(self.s._net_yield_usd(pos), 0.0)

    def test_gas_equals_yield(self):
        pos = _make_position(annual_yield_usd=1000.0, gas_cost_annual_usd=1000.0)
        self.assertAlmostEqual(self.s._net_yield_usd(pos), 0.0)

    def test_large_values(self):
        pos = _make_position(annual_yield_usd=1_000_000.0, gas_cost_annual_usd=50_000.0)
        self.assertAlmostEqual(self.s._net_yield_usd(pos), 950_000.0)


# ---------------------------------------------------------------------------
# 2. _net_yield_pct
# ---------------------------------------------------------------------------

class TestNetYieldPct(unittest.TestCase):
    def setUp(self):
        self.s = CapitalEfficiencyScorer()

    def test_basic_pct(self):
        pos = _make_position(capital_deployed_usd=100_000.0)
        self.assertAlmostEqual(self.s._net_yield_pct(pos, 5000.0), 5.0)

    def test_zero_capital(self):
        pos = _make_position(capital_deployed_usd=0.0)
        self.assertAlmostEqual(self.s._net_yield_pct(pos, 5000.0), 0.0)

    def test_negative_capital_treated_as_zero(self):
        pos = _make_position(capital_deployed_usd=-1.0)
        self.assertAlmostEqual(self.s._net_yield_pct(pos, 5000.0), 0.0)

    def test_zero_net_yield(self):
        pos = _make_position(capital_deployed_usd=100_000.0)
        self.assertAlmostEqual(self.s._net_yield_pct(pos, 0.0), 0.0)

    def test_small_capital(self):
        pos = _make_position(capital_deployed_usd=1000.0)
        self.assertAlmostEqual(self.s._net_yield_pct(pos, 50.0), 5.0)

    def test_large_capital(self):
        pos = _make_position(capital_deployed_usd=1_000_000.0)
        self.assertAlmostEqual(self.s._net_yield_pct(pos, 40_000.0), 4.0)


# ---------------------------------------------------------------------------
# 3. _excess_return_pct
# ---------------------------------------------------------------------------

class TestExcessReturnPct(unittest.TestCase):
    def setUp(self):
        self.s = CapitalEfficiencyScorer()

    def test_positive_alpha(self):
        self.assertAlmostEqual(self.s._excess_return_pct(8.0, 4.25), 3.75)

    def test_negative_alpha(self):
        self.assertAlmostEqual(self.s._excess_return_pct(3.0, 4.25), -1.25)

    def test_zero_alpha(self):
        self.assertAlmostEqual(self.s._excess_return_pct(4.25, 4.25), 0.0)

    def test_zero_opportunity_cost(self):
        self.assertAlmostEqual(self.s._excess_return_pct(5.0, 0.0), 5.0)

    def test_large_alpha(self):
        self.assertAlmostEqual(self.s._excess_return_pct(20.0, 4.25), 15.75)


# ---------------------------------------------------------------------------
# 4. _yield_per_risk_unit
# ---------------------------------------------------------------------------

class TestYieldPerRiskUnit(unittest.TestCase):
    def setUp(self):
        self.s = CapitalEfficiencyScorer()

    def test_zero_risk_multiplied_by_100(self):
        result = self.s._yield_per_risk_unit(5.0, 0.0)
        self.assertAlmostEqual(result, 500.0)

    def test_zero_risk_zero_yield(self):
        result = self.s._yield_per_risk_unit(0.0, 0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_full_risk(self):
        result = self.s._yield_per_risk_unit(5.0, 1.0)
        self.assertAlmostEqual(result, 5.0)

    def test_half_risk(self):
        result = self.s._yield_per_risk_unit(10.0, 0.5)
        self.assertAlmostEqual(result, 20.0)

    def test_low_risk_high_yield(self):
        result = self.s._yield_per_risk_unit(12.0, 0.1)
        self.assertAlmostEqual(result, 120.0)

    def test_high_risk_low_yield(self):
        result = self.s._yield_per_risk_unit(2.0, 0.8)
        self.assertAlmostEqual(result, 2.5)

    def test_negative_risk_treated_as_zero(self):
        """Negative risk_score ≤ 0 → multiply by 100."""
        result = self.s._yield_per_risk_unit(5.0, -0.1)
        self.assertAlmostEqual(result, 500.0)


# ---------------------------------------------------------------------------
# 5. _capital_efficiency_score
# ---------------------------------------------------------------------------

class TestCapitalEfficiencyScore(unittest.TestCase):
    def setUp(self):
        self.s = CapitalEfficiencyScorer()

    def test_perfect_score(self):
        # excess=10 → excess_component=1.0; ypr=50 → risk_component=1.0
        result = self.s._capital_efficiency_score(10.0, 50.0)
        self.assertAlmostEqual(result, 1.0)

    def test_zero_score(self):
        result = self.s._capital_efficiency_score(0.0, 0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_negative_excess_clamped(self):
        result = self.s._capital_efficiency_score(-5.0, 25.0)
        # excess_component = 0.0 (clamped), risk_component = 25/50 = 0.5
        self.assertAlmostEqual(result, 0.0 * 0.6 + 0.5 * 0.4)

    def test_excess_capped_at_1(self):
        # excess > 10 → excess_component capped at 1.0
        result = self.s._capital_efficiency_score(100.0, 0.0)
        self.assertAlmostEqual(result, 1.0 * 0.6 + 0.0 * 0.4)

    def test_risk_capped_at_1(self):
        # yield_per_risk > 50 → risk_component capped at 1.0
        result = self.s._capital_efficiency_score(0.0, 200.0)
        self.assertAlmostEqual(result, 0.0 * 0.6 + 1.0 * 0.4)

    def test_weights_60_40(self):
        # excess_component = 0.5 (5% excess), risk_component = 0.5 (25 ypr)
        result = self.s._capital_efficiency_score(5.0, 25.0)
        self.assertAlmostEqual(result, 0.5 * 0.6 + 0.5 * 0.4)

    def test_score_in_range(self):
        for excess, ypr in [(3.0, 15.0), (-1.0, 100.0), (10.0, 0.0)]:
            score = self.s._capital_efficiency_score(excess, ypr)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)


# ---------------------------------------------------------------------------
# 6. _efficiency_grade
# ---------------------------------------------------------------------------

class TestEfficiencyGrade(unittest.TestCase):
    def setUp(self):
        self.s = CapitalEfficiencyScorer()

    def test_grade_a(self):
        self.assertEqual(self.s._efficiency_grade(0.8), "A")

    def test_grade_a_exactly(self):
        self.assertEqual(self.s._efficiency_grade(1.0), "A")

    def test_grade_b(self):
        self.assertEqual(self.s._efficiency_grade(0.6), "B")

    def test_grade_b_just_below_a(self):
        self.assertEqual(self.s._efficiency_grade(0.79), "B")

    def test_grade_c(self):
        self.assertEqual(self.s._efficiency_grade(0.4), "C")

    def test_grade_c_just_below_b(self):
        self.assertEqual(self.s._efficiency_grade(0.59), "C")

    def test_grade_d(self):
        self.assertEqual(self.s._efficiency_grade(0.2), "D")

    def test_grade_d_just_below_c(self):
        self.assertEqual(self.s._efficiency_grade(0.39), "D")

    def test_grade_f(self):
        self.assertEqual(self.s._efficiency_grade(0.0), "F")

    def test_grade_f_just_below_d(self):
        self.assertEqual(self.s._efficiency_grade(0.19), "F")


# ---------------------------------------------------------------------------
# 7. _recommendation
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):
    def setUp(self):
        self.s = CapitalEfficiencyScorer()

    def test_grade_a_recommendation(self):
        msg = self.s._recommendation("A", 5.0, True)
        self.assertIn("✅", msg)
        self.assertIn("maintain or increase", msg)

    def test_grade_b_recommendation(self):
        msg = self.s._recommendation("B", 3.0, True)
        self.assertIn("📋", msg)
        self.assertIn("core allocation", msg)

    def test_grade_c_recommendation(self):
        msg = self.s._recommendation("C", 1.0, True)
        self.assertIn("⚠️", msg)
        self.assertIn("monitor", msg)

    def test_grade_d_recommendation(self):
        msg = self.s._recommendation("D", -0.5, False)
        self.assertIn("🚨", msg)
        self.assertIn("reallocation", msg)

    def test_grade_f_recommendation(self):
        msg = self.s._recommendation("F", -2.0, False)
        self.assertIn("🚨", msg)

    def test_not_worth_it_note_appended(self):
        msg = self.s._recommendation("D", -1.0, False)
        self.assertIn("risk-free", msg)

    def test_worth_it_no_extra_note(self):
        msg = self.s._recommendation("D", 2.0, True)
        self.assertNotIn("risk-free", msg)

    def test_grade_f_not_worth_it(self):
        msg = self.s._recommendation("F", -3.0, False)
        self.assertIn("risk-free", msg)


# ---------------------------------------------------------------------------
# 8. score_position integration
# ---------------------------------------------------------------------------

class TestScorePosition(unittest.TestCase):
    def setUp(self):
        self.s = CapitalEfficiencyScorer()

    def test_returns_efficiency_report(self):
        pos = _make_good_position()
        report = self.s.score_position(pos)
        self.assertIsInstance(report, EfficiencyReport)

    def test_position_id_preserved(self):
        pos = _make_position(position_id="my-pos")
        report = self.s.score_position(pos)
        self.assertEqual(report.position_id, "my-pos")

    def test_protocol_preserved(self):
        pos = _make_position(protocol="Compound")
        report = self.s.score_position(pos)
        self.assertEqual(report.protocol, "Compound")

    def test_net_yield_usd_correct(self):
        pos = _make_position(annual_yield_usd=5000.0, gas_cost_annual_usd=200.0)
        report = self.s.score_position(pos)
        self.assertAlmostEqual(report.net_yield_usd, 4800.0)

    def test_net_yield_pct_correct(self):
        pos = _make_position(capital_deployed_usd=100_000.0,
                              annual_yield_usd=5000.0, gas_cost_annual_usd=0.0)
        report = self.s.score_position(pos)
        self.assertAlmostEqual(report.net_yield_pct, 5.0)

    def test_excess_return_correct(self):
        pos = _make_position(capital_deployed_usd=100_000.0,
                              annual_yield_usd=5000.0, gas_cost_annual_usd=0.0,
                              opportunity_cost_pct=4.0)
        report = self.s.score_position(pos)
        self.assertAlmostEqual(report.excess_return_pct, 1.0)

    def test_is_worth_it_true(self):
        pos = _make_good_position()
        report = self.s.score_position(pos)
        self.assertTrue(report.is_worth_it)

    def test_is_worth_it_false(self):
        pos = _make_poor_position()
        report = self.s.score_position(pos)
        self.assertFalse(report.is_worth_it)

    def test_efficiency_score_in_range(self):
        for pos in [_make_good_position(), _make_poor_position()]:
            report = self.s.score_position(pos)
            self.assertGreaterEqual(report.capital_efficiency_score, 0.0)
            self.assertLessEqual(report.capital_efficiency_score, 1.0)

    def test_grade_present(self):
        pos = _make_good_position()
        report = self.s.score_position(pos)
        self.assertIn(report.efficiency_grade, ["A", "B", "C", "D", "F"])

    def test_recommendation_not_empty(self):
        pos = _make_good_position()
        report = self.s.score_position(pos)
        self.assertGreater(len(report.recommendation), 0)

    def test_good_position_gets_high_score(self):
        pos = _make_good_position()
        report = self.s.score_position(pos)
        self.assertGreater(report.capital_efficiency_score, 0.5)

    def test_poor_position_gets_low_score(self):
        pos = _make_poor_position()
        report = self.s.score_position(pos)
        self.assertLess(report.capital_efficiency_score, 0.5)


# ---------------------------------------------------------------------------
# 9. score_portfolio
# ---------------------------------------------------------------------------

class TestScorePortfolio(unittest.TestCase):
    def setUp(self):
        self.s = CapitalEfficiencyScorer()

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            self.s.score_portfolio([])

    def test_returns_portfolio_report(self):
        report = self.s.score_portfolio([_make_good_position()])
        self.assertIsInstance(report, PortfolioEfficiencyReport)

    def test_single_position_consistent(self):
        pos = _make_good_position("p1")
        portfolio = self.s.score_portfolio([pos])
        single = self.s.score_position(pos)
        self.assertAlmostEqual(
            portfolio.portfolio_efficiency_score,
            single.capital_efficiency_score,
            places=9,
        )

    def test_total_capital(self):
        p1 = _make_position("p1", capital_deployed_usd=60_000.0)
        p2 = _make_position("p2", capital_deployed_usd=40_000.0)
        report = self.s.score_portfolio([p1, p2])
        self.assertAlmostEqual(report.total_capital_usd, 100_000.0)

    def test_total_net_yield(self):
        p1 = _make_position("p1", annual_yield_usd=3000.0, gas_cost_annual_usd=0.0)
        p2 = _make_position("p2", annual_yield_usd=2000.0, gas_cost_annual_usd=0.0)
        report = self.s.score_portfolio([p1, p2])
        self.assertAlmostEqual(report.total_net_yield_usd, 5000.0)

    def test_portfolio_net_yield_pct(self):
        p1 = _make_position("p1", capital_deployed_usd=100_000.0,
                              annual_yield_usd=5000.0, gas_cost_annual_usd=0.0)
        report = self.s.score_portfolio([p1])
        self.assertAlmostEqual(report.portfolio_net_yield_pct, 5.0)

    def test_weighted_risk_score_single(self):
        pos = _make_position(risk_score=0.3)
        report = self.s.score_portfolio([pos])
        self.assertAlmostEqual(report.weighted_risk_score, 0.3)

    def test_weighted_risk_score_two(self):
        p1 = _make_position("p1", capital_deployed_usd=60_000.0, risk_score=0.2)
        p2 = _make_position("p2", capital_deployed_usd=40_000.0, risk_score=0.5)
        report = self.s.score_portfolio([p1, p2])
        expected = (60_000 * 0.2 + 40_000 * 0.5) / 100_000
        self.assertAlmostEqual(report.weighted_risk_score, expected)

    def test_least_efficient_id(self):
        good = _make_good_position("good")
        poor = _make_poor_position("poor")
        report = self.s.score_portfolio([good, poor])
        self.assertEqual(report.least_efficient, "poor")

    def test_most_efficient_id(self):
        good = _make_good_position("good")
        poor = _make_poor_position("poor")
        report = self.s.score_portfolio([good, poor])
        self.assertEqual(report.most_efficient, "good")

    def test_portfolio_grade_present(self):
        report = self.s.score_portfolio([_make_good_position()])
        self.assertIn(report.portfolio_grade, ["A", "B", "C", "D", "F"])

    def test_positions_list_length(self):
        positions = [_make_position(f"p{i}") for i in range(3)]
        report = self.s.score_portfolio(positions)
        self.assertEqual(len(report.positions), 3)

    def test_recommendations_list(self):
        report = self.s.score_portfolio([_make_good_position()])
        self.assertIsInstance(report.recommendations, list)

    def test_high_risk_recommendation(self):
        pos = _make_position(risk_score=0.9)
        report = self.s.score_portfolio([pos])
        combined = " ".join(report.recommendations)
        self.assertIn("rebalance", combined)

    def test_low_yield_recommendation(self):
        pos = _make_position(
            capital_deployed_usd=100_000.0,
            annual_yield_usd=2000.0,  # 2%
            gas_cost_annual_usd=0.0,
            risk_score=0.1,
        )
        report = self.s.score_portfolio([pos])
        combined = " ".join(report.recommendations)
        self.assertIn("below 3%", combined)

    def test_portfolio_yield_per_risk(self):
        pos = _make_position(
            capital_deployed_usd=100_000.0,
            annual_yield_usd=5000.0,
            gas_cost_annual_usd=0.0,
            risk_score=0.5,
        )
        report = self.s.score_portfolio([pos])
        # net_yield_pct = 5.0, weighted_risk = 0.5 → ratio = 10.0
        self.assertAlmostEqual(report.portfolio_yield_per_risk, 10.0)

    def test_single_position_least_and_most_same(self):
        pos = _make_good_position("only")
        report = self.s.score_portfolio([pos])
        self.assertEqual(report.least_efficient, "only")
        self.assertEqual(report.most_efficient, "only")


# ---------------------------------------------------------------------------
# 10. save_results + ring-buffer + atomic write
# ---------------------------------------------------------------------------

class TestSaveResults(unittest.TestCase):

    def test_save_creates_file(self):
        scorer, data_file = _scorer_with_tmp()
        report = scorer.score_portfolio([_make_good_position()])
        scorer.save_results(report)
        self.assertTrue(data_file.exists())

    def test_save_valid_json(self):
        scorer, data_file = _scorer_with_tmp()
        report = scorer.score_portfolio([_make_good_position()])
        scorer.save_results(report)
        with open(data_file) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_save_has_timestamp(self):
        scorer, data_file = _scorer_with_tmp()
        report = scorer.score_portfolio([_make_good_position()])
        scorer.save_results(report)
        with open(data_file) as fh:
            data = json.load(fh)
        self.assertIn("timestamp", data[0])

    def test_save_has_report(self):
        scorer, data_file = _scorer_with_tmp()
        report = scorer.score_portfolio([_make_good_position()])
        scorer.save_results(report)
        with open(data_file) as fh:
            data = json.load(fh)
        self.assertIn("report", data[0])

    def test_ring_buffer_trims(self):
        scorer, data_file = _scorer_with_tmp()
        report = scorer.score_portfolio([_make_good_position()])
        for _ in range(MAX_ENTRIES + 5):
            scorer.save_results(report)
        with open(data_file) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_atomic_write_no_tmp_remaining(self):
        scorer, data_file = _scorer_with_tmp()
        report = scorer.score_portfolio([_make_good_position()])
        scorer.save_results(report)
        tmp = data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_multiple_saves_accumulate(self):
        scorer, data_file = _scorer_with_tmp()
        report = scorer.score_portfolio([_make_good_position()])
        scorer.save_results(report)
        scorer.save_results(report)
        with open(data_file) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)


# ---------------------------------------------------------------------------
# 11. load_history
# ---------------------------------------------------------------------------

class TestLoadHistory(unittest.TestCase):

    def test_missing_file_returns_empty(self):
        scorer = CapitalEfficiencyScorer(
            data_file=Path(tempfile.mkdtemp()) / "nonexistent.json"
        )
        self.assertEqual(scorer.load_history(), [])

    def test_corrupt_file_returns_empty(self):
        tmpdir = Path(tempfile.mkdtemp())
        data_file = tmpdir / "corrupt.json"
        data_file.write_text("NOT_JSON")
        scorer = CapitalEfficiencyScorer(data_file=data_file)
        self.assertEqual(scorer.load_history(), [])

    def test_empty_list_returns_empty(self):
        tmpdir = Path(tempfile.mkdtemp())
        data_file = tmpdir / "empty.json"
        data_file.write_text("[]")
        scorer = CapitalEfficiencyScorer(data_file=data_file)
        self.assertEqual(scorer.load_history(), [])

    def test_round_trip(self):
        scorer, data_file = _scorer_with_tmp()
        report = scorer.score_portfolio([_make_good_position()])
        scorer.save_results(report)
        history = scorer.load_history()
        self.assertEqual(len(history), 1)
        self.assertIn("report", history[0])

    def test_non_list_file_returns_empty(self):
        tmpdir = Path(tempfile.mkdtemp())
        data_file = tmpdir / "dict.json"
        data_file.write_text('{"key": "value"}')
        scorer = CapitalEfficiencyScorer(data_file=data_file)
        self.assertEqual(scorer.load_history(), [])


if __name__ == "__main__":
    unittest.main()
