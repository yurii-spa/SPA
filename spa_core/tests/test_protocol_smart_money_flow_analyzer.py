"""
Tests for MP-900 ProtocolSmartMoneyFlowAnalyzer (MILESTONE)
Run: python3 -m unittest spa_core.tests.test_protocol_smart_money_flow_analyzer -v
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_smart_money_flow_analyzer import (
    analyze,
    log_result,
    _safe_div,
    _safe_mean,
    _divergence_signal,
    _smart_money_conviction,
    _large_wallet_concentration,
    _recency_signal,
    _price_alignment,
    _composite_score,
    _signal_label,
    _build_flags,
    _recommendation,
    _analyse_protocol,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def make_proto(**overrides) -> dict:
    base = {
        "name": "Aave V3",
        "smart_wallet_inflow_30d_usd": 5_000_000.0,
        "smart_wallet_outflow_30d_usd": 1_000_000.0,
        "retail_inflow_30d_usd": 2_000_000.0,
        "retail_outflow_30d_usd": 500_000.0,
        "large_wallet_count": 20,
        "total_tvl_usd": 100_000_000.0,
        "smart_money_tvl_pct": 30.0,
        "days_since_last_large_deposit": 7,
        "price_correlation_30d": 0.5,
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. _safe_div
# ===========================================================================
class TestSafeDiv(unittest.TestCase):

    def test_normal(self):
        self.assertAlmostEqual(_safe_div(10.0, 2.0), 5.0)

    def test_zero_denominator(self):
        self.assertEqual(_safe_div(99.0, 0.0), 0.0)

    def test_zero_numerator(self):
        self.assertEqual(_safe_div(0.0, 5.0), 0.0)

    def test_both_zero(self):
        self.assertEqual(_safe_div(0.0, 0.0), 0.0)

    def test_negative_result(self):
        self.assertAlmostEqual(_safe_div(-6.0, 3.0), -2.0)

    def test_fractional(self):
        self.assertAlmostEqual(_safe_div(1.0, 3.0), 1 / 3)


# ===========================================================================
# 2. _safe_mean
# ===========================================================================
class TestSafeMean(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(_safe_mean([]), 0.0)

    def test_single(self):
        self.assertEqual(_safe_mean([42.0]), 42.0)

    def test_multiple(self):
        self.assertAlmostEqual(_safe_mean([10.0, 20.0, 30.0]), 20.0)

    def test_negatives(self):
        self.assertAlmostEqual(_safe_mean([-5.0, 5.0]), 0.0)

    def test_all_same(self):
        self.assertAlmostEqual(_safe_mean([7.0, 7.0, 7.0]), 7.0)


# ===========================================================================
# 3. _divergence_signal
# ===========================================================================
class TestDivergenceSignal(unittest.TestCase):

    SIG = 1_000_000.0

    def test_both_below_significance_neutral(self):
        self.assertEqual(_divergence_signal(500_000, 400_000, self.SIG), "NEUTRAL")

    def test_smart_accumulating_retail_exiting(self):
        self.assertEqual(
            _divergence_signal(3_000_000, -2_000_000, self.SIG),
            "SMART_ACCUMULATING_RETAIL_EXITING",
        )

    def test_smart_exiting_retail_buying(self):
        self.assertEqual(
            _divergence_signal(-2_000_000, 3_000_000, self.SIG),
            "SMART_EXITING_RETAIL_BUYING",
        )

    def test_both_accumulating(self):
        self.assertEqual(
            _divergence_signal(2_000_000, 1_500_000, self.SIG),
            "BOTH_ACCUMULATING",
        )

    def test_both_exiting(self):
        self.assertEqual(
            _divergence_signal(-2_000_000, -1_500_000, self.SIG),
            "BOTH_EXITING",
        )

    def test_smart_above_sig_retail_near_zero(self):
        # Smart significant, retail near-zero → NEUTRAL (retail < sig and retail=0)
        self.assertEqual(
            _divergence_signal(2_000_000, 0, self.SIG),
            "NEUTRAL",
        )

    def test_all_zeros_neutral(self):
        self.assertEqual(_divergence_signal(0, 0, self.SIG), "NEUTRAL")

    def test_large_flows_smart_accumulating(self):
        self.assertEqual(
            _divergence_signal(50_000_000, -10_000_000, self.SIG),
            "SMART_ACCUMULATING_RETAIL_EXITING",
        )

    def test_custom_low_significance(self):
        # With threshold=1, any non-zero flow is significant
        self.assertEqual(
            _divergence_signal(100, -50, 1.0),
            "SMART_ACCUMULATING_RETAIL_EXITING",
        )

    def test_custom_high_significance_gives_neutral(self):
        # With threshold=1B, 5M flows are below threshold
        self.assertEqual(
            _divergence_signal(5_000_000, -3_000_000, 1_000_000_000.0),
            "NEUTRAL",
        )

    def test_retail_negative_smart_positive_both_above_sig(self):
        # smart > 0, retail < 0 → SMART_ACCUMULATING_RETAIL_EXITING regardless of magnitude
        # The "NEUTRAL" path only triggers when BOTH are below significance threshold
        self.assertEqual(
            _divergence_signal(500_000, -2_000_000, self.SIG),
            "SMART_ACCUMULATING_RETAIL_EXITING",
        )


# ===========================================================================
# 4. _smart_money_conviction
# ===========================================================================
class TestSmartMoneyConviction(unittest.TestCase):

    def test_very_high(self):
        self.assertEqual(_smart_money_conviction(6.0), "VERY_HIGH")

    def test_very_high_exactly_5_not_included(self):
        # >5 required; =5 is not >5
        self.assertEqual(_smart_money_conviction(5.0), "HIGH")

    def test_high(self):
        self.assertEqual(_smart_money_conviction(3.0), "HIGH")

    def test_high_exactly_2_not_included(self):
        self.assertEqual(_smart_money_conviction(2.0), "MODERATE")

    def test_moderate(self):
        self.assertEqual(_smart_money_conviction(1.0), "MODERATE")

    def test_moderate_exactly_0_5_not_included(self):
        self.assertEqual(_smart_money_conviction(0.5), "LOW")

    def test_low(self):
        self.assertEqual(_smart_money_conviction(0.1), "LOW")

    def test_low_boundary_zero_not_included(self):
        self.assertEqual(_smart_money_conviction(0.0), "NEGATIVE")

    def test_negative(self):
        self.assertEqual(_smart_money_conviction(-3.0), "NEGATIVE")

    def test_large_ratio_very_high(self):
        self.assertEqual(_smart_money_conviction(100.0), "VERY_HIGH")


# ===========================================================================
# 5. _large_wallet_concentration
# ===========================================================================
class TestLargeWalletConcentration(unittest.TestCase):

    def test_high(self):
        self.assertEqual(_large_wallet_concentration(60.0), "HIGH")

    def test_high_boundary_50_not_included(self):
        self.assertEqual(_large_wallet_concentration(50.0), "MODERATE")

    def test_moderate(self):
        self.assertEqual(_large_wallet_concentration(35.0), "MODERATE")

    def test_moderate_boundary_25_not_included(self):
        self.assertEqual(_large_wallet_concentration(25.0), "LOW")

    def test_low(self):
        self.assertEqual(_large_wallet_concentration(15.0), "LOW")

    def test_low_boundary_10_not_included(self):
        self.assertEqual(_large_wallet_concentration(10.0), "MINIMAL")

    def test_minimal(self):
        self.assertEqual(_large_wallet_concentration(5.0), "MINIMAL")

    def test_zero(self):
        self.assertEqual(_large_wallet_concentration(0.0), "MINIMAL")

    def test_hundred(self):
        self.assertEqual(_large_wallet_concentration(100.0), "HIGH")


# ===========================================================================
# 6. _recency_signal
# ===========================================================================
class TestRecencySignal(unittest.TestCase):

    def test_very_recent_0(self):
        self.assertEqual(_recency_signal(0), "VERY_RECENT")

    def test_very_recent_2(self):
        self.assertEqual(_recency_signal(2), "VERY_RECENT")

    def test_recent_boundary_3(self):
        self.assertEqual(_recency_signal(3), "RECENT")

    def test_recent_13(self):
        self.assertEqual(_recency_signal(13), "RECENT")

    def test_cooling_boundary_14(self):
        self.assertEqual(_recency_signal(14), "COOLING")

    def test_cooling_20(self):
        self.assertEqual(_recency_signal(20), "COOLING")

    def test_cold_boundary_30(self):
        self.assertEqual(_recency_signal(30), "COLD")

    def test_cold_100(self):
        self.assertEqual(_recency_signal(100), "COLD")


# ===========================================================================
# 7. _price_alignment
# ===========================================================================
class TestPriceAlignment(unittest.TestCase):

    def test_aligned_high(self):
        self.assertEqual(_price_alignment(0.8), "ALIGNED")

    def test_aligned_boundary_0_3_not_included(self):
        # >0.3 required
        self.assertEqual(_price_alignment(0.3), "NEUTRAL")

    def test_aligned_just_above(self):
        self.assertEqual(_price_alignment(0.31), "ALIGNED")

    def test_neutral_zero(self):
        self.assertEqual(_price_alignment(0.0), "NEUTRAL")

    def test_neutral_negative_small(self):
        self.assertEqual(_price_alignment(-0.2), "NEUTRAL")

    def test_contrarian_boundary_minus_0_3(self):
        # <=-0.3 → CONTRARIAN
        self.assertEqual(_price_alignment(-0.3), "CONTRARIAN")

    def test_contrarian(self):
        self.assertEqual(_price_alignment(-0.9), "CONTRARIAN")


# ===========================================================================
# 8. _composite_score
# ===========================================================================
class TestCompositeScore(unittest.TestCase):

    def test_max_score(self):
        score = _composite_score("VERY_HIGH", "VERY_RECENT", "ALIGNED", "HIGH")
        self.assertEqual(score, 100)

    def test_min_score(self):
        score = _composite_score("NEGATIVE", "COLD", "CONTRARIAN", "MINIMAL")
        self.assertEqual(score, 3)   # 0+0+0+3 = 3

    def test_clamped_to_100(self):
        score = _composite_score("VERY_HIGH", "VERY_RECENT", "ALIGNED", "HIGH")
        self.assertLessEqual(score, 100)

    def test_clamped_to_zero(self):
        score = _composite_score("NEGATIVE", "COLD", "CONTRARIAN", "MINIMAL")
        self.assertGreaterEqual(score, 0)

    def test_typical_buy(self):
        # HIGH(30) + RECENT(15) + ALIGNED(20) + MODERATE(15) = 80
        score = _composite_score("HIGH", "RECENT", "ALIGNED", "MODERATE")
        self.assertEqual(score, 80)

    def test_typical_neutral(self):
        # MODERATE(20) + COOLING(8) + NEUTRAL(10) + LOW(8) = 46
        score = _composite_score("MODERATE", "COOLING", "NEUTRAL", "LOW")
        self.assertEqual(score, 46)

    def test_negative_conviction_cold_contrarian_minimal(self):
        score = _composite_score("NEGATIVE", "COLD", "CONTRARIAN", "MINIMAL")
        self.assertEqual(score, 3)  # 0+0+0+3

    def test_low_conviction_recent_neutral_low(self):
        # LOW(10) + RECENT(15) + NEUTRAL(10) + LOW(8) = 43
        score = _composite_score("LOW", "RECENT", "NEUTRAL", "LOW")
        self.assertEqual(score, 43)


# ===========================================================================
# 9. _signal_label
# ===========================================================================
class TestSignalLabel(unittest.TestCase):

    def test_strong_buy_75(self):
        self.assertEqual(_signal_label(75), "STRONG_BUY")

    def test_strong_buy_100(self):
        self.assertEqual(_signal_label(100), "STRONG_BUY")

    def test_buy_60(self):
        self.assertEqual(_signal_label(60), "BUY")

    def test_buy_74(self):
        self.assertEqual(_signal_label(74), "BUY")

    def test_neutral_40(self):
        self.assertEqual(_signal_label(40), "NEUTRAL")

    def test_neutral_59(self):
        self.assertEqual(_signal_label(59), "NEUTRAL")

    def test_caution_25(self):
        self.assertEqual(_signal_label(25), "CAUTION")

    def test_caution_39(self):
        self.assertEqual(_signal_label(39), "CAUTION")

    def test_sell_24(self):
        self.assertEqual(_signal_label(24), "SELL")

    def test_sell_0(self):
        self.assertEqual(_signal_label(0), "SELL")


# ===========================================================================
# 10. _build_flags
# ===========================================================================
class TestBuildFlags(unittest.TestCase):

    SIG = 1_000_000.0

    def test_whale_accumulation(self):
        flags = _build_flags("VERY_HIGH", 5_000_000, "BOTH_ACCUMULATING",
                              "RECENT", self.SIG)
        self.assertIn("WHALE_ACCUMULATION", flags)

    def test_whale_accumulation_high_conviction(self):
        flags = _build_flags("HIGH", 2_000_000, "BOTH_ACCUMULATING",
                              "RECENT", self.SIG)
        self.assertIn("WHALE_ACCUMULATION", flags)

    def test_no_whale_if_flow_negative(self):
        # conviction is HIGH but flow is negative → no WHALE_ACCUMULATION
        flags = _build_flags("HIGH", -500_000, "BOTH_EXITING",
                              "RECENT", self.SIG)
        self.assertNotIn("WHALE_ACCUMULATION", flags)

    def test_no_whale_if_moderate_conviction(self):
        flags = _build_flags("MODERATE", 2_000_000, "BOTH_ACCUMULATING",
                              "RECENT", self.SIG)
        self.assertNotIn("WHALE_ACCUMULATION", flags)

    def test_smart_exit(self):
        flags = _build_flags("NEGATIVE", -2_000_000, "SMART_EXITING_RETAIL_BUYING",
                              "RECENT", self.SIG)
        self.assertIn("SMART_EXIT", flags)

    def test_smart_exit_boundary_exactly_sig_not_flagged(self):
        # net_smart = -1_000_000 → NOT < -1_000_000
        flags = _build_flags("NEGATIVE", -1_000_000, "SMART_EXITING_RETAIL_BUYING",
                              "RECENT", self.SIG)
        self.assertNotIn("SMART_EXIT", flags)

    def test_divergence_warning(self):
        flags = _build_flags("NEGATIVE", -2_000_000,
                              "SMART_EXITING_RETAIL_BUYING", "RECENT", self.SIG)
        self.assertIn("DIVERGENCE_WARNING", flags)

    def test_no_divergence_warning_other_signals(self):
        flags = _build_flags("VERY_HIGH", 5_000_000,
                              "SMART_ACCUMULATING_RETAIL_EXITING", "RECENT", self.SIG)
        self.assertNotIn("DIVERGENCE_WARNING", flags)

    def test_stale_signal(self):
        flags = _build_flags("LOW", 0, "NEUTRAL", "COLD", self.SIG)
        self.assertIn("STALE_SIGNAL", flags)

    def test_no_stale_signal_when_recent(self):
        flags = _build_flags("LOW", 0, "NEUTRAL", "RECENT", self.SIG)
        self.assertNotIn("STALE_SIGNAL", flags)

    def test_all_flags_possible(self):
        # VERY_HIGH + positive flow → WHALE_ACCUMULATION
        # flow < -sig → SMART_EXIT (conflict here — let's just test possible combos)
        flags = _build_flags("LOW", -2_000_000,
                              "SMART_EXITING_RETAIL_BUYING", "COLD", self.SIG)
        self.assertIn("SMART_EXIT", flags)
        self.assertIn("DIVERGENCE_WARNING", flags)
        self.assertIn("STALE_SIGNAL", flags)

    def test_no_flags_clean_signal(self):
        flags = _build_flags("MODERATE", 500_000, "BOTH_ACCUMULATING",
                              "RECENT", self.SIG)
        self.assertEqual(flags, [])


# ===========================================================================
# 11. _recommendation
# ===========================================================================
class TestRecommendation(unittest.TestCase):

    def test_strong_buy(self):
        r = _recommendation("STRONG_BUY", 5_000_000, "VERY_HIGH", 85, "ALIGNED")
        self.assertIn("5,000,000", r)
        self.assertIn("VERY_HIGH", r)
        self.assertIn("Strong", r)

    def test_buy(self):
        r = _recommendation("BUY", 2_000_000, "HIGH", 65, "ALIGNED")
        self.assertIn("65", r)
        self.assertIn("Consider entry", r)

    def test_neutral(self):
        r = _recommendation("NEUTRAL", 100_000, "LOW", 45, "NEUTRAL")
        self.assertIn("NEUTRAL", r)
        self.assertIn("Monitor", r)

    def test_caution(self):
        r = _recommendation("CAUTION", -500_000, "NEGATIVE", 30, "CONTRARIAN")
        self.assertIn("-500,000", r)
        self.assertIn("cautious", r)

    def test_sell(self):
        r = _recommendation("SELL", -3_000_000, "NEGATIVE", 10, "CONTRARIAN")
        self.assertIn("exiting", r)
        self.assertIn("Review", r)

    def test_recommendation_is_string(self):
        for signal in ("STRONG_BUY", "BUY", "NEUTRAL", "CAUTION", "SELL"):
            r = _recommendation(signal, 0.0, "LOW", 50, "NEUTRAL")
            self.assertIsInstance(r, str)
            self.assertGreater(len(r), 0)


# ===========================================================================
# 12. _analyse_protocol
# ===========================================================================
class TestAnalyseProtocol(unittest.TestCase):

    def test_structure(self):
        result = _analyse_protocol(make_proto(), 1_000_000.0)
        for key in ("name", "net_smart_flow_usd", "net_retail_flow_usd",
                    "smart_flow_ratio", "retail_flow_ratio",
                    "divergence_signal", "smart_money_conviction",
                    "large_wallet_concentration", "recency_signal",
                    "price_alignment", "composite_bullish_score",
                    "signal_label", "flags", "recommendation"):
            self.assertIn(key, result)

    def test_net_smart_flow(self):
        proto = make_proto(smart_wallet_inflow_30d_usd=8_000_000,
                           smart_wallet_outflow_30d_usd=3_000_000)
        r = _analyse_protocol(proto, 1_000_000.0)
        self.assertAlmostEqual(r["net_smart_flow_usd"], 5_000_000.0)

    def test_net_retail_flow(self):
        proto = make_proto(retail_inflow_30d_usd=4_000_000,
                           retail_outflow_30d_usd=1_000_000)
        r = _analyse_protocol(proto, 1_000_000.0)
        self.assertAlmostEqual(r["net_retail_flow_usd"], 3_000_000.0)

    def test_smart_flow_ratio_zero_tvl(self):
        proto = make_proto(total_tvl_usd=0.0)
        r = _analyse_protocol(proto, 1_000_000.0)
        self.assertEqual(r["smart_flow_ratio"], 0.0)
        self.assertEqual(r["retail_flow_ratio"], 0.0)

    def test_smart_flow_ratio(self):
        proto = make_proto(
            smart_wallet_inflow_30d_usd=5_000_000,
            smart_wallet_outflow_30d_usd=1_000_000,
            total_tvl_usd=100_000_000,
        )
        r = _analyse_protocol(proto, 1_000_000.0)
        # net = 4M / 100M * 100 = 4.0%
        self.assertAlmostEqual(r["smart_flow_ratio"], 4.0)

    def test_very_high_conviction(self):
        proto = make_proto(
            smart_wallet_inflow_30d_usd=10_000_000,
            smart_wallet_outflow_30d_usd=1_000_000,
            total_tvl_usd=100_000_000,
        )
        r = _analyse_protocol(proto, 1_000_000.0)
        # ratio = 9% → VERY_HIGH
        self.assertEqual(r["smart_money_conviction"], "VERY_HIGH")

    def test_negative_conviction_zero_tvl(self):
        proto = make_proto(total_tvl_usd=0.0)
        r = _analyse_protocol(proto, 1_000_000.0)
        # ratio = 0 → NEGATIVE
        self.assertEqual(r["smart_money_conviction"], "NEGATIVE")

    def test_concentration_high(self):
        proto = make_proto(smart_money_tvl_pct=60.0)
        r = _analyse_protocol(proto, 1_000_000.0)
        self.assertEqual(r["large_wallet_concentration"], "HIGH")

    def test_recency_very_recent(self):
        proto = make_proto(days_since_last_large_deposit=1)
        r = _analyse_protocol(proto, 1_000_000.0)
        self.assertEqual(r["recency_signal"], "VERY_RECENT")

    def test_recency_cold(self):
        proto = make_proto(days_since_last_large_deposit=60)
        r = _analyse_protocol(proto, 1_000_000.0)
        self.assertEqual(r["recency_signal"], "COLD")

    def test_price_alignment_aligned(self):
        proto = make_proto(price_correlation_30d=0.7)
        r = _analyse_protocol(proto, 1_000_000.0)
        self.assertEqual(r["price_alignment"], "ALIGNED")

    def test_price_alignment_contrarian(self):
        proto = make_proto(price_correlation_30d=-0.5)
        r = _analyse_protocol(proto, 1_000_000.0)
        self.assertEqual(r["price_alignment"], "CONTRARIAN")

    def test_composite_score_range(self):
        r = _analyse_protocol(make_proto(), 1_000_000.0)
        self.assertGreaterEqual(r["composite_bullish_score"], 0)
        self.assertLessEqual(r["composite_bullish_score"], 100)

    def test_signal_label_string(self):
        r = _analyse_protocol(make_proto(), 1_000_000.0)
        self.assertIn(r["signal_label"],
                      ("STRONG_BUY", "BUY", "NEUTRAL", "CAUTION", "SELL"))

    def test_flags_is_list(self):
        r = _analyse_protocol(make_proto(), 1_000_000.0)
        self.assertIsInstance(r["flags"], list)

    def test_recommendation_non_empty(self):
        r = _analyse_protocol(make_proto(), 1_000_000.0)
        self.assertIsInstance(r["recommendation"], str)
        self.assertGreater(len(r["recommendation"]), 0)

    def test_whale_accumulation_flag_present(self):
        proto = make_proto(
            smart_wallet_inflow_30d_usd=20_000_000,
            smart_wallet_outflow_30d_usd=1_000_000,
            total_tvl_usd=100_000_000,
        )
        r = _analyse_protocol(proto, 1_000_000.0)
        # ratio = 19% → VERY_HIGH conviction → WHALE_ACCUMULATION
        self.assertIn("WHALE_ACCUMULATION", r["flags"])

    def test_smart_exit_flag(self):
        proto = make_proto(
            smart_wallet_inflow_30d_usd=0,
            smart_wallet_outflow_30d_usd=5_000_000,
        )
        r = _analyse_protocol(proto, 1_000_000.0)
        self.assertIn("SMART_EXIT", r["flags"])

    def test_stale_signal_flag(self):
        proto = make_proto(days_since_last_large_deposit=90)
        r = _analyse_protocol(proto, 1_000_000.0)
        self.assertIn("STALE_SIGNAL", r["flags"])

    def test_divergence_warning_flag(self):
        proto = make_proto(
            smart_wallet_inflow_30d_usd=0,
            smart_wallet_outflow_30d_usd=3_000_000,
            retail_inflow_30d_usd=2_000_000,
            retail_outflow_30d_usd=0,
        )
        r = _analyse_protocol(proto, 1_000_000.0)
        self.assertIn("DIVERGENCE_WARNING", r["flags"])

    def test_name_preserved(self):
        proto = make_proto(name="Morpho Steakhouse")
        r = _analyse_protocol(proto, 1_000_000.0)
        self.assertEqual(r["name"], "Morpho Steakhouse")


# ===========================================================================
# 13. analyze() — aggregate
# ===========================================================================
class TestAnalyze(unittest.TestCase):

    def test_empty_returns_defaults(self):
        result = analyze([])
        self.assertEqual(result["protocols"], [])
        self.assertIsNone(result["strongest_buy_signal"])
        self.assertIsNone(result["strongest_sell_signal"])
        self.assertEqual(result["average_bullish_score"], 0.0)
        self.assertEqual(result["accumulation_count"], 0)
        self.assertIn("timestamp", result)

    def test_single_protocol_structure(self):
        result = analyze([make_proto()])
        self.assertEqual(len(result["protocols"]), 1)
        self.assertIsNotNone(result["strongest_buy_signal"])
        self.assertIsNotNone(result["strongest_sell_signal"])

    def test_strongest_buy_signal(self):
        high = make_proto(name="HighConv",
                          smart_wallet_inflow_30d_usd=10_000_000,
                          smart_wallet_outflow_30d_usd=0,
                          smart_money_tvl_pct=60.0,
                          days_since_last_large_deposit=1,
                          price_correlation_30d=0.9,
                          total_tvl_usd=100_000_000)
        low  = make_proto(name="LowConv",
                          smart_wallet_inflow_30d_usd=0,
                          smart_wallet_outflow_30d_usd=5_000_000,
                          smart_money_tvl_pct=5.0,
                          days_since_last_large_deposit=60,
                          price_correlation_30d=-0.8,
                          total_tvl_usd=100_000_000)
        result = analyze([high, low])
        self.assertEqual(result["strongest_buy_signal"], "HighConv")
        self.assertEqual(result["strongest_sell_signal"], "LowConv")

    def test_average_bullish_score(self):
        p1 = make_proto(name="A")
        p2 = make_proto(name="B")
        result = analyze([p1, p2])
        expected = (result["protocols"][0]["composite_bullish_score"]
                    + result["protocols"][1]["composite_bullish_score"]) / 2
        self.assertAlmostEqual(result["average_bullish_score"], expected)

    def test_accumulation_count(self):
        high1 = make_proto(name="H1",
                            smart_wallet_inflow_30d_usd=10_000_000,
                            smart_wallet_outflow_30d_usd=0,
                            total_tvl_usd=100_000_000)
        high2 = make_proto(name="H2",
                            smart_wallet_inflow_30d_usd=5_000_000,
                            smart_wallet_outflow_30d_usd=0,
                            total_tvl_usd=100_000_000)
        low   = make_proto(name="L",
                            smart_wallet_inflow_30d_usd=0,
                            smart_wallet_outflow_30d_usd=0,
                            total_tvl_usd=100_000_000)
        result = analyze([high1, high2, low])
        # high1 ratio=10% → VERY_HIGH; high2 ratio=5% → VERY_HIGH; low ratio=0 → NEGATIVE
        self.assertEqual(result["accumulation_count"], 2)

    def test_timestamp_is_recent(self):
        result = analyze([make_proto()])
        self.assertAlmostEqual(result["timestamp"], time.time(), delta=5.0)

    def test_multiple_protocols_count(self):
        protocols = [make_proto(name=f"P{i}") for i in range(5)]
        result = analyze(protocols)
        self.assertEqual(len(result["protocols"]), 5)

    def test_custom_flow_significance(self):
        # With high threshold, small flows → NEUTRAL
        p = make_proto(
            smart_wallet_inflow_30d_usd=500_000,
            smart_wallet_outflow_30d_usd=0,
            retail_inflow_30d_usd=400_000,
            retail_outflow_30d_usd=0,
        )
        result = analyze([p], config={"flow_significance_usd": 2_000_000.0})
        self.assertEqual(result["protocols"][0]["divergence_signal"], "NEUTRAL")

    def test_zero_tvl_no_crash(self):
        p = make_proto(total_tvl_usd=0.0)
        result = analyze([p])
        self.assertEqual(len(result["protocols"]), 1)

    def test_all_protocols_have_signal_label(self):
        protocols = [make_proto(name=f"P{i}") for i in range(6)]
        result = analyze(protocols)
        for p in result["protocols"]:
            self.assertIn(p["signal_label"],
                          ("STRONG_BUY", "BUY", "NEUTRAL", "CAUTION", "SELL"))

    def test_single_buy_and_sell_same_protocol(self):
        result = analyze([make_proto(name="Solo")])
        self.assertEqual(result["strongest_buy_signal"], "Solo")
        self.assertEqual(result["strongest_sell_signal"], "Solo")

    def test_divergence_signal_propagates(self):
        p = make_proto(
            smart_wallet_inflow_30d_usd=5_000_000,
            smart_wallet_outflow_30d_usd=0,
            retail_inflow_30d_usd=0,
            retail_outflow_30d_usd=2_000_000,
        )
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["divergence_signal"],
                         "SMART_ACCUMULATING_RETAIL_EXITING")

    def test_both_exiting_divergence(self):
        p = make_proto(
            smart_wallet_inflow_30d_usd=0,
            smart_wallet_outflow_30d_usd=3_000_000,
            retail_inflow_30d_usd=0,
            retail_outflow_30d_usd=2_000_000,
        )
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["divergence_signal"], "BOTH_EXITING")

    def test_accumulation_count_zero_when_all_negative(self):
        protocols = [
            make_proto(name=f"P{i}",
                       smart_wallet_inflow_30d_usd=0,
                       smart_wallet_outflow_30d_usd=5_000_000,
                       total_tvl_usd=100_000_000)
            for i in range(3)
        ]
        result = analyze(protocols)
        self.assertEqual(result["accumulation_count"], 0)

    def test_high_conviction_counted(self):
        p = make_proto(
            smart_wallet_inflow_30d_usd=4_000_000,
            smart_wallet_outflow_30d_usd=0,
            total_tvl_usd=100_000_000,
        )
        result = analyze([p])
        # ratio = 4% → HIGH conviction → counted
        self.assertEqual(result["accumulation_count"], 1)


# ===========================================================================
# 14. log_result()
# ===========================================================================
class TestLogResult(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def test_creates_file(self):
        result = analyze([make_proto()])
        log_result(result, data_dir=self.tmp_dir)
        self.assertTrue(
            os.path.exists(os.path.join(self.tmp_dir, "smart_money_flow_log.json"))
        )

    def test_appends_entries(self):
        result = analyze([make_proto()])
        log_result(result, data_dir=self.tmp_dir)
        log_result(result, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "smart_money_flow_log.json")) as fh:
            log = json.load(fh)
        self.assertEqual(len(log), 2)

    def test_ring_buffer_cap(self):
        result = analyze([make_proto()])
        for _ in range(110):
            log_result(result, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "smart_money_flow_log.json")) as fh:
            log = json.load(fh)
        self.assertLessEqual(len(log), 100)

    def test_ring_buffer_keeps_recent(self):
        # Fill to 105 entries; log should contain last 100
        result_a = analyze([make_proto(name="A")])
        result_b = analyze([make_proto(name="B")])
        for _ in range(100):
            log_result(result_a, data_dir=self.tmp_dir)
        log_result(result_b, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "smart_money_flow_log.json")) as fh:
            log = json.load(fh)
        # Last entry should be result_b
        self.assertEqual(log[-1]["protocols"][0]["name"], "B")

    def test_valid_json(self):
        result = analyze([make_proto()])
        log_result(result, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "smart_money_flow_log.json")) as fh:
            log = json.load(fh)
        self.assertIsInstance(log, list)

    def test_corrupt_log_recovers(self):
        log_path = os.path.join(self.tmp_dir, "smart_money_flow_log.json")
        with open(log_path, "w") as fh:
            fh.write("not json at all!")
        result = analyze([make_proto()])
        log_result(result, data_dir=self.tmp_dir)
        with open(log_path) as fh:
            log = json.load(fh)
        self.assertEqual(len(log), 1)

    def test_non_list_log_recovers(self):
        log_path = os.path.join(self.tmp_dir, "smart_money_flow_log.json")
        with open(log_path, "w") as fh:
            json.dump({"unexpected": "dict"}, fh)
        result = analyze([make_proto()])
        log_result(result, data_dir=self.tmp_dir)
        with open(log_path) as fh:
            log = json.load(fh)
        self.assertIsInstance(log, list)

    def test_empty_result_logged(self):
        result = analyze([])
        log_result(result, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "smart_money_flow_log.json")) as fh:
            log = json.load(fh)
        self.assertEqual(len(log), 1)

    def test_atomic_write_no_partial(self):
        """Log file should always be valid JSON after write."""
        result = analyze([make_proto()])
        for _ in range(10):
            log_result(result, data_dir=self.tmp_dir)
        log_path = os.path.join(self.tmp_dir, "smart_money_flow_log.json")
        with open(log_path) as fh:
            content = fh.read()
        json.loads(content)  # Should not raise


# ===========================================================================
# 15. Edge cases & integration
# ===========================================================================
class TestEdgeCases(unittest.TestCase):

    def test_all_zero_flows(self):
        p = make_proto(
            smart_wallet_inflow_30d_usd=0,
            smart_wallet_outflow_30d_usd=0,
            retail_inflow_30d_usd=0,
            retail_outflow_30d_usd=0,
            total_tvl_usd=50_000_000,
        )
        result = analyze([p])
        proto = result["protocols"][0]
        self.assertEqual(proto["net_smart_flow_usd"], 0.0)
        self.assertEqual(proto["net_retail_flow_usd"], 0.0)
        self.assertEqual(proto["divergence_signal"], "NEUTRAL")
        self.assertEqual(proto["smart_money_conviction"], "NEGATIVE")

    def test_very_high_tvl(self):
        p = make_proto(total_tvl_usd=10_000_000_000.0)
        result = analyze([p])
        self.assertIsInstance(result["protocols"][0]["smart_flow_ratio"], float)

    def test_very_small_tvl(self):
        p = make_proto(total_tvl_usd=1.0,
                       smart_wallet_inflow_30d_usd=10,
                       smart_wallet_outflow_30d_usd=0)
        result = analyze([p])
        # ratio = 10/1*100 = 1000% → clamped or not, conviction VERY_HIGH
        self.assertEqual(result["protocols"][0]["smart_money_conviction"], "VERY_HIGH")

    def test_negative_correlation_contrarian(self):
        p = make_proto(price_correlation_30d=-1.0)
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["price_alignment"], "CONTRARIAN")

    def test_ten_protocols(self):
        protocols = [make_proto(name=f"P{i}") for i in range(10)]
        result = analyze(protocols)
        self.assertEqual(len(result["protocols"]), 10)

    def test_score_0_to_100(self):
        # All adversarial combination
        p = make_proto(
            smart_wallet_inflow_30d_usd=0,
            smart_wallet_outflow_30d_usd=0,
            total_tvl_usd=0,
            smart_money_tvl_pct=0,
            days_since_last_large_deposit=999,
            price_correlation_30d=-1.0,
        )
        result = analyze([p])
        score = result["protocols"][0]["composite_bullish_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_missing_optional_fields_handled(self):
        # Minimal dict
        p = {"name": "MinimalProto"}
        result = analyze([p])
        self.assertEqual(len(result["protocols"]), 1)
        self.assertEqual(result["protocols"][0]["name"], "MinimalProto")

    def test_default_config_applied(self):
        p = make_proto(
            smart_wallet_inflow_30d_usd=500_000,
            smart_wallet_outflow_30d_usd=0,
            retail_inflow_30d_usd=400_000,
            retail_outflow_30d_usd=0,
        )
        # Default significance = 1M → both flows < 1M → NEUTRAL
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["divergence_signal"], "NEUTRAL")

    def test_smart_exiting_retail_buying_scenario(self):
        p = make_proto(
            smart_wallet_inflow_30d_usd=0,
            smart_wallet_outflow_30d_usd=5_000_000,
            retail_inflow_30d_usd=3_000_000,
            retail_outflow_30d_usd=0,
        )
        result = analyze([p])
        proto = result["protocols"][0]
        self.assertEqual(proto["divergence_signal"], "SMART_EXITING_RETAIL_BUYING")
        self.assertIn("DIVERGENCE_WARNING", proto["flags"])

    def test_accumulation_very_high_counts(self):
        p = make_proto(
            smart_wallet_inflow_30d_usd=15_000_000,
            smart_wallet_outflow_30d_usd=0,
            total_tvl_usd=100_000_000,
        )
        result = analyze([p])
        self.assertEqual(result["accumulation_count"], 1)
        self.assertEqual(result["protocols"][0]["smart_money_conviction"], "VERY_HIGH")

    def test_full_pipeline_consistent_labels(self):
        """Verify signal_label is consistent with composite_bullish_score."""
        for score, expected in [
            (80, "STRONG_BUY"), (65, "BUY"), (50, "NEUTRAL"),
            (30, "CAUTION"), (10, "SELL"),
        ]:
            self.assertEqual(_signal_label(score), expected)


if __name__ == "__main__":
    unittest.main()
