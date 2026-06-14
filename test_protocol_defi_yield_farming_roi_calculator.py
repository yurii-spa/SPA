"""
Tests for MP-1047 ProtocolDeFiYieldFarmingROICalculator
≥90 unittest tests — pure stdlib, no third-party dependencies.
"""

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_defi_yield_farming_roi_calculator import (
    ProtocolDeFiYieldFarmingROICalculator,
    calculate,
    _gross_apy_pct,
    _token_price_ratio,
    _token_adjusted_apy_pct,
    _gas_cost_annual_pct,
    _net_apy_pct,
    _roi_vs_hodl_pct,
    _label,
    _period_return_pct,
    _build_recommendations,
    _atomic_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _params(
    protocol: str = "TestFarm",
    base_yield_apy_pct: float = 8.0,
    reward_token_apy_pct: float = 12.0,
    reward_token_price_usd: float = 2.0,
    reward_token_entry_price_usd: float = 2.0,
    gas_cost_usd_per_week: float = 20.0,
    il_estimate_pct: float = 3.0,
    management_overhead_hrs_per_week: float = 1.0,
    opportunity_cost_apy_pct: float = 5.0,
    weeks_farmed: float = 12.0,
    position_usd: float = 10_000.0,
) -> dict:
    return {
        "protocol": protocol,
        "base_yield_apy_pct": base_yield_apy_pct,
        "reward_token_apy_pct": reward_token_apy_pct,
        "reward_token_price_usd": reward_token_price_usd,
        "reward_token_entry_price_usd": reward_token_entry_price_usd,
        "gas_cost_usd_per_week": gas_cost_usd_per_week,
        "il_estimate_pct": il_estimate_pct,
        "management_overhead_hrs_per_week": management_overhead_hrs_per_week,
        "opportunity_cost_apy_pct": opportunity_cost_apy_pct,
        "weeks_farmed": weeks_farmed,
        "position_usd": position_usd,
    }


# ===========================================================================
# 1. _gross_apy_pct
# ===========================================================================

class TestGrossApy(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(_gross_apy_pct(8.0, 12.0), 20.0)

    def test_zero_reward(self):
        self.assertAlmostEqual(_gross_apy_pct(5.0, 0.0), 5.0)

    def test_zero_base(self):
        self.assertAlmostEqual(_gross_apy_pct(0.0, 10.0), 10.0)

    def test_both_zero(self):
        self.assertAlmostEqual(_gross_apy_pct(0.0, 0.0), 0.0)

    def test_negative_base_treated_as_zero(self):
        self.assertAlmostEqual(_gross_apy_pct(-5.0, 10.0), 10.0)

    def test_negative_reward_treated_as_zero(self):
        self.assertAlmostEqual(_gross_apy_pct(5.0, -3.0), 5.0)

    def test_additive(self):
        v = _gross_apy_pct(3.5, 6.5)
        self.assertAlmostEqual(v, 10.0)


# ===========================================================================
# 2. _token_price_ratio
# ===========================================================================

class TestTokenPriceRatio(unittest.TestCase):
    def test_unchanged(self):
        self.assertAlmostEqual(_token_price_ratio(2.0, 2.0), 1.0)

    def test_doubled(self):
        self.assertAlmostEqual(_token_price_ratio(4.0, 2.0), 2.0)

    def test_halved(self):
        self.assertAlmostEqual(_token_price_ratio(1.0, 2.0), 0.5)

    def test_zero_entry_price_returns_one(self):
        self.assertAlmostEqual(_token_price_ratio(3.0, 0.0), 1.0)

    def test_negative_entry_price_returns_one(self):
        self.assertAlmostEqual(_token_price_ratio(3.0, -1.0), 1.0)

    def test_zero_current_price(self):
        self.assertAlmostEqual(_token_price_ratio(0.0, 2.0), 0.0)

    def test_negative_current_price_clamped(self):
        self.assertAlmostEqual(_token_price_ratio(-1.0, 2.0), 0.0)

    def test_proportional(self):
        r1 = _token_price_ratio(1.0, 2.0)
        r2 = _token_price_ratio(3.0, 2.0)
        self.assertLess(r1, r2)


# ===========================================================================
# 3. _token_adjusted_apy_pct
# ===========================================================================

class TestTokenAdjustedApy(unittest.TestCase):
    def test_no_change(self):
        # price unchanged → same as gross
        self.assertAlmostEqual(_token_adjusted_apy_pct(8.0, 12.0, 2.0, 2.0), 20.0)

    def test_token_halved(self):
        # reward goes from 12% to 6%
        self.assertAlmostEqual(_token_adjusted_apy_pct(8.0, 12.0, 1.0, 2.0), 14.0)

    def test_token_doubled(self):
        # reward goes from 12% to 24%
        self.assertAlmostEqual(_token_adjusted_apy_pct(8.0, 12.0, 4.0, 2.0), 32.0)

    def test_zero_entry_price_uses_nominal(self):
        # ratio = 1.0 when entry=0
        self.assertAlmostEqual(_token_adjusted_apy_pct(8.0, 12.0, 5.0, 0.0), 20.0)

    def test_token_worthless(self):
        # token crashes to 0
        self.assertAlmostEqual(_token_adjusted_apy_pct(8.0, 12.0, 0.0, 2.0), 8.0)

    def test_base_yield_unaffected_by_token_price(self):
        v1 = _token_adjusted_apy_pct(5.0, 0.0, 0.0, 2.0)
        v2 = _token_adjusted_apy_pct(5.0, 0.0, 100.0, 2.0)
        self.assertAlmostEqual(v1, v2)
        self.assertAlmostEqual(v1, 5.0)

    def test_negative_base_treated_as_zero(self):
        self.assertAlmostEqual(_token_adjusted_apy_pct(-5.0, 10.0, 2.0, 2.0), 10.0)


# ===========================================================================
# 4. _gas_cost_annual_pct
# ===========================================================================

class TestGasCostAnnualPct(unittest.TestCase):
    def test_basic(self):
        # $20/week * 52 / $10000 * 100 = 10.4%
        self.assertAlmostEqual(_gas_cost_annual_pct(20.0, 10_000.0), 10.4)

    def test_zero_position(self):
        self.assertAlmostEqual(_gas_cost_annual_pct(20.0, 0.0), 0.0)

    def test_zero_gas(self):
        self.assertAlmostEqual(_gas_cost_annual_pct(0.0, 10_000.0), 0.0)

    def test_scales_with_gas(self):
        v1 = _gas_cost_annual_pct(10.0, 10_000.0)
        v2 = _gas_cost_annual_pct(20.0, 10_000.0)
        self.assertAlmostEqual(v2, v1 * 2)

    def test_inverse_with_position(self):
        v1 = _gas_cost_annual_pct(20.0, 10_000.0)
        v2 = _gas_cost_annual_pct(20.0, 20_000.0)
        self.assertAlmostEqual(v2, v1 / 2)

    def test_negative_gas_treated_as_zero(self):
        self.assertAlmostEqual(_gas_cost_annual_pct(-5.0, 10_000.0), 0.0)

    def test_negative_position_returns_zero(self):
        self.assertAlmostEqual(_gas_cost_annual_pct(20.0, -100.0), 0.0)


# ===========================================================================
# 5. _net_apy_pct
# ===========================================================================

class TestNetApyPct(unittest.TestCase):
    def test_basic(self):
        # 20% - 3% IL - 2% gas = 15%
        self.assertAlmostEqual(_net_apy_pct(20.0, 3.0, 2.0), 15.0)

    def test_can_be_negative(self):
        self.assertLess(_net_apy_pct(2.0, 10.0, 5.0), 0.0)

    def test_no_deductions(self):
        self.assertAlmostEqual(_net_apy_pct(15.0, 0.0, 0.0), 15.0)

    def test_negative_il_treated_as_zero(self):
        v_neg = _net_apy_pct(15.0, -3.0, 0.0)
        v_zero = _net_apy_pct(15.0, 0.0, 0.0)
        self.assertAlmostEqual(v_neg, v_zero)

    def test_negative_gas_treated_as_zero(self):
        v_neg = _net_apy_pct(15.0, 0.0, -5.0)
        v_zero = _net_apy_pct(15.0, 0.0, 0.0)
        self.assertAlmostEqual(v_neg, v_zero)


# ===========================================================================
# 6. _roi_vs_hodl_pct
# ===========================================================================

class TestRoiVsHodl(unittest.TestCase):
    def test_outperforms(self):
        self.assertAlmostEqual(_roi_vs_hodl_pct(15.0, 5.0), 10.0)

    def test_equal(self):
        self.assertAlmostEqual(_roi_vs_hodl_pct(5.0, 5.0), 0.0)

    def test_underperforms(self):
        self.assertAlmostEqual(_roi_vs_hodl_pct(2.0, 5.0), -3.0)

    def test_zero_opportunity_cost(self):
        self.assertAlmostEqual(_roi_vs_hodl_pct(10.0, 0.0), 10.0)

    def test_negative_opp_cost_treated_as_zero(self):
        v1 = _roi_vs_hodl_pct(10.0, 0.0)
        v2 = _roi_vs_hodl_pct(10.0, -5.0)
        self.assertAlmostEqual(v1, v2)

    def test_deep_negative(self):
        self.assertAlmostEqual(_roi_vs_hodl_pct(-5.0, 10.0), -15.0)


# ===========================================================================
# 7. _label
# ===========================================================================

class TestLabelRoi(unittest.TestCase):
    def test_exceptional_at_15(self):
        self.assertEqual(_label(15.0), "EXCEPTIONAL_ROI")

    def test_exceptional_above_15(self):
        self.assertEqual(_label(30.0), "EXCEPTIONAL_ROI")

    def test_good_at_5(self):
        self.assertEqual(_label(5.0), "GOOD_ROI")

    def test_good_below_15(self):
        self.assertEqual(_label(14.9), "GOOD_ROI")

    def test_marginal_at_zero(self):
        self.assertEqual(_label(0.0), "MARGINAL")

    def test_marginal_below_5(self):
        self.assertEqual(_label(4.9), "MARGINAL")

    def test_underperforming_at_minus_1(self):
        self.assertEqual(_label(-1.0), "UNDERPERFORMING")

    def test_underperforming_at_minus_10(self):
        self.assertEqual(_label(-10.0), "UNDERPERFORMING")

    def test_trap_below_minus_10(self):
        self.assertEqual(_label(-10.1), "YIELD_FARMING_TRAP")

    def test_trap_very_negative(self):
        self.assertEqual(_label(-50.0), "YIELD_FARMING_TRAP")

    def test_all_labels_reachable(self):
        labels = {_label(v) for v in [20.0, 10.0, 2.0, -5.0, -15.0]}
        expected = {
            "EXCEPTIONAL_ROI", "GOOD_ROI", "MARGINAL",
            "UNDERPERFORMING", "YIELD_FARMING_TRAP"
        }
        self.assertEqual(labels, expected)


# ===========================================================================
# 8. _period_return_pct
# ===========================================================================

class TestPeriodReturnPct(unittest.TestCase):
    def test_full_year(self):
        # 52 weeks = full year → period return = APY
        self.assertAlmostEqual(_period_return_pct(10.0, 52.0), 10.0)

    def test_half_year(self):
        self.assertAlmostEqual(_period_return_pct(10.0, 26.0), 5.0)

    def test_zero_weeks(self):
        self.assertAlmostEqual(_period_return_pct(10.0, 0.0), 0.0)

    def test_negative_weeks(self):
        self.assertAlmostEqual(_period_return_pct(10.0, -5.0), 0.0)

    def test_zero_apy(self):
        self.assertAlmostEqual(_period_return_pct(0.0, 12.0), 0.0)

    def test_negative_apy(self):
        self.assertAlmostEqual(_period_return_pct(-10.0, 52.0), -10.0)


# ===========================================================================
# 9. _atomic_log
# ===========================================================================

class TestAtomicLogRoi(unittest.TestCase):
    def test_creates_file(self):
        path = _tmp_log()
        _atomic_log(path, {"x": 1})
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_appends(self):
        path = _tmp_log()
        _atomic_log(path, {"x": 1})
        _atomic_log(path, {"x": 2})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        os.unlink(path)

    def test_ring_buffer_cap(self):
        path = _tmp_log()
        for i in range(105):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)
        os.unlink(path)

    def test_truncates_oldest(self):
        path = _tmp_log()
        for i in range(105):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["i"], 5)
        os.unlink(path)

    def test_handles_corrupt_file(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("NOT JSON{{")
        _atomic_log(path, {"x": 42})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)


# ===========================================================================
# 10. ProtocolDeFiYieldFarmingROICalculator.calculate — integration
# ===========================================================================

class TestCalculatorIntegration(unittest.TestCase):
    def _run(self, **kwargs):
        p = _params(**kwargs)
        return ProtocolDeFiYieldFarmingROICalculator().calculate(
            p, config={"skip_log": True}
        )

    def test_returns_dict(self):
        self.assertIsInstance(self._run(), dict)

    def test_required_keys(self):
        result = self._run()
        for key in [
            "gross_apy_pct", "net_apy_pct", "token_adjusted_apy_pct",
            "roi_vs_hodl_pct", "label", "recommendations",
            "timestamp", "gas_cost_annual_pct", "period_net_return_pct",
            "period_opp_return_pct", "period_advantage_pct",
        ]:
            self.assertIn(key, result)

    def test_gross_apy_correct(self):
        result = self._run(base_yield_apy_pct=8.0, reward_token_apy_pct=12.0)
        self.assertAlmostEqual(result["gross_apy_pct"], 20.0)

    def test_token_adjusted_no_change(self):
        result = self._run(
            base_yield_apy_pct=8.0, reward_token_apy_pct=12.0,
            reward_token_price_usd=2.0, reward_token_entry_price_usd=2.0,
        )
        self.assertAlmostEqual(result["token_adjusted_apy_pct"], 20.0)

    def test_token_crash_reduces_apy(self):
        result = self._run(
            base_yield_apy_pct=8.0, reward_token_apy_pct=12.0,
            reward_token_price_usd=0.0, reward_token_entry_price_usd=2.0,
        )
        self.assertAlmostEqual(result["token_adjusted_apy_pct"], 8.0)

    def test_net_less_than_token_adjusted(self):
        result = self._run(il_estimate_pct=5.0, gas_cost_usd_per_week=50.0)
        self.assertLess(result["net_apy_pct"], result["token_adjusted_apy_pct"])

    def test_label_exceptional(self):
        result = self._run(
            base_yield_apy_pct=25.0, reward_token_apy_pct=10.0,
            reward_token_price_usd=2.0, reward_token_entry_price_usd=2.0,
            gas_cost_usd_per_week=0.0, il_estimate_pct=0.0,
            opportunity_cost_apy_pct=5.0, position_usd=100_000.0,
        )
        self.assertEqual(result["label"], "EXCEPTIONAL_ROI")

    def test_label_yield_farming_trap(self):
        result = self._run(
            base_yield_apy_pct=2.0, reward_token_apy_pct=5.0,
            reward_token_price_usd=0.1, reward_token_entry_price_usd=2.0,
            gas_cost_usd_per_week=100.0, il_estimate_pct=20.0,
            opportunity_cost_apy_pct=5.0, position_usd=1_000.0,
        )
        self.assertEqual(result["label"], "YIELD_FARMING_TRAP")

    def test_label_marginal(self):
        # Net APY just above opp cost
        result = self._run(
            base_yield_apy_pct=6.0, reward_token_apy_pct=0.0,
            reward_token_price_usd=1.0, reward_token_entry_price_usd=1.0,
            gas_cost_usd_per_week=0.0, il_estimate_pct=0.0,
            opportunity_cost_apy_pct=5.0, position_usd=100_000.0,
        )
        self.assertEqual(result["label"], "MARGINAL")

    def test_roi_vs_hodl_correct(self):
        result = self._run(
            base_yield_apy_pct=10.0, reward_token_apy_pct=0.0,
            reward_token_price_usd=1.0, reward_token_entry_price_usd=1.0,
            gas_cost_usd_per_week=0.0, il_estimate_pct=0.0,
            opportunity_cost_apy_pct=4.0, position_usd=100_000.0,
        )
        self.assertAlmostEqual(result["roi_vs_hodl_pct"], 6.0)

    def test_period_return_correct(self):
        result = self._run(
            base_yield_apy_pct=10.0, reward_token_apy_pct=0.0,
            reward_token_price_usd=1.0, reward_token_entry_price_usd=1.0,
            gas_cost_usd_per_week=0.0, il_estimate_pct=0.0,
            opportunity_cost_apy_pct=0.0, position_usd=100_000.0,
            weeks_farmed=26.0,
        )
        # 26/52 = 0.5 year → 5%
        self.assertAlmostEqual(result["period_net_return_pct"], 5.0)

    def test_recommendations_list(self):
        result = self._run()
        self.assertIsInstance(result["recommendations"], list)
        self.assertGreater(len(result["recommendations"]), 0)

    def test_protocol_passthrough(self):
        result = self._run(protocol="Aave V3")
        self.assertEqual(result["protocol"], "Aave V3")

    def test_logging_enabled(self):
        path = _tmp_log()
        p = _params()
        ProtocolDeFiYieldFarmingROICalculator().calculate(
            p, config={"log_path": path}
        )
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_logging_skipped(self):
        path = _tmp_log()
        p = _params()
        ProtocolDeFiYieldFarmingROICalculator().calculate(
            p, config={"log_path": path, "skip_log": True}
        )
        self.assertFalse(os.path.exists(path))

    def test_timestamp_present(self):
        result = self._run()
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)
        self.assertGreater(result["timestamp"], 0.0)

    def test_default_position_used_when_zero(self):
        p = _params(position_usd=0.0)
        result = ProtocolDeFiYieldFarmingROICalculator().calculate(
            p, config={"skip_log": True}
        )
        # Should use default (10_000) and not crash
        self.assertGreater(result["position_usd"], 0.0)

    def test_negative_gas_treated_as_zero(self):
        r_neg = self._run(gas_cost_usd_per_week=-50.0)
        r_zero = self._run(gas_cost_usd_per_week=0.0)
        self.assertAlmostEqual(r_neg["gas_cost_annual_pct"], r_zero["gas_cost_annual_pct"])

    def test_negative_il_treated_as_zero(self):
        r_neg = self._run(il_estimate_pct=-5.0)
        r_zero = self._run(il_estimate_pct=0.0)
        self.assertAlmostEqual(r_neg["net_apy_pct"], r_zero["net_apy_pct"])

    def test_gross_minus_costs_equals_net(self):
        # With no token price change, verify the accounting
        result = self._run(
            base_yield_apy_pct=10.0, reward_token_apy_pct=5.0,
            reward_token_price_usd=1.0, reward_token_entry_price_usd=1.0,
            gas_cost_usd_per_week=10.0, il_estimate_pct=2.0,
            position_usd=10_000.0,
        )
        expected_net = result["token_adjusted_apy_pct"] - result["il_estimate_pct"] - result["gas_cost_annual_pct"]
        self.assertAlmostEqual(result["net_apy_pct"], expected_net, places=5)

    def test_period_advantage_equals_net_minus_opp(self):
        result = self._run(weeks_farmed=26.0)
        expected = result["period_net_return_pct"] - result["period_opp_return_pct"]
        self.assertAlmostEqual(result["period_advantage_pct"], expected, places=5)


# ===========================================================================
# 11. Module-level calculate() shortcut
# ===========================================================================

class TestModuleLevelCalculate(unittest.TestCase):
    def test_returns_dict(self):
        self.assertIsInstance(calculate(_params(), config={"skip_log": True}), dict)

    def test_same_label_as_class(self):
        p = _params()
        r1 = calculate(p, config={"skip_log": True})
        r2 = ProtocolDeFiYieldFarmingROICalculator().calculate(p, config={"skip_log": True})
        self.assertEqual(r1["label"], r2["label"])

    def test_same_gross_apy(self):
        p = _params()
        r1 = calculate(p, config={"skip_log": True})
        r2 = ProtocolDeFiYieldFarmingROICalculator().calculate(p, config={"skip_log": True})
        self.assertAlmostEqual(r1["gross_apy_pct"], r2["gross_apy_pct"])


# ===========================================================================
# 12. Edge & boundary cases
# ===========================================================================

class TestEdgeCasesRoi(unittest.TestCase):
    def test_all_zeros_no_crash(self):
        p = _params(
            base_yield_apy_pct=0.0, reward_token_apy_pct=0.0,
            reward_token_price_usd=0.0, reward_token_entry_price_usd=0.0,
            gas_cost_usd_per_week=0.0, il_estimate_pct=0.0,
            opportunity_cost_apy_pct=0.0, weeks_farmed=0.0,
            position_usd=0.0,
        )
        result = ProtocolDeFiYieldFarmingROICalculator().calculate(
            p, config={"skip_log": True}
        )
        self.assertIn("label", result)

    def test_very_high_gas_causes_trap(self):
        p = _params(
            base_yield_apy_pct=5.0, reward_token_apy_pct=0.0,
            reward_token_price_usd=1.0, reward_token_entry_price_usd=1.0,
            gas_cost_usd_per_week=1000.0, il_estimate_pct=0.0,
            opportunity_cost_apy_pct=5.0, position_usd=1_000.0,
        )
        result = ProtocolDeFiYieldFarmingROICalculator().calculate(
            p, config={"skip_log": True}
        )
        self.assertEqual(result["label"], "YIELD_FARMING_TRAP")

    def test_missing_protocol_defaults_unknown(self):
        p = _params()
        del p["protocol"]
        result = ProtocolDeFiYieldFarmingROICalculator().calculate(
            p, config={"skip_log": True}
        )
        self.assertEqual(result["protocol"], "UNKNOWN")

    def test_high_il_reduces_net(self):
        r_low_il = ProtocolDeFiYieldFarmingROICalculator().calculate(
            _params(il_estimate_pct=1.0), config={"skip_log": True}
        )
        r_high_il = ProtocolDeFiYieldFarmingROICalculator().calculate(
            _params(il_estimate_pct=20.0), config={"skip_log": True}
        )
        self.assertGreater(r_low_il["net_apy_pct"], r_high_il["net_apy_pct"])

    def test_custom_log_path_in_constructor(self):
        path = _tmp_log()
        calc = ProtocolDeFiYieldFarmingROICalculator(log_path=path)
        calc.calculate(_params())
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_reward_token_ratio_in_result(self):
        result = ProtocolDeFiYieldFarmingROICalculator().calculate(
            _params(reward_token_price_usd=3.0, reward_token_entry_price_usd=2.0),
            config={"skip_log": True}
        )
        self.assertAlmostEqual(result["reward_token_price_ratio"], 1.5)

    def test_management_overhead_in_result(self):
        result = ProtocolDeFiYieldFarmingROICalculator().calculate(
            _params(management_overhead_hrs_per_week=3.0), config={"skip_log": True}
        )
        self.assertAlmostEqual(result["management_overhead_hrs_per_week"], 3.0)

    def test_position_usd_in_result(self):
        result = ProtocolDeFiYieldFarmingROICalculator().calculate(
            _params(position_usd=50_000.0), config={"skip_log": True}
        )
        self.assertAlmostEqual(result["position_usd"], 50_000.0)

    def test_weeks_farmed_in_result(self):
        result = ProtocolDeFiYieldFarmingROICalculator().calculate(
            _params(weeks_farmed=24.0), config={"skip_log": True}
        )
        self.assertAlmostEqual(result["weeks_farmed"], 24.0)


# ===========================================================================
# 13. Label-specific recommendation content
# ===========================================================================

class TestRecommendationContentRoi(unittest.TestCase):
    def _result_for_label(self, target_label: str) -> dict:
        if target_label == "EXCEPTIONAL_ROI":
            p = _params(
                base_yield_apy_pct=25.0, reward_token_apy_pct=10.0,
                gas_cost_usd_per_week=0.0, il_estimate_pct=0.0,
                opportunity_cost_apy_pct=5.0, position_usd=100_000.0,
            )
        elif target_label == "GOOD_ROI":
            p = _params(
                base_yield_apy_pct=12.0, reward_token_apy_pct=0.0,
                gas_cost_usd_per_week=0.0, il_estimate_pct=0.0,
                opportunity_cost_apy_pct=5.0, position_usd=100_000.0,
            )
        elif target_label == "MARGINAL":
            p = _params(
                base_yield_apy_pct=6.0, reward_token_apy_pct=0.0,
                gas_cost_usd_per_week=0.0, il_estimate_pct=0.0,
                opportunity_cost_apy_pct=5.0, position_usd=100_000.0,
            )
        elif target_label == "UNDERPERFORMING":
            p = _params(
                base_yield_apy_pct=3.0, reward_token_apy_pct=0.0,
                gas_cost_usd_per_week=0.0, il_estimate_pct=0.0,
                opportunity_cost_apy_pct=5.0, position_usd=100_000.0,
            )
        else:  # YIELD_FARMING_TRAP
            p = _params(
                base_yield_apy_pct=2.0, reward_token_apy_pct=5.0,
                reward_token_price_usd=0.1, reward_token_entry_price_usd=2.0,
                gas_cost_usd_per_week=100.0, il_estimate_pct=20.0,
                opportunity_cost_apy_pct=5.0, position_usd=1_000.0,
            )
        return ProtocolDeFiYieldFarmingROICalculator().calculate(
            p, config={"skip_log": True}
        )

    def test_exceptional_recommendation(self):
        r = self._result_for_label("EXCEPTIONAL_ROI")
        self.assertEqual(r["label"], "EXCEPTIONAL_ROI")
        combined = " ".join(r["recommendations"])
        self.assertIn("Exceptional", combined)

    def test_good_recommendation(self):
        r = self._result_for_label("GOOD_ROI")
        self.assertEqual(r["label"], "GOOD_ROI")
        combined = " ".join(r["recommendations"])
        self.assertIn("Good ROI", combined)

    def test_marginal_recommendation(self):
        r = self._result_for_label("MARGINAL")
        self.assertEqual(r["label"], "MARGINAL")
        combined = " ".join(r["recommendations"])
        self.assertIn("Marginal", combined)

    def test_underperforming_recommendation(self):
        r = self._result_for_label("UNDERPERFORMING")
        self.assertEqual(r["label"], "UNDERPERFORMING")
        combined = " ".join(r["recommendations"])
        self.assertIn("underperform", combined.lower())

    def test_trap_recommendation(self):
        r = self._result_for_label("YIELD_FARMING_TRAP")
        self.assertEqual(r["label"], "YIELD_FARMING_TRAP")
        combined = " ".join(r["recommendations"])
        self.assertIn("trap", combined.lower())

    def test_token_crash_warning(self):
        p = _params(
            reward_token_price_usd=0.5, reward_token_entry_price_usd=2.0,
            base_yield_apy_pct=20.0, gas_cost_usd_per_week=0.0,
            il_estimate_pct=0.0, opportunity_cost_apy_pct=5.0, position_usd=100_000.0,
        )
        r = ProtocolDeFiYieldFarmingROICalculator().calculate(p, config={"skip_log": True})
        combined = " ".join(r["recommendations"])
        self.assertIn("lost", combined.lower())

    def test_high_gas_warning(self):
        p = _params(
            gas_cost_usd_per_week=200.0, base_yield_apy_pct=30.0,
            position_usd=10_000.0, il_estimate_pct=0.0,
            opportunity_cost_apy_pct=5.0,
        )
        r = ProtocolDeFiYieldFarmingROICalculator().calculate(p, config={"skip_log": True})
        combined = " ".join(r["recommendations"])
        self.assertIn("Gas", combined)

    def test_high_il_warning(self):
        p = _params(il_estimate_pct=15.0, base_yield_apy_pct=30.0,
                    gas_cost_usd_per_week=0.0, opportunity_cost_apy_pct=5.0)
        r = ProtocolDeFiYieldFarmingROICalculator().calculate(p, config={"skip_log": True})
        combined = " ".join(r["recommendations"])
        self.assertIn("IL", combined)

    def test_high_overhead_warning(self):
        p = _params(
            management_overhead_hrs_per_week=8.0,
            base_yield_apy_pct=30.0, gas_cost_usd_per_week=0.0,
            il_estimate_pct=0.0, opportunity_cost_apy_pct=5.0,
        )
        r = ProtocolDeFiYieldFarmingROICalculator().calculate(p, config={"skip_log": True})
        combined = " ".join(r["recommendations"])
        self.assertIn("overhead", combined.lower())

    def test_all_recommendations_are_strings(self):
        for label in [
            "EXCEPTIONAL_ROI", "GOOD_ROI", "MARGINAL", "UNDERPERFORMING", "YIELD_FARMING_TRAP"
        ]:
            r = self._result_for_label(label)
            for rec in r["recommendations"]:
                self.assertIsInstance(rec, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
