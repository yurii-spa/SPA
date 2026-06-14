"""
Tests for MP-1122: DeFiProtocolYieldFeeStructureAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_yield_fee_structure_analyzer -v
Total: ≥ 110 test methods.
"""

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_yield_fee_structure_analyzer import (
    DeFiProtocolYieldFeeStructureAnalyzer,
    YieldFeeStructureReport,
    MAX_ENTRIES,
    DATA_FILE,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_report(
    gross_apy_pct: float = 10.0,
    protocol_fee_pct: float = 0.0,
    management_fee_annual_pct: float = 0.0,
    performance_fee_pct: float = 0.0,
    withdrawal_fee_pct: float = 0.0,
    holding_period_days: int = 365,
    position_size_usd: float = 10_000.0,
    protocol_name: str = "TestProtocol",
) -> YieldFeeStructureReport:
    ana = DeFiProtocolYieldFeeStructureAnalyzer()
    return ana.analyze(
        gross_apy_pct=gross_apy_pct,
        protocol_fee_pct=protocol_fee_pct,
        management_fee_annual_pct=management_fee_annual_pct,
        performance_fee_pct=performance_fee_pct,
        withdrawal_fee_pct=withdrawal_fee_pct,
        holding_period_days=holding_period_days,
        position_size_usd=position_size_usd,
        protocol_name=protocol_name,
    )


# ---------------------------------------------------------------------------
# 1. Zero-fee baseline
# ---------------------------------------------------------------------------

class TestZeroFees(unittest.TestCase):

    def setUp(self):
        self.r = make_report(gross_apy_pct=10.0)

    def test_yield_after_protocol_fee_equals_gross(self):
        self.assertAlmostEqual(self.r.yield_after_protocol_fee_pct, 10.0, places=6)

    def test_yield_after_management_fee_equals_gross(self):
        self.assertAlmostEqual(self.r.yield_after_management_fee_pct, 10.0, places=6)

    def test_yield_after_performance_fee_equals_gross(self):
        self.assertAlmostEqual(self.r.yield_after_performance_fee_pct, 10.0, places=6)

    def test_annualized_withdrawal_fee_zero(self):
        self.assertAlmostEqual(self.r.annualized_withdrawal_fee_pct, 0.0, places=6)

    def test_net_apy_equals_gross(self):
        self.assertAlmostEqual(self.r.net_apy_pct, 10.0, places=6)

    def test_total_fees_zero(self):
        self.assertAlmostEqual(self.r.total_fees_pct, 0.0, places=6)

    def test_fee_drag_ratio_zero(self):
        self.assertAlmostEqual(self.r.fee_drag_ratio, 0.0, places=6)

    def test_label_low_fee(self):
        self.assertEqual(self.r.fee_label, "LOW_FEE")


# ---------------------------------------------------------------------------
# 2. Protocol fee only
# ---------------------------------------------------------------------------

class TestProtocolFeeOnly(unittest.TestCase):

    def test_10pct_protocol_fee_on_10pct_gross(self):
        r = make_report(gross_apy_pct=10.0, protocol_fee_pct=10.0)
        self.assertAlmostEqual(r.yield_after_protocol_fee_pct, 9.0, places=6)

    def test_protocol_fee_50pct(self):
        r = make_report(gross_apy_pct=8.0, protocol_fee_pct=50.0)
        self.assertAlmostEqual(r.yield_after_protocol_fee_pct, 4.0, places=6)

    def test_protocol_fee_100pct_zeros_yield(self):
        r = make_report(gross_apy_pct=8.0, protocol_fee_pct=100.0)
        self.assertAlmostEqual(r.yield_after_protocol_fee_pct, 0.0, places=6)

    def test_protocol_fee_0pct(self):
        r = make_report(gross_apy_pct=5.0, protocol_fee_pct=0.0)
        self.assertAlmostEqual(r.yield_after_protocol_fee_pct, 5.0, places=6)

    def test_protocol_fee_does_not_alter_management_step_input_indirectly(self):
        r = make_report(gross_apy_pct=10.0, protocol_fee_pct=20.0)
        # y1 = 10*(1-0.2)=8; y2 = 8-0 = 8
        self.assertAlmostEqual(r.yield_after_management_fee_pct, 8.0, places=6)

    def test_protocol_fee_20pct_drag_moderate(self):
        # gross=5, proto_fee=20% → y1=4, net=4, fees=1, drag=0.2 → MODERATE
        r = make_report(gross_apy_pct=5.0, protocol_fee_pct=20.0)
        self.assertEqual(r.fee_label, "MODERATE_FEE")

    def test_protocol_fee_30pct_drag_high(self):
        # gross=5, proto_fee=30% → y1=3.5, net=3.5, fees=1.5, drag=0.3 → HIGH
        r = make_report(gross_apy_pct=5.0, protocol_fee_pct=30.0)
        self.assertEqual(r.fee_label, "HIGH_FEE")

    def test_protocol_fee_60pct_drag_excessive(self):
        r = make_report(gross_apy_pct=5.0, protocol_fee_pct=60.0)
        # drag=0.6 → EXCESSIVE
        self.assertEqual(r.fee_label, "EXCESSIVE_FEE")


# ---------------------------------------------------------------------------
# 3. Management fee only
# ---------------------------------------------------------------------------

class TestManagementFeeOnly(unittest.TestCase):

    def test_management_fee_reduces_yield(self):
        r = make_report(gross_apy_pct=10.0, management_fee_annual_pct=1.0)
        self.assertAlmostEqual(r.yield_after_management_fee_pct, 9.0, places=6)

    def test_management_fee_2pct(self):
        r = make_report(gross_apy_pct=10.0, management_fee_annual_pct=2.0)
        self.assertAlmostEqual(r.yield_after_management_fee_pct, 8.0, places=6)

    def test_management_fee_zero(self):
        r = make_report(gross_apy_pct=10.0, management_fee_annual_pct=0.0)
        self.assertAlmostEqual(r.yield_after_management_fee_pct, 10.0, places=6)

    def test_management_fee_equals_gross_nets_zero(self):
        # gross=5, mf=5 → y2=0 → net=0 → FEE_EXCEEDS_YIELD
        r = make_report(gross_apy_pct=5.0, management_fee_annual_pct=5.0)
        self.assertEqual(r.fee_label, "FEE_EXCEEDS_YIELD")

    def test_management_fee_exceeds_gross_net_negative(self):
        r = make_report(gross_apy_pct=5.0, management_fee_annual_pct=6.0)
        self.assertTrue(r.net_apy_pct < 0.0)
        self.assertEqual(r.fee_label, "FEE_EXCEEDS_YIELD")

    def test_management_fee_05pct_on_10pct_gross_low_drag(self):
        r = make_report(gross_apy_pct=10.0, management_fee_annual_pct=0.5)
        # drag = 0.5/10 = 0.05 < 0.10 → LOW_FEE
        self.assertEqual(r.fee_label, "LOW_FEE")


# ---------------------------------------------------------------------------
# 4. Performance fee only
# ---------------------------------------------------------------------------

class TestPerformanceFeeOnly(unittest.TestCase):

    def test_20pct_performance_fee_on_10pct_gross(self):
        r = make_report(gross_apy_pct=10.0, performance_fee_pct=20.0)
        self.assertAlmostEqual(r.yield_after_performance_fee_pct, 8.0, places=6)

    def test_performance_fee_50pct(self):
        r = make_report(gross_apy_pct=8.0, performance_fee_pct=50.0)
        self.assertAlmostEqual(r.yield_after_performance_fee_pct, 4.0, places=6)

    def test_performance_fee_100pct(self):
        r = make_report(gross_apy_pct=8.0, performance_fee_pct=100.0)
        self.assertAlmostEqual(r.yield_after_performance_fee_pct, 0.0, places=6)

    def test_performance_fee_zero(self):
        r = make_report(gross_apy_pct=8.0, performance_fee_pct=0.0)
        self.assertAlmostEqual(r.yield_after_performance_fee_pct, 8.0, places=6)

    def test_performance_fee_applied_after_management(self):
        # gross=10, mf=2 → y2=8; perf=25% → y3=8*0.75=6
        r = make_report(gross_apy_pct=10.0, management_fee_annual_pct=2.0, performance_fee_pct=25.0)
        self.assertAlmostEqual(r.yield_after_performance_fee_pct, 6.0, places=6)

    def test_performance_fee_20pct_low_drag(self):
        # gross=10, perf=20% → net=8, fees=2, drag=0.2 → MODERATE
        r = make_report(gross_apy_pct=10.0, performance_fee_pct=20.0)
        self.assertEqual(r.fee_label, "MODERATE_FEE")


# ---------------------------------------------------------------------------
# 5. Withdrawal fee annualisation
# ---------------------------------------------------------------------------

class TestWithdrawalFeeAnnualisation(unittest.TestCase):

    def test_withdrawal_fee_365_days(self):
        r = make_report(withdrawal_fee_pct=1.0, holding_period_days=365)
        self.assertAlmostEqual(r.annualized_withdrawal_fee_pct, 1.0, places=6)

    def test_withdrawal_fee_180_days(self):
        r = make_report(withdrawal_fee_pct=1.0, holding_period_days=180)
        expected = 1.0 * 365 / 180
        self.assertAlmostEqual(r.annualized_withdrawal_fee_pct, expected, places=6)

    def test_withdrawal_fee_30_days(self):
        r = make_report(withdrawal_fee_pct=0.5, holding_period_days=30)
        expected = 0.5 * 365 / 30
        self.assertAlmostEqual(r.annualized_withdrawal_fee_pct, expected, places=6)

    def test_withdrawal_fee_zero(self):
        r = make_report(withdrawal_fee_pct=0.0, holding_period_days=90)
        self.assertAlmostEqual(r.annualized_withdrawal_fee_pct, 0.0, places=6)

    def test_short_holding_amplifies_withdrawal_fee(self):
        r = make_report(withdrawal_fee_pct=1.0, holding_period_days=1)
        self.assertAlmostEqual(r.annualized_withdrawal_fee_pct, 365.0, places=4)

    def test_holding_period_1_day_floor(self):
        r = make_report(withdrawal_fee_pct=0.1, holding_period_days=0)
        # holding_period is clamped to at least 1
        self.assertAlmostEqual(r.annualized_withdrawal_fee_pct, 0.1 * 365, places=4)

    def test_withdrawal_fee_reduces_net_apy(self):
        r1 = make_report(gross_apy_pct=10.0, withdrawal_fee_pct=0.0, holding_period_days=365)
        r2 = make_report(gross_apy_pct=10.0, withdrawal_fee_pct=1.0, holding_period_days=365)
        self.assertGreater(r1.net_apy_pct, r2.net_apy_pct)


# ---------------------------------------------------------------------------
# 6. Full waterfall with all fees
# ---------------------------------------------------------------------------

class TestFullWaterfall(unittest.TestCase):

    def test_all_fees_combined(self):
        # gross=10, proto=10%, mf=0.5, perf=20%, wf=0.1, hp=365
        r = make_report(
            gross_apy_pct=10.0,
            protocol_fee_pct=10.0,
            management_fee_annual_pct=0.5,
            performance_fee_pct=20.0,
            withdrawal_fee_pct=0.1,
            holding_period_days=365,
        )
        # y1 = 10*(1-0.1) = 9.0
        self.assertAlmostEqual(r.yield_after_protocol_fee_pct, 9.0, places=6)
        # y2 = 9.0 - 0.5 = 8.5
        self.assertAlmostEqual(r.yield_after_management_fee_pct, 8.5, places=6)
        # y3 = 8.5 * (1-0.2) = 6.8
        self.assertAlmostEqual(r.yield_after_performance_fee_pct, 6.8, places=6)
        # ann_wf = 0.1 * 365/365 = 0.1
        self.assertAlmostEqual(r.annualized_withdrawal_fee_pct, 0.1, places=6)
        # net = 6.8 - 0.1 = 6.7
        self.assertAlmostEqual(r.net_apy_pct, 6.7, places=6)
        # total_fees = 10 - 6.7 = 3.3
        self.assertAlmostEqual(r.total_fees_pct, 3.3, places=6)
        # drag = 3.3/10 = 0.33 → HIGH
        self.assertAlmostEqual(r.fee_drag_ratio, 0.33, places=6)
        self.assertEqual(r.fee_label, "HIGH_FEE")

    def test_waterfall_order_matters(self):
        # Protocol fee reduces the base before management fee applies
        r = make_report(
            gross_apy_pct=10.0,
            protocol_fee_pct=50.0,
            management_fee_annual_pct=2.0,
        )
        # y1=5, y2=3
        self.assertAlmostEqual(r.yield_after_management_fee_pct, 3.0, places=6)

    def test_total_fees_equals_gross_minus_net(self):
        r = make_report(
            gross_apy_pct=12.0,
            protocol_fee_pct=15.0,
            management_fee_annual_pct=1.0,
            performance_fee_pct=20.0,
            withdrawal_fee_pct=0.2,
            holding_period_days=180,
        )
        self.assertAlmostEqual(r.total_fees_pct, r.gross_apy_pct - r.net_apy_pct, places=6)

    def test_fee_drag_ratio_consistency(self):
        r = make_report(
            gross_apy_pct=8.0,
            protocol_fee_pct=10.0,
            management_fee_annual_pct=0.5,
            performance_fee_pct=15.0,
            withdrawal_fee_pct=0.05,
            holding_period_days=365,
        )
        if abs(r.gross_apy_pct) > 1e-9:
            expected_drag = r.total_fees_pct / r.gross_apy_pct
            self.assertAlmostEqual(r.fee_drag_ratio, expected_drag, places=6)


# ---------------------------------------------------------------------------
# 7. Fee label boundaries
# ---------------------------------------------------------------------------

class TestFeeLabelBoundaries(unittest.TestCase):

    def setUp(self):
        self.ana = DeFiProtocolYieldFeeStructureAnalyzer()

    def _make_exact_drag(self, target_drag: float) -> YieldFeeStructureReport:
        """Craft a report where fee_drag_ratio ≈ target_drag."""
        gross = 100.0
        # Use management fee only for simplicity
        mf = gross * target_drag
        return make_report(gross_apy_pct=gross, management_fee_annual_pct=mf,
                           holding_period_days=365)

    def test_drag_just_below_low_threshold(self):
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=9.9)
        self.assertEqual(r.fee_label, "LOW_FEE")

    def test_drag_at_low_threshold(self):
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=10.0)
        # drag = 0.10 → MODERATE (0.10 is not < 0.10)
        self.assertEqual(r.fee_label, "MODERATE_FEE")

    def test_drag_just_above_low_threshold(self):
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=10.1)
        self.assertEqual(r.fee_label, "MODERATE_FEE")

    def test_drag_just_below_moderate_threshold(self):
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=24.9)
        self.assertEqual(r.fee_label, "MODERATE_FEE")

    def test_drag_at_moderate_threshold(self):
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=25.0)
        # 0.25 → HIGH
        self.assertEqual(r.fee_label, "HIGH_FEE")

    def test_drag_just_below_high_threshold(self):
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=49.9)
        self.assertEqual(r.fee_label, "HIGH_FEE")

    def test_drag_at_high_threshold(self):
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=50.0)
        self.assertEqual(r.fee_label, "EXCESSIVE_FEE")

    def test_drag_at_excessive_threshold(self):
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=100.0)
        # net=0 → FEE_EXCEEDS_YIELD
        self.assertEqual(r.fee_label, "FEE_EXCEEDS_YIELD")

    def test_drag_above_1_exceeds_yield(self):
        r = make_report(gross_apy_pct=5.0, management_fee_annual_pct=10.0)
        self.assertEqual(r.fee_label, "FEE_EXCEEDS_YIELD")

    def test_net_zero_exceeds_yield(self):
        # gross=10, mf=10 → net=0, total_fees=10, drag=1.0 → FEE_EXCEEDS_YIELD (drag>=1.0)
        r = make_report(gross_apy_pct=10.0, management_fee_annual_pct=10.0)
        self.assertEqual(r.fee_label, "FEE_EXCEEDS_YIELD")

    def test_net_negative_exceeds_yield(self):
        r = make_report(gross_apy_pct=5.0, management_fee_annual_pct=6.0)
        self.assertEqual(r.fee_label, "FEE_EXCEEDS_YIELD")


# ---------------------------------------------------------------------------
# 8. Zero gross APY edge cases
# ---------------------------------------------------------------------------

class TestZeroGrossAPY(unittest.TestCase):

    def test_gross_zero_fee_drag_zero(self):
        r = make_report(gross_apy_pct=0.0, protocol_fee_pct=10.0)
        self.assertAlmostEqual(r.fee_drag_ratio, 0.0, places=6)

    def test_gross_zero_net_apy_zero_or_negative(self):
        r = make_report(gross_apy_pct=0.0, management_fee_annual_pct=1.0)
        self.assertLessEqual(r.net_apy_pct, 0.0)

    def test_gross_zero_label_fee_exceeds(self):
        r = make_report(gross_apy_pct=0.0, management_fee_annual_pct=0.5)
        # net <= 0
        self.assertEqual(r.fee_label, "FEE_EXCEEDS_YIELD")

    def test_gross_zero_all_fees_zero_low_fee(self):
        r = make_report(gross_apy_pct=0.0)
        # drag=0.0 → LOW_FEE
        self.assertEqual(r.fee_label, "LOW_FEE")


# ---------------------------------------------------------------------------
# 9. Report field types and structure
# ---------------------------------------------------------------------------

class TestReportFieldTypes(unittest.TestCase):

    def setUp(self):
        self.r = make_report(
            gross_apy_pct=10.0,
            protocol_fee_pct=10.0,
            management_fee_annual_pct=0.5,
            performance_fee_pct=20.0,
            withdrawal_fee_pct=0.1,
            holding_period_days=365,
            position_size_usd=50_000.0,
            protocol_name="Aave",
        )

    def test_protocol_name_stored(self):
        self.assertEqual(self.r.protocol_name, "Aave")

    def test_gross_apy_pct_is_float(self):
        self.assertIsInstance(self.r.gross_apy_pct, float)

    def test_net_apy_pct_is_float(self):
        self.assertIsInstance(self.r.net_apy_pct, float)

    def test_fee_drag_ratio_is_float(self):
        self.assertIsInstance(self.r.fee_drag_ratio, float)

    def test_fee_label_is_str(self):
        self.assertIsInstance(self.r.fee_label, str)

    def test_advisory_is_list(self):
        self.assertIsInstance(self.r.advisory, list)

    def test_advisory_not_empty(self):
        self.assertGreater(len(self.r.advisory), 0)

    def test_generated_at_non_empty(self):
        self.assertIsInstance(self.r.generated_at, str)
        self.assertGreater(len(self.r.generated_at), 0)

    def test_holding_period_preserved(self):
        self.assertEqual(self.r.holding_period_days, 365)

    def test_position_size_preserved(self):
        self.assertAlmostEqual(self.r.position_size_usd, 50_000.0, places=2)


# ---------------------------------------------------------------------------
# 10. Advisory message content
# ---------------------------------------------------------------------------

class TestAdvisoryMessages(unittest.TestCase):

    def test_low_fee_advisory_mentions_efficient(self):
        r = make_report(gross_apy_pct=10.0, protocol_name="Compound")
        self.assertTrue(any("efficient" in m.lower() for m in r.advisory))

    def test_moderate_fee_advisory_mentions_protocol(self):
        r = make_report(gross_apy_pct=10.0, management_fee_annual_pct=1.5,
                        protocol_name="Morpho")
        self.assertTrue(any("Morpho" in m for m in r.advisory))

    def test_high_fee_advisory_contains_drag(self):
        r = make_report(gross_apy_pct=10.0, management_fee_annual_pct=3.5)
        self.assertTrue(any("high" in m.lower() or "drag" in m.lower() for m in r.advisory))

    def test_excessive_fee_advisory_warns_alternatives(self):
        r = make_report(gross_apy_pct=10.0, management_fee_annual_pct=6.0)
        advisory_text = " ".join(r.advisory).lower()
        self.assertTrue("consider" in advisory_text or "alternative" in advisory_text
                        or "negative" in advisory_text or "excessive" in advisory_text)

    def test_exceeds_yield_advisory_negative_mention(self):
        r = make_report(gross_apy_pct=5.0, management_fee_annual_pct=6.0)
        advisory_text = " ".join(r.advisory).lower()
        self.assertTrue("negative" in advisory_text or "exceed" in advisory_text)


# ---------------------------------------------------------------------------
# 11. Persistence — save_report / load_history
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def _temp_file(self) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        os.unlink(tmp.name)
        return Path(tmp.name)

    def test_save_creates_file(self):
        ana = DeFiProtocolYieldFeeStructureAnalyzer()
        r = make_report()
        tf = self._temp_file()
        try:
            ana.save_report(r, data_file=tf)
            self.assertTrue(tf.exists())
        finally:
            tf.unlink(missing_ok=True)

    def test_save_file_is_valid_json(self):
        ana = DeFiProtocolYieldFeeStructureAnalyzer()
        r = make_report()
        tf = self._temp_file()
        try:
            ana.save_report(r, data_file=tf)
            with open(tf) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
        finally:
            tf.unlink(missing_ok=True)

    def test_save_stores_one_entry(self):
        ana = DeFiProtocolYieldFeeStructureAnalyzer()
        r = make_report()
        tf = self._temp_file()
        try:
            ana.save_report(r, data_file=tf)
            data = json.loads(tf.read_text())
            self.assertEqual(len(data), 1)
        finally:
            tf.unlink(missing_ok=True)

    def test_save_accumulates_entries(self):
        ana = DeFiProtocolYieldFeeStructureAnalyzer()
        tf = self._temp_file()
        try:
            for _ in range(5):
                ana.save_report(make_report(), data_file=tf)
            data = json.loads(tf.read_text())
            self.assertEqual(len(data), 5)
        finally:
            tf.unlink(missing_ok=True)

    def test_ring_buffer_capped_at_max_entries(self):
        ana = DeFiProtocolYieldFeeStructureAnalyzer()
        tf = self._temp_file()
        try:
            for _ in range(MAX_ENTRIES + 10):
                ana.save_report(make_report(), data_file=tf)
            data = json.loads(tf.read_text())
            self.assertEqual(len(data), MAX_ENTRIES)
        finally:
            tf.unlink(missing_ok=True)

    def test_ring_buffer_keeps_most_recent(self):
        ana = DeFiProtocolYieldFeeStructureAnalyzer()
        tf = self._temp_file()
        try:
            for i in range(MAX_ENTRIES + 5):
                r = make_report(protocol_name=f"Proto{i}")
                ana.save_report(r, data_file=tf)
            data = json.loads(tf.read_text())
            # The last entry should be the most recent
            self.assertEqual(data[-1]["protocol_name"], f"Proto{MAX_ENTRIES + 4}")
        finally:
            tf.unlink(missing_ok=True)

    def test_load_history_missing_file(self):
        ana = DeFiProtocolYieldFeeStructureAnalyzer()
        self.assertEqual(ana.load_history(Path("/nonexistent/path.json")), [])

    def test_load_history_corrupt_file(self):
        ana = DeFiProtocolYieldFeeStructureAnalyzer()
        tf = self._temp_file()
        try:
            tf.write_text("not-valid-json")
            self.assertEqual(ana.load_history(tf), [])
        finally:
            tf.unlink(missing_ok=True)

    def test_entry_has_required_keys(self):
        ana = DeFiProtocolYieldFeeStructureAnalyzer()
        r = make_report()
        tf = self._temp_file()
        try:
            ana.save_report(r, data_file=tf)
            data = json.loads(tf.read_text())
            entry = data[0]
            for key in ("timestamp", "protocol_name", "gross_apy_pct", "net_apy_pct",
                        "fee_label", "fee_drag_ratio", "total_fees_pct"):
                self.assertIn(key, entry, f"Missing key: {key}")
        finally:
            tf.unlink(missing_ok=True)

    def test_entry_net_apy_matches_report(self):
        ana = DeFiProtocolYieldFeeStructureAnalyzer()
        r = make_report(gross_apy_pct=8.0, management_fee_annual_pct=1.0)
        tf = self._temp_file()
        try:
            ana.save_report(r, data_file=tf)
            data = json.loads(tf.read_text())
            self.assertAlmostEqual(data[0]["net_apy_pct"], r.net_apy_pct, places=5)
        finally:
            tf.unlink(missing_ok=True)

    def test_atomic_write_no_tmp_left_behind(self):
        ana = DeFiProtocolYieldFeeStructureAnalyzer()
        r = make_report()
        tf = self._temp_file()
        try:
            ana.save_report(r, data_file=tf)
            tmp = tf.with_suffix(".tmp")
            self.assertFalse(tmp.exists())
        finally:
            tf.unlink(missing_ok=True)

    def test_save_creates_parent_dirs(self):
        ana = DeFiProtocolYieldFeeStructureAnalyzer()
        with tempfile.TemporaryDirectory() as td:
            nested = Path(td) / "sub" / "dir" / "out.json"
            r = make_report()
            ana.save_report(r, data_file=nested)
            self.assertTrue(nested.exists())

    def test_entry_advisory_is_list(self):
        ana = DeFiProtocolYieldFeeStructureAnalyzer()
        r = make_report()
        tf = self._temp_file()
        try:
            ana.save_report(r, data_file=tf)
            data = json.loads(tf.read_text())
            self.assertIsInstance(data[0]["advisory"], list)
        finally:
            tf.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 12. Varied protocol names
# ---------------------------------------------------------------------------

class TestProtocolNames(unittest.TestCase):

    def test_aave_name_stored(self):
        r = make_report(protocol_name="Aave V3")
        self.assertEqual(r.protocol_name, "Aave V3")

    def test_compound_name_stored(self):
        r = make_report(protocol_name="Compound III")
        self.assertEqual(r.protocol_name, "Compound III")

    def test_morpho_name_in_advisory(self):
        r = make_report(protocol_name="Morpho Steakhouse", management_fee_annual_pct=3.0)
        self.assertTrue(any("Morpho Steakhouse" in m for m in r.advisory))

    def test_empty_name(self):
        r = make_report(protocol_name="")
        self.assertEqual(r.protocol_name, "")


# ---------------------------------------------------------------------------
# 13. Numerical precision and edge values
# ---------------------------------------------------------------------------

class TestNumericalEdgeCases(unittest.TestCase):

    def test_very_small_gross_apy(self):
        r = make_report(gross_apy_pct=0.001)
        self.assertIsInstance(r.net_apy_pct, float)

    def test_very_large_gross_apy(self):
        r = make_report(gross_apy_pct=1000.0, protocol_fee_pct=5.0)
        self.assertAlmostEqual(r.yield_after_protocol_fee_pct, 950.0, places=4)

    def test_holding_period_clamped_to_1(self):
        r = make_report(withdrawal_fee_pct=1.0, holding_period_days=-10)
        # clamped to 1
        self.assertAlmostEqual(r.annualized_withdrawal_fee_pct, 365.0, places=4)

    def test_fractional_fee_inputs(self):
        r = make_report(gross_apy_pct=10.0, protocol_fee_pct=7.5)
        self.assertAlmostEqual(r.yield_after_protocol_fee_pct, 10.0 * 0.925, places=6)

    def test_negative_protocol_fee_increases_yield(self):
        # Negative fees are a rebate/incentive; math should still work
        r = make_report(gross_apy_pct=10.0, protocol_fee_pct=-5.0)
        self.assertAlmostEqual(r.yield_after_protocol_fee_pct, 10.0 * 1.05, places=6)

    def test_net_apy_below_zero_label(self):
        r = make_report(gross_apy_pct=2.0, management_fee_annual_pct=5.0)
        self.assertTrue(r.net_apy_pct < 0.0)
        self.assertEqual(r.fee_label, "FEE_EXCEEDS_YIELD")

    def test_total_fees_can_be_negative_with_rebate(self):
        # Negative management fee = rebate
        r = make_report(gross_apy_pct=10.0, management_fee_annual_pct=-1.0)
        # y2 = 10 - (-1) = 11, total_fees = 10 - 11 = -1
        self.assertAlmostEqual(r.total_fees_pct, -1.0, places=6)

    def test_fee_drag_ratio_below_zero_with_rebate(self):
        r = make_report(gross_apy_pct=10.0, management_fee_annual_pct=-2.0)
        self.assertLess(r.fee_drag_ratio, 0.0)

    def test_holding_period_int_conversion(self):
        r = make_report(withdrawal_fee_pct=1.0, holding_period_days=100)
        expected = 1.0 * 365 / 100
        self.assertAlmostEqual(r.annualized_withdrawal_fee_pct, expected, places=6)


# ---------------------------------------------------------------------------
# 14. Integration: multiple scenarios with known expected labels
# ---------------------------------------------------------------------------

class TestKnownScenarios(unittest.TestCase):

    def test_aave_low_fee_scenario(self):
        # Typical Aave V3 USDC ~3.5% APY, 0 management, 0 performance, 0 withdrawal
        r = make_report(gross_apy_pct=3.5, protocol_name="Aave V3")
        self.assertEqual(r.fee_label, "LOW_FEE")

    def test_yearn_vault_moderate_fees(self):
        # Yearn V3: 10% perf, 0.5% mgmt, no withdrawal
        r = make_report(
            gross_apy_pct=8.0,
            protocol_fee_pct=0.0,
            management_fee_annual_pct=0.5,
            performance_fee_pct=10.0,
            withdrawal_fee_pct=0.0,
            holding_period_days=365,
            protocol_name="Yearn V3",
        )
        # y1=8, y2=7.5, y3=6.75, ann_wf=0, net=6.75, fees=1.25, drag=0.15625 → MODERATE
        self.assertEqual(r.fee_label, "MODERATE_FEE")

    def test_high_performance_fee_hedge_fund(self):
        # 2/20 fund: 2% mgmt, 20% perf
        r = make_report(
            gross_apy_pct=15.0,
            management_fee_annual_pct=2.0,
            performance_fee_pct=20.0,
        )
        # y1=15, y2=13, y3=10.4, net=10.4, fees=4.6, drag=0.306 → HIGH
        self.assertEqual(r.fee_label, "HIGH_FEE")

    def test_very_short_hold_excessive_withdrawal_drag(self):
        r = make_report(
            gross_apy_pct=5.0,
            withdrawal_fee_pct=1.0,
            holding_period_days=10,
        )
        # ann_wf = 1.0*365/10 = 36.5 → net hugely negative → EXCEEDS
        self.assertEqual(r.fee_label, "FEE_EXCEEDS_YIELD")

    def test_morpho_steakhouse_with_protocol_fee(self):
        # Morpho Steakhouse ~6.5%, 11% protocol fee → drag=0.11 → MODERATE
        r = make_report(
            gross_apy_pct=6.5,
            protocol_fee_pct=11.0,
            protocol_name="Morpho Steakhouse",
        )
        # y1=6.5*0.89=5.785, fees=0.715, drag=0.715/6.5≈0.11 → MODERATE
        self.assertEqual(r.fee_label, "MODERATE_FEE")

    def test_pendle_yt_high_fees(self):
        r = make_report(
            gross_apy_pct=20.0,
            protocol_fee_pct=10.0,
            performance_fee_pct=30.0,
            management_fee_annual_pct=1.0,
            protocol_name="Pendle YT",
        )
        # y1=18, y2=17, y3=11.9, net~11.9, fees~8.1, drag~0.405 → HIGH
        self.assertEqual(r.fee_label, "HIGH_FEE")


# ---------------------------------------------------------------------------
# 15. Additional coverage for fee_drag_ratio precision
# ---------------------------------------------------------------------------

class TestFeeDragRatio(unittest.TestCase):

    def test_drag_non_negative_standard_fees(self):
        r = make_report(gross_apy_pct=10.0, protocol_fee_pct=5.0, management_fee_annual_pct=0.5)
        self.assertGreaterEqual(r.fee_drag_ratio, 0.0)

    def test_drag_between_0_and_1_for_normal_case(self):
        r = make_report(gross_apy_pct=10.0, management_fee_annual_pct=2.0)
        self.assertGreaterEqual(r.fee_drag_ratio, 0.0)
        self.assertLessEqual(r.fee_drag_ratio, 1.0)

    def test_drag_above_1_exceeds_yield_label(self):
        r = make_report(gross_apy_pct=3.0, management_fee_annual_pct=4.0)
        self.assertGreater(r.fee_drag_ratio, 1.0)
        self.assertEqual(r.fee_label, "FEE_EXCEEDS_YIELD")

    def test_drag_exactly_025(self):
        # gross=100, mf=25 → fees=25, drag=0.25 → HIGH_FEE
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=25.0)
        self.assertAlmostEqual(r.fee_drag_ratio, 0.25, places=6)
        self.assertEqual(r.fee_label, "HIGH_FEE")

    def test_drag_exactly_010(self):
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=10.0)
        self.assertAlmostEqual(r.fee_drag_ratio, 0.10, places=6)
        self.assertEqual(r.fee_label, "MODERATE_FEE")

    def test_drag_exactly_050(self):
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=50.0)
        self.assertAlmostEqual(r.fee_drag_ratio, 0.50, places=6)
        self.assertEqual(r.fee_label, "EXCESSIVE_FEE")

    def test_drag_exactly_0(self):
        r = make_report(gross_apy_pct=10.0)
        self.assertAlmostEqual(r.fee_drag_ratio, 0.0, places=6)
        self.assertEqual(r.fee_label, "LOW_FEE")


# ---------------------------------------------------------------------------
# 16. Analyzer is stateless (multiple calls independent)
# ---------------------------------------------------------------------------

class TestStatelessAnalyzer(unittest.TestCase):

    def test_two_calls_independent(self):
        ana = DeFiProtocolYieldFeeStructureAnalyzer()
        r1 = ana.analyze(10.0, 10.0, 0.0, 0.0, 0.0, 365, 1000.0, "A")
        r2 = ana.analyze(20.0, 0.0, 0.0, 0.0, 0.0, 365, 1000.0, "B")
        self.assertAlmostEqual(r1.gross_apy_pct, 10.0, places=6)
        self.assertAlmostEqual(r2.gross_apy_pct, 20.0, places=6)

    def test_repeated_call_same_result(self):
        ana = DeFiProtocolYieldFeeStructureAnalyzer()
        r1 = ana.analyze(8.0, 5.0, 0.5, 20.0, 0.1, 365, 5000.0, "X")
        r2 = ana.analyze(8.0, 5.0, 0.5, 20.0, 0.1, 365, 5000.0, "X")
        self.assertAlmostEqual(r1.net_apy_pct, r2.net_apy_pct, places=8)
        self.assertEqual(r1.fee_label, r2.fee_label)

    def test_different_position_size_same_net_apy(self):
        ana = DeFiProtocolYieldFeeStructureAnalyzer()
        r1 = ana.analyze(10.0, 10.0, 0.5, 20.0, 0.0, 365, 1_000.0, "P")
        r2 = ana.analyze(10.0, 10.0, 0.5, 20.0, 0.0, 365, 1_000_000.0, "P")
        # position_size shouldn't affect net_apy
        self.assertAlmostEqual(r1.net_apy_pct, r2.net_apy_pct, places=8)


# ---------------------------------------------------------------------------
# 17. Extreme performance fee
# ---------------------------------------------------------------------------

class TestExtremePerformanceFee(unittest.TestCase):

    def test_perf_fee_99pct(self):
        r = make_report(gross_apy_pct=10.0, performance_fee_pct=99.0)
        self.assertAlmostEqual(r.yield_after_performance_fee_pct, 10.0 * 0.01, places=6)

    def test_perf_fee_100pct_yields_zero(self):
        r = make_report(gross_apy_pct=10.0, performance_fee_pct=100.0)
        self.assertAlmostEqual(r.yield_after_performance_fee_pct, 0.0, places=6)
        self.assertEqual(r.fee_label, "FEE_EXCEEDS_YIELD")

    def test_perf_fee_50pct_plus_mf(self):
        r = make_report(gross_apy_pct=10.0, performance_fee_pct=50.0,
                        management_fee_annual_pct=3.0)
        # y2 = 7, y3 = 3.5
        self.assertAlmostEqual(r.yield_after_performance_fee_pct, 3.5, places=6)


# ---------------------------------------------------------------------------
# 18. All fee labels are valid strings
# ---------------------------------------------------------------------------

class TestAllValidLabels(unittest.TestCase):

    VALID_LABELS = {
        "LOW_FEE", "MODERATE_FEE", "HIGH_FEE", "EXCESSIVE_FEE", "FEE_EXCEEDS_YIELD"
    }

    def _check_label(self, **kwargs):
        r = make_report(**kwargs)
        self.assertIn(r.fee_label, self.VALID_LABELS)

    def test_label_valid_no_fees(self):
        self._check_label(gross_apy_pct=10.0)

    def test_label_valid_moderate(self):
        self._check_label(gross_apy_pct=10.0, management_fee_annual_pct=1.5)

    def test_label_valid_high(self):
        self._check_label(gross_apy_pct=10.0, management_fee_annual_pct=3.5)

    def test_label_valid_excessive(self):
        self._check_label(gross_apy_pct=10.0, management_fee_annual_pct=6.0)

    def test_label_valid_exceeds(self):
        self._check_label(gross_apy_pct=5.0, management_fee_annual_pct=8.0)

    def test_label_valid_with_all_fees(self):
        self._check_label(gross_apy_pct=12.0, protocol_fee_pct=10.0,
                          management_fee_annual_pct=1.0, performance_fee_pct=20.0,
                          withdrawal_fee_pct=0.1, holding_period_days=180)

    def test_label_valid_zero_gross(self):
        self._check_label(gross_apy_pct=0.0)


# ---------------------------------------------------------------------------
# 19. Yield cascade monotonicity
# ---------------------------------------------------------------------------

class TestYieldCascadeMonotonicity(unittest.TestCase):

    def test_cascade_monotone_downward_positive_fees(self):
        r = make_report(
            gross_apy_pct=10.0,
            protocol_fee_pct=10.0,
            management_fee_annual_pct=0.5,
            performance_fee_pct=20.0,
            withdrawal_fee_pct=0.1,
            holding_period_days=365,
        )
        self.assertGreaterEqual(r.gross_apy_pct, r.yield_after_protocol_fee_pct)
        self.assertGreaterEqual(r.yield_after_protocol_fee_pct, r.yield_after_management_fee_pct)
        self.assertGreaterEqual(r.yield_after_management_fee_pct, r.yield_after_performance_fee_pct)
        self.assertGreaterEqual(r.yield_after_performance_fee_pct, r.net_apy_pct)

    def test_protocol_fee_reduces_yield(self):
        r = make_report(gross_apy_pct=10.0, protocol_fee_pct=5.0)
        self.assertLess(r.yield_after_protocol_fee_pct, r.gross_apy_pct)

    def test_management_fee_reduces_from_step1(self):
        r = make_report(gross_apy_pct=10.0, protocol_fee_pct=5.0, management_fee_annual_pct=1.0)
        self.assertLess(r.yield_after_management_fee_pct, r.yield_after_protocol_fee_pct)

    def test_performance_fee_reduces_from_step2(self):
        r = make_report(gross_apy_pct=10.0, performance_fee_pct=10.0)
        self.assertLess(r.yield_after_performance_fee_pct, r.yield_after_management_fee_pct)

    def test_withdrawal_fee_reduces_net_from_step3(self):
        r = make_report(gross_apy_pct=10.0, withdrawal_fee_pct=0.5, holding_period_days=365)
        self.assertLess(r.net_apy_pct, r.yield_after_performance_fee_pct)


# ---------------------------------------------------------------------------
# 20. Parametric sweep — fee_drag vs label
# ---------------------------------------------------------------------------

class TestParametricDragSweep(unittest.TestCase):

    def _drag(self, mf: float) -> float:
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=mf)
        return r.fee_drag_ratio

    def test_drag_5_is_low(self):
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=5.0)
        self.assertEqual(r.fee_label, "LOW_FEE")

    def test_drag_15_is_moderate(self):
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=15.0)
        self.assertEqual(r.fee_label, "MODERATE_FEE")

    def test_drag_35_is_high(self):
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=35.0)
        self.assertEqual(r.fee_label, "HIGH_FEE")

    def test_drag_70_is_excessive(self):
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=70.0)
        self.assertEqual(r.fee_label, "EXCESSIVE_FEE")

    def test_drag_110_exceeds_yield(self):
        r = make_report(gross_apy_pct=100.0, management_fee_annual_pct=110.0)
        self.assertEqual(r.fee_label, "FEE_EXCEEDS_YIELD")


if __name__ == "__main__":
    unittest.main()
