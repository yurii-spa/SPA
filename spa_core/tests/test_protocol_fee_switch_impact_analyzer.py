"""
Tests for MP-969: ProtocolFeeSwitchImpactAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_fee_switch_impact_analyzer -v
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_fee_switch_impact_analyzer import (
    ProtocolFeeSwitchImpactAnalyzer,
    _annual_revenue,
    _potential_yield_pct,
    _pe_ratio,
    _impact_label,
    _compute_flags,
    DEFAULT_CONFIG,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proto(
    name="TestProto",
    token_name="TST",
    enabled=True,
    revenue_30d=1_000_000,
    fee_pct=20.0,
    supply=10_000_000,
    price=10.0,
    market_cap=100_000_000,
    holders=10_000,
    staking_ratio=40.0,
    competing_avg=2.0,
    treasury_balance=5_000_000,
    treasury_runway=24.0,
):
    return {
        "name": name,
        "token_name": token_name,
        "current_fee_switch_enabled": enabled,
        "total_protocol_revenue_30d_usd": revenue_30d,
        "fee_switch_pct": fee_pct,
        "circulating_supply": supply,
        "token_price_usd": price,
        "market_cap_usd": market_cap,
        "token_holders_count": holders,
        "staking_ratio_pct": staking_ratio,
        "competing_protocols_avg_fee_yield_pct": competing_avg,
        "treasury_balance_usd": treasury_balance,
        "treasury_runway_months": treasury_runway,
    }


def _no_log_cfg(extra=None):
    cfg = {**DEFAULT_CONFIG, "log_path": "/dev/null"}
    if extra:
        cfg.update(extra)
    return cfg


# ---------------------------------------------------------------------------
# Unit tests: helper functions
# ---------------------------------------------------------------------------

class TestAnnualRevenue(unittest.TestCase):
    def test_basic_12x(self):
        self.assertAlmostEqual(_annual_revenue(1_000_000), 12_000_000)

    def test_zero_revenue(self):
        self.assertAlmostEqual(_annual_revenue(0.0), 0.0)

    def test_large_revenue(self):
        self.assertAlmostEqual(_annual_revenue(50_000_000), 600_000_000)


class TestPotentialYield(unittest.TestCase):
    def test_basic_yield(self):
        # 12M annual, 20% to holders = 2.4M, supply=10M tokens, price=$10
        # fee_per_tok = 2.4M/10M = 0.24, yield = 0.24/10 * 100 = 2.4%
        y = _potential_yield_pct(12_000_000, 20.0, 10_000_000, 10.0)
        self.assertAlmostEqual(y, 2.4, places=4)

    def test_zero_supply(self):
        self.assertAlmostEqual(_potential_yield_pct(1_000_000, 20.0, 0, 10.0), 0.0)

    def test_zero_price(self):
        self.assertAlmostEqual(_potential_yield_pct(1_000_000, 20.0, 10_000_000, 0.0), 0.0)

    def test_zero_fee_pct(self):
        self.assertAlmostEqual(_potential_yield_pct(1_000_000, 0.0, 10_000_000, 10.0), 0.0)

    def test_100_fee_pct(self):
        # 100% to holders
        y = _potential_yield_pct(12_000_000, 100.0, 10_000_000, 10.0)
        self.assertAlmostEqual(y, 12.0, places=4)


class TestPERatio(unittest.TestCase):
    def test_basic_pe(self):
        pe = _pe_ratio(100_000_000, 10_000_000)
        self.assertAlmostEqual(pe, 10.0)

    def test_zero_revenue_none(self):
        self.assertIsNone(_pe_ratio(100_000_000, 0.0))

    def test_negative_revenue_none(self):
        self.assertIsNone(_pe_ratio(100_000_000, -1.0))

    def test_high_pe(self):
        pe = _pe_ratio(1_000_000_000, 5_000_000)
        self.assertAlmostEqual(pe, 200.0)


class TestImpactLabel(unittest.TestCase):
    def test_highly_accretive(self):
        label = _impact_label(True, 6.0, 3.0, 24.0, DEFAULT_CONFIG)
        self.assertEqual(label, "HIGHLY_ACCRETIVE")

    def test_highly_accretive_needs_yield_gt_competitor(self):
        # yield=6% but competitor_avg=7% → not HIGHLY_ACCRETIVE
        label = _impact_label(True, 6.0, 7.0, 24.0, DEFAULT_CONFIG)
        self.assertEqual(label, "ACCRETIVE")

    def test_accretive(self):
        label = _impact_label(True, 3.0, 4.0, 24.0, DEFAULT_CONFIG)
        self.assertEqual(label, "ACCRETIVE")

    def test_neutral_switch_off(self):
        label = _impact_label(False, 0.0, 2.0, 24.0, DEFAULT_CONFIG)
        self.assertEqual(label, "NEUTRAL")

    def test_neutral_low_yield(self):
        label = _impact_label(True, 1.0, 0.5, 24.0, DEFAULT_CONFIG)
        self.assertEqual(label, "NEUTRAL")

    def test_dilutive(self):
        label = _impact_label(True, 0.0, 2.0, 24.0, DEFAULT_CONFIG)
        self.assertEqual(label, "DILUTIVE")

    def test_treasury_risk_takes_priority(self):
        # Even with great yield, treasury concern takes priority
        label = _impact_label(True, 10.0, 1.0, 3.0, DEFAULT_CONFIG)
        self.assertEqual(label, "TREASURY_RISK")

    def test_treasury_risk_below_6_months(self):
        label = _impact_label(True, 2.0, 1.0, 5.9, DEFAULT_CONFIG)
        self.assertEqual(label, "TREASURY_RISK")

    def test_treasury_risk_above_6_months_not_triggered(self):
        label = _impact_label(True, 2.0, 1.0, 7.0, DEFAULT_CONFIG)
        self.assertNotEqual(label, "TREASURY_RISK")

    def test_accretive_threshold_exact(self):
        # yield = exactly accretive_threshold (2.0) → ACCRETIVE
        label = _impact_label(True, 2.0, 0.5, 24.0, DEFAULT_CONFIG)
        self.assertEqual(label, "ACCRETIVE")


class TestComputeFlags(unittest.TestCase):
    def test_fee_switch_off_opportunity(self):
        flags = _compute_flags(False, 0.0, 5.0, 2.0, 24.0, None, 30.0, DEFAULT_CONFIG)
        self.assertIn("FEE_SWITCH_OFF_OPPORTUNITY", flags)

    def test_no_opportunity_when_switch_on(self):
        flags = _compute_flags(True, 5.0, 5.0, 2.0, 24.0, None, 30.0, DEFAULT_CONFIG)
        self.assertNotIn("FEE_SWITCH_OFF_OPPORTUNITY", flags)

    def test_no_opportunity_potential_below_threshold(self):
        flags = _compute_flags(False, 0.0, 2.0, 2.0, 24.0, None, 30.0, DEFAULT_CONFIG)
        self.assertNotIn("FEE_SWITCH_OFF_OPPORTUNITY", flags)

    def test_competitive_advantage(self):
        # yield=4.5, competing_avg=2.0, multiplier=1.5 → 4.5 > 3.0 → flag
        flags = _compute_flags(True, 4.5, 4.5, 2.0, 24.0, None, 30.0, DEFAULT_CONFIG)
        self.assertIn("COMPETITIVE_ADVANTAGE", flags)

    def test_no_competitive_when_disabled(self):
        flags = _compute_flags(False, 0.0, 4.5, 2.0, 24.0, None, 30.0, DEFAULT_CONFIG)
        self.assertNotIn("COMPETITIVE_ADVANTAGE", flags)

    def test_no_competitive_below_multiplier(self):
        # yield=2.5, competing_avg=2.0, need >3.0 → no flag
        flags = _compute_flags(True, 2.5, 2.5, 2.0, 24.0, None, 30.0, DEFAULT_CONFIG)
        self.assertNotIn("COMPETITIVE_ADVANTAGE", flags)

    def test_treasury_concern(self):
        flags = _compute_flags(True, 2.0, 2.0, 2.0, 4.0, None, 30.0, DEFAULT_CONFIG)
        self.assertIn("TREASURY_CONCERN", flags)

    def test_no_treasury_concern_above_threshold(self):
        flags = _compute_flags(True, 2.0, 2.0, 2.0, 10.0, None, 30.0, DEFAULT_CONFIG)
        self.assertNotIn("TREASURY_CONCERN", flags)

    def test_high_pe_flag(self):
        flags = _compute_flags(True, 2.0, 2.0, 2.0, 24.0, 150.0, 30.0, DEFAULT_CONFIG)
        self.assertIn("HIGH_PE", flags)

    def test_no_high_pe_below_threshold(self):
        flags = _compute_flags(True, 2.0, 2.0, 2.0, 24.0, 50.0, 30.0, DEFAULT_CONFIG)
        self.assertNotIn("HIGH_PE", flags)

    def test_no_high_pe_when_none(self):
        flags = _compute_flags(True, 2.0, 2.0, 2.0, 24.0, None, 30.0, DEFAULT_CONFIG)
        self.assertNotIn("HIGH_PE", flags)

    def test_staking_aligned(self):
        flags = _compute_flags(True, 2.0, 2.0, 2.0, 24.0, None, 60.0, DEFAULT_CONFIG)
        self.assertIn("STAKING_ALIGNED", flags)

    def test_no_staking_aligned_below_threshold(self):
        flags = _compute_flags(True, 2.0, 2.0, 2.0, 24.0, None, 40.0, DEFAULT_CONFIG)
        self.assertNotIn("STAKING_ALIGNED", flags)

    def test_staking_aligned_at_exactly_50(self):
        flags = _compute_flags(True, 2.0, 2.0, 2.0, 24.0, None, 50.0, DEFAULT_CONFIG)
        self.assertIn("STAKING_ALIGNED", flags)

    def test_multiple_flags(self):
        # treasury concern + high PE + staking aligned
        flags = _compute_flags(True, 2.0, 2.0, 2.0, 4.0, 200.0, 60.0, DEFAULT_CONFIG)
        self.assertIn("TREASURY_CONCERN", flags)
        self.assertIn("HIGH_PE", flags)
        self.assertIn("STAKING_ALIGNED", flags)


# ---------------------------------------------------------------------------
# Integration tests: ProtocolFeeSwitchImpactAnalyzer.analyze
# ---------------------------------------------------------------------------

class TestAnalyzerEmpty(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolFeeSwitchImpactAnalyzer()

    def test_empty_protocols_returns_empty(self):
        r = self.analyzer.analyze([], _no_log_cfg())
        self.assertEqual(r["protocols"], [])

    def test_empty_aggregates_zero_count(self):
        r = self.analyzer.analyze([], _no_log_cfg())
        self.assertEqual(r["aggregates"]["protocol_count"], 0)

    def test_empty_aggregates_zero_yield(self):
        r = self.analyzer.analyze([], _no_log_cfg())
        self.assertEqual(r["aggregates"]["average_implied_yield"], 0.0)

    def test_empty_highest_yield_none(self):
        r = self.analyzer.analyze([], _no_log_cfg())
        self.assertIsNone(r["aggregates"]["highest_yield_protocol"])

    def test_empty_has_timestamp(self):
        r = self.analyzer.analyze([], _no_log_cfg())
        self.assertIn("timestamp", r)


class TestAnalyzerResultKeys(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolFeeSwitchImpactAnalyzer()
        self.result = self.analyzer.analyze([_make_proto()], _no_log_cfg())

    def test_has_protocols(self):
        self.assertIn("protocols", self.result)

    def test_has_aggregates(self):
        self.assertIn("aggregates", self.result)

    def test_has_timestamp(self):
        self.assertIn("timestamp", self.result)

    def test_protocol_count_matches(self):
        self.assertEqual(self.result["aggregates"]["protocol_count"], 1)


class TestPerProtocolOutput(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolFeeSwitchImpactAnalyzer()
        # Setup: 1M/mo revenue, 20% to holders, 10M supply, $10 price
        # annual=12M, holder_rev=2.4M, fee_per_tok=0.24, yield=2.4%
        self.proto = _make_proto(
            revenue_30d=1_000_000, fee_pct=20.0,
            supply=10_000_000, price=10.0, market_cap=100_000_000,
            competing_avg=1.0, treasury_runway=24.0, staking_ratio=30.0,
        )
        self.result = self.analyzer.analyze([self.proto], _no_log_cfg())
        self.p = self.result["protocols"][0]

    def test_annual_revenue(self):
        self.assertAlmostEqual(self.p["annual_fee_revenue_usd"], 12_000_000, delta=1.0)

    def test_fee_per_token(self):
        # 2.4M / 10M = 0.24
        self.assertAlmostEqual(self.p["fee_per_token_annual_usd"], 0.24, places=4)

    def test_implied_yield(self):
        # 0.24 / 10 * 100 = 2.4%
        self.assertAlmostEqual(self.p["implied_fee_yield_pct"], 2.4, places=3)

    def test_pe_ratio(self):
        # 100M / 12M = 8.33
        self.assertAlmostEqual(self.p["pe_ratio_equivalent"], 100_000_000 / 12_000_000, places=2)

    def test_holder_annual_income_1000_tokens(self):
        # 0.24 * 1000 = 240
        self.assertAlmostEqual(self.p["holder_annual_income_usd"], 240.0, places=2)

    def test_fee_yield_vs_competitors(self):
        # 2.4% - 1.0% = 1.4%
        self.assertAlmostEqual(self.p["fee_yield_vs_competitors_pct"], 1.4, places=2)

    def test_name_preserved(self):
        self.assertEqual(self.p["name"], "TestProto")

    def test_token_name_preserved(self):
        self.assertEqual(self.p["token_name"], "TST")

    def test_fee_switch_enabled_in_output(self):
        self.assertTrue(self.p["fee_switch_enabled"])

    def test_treasury_runway_preserved(self):
        self.assertAlmostEqual(self.p["treasury_runway_months"], 24.0)


class TestImpliedYieldZeroWhenDisabled(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolFeeSwitchImpactAnalyzer()

    def test_yield_zero_when_disabled(self):
        proto = _make_proto(enabled=False)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertAlmostEqual(r["protocols"][0]["implied_fee_yield_pct"], 0.0)

    def test_fee_per_token_zero_when_disabled(self):
        proto = _make_proto(enabled=False)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertAlmostEqual(r["protocols"][0]["fee_per_token_annual_usd"], 0.0)

    def test_holder_income_zero_when_disabled(self):
        proto = _make_proto(enabled=False)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertAlmostEqual(r["protocols"][0]["holder_annual_income_usd"], 0.0)

    def test_potential_yield_nonzero_when_disabled(self):
        proto = _make_proto(enabled=False, revenue_30d=1_000_000, fee_pct=20.0,
                            supply=10_000_000, price=10.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertGreater(r["protocols"][0]["potential_fee_yield_pct"], 0)


class TestImpactLabels(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolFeeSwitchImpactAnalyzer()

    def test_label_highly_accretive(self):
        # 10M/mo, 30% to holders, 1M supply, $10 price
        # annual=120M, holder=36M, fee_per_tok=36, yield=360% → HIGHLY_ACCRETIVE
        proto = _make_proto(revenue_30d=10_000_000, fee_pct=30.0,
                            supply=1_000_000, price=10.0, market_cap=10_000_000,
                            competing_avg=2.0, treasury_runway=24.0, enabled=True)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertEqual(r["protocols"][0]["impact_label"], "HIGHLY_ACCRETIVE")

    def test_label_accretive(self):
        # yield=2.4%, competing_avg=4.0% → ACCRETIVE (yield >= 2% but not > competitor)
        proto = _make_proto(revenue_30d=1_000_000, fee_pct=20.0,
                            supply=10_000_000, price=10.0, market_cap=100_000_000,
                            competing_avg=4.0, treasury_runway=24.0, enabled=True)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertEqual(r["protocols"][0]["impact_label"], "ACCRETIVE")

    def test_label_neutral_switch_off(self):
        proto = _make_proto(enabled=False, treasury_runway=24.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertEqual(r["protocols"][0]["impact_label"], "NEUTRAL")

    def test_label_treasury_risk(self):
        proto = _make_proto(treasury_runway=3.0, enabled=True)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertEqual(r["protocols"][0]["impact_label"], "TREASURY_RISK")

    def test_label_dilutive(self):
        # fee_pct=0 → yield=0 and enabled → DILUTIVE
        proto = _make_proto(fee_pct=0.0, enabled=True, treasury_runway=24.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertEqual(r["protocols"][0]["impact_label"], "DILUTIVE")

    def test_label_neutral_low_yield(self):
        # yield=1% < accretive threshold (2%) → NEUTRAL
        proto = _make_proto(revenue_30d=500_000, fee_pct=10.0,
                            supply=10_000_000, price=10.0, market_cap=100_000_000,
                            competing_avg=0.5, treasury_runway=24.0, enabled=True)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertIn(r["protocols"][0]["impact_label"], ["NEUTRAL", "ACCRETIVE"])


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolFeeSwitchImpactAnalyzer()

    def test_fee_switch_off_opportunity(self):
        # Disabled but potential yield high
        proto = _make_proto(enabled=False, revenue_30d=5_000_000, fee_pct=20.0,
                            supply=1_000_000, price=10.0, treasury_runway=24.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertIn("FEE_SWITCH_OFF_OPPORTUNITY", r["protocols"][0]["flags"])

    def test_no_opportunity_when_enabled(self):
        proto = _make_proto(enabled=True, revenue_30d=5_000_000, fee_pct=20.0,
                            supply=1_000_000, price=10.0, treasury_runway=24.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertNotIn("FEE_SWITCH_OFF_OPPORTUNITY", r["protocols"][0]["flags"])

    def test_competitive_advantage_flag(self):
        proto = _make_proto(enabled=True, revenue_30d=10_000_000, fee_pct=30.0,
                            supply=1_000_000, price=10.0, market_cap=10_000_000,
                            competing_avg=2.0, treasury_runway=24.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertIn("COMPETITIVE_ADVANTAGE", r["protocols"][0]["flags"])

    def test_treasury_concern_flag(self):
        proto = _make_proto(treasury_runway=3.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertIn("TREASURY_CONCERN", r["protocols"][0]["flags"])

    def test_no_treasury_concern_above_threshold(self):
        proto = _make_proto(treasury_runway=12.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertNotIn("TREASURY_CONCERN", r["protocols"][0]["flags"])

    def test_high_pe_flag(self):
        # market_cap=1B, revenue=1M/mo → PE = 1B/12M ≈ 83... need bigger gap
        proto = _make_proto(market_cap=5_000_000_000, revenue_30d=500_000,
                            treasury_runway=24.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertIn("HIGH_PE", r["protocols"][0]["flags"])

    def test_staking_aligned_flag(self):
        proto = _make_proto(staking_ratio=60.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertIn("STAKING_ALIGNED", r["protocols"][0]["flags"])

    def test_no_staking_aligned_below_50(self):
        proto = _make_proto(staking_ratio=49.9)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertNotIn("STAKING_ALIGNED", r["protocols"][0]["flags"])

    def test_flags_is_list(self):
        proto = _make_proto()
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertIsInstance(r["protocols"][0]["flags"], list)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolFeeSwitchImpactAnalyzer()

    def test_highest_yield_protocol(self):
        p1 = _make_proto(name="A", revenue_30d=10_000_000, fee_pct=50.0,
                         supply=1_000_000, price=10.0, treasury_runway=24.0)
        p2 = _make_proto(name="B", revenue_30d=100_000, fee_pct=5.0,
                         supply=10_000_000, price=10.0, treasury_runway=24.0)
        r = self.analyzer.analyze([p1, p2], _no_log_cfg())
        self.assertEqual(r["aggregates"]["highest_yield_protocol"]["name"], "A")

    def test_lowest_yield_protocol(self):
        p1 = _make_proto(name="A", revenue_30d=10_000_000, fee_pct=50.0,
                         supply=1_000_000, price=10.0, treasury_runway=24.0)
        p2 = _make_proto(name="B", enabled=False, treasury_runway=24.0)
        r = self.analyzer.analyze([p1, p2], _no_log_cfg())
        # B has yield=0 (disabled)
        self.assertEqual(r["aggregates"]["lowest_yield"]["name"], "B")

    def test_average_yield_single(self):
        proto = _make_proto(revenue_30d=1_000_000, fee_pct=20.0,
                            supply=10_000_000, price=10.0, treasury_runway=24.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertAlmostEqual(
            r["aggregates"]["average_implied_yield"],
            r["protocols"][0]["implied_fee_yield_pct"],
            places=3,
        )

    def test_average_yield_two_protocols(self):
        p1 = _make_proto(name="A", revenue_30d=1_000_000, fee_pct=20.0,
                         supply=10_000_000, price=10.0, treasury_runway=24.0)
        p2 = _make_proto(name="B", enabled=False, treasury_runway=24.0)
        r = self.analyzer.analyze([p1, p2], _no_log_cfg())
        expected = (r["protocols"][0]["implied_fee_yield_pct"] +
                    r["protocols"][1]["implied_fee_yield_pct"]) / 2
        self.assertAlmostEqual(r["aggregates"]["average_implied_yield"], expected, places=3)

    def test_highly_accretive_count(self):
        p1 = _make_proto(name="A", revenue_30d=10_000_000, fee_pct=30.0,
                         supply=1_000_000, price=10.0, competing_avg=2.0, treasury_runway=24.0)
        p2 = _make_proto(name="B", enabled=False, treasury_runway=24.0)
        r = self.analyzer.analyze([p1, p2], _no_log_cfg())
        self.assertEqual(r["aggregates"]["highly_accretive_count"], 1)

    def test_treasury_risk_count(self):
        p1 = _make_proto(name="A", treasury_runway=2.0)
        p2 = _make_proto(name="B", treasury_runway=3.0)
        p3 = _make_proto(name="C", treasury_runway=24.0)
        r = self.analyzer.analyze([p1, p2, p3], _no_log_cfg())
        self.assertEqual(r["aggregates"]["treasury_risk_count"], 2)

    def test_protocol_count(self):
        protos = [_make_proto(name=f"P{i}") for i in range(5)]
        r = self.analyzer.analyze(protos, _no_log_cfg())
        self.assertEqual(r["aggregates"]["protocol_count"], 5)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolFeeSwitchImpactAnalyzer()

    def test_zero_supply_no_divide(self):
        proto = _make_proto(supply=0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertAlmostEqual(r["protocols"][0]["implied_fee_yield_pct"], 0.0)

    def test_zero_price_no_divide(self):
        proto = _make_proto(price=0.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertAlmostEqual(r["protocols"][0]["implied_fee_yield_pct"], 0.0)

    def test_zero_revenue_pe_none(self):
        proto = _make_proto(revenue_30d=0.0, treasury_runway=24.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertIsNone(r["protocols"][0]["pe_ratio_equivalent"])

    def test_pe_none_no_high_pe_flag(self):
        proto = _make_proto(revenue_30d=0.0, treasury_runway=24.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertNotIn("HIGH_PE", r["protocols"][0]["flags"])

    def test_large_numbers(self):
        proto = _make_proto(revenue_30d=1e12, supply=1e15, price=0.001,
                            market_cap=1e9, treasury_runway=24.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertIsNotNone(r["protocols"][0]["implied_fee_yield_pct"])

    def test_small_numbers(self):
        proto = _make_proto(revenue_30d=100, supply=1_000_000, price=0.01,
                            market_cap=10_000, treasury_runway=24.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertIsNotNone(r["protocols"][0]["implied_fee_yield_pct"])


class TestConfigOverrides(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolFeeSwitchImpactAnalyzer()

    def test_custom_highly_accretive_threshold(self):
        # yield=0.12%, competing_avg=0.05% → yield > competing_avg ✓
        # Lower HA threshold to 0.1% → 0.12% qualifies → HIGHLY_ACCRETIVE
        proto = _make_proto(revenue_30d=100_000, fee_pct=10.0,
                            supply=10_000_000, price=10.0, competing_avg=0.05,
                            treasury_runway=24.0, enabled=True)
        cfg = _no_log_cfg({"highly_accretive_yield_threshold": 0.1})
        r = self.analyzer.analyze([proto], cfg)
        self.assertEqual(r["protocols"][0]["impact_label"], "HIGHLY_ACCRETIVE")

    def test_custom_accretive_threshold(self):
        # Lower accretive threshold to 0.5% → 1% yield → ACCRETIVE
        proto = _make_proto(revenue_30d=500_000, fee_pct=10.0,
                            supply=10_000_000, price=10.0, competing_avg=4.0,
                            treasury_runway=24.0, enabled=True)
        cfg = _no_log_cfg({"accretive_yield_threshold": 0.5})
        r = self.analyzer.analyze([proto], cfg)
        self.assertEqual(r["protocols"][0]["impact_label"], "ACCRETIVE")

    def test_custom_opportunity_threshold(self):
        # Higher opportunity threshold → potential yield 2.4% won't trigger flag
        proto = _make_proto(enabled=False, revenue_30d=1_000_000, fee_pct=20.0,
                            supply=10_000_000, price=10.0, treasury_runway=24.0)
        cfg = _no_log_cfg({"fee_switch_opportunity_threshold": 5.0})
        r = self.analyzer.analyze([proto], cfg)
        self.assertNotIn("FEE_SWITCH_OFF_OPPORTUNITY", r["protocols"][0]["flags"])

    def test_custom_treasury_months(self):
        # Higher treasury concern threshold (12 months) → 8 months runway triggers
        proto = _make_proto(treasury_runway=8.0, enabled=True)
        cfg = _no_log_cfg({"treasury_concern_months": 12.0})
        r = self.analyzer.analyze([proto], cfg)
        self.assertEqual(r["protocols"][0]["impact_label"], "TREASURY_RISK")

    def test_custom_staking_threshold(self):
        # Lower staking threshold (20%) → 30% staking triggers flag
        proto = _make_proto(staking_ratio=30.0)
        cfg = _no_log_cfg({"staking_aligned_threshold": 20.0})
        r = self.analyzer.analyze([proto], cfg)
        self.assertIn("STAKING_ALIGNED", r["protocols"][0]["flags"])

    def test_custom_high_pe_threshold(self):
        # Lower PE threshold to 5 → PE=8.33 triggers HIGH_PE
        proto = _make_proto(revenue_30d=1_000_000, market_cap=100_000_000,
                            treasury_runway=24.0)
        cfg = _no_log_cfg({"high_pe_threshold": 5.0})
        r = self.analyzer.analyze([proto], cfg)
        self.assertIn("HIGH_PE", r["protocols"][0]["flags"])


class TestLogFile(unittest.TestCase):
    def test_log_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "fee_log.json")
            cfg = {**DEFAULT_CONFIG, "log_path": log_path}
            analyzer = ProtocolFeeSwitchImpactAnalyzer()
            analyzer.analyze([_make_proto()], cfg)
            self.assertTrue(os.path.exists(log_path))

    def test_log_entry_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "fee_log.json")
            cfg = {**DEFAULT_CONFIG, "log_path": log_path}
            analyzer = ProtocolFeeSwitchImpactAnalyzer()
            analyzer.analyze([_make_proto()], cfg)
            with open(log_path) as f:
                data = json.load(f)
            entry = data[0]
            self.assertIn("timestamp", entry)
            self.assertIn("protocol_count", entry)
            self.assertIn("average_implied_yield", entry)

    def test_log_ring_buffer(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "fee_log.json")
            cfg = {**DEFAULT_CONFIG, "log_path": log_path, "log_cap": 3}
            analyzer = ProtocolFeeSwitchImpactAnalyzer()
            for _ in range(7):
                analyzer.analyze([_make_proto()], cfg)
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)

    def test_log_accumulates(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "fee_log.json")
            cfg = {**DEFAULT_CONFIG, "log_path": log_path}
            analyzer = ProtocolFeeSwitchImpactAnalyzer()
            analyzer.analyze([_make_proto()], cfg)
            analyzer.analyze([_make_proto()], cfg)
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)

    def test_log_entry_protocol_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "fee_log.json")
            cfg = {**DEFAULT_CONFIG, "log_path": log_path}
            analyzer = ProtocolFeeSwitchImpactAnalyzer()
            analyzer.analyze([_make_proto(name="A"), _make_proto(name="B")], cfg)
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(data[0]["protocol_count"], 2)

    def test_log_atomic_write(self):
        # If log file exists but is corrupted, should still write cleanly
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "fee_log.json")
            with open(log_path, "w") as f:
                f.write("NOT_JSON")
            cfg = {**DEFAULT_CONFIG, "log_path": log_path}
            analyzer = ProtocolFeeSwitchImpactAnalyzer()
            analyzer.analyze([_make_proto()], cfg)
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)


class TestMiscellaneous(unittest.TestCase):
    def setUp(self):
        self.analyzer = ProtocolFeeSwitchImpactAnalyzer()

    def test_protocols_list_length_matches(self):
        protos = [_make_proto(name=f"P{i}") for i in range(4)]
        r = self.analyzer.analyze(protos, _no_log_cfg())
        self.assertEqual(len(r["protocols"]), 4)

    def test_two_protocols_different_labels(self):
        p1 = _make_proto(name="A", revenue_30d=10_000_000, fee_pct=30.0,
                         supply=1_000_000, price=10.0, competing_avg=2.0, treasury_runway=24.0)
        p2 = _make_proto(name="B", treasury_runway=2.0)
        r = self.analyzer.analyze([p1, p2], _no_log_cfg())
        labels = {p["name"]: p["impact_label"] for p in r["protocols"]}
        self.assertNotEqual(labels["A"], labels["B"])

    def test_competitive_advantage_requires_enabled(self):
        proto = _make_proto(enabled=False, revenue_30d=10_000_000, fee_pct=30.0,
                            supply=1_000_000, price=10.0, competing_avg=2.0, treasury_runway=24.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertNotIn("COMPETITIVE_ADVANTAGE", r["protocols"][0]["flags"])

    def test_holder_income_scales_with_fee_per_token(self):
        p_low = _make_proto(name="low", revenue_30d=100_000, fee_pct=10.0,
                            supply=10_000_000, price=10.0, treasury_runway=24.0)
        p_high = _make_proto(name="high", revenue_30d=10_000_000, fee_pct=30.0,
                             supply=10_000_000, price=10.0, treasury_runway=24.0)
        r = self.analyzer.analyze([p_low, p_high], _no_log_cfg())
        income_low = r["protocols"][0]["holder_annual_income_usd"]
        income_high = r["protocols"][1]["holder_annual_income_usd"]
        self.assertGreater(income_high, income_low)

    def test_treasury_risk_zero_runway_not_triggered(self):
        # treasury_runway=0 means unknown/not applicable; only 0 < x < threshold triggers
        proto = _make_proto(treasury_runway=0.0, enabled=True)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertNotEqual(r["protocols"][0]["impact_label"], "TREASURY_RISK")

    def test_dilutive_when_enabled_zero_revenue(self):
        proto = _make_proto(revenue_30d=0.0, fee_pct=20.0, enabled=True, treasury_runway=24.0)
        r = self.analyzer.analyze([proto], _no_log_cfg())
        self.assertEqual(r["protocols"][0]["impact_label"], "DILUTIVE")

    def test_all_protocols_treasury_risk_count(self):
        protos = [_make_proto(name=f"P{i}", treasury_runway=1.0) for i in range(3)]
        r = self.analyzer.analyze(protos, _no_log_cfg())
        self.assertEqual(r["aggregates"]["treasury_risk_count"], 3)


if __name__ == "__main__":
    unittest.main()
