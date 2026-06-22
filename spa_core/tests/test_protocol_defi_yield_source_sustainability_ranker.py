"""
Tests for MP-1011 ProtocolDeFiYieldSourceSustainabilityRanker
Run: python3 -m unittest spa_core.tests.test_protocol_defi_yield_source_sustainability_ranker
"""

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup — allow running from repo root
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_yield_source_sustainability_ranker import (
    ProtocolDeFiYieldSourceSustainabilityRanker,
    LABEL_FORTRESS_YIELD,
    LABEL_SUSTAINABLE,
    LABEL_TRANSITIONAL,
    LABEL_EMISSION_DEPENDENT,
    LABEL_UNSUSTAINABLE,
    LABEL_POINTS_SPECULATION,
    FLAG_REAL_YIELD_DOMINANT,
    FLAG_EMISSION_HEAVY,
    FLAG_REVENUE_SURPLUS,
    FLAG_AIRDROP_BOOSTED,
    FLAG_COMPETITIVE_MOAT,
    FLAG_YIELD_DECLINING,
    _apy_stability_score,
    _sustainability_score,
    _classify_source,
    _compute_flags,
)


def _make_source(**kwargs):
    base = {
        "name": "Test-Source",
        "protocol": "TestProtocol",
        "yield_type": "lending_interest",
        "current_apy_pct": 5.0,
        "apy_90d_avg_pct": 5.2,
        "apy_90d_std_pct": 0.3,
        "token_emission_component_pct": 10.0,
        "has_real_revenue_backing": True,
        "revenue_coverage_ratio": 1.5,
        "competitive_advantage": "efficiency",
        "sustainability_horizon_months": 18.0,
    }
    base.update(kwargs)
    return base


class TestApyStabilityScore(unittest.TestCase):
    """Tests for _apy_stability_score helper."""

    def test_zero_std_high_score(self):
        score = _apy_stability_score(0.0, 5.0, 5.0)
        self.assertGreater(score, 80.0)

    def test_high_std_low_score(self):
        # High std AND current far from avg → both components penalized → low score
        # cv = 10/5 = 2.0 → std_score=5; deviation = |0.5-5|/5=0.9 → prox_score=15
        # composite = 5*0.6 + 15*0.4 = 3 + 6 = 9 → well below 30
        score = _apy_stability_score(10.0, 0.5, 5.0)
        self.assertLess(score, 30.0)

    def test_score_in_range_0_100(self):
        for std in [0.0, 0.5, 2.0, 10.0, 50.0]:
            for apy in [1.0, 5.0, 20.0]:
                score = _apy_stability_score(std, apy, apy)
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 100.0)

    def test_current_near_avg_better_score(self):
        close = _apy_stability_score(0.5, 5.0, 5.1)
        far = _apy_stability_score(0.5, 5.0, 10.0)
        self.assertGreater(close, far)

    def test_low_coefficient_variation(self):
        # CV = 0.1/5.0 = 0.02 → low → high score
        score = _apy_stability_score(0.1, 5.0, 5.0)
        self.assertGreater(score, 70.0)

    def test_zero_avg_uses_current(self):
        # Should not raise ZeroDivisionError
        score = _apy_stability_score(1.0, 5.0, 0.0)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_perfect_stability(self):
        score = _apy_stability_score(0.0, 5.0, 5.0)
        self.assertGreater(score, 90.0)


class TestSustainabilityScore(unittest.TestCase):
    """Tests for _sustainability_score helper."""

    def test_high_real_yield_high_coverage_high_score(self):
        score = _sustainability_score(10.0, 3.0, "monopoly", 36.0, 5.0)
        self.assertGreater(score, 80.0)

    def test_zero_real_yield_low_score(self):
        score = _sustainability_score(0.0, 0.0, "none", 0.0, 80.0)
        self.assertLess(score, 20.0)

    def test_score_in_range(self):
        for ry in [0.0, 2.0, 8.0, 15.0]:
            for rc in [0.0, 0.5, 1.0, 3.0]:
                score = _sustainability_score(ry, rc, "none", 12.0, 20.0)
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 100.0)

    def test_emission_penalty_applied_high(self):
        base = _sustainability_score(5.0, 1.5, "efficiency", 18.0, 10.0)
        penalized = _sustainability_score(5.0, 1.5, "efficiency", 18.0, 85.0)
        self.assertGreater(base, penalized)

    def test_monopoly_advantage_boosts_score(self):
        none_score = _sustainability_score(5.0, 1.5, "none", 18.0, 20.0)
        monopoly_score = _sustainability_score(5.0, 1.5, "monopoly", 18.0, 20.0)
        self.assertGreater(monopoly_score, none_score)

    def test_long_horizon_boosts_score(self):
        short = _sustainability_score(5.0, 1.5, "efficiency", 3.0, 20.0)
        long_ = _sustainability_score(5.0, 1.5, "efficiency", 36.0, 20.0)
        self.assertGreater(long_, short)

    def test_revenue_coverage_above_3_boosts(self):
        low = _sustainability_score(5.0, 0.5, "efficiency", 18.0, 20.0)
        high = _sustainability_score(5.0, 3.0, "efficiency", 18.0, 20.0)
        self.assertGreater(high, low)

    def test_heavy_emission_penalty_above_80(self):
        score_80 = _sustainability_score(5.0, 1.5, "efficiency", 18.0, 81.0)
        score_20 = _sustainability_score(5.0, 1.5, "efficiency", 18.0, 20.0)
        self.assertLess(score_80, score_20)


class TestClassifySource(unittest.TestCase):
    """Tests for _classify_source helper."""

    def test_fortress_yield_label(self):
        label = _classify_source(9.0, 85.0, 2.5, 5.0, "lending_interest")
        self.assertEqual(label, LABEL_FORTRESS_YIELD)

    def test_points_speculation_label(self):
        label = _classify_source(10.0, 90.0, 3.0, 5.0, "points_farming")
        self.assertEqual(label, LABEL_POINTS_SPECULATION)

    def test_unsustainable_label(self):
        label = _classify_source(2.0, 40.0, 0.3, 75.0, "liquidity_mining")
        self.assertEqual(label, LABEL_UNSUSTAINABLE)

    def test_emission_dependent_label(self):
        label = _classify_source(2.0, 50.0, 0.8, 65.0, "liquidity_mining")
        self.assertEqual(label, LABEL_EMISSION_DEPENDENT)

    def test_transitional_label_emission_40_to_60(self):
        label = _classify_source(3.0, 60.0, 1.0, 45.0, "staking_rewards")
        self.assertEqual(label, LABEL_TRANSITIONAL)

    def test_sustainable_label(self):
        label = _classify_source(5.0, 70.0, 1.5, 15.0, "trading_fees")
        self.assertEqual(label, LABEL_SUSTAINABLE)

    def test_fortress_requires_all_three_conditions(self):
        # real_yield=9, sustainability=85, coverage=1.5 (NOT > 2) → not FORTRESS
        label = _classify_source(9.0, 85.0, 1.5, 5.0, "lending_interest")
        self.assertNotEqual(label, LABEL_FORTRESS_YIELD)

    def test_fortress_requires_sustainability_above_80(self):
        label = _classify_source(9.0, 79.0, 2.5, 5.0, "lending_interest")
        self.assertNotEqual(label, LABEL_FORTRESS_YIELD)

    def test_points_farming_overrides_other_conditions(self):
        # even if fortress conditions met but yield_type=points
        label = _classify_source(12.0, 95.0, 3.0, 5.0, "points_farming")
        self.assertEqual(label, LABEL_POINTS_SPECULATION)


class TestComputeFlags(unittest.TestCase):
    """Tests for _compute_flags helper."""

    def test_real_yield_dominant_flag(self):
        flags = _compute_flags(15.0, 1.5, "lending_interest", "efficiency", 5.0, 5.0)
        self.assertIn(FLAG_REAL_YIELD_DOMINANT, flags)

    def test_no_real_yield_dominant_above_20(self):
        flags = _compute_flags(25.0, 1.5, "lending_interest", "efficiency", 5.0, 5.0)
        self.assertNotIn(FLAG_REAL_YIELD_DOMINANT, flags)

    def test_emission_heavy_flag(self):
        flags = _compute_flags(70.0, 1.5, "liquidity_mining", "none", 5.0, 5.0)
        self.assertIn(FLAG_EMISSION_HEAVY, flags)

    def test_revenue_surplus_flag(self):
        flags = _compute_flags(15.0, 2.5, "trading_fees", "efficiency", 5.0, 5.0)
        self.assertIn(FLAG_REVENUE_SURPLUS, flags)

    def test_airdrop_boosted_flag(self):
        flags = _compute_flags(15.0, 1.5, "points_farming", "none", 5.0, 5.0)
        self.assertIn(FLAG_AIRDROP_BOOSTED, flags)

    def test_competitive_moat_flag(self):
        flags = _compute_flags(15.0, 1.5, "lending_interest", "network_effect", 5.0, 5.0)
        self.assertIn(FLAG_COMPETITIVE_MOAT, flags)

    def test_no_moat_for_none(self):
        flags = _compute_flags(15.0, 1.5, "lending_interest", "none", 5.0, 5.0)
        self.assertNotIn(FLAG_COMPETITIVE_MOAT, flags)

    def test_yield_declining_flag(self):
        # current = 4.0 < avg_90d * 0.8 = 5.0 * 0.8 = 4.0 → NOT strictly less
        flags = _compute_flags(15.0, 1.5, "lending_interest", "none", 3.9, 5.0)
        self.assertIn(FLAG_YIELD_DECLINING, flags)

    def test_no_yield_declining_when_stable(self):
        flags = _compute_flags(15.0, 1.5, "lending_interest", "none", 5.0, 5.0)
        self.assertNotIn(FLAG_YIELD_DECLINING, flags)

    def test_no_yield_declining_zero_avg(self):
        # avg=0 → skip check
        flags = _compute_flags(15.0, 1.5, "lending_interest", "none", 5.0, 0.0)
        self.assertNotIn(FLAG_YIELD_DECLINING, flags)

    def test_multiple_flags_together(self):
        flags = _compute_flags(15.0, 2.5, "points_farming", "monopoly", 3.9, 5.0)
        self.assertIn(FLAG_REVENUE_SURPLUS, flags)
        self.assertIn(FLAG_AIRDROP_BOOSTED, flags)
        self.assertIn(FLAG_COMPETITIVE_MOAT, flags)
        self.assertIn(FLAG_YIELD_DECLINING, flags)


class TestRanker(unittest.TestCase):
    """Integration tests for ProtocolDeFiYieldSourceSustainabilityRanker.rank()."""

    def setUp(self):
        self.ranker = ProtocolDeFiYieldSourceSustainabilityRanker()
        self.config = {}

    def test_returns_dict(self):
        result = self.ranker.rank([_make_source()], self.config)
        self.assertIsInstance(result, dict)

    def test_status_ok_with_data(self):
        result = self.ranker.rank([_make_source()], self.config)
        self.assertEqual(result["status"], "ok")

    def test_status_no_data_empty_list(self):
        result = self.ranker.rank([], {})
        self.assertEqual(result["status"], "no_data")

    def test_status_no_data_non_list(self):
        result = self.ranker.rank(None, {})
        self.assertEqual(result["status"], "no_data")

    def test_sources_list_present(self):
        result = self.ranker.rank([_make_source()], self.config)
        self.assertIn("sources", result)
        self.assertEqual(len(result["sources"]), 1)

    def test_ranking_list_present(self):
        result = self.ranker.rank([_make_source()], self.config)
        self.assertIn("ranking", result)
        self.assertIsInstance(result["ranking"], list)

    def test_aggregates_present(self):
        result = self.ranker.rank([_make_source()], self.config)
        self.assertIn("aggregates", result)

    def test_timestamp_present(self):
        result = self.ranker.rank([_make_source()], self.config)
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)

    def test_real_yield_computed(self):
        src = _make_source(current_apy_pct=10.0, token_emission_component_pct=20.0)
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        # real_yield = 10 * (1 - 20/100) = 8.0
        self.assertAlmostEqual(source["real_yield_pct"], 8.0, places=3)

    def test_real_yield_zero_emission(self):
        src = _make_source(current_apy_pct=5.0, token_emission_component_pct=0.0)
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertAlmostEqual(source["real_yield_pct"], 5.0, places=3)

    def test_real_yield_full_emission(self):
        src = _make_source(current_apy_pct=50.0, token_emission_component_pct=100.0)
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertAlmostEqual(source["real_yield_pct"], 0.0, places=3)

    def test_sustainability_score_in_range(self):
        result = self.ranker.rank([_make_source()], self.config)
        source = result["sources"][0]
        self.assertGreaterEqual(source["sustainability_score"], 0.0)
        self.assertLessEqual(source["sustainability_score"], 100.0)

    def test_stability_score_in_range(self):
        result = self.ranker.rank([_make_source()], self.config)
        source = result["sources"][0]
        self.assertGreaterEqual(source["apy_stability_score"], 0.0)
        self.assertLessEqual(source["apy_stability_score"], 100.0)

    def test_risk_adjusted_yield_computed(self):
        src = _make_source(current_apy_pct=10.0, token_emission_component_pct=0.0)
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        # risk_adjusted = real_yield * sustainability/100
        expected = round(source["real_yield_pct"] * source["sustainability_score"] / 100.0, 4)
        self.assertAlmostEqual(source["risk_adjusted_yield"], expected, places=4)

    def test_emission_dependency_risk_high(self):
        src = _make_source(token_emission_component_pct=75.0)
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertEqual(source["emission_dependency_risk"], "HIGH")

    def test_emission_dependency_risk_medium(self):
        src = _make_source(token_emission_component_pct=40.0)
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertEqual(source["emission_dependency_risk"], "MEDIUM")

    def test_emission_dependency_risk_low(self):
        src = _make_source(token_emission_component_pct=15.0)
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertEqual(source["emission_dependency_risk"], "LOW")

    def test_label_field_present(self):
        result = self.ranker.rank([_make_source()], self.config)
        source = result["sources"][0]
        self.assertIn("label", source)

    def test_flags_field_is_list(self):
        result = self.ranker.rank([_make_source()], self.config)
        source = result["sources"][0]
        self.assertIsInstance(source["flags"], list)

    def test_fortress_yield_label(self):
        src = _make_source(
            current_apy_pct=20.0,
            token_emission_component_pct=5.0,     # real_yield = 19 > 8
            revenue_coverage_ratio=3.0,
            competitive_advantage="monopoly",
            sustainability_horizon_months=36.0,
        )
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertEqual(source["label"], LABEL_FORTRESS_YIELD)

    def test_points_speculation_label(self):
        src = _make_source(yield_type="points_farming")
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertEqual(source["label"], LABEL_POINTS_SPECULATION)

    def test_unsustainable_label(self):
        src = _make_source(
            current_apy_pct=50.0,
            token_emission_component_pct=80.0,
            revenue_coverage_ratio=0.3,
            competitive_advantage="none",
            sustainability_horizon_months=2.0,
        )
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertEqual(source["label"], LABEL_UNSUSTAINABLE)

    def test_emission_dependent_label(self):
        src = _make_source(
            token_emission_component_pct=65.0,
            revenue_coverage_ratio=0.8,
            competitive_advantage="none",
            sustainability_horizon_months=6.0,
        )
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertEqual(source["label"], LABEL_EMISSION_DEPENDENT)

    def test_real_yield_dominant_flag(self):
        src = _make_source(token_emission_component_pct=10.0)
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertIn(FLAG_REAL_YIELD_DOMINANT, source["flags"])

    def test_emission_heavy_flag(self):
        src = _make_source(token_emission_component_pct=70.0)
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertIn(FLAG_EMISSION_HEAVY, source["flags"])

    def test_revenue_surplus_flag(self):
        src = _make_source(revenue_coverage_ratio=2.5)
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertIn(FLAG_REVENUE_SURPLUS, source["flags"])

    def test_airdrop_boosted_flag(self):
        src = _make_source(yield_type="points_farming")
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertIn(FLAG_AIRDROP_BOOSTED, source["flags"])

    def test_competitive_moat_flag(self):
        src = _make_source(competitive_advantage="network_effect")
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertIn(FLAG_COMPETITIVE_MOAT, source["flags"])

    def test_yield_declining_flag(self):
        src = _make_source(current_apy_pct=3.0, apy_90d_avg_pct=10.0)  # 3 < 10*0.8=8
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertIn(FLAG_YIELD_DECLINING, source["flags"])

    def test_ranking_sorted_descending_by_sustainability(self):
        sources = [
            _make_source(name="Bad", token_emission_component_pct=80.0, revenue_coverage_ratio=0.2,
                         current_apy_pct=5.0, sustainability_horizon_months=2.0),
            _make_source(name="Good", token_emission_component_pct=5.0, revenue_coverage_ratio=3.0,
                         current_apy_pct=10.0, sustainability_horizon_months=36.0,
                         competitive_advantage="monopoly"),
        ]
        result = self.ranker.rank(sources, self.config)
        ranking = result["ranking"]
        self.assertEqual(ranking[0]["name"], "Good")
        self.assertEqual(ranking[1]["name"], "Bad")

    def test_ranking_rank_field(self):
        sources = [_make_source(name=f"S{i}") for i in range(3)]
        result = self.ranker.rank(sources, self.config)
        ranks = [r["rank"] for r in result["ranking"]]
        self.assertEqual(ranks, [1, 2, 3])

    def test_multiple_sources(self):
        sources = [_make_source(name=f"S{i}") for i in range(5)]
        result = self.ranker.rank(sources, self.config)
        self.assertEqual(len(result["sources"]), 5)
        self.assertEqual(len(result["ranking"]), 5)

    def test_name_protocol_preserved(self):
        src = _make_source(name="AaveV3", protocol="Aave")
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertEqual(source["name"], "AaveV3")
        self.assertEqual(source["protocol"], "Aave")

    def test_yield_type_preserved(self):
        src = _make_source(yield_type="trading_fees")
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertEqual(source["yield_type"], "trading_fees")

    def test_has_real_revenue_preserved(self):
        src = _make_source(has_real_revenue_backing=True)
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertTrue(source["has_real_revenue_backing"])

    def test_default_config_works(self):
        result = self.ranker.rank([_make_source()], {})
        self.assertEqual(result["status"], "ok")

    def test_missing_optional_fields_use_defaults(self):
        minimal = {
            "name": "Minimal",
            "yield_type": "lending_interest",
            "current_apy_pct": 5.0,
        }
        result = self.ranker.rank([minimal], {})
        self.assertEqual(result["status"], "ok")

    def test_zero_apy(self):
        src = _make_source(current_apy_pct=0.0, apy_90d_avg_pct=0.0)
        result = self.ranker.rank([src], self.config)
        self.assertEqual(result["status"], "ok")

    def test_very_high_apy_handled(self):
        src = _make_source(current_apy_pct=500.0, token_emission_component_pct=95.0)
        result = self.ranker.rank([src], self.config)
        self.assertEqual(result["status"], "ok")


class TestAggregates(unittest.TestCase):
    """Tests for aggregate computation."""

    def setUp(self):
        self.ranker = ProtocolDeFiYieldSourceSustainabilityRanker()
        self.config = {}

    def test_source_count(self):
        sources = [_make_source(name=f"S{i}") for i in range(4)]
        result = self.ranker.rank(sources, self.config)
        self.assertEqual(result["aggregates"]["source_count"], 4)

    def test_highest_ranked_in_aggregates(self):
        sources = [
            _make_source(name="Good", token_emission_component_pct=5.0, revenue_coverage_ratio=3.0,
                         current_apy_pct=10.0, sustainability_horizon_months=36.0,
                         competitive_advantage="monopoly"),
            _make_source(name="Bad", token_emission_component_pct=80.0, revenue_coverage_ratio=0.2,
                         current_apy_pct=5.0, sustainability_horizon_months=2.0,
                         competitive_advantage="none"),
        ]
        result = self.ranker.rank(sources, self.config)
        agg = result["aggregates"]
        self.assertEqual(agg["highest_ranked"]["name"], "Good")

    def test_lowest_ranked_in_aggregates(self):
        sources = [
            _make_source(name="Good", token_emission_component_pct=5.0, revenue_coverage_ratio=3.0,
                         current_apy_pct=10.0, sustainability_horizon_months=36.0,
                         competitive_advantage="monopoly"),
            _make_source(name="Bad", token_emission_component_pct=80.0, revenue_coverage_ratio=0.2,
                         current_apy_pct=5.0, sustainability_horizon_months=2.0,
                         competitive_advantage="none"),
        ]
        result = self.ranker.rank(sources, self.config)
        agg = result["aggregates"]
        self.assertEqual(agg["lowest_ranked"]["name"], "Bad")

    def test_avg_real_yield(self):
        sources = [
            _make_source(name="S1", current_apy_pct=10.0, token_emission_component_pct=0.0),  # real=10
            _make_source(name="S2", current_apy_pct=6.0, token_emission_component_pct=0.0),   # real=6
        ]
        result = self.ranker.rank(sources, self.config)
        agg = result["aggregates"]
        self.assertAlmostEqual(agg["avg_real_yield_pct"], 8.0, places=3)

    def test_fortress_count(self):
        sources = [
            _make_source(name="F1", current_apy_pct=20.0, token_emission_component_pct=5.0,
                         revenue_coverage_ratio=3.0, competitive_advantage="monopoly",
                         sustainability_horizon_months=36.0),
            _make_source(name="OK", token_emission_component_pct=40.0),
        ]
        result = self.ranker.rank(sources, self.config)
        agg = result["aggregates"]
        self.assertGreaterEqual(agg["fortress_count"], 1)

    def test_unsustainable_count(self):
        sources = [
            _make_source(name="U1", token_emission_component_pct=80.0, revenue_coverage_ratio=0.3,
                         competitive_advantage="none", sustainability_horizon_months=2.0),
            _make_source(name="OK", token_emission_component_pct=10.0, revenue_coverage_ratio=2.0),
        ]
        result = self.ranker.rank(sources, self.config)
        agg = result["aggregates"]
        self.assertGreaterEqual(agg["unsustainable_count"], 1)

    def test_points_speculation_count(self):
        sources = [
            _make_source(name="P1", yield_type="points_farming"),
            _make_source(name="P2", yield_type="points_farming"),
            _make_source(name="OK", yield_type="lending_interest"),
        ]
        result = self.ranker.rank(sources, self.config)
        agg = result["aggregates"]
        self.assertEqual(agg["points_speculation_count"], 2)

    def test_real_yield_dominant_count(self):
        sources = [
            _make_source(name="RY1", token_emission_component_pct=10.0),
            _make_source(name="RY2", token_emission_component_pct=15.0),
            _make_source(name="EM1", token_emission_component_pct=70.0),
        ]
        result = self.ranker.rank(sources, self.config)
        agg = result["aggregates"]
        self.assertEqual(agg["real_yield_dominant_count"], 2)

    def test_single_source_aggregates(self):
        result = self.ranker.rank([_make_source()], self.config)
        agg = result["aggregates"]
        self.assertEqual(
            agg["highest_ranked"]["name"], agg["lowest_ranked"]["name"]
        )

    def test_emission_dependent_count(self):
        sources = [
            _make_source(name="E1", token_emission_component_pct=65.0,
                         revenue_coverage_ratio=0.8, competitive_advantage="none",
                         sustainability_horizon_months=6.0),
            _make_source(name="E2", token_emission_component_pct=70.0,
                         revenue_coverage_ratio=0.85, competitive_advantage="none",
                         sustainability_horizon_months=6.0),
            _make_source(name="OK", token_emission_component_pct=10.0,
                         revenue_coverage_ratio=2.0),
        ]
        result = self.ranker.rank(sources, self.config)
        agg = result["aggregates"]
        self.assertGreaterEqual(agg["emission_dependent_count"], 1)


class TestRingBufferLog(unittest.TestCase):
    """Tests for the ring-buffer log write."""

    def setUp(self):
        self.ranker = ProtocolDeFiYieldSourceSustainabilityRanker()
        self.tmpdir = tempfile.mkdtemp()

    def _patch_log_path(self, path):
        import spa_core.analytics.protocol_defi_yield_source_sustainability_ranker as mod
        mod._LOG_PATH = path

    def _restore_log_path(self):
        import spa_core.analytics.protocol_defi_yield_source_sustainability_ranker as mod
        mod._LOG_PATH = os.path.join(
            os.path.dirname(mod.__file__), "..", "..", "data", "yield_sustainability_rank_log.json"
        )

    def test_log_file_created(self):
        log_path = os.path.join(self.tmpdir, "test_rank_log.json")
        self._patch_log_path(log_path)
        try:
            self.ranker.rank([_make_source()], {})
            self.assertTrue(os.path.exists(log_path))
        finally:
            self._restore_log_path()

    def test_log_is_list(self):
        log_path = os.path.join(self.tmpdir, "test_rank_log2.json")
        self._patch_log_path(log_path)
        try:
            self.ranker.rank([_make_source()], {})
            with open(log_path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
        finally:
            self._restore_log_path()

    def test_log_grows_on_multiple_calls(self):
        log_path = os.path.join(self.tmpdir, "test_rank_log3.json")
        self._patch_log_path(log_path)
        try:
            for _ in range(4):
                self.ranker.rank([_make_source()], {})
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 4)
        finally:
            self._restore_log_path()

    def test_ring_buffer_cap(self):
        import spa_core.analytics.protocol_defi_yield_source_sustainability_ranker as mod
        orig_cap = mod._LOG_CAP
        mod._LOG_CAP = 3
        log_path = os.path.join(self.tmpdir, "test_rank_cap.json")
        self._patch_log_path(log_path)
        try:
            for _ in range(7):
                self.ranker.rank([_make_source()], {})
            with open(log_path) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), 3)
        finally:
            mod._LOG_CAP = orig_cap
            self._restore_log_path()

    def test_log_record_has_ts(self):
        log_path = os.path.join(self.tmpdir, "test_rank_ts.json")
        self._patch_log_path(log_path)
        try:
            self.ranker.rank([_make_source()], {})
            with open(log_path) as f:
                data = json.load(f)
            self.assertIn("ts", data[0])
        finally:
            self._restore_log_path()

    def test_log_record_has_source_count(self):
        log_path = os.path.join(self.tmpdir, "test_rank_sc.json")
        self._patch_log_path(log_path)
        try:
            self.ranker.rank([_make_source(), _make_source(name="S2")], {})
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(data[0]["source_count"], 2)
        finally:
            self._restore_log_path()

    def test_log_record_has_aggregates(self):
        log_path = os.path.join(self.tmpdir, "test_rank_agg.json")
        self._patch_log_path(log_path)
        try:
            self.ranker.rank([_make_source()], {})
            with open(log_path) as f:
                data = json.load(f)
            self.assertIn("aggregates", data[0])
        finally:
            self._restore_log_path()

    def test_atomic_write_no_tmp_left(self):
        log_path = os.path.join(self.tmpdir, "test_rank_atom.json")
        self._patch_log_path(log_path)
        try:
            self.ranker.rank([_make_source()], {})
            self.assertFalse(os.path.exists(log_path + ".tmp"))
        finally:
            self._restore_log_path()

    def test_corrupt_log_recovery(self):
        log_path = os.path.join(self.tmpdir, "test_rank_corrupt.json")
        with open(log_path, "w") as f:
            f.write("{BAD JSON}}}")
        self._patch_log_path(log_path)
        try:
            self.ranker.rank([_make_source()], {})
            with open(log_path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
        finally:
            self._restore_log_path()


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def setUp(self):
        self.ranker = ProtocolDeFiYieldSourceSustainabilityRanker()
        self.config = {}

    def test_zero_revenue_coverage(self):
        src = _make_source(revenue_coverage_ratio=0.0)
        result = self.ranker.rank([src], self.config)
        self.assertEqual(result["status"], "ok")

    def test_very_high_revenue_coverage(self):
        src = _make_source(revenue_coverage_ratio=10.0)
        result = self.ranker.rank([src], self.config)
        self.assertEqual(result["status"], "ok")
        source = result["sources"][0]
        self.assertIn(FLAG_REVENUE_SURPLUS, source["flags"])

    def test_zero_horizon(self):
        src = _make_source(sustainability_horizon_months=0.0)
        result = self.ranker.rank([src], self.config)
        self.assertEqual(result["status"], "ok")

    def test_very_long_horizon(self):
        src = _make_source(sustainability_horizon_months=120.0)
        result = self.ranker.rank([src], self.config)
        self.assertEqual(result["status"], "ok")

    def test_restaking_yield_type(self):
        src = _make_source(yield_type="restaking")
        result = self.ranker.rank([src], self.config)
        self.assertEqual(result["status"], "ok")

    def test_real_world_yield_type(self):
        src = _make_source(yield_type="real_world_yield")
        result = self.ranker.rank([src], self.config)
        self.assertEqual(result["status"], "ok")

    def test_monopoly_advantage(self):
        src = _make_source(competitive_advantage="monopoly")
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertIn(FLAG_COMPETITIVE_MOAT, source["flags"])

    def test_many_sources_ranked_correctly(self):
        sources = [
            _make_source(
                name=f"S{i}",
                token_emission_component_pct=float(i * 10),
                revenue_coverage_ratio=max(0.1, 3.0 - i * 0.3),
                current_apy_pct=float(i + 1),
            )
            for i in range(10)
        ]
        result = self.ranker.rank(sources, self.config)
        self.assertEqual(len(result["ranking"]), 10)

    def test_sustainability_score_high_for_fortress_candidate(self):
        src = _make_source(
            current_apy_pct=20.0,
            token_emission_component_pct=5.0,
            revenue_coverage_ratio=3.0,
            competitive_advantage="monopoly",
            sustainability_horizon_months=36.0,
        )
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertGreater(source["sustainability_score"], 70.0)

    def test_sustainability_score_low_for_unsustainable(self):
        src = _make_source(
            token_emission_component_pct=85.0,
            revenue_coverage_ratio=0.1,
            competitive_advantage="none",
            sustainability_horizon_months=1.0,
        )
        result = self.ranker.rank([src], self.config)
        source = result["sources"][0]
        self.assertLess(source["sustainability_score"], 30.0)


if __name__ == "__main__":
    unittest.main()
