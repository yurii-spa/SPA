"""
Tests for MP-669: FlashLoanRiskAnalyzer
≥60 test cases using unittest only (no pytest, no numpy, no pandas).
"""

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.flash_loan_risk_analyzer import (
    MAX_ENTRIES,
    FlashLoanRisk,
    FlashLoanRiskAnalyzer,
    ProtocolFlashLoanProfile,
)


def _amm(
    protocol_id="amm_test",
    tvl_usd=10_000_000.0,
    uses_spot_price_oracle=False,
    has_time_weighted_oracle=True,
    governance_token_pct_in_amm=0.0,
    min_block_delay=0,
    flash_loan_available=True,
) -> ProtocolFlashLoanProfile:
    return ProtocolFlashLoanProfile(
        protocol_id=protocol_id,
        protocol_type="AMM",
        tvl_usd=tvl_usd,
        uses_spot_price_oracle=uses_spot_price_oracle,
        has_time_weighted_oracle=has_time_weighted_oracle,
        governance_token_pct_in_amm=governance_token_pct_in_amm,
        min_block_delay=min_block_delay,
        flash_loan_available=flash_loan_available,
    )


def _lending(**kwargs) -> ProtocolFlashLoanProfile:
    defaults = dict(
        protocol_id="lending_test",
        protocol_type="LENDING",
        tvl_usd=500_000_000.0,
        uses_spot_price_oracle=False,
        has_time_weighted_oracle=True,
        governance_token_pct_in_amm=0.0,
        min_block_delay=0,
        flash_loan_available=True,
    )
    defaults.update(kwargs)
    return ProtocolFlashLoanProfile(**defaults)


def _governance(**kwargs) -> ProtocolFlashLoanProfile:
    defaults = dict(
        protocol_id="gov_test",
        protocol_type="GOVERNANCE",
        tvl_usd=50_000_000.0,
        uses_spot_price_oracle=False,
        has_time_weighted_oracle=False,
        governance_token_pct_in_amm=0.3,
        min_block_delay=0,
        flash_loan_available=True,
    )
    defaults.update(kwargs)
    return ProtocolFlashLoanProfile(**defaults)


class TestPriceManipRisk(unittest.TestCase):
    def setUp(self):
        self.az = FlashLoanRiskAnalyzer()

    def test_non_amm_lending_returns_005(self):
        self.assertAlmostEqual(self.az._price_manip_risk(_lending()), 0.05)

    def test_non_amm_governance_returns_005(self):
        self.assertAlmostEqual(self.az._price_manip_risk(_governance()), 0.05)

    def test_non_amm_yield_returns_005(self):
        p = _lending(protocol_type="YIELD")
        self.assertAlmostEqual(self.az._price_manip_risk(p), 0.05)

    def test_amm_small_tvl_higher_risk(self):
        risk = self.az._price_manip_risk(_amm(tvl_usd=1_000_000))
        self.assertGreater(risk, 0.2)

    def test_amm_100m_tvl_equals_base(self):
        # tvl_factor = max(0.0, 1.0 - 100M/100M) = 0.0 → risk = 0.2
        risk = self.az._price_manip_risk(_amm(tvl_usd=100_000_000))
        self.assertAlmostEqual(risk, 0.2)

    def test_amm_above_100m_clamped_to_base(self):
        risk = self.az._price_manip_risk(_amm(tvl_usd=200_000_000))
        self.assertAlmostEqual(risk, 0.2)

    def test_amm_zero_tvl_near_max(self):
        risk = self.az._price_manip_risk(_amm(tvl_usd=0))
        self.assertAlmostEqual(risk, min(1.0, 0.2 + 0.5 * 1.0), places=4)

    def test_amm_risk_capped_at_1(self):
        risk = self.az._price_manip_risk(_amm(tvl_usd=0))
        self.assertLessEqual(risk, 1.0)

    def test_larger_tvl_lower_risk(self):
        small = self.az._price_manip_risk(_amm(tvl_usd=5_000_000))
        large = self.az._price_manip_risk(_amm(tvl_usd=80_000_000))
        self.assertGreater(small, large)


class TestOracleRisk(unittest.TestCase):
    def setUp(self):
        self.az = FlashLoanRiskAnalyzer()

    def test_no_spot_oracle_returns_005(self):
        p = _amm(uses_spot_price_oracle=False)
        self.assertAlmostEqual(self.az._oracle_risk(p), 0.05)

    def test_twap_oracle_returns_010(self):
        p = _amm(uses_spot_price_oracle=True, has_time_weighted_oracle=True)
        self.assertAlmostEqual(self.az._oracle_risk(p), 0.10)

    def test_spot_oracle_no_twap_small_tvl_high_risk(self):
        p = _amm(
            uses_spot_price_oracle=True,
            has_time_weighted_oracle=False,
            tvl_usd=1_000_000,
        )
        risk = self.az._oracle_risk(p)
        self.assertGreater(risk, 0.6)

    def test_spot_oracle_500m_tvl_equals_base(self):
        # tvl_factor = max(0, 1 - 500M/500M) = 0 → risk = 0.6
        p = _amm(
            uses_spot_price_oracle=True,
            has_time_weighted_oracle=False,
            tvl_usd=500_000_000,
        )
        self.assertAlmostEqual(self.az._oracle_risk(p), 0.6)

    def test_spot_oracle_risk_capped_at_1(self):
        p = _amm(
            uses_spot_price_oracle=True, has_time_weighted_oracle=False, tvl_usd=0
        )
        self.assertLessEqual(self.az._oracle_risk(p), 1.0)

    def test_spot_oracle_higher_tvl_lower_risk(self):
        low_tvl = self.az._oracle_risk(
            _amm(uses_spot_price_oracle=True, has_time_weighted_oracle=False, tvl_usd=1_000_000)
        )
        high_tvl = self.az._oracle_risk(
            _amm(uses_spot_price_oracle=True, has_time_weighted_oracle=False, tvl_usd=400_000_000)
        )
        self.assertGreater(low_tvl, high_tvl)


class TestGovernanceRisk(unittest.TestCase):
    def setUp(self):
        self.az = FlashLoanRiskAnalyzer()

    def test_non_governance_amm_returns_002(self):
        self.assertAlmostEqual(self.az._governance_risk(_amm()), 0.02)

    def test_non_governance_lending_returns_002(self):
        self.assertAlmostEqual(self.az._governance_risk(_lending()), 0.02)

    def test_governance_delay_100_returns_005(self):
        p = _governance(min_block_delay=100)
        self.assertAlmostEqual(self.az._governance_risk(p), 0.05)

    def test_governance_delay_above_100_returns_005(self):
        p = _governance(min_block_delay=500)
        self.assertAlmostEqual(self.az._governance_risk(p), 0.05)

    def test_governance_delay_0_higher_risk(self):
        p = _governance(min_block_delay=0, governance_token_pct_in_amm=0.5)
        risk = self.az._governance_risk(p)
        self.assertGreater(risk, 0.4)

    def test_governance_zero_delay_adds_04(self):
        p = _governance(min_block_delay=0, governance_token_pct_in_amm=0.0)
        # base = 0.3*0 + 0.4 = 0.4
        self.assertAlmostEqual(self.az._governance_risk(p), 0.4)

    def test_governance_high_token_pct_higher_risk(self):
        low = self.az._governance_risk(_governance(governance_token_pct_in_amm=0.1, min_block_delay=50))
        high = self.az._governance_risk(_governance(governance_token_pct_in_amm=0.9, min_block_delay=50))
        self.assertGreater(high, low)

    def test_governance_risk_capped_at_1(self):
        p = _governance(min_block_delay=0, governance_token_pct_in_amm=10.0)
        self.assertLessEqual(self.az._governance_risk(p), 1.0)


class TestComposite(unittest.TestCase):
    def setUp(self):
        self.az = FlashLoanRiskAnalyzer()

    def test_zero_inputs(self):
        self.assertAlmostEqual(self.az._composite(0.0, 0.0, 0.0), 0.0)

    def test_weights_sum_to_1(self):
        # pm=1, ora=1, gov=1 → composite = 1*0.35 + 1*0.40 + 1*0.25 = 1.0
        self.assertAlmostEqual(self.az._composite(1.0, 1.0, 1.0), 1.0)

    def test_price_manip_weight(self):
        self.assertAlmostEqual(self.az._composite(1.0, 0.0, 0.0), 0.35)

    def test_oracle_weight(self):
        self.assertAlmostEqual(self.az._composite(0.0, 1.0, 0.0), 0.40)

    def test_governance_weight(self):
        self.assertAlmostEqual(self.az._composite(0.0, 0.0, 1.0), 0.25)

    def test_composite_formula(self):
        pm, ora, gov = 0.6, 0.8, 0.4
        expected = round(pm * 0.35 + ora * 0.40 + gov * 0.25, 4)
        self.assertAlmostEqual(self.az._composite(pm, ora, gov), expected)


class TestRiskTier(unittest.TestCase):
    def setUp(self):
        self.az = FlashLoanRiskAnalyzer()

    def test_below_010_negligible(self):
        self.assertEqual(self.az._risk_tier(0.05), "NEGLIGIBLE")

    def test_exactly_010_low(self):
        self.assertEqual(self.az._risk_tier(0.10), "LOW")

    def test_between_010_025_low(self):
        self.assertEqual(self.az._risk_tier(0.15), "LOW")

    def test_exactly_025_medium(self):
        self.assertEqual(self.az._risk_tier(0.25), "MEDIUM")

    def test_between_025_045_medium(self):
        self.assertEqual(self.az._risk_tier(0.35), "MEDIUM")

    def test_exactly_045_high(self):
        self.assertEqual(self.az._risk_tier(0.45), "HIGH")

    def test_between_045_070_high(self):
        self.assertEqual(self.az._risk_tier(0.60), "HIGH")

    def test_exactly_070_critical(self):
        self.assertEqual(self.az._risk_tier(0.70), "CRITICAL")

    def test_above_070_critical(self):
        self.assertEqual(self.az._risk_tier(0.95), "CRITICAL")

    def test_zero_negligible(self):
        self.assertEqual(self.az._risk_tier(0.0), "NEGLIGIBLE")


class TestAttackVectors(unittest.TestCase):
    def setUp(self):
        self.az = FlashLoanRiskAnalyzer()

    def test_no_vectors_when_all_low(self):
        p = _amm()
        vectors = self.az._attack_vectors(p, pm=0.1, ora=0.1, gov=0.1)
        self.assertEqual(vectors, [])

    def test_price_manip_vector_when_pm_above_03(self):
        p = _amm()
        vectors = self.az._attack_vectors(p, pm=0.4, ora=0.1, gov=0.1)
        self.assertIn("PRICE_MANIPULATION", vectors)

    def test_oracle_vector_when_ora_above_03(self):
        p = _amm()
        vectors = self.az._attack_vectors(p, pm=0.1, ora=0.4, gov=0.1)
        self.assertIn("ORACLE_ATTACK", vectors)

    def test_governance_vector_when_gov_above_03(self):
        p = _governance()
        vectors = self.az._attack_vectors(p, pm=0.1, ora=0.1, gov=0.5)
        self.assertIn("GOVERNANCE_ATTACK", vectors)

    def test_multiple_vectors_possible(self):
        p = _amm()
        vectors = self.az._attack_vectors(p, pm=0.5, ora=0.5, gov=0.5)
        self.assertIn("PRICE_MANIPULATION", vectors)
        self.assertIn("ORACLE_ATTACK", vectors)
        self.assertIn("GOVERNANCE_ATTACK", vectors)

    def test_boundary_exactly_03_not_included(self):
        # >0.3 triggers, =0.3 does not
        p = _amm()
        vectors = self.az._attack_vectors(p, pm=0.3, ora=0.3, gov=0.3)
        self.assertEqual(vectors, [])


class TestMitigations(unittest.TestCase):
    def setUp(self):
        self.az = FlashLoanRiskAnalyzer()

    def test_twap_mitigation_listed(self):
        p = _amm(has_time_weighted_oracle=True)
        mits = self.az._mitigations(p)
        self.assertTrue(any("TWAP" in m for m in mits))

    def test_block_delay_mitigation_listed(self):
        p = _governance(min_block_delay=200)
        mits = self.az._mitigations(p)
        self.assertTrue(any("200" in m for m in mits))

    def test_high_tvl_mitigation_listed(self):
        p = _amm(tvl_usd=200_000_000)
        mits = self.az._mitigations(p)
        self.assertTrue(any("TVL" in m or "tvl" in m.lower() for m in mits))

    def test_no_flash_loan_mitigation_listed(self):
        p = _amm(flash_loan_available=False)
        mits = self.az._mitigations(p)
        self.assertTrue(any("Flash loans not available" in m for m in mits))

    def test_no_mitigations_fallback(self):
        p = ProtocolFlashLoanProfile(
            protocol_id="bare",
            protocol_type="GOVERNANCE",
            tvl_usd=1_000_000,
            uses_spot_price_oracle=True,
            has_time_weighted_oracle=False,
            governance_token_pct_in_amm=0.5,
            min_block_delay=0,
            flash_loan_available=True,
        )
        mits = self.az._mitigations(p)
        self.assertTrue(any("No significant" in m for m in mits))


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.az = FlashLoanRiskAnalyzer()

    def test_returns_flash_loan_risk(self):
        result = self.az.analyze(_amm())
        self.assertIsInstance(result, FlashLoanRisk)

    def test_amm_spot_oracle_no_twap_small_tvl_high_or_critical(self):
        p = _amm(
            tvl_usd=500_000,
            uses_spot_price_oracle=True,
            has_time_weighted_oracle=False,
        )
        result = self.az.analyze(p)
        self.assertIn(result.risk_tier, ("HIGH", "CRITICAL"))

    def test_lending_twap_large_tvl_low_or_negligible(self):
        p = _lending(
            uses_spot_price_oracle=False,
            has_time_weighted_oracle=True,
            tvl_usd=1_000_000_000,
        )
        result = self.az.analyze(p)
        self.assertIn(result.risk_tier, ("NEGLIGIBLE", "LOW"))

    def test_governance_zero_delay_governance_attack_vector(self):
        p = _governance(min_block_delay=0, governance_token_pct_in_amm=0.8)
        result = self.az.analyze(p)
        self.assertIn("GOVERNANCE_ATTACK", result.attack_vectors)

    def test_governance_200_block_delay_low_governance_risk(self):
        p = _governance(min_block_delay=200)
        result = self.az.analyze(p)
        self.assertAlmostEqual(result.governance_attack_risk, 0.05)

    def test_protocol_id_preserved(self):
        p = _amm(protocol_id="my_amm")
        result = self.az.analyze(p)
        self.assertEqual(result.protocol_id, "my_amm")

    def test_protocol_type_preserved(self):
        result = self.az.analyze(_amm())
        self.assertEqual(result.protocol_type, "AMM")

    def test_advisory_contains_tier_keyword(self):
        result = self.az.analyze(
            _amm(tvl_usd=500_000, uses_spot_price_oracle=True, has_time_weighted_oracle=False)
        )
        self.assertIn(result.risk_tier, result.advisory.upper() or result.advisory)

    def test_composite_between_0_and_1(self):
        result = self.az.analyze(_amm())
        self.assertGreaterEqual(result.composite_risk, 0.0)
        self.assertLessEqual(result.composite_risk, 1.0)

    def test_mitigations_is_list(self):
        result = self.az.analyze(_amm())
        self.assertIsInstance(result.mitigations, list)

    def test_attack_vectors_is_list(self):
        result = self.az.analyze(_amm())
        self.assertIsInstance(result.attack_vectors, list)


class TestAnalyzeBatch(unittest.TestCase):
    def setUp(self):
        self.az = FlashLoanRiskAnalyzer()

    def test_empty_batch_returns_empty(self):
        self.assertEqual(self.az.analyze_batch([]), [])

    def test_batch_length_matches(self):
        results = self.az.analyze_batch([_amm(), _lending(), _governance()])
        self.assertEqual(len(results), 3)

    def test_batch_types_correct(self):
        results = self.az.analyze_batch([_amm(), _lending()])
        self.assertEqual(results[0].protocol_type, "AMM")
        self.assertEqual(results[1].protocol_type, "LENDING")


class TestCriticalProtocols(unittest.TestCase):
    def setUp(self):
        self.az = FlashLoanRiskAnalyzer()

    def test_filters_high_and_critical(self):
        results = self.az.analyze_batch([
            _amm(tvl_usd=100_000, uses_spot_price_oracle=True, has_time_weighted_oracle=False),
            _lending(tvl_usd=2_000_000_000),
        ])
        critical = self.az.critical_protocols(results)
        for r in critical:
            self.assertIn(r.risk_tier, ("HIGH", "CRITICAL"))

    def test_empty_input_returns_empty(self):
        self.assertEqual(self.az.critical_protocols([]), [])

    def test_low_risk_excluded(self):
        p = _lending(tvl_usd=2_000_000_000, has_time_weighted_oracle=True)
        result = self.az.analyze(p)
        critical = self.az.critical_protocols([result])
        for r in critical:
            self.assertIn(r.risk_tier, ("HIGH", "CRITICAL"))


class TestSaveLoadResults(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "data" / "flash_loan_risk_log.json"
        self.az = FlashLoanRiskAnalyzer(data_file=self.data_file)

    def _make_result(self, tier="HIGH", vectors=None) -> FlashLoanRisk:
        return FlashLoanRisk(
            protocol_id="test_proto",
            protocol_type="AMM",
            price_manipulation_risk=0.5,
            oracle_attack_risk=0.7,
            governance_attack_risk=0.1,
            composite_risk=0.5,
            risk_tier=tier,
            attack_vectors=vectors or ["ORACLE_ATTACK"],
            mitigations=["TWAP oracle"],
            advisory="Test advisory",
        )

    def test_save_creates_file(self):
        self.az.save_results([self._make_result()])
        self.assertTrue(self.data_file.exists())

    def test_save_atomic_no_tmp_leftover(self):
        self.az.save_results([self._make_result()])
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_save_valid_json(self):
        self.az.save_results([self._make_result()])
        data = json.loads(self.data_file.read_text())
        self.assertIsInstance(data, list)

    def test_save_contains_timestamp(self):
        self.az.save_results([self._make_result()])
        data = json.loads(self.data_file.read_text())
        self.assertIn("timestamp", data[0])

    def test_save_contains_protocol_id(self):
        self.az.save_results([self._make_result()])
        data = json.loads(self.data_file.read_text())
        self.assertEqual(data[0]["protocol_id"], "test_proto")

    def test_save_contains_attack_vectors(self):
        self.az.save_results([self._make_result(vectors=["PRICE_MANIPULATION"])])
        data = json.loads(self.data_file.read_text())
        self.assertIn("PRICE_MANIPULATION", data[0]["attack_vectors"])

    def test_ring_buffer_max_entries(self):
        for _ in range(MAX_ENTRIES + 15):
            self.az.save_results([self._make_result()])
        data = json.loads(self.data_file.read_text())
        self.assertLessEqual(len(data), MAX_ENTRIES)

    def test_load_history_missing_file_returns_empty(self):
        self.assertEqual(self.az.load_history(), [])

    def test_load_history_after_save(self):
        self.az.save_results([self._make_result()])
        history = self.az.load_history()
        self.assertIsInstance(history, list)
        self.assertEqual(len(history), 1)

    def test_load_history_corrupted_returns_empty(self):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.data_file.write_text("{corrupt}")
        self.assertEqual(self.az.load_history(), [])


if __name__ == "__main__":
    unittest.main()
