"""
Tests for MP-684: LiquidationPriceMonitor
≥65 unittest tests. Pure stdlib (unittest only).
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from spa_core.analytics.liquidation_price_monitor import (
    LiquidationPriceMonitor,
    LendingPosition,
    LiquidationRiskReport,
    MAX_ENTRIES,
)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _pos(
    position_id="p1",
    protocol="Aave V3",
    collateral_token="ETH",
    debt_token="USDC",
    collateral_amount=10.0,
    collateral_price_usd=2000.0,
    debt_amount_usd=12000.0,
    liquidation_threshold=0.80,
    current_timestamp=0.0,
):
    return LendingPosition(
        position_id=position_id,
        protocol=protocol,
        collateral_token=collateral_token,
        debt_token=debt_token,
        collateral_amount=collateral_amount,
        collateral_price_usd=collateral_price_usd,
        debt_amount_usd=debt_amount_usd,
        liquidation_threshold=liquidation_threshold,
        current_timestamp=current_timestamp,
    )


# ─── TestCollateralValue ─────────────────────────────────────────────────────

class TestCollateralValue(unittest.TestCase):
    def setUp(self):
        self.mon = LiquidationPriceMonitor()

    def test_collateral_value_basic(self):
        p = _pos(collateral_amount=10.0, collateral_price_usd=2000.0)
        self.assertAlmostEqual(self.mon._collateral_value_usd(p), 20000.0)

    def test_collateral_value_fractional_amount(self):
        p = _pos(collateral_amount=0.5, collateral_price_usd=3000.0)
        self.assertAlmostEqual(self.mon._collateral_value_usd(p), 1500.0)

    def test_collateral_value_zero_amount(self):
        p = _pos(collateral_amount=0.0, collateral_price_usd=2000.0)
        self.assertAlmostEqual(self.mon._collateral_value_usd(p), 0.0)

    def test_collateral_value_zero_price(self):
        p = _pos(collateral_amount=10.0, collateral_price_usd=0.0)
        self.assertAlmostEqual(self.mon._collateral_value_usd(p), 0.0)

    def test_collateral_value_large(self):
        p = _pos(collateral_amount=100.0, collateral_price_usd=50000.0)
        self.assertAlmostEqual(self.mon._collateral_value_usd(p), 5_000_000.0)


# ─── TestCurrentLTV ──────────────────────────────────────────────────────────

class TestCurrentLTV(unittest.TestCase):
    def setUp(self):
        self.mon = LiquidationPriceMonitor()

    def test_ltv_standard(self):
        # debt=12000, col_val=20000 → 0.6
        self.assertAlmostEqual(self.mon._current_ltv(12000.0, 20000.0), 0.6)

    def test_ltv_zero_collateral_returns_one(self):
        self.assertAlmostEqual(self.mon._current_ltv(1000.0, 0.0), 1.0)

    def test_ltv_negative_collateral_returns_one(self):
        self.assertAlmostEqual(self.mon._current_ltv(1000.0, -100.0), 1.0)

    def test_ltv_zero_debt(self):
        self.assertAlmostEqual(self.mon._current_ltv(0.0, 20000.0), 0.0)

    def test_ltv_half(self):
        self.assertAlmostEqual(self.mon._current_ltv(5000.0, 10000.0), 0.5)

    def test_ltv_above_one(self):
        # under-collateralised
        self.assertAlmostEqual(self.mon._current_ltv(15000.0, 10000.0), 1.5)


# ─── TestHealthFactor ────────────────────────────────────────────────────────

class TestHealthFactor(unittest.TestCase):
    def setUp(self):
        self.mon = LiquidationPriceMonitor()

    def test_hf_zero_debt_returns_999(self):
        self.assertAlmostEqual(self.mon._health_factor(20000.0, 0.80, 0.0), 999.0)

    def test_hf_negative_debt_returns_999(self):
        self.assertAlmostEqual(self.mon._health_factor(20000.0, 0.80, -100.0), 999.0)

    def test_hf_standard(self):
        # 20000 * 0.80 / 12000 = 1.3333...
        self.assertAlmostEqual(
            self.mon._health_factor(20000.0, 0.80, 12000.0), 4 / 3, places=6
        )

    def test_hf_exactly_one(self):
        # collateral_val=10000, thresh=0.80, debt=8000 → 1.0
        self.assertAlmostEqual(self.mon._health_factor(10000.0, 0.80, 8000.0), 1.0)

    def test_hf_high_threshold_high_debt(self):
        # 50000 * 0.75 / 37500 = 1.0
        self.assertAlmostEqual(self.mon._health_factor(50000.0, 0.75, 37500.0), 1.0)

    def test_hf_safe_position(self):
        # 100000 * 0.80 / 10000 = 8.0
        self.assertAlmostEqual(self.mon._health_factor(100000.0, 0.80, 10000.0), 8.0)


# ─── TestLiquidationPrice ────────────────────────────────────────────────────

class TestLiquidationPrice(unittest.TestCase):
    def setUp(self):
        self.mon = LiquidationPriceMonitor()

    def test_liq_price_formula(self):
        # debt=12000, amount=10, thresh=0.80 → 12000/(10*0.80)=1500
        p = _pos(collateral_amount=10.0, debt_amount_usd=12000.0,
                 liquidation_threshold=0.80)
        self.assertAlmostEqual(self.mon._liquidation_price_usd(p), 1500.0)

    def test_liq_price_zero_amount_returns_zero(self):
        p = _pos(collateral_amount=0.0, debt_amount_usd=12000.0,
                 liquidation_threshold=0.80)
        self.assertAlmostEqual(self.mon._liquidation_price_usd(p), 0.0)

    def test_liq_price_zero_threshold_returns_zero(self):
        p = _pos(collateral_amount=10.0, debt_amount_usd=12000.0,
                 liquidation_threshold=0.0)
        self.assertAlmostEqual(self.mon._liquidation_price_usd(p), 0.0)

    def test_liq_price_zero_debt(self):
        p = _pos(collateral_amount=10.0, debt_amount_usd=0.0,
                 liquidation_threshold=0.80)
        self.assertAlmostEqual(self.mon._liquidation_price_usd(p), 0.0)

    def test_liq_price_high_threshold(self):
        # debt=9000, amount=10, thresh=0.90 → 9000/9 = 1000
        p = _pos(collateral_amount=10.0, debt_amount_usd=9000.0,
                 liquidation_threshold=0.90)
        self.assertAlmostEqual(self.mon._liquidation_price_usd(p), 1000.0)

    def test_liq_price_large_position(self):
        # debt=800000, amount=100, thresh=0.80 → 800000/80 = 10000
        p = _pos(collateral_amount=100.0, debt_amount_usd=800000.0,
                 liquidation_threshold=0.80)
        self.assertAlmostEqual(self.mon._liquidation_price_usd(p), 10000.0)


# ─── TestPriceDropToLiq ──────────────────────────────────────────────────────

class TestPriceDropToLiq(unittest.TestCase):
    def setUp(self):
        self.mon = LiquidationPriceMonitor()

    def test_drop_standard(self):
        # current=2000, liq=1500 → (2000-1500)/2000 * 100 = 25%
        self.assertAlmostEqual(self.mon._price_drop_to_liq_pct(2000.0, 1500.0), 25.0)

    def test_drop_zero_current_returns_zero(self):
        self.assertAlmostEqual(self.mon._price_drop_to_liq_pct(0.0, 1500.0), 0.0)

    def test_drop_current_below_liq_returns_zero(self):
        # already past liquidation
        self.assertAlmostEqual(self.mon._price_drop_to_liq_pct(1000.0, 1500.0), 0.0)

    def test_drop_current_equals_liq_returns_zero(self):
        self.assertAlmostEqual(self.mon._price_drop_to_liq_pct(1500.0, 1500.0), 0.0)

    def test_drop_liq_zero(self):
        # no liquidation price → full drop to zero
        self.assertAlmostEqual(self.mon._price_drop_to_liq_pct(2000.0, 0.0), 100.0)

    def test_drop_small_margin(self):
        # current=1000, liq=950 → 5%
        self.assertAlmostEqual(self.mon._price_drop_to_liq_pct(1000.0, 950.0), 5.0)

    def test_drop_within_10pct(self):
        # current=1000, liq=960 → 4% < 10%
        result = self.mon._price_drop_to_liq_pct(1000.0, 960.0)
        self.assertLess(result, 10.0)


# ─── TestLTVBufferPct ────────────────────────────────────────────────────────

class TestLTVBufferPct(unittest.TestCase):
    def setUp(self):
        self.mon = LiquidationPriceMonitor()

    def test_ltv_buffer_standard(self):
        # ltv=0.6, threshold=0.80 → (0.80-0.60)/0.80*100 = 25%
        self.assertAlmostEqual(self.mon._ltv_buffer_pct(0.6, 0.80), 25.0)

    def test_ltv_buffer_at_threshold_returns_zero(self):
        self.assertAlmostEqual(self.mon._ltv_buffer_pct(0.80, 0.80), 0.0)

    def test_ltv_buffer_above_threshold_returns_zero(self):
        self.assertAlmostEqual(self.mon._ltv_buffer_pct(0.90, 0.80), 0.0)

    def test_ltv_buffer_zero_ltv(self):
        # ltv=0, threshold=0.75 → 100%
        self.assertAlmostEqual(self.mon._ltv_buffer_pct(0.0, 0.75), 100.0)

    def test_ltv_buffer_small_margin(self):
        # ltv=0.78, threshold=0.80 → (0.02/0.80)*100 = 2.5%
        self.assertAlmostEqual(self.mon._ltv_buffer_pct(0.78, 0.80), 2.5)


# ─── TestStatus ──────────────────────────────────────────────────────────────

class TestStatus(unittest.TestCase):
    def setUp(self):
        self.mon = LiquidationPriceMonitor()

    def test_status_safe(self):
        self.assertEqual(self.mon._status(2.0), "SAFE")

    def test_status_safe_high(self):
        self.assertEqual(self.mon._status(5.0), "SAFE")

    def test_status_caution_lower_bound(self):
        self.assertEqual(self.mon._status(1.5), "CAUTION")

    def test_status_caution_mid(self):
        self.assertEqual(self.mon._status(1.75), "CAUTION")

    def test_status_caution_upper(self):
        self.assertEqual(self.mon._status(1.999), "CAUTION")

    def test_status_warning_lower_bound(self):
        self.assertEqual(self.mon._status(1.2), "WARNING")

    def test_status_warning_mid(self):
        self.assertEqual(self.mon._status(1.35), "WARNING")

    def test_status_warning_upper(self):
        self.assertEqual(self.mon._status(1.499), "WARNING")

    def test_status_danger_lower_bound(self):
        self.assertEqual(self.mon._status(1.05), "DANGER")

    def test_status_danger_mid(self):
        self.assertEqual(self.mon._status(1.1), "DANGER")

    def test_status_danger_upper(self):
        self.assertEqual(self.mon._status(1.199), "DANGER")

    def test_status_critical(self):
        self.assertEqual(self.mon._status(1.0), "CRITICAL")

    def test_status_critical_zero(self):
        self.assertEqual(self.mon._status(0.0), "CRITICAL")

    def test_status_critical_negative(self):
        self.assertEqual(self.mon._status(-1.0), "CRITICAL")

    def test_status_critical_just_below(self):
        self.assertEqual(self.mon._status(1.049), "CRITICAL")


# ─── TestRecommendations ─────────────────────────────────────────────────────

class TestRecommendations(unittest.TestCase):
    def setUp(self):
        self.mon = LiquidationPriceMonitor()

    def test_critical_recommendation_present(self):
        recs = self.mon._recommendations("CRITICAL", 1.0, 50.0)
        self.assertTrue(any("CRITICAL" in r for r in recs))

    def test_critical_has_immediate_keyword(self):
        recs = self.mon._recommendations("CRITICAL", 1.0, 50.0)
        self.assertTrue(any("IMMEDIATELY" in r for r in recs))

    def test_danger_recommendation(self):
        recs = self.mon._recommendations("DANGER", 1.1, 20.0)
        self.assertTrue(any("imminent" in r.lower() for r in recs))

    def test_warning_recommendation(self):
        recs = self.mon._recommendations("WARNING", 1.3, 20.0)
        self.assertTrue(any("1.5" in r for r in recs))

    def test_price_within_10pct_warning(self):
        recs = self.mon._recommendations("CAUTION", 1.8, 5.0)
        self.assertTrue(any("10%" in r for r in recs))

    def test_price_exactly_10pct_no_extra_warning(self):
        # drop == 10.0, condition is < 10 so no warning
        recs = self.mon._recommendations("SAFE", 2.5, 10.0)
        self.assertFalse(any("10%" in r for r in recs))

    def test_safe_high_hf_recommendation(self):
        recs = self.mon._recommendations("SAFE", 3.5, 50.0)
        self.assertTrue(any("very safe" in r for r in recs))

    def test_safe_low_hf_no_yield_recommendation(self):
        recs = self.mon._recommendations("SAFE", 2.5, 50.0)
        self.assertFalse(any("very safe" in r for r in recs))

    def test_caution_no_primary_recommendation(self):
        # CAUTION status without price warning or high HF
        recs = self.mon._recommendations("CAUTION", 1.8, 20.0)
        # No primary status recommendation for CAUTION
        self.assertFalse(any("CRITICAL" in r or "imminent" in r.lower() for r in recs))

    def test_critical_plus_price_within_10(self):
        recs = self.mon._recommendations("CRITICAL", 1.0, 5.0)
        # Should have at least 2 entries
        self.assertGreaterEqual(len(recs), 2)


# ─── TestMonitorIntegration ──────────────────────────────────────────────────

class TestMonitorIntegration(unittest.TestCase):
    def setUp(self):
        self.mon = LiquidationPriceMonitor()

    def _make_standard_pos(self):
        """
        collateral_amount=10 ETH @ $2000 → col_val=$20000
        debt=$12000, threshold=0.80
        LTV = 12000/20000 = 0.60
        HF  = 20000*0.80/12000 = 1.3333
        liq_price = 12000/(10*0.80) = 1500
        price_drop = (2000-1500)/2000*100 = 25%
        ltv_buffer = (0.80-0.60)/0.80*100 = 25%
        status = WARNING (1.2 <= 1.333 < 1.5)
        """
        return _pos(collateral_amount=10.0, collateral_price_usd=2000.0,
                    debt_amount_usd=12000.0, liquidation_threshold=0.80)

    def test_monitor_returns_report(self):
        r = self.mon.monitor(self._make_standard_pos())
        self.assertIsInstance(r, LiquidationRiskReport)

    def test_monitor_collateral_value(self):
        r = self.mon.monitor(self._make_standard_pos())
        self.assertAlmostEqual(r.collateral_value_usd, 20000.0)

    def test_monitor_current_ltv(self):
        r = self.mon.monitor(self._make_standard_pos())
        self.assertAlmostEqual(r.current_ltv, 0.60)

    def test_monitor_liquidation_ltv(self):
        r = self.mon.monitor(self._make_standard_pos())
        self.assertAlmostEqual(r.liquidation_ltv, 0.80)

    def test_monitor_health_factor(self):
        r = self.mon.monitor(self._make_standard_pos())
        self.assertAlmostEqual(r.health_factor, 4 / 3, places=5)

    def test_monitor_liquidation_price(self):
        r = self.mon.monitor(self._make_standard_pos())
        self.assertAlmostEqual(r.liquidation_price_usd, 1500.0)

    def test_monitor_price_drop_pct(self):
        r = self.mon.monitor(self._make_standard_pos())
        self.assertAlmostEqual(r.price_drop_to_liq_pct, 25.0)

    def test_monitor_ltv_buffer(self):
        r = self.mon.monitor(self._make_standard_pos())
        self.assertAlmostEqual(r.ltv_buffer_pct, 25.0)

    def test_monitor_status_warning(self):
        r = self.mon.monitor(self._make_standard_pos())
        self.assertEqual(r.status, "WARNING")

    def test_monitor_days_to_liq_is_none(self):
        r = self.mon.monitor(self._make_standard_pos())
        self.assertIsNone(r.days_to_liq_at_trend)

    def test_monitor_recommendations_list(self):
        r = self.mon.monitor(self._make_standard_pos())
        self.assertIsInstance(r.recommendations, list)

    def test_monitor_position_id_preserved(self):
        p = _pos(position_id="myid123")
        r = self.mon.monitor(p)
        self.assertEqual(r.position_id, "myid123")

    def test_monitor_protocol_preserved(self):
        p = _pos(protocol="Morpho Blue")
        r = self.mon.monitor(p)
        self.assertEqual(r.protocol, "Morpho Blue")

    def test_monitor_safe_position(self):
        # Very safe: col=100000, debt=5000, threshold=0.80
        p = _pos(collateral_amount=100.0, collateral_price_usd=1000.0,
                 debt_amount_usd=5000.0, liquidation_threshold=0.80)
        r = self.mon.monitor(p)
        self.assertEqual(r.status, "SAFE")

    def test_monitor_critical_position(self):
        # HF just below 1.05: col_val=10000, thresh=0.80, debt=9700
        # HF = 8000/9700 ≈ 0.824 → CRITICAL
        p = _pos(collateral_amount=10.0, collateral_price_usd=1000.0,
                 debt_amount_usd=9700.0, liquidation_threshold=0.80)
        r = self.mon.monitor(p)
        self.assertEqual(r.status, "CRITICAL")


# ─── TestMonitorBatch ────────────────────────────────────────────────────────

class TestMonitorBatch(unittest.TestCase):
    def setUp(self):
        self.mon = LiquidationPriceMonitor()

    def test_batch_empty_returns_empty(self):
        self.assertEqual(self.mon.monitor_batch([]), [])

    def test_batch_single(self):
        result = self.mon.monitor_batch([_pos()])
        self.assertEqual(len(result), 1)

    def test_batch_multiple(self):
        positions = [_pos(position_id=str(i)) for i in range(5)]
        result = self.mon.monitor_batch(positions)
        self.assertEqual(len(result), 5)

    def test_batch_ids_preserved(self):
        ids = ["a", "b", "c"]
        positions = [_pos(position_id=i) for i in ids]
        result = self.mon.monitor_batch(positions)
        self.assertEqual([r.position_id for r in result], ids)


# ─── TestCriticalPositions ───────────────────────────────────────────────────

class TestCriticalPositions(unittest.TestCase):
    def setUp(self):
        self.mon = LiquidationPriceMonitor()

    def _report(self, status, pid="p1"):
        return LiquidationRiskReport(
            position_id=pid, protocol="Test",
            collateral_value_usd=10000.0, current_ltv=0.5,
            liquidation_ltv=0.8, ltv_buffer_pct=20.0,
            liquidation_price_usd=1000.0, price_drop_to_liq_pct=30.0,
            health_factor=1.5, status=status,
            days_to_liq_at_trend=None, recommendations=[],
        )

    def test_critical_positions_filters_critical(self):
        reports = [self._report("CRITICAL"), self._report("SAFE"), self._report("DANGER")]
        result = self.mon.critical_positions(reports)
        self.assertEqual(len(result), 2)

    def test_critical_positions_empty_input(self):
        self.assertEqual(self.mon.critical_positions([]), [])

    def test_critical_positions_no_critical(self):
        reports = [self._report("SAFE"), self._report("WARNING"), self._report("CAUTION")]
        self.assertEqual(self.mon.critical_positions(reports), [])

    def test_critical_positions_only_critical(self):
        reports = [self._report("CRITICAL", "a"), self._report("DANGER", "b")]
        result = self.mon.critical_positions(reports)
        self.assertEqual(len(result), 2)

    def test_critical_positions_danger_included(self):
        reports = [self._report("DANGER")]
        result = self.mon.critical_positions(reports)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "DANGER")


# ─── TestRingBuffer ──────────────────────────────────────────────────────────

class TestRingBuffer(unittest.TestCase):
    def _make_monitor(self):
        td = tempfile.mkdtemp()
        return LiquidationPriceMonitor(data_file=Path(td) / "test_liq.json")

    def _make_report(self, pid="p1", status="SAFE"):
        return LiquidationRiskReport(
            position_id=pid, protocol="Aave",
            collateral_value_usd=20000.0, current_ltv=0.6,
            liquidation_ltv=0.8, ltv_buffer_pct=25.0,
            liquidation_price_usd=1500.0, price_drop_to_liq_pct=25.0,
            health_factor=1.333, status=status,
            days_to_liq_at_trend=None, recommendations=[],
        )

    def test_save_creates_file(self):
        mon = self._make_monitor()
        mon.save_results([self._make_report()])
        self.assertTrue(mon.data_file.exists())

    def test_save_valid_json(self):
        mon = self._make_monitor()
        mon.save_results([self._make_report()])
        data = json.loads(mon.data_file.read_text())
        self.assertIsInstance(data, list)

    def test_save_single_entry(self):
        mon = self._make_monitor()
        mon.save_results([self._make_report("x")])
        data = json.loads(mon.data_file.read_text())
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["position_id"], "x")

    def test_save_appends(self):
        mon = self._make_monitor()
        mon.save_results([self._make_report("p1")])
        mon.save_results([self._make_report("p2")])
        data = json.loads(mon.data_file.read_text())
        self.assertEqual(len(data), 2)

    def test_save_ring_buffer_cap(self):
        mon = self._make_monitor()
        for i in range(MAX_ENTRIES + 10):
            mon.save_results([self._make_report(str(i))])
        data = json.loads(mon.data_file.read_text())
        self.assertLessEqual(len(data), MAX_ENTRIES)

    def test_save_atomic_no_tmp_left(self):
        mon = self._make_monitor()
        mon.save_results([self._make_report()])
        tmp = mon.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_load_history_missing_file_returns_empty(self):
        mon = self._make_monitor()
        self.assertEqual(mon.load_history(), [])

    def test_load_history_after_save(self):
        mon = self._make_monitor()
        mon.save_results([self._make_report("p1")])
        history = mon.load_history()
        self.assertEqual(len(history), 1)

    def test_load_history_corrupt_file_returns_empty(self):
        mon = self._make_monitor()
        mon.data_file.parent.mkdir(parents=True, exist_ok=True)
        mon.data_file.write_text("not valid json{{")
        self.assertEqual(mon.load_history(), [])

    def test_save_contains_timestamp(self):
        mon = self._make_monitor()
        before = time.time()
        mon.save_results([self._make_report()])
        after = time.time()
        data = json.loads(mon.data_file.read_text())
        self.assertGreaterEqual(data[0]["timestamp"], before)
        self.assertLessEqual(data[0]["timestamp"], after)

    def test_save_status_recorded(self):
        mon = self._make_monitor()
        mon.save_results([self._make_report("p1", "WARNING")])
        data = json.loads(mon.data_file.read_text())
        self.assertEqual(data[0]["status"], "WARNING")


if __name__ == "__main__":
    unittest.main()
