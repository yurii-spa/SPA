"""
Tests for MP-1081: ProtocolDeFiPositionHealthMonitor
Run: python3 -m unittest spa_core.tests.test_protocol_defi_position_health_monitor
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from spa_core.analytics.protocol_defi_position_health_monitor import (
    ProtocolDeFiPositionHealthMonitor,
    _clamp,
    _compute_net_pnl_usd,
    _compute_net_pnl_pct,
    _compute_annualized_return,
    _health_factor_risk,
    _il_risk,
    _lock_risk,
    _pnl_risk,
    _exit_cost_risk,
    _compute_position_risk_score,
    _compute_position_label,
    _monitor_single,
    _atomic_write,
    _append_log,
    LOG_CAP,
    VALID_POSITION_TYPES,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_data(**overrides):
    base = {
        "protocol_name": "Aave",
        "position_type": "lending",
        "entry_value_usd": 10_000.0,
        "current_value_usd": 10_500.0,
        "unrealized_pnl_usd": 500.0,
        "days_held": 30.0,
        "apy_earned_pct": 5.0,
        "health_factor": 2.0,
        "liquidation_threshold_pct": 80.0,
        "il_pct": None,
        "lock_remaining_days": 0.0,
        "exit_cost_usd": 50.0,
    }
    base.update(overrides)
    return base


def make_lp_data(**overrides):
    base = make_data(
        position_type="lp",
        health_factor=None,
        il_pct=3.0,
    )
    base.update(overrides)
    return base


def make_staking_data(**overrides):
    base = make_data(
        position_type="staking",
        health_factor=None,
        il_pct=None,
        lock_remaining_days=60.0,
    )
    base.update(overrides)
    return base


# ── _clamp ─────────────────────────────────────────────────────────────────────

class TestClamp(unittest.TestCase):

    def test_within_range(self):
        self.assertEqual(_clamp(50.0), 50.0)

    def test_below_min(self):
        self.assertEqual(_clamp(-1.0), 0.0)

    def test_above_max(self):
        self.assertEqual(_clamp(200.0), 100.0)

    def test_at_zero(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_at_hundred(self):
        self.assertEqual(_clamp(100.0), 100.0)

    def test_custom_lo(self):
        self.assertEqual(_clamp(3.0, 5.0, 90.0), 5.0)

    def test_custom_hi(self):
        self.assertEqual(_clamp(95.0, 5.0, 90.0), 90.0)


# ── _compute_net_pnl_usd ──────────────────────────────────────────────────────

class TestComputeNetPnlUsd(unittest.TestCase):

    def test_positive_pnl_minus_cost(self):
        self.assertAlmostEqual(_compute_net_pnl_usd(500.0, 50.0), 450.0)

    def test_zero_cost(self):
        self.assertAlmostEqual(_compute_net_pnl_usd(200.0, 0.0), 200.0)

    def test_loss(self):
        self.assertAlmostEqual(_compute_net_pnl_usd(-300.0, 50.0), -350.0)

    def test_cost_exceeds_pnl(self):
        self.assertAlmostEqual(_compute_net_pnl_usd(100.0, 200.0), -100.0)

    def test_zero_unrealized(self):
        self.assertAlmostEqual(_compute_net_pnl_usd(0.0, 75.0), -75.0)


# ── _compute_net_pnl_pct ──────────────────────────────────────────────────────

class TestComputeNetPnlPct(unittest.TestCase):

    def test_basic_gain(self):
        result = _compute_net_pnl_pct(500.0, 10_000.0)
        self.assertAlmostEqual(result, 5.0)

    def test_zero_entry_returns_zero(self):
        self.assertEqual(_compute_net_pnl_pct(500.0, 0.0), 0.0)

    def test_loss_percentage(self):
        result = _compute_net_pnl_pct(-1000.0, 10_000.0)
        self.assertAlmostEqual(result, -10.0)

    def test_zero_pnl(self):
        self.assertEqual(_compute_net_pnl_pct(0.0, 10_000.0), 0.0)

    def test_fractional(self):
        result = _compute_net_pnl_pct(1.0, 3.0)
        self.assertAlmostEqual(result, 33.3333, places=3)


# ── _compute_annualized_return ────────────────────────────────────────────────

class TestComputeAnnualizedReturn(unittest.TestCase):

    def test_one_year_held(self):
        result = _compute_annualized_return(10.0, 365.0)
        self.assertAlmostEqual(result, 10.0)

    def test_half_year(self):
        result = _compute_annualized_return(5.0, 182.5)
        self.assertAlmostEqual(result, 10.0, places=1)

    def test_zero_days_returns_zero(self):
        self.assertEqual(_compute_annualized_return(10.0, 0.0), 0.0)

    def test_negative_days_returns_zero(self):
        self.assertEqual(_compute_annualized_return(10.0, -5.0), 0.0)

    def test_large_gain_capped(self):
        result = _compute_annualized_return(500.0, 1.0)
        self.assertLessEqual(result, 1000.0)

    def test_large_loss_capped(self):
        result = _compute_annualized_return(-500.0, 1.0)
        self.assertGreaterEqual(result, -1000.0)

    def test_negative_return(self):
        result = _compute_annualized_return(-5.0, 365.0)
        self.assertAlmostEqual(result, -5.0)


# ── _health_factor_risk ───────────────────────────────────────────────────────

class TestHealthFactorRisk(unittest.TestCase):

    def test_non_lending_returns_zero(self):
        self.assertEqual(_health_factor_risk("lp", 1.05, 80.0), 0.0)

    def test_none_hf_returns_zero(self):
        self.assertEqual(_health_factor_risk("lending", None, 80.0), 0.0)

    def test_critical_hf_below_1_1(self):
        risk = _health_factor_risk("lending", 1.05, 80.0)
        self.assertEqual(risk, 40.0)

    def test_at_risk_hf_below_1_3(self):
        risk = _health_factor_risk("lending", 1.2, 80.0)
        self.assertEqual(risk, 25.0)

    def test_safe_hf_above_3(self):
        risk = _health_factor_risk("lending", 3.5, 80.0)
        self.assertEqual(risk, 0.0)

    def test_hf_between_1_3_and_3(self):
        risk = _health_factor_risk("lending", 2.0, 80.0)
        self.assertGreater(risk, 0.0)
        self.assertLess(risk, 25.0)

    def test_staking_no_hf_risk(self):
        self.assertEqual(_health_factor_risk("staking", 2.0, 80.0), 0.0)


# ── _il_risk ──────────────────────────────────────────────────────────────────

class TestIlRisk(unittest.TestCase):

    def test_non_lp_returns_zero(self):
        self.assertEqual(_il_risk("lending", 15.0), 0.0)

    def test_none_il_returns_zero(self):
        self.assertEqual(_il_risk("lp", None), 0.0)

    def test_high_il_above_10pct(self):
        risk = _il_risk("lp", 15.0)
        self.assertEqual(risk, 30.0)

    def test_moderate_il_5_to_10(self):
        risk = _il_risk("lp", 7.0)
        self.assertEqual(risk, 15.0)

    def test_low_il_below_5(self):
        risk = _il_risk("lp", 2.5)
        self.assertGreater(risk, 0.0)
        self.assertLess(risk, 10.0)

    def test_zero_il(self):
        self.assertEqual(_il_risk("lp", 0.0), 0.0)

    def test_negative_il_treated_as_absolute(self):
        # negative IL can happen if provided as negative; abs() used
        risk_pos = _il_risk("lp", 12.0)
        risk_neg = _il_risk("lp", -12.0)
        self.assertEqual(risk_pos, risk_neg)


# ── _lock_risk ────────────────────────────────────────────────────────────────

class TestLockRisk(unittest.TestCase):

    def test_no_lock_zero_risk(self):
        self.assertEqual(_lock_risk(0.0), 0.0)

    def test_negative_lock_zero_risk(self):
        self.assertEqual(_lock_risk(-5.0), 0.0)

    def test_long_lock_max_risk(self):
        self.assertEqual(_lock_risk(100.0), 20.0)

    def test_moderate_lock(self):
        risk = _lock_risk(15.0)
        self.assertEqual(risk, 10.0)

    def test_short_lock_low_risk(self):
        risk = _lock_risk(3.0)
        self.assertLess(risk, 10.0)
        self.assertGreater(risk, 0.0)

    def test_exactly_7_days_low(self):
        risk = _lock_risk(7.0)
        self.assertLessEqual(risk, 10.0)

    def test_exactly_30_days_moderate(self):
        risk = _lock_risk(30.0)
        self.assertEqual(risk, 10.0)

    def test_31_days_high(self):
        risk = _lock_risk(31.0)
        self.assertEqual(risk, 20.0)


# ── _pnl_risk ─────────────────────────────────────────────────────────────────

class TestPnlRisk(unittest.TestCase):

    def test_positive_pnl_no_risk(self):
        self.assertEqual(_pnl_risk(5.0), 0.0)

    def test_zero_pnl_no_risk(self):
        self.assertEqual(_pnl_risk(0.0), 0.0)

    def test_small_loss(self):
        risk = _pnl_risk(-5.0)
        self.assertAlmostEqual(risk, 5.0)

    def test_large_loss_capped_at_20(self):
        risk = _pnl_risk(-50.0)
        self.assertEqual(risk, 20.0)

    def test_moderate_loss(self):
        risk = _pnl_risk(-10.0)
        self.assertAlmostEqual(risk, 10.0)

    def test_exactly_minus_20(self):
        risk = _pnl_risk(-20.0)
        self.assertAlmostEqual(risk, 20.0)


# ── _exit_cost_risk ───────────────────────────────────────────────────────────

class TestExitCostRisk(unittest.TestCase):

    def test_zero_exit_cost(self):
        self.assertEqual(_exit_cost_risk(0.0, 10_000.0), 0.0)

    def test_zero_current_value(self):
        self.assertEqual(_exit_cost_risk(100.0, 0.0), 0.0)

    def test_small_exit_cost_fraction(self):
        # 1% exit cost → 1*2=2 pts
        risk = _exit_cost_risk(100.0, 10_000.0)
        self.assertAlmostEqual(risk, 2.0)

    def test_high_exit_cost_capped(self):
        # 10% exit cost → 10*2=20 but capped at 10
        risk = _exit_cost_risk(1000.0, 10_000.0)
        self.assertEqual(risk, 10.0)

    def test_moderate_exit_cost(self):
        # 3% → 6 pts
        risk = _exit_cost_risk(300.0, 10_000.0)
        self.assertAlmostEqual(risk, 6.0)


# ── _compute_position_risk_score ──────────────────────────────────────────────

class TestComputePositionRiskScore(unittest.TestCase):

    def test_safe_lending_position(self):
        score = _compute_position_risk_score(
            "lending", 2.5, 80.0, None, 0.0, 5.0, 10.0, 10_000.0
        )
        self.assertLess(score, 30.0)

    def test_critical_lending_hf(self):
        score = _compute_position_risk_score(
            "lending", 1.05, 80.0, None, 0.0, 0.0, 0.0, 10_000.0
        )
        self.assertGreaterEqual(score, 40.0)

    def test_high_il_lp(self):
        score = _compute_position_risk_score(
            "lp", None, 0.0, 15.0, 0.0, 0.0, 0.0, 10_000.0
        )
        self.assertGreaterEqual(score, 30.0)

    def test_long_lock_staking(self):
        score = _compute_position_risk_score(
            "staking", None, 0.0, None, 90.0, 0.0, 0.0, 10_000.0
        )
        self.assertGreaterEqual(score, 20.0)

    def test_bounded_0_to_100(self):
        score = _compute_position_risk_score(
            "lending", 1.0, 80.0, 50.0, 365.0, -50.0, 5000.0, 10_000.0
        )
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_healthy_vault(self):
        score = _compute_position_risk_score(
            "vault", None, 0.0, None, 0.0, 10.0, 5.0, 10_000.0
        )
        self.assertLess(score, 10.0)


# ── _compute_position_label ───────────────────────────────────────────────────

class TestComputePositionLabel(unittest.TestCase):

    def test_thriving(self):
        self.assertEqual(_compute_position_label(5.0), "THRIVING")

    def test_healthy(self):
        self.assertEqual(_compute_position_label(15.0), "HEALTHY")

    def test_neutral(self):
        self.assertEqual(_compute_position_label(35.0), "NEUTRAL")

    def test_at_risk(self):
        self.assertEqual(_compute_position_label(60.0), "AT_RISK")

    def test_critical(self):
        self.assertEqual(_compute_position_label(80.0), "CRITICAL_ACTION_NEEDED")

    def test_boundary_10_is_healthy(self):
        self.assertEqual(_compute_position_label(10.0), "HEALTHY")

    def test_boundary_30_is_neutral(self):
        self.assertEqual(_compute_position_label(30.0), "NEUTRAL")

    def test_boundary_50_is_at_risk(self):
        self.assertEqual(_compute_position_label(50.0), "AT_RISK")

    def test_boundary_75_is_critical(self):
        self.assertEqual(_compute_position_label(75.0), "CRITICAL_ACTION_NEEDED")

    def test_zero_risk_thriving(self):
        self.assertEqual(_compute_position_label(0.0), "THRIVING")

    def test_100_risk_critical(self):
        self.assertEqual(_compute_position_label(100.0), "CRITICAL_ACTION_NEEDED")


# ── _monitor_single ───────────────────────────────────────────────────────────

class TestMonitorSingle(unittest.TestCase):

    def test_output_keys_present(self):
        result = _monitor_single(make_data())
        for key in [
            "protocol_name", "position_type", "entry_value_usd",
            "current_value_usd", "net_pnl_usd", "net_pnl_pct",
            "annualized_return_pct", "apy_earned_pct",
            "position_risk_score", "position_label",
            "days_held", "lock_remaining_days",
        ]:
            self.assertIn(key, result)

    def test_protocol_name_passed_through(self):
        result = _monitor_single(make_data(protocol_name="Compound"))
        self.assertEqual(result["protocol_name"], "Compound")

    def test_net_pnl_computed(self):
        result = _monitor_single(make_data(
            unrealized_pnl_usd=500.0,
            exit_cost_usd=50.0,
        ))
        self.assertAlmostEqual(result["net_pnl_usd"], 450.0)

    def test_net_pnl_pct_computed(self):
        result = _monitor_single(make_data(
            entry_value_usd=10_000.0,
            unrealized_pnl_usd=500.0,
            exit_cost_usd=50.0,
        ))
        self.assertAlmostEqual(result["net_pnl_pct"], 4.5)

    def test_annualized_return_positive(self):
        result = _monitor_single(make_data(
            entry_value_usd=10_000.0,
            unrealized_pnl_usd=500.0,
            exit_cost_usd=0.0,
            days_held=365.0,
        ))
        self.assertAlmostEqual(result["annualized_return_pct"], 5.0)

    def test_position_label_valid(self):
        valid = {"THRIVING", "HEALTHY", "NEUTRAL", "AT_RISK", "CRITICAL_ACTION_NEEDED"}
        result = _monitor_single(make_data())
        self.assertIn(result["position_label"], valid)

    def test_risk_score_bounded(self):
        result = _monitor_single(make_data())
        self.assertGreaterEqual(result["position_risk_score"], 0.0)
        self.assertLessEqual(result["position_risk_score"], 100.0)

    def test_critical_lending_hf(self):
        # HF=1.05 adds 40 risk; add losses + lock to push over 75 threshold
        result = _monitor_single(make_data(
            health_factor=1.05,
            unrealized_pnl_usd=-3000.0,   # large loss → pnl_risk +20
            exit_cost_usd=200.0,           # exit_cost_risk adds more
            lock_remaining_days=60.0,      # lock_risk +20
        ))
        self.assertEqual(result["position_label"], "CRITICAL_ACTION_NEEDED")

    def test_lp_high_il(self):
        result = _monitor_single(make_lp_data(il_pct=20.0))
        self.assertGreaterEqual(result["position_risk_score"], 30.0)

    def test_staking_long_lock(self):
        result = _monitor_single(make_staking_data(lock_remaining_days=90.0))
        self.assertGreaterEqual(result["position_risk_score"], 20.0)

    def test_thriving_vault_no_risk_factors(self):
        result = _monitor_single(make_data(
            position_type="vault",
            health_factor=None,
            il_pct=None,
            lock_remaining_days=0.0,
            exit_cost_usd=0.0,
            unrealized_pnl_usd=1000.0,
            entry_value_usd=10_000.0,
        ))
        self.assertEqual(result["position_label"], "THRIVING")

    def test_invalid_position_type_defaults_vault(self):
        result = _monitor_single(make_data(position_type="unknown_type"))
        self.assertEqual(result["position_type"], "vault")

    def test_missing_protocol_name_defaults(self):
        d = make_data()
        del d["protocol_name"]
        result = _monitor_single(d)
        self.assertEqual(result["protocol_name"], "UNKNOWN")

    def test_zero_entry_value(self):
        result = _monitor_single(make_data(entry_value_usd=0.0))
        self.assertEqual(result["net_pnl_pct"], 0.0)

    def test_days_held_passed_through(self):
        result = _monitor_single(make_data(days_held=45.0))
        self.assertEqual(result["days_held"], 45.0)

    def test_lock_remaining_passed_through(self):
        result = _monitor_single(make_data(lock_remaining_days=14.0))
        self.assertEqual(result["lock_remaining_days"], 14.0)

    def test_apy_earned_passed_through(self):
        result = _monitor_single(make_data(apy_earned_pct=8.5))
        self.assertAlmostEqual(result["apy_earned_pct"], 8.5)

    def test_loss_position_not_thriving(self):
        result = _monitor_single(make_data(
            unrealized_pnl_usd=-2000.0,
            exit_cost_usd=100.0,
        ))
        self.assertNotEqual(result["position_label"], "THRIVING")

    def test_health_factor_none_for_lp(self):
        result = _monitor_single(make_lp_data(health_factor=None))
        self.assertIn(result["position_label"], {"THRIVING", "HEALTHY", "NEUTRAL"})


# ── _atomic_write ─────────────────────────────────────────────────────────────

class TestAtomicWrite(unittest.TestCase):

    def test_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.json")
            _atomic_write(path, {"x": 42})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["x"], 42)

    def test_writes_list(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.json")
            _atomic_write(path, [{"a": 1}])
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data[0]["a"], 1)

    def test_creates_subdirectory(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "out.json")
            _atomic_write(path, {})
            self.assertTrue(os.path.exists(path))

    def test_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.json")
            _atomic_write(path, {"v": 1})
            _atomic_write(path, {"v": 2})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["v"], 2)


# ── _append_log ───────────────────────────────────────────────────────────────

class TestAppendLog(unittest.TestCase):

    def _sample_result(self):
        return {
            "protocol_name": "Aave",
            "position_type": "lending",
            "net_pnl_usd": 450.0,
            "position_risk_score": 5.0,
            "position_label": "THRIVING",
        }

    def test_creates_log_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _append_log(self._sample_result(), path)
            self.assertTrue(os.path.exists(path))

    def test_log_is_list(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _append_log(self._sample_result(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_entry_has_ts(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _append_log(self._sample_result(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertIn("ts", data[0])

    def test_entry_has_label(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _append_log(self._sample_result(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data[0]["position_label"], "THRIVING")

    def test_multiple_appends(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for _ in range(5):
                _append_log(self._sample_result(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for _ in range(LOG_CAP + 15):
                _append_log(self._sample_result(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), LOG_CAP)

    def test_recovers_from_corrupt_log(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as f:
                f.write("GARBAGE{{")
            _append_log(self._sample_result(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)

    def test_non_list_log_reset(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as f:
                json.dump({"not": "a list"}, f)
            _append_log(self._sample_result(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)


# ── ProtocolDeFiPositionHealthMonitor (main class) ───────────────────────────

class TestProtocolDeFiPositionHealthMonitor(unittest.TestCase):

    def setUp(self):
        self.monitor = ProtocolDeFiPositionHealthMonitor()
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_log.json")
        self.cfg = {"log_path": self.log_path, "write_log": True}

    def test_returns_dict(self):
        result = self.monitor.monitor(make_data(), self.cfg)
        self.assertIsInstance(result, dict)

    def test_raises_on_non_dict(self):
        with self.assertRaises(TypeError):
            self.monitor.monitor(["not", "a", "dict"], self.cfg)

    def test_output_keys_complete(self):
        result = self.monitor.monitor(make_data(), self.cfg)
        for key in ["net_pnl_usd", "net_pnl_pct", "annualized_return_pct",
                    "position_risk_score", "position_label"]:
            self.assertIn(key, result)

    def test_no_write_log_skips_file(self):
        cfg = {"log_path": self.log_path, "write_log": False}
        self.monitor.monitor(make_data(), cfg)
        self.assertFalse(os.path.exists(self.log_path))

    def test_write_log_creates_file(self):
        self.monitor.monitor(make_data(), self.cfg)
        self.assertTrue(os.path.exists(self.log_path))

    def test_multiple_calls_accumulate_log(self):
        for _ in range(4):
            self.monitor.monitor(make_data(), self.cfg)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 4)

    def test_thriving_healthy_lending(self):
        result = self.monitor.monitor(make_data(
            health_factor=3.0,
            unrealized_pnl_usd=500.0,
            exit_cost_usd=10.0,
            lock_remaining_days=0.0,
        ), self.cfg)
        self.assertIn(result["position_label"], {"THRIVING", "HEALTHY"})

    def test_critical_lending_low_hf(self):
        # HF=1.05 (+40) + losses (+20) + long lock (+20) → ≥75 CRITICAL
        result = self.monitor.monitor(make_data(
            health_factor=1.05,
            unrealized_pnl_usd=-3000.0,
            exit_cost_usd=200.0,
            lock_remaining_days=60.0,
        ), self.cfg)
        self.assertEqual(result["position_label"], "CRITICAL_ACTION_NEEDED")

    def test_lp_at_risk_high_il(self):
        result = self.monitor.monitor(make_lp_data(il_pct=25.0), self.cfg)
        self.assertGreaterEqual(result["position_risk_score"], 30.0)

    def test_staking_neutral_long_lock(self):
        result = self.monitor.monitor(make_staking_data(
            lock_remaining_days=90.0,
            unrealized_pnl_usd=100.0,
            exit_cost_usd=0.0,
        ), self.cfg)
        self.assertIn(result["position_label"], {"NEUTRAL", "AT_RISK", "HEALTHY"})

    def test_vault_no_config_uses_defaults(self):
        result = self.monitor.monitor(make_data(position_type="vault"))
        self.assertIn("position_label", result)

    def test_none_config_uses_defaults(self):
        result = self.monitor.monitor(make_data())
        self.assertIn("position_label", result)

    def test_net_pnl_correct(self):
        result = self.monitor.monitor(make_data(
            unrealized_pnl_usd=1000.0,
            exit_cost_usd=100.0,
        ), self.cfg)
        self.assertAlmostEqual(result["net_pnl_usd"], 900.0)

    def test_annualized_return_365_days(self):
        result = self.monitor.monitor(make_data(
            entry_value_usd=10_000.0,
            unrealized_pnl_usd=1000.0,
            exit_cost_usd=0.0,
            days_held=365.0,
        ), self.cfg)
        self.assertAlmostEqual(result["annualized_return_pct"], 10.0)

    def test_position_type_lp_accepted(self):
        result = self.monitor.monitor(make_lp_data(), self.cfg)
        self.assertEqual(result["position_type"], "lp")

    def test_position_type_staking_accepted(self):
        result = self.monitor.monitor(make_staking_data(), self.cfg)
        self.assertEqual(result["position_type"], "staking")

    def test_position_type_vault_accepted(self):
        result = self.monitor.monitor(make_data(position_type="vault"), self.cfg)
        self.assertEqual(result["position_type"], "vault")

    def test_risk_score_in_valid_range(self):
        result = self.monitor.monitor(make_data(), self.cfg)
        self.assertGreaterEqual(result["position_risk_score"], 0.0)
        self.assertLessEqual(result["position_risk_score"], 100.0)

    def test_loss_position_raises_risk(self):
        healthy = self.monitor.monitor(make_data(unrealized_pnl_usd=1000.0), self.cfg)
        losing = self.monitor.monitor(make_data(unrealized_pnl_usd=-2000.0), self.cfg)
        self.assertGreater(losing["position_risk_score"], healthy["position_risk_score"])

    def test_protocol_name_in_result(self):
        result = self.monitor.monitor(make_data(protocol_name="MorphoBlue"), self.cfg)
        self.assertEqual(result["protocol_name"], "MorphoBlue")

    def test_apy_earned_in_result(self):
        result = self.monitor.monitor(make_data(apy_earned_pct=12.5), self.cfg)
        self.assertAlmostEqual(result["apy_earned_pct"], 12.5)

    def test_valid_position_types_all_accepted(self):
        for ptype in VALID_POSITION_TYPES:
            d = make_data(position_type=ptype, health_factor=None, il_pct=None)
            result = self.monitor.monitor(d, self.cfg)
            self.assertEqual(result["position_type"], ptype)


if __name__ == "__main__":
    unittest.main()
