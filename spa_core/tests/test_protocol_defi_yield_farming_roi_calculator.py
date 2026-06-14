"""
Tests for MP-1097 ProtocolDeFiYieldFarmingROICalculator
≥110 unittest tests — pure stdlib, no third-party dependencies.

Run:
    python3 -m unittest spa_core.tests.test_protocol_defi_yield_farming_roi_calculator -v
"""

import json
import math
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
    _gross_yield_usd,
    _il_loss_usd,
    _reward_decay_loss_usd,
    _protocol_fee_usd,
    _net_yield_usd,
    _net_roi_pct,
    _annualized_net_roi_pct,
    _roi_label,
    _atomic_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    """Return path to a temp file that doesn't yet exist."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _base_params(**overrides) -> dict:
    p = {
        "protocol_name": "TestFarm",
        "initial_investment_usd": 10_000.0,
        "gross_apy_pct": 20.0,
        "il_risk_pct": 5.0,
        "reward_token_decay_pct": 10.0,
        "entry_cost_usd": 50.0,
        "exit_cost_usd": 50.0,
        "holding_days": 90,
        "protocol_fee_pct": 0.5,
    }
    p.update(overrides)
    return p


# ---------------------------------------------------------------------------
# Tests: _gross_yield_usd
# ---------------------------------------------------------------------------

class TestGrossYieldUsd(unittest.TestCase):

    def test_basic_calculation(self):
        # 10000 * 0.20 * 90/365
        expected = 10000.0 * 0.20 * (90 / 365.0)
        self.assertAlmostEqual(_gross_yield_usd(10000.0, 20.0, 90), expected, places=6)

    def test_zero_investment_returns_zero(self):
        self.assertEqual(_gross_yield_usd(0.0, 20.0, 90), 0.0)

    def test_negative_investment_returns_zero(self):
        self.assertEqual(_gross_yield_usd(-1000.0, 20.0, 90), 0.0)

    def test_zero_apy_returns_zero(self):
        self.assertEqual(_gross_yield_usd(10000.0, 0.0, 90), 0.0)

    def test_negative_apy_returns_zero(self):
        self.assertEqual(_gross_yield_usd(10000.0, -5.0, 90), 0.0)

    def test_zero_days_returns_zero(self):
        self.assertEqual(_gross_yield_usd(10000.0, 20.0, 0), 0.0)

    def test_negative_days_returns_zero(self):
        self.assertEqual(_gross_yield_usd(10000.0, 20.0, -10), 0.0)

    def test_full_year(self):
        # 10000 * 0.10 * 365/365 = 1000
        self.assertAlmostEqual(_gross_yield_usd(10000.0, 10.0, 365), 1000.0, places=6)

    def test_high_apy(self):
        # 50000 * 1.0 * 180/365
        expected = 50000.0 * 1.0 * (180 / 365.0)
        self.assertAlmostEqual(_gross_yield_usd(50000.0, 100.0, 180), expected, places=4)

    def test_small_holding_period(self):
        # 1 day holding
        expected = 1000.0 * 0.05 * (1 / 365.0)
        self.assertAlmostEqual(_gross_yield_usd(1000.0, 5.0, 1), expected, places=8)

    def test_returns_float(self):
        self.assertIsInstance(_gross_yield_usd(10000.0, 20.0, 90), float)

    def test_scales_linearly_with_investment(self):
        g1 = _gross_yield_usd(10000.0, 20.0, 90)
        g2 = _gross_yield_usd(20000.0, 20.0, 90)
        self.assertAlmostEqual(g2 / g1, 2.0, places=6)

    def test_scales_linearly_with_apy(self):
        g1 = _gross_yield_usd(10000.0, 10.0, 90)
        g2 = _gross_yield_usd(10000.0, 20.0, 90)
        self.assertAlmostEqual(g2 / g1, 2.0, places=6)

    def test_scales_linearly_with_days(self):
        g1 = _gross_yield_usd(10000.0, 20.0, 90)
        g2 = _gross_yield_usd(10000.0, 20.0, 180)
        self.assertAlmostEqual(g2 / g1, 2.0, places=6)


# ---------------------------------------------------------------------------
# Tests: _il_loss_usd
# ---------------------------------------------------------------------------

class TestIlLossUsd(unittest.TestCase):

    def test_basic(self):
        # 10000 * 5% = 500
        self.assertAlmostEqual(_il_loss_usd(10000.0, 5.0), 500.0, places=6)

    def test_zero_investment_returns_zero(self):
        self.assertEqual(_il_loss_usd(0.0, 5.0), 0.0)

    def test_negative_investment_returns_zero(self):
        self.assertEqual(_il_loss_usd(-500.0, 5.0), 0.0)

    def test_zero_il_risk_returns_zero(self):
        self.assertEqual(_il_loss_usd(10000.0, 0.0), 0.0)

    def test_negative_il_risk_returns_zero(self):
        self.assertEqual(_il_loss_usd(10000.0, -5.0), 0.0)

    def test_100pct_il_risk(self):
        # 10000 * 100% = 10000
        self.assertAlmostEqual(_il_loss_usd(10000.0, 100.0), 10000.0, places=6)

    def test_scales_with_investment(self):
        il1 = _il_loss_usd(10000.0, 5.0)
        il2 = _il_loss_usd(20000.0, 5.0)
        self.assertAlmostEqual(il2 / il1, 2.0, places=6)

    def test_returns_float(self):
        self.assertIsInstance(_il_loss_usd(10000.0, 5.0), float)

    def test_small_il_risk(self):
        expected = 50000.0 * 0.001
        self.assertAlmostEqual(_il_loss_usd(50000.0, 0.1), expected, places=4)


# ---------------------------------------------------------------------------
# Tests: _reward_decay_loss_usd
# ---------------------------------------------------------------------------

class TestRewardDecayLossUsd(unittest.TestCase):

    def test_basic(self):
        # gross=1000, decay=20% → 200
        self.assertAlmostEqual(_reward_decay_loss_usd(1000.0, 20.0), 200.0, places=6)

    def test_zero_gross_returns_zero(self):
        self.assertEqual(_reward_decay_loss_usd(0.0, 50.0), 0.0)

    def test_negative_gross_returns_zero(self):
        self.assertEqual(_reward_decay_loss_usd(-100.0, 50.0), 0.0)

    def test_zero_decay_returns_zero(self):
        self.assertEqual(_reward_decay_loss_usd(1000.0, 0.0), 0.0)

    def test_negative_decay_returns_zero(self):
        self.assertEqual(_reward_decay_loss_usd(1000.0, -10.0), 0.0)

    def test_100pct_decay_equals_full_gross(self):
        self.assertAlmostEqual(_reward_decay_loss_usd(1000.0, 100.0), 1000.0, places=6)

    def test_200pct_decay_capped_at_gross(self):
        # Can't lose more than gross yield through token decay
        self.assertAlmostEqual(_reward_decay_loss_usd(1000.0, 200.0), 1000.0, places=6)

    def test_50pct_decay(self):
        self.assertAlmostEqual(_reward_decay_loss_usd(500.0, 50.0), 250.0, places=6)

    def test_returns_float(self):
        self.assertIsInstance(_reward_decay_loss_usd(500.0, 20.0), float)

    def test_scales_with_gross(self):
        d1 = _reward_decay_loss_usd(1000.0, 10.0)
        d2 = _reward_decay_loss_usd(2000.0, 10.0)
        self.assertAlmostEqual(d2 / d1, 2.0, places=6)


# ---------------------------------------------------------------------------
# Tests: _protocol_fee_usd
# ---------------------------------------------------------------------------

class TestProtocolFeeUsd(unittest.TestCase):

    def test_basic(self):
        # gross=1000, fee=2% → 20
        self.assertAlmostEqual(_protocol_fee_usd(1000.0, 2.0), 20.0, places=6)

    def test_zero_gross_returns_zero(self):
        self.assertEqual(_protocol_fee_usd(0.0, 2.0), 0.0)

    def test_negative_gross_returns_zero(self):
        self.assertEqual(_protocol_fee_usd(-100.0, 2.0), 0.0)

    def test_zero_fee_returns_zero(self):
        self.assertEqual(_protocol_fee_usd(1000.0, 0.0), 0.0)

    def test_negative_fee_returns_zero(self):
        self.assertEqual(_protocol_fee_usd(1000.0, -1.0), 0.0)

    def test_100pct_fee(self):
        self.assertAlmostEqual(_protocol_fee_usd(1000.0, 100.0), 1000.0, places=6)

    def test_small_fee(self):
        expected = 2000.0 * 0.003
        self.assertAlmostEqual(_protocol_fee_usd(2000.0, 0.3), expected, places=6)

    def test_returns_float(self):
        self.assertIsInstance(_protocol_fee_usd(1000.0, 2.0), float)


# ---------------------------------------------------------------------------
# Tests: _net_yield_usd
# ---------------------------------------------------------------------------

class TestNetYieldUsd(unittest.TestCase):

    def test_basic(self):
        net = _net_yield_usd(1000.0, 200.0, 100.0, 10.0, 50.0, 50.0)
        self.assertAlmostEqual(net, 590.0, places=6)

    def test_all_zero_losses(self):
        self.assertAlmostEqual(_net_yield_usd(1000.0, 0.0, 0.0, 0.0, 0.0, 0.0), 1000.0)

    def test_negative_result(self):
        # gross < total losses → negative
        net = _net_yield_usd(100.0, 500.0, 0.0, 0.0, 0.0, 0.0)
        self.assertLess(net, 0.0)

    def test_entry_cost_subtracted(self):
        net1 = _net_yield_usd(1000.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        net2 = _net_yield_usd(1000.0, 0.0, 0.0, 0.0, 100.0, 0.0)
        self.assertAlmostEqual(net1 - net2, 100.0)

    def test_exit_cost_subtracted(self):
        net1 = _net_yield_usd(1000.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        net2 = _net_yield_usd(1000.0, 0.0, 0.0, 0.0, 0.0, 75.0)
        self.assertAlmostEqual(net1 - net2, 75.0)

    def test_negative_entry_cost_treated_as_zero(self):
        net_neg = _net_yield_usd(1000.0, 0.0, 0.0, 0.0, -50.0, 0.0)
        net_zero = _net_yield_usd(1000.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(net_neg, net_zero)

    def test_returns_float(self):
        self.assertIsInstance(_net_yield_usd(100.0, 10.0, 5.0, 2.0, 5.0, 5.0), float)


# ---------------------------------------------------------------------------
# Tests: _net_roi_pct
# ---------------------------------------------------------------------------

class TestNetRoiPct(unittest.TestCase):

    def test_basic(self):
        # 500 / 10000 * 100 = 5.0
        self.assertAlmostEqual(_net_roi_pct(500.0, 10000.0), 5.0, places=6)

    def test_zero_investment_returns_zero(self):
        self.assertEqual(_net_roi_pct(500.0, 0.0), 0.0)

    def test_negative_investment_returns_zero(self):
        self.assertEqual(_net_roi_pct(500.0, -1000.0), 0.0)

    def test_negative_yield_negative_roi(self):
        self.assertAlmostEqual(_net_roi_pct(-200.0, 10000.0), -2.0, places=6)

    def test_zero_yield_zero_roi(self):
        self.assertAlmostEqual(_net_roi_pct(0.0, 10000.0), 0.0, places=6)

    def test_returns_float(self):
        self.assertIsInstance(_net_roi_pct(100.0, 1000.0), float)

    def test_scales_with_net_yield(self):
        r1 = _net_roi_pct(100.0, 1000.0)
        r2 = _net_roi_pct(200.0, 1000.0)
        self.assertAlmostEqual(r2 / r1, 2.0, places=6)

    def test_100pct_roi(self):
        self.assertAlmostEqual(_net_roi_pct(5000.0, 5000.0), 100.0, places=6)


# ---------------------------------------------------------------------------
# Tests: _annualized_net_roi_pct
# ---------------------------------------------------------------------------

class TestAnnualizedNetRoiPct(unittest.TestCase):

    def test_basic_90_days(self):
        # 5% over 90 days → 5 * 365/90
        expected = 5.0 * (365.0 / 90)
        self.assertAlmostEqual(_annualized_net_roi_pct(5.0, 90), expected, places=4)

    def test_zero_days_returns_zero(self):
        self.assertEqual(_annualized_net_roi_pct(5.0, 0), 0.0)

    def test_negative_days_returns_zero(self):
        self.assertEqual(_annualized_net_roi_pct(5.0, -10), 0.0)

    def test_365_days_same_as_roi(self):
        self.assertAlmostEqual(_annualized_net_roi_pct(10.0, 365), 10.0, places=6)

    def test_negative_roi_annualizes(self):
        result = _annualized_net_roi_pct(-3.0, 90)
        self.assertLess(result, 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_annualized_net_roi_pct(5.0, 90), float)

    def test_1_day(self):
        result = _annualized_net_roi_pct(0.1, 1)
        self.assertAlmostEqual(result, 36.5, places=4)


# ---------------------------------------------------------------------------
# Tests: _roi_label
# ---------------------------------------------------------------------------

class TestRoiLabel(unittest.TestCase):

    def test_above_5_excellent(self):
        self.assertEqual(_roi_label(5.1), "EXCELLENT_ROI")
        self.assertEqual(_roi_label(10.0), "EXCELLENT_ROI")
        self.assertEqual(_roi_label(100.0), "EXCELLENT_ROI")

    def test_exactly_5_good(self):
        self.assertEqual(_roi_label(5.0), "GOOD_ROI")

    def test_between_1_and_5_good(self):
        self.assertEqual(_roi_label(1.1), "GOOD_ROI")
        self.assertEqual(_roi_label(3.0), "GOOD_ROI")
        self.assertEqual(_roi_label(4.99), "GOOD_ROI")

    def test_exactly_1_good(self):
        self.assertEqual(_roi_label(1.0), "GOOD_ROI")

    def test_just_above_1_good(self):
        self.assertEqual(_roi_label(1.001), "GOOD_ROI")

    def test_just_below_1_breakeven(self):
        # 0.999 < 1.0 → BREAKEVEN (GOOD_ROI starts at exactly 1.0)
        self.assertEqual(_roi_label(0.999), "BREAKEVEN")

    def test_zero_breakeven(self):
        self.assertEqual(_roi_label(0.0), "BREAKEVEN")

    def test_negative_small_breakeven(self):
        self.assertEqual(_roi_label(-0.5), "BREAKEVEN")
        self.assertEqual(_roi_label(-0.99), "BREAKEVEN")

    def test_exactly_minus_1_breakeven(self):
        self.assertEqual(_roi_label(-1.0), "BREAKEVEN")

    def test_just_below_minus_1_marginal_loss(self):
        self.assertEqual(_roi_label(-1.001), "MARGINAL_LOSS")

    def test_between_minus_5_and_minus_1_marginal_loss(self):
        self.assertEqual(_roi_label(-2.0), "MARGINAL_LOSS")
        self.assertEqual(_roi_label(-3.5), "MARGINAL_LOSS")
        self.assertEqual(_roi_label(-4.99), "MARGINAL_LOSS")

    def test_exactly_minus_5_marginal_loss(self):
        self.assertEqual(_roi_label(-5.0), "MARGINAL_LOSS")

    def test_just_below_minus_5_significant_loss(self):
        self.assertEqual(_roi_label(-5.001), "SIGNIFICANT_LOSS")

    def test_large_negative_significant_loss(self):
        self.assertEqual(_roi_label(-50.0), "SIGNIFICANT_LOSS")
        self.assertEqual(_roi_label(-100.0), "SIGNIFICANT_LOSS")

    def test_returns_string(self):
        self.assertIsInstance(_roi_label(3.0), str)

    def test_all_five_labels_reachable(self):
        labels = {_roi_label(v) for v in [10, 3, 0, -3, -10]}
        expected = {
            "EXCELLENT_ROI",
            "GOOD_ROI",
            "BREAKEVEN",
            "MARGINAL_LOSS",
            "SIGNIFICANT_LOSS",
        }
        self.assertEqual(labels, expected)


# ---------------------------------------------------------------------------
# Tests: _atomic_log
# ---------------------------------------------------------------------------

class TestAtomicLogROI(unittest.TestCase):

    def test_creates_file(self):
        path = _tmp_log()
        _atomic_log(path, {"v": 1})
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_appends_entries(self):
        path = _tmp_log()
        _atomic_log(path, {"n": 1})
        _atomic_log(path, {"n": 2})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        os.unlink(path)

    def test_ring_buffer_cap(self):
        path = _tmp_log()
        for i in range(120):
            _atomic_log(path, {"i": i}, log_cap=100)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)
        self.assertEqual(data[-1]["i"], 119)
        os.unlink(path)

    def test_recovers_corrupt_file(self):
        path = _tmp_log()
        with open(path, "w") as f:
            f.write("CORRUPT {{")
        _atomic_log(path, {"k": "v"})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_output_is_valid_json(self):
        path = _tmp_log()
        _atomic_log(path, {"x": 42})
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        os.unlink(path)

    def test_custom_cap(self):
        path = _tmp_log()
        for i in range(20):
            _atomic_log(path, {"i": i}, log_cap=5)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)
        os.unlink(path)


# ---------------------------------------------------------------------------
# Tests: ProtocolDeFiYieldFarmingROICalculator output structure
# ---------------------------------------------------------------------------

class TestCalculatorOutputStructure(unittest.TestCase):

    def setUp(self):
        self.calc = ProtocolDeFiYieldFarmingROICalculator(log_path=_tmp_log())
        self.params = _base_params()

    def tearDown(self):
        if os.path.exists(self.calc._log_path):
            os.unlink(self.calc._log_path)

    def test_returns_dict(self):
        r = self.calc.calculate(self.params, {"skip_log": True})
        self.assertIsInstance(r, dict)

    def test_required_keys_present(self):
        r = self.calc.calculate(self.params, {"skip_log": True})
        required = {
            "protocol_name",
            "initial_investment_usd",
            "gross_apy_pct",
            "il_risk_pct",
            "reward_token_decay_pct",
            "entry_cost_usd",
            "exit_cost_usd",
            "holding_days",
            "protocol_fee_pct",
            "gross_yield_usd",
            "il_loss_usd",
            "reward_decay_loss_usd",
            "protocol_fee_usd",
            "net_yield_usd",
            "net_roi_pct",
            "annualized_net_roi_pct",
            "roi_label",
            "timestamp",
        }
        self.assertTrue(required.issubset(r.keys()))

    def test_gross_yield_usd_is_float(self):
        r = self.calc.calculate(self.params, {"skip_log": True})
        self.assertIsInstance(r["gross_yield_usd"], float)

    def test_il_loss_usd_is_float(self):
        r = self.calc.calculate(self.params, {"skip_log": True})
        self.assertIsInstance(r["il_loss_usd"], float)

    def test_reward_decay_loss_usd_is_float(self):
        r = self.calc.calculate(self.params, {"skip_log": True})
        self.assertIsInstance(r["reward_decay_loss_usd"], float)

    def test_net_yield_usd_is_float(self):
        r = self.calc.calculate(self.params, {"skip_log": True})
        self.assertIsInstance(r["net_yield_usd"], float)

    def test_net_roi_pct_is_float(self):
        r = self.calc.calculate(self.params, {"skip_log": True})
        self.assertIsInstance(r["net_roi_pct"], float)

    def test_annualized_net_roi_pct_is_float(self):
        r = self.calc.calculate(self.params, {"skip_log": True})
        self.assertIsInstance(r["annualized_net_roi_pct"], float)

    def test_roi_label_is_str(self):
        r = self.calc.calculate(self.params, {"skip_log": True})
        self.assertIsInstance(r["roi_label"], str)

    def test_timestamp_positive(self):
        r = self.calc.calculate(self.params, {"skip_log": True})
        self.assertGreater(r["timestamp"], 0)

    def test_protocol_name_preserved(self):
        r = self.calc.calculate(
            _base_params(protocol_name="MorphoSteakhouse"), {"skip_log": True}
        )
        self.assertEqual(r["protocol_name"], "MorphoSteakhouse")

    def test_holding_days_echoed(self):
        r = self.calc.calculate(
            _base_params(holding_days=180), {"skip_log": True}
        )
        self.assertEqual(r["holding_days"], 180)


# ---------------------------------------------------------------------------
# Tests: label boundaries via calculator
# ---------------------------------------------------------------------------

class TestCalculatorLabels(unittest.TestCase):

    def setUp(self):
        self.calc = ProtocolDeFiYieldFarmingROICalculator(log_path=_tmp_log())

    def tearDown(self):
        if os.path.exists(self.calc._log_path):
            os.unlink(self.calc._log_path)

    def test_excellent_roi_label_high_apy(self):
        r = self.calc.calculate(
            {
                "protocol_name": "HighYield",
                "initial_investment_usd": 1_000_000.0,
                "gross_apy_pct": 20.0,
                "il_risk_pct": 0.0,
                "reward_token_decay_pct": 0.0,
                "entry_cost_usd": 0.0,
                "exit_cost_usd": 0.0,
                "holding_days": 365,
                "protocol_fee_pct": 0.0,
            },
            {"skip_log": True},
        )
        self.assertEqual(r["roi_label"], "EXCELLENT_ROI")

    def test_good_roi_label(self):
        # net_roi ~3%: apy=3%, no costs, 365 days
        r = self.calc.calculate(
            {
                "protocol_name": "GoodYield",
                "initial_investment_usd": 1_000_000.0,
                "gross_apy_pct": 3.0,
                "il_risk_pct": 0.0,
                "reward_token_decay_pct": 0.0,
                "entry_cost_usd": 0.0,
                "exit_cost_usd": 0.0,
                "holding_days": 365,
                "protocol_fee_pct": 0.0,
            },
            {"skip_log": True},
        )
        self.assertEqual(r["roi_label"], "GOOD_ROI")

    def test_breakeven_label(self):
        # zero everything → roi = 0 → BREAKEVEN
        r = self.calc.calculate(
            _base_params(
                gross_apy_pct=0.0,
                il_risk_pct=0.0,
                reward_token_decay_pct=0.0,
                entry_cost_usd=0.0,
                exit_cost_usd=0.0,
                protocol_fee_pct=0.0,
            ),
            {"skip_log": True},
        )
        self.assertEqual(r["roi_label"], "BREAKEVEN")

    def test_significant_loss_label(self):
        # Very high IL: 20% of 10000 = 2000 loss, tiny gross
        r = self.calc.calculate(
            {
                "protocol_name": "LossPool",
                "initial_investment_usd": 10_000.0,
                "gross_apy_pct": 1.0,
                "il_risk_pct": 20.0,
                "reward_token_decay_pct": 0.0,
                "entry_cost_usd": 0.0,
                "exit_cost_usd": 0.0,
                "holding_days": 365,
                "protocol_fee_pct": 0.0,
            },
            {"skip_log": True},
        )
        self.assertEqual(r["roi_label"], "SIGNIFICANT_LOSS")

    def test_marginal_loss_label(self):
        # net_roi ≈ -3%: invest 10000, IL loss = 300, no yield
        r = self.calc.calculate(
            {
                "protocol_name": "SlightLoss",
                "initial_investment_usd": 10_000.0,
                "gross_apy_pct": 0.0,
                "il_risk_pct": 3.0,
                "reward_token_decay_pct": 0.0,
                "entry_cost_usd": 0.0,
                "exit_cost_usd": 0.0,
                "holding_days": 365,
                "protocol_fee_pct": 0.0,
            },
            {"skip_log": True},
        )
        self.assertEqual(r["roi_label"], "MARGINAL_LOSS")


# ---------------------------------------------------------------------------
# Tests: Known-value calculations
# ---------------------------------------------------------------------------

class TestKnownValueCalculations(unittest.TestCase):

    def setUp(self):
        self.calc = ProtocolDeFiYieldFarmingROICalculator(log_path=_tmp_log())

    def tearDown(self):
        if os.path.exists(self.calc._log_path):
            os.unlink(self.calc._log_path)

    def test_gross_yield_known_value(self):
        # 10000 * 20% * 90/365
        expected_gross = 10000.0 * 0.20 * (90 / 365.0)
        r = self.calc.calculate(
            _base_params(
                initial_investment_usd=10000.0,
                gross_apy_pct=20.0,
                holding_days=90,
                il_risk_pct=0.0,
                reward_token_decay_pct=0.0,
                entry_cost_usd=0.0,
                exit_cost_usd=0.0,
                protocol_fee_pct=0.0,
            ),
            {"skip_log": True},
        )
        self.assertAlmostEqual(r["gross_yield_usd"], expected_gross, places=4)

    def test_il_loss_known_value(self):
        # 50000 * 8% = 4000
        r = self.calc.calculate(
            _base_params(
                initial_investment_usd=50000.0,
                il_risk_pct=8.0,
                gross_apy_pct=0.0,
                reward_token_decay_pct=0.0,
                entry_cost_usd=0.0,
                exit_cost_usd=0.0,
                protocol_fee_pct=0.0,
                holding_days=365,
            ),
            {"skip_log": True},
        )
        self.assertAlmostEqual(r["il_loss_usd"], 4000.0, places=4)

    def test_net_roi_is_net_yield_over_investment(self):
        r = self.calc.calculate(_base_params(), {"skip_log": True})
        if r["initial_investment_usd"] > 0:
            expected_roi = r["net_yield_usd"] / r["initial_investment_usd"] * 100
            self.assertAlmostEqual(r["net_roi_pct"], expected_roi, places=4)

    def test_annualized_is_roi_times_365_over_days(self):
        r = self.calc.calculate(_base_params(holding_days=90), {"skip_log": True})
        expected = r["net_roi_pct"] * (365.0 / 90)
        self.assertAlmostEqual(r["annualized_net_roi_pct"], expected, places=4)

    def test_no_costs_scenario(self):
        # 10000 @ 10% for 365 days, no costs → gross = 1000, net = 1000, roi = 10%
        r = self.calc.calculate(
            {
                "protocol_name": "NoCost",
                "initial_investment_usd": 10000.0,
                "gross_apy_pct": 10.0,
                "il_risk_pct": 0.0,
                "reward_token_decay_pct": 0.0,
                "entry_cost_usd": 0.0,
                "exit_cost_usd": 0.0,
                "holding_days": 365,
                "protocol_fee_pct": 0.0,
            },
            {"skip_log": True},
        )
        self.assertAlmostEqual(r["gross_yield_usd"], 1000.0, places=4)
        self.assertAlmostEqual(r["il_loss_usd"], 0.0, places=4)
        self.assertAlmostEqual(r["reward_decay_loss_usd"], 0.0, places=4)
        self.assertAlmostEqual(r["net_yield_usd"], 1000.0, places=4)
        self.assertAlmostEqual(r["net_roi_pct"], 10.0, places=4)
        self.assertAlmostEqual(r["annualized_net_roi_pct"], 10.0, places=4)
        self.assertEqual(r["roi_label"], "EXCELLENT_ROI")

    def test_full_scenario_net_yield_formula(self):
        """Verify: net = gross - il - decay - fee - entry - exit."""
        p = _base_params(
            initial_investment_usd=20000.0,
            gross_apy_pct=15.0,
            il_risk_pct=6.0,
            reward_token_decay_pct=20.0,
            entry_cost_usd=80.0,
            exit_cost_usd=60.0,
            holding_days=180,
            protocol_fee_pct=1.0,
        )
        r = self.calc.calculate(p, {"skip_log": True})
        gross = r["gross_yield_usd"]
        il = r["il_loss_usd"]
        decay = r["reward_decay_loss_usd"]
        fee = r["protocol_fee_usd"]
        expected_net = gross - il - decay - fee - 80.0 - 60.0
        self.assertAlmostEqual(r["net_yield_usd"], expected_net, places=4)


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------

class TestCalculatorEdgeCases(unittest.TestCase):

    def setUp(self):
        self.calc = ProtocolDeFiYieldFarmingROICalculator(log_path=_tmp_log())

    def tearDown(self):
        if os.path.exists(self.calc._log_path):
            os.unlink(self.calc._log_path)

    def test_zero_investment_all_zeros(self):
        r = self.calc.calculate(
            _base_params(initial_investment_usd=0.0), {"skip_log": True}
        )
        self.assertEqual(r["gross_yield_usd"], 0.0)
        self.assertEqual(r["il_loss_usd"], 0.0)
        self.assertEqual(r["net_roi_pct"], 0.0)

    def test_zero_holding_days(self):
        r = self.calc.calculate(
            _base_params(holding_days=0), {"skip_log": True}
        )
        self.assertEqual(r["gross_yield_usd"], 0.0)
        self.assertEqual(r["annualized_net_roi_pct"], 0.0)

    def test_negative_costs_treated_as_zero(self):
        r_pos = self.calc.calculate(
            _base_params(entry_cost_usd=100.0, exit_cost_usd=100.0), {"skip_log": True}
        )
        r_neg = self.calc.calculate(
            _base_params(entry_cost_usd=-100.0, exit_cost_usd=-100.0), {"skip_log": True}
        )
        # Negative costs treated as 0 → net yield of r_neg should be HIGHER
        self.assertGreater(r_neg["net_yield_usd"], r_pos["net_yield_usd"])

    def test_missing_protocol_name_defaults_unknown(self):
        p = _base_params()
        del p["protocol_name"]
        r = self.calc.calculate(p, {"skip_log": True})
        self.assertEqual(r["protocol_name"], "UNKNOWN")

    def test_string_holding_days_coerced(self):
        p = _base_params()
        p["holding_days"] = "90"
        r = self.calc.calculate(p, {"skip_log": True})
        self.assertEqual(r["holding_days"], 90)

    def test_float_holding_days_truncated(self):
        p = _base_params()
        p["holding_days"] = 90.9
        r = self.calc.calculate(p, {"skip_log": True})
        self.assertEqual(r["holding_days"], 90)

    def test_large_investment(self):
        r = self.calc.calculate(
            _base_params(initial_investment_usd=1_000_000.0), {"skip_log": True}
        )
        self.assertGreater(r["gross_yield_usd"], 0.0)

    def test_high_il_risk_yields_significant_loss(self):
        r = self.calc.calculate(
            _base_params(il_risk_pct=50.0, gross_apy_pct=5.0, holding_days=90),
            {"skip_log": True},
        )
        self.assertEqual(r["roi_label"], "SIGNIFICANT_LOSS")

    def test_reward_decay_100pct_equals_gross(self):
        r = self.calc.calculate(
            _base_params(
                reward_token_decay_pct=100.0,
                il_risk_pct=0.0,
                entry_cost_usd=0.0,
                exit_cost_usd=0.0,
                protocol_fee_pct=0.0,
            ),
            {"skip_log": True},
        )
        # decay = gross
        self.assertAlmostEqual(
            r["reward_decay_loss_usd"], r["gross_yield_usd"], places=4
        )

    def test_all_zero_params(self):
        r = self.calc.calculate(
            {
                "protocol_name": "Zero",
                "initial_investment_usd": 0.0,
                "gross_apy_pct": 0.0,
                "il_risk_pct": 0.0,
                "reward_token_decay_pct": 0.0,
                "entry_cost_usd": 0.0,
                "exit_cost_usd": 0.0,
                "holding_days": 0,
                "protocol_fee_pct": 0.0,
            },
            {"skip_log": True},
        )
        self.assertEqual(r["gross_yield_usd"], 0.0)
        self.assertEqual(r["net_yield_usd"], 0.0)
        self.assertEqual(r["net_roi_pct"], 0.0)
        self.assertEqual(r["roi_label"], "BREAKEVEN")


# ---------------------------------------------------------------------------
# Tests: Logging
# ---------------------------------------------------------------------------

class TestCalculatorLogging(unittest.TestCase):

    def test_log_written_by_default(self):
        log = _tmp_log()
        calc = ProtocolDeFiYieldFarmingROICalculator(log_path=log)
        calc.calculate(_base_params())
        self.assertTrue(os.path.exists(log))
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(log)

    def test_skip_log_prevents_write(self):
        log = _tmp_log()
        calc = ProtocolDeFiYieldFarmingROICalculator(log_path=log)
        calc.calculate(_base_params(), {"skip_log": True})
        self.assertFalse(os.path.exists(log))

    def test_ring_buffer_trimmed(self):
        log = _tmp_log()
        calc = ProtocolDeFiYieldFarmingROICalculator(log_path=log, log_cap=10)
        for _ in range(15):
            calc.calculate(_base_params())
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 10)
        os.unlink(log)

    def test_log_entry_has_roi_label(self):
        log = _tmp_log()
        calc = ProtocolDeFiYieldFarmingROICalculator(log_path=log)
        calc.calculate(
            _base_params(
                gross_apy_pct=50.0,
                il_risk_pct=0.0,
                reward_token_decay_pct=0.0,
                entry_cost_usd=0.0,
                exit_cost_usd=0.0,
                protocol_fee_pct=0.0,
            )
        )
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(data[0]["roi_label"], "EXCELLENT_ROI")
        os.unlink(log)

    def test_log_override_via_config(self):
        log1 = _tmp_log()
        log2 = _tmp_log()
        calc = ProtocolDeFiYieldFarmingROICalculator(log_path=log1)
        calc.calculate(_base_params(), {"log_path": log2})
        self.assertFalse(os.path.exists(log1))
        self.assertTrue(os.path.exists(log2))
        os.unlink(log2)


# ---------------------------------------------------------------------------
# Tests: Module-level calculate()
# ---------------------------------------------------------------------------

class TestModuleLevelCalculate(unittest.TestCase):

    def test_returns_dict(self):
        r = calculate(_base_params(), {"skip_log": True})
        self.assertIsInstance(r, dict)

    def test_has_roi_label(self):
        r = calculate(_base_params(), {"skip_log": True})
        self.assertIn("roi_label", r)

    def test_excellent_roi_label(self):
        r = calculate(
            _base_params(
                gross_apy_pct=100.0,
                il_risk_pct=0.0,
                reward_token_decay_pct=0.0,
                entry_cost_usd=0.0,
                exit_cost_usd=0.0,
                protocol_fee_pct=0.0,
                holding_days=365,
            ),
            {"skip_log": True},
        )
        self.assertEqual(r["roi_label"], "EXCELLENT_ROI")

    def test_has_gross_yield(self):
        r = calculate(_base_params(), {"skip_log": True})
        self.assertIn("gross_yield_usd", r)
        self.assertGreater(r["gross_yield_usd"], 0.0)


# ---------------------------------------------------------------------------
# Tests: Realistic DeFi Scenarios
# ---------------------------------------------------------------------------

class TestRealisticScenarios(unittest.TestCase):

    def setUp(self):
        self.calc = ProtocolDeFiYieldFarmingROICalculator(log_path=_tmp_log())

    def tearDown(self):
        if os.path.exists(self.calc._log_path):
            os.unlink(self.calc._log_path)

    def test_aave_stablecoin_farm(self):
        """Low-risk stablecoin farm: 4% APY, no IL, minimal costs."""
        r = self.calc.calculate(
            {
                "protocol_name": "Aave USDC",
                "initial_investment_usd": 100_000.0,
                "gross_apy_pct": 4.0,
                "il_risk_pct": 0.0,
                "reward_token_decay_pct": 0.0,
                "entry_cost_usd": 20.0,
                "exit_cost_usd": 20.0,
                "holding_days": 365,
                "protocol_fee_pct": 0.1,
            },
            {"skip_log": True},
        )
        self.assertGreater(r["net_roi_pct"], 3.0)
        self.assertIn(r["roi_label"], ["GOOD_ROI", "EXCELLENT_ROI"])

    def test_short_hold_costs_dominate(self):
        """3-day hold: gas costs dominate tiny yield."""
        r = self.calc.calculate(
            {
                "protocol_name": "ShortHold",
                "initial_investment_usd": 5_000.0,
                "gross_apy_pct": 10.0,
                "il_risk_pct": 0.0,
                "reward_token_decay_pct": 0.0,
                "entry_cost_usd": 200.0,
                "exit_cost_usd": 200.0,
                "holding_days": 3,
                "protocol_fee_pct": 0.0,
            },
            {"skip_log": True},
        )
        # gross ≈ 5000 * 0.10 * 3/365 ≈ 4.11; costs = 400 → net < 0
        self.assertLess(r["net_yield_usd"], 0.0)
        self.assertIn(r["roi_label"], ["SIGNIFICANT_LOSS", "MARGINAL_LOSS"])

    def test_pendle_high_apy(self):
        """High APY position with token decay risk."""
        r = self.calc.calculate(
            {
                "protocol_name": "Pendle PT",
                "initial_investment_usd": 25_000.0,
                "gross_apy_pct": 18.0,
                "il_risk_pct": 0.0,
                "reward_token_decay_pct": 20.0,
                "entry_cost_usd": 50.0,
                "exit_cost_usd": 50.0,
                "holding_days": 180,
                "protocol_fee_pct": 0.2,
            },
            {"skip_log": True},
        )
        self.assertIn(r["roi_label"], ["EXCELLENT_ROI", "GOOD_ROI"])

    def test_net_yield_components_sum_correctly(self):
        """Verify net = gross - il - decay - fee - entry - exit."""
        r = self.calc.calculate(
            _base_params(
                initial_investment_usd=10000.0,
                gross_apy_pct=20.0,
                il_risk_pct=5.0,
                reward_token_decay_pct=10.0,
                entry_cost_usd=50.0,
                exit_cost_usd=50.0,
                holding_days=90,
                protocol_fee_pct=0.5,
            ),
            {"skip_log": True},
        )
        expected = (
            r["gross_yield_usd"]
            - r["il_loss_usd"]
            - r["reward_decay_loss_usd"]
            - r["protocol_fee_usd"]
            - 50.0
            - 50.0
        )
        self.assertAlmostEqual(r["net_yield_usd"], expected, places=4)

    def test_gross_yield_positive_with_all_params(self):
        r = self.calc.calculate(_base_params(), {"skip_log": True})
        self.assertGreater(r["gross_yield_usd"], 0.0)

    def test_annualized_roi_higher_than_period_roi_for_short_hold(self):
        # If hold < 365 days, annualized > period ROI (for positive ROI)
        r = self.calc.calculate(
            _base_params(
                gross_apy_pct=20.0,
                il_risk_pct=0.0,
                reward_token_decay_pct=0.0,
                entry_cost_usd=0.0,
                exit_cost_usd=0.0,
                protocol_fee_pct=0.0,
                holding_days=90,
            ),
            {"skip_log": True},
        )
        if r["net_roi_pct"] > 0:
            self.assertGreater(r["annualized_net_roi_pct"], r["net_roi_pct"])


if __name__ == "__main__":
    unittest.main()
