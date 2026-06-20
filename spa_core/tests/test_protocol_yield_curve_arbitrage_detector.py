"""
MP-965 Tests: ProtocolYieldCurveArbitrageDetector
Run: python3 -m unittest spa_core.tests.test_protocol_yield_curve_arbitrage_detector -v
"""

import json
import os
import unittest
import tempfile

from spa_core.analytics.protocol_yield_curve_arbitrage_detector import (
    ProtocolYieldCurveArbitrageDetector,
)


def make_opp(**kwargs):
    """Return an opportunity dict with sensible defaults."""
    defaults = {
        "name": "TestArb",
        "long_asset": "sUSDe",
        "long_apy_pct": 12.0,
        "short_asset": "USDT",
        "short_cost_pct": 5.0,
        "strategy_type": "cash_and_carry",
        "collateral_required_usd": 50_000,
        "max_position_usd": 100_000,
        "execution_gas_usd": 50.0,
        "slippage_est_pct": 0.1,
        "holding_period_days": 30,
        "refinancing_risk": False,
        "counterparty_risk_score": 25,
    }
    defaults.update(kwargs)
    return defaults


class TestGrossSpread(unittest.TestCase):
    """Tests for gross_spread_pct = long_apy - short_cost."""

    def setUp(self):
        self.det = ProtocolYieldCurveArbitrageDetector()

    def test_positive_spread(self):
        o = make_opp(long_apy_pct=10.0, short_cost_pct=3.0)
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["gross_spread_pct"], 7.0, places=4)

    def test_zero_spread(self):
        o = make_opp(long_apy_pct=5.0, short_cost_pct=5.0)
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["gross_spread_pct"], 0.0, places=4)

    def test_negative_spread(self):
        o = make_opp(long_apy_pct=2.0, short_cost_pct=8.0)
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["gross_spread_pct"], -6.0, places=4)

    def test_large_spread(self):
        o = make_opp(long_apy_pct=30.0, short_cost_pct=2.0)
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["gross_spread_pct"], 28.0, places=4)

    def test_fractional_spread(self):
        o = make_opp(long_apy_pct=5.75, short_cost_pct=2.25)
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["gross_spread_pct"], 3.5, places=4)


class TestGasDrag(unittest.TestCase):
    """Tests for gas_drag_pct = execution_gas_usd / max_position_usd * 100."""

    def setUp(self):
        self.det = ProtocolYieldCurveArbitrageDetector()

    def test_gas_drag_1pct(self):
        # gas=1000, position=100000 → 1%
        o = make_opp(execution_gas_usd=1000.0, max_position_usd=100_000)
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["gas_drag_pct"], 1.0, places=4)

    def test_gas_drag_zero(self):
        o = make_opp(execution_gas_usd=0.0, max_position_usd=100_000)
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["gas_drag_pct"], 0.0, places=4)

    def test_gas_drag_zero_position(self):
        o = make_opp(execution_gas_usd=100.0, max_position_usd=0)
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["gas_drag_pct"], 0.0, places=4)

    def test_gas_drag_small(self):
        # gas=50, position=100000 → 0.05%
        o = make_opp(execution_gas_usd=50.0, max_position_usd=100_000)
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["gas_drag_pct"], 0.05, places=4)

    def test_gas_drag_large(self):
        # gas=5000, position=10000 → 50%
        o = make_opp(execution_gas_usd=5_000.0, max_position_usd=10_000)
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["gas_drag_pct"], 50.0, places=4)


class TestNetSpread(unittest.TestCase):
    """Tests for net_spread_pct = gross - slippage - gas_drag."""

    def setUp(self):
        self.det = ProtocolYieldCurveArbitrageDetector()

    def test_net_spread_basic(self):
        # gross=7, slippage=0.1, gas_drag=0.05 → 6.85
        o = make_opp(
            long_apy_pct=12.0,
            short_cost_pct=5.0,
            slippage_est_pct=0.1,
            execution_gas_usd=50.0,
            max_position_usd=100_000,
        )
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["net_spread_pct"], 6.85, places=3)

    def test_net_spread_zero_costs(self):
        o = make_opp(
            long_apy_pct=10.0,
            short_cost_pct=4.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
        )
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["net_spread_pct"], 6.0, places=3)

    def test_net_spread_negative(self):
        o = make_opp(
            long_apy_pct=3.0,
            short_cost_pct=5.0,
            slippage_est_pct=0.5,
            execution_gas_usd=100.0,
            max_position_usd=100_000,
        )
        r = self.det.detect([o])
        self.assertLess(r["opportunities"][0]["net_spread_pct"], 0.0)

    def test_net_spread_below_zero_when_high_gas(self):
        o = make_opp(
            long_apy_pct=10.0,
            short_cost_pct=8.0,
            slippage_est_pct=0.5,
            execution_gas_usd=3_000.0,
            max_position_usd=100_000,  # gas_drag=3%
        )
        r = self.det.detect([o])
        # gross=2, costs=0.5+3=3.5, net=-1.5
        self.assertAlmostEqual(r["opportunities"][0]["net_spread_pct"], -1.5, places=3)


class TestAnnualizedReturn(unittest.TestCase):
    """Tests for annualized_return_pct = net_spread * (365 / holding_period_days)."""

    def setUp(self):
        self.det = ProtocolYieldCurveArbitrageDetector()

    def test_annualized_30_days(self):
        # net_spread = 6.85, holding=30 → 6.85 * (365/30) ≈ 83.37
        o = make_opp(
            long_apy_pct=12.0,
            short_cost_pct=5.0,
            slippage_est_pct=0.1,
            execution_gas_usd=50.0,
            max_position_usd=100_000,
            holding_period_days=30,
        )
        r = self.det.detect([o])
        expected = 6.85 * (365.0 / 30)
        self.assertAlmostEqual(
            r["opportunities"][0]["annualized_return_pct"], expected, delta=0.05
        )

    def test_annualized_365_days(self):
        # holding=365 → annualized = net_spread (×1)
        o = make_opp(
            long_apy_pct=10.0,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=365,
        )
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["annualized_return_pct"], 7.0, places=3)

    def test_annualized_negative(self):
        o = make_opp(
            long_apy_pct=2.0,
            short_cost_pct=5.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=30,
        )
        r = self.det.detect([o])
        self.assertLess(r["opportunities"][0]["annualized_return_pct"], 0.0)

    def test_annualized_7_day(self):
        # Short holding period → high annualized return
        o = make_opp(
            long_apy_pct=10.0,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=7,
        )
        r = self.det.detect([o])
        expected = 7.0 * (365.0 / 7)
        self.assertAlmostEqual(r["opportunities"][0]["annualized_return_pct"], expected, places=2)


class TestCapitalEfficiency(unittest.TestCase):
    """Tests for capital_efficiency_ratio = annualized_return * (position / collateral)."""

    def setUp(self):
        self.det = ProtocolYieldCurveArbitrageDetector()

    def test_capital_efficiency_basic(self):
        # net_spread=7, holding=365 → ann=7; position=100k, collateral=50k → eff=7*(100/50)=14
        o = make_opp(
            long_apy_pct=10.0,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=365,
            collateral_required_usd=50_000,
            max_position_usd=100_000,
        )
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["capital_efficiency_ratio"], 14.0, places=2)

    def test_capital_efficiency_zero_collateral(self):
        o = make_opp(collateral_required_usd=0)
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["capital_efficiency_ratio"], 0.0, places=4)

    def test_capital_efficiency_high_leverage(self):
        # position=500k, collateral=10k → 50x leverage
        o = make_opp(
            long_apy_pct=10.0,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=365,
            collateral_required_usd=10_000,
            max_position_usd=500_000,
        )
        r = self.det.detect([o])
        # ann=7, eff=7*(500k/10k)=350
        self.assertAlmostEqual(r["opportunities"][0]["capital_efficiency_ratio"], 350.0, places=2)


class TestRiskAdjustedReturn(unittest.TestCase):
    """Tests for risk_adjusted_return_pct = net_spread * (100 - counterparty_risk) / 100."""

    def setUp(self):
        self.det = ProtocolYieldCurveArbitrageDetector()

    def test_risk_adjusted_zero_risk(self):
        # counterparty_risk=0 → risk_adj = net_spread * 1.0
        o = make_opp(
            long_apy_pct=10.0,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            counterparty_risk_score=0,
        )
        r = self.det.detect([o])
        net = r["opportunities"][0]["net_spread_pct"]
        risk_adj = r["opportunities"][0]["risk_adjusted_return_pct"]
        self.assertAlmostEqual(risk_adj, net, places=4)

    def test_risk_adjusted_100_risk(self):
        # counterparty_risk=100 → risk_adj = net_spread * 0.0 = 0
        o = make_opp(
            long_apy_pct=10.0,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            counterparty_risk_score=100,
        )
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["risk_adjusted_return_pct"], 0.0, places=4)

    def test_risk_adjusted_50_risk(self):
        # net=7, risk=50 → 7 * 0.5 = 3.5
        o = make_opp(
            long_apy_pct=10.0,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=365,
            counterparty_risk_score=50,
        )
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["risk_adjusted_return_pct"], 3.5, places=4)

    def test_risk_adjusted_25_risk(self):
        # net=4, risk=25 → 4 * 0.75 = 3.0
        o = make_opp(
            long_apy_pct=7.0,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=365,
            counterparty_risk_score=25,
        )
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["risk_adjusted_return_pct"], 3.0, places=4)


class TestArbLabels(unittest.TestCase):
    """Tests for arb_label classification."""

    def setUp(self):
        self.det = ProtocolYieldCurveArbitrageDetector()

    def _label(self, **kwargs):
        o = make_opp(**kwargs)
        return self.det.detect([o])["opportunities"][0]["arb_label"]

    def test_exceptional_high_return_low_risk(self):
        # annualized > 5% AND counterparty_risk < 50
        # net=7, holding=365 → ann=7 > 5, risk=25 < 50
        lbl = self._label(
            long_apy_pct=10.0,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=365,
            counterparty_risk_score=25,
        )
        self.assertEqual(lbl, "EXCEPTIONAL")

    def test_not_exceptional_high_risk(self):
        # annualized > 5% but counterparty_risk >= 50
        lbl = self._label(
            long_apy_pct=10.0,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=365,
            counterparty_risk_score=60,
        )
        self.assertEqual(lbl, "ATTRACTIVE")

    def test_attractive_2_to_5_pct(self):
        # ann ≈ 3%, risk=80 (>50 so not EXCEPTIONAL) → ATTRACTIVE
        lbl = self._label(
            long_apy_pct=6.0,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=365,
            counterparty_risk_score=80,
        )
        self.assertEqual(lbl, "ATTRACTIVE")

    def test_marginal_0_to_2_pct(self):
        # net=1, holding=365 → ann=1%, risk=80
        lbl = self._label(
            long_apy_pct=4.0,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=365,
            counterparty_risk_score=80,
        )
        self.assertEqual(lbl, "MARGINAL")

    def test_uneconomical_small_negative(self):
        # net=-0.5, holding=365 → ann=-0.5 → UNECONOMICAL
        lbl = self._label(
            long_apy_pct=2.5,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=365,
            counterparty_risk_score=50,
        )
        self.assertEqual(lbl, "UNECONOMICAL")

    def test_negative_large_negative(self):
        # ann=-5 → NEGATIVE
        lbl = self._label(
            long_apy_pct=2.0,
            short_cost_pct=10.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=365,
            counterparty_risk_score=50,
        )
        self.assertEqual(lbl, "NEGATIVE")

    def test_exceptional_boundary_5pct(self):
        # ann=5.01, risk=49 → EXCEPTIONAL
        lbl = self._label(
            long_apy_pct=8.01,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=365,
            counterparty_risk_score=49,
        )
        self.assertEqual(lbl, "EXCEPTIONAL")

    def test_attractive_exactly_2pct(self):
        # ann=2.01 → ATTRACTIVE (>2)
        lbl = self._label(
            long_apy_pct=5.01,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=365,
            counterparty_risk_score=80,
        )
        self.assertEqual(lbl, "ATTRACTIVE")


class TestFlags(unittest.TestCase):
    """Tests for all arb flags."""

    def setUp(self):
        self.det = ProtocolYieldCurveArbitrageDetector()

    def _flags(self, **kwargs):
        o = make_opp(**kwargs)
        return self.det.detect([o])["opportunities"][0]["flags"]

    # HIGH_CAPITAL_EFFICIENCY tests
    def test_high_capital_efficiency_above_20(self):
        # ann=7*(365/365)=7, position=1M, collateral=10k → 7*100=700 > 20
        flags = self._flags(
            long_apy_pct=10.0,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=365,
            collateral_required_usd=10_000,
            max_position_usd=1_000_000,
        )
        self.assertIn("HIGH_CAPITAL_EFFICIENCY", flags)

    def test_no_high_capital_efficiency_below_20(self):
        # ann=7, position=100k, collateral=100k → 7*1=7 < 20
        flags = self._flags(
            long_apy_pct=10.0,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=365,
            collateral_required_usd=100_000,
            max_position_usd=100_000,
        )
        self.assertNotIn("HIGH_CAPITAL_EFFICIENCY", flags)

    # REFINANCING_RISK tests
    def test_refinancing_risk_true(self):
        flags = self._flags(refinancing_risk=True)
        self.assertIn("REFINANCING_RISK", flags)

    def test_refinancing_risk_false(self):
        flags = self._flags(refinancing_risk=False)
        self.assertNotIn("REFINANCING_RISK", flags)

    # LOW_COUNTERPARTY_RISK tests
    def test_low_counterparty_risk_below_30(self):
        flags = self._flags(counterparty_risk_score=20)
        self.assertIn("LOW_COUNTERPARTY_RISK", flags)

    def test_low_counterparty_risk_at_29(self):
        flags = self._flags(counterparty_risk_score=29)
        self.assertIn("LOW_COUNTERPARTY_RISK", flags)

    def test_no_low_counterparty_risk_at_30(self):
        flags = self._flags(counterparty_risk_score=30)
        self.assertNotIn("LOW_COUNTERPARTY_RISK", flags)

    def test_no_low_counterparty_risk_high_score(self):
        flags = self._flags(counterparty_risk_score=75)
        self.assertNotIn("LOW_COUNTERPARTY_RISK", flags)

    # GAS_HEAVY tests
    def test_gas_heavy_when_gas_over_10pct_gross(self):
        # gross=7%, gas_drag = (700/100000)*100=0.7% → 0.7 > 0.7? exactly 10%
        # Make gas clearly > 10%: gas=800 → 0.8 > 7*0.1=0.7 → YES
        flags = self._flags(
            long_apy_pct=10.0,
            short_cost_pct=3.0,
            execution_gas_usd=800.0,
            max_position_usd=100_000,
            slippage_est_pct=0.0,
        )
        self.assertIn("GAS_HEAVY", flags)

    def test_no_gas_heavy_when_gas_under_10pct_gross(self):
        # gross=7, gas_drag=0.05 (50/100000*100=0.05) → 0.05 < 7*0.1=0.7
        flags = self._flags(
            long_apy_pct=10.0,
            short_cost_pct=3.0,
            execution_gas_usd=50.0,
            max_position_usd=100_000,
            slippage_est_pct=0.0,
        )
        self.assertNotIn("GAS_HEAVY", flags)

    def test_no_gas_heavy_when_gross_zero(self):
        # gross=0 → no GAS_HEAVY (guard for division by zero)
        flags = self._flags(
            long_apy_pct=3.0,
            short_cost_pct=3.0,
            execution_gas_usd=1000.0,
            max_position_usd=100_000,
        )
        self.assertNotIn("GAS_HEAVY", flags)

    # CLOSING_SOON tests
    def test_closing_soon_5_days(self):
        flags = self._flags(holding_period_days=5)
        self.assertIn("CLOSING_SOON", flags)

    def test_closing_soon_1_day(self):
        flags = self._flags(holding_period_days=1)
        self.assertIn("CLOSING_SOON", flags)

    def test_no_closing_soon_30_days(self):
        flags = self._flags(holding_period_days=30)
        self.assertNotIn("CLOSING_SOON", flags)

    def test_no_closing_soon_7_days_exactly(self):
        # < 7 → CLOSING_SOON; at 7 → not
        flags = self._flags(holding_period_days=7)
        self.assertNotIn("CLOSING_SOON", flags)

    def test_closing_soon_6_days(self):
        flags = self._flags(holding_period_days=6)
        self.assertIn("CLOSING_SOON", flags)

    def test_multiple_flags_coexist(self):
        # refinancing_risk=True + low_counterparty_risk + closing_soon
        flags = self._flags(
            refinancing_risk=True,
            counterparty_risk_score=10,
            holding_period_days=3,
        )
        self.assertIn("REFINANCING_RISK", flags)
        self.assertIn("LOW_COUNTERPARTY_RISK", flags)
        self.assertIn("CLOSING_SOON", flags)


class TestAggregates(unittest.TestCase):
    """Tests for aggregate computations."""

    def setUp(self):
        self.det = ProtocolYieldCurveArbitrageDetector()

    def test_best_opportunity(self):
        opps = [
            make_opp(name="A", long_apy_pct=20.0, short_cost_pct=3.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=365),
            make_opp(name="B", long_apy_pct=5.0, short_cost_pct=3.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=365),
        ]
        r = self.det.detect(opps)
        self.assertEqual(r["aggregates"]["best_opportunity"]["name"], "A")

    def test_worst_opportunity(self):
        opps = [
            make_opp(name="A", long_apy_pct=20.0, short_cost_pct=3.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=365),
            make_opp(name="B", long_apy_pct=2.0, short_cost_pct=5.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=365),
        ]
        r = self.det.detect(opps)
        self.assertEqual(r["aggregates"]["worst_opportunity"]["name"], "B")

    def test_total_deployable_exceptional_only(self):
        # A: ann=17>5, risk=25<50 → EXCEPTIONAL; B: ann=-3 → NEGATIVE
        opps = [
            make_opp(name="A", long_apy_pct=20.0, short_cost_pct=3.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=365, counterparty_risk_score=25,
                     max_position_usd=100_000),
            make_opp(name="B", long_apy_pct=2.0, short_cost_pct=5.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=365, max_position_usd=50_000),
        ]
        r = self.det.detect(opps)
        self.assertAlmostEqual(r["aggregates"]["total_deployable_usd"], 100_000, places=0)

    def test_total_deployable_includes_attractive(self):
        # A: EXCEPTIONAL, B: ATTRACTIVE
        opps = [
            make_opp(name="A", long_apy_pct=10.0, short_cost_pct=3.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=365, counterparty_risk_score=25,
                     max_position_usd=100_000),
            make_opp(name="B", long_apy_pct=6.0, short_cost_pct=3.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=365, counterparty_risk_score=80,
                     max_position_usd=200_000),
        ]
        r = self.det.detect(opps)
        self.assertAlmostEqual(r["aggregates"]["total_deployable_usd"], 300_000, places=0)

    def test_average_net_spread(self):
        # A: net=6.0 (long=9,short=3,slippage=0,gas=0), B: net=2.0 (long=5,short=3)
        opps = [
            make_opp(name="A", long_apy_pct=9.0, short_cost_pct=3.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=30),
            make_opp(name="B", long_apy_pct=5.0, short_cost_pct=3.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=30),
        ]
        r = self.det.detect(opps)
        self.assertAlmostEqual(r["aggregates"]["average_net_spread"], 4.0, places=3)

    def test_exceptional_count(self):
        opps = [
            make_opp(name="A", long_apy_pct=10.0, short_cost_pct=3.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=365, counterparty_risk_score=25),
            make_opp(name="B", long_apy_pct=10.0, short_cost_pct=3.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=365, counterparty_risk_score=25),
            make_opp(name="C", long_apy_pct=3.0, short_cost_pct=5.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=365),
        ]
        r = self.det.detect(opps)
        self.assertEqual(r["aggregates"]["exceptional_count"], 2)

    def test_aggregates_empty_list(self):
        r = self.det.detect([])
        agg = r["aggregates"]
        self.assertIsNone(agg["best_opportunity"])
        self.assertIsNone(agg["worst_opportunity"])
        self.assertEqual(agg["total_deployable_usd"], 0.0)
        self.assertIsNone(agg["average_net_spread"])
        self.assertEqual(agg["exceptional_count"], 0)

    def test_aggregates_single_opportunity(self):
        r = self.det.detect([make_opp(name="Solo")])
        agg = r["aggregates"]
        self.assertEqual(agg["best_opportunity"]["name"], "Solo")
        self.assertEqual(agg["worst_opportunity"]["name"], "Solo")


class TestOutputStructure(unittest.TestCase):
    """Tests for output structure and field presence."""

    def setUp(self):
        self.det = ProtocolYieldCurveArbitrageDetector()

    def test_output_has_opportunities_key(self):
        r = self.det.detect([make_opp()])
        self.assertIn("opportunities", r)

    def test_output_has_aggregates_key(self):
        r = self.det.detect([make_opp()])
        self.assertIn("aggregates", r)

    def test_output_has_opportunity_count(self):
        r = self.det.detect([make_opp()])
        self.assertEqual(r["opportunity_count"], 1)

    def test_output_has_timestamp(self):
        r = self.det.detect([make_opp()])
        self.assertIn("timestamp", r)
        self.assertIsInstance(r["timestamp"], str)

    def test_opportunity_has_name(self):
        r = self.det.detect([make_opp(name="MyArb")])
        self.assertEqual(r["opportunities"][0]["name"], "MyArb")

    def test_opportunity_has_gross_spread(self):
        r = self.det.detect([make_opp()])
        self.assertIn("gross_spread_pct", r["opportunities"][0])

    def test_opportunity_has_gas_drag(self):
        r = self.det.detect([make_opp()])
        self.assertIn("gas_drag_pct", r["opportunities"][0])

    def test_opportunity_has_net_spread(self):
        r = self.det.detect([make_opp()])
        self.assertIn("net_spread_pct", r["opportunities"][0])

    def test_opportunity_has_annualized_return(self):
        r = self.det.detect([make_opp()])
        self.assertIn("annualized_return_pct", r["opportunities"][0])

    def test_opportunity_has_capital_efficiency(self):
        r = self.det.detect([make_opp()])
        self.assertIn("capital_efficiency_ratio", r["opportunities"][0])

    def test_opportunity_has_risk_adjusted(self):
        r = self.det.detect([make_opp()])
        self.assertIn("risk_adjusted_return_pct", r["opportunities"][0])

    def test_opportunity_has_arb_label(self):
        r = self.det.detect([make_opp()])
        self.assertIn("arb_label", r["opportunities"][0])

    def test_opportunity_has_flags_list(self):
        r = self.det.detect([make_opp()])
        self.assertIsInstance(r["opportunities"][0]["flags"], list)

    def test_opportunity_preserves_strategy_type(self):
        r = self.det.detect([make_opp(strategy_type="basis_trade")])
        self.assertEqual(r["opportunities"][0]["strategy_type"], "basis_trade")

    def test_opportunity_preserves_refinancing_risk(self):
        r = self.det.detect([make_opp(refinancing_risk=True)])
        self.assertTrue(r["opportunities"][0]["refinancing_risk"])

    def test_opportunity_preserves_counterparty_risk(self):
        r = self.det.detect([make_opp(counterparty_risk_score=42)])
        self.assertAlmostEqual(
            r["opportunities"][0]["counterparty_risk_score"], 42.0, places=2
        )

    def test_empty_list_returns_empty_opportunities(self):
        r = self.det.detect([])
        self.assertEqual(r["opportunities"], [])
        self.assertEqual(r["opportunity_count"], 0)

    def test_multiple_opportunities_count(self):
        opps = [make_opp(name=f"Arb{i}") for i in range(5)]
        r = self.det.detect(opps)
        self.assertEqual(len(r["opportunities"]), 5)


class TestLogWriting(unittest.TestCase):
    """Tests for ring-buffer log writing."""

    def setUp(self):
        self.det = ProtocolYieldCurveArbitrageDetector()

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.det.detect([make_opp()], config={"write_log": True, "data_dir": tmp})
            self.assertTrue(os.path.exists(os.path.join(tmp, "yield_curve_arb_log.json")))

    def test_write_log_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.det.detect([make_opp()], config={"write_log": True, "data_dir": tmp})
            with open(os.path.join(tmp, "yield_curve_arb_log.json")) as f:
                log = json.load(f)
            self.assertEqual(len(log), 1)
            self.assertIn("timestamp", log[0])

    def test_write_log_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"write_log": True, "data_dir": tmp}
            self.det.detect([make_opp()], config=cfg)
            self.det.detect([make_opp()], config=cfg)
            with open(os.path.join(tmp, "yield_curve_arb_log.json")) as f:
                log = json.load(f)
            self.assertEqual(len(log), 2)

    def test_write_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"write_log": True, "data_dir": tmp}
            for _ in range(105):
                self.det.detect([make_opp()], config=cfg)
            with open(os.path.join(tmp, "yield_curve_arb_log.json")) as f:
                log = json.load(f)
            self.assertEqual(len(log), 100)

    def test_no_log_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.det.detect([make_opp()])
            self.assertFalse(os.path.exists(os.path.join(tmp, "yield_curve_arb_log.json")))

    def test_write_log_has_opportunity_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            opps = [make_opp(), make_opp()]
            self.det.detect(opps, config={"write_log": True, "data_dir": tmp})
            with open(os.path.join(tmp, "yield_curve_arb_log.json")) as f:
                log = json.load(f)
            self.assertEqual(log[0]["opportunity_count"], 2)

    def test_write_log_has_exceptional_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            o = make_opp(long_apy_pct=10.0, short_cost_pct=3.0, slippage_est_pct=0.0,
                         execution_gas_usd=0.0, holding_period_days=365, counterparty_risk_score=25)
            self.det.detect([o], config={"write_log": True, "data_dir": tmp})
            with open(os.path.join(tmp, "yield_curve_arb_log.json")) as f:
                log = json.load(f)
            self.assertEqual(log[0]["exceptional_count"], 1)

    def test_write_log_invalid_existing_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "yield_curve_arb_log.json")
            with open(log_path, "w") as f:
                f.write("NOT JSON")
            self.det.detect([make_opp()], config={"write_log": True, "data_dir": tmp})
            with open(log_path) as f:
                log = json.load(f)
            self.assertEqual(len(log), 1)


class TestEdgeCases(unittest.TestCase):
    """Edge cases and misc tests."""

    def setUp(self):
        self.det = ProtocolYieldCurveArbitrageDetector()

    def test_default_config_none(self):
        r = self.det.detect([make_opp()], config=None)
        self.assertIsInstance(r, dict)

    def test_string_numbers_coerced(self):
        o = make_opp(long_apy_pct="10.0", short_cost_pct="3.0")
        r = self.det.detect([o])
        self.assertAlmostEqual(r["opportunities"][0]["gross_spread_pct"], 7.0, places=4)

    def test_missing_optional_fields_use_defaults(self):
        o = {"name": "MinimalArb", "long_apy_pct": 10.0, "short_cost_pct": 3.0}
        r = self.det.detect([o])
        self.assertIn("gross_spread_pct", r["opportunities"][0])

    def test_detect_returns_dict(self):
        r = self.det.detect([make_opp()])
        self.assertIsInstance(r, dict)

    def test_all_arb_label_values_valid(self):
        valid_labels = {"EXCEPTIONAL", "ATTRACTIVE", "MARGINAL", "UNECONOMICAL", "NEGATIVE"}
        opps = [
            make_opp(long_apy_pct=20.0, short_cost_pct=3.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=365, counterparty_risk_score=25),
            make_opp(long_apy_pct=6.0, short_cost_pct=3.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=365, counterparty_risk_score=80),
            make_opp(long_apy_pct=4.0, short_cost_pct=3.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=365),
            make_opp(long_apy_pct=2.5, short_cost_pct=3.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=365),
            make_opp(long_apy_pct=1.0, short_cost_pct=5.0, slippage_est_pct=0.0,
                     execution_gas_usd=0.0, holding_period_days=365),
        ]
        r = self.det.detect(opps)
        for opp in r["opportunities"]:
            self.assertIn(opp["arb_label"], valid_labels)

    def test_gross_spread_greater_than_net_spread_when_costs(self):
        o = make_opp(
            slippage_est_pct=0.5,
            execution_gas_usd=100.0,
            max_position_usd=100_000,
        )
        r = self.det.detect([o])
        self.assertGreater(
            r["opportunities"][0]["gross_spread_pct"],
            r["opportunities"][0]["net_spread_pct"],
        )

    def test_holding_period_1_day(self):
        # Holding period = 1 day → annualized ≈ 365 × net_spread
        o = make_opp(
            long_apy_pct=10.0,
            short_cost_pct=3.0,
            slippage_est_pct=0.0,
            execution_gas_usd=0.0,
            holding_period_days=1,
        )
        r = self.det.detect([o])
        expected = 7.0 * 365
        self.assertAlmostEqual(r["opportunities"][0]["annualized_return_pct"], expected, places=2)


if __name__ == "__main__":
    unittest.main()
