"""
Tests for StrategyComparisonMatrix (MP-721 / SPA-V597).
Run: python3 -m pytest spa_core/tests/test_strategy_comparison_matrix.py -v
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.strategy_comparison_matrix import (
    StrategyComparison,
    StrategyProfile,
    _DIMENSIONS,
    _WEIGHTS,
    _normalize,
    _raw_value,
    load_history,
    save_results,
    score_strategies,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _profile(
    name: str = "TestStrategy",
    apy: float = 5.0,
    real_yield_ratio: float = 0.8,
    risk_score: float = 30.0,
    sustainability_index: float = 60.0,
    liquidity_usd: float = 10_000_000.0,
    min_capital_usd: float = 1_000.0,
    lock_period_days: int = 0,
) -> StrategyProfile:
    return StrategyProfile(
        name=name,
        apy=apy,
        real_yield_ratio=real_yield_ratio,
        risk_score=risk_score,
        sustainability_index=sustainability_index,
        liquidity_usd=liquidity_usd,
        min_capital_usd=min_capital_usd,
        lock_period_days=lock_period_days,
    )


def _three_strategies():
    """Three clearly differentiated strategies for ranking tests."""
    return [
        _profile("HighAPY",   apy=20.0, risk_score=70.0, sustainability_index=40.0,
                 liquidity_usd=1_000_000.0,   min_capital_usd=10_000.0, lock_period_days=30),
        _profile("Balanced",  apy=7.0,  risk_score=30.0, sustainability_index=70.0,
                 liquidity_usd=50_000_000.0,  min_capital_usd=500.0,    lock_period_days=0),
        _profile("SafeLow",   apy=3.0,  risk_score=10.0, sustainability_index=90.0,
                 liquidity_usd=500_000_000.0, min_capital_usd=100.0,    lock_period_days=0),
    ]


# ===========================================================================
# _normalize
# ===========================================================================

class TestNormalize(unittest.TestCase):

    def test_all_same_returns_50(self):
        result = _normalize([5.0, 5.0, 5.0])
        self.assertEqual(result, [50.0, 50.0, 50.0])

    def test_two_values_min_gets_0_max_gets_100(self):
        result = _normalize([0.0, 10.0])
        self.assertAlmostEqual(result[0], 0.0, places=6)
        self.assertAlmostEqual(result[1], 100.0, places=6)

    def test_min_gets_0(self):
        result = _normalize([1.0, 5.0, 10.0])
        self.assertAlmostEqual(result[0], 0.0, places=6)

    def test_max_gets_100(self):
        result = _normalize([1.0, 5.0, 10.0])
        self.assertAlmostEqual(result[-1], 100.0, places=6)

    def test_midpoint_is_midpoint(self):
        # [0, 5, 10] → [0, 50, 100]
        result = _normalize([0.0, 5.0, 10.0])
        self.assertAlmostEqual(result[1], 50.0, places=6)

    def test_three_values_proportional(self):
        result = _normalize([2.0, 4.0, 6.0])
        self.assertAlmostEqual(result[0], 0.0, places=6)
        self.assertAlmostEqual(result[1], 50.0, places=6)
        self.assertAlmostEqual(result[2], 100.0, places=6)

    def test_single_value_returns_50(self):
        result = _normalize([7.0])
        self.assertEqual(result, [50.0])

    def test_two_identical_values_return_50(self):
        result = _normalize([3.0, 3.0])
        self.assertEqual(result, [50.0, 50.0])

    def test_output_length_matches_input(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _normalize(values)
        self.assertEqual(len(result), len(values))

    def test_all_in_range_0_100(self):
        values = [1.0, 7.0, 3.0, 9.0, 2.0]
        result = _normalize(values)
        for v in result:
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 100.0)


# ===========================================================================
# _raw_value
# ===========================================================================

class TestRawValue(unittest.TestCase):

    def test_yield_raw_equals_apy(self):
        p = _profile(apy=8.5)
        self.assertAlmostEqual(_raw_value(p, "YIELD"), 8.5, places=8)

    def test_safety_raw_inverts_risk_score(self):
        p = _profile(risk_score=40.0)
        self.assertAlmostEqual(_raw_value(p, "SAFETY"), 60.0, places=8)

    def test_safety_raw_zero_risk_gives_100(self):
        p = _profile(risk_score=0.0)
        self.assertAlmostEqual(_raw_value(p, "SAFETY"), 100.0, places=8)

    def test_safety_raw_100_risk_gives_0(self):
        p = _profile(risk_score=100.0)
        self.assertAlmostEqual(_raw_value(p, "SAFETY"), 0.0, places=8)

    def test_sustainability_raw_equals_index(self):
        p = _profile(sustainability_index=72.5)
        self.assertAlmostEqual(_raw_value(p, "SUSTAINABILITY"), 72.5, places=8)

    def test_liquidity_uses_log10(self):
        p = _profile(liquidity_usd=1_000_000.0)
        expected = math.log10(1_000_000.0)
        self.assertAlmostEqual(_raw_value(p, "LIQUIDITY"), expected, places=8)

    def test_liquidity_clamps_to_log10_1_for_zero(self):
        p = _profile(liquidity_usd=0.0)
        self.assertAlmostEqual(_raw_value(p, "LIQUIDITY"), 0.0, places=8)  # log10(1)=0

    def test_liquidity_log10_1_equals_0(self):
        p = _profile(liquidity_usd=1.0)
        self.assertAlmostEqual(_raw_value(p, "LIQUIDITY"), 0.0, places=8)

    def test_liquidity_large_value_log_scale(self):
        p_large = _profile(liquidity_usd=1e9)
        p_small = _profile(liquidity_usd=1e3)
        raw_large = _raw_value(p_large, "LIQUIDITY")
        raw_small = _raw_value(p_small, "LIQUIDITY")
        # log10(1e9)=9, log10(1e3)=3
        self.assertAlmostEqual(raw_large, 9.0, places=6)
        self.assertAlmostEqual(raw_small, 3.0, places=6)

    def test_accessibility_no_capital_no_lock(self):
        p = _profile(min_capital_usd=0.0, lock_period_days=0)
        # 100 - min(50,0) - min(50,0) = 100
        self.assertAlmostEqual(_raw_value(p, "ACCESSIBILITY"), 100.0, places=6)

    def test_accessibility_high_capital_capped(self):
        # capital=100000 → min(50, 100)=50; lock=0 → 100-50-0=50
        p = _profile(min_capital_usd=100_000.0, lock_period_days=0)
        self.assertAlmostEqual(_raw_value(p, "ACCESSIBILITY"), 50.0, places=6)

    def test_accessibility_high_lock_capped(self):
        # capital=0; lock=300 → min(50,100)=50 → 100-0-50=50
        p = _profile(min_capital_usd=0.0, lock_period_days=300)
        self.assertAlmostEqual(_raw_value(p, "ACCESSIBILITY"), 50.0, places=6)

    def test_accessibility_max_both_penalties(self):
        # capital=100k, lock=300 → 100-50-50=0
        p = _profile(min_capital_usd=100_000.0, lock_period_days=300)
        self.assertAlmostEqual(_raw_value(p, "ACCESSIBILITY"), 0.0, places=6)

    def test_accessibility_never_negative(self):
        p = _profile(min_capital_usd=999_999.0, lock_period_days=999)
        self.assertGreaterEqual(_raw_value(p, "ACCESSIBILITY"), 0.0)

    def test_accessibility_1k_capital_no_lock(self):
        # 100 - min(50, 1) - 0 = 99
        p = _profile(min_capital_usd=1_000.0, lock_period_days=0)
        self.assertAlmostEqual(_raw_value(p, "ACCESSIBILITY"), 99.0, places=6)

    def test_accessibility_0_capital_30_day_lock(self):
        # 100 - 0 - min(50, 10) = 90
        p = _profile(min_capital_usd=0.0, lock_period_days=30)
        self.assertAlmostEqual(_raw_value(p, "ACCESSIBILITY"), 90.0, places=6)

    def test_accessibility_50k_capital_90_day_lock(self):
        # 100 - min(50,50) - min(50,30) = 100-50-30 = 20
        p = _profile(min_capital_usd=50_000.0, lock_period_days=90)
        self.assertAlmostEqual(_raw_value(p, "ACCESSIBILITY"), 20.0, places=6)


# ===========================================================================
# Dimension weights
# ===========================================================================

class TestWeights(unittest.TestCase):

    def test_weights_sum_to_1(self):
        total = sum(_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=10)

    def test_five_dimensions_present(self):
        self.assertEqual(set(_WEIGHTS.keys()), set(_DIMENSIONS))

    def test_yield_weight(self):
        self.assertAlmostEqual(_WEIGHTS["YIELD"], 0.30, places=8)

    def test_safety_weight(self):
        self.assertAlmostEqual(_WEIGHTS["SAFETY"], 0.25, places=8)

    def test_sustainability_weight(self):
        self.assertAlmostEqual(_WEIGHTS["SUSTAINABILITY"], 0.20, places=8)

    def test_liquidity_weight(self):
        self.assertAlmostEqual(_WEIGHTS["LIQUIDITY"], 0.15, places=8)

    def test_accessibility_weight(self):
        self.assertAlmostEqual(_WEIGHTS["ACCESSIBILITY"], 0.10, places=8)


# ===========================================================================
# score_strategies — structure
# ===========================================================================

class TestScoreStrategiesStructure(unittest.TestCase):

    def test_returns_strategy_comparison(self):
        comp = score_strategies([_profile()])
        self.assertIsInstance(comp, StrategyComparison)

    def test_strategies_preserved(self):
        ps = [_profile("A"), _profile("B")]
        comp = score_strategies(ps)
        self.assertEqual([s.name for s in comp.strategies], ["A", "B"])

    def test_dimension_scores_has_entry_per_strategy(self):
        ps = [_profile("A"), _profile("B"), _profile("C")]
        comp = score_strategies(ps)
        self.assertEqual(set(comp.dimension_scores.keys()), {"A", "B", "C"})

    def test_dimension_scores_list_has_5_entries(self):
        comp = score_strategies([_profile()])
        for name, dsl in comp.dimension_scores.items():
            self.assertEqual(len(dsl), 5)

    def test_all_five_dimensions_in_scores(self):
        comp = score_strategies([_profile()])
        for name, dsl in comp.dimension_scores.items():
            dims = [ds.dimension for ds in dsl]
            self.assertEqual(set(dims), set(_DIMENSIONS))

    def test_composite_scores_keys_match_strategies(self):
        ps = [_profile("X"), _profile("Y")]
        comp = score_strategies(ps)
        self.assertEqual(set(comp.composite_scores.keys()), {"X", "Y"})

    def test_ranked_strategies_length(self):
        ps = _three_strategies()
        comp = score_strategies(ps)
        self.assertEqual(len(comp.ranked_strategies), len(ps))

    def test_ranked_strategies_contain_all_names(self):
        ps = _three_strategies()
        comp = score_strategies(ps)
        self.assertEqual(set(comp.ranked_strategies), {s.name for s in ps})


# ===========================================================================
# score_strategies — normalisation & scoring
# ===========================================================================

class TestScoreStrategiesScoring(unittest.TestCase):

    def test_single_strategy_all_normalized_50(self):
        comp = score_strategies([_profile("Solo")])
        for ds in comp.dimension_scores["Solo"]:
            self.assertAlmostEqual(ds.normalized_score, 50.0, places=6)

    def test_two_identical_strategies_both_50(self):
        p = _profile("A")
        q = _profile("B")
        comp = score_strategies([p, q])
        for name in ["A", "B"]:
            for ds in comp.dimension_scores[name]:
                self.assertAlmostEqual(ds.normalized_score, 50.0, places=6)

    def test_weighted_score_is_normalized_times_weight(self):
        ps = _three_strategies()
        comp = score_strategies(ps)
        for name, dsl in comp.dimension_scores.items():
            for ds in dsl:
                expected = ds.normalized_score * ds.weight
                self.assertAlmostEqual(ds.weighted_score, expected, places=8)

    def test_composite_equals_sum_of_weighted_scores(self):
        ps = _three_strategies()
        comp = score_strategies(ps)
        for name in comp.composite_scores:
            expected = sum(ds.weighted_score for ds in comp.dimension_scores[name])
            self.assertAlmostEqual(comp.composite_scores[name], expected, places=6)

    def test_normalized_scores_in_0_100_range(self):
        ps = _three_strategies()
        comp = score_strategies(ps)
        for name, dsl in comp.dimension_scores.items():
            for ds in dsl:
                with self.subTest(name=name, dim=ds.dimension):
                    self.assertGreaterEqual(ds.normalized_score, 0.0)
                    self.assertLessEqual(ds.normalized_score, 100.0 + 1e-9)

    def test_high_apy_wins_yield_dimension(self):
        high = _profile("High", apy=20.0)
        low  = _profile("Low",  apy=3.0)
        comp = score_strategies([high, low])
        high_norm = next(ds.normalized_score for ds in comp.dimension_scores["High"]
                         if ds.dimension == "YIELD")
        low_norm  = next(ds.normalized_score for ds in comp.dimension_scores["Low"]
                         if ds.dimension == "YIELD")
        self.assertGreater(high_norm, low_norm)

    def test_low_risk_wins_safety_dimension(self):
        safe   = _profile("Safe",   risk_score=5.0)
        risky  = _profile("Risky",  risk_score=90.0)
        comp = score_strategies([safe, risky])
        safe_norm  = next(ds.normalized_score for ds in comp.dimension_scores["Safe"]
                          if ds.dimension == "SAFETY")
        risky_norm = next(ds.normalized_score for ds in comp.dimension_scores["Risky"]
                          if ds.dimension == "SAFETY")
        self.assertGreater(safe_norm, risky_norm)

    def test_high_sustainability_wins_sustainability_dim(self):
        a = _profile("A", sustainability_index=90.0)
        b = _profile("B", sustainability_index=20.0)
        comp = score_strategies([a, b])
        a_norm = next(ds.normalized_score for ds in comp.dimension_scores["A"]
                      if ds.dimension == "SUSTAINABILITY")
        b_norm = next(ds.normalized_score for ds in comp.dimension_scores["B"]
                      if ds.dimension == "SUSTAINABILITY")
        self.assertGreater(a_norm, b_norm)

    def test_high_tvl_wins_liquidity_dim(self):
        deep   = _profile("Deep",    liquidity_usd=1e9)
        shallow= _profile("Shallow", liquidity_usd=1e4)
        comp = score_strategies([deep, shallow])
        deep_norm    = next(ds.normalized_score for ds in comp.dimension_scores["Deep"]
                            if ds.dimension == "LIQUIDITY")
        shallow_norm = next(ds.normalized_score for ds in comp.dimension_scores["Shallow"]
                            if ds.dimension == "LIQUIDITY")
        self.assertGreater(deep_norm, shallow_norm)

    def test_low_lock_wins_accessibility_dim(self):
        unlocked = _profile("Unlocked", lock_period_days=0,  min_capital_usd=100.0)
        locked   = _profile("Locked",   lock_period_days=90, min_capital_usd=50_000.0)
        comp = score_strategies([unlocked, locked])
        u_norm = next(ds.normalized_score for ds in comp.dimension_scores["Unlocked"]
                      if ds.dimension == "ACCESSIBILITY")
        l_norm = next(ds.normalized_score for ds in comp.dimension_scores["Locked"]
                      if ds.dimension == "ACCESSIBILITY")
        self.assertGreater(u_norm, l_norm)


# ===========================================================================
# score_strategies — rankings and recommendations
# ===========================================================================

class TestScoreStrategiesRankings(unittest.TestCase):

    def test_ranked_desc_by_composite(self):
        ps = _three_strategies()
        comp = score_strategies(ps)
        composites = [comp.composite_scores[n] for n in comp.ranked_strategies]
        self.assertEqual(composites, sorted(composites, reverse=True))

    def test_best_overall_is_first_ranked(self):
        ps = _three_strategies()
        comp = score_strategies(ps)
        self.assertEqual(comp.best_overall, comp.ranked_strategies[0])

    def test_best_yield_has_highest_apy(self):
        ps = _three_strategies()
        comp = score_strategies(ps)
        best = comp.best_yield
        for s in ps:
            if s.name != best:
                # best should have equal or higher APY (or at least the highest norm)
                pass
        best_apy = next(s.apy for s in ps if s.name == best)
        max_apy = max(s.apy for s in ps)
        self.assertAlmostEqual(best_apy, max_apy, places=6)

    def test_best_safety_lowest_risk_score(self):
        ps = _three_strategies()
        comp = score_strategies(ps)
        best_risk = next(s.risk_score for s in ps if s.name == comp.best_safety)
        min_risk  = min(s.risk_score for s in ps)
        self.assertAlmostEqual(best_risk, min_risk, places=6)

    def test_best_sustainability_highest_index(self):
        ps = _three_strategies()
        comp = score_strategies(ps)
        best_sus = next(s.sustainability_index for s in ps if s.name == comp.best_sustainability)
        max_sus  = max(s.sustainability_index for s in ps)
        self.assertAlmostEqual(best_sus, max_sus, places=6)

    def test_best_liquidity_highest_tvl(self):
        ps = _three_strategies()
        comp = score_strategies(ps)
        best_liq = next(s.liquidity_usd for s in ps if s.name == comp.best_liquidity)
        max_liq  = max(s.liquidity_usd for s in ps)
        self.assertAlmostEqual(best_liq, max_liq, places=2)

    def test_best_overall_highest_composite(self):
        ps = _three_strategies()
        comp = score_strategies(ps)
        best_comp = comp.composite_scores[comp.best_overall]
        max_comp  = max(comp.composite_scores.values())
        self.assertAlmostEqual(best_comp, max_comp, places=6)

    def test_best_risk_adjusted_formula(self):
        ps = _three_strategies()
        comp = score_strategies(ps)
        expected = max(ps, key=lambda s: s.apy / max(s.risk_score, 0.1)).name
        self.assertEqual(comp.best_risk_adjusted, expected)

    def test_best_risk_adjusted_with_zero_risk_uses_clamp(self):
        p1 = _profile("HighApy",  apy=10.0, risk_score=0.0)
        p2 = _profile("LowApy",   apy=2.0,  risk_score=5.0)
        comp = score_strategies([p1, p2])
        # p1: 10/max(0,0.1)=10/0.1=100; p2: 2/5=0.4 → p1 wins
        self.assertEqual(comp.best_risk_adjusted, "HighApy")

    def test_best_for_small_capital_min_capital_composite_above_50(self):
        # Balanced has low capital and likely high composite
        ps = [
            _profile("Expensive", min_capital_usd=100_000.0, apy=5.0, risk_score=30.0),
            _profile("Cheap",     min_capital_usd=100.0,     apy=4.0, risk_score=25.0),
        ]
        comp = score_strategies(ps)
        eligible = [s for s in ps if comp.composite_scores[s.name] > 50.0]
        if eligible:
            expected = min(eligible, key=lambda s: s.min_capital_usd).name
            self.assertEqual(comp.best_for_small_capital, expected)

    def test_best_for_small_capital_fallback_when_none_above_50(self):
        # Construct a case where no composite exceeds 50 — all strategies same → all get 50
        # Actually equal strategies all get composite=50 (normalized 50 * weights summed)
        # With equal strategies, composite = 50 * sum(weights) = 50, which is NOT > 50.
        p1 = _profile("A")
        p2 = _profile("B")  # identical → all normalized to 50 → composite = 50
        comp = score_strategies([p1, p2])
        # composite = 50 exactly, not > 50 → fallback to ranked_strategies[0]
        if all(v <= 50.0 for v in comp.composite_scores.values()):
            self.assertEqual(comp.best_for_small_capital, comp.ranked_strategies[0])

    def test_best_for_small_capital_multiple_eligible(self):
        ps = [
            _profile("A", min_capital_usd=1_000.0,  apy=8.0, risk_score=20.0, sustainability_index=75.0),
            _profile("B", min_capital_usd=500.0,    apy=6.0, risk_score=25.0, sustainability_index=70.0),
            _profile("C", min_capital_usd=10_000.0, apy=5.0, risk_score=15.0, sustainability_index=80.0),
        ]
        comp = score_strategies(ps)
        eligible = [s for s in ps if comp.composite_scores[s.name] > 50.0]
        if len(eligible) > 1:
            expected = min(eligible, key=lambda s: s.min_capital_usd).name
            self.assertEqual(comp.best_for_small_capital, expected)


# ===========================================================================
# save_results / load_history
# ===========================================================================

class TestSaveLoadHistory(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def _make_comparison(self, prefix: str = "T") -> StrategyComparison:
        return score_strategies([
            _profile(f"{prefix}A", apy=5.0, risk_score=20.0),
            _profile(f"{prefix}B", apy=8.0, risk_score=40.0),
        ])

    def test_save_creates_file(self):
        comp = self._make_comparison()
        path = save_results(comp, data_dir=Path(self.tmp_dir))
        self.assertTrue(os.path.exists(path))

    def test_save_returns_path_with_filename(self):
        comp = self._make_comparison()
        path = save_results(comp, data_dir=Path(self.tmp_dir))
        self.assertIn("strategy_comparison_log.json", path)

    def test_save_sets_saved_to(self):
        comp = self._make_comparison()
        save_results(comp, data_dir=Path(self.tmp_dir))
        self.assertIn("strategy_comparison_log.json", comp.saved_to)

    def test_load_after_save_one_entry(self):
        comp = self._make_comparison()
        save_results(comp, data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        self.assertEqual(len(history), 1)

    def test_round_trip_ranked_strategies(self):
        comp = self._make_comparison()
        save_results(comp, data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        self.assertEqual(history[0]["ranked_strategies"], comp.ranked_strategies)

    def test_round_trip_best_overall(self):
        comp = self._make_comparison()
        save_results(comp, data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        self.assertEqual(history[0]["best_overall"], comp.best_overall)

    def test_round_trip_composite_scores(self):
        comp = self._make_comparison()
        save_results(comp, data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        for name, score in comp.composite_scores.items():
            self.assertAlmostEqual(history[0]["composite_scores"][name], score, places=6)

    def test_save_appends_multiple(self):
        for i in range(5):
            save_results(self._make_comparison(prefix=str(i)),
                         data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        self.assertEqual(len(history), 5)

    def test_ring_buffer_cap_at_100(self):
        for i in range(105):
            save_results(self._make_comparison(prefix=str(i)),
                         data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        self.assertEqual(len(history), 100)

    def test_ring_buffer_removes_oldest(self):
        for i in range(105):
            comp = score_strategies([_profile(f"S{i}")])
            save_results(comp, data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        first_name = history[0]["strategies"][0]["name"]
        self.assertEqual(first_name, "S5")
        last_name = history[-1]["strategies"][0]["name"]
        self.assertEqual(last_name, "S104")

    def test_load_missing_file_returns_empty_list(self):
        history = load_history(data_dir=Path(self.tmp_dir) / "nonexistent")
        self.assertEqual(history, [])

    def test_saved_json_is_valid(self):
        comp = self._make_comparison()
        path = save_results(comp, data_dir=Path(self.tmp_dir))
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_entry_has_timestamp(self):
        comp = self._make_comparison()
        save_results(comp, data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        self.assertIn("timestamp", history[0])

    def test_dimension_scores_serialized(self):
        comp = self._make_comparison()
        save_results(comp, data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        dim_scores = history[0]["dimension_scores"]
        self.assertIsInstance(dim_scores, dict)
        # Each strategy should have 5 dimension scores
        for name, dsl in dim_scores.items():
            self.assertEqual(len(dsl), 5)


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_single_strategy_composite_is_50(self):
        comp = score_strategies([_profile("Solo")])
        # All norms = 50, composite = 50 * sum(weights) = 50 * 1.0 = 50
        self.assertAlmostEqual(comp.composite_scores["Solo"], 50.0, places=6)

    def test_single_strategy_ranked_list_has_one(self):
        comp = score_strategies([_profile("Solo")])
        self.assertEqual(len(comp.ranked_strategies), 1)
        self.assertEqual(comp.ranked_strategies[0], "Solo")

    def test_single_strategy_best_fields_are_strategy_name(self):
        comp = score_strategies([_profile("Solo")])
        for attr in ["best_yield", "best_safety", "best_sustainability",
                     "best_liquidity", "best_accessibility", "best_overall"]:
            self.assertEqual(getattr(comp, attr), "Solo")

    def test_two_identical_strategies_same_composite(self):
        p1 = _profile("A")
        p2 = _profile("B")
        comp = score_strategies([p1, p2])
        self.assertAlmostEqual(
            comp.composite_scores["A"],
            comp.composite_scores["B"],
            places=6,
        )

    def test_dimension_score_weight_matches_global(self):
        comp = score_strategies([_profile("X"), _profile("Y")])
        for name, dsl in comp.dimension_scores.items():
            for ds in dsl:
                self.assertAlmostEqual(ds.weight, _WEIGHTS[ds.dimension], places=8)

    def test_no_exception_for_zero_liquidity(self):
        p = _profile(liquidity_usd=0.0)
        comp = score_strategies([p, _profile("Other", liquidity_usd=1e6)])
        self.assertIsNotNone(comp)

    def test_no_exception_for_zero_risk_score(self):
        p = _profile(risk_score=0.0)
        comp = score_strategies([p])
        self.assertIsNotNone(comp)


if __name__ == "__main__":
    unittest.main()
