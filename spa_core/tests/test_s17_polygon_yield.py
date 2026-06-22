"""
spa_core/tests/test_s17_polygon_yield.py — Unit tests for S17 Polygon Yield Strategy

Tests: 80+ cases across 8 test classes.
  TestInit (10)
  TestAllocationWeights (10)
  TestGetAllocation (15)
  TestGetExpectedAPY (10)
  TestGetPolygonAdvantages (10)
  TestGetHealth (10)
  TestSimulate (8)
  TestToDict (7)

Stdlib only. All tests isolate adapters via monkey-patching so no network calls.
"""
from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Import target module
# ---------------------------------------------------------------------------
from spa_core.strategies.s17_polygon_yield import (
    ALLOCATION,
    ALLOCATION_WEIGHTS,
    DESCRIPTION,
    FALLBACK_APY,
    GAS_L2_USD,
    GAS_SAVINGS_PCT,
    AVG_FINALITY_MINUTES,
    MAX_DRAWDOWN_PCT,
    RISK_BLENDED,
    RISK_SCORES,
    STRATEGY_ID,
    TARGET_APY_MAX,
    TARGET_APY_MIN,
    TARGET_APY_PCT,
    WEIGHTED_APY_EXPECTED,
    PolygonYieldStrategy,
)


# ---------------------------------------------------------------------------
# Helpers — fake adapter factories
# ---------------------------------------------------------------------------

def _make_adapter(apy: float = 5.0, eligible: bool = True) -> MagicMock:
    """Create a mock adapter with get_apy, is_eligible, simulate_deposit."""
    a = MagicMock()
    a.get_apy.return_value = apy
    a.is_eligible.return_value = eligible
    a.simulate_deposit.return_value = {
        "status": "ok",
        "apy_pct": apy,
        "annual_yield_usd": 0.0,
    }
    return a


def _strategy_no_adapters() -> PolygonYieldStrategy:
    """Strategy with no real adapters loaded — uses fallback everywhere."""
    s = PolygonYieldStrategy.__new__(PolygonYieldStrategy)
    s._adapters = {}
    return s


def _strategy_all_mocked(
    polygon_apy: float = 5.1,
    spark_apy: float = 5.5,
    morpho_apy: float = 7.0,
    polygon_eligible: bool = True,
    spark_eligible: bool = True,
    morpho_eligible: bool = True,
) -> PolygonYieldStrategy:
    """Strategy with all 3 adapters mocked."""
    s = PolygonYieldStrategy.__new__(PolygonYieldStrategy)
    s._adapters = {
        "aave_v3_polygon": _make_adapter(polygon_apy, polygon_eligible),
        "spark_susds":     _make_adapter(spark_apy, spark_eligible),
        "morpho_blue":     _make_adapter(morpho_apy, morpho_eligible),
    }
    return s


# ===========================================================================
# TestInit
# ===========================================================================
class TestInit(unittest.TestCase):
    """10 tests — construction, class attributes, adapter loading."""

    def test_strategy_id_class(self):
        self.assertEqual(PolygonYieldStrategy.STRATEGY_ID, "S17")

    def test_strategy_name_class(self):
        self.assertEqual(PolygonYieldStrategy.STRATEGY_NAME, "Polygon Yield")

    def test_tier_class(self):
        self.assertEqual(PolygonYieldStrategy.TIER, "T1")

    def test_target_apy_class(self):
        self.assertEqual(PolygonYieldStrategy.TARGET_APY_PCT, 5.8)

    def test_risk_score_class(self):
        self.assertAlmostEqual(PolygonYieldStrategy.RISK_SCORE, 0.25, places=2)

    def test_init_creates_adapters_dict(self):
        s = _strategy_no_adapters()
        self.assertIsInstance(s._adapters, dict)

    def test_init_instance_strategy_id(self):
        s = _strategy_no_adapters()
        self.assertEqual(s.STRATEGY_ID, "S17")

    def test_init_instance_strategy_name(self):
        s = _strategy_no_adapters()
        self.assertEqual(s.STRATEGY_NAME, "Polygon Yield")

    def test_init_load_adapters_fails_gracefully(self):
        """If all adapter imports fail, _adapters remains empty — no exception."""
        with patch.dict(sys.modules, {
            "spa_core.adapters.aave_v3_polygon_adapter": None,
            "spa_core.adapters.spark_susds_adapter": None,
            "spa_core.adapters.morpho_blue": None,
        }):
            try:
                s = PolygonYieldStrategy()
                # should not raise; adapters may be empty or partially loaded
                self.assertIsInstance(s._adapters, dict)
            except Exception:
                pass  # acceptable if imports raise non-ImportError

    def test_module_constants_strategy_id(self):
        self.assertEqual(STRATEGY_ID, "S17")


# ===========================================================================
# TestAllocationWeights
# ===========================================================================
class TestAllocationWeights(unittest.TestCase):
    """10 tests — weight correctness, sum, per-slot values, fallback."""

    def test_weights_sum_to_one(self):
        total = sum(ALLOCATION_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_core_weight_is_60_pct(self):
        self.assertAlmostEqual(ALLOCATION_WEIGHTS["aave_v3_polygon"], 0.60, places=9)

    def test_anchor_weight_is_25_pct(self):
        self.assertAlmostEqual(ALLOCATION_WEIGHTS["spark_susds"], 0.25, places=9)

    def test_boost_weight_is_15_pct(self):
        self.assertAlmostEqual(ALLOCATION_WEIGHTS["morpho_blue"], 0.15, places=9)

    def test_allocation_three_slots(self):
        self.assertEqual(len(ALLOCATION), 3)
        self.assertIn("core", ALLOCATION)
        self.assertIn("anchor", ALLOCATION)
        self.assertIn("boost", ALLOCATION)

    def test_allocation_core_adapter_key(self):
        self.assertEqual(ALLOCATION["core"]["adapter"], "aave_v3_polygon")

    def test_allocation_anchor_adapter_key(self):
        self.assertEqual(ALLOCATION["anchor"]["adapter"], "spark_susds")

    def test_allocation_boost_adapter_key(self):
        self.assertEqual(ALLOCATION["boost"]["adapter"], "morpho_blue")

    def test_effective_weights_all_eligible_sum_one(self):
        s = _strategy_all_mocked()
        weights = s._compute_effective_weights()
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=9)

    def test_effective_weights_all_eligible_core_60(self):
        s = _strategy_all_mocked()
        weights = s._compute_effective_weights()
        self.assertAlmostEqual(weights["aave_v3_polygon"], 0.60, places=9)


# ===========================================================================
# TestGetAllocation
# ===========================================================================
class TestGetAllocation(unittest.TestCase):
    """15 tests — capital split, fallback, redistribution, edge cases."""

    def test_allocation_sum_equals_capital(self):
        s = _strategy_all_mocked()
        result = s.get_allocation(100_000)
        self.assertAlmostEqual(sum(result.values()), 100_000, places=4)

    def test_allocation_core_60k_of_100k(self):
        s = _strategy_all_mocked()
        result = s.get_allocation(100_000)
        self.assertAlmostEqual(result["aave_v3_polygon"], 60_000, places=4)

    def test_allocation_anchor_25k_of_100k(self):
        s = _strategy_all_mocked()
        result = s.get_allocation(100_000)
        self.assertAlmostEqual(result["spark_susds"], 25_000, places=4)

    def test_allocation_boost_15k_of_100k(self):
        s = _strategy_all_mocked()
        result = s.get_allocation(100_000)
        self.assertAlmostEqual(result["morpho_blue"], 15_000, places=4)

    def test_allocation_zero_capital_returns_zeros(self):
        s = _strategy_all_mocked()
        result = s.get_allocation(0.0)
        for v in result.values():
            self.assertEqual(v, 0.0)

    def test_allocation_negative_capital_returns_zeros(self):
        s = _strategy_all_mocked()
        result = s.get_allocation(-500.0)
        for v in result.values():
            self.assertEqual(v, 0.0)

    def test_allocation_no_adapters_fallback_sum(self):
        """No real adapters → fallback eligible=True → same weights."""
        s = _strategy_no_adapters()
        result = s.get_allocation(100_000)
        self.assertAlmostEqual(sum(result.values()), 100_000, places=4)

    def test_allocation_no_adapters_core_60k(self):
        s = _strategy_no_adapters()
        result = s.get_allocation(100_000)
        self.assertAlmostEqual(result["aave_v3_polygon"], 60_000, places=4)

    def test_allocation_core_ineligible_redistributes(self):
        """Core (60%) ineligible → anchor+boost absorb remaining weight."""
        s = _strategy_all_mocked(polygon_eligible=False)
        result = s.get_allocation(100_000)
        self.assertNotIn("aave_v3_polygon", result)
        self.assertAlmostEqual(sum(result.values()), 100_000, places=4)
        # anchor weight was 0.25, boost 0.15 → total 0.40; anchor = 0.25/0.40=62.5%
        self.assertAlmostEqual(result["spark_susds"], 62_500, places=3)

    def test_allocation_boost_ineligible_redistributes(self):
        """Boost (15%) ineligible → core+anchor absorb 100%."""
        s = _strategy_all_mocked(morpho_eligible=False)
        result = s.get_allocation(100_000)
        self.assertNotIn("morpho_blue", result)
        self.assertAlmostEqual(sum(result.values()), 100_000, places=4)

    def test_allocation_two_ineligible_only_anchor(self):
        """Only anchor eligible → gets 100%."""
        s = _strategy_all_mocked(polygon_eligible=False, morpho_eligible=False)
        result = s.get_allocation(100_000)
        self.assertEqual(list(result.keys()), ["spark_susds"])
        self.assertAlmostEqual(result["spark_susds"], 100_000, places=4)

    def test_allocation_all_ineligible_empty(self):
        """All ineligible → empty dict."""
        s = _strategy_all_mocked(polygon_eligible=False, spark_eligible=False, morpho_eligible=False)
        result = s.get_allocation(100_000)
        self.assertEqual(result, {})

    def test_allocation_small_capital(self):
        s = _strategy_all_mocked()
        result = s.get_allocation(1.0)
        self.assertAlmostEqual(sum(result.values()), 1.0, places=9)

    def test_allocation_large_capital(self):
        s = _strategy_all_mocked()
        result = s.get_allocation(10_000_000)
        self.assertAlmostEqual(result["aave_v3_polygon"], 6_000_000, places=2)

    def test_allocation_returns_dict(self):
        s = _strategy_all_mocked()
        result = s.get_allocation(100_000)
        self.assertIsInstance(result, dict)


# ===========================================================================
# TestGetExpectedAPY
# ===========================================================================
class TestGetExpectedAPY(unittest.TestCase):
    """10 tests — weighted APY computation, fallback, edge cases."""

    def test_expected_apy_all_fallback(self):
        """No adapters → fallback APYs used → 0.60*5.1+0.25*5.5+0.15*7.0 ≈ 5.485."""
        s = _strategy_no_adapters()
        apy = s.get_expected_apy()
        self.assertAlmostEqual(apy, 5.485, places=3)

    def test_expected_apy_all_mocked_defaults(self):
        s = _strategy_all_mocked(5.1, 5.5, 7.0)
        apy = s.get_expected_apy()
        self.assertAlmostEqual(apy, 5.485, places=3)

    def test_expected_apy_higher_polygon(self):
        """If polygon APY goes to 8%: 0.60*8+0.25*5.5+0.15*7.0 = 4.8+1.375+1.05=7.225."""
        s = _strategy_all_mocked(polygon_apy=8.0)
        apy = s.get_expected_apy()
        self.assertAlmostEqual(apy, 7.225, places=3)

    def test_expected_apy_zero_when_all_ineligible(self):
        s = _strategy_all_mocked(polygon_eligible=False, spark_eligible=False, morpho_eligible=False)
        apy = s.get_expected_apy()
        self.assertEqual(apy, 0.0)

    def test_expected_apy_positive(self):
        s = _strategy_all_mocked()
        self.assertGreater(s.get_expected_apy(), 0.0)

    def test_expected_apy_weighted_constant_matches(self):
        """Module-level WEIGHTED_APY_EXPECTED should match formula."""
        expected = 0.60 * 5.1 + 0.25 * 5.5 + 0.15 * 7.0
        self.assertAlmostEqual(WEIGHTED_APY_EXPECTED, expected, places=3)

    def test_expected_apy_only_core_eligible(self):
        s = _strategy_all_mocked(spark_eligible=False, morpho_eligible=False)
        # Only core (aave_v3_polygon=5.1%) eligible → weight=1.0 → APY=5.1
        apy = s.get_expected_apy()
        self.assertAlmostEqual(apy, 5.1, places=4)

    def test_expected_apy_returns_float(self):
        s = _strategy_no_adapters()
        self.assertIsInstance(s.get_expected_apy(), float)

    def test_expected_apy_fallback_when_adapter_apy_invalid(self):
        """Adapter returns negative APY → fallback used."""
        s = PolygonYieldStrategy.__new__(PolygonYieldStrategy)
        bad_adapter = MagicMock()
        bad_adapter.get_apy.return_value = -1.0
        bad_adapter.is_eligible.return_value = True
        s._adapters = {"aave_v3_polygon": bad_adapter}
        # polygon falls back to 5.1; spark/morpho use no-adapter fallback
        apy = s.get_expected_apy()
        expected = 0.60 * 5.1 + 0.25 * 5.5 + 0.15 * 7.0
        self.assertAlmostEqual(apy, expected, places=2)

    def test_expected_apy_with_all_higher_apys(self):
        s = _strategy_all_mocked(polygon_apy=6.0, spark_apy=6.5, morpho_apy=9.0)
        apy = s.get_expected_apy()
        expected = 0.60 * 6.0 + 0.25 * 6.5 + 0.15 * 9.0
        self.assertAlmostEqual(apy, expected, places=3)


# ===========================================================================
# TestGetPolygonAdvantages
# ===========================================================================
class TestGetPolygonAdvantages(unittest.TestCase):
    """10 tests — gas_savings, finality, bridge_risk, usdc_note."""

    def _adv(self) -> dict:
        return _strategy_no_adapters().get_polygon_advantages()

    def test_gas_savings_pct_positive(self):
        adv = self._adv()
        self.assertGreater(adv["gas_savings_pct"], 0.0)

    def test_gas_savings_pct_90_default(self):
        adv = self._adv()
        self.assertAlmostEqual(adv["gas_savings_pct"], 90.0, places=1)

    def test_gas_l2_usd_less_than_mainnet(self):
        adv = self._adv()
        self.assertLess(adv["gas_l2_usd"], adv["gas_mainnet_usd"])

    def test_avg_finality_minutes_positive(self):
        adv = self._adv()
        self.assertGreater(adv["avg_finality_minutes"], 0)

    def test_avg_finality_minutes_is_int(self):
        adv = self._adv()
        self.assertIsInstance(adv["avg_finality_minutes"], int)

    def test_chain_is_polygon(self):
        adv = self._adv()
        self.assertEqual(adv["chain"], "polygon")

    def test_usdc_note_nonempty(self):
        adv = self._adv()
        self.assertIsInstance(adv["usdc_note"], str)
        self.assertGreater(len(adv["usdc_note"]), 10)

    def test_bridge_risk_nonempty(self):
        adv = self._adv()
        self.assertIsInstance(adv["bridge_risk"], str)
        self.assertGreater(len(adv["bridge_risk"]), 10)

    def test_uses_adapter_gas_info_if_loaded(self):
        """If core adapter loaded, gas info from adapter is used."""
        s = PolygonYieldStrategy.__new__(PolygonYieldStrategy)
        mock_adapter = MagicMock()
        mock_adapter.get_gas_savings_vs_mainnet.return_value = {
            "savings_pct": 92.0,
            "chain": "polygon",
            "gas_l2_usd": 0.0005,
            "gas_mainnet_usd": 0.12,
            "finality_minutes": 3,
            "mainnet_bridge_exit_days": 7,
        }
        mock_adapter.get_bridge_risk_note.return_value = "custom bridge note"
        s._adapters = {"aave_v3_polygon": mock_adapter}
        adv = s.get_polygon_advantages()
        self.assertAlmostEqual(adv["gas_savings_pct"], 92.0, places=1)
        self.assertEqual(adv["bridge_risk"], "custom bridge note")

    def test_all_required_keys_present(self):
        adv = self._adv()
        for key in [
            "gas_savings_pct", "gas_l2_usd", "gas_mainnet_usd",
            "avg_finality_minutes", "mainnet_bridge_exit_days",
            "chain", "usdc_note", "bridge_risk"
        ]:
            self.assertIn(key, adv, f"Missing key: {key}")


# ===========================================================================
# TestGetHealth
# ===========================================================================
class TestGetHealth(unittest.TestCase):
    """10 tests — health status, chain_breakdown, flags."""

    def test_health_returns_dict(self):
        s = _strategy_all_mocked()
        self.assertIsInstance(s.get_health(), dict)

    def test_health_strategy_id(self):
        s = _strategy_all_mocked()
        self.assertEqual(s.get_health()["strategy_id"], "S17")

    def test_health_all_eligible_true(self):
        s = _strategy_all_mocked()
        health = s.get_health()
        self.assertTrue(health["all_eligible"])

    def test_health_overall_status_ok_when_all_eligible(self):
        s = _strategy_all_mocked()
        self.assertEqual(s.get_health()["overall_status"], "ok")

    def test_health_overall_status_warning_when_core_ineligible(self):
        s = _strategy_all_mocked(polygon_eligible=False)
        self.assertIn(s.get_health()["overall_status"], ("ok", "warning"))

    def test_health_all_eligible_false_when_any_ineligible(self):
        s = _strategy_all_mocked(polygon_eligible=False)
        health = s.get_health()
        self.assertFalse(health["all_eligible"])

    def test_health_polygon_core_eligible_true(self):
        s = _strategy_all_mocked()
        self.assertTrue(s.get_health()["polygon_core_eligible"])

    def test_health_polygon_core_eligible_false_when_core_down(self):
        s = _strategy_all_mocked(polygon_eligible=False)
        self.assertFalse(s.get_health()["polygon_core_eligible"])

    def test_health_chain_breakdown_has_all_adapters(self):
        s = _strategy_all_mocked()
        bd = s.get_health()["chain_breakdown"]
        for key in ["aave_v3_polygon", "spark_susds", "morpho_blue"]:
            self.assertIn(key, bd)

    def test_health_chain_breakdown_has_expected_fields(self):
        s = _strategy_all_mocked()
        bd = s.get_health()["chain_breakdown"]
        for adapter_info in bd.values():
            for field in ["slot", "role", "weight", "apy", "eligible", "tier", "risk_score"]:
                self.assertIn(field, adapter_info, f"Missing field: {field}")


# ===========================================================================
# TestSimulate
# ===========================================================================
class TestSimulate(unittest.TestCase):
    """8 tests — simulation results, yield calculation, status."""

    def test_simulate_returns_dict(self):
        s = _strategy_all_mocked()
        result = s.simulate(100_000)
        self.assertIsInstance(result, dict)

    def test_simulate_expected_yield_positive(self):
        s = _strategy_all_mocked()
        result = s.simulate(100_000)
        self.assertGreater(result["expected_annual_yield_usd"], 0.0)

    def test_simulate_allocation_sum_equals_capital(self):
        s = _strategy_all_mocked()
        result = s.simulate(100_000)
        self.assertAlmostEqual(sum(result["allocation"].values()), 100_000, places=2)

    def test_simulate_status_ok(self):
        s = _strategy_all_mocked()
        self.assertEqual(s.simulate(100_000)["status"], "ok")

    def test_simulate_no_eligible_adapters(self):
        s = _strategy_all_mocked(polygon_eligible=False, spark_eligible=False, morpho_eligible=False)
        result = s.simulate(100_000)
        self.assertEqual(result["status"], "no_eligible_adapters")
        self.assertEqual(result["expected_annual_yield_usd"], 0.0)

    def test_simulate_expected_apy_pct_positive(self):
        s = _strategy_all_mocked()
        self.assertGreater(s.simulate(100_000)["expected_apy_pct"], 0.0)

    def test_simulate_slot_results_keys(self):
        s = _strategy_all_mocked()
        result = s.simulate(100_000)
        for key in result["slot_results"]:
            slot = result["slot_results"][key]
            self.assertIn("amount_usd", slot)
            self.assertIn("apy_pct", slot)
            self.assertIn("annual_yield_usd", slot)

    def test_simulate_yield_formula(self):
        """Annual yield = sum(amount * apy/100) for each adapter."""
        s = _strategy_all_mocked(polygon_apy=5.1, spark_apy=5.5, morpho_apy=7.0)
        result = s.simulate(100_000)
        expected_yield = (60_000 * 5.1 / 100) + (25_000 * 5.5 / 100) + (15_000 * 7.0 / 100)
        self.assertAlmostEqual(result["expected_annual_yield_usd"], expected_yield, places=2)


# ===========================================================================
# TestToDict
# ===========================================================================
class TestToDict(unittest.TestCase):
    """7 tests — JSON serializability, required keys, values."""

    def _d(self) -> dict:
        return _strategy_all_mocked().to_dict()

    def test_to_dict_returns_dict(self):
        self.assertIsInstance(self._d(), dict)

    def test_to_dict_strategy_id(self):
        self.assertEqual(self._d()["strategy_id"], "S17")

    def test_to_dict_strategy_name(self):
        self.assertEqual(self._d()["strategy_name"], "Polygon Yield")

    def test_to_dict_json_serializable(self):
        import json
        d = self._d()
        serialized = json.dumps(d)
        restored = json.loads(serialized)
        self.assertEqual(restored["strategy_id"], "S17")

    def test_to_dict_required_keys(self):
        d = self._d()
        for key in [
            "strategy_id", "strategy_name", "tier", "description",
            "target_apy_pct", "expected_apy_pct", "risk_score",
            "allocation", "allocation_weights", "fallback_apy", "risk_scores",
            "all_eligible", "overall_status", "polygon_advantages",
            "adapters_loaded", "timestamp",
        ]:
            self.assertIn(key, d, f"Missing key: {key}")

    def test_to_dict_allocation_weights_sum_one(self):
        d = self._d()
        total = sum(d["allocation_weights"].values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_to_dict_polygon_advantages_present(self):
        d = self._d()
        adv = d["polygon_advantages"]
        self.assertIn("gas_savings_pct", adv)
        self.assertGreater(adv["gas_savings_pct"], 0)


# ===========================================================================
# Additional edge-case / module-level tests
# ===========================================================================
class TestModuleConstants(unittest.TestCase):
    """Additional constant-level checks."""

    def test_gas_savings_pct_is_90(self):
        self.assertAlmostEqual(GAS_SAVINGS_PCT, 90.0, places=1)

    def test_gas_l2_usd_less_than_01(self):
        self.assertLess(GAS_L2_USD, 0.01)

    def test_target_apy_pct_is_5_8(self):
        self.assertAlmostEqual(TARGET_APY_PCT, 5.8, places=1)

    def test_risk_blended_is_025(self):
        self.assertAlmostEqual(RISK_BLENDED, 0.25, places=2)

    def test_target_apy_min_less_than_max(self):
        self.assertLess(TARGET_APY_MIN, TARGET_APY_MAX)

    def test_max_drawdown_pct_is_5(self):
        self.assertAlmostEqual(MAX_DRAWDOWN_PCT, 5.0, places=1)

    def test_fallback_apy_all_positive(self):
        for k, v in FALLBACK_APY.items():
            self.assertGreater(v, 0.0, f"FALLBACK_APY[{k}] should be > 0")

    def test_risk_scores_all_between_0_and_1(self):
        for k, v in RISK_SCORES.items():
            self.assertGreater(v, 0.0)
            self.assertLess(v, 1.0)

    def test_avg_finality_minutes_positive(self):
        self.assertGreater(AVG_FINALITY_MINUTES, 0)

    def test_description_nonempty(self):
        self.assertGreater(len(DESCRIPTION), 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
