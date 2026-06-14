"""
Tests for MP-685: DebtRatioAnalyzer
≥60 unittest tests. Pure stdlib (unittest only).
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from spa_core.analytics.debt_ratio_analyzer import (
    DebtRatioAnalyzer,
    DebtPosition,
    DebtRatioReport,
    PortfolioLeverageReport,
    DATA_FILE,
    MAX_ENTRIES,
)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _pos(
    position_id="p1",
    protocol="Aave V3",
    strategy="YIELD_LOOP",
    gross_assets_usd=100_000.0,
    net_assets_usd=50_000.0,
    total_debt_usd=50_000.0,
    interest_rate_pct=3.0,
    gross_yield_pct=5.0,
):
    return DebtPosition(
        position_id=position_id,
        protocol=protocol,
        strategy=strategy,
        gross_assets_usd=gross_assets_usd,
        net_assets_usd=net_assets_usd,
        total_debt_usd=total_debt_usd,
        interest_rate_pct=interest_rate_pct,
        gross_yield_pct=gross_yield_pct,
    )


# ─── TestLeverageRatio ───────────────────────────────────────────────────────

class TestLeverageRatio(unittest.TestCase):
    def setUp(self):
        self.az = DebtRatioAnalyzer()

    def test_leverage_standard(self):
        # gross=100k, net=50k → 2.0
        self.assertAlmostEqual(self.az._leverage_ratio(100_000.0, 50_000.0), 2.0)

    def test_leverage_no_debt(self):
        # gross=net=50k → 1.0
        self.assertAlmostEqual(self.az._leverage_ratio(50_000.0, 50_000.0), 1.0)

    def test_leverage_zero_net_returns_999(self):
        self.assertAlmostEqual(self.az._leverage_ratio(100_000.0, 0.0), 999.0)

    def test_leverage_negative_net_returns_999(self):
        self.assertAlmostEqual(self.az._leverage_ratio(100_000.0, -1000.0), 999.0)

    def test_leverage_3x(self):
        # gross=300k, net=100k → 3.0
        self.assertAlmostEqual(self.az._leverage_ratio(300_000.0, 100_000.0), 3.0)

    def test_leverage_fractional(self):
        self.assertAlmostEqual(self.az._leverage_ratio(175_000.0, 100_000.0), 1.75)


# ─── TestDebtToEquity ────────────────────────────────────────────────────────

class TestDebtToEquity(unittest.TestCase):
    def setUp(self):
        self.az = DebtRatioAnalyzer()

    def test_d2e_standard(self):
        # debt=50k, net=50k → 1.0
        self.assertAlmostEqual(self.az._debt_to_equity(50_000.0, 50_000.0), 1.0)

    def test_d2e_zero_net_returns_999(self):
        self.assertAlmostEqual(self.az._debt_to_equity(50_000.0, 0.0), 999.0)

    def test_d2e_zero_debt(self):
        self.assertAlmostEqual(self.az._debt_to_equity(0.0, 50_000.0), 0.0)

    def test_d2e_high_debt(self):
        # debt=200k, net=50k → 4.0
        self.assertAlmostEqual(self.az._debt_to_equity(200_000.0, 50_000.0), 4.0)

    def test_d2e_negative_net_returns_999(self):
        self.assertAlmostEqual(self.az._debt_to_equity(50_000.0, -1.0), 999.0)


# ─── TestInterestCoverage ────────────────────────────────────────────────────

class TestInterestCoverage(unittest.TestCase):
    def setUp(self):
        self.az = DebtRatioAnalyzer()

    def test_coverage_no_interest_cost_returns_999(self):
        self.assertAlmostEqual(self.az._interest_coverage(5000.0, 0.0), 999.0)

    def test_coverage_negative_interest_cost_returns_999(self):
        self.assertAlmostEqual(self.az._interest_coverage(5000.0, -100.0), 999.0)

    def test_coverage_standard(self):
        # gyi=5000, ic=1500 → 10/3 ≈ 3.333
        self.assertAlmostEqual(
            self.az._interest_coverage(5000.0, 1500.0), 10 / 3, places=5
        )

    def test_coverage_below_one(self):
        # gyi=100, ic=200 → 0.5
        self.assertAlmostEqual(self.az._interest_coverage(100.0, 200.0), 0.5)

    def test_coverage_exactly_one(self):
        self.assertAlmostEqual(self.az._interest_coverage(1000.0, 1000.0), 1.0)


# ─── TestNetYieldPct ─────────────────────────────────────────────────────────

class TestNetYieldPct(unittest.TestCase):
    def setUp(self):
        self.az = DebtRatioAnalyzer()

    def test_net_yield_standard(self):
        # gyi=5000, ic=1500, net=50000 → (3500/50000)*100 = 7.0
        self.assertAlmostEqual(self.az._net_yield_pct(5000.0, 1500.0, 50_000.0), 7.0)

    def test_net_yield_zero_net_returns_zero(self):
        self.assertAlmostEqual(self.az._net_yield_pct(5000.0, 1500.0, 0.0), 0.0)

    def test_net_yield_negative_carry(self):
        # gyi=500, ic=1000 → (-500/50000)*100 = -1.0
        self.assertAlmostEqual(self.az._net_yield_pct(500.0, 1000.0, 50_000.0), -1.0)

    def test_net_yield_no_debt_cost(self):
        # gyi=5000, ic=0, net=100000 → 5.0%
        self.assertAlmostEqual(self.az._net_yield_pct(5000.0, 0.0, 100_000.0), 5.0)


# ─── TestCarrySpreadBps ──────────────────────────────────────────────────────

class TestCarrySpreadBps(unittest.TestCase):
    def setUp(self):
        self.az = DebtRatioAnalyzer()

    def test_carry_standard(self):
        # (5.0 - 3.0) * 100 = 200 bps
        self.assertAlmostEqual(self.az._carry_spread_bps(5.0, 3.0), 200.0)

    def test_carry_negative(self):
        # (3.0 - 5.0) * 100 = -200 bps
        self.assertAlmostEqual(self.az._carry_spread_bps(3.0, 5.0), -200.0)

    def test_carry_zero(self):
        self.assertAlmostEqual(self.az._carry_spread_bps(4.0, 4.0), 0.0)

    def test_carry_large(self):
        # (20.0 - 5.0) * 100 = 1500 bps
        self.assertAlmostEqual(self.az._carry_spread_bps(20.0, 5.0), 1500.0)


# ─── TestRiskLevel ───────────────────────────────────────────────────────────

class TestRiskLevel(unittest.TestCase):
    def setUp(self):
        self.az = DebtRatioAnalyzer()

    def test_risk_conservative_no_leverage(self):
        self.assertEqual(self.az._risk_level(1.0), "CONSERVATIVE")

    def test_risk_conservative_below_one(self):
        self.assertEqual(self.az._risk_level(0.5), "CONSERVATIVE")

    def test_risk_moderate_just_above(self):
        self.assertEqual(self.az._risk_level(1.01), "MODERATE")

    def test_risk_moderate_mid(self):
        self.assertEqual(self.az._risk_level(1.5), "MODERATE")

    def test_risk_moderate_upper(self):
        self.assertEqual(self.az._risk_level(2.0), "MODERATE")

    def test_risk_aggressive_lower(self):
        self.assertEqual(self.az._risk_level(2.01), "AGGRESSIVE")

    def test_risk_aggressive_mid(self):
        self.assertEqual(self.az._risk_level(3.0), "AGGRESSIVE")

    def test_risk_aggressive_upper(self):
        self.assertEqual(self.az._risk_level(3.5), "AGGRESSIVE")

    def test_risk_extreme(self):
        self.assertEqual(self.az._risk_level(3.51), "EXTREME")

    def test_risk_extreme_high(self):
        self.assertEqual(self.az._risk_level(10.0), "EXTREME")

    def test_risk_extreme_999(self):
        self.assertEqual(self.az._risk_level(999.0), "EXTREME")


# ─── TestCashFlowPositive ────────────────────────────────────────────────────

class TestCashFlowPositive(unittest.TestCase):
    def setUp(self):
        self.az = DebtRatioAnalyzer()

    def test_cfp_coverage_above_one(self):
        # gross_yield_income > interest_cost
        gyi = self.az._gross_yield_income(100_000.0, 5.0)   # 5000
        ic = self.az._interest_cost(50_000.0, 3.0)            # 1500
        cov = self.az._interest_coverage(gyi, ic)
        self.assertGreater(cov, 1.0)

    def test_cfp_coverage_below_one(self):
        gyi = self.az._gross_yield_income(100_000.0, 1.0)   # 1000
        ic = self.az._interest_cost(50_000.0, 5.0)            # 2500
        cov = self.az._interest_coverage(gyi, ic)
        self.assertLess(cov, 1.0)


# ─── TestRecommendation ──────────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def setUp(self):
        self.az = DebtRatioAnalyzer()

    def test_conservative_rec(self):
        rec = self.az._recommendation("CONSERVATIVE", 1.0, 200.0, True)
        self.assertIn("No leverage", rec)

    def test_moderate_rec_contains_leverage(self):
        rec = self.az._recommendation("MODERATE", 1.5, 200.0, True)
        self.assertIn("1.5x", rec)
        self.assertIn("200bps", rec)

    def test_aggressive_rec_contains_leverage(self):
        rec = self.az._recommendation("AGGRESSIVE", 3.0, 150.0, True)
        self.assertIn("3.0x", rec)
        self.assertIn("risk elevated", rec)

    def test_extreme_rec(self):
        rec = self.az._recommendation("EXTREME", 5.0, 100.0, True)
        self.assertIn("EXTREME", rec)
        self.assertIn("deleveraging", rec)

    def test_negative_carry_suffix_appended(self):
        rec = self.az._recommendation("AGGRESSIVE", 3.0, -100.0, False)
        self.assertIn("NEGATIVE CARRY", rec)

    def test_positive_carry_no_suffix(self):
        rec = self.az._recommendation("MODERATE", 1.5, 200.0, True)
        self.assertNotIn("NEGATIVE CARRY", rec)

    def test_extreme_negative_carry(self):
        rec = self.az._recommendation("EXTREME", 6.0, -200.0, False)
        self.assertIn("EXTREME", rec)
        self.assertIn("NEGATIVE CARRY", rec)


# ─── TestAnalyzeIntegration ──────────────────────────────────────────────────

class TestAnalyzeIntegration(unittest.TestCase):
    def setUp(self):
        self.az = DebtRatioAnalyzer()

    def _leveraged_staking_pos(self):
        """
        gross=100k, net=50k, debt=50k, interest=3%, yield=5%
        leverage=2.0, d2e=1.0
        gyi=5000, ic=1500, cov=3.333
        net_yield=(5000-1500)/50000*100=7%
        carry=(5-3)*100=200bps
        risk=MODERATE
        """
        return _pos(
            strategy="LEVERAGED_STAKING",
            gross_assets_usd=100_000.0,
            net_assets_usd=50_000.0,
            total_debt_usd=50_000.0,
            interest_rate_pct=3.0,
            gross_yield_pct=5.0,
        )

    def test_analyze_returns_report(self):
        r = self.az.analyze(self._leveraged_staking_pos())
        self.assertIsInstance(r, DebtRatioReport)

    def test_analyze_leverage_ratio(self):
        r = self.az.analyze(self._leveraged_staking_pos())
        self.assertAlmostEqual(r.leverage_ratio, 2.0)

    def test_analyze_debt_to_equity(self):
        r = self.az.analyze(self._leveraged_staking_pos())
        self.assertAlmostEqual(r.debt_to_equity, 1.0)

    def test_analyze_interest_coverage(self):
        r = self.az.analyze(self._leveraged_staking_pos())
        self.assertAlmostEqual(r.interest_coverage, 10 / 3, places=4)

    def test_analyze_net_yield_pct(self):
        r = self.az.analyze(self._leveraged_staking_pos())
        self.assertAlmostEqual(r.net_yield_pct, 7.0)

    def test_analyze_carry_spread_bps(self):
        r = self.az.analyze(self._leveraged_staking_pos())
        self.assertAlmostEqual(r.carry_spread_bps, 200.0)

    def test_analyze_risk_level_moderate(self):
        r = self.az.analyze(self._leveraged_staking_pos())
        self.assertEqual(r.risk_level, "MODERATE")

    def test_analyze_cash_flow_positive(self):
        r = self.az.analyze(self._leveraged_staking_pos())
        self.assertTrue(r.is_cash_flow_positive)

    def test_analyze_recommendation_str(self):
        r = self.az.analyze(self._leveraged_staking_pos())
        self.assertIsInstance(r.recommendation, str)
        self.assertGreater(len(r.recommendation), 0)

    def test_analyze_position_id_preserved(self):
        p = _pos(position_id="abc_xyz")
        r = self.az.analyze(p)
        self.assertEqual(r.position_id, "abc_xyz")


# ─── TestAnalyzePortfolio ────────────────────────────────────────────────────

class TestAnalyzePortfolio(unittest.TestCase):
    def setUp(self):
        self.az = DebtRatioAnalyzer()

    def test_portfolio_empty_raises(self):
        with self.assertRaises(ValueError):
            self.az.analyze_portfolio([])

    def test_portfolio_single_position(self):
        result = self.az.analyze_portfolio([_pos()])
        self.assertIsInstance(result, PortfolioLeverageReport)

    def test_portfolio_total_gross(self):
        positions = [
            _pos("a", gross_assets_usd=100_000.0, net_assets_usd=50_000.0,
                 total_debt_usd=50_000.0),
            _pos("b", gross_assets_usd=200_000.0, net_assets_usd=100_000.0,
                 total_debt_usd=100_000.0),
        ]
        r = self.az.analyze_portfolio(positions)
        self.assertAlmostEqual(r.total_gross_usd, 300_000.0)

    def test_portfolio_total_net(self):
        positions = [
            _pos("a", gross_assets_usd=100_000.0, net_assets_usd=50_000.0,
                 total_debt_usd=50_000.0),
            _pos("b", gross_assets_usd=200_000.0, net_assets_usd=100_000.0,
                 total_debt_usd=100_000.0),
        ]
        r = self.az.analyze_portfolio(positions)
        self.assertAlmostEqual(r.total_net_usd, 150_000.0)

    def test_portfolio_total_debt(self):
        positions = [
            _pos("a", total_debt_usd=50_000.0),
            _pos("b", total_debt_usd=100_000.0),
        ]
        r = self.az.analyze_portfolio(positions)
        self.assertAlmostEqual(r.total_debt_usd, 150_000.0)

    def test_portfolio_leverage_grade_a(self):
        # portfolio_leverage = 300k/200k = 1.5 → A
        positions = [
            _pos("a", gross_assets_usd=300_000.0, net_assets_usd=200_000.0,
                 total_debt_usd=100_000.0),
        ]
        r = self.az.analyze_portfolio(positions)
        self.assertEqual(r.leverage_grade, "A")

    def test_portfolio_leverage_grade_b(self):
        # leverage = 200k/100k = 2.0 → B (>1.5 and <=2.0)
        positions = [
            _pos("a", gross_assets_usd=200_000.0, net_assets_usd=100_000.0,
                 total_debt_usd=100_000.0),
        ]
        r = self.az.analyze_portfolio(positions)
        self.assertEqual(r.leverage_grade, "B")

    def test_portfolio_leverage_grade_c(self):
        # leverage = 300k/100k = 3.0 → C (>2.0 and <=3.0)
        positions = [
            _pos("a", gross_assets_usd=300_000.0, net_assets_usd=100_000.0,
                 total_debt_usd=200_000.0),
        ]
        r = self.az.analyze_portfolio(positions)
        self.assertEqual(r.leverage_grade, "C")

    def test_portfolio_leverage_grade_d(self):
        # leverage = 500k/100k = 5.0 → D (>3.0 and <=5.0)
        positions = [
            _pos("a", gross_assets_usd=500_000.0, net_assets_usd=100_000.0,
                 total_debt_usd=400_000.0),
        ]
        r = self.az.analyze_portfolio(positions)
        self.assertEqual(r.leverage_grade, "D")

    def test_portfolio_leverage_grade_f(self):
        # leverage = 600k/100k = 6.0 → F (>5.0)
        positions = [
            _pos("a", gross_assets_usd=600_000.0, net_assets_usd=100_000.0,
                 total_debt_usd=500_000.0),
        ]
        r = self.az.analyze_portfolio(positions)
        self.assertEqual(r.leverage_grade, "F")

    def test_portfolio_highest_leverage_position(self):
        # position "b" has higher leverage
        positions = [
            _pos("a", gross_assets_usd=200_000.0, net_assets_usd=100_000.0,
                 total_debt_usd=100_000.0),
            _pos("b", gross_assets_usd=500_000.0, net_assets_usd=100_000.0,
                 total_debt_usd=400_000.0),
        ]
        r = self.az.analyze_portfolio(positions)
        self.assertEqual(r.highest_leverage_position, "b")

    def test_portfolio_recommendations_safe_bounds(self):
        # Grade A or B → "safe bounds" recommendation present
        positions = [_pos("a", gross_assets_usd=150_000.0, net_assets_usd=100_000.0,
                          total_debt_usd=50_000.0)]
        r = self.az.analyze_portfolio(positions)
        self.assertTrue(any("safe bounds" in rec for rec in r.recommendations))

    def test_portfolio_recommendations_high_leverage_warning(self):
        # portfolio leverage > 2.5 → systemic risk warning
        positions = [
            _pos("a", gross_assets_usd=300_000.0, net_assets_usd=100_000.0,
                 total_debt_usd=200_000.0),
        ]
        r = self.az.analyze_portfolio(positions)
        self.assertTrue(any("2.5x" in rec for rec in r.recommendations))

    def test_portfolio_recommendations_negative_carry(self):
        # interest > yield → negative carry warning
        positions = [
            _pos("a", interest_rate_pct=8.0, gross_yield_pct=3.0),
        ]
        r = self.az.analyze_portfolio(positions)
        self.assertTrue(any("Negative carry" in rec for rec in r.recommendations))

    def test_portfolio_positions_count(self):
        positions = [_pos(str(i)) for i in range(4)]
        r = self.az.analyze_portfolio(positions)
        self.assertEqual(len(r.positions), 4)

    def test_portfolio_weighted_carry_single(self):
        # single position: weighted carry = carry_spread of that position
        p = _pos("a", gross_assets_usd=100_000.0, gross_yield_pct=5.0,
                 interest_rate_pct=3.0)
        r = self.az.analyze_portfolio([p])
        self.assertAlmostEqual(r.weighted_carry_spread_bps, 200.0)

    def test_portfolio_debt_ratio(self):
        # debt=100k, gross=200k → 0.5
        positions = [_pos("a", gross_assets_usd=200_000.0, net_assets_usd=100_000.0,
                          total_debt_usd=100_000.0)]
        r = self.az.analyze_portfolio(positions)
        self.assertAlmostEqual(r.portfolio_debt_ratio, 0.5)

    def test_portfolio_debt_ratio_high_triggers_rec(self):
        # debt=110k, gross=200k → 0.55 > 0.5
        positions = [_pos("a", gross_assets_usd=200_000.0, net_assets_usd=90_000.0,
                          total_debt_usd=110_000.0)]
        r = self.az.analyze_portfolio(positions)
        self.assertTrue(any("50%" in rec for rec in r.recommendations))


# ─── TestRingBuffer ──────────────────────────────────────────────────────────

class TestRingBuffer(unittest.TestCase):
    def _make_analyzer(self):
        td = tempfile.mkdtemp()
        return DebtRatioAnalyzer(data_file=Path(td) / "test_debt.json")

    def _make_report(self, pid="p1"):
        return DebtRatioReport(
            position_id=pid,
            strategy="YIELD_LOOP",
            leverage_ratio=2.0,
            debt_to_equity=1.0,
            interest_coverage=3.333,
            net_yield_pct=7.0,
            carry_spread_bps=200.0,
            risk_level="MODERATE",
            is_cash_flow_positive=True,
            recommendation="📋 Moderate leverage 2.0x — carry spread 200bps",
        )

    def test_save_creates_file(self):
        az = self._make_analyzer()
        az.save_results([self._make_report()])
        self.assertTrue(az.data_file.exists())

    def test_save_valid_json(self):
        az = self._make_analyzer()
        az.save_results([self._make_report()])
        data = json.loads(az.data_file.read_text())
        self.assertIsInstance(data, list)

    def test_save_single_entry(self):
        az = self._make_analyzer()
        az.save_results([self._make_report("x")])
        data = json.loads(az.data_file.read_text())
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["position_id"], "x")

    def test_save_appends(self):
        az = self._make_analyzer()
        az.save_results([self._make_report("p1")])
        az.save_results([self._make_report("p2")])
        data = json.loads(az.data_file.read_text())
        self.assertEqual(len(data), 2)

    def test_save_ring_buffer_cap(self):
        az = self._make_analyzer()
        for i in range(MAX_ENTRIES + 10):
            az.save_results([self._make_report(str(i))])
        data = json.loads(az.data_file.read_text())
        self.assertLessEqual(len(data), MAX_ENTRIES)

    def test_save_atomic_no_tmp_left(self):
        az = self._make_analyzer()
        az.save_results([self._make_report()])
        tmp = az.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_load_history_missing_file_returns_empty(self):
        az = self._make_analyzer()
        self.assertEqual(az.load_history(), [])

    def test_load_history_after_save(self):
        az = self._make_analyzer()
        az.save_results([self._make_report("p1")])
        history = az.load_history()
        self.assertEqual(len(history), 1)

    def test_load_history_corrupt_file_returns_empty(self):
        az = self._make_analyzer()
        az.data_file.parent.mkdir(parents=True, exist_ok=True)
        az.data_file.write_text("definitely not json {{{")
        self.assertEqual(az.load_history(), [])

    def test_save_contains_timestamp(self):
        az = self._make_analyzer()
        before = time.time()
        az.save_results([self._make_report()])
        after = time.time()
        data = json.loads(az.data_file.read_text())
        self.assertGreaterEqual(data[0]["timestamp"], before)
        self.assertLessEqual(data[0]["timestamp"], after)

    def test_save_risk_level_recorded(self):
        az = self._make_analyzer()
        az.save_results([self._make_report("p1")])
        data = json.loads(az.data_file.read_text())
        self.assertEqual(data[0]["risk_level"], "MODERATE")


if __name__ == "__main__":
    unittest.main()
