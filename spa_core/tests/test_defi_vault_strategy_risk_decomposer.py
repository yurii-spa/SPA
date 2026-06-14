"""
Tests for MP-926 DeFiVaultStrategyRiskDecomposer.
Run: python3 -m unittest spa_core.tests.test_defi_vault_strategy_risk_decomposer
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure repo root on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_vault_strategy_risk_decomposer import (
    DeFiVaultStrategyRiskDecomposer,
    _weighted_risk,
    _composite_risk_score,
    _risk_label,
    _dominant_risk_type,
    _compute_flags,
    FLAG_CONCENTRATION_RISK,
    FLAG_UNINSURED_HIGH_RISK,
    FLAG_HIGH_ORACLE_EXPOSURE,
    FLAG_COMPLEX_STRATEGY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_strategy(
    name="S1",
    allocation_pct=100.0,
    sc_risk=5.0,
    liq_risk=5.0,
    oracle_risk=5.0,
    cp_risk=5.0,
    apy_pct=8.0,
) -> dict:
    return {
        "name": name,
        "allocation_pct": allocation_pct,
        "smart_contract_risk": sc_risk,
        "liquidity_risk": liq_risk,
        "oracle_risk": oracle_risk,
        "counterparty_risk": cp_risk,
        "apy_pct": apy_pct,
    }


def make_vault(
    name="TestVault",
    protocol="TestProtocol",
    strategies=None,
    total_tvl_usd=1_000_000.0,
    insurance_coverage_pct=0.0,
) -> dict:
    if strategies is None:
        strategies = [make_strategy()]
    return {
        "name": name,
        "protocol": protocol,
        "strategies": strategies,
        "total_tvl_usd": total_tvl_usd,
        "insurance_coverage_pct": insurance_coverage_pct,
    }


class TestWeightedRisk(unittest.TestCase):
    """Unit tests for _weighted_risk helper."""

    def test_single_strategy_100pct(self):
        strategies = [make_strategy(sc_risk=7.0, allocation_pct=100.0)]
        self.assertAlmostEqual(_weighted_risk(strategies, "smart_contract_risk"), 7.0)

    def test_two_strategies_equal_split(self):
        strategies = [
            make_strategy(name="A", allocation_pct=50.0, sc_risk=4.0),
            make_strategy(name="B", allocation_pct=50.0, sc_risk=8.0),
        ]
        self.assertAlmostEqual(_weighted_risk(strategies, "smart_contract_risk"), 6.0)

    def test_two_strategies_unequal_split(self):
        strategies = [
            make_strategy(name="A", allocation_pct=30.0, sc_risk=0.0),
            make_strategy(name="B", allocation_pct=70.0, sc_risk=10.0),
        ]
        result = _weighted_risk(strategies, "smart_contract_risk")
        self.assertAlmostEqual(result, 7.0)

    def test_zero_allocation_returns_zero(self):
        strategies = [make_strategy(allocation_pct=0.0, sc_risk=9.0)]
        self.assertEqual(_weighted_risk(strategies, "smart_contract_risk"), 0.0)

    def test_empty_strategies_returns_zero(self):
        self.assertEqual(_weighted_risk([], "smart_contract_risk"), 0.0)

    def test_liquidity_risk_key(self):
        strategies = [make_strategy(liq_risk=6.0, allocation_pct=100.0)]
        self.assertAlmostEqual(_weighted_risk(strategies, "liquidity_risk"), 6.0)

    def test_oracle_risk_key(self):
        strategies = [make_strategy(oracle_risk=3.5, allocation_pct=100.0)]
        self.assertAlmostEqual(_weighted_risk(strategies, "oracle_risk"), 3.5)

    def test_counterparty_risk_key(self):
        strategies = [make_strategy(cp_risk=9.0, allocation_pct=100.0)]
        self.assertAlmostEqual(_weighted_risk(strategies, "counterparty_risk"), 9.0)

    def test_three_strategies_weighted(self):
        strategies = [
            make_strategy(name="A", allocation_pct=25.0, sc_risk=0.0),
            make_strategy(name="B", allocation_pct=25.0, sc_risk=10.0),
            make_strategy(name="C", allocation_pct=50.0, sc_risk=5.0),
        ]
        # (0*25 + 10*25 + 5*50) / 100 = (0+250+250)/100 = 5.0
        self.assertAlmostEqual(_weighted_risk(strategies, "smart_contract_risk"), 5.0)


class TestCompositeRiskScore(unittest.TestCase):
    """Unit tests for _composite_risk_score helper."""

    def test_all_five_gives_50(self):
        score = _composite_risk_score(5.0, 5.0, 5.0, 5.0)
        self.assertAlmostEqual(score, 50.0)

    def test_all_zero_gives_zero(self):
        self.assertAlmostEqual(_composite_risk_score(0.0, 0.0, 0.0, 0.0), 0.0)

    def test_all_ten_gives_100(self):
        self.assertAlmostEqual(_composite_risk_score(10.0, 10.0, 10.0, 10.0), 100.0)

    def test_capped_at_100(self):
        self.assertEqual(_composite_risk_score(10.0, 10.0, 10.0, 10.0), 100.0)

    def test_average_formula(self):
        # (2 + 4 + 6 + 8) / 4 = 5.0 → 50.0
        self.assertAlmostEqual(_composite_risk_score(2.0, 4.0, 6.0, 8.0), 50.0)

    def test_partial_components(self):
        # (10 + 0 + 0 + 0) / 4 * 10 = 25
        self.assertAlmostEqual(_composite_risk_score(10.0, 0.0, 0.0, 0.0), 25.0)

    def test_result_not_negative(self):
        self.assertGreaterEqual(_composite_risk_score(-1.0, -1.0, -1.0, -1.0), 0.0)


class TestRiskLabel(unittest.TestCase):
    """Unit tests for _risk_label helper."""

    def test_conservative_at_0(self):
        self.assertEqual(_risk_label(0.0), "CONSERVATIVE")

    def test_conservative_at_20(self):
        self.assertEqual(_risk_label(20.0), "CONSERVATIVE")

    def test_moderate_at_21(self):
        self.assertEqual(_risk_label(21.0), "MODERATE")

    def test_moderate_at_40(self):
        self.assertEqual(_risk_label(40.0), "MODERATE")

    def test_balanced_at_41(self):
        self.assertEqual(_risk_label(41.0), "BALANCED")

    def test_balanced_at_55(self):
        self.assertEqual(_risk_label(55.0), "BALANCED")

    def test_aggressive_at_56(self):
        self.assertEqual(_risk_label(56.0), "AGGRESSIVE")

    def test_aggressive_at_70(self):
        self.assertEqual(_risk_label(70.0), "AGGRESSIVE")

    def test_speculative_at_71(self):
        self.assertEqual(_risk_label(71.0), "SPECULATIVE")

    def test_speculative_at_100(self):
        self.assertEqual(_risk_label(100.0), "SPECULATIVE")


class TestDominantRiskType(unittest.TestCase):
    """Unit tests for _dominant_risk_type helper."""

    def test_smart_contract_dominates(self):
        self.assertEqual(_dominant_risk_type(9.0, 1.0, 1.0, 1.0), "smart_contract")

    def test_liquidity_dominates(self):
        self.assertEqual(_dominant_risk_type(1.0, 9.0, 1.0, 1.0), "liquidity")

    def test_oracle_dominates(self):
        self.assertEqual(_dominant_risk_type(1.0, 1.0, 9.0, 1.0), "oracle")

    def test_counterparty_dominates(self):
        self.assertEqual(_dominant_risk_type(1.0, 1.0, 1.0, 9.0), "counterparty")

    def test_all_equal_returns_first(self):
        # When all equal, max() returns first max found = smart_contract
        result = _dominant_risk_type(5.0, 5.0, 5.0, 5.0)
        self.assertEqual(result, "smart_contract")

    def test_all_zero_returns_first(self):
        result = _dominant_risk_type(0.0, 0.0, 0.0, 0.0)
        self.assertEqual(result, "smart_contract")


class TestFlags(unittest.TestCase):
    """Unit tests for _compute_flags helper."""

    def _strategies_with_alloc(self, *allocs):
        return [make_strategy(name=f"S{i}", allocation_pct=a) for i, a in enumerate(allocs)]

    def test_concentration_risk_above_60(self):
        strats = self._strategies_with_alloc(61.0, 39.0)
        flags = _compute_flags(strats, 50.0, 3.0, 50.0, {})
        self.assertIn(FLAG_CONCENTRATION_RISK, flags)

    def test_no_concentration_risk_at_60(self):
        strats = self._strategies_with_alloc(60.0, 40.0)
        flags = _compute_flags(strats, 50.0, 3.0, 50.0, {})
        self.assertNotIn(FLAG_CONCENTRATION_RISK, flags)

    def test_concentration_risk_100pct_single(self):
        strats = self._strategies_with_alloc(100.0)
        flags = _compute_flags(strats, 50.0, 3.0, 50.0, {})
        self.assertIn(FLAG_CONCENTRATION_RISK, flags)

    def test_uninsured_high_risk_both_conditions(self):
        strats = self._strategies_with_alloc(50.0, 50.0)
        # composite > 70, insurance < 10
        flags = _compute_flags(strats, 75.0, 3.0, 5.0, {})
        self.assertIn(FLAG_UNINSURED_HIGH_RISK, flags)

    def test_no_uninsured_high_risk_low_composite(self):
        strats = self._strategies_with_alloc(50.0, 50.0)
        # composite = 60 (not > 70)
        flags = _compute_flags(strats, 60.0, 3.0, 5.0, {})
        self.assertNotIn(FLAG_UNINSURED_HIGH_RISK, flags)

    def test_no_uninsured_high_risk_adequate_insurance(self):
        strats = self._strategies_with_alloc(50.0, 50.0)
        # composite > 70 but insurance >= 10
        flags = _compute_flags(strats, 80.0, 3.0, 10.0, {})
        self.assertNotIn(FLAG_UNINSURED_HIGH_RISK, flags)

    def test_high_oracle_exposure_above_7(self):
        strats = self._strategies_with_alloc(100.0)
        flags = _compute_flags(strats, 50.0, 7.1, 50.0, {})
        self.assertIn(FLAG_HIGH_ORACLE_EXPOSURE, flags)

    def test_no_high_oracle_exposure_at_7(self):
        strats = self._strategies_with_alloc(100.0)
        flags = _compute_flags(strats, 50.0, 7.0, 50.0, {})
        self.assertNotIn(FLAG_HIGH_ORACLE_EXPOSURE, flags)

    def test_complex_strategy_above_5(self):
        strats = self._strategies_with_alloc(*([16.67] * 6))
        flags = _compute_flags(strats, 50.0, 3.0, 50.0, {})
        self.assertIn(FLAG_COMPLEX_STRATEGY, flags)

    def test_no_complex_strategy_at_5(self):
        strats = self._strategies_with_alloc(*([20.0] * 5))
        flags = _compute_flags(strats, 50.0, 3.0, 50.0, {})
        self.assertNotIn(FLAG_COMPLEX_STRATEGY, flags)

    def test_all_flags_at_once(self):
        strats = self._strategies_with_alloc(*([16.67] * 6))
        strats[0]["allocation_pct"] = 65.0
        flags = _compute_flags(strats, 80.0, 8.0, 5.0, {})
        self.assertIn(FLAG_CONCENTRATION_RISK, flags)
        self.assertIn(FLAG_UNINSURED_HIGH_RISK, flags)
        self.assertIn(FLAG_HIGH_ORACLE_EXPOSURE, flags)
        self.assertIn(FLAG_COMPLEX_STRATEGY, flags)

    def test_no_flags_when_none_apply(self):
        strats = self._strategies_with_alloc(30.0, 30.0, 40.0)
        flags = _compute_flags(strats, 30.0, 3.0, 50.0, {})
        self.assertEqual(flags, [])

    def test_custom_concentration_threshold(self):
        strats = self._strategies_with_alloc(55.0, 45.0)
        # custom threshold of 50 → 55 > 50 → flag
        flags = _compute_flags(strats, 30.0, 3.0, 50.0, {"concentration_threshold": 50.0})
        self.assertIn(FLAG_CONCENTRATION_RISK, flags)

    def test_custom_oracle_threshold(self):
        strats = self._strategies_with_alloc(100.0)
        # custom threshold = 8, oracle_risk=7.5 → no flag
        flags = _compute_flags(strats, 30.0, 7.5, 50.0, {"oracle_risk_threshold": 8.0})
        self.assertNotIn(FLAG_HIGH_ORACLE_EXPOSURE, flags)

    def test_custom_complex_strategy_count(self):
        strats = self._strategies_with_alloc(*([25.0] * 4))
        # custom count = 3 → 4 > 3 → flag
        flags = _compute_flags(strats, 30.0, 3.0, 50.0, {"complex_strategy_count": 3})
        self.assertIn(FLAG_COMPLEX_STRATEGY, flags)


class TestDecomposerBasic(unittest.TestCase):
    """Integration tests for DeFiVaultStrategyRiskDecomposer.decompose()."""

    def setUp(self):
        self.decomposer = DeFiVaultStrategyRiskDecomposer()
        self.tmpdir = tempfile.mkdtemp()

    def _run(self, vaults, config=None):
        return self.decomposer.decompose(
            vaults, config or {}, data_dir=self.tmpdir, dry_run=False
        )

    def test_result_has_vaults_key(self):
        result = self._run([make_vault()])
        self.assertIn("vaults", result)

    def test_result_has_aggregates_key(self):
        result = self._run([make_vault()])
        self.assertIn("aggregates", result)

    def test_vault_keys_present(self):
        result = self._run([make_vault(name="V1")])
        self.assertIn("V1", result["vaults"])

    def test_per_vault_result_keys(self):
        result = self._run([make_vault(name="V1")])
        vr = result["vaults"]["V1"]
        expected_keys = [
            "weighted_sc_risk", "weighted_liquidity_risk", "weighted_oracle_risk",
            "weighted_counterparty_risk", "composite_risk_score", "insurance_adjusted_risk",
            "dominant_risk_type", "risk_label", "flags",
        ]
        for k in expected_keys:
            self.assertIn(k, vr)

    def test_aggregate_keys_present(self):
        result = self._run([make_vault()])
        agg = result["aggregates"]
        for k in ["safest_vault", "riskiest_vault", "average_composite_risk",
                  "conservative_count", "speculative_count", "vault_count"]:
            self.assertIn(k, agg)

    def test_single_vault_50_composite(self):
        vault = make_vault(strategies=[make_strategy(
            sc_risk=5.0, liq_risk=5.0, oracle_risk=5.0, cp_risk=5.0, allocation_pct=100.0
        )])
        result = self._run([vault])
        self.assertAlmostEqual(result["vaults"]["TestVault"]["composite_risk_score"], 50.0)

    def test_single_vault_zero_composite(self):
        vault = make_vault(strategies=[make_strategy(
            sc_risk=0.0, liq_risk=0.0, oracle_risk=0.0, cp_risk=0.0, allocation_pct=100.0
        )])
        result = self._run([vault])
        self.assertAlmostEqual(result["vaults"]["TestVault"]["composite_risk_score"], 0.0)

    def test_single_vault_100_composite(self):
        vault = make_vault(strategies=[make_strategy(
            sc_risk=10.0, liq_risk=10.0, oracle_risk=10.0, cp_risk=10.0, allocation_pct=100.0
        )])
        result = self._run([vault])
        self.assertAlmostEqual(result["vaults"]["TestVault"]["composite_risk_score"], 100.0)

    def test_insurance_adjustment_50pct(self):
        vault = make_vault(
            strategies=[make_strategy(sc_risk=5.0, liq_risk=5.0, oracle_risk=5.0, cp_risk=5.0)],
            insurance_coverage_pct=50.0,
        )
        result = self._run([vault])
        vr = result["vaults"]["TestVault"]
        self.assertAlmostEqual(vr["insurance_adjusted_risk"], 25.0)

    def test_insurance_adjustment_0pct(self):
        vault = make_vault(
            strategies=[make_strategy(sc_risk=5.0, liq_risk=5.0, oracle_risk=5.0, cp_risk=5.0)],
            insurance_coverage_pct=0.0,
        )
        result = self._run([vault])
        vr = result["vaults"]["TestVault"]
        self.assertAlmostEqual(vr["insurance_adjusted_risk"], 50.0)

    def test_insurance_adjustment_100pct(self):
        vault = make_vault(
            strategies=[make_strategy(sc_risk=5.0, liq_risk=5.0, oracle_risk=5.0, cp_risk=5.0)],
            insurance_coverage_pct=100.0,
        )
        result = self._run([vault])
        vr = result["vaults"]["TestVault"]
        self.assertAlmostEqual(vr["insurance_adjusted_risk"], 0.0)

    def test_risk_label_conservative(self):
        vault = make_vault(strategies=[make_strategy(
            sc_risk=0.5, liq_risk=0.5, oracle_risk=0.5, cp_risk=0.5
        )])
        result = self._run([vault])
        self.assertEqual(result["vaults"]["TestVault"]["risk_label"], "CONSERVATIVE")

    def test_risk_label_moderate(self):
        # composite ~30: each component = 3, composite = 3*10 = 30
        vault = make_vault(strategies=[make_strategy(
            sc_risk=3.0, liq_risk=3.0, oracle_risk=3.0, cp_risk=3.0
        )])
        result = self._run([vault])
        self.assertEqual(result["vaults"]["TestVault"]["risk_label"], "MODERATE")

    def test_risk_label_balanced(self):
        # composite = 4.5*10 = 45
        vault = make_vault(strategies=[make_strategy(
            sc_risk=4.5, liq_risk=4.5, oracle_risk=4.5, cp_risk=4.5
        )])
        result = self._run([vault])
        self.assertEqual(result["vaults"]["TestVault"]["risk_label"], "BALANCED")

    def test_risk_label_aggressive(self):
        # composite = 6.0*10 = 60
        vault = make_vault(strategies=[make_strategy(
            sc_risk=6.0, liq_risk=6.0, oracle_risk=6.0, cp_risk=6.0
        )])
        result = self._run([vault])
        self.assertEqual(result["vaults"]["TestVault"]["risk_label"], "AGGRESSIVE")

    def test_risk_label_speculative(self):
        # composite = 8.0*10 = 80
        vault = make_vault(strategies=[make_strategy(
            sc_risk=8.0, liq_risk=8.0, oracle_risk=8.0, cp_risk=8.0
        )])
        result = self._run([vault])
        self.assertEqual(result["vaults"]["TestVault"]["risk_label"], "SPECULATIVE")

    def test_dominant_risk_sc(self):
        vault = make_vault(strategies=[make_strategy(
            sc_risk=9.0, liq_risk=1.0, oracle_risk=1.0, cp_risk=1.0
        )])
        result = self._run([vault])
        self.assertEqual(result["vaults"]["TestVault"]["dominant_risk_type"], "smart_contract")

    def test_dominant_risk_liquidity(self):
        vault = make_vault(strategies=[make_strategy(
            sc_risk=1.0, liq_risk=9.0, oracle_risk=1.0, cp_risk=1.0
        )])
        result = self._run([vault])
        self.assertEqual(result["vaults"]["TestVault"]["dominant_risk_type"], "liquidity")

    def test_dominant_risk_oracle(self):
        vault = make_vault(strategies=[make_strategy(
            sc_risk=1.0, liq_risk=1.0, oracle_risk=9.0, cp_risk=1.0
        )])
        result = self._run([vault])
        self.assertEqual(result["vaults"]["TestVault"]["dominant_risk_type"], "oracle")

    def test_dominant_risk_counterparty(self):
        vault = make_vault(strategies=[make_strategy(
            sc_risk=1.0, liq_risk=1.0, oracle_risk=1.0, cp_risk=9.0
        )])
        result = self._run([vault])
        self.assertEqual(result["vaults"]["TestVault"]["dominant_risk_type"], "counterparty")


class TestDecomposerAggregates(unittest.TestCase):
    """Tests for cross-vault aggregate calculations."""

    def setUp(self):
        self.decomposer = DeFiVaultStrategyRiskDecomposer()
        self.tmpdir = tempfile.mkdtemp()

    def _run(self, vaults, config=None):
        return self.decomposer.decompose(
            vaults, config or {}, data_dir=self.tmpdir, dry_run=True
        )

    def test_safest_vault(self):
        vaults = [
            make_vault(name="Safe", strategies=[make_strategy(
                sc_risk=1.0, liq_risk=1.0, oracle_risk=1.0, cp_risk=1.0
            )]),
            make_vault(name="Risky", strategies=[make_strategy(
                sc_risk=8.0, liq_risk=8.0, oracle_risk=8.0, cp_risk=8.0
            )]),
        ]
        result = self._run(vaults)
        self.assertEqual(result["aggregates"]["safest_vault"], "Safe")

    def test_riskiest_vault(self):
        vaults = [
            make_vault(name="Safe", strategies=[make_strategy(
                sc_risk=1.0, liq_risk=1.0, oracle_risk=1.0, cp_risk=1.0
            )]),
            make_vault(name="Risky", strategies=[make_strategy(
                sc_risk=8.0, liq_risk=8.0, oracle_risk=8.0, cp_risk=8.0
            )]),
        ]
        result = self._run(vaults)
        self.assertEqual(result["aggregates"]["riskiest_vault"], "Risky")

    def test_average_composite_risk_two_vaults(self):
        vaults = [
            make_vault(name="V1", strategies=[make_strategy(
                sc_risk=2.0, liq_risk=2.0, oracle_risk=2.0, cp_risk=2.0
            )]),  # composite=20
            make_vault(name="V2", strategies=[make_strategy(
                sc_risk=4.0, liq_risk=4.0, oracle_risk=4.0, cp_risk=4.0
            )]),  # composite=40
        ]
        result = self._run(vaults)
        self.assertAlmostEqual(result["aggregates"]["average_composite_risk"], 30.0)

    def test_conservative_count(self):
        vaults = [
            make_vault(name="C1", strategies=[make_strategy(
                sc_risk=1.0, liq_risk=1.0, oracle_risk=1.0, cp_risk=1.0
            )]),  # 10 → CONSERVATIVE
            make_vault(name="C2", strategies=[make_strategy(
                sc_risk=1.5, liq_risk=1.5, oracle_risk=1.5, cp_risk=1.5
            )]),  # 15 → CONSERVATIVE
            make_vault(name="A1", strategies=[make_strategy(
                sc_risk=8.0, liq_risk=8.0, oracle_risk=8.0, cp_risk=8.0
            )]),  # 80 → SPECULATIVE
        ]
        result = self._run(vaults)
        self.assertEqual(result["aggregates"]["conservative_count"], 2)

    def test_speculative_count(self):
        vaults = [
            make_vault(name="S1", strategies=[make_strategy(
                sc_risk=9.0, liq_risk=9.0, oracle_risk=9.0, cp_risk=9.0
            )]),  # 90 → SPECULATIVE
            make_vault(name="C1", strategies=[make_strategy(
                sc_risk=1.0, liq_risk=1.0, oracle_risk=1.0, cp_risk=1.0
            )]),  # 10 → CONSERVATIVE
        ]
        result = self._run(vaults)
        self.assertEqual(result["aggregates"]["speculative_count"], 1)

    def test_vault_count(self):
        vaults = [make_vault(name=f"V{i}") for i in range(5)]
        result = self._run(vaults)
        self.assertEqual(result["aggregates"]["vault_count"], 5)

    def test_empty_vaults_aggregates(self):
        result = self._run([])
        agg = result["aggregates"]
        self.assertIsNone(agg["safest_vault"])
        self.assertIsNone(agg["riskiest_vault"])
        self.assertEqual(agg["average_composite_risk"], 0.0)
        self.assertEqual(agg["vault_count"], 0)

    def test_conservative_count_zero(self):
        vaults = [
            make_vault(name="R1", strategies=[make_strategy(
                sc_risk=8.0, liq_risk=8.0, oracle_risk=8.0, cp_risk=8.0
            )]),
        ]
        result = self._run(vaults)
        self.assertEqual(result["aggregates"]["conservative_count"], 0)

    def test_speculative_count_zero(self):
        vaults = [
            make_vault(name="C1", strategies=[make_strategy(
                sc_risk=1.0, liq_risk=1.0, oracle_risk=1.0, cp_risk=1.0
            )]),
        ]
        result = self._run(vaults)
        self.assertEqual(result["aggregates"]["speculative_count"], 0)

    def test_single_vault_safest_equals_riskiest(self):
        result = self._run([make_vault(name="Only")])
        self.assertEqual(result["aggregates"]["safest_vault"], "Only")
        self.assertEqual(result["aggregates"]["riskiest_vault"], "Only")


class TestDecomposerFlagsIntegration(unittest.TestCase):
    """Integration flag tests through decompose()."""

    def setUp(self):
        self.decomposer = DeFiVaultStrategyRiskDecomposer()
        self.tmpdir = tempfile.mkdtemp()

    def _run(self, vaults, config=None):
        return self.decomposer.decompose(
            vaults, config or {}, data_dir=self.tmpdir, dry_run=True
        )

    def test_concentration_flag_via_decompose(self):
        vault = make_vault(strategies=[
            make_strategy(name="Big", allocation_pct=80.0),
            make_strategy(name="Small", allocation_pct=20.0),
        ])
        result = self._run([vault])
        self.assertIn(FLAG_CONCENTRATION_RISK, result["vaults"]["TestVault"]["flags"])

    def test_uninsured_high_risk_flag_via_decompose(self):
        vault = make_vault(
            strategies=[make_strategy(
                sc_risk=8.0, liq_risk=8.0, oracle_risk=8.0, cp_risk=8.0,
                allocation_pct=100.0
            )],
            insurance_coverage_pct=0.0,
        )
        result = self._run([vault])
        self.assertIn(FLAG_UNINSURED_HIGH_RISK, result["vaults"]["TestVault"]["flags"])

    def test_high_oracle_exposure_flag_via_decompose(self):
        vault = make_vault(strategies=[make_strategy(oracle_risk=8.0, allocation_pct=100.0)])
        result = self._run([vault])
        self.assertIn(FLAG_HIGH_ORACLE_EXPOSURE, result["vaults"]["TestVault"]["flags"])

    def test_complex_strategy_flag_via_decompose(self):
        strategies = [
            make_strategy(name=f"S{i}", allocation_pct=100.0/6)
            for i in range(6)
        ]
        vault = make_vault(strategies=strategies)
        result = self._run([vault])
        self.assertIn(FLAG_COMPLEX_STRATEGY, result["vaults"]["TestVault"]["flags"])

    def test_no_flags_clean_vault(self):
        vault = make_vault(
            strategies=[
                make_strategy(name="A", allocation_pct=30.0, oracle_risk=1.0),
                make_strategy(name="B", allocation_pct=30.0, oracle_risk=1.0),
                make_strategy(name="C", allocation_pct=40.0, oracle_risk=1.0),
            ],
            insurance_coverage_pct=50.0,
        )
        result = self._run([vault])
        self.assertEqual(result["vaults"]["TestVault"]["flags"], [])

    def test_flags_only_for_qualifying_vault(self):
        safe_vault = make_vault(
            name="Safe",
            strategies=[
                make_strategy(name="A", sc_risk=1.0, liq_risk=1.0, oracle_risk=1.0,
                              cp_risk=1.0, allocation_pct=40.0),
                make_strategy(name="B", sc_risk=1.0, liq_risk=1.0, oracle_risk=1.0,
                              cp_risk=1.0, allocation_pct=60.0),
            ],
            insurance_coverage_pct=50.0,
        )
        risky_vault = make_vault(
            name="Risky",
            strategies=[make_strategy(
                sc_risk=8.0, liq_risk=8.0, oracle_risk=8.5, cp_risk=8.0,
                allocation_pct=100.0
            )],
            insurance_coverage_pct=0.0,
        )
        result = self._run([safe_vault, risky_vault])
        safe_flags  = result["vaults"]["Safe"]["flags"]
        risky_flags = result["vaults"]["Risky"]["flags"]
        self.assertEqual(safe_flags, [])
        self.assertIn(FLAG_UNINSURED_HIGH_RISK, risky_flags)
        self.assertIn(FLAG_HIGH_ORACLE_EXPOSURE, risky_flags)


class TestDecomposerLogBehavior(unittest.TestCase):
    """Tests for ring-buffer log write behavior."""

    def setUp(self):
        self.decomposer = DeFiVaultStrategyRiskDecomposer()
        self.tmpdir = tempfile.mkdtemp()

    def _log_path(self):
        return os.path.join(self.tmpdir, "vault_risk_decomposition_log.json")

    def _run(self, vaults=None, dry_run=False):
        return self.decomposer.decompose(
            vaults or [make_vault()], {}, data_dir=self.tmpdir, dry_run=dry_run
        )

    def test_log_file_created(self):
        self._run(dry_run=False)
        self.assertTrue(os.path.exists(self._log_path()))

    def test_log_file_contains_list(self):
        self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_count_increases(self):
        self._run(dry_run=False)
        self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_entry_has_timestamp(self):
        self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_vault_count(self):
        self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIn("vault_count", data[0])

    def test_dry_run_no_log_file(self):
        self._run(dry_run=True)
        self.assertFalse(os.path.exists(self._log_path()))

    def test_ring_buffer_cap_100(self):
        for _ in range(110):
            self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_entry_average_composite_risk(self):
        self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIn("average_composite_risk", data[0])

    def test_log_entry_safest_vault(self):
        self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIn("safest_vault", data[0])

    def test_log_entry_riskiest_vault(self):
        self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIn("riskiest_vault", data[0])

    def test_log_entries_accumulate_and_oldest_dropped(self):
        """After 101 writes, oldest entry is dropped (ring buffer)."""
        for i in range(101):
            self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)


class TestDecomposerEdgeCases(unittest.TestCase):
    """Edge case tests."""

    def setUp(self):
        self.decomposer = DeFiVaultStrategyRiskDecomposer()
        self.tmpdir = tempfile.mkdtemp()

    def _run(self, vaults, config=None):
        return self.decomposer.decompose(
            vaults, config or {}, data_dir=self.tmpdir, dry_run=True
        )

    def test_empty_strategies_list(self):
        vault = make_vault(strategies=[])
        result = self._run([vault])
        vr = result["vaults"]["TestVault"]
        self.assertEqual(vr["composite_risk_score"], 0.0)

    def test_strategy_with_zero_allocation(self):
        vault = make_vault(strategies=[
            make_strategy(name="A", allocation_pct=0.0, sc_risk=10.0)
        ])
        result = self._run([vault])
        # Zero allocation → weighted risk = 0
        self.assertEqual(result["vaults"]["TestVault"]["composite_risk_score"], 0.0)

    def test_two_vaults_different_protocols(self):
        vaults = [
            make_vault(name="VaultA", protocol="Aave"),
            make_vault(name="VaultB", protocol="Compound"),
        ]
        result = self._run(vaults)
        self.assertIn("VaultA", result["vaults"])
        self.assertIn("VaultB", result["vaults"])

    def test_weighted_risk_50_50_split_accuracy(self):
        vault = make_vault(strategies=[
            make_strategy(name="A", allocation_pct=50.0, sc_risk=0.0, liq_risk=0.0, oracle_risk=0.0, cp_risk=0.0),
            make_strategy(name="B", allocation_pct=50.0, sc_risk=10.0, liq_risk=10.0, oracle_risk=10.0, cp_risk=10.0),
        ])
        result = self._run([vault])
        self.assertAlmostEqual(result["vaults"]["TestVault"]["composite_risk_score"], 50.0)

    def test_many_strategies_equal_alloc(self):
        n = 10
        strategies = [make_strategy(name=f"S{i}", allocation_pct=10.0) for i in range(n)]
        vault = make_vault(strategies=strategies)
        result = self._run([vault])
        # All strategies same risk, so weighted = same
        vr = result["vaults"]["TestVault"]
        self.assertAlmostEqual(vr["composite_risk_score"], 50.0)

    def test_flags_list_is_list_type(self):
        result = self._run([make_vault()])
        self.assertIsInstance(result["vaults"]["TestVault"]["flags"], list)

    def test_multiple_vaults_count_matches(self):
        vaults = [make_vault(name=f"V{i}") for i in range(3)]
        result = self._run(vaults)
        self.assertEqual(len(result["vaults"]), 3)

    def test_insurance_reduces_adjusted_risk(self):
        vault = make_vault(
            strategies=[make_strategy(sc_risk=8.0, liq_risk=8.0, oracle_risk=8.0, cp_risk=8.0)],
            insurance_coverage_pct=25.0,
        )
        result = self._run([vault])
        vr = result["vaults"]["TestVault"]
        self.assertLess(vr["insurance_adjusted_risk"], vr["composite_risk_score"])

    def test_config_empty_dict_uses_defaults(self):
        # Should not raise
        result = self._run([make_vault()], config={})
        self.assertIn("vaults", result)

    def test_composite_score_is_float(self):
        result = self._run([make_vault()])
        score = result["vaults"]["TestVault"]["composite_risk_score"]
        self.assertIsInstance(score, float)

    def test_risk_label_is_string(self):
        result = self._run([make_vault()])
        label = result["vaults"]["TestVault"]["risk_label"]
        self.assertIsInstance(label, str)

    def test_dominant_risk_type_is_string(self):
        result = self._run([make_vault()])
        dom = result["vaults"]["TestVault"]["dominant_risk_type"]
        self.assertIsInstance(dom, str)

    def test_result_is_dict(self):
        result = self._run([make_vault()])
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
