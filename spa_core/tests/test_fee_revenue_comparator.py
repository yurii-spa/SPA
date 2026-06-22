"""
Tests for MP-800 FeeRevenueComparator
Run: python3 -m unittest spa_core/tests/test_fee_revenue_comparator.py
"""

import json
import math
import os
import sys
import tempfile
import time
import unittest

# Ensure repo root is on path
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.fee_revenue_comparator import (
    analyze,
    save_snapshot,
    load_log,
    _efficiency_grade,
    _atomic_write,
    _sanitise_for_json,
)


# ---------------------------------------------------------------------------
# Sample protocol builder
# ---------------------------------------------------------------------------

def _proto(
    name="TestProto",
    tvl=10_000_000,
    daily_fee=1_000,
    lp_share=80.0,
    proto_share=20.0,
    monthly_exp=5_000,
):
    return {
        "name": name,
        "tvl_usd": tvl,
        "daily_fee_revenue_usd": daily_fee,
        "lp_fee_share_pct": lp_share,
        "protocol_fee_share_pct": proto_share,
        "monthly_expenses_usd": monthly_exp,
    }


def _two_protos():
    return [
        _proto("Alpha", tvl=5_000_000, daily_fee=2_000, lp_share=75.0, proto_share=25.0, monthly_exp=3_000),
        _proto("Beta", tvl=8_000_000, daily_fee=1_000, lp_share=50.0, proto_share=50.0, monthly_exp=1_000),
    ]


# ---------------------------------------------------------------------------
# 1. Return structure
# ---------------------------------------------------------------------------

class TestReturnStructure(unittest.TestCase):

    def setUp(self):
        self.result = analyze([_proto()])

    def test_returns_dict(self):
        self.assertIsInstance(self.result, dict)

    def test_top_level_keys(self):
        for k in ("protocols", "ranking", "most_efficient", "best_lp_yield",
                   "most_sustainable", "market_summary", "timestamp"):
            self.assertIn(k, self.result)

    def test_protocols_is_list(self):
        self.assertIsInstance(self.result["protocols"], list)

    def test_ranking_is_list(self):
        self.assertIsInstance(self.result["ranking"], list)

    def test_most_efficient_is_str(self):
        self.assertIsInstance(self.result["most_efficient"], str)

    def test_best_lp_yield_is_str(self):
        self.assertIsInstance(self.result["best_lp_yield"], str)

    def test_most_sustainable_is_str(self):
        self.assertIsInstance(self.result["most_sustainable"], str)

    def test_market_summary_keys(self):
        ms = self.result["market_summary"]
        for k in ("total_daily_revenue_usd", "total_annualized_revenue_usd",
                   "avg_revenue_to_tvl_pct", "sustainable_protocol_count"):
            self.assertIn(k, ms)

    def test_timestamp_is_float(self):
        self.assertIsInstance(self.result["timestamp"], float)

    def test_timestamp_is_recent(self):
        before = time.time()
        r = analyze([_proto()])
        self.assertGreaterEqual(r["timestamp"], before)

    def test_protocol_row_keys(self):
        row = self.result["protocols"][0]
        for k in ("name", "annualized_revenue_usd", "revenue_to_tvl_pct",
                   "lp_yield_pct", "protocol_revenue_annual_usd",
                   "sustainability_ratio", "efficiency_grade", "is_sustainable"):
            self.assertIn(k, row)


# ---------------------------------------------------------------------------
# 2. Annualized revenue calculation
# ---------------------------------------------------------------------------

class TestAnnualizedRevenue(unittest.TestCase):

    def test_annualized_equals_daily_times_365(self):
        r = analyze([_proto(daily_fee=1_000)])
        self.assertAlmostEqual(r["protocols"][0]["annualized_revenue_usd"], 365_000, places=1)

    def test_zero_daily_fee(self):
        r = analyze([_proto(daily_fee=0)])
        self.assertAlmostEqual(r["protocols"][0]["annualized_revenue_usd"], 0.0, places=4)

    def test_large_daily_fee(self):
        r = analyze([_proto(daily_fee=10_000_000)])
        self.assertAlmostEqual(r["protocols"][0]["annualized_revenue_usd"], 3_650_000_000, places=0)

    def test_total_annualized_sums_all(self):
        protocols = [_proto("A", daily_fee=1_000), _proto("B", daily_fee=2_000)]
        r = analyze(protocols)
        self.assertAlmostEqual(
            r["market_summary"]["total_annualized_revenue_usd"],
            (1_000 + 2_000) * 365,
            places=1,
        )

    def test_total_daily_sums_all(self):
        protocols = [_proto("A", daily_fee=500), _proto("B", daily_fee=1_500)]
        r = analyze(protocols)
        self.assertAlmostEqual(r["market_summary"]["total_daily_revenue_usd"], 2_000, places=2)

    def test_negative_daily_fee_clamped_to_zero(self):
        r = analyze([_proto(daily_fee=-1_000)])
        self.assertAlmostEqual(r["protocols"][0]["annualized_revenue_usd"], 0.0, places=4)


# ---------------------------------------------------------------------------
# 3. Revenue-to-TVL
# ---------------------------------------------------------------------------

class TestRevenueToTVL(unittest.TestCase):

    def test_revenue_to_tvl_correct(self):
        # annualized = 1000*365 = 365_000; tvl = 10_000_000; ratio = 365_000/10_000_000*100 = 3.65%
        r = analyze([_proto(tvl=10_000_000, daily_fee=1_000)])
        self.assertAlmostEqual(r["protocols"][0]["revenue_to_tvl_pct"], 3.65, places=4)

    def test_zero_tvl_gives_zero_ratio(self):
        r = analyze([_proto(tvl=0)])
        self.assertAlmostEqual(r["protocols"][0]["revenue_to_tvl_pct"], 0.0, places=4)

    def test_high_daily_fee_high_ratio(self):
        # annualized = 500*365 = 182_500; tvl = 1_000_000 → ratio = 18.25%
        r = analyze([_proto(tvl=1_000_000, daily_fee=500)])
        self.assertAlmostEqual(r["protocols"][0]["revenue_to_tvl_pct"], 18.25, places=4)

    def test_avg_revenue_to_tvl_is_mean(self):
        protocols = [
            _proto("A", tvl=1_000_000, daily_fee=100),  # annualized 36_500, ratio 3.65%
            _proto("B", tvl=2_000_000, daily_fee=200),  # annualized 73_000, ratio 3.65%
        ]
        r = analyze(protocols)
        self.assertAlmostEqual(r["market_summary"]["avg_revenue_to_tvl_pct"], 3.65, places=3)

    def test_negative_tvl_clamped(self):
        r = analyze([_proto(tvl=-5_000_000)])
        self.assertAlmostEqual(r["protocols"][0]["revenue_to_tvl_pct"], 0.0, places=4)


# ---------------------------------------------------------------------------
# 4. LP yield
# ---------------------------------------------------------------------------

class TestLPYield(unittest.TestCase):

    def test_lp_yield_correct(self):
        # annualized = 1000*365 = 365_000; lp_share=80%; tvl=10M
        # lp_yield = 365_000 * 0.8 / 10_000_000 * 100 = 2.92%
        r = analyze([_proto(tvl=10_000_000, daily_fee=1_000, lp_share=80.0)])
        self.assertAlmostEqual(r["protocols"][0]["lp_yield_pct"], 2.92, places=3)

    def test_zero_tvl_gives_zero_lp_yield(self):
        r = analyze([_proto(tvl=0)])
        self.assertAlmostEqual(r["protocols"][0]["lp_yield_pct"], 0.0, places=4)

    def test_100_pct_lp_share_equals_revenue_to_tvl(self):
        r = analyze([_proto(tvl=10_000_000, daily_fee=1_000, lp_share=100.0)])
        self.assertAlmostEqual(
            r["protocols"][0]["lp_yield_pct"],
            r["protocols"][0]["revenue_to_tvl_pct"],
            places=4,
        )

    def test_zero_lp_share_gives_zero_lp_yield(self):
        r = analyze([_proto(lp_share=0.0)])
        self.assertAlmostEqual(r["protocols"][0]["lp_yield_pct"], 0.0, places=4)

    def test_lp_share_capped_at_100(self):
        r = analyze([_proto(lp_share=200.0, tvl=1_000_000, daily_fee=100)])
        expected = 100 * 365 / 1_000_000 * 100  # as if 100% LP share
        self.assertAlmostEqual(r["protocols"][0]["lp_yield_pct"], expected, places=4)


# ---------------------------------------------------------------------------
# 5. Protocol revenue and sustainability
# ---------------------------------------------------------------------------

class TestSustainability(unittest.TestCase):

    def test_protocol_revenue_correct(self):
        # annualized=365_000; proto_share=20% → proto_rev=73_000
        r = analyze([_proto(daily_fee=1_000, proto_share=20.0)])
        self.assertAlmostEqual(r["protocols"][0]["protocol_revenue_annual_usd"], 73_000, places=1)

    def test_sustainability_ratio_correct(self):
        # proto_rev=73_000; annual_exp=12*5000=60_000; ratio=73000/60000=1.2167
        r = analyze([_proto(daily_fee=1_000, proto_share=20.0, monthly_exp=5_000)])
        self.assertAlmostEqual(r["protocols"][0]["sustainability_ratio"], 73_000 / 60_000, places=4)

    def test_is_sustainable_true_when_ratio_ge_1(self):
        r = analyze([_proto(daily_fee=1_000, proto_share=20.0, monthly_exp=5_000)])
        self.assertTrue(r["protocols"][0]["is_sustainable"])

    def test_is_sustainable_false_when_ratio_lt_1(self):
        # proto_rev=73_000; monthly_exp=10_000 → annual=120_000; ratio=0.608
        r = analyze([_proto(daily_fee=1_000, proto_share=20.0, monthly_exp=10_000)])
        self.assertFalse(r["protocols"][0]["is_sustainable"])

    def test_zero_expenses_gives_infinite_sustainability(self):
        r = analyze([_proto(monthly_exp=0, proto_share=50.0, daily_fee=1_000)])
        self.assertTrue(math.isinf(r["protocols"][0]["sustainability_ratio"]))

    def test_zero_expenses_is_sustainable(self):
        r = analyze([_proto(monthly_exp=0, proto_share=50.0)])
        self.assertTrue(r["protocols"][0]["is_sustainable"])

    def test_zero_proto_share_zero_proto_revenue(self):
        r = analyze([_proto(proto_share=0.0)])
        self.assertAlmostEqual(r["protocols"][0]["protocol_revenue_annual_usd"], 0.0, places=4)

    def test_zero_proto_share_not_sustainable_with_expenses(self):
        r = analyze([_proto(proto_share=0.0, monthly_exp=1_000)])
        self.assertFalse(r["protocols"][0]["is_sustainable"])

    def test_sustainable_count_correct(self):
        # Alpha: ratio=73000/36000=2.03 → sustainable
        # Beta: ratio=0/(12000) = 0 → not sustainable
        protocols = [
            _proto("Alpha", daily_fee=1_000, proto_share=20.0, monthly_exp=3_000),
            _proto("Beta", daily_fee=0, proto_share=20.0, monthly_exp=1_000),
        ]
        r = analyze(protocols)
        self.assertEqual(r["market_summary"]["sustainable_protocol_count"], 1)

    def test_sustainability_ratio_exactly_1_is_sustainable(self):
        # ratio = 1.0 exactly → is_sustainable=True
        # proto_rev = daily*365*proto_share/100 ; annual_exp = monthly*12
        # want proto_rev = annual_exp
        # daily=1000, proto_share=100% → proto_rev=365_000; monthly_exp=365_000/12
        monthly = 365_000 / 12.0
        r = analyze([_proto(daily_fee=1_000, proto_share=100.0, monthly_exp=monthly)])
        self.assertAlmostEqual(r["protocols"][0]["sustainability_ratio"], 1.0, places=4)
        self.assertTrue(r["protocols"][0]["is_sustainable"])


# ---------------------------------------------------------------------------
# 6. Efficiency grade
# ---------------------------------------------------------------------------

class TestEfficiencyGrade(unittest.TestCase):

    def test_grade_a_at_5_pct(self):
        self.assertEqual(_efficiency_grade(5.0), "A")

    def test_grade_a_above_5_pct(self):
        self.assertEqual(_efficiency_grade(10.0), "A")

    def test_grade_b_at_2_pct(self):
        self.assertEqual(_efficiency_grade(2.0), "B")

    def test_grade_b_below_5_pct(self):
        self.assertEqual(_efficiency_grade(4.9), "B")

    def test_grade_c_at_1_pct(self):
        self.assertEqual(_efficiency_grade(1.0), "C")

    def test_grade_c_below_2_pct(self):
        self.assertEqual(_efficiency_grade(1.5), "C")

    def test_grade_d_at_0_5_pct(self):
        self.assertEqual(_efficiency_grade(0.5), "D")

    def test_grade_d_below_1_pct(self):
        self.assertEqual(_efficiency_grade(0.9), "D")

    def test_grade_f_at_zero(self):
        self.assertEqual(_efficiency_grade(0.0), "F")

    def test_grade_f_below_0_5_pct(self):
        self.assertEqual(_efficiency_grade(0.49), "F")

    def test_grade_assigned_in_protocol_row(self):
        # 3.65% → grade B
        r = analyze([_proto(tvl=10_000_000, daily_fee=1_000)])
        self.assertEqual(r["protocols"][0]["efficiency_grade"], "B")

    def test_grade_a_in_row(self):
        # annualized = 100*365=36500; tvl=200_000 → 18.25% → A
        r = analyze([_proto(tvl=200_000, daily_fee=100)])
        self.assertEqual(r["protocols"][0]["efficiency_grade"], "A")

    def test_grade_f_zero_daily(self):
        r = analyze([_proto(daily_fee=0)])
        self.assertEqual(r["protocols"][0]["efficiency_grade"], "F")


# ---------------------------------------------------------------------------
# 7. Ranking
# ---------------------------------------------------------------------------

class TestRanking(unittest.TestCase):

    def test_ranking_sorted_by_revenue_to_tvl_desc(self):
        # Alpha: 100*365/1_000_000*100 = 3.65%; Beta: 10*365/100_000*100 = 3.65% equal
        # Let's make them unequal:
        # Alpha: 200*365/1_000_000*100 = 7.3%; Beta: 100*365/5_000_000*100 = 0.73%
        protocols = [
            _proto("Alpha", tvl=1_000_000, daily_fee=200),
            _proto("Beta", tvl=5_000_000, daily_fee=100),
        ]
        r = analyze(protocols)
        self.assertEqual(r["ranking"][0], "Alpha")
        self.assertEqual(r["ranking"][1], "Beta")

    def test_ranking_length_matches_protocols(self):
        protocols = [_proto(str(i)) for i in range(5)]
        r = analyze(protocols)
        self.assertEqual(len(r["ranking"]), 5)

    def test_ranking_contains_all_names(self):
        protocols = [_proto("X"), _proto("Y"), _proto("Z")]
        r = analyze(protocols)
        self.assertIn("X", r["ranking"])
        self.assertIn("Y", r["ranking"])
        self.assertIn("Z", r["ranking"])

    def test_single_protocol_ranking(self):
        r = analyze([_proto("Solo")])
        self.assertEqual(r["ranking"], ["Solo"])
        self.assertEqual(r["most_efficient"], "Solo")
        self.assertEqual(r["best_lp_yield"], "Solo")
        self.assertEqual(r["most_sustainable"], "Solo")

    def test_most_efficient_is_first_in_ranking(self):
        protocols = _two_protos()
        r = analyze(protocols)
        self.assertEqual(r["most_efficient"], r["ranking"][0])


# ---------------------------------------------------------------------------
# 8. most_efficient / best_lp_yield / most_sustainable
# ---------------------------------------------------------------------------

class TestLeaders(unittest.TestCase):

    def setUp(self):
        # A: high revenue/tvl, moderate lp
        # B: lower revenue/tvl, high lp share
        # C: high sustainability
        self.protocols = [
            _proto("A", tvl=500_000, daily_fee=200, lp_share=30.0, proto_share=70.0, monthly_exp=100),
            _proto("B", tvl=2_000_000, daily_fee=100, lp_share=95.0, proto_share=5.0, monthly_exp=1_000),
            _proto("C", tvl=10_000_000, daily_fee=50, lp_share=50.0, proto_share=50.0, monthly_exp=50),
        ]

    def test_most_efficient_is_highest_revenue_to_tvl(self):
        r = analyze(self.protocols)
        rows = {x["name"]: x for x in r["protocols"]}
        # Verify most_efficient has the highest rev_to_tvl
        best = max(rows.values(), key=lambda x: x["revenue_to_tvl_pct"])
        self.assertEqual(r["most_efficient"], best["name"])

    def test_best_lp_yield_has_highest_lp_yield(self):
        r = analyze(self.protocols)
        rows = {x["name"]: x for x in r["protocols"]}
        best_lp = max(rows.values(), key=lambda x: x["lp_yield_pct"])
        self.assertEqual(r["best_lp_yield"], best_lp["name"])

    def test_most_sustainable_has_highest_ratio(self):
        r = analyze(self.protocols)
        rows = {x["name"]: x for x in r["protocols"]}
        def sust_val(row):
            s = row["sustainability_ratio"]
            return s if not math.isinf(s) else 1e300
        best_s = max(rows.values(), key=sust_val)
        self.assertEqual(r["most_sustainable"], best_s["name"])

    def test_infinite_sustainability_wins(self):
        protocols = [
            _proto("HighRatio", proto_share=100.0, daily_fee=1_000, monthly_exp=1),
            _proto("InfRatio", proto_share=100.0, daily_fee=1_000, monthly_exp=0),
        ]
        r = analyze(protocols)
        self.assertEqual(r["most_sustainable"], "InfRatio")


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_empty_list_returns_empty_protocols(self):
        r = analyze([])
        self.assertEqual(r["protocols"], [])
        self.assertEqual(r["ranking"], [])
        self.assertEqual(r["most_efficient"], "")
        self.assertEqual(r["best_lp_yield"], "")
        self.assertEqual(r["most_sustainable"], "")

    def test_empty_market_summary_zeros(self):
        r = analyze([])
        ms = r["market_summary"]
        self.assertAlmostEqual(ms["total_daily_revenue_usd"], 0.0, places=4)
        self.assertAlmostEqual(ms["total_annualized_revenue_usd"], 0.0, places=4)
        self.assertAlmostEqual(ms["avg_revenue_to_tvl_pct"], 0.0, places=4)
        self.assertEqual(ms["sustainable_protocol_count"], 0)

    def test_none_config_uses_defaults(self):
        r = analyze([_proto()], config=None)
        self.assertIn("protocols", r)

    def test_empty_config_uses_defaults(self):
        r = analyze([_proto()], config={})
        self.assertIn("protocols", r)

    def test_missing_name_defaults_to_empty_string(self):
        r = analyze([{"tvl_usd": 1_000_000, "daily_fee_revenue_usd": 100,
                      "lp_fee_share_pct": 50, "protocol_fee_share_pct": 50,
                      "monthly_expenses_usd": 1_000}])
        self.assertEqual(r["protocols"][0]["name"], "")

    def test_missing_fields_default_to_zero(self):
        r = analyze([{"name": "Minimal"}])
        row = r["protocols"][0]
        self.assertAlmostEqual(row["annualized_revenue_usd"], 0.0, places=4)
        self.assertAlmostEqual(row["revenue_to_tvl_pct"], 0.0, places=4)

    def test_lp_share_over_100_clamped(self):
        r = analyze([_proto(lp_share=150.0, tvl=1_000_000, daily_fee=100)])
        row = r["protocols"][0]
        # should be same as 100%
        expected = 100 * 365 / 1_000_000 * 100
        self.assertAlmostEqual(row["lp_yield_pct"], expected, places=4)

    def test_protocol_share_over_100_clamped(self):
        r = analyze([_proto(proto_share=150.0, daily_fee=100, monthly_exp=1)])
        row = r["protocols"][0]
        # capped at 100%
        expected = 100 * 365 * 1.0  # = 36_500
        self.assertAlmostEqual(row["protocol_revenue_annual_usd"], expected, places=1)

    def test_all_zeros(self):
        r = analyze([_proto(tvl=0, daily_fee=0, lp_share=0, proto_share=0, monthly_exp=0)])
        row = r["protocols"][0]
        self.assertAlmostEqual(row["revenue_to_tvl_pct"], 0.0, places=4)
        self.assertAlmostEqual(row["lp_yield_pct"], 0.0, places=4)
        # proto_rev = 0, expenses = 0 → inf sustainability
        self.assertTrue(math.isinf(row["sustainability_ratio"]))


# ---------------------------------------------------------------------------
# 10. Market summary
# ---------------------------------------------------------------------------

class TestMarketSummary(unittest.TestCase):

    def test_sustainable_count_all_sustainable(self):
        protocols = [
            _proto("A", daily_fee=10_000, proto_share=50.0, monthly_exp=1),
            _proto("B", daily_fee=10_000, proto_share=50.0, monthly_exp=1),
        ]
        r = analyze(protocols)
        self.assertEqual(r["market_summary"]["sustainable_protocol_count"], 2)

    def test_sustainable_count_none_sustainable(self):
        protocols = [
            _proto("A", daily_fee=0, proto_share=100.0, monthly_exp=10_000),
            _proto("B", daily_fee=0, proto_share=100.0, monthly_exp=5_000),
        ]
        r = analyze(protocols)
        self.assertEqual(r["market_summary"]["sustainable_protocol_count"], 0)

    def test_avg_revenue_to_tvl_single(self):
        r = analyze([_proto(tvl=10_000_000, daily_fee=1_000)])
        self.assertAlmostEqual(r["market_summary"]["avg_revenue_to_tvl_pct"], 3.65, places=3)

    def test_total_annualized_matches_sum(self):
        protocols = [_proto("A", daily_fee=500), _proto("B", daily_fee=700)]
        r = analyze(protocols)
        self.assertAlmostEqual(
            r["market_summary"]["total_annualized_revenue_usd"],
            (500 + 700) * 365,
            places=1,
        )


# ---------------------------------------------------------------------------
# 11. Sanitise for JSON
# ---------------------------------------------------------------------------

class TestSanitise(unittest.TestCase):

    def test_inf_becomes_string(self):
        result = _sanitise_for_json({"ratio": math.inf})
        self.assertEqual(result["ratio"], "Infinity")

    def test_neg_inf_becomes_string(self):
        result = _sanitise_for_json({"ratio": -math.inf})
        self.assertEqual(result["ratio"], "-Infinity")

    def test_nan_becomes_string(self):
        result = _sanitise_for_json({"v": float("nan")})
        self.assertEqual(result["v"], "NaN")

    def test_normal_float_unchanged(self):
        result = _sanitise_for_json({"v": 3.14})
        self.assertAlmostEqual(result["v"], 3.14, places=5)

    def test_list_sanitised(self):
        result = _sanitise_for_json([math.inf, 1.0])
        self.assertEqual(result[0], "Infinity")
        self.assertAlmostEqual(result[1], 1.0, places=5)

    def test_nested_sanitised(self):
        result = _sanitise_for_json({"a": {"b": math.inf}})
        self.assertEqual(result["a"]["b"], "Infinity")


# ---------------------------------------------------------------------------
# 12. Persistence
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.write(b"[]")
        self.tmp.close()
        self.log_path = self.tmp.name

    def tearDown(self):
        os.unlink(self.log_path)

    def test_save_creates_entry(self):
        result = analyze([_proto()])
        save_snapshot(result, self.log_path)
        log = load_log(self.log_path)
        self.assertEqual(len(log), 1)

    def test_load_returns_list(self):
        log = load_log(self.log_path)
        self.assertIsInstance(log, list)

    def test_multiple_saves_accumulate(self):
        result = analyze([_proto()])
        for _ in range(3):
            save_snapshot(result, self.log_path)
        log = load_log(self.log_path)
        self.assertEqual(len(log), 3)

    def test_ring_buffer_caps_at_100(self):
        result = analyze([_proto()])
        for _ in range(105):
            save_snapshot(result, self.log_path)
        log = load_log(self.log_path)
        self.assertEqual(len(log), 100)

    def test_ring_buffer_keeps_last_100(self):
        for i in range(105):
            result = analyze([_proto(daily_fee=float(i) + 1)])
            save_snapshot(result, self.log_path)
        log = load_log(self.log_path)
        self.assertEqual(len(log), 100)

    def test_nonexistent_log_returns_empty(self):
        log = load_log("/tmp/_nonexistent_spa_fee_test_xyz.json")
        self.assertEqual(log, [])

    def test_save_content_has_market_summary(self):
        result = analyze([_proto()])
        save_snapshot(result, self.log_path)
        log = load_log(self.log_path)
        self.assertIn("market_summary", log[0])

    def test_inf_serialised_safely(self):
        # zero expenses → inf sustainability → must not raise on save
        result = analyze([_proto(monthly_exp=0)])
        save_snapshot(result, self.log_path)
        log = load_log(self.log_path)
        self.assertEqual(len(log), 1)

    def test_atomic_write_valid_json(self):
        data = [{"x": 1}, {"y": 2}]
        _atomic_write(self.log_path, data)
        with open(self.log_path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_load_corrupted_file_returns_empty(self):
        with open(self.log_path, "w") as f:
            f.write("not valid {{")
        log = load_log(self.log_path)
        self.assertEqual(log, [])

    def test_load_non_list_json_returns_empty(self):
        with open(self.log_path, "w") as f:
            json.dump({"key": "val"}, f)
        log = load_log(self.log_path)
        self.assertEqual(log, [])


# ---------------------------------------------------------------------------
# 13. Realistic scenario
# ---------------------------------------------------------------------------

class TestRealisticScenario(unittest.TestCase):
    """Sanity checks on a realistic multi-protocol dataset."""

    def setUp(self):
        self.protocols = [
            {
                "name": "Uniswap V3",
                "tvl_usd": 5_000_000_000,
                "daily_fee_revenue_usd": 1_500_000,
                "lp_fee_share_pct": 100.0,
                "protocol_fee_share_pct": 0.0,
                "monthly_expenses_usd": 500_000,
            },
            {
                "name": "Aave V3",
                "tvl_usd": 10_000_000_000,
                "daily_fee_revenue_usd": 800_000,
                "lp_fee_share_pct": 90.0,
                "protocol_fee_share_pct": 10.0,
                "monthly_expenses_usd": 2_000_000,
            },
            {
                "name": "Curve",
                "tvl_usd": 2_000_000_000,
                "daily_fee_revenue_usd": 200_000,
                "lp_fee_share_pct": 50.0,
                "protocol_fee_share_pct": 50.0,
                "monthly_expenses_usd": 300_000,
            },
        ]
        self.r = analyze(self.protocols)

    def test_three_protocols_in_result(self):
        self.assertEqual(len(self.r["protocols"]), 3)

    def test_three_in_ranking(self):
        self.assertEqual(len(self.r["ranking"]), 3)

    def test_uniswap_sustainable_with_zero_proto_share(self):
        # protocol_fee_share=0 → proto_rev=0; expenses=6M; ratio=0 → NOT sustainable
        rows = {x["name"]: x for x in self.r["protocols"]}
        self.assertFalse(rows["Uniswap V3"]["is_sustainable"])

    def test_aave_sustainability(self):
        # proto_rev = 800_000*365*0.1 = 29_200_000; annual_exp=24_000_000; ratio=1.217
        rows = {x["name"]: x for x in self.r["protocols"]}
        self.assertAlmostEqual(rows["Aave V3"]["sustainability_ratio"],
                               800_000 * 365 * 0.1 / (2_000_000 * 12), places=3)

    def test_total_daily_correct(self):
        self.assertAlmostEqual(
            self.r["market_summary"]["total_daily_revenue_usd"],
            1_500_000 + 800_000 + 200_000,
            places=1,
        )

    def test_uniswap_lp_yield_highest_lp_share(self):
        rows = {x["name"]: x for x in self.r["protocols"]}
        # Uniswap: 100% LP share on 1.5M/5B TVL
        expected = 1_500_000 * 365 / 5_000_000_000 * 100
        self.assertAlmostEqual(rows["Uniswap V3"]["lp_yield_pct"], expected, places=4)


if __name__ == "__main__":
    unittest.main()
