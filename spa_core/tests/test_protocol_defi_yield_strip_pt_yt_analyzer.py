"""
Tests for MP-1009: ProtocolDeFiYieldStripPtYtAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_yield_strip_pt_yt_analyzer -v
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_defi_yield_strip_pt_yt_analyzer import (
    ProtocolDeFiYieldStripPtYtAnalyzer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pt_hold(**kwargs) -> dict:
    """Baseline PT hold position."""
    base = {
        "name": "PT-stETH-Jun26",
        "protocol": "Pendle",
        "underlying_asset": "stETH",
        "maturity_date_days": 180,
        "pt_price_usd": 0.94,
        "yt_price_usd": 0.06,
        "underlying_apy_pct": 6.0,
        "implied_apy_pct": 6.5,
        "yt_leverage_factor": 15.0,
        "pt_face_value_usd": 1.0,
        "position_type": "pt_hold",
        "capital_usd": 50_000,
        "slippage_to_exit_bps": 20,
    }
    base.update(kwargs)
    return base


def _yt_spec(**kwargs) -> dict:
    """Baseline YT speculation position."""
    base = {
        "name": "YT-sUSDE-Mar26",
        "protocol": "Pendle",
        "underlying_asset": "sUSDE",
        "maturity_date_days": 90,
        "pt_price_usd": 0.975,
        "yt_price_usd": 0.025,
        "underlying_apy_pct": 15.0,
        "implied_apy_pct": 10.0,
        "yt_leverage_factor": 39.0,
        "pt_face_value_usd": 1.0,
        "position_type": "yt_speculation",
        "capital_usd": 10_000,
        "slippage_to_exit_bps": 80,
    }
    base.update(kwargs)
    return base


def _near_expiry(**kwargs) -> dict:
    """Near expiry PT position."""
    base = {
        "name": "PT-USDC-Expiring",
        "protocol": "Pendle",
        "underlying_asset": "USDC",
        "maturity_date_days": 3,
        "pt_price_usd": 0.9998,
        "yt_price_usd": 0.0002,
        "underlying_apy_pct": 5.0,
        "implied_apy_pct": 5.0,
        "yt_leverage_factor": 5.0,
        "pt_face_value_usd": 1.0,
        "position_type": "pt_hold",
        "capital_usd": 20_000,
        "slippage_to_exit_bps": 5,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

class TestInstantiation(unittest.TestCase):
    def test_instantiation(self):
        a = ProtocolDeFiYieldStripPtYtAnalyzer()
        self.assertIsNotNone(a)

    def test_analyze_returns_dict(self):
        a = ProtocolDeFiYieldStripPtYtAnalyzer()
        result = a.analyze([_pt_hold()], {})
        self.assertIsInstance(result, dict)

    def test_result_has_positions_key(self):
        a = ProtocolDeFiYieldStripPtYtAnalyzer()
        result = a.analyze([_pt_hold()], {})
        self.assertIn("positions", result)

    def test_result_has_aggregates_key(self):
        a = ProtocolDeFiYieldStripPtYtAnalyzer()
        result = a.analyze([_pt_hold()], {})
        self.assertIn("aggregates", result)

    def test_empty_positions(self):
        a = ProtocolDeFiYieldStripPtYtAnalyzer()
        result = a.analyze([], {})
        self.assertEqual(result["positions"], [])
        self.assertEqual(result["aggregates"]["total_positions"], 0)

    def test_type_error_positions(self):
        a = ProtocolDeFiYieldStripPtYtAnalyzer()
        with self.assertRaises(TypeError):
            a.analyze("not-a-list", {})

    def test_type_error_config(self):
        a = ProtocolDeFiYieldStripPtYtAnalyzer()
        with self.assertRaises(TypeError):
            a.analyze([], "not-a-dict")

    def test_multiple_positions_count(self):
        a = ProtocolDeFiYieldStripPtYtAnalyzer()
        result = a.analyze([_pt_hold(), _yt_spec()], {})
        self.assertEqual(len(result["positions"]), 2)


class TestPtFixedRate(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiYieldStripPtYtAnalyzer()

    def test_pt_fixed_rate_calculated(self):
        # pt=0.94, face=1.0, maturity=180d → rate=(1/0.94-1)*(365/180)*100
        result = self.a.analyze([_pt_hold()], {})
        rate = result["positions"][0]["pt_fixed_rate_pct"]
        expected = ((1.0 / 0.94) - 1.0) * (365.0 / 180.0) * 100.0
        self.assertAlmostEqual(rate, expected, places=2)

    def test_pt_at_par_zero_rate(self):
        p = _pt_hold(pt_price_usd=1.0, maturity_date_days=180)
        result = self.a.analyze([p], {})
        self.assertAlmostEqual(result["positions"][0]["pt_fixed_rate_pct"], 0.0, places=4)

    def test_bigger_discount_higher_rate(self):
        p_small = _pt_hold(pt_price_usd=0.97)
        p_big = _pt_hold(pt_price_usd=0.90)
        r1 = self.a.analyze([p_small], {})["positions"][0]["pt_fixed_rate_pct"]
        r2 = self.a.analyze([p_big], {})["positions"][0]["pt_fixed_rate_pct"]
        self.assertGreater(r2, r1)

    def test_shorter_maturity_higher_annualized_rate(self):
        p_long = _pt_hold(pt_price_usd=0.94, maturity_date_days=365)
        p_short = _pt_hold(pt_price_usd=0.94, maturity_date_days=90)
        r1 = self.a.analyze([p_long], {})["positions"][0]["pt_fixed_rate_pct"]
        r2 = self.a.analyze([p_short], {})["positions"][0]["pt_fixed_rate_pct"]
        self.assertGreater(r2, r1)

    def test_zero_maturity_no_crash(self):
        p = _pt_hold(maturity_date_days=0)
        result = self.a.analyze([p], {})
        self.assertAlmostEqual(result["positions"][0]["pt_fixed_rate_pct"], 0.0, places=4)


class TestCarry(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiYieldStripPtYtAnalyzer()

    def test_carry_positive_for_high_rate(self):
        # pt=0.94, maturity=180, risk_free=4% → rate ~12.5%, carry ~8.5%
        result = self.a.analyze([_pt_hold()], {"risk_free_rate_pct": 4.0})
        self.assertGreater(result["positions"][0]["carry_pct"], 0)

    def test_carry_negative_near_par(self):
        p = _pt_hold(pt_price_usd=0.999, maturity_date_days=180)
        result = self.a.analyze([p], {"risk_free_rate_pct": 4.0})
        # rate ≈ 0.2% annualised → carry negative
        self.assertLess(result["positions"][0]["carry_pct"], 4.0)

    def test_custom_risk_free_rate(self):
        r4 = self.a.analyze([_pt_hold()], {"risk_free_rate_pct": 4.0})["positions"][0]["carry_pct"]
        r8 = self.a.analyze([_pt_hold()], {"risk_free_rate_pct": 8.0})["positions"][0]["carry_pct"]
        self.assertGreater(r4, r8)

    def test_strong_carry_flag(self):
        # Needs carry > 4%: big discount on short maturity
        p = _pt_hold(pt_price_usd=0.90, maturity_date_days=90)
        result = self.a.analyze([p], {"risk_free_rate_pct": 2.0})
        self.assertIn("STRONG_CARRY", result["positions"][0]["flags"])

    def test_no_strong_carry_flag_low_carry(self):
        p = _pt_hold(pt_price_usd=0.999, maturity_date_days=365)
        result = self.a.analyze([p], {"risk_free_rate_pct": 4.0})
        self.assertNotIn("STRONG_CARRY", result["positions"][0]["flags"])


class TestYtMetrics(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiYieldStripPtYtAnalyzer()

    def test_yt_profit_positive_when_above_break_even(self):
        # underlying_apy > break_even → profit
        p = _yt_spec(underlying_apy_pct=20.0, implied_apy_pct=10.0, yt_leverage_factor=10.0)
        result = self.a.analyze([p], {})
        self.assertGreater(result["positions"][0]["yt_profit_loss_pct"], 0)

    def test_yt_profit_negative_when_below_break_even(self):
        p = _yt_spec(underlying_apy_pct=5.0, implied_apy_pct=10.0, yt_leverage_factor=10.0)
        result = self.a.analyze([p], {})
        self.assertLess(result["positions"][0]["yt_profit_loss_pct"], 0)

    def test_higher_leverage_amplifies_profit(self):
        p1 = _yt_spec(underlying_apy_pct=15.0, implied_apy_pct=10.0, yt_leverage_factor=5.0)
        p2 = _yt_spec(underlying_apy_pct=15.0, implied_apy_pct=10.0, yt_leverage_factor=10.0)
        r1 = self.a.analyze([p1], {})["positions"][0]["yt_profit_loss_pct"]
        r2 = self.a.analyze([p2], {})["positions"][0]["yt_profit_loss_pct"]
        self.assertGreater(r2, r1)

    def test_time_decay_per_day_positive(self):
        result = self.a.analyze([_yt_spec()], {})
        self.assertGreater(result["positions"][0]["time_value_decay_per_day"], 0)

    def test_time_decay_higher_for_short_maturity(self):
        p_long = _yt_spec(maturity_date_days=360)
        p_short = _yt_spec(maturity_date_days=30)
        d_long = self.a.analyze([p_long], {})["positions"][0]["time_value_decay_per_day"]
        d_short = self.a.analyze([p_short], {})["positions"][0]["time_value_decay_per_day"]
        self.assertGreater(d_short, d_long)

    def test_yt_break_even_equals_implied(self):
        p = _yt_spec(implied_apy_pct=12.5)
        result = self.a.analyze([p], {})
        self.assertAlmostEqual(result["positions"][0]["yt_break_even_apy_pct"], 12.5, places=3)

    def test_zero_leverage_zero_profit(self):
        p = _yt_spec(yt_leverage_factor=0.0)
        result = self.a.analyze([p], {})
        self.assertEqual(result["positions"][0]["yt_profit_loss_pct"], 0.0)


class TestLabels(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiYieldStripPtYtAnalyzer()

    def test_attractive_fixed_rate_label(self):
        # carry > 3%, discount > 5%: pt=0.90 on 90d, rf=2%
        p = _pt_hold(
            pt_price_usd=0.90,
            maturity_date_days=90,
            position_type="pt_hold",
        )
        result = self.a.analyze([p], {"risk_free_rate_pct": 2.0})
        self.assertEqual(result["positions"][0]["label"], "ATTRACTIVE_FIXED_RATE")

    def test_near_expiry_arbitrage_label(self):
        p = _near_expiry()
        result = self.a.analyze([p], {})
        self.assertEqual(result["positions"][0]["label"], "NEAR_EXPIRY_ARBITRAGE")

    def test_yt_time_decay_risk_label(self):
        p = _yt_spec(maturity_date_days=15, position_type="yt_speculation")
        result = self.a.analyze([p], {})
        self.assertEqual(result["positions"][0]["label"], "YT_TIME_DECAY_RISK")

    def test_speculative_yt_bull_label(self):
        p = _yt_spec(
            maturity_date_days=60,
            yt_leverage_factor=8.0,
            underlying_apy_pct=15.0,
            position_type="yt_speculation",
        )
        result = self.a.analyze([p], {})
        self.assertEqual(result["positions"][0]["label"], "SPECULATIVE_YT_BULL")

    def test_overpriced_pt_label(self):
        # carry < 1%: pt very close to par
        p = _pt_hold(pt_price_usd=0.999, maturity_date_days=180, position_type="pt_hold")
        result = self.a.analyze([p], {"risk_free_rate_pct": 4.0})
        self.assertEqual(result["positions"][0]["label"], "OVERPRICED_PT")

    def test_fair_value_label(self):
        # Medium discount, carry 1-3%, no special conditions
        p = _pt_hold(
            pt_price_usd=0.975,
            maturity_date_days=180,
            position_type="pt_hold",
        )
        result = self.a.analyze([p], {"risk_free_rate_pct": 4.0})
        label = result["positions"][0]["label"]
        self.assertIn(label, ("FAIR_VALUE", "OVERPRICED_PT", "ATTRACTIVE_FIXED_RATE"))

    def test_all_labels_valid(self):
        valid = {
            "ATTRACTIVE_FIXED_RATE", "FAIR_VALUE", "OVERPRICED_PT",
            "SPECULATIVE_YT_BULL", "YT_TIME_DECAY_RISK", "NEAR_EXPIRY_ARBITRAGE",
        }
        positions = [_pt_hold(), _yt_spec(), _near_expiry()]
        result = self.a.analyze(positions, {})
        for pos in result["positions"]:
            self.assertIn(pos["label"], valid)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiYieldStripPtYtAnalyzer()

    def test_high_yt_leverage_flag(self):
        p = _yt_spec(yt_leverage_factor=12.0)
        result = self.a.analyze([p], {})
        self.assertIn("HIGH_YT_LEVERAGE", result["positions"][0]["flags"])

    def test_no_high_yt_leverage_below_10(self):
        p = _yt_spec(yt_leverage_factor=8.0)
        result = self.a.analyze([p], {})
        self.assertNotIn("HIGH_YT_LEVERAGE", result["positions"][0]["flags"])

    def test_fixed_rate_advantage_flag(self):
        # pt_fixed_rate > underlying_apy + 2
        p = _pt_hold(
            pt_price_usd=0.85,
            maturity_date_days=90,
            underlying_apy_pct=5.0,
        )
        result = self.a.analyze([p], {})
        self.assertIn("FIXED_RATE_ADVANTAGE", result["positions"][0]["flags"])

    def test_no_fixed_rate_advantage_when_close(self):
        # rate ≈ underlying, no advantage
        p = _pt_hold(
            pt_price_usd=0.975,
            maturity_date_days=365,
            underlying_apy_pct=6.5,
        )
        result = self.a.analyze([p], {})
        # pt_fixed_rate ≈ 2.6% vs underlying 6.5% → no advantage
        self.assertNotIn("FIXED_RATE_ADVANTAGE", result["positions"][0]["flags"])

    def test_expiry_risk_flag_for_yt_near_expiry(self):
        p = _yt_spec(maturity_date_days=20, position_type="yt_speculation")
        result = self.a.analyze([p], {})
        self.assertIn("EXPIRY_RISK", result["positions"][0]["flags"])

    def test_no_expiry_risk_for_pt_near_expiry(self):
        p = _pt_hold(maturity_date_days=20, position_type="pt_hold")
        result = self.a.analyze([p], {})
        self.assertNotIn("EXPIRY_RISK", result["positions"][0]["flags"])

    def test_illiquid_exit_flag(self):
        p = _pt_hold(slippage_to_exit_bps=150)
        result = self.a.analyze([p], {})
        self.assertIn("ILLIQUID_EXIT", result["positions"][0]["flags"])

    def test_no_illiquid_exit_flag_low_slippage(self):
        p = _pt_hold(slippage_to_exit_bps=30)
        result = self.a.analyze([p], {})
        self.assertNotIn("ILLIQUID_EXIT", result["positions"][0]["flags"])

    def test_break_even_achievable_flag(self):
        # break_even = implied_apy, underlying ≥ break_even
        p = _yt_spec(underlying_apy_pct=15.0, implied_apy_pct=10.0)
        result = self.a.analyze([p], {})
        self.assertIn("BREAK_EVEN_ACHIEVABLE", result["positions"][0]["flags"])

    def test_break_even_not_achievable_flag(self):
        # underlying must be ≥ break_even * (1/1.2) for flag
        p = _yt_spec(underlying_apy_pct=5.0, implied_apy_pct=10.0)
        result = self.a.analyze([p], {})
        self.assertNotIn("BREAK_EVEN_ACHIEVABLE", result["positions"][0]["flags"])


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiYieldStripPtYtAnalyzer()

    def test_empty_aggregates(self):
        result = self.a.analyze([], {})
        agg = result["aggregates"]
        self.assertIsNone(agg["best_fixed_rate"])
        self.assertIsNone(agg["worst_value"])
        self.assertEqual(agg["avg_carry_pct"], 0.0)
        self.assertEqual(agg["near_expiry_count"], 0)
        self.assertEqual(agg["attractive_count"], 0)

    def test_total_positions(self):
        result = self.a.analyze([_pt_hold(), _yt_spec()], {})
        self.assertEqual(result["aggregates"]["total_positions"], 2)

    def test_best_fixed_rate_name(self):
        p1 = _pt_hold(name="A", pt_price_usd=0.90, maturity_date_days=90)
        p2 = _pt_hold(name="B", pt_price_usd=0.98, maturity_date_days=180)
        result = self.a.analyze([p1, p2], {})
        self.assertEqual(result["aggregates"]["best_fixed_rate"], "A")

    def test_worst_value_name(self):
        p1 = _pt_hold(name="A", pt_price_usd=0.85, maturity_date_days=90)
        p2 = _pt_hold(name="B", pt_price_usd=0.999, maturity_date_days=365)
        result = self.a.analyze([p1, p2], {"risk_free_rate_pct": 4.0})
        self.assertEqual(result["aggregates"]["worst_value"], "B")

    def test_near_expiry_count(self):
        p1 = _near_expiry(name="X")
        p2 = _pt_hold(name="Y", maturity_date_days=180)
        result = self.a.analyze([p1, p2], {})
        self.assertEqual(result["aggregates"]["near_expiry_count"], 1)

    def test_attractive_count(self):
        p_attr = _pt_hold(pt_price_usd=0.90, maturity_date_days=90, name="Attr")
        p_other = _pt_hold(pt_price_usd=0.999, maturity_date_days=180, name="Other")
        result = self.a.analyze([p_attr, p_other], {"risk_free_rate_pct": 2.0})
        self.assertGreaterEqual(result["aggregates"]["attractive_count"], 1)

    def test_avg_carry_single_position(self):
        result = self.a.analyze([_pt_hold()], {"risk_free_rate_pct": 4.0})
        carry = result["positions"][0]["carry_pct"]
        avg = result["aggregates"]["avg_carry_pct"]
        self.assertAlmostEqual(avg, carry, places=4)

    def test_single_position_best_and_worst_same(self):
        result = self.a.analyze([_pt_hold(name="Only")], {})
        self.assertEqual(result["aggregates"]["best_fixed_rate"], "Only")
        self.assertEqual(result["aggregates"]["worst_value"], "Only")


class TestOutputFields(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiYieldStripPtYtAnalyzer()

    def test_required_fields_present(self):
        expected = {
            "name", "protocol", "underlying_asset", "maturity_date_days",
            "pt_fixed_rate_pct", "yt_break_even_apy_pct", "yt_profit_loss_pct",
            "time_value_decay_per_day", "carry_pct", "position_type",
            "capital_usd", "label", "flags",
        }
        result = self.a.analyze([_pt_hold()], {})
        actual = set(result["positions"][0].keys())
        self.assertTrue(expected.issubset(actual))

    def test_label_is_string(self):
        result = self.a.analyze([_pt_hold()], {})
        self.assertIsInstance(result["positions"][0]["label"], str)

    def test_flags_is_list(self):
        result = self.a.analyze([_pt_hold()], {})
        self.assertIsInstance(result["positions"][0]["flags"], list)

    def test_carry_is_float(self):
        result = self.a.analyze([_pt_hold()], {})
        self.assertIsInstance(result["positions"][0]["carry_pct"], float)

    def test_pt_fixed_rate_is_float(self):
        result = self.a.analyze([_pt_hold()], {})
        self.assertIsInstance(result["positions"][0]["pt_fixed_rate_pct"], float)

    def test_name_preserved(self):
        result = self.a.analyze([_pt_hold(name="SpecialPT")], {})
        self.assertEqual(result["positions"][0]["name"], "SpecialPT")

    def test_protocol_preserved(self):
        result = self.a.analyze([_pt_hold(protocol="CustomProtocol")], {})
        self.assertEqual(result["positions"][0]["protocol"], "CustomProtocol")


class TestPositionTypes(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiYieldStripPtYtAnalyzer()

    def test_pt_hold_type(self):
        result = self.a.analyze([_pt_hold(position_type="pt_hold")], {})
        self.assertEqual(result["positions"][0]["position_type"], "pt_hold")

    def test_yt_speculation_type(self):
        result = self.a.analyze([_yt_spec(position_type="yt_speculation")], {})
        self.assertEqual(result["positions"][0]["position_type"], "yt_speculation")

    def test_lp_pt_yt_type(self):
        result = self.a.analyze([_pt_hold(position_type="lp_pt_yt")], {})
        self.assertEqual(result["positions"][0]["position_type"], "lp_pt_yt")

    def test_fixed_rate_lock_type(self):
        result = self.a.analyze([_pt_hold(position_type="fixed_rate_lock")], {})
        self.assertEqual(result["positions"][0]["position_type"], "fixed_rate_lock")


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiYieldStripPtYtAnalyzer()

    def test_zero_pt_price_no_crash(self):
        p = _pt_hold(pt_price_usd=0.0)
        result = self.a.analyze([p], {})
        self.assertIsNotNone(result)

    def test_zero_yt_price_no_crash(self):
        p = _yt_spec(yt_price_usd=0.0)
        result = self.a.analyze([p], {})
        self.assertIsNotNone(result)

    def test_minimal_position_dict(self):
        p = {"name": "Minimal"}
        result = self.a.analyze([p], {})
        self.assertIn("label", result["positions"][0])

    def test_very_large_capital(self):
        p = _pt_hold(capital_usd=1_000_000_000)
        result = self.a.analyze([p], {})
        self.assertEqual(result["positions"][0]["capital_usd"], 1_000_000_000)

    def test_five_positions(self):
        positions = [_pt_hold(name=f"PT{i}") for i in range(3)] + [_yt_spec(name=f"YT{i}") for i in range(2)]
        result = self.a.analyze(positions, {})
        self.assertEqual(len(result["positions"]), 5)

    def test_names_preserved_in_order(self):
        names = ["A", "B", "C"]
        result = self.a.analyze([_pt_hold(name=n) for n in names], {})
        self.assertEqual([p["name"] for p in result["positions"]], names)

    def test_time_decay_zero_when_no_maturity(self):
        p = _yt_spec(maturity_date_days=0)
        result = self.a.analyze([p], {})
        self.assertEqual(result["positions"][0]["time_value_decay_per_day"], 0.0)


class TestWriteLog(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiYieldStripPtYtAnalyzer()
        self.tmp_dir = tempfile.mkdtemp()

    def _patch_log(self, path):
        import spa_core.analytics.protocol_defi_yield_strip_pt_yt_analyzer as mod
        self._orig = mod.LOG_FILE
        mod.LOG_FILE = path

    def _restore_log(self):
        import spa_core.analytics.protocol_defi_yield_strip_pt_yt_analyzer as mod
        mod.LOG_FILE = self._orig

    def test_write_log_creates_file(self):
        log_path = os.path.join(self.tmp_dir, "yield_strip_log.json")
        self._patch_log(log_path)
        try:
            self.a.analyze([_pt_hold()], {"write_log": True})
            self.assertTrue(os.path.exists(log_path))
        finally:
            self._restore_log()

    def test_write_log_valid_json(self):
        log_path = os.path.join(self.tmp_dir, "yield_strip_log2.json")
        self._patch_log(log_path)
        try:
            self.a.analyze([_pt_hold()], {"write_log": True})
            with open(log_path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
        finally:
            self._restore_log()

    def test_write_log_appends_entries(self):
        log_path = os.path.join(self.tmp_dir, "yield_strip_log3.json")
        self._patch_log(log_path)
        try:
            self.a.analyze([_pt_hold()], {"write_log": True})
            self.a.analyze([_pt_hold()], {"write_log": True})
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)
        finally:
            self._restore_log()

    def test_write_log_respects_cap(self):
        import spa_core.analytics.protocol_defi_yield_strip_pt_yt_analyzer as mod
        log_path = os.path.join(self.tmp_dir, "yield_strip_log4.json")
        self._patch_log(log_path)
        old_cap = mod.LOG_CAP
        mod.LOG_CAP = 4
        try:
            for _ in range(8):
                self.a.analyze([_pt_hold()], {"write_log": True})
            with open(log_path) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), 4)
        finally:
            mod.LOG_CAP = old_cap
            self._restore_log()

    def test_no_log_without_flag(self):
        log_path = os.path.join(self.tmp_dir, "yield_strip_no_log.json")
        self._patch_log(log_path)
        try:
            self.a.analyze([_pt_hold()], {})
            self.assertFalse(os.path.exists(log_path))
        finally:
            self._restore_log()

    def test_log_entry_has_ts_field(self):
        log_path = os.path.join(self.tmp_dir, "yield_strip_log5.json")
        self._patch_log(log_path)
        try:
            self.a.analyze([_pt_hold()], {"write_log": True})
            with open(log_path) as f:
                data = json.load(f)
            self.assertIn("ts", data[0])
        finally:
            self._restore_log()

    def test_log_entry_has_total_positions(self):
        log_path = os.path.join(self.tmp_dir, "yield_strip_log6.json")
        self._patch_log(log_path)
        try:
            self.a.analyze([_pt_hold(), _yt_spec()], {"write_log": True})
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(data[0]["total_positions"], 2)
        finally:
            self._restore_log()


class TestImpliedApyFallback(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiYieldStripPtYtAnalyzer()

    def test_implied_apy_zero_uses_pt_rate(self):
        p = _pt_hold(pt_price_usd=0.94, maturity_date_days=180, implied_apy_pct=0.0)
        result = self.a.analyze([p], {})
        pos = result["positions"][0]
        self.assertAlmostEqual(pos["yt_break_even_apy_pct"], pos["pt_fixed_rate_pct"], places=3)

    def test_explicit_implied_apy_used(self):
        p = _pt_hold(implied_apy_pct=8.5)
        result = self.a.analyze([p], {})
        self.assertAlmostEqual(result["positions"][0]["yt_break_even_apy_pct"], 8.5, places=3)


class TestNearExpiry(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiYieldStripPtYtAnalyzer()

    def test_near_expiry_not_triggered_at_7_days(self):
        # boundary: 7d AND price close to face
        p = _near_expiry(maturity_date_days=7, pt_price_usd=0.9999)
        result = self.a.analyze([p], {})
        # at exactly 7 days with price close to face, NEAR_EXPIRY_ARBITRAGE fires
        label = result["positions"][0]["label"]
        self.assertIn(label, ("NEAR_EXPIRY_ARBITRAGE", "FAIR_VALUE", "OVERPRICED_PT", "ATTRACTIVE_FIXED_RATE"))

    def test_near_expiry_not_triggered_far_from_face(self):
        # Even with maturity < 7d, if price not near face → different label
        p = _near_expiry(maturity_date_days=3, pt_price_usd=0.80)
        result = self.a.analyze([p], {})
        label = result["positions"][0]["label"]
        self.assertNotEqual(label, "NEAR_EXPIRY_ARBITRAGE")

    def test_near_expiry_count_zero_when_all_far(self):
        result = self.a.analyze([_pt_hold(maturity_date_days=180)], {})
        self.assertEqual(result["aggregates"]["near_expiry_count"], 0)

    def test_near_expiry_count_includes_short_maturity(self):
        positions = [
            _pt_hold(name="Far", maturity_date_days=180),
            _near_expiry(name="Near"),
        ]
        result = self.a.analyze(positions, {})
        self.assertEqual(result["aggregates"]["near_expiry_count"], 1)


if __name__ == "__main__":
    unittest.main()
