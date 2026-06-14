"""
Tests for spa_core/analytics/fee_impact_analyzer.py  (MP-642)
≥65 tests — stdlib unittest only (no external dependencies).
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
import unittest

# Make spa_core importable when run from project root or directly
_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.analytics.fee_impact_analyzer import (
    FeeImpactAnalyzer,
    FeeImpact,
    FeeStructure,
    MAX_ENTRIES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _zero_fee(protocol_id="proto"):
    return FeeStructure(
        protocol_id=protocol_id,
        management_fee_pct=0.0,
        performance_fee_pct=0.0,
        withdrawal_fee_pct=0.0,
        entry_fee_pct=0.0,
        gas_cost_usd=0.0,
    )


def _aave_like(protocol_id="aave"):
    return FeeStructure(
        protocol_id=protocol_id,
        management_fee_pct=0.000,
        performance_fee_pct=0.000,
        withdrawal_fee_pct=0.000,
        entry_fee_pct=0.000,
        gas_cost_usd=5.0,
    )


def _yearn_like(protocol_id="yearn"):
    return FeeStructure(
        protocol_id=protocol_id,
        management_fee_pct=0.02,
        performance_fee_pct=0.20,
        withdrawal_fee_pct=0.000,
        entry_fee_pct=0.000,
        gas_cost_usd=20.0,
    )


def _maple_like(protocol_id="maple"):
    return FeeStructure(
        protocol_id=protocol_id,
        management_fee_pct=0.005,
        performance_fee_pct=0.10,
        withdrawal_fee_pct=0.005,
        entry_fee_pct=0.001,
        gas_cost_usd=10.0,
    )


class BaseAnalyzerTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "fee_impact_analysis.json"
        self.a = FeeImpactAnalyzer(data_file=self.data_file)


# ---------------------------------------------------------------------------
# _grade
# ---------------------------------------------------------------------------

class TestGrade(BaseAnalyzerTest):

    def test_zero_bps_is_A(self):
        self.assertEqual(self.a._grade(0.0), "A")

    def test_under_10_bps_is_A(self):
        self.assertEqual(self.a._grade(9.99), "A")

    def test_exactly_10_bps_is_B(self):
        self.assertEqual(self.a._grade(10.0), "B")

    def test_15_bps_is_B(self):
        self.assertEqual(self.a._grade(15.0), "B")

    def test_24_99_bps_is_B(self):
        self.assertEqual(self.a._grade(24.99), "B")

    def test_exactly_25_bps_is_C(self):
        self.assertEqual(self.a._grade(25.0), "C")

    def test_30_bps_is_C(self):
        self.assertEqual(self.a._grade(30.0), "C")

    def test_49_99_bps_is_C(self):
        self.assertEqual(self.a._grade(49.99), "C")

    def test_exactly_50_bps_is_D(self):
        self.assertEqual(self.a._grade(50.0), "D")

    def test_100_bps_is_D(self):
        self.assertEqual(self.a._grade(100.0), "D")

    def test_500_bps_is_D(self):
        self.assertEqual(self.a._grade(500.0), "D")


# ---------------------------------------------------------------------------
# _recommendation
# ---------------------------------------------------------------------------

class TestRecommendation(BaseAnalyzerTest):

    def test_avoid_net_negative_grade_A(self):
        self.assertEqual(self.a._recommendation("A", -0.001, 0.05), "AVOID")

    def test_avoid_net_negative_grade_D(self):
        self.assertEqual(self.a._recommendation("D", -0.001, 0.05), "AVOID")

    def test_expensive_grade_D_net_positive(self):
        self.assertEqual(self.a._recommendation("D", 0.01, 0.05), "EXPENSIVE")

    def test_acceptable_grade_B(self):
        self.assertEqual(self.a._recommendation("B", 0.04, 0.05), "ACCEPTABLE")

    def test_acceptable_grade_C(self):
        self.assertEqual(self.a._recommendation("C", 0.04, 0.05), "ACCEPTABLE")

    def test_favorable_grade_A(self):
        self.assertEqual(self.a._recommendation("A", 0.05, 0.05), "FAVORABLE")

    def test_avoid_trumps_grade_A(self):
        self.assertEqual(self.a._recommendation("A", -0.01, 0.05), "AVOID")

    def test_favorable_net_apy_positive_grade_A(self):
        self.assertEqual(self.a._recommendation("A", 0.001, 0.10), "FAVORABLE")


# ---------------------------------------------------------------------------
# analyze: zero fees
# ---------------------------------------------------------------------------

class TestAnalyzeZeroFees(BaseAnalyzerTest):

    def test_zero_fees_net_equals_gross(self):
        impact = self.a.analyze(_zero_fee(), 0.05, 10_000, 365)
        self.assertAlmostEqual(impact.net_apy, 0.05, places=6)

    def test_zero_fees_no_costs(self):
        impact = self.a.analyze(_zero_fee(), 0.05, 10_000, 365)
        self.assertEqual(impact.total_fee_cost_usd, 0.0)
        self.assertEqual(impact.management_fee_cost_usd, 0.0)
        self.assertEqual(impact.performance_fee_cost_usd, 0.0)

    def test_zero_fees_gross_pnl_correct(self):
        impact = self.a.analyze(_zero_fee(), 0.10, 10_000, 365)
        self.assertAlmostEqual(impact.gross_pnl_usd, 1000.0, delta=0.01)

    def test_zero_fees_net_pnl_equals_gross_pnl(self):
        impact = self.a.analyze(_zero_fee(), 0.05, 10_000, 365)
        self.assertAlmostEqual(impact.net_pnl_usd, impact.gross_pnl_usd, places=4)

    def test_zero_fees_drag_zero_bps(self):
        impact = self.a.analyze(_zero_fee(), 0.05, 10_000, 365)
        self.assertEqual(impact.fee_drag_bps, 0.0)

    def test_zero_fees_grade_A(self):
        impact = self.a.analyze(_zero_fee(), 0.05, 10_000, 365)
        self.assertEqual(impact.grade, "A")

    def test_zero_fees_favorable(self):
        impact = self.a.analyze(_zero_fee(), 0.05, 10_000, 365)
        self.assertEqual(impact.recommendation, "FAVORABLE")

    def test_zero_fees_break_even_zero(self):
        impact = self.a.analyze(_zero_fee(), 0.05, 10_000, 365)
        self.assertEqual(impact.break_even_days, 0)


# ---------------------------------------------------------------------------
# analyze: management fee
# ---------------------------------------------------------------------------

class TestManagementFee(BaseAnalyzerTest):

    def test_management_fee_cost_correct_1yr(self):
        fs = FeeStructure("p", management_fee_pct=0.02, performance_fee_pct=0.0,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.0, gas_cost_usd=0.0)
        impact = self.a.analyze(fs, 0.10, 10_000, 365)
        self.assertAlmostEqual(impact.management_fee_cost_usd, 200.0, delta=0.01)

    def test_management_fee_prorated_half_year(self):
        fs = FeeStructure("p", management_fee_pct=0.02, performance_fee_pct=0.0,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.0, gas_cost_usd=0.0)
        impact = self.a.analyze(fs, 0.10, 10_000, 182)
        expected = 10_000 * 0.02 * (182 / 365)
        self.assertAlmostEqual(impact.management_fee_cost_usd, expected, delta=0.01)

    def test_management_fee_reduces_net_apy(self):
        fs = FeeStructure("p", management_fee_pct=0.01, performance_fee_pct=0.0,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.0, gas_cost_usd=0.0)
        impact = self.a.analyze(fs, 0.10, 10_000, 365)
        self.assertLess(impact.net_apy, 0.10)


# ---------------------------------------------------------------------------
# analyze: performance fee
# ---------------------------------------------------------------------------

class TestPerformanceFee(BaseAnalyzerTest):

    def test_performance_fee_20pct_of_gross(self):
        fs = FeeStructure("p", management_fee_pct=0.0, performance_fee_pct=0.20,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.0, gas_cost_usd=0.0)
        impact = self.a.analyze(fs, 0.10, 10_000, 365)
        self.assertAlmostEqual(impact.performance_fee_cost_usd, 200.0, delta=0.01)

    def test_performance_fee_not_negative_zero_apy(self):
        fs = FeeStructure("p", management_fee_pct=0.0, performance_fee_pct=0.30,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.0, gas_cost_usd=0.0)
        impact = self.a.analyze(fs, 0.0, 10_000, 365)
        self.assertEqual(impact.performance_fee_cost_usd, 0.0)

    def test_performance_fee_proportional_to_gross_profit(self):
        fs = FeeStructure("p", management_fee_pct=0.0, performance_fee_pct=0.10,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.0, gas_cost_usd=0.0)
        impact = self.a.analyze(fs, 0.08, 50_000, 365)
        expected_gross = 50_000 * 0.08
        self.assertAlmostEqual(impact.performance_fee_cost_usd, expected_gross * 0.10, delta=0.01)


# ---------------------------------------------------------------------------
# analyze: entry + withdrawal fee
# ---------------------------------------------------------------------------

class TestEntryWithdrawalFee(BaseAnalyzerTest):

    def test_entry_fee_one_time(self):
        fs = FeeStructure("p", management_fee_pct=0.0, performance_fee_pct=0.0,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.01, gas_cost_usd=0.0)
        impact = self.a.analyze(fs, 0.05, 10_000, 365)
        self.assertAlmostEqual(impact.entry_fee_cost_usd, 100.0, delta=0.01)

    def test_withdrawal_fee_one_time(self):
        fs = FeeStructure("p", management_fee_pct=0.0, performance_fee_pct=0.0,
                          withdrawal_fee_pct=0.005, entry_fee_pct=0.0, gas_cost_usd=0.0)
        impact = self.a.analyze(fs, 0.05, 10_000, 365)
        self.assertAlmostEqual(impact.withdrawal_fee_cost_usd, 50.0, delta=0.01)

    def test_entry_fee_same_regardless_of_hold_days(self):
        fs = FeeStructure("p", management_fee_pct=0.0, performance_fee_pct=0.0,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.01, gas_cost_usd=0.0)
        imp30 = self.a.analyze(fs, 0.05, 10_000, 30)
        imp365 = self.a.analyze(fs, 0.05, 10_000, 365)
        self.assertAlmostEqual(imp30.entry_fee_cost_usd, imp365.entry_fee_cost_usd, places=4)


# ---------------------------------------------------------------------------
# analyze: gas cost
# ---------------------------------------------------------------------------

class TestGasCost(BaseAnalyzerTest):

    def test_gas_doubled(self):
        fs = FeeStructure("p", management_fee_pct=0.0, performance_fee_pct=0.0,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.0, gas_cost_usd=15.0)
        impact = self.a.analyze(fs, 0.05, 10_000, 365)
        self.assertAlmostEqual(impact.gas_cost_total_usd, 30.0, places=6)

    def test_gas_zero_when_no_gas(self):
        impact = self.a.analyze(_zero_fee(), 0.05, 10_000, 365)
        self.assertEqual(impact.gas_cost_total_usd, 0.0)

    def test_gas_included_in_total_fees(self):
        fs = FeeStructure("p", management_fee_pct=0.0, performance_fee_pct=0.0,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.0, gas_cost_usd=10.0)
        impact = self.a.analyze(fs, 0.05, 10_000, 365)
        self.assertAlmostEqual(impact.total_fee_cost_usd, 20.0, delta=0.01)


# ---------------------------------------------------------------------------
# analyze: break_even_days
# ---------------------------------------------------------------------------

class TestBreakEvenDays(BaseAnalyzerTest):

    def test_break_even_zero_no_entry_costs(self):
        fs = FeeStructure("p", management_fee_pct=0.01, performance_fee_pct=0.0,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.0, gas_cost_usd=0.0)
        impact = self.a.analyze(fs, 0.10, 10_000, 365)
        self.assertEqual(impact.break_even_days, 0)

    def test_break_even_positive_with_gas(self):
        fs = FeeStructure("p", management_fee_pct=0.0, performance_fee_pct=0.0,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.0, gas_cost_usd=50.0)
        impact = self.a.analyze(fs, 0.10, 10_000, 365)
        self.assertGreater(impact.break_even_days, 0)
        self.assertLess(impact.break_even_days, 365)

    def test_break_even_zero_apy(self):
        fs = FeeStructure("p", management_fee_pct=0.0, performance_fee_pct=0.0,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.01, gas_cost_usd=0.0)
        impact = self.a.analyze(fs, 0.0, 10_000, 365)
        self.assertEqual(impact.break_even_days, 0)

    def test_break_even_decreases_with_higher_apy(self):
        fs = FeeStructure("p", management_fee_pct=0.0, performance_fee_pct=0.0,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.01, gas_cost_usd=10.0)
        imp_low = self.a.analyze(fs, 0.04, 10_000, 365)
        imp_high = self.a.analyze(fs, 0.20, 10_000, 365)
        self.assertGreater(imp_low.break_even_days, imp_high.break_even_days)


# ---------------------------------------------------------------------------
# analyze: net_pnl and net_apy
# ---------------------------------------------------------------------------

class TestNetPnlAndApy(BaseAnalyzerTest):

    def test_net_pnl_gross_minus_fees(self):
        fs = FeeStructure("p", management_fee_pct=0.01, performance_fee_pct=0.0,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.0, gas_cost_usd=0.0)
        impact = self.a.analyze(fs, 0.10, 10_000, 365)
        self.assertAlmostEqual(
            impact.net_pnl_usd,
            impact.gross_pnl_usd - impact.total_fee_cost_usd,
            delta=0.001
        )

    def test_net_apy_floor_minus_100(self):
        fs = FeeStructure("p", management_fee_pct=5.0, performance_fee_pct=0.0,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.0, gas_cost_usd=0.0)
        impact = self.a.analyze(fs, 0.01, 10_000, 365)
        self.assertGreaterEqual(impact.net_apy, -1.0)

    def test_net_apy_positive_low_fee(self):
        impact = self.a.analyze(_aave_like(), 0.05, 100_000, 365)
        self.assertGreater(impact.net_apy, 0)

    def test_hold_1_day(self):
        impact = self.a.analyze(_zero_fee(), 0.10, 10_000, 1)
        expected = 10_000 * 0.10 / 365
        self.assertAlmostEqual(impact.gross_pnl_usd, expected, delta=0.001)

    def test_hold_7_days(self):
        impact = self.a.analyze(_zero_fee(), 0.10, 10_000, 7)
        expected = 10_000 * 0.10 * (7 / 365)
        self.assertAlmostEqual(impact.gross_pnl_usd, expected, delta=0.001)

    def test_hold_30_days(self):
        impact = self.a.analyze(_zero_fee(), 0.10, 10_000, 30)
        expected = 10_000 * 0.10 * (30 / 365)
        self.assertAlmostEqual(impact.gross_pnl_usd, expected, delta=0.001)

    def test_hold_365_days(self):
        impact = self.a.analyze(_zero_fee(), 0.10, 10_000, 365)
        self.assertAlmostEqual(impact.gross_pnl_usd, 1000.0, delta=0.001)


# ---------------------------------------------------------------------------
# fee_drag_bps
# ---------------------------------------------------------------------------

class TestFeeDragBps(BaseAnalyzerTest):

    def test_drag_200_bps_for_2pct_mgmt(self):
        fs = FeeStructure("p", management_fee_pct=0.02, performance_fee_pct=0.0,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.0, gas_cost_usd=0.0)
        impact = self.a.analyze(fs, 0.10, 10_000, 365)
        self.assertAlmostEqual(impact.fee_drag_bps, 200.0, delta=0.01)

    def test_drag_higher_short_hold_with_entry_fee(self):
        fs = FeeStructure("p", management_fee_pct=0.0, performance_fee_pct=0.0,
                          withdrawal_fee_pct=0.0, entry_fee_pct=0.01, gas_cost_usd=0.0)
        imp30 = self.a.analyze(fs, 0.10, 10_000, 30)
        imp365 = self.a.analyze(fs, 0.10, 10_000, 365)
        self.assertGreater(imp30.fee_drag_bps, imp365.fee_drag_bps)


# ---------------------------------------------------------------------------
# compare_protocols
# ---------------------------------------------------------------------------

class TestCompareProtocols(BaseAnalyzerTest):

    def test_sorted_by_net_apy_descending(self):
        protocols = [_aave_like("aave"), _yearn_like("yearn"), _maple_like("maple")]
        ranked = self.a.compare_protocols(protocols, 0.08, 100_000, 365)
        self.assertEqual(len(ranked), 3)
        for i in range(len(ranked) - 1):
            self.assertGreaterEqual(ranked[i].net_apy, ranked[i + 1].net_apy)

    def test_zero_fee_first_in_ranking(self):
        protocols = [_yearn_like("yearn"), _zero_fee("zero")]
        ranked = self.a.compare_protocols(protocols, 0.08, 100_000, 365)
        self.assertEqual(ranked[0].protocol_id, "zero")

    def test_single_protocol(self):
        ranked = self.a.compare_protocols([_aave_like()], 0.05, 50_000, 180)
        self.assertEqual(len(ranked), 1)

    def test_empty_protocols(self):
        self.assertEqual(self.a.compare_protocols([], 0.05, 50_000, 180), [])


# ---------------------------------------------------------------------------
# Full scenario: 3 protocols
# ---------------------------------------------------------------------------

class TestFullScenario(BaseAnalyzerTest):

    def test_three_protocol_scenario_aave_first(self):
        ranked = self.a.compare_protocols(
            [_yearn_like("yearn"), _maple_like("maple"), _aave_like("aave")],
            gross_apy=0.10, capital_usd=100_000, hold_days=365
        )
        self.assertEqual(ranked[0].protocol_id, "aave")

    def test_all_positive_net_apy_high_gross(self):
        for fs in [_aave_like(), _yearn_like(), _maple_like()]:
            impact = self.a.analyze(fs, 0.20, 100_000, 365)
            self.assertGreater(impact.net_apy, 0)

    def test_yearn_higher_fee_drag_than_aave(self):
        imp_aave = self.a.analyze(_aave_like(), 0.10, 100_000, 365)
        imp_yearn = self.a.analyze(_yearn_like(), 0.10, 100_000, 365)
        self.assertGreater(imp_yearn.fee_drag_bps, imp_aave.fee_drag_bps)


# ---------------------------------------------------------------------------
# save_analysis / load_history / ring-buffer
# ---------------------------------------------------------------------------

class TestSaveAndLoad(BaseAnalyzerTest):

    def _impacts(self):
        return [self.a.analyze(_zero_fee(), 0.05, 10_000, 365)]

    def test_save_creates_file(self):
        self.a.save_analysis(self._impacts())
        self.assertTrue(self.data_file.exists())

    def test_save_valid_json(self):
        self.a.save_analysis(self._impacts())
        content = json.loads(self.data_file.read_text())
        self.assertIsInstance(content, list)
        self.assertEqual(len(content), 1)

    def test_entry_has_timestamp_and_analyses(self):
        self.a.save_analysis(self._impacts())
        entry = json.loads(self.data_file.read_text())[0]
        self.assertIn("timestamp", entry)
        self.assertIn("analyses", entry)

    def test_analyses_inner_fields(self):
        self.a.save_analysis(self._impacts())
        analysis = json.loads(self.data_file.read_text())[0]["analyses"][0]
        for key in ("protocol_id", "gross_apy", "net_apy", "fee_drag_bps", "grade",
                    "recommendation", "break_even_days", "total_fee_cost_usd"):
            self.assertIn(key, analysis)

    def test_ring_buffer_max_entries(self):
        for _ in range(MAX_ENTRIES + 5):
            self.a.save_analysis(self._impacts())
        history = json.loads(self.data_file.read_text())
        self.assertEqual(len(history), MAX_ENTRIES)

    def test_atomic_write_no_tmp_left(self):
        self.a.save_analysis(self._impacts())
        self.assertFalse(self.data_file.with_suffix(".tmp").exists())

    def test_load_history_missing_file(self):
        self.assertEqual(self.a.load_history(), [])

    def test_load_history_returns_list(self):
        self.a.save_analysis(self._impacts())
        history = self.a.load_history()
        self.assertIsInstance(history, list)
        self.assertEqual(len(history), 1)

    def test_load_history_corrupt_file(self):
        self.data_file.write_text("not valid json !!!")
        a = FeeImpactAnalyzer(data_file=self.data_file)
        self.assertEqual(a.load_history(), [])

    def test_save_multiple_accumulates(self):
        for _ in range(5):
            self.a.save_analysis([self.a.analyze(_aave_like(), 0.08, 50_000, 180)])
        self.assertEqual(len(self.a.load_history()), 5)


if __name__ == "__main__":
    unittest.main()
