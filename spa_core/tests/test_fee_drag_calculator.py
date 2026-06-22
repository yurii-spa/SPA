"""
Tests for MP-766 FeeDragCalculator.
65+ unit tests covering: zero fees, 100% fee scenarios, edge inputs,
break-even logic, advisory text, persistence, and FeeSpec defaults.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Allow running from project root or directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.fee_drag_calculator import (
    FeeDragCalculator,
    FeeDragReport,
    FeeSpec,
)

_EPS = 1e-6


def _zero_fees() -> FeeSpec:
    return FeeSpec(
        management_fee_bps=0.0,
        performance_fee_pct=0.0,
        gas_cost_usd=0.0,
        swap_fee_bps=0.0,
    )


def _typical_fees() -> FeeSpec:
    return FeeSpec(
        management_fee_bps=50.0,   # 0.50 % annual
        performance_fee_pct=20.0,  # 20 % of profit
        gas_cost_usd=15.0,
        swap_fee_bps=30.0,         # 0.30 % one-time
    )


class TestFeeSpecDefaults(unittest.TestCase):

    def test_default_management_fee_bps(self):
        fs = FeeSpec()
        self.assertEqual(fs.management_fee_bps, 0.0)

    def test_default_performance_fee_pct(self):
        fs = FeeSpec()
        self.assertEqual(fs.performance_fee_pct, 0.0)

    def test_default_gas_cost_usd(self):
        fs = FeeSpec()
        self.assertEqual(fs.gas_cost_usd, 0.0)

    def test_default_swap_fee_bps(self):
        fs = FeeSpec()
        self.assertEqual(fs.swap_fee_bps, 0.0)

    def test_custom_fee_spec(self):
        fs = FeeSpec(management_fee_bps=100, performance_fee_pct=10,
                     gas_cost_usd=5, swap_fee_bps=20)
        self.assertEqual(fs.management_fee_bps, 100)
        self.assertEqual(fs.performance_fee_pct, 10)
        self.assertEqual(fs.gas_cost_usd, 5)
        self.assertEqual(fs.swap_fee_bps, 20)


class TestZeroFees(unittest.TestCase):
    """With all fees = 0, net yield == gross yield and net APY == gross APY."""

    def setUp(self):
        self.calc = FeeDragCalculator()
        self.fees = _zero_fees()

    def test_zero_fees_net_yield_equals_gross(self):
        r = self.calc.calculate_drag(5.0, self.fees, 10_000.0, 365)
        self.assertAlmostEqual(r.net_yield_after_fees, r.gross_yield_usd, places=5)

    def test_zero_fees_net_apy_equals_gross(self):
        r = self.calc.calculate_drag(5.0, self.fees, 10_000.0, 365)
        self.assertAlmostEqual(r.net_apy, 5.0, places=5)

    def test_zero_fees_total_fees_usd_is_zero(self):
        r = self.calc.calculate_drag(5.0, self.fees, 10_000.0, 365)
        self.assertAlmostEqual(r.total_fees_usd, 0.0, places=8)

    def test_zero_fees_fee_drag_pct_zero(self):
        r = self.calc.calculate_drag(5.0, self.fees, 10_000.0, 365)
        self.assertAlmostEqual(r.fee_drag_pct, 0.0, places=5)

    def test_zero_fees_efficiency_score_100(self):
        r = self.calc.calculate_drag(5.0, self.fees, 10_000.0, 365)
        self.assertAlmostEqual(r.fee_efficiency_score, 100.0, places=5)

    def test_zero_fees_break_even_immediate(self):
        r = self.calc.calculate_drag(5.0, self.fees, 10_000.0, 30)
        # No fixed costs → break-even is 0.0 or at least very small
        self.assertIsNotNone(r.break_even_days)
        self.assertAlmostEqual(r.break_even_days, 0.0, places=4)

    def test_zero_fees_gross_yield_formula(self):
        cap = 20_000.0
        apy = 8.0
        days = 90
        r = self.calc.calculate_drag(apy, self.fees, cap, days)
        expected = cap * (apy / 100.0) * (days / 365.0)
        self.assertAlmostEqual(r.gross_yield_usd, expected, places=4)

    def test_zero_apy_zero_yield(self):
        r = self.calc.calculate_drag(0.0, self.fees, 10_000.0, 90)
        self.assertAlmostEqual(r.gross_yield_usd, 0.0, places=8)
        self.assertAlmostEqual(r.net_yield_after_fees, 0.0, places=8)

    def test_zero_capital_zero_yield(self):
        r = self.calc.calculate_drag(5.0, self.fees, 0.0, 90)
        self.assertAlmostEqual(r.gross_yield_usd, 0.0, places=8)
        self.assertAlmostEqual(r.net_yield_after_fees, 0.0, places=8)


class TestManagementFeeOnly(unittest.TestCase):

    def setUp(self):
        self.calc = FeeDragCalculator()

    def test_mgmt_fee_proportional_to_time(self):
        fees_90 = FeeSpec(management_fee_bps=100)
        fees_180 = FeeSpec(management_fee_bps=100)
        r90 = self.calc.calculate_drag(10.0, fees_90, 10_000.0, 90)
        r180 = self.calc.calculate_drag(10.0, fees_180, 10_000.0, 180)
        self.assertAlmostEqual(r180.management_fee_usd, 2 * r90.management_fee_usd, places=4)

    def test_mgmt_fee_proportional_to_capital(self):
        fees_a = FeeSpec(management_fee_bps=50)
        fees_b = FeeSpec(management_fee_bps=50)
        ra = self.calc.calculate_drag(10.0, fees_a, 10_000.0, 90)
        rb = self.calc.calculate_drag(10.0, fees_b, 20_000.0, 90)
        self.assertAlmostEqual(rb.management_fee_usd, 2 * ra.management_fee_usd, places=4)

    def test_mgmt_fee_correct_value(self):
        # 50 bps = 0.5%; capital $10k, 365 days → $50
        fees = FeeSpec(management_fee_bps=50)
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 365)
        self.assertAlmostEqual(r.management_fee_usd, 50.0, places=3)

    def test_mgmt_fee_reduces_net_apy(self):
        fees = FeeSpec(management_fee_bps=100)  # 1 %
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 365)
        # net APY should be ~4 %
        self.assertAlmostEqual(r.net_apy, 4.0, places=3)

    def test_mgmt_fee_zero_bps_no_cost(self):
        fees = FeeSpec(management_fee_bps=0.0)
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 90)
        self.assertAlmostEqual(r.management_fee_usd, 0.0, places=8)


class TestPerformanceFee(unittest.TestCase):

    def setUp(self):
        self.calc = FeeDragCalculator()

    def test_performance_fee_correct_value(self):
        fees = FeeSpec(performance_fee_pct=20.0)
        r = self.calc.calculate_drag(10.0, fees, 10_000.0, 365)
        expected_perf = r.gross_yield_usd * 0.20
        self.assertAlmostEqual(r.performance_fee_usd, expected_perf, places=4)

    def test_100pct_performance_fee_wipes_profit(self):
        fees = FeeSpec(performance_fee_pct=100.0)
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 365)
        # net yield ≈ 0 (only performance fee, no fixed costs)
        self.assertAlmostEqual(r.net_yield_after_fees, 0.0, places=4)
        self.assertAlmostEqual(r.fee_drag_pct, 100.0, places=4)

    def test_zero_performance_fee_no_cost(self):
        fees = FeeSpec(performance_fee_pct=0.0)
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 90)
        self.assertAlmostEqual(r.performance_fee_usd, 0.0, places=8)

    def test_performance_fee_scales_with_gross_yield(self):
        fees_a = FeeSpec(performance_fee_pct=20.0)
        fees_b = FeeSpec(performance_fee_pct=20.0)
        ra = self.calc.calculate_drag(5.0, fees_a, 10_000.0, 90)
        rb = self.calc.calculate_drag(10.0, fees_b, 10_000.0, 90)
        self.assertAlmostEqual(rb.performance_fee_usd, 2 * ra.performance_fee_usd, places=4)


class TestGasCostAndSwapFee(unittest.TestCase):

    def setUp(self):
        self.calc = FeeDragCalculator()

    def test_gas_cost_one_time(self):
        fees = FeeSpec(gas_cost_usd=50.0)
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 90)
        self.assertAlmostEqual(r.gas_cost_usd, 50.0, places=6)

    def test_gas_cost_zero(self):
        fees = FeeSpec(gas_cost_usd=0.0)
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 90)
        self.assertAlmostEqual(r.gas_cost_usd, 0.0, places=8)

    def test_swap_fee_correct_value(self):
        # 30 bps = 0.30 % on $10k = $30.00
        fees = FeeSpec(swap_fee_bps=30.0)
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 90)
        self.assertAlmostEqual(r.swap_fee_usd, 30.0, places=4)

    def test_swap_fee_not_time_proportional(self):
        fees_30 = FeeSpec(swap_fee_bps=30.0)
        fees_60 = FeeSpec(swap_fee_bps=30.0)
        r30 = self.calc.calculate_drag(5.0, fees_30, 10_000.0, 30)
        r60 = self.calc.calculate_drag(5.0, fees_60, 10_000.0, 60)
        # Swap fee should be identical regardless of holding period
        self.assertAlmostEqual(r30.swap_fee_usd, r60.swap_fee_usd, places=6)

    def test_swap_fee_proportional_to_capital(self):
        fees_a = FeeSpec(swap_fee_bps=50.0)
        fees_b = FeeSpec(swap_fee_bps=50.0)
        ra = self.calc.calculate_drag(5.0, fees_a, 5_000.0, 90)
        rb = self.calc.calculate_drag(5.0, fees_b, 10_000.0, 90)
        self.assertAlmostEqual(rb.swap_fee_usd, 2 * ra.swap_fee_usd, places=6)


class TestTotalFeesAndDrag(unittest.TestCase):

    def setUp(self):
        self.calc = FeeDragCalculator()

    def test_total_fees_sum_of_components(self):
        fees = _typical_fees()
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 90)
        expected_total = (
            r.management_fee_usd
            + r.performance_fee_usd
            + r.gas_cost_usd
            + r.swap_fee_usd
        )
        self.assertAlmostEqual(r.total_fees_usd, expected_total, places=5)

    def test_fee_drag_pct_bounded_0_to_100(self):
        fees = _typical_fees()
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 90)
        self.assertGreaterEqual(r.fee_drag_pct, 0.0)
        self.assertLessEqual(r.fee_drag_pct, 100.0)

    def test_efficiency_plus_drag_equals_100_when_drag_lt_100(self):
        fees = FeeSpec(management_fee_bps=50, performance_fee_pct=10)
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 365)
        if r.fee_drag_pct < 100.0:
            self.assertAlmostEqual(
                r.fee_drag_pct + r.fee_efficiency_score, 100.0, places=4
            )

    def test_efficiency_score_bounded_0_to_100(self):
        fees = FeeSpec(performance_fee_pct=200.0)  # absurd
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 90)
        self.assertGreaterEqual(r.fee_efficiency_score, 0.0)
        self.assertLessEqual(r.fee_efficiency_score, 100.0)

    def test_very_high_fees_drag_at_100(self):
        fees = FeeSpec(performance_fee_pct=100.0, management_fee_bps=1000.0)
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 365)
        self.assertAlmostEqual(r.fee_drag_pct, 100.0, places=2)
        self.assertAlmostEqual(r.fee_efficiency_score, 0.0, places=2)

    def test_net_yield_can_be_negative(self):
        fees = FeeSpec(gas_cost_usd=10_000.0)  # massive gas cost
        r = self.calc.calculate_drag(1.0, fees, 100.0, 10)
        self.assertLess(r.net_yield_after_fees, 0.0)

    def test_zero_apy_with_fixed_fees_all_drag(self):
        fees = FeeSpec(gas_cost_usd=10.0)
        r = self.calc.calculate_drag(0.0, fees, 10_000.0, 90)
        # gross yield=0, but we have gas cost → fee_drag_pct = 100
        self.assertAlmostEqual(r.fee_drag_pct, 100.0, places=4)

    def test_gross_apy_display_matches_input(self):
        r = self.calc.calculate_drag(7.25, _zero_fees(), 5_000.0, 60)
        self.assertAlmostEqual(r.gross_apy_display, 7.25, places=5)


class TestNetAPY(unittest.TestCase):

    def setUp(self):
        self.calc = FeeDragCalculator()

    def test_net_apy_lower_than_gross(self):
        r = self.calc.calculate_drag(5.0, _typical_fees(), 10_000.0, 90)
        self.assertLess(r.net_apy, r.gross_apy)

    def test_net_apy_zero_capital(self):
        r = self.calc.calculate_drag(5.0, _zero_fees(), 0.0, 90)
        self.assertAlmostEqual(r.net_apy, 0.0, places=8)

    def test_net_apy_small_capital_large_gas(self):
        fees = FeeSpec(gas_cost_usd=100.0)
        r = self.calc.calculate_drag(5.0, fees, 100.0, 365)
        # Gas cost $100 on $100 capital → net is deeply negative
        self.assertLess(r.net_apy, 0.0)

    def test_net_apy_positive_for_low_fees(self):
        fees = FeeSpec(management_fee_bps=5)  # 0.05 % annual — tiny fee
        r = self.calc.calculate_drag(5.0, fees, 50_000.0, 365)
        self.assertGreater(r.net_apy, 0.0)

    def test_net_apy_recovered_from_getter(self):
        r = self.calc.calculate_drag(6.0, _zero_fees(), 10_000.0, 180)
        self.assertAlmostEqual(self.calc.get_net_apy(), r.net_apy, places=6)

    def test_get_net_apy_before_any_call_returns_zero(self):
        fresh = FeeDragCalculator()
        self.assertEqual(fresh.get_net_apy(), 0.0)


class TestBreakEvenDays(unittest.TestCase):

    def setUp(self):
        self.calc = FeeDragCalculator()

    def test_break_even_zero_fixed_costs(self):
        # Only proportional fees → break-even on day 0
        fees = FeeSpec(management_fee_bps=50, performance_fee_pct=10)
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 90)
        self.assertIsNotNone(r.break_even_days)
        self.assertAlmostEqual(r.break_even_days, 0.0, places=4)

    def test_break_even_with_gas_cost(self):
        fees = FeeSpec(gas_cost_usd=100.0)
        r = self.calc.calculate_drag(10.0, fees, 10_000.0, 365)
        self.assertIsNotNone(r.break_even_days)
        self.assertGreater(r.break_even_days, 0.0)

    def test_break_even_proportional_to_fixed_costs(self):
        fees_a = FeeSpec(gas_cost_usd=50.0)
        fees_b = FeeSpec(gas_cost_usd=100.0)
        ra = self.calc.calculate_drag(5.0, fees_a, 10_000.0, 365)
        rb = self.calc.calculate_drag(5.0, fees_b, 10_000.0, 365)
        self.assertIsNotNone(ra.break_even_days)
        self.assertIsNotNone(rb.break_even_days)
        self.assertAlmostEqual(rb.break_even_days, 2 * ra.break_even_days, places=3)

    def test_break_even_none_when_perf_fee_100pct(self):
        # Performance fee 100% eats all yield → daily net ≤ 0 → impossible
        fees = FeeSpec(performance_fee_pct=100.0, gas_cost_usd=10.0)
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 90)
        self.assertIsNone(r.break_even_days)

    def test_break_even_none_zero_apy(self):
        fees = FeeSpec(gas_cost_usd=10.0)
        r = self.calc.calculate_drag(0.0, fees, 10_000.0, 90)
        self.assertIsNone(r.break_even_days)

    def test_break_even_none_zero_capital(self):
        fees = FeeSpec(gas_cost_usd=10.0)
        r = self.calc.calculate_drag(5.0, fees, 0.0, 90)
        self.assertIsNone(r.break_even_days)

    def test_get_break_even_days_matches_report(self):
        fees = FeeSpec(gas_cost_usd=50.0)
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 365)
        self.assertEqual(self.calc.get_break_even_days(), r.break_even_days)

    def test_get_break_even_days_before_any_call_is_none(self):
        fresh = FeeDragCalculator()
        self.assertIsNone(fresh.get_break_even_days())

    def test_break_even_less_than_holding_period_for_sufficient_apy(self):
        fees = FeeSpec(gas_cost_usd=1.0)  # tiny gas cost
        r = self.calc.calculate_drag(20.0, fees, 10_000.0, 365)
        self.assertIsNotNone(r.break_even_days)
        self.assertLess(r.break_even_days, 365)


class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.calc = FeeDragCalculator()

    def test_negative_capital_treated_as_zero(self):
        r = self.calc.calculate_drag(5.0, _zero_fees(), -5_000.0, 90)
        self.assertAlmostEqual(r.capital_usd, 0.0, places=4)
        self.assertAlmostEqual(r.gross_yield_usd, 0.0, places=8)

    def test_negative_apy_treated_as_zero(self):
        r = self.calc.calculate_drag(-5.0, _zero_fees(), 10_000.0, 90)
        self.assertAlmostEqual(r.gross_apy, 0.0, places=4)

    def test_holding_days_one(self):
        r = self.calc.calculate_drag(5.0, _zero_fees(), 10_000.0, 1)
        self.assertEqual(r.holding_days, 1)
        expected = 10_000.0 * (5.0 / 100.0) * (1.0 / 365.0)
        self.assertAlmostEqual(r.gross_yield_usd, expected, places=6)

    def test_holding_days_zero_treated_as_one(self):
        r = self.calc.calculate_drag(5.0, _zero_fees(), 10_000.0, 0)
        self.assertEqual(r.holding_days, 1)

    def test_holding_days_large(self):
        r = self.calc.calculate_drag(5.0, _zero_fees(), 10_000.0, 3650)
        # 10 years at 5 % on $10k = $5000
        self.assertAlmostEqual(r.gross_yield_usd, 5000.0, places=2)

    def test_very_large_capital(self):
        r = self.calc.calculate_drag(5.0, _zero_fees(), 1_000_000.0, 365)
        self.assertAlmostEqual(r.gross_yield_usd, 50_000.0, places=2)

    def test_negative_gas_cost_clamped_to_zero(self):
        fees = FeeSpec(gas_cost_usd=-100.0)
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 90)
        self.assertAlmostEqual(r.gas_cost_usd, 0.0, places=6)

    def test_all_fields_present_in_report(self):
        r = self.calc.calculate_drag(5.0, _typical_fees(), 10_000.0, 90)
        required = [
            "gross_apy", "capital_usd", "holding_days", "fees",
            "gross_yield_usd", "management_fee_usd", "performance_fee_usd",
            "gas_cost_usd", "swap_fee_usd", "total_fees_usd",
            "net_yield_after_fees", "net_apy", "fee_drag_pct",
            "fee_efficiency_score", "break_even_days", "advisory", "generated_at",
        ]
        for field in required:
            self.assertTrue(hasattr(r, field), f"Missing field: {field}")

    def test_generated_at_is_string(self):
        r = self.calc.calculate_drag(5.0, _zero_fees(), 10_000.0, 90)
        self.assertIsInstance(r.generated_at, str)
        self.assertTrue(len(r.generated_at) > 0)

    def test_advisory_is_list_of_strings(self):
        r = self.calc.calculate_drag(5.0, _typical_fees(), 10_000.0, 90)
        self.assertIsInstance(r.advisory, list)
        for item in r.advisory:
            self.assertIsInstance(item, str)

    def test_advisory_not_empty(self):
        r = self.calc.calculate_drag(5.0, _typical_fees(), 10_000.0, 90)
        self.assertGreater(len(r.advisory), 0)

    def test_last_report_updated_on_each_call(self):
        self.calc.calculate_drag(5.0, _zero_fees(), 10_000.0, 30)
        r2 = self.calc.calculate_drag(8.0, _zero_fees(), 20_000.0, 60)
        self.assertAlmostEqual(self.calc.get_net_apy(), r2.net_apy, places=6)


class TestAdvisoryContent(unittest.TestCase):

    def setUp(self):
        self.calc = FeeDragCalculator()

    def _advisory_str(self, r: FeeDragReport) -> str:
        return " ".join(r.advisory)

    def test_low_drag_advisory_present(self):
        fees = FeeSpec(management_fee_bps=5)
        r = self.calc.calculate_drag(10.0, fees, 10_000.0, 365)
        self.assertIn("Low fee drag", self._advisory_str(r))

    def test_high_drag_advisory_present(self):
        fees = FeeSpec(performance_fee_pct=80.0, gas_cost_usd=200.0)
        r = self.calc.calculate_drag(1.0, fees, 1_000.0, 90)
        text = self._advisory_str(r)
        self.assertTrue(
            "High fee drag" in text or "100 %" in text or "Fees consume" in text
        )

    def test_advisory_mentions_net_apy(self):
        fees = FeeSpec(management_fee_bps=50)
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 365)
        text = self._advisory_str(r)
        self.assertTrue("Net APY" in text or "net_apy" in text.lower() or "APY" in text)

    def test_advisory_efficiency_score_present(self):
        r = self.calc.calculate_drag(5.0, _typical_fees(), 10_000.0, 90)
        text = self._advisory_str(r)
        self.assertTrue(
            "EFFICIENT" in text or "MODERATE" in text or "POOR" in text
        )

    def test_advisory_break_even_mentioned_with_fixed_costs(self):
        fees = FeeSpec(gas_cost_usd=50.0)
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 365)
        text = self._advisory_str(r)
        self.assertTrue(
            "break-even" in text.lower() or "Break-even" in text
        )

    def test_advisory_negative_yield_flagged(self):
        fees = FeeSpec(gas_cost_usd=100_000.0)
        r = self.calc.calculate_drag(1.0, fees, 100.0, 10)
        text = self._advisory_str(r)
        self.assertTrue("negative" in text.lower() or "loss" in text.lower())

    def test_advisory_break_even_impossible_mentioned(self):
        fees = FeeSpec(performance_fee_pct=100.0, gas_cost_usd=10.0)
        r = self.calc.calculate_drag(5.0, fees, 10_000.0, 90)
        text = self._advisory_str(r)
        self.assertIn("impossible", text.lower())


class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.calc = FeeDragCalculator()
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "fee_drag_test.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_save_creates_file(self):
        r = self.calc.calculate_drag(5.0, _zero_fees(), 10_000.0, 90)
        self.calc.save_report(r, self.data_file)
        self.assertTrue(self.data_file.exists())

    def test_save_creates_valid_json_list(self):
        r = self.calc.calculate_drag(5.0, _zero_fees(), 10_000.0, 90)
        self.calc.save_report(r, self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_save_multiple_appends(self):
        for apy in [3.0, 5.0, 8.0]:
            r = self.calc.calculate_drag(apy, _zero_fees(), 10_000.0, 90)
            self.calc.save_report(r, self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), 3)

    def test_ring_buffer_capped_at_100(self):
        for i in range(105):
            r = self.calc.calculate_drag(float(i % 10 + 1), _zero_fees(), 1000.0, 30)
            self.calc.save_report(r, self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertLessEqual(len(data), 100)

    def test_load_history_empty_when_file_missing(self):
        missing = Path(self.tmp_dir) / "nonexistent.json"
        result = self.calc.load_history(missing)
        self.assertEqual(result, [])

    def test_load_history_returns_saved_entries(self):
        r = self.calc.calculate_drag(5.0, _zero_fees(), 10_000.0, 90)
        self.calc.save_report(r, self.data_file)
        loaded = self.calc.load_history(self.data_file)
        self.assertEqual(len(loaded), 1)
        self.assertIn("net_apy", loaded[0])

    def test_load_history_corrupt_json_returns_empty(self):
        self.data_file.write_text("NOT VALID JSON")
        result = self.calc.load_history(self.data_file)
        self.assertEqual(result, [])

    def test_atomic_write_no_tmp_file_after_save(self):
        r = self.calc.calculate_drag(5.0, _zero_fees(), 10_000.0, 90)
        self.calc.save_report(r, self.data_file)
        tmp_file = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp_file.exists())

    def test_save_entry_has_required_keys(self):
        r = self.calc.calculate_drag(5.0, _typical_fees(), 10_000.0, 90)
        self.calc.save_report(r, self.data_file)
        entry = json.loads(self.data_file.read_text())[0]
        for key in ["timestamp", "gross_apy", "net_apy", "total_fees_usd",
                    "fee_drag_pct", "fee_efficiency_score"]:
            self.assertIn(key, entry, f"Missing key: {key}")

    def test_save_directory_created_if_missing(self):
        nested_path = Path(self.tmp_dir) / "subdir" / "fee_drag.json"
        r = self.calc.calculate_drag(5.0, _zero_fees(), 10_000.0, 90)
        self.calc.save_report(r, nested_path)
        self.assertTrue(nested_path.exists())


class TestNoImportForbidden(unittest.TestCase):

    def test_no_numpy(self):
        import spa_core.analytics.fee_drag_calculator as mod
        source = Path(mod.__file__).read_text()
        self.assertNotIn("import numpy", source)
        self.assertNotIn("import pandas", source)
        self.assertNotIn("import scipy", source)

    def test_no_llm_call(self):
        import spa_core.analytics.fee_drag_calculator as mod
        source = Path(mod.__file__).read_text()
        self.assertNotIn("anthropic", source.lower())
        self.assertNotIn("openai", source.lower())

    def test_no_direct_open_w_on_data_files(self):
        import spa_core.analytics.fee_drag_calculator as mod
        source = Path(mod.__file__).read_text()
        # Ensure atomic pattern (os.replace) is used
        self.assertIn("os.replace", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
