"""
Tests for MP-1136: DeFiProtocolWithdrawalQueueRiskAnalyzer
>=110 test cases using unittest only.
Tempfile-based log isolation — production data/ is never touched.
Pure stdlib.  Python 3.9 compatible.
"""

import json
import os
import tempfile
import unittest
from typing import Optional

from spa_core.analytics.defi_protocol_withdrawal_queue_risk_analyzer import (
    DAYS_PER_YEAR,
    HOURS_PER_DAY,
    LABEL_FAST_MAX,
    LABEL_INSTANT_MAX,
    LABEL_LONG_MAX,
    LABEL_MANAGEABLE_MAX,
    LOG_MAX_ENTRIES,
    SCORE_BREAKPOINTS,
    VALID_WITHDRAWAL_TYPES,
    DeFiProtocolWithdrawalQueueRiskAnalyzer,
    _atomic_write,
    _compute_estimated_wait_hours,
    _compute_queue_label,
    _compute_queue_risk_score,
    _load_log,
    _validate_inputs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_analyzer(tmp_dir: str) -> DeFiProtocolWithdrawalQueueRiskAnalyzer:
    log = os.path.join(tmp_dir, "wq_log.json")
    return DeFiProtocolWithdrawalQueueRiskAnalyzer(log_path=log)


def _default_kwargs(**overrides):
    base = dict(
        withdrawal_type="queued",
        queue_wait_hours=0.0,
        queue_size_usd=0.0,
        daily_exit_capacity_usd=1_000_000.0,
        position_size_usd=10_000.0,
        annual_yield_during_wait_pct=5.0,
        price_impact_risk_pct=0.5,
        protocol_name="TestProtocol",
    )
    base.update(overrides)
    return base


# ===========================================================================
# TestValidateInputs
# ===========================================================================

class TestValidateInputs(unittest.TestCase):
    """20 tests covering every guard in _validate_inputs."""

    def _call(self, **kw):
        _validate_inputs(**_default_kwargs(**kw))

    def test_all_valid_queued(self):
        self._call()  # no exception

    def test_all_valid_instant(self):
        self._call(withdrawal_type="instant", queue_wait_hours=0.0)

    def test_all_valid_unbonding(self):
        self._call(withdrawal_type="unbonding", queue_wait_hours=168.0)

    def test_all_valid_maturity_locked(self):
        self._call(withdrawal_type="maturity_locked", queue_wait_hours=720.0)

    def test_invalid_withdrawal_type(self):
        with self.assertRaises(ValueError):
            self._call(withdrawal_type="flash")

    def test_invalid_withdrawal_type_empty(self):
        with self.assertRaises(ValueError):
            self._call(withdrawal_type="")

    def test_invalid_withdrawal_type_case(self):
        with self.assertRaises(ValueError):
            self._call(withdrawal_type="INSTANT")

    def test_negative_queue_wait_hours(self):
        with self.assertRaises(ValueError):
            self._call(queue_wait_hours=-1.0)

    def test_zero_queue_wait_hours_ok(self):
        self._call(queue_wait_hours=0.0)  # boundary: ok

    def test_negative_queue_size(self):
        with self.assertRaises(ValueError):
            self._call(queue_size_usd=-0.01)

    def test_zero_queue_size_ok(self):
        self._call(queue_size_usd=0.0)  # boundary: ok

    def test_negative_daily_capacity(self):
        with self.assertRaises(ValueError):
            self._call(daily_exit_capacity_usd=-100.0)

    def test_zero_daily_capacity_ok(self):
        self._call(daily_exit_capacity_usd=0.0)  # valid (may produce inf wait)

    def test_zero_position_size(self):
        with self.assertRaises(ValueError):
            self._call(position_size_usd=0.0)

    def test_negative_position_size(self):
        with self.assertRaises(ValueError):
            self._call(position_size_usd=-1.0)

    def test_negative_annual_yield(self):
        with self.assertRaises(ValueError):
            self._call(annual_yield_during_wait_pct=-0.01)

    def test_zero_yield_ok(self):
        self._call(annual_yield_during_wait_pct=0.0)

    def test_negative_price_impact(self):
        with self.assertRaises(ValueError):
            self._call(price_impact_risk_pct=-0.01)

    def test_empty_protocol_name(self):
        with self.assertRaises(ValueError):
            self._call(protocol_name="")

    def test_whitespace_protocol_name(self):
        with self.assertRaises(ValueError):
            self._call(protocol_name="   ")


# ===========================================================================
# TestComputeEstimatedWaitHours
# ===========================================================================

class TestComputeEstimatedWaitHours(unittest.TestCase):
    """17 tests for _compute_estimated_wait_hours."""

    def test_instant_zero_everything(self):
        self.assertEqual(_compute_estimated_wait_hours(0.0, 0.0, 0.0), 0.0)

    def test_no_queue_uses_stated_wait(self):
        # queue_size=0, no capacity issue → queue_wait_hours
        result = _compute_estimated_wait_hours(12.0, 0.0, 1_000_000.0)
        self.assertAlmostEqual(result, 12.0)

    def test_queue_longer_than_stated(self):
        # queue_size_usd=500k, capacity=1M/day → 0.5 days = 12h queue-based
        # stated=6h → max(6, 12) = 12
        result = _compute_estimated_wait_hours(6.0, 500_000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 12.0)

    def test_stated_longer_than_queue(self):
        # queue_size_usd=100k, capacity=1M/day → 2.4h queue-based
        # stated=24h → max(24, 2.4) = 24
        result = _compute_estimated_wait_hours(24.0, 100_000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 24.0)

    def test_exact_equality_takes_max(self):
        # queue_size=1M, capacity=1M/day → 24h queue-based; stated=24h → 24
        result = _compute_estimated_wait_hours(24.0, 1_000_000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 24.0)

    def test_zero_capacity_nonzero_queue_is_inf(self):
        result = _compute_estimated_wait_hours(0.0, 100.0, 0.0)
        self.assertEqual(result, float("inf"))

    def test_zero_capacity_zero_queue_uses_stated(self):
        result = _compute_estimated_wait_hours(48.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 48.0)

    def test_zero_capacity_zero_queue_zero_stated(self):
        result = _compute_estimated_wait_hours(0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_large_queue_small_capacity(self):
        # 10M queue, 100k/day → 100 days = 2400h
        result = _compute_estimated_wait_hours(0.0, 10_000_000.0, 100_000.0)
        self.assertAlmostEqual(result, 2400.0)

    def test_tiny_queue_large_capacity(self):
        # 1 USD queue, 1B/day → tiny
        result = _compute_estimated_wait_hours(0.0, 1.0, 1_000_000_000.0)
        self.assertAlmostEqual(result, 1.0 / 1_000_000_000.0 * 24.0)

    def test_formula_hours_per_day_used(self):
        # queue_size=capacity → exactly 24h
        result = _compute_estimated_wait_hours(0.0, 5_000.0, 5_000.0)
        self.assertAlmostEqual(result, 24.0)

    def test_stated_zero_queue_based_nonzero(self):
        # queue_size=2M, cap=1M/day → 48h; stated=0 → 48
        result = _compute_estimated_wait_hours(0.0, 2_000_000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 48.0)

    def test_fractional_hours(self):
        # queue_size=250k, cap=1M/day → 6h
        result = _compute_estimated_wait_hours(0.0, 250_000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 6.0)

    def test_exactly_two_hours(self):
        result = _compute_estimated_wait_hours(2.0, 0.0, 1_000_000.0)
        self.assertAlmostEqual(result, 2.0)

    def test_exactly_168_hours(self):
        # queue_size = 7 * cap → 168h
        result = _compute_estimated_wait_hours(0.0, 7_000_000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 168.0)

    def test_max_selects_queue_based(self):
        result = _compute_estimated_wait_hours(1.0, 1_000_000.0, 500_000.0)
        # queue_based = 1M/500k * 24 = 48h; stated = 1h → 48
        self.assertAlmostEqual(result, 48.0)

    def test_max_selects_stated(self):
        result = _compute_estimated_wait_hours(72.0, 100_000.0, 1_000_000.0)
        # queue_based = 2.4h; stated = 72h → 72
        self.assertAlmostEqual(result, 72.0)


# ===========================================================================
# TestComputeQueueRiskScore
# ===========================================================================

class TestComputeQueueRiskScore(unittest.TestCase):
    """18 tests for _compute_queue_risk_score."""

    def test_zero_hours_score_zero(self):
        self.assertEqual(_compute_queue_risk_score(0.0), 0)

    def test_negative_hours_score_zero(self):
        self.assertEqual(_compute_queue_risk_score(-5.0), 0)

    def test_1h_score(self):
        # [0,2] piecewise: 1/2 * 20 = 10
        self.assertEqual(_compute_queue_risk_score(1.0), 10)

    def test_2h_boundary_score(self):
        self.assertEqual(_compute_queue_risk_score(2.0), 20)

    def test_2h_01_just_above_fast(self):
        # Between 2 and 24: int(20 + (0.01/22)*30) = int(20.013) = 20 (int truncation)
        score = _compute_queue_risk_score(2.01)
        self.assertGreaterEqual(score, 20)

    def test_13h_score(self):
        # 20 + (13-2)/22 * 30 = 20 + 11/22*30 = 20+15 = 35
        self.assertEqual(_compute_queue_risk_score(13.0), 35)

    def test_24h_boundary_score(self):
        self.assertEqual(_compute_queue_risk_score(24.0), 50)

    def test_25h_just_above_manageable(self):
        # int(50 + (1/144)*30) = int(50.208) = 50 (int truncation at tiny offset)
        score = _compute_queue_risk_score(25.0)
        self.assertGreaterEqual(score, 50)

    def test_96h_score(self):
        # 50 + (96-24)/144 * 30 = 50 + 72/144*30 = 50+15 = 65
        self.assertEqual(_compute_queue_risk_score(96.0), 65)

    def test_168h_boundary_score(self):
        self.assertEqual(_compute_queue_risk_score(168.0), 80)

    def test_169h_just_above_long(self):
        # int(80 + (1/168)*20) = int(80.119) = 80 (int truncation at 1h step)
        score = _compute_queue_risk_score(169.0)
        self.assertGreaterEqual(score, 80)

    def test_252h_score(self):
        # 80 + (252-168)/168 * 20 = 80 + 84/168*20 = 80+10 = 90
        self.assertEqual(_compute_queue_risk_score(252.0), 90)

    def test_336h_boundary_score(self):
        self.assertEqual(_compute_queue_risk_score(336.0), 100)

    def test_337h_capped_at_100(self):
        self.assertEqual(_compute_queue_risk_score(337.0), 100)

    def test_1000h_capped_at_100(self):
        self.assertEqual(_compute_queue_risk_score(1000.0), 100)

    def test_inf_is_100(self):
        self.assertEqual(_compute_queue_risk_score(float("inf")), 100)

    def test_score_monotonic_increases(self):
        hours = [0, 1, 2, 10, 24, 50, 100, 168, 200, 300, 336, 500]
        scores = [_compute_queue_risk_score(h) for h in hours]
        for i in range(len(scores) - 1):
            self.assertLessEqual(scores[i], scores[i + 1])

    def test_score_is_int(self):
        for h in [0, 1, 2, 24, 168, 336]:
            self.assertIsInstance(_compute_queue_risk_score(float(h)), int)


# ===========================================================================
# TestComputeQueueLabel
# ===========================================================================

class TestComputeQueueLabel(unittest.TestCase):
    """13 tests for _compute_queue_label."""

    def test_zero_is_instant(self):
        self.assertEqual(_compute_queue_label(0.0), "INSTANT_EXIT")

    def test_negative_is_instant(self):
        # Should not normally happen but guard check
        self.assertEqual(_compute_queue_label(-1.0), "INSTANT_EXIT")

    def test_0_01_is_fast(self):
        self.assertEqual(_compute_queue_label(0.01), "FAST_EXIT")

    def test_1h_is_fast(self):
        self.assertEqual(_compute_queue_label(1.0), "FAST_EXIT")

    def test_2h_boundary_is_fast(self):
        self.assertEqual(_compute_queue_label(2.0), "FAST_EXIT")

    def test_2_01h_is_manageable(self):
        self.assertEqual(_compute_queue_label(2.01), "MANAGEABLE_QUEUE")

    def test_12h_is_manageable(self):
        self.assertEqual(_compute_queue_label(12.0), "MANAGEABLE_QUEUE")

    def test_24h_boundary_is_manageable(self):
        self.assertEqual(_compute_queue_label(24.0), "MANAGEABLE_QUEUE")

    def test_24_01h_is_long(self):
        self.assertEqual(_compute_queue_label(24.01), "LONG_QUEUE")

    def test_72h_is_long(self):
        self.assertEqual(_compute_queue_label(72.0), "LONG_QUEUE")

    def test_168h_boundary_is_long(self):
        self.assertEqual(_compute_queue_label(168.0), "LONG_QUEUE")

    def test_168_01h_is_illiquid(self):
        self.assertEqual(_compute_queue_label(168.01), "EXIT_ILLIQUID")

    def test_inf_is_illiquid(self):
        self.assertEqual(_compute_queue_label(float("inf")), "EXIT_ILLIQUID")


# ===========================================================================
# TestAnalyzeOutputKeys
# ===========================================================================

class TestAnalyzeOutputKeys(unittest.TestCase):
    """Verify all expected keys are present in analyze() result."""

    EXPECTED_KEYS = {
        "protocol_name", "withdrawal_type", "queue_wait_hours",
        "queue_size_usd", "daily_exit_capacity_usd", "position_size_usd",
        "annual_yield_during_wait_pct", "price_impact_risk_pct",
        "estimated_wait_hours", "estimated_wait_days",
        "yield_earned_during_wait_usd", "price_impact_usd",
        "net_exit_value_usd", "queue_risk_score", "queue_label",
        "generated_at",
    }

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _mk_analyzer(self.tmp)

    def test_all_keys_present(self):
        r = self.a.analyze(**_default_kwargs())
        self.assertEqual(set(r.keys()), self.EXPECTED_KEYS)

    def test_protocol_name_in_result(self):
        r = self.a.analyze(**_default_kwargs(protocol_name="Aave"))
        self.assertEqual(r["protocol_name"], "Aave")

    def test_withdrawal_type_in_result(self):
        r = self.a.analyze(**_default_kwargs(withdrawal_type="instant"))
        self.assertEqual(r["withdrawal_type"], "instant")

    def test_generated_at_is_string(self):
        r = self.a.analyze(**_default_kwargs())
        self.assertIsInstance(r["generated_at"], str)
        self.assertIn("T", r["generated_at"])

    def test_queue_risk_score_is_int(self):
        r = self.a.analyze(**_default_kwargs())
        self.assertIsInstance(r["queue_risk_score"], int)

    def test_queue_label_is_string(self):
        r = self.a.analyze(**_default_kwargs())
        self.assertIsInstance(r["queue_label"], str)


# ===========================================================================
# TestAnalyzeComputations
# ===========================================================================

class TestAnalyzeComputations(unittest.TestCase):
    """25 tests verifying the numerical outputs of analyze()."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _mk_analyzer(self.tmp)

    # --- INSTANT case -------------------------------------------------------

    def test_instant_zero_wait(self):
        r = self.a.analyze(**_default_kwargs(
            withdrawal_type="instant", queue_wait_hours=0.0,
            queue_size_usd=0.0, daily_exit_capacity_usd=1_000_000.0,
        ))
        self.assertAlmostEqual(r["estimated_wait_hours"], 0.0)
        self.assertAlmostEqual(r["estimated_wait_days"], 0.0)
        self.assertEqual(r["queue_label"], "INSTANT_EXIT")
        self.assertEqual(r["queue_risk_score"], 0)

    def test_instant_yield_zero_wait(self):
        # With 0 wait days, yield earned = 0
        r = self.a.analyze(**_default_kwargs(
            withdrawal_type="instant", queue_wait_hours=0.0,
            queue_size_usd=0.0, daily_exit_capacity_usd=1_000_000.0,
            annual_yield_during_wait_pct=10.0,
        ))
        self.assertAlmostEqual(r["yield_earned_during_wait_usd"], 0.0)

    def test_instant_net_value_without_price_impact(self):
        r = self.a.analyze(**_default_kwargs(
            withdrawal_type="instant", queue_wait_hours=0.0,
            queue_size_usd=0.0, daily_exit_capacity_usd=1_000_000.0,
            position_size_usd=50_000.0,
            annual_yield_during_wait_pct=0.0,
            price_impact_risk_pct=0.0,
        ))
        self.assertAlmostEqual(r["net_exit_value_usd"], 50_000.0)

    # --- QUEUED/UNBONDING cases ---------------------------------------------

    def test_queued_stated_wait(self):
        # No queue size, but stated 48h wait
        r = self.a.analyze(**_default_kwargs(
            withdrawal_type="queued", queue_wait_hours=48.0,
            queue_size_usd=0.0, daily_exit_capacity_usd=1_000_000.0,
        ))
        self.assertAlmostEqual(r["estimated_wait_hours"], 48.0)
        self.assertAlmostEqual(r["estimated_wait_days"], 2.0)
        self.assertEqual(r["queue_label"], "LONG_QUEUE")

    def test_queue_based_wait_dominates(self):
        # queue_size=10M, cap=1M/day → 240h; stated=12h
        r = self.a.analyze(**_default_kwargs(
            queue_wait_hours=12.0, queue_size_usd=10_000_000.0,
            daily_exit_capacity_usd=1_000_000.0,
        ))
        self.assertAlmostEqual(r["estimated_wait_hours"], 240.0)
        self.assertEqual(r["queue_label"], "EXIT_ILLIQUID")

    def test_yield_calculation_1day(self):
        # position=10000, yield=10% annual, wait=1 day
        # yield = 10000 * 0.10 * 1/365 = 2.739726...
        r = self.a.analyze(**_default_kwargs(
            withdrawal_type="queued", queue_wait_hours=24.0,
            queue_size_usd=0.0, daily_exit_capacity_usd=1_000_000.0,
            position_size_usd=10_000.0,
            annual_yield_during_wait_pct=10.0,
            price_impact_risk_pct=0.0,
        ))
        expected_yield = 10_000.0 * 0.10 * (1.0 / 365.0)
        self.assertAlmostEqual(r["yield_earned_during_wait_usd"], expected_yield, places=6)

    def test_yield_calculation_7days(self):
        # position=50000, yield=5%, wait=168h (7 days)
        r = self.a.analyze(**_default_kwargs(
            queue_wait_hours=168.0, queue_size_usd=0.0,
            daily_exit_capacity_usd=1_000_000.0,
            position_size_usd=50_000.0,
            annual_yield_during_wait_pct=5.0,
            price_impact_risk_pct=0.0,
        ))
        expected_yield = 50_000.0 * 0.05 * (7.0 / 365.0)
        self.assertAlmostEqual(r["yield_earned_during_wait_usd"], expected_yield, places=4)

    def test_price_impact_calculation(self):
        r = self.a.analyze(**_default_kwargs(
            position_size_usd=20_000.0, price_impact_risk_pct=2.0,
            annual_yield_during_wait_pct=0.0,
        ))
        self.assertAlmostEqual(r["price_impact_usd"], 400.0)

    def test_net_exit_value_composition(self):
        r = self.a.analyze(**_default_kwargs(
            withdrawal_type="queued", queue_wait_hours=24.0,
            queue_size_usd=0.0, daily_exit_capacity_usd=1_000_000.0,
            position_size_usd=10_000.0,
            annual_yield_during_wait_pct=10.0,
            price_impact_risk_pct=1.0,
        ))
        expected_yield = 10_000.0 * 0.10 / 365.0
        expected_impact = 100.0
        expected_net = 10_000.0 + expected_yield - expected_impact
        self.assertAlmostEqual(r["net_exit_value_usd"], expected_net, places=4)

    def test_net_value_positive_when_yield_covers_impact(self):
        r = self.a.analyze(**_default_kwargs(
            withdrawal_type="queued", queue_wait_hours=0.0,
            queue_size_usd=0.0, daily_exit_capacity_usd=1_000_000.0,
            position_size_usd=10_000.0,
            annual_yield_during_wait_pct=0.0,
            price_impact_risk_pct=0.0,
        ))
        self.assertAlmostEqual(r["net_exit_value_usd"], 10_000.0)

    def test_net_value_reduced_by_price_impact(self):
        r = self.a.analyze(**_default_kwargs(
            position_size_usd=10_000.0,
            annual_yield_during_wait_pct=0.0,
            price_impact_risk_pct=5.0,
            queue_wait_hours=0.0, queue_size_usd=0.0,
        ))
        self.assertAlmostEqual(r["net_exit_value_usd"], 9_500.0)

    # --- Infinite queue cases -----------------------------------------------

    def test_infinite_queue_wait_hours_none(self):
        r = self.a.analyze(**_default_kwargs(
            queue_wait_hours=0.0, queue_size_usd=1.0,
            daily_exit_capacity_usd=0.0,
        ))
        self.assertIsNone(r["estimated_wait_hours"])
        self.assertIsNone(r["estimated_wait_days"])

    def test_infinite_queue_yield_zero(self):
        r = self.a.analyze(**_default_kwargs(
            queue_wait_hours=0.0, queue_size_usd=1.0,
            daily_exit_capacity_usd=0.0,
            annual_yield_during_wait_pct=20.0,
        ))
        self.assertAlmostEqual(r["yield_earned_during_wait_usd"], 0.0)

    def test_infinite_queue_label_illiquid(self):
        r = self.a.analyze(**_default_kwargs(
            queue_wait_hours=0.0, queue_size_usd=1.0,
            daily_exit_capacity_usd=0.0,
        ))
        self.assertEqual(r["queue_label"], "EXIT_ILLIQUID")

    def test_infinite_queue_risk_score_100(self):
        r = self.a.analyze(**_default_kwargs(
            queue_wait_hours=0.0, queue_size_usd=1.0,
            daily_exit_capacity_usd=0.0,
        ))
        self.assertEqual(r["queue_risk_score"], 100)

    def test_infinite_queue_net_value_without_yield(self):
        # net = position + 0 - price_impact
        r = self.a.analyze(**_default_kwargs(
            queue_wait_hours=0.0, queue_size_usd=1.0,
            daily_exit_capacity_usd=0.0,
            position_size_usd=10_000.0,
            annual_yield_during_wait_pct=0.0,
            price_impact_risk_pct=2.0,
        ))
        self.assertAlmostEqual(r["net_exit_value_usd"], 9_800.0)

    # --- Label checks -------------------------------------------------------

    def test_fast_exit_label(self):
        r = self.a.analyze(**_default_kwargs(
            withdrawal_type="queued", queue_wait_hours=1.5,
            queue_size_usd=0.0, daily_exit_capacity_usd=1_000_000.0,
        ))
        self.assertEqual(r["queue_label"], "FAST_EXIT")

    def test_manageable_queue_label(self):
        r = self.a.analyze(**_default_kwargs(
            withdrawal_type="queued", queue_wait_hours=12.0,
            queue_size_usd=0.0, daily_exit_capacity_usd=1_000_000.0,
        ))
        self.assertEqual(r["queue_label"], "MANAGEABLE_QUEUE")

    def test_long_queue_label(self):
        r = self.a.analyze(**_default_kwargs(
            withdrawal_type="unbonding", queue_wait_hours=120.0,
            queue_size_usd=0.0, daily_exit_capacity_usd=1_000_000.0,
        ))
        self.assertEqual(r["queue_label"], "LONG_QUEUE")

    # --- Input echoed back --------------------------------------------------

    def test_inputs_echoed_in_result(self):
        kw = _default_kwargs(
            queue_wait_hours=10.0, queue_size_usd=200_000.0,
            daily_exit_capacity_usd=500_000.0, position_size_usd=25_000.0,
            annual_yield_during_wait_pct=8.0, price_impact_risk_pct=1.5,
            protocol_name="Compound", withdrawal_type="queued",
        )
        r = self.a.analyze(**kw)
        self.assertEqual(r["queue_wait_hours"], 10.0)
        self.assertEqual(r["queue_size_usd"], 200_000.0)
        self.assertEqual(r["daily_exit_capacity_usd"], 500_000.0)
        self.assertEqual(r["position_size_usd"], 25_000.0)
        self.assertEqual(r["annual_yield_during_wait_pct"], 8.0)
        self.assertEqual(r["price_impact_risk_pct"], 1.5)

    # --- Maturity locked ----------------------------------------------------

    def test_maturity_locked_high_wait(self):
        r = self.a.analyze(**_default_kwargs(
            withdrawal_type="maturity_locked",
            queue_wait_hours=720.0,   # 30 days
            queue_size_usd=0.0, daily_exit_capacity_usd=1_000_000.0,
        ))
        self.assertEqual(r["queue_label"], "EXIT_ILLIQUID")
        self.assertAlmostEqual(r["estimated_wait_days"], 30.0)

    def test_maturity_locked_yield_correct(self):
        # position=100000, yield=12%, wait=30 days
        r = self.a.analyze(**_default_kwargs(
            withdrawal_type="maturity_locked",
            queue_wait_hours=720.0,
            queue_size_usd=0.0, daily_exit_capacity_usd=1_000_000.0,
            position_size_usd=100_000.0,
            annual_yield_during_wait_pct=12.0,
            price_impact_risk_pct=0.0,
        ))
        expected = 100_000.0 * 0.12 * (30.0 / 365.0)
        self.assertAlmostEqual(r["yield_earned_during_wait_usd"], expected, places=4)

    def test_zero_yield_zero_impact(self):
        r = self.a.analyze(**_default_kwargs(
            annual_yield_during_wait_pct=0.0,
            price_impact_risk_pct=0.0,
            position_size_usd=5_000.0,
        ))
        self.assertAlmostEqual(r["price_impact_usd"], 0.0)
        self.assertAlmostEqual(r["net_exit_value_usd"], 5_000.0)

    def test_high_price_impact(self):
        r = self.a.analyze(**_default_kwargs(
            position_size_usd=10_000.0,
            price_impact_risk_pct=50.0,
            annual_yield_during_wait_pct=0.0,
            queue_wait_hours=0.0, queue_size_usd=0.0,
        ))
        self.assertAlmostEqual(r["price_impact_usd"], 5_000.0)
        self.assertAlmostEqual(r["net_exit_value_usd"], 5_000.0)


# ===========================================================================
# TestLogging
# ===========================================================================

class TestLogging(unittest.TestCase):
    """16 tests for analyze_and_log, get_log, and ring-buffer behaviour."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "wq_log.json")
        self.a = DeFiProtocolWithdrawalQueueRiskAnalyzer(log_path=self.log_path)

    def test_log_starts_empty(self):
        self.assertEqual(self.a.get_log(), [])

    def test_single_entry_logged(self):
        self.a.analyze_and_log(**_default_kwargs())
        log = self.a.get_log()
        self.assertEqual(len(log), 1)

    def test_logged_entry_matches_result(self):
        kw = _default_kwargs(protocol_name="Lido")
        result = self.a.analyze_and_log(**kw)
        log = self.a.get_log()
        self.assertEqual(log[0]["protocol_name"], "Lido")
        self.assertEqual(log[0]["queue_risk_score"], result["queue_risk_score"])

    def test_multiple_entries_accumulate(self):
        for i in range(5):
            self.a.analyze_and_log(**_default_kwargs(protocol_name=f"Proto{i}"))
        self.assertEqual(len(self.a.get_log()), 5)

    def test_ring_buffer_caps_at_100(self):
        for i in range(105):
            self.a.analyze_and_log(**_default_kwargs(protocol_name=f"P{i}"))
        log = self.a.get_log()
        self.assertEqual(len(log), LOG_MAX_ENTRIES)

    def test_ring_buffer_keeps_last_100(self):
        for i in range(105):
            self.a.analyze_and_log(**_default_kwargs(protocol_name=f"P{i}"))
        log = self.a.get_log()
        self.assertEqual(log[-1]["protocol_name"], "P104")
        self.assertEqual(log[0]["protocol_name"], "P5")

    def test_log_file_is_valid_json(self):
        self.a.analyze_and_log(**_default_kwargs())
        with open(self.log_path, "r") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_log_persists_across_instances(self):
        self.a.analyze_and_log(**_default_kwargs(protocol_name="Aave"))
        a2 = DeFiProtocolWithdrawalQueueRiskAnalyzer(log_path=self.log_path)
        log = a2.get_log()
        self.assertEqual(log[0]["protocol_name"], "Aave")

    def test_corrupted_log_gracefully_recovered(self):
        with open(self.log_path, "w") as fh:
            fh.write("NOT JSON{{{")
        self.a.analyze_and_log(**_default_kwargs())
        self.assertEqual(len(self.a.get_log()), 1)

    def test_missing_log_returns_empty_list(self):
        log = _load_log(os.path.join(self.tmp, "nonexistent.json"))
        self.assertEqual(log, [])

    def test_analyze_and_log_returns_same_as_analyze(self):
        kw = _default_kwargs(protocol_name="Morpho")
        r1 = self.a.analyze(**kw)
        r2 = self.a.analyze_and_log(**kw)
        # Same fields (generated_at may differ by 1 second)
        self.assertEqual(r1["queue_label"], r2["queue_label"])
        self.assertEqual(r1["queue_risk_score"], r2["queue_risk_score"])

    def test_atomic_write_creates_file(self):
        path = os.path.join(self.tmp, "atomic_test.json")
        _atomic_write(path, [{"x": 1}])
        self.assertTrue(os.path.isfile(path))

    def test_atomic_write_no_tmp_left(self):
        path = os.path.join(self.tmp, "atomic_test2.json")
        _atomic_write(path, [])
        tmp_files = [f for f in os.listdir(self.tmp) if f.startswith(".tmp_")]
        self.assertEqual(tmp_files, [])

    def test_log_entries_json_serializable(self):
        # Infinite queue case must also serialize (None replaces inf)
        self.a.analyze_and_log(**_default_kwargs(
            queue_wait_hours=0.0, queue_size_usd=1.0,
            daily_exit_capacity_usd=0.0,
        ))
        with open(self.log_path, "r") as fh:
            data = json.load(fh)
        self.assertIsNone(data[0]["estimated_wait_hours"])

    def test_exact_100_entries_no_trim(self):
        for i in range(100):
            self.a.analyze_and_log(**_default_kwargs(protocol_name=f"P{i}"))
        self.assertEqual(len(self.a.get_log()), 100)

    def test_101st_entry_trims_oldest(self):
        for i in range(101):
            self.a.analyze_and_log(**_default_kwargs(protocol_name=f"P{i}"))
        log = self.a.get_log()
        self.assertEqual(len(log), 100)
        self.assertEqual(log[0]["protocol_name"], "P1")


# ===========================================================================
# TestEdgeCases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    """13 edge/boundary-condition tests."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a = _mk_analyzer(self.tmp)

    def test_very_large_position(self):
        r = self.a.analyze(**_default_kwargs(position_size_usd=1e9))
        self.assertGreater(r["net_exit_value_usd"], 0)

    def test_very_small_position(self):
        r = self.a.analyze(**_default_kwargs(position_size_usd=0.01))
        self.assertGreater(r["net_exit_value_usd"], 0)

    def test_100pct_price_impact(self):
        r = self.a.analyze(**_default_kwargs(
            position_size_usd=10_000.0,
            price_impact_risk_pct=100.0,
            annual_yield_during_wait_pct=0.0,
            queue_wait_hours=0.0, queue_size_usd=0.0,
        ))
        self.assertAlmostEqual(r["price_impact_usd"], 10_000.0)

    def test_zero_yield_does_not_affect_net(self):
        r = self.a.analyze(**_default_kwargs(
            annual_yield_during_wait_pct=0.0,
            price_impact_risk_pct=0.0,
            position_size_usd=7_500.0,
            queue_wait_hours=24.0, queue_size_usd=0.0,
        ))
        self.assertAlmostEqual(r["net_exit_value_usd"], 7_500.0)

    def test_all_withdrawal_types_pass(self):
        for wt in VALID_WITHDRAWAL_TYPES:
            r = self.a.analyze(**_default_kwargs(withdrawal_type=wt))
            self.assertEqual(r["withdrawal_type"], wt)

    def test_score_is_between_0_and_100(self):
        for hours in [0, 0.5, 2, 24, 100, 168, 300, 500]:
            score = _compute_queue_risk_score(float(hours))
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_label_always_in_valid_set(self):
        valid = {"INSTANT_EXIT", "FAST_EXIT", "MANAGEABLE_QUEUE",
                 "LONG_QUEUE", "EXIT_ILLIQUID"}
        for hours in [0, 0.5, 2, 2.5, 24, 48, 168, 200, 500]:
            label = _compute_queue_label(float(hours))
            self.assertIn(label, valid)

    def test_large_queue_score_100(self):
        r = self.a.analyze(**_default_kwargs(
            queue_size_usd=100_000_000.0, daily_exit_capacity_usd=100_000.0,
            queue_wait_hours=0.0,
        ))
        self.assertEqual(r["queue_risk_score"], 100)

    def test_protocol_name_whitespace_stripped_in_error(self):
        with self.assertRaises(ValueError):
            self.a.analyze(**_default_kwargs(protocol_name="  "))

    def test_identical_calls_produce_consistent_labels(self):
        kw = _default_kwargs()
        r1 = self.a.analyze(**kw)
        r2 = self.a.analyze(**kw)
        self.assertEqual(r1["queue_label"], r2["queue_label"])
        self.assertEqual(r1["queue_risk_score"], r2["queue_risk_score"])

    def test_wait_days_equals_hours_divided_by_24(self):
        r = self.a.analyze(**_default_kwargs(
            queue_wait_hours=48.0, queue_size_usd=0.0,
        ))
        self.assertAlmostEqual(r["estimated_wait_days"], 2.0)

    def test_log_constants(self):
        self.assertEqual(LOG_MAX_ENTRIES, 100)
        self.assertEqual(HOURS_PER_DAY, 24.0)
        self.assertEqual(DAYS_PER_YEAR, 365.0)

    def test_score_breakpoints_structure(self):
        self.assertGreater(len(SCORE_BREAKPOINTS), 2)
        hours = [bp[0] for bp in SCORE_BREAKPOINTS]
        scores = [bp[1] for bp in SCORE_BREAKPOINTS]
        # Hours should be increasing
        for i in range(len(hours) - 1):
            self.assertLess(hours[i], hours[i + 1])
        # Scores should be non-decreasing
        for i in range(len(scores) - 1):
            self.assertLessEqual(scores[i], scores[i + 1])


if __name__ == "__main__":
    unittest.main()
