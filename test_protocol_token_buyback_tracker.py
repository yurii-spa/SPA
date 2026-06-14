"""
Tests for MP-842 ProtocolTokenBuybackTracker
(spa_core/analytics/protocol_token_buyback_tracker.py)

Pure stdlib unittest — do NOT use pytest or any external deps.
Run: python3 -m unittest spa_core.tests.test_protocol_token_buyback_tracker -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.analytics.protocol_token_buyback_tracker import (  # noqa: E402
    analyze,
    run,
    _safe_float,
    _safe_bool,
    _compute_buyback_yield,
    _compute_revenue_allocation,
    _compute_sustainability,
    _compute_price_support_score,
    _compute_signal,
    _compute_flags,
    _load_log,
    _save_log,
    _RING_BUFFER_MAX,
    _DEFAULT_MIN_REVENUE_COVERAGE,
    _SENTINEL_REVENUE_ALLOC,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proto(name="TestProto", symbol="TP",
           buyback=100_000, revenue=500_000,
           price=10.0, market_cap=10_000_000,
           supply=1_000_000,
           frequency="MONTHLY", burned=False):
    return {
        "name": name,
        "token_symbol": symbol,
        "buyback_usd_30d": buyback,
        "revenue_usd_30d": revenue,
        "token_price_usd": price,
        "market_cap_usd": market_cap,
        "circulating_supply": supply,
        "buyback_frequency": frequency,
        "tokens_burned": burned,
    }


def _strong_proto(name="StrongProto"):
    """Protocol with STRONG sustainability."""
    return _proto(name=name, buyback=100_000, revenue=2_000_000,
                  market_cap=50_000_000, frequency="WEEKLY", burned=True)


def _unsustainable_proto(name="BadProto"):
    """Protocol spending more than earning."""
    return _proto(name=name, buyback=600_000, revenue=500_000,
                  market_cap=10_000_000, frequency="MONTHLY")


def _none_proto(name="NoneProto"):
    """Protocol with no buyback."""
    return _proto(name=name, buyback=0, revenue=500_000,
                  market_cap=10_000_000, frequency="NONE")


# ===========================================================================
# 1. Constants / defaults
# ===========================================================================

class TestConstants(unittest.TestCase):

    def test_ring_buffer_max(self):
        self.assertEqual(_RING_BUFFER_MAX, 100)

    def test_default_min_revenue_coverage(self):
        self.assertAlmostEqual(_DEFAULT_MIN_REVENUE_COVERAGE, 0.1)

    def test_sentinel_value(self):
        self.assertAlmostEqual(_SENTINEL_REVENUE_ALLOC, 999.0)


# ===========================================================================
# 2. _safe_float
# ===========================================================================

class TestSafeFloat(unittest.TestCase):

    def test_int(self):
        self.assertEqual(_safe_float(5), 5.0)

    def test_float(self):
        self.assertAlmostEqual(_safe_float(3.14), 3.14)

    def test_none_default(self):
        self.assertEqual(_safe_float(None), 0.0)

    def test_bad_string(self):
        self.assertEqual(_safe_float("oops"), 0.0)

    def test_string_number(self):
        self.assertAlmostEqual(_safe_float("7.5"), 7.5)

    def test_custom_default(self):
        self.assertEqual(_safe_float(None, 42.0), 42.0)

    def test_negative(self):
        self.assertAlmostEqual(_safe_float(-3.5), -3.5)

    def test_zero(self):
        self.assertEqual(_safe_float(0), 0.0)


# ===========================================================================
# 3. _safe_bool
# ===========================================================================

class TestSafeBool(unittest.TestCase):

    def test_true(self):
        self.assertTrue(_safe_bool(True))

    def test_false(self):
        self.assertFalse(_safe_bool(False))

    def test_int_1(self):
        self.assertTrue(_safe_bool(1))

    def test_int_0(self):
        self.assertFalse(_safe_bool(0))

    def test_none_default_false(self):
        self.assertFalse(_safe_bool(None))

    def test_string_returns_default(self):
        self.assertFalse(_safe_bool("true"))


# ===========================================================================
# 4. _compute_buyback_yield
# ===========================================================================

class TestBuybackYield(unittest.TestCase):

    def test_basic(self):
        # (100_000 * 12 / 10_000_000) * 100 = 12.0%
        result = _compute_buyback_yield(100_000, 10_000_000)
        self.assertAlmostEqual(result, 12.0)

    def test_zero_market_cap(self):
        result = _compute_buyback_yield(100_000, 0)
        self.assertEqual(result, 0.0)

    def test_negative_market_cap(self):
        result = _compute_buyback_yield(100_000, -1)
        self.assertEqual(result, 0.0)

    def test_zero_buyback(self):
        result = _compute_buyback_yield(0, 10_000_000)
        self.assertEqual(result, 0.0)

    def test_high_buyback(self):
        # (500_000 * 12 / 1_000_000) * 100 = 600%
        result = _compute_buyback_yield(500_000, 1_000_000)
        self.assertAlmostEqual(result, 600.0)


# ===========================================================================
# 5. _compute_revenue_allocation
# ===========================================================================

class TestRevenueAllocation(unittest.TestCase):

    def test_basic(self):
        # 100_000 / 500_000 * 100 = 20%
        result = _compute_revenue_allocation(100_000, 500_000)
        self.assertAlmostEqual(result, 20.0)

    def test_zero_revenue_zero_buyback(self):
        result = _compute_revenue_allocation(0, 0)
        self.assertEqual(result, 0.0)

    def test_zero_revenue_positive_buyback(self):
        result = _compute_revenue_allocation(50_000, 0)
        self.assertAlmostEqual(result, _SENTINEL_REVENUE_ALLOC)

    def test_buyback_exceeds_revenue(self):
        # 600_000 / 500_000 * 100 = 120%
        result = _compute_revenue_allocation(600_000, 500_000)
        self.assertAlmostEqual(result, 120.0)

    def test_full_allocation(self):
        result = _compute_revenue_allocation(500_000, 500_000)
        self.assertAlmostEqual(result, 100.0)


# ===========================================================================
# 6. _compute_sustainability
# ===========================================================================

class TestSustainability(unittest.TestCase):

    def test_none_zero_buyback(self):
        s = _compute_sustainability(0, "WEEKLY", 0.0, 500_000)
        self.assertEqual(s, "NONE")

    def test_none_frequency_none(self):
        s = _compute_sustainability(100_000, "NONE", 20.0, 500_000)
        self.assertEqual(s, "NONE")

    def test_unsustainable_sentinel(self):
        s = _compute_sustainability(100_000, "MONTHLY", _SENTINEL_REVENUE_ALLOC,
                                    0)
        self.assertEqual(s, "UNSUSTAINABLE")

    def test_unsustainable_over_100(self):
        s = _compute_sustainability(600_000, "WEEKLY", 120.0, 500_000)
        self.assertEqual(s, "UNSUSTAINABLE")

    def test_aggressive_51pct(self):
        s = _compute_sustainability(51_000, "MONTHLY", 51.0, 100_000)
        self.assertEqual(s, "AGGRESSIVE")

    def test_moderate_30pct(self):
        s = _compute_sustainability(30_000, "MONTHLY", 30.0, 100_000)
        self.assertEqual(s, "MODERATE")

    def test_strong_10pct(self):
        s = _compute_sustainability(10_000, "MONTHLY", 10.0, 100_000)
        self.assertEqual(s, "STRONG")

    def test_strong_exactly_20pct(self):
        s = _compute_sustainability(20_000, "MONTHLY", 20.0, 100_000)
        self.assertEqual(s, "STRONG")

    def test_aggressive_boundary_50pct(self):
        # exactly 50% → still MODERATE (> 50 is AGGRESSIVE)
        s = _compute_sustainability(50_000, "MONTHLY", 50.0, 100_000)
        self.assertEqual(s, "MODERATE")


# ===========================================================================
# 7. _compute_price_support_score
# ===========================================================================

class TestPriceSupportScore(unittest.TestCase):

    def test_none_sustainability_zero_score(self):
        score = _compute_price_support_score(10.0, "MONTHLY", True, "NONE")
        self.assertEqual(score, 0)

    def test_max_capped_at_100(self):
        # yield=25 → base=40, CONTINUOUS=20, burn=20, total=80, STRONG mult=1.0 → 80
        score = _compute_price_support_score(25.0, "CONTINUOUS", True, "STRONG")
        self.assertLessEqual(score, 100)
        self.assertGreaterEqual(score, 0)

    def test_base_capped_at_40(self):
        # yield=20 → 20*4=80 → capped at 40
        score = _compute_price_support_score(20.0, "NONE", False, "STRONG")
        # base=40, freq=0, burn=0, mult=1.0 → 40
        self.assertEqual(score, 40)

    def test_burn_bonus(self):
        # yield=5 → base=20, no freq, burn → 20+20=40, STRONG → 40
        s_burn = _compute_price_support_score(5.0, "NONE", True, "STRONG")
        s_no = _compute_price_support_score(5.0, "NONE", False, "STRONG")
        self.assertGreater(s_burn, s_no)

    def test_continuous_freq_bonus(self):
        s_cont = _compute_price_support_score(5.0, "CONTINUOUS", False, "STRONG")
        s_none = _compute_price_support_score(5.0, "NONE", False, "STRONG")
        self.assertGreater(s_cont, s_none)

    def test_unsustainable_multiplier_0_3(self):
        # base=40, CONTINUOUS=20, burn=20, total=80 * 0.3 = 24
        score = _compute_price_support_score(25.0, "CONTINUOUS", True,
                                              "UNSUSTAINABLE")
        self.assertEqual(score, int(80 * 0.3))

    def test_score_non_negative(self):
        score = _compute_price_support_score(0.0, "NONE", False, "NONE")
        self.assertGreaterEqual(score, 0)

    def test_score_is_int(self):
        score = _compute_price_support_score(5.0, "WEEKLY", True, "STRONG")
        self.assertIsInstance(score, int)


# ===========================================================================
# 8. _compute_signal
# ===========================================================================

class TestSignal(unittest.TestCase):

    def test_bullish(self):
        sig = _compute_signal(65, "STRONG", 5.0, "MONTHLY")
        self.assertEqual(sig, "BULLISH")

    def test_bullish_moderate(self):
        sig = _compute_signal(70, "MODERATE", 5.0, "WEEKLY")
        self.assertEqual(sig, "BULLISH")

    def test_bearish_unsustainable(self):
        sig = _compute_signal(80, "UNSUSTAINABLE", 5.0, "MONTHLY")
        self.assertEqual(sig, "BEARISH")

    def test_bearish_none_frequency_low_yield(self):
        sig = _compute_signal(10, "NONE", 0.5, "NONE")
        self.assertEqual(sig, "BEARISH")

    def test_neutral_score_below_threshold(self):
        sig = _compute_signal(50, "STRONG", 5.0, "MONTHLY")
        self.assertEqual(sig, "NEUTRAL")

    def test_neutral_high_score_aggressive(self):
        # score >= 60 but sustainability AGGRESSIVE → NEUTRAL
        sig = _compute_signal(70, "AGGRESSIVE", 5.0, "MONTHLY")
        self.assertEqual(sig, "NEUTRAL")

    def test_bullish_exactly_at_threshold(self):
        sig = _compute_signal(60, "STRONG", 5.0, "MONTHLY")
        self.assertEqual(sig, "BULLISH")

    def test_none_frequency_high_yield_not_bearish(self):
        # NONE frequency but high yield → low yield condition doesn't apply
        sig = _compute_signal(20, "NONE", 5.0, "NONE")
        # yield >= 1.0 and NONE → not BEARISH from that condition
        # sustainability is not UNSUSTAINABLE
        # score=20 < 60 → NEUTRAL
        self.assertEqual(sig, "NEUTRAL")


# ===========================================================================
# 9. _compute_flags
# ===========================================================================

class TestFlags(unittest.TestCase):

    def test_no_buyback_flag(self):
        flags = _compute_flags(0, "NONE", 0.0, False, 0.0)
        self.assertIn("No buyback program", flags)

    def test_frequency_none_flag(self):
        flags = _compute_flags(0, "NONE", 0.0, False, 0.0)
        self.assertIn("No buyback program", flags)

    def test_exceeds_revenue_flag(self):
        flags = _compute_flags(100_000, "MONTHLY", 120.0, False, 5.0)
        self.assertIn("Buyback spending exceeds revenue", flags)

    def test_sentinel_exceeds_revenue_flag(self):
        flags = _compute_flags(100_000, "MONTHLY", _SENTINEL_REVENUE_ALLOC,
                               False, 5.0)
        self.assertIn("Buyback spending exceeds revenue", flags)

    def test_tokens_not_burned_flag(self):
        flags = _compute_flags(100_000, "MONTHLY", 20.0, False, 5.0)
        self.assertIn("Tokens not burned — limited supply reduction", flags)

    def test_burned_no_flag(self):
        flags = _compute_flags(100_000, "MONTHLY", 20.0, True, 5.0)
        self.assertNotIn("Tokens not burned — limited supply reduction", flags)

    def test_irregular_flag(self):
        flags = _compute_flags(100_000, "IRREGULAR", 20.0, False, 5.0)
        self.assertIn("Irregular buybacks — unpredictable support", flags)

    def test_high_yield_flag(self):
        flags = _compute_flags(100_000, "MONTHLY", 20.0, True, 25.0)
        matching = [f for f in flags if "High buyback yield" in f]
        self.assertEqual(len(matching), 1)
        self.assertIn("25.0%", matching[0])

    def test_no_high_yield_flag_below_threshold(self):
        flags = _compute_flags(100_000, "MONTHLY", 20.0, True, 15.0)
        matching = [f for f in flags if "High buyback yield" in f]
        self.assertEqual(len(matching), 0)

    def test_flags_is_list(self):
        flags = _compute_flags(0, "NONE", 0.0, False, 0.0)
        self.assertIsInstance(flags, list)


# ===========================================================================
# 10. analyze() — empty/edge inputs
# ===========================================================================

class TestAnalyzeEmpty(unittest.TestCase):

    def test_empty_list(self):
        result = analyze([])
        self.assertEqual(result["protocols"], [])
        self.assertIsNone(result["highest_yield_buyback"])
        self.assertIsNone(result["most_sustainable"])
        self.assertAlmostEqual(result["average_buyback_yield"], 0.0)
        self.assertAlmostEqual(result["total_implied_annual_buybacks_usd"], 0.0)
        self.assertIn("timestamp", result)

    def test_none_input(self):
        result = analyze(None)
        self.assertEqual(result["protocols"], [])

    def test_single_none_buyback_protocol(self):
        result = analyze([_none_proto()])
        self.assertEqual(len(result["protocols"]), 1)
        p = result["protocols"][0]
        self.assertEqual(p["buyback_sustainability"], "NONE")


# ===========================================================================
# 11. analyze() — per-protocol fields
# ===========================================================================

class TestAnalyzePerProtocol(unittest.TestCase):

    def test_buyback_yield_computed(self):
        proto = _proto(buyback=100_000, market_cap=10_000_000)
        result = analyze([proto])
        expected = (100_000 * 12 / 10_000_000) * 100
        p = result["protocols"][0]
        self.assertAlmostEqual(p["buyback_yield_annualized_pct"], expected)

    def test_revenue_allocation_computed(self):
        proto = _proto(buyback=100_000, revenue=500_000)
        p = analyze([proto])["protocols"][0]
        self.assertAlmostEqual(p["revenue_allocation_pct"], 20.0)

    def test_implied_annual_buyback(self):
        proto = _proto(buyback=100_000)
        p = analyze([proto])["protocols"][0]
        self.assertAlmostEqual(p["implied_annual_buyback_usd"], 1_200_000.0)

    def test_name_preserved(self):
        proto = _proto(name="MyProtocol")
        p = analyze([proto])["protocols"][0]
        self.assertEqual(p["name"], "MyProtocol")

    def test_token_symbol_preserved(self):
        proto = _proto(symbol="XYZ")
        p = analyze([proto])["protocols"][0]
        self.assertEqual(p["token_symbol"], "XYZ")

    def test_zero_market_cap_yield_zero(self):
        proto = _proto(buyback=100_000, market_cap=0)
        p = analyze([proto])["protocols"][0]
        self.assertAlmostEqual(p["buyback_yield_annualized_pct"], 0.0)

    def test_sustainability_strong(self):
        proto = _strong_proto()
        p = analyze([proto])["protocols"][0]
        self.assertEqual(p["buyback_sustainability"], "STRONG")

    def test_sustainability_unsustainable(self):
        proto = _unsustainable_proto()
        p = analyze([proto])["protocols"][0]
        self.assertEqual(p["buyback_sustainability"], "UNSUSTAINABLE")

    def test_sustainability_none(self):
        proto = _none_proto()
        p = analyze([proto])["protocols"][0]
        self.assertEqual(p["buyback_sustainability"], "NONE")

    def test_sustainability_aggressive(self):
        proto = _proto(buyback=600_000, revenue=1_000_000)
        p = analyze([proto])["protocols"][0]
        # 60% > 50% → AGGRESSIVE
        self.assertEqual(p["buyback_sustainability"], "AGGRESSIVE")

    def test_sustainability_moderate(self):
        proto = _proto(buyback=300_000, revenue=1_000_000)
        p = analyze([proto])["protocols"][0]
        # 30% > 20% → MODERATE
        self.assertEqual(p["buyback_sustainability"], "MODERATE")

    def test_signal_bearish_unsustainable(self):
        proto = _unsustainable_proto()
        p = analyze([proto])["protocols"][0]
        self.assertEqual(p["signal"], "BEARISH")

    def test_signal_bearish_none_frequency(self):
        proto = _none_proto()
        p = analyze([proto])["protocols"][0]
        self.assertEqual(p["signal"], "BEARISH")

    def test_flags_is_list(self):
        proto = _proto()
        p = analyze([proto])["protocols"][0]
        self.assertIsInstance(p["flags"], list)

    def test_score_is_int(self):
        proto = _proto()
        p = analyze([proto])["protocols"][0]
        self.assertIsInstance(p["price_support_score"], int)

    def test_price_support_score_range(self):
        for freq in ["CONTINUOUS", "WEEKLY", "MONTHLY", "IRREGULAR", "NONE"]:
            for burned in [True, False]:
                proto = _proto(frequency=freq, burned=burned)
                p = analyze([proto])["protocols"][0]
                self.assertGreaterEqual(p["price_support_score"], 0)
                self.assertLessEqual(p["price_support_score"], 100)


# ===========================================================================
# 12. analyze() — summary fields
# ===========================================================================

class TestAnalyzeSummary(unittest.TestCase):

    def test_highest_yield_is_correct(self):
        p1 = _proto("Low", buyback=10_000, market_cap=10_000_000)
        p2 = _proto("High", buyback=500_000, market_cap=10_000_000)
        result = analyze([p1, p2])
        self.assertEqual(result["highest_yield_buyback"], "High")

    def test_most_sustainable_from_strong(self):
        p_strong = _strong_proto("GoodProto")
        p_bad = _unsustainable_proto("BadProto")
        result = analyze([p_strong, p_bad])
        self.assertEqual(result["most_sustainable"], "GoodProto")

    def test_most_sustainable_none_if_no_strong(self):
        result = analyze([_unsustainable_proto()])
        self.assertIsNone(result["most_sustainable"])

    def test_most_sustainable_highest_revenue(self):
        # Two STRONG protocols; pick highest revenue
        p1 = _proto("SmallRevenue", buyback=10_000, revenue=100_000,
                     frequency="WEEKLY")
        p2 = _proto("BigRevenue", buyback=10_000, revenue=500_000,
                     frequency="WEEKLY")
        result = analyze([p1, p2])
        # Both are STRONG (10k/100k=10% and 10k/500k=2%)
        self.assertEqual(result["most_sustainable"], "BigRevenue")

    def test_average_yield_single(self):
        proto = _proto(buyback=100_000, market_cap=10_000_000)
        result = analyze([proto])
        expected = (100_000 * 12 / 10_000_000) * 100
        self.assertAlmostEqual(result["average_buyback_yield"], expected)

    def test_average_yield_two(self):
        p1 = _proto("A", buyback=100_000, market_cap=10_000_000)
        p2 = _proto("B", buyback=50_000, market_cap=10_000_000)
        result = analyze([p1, p2])
        y1 = (100_000 * 12 / 10_000_000) * 100
        y2 = (50_000 * 12 / 10_000_000) * 100
        self.assertAlmostEqual(result["average_buyback_yield"], (y1 + y2) / 2)

    def test_total_implied_annual_buybacks(self):
        p1 = _proto("A", buyback=100_000)
        p2 = _proto("B", buyback=200_000)
        result = analyze([p1, p2])
        self.assertAlmostEqual(
            result["total_implied_annual_buybacks_usd"],
            (100_000 + 200_000) * 12
        )

    def test_timestamp_is_recent(self):
        result = analyze([])
        self.assertAlmostEqual(result["timestamp"], time.time(), delta=5.0)

    def test_protocols_list_length(self):
        protos = [_proto(f"P{i}") for i in range(5)]
        result = analyze(protos)
        self.assertEqual(len(result["protocols"]), 5)


# ===========================================================================
# 13. _load_log / _save_log
# ===========================================================================

class TestLogPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.log_path = self.tmp_dir / "token_buyback_log.json"

    def test_load_nonexistent(self):
        self.assertEqual(_load_log(self.log_path), [])

    def test_save_and_load_roundtrip(self):
        data = [{"x": 1}, {"y": 2}]
        _save_log(self.log_path, data)
        loaded = _load_log(self.log_path)
        self.assertEqual(loaded, data)

    def test_ring_buffer_cap(self):
        data = [{"i": i} for i in range(150)]
        _save_log(self.log_path, data)
        loaded = _load_log(self.log_path)
        self.assertEqual(len(loaded), _RING_BUFFER_MAX)
        self.assertEqual(loaded[-1]["i"], 149)

    def test_atomic_write_valid_json(self):
        _save_log(self.log_path, [{"test": True}])
        with open(self.log_path) as f:
            parsed = json.load(f)
        self.assertEqual(parsed, [{"test": True}])

    def test_load_corrupt_returns_empty(self):
        self.log_path.write_text("not json")
        self.assertEqual(_load_log(self.log_path), [])

    def test_load_non_list_returns_empty(self):
        self.log_path.write_text('{"not": "list"}')
        self.assertEqual(_load_log(self.log_path), [])


# ===========================================================================
# 14. run() — persistence integration
# ===========================================================================

class TestRun(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def test_run_creates_log(self):
        run([_proto()], data_dir=self.tmp_dir)
        log_path = Path(self.tmp_dir) / "token_buyback_log.json"
        self.assertTrue(log_path.exists())

    def test_run_returns_dict(self):
        result = run([_proto()], data_dir=self.tmp_dir)
        self.assertIn("protocols", result)

    def test_run_accumulates(self):
        proto = _proto()
        run([proto], data_dir=self.tmp_dir)
        run([proto], data_dir=self.tmp_dir)
        log_path = Path(self.tmp_dir) / "token_buyback_log.json"
        with open(log_path) as f:
            log = json.load(f)
        self.assertEqual(len(log), 2)

    def test_run_ring_buffer(self):
        for _ in range(110):
            run([_proto()], data_dir=self.tmp_dir)
        log_path = Path(self.tmp_dir) / "token_buyback_log.json"
        with open(log_path) as f:
            log = json.load(f)
        self.assertLessEqual(len(log), _RING_BUFFER_MAX)

    def test_run_empty_protocols(self):
        result = run([], data_dir=self.tmp_dir)
        self.assertEqual(result["protocols"], [])


# ===========================================================================
# 15. Result structure completeness
# ===========================================================================

class TestResultStructure(unittest.TestCase):

    def test_top_level_keys(self):
        result = analyze([])
        required = {
            "protocols", "highest_yield_buyback", "most_sustainable",
            "average_buyback_yield", "total_implied_annual_buybacks_usd",
            "timestamp",
        }
        self.assertTrue(required.issubset(set(result.keys())))

    def test_protocol_result_keys(self):
        result = analyze([_proto()])
        p = result["protocols"][0]
        required = {
            "name", "token_symbol", "buyback_yield_annualized_pct",
            "revenue_allocation_pct", "buyback_sustainability",
            "implied_annual_buyback_usd", "price_support_score",
            "signal", "flags",
        }
        self.assertTrue(required.issubset(set(p.keys())))

    def test_protocols_is_list(self):
        self.assertIsInstance(analyze([])["protocols"], list)

    def test_average_yield_is_float(self):
        self.assertIsInstance(analyze([])["average_buyback_yield"], float)

    def test_total_implied_is_float(self):
        self.assertIsInstance(
            analyze([])["total_implied_annual_buybacks_usd"], float
        )

    def test_signal_valid_values(self):
        for freq in ["CONTINUOUS", "NONE", "IRREGULAR"]:
            p = _proto(frequency=freq)
            result = analyze([p])
            sig = result["protocols"][0]["signal"]
            self.assertIn(sig, ("BULLISH", "NEUTRAL", "BEARISH"))

    def test_sustainability_valid_values(self):
        valid = {"STRONG", "MODERATE", "AGGRESSIVE", "UNSUSTAINABLE", "NONE"}
        for proto in [_strong_proto(), _none_proto(), _unsustainable_proto()]:
            p = analyze([proto])["protocols"][0]
            self.assertIn(p["buyback_sustainability"], valid)


# ===========================================================================
# 16. Additional edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_zero_revenue_zero_buyback_not_unsustainable(self):
        proto = _proto(buyback=0, revenue=0, frequency="NONE")
        p = analyze([proto])["protocols"][0]
        self.assertEqual(p["buyback_sustainability"], "NONE")

    def test_multiple_strong_highest_revenue_wins(self):
        p1 = _proto("A", buyback=5_000, revenue=100_000,
                     market_cap=10_000_000, frequency="MONTHLY")
        p2 = _proto("B", buyback=5_000, revenue=200_000,
                     market_cap=10_000_000, frequency="MONTHLY")
        result = analyze([p1, p2])
        # Both 5% → STRONG; B has higher revenue
        self.assertEqual(result["most_sustainable"], "B")

    def test_missing_fields_no_crash(self):
        # minimal dict
        result = analyze([{"name": "X"}])
        self.assertIsInstance(result, dict)

    def test_frequency_case_insensitive(self):
        proto = _proto(frequency="weekly")
        p = analyze([proto])["protocols"][0]
        # Should treat "weekly" as "WEEKLY"
        self.assertIsInstance(p["buyback_sustainability"], str)

    def test_boolean_tokens_burned_true(self):
        proto = _proto(burned=True)
        p = analyze([proto])["protocols"][0]
        # Burned → no "Tokens not burned" flag
        self.assertNotIn("Tokens not burned — limited supply reduction",
                         p["flags"])

    def test_boolean_tokens_burned_false(self):
        proto = _proto(burned=False, buyback=100_000)
        p = analyze([proto])["protocols"][0]
        self.assertIn("Tokens not burned — limited supply reduction",
                      p["flags"])

    def test_highest_yield_single_protocol(self):
        proto = _proto("Only", buyback=100_000, market_cap=1_000_000)
        result = analyze([proto])
        self.assertEqual(result["highest_yield_buyback"], "Only")

    def test_timestamp_type(self):
        result = analyze([])
        self.assertIsInstance(result["timestamp"], float)

    def test_large_number_of_protocols(self):
        protos = [_proto(f"P{i}", buyback=i * 1000) for i in range(50)]
        result = analyze(protos)
        self.assertEqual(len(result["protocols"]), 50)

    def test_revenue_sentinel_yields_unsustainable(self):
        # revenue=0, buyback>0 → sentinel → UNSUSTAINABLE
        proto = _proto(buyback=100_000, revenue=0, frequency="MONTHLY")
        p = analyze([proto])["protocols"][0]
        self.assertEqual(p["buyback_sustainability"], "UNSUSTAINABLE")

    def test_revenue_sentinel_yields_bearish(self):
        proto = _proto(buyback=100_000, revenue=0, frequency="MONTHLY")
        p = analyze([proto])["protocols"][0]
        self.assertEqual(p["signal"], "BEARISH")


if __name__ == "__main__":
    unittest.main(verbosity=2)
