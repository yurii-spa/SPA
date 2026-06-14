"""
Tests for MP-856 ProtocolRevenueQualityScorer
Run with: python3 -m unittest spa_core.tests.test_protocol_revenue_quality_scorer
"""

import json
import os
import tempfile
import time
import unittest

from spa_core.analytics.protocol_revenue_quality_scorer import (
    analyze,
    append_log,
    run,
    _fee_to_emission_ratio,
    _real_yield_score,
    _diversification_score,
    _growth_score,
    _efficiency_score,
    _revenue_per_tvl_pct,
    _revenue_per_user_usd,
    _revenue_quality,
    _sustainability_label,
    _INF_RATIO_SENTINEL,
)


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def make_proto(
    name="TestProtocol",
    fee_revenue=1_000_000.0,
    emission_cost=200_000.0,
    tvl=100_000_000.0,
    mau=5000,
    unique_sources=3,
    has_buyback=False,
    growth_pct=10.0,
):
    return {
        "name": name,
        "protocol_fee_revenue_30d_usd": fee_revenue,
        "token_emission_cost_30d_usd": emission_cost,
        "tvl_usd": tvl,
        "monthly_active_users": mau,
        "unique_revenue_sources": unique_sources,
        "has_buyback_mechanism": has_buyback,
        "fee_revenue_growth_30d_pct": growth_pct,
    }


# ===========================================================================
# Unit tests — _fee_to_emission_ratio
# ===========================================================================

class TestFeeToEmissionRatio(unittest.TestCase):

    def test_normal_ratio(self):
        self.assertAlmostEqual(_fee_to_emission_ratio(1_000_000, 200_000), 5.0, places=6)

    def test_zero_emission_returns_sentinel(self):
        self.assertEqual(_fee_to_emission_ratio(500_000, 0), _INF_RATIO_SENTINEL)

    def test_sentinel_is_999(self):
        self.assertEqual(_INF_RATIO_SENTINEL, 999.0)

    def test_low_ratio(self):
        self.assertAlmostEqual(_fee_to_emission_ratio(100, 1000), 0.1, places=6)

    def test_equal_ratio(self):
        self.assertAlmostEqual(_fee_to_emission_ratio(500, 500), 1.0, places=6)

    def test_negative_emission_treated_as_zero(self):
        # negative emission → no emission → sentinel
        self.assertEqual(_fee_to_emission_ratio(1000, -100), _INF_RATIO_SENTINEL)

    def test_zero_fee_zero_emission(self):
        self.assertEqual(_fee_to_emission_ratio(0, 0), _INF_RATIO_SENTINEL)

    def test_zero_fee_with_emission(self):
        self.assertAlmostEqual(_fee_to_emission_ratio(0, 1000), 0.0, places=6)


# ===========================================================================
# Unit tests — _real_yield_score
# ===========================================================================

class TestRealYieldScore(unittest.TestCase):

    def test_no_emission_organic_40(self):
        self.assertEqual(_real_yield_score(1_000_000, 0, False), 40)

    def test_no_emission_with_buyback_still_40(self):
        # cap at 40
        self.assertEqual(_real_yield_score(1_000_000, 0, True), 40)

    def test_ratio_5_exact(self):
        # fee=1000, emission=200 → ratio=5.0 → base=40
        self.assertEqual(_real_yield_score(1000, 200, False), 40)

    def test_ratio_above_5(self):
        self.assertEqual(_real_yield_score(10000, 200, False), 40)

    def test_ratio_2_to_5(self):
        # fee=400, emission=200 → ratio=2.0 → base=30
        self.assertEqual(_real_yield_score(400, 200, False), 30)

    def test_ratio_1_to_2(self):
        # fee=200, emission=200 → ratio=1.0 → base=20
        self.assertEqual(_real_yield_score(200, 200, False), 20)

    def test_ratio_0_5_to_1(self):
        # fee=100, emission=200 → ratio=0.5 → base=10
        self.assertEqual(_real_yield_score(100, 200, False), 10)

    def test_ratio_0_2_to_0_5(self):
        # fee=60, emission=200 → ratio=0.3 → base=5
        self.assertEqual(_real_yield_score(60, 200, False), 5)

    def test_ratio_below_0_2(self):
        # fee=20, emission=200 → ratio=0.1 → base=0
        self.assertEqual(_real_yield_score(20, 200, False), 0)

    def test_buyback_adds_5(self):
        # ratio=2.0 → base=30, +5=35
        self.assertEqual(_real_yield_score(400, 200, True), 35)

    def test_buyback_capped_at_40(self):
        # ratio=5.0 → base=40, +5 → cap 40
        self.assertEqual(_real_yield_score(1000, 200, True), 40)

    def test_buyback_at_zero_base(self):
        # ratio<0.2 → base=0, +5=5
        self.assertEqual(_real_yield_score(20, 200, True), 5)

    def test_ratio_exactly_0_2(self):
        # fee=40, emission=200 → ratio=0.2 → base=5
        self.assertEqual(_real_yield_score(40, 200, False), 5)

    def test_ratio_exactly_1(self):
        self.assertEqual(_real_yield_score(200, 200, False), 20)

    def test_ratio_exactly_2(self):
        self.assertEqual(_real_yield_score(400, 200, False), 30)


# ===========================================================================
# Unit tests — _diversification_score
# ===========================================================================

class TestDiversificationScore(unittest.TestCase):

    def test_zero_sources(self):
        self.assertEqual(_diversification_score(0), 0)

    def test_one_source(self):
        self.assertEqual(_diversification_score(1), 4)

    def test_two_sources(self):
        self.assertEqual(_diversification_score(2), 8)

    def test_three_sources(self):
        self.assertEqual(_diversification_score(3), 12)

    def test_four_sources(self):
        self.assertEqual(_diversification_score(4), 16)

    def test_five_sources(self):
        self.assertEqual(_diversification_score(5), 20)

    def test_six_sources(self):
        self.assertEqual(_diversification_score(6), 20)

    def test_ten_sources(self):
        self.assertEqual(_diversification_score(10), 20)


# ===========================================================================
# Unit tests — _growth_score
# ===========================================================================

class TestGrowthScore(unittest.TestCase):

    def test_above_30(self):
        self.assertEqual(_growth_score(35.0), 20)

    def test_exactly_30(self):
        self.assertEqual(_growth_score(30.0), 20)

    def test_10_to_30(self):
        self.assertEqual(_growth_score(15.0), 15)

    def test_exactly_10(self):
        self.assertEqual(_growth_score(10.0), 15)

    def test_0_to_10(self):
        self.assertEqual(_growth_score(5.0), 10)

    def test_exactly_0(self):
        self.assertEqual(_growth_score(0.0), 10)

    def test_negative_10_to_0(self):
        self.assertEqual(_growth_score(-5.0), 5)

    def test_exactly_neg_10(self):
        self.assertEqual(_growth_score(-10.0), 5)

    def test_below_neg_10(self):
        self.assertEqual(_growth_score(-15.0), 0)

    def test_extreme_negative(self):
        self.assertEqual(_growth_score(-100.0), 0)

    def test_extreme_positive(self):
        self.assertEqual(_growth_score(1000.0), 20)


# ===========================================================================
# Unit tests — _efficiency_score
# ===========================================================================

class TestEfficiencyScore(unittest.TestCase):

    def test_zero_tvl_returns_0(self):
        self.assertEqual(_efficiency_score(1_000_000, 0), 0)

    def test_above_1pct(self):
        # 1_000_000 / 50_000_000 * 100 = 2.0%
        self.assertEqual(_efficiency_score(1_000_000, 50_000_000), 20)

    def test_exactly_1pct(self):
        # 1_000_000 / 100_000_000 * 100 = 1.0%
        self.assertEqual(_efficiency_score(1_000_000, 100_000_000), 20)

    def test_0_5_to_1pct(self):
        # 500_000 / 100_000_000 * 100 = 0.5%
        self.assertEqual(_efficiency_score(500_000, 100_000_000), 15)

    def test_0_2_to_0_5pct(self):
        # 300_000 / 100_000_000 * 100 = 0.3%
        self.assertEqual(_efficiency_score(300_000, 100_000_000), 10)

    def test_0_1_to_0_2pct(self):
        # 150_000 / 100_000_000 * 100 = 0.15%
        self.assertEqual(_efficiency_score(150_000, 100_000_000), 5)

    def test_below_0_1pct(self):
        # 50_000 / 100_000_000 * 100 = 0.05%
        self.assertEqual(_efficiency_score(50_000, 100_000_000), 0)

    def test_negative_tvl_treated_as_zero(self):
        self.assertEqual(_efficiency_score(1_000_000, -1), 0)


# ===========================================================================
# Unit tests — _revenue_per_tvl_pct
# ===========================================================================

class TestRevenuePerTvlPct(unittest.TestCase):

    def test_normal(self):
        self.assertAlmostEqual(_revenue_per_tvl_pct(1_000_000, 100_000_000), 1.0, places=6)

    def test_zero_tvl_returns_0(self):
        self.assertAlmostEqual(_revenue_per_tvl_pct(1_000_000, 0), 0.0, places=6)

    def test_zero_fee(self):
        self.assertAlmostEqual(_revenue_per_tvl_pct(0, 100_000_000), 0.0, places=6)


# ===========================================================================
# Unit tests — _revenue_per_user_usd
# ===========================================================================

class TestRevenuePerUserUsd(unittest.TestCase):

    def test_normal(self):
        self.assertAlmostEqual(_revenue_per_user_usd(1_000_000, 1000), 1000.0, places=6)

    def test_zero_mau_returns_0(self):
        self.assertAlmostEqual(_revenue_per_user_usd(1_000_000, 0), 0.0, places=6)

    def test_zero_fee(self):
        self.assertAlmostEqual(_revenue_per_user_usd(0, 1000), 0.0, places=6)


# ===========================================================================
# Unit tests — _revenue_quality
# ===========================================================================

class TestRevenueQuality(unittest.TestCase):

    def test_excellent_80(self):
        self.assertEqual(_revenue_quality(80), "EXCELLENT")

    def test_excellent_100(self):
        self.assertEqual(_revenue_quality(100), "EXCELLENT")

    def test_strong_60(self):
        self.assertEqual(_revenue_quality(60), "STRONG")

    def test_strong_79(self):
        self.assertEqual(_revenue_quality(79), "STRONG")

    def test_adequate_40(self):
        self.assertEqual(_revenue_quality(40), "ADEQUATE")

    def test_adequate_59(self):
        self.assertEqual(_revenue_quality(59), "ADEQUATE")

    def test_weak_20(self):
        self.assertEqual(_revenue_quality(20), "WEAK")

    def test_weak_39(self):
        self.assertEqual(_revenue_quality(39), "WEAK")

    def test_unsustainable_0(self):
        self.assertEqual(_revenue_quality(0), "UNSUSTAINABLE")

    def test_unsustainable_19(self):
        self.assertEqual(_revenue_quality(19), "UNSUSTAINABLE")


# ===========================================================================
# Unit tests — _sustainability_label
# ===========================================================================

class TestSustainabilityLabel(unittest.TestCase):

    def test_score_80_plus(self):
        label = _sustainability_label(80, 3, 5.0)
        self.assertIn("Revenue-backed", label)

    def test_score_60_plus(self):
        label = _sustainability_label(65, 4, 3.5)
        self.assertIn("Strong fundamentals", label)
        self.assertIn("4 revenue streams", label)
        self.assertIn("3.5x", label)

    def test_score_40_plus(self):
        label = _sustainability_label(45, 2, 1.0)
        self.assertIn("Adequate", label)

    def test_score_20_plus(self):
        label = _sustainability_label(25, 1, 0.3)
        self.assertIn("Weak", label)

    def test_score_below_20(self):
        label = _sustainability_label(10, 1, 0.1)
        self.assertIn("Unsustainable", label)

    def test_strong_with_sentinel_ratio(self):
        label = _sustainability_label(65, 3, _INF_RATIO_SENTINEL)
        self.assertIn("Strong fundamentals", label)
        self.assertIn("999.0x", label)


# ===========================================================================
# Integration tests — analyze()
# ===========================================================================

class TestAnalyzeEmpty(unittest.TestCase):

    def test_empty_protocols(self):
        result = analyze([])
        self.assertEqual(result["protocols"], [])
        self.assertIsNone(result["most_sustainable"])
        self.assertIsNone(result["least_sustainable"])
        self.assertAlmostEqual(result["average_revenue_score"], 0.0, places=6)
        self.assertIn("timestamp", result)

    def test_timestamp_is_float(self):
        result = analyze([])
        self.assertIsInstance(result["timestamp"], float)


class TestAnalyzeSingleProtocol(unittest.TestCase):

    def setUp(self):
        self.proto = make_proto(
            fee_revenue=1_000_000,
            emission_cost=200_000,  # ratio=5.0 → rys=40
            tvl=100_000_000,        # rev_per_tvl=1.0% → effs=20
            mau=5000,
            unique_sources=3,       # divs=12
            has_buyback=False,
            growth_pct=15.0,        # gs=15
        )
        self.result = analyze([self.proto])
        self.p = self.result["protocols"][0]

    def test_one_protocol_returned(self):
        self.assertEqual(len(self.result["protocols"]), 1)

    def test_name_preserved(self):
        self.assertEqual(self.p["name"], "TestProtocol")

    def test_real_yield_score(self):
        self.assertEqual(self.p["real_yield_score"], 40)

    def test_diversification_score(self):
        self.assertEqual(self.p["diversification_score"], 12)

    def test_growth_score(self):
        self.assertEqual(self.p["growth_score"], 15)

    def test_efficiency_score(self):
        self.assertEqual(self.p["efficiency_score"], 20)

    def test_total_score(self):
        # 40 + 12 + 15 + 20 = 87
        self.assertEqual(self.p["revenue_score"], 87)

    def test_quality_excellent(self):
        self.assertEqual(self.p["revenue_quality"], "EXCELLENT")

    def test_most_sustainable_set(self):
        self.assertEqual(self.result["most_sustainable"], "TestProtocol")

    def test_least_sustainable_set(self):
        self.assertEqual(self.result["least_sustainable"], "TestProtocol")

    def test_average_revenue_score(self):
        self.assertAlmostEqual(self.result["average_revenue_score"], 87.0, places=6)

    def test_fee_to_emission_ratio(self):
        self.assertAlmostEqual(self.p["fee_to_emission_ratio"], 5.0, places=6)

    def test_revenue_per_tvl_pct(self):
        self.assertAlmostEqual(self.p["revenue_per_tvl_pct"], 1.0, places=6)

    def test_revenue_per_user_usd(self):
        self.assertAlmostEqual(self.p["revenue_per_user_usd"], 200.0, places=6)

    def test_sustainability_label_is_str(self):
        self.assertIsInstance(self.p["sustainability_label"], str)


class TestAnalyzeZeroEmission(unittest.TestCase):

    def setUp(self):
        proto = make_proto(
            fee_revenue=500_000,
            emission_cost=0,
            tvl=50_000_000,
            unique_sources=5,
            growth_pct=35.0,
        )
        self.result = analyze([proto])
        self.p = self.result["protocols"][0]

    def test_ratio_is_sentinel(self):
        self.assertEqual(self.p["fee_to_emission_ratio"], _INF_RATIO_SENTINEL)

    def test_real_yield_score_40(self):
        self.assertEqual(self.p["real_yield_score"], 40)

    def test_diversification_score_20(self):
        self.assertEqual(self.p["diversification_score"], 20)

    def test_growth_score_20(self):
        self.assertEqual(self.p["growth_score"], 20)


class TestAnalyzeZeroTvl(unittest.TestCase):

    def setUp(self):
        proto = make_proto(tvl=0)
        self.result = analyze([proto])
        self.p = self.result["protocols"][0]

    def test_efficiency_score_0(self):
        self.assertEqual(self.p["efficiency_score"], 0)

    def test_revenue_per_tvl_pct_0(self):
        self.assertAlmostEqual(self.p["revenue_per_tvl_pct"], 0.0, places=6)


class TestAnalyzeZeroMau(unittest.TestCase):

    def setUp(self):
        proto = make_proto(mau=0)
        self.result = analyze([proto])
        self.p = self.result["protocols"][0]

    def test_revenue_per_user_0(self):
        self.assertAlmostEqual(self.p["revenue_per_user_usd"], 0.0, places=6)


class TestAnalyzeUnsustainable(unittest.TestCase):

    def setUp(self):
        proto = make_proto(
            fee_revenue=10,
            emission_cost=10_000,   # ratio=0.001 → rys=0
            tvl=10_000_000_000,     # very low rev/tvl → effs=0
            unique_sources=0,       # divs=0
            growth_pct=-50.0,       # gs=0
            has_buyback=False,
        )
        self.result = analyze([proto])
        self.p = self.result["protocols"][0]

    def test_score_0(self):
        self.assertEqual(self.p["revenue_score"], 0)

    def test_quality_unsustainable(self):
        self.assertEqual(self.p["revenue_quality"], "UNSUSTAINABLE")

    def test_sustainability_label_contains_unsustainable(self):
        self.assertIn("Unsustainable", self.p["sustainability_label"])


class TestAnalyzeMultipleProtocols(unittest.TestCase):

    def setUp(self):
        protocols = [
            make_proto("Good", fee_revenue=1_000_000, emission_cost=100_000,
                       tvl=50_000_000, unique_sources=5, growth_pct=30.0),
            make_proto("Bad", fee_revenue=10, emission_cost=10_000,
                       tvl=10_000_000_000, unique_sources=0, growth_pct=-50.0),
            make_proto("Mid", fee_revenue=200_000, emission_cost=200_000,
                       tvl=100_000_000, unique_sources=2, growth_pct=0.0),
        ]
        self.result = analyze(protocols)

    def test_three_protocols(self):
        self.assertEqual(len(self.result["protocols"]), 3)

    def test_most_sustainable_is_good(self):
        self.assertEqual(self.result["most_sustainable"], "Good")

    def test_least_sustainable_is_bad(self):
        self.assertEqual(self.result["least_sustainable"], "Bad")

    def test_average_score_computed(self):
        scores = [p["revenue_score"] for p in self.result["protocols"]]
        expected = sum(scores) / 3
        self.assertAlmostEqual(self.result["average_revenue_score"], expected, places=6)

    def test_no_score_above_100(self):
        for p in self.result["protocols"]:
            self.assertLessEqual(p["revenue_score"], 100)

    def test_all_scores_non_negative(self):
        for p in self.result["protocols"]:
            self.assertGreaterEqual(p["revenue_score"], 0)


class TestAnalyzeFieldPresence(unittest.TestCase):

    def test_all_required_keys_present(self):
        proto = make_proto()
        result = analyze([proto])
        p = result["protocols"][0]
        expected_keys = [
            "name", "revenue_score", "revenue_quality", "fee_to_emission_ratio",
            "revenue_per_tvl_pct", "revenue_per_user_usd", "real_yield_score",
            "diversification_score", "growth_score", "efficiency_score",
            "sustainability_label",
        ]
        for key in expected_keys:
            self.assertIn(key, p, f"Missing key: {key}")

    def test_top_level_keys_present(self):
        result = analyze([make_proto()])
        for key in ["protocols", "most_sustainable", "least_sustainable",
                    "average_revenue_score", "timestamp"]:
            self.assertIn(key, result, f"Missing top-level key: {key}")


class TestAnalyzeFieldTypes(unittest.TestCase):

    def setUp(self):
        self.p = analyze([make_proto()])["protocols"][0]

    def test_name_str(self):
        self.assertIsInstance(self.p["name"], str)

    def test_revenue_score_int(self):
        self.assertIsInstance(self.p["revenue_score"], int)

    def test_revenue_quality_str(self):
        self.assertIsInstance(self.p["revenue_quality"], str)

    def test_fee_to_emission_ratio_float(self):
        self.assertIsInstance(self.p["fee_to_emission_ratio"], float)

    def test_revenue_per_tvl_float(self):
        self.assertIsInstance(self.p["revenue_per_tvl_pct"], float)

    def test_revenue_per_user_float(self):
        self.assertIsInstance(self.p["revenue_per_user_usd"], float)

    def test_real_yield_score_int(self):
        self.assertIsInstance(self.p["real_yield_score"], int)

    def test_diversification_score_int(self):
        self.assertIsInstance(self.p["diversification_score"], int)

    def test_growth_score_int(self):
        self.assertIsInstance(self.p["growth_score"], int)

    def test_efficiency_score_int(self):
        self.assertIsInstance(self.p["efficiency_score"], int)

    def test_sustainability_label_str(self):
        self.assertIsInstance(self.p["sustainability_label"], str)


class TestAnalyzeScoreCap100(unittest.TestCase):

    def test_max_scores_do_not_exceed_100(self):
        # All max: rys=40, divs=20, gs=20, effs=20 → 100
        proto = make_proto(
            fee_revenue=10_000_000,
            emission_cost=0,         # rys=40 (no emission)
            tvl=500_000_000,         # effs=20 (rev/tvl=2%)
            unique_sources=10,       # divs=20
            growth_pct=100.0,        # gs=20
            has_buyback=True,        # +5 but capped
        )
        result = analyze([proto])
        self.assertEqual(result["protocols"][0]["revenue_score"], 100)

    def test_buyback_does_not_exceed_40_rys(self):
        # emission=0 → base=40, +5 buyback → cap=40
        score = _real_yield_score(1_000_000, 0, True)
        self.assertEqual(score, 40)


class TestAnalyzeQualityBoundaries(unittest.TestCase):

    def _make_score(self, target_score: int):
        """
        Build a protocol that achieves roughly target_score by controlling
        individual components. We'll use a direct approach:
        real_yield=target//4, etc. Easier: just test _revenue_quality directly.
        """
        return _revenue_quality(target_score)

    def test_boundary_80(self):
        self.assertEqual(self._make_score(80), "EXCELLENT")

    def test_boundary_79(self):
        self.assertEqual(self._make_score(79), "STRONG")

    def test_boundary_60(self):
        self.assertEqual(self._make_score(60), "STRONG")

    def test_boundary_59(self):
        self.assertEqual(self._make_score(59), "ADEQUATE")

    def test_boundary_40(self):
        self.assertEqual(self._make_score(40), "ADEQUATE")

    def test_boundary_39(self):
        self.assertEqual(self._make_score(39), "WEAK")

    def test_boundary_20(self):
        self.assertEqual(self._make_score(20), "WEAK")

    def test_boundary_19(self):
        self.assertEqual(self._make_score(19), "UNSUSTAINABLE")


class TestAnalyzeNamesAndAverages(unittest.TestCase):

    def test_protocol_name_preserved(self):
        result = analyze([make_proto(name="Aave V3")])
        self.assertEqual(result["protocols"][0]["name"], "Aave V3")

    def test_single_protocol_most_least_same(self):
        result = analyze([make_proto(name="Only")])
        self.assertEqual(result["most_sustainable"], "Only")
        self.assertEqual(result["least_sustainable"], "Only")

    def test_average_single(self):
        result = analyze([make_proto(
            fee_revenue=1_000_000, emission_cost=200_000,
            tvl=100_000_000, unique_sources=3, growth_pct=15.0
        )])
        score = result["protocols"][0]["revenue_score"]
        self.assertAlmostEqual(result["average_revenue_score"], float(score), places=6)

    def test_average_two_equal(self):
        proto = make_proto()
        result = analyze([proto, proto])
        scores = [p["revenue_score"] for p in result["protocols"]]
        expected = sum(scores) / 2
        self.assertAlmostEqual(result["average_revenue_score"], expected, places=6)


class TestAnalyzeSustainabilityLabelContent(unittest.TestCase):

    def test_strong_label_contains_streams_and_ratio(self):
        proto = make_proto(
            fee_revenue=600_000,   # ratio=3.0 with emission=200k
            emission_cost=200_000,
            tvl=200_000_000,
            unique_sources=4,
            growth_pct=10.0,
        )
        result = analyze([proto])
        p = result["protocols"][0]
        if p["revenue_score"] >= 60 and p["revenue_score"] < 80:
            self.assertIn("Strong fundamentals", p["sustainability_label"])

    def test_adequate_label(self):
        proto = make_proto(
            fee_revenue=50_000,
            emission_cost=200_000,    # ratio=0.25 → rys=5
            tvl=500_000_000,          # effs=0
            unique_sources=2,         # divs=8
            growth_pct=5.0,           # gs=10
        )
        result = analyze([proto])
        p = result["protocols"][0]
        self.assertIn(p["revenue_quality"], ["ADEQUATE", "WEAK", "UNSUSTAINABLE"])


# ===========================================================================
# Persistence tests
# ===========================================================================

class TestAppendLog(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_log_file(self):
        result = analyze([make_proto()])
        append_log(result, data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, "revenue_quality_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_log_is_list(self):
        result = analyze([make_proto()])
        append_log(result, data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, "revenue_quality_log.json")
        with open(log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_has_one_entry(self):
        result = analyze([make_proto()])
        append_log(result, data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, "revenue_quality_log.json")
        with open(log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_ring_buffer_cap_100(self):
        for i in range(105):
            result = analyze([make_proto(name=f"P{i}")])
            append_log(result, data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, "revenue_quality_log.json")
        with open(log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            result = analyze([make_proto(name=f"P{i}")])
            append_log(result, data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, "revenue_quality_log.json")
        with open(log_path) as fh:
            data = json.load(fh)
        last_name = data[-1]["protocols"][0]["name"]
        self.assertEqual(last_name, "P104")

    def test_log_grows_incrementally(self):
        for _ in range(3):
            result = analyze([make_proto()])
            append_log(result, data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, "revenue_quality_log.json")
        with open(log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 3)


class TestRunFunction(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_run_returns_dict(self):
        result = run([make_proto()], data_dir=self.tmpdir)
        self.assertIsInstance(result, dict)

    def test_run_creates_log(self):
        run([make_proto()], data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, "revenue_quality_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_run_result_has_protocols(self):
        result = run([make_proto()], data_dir=self.tmpdir)
        self.assertIn("protocols", result)
        self.assertEqual(len(result["protocols"]), 1)

    def test_run_with_config_none(self):
        result = run([make_proto()], config=None, data_dir=self.tmpdir)
        self.assertIn("protocols", result)

    def test_run_with_config_empty(self):
        result = run([make_proto()], config={}, data_dir=self.tmpdir)
        self.assertIn("protocols", result)


if __name__ == "__main__":
    unittest.main()


# =============================================================================
# MP-973  ProtocolRevenueQualityScorer tests
# =============================================================================

from spa_core.analytics.protocol_revenue_quality_scorer import (
    ProtocolRevenueQualityScorer,
    MP973_LABEL_PREMIUM,
    MP973_LABEL_HIGH,
    MP973_LABEL_MEDIUM,
    MP973_LABEL_LOW,
    MP973_LABEL_INCENTIVE_DEPENDENT,
    MP973_FLAG_INCENTIVE_DEPENDENT,
    MP973_FLAG_WHALE_REVENUE,
    MP973_FLAG_DECLINING,
    MP973_FLAG_HIGH_QUALITY_GROWTH,
    MP973_FLAG_CYCLICAL_RISK,
    _mp973_organic_revenue_pct,
    _mp973_diversity_score,
    _mp973_recurring_score,
    _mp973_growth_score,
    _mp973_quality_score,
    _mp973_cyclicality_resilience,
    _mp973_revenue_stability_score,
    _mp973_sustainability_multiple,
    _mp973_quality_label,
    _mp973_flags,
)


def make_proto_mp973(
    name="TestProtocol",
    total_revenue_30d_usd=1_000_000.0,
    trading_fee_revenue_pct=60.0,
    liquidation_fee_revenue_pct=10.0,
    protocol_fee_revenue_pct=20.0,
    incentive_revenue_pct=10.0,
    revenue_growth_mom_pct=15.0,
    revenue_concentration_top3_users_pct=40.0,
    unique_revenue_sources_count=4,
    has_recurring_revenue=True,
    cyclical_dependency="neutral",
    revenue_30d_vs_90d_avg_ratio=1.0,
):
    return {
        "name": name,
        "total_revenue_30d_usd": total_revenue_30d_usd,
        "trading_fee_revenue_pct": trading_fee_revenue_pct,
        "liquidation_fee_revenue_pct": liquidation_fee_revenue_pct,
        "protocol_fee_revenue_pct": protocol_fee_revenue_pct,
        "incentive_revenue_pct": incentive_revenue_pct,
        "revenue_growth_mom_pct": revenue_growth_mom_pct,
        "revenue_concentration_top3_users_pct": revenue_concentration_top3_users_pct,
        "unique_revenue_sources_count": unique_revenue_sources_count,
        "has_recurring_revenue": has_recurring_revenue,
        "cyclical_dependency": cyclical_dependency,
        "revenue_30d_vs_90d_avg_ratio": revenue_30d_vs_90d_avg_ratio,
    }


# ── Sub-scorer unit tests ─────────────────────────────────────────────────────

class TestMp973OrganicRevenuePct(unittest.TestCase):

    def test_basic(self):
        self.assertAlmostEqual(_mp973_organic_revenue_pct(30.0), 70.0)

    def test_zero_incentive(self):
        self.assertAlmostEqual(_mp973_organic_revenue_pct(0.0), 100.0)

    def test_full_incentive(self):
        self.assertAlmostEqual(_mp973_organic_revenue_pct(100.0), 0.0)

    def test_clamped_below_zero(self):
        self.assertAlmostEqual(_mp973_organic_revenue_pct(110.0), 0.0)

    def test_clamped_above_100(self):
        self.assertAlmostEqual(_mp973_organic_revenue_pct(-10.0), 100.0)

    def test_50_pct(self):
        self.assertAlmostEqual(_mp973_organic_revenue_pct(50.0), 50.0)


class TestMp973DiversityScore(unittest.TestCase):

    def test_zero_sources(self):
        self.assertAlmostEqual(_mp973_diversity_score(0), 0.0)

    def test_one_source(self):
        self.assertAlmostEqual(_mp973_diversity_score(1), 20.0)

    def test_two_sources(self):
        self.assertAlmostEqual(_mp973_diversity_score(2), 40.0)

    def test_three_sources(self):
        self.assertAlmostEqual(_mp973_diversity_score(3), 60.0)

    def test_five_sources(self):
        self.assertAlmostEqual(_mp973_diversity_score(5), 100.0)

    def test_six_sources_capped(self):
        self.assertAlmostEqual(_mp973_diversity_score(6), 100.0)

    def test_ten_sources_capped(self):
        self.assertAlmostEqual(_mp973_diversity_score(10), 100.0)


class TestMp973RecurringScore(unittest.TestCase):

    def test_has_recurring(self):
        self.assertAlmostEqual(_mp973_recurring_score(True), 100.0)

    def test_no_recurring(self):
        self.assertAlmostEqual(_mp973_recurring_score(False), 0.0)


class TestMp973GrowthScore(unittest.TestCase):

    def test_high_growth(self):
        self.assertAlmostEqual(_mp973_growth_score(30.0), 100.0)

    def test_above_30(self):
        self.assertAlmostEqual(_mp973_growth_score(50.0), 100.0)

    def test_moderate_growth(self):
        self.assertAlmostEqual(_mp973_growth_score(15.0), 75.0)

    def test_below_10(self):
        self.assertAlmostEqual(_mp973_growth_score(5.0), 50.0)

    def test_zero_growth(self):
        self.assertAlmostEqual(_mp973_growth_score(0.0), 50.0)

    def test_slight_decline(self):
        self.assertAlmostEqual(_mp973_growth_score(-10.0), 25.0)

    def test_sharp_decline(self):
        self.assertAlmostEqual(_mp973_growth_score(-25.0), 0.0)

    def test_exactly_minus_20(self):
        self.assertAlmostEqual(_mp973_growth_score(-20.0), 25.0)


class TestMp973QualityScore(unittest.TestCase):

    def test_perfect_score(self):
        # organic=100, 5+sources, recurring, growth>=30
        s = _mp973_quality_score(100.0, 5, True, 30.0)
        # 100*0.4 + 100*0.3 + 100*0.2 + 100*0.1 = 100
        self.assertAlmostEqual(s, 100.0)

    def test_zero_score(self):
        # organic=0, 0 sources, not recurring, growth < -20
        s = _mp973_quality_score(0.0, 0, False, -30.0)
        # 0*0.4 + 0*0.3 + 0*0.2 + 0*0.1 = 0
        self.assertAlmostEqual(s, 0.0)

    def test_components_weighted(self):
        # organic=80, 2 sources (div=40), recurring=True (100), growth=15 (75)
        s = _mp973_quality_score(80.0, 2, True, 15.0)
        expected = 80 * 0.4 + 40 * 0.3 + 100 * 0.2 + 75 * 0.1
        self.assertAlmostEqual(s, expected, places=3)

    def test_capped_at_100(self):
        s = _mp973_quality_score(100.0, 100, True, 100.0)
        self.assertLessEqual(s, 100.0)

    def test_floored_at_0(self):
        s = _mp973_quality_score(0.0, 0, False, -100.0)
        self.assertGreaterEqual(s, 0.0)


class TestMp973CyclicalityResilience(unittest.TestCase):

    def test_bear(self):
        self.assertAlmostEqual(_mp973_cyclicality_resilience("bear"), 100.0)

    def test_neutral(self):
        self.assertAlmostEqual(_mp973_cyclicality_resilience("neutral"), 67.0)

    def test_bull_market(self):
        self.assertAlmostEqual(_mp973_cyclicality_resilience("bull_market"), 33.0)

    def test_unknown_defaults_neutral(self):
        self.assertAlmostEqual(_mp973_cyclicality_resilience("unknown_value"), 67.0)


class TestMp973RevenueStabilityScore(unittest.TestCase):

    def test_perfect_stability(self):
        # conc=0 → 100; bear → 100; ratio=1.0 → 100
        s = _mp973_revenue_stability_score(0.0, "bear", 1.0)
        self.assertAlmostEqual(s, 100.0)

    def test_poor_stability(self):
        # conc=100 → 0; bull_market → 33; ratio=2.0 → 0
        s = _mp973_revenue_stability_score(100.0, "bull_market", 2.0)
        expected = (0.0 + 33.0 + 0.0) / 3.0
        self.assertAlmostEqual(s, expected, places=3)

    def test_ratio_close(self):
        s = _mp973_revenue_stability_score(30.0, "neutral", 1.05)  # delta=0.05 < 0.1 → 100
        expected = (70.0 + 67.0 + 100.0) / 3.0
        self.assertAlmostEqual(s, expected, places=3)

    def test_ratio_medium_delta(self):
        s = _mp973_revenue_stability_score(30.0, "neutral", 1.25)  # delta=0.25 → 60
        expected = (70.0 + 67.0 + 60.0) / 3.0
        self.assertAlmostEqual(s, expected, places=3)

    def test_ratio_large_delta(self):
        s = _mp973_revenue_stability_score(30.0, "neutral", 2.0)  # delta=1.0 ≥ 0.5 → 0
        expected = (70.0 + 67.0 + 0.0) / 3.0
        self.assertAlmostEqual(s, expected, places=3)


class TestMp973SustainabilityMultiple(unittest.TestCase):

    def test_basic(self):
        # quality=80 → 0.8; rev=1M; annualized=12M; multiple=9.6M
        val = _mp973_sustainability_multiple(80.0, 1_000_000)
        self.assertAlmostEqual(val, 9_600_000.0)

    def test_zero_quality(self):
        val = _mp973_sustainability_multiple(0.0, 1_000_000)
        self.assertAlmostEqual(val, 0.0)

    def test_zero_revenue(self):
        val = _mp973_sustainability_multiple(80.0, 0.0)
        self.assertAlmostEqual(val, 0.0)

    def test_perfect_quality(self):
        val = _mp973_sustainability_multiple(100.0, 500_000)
        self.assertAlmostEqual(val, 6_000_000.0)


class TestMp973QualityLabel(unittest.TestCase):

    def test_premium(self):
        label = _mp973_quality_label(90.0, 80.0, 5.0)
        self.assertEqual(label, MP973_LABEL_PREMIUM)

    def test_not_premium_low_organic(self):
        label = _mp973_quality_label(70.0, 80.0, 10.0)  # organic=70 ≤ 80
        # quality=80 > 60 → HIGH
        self.assertEqual(label, MP973_LABEL_HIGH)

    def test_not_premium_low_quality(self):
        label = _mp973_quality_label(90.0, 70.0, 5.0)  # quality=70 ≤ 75
        # quality=70 > 60 → HIGH
        self.assertEqual(label, MP973_LABEL_HIGH)

    def test_high(self):
        label = _mp973_quality_label(70.0, 65.0, 10.0)
        self.assertEqual(label, MP973_LABEL_HIGH)

    def test_medium(self):
        label = _mp973_quality_label(60.0, 50.0, 20.0)
        self.assertEqual(label, MP973_LABEL_MEDIUM)

    def test_low(self):
        label = _mp973_quality_label(50.0, 30.0, 20.0)
        self.assertEqual(label, MP973_LABEL_LOW)

    def test_incentive_dependent_by_incentive_pct(self):
        label = _mp973_quality_label(40.0, 80.0, 60.0)  # incentive=60 > 50
        self.assertEqual(label, MP973_LABEL_INCENTIVE_DEPENDENT)

    def test_incentive_dependent_very_low_quality(self):
        label = _mp973_quality_label(10.0, 10.0, 10.0)  # quality=10 ≤ 20
        self.assertEqual(label, MP973_LABEL_INCENTIVE_DEPENDENT)


class TestMp973Flags(unittest.TestCase):

    def test_no_flags(self):
        flags = _mp973_flags(10.0, 30.0, 10.0, 75.0, "neutral")
        self.assertEqual(flags, [])

    def test_incentive_dependent_flag(self):
        flags = _mp973_flags(60.0, 30.0, 10.0, 75.0, "neutral")
        self.assertIn(MP973_FLAG_INCENTIVE_DEPENDENT, flags)

    def test_incentive_exactly_50_no_flag(self):
        flags = _mp973_flags(50.0, 30.0, 10.0, 75.0, "neutral")
        self.assertNotIn(MP973_FLAG_INCENTIVE_DEPENDENT, flags)

    def test_whale_revenue_flag(self):
        flags = _mp973_flags(10.0, 80.0, 10.0, 75.0, "neutral")
        self.assertIn(MP973_FLAG_WHALE_REVENUE, flags)

    def test_whale_revenue_exactly_70_no_flag(self):
        flags = _mp973_flags(10.0, 70.0, 10.0, 75.0, "neutral")
        self.assertNotIn(MP973_FLAG_WHALE_REVENUE, flags)

    def test_declining_flag(self):
        flags = _mp973_flags(10.0, 30.0, -25.0, 75.0, "neutral")
        self.assertIn(MP973_FLAG_DECLINING, flags)

    def test_declining_exactly_minus_20_no_flag(self):
        flags = _mp973_flags(10.0, 30.0, -20.0, 75.0, "neutral")
        self.assertNotIn(MP973_FLAG_DECLINING, flags)

    def test_high_quality_growth_flag(self):
        flags = _mp973_flags(10.0, 30.0, 25.0, 75.0, "neutral")
        self.assertIn(MP973_FLAG_HIGH_QUALITY_GROWTH, flags)

    def test_high_quality_growth_low_quality_no_flag(self):
        flags = _mp973_flags(10.0, 30.0, 25.0, 65.0, "neutral")
        self.assertNotIn(MP973_FLAG_HIGH_QUALITY_GROWTH, flags)

    def test_cyclical_risk_flag(self):
        flags = _mp973_flags(10.0, 30.0, 10.0, 75.0, "bull_market")
        self.assertIn(MP973_FLAG_CYCLICAL_RISK, flags)

    def test_cyclical_risk_neutral_no_flag(self):
        flags = _mp973_flags(10.0, 30.0, 10.0, 75.0, "neutral")
        self.assertNotIn(MP973_FLAG_CYCLICAL_RISK, flags)

    def test_multiple_flags(self):
        flags = _mp973_flags(60.0, 80.0, -25.0, 50.0, "bull_market")
        self.assertIn(MP973_FLAG_INCENTIVE_DEPENDENT, flags)
        self.assertIn(MP973_FLAG_WHALE_REVENUE, flags)
        self.assertIn(MP973_FLAG_DECLINING, flags)
        self.assertIn(MP973_FLAG_CYCLICAL_RISK, flags)


# ── ProtocolRevenueQualityScorer.score() tests ────────────────────────────────

class TestProtocolRevenueQualityScorerScore(unittest.TestCase):

    def setUp(self):
        self.scorer = ProtocolRevenueQualityScorer()

    def test_empty_protocols(self):
        result = self.scorer.score([])
        self.assertIsInstance(result, dict)

    def test_empty_returns_zero_aggregates(self):
        result = self.scorer.score([])
        self.assertIsNone(result["highest_quality"])
        self.assertIsNone(result["lowest_quality"])
        self.assertAlmostEqual(result["average_quality_score"], 0.0)
        self.assertEqual(result["premium_count"], 0)
        self.assertEqual(result["incentive_dependent_count"], 0)

    def test_single_protocol_keys(self):
        result = self.scorer.score([make_proto_mp973()])
        self.assertIn("protocols", result)
        self.assertIn("highest_quality", result)
        self.assertIn("lowest_quality", result)
        self.assertIn("average_quality_score", result)
        self.assertIn("premium_count", result)
        self.assertIn("incentive_dependent_count", result)
        self.assertIn("timestamp", result)

    def test_protocol_entry_keys(self):
        result = self.scorer.score([make_proto_mp973()])
        p = result["protocols"][0]
        for key in [
            "name", "quality_score", "organic_revenue_pct",
            "revenue_stability_score", "sustainability_multiple",
            "label", "flags",
        ]:
            self.assertIn(key, p, f"Missing key: {key}")

    def test_quality_score_in_range(self):
        result = self.scorer.score([make_proto_mp973()])
        q = result["protocols"][0]["quality_score"]
        self.assertGreaterEqual(q, 0.0)
        self.assertLessEqual(q, 100.0)

    def test_organic_revenue_computed(self):
        result = self.scorer.score([make_proto_mp973(incentive_revenue_pct=30.0)])
        self.assertAlmostEqual(result["protocols"][0]["organic_revenue_pct"], 70.0)

    def test_premium_label(self):
        proto = make_proto_mp973(
            incentive_revenue_pct=5.0,    # organic=95>80
            unique_revenue_sources_count=5,
            has_recurring_revenue=True,
            revenue_growth_mom_pct=30.0,
        )
        result = self.scorer.score([proto])
        # quality = 95*0.4+100*0.3+100*0.2+100*0.1 = 38+30+20+10 = 98 > 75
        self.assertEqual(result["protocols"][0]["label"], MP973_LABEL_PREMIUM)

    def test_incentive_dependent_label(self):
        proto = make_proto_mp973(incentive_revenue_pct=70.0)
        result = self.scorer.score([proto])
        self.assertEqual(result["protocols"][0]["label"], MP973_LABEL_INCENTIVE_DEPENDENT)

    def test_highest_quality_name(self):
        protos = [
            make_proto_mp973(name="A", unique_revenue_sources_count=5, has_recurring_revenue=True, incentive_revenue_pct=0.0),
            make_proto_mp973(name="B", unique_revenue_sources_count=0, has_recurring_revenue=False, incentive_revenue_pct=80.0),
        ]
        result = self.scorer.score(protos)
        self.assertEqual(result["highest_quality"], "A")
        self.assertEqual(result["lowest_quality"], "B")

    def test_average_quality_score(self):
        protos = [
            make_proto_mp973(name="A"),
            make_proto_mp973(name="B"),
        ]
        result = self.scorer.score(protos)
        scores = [p["quality_score"] for p in result["protocols"]]
        expected_avg = sum(scores) / len(scores)
        self.assertAlmostEqual(result["average_quality_score"], expected_avg, places=2)

    def test_premium_count(self):
        protos = [
            make_proto_mp973(
                name="Premium",
                incentive_revenue_pct=5.0,
                unique_revenue_sources_count=5,
                has_recurring_revenue=True,
                revenue_growth_mom_pct=30.0,
            ),
            make_proto_mp973(name="Low", incentive_revenue_pct=80.0),
        ]
        result = self.scorer.score(protos)
        self.assertEqual(result["premium_count"], 1)

    def test_incentive_dependent_count(self):
        protos = [
            make_proto_mp973(incentive_revenue_pct=60.0),
            make_proto_mp973(incentive_revenue_pct=70.0),
            make_proto_mp973(incentive_revenue_pct=10.0),
        ]
        result = self.scorer.score(protos)
        self.assertEqual(result["incentive_dependent_count"], 2)

    def test_sustainability_multiple_computed(self):
        proto = make_proto_mp973(total_revenue_30d_usd=1_000_000)
        result = self.scorer.score([proto])
        p = result["protocols"][0]
        expected = (p["quality_score"] / 100.0) * 1_000_000 * 12
        self.assertAlmostEqual(p["sustainability_multiple"], expected, places=0)

    def test_config_none_accepted(self):
        result = self.scorer.score([make_proto_mp973()], config=None)
        self.assertIn("protocols", result)

    def test_config_empty_dict_accepted(self):
        result = self.scorer.score([make_proto_mp973()], config={})
        self.assertIn("protocols", result)

    def test_timestamp_is_recent(self):
        before = time.time()
        result = self.scorer.score([make_proto_mp973()])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_multiple_protocols_count(self):
        protos = [make_proto_mp973(name=f"P{i}") for i in range(5)]
        result = self.scorer.score(protos)
        self.assertEqual(len(result["protocols"]), 5)

    def test_flags_list(self):
        result = self.scorer.score([make_proto_mp973()])
        self.assertIsInstance(result["protocols"][0]["flags"], list)

    def test_cyclical_risk_flag_in_score(self):
        proto = make_proto_mp973(cyclical_dependency="bull_market")
        result = self.scorer.score([proto])
        self.assertIn(MP973_FLAG_CYCLICAL_RISK, result["protocols"][0]["flags"])

    def test_whale_revenue_flag_in_score(self):
        proto = make_proto_mp973(revenue_concentration_top3_users_pct=80.0)
        result = self.scorer.score([proto])
        self.assertIn(MP973_FLAG_WHALE_REVENUE, result["protocols"][0]["flags"])

    def test_declining_flag_in_score(self):
        proto = make_proto_mp973(revenue_growth_mom_pct=-30.0)
        result = self.scorer.score([proto])
        self.assertIn(MP973_FLAG_DECLINING, result["protocols"][0]["flags"])


# ── ring-buffer persistence tests for ProtocolRevenueQualityScorer ─────────────

class TestProtocolRevenueQualityScorerRun(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.scorer = ProtocolRevenueQualityScorer()
        self.log_path = os.path.join(self.tmpdir, "revenue_quality_log.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_run_creates_log(self):
        self.scorer.run([make_proto_mp973()], data_dir=self.tmpdir)
        self.assertTrue(os.path.exists(self.log_path))

    def test_run_log_is_list(self):
        self.scorer.run([make_proto_mp973()], data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_run_appends_entries(self):
        self.scorer.run([make_proto_mp973()], data_dir=self.tmpdir)
        self.scorer.run([make_proto_mp973()], data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_run_ring_buffer_cap(self):
        for _ in range(105):
            self.scorer.run([make_proto_mp973()], data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_run_returns_result(self):
        result = self.scorer.run([make_proto_mp973()], data_dir=self.tmpdir)
        self.assertIn("protocols", result)

    def test_run_atomic_write_valid_json(self):
        self.scorer.run([make_proto_mp973()], data_dir=self.tmpdir)
        with open(self.log_path) as f:
            content = f.read()
        parsed = json.loads(content)
        self.assertIsInstance(parsed, list)


# edge cases for scorer
class TestProtocolRevenueQualityScorerEdgeCases(unittest.TestCase):

    def setUp(self):
        self.scorer = ProtocolRevenueQualityScorer()

    def test_missing_fields_default_values(self):
        result = self.scorer.score([{}])
        p = result["protocols"][0]
        self.assertEqual(p["name"], "unknown")

    def test_zero_revenue_zero_sustainability(self):
        proto = make_proto_mp973(total_revenue_30d_usd=0.0)
        result = self.scorer.score([proto])
        self.assertAlmostEqual(result["protocols"][0]["sustainability_multiple"], 0.0)

    def test_high_quality_growth_flag(self):
        proto = make_proto_mp973(
            incentive_revenue_pct=5.0,
            unique_revenue_sources_count=5,
            has_recurring_revenue=True,
            revenue_growth_mom_pct=25.0,
        )
        result = self.scorer.score([proto])
        p = result["protocols"][0]
        if p["quality_score"] > 70.0:
            self.assertIn(MP973_FLAG_HIGH_QUALITY_GROWTH, p["flags"])

    def test_stability_score_in_range(self):
        proto = make_proto_mp973()
        result = self.scorer.score([proto])
        s = result["protocols"][0]["revenue_stability_score"]
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_all_fields_preserved_in_output(self):
        proto = make_proto_mp973(
            trading_fee_revenue_pct=50.0,
            liquidation_fee_revenue_pct=15.0,
            protocol_fee_revenue_pct=25.0,
        )
        result = self.scorer.score([proto])
        p = result["protocols"][0]
        self.assertAlmostEqual(p["trading_fee_revenue_pct"], 50.0)
        self.assertAlmostEqual(p["liquidation_fee_revenue_pct"], 15.0)
        self.assertAlmostEqual(p["protocol_fee_revenue_pct"], 25.0)
