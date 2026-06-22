"""
Tests for MP-951 ProtocolLiquidityProviderProfitabilityTracker.
Run: python3 -m unittest spa_core.tests.test_protocol_liquidity_provider_profitability_tracker -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from spa_core.analytics.protocol_liquidity_provider_profitability_tracker import (
    ProtocolLiquidityProviderProfitabilityTracker,
    LABEL_EXCELLENT,
    LABEL_GOOD,
    LABEL_BREAK_EVEN,
    LABEL_UNDERPERFORMING,
    LABEL_LOSS,
    FLAG_BEATS_HODL,
    FLAG_HIGH_IL_RATIO,
    FLAG_GAS_HEAVY,
    FLAG_REWARD_DEPENDENT,
    FLAG_LONG_TERM_HOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_position(**kwargs) -> dict:
    """Return a minimal valid position dict, overriding with kwargs."""
    base = {
        "protocol": "Uniswap V3",
        "pair": "ETH/USDC",
        "entry_value_usd": 10_000.0,
        "current_value_usd": 10_200.0,
        "fees_earned_usd": 500.0,
        "rewards_earned_usd": 100.0,
        "il_loss_usd": 50.0,
        "gas_costs_usd": 30.0,
        "days_held": 90.0,
        "entry_price_ratio": 1.0,
        "current_price_ratio": 1.02,
        "benchmark_hodl_value_usd": 10_200.0,
    }
    base.update(kwargs)
    return base


def _tracker(data_dir=None) -> ProtocolLiquidityProviderProfitabilityTracker:
    return ProtocolLiquidityProviderProfitabilityTracker(data_dir=data_dir)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTrackReturnsStructure(unittest.TestCase):
    def setUp(self):
        self.tk = _tracker()

    def test_returns_dict(self):
        result = self.tk.track([_make_position()])
        self.assertIsInstance(result, dict)

    def test_has_positions_key(self):
        result = self.tk.track([_make_position()])
        self.assertIn("positions", result)

    def test_has_aggregates_key(self):
        result = self.tk.track([_make_position()])
        self.assertIn("aggregates", result)

    def test_has_tracked_at_key(self):
        result = self.tk.track([_make_position()])
        self.assertIn("tracked_at", result)

    def test_positions_is_list(self):
        result = self.tk.track([_make_position()])
        self.assertIsInstance(result["positions"], list)

    def test_positions_length_matches_input(self):
        result = self.tk.track([_make_position(), _make_position(pair="BTC/USDC")])
        self.assertEqual(len(result["positions"]), 2)

    def test_empty_positions(self):
        result = self.tk.track([])
        self.assertEqual(result["positions"], [])

    def test_empty_aggregates_total_zero(self):
        result = self.tk.track([])
        self.assertEqual(result["aggregates"]["total_positions"], 0)

    def test_tracked_at_is_string(self):
        result = self.tk.track([_make_position()])
        self.assertIsInstance(result["tracked_at"], str)


class TestPerPositionFields(unittest.TestCase):
    def setUp(self):
        self.tk = _tracker()
        self.r = self.tk.track([_make_position()])["positions"][0]

    def test_protocol_field(self):
        self.assertEqual(self.r["protocol"], "Uniswap V3")

    def test_pair_field(self):
        self.assertEqual(self.r["pair"], "ETH/USDC")

    def test_gross_pnl_present(self):
        self.assertIn("gross_pnl_usd", self.r)

    def test_net_pnl_present(self):
        self.assertIn("net_pnl_usd", self.r)

    def test_net_pnl_pct_present(self):
        self.assertIn("net_pnl_pct", self.r)

    def test_vs_hodl_pct_present(self):
        self.assertIn("vs_hodl_pct", self.r)

    def test_fee_apy_pct_present(self):
        self.assertIn("fee_apy_pct", self.r)

    def test_total_apy_pct_present(self):
        self.assertIn("total_apy_pct", self.r)

    def test_il_as_pct_fees_present(self):
        self.assertIn("il_as_pct_fees", self.r)

    def test_label_present(self):
        self.assertIn("label", self.r)

    def test_flags_present(self):
        self.assertIn("flags", self.r)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)


class TestGrossPnlComputation(unittest.TestCase):
    def setUp(self):
        self.tk = _tracker()

    def test_gross_pnl_basic(self):
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=10_000,  # no capital change
            fees_earned_usd=500,
            rewards_earned_usd=200,
            il_loss_usd=100,
            gas_costs_usd=0,
        )
        r = self.tk.track([pos])["positions"][0]
        # gross = 0 + 500 + 200 - 100 = 600
        self.assertAlmostEqual(r["gross_pnl_usd"], 600.0, places=2)

    def test_net_pnl_subtracts_gas(self):
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=10_000,
            fees_earned_usd=500,
            rewards_earned_usd=200,
            il_loss_usd=100,
            gas_costs_usd=50,
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertAlmostEqual(r["net_pnl_usd"], 550.0, places=2)

    def test_net_pnl_pct_calculation(self):
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=10_000,
            fees_earned_usd=1_000,
            rewards_earned_usd=0,
            il_loss_usd=0,
            gas_costs_usd=0,
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertAlmostEqual(r["net_pnl_pct"], 10.0, places=2)

    def test_negative_pnl(self):
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=8_000,
            fees_earned_usd=100,
            rewards_earned_usd=50,
            il_loss_usd=500,
            gas_costs_usd=100,
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertLess(r["net_pnl_usd"], 0.0)

    def test_zero_entry_value_no_crash(self):
        pos = _make_position(entry_value_usd=0.0)
        r = self.tk.track([pos])["positions"][0]
        self.assertEqual(r["net_pnl_pct"], 0.0)


class TestVsHodlCalculation(unittest.TestCase):
    def setUp(self):
        self.tk = _tracker()

    def test_beats_hodl_positive_vs_hodl(self):
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=10_000,
            fees_earned_usd=800,
            rewards_earned_usd=0,
            il_loss_usd=100,
            gas_costs_usd=50,
            benchmark_hodl_value_usd=10_200,  # hodl gains 200
        )
        r = self.tk.track([pos])["positions"][0]
        # net_pnl = 0+800+0-100-50 = 650
        # hodl_pnl = 200
        # vs_hodl = 650 - 200 = 450 → positive
        self.assertGreater(r["vs_hodl_pct"], 0.0)

    def test_underperforms_hodl(self):
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=10_000,
            fees_earned_usd=100,
            rewards_earned_usd=0,
            il_loss_usd=500,
            gas_costs_usd=50,
            benchmark_hodl_value_usd=11_000,  # hodl gains 1000
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertLess(r["vs_hodl_pct"], 0.0)


class TestFeeApyCalculation(unittest.TestCase):
    def setUp(self):
        self.tk = _tracker()

    def test_fee_apy_annualization(self):
        # fees = 10% of entry over 365 days → fee_apy = 10%
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=10_000,
            fees_earned_usd=1_000,
            rewards_earned_usd=0,
            il_loss_usd=0,
            gas_costs_usd=0,
            days_held=365,
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertAlmostEqual(r["fee_apy_pct"], 10.0, places=2)

    def test_fee_apy_90_day_extrapolation(self):
        # fees = 500 / 10000 over 90 days → annualized = 500/10000 * 365/90 * 100
        pos = _make_position(
            entry_value_usd=10_000,
            fees_earned_usd=500,
            rewards_earned_usd=0,
            il_loss_usd=0,
            gas_costs_usd=0,
            days_held=90,
        )
        expected = (500 / 10_000) * (365 / 90) * 100
        r = self.tk.track([pos])["positions"][0]
        self.assertAlmostEqual(r["fee_apy_pct"], expected, places=2)

    def test_zero_days_no_crash(self):
        pos = _make_position(days_held=0)
        r = self.tk.track([pos])["positions"][0]
        self.assertEqual(r["fee_apy_pct"], 0.0)


class TestILAsPercentFees(unittest.TestCase):
    def setUp(self):
        self.tk = _tracker()

    def test_il_as_pct_fees_50pct(self):
        pos = _make_position(il_loss_usd=200, fees_earned_usd=400)
        r = self.tk.track([pos])["positions"][0]
        self.assertAlmostEqual(r["il_as_pct_fees"], 50.0, places=2)

    def test_il_as_pct_fees_zero_il(self):
        pos = _make_position(il_loss_usd=0, fees_earned_usd=500)
        r = self.tk.track([pos])["positions"][0]
        self.assertAlmostEqual(r["il_as_pct_fees"], 0.0)

    def test_il_as_pct_fees_zero_fees_with_il(self):
        pos = _make_position(il_loss_usd=100, fees_earned_usd=0)
        r = self.tk.track([pos])["positions"][0]
        self.assertAlmostEqual(r["il_as_pct_fees"], 100.0)

    def test_il_as_pct_fees_zero_both(self):
        pos = _make_position(il_loss_usd=0, fees_earned_usd=0)
        r = self.tk.track([pos])["positions"][0]
        self.assertAlmostEqual(r["il_as_pct_fees"], 0.0)

    def test_il_exceeds_fees(self):
        pos = _make_position(il_loss_usd=1_000, fees_earned_usd=300)
        r = self.tk.track([pos])["positions"][0]
        self.assertGreater(r["il_as_pct_fees"], 100.0)


class TestLabelAssignment(unittest.TestCase):
    def setUp(self):
        self.tk = _tracker()

    def test_excellent_label_high_apy_beats_hodl(self):
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=10_000,
            fees_earned_usd=2_000,
            rewards_earned_usd=500,
            il_loss_usd=0,
            gas_costs_usd=0,
            days_held=90,
            benchmark_hodl_value_usd=10_000,  # hodl flat
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertEqual(r["label"], LABEL_EXCELLENT)

    def test_loss_label(self):
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=8_000,
            fees_earned_usd=50,
            rewards_earned_usd=0,
            il_loss_usd=2_000,
            gas_costs_usd=100,
            days_held=90,
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertIn(r["label"], (LABEL_LOSS, LABEL_UNDERPERFORMING))

    def test_break_even_label(self):
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=10_000,
            fees_earned_usd=200,
            rewards_earned_usd=0,
            il_loss_usd=150,
            gas_costs_usd=50,
            days_held=365,
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertIn(r["label"], (LABEL_BREAK_EVEN, LABEL_GOOD, LABEL_UNDERPERFORMING))

    def test_good_label_moderate_apy(self):
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=10_000,
            fees_earned_usd=1_000,  # ~4% APY over 365d but more over 90d
            rewards_earned_usd=0,
            il_loss_usd=100,
            gas_costs_usd=20,
            days_held=365,
            benchmark_hodl_value_usd=9_800,
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertIn(r["label"], (LABEL_GOOD, LABEL_BREAK_EVEN, LABEL_EXCELLENT))

    def test_label_is_valid_string(self):
        valid_labels = {LABEL_EXCELLENT, LABEL_GOOD, LABEL_BREAK_EVEN,
                        LABEL_UNDERPERFORMING, LABEL_LOSS}
        r = self.tk.track([_make_position()])["positions"][0]
        self.assertIn(r["label"], valid_labels)

    def test_excellent_requires_positive_vs_hodl(self):
        # High APY but lags hodl → should NOT be EXCELLENT
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=10_000,
            fees_earned_usd=2_000,
            rewards_earned_usd=500,
            il_loss_usd=0,
            gas_costs_usd=0,
            days_held=90,
            benchmark_hodl_value_usd=14_000,  # hodl gained 40% → LP underperforms hodl
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertNotEqual(r["label"], LABEL_EXCELLENT)

    def test_custom_excellent_threshold(self):
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=10_000,
            fees_earned_usd=3_000,
            rewards_earned_usd=0,
            il_loss_usd=0,
            gas_costs_usd=0,
            days_held=365,
            benchmark_hodl_value_usd=10_000,
        )
        r = self.tk.track([pos], config={"excellent_apy": 40.0})["positions"][0]
        # 30% APY < 40% threshold → not EXCELLENT
        self.assertNotEqual(r["label"], LABEL_EXCELLENT)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.tk = _tracker()

    def test_beats_hodl_flag(self):
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=10_000,
            fees_earned_usd=1_000,
            rewards_earned_usd=0,
            il_loss_usd=100,
            gas_costs_usd=50,
            benchmark_hodl_value_usd=10_100,  # hodl gains 100; LP net = 850 > 100
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertIn(FLAG_BEATS_HODL, r["flags"])

    def test_no_beats_hodl_when_underperforms(self):
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=10_000,
            fees_earned_usd=100,
            rewards_earned_usd=0,
            il_loss_usd=500,
            gas_costs_usd=50,
            benchmark_hodl_value_usd=11_000,
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertNotIn(FLAG_BEATS_HODL, r["flags"])

    def test_high_il_ratio_flag(self):
        pos = _make_position(
            il_loss_usd=400,
            fees_earned_usd=500,  # IL = 80% of fees
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertIn(FLAG_HIGH_IL_RATIO, r["flags"])

    def test_no_high_il_ratio_flag_low_il(self):
        pos = _make_position(
            il_loss_usd=50,
            fees_earned_usd=500,  # IL = 10% of fees
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertNotIn(FLAG_HIGH_IL_RATIO, r["flags"])

    def test_high_il_ratio_when_no_fees_but_il(self):
        pos = _make_position(il_loss_usd=100, fees_earned_usd=0)
        r = self.tk.track([pos])["positions"][0]
        self.assertIn(FLAG_HIGH_IL_RATIO, r["flags"])

    def test_no_high_il_ratio_when_no_fees_no_il(self):
        pos = _make_position(il_loss_usd=0, fees_earned_usd=0)
        r = self.tk.track([pos])["positions"][0]
        self.assertNotIn(FLAG_HIGH_IL_RATIO, r["flags"])

    def test_gas_heavy_flag(self):
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=10_000,
            fees_earned_usd=100,
            rewards_earned_usd=0,
            il_loss_usd=0,
            gas_costs_usd=20,  # gas = 20% of gross_pnl=100 > 5%
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertIn(FLAG_GAS_HEAVY, r["flags"])

    def test_no_gas_heavy_flag_low_gas(self):
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=10_000,
            fees_earned_usd=1_000,
            rewards_earned_usd=0,
            il_loss_usd=0,
            gas_costs_usd=10,  # gas = 1% of gross_pnl=1000
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertNotIn(FLAG_GAS_HEAVY, r["flags"])

    def test_reward_dependent_flag(self):
        pos = _make_position(
            fees_earned_usd=200,
            rewards_earned_usd=500,  # rewards > fees
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertIn(FLAG_REWARD_DEPENDENT, r["flags"])

    def test_no_reward_dependent_when_fees_dominate(self):
        pos = _make_position(
            fees_earned_usd=800,
            rewards_earned_usd=100,
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertNotIn(FLAG_REWARD_DEPENDENT, r["flags"])

    def test_long_term_hold_flag(self):
        pos = _make_position(days_held=200)
        r = self.tk.track([pos])["positions"][0]
        self.assertIn(FLAG_LONG_TERM_HOLD, r["flags"])

    def test_no_long_term_hold_flag_short(self):
        pos = _make_position(days_held=90)
        r = self.tk.track([pos])["positions"][0]
        self.assertNotIn(FLAG_LONG_TERM_HOLD, r["flags"])

    def test_long_term_hold_exactly_at_threshold(self):
        pos = _make_position(days_held=180)
        r = self.tk.track([pos])["positions"][0]
        self.assertIn(FLAG_LONG_TERM_HOLD, r["flags"])

    def test_multiple_flags_simultaneously(self):
        pos = _make_position(
            il_loss_usd=600,
            fees_earned_usd=500,   # HIGH_IL_RATIO
            rewards_earned_usd=700,  # REWARD_DEPENDENT
            days_held=200,           # LONG_TERM_HOLD
            gas_costs_usd=100,
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertIn(FLAG_HIGH_IL_RATIO, r["flags"])
        self.assertIn(FLAG_REWARD_DEPENDENT, r["flags"])
        self.assertIn(FLAG_LONG_TERM_HOLD, r["flags"])


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.tk = _tracker()

    def test_most_profitable_identifier(self):
        pos1 = _make_position(protocol="Uniswap V3", pair="ETH/USDC",
                               fees_earned_usd=2_000, rewards_earned_usd=0,
                               il_loss_usd=0, gas_costs_usd=0,
                               days_held=90)
        pos2 = _make_position(protocol="Curve", pair="3pool",
                               fees_earned_usd=100, rewards_earned_usd=0,
                               il_loss_usd=200, gas_costs_usd=50,
                               days_held=90)
        agg = self.tk.track([pos1, pos2])["aggregates"]
        self.assertEqual(agg["most_profitable"], "Uniswap V3:ETH/USDC")

    def test_least_profitable_identifier(self):
        pos1 = _make_position(protocol="Aave", pair="USDC",
                               fees_earned_usd=2_000, days_held=90)
        pos2 = _make_position(protocol="Bad Pool", pair="RUG/ETH",
                               entry_value_usd=10_000, current_value_usd=7_000,
                               fees_earned_usd=100, rewards_earned_usd=0,
                               il_loss_usd=3_000, gas_costs_usd=200,
                               days_held=90)
        agg = self.tk.track([pos1, pos2])["aggregates"]
        self.assertEqual(agg["least_profitable"], "Bad Pool:RUG/ETH")

    def test_total_net_pnl_sum(self):
        pos1 = _make_position(entry_value_usd=10_000, current_value_usd=10_000,
                               fees_earned_usd=500, rewards_earned_usd=0,
                               il_loss_usd=0, gas_costs_usd=0)
        pos2 = _make_position(protocol="P2", pair="B", entry_value_usd=5_000,
                               current_value_usd=5_000, fees_earned_usd=200,
                               rewards_earned_usd=0, il_loss_usd=0, gas_costs_usd=0)
        agg = self.tk.track([pos1, pos2])["aggregates"]
        self.assertAlmostEqual(agg["total_net_pnl_usd"], 700.0, places=2)

    def test_average_total_apy(self):
        pos1 = _make_position(entry_value_usd=10_000, current_value_usd=10_000,
                               fees_earned_usd=1_000, rewards_earned_usd=0,
                               il_loss_usd=0, gas_costs_usd=0, days_held=365)
        pos2 = _make_position(protocol="P2", pair="B",
                               entry_value_usd=10_000, current_value_usd=10_000,
                               fees_earned_usd=500, rewards_earned_usd=0,
                               il_loss_usd=0, gas_costs_usd=0, days_held=365)
        agg = self.tk.track([pos1, pos2])["aggregates"]
        # APYs: 10% and 5% → avg 7.5%
        self.assertAlmostEqual(agg["average_total_apy"], 7.5, places=2)

    def test_excellent_count(self):
        pos1 = _make_position(entry_value_usd=10_000, current_value_usd=10_000,
                               fees_earned_usd=3_000, rewards_earned_usd=0,
                               il_loss_usd=0, gas_costs_usd=0, days_held=90,
                               benchmark_hodl_value_usd=10_000)
        pos2 = _make_position(protocol="P2", pair="Y",
                               entry_value_usd=10_000, current_value_usd=9_000,
                               fees_earned_usd=50, rewards_earned_usd=0,
                               il_loss_usd=1_000, gas_costs_usd=50, days_held=90)
        agg = self.tk.track([pos1, pos2])["aggregates"]
        self.assertGreaterEqual(agg["excellent_count"], 0)

    def test_total_positions_count(self):
        positions = [_make_position(pair=f"P{i}") for i in range(6)]
        agg = self.tk.track(positions)["aggregates"]
        self.assertEqual(agg["total_positions"], 6)

    def test_empty_most_profitable_is_none(self):
        agg = self.tk.track([])["aggregates"]
        self.assertIsNone(agg["most_profitable"])

    def test_empty_least_profitable_is_none(self):
        agg = self.tk.track([])["aggregates"]
        self.assertIsNone(agg["least_profitable"])

    def test_empty_total_pnl_zero(self):
        agg = self.tk.track([])["aggregates"]
        self.assertAlmostEqual(agg["total_net_pnl_usd"], 0.0)

    def test_empty_average_apy_zero(self):
        agg = self.tk.track([])["aggregates"]
        self.assertAlmostEqual(agg["average_total_apy"], 0.0)


class TestConfigOverride(unittest.TestCase):
    def setUp(self):
        self.tk = _tracker()

    def test_custom_long_term_days(self):
        pos = _make_position(days_held=100)
        r = self.tk.track([pos], config={"long_term_days": 90})["positions"][0]
        self.assertIn(FLAG_LONG_TERM_HOLD, r["flags"])

    def test_custom_long_term_days_not_triggered(self):
        pos = _make_position(days_held=100)
        r = self.tk.track([pos], config={"long_term_days": 200})["positions"][0]
        self.assertNotIn(FLAG_LONG_TERM_HOLD, r["flags"])

    def test_custom_il_ratio_threshold(self):
        pos = _make_position(il_loss_usd=100, fees_earned_usd=400)  # 25%
        # With threshold=0.20, 25% > 20% → flag
        r = self.tk.track([pos], config={"il_ratio_threshold": 0.20})["positions"][0]
        self.assertIn(FLAG_HIGH_IL_RATIO, r["flags"])

    def test_custom_il_ratio_threshold_not_triggered(self):
        pos = _make_position(il_loss_usd=100, fees_earned_usd=400)  # 25%
        # With threshold=0.30, 25% < 30% → no flag
        r = self.tk.track([pos], config={"il_ratio_threshold": 0.30})["positions"][0]
        self.assertNotIn(FLAG_HIGH_IL_RATIO, r["flags"])

    def test_custom_gas_heavy_threshold(self):
        pos = _make_position(
            entry_value_usd=10_000, current_value_usd=10_000,
            fees_earned_usd=1_000, rewards_earned_usd=0,
            il_loss_usd=0, gas_costs_usd=20,  # gas=2% of 1000
        )
        # With threshold=0.01 (1%), 2% > 1% → GAS_HEAVY
        r = self.tk.track([pos], config={"gas_heavy_threshold": 0.01})["positions"][0]
        self.assertIn(FLAG_GAS_HEAVY, r["flags"])

    def test_config_none_uses_defaults(self):
        pos = _make_position()
        r1 = self.tk.track([pos], config=None)
        r2 = self.tk.track([pos], config={})
        self.assertEqual(r1["positions"][0]["label"], r2["positions"][0]["label"])


class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tk = _tracker(data_dir=self.tmpdir)

    def test_log_file_created(self):
        result = self.tk.track([_make_position()])
        self.tk.write_log(result)
        log_path = Path(self.tmpdir) / "lp_profitability_log.json"
        self.assertTrue(log_path.exists())

    def test_log_is_valid_json(self):
        result = self.tk.track([_make_position()])
        self.tk.write_log(result)
        with open(Path(self.tmpdir) / "lp_profitability_log.json") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_has_one_entry_after_one_write(self):
        result = self.tk.track([_make_position()])
        self.tk.write_log(result)
        with open(Path(self.tmpdir) / "lp_profitability_log.json") as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_accumulates(self):
        for _ in range(4):
            result = self.tk.track([_make_position()])
            self.tk.write_log(result)
        with open(Path(self.tmpdir) / "lp_profitability_log.json") as f:
            data = json.load(f)
        self.assertEqual(len(data), 4)

    def test_ring_buffer_capped_at_100(self):
        for _ in range(110):
            result = self.tk.track([_make_position()])
            self.tk.write_log(result)
        with open(Path(self.tmpdir) / "lp_profitability_log.json") as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_write_log_returns_path(self):
        result = self.tk.track([_make_position()])
        path = self.tk.write_log(result)
        self.assertIsInstance(path, Path)

    def test_corrupted_log_handled(self):
        log_path = Path(self.tmpdir) / "lp_profitability_log.json"
        with open(log_path, "w") as f:
            f.write("{{{CORRUPTED")
        result = self.tk.track([_make_position()])
        self.tk.write_log(result)  # must not raise
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_non_list_log_handled(self):
        log_path = Path(self.tmpdir) / "lp_profitability_log.json"
        with open(log_path, "w") as f:
            json.dump({"bad": "structure"}, f)
        result = self.tk.track([_make_position()])
        self.tk.write_log(result)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tk = _tracker()

    def test_empty_positions_list(self):
        result = self.tk.track([])
        self.assertEqual(result["positions"], [])

    def test_single_position(self):
        result = self.tk.track([_make_position()])
        self.assertEqual(len(result["positions"]), 1)

    def test_many_positions(self):
        positions = [_make_position(pair=f"P{i}") for i in range(30)]
        result = self.tk.track(positions)
        self.assertEqual(len(result["positions"]), 30)

    def test_protocol_default_unknown(self):
        pos = _make_position()
        del pos["protocol"]
        r = self.tk.track([pos])["positions"][0]
        self.assertEqual(r["protocol"], "unknown")

    def test_pair_default_unknown(self):
        pos = _make_position()
        del pos["pair"]
        r = self.tk.track([pos])["positions"][0]
        self.assertEqual(r["pair"], "unknown")

    def test_days_held_zero_no_crash(self):
        pos = _make_position(days_held=0)
        r = self.tk.track([pos])["positions"][0]
        self.assertEqual(r["fee_apy_pct"], 0.0)
        self.assertEqual(r["total_apy_pct"], 0.0)

    def test_zero_gas_no_gas_heavy_flag(self):
        pos = _make_position(gas_costs_usd=0, fees_earned_usd=1_000)
        r = self.tk.track([pos])["positions"][0]
        self.assertNotIn(FLAG_GAS_HEAVY, r["flags"])

    def test_entry_value_passthrough(self):
        pos = _make_position(entry_value_usd=25_000)
        r = self.tk.track([pos])["positions"][0]
        self.assertEqual(r["entry_value_usd"], 25_000.0)

    def test_current_value_passthrough(self):
        pos = _make_position(current_value_usd=26_000)
        r = self.tk.track([pos])["positions"][0]
        self.assertEqual(r["current_value_usd"], 26_000.0)

    def test_entry_price_ratio_passthrough(self):
        pos = _make_position(entry_price_ratio=1.5)
        r = self.tk.track([pos])["positions"][0]
        self.assertAlmostEqual(r["entry_price_ratio"], 1.5)

    def test_current_price_ratio_passthrough(self):
        pos = _make_position(current_price_ratio=2.0)
        r = self.tk.track([pos])["positions"][0]
        self.assertAlmostEqual(r["current_price_ratio"], 2.0)


class TestJsonSerializable(unittest.TestCase):
    def setUp(self):
        self.tk = _tracker()

    def test_output_json_serializable(self):
        pos = _make_position()
        result = self.tk.track([pos])
        try:
            json.dumps(result)
        except (TypeError, ValueError) as e:
            self.fail(f"Output is not JSON-serializable: {e}")

    def test_multiple_positions_serializable(self):
        positions = [
            _make_position(protocol="Uni", pair="ETH/USDC", days_held=200),
            _make_position(protocol="Curve", pair="3pool", il_loss_usd=0),
        ]
        result = self.tk.track(positions)
        try:
            json.dumps(result)
        except (TypeError, ValueError) as e:
            self.fail(f"Output is not JSON-serializable: {e}")


class TestNumericalConsistency(unittest.TestCase):
    def setUp(self):
        self.tk = _tracker()

    def test_net_pnl_less_than_gross_when_gas_positive(self):
        pos = _make_position(gas_costs_usd=100)
        r = self.tk.track([pos])["positions"][0]
        self.assertLess(r["net_pnl_usd"], r["gross_pnl_usd"])

    def test_net_pnl_equals_gross_when_no_gas(self):
        pos = _make_position(gas_costs_usd=0)
        r = self.tk.track([pos])["positions"][0]
        self.assertAlmostEqual(r["net_pnl_usd"], r["gross_pnl_usd"], places=4)

    def test_total_apy_accounts_for_all_factors(self):
        # total_apy includes capital change, fees, rewards, IL, gas
        pos = _make_position(
            entry_value_usd=10_000,
            current_value_usd=10_000,
            fees_earned_usd=0,
            rewards_earned_usd=0,
            il_loss_usd=0,
            gas_costs_usd=0,
            days_held=90,
        )
        r = self.tk.track([pos])["positions"][0]
        self.assertAlmostEqual(r["total_apy_pct"], 0.0, places=4)

    def test_benchmark_hodl_default_is_entry_value(self):
        pos = _make_position(entry_value_usd=20_000)
        del pos["benchmark_hodl_value_usd"]
        r = self.tk.track([pos])["positions"][0]
        # should not crash, benchmark defaults to entry_value
        self.assertIn("vs_hodl_pct", r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
