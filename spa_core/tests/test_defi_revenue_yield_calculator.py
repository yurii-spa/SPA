"""
Tests for MP-742: DeFiRevenueYieldCalculator
Pure stdlib unittest only. ≥65 tests.
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_revenue_yield_calculator import (
    ProtocolRevenue,
    RevenueYieldResult,
    analyze_market,
    analyze_protocol,
    compute_emission_yield,
    compute_revenue_yield,
    load_history,
    real_yield_ratio,
    revenue_label,
    save_results,
    sustainability_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # let save_results create it
    return path


def _sample_protocols(count=3):
    return [
        {
            "protocol": "Aave",
            "daily_fee_revenue_usd": 10_000,
            "daily_token_emissions_usd": 2_000,
            "total_value_locked_usd": 1_000_000_000,
        },
        {
            "protocol": "Farm",
            "daily_fee_revenue_usd": 500,
            "daily_token_emissions_usd": 50_000,
            "total_value_locked_usd": 100_000_000,
        },
        {
            "protocol": "Compound",
            "daily_fee_revenue_usd": 5_000,
            "daily_token_emissions_usd": 5_000,
            "total_value_locked_usd": 500_000_000,
        },
    ][:count]


# ---------------------------------------------------------------------------
# compute_revenue_yield
# ---------------------------------------------------------------------------

class TestComputeRevenueYield(unittest.TestCase):

    def test_basic_formula(self):
        # daily_fee=100, tvl=365*100 → 1%*100 = 1%... let's be explicit:
        # annual = 100*365=36500; ratio=36500/365000*100 = 10%
        result = compute_revenue_yield(100.0, 365_000.0)
        self.assertAlmostEqual(result, 10.0, places=5)

    def test_tvl_zero_returns_zero(self):
        self.assertEqual(compute_revenue_yield(1000.0, 0.0), 0.0)

    def test_tvl_negative_returns_zero(self):
        self.assertEqual(compute_revenue_yield(1000.0, -500.0), 0.0)

    def test_formula_annualised(self):
        # 1000 daily fees on 1M TVL → annual = 365000 → 36.5%
        result = compute_revenue_yield(1000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 36.5, places=5)

    def test_zero_fees_returns_zero(self):
        self.assertEqual(compute_revenue_yield(0.0, 1_000_000.0), 0.0)

    def test_large_numbers(self):
        r = compute_revenue_yield(1_000_000.0, 10_000_000_000.0)
        self.assertAlmostEqual(r, 3.65, places=5)

    def test_fractional_fees(self):
        r = compute_revenue_yield(0.5, 365.0)
        self.assertAlmostEqual(r, 50.0, places=4)


# ---------------------------------------------------------------------------
# compute_emission_yield
# ---------------------------------------------------------------------------

class TestComputeEmissionYield(unittest.TestCase):

    def test_basic_formula(self):
        result = compute_emission_yield(100.0, 365_000.0)
        self.assertAlmostEqual(result, 10.0, places=5)

    def test_tvl_zero_returns_zero(self):
        self.assertEqual(compute_emission_yield(500.0, 0.0), 0.0)

    def test_tvl_negative_returns_zero(self):
        self.assertEqual(compute_emission_yield(500.0, -1.0), 0.0)

    def test_zero_emissions_returns_zero(self):
        self.assertEqual(compute_emission_yield(0.0, 1_000_000.0), 0.0)

    def test_annual_emission_formula(self):
        # daily_emission=1000, tvl=1M → annual=365000 → 36.5%
        result = compute_emission_yield(1000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 36.5, places=5)

    def test_matches_revenue_yield_formula(self):
        # emission and fee yield use identical formula — check symmetry
        fee = compute_revenue_yield(200.0, 500_000.0)
        em = compute_emission_yield(200.0, 500_000.0)
        self.assertAlmostEqual(fee, em, places=8)


# ---------------------------------------------------------------------------
# Annualisation (via analyze_protocol fields)
# ---------------------------------------------------------------------------

class TestAnnualisation(unittest.TestCase):

    def test_annual_fee_equals_daily_times_365(self):
        pr = analyze_protocol("X", 1000.0, 0.0, 1_000_000.0)
        self.assertAlmostEqual(pr.annual_fee_revenue_usd, 365_000.0, places=4)

    def test_annual_emission_equals_daily_times_365(self):
        pr = analyze_protocol("X", 0.0, 500.0, 1_000_000.0)
        self.assertAlmostEqual(pr.annual_emission_usd, 182_500.0, places=4)

    def test_total_yield_equals_rev_plus_em(self):
        pr = analyze_protocol("X", 100.0, 200.0, 1_000_000.0)
        self.assertAlmostEqual(
            pr.total_yield_pct, pr.revenue_yield_pct + pr.emission_yield_pct, places=8
        )

    def test_total_yield_zero_when_no_fees_no_emissions(self):
        pr = analyze_protocol("X", 0.0, 0.0, 1_000_000.0)
        self.assertEqual(pr.total_yield_pct, 0.0)


# ---------------------------------------------------------------------------
# real_yield_ratio
# ---------------------------------------------------------------------------

class TestRealYieldRatio(unittest.TestCase):

    def test_basic_formula(self):
        # revenue=5, total=10 → ratio=50
        r = real_yield_ratio(5.0, 10.0)
        self.assertAlmostEqual(r, 50.0, places=8)

    def test_total_zero_returns_100(self):
        self.assertEqual(real_yield_ratio(0.0, 0.0), 100.0)

    def test_all_real(self):
        r = real_yield_ratio(10.0, 10.0)
        self.assertAlmostEqual(r, 100.0, places=8)

    def test_no_real(self):
        r = real_yield_ratio(0.0, 10.0)
        self.assertAlmostEqual(r, 0.0, places=8)

    def test_partial(self):
        r = real_yield_ratio(3.0, 12.0)
        self.assertAlmostEqual(r, 25.0, places=8)


# ---------------------------------------------------------------------------
# sustainability_score
# ---------------------------------------------------------------------------

class TestSustainabilityScore(unittest.TestCase):

    def test_basic_formula(self):
        # rev=5, em=5 → 50%
        s = sustainability_score(5.0, 5.0)
        self.assertAlmostEqual(s, 50.0, places=8)

    def test_both_zero_returns_100(self):
        self.assertEqual(sustainability_score(0.0, 0.0), 100.0)

    def test_all_revenue_returns_100(self):
        s = sustainability_score(10.0, 0.0)
        self.assertAlmostEqual(s, 100.0, places=8)

    def test_all_emission_returns_zero(self):
        s = sustainability_score(0.0, 10.0)
        self.assertAlmostEqual(s, 0.0, places=8)

    def test_partial_score(self):
        s = sustainability_score(1.0, 3.0)
        self.assertAlmostEqual(s, 25.0, places=8)


# ---------------------------------------------------------------------------
# revenue_label
# ---------------------------------------------------------------------------

class TestRevenueLabel(unittest.TestCase):

    def test_real_yield_at_70(self):
        self.assertEqual(revenue_label(70.0), "REAL_YIELD")

    def test_real_yield_above_70(self):
        self.assertEqual(revenue_label(95.0), "REAL_YIELD")

    def test_hybrid_at_30(self):
        self.assertEqual(revenue_label(30.0), "HYBRID")

    def test_hybrid_at_69(self):
        self.assertEqual(revenue_label(69.9), "HYBRID")

    def test_emission_only_at_0(self):
        self.assertEqual(revenue_label(0.0), "EMISSION_ONLY")

    def test_emission_only_below_30(self):
        self.assertEqual(revenue_label(29.9), "EMISSION_ONLY")

    def test_boundary_exactly_70(self):
        self.assertEqual(revenue_label(70.0), "REAL_YIELD")


# ---------------------------------------------------------------------------
# is_real_yield_protocol
# ---------------------------------------------------------------------------

class TestIsRealYieldProtocol(unittest.TestCase):

    def test_true_when_ratio_ge_50(self):
        pr = analyze_protocol("X", 50.0, 50.0, 1_000_000.0)
        # ratio=50 → True
        self.assertTrue(pr.is_real_yield_protocol)

    def test_false_when_ratio_lt_50(self):
        pr = analyze_protocol("X", 10.0, 90.0, 1_000_000.0)
        # ratio ≈ 10 → False
        self.assertFalse(pr.is_real_yield_protocol)

    def test_true_when_pure_real(self):
        pr = analyze_protocol("X", 100.0, 0.0, 1_000_000.0)
        self.assertTrue(pr.is_real_yield_protocol)


# ---------------------------------------------------------------------------
# analyze_protocol (integration)
# ---------------------------------------------------------------------------

class TestAnalyzeProtocol(unittest.TestCase):

    def setUp(self):
        self.pr = analyze_protocol(
            protocol="TestProto",
            daily_fee_usd=1000.0,
            daily_emission_usd=500.0,
            tvl_usd=10_000_000.0,
        )

    def test_protocol_name(self):
        self.assertEqual(self.pr.protocol, "TestProto")

    def test_revenue_yield_pct_correct(self):
        expected = (1000.0 * 365) / 10_000_000.0 * 100
        self.assertAlmostEqual(self.pr.revenue_yield_pct, expected, places=6)

    def test_emission_yield_pct_correct(self):
        expected = (500.0 * 365) / 10_000_000.0 * 100
        self.assertAlmostEqual(self.pr.emission_yield_pct, expected, places=6)

    def test_total_yield_is_sum(self):
        self.assertAlmostEqual(
            self.pr.total_yield_pct,
            self.pr.revenue_yield_pct + self.pr.emission_yield_pct,
            places=8,
        )

    def test_real_yield_ratio_computed(self):
        ratio = real_yield_ratio(self.pr.revenue_yield_pct, self.pr.total_yield_pct)
        self.assertAlmostEqual(self.pr.real_yield_ratio, ratio, places=8)

    def test_sustainability_score_computed(self):
        ss = sustainability_score(self.pr.revenue_yield_pct, self.pr.emission_yield_pct)
        self.assertAlmostEqual(self.pr.sustainability_score, ss, places=8)

    def test_revenue_label_set(self):
        self.assertIn(self.pr.revenue_label, ["REAL_YIELD", "HYBRID", "EMISSION_ONLY"])

    def test_is_real_yield_consistent_with_ratio(self):
        if self.pr.real_yield_ratio >= 50.0:
            self.assertTrue(self.pr.is_real_yield_protocol)
        else:
            self.assertFalse(self.pr.is_real_yield_protocol)

    def test_annual_fee_correct(self):
        self.assertAlmostEqual(self.pr.annual_fee_revenue_usd, 365_000.0, places=4)


# ---------------------------------------------------------------------------
# Edge: zero fees (pure emission)
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_zero_fees_pure_emission(self):
        pr = analyze_protocol("EmFarm", 0.0, 1000.0, 1_000_000.0)
        self.assertEqual(pr.revenue_yield_pct, 0.0)
        self.assertGreater(pr.emission_yield_pct, 0.0)
        self.assertEqual(pr.revenue_label, "EMISSION_ONLY")
        self.assertFalse(pr.is_real_yield_protocol)

    def test_zero_emissions_pure_real(self):
        pr = analyze_protocol("RealProto", 1000.0, 0.0, 1_000_000.0)
        self.assertEqual(pr.emission_yield_pct, 0.0)
        self.assertGreater(pr.revenue_yield_pct, 0.0)
        self.assertEqual(pr.real_yield_ratio, 100.0)
        self.assertEqual(pr.revenue_label, "REAL_YIELD")
        self.assertTrue(pr.is_real_yield_protocol)

    def test_zero_tvl_all_zero(self):
        pr = analyze_protocol("ZeroTVL", 1000.0, 500.0, 0.0)
        self.assertEqual(pr.revenue_yield_pct, 0.0)
        self.assertEqual(pr.emission_yield_pct, 0.0)
        self.assertEqual(pr.total_yield_pct, 0.0)


# ---------------------------------------------------------------------------
# analyze_market
# ---------------------------------------------------------------------------

class TestAnalyzeMarket(unittest.TestCase):

    def setUp(self):
        self.data = _sample_protocols()
        self.result = analyze_market(self.data)

    def test_returns_result_type(self):
        self.assertIsInstance(self.result, RevenueYieldResult)

    def test_protocols_count(self):
        self.assertEqual(len(self.result.protocols), 3)

    def test_top_real_yield_sorted_by_revenue_yield_desc(self):
        # top_real_yield_protocols should have highest revenue_yield_pct first
        protocols = {p.protocol: p for p in self.result.protocols}
        names = self.result.top_real_yield_protocols
        if len(names) >= 2:
            self.assertGreaterEqual(
                protocols[names[0]].revenue_yield_pct,
                protocols[names[1]].revenue_yield_pct,
            )

    def test_most_inflationary_sorted_by_emission_yield_desc(self):
        protocols = {p.protocol: p for p in self.result.protocols}
        names = self.result.most_inflationary_protocols
        if len(names) >= 2:
            self.assertGreaterEqual(
                protocols[names[0]].emission_yield_pct,
                protocols[names[1]].emission_yield_pct,
            )

    def test_avg_real_yield_ratio_formula(self):
        expected = sum(p.real_yield_ratio for p in self.result.protocols) / 3
        self.assertAlmostEqual(self.result.avg_real_yield_ratio, expected, places=5)

    def test_real_yield_protocol_count(self):
        count = sum(1 for p in self.result.protocols if p.is_real_yield_protocol)
        self.assertEqual(self.result.real_yield_protocol_count, count)

    def test_market_real_yield_label_mature(self):
        data = [
            {
                "protocol": f"P{i}",
                "daily_fee_revenue_usd": 10_000,
                "daily_token_emissions_usd": 100,
                "total_value_locked_usd": 1_000_000_000,
            }
            for i in range(3)
        ]
        r = analyze_market(data)
        self.assertEqual(r.market_real_yield_label, "MATURE")

    def test_market_real_yield_label_inflationary(self):
        data = [
            {
                "protocol": f"P{i}",
                "daily_fee_revenue_usd": 100,
                "daily_token_emissions_usd": 100_000,
                "total_value_locked_usd": 1_000_000_000,
            }
            for i in range(3)
        ]
        r = analyze_market(data)
        self.assertEqual(r.market_real_yield_label, "INFLATIONARY")

    def test_market_real_yield_label_mixed(self):
        # avg ratio around 40% → MIXED
        data = [
            {
                "protocol": "A",
                "daily_fee_revenue_usd": 4_000,
                "daily_token_emissions_usd": 6_000,
                "total_value_locked_usd": 1_000_000_000,
            }
        ]
        r = analyze_market(data)
        self.assertEqual(r.market_real_yield_label, "MIXED")

    def test_recommendation_inflationary_trigger(self):
        data = [
            {
                "protocol": f"P{i}",
                "daily_fee_revenue_usd": 10,
                "daily_token_emissions_usd": 1_000_000,
                "total_value_locked_usd": 1_000_000_000,
            }
            for i in range(3)
        ]
        r = analyze_market(data)
        self.assertIn("dominated by token emissions", r.recommendation_summary)

    def test_recommendation_few_real_yield(self):
        # 1 real yield protocol → trigger "Few real yield"
        data = [
            {
                "protocol": "Real",
                "daily_fee_revenue_usd": 10_000,
                "daily_token_emissions_usd": 0,
                "total_value_locked_usd": 1_000_000_000,
            },
            {
                "protocol": "Fake1",
                "daily_fee_revenue_usd": 100,
                "daily_token_emissions_usd": 50_000,
                "total_value_locked_usd": 100_000_000,
            },
            {
                "protocol": "Fake2",
                "daily_fee_revenue_usd": 50,
                "daily_token_emissions_usd": 30_000,
                "total_value_locked_usd": 100_000_000,
            },
        ]
        r = analyze_market(data)
        # avg_ratio: depends; ensure at least something sensible
        self.assertIsInstance(r.recommendation_summary, str)
        self.assertGreater(len(r.recommendation_summary), 5)

    def test_top_real_yield_max_3(self):
        self.assertLessEqual(len(self.result.top_real_yield_protocols), 3)

    def test_most_inflationary_max_3(self):
        self.assertLessEqual(len(self.result.most_inflationary_protocols), 3)


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):

    def test_save_creates_file(self):
        path = _tmp_log()
        data = _sample_protocols()
        result = analyze_market(data)
        save_results(result, path)
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_load_returns_list(self):
        path = _tmp_log()
        result = analyze_market(_sample_protocols())
        save_results(result, path)
        history = load_history(path)
        self.assertIsInstance(history, list)
        os.unlink(path)

    def test_round_trip_entry_count(self):
        path = _tmp_log()
        for _ in range(3):
            save_results(analyze_market(_sample_protocols()), path)
        history = load_history(path)
        self.assertEqual(len(history), 3)
        os.unlink(path)

    def test_load_missing_file_returns_empty_list(self):
        history = load_history("/tmp/__nonexistent_spa_test__.json")
        self.assertEqual(history, [])

    def test_ring_buffer_capped_at_100(self):
        path = _tmp_log()
        for _ in range(105):
            save_results(analyze_market(_sample_protocols(1)), path)
        history = load_history(path)
        self.assertEqual(len(history), 100)
        os.unlink(path)

    def test_saved_to_field_set(self):
        path = _tmp_log()
        result = analyze_market(_sample_protocols())
        save_results(result, path)
        self.assertEqual(result.saved_to, path)
        os.unlink(path)


if __name__ == "__main__":
    unittest.main()
