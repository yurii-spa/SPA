"""
Tests for MP-988: DeFiYieldAggregationEfficiencyAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_yield_aggregation_efficiency_analyzer
"""
import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_yield_aggregation_efficiency_analyzer import (
    DeFiYieldAggregationEfficiencyAnalyzer,
    _compute_capital_utilization_score,
    _compute_compound_boost,
    _compute_efficiency_label,
    _compute_flags,
    _compute_gas_cost_annual_pct,
    _fee_pct_of_gross,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _vault(
    name="VaultA",
    protocol="Yearn",
    strategy_count=3,
    gross_apy_pct=10.0,
    net_apy_pct=8.0,
    management_fee_pct=0.5,
    performance_fee_pct=1.0,
    total_assets_usd=5_000_000.0,
    harvest_interval_hours=6.0,
    auto_compound=True,
    underlying_base_apy_pct=5.0,
    gas_per_harvest_usd=50.0,
    slippage_per_harvest_pct=0.05,
    strategy_utilization_pct=90.0,
):
    return dict(
        name=name,
        protocol=protocol,
        strategy_count=strategy_count,
        gross_apy_pct=gross_apy_pct,
        net_apy_pct=net_apy_pct,
        management_fee_pct=management_fee_pct,
        performance_fee_pct=performance_fee_pct,
        total_assets_usd=total_assets_usd,
        harvest_interval_hours=harvest_interval_hours,
        auto_compound=auto_compound,
        underlying_base_apy_pct=underlying_base_apy_pct,
        gas_per_harvest_usd=gas_per_harvest_usd,
        slippage_per_harvest_pct=slippage_per_harvest_pct,
        strategy_utilization_pct=strategy_utilization_pct,
    )


class TestCompoundBoost(unittest.TestCase):
    """_compute_compound_boost helper."""

    def test_no_auto_compound_returns_zero(self):
        self.assertEqual(_compute_compound_boost(10.0, 6.0, False), 0.0)

    def test_zero_interval_returns_zero(self):
        self.assertEqual(_compute_compound_boost(10.0, 0.0, True), 0.0)

    def test_auto_compound_positive(self):
        boost = _compute_compound_boost(10.0, 6.0, True)
        self.assertGreater(boost, 0.0)

    def test_shorter_interval_gives_more_boost(self):
        boost_6h = _compute_compound_boost(10.0, 6.0, True)
        boost_24h = _compute_compound_boost(10.0, 24.0, True)
        self.assertGreater(boost_6h, boost_24h)

    def test_higher_apy_gives_more_boost(self):
        boost_high = _compute_compound_boost(20.0, 6.0, True)
        boost_low = _compute_compound_boost(5.0, 6.0, True)
        self.assertGreater(boost_high, boost_low)

    def test_boost_never_negative(self):
        for gross in [0.1, 1.0, 5.0, 20.0, 50.0]:
            self.assertGreaterEqual(_compute_compound_boost(gross, 1.0, True), 0.0)

    def test_returns_float(self):
        result = _compute_compound_boost(10.0, 6.0, True)
        self.assertIsInstance(result, float)

    def test_daily_compound_positive(self):
        boost = _compute_compound_boost(12.0, 24.0, True)
        self.assertGreater(boost, 0.0)

    def test_hourly_compound_large_boost(self):
        boost = _compute_compound_boost(50.0, 1.0, True)
        self.assertGreater(boost, 1.0)


class TestGasCostAnnualPct(unittest.TestCase):
    """_compute_gas_cost_annual_pct helper."""

    def test_normal_case(self):
        pct = _compute_gas_cost_annual_pct(50.0, 6.0, 5_000_000.0)
        # 8760/6 * 50 / 5_000_000 * 100
        expected = (8760 / 6 * 50) / 5_000_000 * 100
        self.assertAlmostEqual(pct, expected, places=4)

    def test_zero_assets_returns_zero(self):
        self.assertEqual(_compute_gas_cost_annual_pct(50.0, 6.0, 0.0), 0.0)

    def test_zero_interval_returns_zero(self):
        self.assertEqual(_compute_gas_cost_annual_pct(50.0, 0.0, 5_000_000.0), 0.0)

    def test_more_gas_higher_cost(self):
        low = _compute_gas_cost_annual_pct(10.0, 24.0, 1_000_000.0)
        high = _compute_gas_cost_annual_pct(100.0, 24.0, 1_000_000.0)
        self.assertGreater(high, low)

    def test_shorter_interval_higher_cost(self):
        daily = _compute_gas_cost_annual_pct(50.0, 24.0, 1_000_000.0)
        hourly = _compute_gas_cost_annual_pct(50.0, 1.0, 1_000_000.0)
        self.assertGreater(hourly, daily)

    def test_returns_float(self):
        self.assertIsInstance(_compute_gas_cost_annual_pct(50.0, 6.0, 1_000_000.0), float)


class TestCapitalUtilizationScore(unittest.TestCase):
    """_compute_capital_utilization_score helper."""

    def test_full_utilization_high_score(self):
        score = _compute_capital_utilization_score(100.0, 5)
        self.assertGreater(score, 70.0)

    def test_zero_utilization_low_score(self):
        score = _compute_capital_utilization_score(0.0, 0)
        self.assertAlmostEqual(score, 0.0, places=2)

    def test_more_strategies_higher_score(self):
        low = _compute_capital_utilization_score(80.0, 1)
        high = _compute_capital_utilization_score(80.0, 10)
        self.assertGreater(high, low)

    def test_capped_at_100(self):
        score = _compute_capital_utilization_score(100.0, 100)
        self.assertLessEqual(score, 100.0)

    def test_returns_float(self):
        self.assertIsInstance(_compute_capital_utilization_score(80.0, 3), float)

    def test_under_70_pct_utilization(self):
        score = _compute_capital_utilization_score(50.0, 1)
        self.assertLess(score, 80.0)


class TestFeePctOfGross(unittest.TestCase):
    """_fee_pct_of_gross helper."""

    def test_zero_gross_returns_zero(self):
        self.assertEqual(_fee_pct_of_gross(2.0, 0.0), 0.0)

    def test_correct_ratio(self):
        ratio = _fee_pct_of_gross(2.0, 10.0)
        self.assertAlmostEqual(ratio, 20.0, places=4)

    def test_fees_larger_than_gross(self):
        ratio = _fee_pct_of_gross(15.0, 10.0)
        self.assertAlmostEqual(ratio, 150.0, places=4)

    def test_returns_float(self):
        self.assertIsInstance(_fee_pct_of_gross(1.0, 5.0), float)


class TestEfficiencyLabel(unittest.TestCase):
    """_compute_efficiency_label helper."""

    def test_value_destroying_when_net_below_underlying(self):
        label = _compute_efficiency_label(
            value_add_pct=-2.0, gross_apy_pct=10.0, total_fees_pct=3.0,
            net_apy_pct=3.0, underlying_base_apy_pct=5.0,
        )
        self.assertEqual(label, "VALUE_DESTROYING")

    def test_highly_efficient(self):
        # value_add > 3%, fee_drag < 30%
        label = _compute_efficiency_label(
            value_add_pct=4.0, gross_apy_pct=10.0, total_fees_pct=2.0,
            net_apy_pct=9.0, underlying_base_apy_pct=5.0,
        )
        self.assertEqual(label, "HIGHLY_EFFICIENT")

    def test_efficient(self):
        # value_add > 1.5%, fee_drag < 40%
        label = _compute_efficiency_label(
            value_add_pct=2.0, gross_apy_pct=10.0, total_fees_pct=3.0,
            net_apy_pct=7.0, underlying_base_apy_pct=5.0,
        )
        self.assertEqual(label, "EFFICIENT")

    def test_neutral_zero_value_add(self):
        label = _compute_efficiency_label(
            value_add_pct=0.5, gross_apy_pct=10.0, total_fees_pct=2.0,
            net_apy_pct=5.5, underlying_base_apy_pct=5.0,
        )
        self.assertEqual(label, "NEUTRAL")

    def test_inefficient_high_fee_drag(self):
        # value_add > 0 but fee_drag > 50%
        label = _compute_efficiency_label(
            value_add_pct=1.0, gross_apy_pct=10.0, total_fees_pct=6.0,
            net_apy_pct=6.0, underlying_base_apy_pct=5.0,
        )
        self.assertEqual(label, "INEFFICIENT")

    def test_neutral_not_destroying(self):
        label = _compute_efficiency_label(
            value_add_pct=0.0, gross_apy_pct=8.0, total_fees_pct=1.0,
            net_apy_pct=5.0, underlying_base_apy_pct=5.0,
        )
        self.assertIn(label, {"NEUTRAL", "EFFICIENT", "HIGHLY_EFFICIENT"})

    def test_value_destroying_exact_equality_not_triggered(self):
        # net == underlying → not VALUE_DESTROYING (boundary)
        label = _compute_efficiency_label(
            value_add_pct=0.0, gross_apy_pct=8.0, total_fees_pct=2.0,
            net_apy_pct=5.0, underlying_base_apy_pct=5.0,
        )
        self.assertNotEqual(label, "VALUE_DESTROYING")

    def test_label_is_string(self):
        label = _compute_efficiency_label(3.0, 10.0, 2.0, 8.0, 5.0)
        self.assertIsInstance(label, str)


class TestComputeFlags(unittest.TestCase):
    """_compute_flags helper."""

    def test_no_flags_clean_vault(self):
        flags = _compute_flags(
            net_apy_pct=8.0, underlying_base_apy_pct=5.0,
            total_fees_pct=1.0, gross_apy_pct=10.0,
            compound_boost_pct=0.5, harvest_cost_ratio=1.0,
            strategy_utilization_pct=90.0,
        )
        self.assertEqual(flags, [])

    def test_value_destroying_flag(self):
        flags = _compute_flags(
            net_apy_pct=3.0, underlying_base_apy_pct=5.0,
            total_fees_pct=1.0, gross_apy_pct=10.0,
            compound_boost_pct=0.0, harvest_cost_ratio=1.0,
            strategy_utilization_pct=90.0,
        )
        self.assertIn("VALUE_DESTROYING", flags)

    def test_high_fee_drag_flag(self):
        # fees = 5%, gross = 10% → 50% drag > 40%
        flags = _compute_flags(
            net_apy_pct=6.0, underlying_base_apy_pct=5.0,
            total_fees_pct=5.0, gross_apy_pct=10.0,
            compound_boost_pct=0.0, harvest_cost_ratio=1.0,
            strategy_utilization_pct=90.0,
        )
        self.assertIn("HIGH_FEE_DRAG", flags)

    def test_compound_heavy_flag(self):
        flags = _compute_flags(
            net_apy_pct=8.0, underlying_base_apy_pct=5.0,
            total_fees_pct=1.0, gross_apy_pct=10.0,
            compound_boost_pct=3.0, harvest_cost_ratio=1.0,
            strategy_utilization_pct=90.0,
        )
        self.assertIn("COMPOUND_HEAVY", flags)

    def test_gas_intensive_flag(self):
        flags = _compute_flags(
            net_apy_pct=8.0, underlying_base_apy_pct=5.0,
            total_fees_pct=1.0, gross_apy_pct=10.0,
            compound_boost_pct=0.0, harvest_cost_ratio=6.0,
            strategy_utilization_pct=90.0,
        )
        self.assertIn("GAS_INTENSIVE", flags)

    def test_under_utilized_flag(self):
        flags = _compute_flags(
            net_apy_pct=8.0, underlying_base_apy_pct=5.0,
            total_fees_pct=1.0, gross_apy_pct=10.0,
            compound_boost_pct=0.0, harvest_cost_ratio=1.0,
            strategy_utilization_pct=60.0,
        )
        self.assertIn("UNDER_UTILIZED", flags)

    def test_multiple_flags_simultaneously(self):
        flags = _compute_flags(
            net_apy_pct=3.0, underlying_base_apy_pct=5.0,
            total_fees_pct=5.0, gross_apy_pct=10.0,
            compound_boost_pct=3.0, harvest_cost_ratio=8.0,
            strategy_utilization_pct=50.0,
        )
        self.assertIn("VALUE_DESTROYING", flags)
        self.assertIn("HIGH_FEE_DRAG", flags)
        self.assertIn("COMPOUND_HEAVY", flags)
        self.assertIn("GAS_INTENSIVE", flags)
        self.assertIn("UNDER_UTILIZED", flags)

    def test_flags_is_list(self):
        self.assertIsInstance(_compute_flags(8.0, 5.0, 1.0, 10.0, 0.0, 1.0, 90.0), list)

    def test_high_fee_drag_boundary_exactly_40_not_triggered(self):
        # 40% fee drag → NOT triggered (> 40 required)
        flags = _compute_flags(
            net_apy_pct=6.0, underlying_base_apy_pct=5.0,
            total_fees_pct=4.0, gross_apy_pct=10.0,
            compound_boost_pct=0.0, harvest_cost_ratio=1.0,
            strategy_utilization_pct=90.0,
        )
        self.assertNotIn("HIGH_FEE_DRAG", flags)

    def test_under_utilized_boundary_exactly_70_not_triggered(self):
        flags = _compute_flags(
            net_apy_pct=8.0, underlying_base_apy_pct=5.0,
            total_fees_pct=1.0, gross_apy_pct=10.0,
            compound_boost_pct=0.0, harvest_cost_ratio=1.0,
            strategy_utilization_pct=70.0,
        )
        self.assertNotIn("UNDER_UTILIZED", flags)


class TestAnalyzeBasic(unittest.TestCase):
    """analyze() basic structure and content."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "log.json")
        self.analyzer = DeFiYieldAggregationEfficiencyAnalyzer(log_path=self.log_path)

    def test_empty_vaults_returns_empty_list(self):
        result = self.analyzer.analyze([], {})
        self.assertEqual(result["vaults"], [])
        self.assertEqual(result["vault_count"], 0)

    def test_single_vault_returns_one_entry(self):
        result = self.analyzer.analyze([_vault()], {})
        self.assertEqual(len(result["vaults"]), 1)

    def test_output_has_timestamp(self):
        result = self.analyzer.analyze([], {})
        self.assertIn("timestamp", result)

    def test_output_has_vault_count(self):
        result = self.analyzer.analyze([_vault(), _vault(name="B")], {})
        self.assertEqual(result["vault_count"], 2)

    def test_output_has_aggregates(self):
        result = self.analyzer.analyze([_vault()], {})
        self.assertIn("aggregates", result)

    def test_vault_entry_has_all_fields(self):
        result = self.analyzer.analyze([_vault()], {})
        v = result["vaults"][0]
        for field in [
            "name", "protocol", "value_add_pct", "fee_efficiency_ratio",
            "compound_boost_pct", "harvest_cost_ratio", "capital_utilization_score",
            "efficiency_label", "flags",
        ]:
            self.assertIn(field, v, f"Missing field: {field}")

    def test_name_propagated(self):
        result = self.analyzer.analyze([_vault(name="MyVault")], {})
        self.assertEqual(result["vaults"][0]["name"], "MyVault")

    def test_protocol_propagated(self):
        result = self.analyzer.analyze([_vault(protocol="Beefy")], {})
        self.assertEqual(result["vaults"][0]["protocol"], "Beefy")

    def test_value_add_correct(self):
        v = _vault(net_apy_pct=8.0, underlying_base_apy_pct=5.0)
        result = self.analyzer.analyze([v], {})
        self.assertAlmostEqual(result["vaults"][0]["value_add_pct"], 3.0, places=4)

    def test_total_fees_correct(self):
        v = _vault(management_fee_pct=0.5, performance_fee_pct=1.5)
        result = self.analyzer.analyze([v], {})
        self.assertAlmostEqual(result["vaults"][0]["total_fees_pct"], 2.0, places=4)

    def test_fee_efficiency_ratio_none_when_no_fees(self):
        v = _vault(management_fee_pct=0.0, performance_fee_pct=0.0)
        result = self.analyzer.analyze([v], {})
        self.assertIsNone(result["vaults"][0]["fee_efficiency_ratio"])

    def test_fee_efficiency_ratio_positive_value_add(self):
        v = _vault(
            net_apy_pct=8.0, underlying_base_apy_pct=5.0,
            management_fee_pct=1.0, performance_fee_pct=0.0,
        )
        result = self.analyzer.analyze([v], {})
        ratio = result["vaults"][0]["fee_efficiency_ratio"]
        self.assertIsNotNone(ratio)
        self.assertAlmostEqual(ratio, 3.0 / 1.0, places=4)

    def test_compound_boost_zero_no_auto(self):
        v = _vault(auto_compound=False)
        result = self.analyzer.analyze([v], {})
        self.assertEqual(result["vaults"][0]["compound_boost_pct"], 0.0)

    def test_compound_boost_positive_with_auto(self):
        v = _vault(auto_compound=True, harvest_interval_hours=1.0, gross_apy_pct=20.0)
        result = self.analyzer.analyze([v], {})
        self.assertGreater(result["vaults"][0]["compound_boost_pct"], 0.0)

    def test_capital_utilization_score_range(self):
        v = _vault(strategy_utilization_pct=80.0, strategy_count=3)
        result = self.analyzer.analyze([v], {})
        score = result["vaults"][0]["capital_utilization_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_efficiency_label_present(self):
        result = self.analyzer.analyze([_vault()], {})
        label = result["vaults"][0]["efficiency_label"]
        self.assertIn(label, {
            "HIGHLY_EFFICIENT", "EFFICIENT", "NEUTRAL",
            "INEFFICIENT", "VALUE_DESTROYING",
        })

    def test_flags_is_list(self):
        result = self.analyzer.analyze([_vault()], {})
        self.assertIsInstance(result["vaults"][0]["flags"], list)

    def test_multiple_vaults_count(self):
        vaults = [_vault(name=f"V{i}") for i in range(5)]
        result = self.analyzer.analyze(vaults, {})
        self.assertEqual(result["vault_count"], 5)
        self.assertEqual(len(result["vaults"]), 5)


class TestEfficiencyLabelIntegration(unittest.TestCase):
    """end-to-end label assignment via analyze()."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = DeFiYieldAggregationEfficiencyAnalyzer(
            log_path=os.path.join(self.tmp, "log.json")
        )

    def test_highly_efficient_label(self):
        v = _vault(
            gross_apy_pct=10.0, net_apy_pct=9.5, underlying_base_apy_pct=5.0,
            management_fee_pct=0.2, performance_fee_pct=0.5,
        )
        result = self.analyzer.analyze([v], {})
        self.assertEqual(result["vaults"][0]["efficiency_label"], "HIGHLY_EFFICIENT")

    def test_efficient_label(self):
        v = _vault(
            gross_apy_pct=10.0, net_apy_pct=7.5, underlying_base_apy_pct=5.0,
            management_fee_pct=1.0, performance_fee_pct=2.0,
        )
        result = self.analyzer.analyze([v], {})
        self.assertEqual(result["vaults"][0]["efficiency_label"], "EFFICIENT")

    def test_value_destroying_label(self):
        v = _vault(net_apy_pct=2.0, underlying_base_apy_pct=4.0)
        result = self.analyzer.analyze([v], {})
        self.assertEqual(result["vaults"][0]["efficiency_label"], "VALUE_DESTROYING")

    def test_inefficient_label_high_fees(self):
        v = _vault(
            gross_apy_pct=10.0, net_apy_pct=5.5, underlying_base_apy_pct=5.0,
            management_fee_pct=3.0, performance_fee_pct=3.0,
        )
        result = self.analyzer.analyze([v], {})
        self.assertEqual(result["vaults"][0]["efficiency_label"], "INEFFICIENT")


class TestAggregates(unittest.TestCase):
    """aggregates block correctness."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = DeFiYieldAggregationEfficiencyAnalyzer(
            log_path=os.path.join(self.tmp, "log.json")
        )

    def test_empty_vaults_aggregates(self):
        result = self.analyzer.analyze([], {})
        agg = result["aggregates"]
        self.assertIsNone(agg["most_efficient"])
        self.assertIsNone(agg["least_efficient"])
        self.assertEqual(agg["average_value_add"], 0.0)
        self.assertEqual(agg["value_destroying_count"], 0)
        self.assertIsNone(agg["average_fee_efficiency"])

    def test_most_efficient_is_highest_value_add(self):
        v1 = _vault(name="BestVault", net_apy_pct=10.0, underlying_base_apy_pct=5.0)
        v2 = _vault(name="WorseVault", net_apy_pct=6.0, underlying_base_apy_pct=5.0)
        result = self.analyzer.analyze([v1, v2], {})
        self.assertEqual(result["aggregates"]["most_efficient"], "BestVault")

    def test_least_efficient_is_lowest_value_add(self):
        v1 = _vault(name="BestVault", net_apy_pct=10.0, underlying_base_apy_pct=5.0)
        v2 = _vault(name="BadVault", net_apy_pct=4.0, underlying_base_apy_pct=5.0)
        result = self.analyzer.analyze([v1, v2], {})
        self.assertEqual(result["aggregates"]["least_efficient"], "BadVault")

    def test_average_value_add_correct(self):
        v1 = _vault(name="A", net_apy_pct=8.0, underlying_base_apy_pct=5.0)
        v2 = _vault(name="B", net_apy_pct=7.0, underlying_base_apy_pct=5.0)
        result = self.analyzer.analyze([v1, v2], {})
        self.assertAlmostEqual(result["aggregates"]["average_value_add"], 2.5, places=4)

    def test_value_destroying_count(self):
        v1 = _vault(name="Good", net_apy_pct=8.0, underlying_base_apy_pct=5.0)
        v2 = _vault(name="Bad", net_apy_pct=3.0, underlying_base_apy_pct=5.0)
        v3 = _vault(name="AlsoBad", net_apy_pct=1.0, underlying_base_apy_pct=5.0)
        result = self.analyzer.analyze([v1, v2, v3], {})
        self.assertEqual(result["aggregates"]["value_destroying_count"], 2)

    def test_average_fee_efficiency_none_all_zero_fees(self):
        v = _vault(management_fee_pct=0.0, performance_fee_pct=0.0)
        result = self.analyzer.analyze([v], {})
        self.assertIsNone(result["aggregates"]["average_fee_efficiency"])

    def test_average_fee_efficiency_calculated(self):
        v1 = _vault(
            name="A", net_apy_pct=8.0, underlying_base_apy_pct=5.0,
            management_fee_pct=1.0, performance_fee_pct=0.0,
        )
        v2 = _vault(
            name="B", net_apy_pct=7.0, underlying_base_apy_pct=5.0,
            management_fee_pct=1.0, performance_fee_pct=0.0,
        )
        result = self.analyzer.analyze([v1, v2], {})
        # v1: value_add=3, fee=1 → ratio=3; v2: value_add=2, fee=1 → ratio=2; avg=2.5
        self.assertAlmostEqual(result["aggregates"]["average_fee_efficiency"], 2.5, places=4)

    def test_single_vault_most_and_least_same(self):
        v = _vault(name="Solo")
        result = self.analyzer.analyze([v], {})
        self.assertEqual(result["aggregates"]["most_efficient"], "Solo")
        self.assertEqual(result["aggregates"]["least_efficient"], "Solo")

    def test_value_destroying_count_zero_when_all_good(self):
        vaults = [_vault(name=f"V{i}", net_apy_pct=8.0, underlying_base_apy_pct=5.0)
                  for i in range(3)]
        result = self.analyzer.analyze(vaults, {})
        self.assertEqual(result["aggregates"]["value_destroying_count"], 0)


class TestFlagsIntegration(unittest.TestCase):
    """Flag assertions via full analyze() path."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = DeFiYieldAggregationEfficiencyAnalyzer(
            log_path=os.path.join(self.tmp, "log.json")
        )

    def test_gas_intensive_flag_triggered(self):
        # gas_per_harvest=500, interval=24h, assets=100k → annual gas = 365*500=182500
        # pct = 182500/100000*100 = 182.5%
        # harvest_cost_ratio = 182.5/10*100 = 1825% >> 5% → GAS_INTENSIVE
        v = _vault(
            gas_per_harvest_usd=500.0, harvest_interval_hours=24.0,
            total_assets_usd=100_000.0, gross_apy_pct=10.0,
        )
        result = self.analyzer.analyze([v], {})
        self.assertIn("GAS_INTENSIVE", result["vaults"][0]["flags"])

    def test_gas_intensive_flag_not_triggered_when_small(self):
        # gas_per_harvest=1, 24h, 10M AUM, gross=10%
        v = _vault(
            gas_per_harvest_usd=1.0, harvest_interval_hours=24.0,
            total_assets_usd=10_000_000.0, gross_apy_pct=10.0,
        )
        result = self.analyzer.analyze([v], {})
        self.assertNotIn("GAS_INTENSIVE", result["vaults"][0]["flags"])

    def test_under_utilized_flag_triggered(self):
        v = _vault(strategy_utilization_pct=50.0)
        result = self.analyzer.analyze([v], {})
        self.assertIn("UNDER_UTILIZED", result["vaults"][0]["flags"])

    def test_value_destroying_flag_and_label_consistent(self):
        v = _vault(net_apy_pct=2.0, underlying_base_apy_pct=4.0)
        result = self.analyzer.analyze([v], {})
        entry = result["vaults"][0]
        self.assertIn("VALUE_DESTROYING", entry["flags"])
        self.assertEqual(entry["efficiency_label"], "VALUE_DESTROYING")


class TestPersistAndLog(unittest.TestCase):
    """Ring-buffer log persistence."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "yield_eff_log.json")
        self.analyzer = DeFiYieldAggregationEfficiencyAnalyzer(log_path=self.log_path)

    def test_no_log_file_without_persist(self):
        self.analyzer.analyze([_vault()], {"persist": False})
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_file_created_with_persist(self):
        self.analyzer.analyze([_vault()], {"persist": True})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.analyzer.analyze([_vault()], {"persist": True})
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertIsInstance(log, list)

    def test_log_grows_with_multiple_calls(self):
        for _ in range(3):
            self.analyzer.analyze([_vault()], {"persist": True})
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertEqual(len(log), 3)

    def test_log_entry_has_timestamp(self):
        self.analyzer.analyze([_vault()], {"persist": True})
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertIn("timestamp", log[0])

    def test_log_entry_has_vaults(self):
        self.analyzer.analyze([_vault()], {"persist": True})
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertIn("vaults", log[0])

    def test_log_ring_buffer_cap(self):
        for _ in range(110):
            self.analyzer.analyze([_vault()], {"persist": True})
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertLessEqual(len(log), 100)

    def test_log_cap_keeps_latest(self):
        for i in range(105):
            # Use vault_count as a marker via different vault lists
            self.analyzer.analyze([_vault(name=f"V{i}")], {"persist": True})
        with open(self.log_path) as f:
            log = json.load(f)
        # Latest entry should have vault name V104
        self.assertEqual(log[-1]["vaults"][0]["name"], "V104")

    def test_atomic_write_no_tmp_file_remains(self):
        self.analyzer.analyze([_vault()], {"persist": True})
        tmp_files = [f for f in os.listdir(self.tmp) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])

    def test_persist_default_false(self):
        self.analyzer.analyze([_vault()], {})
        self.assertFalse(os.path.exists(self.log_path))


class TestEdgeCases(unittest.TestCase):
    """Edge cases and robustness."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = DeFiYieldAggregationEfficiencyAnalyzer(
            log_path=os.path.join(self.tmp, "log.json")
        )

    def test_zero_gross_apy_no_crash(self):
        v = _vault(gross_apy_pct=0.0, net_apy_pct=0.0)
        result = self.analyzer.analyze([v], {})
        self.assertEqual(len(result["vaults"]), 1)

    def test_very_large_assets(self):
        v = _vault(total_assets_usd=1e12)
        result = self.analyzer.analyze([v], {})
        self.assertIn("gas_cost_annual_pct", result["vaults"][0])

    def test_negative_value_add_sets_correct_label(self):
        v = _vault(net_apy_pct=0.5, underlying_base_apy_pct=3.0)
        result = self.analyzer.analyze([v], {})
        self.assertEqual(result["vaults"][0]["efficiency_label"], "VALUE_DESTROYING")

    def test_missing_fields_use_defaults(self):
        v = {"name": "MinVault"}
        result = self.analyzer.analyze([v], {})
        self.assertEqual(len(result["vaults"]), 1)

    def test_strategy_count_zero(self):
        v = _vault(strategy_count=0)
        result = self.analyzer.analyze([v], {})
        score = result["vaults"][0]["capital_utilization_score"]
        self.assertGreaterEqual(score, 0.0)

    def test_harvest_cost_ratio_zero_when_no_gas(self):
        v = _vault(gas_per_harvest_usd=0.0)
        result = self.analyzer.analyze([v], {})
        self.assertEqual(result["vaults"][0]["harvest_cost_ratio"], 0.0)

    def test_slippage_propagated(self):
        v = _vault(slippage_per_harvest_pct=0.1)
        result = self.analyzer.analyze([v], {})
        self.assertEqual(result["vaults"][0]["slippage_per_harvest_pct"], 0.1)

    def test_result_is_dict(self):
        result = self.analyzer.analyze([_vault()], {})
        self.assertIsInstance(result, dict)

    def test_config_persist_true_string_coerced(self):
        # persist must work as bool True
        self.analyzer.analyze([_vault()], {"persist": True})
        self.assertTrue(os.path.exists(self.analyzer.log_path))


if __name__ == "__main__":
    unittest.main()
