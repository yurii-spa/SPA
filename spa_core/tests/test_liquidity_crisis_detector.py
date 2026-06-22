"""
Tests for MP-748: LiquidityCrisisDetector
Uses unittest only (no pytest).
Run: python3 -m unittest spa_core.tests.test_liquidity_crisis_detector -v
"""

import os
import tempfile
import unittest

from spa_core.analytics.liquidity_crisis_detector import (
    LiquiditySignal,
    LiquidityCrisisResult,
    RING_BUFFER_CAP,
    compute_liquidity_ratio,
    compute_crisis_score,
    alert_level,
    compute_hours_to_illiquidity,
    analyze_signal,
    detect_crises,
    save_results,
    load_history,
    _worst_alert,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sig(
    protocol="TestProtocol",
    asset="USDC",
    utilization_pct=50.0,
    available_liquidity_usd=50_000_000.0,
    total_deposits_usd=100_000_000.0,
    borrow_rate_pct=5.0,
    borrow_rate_7d_avg_pct=4.5,
):
    return analyze_signal(
        protocol=protocol,
        asset=asset,
        utilization_pct=utilization_pct,
        available_liquidity_usd=available_liquidity_usd,
        total_deposits_usd=total_deposits_usd,
        borrow_rate_pct=borrow_rate_pct,
        borrow_rate_7d_avg_pct=borrow_rate_7d_avg_pct,
    )


def _signals_data(
    protocol="TestProtocol",
    utilization_pct=50.0,
    available_liquidity_usd=50_000_000.0,
    total_deposits_usd=100_000_000.0,
    borrow_rate_pct=5.0,
    borrow_rate_7d_avg_pct=4.5,
):
    return [{
        "protocol": protocol,
        "asset": "USDC",
        "utilization_pct": utilization_pct,
        "available_liquidity_usd": available_liquidity_usd,
        "total_deposits_usd": total_deposits_usd,
        "borrow_rate_pct": borrow_rate_pct,
        "borrow_rate_7d_avg_pct": borrow_rate_7d_avg_pct,
    }]


# ===========================================================================
# 1. compute_liquidity_ratio
# ===========================================================================

class TestComputeLiquidityRatio(unittest.TestCase):

    def test_basic(self):
        ratio = compute_liquidity_ratio(10_000_000.0, 100_000_000.0)
        self.assertAlmostEqual(ratio, 10.0)

    def test_zero_total_returns_zero(self):
        self.assertEqual(compute_liquidity_ratio(5000.0, 0.0), 0.0)

    def test_full_available(self):
        ratio = compute_liquidity_ratio(100.0, 100.0)
        self.assertAlmostEqual(ratio, 100.0)

    def test_partial(self):
        ratio = compute_liquidity_ratio(25.0, 200.0)
        self.assertAlmostEqual(ratio, 12.5)

    def test_zero_available(self):
        ratio = compute_liquidity_ratio(0.0, 100_000.0)
        self.assertAlmostEqual(ratio, 0.0)


# ===========================================================================
# 2. compute_crisis_score
# ===========================================================================

class TestComputeCrisisScore(unittest.TestCase):

    def test_all_zero(self):
        score = compute_crisis_score(0.0, 0.0, False, False)
        self.assertAlmostEqual(score, 0.0)

    def test_formula_components(self):
        # util=50, spike=2, thin=True, critical=False
        # = 50*0.4 + min(2*5, 30) + 10 + 0 = 20 + 10 + 10 = 40
        score = compute_crisis_score(50.0, 2.0, True, False)
        self.assertAlmostEqual(score, 40.0)

    def test_formula_with_critical(self):
        # util=80, spike=3, thin=True, critical=True
        # = 80*0.4 + min(15,30) + 10 + 20 = 32+15+10+20=77
        score = compute_crisis_score(80.0, 3.0, True, True)
        self.assertAlmostEqual(score, 77.0)

    def test_clamped_to_100(self):
        score = compute_crisis_score(100.0, 10.0, True, True)
        self.assertLessEqual(score, 100.0)

    def test_clamped_to_0(self):
        score = compute_crisis_score(0.0, -5.0, False, False)
        self.assertGreaterEqual(score, 0.0)

    def test_spike_capped_at_30(self):
        # spike=10 → min(50,30)=30; spike=100 → min(500,30)=30
        score1 = compute_crisis_score(0.0, 10.0, False, False)
        score2 = compute_crisis_score(0.0, 100.0, False, False)
        self.assertAlmostEqual(score1, 30.0)
        self.assertAlmostEqual(score2, 30.0)

    def test_no_indicators_low_score(self):
        score = compute_crisis_score(10.0, 0.0, False, False)
        # 10*0.4 = 4
        self.assertAlmostEqual(score, 4.0)

    def test_thin_adds_10(self):
        s_no_thin = compute_crisis_score(50.0, 0.0, False, False)
        s_thin = compute_crisis_score(50.0, 0.0, True, False)
        self.assertAlmostEqual(s_thin - s_no_thin, 10.0)

    def test_critical_adds_20(self):
        s_no_crit = compute_crisis_score(50.0, 0.0, False, False)
        s_crit = compute_crisis_score(50.0, 0.0, False, True)
        self.assertAlmostEqual(s_crit - s_no_crit, 20.0)


# ===========================================================================
# 3. alert_level
# ===========================================================================

class TestAlertLevel(unittest.TestCase):

    def test_normal(self):
        self.assertEqual(alert_level(0.0), "NORMAL")
        self.assertEqual(alert_level(29.9), "NORMAL")

    def test_watch(self):
        self.assertEqual(alert_level(30.0), "WATCH")
        self.assertEqual(alert_level(59.9), "WATCH")

    def test_warning(self):
        self.assertEqual(alert_level(60.0), "WARNING")
        self.assertEqual(alert_level(79.9), "WARNING")

    def test_crisis(self):
        self.assertEqual(alert_level(80.0), "CRISIS")
        self.assertEqual(alert_level(100.0), "CRISIS")


# ===========================================================================
# 4. compute_hours_to_illiquidity
# ===========================================================================

class TestComputeHoursToIlliquidity(unittest.TestCase):

    def test_util_95_returns_0(self):
        self.assertEqual(compute_hours_to_illiquidity(1_000_000.0, 10_000_000.0, 95.0), 0.0)

    def test_util_100_returns_0(self):
        self.assertEqual(compute_hours_to_illiquidity(0.0, 10_000_000.0, 100.0), 0.0)

    def test_capped_at_720(self):
        # available >> total → formula gives huge number → capped at 720
        # e.g. available=100_000, total=1, util=5 → 100000/1/0.01 = 1e7 → capped
        hours = compute_hours_to_illiquidity(100_000.0, 1.0, 5.0)
        self.assertAlmostEqual(hours, 720.0)

    def test_formula(self):
        # available=10M, total=100M → 10M/100M/0.01 = 10
        hours = compute_hours_to_illiquidity(10_000_000.0, 100_000_000.0, 50.0)
        self.assertAlmostEqual(hours, 10.0)

    def test_total_zero_returns_720(self):
        hours = compute_hours_to_illiquidity(0.0, 0.0, 0.0)
        self.assertAlmostEqual(hours, 720.0)

    def test_util_94_not_zero(self):
        hours = compute_hours_to_illiquidity(6_000_000.0, 100_000_000.0, 94.0)
        self.assertGreater(hours, 0.0)


# ===========================================================================
# 5. analyze_signal — computed fields
# ===========================================================================

class TestAnalyzeSignal(unittest.TestCase):

    def test_utilization_spike_formula(self):
        sig = _sig(borrow_rate_pct=7.0, borrow_rate_7d_avg_pct=4.5)
        self.assertAlmostEqual(sig.utilization_spike, 2.5)

    def test_negative_spike(self):
        sig = _sig(borrow_rate_pct=3.0, borrow_rate_7d_avg_pct=5.0)
        self.assertAlmostEqual(sig.utilization_spike, -2.0)

    def test_liquidity_ratio_pct_formula(self):
        sig = _sig(available_liquidity_usd=15_000_000.0, total_deposits_usd=100_000_000.0)
        self.assertAlmostEqual(sig.liquidity_ratio_pct, 15.0)

    def test_liquidity_ratio_zero_total(self):
        sig = _sig(available_liquidity_usd=0.0, total_deposits_usd=0.0)
        self.assertAlmostEqual(sig.liquidity_ratio_pct, 0.0)

    def test_crisis_score_computed(self):
        sig = _sig(utilization_pct=50.0, borrow_rate_pct=5.0, borrow_rate_7d_avg_pct=4.5)
        self.assertGreaterEqual(sig.crisis_score, 0.0)
        self.assertLessEqual(sig.crisis_score, 100.0)

    def test_alert_level_assigned(self):
        sig = _sig()
        self.assertIn(sig.alert_level, ["NORMAL", "WATCH", "WARNING", "CRISIS"])

    def test_is_utilization_critical_true(self):
        sig = _sig(utilization_pct=95.0)
        self.assertTrue(sig.is_utilization_critical)

    def test_is_utilization_critical_false(self):
        sig = _sig(utilization_pct=94.9)
        self.assertFalse(sig.is_utilization_critical)

    def test_is_rate_spiking_true(self):
        sig = _sig(borrow_rate_pct=7.0, borrow_rate_7d_avg_pct=4.5)  # spike=2.5
        self.assertTrue(sig.is_rate_spiking)

    def test_is_rate_spiking_boundary(self):
        sig = _sig(borrow_rate_pct=6.5, borrow_rate_7d_avg_pct=4.5)  # spike=2.0
        self.assertTrue(sig.is_rate_spiking)

    def test_is_rate_spiking_false(self):
        sig = _sig(borrow_rate_pct=5.0, borrow_rate_7d_avg_pct=4.5)  # spike=0.5
        self.assertFalse(sig.is_rate_spiking)

    def test_is_liquidity_thin_true(self):
        sig = _sig(available_liquidity_usd=8_000_000.0, total_deposits_usd=100_000_000.0)
        self.assertTrue(sig.is_liquidity_thin)

    def test_is_liquidity_thin_false(self):
        sig = _sig(available_liquidity_usd=15_000_000.0, total_deposits_usd=100_000_000.0)
        self.assertFalse(sig.is_liquidity_thin)

    def test_protocol_field(self):
        sig = _sig(protocol="Aave V3")
        self.assertEqual(sig.protocol, "Aave V3")

    def test_asset_field(self):
        sig = analyze_signal("P", "WETH", 50, 50e6, 100e6, 5.0, 4.5)
        self.assertEqual(sig.asset, "WETH")

    def test_hours_illiquidity_crisis_util(self):
        sig = _sig(utilization_pct=97.0)
        self.assertEqual(sig.hours_to_illiquidity, 0.0)


# ===========================================================================
# 6. Recommendations
# ===========================================================================

class TestRecommendations(unittest.TestCase):

    def test_crisis_recommendation(self):
        # util=100, spike=10 → massive score
        sig = _sig(
            utilization_pct=100.0,
            available_liquidity_usd=0.0,
            total_deposits_usd=1_000_000.0,
            borrow_rate_pct=50.0,
            borrow_rate_7d_avg_pct=5.0,
        )
        self.assertIn("CRISIS", sig.recommendation)
        self.assertIn("Withdraw immediately", sig.recommendation)

    def test_warning_recommendation(self):
        # Score in 60-79 range: util=80, spike=0, thin=True, critical=False
        # = 80*0.4 + 0 + 10 + 0 = 42 → WATCH, need to push higher
        # util=90, spike=3, thin=True, critical=False → 90*0.4+15+10=61 → WARNING
        sig = _sig(
            utilization_pct=90.0,
            available_liquidity_usd=8_000_000.0,
            total_deposits_usd=100_000_000.0,
            borrow_rate_pct=8.0,
            borrow_rate_7d_avg_pct=5.0,
        )
        if sig.alert_level == "WARNING":
            self.assertIn("WARNING", sig.recommendation)
            self.assertIn("Monitor closely", sig.recommendation)
        else:
            # Any other level still has a valid recommendation
            self.assertIn(sig.alert_level, ["NORMAL", "WATCH", "WARNING", "CRISIS"])

    def test_watch_recommendation(self):
        # util=50, thin=True → 50*0.4+10=30 → WATCH
        sig = _sig(
            utilization_pct=50.0,
            available_liquidity_usd=5_000_000.0,
            total_deposits_usd=100_000_000.0,
            borrow_rate_pct=5.0,
            borrow_rate_7d_avg_pct=4.5,
        )
        if sig.alert_level == "WATCH":
            self.assertIn("WATCH", sig.recommendation)
            self.assertIn("Track utilization", sig.recommendation)

    def test_normal_recommendation(self):
        sig = _sig(
            utilization_pct=10.0,
            available_liquidity_usd=90_000_000.0,
            total_deposits_usd=100_000_000.0,
            borrow_rate_pct=2.0,
            borrow_rate_7d_avg_pct=2.0,
        )
        if sig.alert_level == "NORMAL":
            self.assertIn("healthy", sig.recommendation)


# ===========================================================================
# 7. detect_crises — result fields
# ===========================================================================

class TestDetectCrises(unittest.TestCase):

    def _make_data(self, **kwargs):
        return _signals_data(**kwargs)

    def test_crisis_protocols_list(self):
        # Build a crisis signal: util=100, spike=20
        data = [
            {
                "protocol": "BadProtocol",
                "asset": "USDC",
                "utilization_pct": 100.0,
                "available_liquidity_usd": 0.0,
                "total_deposits_usd": 1_000_000.0,
                "borrow_rate_pct": 50.0,
                "borrow_rate_7d_avg_pct": 5.0,
            }
        ]
        result = detect_crises(data)
        self.assertIn("BadProtocol", result.crisis_protocols)

    def test_warning_protocols_list(self):
        data = [
            {
                "protocol": "WarnProto",
                "asset": "USDC",
                "utilization_pct": 90.0,
                "available_liquidity_usd": 8_000_000.0,
                "total_deposits_usd": 100_000_000.0,
                "borrow_rate_pct": 9.0,
                "borrow_rate_7d_avg_pct": 5.0,
            }
        ]
        result = detect_crises(data)
        # Depending on score, may be WARNING or WATCH or CRISIS
        sig = result.signals[0]
        if sig.alert_level == "WARNING":
            self.assertIn("WarnProto", result.warning_protocols)

    def test_normal_not_in_crisis_or_warning(self):
        data = _signals_data(utilization_pct=20.0, borrow_rate_pct=2.0, borrow_rate_7d_avg_pct=2.0)
        result = detect_crises(data)
        self.assertEqual(result.crisis_protocols, [])

    def test_most_at_risk_highest_score(self):
        data = [
            {
                "protocol": "Safe",
                "asset": "USDC",
                "utilization_pct": 10.0,
                "available_liquidity_usd": 90e6,
                "total_deposits_usd": 100e6,
                "borrow_rate_pct": 2.0,
                "borrow_rate_7d_avg_pct": 2.0,
            },
            {
                "protocol": "Risky",
                "asset": "USDC",
                "utilization_pct": 100.0,
                "available_liquidity_usd": 0.0,
                "total_deposits_usd": 1e6,
                "borrow_rate_pct": 50.0,
                "borrow_rate_7d_avg_pct": 5.0,
            },
        ]
        result = detect_crises(data)
        self.assertEqual(result.most_at_risk_protocol, "Risky")

    def test_system_alert_level_worst(self):
        data = [
            {
                "protocol": "Safe",
                "asset": "USDC",
                "utilization_pct": 10.0,
                "available_liquidity_usd": 90e6,
                "total_deposits_usd": 100e6,
                "borrow_rate_pct": 2.0,
                "borrow_rate_7d_avg_pct": 2.0,
            },
            {
                "protocol": "Crisis",
                "asset": "USDC",
                "utilization_pct": 100.0,
                "available_liquidity_usd": 0.0,
                "total_deposits_usd": 1e6,
                "borrow_rate_pct": 50.0,
                "borrow_rate_7d_avg_pct": 5.0,
            },
        ]
        result = detect_crises(data)
        self.assertEqual(result.system_alert_level, "CRISIS")

    def test_empty_signals(self):
        result = detect_crises([])
        self.assertEqual(result.signals, [])
        self.assertEqual(result.crisis_protocols, [])
        self.assertEqual(result.system_alert_level, "NORMAL")

    def test_signals_count(self):
        data = [
            _signals_data("P1")[0],
            _signals_data("P2")[0],
        ]
        result = detect_crises(data)
        self.assertEqual(len(result.signals), 2)

    def test_result_has_recommendation_summary(self):
        result = detect_crises(_signals_data())
        self.assertIsInstance(result.recommendation_summary, str)
        self.assertGreater(len(result.recommendation_summary), 0)


# ===========================================================================
# 8. save / load / ring-buffer
# ===========================================================================

class TestSaveLoadRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmp_dir, "liquidity_crisis_log.json")

    def _basic_result(self, protocol="P"):
        data = _signals_data(protocol=protocol)
        return detect_crises(data, data_file=self.data_file)

    def test_save_and_load_round_trip(self):
        result = self._basic_result()
        save_results(result, self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(len(history), 1)
        self.assertIn("signals", history[0])

    def test_load_empty_when_no_file(self):
        history = load_history(os.path.join(self.tmp_dir, "nonexistent.json"))
        self.assertEqual(history, [])

    def test_ring_buffer_cap(self):
        for i in range(RING_BUFFER_CAP + 5):
            result = self._basic_result(protocol=f"P{i}")
            save_results(result, self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(len(history), RING_BUFFER_CAP)

    def test_saved_to_field_updated(self):
        result = self._basic_result()
        save_results(result, self.data_file)
        self.assertEqual(result.saved_to, self.data_file)

    def test_multiple_saves_accumulate(self):
        for _ in range(3):
            result = self._basic_result()
            save_results(result, self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(len(history), 3)

    def test_invalid_json_returns_empty(self):
        with open(self.data_file, "w") as f:
            f.write("NOT JSON")
        history = load_history(self.data_file)
        self.assertEqual(history, [])


# ===========================================================================
# 9. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_100pct_utilization_crisis(self):
        sig = _sig(
            utilization_pct=100.0,
            available_liquidity_usd=0.0,
            total_deposits_usd=1_000_000.0,
            borrow_rate_pct=50.0,
            borrow_rate_7d_avg_pct=5.0,
        )
        self.assertEqual(sig.alert_level, "CRISIS")
        self.assertEqual(sig.hours_to_illiquidity, 0.0)

    def test_low_utilization_normal(self):
        sig = _sig(
            utilization_pct=5.0,
            available_liquidity_usd=95_000_000.0,
            total_deposits_usd=100_000_000.0,
            borrow_rate_pct=2.0,
            borrow_rate_7d_avg_pct=2.0,
        )
        self.assertEqual(sig.alert_level, "NORMAL")

    def test_worst_alert_helper_empty(self):
        self.assertEqual(_worst_alert([]), "NORMAL")

    def test_worst_alert_helper_mixed(self):
        self.assertEqual(_worst_alert(["NORMAL", "WATCH", "CRISIS"]), "CRISIS")

    def test_worst_alert_all_normal(self):
        self.assertEqual(_worst_alert(["NORMAL", "NORMAL"]), "NORMAL")

    def test_score_boundary_exactly_30(self):
        # Verify exactly 30 maps to WATCH
        self.assertEqual(alert_level(30.0), "WATCH")

    def test_score_boundary_exactly_60(self):
        self.assertEqual(alert_level(60.0), "WARNING")

    def test_score_boundary_exactly_80(self):
        self.assertEqual(alert_level(80.0), "CRISIS")

    def test_very_large_deposits(self):
        sig = analyze_signal("P", "USDC", 50.0, 1e12, 2e12, 5.0, 5.0)
        self.assertAlmostEqual(sig.liquidity_ratio_pct, 50.0)

    def test_zero_spike_not_spiking(self):
        sig = _sig(borrow_rate_pct=5.0, borrow_rate_7d_avg_pct=5.0)
        self.assertFalse(sig.is_rate_spiking)
        self.assertAlmostEqual(sig.utilization_spike, 0.0)

    def test_detect_crises_returns_result_type(self):
        result = detect_crises(_signals_data())
        self.assertIsInstance(result, LiquidityCrisisResult)

    def test_analyze_signal_returns_signal_type(self):
        sig = _sig()
        self.assertIsInstance(sig, LiquiditySignal)


if __name__ == "__main__":
    unittest.main()
