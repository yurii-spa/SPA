"""
Tests for MP-1008: DeFiProtocolFlashLoanRiskAssessor
Run: python3 -m unittest spa_core.tests.test_defi_protocol_flash_loan_risk_assessor -v
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_protocol_flash_loan_risk_assessor import (
    DeFiProtocolFlashLoanRiskAssessor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_protocol(**kwargs) -> dict:
    """Return a safe baseline protocol overridden by kwargs."""
    base = {
        "name": "SafeLend",
        "category": "lending",
        "flash_loan_available": False,
        "flash_loan_fee_bps": 0,
        "total_flash_loan_volume_30d_usd": 0,
        "historical_flash_loan_attacks": 0,
        "amount_lost_to_flash_loans_usd": 0,
        "oracle_type": "chainlink_twap",
        "twap_period_minutes": 30,
        "single_block_price_manipulation_possible": False,
        "reentrancy_guard": True,
        "governance_attack_via_flash_loan_possible": False,
        "max_single_flash_loan_as_pct_tvl": 5,
        "tvl_usd": 100_000_000,
        "total_protocol_fees_30d_usd": 500_000,
    }
    base.update(kwargs)
    return base


def _risky_protocol(**kwargs) -> dict:
    """Return a high-risk baseline protocol."""
    base = {
        "name": "RiskyDex",
        "category": "dex",
        "flash_loan_available": True,
        "flash_loan_fee_bps": 3,
        "total_flash_loan_volume_30d_usd": 50_000_000,
        "historical_flash_loan_attacks": 2,
        "amount_lost_to_flash_loans_usd": 5_000_000,
        "oracle_type": "uniswap_spot",
        "twap_period_minutes": 0,
        "single_block_price_manipulation_possible": True,
        "reentrancy_guard": False,
        "governance_attack_via_flash_loan_possible": True,
        "max_single_flash_loan_as_pct_tvl": 80,
        "tvl_usd": 10_000_000,
        "total_protocol_fees_30d_usd": 100_000,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

class TestBasicInstantiation(unittest.TestCase):
    def test_instantiation(self):
        a = DeFiProtocolFlashLoanRiskAssessor()
        self.assertIsNotNone(a)

    def test_assess_returns_dict(self):
        a = DeFiProtocolFlashLoanRiskAssessor()
        result = a.assess([_safe_protocol()], {})
        self.assertIsInstance(result, dict)

    def test_result_has_protocols_key(self):
        a = DeFiProtocolFlashLoanRiskAssessor()
        result = a.assess([_safe_protocol()], {})
        self.assertIn("protocols", result)

    def test_result_has_aggregates_key(self):
        a = DeFiProtocolFlashLoanRiskAssessor()
        result = a.assess([_safe_protocol()], {})
        self.assertIn("aggregates", result)

    def test_protocols_list_length(self):
        a = DeFiProtocolFlashLoanRiskAssessor()
        result = a.assess([_safe_protocol(), _risky_protocol()], {})
        self.assertEqual(len(result["protocols"]), 2)

    def test_empty_protocols(self):
        a = DeFiProtocolFlashLoanRiskAssessor()
        result = a.assess([], {})
        self.assertEqual(result["protocols"], [])
        self.assertEqual(result["aggregates"]["total_protocols"], 0)

    def test_type_error_protocols(self):
        a = DeFiProtocolFlashLoanRiskAssessor()
        with self.assertRaises(TypeError):
            a.assess("not-a-list", {})

    def test_type_error_config(self):
        a = DeFiProtocolFlashLoanRiskAssessor()
        with self.assertRaises(TypeError):
            a.assess([], "not-a-dict")


class TestSafeProtocol(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_safe_protocol_label(self):
        result = self.a.assess([_safe_protocol()], {})
        label = result["protocols"][0]["risk_label"]
        self.assertIn(label, ("FLASH_LOAN_SAFE", "LOW_RISK"))

    def test_safe_attack_surface_low(self):
        result = self.a.assess([_safe_protocol()], {})
        score = result["protocols"][0]["attack_surface_score"]
        self.assertLess(score, 30)

    def test_safe_historical_loss_ratio_zero(self):
        result = self.a.assess([_safe_protocol()], {})
        self.assertEqual(result["protocols"][0]["historical_loss_ratio"], 0.0)

    def test_safe_composite_score_low(self):
        result = self.a.assess([_safe_protocol()], {})
        self.assertLess(result["protocols"][0]["composite_risk_score"], 40)

    def test_reentrancy_flag_present_when_protected(self):
        result = self.a.assess([_safe_protocol()], {})
        self.assertIn("REENTRANCY_PROTECTED", result["protocols"][0]["flags"])

    def test_spot_oracle_flag_absent_for_safe(self):
        result = self.a.assess([_safe_protocol()], {})
        self.assertNotIn("SPOT_ORACLE_EXPOSED", result["protocols"][0]["flags"])

    def test_gov_attack_flag_absent(self):
        result = self.a.assess([_safe_protocol()], {})
        self.assertNotIn("GOVERNANCE_ATTACK_VECTOR", result["protocols"][0]["flags"])

    def test_fl_provider_flag_absent_when_not_providing(self):
        result = self.a.assess([_safe_protocol(flash_loan_available=False)], {})
        self.assertNotIn("FLASH_LOAN_PROVIDER", result["protocols"][0]["flags"])


class TestRiskyProtocol(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_risky_label_high_or_critical(self):
        result = self.a.assess([_risky_protocol()], {})
        label = result["protocols"][0]["risk_label"]
        self.assertIn(label, ("HIGH_RISK", "CRITICAL"))

    def test_risky_attack_surface_high(self):
        result = self.a.assess([_risky_protocol()], {})
        self.assertGreater(result["protocols"][0]["attack_surface_score"], 60)

    def test_historical_loss_ratio_positive(self):
        result = self.a.assess([_risky_protocol()], {})
        self.assertGreater(result["protocols"][0]["historical_loss_ratio"], 0)

    def test_spot_oracle_flag_present(self):
        result = self.a.assess([_risky_protocol()], {})
        self.assertIn("SPOT_ORACLE_EXPOSED", result["protocols"][0]["flags"])

    def test_governance_attack_flag_present(self):
        result = self.a.assess([_risky_protocol()], {})
        self.assertIn("GOVERNANCE_ATTACK_VECTOR", result["protocols"][0]["flags"])

    def test_fl_provider_flag_present(self):
        result = self.a.assess([_risky_protocol()], {})
        self.assertIn("FLASH_LOAN_PROVIDER", result["protocols"][0]["flags"])

    def test_historical_exploit_flag_present(self):
        result = self.a.assess([_risky_protocol()], {})
        self.assertIn("HISTORICAL_EXPLOIT", result["protocols"][0]["flags"])

    def test_no_reentrancy_guard_increases_surface(self):
        safe_with_guard = self.a.assess([_safe_protocol(reentrancy_guard=True)], {})
        safe_without = self.a.assess([_safe_protocol(reentrancy_guard=False)], {})
        self.assertGreater(
            safe_without["protocols"][0]["attack_surface_score"],
            safe_with_guard["protocols"][0]["attack_surface_score"],
        )


class TestCriticalLabel(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_critical_requires_all_three(self):
        p = _risky_protocol(
            historical_flash_loan_attacks=1,
            oracle_type="uniswap_spot",
            governance_attack_via_flash_loan_possible=True,
        )
        result = self.a.assess([p], {})
        self.assertEqual(result["protocols"][0]["risk_label"], "CRITICAL")

    def test_no_critical_without_gov_attack(self):
        p = _risky_protocol(
            historical_flash_loan_attacks=1,
            oracle_type="uniswap_spot",
            governance_attack_via_flash_loan_possible=False,
        )
        result = self.a.assess([p], {})
        self.assertNotEqual(result["protocols"][0]["risk_label"], "CRITICAL")

    def test_no_critical_without_spot_oracle(self):
        p = _risky_protocol(
            historical_flash_loan_attacks=1,
            oracle_type="chainlink_twap",
            twap_period_minutes=30,
            governance_attack_via_flash_loan_possible=True,
        )
        result = self.a.assess([p], {})
        self.assertNotEqual(result["protocols"][0]["risk_label"], "CRITICAL")

    def test_no_critical_without_history(self):
        p = _risky_protocol(
            historical_flash_loan_attacks=0,
            oracle_type="uniswap_spot",
            governance_attack_via_flash_loan_possible=True,
        )
        result = self.a.assess([p], {})
        self.assertNotEqual(result["protocols"][0]["risk_label"], "CRITICAL")


class TestHighRiskLabel(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_two_historical_attacks_gives_high(self):
        p = _safe_protocol(
            historical_flash_loan_attacks=2,
            amount_lost_to_flash_loans_usd=1_000,
        )
        result = self.a.assess([p], {})
        label = result["protocols"][0]["risk_label"]
        self.assertIn(label, ("HIGH_RISK", "CRITICAL"))

    def test_attack_surface_above_60_gives_high(self):
        # spot oracle (40) + governance (30) = 70 → HIGH
        p = _safe_protocol(
            oracle_type="uniswap_spot",
            governance_attack_via_flash_loan_possible=True,
        )
        result = self.a.assess([p], {})
        label = result["protocols"][0]["risk_label"]
        self.assertIn(label, ("HIGH_RISK", "CRITICAL"))


class TestAttackSurfaceScore(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_spot_oracle_adds_40(self):
        p_twap = _safe_protocol(oracle_type="chainlink_twap", twap_period_minutes=30)
        p_spot = _safe_protocol(oracle_type="uniswap_spot")
        r1 = self.a.assess([p_twap], {})["protocols"][0]["attack_surface_score"]
        r2 = self.a.assess([p_spot], {})["protocols"][0]["attack_surface_score"]
        self.assertGreaterEqual(r2 - r1, 35)  # ~40

    def test_gov_attack_adds_30(self):
        p_no = _safe_protocol(governance_attack_via_flash_loan_possible=False)
        p_yes = _safe_protocol(governance_attack_via_flash_loan_possible=True)
        r1 = self.a.assess([p_no], {})["protocols"][0]["attack_surface_score"]
        r2 = self.a.assess([p_yes], {})["protocols"][0]["attack_surface_score"]
        self.assertGreaterEqual(r2 - r1, 25)

    def test_no_reentrancy_adds_20(self):
        p_guard = _safe_protocol(reentrancy_guard=True)
        p_no = _safe_protocol(reentrancy_guard=False)
        r1 = self.a.assess([p_guard], {})["protocols"][0]["attack_surface_score"]
        r2 = self.a.assess([p_no], {})["protocols"][0]["attack_surface_score"]
        self.assertGreaterEqual(r2 - r1, 15)

    def test_high_loan_pct_adds_score(self):
        p_low = _safe_protocol(max_single_flash_loan_as_pct_tvl=5)
        p_high = _safe_protocol(max_single_flash_loan_as_pct_tvl=80)
        r1 = self.a.assess([p_low], {})["protocols"][0]["attack_surface_score"]
        r2 = self.a.assess([p_high], {})["protocols"][0]["attack_surface_score"]
        self.assertGreaterEqual(r2, r1)

    def test_score_capped_at_100(self):
        result = self.a.assess([_risky_protocol()], {})
        self.assertLessEqual(result["protocols"][0]["attack_surface_score"], 100)

    def test_score_non_negative(self):
        result = self.a.assess([_safe_protocol()], {})
        self.assertGreaterEqual(result["protocols"][0]["attack_surface_score"], 0)


class TestFeeDeterrentScore(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_zero_fee_zero_deterrent(self):
        p = _safe_protocol(flash_loan_fee_bps=0)
        result = self.a.assess([p], {})
        self.assertEqual(result["protocols"][0]["fee_deterrent_score"], 0.0)

    def test_high_fee_partial_deterrent(self):
        p = _safe_protocol(flash_loan_fee_bps=50)
        result = self.a.assess([p], {})
        self.assertGreater(result["protocols"][0]["fee_deterrent_score"], 0)

    def test_very_high_fee_highest_deterrent(self):
        p1 = _safe_protocol(flash_loan_fee_bps=50)
        p2 = _safe_protocol(flash_loan_fee_bps=5)
        r1 = self.a.assess([p1], {})["protocols"][0]["fee_deterrent_score"]
        r2 = self.a.assess([p2], {})["protocols"][0]["fee_deterrent_score"]
        self.assertGreater(r1, r2)

    def test_mid_fee_mid_deterrent(self):
        p = _safe_protocol(flash_loan_fee_bps=20)
        result = self.a.assess([p], {})
        score = result["protocols"][0]["fee_deterrent_score"]
        self.assertGreater(score, 0)
        self.assertLess(score, 60)


class TestFlashLoanRevenuePct(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_no_flash_loan_zero_revenue_pct(self):
        p = _safe_protocol(flash_loan_available=False, total_flash_loan_volume_30d_usd=0)
        result = self.a.assess([p], {})
        self.assertEqual(result["protocols"][0]["flash_loan_revenue_pct"], 0.0)

    def test_high_revenue_flag_triggered(self):
        p = _safe_protocol(
            flash_loan_available=True,
            flash_loan_fee_bps=30,
            total_flash_loan_volume_30d_usd=10_000_000,
            total_protocol_fees_30d_usd=20_000,  # fl_fee_revenue = 30k > 30% of 20k
        )
        result = self.a.assess([p], {})
        self.assertIn("HIGH_REVENUE_DEPENDENCY", result["protocols"][0]["flags"])

    def test_low_revenue_flag_not_triggered(self):
        p = _safe_protocol(
            flash_loan_available=True,
            flash_loan_fee_bps=9,
            total_flash_loan_volume_30d_usd=100_000,
            total_protocol_fees_30d_usd=10_000_000,
        )
        result = self.a.assess([p], {})
        self.assertNotIn("HIGH_REVENUE_DEPENDENCY", result["protocols"][0]["flags"])

    def test_zero_total_fees_no_crash(self):
        p = _safe_protocol(total_protocol_fees_30d_usd=0)
        result = self.a.assess([p], {})
        self.assertGreaterEqual(result["protocols"][0]["flash_loan_revenue_pct"], 0.0)


class TestHistoricalLossRatio(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_no_loss_ratio_zero(self):
        p = _safe_protocol(amount_lost_to_flash_loans_usd=0, tvl_usd=100_000_000)
        result = self.a.assess([p], {})
        self.assertEqual(result["protocols"][0]["historical_loss_ratio"], 0.0)

    def test_partial_loss(self):
        p = _safe_protocol(amount_lost_to_flash_loans_usd=10_000_000, tvl_usd=100_000_000)
        result = self.a.assess([p], {})
        ratio = result["protocols"][0]["historical_loss_ratio"]
        self.assertAlmostEqual(ratio, 10.0, places=2)

    def test_loss_capped_at_100(self):
        p = _safe_protocol(amount_lost_to_flash_loans_usd=999_999_999, tvl_usd=1)
        result = self.a.assess([p], {})
        self.assertLessEqual(result["protocols"][0]["historical_loss_ratio"], 100.0)


class TestCompositeRiskScore(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_composite_in_range(self):
        for p in [_safe_protocol(), _risky_protocol()]:
            result = self.a.assess([p], {})
            score = result["protocols"][0]["composite_risk_score"]
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_risky_higher_than_safe(self):
        r_safe = self.a.assess([_safe_protocol()], {})["protocols"][0]["composite_risk_score"]
        r_risky = self.a.assess([_risky_protocol()], {})["protocols"][0]["composite_risk_score"]
        self.assertGreater(r_risky, r_safe)

    def test_fee_reduces_composite(self):
        p_no_fee = _risky_protocol(flash_loan_fee_bps=0)
        p_fee = _risky_protocol(flash_loan_fee_bps=50)
        r1 = self.a.assess([p_no_fee], {})["protocols"][0]["composite_risk_score"]
        r2 = self.a.assess([p_fee], {})["protocols"][0]["composite_risk_score"]
        self.assertGreaterEqual(r1, r2)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_empty_aggregates(self):
        result = self.a.assess([], {})
        agg = result["aggregates"]
        self.assertIsNone(agg["safest"])
        self.assertIsNone(agg["riskiest"])
        self.assertEqual(agg["total_historical_losses_usd"], 0.0)
        self.assertEqual(agg["critical_count"], 0)
        self.assertEqual(agg["safe_count"], 0)

    def test_total_protocols(self):
        result = self.a.assess([_safe_protocol(), _risky_protocol()], {})
        self.assertEqual(result["aggregates"]["total_protocols"], 2)

    def test_safest_name(self):
        result = self.a.assess([_safe_protocol(name="A"), _risky_protocol(name="B")], {})
        self.assertEqual(result["aggregates"]["safest"], "A")

    def test_riskiest_name(self):
        result = self.a.assess([_safe_protocol(name="A"), _risky_protocol(name="B")], {})
        self.assertEqual(result["aggregates"]["riskiest"], "B")

    def test_total_losses_sum(self):
        p1 = _safe_protocol(amount_lost_to_flash_loans_usd=1_000)
        p2 = _risky_protocol(amount_lost_to_flash_loans_usd=5_000)
        result = self.a.assess([p1, p2], {})
        self.assertAlmostEqual(result["aggregates"]["total_historical_losses_usd"], 6_000, places=1)

    def test_critical_count(self):
        critical = _risky_protocol(
            historical_flash_loan_attacks=1,
            oracle_type="uniswap_spot",
            governance_attack_via_flash_loan_possible=True,
        )
        result = self.a.assess([critical, _safe_protocol()], {})
        self.assertEqual(result["aggregates"]["critical_count"], 1)

    def test_safe_count(self):
        result = self.a.assess([_safe_protocol(name="X"), _safe_protocol(name="Y")], {})
        self.assertGreaterEqual(result["aggregates"]["safe_count"], 1)


class TestOracleTypeVariants(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_chainlink_twap_not_spot(self):
        p = _safe_protocol(oracle_type="chainlink_twap", twap_period_minutes=30)
        result = self.a.assess([p], {})
        self.assertNotIn("SPOT_ORACLE_EXPOSED", result["protocols"][0]["flags"])

    def test_uniswap_spot_is_spot(self):
        p = _safe_protocol(oracle_type="uniswap_spot")
        result = self.a.assess([p], {})
        self.assertIn("SPOT_ORACLE_EXPOSED", result["protocols"][0]["flags"])

    def test_manual_oracle_is_spot(self):
        p = _safe_protocol(oracle_type="manual")
        result = self.a.assess([p], {})
        self.assertIn("SPOT_ORACLE_EXPOSED", result["protocols"][0]["flags"])

    def test_pyth_not_spot(self):
        p = _safe_protocol(oracle_type="pyth")
        result = self.a.assess([p], {})
        self.assertNotIn("SPOT_ORACLE_EXPOSED", result["protocols"][0]["flags"])

    def test_band_not_spot(self):
        p = _safe_protocol(oracle_type="band")
        result = self.a.assess([p], {})
        self.assertNotIn("SPOT_ORACLE_EXPOSED", result["protocols"][0]["flags"])

    def test_very_short_twap_treated_as_spot(self):
        p = _safe_protocol(oracle_type="chainlink_twap", twap_period_minutes=2)
        result = self.a.assess([p], {})
        self.assertIn("SPOT_ORACLE_EXPOSED", result["protocols"][0]["flags"])

    def test_sufficient_twap_not_spot(self):
        p = _safe_protocol(oracle_type="chainlink_twap", twap_period_minutes=10)
        result = self.a.assess([p], {})
        self.assertNotIn("SPOT_ORACLE_EXPOSED", result["protocols"][0]["flags"])


class TestSingleBlockManipulation(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_single_block_manip_adds_spot_flag(self):
        p = _safe_protocol(
            oracle_type="chainlink_twap",
            twap_period_minutes=30,
            single_block_price_manipulation_possible=True,
        )
        result = self.a.assess([p], {})
        self.assertIn("SPOT_ORACLE_EXPOSED", result["protocols"][0]["flags"])

    def test_no_single_block_no_spot_flag(self):
        p = _safe_protocol(
            oracle_type="chainlink_twap",
            twap_period_minutes=30,
            single_block_price_manipulation_possible=False,
        )
        result = self.a.assess([p], {})
        self.assertNotIn("SPOT_ORACLE_EXPOSED", result["protocols"][0]["flags"])


class TestProtocolCategories(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def _category(self, cat):
        return _safe_protocol(name=cat, category=cat)

    def test_lending_category(self):
        result = self.a.assess([self._category("lending")], {})
        self.assertEqual(result["protocols"][0]["category"], "lending")

    def test_dex_category(self):
        result = self.a.assess([self._category("dex")], {})
        self.assertEqual(result["protocols"][0]["category"], "dex")

    def test_yield_category(self):
        result = self.a.assess([self._category("yield")], {})
        self.assertEqual(result["protocols"][0]["category"], "yield")

    def test_bridge_category(self):
        result = self.a.assess([self._category("bridge")], {})
        self.assertEqual(result["protocols"][0]["category"], "bridge")


class TestWriteLog(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()
        self.tmp_dir = tempfile.mkdtemp()

    def _patch_log(self, path):
        import spa_core.analytics.defi_protocol_flash_loan_risk_assessor as mod
        self._orig = mod.LOG_FILE
        mod.LOG_FILE = path

    def _restore_log(self):
        import spa_core.analytics.defi_protocol_flash_loan_risk_assessor as mod
        mod.LOG_FILE = self._orig

    def test_write_log_creates_file(self):
        log_path = os.path.join(self.tmp_dir, "flash_loan_risk_log.json")
        self._patch_log(log_path)
        try:
            self.a.assess([_safe_protocol()], {"write_log": True})
            self.assertTrue(os.path.exists(log_path))
        finally:
            self._restore_log()

    def test_write_log_valid_json(self):
        log_path = os.path.join(self.tmp_dir, "flash_loan_risk_log2.json")
        self._patch_log(log_path)
        try:
            self.a.assess([_safe_protocol()], {"write_log": True})
            with open(log_path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
        finally:
            self._restore_log()

    def test_write_log_appends(self):
        log_path = os.path.join(self.tmp_dir, "flash_loan_risk_log3.json")
        self._patch_log(log_path)
        try:
            self.a.assess([_safe_protocol()], {"write_log": True})
            self.a.assess([_safe_protocol()], {"write_log": True})
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)
        finally:
            self._restore_log()

    def test_write_log_respects_cap(self):
        import spa_core.analytics.defi_protocol_flash_loan_risk_assessor as mod
        log_path = os.path.join(self.tmp_dir, "flash_loan_risk_log4.json")
        self._patch_log(log_path)
        old_cap = mod.LOG_CAP
        mod.LOG_CAP = 3
        try:
            for _ in range(6):
                self.a.assess([_safe_protocol()], {"write_log": True})
            with open(log_path) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), 3)
        finally:
            mod.LOG_CAP = old_cap
            self._restore_log()

    def test_no_log_without_flag(self):
        log_path = os.path.join(self.tmp_dir, "flash_loan_risk_log5.json")
        self._patch_log(log_path)
        try:
            self.a.assess([_safe_protocol()], {})
            self.assertFalse(os.path.exists(log_path))
        finally:
            self._restore_log()


class TestMultipleProtocols(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_five_protocols(self):
        protocols = [
            _safe_protocol(name=f"P{i}") for i in range(3)
        ] + [_risky_protocol(name=f"R{i}") for i in range(2)]
        result = self.a.assess(protocols, {})
        self.assertEqual(len(result["protocols"]), 5)

    def test_all_names_preserved(self):
        names = ["Alpha", "Beta", "Gamma"]
        result = self.a.assess([_safe_protocol(name=n) for n in names], {})
        returned = [p["name"] for p in result["protocols"]]
        self.assertEqual(returned, names)

    def test_protocol_without_optional_keys(self):
        minimal = {"name": "Minimal", "oracle_type": "chainlink_twap"}
        result = self.a.assess([minimal], {})
        self.assertIn("risk_label", result["protocols"][0])

    def test_single_protocol_safest_equals_riskiest(self):
        result = self.a.assess([_safe_protocol(name="Only")], {})
        self.assertEqual(result["aggregates"]["safest"], "Only")
        self.assertEqual(result["aggregates"]["riskiest"], "Only")


class TestConfigOverrides(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_custom_high_revenue_threshold(self):
        # fl_fee_revenue = 1_000_000 * (30/10000) = 3000
        # total_fees = 10_000 → fl_revenue_pct = 30% → above 5% strict threshold
        p = _safe_protocol(
            flash_loan_available=True,
            flash_loan_fee_bps=30,
            total_flash_loan_volume_30d_usd=1_000_000,
            total_protocol_fees_30d_usd=10_000,
        )
        result_default = self.a.assess([p], {})  # threshold=30%, 30%==30% boundary
        result_strict = self.a.assess([p], {"high_revenue_threshold_pct": 5.0})  # 30% > 5%
        flags_strict = result_strict["protocols"][0]["flags"]
        self.assertIn("HIGH_REVENUE_DEPENDENCY", flags_strict)

    def test_write_log_false_by_default(self):
        # config without write_log key shouldn't log
        import spa_core.analytics.defi_protocol_flash_loan_risk_assessor as mod
        log_path = "/tmp/_test_fl_no_write.json"
        old = mod.LOG_FILE
        mod.LOG_FILE = log_path
        try:
            if os.path.exists(log_path):
                os.remove(log_path)
            self.a.assess([_safe_protocol()], {})
            self.assertFalse(os.path.exists(log_path))
        finally:
            mod.LOG_FILE = old


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_zero_tvl_no_division_error(self):
        p = _safe_protocol(tvl_usd=0, amount_lost_to_flash_loans_usd=0)
        result = self.a.assess([p], {})
        self.assertIsNotNone(result)

    def test_very_large_tvl(self):
        p = _safe_protocol(tvl_usd=1_000_000_000_000)
        result = self.a.assess([p], {})
        self.assertIsNotNone(result)

    def test_negative_amounts_handled(self):
        # Should not crash; values treated as provided
        p = _safe_protocol(amount_lost_to_flash_loans_usd=-100)
        result = self.a.assess([p], {})
        self.assertIsNotNone(result)

    def test_max_loan_pct_25_mid_score(self):
        p_low = _safe_protocol(max_single_flash_loan_as_pct_tvl=10)
        p_mid = _safe_protocol(max_single_flash_loan_as_pct_tvl=30)
        r_low = self.a.assess([p_low], {})["protocols"][0]["attack_surface_score"]
        r_mid = self.a.assess([p_mid], {})["protocols"][0]["attack_surface_score"]
        self.assertGreaterEqual(r_mid, r_low)

    def test_all_risk_labels_valid(self):
        valid = {"FLASH_LOAN_SAFE", "LOW_RISK", "MODERATE_RISK", "HIGH_RISK", "CRITICAL"}
        for p in [_safe_protocol(), _risky_protocol()]:
            result = self.a.assess([p], {})
            label = result["protocols"][0]["risk_label"]
            self.assertIn(label, valid)

    def test_protocol_name_preserved(self):
        p = _safe_protocol(name="SpecialName_123")
        result = self.a.assess([p], {})
        self.assertEqual(result["protocols"][0]["name"], "SpecialName_123")

    def test_output_fields_complete(self):
        expected_fields = {
            "name", "category", "attack_surface_score", "historical_loss_ratio",
            "fee_deterrent_score", "flash_loan_revenue_pct", "composite_risk_score",
            "risk_label", "flags",
        }
        result = self.a.assess([_safe_protocol()], {})
        actual = set(result["protocols"][0].keys())
        self.assertTrue(expected_fields.issubset(actual))


class TestLowRiskLabel(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_partial_risk_gives_low_or_moderate(self):
        # Band oracle (not spot), reentrancy, slight governance concern
        p = _safe_protocol(
            oracle_type="band",
            reentrancy_guard=True,
            governance_attack_via_flash_loan_possible=False,
            historical_flash_loan_attacks=0,
        )
        result = self.a.assess([p], {})
        label = result["protocols"][0]["risk_label"]
        self.assertIn(label, ("FLASH_LOAN_SAFE", "LOW_RISK", "MODERATE_RISK"))

    def test_composite_score_drives_label(self):
        p = _safe_protocol(
            oracle_type="chainlink_twap",
            twap_period_minutes=30,
            reentrancy_guard=False,  # adds 20 to surface
            governance_attack_via_flash_loan_possible=False,
        )
        result = self.a.assess([p], {})
        label = result["protocols"][0]["risk_label"]
        self.assertIn(label, ("LOW_RISK", "MODERATE_RISK", "HIGH_RISK", "FLASH_LOAN_SAFE"))


class TestReturnTypes(unittest.TestCase):
    def setUp(self):
        self.a = DeFiProtocolFlashLoanRiskAssessor()

    def test_attack_surface_is_float(self):
        result = self.a.assess([_safe_protocol()], {})
        self.assertIsInstance(result["protocols"][0]["attack_surface_score"], float)

    def test_composite_score_is_float(self):
        result = self.a.assess([_safe_protocol()], {})
        self.assertIsInstance(result["protocols"][0]["composite_risk_score"], float)

    def test_flags_is_list(self):
        result = self.a.assess([_safe_protocol()], {})
        self.assertIsInstance(result["protocols"][0]["flags"], list)

    def test_risk_label_is_str(self):
        result = self.a.assess([_safe_protocol()], {})
        self.assertIsInstance(result["protocols"][0]["risk_label"], str)

    def test_aggregates_is_dict(self):
        result = self.a.assess([_safe_protocol()], {})
        self.assertIsInstance(result["aggregates"], dict)

    def test_total_losses_is_float(self):
        result = self.a.assess([_safe_protocol()], {})
        self.assertIsInstance(result["aggregates"]["total_historical_losses_usd"], float)


if __name__ == "__main__":
    unittest.main()
